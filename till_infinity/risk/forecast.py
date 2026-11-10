"""The volatility forecast a stop and a target should be set from.

Three measured facts, and this module is their composition.

**1. A decaying average of true range is the best forecast this desk has.**
`profile.py` records it against 11,797 recorded calls: `ewma_tr_bps` beat
`vol_bps`, `garch_bps`, `ensemble_bps`, `forecast_bps` and `range_bps` **in
every cell**, and beat GARCH at one bar ahead scored against return variance -
GARCH's own quantity. `drive-q-from-the-range` says why a range estimator wins
at all: the range-vs-close estimator ratio is **0.648 within strata on FX** and
0.667 on 371 of 392 equities, and the advantage *grows as the window shortens*.

**2. A Gaussian band is miscalibrated at one bar and a Student-t fixes it.**
`risk/quantiles.student_stop` is that band - the `tau` quantile of `|Student-t|`
at unit variance - and `no-gaussian-band-is-calibrated` records it holding on
**64 of 64 out of sample** at dof 3 to 5. The same note records the two-sided
quantile putting the baseline at 1.08 units where it belongs at **1.51**, which
is the mistake this module must not repeat: it calls `student_stop` rather than
computing a quantile of its own.

**3. The measured band is the ONE-BAR band, and that bound is load-bearing.**
`no-gaussian-band-is-calibrated` is explicit: *only* the one-bar band was
miscalibrated and the Student-t fixed it, 64 of 64 out of sample. Scaling it
over a hold by `sqrt(n)` is an **extrapolation nobody here has measured**, and
the numbers say why that matters rather than being a quibble: on a steady
20-pip 15m bar the one-bar band is **30 pips**, which sits just under a rule's
own 3.0-unit stop of 60 and so binds only on a stop that is genuinely too
tight. The same band over `smc-bos-causal`'s 96-bar hold is **295 pips** - five
times the rule's own stop - so a floor built on it would not be a floor, it
would be a silent rewrite of every stop on the desk.

So `bars` defaults to 1 and a caller asking for more is asking for something
unmeasured. It is a parameter rather than a constant because the extrapolation
is the obvious next measurement, not because it is ready.

A further reason to distrust the `sqrt(n)` form here: a stop is a **barrier**,
not a terminal distribution. The quantile of a running maximum over `n` bars is
larger than the quantile of the terminal value, so `sqrt(n)` understates the
excursion a hold actually sees - which is the safe direction for a floor and
the wrong direction for anyone reading it as a coverage claim.

## What this is not

Not a direction forecast. `direction-is-closed-not-just-null` records the gate
finding a planted drift at z+2.90 and earning 2% of a spread, so nothing here
claims to know which way price goes - only how far it is likely to travel.

Not a replacement for a rule's own stop either, at least not by default. Each
rule's stop distance is part of what was measured about it, and
`reproduce-the-baseline-before-an-increment` is the standing warning about
swapping a model under a result: HAR read **+0.036 against the shelf's +0.110**
and the cause was the data window, not the model. So `band` is offered as a
**floor** - it widens a stop that is tighter than the forecast says it should
be, and leaves a wider one alone - and the comparison that would license
replacing a rule's stop outright has not been run.
"""

from __future__ import annotations

import math

from .quantiles import DOF, TAU, student_stop

#: Decay for the true-range average. 2/(n+1) for n=14, matching the ATR period
#: every rule here already uses, so the forecast and the rules' own `*_atr`
#: features are comparable rather than two different windows.
ALPHA = 2.0 / 15.0

#: Bars before the average is worth reading. Below it the decay has not seen
#: enough range to be an average of anything, and a stop set from two bars is
#: a stop set from two bars.
WARM = 14


class RangeForecast:
    """A decaying average of true range, in price units.

    Price units and not basis points, because a stop is a distance and the
    conversion to bps and back is two places to lose a factor. A caller wanting
    bps divides by the close itself.

    **True range and not the bar's own high-low.** A gap between bars is
    movement the position lives through, and a high-low that ignores the
    previous close reports a quiet bar on a day that opened 2% away.
    """

    __slots__ = ("_bars", "_previous", "value")

    def __init__(self) -> None:
        self.value = 0.0
        self._bars = 0
        self._previous: float | None = None

    @property
    def ready(self) -> bool:
        return self._bars >= WARM and self.value > 0.0

    def update(self, high: float, low: float, close: float) -> float:
        """Fold one closed bar. Returns the current forecast."""
        span = high - low
        if self._previous is not None:
            # True range: the widest of the bar and either gap.
            span = max(span, abs(high - self._previous), abs(low - self._previous))
        self._previous = close
        self._bars += 1
        if span <= 0.0:
            return self.value
        # Seeded with the first range rather than from zero, so the average is
        # not biased low for its whole warm-up by a start nobody chose.
        self.value = span if self.value <= 0.0 else self.value + ALPHA * (span - self.value)
        return self.value

    def reset(self) -> None:
        self.value = 0.0
        self._bars = 0
        self._previous = None


def band(forecast: float, bars: float = 1.0, *, tau: float = TAU, dof: float = DOF) -> float:
    """How far price is likely to travel against a trade over `bars` bars.

    The one-bar Student-t band times `sqrt(bars)`. Zero for a forecast that is
    not positive, which a caller must read as "no opinion" rather than as a
    stop at no distance - a band of zero would be a stop on the entry.

    `bars` below one is clamped to one: a hold shorter than a bar still lives
    through that bar, and `sqrt` of a fraction would report a band tighter than
    the bar it is measured in.

    **`bars` above one is unmeasured.** The calibration result is a one-bar
    result; see the module docstring for the 30-against-295-pip arithmetic that
    makes the difference a decision rather than a detail.
    """
    if forecast <= 0.0:
        return 0.0
    return forecast * student_stop(tau, dof) * math.sqrt(max(1.0, bars))


def floored(distance: float, forecast: float, bars: float = 1.0, **limits: float) -> float:
    """`distance`, widened to the forecast band where it is tighter than one.

    **A floor and not a replacement**, for the reason the module docstring
    gives: a rule's stop distance is part of what was measured about that rule,
    and a band that only ever widens cannot make a measured stop tighter than
    it was tested at. With no usable forecast the distance is returned
    unchanged, so an unwarmed desk behaves exactly as it did before.
    """
    wanted = band(forecast, bars, **limits)
    return max(distance, wanted) if wanted > 0.0 else distance


__all__ = ["ALPHA", "WARM", "RangeForecast", "band", "floored"]
