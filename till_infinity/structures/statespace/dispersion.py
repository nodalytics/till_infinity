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

import itertools
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


#: Observations a unit needs to contribute a **mean**. Three, not `LEAST`'s two:
#: a mean needs its own sample variance to be weighted, and two observations
#: give one degree of freedom, which is a variance with no precision at all.
LEAST_VALUES = 3


def tau_squared_of_means(
    groups: Sequence[Sequence[float]], logs: bool = False
) -> tuple[float, float, int]:
    """`(tau_squared, pooled, units)` for a per-unit **mean** rather than a rate.

    The same decomposition as `tau_squared` with one change, and it is the
    change that makes the function necessary: a rate's sampling variance is
    `p(1-p)/n` and comes from the **pool**, where a mean's is `s_squared/n` and
    comes from the **unit**. Everything after that is identical - inverse
    variance weights, the weighted spread about the pooled mean, and subtract
    the degrees of freedom sampling alone would have produced.

    **`logs` should usually be on for a distance, and `research/docs/
    level-shrinkage.md` is why.** These quantities - a sweep depth, a push, a
    wick - are positive and heavy-tailed, and in raw units a unit's mean is
    carried by its largest one or two observations: on a lognormal with a log-sd
    of 1.5, the single largest of thirty observations holds a median **26.7%**
    of the unit's total, against 3.3% if they contributed evenly. Under `log1p`
    that falls to 11.5%. The practical effect on the study was large - on a feed
    whose breaks run hundreds of in-range bars, the raw arm's out-of-sample MSE
    came back at 577 against 1.79 elsewhere, and the raw test went blind below a
    **20%** between-unit spread where the log-space one resolved **5%**.

    `log1p` is a variance-stabiliser here and not a change of units: it tends to
    `log` only for values well above 1, so a planted multiplicative spread of
    0.25 is recovered as 0.12 at a pooled mean near 1.7 and as 0.21 at a pooled
    mean near 170. Read a log-space `tau` as a lower bound on a proportional
    spread, and read it against its own null either way.

    Because the within-unit variances are **estimated** rather than known, this
    is biased upward: on identical units of thirty observations it returns a
    `tau` near 0.03 where the truth is zero. So the number is not readable on
    its own and `differ_means` is the entry point - what matters is `tau`
    against a null built the same way, not `tau` against zero.
    """
    usable: list[tuple[float, float]] = []
    for values in groups:
        got = [math.log1p(float(v)) for v in values] if logs else [float(v) for v in values]
        if len(got) < LEAST_VALUES:
            continue
        mean = sum(got) / len(got)
        variance = sum((v - mean) ** 2 for v in got) / (len(got) - 1)
        if variance <= 0.0:
            continue
        usable.append((mean, variance / len(got)))
    if len(usable) < 2:
        return 0.0, float("nan"), len(usable)
    weights = sum(1.0 / v for _, v in usable)
    pooled = sum(m / v for m, v in usable) / weights
    q = sum((m - pooled) ** 2 / v for m, v in usable)
    squared = sum((1.0 / v) ** 2 for _, v in usable)
    divisor = weights - squared / weights
    if divisor <= 0.0:
        return 0.0, pooled, len(usable)
    return max(0.0, (q - (len(usable) - 1)) / divisor), pooled, len(usable)


def tau_of_means(groups: Sequence[Sequence[float]], logs: bool = False) -> float:
    """`sqrt` of `tau_squared_of_means`, in the quantity's own units.

    Under `logs` it reads approximately as a proportion, so 0.05 is near a 5%
    spread between units whatever the quantity is measured in - approximately
    because `log1p` compresses values near zero, which makes it an under-
    estimate rather than an over-estimate. The raw ratio `tau / pooled` is
    exactly scale-free and does not stabilise the variance, so the two are
    worth reading together.
    """
    got, _pooled, _units = tau_squared_of_means(groups, logs=logs)
    return math.sqrt(got)


def lag_one(groups: Sequence[Sequence[float]]) -> float:
    """Mean within-unit lag-1 autocorrelation: how long `differ_means` blocks be.

    Each unit's own mean is removed first, so this is dependence *inside* a
    unit and not the between-unit spread the gate is about. It is the number
    that decides `differ_means`'s `block`, and a caller that cannot be bothered
    to look at it should leave `block` at its conservative default.
    """
    got: list[float] = []
    for values in groups:
        kept = [float(v) for v in values]
        if len(kept) < LEAST_VALUES:
            continue
        mean = sum(kept) / len(kept)
        centred = [v - mean for v in kept]
        top = sum(a * b for a, b in itertools.pairwise(centred))
        bottom = sum(v * v for v in centred)
        if bottom > 0.0:
            got.append(top / bottom)
    return sum(got) / len(got) if got else float("nan")


def differ_means(
    groups: Sequence[Sequence[float]],
    draws: int = 400,
    seed: int = 0,
    logs: bool = False,
    block: int = 0,
) -> tuple[float, float, float]:
    """`(tau, null tau, p)` for per-unit means: the gate, in its continuous form.

    `differ` for a rate, and it has the same job - decide whether a per-unit
    statistic is worth fitting before anything is fitted - with a harder null,
    because a continuous observation can be correlated with the one before it
    and a rate's cannot usefully be treated that way.

    **The null deals contiguous blocks, and an i.i.d. shuffle is wrong here.**
    Dealing single observations destroys dependence *within* a unit, which
    lowers the floor without lowering the observed value. Measured on units
    that are identical by construction, with an AR(1) inside each: the i.i.d.
    version rejects at `p <= 0.05` on **100%** of trials at rho of 0.3 and 0.6,
    against 7% at rho of zero. Consecutive touches of a level are correlated,
    so that version reports that every pool of levels differs. The block
    version lays the units end to end and deals each a contiguous run at a
    random circular offset, so a drawn unit carries dependence at the scale a
    real one does; its size came back at 0.00 to 0.07 across the same rho, and
    it still finds a planted 10% spread on 87% of trials and a 20% one on all
    of them.

    **`block` is the length of those runs, and it is a trade-off rather than a
    detail.** It has to exceed the dependence scale or the floor drops back to
    the i.i.d. case, and stay under the unit's own length or the null inherits
    that unit's mean and eats the effect it was meant to price. Swept on 150
    identical units of 30 observations with an AR(1) inside each, reported as
    (size at rho 0.3, size at rho 0.6, power against a planted 5% spread):

        L = 3   ->  0.75, 1.00, 1.00     the floor is far too low
        L = 8   ->  0.12, 0.88, 0.69
        L = 16  ->  0.00, 0.19, 0.38
        L = 30  ->  0.00, 0.06, 0.06     correct size, almost no power

    So under strong dependence only a whole-unit block is honest, and it costs
    nearly all the power against a small effect. `block` of 0 - the default -
    is that whole-unit block, because a gate that reports "they differ" when
    they do not is the failure that matters.

    **And on real data the binding reason was not dependence inside a unit.**
    `level-shrinkage.md` measured `lag_one` at -0.074 to +0.105 on 72 pools of
    level interactions, so touches are near enough independent - yet a block of
    8 still declared 27 of 36 **placebo** pools to be differing populations,
    against 3 of 36 at the default. The pool itself is heterogeneous: laid end
    to end it runs across instruments and epochs, so a whole-unit block inherits
    one local mean where a unit built from short blocks averages several and
    lands nearer the grand mean. A null unit has to be the same kind of object
    as a real one, and a placebo arm is what shows when it is not - which is
    worth more here than any calibration on a synthetic pool.
    """
    import random

    observed, _pooled, used = tau_squared_of_means(groups, logs=logs)
    observed = math.sqrt(observed)
    if used < UNITS:
        return observed, float("nan"), float("nan")
    kept = [
        [math.log1p(float(v)) for v in values] if logs else [float(v) for v in values]
        for values in groups
        if len(values) >= LEAST_VALUES
    ]
    laid = [v for values in kept for v in values]
    counts = [len(values) for values in kept]
    size = len(laid)
    if size < LEAST_VALUES:
        return observed, float("nan"), float("nan")
    rng = random.Random(seed)
    nulls: list[float] = []
    over = 0
    for _ in range(draws):
        drawn = []
        for n in counts:
            length = n if block <= 0 else min(int(block), n)
            values: list[float] = []
            while len(values) < n:
                at = rng.randrange(size)
                take = min(length, n - len(values))
                values.extend(laid[(at + step) % size] for step in range(take))
            drawn.append(values)
        got, _mean, _units = tau_squared_of_means(drawn)
        nulls.append(math.sqrt(got))
        over += math.sqrt(got) >= observed
    if not nulls:
        return observed, float("nan"), float("nan")
    nulls.sort()
    return observed, nulls[len(nulls) // 2], (over + 1) / (len(nulls) + 1)


def borrow_weight_of_means(
    groups: Sequence[Sequence[float]], fallback: float = 4.0, logs: bool = False
) -> float:
    """`K` for a per-unit mean, in pseudo-observations.

    `borrow_weight` with the rate's `p(1-p)` replaced by the pooled within-unit
    variance, for the same shrinkage `own / (own + K)`. Clamped at both ends for
    the same two degenerate reasons.

    **Read it only when `differ_means` has opened the gate.** `K` is a ratio
    with `tau_squared` underneath, so as the between-unit spread goes to zero
    the weight goes to the clamp - which is correct behaviour and completely
    uninformative about the quantity. `level-shrinkage.md` has it returning 14
    on a pool whose `tau` is indistinguishable from its own null, where the
    honest answer is "pool everything" and the number 14 means nothing.
    """
    got, _pooled, used = tau_squared_of_means(groups, logs=logs)
    if used < UNITS:
        return float(fallback)
    within: list[float] = []
    for values in groups:
        kept = [math.log1p(float(v)) for v in values] if logs else [float(v) for v in values]
        if len(kept) < LEAST_VALUES:
            continue
        mean = sum(kept) / len(kept)
        within.append(sum((v - mean) ** 2 for v in kept) / (len(kept) - 1))
    if not within:
        return float(fallback)
    pooled_within = sum(within) / len(within)
    if got <= 0.0 or pooled_within <= 0.0:
        return 50.0
    return min(max(pooled_within / got, 0.5), 50.0)
