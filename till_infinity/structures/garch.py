"""Volatility with somewhere to return to.

`volatility.py` tracks an exponentially weighted mean absolute return, and the
two decisions behind it are both right. **Absolute rather than squared**,
because financial returns are fat-tailed and a variance is dominated by its
worst observation. **Exponential rather than a window**, because a window has
an edge and a level's zone should not jump when a violent bar falls off it.

What it does not have is a level to come back to. An exponentially weighted
mean is a random walk over its own history: after a shock it decays toward
wherever the recent data happens to sit, and nothing says a calm instrument
that spiked ought to end up calm again. That is a real omission, because the
one thing volatility is famous for is clustering *and* reverting - shocks
persist for a while and then fade, and the fading has a destination.

## The model

This is GARCH(1,1) written on absolute returns rather than squared ones - the
Taylor-Schwert parameterisation, which models the conditional *scale* directly:

    s_t = w + a * |r_{t-1}| + b * s_{t-1}

The ordinary form squares everything, and adopting it here would have quietly
undone `volatility.py`'s first decision: one outlier would move the estimate
that every threshold in this package divides by. Absolute returns keep the
robustness and still give the recursion.

**The parameters are targeted rather than fitted.** `w` is not free; it is
pinned to the long-run scale so the model reverts there by construction:

    w = (1 - a - b) * L

with `L` a slowly decayed mean of `|r|`. This is Engle's variance targeting,
and it is what makes the model usable online: fitting three free parameters per
instrument per timeframe by maximum likelihood needs a batch, a solver, and a
constraint region to stay inside, and it would still be re-fitting forever.
Targeting leaves one number to estimate and it is the number a slow average
already gives.

**`a + b` is the whole difference.** At exactly 1 the constant vanishes and
this reduces to the estimator already here - the equivalence is a test, not a
claim. Below 1 the estimate is pulled toward `L` at a rate of `1 - a - b` per
bar. `a` is taken from the same half-life `volatility.py` uses, so
responsiveness to a new shock is unchanged and the only thing added is the
destination.

## What it is not

It is not a forecast of price and it is not a filter. It produces one number in
the same units as the existing estimate, on the same input, so the two can be
recorded side by side and the question "does reverting help" becomes a
measurement rather than an argument. Given how many thresholds divide by this
number, switching to it on the strength of the reasoning alone would be exactly
the mistake this repository keeps writing down.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .state import Restorable

#: `a + b`. The persistence of a shock, and the one number that separates this
#: from an exponentially weighted mean, which sits at exactly 1.
#:
#: 0.995 leaves a half-life of about 140 bars on the pull toward the long-run
#: scale - slow enough that an hour of quiet does not drag a genuinely volatile
#: instrument back down, fast enough that a day-old spike is gone. Published
#: GARCH fits on daily equity and FX data land between 0.97 and 0.99; this sits
#: deliberately above them because the series here are intraday, where
#: persistence measured in bars is higher for the same persistence in time.
PERSISTENCE = 0.995

#: Half-life in bars for the long-run scale itself. Long, because it is the
#: anchor: if it moved at the speed of the estimate it would follow it, and
#: there would be nothing to revert to.
LONG_HALF_LIFE = 2_000.0

#: Bars before the estimate means anything. Higher than `volatility.WARMUP`
#: because the long-run scale needs history before it is an anchor rather than
#: a restatement of the last few bars.
WARMUP = 60


def _alpha(half_life: float) -> float:
    return 1.0 - math.exp(math.log(0.5) / max(half_life, 1.0))


@dataclass(slots=True)
class Garch(Restorable):
    """Conditional scale of returns in basis points, with mean reversion."""

    #: Half-life in bars of the reaction to a new move. Matched to
    #: `volatility.HALF_LIFE` so this differs from the existing estimator in
    #: exactly one respect.
    half_life: float = 60.0
    persistence: float = PERSISTENCE
    long_half_life: float = LONG_HALF_LIFE
    floor_bps: float = 0.05
    warmup: int = WARMUP

    _scale: float = 0.0
    _long: float = 0.0
    _last: float = 0.0
    _seen: int = 0

    @property
    def a(self) -> float:
        """Weight on the newest move. Never more than the total persistence."""
        return min(_alpha(self.half_life), self.persistence)

    @property
    def b(self) -> float:
        """Weight on the previous estimate."""
        return self.persistence - self.a

    def update(self, price: float) -> float:
        """Take one price, return the current scale estimate in bps."""
        if price <= 0:
            return self.bps
        if not self._last:
            self._last = price
            return self.bps

        move = abs(price - self._last) / self._last * 10_000
        self._last = price
        self._seen += 1

        # The anchor first, so a brand-new series has something to revert to
        # rather than reverting to zero on its second observation.
        slow = _alpha(self.long_half_life)
        self._long = move if self._seen == 1 else self._long + slow * (move - self._long)

        if self._seen == 1:
            self._scale = move
            return self.bps

        # w is not stored: it is defined by the target, so a change to the
        # long-run scale takes effect immediately rather than after however
        # long it takes a stored constant to be re-derived.
        omega = (1.0 - self.persistence) * self._long
        self._scale = omega + self.a * move + self.b * self._scale
        return self.bps

    @property
    def bps(self) -> float:
        return max(self._scale, self.floor_bps)

    @property
    def long_run_bps(self) -> float:
        """Where the estimate is being pulled. Zero until it has seen a move."""
        return self._long

    @property
    def warm(self) -> bool:
        return self._seen >= self.warmup

    @property
    def stretch(self) -> float:
        """Current scale over its long-run level. 1.0 when there is no view.

        Above 1 the instrument is more volatile than it usually is and the
        model expects that to fade; below 1, quieter than usual. It is the part
        an exponentially weighted mean cannot express at all, because it has no
        usual.
        """
        if self._long <= 0 or not self.warm:
            return 1.0
        return self.bps / self._long
