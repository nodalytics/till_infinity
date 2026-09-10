"""A learned volatility forecast, online, scored against the two it must beat.

`har.py` already forecasts the next bar and already learns from its mistakes:
it is a `StandardScaler | LinearRegression(SGD)` refitting on every close. So
this is not a new idea in this package. It is that idea with the two limits
removed - **linear**, and **three features, all of them the same quantity at
different lags**.

What that costs is specific. HAR cannot express "a big bar is usually followed
by a big bar, *unless* the big bar was a single rejection wick, in which case
it is usually followed by a small one." That is an interaction between
magnitude and shape and a straight line has nowhere to put it.

## One model for the whole book, not one per series

This is the decision worth arguing with, because `returns.py` makes the
opposite one a few files away and says why: its features include **macro**
inputs - a carry gap, a dollar index - and "a euro cross and a dollar index do
not share a carry gap", so a pooled model would fit one weight right for
neither. That reasoning is correct and it does not apply here, because there is
no macro input in this feature set. Every feature below is a **ratio of two
quantities measured on the same series**, and every one is dimensionless.

The consequence is the whole design: with a scale-free target and scale-free
features, `eurusd` at 5m and `volatility_75_index` at 4h are **the same
learning problem**. A per-series model learns each from a few hundred bars; one
pooled model learns from all of them at once, and a newly listed instrument
arrives already warm instead of spending a week being useless.

It is also the only version that fits. Measured in this container on 3,000
observations of 16 features, per model:

| model | us/learn | us/predict | memory |
| --- | --- | --- | --- |
| `AMFRegressor` | 1,986 | 126 | **46 MB** |
| `ARFRegressor` | 7,301 | 230 | 8.7 MB |
| `HoeffdingAdaptiveTreeRegressor` | 1,456 | 21 | 2.0 MB |
| **`HoeffdingTreeRegressor`** | **1,596** | **12** | **1.2 MB** |
| `SGTRegressor` | 3,447 | 1.5 | 2.1 MB |
| linear, as `har.py` runs it | 172 | 27 | 20 KB |

53 instruments across eight timeframes is ~424 series. One tree each is 525MB
at the cheapest and 19GB at the most accurate, on a two-core box with about
1.1GB free that was starved into an eleven-hour outage on 2026-09-07. Pooled,
it is **one** tree: 1.2MB, and roughly 1.3 bar-closes a second across the whole
book, which at 1.6ms is about 0.2% of one core.

So the pooled design is not a compromise forced by the box. The box refuses the
alternative, and the pooled version is the better statistics anyway.

## What it predicts

**The log ratio of the next bar's realised volatility to the current
estimate**, `log(realised / ew)`.

Three separate reasons, and the target is doing more work than the model:

* **Scale-free**, which is what lets one model span the book at all.
* **Logarithmic**, because volatility is positive and multiplicative. Regressed
  on raw basis points, a single violent bar on a synthetic index rewrites the
  splits for every instrument - `har.py` already pays for this, and its
  `LEARNING_RATE = 0.005` exists to survive exactly that.
* **Centred on the estimate we already have.** Predicting zero means "the
  current estimate is right", so the model starts at the incumbent answer and
  only has to learn the *correction*. A model that has learned nothing returns
  the existing number rather than a worse one.

## Scored against both baselines, on identical samples

An estimator that has not been checked against an outcome is an opinion.
`consensus_vol.py` says so and scores its four members; this is scored the same
way, with one addition that matters.

Two baselines are scored **on the very same observations**, in the same call:

* **naive** - the last realised value, which is the forecast a persistence
  model reduces to and the one any volatility forecaster has to beat first.
* **har** - the linear forecast this is meant to improve on.

Comparing decayed error histories held in different objects is not the same
test: the members would have seen different samples in a different order.
Here all three are asked the same question about the same bar at the same
moment, so `standings()` is a head-to-head rather than a table of numbers that
were computed nearby.

## Lead time is the point, and price-only features cannot supply it

Everything in `structures/vol/` is a function of the price series, so all of it
is **reactive**: it reports that volatility arrived, never that it is coming.
A GARCH-family model walking into a scheduled event is at its most confident
precisely when it is about to be most wrong.

This class exists to be the place a *leading* input can be put, and it starts
with the two that are already in hand and were not being used:

* **`hour_share`** - `sessions.volatility` already computes each instrument's
  volatility by hour of day as a share of its own daily mean, and 1.8 means
  "one of this instrument's violent hours". The London open is violent
  tomorrow for the same reason it was violent today, and that is known in
  advance rather than inferred. It was published on every call and fed to no
  volatility model.
* **`volume_rel`** - quote and trade arrival rate against its own recent
  normal. Activity tends to rise before range does.

And one that is reactive but fast: **`focus_nats`**, the changepoint evidence
from `learning/focus.py`. A persistence model cannot represent "the past just
stopped being relevant"; FOCuS scores exactly that hypothesis, and handing the
score to the learner is what lets it discount its own history on the bar a
regime breaks rather than a half-life later.

What is still missing is named in `research/clustering.md`: an economic
calendar, and a news feed whose `symbols` field is not empty on all 24,214
rows. Those are the inputs with real lead time, and neither is a modelling
problem.

## What this does not do

Nothing divides by it. It is published beside `vol_bps` exactly as `garch_bps`,
`range_bps` and `forecast_bps` are, and the journal decides whether it earned
anything. Every threshold in this package is denominated in one number, and
switching that number on the strength of the reasoning above is the mistake
this repository keeps writing down.
"""

from __future__ import annotations

import contextlib
import math
from collections import deque
from dataclasses import dataclass, field

from river import anomaly as river_anomaly
from river import preprocessing, tree

from ..state import Restorable
from .analogue import Analogue
from .consensus_vol import MAD_TO_SIGMA, Score

#: Bars of realised history kept per series, for the three horizon features.
#: Matches `har.LONG` so the two forecasters see the same window and any
#: difference between them is the model rather than the memory.
HISTORY = 22

#: Learning pairs before `predict` is trusted. Higher than `har.WARMUP` by a
#: wide margin **because the model is pooled**: 120 observations is a fair
#: warmup for a three-feature line fitted to one series, and nothing at all for
#: a tree spanning the book. This is roughly a day of closes across all series.
WARMUP = 2_000

#: Ceiling on the log correction, in either direction. `exp(1.6)` is about 5x.
#:
#: A forecast five times the standing estimate is already an extreme claim
#: about the next bar; past that the model is describing a denominator rather
#: than making a prediction. `har.RATIO_CAP` is the same guard arrived at the
#: hard way - see the record in its docstring, where an unbounded ratio reached
#: 1.3e11 and went on to be published 19,511 times.
LOG_CAP = 1.6

#: Scores remembered for the anomaly percentile. See `_anomaly_pct`.
ANOMALY_WINDOW = 2_000

#: Grace period, in bars, after a series' last changepoint alarm - how long
#: `focus_nats` keeps decaying rather than being read as current evidence.
CHANGE_MEMORY = 30.0

#: Bars of future averaged into the target. **Not 1, and the reason is a
#: measurement rather than a preference.**
#:
#: One bar's realised volatility is a very noisy draw around a slowly moving
#: scale, and because volatility clusters, consecutive draws are *correlated
#: noise*. A forecaster that repeats the last draw therefore scores well by
#: reproducing the noise. Replayed over 250,000 real bars
#: (`research/harness/volhorizon.py`):
#:
#: | horizon | naive | har | learned at k=1 |
#: | --- | --- | --- | --- |
#: | 1 bar | **0.798** | 0.776 | 0.775 |
#: | 5 bars | 0.825 | **0.839** | 0.822 |
#: | 10 bars | 0.808 | **0.842** | 0.828 |
#:
#: Persistence wins at one bar and loses at five. So a model trained on the
#: single-bar target is being fitted to the noise it will then be graded for
#: not reproducing, and *any* comparison scored on one bar will crown `naive`.
#: Nothing downstream wants the next print either: a stop is placed for the
#: next hour and `vol_bps` is itself a smoothed quantity.
#:
#: 5 rather than 1, on measurement, and rather than 10 for the same reason.
#: Replayed over 250,000 real bars, the learner scored by what it was trained
#: on (`naive` and `har` are fixed baselines on the same bars):
#:
#: | trained on | k=1 | k=5 | k=10 | k=20 |
#: | --- | --- | --- | --- | --- |
#: | next bar | 0.775 | 0.822 | 0.828 | 0.824 |
#: | **forward 5-bar mean** | **0.777** | **0.827** | **0.834** | **0.856** |
#: | forward 10-bar mean | 0.760 | 0.818 | 0.831 | 0.838 |
#: | *naive* | *0.798* | *0.825* | *0.808* | *0.803* |
#: | *har* | *0.776* | *0.839* | *0.842* | *0.842* |
#:
#: The 5-bar target dominates the 1-bar target at every horizon, and at k=20 it
#: is the only thing here that beats `har`. Ten bars is worse than five
#: everywhere, so this is a peak rather than "longer is better".
#:
#: A first attempt at this measurement said the opposite - that the forward
#: target made things worse at every horizon - with a plausible story attached
#: about variance-reduction splitting. That run was contaminated by the
#: shadowing bug recorded in `observe`, and `research/forecasting.md` keeps the
#: episode because the wrong answer was the more believable one.
HORIZON = 5


def _anomaly_model():
    """Joint anomaly score over the whole feature row.

    Every other reading in this package is **univariate**: `vol_stretch` asks
    whether the scale is unusual, `focus_nats` whether the mean just moved,
    the rolling quantiles whether this reading is high for this instrument.
    None of them can say that a combination is unusual while every part of it
    is ordinary - and `learning/anomaly.py` makes exactly that case for the
    cross-venue model: "a small deviation is fine, a slightly wide spread is
    fine, both at once on a venue that has gone quiet is not".

    Here that becomes: an elevated `span_rel` is ordinary, some `focus_nats` is
    ordinary, both together in an hour this instrument is normally quiet in is
    not. That is a statement no single feature in the row can make.

    `MinMaxScaler` in front because `HalfSpaceTrees` partitions the unit cube
    and expects bounded inputs; the ratios here are not bounded. Five trees of
    height six rather than the default ten and eight: measured in this
    container at 290us and 123KB against 685us and 1.16MB, on a two-core box
    with about a gigabyte spare, and the dynamic range that costs is recovered
    by the percentile transform rather than by the model.
    """
    return preprocessing.MinMaxScaler() | river_anomaly.HalfSpaceTrees(
        n_trees=5, height=6, window_size=250, seed=7
    )


def _model():
    """The regressor. Standardised inputs, one tree.

    `HoeffdingTreeRegressor` on the table above: within 10% of the adaptive
    variant's learning cost, an order of magnitude cheaper to predict, and the
    smallest of the tree family by memory - which is the constraint that
    actually binds here.

    The adaptive variant was the tempting choice, since it carries its own
    drift detection. It is not needed: drift is what `focus_nats` is *for*, and
    handing the model the evidence as a feature is a better answer than having
    the tree quietly rebuild a subtree without saying so. One of those appears
    in the journal and the other does not.
    """
    return preprocessing.StandardScaler() | tree.HoeffdingTreeRegressor(grace_period=50)


@dataclass(slots=True)
class Recent(Restorable):
    """The small per-series state the pooled model needs to build a row."""

    realised: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY))
    #: Forecasts whose horizon has not filled yet: each is a feature row and
    #: the running sum of realised volatility since it was made. Learned from
    #: only once `HORIZON` bars have arrived, so the target is the forward
    #: *average* rather than the next noisy print. This is the same shape
    #: `returns.Pending` uses and for the same reason.
    waiting: list[tuple[dict[str, float], float, float, int]] = field(default_factory=list)
    #: The features that predicted the bar now arriving, held so the model
    #: learns on the pair it actually had to forecast with.
    pending: dict[str, float] | None = None
    #: What each forecaster said about that same bar, for the head-to-head.
    said: dict[str, float] = field(default_factory=dict)
    #: The estimate the pending row was centred on, to undo the log ratio.
    unit: float = 0.0
    close: float = 0.0
    #: Decayed mean of log volume, so `volume_rel` is against this series' own
    #: normal rather than an absolute that means nothing across instruments.
    log_volume: float = 0.0
    #: Bars since this series last raised a changepoint, for `focus_age`.
    since_change: float = 1_000.0


@dataclass(slots=True)
class Learned(Restorable):
    """One online regressor over every series, forecasting the next bar.

    Keyed state is per series; the model is not. See the module note for why
    that is the design rather than a concession.
    """

    warmup: int = WARMUP
    horizon: int = HORIZON
    _model: object = field(default_factory=_model)
    _seen: int = 0
    _by_key: dict[str, Recent] = field(default_factory=dict)
    #: Joint anomaly detector over the feature row, and the recent scores it
    #: has produced. Pooled like the model, for the same reason.
    _anomaly: object = field(default_factory=_anomaly_model)
    _anomaly_seen: deque[float] = field(default_factory=lambda: deque(maxlen=ANOMALY_WINDOW))
    #: Relevance-weighted rather than recency-weighted - the one part of an
    #: attention layer that fits on this box. Scored beside the tree, on the
    #: same rows, so "does similarity beat splitting" is a measurement. See
    #: `analogue.py`.
    _analogue: Analogue = field(default_factory=Analogue)
    #: Head-to-head, all three asked about the same bar at the same moment.
    _scores: dict[str, Score] = field(default_factory=dict)

    def _recent(self, key: str) -> Recent:
        found = self._by_key.get(key)
        if found is None:
            found = self._by_key[key] = Recent()
        return found

    def _score(self, name: str) -> Score:
        found = self._scores.get(name)
        if found is None:
            found = self._scores[name] = Score()
        return found

    @property
    def warm(self) -> bool:
        return self._seen >= self.warmup

    def _anomaly_pct(self, row: dict[str, float]) -> float:
        """Where this row's anomaly score sits among the recent ones, in [0, 1].

        **The percentile, not the score.** `HalfSpaceTrees` is uncalibrated -
        `learning/anomaly.py` records its median landing around 0.77 on normal
        data, and measured here on random rows the tenth and ninetieth
        percentiles were 0.70 and 0.83. A feature living in a tenth of its range
        is one a tree can barely split on, and the position of that band drifts
        as the market changes, so a constant read off it today would mean
        something else next month.

        Ranking against the model's own recent output fixes both: it fills
        [0, 1], and it re-centres itself the way `QuantileFilter` does for the
        cross-venue detector rather than the way a fixed cutoff does not.

        0.5 while cold - deliberately the middle. This is one feature among
        twenty and a missing reading should sit where it says nothing, not at
        an extreme that says "most anomalous thing I have ever seen".
        """
        try:
            score = float(self._anomaly.score_one(row))
        except Exception:
            return 0.5
        if not math.isfinite(score):
            return 0.5
        seen = self._anomaly_seen
        if len(seen) < 200:
            seen.append(score)
            return 0.5
        below = sum(1 for past in seen if past < score)
        seen.append(score)
        return below / len(seen)

    def features(
        self,
        key: str,
        *,
        ew_bps: float,
        garch_bps: float = 0.0,
        range_bps: float = 0.0,
        har_bps: float = 0.0,
        stretch: float = 1.0,
        open_: float = 0.0,
        high: float = 0.0,
        low: float = 0.0,
        close: float = 0.0,
        hour: float = -1.0,
        weekday: float = -1.0,
        hour_share: float = 1.0,
        volume: float = 0.0,
        focus_nats: float = 0.0,
        interval_seconds: float = 0.0,
    ) -> dict[str, float] | None:
        """One row, or None when the series has nothing to say yet.

        Every value here is dimensionless. That is not tidiness - it is the
        condition that makes one pooled model legitimate, and a single feature
        in price units would silently turn this back into a per-series model
        that happens to share its splits with 423 other instruments.
        """
        if ew_bps <= 0:
            return None
        seen = self._recent(key)
        history = list(seen.realised)
        if len(history) < 2:
            return None

        def rel(value: float, sigma: bool = False) -> float:
            if value <= 0:
                return 1.0
            return (value / MAD_TO_SIGMA if sigma else value) / ew_bps

        span = max(high - low, 0.0)
        body = abs(close - open_) / span if span > 0 else 0.0
        upper = (high - max(open_, close)) / span if span > 0 else 0.0
        lower = (min(open_, close) - low) / span if span > 0 else 0.0

        short = history[-1]
        medium = sum(history[-5:]) / min(len(history), 5)
        long = sum(history) / len(history)

        row = {
            # The other estimators, as corrections to the incumbent rather than
            # as levels. A tree splitting on "garch is 1.3x the EW estimate"
            # transfers across the book; one splitting on "garch is 17bps"
            # learns that volatility indices exist.
            "garch_rel": rel(garch_bps),
            "range_rel": rel(range_bps, sigma=True),
            "har_rel": rel(har_bps, sigma=True),
            "stretch": max(0.0, min(float(stretch), 10.0)),
            # The three HAR horizons, relative. Given to the tree so that
            # beating HAR means beating it on its own inputs rather than on a
            # richer feature set - otherwise a win says nothing about linearity.
            "r1": rel(short),
            "r5": rel(medium),
            "r22": rel(long),
            # Whether the scale is rising or falling, which the three levels
            # above contain but only as a difference a linear model has to be
            # given as its own term.
            "accel": (medium / long) if long > 0 else 1.0,
            # **This bar's own size**, in volatility units. Not redundant with
            # `r1` and the omission of it was a real bug: `r1` reads the
            # *realised history*, and at the moment this row is built the bar
            # in front of us has not been appended to it yet. So without this
            # the model could see whether the current bar was a wick or a body
            # and not whether it was large - which is most of the signal, and
            # exactly the thing every estimator in this package is built on.
            #
            # A test caught it, and only because the synthetic series it
            # learns was built so that magnitude was the thing that mattered.
            "span_rel": ((span / close * 10_000) / ew_bps if close > 0 and span > 0 else 0.0),
            # Shape. The interaction HAR structurally cannot hold: a large bar
            # that is one rejection wick and a large bar that is a trend are
            # the same magnitude and different futures.
            "body": body,
            "upper_wick": upper,
            "lower_wick": lower,
            "gap": (
                abs(open_ - seen.close) / seen.close * 10_000 / ew_bps
                if seen.close > 0 and open_ > 0
                else 0.0
            ),
            # Leading, and free: the intraday shape is known a day ahead.
            # Sine and cosine rather than the raw hour, so 23:00 and 00:00 are
            # adjacent - a tree can split a bare hour into arbitrary sets, but
            # it needs far more data to discover a wrap it could be told about.
            "hour_sin": math.sin(2 * math.pi * hour / 24.0) if hour >= 0 else 0.0,
            "hour_cos": math.cos(2 * math.pi * hour / 24.0) if hour >= 0 else 0.0,
            "hour_share": max(0.0, min(float(hour_share), 5.0)),
            "weekday": float(weekday) if weekday >= 0 else -1.0,
            # Leading-ish: activity tends to rise before range does.
            "volume_rel": (
                math.log1p(volume) / seen.log_volume if volume > 0 and seen.log_volume > 0 else 1.0
            ),
            # Reactive but fast - the evidence that the past stopped applying.
            "focus_nats": max(0.0, min(float(focus_nats), 100.0)),
            "focus_age": min(seen.since_change, CHANGE_MEMORY) / CHANGE_MEMORY,
            # Which timeframe this is, in log seconds. One model spans eight of
            # them and they are not interchangeable: a 1m bar's relationship to
            # its own recent history is not a 4h bar's. This is the only
            # feature that identifies anything about the series, and it
            # identifies its *sampling rate* rather than its name.
            "log_bar": math.log(interval_seconds) if interval_seconds > 0 else 0.0,
        }
        # **Scored before it is learned from, always.** `learning/anomaly.py`
        # states the rule and the reason: learning first teaches the model that
        # the anomaly is normal, and it then scores it as normal - the detector
        # quietly trains itself to miss the thing it exists to find. Learning
        # happens in `observe`, one call later.
        row["anomaly"] = self._anomaly_pct(row)
        return row

    def observe(
        self,
        key: str,
        realised_bps: float,
        row: dict[str, float] | None,
        *,
        ew_bps: float,
        har_bps: float = 0.0,
        close: float = 0.0,
        volume: float = 0.0,
        changed: bool = False,
    ) -> None:
        """Take what the bar actually did, learn from it, and score everyone.

        Called **after** the bar has closed and **before** `row` is used for
        the next one, so the model only ever learns on a pair it could have
        predicted from. The alternative - building features from a window that
        already contains the answer - is the mistake `har.observe` documents,
        and it is the one that makes a backtest look excellent.
        """
        if realised_bps <= 0 or ew_bps <= 0:
            return
        seen = self._recent(key)

        # Score the standing forecasts before anything is updated: each is
        # judged on what it said when it could not yet know.
        #
        # **Scored at one bar, learned at `horizon`.** That looks inconsistent
        # and is deliberate: the scoreboard has to stay comparable with
        # `consensus_vol`, which scores its four members against the next bar,
        # while the *training* target is the forward average for the reason
        # `HORIZON` sets out at length. `research/harness/volhorizon.py` is
        # what scores every member at every horizon on the same replay.
        if seen.pending is not None and seen.unit > 0:
            for name, said in seen.said.items():
                if said > 0:
                    self._score(name).record(said, realised_bps)

        # Every forecast still waiting counts this bar as part of its future,
        # and any whose horizon has now filled is learned from and dropped.
        if seen.waiting:
            grown = []
            # **Not `row`.** Naming this loop variable `row` shadowed the
            # parameter of the same name, so every row appended to the queue
            # below was the last one pulled off it here. The model then learned
            # a near-constant mapping and its tree never split - 1 node after
            # 3,000 observations - which does not look like a bug from the
            # outside: it looks like a model that does not work.
            for waited, unit, so_far, bars in seen.waiting:
                summed = so_far + realised_bps
                filled = bars + 1
                if filled >= self.horizon:
                    target = self._target(summed / filled, unit)
                    self._model.learn_one(waited, target)
                    self._analogue.observe(waited, target)
                    self._seen += 1
                else:
                    grown.append((waited, unit, summed, filled))
            seen.waiting = grown

        # The detector learns the row it scored - without the score it produced,
        # which would otherwise be an input to its own next answer.
        if row:
            # Suppressed rather than caught: a detector nobody gates on must not
            # be able to stop the engine, which is the rule two outages this
            # month were caused by not following.
            with contextlib.suppress(Exception):
                self._anomaly.learn_one({k: v for k, v in row.items() if k != "anomaly"})

        seen.realised.append(realised_bps)
        seen.close = close if close > 0 else seen.close
        if volume > 0:
            got = math.log1p(volume)
            seen.log_volume = got if not seen.log_volume else seen.log_volume * 0.99 + got * 0.01
        seen.since_change = 0.0 if changed else seen.since_change + 1.0

        # What each forecaster says about the bar that has *not* happened yet.
        # `naive` is the last realised value, which is what a persistence model
        # collapses to and the floor any of this has to clear.
        seen.pending = row
        seen.unit = ew_bps
        if row is not None:
            seen.waiting.append((row, ew_bps, 0.0, 0))
            # Bounded. A series that stops reporting must not leave a queue
            # growing against a horizon that will never fill - the same
            # unbounded-accumulator shape that has already cost this
            # repository four outages.
            if len(seen.waiting) > self.horizon * 4:
                del seen.waiting[: len(seen.waiting) - self.horizon * 4]
        analogue = self._analogue.predict(row)
        seen.said = {
            "naive": realised_bps,
            # `har` is fed the sigma-scale realised value, so it forecasts on
            # that scale and is converted to match the rest. `naive` needs no
            # conversion: `Book.learn` has already put `realised_bps` on the
            # mean-absolute scale before this sees it, so every member and the
            # truth they are scored against are now one convention. Mixing them
            # shrank two competitors by a quarter and flattered the third.
            "har": har_bps / MAD_TO_SIGMA if har_bps > 0 else 0.0,
            "learned": self._predict(row, ew_bps, fallback=realised_bps),
            # `None` means it has no view, and that is not the same as agreeing
            # with the incumbent - so it is omitted from the scoreboard rather
            # than entered at the fallback, which would credit it for an answer
            # the estimator already had.
            "analogue": (
                ew_bps * math.exp(max(-LOG_CAP, min(LOG_CAP, analogue)))
                if analogue is not None and math.isfinite(analogue)
                else 0.0
            ),
        }

    def _target(self, realised_bps: float, unit_bps: float) -> float:
        """The log correction to the standing estimate, bounded."""
        return max(-LOG_CAP, min(LOG_CAP, math.log(realised_bps / unit_bps)))

    def _predict(self, row: dict[str, float] | None, ew_bps: float, fallback: float) -> float:
        if row is None or not self.warm:
            return fallback
        try:
            got = float(self._model.predict_one(row) or 0.0)
        except Exception:
            # A learner that has not been asked this shape before must not be
            # able to stop the engine. Two outages this month were a reading
            # nobody gates on taking the structures service down with it.
            return fallback
        if not math.isfinite(got):
            return fallback
        return ew_bps * math.exp(max(-LOG_CAP, min(LOG_CAP, got)))

    def predict(self, key: str) -> float:
        """The standing forecast for this series' next bar, in bps."""
        seen = self._by_key.get(key)
        if seen is None:
            return 0.0
        return float(seen.said.get("learned") or 0.0)

    def ratio(self, key: str) -> float:
        """Forecast over the standing estimate. 1.0 when there is no view.

        The same shape as `har.ratio` and the same reading: above one the model
        expects the next bar to be livelier than the estimate in force. Bounded
        by construction rather than by a cap bolted on afterwards, because the
        model predicts the log of this quantity and the log is what is clipped.
        """
        seen = self._by_key.get(key)
        if seen is None or seen.unit <= 0 or not self.warm:
            return 1.0
        got = float(seen.said.get("learned") or 0.0)
        return got / seen.unit if got > 0 else 1.0

    def standings(self) -> list[tuple[str, float]]:
        """`learned`, `har` and `naive` by accuracy, best first.

        The whole point of this class arriving with its own scoreboard: it is
        allowed to be worse than the line it replaces, and the record has to be
        able to say so without anyone running a separate study.
        """
        return sorted(
            ((n, s.accuracy) for n, s in self._scores.items() if s.warm),
            key=lambda pair: -pair[1],
        )

    def reading(self) -> dict[str, float]:
        """Standings and sample count, for the journal."""
        out = {f"vol_model_{name}": value for name, value in self.standings()}
        out["vol_model_seen"] = float(self._seen)
        return out
