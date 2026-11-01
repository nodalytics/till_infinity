"""Momentum: how far price has run, how fast, and who is moving it.

Grouped the way `nautilus_trader.indicators.momentum` is grouped, and holding
what that module does not: a CUSUM filter that accumulates rather than
averaging over a fixed window, three exponential speeds per feed with an
agreement test, and a tick momentum that works off quote revisions because
this desk's main venue sends no trades.

**Nautilus has RSI, stochastics, rate of change, CCI, Chande and the
efficiency ratio** - take those from there rather than writing them. One
caution: `momentum.EfficiencyRatio` is arithmetically wrong, reporting
`(period - 1) / period` on a straight line where the ratio is 1.0 by
definition. `trend.ratio` is the corrected one and a test pins the fault.

`volume.OnBalanceVolume` and `volume.Pressure` are the nearest things to
`TickMomentum` and neither fits: both sign by close direction off bars, and
neither reads `aggressor_side` or works from quote revisions.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

from till_infinity.utils.state import Restorable

from .bars import (
    NANOS,
    Reading,
    bar_input,
    check_feed,
    check_scale,
    read,
    reset_state,
    tick_input,
)

# ==========================================================================
# from cusum.py
# ==========================================================================

EVENTS_KEPT = 64

#: Volatility units of net directional progress that constitute an event.
#:
#: Kept as the ceiling rather than the working value. Measured over 59,982
#: resolutions, a 2.0v threshold is **silent through 47.5% of all moves** - the
#: median realised push is 2.07v, so it confirms after essentially the whole
#: move has happened, which is useless for timing an entry. See
#: `adaptive_threshold`.
THRESHOLD = 2.0

#: The share of a typical move the filter should fire inside. A filter meant to
#: time an entry has to speak partway through, not at the end.
SHARE = 0.35

#: The hard floor, below which this is reading noise rather than momentum. Only
#: 1.9% of measured moves are smaller than this, so the floor costs almost
#: nothing and stops a quiet instrument from firing on every tick.
FLOOR = 0.5


def adaptive_threshold(
    typical_push: float, *, share: float = SHARE, floor: float = FLOOR, ceiling: float = THRESHOLD
) -> float:
    """A threshold sized to the moves this instrument actually makes.

    See `structures-context-cusum.md` in research/docs.
    """
    if typical_push <= 0:
        return floor
    return max(floor, min(ceiling, share * typical_push))


@dataclass(slots=True)
class Event(Restorable):
    """One threshold crossing."""

    index: int
    when: float
    price: float
    #: "up" or "down" - which accumulator fired.
    side: str
    #: How far the accumulator had run when it fired, in volatility units.
    run_vol: float

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "when": self.when,
            "price": round(self.price, 8),
            "side": self.side,
            "run_vol": round(self.run_vol, 4),
        }


@dataclass(slots=True)
class Cusum(Indicator, Restorable):
    """A symmetric CUSUM filter over a price series.

    Stateful across calls, so it can be fed a stream one price at a time and
    keep its accumulators - which is the point of it over a windowed measure.
    """

    threshold: float = THRESHOLD
    up: float = 0.0
    down: float = 0.0
    last: float = 0.0
    started: bool = False
    events: deque[Event] = field(default_factory=lambda: deque(maxlen=EVENTS_KEPT))

    # ---------------------------------------------------- the engine's path
    #: Which float of a bar this reads when the Nautilus engine feeds it.
    #: Unused when a caller drives `push` directly. See `bars.Reading`.
    source: Reading = Reading.CLOSE
    #: One volatility unit in price, fixed. Zero takes the unit off each bar
    #: through `unit_from` instead, which is the default.
    unit: float = 0.0
    #: Where a per-bar unit comes from. The **range**, because the range-based
    #: estimator beats close-to-close as a volatility driver by a ratio of
    #: 0.648 within strata on FX and on 371 of 392 equities, and the advantage
    #: grows as the window shortens - which is the regime a one-bar unit is in.
    unit_from: Reading | None = Reading.RANGE
    #: EWMA half-life in bars for `unit_from`. Zero uses each bar's own
    #: reading, which is noisier but carries no warmup.
    unit_span: int = 0
    _bar_prev: float | None = field(default=None, repr=False)
    _bar_scale: float = field(default=0.0, repr=False)

    # ------------------------------------------------------ the tick path
    #: EWMA half-life in **ticks** for the tick-path scale. A tick has no
    #: range, so the unit is an average of how far price moves between prints.
    #: 200 rather than the bar path's handful, because tick noise is the thing
    #: being averaged out and there is a lot more of it.
    tick_span: int = 200
    _tick_prev: float | None = field(default=None, repr=False)
    _tick_scale: float = field(default=0.0, repr=False)
    #: Which feed has fed this instance: "bars" or "ticks". One Cusum has one
    #: pair of accumulators, so two feeds would interleave two clocks into
    #: them - see `_feed`.
    _fed: str = field(default="", repr=False)

    #: The fields a reset keeps. Everything else is state - note that `up` and
    #: `down` here are the two accumulators, not a direction.
    _CONFIG: ClassVar[frozenset[str]] = frozenset(
        {"threshold", "source", "unit", "unit_from", "unit_span", "tick_span"}
    )

    def __post_init__(self) -> None:
        """Hand Nautilus its parameters, and refuse an unset scale."""
        Indicator.__init__(self, [self.threshold])
        check_scale(type(self).__name__, self.source, self.unit, self.unit_from)

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen an observation.

        Called when the engine rewinds. Not `restart`, which zeroes the two
        accumulators and keeps the price history. Every field outside `_CONFIG`
        goes back to its initial value - see `bars.reset_state`.
        """
        reset_state(self, self._CONFIG)
        self._set_has_inputs(False)
        self._set_initialized(False)

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point, once registered for a bar type.

        `push` wants a **price**, so `reading` wants to be a level. Feeding it
        a return makes it accumulate changes in the return, which is a
        different and much noisier question.
        """
        check_feed(self, "bars")
        value, scale = bar_input(self, bar)
        if value is None or scale <= 0.0:
            return
        self._set_has_inputs(True)
        self.push(value, scale, bar.ts_event / NANOS, len(self.events))
        if not self.initialized and self.started:
            self._set_initialized(True)

    def handle_quote_tick(self, tick: Any) -> None:
        """Nautilus's entry point for quotes, using the **mid**.

        A CUSUM accumulates a price series and a tick is a price, so this is
        the same detector on a faster clock - with one thing that does not
        carry over. The threshold is in volatility units and is scale-free, but
        the *rate* at which it is crossed is not: the same threshold fires far
        more often per hour at tick rate than on bars, so an event rate
        measured on bars says nothing about this. See `bars.tick_input`.
        """
        self._on_tick(tick)

    def handle_trade_tick(self, tick: Any) -> None:
        """Nautilus's entry point for trades, using the traded price."""
        self._on_tick(tick)

    def _on_tick(self, tick: Any) -> None:
        check_feed(self, "ticks")
        price, scale = tick_input(self, tick)
        if price is None or scale <= 0.0:
            return
        self._set_has_inputs(True)
        self.push(price, scale, tick.ts_event / NANOS, len(self.events))
        if not self.initialized and self.started:
            self._set_initialized(True)

    def restart(self) -> None:
        """Zero both accumulators, after an event has been acted on.

        Keeps `last` and `started`: the accumulation restarts, the price
        series does not. `reset` is Nautilus's, and means the other thing.
        """
        self.up = 0.0
        self.down = 0.0

    def push(self, price: float, unit: float, when: float = 0.0, index: int = 0) -> Event | None:
        """Feed one price. Returns an Event if this one crossed the threshold.

        `unit` is one volatility unit in price, and is taken per call rather
        than stored, because volatility moves and a filter calibrated to last
        week's is measuring the wrong thing this week.
        """
        if not self.started:
            self.last, self.started = price, True
            return None
        if unit <= 0:
            self.last = price
            return None

        change = (price - self.last) / unit
        self.last = price
        # Floored at zero, so an accumulator can be held down by movement the
        # other way but never driven negative. That is what makes this
        # "progress since the last event" rather than a running total of price.
        self.up = max(0.0, self.up + change)
        self.down = min(0.0, self.down + change)

        # **`restart`, not `reset`.** This means *an event has fired, so
        # accumulate from here* - it keeps `last` and `started`, because the
        # price series did not restart. `reset` is Nautilus's and means *this
        # detector has never seen anything*, and these two lines called it for
        # a while after the rename: every event wiped the whole detector, so
        # `has_inputs` and `initialized` went back to False and the filter
        # never accumulated past its first event. The module docstring warned
        # about exactly this and the call sites were missed anyway.
        if self.up >= self.threshold:
            run = self.up
            self.restart()
            return self._record(index, when, price, "up", run)
        if -self.down >= self.threshold:
            run = -self.down
            self.restart()
            return self._record(index, when, price, "down", run)
        return None

    def _record(self, index: int, when: float, price: float, side: str, run: float) -> Event:
        event = Event(index=index, when=when, price=price, side=side, run_vol=run)
        self.events.append(event)
        return event

    def feed(self, times: list[float], prices: list[float], unit: float) -> list[Event]:
        """Run the whole series through. Convenience over `push`."""
        out = []
        for i, price in enumerate(prices):
            when = times[i] if i < len(times) else 0.0
            got = self.push(price, unit, when=when, index=i)
            if got is not None:
                out.append(got)
        return out

    @property
    def pressure(self) -> float:
        """Current net accumulation, in volatility units. Positive is upward.

        The reading *between* events, for anything that wants a continuous
        measure rather than a trigger - how close the market is to having done
        enough in one direction to count.
        """
        return self.up + self.down


#: The timeframes an ensemble reads, all below 1h. Above that the swing's own
#: context timeframes already speak, and they answer a different question:
#: whether the level is real, not whether it is being rejected right now.
SUB_HOUR: tuple[str, ...] = ("1m", "3m", "5m", "15m", "30m")

#: Seconds per interval, kept here rather than imported so this module stays
#: free of the level machinery.
CADENCE: dict[str, float] = {
    "1m": 60.0,
    "3m": 180.0,
    "5m": 300.0,
    "15m": 900.0,
    "30m": 1_800.0,
}


@dataclass
class Ensemble(Restorable):
    """One CUSUM per sub-hour timeframe, read together.

    See `structures-context-cusum.md` in research/docs.
    """

    intervals: tuple[str, ...] = SUB_HOUR
    threshold: float = THRESHOLD
    members: dict[str, Cusum] = field(default_factory=dict)
    seen_at: dict[str, float] = field(default_factory=dict)

    def push(self, price: float, unit: float, when: float = 0.0) -> None:
        """Feed one price to whichever members are due for it."""
        for interval in self.intervals:
            every = CADENCE.get(interval, 0.0)
            if every <= 0:
                continue
            last = self.seen_at.get(interval)
            if last is not None and when - last < every:
                continue
            self.seen_at[interval] = when
            member = self.members.setdefault(interval, Cusum(threshold=self.threshold))
            # Applied on every push, not only at construction. The threshold
            # adapts as the instrument's typical push is re-estimated, and a
            # member built with the old one would keep it forever.
            member.threshold = self.threshold
            member.push(price, unit, when=when)

    @property
    def ready(self) -> int:
        """How many members have seen enough to have an opinion."""
        return sum(1 for m in self.members.values() if m.started)

    @property
    def pressure(self) -> float:
        """The members' mean accumulation, in volatility units.

        The mean rather than the sum, so the reading does not change scale when
        a member is added or is not yet warm - it stays comparable with the
        single-filter reading it replaces, and with `require_turn_vol`, which
        is calibrated in those units.
        """
        warm = [m.pressure for m in self.members.values() if m.started]
        return sum(warm) / len(warm) if warm else 0.0

    @staticmethod
    def _opinion(member: Cusum) -> int:
        """Which way one member is pointing: 1, -1, or 0 for no view.

        **The accumulator alone is not enough.** A CUSUM resets when it fires,
        so a member that has just confirmed a run reads a pressure of exactly
        zero - the strongest case it can report looks identical to a flat
        market. Falling back to the side of its last event is what keeps a
        confirmed run counted as a view rather than an abstention.
        """
        if member.pressure > 0:
            return 1
        if member.pressure < 0:
            return -1
        if member.events:
            return 1 if member.events[-1].side == "up" else -1
        return 0

    @property
    def agreement(self) -> float:
        """Signed share of warm members pointing the same way, -1 to 1.

        See `structures-context-cusum.md` in research/docs.
        """
        warm = [m for m in self.members.values() if m.started]
        if not warm:
            return 0.0
        views = [self._opinion(m) for m in warm]
        return sum(views) / len(warm)


# ==========================================================================
# from speeds.py
# ==========================================================================

WARMUP = 12.0


@dataclass(slots=True)
class Speeds(Indicator):
    """Three speeds over one series per key, and their agreement."""

    half_lives: tuple[float, float, float] = (3.0, 12.0, 48.0)
    #: Observations of one feed before `ready` says yes.
    #:
    #: **12, not the slowest half-life, and the reason is a measurement.** This
    #: used to be `half_lives[-1]` - 48 - on the argument that the slow average
    #: is meaningless until it has seen about its own half-life. The argument is
    #: right and the number was unreachable: read off the live state on
    #: 2026-09-10, `momentum-scalp` was tracking **253 feeds and the busiest had
    #: seven observations**, none at 48. Its refusals were 99.2% `warmup` across
    #: every day it has run, so the strategy had never formed a view at all.
    #:
    #: The arithmetic is the problem. These are observations of *published level
    #: calls*, not bars, and the book produces single digits per feed per week -
    #: so 48 is somewhere near two months per instrument, on a scalper.
    #:
    #: 12 is the middle half-life: it says the *fast* and *middle* lines are
    #: meaningful and the slow one is still partly its seed value. That is a
    #: real cost and it points one way - a slow line still near its first
    #: observation makes `agree` easier to satisfy, so the gate is looser than
    #: it reads for a while after a feed appears. Being loose on a gate that has
    #: never once fired is the better failure.
    warmup: float = WARMUP
    #: Which float of a bar this reads when the Nautilus engine feeds it.
    #: A **return**, not a level: three EWMAs of a price are three prices, and
    #: their agreement says only that price is above where it was, which is
    #: already in the price. No scale is read - `agree` is a test of three
    #: signs, and a sign does not have units.
    source: Reading = Reading.LOG_RETURN
    _values: dict[str, list[float]] = field(default_factory=dict)
    _seen: dict[str, int] = field(default_factory=dict)
    _prev: dict[str, float] = field(default_factory=dict)

    #: The fields a reset keeps. Everything else is state.
    _CONFIG: ClassVar[frozenset[str]] = frozenset({"half_lives", "warmup", "source"})

    def __post_init__(self) -> None:
        """Hand Nautilus its parameters."""
        Indicator.__init__(self, [self.half_lives, self.warmup, self.source])

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point, keyed by the bar type that delivered it.

        **One `Speeds` holds many feeds**, which is what the class is for, so
        registering the same instance against several bar types is correct and
        each keeps its own three lines. The key is the bar type rather than the
        instrument, because the same instrument at 1m and at 1h is two series
        and averaging them together would be a third thing that is neither.

        A previous close is kept per key for the same reason: one shared
        previous close would make every return the gap between whichever two
        feeds happened to arrive next to each other.
        """
        key = str(bar.bar_type)
        value = read(bar, self.source, self._prev.get(key))
        self._prev[key] = float(bar.close)
        if value is None:
            return
        self.observe(key, value)
        self._set_has_inputs(True)
        if not self.initialized and self.ready(key):
            self._set_initialized(True)

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen an observation."""
        self._values.clear()
        self._seen.clear()
        self._prev.clear()
        self._set_has_inputs(False)
        self._set_initialized(False)

    def observe(self, key: str, value: float) -> tuple[float, float, float]:
        held = self._values.get(key)
        if held is None:
            held = self._values[key] = [value, value, value]
            self._seen[key] = 0
        for index, half_life in enumerate(self.half_lives):
            alpha = 1.0 - 2.0 ** (-1.0 / half_life)
            held[index] += alpha * (value - held[index])
        self._seen[key] = self._seen.get(key, 0) + 1
        return tuple(held)  # type: ignore[return-value]

    def ready(self, key: str) -> bool:
        """Whether this feed has been seen enough for the lines to mean anything.

        See `trading-speeds.md` in research/docs.
        """
        warmup = self.warmup if isinstance(self.warmup, int | float) else WARMUP
        return self._seen.get(key, 0) >= warmup

    def agree(self, key: str, sign: int) -> bool:
        """True when all three lines point the way `sign` does."""
        held = self._values.get(key)
        if held is None or not self.ready(key):
            return False
        return all((value > 0) == (sign > 0) and value != 0 for value in held)

    def of(self, key: str) -> tuple[float, float, float]:
        held = self._values.get(key)
        return tuple(held) if held else (0.0, 0.0, 0.0)  # type: ignore[return-value]


# ==========================================================================
# from ticks.py
# ==========================================================================

#: Half-life in ticks for the flow average. Ticks, not seconds, because the
#: stream's rate is not constant and a time half-life on a sampled stream
#: weights busy periods by how busy they are twice.
HALF_LIFE = 50


class Basis(StrEnum):
    """Which observable a reading was built from."""

    #: Nothing has arrived yet.
    NONE = "none"
    #: Signed volume from `TradeTick.aggressor_side`.
    TRADES = "trades"
    #: Mid moves and one-sided revisions from `QuoteTick`.
    QUOTES = "quotes"


def _alpha(half_life: int) -> float:
    return 1.0 - 0.5 ** (1.0 / max(1, half_life))


class TickMomentum(Indicator):
    """Signed flow over recent ticks, in -1..+1.

    Registered with `register_indicator_for_trade_ticks`,
    `register_indicator_for_quote_ticks`, or both - on an `Actor` or a
    `Strategy`, the API is identical. Given both, trades win: an aggressor side
    is a fact about who paid, and a quote revision is an inference about it.

    `momentum` follows this package's convention: **-1..+1, 0 neutral, +1
    bullish**. The two encodings - 0..1 and -1..+1 - are the same function, so
    this is a convention rather than a claim, and it is written down because
    mixing them silently halves or doubles every weight that reads it.
    """

    def __init__(self, half_life: int = HALF_LIFE) -> None:
        if half_life < 1:
            raise ValueError(f"half_life={half_life} is not a half-life in ticks.")
        super().__init__([half_life])
        self.half_life = int(half_life)
        self.basis = Basis.NONE
        #: EWMA of the signed flow, already in -1..+1.
        self._flow = 0.0
        #: EWMA of "this revision moved one side only", in 0..1.
        self._one_sided = 0.0
        self.ticks = 0
        self._bid: float | None = None
        self._ask: float | None = None

    # ------------------------------------------------------------- the engine

    def handle_trade_tick(self, tick: Any) -> None:
        """Nautilus's entry point for trades: signed by who crossed the spread.

        `NO_AGGRESSOR` is **dropped, not counted as zero**. A venue that
        reports trades without a side is telling us it does not know, and
        folding that in as neutral flow would pull the average toward zero at a
        rate set by how often the venue is uninformative - which is a reading
        about the feed wearing the shape of a reading about the market.
        """
        side = int(tick.aggressor_side)
        if side == 0:
            return
        self.basis = Basis.TRADES
        self._fold(1.0 if side == 1 else -1.0)

    def handle_quote_tick(self, tick: Any) -> None:
        """Nautilus's entry point for quotes: signed by which side moved.

        Ignored once trades have been seen, because an aggressor side is a fact
        and a revision is an inference about one. The first quote only sets the
        reference - there is no revision until there are two.
        """
        bid, ask = float(tick.bid_price), float(tick.ask_price)
        was_bid, was_ask = self._bid, self._ask
        self._bid, self._ask = bid, ask
        if self.basis is Basis.TRADES or was_bid is None or was_ask is None:
            return
        up = bid > was_bid or ask > was_ask
        down = bid < was_bid or ask < was_ask
        if not up and not down:
            return
        self.basis = Basis.QUOTES
        moved = (bid != was_bid) + (ask != was_ask)
        self._one_sided += _alpha(self.half_life) * (float(moved == 1) - self._one_sided)
        self._fold(0.0 if up and down else (1.0 if up else -1.0))

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen a tick."""
        self.basis = Basis.NONE
        self._flow = 0.0
        self._one_sided = 0.0
        self.ticks = 0
        self._bid = None
        self._ask = None
        self._set_has_inputs(False)
        self._set_initialized(False)

    def _fold(self, signed: float) -> None:
        self._flow += _alpha(self.half_life) * (signed - self._flow)
        self.ticks += 1
        self._set_has_inputs(True)
        if not self.initialized and self.ticks >= self.half_life:
            self._set_initialized(True)

    # ------------------------------------------------------------ the reading

    @property
    def momentum(self) -> float:
        """Signed flow in -1..+1. 0 neutral, +1 bullish."""
        return self._flow

    @property
    def one_sided(self) -> float:
        """Share of recent revisions that moved one side only, in 0..1.

        Zero on a trade-based feed, where there are no revisions to count.
        **A rate over the ticks that arrived**, which on MT5 is a sample - see
        the module docstring. The measured figure on this desk's terminal is
        22.8%, so a reading far from that says something about the feed before
        it says anything about the market.
        """
        return self._one_sided

    @property
    def spread(self) -> float | None:
        """The last quoted spread, or None before two sides have arrived."""
        if self._bid is None or self._ask is None:
            return None
        return self._ask - self._bid


# ==========================================================================
# slope momentum
# ==========================================================================

#: Bars in the slope window. Short, because this is a local reading: the point
#: is how the slope *changed*, and a long window changes slowly by
#: construction.
SLOPE_WINDOW = 20

#: How many readings back the comparison slope comes from. One is "since the
#: last bar"; larger is "since N bars ago".
SLOPE_LAG = 1

#: Slopes kept, so `past` can reach back and a caller can see the path.
SLOPE_KEPT = 128

#: Standard errors a change must clear before `turning` calls it a turn. One,
#: which is weak as evidence and is not meant as evidence - it is there to stop
#: the reading firing on float noise. Sweep it on the mean rather than on `z`.
TURNING_Z = 1.0

#: Relative tolerance for the no-residual case, in units of the slope itself.
_FLOOR = 1e-9


class SlopeMomentum(Indicator):
    """Momentum as a change in slope: the second derivative of price.

    `slope` is the OLS gradient over the last `window` bars, in price per bar.
    `change` is that slope minus the one `lag` readings ago, which is an
    **acceleration** - price per bar per bar - and is the reading this is for.
    A rising slope says the move is still building; a falling one says it is
    still a move and is running out.

    ## The overlap, which is the whole difficulty

    Consecutive rolling slopes **share all but one bar of their windows**, so
    they are not two independent estimates of anything: at `stride` 1 and
    `window` 20, `change` is driven almost entirely by the single bar that
    entered and the single bar that left. That makes it responsive and makes it
    nearly useless as evidence - the desk has paid for this shape twice. A
    trailing z-score's shuffled twin took **+0.111 of a +0.137 effect** at z
    4.23, which is more than an FX cross's spread earned from the overlap
    alone; and a level finding at p 0.015 turned out to be anchor overlap, with
    the no-level control passing as the tell.

    So two things are built in rather than left to the caller:

    * **`stride`** samples the slope every `stride` bars. With
      `stride * lag >= window` the two windows do not overlap at all, which is
      the configuration a null can actually be run against.
    * **`overlapping`** says whether the current settings overlap, and
      `shared_bars` says by how many. A result from an overlapping
      configuration is not wrong, it is *uninterpretable without a null that
      overlaps the same way* - so the number is published rather than hidden.

    ## Nautilus has the first derivative

    `trend.LinearRegression` gives a slope and agrees with `trend.fit` to
    1e-9. What it does not keep is the slope's own history, which is what a
    difference needs - so this holds the path, and `trend.ratio` remains the
    scale-free way to ask whether the move went anywhere at all.
    """

    def __init__(
        self,
        *,
        window: int = SLOPE_WINDOW,
        lag: int = SLOPE_LAG,
        stride: int = 1,
        kept: int = SLOPE_KEPT,
        turning_z: float = TURNING_Z,
        source: Reading = Reading.CLOSE,
        unit: float = 0.0,
        unit_from: Reading | None = Reading.RANGE,
        unit_span: int = 0,
    ) -> None:
        check_scale(type(self).__name__, source, unit, unit_from)
        if window < 3:
            raise ValueError(
                f"window={window} is not a slope: two points are a chord with "
                f"no residual, so there is no standard error and `change_se` "
                f"cannot be computed."
            )
        if lag < 1 or stride < 1:
            raise ValueError(f"lag={lag} and stride={stride} must both be at least 1.")
        super().__init__([window, lag, stride, turning_z])
        self.window = int(window)
        self.lag = int(lag)
        self.stride = int(stride)
        self.turning_z = float(turning_z)
        self.source = source
        self.unit = float(unit)
        self.unit_from = unit_from
        self.unit_span = int(unit_span)
        self._bar_prev: float | None = None
        self._bar_scale = 0.0
        self._fed = ""
        self._values: deque[float] = deque(maxlen=self.window)
        self.slopes: deque[float] = deque(maxlen=max(kept, self.lag + 1))
        self.residual_sd = 0.0
        self.bars = 0

    # ------------------------------------------------------------- the engine

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point. A slope is taken every `stride` bars."""
        check_feed(self, "bars")
        value, _ = bar_input(self, bar)
        if value is None:
            return
        self._values.append(value)
        self.bars += 1
        self._set_has_inputs(True)
        if len(self._values) < self.window or self.bars % self.stride:
            return
        slope, sd = _ols(self._values)
        if slope is None:
            return
        self.slopes.append(slope)
        self.residual_sd = sd
        if not self.initialized and len(self.slopes) > self.lag:
            self._set_initialized(True)

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen a bar."""
        self._values.clear()
        self.slopes.clear()
        self.residual_sd = 0.0
        self.bars = 0
        self._fed = ""
        self._bar_prev = None
        self._bar_scale = 0.0
        self._set_has_inputs(False)
        self._set_initialized(False)

    # ------------------------------------------------------------ the reading

    @property
    def slope(self) -> float | None:
        """The current gradient, in price per bar."""
        return self.slopes[-1] if self.slopes else None

    def past(self, lag: int | None = None) -> float | None:
        """The gradient `lag` readings ago, or None if it is not held."""
        back = self.lag if lag is None else lag
        return self.slopes[-1 - back] if len(self.slopes) > back else None

    def change_over(self, lag: int | None = None) -> float | None:
        """Current slope minus the one `lag` readings ago."""
        here, there = self.slope, self.past(lag)
        return None if here is None or there is None else here - there

    @property
    def change(self) -> float | None:
        """The acceleration at the configured `lag`, in price per bar per bar."""
        return self.change_over()

    @property
    def change_vol(self) -> float | None:
        """`change` in volatility units per bar, which compares across markets."""
        got = self.change
        if got is None or self._bar_scale <= 0.0:
            return None
        return got / self._bar_scale

    @property
    def slope_se(self) -> float:
        """Standard error of one slope: `sd_resid / sqrt(Sxx)`."""
        n = len(self._values)
        if n < 3 or self.residual_sd <= 0.0:
            return 0.0
        mean_x = (n - 1) / 2.0
        sxx = sum((i - mean_x) ** 2 for i in range(n))
        return self.residual_sd / math.sqrt(sxx) if sxx > 0 else 0.0

    @property
    def change_se(self) -> float | None:
        """Standard error of `change`, **assuming the two slopes are
        independent** - which at `stride * lag < window` they are not.

        Reported with that caveat rather than corrected, because the
        correction needs the overlap's covariance and the honest answer to an
        overlapping configuration is to run the null overlapping the same way.
        Over-stating this error makes `change_z` *conservative*, which is the
        right direction for a number nobody has nulled yet.
        """
        se = self.slope_se
        return None if se <= 0.0 else se * math.sqrt(2.0)

    @property
    def change_z(self) -> float | None:
        """`change` in units of its own standard error.

        **Not a p-value.** A z here is a ratio of two numbers this indicator
        computed, on overlapping windows, with no null behind it. Sweep a
        threshold on the *mean* rather than on this - a z grid faked a ridge at
        the chosen threshold on this desk once, where the mean grid was
        monotone.
        """
        got, se = self.change, self.change_se
        return None if got is None or se is None else got / se

    @property
    def shared_bars(self) -> int:
        """Bars the two differenced windows have in common."""
        return max(0, self.window - self.stride * self.lag)

    @property
    def overlapping(self) -> bool:
        """Do the two differenced windows share any bars?"""
        return self.shared_bars > 0

    @property
    def turning(self) -> int:
        """+1 when the slope is steepening upward, -1 downward, 0 neither.

        **A change has to clear its own standard error to count.** The first
        version of this compared against exact zero, and on a perfectly
        straight line - where the acceleration is zero by construction - the
        difference of two OLS slopes comes out at around -1e-19 rather than
        0.0, so it reported a confident downturn built entirely from rounding.
        Its own test caught it.

        Sign only beyond that, because sign is all that survives into a
        weighted sum anyway: activation, scale and a per-term offset are rank
        identities on a monotone score, so the encoding carries nothing the
        ordering does not.
        """
        got = self.change
        if got is None:
            return 0
        error = self.change_se
        if error is not None and error > 0.0:
            if abs(got) < self.turning_z * error:
                return 0
        elif abs(got) <= _FLOOR * max(abs(self.slope or 0.0), 1e-12):
            # No residual at all, so no standard error: a straight line. What
            # is left to guard against is float noise, so the tolerance is
            # relative to the slope the noise came from.
            return 0
        return 1 if got > 0 else -1


def _ols(values: Sequence[float]) -> tuple[float | None, float]:
    """`(gradient per step, residual sd)` of an OLS line through `values`.

    `x` is the index, so the gradient is per bar and needs no time re-centring
    the way a fit against unix seconds does.
    """
    n = len(values)
    if n < 3:
        return None, 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    sxx = sum((i - mean_x) ** 2 for i in range(n))
    if sxx <= 0.0:
        return None, 0.0
    sxy = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(values))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    residuals = [y - (intercept + slope * i) for i, y in enumerate(values)]
    # n - 2 degrees of freedom: a line costs two.
    var = sum(r * r for r in residuals) / (n - 2)
    return slope, math.sqrt(max(var, 0.0))
