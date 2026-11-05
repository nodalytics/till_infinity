# Conditional on the volatility state, an impulse says a great deal about volatility and nothing that pays about direction

Measured 2026-11-05 on the lab with [`impulse_vol.py`](../harness/impulse_vol.py), on bars pulled
with [`seqlab_pull.py`](../harness/seqlab_pull.py): 8 traded markets and 4 Deriv synthetics at a
15-minute base, 198,529 to 294,533 bars each (5.7 to 11.8 years), 11,520 cells.

An **impulse** is a bar whose move is large relative to the volatility forecast made *before* it:
`|z| = |r| / EWMA(|r|, 60).shift(1)` at or above 2, 3 or 4.

| question | verdict |
|---|---|
| Does an impulse say anything about **volatility** that the volatility state does not? | **Yes, and it is large.** Forward volatility runs **+0.167 to +0.355** of a forecast unit above a bar matched on the same instrument, volatility bin and hour, at 12 bars, on **8 of 8** traded markets, every one at the bootstrap floor (p 0.001). The four constant-generator synthetics read **+0.002 to +0.018** and the i.i.d.-shuffled twin of each traded series itself reads **-0.008 to +0.018** |
| Does it say anything about **direction**? | **Something real, and nothing that pays.** The sign-flip arm reads **+0.0013** with its own sd at **0.0750**, and real cells beat it on **38.3%** of traded cells against **3.9%** of synthetic ones - so sign structure exists. It survives the calendar (97.0% kept) and the rollover mask (98.6% kept), and it does **not** survive the price: at the headline cell **4 of 8** traded instruments agree in sign between halves, which is chance, and **1 of 8** is positive net of the quoted round trip out of sample - by 0.048 of a forecast unit, a fifth of a spread, with its own interval straddling its cost in both halves |
| **A squeeze then an impulse**, vs an impulse in already-high volatility? | **The same information, a different level.** The impulse's own contribution is flat across states - `d_rv` at 12 bars is 0.226 in a squeeze, 0.237 in high volatility, 0.226 overall. What changes is where it lands: 48 bars later, forward volatility is **1.49x** the pre-event forecast after a squeeze impulse and **0.95x** after a high-volatility one |
| **Does volatility rise or fall afterwards?** | **Rises, then decays towards the state it came from.** Over the traded panel at trigger 3, forward volatility is **1.78x** the pre-event forecast at 1 bar, 1.63x at 4, 1.45x at 12 and 1.23x at 48, and the excess over the matched placebo decays **0.534 -> 0.366 -> 0.226 -> 0.109** |
| Does the **multi-timeframe** version differ? | **No.** A 4-hour squeeze with a 15-minute impulse reads `d_rv` **0.225** against 0.226 for the single-timeframe squeeze and 0.226 for no condition at all. The slow leg adds nothing the fast one does not already carry |
| Should anything be built? | **No gate, no trade.** The risk reading is the one this desk already has, measured here conditional on the state for the first time. The direction reading is below its own dealing cost on every instrument |

## The claim, and the three it is distinct from

The directional reading of an impulse is closed here three ways, and none of them was re-run:
[`fractal-twins.md`](fractal-twins.md) found candle shapes call volatility and not direction over
20 instruments and ~1.18M moments against random-walk controls; [`bos-predict.md`](bos-predict.md)
found a break of structure carries no side beyond the geometry of its two levels; and
[`findings.md`](findings.md) records a direction gate that finds a *planted* drift at z +2.90 and
still earns 2% of a spread.

The claim measured here is narrower, and is a sentence none of those three could test:

> **Conditional on the volatility state at the time, does an impulse say anything the volatility
> state does not already say?**

Those studies compared a shape against a walk. This one compares an impulse against a
**volatility-and-hour-matched bar of the same instrument**, which is a different null and a
different question. It is asked of two channels, and keeping them apart is the point:

* the **risk** channel - forward realised volatility. This desk already forecasts risk, so a
  reading here confirms the known. Its job in this study is to be the **positive control**: it runs
  on the same events, through the same estimator, with the same bootstrap, so a null on direction
  beside a strong reading on volatility is a null with demonstrated power rather than a blind test.
* the **direction** channel - the forward move signed by the impulse. This is the open question,
  and the sign-flip arm decides it.

## The rules, as frozen before the run

| | |
|---|---|
| base | 15-minute bars, UTC |
| volatility forecast | `EWMA(abs(r), span 60).shift(1)` - **shifted, so it never sees its own bar** |
| impulse | `abs(r) / forecast >= 2.0, 3.0, 4.0` |
| volatility state | the forecast's rank inside a trailing 500-bar window (min 200). A **global** quantile would use the future to label the past |
| slow leg | the same construction on 4-hour calendar bins: slow return = **the sum of the fast returns in the bin**, never a difference of aligned closes, which would turn every session gap into a fabricated one-bar return. Its EWMA is shifted by one bin, so a bar inside bin `j` may read bin `j`'s rank without look-ahead |
| bands | `all`; `lo` = state in its lowest trailing third (a squeeze); `hi` = highest third; `slow_lo` / `slow_hi` = the same on the 4-hour leg |
| horizons | 1, 4, 12, 48 bars, **on one event set** - every cell requires the longest window to exist, so the horizons differ by horizon and not by which bars survived |
| forward move | the signed sum over `(i, i+k]`, divided by the **pre-event** forecast, then signed by the impulse: positive means the move continued |
| forward volatility | the **mean `abs(return)`** over the same window divided by the same forecast, so the null is exactly 1.0. An RMS would be one estimator over a different one and their ratio moves with the shape of the tail |
| headline cell | band `all`, trigger 3.0, horizon 12 - named before the grid was read |
| uncertainty | day-block bootstrap, 1,000 draws, 90% interval, because impulses cluster in days |
| below 100 events | reported with its `n` and read as noise, never dropped - a dropped cell is invisible |

### The controls, which are the study

1. **The sign-flip surrogate**, 200 draws per cell. Keep every `abs(return)` in its original order
   and randomise the signs: the volatility path - the clustering, the squeeze, the expansion -
   survives *exactly*, direction does not. Any directional effect that appears here is volatility,
   not skill. It is applied analytically rather than by re-running on a flipped series, and that is
   not an approximation: with `r'[t] = abs(r[t]) * s[t]` the forecast, the state and the event set
   are functions of `abs(r)` alone and so are **identical**, and the continuation of event `i` is
   `s[i] * sum_{t in (i,i+k]} abs(r[t]) s[t] / vol[i]`. Checked against a literal re-run on a
   flipped series before the study: forecast, state, `abs(z)`, event set and forward volatility all
   identical, and the continuation agreed to a **maximum absolute difference of 0.0** over 2,246
   events. Costing two cumulative sums instead of a re-dressing is what makes 200 draws affordable.
2. **A volatility-and-hour-matched placebo.** For every impulse, a non-impulse bar from the same
   instrument, the same volatility bin (20 of them), the same hour of day and the same band. The
   matching **filled completely** - `placebo_n == n` on all 8 traded instruments at the headline
   cell.
3. **The i.i.d.-shuffle arm**, which is the sign-flip's opposite number for the risk channel. A
   permutation of the returns keeps the marginal distribution - the fat tails, every
   `abs(return)` - and destroys the clustering. The sign-flip arm is silent about volatility by
   construction, so without this there is no null for the risk channel at all.
4. **Four Deriv synthetics, each for one named property.** They are real markets here, not a
   general control - [`findings.md`](findings.md) sets that rule - so each is carried for the
   property its published generator fixes and for nothing else: `Volatility 25/75 Index` are
   generated at **constant volatility**, so there is no clustering in them to find; `Step Index` is
   a fixed step; and `Jump 75 Index` has **fat tails without clustering**, which is the one control
   that separates "the harness found volatility memory" from "the harness manufactured a reading
   out of a heavy tail".
5. **Two attribution arms for the direction channel**, because the sign-flip surrogate is a
   *generated* null and has no daily cycle in it at all - the one thing it cannot rule out. If
   impulses at some hour are systematically signed and that hour is systematically followed by
   drift, `side x forward move` is non-zero with nothing conditional about it.
   - `deseason`: returns with the **weekday x hour-of-day** mean removed. The cell means are read
     from the whole sample, so this arm may only ever remove a reading, never create one.
   - `masked`: the event set with the **20:00-23:00 UTC rollover** and the first four bars after
     any session gap dropped. This is [`fx-reversal.md`](fx-reversal.md)'s own mask, reused rather
     than invented.
6. **A discovery / confirmation split** by time, on every cell.
7. **Benjamini-Hochberg** across the direction family, and the synthetics as the calibration
   check on the same grid.

## The data

Pulled from the MT5 bridge on 2026-11-05 with `seqlab_pull.py`, 15-minute bars, newest 2026-11-05.

| instrument | bars | years | from | quoted round trip, in forecast-vol units |
|---|---|---|---|---|
| EURUSD | 294,498 | 11.8 | 2015-01-02 | 0.276 |
| GBPUSD | 294,523 | 11.8 | 2015-01-02 | 0.252 |
| USDJPY | 294,521 | 11.8 | 2015-01-02 | 0.247 |
| AUDUSD | 294,532 | 11.8 | 2015-01-02 | 0.238 |
| USDCAD | 294,516 | 11.8 | 2015-01-02 | 0.270 |
| XAUUSD | 276,422 | 11.8 | 2015-01-02 | 0.163 |
| XAGUSD | 278,206 | 11.8 | 2015-01-02 | 1.354 |
| BTCUSD | 259,485 | 7.4 | 2019-06-09 | 0.258 |
| Volatility 75 Index | 275,052 | 7.8 | 2019-01-01 | 0.013 |
| Volatility 25 Index | 275,052 | 7.8 | 2019-01-01 | 0.127 |
| Step Index | 260,916 | 7.4 | 2019-05-28 | 0.043 |
| Jump 75 Index | 198,529 | 5.7 | 2021-03-08 | 0.028 |

Events at the headline trigger of 3.0 run 5,216 to 14,205 per instrument; at 2.0, 23,571 to
37,764; at 4.0, 548 to 6,143. Every cell in the tables below carries its own `n`.

**The cost line does not come from the bars.** The per-bar `spread` column is in points, not price,
and on this feed it is also **unusable as a cost**: it is exactly zero on 7-35% of bars and its
median is three to eight times below what the terminal quotes. Every cost here is the quoted
spread - see *Bugs this run caught*.

## Result 1: the risk channel, which is the positive control and reads loudly

Forward volatility over the matched placebo, `d_rv`, in units of the pre-event forecast. Trigger
3.0, 12 bars, full sample, per instrument - never only pooled:

| instrument | n | placebo n | rv | rv placebo | **d_rv** | p | d_rv, i.i.d.-shuffled twin |
|---|---|---|---|---|---|---|---|
| EURUSD | 13,738 | 13,738 | 1.507 | 1.311 | **+0.196** | 0.001 | -0.008 |
| GBPUSD | 14,196 | 14,196 | 1.547 | 1.357 | **+0.190** | 0.001 | +0.006 |
| USDJPY | 12,380 | 12,380 | 1.383 | 1.105 | **+0.278** | 0.001 | +0.014 |
| AUDUSD | 11,797 | 11,797 | 1.304 | 1.117 | **+0.187** | 0.001 | +0.012 |
| USDCAD | 13,182 | 13,182 | 1.504 | 1.337 | **+0.167** | 0.001 | +0.009 |
| XAUUSD | 12,785 | 12,785 | 1.458 | 1.243 | **+0.215** | 0.001 | +0.015 |
| XAGUSD | 13,568 | 13,568 | 1.455 | 1.236 | **+0.219** | 0.001 | +0.008 |
| BTCUSD | 10,878 | 10,878 | 1.443 | 1.088 | **+0.355** | 0.001 | +0.018 |
| Volatility 75 Index | 5,411 | 5,411 | 1.064 | 1.062 | +0.002 | 0.728 | +0.015 |
| Volatility 25 Index | 5,298 | 5,298 | 1.068 | 1.057 | +0.011 | 0.028 | +0.021 |
| Step Index | 5,216 | 5,216 | 1.066 | 1.059 | +0.007 | 0.172 | +0.012 |
| Jump 75 Index | 5,888 | 5,888 | 1.065 | 1.047 | +0.018 | 0.001 | +0.005 |

**8 of 8 traded markets at the bootstrap floor; 4 of 4 generated markets flat.** The separation is
a factor of ten to a hundred, and the i.i.d.-shuffled twin of each traded series - the same
returns, the same fat tails, the clustering destroyed - lands with the synthetics, which is what
makes the reading about memory rather than about the tail.

`Jump 75 Index` reaching p 0.001 at +0.018 is the estimator's residual, not a finding: selecting on
`abs(r) / vol` tilts towards a **small denominator**, so an impulse sits at the low end of whatever
bin it is matched in and its forward volatility reads high for that reason alone. On generated
i.i.d. returns the residual was +0.01 to +0.03 at ten matching bins; it is why there are twenty,
and why the shuffled twin is printed beside every reading as the floor rather than assumed away.
The traded readings clear that floor by a factor of ten to forty.

It scales with the impulse, which a label for the stratum would not (traded panel, band `all`):

| trigger | d_rv at k=1 | k=4 | k=12 | k=48 |
|---|---|---|---|---|
| 2.0 | +0.311 | +0.220 | +0.140 | +0.072 |
| 3.0 | +0.534 | +0.366 | +0.226 | +0.109 |
| 4.0 | +0.786 | +0.542 | +0.326 | +0.152 |

and the synthetics stay at +0.004 to +0.057 across the whole of that grid, the largest being
trigger 4 at one bar where `Volatility 75 Index` has 609 events.

## Result 2: volatility rises, then decays towards the state it came from

Traded panel, trigger 3.0. `rv` is forward volatility in units of the pre-event forecast, so 1.0 is
"exactly what the forecast said":

| band | rv, k=1 | k=4 | k=12 | k=48 | placebo, k=48 | **d_rv, k=12** |
|---|---|---|---|---|---|---|
| all | 1.781 | 1.627 | 1.450 | 1.232 | 1.123 | +0.226 |
| `lo` - a squeeze, then an impulse | 1.854 | 1.730 | 1.608 | **1.487** | 1.371 | +0.226 |
| `hi` - an impulse in already-high volatility | 1.694 | 1.495 | 1.247 | **0.945** | 0.835 | +0.237 |
| `slow_lo` - 4-hour squeeze, 15-minute impulse | 1.855 | 1.684 | 1.495 | 1.272 | 1.164 | +0.225 |
| `slow_hi` | 1.722 | 1.563 | 1.392 | 1.181 | 1.067 | +0.227 |

Two readings, and the second is the one worth keeping:

* **Which way volatility goes depends on the state, not on the impulse.** Twelve hours after an
  impulse out of a squeeze, volatility is still 1.49 times the forecast made before it; after an
  impulse in already-high volatility it is 0.95 - *below* it. Volatility mean-reverts, and the
  impulse rides that reversion rather than setting it.
* **What the impulse itself adds is flat across every state**: `d_rv` at 12 bars is 0.226, 0.226,
  0.237, 0.225, 0.227 across the five bands. The matched placebo moves with the band and the gap
  does not. So the squeeze is not a condition that makes an impulse *more* informative; it is a
  condition that says where the level will sit.

**The multi-timeframe version adds nothing.** A 4-hour squeeze plus a 15-minute impulse reads
+0.225 where the 15-minute squeeze alone reads +0.226 and no condition at all reads +0.226. On the
level the fast leg is the stronger conditioner (1.487 against 1.272 at 48 bars), so the slow leg is
a weaker copy of the fast one rather than an independent reading.

## Result 3: the direction channel

### What the sign-flip arm read

Across all 708 real full-sample cells the sign-flip surrogate has mean **+0.00129**, median
absolute mean **0.00347**, and median sd **0.0750** - which is the number every reading below has
to be measured against, and is itself about a third of a round trip on FX.

It is calibrated. On the four generated markets, where there is no direction to find, **9 of 228
real cells** beat it at p<0.05 - a rate of **0.039** against the 0.05 the test claims. On the eight
traded markets **184 of 480** do, a rate of **0.383**. So sign structure conditional on an impulse
exists in real markets and does not exist in generated ones, and the surrogate can tell.

At the headline cell, per instrument, with the day-block interval and the quoted round trip:

| instrument | n | cont | 90% interval | flip sd | flip p | placebo-differenced | round trip |
|---|---|---|---|---|---|---|---|
| EURUSD | 13,738 | -0.049 | [-0.156, +0.058] | 0.070 | 0.413 | +0.036 | 0.276 |
| GBPUSD | 14,196 | -0.016 | [-0.120, +0.093] | 0.066 | 0.741 | +0.046 | 0.252 |
| USDJPY | 12,380 | +0.106 | [-0.012, +0.220] | 0.066 | 0.109 | +0.179 | 0.247 |
| **AUDUSD** | 11,797 | **-0.253** | [-0.352, -0.153] | 0.059 | **0.005** | -0.188 | 0.238 |
| **USDCAD** | 13,182 | **-0.228** | [-0.330, -0.130] | 0.068 | **0.005** | -0.206 | 0.270 |
| XAUUSD | 12,785 | +0.067 | [-0.049, +0.183] | 0.074 | 0.403 | +0.060 | 0.163 |
| XAGUSD | 13,568 | -0.021 | [-0.133, +0.093] | 0.064 | 0.756 | -0.024 | 1.354 |
| **BTCUSD** | 10,878 | **+0.191** | [+0.045, +0.333] | 0.079 | **0.025** | +0.238 | 0.258 |
| Volatility 75 Index | 5,411 | -0.013 | [-0.121, +0.089] | 0.062 | 0.826 | -0.048 | 0.013 |
| Volatility 25 Index | 5,298 | -0.025 | [-0.126, +0.078] | 0.058 | 0.577 | +0.009 | 0.127 |
| Step Index | 5,216 | +0.018 | [-0.097, +0.125] | 0.065 | 0.881 | +0.063 | 0.043 |
| Jump 75 Index | 5,888 | -0.055 | [-0.151, +0.045] | 0.069 | 0.428 | -0.010 | 0.028 |

Three of eight traded instruments read outside their own sign-flip null; five do not, and neither
does any generated one. **Every one of the three sits at or below its own round trip**: AUDUSD
-0.253 against 0.238, USDCAD -0.228 against 0.270, BTCUSD +0.191 against 0.258 - and each
interval contains its cost.

The sign is not shared. AUDUSD and USDCAD **revert**, BTCUSD and USDJPY **continue**, EURUSD and
GBPUSD do neither, and across the bands BTCUSD reverses its own sign (`slow_lo` +0.557,
`slow_hi` -0.268). A reading whose direction depends on which instrument and which band it is
read in is a reading that cannot be traded even if every cell of it were real.

### The attribution arms: it is not the calendar and not the rollover

Over all 2,072 real cells, the share of the reading each arm leaves standing:

| arm | mean abs(cont) | share of the real reading kept |
|---|---|---|
| real | 0.1514 | 1.000 |
| `deseason` - weekday x hour mean removed | 0.1503 | **0.970** |
| `masked` - rollover hours and post-gap bars dropped | 0.1567 | **0.986** |

At the headline cell AUDUSD reads -0.253 real, -0.254 deseasoned, -0.180 masked; USDCAD -0.228,
-0.248, -0.179; BTCUSD +0.191, +0.202, +0.246 - all three still outside the surrogate after both
arms. The hour profile says the same: 19 of 24 hours carry AUDUSD's sign and 16 of 24 carry
USDCAD's, and dropping each instrument's two largest hours leaves 79% and 83% of the effect. So
this is not [`calendar-returns.md`](calendar-returns.md)'s rollover quote artefact.

**BTCUSD is the exception and it is the tell.** Only 14 of 24 hours carry its sign and dropping its
two largest hours leaves **16%** of the effect. Whatever BTCUSD's +0.191 is, it lives in two hours
of the day.

**It is also not a trailing-z-score artefact.** `trailing-zscore-fakes-reversion` records a case
where the shuffled twin took +0.111 of a +0.137 effect. Here the i.i.d.-shuffled twin of the same
series beats its own sign-flip surrogate on **4.7% of all 708 cells** and **3.7%** of the trigger-3
grid, against the 5% the test claims, with a median flip p of 0.547. Destroying the ordering
destroys the whole reading, so no part of it is manufactured by the trailing denominator.

### Discovery and confirmation, which is where it ends

Select each instrument's best cell on the **first half by time** - the cell whose
`abs(cont) - round trip` is largest - and then read that cell, signed the way the first half said,
on the **second half**:

| instrument | selected cell | half 1 net | half 2, signed by half 1 | **half 2 net** |
|---|---|---|---|---|
| AUDUSD | trig 3.0, `lo`, k 48 | +0.450 | +0.294 | **+0.055** |
| BTCUSD | trig 4.0, `slow_lo`, k 48 | +1.143 | +1.073 | **+0.815** |
| USDCAD | trig 4.0, `slow_hi`, k 48 | +0.776 | +0.581 | **+0.312** |
| USDJPY | trig 4.0, `slow_lo`, k 48 | +0.640 | +0.564 | **+0.317** |
| EURUSD | trig 4.0, `slow_hi`, k 48 | +1.195 | -0.235 | -0.510 |
| GBPUSD | trig 4.0, `slow_hi`, k 48 | +0.309 | -0.071 | -0.323 |
| XAUUSD | trig 4.0, `slow_hi`, k 48 | +1.163 | -0.030 | -0.192 |
| XAGUSD | trig 4.0, `lo`, k 12 | -0.608 | -0.294 | -1.648 |
| *Jump 75 Index* | trig 4.0, `slow_hi`, k 48 | +1.026 | +0.475 | *+0.446* |
| *Step Index* | trig 4.0, `slow_lo`, k 48 | +1.386 | +0.945 | *+0.903* |
| *Volatility 25 Index* | trig 4.0, `slow_lo`, k 48 | +0.444 | +0.734 | *+0.607* |
| *Volatility 75 Index* | trig 4.0, `lo`, k 48 | +1.055 | +0.029 | *+0.017* |

**4 of 8 traded instruments confirm. 4 of 4 generated markets also confirm.** A constant-volatility
GBM cannot have a directional edge, so a procedure that finds a paying one on every one of them is
measuring the selection, not the signal. Picking the best of 60 cells at the sparsest trigger and
the longest horizon - where the surrogate's own sd is 0.13 to 0.23 - produces a cell that clears a
small spread about half the time, and the synthetics' spreads are the smallest in the panel.

Taking instead the cell named in advance, and asking only whether each instrument's sign holds:

| | traded | generated |
|---|---|---|
| sign agrees between halves | **4 of 8** | 2 of 4 |
| positive net of the quoted round trip on the confirmation half | **1 of 8** (AUDUSD, +0.048) | 1 of 4 (Jump 75, +0.010) |

Four of eight is exactly chance. **The one survivor is AUDUSD**, and it is the strongest cell in
the study: -0.220 [-0.358, -0.085] on the first half and -0.287 [-0.419, -0.148] on the second,
p 0.015 in each. Against a round trip of 0.238 its interval contains its own cost **in both
halves**, so even the one instrument that confirms is a reversion that cannot be shown to be larger
than the spread it would pay.

Benjamini-Hochberg over the 708-cell direction family returns 142 cells at q<0.10, of which **6 are
on generated markets**. The smallest q is 0.037, which is the floor the surrogate's own resolution
imposes: with 200 draws a p-value cannot go below 1/201, and 96 cells are tied there. BH on a grid
this nested - four horizons and five bands sharing one event set - counts one instrument's reading
many times, which is why the per-instrument tables above are the result and the BH count is a
footnote.

## Power, before the null is believed

A drift of known size, in units of the pre-event forecast, is planted on the bar after every
impulse and swept. The plant lands where it is aimed - the median `abs(cont)` on the synthetics
reads 0.045, 0.095 and 0.195 for plants of 0.05, 0.10 and 0.20 - and the detection rate against the
same sign-flip null is:

| planted drift | detected, generated markets | at k=1 | k=4 | k=12 | k=48 |
|---|---|---|---|---|---|
| 0.00 (the zero cell) | **0.042** | 0.00 | 0.08 | 0.08 | 0.00 |
| 0.02 | 0.083 | 0.25 | 0.00 | 0.00 | 0.08 |
| 0.05 | 0.312 | 0.58 | 0.33 | 0.17 | 0.17 |
| 0.10 | 0.542 | 0.92 | 0.67 | 0.25 | 0.33 |
| 0.20 | 0.792 | 1.00 | 1.00 | 0.75 | 0.42 |

**The zero cell passes at 0.042 against a claimed 0.05**, which is what makes the rest of the
column readable.

**Where the test goes blind:** below 0.05 of a forecast unit at any horizon, and below 0.10 at 48
bars. A round trip on this panel costs **0.16 to 0.28**, and a drift of 0.20 is seen on 79% of
generated cells and on 100% of them at one and four bars. **So an effect large enough to pay would
have been seen**, on instruments with 5,200-5,900 events; the traded markets carry two to three
times that and see more.

The same table read on the traded markets is **not** a power curve and must not be quoted as one:
its baseline is 0.562, because those symbols already carry the real reading of Result 3 and the
plant is added on top of it. That is why power is reported only where the baseline is null.

## Bugs and measurement defects this run caught

1. **The per-bar `spread` column is not a cost.** It is zero on 7-35% of bars and its median runs
   three to eight times below the terminal's quote - 1 point against 9 on EURUSD, 2 against 7 on
   AUDUSD, 2,424 against 18,424 on BTCUSD. Costed from the column, a round trip on EURUSD is 0.033
   forecast units; costed from the quote it is 0.276. **Every direction cell in this study is
   profitable at the first number and almost none at the second**, so the whole verdict turns on
   it. Both are now computed and printed, and every statement here uses the quote. This is a
   different defect from the one already on file - that the column is in points and not price -
   and it bites in the same direction.
2. **The bar puller would have died on the first row.** The bridge sends ISO strings
   (`{"time": "2026-11-05T15:15:00"}`), with no timezone, and the puller it replaced did
   `int(row["time"])`. `tests/test_mt5_live.py` records the identical defect against the same
   route. Now parsed as UTC, with the check that a bar lands inside the window that asked for it.
3. **`rates/pos` caps the sample at a fifth of what exists.** The route counts back with
   `num_bars` and this deployment answers 50,000 and refuses 100,000 - about two years at 15
   minutes. `rates/range` pages and reaches 2015: **294,499 bars instead of 46,000**, which is the
   difference between a trigger 4.0 cell with 5,700 events and one with 900.
4. **A helper that coerced every payload to a list silently emptied the symbol-info call.**
   `rates/*` answer with a list and `symbols/info/*` with a dict, and `return got if
   isinstance(got, list) else []` turned every one of twelve into `[]` with no error. Found because
   the `point` table came back `{}`, which would have made every cost `nan`.
5. **A trailing `?` with no query is a 404 on this bridge.** `/symbols/info/EURUSD` answers;
   `/symbols/info/EURUSD?` does not.
6. **The placebo carries a residual with a known direction.** Selecting on `abs(r) / vol` tilts
   towards a small denominator, so an impulse sits at the low end of whatever bin it is matched in
   and its forward volatility reads high for that reason alone. On generated i.i.d. returns it was
   +0.01 to +0.03 at ten bins. Twenty bins shrink it and do not remove it, so the i.i.d.-shuffled
   twin is reported beside every reading as the floor.
7. **A planted-drift sweep scored on a series that already has an effect is not a power curve.**
   Scored against the real arm's own surrogate, the traded markets detect a 0.02 plant on 51% of
   cells - because their baseline is already 0.562. Power is reported on the synthetics alone,
   where the zero cell is 0.042.
8. **The harness used to write zero cells and exit 0.** It now raises, counts bars, bars with a
   state and events per trigger for every instrument before any cell is read, and was reproduced
   twice in one process (420 rows, identical) before the run.

## What this does not close

* **The mechanism of the AUDUSD and USDCAD reversion is unmeasured.** The feed is bid bars only and
  no tick or ask history was pulled, so bid-ask bounce cannot be separated from a genuine
  conditional reversion. Both halves agree and the effect is broad across hours, which is unlike a
  pure one-bar bounce; it also fails to clear the spread, which is what a bounce would do.
* **This is a conditional mean, not a trade.** There is no stop, no target and no fill model, so
  the `P(>= N R)` against `1/(1+N)` that this desk leads with is not computed. The cost comparison
  here is the weaker one of a mean against a round trip, and a stop would only make it worse: cost
  in R is set by the stop, and a 15-minute stop pays the same spread as a daily one.
* **The two generated families cover clustering and the tail, not the auction.** Nothing here
  controls for the absence of a dealer, a rollover or a session - that is what the `deseason` and
  `masked` arms do instead, and they are arms of the real series rather than independent markets.
* **The synthetics are 5.7-7.8 years against the traded panel's 7.4-11.8.** The comparison of
  rates across kinds carries that difference.
* **Nothing here was traded.** No gate is proposed and none should be: the reading that survives
  every control is the one this desk already has.
