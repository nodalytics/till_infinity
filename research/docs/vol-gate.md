# A volatility gate buys cheaper trades, not better ones, and the duty-cycle twin cannot tell you that

Measured 2026-11-06 on the lab with [`vol_gate.py`](../harness/vol_gate.py) and
[`vol_gate_report.py`](../harness/vol_gate_report.py): 8 traded markets and 4 Deriv synthetics at a
15-minute base, **198,529 to 294,532 bars each (5.7 to 11.8 years)**, **10,368 real-arm
gate-versus-twin cells** and about **145,600 non-overlapping trades per direction rule** on the
traded panel at the headline cell.

The proposal was: *build a high-accuracy volatility model, trade only when it predicts high
volatility, and take direction from other indicators.*

| question | verdict |
|---|---|
| **Does gating a direction rule on predicted high volatility produce a book that pays?** | **No.** The best rule, at the tightest keep rate, goes from **-0.121R** to **-0.023R** a trade and never crosses zero. **2 of 128** instrument x rule x keep cells are net-positive in **both** halves, where chance gives about 1.5 |
| **What did the duty-cycle twin read?** | **It passed, and passing it means nothing.** The gate beats its same-keep-rate random twin on net R in **2,314 of 6,912** traded cells after Benjamini-Hochberg - and the **day-shuffled walk beats its own twin in 2,544 of the same 6,912**, *more often than the real market*. A control a shuffled series passes more often than the market is not a control |
| **On gross R, which carries no cost term?** | **Almost nothing, and the one exception does not pay.** Per cell: **63 of 6,912** survive on the real arm against **0 of 6,912** on the walk. Pooled over the 8 instruments, three of the four rules are null (`coin` +0.82, `rev1` +0.56, `mom1` +4.60 against its walk's +3.24) and `donch` reads **+5.62 against its walk's +2.73**. Its gross lift over the ungated book is **+0.064R** against the walk's +0.014R - and the quoted round trip at that keep rate is **0.074R**, so the book is **-0.026R** a trade |
| **How much of the improvement is the cost arithmetic?** | **80% to 109% for a coin and 49% to 87% for the direction rules.** Cost in R falls **2.5x** across the predicted-volatility quintiles - **0.2026 to 0.0810** - while gross expectancy moves **+0.038**. For a zero-skill rule the whole gain is arithmetic, and at two keep rates it is *more* than the whole gain |
| **Is the gate the session clock?** | **A third of it is.** The hour explains **18.7% to 39.6%** of when the forecast gate fires. Deseasoning it cuts that to **0.9-3.0%** - and makes the book **worse**, -0.062R against -0.041R, because the clock is where the wide stops are |
| **In cash rather than in R?** | **Most of the gain goes.** Across the same quintiles net R improves 0.231 to 0.071 while fixed-unit cash improves only 0.458 to 0.337 - `crash-timing.md`'s lesson for the sizing switch, reproduced for the entry gate |
| **Does a *forecast* beat production's *contemporaneous* percentile?** | **It buys cheaper trades and does not pay better.** The forecast gate reaches the lowest cost in R of the three (0.0564 against `tr_percentile`'s 0.0666) and the *worse* net (-0.0413 against -0.0366). Both are negative and the gap is inside the noise |
| **Is the volatility model any good?** | **Yes, and it does not help.** Gradient boosting cuts QLIKE **44%** against the shipped EWMA (0.0704 against 0.1246) and lifts Spearman from **0.49 to 0.76** out of sample. It does **not** fix the band: a Gaussian 99% nominal still covers 96.4% (EWMA) and 97.1% (GBM), where a Student-t(4) covers 98.8% and 99.1% |
| **Was the null a blind test?** | **No.** A trend planted only in the high-volatility regime is caught at pooled gross z **+7.32** at the smallest size swept (0.02 forecast units a bar) and **+24.18** at 0.20, on the same arm, rule and basis as the real reading of **+5.62** - which is therefore smaller than a drift of 0.02 forecast units a bar, and above its walk's **+2.73** |
| **Should anything be built?** | **No gate.** The one thing worth keeping is the cost reading itself: a 15m book pays **0.20R** a trade in spread in its quietest volatility quintile and **0.08R** in its busiest, which prices ideas before they are measured |

## The claim, and the one it is distinct from

The **sizing** version of this gate is closed and shipped off. `strategies/config.py`'s
`spike_above` halves size when the 14-bar true-range average reaches the 80th percentile of its own
last 1,500 bars, and its default is `0.0` - *off is the measured setting*. Halving on the switch
beat halving a random fifth of positions in **1 of 18 cells unstopped and 0 of 18 with a stop**, and
a uniform cut in risk per trade beat it everywhere ([crash-timing.md](crash-timing.md),
[session-switch.md](session-switch.md)).

The claim here is a different sentence, which those studies could not test:

> Does gating a direction rule **on entry** on **predicted** high volatility produce a book that
> pays?

Those asked what to do with the size of a position already taken; this asks whether to take it. And
they gated on a *contemporaneous* percentile where this gates on a *forecast*, which is the second
thing nobody here had run. Both of their findings are carried in as controls rather than assumed:
the cash unit, and the hour.

## What is not being re-answered

**Volatility is forecastable here**, and the run confirms it rather than discovering it:
[fractal-twins.md](fractal-twins.md) reads expansion from compression at AUC 0.728-0.738,
[impulse-vol.md](impulse-vol.md) adds +0.167 to +0.355 of a forecast unit on 8 of 8 traded markets,
[expansion.md](expansion.md) reads AUC 0.798 held out. **Direction is closed** five ways -
[trigger-expectancy.md](trigger-expectancy.md), [chart-patterns.md](chart-patterns.md),
[bos-predict.md](bos-predict.md), [fractal-twins.md](fractal-twins.md), and
[findings.md](findings.md)'s gate that finds a *planted* drift at z +2.90 and earns 2% of a spread.
The four direction rules below are carried as arms **expected to be null**.

## The rules, frozen before the run

Everything below is in the harness docstring, which was written before any real-data run.

* **Split** first half by time is discovery, second half confirmation. Every model is fitted on
  discovery only and both halves are reported.
* **Mask** no rollover hour (20-23 UTC) and no bar within 4 of a session gap -
  [fx-reversal.md](fx-reversal.md)'s mask, reused.
* **Stage A** target is `log mean(|r|)` over the next 12 bars. Features use bars up to **and
  including** the decision bar, because the trade is entered at that bar's close. Three models:
  `ewma` (the shipped EWMA of `|r|`, span 60, untouched), `har` (OLS on log realised volatility at
  1h, 1d, 1w) and `gbm` (histogram gradient boosting on compression, range and clock features).
* **Stage B** risk is `3.0 x the book's volatility estimate` - `risk_vol` is a structures feature
  about the level, and the stop is `Intent.stop_vol`, whose live median is 3.0. Target `N x risk`,
  stop `1 x risk`, raced bar by bar over at most 96 bars on each bar's own high and low. **Both
  barriers inside one bar counts as the stop.** Unresolved at 96 bars, marked to market. Cost is one
  **quoted** round trip, charged in R and in cash.
* **Non-overlap** the ungated book is sequential: a signal is taken only when flat. The gate, its
  twin and its hour placebo then select subsets of *that* candidate set, which is what makes the
  keep-rate comparison exact.
* **Two books** (`ewma`, `gbm`) differing only in what the stop is a multiple of, and **three gate
  statistics** at keep rates 0.50 / 0.30 / 0.20 / 0.10: `model` (the book's own forecast), `trpct`
  (production's switch - a 14-bar EWMA of the bar range, **contemporaneous**) and `samehour`
  ([session-switch.md](session-switch.md)'s `deseason`). Every rank window is production's 1,500
  bars, so the three differ in *what* they rank and not in how far back.
* **Direction rules** `mom1`, `rev1`, `donch` (20-bar closing extreme) and `coin`. **The coin is the
  sign-flip surrogate**: identical entry bars, identical stops, identical costs, no direction
  content.
* **Errors** day-block bootstrap on every mean. **Multiplicity** Benjamini-Hochberg at q=0.05 over
  the full cell count, stated with every table.

### Costs come from the quote

`SPREAD_POINTS` is the spread the terminal quoted on 2026-11-05, never the stored per-bar column,
which reads 3.3-8.3x below it on FX and 6.5x *above* it on `Volatility 75 Index`. The stored column
is in **points, not price**; reading it as price once put a 476% round trip on EURUSD and reordered
every instrument by cost.

## Stage A: the model is good, and good is not the point

Traded panel, confirmation half, 8 instruments, about 1.1M rows:

| model | QLIKE | Spearman | Gaussian 90 / 99 | Student-t(4) 90 / 99 | calibrated 90 / 99 |
|---|---:|---:|---:|---:|---:|
| `ewma` (shipped) | 0.1246 | 0.4915 | 0.8851 / 0.9642 | 0.8935 / **0.9882** | 0.8999 / 0.9911 |
| `har` | 0.1039 | 0.5978 | 0.8978 / 0.9709 | 0.9058 / 0.9906 | 0.9005 / 0.9911 |
| **`gbm`** | **0.0704** | **0.7625** | 0.8906 / 0.9708 | 0.8994 / **0.9913** | 0.8985 / 0.9906 |

Gradient boosting beats the shipped EWMA on **8 of 8** traded instruments, with Spearman running
0.696 to 0.808 against the EWMA's 0.407 to 0.624, and the discovery-to-confirmation QLIKE drift is
0.0563 to 0.0704, so it is not fitted noise.

**Two things in that table are worth more than the win.** First, the better model does **not** fix
the band: the Gaussian 99% nominal covers 96.4% under the EWMA and 97.1% under the GBM, while a
Student-t(4) covers 98.8% and 99.1%. The band's defect is its *shape*, not its *scale*, and a better
point forecast cannot reach it - consistent with `vol-particle.md` and with the one-bar band work.
Second, the whole of Stage A changes the book by **0.008R a trade** (see below). A 44% QLIKE
improvement is worth less than a tenth of a spread.

## The question: the duty-cycle twin passes, and the walk passes harder

Traded panel, keep rate below 1, **6,912 cells on each arm**, Benjamini-Hochberg at q=0.05 over all
of them:

| arm | measure | BH rejections | of which positive | median z |
|---|---|---:|---:|---:|
| **real** | **net R** | **2,314** | 2,307 | **+1.683** |
| **walk** | **net R** | **2,544** | 2,541 | **+1.779** |
| real | gross R | 63 | 58 | +0.385 |
| **walk** | **gross R** | **0** | 0 | +0.205 |
| real | fixed cash | 238 | 190 | +0.378 |
| walk | fixed cash | 783 | 581 | +0.269 |

**Read the first two rows together.** A series with its days permuted - no direction memory, no
volatility clustering across days - beats its own duty-cycle twin on net R in **more** cells than
the real market does. The duty-cycle twin is necessary and it is nowhere near sufficient, and this
is the study's main contribution to the desk's method rather than to its book.

**Why it fails is arithmetic.** A random twin keeps the same *number* of trades but keeps them at
the book's *average* cost in R. A volatility gate keeps the ones whose stop is widest, and therefore
whose spread is cheapest in R. The twin controls for trading **less**; it does not control for
trading **cheaper**. The harness caught this on generated bars before it ever ran on a market: a
**coin** cleared its net twin at **z = +12.8** at keep 0.5, with gross expectancy flat (-0.141 to
-0.138) and cost in R falling from 0.676 to 0.279.

So every control is run on three measures, and `gross` - which has no cost term in it - is the one
that decides the study. On gross the real arm's median z is **+0.385** against the walk's **+0.205**.

## The cost arithmetic, which is the whole effect

Traded, confirmation half, `gbm` book, `model` gate, 2R target. `d_cost / d_net` is the share of the
net improvement that is the spread getting cheaper in R:

| rule | keep | trades | gross | cost in R | net | d_net | d_gross | d_cost | **cost share** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `coin` | 1.00 | 73,199 | -0.0019 | 0.1031 | -0.1050 | | | | |
| `coin` | 0.50 | 36,627 | +0.0017 | 0.0765 | -0.0748 | +0.0302 | +0.0036 | +0.0266 | **0.88** |
| `coin` | 0.20 | 14,671 | -0.0051 | 0.0624 | -0.0675 | +0.0374 | -0.0032 | +0.0406 | **1.09** |
| `coin` | 0.10 | 7,352 | +0.0098 | 0.0562 | -0.0464 | +0.0586 | +0.0117 | +0.0469 | **0.80** |
| `mom1` | 0.10 | 7,400 | +0.0158 | 0.0563 | -0.0405 | +0.0733 | +0.0266 | +0.0467 | 0.64 |
| `rev1` | 0.10 | 7,268 | +0.0007 | 0.0564 | -0.0557 | +0.0445 | -0.0017 | +0.0462 | **1.04** |
| `donch` | 0.10 | 5,450 | +0.0340 | 0.0567 | -0.0227 | +0.0984 | +0.0505 | +0.0479 | 0.49 |

For the **coin** - a rule with no direction content whatever - the cost share is **0.80 to 1.09**,
and at two keep rates it exceeds 1, meaning the gate's gross expectancy moved *against* it and the
cheaper spread paid for that too. For `rev1` it is 0.85 to 1.04. For `mom1` 0.60 to 0.72 and for
`donch` 0.49 to 0.59.

The driver, pooled over the traded panel and all four rules, per predicted-volatility quintile:

| quintile | trades | **cost in R** | gross | net | fixed cash |
|---|---:|---:|---:|---:|---:|
| 0 (quietest) | 108,580 | **0.2026** | -0.0285 | -0.2311 | -0.4582 |
| 1 | 108,682 | 0.1534 | -0.0185 | -0.1719 | -0.4485 |
| 2 | 108,737 | 0.1284 | -0.0090 | -0.1375 | -0.4369 |
| 3 | 108,655 | 0.1062 | +0.0011 | -0.1051 | -0.3881 |
| 4 (busiest) | 108,966 | **0.0810** | +0.0097 | -0.0713 | -0.3367 |

Cost in R falls **2.5x**; net improves by 0.160; gross moves +0.038, a quarter of it. And the cash
column is the check: measured with a **fixed** position rather than a fixed risk, the same gate
improves 0.458 to 0.337 - a sixth of what the R column shows. That is exactly the gap
[crash-timing.md](crash-timing.md) found between its two units for the sizing switch, reproduced
here for the entry gate.

## The hour: a third of the gate is the session clock

Traded, confirmation, `gbm` book, 2R. `hour_share` is the share of the gate's firing the hour of day
explains:

| gate | keep | **hour share** | cost in R | gross | net | median z (net) | median z (gross) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `model` (forecast) | 0.10 | **0.187** | **0.0564** | +0.0151 | -0.0413 | +1.24 | +0.22 |
| `model` | 0.50 | **0.396** | 0.0764 | +0.0045 | -0.0719 | +2.78 | +0.95 |
| `trpct` (production, contemporaneous) | 0.10 | 0.105 | 0.0666 | +0.0300 | **-0.0366** | +1.65 | +0.74 |
| `trpct` | 0.50 | 0.300 | 0.0838 | -0.0036 | -0.0874 | +1.39 | +0.44 |
| `samehour` (deseasoned) | 0.10 | **0.030** | 0.0797 | +0.0174 | -0.0623 | +1.05 | +0.64 |
| `samehour` | 0.50 | **0.009** | 0.0926 | -0.0004 | -0.0931 | +1.03 | +0.29 |

The forecast gate is **more** of a clock than production's switch is - 18.7-39.6% against 10.5-30.0%
- which is what a model with the hour among its features should be expected to do, and is above the
6.7-9.5% [session-switch.md](session-switch.md) measured for `tr_percentile` at 15m.

**Deseasoning removes the clock and removes most of the benefit with it.** `samehour` cuts the
hour's share to 0.9-3.0% and the book gets *worse*: -0.062R against the forecast gate's -0.041R at
keep 0.10, because cost in R rises from 0.0564 to 0.0797. The clock is where the wide stops are.
"Trade only when volatility is predicted high" is substantially "trade at 14-15 UTC, where the stop
is wide enough that the spread is a smaller fraction of it".

**And the forecast's advantage over production's switch is the cost line, not the edge.** The
forecast gate buys the cheapest trades of the three (0.0564) and still produces a slightly *worse*
net book than the contemporaneous percentile (-0.0413 against -0.0366), which has the higher gross.
Both are negative and the gap is well inside the per-trade standard errors (0.04-0.05).

## Lead with the tail

Traded, confirmation, `gbm` book, `model` gate. `resolved` is the share of trades that reached a
barrier rather than being marked out at 96 bars, which is why the tail sits below `1/(1+N)` even on
the walk:

| rule | target | keep | real | walk | 1/(1+N) | **excess** | resolved |
|---|---:|---:|---:|---:|---:|---:|---:|
| `coin` | 2R | 1.00 | 0.329 | 0.327 | 0.333 | +0.001 | 0.993 |
| `coin` | 2R | 0.10 | 0.320 | 0.301 | 0.333 | +0.018 | 0.968 |
| `donch` | 2R | 1.00 | 0.324 | 0.324 | 0.333 | -0.000 | 0.993 |
| `donch` | 2R | 0.10 | 0.329 | 0.304 | 0.333 | +0.025 | 0.968 |
| `mom1` | 2R | 0.10 | 0.323 | 0.310 | 0.333 | +0.013 | 0.968 |
| `rev1` | 2R | 0.10 | 0.316 | 0.301 | 0.333 | +0.015 | 0.965 |
| `donch` | 4R | 0.10 | 0.143 | 0.132 | 0.200 | +0.011 | 0.849 |
| `donch` | 4R | 1.00 | 0.169 | 0.169 | 0.200 | -0.001 | 0.940 |

**No cell reaches its target more often than the walk by enough to pay for the stop.** The largest
2R excess is `donch` at keep 0.10, **+0.025**, which at 2R is worth about 0.075R a trade against a
cost of 0.057R. The coin reads **+0.018** at the same keep rate on its own entry bars, so most of
that excess is shared with a rule carrying no direction content at all.

## The controls

**The synthetics behave as a named-property control should, and quantify the mechanism.** The four
Deriv feeds are carried for one named property each - `Volatility 25/75 Index` and `Step Index` are
generated at constant volatility, so a gate on predicted volatility has nothing to select;
`Jump 75 Index` has fat tails without clustering. Their cost in R is tiny (0.012 to 0.044 against
0.028 to 0.220 on the traded panel) because Deriv's spreads are small relative to their volatility -
and with cost in R near zero, `z_net`, `z_gross` and `z_cash` collapse onto each other:

| symbol | cost in R | z net | z gross | z cash |
|---|---:|---:|---:|---:|
| Jump 75 Index | 0.012 | +0.33 | +0.32 | +0.33 |
| Step Index | 0.014 | +0.95 | +0.90 | +0.91 |
| Volatility 75 Index | 0.016 | +1.66 | +1.63 | +1.66 |
| XAUUSD (traded) | 0.028 | -0.66 | -1.26 | -1.30 |
| Volatility 25 Index | 0.044 | -1.43 | -1.51 | -1.50 |
| XAGUSD (traded) | **0.220** | **+4.04** | -0.36 | -0.76 |

Across the 12 instruments, **corr(cost in R, z net) = +0.646** and **corr(cost in R, z gross) =
-0.145**. XAGUSD, whose quoted round trip is a fifth of its own R, shows the largest net z in the
study and a *negative* gross z. The gate's apparent skill is proportional to how much the instrument
costs to trade.

**One control reading is not clean and is reported as such.** `Volatility 75 Index` - a
constant-volatility generator - reads z +2.56 on all three measures at keep 0.20. It does not
survive Benjamini-Hochberg over the grid, and its cost in R is 0.016 so it cannot be the cost
arithmetic, but it is not a zero and it is the one row that would want re-running.

**Power.** A trend is planted *only* in the high-volatility regime (aligned with the trailing 20-bar
move, so it persists for as long as that move does) and swept, scored the same way as the real arm,
pooled over the 8 traded markets by Stouffer:

All rows are `donch`, `gbm` book, `model` gate, 2R, both halves, so the real and walk arms are
directly comparable to the planted ones:

| arm | pooled gross z, keep 0.50 | keep 0.10 |
|---|---:|---:|
| planted 0.20 | +24.18 | +17.56 |
| planted 0.10 | +14.80 | +10.65 |
| planted 0.05 | +10.80 | +7.00 |
| planted 0.02 | **+7.32** | +5.78 |
| **real** | **+5.62** | +4.99 |
| **walk** | **+2.73** | +1.15 |

**The test is not blind anywhere in the swept range.** The smallest planted drift, 0.02 forecast
units a bar, is caught at +7.32, so a null here is a null with demonstrated power rather than a
blind test.

It also places the real reading. `donch` sits **below** the smallest planted effect and **above** its
own walk, which is the honest description: there is something in the real arm that the shuffled
series does not have, and it is smaller than a drift of 0.02 forecast units a bar - about 0.007R a
bar against a 3-unit stop. The section below prices it.

## The one reading that is not a null, and why it still does not pay

`donch` - a 20-bar closing extreme - is the only rule whose gross expectancy responds to the gate by
more than its walk does. It is reported here rather than buried, because the rest of this page is a
null and a null is only worth reading if the exceptions are in it.

Pooled Stouffer gross z over the 8 traded instruments, gate against its duty-cycle twin, both
halves, `gbm` book / `model` gate / 2R:

| rule | real, keep 0.50 | its walk | real, keep 0.10 | its walk |
|---|---:|---:|---:|---:|
| `coin` (no direction content) | +0.82 | +2.13 | +1.23 | -1.54 |
| `rev1` | +0.56 | -0.86 | -0.26 | -1.47 |
| `mom1` | +4.60 | +3.24 | +2.83 | +0.68 |
| **`donch`** | **+5.62** | **+2.73** | **+4.99** | **+1.15** |

`coin` and `rev1` are null, `mom1` is matched by its walk within about 1.4 sigma, and `donch` is
roughly 3 sigma clear of its walk. Its gross expectancy also rises monotonically across the
volatility quintiles, **-0.053 to +0.029**, with a per-bucket standard error of 0.027.

**Then it is priced, and that ends it.** At keep 0.10, pooled over the traded panel:

| arm | ungated gross | gated gross | lift | quoted round trip | **net** |
|---|---:|---:|---:|---:|---:|
| `donch` real | -0.0154 | +0.0481 | **+0.0635** | 0.0737 | **-0.0256** |
| `donch` walk | -0.0078 | +0.0061 | +0.0139 | 0.0492 | -0.0431 |

Even crediting `donch` the **entire** real-minus-walk gross lift of +0.050R, the quoted round trip
at that keep rate is 0.074R and the book loses **0.026R a trade**. In the confirmation half alone it
is +0.034R gross against 0.057R of cost, so -0.023R. On XAGUSD, whose round trip is 0.16R, it is
-0.097R.

Three further things weaken it. It **shrinks out of sample** - pooled gross z +4.96 in discovery
against +3.17 in confirmation at keep 0.50. **6 of 8** instruments agree in sign between halves,
where chance gives 4 (P(>=6 of 8) = 0.145). And across the whole grid, **2 of 128** instrument x
rule x keep cells are net-positive in both halves, where chance gives about 1.5.

So the claim this supports is narrow and is not a trading claim: *the 20-bar-extreme rule's gross
expectancy improves with predicted volatility by more than a day-shuffled series' does, by about
0.05R a trade, which is two thirds of what it costs to deal.* Re-opening it would mean finding a
cheaper way to take the trade, not a better gate.

## The bugs this run caught

* **The duty-cycle twin alone is not a control for this question**, found on generated bars before
  the harness ever read a market. A coin cleared its net twin at **z +12.8** at keep 0.5 with flat
  gross and cost in R falling 0.676 to 0.279. The design changed in response: every control now runs
  on `net`, `gross` and `cash`. Had the run gone ahead on net alone it would have reported 2,314 BH
  survivors and a volatility gate that works.
* **The first planted drift was unmeasurable and the sweep said so.** Aligning the plant with
  `sign(r[t-1])` gives a trade exactly one aligned bar - 0.02 forecast units against a 3-unit stop is
  0.0067R - and the sweep read gross z between **-1.0 and +0.6 at every planted size**, including
  0.20. A power sweep that is flat in its own effect size is reporting a broken plant, not a blind
  test. Fixed by aligning with the trailing 20-bar move so the drift persists.
* **`time.time()` on the lab stepped 8 hours mid-run** and reported 29,679 s for a 20-minute smoke
  test, which would have mis-sized the real run by an order of magnitude. Runtime was re-measured
  with `time.monotonic()` and the real cost was 80 s per 60k bars; the profile then put 64% of it in
  the twin draw, which now serves all three measures from one set of permutations.

## What could not be measured

* **The coin is not a bar-matched surrogate for `donch`.** Each rule generates its own entry bars,
  so the coin is a surrogate for the gating machinery - same gate, same stops, same costs, random
  side - and not a sign-flip of `donch` on `donch`'s own bars. That is why `donch` is priced against
  the walk above rather than against the coin, and a bar-matched sign-flip arm is the first thing a
  re-opening should add.
* **A truly gated book could re-enter sooner.** The gate selects from the *ungated* book's
  non-overlapping candidates, which is what makes the keep-rate comparison exact and what understates
  a real gated book's trade count. Not modelled.
* **Entries are at the close with a full quoted round trip.** No maker side, no limit fills, no
  partial spreads. [limitfills.md](limitfills.md) says the winner's curse is about the size of the
  better price, so this is unlikely to reverse anything, but it is not measured here.
* **One interval and one stop multiple.** Everything is 15m with `risk = 3.0 x vol`. The *size* of
  the cost arithmetic is specific to that: the same spread is far dearer in R at a shorter clock, so
  the 2.5x fall across quintiles is a 15m number and not a general one.
* **The power sweep's blind point was not bracketed.** The smallest planted size (0.02) was still
  caught at pooled gross z +5.78, so the lower limit is below 0.02 and this run does not say where.
* **`Volatility 75 Index`'s +2.56** on a constant-volatility generator is unexplained, as above.

## What this changes

**Nothing ships.** `spike_above` stays at 0.0 and no entry gate is added. Four things are worth
carrying forward:

1. **Every on/off rule on this desk now needs its control run on a cost-free measure**, not only
   against a random twin at the same duty cycle. The twin answers "does trading less explain it" and
   is silent on "does trading cheaper explain it", and on a 15m book the second is the larger effect.
   The day-shuffled walk beating its twin more often than the market is the cheapest way to show it.
2. **Cost in R by volatility quintile is a useful number in its own right**: 0.20R a trade in the
   quietest fifth and 0.08R in the busiest, on this panel at 15m. An idea whose edge is smaller than
   the difference between those two is an idea about costs.
3. **A better volatility model is worth about 0.008R a trade here**, through the stop and nothing
   else. It is still the right thing to improve for sizing and bands - where
   [volatility-estimators.md](volatility-estimators.md) and the envelope work already use it - but it
   is not a route to a book that pays.
4. **`donch` x predicted volatility is the one cell worth re-opening**, and only on the cost side.
   Its gross lift over a day-shuffled series is about +0.05R a trade and the quoted round trip is
   0.074R, so the question it poses is whether the same trade can be taken for under 5 basis points
   of R - a maker-side or a cheaper instrument - and not whether the gate can be sharpened. Any
   re-opening needs a bar-matched sign-flip arm, which this run does not have.

## Reproducing

```sh
./.secrets/lab.sh sync
./.secrets/lab.sh exec 'cd $HOME/till_infinity && nohup env OMP_NUM_THREADS=2 \
    SEQLAB=$HOME/till_infinity/data/seqlab OUT=$HOME/till_infinity/out \
    $SKPY -u repo/research/harness/vol_gate.py \
    > logs/vol_gate.log 2>&1 &'
OUT=<fetched> uv run python research/harness/vol_gate_report.py
```

`$SKPY` is any interpreter on the lab carrying scikit-learn; the one `lab.sh run` uses does not,
which is why this launches through `exec`.
The committed harness differs from the executed one **only in docstring prose**: the executed build
hashed `35af8b5def9a483a445339fcad6955a5`, and the two parse to an identical syntax tree once
docstrings are stripped.
