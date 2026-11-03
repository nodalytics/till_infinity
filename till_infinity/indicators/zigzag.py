"""Alternating legs between confirmed pivots, and the attributes of each.

`trend.pivots` already produces a causal zigzag: it confirms a turn `reach`
bars after the extreme printed, and `Pivot` keeps both times so a caller can
check which one a study used. What it does not produce is the **leg** - the
move between two consecutive turns - or any reading off one.

## The repainting problem, and why the provisional leg is not returned

A zigzag's last leg is **not confirmed**. Price has left the previous pivot
and has not yet retraced enough to fix the new one, so the leg's extent, its
duration and even its direction can all still change. Every chart-drawn
zigzag shows that leg as though it were settled, which is why they repaint,
and a backtest reading it is reading a value that did not exist at the bar.

So `Zigzag.legs` returns **confirmed legs only**, and the leg in progress is
reachable solely through `forming`, whose docstring says it is not usable for
a decision. This is the same discipline as `strategies.timeframes.Frames
.ready`, which drops a higher frame whose bar has not closed rather than
flagging it: a caller who has to remember a flag is a caller who will forget.

## The attribute every zigzag study gets wrong

`research/docs/asking.md` names it, and it is a truncation:

> Every zigzag takes a threshold `theta` and records a turn only after a
> reversal of at least that much - so **every rally and every correction it
> records is at least `theta`**, and the ratio of two quantities truncated
> from below is not the ratio of the underlying ones.

So `retracement` here is the attribute most likely to be an artefact, and it
has a published diagnostic: **sweep `theta` and see whether the reading moves
with it.** If it does, the constant is the detector rather than the market.
Nothing in this module chooses a `theta`; `reach` is passed in and a study is
expected to sweep it.

## What is already measured about these attributes

**The asymmetry is real and carries no path information.** `fear-greed.md`
measured up legs **21% longer in bars** and down legs **33% faster per bar**,
audusd at z -4.56 and negative in 6 of 6 eras against a placebo's 3 of 6. But
at 80 surrogate draws **a memory-free bar shuffle reproduces it on every one
of fourteen instruments**, so it is a property of the return distribution, not
of leg structure. A per-side leg parameter therefore fits something real that
tells you nothing about what comes next.

**A leg-derived feature has been tested and was the weakest that read
anything.** `crash-timing.md` has `impulse` - consecutive legs to new
extremes, "the mechanical part of an Elliott count" - at AUC **0.562 at 15m
and nothing at 1h or 1d**, beaten in its own table by `downshare` at 0.590 and
by lower-wick skew at 0.584.

**A departure has no characteristic length.** `level-bounce.md` measured first
return to a level across 167 cells: **S(8) above the hardest null arm in 0 of
them**, the power law still better in 157, and 55% of departures ending on the
very next bar. So an attribute built on "how long this leg has run" is
describing a quantity with no scale of its own.

None of that forbids the readings below. It says what they are for: a leg is a
**state** to condition on, not a prediction, which is the framing
`anchored-states-prereg.md` sets out.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

from .levels import Sided
from .trend import REACH, Pivot, pivots

NANOS = 1_000_000_000


class Source(StrEnum):
    """Which pair of prices a turn is read off.

    **`EXTREME` and `BODY` answer different questions and neither is wrong.**
    A wick is where price traded and failed; a body is where it closed. A turn
    off the extremes catches the stop-run that the close rejected, and a turn
    off the bodies catches only what the market was willing to settle at.

    The difference is not cosmetic here. The stop-anchor study measured a
    stop being hit by the bar's **extreme** while the nearest level sat 0.43
    units away against a median bar range near one unit - the wick twice the
    distance to the level. And the bounce study found roughly half of all
    measured departure durations set by how wide a bar is against the level
    rather than by the close path. So which source a zigzag reads changes
    what its legs are, and a study must say which it used.

    **Which source is quieter is a fact about the data, not about the
    detectors.** Where most of a bar is wick the body series is a smoothed
    version of the extreme series and `BODY` finds fewer turns; where bodies
    swing inside the range it finds more. Measured both ways on synthetic
    fixtures while writing this, which is why the claim is stated as a
    dependence rather than a direction.
    """

    #: `high` and `low`. What `trend.pivots` has always read.
    EXTREME = "extreme"
    #: `max(open, close)` and `min(open, close)` - the body's own extremes.
    BODY = "body"


#: Bars kept for the pivot scan. Enough to hold several legs at `REACH` 3
#: without being a window a caller has to think about.
SPAN = 240


@dataclass(frozen=True, slots=True)
class Leg:
    """One confirmed move between two consecutive turns.

    `side` is +1 for a leg rising into a pivot high and -1 for one falling
    into a pivot low, which is the side of the pivot that **ends** it. The
    pivot that ends a leg is the one whose confirmation made the leg knowable,
    so dating a leg by its ending pivot is what keeps it causal.
    """

    side: int
    #: Price at the start and end of the leg.
    start: float
    end: float
    #: Unix seconds of each extreme, and of the confirmation that fixed it.
    began: float
    ended: float
    confirmed: float

    @property
    def extent(self) -> float:
        """Absolute price travelled. Non-negative, so it is a scale."""
        return abs(self.end - self.start)

    @property
    def span(self) -> float:
        """Seconds from one extreme to the other."""
        return max(0.0, self.ended - self.began)

    @property
    def lag(self) -> float:
        """Seconds between the leg ending and being knowable.

        **The number a study has to respect.** A leg is not a fact until this
        has elapsed, which is why `Zigzag.legs` holds back the one in
        progress.
        """
        return max(0.0, self.confirmed - self.ended)

    def speed(self) -> float:
        """Price per hour over the leg, or 0.0 where it spans no time."""
        hours = self.span / 3_600.0
        return self.extent / hours if hours > 0.0 else 0.0

    def units(self, unit: float) -> float:
        """`extent` in volatility units. 0.0 where the unit is unusable.

        Volatility units rather than price, because that is the only form in
        which a leg on gold and a leg on eurusd are the same quantity.
        """
        return self.extent / unit if unit > 0.0 else 0.0


@dataclass(frozen=True, slots=True)
class Shape:
    """A pair of consecutive legs, which is the smallest unit with a ratio.

    Kept apart from `Leg` because a ratio needs two, and because the
    truncation warning in the module docstring applies to this object and not
    to a single leg's extent.
    """

    prior: Leg
    latest: Leg

    @property
    def retracement(self) -> float:
        """`latest.extent / prior.extent`.

        **Truncated from below by construction**, since every leg a detector
        records is at least its threshold - so this ratio is not the ratio of
        the underlying moves, and a study quoting it must sweep `reach` and
        report whether the reading moves. `research/docs/asking.md` sets out
        the three outcomes that sweep separates.
        """
        return self.latest.extent / self.prior.extent if self.prior.extent > 0.0 else 0.0

    @property
    def alternates(self) -> bool:
        """Whether the two legs face opposite ways, as a zigzag's should.

        False is not an error: a `reach` that admits a tie can place two
        same-side pivots in a row, and a caller filtering on this is making a
        choice rather than correcting a bug.
        """
        return self.prior.side != self.latest.side

    def extends(self) -> bool:
        """Whether `latest` carried past where `prior` began - a new extreme.

        This is `crash-timing.md`'s `impulse`, "the mechanical part of an
        Elliott count", measured there at **AUC 0.562 at 15m and nothing at
        1h or 1d**. Exposed so a study can reuse that reading rather than
        re-derive it, with its measured weakness recorded here.
        """
        return (
            self.latest.end > self.prior.start
            if self.latest.side > 0
            else self.latest.end < self.prior.start
        )


def legs_from(found: Sequence[Pivot]) -> list[Leg]:
    """Consecutive pivots as legs, oldest first.

    One leg per adjacent pair, so `n` pivots give `n - 1` legs. A leg is dated
    by the confirmation of the pivot that **ends** it, which is the moment it
    became knowable.
    """
    out: list[Leg] = []
    for prior, latest in itertools.pairwise(found):
        out.append(
            Leg(
                side=latest.side,
                start=prior.price,
                end=latest.price,
                began=prior.when,
                ended=latest.when,
                confirmed=latest.confirmed,
            )
        )
    return out


class Zigzag(Indicator):
    """Confirmed legs between alternating pivots, with per-side parameters.

    Registered with `Actor.register_indicator_for_bars` or the identical
    method on `Strategy`.

    **Returns confirmed legs only.** The leg in progress is reachable through
    `forming` and is not usable for a decision - see the module docstring on
    repainting.
    """

    def __init__(
        self,
        *,
        reach: Sided | int = REACH,
        span: int = SPAN,
        keep: int = 16,
        source: Source | str = Source.EXTREME,
    ) -> None:
        self.reach = Sided.of(reach)
        self.source = Source(source)
        widest = max(self.reach.for_side(1), self.reach.for_side(-1))
        if span < 2 * widest + 1:
            raise ValueError(
                f"span={span} cannot hold a pivot at reach={widest:g}: a "
                f"confirmation needs {int(2 * widest + 1)} bars, so no leg "
                f"would ever be published."
            )
        super().__init__([str(self.reach), span, keep, self.source])
        self.span = int(span)
        self.keep = int(keep)
        self._window: list[tuple[float, float, float]] = []
        #: Confirmed legs, oldest first, capped at `keep`.
        self.legs: list[Leg] = []
        self.when = 0.0

    # ----------------------------------------------------------------- feeding

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point. `ts_event` is the bar's close."""
        self.update_raw(
            float(bar.high),
            float(bar.low),
            bar.ts_event / NANOS,
            open_=float(bar.open),
            close=float(bar.close),
        )

    def update_raw(
        self,
        high: float,
        low: float,
        when: float,
        *,
        open_: float | None = None,
        close: float | None = None,
    ) -> None:
        """Fold one bar in and republish the confirmed legs.

        `open_` and `close` are read only under `Source.BODY`, and a `BODY`
        zigzag fed without them **raises** rather than silently reading the
        extremes - a detector quietly answering a different question is the
        failure this whole module is written against.
        """
        if high < low:
            return
        if self.source is Source.BODY:
            if open_ is None or close is None:
                raise ValueError(
                    "Source.BODY needs the open and the close. Without them this "
                    "would read the extremes and answer a different question."
                )
            high, low = max(open_, close), min(open_, close)
        self.when = when
        self._window.append((high, low, when))
        if len(self._window) > self.span:
            del self._window[: len(self._window) - self.span]
        self._set_has_inputs(True)

        up = int(self.reach.for_side(1))
        down = int(self.reach.for_side(-1))
        found = pivots(self._window, reach=max(up, down), reach_up=up, reach_down=down)
        built = legs_from(found)
        self.legs = built[-self.keep :] if self.keep > 0 else built
        if self.legs:
            self._set_initialized(True)

    # ---------------------------------------------------------------- the reads

    @property
    def latest(self) -> Leg | None:
        """The newest **confirmed** leg, or `None` before one exists."""
        return self.legs[-1] if self.legs else None

    @property
    def shape(self) -> Shape | None:
        """The newest pair of confirmed legs, which is what carries a ratio."""
        return Shape(prior=self.legs[-2], latest=self.legs[-1]) if len(self.legs) > 1 else None

    def forming(self) -> tuple[int, float, float] | None:
        """The leg in progress as `(side, from_price, extent_so_far)`.

        **Not usable for a decision, and that is the whole point of the
        method.** The pivot that will end this leg is not fixed, so its side,
        its extent and its duration can all still change - which is why a
        chart-drawn zigzag repaints and why `legs` holds it back.

        Offered because an operator reading a log wants to know where price is
        relative to the last confirmed turn, and because refusing to compute
        it would mean every caller writing its own and getting the causality
        wrong in private.
        """
        if not self.legs or not self._window:
            return None
        last = self.legs[-1]
        price = self._window[-1][0] if last.side < 0 else self._window[-1][1]
        return -last.side, last.end, abs(price - last.end)

    def sided(self, unit: float = 0.0) -> dict[str, float]:
        """Mean extent, span and speed of confirmed legs, by side.

        **Up and down reported apart, because they are measured to differ.**
        `fear-greed.md` has up legs 21% longer in bars and down legs 33%
        faster per bar, audusd at z -4.56 and negative in 6 of 6 eras - and
        also that a memory-free bar shuffle reproduces it on all fourteen
        instruments at 80 draws. So this is a description of the return
        distribution, not a forecast, and pooling the sides would hide a real
        asymmetry that happens to carry no path information.

        Extents are in volatility units where `unit` is given, because a leg
        on gold and a leg on eurusd are otherwise not the same quantity.
        """
        out: dict[str, float] = {}
        for name, side in (("up", 1), ("down", -1)):
            picked = [leg for leg in self.legs if leg.side == side]
            if not picked:
                continue
            extents = [leg.units(unit) if unit > 0.0 else leg.extent for leg in picked]
            out[f"{name}_n"] = float(len(picked))
            out[f"{name}_extent"] = math.fsum(extents) / len(picked)
            out[f"{name}_bars"] = math.fsum(leg.span for leg in picked) / len(picked) / 3_600.0
            out[f"{name}_speed"] = math.fsum(leg.speed() for leg in picked) / len(picked)
        return out

    def _reset(self) -> None:
        self._window = []
        self.legs = []
        self.when = 0.0
        self._set_has_inputs(False)
        self._set_initialized(False)

    def handle_quote_tick(self, tick: Any) -> None:
        """Refused: a pivot needs a bar's high and low, and a quote has
        neither, so this would be an indicator that never published."""
        raise NotImplementedError(
            "Zigzag needs bars - a high and a low - so register it with "
            "register_indicator_for_bars, not for quote ticks."
        )


# ------------------------------------------------- one leg ahead, scored as it goes


@dataclass(frozen=True, slots=True)
class Prediction:
    """The next leg, as far as it can be stated before it exists.

    **The side is determined rather than predicted.** A zigzag alternates by
    construction, so the next leg must face the other way and there is no
    forecasting content in saying so. `side` is carried because a caller needs
    it, and is deliberately not scored.

    What is open is `extent`, in volatility units, and it is reported with the
    predictor's own recent error so it reads as a distribution rather than a
    number. `anchored-states-prereg.md` is the framing: magnitude is what
    sizing and stops consume, and direction is measured closed on this desk.
    """

    side: int
    extent: float
    #: Mean absolute error of this predictor's own recent one-step-ahead
    #: forecasts, in the same units as `extent`. **This is the volatility of
    #: the forecast**, and the reason the reading is a distribution rather
    #: than a number.
    error: float
    #: Confirmed legs behind the estimate.
    n: int
    #: Predicted duration, in seconds. 0.0 before one has been scored.
    span: float = 0.0
    #: Share of recent legs on this side that carried past where the previous
    #: leg began - a new extreme. This is `crash-timing.md`'s `impulse`,
    #: measured there at AUC 0.562 at 15m and **nothing at 1h or 1d**, so it
    #: is a rate to condition on rather than a signal.
    impulse: float = 0.0

    def bars(self, seconds: float) -> float:
        """`span` in bars of `seconds` each. 0.0 where either is unusable."""
        return self.span / seconds if seconds > 0.0 and self.span > 0.0 else 0.0

    def speed(self) -> float:
        """Predicted extent per hour - the leg's implied velocity.

        Derived rather than forecast separately: two estimates of a ratio and
        its parts would disagree, and the disagreement would be silent.
        """
        hours = self.span / 3_600.0
        return self.extent / hours if hours > 0.0 else 0.0

    def interval(self, k: float = 1.0) -> tuple[float, float]:
        """`extent` plus and minus `k` of the predictor's own error.

        Floored at zero, because an extent is a distance and a negative one is
        not a wider interval but a different quantity.
        """
        reach = k * self.error
        return max(0.0, self.extent - reach), self.extent + reach


@dataclass(slots=True)
class Forecast:
    """One-step-ahead leg extent, corrected by its own error as it goes.

    Per side, because up and down legs are measured to differ - and the
    difference appears on a random walk too, so this tracks it as a property
    of the return distribution rather than treating it as structure.

    ## The correction, and what it is scored against

    Each confirmed leg produces an error against what was predicted for it,
    and the estimate moves by `gain` times that error. A fixed gain is an
    exponentially weighted mean; it is chosen rather than fitted, because
    fitting it on the same legs it is scored on is how an adaptive estimator
    comes to look skilful.

    **The point of this object is `skill`, which can refuse it.** The estimate
    is scored one step ahead and out of sample against the running mean of all
    prior legs on that side - the forecast a constant would have made. On a
    walk the leg extents are exchangeable given the threshold, so the running
    mean is optimal and the adaptive estimate should read **no skill**. A
    positive skill is therefore a claim, and a negative one says plainly that
    the adaptivity is costing accuracy.

    Nothing here predicts direction: see `Prediction`.
    """

    gain: float = 0.2
    #: Running estimate, mean absolute error, squared-error totals and count,
    #: per side. The two error totals are what `skill` divides.
    state: dict[int, dict[str, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 < self.gain <= 1.0:
            raise ValueError(
                f"gain={self.gain} is not a correction weight. It multiplies an "
                f"error, so 0 never learns and above 1 overshoots every time."
            )

    def _side(self, side: int) -> dict[str, float]:
        return self.state.setdefault(
            side,
            {
                "estimate": 0.0,
                "mae": 0.0,
                "adaptive": 0.0,
                "constant": 0.0,
                "n": 0.0,
                "sum": 0.0,
                "span": 0.0,
                "impulse": 0.0,
            },
        )

    def observe(self, leg: Leg, unit: float, *, extended: bool | None = None) -> None:
        """Score the forecast this leg tested, then correct the estimate.

        **Scored before it is folded in**, which is what makes the error
        one-step-ahead and out of sample. Folding first would score the
        estimate against a leg it had already seen.

        A leg with no usable volatility unit is skipped rather than folded at
        price scale, which would put a gold leg and a eurusd leg in one mean.
        """
        size = leg.units(unit)
        if size <= 0.0:
            return
        held = self._side(leg.side)
        if held["n"] >= 1.0:
            error = size - held["estimate"]
            flat = held["sum"] / held["n"]
            held["adaptive"] += error * error
            held["constant"] += (size - flat) * (size - flat)
            held["mae"] += self.gain * (abs(error) - held["mae"])
            held["estimate"] += self.gain * error
        else:
            held["estimate"] = size
            held["mae"] = 0.0
        # Duration and impulse are corrected the same way, so every reading
        # on a `Prediction` comes from one update rule rather than three.
        held["span"] += self.gain * (leg.span - held["span"]) if held["n"] >= 1.0 else leg.span
        if extended is not None:
            seen = 1.0 if extended else 0.0
            held["impulse"] += self.gain * (seen - held["impulse"]) if held["n"] >= 1.0 else seen
        held["sum"] += size
        held["n"] += 1.0

    def predict(self, last: Leg | None) -> Prediction | None:
        """The next leg, given the last confirmed one.

        `None` until that side has been seen, because a first forecast would
        be the predictor's initial value rather than a reading.
        """
        if last is None:
            return None
        side = -last.side
        held = self.state.get(side)
        if held is None or held["n"] < 1.0:
            return None
        return Prediction(
            side=side,
            extent=held["estimate"],
            error=held["mae"],
            n=int(held["n"]),
            span=held["span"],
            impulse=held["impulse"],
        )

    def skill(self, side: int) -> float | None:
        """One minus the ratio of squared errors against a constant forecast.

        Positive means the correction earns its place; zero means it matches a
        running mean; negative means it is costing accuracy. `None` until two
        legs on that side have been scored, since the first produces no
        out-of-sample error at all.

        **On a walk this should read about zero**, and a test asserts it does.
        An adaptive estimator that reads skilful on exchangeable draws is
        measuring its own fitting.
        """
        held = self.state.get(side)
        if held is None or held["n"] < 2.0 or held["constant"] <= 0.0:
            return None
        return 1.0 - held["adaptive"] / held["constant"]
