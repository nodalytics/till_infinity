# Confluence: four frameworks name 98% of all prices, and a walk gets the same answer

**Measured 2026-11-10** on the lab with
[`confluence_levels.py`](../ideas/confluence_levels.py) and
[`test_confluence_levels.py`](../ideas/test_confluence_levels.py). 50
instruments, 162 instrument-interval series, **6,276,645 bars** at 15m, 1h, 4h
and 1d, 1.06 million de-overlapped observations. Outputs in
`~/conf/out/{main,calib,power,sweep,cost}` on the lab: `overlap.csv`,
`cells.csv`, `obs.npz`, `power.csv`, `sweep.csv`, `calibrate.csv`, `cost.csv`.

A piece of gold commentary called $3,977 a "high-conviction decision point"
because a Square-of-9 45 degree angle ($3,971.63), a Fibonacci 62-79% OTE zone
($3,975-3,928), a prior swing low / double bottom ($3,975.48 and $3,977.95) and
the $4,000 round-number magnet all land together; that the outcome there is
**bimodal** (defend and revert to ~$4,050, or break and trend to ~$3,880); and
that breaking it triggers a **stop cascade**. This does not test $3,977. It
tests the class: over every instrument and all available history, does a price
named by `k` frameworks behave differently from one named by 1, and from one
named by none?

## Verdict

| question | answer |
|---|---|
| **Is a confluence rare?** | **No, and this is the result worth reading first.** A price drawn at a matched arrival is named by at least one of the four frameworks **97.96% of the time** (3,404,361 of 3,475,204 draws), and **68.02%** of named first touches carry `k >= 2`. Confluence is the *modal* state of the price axis, not a selection from it |
| **Are the four frameworks four objects?** | **Partly.** Pairwise agreement over each pair's union is **0.3101** (fib-swing), **0.3098** (fib-gann), **0.2180** (gann-swing) and **0.058-0.062** for every pair involving the round grid. So the three history-driven frameworks share a fifth to a third of their levels and the round grid is nearly independent of all three - but they are dense enough (0.156 to 1.632 levels per volatility unit) that co-location needs no agreement to occur |
| **Does the hold rate rise with `k`?** | **Yes, and so does a walk's, by the same amount.** Traded instruments, `k >= 2` against `k = 1`, paired on days: real **+0.0156 +- 0.0022** [+0.0113, +0.0197] on 154,053 against 79,677 resolved observations; a driftless Brownian-bridge walk through the identical detectors reads **+0.0154 +- 0.0022**; a GARCH(1,1)-t(5) bridge reads **+0.0139 +- 0.0021**. **Real minus walk is +0.0002 +- 0.0031** |
| **Does any cell survive multiplicity?** | **No. 0 of 131** instrument-interval cells survive Benjamini-Hochberg; 95 are nominally positive where chance gives 65, and 15 have a lower bound above zero where chance gives about 3 - which is what a mechanical effect present in every cell looks like, since the walk arm has it too |
| **Is the outcome distribution bimodal?** | **No, and it is the opposite shape.** Excess kurtosis of the next-20-bar return is **+8.94 / +8.43 / +8.33** at `k = 1 / 2 / 3` - fat-tailed and unimodal, where bimodality requires it to be *negative*. Sarle's coefficient reads **0.087-0.096** against the 0.5556 flag. The two-component mixture beats one Gaussian by a huge margin (dBIC 11,379-13,286) and its fitted means are **0.10-0.12** pooled standard deviations apart: it is a **scale** mixture, which is a fat tail, not a location mixture, which is what two outcomes would be |
| **Is there a cascade after a break?** | **No.** Conditional on breaking, the move goes another `HOLD_VOL` unit through before returning to the level on **0.5241-0.5264** of breaks at every `k`, against **0.5465** at the matched placebo break and **0.5250-0.5317** on the walk. Realised volatility over the next 20 bars is **0.736-0.753** of a unit, flat in `k`; the excursion is **3.89-3.97** units, flat in `k` |
| **Does the harness see a level that is really there?** | **Yes, at twenty points.** `Range Break 100/200 Index` - a range by construction - holds on **0.3224 / 0.3216 / 0.3213** of arrivals against its own walk's **0.5228 / 0.5486 / 0.5306**. The detector finds a structure worth **-0.20 to -0.23** there, in the break direction, and **the `k` ladder is flat to three decimal places inside it** |
| **Does it reproduce a known number?** | **Yes.** The round-number arm alone holds on **0.4797** of 1,059 arrivals against **0.5048** when joined, and the matched placebo holds on **0.5087** - against [`magnet.md`](../../docs/magnet.md)'s 44.9% reached at a level against 49.5% at an arbitrary price the same distance away, and [`focal-points.md`](focal-points.md)'s round-number bounce rate of 51.9% against a 53.1% placebo. Three constructions, three venues, the same sign: a level is not where price turns |
| **So is watchedness measurable this way?** | **No, and the reason is the first row.** A confluence count cannot be a measure of how many participants compute a price when the frameworks' own rules name 98% of all prices. What is refuted is this *observable*, not the hypothesis - see [What is unmeasurable](#what-is-unmeasurable) |

**The headline as a rate:** `k >= 2` arrivals hold on **0.5173 +- 0.0014**
[0.5148, 0.5200] of **154,053** resolved observations on traded instruments
against **0.5018 +- 0.0019** at `k = 1` on **79,677** - and the same detectors
on a driftless Brownian-bridge walk read **0.5434 +- 0.0014** [0.5409, 0.5463]
against **0.5280 +- 0.0017**. The market's ladder is the walk's ladder shifted
down, and the *excess* of the market's `k` gap over the walk's is
**+0.0002 +- 0.0029** [-0.0059, +0.0054]. Standard errors are block
bootstraps over whole UTC days; **0.02-0.03% of races are censored**, so the
rate is not a reporting artefact of a short horizon.

## Why this was worth running at all

Six level claims are closed on this desk and none of them is this one.
[`magnet.md`](../../docs/magnet.md): a level does not **attract**.
[`level-shield.md`](level-shield.md): a level does not **block** the path, 1 of
210 cells. [`gap-levels.md`](gap-levels.md): a level is not **graded** by how it
behaved before. [`topology.md`](topology.md): levels, ranges and shapes restate
volatility. `a-magnet-is-a-shared-reference` names the one thing none of them
tested - **watchedness**, the claim that liquidity rests where many participants
compute the same price - and a confluence count is the most direct observable of
it this desk can build.

The nearest prior measurement is [`strength.md`](strength.md), and it is a
different claim. Confluence **breadth across timeframes** - one framework on
several clocks - does not separate: AUC **0.476** and **0.452**, four runs and
four orderings, `depth >= 3` against `depth < 3` at **-2.2 [-6.3, +1.7]** points.
`Zone.strength` still multiplies by `1 + 0.15*(depth - 1)` on that evidence.
Breadth across *frameworks* was open, because four frameworks are four
populations of screens where one framework on four clocks is one population
looking at four charts.

## The rules, as frozen before any outcome was read

**Four frameworks, all causal.** Each emits a price and the bar it became
*knowable*, never the bar it describes.

| framework | the level | knowable at |
|---|---|---|
| `swing` | a confirmed pivot high or low (`indicators/trend.pivots`' definition, reach 10 either side), flagged `doubled` when a second pivot lands within the tolerance of an earlier one - the double bottom the commentary names | pivot bar + 10 |
| `fib` | the 0.382, 0.5, 0.618 and 0.786 retracements of a **completed** leg between two confirmed opposite pivots, the leg at least 2.0 units | the later pivot's confirmation |
| `gann` | the Square-of-9 wheel from the latest confirmed pivot, `((sqrt(a*s) + deg/180)^2)/s` at 45, 90, 135, 180, 270 and 360 degrees both signs | the anchor pivot's confirmation |
| `round` | the whole and half steps of the smallest power of ten at least 5 units wide (`rounds.py`'s rule) | always; it needs no history |

`gann` is in the study **precisely because it is the most arbitrary of the
four**: a Square of 9 has no mechanism, so if it added information the first
hypothesis would be a bug in the harness.

**The scale of a Gann wheel is a choice and it is stated.** One 45 degree step
is about `0.5*sqrt(price/s)` wide, which at `s = 1` is $31 on gold and 0.52 on
EURUSD - half the price. The harness picks the power of ten whose step is
nearest **five volatility units**, which is the density `rounds.py` draws the
round grid at, so neither grid can agree with the other merely by being finer.
A test pins the step to within a factor of `sqrt(10)` on prices from 0.65 to
90,000, and another pins the wheel against the commentary's own number: the
anchor implied by $3,971.63 is $3,940.17, and
`(sqrt(3940.17) + 0.25)^2 = 3971.63`.

**Other constants**, all fixed before the first outcome: tolerance **0.25**
volatility units (the unit is a causal EWMA of the bar range, lagged one bar -
`drive-q-from-the-range`); level life **500** bars; race distance **1.0** unit
back against 1.0 unit through with a **48**-bar horizon; shape and cascade
windows **20** bars; **5** volatility strata by causal quantile rank over the
previous 500 bars; warmup 600 bars; a series under 1,200 bars is skipped and
named.

**The tolerance was set at 0.25 before any outcome was read**, on the
distribution of `k` alone: at 0.5 units `k >= 2` is 89% of touches on a walk, so
there is nothing to contrast, and at 0.1 the `k = 4` cell is too small to carry
a rate. The full sweep is reported below rather than the chosen cell.

**The arms.**

| arm | what it is | the property it carries |
|---|---|---|
| `real` | the market's own bars, split by `k` | the claim |
| `placebo` | an arrival at a price **no framework names**, matched on the signed displacement from the previous close and on the volatility stratum, one per real observation | geometry without a level |
| `walkpath` | a driftless Brownian-bridge walk resampling this series' own steps, through the identical detectors | **the arm that decides.** A walk has swings, retracements, wheels and round numbers too, and `k` counts them the same way |
| `garchpath` | the same bridge driven by GARCH(1,1)-t(5) steps | clustered volatility, still no participants |

Both surrogate arms build the **path**. `node/surrogates.walk_with_bar_geometry`
is not a barrier null - it re-hangs real bar shapes on a synthetic close path,
so a stop fires where the path never went, and it gaps 0.60-0.64 of a bar range
on every bar against the market's median `|gap|` of 0.0000 on 71-79% of bars.
The bridge is [`entry_timing.py`](../harness/entry_timing.py)'s, which measured
the difference at `-0.1985R` against `+0.0003R` on real bars where optional
stopping requires exactly zero. A test asserts `open == previous close` to zero
tolerance on 4,000 bars.

**The settlement**, stated because it is where a barrier study leaks: the
arrival bar contributes its **close only** (OHLC cannot order its high against
its low, so using the extremes would be the harness choosing an intrabar path);
from the next bar the extremes count; when both barriers are reachable in one
bar the **break** wins, which is the conservative direction for a hold claim.

**De-overlapping.** Every arm and every `k` bucket is its own stream: an
observation is accepted only 48 bars after the last one accepted *in that
stream*, so no two observations **within a stream** share an outcome bar. Two
streams still can - `k = 1` and `k >= 2` are drawn from the same bars - and
that dependence is priced by the day-block bootstrap, which resamples whole UTC
days across both arms at once rather than resampling rows. A touch is
a **first** touch - sitting inside a level for forty bars is one observation,
which is the correction that turned a published 0.6365 into 0.5092. A stream per
bucket and not one stream, because with one stream the rarest bucket - the claim
- loses every slot to one that fires ten times as often.

## Deliverable 1: is it four frameworks or one counted four times?

Over 162 series and 6.28 million bars, every 20th bar, levels within 12 units
of the close:

| framework | fires | levels per volatility unit | levels cut |
|---|---|---|---|
| `swing` | 0.994 | 0.600 | 254,875 |
| `fib` | 0.987 | 0.994 | 417,451 |
| `gann` | 0.995 | **1.632** | 1,885,486 |
| `round` | 1.000 | 0.156 | analytic |

| pair | share of the pair's union naming one price |
|---|---|
| `fib` - `swing` | **0.3101** |
| `fib` - `gann` | **0.3098** |
| `gann` - `swing` | **0.2180** |
| `gann` - `round` | 0.0618 |
| `round` - `swing` | 0.0592 |
| `fib` - `round` | 0.0584 |

| `k` of a named price | share of first touches |
|---|---|
| 1 | 0.3198 |
| 2 | 0.4450 |
| 3 | 0.2194 |
| 4 | 0.0158 |

**The answer is neither, and that is the finding.** The three history-driven
frameworks are not one object counted three times - a fifth to a third of their
union is shared, which is in the range `smc-primitives-overlap-and-are-closed`
records for detectors assumed to differ, and the round grid is nearly
independent of all three at 0.058-0.062. But **it does not matter**, because
they are dense enough that co-location needs no agreement. The Gann wheel alone
emits 1.63 levels per volatility unit; with a tolerance of 0.25 units a price
has a wheel rung within reach most of the time whatever else is nearby. The
placebo draw measures the consequence directly: of 3,475,204 matched arrivals
at a price inside the bar, **3,404,361 (97.96%) were named by at least one
framework** and only 70,843 were free. Two thirds of the named ones carry
`k >= 2`.

So a confluence count at these frameworks' own densities is **not a selective
condition**. It is close to a property of the price axis. Whatever watchedness
is, this is not a measurement of it - and the rest of the study is what happens
when you measure it anyway.

## Deliverable 2, outcome 1: the hold rate on the arriving side

Traded instruments (every family except the Deriv synthetics), hold = travels
1.0 unit back the way it came before 1.0 unit through, within 48 bars.

| arm / bucket | n | hold | block se | 95% | within strata | mean \|displacement\| |
|---|---|---|---|---|---|---|
| real / k=1 | 79,677 | 0.5018 | 0.0019 | [0.4981, 0.5054] | 0.5028 | 0.678 |
| real / k=2 | 83,745 | 0.5130 | 0.0018 | [0.5093, 0.5163] | 0.5133 | 0.586 |
| real / k>=3 | 70,308 | 0.5226 | 0.0021 | [0.5187, 0.5267] | 0.5229 | 0.722 |
| **placebo / k=0** | 48,326 | 0.5087 | 0.0024 | [0.5041, 0.5133] | 0.5093 | 0.507 |
| walkpath / k=1 | 81,524 | 0.5280 | 0.0017 | [0.5245, 0.5314] | 0.5277 | 0.619 |
| walkpath / k=2 | 82,017 | **0.5462** | 0.0018 | [0.5430, 0.5498] | 0.5455 | 0.578 |
| walkpath / k>=3 | 62,869 | 0.5396 | 0.0020 | [0.5356, 0.5437] | 0.5392 | 0.693 |
| garchpath / k=1 | 81,373 | 0.4989 | 0.0017 | [0.4955, 0.5020] | 0.4967 | 0.588 |
| garchpath / k=2 | 82,887 | 0.5098 | 0.0017 | [0.5064, 0.5128] | 0.5081 | 0.553 |
| garchpath / k>=3 | 65,682 | 0.5166 | 0.0020 | [0.5124, 0.5203] | 0.5142 | 0.626 |

The ladder is monotone on the real arm and it is monotone on both nulls.

| the comparison that decides, `k >= 2` minus `k = 1`, paired on days | gap |
|---|---|
| real | **+0.0156 +- 0.0022** [+0.0113, +0.0197] |
| walkpath | **+0.0154 +- 0.0022** [+0.0110, +0.0196] |
| garchpath | **+0.0139 +- 0.0021** [+0.0100, +0.0180] |
| real `k >= 2` against the matched placebo | +0.0087 +- 0.0025 [+0.0040, +0.0138] |

and the difference of differences, which is the number the study exists to
produce - the same days resampled across all four streams at once:

| how much further `k` moves the market than it moves a null | excess |
|---|---|
| real minus `walkpath` | **+0.0002 +- 0.0029** [-0.0059, +0.0054] |
| real minus `garchpath` | **+0.0016 +- 0.0029** [-0.0042, +0.0074] |

**A driftless walk, whose levels nobody computes and at which no order rests,
gains 0.0154 from confluence where the market gains 0.0156.** The walk arm is
not a weaker version of the effect; it is the whole effect. The within-strata
column moves the real figures by at most 0.0010, so it is not the volatility
regime either.

Per framework, alone against joined by at least one other - the "beyond each
framework alone" column the question asks for:

| framework | arm | alone | joined | gap | real minus walk |
|---|---|---|---|---|---|
| `swing` | real | 0.4984 (8,492) | 0.5188 (96,918) | +0.0204 +- 0.0054 | **+0.0089 +- 0.0076** |
| | walkpath | 0.5312 (10,319) | 0.5426 (93,556) | +0.0115 +- 0.0052 | |
| | garchpath | 0.4997 (9,486) | 0.5146 (95,342) | +0.0149 +- 0.0054 | |
| `fib` | real | 0.5050 (34,003) | 0.5193 (127,225) | +0.0143 +- 0.0032 | **-0.0026 +- 0.0042** |
| | walkpath | 0.5284 (39,365) | 0.5453 (119,566) | +0.0169 +- 0.0028 | |
| | garchpath | 0.5001 (38,501) | 0.5133 (122,645) | +0.0132 +- 0.0029 | |
| `gann` | real | 0.5001 (36,123) | 0.5193 (131,852) | +0.0192 +- 0.0030 | **+0.0036 +- 0.0042** |
| | walkpath | 0.5260 (29,993) | 0.5416 (112,768) | +0.0156 +- 0.0032 | |
| | garchpath | 0.4981 (31,486) | 0.5136 (118,559) | +0.0156 +- 0.0032 | |
| `round` | real | 0.4797 (1,059) | 0.5048 (26,169) | +0.0251 +- 0.0159 | **+0.0222 +- 0.0196** |
| | walkpath | 0.5349 (1,847) | 0.5378 (30,199) | +0.0029 +- 0.0117 | |
| | garchpath | 0.4842 (1,900) | 0.5121 (29,988) | +0.0279 +- 0.0121 | |

Every framework gains from company on the market, including the Square of 9 -
and every framework gains from company on a walk too. **All four `real minus
walkpath` intervals contain zero**: [-0.0065, +0.0233], [-0.0117, +0.0050],
[-0.0048, +0.0121] and [-0.0173, +0.0608]. `a-control-is-only-for-a-named-
property` applies to the Square of 9 row: a framework with no mechanism gaining
as much as the three with one is the signature of an effect that belongs to the
construction.

The double bottom, which is the commentary's specific claim about the swing
level, is measured on its own: a swing level that repeats an earlier one within
the tolerance holds on **0.5215 +- 0.0082** of 4,017 arrivals against a single
swing's rate on the remainder - no separation.

### The multiplicity table

**131 instrument-interval cells, 95 nominally positive** (chance gives 65),
**15 with a lower bound above zero** (chance gives about 3), **0 surviving
Benjamini-Hochberg**. The excess of nominally positive cells is what a
mechanical effect present in every cell produces, and the walk arm has it too.
The largest cells are small ones: `AUDCAD/1h` at +0.1973 +- 0.0693 on 169
against 77 observations, `EURAUD/1h` at +0.1437 +- 0.0640 on 160 against 80.

### The controls

| control | arm | k=1 | k=2 | k>=3 |
|---|---|---|---|---|
| **`Range Break 100/200`**, the level positive control | real | **0.3224 +- 0.0099** | 0.3216 +- 0.0101 | 0.3213 +- 0.0121 |
| | walkpath | 0.5228 +- 0.0090 | 0.5486 +- 0.0104 | 0.5306 +- 0.0113 |
| **`Volatility 25/75`**, the independent placebo pair | real | 0.4866 +- 0.0044 | 0.5030 +- 0.0043 | 0.5131 +- 0.0047 |
| | walkpath | 0.4800 +- 0.0044 | 0.4949 +- 0.0043 | 0.4901 +- 0.0058 |

`Range Break` is the row that makes the null readable. It is a range by
construction, its boundaries are levels that exist, and the harness finds them:
**-0.20 at `k = 1` and -0.23 at `k = 2` against its own walk**, in the *break*
direction, which is what a
process designed to break out of ranges should do. So the detectors are not
blind - they resolve a real level structure at twenty points - **and the `k`
ladder inside that structure is flat to three decimal places** (0.3224, 0.3216,
0.3213). Where levels matter most, confluence still carries nothing.

The placebo pair behaves as the traded book does, which is the second half of
the same reading: two generated processes with **constant volatility by
construction** produce a `k` ladder of **+0.0209** (0.4866 at `k = 1` against
0.5075 pooled at `k >= 2`) where the traded book produces **+0.0155**. A ladder
that is *larger* on a generated process than on the market is not a market
property.

## Outcome 2: the bimodality claim

The distinctive and falsifiable half of the commentary. Conditional on arrival,
the next-20-bar return signed by the arriving side (positive = went back the way
it came), in volatility units. **The direction was stated before the run**:
bimodality means *negative* excess kurtosis, a bimodality coefficient above
0.5556, and a mixture whose two components differ in **location**.

| arm / bucket | n | skew | excess kurtosis | Sarle bc | h_crit/sd | Silverman p | dBIC | mixture separation |
|---|---|---|---|---|---|---|---|---|
| real / k=1 | 79,699 | -0.209 | **+8.942** | 0.0874 | 1.418 | 0.055 | 12,936 | **0.113** |
| real / k=2 | 83,764 | -0.219 | **+8.432** | 0.0917 | 3.242 | 0.005 | 13,286 | **0.117** |
| real / k>=3 | 70,322 | -0.287 | **+8.333** | 0.0955 | 2.234 | 0.005 | 11,379 | **0.103** |
| placebo / k=0 | 48,331 | +0.033 | +7.450 | 0.0958 | 0.492 | 0.746 | 6,236 | 0.082 |
| walkpath / k=1 | 81,524 | -0.254 | +7.524 | 0.1011 | 1.923 | 0.005 | 6,874 | 0.192 |
| walkpath / k=2 | 82,017 | -0.145 | +5.803 | 0.1160 | 1.294 | 0.010 | 6,301 | 0.143 |
| walkpath / k>=3 | 62,869 | -0.335 | +7.428 | 0.1066 | 2.464 | 0.005 | 5,574 | 0.249 |
| garchpath / k=1 | 81,373 | -0.039 | +1.136 | 0.2421 | 0.600 | 0.159 | 1,511 | 0.057 |
| garchpath / k=2 | 82,887 | -0.083 | +1.540 | 0.2218 | 1.328 | 0.005 | 1,833 | 0.072 |
| garchpath / k>=3 | 65,682 | -0.066 | +1.461 | 0.2251 | 1.651 | 0.005 | 1,389 | 0.054 |

**Every statistic points the other way.** Excess kurtosis is **positive and
large** at every `k` - the distribution is a single sharp peak with heavy tails,
which is the shape this desk measures everywhere and the exact opposite of two
separated outcomes. Sarle's coefficient is **0.087 to 0.096** against the
0.5556 flag, and a uniform distribution reads exactly 0.5556. And the mixture
is the clean answer: two Gaussians beat one by 11,379 to 13,286 BIC points,
which is enormous, **and their fitted means are 0.10 to 0.12 pooled standard
deviations apart**. That is a *scale* mixture - one mean, two variances - which
is how a two-component fit represents a fat tail, and it is not a *location*
mixture, which is what "defend or break" would be. The study's own positive
control pins the distinction: on a planted 50/50 mixture at +-3 sd the same
estimator returns a separation above 1.5, and on a pure scale mixture it returns
below 0.5.

**Silverman's p is reported and not interpreted, and the reason is in the
tests.** The critical-bandwidth test over-rejects on heavy tails - on a
Student-t(3) it returns p = 0.016 - because a handful of extreme points are
isolated bumps that only a very wide kernel smooths away. Read across arms it
says nothing: the walk rejects unimodality at p = 0.005 on all three buckets,
harder than the market does at `k = 1`.

## Outcome 3: the cascade

Conditional on *breaking* (price travelled 1.0 unit through), over the next 20
bars: `went on` races another unit through against a return to the level, which
on a martingale is 0.5 by symmetry.

| arm / bucket | n breaks | went on | se | realised / unit | excursion / unit |
|---|---|---|---|---|---|
| real / k=1 | 39,698 | 0.5264 | 0.0028 | 0.7518 | 3.9518 |
| real / k=2 | 40,787 | 0.5241 | 0.0027 | 0.7360 | 3.8853 |
| real / k>=3 | 33,568 | 0.5261 | 0.0029 | 0.7533 | 3.9661 |
| **placebo / k=0** | 23,744 | **0.5465** | 0.0034 | 0.7867 | 4.0530 |
| walkpath / k=1 | 38,478 | 0.5250 | 0.0028 | 0.6666 | 3.6380 |
| walkpath / k=2 | 37,216 | 0.5280 | 0.0027 | 0.6658 | 3.6346 |
| walkpath / k>=3 | 28,942 | 0.5317 | 0.0031 | 0.6692 | 3.6721 |
| garchpath / k=1 | 40,778 | 0.5265 | 0.0025 | 0.6874 | 3.5778 |
| garchpath / k=2 | 40,631 | 0.5227 | 0.0024 | 0.6821 | 3.5282 |
| garchpath / k>=3 | 31,750 | 0.5255 | 0.0028 | 0.6881 | 3.5568 |

**There is no cascade and `k` is not in it.** Continuation after a break is
flat across `k` to within a standard error, the walk does it slightly more
often, and the arm that continues *most* is the **matched placebo break at a
price no framework names** (0.5465). Realised volatility and excursion are
higher on the market than on either surrogate - 0.75 against 0.67 of a unit, and
3.9 against 3.6 units - which is this market's own wickiness
(`how-markets-differ-from-every-simple-process`) and is **flat in `k`**: a
break of a four-framework confluence is followed by the same volatility as a
break of a one-framework level.

This is the third construction to reach the same place.
[`focal-points.md`](focal-points.md) measured the published version of the stop
cascade directly: FX accelerates after crossing a big figure on 56.7% of
crossings against a shifted-grid placebo's 54.1%, and the random walks do it at
53.7% against 52.5%, so the market's own share is about 1.4 points. That is the
only acceleration anybody here has measured, it belongs to the round number
alone, and adding three more frameworks on top of it does nothing.

## By family: the regime split, reported as information

`k >= 2` hold rate on the real arm:

| family | hold | se | n |
|---|---|---|---|
| fx | 0.5203 | 0.0018 | 82,317 |
| metal | 0.5205 | 0.0029 | 29,623 |
| crypto | 0.5118 | 0.0044 | 14,745 |
| index | 0.5089 | 0.0040 | 22,725 |
| energy | 0.5042 | 0.0073 | 4,643 |
| deriv | 0.4788 | 0.0022 | 67,818 |

The split is real and it is not a gating condition, because the quantity that
differs between families is the *level* of the rate rather than the `k` ladder,
and the level is a property of the construction (see below). A rule gated on
"trade confluence in FX and not in energy" would be gated on 1.6 points of hold
rate that the walk arm reproduces in both.

## What the construction itself contributes, and why no level here is quotable

The walk arm does **not** read 0.5, and the reason has to be named rather than
absorbed. The race is marked from the **level**, but the path is at the arrival
bar's **close** when the race starts, and a bar that dipped to the level and
closed is on average displaced back toward the side it came from - so the hold
barrier is already nearer than the break barrier before anything happens. That
is a property of marking a race from a touched price, not of levels.

`MODE=calibrate` measures it with **random anchors so the detector cannot be
the cause**, on generated bars, two ways: barriers about the arrival bar's close
(a martingale race, which owes exactly 0.5) and barriers about the touched price
(what this study measures).

| what the race is marked from | pooled hold rate over 8 generated series |
|---|---|
| the arrival bar's **close** (a martingale race) | **0.5006** |
| the **touched price** (what this study measures) | **0.5717** |

Per series the close-marked race reads 0.4734 to 0.5177 on about 1,100
observations each, straddling 0.5, and the level-marked race reads 0.5518 to
0.5995 - so the construction contributes about **+7 points** of hold rate on a
driftless walk with no detector involved at all. The `garch` bridge contributes
more than the `iid` one (0.580-0.600 against 0.552-0.556), which is why the
`garchpath` arm sits at a different level from the `walkpath` arm in every table
above.

So no *level* in this document is a measurement of a market property, and every
verdict above rests on a **difference between arms** or a **difference of
differences**, never on the level of one arm.

## The mechanism, measured rather than argued

Whether the `k` ladder is the arrival's geometry - a `k >= 2` price being
differently placed inside its bar than a `k = 1` price - is testable directly,
in quintiles of the arrival's signed displacement from the previous close:

| quintile of \|displacement\| | real k=1 | real k>=2 | gap | walk k=1 | walk k>=2 | gap |
|---|---|---|---|---|---|---|
| [0.000, 0.256) | 0.5074 | 0.5156 | +0.0082 | 0.5251 | 0.5343 | +0.0092 |
| [0.256, 0.421) | 0.5002 | 0.5159 | +0.0157 | 0.5540 | 0.5731 | +0.0192 |
| [0.421, 0.604) | 0.5061 | 0.5188 | +0.0127 | 0.5839 | 0.5873 | +0.0034 |
| [0.604, 0.879) | 0.5045 | 0.5190 | +0.0145 | 0.5633 | 0.5865 | +0.0232 |
| [0.879, 29.978) | 0.4934 | 0.5176 | +0.0242 | 0.4042 | 0.4294 | +0.0252 |
| **equal weight** | | | **+0.0151** | | | **+0.0160** |

The displacement is **not** the mechanism: the gap survives inside every
quintile and the equal-weight figure (+0.0151) is the pooled one (+0.0156). But
the walk's gap survives too, at +0.0160, so conditioning on geometry does not
separate the market from the null either. What the quintiles do show is how
strongly the *level* of the rate depends on the construction - the walk arm runs
from 0.58 in the middle quintile to 0.40 in the top one, a 18-point swing driven
by nothing but where in its bar the touched price sat.

So no *level* in this document is a measurement of a market property, and every
verdict above rests on a **difference between arms** or a **difference of
differences**, never on the level of one arm.

## Power: where the test goes blind

<!-- POWER -->

## The sweep, reported whole

<!-- SWEEP -->

## Cost

Nothing survived the three outcomes, so there is no traded arm to cost. The
table is still worth printing, because it sets what a surviving effect would
have had to be worth. Round trips are the terminal's own live bid-ask through
[`venue.py`](../harness/venue.py) - **not** the stored `spread` column, which is
in points rather than price and reads zero on 7-35% of bars.

| instrument | round trip | cost in R at a 1.0-unit stop, 15m / 1h / 4h / 1d |
|---|---|---|
| XAUUSD | 0.16 px | **0.0832** / 0.0396 / 0.0199 / 0.0082 |
| US SP 500 | 0.36 px | 0.0551 / 0.0259 / 0.0125 / 0.0053 |
| BTCUSD | 18.737 px | 0.1209 / 0.0548 / 0.0247 / 0.0089 |
| EURUSD | 0.00009 px | 0.1365 / 0.0654 / 0.0322 / 0.0131 |
| XAGUSD | 0.03 px | 0.6490 / 0.3070 / 0.1558 / 0.0647 |

The ceiling is 0.16 of risk. **The whole measured `k` gap - the one the walk
also has - is worth 0.031R a trade** in a 1:1 race (`2 x 0.0156`), which is
below XAUUSD's own 15m round trip of 0.0832R and clears cost only at 4h and 1d.
The part of it that is not the walk's is +0.0002 +- 0.0029 in hold rate, or
**+0.0004R +- 0.0058R**, against a cheapest-instrument round trip of 0.0082R at
1d. So even if the excess were the whole of its upper bound it would pay
`2 x 0.0054 = 0.011R` against 0.0082R at 1d and lose at every shorter clock.
`a-shorter-clock-multiplies-cost-in-r` is the general form: the same spread is
19x dearer at 15m than 1d.

## What is refuted

1. **A confluence count is not a selective condition** at the densities these
   four frameworks' own rules imply. 97.96% of matched arrivals are at a named
   price and 68.02% of named touches carry `k >= 2`. Any claim that begins "when
   several frameworks agree" is, at this tolerance, a claim about most prices.
2. **Confluence does not raise the hold rate beyond a walk.** The gap is
   +0.0156 +- 0.0022 on the market and +0.0154 +- 0.0022 on a driftless
   Brownian-bridge walk through the same detectors, a difference of +0.0002
   +- 0.0031. 0 of 131 cells survive Benjamini-Hochberg.
3. **The bimodality claim is refuted in the direction it was stated.** The
   next-20-bar return at a `k >= 2` arrival has excess kurtosis +8.4, Sarle
   0.092 against a 0.5556 flag, and a two-component mixture separated by 0.12
   standard deviations: one sharp mode with fat tails, not two outcomes.
4. **There is no stop cascade attributable to confluence.** Continuation after
   a break is 0.5241-0.5264 at every `k`, below the matched placebo's 0.5465,
   and realised volatility and excursion after a break are flat in `k`.
5. **The Square of 9 adds nothing, and that is a check rather than a result.**
   It gains +0.0192 +- 0.0030 from company, the second largest of the four,
   which is the size the other three gain. A framework with no mechanism
   behaving like the ones with mechanisms is the signature of an effect that
   belongs to the construction.
6. **A double bottom is not a better swing level**: 0.5215 +- 0.0082 on 4,017
   arrivals, flat against a single swing.

## What is unmeasurable

1. **Watchedness itself.** The hypothesis is that liquidity rests where many
   participants compute the same price. A confluence count is a proxy for *how
   many frameworks a harness can compute*, and the two part company as soon as
   the frameworks are dense - which they are, by their own rules. Measuring
   watchedness needs a quantity that scales with **attention** rather than with
   arithmetic: how many screens actually draw the line, which this venue cannot
   see (no DOM, `real_volume` is 0, `tick_volume` is a quote count - see
   `no-order-flow-and-no-real-volume`). The nearest observable this desk could
   build is a **count of distinct frameworks that is density-matched across
   frameworks and sparse in absolute terms** - one level per framework per
   several volatility units rather than one per fraction of a unit - and that is
   a different harness, not a parameter of this one.
2. **Whether a tighter tolerance has an effect**, below the point where the
   cells carry a rate. The sweep reaches 0.10 units; below that the `k = 4`
   bucket empties.
3. **The level of any hold rate**, for the construction reason above. Only
   differences between arms are quotable.
4. **Whether a *human* reading of "confluence" - a handful of levels a person
   would draw, not every level four rules emit - behaves differently.** Nothing
   here measures a person's chart. It measures what the four published rules
   produce when they are run exhaustively, which is the only version that can be
   run over 6.28 million bars, and it is a different object from four lines
   somebody chose.

## Deviations from the design, and the bugs the tests caught

* **Sarle's bimodality coefficient was wrong in the first version** of the
  harness: the published denominator is `excess kurtosis +
  3(n-1)^2/((n-2)(n-3))`, which tends to 3, and the first version added another
  3. It read **0.228** on a clean two-component mixture at +-3 sd, so it would
  have flagged nothing, ever. `test_the_bimodality_coefficient_flags_the
  _mixture_and_not_the_t` caught it before any result was read.
* **`race`'s horizon was a default argument**, bound at import, so a test that
  monkeypatched the module constant silently raced over the old horizon. Changed
  to resolve from the global at call time. This is the shape
  `till.env needs a container recreate` is about: a configuration read in one
  place and set in another, which reads as healthy either way.
* **`ARMS` was narrowed by setting `os.environ`** in two modes, which does
  nothing, because the constant is read once at import. Both modes would have
  quietly run every arm. Replaced by `use_arms`, which assigns the module global
  and says why in its docstring.
* **The reflecting plant leaks** and the sweep had to be of the *realised* lift
  rather than the nominal probability: a reflected sub-step is retried by the
  next one, so sixty sub-steps a bar transmit a barrier at `p = 0.6` almost
  completely (no measurable lift) while `p = 0.9` lifts the hold rate at a
  planted line by eleven points.
* **Silverman's critical bandwidth is not calibrated for heavy tails.** On a
  Student-t(3) it returns p = 0.016 and `h_crit/sd` = 3.20 against a clean
  mixture's 0.89. It is reported across arms and never as a p-value, and a test
  pins both behaviours so nobody reads it as one later.
* **The round grid is analytic, not a row set.** The first version emitted grid
  rows whenever the close moved two units, which produces a million rows a
  series and makes a density figure meaningless. It needs no history, so it is
  computed from the unit at the bar.
* **The `k = 0` placebo is capacity-bound and selected**, and both are reported:
  70,843 drawn of 337,592 wanted, 30.0 million draws rejected for overlapping an
  accepted placebo, 7.3 million for the matched price falling outside the bar
  and 3.4 million for being named. A de-overlapped single stream admits at most
  `bars / 48` placebos however many are asked for. `level-shield.md` hit the
  same wall from the other side - its clear arm was 7-9% of anchors, and "a
  clear path is a regime of its own" - so the placebo is read beside the walk
  and never instead of it.
* **120 duplicate bars** were dropped across 162 series by the unconditional
  timestamp de-duplication. The guard stays: a duplicate bar doubles a
  detector's firing rate in silence.
* **38 of 200 instrument-interval jobs were skipped as short** and named rather
  than reported - all of them 1d, where only 12 of 50 stores carry 1,200 UTC
  days.

## Re-running it

```
./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=overlap
./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=run
./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=calibrate
./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=power
./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=sweep
./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=cost
MODE=report uv run python research/ideas/confluence_levels.py
MODE=smoke  uv run python research/ideas/confluence_levels.py
uv run pytest research/ideas/test_confluence_levels.py
```

`MODE=run` writes `$OUT/obs.npz` (every observation as columns),
`$OUT/cells.csv` (every statistic quoted above) and `$OUT/overlap.csv`.
`MODE=report` re-prints every table from `obs.npz` without recomputing the
panel. The harness was staged **outside** `~/till_infinity/repo` and verified by
checksum on both sides, because `lab.sh sync` rsyncs with `--delete` and a
concurrent agent removes an untracked harness from under a running job.
