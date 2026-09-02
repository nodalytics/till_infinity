"""One strategy, parameterised, instead of nine racing each other.

## Why the nine are really one

`level-scalp`, `thesis-only`, `snap`, `runner`, `sweep-aware`, `swing-level`,
`approach-scalp`, `fade-to-value` and `confluence-scalp` read the same signal,
apply the same gates and take the same side. What separates them is a handful
of numbers: how wide the stop, how far the target, how tight the trail, how
long the clock runs, and whether the entry is rested or paid for. Several of
their own docstrings say so outright - *"same entries, same anchors, same
gates, same stop. Only the exit moves."*

So they are not nine strategies. They are **nine points in one parameter
space**, and the machinery that picks between them is a fixed list in an
environment variable.

Measured on 2026-09-02, that list is doing the choosing: entry counts track
queue position almost perfectly, and the strategy at the front of the queue
(`thesis-only`, 65 trades) scores **worst** on the common stream at -0.231R,
while `level-scalp` at position eight took two trades and scores +0.097R over
the largest sample. See research/failing.md.

## What this class is

The parameter vector, made explicit. `PRESETS` recovers the named strategies as
points, so nothing is lost and the comparison becomes arithmetic rather than
architecture. A new candidate is a new vector, not a new class - which is what
lets something propose one that nobody wrote.

## Why it has no style

There is no scalping and no swing trading here, only opportunities, and they
last from seconds to days. `style` survives in this codebase as the thing that
picks a *ceiling* (`max_hold` against `max_hold_swing`), not as a claim about
the trade, and this carries `swing` for that reason alone.

`hold_seconds` is **0**, which `hold_for` reads as "the ceiling and nothing
tighter". That is deliberate and it is the measured part: 91 closes ended on
the clock rather than on a barrier, and replaying them with the clock removed
turns **-10.58R into -0.91R**. Of the 86 that then resolved, 72 did so within
the hour - so the clock was not wrong by days, it was wrong by minutes.

## Where the defaults come from

* **The stop is tight** (`stop_multiple` 1.0), because the tight-stopped
  strategies are the ones that score. `thesis-only` runs a 4.0v stop and has
  the worst mean R on the common stream; its live record is a +0.66R average
  target against a -1.12R average stop, which is winning small and losing big.
* **The target is far** (`target_multiple` 3.0) and the **trail is what ends
  the trade**. This is `runner`'s thesis, and `runner` fails for a reason that
  is now fixed rather than for the thesis being wrong: 16 of its 26 exits were
  the four-hour clock, so the tail it exists to catch never had time to arrive.
* **The trail is tight enough to guard an open profit** (`trail_vol` 1.0).
  Giving back an open profit was reported from live observation and could not
  be measured at all until 2026-09-02, because `best_r` was recorded as exactly
  0.000 on all 188 closes that carried it.
* **The entry is rested**, because parked entries beat market entries on the
  common stream - 50% win against 39% - though on 20 closes against 162.

**The honest caveat on the target.** The book's worst reward-to-risk bucket is
RR 1.5+ at -12.66 a close and a 21% win rate, and a far target raises RR. The
argument for doing it anyway is that every one of those observations comes from
a trade whose exit was a fixed target or a clock, never a trail on a trade
given room to run. That is a claim this class exists to test, not one it
assumes - and it is testable, because a strategy listed last is shadow-scored
by `_also_wanted` on every signal without ever placing an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .scalper import LevelStrategy
from .strategy import register


@dataclass(frozen=True, slots=True)
class Shape:
    """One point in the space the named strategies occupy.

    Every field is a number a strategy already carries; naming them together is
    the whole idea. A proposal from a search or a learner is an instance of
    this, and needs no new class, no new magic and no new registration.
    """

    #: Stop distance as a multiple of the call's own risk estimate.
    stop: float = 1.0
    #: Target as a multiple of the modelled push.
    target: float = 3.0
    #: Trail distance in volatility units. Zero disables the trail.
    trail: float = 1.0
    #: Move the stop to break even once this many R in front. Zero disables it.
    protect: float = 1.0
    #: Seconds to hold. **Zero means the deployment ceiling and nothing
    #: tighter**, which is the point - see the module docstring on the clock.
    hold: float = 0.0
    #: How much of a retracement to wait for before entering, as a fraction.
    #: 1.0 rests the entry; 0.0 pays the market.
    pullback: float = 1.0
    #: A floor on the stop in volatility units, under which `stop` cannot take
    #: it. This is the dimension that actually separates `thesis-only`: its
    #: `stop_multiple` is 1.0 like everything else, and its wide stop comes
    #: from `Settings.thesis_stop_vol` reaching it through `stop_floor_vol`.
    #: Discovering that cost a failing test, which is the right way to find it.
    floor: float = 1.0

    def named(self) -> str:
        return (
            f"stop{self.stop:g}/target{self.target:g}/trail{self.trail:g}"
            f"/protect{self.protect:g}/hold{self.hold:g}/pull{self.pullback:g}"
        )


#: The named strategies as points, so the space is anchored to things that have
#: actually run. Not used by the class - this is the map between the old
#: architecture and the new one, and the reference a search starts from.
PRESETS: dict[str, Shape] = {
    # Read off the classes rather than written by hand, and two of them are the
    # **same point**: `level-scalp` and `sweep-aware` have identical exits and
    # differ only in an extra entry gate. `fade-to-value` and `approach-scalp`
    # differ from them by a hold and nothing else. That is the argument for
    # this module in one table.
    "level-scalp": Shape(stop=1.0, target=1.0, trail=0.0, protect=0.0, hold=0.0, pullback=0.0),
    "sweep-aware": Shape(stop=1.0, target=1.0, trail=0.0, protect=0.0, hold=0.0, pullback=0.0),
    "thesis-only": Shape(
        stop=1.0, target=1.0, trail=0.0, protect=0.0, hold=0.0, pullback=0.0, floor=4.0
    ),
    "confluence-scalp": Shape(stop=1.5, target=1.0, trail=0.0, protect=0.0, hold=0.0, pullback=0.0),
    "snap": Shape(stop=1.0, target=1.0, trail=0.75, protect=0.5, hold=120.0, pullback=0.0),
    "fade-to-value": Shape(
        stop=1.0, target=1.0, trail=0.0, protect=0.0, hold=14400.0, pullback=0.0
    ),
    "approach-scalp": Shape(
        stop=1.0, target=1.0, trail=0.0, protect=0.0, hold=14400.0, pullback=0.0
    ),
    "runner": Shape(stop=1.0, target=3.0, trail=1.0, protect=1.0, hold=14400.0, pullback=0.0),
    "swing-level": Shape(stop=1.5, target=2.5, trail=4.0, protect=1.5, hold=86400.0, pullback=1.0),
}


@register
class Opportunity(LevelStrategy):
    """The parameterised strategy. See the module docstring.

    Listed **last** while it proves itself. `_also_wanted` evaluates every
    strategy that did not take a signal and journals what it would have done,
    so a strategy at the bottom of the list is scored on every signal in the
    book at the cost of one arithmetic pass and no risk at all. It owns a trade
    only when everything above it has refused one.
    """

    name: ClassVar[str] = "opportunity"
    description: ClassVar[str] = (
        "One parameterised strategy: tight stop, far target, and a trail that ends "
        "the trade rather than a clock."
    )

    #: The ceiling picker, not a claim about the trade. See the docstring.
    style: ClassVar[str] = "swing"

    #: Empty, so it triggers on whatever the deployment allows. An opportunity
    #: is not a timeframe, and the named strategies split 1m-30m from 1h-1w for
    #: reasons that were about holding periods rather than about the level.
    entries: ClassVar[tuple[str, ...]] = ()

    #: Agreement from anywhere other than the entry bar. `anchored` already
    #: excludes the entry interval, so this reads as "some other timeframe sees
    #: this level too" at every speed rather than naming a hierarchy.
    context: ClassVar[tuple[str, ...]] = ("15m", "30m", "1h", "2h", "4h", "1d", "1w")

    #: The defaults, as a `Shape`, expanded into the fields the base class
    #: reads. Kept beside them so the vector and the knobs cannot drift apart.
    shape_of: ClassVar[Shape] = Shape()

    stop_multiple: ClassVar[float] = 1.0
    target_multiple: ClassVar[float] = 3.0
    trail_vol: ClassVar[float] = 1.0
    break_even_at: ClassVar[float] = 1.0
    #: Zero: the ceiling decides, not a clock of this strategy's own.
    hold_seconds: ClassVar[float] = 0.0
    pullback_fraction: ClassVar[float] = 1.0
