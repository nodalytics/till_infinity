"""Combining levels across timeframes.

A level found on the 4h chart and one found on the 15m chart at the same price
are not two levels. They are one level seen at two resolutions, and each
resolution knows something the other does not:

- the **higher** timeframe knows the level *matters* — a swing that shows up on
  a 4h chart is a larger structure than one visible only on 15m;
- the **lower** timeframe knows *where it is* — its swings cluster inside a
  tighter band, so it pins the price far more precisely.

## Fusing them is inverse-variance weighting

That split is already encoded, because every level carries a Kalman variance
and a lower-timeframe level naturally has a smaller one. Combining independent
estimates of the same quantity by their precision is the standard result:

    1/sigma^2  =  sum of 1/sigma_i^2
    x          =  sum(x_i / sigma_i^2) / sum(1 / sigma_i^2)

The finer timeframe has the smaller sigma, so it dominates the position — "the
lower you go the more precise you get" is not a rule anyone had to write, it
falls out of the arithmetic. And the fused sigma is smaller than any member's,
which is correct: several timeframes agreeing on a price is more evidence about
where it is than any one of them alone.

## Confluence is evidence, not decoration

A price that is a level on 15m, 1h *and* 4h is a different object from one that
only appears on 15m. The count of distinct timeframes agreeing is carried
through as its own term, because it is the thing a person actually looks for on
a chart and the per-timeframe statistics cannot express it.

Touch histories are merged too. A level is only as good as its evidence, and
evidence gathered at three resolutions of the same price is evidence about the
same price.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .levels import Level, Side, SideStats, State
from .volatility import Volatility

#: Timeframes from finest to coarsest. Rank is what "higher" and "lower" mean,
#: and pivot sessions sit at the top because a daily pivot is a daily structure.
ORDER: tuple[str, ...] = (
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "1d",
    # A daily pivot is a daily structure, so it ranks with 1d rather than above.
    "daily",
    "1w",
    "weekly",
)

#: The timeframes levels are built on, and therefore the ones confluence can
#: combine. One list, because they were two and drifted: confluence spanned 4h
#: while the engine never built it, so it spent its life looking for a
#: timeframe that did not exist.
#:
#: Finest first. Below 5m a "level" is mostly the noise of the session. The top
#: end runs to 1w because that is where the levels people actually trade come
#: from — and it only became usable once volatility and evidence decay were
#: measured per timeframe, since a weekly level in 5m units is placed to the
#: nearest dollar and forgets a touch before the next one arrives.
TIMEFRAMES: tuple[str, ...] = ("3m", "5m", "15m", "1h", "4h", "1d", "1w")

#: Alias kept for readers who think of it as a span rather than a list.
DEFAULT_SPAN: tuple[str, ...] = TIMEFRAMES


def rank(interval: str) -> int:
    """Position in `ORDER`; unknown intervals sort last rather than crashing."""
    try:
        return ORDER.index(interval)
    except ValueError:
        return len(ORDER)


@dataclass(slots=True)
class Zone:
    """One price agreed on by levels from several timeframes."""

    feed: str
    price: float
    sigma: float
    members: list[Level] = field(default_factory=list)

    @property
    def timeframes(self) -> tuple[str, ...]:
        """Every distinct timeframe agreeing, coarsest first."""
        return tuple(sorted({level.interval for level in self.members}, key=rank, reverse=True))

    @property
    def span(self) -> str:
        """The highest timeframe present — how big a structure this is."""
        return self.timeframes[0] if self.timeframes else ""

    @property
    def precision(self) -> str:
        """The lowest timeframe present — how precisely it is placed."""
        return self.timeframes[-1] if self.timeframes else ""

    @property
    def depth(self) -> int:
        return len(self.timeframes)

    @property
    def touches(self) -> float:
        return sum(level.touches for level in self.members)

    @property
    def state(self) -> State:
        """The state of the most significant member.

        Not a vote. A 15m level breaking while the 4h level it sits inside
        holds is an ordinary morning, and letting the finer timeframe overrule
        the coarser one on *significance* would invert the whole point.
        """
        top = max(self.members, key=lambda level: (rank(level.interval), level.touches))
        return top.state

    def sides(self) -> dict[Side, SideStats]:
        """Touch history merged across every member.

        Evidence gathered at three resolutions of one price is evidence about
        the same price, so it is pooled rather than kept in three thin piles
        none of which clears the bar on its own.
        """
        merged: dict[Side, SideStats] = {}
        for level in self.members:
            for side, stats in level.sides.items():
                into = merged.setdefault(side, SideStats())
                into.touches += stats.touches
                into.rejects += stats.rejects
                into.breaks += stats.breaks
                into.chops += stats.chops
                into.push_sum += stats.push_sum
                into.push_sq += stats.push_sq
                into.ups += stats.ups
        return merged

    def band(self, vol: Volatility) -> tuple[float, float]:
        """The narrowest band any member claims.

        The finest timeframe wins here for the same reason it dominates the
        price: a wider member is not evidence that the level is fuzzier, only
        that its own timeframe cannot see as sharply.
        """
        bands = [level.zone(vol) for level in self.members]
        low, high = max(lo for lo, _ in bands), min(hi for _, hi in bands)
        if low <= high:
            return low, high
        # No band common to every member. Grouping is by *pairwise* overlap and
        # overlap chains: A can overlap B and B overlap C while A and C do not
        # touch, so the intersection is empty and the narrowest-band rule above
        # returns an inverted pair. Fall back to the tightest member's width,
        # centred on the fused price — the members still agree on roughly where
        # this is, which is what put them in one zone, and a band that reads
        # high-then-low is worse than a slightly generous one.
        width = min(hi - lo for lo, hi in bands) / 2.0
        return self.price - width, self.price + width

    def strength(self, when: float, vol: Volatility) -> float:
        """Best member, lifted by how many timeframes agree.

        Confluence is a multiplier rather than an average: three timeframes
        agreeing is stronger than the best of them, whereas averaging would let
        a weak 15m level drag down a strong 4h one it merely happens to sit
        beside.
        """
        best = max((level.strength(when, vol) for level in self.members), default=0.0)
        agreement = 1.0 + 0.15 * (self.depth - 1)
        return round(min(1.0, best * agreement), 4)

    def to_dict(self, vol: Volatility, when: float) -> dict:
        low, high = self.band(vol)
        return {
            "feed": self.feed,
            "price": round(self.price, 8),
            "low": round(low, 8),
            "high": round(high, 8),
            "sigma": round(self.sigma, 8),
            "span": self.span,
            "precision": self.precision,
            "timeframes": list(self.timeframes),
            "depth": self.depth,
            "state": str(self.state),
            "touches": round(self.touches, 3),
            "strength": self.strength(when, vol),
            "sides": {str(side): stats.to_dict() for side, stats in self.sides().items()},
        }

    def __str__(self) -> str:
        return f"{self.price:.5g} [{'+'.join(self.timeframes)}] {self.touches:.1f} touches"


def fuse(members: Sequence[Level]) -> tuple[float, float]:
    """Inverse-variance fusion of several estimates of one price.

    Returns (price, sigma). A member with zero variance would claim infinite
    precision and swallow the result, so variances are floored — no estimate
    from finitely many noisy touches is exact.
    """
    weights, weighted = 0.0, 0.0
    for level in members:
        variance = max(level.filter.variance, 1e-12)
        weight = 1.0 / variance
        weights += weight
        weighted += weight * level.price
    if weights <= 0:
        return (members[0].price, members[0].filter.sigma) if members else (0.0, 0.0)
    return weighted / weights, math.sqrt(1.0 / weights)


def combine(
    levels: Sequence[Level],
    vol: Volatility,
    *,
    span: Sequence[str] = DEFAULT_SPAN,
    volatility: Callable[[Level], Volatility] | None = None,
) -> list[Zone]:
    """Group levels across timeframes into confluence zones, cheapest first.

    Grouping is on **zone overlap**, not on a single tolerance, and that is the
    difference between this working and not. A shared tolerance is necessarily
    expressed in one timeframe's volatility, and the timeframes differ by more
    than an order of magnitude — measured on gold, one volatility unit is $0.74
    on 5m and $9.87 on 4h. With a 5m-scale tolerance a 4h level would have to
    sit within about fifty cents of a 5m level to be considered the same price,
    which almost never happens, so nothing ever combined.

    A level's zone already encodes how precisely its own timeframe can place
    it. Two levels describe one price when those zones overlap — which is the
    same test `dedupe` uses within a timeframe, applied across them.

    `volatility` resolves each level's estimate; without it every level is
    measured with `vol`, which is only correct when they share a timeframe.

    Levels outside `span` are ignored rather than merged. Combining a 1m level
    into a 4h zone would drag the fused price toward whichever minute-scale
    wiggle happened to be nearby, which is precision about the wrong thing.
    """
    resolve = volatility or (lambda _level: vol)
    wanted = set(span)
    usable = sorted(
        (level for level in levels if level.interval in wanted),
        key=lambda level: level.price,
    )
    if not usable:
        return []

    groups: list[list[Level]] = [[usable[0]]]
    reach = usable[0].zone(resolve(usable[0]))[1]
    for level in usable[1:]:
        low, high = level.zone(resolve(level))
        if low <= reach:
            groups[-1].append(level)
            # The group reaches as far as its widest member — a coarse level
            # that overlaps a fine one also reaches whatever else it covers.
            reach = max(reach, high)
        else:
            groups.append([level])
            reach = high

    zones: list[Zone] = []
    for members in groups:
        price, sigma = fuse(members)
        zones.append(Zone(feed=members[0].feed, price=price, sigma=sigma, members=list(members)))
    return zones


def at(zones: Sequence[Zone], price: float, vol: Volatility, within_vol: float = 3.0) -> list[Zone]:
    """Zones close enough to `price` to matter, nearest first."""
    scored = []
    for zone in zones:
        if not zone.price:
            continue
        distance = abs((price - zone.price) / zone.price * 10_000) / vol.bps
        if distance <= within_vol:
            scored.append((distance, zone))
    return [zone for _, zone in sorted(scored, key=lambda pair: pair[0])]
