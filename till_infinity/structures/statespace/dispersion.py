"""Do these units differ at all, once their own counting noise is removed?

The one gap in this package that a night of measuring actually proved. Asked on
2026-10-14 for statespace versions of nine production modules, five of which
turned out to have counterparts here already - `zma` and `cycles` against
`oscillator`, `spectrum` and `switching`; `spreadquotes` against `relating`;
`features` against `inputs`; `models` against `subjects` and `facts`.
`rollover` is data hygiene rather than modelling, and `reactions` computes a
direction this desk has measured closed twice.

`shrinkage.tau_squared` was the exception, and the proof is in
`research/ideas/conditional_holds.py`: it had to import it **from a sibling
module**, which this package forbids itself and asserts in a test. A harness may
reach across; the library may not, and the thing it was reaching for is the
question below.

## The question, and why a spread is not an answer to it

Twenty levels show hold rates from 0.3 to 0.7. Do those levels **differ**, or
were they each counted a dozen times? A sample rate carries its own binomial
noise, so the observed spread is the real spread **plus** that noise, and the
whole content of the question is in the subtraction.

DerSimonian and Laird's method of moments does it: weight each unit by its
precision, form the weighted spread about the pooled mean, and subtract the
degrees of freedom that sampling alone would have produced. What is left is
`tau_squared`, the between-unit variance of the **true** rates. Zero means every
unit is the same and its record is noise.

## It earns its place by having closed a question

`statespace-conditional-holds.md` used it on 279 levels: `tau` came back at
**0.0109** on traded instruments - a between-level standard deviation of one
percentage point on a pooled rate of 0.493 - and at **0.0000** on
distance-matched placebo prices. Reading that 0.0109 took an eye until `differ`
existed: 279 units counted as often as those were produce **0.0085** from
sampling alone, so the traded figure was never outside its own noise either.
That arm is a null, not a small effect, and the difference matters - a small
effect invites a bigger sample, a null does not. On the generated feeds, whose processes have no
levels at all, a placebo showed **more** dispersion than a real level, 0.0408
against 0.0227.

That closed `levels.sym_hold_rate`, a field production had been accumulating
since `engine.py:2759` and nothing had ever read, in one arm - and it closed it
*before* any estimator was tried, which is the property worth having. Prediction
can fail for many reasons; `tau` near zero says there was never anything to
predict from.

**So this is the first thing to reach for when a per-unit statistic is
proposed**, not the last. It is cheap, it needs no held-out split, and a zero
means no estimator was ever going to work.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: Observations a unit needs to contribute a rate. One observation is a rate of
#: 0 or 1 with no information about its own precision, and a pool of those
#: produces a spread that is all sampling noise.
LEAST = 2.0

#: Units a pool needs before it is asked anything. Below this the estimate is
#: dominated by whichever two units happened to be included.
UNITS = 12


def tau_squared(samples: Sequence[tuple[float, float]], mean: float) -> tuple[float, int]:
    """Between-unit variance of the **true** rates, and how many units said so.

    `samples` is `(observations, hits)` per unit; `mean` is the pooled rate.
    Returns `(tau_squared, units used)`.

    DerSimonian and Laird. The observed spread already contains each unit's own
    sampling noise, so subtracting it is not a refinement - it is the entire
    question, and it is what separates "these differ" from "these were counted
    few times".
    """
    within = float(mean) * (1.0 - float(mean))
    if within <= 0.0:
        return 0.0, 0
    usable = [(float(n), float(hits)) for n, hits in samples if float(n) >= LEAST]
    if len(usable) < 2:
        return 0.0, len(usable)
    weights = [n / within for n, _ in usable]
    q = sum(w * (hits / n - float(mean)) ** 2 for w, (n, hits) in zip(weights, usable, strict=True))
    total = sum(weights)
    spread = sum(w * w for w in weights)
    divisor = total - (spread / total if total else 0.0)
    if divisor <= 0.0:
        return 0.0, len(usable)
    return max(0.0, (q - (len(usable) - 1)) / divisor), len(usable)


def tau(samples: Sequence[tuple[float, float]], mean: float) -> float:
    """`sqrt(tau_squared)`: the between-unit spread in the rate's own units.

    Reported in preference to the variance because it is directly comparable
    with the pooled rate - a `tau` of 0.01 against a mean of 0.49 says the units
    differ by one percentage point, which is a sentence a reader can check.
    """
    got, _ = tau_squared(samples, mean)
    return math.sqrt(got)


def differ(
    samples: Sequence[tuple[float, float]],
    mean: float,
    draws: int = 400,
    seed: int = 0,
) -> tuple[float, float, float]:
    """`(tau, null tau, p)`: observed spread against the spread of no spread.

    **The gate to apply before fitting anything per unit**, and it has to be a
    null rather than a threshold. A first version of this took a constant -
    `tau > 0.02` - and called sixty identical units different, because at forty
    observations each their sampling noise alone produces a `tau` of **0.029**.
    The floor is not a number, it is a function of how many units there are and
    how often each was counted, so the only honest version simulates it.

    Every unit is redrawn at the pooled rate with its own count, `tau` is
    recomputed, and `p` is the share of those draws reaching the observed value.
    A large `p` means the spread is what identical units would have produced.
    """
    import random

    got, used = tau_squared(samples, mean)
    observed = math.sqrt(got)
    if used < UNITS:
        return observed, float("nan"), float("nan")
    counts = [float(n) for n, _ in samples if float(n) >= LEAST]
    rng = random.Random(seed)
    over = 0
    nulls = []
    for _ in range(draws):
        drawn = [
            (n, float(sum(1 for _ in range(int(n)) if rng.random() < float(mean)))) for n in counts
        ]
        null, _used = tau_squared(drawn, mean)
        nulls.append(math.sqrt(null))
        over += math.sqrt(null) >= observed
    nulls.sort()
    return observed, nulls[len(nulls) // 2], (over + 1) / (draws + 1)


def borrow_weight(
    samples: Sequence[tuple[float, float]], mean: float, fallback: float = 4.0
) -> float:
    """How many pseudo-observations a unit's neighbours are worth to it.

    The shrinkage weight `K` in `own / (own + K)`, from the same decomposition:
    if the units barely differ, borrowed evidence is worth a great deal and `K`
    is large; if they differ a lot, a unit's own record should dominate and `K`
    is small. `fallback` is returned when the pool cannot say.

    Clamped, because both limits are degenerate: at zero a unit with one
    observation overrides the pool, and unbounded means a unit never gets to
    speak at all.
    """
    got, used = tau_squared(samples, mean)
    if used < UNITS or got <= 0.0:
        return float(fallback)
    within = float(mean) * (1.0 - float(mean))
    if within <= 0.0:
        return float(fallback)
    return min(max(within / got, 0.5), 50.0)
