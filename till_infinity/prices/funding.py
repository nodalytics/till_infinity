"""What it costs to hold a perpetual, current and historical.

## Why this is not a nice-to-have

A perpetual swap charges funding every few hours, paid by whoever is holding
through the stamp. It is not spread and it is not commission: it is a carry that
scales with **time in the trade**, which is the one dimension
[research/paying.md](../../research/paying.md) does not price. Everything that
document measures is paid once, on the way in and the way out.

That matters most for exactly the trade this desk is trying to build. A
scalp-to-swing hold - in on a low timeframe, trailed until it reverses - is the
shape that sits through the most stamps, so the strategy with the best expected
push is also the one paying the most carry, and nothing currently nets the two.

It is also a **signal**, not only a cost. Funding is the market paying one side
to hold; a rate far from zero says positioning is lopsided, which is the same
claim `research/positioning.md` makes from other evidence and has never been
able to check against a direct measurement.

## Two collections, because they are two different requests

**Current** is one call per exchange for every pair - `fetch_funding_rates` -
and carries the predicted rate, the next stamp, and mark against index. Cheap
enough to poll on the ordinary cycle.

**History** is one call per *pair*, so 250 pairs across five exchanges is 1,250
requests and cannot go on the same clock. It is backfilled once and then topped
up from the newest stamp already stored, which is why `since` is read from the
store rather than assumed.

## What is stored, and what is deliberately not

The rate, the stamp it applies to, mark and index where the exchange gives
them. **Not** an annualised figure: that is a presentation choice - 8-hourly
against 4-hourly is a factor of two - and baking it in would put an assumption
in the record where an arithmetic step belongs. `annualised` computes it from
the stored interval for anything that wants it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..logging import get_logger

log = get_logger(__name__)

#: Stamps per day at the common intervals, for `annualised`. A pair whose
#: interval is unknown is left alone rather than assumed to be 8-hourly - the
#: exchanges differ and several have moved to 4h and 1h on volatile pairs.
PER_DAY: dict[str, float] = {"1h": 24.0, "2h": 12.0, "4h": 6.0, "8h": 3.0, "12h": 2.0}

#: How many pairs' histories to ask for at once. One exchange, one rate limit -
#: ccxt serialises within a client anyway, so this bounds the queue rather than
#: the throughput, and keeps a backfill from monopolising the loop.
HISTORY_BATCH = 8


@dataclass(frozen=True, slots=True)
class Funding:
    """One funding observation, as it goes into the store."""

    feed: str
    exchange: str
    pair: str
    #: The rate as a fraction, not a percentage: 0.0001 is one basis point.
    rate: float
    #: When this rate applies, epoch seconds.
    time: float
    #: How often this pair funds, as the exchange states it - "8h", "4h", "".
    interval: str = ""
    mark: float = 0.0
    index: float = 0.0
    #: True for a rate that has already been charged, False for the predicted
    #: next one. Keeping both in one table needs this: a prediction that moved
    #: is not a correction of history, and averaging the two would silently mix
    #: what was paid with what might be.
    settled: bool = True

    @property
    def annualised(self) -> float | None:
        """The rate as a yearly fraction, or None when the interval is unknown.

        Computed rather than stored. 8-hourly against 4-hourly is a factor of
        two, so an annualised number written into the record would bake a
        presentation choice into the measurement.
        """
        per_day = PER_DAY.get(self.interval)
        if per_day is None:
            return None
        return self.rate * per_day * 365.0

    @property
    def basis(self) -> float | None:
        """Mark against index, as a fraction. None when either is missing.

        The premium funding exists to close, so it is the thing to check a rate
        against: they should agree in sign, and a pair where they do not is
        either mid-stamp or being reported oddly.
        """
        if self.mark <= 0 or self.index <= 0:
            return None
        return (self.mark - self.index) / self.index


def _rate_from(row: dict[str, Any], exchange: str, feed: str, *, settled: bool) -> Funding | None:
    """One ccxt funding row, or None if it carries no usable rate."""
    rate = row.get("fundingRate")
    if not isinstance(rate, int | float):
        return None
    pair = str(row.get("symbol") or "")
    if not pair:
        return None
    stamp = row.get("fundingTimestamp") or row.get("timestamp") or 0
    return Funding(
        feed=feed,
        exchange=exchange,
        pair=pair,
        rate=float(rate),
        time=float(stamp) / 1000.0 if stamp else 0.0,
        interval=str(row.get("interval") or ""),
        mark=float(row.get("markPrice") or 0.0),
        index=float(row.get("indexPrice") or 0.0),
        settled=settled,
    )


async def current(exchange: Any, name: str, feeds: dict[str, str]) -> list[Funding]:
    """The predicted next rate for every pair, in one call.

    `feeds` maps ccxt pair -> feed slug, so only what the desk carries is kept -
    an exchange lists hundreds more and none of them have levels.

    Returns `[]` rather than raising when the exchange cannot answer. Funding is
    an input to sizing and to research, not to whether the desk runs.
    """
    if not exchange.has.get("fetchFundingRates"):
        return []
    try:
        rows = await exchange.fetch_funding_rates()
    except Exception as exc:
        log.info("prices: %s funding rates failed: %s", name, exc)
        return []
    out = []
    for pair, row in rows.items():
        feed = feeds.get(str(pair))
        if feed is None or not isinstance(row, dict):
            continue
        # Predicted, not charged: this is the rate for the *next* stamp.
        got = _rate_from(row, name, feed, settled=False)
        if got is not None:
            out.append(got)
    return out


async def history(
    exchange: Any,
    name: str,
    feeds: dict[str, str],
    *,
    since: dict[str, float] | None = None,
    limit: int = 200,
) -> list[Funding]:
    """Past rates for each carried pair, newest stamp first per pair.

    One request per pair, so this is the expensive half and is batched rather
    than fired all at once. `since` maps pair -> the newest stamp already
    stored, in epoch seconds, so a top-up asks for what is missing instead of
    re-fetching the whole window every cycle.
    """
    if not exchange.has.get("fetchFundingRateHistory"):
        return []
    seen = since or {}
    pairs = list(feeds)
    out: list[Funding] = []

    async def one(pair: str) -> list[Funding]:
        feed = feeds[pair]
        start = seen.get(pair, 0.0)
        try:
            rows = await exchange.fetch_funding_rate_history(
                pair, since=int(start * 1000) + 1 if start else None, limit=limit
            )
        except Exception as exc:
            log.debug("prices: %s funding history for %s failed: %s", name, pair, exc)
            return []
        got = []
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            made = _rate_from(row, name, feed, settled=True)
            # A history row is a rate that was charged, so a stamp is required:
            # without one it cannot be placed in time and is worse than absent.
            if made is not None and made.time > 0:
                got.append(made)
        return got

    for start in range(0, len(pairs), HISTORY_BATCH):
        batch = pairs[start : start + HISTORY_BATCH]
        for chunk in await asyncio.gather(*(one(pair) for pair in batch)):
            out.extend(chunk)
        await asyncio.sleep(0)
    return out


@dataclass(slots=True)
class Book:
    """The most recent funding seen per feed, for anything that needs it now."""

    seen: dict[str, Funding] = field(default_factory=dict)

    def observe(self, rows: Sequence[Funding]) -> int:
        """Keep the newest row per feed. Returns how many were new."""
        fresh = 0
        for row in rows:
            was = self.seen.get(row.feed)
            if was is None or row.time >= was.time:
                self.seen[row.feed] = row
                fresh += 1
        return fresh

    def rate(self, feed: str) -> float | None:
        got = self.seen.get(feed)
        return None if got is None else got.rate

    def cost_over(self, feed: str, seconds: float) -> float | None:
        """What holding this feed for `seconds` costs as a fraction of notional.

        Positive means a long pays. **None when the interval is unknown**,
        rather than assuming eight hours: the assumption would be wrong by a
        factor of two on the pairs that fund fastest, which are exactly the
        ones where the number matters.
        """
        got = self.seen.get(feed)
        if got is None:
            return None
        per_day = PER_DAY.get(got.interval)
        if per_day is None:
            return None
        return got.rate * per_day * (seconds / 86_400.0)
