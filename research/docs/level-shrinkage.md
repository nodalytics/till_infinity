# One shrinkage weight, borrowed from a rate and spent on a mean

**Measured 2026-10-15.** Code:
[`push_shrinkage.py`](../ideas/push_shrinkage.py). 126,002 resolved level
interactions across 1h and 4h, six traded instruments, four generated feeds and
a construction-guaranteed positive control.

`reactions.infer` is the function that turns a level's record into an answer,
and it shrinks that record toward the level's neighbours with one weight:

```python
weight = own.touches / (own.touches + prior_weight)
probability = weight * own.probability_up(prior_up, prior_weight) + (1 - weight) * prior_up
push        = weight * own.mean_push                             + (1 - weight) * prior_push
```

`prior_weight` is `PRIOR_WEIGHT = 4.0` until the pool can measure it, and then
it is `engine._prior_weight`, which calls `shrinkage.prior_weight` on samples of
`(stats.touches, stats.ups)` - the **direction rate**. The closed form it uses
is right for a rate: `K = p(1-p) / tau_squared`, a touch's own binomial noise
over the real spread between levels.

**The same `K` is then spent on `mean_push`, which is not a rate.** A continuous
mean's sampling variance is `s_squared / n`, not `p(1-p) / n`, and its
between-level spread is a different number in different units. Nothing says the
two ratios agree. That is the question, and three others came with it:

1. what `K` production's own estimator actually returns on live-shaped data;
2. whether levels differ in **sweep depth** or **push** at all - the continuous
   quantities [`statespace-conditional-holds.md`](statespace-conditional-holds.md)
   explicitly left open when it closed the hold rate, on the argument that a
   hold is one bit per touch and a depth is not;
3. whether a level's own record predicts its next interaction out of sample.

## The answer

**`K` is pinned at its clamp, and that turns out to be the right answer reached
by the wrong route.**

| frame, group | pooled hold | `tau` | levels | interactions | `K` returned |
|---|---:|---:|---:|---:|---:|
| 1h traded | 0.4927 | 0.0109 | 279 | 20,741 | **50.00** (clamp) |
| 4h traded | 0.4890 | 0.0148 | 265 | 17,758 | **50.00** (clamp) |
| 1h generated | 0.4980 | 0.0190 | 184 | 13,324 | **50.00** (clamp) |
| 1h range-break | 0.2760 | 0.0670 | 90 | 4,120 | 44.45 |

`shrinkage.prior_weight` documents the behaviour exactly - "no measurable spread
between levels: pool hard" - and `MAX_WEIGHT` is 50. So on every traded pool,
`weight = touches / (touches + 50)`: a level with the median couple of dozen
touches is heard at about a third, and a level needs **fifty** touches before
its own record outweighs its neighbours'.

Two mechanisms drive it there and both are working as designed. The direction
rate has no between-level spread to find - `prod-probability-up-needs-halving`
measured the rate itself as carrying no signal - and `SideStats.decay` multiplies
`touches` by a factor, so `n` is a decayed pseudo-count, `p(1-p)/n` is
**overstated**, more of the observed spread is charged to sampling, and `tau` is
biased down. A downward-biased `tau` is an upward-biased `K`.

## Do levels differ in depth or push? No, to a resolution of 5%

The continuous counterpart of the same decomposition, in log space, on traded
instruments. `tau` is the between-level sd of the true mean; `null` is what
identical levels counted this often produce; `fake` is a distance-matched price
that is not a level.

| frame | quantity | arm | `tau` | null | excess | p |
|---|---|---|---:|---:|---:|---:|
| 1h | wick | real | 0.0702 | 0.0660 | +0.0042 | 0.202 |
| 1h | wick | fake | 0.0705 | 0.0657 | +0.0048 | 0.192 |
| 1h | depth | real | 0.0300 | 0.0300 | −0.0000 | 0.504 |
| 1h | depth | fake | 0.0269 | 0.0269 | +0.0000 | 0.496 |
| 1h | push | real | 0.0839 | 0.0787 | +0.0051 | 0.125 |
| 1h | push | fake | 0.0833 | 0.0763 | +0.0070 | 0.095 |
| 4h | push | real | 0.0954 | 0.0897 | +0.0057 | 0.130 |
| 4h | push | fake | 0.0927 | 0.0892 | +0.0035 | 0.249 |

In log space `tau` reads approximately as a proportion, so 0.05 is near a 5%
spread between levels. **The planted-offset arm finds 5% at p of 0.015 to 0.030
and 10% at p of 0.002 on all three quantities**, so this is a test with
resolution, and what it sees is nothing:

| planted | wick | depth | push |
|---|---:|---:|---:|
| 0% | p 0.202 | p 0.504 | p 0.125 |
| 5% | **p 0.030** | **p 0.015** | **p 0.027** |
| 10% | **p 0.002** | **p 0.002** | **p 0.002** |
| 20% | **p 0.002** | **p 0.005** | **p 0.002** |

Across all 36 real-arm rows, six reach p ≤ 0.05 against ~1.8 expected by
chance - and every one of the six has a placebo twin at the same value, the
largest excess on a real arm is **+0.0084**, and the largest on a **placebo** is
**+0.0120**. A quantity whose placebo out-disperses it is not a quantity with
between-level structure. The depth and push distributions carry no more
between-level information than the hold rate did.

## The positive control, and what a null `tau` does not mean

`Range_Break_*` has a range **by construction**, so it is the one feed where
levels are guaranteed real, and it behaves like it: its boundaries hold
**0.2760** against the placebo's **0.2507**, a gap of +0.0253 at **z = +2.60**.
On traded instruments the same comparison is +0.0007 at z = +0.15 (1h) and
+0.0035 at z = +0.66 (4h).

And on that same feed, `tau` is null - wick p 0.479, push p 0.481, depth p 1.000.

**So a level population can be real and homogeneous at once, and this is the
distinction the whole study turns on.** A null `tau` does not say levels do
nothing. It says they all do the same thing, and the right response to that is
not to retire the machinery but to **pool it**: one depth distribution and one
push distribution per instrument, read by every level on it.

That also means `Range_Break_*` is a positive control for *levels existing* and
**not** for *levels differing*, because the generator has one range process and
every boundary inherits it. There is no available feed that plants a population
of levels that differ, so the planted-offset arm is the only power statement
available for `tau` - and it is power against exactly `tau`'s estimand, which is
the property worth having.

## Does a level's own record predict? Only what a non-level does

Out of sample, walk-forward, against the baseline that already knows the
instrument - log space, 1h and 4h traded, `K = 4`:

| frame | quantity | real, vs feed | placebo, vs feed |
|---|---|---:|---:|
| 1h | push | +0.00566 | +0.00570 |
| 1h | wick | +0.00198 | +0.00169 |
| 4h | push | +0.00908 | +0.00928 |
| 4h | wick | +0.00531 | +0.00521 |

A level's own running mean does beat its instrument's pooled mean. So does a
price that is not a level, by the same amount or more. The gain is a
volatility-regime effect: the scale is fixed when the level is nominated, so any
price's own recent record tracks the current regime and a static pooled mean
cannot. It is not a level effect, and on the generated feeds - where volatility
is stationary by construction - it vanishes to ±0.0005 and `K = 50` wins.

## Three things this harness got wrong first

The corrections are more durable than the result.

**A null unit has to be the same kind of object as a real one, and the placebo
arm is what proves which.** The first null dealt single observations at random,
i.i.d.; on units identical by construction with an AR(1) inside each, that
rejects at p ≤ 0.05 on **100%** of trials at rho of 0.3 and 0.6 against 7% at
rho of zero, because dealing singly destroys dependence inside a unit and so
lowers the floor without lowering the observed value. The fix was to deal each
unit a contiguous run from the units laid end to end.

Then the block length turned out to be the whole question, and the reason is not
the one that motivated it. Swept on the synthetic pool, as (size at rho 0.3,
size at rho 0.6, power against a planted 5%):

| block | size, rho 0.3 | size, rho 0.6 | power at 5% |
|---|---:|---:|---:|
| 3 | 0.75 | 1.00 | 1.00 |
| 8 | 0.12 | 0.88 | 0.69 |
| 16 | 0.00 | 0.19 | 0.38 |
| 30 (whole unit) | 0.00 | **0.06** | 0.06 |

**But the measured within-level autocorrelation is −0.074 to +0.105** across all
72 rows - consecutive touches of a level are essentially independent, so serial
dependence is not what forces the conservative choice. What forces it is that
the **pool** is heterogeneous: laid end to end, the observations run across six
instruments and several years, so a whole-unit block inherits one local mean
where a unit built from short blocks averages several and comes out closer to
the grand mean. Shorter blocks therefore understate the floor by destroying the
pool's own structure rather than the unit's.

And the placebo is what settles it rather than the argument. With the whole-unit
block, 6 of 36 real-arm rows reach p ≤ 0.05 against ~1.8 expected. With a block
of 8, **27 of 36 real rows and 27 of 36 placebo rows** do - the shorter null
declares that three-quarters of distance-matched non-levels differ between
themselves. A null that rejects on the placebo is refuted, whatever its
calibration looks like on a synthetic pool.

**A scale-free plant on a scale-free statistic is not an effect.** The first
power arm multiplied each level's observations by its own lognormal factor,
which scales the level's own spread along with its mean - so the ratio the test
forms is unchanged. A log-sd of 0.20 moved `tau` by less than 0.004 on every
quantity and frame, where the between-level sd it implies is 0.07 to 0.36. The
plant has to be additive, and on a positive quantity that means working in logs.

**The baseline has to know the instrument.** The first run pooled across all six
traded instruments, and a level's own record beat that by 0.112 of MSE on push -
which reads as a per-level effect and is a per-**feed** one, because push in
median-bar-range units is not the same size on XAUUSD as on EURUSD. The
generated arm, whose feeds are alike, showed the same gain **reversed** at
−0.004 in the same run, which is the tell.

A fourth, from the positive control: in raw units the per-level mean of a sweep
depth is carried by its largest one or two observations. On `Range_Break_*`,
where a break runs hundreds of in-range bars in one move, arm 4's MSE came back
at **577** against 1.79 on traded instruments, and the raw-space test went blind
below a 20% spread where the log-space one sees 5%. On a lognormal with log-sd
1.5, the single largest of thirty observations holds a median 26.7% of a unit's
total against 3.3% if they contributed evenly, and 11.5% under `log1p`.

One claim about that transform needed walking back. `log1p` is a
variance-stabiliser and not a change of units: it tends to `log` only for values
well above 1, so a planted multiplicative spread of 0.25 is recovered as 0.12 at
a pooled mean near 1.7 and as 0.21 at a pooled mean near 170. A log-space `tau`
is a **lower bound** on a proportional spread. The raw ratio `tau / pooled` is
the exactly scale-free quantity, and it does not stabilise the variance, so the
two are worth reading side by side - which is what the tables above do.

## What to change

**Nothing in the live arithmetic, and that is the finding.** `K` at 50 is where
push wants to be; the measurement says pool, and pooling is what the clamp does.

What is worth fixing is that the two are **coupled by accident**. One weight
serves a rate and a mean, so if the direction rate's `tau` ever rises - a
regime, a feed, a changed decay factor - `K` falls and `expected_push` stops
pooling as a side effect of a question it was not asked. The weights should be
separate even while they agree, because they agree for unrelated reasons.

And `engine._prior_weight` is computed, cached for `PRIOR_WEIGHT_RECHECK` and
**never published**. A parameter that governs every `expected_push` on the desk
is currently invisible to the journal, so nobody could see that it sits at its
clamp. That is the cheap half of the fix.

`dispersion.tau_squared_of_means`, `differ_means` and `borrow_weight_of_means`
are the continuous counterparts the library did not have, with the block null
and the log-space default carried in their docstrings so the next caller does
not re-learn the three mistakes above.
