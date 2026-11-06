# The four Eve/Adam variants are separable and the rule is not: the hit rate clears 1/3 by less than its own day-block shuffle does, and loses to the stop it was given

Measured 2026-11-06 on the lab with [`eve_adam.py`](../harness/eve_adam.py) and reported with
[`eve_adam_report.py`](../harness/eve_adam_report.py), on bars pulled by
[`seqlab_pull.py`](../harness/seqlab_pull.py): 8 traded markets and 4 Deriv synthetics at a
15-minute base, **198,530 to 294,532 bars each (5.7 to 11.8 years)**, four timeframes, two swing
scales, **540 cells** and **24 surrogate series each** (12 i.i.d.-shuffled, 12
day-block-shuffled).

A trade rule rather than a census, so it is its own document. It uses the detector and barrier
machinery of [`chart-patterns.md`](chart-patterns.md) and inherits its controls.

**The rule.** An Eve-and-Adam double bottom, entered on the close that breaks above the
intervening peak, **stop at half the pattern height**, **target at the measure rule** - one
pattern height projected from the break-out. Reward-to-risk is therefore 2, and a driftless
walk answers exactly `1/(1+2) = 0.3333`.

| question | verdict |
|---|---|
| **Are the four variants separable at all?** | **Yes, and clearly.** The label comes from the bottom's **width**; a second criterion, its **duration**, is never used to label and agrees with it at Spearman **+0.70** and Cohen's kappa **+0.67**, with Adam bottoms lasting 2.77 bars against Eve's 7.46 - a gap of **1.51 standard deviations**. It holds on **12 of 12 instruments** (kappa 0.665 to 0.742) and on the generated markets too, which is what a geometric classification should do. So the four-way split is a real distinction and not a relabelling |
| **Does the rule beat 1/3?** | **Marginally, and by less than its own shuffled twin does.** Pooled over the traded panel's cells with 100 or more races, the rule hits **0.3569** on 26,217 races against the fair 0.3333 - and its **day-block twin hits 0.3644** and its i.i.d. twin **0.3714**. The real series is below its day-block twin on **4 of the 5 cells** - three of the four variants, and every double bottom together |
| **What does it pay?** | **Nothing, on any variant.** At the only cell where all four have a sample on all eight instruments, net of the quoted round trip: Eve-Eve **-0.130R**, Eve-Adam **-0.107R**, Adam-Eve **-0.166R**, Adam-Adam **-0.098R**, every double bottom **-0.120R**. Halving the stop doubled the cost in R to **0.14 to 0.20** on this panel, which lifts the break-even hit rate from 0.333 to **0.38-0.40**; the measured rates are 0.337 to 0.368 |
| **Is the excess over 1/3 a market property?** | **No - the generated markets have more of it.** At the same cell the four constant-generator synthetics read **0.3601** against the traded panel's **0.3521**. A constant-volatility GBM cannot have a directional edge, so whatever lifts the race above 1/3 is in the bar geometry and the volatility path, not in the pattern |
| **Does the geometry change anything?** | **No, which is `1/(1+N)` doing what it does.** The same patterns run as a 1:1 race read **0.4955 to 0.5089** on the traded panel and 0.4834 to 0.5160 on the generated one. Fair at 1:1 and fair at 2:1 |
| **Multiplicity** | **Benjamini-Hochberg against the day-block arm keeps 0 of 157 cells.** Against the i.i.d. arm it keeps 9, of which **8 have the real series *below* its walk** |
| Should anything be built? | **No.** |

## The claim, and what it adds to what is already measured

[`chart-patterns.md`](chart-patterns.md) ran a **generic** double bottom as a **1:1** race and
found it on 0.500, with its break-out direction (61.0% upward) reproduced by an i.i.d. shuffle
(60.9%). This rule is narrower in exactly two ways:

1. **The Eve/Adam sub-classification**, which that study did not make.
2. **The 2:1 geometry**, which it did not run.

Three results from it bear on this rule directly and are not rediscovered here:

* **The measure rule is volatility clustering.** 274 of 919 measure-rule-met cells survived BH
  against the i.i.d. walk at up to 2.5x its rate, and the **day-block shuffle reproduced it
  almost exactly** (head and shoulders 0.070 real, 0.045 i.i.d., **0.074 day-block**). This
  rule's *target is the measure rule*, so a hit rate above the i.i.d. walk is already explained.
  **The day-block arm is therefore the one that decides this rule**, and both are printed, in
  that order.
* **Halving the stop doubles the cost in R.** Cost in R is `cost_px / risk` and `risk` is the
  stop. At 1:1 - a stop twice as wide as this one - 6 of 8 traded instruments were already
  negative net of the quoted round trip.
* **The 1:1 race on these same events is the control**, recomputed here rather than quoted, so
  "0.500 at 1:1 and 0.333 at 2:1" is a statement about the same patterns.

## The rules, as frozen before the run

| | |
|---|---|
| detector | the double bottom of [`chart_patterns.py`](../harness/chart_patterns.py): three alternating pivots low-high-low over a `2L+1` zigzag, the two lows level within **0.15 of the pattern height**, `L` in {3, 8} |
| no look-ahead | a pivot at bar `i` is not known until `i+L`; a pattern counts at its **break-out bar**, the first close above the peak or below the lower low inside one pattern span of confirmation. Verified by truncating the series at a break-out bar and reproducing all 1,367 earlier break-outs **and their variant labels** exactly |
| the trade | long from the break-out close, target `+1.0` pattern height, stop `-0.5`, 200 bars. **The stop is taken when both fall in one bar**, which is the conservative reading |
| the null | `1/(1 + target/stop) = 1/3`, and the walk arms answer it for themselves rather than being handed it |
| **width** `w` | bars in the contiguous run containing the bottom whose **low** is within **0.25** of the pattern height above the bottom price |
| **duration** `d` | bars from the last **close** above half the pattern height down to the bottom, plus bars back up to the first close above that level. A different level, a different series, a different shape of count |
| the window | `[i-4, i+4]`, **fixed and independent of `L`** - see *Why the window is four bars* |
| the label | **from the width alone**: `Adam` at `w <= 2` (the description's "one- or two-bar spike"), `Eve` at `w >= 5`, **`unclassified` in between and reported, never forced into a bucket**. The duration is held back as the independent criterion |
| cells | `all`, the four variants, and `unclassified`, per instrument x timeframe x lookback |
| uncertainty | day-block bootstrap, 500 draws, 90% interval |
| below 100 races | reported with its `n` and read as noise, never dropped |

### Why the window is four bars

Measuring width and duration inside the **pivot's own** window caps the width at `2L+1` and
makes the whole classification a function of `L`: on a 200,000-step walk the mix went from 31%
Adam-Adam and 3.9% Eve-Eve at `L = 3` to 9.4% and 23% at `L = 8`. That is a statement about the
detector, not about the bottoms, so the window is fixed instead.

A fixed window has its own cost: a pattern whose break-out arrives before the right bottom's
window closes cannot be labelled without reading past the break-out, and would have to be
**dropped** - which selects on how fast the break-out came, a property of the trade. Four is the
largest half-window that drops **nothing**:

| half-window | dropped at `L = 3` | dropped at `L = 8` | Spearman(w, d) | kappa |
|---|---|---|---|---|
| **4** | **0%** | **0%** | **+0.667 / +0.675** | **+0.618 / +0.621** |
| 5 | 27% | 0% | +0.660 / +0.680 | +0.629 / +0.589 |
| 6 | 43% | 0% | +0.651 / +0.680 | +0.619 / +0.610 |
| 8 | 67% | 0% | +0.623 / +0.676 | +0.612 / +0.572 |

It is also where the two criteria agree best, which settled it.

## Result 0: the four variants are separable, and that is tested before anything is traded

The width labels the bottom; the duration never does, so their agreement is a test rather than a
restatement.

| | cells | bottoms | Spearman(w, d) | kappa | duration, Adam | duration, Eve | gap, sd | Adam share | Eve share | unclassified |
|---|---|---|---|---|---|---|---|---|---|---|
| traded, `L = 3` | 32 | 62,764 | **+0.700** | **+0.671** | 2.77 | 7.46 | **1.51** | 0.304 | 0.391 | 0.305 |
| traded, `L = 8` | 32 | 25,966 | **+0.735** | +0.414 | 3.83 | 8.64 | **1.71** | 0.182 | 0.590 | 0.228 |
| generated, `L = 3` | 16 | 34,240 | +0.671 | +0.631 | 3.11 | 7.30 | 1.50 | 0.199 | 0.427 | 0.375 |
| generated, `L = 8` | 16 | 15,224 | +0.686 | +0.181 | 4.68 | 8.75 | 1.80 | 0.062 | 0.703 | 0.236 |

Per instrument at 15m and `L = 3`, kappa runs **0.665 to 0.742** on all twelve - the eight
traded markets and the four generated ones alike - with Spearman 0.669 to 0.718 and the duration
gap 1.49 to 1.61 standard deviations. A geometric classification *should* behave identically on
a generated market, and it does.

**kappa is lower at `L = 8` (0.414 and 0.181) because the classes are lopsided there**, not
because the criteria disagree: an `L = 8` zigzag finds wider bottoms, so 59-70% are Eve and only
6-18% Adam, and kappa is prevalence-sensitive. Spearman, which is not, reads +0.735 and +0.686
at that scale - its highest values in the table.

**Between a third and a half of all patterns are `unclassified`** and stay that way: 0.305 of
bottoms at `L = 3`, and 51.6% of *patterns* on the traded panel (both bottoms must decide). That
cell is reported throughout rather than absorbed into the nearest variant.

### One criterion was tried and rejected, and the numbers are why

The first candidate for the independent criterion was the difference of the correlations with
the `V` and `U` templates of [`letter_shapes.py`](../harness/letter_shapes.py). **Those two
templates are 0.942 correlated** at this length, so their difference is a small residual of two
nearly identical things; it separated narrow bottoms from wide ones by **-0.03 to +0.07 standard
deviations** for a kappa of **+0.001 to +0.020**. Orthogonalising `U` out of `V` did not help
(kappa -0.021 to -0.001).

The second was `roundedness`, the R-squared of a quadratic minus the R-squared of a V kinked at
the bottom - the literal "wide and rounded" against "V-shaped". It reads kappa **+0.034 to
+0.116** across the panel. A parabola and a kinked line fit a noisy nine-bar path about equally
well. It is computed and printed on every real cell so the rejection is visible, and it is not
used.

## Result 1: the rule, per variant

At **15m, `L = 3`** - the only cell where all four variants have a sample on all eight traded
instruments. `hit` is P(target before stop); the fair rate is 0.3333.

| variant | cells | races | **hit** | i.i.d. walk | **day-block walk** | cost in R | **net, R per trade** | the same events at 1:1 |
|---|---|---|---|---|---|---|---|---|
| Eve-Eve | 8 | 1,604 | 0.3370 | 0.3677 | **0.3495** | 0.141 | **-0.130** | 0.4859 |
| **Eve-Adam** | 8 | 1,718 | **0.3504** | 0.3735 | **0.3613** | 0.158 | **-0.107** | 0.4981 |
| Adam-Eve | 8 | 1,055 | 0.3386 | 0.3678 | **0.3461** | 0.182 | **-0.166** | 0.4976 |
| Adam-Adam | 8 | 1,894 | 0.3680 | 0.3762 | **0.3632** | 0.202 | **-0.098** | 0.5089 |
| *unclassified* | 8 | 8,456 | 0.3531 | 0.3766 | 0.3608 | 0.180 | -0.120 | 0.4879 |
| **every double bottom** | 8 | 14,727 | **0.3521** | 0.3742 | **0.3589** | 0.176 | **-0.120** | 0.4925 |
| *the four generated markets* | 4 | 7,717 | *0.3601* | *-* | *0.3538* | *0.023* | *+0.058* | *0.5017* |

Three readings:

* **Every variant clears 1/3 by between +0.004 and +0.035, and every one is below its own
  day-block twin except Adam-Adam** (+0.005). The named rule, Eve-Adam, reads 0.3504 where a
  day-block shuffle of the same returns reads 0.3613.
* **Every variant loses money.** The cost line is the reason: at a stop of half a pattern
  height the quoted round trip is 0.14 to 0.20 R on this panel, so break-even is
  `(1 + cost) / 3` = **0.380 to 0.401**, and nothing comes close.
* **The generated markets read higher than the traded ones** - 0.3601 against 0.3521 - and show
  a *positive* net only because their round trip is 0.023 R against the traded panel's 0.176.

Pooled over every cell with 100 or more races, race-weighted:

| variant | races | hit | i.i.d. | day-block | hit - fair | hit - day-block |
|---|---|---|---|---|---|---|
| every double bottom | 26,217 | 0.3569 | 0.3714 | 0.3644 | +0.0236 | **-0.0075** |
| Eve-Eve | 3,195 | 0.3465 | 0.3646 | 0.3574 | +0.0132 | **-0.0109** |
| Eve-Adam | 1,844 | 0.3530 | 0.3714 | 0.3629 | +0.0197 | **-0.0099** |
| Adam-Eve | 1,055 | 0.3374 | 0.3679 | 0.3454 | +0.0041 | **-0.0080** |
| Adam-Adam | 1,894 | 0.3680 | 0.3761 | 0.3631 | +0.0347 | +0.0049 |

The day-block arm's own spread across its 12 draws is **0.020 to 0.032**, so a gap of -0.008 is
a third of one draw's variation - the real series and its day-block twin are indistinguishable
here, which is the finding.

### Per instrument, never only pooled

Every double bottom, 15m, `L = 3`:

| instrument | patterns | races | hit | 90% interval | p vs 1/3 | i.i.d. | day-block | cost R | **net R** | 1:1 |
|---|---|---|---|---|---|---|---|---|---|---|
| EURUSD | 1,987 | 1,986 | 0.3389 | [0.321, 0.355] | 0.640 | 0.3633 | 0.3484 | 0.130 | **-0.113** | 0.466 |
| GBPUSD | 1,918 | 1,916 | 0.3377 | [0.320, 0.357] | 0.700 | 0.3716 | 0.3451 | 0.116 | **-0.103** | 0.474 |
| USDJPY | 1,877 | 1,875 | 0.3653 | [0.345, 0.383] | 0.016 | 0.3808 | 0.3825 | 0.112 | **-0.016** | 0.506 |
| AUDUSD | 1,928 | 1,924 | **0.3753** | [0.355, 0.392] | **0.002** | 0.3685 | 0.3584 | 0.103 | **+0.023** | 0.507 |
| USDCAD | 2,076 | 2,076 | 0.3565 | [0.339, 0.374] | 0.036 | 0.3662 | 0.3654 | 0.126 | **-0.057** | 0.497 |
| XAUUSD | 1,711 | 1,709 | 0.3528 | [0.334, 0.372] | 0.092 | 0.3809 | 0.3647 | 0.074 | **-0.015** | 0.497 |
| XAGUSD | 1,717 | 1,716 | 0.3357 | [0.316, 0.355] | 0.828 | 0.3830 | 0.3455 | **0.627** | **-0.620** | 0.483 |
| BTCUSD | 1,529 | 1,525 | 0.3548 | [0.335, 0.376] | 0.072 | 0.3792 | 0.3615 | 0.119 | **-0.054** | 0.510 |
| *Volatility 75 Index* | 2,114 | 2,113 | 0.3483 | [0.332, 0.366] | 0.168 | 0.3660 | 0.3484 | 0.005 | *+0.040* | 0.501 |
| *Volatility 25 Index* | 2,122 | 2,121 | 0.3621 | [0.345, 0.380] | **0.008** | 0.3697 | 0.3519 | 0.054 | *+0.032* | 0.510 |
| *Step Index* | 2,065 | 2,064 | 0.3425 | [0.324, 0.362] | 0.424 | 0.3550 | 0.3479 | 0.018 | *+0.009* | 0.484 |
| *Jump 75 Index* | 1,420 | 1,419 | **0.3876** | [0.365, 0.409] | **0.002** | 0.3710 | 0.3670 | 0.012 | *+0.151* | 0.512 |

**One traded instrument is positive net of cost: AUDUSD, +0.023R.** It is also the one
instrument above both of its own walks (0.3753 against 0.3685 i.i.d. and 0.3584 day-block) -
one cell out of eight, which is what a BH count of zero against the day-block arm across 157
cells is there to correct for. Two generated markets reach p<0.01 against 1/3 - `Volatility 25 Index` and
`Jump 75 Index`, the latter the highest hit rate in the whole table at 0.3876 - and a
constant-generator synthetic cannot have a directional edge. That is the control that must come
back empty failing to, and it is what pins the reading: **the right comparison is the gap to the
walk, not the gap to 1/3.**

The named rule, Eve-Adam, per instrument at the same cell:

| instrument | patterns | hit | 90% interval | p vs 1/3 | day-block | cost R | **net R** |
|---|---|---|---|---|---|---|---|
| EURUSD | 242 | 0.3512 | [0.307, 0.400] | 0.604 | 0.3732 | 0.121 | -0.067 |
| GBPUSD | 205 | 0.3268 | [0.278, 0.381] | 0.824 | 0.3550 | 0.100 | -0.119 |
| USDJPY | 218 | **0.4009** | [0.347, 0.456] | **0.028** | 0.4005 | 0.107 | **+0.095** |
| AUDUSD | 258 | 0.3580 | [0.310, 0.409] | 0.376 | 0.3400 | 0.094 | -0.020 |
| USDCAD | 257 | 0.3696 | [0.323, 0.425] | 0.200 | 0.3646 | 0.119 | -0.010 |
| XAUUSD | 198 | 0.3586 | [0.304, 0.416] | 0.480 | 0.3775 | 0.064 | +0.012 |
| XAGUSD | 214 | 0.3411 | [0.291, 0.394] | 0.768 | 0.3427 | 0.547 | -0.523 |
| BTCUSD | 129 | 0.2969 | [0.234, 0.362] | 0.400 | 0.3371 | 0.113 | -0.222 |
| *Volatility 25 Index* | 158 | *0.4241* | [0.359, 0.487] | *0.004* | 0.3966 | 0.057 | *+0.215* |

**Two of eight traded instruments are positive, by 0.095R and 0.012R, on 218 and 198 patterns** -
and USDJPY's 0.4009 sits on top of a day-block twin reading **0.4005**. The largest reading in
the table belongs to `Volatility 25 Index`, a generated market, at 0.4241 and p 0.004.

## Result 2: the 1:1 control on the same patterns

| | every double bottom | Eve-Eve | Eve-Adam | Adam-Eve | Adam-Adam | unclassified |
|---|---|---|---|---|---|---|
| traded, 1:1 | **0.5057** | 0.4979 | 0.4970 | 0.4976 | 0.5089 | 0.4955 |
| traded, its i.i.d. walk | 0.5099 | 0.5082 | 0.5028 | 0.4977 | 0.5018 | 0.5061 |
| traded, its day-block walk | 0.5091 | 0.5028 | 0.4994 | 0.4927 | 0.4978 | 0.5042 |
| traded, 2:1 | 0.3648 | 0.3488 | 0.3494 | 0.3386 | 0.3680 | 0.3572 |
| generated, 1:1 | 0.4949 | 0.4955 | 0.4834 | 0.4978 | 0.5160 | 0.5000 |

**0.500 at 1:1 and 0.333-0.368 at 2:1, on the same patterns, on every variant.** Moving the
barriers moves the hit rate and the payoff in step and leaves expectancy where it was, which is
`1/(1+N)` doing exactly what this desk's own null says it does. The geometry is not the lever.

## Result 3: the cost line, and what halving the stop did

| instrument | quoted round trip | the stored `spread` column | quoted / stored | cost in R at 1:1 | **cost in R at this rule's stop** |
|---|---|---|---|---|---|
| EURUSD | 0.000080 | 0.000010 | **8.26x** | 0.024 | **0.048** |
| BTCUSD | 0.000440 | 0.000057 | **7.76x** | 0.022 | **0.045** |
| GBPUSD | 0.000084 | 0.000017 | 5.09x | 0.022 | **0.043** |
| XAGUSD | 0.001443 | 0.000314 | 4.59x | 0.113 | **0.225** |
| USDJPY | 0.000078 | 0.000019 | 4.14x | 0.020 | **0.040** |
| USDCAD | 0.000075 | 0.000021 | 3.54x | 0.024 | **0.049** |
| AUDUSD | 0.000099 | 0.000030 | 3.26x | 0.019 | **0.038** |
| XAUUSD | 0.000091 | 0.000034 | 2.67x | 0.013 | **0.027** |
| *Volatility 25 Index* | 0.000135 | 0.000069 | *1.96x* | 0.012 | *0.023* |
| *Step Index* | 0.000012 | 0.000012 | *1.00x* | 0.004 | *0.008* |
| *Jump 75 Index* | 0.000116 | 0.000176 | *0.66x* | 0.003 | *0.006* |
| *Volatility 75 Index* | 0.000040 | 0.000260 | ***0.15x*** | 0.001 | *0.002* |

Those are averages over every cell. **On the cells the rule is actually read on - 15m, `L = 3`,
where the patterns are small - the cost is 0.10 to 0.20 R on the traded panel and 0.63 R on
XAGUSD**, because `cost_px / risk` scales inversely with the pattern height and the small
patterns are the numerous ones. The break-even hit rate is `(1 + cost) / 3`:

| instrument | cost in R | break-even hit | measured hit | clears it? |
|---|---|---|---|---|
| AUDUSD | 0.103 | 0.368 | 0.3753 | **yes, by 0.008** (and above both its walks) |
| USDJPY | 0.112 | 0.371 | 0.3653 | no |
| XAUUSD | 0.074 | 0.358 | 0.3528 | no |
| BTCUSD | 0.119 | 0.373 | 0.3548 | no |
| USDCAD | 0.126 | 0.375 | 0.3565 | no |
| EURUSD | 0.130 | 0.377 | 0.3389 | no |
| GBPUSD | 0.116 | 0.372 | 0.3377 | no |
| XAGUSD | 0.627 | 0.542 | 0.3357 | no |

**One of eight.** And that one is below its own i.i.d. walk.

The `spread` column is wrong in both directions again - 8.3x below the quote on EURUSD and 6.5x
**above** it on `Volatility 75 Index`. Every number here uses the quote.

## Result 4: multiplicity

157 cells carry 100 or more races (the four-way split is thin: **383 of 540 cells** are below
that bar and are reported with their `n` rather than dropped; `all` has 57 cells over it,
`Eve-Eve` 25, `Eve-Adam` 13, `Adam-Eve` 11, `Adam-Adam` 11).

Benjamini-Hochberg at q<0.10 on the z against each arm's 12 draws, since a rank p with 12 draws
floors at 1/13 = 0.077:

| arm | survivors | on generated markets | which way |
|---|---|---|---|
| **day-block** | **0 of 157** | 0 | - |
| i.i.d. | 9 of 157 | 0 | **8 of 9 have the real series *below* its walk** |

The one positive i.i.d. survivor is EURUSD at 4h and `L = 3`, every double bottom, hitting
0.4815 on **108 races**. The other eight are XAGUSD, GBPUSD, EURUSD, USDCAD and BTCUSD reading
0.25 to 0.34 against walks of 0.35 to 0.39.

**Zero survivors against the day-block arm is the headline of this section.** The i.i.d. arm
destroys the volatility clustering and the real series beats it in one cell and loses to it in
eight; the day-block arm keeps the clustering and nothing separates from it at all.

## Power, before the null is believed

A drift of known size in pattern heights, planted on the four generated markets where the real
answer is `1/3`, on a **disjoint** subset of break-outs (about 89 a cell) so it stays local and
does not compound:

| planted drift | hit | detected (p<0.05) |
|---|---|---|
| 0.00 | 0.3587 | **0.043** |
| 0.05 | 0.3675 | 0.087 |
| 0.10 | 0.3762 | 0.087 |
| 0.20 | 0.3857 | 0.217 |
| 0.40 | 0.3970 | 0.304 |

**The zero cell reads 0.043 against a claimed 0.05**, which is what makes the rest readable, and
**the plant lands where it is aimed** - the hit rate rises monotonically by 0.009, 0.018, 0.027
and 0.038 for drifts of 0.05, 0.10, 0.20 and 0.40 pattern heights.

**Where it goes blind: below about 0.40 pattern heights per cell**, which is severe, because a
cell here carries 89 races. So the per-cell null is weak and nothing in this study rests on a
single cell. The pooled readings rest on **26,217 races** for every double bottom and 1,055 to
3,195 per variant, where the binomial standard error is 0.003 and 0.008-0.015 - and the binding
resolution is not that but the **day-block arm's own draw-to-draw spread of 0.020 to 0.032**,
against which the observed gaps of -0.011 to +0.005 are a fraction of one draw.

## Bugs and measurement defects this run caught

1. **The classification was a function of the detector.** Reading width and duration inside the
   pivot's own `[i-L, i+L]` window capped the width at `2L+1`, and the variant mix on one walk
   moved from 31% Adam-Adam and 3.9% Eve-Eve at `L = 3` to 9.4% and 23% at `L = 8`. A fixed
   window fixes it; the window size was then chosen as the largest that **drops nothing**, since
   dropping selects on how fast the break-out came.
2. **The `V` and `U` templates are 0.942 correlated** at nine and seventeen bars, so the
   difference of their correlations is a residual of two nearly identical things. As a shape
   criterion it reads kappa +0.001 to +0.020 - indistinguishable from no criterion at all -
   and orthogonalising did not rescue it.
3. **A parabola and a kinked line fit a noisy nine-bar path about equally well.** The
   roundedness criterion reads kappa +0.034 to +0.116. It is computed and printed on every real
   cell so the rejection stays visible rather than becoming a silent choice.
4. **The excess over 1/3 is larger on the generated markets than on the traded ones** (0.3601
   against 0.3521), and `Jump 75 Index` reads 0.3876 at p 0.002 against the fair rate. The
   mechanism is unexplained and is bracketed by both walk arms, which read 0.355 to 0.377 on the
   same cells. It is why every statement in this document is made against a walk and not against
   0.3333.
5. **The `spread` column is wrong in both directions**, 8.3x below the quote on EURUSD and 6.5x
   above it on `Volatility 75 Index` - the defect [`impulse-vol.md`](impulse-vol.md) and
   [`chart-patterns.md`](chart-patterns.md) already carry, reconfirmed on a geometry where it
   matters twice as much.

## What this does not close

* **The 2:1 geometry was chosen, not derived.** A half-height stop is one reading of "stop
  below the pattern"; a stop below the lower bottom, or at the midpoint, is a different trade
  with a different `N` and a different cost in R. This study measures the geometry it was given.
* **`unclassified` is 40-59% of patterns** and is carried as its own cell rather than resolved.
  A tighter width rule would shrink it and thin the named variants further.
* **Three of the four variants are thin outside 15m and `L = 3`** - 11 to 25 cells each clear
  100 races - so the per-variant verdict rests mostly on one timeframe and one swing scale.
* **No fill model.** The entry is the break-out close, the barriers are checked on closes, and
  the quoted spread is charged once per round trip at the stop distance. No slippage, no queue,
  no partial fills, and no gap through the stop.
* **Nothing here was traded.**
