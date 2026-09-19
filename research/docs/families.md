# One family in the book is not a martingale, hits 63% of the time, and still cannot be traded

Five arms of the sequence-model study cover the Volatility family, where the
question is closed: a Volatility index is geometric Brownian motion at a
published constant sigma, [deriving.md](deriving.md) proves
`E[net] = -(c/2) x turnover` for any predictable position on a martingale, and
[rebuilding.md](rebuilding.md) confirmed it with `n*` infinite on every arm.
This arm covers **everything else** - Boom, Crash, Step, Jump, Range Break,
Drift Switch and DEX, 43 symbols across seven families - and the point of it is
that everything else is **not one process**.

The headline is one family and two numbers that have to be read together.

**`Drift Switch Index 20` has a lag-one return autocorrelation of `+0.1525` on
50,000 fifteen-minute bars.** That is `t = +34.1`, it is `+0.1552` and `+0.1499`
in the two halves, its Ljung-Box `p` is `5.9e-279`, the same statistic on the
shuffled returns is `-0.0030`, and on the six control symbols - a tier-1 fair
coin, two Volatility indices and three real markets - the largest `|t|` anywhere
on the grid is `5.2`. It is real, it is enormous, and it means
`E[r_{t+1} | r_t] != 0`. **That is the negation of the martingale property**,
which is the first assumption of `deriving.md`'s theorem, a page careful to call
it *measured* rather than assumed - and it was measured on twenty-six synthetics
that did not include this one. On this family the theorem does not apply and the
question it closes everywhere else is open.

**A walk-forward AR(1) rule on that series wins 56.9% of its bars, and loses
money.** Gross `+2.07e-4` a bar against a measured relative spread of `1.07e-3`
at a turnover of 0.860, so net is `-2.52e-4`. The spread at which it would break
even is `0.451` of the spread the broker quotes. Cutting turnover with a
threshold chosen on the training block makes it worse, not better: `0.233`. The
best cell in the entire eight-timeframe sweep across all three Drift Switch
members is `Drift Switch Index 30` at 1h, breakeven at **0.884 of the quoted
spread**, still short, net still negative. `Drift Switch Index 10` at 3m hits
**63.1%** and breaks even at `0.293` of its spread.

So: **structure exists, and it is not tradeable.** Those are two claims,
`deriving.md`'s theorem bears on the second only, and keeping them apart is what
this page is for. It is also [spending.md](spending.md)'s finding arriving from
the other direction - "the entries are within noise of adequate... the exits
realise **half** the payoff the entries were sized for" - here a 63% hit rate
that cannot pay for its own crossing.

A causal hidden-state filter reads the regime out of that autocorrelation at
**AUC 0.619** on 15m bars, and a GRU on the same rows reaches 0.6138 - below it,
as it is on seven of the nine cells. A phase surrogate reproduces 88% of the
filter's excess over 0.500 at 1h and 55% at 15m, so the structure is mostly but
not wholly spectral - and the residual does not go to the net either, which never
beats the filter where either of them is above chance. **The instrument built for
the generator's shape beats the general-purpose one on the generator it was built
for.** That is the second half of what this arm was commissioned to find: the one
family in the book where a sequence model has a legitimate job is also the one
family where it is unnecessary.

Every other family is a martingale as far as 11.34 million ticks and 336
symbol-timeframe cells of bars can see: not one of them reaches `|t| = 3.1` at
any timeframe, which puts all six of them below the real-market controls. The
ranking at the end says how much structure each has and, more usefully, of what
kind - because a large asymmetry in a marginal and a small one in a conditional
are not the same finding and only the second is a job for a sequence model.

## What was already known, and is therefore not re-run

Re-measuring a settled number on a worse sample is the most common way a page in
this folder has been wrong, so the inventory comes before the plan.

| already measured | where | status here |
|---|---|---|
| Step Index: 86,391 of 86,393 tick moves exactly 0.1; `p(up) = 0.499734 +- 0.000220` over 5.18M flips | [generators.md](generators.md), tier 1 | **positive control**, reproduced at `p(up) = 0.498710 +- 0.001000` on 249,999 moves |
| Range Break: 998 and 483 breaks over sixty days, 86.6 and 178.9 min, CV 1.003 and 1.075; sub-diffusion 3.6x and 8.9x | [deriving.md](deriving.md) | **not re-run**; section four is a detector check only |
| Range Break relaxation ladder `l2/l1` = 2.076 and 1.976, pre-registered band of 2 to 4 refuted from below | [quantising.md](quantising.md) | **not re-run** |
| Boom/Crash **300, 500, 1000**: rate, grind, jump size, closure; waiting-time CV 0.844 to 1.103 on 86 to 306 spikes | [generators.md](generators.md), tier 2 | rate confirmed; **the waiting-time test is re-run and section one says why** |
| Jump: realised/nominal 1.3226 on five feeds; jumps every 22 to 27 min against a published 20 | [rebuilding.md](rebuilding.md) | rate replicated independently at 23.1 to 25.1 min |

And the gap this page exists to fill. Enumerated across every markdown file in
`research/`, the following had **no measurement anywhere in the folder**:

* **Boom and Crash at 50, 100, 150, 200, 600 and 900** - twelve of the eighteen feeds;
* **eight of the nine Step-family members** - everything but the base Step Index;
* **all three Drift Switch** and **all six DEX**;
* the Boom/Crash waiting-time *distribution*, as opposed to its first two moments.

## Why `generators.md`'s memoryless verdict needed re-running, which is not the same as needing correcting

[generators.md](generators.md) reports "**The waiting time is memoryless across
the whole family** (CV 0.84 to 1.10 against 1.00)" and concludes that "nothing
can call a spike anywhere in this family". That conclusion is **upheld** below.
But the evidence for it was one moment on a small sample, and the difference
matters:

* a **coefficient of variation is one moment**, and it is the moment a Poisson
  process shares with a great many non-Poisson ones. A gamma renewal at shape
  1.2 has CV 0.91. A process with a hard refractory period and an otherwise flat
  hazard has a CV below 1 that no amount of sample separates from a short one.
* the sample was **twenty-four hours of ticks**, which is 94 spikes on Boom 1000.
  The standard error of a CV on 94 draws is about 0.073, so the measured range of
  0.844 to 1.103 is **two standard errors wide** and the test could not have
  rejected a gamma renewal at shape 1.2 if one had been there.
* it covered **six of eighteen** Boom and Crash feeds and none of DEX.

So this page runs 300,000 ticks a symbol - 303 to 5,462 spikes, three to
fifty-seven times the earlier sample - on all eighteen, plus six DEX and five
Jump, and replaces the single moment with five statistics, each against a
simulated compound Poisson built from the feed's own pools and passed through
the identical detector.

## The kill conditions, written before any number was read

They are in `research/harness/seqfamilies.py`'s docstring, before any result.
The ledger of which fired is at the end of the page.

1. **The detector is a detector artefact** if the spike rate moves with the threshold.
2. **The hazard result is void** if the simulated compound Poisson does not return CV 1.00, Fano 1.00 and acf1 0.00 within its own replicate band.
3. **The Skew Step reading is wrong** if `p_up * E[up] + (1 - p_up) * E[down]` does not close to zero within three standard errors.
4. **The Drift Switch claim is void** if the variance ratio on *shuffled* returns is not 1.00 within its band.
5. **A hidden-state model has found nothing** if the dwell time it reports on a phase surrogate is within a factor of two of the dwell time it reports on the feed.
6. **The wall clock is the wrong clock** and any next-bar spike number from it is withdrawn, if the mean spike count per bar is outside roughly [0.05, 1.0].

## One: the spike hazard is memoryless on all 29 feeds, at a sample that could have said otherwise

Detector: a tick whose **bid** move exceeds ten times the median absolute move -
`genspike.py`'s detector unchanged, reused rather than re-chosen so the rates
here can be set beside `generators.md`'s without a conversion. The bid and not
the mid, because [rebuilding.md](rebuilding.md) established that the mid takes a
half-grid step on every spread change and separates a feed from its own rebuild
at AUC 0.0242 on that artefact alone.

300,000 ticks a symbol, 84 to 88 hours each, 11.34 million ticks in total.

| family | n | ticks per spike / name | CV | max abs z over 5 tests |
|---|---|---|---|---|
| **boom** | 9 | **1.014** [0.890, 1.115] | 0.972 [0.843, 1.035] | 3.63 |
| **crash** | 9 | **1.031** [0.990, 1.098] | 0.980 [0.919, 1.044] | 2.32 |
| **jump** | 5 | 1.213 [1.157, 1.256] | 0.983 [0.897, 1.092] | 1.62 |
| **dex** | 6 | **0.380** [0.310, 0.472] | 1.003 [0.955, 1.060] | 3.36 |

**Every feed, because a family mean can hide a member.** `per` is the measured
ticks per spike, `rat` is that over the number in the name, `mspr` is the ratio of
the largest to the smallest rate across detection thresholds of 5x, 10x and 20x,
and each `z` is against this feed's own 200-replicate memoryless null.

| symbol | spikes | per | rat | mspr | CV (z) | KS (z) | Fano (z) | gap acf1 (z) | hz slope (z) | min gap |
|---|---|---|---|---|---|---|---|---|---|---|
| Boom 50 | 5,382 | 55.7 | 1.11 | 1.20 | 0.979 (-0.8) | 0.0215 (+0.5) | 0.904 (-1.2) | -0.026 (-1.8) | -0.033 (-1.2) | 1 |
| Boom 100 | 2,932 | 102.3 | 1.02 | 1.10 | 1.007 (+0.6) | 0.0159 (-0.3) | 0.968 (-0.2) | +0.017 (+0.9) | +0.007 (+0.2) | 1 |
| Boom 150 | 1,828 | 164.1 | 1.09 | 1.06 | 0.955 (-1.8) | 0.0272 (+2.0) | 1.066 (+0.7) | +0.017 (+0.8) | -0.013 (-0.2) | 1 |
| Boom 200 | 1,409 | 212.9 | 1.06 | 1.05 | 0.992 (-0.2) | 0.0180 (-0.4) | 0.963 (-0.2) | -0.009 (-0.3) | +0.012 (+0.2) | 1 |
| Boom 300 | 1,046 | 286.8 | 0.96 | 1.04 | 0.983 (-0.4) | 0.0260 (+0.5) | 0.888 (-0.6) | +0.009 (+0.4) | -0.000 (-0.1) | 1 |
| Boom 500 | 601 | 499.2 | 1.00 | 1.02 | 1.035 (+0.9) | 0.0203 (-1.4) | 1.258 (+1.4) | +0.037 (+1.1) | -0.289 (**-3.6**) | 2 |
| Boom 600 | 481 | 623.7 | 1.04 | 1.02 | 0.962 (-0.9) | 0.0252 (-0.9) | 1.052 (+0.3) | +0.045 (+1.1) | -0.004 (+0.1) | 4 |
| Boom 900 | 353 | 849.9 | 0.94 | 1.00 | 0.988 (-0.1) | 0.0232 (-1.5) | 0.929 (-0.4) | -0.002 (+0.0) | -0.093 (-1.0) | 1 |
| Boom 1000 | 337 | 890.2 | 0.89 | 1.01 | 0.843 (**-3.2**) | 0.0550 (+1.7) | 0.925 (-0.3) | +0.078 (+1.5) | +0.354 (**+3.3**) | 4 |
| Crash 50 | 5,462 | 54.9 | 1.10 | 1.20 | 0.994 (+0.4) | 0.0246 (+1.9) | 0.936 (-0.7) | -0.002 (-0.0) | -0.019 (-0.7) | 1 |
| Crash 100 | 2,850 | 105.3 | 1.05 | 1.10 | 0.983 (-0.7) | 0.0144 (-0.7) | 0.867 (-1.6) | -0.012 (-0.6) | +0.014 (+0.3) | 1 |
| Crash 150 | 1,994 | 150.5 | 1.00 | 1.06 | 0.994 (+0.0) | 0.0133 (-1.1) | 1.029 (+0.4) | +0.028 (+1.1) | +0.018 (+0.5) | 1 |
| Crash 200 | 1,482 | 202.4 | 1.01 | 1.03 | 0.988 (-0.3) | 0.0151 (-0.8) | 1.142 (+1.3) | +0.066 (+2.3) | +0.040 (+0.7) | 1 |
| Crash 300 | 973 | 308.3 | 1.03 | 1.04 | 1.044 (+1.5) | 0.0186 (-0.9) | 0.975 (-0.0) | -0.036 (-1.1) | -0.090 (-1.5) | 1 |
| Crash 500 | 577 | 519.9 | 1.04 | 1.02 | 0.976 (-0.5) | 0.0238 (-1.0) | 0.971 (-0.2) | +0.010 (+0.4) | -0.048 (-0.5) | 2 |
| Crash 600 | 490 | 612.2 | 1.02 | 1.02 | 0.939 (-1.4) | 0.0377 (+0.5) | 0.932 (-0.4) | -0.021 (-0.3) | -0.074 (-0.7) | 3 |
| Crash 900 | 323 | 928.8 | 1.03 | 1.03 | 0.982 (-0.3) | 0.0315 (-0.8) | 0.663 (-1.4) | -0.069 (-1.1) | +0.027 (+0.2) | 1 |
| Crash 1000 | 303 | 990.1 | 0.99 | 1.00 | 0.919 (-1.5) | 0.0490 (+0.8) | 0.481 (-2.0) | -0.088 (-1.5) | +0.042 (+0.2) | 3 |
| DEX 600 UP | 1,614 | 185.9 | 0.31 | **2.29** | 0.955 (-1.7) | 0.0353 (**+3.4**) | 0.887 (-0.9) | -0.022 (-0.8) | +0.012 (+0.2) | 1 |
| DEX 600 DOWN | 1,567 | 191.4 | 0.32 | **2.21** | 1.030 (+1.4) | 0.0158 (-0.6) | 1.120 (+1.2) | +0.008 (+0.4) | -0.020 (-0.5) | 1 |
| DEX 900 DOWN | 945 | 317.5 | 0.35 | **2.52** | 1.060 (+2.0) | 0.0365 (+2.1) | 1.276 (+2.0) | +0.006 (+0.3) | -0.108 (-1.8) | 1 |
| DEX 900 UP | 931 | 322.2 | 0.36 | **2.40** | 1.026 (+1.0) | 0.0219 (-0.4) | 1.194 (+1.5) | -0.016 (-0.4) | -0.130 (-2.1) | 1 |
| DEX 1500 DOWN | 426 | 704.2 | 0.47 | **1.94** | 0.988 (-0.2) | 0.0235 (-1.3) | 0.800 (-0.9) | +0.012 (+0.4) | +0.119 (+1.4) | 2 |
| DEX 1500 UP | 424 | 707.5 | 0.47 | **1.76** | 0.959 (-0.8) | 0.0337 (-0.1) | 0.961 (-0.2) | -0.025 (-0.4) | +0.000 (+0.1) | 2 |
| Jump 10 | 214 | 1401.9 | 1.17 | **2.82** | 0.897 (-1.6) | 0.0553 (+0.5) | 0.908 (-0.3) | -0.095 (-1.3) | +0.160 (+1.1) | 9 |
| Jump 25 | 199 | 1507.5 | 1.26 | **2.82** | 1.092 (+1.6) | 0.0418 (-0.6) | 0.706 (-1.0) | -0.028 (-0.4) | +0.049 (+0.3) | 3 |
| Jump 50 | 200 | 1500.0 | 1.25 | **2.81** | 0.938 (-0.9) | 0.0453 (-0.4) | 0.827 (-0.6) | -0.077 (-1.1) | +0.179 (+1.2) | 14 |
| Jump 75 | 203 | 1477.8 | 1.23 | **3.01** | 1.026 (+0.5) | 0.0458 (-0.3) | 0.746 (-0.8) | -0.043 (-0.6) | -0.088 (-0.7) | 12 |
| Jump 100 | 216 | 1388.9 | 1.16 | **2.14** | 0.960 (-0.5) | 0.0459 (-0.2) | 0.900 (-0.4) | +0.025 (+0.3) | +0.040 (+0.2) | 3 |

The five statistics are the CV, a Kolmogorov-Smirnov distance against a
geometric fitted by its mean, the Fano factor of the spike count in windows of
ten mean waits, the lag-one correlation of consecutive gaps, and the slope of
the empirical hazard in equal-width bins of elapsed ticks. Each is compared to
200 replicates of a compound Poisson drawing its grind and its spikes from this
feed's own observed pools at this feed's own rate - **memoryless by
construction, marginals exact by construction** - put through the same detector.

**The largest `|z|` anywhere is 3.63, on 145 tests, against a two-sided
Bonferroni threshold of 4.16.** Six of 29 symbols reach `|z| > 2`, where six is
what 29 symbols of five tests produce by chance. The mean over symbols of each
symbol's worst statistic is 1.59.

**Three symbols reach `|z| > 3` where fewer than one is expected, and they are
reported rather than rounded off.** They are `Boom 500` (hazard slope -3.63),
`Boom 1000` (hazard slope +3.30, CV -3.17) and `DEX 600 UP` (KS +3.36). Two
things say this is noise rather than a finding. The two Boom slopes have
**opposite signs** - a real hazard shape would not reverse between two members of
one family built by one generator - and the DEX cell is on a feed where kill
condition 1 has already fired, its detected rate moving by a factor of 2.29
across thresholds, so its gap distribution is partly a property of the cut.
Neither clears the Bonferroni threshold and neither is claimed.

**The waiting time is memoryless, and now it is memoryless on a sample that
could have said otherwise.** `min_gap` is exactly 1 tick on 16 of 29 feeds, is 4
or less on 24 of them, and its largest value anywhere is 14 on Jump 50: there is
no refractory period, two spikes can land on consecutive ticks, and the last
shape of non-memorylessness a model could have traded is absent too.

Three things the wider sample adds that were not there before:

* **The number in a Boom or Crash name is the rate, on all eighteen feeds** -
  including the twelve never measured. `Boom 50` spikes every 55.7 ticks,
  `Crash 1000` every 990.1, and the pooled ratio to the name is 1.014 and 1.031.
* **The number in a Jump name is not the rate** and the published rate is
  optimistic. All five jump every 1,389 to 1,508 ticks - 23.1 to 25.1 minutes -
  against a documented twenty, which independently replicates
  [rebuilding.md](rebuilding.md)'s 22 to 27 minutes on a different sample.
* **The number in a DEX name is not the rate either, and kill condition 1 fires
  on DEX and on Jump.** The detected rate changes by a factor of 1.76 to 3.01
  across thresholds of 5x, 10x and 20x on those two families, against 1.00 to
  1.20 on Boom and Crash. On Boom the spike is two to three orders of
  magnitude larger than the grind - [generators.md](generators.md) measures 266x
  to 905x on three of these feeds - and the detector cannot miss; on Jump and DEX
  the large move is not separated from the small one by a gap, so a "rate" there is a property of the cut and not of the
  generator. **DEX 600 detects a spike every 186 ticks, DEX 900 every 320 and
  DEX 1500 every 706 - ratios to the name of 0.31, 0.35 and 0.47, not constant** -
  and the honest reading is that the number means something else. The CVs are
  still 0.955 to 1.060 whatever the cut, so the *memorylessness* survives even
  though the rate does not.

## Two: every Step-family name is exactly true, and the reading pre-registered for Skew Step was exactly backwards

200,000 to 250,000 ticks a symbol. The increment lives at tick scale - a
three-minute bar has already summed a hundred and eighty of them - so everything
here is a tick-to-tick bid move and no bar appears in this section.

**The base, as a positive control.** `Step Index`: 249,999 moves, zero unchanged
ticks, **one magnitude carrying 100.000%** of them at exactly 0.1,
`p(up) = 0.498710 +- 0.001000` with halves 0.49693 and 0.50049, sign acf outside
`+-3/sqrt(n)` at **0 of 30 lags**, Wald-Wolfowitz runs `z = -0.78`. That
reproduces tier 1 and it is the row that makes the rest of the table readable.
`Step Index 200` is the same object at exactly 0.2, `p(up) = 0.499566 +- 0.001000`.

**Multi Step `n` has exactly `n` step magnitudes. Three for three.**

| symbol | magnitudes and shares | `p(up)` | closure z |
|---|---|---|---|
| Multi Step 2 | 0.1 @ 94.91%, 0.5 @ 5.09% | 0.498702 +- 0.00100 | -0.20 |
| Multi Step 3 | 0.1 @ 94.98%, 0.5 @ 3.01%, 0.25 @ 2.01% | 0.500308 +- 0.00112 | -0.12 |
| Multi Step 4 | 0.1 @ 95.04%, 0.2 @ 2.00%, 0.3 @ 1.98%, 0.5 @ 0.98% | 0.498972 +- 0.00112 | -0.65 |

All three are symmetric to within 1.3 standard errors and their up and down
conditional means match to four significant figures.

**Skew Step, and the pre-registration that fired.** The name was read, before the
data was opened, as: the number `k` is the size ratio, the generator is a
martingale, so `p_up = 1/(1+k)` and `Skew Step Index 4 Up` should be an index
that rises rarely in large steps. The measurement:

| symbol | `p(up)` +- se | halves | `E[up]` | `E[down]` | size ratio | closure z |
|---|---|---|---|---|---|---|
| Skew Step 4 **Up** | **0.799944** +- 0.00089 | 0.80038, 0.79951 | +0.12507 | -0.50000 | 1 : 3.998 | **+0.04** |
| Skew Step 4 **Down** | 0.199346 +- 0.00089 | 0.19991, 0.19878 | +0.50000 | -0.12507 | 3.998 : 1 | -0.82 |
| Skew Step 5 **Up** | **0.899569** +- 0.00067 | 0.89961, 0.89953 | +0.11114 | -1.00000 | 1 : 8.998 | -0.60 |
| Skew Step 5 **Down** | 0.100991 +- 0.00067 | 0.10096, 0.10102 | +1.00000 | -0.11114 | 8.998 : 1 | +1.30 |

**The realised asymmetry matches the name, and the pre-registered reading of the
name was wrong in both of its two parts.** Wrong about the side: `4 Up` rises
*often* in small steps (80% of ticks, 0.12507) and falls *rarely* in large ones
(20%, 0.50000) - a Boom shape on a lattice, not the rare-large-up shape
predicted. And wrong about the number: the skew ratio is **4:1 on the "4" pair
and 9:1 on the "5" pair**, not 5:1, so `k` is not the ratio. It is instead the
**count of distinct step magnitudes**, the same convention Multi Step uses - the
"4" variants carry four magnitudes and `Skew Step Index 5 Up` carries five.
Two points do not determine the map from that count to the ratio and this page
does not invent one.

**What is exact is the closure.** In all four, `p_up / p_down` and
`E[down] / E[up]` agree to four significant figures - 3.999 against 3.998, and
8.957 against 8.998 - and `p_up * E[up] + p_down * E[down]` is zero within
`z = +0.04, -0.82, -0.60, +1.30`. **Kill condition 3 did not fire on any of the
four.** The skew is in the probability and in the size simultaneously and exactly
reciprocally, which is the only way an asymmetric lattice walk can be a
martingale. Sign autocorrelation is outside its band at 0, 0, 1 and 0 of 30 lags
and every runs `z` is inside `+-2.2`.

**So the Skew Step family is asymmetric and unforecastable at once**, and that is
not a contradiction: the asymmetry is entirely in the marginal, where a model
that learns it learns a constant, and there is nothing in the order.

## Three: the drift in Drift Switch is real, orders with the name, and is entirely linear

No page in this folder had ever measured this family. Three instruments, bars
from `seqlab.load` across the full grid plus 200,000 ticks each.

**The cheap statistic first, because it needs no model.** A variance ratio -
`Var(sum of k returns) / (k * Var(r))` - is 1.00 at every `k` for a martingale,
and a drift that persists and then flips makes it exceed 1 at horizons near the
dwell time. At 1h, on 26,643 bars:

| symbol | VR peak | at k | shuffled | phase surrogate |
|---|---|---|---|---|
| Drift Switch 10 | 1.070 | 20 | 1.022 | 1.049 |
| Drift Switch 20 | 1.327 | 100 | 0.989 | 1.298 |
| Drift Switch 30 | 1.201 | 20 | 0.957 | 1.162 |

**Kill condition 4 did not fire** - the shuffle sits at 0.96 to 1.02 where it
should, so the estimator is not reading its own overlap. The process is
super-diffusive and the switching is real.

**And the phase surrogate reproduces almost all of it.** A surrogate keeps the
power spectrum and the entire linear autocorrelation and destroys every nonlinear
dependence; at 1.298 against 1.327 it has kept 96% of the effect. **Whatever is
there is linear.** That is the single most consequential control on this page and
it is what section seven's model result is made of.

**The hidden-state model, and the statistic that had to be replaced.** A
two-state and a three-state Gaussian HMM were fitted by EM, and the first version
of this arm reported the mean dwell time `1/(1 - p_ii)`. On *shuffled* returns -
independent by construction, no regime left at all - the three-state fit came
back with dwells of `[1.6, 7.5, 1.9]`. That is not a bug in the shuffle. On
i.i.d. data the likelihood is maximised by transition rows equal to the
stationary weights, so a state holding 87% of the mass has `p_ii = 0.87` and a
"dwell" of 7.7 with precisely zero persistence. **Reading that 7.5 as a dwell
time would have been this page's headline and it would have been an artefact of
the state weight.** The statistic reported instead is
`persist[i] = p_ii / pi_i`, the ratio to that i.i.d. baseline, which is 1.00 for
a memoryless mixture.

| symbol, 1h | `sep` real | `sep` shuffle | `sep` surrogate | hmm2 persist real | hmm2 persist shuffle |
|---|---|---|---|---|---|
| Drift Switch 10 | 0.33 | 0.10 | 0.31 | [1.70, 1.61] | [1.65, 1.77] |
| Drift Switch 20 | 0.62 | 0.13 | 0.49 | [1.45, 1.67] | [1.68, 1.75] |
| Drift Switch 30 | 1.75 | 0.30 | 0.84 | [1.13, 1.34] | [1.51, 1.79] |

`sep` is the spread of fitted drifts over the mean fitted sigma, and it does
separate real from shuffled, 0.33/0.62/1.75 against 0.10/0.13/0.30. **The
persistence does not separate at all** - on all three instruments the shuffle
reports *more* persistence than the feed. **Kill condition 5 fired on the
three-state fit** and fired hardest on Drift Switch 10, where the shuffle's
persistence is `[17.6, 1.05, 14.2]` against the feed's `[5.26, 1.16, 6.16]`.
The three-state fit is a Gaussian mixture with a transition matrix attached and
it is not used anywhere else on this page.

**The name orders the strength.** Every statistic is monotone in the number:
lag-one autocorrelation at 1h `+0.0352`, `+0.0613`, `+0.0986`; `sep` 0.33, 0.62,
1.75; and on the positive control - a simulation at the fitted parameters where
the true regime path is known - the causal filter's correlation with the true
drift is 0.227, 0.346, 0.687 and its AUC on the next bar's sign is 0.5143,
0.5275, 0.5506. **`Drift Switch Index 30` is the strongest of the three**, and
0.5506 is what the filter can reach at 1h on a process built to be readable.
Section seven runs the same comparison at 15m, where the autocorrelation is twice
as large, and the same ceiling is 0.6069.

## Four: Range Break is a detector check and nothing else

[deriving.md](deriving.md) has the break arrival at 86.6 and 178.9 minutes with
CV 1.003 and 1.075 over **998 and 483 breaks and sixty days**, and
[quantising.md](quantising.md) has the relaxation ladder. Thirty-three hours of
ticks cannot improve on either and re-running them here would put a second value
for one quantity in the folder, which is how this folder has gone wrong before.

The same detector used in section one, run on 120,000 ticks a side:

| symbol | breaks | ticks per break | minutes per break | published (60 days) | unit-move fraction |
|---|---|---|---|---|---|
| Range Break 100 | 30 | 4,000 | 66.7 | 86.6 | 0.9997 |
| Range Break 200 | 14 | 8,571 | 142.9 | 178.9 | 0.9999 |

**The ratio replicates and the level does not.** 142.9 / 66.7 = 2.14 against the
published 2.066 and a documented 2.000; the absolute rates are 23% and 20% low on
counts of 30 and 14, which is what a thirty-break sample does to a Poisson rate.
`deriving.md`'s numbers stand and these do not compete with them. What the row
does establish is that this file's detector finds the right object on a feed
where the right answer is known, which is the only reason it is here.

**And the premise of this section turned out to be wrong, which is left standing
rather than edited away.** "Already measured" was true of the break arrival and
the relaxation ladder; it was not true of the conditional direction, and nobody
had looked. The pooled direction table in section seven returns **AUC 0.6627** on
these two symbols at 15m with a shuffle at 0.4961 and a surrogate at 0.4956 - the
largest direction number in the study, on the family this page had decided not to
study. The finding is written up there and its consequence for the ranking is at
the end. This section is left as it was written because the reasoning in it is
still correct and the conclusion it licensed was still wrong: two settled
quantities do not make a third one settled.

## Five: the lag-one autocorrelation, which is the whole result

This section was not in the plan. It was added after a smoke run turned up a
`+0.132` on `Drift Switch Index 30`, and it is recorded that way rather than
presented as a design.

The statistic is the lag-one autocorrelation of bar log returns, on every symbol
at all eight timeframes in `seqlab.GRID`, with both halves, a Ljung-Box `Q` over
ten lags, a shuffle, a phase surrogate, and - on the same rows - eleven control
symbols.

**Mean `acf1` over the family's symbols, and the largest `|t|` in the cell:**

| family | 3m | 15m | 1h | 4h | 6h | 8h | 12h | 1d |
|---|---|---|---|---|---|---|---|---|
| **drift_switch** | +0.0715 / **+28.5** | +0.1349 / **+34.1** | +0.0650 / **+16.1** | +0.0094 / +1.1 | +0.0025 / +1.2 | +0.0011 / +0.4 | +0.0181 / +1.1 | +0.0134 / +2.0 |
| boom | -0.0013 / -2.0 | -0.0004 / +1.5 | -0.0030 / -1.4 | +0.0073 / -1.4 | -0.0050 / -1.1 | -0.0117 / -1.5 | +0.0106 / +1.8 | +0.0067 / -2.3 |
| crash | +0.0042 / +2.2 | +0.0012 / -2.4 | +0.0001 / -1.4 | +0.0034 / -2.0 | -0.0027 / -2.9 | -0.0018 / -2.0 | +0.0078 / +1.9 | +0.0196 / +2.8 |
| dex | -0.0007 / -1.7 | +0.0011 / +2.4 | +0.0017 / +2.8 | +0.0039 / +1.3 | +0.0020 / +1.9 | -0.0022 / -2.1 | +0.0019 / -1.7 | -0.0080 / -2.3 |
| jump | +0.0002 / +2.6 | -0.0005 / -0.9 | +0.0011 / -1.3 | -0.0002 / -2.3 | +0.0008 / -2.7 | -0.0071 / -2.1 | -0.0053 / -2.1 | +0.0082 / +1.7 |
| step | +0.0016 / +1.8 | +0.0036 / +2.6 | -0.0038 / +1.7 | +0.0011 / +1.4 | -0.0079 / -2.0 | -0.0005 / -1.9 | -0.0033 / -3.0 | -0.0072 / -1.4 |
| range_break | +0.0005 / +0.5 | +0.0008 / +0.8 | +0.0013 / +0.5 | -0.0115 / -2.1 | -0.0090 / -1.7 | -0.0121 / -2.2 | -0.0033 / -0.3 | +0.0143 / +1.7 |
| *controls* | -0.0097 / -3.8 | -0.0074 / -5.2 | -0.0102 / -4.5 | +0.0062 / +3.7 | +0.0032 / +4.5 | +0.0137 / +4.4 | +0.0193 / +5.0 | +0.0057 / +1.5 |

**Drift Switch is the only synthetic family anywhere on the grid with a `|t|`
above 3.0, and it is at 34.1.** Every other family sits at or below the real
markets, whose largest `|t|` is 5.2 on EURUSD at 15m and is the bid-ask bounce.
`Step Index` reads `-0.0003` at 15m (`t = -0.1`) and `Volatility 75 Index` reads
`+0.0009` (`t = +0.2`), which is what a verified fair coin and a geometric
Brownian motion are supposed to read and is the reason the `+0.1349` above them
can be believed.

**The cost sweep. This is the table the page is for.** `cost` is the median
relative bid-ask spread measured from the same ticks. The rule is walk-forward:
fit `beta` on the training block, take `w = sign(beta * r_t)` on the test block,
charge `(cost/2) * turnover`. `be/cost` is the spread at which the rule would
break even, divided by the spread the broker quotes. `thr` is the same rule with
a stand-aside threshold chosen on the **training** block by net-after-cost.

| symbol | tf | n | acf1 | t | cost/sigma | hit | gross | turnover | net | be/cost | thr be/cost |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Drift Switch 10 | 3m | 49,999 | +0.1273 | +28.5 | 1.182 | **0.6314** | +9.66e-05 | 0.734 | **-2.33e-04** | 0.293 | 0.120 |
| Drift Switch 10 | 15m | 49,999 | +0.1204 | +26.9 | 0.450 | 0.5404 | +1.90e-04 | 0.918 | -2.22e-04 | 0.460 | 0.439 |
| Drift Switch 10 | 1h | 26,642 | +0.0352 | +5.8 | 0.205 | 0.5068 | +1.13e-04 | 0.986 | -3.30e-04 | 0.255 | 0.535 |
| Drift Switch 20 | 3m | 49,999 | +0.0606 | +13.5 | 1.673 | 0.6120 | +5.69e-05 | 0.771 | -3.55e-04 | 0.138 | 0.000 |
| **Drift Switch 20** | **15m** | 49,999 | **+0.1525** | **+34.1** | 0.675 | 0.5691 | +2.07e-04 | 0.860 | **-2.52e-04** | **0.451** | 0.233 |
| Drift Switch 20 | 1h | 26,642 | +0.0613 | +10.0 | 0.296 | 0.5172 | +1.45e-04 | 0.965 | -3.71e-04 | 0.281 | 0.448 |
| Drift Switch 30 | 3m | 49,999 | +0.0267 | +6.0 | 1.318 | 0.5594 | +2.91e-05 | 0.879 | -2.54e-04 | 0.103 | -0.071 |
| Drift Switch 30 | 15m | 49,999 | +0.1317 | +29.4 | 0.551 | 0.5869 | +1.40e-04 | 0.825 | -1.26e-04 | 0.526 | 0.298 |
| **Drift Switch 30** | **1h** | 26,642 | +0.0986 | +16.1 | 0.243 | 0.5325 | +2.08e-04 | 0.935 | -9.26e-05 | 0.692 | **0.884** |

**In every one of the nine cells where the autocorrelation is real - `|t| > 5.8`
on 26,642 to 49,999 bars - the breakeven spread is between 0.103 and 0.692 of the
quoted spread and the net is negative.** The best number the threshold rule
reaches anywhere is 0.884, on Drift Switch 30 at 1h, and its net is still
`-4.2e-06`.

Two cells in the full sweep do report `be/cost` above 1 - Drift Switch 10 at 12h
(1.126) and Drift Switch 20 at 1d (1.046) - and one comes close, Drift Switch 30
at 12h (0.963). **All three have `|t| <= 2.0` and `n <= 2,219`**, which is to say
no measurable autocorrelation and a few hundred test rows; two of the three have
a *negative* net under the threshold rule on the same data. They are noise and
they are listed here so that they are on the page rather than available to be
found later by someone scanning the sweep for a number above one.

**The mechanism, which is why no timeframe works.** Read the `cost/sigma` column
down. The spread is fixed in price terms, so as the bar gets longer the spread
falls relative to one bar's volatility: on Drift Switch 10 it is 1.182 of a bar's
sigma at 3m, 0.450 at 15m, 0.205 at 1h, 0.100 at 4h, 0.041 at 1d. Cost is
therefore no obstacle at all at four hours and above. But the autocorrelation
falls faster: `+0.1273`, `+0.1204`, `+0.0352`, `+0.0067`, and it is gone by 4h.
**The signal lives at 3m to 1h and the cost advantage lives at 4h and above, and
they do not overlap.** The regime is too short to hold through a bar long enough
to pay for the crossing. That is not a statement about this rule; it is a
property of the instrument, and any rule reading this autocorrelation meets it.

## Six: it is in the generator, not in the bars

The cheapest discriminator available, and it costs one cached read. If a
bar-scale autocorrelation were an artefact of how bars are cut, of a stale quote,
or of a mid that moves when a spread changes, it would be **in the ticks**. If it
is a slow drift, it is **not** in the ticks - at one tick the drift is negligible
against the diffusion, and it only emerges as the bar aggregates.

| family | symbols | tick `acf1` on the bid | se | max abs t |
|---|---|---|---|---|
| drift_switch | 3 | **-0.00429** | 0.00224 | 2.91 |
| boom | 9 | -0.00085 | 0.00183 | 1.56 |
| crash | 9 | -0.00104 | 0.00183 | 1.25 |
| dex | 6 | +0.00034 | 0.00183 | 1.63 |
| jump | 5 | -0.00082 | 0.00183 | 3.89 |
| step | 9 | -0.00160 | 0.00216 | 2.12 |
| range_break | 2 | -0.00479 | 0.00289 | 2.33 |

On 200,000 ticks a symbol, Drift Switch's lag-one tick autocorrelation is
`-0.0034`, `-0.0065` and `-0.0029` against a standard error of 0.00224, and lags
two to five are inside the same band. **Zero at the tick, `+0.15` at fifteen
minutes.** That is the signature of a drift and it is not the signature of any
artefact of bar construction, which would be largest at the finest resolution and
would wash out with aggregation rather than build up.

## Seven: the model arm, where a recurrent net finds nothing a straight line had not

Three targets, four control arms on every cell, `seqlab.gbm_bars` used nowhere -
it is the right null for a Volatility index and the wrong null for every symbol
here, and a model that separates Boom from a Brownian motion has identified the
simulator.

### `spike_next`, the family target, which has an exact analytic floor

If the hazard is memoryless at per-tick probability `p`, then for a bar of
exactly `m` ticks

    P(spike in the next bar | anything at all) = 1 - (1 - p)^m

is a **constant**, and a constant score has rank AUC exactly 0.500. **So on a
memoryless generator the Bayes-optimal classifier scores 0.500 and any AUC above
it is either non-memorylessness or a leak, with no third option and no baseline
to argue about.** That statement only holds on a bar of exactly `m` ticks, which
is why this target runs on tick bars.

**The wall clock would have manufactured a result.** On a three-minute bar the
tick count varies, a bar with more ticks is more likely to contain a spike for a
reason that has nothing to do with the hazard, and `logvolume` is in
`seqlab.NAMES`. Tick bars remove the confound by construction because every bar
carries the same `m`. The bar is sized to a third of the mean wait, floored so
that at least 4,000 bars survive.

**And the wall clock destroys the object outright at the top of the grid.**
Expected spikes per bar on `Boom 500`:

| 3m | 15m | 1h | 4h | 6h | 8h | 12h | 1d |
|---|---|---|---|---|---|---|---|
| 0.36 | 1.80 | 7.21 | 28.85 | 43.27 | 57.70 | 86.54 | **173.09** |

At one day the answer to "will a spike happen in the next bar" is yes, 173 times
over. The classifier would be scoring a constant label and its AUC would be
undefined or trivially 0.500 for the wrong reason. **Kill condition 6 fires on
every timeframe from 15m upward for Boom 500, and on 3m as well for the fast
members** - `Boom 50` puts 3.2 spikes in a three-minute bar. Nothing in this
section is taken from the wall clock, and that is the honest version of "which
timeframe" for this family.

### `direction` and `logvol` on wall-clock bars

The direction arm is a null calibration and it comes back as one. One caveat the
family forces: **on Boom and Crash the base rate is not one half.** Over 200,000
`Boom 500` ticks, 0.18% of moves are up and 0.04% are unchanged, so 99.78% are
down and a bar's sign is very nearly a statement about whether a spike landed.
This page reports AUC and never accuracy.

The volatility arm's interesting quantity is not the model score but the
**naive-versus-mean gap**, which `seqlab.py`'s docstring names as a
generator-identification statistic: where conditional variance is constant the
unconditional mean beats the last realised value, and where variance clusters the
last value wins.

### What the models scored

**`spike_next`, on tick bars, where the floor is analytically 0.500.** All 29
feeds. `per` is ticks per bar - a third of that feed's measured wait, floored so
at least 4,000 bars survive - and `null` is that feed's own memoryless compound
Poisson through the identical pipeline, 24 replicates.

| symbol | per | rows | base | logistic | null | z | no-hazard | GRU | shuffle |
|---|---|---|---|---|---|---|---|---|---|
| Boom 50 | 19 | 15,767 | 0.290 | 0.5106 | 0.5030 +- 0.0066 | +1.15 | 0.5123 | 0.5112 | 0.4990 |
| Boom 100 | 34 | 8,801 | 0.284 | 0.5029 | 0.5023 +- 0.0077 | +0.08 | 0.5031 | 0.5052 | 0.5028 |
| Boom 150 | 55 | 5,432 | 0.286 | 0.5076 | 0.4997 +- 0.0103 | +0.76 | 0.5119 | 0.4923 | 0.5063 |
| Boom 200 | 71 | 4,203 | 0.290 | 0.4773 | 0.5045 +- 0.0132 | -2.05 | 0.4818 | 0.4855 | 0.5017 |
| Boom 300 | 75 | 3,978 | 0.234 | 0.5321 | 0.5033 +- 0.0139 | +2.07 | 0.5320 | 0.4752 | 0.5068 |
| Boom 500 | 75 | 3,978 | 0.138 | 0.4776 | 0.4969 +- 0.0140 | -1.38 | 0.4814 | 0.4982 | 0.4832 |
| Boom 600 | 75 | 3,978 | 0.117 | 0.4822 | 0.4979 +- 0.0162 | -0.97 | 0.4819 | 0.4920 | 0.4763 |
| Boom 900 | 75 | 3,978 | 0.084 | 0.4838 | 0.5044 +- 0.0165 | -1.25 | 0.4817 | 0.5251 | 0.5153 |
| Boom 1000 | 75 | 3,978 | 0.082 | 0.5319 | 0.5040 +- 0.0152 | +1.84 | 0.5234 | 0.5937 | 0.4908 |
| Crash 50 | 18 | 16,644 | 0.283 | 0.4898 | 0.5012 +- 0.0044 | **-2.63** | 0.4878 | 0.4926 | 0.5039 |
| Crash 100 | 35 | 8,549 | 0.284 | 0.5033 | 0.5052 +- 0.0074 | -0.26 | 0.5028 | 0.4970 | 0.4874 |
| Crash 150 | 50 | 5,978 | 0.283 | 0.4983 | 0.4989 +- 0.0077 | -0.07 | 0.4981 | 0.4853 | 0.4894 |
| Crash 200 | 67 | 4,455 | 0.282 | 0.4887 | 0.5064 +- 0.0116 | -1.52 | 0.4849 | 0.4959 | 0.4826 |
| Crash 300 | 75 | 3,978 | 0.215 | 0.5030 | 0.4990 +- 0.0134 | +0.30 | 0.5024 | 0.4850 | 0.4760 |
| Crash 500 | 75 | 3,978 | 0.136 | 0.4997 | 0.5045 +- 0.0137 | -0.35 | 0.5039 | 0.4713 | 0.5090 |
| Crash 600 | 75 | 3,978 | 0.115 | 0.5255 | 0.5066 +- 0.0106 | +1.78 | 0.5190 | 0.4787 | 0.4488 |
| Crash 900 | 75 | 3,978 | 0.077 | 0.5001 | 0.5036 +- 0.0183 | -0.19 | 0.5023 | 0.4889 | 0.4848 |
| Crash 1000 | 75 | 3,978 | 0.072 | 0.4997 | 0.5020 +- 0.0216 | -0.11 | 0.5004 | 0.4954 | 0.4943 |
| DEX 600 UP | 62 | 4,816 | 0.291 | 0.4956 | 0.4984 +- 0.0100 | -0.28 | 0.4971 | 0.5045 | 0.4742 |
| DEX 600 DOWN | 64 | 4,665 | 0.285 | 0.5022 | 0.5026 +- 0.0146 | -0.02 | 0.5036 | 0.4905 | 0.4991 |
| DEX 900 DOWN | 75 | 3,978 | 0.209 | 0.5058 | 0.4984 +- 0.0138 | +0.54 | 0.4984 | 0.5167 | 0.5000 |
| DEX 900 UP | 75 | 3,978 | 0.208 | 0.4858 | 0.5019 +- 0.0168 | -0.96 | 0.4861 | 0.5025 | 0.4890 |
| DEX 1500 DOWN | 75 | 3,978 | 0.101 | 0.5278 | 0.5049 +- 0.0116 | +1.96 | 0.5306 | 0.4873 | 0.4848 |
| DEX 1500 UP | 75 | 3,978 | 0.101 | 0.4961 | 0.5055 +- 0.0172 | -0.55 | 0.4963 | 0.4818 | 0.5203 |
| Jump 10 | 75 | 3,978 | 0.053 | 0.5226 | 0.5028 +- 0.0200 | +1.00 | 0.5126 | 0.5083 | 0.5150 |
| Jump 25 | 75 | 3,978 | 0.048 | 0.4946 | 0.5135 +- 0.0443 | -0.43 | 0.4936 | 0.5284 | 0.4919 |
| Jump 50 | 75 | 3,978 | 0.050 | 0.5338 | 0.5048 +- 0.0219 | +1.32 | 0.5345 | 0.4767 | 0.5015 |
| Jump 75 | 75 | 3,978 | 0.050 | 0.4557 | 0.4976 +- 0.0250 | -1.68 | 0.4622 | 0.4461 | 0.4986 |
| Jump 100 | 75 | 3,978 | 0.052 | 0.4891 | 0.4999 +- 0.0298 | -0.36 | 0.4921 | 0.5434 | 0.4945 |

**Max `|z|` over 29 cells is 2.63, three exceed 2, and nothing is claimed.** The
null column is the check on the harness and it passes: all 29 memoryless
simulations return a mean in [0.4969, 0.5135], centred on the analytic 0.500 that
`1 - (1-p)^m` requires. **Kill condition 2 holds a second time**, on arithmetic
with nothing in common with section one's.

**The `no-hazard` column is the memorylessness restated through a model.** It is
the identical logistic with the ticks-since-last-spike columns deleted, and it
tracks the full model to the third decimal nearly everywhere - Boom 300 reads
0.5320 against 0.5321, Crash 500 0.5039 against 0.4997. **The one feature a
non-memoryless hazard would have made valuable is worth nothing on any of the 29
feeds.** Section one says that with five statistics against a simulated null;
this says it with a model that was free to use the feature and declined.

**The GRU adds nothing either** - above the logistic on 12 of 29, below on 17,
and its wider spread (0.4461 to 0.5937) is the recurrent budget's smaller
training set rather than a signal.

Two honest caveats. **The five Jump rows sit at base rates of 0.048 to 0.053**,
on kill condition 6's floor, so they carry the least power here - their null
standard deviations, 0.0200 to 0.0443, are three to ten times Boom 50's. And
**`per` is capped at 75 ticks on the eighteen slower feeds** by the 4,000-bar
floor, so their labels land at base rates of 0.05 to 0.14 where the fast feeds
get 0.28. Both follow from a 300,000-tick sample and both are visible in the
table rather than buried in a pooled mean.

**`direction` and `logvol` on wall-clock bars, pooled by family.** `gap` is
`naive_srel - mean_srel`, the generator-identification statistic.

| family | tf | n | base | logistic | shuffle | surrogate | momentum | HMM | naive | mean | gap | HAR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **drift_switch** | 15m | 3 | 0.5347 | **0.5973** | 0.4997 | 0.5595 | 0.5740 | 0.5924 | 0.8180 | 0.6381 | 0.1799 | 0.6890 |
| **drift_switch** | 1h | 3 | 0.5003 | 0.5356 | 0.4992 | 0.5224 | 0.5189 | 0.5268 | 0.8677 | 0.6622 | 0.2054 | 0.7070 |
| drift_switch | 4h | 3 | 0.4927 | 0.4998 | 0.5017 | 0.4969 | 0.4974 | 0.5026 | 0.8798 | 0.6661 | 0.2137 | 0.7039 |
| drift_switch | 1d | 3 | 0.4770 | 0.5158 | 0.4852 | 0.4828 | 0.5002 | 0.4980 | 0.8896 | 0.6776 | 0.2119 | 0.7163 |
| boom | 15m | 9 | 0.4371 | 0.5000 | 0.4989 | 0.5015 | 0.4992 | - | 0.8275 | 0.6053 | 0.2222 | 0.6619 |
| boom | 1h | 9 | 0.4687 | 0.5018 | 0.4957 | 0.5002 | 0.4989 | - | 0.8750 | 0.6605 | 0.2144 | 0.6994 |
| boom | 4h | 9 | 0.4821 | 0.4952 | 0.4984 | 0.5050 | 0.4956 | - | 0.8758 | 0.6607 | 0.2150 | 0.7010 |
| boom | 1d | 5 | 0.4897 | 0.5089 | 0.4965 | 0.4890 | 0.4966 | - | 0.8802 | 0.6658 | 0.2144 | 0.6988 |
| crash | 15m | 9 | 0.5613 | 0.5008 | 0.4998 | 0.4995 | 0.5001 | - | 0.8267 | 0.6040 | 0.2227 | 0.6593 |
| crash | 1h | 9 | 0.5296 | 0.5032 | 0.5029 | 0.4944 | 0.4975 | - | 0.8748 | 0.6607 | 0.2141 | 0.7019 |
| crash | 4h | 9 | 0.5149 | 0.5019 | 0.4949 | 0.5126 | 0.4966 | - | 0.8839 | 0.6659 | 0.2180 | 0.7018 |
| crash | 1d | 5 | 0.5029 | 0.5095 | 0.5107 | 0.5138 | 0.4818 | - | 0.8790 | 0.6715 | 0.2075 | 0.7116 |
| step | 15m | 9 | 0.4952 | 0.5004 | 0.4998 | 0.5019 | 0.5019 | - | 0.8840 | 0.6699 | 0.2140 | 0.7487 |
| step | 1h | 9 | 0.4989 | 0.4991 | 0.4977 | 0.5011 | 0.4996 | - | 0.8835 | 0.6711 | 0.2124 | 0.7241 |
| step | 4h | 9 | 0.5028 | 0.4983 | 0.4998 | 0.5023 | 0.4956 | - | 0.8913 | 0.6754 | 0.2158 | 0.7166 |
| step | 1d | 8 | 0.5075 | 0.5008 | 0.5196 | 0.4956 | 0.4853 | - | 0.8876 | 0.6783 | 0.2094 | 0.7245 |
| **range_break** | 15m | 2 | 0.4769 | **0.6627** | 0.4961 | 0.4956 | **0.3863** | - | 1.0366 | 0.9651 | **0.0715** | 0.9609 |
| **range_break** | 1h | 2 | 0.4853 | **0.6047** | 0.4990 | 0.5025 | 0.4442 | - | 1.1181 | 1.0558 | **0.0623** | 0.9856 |
| range_break | 4h | 2 | 0.4979 | 0.5188 | 0.4940 | 0.4982 | 0.4866 | - | 1.0137 | 0.8407 | 0.1730 | 0.9033 |
| range_break | 1d | 2 | 0.5009 | 0.4978 | 0.4952 | 0.5107 | 0.4956 | - | 0.8946 | 0.7102 | 0.1844 | 0.7339 |

**Boom, Crash and Step are null on direction at every timeframe** - sixteen rows
covering 116 symbol-timeframe cells, every logistic between 0.4952 and 0.5095,
every control alongside it. **Two families are not**, and they are the subject of
section five and of the subsection below.

**The naive-versus-mean gap is `+0.21 +- 0.01` on every compound-Poisson and
lattice family** - boom 0.2144 to 0.2222, crash 0.2075 to 0.2227, step 0.2094 to
0.2158, across four timeframes each. The unconditional mean beats the last
realised value by a fifth of the score. **That is the signature of a constant
conditional variance**: there is no clustering to lean on, so the last bar's
realised value is noise around a constant and the mean is the better estimate. It
is the opposite of what a real market gives, and it is `seqlab.py`'s
generator-identification statistic returning a clean identification on every
family whose generator is known to be clean.

**And the two families that are not null on direction are the two where that gap
collapses.** Range Break reads `+0.0715` and `+0.0623` at 15m and 1h - a third of
everyone else's - and Drift Switch reads `+0.1799` at 15m against its own
`+0.2137` at 4h. In both, the gap shrinks at exactly the timeframes where the
direction AUC rises. **Conditional variance and conditional mean are carried by
the same structure**, which is what a reflecting band and a switching drift both
predict and what a compound Poisson does not. It is also the cleanest vindication
on this page of the distinction it is built on: the same object that makes the
direction forecastable makes the *variance* forecastable, and only the second is
something `deriving.md`'s theorem was ever silent about.

One number there is a sample statistic and not a generator property: **`crash`
shows a base rate of 0.5613 at 15m and `boom` 0.4371.** That is the one-sided
grind, not a forecastable edge, and it is exactly why every score on this page is
an AUC and never an accuracy.

### The largest direction AUC in the book is Range Break's, and it was not what this page went looking for

The pooled direction table turned up something section four had explicitly
declined to look for. On the two Range Break symbols, walk-forward, with the
shuffle and the phase surrogate on identical rows:

| family | tf | symbols | base rate | logistic | shuffle | surrogate | momentum 22 |
|---|---|---|---|---|---|---|---|
| **range_break** | **15m** | 2 | 0.4769 | **0.6627** | 0.4961 | 0.4956 | **0.3863** |
| **range_break** | 1h | 2 | 0.4853 | **0.6047** | 0.4990 | 0.5025 | 0.4442 |
| range_break | 4h | 2 | 0.4979 | 0.5188 | 0.4940 | 0.4982 | 0.4866 |
| range_break | 1d | 2 | 0.5009 | 0.4978 | 0.4952 | 0.5107 | 0.4956 |
| step | 15m | 9 | 0.4952 | 0.5004 | 0.4998 | 0.5019 | 0.5019 |
| step | 1h | 9 | 0.4989 | 0.4991 | 0.4977 | 0.5011 | 0.4996 |
| step | 4h | 9 | 0.5028 | 0.4983 | 0.4998 | 0.5023 | 0.4956 |
| step | 1d | 8 | 0.5075 | 0.5008 | 0.5196 | 0.4956 | 0.4853 |

**0.6627 is the largest out-of-sample direction AUC anywhere in this study**, and
it is not the family the page was built around. Four things about it.

**The controls are clean and the decay is monotone.** Shuffle and surrogate sit
at 0.494 to 0.520 in every Range Break cell, and the effect falls 0.663, 0.605,
0.519, 0.498 across the four timeframes - a shape, not a spike in one cell. The
Step rows directly beneath are the negative control read at the same moment: nine
symbols, four timeframes, every single number inside [0.498, 0.508].

**The mechanism is in the momentum column, and it is mean reversion.** `runlen`
scores **0.3863** at 15m - *below* 0.500, so a run of same-signed bars predicts a
reversal. That is precisely what a reflecting geometry does, and it is what
[deriving.md](deriving.md) already measured from the other side: the process
between breaks is **sub-diffusive by a factor of 3.6 on RB100 and 8.9 on RB200**.

**It is invisible to everything section five measures.** Range Break's lag-one
autocorrelation is `+0.0008` at 15m with `t = +0.8`, and the phase surrogate -
which keeps the entire linear autocorrelation - scores 0.4956. **The structure is
conditional on where the price sits in its band, not on the sign of the last
bar**, so a correlation and a spectrum both miss it completely. That is the one
place in this study where the cheap statistic would have said "nothing" and been
wrong, and it is worth recording as such.

**And it is already known to be untradeable, by a page that tested it properly.**
`deriving.md` ran the fade: RB100 gives `+0.114` gross at ten ticks against a
spread of `1.000` - **eleven percent of its cost** - and its own shuffle returns
`+0.298`, larger than the real thing. Its ex-break fade screen is 46 + 44 cells
with **zero survivors**, against a `step_index` control that admits one of 47.

**This page did not design an arm for this and does not claim one.** The number
fell out of a pooled table built for a different purpose, it rests on two
symbols, and it has had none of the treatment section five gave Drift Switch - no
cost sweep, no tick-scale check, no simulated null of a reflecting band. What it
has is a clean shuffle, a clean surrogate, a monotone decay, a named mechanism
and a prior page that independently reached the same conclusion from the variance
side. It is listed in `What follows` as the measurement this study most obviously
owes next, and the ranking below places it on the evidence rather than on the
effort that produced it.

## The ranking, which is what this arm was commissioned to produce

Seven families, ordered by how much structure a sequence model actually finds,
with the control that makes each number readable and - separately, because they
are separate claims - whether any of it survives the spread.

Ranked on the measured statistic rather than on the effort that produced it,
which moves one family a long way and is the honest order.

| rank | family | n | the structure that is there | strongest statistic | control | tradeable after costs |
|---|---|---|---|---|---|---|
| **1** | **range_break** | 2 | **a reflecting band.** Mean reversion conditional on position in the range - invisible to a correlation and to a spectrum | direction **AUC 0.6627** at 15m, the largest in the study; momentum **0.3863**, i.e. reversal | shuffle 0.4961, surrogate 0.4956, monotone decay to 0.4978 by 1d; Step at 0.5004 on the same table | **no.** [deriving.md](deriving.md): gross is **11% of the spread**, its own shuffle scores higher, 0 survivors in 90 fade cells |
| **2** | **drift_switch** | 3 | **a genuinely non-martingale drift.** `E[r_{t+1} \| r_t] != 0`, super-diffusive, regime inferrable in real time | `acf1 = +0.1525`, `t = +34.1`, n = 49,999; HMM filter **AUC 0.619** at 15m | shuffle `-0.0030` and 27 of 27 model shuffles in [0.485, 0.507]; tick-scale `acf1 = -0.0065 +- 0.0022`; drift-free null returns 0.483 to 0.499 | **no.** Best breakeven **0.884** of the quoted spread; net negative in all 9 significant cells |
| **3** | **step** (Skew and Multi) | 9 | **a large, exact asymmetry in the marginal.** `p(up) = 0.7999` and `0.8996`; two to five step magnitudes | `p_up` **337 and 596 se** from 0.5; size ratio 3.998 and 8.998 | closure `z` inside `+-1.3` on all four Skew; sign acf outside band 0, 0, 1, 0 of 30 lags; direction AUC 0.4983 to 0.5008 on 35 cells | **no**, and not for a cost reason - it is all marginal. Nothing whatever in the order |
| **4** | **boom / crash** | 18 | **a rate, exact to the name.** Nothing else | rate / name `1.014` and `1.031` over 18 feeds | 200-replicate compound Poisson at the feed's own pools; max `\|z\|` 3.63 on 145 tests vs Bonferroni 4.16 | **no.** Hazard memoryless, so the analytic AUC floor is 0.500 and it is where the models land |
| **5** | **jump** | 5 | **a rate, 16% to 26% slower than published**, and a jump not cleanly separable from the diffusion | 1,389 to 1,508 ticks per jump vs a documented 1,200 | kill condition 1 **fires**: rate moves 2.14x to 3.01x across thresholds | **no.** Waiting time memoryless, max `\|z\|` 1.62 |
| **6** | **dex** | 6 | **a compound-Poisson shape whose published number is not its rate** | rate / name `0.31`, `0.35`, `0.47` on 600, 900 and 1500 - not constant | kill condition 1 **fires**: rate moves 1.76x to 2.52x across thresholds | **no.** CV 0.955 to 1.060 whatever the cut |
| - | *Volatility (five sibling arms)* | 22 | *nothing, by construction* | - | - | *no, and the theorem proves it* |

Three things about the order, and the first is that **it is not the order this
page expected**. Range Break was scheduled as a replication, ranked last, and
explicitly not given an arm on the grounds that two prior pages had settled it.
It then returned the largest direction AUC in the study from a table built for
something else. The lesson is narrow and worth keeping: **the two prior pages had
settled the break arrival and the relaxation spectrum, and neither of those is
the conditional direction.** "Already measured" was true of the quantities that
had been measured, and the inventory at the top of this page could not have told
the difference.

**Second, the top two are structure of completely different kinds, and only one
of them is a martingale violation.** Drift Switch's increments have
`E[r_{t+1} | r_t] != 0` - the theorem's first assumption fails outright. Range
Break's conditional mean depends on *position in the band* rather than on the
last return, which is why its lag-one autocorrelation is `+0.0008` and its
surrogate is at 0.4956. Both are real, both defeat a martingale intuition, and
only one of them would ever show up in the statistic section five is built on.

**Third, "structure" at rank 3 is a different object again.** Skew Step's
asymmetry is enormous - `p(up) = 0.899569 +- 0.00067` is 596 standard errors from
a fair coin - and it is **entirely in the marginal**. A model that learns it
learns a constant, its direction AUC is 0.4983 to 0.5008 across 35 cells, and no
amount of sequence modelling will find anything there. A large number in a
marginal and a small one in a conditional are not the same finding, and only the
second is a job for any of the six arms of this study.

## What a recurrent net was for, and what it was worth

The brief was to find where a sequence model has a legitimate job. It has exactly
one on this book - inferring the hidden regime on Drift Switch - and the answer
is that it does the job and the job was already done by a straight line.

All nine cells, walk-forward, every arm on identical rows. `null-switch` is a
simulated two-state process at that cell's own fitted parameters - the positive
control, where a regime is known to exist and the filter is entitled to find it:

| symbol | tf | HMM filter | GRU | momentum 22 | null-switch HMM |
|---|---|---|---|---|---|
| Drift Switch 30 | **15m** | **0.6190** | 0.6138 | 0.5360 | 0.6069 |
| Drift Switch 20 | **15m** | 0.5976 | 0.5936 | 0.5268 | 0.5938 |
| Drift Switch 10 | **15m** | 0.5607 | 0.5497 | 0.5122 | 0.5633 |
| Drift Switch 30 | 1h | 0.5449 | 0.5346 | 0.5105 | 0.5451 |
| Drift Switch 20 | 1h | 0.5235 | 0.5251 | 0.5100 | 0.5236 |
| Drift Switch 10 | 1h | 0.5120 | 0.4980 | 0.5001 | 0.5068 |
| Drift Switch 20 | 4h | 0.5095 | 0.5152 | 0.5070 | 0.4983 |
| Drift Switch 30 | 4h | 0.5009 | 0.4974 | 0.4979 | 0.4968 |
| Drift Switch 10 | 4h | 0.4973 | 0.4948 | 0.4890 | 0.4960 |

**Three things fall straight out of it.**

**The filter reaches 0.619 and the grid is ordered exactly as section five is.**
15m beats 1h beats 4h, and within each timeframe 30 beats 20 beats 10 - the same
order as `acf1`, the same order as `sep`, and the same order as the recovery
control. **By 4h every arm is at 0.50**, which is the same collapse the cost sweep
shows and the same reason: the regime does not survive a four-hour bar.

**The feed is indistinguishable from a two-state simulation of itself.** On six of
the nine cells the `null-switch` column is within 0.006 of the real column, and
the largest gap anywhere is 0.012. The fitted model is not an approximation to
something richer; it is the thing.

**The GRU never wins.** It loses to the HMM filter on seven of nine cells, ties on
one and beats it on one (Drift Switch 20 at 4h, 0.5152 against 0.5095, in a cell
where both are at chance). A recurrent net given the one family in the book with
a genuine hidden state recovers it slightly less well than the linear-Gaussian
filter written for exactly that state.

**And the controls, on all nine cells, say what kind of structure it is.**

| symbol | tf | rows | real hmm/gru/mom | shuffle | surrogate | null-volonly |
|---|---|---|---|---|---|---|
| Drift Switch 10 | 15m | 49,978 | 0.5607/0.5497/0.5122 | 0.5017/0.4998/0.5039 | 0.5501/0.5296/0.5078 | 0.4960/-/0.4989 |
| Drift Switch 20 | 15m | 49,978 | 0.5976/0.5936/0.5268 | 0.5015/0.4907/0.4956 | 0.5669/0.5612/0.5165 | 0.4989/-/0.4987 |
| Drift Switch 30 | 15m | 49,978 | 0.6190/0.6138/0.5360 | 0.4998/0.5013/0.4948 | 0.5660/0.5595/0.5178 | 0.4971/-/0.4989 |
| Drift Switch 10 | 1h | 26,621 | 0.5120/0.4980/0.5001 | 0.5025/0.4915/0.4980 | 0.5066/0.5004/0.5033 | 0.4961/-/0.4926 |
| Drift Switch 20 | 1h | 26,621 | 0.5235/0.5251/0.5100 | 0.5062/0.5071/0.5014 | 0.5247/0.5132/0.5149 | 0.4960/-/0.4925 |
| Drift Switch 30 | 1h | 26,621 | 0.5449/0.5346/0.5105 | 0.5012/0.5072/0.4954 | 0.5395/0.5322/0.5109 | 0.4993/-/0.4924 |
| Drift Switch 10 | 4h | 6,638 | 0.4973/0.4948/0.4890 | 0.4981/0.4953/0.4848 | 0.5098/0.4805/0.4821 | 0.4831/-/0.4947 |
| Drift Switch 20 | 4h | 6,638 | 0.5095/0.5152/0.5070 | 0.4853/0.4872/0.5025 | 0.5141/0.4884/0.5025 | 0.4925/-/0.4949 |
| Drift Switch 30 | 4h | 6,638 | 0.5009/0.4974/0.4979 | 0.4954/0.5024/0.4994 | 0.4926/0.5089/0.4987 | 0.4851/-/0.4947 |

**The floor is clean everywhere.** All 27 shuffle cells lie in [0.485, 0.507].

**`null-volonly` is the control that makes the whole family readable**, and it is
the one worth having. It is the same two-state generator with **the drifts set to
zero and only the variances switching**, so a regime exists and carries no
directional information at all. Every arm returns 0.483 to 0.499 on it. The
filter is therefore reading a drift and not reading a variance regime, which is
the single most likely way a hidden-state model on this family would have been
wrong.

**The surrogate splits by timeframe, and the split is a correction to what this
page said before the last nine cells arrived.** At 1h the phase surrogate
reproduces 88% of the filter's excess over 0.500 and 93% of the net's - the
structure there is spectral and a straight line has it. **At 15m it reproduces
only 55% on Drift Switch 30** (0.5660 against 0.6190), 69% on 20 and 83% on 10.
So at the timeframe where the autocorrelation is largest there is a real
component that phase randomisation destroys, and the earlier flat claim that the
effect "is entirely linear" was true of the 1h cell and **not** of the 15m one.

That does not rescue the recurrent net. A hidden-state filter is itself a
nonlinear estimator - the posterior update is nonlinear in the observation - so
the residual is not evidence that a *net* is needed, only that a lag-one
correlation is not the whole object. **And the net does not capture it**: at 15m
the GRU is at 0.6138 against the filter's 0.6190, and across the nine cells it
loses on seven, ties on one and wins on one - Drift Switch 20 at 4h, where both
are at chance. The instrument built for the generator's actual shape beats the
general-purpose one on the generator it was built for, which is the least
surprising possible result and is the one that was measured.

**A simulated two-state process at the fitted parameters returns 0.5451** - the
feed behaves exactly like the fitted model - and the same generator with the
drifts set to zero and only the variances switching returns **0.4993 for the
filter and 0.4924 for momentum**, so the filter is correctly refusing to call
direction off a variance regime. That is the control which says the 0.5449 is a
drift reading and not an artefact of a two-component fit.

So the recurrent net is not wrong and it is not useful. It recovers a linear
object slightly less well than the linear method built for it, and the surrogate
says there was never anything else to recover.

## The ledger of what fired

Written before the runs, in `research/harness/seqfamilies.py` and
`research/harness/fammodels.py`.

| condition | outcome |
|---|---|
| 1. rate must not move with the detection threshold | **fired on Jump (2.14x to 3.01x) and DEX (1.76x to 2.52x)**; held on Boom and Crash (1.00x to 1.20x). The Jump and DEX rates are reported as detector-dependent |
| 2. the simulated null must return CV 1.00, Fano 1.00, acf1 0.00 | **held.** 200 replicates per symbol returned CV `0.991 +- 0.013`, Fano `0.962 +- 0.058`, acf1 `-0.005 +- 0.018` |
| 3. Skew Step must close to a martingale within 3 se | **held on all four**, `z = +0.04, -0.82, -0.60, +1.30` |
| 4. the shuffled variance ratio must be 1.00 | **held**, 0.957 to 1.022 at the peak horizon on all three |
| 5. a hidden-state model has found nothing if the surrogate dwell is within 2x of the feed's | **fired on the three-state fit, in the worst direction.** On `Drift Switch 10` the surrogate's persistence is `[16.6, 1.06, 20.2]` and the shuffle's `[17.6, 1.05, 14.2]` against the feed's `[5.26, 1.16, 6.16]` - not within a factor of two, but *larger*, on data with no regime in it at all. The three-state fit is withdrawn. The two-state fit fails the same test on persistence and survives on `sep` (0.33/0.62/1.75 real against 0.10/0.13/0.30 shuffled), and is reported only on that |
| 6. the wall clock is the wrong clock outside 0.05 to 1.0 spikes per bar | **fired on every timeframe at 15m and above for Boom 500 and on 3m for the fast members.** No `spike_next` number is taken from a wall-clock bar |
| *unnumbered: the pre-registered reading of the Skew Step name* | **wrong in both parts** - wrong about which side is rare, and wrong about what the number counts. Recorded in section two rather than revised |
| *unnumbered: the first hazard estimator* | **wrong.** Quantile bins plus a raw failure fraction returned a last-bin-over-first ratio of 0.148 on a *simulated memoryless* process. Replaced with equal-width bins and an exact per-tick rate, which returns 1.04 there. The uncorrected version would have been this page's headline |
| *unnumbered: the first persistence statistic* | **wrong.** `1/(1 - p_ii)` returned a "dwell" of 7.5 on shuffled i.i.d. returns. Replaced with `p_ii / pi_i` |

| *unnumbered: nothing was written for Range Break* | **the one real gap.** No condition covers "a family ranked last on the strength of two prior measurements turns out to have the largest direction AUC in the study". Section four's reasoning was sound and its conclusion was wrong, and no pre-registered test would have caught it, because the page did not think to test there |

Three of the six numbered conditions fired, two of the three unnumbered
corrections would each have produced a false headline, and the fourth unnumbered
row is a condition that should have existed and did not.

## Running it

    ./.secrets/lab.sh run research/harness/famticks.py      # 43 symbols, 11.34M ticks, 14.7m
    ./.secrets/lab.sh run research/harness/seqfamilies.py   # 470 cells, 2.6m
    ./.secrets/lab.sh run research/harness/fammodels.py     # 210 cells, 13.2m
    ./.secrets/lab.sh run research/harness/famreport.py PART=1   # the tables above, 55 lines a part
    ./.secrets/lab.sh run research/harness/famspike.py           # the two tables past the log window

Everything is resumable from the tick cache, so a re-run of the last three costs
minutes rather than the 14.7 of the pull. Every number on this page comes from a
completed run of these files.

`famsmoke.py` runs one cell of every code path on cached ticks and is what turned
up two of the three unnumbered corrections above; `famtime.py` times one
recurrent cell before an hour is committed to it. Both are cheap and both are
worth running before either of the two long harnesses.

**What was added to `seqlab.py`**, as one block below the shared layer and above
`main()`, leaving the six-arm floor untouched:

* `FAMILY_OF` - symbol to family, so a pooled table cannot put a Boom row under `step`.
* `TICK_CACHE`, `tick_window`, `tick_cache` - backward-chunked tick history sized by **sample count rather than time span**, because the sample size of a spike-gap statistic is the spike count and not the hour count.
* `SPIKE_MULTS`, `spikes` - `genspike.py`'s detector, reused unchanged.
* `hazard` - the five-statistic memorylessness battery with the equal-width exact-rate hazard curve.
* `compound_poisson_ticks`, `step_ticks`, `switch_bars` - **the three family-appropriate nulls**, each built from the feed's own pooled marginals rather than a published parameter, and `switch_bars` returning the true state path so a filter can be scored against truth. `gbm_bars` is used by neither this file nor its two harnesses.
* `bars_from_ticks` - a tick clock rather than a wall clock.

## What this does not say

* **It does not say Drift Switch can be traded some other way.** It says an AR(1)
  on its own autocorrelation cannot, that a threshold on the same forecast cannot,
  and that no timeframe in `seqlab.GRID` puts the signal and the cost advantage in
  the same cell. A different functional form reading the same `+0.15` meets the
  same `cost/sigma`, but this page has tested one family of rules and not all of them.
* **It does not extend `deriving.md`'s theorem to Drift Switch and it does not
  refute it.** The theorem's first assumption fails here, so the theorem is silent,
  and the negative result above is arithmetic on a sample rather than a proof. That
  is a weaker kind of answer than the Volatility arm has and it is stated as one.
* **The spread is the quoted spread**, median over 200,000 ticks, and no financing,
  commission or slippage is included. All three would make the net more negative.
* **Three days of ticks.** The tick sample spans 84 to 88 hours per symbol.
  Everything in section one rests on it, and a generator whose parameters change
  weekly would not be caught.
* **The Jump and DEX rates are detector-dependent** and are not properties of the
  generator. Their *memorylessness* is threshold-stable and is.
* **Range Break is not measured here.** Section four is a detector check on 30 and
  14 breaks and it is 20% off the sixty-day values, which is what that sample size
  does. [deriving.md](deriving.md) and [quantising.md](quantising.md) hold those numbers.
* **The DEX naming convention is not decoded.** The number is not the tick rate and
  this page does not say what it is.
* **The Range Break result has not had an arm built for it.** It fell out of a
  pooled table assembled for a different question, it rests on two symbols, and it
  has had no cost sweep, no tick-scale check and no simulated reflecting-band null.
  What it has is a clean shuffle, a clean surrogate, a monotone decay across four
  timeframes, a named mechanism and a prior page reaching the same conclusion from
  the variance side. It is reported at that strength and no higher.
* **`n*` is not computed for the direction arms.** Where the analytic floor is
  exactly 0.500 - which is the case for every memoryless-hazard cell - a gap of
  zero makes `n*` infinite by construction, and printing infinity in 29 rows would
  be a table of the same statement.

## What follows

1. **Publish the Skew Step and Multi Step specifications.** Seven instruments'
   increment laws are pinned exactly here - magnitudes, shares, `p(up)` to six
   decimals, closure `z` - and a repo-wide search finds no prior measurement of
   any of them. [generators.md](generators.md) is where they belong, beside the
   base Step Index it already carries.
2. **Settle what the number in a DEX name means.** It is not the tick rate: 600
   spikes every 186 ticks, 900 every 320, 1500 every 706, and the ratios 0.31,
   0.35 and 0.47 are not constant. One question to the broker's specification, no
   model. The same question applies to the map from a Skew Step's magnitude count
   to its 4:1 and 9:1 skew, which two instruments cannot determine.
3. **Give Range Break the arm this page gave Drift Switch.** It has the largest
   direction AUC in the study - 0.6627 at 15m on two symbols, controls at 0.496 -
   and none of the treatment: no cost sweep against its measured spread, no
   tick-scale check, no simulated reflecting-band null, no `max_of_k` over the
   grid. `deriving.md`'s fade screen says the answer will be no - gross at 11% of
   the spread, zero survivors in 90 cells - but that screen tested a fade on a
   break, not a classifier on position within the band, and they are not the same
   rule. The machinery in `seqfamilies.py` and `fammodels.py` runs it unchanged;
   what is missing is a `range_walk` null beside the other three in `seqlab.py`.
4. **Try a continuous position on Drift Switch, which is the one lever this page
   did not pull.** Both rules tested here take a *sign*, so turnover is 0.73 to
   0.99 a bar and is nearly fixed. A position proportional to the forecast moves
   gross and turnover by different amounts, and breakeven is `2 * gross /
   turnover` - so it is the ratio and not either term that has to improve. The
   threshold rule, which is the stand-aside version of the same idea, made seven
   of nine cells worse and one better (0.692 to 0.884). That one cell is the only
   thing in this study close enough to 1.0 to be worth another measurement, and
   a month of ticks rather than three days is what it would need.
5. **Add Drift Switch to `generators.md`'s martingale verification.** That page
   verified twenty-six synthetics four ways; this family was not among them and
   it is the one that fails. A table asserting the property should name its
   exception rather than leave it out of scope.
6. **Check whether `TRADING_STOP_OVERSHOOT` should cover Boom and Crash 50 to 900.**
   `till_infinity/trading/config.py` carries it for 300, 500 and 1000 only. The
   rate is confirmed to the name on all eighteen feeds here, and the one-sided
   grind that justified the multiple - 99.78% of `Boom 500` tick moves are down -
   is a property of the family and not of three of its members. This page does not
   measure slippage and so does not propose a number; it says the twelve uncovered
   feeds have the same mechanism as the six covered ones.
