"""An anchored fair value, and the distance from it in band units.

The reference traders reach for here is VWAP: a mean the market is measured
against, with bands either side. It is a null on this desk as published -
`orderflow.md` measured volume-profile POC, HVN, LVN and value-area levels
bouncing like random prices, FX within **1.2 points of the placebo** - and the
reason is mechanical rather than statistical. **MT5 tick volume counts quote
updates, not contracts**, and spot FX has no trade volume at all, so a
volume-weighted mean on these feeds is weighted by something that does not mean
what its name says.

This is the same idea with the weights replaced by the thing the package
already has: each observation enters weighted by its own **precision**, so the
mean is weighted by how well-measured each reading was rather than by a volume
field. And the band around it is `Readout.covering`, whose coverage is
*measured* - breach ratios of 1.02 to 1.10 against a Gaussian band's 1.28 to
14.8 - rather than a plus-or-minus one standard deviation drawn by assumption.

## What it is a fair value *of*

**Log variance, not price.** The service folds `log(garman_klass(...))`, so
this is an anchored fair *volatility* and `stretch` says "dispersion is this
many band units above where it has sat since the anchor". That is a sizing and
gating quantity. It is **not** a price mean-reversion signal, and the naming
here is deliberate so it cannot be read as one: a price-anchored version would
need a second subject fed closes, which is a separate decision because
`DISPERSION` is the topic's whole contract.

## Why anchored at all

`reverting`'s level is already a fair value, but its anchor is a half-life: it
forgets smoothly and has no edges. A session anchor has edges, and the edges
are the point - "high relative to today" is a different claim from "high
relative to the last fortnight", and a consumer deciding whether to trade this
session wants the first. `ANCHOR_HOURS` is 24 by default, in hours rather than
bars for the reason `inputs.py` gives: a bar count is a horizon times a
timeframe, and means something different on every series.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["ANCHOR_HOURS", "Anchor"]

#: Hours between re-anchorings. A day, in hours rather than bars so that one
#: day is one day at 1m and at 1h.
ANCHOR_HOURS = 24.0

#: Smallest observation count before a fair value is offered. Below this the
#: precision-weighted mean is one or two readings and its own spread is wider
#: than the band it would be compared against.
LEAST = 10


@dataclass(slots=True)
class Anchor:
    """A precision-weighted mean since the last anchor, and its own spread.

    The update is the standard one for a Gaussian mean with known measurement
    variance: precision adds, and the mean moves by the new reading's share of
    the total precision. Which makes the weights the inverse of each
    observation's own noise - the honest version of "volume-weighted", where
    the weight is how well the reading was measured.
    """

    #: Hours after which the next reading starts a fresh anchor.
    hours: float = ANCHOR_HOURS

    #: Sum of precisions, the mean itself, and when this anchor began.
    precision: float = 0.0
    mean: float = 0.0
    since: float = 0.0
    seen: int = 0

    @property
    def ready(self) -> bool:
        """Whether the mean is worth publishing. See `LEAST`."""
        return self.seen >= LEAST and self.precision > 0.0

    @property
    def sd(self) -> float:
        """The fair value's own standard deviation, not the observations'."""
        return math.sqrt(1.0 / self.precision) if self.precision > 0 else 0.0

    def observe(self, value: float, noise: float, when: float) -> None:
        """Fold one reading in, re-anchoring first if the window has closed.

        `when` is in seconds, as every timestamp in this package is; `hours`
        is in hours, as every window in this package is.
        """
        if not (math.isfinite(value) and math.isfinite(noise)) or noise <= 0.0:
            return
        if self.seen == 0 or when - self.since >= self.hours * 3600.0:
            self.precision = 0.0
            self.mean = 0.0
            self.seen = 0
            self.since = when
        weight = 1.0 / noise
        total = self.precision + weight
        self.mean += weight * (value - self.mean) / total
        self.precision = total
        self.seen += 1

    def stretch(self, value: float, half: float) -> float:
        """How far `value` sits from fair, in half-band units.

        `half` is half the width of the published band - so 1.0 means the
        reading sits exactly at the band's edge, and the number is comparable
        across feeds because the band's coverage is measured rather than
        assumed. Zero when there is no band yet, which is the honest answer
        rather than an infinity.
        """
        if not self.ready or not half > 0.0 or not math.isfinite(value):
            return 0.0
        return (value - self.mean) / half
