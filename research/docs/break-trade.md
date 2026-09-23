# Trading the break: one factor of three survives, and it is the clock

Run: `python research/harness/break_trade.py`

**Measured 2026-09-22 on 312,420 resolved level touches** from the live journal, 2026-08-13 to
2026-09-22, every timeframe, no band filter. The desk's own record rather than stored history.

The question came from the desk, in three parts, and it is the right decomposition:

> *for breaks if we know that the break has a high probability of happening and we can estimate
> how far it will go we can take the position [...] we can also estimate/predict the optimal hold
> time or a high probability hold time for the trade*

That is exactly the arithmetic `learning/breaking.py` says is missing from its own output. It
publishes `break_probability` and decides nothing, for a stated reason: *"a break rate is not
money: what it is worth depends on the size of what follows and the cost of being wrong."* So:
probability, magnitude, hold time. Three factors, and `overshoot_theory.py` already proved the
third is a factor and not a detail - `E[P&L] = m = mu E[tau]`.

**One of the three survives. It is the third one, and it survives in a different form than the
one asked for.**

| factor | measured | verdict |
| --- | --- | --- |
| probability | AUC 0.5433 (`slowing`) to 0.624 (`experience`, inverted) unconditionally | **works** |
| magnitude | `r` with the realised move: **−0.006 to +0.006** across seven features, n=312,420 | **null** |
| hold time | not forecastable *up front*; but **P(break) runs 14.4% → 77.8% as the clock runs** | **works, reframed** |

## First, a correction to a number this repository has been quoting

`breaking.py` calls `interval_log` the largest single separator in the book and gives the break
rate by the level's timeframe as **1m 57.9%, 3m 26.8%, 5m 20.4%, 15m 12.8%, 30m 2.8%, 1h 1.4%**,
monotone and fortyfold over 126,296 resolutions.

Unconditionally, over 312,420, it is not that:

| timeframe | n | break rate, **published** | break rate, **unconditional** |
| --- | ---: | ---: | ---: |
| 1m | 147,312 | 57.9% | **13.4%** |
| 3m | 69,671 | 26.8% | **8.9%** |
| 5m | 51,132 | 20.4% | **9.5%** |
| 15m | 17,836 | 12.8% | **4.5%** |
| 30m | 5,883 | 2.8% | **2.7%** |
| 1h | 3,684 | 1.4% | **0.5%** |

The published figures were measured on resolutions **lasting five minutes or more**, and the
median 1m touch resolves in **120 seconds**. So the cut discards most of the population, and it
discards it non-randomly: slow touches are the ones that break. The monotone ordering is real and
survives - the level's timeframe does separate - but **the level of it was a selection effect**,
and 57.9% is not a number any desk can trade against because nothing knows at order time that
this touch will be a slow one.

This matters beyond bookkeeping. It was tempting to read "1m levels break 57.9% of the time"
against the live record's **−7.75 per close over 47 closes at 1m** (`trading-scaling.md`,
t = −2.29) and conclude that the desk's 1m losses are the desk taking the wrong side of a 58/42
split. **That conclusion is wrong.** Unconditionally 1m levels hold 86.6% of the time, the level's
directional call is on the right side of them, and the 1m losses have to be explained by something
else - cost, most likely, since `banded-labels.md` measured that **86.0% of one-minute calls never
move enough to pay for a trade** against a 4bp band.

## Magnitude does not predict, and this is a clean null

Correlation of each causal feature with the realised absolute move, over every resolved touch:

| feature | n | AUC on break | r with \|move\| | r with log tau |
| --- | ---: | ---: | ---: | ---: |
| `approach_vol` | 312,420 | 0.5253 | −0.002 | −0.051 |
| `depth_vol` | 312,420 | 0.4379 | +0.001 | −0.071 |
| `slowing` | 224,278 | **0.5433** | −0.000 | −0.002 |
| `slope` | 192,402 | 0.5048 | +0.006 | +0.011 |
| `prior_slope` | 192,402 | 0.4980 | −0.003 | +0.002 |
| `strength` | 312,420 | 0.3924 | −0.003 | −0.317 |
| `experience` | 312,420 | **0.3764** | −0.002 | **−0.523** |

Every entry in the `|move|` column is inside ±0.006 at six figures of sample. **Nothing the desk
knows when a touch opens predicts how far the resolution will travel.** That closes the middle
factor, and it closes it hard enough that it should not be re-opened without a new feature rather
than a new model - this is seven features against one target at n=312,420, which is not a power
problem.

Two side notes worth keeping. **The AUC ranking inverts between the band and the population.**
`force.md` measured `depth_vol` as the strongest separator inside the 300-1800s band and found
`strength` and `experience` leaning the *wrong* way - stronger levels breaking more. On the full
population they are the strongest separators there are, and they lean the *right* way: 0.3924 and
0.3764 read inverted are **0.608 and 0.624**, ahead of anything in `force.md`. A sign flip between
a subsample and its population is Simpson's paradox, which the README records this folder walking
into three times already. This is the fourth.

And `experience` at r = −0.523 with log resolution time is the strongest single relationship on
the page. It is almost certainly mechanical - busy instruments accumulate level experience and
also resolve touches quickly - but it means `experience` is largely a **clock** rather than a
quality measure, which is not how its name reads.

## The clock is the result

Elapsed time is the one conditioning variable that is free. "This touch took at least `t` to
resolve" and "this touch is still open at `t`" are the same event, so a table built on realised
durations is a table a live timer can act on - which is what separates it from everything else
here.

**P(break | still open at t):**

| tf | 0s | 30s | 60s | 120s | 300s | 600s | 1200s | 1800s | 3600s | 7200s | n | crosses 50% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1m | 14.4% | 15.7% | 16.6% | 22.4% | **54.7%** | **77.8%** | | | | | 136,929 | **300s** |
| 3m | 9.2% | 12.3% | 12.9% | 15.6% | 26.3% | 44.9% | **77.1%** | 75.6% | | | 67,029 | **1200s** |
| 5m | 9.7% | 11.2% | 11.5% | 12.7% | 17.8% | 27.4% | **50.1%** | 73.6% | 80.9% | | 50,037 | **1200s** |
| 15m | 4.5% | 5.5% | 5.7% | 6.1% | 7.4% | 9.5% | 15.2% | 23.2% | **50.0%** | 72.6% | 17,634 | **3600s** |
| 30m | 2.7% | 2.8% | 2.8% | 3.0% | 3.4% | 4.1% | 5.8% | 8.4% | 19.1% | 48.9% | 5,877 | ~7200s |
| 1h | 0.5% | 0.6% | 0.6% | 0.7% | 0.7% | 0.9% | 1.1% | 1.4% | 3.1% | 7.9% | 3,684 | |

A 1m touch still open at five minutes is **five times** as likely to break as one just opened.
The effect is monotone on every row and it is large - larger than any feature in this
repository - and it is free.

**And it scales.** The crossing point is not a constant number of seconds, it is a constant
number of the level's own bars:

| timeframe | crosses 50% at | in bars of its own timeframe |
| --- | ---: | ---: |
| 1m | 300s | **5** |
| 3m | 1200s | ~7 |
| 5m | 1200s | **4** |
| 15m | 3600s | **4** |
| 30m | ~7200s | ~4 |

Four to seven bars, on five timeframes spanning a factor of thirty. So the rule is scale-free and
has one parameter:

> **A level that has not resolved within about five of its own bars is more likely to break than
> to hold.**

That is a rule a desk can hold in its head, and `breaks.py` can compute it from a timestamp.

### Why this is a mechanism and not a curiosity

A break has to travel *through* the zone before it travels past it; a rejection only has to
travel away. So a break is the slower outcome by construction, and the median durations say so
directly - **480s against 120s at 1m, 12,096s against 1,020s at 30m**, a four- to twelvefold gap
on every timeframe.

That explains the effect rather than explaining it away. The forward probability is still the
forward probability, and the fact that it has a mechanical cause is the reason to expect it to
persist rather than to decay - which is what happened to every fitted effect in this folder.

## What is *not* shown here, stated plainly

**The expectancy columns in the harness are contaminated and should not be read as a P&L.** They
report the mean signed move in the break direction, which comes out at −2.80 volatility units for
the break side and +2.72 for the hold side at 1m, apparently overwhelming the 0.040 round trip.

That is not an edge. `push_vol` is measured **to the resolution point, and the resolution point is
defined by price having travelled a resolve distance from the level.** So its magnitude is close
to the labelling threshold by construction, and "the hold direction pays 2.7 volatility units"
largely restates the rule that declares a resolution. It is the trap `trend.py` names - *"a
quantity signed by the outcome was scored against the outcome"* - arriving one level removed,
in the payoff rather than in the feature.

The harness keeps the columns because the *asymmetry* between them is not definitional - `m break`
runs 4.02 to 5.48 against `m hold` at 1.96 to 3.80, so breaks travel further than holds once they
happen - but the levels are, and neither number is a return.

**So nothing here authorises a trade yet.** What it authorises is a change to what
`break_probability` is computed from, and the honest next step is the shadow counterfactual
`bandits.md` argues for: run the clock rule live, record what it would have overruled, and price
it on real fills before it sizes anything.

## The period split, which is the warning

| timeframe | break rate, first half | second half |
| --- | ---: | ---: |
| 1m | 9.4% | **18.5%** |
| 3m | 5.8% | **12.7%** |
| 5m | 8.3% | **10.4%** |
| 15m | 4.3% | 4.6% |

The 1m break rate **doubled across forty days.** The fast timeframes are not stationary over the
horizon this study covers, so any model that learns a break *level* is fitting a moving target,
and only the *ordering* - by timeframe, and by elapsed time - should be trusted to persist. The
clock rule is an ordering, which is the second reason to prefer it.

## Method notes carried forward

* The error bars in the harness are two plain standard errors and are **too narrow**. Touches on
  one feed and interval overlap in time. A block bootstrap is the honest interval and is not
  implemented here; nothing in this document rests on a margin narrower than a factor of two.
* The sign convention was **checked, not assumed** - `signed()` is verified against 312,420 rows
  before anything is computed with it: breaks come out 100.0% positive in the break direction and
  holds 0.0-0.1%. Two earlier documents in this folder got a sign wrong and published from it.
* These are level resolutions, not trades. They have no stop. `barrier-geometry-is-irrelevant.md`
  licenses scoring a signed move instead of a barrier race, but a real stop truncates the losers
  and `adverse_vol` is the only handle on that - unused here, and the first thing to add.
