"""Candles from any exchange ccxt speaks to, on a filtered set of pairs.

## Why a filter is the point, not an afterthought

A large exchange lists thousands of pairs. Collecting all of them is what
freqtrade's pairlist handlers exist to avoid, and their reasoning applies here
with more force: this desk already carries 53 feeds across nine timeframes and
has been OOM-killed for less. The filters below follow the concepts those
handlers are documented as using - rank by volume, then discard what cannot be
traded properly - reimplemented here rather than copied, since freqtrade is not
a dependency of this project.

The order matters and is the same as theirs: **rank first, then reject.**
Ranking a filtered list would let a single strict filter change which pairs are
even considered, so the volume ranking is taken from the full board and the
rejections are applied to the ranked head.

## What each filter is for

* **volume** - a pair nobody trades has a price that means nothing. Ranked on
  quote volume, not base, so a $10 coin and a $60,000 one compare.
* **age** - a pair listed last week has no history to learn a level from, and
  this system's models need touches before they say anything.
* **spread** - the cost to cross. research/paying.md measures the same thing
  for the broker's instruments and finds it decides more than direction does.
* **price floor** - a coin priced at 0.00000012 has three significant figures
  of tick granularity, so a "level" on it is an artefact of rounding.
* **range** - a pair that has not moved in a fortnight cannot be traded even
  when the model is right.

Every threshold is off by default. A filter with a number nobody chose is a
filter that will one day silently empty the board.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Self

from ..logging import get_logger
from .models import Bar, Interval, Symbol
from .source import Job, PermanentError, Source, TransientError

log = get_logger(__name__)

#: ccxt speaks these directly; anything else has to be resampled and is not
#: served rather than guessed at.
TIMEFRAMES: dict[str, str] = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
}


@dataclass(frozen=True, slots=True)
class Board:
    """One pair as the exchange currently describes it."""

    symbol: str
    quote_volume: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    listed_days: float = 0.0
    range_share: float = 0.0

    @property
    def spread_share(self) -> float:
        """Spread as a fraction of the mid, or 0 when it cannot be computed."""
        if self.bid <= 0 or self.ask <= 0:
            return 0.0
        mid = (self.bid + self.ask) / 2
        return (self.ask - self.bid) / mid if mid > 0 else 0.0


@dataclass(frozen=True, slots=True)
class Filters:
    """Thresholds for choosing which pairs are worth carrying.

    Every one is **off at zero**, and zero is the default. A pairlist filter
    with a number nobody chose is one that will eventually empty the board on a
    quiet day and leave the desk with nothing, which is worse than collecting
    too much.
    """

    #: How many pairs to keep, after ranking by quote volume. Zero keeps all.
    top: int = 0
    #: Minimum 24h quote volume, in the quote currency.
    min_volume: float = 0.0
    #: Minimum days since listing.
    min_days: float = 0.0
    #: Maximum spread as a fraction of the mid - 0.001 is ten basis points.
    max_spread: float = 0.0
    #: Minimum last price, against tick-granularity artefacts.
    min_price: float = 0.0
    #: Minimum recent range as a fraction of price, against dead pairs.
    min_range: float = 0.0
    #: Quote currencies to consider at all.
    quotes: tuple[str, ...] = ()
    #: Keep only perpetuals, dropping dated futures and anything else the
    #: exchange lists alongside them. A dated contract expires, and a level
    #: learned on one dies with it.
    swaps_only: bool = False

    def choose(self, board: Sequence[Board]) -> tuple[list[Board], dict[str, int]]:
        """The pairs worth carrying, and a tally of why the rest were dropped.

        The tally is returned rather than logged so the caller decides whether
        anyone should hear about it - and so "the board came back empty" is
        always answerable, which is the failure this shape exists to prevent.
        """
        dropped: dict[str, int] = {}

        def reject(reason: str) -> None:
            dropped[reason] = dropped.get(reason, 0) + 1

        wanted = list(board)
        if self.swaps_only:
            keep = []
            for pair in wanted:
                # ccxt spells a perpetual `BASE/QUOTE:SETTLE`; a dated future
                # carries an expiry in the id instead.
                if ":" in pair.symbol and not any(c.isdigit() for c in pair.symbol.split(":")[-1]):
                    keep.append(pair)
                else:
                    reject("not a perpetual")
            wanted = keep
        if self.quotes:
            keep = []
            for pair in wanted:
                quote = pair.symbol.split("/")[-1].split(":")[0].upper()
                if quote in self.quotes:
                    keep.append(pair)
                else:
                    reject("quote currency")
            wanted = keep

        # Rank on the full board, then reject. Ranking a filtered list would
        # let one strict threshold change which pairs are even considered.
        wanted.sort(key=lambda p: p.quote_volume, reverse=True)
        if self.top > 0:
            cut = wanted[self.top :]
            for _ in cut:
                reject("outside the volume ranking")
            wanted = wanted[: self.top]

        kept = []
        for pair in wanted:
            why = self._rejects(pair)
            if why:
                reject(why)
            else:
                kept.append(pair)
        return kept, dropped

    def _rejects(self, pair: Board) -> str:
        """Why this pair is not worth carrying, or "".

        A zero threshold is off, and a zero *reading* is unknown rather than
        failing - an exchange that does not report a listing date should not
        cost a pair its place, which is why each test also requires the value
        to be positive.
        """
        if self.min_volume > 0 and pair.quote_volume < self.min_volume:
            return "too little volume"
        if self.min_days > 0 and 0 < pair.listed_days < self.min_days:
            return "listed too recently"
        if self.max_spread > 0 and pair.spread_share > self.max_spread:
            return "spread too wide"
        if self.min_price > 0 and 0 < pair.last < self.min_price:
            return "priced below the tick floor"
        if self.min_range > 0 and 0 < pair.range_share < self.min_range:
            return "range too small to trade"
        return ""


class CcxtSource(Source):
    """Candles from a ccxt exchange.

    One exchange per instance, named by `PRICES_CCXT_EXCHANGE`. The pair set is
    either given explicitly - in which case the filters are not consulted, and
    a named pair is always carried - or discovered from the exchange's tickers
    and filtered.
    """

    name: ClassVar[str] = "ccxt"

    def __init__(self, settings: Any) -> None:
        super().__init__(settings)
        self._exchange: Any = None

    @property
    def concurrency(self) -> int:
        # One exchange, one rate limit. ccxt's own throttle serialises anyway,
        # so more workers buy queueing rather than throughput.
        return 2

    def supported(self, intervals: Sequence[Interval]) -> tuple[Interval, ...]:
        return tuple(i for i in intervals if i.name in TIMEFRAMES)

    async def __aenter__(self) -> Self:
        try:
            import ccxt.async_support as ccxt
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise PermanentError(
                "ccxt is not installed; add it or drop 'ccxt' from PRICES_SOURCES"
            ) from exc
        name = getattr(self.settings, "ccxt_exchange", "") or "binance"
        maker = getattr(ccxt, name, None)
        if maker is None:
            raise PermanentError(f"ccxt has no exchange called {name!r}")
        # `enableRateLimit` is the whole reason to let ccxt own the throttle:
        # it knows each exchange's published limit and this does not.
        #
        # `defaultType` picks spot against perpetual swaps, and it is not a
        # detail. **Swaps are what this desk can actually trade**: they have
        # positions with a size and a side, which is the model `trading` is
        # built around, where spot has balances and no such thing as a short.
        # Collecting spot candles and trading swaps would also mean learning
        # levels on a different instrument from the one being traded - the
        # basis between them is small but the liquidations that move a
        # perpetual do not exist on spot at all.
        kind = (getattr(self.settings, "ccxt_market_type", "") or "swap").strip()
        self._exchange = maker({"enableRateLimit": True, "options": {"defaultType": kind}})
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._exchange is not None:
            await self._exchange.close()
            self._exchange = None

    async def board(self) -> list[Board]:
        """Every pair the exchange lists, as the filters want to see it."""
        if self._exchange is None:
            raise PermanentError("the exchange is not open")
        tickers = await self._exchange.fetch_tickers()
        out = []
        for symbol, row in tickers.items():
            if not isinstance(row, dict):
                continue
            high, low = row.get("high") or 0.0, row.get("low") or 0.0
            last = float(row.get("last") or 0.0)
            out.append(
                Board(
                    symbol=str(symbol),
                    quote_volume=float(row.get("quoteVolume") or 0.0),
                    bid=float(row.get("bid") or 0.0),
                    ask=float(row.get("ask") or 0.0),
                    last=last,
                    # The day's range as a share of price, which is the cheap
                    # version of freqtrade's range-stability idea: a pair that
                    # did not move today is unlikely to be worth watching.
                    range_share=((high - low) / last) if last > 0 and high > low else 0.0,
                )
            )
        return out

    async def fetch(self, job: Job, bars: int, sink: Any) -> Any:
        from .models import WriteResult

        if self._exchange is None:
            raise PermanentError("the exchange is not open")
        total = WriteResult()
        for interval in job.intervals:
            code = TIMEFRAMES.get(interval.name)
            if code is None:
                continue
            try:
                candles = await self._exchange.fetch_ohlcv(
                    job.symbol.ticker, timeframe=code, limit=bars
                )
            except Exception as exc:  # ccxt raises a wide family
                # Transient: a rate limit or a dropped socket should be retried
                # by the caller rather than disabling the pair for the run.
                raise TransientError(f"{job.symbol.full} {interval.name}: {exc}") from exc
            got = [
                Bar(
                    time=int(row[0] // 1000),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]) if len(row) > 5 and row[5] is not None else None,
                )
                for row in candles
                if isinstance(row, list | tuple) and len(row) >= 5
            ]
            total += await sink(job.key(interval), self.keep(got, interval))
            await asyncio.sleep(0)
        return total


def pairs_for(board: Sequence[Board], filters: Filters) -> tuple[Symbol, ...]:
    """The chosen pairs as `Symbol`s, venue-tagged by exchange name upstream."""
    kept, dropped = filters.choose(board)
    if dropped:
        log.info("prices: ccxt board %d kept, dropped %s", len(kept), dropped)
    return tuple(Symbol("CCXT", pair.symbol) for pair in kept)
