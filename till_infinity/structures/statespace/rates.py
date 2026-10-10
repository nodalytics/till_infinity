"""A rate is per unit time, and a bar is not a unit of time. Improvement I6.

Every coefficient in `A` carries units of inverse time - that is why the
state-space form is written `A(t)` and not `A(k)`. The level filter already
honours this: `slope` is price per *hour* and `predict` works in elapsed hours,
so a level untouched across a weekend and one untouched for an hour are handled
by the same arithmetic rather than by the same number of missing bars.

**The regression slope published beside it does not.** `Engine._slope` regresses
close against the bar **index**:

    rise = sum((i - middle) * x for i, x in enumerate(window))
    # Price per bar -> basis points per bar -> volatility units per bar.

`zma`'s does the same. Index and time agree only when bars arrive uniformly, and
on this desk they do not:

* sessions close, so one index step can be a minute or three days;
* venues drop out - `wrote 299 bars and announced 8` is in the logs often enough
  to be routine rather than exotic;
* the synthetics run continuously and the real instruments do not, so a per-bar
  rate is not comparable between them even at the same interval.

A per-bar rate silently changes meaning across every one of those, and nothing
in the name says so. `slope` and `level_slope_vol` sit in the same decision
context today with one per bar and one per hour.

## What this returns that the incumbent does not

The slope's **own variance**, which is the estimator's standard error and not the
same thing as the process variance `var_slope` the Kalman carries. The
distinction matters and I10 is about the other one:

* `Slope.variance` here says *how well this window pins the slope down* - it
  falls as the window lengthens and as the fit tightens.
* `Kalman.var_slope` says *how fast the true slope is believed to wander*, which
  is a property of the world and is currently set by `DRIFT_VOL_PER_HOUR = 0.02`,
  a number chosen rather than measured.

Reporting the first does not measure the second. It does make the comparison
possible, because an estimator that disagrees with the filter by more than its
own standard error is evidence about the filter's `q`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

#: Points before a slope is reported at all. Two define a line with no residual
#: and therefore no standard error, which would publish a certainty the data
#: cannot support.
MIN_POINTS = 3

#: Seconds in the hour every rate here is expressed per.
HOUR = 3_600.0


@dataclass(frozen=True, slots=True)
class Slope:
    """A rate in value units per hour, with what the fit knows about it."""

    #: Value units per hour. The quantity `A`'s off-diagonal actually wants.
    per_hour: float
    #: The ordinary-least-squares variance of `per_hour`, in (units/hour)^2.
    #: Zero when the fit is exact, which happens and is not a certainty.
    variance: float
    #: Hours from the first point to the last. The denominator of everything
    #: above, and the number an index-based fit throws away.
    hours: float
    #: Points used.
    n: int
    #: Value units per *bar*, for the incumbent's convention - so the two can be
    #: compared on the same window rather than argued about.
    per_bar: float

    @property
    def sd(self) -> float:
        return math.sqrt(max(self.variance, 0.0))

    @property
    def confident(self) -> bool:
        """True when the slope is more than two of its own standard errors from zero.

        A level with one touch has a slope because the arithmetic produces one,
        not because anything said so. This is the question `earned_slope` asks of
        the filter, asked of the regression.
        """
        return self.variance > 0 and abs(self.per_hour) > 2.0 * self.sd


def slope_per_hour(
    times: Sequence[float], values: Sequence[float], *, min_points: int = MIN_POINTS
) -> Slope | None:
    """Least squares of `values` on `times`, as a rate per hour. None if it cannot.

    `times` are unix seconds, in any order and with any spacing - the whole point
    is that the spacing is read rather than assumed. Duplicated timestamps are
    allowed; a window where *every* timestamp is the same has no time span to
    regress against and returns None rather than infinity.
    """
    n = min(len(times), len(values))
    if n < max(min_points, 2):
        return None
    xs = [float(times[i]) / HOUR for i in range(n)]
    ys = [float(values[i]) for i in range(n)]
    if not all(math.isfinite(v) for v in (*xs, *ys)):
        return None

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0.0:
        # Every point at one instant. A rate is not defined here, and the
        # index-based form would happily return one.
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    per_hour = sxy / sxx

    # The estimator's own variance: residual variance over the spread of x. With
    # n == 2 the residual is identically zero, which is why `MIN_POINTS` is 3.
    intercept = mean_y - per_hour * mean_x
    rss = sum((y - (intercept + per_hour * x)) ** 2 for x, y in zip(xs, ys, strict=True))
    variance = (rss / (n - 2)) / sxx if n > 2 else 0.0

    span = max(xs) - min(xs)
    # The incumbent's quantity on the same window, so "does time matter here"
    # has an answer per call rather than per argument. Equal spacing makes the
    # two differ by exactly the bar length in hours.
    per_bar = per_hour * (span / (n - 1)) if n > 1 else 0.0

    return Slope(
        per_hour=per_hour,
        variance=max(variance, 0.0),
        hours=span,
        n=n,
        per_bar=per_bar,
    )


def slope_per_bar(values: Sequence[float]) -> float:
    """The incumbent's slope: least squares against the bar **index**.

    Here so the comparison in `slope_per_hour` is against the real thing rather
    than a description of it. This is `Engine._slope`'s `fit`, without the
    volatility scaling, and it is wrong for the reason the module docstring
    gives - kept because a null has to be the code that is shipping.
    """
    n = len(values)
    if n < 2:
        return 0.0
    middle = (n - 1) / 2
    spread = sum((i - middle) ** 2 for i in range(n))
    if not spread:
        return 0.0
    rise = sum((i - middle) * float(x) for i, x in enumerate(values))
    return rise / spread
