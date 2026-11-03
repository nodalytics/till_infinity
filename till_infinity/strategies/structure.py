"""`smc_bos_c_L50|M15|N20|time` - a break of structure, read causally.

The rule as specified, and nothing else:

1. **Swings.** On M15 bars, a swing high is a bar whose high is the highest of
   the 50 bars on each side; a swing low is the mirror. A swing is therefore
   only *known* once the fiftieth bar after it has closed, and this waits for
   that.
2. **Trend.** A higher high **and** a higher low is an uptrend; a lower high
   **and** a lower low is a downtrend; anything else keeps the previous label.
3. **The break.** An M15 bar must *close* beyond the latest unbroken swing - a
   wick is not enough - and each swing may trigger once.
4. **Direction.** With the trend, a break is a BOS and is traded. Against it,
   it is a CHoCH: **not traded**, but it flips the label.
5. **Entry.** At market, so the fill lands on the first minute after the M15
   close, at the ask on a buy and the bid on a sell.
6. **Stop.** The wider of one M15 ATR and 20 spreads - the `N20`.
7. **Exit.** No target. Out after 1,440 one-minute bars unless the stop is hit
   first - the `time`.

## What the `c` is for, and why it is the whole point

Variant `a` took its swing timestamps from a published library, and those
depend on bars after the swing: a backtest reading them knows at 09:00 what
only 21:30 could tell it. Variant `b` moved the signal to when it was knowable
and still erased order blocks that later failed, so the losers left the sample
with hindsight. Both read far better than this and neither can be traded.

So the one invariant this module is built around: **nothing here may read a bar
that has not closed.** `Fold` is a plain state machine over `(high, low,
close)` in arrival order with no access to anything else, which is what makes
that claim testable rather than asserted - `tests/test_structure_bos.py` runs
every prefix of a series through it and requires the events in the first `n`
bars to be identical to the ones the full series produced. A fold that peeked
would disagree with itself there.

**It claims no edge.** The user's own standing description of this rule ends
"it's the best causal lead we have, but it's unproven", and a faithful port is
the entire contribution here. The numbers it produces are in the harness that
ran it, not in this docstring.

## Why the state machine is a plain class

For the reason `sizes.py` gives: a `Strategy` cannot be instantiated without a
`BacktestEngine` or a `TradingNode` around it, so anything that only exists as
a method on one is testable only through a kernel nobody stands up in a unit
test. The structure reading is the part of this rule that can be wrong in a way
that still trades, so it is a plain object over three floats.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, ClassVar

from nautilus_trader.model.data import Bar

from ..domain.models import Intent, Refusal, Side
from .entries import EdgeEntry
from .exits import ManagedExit
from .profile import Profile

#: Minutes a trade is held before it is closed on the clock. The `time` in the
#: rule's name, and 1,440 one-minute bars is about a day.
HOLD_MINUTES = 1_440

#: Bars each side of a swing. The `L50` in the rule's name: at M15 that is
#: about 12.5 hours each way, so these are major swings.
REACH = 50

#: Spreads the stop must clear, where one ATR is tighter than that. The `N20`.
SPREADS = 20.0


def _number(value: Any) -> float:
    """A float, or zero. A feature that is absent and one that is unparseable
    are the same thing to a threshold, and neither is a reason to raise."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True, slots=True)
class Event:
    """One break, classified. `kind` is the vocabulary the rule is written in.

    `side` is the direction of the break and not of the trade: a CHoCH has a
    side and is not traded, which is exactly the distinction that has to
    survive into the tally.
    """

    #: `bos`, `choch`, or `unlabelled` for a break before any trend was named.
    kind: str
    side: Side
    #: The swing price the close went beyond.
    swing: float
    #: The trend label **after** this event, so a CHoCH's flip is visible.
    trend: int
    #: Bars since the series started, counting the one that closed beyond.
    at: int


@dataclass(slots=True)
class Fold:
    """The causal structure reading: swings, the trend label, and the breaks.

    Fed one closed bar at a time and never anything else. Everything it answers
    is a function of the bars it has already been given, which is the property
    `a` and `b` lost.
    """

    reach: int = REACH
    #: Bars each side of a swing **high** and of a swing **low**, zero meaning
    #: `reach`. Two windows rather than one is the whole per-side question: a
    #: buy break comes from a confirmed high and a sell break from a confirmed
    #: low, so a reach per side is a lookback per traded direction. Zero on
    #: both is arithmetically identical to the single-window version.
    reach_up: int = 0
    reach_down: int = 0
    #: True requires a candidate strictly beyond both windows; False admits a
    #: tie, which is what the rule's reference statement does (`high[j] ==
    #: max(...)`). Strict is the default because a tie lets a flat run nominate
    #: every bar in it, and with one live slot per side the last of them wins -
    #: so the two differ only on exact equality. Measured on this catalogue:
    #: 0 breaks of 94 moved.
    strict: bool = True
    #: `(high, low)` for the last `2 * max(reach_up, reach_down) + 1` bars. The
    #: candidate for a side is the bar exactly that side's reach back from the
    #: newest, so it is judged that many bars after it printed and not before.
    window: deque[tuple[float, float]] = field(default_factory=deque)
    #: The latest confirmed swing on each side, and whether it has triggered.
    #: One slot rather than a stack: the rule says *the latest unbroken swing*,
    #: so a new confirmation replaces the old one whether or not it was broken.
    high: float = 0.0
    low: float = 0.0
    high_live: bool = False
    low_live: bool = False
    #: The previous confirmed swing on each side, for the comparison the trend
    #: label is made of.
    last_high: float = 0.0
    last_low: float = 0.0
    #: Which way the last pair of swings stepped: +1 higher, -1 lower, 0 for
    #: equal or not yet known. Three values and not a bool, because "equal" is
    #: neither a higher high nor a lower one and the label has to keep its
    #: previous state on it.
    high_step: int = 0
    low_step: int = 0
    #: +1 uptrend, -1 downtrend, 0 before either has been established.
    trend: int = 0
    bars: int = 0
    highs: int = 0
    lows: int = 0

    def __post_init__(self) -> None:
        if self.reach < 1:
            raise ValueError(f"a swing needs at least one bar each side, not {self.reach}")
        for name in ("reach_up", "reach_down"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} is a bar count or zero, not {getattr(self, name)}")
        self.window = deque(self.window, maxlen=2 * max(self._reach(1), self._reach(-1)) + 1)

    def _reach(self, side: int) -> int:
        """This side's reach, falling back to the shared one on zero."""
        return (self.reach_up if side > 0 else self.reach_down) or self.reach

    def update(self, high: float, low: float, close: float) -> list[Event]:
        """One closed bar. Every break it produced, in order.

        A list because both sides can break on one close - a swing low
        confirmed above an older swing high makes that possible - and dropping
        the second would leave a swing marked unbroken for ever.

        Swings are confirmed before the break is checked, and on the high side
        the order cannot matter: a bar that confirms a swing high is, by the
        definition, not higher than it. On the low side it can, and confirming
        first is the choice made here - a swing is known at this close, so it
        is available to this close.
        """
        self.bars += 1
        self.window.append((high, low))
        self._confirm()
        return self._broke(close)

    def _confirm(self) -> None:
        """Promote each side's candidate, if it is one.

        Asked per side rather than once, because the two reaches can differ: a
        short side ready at `2 * reach_down + 1` bars must not wait for the
        long side's window to fill.
        """
        bars = list(self.window)
        up, down = self._reach(1), self._reach(-1)
        if len(bars) >= 2 * up + 1:
            span = bars[len(bars) - (2 * up + 1) :]
            highs = [bar[0] for bar in span]
            candidate = highs[up]
            beyond = max(highs[:up]), max(highs[up + 1 :])
            if (candidate > beyond[0] and candidate > beyond[1]) or (
                not self.strict and candidate >= beyond[0] and candidate >= beyond[1]
            ):
                self.highs += 1
                self.high_step = _step(candidate, self.last_high) if self.last_high else 0
                self.last_high = candidate
                self.high = candidate
                self.high_live = True
                self._relabel()
        if len(bars) >= 2 * down + 1:
            span = bars[len(bars) - (2 * down + 1) :]
            lows = [bar[1] for bar in span]
            candidate = lows[down]
            beyond = min(lows[:down]), min(lows[down + 1 :])
            if (candidate < beyond[0] and candidate < beyond[1]) or (
                not self.strict and candidate <= beyond[0] and candidate <= beyond[1]
            ):
                self.lows += 1
                self.low_step = _step(candidate, self.last_low) if self.last_low else 0
                self.last_low = candidate
                self.low = candidate
                self.low_live = True
                self._relabel()

    def _relabel(self) -> None:
        """The trend, from the last pair of swings on each side.

        Keeps its previous value on anything that is not both-higher or
        both-lower, which is what "anything else keeps the previous state"
        means and is the reason this is not an `if/else`.
        """
        if self.high_step > 0 and self.low_step > 0:
            self.trend = 1
        elif self.high_step < 0 and self.low_step < 0:
            self.trend = -1

    def _broke(self, close: float) -> list[Event]:
        """Which live swings this close went beyond, and what each one is."""
        found: list[Event] = []
        if self.high_live and close > self.high:
            self.high_live = False
            found.append(self._classify(Side.BUY, self.high))
        if self.low_live and close < self.low:
            self.low_live = False
            found.append(self._classify(Side.SELL, self.low))
        return found

    def _classify(self, side: Side, swing: float) -> Event:
        """A break as a BOS, a CHoCH, or neither for want of a trend.

        The CHoCH flip is applied here rather than returned as a request,
        because the next bar has to see the new label whether or not anything
        acted on the event.
        """
        if self.trend == 0:
            return Event(kind="unlabelled", side=side, swing=swing, trend=0, at=self.bars)
        if self.trend != side.sign:
            self.trend = side.sign
            return Event(kind="choch", side=side, swing=swing, trend=self.trend, at=self.bars)
        return Event(kind="bos", side=side, swing=swing, trend=self.trend, at=self.bars)


def _step(price: float, previous: float) -> int:
    """+1 higher, -1 lower, 0 equal.

    The comparisons are cast rather than subtracted directly, because a
    `numpy` float makes `bool - bool` raise - and a harness folding stored bars
    hands over exactly that.
    """
    return int(price > previous) - int(price < previous)


@dataclass(slots=True)
class Closed:
    """One finished trade, as this rule's own record of it.

    Kept because the question the port has to answer is *what did the engine
    do* - how many were stopped, how many ran out of clock, and what each one
    was worth in R - and a position in the cache carries the money without the
    budget it was sized against.
    """

    feed: str
    side: Side
    reward: float
    money: float
    risk_money: float
    #: `stop`, `clock`, or whatever else asked for the close.
    how: str
    opened: float
    closed: float
    #: The stop distance in price, and the spread at the decision. Kept
    #: together because the cost of a trade in R is the second over the first
    #: and nothing else: `cost_px / risk` is **set by the stop**, so a rule
    #: that loses a fixed fraction of an R a trade is paying for its stop
    #: width and no exit rule can repair it. Recording them is what lets that
    #: be read off a run rather than guessed from the mean.
    risk_px: float = 0.0
    spread_px: float = 0.0


class StructureProfile(Profile):
    """The numbers the rule names, and nothing it does not.

    Every value here is in the rule's own specification except `atr_period`,
    which the specification does not state - see its comment.
    """

    name: ClassVar[str] = "smc-bos-causal"
    description: ClassVar[str] = "smc_bos_c_L50|M15|N20|time"
    #: Its own shape, so a statespace proposal on the same topic is skipped
    #: rather than judged - this rule reads bars and nothing else.
    shape: ClassVar[str] = "structure"
    #: A swing's thesis is duration: 1,440 one-minute bars, not a reaction.
    style: ClassVar[str] = "swing"
    hold_bars: ClassVar[float] = float(HOLD_MINUTES)
    hold_seconds: ClassVar[float] = HOLD_MINUTES * 60.0
    #: Bars each side of a swing - `L50`.
    reach: ClassVar[int] = REACH
    #: Spreads the stop clears where one ATR is tighter - `N20`.
    spreads: ClassVar[float] = SPREADS
    #: **Not in the specification.** "One M15 ATR" names neither a period nor a
    #: smoothing, so 14 and Nautilus's own `AverageTrueRange` are taken here:
    #: 14 because it is the textbook default the rule's family is written
    #: against, and the framework's because `indicators/__init__.py` says to
    #: take theirs rather than write one. Both are choices this port made and
    #: the rule did not, which is why they are named here rather than inlined.
    atr_period: ClassVar[int] = 14
    #: The clock the signal is read on. Stated so a desk built on another one
    #: is visible rather than quietly measuring a different rule.
    interval: ClassVar[str] = "15m"
    #: Signal-clock bars the trade is held: 1,440 one-minute bars is 96 M15
    #: ones. **A bar count and not `hold_seconds`.** The two differ by whatever
    #: the feed's gaps are worth: three of the 31 FX trades on this catalogue
    #: exited at 49.0h and 56.8h of clock because the 86,400-second deadline
    #: fell inside a weekend and the exit landed on the first quote at the
    #: Sunday reopen - which is the one place a survivorship confound lives.
    hold_signal_bars: ClassVar[int] = HOLD_MINUTES // 15
    #: Bars each side of a swing, per side, zero meaning `reach`. See `Fold`.
    reach_up: ClassVar[int] = 0
    reach_down: ClassVar[int] = 0
    #: Multiples of one M15 ATR the stop clears, per side on zero. Separate
    #: from `spreads` because the two legs are anchored differently.
    atr_mult: ClassVar[float] = 1.0
    atr_mult_up: ClassVar[float] = 0.0
    atr_mult_down: ClassVar[float] = 0.0
    #: Spreads the stop clears, per side on zero. See `spreads`.
    spreads_up: ClassVar[float] = 0.0
    spreads_down: ClassVar[float] = 0.0
    #: True admits a swing on a tie; see `Fold.strict`, whose default is the
    #: opposite because this flag is stated the way the rule reads.
    tie_is_a_swing: ClassVar[bool] = False
    #: True anchors the **ATR leg at the signal bar's close** and the spread
    #: floor at the fill, then takes the wider - which is how the rule states
    #: it. False anchors both at the fill, which was this port's reading and
    #: makes `risk` exactly `max(atr, 20 * spread)`. On this catalogue the two
    #: differ by half a spread, because the modelled quote *is* the bar's
    #: close, so nothing here can measure the real gap.
    stop_from_close: ClassVar[bool] = True
    #: UTC hours in which no fill is taken. The rule's later variants cut
    #: 19:00-23:59, judged on the fill. Read here off the signal bar's close
    #: stamp, which is the same hour except in its last minute.
    no_fill_hours: ClassVar[tuple[int, ...]] = (19, 20, 21, 22, 23)

    def reach_for(self, sign: int) -> int:
        """This side's swing reach, falling back to `reach` on zero."""
        return (self.reach_up if sign > 0 else self.reach_down) or self.reach

    def atr_mult_for(self, sign: int) -> float:
        """This side's ATR multiple, falling back to `atr_mult` on zero."""
        return (self.atr_mult_up if sign > 0 else self.atr_mult_down) or self.atr_mult

    def spreads_for(self, sign: int) -> float:
        """This side's spread floor, falling back to `spreads` on zero."""
        return (self.spreads_up if sign > 0 else self.spreads_down) or self.spreads


class Structure:
    """Trade a causal break of structure in the direction of the trend.

    A mixin with no base, composed with an entry from `entries.py` and an exit
    from `exits.py` - see `leaves.py`. Unlike `Surprise` it reads **bars**
    rather than a published reading, so `on_bar` is where the signal is made;
    everything after that is the shared gate sequence in `Desk.consider`.
    """

    profile: ClassVar[StructureProfile] = StructureProfile.__new__(StructureProfile)

    #: **The thesis is duration, so the stale rule does not apply.** `Exits
    #: .stale_after` is the per-rule half of what `Intent.stale_exempt`
    #: expresses per trade: the rule exists because a level touch resolves in
    #: eighteen seconds at the median, and that premise is simply false of a
    #: trade whose exit *is* a 24-hour clock.
    stale: ClassVar[bool] = False

    # ----------------------------------------------------------- the lifecycle

    def on_start(self) -> None:
        """Build the fold and the ATR, register it, then start the desk.

        Registration before `super()`, which subscribes: the two orders are
        indistinguishable on a live feed and differ in a backtest, which
        delivers the first bar immediately.

        The ATR is built here rather than named in the config because
        `node/desks.build` writes the config and sets no indicators - a rule
        whose stop needs one would otherwise be deployable with it missing,
        which is a stop distance of 20 spreads wearing an ATR's name.
        """
        from ..indicators import build_detector

        self.fold = Fold(
            reach=self.profile.reach,
            reach_up=self.profile.reach_up,
            reach_down=self.profile.reach_down,
            strict=not self.profile.tie_is_a_swing,
        )
        #: The signal-bar index a position opened on, for the bar clock. Kept
        #: here rather than on `Held` because the clock is this rule's own: a
        #: bar count is not a duration and `Exits._expired` reads seconds.
        self.opened_on: dict[Any, int] = {}
        #: What the fold has produced, by kind, including the zeros. A port is
        #: judged on these before it is judged on any money: a run with no
        #: swings and a run with no breaks are different failures and a trade
        #: count of zero does not tell them apart.
        self.structure: dict[str, int] = {
            "bars": 0,
            "swing_highs": 0,
            "swing_lows": 0,
            "breaks": 0,
            "bos": 0,
            "choch": 0,
            "unlabelled": 0,
            "both_sides": 0,
        }
        #: Finished trades, in the order they closed.
        self.closed: list[Closed] = []
        self.atr = build_detector("atr", period=self.profile.atr_period)
        self.register_indicator_for_bars(self._cfg.bar_type, self.atr)
        super().on_start()
        if not str(self._cfg.bar_type.spec).startswith("15-MINUTE"):
            # Said out loud rather than refused: a sweep may deliberately run
            # the same rule on another clock, and a deploy that did so by
            # accident is the failure this names - `L50|M15` is 12.5 hours a
            # side on M15 and four days a side on 4h.
            self.log.error(
                f"{self.profile.description} is an M15 rule and this desk is on "
                f"{self._cfg.bar_type}: the swing reach is {self.profile.reach} bars "
                f"of whatever this clock is."
            )

    # -------------------------------------------------------------- the signal

    def on_bar(self, bar: Bar) -> None:
        """One closed M15 bar through the fold, and any BOS it produced.

        **Called with closed bars only.** Nautilus delivers an aggregated bar
        when the interval ends, so the close this reads is final; a partial bar
        would be variant `a` by accident.
        """
        super().on_bar(bar)
        self.structure["bars"] += 1
        self._clock()
        events = self.fold.update(float(bar.high), float(bar.low), float(bar.close))
        self.structure["swing_highs"] = self.fold.highs
        self.structure["swing_lows"] = self.fold.lows
        self.structure["breaks"] += len(events)
        if len(events) > 1:
            # Both sides broken by one close, which needs a swing low standing
            # above an older swing high. Counted because the rule does not say
            # what to do with it and the desk would refuse the second order as
            # already held - so the number is the only honest record of it.
            self.structure["both_sides"] += 1
        for event in events:
            self.structure[event.kind] += 1
            if event.kind != "bos":
                continue
            # Through `on_data` and not `consider` directly, because that is
            # where the desk counts what it took, places it, and follows what
            # it declined. A dict is one of the two shapes it accepts.
            self.on_data(self._payload(event, bar))

    def _clock(self) -> None:
        """Close anything that has run out of bars.

        **The `time` in the rule's name, as a bar count.** Run before the
        fold's own events so the slot a closing trade holds is free for a
        break on this bar, which is what a greedy one-position rule does.
        """
        due = self.profile.hold_signal_bars
        if due <= 0:
            return
        for position_id, opened in list(self.opened_on.items()):
            held = self.structure["bars"] - opened
            if held < due:
                continue
            if self._close(position_id, f"held {held} bars and its rule allows {due}"):
                self._count("(exit):closed")

    def on_position_opened(self, event: Any) -> None:
        """Stamp the bar the position opened on, for `_clock`."""
        self.opened_on[event.position_id] = self.structure["bars"]
        super().on_position_opened(event)

    def _payload(self, event: Event, bar: Bar) -> dict[str, Any]:
        """The BOS as the payload `Desk.consider` reads.

        Handed straight to `on_data` rather than published on `PROPOSALS`: the
        bus would deliver a structure reading to every other desk subscribed to
        that topic, each of which would count it as unwanted. The reading is
        this strategy's own and never leaves it.
        """
        return {
            "feed": self._feed_name(),
            "shape": self.profile.shape,
            "interval": self.profile.interval,
            "direction": event.side.sign,
            "features": {
                # Named for the rule, so a later score can find them, and
                # **not** named `vol_bps`: that column is a folded log variance
                # elsewhere on this desk and an ATR in it would put one journal
                # column in two units.
                "bos_swing": event.swing,
                "bos_atr": float(self.atr.value) if self.atr.initialized else 0.0,
                "bos_trend": float(event.trend),
                "bos_close": float(bar.close),
                "bos_reach": float(self.profile.reach_for(event.side.sign)),
                # The hour the fill lands in, read off the close stamp. In
                # whole hours, because that is what the cut-off is written in.
                "bos_hour": float((bar.ts_event // 3_600_000_000_000) % 24),
            },
        }

    # ------------------------------------------------------------ the decision

    def wants(self, payload: dict[str, Any]) -> bool:
        """Only its own readings. A statespace proposal on the shared topic is
        not this rule's to decline."""
        return str(payload.get("shape") or "") == self.profile.shape

    def decide(self, payload: dict[str, Any]) -> Intent | Refusal | None:
        """A trade, or the reason there is not one. Never raises on a payload.

        There is no threshold here and no gate of this rule's own invention:
        the rule's filtering is the trend label and the close, both of which
        happened in the fold. What is left is the geometry - which side, at
        what price, with the stop where step 6 puts it.
        """
        feed = str(payload.get("feed") or "")
        tick = self._tick()
        if tick is None:
            # `Desk.consider` has already refused a missing quote, so this is
            # a second line rather than the only one.
            return Refusal(gate="no-quote", detail=f"no quote for {feed}", feed=feed)

        features = payload.get("features") or {}
        if not isinstance(features, dict):
            return Refusal(gate="features", detail="no features on the proposal", feed=feed)

        side_raw = int(_number(payload.get("direction")))
        if side_raw == 0:
            return Refusal(gate="direction", detail="the break took no side", feed=feed)
        side = Side.BUY if side_raw > 0 else Side.SELL

        atr = _number(features.get("bos_atr"))
        if atr <= 0.0:
            # The ATR is warm long before the first swing can be confirmed -
            # 14 bars against 101 - so this is a guard and not a path the rule
            # trades through.
            return Refusal(gate="atr", detail=f"the M15 ATR reads {atr:.6g}", feed=feed)

        hour = int(_number(features.get("bos_hour")))
        if hour in self.profile.no_fill_hours:
            # The later variants' entry cut-off. Refused here and not in the
            # fold, so the break is still counted and still spends its swing:
            # a cut trade must not free the one-position slot for a different
            # one, and must not leave the swing live to break again.
            return Refusal(gate="cut-off", detail=f"no fill at {hour:02d} UTC", feed=feed)

        entry = tick.ask if side is Side.BUY else tick.bid
        if entry <= 0.0:
            return Refusal(gate="bad-quote", detail=f"{feed} quoted {entry}", feed=feed)
        # Step 6: the wider of one ATR and 20 spreads, which are **anchored at
        # different prices** - the ATR at the signal bar's close, the floor at
        # the fill. The spread is the quote's own, not the spread *column*,
        # whose conversion is a measured 476% error on this desk.
        spreads = self.profile.spreads_for(side.sign) * tick.spread
        reach = self.profile.atr_mult_for(side.sign) * atr
        close = _number(features.get("bos_close"))
        if self.profile.stop_from_close and close > 0.0:
            # The wider of the two levels, which is a `min` on a buy: a stop
            # further below is a wider one.
            stop = (
                min(close - reach, entry - spreads)
                if side is Side.BUY
                else max(close + reach, entry + spreads)
            )
        else:
            stop = entry - side.sign * max(reach, spreads)
        risk = abs(entry - stop)
        if risk <= 0.0:
            return Refusal(gate="stop", detail="a zero stop distance", feed=feed)

        return Intent(
            feed=feed,
            symbol=self._cfg.instrument_id.symbol.value,
            side=side,
            # Zero: `Desk.consider` sizes it. Two places computing a size is
            # how they come to disagree.
            volume=0.0,
            entry=entry,
            stop=stop,
            # **No target, which is the rule.** `EdgeEntry` submits the entry
            # alone on a zero and attaches the stop from `on_order_filled`;
            # a target invented here would be a different rule with better
            # arithmetic.
            target=0.0,
            reason=(
                f"{'BOS up' if side is Side.BUY else 'BOS down'} through "
                f"{_number(features.get('bos_swing')):.5g} on {feed}"
            ),
            interval=self.profile.interval,
            features={k: _number(v) for k, v in features.items()}
            | {"bos_stop_spreads": spreads, "bos_stop_atr": reach},
            # Step 7 is `hold_signal_bars` and `_clock` runs it, so no seconds
            # hold: the two would race and the seconds one wins across a
            # session gap, which is what put three FX exits on the Sunday
            # reopen quote. Zero bars falls back to the seconds clock, which
            # exists only to reproduce the superseded reading.
            hold=0.0 if self.profile.hold_signal_bars > 0 else self.profile.hold_seconds,
        )

    # -------------------------------------------------------------- the record

    def on_position_closed(self, event: Any) -> None:
        """Record what the trade was worth before the exit book forgets it.

        Read here rather than from the cache afterwards because `R` needs the
        budget the trade was *sized* against, and that lives on the intent:
        `ExitMechanism.on_position_closed` pops it, so this has to run in front
        of it.

        `how` comes from the closing latch rather than from the order type,
        because that is the only place the reason is written: a stop-out leaves
        it empty, the clock and the basket each say why.
        """
        self.opened_on.pop(event.position_id, None)
        held = self.exits.held(event.position_id)
        position = self.cache.position(event.position_id)
        if held is not None and position is not None:
            money = float(position.realized_pnl) if position.realized_pnl is not None else 0.0
            risk = float(held.intent.risk_money or 0.0)
            self.closed.append(
                Closed(
                    feed=held.intent.feed,
                    side=held.intent.side,
                    # Zero risk money cannot happen on a sized intent, and a
                    # division that invented an R would be worse than a zero.
                    reward=money / risk if risk > 0.0 else 0.0,
                    money=money,
                    risk_money=risk,
                    how="clock" if held.closing else "stop",
                    opened=held.opened,
                    closed=self.clock.timestamp(),
                    risk_px=held.intent.risk,
                    # Divided by **this side's** floor, not the shared one:
                    # `bos_stop_spreads` is `spreads_for(side) * spread`, so a
                    # per-side floor recovers the wrong quote spread here and
                    # the cost in R is misread by the ratio of the two.
                    spread_px=_number(held.intent.features.get("bos_stop_spreads"))
                    / self.profile.spreads_for(held.intent.side.sign),
                )
            )
        super().on_position_closed(event)


class StructureEdge(Structure, ManagedExit, EdgeEntry):
    """The causal BOS, taken at market. The only pairing the rule names.

    Step 5 is "at market, on the open of the first minute after the M15 close",
    so a resting limit or an arrival wait would be a different rule - which is
    why `leaves.py` lists this rule for the edge entry and for nothing else,
    and `desks.build` refuses the others by name rather than skipping them.
    """
