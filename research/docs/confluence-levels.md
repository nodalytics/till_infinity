# Confluence: four frameworks name 98% of all prices, and `k` is a proxy for the bar's width

**Measured 2026-11-10** on the lab with
[`confluence_levels.py`](../ideas/confluence_levels.py) and
[`test_confluence_levels.py`](../ideas/test_confluence_levels.py). 50
instruments, 162 instrument-interval series, **6,276,645 bars** at 15m, 1h, 4h
and 1d, 1,067,861 de-overlapped observations.

The runs behind this document wrote to `~/conf/out/<mode>` on the lab -
`overlap.csv`, `cells.csv`, `obs.npz`, `power.csv`, `sweep.csv`,
`lifesweep.csv`, `calibrate.csv`, `cost.csv` - because the harness was staged
**outside** `~/till_infinity/repo`: `lab.sh sync` rsyncs with `--delete`, so a
concurrent agent removes an untracked harness from under a running job, and a
"launched" message is not evidence the code is there. Both copies were verified
by checksum. A `lab.sh run` of the same harness writes to the default
`.data/confluence`.

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
| **Is a confluence rare?** | **No, and this is the result worth reading first.** A price drawn at a matched arrival is named by at least one of the four frameworks **97.82% of the time** (3,259,135 of 3,331,801 draws), and **67.63%** of named first touches carry `k >= 2`. Confluence is the *modal* state of the price axis, not a selection from it |
| **Are the four frameworks four objects?** | **Partly.** Pairwise agreement over each pair's union is **0.3098** (fib-swing), **0.3058** (fib-gann), **0.2174** (gann-swing) and **0.059-0.063** for every pair involving the round grid. So the three history-driven frameworks share a fifth to a third of their levels and the round grid is nearly independent of all three - but they are dense enough (0.156 to 1.595 levels per volatility unit) that co-location needs no agreement to occur |
| **Does the hold rate rise with `k`?** | **Yes, and so does a walk's, by the same amount.** Traded instruments, `k >= 2` against `k = 1`, paired on days: real **+0.0142 +- 0.0022** [+0.0100, +0.0184] on 153,526 against 80,003 resolved observations; a driftless Brownian-bridge walk through the identical detectors reads **+0.0140 +- 0.0022** and a GARCH(1,1)-t(5) bridge reads **+0.0167 +- 0.0021** - *more* than the market. **Real minus walk is +0.0002 +- 0.0029** |
| **Does the comparison hold up across the parameters?** | **No, and this is the study's sharpest caveat.** Over **sixteen configurations** the **market's** gap is stable at **+0.0097 to +0.0191** and always positive, while the **walk's** runs **-0.0144 to +0.0491**, cleanly monotone in how dense the level book is. So the excess crosses zero inside the swept range - **+0.0269** at the sparsest tolerance, **-0.0314** at the densest - and an effect cannot change sign with the tolerance that defines "the same price". The null is not inert, so the excess is **not identified**; the pre-registered cell is where the two arms happen to coincide |
| **Is there a recency reading that survives?** | **No, and it was refuted on a prediction written before the run.** Three points on the level-life axis went the hypothesis' way, so `MODE=lifesweep` stated the prediction - the market's gap keeps rising as the life shortens, the walk's keeps falling, monotonically - and ran seven. **The market's gap turns over**, peaking at a life of 150 and falling back at 100 and 50, flat overall in a band from +0.0123 to +0.0184 with two turning points; the walk's is monotone across **0.0295** of hold rate, tracking the level density step for step. Three points looked like a mechanism; seven are a constant minus a ramp |
| **What is `k` actually measuring?** | **The width of the bar the arrival printed in.** The mean arrival-bar range over the *lagged* volatility unit is **1.202** at `k = 1` and **1.446** at `k >= 2`, and the hold rate is dominated by that width rather than by `k`: it falls from **0.5420 to 0.3792** across width quintiles on the market and from **0.6076 to 0.1995** on the walk, because the race's barriers are set from the lagged unit and in a bar that is wide for its regime both are close. **Within width quintiles the real gap is +0.0263 and the walk's is +0.0211** - a difference of about +0.005 where the pooled figures differ by +0.0238 - so the one configuration with a positive excess is a composition effect in the null arm |
| **Does any cell survive multiplicity?** | **3 of 131**, and none is among the ten largest gaps, so all three are small gaps on large samples. 93 cells are nominally positive where chance gives 65 and 16 have a lower bound above zero where chance gives about 3 - which is what a mechanical effect present in every cell looks like, since the walk arm has it too |
| **Is the outcome distribution bimodal?** | **No, and it is the opposite shape.** Excess kurtosis of the next-20-bar return is **+8.94 / +8.43 / +8.33** at `k = 1 / 2 / 3` - fat-tailed and unimodal, where bimodality requires it to be *negative*. Sarle's coefficient reads **0.087-0.096** against the 0.5556 flag. The two-component mixture beats one Gaussian by a huge margin (dBIC 11,379-13,286) and its fitted means are **0.10-0.12** pooled standard deviations apart: it is a **scale** mixture, which is a fat tail, not a location mixture, which is what two outcomes would be |
| **Is there a cascade after a break?** | **No.** Conditional on breaking, the move goes another `HOLD_VOL` unit through before returning to the level on **0.5241-0.5264** of breaks at every `k`, against **0.5465** at the matched placebo break and **0.5250-0.5317** on the walk. Realised volatility over the next 20 bars is **0.736-0.753** of a unit, flat in `k`; the excursion is **3.89-3.97** units, flat in `k` |
| **Does the harness see a level that is really there?** | **Yes, at twenty points.** `Range Break 100/200 Index` - a range by construction - holds on **0.3243 / 0.3215 / 0.3199** of arrivals against its own walk's **0.5282 / 0.5590 / 0.5293**. The detector finds a structure worth **-0.20 to -0.24** there, in the break direction, and **the `k` ladder inside it is flat, and if anything slopes the other way** |
| **Does it reproduce a known number?** | **Yes.** The round-number arm alone holds on **0.4924** of 1,117 arrivals against **0.5023** when joined, and the matched placebo holds on **0.5052** - against [`magnet.md`](../../docs/magnet.md)'s 44.9% reached at a level against 49.5% at an arbitrary price the same distance away, and [`focal-points.md`](focal-points.md)'s round-number bounce rate of 51.9% against a 53.1% placebo. Three constructions, three venues, the same sign: a level is not where price turns |
| **So is watchedness measurable this way?** | **No, and the reason is the first row.** A confluence count cannot be a measure of how many participants compute a price when the frameworks' own rules name 98% of all prices. What is refuted is this *observable*, not the hypothesis - see [What is unmeasurable](#what-is-unmeasurable) |

**The headline as a rate:** `k >= 2` arrivals hold on **0.5174 +- 0.0014** of
**153,526** resolved observations on traded instruments against **0.5032 +-
0.0018** at `k = 1` on **80,003** - and the same detectors on a driftless
Brownian-bridge walk read **0.5431 +- 0.0013** against **0.5290 +- 0.0019**.
The market's ladder is the walk's ladder shifted down, and the *excess* of the
market's `k` gap over the walk's is **+0.0002 +- 0.0029**. Standard errors are
block bootstraps over whole UTC days; **0.02-0.03% of races are censored**, so
the rate is not a reporting artefact of a short horizon.

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
| `gann` | the Square-of-9 wheel from **each** confirmed pivot, `((sqrt(a*s) + deg/180)^2)/s` at 45, 90, 135, 180, 270 and 360 degrees both signs, every rung alive for 500 bars | the anchor pivot's confirmation |
| `round` | the whole and half steps of the smallest power of ten at least 5 units wide (`rounds.py`'s rule) | always; it needs no history |

`gann` is in the study **precisely because it is the most arbitrary of the
four**: a Square of 9 has no mechanism, so if it added information the first
hypothesis would be a bug in the harness.

**Every pivot is an anchor, not only the latest**, because a practitioner
redraws the wheel when the swing changes - so the live book is the
superposition of every anchor inside the last 500 bars. That is most of why
`gann` is the densest framework of the four at 1.595 levels per volatility
unit, and it is reported rather than assumed.

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
| `swing` | 0.994 | 0.593 | 250,010 |
| `fib` | 0.987 | 0.970 | 401,678 |
| `gann` | 0.995 | **1.595** | 1,821,447 |
| `round` | 1.000 | 0.156 | analytic (no rows; it needs no history) |

| pair | share of the pair's union naming one price |
|---|---|
| `fib` - `swing` | **0.3098** |
| `fib` - `gann` | **0.3058** |
| `gann` - `swing` | **0.2174** |
| `gann` - `round` | 0.0626 |
| `round` - `swing` | 0.0593 |
| `fib` - `round` | 0.0591 |

| `k` of a named price | share of first touches |
|---|---|
| 1 | 0.3237 |
| 2 | 0.4450 |
| 3 | 0.2157 |
| 4 | 0.0155 |

**The answer is neither, and that is the finding.** The three history-driven
frameworks are not one object counted three times - a fifth to a third of their
union is shared, which is in the range `smc-primitives-overlap-and-are-closed`
records for detectors assumed to differ, and the round grid is nearly
independent of all three at 0.059-0.063. But **it does not matter**, because
they are dense enough that co-location needs no agreement. The Gann wheel alone
emits 1.60 levels per volatility unit; with a tolerance of 0.25 units a price
has a wheel rung within reach most of the time whatever else is nearby. The
placebo draw measures the consequence directly: of 3,331,801 matched arrivals
at a price inside the bar, **3,259,135 (97.82%) were named by at least one
framework** and only 72,666 were free. Two thirds of the named ones carry
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
| real / k=1 | 80,003 | 0.5032 | 0.0018 | [0.4995, 0.5066] | 0.5043 | 0.672 |
| real / k=2 | 83,656 | 0.5124 | 0.0020 | [0.5084, 0.5161] | 0.5127 | 0.588 |
| real / k>=3 | 69,870 | 0.5234 | 0.0020 | [0.5197, 0.5276] | 0.5238 | 0.728 |
| **placebo / k=0** | 49,751 | 0.5052 | 0.0023 | [0.5007, 0.5100] | 0.5060 | 0.509 |
| walkpath / k=1 | 81,404 | 0.5290 | 0.0019 | [0.5254, 0.5329] | 0.5285 | 0.622 |
| walkpath / k=2 | 82,146 | **0.5435** | 0.0017 | [0.5401, 0.5470] | 0.5432 | 0.580 |
| walkpath / k>=3 | 64,021 | 0.5425 | 0.0019 | [0.5389, 0.5465] | 0.5419 | 0.689 |
| garchpath / k=1 | 81,329 | 0.4983 | 0.0017 | [0.4951, 0.5017] | 0.4961 | 0.587 |
| garchpath / k=2 | 82,886 | 0.5138 | 0.0018 | [0.5103, 0.5174] | 0.5119 | 0.554 |
| garchpath / k>=3 | 65,367 | 0.5165 | 0.0020 | [0.5125, 0.5206] | 0.5140 | 0.629 |

The ladder is monotone on the real arm (0.5032, 0.5124, 0.5234), on the GARCH
arm (0.4983, 0.5138, 0.5165) and on the walk arm (0.5290, 0.5435, 0.5425) -
three arms, one shape.

| the comparison that decides, `k >= 2` minus `k = 1`, paired on days | gap |
|---|---|
| real | **+0.0142 +- 0.0022** [+0.0100, +0.0184] |
| walkpath | **+0.0140 +- 0.0022** [+0.0099, +0.0184] |
| garchpath | **+0.0167 +- 0.0021** [+0.0124, +0.0207] |
| real `k >= 2` against the matched placebo | +0.0122 +- 0.0026 [+0.0071, +0.0172] |

and the difference of differences, which is the number the study exists to
produce - the same days resampled across all four streams at once:

| how much further `k` moves the market than it moves a null | excess |
|---|---|
| real minus `walkpath` | **+0.0002 +- 0.0031** [-0.0059, +0.0060] |
| real minus `garchpath` | **-0.0025 +- 0.0029** [-0.0085, +0.0029] |

**A driftless walk, whose levels nobody computes and at which no order rests,
gains 0.0140 from confluence where the market gains 0.0142, and a GARCH bridge
gains more than either at +0.0167.** The walk arm is not a weaker version of
the effect; it is the whole effect, and the arm that carries this market's
volatility clustering overshoots it. The within-strata column moves the real
figures by at most 0.0011, so it is not the volatility regime either.

Per framework, alone against joined by at least one other - the "beyond each
framework alone" column the question asks for:

| framework | arm | alone | joined | gap | real minus walk |
|---|---|---|---|---|---|
| `swing` | real | 0.4956 (8,698) | 0.5195 (96,784) | +0.0239 +- 0.0055 | **+0.0079 +- 0.0078** |
| | walkpath | 0.5288 (9,997) | 0.5447 (93,999) | +0.0159 +- 0.0052 | |
| | garchpath | 0.4971 (9,905) | 0.5163 (94,891) | +0.0192 +- 0.0052 | |
| `fib` | real | 0.5050 (34,183) | 0.5193 (126,477) | +0.0143 +- 0.0031 | **-0.0013 +- 0.0041** |
| | walkpath | 0.5297 (38,378) | 0.5453 (120,811) | +0.0156 +- 0.0030 | |
| | garchpath | 0.5024 (38,324) | 0.5169 (122,220) | +0.0145 +- 0.0030 | |
| `gann` | real | 0.5037 (36,005) | 0.5199 (130,936) | +0.0162 +- 0.0028 | **+0.0017 +- 0.0042** |
| | walkpath | 0.5271 (31,293) | 0.5415 (115,272) | +0.0144 +- 0.0033 | |
| | garchpath | 0.4940 (31,544) | 0.5141 (118,636) | +0.0201 +- 0.0031 | |
| `round` | real | 0.4924 (1,117) | 0.5023 (26,353) | +0.0099 +- 0.0149 | **+0.0266 +- 0.0192** |
| | walkpath | 0.5513 (1,736) | 0.5346 (29,787) | -0.0167 +- 0.0123 | |
| | garchpath | 0.4936 (1,556) | 0.5103 (29,851) | +0.0167 +- 0.0123 | |

Every framework gains from company on the market, including the Square of 9 -
and every framework gains from company on a walk too, and on a GARCH bridge.
**All four `real minus walkpath` intervals contain zero**: [-0.0063, +0.0238],
[-0.0098, +0.0064], [-0.0063, +0.0094] and [-0.0127, +0.0642].
`a-control-is-only-for-a-named-property` applies to the Square of 9 row: a
framework with no mechanism gaining as much as the three with one (+0.0162
against +0.0239, +0.0143 and +0.0099) is the signature of an effect that
belongs to the construction rather than to any framework's content.

The double bottom, which is the commentary's specific claim about the swing
level, is measured on its own: a swing level that repeats an earlier one within
the tolerance holds on **0.5173 +- 0.0088** [0.4994, 0.5345] of 3,273 arrivals,
against the swing arm's own 0.5195 when joined and 0.4956 when alone - no
separation either way.

### The multiplicity table

**131 instrument-interval cells, 93 nominally positive** (chance gives 65),
**16 with a lower bound above zero** (chance gives about 3), **3 surviving
Benjamini-Hochberg**. None of the three is among the ten largest gaps - those
are the smallest samples, `AUDCAD/1h` at +0.2021 +- 0.0687 on 169 against 77
observations and `EURAUD/1h` at +0.1474 +- 0.0676 on 159 against 80 - and the
three that survive are 15-minute cells with ten thousand observations each:

| cell | gap | p | n k>=2 / k=1 |
|---|---|---|---|
| **`Volatility 75 Index`/15m** | **+0.0324 +- 0.0088** | 2.5e-04 | 9,791 / 5,194 |
| `EURUSD`/15m | +0.0272 +- 0.0081 | 8.1e-04 | 10,457 / 5,501 |
| `AUDUSD`/15m | +0.0272 +- 0.0082 | 9.8e-04 | 10,515 / 5,530 |

**The largest of the three is `Volatility 75 Index`**, which is one of the two
instruments carried precisely because they must read nothing: a generated
process with constant volatility and a published generator, where no
participant computes anything and no order rests anywhere.
`carry-an-independent-placebo-pair` says to carry two of them in every
relationship harness because they caught two leaks in one run, and this is a
third. A multiplicity-surviving cell in the arm that cannot have the property
is the clearest possible statement about what the other two are.

### The controls

| control | arm | k=1 | k=2 | k>=3 |
|---|---|---|---|---|
| **`Range Break 100/200`**, the level positive control | real | **0.3243 +- 0.0099** | 0.3215 +- 0.0101 | 0.3199 +- 0.0122 |
| | walkpath | 0.5282 +- 0.0100 | 0.5590 +- 0.0101 | 0.5293 +- 0.0110 |
| **`Volatility 25/75`**, the independent placebo pair | real | 0.4828 +- 0.0043 | 0.5022 +- 0.0043 | 0.5147 +- 0.0047 |
| | walkpath | 0.4789 +- 0.0044 | 0.4914 +- 0.0044 | 0.4974 +- 0.0051 |

`Range Break` is the row that makes the null readable. It is a range by
construction, its boundaries are levels that exist, and the harness finds them:
**-0.20 at `k = 1` and -0.24 at `k = 2` against its own walk**, in the *break*
direction, which is what a
process designed to break out of ranges should do. So the detectors are not
blind - they resolve a real level structure at twenty points - **and the `k`
ladder inside that structure is flat to three decimal places** (0.3243, 0.3215,
0.3199). Where levels matter most, confluence still carries nothing.

The placebo pair behaves as the traded book does, which is the second half of
the same reading: two generated processes with **constant volatility by
construction** produce a `k` ladder of **+0.0250** (0.4828 at `k = 1` against
0.5078 pooled at `k >= 2`) where the traded book produces **+0.0142**. A ladder
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
| real / k=1 | 80,024 | -0.171 | **+9.009** | 0.0857 | 2.526 | 0.005 | 13,124 | **0.103** |
| real / k=2 | 83,672 | -0.220 | **+8.541** | 0.0909 | 3.342 | 0.005 | 13,184 | **0.113** |
| real / k>=3 | 69,887 | -0.336 | **+8.535** | 0.0965 | 2.352 | 0.005 | 11,533 | **0.123** |
| placebo / k=0 | 49,759 | +0.125 | +6.550 | 0.1063 | 0.894 | 0.075 | 5,868 | 0.070 |
| walkpath / k=1 | 81,404 | -0.162 | +7.529 | 0.0975 | 1.404 | 0.015 | 6,623 | 0.137 |
| walkpath / k=2 | 82,146 | -0.056 | +7.326 | 0.0971 | 2.410 | 0.005 | 6,864 | 0.106 |
| walkpath / k>=3 | 64,021 | -0.279 | +7.294 | 0.1047 | 0.896 | 0.139 | 5,575 | 0.251 |
| garchpath / k=1 | 81,329 | -0.034 | +1.261 | 0.2349 | 0.282 | 0.602 | 1,674 | 0.051 |
| garchpath / k=2 | 82,886 | -0.067 | +1.202 | 0.2390 | 0.298 | 0.716 | 1,691 | 0.081 |
| garchpath / k>=3 | 65,367 | -0.009 | +1.874 | 0.2052 | 1.300 | 0.055 | 1,614 | 0.066 |

**Every statistic points the other way.** Excess kurtosis is **positive and
large** at every `k` - +9.01, +8.54, +8.54 - so the distribution is a single
sharp peak with heavy tails, which is the shape this desk measures everywhere
and the exact opposite of two separated outcomes. Sarle's coefficient is
**0.086 to 0.097** against the 0.5556 flag, and a uniform distribution reads
exactly 0.5556. And the mixture is the clean answer: two Gaussians beat one by
11,533 to 13,184 BIC points, which is enormous, **and their fitted means are
0.10 to 0.12 pooled standard deviations apart**. That is a *scale* mixture - one mean, two variances - which
is how a two-component fit represents a fat tail, and it is not a *location*
mixture, which is what "defend or break" would be. The study's own positive
control pins the distinction: on a planted 50/50 mixture at +-3 sd the same
estimator returns a separation above 1.5, and on a pure scale mixture it returns
below 0.5.

**Silverman's p is reported and not interpreted, and the reason is in the
tests.** The critical-bandwidth test over-rejects on heavy tails - on a
Student-t(3) it returns p = 0.016 - because a handful of extreme points are
isolated bumps that only a very wide kernel smooths away. Read across arms it
says nothing: the walk rejects unimodality at p = 0.005 and 0.015 on two of its
three buckets, as hard as the market does, while the GARCH bridge - whose
kurtosis is +1.2 rather than +8.5 - does not reject at all (p = 0.60, 0.72).
The statistic is tracking the tail weight, which is what a critical bandwidth
divided by a tail-inflated standard deviation would do.

## Outcome 3: the cascade

Conditional on *breaking* (price travelled 1.0 unit through), over the next 20
bars: `went on` races another unit through against a return to the level, which
on a martingale is 0.5 by symmetry.

| arm / bucket | n breaks | went on | se | realised / unit | excursion / unit |
|---|---|---|---|---|---|
| real / k=1 | 39,745 | 0.5294 | 0.0026 | 0.7512 | 3.9502 |
| real / k=2 | 40,790 | 0.5237 | 0.0029 | 0.7355 | 3.8699 |
| real / k>=3 | 33,302 | 0.5259 | 0.0028 | 0.7545 | 3.9719 |
| **placebo / k=0** | 24,615 | **0.5448** | 0.0033 | 0.7786 | 4.0181 |
| walkpath / k=1 | 38,339 | 0.5288 | 0.0026 | 0.6672 | 3.6425 |
| walkpath / k=2 | 37,498 | 0.5225 | 0.0027 | 0.6627 | 3.6096 |
| walkpath / k>=3 | 29,291 | 0.5342 | 0.0030 | 0.6692 | 3.6801 |
| garchpath / k=1 | 40,799 | 0.5276 | 0.0025 | 0.6836 | 3.5482 |
| garchpath / k=2 | 40,297 | 0.5264 | 0.0027 | 0.6840 | 3.5589 |
| garchpath / k>=3 | 31,603 | 0.5230 | 0.0026 | 0.6865 | 3.5624 |

**There is no cascade and `k` is not in it.** Continuation after a break is
flat across `k` to within a standard error on all three arms, and the arm that
continues *most* is the **matched placebo break at a price no framework names**
(0.5448). Realised volatility and excursion are
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
| fx | 0.5203 | 0.0018 | 82,129 |
| metal | 0.5205 | 0.0030 | 29,460 |
| crypto | 0.5128 | 0.0043 | 14,659 |
| energy | 0.5084 | 0.0073 | 4,609 |
| index | 0.5078 | 0.0041 | 22,669 |
| deriv | 0.4795 | 0.0022 | 67,672 |

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

`k` is not an independent label. Two things about an arrival move with it, and
both are recorded so the question can be asked rather than argued: **where in
its bar** the touched price sat, and **how wide that bar was** for its regime.

### What `k` is a proxy for: the arrival bar's width

Quintiles of the arrival bar's range over the **lagged** volatility unit - the
same unit the race's barriers are set from - at the pre-registered tolerance:

| quintile of bar range / unit | real k=1 | real k>=2 | gap | walk k=1 | walk k>=2 | gap |
|---|---|---|---|---|---|---|
| [0.028, 0.806) | 0.5518 | 0.5582 | +0.0063 | 0.6136 | 0.6218 | +0.0082 |
| [0.806, 1.006) | 0.5463 | 0.5621 | +0.0157 | 0.6395 | 0.6428 | +0.0034 |
| [1.006, 1.232) | 0.5429 | 0.5523 | +0.0095 | 0.6185 | 0.6280 | +0.0095 |
| [1.232, 1.615) | 0.5111 | 0.5298 | +0.0187 | 0.5277 | 0.5330 | +0.0053 |
| [1.615, 113.58) | **0.4144** | 0.4232 | +0.0088 | **0.1975** | 0.2149 | +0.0174 |
| **equal weight** | | | **+0.0118** | | | **+0.0087** |

and the same table from the tight-tolerance run, where the excess over the walk
is largest:

| quintile of bar range / unit | real k=1 | real k>=2 | gap | walk k=1 | walk k>=2 | gap |
|---|---|---|---|---|---|---|
| [0.043, 0.784) | 0.5420 | 0.5485 | +0.0065 | 0.6076 | 0.6115 | +0.0039 |
| [0.784, 0.978) | 0.5423 | 0.5601 | +0.0177 | 0.6185 | 0.6387 | +0.0202 |
| [0.978, 1.193) | 0.5201 | 0.5491 | +0.0290 | 0.6076 | 0.6249 | +0.0172 |
| [1.193, 1.554) | 0.4935 | 0.5286 | +0.0351 | 0.5139 | 0.5510 | +0.0370 |
| [1.554, 113.58) | **0.3792** | 0.4222 | +0.0430 | **0.1995** | 0.2267 | +0.0272 |
| **equal weight** | | | **+0.0263** | | | **+0.0211** |

Three facts, and together they are the mechanism:

1. **The hold rate is dominated by bar width, not by `k`.** It falls from
   0.5518 to **0.4144** on the market and from 0.6136 to **0.1975** on the walk
   - a 14-point and a 42-point swing, against a `k` effect of one to two points
   - because the race's barriers are set from the *lagged* unit, so in a bar
   that is wide for its regime both barriers are close and whichever the close
   is nearer to wins.
2. **`k` is a proxy for that width, and how strong a proxy depends on the
   tolerance.** At 0.10 the mean width is **1.202** at `k = 1` and **1.446** at
   `k >= 2` - a tight co-location needs a wide bar - while at 0.25 it is
   **1.434** against **1.391**, no confound at all. That is the whole reason
   the sweep is unstable: with a 14-to-42-point gradient, a small change in the
   width mix moves the pooled `k` gap by more than the gap itself.
3. **And the excess dissolves when width is held fixed.** At the tight
   tolerance the pooled figures are real +0.0123 against the walk's
   **-0.0115**, an excess of **+0.0238 +- 0.0029**; *within* width quintiles
   they are **+0.0263** against **+0.0211**, a difference of about **+0.005**.
   At the pre-registered tolerance, within quintiles, **+0.0118** against
   **+0.0087**, a difference of **+0.003**. Both land where the base cell's
   difference of differences already was: **+0.0002 +- 0.0031**.

The walk's pooled gap at the tight tolerance is negative only because its
`k >= 2` arrivals pile into the widest quintile, where its hold rate collapses
to 0.1975; within quintiles the walk's gap is positive in all five. **So the
one statistic in this study that could have been read as a finding - a positive
excess at a tight tolerance - is a composition effect in the null arm, and it
goes away when the arrival's own geometry is held fixed.**

### The displacement, which is not the mechanism

The other candidate, in quintiles of the signed displacement from the previous
close:

| quintile of \|displacement\| | real k=1 | real k>=2 | gap | walk k=1 | walk k>=2 | gap |
|---|---|---|---|---|---|---|
| [0.000, 0.257) | 0.5044 | 0.5188 | +0.0144 | 0.5221 | 0.5338 | +0.0117 |
| [0.257, 0.422) | 0.5018 | 0.5156 | +0.0139 | 0.5624 | 0.5721 | +0.0097 |
| [0.422, 0.605) | 0.5021 | 0.5157 | +0.0135 | 0.5778 | 0.5910 | +0.0132 |
| [0.605, 0.880) | 0.5091 | 0.5163 | +0.0072 | 0.5673 | 0.5838 | +0.0165 |
| [0.880, 29.978) | 0.4998 | 0.5200 | +0.0202 | 0.4073 | 0.4262 | +0.0189 |
| **equal weight** | | | **+0.0138** | | | **+0.0140** |

The displacement is **not** the mechanism at the pre-registered tolerance: the
gap survives inside every quintile and the equal-weight figure (+0.0138) is the
pooled one (+0.0142), and the walk's survives too at +0.0140. At the tight
tolerance it does part of the work - the walk's pooled -0.0115 becomes -0.0018
within displacement quintiles - but not all of it, which is what the width
table above finishes. What the displacement quintiles do show is how strongly
the *level* of the rate depends on the construction: the walk arm runs from 0.58
in the middle quintile to 0.40 in the top one, an 18-point swing driven by
nothing but where in its bar the touched price sat.

## Power: where the test goes blind

Two plants, because "can the estimator resolve a small effect" and "can the
detectors find a barrier" are different questions.

### The label plant: the smallest hold-rate lift this pipeline resolves

A share of `k >= 2` outcomes is overwritten with a hold and the share is swept.
A forced hold raises the gap by about `share x (1 - p0)`, and the question is
whether the whole pipeline - de-overlapped streams, day-block bootstrap, strata,
Benjamini-Hochberg - recovers it.

| planted share | k=1 | k=2 | k>=3 | `k >= 2` minus `k = 1` |
|---|---|---|---|---|
| 0.00 | 0.4885 | 0.5010 | 0.5111 | +0.0170 +- 0.0019 [+0.0133, +0.0207] |
| 0.01 | 0.4885 | 0.5059 | 0.5160 | +0.0219 +- 0.0018 [+0.0183, +0.0256] |
| 0.02 | 0.4885 | 0.5109 | 0.5209 | +0.0269 +- 0.0018 [+0.0234, +0.0306] |
| 0.05 | 0.4885 | 0.5255 | 0.5357 | +0.0416 +- 0.0018 [+0.0380, +0.0452] |
| 0.10 | 0.4885 | 0.5501 | 0.5602 | +0.0661 +- 0.0018 [+0.0623, +0.0697] |
| 0.20 | 0.4885 | 0.6003 | 0.6084 | +0.1154 +- 0.0019 [+0.1117, +0.1189] |

The response is linear at **+0.00492 of gap per 1% of planted holds** and the
gap's block standard error is **0.0019**, so the test resolves a lift of
**0.0038 of hold rate at two standard errors** - a plant of 0.8% of
observations. These figures are on the whole panel (337,592 observations, the
Deriv families included, because the plant run uses the real arm only); the
traded-only sample is 69% of it, so the traded figure is **0.0046**. For the
difference of differences against the walk, where the standard error is 0.0029,
the blind spot is **0.0058**.

**In realised units**, 0.0058 of hold rate in a 1:1 race is **0.0116R a trade**
- above XAUUSD's own 1d round trip of 0.0082R and well below its 15m one of
0.0832R. So the test is sensitive enough to see an effect that would be
tradeable at a daily clock, and it cannot rule out one worth less than the
spread at 15m. The measured excess over the walk is +0.0002 +- 0.0029.

### The geometric plant: can the detectors find a barrier at all?

A reflecting grid planted on a generated path at the round grid's own
**half-step**, which is a function of the price and the volatility unit and so
does not depend on the path - no circularity - then the whole four-framework
pipeline run on the result. Hold rate at prices the `round` framework names,
against the rest of the same series:

| reflection probability | EURUSD | XAUUSD | BTCUSD | US SP 500 | elsewhere on the same series |
|---|---|---|---|---|---|
| 0.00 | 0.5067 | 0.5760 | 0.5198 | 0.5629 | 0.512-0.575 |
| 0.50 | 0.5011 | 0.4967 | 0.5402 | 0.4901 | 0.514-0.577 |
| 0.90 | 0.5204 | 0.5317 | 0.5193 | 0.5301 | 0.504-0.575 |
| **0.99** | **0.8419** | **0.8370** | **0.8521** | **0.8417** | 0.559-0.602 |

**The probability is not the unit and that is the finding of this arm.** A
reflected sub-step is immediately retried by the next one, so with sixty
sub-steps a bar a barrier that reflects 90% of crossings transmits almost
everything and produces **no measurable lift**. At 0.99 the barrier is real and
the pipeline resolves it at once: **+0.28 to +0.33** of hold rate at the planted
price against the same series' unplanted prices, on 139 to 816 observations,
which is eight to twenty-five standard errors. The second-order effect is
visible too - a confining grid raises the hold rate *everywhere* on the series,
from 0.512-0.575 to 0.559-0.602 - which is what a global barrier should do and
is a check that the plant is a barrier rather than a label.

Together with `Range Break 100/200` reading **-0.20** against its own walk on
real data, the harness is shown to resolve structures of twenty to thirty points
immediately, and the label plant prices the small end at half a point.

## The sweep, reported whole

Nine configurations, every one with both arms, because a sweep that reports
only the real arm turns a grid into a search. `real` and `walk` are the
`k >= 2` minus `k = 1` gap; `excess` is the difference of the two.

| cell | real gap | walk gap | excess | n |
|---|---|---|---|---|
| **base** (tol 0.25, dist 1.0, life 500, swing 10) | +0.0156 +- 0.0022 | +0.0170 +- 0.0022 | **-0.0014** [-0.0075, +0.0047] | 154,053 |
| tolerance 0.10 | +0.0124 +- 0.0020 | **-0.0144** +- 0.0022 | **+0.0269** [+0.0211, +0.0323] | 139,893 |
| tolerance 0.50 | +0.0177 +- 0.0024 | **+0.0491** +- 0.0025 | **-0.0314** [-0.0380, -0.0253] | 155,972 |
| race distance 0.5 | +0.0187 +- 0.0022 | +0.0199 +- 0.0021 | -0.0012 [-0.0073, +0.0051] | 154,086 |
| race distance 2.0 | +0.0097 +- 0.0023 | +0.0134 +- 0.0022 | -0.0038 [-0.0098, +0.0020] | 150,497 |
| level life 150 | +0.0191 +- 0.0023 | **+0.0022** +- 0.0021 | **+0.0169** [+0.0112, +0.0225] | 124,297 |
| level life 1500 | +0.0097 +- 0.0024 | **+0.0279** +- 0.0023 | **-0.0182** [-0.0245, -0.0118] | 163,516 |
| 10 volatility strata | +0.0156 +- 0.0022 | +0.0170 +- 0.0022 | -0.0014 [-0.0075, +0.0047] | 154,053 |
| pivot reach 20 | +0.0126 +- 0.0023 | +0.0120 +- 0.0023 | +0.0006 [-0.0056, +0.0068] | 151,132 |

**Read the two middle columns before the third, because the third is the one
that moves and it is not the market that moves it.**

* **The market's gap is stable**: +0.0097 to +0.0191 over a fivefold change in
  tolerance, a fourfold change in race distance, a tenfold change in level life
  and a doubling of the pivot reach. It is positive in all nine.
* **The walk's gap is not**: -0.0144 to +0.0491, a 6.3-point range with a sign
  change, and it is cleanly monotone in **how dense the level book is**.
  Tolerance 0.10 (fewest co-locations) gives -0.0144, 0.25 gives +0.0170, 0.50
  gives +0.0491; level life 150 gives +0.0022, 500 gives +0.0170, 1500 gives
  +0.0279. A walk's `k` ladder is a function of book density and nothing else,
  which is what a geometry term looks like.
* **So the excess crosses zero inside the swept range**, and its sign is set by
  where on the density axis the configuration sits: +0.0269 at the sparsest
  tolerance, -0.0314 at the densest. Four of nine cells exclude zero, two in
  each direction. **An effect cannot change sign with the tolerance that
  defines "the same price"; a difference of two density-dependent geometry
  terms can, and does.**
* **The 10-strata cell is a no-op and is in the grid to prove it.** Strata enter
  the `within strata` column and not the gap, so an identical number there says
  the gap is not a strata artefact rather than saying the parameter does
  nothing.

The conclusion the sweep supports is narrower and firmer than the base cell's
alone: **the market's `k` gap of +0.010 to +0.019 sits inside the range the same
detectors produce on a driftless walk**, and there is no configuration at which
it stably exceeds it. The pre-registered cell is where the two happen to
coincide; the honest statement is not "the excess is zero" but "the excess is
not identified, because the null it subtracts is not inert". The cell with the
largest positive was then run in full, and its excess dissolves once the
arrival bar's width is held fixed - below.

`the-placebo-arm-selects-the-null` is the rule that applies: a null arm that
finds structure of its own - and +0.0491 is structure - is a reason to reject
the comparison, not to read its residual.

### The tight-tolerance cell run in full, because it is the one positive

The sweep's `tolerance 0.10` cell is where the excess is largest, so it was
re-run with every arm and every diagnostic rather than left as a line in a grid.
Tolerance 0.10 makes a confluence selective: `k = 1` is **57.43%** of named
first touches against 31.98% at the pre-registered tolerance, and `k >= 2` is
**42.57%** against 68.02%.

| arm / bucket | n | hold | block se | within strata | mean \|displacement\| |
|---|---|---|---|---|---|
| real / k=1 | 87,298 | 0.4962 | 0.0017 | 0.4969 | 0.465 |
| real / k=2 | 83,127 | 0.5032 | 0.0018 | 0.5043 | 0.560 |
| real / k>=3 | 56,082 | 0.5162 | 0.0023 | 0.5170 | 0.835 |
| placebo / k=0 | 63,005 | 0.5012 | 0.0020 | 0.5018 | 0.503 |
| walkpath / k=1 | 87,390 | 0.5436 | 0.0017 | 0.5433 | 0.455 |
| walkpath / k=2 | 80,810 | 0.5404 | 0.0018 | 0.5399 | 0.565 |
| walkpath / k>=3 | 49,125 | 0.5183 | 0.0022 | 0.5180 | 0.771 |
| garchpath / k=1 | 87,703 | 0.5042 | 0.0017 | 0.5033 | 0.449 |
| garchpath / k=2 | 82,633 | 0.5044 | 0.0017 | 0.5032 | 0.529 |
| garchpath / k>=3 | 53,816 | 0.5052 | 0.0022 | 0.5028 | 0.665 |

| the gap, `k >= 2` minus `k = 1` | value |
|---|---|
| real | **+0.0123 +- 0.0021** [+0.0084, +0.0164] |
| walkpath | **-0.0115 +- 0.0022** [-0.0156, -0.0072] |
| garchpath | **+0.0005 +- 0.0022** [-0.0037, +0.0048] |
| real against the matched placebo | +0.0072 +- 0.0024 [+0.0024, +0.0119] |
| **real minus walkpath** | **+0.0238 +- 0.0029** [+0.0179, +0.0290] |
| **real minus garchpath** | **+0.0117 +- 0.0030** [+0.0058, +0.0173] |

**Two things kill it, and both are in the table.**

First, **the two nulls disagree by half the effect**. The walk reads -0.0115 and
the GARCH bridge reads +0.0005 for the same quantity on the same bars, so the
"excess" is +0.0238 or +0.0117 depending on which surrogate is the null - and
the arm carrying more of this market's mechanical properties (clustering, fat
tails) is the one that leaves less residual. A difference of differences needs
an identified null, and two nulls a standard error apart from each other but
twelve points apart in the answer are not one.

Second, **it is a composition effect in the null arm**, which the width table
in [the mechanism](#what-k-is-a-proxy-for-the-arrival-bars-width) shows
directly: within quintiles of the arrival bar's width the real gap is +0.0263
and the walk's is +0.0211, a difference of about +0.005 rather than +0.0238.
The walk's pooled gap is negative only because its `k >= 2` arrivals pile into
the widest bars, where its hold rate collapses to 0.1995.

Multiplicity at this tolerance: **142 cells, 92 nominally positive, 18 with a
lower bound above zero, 2 surviving Benjamini-Hochberg** - and neither survivor
is among the ten largest gaps, so both are small gaps on large samples. The
largest cells are the usual small ones: `XPTUSD/4h` at +0.2056 +- 0.0832 on 86
against 56 observations.

### The sparse configuration: confluence made rare

The study's obvious weakness is density, so the frameworks were re-run with
their rules **sharpened** rather than their parameters nudged: two Fibonacci
ratios instead of four (0.618 and 0.786, the OTE zone the commentary names),
two Gann rungs instead of six (45 and 90 degrees), a minimum leg of 4.0 units
instead of 2.0, a level life of 150 bars instead of 500 and a tolerance of
0.15. Densities fall to **0.307 / 0.317 / 0.814 / 0.156** levels per volatility
unit, and a confluence becomes rare: `k = 1` is **75.50%** of named first
touches and `k >= 2` is **24.49%**.

| the gap, `k >= 2` minus `k = 1` | value |
|---|---|
| real | **+0.0102 +- 0.0023** [+0.0056, +0.0148] |
| walkpath | **-0.0178 +- 0.0025** [-0.0228, -0.0131] |
| **real minus walkpath** | **+0.0280 +- 0.0035** [+0.0212, +0.0351] |

Read on its own this is the hypothesis' best case and it looks like a result.
It is the same composition effect, larger: the mean arrival-bar width is
**1.300** at `k = 1` and **1.683** at `k >= 2` - the strongest confound of any
configuration, because a co-location inside 0.15 units from a thinner book
needs a wider bar still - and within width quintiles the real gap is
**+0.0312** against the walk's **+0.0241**, a difference of **+0.0071** rather
than +0.0280. Multiplicity: **135 cells, 81 positive, 14 with a lower bound
above zero, 1 BH survivor**, and the survivor is `Range Break 100 Index/4h`,
the positive-control process.

**And the market's own gap is the smallest of any configuration.** Sharpening
the definition of confluence from 0.25 to 0.15 units and halving the frameworks'
output takes the market's `k` gap from +0.0142 to **+0.0102**. If confluence
carried information that density was diluting, making it selective would raise
the market's gap. It lowers it, and only the null moves far.

### The level-life axis, with the prediction stated before the run

The tolerance disqualifies itself - an effect cannot depend on what counts as
"the same price" - but the **level life** is different in kind. It is how long
a level stays in the book, which is the closest thing in this harness to *how
long anybody is still watching*, and the first sweep's three points went the
right way for the hypothesis: the market's gap rose as the life shortened
(+0.0097, +0.0156, +0.0191 at 1500, 500 and 150) while the walk's fell
(+0.0279, +0.0170, +0.0022). So `MODE=lifesweep` was written with the
prediction in its docstring **before it ran**: *if it is recency, the market's
gap keeps rising as the life shortens and the walk's keeps falling,
monotonically, through 50 and 100 bars. If either series turns over, it is
neither.*

| level life | share `k >= 2` | `gann` density | real gap | walk gap | excess |
|---|---|---|---|---|---|
| 50 | 0.239 | 0.412 | +0.0131 +- 0.0025 | -0.0008 +- 0.0025 | +0.0139 [+0.0071, +0.0217] |
| 100 | 0.363 | 0.683 | +0.0155 +- 0.0023 | -0.0026 +- 0.0023 | +0.0181 [+0.0123, +0.0237] |
| 150 | 0.447 | 0.883 | **+0.0184 +- 0.0022** | +0.0024 +- 0.0021 | +0.0160 [+0.0099, +0.0231] |
| 300 | 0.588 | 1.280 | +0.0123 +- 0.0021 | +0.0050 +- 0.0022 | +0.0073 [+0.0011, +0.0131] |
| 500 | 0.676 | 1.595 | +0.0142 +- 0.0021 | +0.0166 +- 0.0022 | -0.0024 [-0.0085, +0.0040] |
| 1000 | 0.764 | 1.976 | +0.0131 +- 0.0022 | +0.0246 +- 0.0024 | -0.0115 [-0.0176, -0.0056] |
| 1500 | 0.798 | 2.172 | +0.0131 +- 0.0023 | +0.0287 +- 0.0022 | -0.0156 [-0.0219, -0.0094] |

**The prediction fails on the half that mattered.** The market's gap **turns
over**: it peaks at a life of 150 and comes *back down* to +0.0155 at 100 and
+0.0131 at 50, where recency says it should keep climbing. Over the whole axis
it is flat - seven values in a band from +0.0123 to +0.0184, mean +0.0142,
with no trend and two turning points - while the **walk's is monotone across
0.0295 of hold rate**, from -0.0026 at a life of 100 to +0.0287 at 1500,
tracking the `gann` density (0.41 to 2.17) step for step.

So the excess is monotone decreasing in the level life and crosses zero at a
life of about 450 **entirely because the walk's gap is**, and the one reading
that would have made the three-point pattern a recency effect is refuted on a
prediction written down before the data was seen. Three points looked like a
mechanism; seven points are a constant minus a ramp.

### The three configurations side by side

| configuration | share `k >= 2` | mean width k=1 / k>=2 | real gap | walk gap | pooled excess | **excess within width quintiles** |
|---|---|---|---|---|---|---|
| **base**, tolerance 0.25 | 0.676 | 1.434 / 1.391 | +0.0142 | +0.0140 | **+0.0002 +- 0.0031** | **+0.0031** |
| tolerance 0.10 | 0.426 | 1.202 / 1.446 | +0.0123 | -0.0115 | **+0.0238 +- 0.0029** | **+0.0052** |
| sparse rules, tolerance 0.15 | 0.245 | 1.300 / 1.683 | +0.0102 | -0.0178 | **+0.0280 +- 0.0035** | **+0.0071** |

The last two columns are the study. **The pooled excess ranges over four
hundred basis points of hold rate and tracks the width confound exactly; the
excess within width quintiles is +0.003 to +0.007 in all three.** That residual
is no longer configuration-dependent, and it is at or below the smallest lift
this pipeline can resolve - the label plant puts the blind spot at 0.0058 in
the difference of differences - so it is reported as a bound rather than as an
effect.

And the quantity that is stable across **all sixteen configurations run** -
nine in the sweep, seven on the life axis, plus the sparse rules and the tight
tolerance - is the market's own `k` gap: **+0.0097 to +0.0191**, mean about
+0.014, never negative and never twice its smallest value. What moves by six
times that range is the null.

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
2. **Confluence does not raise the hold rate beyond a walk at the
   pre-registered tolerance.** The gap is +0.0142 +- 0.0022 on the market,
   +0.0140 +- 0.0022 on a driftless Brownian-bridge walk through the same
   detectors and +0.0167 +- 0.0021 on a GARCH bridge, so the market sits
   between its two nulls. Of 131 instrument-interval cells 3 survive
   Benjamini-Hochberg and the largest of the three is `Volatility 75 Index`,
   a generated process that cannot have the property.
3. **The excess over a walk is not identified at any configuration**, and
   where it is positive it is a composition effect in the arrival bar's width:
   pooled +0.0002, +0.0238 and +0.0280 across three configurations, +0.0031,
   +0.0052 and +0.0071 within width quintiles.
4. **The recency reading is refuted on a pre-stated prediction.** The market's
   `k` gap does not rise as the level life shortens; it turns over at 150 bars
   and is flat across seven lives, while the walk's is monotone across 0.0295.
5. **The bimodality claim is refuted in the direction it was stated.** The
   next-20-bar return at a `k >= 2` arrival has excess kurtosis +8.54, Sarle
   0.091 against a 0.5556 flag, and a two-component mixture separated by 0.113
   standard deviations: one sharp mode with fat tails, not two outcomes.
6. **There is no stop cascade attributable to confluence.** Continuation after
   a break is 0.5237-0.5294 at every `k`, below the matched placebo's 0.5448,
   and realised volatility and excursion after a break are flat in `k`.
7. **The Square of 9 adds nothing, and that is a check rather than a result.**
   It gains +0.0162 +- 0.0028 from company, which is the size the other three
   gain (+0.0239, +0.0143, +0.0099). A framework with no mechanism behaving
   like the ones with mechanisms is the signature of an effect that belongs to
   the construction.
8. **A double bottom is not a better swing level**: 0.5173 +- 0.0088 on 3,273
   arrivals, flat against the swing framework's own rate.

## What is unmeasurable

**The first item is the methodological result of the study and it is why the
sweep behaves as it does.**

1. **Watchedness cannot be separated from its proxy by a surrogate, because a
   confluence count is a deterministic function of the bars.** Every framework
   here is a rule applied to the price series, so *any* surrogate that keeps the
   bars keeps the levels, and any surrogate that changes the bars changes the
   levels. There is therefore **no null that holds the level book fixed and
   removes only "many participants compute this price"** - which is exactly the
   contrast the hypothesis needs. What a surrogate actually varies is the book's
   **density** and the **arrival geometry**, and that is why the excess over a
   walk moves with the tolerance and the level life rather than staying put.
   Two of the arms make this concrete: at the tight tolerance the walk reads
   -0.0115 and the GARCH bridge reads +0.0005 for the same quantity on the same
   bars, a disagreement **the size of the effect being claimed**, and the arm
   that carries more of this market's mechanical properties is the one that
   leaves less residual. `let-the-shuffled-twin-name-the-mechanical-observables`
   says to use the highest-powered arm; here the two arms do not agree on what
   the null is.

   **The null this claim needs is a cross-instrument book, not a surrogate
   series.** Take instrument A's live levels, express each as a distance from
   the close in volatility units, and lay that book on instrument B's real bars
   over the same calendar. The bars are real, so the arrival geometry and the
   wickiness are real; the book has a real book's density and clustering; and
   nobody is watching those prices *on B*. That separates "a price four rules
   compute" from "a price many participants compute", which no surrogate of B's
   own bars can. This study's matched placebo is the one-level version of it;
   the full version is a different harness and is the thing to build if anyone
   reopens this.

2. **Watchedness measured as attention rather than as arithmetic.** How many
   screens actually draw the line is not visible at this venue: no DOM,
   `real_volume` is 0 and `tick_volume` is a quote count
   (`no-order-flow-and-no-real-volume`). A confluence count is a proxy for *how
   many frameworks a harness can compute*, and the two part company as soon as
   the frameworks are dense - which they are, by their own rules.
3. **The excess over a walk, at any configuration**, because the walk's own
   `k` gap is not stable and the excess is a difference of two numbers only one
   of which is a market measurement. Across sixteen configurations the market's
   gap moves from +0.0097 to +0.0191 while the walk's moves from -0.0144 to
   +0.0491, so the excess flips sign. A difference of differences is only as
   good as the stability of the null it subtracts, and what this study can
   report is a **bound**: within width quintiles the residual is +0.003 to
   +0.007, against a resolvable floor of 0.0058.
4. **The level of any hold rate**, for the construction reason above. Only
   differences between arms are quotable.
5. **Whether a *human* reading of "confluence" - a handful of levels a person
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
* **The dedupe scan width was fixed at one bucket** while the bucket grid is
  the tolerance at the *median* unit, so on a series whose volatility spans an
  order of magnitude a late row's tolerance is several buckets wide and the
  scan silently stopped de-duplicating in the violent regime with the most
  levels. Measured at 1h: **-0.9 to -1.9%** of rows on EURUSD (unit range
  3.9x), **-2.4 to -4.3%** on BTCUSD (5.0x) and **-4.5 to -8.4%** on XAUUSD
  (25.1x). It changes the level counts and densities only - `k` comes from
  `Book.names`, which searches a price window with the bar's own tolerance and
  never consults the grid - and the main panel was re-run with the fix, which
  moved the headline from +0.0156 to +0.0142 against a walk's +0.0154 to
  +0.0140 and changed no verdict. The power and tolerance sweeps were taken
  before it.
* **`cells.csv` carried the ten printed cells, not all of them**, so the three
  Benjamini-Hochberg survivors were counted in a summary line and absent from
  the file - which is the one row anybody would want to audit. Fixed, and the
  report now also prints any survivor outside the top ten. The survivors are
  named above *because* of the fix.
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
./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=lifesweep
./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=cost
MODE=report uv run python research/ideas/confluence_levels.py
MODE=smoke  uv run python research/ideas/confluence_levels.py
uv run pytest research/ideas/test_confluence_levels.py
```

and the two configurations this document reports beside the base one:

```
# the tight tolerance, where the excess over a walk is largest
MODE=run TOL_VOL=0.10
# the sparse rules, where a confluence is rare
MODE=run ARMS=real,walkpath TOL_VOL=0.15 LIFE=150 MIN_LEG_VOL=4.0 \
    FIB_RATIOS=0.618,0.786 GANN_DEGREES=45,90
```

`MODE=run` writes `$OUT/obs.npz` (every observation as columns),
`$OUT/cells.csv` (every statistic quoted above, one row per cell) and
`$OUT/overlap.csv`. `MODE=report` re-prints every table from `obs.npz` without
recomputing the panel. The harness was staged **outside** `~/till_infinity/repo`
and verified by checksum on both sides, because `lab.sh sync` rsyncs with
`--delete` and a concurrent agent removes an untracked harness from under a
running job.
