# How far, and what it costs to be wrong

Run: `python research/harness/magnitude.py`

[prior.md](prior.md) established that the directional claim is a re-encoding of
`side` - give the baseline the same side conditioning and what remains predicts
at 51.8%, AUC 0.520. It also said what it had not tested: magnitude and risk. A
system can be useful for *how far* while having nothing to say about *which
way*.

**Magnitude works and is miscalibrated. Risk does not work, and the gate built
on it is losing money.**

| claim | verdict |
|---|---|
| `expected_push` ranks how far price goes | **yes** - and it is the first thing in this project to beat its null |
| `expected_push` is the right size | **no** - it understates by 3x |
| `risk_vol` bounds the loss | **no** - zero relationship to realised adverse movement |
| `reward_to_risk` selects good trades | **no** - it selects losing ones, and the mechanism is known |

11,116 calls paired with the outcome of the touch each one opened, across
fourteen instruments.

## 1. `expected_push` ranks, which is the part that matters

Realised profit of the call's own trade, by decile of `|expected_push|`:

| decile | \|expected\| | n | realised \|push\| | **realised** |
|---|---|---|---|---|
| 1 | 0.000 | 1,111 | 2.884 | **+0.212** |
| 2 | 0.172 | 1,111 | 2.801 | +0.258 |
| 5 | 0.701 | 1,111 | 2.864 | +0.264 |
| 7 | 1.098 | 1,111 | 2.973 | +0.481 |
| 9 | 1.609 | 1,111 | 3.127 | +0.944 |
| 10 | 2.033 | 1,117 | 3.451 | **+1.603** |

**A 7.5x spread, monotone in the top half.** Against its null - the
per-(feed, interval) mean push, accumulated causally - it wins on rank
correlation too, +0.072 against +0.029. Both are small; the point is the sign
and the ordering, and that this is the first measurement in this project where
the machinery beats the counting.

Note *what* is being ranked. Realised `|push|` is nearly flat at about 2.9
across the deciles: `expected_push` is **not** ordering how far price moves. It
is ordering how often the call is right, which is a different and more useful
thing than its name suggests.

## 2. It is three times too small

| | |
|---|---|
| mean `\|expected_push\|` | **1.023** |
| mean realised `\|push\|` | **2.992** |
| ratio | **0.34** |

A number denominated in volatility units that reads 1.0 when the truth is 3.0
is not a rounding error. Everything downstream inherits it, and
`reward_to_risk` inherits it most: the ratio is understated by the same factor,
so `MIN_REWARD_TO_RISK = 1.0` is in practice demanding a true ratio near 3.

**Fixing the calibration alone would make things worse**, because it would push
three times as many calls through a gate that section 4 shows is losing money.
Order matters here.

## 3. `risk_vol` has no relationship to being wrong

| | |
|---|---|
| median stop distance beyond the level | 1.388 |
| median adverse excursion | **0.000** |
| ever went beyond the level | 34.3% |
| **would have been stopped out** | **31.6%** |
| **corr(stop distance, adverse excursion)** | **+0.006** |

Zero. The stop is placed by geometry - the zone plus a buffer - and that
geometry carries no information about how far price actually goes against the
trade.

It is also not a small stop in practice: **31.6% of calls would have been
stopped out** before resolving, which means the realised figures elsewhere in
this document, which assume the position is held to resolution, are optimistic.

## 4. `reward_to_risk` selects losing trades

This is the finding that needs acting on.

| RR at least | n | share | mean realised | per unit of risk |
|---|---|---|---|---|
| 0.0 | 11,113 | 100% | **+0.496** | +0.084 |
| 0.5 | 5,199 | 46.8% | +0.424 | −0.016 |
| **1.0** *(the live gate)* | 1,560 | 14.0% | **−0.268** | **−0.485** |
| 1.5 | 620 | 5.6% | −0.570 | −0.836 |
| 2.0 | 298 | 2.7% | −0.614 | −0.891 |
| 3.0 | 56 | 0.5% | +0.032 | +0.101 |

**Gating at 1.0 turns +0.496 into −0.268.** It inverts the sign of the expected
return. The 3.0 row is 56 calls and is noise.

### The mechanism, which the codebase already knew

`reward_to_risk` is `|net_push| / risk_vol`, and it correlates **+0.571 with
its numerator and −0.359 with its denominator**. A high ratio is substantially
just a *small* `risk_vol`:

| decile | RR | \|expected\| | `risk_vol` | stopped out |
|---|---|---|---|---|
| 1 | 0.049 | 0.111 | 2.279 | 29.1% |
| 5 | 0.419 | 1.029 | 2.454 | 30.1% |
| 9 | 0.982 | 1.551 | 1.592 | 35.9% |
| **10** | **1.791** | 1.629 | **0.968** | **44.8%** |

A small `risk_vol` is a tight zone, which puts the stop close to the level.
`Level.stop_for` says exactly what is wrong with that:

> Beyond the zone, not at the level. The zone is precisely the band in which
> price can sit and still be respecting the level, so a stop inside it is a
> stop inside the noise - **it gets hit by the level working.**

`reward_to_risk` rewards the thing that docstring was written to avoid. The
principle was understood and the ratio quietly violates it.

## 5. What `actionable` delivers

| | |
|---|---|
| calls passing every gate | 1,107 of 11,130 (**9.9%**) |
| **mean realised** | **−0.151** |
| median realised | +1.108 |
| share that made money | 64.3% |
| **mean realised of everything it rejected** | **+0.569** |

**The gate selects a losing tenth out of a winning population.** Taking every
call indiscriminately returns +0.496; taking only what `actionable` approves
returns −0.151; taking only what it *rejects* returns +0.569.

The shape is worth naming: it wins 64.3% of the time with a median of +1.108
and still loses on average, so a minority of large losses dominates. That is
the signature of selling volatility, and it is what a gate keyed on a tight
stop will produce.

## Limits

- **Bars only**, no spread, no slippage, no funding. `cost_vol` exists and is
  not modelled here.
- **Held to resolution.** Section 3 measures stop-outs separately; the realised
  figures elsewhere do not apply them, so they are optimistic by an unknown
  amount on the 31.6% that would have been stopped.
- **One sign convention checked twice.** The first version of this script scored
  the *hold* trade rather than the *call's* trade. They agree on about nine
  calls in ten, and the tenth is the entire question, so the distinction is
  reported explicitly: on the calls `actionable` passes, holding instead
  returns −0.086 against the call's −0.151. Both are negative; the selection is
  the problem, not only the direction.

## Recommendations, in order

1. **Stop gating on `reward_to_risk`.** It is measured, on 11,113 calls, to
   invert the sign of the expected return. This is not a tuning question -
   there is no threshold at which it helps, because the quantity is
   anti-correlated with what it claims to measure.
2. **Do not fix the calibration first.** Correcting the 3x understatement while
   the ratio gate stands would triple the number of calls passing a gate that
   loses money. Remove the gate, then fix the number.
3. **Keep `expected_push` and publish it.** It is the one component here that
   beats its null and it orders realised profit 7.5x from bottom decile to top.
   It is the most valuable thing the level model produces, and it is currently
   used mainly as an input to the ratio that is doing the damage.
4. **Re-derive the stop from realised adverse excursion**, not from zone
   geometry. The data to do it is already collected - `excursion_vol` is
   recorded on every touch - and the current placement has a measured
   correlation of +0.006 with what it is supposed to bound.
5. **Then reconsider what a risk gate is for.** A stop that gets hit 31.6% of
   the time on a population that resolves favourably 64% of the time is
   converting winners into losers. Whether the answer is a wider stop, no stop,
   or a different exit rule is a design question this measurement does not
   settle - but it does rule out the current one.
