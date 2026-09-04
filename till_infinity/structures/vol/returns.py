"""What the next stretch of price is expected to do, as a number with a sign.

Everything else in this package predicts something *about a level*: whether a
touch holds, how far the push goes, where the band is. Nothing predicts the
plain forward return, and that gap is worth closing for a reason about
measurement rather than about profit.

## Why bother, when the honest prior is zero

Because the honest prior being zero is a claim, and this is what checks it. A
walk-forward R^2 near zero is the efficient-market answer arriving as a
*measurement* rather than as an assumption - and the same estimator would
report a non-zero one if there were one.

The trap this is built to avoid is the one every "gold price prediction"
tutorial falls into: regressing tomorrow's **price** on a moving average of
today's and reporting 99% R-squared. A random walk's level is almost entirely
explained by its own recent average, so that number is an identity rather than
a finding, and it survives being wrong about everything that matters. The
target here is the **forward return in volatility units**, where the same trick
scores nothing. That is the point of choosing it.

## Scale-free, like everything else

The target is how far price moved, divided by one volatility unit, so a
prediction of 0.5 means "half a typical move" on gold and on eurusd alike.

## Where it is useful for levels

A level call gets its direction from the kNN over past touches at that level.
This is a second opinion built from something else entirely - the state of the
market and the state of policy, rather than the history of one price - so where
they agree there is more behind the call than either provides alone, and where
they disagree that is worth knowing before sizing.

Published as a feature. It decides nothing until the record says it should.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..learning.online import Linear
from ..state import Restorable

#: The inputs, named so the fitted weights can be read. Every one is either
#: already scale-free or in [0, 1] - a feature in price units would defeat the
#: whole design, since the weights are shared across a series' history and a
#: price level is not comparable with itself a month later.
FEATURES: tuple[str, ...] = (
    "pressure_vol",
    "momentum_agree",
    "vol_stretch",
    "forecast_ratio",
    "hour_vol_share",
    "activity",
    "macro_carry_gap_change",
    "macro_dollar_change",
    "macro_us_real_yield_change",
)

#: How far ahead the estimate looks, in bars of whatever interval fed it.
HORIZON = 12


@dataclass(slots=True)
class Pending(Restorable):
    """One prediction waiting for its horizon to arrive."""

    x: list[float] = field(default_factory=list)
    price: float = 0.0
    unit: float = 0.0
    due: int = 0


@dataclass(slots=True)
class Returns(Restorable):
    """Forward return per instrument and interval, learned online.

    One model per series rather than one across the book, which is a real
    choice with a cost: pooling would give every instrument the benefit of
    every other's history, and that is exactly the argument the scale-free
    features exist to support. It is kept separate because the *macro* inputs
    differ per instrument - a euro cross and a dollar index do not share a
    carry gap - so a pooled model would fit one weight that is right for
    neither.
    """

    horizon: int = HORIZON
    models: dict[tuple[str, str], Linear] = field(default_factory=dict)
    waiting: dict[tuple[str, str], list[Pending]] = field(default_factory=dict)
    #: Bars seen per series, so a pending prediction knows when it is due.
    clock: dict[tuple[str, str], int] = field(default_factory=dict)

    def model(self, feed: str, interval: str) -> Linear:
        key = (feed, interval)
        found = self.models.get(key)
        if found is None:
            found = self.models[key] = Linear()
        return found

    @staticmethod
    def inputs(features: dict[str, float]) -> list[float]:
        """The feature vector, with an absent input read as zero.

        Zero rather than omitted, because the vector has to be the same width
        every time or the weights stop meaning anything - and zero *after
        standardisation* is the running mean, which is the right thing for "no
        reading" to mean.
        """
        return [float(features.get(name, 0.0) or 0.0) for name in FEATURES]

    def observe(
        self,
        feed: str,
        interval: str,
        price: float,
        unit: float,
        features: dict[str, float],
    ) -> float | None:
        """Take one bar. Returns the prediction for the next `horizon` bars.

        Learning happens here too, for the predictions this bar completes -
        which is what keeps the whole thing walk-forward. Nothing is ever
        trained on a future it has already been asked about.
        """
        if not feed or not interval or price <= 0 or unit <= 0:
            return None
        key = (feed, interval)
        now = self.clock.get(key, 0) + 1
        self.clock[key] = now
        model = self.model(feed, interval)

        held = self.waiting.setdefault(key, [])
        still: list[Pending] = []
        for pending in held:
            if pending.due > now:
                still.append(pending)
                continue
            model.observe(pending.x, (price - pending.price) / pending.unit)
        self.waiting[key] = still

        x = self.inputs(features)
        said = model.predict(x)
        still.append(Pending(x=x, price=price, unit=unit, due=now + self.horizon))
        # Bounded: a series that stops printing must not hold its pending
        # predictions forever, and one that prints fast must not accumulate.
        if len(still) > self.horizon * 4:
            del still[: len(still) - self.horizon * 4]
        return said if model.warm else None

    def reading(self, feed: str, interval: str) -> dict[str, float]:
        """What this series' model currently claims, for a signal's features."""
        model = self.models.get((feed, interval))
        if model is None or not model.warm:
            return {}
        return {"return_r2": round(model.r2, 5), "return_seen": round(model.seen, 1)}

    def importance(self, feed: str, interval: str) -> list[tuple[str, float]]:
        """Which inputs carry the signal for this series, largest first."""
        model = self.models.get((feed, interval))
        return model.importance(FEATURES) if model else []
