"""Tomorrow's volatility from three horizons of yesterday's.

Everything else in this package that measures volatility measures it **now**.
`volatility.py` reports what the last stretch of prices did; `ranges.py` reads
the same from whole bars; `garch.py` adds a level to revert toward. All three
answer "how big is a move at the moment".

This one answers a different question: **how big is the next one likely to be**.
That distinction is why it is a separate module rather than a fourth estimator,
and it is also why it is the only one here that can be wrong in a way the
others cannot - a description of the past cannot miss, a forecast can.

## The model

Realised volatility has long memory: today's depends on last week's and last
month's, not only on yesterday's, and the dependence decays far too slowly for
one exponential to capture. The usual fix is fractional integration, which is
awkward to fit and worse to run online.

The heterogeneous autoregressive form does it with three lags and a straight
line:

    RV_next = b0 + b_s * RV_short + b_m * RV_medium + b_l * RV_long

The three terms stand for market participants acting on different horizons -
the intraday desk, the weekly book, the monthly allocator - each caring about
volatility measured over their own window. Summing three exponentials with well
separated timescales approximates the slow decay closely enough that this
routinely matches or beats GARCH out of sample, while being a linear regression
on three numbers.

## Why the horizons are in bars

The published form uses days, weeks and months on daily data. Nothing here
runs on daily bars alone - the same instrument is modelled on eight timeframes
at once - so the windows are expressed in **bars of whatever series this is**,
keeping the roughly 1 : 5 : 22 spacing that gives the three terms genuinely
different memories. On 1m bars that is minutes to a third of an hour; on 1d
bars it is the original. The ratio is what matters, not the calendar.

## Fitted online, and what that costs

Three coefficients estimated by stochastic gradient descent on standardised
features, learning as each bar closes. That is the only shape that works here
- a batch fit would need to be redone forever, per instrument, per timeframe.
The cost is that early predictions are poor and the model needs to be told so
rather than quietly asked: `warm` is false until it has seen enough bars for
the coefficients to mean anything, and `predict` falls back to the most recent
realised value until then, which is the naive forecast this is measured
against.

## What it is not

It is not used by anything. Like the other estimators added recently it is fed
the same data and recorded alongside, so the question of whether forecasting
volatility helps a level model can be answered from our own outcomes. A
volatility forecast is a genuinely useful thing to have - a stop sized for the
next thirty minutes should arguably use the volatility expected over them
rather than the volatility just observed - but "arguably" is not a measurement,
and the number every threshold divides by does not change on an argument.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from river import linear_model, optim, preprocessing

from ...shared import effects
from ..state import Restorable
from . import stated

#: On when the flag is, and it shipped once while reaching nothing - see
#: `Book.of`'s note about the restore path.
effects.declare("structures.stated_forecast", enabled=stated.ENABLED)

#: Bars in each horizon, keeping roughly the 1 : 5 : 22 spacing of the
#: published daily/weekly/monthly form. Expressed in bars because the same
#: instrument is modelled on eight timeframes at once - see the module note.
SHORT, MEDIUM, LONG = 1, 5, 22

#: Bars before the fitted coefficients are trusted. Below this `predict`
#: returns the last realised value, which is the naive forecast a HAR model
#: has to beat to be worth anything.
WARMUP = 120

#: Learning rate. Small: the features are standardised and the target is a
#: volatility, so a rate that would be unremarkable on a classification
#: problem lets one violent bar rewrite the coefficients.
LEARNING_RATE = 0.005


def _model():
    return preprocessing.StandardScaler() | linear_model.LinearRegression(
        optimizer=optim.SGD(LEARNING_RATE)
    )


#: Ceiling on `Har.ratio`. Median 1.12 in the record, p99 629, max 1.3e11.
#:
#: **That tail was the symptom of fitting a right-skewed variable in levels**,
#: and `LOG_TARGET` is the cause being removed rather than clipped. The cap
#: stays because a clip is still the right last line against a cold model, but
#: it should now almost never bind.
RATIO_CAP = 10.0

#: Fit `log(realised)` rather than `realised`. Realised volatility is
#: right-skewed and strictly positive, so a squared-error fit in levels is
#: dominated by the largest bars and its residuals are not symmetric - which is
#: what produced a p99 of 629 against a median of 1.12. In logs the errors are
#: roughly symmetric, a negative prediction is impossible by construction, and
#: the model that `research/controls.md` and `research/foundation.md` both scored
#: positively on real markets was **log**-HAR.
LOG_TARGET = True

#: Floor under the log, so a zero-volatility bar cannot produce `-inf`.
MIN_BPS = 1e-6

#: `pi/2`, the bipower scaling that makes `sqrt(x_t * x_{t-1})` an estimator of
#: the continuous part. See `_split`.
BIPOWER = math.pi / 2.0


@dataclass(slots=True)
class Har(Restorable):
    """A realised-volatility forecast from three horizons of its own history.

    `Restorable` because it is a field of `Volatility`, which is saved - so
    this is persisted whether or not it was meant to be, and a field added
    later would raise on the first restore rather than starting cold. That
    reasoning was written the other way round here at first and the persistence
    test caught it, which is the second time in one session that test has paid
    for itself.
    """

    short: int = SHORT
    medium: int = MEDIUM
    long: int = LONG
    warmup: int = WARMUP

    #: The instrument, when the caller knows it. Only used to ask `stated.py`
    #: whether this feed publishes its own volatility - see `predict`.
    feed: str = ""
    #: This series' bar length. `stated.bps_for` needs it to scale an annual
    #: figure onto one bar, and zero means "do not ask".
    interval_seconds: float = 0.0

    _seen: int = 0
    _history: deque[float] = field(default_factory=lambda: deque(maxlen=LONG))
    _model: object = field(default_factory=_model)
    _last_features: dict[str, float] | None = None

    @staticmethod
    def _split(values: list[float]) -> tuple[list[float], list[float]]:
        """Separate the continuous part of each bar from its jump part.

        See `structures-vol-har.md` in research/docs.
        """
        cont: list[float] = []
        jump: list[float] = []
        for i, x in enumerate(values):
            previous = values[i - 1] if i else x
            bipower = BIPOWER * math.sqrt(max(x, 0.0) * max(previous, 0.0))
            # A jump cannot be negative: a bar quieter than its neighbour is a
            # quiet bar, not a negative jump.
            this_jump = max(x - bipower, 0.0)
            jump.append(this_jump)
            cont.append(max(x - this_jump, 0.0))
        return cont, jump

    def _features(self) -> dict[str, float] | None:
        """Means over the three horizons, split into continuous and jump parts.

        Six regressors where the published form has three. The three horizons
        are unchanged and are what makes this HAR; the split is what makes it
        HAR-CJ, and it is there because the two components have genuinely
        different memories - see `_split`.
        """
        if len(self._history) < self.long:
            return None
        values = list(self._history)
        cont, jump = self._split(values)

        def mean(seq: list[float], window: int) -> float:
            take = seq[-window:] if window else seq
            return sum(take) / max(len(take), 1)

        return {
            "short": mean(values, self.short),
            "medium": mean(values, self.medium),
            "long": mean(values, 0),
            "cont_short": mean(cont, self.short),
            "cont_long": mean(cont, 0),
            "jump_short": mean(jump, self.short),
            "jump_long": mean(jump, 0),
        }

    def observe(self, realised_bps: float) -> None:
        """Take one bar's realised volatility, in basis points.

        The features from *before* this observation are what predicted it, so
        the model learns on the pair it actually had to forecast with - using
        the post-update window would be fitting to a number that includes the
        answer.
        """
        if realised_bps <= 0:
            return
        if self._last_features is not None:
            target = realised_bps
            if LOG_TARGET:
                target = math.log(max(realised_bps, MIN_BPS))
            self._model.learn_one(self._last_features, target)
            self._seen += 1
        self._history.append(realised_bps)
        self._last_features = self._features()

    def published(self) -> float | None:
        """The volatility this instrument's own name states, for one bar.

        See `structures-vol-har.md` in research/docs.
        """
        if not self.feed or self.interval_seconds <= 0 or not stated.ENABLED:
            return None
        got = stated.bps_for(self.feed, self.interval_seconds)
        if got is not None:
            effects.fired("structures.stated_forecast")
        return got

    def predict(self) -> float:
        """Expected realised volatility for the next bar, in basis points.

        See `structures-vol-har.md` in research/docs.
        """
        told = self.published()
        if told is not None and told > 0:
            return told
        latest = self._history[-1] if self._history else 0.0
        if not self.warm or self._last_features is None:
            return latest
        got = float(self._model.predict_one(self._last_features) or 0.0)
        if LOG_TARGET:
            # `exp` of a cold or wild fit can overflow; an absurd forecast is
            # the model having nothing, which is what `latest` already means.
            try:
                got = math.exp(got)
            except OverflowError:
                return latest
        # A forecast of zero or a negative volatility is the regression saying
        # it has nothing, not a prediction of stillness.
        return got if got > 0 else latest

    def predict_over(self, bars: int) -> float:
        """Expected realised volatility **per bar** over the next `bars`.

        See `structures-vol-har.md` in research/docs.
        """
        if bars <= 1:
            return self.predict()
        told = self.published()
        if told is not None and told > 0:
            return told  # constant sigma: the horizon changes nothing
        near = self.predict()
        if not self.warm or self._last_features is None:
            return near
        far = float(self._last_features.get("long", near))
        if far <= 0:
            return near
        # Weight toward the long-horizon mean as the horizon lengthens, capped
        # at the longest window the model actually holds.
        share = min(bars / float(self.long), 1.0)
        return (1.0 - share) * near + share * far

    @property
    def warm(self) -> bool:
        return self._seen >= self.warmup

    @property
    def ratio(self) -> float:
        """Forecast over the most recent realised value. 1.0 when it has no view.

        Above 1 the model expects the next bar to be livelier than the last.
        This is the part none of the other estimators can express, because they
        describe what has already happened.
        """
        latest = self._history[-1] if self._history else 0.0
        if latest <= 0 or not self.warm:
            return 1.0
        # Bounded, and the record says why. Measured over 19,511 published
        # values on 2026-09-03: median **1.12**, p99 **629**, max
        # **132,923,621,621**. `latest <= 0` catches a zero denominator and
        # nothing near one, so a quiet bar followed by an ordinary forecast
        # produces a number with no meaning.
        #
        # A forecast ten times the last realised value is already an extreme
        # claim about the next bar. Past that the ratio is describing the
        # denominator, not the forecast. See research/standardising.md for what
        # an unbounded ratio did to the break model's standardiser.
        return min(self.predict() / latest, RATIO_CAP)
