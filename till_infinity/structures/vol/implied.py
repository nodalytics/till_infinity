"""The options market's own volatility forecast, as a member of the ensemble.

## Why this is a member and not a knob

[research/implied.md](../../../research/implied.md) is the only positive result
in this project's research folder. Over 15 years, walk-forward with the fit
redone at every step, VIX beats a trailing realised estimate by **12 to 20
points of R-squared**, and beats the naive baseline - which has beaten GARCH,
HAR, the pooled tree and the factorisation machine - by **+0.26 to +0.43**.

Its sharpest finding decides the shape of this file: **`both` is not better than
`vix` alone.** The historical estimate adds nothing once VIX is present. That is
not "VIX helps", it is "VIX replaces", and a sizing multiplier bolted on the
side would not use that finding.

So it joins `consensus_vol.Ensemble`, which already converts members to one
convention, scores each against **what the next bar actually did**, and can
weight by that score. A scaler that is wrong sits there being wrong; a scored
member that is wrong loses its vote, and `Ensemble.standings()` says so without
anyone intervening.

## One series, four feeds

`implied.md` measured the matched indices and found them unnecessary: `own -
vix` is **+0.0014** for us100 at one day and **-0.0080** for us30, where plain
VIX is *better* than VXD. One feed to keep alive rather than four, and on us30
the matched series would have been worse.

## `1d` and `1w`, and why the scope is narrow on purpose

VIX is a **30-day** forward view published **daily**. Scaling it to a 1m bar by
root-time assumes a flat term structure and no intraday seasonality, and the
intraday U-shape is large and real. The other four members read actual bars and
have no such problem.

At `1d` the conversion is a division by `sqrt(252)` with no intraday assumption
at all. That is the reason for the scope rather than a consequence of it, and
`implied.md`'s own scope line agrees: *"the equity indices at a day and up"*.

**What this improves is the estimate daily and weekly levels and origins are
drawn from** - not the 1m-30m entries the desk fires on.

## 2026-09-11: measured before shipping, and it loses

`research/harness/vixseed.py` replayed every member over 20 years of daily and
weekly bars on all four indices, scoring each exactly as the live path does.
Accuracy is 1 - decayed relative error:

| feed | interval | best | `vix` |
| --- | --- | --- | --- |
| spx500 | 1d | har 0.816 | **0.635, last of five** |
| spx500 | 1w | har 0.811 | **0.708, last** |
| us100 | 1d | har 0.827 | 0.761, second |
| us100 | 1w | har 0.823 | 0.800, second |
| us2000 | 1d | har 0.802 | 0.735, second |
| us2000 | 1w | har 0.815 | 0.808, second |
| us30 | 1d | har 0.831 | **0.666, last** |
| us30 | 1w | har 0.813 | **0.693, last** |

**`har` wins everywhere and `vix` is last on half the series.** So the member is
built, tested and **off**: seeding it would start a member with a weight it has
not earned, and turning `weighted` on was justified by the claim that VIX should
dominate, which this refutes.

### Why this does not contradict `implied.md`

It measures a different quantity. `implied.md` regressed forward realised
volatility on VIX **walk-forward, refitting the coefficient at every step**, and
reported R-squared. This scores a **raw point forecast** with no coefficient at
all.

VIX systematically exceeds realised volatility - the variance risk premium - so
it is highly *informative* and badly *biased* as a point estimate. A regression
removes the bias and keeps the information; an ensemble of point forecasts keeps
both. Being second on us100 and us2000 while last on spx500 and us30 is exactly
what a premium that differs by index looks like.

### What would make it work

Fit the scale. A member that reports `a + b * vix`, with `a` and `b` estimated
online against realised volatility, would carry the information `implied.md`
measured without the bias this found. That is a different member from this one -
it has parameters, it needs its own warm-up, and it can overfit - so it is a
separate piece of work rather than a tweak, and this file is the evidence that
it is the piece of work actually required.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from ..state import Restorable

#: **Off, because it was measured and it loses.** See the note below.
ENABLED = os.environ.get("STRUCTURES_IMPLIED", "0") not in ("0", "false", "no")

#: The equity indices `implied.md` measured, keyed to this book's feed names.
IMPLIED_FEEDS: frozenset[str] = frozenset({"spx500", "us100", "us30", "us2000"})

#: Where VIX's own horizon roughly matches the bar. See the module note.
IMPLIED_INTERVALS: tuple[str, ...] = ("1d", "1w")

#: Trading days in a year and in a week. VIX is quoted as an annualised
#: percentage against the first.
YEAR_DAYS = 252.0
INTERVAL_DAYS: dict[str, float] = {"1d": 1.0, "1w": 5.0}

#: A reading older than this does not vote. If the feed dies, the last value
#: otherwise keeps voting with full confidence on every subsequent bar - which
#: is the failure mode that matters here, because a daily series looks alive
#: for a long time after it stops.
MAX_AGE = 3 * 86_400.0


def bps_for(vix: float, interval: str) -> float | None:
    """A VIX quote as this bar's standard deviation, in basis points.

    VIX 20 means 20% annualised sigma, so one trading day is `20 / sqrt(252)`
    percent - 125.99 bps - and a week is that times `sqrt(5)`.

    Returns a **sigma**. The ensemble is on the mean-absolute convention and
    converts anything named in its `sigma_scaled` set, so this must not do that
    conversion itself or it would be applied twice.
    """
    days = INTERVAL_DAYS.get(interval)
    if days is None or vix <= 0:
        return None
    return vix / math.sqrt(YEAR_DAYS) * math.sqrt(days) * 100.0


@dataclass(slots=True)
class Implied(Restorable):
    """The last VIX reading, and whether it is fresh enough to vote."""

    max_age: float = MAX_AGE
    level: float = 0.0
    at: float = 0.0

    def observe(self, vix: float, when: float) -> None:
        if vix > 0:
            self.level, self.at = float(vix), float(when)

    def fresh(self, now: float) -> bool:
        return self.level > 0 and (now - self.at) <= self.max_age

    def bps(self, interval: str, now: float) -> float | None:
        """This bar's implied sigma in bps, or None when it must not vote."""
        return bps_for(self.level, interval) if self.fresh(now) else None
