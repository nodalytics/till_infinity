"""More than one clock on one strategy, and the look-ahead that makes it wrong.

A desk subscribes to one bar type. Trading a signal on M15 while reading trend
on H1 or D1 needs several, and Nautilus supports that directly - a strategy may
`subscribe_bars` any number of times and `on_bar` is handed whichever closed.
What it does not supply is the part that makes the second clock honest.

## The prior is good, and it is measured

`the-clock-and-the-loop-compose` is the reason to build this: the clock and the
loop together read **+1567 against +848 and +518 apart**, so composing across
clocks pays more than either alone. This is not a speculative feature.

## The one invariant, and it is enforced here rather than documented

**A higher timeframe is readable only from its last *closed* bar.** The H1 bar
containing an M15 signal has not finished when that signal fires, and three of
its four constituent bars are in the future. Reading it is look-ahead, it is
the single commonest multi-timeframe bug, and it does not announce itself: the
backtest simply gets better.

`Frames.ready` is the whole point of this module. It returns context only from
bars that closed **at or before** the signal bar's close, so a forming bar
cannot be read at all. A caller that wants the look-ahead has to not use this.

This desk has the failure on record in the same shape:
`open-gap-filters-are-lookahead` - `drawing.gaps` emits only *unfilled* gaps,
and as a bias that read +0.50R a trade. A forming higher bar is the same
mistake with a clock instead of a filter.

## What a second clock must not share

**One indicator instance per bar type.** An indicator registered against two
bar types folds both series into one state, so an ATR fed M15 and H1 together
measures neither. `register_indicator_for_bars` is per bar type for this
reason and `Frames.detectors` keys them that way.

**Spans and bar counts both, when comparing clocks.**
`the-Q-clock-is-an-activity-clock` records that volume time absorbs 76% of the
clock effect and still pays on top - and that the comparison is only meaningful
with *both* the span and the bar count matched across clocks. 500 M15 bars and
500 D1 bars are not the same experiment, and neither are 76 days of each.

**An i.i.d. control, if the second clock is not a time clock.**
`clocks-must-pass-an-iid-control` is a refutation: range time looked best on 8
of 8 markets and invented clustering at **5.3x** on a process specified to have
none. A tick, volume or range clock has to read nothing on i.i.d. input before
any result on it means anything.

**External bars for a context frame, not composite ones.** An internally
aggregated bar type **back-fills a session gap** - a 48.5-hour hole becomes
194 empty M15 bars, measured this session - so a coarse frame built by
aggregation inside the engine will silently contain bars no session produced,
and anything measuring a session effect on it is measuring a feed with no
sessions in it.

That is a warning about what to *read*, not a refusal to construct: a
composite signal frame is legitimate and `strategies/structure.py` uses one,
building M15 from the M1 feed because the rule is specified that way. So
`seconds_of` reads the span off the primary spec and ignores the aggregation
source, and the judgement about back-filling stays with whoever chooses the
context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Seconds in each interval this desk names, for ordering frames coarsest
#: last. Keyed by the suffix `node/desks.spec_for` accepts.
SECONDS: dict[str, float] = {
    "1m": 60.0,
    "3m": 180.0,
    "5m": 300.0,
    "15m": 900.0,
    "30m": 1_800.0,
    "1h": 3_600.0,
    "2h": 7_200.0,
    "4h": 14_400.0,
    "1d": 86_400.0,
    "1w": 604_800.0,
}


def seconds_of(bar_type: Any) -> float:
    """How long one bar of `bar_type` covers, or 0.0 if it is not a time bar.

    Parsed from the specification rather than taken from a table of our own,
    so a bar type the engine accepts and this does not is a zero rather than a
    wrong number. Zero means "not comparable on a clock", which `Frames`
    refuses rather than guessing at.
    """
    # **The composite tail first, then split from the right.** Two parsing
    # bugs, both caught by other files' tests and neither by this module's:
    #
    # A composite bar type names what it was aggregated *from* after an `@`,
    # as in `XAU/USD.SIM-15-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL`, which
    # `strategies/structure.py` uses as its signal frame. The span is the
    # primary spec's; the source spec does not change it.
    #
    # And a symbol may contain a hyphen - `ETHUSDT-PERP.BINANCE` - so the
    # split is from the right. A bar type is
    # `{instrument}-{step}-{unit}-{price}-{source}`, so the last four fields
    # are fixed and the instrument is whatever precedes them. From the left,
    # a perpetual read a step of "PERP.BINANCE".
    primary = str(bar_type).split("@", 1)[0]
    parts = primary.rsplit("-", 4)
    if len(parts) < 5:
        return 0.0
    try:
        step = float(parts[1])
    except ValueError:
        return 0.0
    unit = parts[2].upper()
    units = {
        "SECOND": 1.0,
        "MINUTE": 60.0,
        "HOUR": 3_600.0,
        "DAY": 86_400.0,
        "WEEK": 604_800.0,
    }
    return step * units[unit] if unit in units else 0.0


@dataclass(frozen=True, slots=True)
class Reading:
    """One frame's state, with the close it came from.

    **The close is the field that matters.** A reading without the time of the
    bar that produced it cannot be checked for look-ahead, so this carries it
    and `Frames.ready` compares it rather than trusting a caller.
    """

    bar_type: str
    closed_at: float
    value: Any

    def known_by(self, when: float) -> bool:
        """Whether this was knowable at `when`. Closed *at* `when` counts: a
        bar's close is the instant its values are final."""
        return self.closed_at <= when


@dataclass(slots=True)
class Frames:
    """The clocks one strategy reads, and which of them it may act on.

    `signal` is the frame a decision fires on. `context` are coarser frames
    read for state and never for a trigger - a trigger on the coarse frame is
    a different strategy on that frame, not this one with context.
    """

    signal: str
    context: tuple[str, ...] = ()
    #: The last closed reading per frame. Written by `observe`, read by
    #: `ready`, and never pre-seeded: a frame with no closed bar yet has no
    #: reading, which is the honest state at the start of a run.
    seen: dict[str, Reading] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.signal:
            raise ValueError("a strategy needs a signal frame to fire on")
        own = seconds_of(self.signal)
        if own <= 0.0:
            raise ValueError(
                f"{self.signal} is not a time bar, so no frame can be ordered "
                f"against it - match spans and bar counts by hand instead, and "
                f"give a non-time clock an i.i.d. control before trusting it"
            )
        for frame in self.context:
            span = seconds_of(frame)
            if span <= 0.0:
                raise ValueError(f"{frame} is not a time bar and cannot be a context frame")
            if span < own:
                raise ValueError(
                    f"{frame} is finer than the signal frame {self.signal}. Context "
                    f"is read for state on a slower clock; a finer frame is a "
                    f"different signal and belongs in its own strategy."
                )
            if frame == self.signal:
                raise ValueError(
                    f"{frame} is the signal frame. Reading it as context would fold "
                    f"one series into two states and double its weight."
                )

    @property
    def all(self) -> tuple[str, ...]:
        """Every frame to subscribe, signal first."""
        return (self.signal, *self.context)

    def observe(self, bar_type: Any, closed_at: float, value: Any) -> None:
        """Record a frame's state from a bar that has **closed**.

        Nautilus delivers a bar at its close, so a caller in `on_bar` is
        always recording a closed bar. The name says so because the invariant
        belongs at the call site too: anything reading a forming bar must not
        reach this.
        """
        key = str(bar_type)
        self.seen[key] = Reading(bar_type=key, closed_at=closed_at, value=value)

    def ready(self, when: float) -> dict[str, Any]:
        """Every context frame knowable at `when`, by frame.

        **The look-ahead guard.** A frame whose last close is after `when` is
        left out entirely rather than returned stale-flagged, because a
        caller that has to remember to check a flag is a caller that will
        forget. A frame absent from the result has nothing knowable yet.
        """
        out: dict[str, Any] = {}
        for frame in self.context:
            found = self.seen.get(frame)
            if found is not None and found.known_by(when):
                out[frame] = found.value
        return out

    def complete(self, when: float) -> bool:
        """Whether every context frame has a reading knowable at `when`.

        For a rule that must not fire on partial context. Separate from
        `ready` because "trade on what is known" and "wait for all of it" are
        both legitimate and the choice is the strategy's.
        """
        return len(self.ready(when)) == len(self.context)

    def stale(self, when: float) -> dict[str, float]:
        """How old each knowable context reading is, in seconds.

        A D1 frame read 20 hours after its close is still causal and still
        nearly a day out of date, which is a fact a decision may want and
        cannot get from `ready` alone.
        """
        return {frame: when - self.seen[frame].closed_at for frame in self.ready(when)}
