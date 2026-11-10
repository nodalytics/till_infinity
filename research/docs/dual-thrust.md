# Dual Thrust: the range sets the distance, nothing sets the side, and the clock sets the cost

Measured 2026-11-10 on the lab with
[`dualthrust.py`](../ideas/dualthrust.py), arithmetic pinned by
[`tests/test_dualthrust.py`](../../tests/test_dualthrust.py). 17 instruments at
15m (FX, metals, indices, a placebo pair and a positive control) and 27 at 1d
across three sources, **50,000 to 294,533 bars** a cell at 15m and **521 to
5,008** at 1d, **463,680 trades** at 15m and **14,864** at 1d on traded
instruments, with **six surrogate draws of three different nulls** beside every
one of them.

The source reports SPY **Sharpe -0.17** at a **41.1%** maximum drawdown while
its abstract says the rule "beat the market", models no costs and runs no
control - so there was no result to reproduce. What was worth measuring is the
*shape*: the trigger distance is scaled by a **measured range**, and the range
is the strongest volatility reading on this desk
([`candle-screen.md`](candle-screen.md): the range-vs-close estimator ratio is
**0.6484** within strata on FX at a forty-bar window, and holds on 371 of 392
equities).

## The verdict

| | |
|---|---|
| **Is the edge in the side?** | **No, and on the clock with power it is on the wrong side of its own null.** Against `reflect` - the real bars with their direction coined - the rule reads `-0.0515` units a trade pooled on 15m FX, `-0.0311` on metals and `-0.0103` on indices. Of **13** 15m cells, **4** are above the null, **5 survive Benjamini-Hochberg and none of those is positive**. At 1d, **10 of 23** above the null and **0 survive BH**: that clock has 100-1,000 trades a cell and cannot see an effect of this size. |
| **Is the distance's edge in the range?** | **There is no edge for the range to be in.** `const` - the same geometry with `range` replaced by a constant fixed on a training block - reads `+0.0106` against `reflect-const`'s `+0.0383` at 15m FX, the same story as the measured arm. Neither distance beats its own null, so the question "measured range or constant" has no winner to award. |
| **Does the rule carry the range at all?** | **Yes, and that is the one thing it does.** `K * range` at the published `N = 4, K = 0.5` lands at **0.775 to 0.969 of one bar's median range** (median 0.895) on every traded instrument at both clocks, and the rule flips every **5.0 bars** with a **duty cycle of 1.0 by construction**. It is a bar-scale reversal system, not a position system, and the published defaults put its trigger within one bar of the open at every clock tested. |
| **Does the positive control fire?** | **Yes, by a factor of 100 - and what it collects is the bar fill.** `Range Break 100/200 Index` read **`+1.5932`** and **`+1.1477`** units a trade where nothing traded reads above `+0.12`. So the detector is not blind to a planted range. But their **direction-free reflections read `+2.0430` and `+1.9393`** - more than the real arm, at `z -6.63` and `z -12.09` - and [`range-break-100.md`](range-break-100.md) already measured why: that generator breaks by a **jump of mean 99 units**, a bar replay fills the jump at the trigger, and the same arm reads **`+3.69R` on bars against `-0.199R` on ticks**. The control proves the detector works and proves the fill is not tradeable, in one number. |
| **Is it affordable?** | **At 1d yes, at 15m no except on the three US indices.** On the round trip the trades **actually** pay, every priced 1d cell clears the **0.16** ceiling at `0.0012` to `0.1568`, and at 15m **10 of 15 fail - all five FX pairs (`0.191` to `0.231`), both metals (`0.254` and `1.698`) and the three European and Asian indices**. Only US SP 500 `0.099`, US Tech 100 `0.047` and Wall Street 30 `0.074` pass. |
| **Is the 15m clock 19x dearer than 1d?** | **No, about 11x, and the reason is the unit.** Measured on one broker feed per instrument the ratio is `9.5x` to `12.7x`, median `11.0x`. A spread in R is 19x dearer at 15m when the risk unit is a **fixed** multiple of a short-clock ATR; here the unit is a 4-bar range which shrinks with the clock too, so the rule recovers about 40% of the penalty. |
| **Does a cost screen run before the rule give the rule's cost?** | **No, it understates it by a quarter, systematically.** A near trigger is easier to reach, so the trades taken are selected towards a small measured range: the trigger is `0.895` of a bar range unconditionally and `0.707` over the trades actually taken, and the realised round trip is **`1.21x` to `1.35x`** the screened one on 44 of 45 cells. Three 15m FX cells flip from pass to fail on that alone. |
| **Does the volatility stratum change the answer?** | **Not where there is power.** 15m FX reads `-0.0543, -0.0467, -0.0536` against the null across the three terciles - flat and negative in all of them. 1d FX reads `+0.1105, +0.0676, -0.0774`, a gradient favouring the quiet tercile, which **the 15m arm with a hundred times the trades does not reproduce**, and the 1d arm has no BH survivor at all. |
| **Does the placebo pair read anything?** | **No, which is the arm working.** Volatility 25 and Volatility 75 Index at 15m read `-0.0024` and `-0.0031` against their nulls, on 111,416 trades. |
| **Does the side-shuffle arm the brief asked for work?** | **No, and showing that is a result.** A trade-level side shuffle has expectation exactly zero, so it credits the rule with the harness's own fill offset: read against it, **4 of 36 traded cells survive BH and all four are positive**. Run the identical test on the **direction-free** `reflect` series and it passes on **57 of 216 rows, 52 positive**, median own-coin `z` **+3.41** on 15m traded cells. A null a direction-free series fails is not a null, so the side question is answered with `real - reflect` instead. |
| **What is the biggest number in the study?** | **An intra-bar convention the published rule does not specify.** Both triggers are reached on **7.5-8.1%** of the bars that move the position, and resolving those bars optimistically against pessimistically moves the pooled 15m mean from `+0.0364` to `-0.1599` - a span of **0.196 units, 13x the size of the effect being argued about** and 4x the harness's own offset. |
| **Can the published rule's P&L be measured at all?** | **Not from OHLC bars, and that is the study's second finding.** Two separate OHLC-only artefacts - the trigger-price fill worth `+0.03` to `+0.06` units a trade on a series with no direction in it, and the whipsaw convention worth `0.196` - are each larger than anything the rule is claimed to do. |
| **Is there a duty cycle to control for?** | **No, and there cannot be.** The trades tile the series back to back, so there is no outcome overlap to de-overlap and no flat state to compare against: every comparison here is **two always-invested series**. Nothing in this study needs a duty-cycle twin and nothing in it can have one. |
| **Should anything be built?** | **No.** Nothing here is wired and nothing should be. |

## What this is distinct from, and what it does not re-open

[`scalping.md`](scalping.md) already refuted an **opening-range breakout** and a
**20-bar level break** at 1m-15m with a 1xATR stop and a 2xATR target: null
after cost on 8 of 8, and the opening-range form worse than entering at random.
This is a different rule and the difference is the point:

* it is a **reversal** system with **no stop and no target**, so there is no
  1:(1+N) arithmetic to beat and no R to report;
* it is **always invested**, so the duty cycle is 1.0 and there is nothing to
  gate;
* its distance is a **measured range** rather than an ATR multiple or a session
  high, which is the one component this desk has a positive finding about.

What this does **not** re-open: a level attracting price
([`magnets.md`](magnets.md)), a rolling-quantile edge gate
([`docs/edge.md`](../../docs/edge.md)), or direction in any of the forms
[`findings.md`](findings.md) lists.
[`findings.md`](findings.md)'s *What does not work: direction* is why the side
arm was expected to read nothing, and it did.

## The trap: there is no flat state, so there is no duty cycle to control

Because the rule is always in the market, each exit **is** the next entry, in
index and in price - the harness asserts it - and the sides strictly alternate.
Three things follow and all three are unusual for this folder:

* **There is no outcome overlap to de-overlap.** The trades tile; they cannot
  share a forward window. The de-overlapping that
  [`overlapping-outcome-windows-leak`](findings.md) is about does not apply, and
  neither does a one-position-at-a-time filter, because there is only ever one
  position.
* **There is no duty cycle to match.** Every arm here runs at a duty cycle of
  **1.0 by construction**, so a same-keep-rate random twin - the control that
  has refuted every pause rule on this desk - has nothing to vary. Every
  comparison is two always-invested series.
* **So any variant that sits out is a different study.**
  [`strategy-switching.md`](strategy-switching.md) found every pause rule
  matching random pausing at the same duty cycle, which means a Dual Thrust
  variant with a flat state would have to be compared against its **own** duty
  cycle and not against this one. No variant measured here sits out.

The one thing that does replace the duty-cycle twin is the **drift** column:
an always-invested rule on a market that went somewhere beats a direction-free
null by its exposure, so `drift_u` - the instrument's mean step over the mean
hold, in trigger units - is reported beside every cell. On the 1d index cells
it reads `+0.3126` where the rule reads `-0.0379`.

## Cost first, because it nearly ended the study

The rule has **no stop**, so R is undefined. The unit here is the **trigger
distance** `K * range` at the bar that opened the trade, which is also what a
round trip divides into. Quotes are the terminal's own live bid/ask through
[`venue.quoted`](../harness/venue.py); the per-bar `spread` column is in
**points, not price** and is not used.

The first fact is structural. Unconditionally, at the published `N = 4,
K = 0.5`, the trigger sits at **0.775 to 0.969 of one bar's median range**
(median **0.895**) from the open, on every traded instrument at both clocks. So
"cost in trigger units" and "cost in bar ranges" are nearly the same number and
the warning that an exotic's round trip is a whole bar range applies directly.

**But the rule does not fire on an average bar, and this understates its cost by
a quarter.** A near trigger is easier to reach, so the trades taken are selected
towards a *small* measured range: over the trades actually taken the trigger is
**0.584 to 0.796** of a bar range (median **0.707**), which is `0.79x` the
unconditional figure, and the realised round trip is therefore **1.21x to 1.35x**
the screened one on 44 of 45 cells. A cost screen run before the rule is a
**systematic under-estimate of what the rule pays**, by a factor that is the
rule's own selection on its own distance.

| instrument | class | 15m screened | 15m **realised** | 1d screened | 1d **realised** | clock ratio |
|---|---|---|---|---|---|---|
| AUDUSD | fx | 0.1505 | **0.1918** | 0.0143 | 0.0181 | 10.5x |
| EURUSD | fx | 0.1800 | **0.2308** | 0.0158 | 0.0192 | 11.4x |
| GBPUSD | fx | 0.1471 | **0.1905** | 0.0132 | 0.0165 | 11.1x |
| USDCAD | fx | 0.1786 | **0.2247** | 0.0161 | 0.0202 | 11.1x |
| USDJPY | fx | 0.1463 | **0.1915** | 0.0131 | 0.0170 | 11.2x |
| XAUUSD | metal | 0.1946 | **0.2544** | 0.0177 | 0.0233 | 11.0x |
| XAGUSD | metal | 1.2857 | **1.6981** | 0.1199 | 0.1568 | 10.7x |
| Germany 40 | index | 0.4000 | **0.5176** | 0.0364 | 0.0427 | 11.0x |
| Japan 225 | index | 0.1944 | **0.4497** | 0.0180 | 0.0384 | 10.8x |
| UK 100 | index | 0.4480 | **0.5843** | 0.0472 | 0.0619 | 9.5x |
| US SP 500 | index | 0.0738 | 0.0993 | 0.0059 | 0.0075 | 12.4x |
| US Tech 100 | index | 0.0355 | 0.0471 | 0.0029 | 0.0037 | 12.4x |
| Wall Street 30 | index | 0.0554 | 0.0735 | 0.0044 | 0.0052 | 12.7x |
| Volatility 25 Index | placebo | 0.0785 | 0.0970 | 0.0079 | 0.0099 | 9.9x |
| Volatility 75 Index | placebo | 0.0094 | 0.0113 | 0.0009 | 0.0012 | 10.0x |

Bold is a failure against the 0.16 ceiling on the realised figure. **At 15m,
10 of 15 priced cells fail - including all five FX pairs and both metals -
where the unconditional screen failed only 7.** AUDUSD, GBPUSD and USDJPY flip
from pass to fail on the selection alone. The three affordable 15m cells are
US SP 500, US Tech 100 and Wall Street 30.

**At 1d nothing fails**, realised, and the worst cell is silver at **0.1568**,
just inside the ceiling. The 1d FX pairs from the price store run 0.0120 to
0.0942 (`usdcnh` is the 0.0942) and 1d gold reads 0.0211.

**The quote is a time of day.** Two readings were taken 35 minutes apart either
side of the European close. FX barely moved (EURUSD 0.160 to 0.180 screened,
the rest unchanged to three figures) and the US index names did not move at all,
but **Germany 40 went 0.055 to 0.400, UK 100 0.128 to 0.448 and gold 0.107 to
0.195**. So the European and Asian index cells *pass in their own session and
fail outside it*, the US index cells pass in both, and the FX, metal and silver
verdicts are the same either way. The table is the wider reading.

**The 19x figure does not transfer.** The 19x in
[`tradingview-survey.md`](tradingview-survey.md) is measured against a risk unit
that is a fixed multiple of the clock's own ATR. Here the unit is a **4-bar
range**, which also shrinks by roughly the square root of the clock ratio, so
the measured penalty is `9.5x` to `12.7x`, median `11.0x`. That is the rule's
one structural advantage over a fixed-ATR stop, and it is not enough: ten of
fifteen priced 15m cells still fail.

## The null, and why the arm this study was briefed to use is not one

This study was briefed to null itself on the Brownian-bridge arm in
[`entry_timing.walk_path`](../harness/entry_timing.py) - each bar a bridge of
sub-steps pinned to a real close-to-close step, so `open == previous close`
exactly and the extremes are the path's own - and
[`breaker-blocks.md`](breaker-blocks.md) records it reproducing a 2R race's
arithmetic rate at **0.3285** against **0.3333** where the broken
`walk_with_bar_geometry` arm read 0.3022. **Measured here it is not a null for
this rule**, and the reason is specific to this rule rather than a criticism of
that one.

**First, the machinery is right.** On a clean Gaussian walk the bridge **is** a
Brownian motion, so optional stopping requires exactly zero. The rule reads:

| sub-steps a bar | 30 | 120 | 480 | 1920 |
|---|---|---|---|---|
| mean units a trade | +0.1936 | +0.0983 | +0.0300 | **-0.0035** |
| z | +15.85 | +8.57 | +2.74 | **-0.32** |
| median range / median \|step\| | 1.94 | 2.09 | 2.17 | 2.20 |

At a resolved path the harness reads zero. The residual at a coarse path is the
**overshoot past a trigger between two visited points**: the path jumps by
`sigma / sqrt(sub)` a step, a bar triggers when some visited point passes the
trigger, and filling at the trigger rather than at that point is worth about
half a jump on each leg. At 120 sub-steps the jump is `0.01 / sqrt(120)` and the
median unit is `0.0103`, so one jump is `0.089` units; the measured residual is
`0.0983`. That is one jump a trade to within a tenth, and it halves as the path
is refined fourfold - `0.1936, 0.0983` is a factor of 1.97 against the `2.0` a
`1 / sqrt(sub)` scaling predicts.

**Second, pinned to real steps it is not a Brownian motion.** The free excursion
inside each bar carries the full step **standard deviation** while the pin is
drawn from a heavy-tailed empirical distribution, so a quiet bar comes out as
wicky as a violent one. The giveaway is the one ratio this rule is priced in:

| series | median range / median \|step\| | mean units a trade at 120 / 480 |
|---|---|---|
| EURUSD 15m, real | **2.37** | `-0.0078` (the real arm) |
| EURUSD 15m, `walk-path` | 3.23 / 3.36 | `-0.0965` / `-0.1646` |
| XAUUSD 15m, real | **2.45** | `+0.0514` |
| XAUUSD 15m, `walk-path` | 5.43 / 5.66 | `-0.5924` / `-0.6542` |
| XAGUSD 15m, real | **2.35** | `-0.0287` |
| XAGUSD 15m, `walk-path` | 7.53 / 7.86 | `-0.9101` / `-0.9667` |

Refining the path makes it **worse**, so it is the geometry and not the
discreteness. A rule whose trigger distance *is* a function of the bar range
cannot be nulled by an arm that gets the bar range wrong by a factor of three,
however well calibrated that arm is for a fixed barrier.

### `reflect`, and the offset both arms share

So the headline null is `reflect`: **every real bar kept exactly as it is, its
direction coined, its gap carried, the path laid back out continuous.** One coin
per bar covers the gap and the body together, so a bar that gapped up and closed
down keeps that relationship. It reproduces the geometry term by term on
EURUSD 15m:

| | median range | median \|step\| | range / \|step\| | median \|gap\| | gap = 0 share | kurtosis of step |
|---|---|---|---|---|---|---|
| real | 0.000570 | 0.000230 | 2.37 | 0.000000 | 0.565 | 46.53 |
| `reflect` | 0.000570 | 0.000230 | **2.37** | 0.000000 | 0.563 | 46.52 |
| `walk-path` 120 | 0.000743 | 0.000230 | 3.23 | 0.000000 | 0.735 | 41.88 |
| `walk-path` 1920 | 0.000787 | 0.000230 | 3.42 | 0.000000 | 0.735 | 41.88 |

`shuffle` is the same construction with the bar order permuted as well, so it
keeps the marginal and destroys the volatility clustering; the pair exist to say
whether an offset is the clustering, and **the answer is that it is not**. On
15m FX `reflect` reads `+0.0637` and `shuffle` `+0.0653`; on indices `+0.0490`
and `+0.0505`; on the placebo pair `+0.0549` and `+0.0865`. Removing the
clustering leaves the offset where it was, so what is left is the OHLC fill
assumption itself. Pooled over 264 cells and 3.47-4.18M trades the three nulls
read `reflect` **+0.1160**, `shuffle` **+0.1390** and `walk-path` **-0.2499**.

**And the nulls are not centred on zero, which is the reason they are run.** A
bar is four numbers, and the rule fills at a trigger inside `[low, high]` with
no intra-bar path to check it against. That assumption is worth **+0.03 to
+0.06 units a trade** on 15m FX and metals on a series with **no direction in
it at all**. Which means:

* **`real - reflect` is the statistic, and `real` against zero is not.**
* **The trade-level side shuffle is in the same position**, and this is the
  cleanest demonstration in the study. It takes the identical trigger distances
  firing at the identical times and coins the long/short choice, so its
  expectation is exactly zero by construction - which means it credits the rule
  with the fill offset. Read against zero, **4 of 36 traded cells survive BH
  and all four are positive**: US Tech 100 15m at `z +3.95`, USDJPY 15m at
  `z +6.16`, XAUUSD 15m at `z +4.44`, XAUUSD 1d at `z +2.54`. Run the same test
  on the **`reflect` arm**, which has no direction in it whatsoever, and it
  passes on **57 of 216 rows, 52 of them positive**, with a median own-coin `z`
  of **+3.41** on the 15m traded cells and `|z| > 1.96` on **65%** of them. A
  null that a direction-free series fails is not a null. The coin arm is
  reported throughout and is the statistic this study says not to use.

## The decomposition

Lead with the rate and the sample. Every cell is one instrument at one clock
with `N = 4, K = 0.5`; `real` is the rule, `refl` is the mean of six `reflect`
draws, `diff` is the statistic, `z` is `diff` over the two arms' combined
spread (the real arm's from a block bootstrap over contiguous runs of trades,
which is what carries the dependence between tiling trades), `drift` is what
being permanently long would have earned over the same hold in the same unit,
and `net` is `diff` less the quoted round trip.

### 15m, where the sample is 9,721 to 60,169 trades a cell

| symbol | class | bars | n | rate /1k | held | u/bar | real | refl | diff | z | const | c-refl | cost | net |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AUDUSD | fx | 294,533 | 58,915 | 200.0 | 5.0 | 0.70 | +0.0049 | +0.0682 | **-0.0632** | **-5.01** | -0.0003 | +0.0355 | 0.192 | -0.2550 |
| EURUSD | fx | 294,499 | 58,844 | 199.8 | 5.0 | 0.68 | -0.0078 | +0.0591 | **-0.0669** | **-5.09** | +0.0136 | +0.0529 | 0.231 | -0.2976 |
| GBPUSD | fx | 294,524 | 59,256 | 201.2 | 5.0 | 0.68 | -0.0139 | +0.0455 | **-0.0594** | **-4.71** | +0.0008 | +0.0514 | 0.190 | -0.2499 |
| USDCAD | fx | 294,517 | 60,169 | 204.3 | 4.9 | 0.71 | +0.0032 | +0.0634 | **-0.0602** | **-4.81** | -0.0036 | +0.0477 | 0.225 | -0.2849 |
| USDJPY | fx | 294,522 | 56,542 | 192.0 | 5.2 | 0.68 | +0.0774 | +0.0827 | -0.0053 | -0.36 | +0.0366 | +0.0542 | 0.191 | -0.1968 |
| XAUUSD | metal | 276,423 | 53,797 | 194.6 | 5.1 | 0.68 | +0.0514 | +0.0626 | -0.0113 | -0.71 | +0.0815 | +0.0955 | 0.254 | -0.2656 |
| XAGUSD | metal | 278,207 | 56,154 | 201.8 | 5.0 | 0.66 | -0.0287 | +0.0211 | **-0.0498** | **-2.79** | +0.0929 | +0.1281 | 1.698 | -1.7479 |
| Germany 40 | index | 50,000 | 9,811 | 196.2 | 5.1 | 0.68 | +0.0456 | +0.0224 | +0.0232 | +0.73 | -0.0120 | +0.0656 | 0.518 | -0.4945 |
| Japan 225 | index | 50,000 | 10,065 | 201.3 | 5.0 | 0.69 | +0.0379 | +0.0692 | -0.0313 | -0.94 | +0.0669 | +0.0946 | 0.450 | -0.4811 |
| UK 100 | index | 50,000 | 10,282 | 205.6 | 4.9 | 0.72 | -0.0713 | +0.0135 | -0.0848 | -1.61 | -0.0471 | +0.0129 | 0.584 | -0.6692 |
| US SP 500 | index | 50,000 | 10,031 | 200.6 | 5.0 | 0.69 | +0.0640 | +0.0535 | +0.0105 | +0.35 | +0.0033 | +0.0704 | 0.099 | -0.0888 |
| US Tech 100 | index | 50,000 | 9,721 | 194.4 | 5.1 | 0.68 | +0.1152 | +0.0938 | +0.0215 | +0.71 | +0.0121 | +0.0318 | 0.047 | -0.0256 |
| Wall Street 30 | index | 50,000 | 10,093 | 201.9 | 5.0 | 0.68 | +0.0458 | +0.0424 | +0.0035 | +0.11 | +0.0545 | +0.0674 | 0.073 | -0.0700 |
| Volatility 25 Index | placebo | 275,053 | 55,507 | 201.8 | 5.0 | 0.72 | +0.0579 | +0.0604 | -0.0024 | -0.25 | +0.0512 | +0.0431 | 0.097 | -0.0995 |
| Volatility 75 Index | placebo | 275,053 | 55,909 | 203.3 | 4.9 | 0.72 | +0.0463 | +0.0495 | -0.0031 | -0.35 | +0.1061 | +0.1013 | 0.011 | -0.0145 |
| Range Break 100 Index | **positive** | 50,000 | 12,266 | 245.3 | 4.1 | 0.57 | **+1.5932** | **+2.0430** | -0.4498 | **-6.63** | +2.5419 | +2.5854 | - | - |
| Range Break 200 Index | **positive** | 50,000 | 14,634 | 292.7 | 3.4 | 0.60 | **+1.1477** | **+1.9393** | -0.7916 | **-12.09** | +0.9208 | +2.1474 | - | - |

**The side carries nothing, and on four of five FX pairs and on silver it
carries less than nothing** - the real arm is below its own direction-free
reflection at `z -2.79` to `-5.09`. Of 13 traded 15m cells, 4 are above the null
and **5 survive Benjamini-Hochberg with none of them positive**. The placebo
pair reads `-0.0024` and `-0.0031` on 111,416 trades, which is the arm working.

**And the distance is not where it is either.** `const` reads `+0.0106` pooled
on 15m FX against `reflect-const`'s `+0.0383`, and `+0.0872` on metals against
`+0.1117`. Every arm sits at or below its own null, so the question "does the
*measured* range beat a constant" has no winner to award: both are nulls.

### 1d, where the sample is 97 to 1,014 trades a cell

| class | cells | trades | real | reflect | shuffle | walk | const | real - refl | drift |
|---|---|---|---|---|---|---|---|---|---|
| fx | 12 | 10,442 | +0.0268 | -0.0067 | -0.1018 | +0.0427 | -0.0950 | +0.0335 | -0.0053 |
| metal | 3 | 2,431 | +0.2019 | +0.1176 | +0.2122 | -0.6104 | +0.2430 | +0.0843 | **+0.2661** |
| index | 8 | 1,991 | **-0.0379** | +0.0474 | +0.0119 | +0.0379 | -0.0393 | -0.0853 | **+0.3126** |
| placebo | 2 | 1,160 | +0.1002 | +0.0417 | +0.0083 | +0.0629 | +0.0614 | +0.0585 | -0.0199 |
| positive | 2 | 203 | +0.2514 | +0.3344 | +0.1986 | +0.0888 | +0.1890 | -0.0830 | -0.0762 |

**The 1d clock cannot answer the question**: 10 of 23 traded cells are above
the null and **none survives BH**. The block-bootstrap standard error is 0.08 to
0.20 units a cell where the effect at 15m is 0.05, so this is a power statement
and not a null - see *Power*.

**The `drift` column is why the 1d positives are not an edge.** On the eight
index cells, being permanently long would have earned **+0.3126** units over the
same five-day hold while the rule earned **-0.0379**. Every null here coins or
demeans the direction, so an always-invested rule on a market that went
somewhere beats them by exposure; these cells do not even do that. Against the
source's own abstract - that the rule "beat the market" - the measurement is
that on indices at 1d it **gave away +0.35 units a trade of the market's own
drift**.

### The tail, which is where an edge of this shape would have to live

| clock | class | P(>= +1u) real | null | P(>= +2u) real | null | hit real | null |
|---|---|---|---|---|---|---|---|
| 15m | fx | 0.1963 | 0.2091 | 0.1241 | 0.1358 | 0.3295 | 0.3387 |
| 15m | metal | 0.1932 | 0.2053 | 0.1239 | 0.1332 | 0.3269 | 0.3349 |
| 15m | index | 0.2068 | 0.2084 | 0.1313 | 0.1349 | 0.3369 | 0.3370 |
| 15m | placebo | 0.2112 | 0.2113 | 0.1351 | 0.1355 | 0.3411 | 0.3414 |
| 15m | positive | 0.2221 | 0.3381 | 0.1913 | 0.2731 | 0.2796 | 0.4386 |

The real arm's right tail is **thinner** than its null's on every traded class,
and on the positive control by a third. There is no tail to lead with.

### Within volatility strata

Terciles of the entry bar's causal EWMA range, with the null's own terciles
beside them, `real - reflect`:

| clock | class | quiet | middle | loud |
|---|---|---|---|---|
| 15m | fx | -0.0543 | -0.0467 | -0.0536 |
| 15m | metal | -0.0206 | -0.0491 | -0.0237 |
| 15m | index | +0.0010 | -0.0291 | -0.0028 |
| 15m | placebo | +0.0171 | -0.0150 | -0.0105 |
| 15m | positive | -0.5667 | -0.5934 | -0.7533 |
| 1d | fx | **+0.1105** | +0.0676 | **-0.0774** |
| 1d | metal | +0.0985 | +0.1413 | +0.0134 |
| 1d | index | -0.0425 | -0.1786 | -0.0352 |

At 15m the answer is the same in all three terciles on every class, which is
what makes the pooled reading usable. The 1d FX gradient - the quiet tercile
`+0.1105`, the loud one `-0.0774` - is the one place a conditioning story could
start, and two things say not to start it: the 15m arm has **a hundred times the
trades and shows no trace of it**, and the 1d arm has no BH survivor at any
stratum. Reported as information, per the standing instruction that a regime
split is a gating condition rather than a verdict - but a gradient that reverses
between clocks and vanishes where there is power is a sampling story first.

### The positive control, and what it actually proves

`Range Break 100/200 Index` have a range by construction, so a range-breakout
rule that cannot see them is broken. The rule reads **+1.5932** and **+1.1477**
units a trade there against nothing above `+0.12` anywhere traded, so **it is
not broken**. What it collects is another matter.
[`range-break-100.md`](range-break-100.md) measured that generator off
55.5M ticks: a +/-1 walk in a range about 35 wide that breaks outward at an edge
with `p = 0.0101` **by a jump of mean 99**, landing on the far edge of the new
range, with the price a martingale. The same document reports its own frozen
trade at **+3.69R on a bar fill against -0.199R on a tick fill**, because a bar
replay fills a jump at the trigger price. This study's two independent arms say
the same thing without ticks:

* the **direction-free reflection** of Range Break reads `+2.0430` and
  `+1.9393` - **more** than the real arm, at `z -6.63` and `-12.09`;
* the **`const`** arm reads `+2.5419` there, so the planted range is not even
  needed to size the distance.

[`expansion.md`](expansion.md) already records the Deriv positives on Boom,
Crash and Range Break as bar-fill optimism. This is a third measurement of it,
and it is the cleanest available statement of what the trigger-price fill is
worth when the underlying move is a jump: **everything**.

## The multiplicity surface

`N = 4, K = 0.5` is the **pre-registered headline** because that is what the
source publishes, and the source's own statement that the parameters are fixed
"for demonstration" is what makes the published cell the honest one to lead
with. `N` and `K` were then swept **separately** - the two lines through the
published point rather than their product, because a grid would be a different
and larger claim - giving **313 cells on traded instruments**, 196 at 1d and
117 at 15m.

**Every swept cell has its own null**, and that is not optional. The first run
of this sweep was made without one and read EURUSD at 15m `K = 0.2` as
**`+0.1034` at `z +12.3`** against `-0.008` at `K = 0.5`, monotone in `K` and
on 164,583 trades. It is an artefact with an obvious shape once stated: the
fill offset is a **fixed price** per trade and the unit is `K * range`, so the
offset **in units** grows as `K` shrinks. The null does the same thing:

| clock | line | value | cells | trades | real | null | diff | cost | net |
|---|---|---|---|---|---|---|---|---|---|
| 15m | K | 0.2 | 13 | 1,300,662 | +0.0950 | **+0.1264** | -0.0313 | 0.764 | -0.7949 |
| 15m | K | 0.3 | 13 | 930,664 | +0.0505 | **+0.0869** | -0.0364 | 0.539 | -0.5758 |
| 15m | K | 0.5 | 13 | 463,680 | +0.0152 | +0.0551 | -0.0399 | 0.366 | -0.4056 |
| 15m | K | 0.7 | 13 | 235,556 | +0.0060 | +0.0586 | -0.0526 | 0.284 | -0.3362 |
| 15m | K | 1.0 | 13 | 97,923 | -0.0249 | +0.0612 | -0.0861 | 0.218 | -0.3042 |
| 15m | N | 2 | 13 | 856,080 | +0.0390 | +0.0792 | -0.0402 | 0.523 | -0.5628 |
| 15m | N | 4 | 13 | 463,680 | +0.0152 | +0.0551 | -0.0399 | 0.366 | -0.4056 |
| 15m | N | 6 | 13 | 291,313 | +0.0033 | +0.0468 | -0.0435 | 0.299 | -0.3428 |
| 15m | N | 10 | 13 | 149,504 | +0.0090 | +0.0459 | -0.0370 | 0.234 | -0.2707 |
| 15m | N | 20 | 13 | 54,703 | +0.0597 | +0.0349 | +0.0249 | 0.162 | -0.1374 |
| 1d | K | 0.2 | 23 | 40,917 | +0.0299 | +0.0028 | +0.0271 | 0.062 | -0.0346 |
| 1d | K | 0.3 | 23 | 29,189 | +0.0446 | +0.0349 | +0.0096 | 0.043 | -0.0331 |
| 1d | K | 0.5 | 23 | 14,864 | +0.0468 | +0.0151 | +0.0317 | 0.029 | +0.0029 |
| 1d | K | 0.7 | 23 | 7,614 | +0.0835 | +0.0216 | +0.0619 | 0.022 | +0.0396 |
| 1d | K | 1.0 | 18 | 2,900 | +0.0358 | -0.0353 | +0.0711 | 0.020 | +0.0514 |
| 1d | N | 2 | 23 | 27,196 | +0.0308 | +0.0314 | -0.0006 | 0.042 | -0.0429 |
| 1d | N | 4 | 23 | 14,864 | +0.0468 | +0.0151 | +0.0317 | 0.029 | +0.0029 |
| 1d | N | 6 | 23 | 9,111 | +0.0589 | -0.0349 | +0.0938 | 0.023 | +0.0704 |
| 1d | N | 10 | 23 | 4,273 | +0.0409 | -0.0488 | +0.0898 | 0.019 | +0.0713 |
| 1d | N | 20 | 17 | 1,049 | -0.0553 | -0.0807 | +0.0254 | 0.014 | +0.0115 |

**At 15m the swept surface is negative against its null at nine of ten points**
and `N = 20` - the one exception, at `+0.0249` on 54,703 trades - is still
`-0.1374` net. Of 117 cells, **32 are above the null where chance gives 58**,
and **37 survive BH with exactly one of them above it**: the significant cells
are the rule losing to a coined version of itself, led by EURUSD `N = 4,
K = 0.7` at `-0.1007`, `z -5.33`.

**At 1d the surface is uniformly positive against the null and uniformly
unpowered.** 107 of 196 cells are above the null where chance gives 98, 86 are
nominally net positive, and **three survive BH - all three of them `usdcnh`**,
at `N = 6, 10, 20` with `K = 0.5` on 502, 248 and 65 trades. They are nested
parameterisations of one instrument on one sample, so they are one cell and not
three; `usdcnh` is a managed currency, and what makes them significant is that
the **null** reads `-0.48` to `-1.32` there rather than that the real arm reads
anything unusual - reflecting a range-bound managed rate gives a diffusing
series with the same step sizes, which is the one place `reflect` is a poor
match for the thing it is reflecting. At the **published** cell `usdcnh` reads
`z +2.60`, which does not survive BH among the 23 headline cells.

**And this is what a sweep reported as a result would have selected.** The best
cell per instrument at 1d is `Germany 40` at `N = 6, K = 0.5` on **73 trades**
reading `+0.6912`, `UK 100` at `N = 4, K = 1.0` on **30 trades** reading
`+0.4930`, `usdjpy` at `N = 20, K = 0.5` on **49 trades** reading `+0.3974` -
and the `drift` column beside them reads `+0.4141`, `+0.8415` and `+0.5990`. The
best cells are thin and their size is the instrument's own drift. Every one of
them has `p > 0.15`.

## Power

A null is worth nothing without the strength at which the test goes blind, so
the effect was planted and swept. The plant is defined on the **series**, not
on the rule's trigger, so the detector has to find it: after a close that is
the highest or lowest of the last four, a continuation of `strength` trigger
units is added over the next four bars, as a cumulative offset to whole bars so
the bar geometry and the wickiness survive. It is planted on the `reflect`
surrogate, which has no direction of its own, and the whole pipeline is re-run
on the result.

A plant fires on every four-bar close extreme and a trade holds about five
bars, so a trade collects two to three plants; the **realised** gain per trade
is therefore 2.0x to 2.9x the planted strength, and the realised column is what
an effect should be compared against.

| clock | planted | realised gain | recovery | median z | detected on |
|---|---|---|---|---|---|
| 15m | 0.010 | **+0.0293** | 2.93x | +2.72 | **0.77** of instruments |
| 15m | 0.020 | +0.0502 | 2.51x | +4.53 | **1.00** |
| 15m | 0.050 | +0.1168 | 2.34x | +10.55 | 1.00 |
| 15m | 0.100 | +0.2396 | 2.40x | +18.95 | 1.00 |
| 15m | 0.200 | +0.5216 | 2.61x | +26.83 | 1.00 |
| 15m | 0.400 | +1.1805 | 2.95x | +32.21 | 1.00 |
| 1d | 0.010 | +0.0240 | 2.40x | +0.30 | **0.00** |
| 1d | 0.020 | +0.0435 | 2.18x | +0.59 | 0.00 |
| 1d | 0.050 | +0.1008 | 2.02x | +1.36 | 0.04 |
| 1d | 0.100 | **+0.2191** | 2.19x | +3.00 | **0.74** |
| 1d | 0.200 | +0.4868 | 2.43x | +6.02 | 0.91 |
| 1d | 0.400 | +1.1288 | 2.82x | +10.63 | 1.00 |

`detected` is the share of instruments whose planted mean clears its **own
unplanted** mean by 1.96 combined standard errors. It has to be that and not the
row's own p-value: the unplanted arm already beats its trade-level coin at
`z +4` to `+5` from the fill offset alone, so a detection rate read off the coin
test is 1.00 at a planted strength of zero. The first version of this table
said so, which is how the error was found.

**At 15m the test sees a realised `+0.029` units a trade on 77% of instruments
and `+0.050` on all of them.** The effect it was looking for is about `0.05` and
the effect it found is `-0.05`, so the 15m null is a measurement and not a blind
spot: it would have seen an edge half the size of the published rule's claim,
on every instrument.

**At 1d the test is blind below about `+0.10` realised units a trade** - where
it fires on 4% of instruments - and needs `+0.22` for 74%. Every 1d reading in
this study is inside that blind region, which is why the 1d half of the table is
reported as **unmeasurable** rather than as null. One hundred to a thousand
trades over up to nineteen years at a per-trade sd of 1.5 to 3 units is not a
sample that can resolve five hundredths of a unit, and no amount of care in the
harness changes that.

A second-order reading worth keeping: the plant **lowers the trade rate**, from
204 to 160 per thousand bars at `strength = 0.400`, because a drift widens the
measured range and pushes the triggers out. A rule whose trigger distance is
read off the range is self-damping in a trend, which is a mechanical reason a
range-scaled breakout captures less of a move than its geometry suggests.

## Refuted, and unmeasurable

### Refuted

1. **The side.** Dual Thrust's long/short choice carries no information that a
   coin at the same times and distances does not. On the clock with power the
   real arm is **below** its direction-free reflection on 4 of 5 FX pairs and on
   silver, at `z -2.79` to `-5.09`, and 5 of 13 cells survive BH with **none of
   them positive**. A planted continuation of a fifth the size would have been
   seen on 77% of instruments, and one of half the size on all of them.
2. **The measured range as the thing that makes the distance work.** The `const`
   arm - the identical geometry with the range replaced by a constant frozen on
   a training block - reads `+0.0106` pooled on 15m FX against its own null's
   `+0.0383`, and `+0.0872` on metals against `+0.1117`. Neither distance beats
   its own null, so there is no edge for the range to be the source of. This
   does **not** touch [`candle-screen.md`](candle-screen.md)'s finding that a
   range is the better **volatility** estimator; it says that a trigger placed
   at `K * range` is not thereby a trade.
3. **"It beat the market."** On 8 index cells at 1d the rule reads `-0.0379`
   units a trade where a permanent long over the same five-day hold reads
   `+0.3126` in the same unit. The source's own Sharpe of `-0.17` is the more
   accurate of its two statements.
4. **Small `K` as the better parameterisation.** The apparent monotone
   improvement as `K` falls - EURUSD 15m at `K = 0.2` reading `+0.1034`,
   `z +12.3`, on 164,583 trades - is the fill offset divided by a smaller unit.
   Its null reads `+0.1264` at the same cell, and the cost of the same cell is
   `0.764` units.
5. **The 15m clock for FX, metals and the non-US indices, on cost alone.** On
   the round trip the trades actually pay: EURUSD `0.231`, USDCAD `0.225`,
   USDJPY `0.192`, AUDUSD `0.192`, GBPUSD `0.191`, XAUUSD `0.254`, XAGUSD
   `1.698`, Germany 40 `0.518`, UK 100 `0.584`, Japan 225 `0.450`, against a
   ceiling of `0.16`. No signal argument is needed for ten of fifteen cells.

### Unmeasurable, which is the other half of the answer

1. **The published rule's P&L, from OHLC bars.** Both triggers are reached on
   **7.5-8.1%** of the bars that move the position, the published rule specifies
   no tiebreak, and the three defensible conventions span **0.196 units a
   trade** at 15m (`+0.0364` optimistic, `+0.0152` headline, `-0.1599`
   pessimistic) and `0.197` at 1d. That is **13x** the effect under discussion.
   Nothing in the source, and nothing in a bar, decides it. Settling it needs
   the intra-bar path - ticks - and then it is a different study.
2. **The level of the per-trade mean, from OHLC bars.** Filling at a trigger
   inside `[low, high]` is worth `+0.03` to `+0.06` units a trade on a series
   with no direction in it, and `+1.9` to `+2.0` on a jump process. Only
   *differences* against a matched null are readable here; absolute levels are
   not, and the trade-level coin arm - whose expectation is exactly zero - is
   therefore the wrong comparison and is reported as such.
3. **Anything at 1d.** 97 to 1,014 trades a cell, a block-bootstrap standard
   error of 0.08 to 0.20 units, and a test that fires on 4% of instruments at a
   realised `+0.10` and on 74% at `+0.22`. The 1d column is a power statement.
   It includes the one apparently strong result in the study, `usdcnh` at
   `N = 6, 10, 20`, which is three nested views of one 4,477-bar sample of a
   **managed** exchange rate and
   whose significance comes from the null reading `-0.48` to `-1.32` rather
   than from the real arm.
4. **Whether the 1d quiet-tercile gradient is real.** 1d FX reads `+0.1105`
   against the null in the quiet tercile and `-0.0774` in the loud one. The
   gradient is in the direction a conditioning story would want, the 15m arm
   with a hundred times the trades shows no trace of it, and the 1d arm has no
   BH survivor at any stratum. Reported as a gating condition that **has not
   been established**, per the standing instruction that a regime split is
   information rather than a verdict.
5. **The European and Asian index cells at 15m, on cost.** Germany 40 and
   UK 100 read `0.055` and `0.128` in session and `0.400` and `0.448` out of it
   - the quote is a time of day, and a single reading does not settle whether
   those cells are affordable.

### Two defects this found on the way

* **The 1d price store's `YAHOO` bars are malformed.** `gold` on `YAHOO` has
  **177 of 5,009 (3.53%)** bars whose high and low do not contain their own open
  and close, one with `high < low`, and **355 (7.09%)** with zero range, while
  four other venues of the same instrument carry 5,008 bars with none. Every FX
  pair's `YAHOO` 1d series is malformed too, at **1.86% to 5.10%**. The series
  was selected by this repository's usual "most bars" rule and produced the
  single largest positive cell in the first parameter sweep, **`+1.16` units a
  trade at `z +10.4`** on 1,973 trades. `db_series` now picks the venue by
  malformed share first and bar count second, and prints every candidate's
  share.
  **It was found by an assertion, not by looking**: `reflect` inverts a bar
  whose `high < low`, the assertion fired, and the cell came back as an `ERROR`
  row instead of as a number. An arm that cannot represent a bad bar is worth
  more than one that quietly trades it.
* **The first intra-bar convention had a side.** Firing the nearer trigger first
  and then the other puts the position on the second of a fixed order, and with
  `K1 == K2` the two distances are equal, so the position ended **short** on
  every whipsaw bar. On a hand-built momentum fixture it was short on every
  up-expansion. `once` - reverse the position and stop - is symmetric in the
  side by construction and is the headline; `close` and `adverse` bracket it.

## Re-running it

All computation on the lab, nothing on `tis`. The harness is staged outside
`repo/` because `lab.sh run` rsyncs with `--delete` and a second agent syncing
its own worktree removes it; `repo` goes on `PYTHONPATH` instead. Verify the
remote copy before trusting a run.

    ./.secrets/lab.sh run research/ideas/dualthrust.py MODE=cost
    ./.secrets/lab.sh run research/ideas/dualthrust.py MODE=leak  DT_WORKERS=16
    ./.secrets/lab.sh run research/ideas/dualthrust.py MODE=main  DT_WORKERS=16
    ./.secrets/lab.sh run research/ideas/dualthrust.py MODE=sweep DT_WORKERS=16
    ./.secrets/lab.sh run research/ideas/dualthrust.py MODE=power DT_WORKERS=16 \
        DT_NULLS=reflect DT_SURROGATES=4

always with `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1`. Cells
land in `out/dualthrust/cells-<mode>.csv`. `cost` runs first and is allowed to
end the study; `leak` runs the null arms alone and is the arm that found the
`walk-path` problem; `main` is the study; `sweep` is the multiplicity surface
with its own null; `power` plants the effect.

The null-calibration readings in *The null* - the sub-step sweep on a Gaussian
walk and the geometry table - come from a one-off probe rather than from a mode,
because they are a statement about the surrogate rather than about the rule. The
numbers are reproduced by `walk_path(series, rng, sub=S)` for
`S in (30, 120, 480, 1920)` on a `sigma = 0.01` Gaussian walk of 200,000 bars,
and by `wickiness` on each arm.

### Data

| population | source | instruments | bars a cell |
|---|---|---|---|
| 15m, `cache` | `data/seqlab` (FX, metals, placebo), `data/btc` (indices), `data/syn` (positive control) | 5 FX, 2 metals, 6 indices, 2 placebo, 2 control | 50,000 - 294,533 |
| 1d, `cache1d` | the same 15m feed folded into UTC days | the same 17 | 521 - 3,693 |
| 1d, `db` | `.data/prices/prices.db`, one venue per feed by malformed share then bar count | 7 FX, 1 metal, 2 indices | 3,006 - 5,008 |

The sequence cache holds no 1d and no indices at any interval, which is why
there are three sources rather than one. `cache1d` exists so the two clocks are
compared on **one venue** and so the synthetic controls have a 1d arm at all; a
UTC midnight boundary is a stated choice and not the broker's session open.
Equities are out of scope.
