# Fear and greed in FX at 15 minutes: a separate rule, and it is empty

**Measured 2026-11-04.** This is the 15m arm of
[fear-greed.md](fear-greed.md), which measured risk-on / risk-off in FX at 1d
and named this run as "the largest gap in the study". It is run here with the
same code, the same instruments and the same null arms, at **sixteen surrogate
draws an arm** rather than the four the committed 1d panel used.

**It is a different rule and nothing in it is pooled with 1d.** Every parameter
in the harness is in bars - the swing reach, the volatility unit, the forward
hold, the gate's lookback - so the same constants at 15m name different
quantities: a 20-bar hold becomes 48 bars of 15 minutes, a 60-bar sentiment
window becomes 15 hours, and the whole sample is 63 trading days rather than
19.25 years. The 1d numbers appear in this document only as the thing the 15m
answer is compared against.

**Four sections were run and one was not.** `control`, `asym`, `trade` and
`power`; `levels` was excluded by the 1d pre-registration's own reasoning -
"the books publish a few hundred levels over 19 years at 1d, so at 50 days the
crash class would hold single digits" - and the power arm that *did* run
measures that reason: see section 4.

## Verdict

| question | answer |
|---|---|
| **Does the 1d swing asymmetry appear at 15m?** | **No, and not marginally.** AUDJPY's speed gap reads **+0.050 +- 0.093 (z +0.53)** at `reach` 10 where 1d reads -0.285 (z -3.78), and the sign is *reversed*: up swings faster. The pre-stated direction holds on **6 of 14** feeds for `speed` at `reach` 10 and 9 of 14 at `reach` 3 - a coin flip. **Benjamini-Hochberg over the 14 speed cells leaves 0 survivors at both swing scales** |
| Does any cell beat its hardest null arm? | **1 of 84, where chance gives 1.0.** `audchf` `size` at `reach` 3: real -0.136 +- 0.034 against the most negative of 80 draws at -0.121, excess **+0.0151**. It reads **+0.012** at `reach` 10, so the pre-registered consistency rule fails outright. Read two-sided instead - which is not the frozen rule, because the direction was pre-stated - it is **2 of 84 against 2.1 expected** |
| The two largest readings have the wrong sign. Is *that* real? | **No.** AUDUSD +0.206 +- 0.094 and EURUSD +0.278 +- 0.136 are the largest speed gaps in the panel and both are "up faster", the opposite of the carry story. Neither beats its own arms in that direction either: the 80 draws reach **+0.320** on AUDUSD and **+0.291** on EURUSD |
| Is it stable inside the window? | **No, and the placebo is indistinguishable.** Cut into six equal blocks the AUDUSD speed gap is negative in **1 of 6**, EURUSD in **0 of 6**, AUDJPY in 3 of 6 - against **4 of 6 on the EURGBP placebo**. At 1d the separation was 6 of 6 against 3 of 6; here the placebo wins |
| **Does the short-the-cross trade pay at 15m?** | **No.** Of **420 cells, 2 beat their hardest null arm where chance gives 5.2**, and the gate beats its own duty-cycle twin in **214 of 420 = 51.0%** against a 50% chance. The two that exceed are `gbpusd` `volatile_off` short at 1:1 (excess **+0.0172**) and `gold` `both` long at 1:1 (**+0.0085**, **n 65 - under 100, so noise**), and neither is a cross or a short-the-carry cell |
| Then what are the **42 of 420** cells that survive Benjamini-Hochberg? | **One macro fact counted 42 times.** They are 21 directional bets each appearing as a mirrored pair (a 2:1 long and a 1:2 short of the same race), 17 of them on the **ungated** arm, concentrated on `usdjpy` (10) and `usdchf` (8). The window's own drift is +49.5 volatility units on USDCHF and -36.6 on EURGBP over 63 days. **Every one of the 42 sits below its hardest null arm** - the surrogates with the same step distribution make more - so what survives BH is the drift, not the gate |
| Is the gated arm better than the ungated one? | **Not reliably.** The best-looking cell in the panel is `eurchf` `volatile_off` short at 2:1, **+0.3584 +- 0.0927 on 165 trades** against **+0.2080 +- 0.0669** ungated - but its hardest null arm reads **+0.4995**, and over all 420 cells the gate beats its random twin 51.0% of the time |
| **Does the 2008 control transfer?** | **It cannot be run, which is not the same as a null.** The 15m intersection starts **2026-06-03**, so the 2008-08-01..2009-03-31 window holds **0 bars**. The harness raised `ValueError` on it and took the whole `control` section down; fixed to write a row marked `skipped`, because a control that could not run and a control that came back empty are different facts |
| Is the reading itself intact at 15m? | **Yes, on all three checks that can run.** The triangle is exact (**8.9e-16** in log price) and collapses to r2 **0.0007-0.0069** at a one-bar leg shift; the measured gate boundary is **+0.111 at the 80th percentile and +0.156 at the 90th** against +0.10 and +0.15 at 1d; and the planted-crash arm finds a 10% crash in **12 of 16** draws while reading **0 of 16 at depth zero** |
| Is the index's power better or worse at 15m? | **Better, and for an uninteresting reason.** The direction half finds a planted crash on **16 of 16** draws from depth 0.05, where at 1d it took 0.10 to reach 4 of 4: a 5% move spread over 68 bars is enormous against 15-minute volatility. The composite is **non-monotone** (12/16 at 0.10, 8/16 at 0.45) because the plant is a smooth drift and does not widen ranges - the same limitation the 1d study recorded |
| **Could the synthetic-generator placebo the 1d run lacked be added here?** | **No, and the 1d note is wrong about why.** It says "the synthetics present are 15m-only or absent"; in fact **this store holds no generated synthetic at any interval**. Its 14 feeds are FX, gold, two equity indices and three crypto, and the `DERIV` venue's 15m feeds are that broker's *real* markets (`audusd`, `btc`, `eurusd`, `gold`, ...), not its volatility indices. `eurgbp` is still the placebo |
| **Is any of this priced?** | **Partly, for the first time, and the price is fatal.** On the three feeds with recorded OANDA quotes a round trip costs **0.339R on EURUSD, 0.323R on GBPUSD and 0.077R on gold** at the study's 1.0-unit stop, against **0.018R, 0.018R and 0.031R for the same spreads at 1d**. The largest gross gated mean in the whole panel is +0.358R. **The primary tables below are gross and the cost is not subtracted from them** |
| Does the conditioning question move? | **No, and the circularity is reproduced.** The down-share difference between the top and bottom tercile of `directional_off` matches `RISK_OFF_SIGN` on **6 of 6** basket legs (AUDUSD -0.267 at sign -1, USDCAD +0.307 at sign +1) and is near zero on the out-of-basket feeds (EURUSD -0.149, GBPUSD -0.174, EURGBP +0.135). The index reads each instrument's own recent direction back to itself |
| Was the level study run? | **No, by the 1d pre-registration's own rule, and the power arm says that was right.** On AUDUSD at 15m the crash-labelled class holds **5.6 to 10.4 levels** on `Pivots` and 37 to 47 on `Pips` across the plant's strengths |

**Nothing in the tables is priced.** The cost calculation is in
[Costs](#costs-and-the-one-thing-this-interval-can-price) and is deliberately
kept out of the result columns.

## What was run

| section | coverage | arms |
|---|---|---|
| **1. the control** | coverage, the triangle at 4 calendar shifts on all 6 crosses, the gate boundary at 4 quantiles on 3 readings, the planted crash at 6 depths | **16 draws a depth**; the 2008 window itself is **not available** |
| **2. the synthetic range** | all 8 legs and all 6 crosses, at 15m and re-measured at 1d | arithmetic, no arms |
| **3. the asymmetry** | 14 series x 2 swing scales x both pivot kinds, **3,680 rows** | **5 null arms x 16 draws + 2 diagnostics** (80 surrogate draws a cell) |
| 4. the level labels | **not run** - see the verdict and section 4 | the level *plant* ran on `audusd` x `pips`, `pivots` as part of `power` |
| **5. the trade** | 14 series x 5 gates x 3 races x 2 sides, **35,280 rows** | **5 null arms x 16 draws + 2 diagnostics + the duty-cycle twin** |
| **6. the conditioning** | 14 series x 2 swing scales, 28 rows | real arm only by construction, as at 1d |
| the power sweeps | 3 asymmetry plants on 4 feeds x 2 scales, the trade drift plant on 4 feeds, the level plant on `audusd` x 2 books | 144 rows |

**Runtime: 174 seconds at `--jobs 16` on a 64-core box** - control 38s, asym 5s
over 14 jobs, trade 4s over 14 jobs, power 127s over 4 jobs. The 1d panel's
"25 to 35 minutes" estimate is wrong by two orders of magnitude at 15m, which
is a shorter series and no `levels` section.

Every table is read from `.data/out/fear_greed_15m/*.jsonl` and
`fear_greed_report.py` prints it from those files.

## The rules, as frozen before the run

Identical to [fear-greed.md](fear-greed.md)'s, with the interval changed and
nothing else. What that means in 15-minute bars:

* **Instruments**: the same 8 OANDA legs (`audusd`, `nzdusd`, `usdcad`,
  `usdjpy`, `usdchf`, `eurusd`, `gbpusd`, `gold`) and the same 6 synthetic
  crosses, `eurgbp` the placebo, `eurchf` the haven-only control.
* **Venue: OANDA**, for the same reason - it is the only venue whose gold and
  FX bars share a stamp.
* **The reading is `FearGreed`** at module defaults, `span` 60 and `warmup` 20,
  which at 15m is a **15-hour** window. Reported as `volatile` and
  `directional` separately, never as the composite alone.
* **The index is a basket of the six real legs** oriented by `RISK_OFF_SIGN`.
* **Horizon 48 bars (12 hours) and the volatility unit a 48-bar EWMA of the bar
  range**, from `SETTINGS["15m"]`, taken from `level_shield.SETTINGS`
  unchanged. On a synthetic cross the unit is the close-step one scaled by
  `RANGE_OVER_STEP` 2.39, because a cross's range is a bound.
* **Swing scales `reach` 3 and `reach` 10**, two named rules, not a sweep.
* **Gates are causal**: a trailing quantile over the prior 500 bars at the 80th
  percentile. `all` (ungated), `volatile_off`, `directional_off`, `risk_off`
  and `both` (the interaction).
* **Races**: 2:1, 1:1 and 1:2 on closes, both sides, one position at a time.
* **Null arms**: `garch-bars`, `walk-geometry`, `bar-shuffle`, `log-walk`,
  `log-shuffle`, **16 draws each**, scored against the extreme of all 80 draws;
  `sign-flip` and `drift-free` are diagnostics and are not in the set.
* **Direction pre-stated and one-sided** for the asymmetry: `bars` positive,
  `size` negative, `speed` negative.
* **Nothing is priced** in the result columns.

### Deviations, and they are all recorded rather than fixed quietly

1. **`levels` was not run.** The 1d pre-registration excluded it at 50 days and
   section 4 measures the crash class to show the exclusion was right. The
   level *plant* ran anyway, because `power` runs it for any feed whose range
   is trusted.
2. **The 2008 control cannot run at 15m** and now writes a `skipped` row. This
   was a crash, not a design choice - see [Defects](#defects-found-on-the-way).
3. **A six-block stability diagnostic was added after the panel ran.** `F.ERAS`
   are calendar years and the whole 15m window sits inside one of them, so the
   panel's era table is a single row and the 1d study's strongest evidence - the
   sign holding in 6 of 6 eras against 3 of 6 on the placebo - has no 15m
   counterpart. Six equal blocks of bars is the closest analogue. **It is a
   diagnostic and not a test: it has no null arm**, and it was computed after
   the result was known.
4. **Two aggregates were added to the report**, because the verdict is a count
   over cells and the report printed only the cells. They reproduce the 1d
   panel's own published numbers exactly (6 of 420 above the hardest arm, 206
   of 420 against the twin, 8 BH survivors), which is the check that the
   counting rule is the study's and not a new one.

## The data, and the sample sizes

**4,760 bars common to all eight legs, 2026-06-03 19:00 to 2026-08-14 20:45
UTC - 0.197 years, 63 trading days.** Of the 4,759 steps, 4,707 are 15 minutes,
42 are 75 minutes (the daily break) and **10 are weekends** of 49.25 to 53.25
hours. The day-block bootstrap therefore resamples **63 blocks**, where the 1d
study had about 4,980.

| what | at 15m | at 1d |
|---|---|---|
| bars | 4,760 | 4,980 |
| span | 63 trading days | 19.25 years |
| swings, `reach` 10 | **207 to 258**, median **12 bars** | about 250, median ~20 |
| swings, `reach` 3 | **736 to 839**, median **4 bars** | about 800, median 4 |
| trades a cell, ungated | **347 to 845** | 200 to 500 |
| trades a cell, gated | **119 to 285** | 50 to 200 |
| trades a cell, `both` | **49 to 65 - under 100, so noise** | 65 |

**Every mean below carries its standard error** and the `both` gate's cells are
flagged as thin wherever they appear: at 49 to 65 trades with a per-trade sd
near 1.3R, a 95% interval is about +-0.35R and no row of that gate can decide
anything.

## 1. The control: two of three checks run, and both pass

### The triangle is exact at 15m too

| leg shift | r2 range over the 6 crosses | max log-price deviation |
|---|---|---|
| **0** | **1.000000** | **8.9e-16** |
| 1 | 0.0005 to 0.0069 | 1.5e-03 to 1.4e-02 |
| 2 | 0.0003 to 0.0021 | 2.3e-03 to 1.6e-02 |
| 5 | 0.0001 to 0.0034 | 3.2e-03 to 2.2e-02 |

The deviation at a one-bar shift is an order of magnitude smaller than 1d's
(1.4e-02 against 1.2e-01) for the obvious reason - a 15-minute bar moves less -
but r2 collapses just as completely, so the check is as falsifiable here.

### The measured boundary agrees with 1d to a hundredth

| reading | q60 | q70 | **q80** | q90 |
|---|---|---|---|---|
| `risk_off` | +0.0368 | +0.0721 | **+0.1114** | +0.1560 |
| `volatile_off` | +0.1256 | +0.1775 | **+0.2306** | +0.3011 |
| `directional_off` | +0.0030 | +0.0303 | **+0.0698** | +0.1245 |

At 1d the same trailing quantiles land on +0.10 and +0.15. **`Mood`'s
conventional +-0.5 never fires at 15m either**: the basket's whole-sample
maximum is **+0.3253** on `risk_off` and +0.5249 on `volatile_off`.

### Power for the control, which reads better here than at 1d

Every basket leg replaced by a `walk-geometry` surrogate, a crash of known
depth spread over 68 bars at a random start with each leg's own risk-off sign,
**16 draws a depth**. Chance is 0.0143.

| planted depth | index argmax in window | `volatile_off` | `directional_off` |
|---|---|---|---|
| **0.00** | **0 / 16** | 0 / 16 | **0 / 16** |
| 0.05 | 3 / 16 | 6 / 16 | **16 / 16** |
| **0.10** | **12 / 16** | 7 / 16 | 16 / 16 |
| 0.20 | 10 / 16 | 8 / 16 | 16 / 16 |
| 0.30 | 8 / 16 | 8 / 16 | 16 / 16 |
| 0.45 | 8 / 16 | 8 / 16 | 16 / 16 |

**The arm that must come back empty does: 0 of 16 at depth zero on all three
readings.** The direction half is saturated from the smallest depth tested,
which is what 68 bars of 15-minute data does to a 5% move. The composite is
**non-monotone** - 12 of 16 at 0.10 falling to 8 of 16 at 0.45 - and the cause
is the one the 1d study named: the plant is a smooth drift, `expansion` is a
range statistic, so at large depths the volatility half's own argmax sits
outside the window and drags the composite. **The plant cannot speak for the
volatility half** at either interval.

### What could not be run

The 2008 window holds **0 of 4,760 bars**. No rank among non-overlapping
windows, no episode table, no cross drawdowns, no breadth at the peak. The
positive control of the whole study is a 1d-only object, and the correct
statement about the 15m rule is that **it has no positive control** beyond the
planted crash above.

## 2. The synthetic cross's range at 15m, and a row the 1d table left out

Median bar range over median absolute close-to-close move. The 1d column is
re-measured here on the same store.

| instrument | kind | 15m | 1d |
|---|---|---|---|
| nzdusd | real | 2.188 | 2.300 |
| usdchf | real | 2.235 | 2.356 |
| usdcad | real | 2.263 | 2.336 |
| usdjpy | real | 2.286 | 2.439 |
| audusd | real | 2.312 | 2.344 |
| eurusd | real | 2.333 | 2.319 |
| gold | real | 2.376 | 2.412 |
| gbpusd | real | 2.500 | 2.322 |
| **real band** | | **2.188-2.500, median 2.299** | 2.300-2.439, median 2.340 |
| eurchf | haven | 2.400 | 2.447 |
| audchf | carry+haven | 2.522 | 2.785 |
| nzdjpy | carry+haven | **3.946** | 4.096 |
| cadjpy | carry+haven | **4.059** | 3.589 |
| audjpy | carry+haven | **4.100** | 4.027 |
| **eurgbp** | **placebo** | **8.363** | **5.777** |

Two things fall out, one of them a correction to the 1d document.

**The JPY crosses' bound inflation is the same at 15m** - 1.7x the real band's
median - so the split that study made (closes on a cross, ranges on a leg only)
carries over unchanged, and `RANGE_OVER_STEP` 2.39 still sits 4% above the
real band's median of 2.299.

**EURGBP is the worst cross in the store and the 1d table does not contain it.**
At 1d it reads **5.777**, larger than audjpy's 4.027; at 15m **8.363**. The
mechanism is the quotient of two highly correlated legs: the common dollar
factor cancels out of the close step, leaving a small denominator, while the
synthesised high over low keeps both legs' full ranges. **No result at either
interval changes** - every cross reading in both studies is close-only, which
is exactly why the split exists - but the 1d section's table claims to cover
"all 6 crosses" and prints five, and the one it drops is the placebo.

## 3. The asymmetry: absent at 15m, with the sign reversed on the largest cells

`reach` 10 close pivots, log-mean gaps of up swings against down swings, z on a
day-block bootstrap over whole days (63 blocks). The hardest arm is the extreme
of **80 surrogate draws** in the pre-stated direction, and `excess` is signed so
that positive means the real value beat it.

| instrument | kind | n | speed | se | z | bars | se | z | hardest speed arm | excess |
|---|---|---|---|---|---|---|---|---|---|---|
| audjpy | carry+haven | 249 | **+0.050** | 0.093 | +0.53 | -0.010 | 0.085 | -0.12 | -0.366 | -0.415 |
| nzdjpy | carry+haven | 248 | -0.096 | 0.097 | -1.00 | +0.119 | 0.099 | +1.19 | -0.250 | -0.154 |
| cadjpy | carry+haven | 248 | -0.128 | 0.103 | -1.24 | +0.205 | 0.084 | +2.45 | -0.376 | -0.249 |
| audchf | carry+haven | 249 | +0.006 | 0.102 | +0.06 | +0.006 | 0.096 | +0.07 | -0.145 | -0.151 |
| eurchf | haven | 233 | +0.100 | 0.117 | +0.86 | -0.112 | 0.112 | -1.00 | -0.166 | -0.266 |
| **eurgbp** | **placebo** | 258 | +0.054 | 0.085 | +0.63 | -0.085 | 0.075 | -1.13 | -0.231 | -0.285 |
| **audusd** | leg (carry) | 225 | **+0.206** | 0.094 | **+2.19** | **-0.211** | 0.092 | -2.28 | -0.126 | -0.332 |
| nzdusd | leg (carry) | 207 | **+0.194** | 0.092 | +2.12 | -0.180 | 0.082 | -2.20 | -0.182 | -0.376 |
| usdjpy | leg (haven) | 233 | -0.095 | 0.106 | -0.90 | +0.161 | 0.084 | +1.92 | -0.476 | -0.381 |
| usdchf | leg (haven) | 216 | -0.050 | 0.136 | -0.36 | +0.160 | 0.113 | +1.42 | -0.268 | -0.219 |
| usdcad | leg (carry) | 224 | -0.157 | 0.099 | -1.58 | +0.074 | 0.121 | +0.61 | -0.275 | -0.118 |
| gold | leg (haven) | 248 | +0.077 | 0.095 | +0.81 | -0.067 | 0.080 | -0.84 | -0.146 | -0.224 |
| **eurusd** | leg | 223 | **+0.278** | 0.136 | **+2.05** | **-0.316** | 0.112 | -2.82 | -0.131 | -0.409 |
| gbpusd | leg | 233 | -0.077 | 0.086 | -0.90 | +0.131 | 0.085 | +1.54 | -0.165 | -0.088 |

**Benjamini-Hochberg over the 14 speed cells: 0 survive.** At `reach` 3 the
same table reads -0.087 to +0.107 on `speed` with |z| at most 2.17 and again
**0 BH survivors**.

The three comparisons that decide the section:

**Against the 1d result.** AUDJPY -0.285 becomes **+0.050**, NZDJPY -0.252
becomes -0.096, AUDUSD -0.297 becomes **+0.206**, USDCHF -0.261 becomes -0.050.
Nothing of the 1d pattern is present, and the 1d study's own conclusion - that
the asymmetry is a property of the **return distribution** rather than the path
- is why: a distributional property of daily returns does not have to appear in
15-minute returns, and here it does not.

**Against the pre-stated direction.** `speed` negative on 6 of 14 at `reach` 10
and 9 of 14 at `reach` 3; `bars` positive on 7 of 14 at both. That is a coin
flip, and the two largest magnitudes in the panel point the *wrong way*.

**Against the arms.** One cell of 84 beats its hardest arm in the pre-stated
direction - `audchf` `size` at `reach` 3, excess **+0.0151** - where 84 cells at
80 draws gives **1.0 by chance**, and it reverses sign at the other swing scale,
so the pre-registered consistency rule fails. Read two-sidedly it is 2 of 84
against 2.1 expected, the second being `eurusd` `bars` at `reach` 10 (-0.316
against draws spanning [-0.251, +0.139]).

### The reversed sign is not a finding either

AUDUSD's +0.206 and EURUSD's +0.278 are the panel's largest readings and both
say *up swings are faster*. Testing them in that direction is a post-hoc flip
and is reported as one, but it does not survive even so: every arm reaches
further than the real value.

| cell | real | garch | bar-shuffle | log-shuffle | log-walk | walk-geometry | max of 80 draws |
|---|---|---|---|---|---|---|---|
| audusd speed | **+0.206** | +0.152 | +0.190 | +0.145 | **+0.320** | +0.192 | **+0.320** |
| eurusd speed | **+0.278** | +0.119 | +0.208 | **+0.291** | +0.277 | +0.211 | **+0.291** |

The diagnostics behave: `sign-flip` mirrors AUDUSD to -0.205 against +0.206 and
EURUSD to -0.277 against +0.278, so the statistic is measuring what it claims
to; `drift-free` leaves AUDUSD at +0.156 and EURUSD at **+0.293**, so the
reversal is not the 63-day trend.

### Six blocks, and the placebo wins

Added after the run, no null arm, a diagnostic only. The speed gap at `reach`
10 within each sixth of the window, with blocks under 4 swings dropped:

| instrument | pooled | per-block speed gap | negative blocks | first half | second half |
|---|---|---|---|---|---|
| audusd | +0.206 | +0.55 +0.07 +0.31 +0.08 +0.19 -0.02 | **1 of 6** | +0.315 | +0.095 |
| eurusd | +0.278 | +0.24 +0.04 +0.25 +0.01 +0.40 +0.76 | **0 of 6** | +0.171 | +0.384 |
| audjpy | +0.050 | +0.53 -0.20 -0.04 +0.15 -0.11 +0.04 | 3 of 6 | +0.095 | +0.012 |
| nzdjpy | -0.096 | +0.06 +0.01 -0.27 +0.06 -0.29 -0.13 | 4 of 6 | -0.066 | -0.130 |
| cadjpy | -0.128 | -0.17 -0.18 -0.09 +0.04 -0.37 +0.11 | 4 of 6 | -0.146 | -0.111 |
| usdjpy | -0.095 | +0.16 +0.15 -0.09 -0.02 -0.60 -0.19 | 4 of 6 | +0.083 | -0.292 |
| **eurgbp (placebo)** | +0.054 | -0.12 +0.28 -0.11 -0.06 +0.29 -0.00 | **4 of 6** | +0.025 | +0.083 |

At 1d this table was the study's strongest evidence: 6 of 6 on AUDUSD and
USDCHF against 3 of 6 on the placebo. **Here the placebo matches or beats every
traded instrument**, which is what a null era profile looks like.

### The three statistics are two, and the multiplicity is smaller than it looks

`speed = size / bars` per swing, so in log gaps **the speed gap is exactly the
size gap minus the duration gap**. Measured over the 28 real close-pivot rows
of this panel the identity holds to **1.1e-15**. So the 14 x 2 x 3 grid is 56
independent cells, not 84, and `speed` and `bars` moving in opposite directions
on the same feed is arithmetic rather than corroboration.

It leaks in exactly one place and the leak is worth knowing: a swing whose
*close* move is exactly zero has `size` 0 and `speed` 0, which `_log_gap` drops
while keeping its `bars`. That never happens on close pivots here (0 of 3,294 at
`reach` 10) but does on the high/low detector and on surrogate paths, where up
to 3.3e-02 of the identity is lost - larger than several of the effects being
measured.

### Power: the same three plants, and the same two blind spots

Eight plants a strength, each against the shuffle arm matched to how the plant
builds its path.

**The up-bar share is near-marginal arithmetic**, as at 1d. AUDJPY, `reach` 10,
duration gap: the real statistic runs +0.015, +0.058, +0.261, **+0.540** as the
up-share goes 0.50 to 0.60, and the matched shuffle runs +0.020, +0.068, +0.277,
**+0.526** behind it. The excess never clears |z| 1.6 and the zero cell reads
+0.013 (z +0.43), correctly empty.

**Skewness moves the statistic and the shuffle keeps it.** AUDJPY, `reach` 10,
speed gap: -0.009 at strength 0, -0.116 at 0.20, **-0.171** at 0.35, against a
matched shuffle at -0.056, -0.111, **-0.170**. Excess +0.047 to -0.001. So a
planted skew of a size that moves the statistic by 0.17 is **invisible** to the
exceedance test, which is the quantitative version of the 1d conclusion that
the asymmetry is distributional.

**There is still no calibrated test for pure order.** The sign-clustering plant
reorders the exact multiset of returns by a two-state Markov chain, so
persistence 0.50 is its zero control. On `speed` that control now passes
(AUDJPY -0.029 at z -1.17, EURGBP -0.033 at z -1.46) where at 1d it failed at
-0.180 and z -4.76 - but on `bars` it fails in both directions on different
feeds (**z -2.54 on AUDJPY, +4.11 on EURGBP, with nothing planted**), and no
strength up to 0.80 produces a `speed` excess clear of noise. **So the 15m null
is a null against what the test can see, and the test is blind to order.**

## 4. The level labels: not run, and the number that says why

The 1d pre-registration excluded this section at 50 days. The `power` section
runs the level plant for any feed whose range is trusted, so it ran on AUDUSD
and reports the sample the excluded section would have had:

| book | crash-labelled levels, across the plant's strengths | planted gap | sd |
|---|---|---|---|
| `pivots` (the no-parameter control) | **5.6 to 10.4** | -0.274 to -0.023 | 0.17 to 0.44 |
| `pips` | 37.1 to 46.6 | -0.053 to +0.125 | 0.09 to 0.21 |

So the book with power at 1d has **single digits** at 15m, exactly as predicted,
and the plant is non-monotone in strength on both books with an sd larger than
any gap - which is the same rejection the 1d study recorded: **planting a
label-conditional hold changes the path, so the recomputed shape labels no
longer mark the bars the effect was placed at, and the act of planting destroys
the association being planted.** The arm is rejected at 15m for the same reason
and no level result is reported at this interval.

## 5. The trade: null on the arms, and 42 cells of one macro fact

### The three counts that decide it

| count | 15m | 1d |
|---|---|---|
| cells | **420** | 420 |
| surrogate draws a cell | **80** | 20 |
| **real above its hardest null arm** | **2 / 420, chance about 5.2** | 6 / 420, chance about 20 |
| **real above its own duty-cycle twin** | **214 / 420 = 51.0%** | 206 / 420 = 49.0% |
| Benjamini-Hochberg on the day-block t | **42 / 420** | 8 / 420 |

The two cells above their hardest arm:

| cell | n | duty | mean R | se | 95% CI | hardest arm | excess | twin |
|---|---|---|---|---|---|---|---|---|
| `gbpusd` `volatile_off` -1 1:1 | 272 | 0.30 | +0.1760 | 0.0536 | [+0.074,+0.298] | +0.1588 | **+0.0172** | +0.0720 |
| `gold` `both` +1 1:1 | **65** | 0.08 | +0.2000 | 0.1133 | [-0.053,+0.390] | +0.1915 | **+0.0085** | +0.0986 |

Neither is a cross, neither is the short-the-carry trade the framing names,
both are 1:1 races, the gold cell has **65 trades and a CI that contains zero**,
and two cells is fewer than the 5.2 chance gives.

### The trade as framed, short the cross at 2:1

Gross, in R, with the day-block standard error. `hardest` is the best of 80
surrogate draws and `twin` is the duty-cycle random control.

| gate | cross | n | duty | mean R | se | hardest | excess | twin |
|---|---|---|---|---|---|---|---|---|
| `all` | audjpy | 361 | 0.89 | -0.0016 | 0.0671 | +0.1901 | -0.1916 | +0.0704 |
| `all` | nzdjpy | 407 | 0.89 | +0.0428 | 0.0727 | +0.2128 | -0.1700 | -0.0043 |
| `all` | cadjpy | 403 | 0.89 | +0.0009 | 0.0775 | +0.2564 | -0.2555 | +0.0306 |
| `all` | audchf | 364 | 0.89 | +0.2079 | 0.0532 | +0.3383 | -0.1304 | +0.2445 |
| `all` | eurchf | 368 | 0.89 | +0.2080 | 0.0669 | +0.4124 | -0.2045 | +0.0982 |
| `all` | **eurgbp** | 383 | 0.89 | +0.1450 | 0.0697 | +0.2901 | -0.1451 | +0.0674 |
| `risk_off` | audjpy | 136 | 0.35 | -0.0242 | 0.1192 | +0.2576 | -0.2818 | -0.0875 |
| `risk_off` | nzdjpy | 140 | 0.33 | +0.0141 | 0.1169 | +0.2935 | -0.2794 | -0.0210 |
| `risk_off` | cadjpy | 158 | 0.35 | -0.0704 | 0.1368 | +0.3492 | -0.4196 | +0.0456 |
| `risk_off` | audchf | 148 | 0.37 | +0.2113 | 0.0895 | +0.4683 | -0.2570 | +0.2176 |
| `risk_off` | eurchf | 167 | 0.38 | +0.2403 | 0.1077 | +0.4099 | -0.1696 | +0.0867 |
| `risk_off` | **eurgbp** | 179 | 0.41 | +0.0582 | 0.0764 | +0.4040 | -0.3458 | +0.1790 |
| `volatile_off` | audjpy | 156 | 0.39 | -0.0348 | 0.1039 | +0.2737 | -0.3085 | +0.0517 |
| `volatile_off` | nzdjpy | 153 | 0.37 | -0.0052 | 0.0941 | +0.3466 | -0.3517 | -0.1159 |
| `volatile_off` | cadjpy | 166 | 0.37 | -0.0365 | 0.1252 | +0.2652 | -0.3016 | +0.0783 |
| `volatile_off` | audchf | 159 | 0.42 | +0.2917 | 0.0967 | +0.4555 | -0.1637 | +0.1105 |
| `volatile_off` | eurchf | 165 | 0.39 | **+0.3584** | 0.0927 | +0.4995 | -0.1411 | +0.1811 |
| `volatile_off` | **eurgbp** | 162 | 0.43 | -0.0009 | 0.1009 | +0.4522 | -0.4531 | +0.0386 |
| `directional_off` | audjpy | 123 | 0.29 | -0.0704 | 0.1078 | +0.2791 | -0.3496 | -0.0153 |
| `directional_off` | nzdjpy | 125 | 0.29 | +0.2053 | 0.1349 | +0.3607 | -0.1554 | -0.0234 |
| `directional_off` | cadjpy | 125 | 0.29 | +0.0254 | 0.1708 | +0.3909 | -0.3655 | -0.1588 |
| `directional_off` | audchf | 119 | 0.29 | +0.0588 | 0.1266 | +0.4519 | -0.3931 | +0.2138 |
| `directional_off` | eurchf | 129 | 0.30 | +0.1018 | 0.1085 | +0.5115 | -0.4097 | +0.2527 |
| `directional_off` | **eurgbp** | 152 | 0.32 | -0.0441 | 0.0934 | +0.3975 | -0.4416 | +0.2457 |
| `both` | audjpy | **49** | 0.11 | -0.2861 | 0.2374 | +0.6174 | -0.9036 | -0.0493 |
| `both` | nzdjpy | **49** | 0.12 | -0.0558 | 0.2043 | +0.5251 | -0.5809 | -0.0408 |
| `both` | cadjpy | **53** | 0.12 | +0.0976 | 0.2224 | +0.5167 | -0.4191 | -0.0058 |
| `both` | audchf | **54** | 0.12 | +0.0306 | 0.2111 | +0.5699 | -0.5393 | -0.0741 |
| `both` | eurchf | **57** | 0.11 | +0.2146 | 0.1803 | +0.8924 | -0.6777 | +0.1624 |
| `both` | **eurgbp** | **60** | 0.14 | +0.2359 | 0.1979 | +0.7727 | -0.5368 | -0.1733 |

All thirty cells of the gate x cross grid at 2:1 short, with no row
omitted; **n in bold is under 100 and decides nothing**.

**Every one of the thirty excesses is negative** - the surrogates built from the
same step distribution reach further than the real series in all of them. The
three JPY crosses, which are the trade the framing is about, span **-0.0704 to
+0.2053R** across the four gates, every one inside about 1.5 of its own
standard errors; the best of them, `nzdjpy` on `directional_off`
(+0.2053 +- 0.1349), has an excess of **-0.1554** and is beaten by nothing but
its own arms. **The `both` rows are thin at 49 to 60 trades and decide
nothing.**

The long arm is where the window's return sits: AUDJPY long reads **+0.2326 +-
0.0744** ungated against -0.0016 +- 0.0671 short, and AUDCHF the other way
round (+0.0201 +- 0.0584 long against +0.2079 +- 0.0532 short). That is the
direction each cross happened to travel over 63 days, and section 5's next
sub-section is the evidence for that reading.

### The 42 BH survivors are the dollar, counted 42 times

| by gate | by feed | by side |
|---|---|---|
| `all` 17, `volatile_off` 22, `risk_off` 3 | usdjpy 10, usdchf 8, audchf 6, gbpusd 5, eurchf 4, eurusd 4, usdcad 2, audjpy 2, cadjpy 1 | short 21, long 21 |

Three facts make them one fact:

* **They are mirrored pairs.** `usdjpy all +1 2:1` reads +0.3306 +- 0.0589 and
  `usdjpy all -1 1:2` reads -0.1653 +- 0.0284; the 1:1 races are exactly
  antisymmetric (`usdjpy all +1 1:1` +0.1132, `-1 1:1` -0.1132). Twenty-one
  bets appear as forty-two cells.
* **The window drifted, and by a lot in stop units.** Over the 63 days USDCHF
  moved **+49.5** volatility units, EURGBP -36.6, AUDCHF -26.5, EURCHF -25.9,
  GBPUSD +18.8, AUDJPY -16.1, USDJPY -12.0.
* **Not one of the 42 beats its hardest null arm.** `usdjpy all +1 2:1` is
  +0.3306 against +0.6003; `usdchf volatile_off +1 2:1` is +0.4336 +- 0.0854
  against +0.5436. The drift is in the step distribution, which every arm
  keeps, so the day-block t is testing "did this instrument trend" and the
  arms are testing "did the gate find anything", and only the second is the
  study's question.

At 1d this count was 8 and the 1d write-up describes them as "all the ungated
arm on gold and usdjpy". Re-read from the committed panel with the new
aggregate, **6 of the 8 are the ungated arm and 2 are `gold` under the
`risk_off` gate** - a small error in that document, found by making its own
headline numbers reproducible.

### Power for the trade: a drift of a tenth of a stop would have been seen

A conditional drift planted into the gated bars, 8 draws a strength, mean R over
the 48-bar hold:

| drift, units a horizon | audjpy mean R | sd | audusd mean R | sd |
|---|---|---|---|---|
| **0.00** | **+0.0528** | 0.1381 | **+0.1742** | 0.1153 |
| 0.10 | **+0.2704** | 0.2233 | **+0.3661** | 0.1280 |
| 0.25 | +0.6461 | 0.1304 | +0.6193 | 0.0741 |
| 0.50 | +1.1054 | 0.1554 | +0.9633 | 0.0658 |
| 1.00 | +1.5124 | 0.1038 | +1.3175 | 0.0715 |

**The zero cells are feed-specific and are not zero** - +0.0528 on audjpy and
+0.1742 on audusd - which is the 1d study's warning repeated: no row may be
read against zero, only against its own zero cell and its own arms. A drift of
0.10 units over the hold lifts audjpy by **+0.218 against a pooled standard
error of 0.093 over the two 8-draw means (2.3 sigma)** and audusd by **+0.192
against 0.061 (3.1 sigma)**, so **a conditional drift of a tenth of a stop over
12 hours would have been visible**, and the real gated arms sit at or below
their own zero cells.

## 6. Direction inside a volatility state: the circularity, reproduced

Real arm only, as at 1d - the conditioning statistic has no shuffle of its own
because the index would have to be recomputed on the surrogate. Down-share in
the top tercile of `directional_off` minus the bottom, `reach` 10:

| feed | in basket | `RISK_OFF_SIGN` | high minus low |
|---|---|---|---|
| audusd | yes | -1 | **-0.267** |
| nzdusd | yes | -1 | **-0.377** |
| usdjpy | yes | -1 | -0.192 |
| usdchf | yes | -1 | +0.042 |
| usdcad | yes | **+1** | **+0.307** |
| gold | yes | **+1** | **+0.145** |
| eurusd | no | - | -0.149 |
| gbpusd | no | - | -0.174 |
| eurgbp | no (placebo) | - | +0.135 |

**The sign matches `RISK_OFF_SIGN` on 6 of 6 basket legs**, including both
positive-signed ones, and USDCHF is the only near-zero. The out-of-basket feeds
are smaller and unsigned. This is the 1d mechanism exactly: the index is each
instrument's own recent direction with the quote convention's sign on it, so
"direction conditioned on the index" reads a tautology back. The interaction
cells (`directional_off` terciles inside `volatile_off` terciles) are **85 to 93
swings each - thin** - and run -0.276 to +0.102 on the speed gap with no pattern
across feeds.

## Costs, and the one thing this interval can price

**The tables above are gross.** The 1d study could price nothing. This one can
price three feeds, because the store holds recorded OANDA quotes for them, and
the answer is decisive enough to report in the verdict.

| feed | quotes | median bid-ask | median 1.0-unit stop | **round trip, 15m** | **round trip, 1d** |
|---|---|---|---|---|---|
| eurusd | 604 | 0.000160 | 0.000472 (4.1 bp) | **0.339 R** | 0.018 R |
| gbpusd | 842 | 0.000200 | 0.000620 (4.6 bp) | **0.323 R** | 0.018 R |
| gold | 2,806 | 0.640 | 8.342 (20.3 bp) | **0.077 R** | 0.031 R |

The spread is the same in price at both intervals; **the stop is 19 times
smaller at 15m on EURUSD** (18x on GBPUSD, and only 2.5x on gold, whose daily
range is proportionally far smaller), and cost in R is `cost_px / risk`, set by
the stop and not by the target. One round trip is **0.38 of a 15-minute bar
range** on EURUSD against 0.019 of a daily one. `exotic-spreads-are-a-whole-bar-range` is the standing version of this and
it applies to a major FX pair as soon as the interval is short enough.

What that means for the panel: the largest gross gated mean in 420 cells is
+0.358R, the carry crosses read -0.07 to +0.21R gated, and a cross's spread is
**wider than either leg's and is not recorded anywhere in this store**, so it
cannot even be charged. Charging the EURUSD figure to the FX cells would move
every cross row to roughly -0.4 to 0.0R. **No cost is subtracted from any
number above**, because inventing a cross's spread is the one result that looks
like a measurement and is not; the three measured round trips are reported here
and applied nowhere.

## Defects found on the way

**1. The `control` section crashed at 15m and took the run with it.**
`crash_control` masks the 2008 window and `window_rank` raises
`ValueError: a 0-bar window has no mean worth ranking` on an empty mask.
Because `control` runs first and the exception propagates out of `main`,
`--intervals 15m` wrote **no output at all** - not a partial panel, nothing.
Fixed by `FEWEST_CRASH_BARS` and a row carrying `skipped`, and the report prints
`NOT RUN` with the reason rather than omitting the section.

**2. The report pooled intervals in three of its five tables.** `asym` keys on
`(interval, reach, feed)`; `trade`, `levels` and `power` did not key on interval
at all, so `--intervals 1d,15m` would have interleaved two rules in one table,
feed by feed, with nothing in the row to say which was which. The trade table
now sorts on interval first and the new aggregate is printed per interval;
**`levels` and `power` are still interval-blind and were left that way**, since
neither is run at two intervals here and fixing a table nobody has pooled yet
would be a change without a measurement behind it. This is the defect the 1d
document's "never pooled with 1d" warning was about, living in the code that
prints the tables.

**3. The verdict's own counts were not reproducible from the harness.** The 1d
write-up's headline trade numbers - 6 of 420 above the hardest arm, 206 of 420
against the twin, 8 BH survivors - were not printed by `fear_greed_report.py`.
They are now, and they reproduce to the digit on the committed 1d panel, which
is the check that this document's 2 of 420 and 214 of 420 are the same
statistic and not a new one.

**4. The 1d document mis-describes its 8 BH survivors** as "all the ungated
arm"; 2 of the 8 are `gold` under the `risk_off` gate.

**5. The 1d section 2 table omits `eurgbp`**, the placebo, which is the largest
range inflation of the six crosses at 1d (5.777) and the largest in the store at
15m (8.363).

**6. The 1d note on the missing generator placebo is wrong about the store.**
"The synthetics present are 15m-only or absent" - there are none at any
interval. The store holds 14 feeds from two sources, and the `DERIV` venue
carries that broker's real FX, crypto and gold rather than its volatility
indices. The correct statement is that **this store has no generated process in
it at all**, so neither interval can have a generator placebo and `eurgbp` is
the best control either run supports.

**7. The log-gap identity leaks on zero-move swings.** `speed = size - bars`
holds to 1.1e-15 on the close-pivot rows this study reports and loses up to
3.3e-02 on the high/low detector and on surrogate paths, because a swing whose
close move is exactly zero is dropped from two of the three statistics and kept
in the third. Larger than several of the effects in the table.

## What was not done, and why

* **No `levels` section.** Section 4 gives the measured reason (5.6-10.4
  crash-labelled levels on `Pivots`).
* **No 2008 control, and no substitute for it.** The 15m rule's only positive
  control is the planted crash. There is no 15-minute episode in this window
  that is known in advance to be risk-off, so the control that makes the 1d
  study trustworthy has no counterpart here, and that is the single biggest
  weakness of this document.
* **No cost applied**, and no cross priced. Three legs are priced in
  [Costs](#costs-and-the-one-thing-this-interval-can-price) and the figures are
  applied to nothing.
* **No era split**, because the window is 63 days inside one era. The six-block
  diagnostic replaces it and is not a test.
* **No second window.** 4,760 bars is all the 15m data this store holds for
  eight feeds, so there is no discovery/confirmation split and no out-of-sample
  period. Every number here is in-sample on one 63-day window, which for the
  trade section means **one realisation of one dollar trend**.
* **No calibrated order test.** The sign-clustering arm's zero control fails on
  the duration gap at 15m as it did at 1d, in both directions on different
  feeds.
* **The JPY crosses are still not three independent cells.** `audjpy`, `nzdjpy`
  and `cadjpy` all carry the `usdjpy` leg. Counted as one cell for
  Benjamini-Hochberg would be stricter and was not done; with 0 survivors at
  both scales it changes nothing.
* **No intrabar reconstruction of a cross's true range.** Possible from 1m legs
  over a shorter window and would turn the bound inflation into a direct
  measurement; it would change nothing here, because every cross reading is
  close-only.

## The code

The same modules as [fear-greed.md](fear-greed.md). Two were changed for this
run and both changes are additive:

| file | change |
|---|---|
| `research/ideas/fear_greed_control.py` | `FEWEST_CRASH_BARS`, and `crash_control` returns a `skipped` row instead of raising where the interval's data does not reach 2008 |
| `research/ideas/fear_greed_report.py` | prints `NOT RUN` for a skipped control; sorts the trade table by interval first; adds `trade_summary`, the per-interval counts the verdict rests on |

### How to run it

```sh
uv run python -m research.ideas.fear_greed_run --out <dir> --jobs 16 \
    --intervals 15m --sections control,asym,trade,power --draws 16
uv run python -m research.ideas.fear_greed_report <dir>
```

`--draws` defaults to 16 and must not be lowered for a positive claim: a
hardest-of-N test at four draws is anti-conservative, which is deviation 6 of
the 1d study. `--sections` omits `levels` deliberately. **Do not add
`--intervals 1d,15m` and read one table**: they are two rules, and the report
now keys the trade table on the interval so a pooled run is at least legible.

Analysis runs on the research machine, never on the production instance, which
has two cores shared with the live desk.
