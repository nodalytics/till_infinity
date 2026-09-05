"""Open interest and the long/short split - who is positioned, not just where.

## Why this ranks above funding

**Open interest with price direction separates new money from closing**, and
nothing derived from price alone can:

| price | open interest | what it is |
| --- | --- | --- |
| up | up | fresh longs - new money committing |
| up | down | shorts covering - old money leaving |
| down | up | fresh shorts |
| down | down | longs capitulating |

Those four resolve at a level differently. A level approached by fresh longs has
buyers who will defend it; the same level approached by shorts covering has
buying that stops the moment the covering finishes - and **the price path is
identical in both cases**. That is the whole argument for collecting this:
it is information a price-only model cannot recover.

Funding does not have that property. It is computed from the premium, which is
computed from price, so a model handed funding may be handed a lagged transform
of what it already sees. See [research/crypto.md](../../research/crypto.md).

## The unit trap, which is the easy way to get this wrong

`openInterestAmount` is in **contracts or base units and does not compare
across pairs** - 107,919 BTC contracts and 2,744,748 okx contracts are not the
same kind of number, and neither compares to a small-cap altcoin's. Only okx
returns `openInterestValue` populated; everywhere else it is None and the
notional has to be computed as `amount x mark`.

So `Interest.notional` is the comparable quantity, and even that is a level.
**What a model wants is the change**, as a share of what was there - which is
scale-free the way a volatility unit is, and is the only form in which one
model can borrow evidence across instruments.

## Liquidations are not collected, and that is a finding

`gate` is the only exchange of the five that advertises a public
`fetchLiquidations`; everywhere else the method is `fetchMyLiquidations`, an
account endpoint that says nothing about the market and sits right beside it in
`ex.has`. Probed on 2026-09-05, gate's returned **zero rows** for BTC and ETH
over a 24-hour window - pairs that certainly had liquidations in it.

A collector for that would be a feature that ships, configures, logs correctly
and collects nothing, which is the pattern `research/inert.md` exists for. So
cascades have to be **inferred**: open interest collapsing against a price move
in the same direction is forced closing, which `Book.flow` reports as
capitulation or covering.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..logging import get_logger

log = get_logger(__name__)

#: How many pairs to ask at once. One exchange, one rate limit - ccxt
#: serialises within a client anyway, so this bounds the queue rather than the
#: throughput and keeps a backfill off the loop's neck.
BATCH = 8

#: The share of open interest a move has to change before it is called a flow
#: rather than noise. 1% over the sampling interval; below it, `flow` says
#: "steady" instead of inventing one of the four stories.
MIN_SHIFT = 0.01


@dataclass(frozen=True, slots=True)
class Interest:
    """Open interest at one moment, for one pair on one exchange."""

    feed: str
    exchange: str
    pair: str
    #: In contracts or base units. **Not comparable across pairs** - use
    #: `notional`.
    amount: float
    #: The exchange's own notional, where it gives one. Zero means it did not.
    value: float = 0.0
    #: Mark price at the same moment, used to build a notional when `value` is
    #: absent. Zero when unknown.
    mark: float = 0.0
    time: float = 0.0

    @property
    def notional(self) -> float | None:
        """Open interest in quote currency, or None when it cannot be built.

        None rather than falling back to `amount`: a contract count and a
        notional differ by orders of magnitude, and quietly returning one where
        the other is expected would put two incomparable quantities in the same
        column.
        """
        if self.value > 0:
            return self.value
        if self.amount > 0 and self.mark > 0:
            return self.amount * self.mark
        return None


@dataclass(frozen=True, slots=True)
class Ratio:
    """How the accounts on one pair are split, long against short."""

    feed: str
    exchange: str
    pair: str
    #: Long accounts divided by short accounts. 1.0 is balanced.
    ratio: float
    #: The two shares where the exchange gives them - binance does, okx does
    #: not. Zero means it did not.
    long_share: float = 0.0
    short_share: float = 0.0
    time: float = 0.0

    @property
    def tilt(self) -> float:
        """Crowding as a signed share, -1 (all short) to +1 (all long).

        Built from the shares when they are given and from the ratio when they
        are not, so one number serves both exchanges. A ratio of 1.0 and shares
        of 50/50 both come out at 0.0.
        """
        if self.long_share > 0 and self.short_share > 0:
            total = self.long_share + self.short_share
            return (self.long_share - self.short_share) / total if total else 0.0
        if self.ratio <= 0:
            return 0.0
        return (self.ratio - 1.0) / (self.ratio + 1.0)


def _interest_from(row: dict[str, Any], exchange: str, feed: str, pair: str) -> Interest | None:
    amount = row.get("openInterestAmount")
    value = row.get("openInterestValue")
    if not isinstance(amount, int | float) and not isinstance(value, int | float):
        return None
    stamp = row.get("timestamp") or 0
    return Interest(
        feed=feed,
        exchange=exchange,
        pair=str(row.get("symbol") or pair),
        amount=float(amount or 0.0),
        value=float(value or 0.0),
        mark=float((row.get("info") or {}).get("markPrice") or 0.0)
        if isinstance(row.get("info"), dict)
        else 0.0,
        time=float(stamp) / 1000.0 if stamp else 0.0,
    )


async def _per_pair(feeds: dict[str, str], call: Any, label: str, name: str) -> list[Any]:
    """Run `call` over every carried pair, a batch at a time."""
    pairs = list(feeds)
    out: list[Any] = []
    for start in range(0, len(pairs), BATCH):
        batch = pairs[start : start + BATCH]
        for got in await asyncio.gather(*(call(pair) for pair in batch), return_exceptions=True):
            if isinstance(got, BaseException):
                log.debug("prices: %s %s failed: %s", name, label, got)
                continue
            out.extend(got)
        await asyncio.sleep(0)
    return out


async def open_interest(exchange: Any, name: str, feeds: dict[str, str]) -> list[Interest]:
    """Current open interest for every carried pair.

    Uses the bulk call where the exchange has one - **only okx does**, and it
    is the difference between one request and two hundred and fifty.
    """
    if exchange.has.get("fetchOpenInterests"):
        try:
            rows = await exchange.fetch_open_interests()
        except Exception as exc:
            log.info("prices: %s open interest failed: %s", name, exc)
            return []
        out = []
        for pair, row in (rows or {}).items():
            feed = feeds.get(str(pair))
            if feed and isinstance(row, dict):
                got = _interest_from(row, name, feed, str(pair))
                if got is not None:
                    out.append(got)
        return out

    if not exchange.has.get("fetchOpenInterest"):
        return []

    async def one(pair: str) -> list[Interest]:
        row = await exchange.fetch_open_interest(pair)
        got = _interest_from(row or {}, name, feeds[pair], pair)
        return [got] if got is not None else []

    return await _per_pair(feeds, one, "open interest", name)


async def open_interest_history(
    exchange: Any,
    name: str,
    feeds: dict[str, str],
    *,
    timeframe: str = "5m",
    since: dict[str, float] | None = None,
    limit: int = 200,
) -> list[Interest]:
    """Past open interest per pair, from the newest stamp already stored."""
    if not exchange.has.get("fetchOpenInterestHistory"):
        return []
    seen = since or {}

    async def one(pair: str) -> list[Interest]:
        start = seen.get(pair, 0.0)
        rows = await exchange.fetch_open_interest_history(
            pair, timeframe, since=int(start * 1000) + 1 if start else None, limit=limit
        )
        got = []
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            made = _interest_from(row, name, feeds[pair], pair)
            # A history row without a stamp cannot be placed in time, which is
            # worse than being absent.
            if made is not None and made.time > 0:
                got.append(made)
        return got

    return await _per_pair(feeds, one, "open interest history", name)


async def long_short(
    exchange: Any,
    name: str,
    feeds: dict[str, str],
    *,
    timeframe: str = "5m",
    since: dict[str, float] | None = None,
    limit: int = 200,
) -> list[Ratio]:
    """The long/short account split per pair, newest stamps last.

    Positioning **measured rather than inferred**, which is what makes it worth
    more than either open interest or funding on its own - and it has the least
    coverage of the three.
    """
    if not exchange.has.get("fetchLongShortRatioHistory"):
        return []
    seen = since or {}

    async def one(pair: str) -> list[Ratio]:
        start = seen.get(pair, 0.0)
        rows = await exchange.fetch_long_short_ratio_history(
            pair, timeframe, since=int(start * 1000) + 1 if start else None, limit=limit
        )
        got = []
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            ratio = row.get("longShortRatio")
            stamp = row.get("timestamp") or 0
            if not isinstance(ratio, int | float) or not stamp:
                continue
            info = row.get("info") if isinstance(row.get("info"), dict) else {}
            got.append(
                Ratio(
                    feed=feeds[pair],
                    exchange=name,
                    pair=str(row.get("symbol") or pair),
                    ratio=float(ratio),
                    long_share=float(info.get("longAccount") or 0.0),
                    short_share=float(info.get("shortAccount") or 0.0),
                    time=float(stamp) / 1000.0,
                )
            )
        return got

    return await _per_pair(feeds, one, "long/short ratio", name)


@dataclass(slots=True)
class Book:
    """The newest reading per feed, and what the change in it means."""

    interest: dict[str, Interest] = field(default_factory=dict)
    ratio: dict[str, Ratio] = field(default_factory=dict)
    #: The previous open interest per feed, kept so `flow` has something to
    #: compare against. One step back, not a series: this answers "what is
    #: happening now", and the series belongs in the store.
    was: dict[str, Interest] = field(default_factory=dict)

    def observe(self, rows: Sequence[Interest | Ratio]) -> int:
        fresh = 0
        for row in rows:
            if isinstance(row, Ratio):
                held = self.ratio.get(row.feed)
                if held is None or row.time >= held.time:
                    self.ratio[row.feed] = row
                    fresh += 1
                continue
            held = self.interest.get(row.feed)
            if held is None or row.time >= held.time:
                if held is not None and row.time > held.time:
                    self.was[row.feed] = held
                self.interest[row.feed] = row
                fresh += 1
        return fresh

    def shift(self, feed: str) -> float | None:
        """Change in open interest as a share of what was there, or None.

        The scale-free form, and the only one in which a model can borrow
        evidence across instruments - the same argument volatility units make
        everywhere else here.
        """
        now, before = self.interest.get(feed), self.was.get(feed)
        if now is None or before is None:
            return None
        first, second = before.notional, now.notional
        if first is None or second is None or first <= 0:
            return None
        return (second - first) / first

    def flow(self, feed: str, price_change: float) -> str:
        """Which of the four this is, or "steady"/"unknown".

        `price_change` is signed and its units do not matter - only the sign is
        read. "unknown" when there is no open interest to compare, which is a
        different answer from "steady" and must not be confused with it.
        """
        moved = self.shift(feed)
        if moved is None:
            return "unknown"
        if abs(moved) < MIN_SHIFT or price_change == 0:
            return "steady"
        rising = moved > 0
        if price_change > 0:
            return "fresh longs" if rising else "shorts covering"
        return "fresh shorts" if rising else "longs capitulating"

    def tilt(self, feed: str) -> float | None:
        got = self.ratio.get(feed)
        return None if got is None else got.tilt
