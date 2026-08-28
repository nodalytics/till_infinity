"""How far price reaches: into a level, and against a trade once in it.

Three numbers currently chosen by hand, all of them about distance:

* **the pullback** - `pullback_fraction` waits for price to come back some
  share of the way to the level. One is a full return, and how often that
  fills is not something anybody measured.
* **the entry** - where in the zone to act, which the level model does not say.
* **the stop** - `min_stop_vol` plus a scaling, sized against a bar rather than
  against what actually goes wrong.

The journal records the two quantities that answer them. `depth_vol` is how far
price went *into* a level, which is the pullback question. `excursion_vol` is
how far it went *against* the trade before resolving, which is the stop
question.

## Quantiles, not means

A mean depth says where price usually stops; an entry wants somewhere it
usually *reaches*, and a stop wants somewhere it usually does **not**. Both are
questions about the tail of a distribution, and a mean answers neither.

That distinction also settles whether these are worth building. Screened for
estimability (`research/harness/estimable.py`), `depth_vol` persists at +0.188
with a 5.8x spread across series - forecastable and with room to be wrong in.
`excursion_vol` persists at only +0.141, which is weak. **But a stop does not
need the next excursion forecast**; it needs a distance most excursions fall
short of, and the 2.7x spread across series says that distance genuinely
differs by instrument. The first is an estimator, the second is a measurement
of a distribution, and only the first depends on persistence.

## A window rather than an accumulator

Both are read as quantiles, and a quantile needs the sample, not a running
total. A bounded window keeps it honest about the recent past without storing
a year of touches - and unlike an exponential mean there is no weighting to
justify, because the quantile of a window is exactly the quantile of what it
holds.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .state import Restorable

#: How many observations a series keeps.
WINDOW = 200
#: Fewest before it will answer at all.
FEWEST = 20


@dataclass(slots=True)
class Reach(Restorable):
    """A bounded sample of one distance, read by quantile."""

    seen: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))

    def observe(self, value: float) -> None:
        """Fold in one distance. Negatives are folded by magnitude.

        Both quantities are distances and arrive signed by which side of the
        level they were on, which is a fact about the approach rather than
        about how far price went.

        **Zero is an observation, not a missing one**, and the first version of
        this discarded it. Many touches resolve with no adverse excursion at
        all - the median resolves in nineteen seconds - and a trade that never
        threatened its stop is the most informative thing a stop estimator can
        see. Dropping those leaves a sample of only the touches that went
        wrong, and a quantile of that puts the stop far wider than the
        instrument warrants. The same holds for depth: a touch that reached a
        level without penetrating it is a real thing price did.

        A field that is genuinely absent is the caller's business, and the
        caller does not call.
        """
        value = abs(float(value))
        if value >= 0:
            self.seen.append(value)

    def at(self, share: float) -> float | None:
        """The distance `share` of observations fall below, or None."""
        if len(self.seen) < FEWEST:
            return None
        ordered = sorted(self.seen)
        index = min(len(ordered) - 1, max(0, int(share * len(ordered))))
        return ordered[index]

    def to_dict(self) -> dict:
        return {"seen": len(self.seen), "median": round(self.at(0.5) or 0.0, 4)}


@dataclass(slots=True)
class Reaches(Restorable):
    """Depth into the level and excursion against the trade, per series."""

    depth: dict[tuple[str, str], Reach] = field(default_factory=dict)
    excursion: dict[tuple[str, str], Reach] = field(default_factory=dict)

    def observe(
        self, feed: str, interval: str, depth: float | None, excursion: float | None
    ) -> None:
        """Fold in one resolution. `None` means the field was absent, which is
        not the same as a distance of zero and must not be counted as one."""
        key = (feed, interval)
        if depth is not None:
            self.depth.setdefault(key, Reach()).observe(depth)
        if excursion is not None:
            self.excursion.setdefault(key, Reach()).observe(excursion)

    def entry_at(self, feed: str, interval: str, share: float = 0.5) -> float | None:
        """How far into the level to wait for, in volatility units.

        The median by default: a depth price reaches about half the time, which
        is the trade-off an entry is - deeper fills better and fills less
        often. Asking for a share is how that trade-off gets made explicitly
        rather than by a constant.
        """
        found = self.depth.get((feed, interval))
        return found.at(share) if found else None

    def stop_at(
        self, feed: str, interval: str, share: float = 0.8, risk_vol: float = 0.0
    ) -> float | None:
        """How far beyond the level a stop must sit, in volatility units.

        `share` of past excursions fall short of this, so at 0.8 roughly one
        trade in five is stopped by something the level has done before - which
        is a choice about how much noise to pay for, made where it can be seen.

        **`risk_vol` is added, not maxed against.** The level model's own risk
        distance describes the structure; the excursion quantile describes what
        price has actually done to trades there. They are different evidence
        about the same question and a stop that clears both is not the larger
        of the two, it is the sum - which is also why this returns a distance
        rather than a stop price, and lets the caller decide what to anchor it
        to.
        """
        found = self.excursion.get((feed, interval))
        got = found.at(share) if found else None
        if got is None:
            return None
        return got + max(0.0, risk_vol)

    def ready(self) -> int:
        return sum(1 for r in self.depth.values() if r.at(0.5) is not None)
