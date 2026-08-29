"""Candles from the trading terminal, for the instruments nothing else carries.

`BrokerQuotes` gave synthetics a live price and that turned out to be half of
what they need. `structures` builds levels from **bars**, so an instrument with
quotes and no candles produces no level, no signal and no trade - it simply
sits there quoting. Nine synthetics collected 1,271 quotes each and zero bars,
which reads as a slow warm-up and is not one.

This is the other half. Same bridge, same symbols, the `rates` endpoint rather
than `ticks`.

## Two things the bridge does differently from itself

**Times arrive as ISO strings here and epoch seconds on the tick endpoint** -
`2026-08-07T15:00:00` against `1787949898`. Both are the broker's server clock,
which is UTC on this account: Wall Street 30's last Friday bar opens 20:45 and
its last tick was 20:44:58.

**A symbol must be selected before it returns anything**, exactly as for
quotes: an unselected symbol answers `200` with an empty list rather than an
error. `prepare` selects them, and skipping it would poll happily and store
nothing.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any, ClassVar

from ..logging import get_logger
from .config import BROKER, Feed, Settings
from .models import Bar, Symbol, WriteResult
from .source import BarSink, Job, PermanentError, Source, TransientError

log = get_logger(__name__)

#: Our interval names to the bridge's timeframe codes. Anything absent is not
#: served rather than silently substituted - a 3m candle built from 1m bars is
#: a different series and must not land in the same place.
TIMEFRAMES: dict[str, str] = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1h": "H1",
    "2h": "H2",
    "4h": "H4",
    "1d": "D1",
    "1w": "W1",
}


def bar_time(raw: Any) -> float:
    """A bar's open time as epoch seconds, from either form the bridge sends."""
    if isinstance(raw, int | float):
        return float(raw)
    if not isinstance(raw, str) or not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=UTC).timestamp()
    except ValueError:
        return 0.0


def parse(rows: Any) -> list[Bar]:
    """Bars from one `rates` response, oldest first."""
    if not isinstance(rows, list):
        return []
    out: list[Bar] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        when = bar_time(row.get("time"))
        if not when:
            continue
        try:
            out.append(
                Bar(
                    time=int(when),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("tick_volume") or row.get("real_volume") or 0.0),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda bar: bar.time)
    return out


class BrokerSource(Source):
    """Candles from the terminal, over the MT5 bridge."""

    name: ClassVar[str] = BROKER

    #: Read from the same variables the trading service uses, so one bridge is
    #: configured once. A deployment that can trade can collect.
    URL_VAR: ClassVar[str] = "TRADING_MT5_URL"
    KEY_VAR: ClassVar[str] = "TRADING_MT5_API_KEY"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client: Any = None
        self._selected: set[str] = set()

    @property
    def concurrency(self) -> int:
        # One terminal behind one bridge. Six parallel sweeps against it is not
        # six times the throughput, it is a queue with extra steps.
        return 3

    def symbols(self, feed: Feed) -> tuple[Symbol, ...]:
        return feed.for_source(self.name)

    def supported(self, intervals):
        return tuple(i for i in intervals if i.name in TIMEFRAMES)

    async def __aenter__(self):
        import httpx

        url = os.environ.get(self.URL_VAR, "")
        if not url:
            raise PermanentError(
                f"{self.name} candles need {self.URL_VAR} - there is no bridge to read"
            )
        headers = {"Accept": "application/json"}
        key = os.environ.get(self.KEY_VAR, "")
        if key:
            headers["X-API-Key"] = key
        self._client = httpx.AsyncClient(base_url=url, headers=headers, timeout=30.0)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _select(self, symbol: Symbol) -> None:
        """Put the symbol in Market Watch. Once per session, not per sweep.

        Not optional and silent when skipped: an unselected symbol answers 200
        with an empty list, which is indistinguishable from a quiet market.
        """
        if symbol.ticker in self._selected or self._client is None:
            return
        self._selected.add(symbol.ticker)
        try:
            await self._client.post(f"/api/v1/symbols/select/{symbol.ticker}")
        except Exception as exc:  # httpx raises a family of transport errors
            log.warning("%s could not select %s: %s", self.name, symbol.full, exc)

    async def fetch(self, job: Job, bars: int, sink: BarSink) -> WriteResult:
        total = WriteResult()
        if self._client is None:
            return total
        await self._select(job.symbol)

        for interval in job.intervals:
            code = TIMEFRAMES.get(interval.name)
            if code is None:
                continue
            try:
                response = await self._client.get(
                    "/api/v1/symbols/rates/pos",
                    params={
                        "symbol": job.symbol.ticker,
                        "timeframe": code,
                        "num_bars": max(2, bars),
                    },
                )
            except Exception as exc:  # transport, not data
                raise TransientError(f"{job.symbol.full} {interval.name}: {exc}") from exc
            if response.status_code != 200:
                log.warning(
                    "skipping %s %s: HTTP %s",
                    job.symbol.full,
                    interval.name,
                    response.status_code,
                )
                continue
            try:
                candles = parse(response.json())
            except ValueError:
                log.warning("skipping %s %s: not JSON", job.symbol.full, interval.name)
                continue
            if not candles:
                log.debug("%s %s: no candles", job.symbol.full, interval.name)
                continue
            total += await sink(job.key(interval), self.keep(candles, interval))
            await asyncio.sleep(0)
        return total
