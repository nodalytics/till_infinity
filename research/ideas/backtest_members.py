"""The members on real markets: calibration, sharpness, and a P&L arm.

Asked on 2026-10-12: test and backtest the state-space members against real
markets.

Two things already exist and are not repeated. `research/harness/statespace_fx.py`
ran the **directional** question - a Kalman AR(1) drift, 13 of 96 cells past
Benjamini-Hochberg at AUC 0.510 to 0.523 against walks at 0.49 to 0.51, found
on EURUSD so EURUSD cannot confirm it. And `statespace-measured.md` has a
coverage table, on **one cell**, with `linear` at 68.6% against a nominal 95%.

## Why the coverage table needs redoing

That 68.6% is not a verdict on `linear`; it is a verdict on `linear` with its
`jerk` left at the default. `statespace-clock-levers.md` has just measured
that a fitted jerk lands at **1e-10 to 1e-6 times** the dimensionally natural
value, so a default of `1e-6` is orders of magnitude too large - which makes
the state wander far more than the series does, which makes the band far too
narrow relative to the residual, which is exactly what 68.6% coverage with
`+0.32` residual autocorrelation looks like.

So every member here gets its process noise **fitted on the first half** of
each series by a sweep over fourteen decades, and everything is scored on the
second half. A calibration number from an unfitted member measures the
default, not the model.

## Four readings, in the order they decide things

* **coverage** at one and two sigma against the nominal 68.3% and 95.4%. This
  is the claim the desk would actually use, because a stop is a band.
* **sharpness** - the median band width in volatility units - read **only**
  for members whose coverage is honest. A tight band that does not cover is
  not sharp, it is wrong, and ranking on width alone rewards exactly that.
* **whiteness** - the lag-1 autocorrelation of the standardised residual.
  Scale-free, so comparable across members whose units differ, and it is the
  diagnostic that says whether the state equation is wrong rather than merely
  imprecise.
* **a P&L arm**, because the ask was a backtest. The member's own rate as the
  signal, entry on the next bar, cost in spread units, against **random
  entries at the same rate and the same holding time** - which is the control
  that matters, since any rule that trades more in volatile stretches looks
  different from a constant-rate one for reasons that are not signal.

## The prior, which is unkind and specific

Direction is close to unforecastable here: at most 6 of 45 bin pairs were
orderable in `statespace-informatory-pairs.md`, the up/down edge died at -98%
with good fills, and a plain level walk beats `kalman` and `reverting` by
about forty thousand nats. A P&L arm is run because it was asked for and
because the number is worth having written down, not because it is expected
to clear cost.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from pathlib import Path

from till_infinity.structures.statespace.linear import Gaussian
from till_infinity.structures.statespace.nulls import Walk
from till_infinity.structures.statespace.reverting import Reverting
from till_infinity.structures.statespace.switching import Switching

HOUR = 3600.0

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD", "SPX500")
GENERATED = ("Volatility_75_Index", "Step_Index", "Boom_500_Index")
FRAMES = tuple(os.environ.get("FRAMES", "1h,4h").split(","))

#: The sweep for each member's process noise, as multiples of a dimensionally
#: natural base. Fourteen decades, because `jerk` needs them.
GRID = tuple(10.0**k for k in range(-12, 3, 2))

#: Nominal coverage of the one- and two-sigma bands for a Gaussian.
NOMINAL = {1.0: 0.6827, 2.0: 0.9545}

#: Holding time for the P&L arm, in hours, and the round-trip cost in spreads.
HOLD_HOURS = 24
COST_SPREADS = 1.5

SINCE = float(os.environ.get("SINCE", "1420070400"))
LIMIT = int(os.environ.get("LIMIT", "30000"))
SEED = 20261012
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str):
    import numpy as np

    for path in (CACHE / f"{name}.{frame}.npz", Path(f"data/seqlab/{name}.{frame}.npz")):
        if not path.exists():
            continue
        with np.load(path) as bundle:
            if not {"time", "close"} <= set(bundle.keys()):
                continue
            order = np.argsort(bundle["time"])
            times = bundle["time"][order].tolist()
            closes = bundle["close"][order].tolist()
        first = 0
        while first < len(times) and times[first] < SINCE:
            first += 1
        times, closes = times[first:], closes[first:]
        if len(times) > LIMIT:
            times, closes = times[-LIMIT:], closes[-LIMIT:]
        return (times, closes) if len(times) > 5000 else None
    return None


#: name, builder taking the noise, the lever's name, and the natural base from
#: a one-step spread `s` over `dt` hours. The exponent is the integration
#: order: a level's variance grows like `q dt`, a reverting rate's
#: contribution like `q dt^3`, an integrated jerk's like `q dt^5`.
MEMBERS = (
    ("walk", lambda q: Walk(noise=math.sqrt(q)), "noise", lambda s, dt: s * s / dt),
    ("kalman", lambda q: Gaussian(jerk=q), "jerk", lambda s, dt: s * s / dt**5),
    ("reverting", lambda q: Reverting(sigma2=q), "sigma2", lambda s, dt: s * s / dt**3),
    (
        "switching",
        lambda q: Switching(balance_wander=q, imbalance_wander=q * 100.0),
        "balance_wander",
        lambda s, dt: s * s / dt,
    ),
)
