"""Is speed more persistent than signed velocity? The split, measured.

The IBM note says velocity can be split into speed and direction but calls the
split **inefficient** - the minimal-state principle, which wants the smallest
set of linearly independent variables.

That principle assumes every component of the state is equally learnable. On
this desk they demonstrably are not: everything that has survived a control
predicts *how much* price moves and never *which way*. So if |v| is persistent
and sign(v) is a coin, carrying them as one signed number forces one filter onto
a quantity whose two halves have opposite predictability.

That is a measurement, not an opinion. Autocorrelation of the signed rate
against the autocorrelation of its magnitude, on the same series.

## What it said, 2026-10-10, eurusd 4h, 999 returns

    component            lag1   sum of first 5
    signed velocity     -0.00          -0.047
    speed |v|           +0.16          +0.381
    log speed           +0.06          +0.148
    direction sign(v)   -0.01          -0.100

**Speed is 8.1x as persistent as the signed rate, and direction is a coin** -
consecutive signs agree 49.499% of the time against 50% +/- 3.102% at 95%, which
is indistinguishable from chance on 998 pairs.

So the split is not inefficient here, it is the whole point. A filter given
signed velocity as a state is tracking a quantity with **no autocorrelation at
all** while discarding a magnitude that has +0.38.

**And it explains a result that looked like a property of the market.**
`reverting.py` fitted `theta = 0.5` per hour on this series, a 1.39-hour
half-life, meaning a level's drift decays 86% across one 4h bar. That is not the
market being memoryless: it is the filter correctly concluding that *the state
variable it was handed* does not persist. Hand it `log speed` and the same
machinery should find something far more persistent.

## What this implies, and what it does not

The implied state is `(position, log speed)` plus a **separate** direction
process - continuous magnitude, discrete direction, which is a switching
state-space model. That is the spec's I9 ("two state spaces - and there already
are two") and it is what the HMM member in `family.PENDING` would be for.

**What it does not establish**: this is measured on bar-to-bar price returns, not
on a *level's* rate. A level's rate is estimated from touches, which is a sparser
and differently-biased series. So this is strong evidence about the right shape
and not yet a measurement of the thing the filter tracks.

Repeating it on touches is available rather than blocked: `entry` on the episode
record is the touch price, at eight decimal places, 250,412 of them since
2026-10-02. This docstring used to call that a missing field - the *resolutions*
write is the one that lacks it.
"""
from __future__ import annotations

import csv
import math
import sys

import numpy as np

HOUR = 3600.0


def load(path, venue="FOREXCOM"):
    rows = []
    with open(path) as fh:
        for row in csv.DictReader(fh):
            if row["venue"] == venue and row["close"]:
                rows.append((int(row["ts"]), float(row["close"])))
    rows.sort()
    return [t for t, _ in rows], [c for _, c in rows]


def acf(x, lags):
    x = np.asarray(x, float)
    x = x - x.mean()
    n, var = len(x), float(np.mean(x * x))
    return [float(np.sum(x[k:] * x[:-k]) / (var * n)) for k in range(1, lags + 1)]


times, closes = load(sys.argv[1])
ret = np.diff(np.log(closes)) * 1e4          # the "velocity" per bar, in bps
speed = np.abs(ret)                           # magnitude
direction = np.sign(ret)                      # the other half
print(f"{len(ret)} eurusd 4h returns\n")

lags = 10
rows = [
    ("signed velocity", acf(ret, lags)),
    ("speed  |v|", acf(speed, lags)),
    ("log speed", acf(np.log(speed + 1e-9), lags)),
    ("direction sign(v)", acf(direction, lags)),
]
head = "component".ljust(19) + "".join(f"  lag{k}" for k in range(1, lags + 1))
print(head)
print("-" * len(head))
for label, a in rows:
    print(label.ljust(19) + "".join(f"{v:+6.2f}" for v in a))

print("\nsum of the first 5 autocorrelations (persistence, crudely):")
for label, a in rows:
    print(f"  {label:<19} {sum(a[:5]):+.3f}")

# The decisive pair: does |v| carry structure the signed version hides?
sv, sp = acf(ret, 5), acf(speed, 5)
print(f"\nsigned velocity, |sum| of first 5 : {abs(sum(sv)):.3f}")
print(f"speed,           |sum| of first 5 : {abs(sum(sp)):.3f}")
ratio = abs(sum(sp)) / max(abs(sum(sv)), 1e-9)
print(f"speed is {ratio:.1f}x as persistent as the signed rate")

# And is direction predictable at all? A sign-agreement rate against 50%.
agree = float(np.mean(direction[1:] == direction[:-1]))
n = len(direction) - 1
se = math.sqrt(0.25 / n)
print(f"\nconsecutive signs agree {agree:.3%} of the time")
print(f"  against 50% +/- {1.96*se:.3%} (95%), n={n}")
print(f"  {'predictable' if abs(agree-0.5) > 1.96*se else 'INDISTINGUISHABLE FROM A COIN'}")
