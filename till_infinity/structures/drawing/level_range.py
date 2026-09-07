"""The two levels price is currently between, and how much room is on each side.

## Why a pair, when everything else here is about one level

Every call this engine makes is about **one** price: a level was touched, and
the question is what happens next. That is the right shape for an entry and the
wrong shape for a target, because a target is a claim about where price can get
to, and the honest answer to that is bounded by the next structure in the way.

`research/reachable.md` is the measurement behind this. A target set by a fixed
multiple of the stop is a target set without reference to the market: it lands
wherever the arithmetic puts it, which is sometimes past a level that has
turned price back nine times, and sometimes a third of the way to open air.

A range says the thing a person reads off a chart in one glance - *price is
here, there is a ceiling there and a floor there* - and it makes two questions
answerable that a single level cannot:

* **Entry.** Price sitting hard against one bound is a different proposition
  from price in the middle of the range, and the strategies currently cannot
  tell those apart.
* **Target.** The opposite bound is a target with a reason. It is not
  necessarily the *right* target - it may be too close to be worth trading, and
  `room_vol` is what says so - but it is a number the market drew rather than
  one the position sizer did.

## Built from zones, not from levels

The bounds are `confluence.Zone`s: prices that levels from more than one
timeframe agree on. A single 5m level is not a ceiling, and treating it as one
would put a bound almost anywhere, which is the failure that makes a range
useless - a box whose walls are noise measures nothing.

Where a side has no zone the bound is simply **absent**, and `room_vol` is
`None` rather than a large number. Open air above is a real reading and it is
not the same as a distant ceiling: one says the target is unbounded by
structure, the other says it is far away. Substituting a number for the first
would make them indistinguishable in the record, which is the mistake
`_reaches` already documents on `depth_vol`.

## Not a gate

Nothing here refuses anything. The range lands on the signal as features and
in the journal beside the outcome, so the outcome machinery gets to say whether
position within a range predicts anything before a strategy is allowed to
read it. This is the order [features.md](../../../research/features.md) argues
for and the one `drawn_by_n` was added under.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...logging import get_logger
from .confluence import ORDER, rank

log = get_logger(__name__)


class Bound(Protocol):
    """What a range needs from whatever is acting as a wall."""

    price: float


# Frozen, and deliberately **not** slotted, which is the opposite of the
# convention everywhere else in this package.
#
# `store._schema` fingerprints every slotted dataclass here and refuses saved
# state whose fingerprint differs - the guard that stops a restore crashing on
# a field it predates. It cannot tell a persisted shape from any other slotted
# one, so adding this class with `slots=True` changed the hash from
# 1c464f3d6dbfafb5 to b374ed5f783c697a and would have cold-started 58MB of
# learned state - every level, the break model, weeks of touches - for a value
# object that is built per call, read once and discarded, and is not
# `Restorable` and never persisted.
#
# Losing that to a false positive is the wrong trade. The slots were buying a
# little memory on a short-lived object; the fingerprint is protecting the
# evidence every measurement in research/ is computed from.
@dataclass(frozen=True)
class LevelRange:
    """Where price sits between the nearest structure above and below it."""

    feed: str
    price: float
    #: The nearest zone below price, and above it. Either may be absent, which
    #: is open air on that side rather than a distant wall.
    lower: Any = None
    upper: Any = None
    #: One volatility unit as a price distance, for the readings below.
    unit: float = 0.0

    @property
    def bounded(self) -> bool:
        """Whether price is enclosed on both sides - the case the name implies."""
        return self.lower is not None and self.upper is not None

    @property
    def width(self) -> float:
        """The range's height in price, or 0.0 when it is open on a side."""
        if not self.bounded:
            return 0.0
        return abs(self.upper.price - self.lower.price)

    @property
    def width_vol(self) -> float:
        """The same in volatility units, which is what compares across feeds."""
        return self.width / self.unit if self.unit > 0 else 0.0

    @property
    def room_up_vol(self) -> float | None:
        """How far a long can run before it meets structure. `None` is open air."""
        if self.upper is None or self.unit <= 0:
            return None
        return max(0.0, (self.upper.price - self.price) / self.unit)

    @property
    def room_down_vol(self) -> float | None:
        """The same for a short."""
        if self.lower is None or self.unit <= 0:
            return None
        return max(0.0, (self.price - self.lower.price) / self.unit)

    @property
    def position(self) -> float | None:
        """Where price sits in the range: 0.0 at the floor, 1.0 at the ceiling.

        `None` when either side is open, because a position needs both walls to
        mean anything - and 0.5 for "we do not know" would be a reading in the
        middle of the range, which is the most misleading answer available.
        """
        if not self.bounded:
            return None
        width = self.width
        if width <= 0:
            return None
        return min(1.0, max(0.0, (self.price - self.lower.price) / width))

    def features(self, prefix: str = "") -> dict[str, float]:
        """The readings, for the signal and the journal.

        Absent bounds are **omitted rather than zeroed**. A missing key is a
        missing reading downstream; a zero is a claim that the ceiling is at
        the current price, which is the opposite of open air.
        """
        out: dict[str, float] = {}
        up, down = self.room_up_vol, self.room_down_vol
        if up is not None:
            out[f"{prefix}room_up_vol"] = up
        if down is not None:
            out[f"{prefix}room_down_vol"] = down
        if self.bounded:
            out[f"{prefix}range_width_vol"] = self.width_vol
            here = self.position
            if here is not None:
                out[f"{prefix}range_position"] = here
            # The bounds as prices, for the alert - a person placing an entry
            # wants the number to type, and "2.1v above" is not it.
            #
            # Raw prices in a feature dictionary are not free: `facto` learns
            # from every key it is given, so a value in the thousands sits
            # beside ratios in the units. `level` is already there and already
            # does this, so these two do not introduce the problem - but they
            # do enlarge it, and it is worth someone deciding on purpose rather
            # than inheriting. `racing` is unaffected: it reads `NAMES` only.
            out[f"{prefix}range_upper"] = self.upper.price
            out[f"{prefix}range_lower"] = self.lower.price
        return out

    def __str__(self) -> str:
        floor = f"{self.lower.price:g}" if self.lower is not None else "open"
        roof = f"{self.upper.price:g}" if self.upper is not None else "open"
        if not self.bounded:
            return f"{self.feed} {floor} .. {roof}"
        return (
            f"{self.feed} {floor} .. {roof} - {self.width_vol:.1f}v wide, "
            f"price {self.position:.0%} up it"
        )


#: The timeframe a swing's range is drawn on, whatever timeframe triggered it.
#:
#: A range is only a range if both walls are the same kind of object, and the
#: call's own interval is the wrong anchor for a strategy that *enters* below
#: the hour on purpose. `swing-level` triggers on 15m and 30m, so anchoring to
#: the call gave it a 15m box - two prices a quarter of an hour of auction
#: paused at - and asked a trade held for a day to aim at one of them.
#:
#: 4h is the one timeframe a day-long trade both respects and can cross, and
#: it is where `service` asks the origin model for the swing's walls.
ANCHOR = "4h"


@dataclass(frozen=True)
class Edge:
    """A wall that is a price and nothing else - what `Bound` actually needs.

    Not slotted, for the reason the block above `LevelRange` gives at length:
    `store._schema` fingerprints slotted dataclasses in this package, and a
    value object built per call is not worth cold-starting 58MB of state over.
    """

    price: float


def between_origins(
    below: float | None,
    above: float | None,
    price: float,
    unit: float,
    *,
    feed: str = "",
) -> LevelRange:
    """The range between the two nearest origins - **the swing's box.**

    An origin is where a violent move began, so the interest that stopped the
    last advance is still resting there. That is a different object from a
    confluence zone, which is a price several timeframes happen to have drawn
    a level at, and the difference is not academic: measured over 4,117
    published calls on 2026-09-07, at 4h the confluence box is **385bps wide
    against the origin box's 71bps**, and wider on 2,711 of 2,724.

    A box of 3.85% is not a box a trade held for a day moves inside. Its far
    wall is a target price cannot reach, and a position inside it is a reading
    about a range that will never be traversed - the same failure the 15m
    anchor had, arrived at from the other direction.

    The confluence-anchored version of this (`anchored`, with a `PLACED_BY`
    ceiling on which timeframes could place a wall) was removed rather than
    left beside it. It was a careful answer to the wrong question, and leaving
    it would have meant someone finding it and using it.

    Bounds are the origins' **near edges** - `high` for the one below, `low`
    for the one above - because the tradeable room ends where the band starts.
    Either side may be absent, which is open air rather than a distant wall.
    """
    return LevelRange(
        feed=feed,
        price=price,
        lower=Edge(below) if below is not None else None,
        upper=Edge(above) if above is not None else None,
        unit=float(unit),
    )


def within(zones: Any, interval: str, placed_by: str = "") -> list[Any]:
    """Zones significant at `interval` or above and placed at `placed_by` or below.

    **A range with a 1h ceiling and a 5m floor is not a range.** The two bounds
    have to be the same kind of object or the box measures nothing: a 5m zone
    is a place price paused for a few bars, a 1h zone is a place it turned, and
    the distance between one of each is a number with no meaning attached.

    So the span is filtered to the call's own timeframe and coarser. Higher is
    the safe direction - a 4h zone is a real boundary for a 15m trade, while a
    15m zone is noise inside a 4h one - which is the same asymmetry
    `confluence` already relies on when it lets the higher timeframe carry the
    significance and the lower carry the placement.

    A zone with no members has no span and is dropped: it cannot be shown to
    belong.

    `placed_by` is the other end, and it reads the **other** property. A zone
    is not excluded for reaching into the daily or the week - that is what
    makes it significant - it is excluded when *nothing finer agrees with it*,
    because then the only price on offer is one a week of auction produced, and
    a box built from two of those is not a box a day-long trade moves inside.
    Empty means no such requirement, which is what a caller without an opinion
    wants.
    """
    if not interval:
        return list(zones)
    # `ORDER` runs fine to coarse, so a coarser timeframe has the **higher**
    # rank: significance is `>=` and placement is `<=`.
    floor = rank(interval)
    roof = rank(placed_by) if placed_by else len(ORDER) + 1
    kept = []
    for zone in zones:
        span = getattr(zone, "span", "")
        # A stub with a span and no precision is placed by its own span, which
        # is what a single-timeframe wall means.
        placed = getattr(zone, "precision", "") or span
        if span and rank(span) >= floor and rank(placed) <= roof:
            kept.append(zone)
    return kept


def level_range_of(
    zones: Any,
    price: float,
    unit: float,
    *,
    feed: str = "",
    interval: str = "",
    placed_by: str = "",
) -> LevelRange:
    """The nearest zone below price and the nearest above it.

    `unit` is one volatility unit as a price distance - the same conversion
    every other reading here uses, passed in rather than recomputed so a
    range cannot disagree with the signal it is attached to.

    `interval` keeps the two bounds comparable: only zones drawn on that
    timeframe or a coarser one are considered, because a ceiling from 1h and a
    floor from 5m are not two ends of one thing. Empty means take them all,
    which is what the tests and any caller without a timeframe want.

    A zone sitting exactly at `price` is treated as **below**, matching
    `Level.side_of`, which resolves the same tie the same way. Consistency
    matters more than the choice: price is at the level either way, and the two
    modules disagreeing would put the same touch on different sides of its own
    range.
    """
    lower = upper = None
    for zone in within(zones, interval, placed_by):
        at = getattr(zone, "price", None)
        if not isinstance(at, int | float) or not at:
            continue
        if at <= price:
            if lower is None or at > lower.price:
                lower = zone
        elif upper is None or at < upper.price:
            upper = zone
    return LevelRange(feed=feed, price=price, lower=lower, upper=upper, unit=float(unit))
