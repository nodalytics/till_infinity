"""Online anomaly detection over cross-venue features.

Two detectors, because "unusual" has two useful meanings and one model cannot
express both:

- **`HalfSpaceTrees`** scores the joint feature vector — deviation, spread ratio
  and staleness together. It catches combinations no single threshold would:
  a small deviation is fine, a slightly wide spread is fine, both at once on a
  venue that has gone quiet is not. Its score is **not calibrated** — on normal
  cross-venue data the median lands around 0.77 — so a fixed cutoff would fire
  on half of everything. `QuantileFilter` is what makes it usable: it learns the
  running distribution of scores and flags only the top `q`, which is a
  threshold that retunes itself as the market changes.
- **`GaussianScorer`** tracks one number per venue, so the score reads as "how
  many standard deviations is this, *for this venue*". A venue that normally
  sits 2bps off consensus is not news at 2bps; one that never leaves 0.1bps is.

Both learn continuously and neither is ever told what an anomaly looks like.
That is the point: thresholds age badly and a market that changes character
invalidates them silently, whereas a model that learns from the last N readings
is always describing the market that exists now.

Scoring happens **before** learning, always. Learning first would teach the
model that the anomaly is normal, and it would then score it as normal — the
detector would quietly train itself to miss exactly what it exists to find.
"""

from __future__ import annotations

import time
from math import erf, sqrt

from river import anomaly as river_anomaly
from river import preprocessing

from ..logging import get_logger
from .features import Books
from .models import Shape, Signal

log = get_logger(__name__)

#: Features fed to the joint model, in a fixed order so a restored model lines up.
FEATURES = ("abs_dev_bps", "spread_ratio", "staleness_ratio")

#: Metrics tracked per venue in their own right. Each answers a different
#: question, so each gets its own distribution rather than being blended.
#:
#: `dev_bps` signed, not absolute, and that matters more than it looks:
#: GaussianScorer fits a normal and scores `2*|CDF(y) - 0.5|`. A signed
#: deviation between venues really is roughly normal, so the fit is sound and
#: the two-tailed score already covers both directions. Folding it to absolute
#: first makes it half-normal, which a normal fit cannot represent — the upper
#: tail is then permanently overweight and the scorer cries wolf.
PER_VENUE = ("dev_bps", "spread_ratio")

#: Readings needed before a score means anything. Below this the model has no
#: idea what normal is and would call everything unusual.
WARMUP = 60

#: Quantile of the score distribution above which a joint reading is unusual.
#: 0.999 is roughly one tick in a thousand per venue — with six venues quoting
#: continuously that is a handful an hour, not a stream.
ANOMALY_QUANTILE = 0.999
#: How many standard deviations from a venue's own norm counts as unusual.
SIGMA = 4.0

#: A venue this far off consensus, or this much stiller than the group, is not
#: ambiguous — it needs no model to interpret and no calendar to explain.
OBVIOUS_DEV_BPS = 50.0
#: Times longer than the group has been still. A venue quoting the same price
#: while five others move is not a judgement call.
OBVIOUS_STALENESS = 5.0
#: Below this a "stale" venue is just a quiet second.
MIN_STALE_SECONDS = 20.0


class Detector:
    """Cross-venue anomaly detection for every instrument at once.

    One `HalfSpaceTrees` per instrument rather than one globally: gold and
    EURUSD have different normal ranges for every feature, and a shared model
    would spend its capacity learning the difference between instruments rather
    than the difference between venues.
    """

    def __init__(
        self,
        *,
        warmup: int = WARMUP,
        quantile: float = ANOMALY_QUANTILE,
        sigma: float = SIGMA,
        seed: int = 7,
    ) -> None:
        self.warmup = warmup
        self.quantile = quantile
        self.sigma = sigma
        self.seed = seed
        self.books = Books()
        self._joint: dict[str, object] = {}
        self._deviation: dict[tuple[str, str, str], river_anomaly.GaussianScorer] = {}
        self._seen: dict[str, int] = {}

    # ------------------------------------------------------------- models

    def _model(self, feed: str):
        model = self._joint.get(feed)
        if model is None:
            # Scaled because HalfSpaceTrees works on ranges, and staleness in
            # seconds would otherwise dominate a deviation in basis points.
            model = preprocessing.MinMaxScaler() | river_anomaly.QuantileFilter(
                river_anomaly.HalfSpaceTrees(n_trees=25, height=8, window_size=250, seed=self.seed),
                q=self.quantile,
                # Do not learn from what it just called an anomaly: a detector
                # trained on its own detections drifts towards accepting them.
                protect_anomaly_detector=True,
            )
            self._joint[feed] = model
        return model

    def _venue_model(self, feed: str, venue: str, metric: str) -> river_anomaly.GaussianScorer:
        """One scorer per (instrument, venue, metric).

        Per metric, not per venue: "unusually far from consensus" and
        "unusually wide" are different questions about the same venue, and a
        single scorer over a blend of the two answers neither.
        """
        key = (feed, venue, metric)
        model = self._deviation.get(key)
        if model is None:
            model = self._deviation[key] = river_anomaly.GaussianScorer(grace_period=self.warmup)
        return model

    # ------------------------------------------------------------ scoring

    def observe(self, payload: dict) -> list[Signal]:
        """Take one quote, return whatever it says. Usually nothing."""
        seen = self.books.observe(payload)
        if seen is None:
            return []
        feed, venue, features = seen
        when = float(payload.get("time") or time.time())
        vector = {name: features[name] for name in FEATURES}

        # Score everything before learning anything. Learning first would teach
        # each model that the reading is normal, and it would then score it as
        # normal — training itself to miss exactly what it exists to find.
        model = self._model(feed)
        score = float(model.score_one(vector))
        unusual = bool(model[-1].classify(score))
        scores = {
            metric: float(self._venue_model(feed, venue, metric).score_one(None, features[metric]))
            for metric in PER_VENUE
        }

        model.learn_one(vector)
        cutoff = _sigma_to_score(self.sigma)
        for metric in PER_VENUE:
            if scores[metric] >= cutoff:
                # Do not learn from an outlier. One 30bps print folded into the
                # variance makes the next 3bps look ordinary, which is how a
                # detector goes quiet right after the interesting thing starts.
                continue
            self._venue_model(feed, venue, metric).learn_one(None, features[metric])
        count = self._seen[feed] = self._seen.get(feed, 0) + 1

        signals = self._obvious(feed, venue, features, when)
        if signals or count < self.warmup:
            # Below warmup the models know nothing, but arithmetic still works,
            # so an unmistakable reading is still reported.
            return signals
        return self._learned(feed, venue, features, when, score, scores, unusual)

    def _obvious(
        self, feed: str, venue: str, features: dict[str, float], when: float
    ) -> list[Signal]:
        """Detections that need no model, and therefore no warmup."""
        if features["staleness"] > MIN_STALE_SECONDS and (
            features["staleness_ratio"] >= OBVIOUS_STALENESS
        ):
            return [
                Signal(
                    shape=Shape.STALE,
                    feed=feed,
                    venue=venue,
                    score=1.0,
                    detail=(
                        f"has not moved in {features['staleness']:.0f}s while "
                        f"{features['venues']:.0f} other venues have"
                    ),
                    features=features,
                    time=when,
                )
            ]
        if features["abs_dev_bps"] >= OBVIOUS_DEV_BPS:
            return [
                Signal(
                    shape=Shape.DISLOCATION,
                    feed=feed,
                    venue=venue,
                    score=1.0,
                    detail=(
                        f"{features['dev_bps']:+.1f}bps from where "
                        f"{features['venues']:.0f} other venues agree"
                    ),
                    features=features,
                    time=when,
                )
            ]
        return []

    def _learned(
        self,
        feed: str,
        venue: str,
        features: dict[str, float],
        when: float,
        score: float,
        scores: dict[str, float],
        unusual: bool,
    ) -> list[Signal]:
        """Detections that only a model that has watched this market can make."""
        cutoff = _sigma_to_score(self.sigma)
        if scores["dev_bps"] >= cutoff:
            return [
                Signal(
                    shape=Shape.DISLOCATION,
                    feed=feed,
                    venue=venue,
                    score=scores["dev_bps"],
                    detail=(
                        f"{features['dev_bps']:+.2f}bps from consensus, outside "
                        f"anything this venue normally does"
                    ),
                    features=features,
                    time=when,
                )
            ]
        if scores["spread_ratio"] >= cutoff and features["spread_ratio"] > 1.0:
            # `> 1.0` because the scorer is two-tailed: unusually *tight* is
            # real, but it is not a liquidity problem and nobody needs telling.
            return [
                Signal(
                    shape=Shape.SPREAD,
                    feed=feed,
                    venue=venue,
                    score=scores["spread_ratio"],
                    detail=(
                        f"spread {features['spread_ratio']:.1f}x the group at "
                        f"{features['spread_bps']:.2f}bps, wide even for this venue"
                    ),
                    features=features,
                    time=when,
                )
            ]
        if unusual:
            named = _describe(features)
            # A signal we cannot name is a signal we should not send. The joint
            # model reports rare *combinations*, and a combination in which no
            # single component is remarkable is a rare shade of ordinary —
            # reporting it sends someone looking for something that is not there.
            if named is None:
                return []
            shape, detail = named
            return [
                Signal(
                    shape=shape,
                    feed=feed,
                    venue=venue,
                    score=score,
                    detail=detail,
                    features=features,
                    time=when,
                )
            ]
        return []

    @property
    def warm(self) -> bool:
        return any(count >= self.warmup for count in self._seen.values())

    def seen(self) -> dict[str, int]:
        return dict(self._seen)


#: What a feature has to reach before it counts as the thing that drove a
#: joint detection. Below all of these, nothing is worth naming.
NAMEABLE_STALENESS = 3.0
NAMEABLE_SPREAD = 1.5
NAMEABLE_DEV_BPS = 1.0


def _describe(features: dict[str, float]) -> tuple[Shape, str] | None:
    """Name the anomaly after whatever actually drove it, or None if nothing did.

    The joint model says "this combination is rare" without saying which part
    was rare, and a signal reported as a dislocation when the price never moved
    is worse than no signal — it sends someone looking in the wrong place.
    """
    if features["staleness_ratio"] >= NAMEABLE_STALENESS:
        return Shape.STALE, (
            f"still for {features['staleness']:.0f}s, "
            f"{features['staleness_ratio']:.1f}x longer than the group"
        )
    if features["spread_ratio"] >= NAMEABLE_SPREAD:
        return Shape.SPREAD, (
            f"spread {features['spread_ratio']:.1f}x the group at {features['spread_bps']:.2f}bps"
        )
    if features["abs_dev_bps"] >= NAMEABLE_DEV_BPS:
        return Shape.DISLOCATION, (
            f"{features['dev_bps']:+.2f}bps off where {features['venues']:.0f} other venues agree"
        )
    return None


def _sigma_to_score(sigma: float) -> float:
    """GaussianScorer returns `2*|CDF(y) - 0.5|`, not a z-score.

    For a normal distribution that is exactly `erf(sigma/sqrt(2))`, so the conversion is
    exact rather than a fit. Keeping `sigma` in the configuration means the
    knob stays in the unit anyone reasoning about markets actually thinks in.
    """
    return erf(sigma / sqrt(2))
