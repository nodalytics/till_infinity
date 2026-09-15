"""The z-score on constructed spreads, fed from quotes rather than from bars.

`research/constructing.md` measured the reading at **AUC 0.6985 against 0.5031**
on cross-venue spreads - the only positive directional result this folder has.
That was on **1-minute bars**, and the thing those spreads revert by is
arbitrage between two venues, which operates in seconds. A 1m close samples a
seconds-scale process once and misses most of it, so the measured number is
likely a smoothed shadow of whatever is there.

This computes the same spread from the **live quotes of its legs** and keeps a
separate z-score on it.

## What makes this dangerous, and the rule that follows

A spread is the difference between two nearly equal numbers, so **pairing a
fresh quote with a stale one manufactures a move that never happened**. It is
the same defect `prices/spreads.py` refuses at the bar level by dropping a
bucket where a leg is missing, arriving here in a live form where it is easier
to commit: quotes tick independently, one venue can go quiet for a minute, and
nothing about the arithmetic complains.

So both legs must have quoted within `MAX_SKEW` of each other, and a pair that
has not is skipped rather than carried forward. `stale` counts how often that
happens, because a pair skipping most of its ticks is not a spread - it is two
instruments that rarely quote together.

## Kept apart from the bar record on purpose

Readings land under the interval name `tick`, so `Book.of(name, "tick")` is a
different series from `Book.of(name, "1m")`. Two records, scored separately,
because they are two different claims: one about a minutely close, one about a
quote. Merging them would produce a number describing neither, and it is the
bar record that `TRADING_ZMA_GATE` currently reads.

**Off by default.** It costs a dictionary lookup per quote and does nothing
until `STRUCTURES_SPREAD_QUOTES` names the pairs to watch.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field

from ..logging import get_logger
from ..shared import effects
from .state import Restorable

log = get_logger(__name__)

#: The interval these are recorded under, so the quote record and the bar
#: record stay separate series in the same book.
INTERVAL = "tick"

#: The level a spread of zero maps to, matching `prices/spreads.py` so the two
#: series describe the same quantity on the same scale.
BASE = 100.0

#: How far apart two legs' quotes may be and still be treated as simultaneous.
#: A spread is a difference of two nearly equal numbers, so this is the single
#: number protecting the reading from being mostly staleness.
MAX_SKEW = float(os.environ.get("STRUCTURES_SPREAD_SKEW_S", "2.0"))

#: Pairs to watch, as `name=feed@VENUE-feed@VENUE`, comma separated. Empty
#: means this does nothing, which is the default.
SPEC = os.environ.get("STRUCTURES_SPREAD_QUOTES", "").strip()

ENABLED = bool(SPEC)

effects.declare("structures.spread_quotes", enabled=ENABLED)


@dataclass(frozen=True, slots=True)
class Pair(Restorable):
    """One constructed spread, and the two quoted legs it is made of."""

    name: str
    feed_a: str
    venue_a: str
    feed_b: str
    venue_b: str

    def price(self, a: float, b: float) -> float | None:
        """`BASE * exp(ln a - ln b)`, so log returns are the spread's own moves."""
        if a <= 0 or b <= 0:
            return None
        gap = math.log(a) - math.log(b)
        if not -50.0 < gap < 50.0:
            return None
        return BASE * math.exp(gap)


def parse(spec: str) -> list[Pair]:
    """`name=feed@VENUE-feed@VENUE,...` into pairs, skipping anything malformed.

    Skipped rather than raised: this is a diagnostic reading that nothing gates
    on, and a typo in one entry should not stop a desk from starting.
    """
    out: list[Pair] = []
    for raw in spec.split(","):
        chunk = raw.strip()
        if not chunk or "=" not in chunk:
            continue
        name, _, legs = chunk.partition("=")
        first, _, second = legs.partition("-")
        if "@" not in first or "@" not in second:
            log.warning("structures: cannot read spread quote spec %r", chunk)
            continue
        feed_a, _, venue_a = first.partition("@")
        feed_b, _, venue_b = second.partition("@")
        if not all((name, feed_a, venue_a, feed_b, venue_b)):
            log.warning("structures: incomplete spread quote spec %r", chunk)
            continue
        out.append(
            Pair(name.strip(), feed_a.strip(), venue_a.strip(), feed_b.strip(), venue_b.strip())
        )
    return out


@dataclass(slots=True)
class Watcher(Restorable):
    """Latest quote per leg, and the spreads that become computable from them.

    `Restorable` because it hangs off the engine and is therefore pickled, and
    a slots dataclass without it raises on a field added after a save rather
    than starting cold. But **the restored contents are deliberately thrown
    away** - see `Engine.rearm_spread_quotes`. A quote cached before a restart
    is stale by definition, and reviving one to pair against a live quote is
    the exact defect this module exists to refuse.
    """

    pairs: tuple[Pair, ...] = ()
    #: `(feed, venue) -> (when, mid)`. One entry a leg, not a history: the
    #: z-score keeps the history and this only has to answer "what is the other
    #: side worth right now, and how long ago was that true".
    _latest: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)
    seen: int = 0
    emitted: int = 0
    stale: int = 0

    def observe(self, payload: dict) -> list[tuple[str, float]]:
        """One quote in, zero or more `(spread name, price)` out.

        Returns rather than writes, so the caller owns the book and this stays
        testable without one.
        """
        feed = str(payload.get("feed") or "")
        venue = str(payload.get("venue") or "")
        mid = payload.get("mid")
        if not feed or not isinstance(mid, int | float) or mid <= 0:
            return []
        when = float(payload.get("time") or time.time())
        self._latest[(feed, venue)] = (when, float(mid))
        self.seen += 1

        out: list[tuple[str, float]] = []
        for pair in self.pairs:
            if (feed, venue) not in ((pair.feed_a, pair.venue_a), (pair.feed_b, pair.venue_b)):
                continue
            first = self._latest.get((pair.feed_a, pair.venue_a))
            second = self._latest.get((pair.feed_b, pair.venue_b))
            if first is None or second is None:
                continue
            # **Both legs quoted together, or neither counts.** A fresh quote
            # against a stale one is a manufactured move on a series whose
            # whole content is the difference between two nearly equal numbers.
            if abs(first[0] - second[0]) > MAX_SKEW:
                self.stale += 1
                continue
            price = pair.price(first[1], second[1])
            if price is None:
                continue
            out.append((pair.name, price))
            self.emitted += 1
            effects.fired("structures.spread_quotes")
        return out

    def to_dict(self) -> dict:
        return {
            "enabled": ENABLED,
            "pairs": [p.name for p in self.pairs],
            "quotes_seen": self.seen,
            "readings": self.emitted,
            "skipped_stale": self.stale,
            "skew_limit_s": MAX_SKEW,
        }


def from_env() -> Watcher:
    """The watcher this deployment asks for. Empty unless `SPEC` names pairs."""
    return Watcher(pairs=tuple(parse(SPEC)))


def rearm(engine) -> int:
    """Rebuild the watcher from the environment after a restore. Returns pairs.

    **The cache is dropped, not carried.** Everything in `_latest` was true
    before the process stopped, and pairing any of it against a live quote
    would manufacture exactly the move this module refuses to compute. The
    pairs are re-read too, so a deployment that changed them takes effect -
    the same rule `service.load` applies to every other setting: what is
    learned is kept, what was chosen comes from this deployment.
    """
    fresh = from_env()
    engine.spread_quotes = fresh
    return len(fresh.pairs)
