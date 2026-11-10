"""Nautilus's fuzzy candle grading, joined to this desk's level question.

**This module is the instruction `candles.py` already wrote and nobody
followed.** Its `Candles` docstring says it plainly: `fuzzy_candlesticks`
"grades body, size and wicks into categories against a rolling window, which
is a better size judgement than this module's fixed fractions - `TAIL_SHARE`,
`STUB_SHARE`, `BODY_THIRD`. What it has no notion of is a **level**, and
`confirms(bars, level, want_up)` is the question this desk asks. Use both:
theirs for how big, this for where."

`"fuzzy"` has been in `indicators/__init__.FRAMEWORK` the whole time and had
**exactly one reference in the repository - its own registration.** Another
built-and-unread entry, like `BjorgumLevels` before `zones.py` and
`context_bar_types` before the interval fan-out.

## Why a grade beats a ratio, and this is the whole argument

A fixed fraction asks "is the tail more than half the range". A grade asks "is
the tail long **for this market lately**", against a rolling mean and standard
deviation. Three things follow and all three are measured facts on this desk:

* **It is scale-free without a scale.** Every `*_vol` reading here needs a
  `unit` and a `check_scale` call, and `a-synthetic-at-price-one-hides-scale-bugs`
  records what happens when that goes wrong. An ordinal computed from a bar's
  own range against its own window needs none of it: a `WICK_LARGE` means the
  same thing on gold at 4,000 and on EURUSD at 1.09.
* **It absorbs a threshold nobody specified.** The price-action literature
  describes a pin bar by a long tail and states **no tail-to-body ratio** -
  checked across its own pages. Encoding that as 0.5 is inventing the method's
  parameter and then reporting results under its name. Encoding it as
  `lower_wick_size >= WICK_LARGE` leaves the question where the source left
  it, and the sweep is over four ordinals instead of a continuum.
* **Wickiness is a market property, not a signal.**
  `how-markets-differ-from-every-simple-process` measured real bars as
  *wickier* than every simple process. So an absolute wick threshold fires more
  often on real data than on a walk **for mechanical reasons**, and a rule
  built on one inherits that as a fake edge. A window-relative grade is
  normalised against exactly that, which is what makes it the honest encoding
  rather than only the tidier one.

## What is delegated and what is ours

The fuzzification is **theirs** and is not reimplemented here: `period` bars of
history, four thresholds in standard deviations (0.5, 1.0, 2.0, 3.0), giving
direction in -1/0/+1, overall size in 0..6, body in 0..4 and each wick in 0..3.
`indicators/__init__` records that two of Nautilus's indicators are
arithmetically wrong and the rest sound - and that this one had never been
exercised here, so `tests/test_fuzzy_candles.py` exercises it before anything
trades on it, including the test that it is **window-relative at all**.

Ours is the level: `rejection(level, want_up)` asks whether the graded bar is a
rejection *at a price*, which no amount of candle shape can answer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.indicators.fuzzy_candlesticks import FuzzyCandlesticks
from nautilus_trader.model.data import Bar as NautilusBar

from .candles import Bar, confirms, touched

#: The window the grades are relative to. 10 is what `FRAMEWORK` already
#: registered, kept so the two entries cannot disagree about what `fuzzy`
#: means. Short on purpose: "long for lately" is a claim about lately.
PERIOD = 10

#: The membership thresholds, in **standard deviations** of the rolling window.
#: Nautilus's own defaults, named here because a reader of a result needs to
#: know a `WICK_LARGE` is "two sigma of recent wick share" and not a fraction.
THRESHOLDS: tuple[float, float, float, float] = (0.5, 1.0, 2.0, 3.0)

#: Wick grades, as `fuzzy_enums.CandleWickSize` orders them.
WICK_NONE, WICK_SMALL, WICK_MEDIUM, WICK_LARGE = 0, 1, 2, 3

#: Body grades, as `fuzzy_enums.CandleBodySize` orders them.
BODY_NONE, BODY_SMALL, BODY_MEDIUM, BODY_LARGE, BODY_TREND = 0, 1, 2, 3, 4

#: What `pin` asks for by default, and **both halves matter**. A long tail with
#: a long opposing wick is a bar rejected from both directions, which is
#: indecision rather than a signal - `candles.STUB_SHARE` is the fixed-fraction
#: form of the same guard, and leaving it out is how a doji counts as a pin.
PIN_TAIL = WICK_LARGE
PIN_STUB = WICK_SMALL
#: A body this graded or smaller. `BODY_TREND` is the graded form of "this bar
#: was the move", which is the opposite shape to a rejection.
PIN_BODY = BODY_MEDIUM


@dataclass(frozen=True, slots=True)
class Grade:
    """One bar's fuzzy reading. Ordinals, not prices, and so unit-free.

    Named rather than passed around as `FuzzyCandle` so this package's readers
    see plain ints and so `features` has somewhere to come from. The values are
    exactly Nautilus's enum values; nothing is rescaled, because a rescaled
    ordinal is a number whose provenance a result cannot state.
    """

    #: -1 bear, 0 doji, +1 bull.
    direction: int
    #: Overall size, 0..6.
    size: int
    #: Body, 0..4.
    body: int
    #: Wicks, each 0..3.
    upper: int
    lower: int

    def tail(self, want_up: bool) -> int:
        """The wick that would have rejected the level, graded.

        A trade wanting **up** is rejected from below, so its tail is the
        *lower* wick. Naming this for the trade rather than for the wick is the
        inversion that reads identically at the call site and means the
        opposite - `origins.Zone.of` carries the same warning about
        `Origin.side`.
        """
        return self.lower if want_up else self.upper

    def stub(self, want_up: bool) -> int:
        """The opposing wick, graded. See `PIN_STUB`."""
        return self.upper if want_up else self.lower


def pin(
    grade: Grade,
    want_up: bool,
    *,
    tail: int = PIN_TAIL,
    stub: int = PIN_STUB,
    body: int = PIN_BODY,
) -> bool:
    """Whether this graded bar is a pin bar in the direction `want_up`.

    **The source states no tail-to-body ratio**, so the parameters here are
    ordinals and the sweep is over four values rather than a continuum. The
    defaults are this module's reading of "long tail, short opposing wick,
    body that is not itself the move" and are **not** the method's: the method
    does not specify them, and `origin-zones-traded.md` is the house precedent
    for saying so rather than quietly choosing.

    A doji is refused by the body grade alone being insufficient: `BODY_NONE`
    passes `body <= PIN_BODY`, so the direction check is what excludes it -
    a bar with no direction cannot reject in one.
    """
    if grade.direction == 0:
        return False
    return grade.tail(want_up) >= tail and grade.stub(want_up) <= stub and grade.body <= body


def grade_window(
    window: list[tuple[float, float, float, float]],
    *,
    period: int = PERIOD,
    thresholds: tuple[float, float, float, float] = THRESHOLDS,
) -> Grade | None:
    """Grade the **last** bar of a window of `(open, high, low, close)`.

    For research and backtests, which have bars as arrays and not as Nautilus
    `Bar` objects. `update_raw` is the framework's own entry point, so this is
    the same arithmetic the live indicator runs - `reproduce-the-baseline-before-an-increment`
    is why that matters: a harness with its own copy of the grading would
    measure a different rule from the one that trades.

    None until there are `period` bars, rather than a grade computed from
    fewer: the grades are relative to the window, so a short window gives a
    reading whose scale is not the one the result will be quoted in.
    """
    if len(window) < period:
        return None
    engine = FuzzyCandlesticks(period, *thresholds)
    for open_, high, low, close in window[-period:]:
        engine.update_raw(open_, high, low, close)
    return _grade_of(engine)


def _grade_of(engine: FuzzyCandlesticks) -> Grade | None:
    value = engine.value
    if value is None:
        return None
    return Grade(
        direction=int(value.direction),
        size=int(value.size),
        body=int(value.body_size),
        upper=int(value.upper_wick_size),
        lower=int(value.lower_wick_size),
    )


class FuzzyCandles(Indicator):
    """Graded candles with a level question attached.

    Registered with `register_indicator_for_bars`, so the engine feeds it and
    nothing here re-implements a bus, a clock or a warm-up. No `source` and no
    `unit`: it reads a bar's whole shape and the grades are ordinals relative
    to their own window, which is the property that makes it scale-free - see
    the module docstring.
    """

    def __init__(
        self,
        *,
        period: int = PERIOD,
        thresholds: tuple[float, float, float, float] = THRESHOLDS,
        kept: int = 3,
    ) -> None:
        if kept < 2:
            raise ValueError(
                f"kept={kept} cannot see a two-bar pattern, and `candles.confirms` "
                f"needs the bar before to read an engulfing."
            )
        super().__init__([period, *thresholds, kept])
        self.period = int(period)
        self.thresholds = thresholds
        self._fuzzy = FuzzyCandlesticks(int(period), *thresholds)
        self._bars: deque[Bar] = deque(maxlen=int(kept))
        self._grade: Grade | None = None

    # ------------------------------------------------------------- the engine

    def handle_bar(self, bar: NautilusBar) -> None:
        """Nautilus's entry point. Feeds the grader and keeps the prices.

        **Both, because the grades cannot answer a level question.** The
        framework indicator holds no prices a caller can reach - its window is
        percentages and lengths - so `rejection` would have nothing to compare
        with a level if this did not keep the bars itself.
        """
        self._fuzzy.handle_bar(bar)
        self._bars.append(
            Bar(
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
            )
        )
        # **Only once their window is full, and this was a bug a test
        # caught.** `FuzzyCandlesticks` publishes a `value` from a partial
        # window, so this read a grade from three bars - while `grade_window`
        # returns None below `period`, because a grade is relative to its
        # window and one taken from fewer bars is quoted in a different scale.
        # Live and research would have graded the same bar differently during
        # warm-up, which is the one failure this repository is built against.
        self._grade = _grade_of(self._fuzzy) if self._fuzzy.initialized else None
        self._set_has_inputs(True)
        # **Theirs *and* ours.** The grader initialises after `period` bars and
        # `confirms` needs two, so a reading is only complete when both are -
        # an indicator that reported initialised on one of them would answer
        # `rejection` with a grade and no pattern, or the reverse.
        if not self.initialized and self._fuzzy.initialized and len(self._bars) >= 2:
            self._set_initialized(True)

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen a bar."""
        self._fuzzy.reset()
        self._bars.clear()
        self._grade = None
        self._set_has_inputs(False)
        self._set_initialized(False)

    # ------------------------------------------------------------ the reading

    @property
    def grade(self) -> Grade | None:
        """The last bar's grades, or None before `period` bars.

        None rather than a reading from a partial window - see `handle_bar`.
        """
        return self._grade

    @property
    def vector(self) -> list[int]:
        """The grades as the framework's own vector of ints, for a model."""
        return list(self._fuzzy.vector or [])

    def pin(self, want_up: bool, **limits: int) -> bool:
        """Whether the last bar is a pin bar in this direction. See `pin`."""
        return False if self._grade is None else pin(self._grade, want_up, **limits)

    def rejection(self, level: float, want_up: bool, tolerance: float = 0.0) -> str:
        """The graded rejection at `level`, or "" if there is none.

        **Theirs for how big, ours for where**, which is the one sentence this
        module exists for. `candles.confirms` already enforces the check most
        easily left out and the most important: a tail that pierces support on
        a bar that *closes* below it is support breaking, not support holding.
        This adds the size judgement that `confirms` makes with fixed fractions.

        Returns the grade's own name for the shape - `pin` or the pattern
        `candles.confirms` found - so a journal row says which test passed.
        """
        if self._grade is None or len(self._bars) < 2:
            return ""
        if not touched(self._bars[-1], level, tolerance):
            return ""
        # The close has to be on the side the trade wants, whichever test
        # follows. Read here rather than left to `confirms`, because `pin` does
        # not consult the level at all and would otherwise accept a pierce.
        bar = self._bars[-1]
        if (bar.close < level) if want_up else (bar.close > level):
            return ""
        if self.pin(want_up):
            return "pin"
        return confirms(list(self._bars), level, want_up, tolerance)

    def features(self) -> dict[str, float]:
        """The grades as journal columns, or empty before there is a reading.

        Prefixed `fuzzy_` and floats, because `Intent.features` is
        `dict[str, float]`. The ordinals are **not** rescaled to 0..1: a
        rescaled ordinal is a number whose provenance a result cannot state,
        and these are Nautilus's enum values exactly.
        """
        if self._grade is None:
            return {}
        return {
            "fuzzy_direction": float(self._grade.direction),
            "fuzzy_size": float(self._grade.size),
            "fuzzy_body": float(self._grade.body),
            "fuzzy_upper_wick": float(self._grade.upper),
            "fuzzy_lower_wick": float(self._grade.lower),
        }

    def card(self) -> dict[str, Any]:
        """A readable line for a tally, naming the grades rather than numbering."""
        if self._grade is None:
            return {"fuzzy": "unwarmed"}
        sizes = ("none", "small", "medium", "large", "trend")
        wicks = ("none", "small", "medium", "large")
        return {
            "direction": {-1: "bear", 0: "doji", 1: "bull"}[self._grade.direction],
            "body": sizes[min(self._grade.body, len(sizes) - 1)],
            "upper": wicks[min(self._grade.upper, len(wicks) - 1)],
            "lower": wicks[min(self._grade.lower, len(wicks) - 1)],
        }


def graded_at(
    fuzzy: FuzzyCandles,
    levels: list[float],
    want_up: bool,
    tolerance: float = 0.0,
) -> list[tuple[float, str]]:
    """Which of `levels` the last bar made a graded rejection at.

    **The composition this module exists to make possible**, and it takes
    plain floats on purpose. A level can come from `BjorgumLevels`
    (`zone.level`), from `Displacement` (`origin.line`), from `Levels`, or from
    a placebo generator - and `delivering.md`'s table is why that matters:
    those are "one hypothesis with several detectors, not several hypotheses",
    so the grading must not know which nominator it is serving. Importing a
    zone type here would couple the shape question to one answer to the level
    question and quietly make a cross-nominator comparison impossible.

    Returns `(level, shape)` pairs, so a caller can tell a `pin` from an
    `engulfing` and can count how many nominated levels one bar rejected at -
    which is itself a reading worth having, since several zones at one price
    is `a-magnet-is-a-shared-reference`'s whole point.
    """
    found = [(level, fuzzy.rejection(level, want_up, tolerance)) for level in levels]
    return [(level, shape) for level, shape in found if shape]


__all__ = [
    "BODY_MEDIUM",
    "BODY_TREND",
    "PERIOD",
    "PIN_BODY",
    "PIN_STUB",
    "PIN_TAIL",
    "THRESHOLDS",
    "WICK_LARGE",
    "WICK_SMALL",
    "FuzzyCandles",
    "Grade",
    "grade_window",
    "graded_at",
    "pin",
]
