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

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from .models import SymbolSpec, Tick, Verdict
from .scalper import LevelStrategy
from .strategy import register

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .policy import Policy


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

    # ---------------------------------------------------------------------
    # The rest of the decision surface. Everything above shapes the trade once
    # it exists; everything below decides whether it exists, how it is
    # entered, and how it is unwound. `Settings` already honours each of these
    # as a deployment-wide constant - the point of naming them here is that
    # they become **per-opportunity** choices instead.
    # ---------------------------------------------------------------------

    #: Take it at all. The leave arm.
    take: bool = True

    #: Leave the resting price with the broker as a limit order, rather than
    #: polling and firing at market. `Settings.entry_pending`. This is the
    #: market-or-limit choice, and it is not cosmetic: a poller misses the deep
    #: wick that a limit fills, and a limit cannot change its mind.
    resting: bool = True

    #: Fraction of the risk budget this opportunity is worth, in (0, 1]. Only
    #: ever reduces - `scaling.combined` and the guards keep the ceiling, and
    #: a policy that can size *up* is one that turns an estimation error into a
    #: margin call.
    size: float = 1.0

    #: R multiple at which part of the position comes off, and how much.
    #: `Settings.scale_out_at` and `scale_out_fraction`. Zero banks nothing.
    #:
    #: This is the honest middle of the target argument: the push distribution
    #: runs median 2.24v against p90 4.93v, and a single exit has to pick which
    #: half to serve. Banking part at the median and letting the rest run
    #: serves both - and it is the direct answer to giving back an open profit,
    #: which `best_r` can finally measure.
    bank_at: float = 0.0
    bank_share: float = 0.5

    def named(self) -> str:
        """A stable identity for this point, so a learner can key on it."""
        if not self.take:
            return "leave"
        return (
            f"stop{self.stop:g}f{self.floor:g}/target{self.target:g}"
            f"/trail{self.trail:g}/protect{self.protect:g}/hold{self.hold:g}"
            f"/pull{self.pullback:g}{'L' if self.resting else 'M'}"
            f"/size{self.size:g}/bank{self.bank_at:g}x{self.bank_share:g}"
        )

    #: Which fields the engine reads today, against which are still deployment
    #: constants that a per-opportunity choice would have to be threaded into.
    #: Named here rather than left implicit, because a policy that varies a
    #: dimension nothing honours is a policy that appears to work and does not.
    WIRED: ClassVar[frozenset[str]] = frozenset(
        {"stop", "target", "trail", "protect", "hold", "pullback", "floor"}
    )
    PENDING: ClassVar[frozenset[str]] = frozenset(
        {"take", "resting", "size", "bank_at", "bank_share"}
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

    #: Momentum leads; the candle confirms it. An opportunity that lasts
    #: hours should not be opened on a bar that closed before it.
    momentum_leads: ClassVar[bool] = True

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

    #: Attached by the service when one exists. Absent means the class
    #: defaults, which are the measured ones - so this strategy is a fixed,
    #: reasonable shape until something has learned enough to improve on it,
    #: and never a random one.
    policy: Policy | None = None

    #: The arm the last decision used, so the outcome can credit the right one.
    #: A shape chosen and then scored against a different name is worse than
    #: not scoring it.
    arm: str = ""

    def consider(
        self,
        payload: dict[str, Any],
        *,
        spec: SymbolSpec,
        tick: Tick,
        equity: float,
        positions: Sequence[Any] = (),
        peak: float = 0.0,
    ) -> Verdict:
        """Pick a shape for this opportunity, then decide with it.

        **Spelled out rather than `**kw`.** A test walks `STRATEGIES` asserting
        every `consider` accepts what the service passes, and it exists because
        widening the base signature once left two overrides behind and stopped
        the desk trading for two hours. `**kw` passes at runtime and fails that
        test, which is the right way round.

        Safe to set instance attributes here: `consider` is synchronous, so one
        signal is shaped and decided before the next is looked at. The async
        wrapper is around this, not inside it.
        """
        policy = self.policy
        if policy is not None:
            shape, why = policy.pick(
                str(payload.get("feed") or ""), str(payload.get("interval") or "")
            )
            self.arm = shape.named()
            self._wear(shape)
            payload.setdefault("features", {})
            if isinstance(payload["features"], dict):
                payload["features"]["arm_reason"] = why
        return super().consider(
            payload, spec=spec, tick=tick, equity=equity, positions=positions, peak=peak
        )

    def _wear(self, shape: Shape) -> None:
        """Take on a point in the space, as instance attributes.

        Only the dimensions the engine actually reads - `Shape.WIRED`. Setting
        the others would produce a policy that appears to vary something
        nothing honours, which is the defect this repository keeps finding.
        """
        self.stop_multiple = shape.stop
        self.target_multiple = shape.target
        self.trail_vol = shape.trail
        self.break_even_at = shape.protect
        self.hold_seconds = shape.hold
        self.pullback_fraction = shape.pullback
