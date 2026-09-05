"""Turning a score that ranks well into a probability that means something.

## Why this exists

`breaking.Breaks` was measured on 2026-09-05 against the only benchmark that
matters for a probability, over 141,230 resolved touches:

| | log loss | accuracy |
| --- | --- | --- |
| quoting the base rate every time | **0.2493** | **93.2%** |
| the model | 0.3624 | 87.4% |

Breaks are **6.8%** of resolutions. With a class that rare, "always hold" is
right 93.2% of the time and a constant 0.068 scores 0.2493 - and the model is
worse on both. It is paying for confidence it has not earned.

That is not the same as the model being useless. `research/force.md` measures
**AUC 0.658** for its two strongest inputs, which is a claim about *ranking*:
touches more likely to break score higher than touches less likely to. Whether
the number attached is the right probability is a separate claim, and nothing
had ever checked it. A model can rank well and be calibrated badly, and this
one is.

Calibration is the standard repair, and it repairs exactly the half that is
broken: it is monotone, so it **cannot change the ranking or the AUC**, and it
moves the numbers to where the outcomes actually are.

## Platt rather than isotonic, deliberately

Isotonic is more flexible and wants more data per bin than a 6.8% positive rate
gives online. Platt is two parameters fitted on the log-odds, which is a
straight line in the space the model already works in - enough to fix
over-confidence, and cheap enough to run per observation without a second pass
over history.

## It has to prove it helped

The failure this project keeps finding is a fix that ships and changes nothing,
or changes the wrong thing. So the calibrator scores **both** streams on the
same observations - its own output and the raw one it was given - and
`improvement` is the difference. It can be negative, and if it is, the
calibrator is the thing to remove.

Nothing consumes the calibrated number yet. It is published beside the raw one
so the record can say which is better before either decides anything.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..state import Restorable

#: How fast the two parameters move. Slow, because they are correcting a
#: systematic bias rather than tracking a moving one - and because a
#: calibrator that chases noise turns a ranking model into a worse one.
RATE = 0.01

#: How many observations the decayed scores remember, matching `online`'s own
#: horizon so the two are comparable.
MEMORY = 2000.0

#: Below this, `apply` returns the raw score unchanged. Two parameters need far
#: less than a six-feature model, but fitted on nothing they are noise, and
#: passing the input through is the honest default.
MIN_SEEN = 200.0


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


@dataclass(slots=True)
class Platt(Restorable):
    """A two-parameter correction on a score's log-odds, fitted online."""

    #: Slope. Below 1 it pulls predictions toward the base rate, which is the
    #: direction an over-confident model needs.
    slope: float = 1.0
    intercept: float = 0.0
    seen: float = 0.0
    #: Decayed log loss of the corrected stream and of the raw one, on the same
    #: observations. The pair is the point: one number alone cannot say whether
    #: this helped.
    loss: float = 0.0
    raw_loss: float = 0.0

    def apply(self, raw: float) -> float:
        """The corrected probability, or `raw` while there is nothing behind it."""
        if self.seen < MIN_SEEN:
            return raw
        return _sigmoid(self.slope * _logit(raw) + self.intercept)

    def observe(self, raw: float, outcome: bool) -> float:
        """Score both streams on this observation, then learn. Returns what it said.

        Predict-then-update, like everything else here, so the scores are out
        of sample by construction rather than by discipline.
        """
        said = self.apply(raw)
        target = 1.0 if outcome else 0.0

        keep = max(0.0, 1.0 - 1.0 / MEMORY)
        self.seen = self.seen * keep + 1.0
        for name, value in (("loss", said), ("raw_loss", raw)):
            safe = min(max(value, 1e-9), 1.0 - 1e-9)
            hit = -(target * math.log(safe) + (1 - target) * math.log(1 - safe))
            setattr(self, name, getattr(self, name) * keep + hit)

        # Gradient of log loss on the two parameters, in log-odds space.
        z = _logit(raw)
        residual = target - _sigmoid(self.slope * z + self.intercept)
        self.slope += RATE * residual * z
        self.intercept += RATE * residual
        return said

    @property
    def log_loss(self) -> float:
        return self.loss / self.seen if self.seen else 0.0

    @property
    def raw_log_loss(self) -> float:
        return self.raw_loss / self.seen if self.seen else 0.0

    @property
    def improvement(self) -> float | None:
        """How much log loss the correction saves. **Negative means remove it.**

        None until there is enough behind it to read, because a calibrator that
        has seen a hundred observations has an opinion about nothing.
        """
        if self.seen < MIN_SEEN:
            return None
        return self.raw_log_loss - self.log_loss

    @property
    def warm(self) -> bool:
        return self.seen >= MIN_SEEN

    def reading(self) -> dict[str, float]:
        """The pair, for a signal's features - never the corrected value alone."""
        if not self.warm:
            return {}
        return {
            "calibrated_loss": round(self.log_loss, 5),
            "uncalibrated_loss": round(self.raw_log_loss, 5),
        }


@dataclass(slots=True)
class Reliability(Restorable):
    """Observed break rate per predicted band - the picture behind the number.

    `Platt` says whether the correction helps. This says *where* the model is
    wrong, which is what tells a reader whether to trust a 90% at all. Ten
    fixed bands, counted rather than fitted, so it cannot itself be miscalibrated.
    """

    bands: int = 10
    said: list[float] = field(default_factory=list)
    hit: list[float] = field(default_factory=list)

    def observe(self, raw: float, outcome: bool) -> None:
        if not self.said:
            self.said = [0.0] * self.bands
            self.hit = [0.0] * self.bands
        where = min(self.bands - 1, max(0, int(raw * self.bands)))
        self.said[where] += 1.0
        self.hit[where] += 1.0 if outcome else 0.0

    def table(self) -> list[tuple[float, float, float]]:
        """(band centre, observed rate, count), for bands with anything in them."""
        out = []
        for i, n in enumerate(self.said):
            if n > 0:
                out.append(((i + 0.5) / self.bands, self.hit[i] / n, n))
        return out
