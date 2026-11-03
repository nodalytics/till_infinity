"""The volatility Deriv publishes in the instrument's own name.

## Why a constant beats an estimator here

Three separate studies on 2026-09-11 agreed: **the synthetics have no volatility
clustering at all.** Largest `|acf|` of the absolute 1m return across 26 feeds is
**0.017**, against 0.219 to 0.453 on real controls; variance ratios span
[0.9743, 1.0291] where their own shuffles span [0.9733, 1.0292]; the twelve
Volatility indices measure `H = 0.50`, kurtosis 2.98 to 3.02 and Jarque-Bera p
0.40 to 0.95. They are textbook geometric Brownian motion.

So there is nothing for a rolling estimator to track, and it shows: on these
feeds the estimator's correlation with the next move is **-0.015 to +0.007**,
against 0.366 to 0.493 on real ones. It is not a weak signal, it is noise - and
that noise sets stop distances, target distances and the unit every level on
those instruments is measured in.

Meanwhile the true value is **printed in the name**, and it is right:

| claim | measured |
| --- | --- |
| `volatility_75_index` realises 75% annualised | 12 of 12 within **0.49%**, both halves |
| `jump_25_index` realises 25% | **false** - all five realise **1.32x** the name |

The Jump gap is a convention rather than an error. Five instruments at 1.3128 to
1.3382 across two independent halves is too tight to be measurement, and
`1.322^2 - 1 = 0.75` of the diffusive variance is the right leftover for a jump
of that rate and size: **the name is the diffusive volatility and the jumps are
extra.** See `research/generators.md`.

## The annualisation is 365, not 252

These run 24/7 with no session and no weekend, so the factor is
`sqrt(365*24*60)` exactly rather than an approximation of one. Getting this
wrong by using the trading-day convention would put every reading out by
`sqrt(365/252)` = 1.20 - an error that looks like a result.

## It is a member, not a replacement

It joins `consensus_vol.Ensemble` and is scored against what the next bar
actually did, like every other member. If the published constant really is the
truth it will dominate on these feeds; if the generator changes, or the name
stops meaning what it says, it loses its weight without anyone intervening.
That is the same argument `implied.py` makes, and the reason neither is wired
as a direct substitution.
"""

from __future__ import annotations

import math
import os
import re

#: Off until measured live, like every other new member on this book.
ENABLED = os.environ.get("STRUCTURES_STATED", "0") not in ("0", "false", "no")

#: Minutes in a 365-day year. The synthetics have no session and no weekend, so
#: this is the annualisation factor rather than an approximation of one.
MINUTES_PER_YEAR = 365 * 24 * 60

#: Jump indices realise **1.32x** their name, stably: 1.3267, 1.3128, 1.3382,
#: 1.3194, 1.3159 over 60 days, and the same in each half. The name is the
#: diffusive volatility; the jumps are on top of it.
JUMP_MULTIPLE = 1.322

#: `volatility_75_index`, `volatility_75_1s_index`, `jump_25_index`. Read from
#: the name rather than tabulated, so an index this desk has not seen yet is
#: covered the day it arrives - and `volatility_200_1s_index`, which has no bars
#: in the research store and is the one index nobody has been able to check, is
#: covered without pretending it was measured.
NAMED = re.compile(r"^(volatility|jump)_(\d+)(?:_1s)?_index$")


def nominal(feed: str) -> float:
    """The annualised volatility this instrument's name claims, in percent.

    Zero when the name claims nothing, which is every real instrument on the
    book and the Boom, Crash, Step and Range Break families - those have
    documented *mechanics* but no published volatility, and inventing one for
    them would be the failure this module exists to avoid.
    """
    found = NAMED.match(feed.strip().lower())
    if not found:
        return 0.0
    kind, size = found.group(1), float(found.group(2))
    return size * JUMP_MULTIPLE if kind == "jump" else size


def bps_for(feed: str, seconds: float) -> float | None:
    """This bar's standard deviation in bps, from the name, or None.

    Returns a **sigma**, so the ensemble's `sigma_scaled` set converts it onto
    the mean-absolute convention - and with this book's own measured ratio
    rather than the Gaussian constant, which for these feeds happens to be the
    same thing because they really are Gaussian.
    """
    claimed = nominal(feed)
    if claimed <= 0 or seconds <= 0:
        return None
    minutes = seconds / 60.0
    return claimed / 100.0 * math.sqrt(minutes / MINUTES_PER_YEAR) * 10_000.0
