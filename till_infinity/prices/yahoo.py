"""Yahoo Finance candles via yfinance.

yfinance is synchronous and does its own HTTP, so every call is pushed onto a
worker thread and the sweep stays async end to end.

Two Yahoo quirks are handled here rather than leaking into the rest of the
package: history depth is capped per interval (a minute bar older than a week
simply does not exist), and there are no 2h/4h candles - those are resampled
from 1h so both sources cover the same grid.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Self

from ..logging import get_logger
from .models import Bar, Interval, WriteResult
from .source import BarSink, Job, PermanentError, Source, TransientError

if TYPE_CHECKING:  # pragma: no cover - import cost stays out of the CLI path
    import pandas as pd

log = get_logger(__name__)

#: Canonical interval -> Yahoo interval string.
INTERVAL_CODES: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "1d": "1d",
    "1w": "1wk",
}

#: Intervals Yahoo does not serve, rebuilt from a finer one. Yahoo offers 2m
#: but not 3m, so this one comes off the 1m series - which caps its history at
#: Yahoo's 7-day 1m window, unlike the venues that serve 3m directly.
RESAMPLE_FROM: dict[str, str] = {"2h": "1h", "4h": "1h", "3m": "1m"}

#: How far back Yahoo will go per interval, in days (None = unlimited).
MAX_LOOKBACK_DAYS: dict[str, int | None] = {
    "1m": 7,
    "5m": 59,
    "15m": 59,
    "30m": 59,
    "1h": 729,
    "1d": None,
    "1w": None,
}

#: Bars are sparse (weekends, holidays, half days) so ask for a wider window.
_SLACK = 1.8

_COLUMNS = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def start_time(interval: Interval, bars: int, *, now: datetime | None = None) -> datetime:
    """Earliest timestamp worth asking for, clamped to Yahoo's retention."""
    now = now or datetime.now(UTC)
    span = timedelta(seconds=interval.seconds * max(bars, 1) * _SLACK)
    cap = MAX_LOOKBACK_DAYS.get(interval.name)
    if cap is not None:
        span = min(span, timedelta(days=cap))
    return now - span


def to_bars(frame: pd.DataFrame) -> list[Bar]:
    """Convert a yfinance frame to bars with UTC epoch open times."""
    if frame is None or frame.empty:
        return []
    index = frame.index
    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    bars: list[Bar] = []
    for stamp, row in zip(index, frame.itertuples(index=False), strict=True):
        values = row._asdict()
        try:
            bar = Bar(
                time=int(stamp.timestamp()),
                open=float(values["Open"]),
                high=float(values["High"]),
                low=float(values["Low"]),
                close=float(values["Close"]),
                volume=_optional_float(values.get("Volume")),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isnan(bar.open):  # drop NaN rows
            bars.append(bar)
    return bars


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def resample(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate finer candles onto a coarser UTC-aligned grid."""
    index = frame.index
    frame = frame.copy()
    frame.index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    columns = {name: how for name, how in _COLUMNS.items() if name in frame.columns}
    out = frame.resample(rule, label="left", closed="left", origin="epoch").agg(columns)
    return out.dropna(subset=["Open"])


class YahooSource(Source):
    """Candles from Yahoo Finance."""

    name = "yahoo"

    @property
    def concurrency(self) -> int:
        return self.settings.yahoo_concurrency

    def supported(self, intervals: Sequence[Interval]) -> tuple[Interval, ...]:
        return tuple(i for i in intervals if i.name in INTERVAL_CODES or i.name in RESAMPLE_FROM)

    async def __aenter__(self) -> Self:
        # Imported lazily: yfinance drags in pandas and costs ~1s of startup.
        import yfinance  # noqa: F401

        return self

    async def fetch(self, job: Job, bars: int, sink: BarSink) -> WriteResult:
        total = WriteResult()
        cache: dict[str, pd.DataFrame] = {}
        for interval in job.intervals:
            try:
                candles = await self._series(job.symbol.ticker, interval, bars, cache)
            except PermanentError as exc:
                log.warning("skipping %s %s: %s", job.symbol.full, interval.name, exc)
                continue
            total += await sink(job.key(interval), self.keep(candles, interval))
            await asyncio.sleep(self.settings.yahoo_request_gap)
        return total

    async def _series(
        self,
        ticker: str,
        interval: Interval,
        bars: int,
        cache: dict[str, pd.DataFrame],
    ) -> list[Bar]:
        source_name = RESAMPLE_FROM.get(interval.name, interval.name)
        code = INTERVAL_CODES.get(source_name)
        if code is None:
            raise PermanentError(f"Yahoo has no {interval.name} candles")

        # 2h and 4h both derive from the same 1h pull - download it once.
        frame = cache.get(code)
        if frame is None:
            frame = await asyncio.to_thread(
                self._download, ticker, code, start_time(interval, bars)
            )
            cache[code] = frame

        # Off the event loop, like the download above and for a better reason.
        # The download at least waits on a socket; these two are pure work.
        # `resample` is pandas over the whole frame and `to_bars` is a Python
        # loop over every row of it, building a dict per row - tens of thousands
        # of iterations for a 1m backfill, none of which yields.
        #
        # Everything here runs in one process on two cores - bus, journal,
        # notifications, agents, structures, prices, news - so for as long as
        # this ran, the structures consumer was not scheduled at all. Its queue
        # filled and the bus dropped quotes at eight a second, and since a
        # backfill runs on every startup, every deploy took the level pipeline
        # down for as long as the backfill lasted rather than for as long as
        # the restart did.
        #
        # A thread does not dodge the GIL for the row loop, but it does turn
        # "blocked until finished" into "interleaved every few milliseconds",
        # which is the difference that matters to a consumer being starved.
        return await asyncio.to_thread(self._shape, frame, source_name, interval.name, bars)

    @staticmethod
    def _shape(frame: pd.DataFrame, source_name: str, interval_name: str, bars: int) -> list[Bar]:
        """Resample and convert. Pure CPU, so it is called in a thread.

        Only the rows that are going to be kept are converted. This used to
        convert the whole frame and then discard all but the last `bars` of it,
        which for a week of 1m candles is ten thousand rows built into `Bar`
        objects to keep five hundred.

        The slice cannot simply be taken first, which is why it was left alone
        the first time: `to_bars` drops rows with a NaN open, so the last
        `bars` *rows* are not the last `bars` *bars*, and the count would
        quietly come up short. Dropping them in pandas first - the same
        condition, applied where it is cheap - makes the two equivalent.

        A row whose open is present but not a number is still dropped by
        `to_bars` alone, so the trimmed result can be short. That is rare
        enough to be worth a second pass rather than a wider margin, and
        converting the rest is what the old code did anyway.
        """
        if source_name != interval_name:
            frame = resample(frame, interval_name)
        if "Open" not in getattr(frame, "columns", ()):
            return []
        usable = frame.dropna(subset=["Open"])
        trimmed = to_bars(usable.tail(bars))
        if len(trimmed) < bars and len(usable) > bars:
            return to_bars(usable)[-bars:]
        return trimmed

    def _download(self, ticker: str, code: str, start: datetime) -> pd.DataFrame:
        import yfinance as yf

        try:
            return yf.Ticker(ticker).history(
                start=start,
                end=datetime.now(UTC),
                interval=code,
                auto_adjust=False,
                actions=False,
                raise_errors=True,
            )
        except Exception as exc:  # yfinance raises a grab bag of types
            text = str(exc).lower()
            if "no data" in text or "delisted" in text or "not found" in text:
                raise PermanentError(f"{ticker} {code}: {exc}") from exc
            raise TransientError(f"{ticker} {code}: {exc}") from exc
