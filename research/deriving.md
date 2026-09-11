# A martingale minus a spread is a loss at every horizon, and here is the proof

[generators.md](generators.md) and [twins.md](twins.md) finished the
measurement. The Deriv synthetics are exactly the processes the venue
publishes: the twelve Volatility indices are geometric Brownian motion at the
annualised volatility in their names to within **0.49%**, Step Index is a fixed
0.1 step and a fair coin to **p = 0.499734 +- 0.000220**, Boom and Crash spike at
the published rate with a memoryless arrival, Range Break 100 breaks **2.066x**
as often as 200, and the Jump indices realise **1.322x** their names.

Once the parameters are known the question changes. A statistic asks whether a
pattern holds up and needs a split sample and a p-value. A **derivation** asks
what the exact distribution of something is, and needs neither, because it is
arithmetic on a specified process. This page is that arithmetic, and its results
divide into two kinds which are marked as such throughout: **theorems**, which
are true of the process by construction, and **measurements**, which are the
data agreeing or failing to agree with them.

Four harnesses: [`derivegbm.py`](harness/derivegbm.py),
[`deriveruin.py`](harness/deriveruin.py),
[`derivejump.py`](harness/derivejump.py),
[`derivecost.py`](harness/derivecost.py). Each states its kill conditions in its
docstring before any number, and each prints every result three ways - the
closed form, a Monte Carlo of the *specified* generator, and the real data -
so that a disagreement can be blamed on the right one of the three.

## The theorem, first, because it retires most of the book

Let `P` be the mid price and `w_t` the position held over `[t, t+1)`, decided
from anything known at `t`. If `P` is a martingale - which
[generators.md](generators.md) verified four separate ways on all 26 synthetics -
then

    E[ sum_t w_t (P_{t+1} - P_t) ] = 0

for every such `w` with finite expected turnover. That is the martingale
transform, and optional stopping is its special case. The broker's cost is

    (c/2) * sum_t |w_t - w_{t-1}|

which is strictly positive whenever anything is traded. Therefore

    **E[net] = -(c/2) * E[turnover],  strictly negative, always.**

A stop is a position process. So is a target, a trailing stop, a break-even
move, a scale-out, a pyramid, a grid, martingale doubling, an entry filter, a
time exit and every position-sizing scheme including Kelly. **None of them can
change the sign**, because none of them is anything but a choice of `w`. The
only free variable is turnover, and driving turnover to its floor - one entry,
one exit, held forever - gives exactly `-c`. Never more.

Two corollaries worth having in this form:

* **the barrier trade.** A long entered at the offer with a stop `S` and a
  target `T` has `E[net] = -c` in price units and `-c/S` in R, **at every
  geometry**. That is [generators.md](generators.md)'s stop table - -0.200,
  -0.100, -0.040, -0.020 at stops of 5, 10, 25 and 50 spreads - derived rather
  than replayed: they are `-0.1/0.5`, `-0.1/1.0`, `-0.1/2.5`, `-0.1/5.0`.
* **every exit that forces a re-entry strictly loses to holding**, because
  expectancy is decreasing in turnover and nothing else. The eighteen exit
  policies in [exiting.md](exiting.md) are eighteen turnovers.

### The theorem, verified twenty-three ways, twice, with a positive control

`deriveruin.py` writes twenty-three rules as position processes and replays them
on a 4,000,000-step fair walk and on the 86,393 real `step_index` ticks. Each
must return gross zero and a net of exactly `-c/2` per unit of turnover.

| | simulated fair walk | measured step_index |
| --- | --- | --- |
| rules | 22 + 1 control | 22 + 1 control |
| max \|z\| on gross | **1.84** | **1.03** |
| rules past \|z\| = 2 | **0** | **0** |
| net per unit turnover | -0.4794 to -0.4996 | -0.0344 to -0.0508 |
| derived `-c/2` | **-0.5000** | **-0.0500** |
| **look-ahead control** | **+0.5002** | **+0.0505** |

The rules are stops at three geometries, two time stops, two trailing stops, a
break-even move, a scale-out, a pyramid, doubling after a loss and after a win,
a four-add grid, an always-in reversal, buy-and-hold, two entry filters on
consecutive-step runs, sizing by streak length, a 100-step momentum rule, its
reversion mirror, and random sizing. They share one path, so these are not
twenty-two independent tests and no combined z is quoted.

**The control is the load-bearing row.** A table of zeros is indistinguishable
from a harness that computes zero, and this repository has published a statistic
sitting on exactly its null twice ([giveback.md](giveback.md),
[twins.md](twins.md) section 6). `cheat_next` is handed the next step and earns
**+0.5002 per unit of turnover where every honest rule pays -0.5000**. The
estimator can see an edge. There is none to see.

The three rules whose *net* comes out positive are the ones with almost no
turnover - buy-and-hold, the wide grid, the wide barrier - and what they are
showing is the one realised path's terminal displacement, which on this sample
has a standard error of 2,142 against a value of 1,725.

## One: geometric Brownian motion, and the correction that is the finding

For `volatility_N_index` the unit that makes every answer parameter-free is the
one-minute sigma, `u = (N/100)/sqrt(365*24*60)`. Measured in `u`, the textbook
results lose their constants:

| question | continuous closed form | **discretely monitored** |
| --- | --- | --- |
| P(up barrier `a` before down `b`) | `b/(a+b)` | `(b+B)/(a+b+2B)` |
| expected time to leave the band | `a*b` minutes | `(a+B)(b+B)` |
| expected maximum over `T` | `sqrt(2T/pi)` | less `B*sigma*sqrt(dt)` |
| expected high-low range over `T` | `sqrt(8T/pi)` | less `2B*sigma*sqrt(dt)` |
| P(touch `a` within `T`), one-sided | `2*Phi(-a/sqrt(T))` | `2*Phi(-(a+B)/sqrt(T))` |
| fraction of `T` spent above the start | arcsine, `(2/pi)arcsin(sqrt(x))` | - |

with

    B = -zeta(1/2)/sqrt(2*pi) = 0.5826

the Broadie-Glasserman-Kou continuity correction, which is also the limiting
expected overshoot of a Gaussian random walk past a level. **That constant is
the finding of this section**, because at one-minute monitoring in one-minute
sigmas `sigma*sqrt(dt)` is 1 and the correction is 0.5826 of a *unit*. It is not
a refinement; it is most of the answer.

### Measured on 86,411 bars a feed, twelve feeds

| a:b | n | P(up) measured | continuous | **corrected** | z vs corrected | E[tau] measured | continuous | **corrected** | err cont | **err corr** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1:1 | 372,708 | 0.5000 | 0.5000 | 0.5000 | 0.00 | 2.782 | 1.000 | 2.505 | +178.2% | **+11.1%** |
| 3:3 | 79,442 | 0.5001 | 0.5000 | 0.5000 | 0.08 | 13.051 | 9.000 | 12.835 | +45.0% | **+1.7%** |
| 5:5 | 33,141 | 0.5008 | 0.5000 | 0.5000 | 0.30 | 31.279 | 25.000 | 31.165 | +25.1% | **+0.4%** |
| 10:10 | 9,240 | 0.5015 | 0.5000 | 0.5000 | 0.29 | 112.062 | 100.000 | 111.991 | +12.1% | **+0.1%** |
| 3:1 | 174,501 | **0.3073** | 0.2500 | **0.3064** | +0.79 | 5.942 | 3.000 | 5.670 | +98.1% | **+4.8%** |
| 1:3 | 174,898 | 0.6928 | 0.7500 | 0.6936 | -0.69 | 5.929 | 3.000 | 5.670 | +97.6% | **+4.6%** |
| 9:1 | 67,400 | **0.1426** | 0.1000 | **0.1417** | +0.44 | 15.382 | 9.000 | 15.165 | +70.9% | **+1.4%** |
| 2:10 | 37,726 | 0.8042 | 0.8333 | 0.8038 | +0.14 | 27.472 | 20.000 | 27.331 | +37.4% | **+0.5%** |

Read the `3:1` row. A stop one sigma below and a target three above is *not* a
25% shot. It is a **30.7%** shot, because a discretely quoted price crosses a
near barrier by an overshoot that matters more the nearer the barrier is. The
textbook number is wrong by a fifth of itself and the corrected one is right to
within 0.8 standard errors on 174,501 trades.

Both halves of the sample agree on all twelve feeds: the `5:5` expected duration
runs 30.55 to 32.31 in the first thirty days and 30.08 to 31.90 in the last
against a derived 31.165, and the `2:10` hit probability runs 0.7906 to 0.8165
and 0.7955 to 0.8149 against a derived 0.8038.

### The same correction, three more times

**Touch probabilities.** Over cells away from the boundaries, the mean absolute
error of the continuous formula is **14.3%**, of the first-order correction
**1.5%**, and of the exactly-evaluated discrete law **0.4%**.

**The maximum and the range**, in one-minute sigmas, pooled over twelve feeds:

| T | E[max] measured | continuous | corrected | **exact discrete** | E[range] measured | continuous | **exact discrete** |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5m | 1.2933 | 1.7841 | 1.2015 | **1.2895** | 2.5821 | 3.5682 | **2.5782** |
| 15m | 2.5649 | 3.0902 | 2.5076 | **2.5638** | 5.1245 | 6.1804 | **5.1198** |
| 60m | 5.6502 | 6.1804 | 5.5978 | **5.6280** | 11.2338 | 12.3608 | **11.2453** |
| 240m | 11.7735 | 12.3608 | 11.7782 | **11.7722** | 23.6321 | 24.7215 | **23.5782** |

**And the number `generators.md` could not explain.** That page measured a
Parkinson-to-close volatility ratio of **0.870** on the two-second family and
**0.909** on the one-second family and left it as an observation about tick
resolution. It is the same constant. A bar's range is resolved by `n` ticks, so
both ends are short by `B` per-tick sigmas, and

    ratio ~= 1 - 2B / sqrt(8n/pi)

gives **0.8667** at n=30 and **0.9057** at n=60; evaluating the discrete range
law exactly gives **0.8701** and **0.9100**. Per feed, using each feed's own
*measured* publication rate rather than its nominal one:

| feed | ticks/bar | measured | **exact discrete** | error |
| --- | --- | --- | --- | --- |
| volatility_25_index | 29.9 | 0.8699 | 0.8701 | **-0.02%** |
| volatility_75_index | 30.0 | 0.8697 | 0.8701 | **-0.05%** |
| volatility_100_index | 29.1 | 0.8702 | 0.8676 | +0.30% |
| volatility_75_1s_index | 59.7 | 0.9095 | 0.9100 | **-0.05%** |
| volatility_250_1s_index | 58.1 | 0.9093 | 0.9082 | +0.12% |
| *volatility_150_1s_index* | *39.4* | *0.9060* | *0.8837* | *+2.18%* |

**Mean absolute error 0.30% across twelve feeds.** The one outlier is the feed
[twins.md](twins.md) section 6 already quarantined for a coarse quote grid and
a collector dropping 7.85% of its ticks, and it misses in the direction a
dropped-tick count predicts.

That closes a loose end and opens a practical one: **a barrier is further away
than it looks, by `0.5826` tick-sigmas, on every tick-settled product.** On the
Volatility family that shift is 0.29 to 0.38 of the quoted spread.

### Two more closed forms that hold

**Occupation time** follows the arcsine law, which is the least intuitive result
in elementary probability and is exactly right here. Fraction of a 60-minute
window spent above the starting price, pooled over twelve feeds:

| decile | derived | simulated | measured |
| --- | --- | --- | --- |
| 0.0-0.1 | 0.2048 | 0.1992 | **0.1984** |
| 0.4-0.5 | 0.0641 | 0.0638 | 0.0637 |
| 0.5-0.6 | 0.0641 | 0.0641 | 0.0587 |
| 0.9-1.0 | 0.2048 | 0.2169 | **0.2195** |

A price spends most of an hour on one side of where it started, and the mode of
that distribution is at the two ends. Any rule built on "it has been above the
open all session" is reading the arcsine law.

**The expectancy theorem, on GBM.** Sixty cells - twelve feeds, five geometries,
the quoted spread charged:

* gross expectancy: **max \|z\| 0.71**, combined +0.506;
* net in R against the derived `-c/risk`: errors from **0.0002 to 0.0152**,
  the worst being `volatility_10_1s_index` at a 5:5 barrier where the derived
  -0.0566 comes out -0.0414.

## Two: the drift is undecidable in sixty days, and it does not matter

A driftless *log* price and a driftless *price* differ by `sigma^2/2`. Which
convention Deriv's generator uses is a real question and this sample cannot
answer it. Over 86,410 one-minute returns a feed:

* mean log return against zero: **combined z = +0.231** over twelve feeds;
* the two conventions are **0.537 combined standard errors apart**.

So the drift is bounded but not identified. It does not matter, and the bound is
why: on `volatility_75_index` the larger of the two candidate drifts is
`5.35e-7` per minute against a spread of `3.53e-4`. **The spread is 660 minutes
of the largest drift the process could have**, and both candidates are smaller
than the cost at every horizon a position is held for. The theorem survives the
ambiguity.

## Three: Step Index is Gambler's Ruin, and nothing escapes it

A fixed step `d` and a fair coin make this the most solved problem in
probability. Target `T` steps, stop `S` steps:

    P(target) = S/(S+T)      E[tau] = S*T steps      Var[tau] = S*T*(S^2+T^2-2)/3

Measured on the 86,393 real ticks, against those exact values:

| S:T | P(target) | derived | z | E[tau] | derived | error | n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5:5 | 0.5004 | 0.5000 | +0.05 | 24.9 | 25.0 | -0.58% | 3,475 |
| 5:10 | 0.3339 | 0.3333 | +0.05 | 48.9 | 50.0 | -2.24% | 1,767 |
| 5:15 | 0.2504 | 0.2500 | +0.03 | 75.5 | 75.0 | +0.71% | 1,142 |
| 10:10 | 0.5012 | 0.5000 | +0.07 | 99.5 | 100.0 | -0.55% | 868 |
| 5:50 | 0.0917 | 0.0909 | +0.03 | 255.5 | 250.0 | +2.22% | 338 |
| 50:5 | 0.9102 | 0.9091 | +0.04 | 267.3 | 250.0 | +6.90% | 323 |

### And it explains a 6% discrepancy already in print

[generators.md](generators.md)'s replay reported hit rates of **0.3525** at a 2R
target and **0.2722** at 3R where `S/(S+T)` says 0.3333 and 0.2500. That is a 6%
and a 9% excess and the page did not account for it.

It is the fill rule. A lattice walk crosses a level by at most one step, and a
comparison that triggers strictly beyond the level puts the effective stop at
`S+d` and the effective target at `T+d`:

    P(target) = (S+d)/(S+T+2d)

| target | `S/(S+T)` | **`(S+d)/(S+T+2d)`** | generators.md |
| --- | --- | --- | --- |
| 1R | 0.5000 | 0.5000 | 0.4998 |
| 2R | 0.3333 | **0.3529** | **0.3525** |
| 3R | 0.2500 | **0.2727** | **0.2722** |

and running the same path under both conventions reproduces both columns:

| S:T | fill at the level | derived | fill one step past | derived |
| --- | --- | --- | --- | --- |
| 5:10 | 0.3339 | 0.3333 | **0.3536** | **0.3529** |
| 5:15 | 0.2504 | 0.2500 | **0.2732** | **0.2727** |
| 5:25 | 0.1667 | 0.1667 | **0.1874** | **0.1875** |

This is the lattice form of the same continuity correction as section one, and
it is a property of the fill rule rather than of the instrument - but it is also
the honest risk: **at a five-spread stop the realised loss is 0.6 rather than
0.5, a fifth more than the sizing assumed.** The expectancy is unchanged at
`-c`, because the barriers are still symmetric about a martingale.

**Step Index is therefore closed.** Not "no edge found" - *there is no edge*,
and the statement is a theorem rather than a null.

## Four: Range Break has a range, and the break pays for it exactly

This is the one genuinely new generator property on the page, and it is a
**measurement**.

Range Break ticks one unit at a time like Step Index, so it should be the same
free walk. It is not. `Var(C_{t+n} - C_t) / (n * 60 * d^2)` must be 1.0 at every
`n` for independent steps, and on 86,410 one-minute bars:

| series | n=1 | n=5 | n=20 | n=100 | n=500 | n=1000 |
| --- | --- | --- | --- | --- | --- | --- |
| step_index *(control)* | 1.001 | 1.009 | 1.016 | 1.066 | 1.069 | 1.114 |
| range_break_100, all bars | 4.217 | 4.225 | 4.271 | 4.295 | 4.441 | 4.713 |
| range_break_100, **ex-break** | 0.978 | 0.730 | 0.436 | **0.283** | **0.274** | **0.279** |
| range_break_200, all bars | 5.645 | 5.669 | 5.681 | 5.917 | 5.685 | 5.176 |
| range_break_200, **ex-break** | 0.930 | 0.750 | 0.477 | **0.192** | **0.116** | **0.112** |

Drop the bars containing a break and the process is **sub-diffusive by a factor
of 3.6 on RB100 and 8.9 on RB200** - the range is real, it confines the price,
and it orders correctly, since RB200 spends twice as long inside one before
breaking out. The step_index control is flat at 1.0 and each series' own
return-shuffle reproduces the all-bars curve exactly, so the estimator is alive.

**And the all-bars curve is flat.** The break contributes 76.8% of one-bar
variance on RB100 and 93.6% of the variance at 200 bars; on RB200 it is 83.5%
and 97.6%. The mean reversion between breaks is paid for by the break to the
precision of a flat variance ratio over three orders of magnitude in horizon.

That is **the same construction as Boom and Crash**: a predictable small move in
one direction and a memoryless jump that exactly cancels it. Boom grinds and
spikes; Range Break reverts and breaks. Both close.

### So the confinement cannot be traded, and the screen says so against its own false-positive rate

Fading an `m`-bar move and holding `n` bars, 46 and 44 cells over m,n in
{5,15,60,240} and three thresholds, each against its own return shuffle, both
halves of the sixty days and z=2:

| feed | cells | largest gross | as % of spread | z | **cells clearing all four filters** |
| --- | --- | --- | --- | --- | --- |
| range_break_100_index | 46 | 17.86 | 1786% | 1.14 | **0** |
| range_break_200_index | 44 | 16.39 | 1639% | 0.71 | **0** |
| *step_index (control)* | *47* | *1.43* | *1430%* | *1.21* | ***1*** |

The control row is what makes the zeros readable. **The same screen admits one
survivor in 47 on an instrument that is provably a fair coin**, and Range Break
produces none in ninety. The largest raw numbers look enormous - 17.86 units
against a one-unit spread - and they are noise: the standard error on that cell
is 15.6 and its own shuffle produces 5.50.

The break rate itself is known and useless in the way [generators.md](generators.md)
already established, but it is worth writing as the formula it is: the arrival
is memoryless at 86.5 and 178.8 minutes (CV 1.003 and 1.076), so

    P(a break inside a hold of t minutes) = 1 - exp(-t/86.5)

which is **0.500** for an hour and **0.938** for four hours on RB100, and 0.285
and 0.739 on RB200. That is a variance statement. The mean is still zero.

## Five: Boom and Crash, as the compound Poisson process they are

Per tick the price moves `-g` with probability `1-p` and `+J` with probability
`p = 1/lambda`. Every parameter is measurable, so the P&L of a hold is a
distribution with a formula rather than a backtest.

| feed | spikes | lambda | E[g] | CV[g] | E[J] | median J | closure | z | z h1 | z h2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| boom_300_index | 306 | 267.7 | 0.00373 | 0.632 | 1.0624 | 0.9327 | -2.48e-04 | -0.90 | +0.99 | +0.29 |
| boom_500_index | 160 | 529.4 | 0.00977 | 0.661 | 4.7837 | 3.9635 | +7.16e-04 | +0.81 | -0.70 | -0.43 |
| boom_1000_index | 94 | 908.3 | 0.01511 | 0.671 | 14.6405 | 12.2198 | -1.02e-03 | -0.49 | -0.29 | +0.92 |
| crash_300_index | 260 | 329.0 | 0.01787 | 0.676 | 5.4198 | 4.7620 | +1.34e-03 | +1.08 | +0.24 | +1.32 |
| crash_500_index | 165 | 507.7 | 0.00624 | 0.655 | 2.8331 | 2.6280 | +6.44e-04 | +1.21 | +0.30 | +1.44 |
| crash_1000_index | 86 | 973.8 | 0.00605 | 0.656 | 5.6712 | 4.9718 | +2.20e-04 | +0.28 | +0.63 | -0.20 |

The same detector on `volatility_75_index` and `step_index` finds **zero**
spikes, which is the control.

### The derived P&L law reproduces the empirical one across the whole ladder

`P&L(N) = N*g - sum_{k=1..K} J_k` with `K ~ Binomial(N, p)`. Drawing `K` from
that binomial and the magnitudes from their fitted marginals - nothing here
walks the real path - against the real 24 hours of ticks, on `boom_500_index`:

| N ticks | | mean | median | sd | P(profit) | q01 | q99 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | derived | +0.0066 | 0.0972 | 0.8210 | **0.9813** | -3.386 | 0.145 |
| | observed | +0.0071 | 0.0960 | 0.8150 | **0.9812** | -3.318 | 0.149 |
| 100 | derived | +0.0713 | 0.9601 | 2.5735 | **0.8500** | -10.802 | 1.122 |
| | observed | +0.0768 | 0.9610 | 2.5364 | **0.8481** | -9.859 | 1.131 |
| 500 | derived | +0.3591 | 2.7540 | 5.7707 | **0.6457** | -18.479 | 5.166 |
| | observed | +0.4092 | 2.3560 | 5.5881 | **0.6303** | -18.635 | 5.141 |
| 3000 | derived | +2.1576 | 3.6801 | 14.1496 | **0.5989** | -36.770 | 27.608 |
| | observed | +2.6873 | 5.0382 | 14.4065 | **0.6246** | -40.270 | 29.166 |

Mean, median, standard deviation, hit rate and both tails, at every holding
period. The generator is the model.

**And the closure forces the shape.** `E[J] = lambda * E[g]` exactly - measured
at 489.6 against lambda 529.4 on boom_500 - so one spike costs one lambda of
grind and the hold is profitable **iff fewer than `N/lambda` spikes arrive**.
A Poisson variable lands below its own mean more than half the time at every
`N`, which is why:

**the grind side of Boom and Crash wins 98% of ten-tick holds, 85% of
hundred-tick holds and 60-63% of thousand-tick holds - and its expectancy is
exactly zero at all three.** That is picking up pennies in front of a steamroller
with the pennies and the steamroller both counted.

### The +13.96R stop slippage, derived

[generators.md](generators.md) measured, on 24 hours of ticks and before this
page existed, that a stop on the spike side of `boom_500_index` fills
**+13.96R, +6.81R, +2.44R and +1.02R** past where it was placed at stops of 5,
10, 25 and 50 spreads. Those four numbers are the target here and are not
refitted.

Derive it. Price grinds *away* from the stop at `g` a tick, so the barrier the
spike has to clear grows with time held; the trade ends at the first
`J_t > D + sum(g)`, and the fill is at `entry - sum(g) + J`. Evaluating that on
the fitted jump distribution:

| feed | stop | | P(stop) | mean slip R | p90 | max | >0.5R | mean loss R |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| boom_500 | 5 | **derived** | 0.0603 | **+13.348** | 27.81 | 40.88 | 0.970 | -14.348 |
| | | observed | 0.0593 | **+13.961** | 28.27 | 40.24 | 0.973 | -14.961 |
| boom_500 | 10 | **derived** | 0.1078 | **+6.772** | 13.72 | 19.98 | 0.944 | -7.772 |
| | | observed | 0.1066 | **+6.807** | 13.75 | 19.49 | 0.963 | -7.807 |
| boom_500 | 25 | **derived** | 0.2076 | **+2.462** | 4.86 | 7.88 | 0.843 | -3.462 |
| | | observed | 0.2106 | **+2.439** | 4.85 | 6.96 | 0.820 | -3.439 |
| boom_500 | 50 | **derived** | 0.3014 | **+1.067** | 2.06 | 4.00 | 0.736 | -2.067 |
| | | observed | 0.3077 | **+1.019** | 1.93 | 2.88 | 0.711 | -2.019 |

Twenty-four cells across six feeds; **the worst disagreement on the mean
slippage is 5.2%** (`crash_1000` at a five-spread stop, 20.09 derived against
19.09 measured) and most are inside 2%. The stop-out probability, the 90th
percentile, the maximum and the fraction past half an R all come along with it.

The derived column is a 60,000-path Monte Carlo of the derived model rather than
a closed form, because the first-passage problem for a compound Poisson process
against a moving barrier has no elementary one - so it carries its own noise,
about half an R at the narrowest stop, which is the size of most of the residual
in the table.

**What was a measurement on one day of ticks is now a formula**, so the multiple
for any stop width on any of the six can be computed without re-running
anything, which is what a sizing rule needs.

### The stop does not bound the risk until it clears the jump

`P(J > D)`, the fraction of stop-outs that gap straight through:

| feed | 5 spreads | 10 | 25 | 50 | stop at the 95th percentile of J |
| --- | --- | --- | --- | --- | --- |
| boom_300_index | 0.964 | 0.895 | 0.729 | 0.458 | **122 spreads** |
| boom_500_index | 0.963 | 0.888 | 0.763 | 0.531 | **161 spreads** |
| boom_1000_index | 0.979 | 0.926 | 0.809 | 0.692 | **231 spreads** |
| crash_500_index | 0.933 | 0.903 | 0.770 | 0.582 | **144 spreads** |
| crash_1000_index | 0.954 | 0.884 | 0.826 | 0.674 | **212 spreads** |

So the answer to "derive the correct position size and stop placement given a
known jump intensity" is unwelcome and exact:

1. **the growth-optimal size is zero**, because expectancy is `-c` and Kelly on
   a negative-expectancy bet is not a fraction, it is abstention
   ([compounding.md](compounding.md) reaches the same place from the live R
   distribution);
2. **if the side is taken anyway, the stop is not the risk until it is past the
   95th percentile of the jump - 120 to 231 spreads** - and at any width below
   that the risk per unit is `D * (1 + m(D))` with `m` from the table above;
3. **the cost-minimising exit rule is no exit**, by the turnover theorem. A stop
   on the spike side does not cap the loss and does force a re-entry, so it is
   strictly worse than holding on both terms.

## Six: the cost, against the volatility that is known

If the game is fair, the spread is the whole expectancy, and for seventeen
instruments the volatility on the other side of the comparison is known to three
figures. The natural unit is `t* = (c/sigma)^2` - the horizon at which the
standard deviation of the move first equals the spread, which is the exact form
of "how long must this be held to pay for itself".

| feed | realised ann. | spread bps | c / sigma_1s | **t\* (seconds)** |
| --- | --- | --- | --- | --- |
| boom/crash (six) | 21.6-102.0 | 0.10-0.50 | 0.259-0.279 | **0.07-0.08** |
| range_break_200 | 20.10 | 0.161 | 0.450 | 0.20 |
| *btc* | *35.26* | *0.310* | *0.494* | *0.24* |
| range_break_100 | 20.89 | 0.184 | 0.496 | 0.25 |
| *gold* | *27.08* | *0.341* | *0.708* | *0.50* |
| **jump_10 ... jump_100** | 13.3-131.6 | 0.24-2.42 | **0.990-1.031** | **0.98-1.06** |
| step_index | 7.24 | 0.132 | 1.026 | 1.05 |
| *usdjpy* | *10.58* | *0.261* | *1.383* | *1.91* |
| volatility (ten) | 10.0-100.5 | 0.39-4.31 | 1.874-2.799 | 3.51-7.83 |
| *eurusd* | *5.60* | *0.258* | *2.586* | *6.69* |
| *silver* | *50.31* | *3.738* | *4.173* | *17.41* |
| volatility_150_1s | 150.70 | 12.505 | 4.660 | 21.71 |
| **volatility_250_1s** | **250.76** | **75.876** | **16.992** | **288.74** |

Three things fall out of that table.

**`volatility_250_1s_index` costs 289 seconds of its own volatility to cross.**
That is 17 times the Jump family, 40 times any real instrument on the book bar
silver, and four times the next worst synthetic. Nothing on this book should
touch it. `volatility_150_1s_index` is second worst at 21.7 seconds, and both
are the feeds [twins.md](twins.md) flagged for coarse quoting - so part of this
is the quote grid rather than the dealer, but the cost is paid either way.

**The Boom/Crash row flatters them** and should not be read as cheapness. Their
annualised volatility is spike variance, and what a grind position actually
waits through is `spread/E[g]` ticks: **5.4, 6.9, 9.9, 5.7, 6.7 and 9.8**, which
reproduces [generators.md](generators.md)'s 5.7 to 11.0 from the other side.

**The synthetics are not uniformly cheap.** [catalogue.md](catalogue.md) put the
synthetics at 0.170v against FX's 2.267v and concluded the point spreads lie.
Measured against the *known* volatility rather than an estimated one, the
ordering is finer than that: Boom, Crash and Range Break really are cheaper than
anything real, but the entire Volatility family is more expensive than btc,
us100, gold and usdjpy, and two of its members are the worst prices on the book.

### Is the spread set off the name? No - and that closes the 1.322

The Jump indices realise 1.322 times their names, so if the venue's own pricing
uses the name anywhere, that gap is worth money. The spread is the only
broker-set price in `research.db`, so it is the only place this is testable.

| family | c / sigma_realised (per second) | range | n |
| --- | --- | --- | --- |
| volatility | 2.3632 +- 0.2543 | 1.874 - 2.799 | 10 |
| **jump** | **1.0103 +- 0.0151** | **0.990 - 1.031** | **5** |

**The Jump spread is exactly one second of realised volatility, on all five
feeds, to 1.5%** - and these feeds print once a second, so the spread is exactly
one tick's standard deviation of the *true* process. Step Index sits at 1.026 on
the same measure, which is the same rule, since its spread is exactly one step.
Had the spread been a formula on the name it would have landed at
`multiple / 1.322` against realised volatility and it does not.

**So the venue's own quote already knows the Jump indices run a third hotter
than their names.** The hypothesis is refuted, cleanly, and that is the useful
form of the result: the most obvious place a published-parameter error could
have been worth money is closed.

What survives is the *ratio*. Per unit of the volatility actually delivered, the
Volatility family costs **2.34x** what the Jump family costs (0.04208 against
0.01799 bps per point of annualised volatility, excluding the two coarse feeds).
That is a real difference in the venue's pricing across two families of the same
product, and by the theorem in section one it changes the size of the loss and
not its sign.

### The conditional theorem, and exactly what to check

The process does touch as often as its realised volatility says and not as often
as its name says, and the Volatility family is the control where the two
coincide:

| family | cells | mean \|error\| vs the **name** | mean \|error\| vs the **process** |
| --- | --- | --- | --- |
| volatility *(control)* | 108 | 12.2% | **3.6%** |
| jump | 45 | **56.6%** | **7.6%** |

measured / predicted-from-the-process, by barrier distance:

| x (window sigmas) | volatility | jump |
| --- | --- | --- |
| 0.5 | 1.007 | 0.946 |
| 1.0 | 1.007 | 0.929 |
| 1.5 | 1.007 | 0.925 |
| 2.0 | 1.001 | 1.030 |
| 2.5 | 1.023 | 1.023 |

So **if** any Deriv product on a Jump index is priced off the name - a one-touch,
a no-touch, a digital, an accumulator range, a knock-out - then it is mispriced
by `Phi(-x)/Phi(-1.322x)`:

| barrier, in realised window sigmas | P(touch) at the name | true | **true/name** | no-touch true/name |
| --- | --- | --- | --- | --- |
| 0.5 | 0.5084 | 0.6171 | **1.21** | 0.779 |
| 1.0 | 0.1860 | 0.3173 | **1.71** | 0.839 |
| 2.0 | 0.0082 | 0.0455 | **5.57** | 0.962 |
| 3.0 | 0.0001 | 0.0027 | **37.2** | 0.997 |
| 4.0 | ~0 | 0.0001 | **519** | 1.000 |

and the measured excess on the real bars tracks it: at 60 minutes the Jump feeds
touch **1.44x** the name's prediction at one sigma (derived 1.71) and **4.59x**
at two (derived 5.57), the gap being the discrete-monitoring correction from
section one biting harder on the more distant barrier.

**`research.db` contains no Deriv option or multiplier quote, so this is a
conditional and it stays one.** The check is one afternoon's work and it is
specific: pull a one-touch quote on `jump_75_index` at a barrier two window
sigmas out, and compare it with `2*Phi(-2)` rather than `2*Phi(-2.64)`. If the
venue prices its barriers the way it prices its spread, there is nothing there.
[twins.md](twins.md) is also right about the order of operations - a generator
artefact is measured, then the contract is read, and only then sized, because an
edge that gets voided on withdrawal is unpaid QA.

## The failure conditions, as they were written before the runs

| stated in | condition that would have killed it | outcome |
| --- | --- | --- |
| `derivegbm.py` | closed forms miss measured P or E[tau] by more than a few percent on the larger barriers | **survived** - corrected forms within 0.1-1.9% at a,b >= 3 |
| `derivegbm.py` | the uncorrected formula fits better, or the correction has the wrong sign | **survived** - 14.3% against 1.5% on touch, 12-178% against 0.1-11% on E[tau] |
| `derivegbm.py` | closed form, simulation and data disagree | **survived** - simulation matches data to 0.1-0.4% everywhere |
| `derivegbm.py` | a statistic lands on exactly its null | **survived, with a caveat below** |
| `deriveruin.py` | any rule more than 3 SE from zero gross on both paths | **survived** - max 1.84 and 1.03, none past 2 |
| `deriveruin.py` | the look-ahead control does not win enormously | **survived** - +0.5002 against -0.5000 per unit turnover |
| `deriveruin.py` | measured hit rates and durations miss the derived values | **survived on Step Index; failed on Range Break** - and that failure is section four |
| `deriveruin.py` | the simulated walk and the real tick path disagree | **survived** on Step Index |
| `derivejump.py` | the derived P&L distribution misses the empirical one | **survived** - mean, median, sd, hit rate and both tails, every holding period |
| `derivejump.py` | the slippage prediction misses genstop.py's four numbers by >20% | **survived** - worst cell 5.2% |
| `derivejump.py` | the closure fails on more than one feed | **survived** - \|z\| <= 1.21 on all six, both halves |
| `derivejump.py` | the control finds spikes on a feed with no spike mechanism | **survived** - zero on v75 and Step |
| `derivecost.py` | spread-per-unit-of-stated-volatility is no more constant than per-unit-of-realised | **the name hypothesis died** - c/sigma_realised is 1.0103 +- 0.0151 |
| `derivecost.py` | the Volatility control is not flat in cost per unit volatility | **failed** - it runs 1.874 to 2.799, CV 10.7%, so there is no single venue formula |
| `derivecost.py` | measured touch is not above what the name predicts | **survived** - 56.6% against 7.6% |
| `derivecost.py` | realised volatilities do not reproduce generators.md | **survived** - 0.9985-1.0050 and 1.3128-1.3382 |

Two fired. One found the Range Break range. The other says the venue prices two
families of its own product on two different rules.

**The caveat on landing exactly on the null.** `P(up)` at a symmetric barrier
comes out 0.5000 on 372,708 trades, which is exactly the number a dead column
produces. Three things say the column is alive: the same estimator on the same
call returns **0.3073** and **0.1426** at asymmetric barriers, matching a
*different* derived value each time; the null here is the vendor's own claim, so
hitting it is the alternative hypothesis rather than the absence of one; and the
look-ahead control in `deriveruin.py` moves the same machinery off zero by three
orders of magnitude.

## What this does not say

* **It is a statement about the generators, not about the venue's other
  prices.** Everything here is `research.db`: 86,411 one-minute bars a feed over
  60 days and 24 hours of ticks with bid and ask. Deriv sells multipliers,
  accumulators, turbos and digital options on these same processes and not one
  of those quotes is in the store. The section-six conditional is exactly as
  strong as that absence makes it.
* **The theorem is about expectancy, not about outcomes.** `E[net] = -c` says a
  strategy loses on average. It says nothing about the variance, and section
  five is the demonstration: the grind side of Boom wins 98% of short holds at
  an expectancy of zero. A rule can be simultaneously a theorem-guaranteed loser
  and a producer of long winning streaks, and this desk has mistaken the second
  for the first before.
* **It assumes the cost is the quoted spread.** Overnight financing, commission
  and any slippage beyond the quote are not in `research.db` and would only make
  the sign more negative. Nothing here needs them.
* **The martingale property is measured, not assumed - but it is measured on
  sixty days.** If Deriv re-parameterised a generator to carry a drift, this
  sample would not see it. Section two shows the drift bound is loose: the data
  cannot even distinguish `sigma^2/2` from zero. What it *can* say is that any
  drift small enough to hide here is far too small to pay a spread.
* **The Range Break confinement is a measurement and its mechanism is not
  published.** The variance deficit is large and clean and the fade is not
  tradeable, but the actual range rule - how wide, how it resets, what counts as
  a bounce - is unknown, so nothing here derives it.
* **The 0.5826 correction is asymptotic.** It is excellent at barriers of three
  units and more (0.1-1.9% error) and only fair at one unit (11%). Where the
  barrier is inside a couple of quote intervals, evaluate the discrete law
  numerically rather than correcting the continuous one.
* **Twenty-four hours of ticks.** The Boom/Crash jump distribution rests on 86
  to 306 spikes a feed. The *mechanism* is not statistical, so the derivation
  holds, but the quantiles of `J` - and therefore the sizing table - would move
  on a longer sample.

## What follows

1. **Stop searching for entries, exits, stops, targets and sizing on the 72% of
   the book that is generated.** Not because the search has failed but because
   it is provably the wrong search. The expectancy of every one of them is
   `-(c/2) * turnover` and the only reachable improvement is to trade less.
2. **Replace every barrier estimator on a synthetic with its closed form.** Hit
   probability `(b+B)/(a+b+2B)`, expected duration `(a+B)(b+B)` minutes, touch
   `2*Phi(-(a+B)/sqrt(T))`, all in one-minute sigmas with `B = 0.5826`. They
   need no warm-up, carry no estimation error, and they are 0.1% right where
   the textbook forms are 12% to 178% wrong.
3. **Apply the derived slippage multiple to the spike side of Boom and Crash, or
   do not take it.** [generators.md](generators.md) asked for this and could only
   give four measured numbers; it is now a function of the stop width and the
   fitted jump distribution, for any width.
4. **Retire `volatility_250_1s_index` and `volatility_150_1s_index` from the
   book.** 289 and 22 seconds of volatility to cross against 1.0 for the Jump
   family. Whatever a strategy is doing, it can do it somewhere 17 times cheaper.
5. **Pull one Deriv barrier-product quote on a Jump index and check it against
   `2*Phi(-x)`.** It is the one open question on this page with money attached,
   the arithmetic is in section six, and the prior after the spread result is
   that it will come back negative - which is worth an afternoon to establish,
   because it closes the last route by which a published parameter this desk
   knows to be wrong could have been worth anything.
