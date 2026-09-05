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
import time
from collections import defaultdict
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
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
        #: exchange name -> the open ccxt client.
        self._exchanges: dict[str, Any] = {}

    @property
    def concurrency(self) -> int:
        # Two per exchange. Each has its own rate limit and ccxt's throttle
        # serialises *within* one, so workers beyond that buy queueing rather
        # than throughput - but a second exchange is a second budget, and
        # sharing one pair of workers across them would leave both idle in
        # turn.
        return max(2, 2 * len(exchange_names(self.settings)))

    def supported(self, intervals: Sequence[Interval]) -> tuple[Interval, ...]:
        return tuple(i for i in intervals if i.name in TIMEFRAMES)

    async def __aenter__(self) -> Self:
        try:
            import ccxt.async_support as ccxt
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise PermanentError(
                "ccxt is not installed; add it or drop 'ccxt' from PRICES_SOURCES"
            ) from exc
        wanted = exchange_names(self.settings)
        makers = {}
        for name in wanted:
            maker = getattr(ccxt, name, None)
            if maker is None:
                raise PermanentError(f"ccxt has no exchange called {name!r}")
            makers[name] = maker
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
        for name, maker in makers.items():
            self._exchanges[name] = maker(
                {"enableRateLimit": True, "options": {"defaultType": kind}}
            )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        for exchange in self._exchanges.values():
            with suppress(Exception):
                await exchange.close()
        self._exchanges.clear()

    def _pick(self, name: str) -> Any:
        """The open client for this exchange, by name or by being the only one."""
        if not self._exchanges:
            raise PermanentError("no ccxt exchange is open")
        wanted = (name or "").lower()
        got = self._exchanges.get(wanted)
        if got is not None:
            return got
        if not wanted or len(self._exchanges) == 1:
            return next(iter(self._exchanges.values()))
        raise PermanentError(f"ccxt exchange {name!r} is not open")

    async def _top_of_book(self, exchange: Any) -> dict[str, tuple[float, float]]:
        """Bid and ask per symbol, from the book rather than the day summary.

        **`fetch_tickers` does not carry them here.** Binance answers it from
        the 24h statistics endpoint, which has no top of book: all 762 swap
        rows came back `bid=0, ask=0`, and since `spread_share` reports 0.0
        when it cannot be computed, `max_spread` could not reject a single
        pair at any threshold - 1e-9 dropped none of them. The filter was
        decorative. `fetch_bids_asks` is the bookTicker endpoint and returns
        all 762 populated.

        Best-effort: an exchange without it keeps the old behaviour, where an
        unknown spread costs a pair nothing.
        """
        if not exchange.has.get("fetchBidsAsks"):
            return {}
        try:
            rows = await exchange.fetch_bids_asks()
        except Exception as exc:  # a missing spread must not cost us the board
            log.info("prices: ccxt could not fetch top of book: %s", exc)
            return {}
        out: dict[str, tuple[float, float]] = {}
        for symbol, row in rows.items():
            if isinstance(row, dict):
                out[str(symbol)] = (float(row.get("bid") or 0.0), float(row.get("ask") or 0.0))
        return out

    async def _markets(self, exchange: Any) -> dict[str, tuple[float, float]]:
        """Per symbol: when it was created, and how much base one contract is.

        Two fields from one call. `created` fills `listed_days`, which was
        never assigned anywhere in this module - the field existed, defaulted
        to 0.0, and `min_days` was written to skip a zero reading, so a
        10,000-day threshold rejected nothing.

        `contractSize` is here because **okx reports no `quoteVolume` at all**
        - None on all 470 of its swaps - so `min_volume` rejected every pair it
        listed and one of the largest perpetual venues contributed nothing to
        the board, silently. Its `baseVolume` is in *contracts*, and a contract
        is not a coin: BTC-USDT-SWAP is 0.01 BTC, so multiplying the raw count
        by the price overstates the notional a hundredfold. This is the same
        unit trap `positioning.py` documents for open interest, on a different
        field.
        """
        try:
            markets = await exchange.load_markets()
        except Exception as exc:
            log.info("prices: ccxt could not load markets: %s", exc)
            return {}
        out: dict[str, tuple[float, float]] = {}
        for symbol, market in markets.items():
            if not isinstance(market, dict):
                continue
            size = market.get("contractSize")
            out[str(symbol)] = (
                float(market.get("created") or 0.0),
                float(size) if isinstance(size, int | float) and size > 0 else 1.0,
            )
        return out

    async def board(self, exchange_name: str = "") -> list[Board]:
        """Every pair one exchange lists, as the filters want to see it.

        Named rather than assumed: with several exchanges open, "the board" is
        not a thing - each has its own, and they are ranked against each other
        by `discover_ccxt`.
        """
        exchange = self._pick(exchange_name)
        tickers = await exchange.fetch_tickers()
        # Both are needed because `fetch_tickers` carries neither, and a filter
        # reading a field nothing populates is off however it is configured.
        book = await self._top_of_book(exchange)
        markets = await self._markets(exchange)
        now = time.time() * 1000.0
        out = []
        for symbol, row in tickers.items():
            if not isinstance(row, dict):
                continue
            high, low = row.get("high") or 0.0, row.get("low") or 0.0
            last = float(row.get("last") or 0.0)
            bid, ask = book.get(str(symbol), (0.0, 0.0))
            created, contract = markets.get(str(symbol), (0.0, 1.0))
            # Built from base volume where the exchange gives no quote volume,
            # through the contract size - without which okx is excluded from
            # its own board.
            turnover = float(row.get("quoteVolume") or 0.0)
            if turnover <= 0:
                base = float(row.get("baseVolume") or 0.0)
                turnover = base * contract * last if base > 0 and last > 0 else 0.0
            out.append(
                Board(
                    symbol=str(symbol),
                    quote_volume=turnover,
                    bid=bid or float(row.get("bid") or 0.0),
                    ask=ask or float(row.get("ask") or 0.0),
                    listed_days=(now - created) / 86_400_000.0 if created > 0 else 0.0,
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

        # The venue on the job names which exchange to ask. A pair carried by
        # three of them is one feed with three symbols, exactly as a
        # TradingView instrument is - and the consensus layer downstream is
        # what makes that worth doing.
        exchange = self._pick(job.symbol.venue)
        total = WriteResult()
        # What *this* exchange offers, not what ccxt names in general.
        #
        # `supported` filters against `TIMEFRAMES`, which is one map for every
        # venue - so with several open, every 3m job went to mexc, which does
        # not carry 3m, and came back `{"code":600,"message":"Parameter
        # error"}`. One warning per pair per cycle, and a request spent to
        # earn it. The client knows its own list without a network call.
        offers = getattr(exchange, "timeframes", None) or {}
        for interval in job.intervals:
            code = TIMEFRAMES.get(interval.name)
            if code is None:
                continue
            if offers and code not in offers:
                log.debug(
                    "prices: %s does not carry %s, skipping %s",
                    job.symbol.venue,
                    interval.name,
                    job.symbol.ticker,
                )
                continue
            try:
                candles = await exchange.fetch_ohlcv(job.symbol.ticker, timeframe=code, limit=bars)
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


def exchange_names(settings: Any) -> tuple[str, ...]:
    """Which exchanges to ask, lowered and de-duplicated in the order given.

    `PRICES_CCXT_EXCHANGES` if set, else the single `PRICES_CCXT_EXCHANGE`,
    else binance. Several is the point: one venue's board is one venue's
    opinion of what is liquid.
    """
    raw = getattr(settings, "ccxt_exchanges", ()) or ()
    if not raw:
        one = (getattr(settings, "ccxt_exchange", "") or "binance").strip()
        raw = (one,)
    seen: dict[str, None] = {}
    for name in raw:
        cleaned = str(name).strip().lower()
        if cleaned:
            seen.setdefault(cleaned, None)
    return tuple(seen) or ("binance",)


def filters_from(settings: Any) -> Filters:
    """The configured filter set, read off `Settings`."""
    return Filters(
        top=int(getattr(settings, "ccxt_top", 0) or 0),
        min_volume=float(getattr(settings, "ccxt_min_volume", 0.0) or 0.0),
        min_days=float(getattr(settings, "ccxt_min_days", 0.0) or 0.0),
        max_spread=float(getattr(settings, "ccxt_max_spread", 0.0) or 0.0),
        min_price=float(getattr(settings, "ccxt_min_price", 0.0) or 0.0),
        min_range=float(getattr(settings, "ccxt_min_range", 0.0) or 0.0),
        quotes=tuple(getattr(settings, "ccxt_quotes", ()) or ()),
        swaps_only=bool(getattr(settings, "ccxt_swaps_only", False)),
    )


async def discover_ccxt(settings: Any) -> dict[str, tuple[str, ...]]:
    """The pairs worth carrying, and which exchanges carry each one.

    **Ranked across the exchanges, not within them.** One venue's board is one
    venue's opinion of what is liquid; the desk wants the pairs that are liquid
    *in the market*, which is the same reason gold is quoted from six venues
    and not from whichever one answered first. So the quality filters run per
    exchange - a pair that is wide or dead or newly listed *there* is dropped
    from *there* - and the volume ranking is then taken over the summed volume
    of what survives.

    The cut is applied last, once, globally. Applying `top` per exchange and
    then merging would give the union of several top-250s, which is neither 250
    pairs nor the 250 largest.

    Returns pair -> the exchanges carrying it, busiest first, so a feed's
    symbols are ordered the way the TradingView feeds are.
    """
    wanted = exchange_names(settings)
    rules = filters_from(settings)
    # `top` is the global cut and must not fire per exchange.
    local = replace(rules, top=0)

    volume: dict[str, float] = defaultdict(float)
    carried: dict[str, list[tuple[float, str]]] = defaultdict(list)
    reached = 0
    try:
        async with CcxtSource(settings) as source:
            for name in wanted:
                try:
                    board = await source.board(name)
                except Exception as exc:  # one venue down is not all of them
                    log.warning("prices: ccxt %s board failed: %s", name, exc)
                    continue
                reached += 1
                kept, dropped = local.choose(board)
                log.info(
                    "prices: ccxt %s - %d of %d pairs kept%s",
                    name,
                    len(kept),
                    len(board),
                    f", dropped {dict(dropped)}" if dropped else "",
                )
                for pair in kept:
                    volume[pair.symbol] += pair.quote_volume
                    carried[pair.symbol].append((pair.quote_volume, name))
    except Exception as exc:  # an unreachable exchange must not take the desk down
        log.warning("prices: ccxt discovery failed: %s", exc)
        return {}
    if not reached:
        log.warning("prices: no ccxt exchange answered - carrying nothing")
        return {}

    ranked = sorted(volume, key=lambda pair: -volume[pair])
    if rules.top > 0:
        ranked = ranked[: rules.top]
    out = {pair: tuple(name for _, name in sorted(carried[pair], reverse=True)) for pair in ranked}
    log.info(
        "prices: ccxt %d pair(s) carried across %d exchange(s) - %d on more than one",
        len(out),
        reached,
        sum(1 for names in out.values() if len(names) > 1),
    )
    return out


def pairs_for(board: Sequence[Board], filters: Filters) -> tuple[Symbol, ...]:
    """The chosen pairs as `Symbol`s, venue-tagged by exchange name upstream."""
    kept, dropped = filters.choose(board)
    if dropped:
        log.info("prices: ccxt board %d kept, dropped %s", len(kept), dropped)
    return tuple(Symbol("CCXT", pair.symbol) for pair in kept)
