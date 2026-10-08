"""How much borrowed evidence is worth, estimated instead of chosen.

`reactions.infer` blends a level's own record with its neighbours':

    weight = own.touches / (own.touches + PRIOR_WEIGHT)

`PRIOR_WEIGHT` is 4.0 and its docstring says "roughly: borrowed evidence is
worth this much of the level's own". That is the right shape and the number is
a guess, and the thing a guess costs here is not obvious in either direction:

* if levels genuinely differ, the true weight is **smaller** and 4.0
  **over-shrinks** - every level is dragged toward its neighbours and real
  idiosyncrasy is averaged away
* if levels barely differ, the true weight is **larger** and 4.0
  **under-shrinks** - three noisy touches are allowed to override a pooled
  estimate built on hundreds

Nobody has checked which, and the answer is not a matter of taste.

## It has a closed form

`PRIOR_WEIGHT` is the `K` of a shrinkage estimator, and the Bayes weight for a
binomial rate observed `n` times is

    n / (n + K)     with    K = sigma_within^2 / tau^2

where `sigma_within^2` is the noise in one observation - `p(1-p)` for a
rate - and `tau^2` is the **real** spread of rates between levels. So `K` is a
variance ratio, estimable from the same touches the levels already record, and
both halves of the intuition fall straight out of it: levels that really differ
give a large `tau^2` and a small `K`, levels that do not give `tau^2` near zero
and a `K` that says "pool almost everything".

`tau^2` is estimated by DerSimonian and Laird's method of moments, which is the
standard closed form for exactly this - a between-group variance recovered by
subtracting the sampling noise from the observed spread. It cannot be done by
taking the variance of the observed rates directly: that spread already
contains the binomial noise, so it always overstates `tau^2`, and the
correction is the whole method.

## Why this is not another adaptive parameter replacing a constant

`research/docs/edge.md` found a rolling quantile losing to a matched constant
**four times out of four**, and a walk-forward adaptive probability floor
coming out worse than no floor. That is a strong prior against this kind of
change and it is taken seriously.

The difference is what is being estimated. Those fitted a **threshold against
returns** - a free parameter chosen to make a number look good, with no
identity constraining it. This estimates a **variance ratio with a closed
form**, from the touch counts themselves, with no reference to whether anything
made money. It is the same arithmetic that says a mean of ten samples is worth
ten times one sample.

## What it needs, and the honest caveat

`K` needs enough **levels** in a pool, not enough touches in a level. A pool of
three levels cannot say how much levels differ however many times each was
touched, so below `MIN_LEVELS` this returns the constant unchanged - the same
run-in shape `conformal.SETTLE` uses, and for the same reason.

It is also clamped at both ends. A pool that happens to produce `tau^2` near
zero would otherwise ask for infinite pooling, which is a statement no finite
sample earns.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Levels a pool needs before its own `K` is used. Below this the constant
#: stands, because a handful of levels cannot say how much levels differ.
MIN_LEVELS = 12

#: Touches a level needs to contribute a rate. One touch is a rate of 0 or 1
#: with no information about its own precision, and a pool of those produces a
#: spread that is all sampling noise.
MIN_TOUCHES = 2.0

#: How far the estimate may travel from the constant it replaces. At the low
#: end borrowed evidence stops counting at all; at the high end a level's own
#: history never gets to speak.
MIN_WEIGHT, MAX_WEIGHT = 0.5, 50.0


def tau_squared(samples: Sequence[tuple[float, float]], mean: float) -> tuple[float, int]:
    """Between-level variance of the true rates, and how many levels said so.

    DerSimonian and Laird's method of moments. The observed spread of rates
    already contains each level's own sampling noise, so subtracting it is not
    a refinement - it is what separates "levels differ" from "levels were
    counted few times".
    """
    within = mean * (1.0 - mean)
    if within <= 0.0:
        return 0.0, 0
    usable = [(n, ups) for n, ups in samples if n >= MIN_TOUCHES]
    if len(usable) < 2:
        return 0.0, len(usable)
    # Each level weighted by its own precision: n / p(1 - p).
    weights = [n / within for n, _ in usable]
    q = sum(w * (ups / n - mean) ** 2 for w, (n, ups) in zip(weights, usable, strict=True))
    total = sum(weights)
    spread = sum(w * w for w in weights)
    divisor = total - (spread / total if total else 0.0)
    if divisor <= 0.0:
        return 0.0, len(usable)
    return max(0.0, (q - (len(usable) - 1)) / divisor), len(usable)


def prior_weight(samples: Sequence[tuple[float, float]], fallback: float) -> float:
    """`K` for this pool, in pseudo-touches, or `fallback` if it cannot say.

    `samples` is `(touches, ups)` per level, from one side. See the module
    docstring for why this is a variance ratio rather than a fitted parameter.
    """
    usable = [(n, ups) for n, ups in samples if n >= MIN_TOUCHES]
    if len(usable) < MIN_LEVELS:
        return fallback
    touches = sum(n for n, _ in usable)
    if touches <= 0:
        return fallback
    mean = sum(ups for _, ups in usable) / touches
    if not 0.0 < mean < 1.0:
        # Every level agreed. That is a pool with no spread to measure, not a
        # pool whose levels are identical, and the two are indistinguishable
        # from here.
        return fallback
    tau, counted = tau_squared(usable, mean)
    if counted < MIN_LEVELS or tau <= 0.0:
        # No measurable spread between levels: pool hard. Clamped rather than
        # infinite, because "indistinguishable" is a claim no finite sample
        # earns outright.
        return MAX_WEIGHT
    return min(max(mean * (1.0 - mean) / tau, MIN_WEIGHT), MAX_WEIGHT)
