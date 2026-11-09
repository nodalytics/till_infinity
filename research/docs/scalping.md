# Scalping at 1 to 15 minutes: what can and cannot pay on this venue

Measured 2026-11-08 by [`scalps.py`](../harness/scalps.py),
[`scalp_cost.py`](../harness/scalp_cost.py) and
[`scalp_orb.py`](../harness/scalp_orb.py), with the data pulled by
[`scalp_pull.py`](../harness/scalp_pull.py) and the arithmetic pinned by
[`tests/test_scalps.py`](../../tests/test_scalps.py).

Four strategy families were asked for: price action / momentum, mean reversion,
breakout, and order flow / tape reading. Execution on M1/M3/M5 with M15 as
context, a 1xATR stop and a 2xATR target, hard stop every trade, a daily loss
limit and a cap on trades per session.

## The verdict

| | |
|---|---|
| **order flow, tape reading, DOM absorption** | **cannot be built.** `ticks_bookdepth` is **0** on every symbol asked and `real_volume` is **0 on 80,000 of 80,000** M1 bars. Not attempted |
| **VWAP, and the volume-surge breakout confirmation** | **cannot be built.** `tick_volume` is a quote-update count, not size: on Step Index it reads median 60, min 17, **max 62** a minute - a one-per-second publication clock. Dropped, with nothing substituted |
| **FX at 1 to 15 minutes** | **arithmetically dead before any signal.** A round trip costs **0.865R on EURUSD and 0.986R on GBPUSD at a 1-minute 1xATR stop**, and no FX pair clears the desk's 0.16R ceiling at that geometry on *any* clock from 1m to 15m. 42 of 249 (instrument, clock) cells refused unmeasured |
| **price action / momentum** | **null after cost on 8 of 8 live (family, clock) cells.** Gross is positive and clear of zero at 1m/3m/5m (+0.013 to +0.019R) and a coin on the same bars earns the same gross; net is -0.038 to -0.092R |
| **mean reversion** | **null after cost on 8 of 8.** The best gross in the study, `bb_reversion` at 3m, **+0.0300R [+0.0128, +0.0472]** - against a cost of 0.096R. Targeting the middle band instead of 2 ATR changes the geometry, not the answer |
| **breakout** | **null after cost on 8 of 8, and the opening-range form is worse than entering at random.** `orb` at 1m reads -0.2262R against -0.0831R for a random entry time |
| **the opening range on the US indices** | **the one candidate, and it died on the anchor.** +0.0877R over 375 trades at 15m became **-0.0947R [-0.1941, +0.0027] over 878** once the opening was moved from the CFD reopen to **09:30 New York**, and the index arm is indistinguishable from the same rule on markets with no opening at all (**-0.0487R [-0.1553, +0.0589], p 0.448**) |
| **the M15 context filter** | **does not earn its place.** Against the filter removed it is better in 8 of 24 pooled cells; against the filter inverted, 10 of 24; against a random filter keeping the same share, 8 of 24. One nominal pass and one nominal failure on each comparison, **Benjamini-Hochberg keeps nothing**, median effect **-0.0033R** |
| **the daily loss limit and the trade cap** | **duty-cycle rules with no edge in them.** The loss limit improves the *total* in 113 of 176 cells and beats its own same-rate random twin in **0 of 176**; the cap improves the total in 114 of 176 and beats its twin in **6 of 176** at a median twin-beat rate of 0.760 |
| **the 1:2 geometry** | **exactly fair, which is the problem.** P(>=2R) is **0.294 to 0.342, median 0.336**, where a driftless walk answers 0.3333 and break-even `(1+cost)/3` needs **0.348 to 0.371** |

**0 of 24 pooled (family, clock) cells is net positive**; 21 of 24 have a 90%
day-block interval entirely below zero. Of 207 per-instrument cells, 24 are
positive, **none survives BH**, and 76 survive as losers.

## What the feed does not have, measured rather than assumed

[positioning.md](positioning.md) records that this broker "gives a spread and
nothing behind it - no order book, no depth, no resting size". Two readings
confirm it from the terminal rather than from the note:

* `symbols/info` returns `ticks_bookdepth: 0` on every symbol asked, so there is
  no DOM at any depth. **Absorption cannot be observed**, and neither can
  Time & Sales size or speed, because the adapter publishes a `QuoteTick` with
  a placeholder size and never a `TradeTick`.
* `real_volume` is **0 on all 20,000 M1 bars** of each of US Tech 100, EURUSD,
  Step Index and Volatility 75 Index. `tick_volume` is non-zero but it is a
  **count of quote updates**: Step Index reads median 60, min 17, max 62 a
  minute and Volatility 75 median 30, max 31, which is the venue's publication
  rate and not activity. A volume surge on a synthetic is therefore impossible
  by construction, and a VWAP weighted by a tick count is a *time*-weighted
  average price wearing a volume-weighted one's name.

That last argument is already in the code:
[`node/desks.py`](../../till_infinity/node/desks.py) refuses `VOLUME` and
`VALUE` bars because "an MT5 tick's trade fields read 0 or a constant 5000, so
there is no size to aggregate". The same reasoning retires VWAP and the
volume-surge confirmation here. **Nothing was substituted for them**: the
reversion target is the middle Bollinger band and the breakout confirmation is
a hold beyond the level.

## The cost screen, and the cells it kills

Cost in R is `round_trip / stop` and is set by the **stop, not the target**, so
the brief's 1xATR stop with a 2xATR target is the most expensive geometry
available. ATR(14) is read off bars aggregated from M1 rather than scaled from
a 1-minute ATR by `sqrt(k)`, because volatility clusters and sqrt-scaling would
make short clocks look dearer than they are - the direction that would flatter
this screen's conclusion.

Round trip from the terminal's own bid/ask through the single
[`venue.quoted`](../harness/venue.py). The desk's ceiling is **0.16 of the
risk**, `Settings.max_spread_vol`.

**The FX rows below are Friday-close quotes.** Read the weekend-quote defect at
the end of this document before reordering the book on them.

### Dead at a 1xATR stop: every FX pair, on every clock measured

| instrument | clock | ATR(14) | round trip | cost/R | |
|---|---:|---:|---:|---:|---|
| EURUSD | 1m | 0.00012714 | 0.00011 | **0.865** | the whole stop |
| GBPUSD | 1m | 0.00015214 | 0.00015 | **0.986** | more than the whole stop |
| USDCAD | 1m | 0.00012357 | 0.00010 | 0.809 | |
| AUDUSD | 1m | 0.00009714 | 0.00007 | 0.721 | |
| USDCHF | 1m | 0.00012000 | 0.00006 | 0.500 | |
| USDJPY | 1m | 0.02043 | 0.009 | 0.441 | |
| XAUUSD | 1m | 1.6814 | 0.59 | 0.351 | |
| ETHUSD | 1m | 1.4366 | 1.58 | 1.100 | |
| BTCUSD | 1m | 34.108 | 18.424 | 0.540 | |
| EURUSD | 5m | 0.00030643 | 0.00011 | 0.359 | still 2.2x the ceiling |
| EURUSD | 15m | 0.00055393 | 0.00011 | 0.199 | still above it |
| GBPUSD | 15m | 0.00064464 | 0.00015 | 0.233 | |

At a 2xATR stop EURUSD reaches 0.099 at 15 minutes and AUDUSD 0.082, which is
affordable and is **not the geometry the brief asks for**; it is also a stop two
ATR wide, which is a different trade. On the whole book at 15 minutes, 36 of the
41 further instruments in `data/btc` and `data/seqlab` are dead at a 1xATR stop,
the worst being NZDCAD at **8.148** and GBPAUD at **2.622**.

### Live at a 1xATR stop

| clock | instruments inside 0.16R | cheapest |
|---|---|---|
| 1m | Step Index 0.088, US Tech 100 0.091, Jump 75 Index 0.125 | Step Index |
| 2m | the above plus Wall Street 30 0.113, Volatility 25 (1s) 0.118, Volatility 75 (1s) 0.126, Volatility 75 0.150, US SP 500 0.153 | US Tech 100 0.063 |
| 3m | the above plus Volatility 25 Index 0.137 | Step Index 0.049 |
| 5m | the above plus Volatility 100 (1s) 0.133, XAUUSD 0.149 | US Tech 100 0.039 |
| 15m | the above plus USDJPY 0.104, BTCUSD 0.105, USDCHF 0.113 | US Tech 100 **0.021** (1.0% of a 2xATR target), Step Index 0.021 (1.1%), Jump 75 0.027 (1.4%), Wall Street 30 0.037 (1.9%), US SP 500 0.051 (2.5%) |

The three cheapest instruments on the whole book at 15 minutes are US Tech 100,
Wall Street 30 and US SP 500, as the brief states, and the synthetics are the
only things cheap enough to execute on at 1 to 3 minutes.

## The rules, frozen

Context is the M15 EMA9-vs-EMA21 sign, read from the last M15 bar that had
**closed** before the execution bar opened. Execution clocks are built from M1
on wall-clock buckets, so no bucket spans a session gap.

| family | long condition |
|---|---|
| `ema_pullback` | EMA9 > EMA21, the bar's low touches EMA9, close back above EMA9 and above EMA21 |
| `candle_momentum` | body >= 1.0 ATR and body/range >= 0.60, up bar |
| `bb_reversion` | close below BB(20,2) lower, next close back inside, RSI(4) <= 25 at the excursion |
| `bb_to_mid` | the same entry targeting the middle band instead of 2 ATR |
| `orb` | first break of the session's opening 15 minutes with the next bar still closing beyond |
| `level_break` | close beyond the prior 20-bar extreme with the next bar still closing beyond |

Entry at the **next bar's open**, stop 1xATR(14) at the signal bar, target
2xATR, barriers on the wicks with the **stop winning a tie**, maximum hold 40
bars, one position at a time. Net R subtracts `round_trip / risk` per trade
with the risk that trade used. Day-block bootstrap, 2,000 draws, 90% intervals.

Data: 300,000 M1 bars for each of the three US indices (2026-01-05 to
2026-11-06) and each of seven synthetics (2026-04-14 to 2026-11-08), pulled for
this study; the existing 20,000-bar M1 store for FX, gold and crypto; and
50,000 15-minute bars an index (2024-08 to 2026-10) for the focused ORB run.

## The result: gross is a geometry effect and net is the spread

| family | clock | n | net R | 90% | gross R | 90% | cost | P(>=2R) | break-even |
|---|---:|---:|---:|---|---:|---|---:|---:|---:|
| `ema_pullback` | 1m | 46,251 | **-0.0920** | [-0.1033, -0.0814] | +0.0128 | [+0.0016, +0.0246] | 0.105 | 0.337 | 0.368 |
| `ema_pullback` | 3m | 54,996 | **-0.0772** | [-0.0883, -0.0661] | +0.0189 | [+0.0072, +0.0300] | 0.096 | 0.338 | 0.365 |
| `ema_pullback` | 5m | 41,602 | **-0.0649** | [-0.0775, -0.0527] | +0.0141 | [+0.0013, +0.0266] | 0.079 | 0.336 | 0.360 |
| `ema_pullback` | 15m | 17,554 | **-0.0378** | [-0.0564, -0.0186] | +0.0063 | [-0.0113, +0.0257] | 0.044 | 0.333 | 0.348 |
| `candle_momentum` | 1m | 41,958 | **-0.0853** | [-0.0966, -0.0737] | +0.0182 | [+0.0067, +0.0298] | 0.103 | 0.339 | 0.368 |
| `candle_momentum` | 3m | 40,597 | **-0.0871** | [-0.0992, -0.0755] | +0.0082 | [-0.0040, +0.0197] | 0.095 | 0.335 | 0.365 |
| `candle_momentum` | 5m | 26,631 | **-0.0666** | [-0.0817, -0.0504] | +0.0112 | [-0.0048, +0.0276] | 0.078 | 0.336 | 0.359 |
| `candle_momentum` | 15m | 8,541 | **-0.0488** | [-0.0768, -0.0220] | -0.0055 | [-0.0339, +0.0207] | 0.043 | 0.330 | 0.348 |
| `bb_reversion` | 1m | 23,325 | **-0.0853** | [-0.1010, -0.0703] | +0.0191 | [+0.0033, +0.0344] | 0.104 | 0.339 | 0.368 |
| `bb_reversion` | 3m | 20,759 | **-0.0659** | [-0.0838, -0.0478] | **+0.0300** | [+0.0128, +0.0472] | 0.096 | 0.342 | 0.365 |
| `bb_reversion` | 5m | 11,836 | **-0.0731** | [-0.0941, -0.0514] | +0.0057 | [-0.0166, +0.0270] | 0.079 | 0.333 | 0.360 |
| `bb_reversion` | 15m | 493 | -0.0964 | [-0.2065, +0.0139] | -0.0525 | [-0.1638, +0.0588] | 0.044 | 0.314 | 0.348 |
| `bb_to_mid` | 1m | 23,205 | **-0.0891** | [-0.1054, -0.0734] | +0.0154 | [-0.0007, +0.0325] | 0.104 | 0.365 | 0.360 |
| `bb_to_mid` | 3m | 20,706 | **-0.0800** | [-0.0961, -0.0634] | +0.0159 | [-0.0004, +0.0323] | 0.096 | 0.386 | 0.381 |
| `bb_to_mid` | 5m | 11,830 | **-0.0761** | [-0.0969, -0.0556] | +0.0027 | [-0.0187, +0.0233] | 0.079 | 0.399 | 0.392 |
| `bb_to_mid` | 15m | 493 | **-0.1556** | [-0.2307, -0.0774] | -0.1116 | [-0.1859, -0.0326] | 0.044 | 0.469 | 0.514 |
| `orb` | 1m | 330 | **-0.2262** | [-0.3415, -0.1129] | -0.1124 | [-0.2236, +0.0054] | 0.114 | 0.294 | 0.371 |
| `orb` | 3m | 959 | **-0.1669** | [-0.2400, -0.0943] | -0.0645 | [-0.1389, +0.0133] | 0.102 | 0.310 | 0.367 |
| `orb` | 5m | 1,097 | **-0.1235** | [-0.1970, -0.0513] | -0.0422 | [-0.1154, +0.0338] | 0.081 | 0.317 | 0.360 |
| `orb` | 15m | 1,205 | -0.0108 | [-0.0894, +0.0652] | +0.0318 | [-0.0505, +0.1132] | 0.043 | 0.338 | 0.348 |
| `level_break` | 1m | 24,332 | **-0.1045** | [-0.1206, -0.0895] | -0.0000 | [-0.0154, +0.0150] | 0.104 | 0.333 | 0.368 |
| `level_break` | 3m | 27,324 | **-0.0869** | [-0.1041, -0.0702] | +0.0077 | [-0.0092, +0.0248] | 0.095 | 0.335 | 0.365 |
| `level_break` | 5m | 20,731 | **-0.0648** | [-0.0828, -0.0475] | +0.0132 | [-0.0047, +0.0307] | 0.078 | 0.336 | 0.359 |
| `level_break` | 15m | 9,848 | -0.0170 | [-0.0436, +0.0106] | +0.0265 | [-0.0005, +0.0537] | 0.044 | 0.340 | 0.348 |

For `bb_to_mid` the break-even column is `(1 + cost) / (1 + target_r)` with the
realised mean target of 2.07, 1.88, 1.75 and 1.03 R, not `(1 + cost) / 3`: the
middle band is a moving target and a P(hit) of 0.469 against a 1.03R reward is
*worse* odds than 0.333 against 2R, not better.

**Gross is clear of zero in 6 of 24 cells** and all six are at 1 to 5 minutes.
It is not direction. A coin on the same entry bars with the same geometry and
the same cost earns the same gross: `ema_pullback` at 3m reads a rule gross of
+0.0189 against a **coin gross of +0.0201**, at 1m +0.0128 against +0.0221, and
`candle_momentum` at 1m +0.0182 against +0.0154. The small positive gross is
the same effect [chart-patterns.md](chart-patterns.md) found on the measure
rule - a fixed distance is easier to reach because volatility clusters, which a
day-block twin reproduces - and it is available to a coin flip.

## The nulls, pooled over 24 cells

Each row is the rule minus one arm, day-block paired over the union of days.

| arm | rule better in | median | nominal p<0.05 | BH at 0.05 |
|---|---|---:|---|---|
| filter **removed** | 8 of 24 | -0.0037 | 2 (one for, one against) | keeps 0 |
| filter **inverted** | 10 of 24 | -0.0037 | 2 (one for, one against) | keeps 0 |
| filter **random, same share** | 8 of 24 | -0.0033 | 1, and it is against | keeps 0 |
| **coin** on the same bars | 12 of 24 | +0.0002 | 3 (one for, two against) | keeps 0 |
| **random entry times** | 8 of 24 | -0.0064 | 5 (three for, two against) | keeps 0 |
| **the signal 3 bars stale** | 9 of 24 | -0.0030 | 4 (one for, three against) | keeps 0 |

Twelve of twenty-four on the coin comparison with a median of +0.0002R is the
cleanest statement available: **the side these rules pick is worth nothing.**

### The M15 context filter, which is the brief's central claim

It gets its own arms because it is the claim: take only longs when M15 trends up
and only shorts when it trends down.

| family | clock | vs removed | vs inverted | vs random same-share |
|---|---:|---|---|---|
| `ema_pullback` | 1m | +0.0029 p 0.49 | +0.0062 p 0.52 | +0.0030 p 0.65 |
| `ema_pullback` | **3m** | **+0.0092 p 0.019** | **+0.0275 p 0.009** | +0.0089 p 0.07 |
| `ema_pullback` | 5m | +0.0053 p 0.25 | +0.0131 p 0.34 | +0.0035 p 0.51 |
| `ema_pullback` | 15m | -0.0043 p 0.21 | +0.0135 p 0.60 | -0.0057 p 0.11 |
| `bb_reversion` | 3m | +0.0143 p 0.07 | +0.0264 p 0.06 | +0.0099 p 0.37 |
| `level_break` | 1m | -0.0076 p 0.28 | -0.0157 p 0.27 | **-0.0185 p 0.038** |
| `bb_to_mid` | 15m | **-0.0993 p 0.044** | **-0.1043 p 0.030** | -0.1154 p 0.11 |
| the other 17 cells | | all p >= 0.12 | all p >= 0.18 | all p >= 0.09 |

**The filter does not earn its place.** The one place all three comparisons
agree in sign and two of them clear zero is `ema_pullback` at 3 minutes, and the
same filter on the same family reads nothing at 1m, 5m and 15m - a mechanism
that works on one clock of four and not its neighbours is not yet a mechanism.
Even taken at face value, the largest effect the filter buys anywhere is
**+0.0275R against a cost of 0.096R**: it covers 29% of the spread it would have
to beat. BH over the 24 comparisons keeps nothing on any of the three arms.

Reported as a gating condition rather than a rejection, per the operator's
standing instruction that findings may be regime-specific: *if* someone wants to
keep the M15 filter, the only cell with evidence for it is a momentum pullback
on a 3-minute clock, and it is not enough evidence to pay a spread with.

## The 1:2 geometry is a claim, and it is exactly fair

On a driftless walk P(+2R before -1R) is exactly 1/3. Over the 20 pooled cells
with a true 1:2 geometry, P(>=2R) runs **0.294 to 0.342 with a median of
0.336** - on the walk's answer, to about half a percentage point. Break-even is
`(1 + cost)/3`, which here is **0.348 to 0.371**. Every cell is 1 to 8
percentage points short of break-even and all of that shortfall is the spread.

This is also why "move the target further out" is not a fix. Cost in R is set by
the stop; the target only reshapes a distribution whose mean is already zero.

## The risk rules are duty-cycle rules

| rule | cells | keeps | total better than base | per-trade better | beats its same-rate random twin |
|---|---:|---:|---|---|---|
| daily loss limit at -3R | 176 | 0.75 | 113 of 176 | 61 of 176 | **0 of 176**, twin-beat rate median **1.000** |
| cap of 5 trades a day | 176 | 0.50 | 114 of 176 | 57 of 176 | **6 of 176**, twin-beat rate median 0.760 |

Both improve the book's total, both for the only reason available on a
net-negative book - they trade less - and neither beats a twin that drops the
same number of trades **within the same day**. The loss limit is *worse* than
random in essentially every cell: its twin beats it at a median rate of 1.000,
because stopping after a run of losses removes the trades that follow a loss,
and those are no worse than any others. This reproduces
[strategy-switching.md](strategy-switching.md) on a new rule family.

A hard stop on every trade is not tested here as a choice: every arm has one,
because a barrier race is how the whole study is scored.

## The opening range: the one candidate, and the anchor that killed it

The 207-cell sweep left exactly one thing worth a second look. At 15 minutes,
`orb` on the three US indices read **+0.0877R over 375 trades** where the same
rule on continuously-quoted synthetics - markets with no opening at all - read
**-0.0553R over 830**. Three of three instruments positive with the control
negative is the shape of a finding.

[`scalp_orb.py`](../harness/scalp_orb.py) re-ran it on the 50,000-bar 15-minute
store (550 sessions an instrument against the 230 the M1 pull reaches) and fixed
the anchor. **The opening the sweep found was the wrong one.** A US index CFD
here quotes about 23 hours with one daily break, so the session boundary in the
feed is the **CFD reopen** - a thin hour around 22:00-23:00 UTC with no auction
in it. A trader asking for an opening-range breakout on US indices means
**09:30 New York**, computed through `zoneinfo` so the daylight-saving shift is
right rather than approximated as a fixed UTC hour.

| anchor | kind | n | net R | 90% | gross R |
|---|---|---:|---:|---|---:|
| 09:30 New York | the three indices | 878 | **-0.0947** | [-0.1941, +0.0027] | -0.0364 |
| 09:30 New York | three synthetics (control) | 4,901 | -0.0460 | [-0.0788, -0.0127] | -0.0111 |
| the CFD reopen | the three indices | 963 | +0.0442 | [-0.0530, +0.1466] | +0.0888 |

At the real opening the indices read **-0.0947R**, which is *worse* than the
control, and the index-minus-control difference is **-0.0487R [-0.1553,
+0.0589], p 0.448**. At the CFD reopen the sign is positive and the interval
still contains zero, and the figure **shrank from +0.0877 on 375 trades to
+0.0442 on 963** as the sample grew - the shape this repository has recorded
before for a cell picked out of many. There is no control for the reopen arm,
because a synthetic has three gaps in seven years, so "is the CFD reopen
special?" is **unknown** rather than answered.

At 1m, 3m and 5m anchored at the cash open the indices read -0.0582, -0.0697
and -0.0268R over 646, 579 and 531 trades, all intervals containing zero, and
the index-minus-control differences are +0.1346 (p 0.120), -0.0272 (p 0.833) and
-0.0961 (p 0.325).

The ORB's other reading is worth keeping: at 1 and 3 minutes it is **worse than
entering at a random time** (-0.2806R, p 0.007 and -0.1624R, p 0.014) and worse
than taking its own signal three bars late (-0.1748R, p 0.048 at 1m). A fresh
opening-range break at a 1-minute clock is an actively bad moment to buy.

## Power: where this test goes blind

A drift of `strength` R per bar is planted in each trade's favour while it is
open, each window clipped to the next entry so no bar gets two plants, and the
same book is re-raced.

| planted drift | cells where the 90% interval clears zero | median shift in mean net R |
|---|---|---:|
| 0.01 R/bar | 4 of 123 | +0.0436 |
| 0.02 R/bar | 29 of 123 | +0.0876 |
| 0.05 R/bar | **119 of 123** | +0.2110 |
| 0.10 R/bar | 123 of 123 | +0.4116 |
| 0.20 R/bar | 123 of 123 | +0.7428 |

Over the 123 cells with at least 1,000 trades the test is **reliable at a shift
of about 0.21R a trade, finds about a quarter of a 0.09R shift, and is blind at
0.04R**. The cost it would have to beat is 0.04 to 0.11R, so the blind spot sits
just below the cost: an edge too small for this study to see is also too small
to pay for the spread - but an edge of exactly the size of the cost would be
found only about a quarter of the time, and that is the honest limit of the
null. The unplanted median is -0.0747R.

## Multiplicity and the split

207 per-instrument cells were measured. 24 are net positive where chance on a
zero-mean book would give about half; **none survives Benjamini-Hochberg** and
76 survive as losers. The best positive cell is Wall Street 30 `orb` at 15m,
+0.1460R over 114 trades, p 0.237 - and it is one of the cells
[`scalp_orb.py`](../harness/scalp_orb.py) then measured properly and found
negative.

Both halves of the sample agree in sign in **110 of 123** cells with at least
1,000 trades, so the negative result is not a regime.

## Defects this run found and fixed

Reported because a study that quietly drops its own off-by-one is worth less
than one that says so.

* **A look-ahead in the context filter.** The first version read the M15 trend
  with `searchsorted(m15_open, t) - 1`, which at 10:03 returns the bar that
  opened at 10:00 and closes at **10:15** - twelve minutes of the future handed
  to the filter, on the study's central claim. Searching the M15 bars' *ends*
  fixes it, and `test_scalps.py` pins it.
* **The opening-range anchor was a day out.** `datetime.fromtimestamp(stamp *
  86400, UTC).astimezone(NY).date()` names the **previous** New York day,
  because midnight UTC is 19:00 or 20:00 in New York. Every bar took an anchor
  seventeen hours old, the range was never inside its own window, and the rule
  fired **zero** times on all six instruments - printing as "too few signals"
  rather than as an error, which is how it survived a whole run.
* **A paired bootstrap that could not see the filter's effect.** Comparing two
  arms over the *intersection* of their days reads `+0.0000 [+0.0000, +0.0000]`
  when each arm takes about one trade a day, because on a shared day both arms
  hold the same trade. A filter whose whole effect is skipping days cannot be
  measured on the days it did not skip. Taken over the union now.
* **A two-sided p of 0.000 for two identical arms.** `mean(boots <= 0)` is 1.0
  when every draw is exactly zero, and `2 * min(below, 1 - below)` turns that
  into the most significant result available. Ties count as half.
* **A plant that could not land.** The power ramp first delivered `strength` R
  spread over the 40-bar hold window, so a trade resolving in three bars got a
  fourteenth of it and every strength read as blind - the harness's own geometry
  reported as a power limit. A drift is a rate, so the plant is now R **per
  bar**.
* **`RelativeStrengthIndex(4)` is not Wilder's RSI(4).** Nautilus defaults to an
  ordinary exponential average and reads **32.1 where Wilder reads 47.4** on the
  same 600 bars. Both are called RSI(4); a rule thresholded at 25 fires at a
  different rate under each. `ma_type` has to be said out loud.
* **A sixth copy of `quoted()`, nearly written.** On `main` the only copies of
  it are in `clockfloor.py` and `fivevsfifteen.py`, both building
  `f"{BASE}/symbols/info/{symbol}"` with no percent-encoding - and every
  instrument this desk can afford to scalp fast has a space in its name, so an
  unencoded space returns a 404 that a bare `except` turns into `nan`. These
  harnesses take [`venue.py`](../harness/venue.py) instead, which is
  byte-identical to the file on `research/unused-rules` (a2a0f2d1) where the
  same defect was found across five harnesses. **This study depends on that
  file**; nothing here forks it, and `point_size` and `recorded` live in
  [`scalp_cost.py`](../harness/scalp_cost.py), which is their only consumer.
* **A weekend quote is not a trading spread.** The cost screen first ran while
  the terminal still held Friday's last FX quote (EURUSD **11 points**) and
  re-ran after it had updated to a closed-market quote (**81 points**, and
  USDCHF went from 6 to 203). The synthetics quote continuously and the index
  CFDs did not move, so only FX is affected and FX is dead under either number
  - but the ordering of the book is not stable across that change, and **the
  screen must be re-run on a weekday** before anything is built on it. The
  FX rows in the dead-cell table above are the Friday-close quotes, which are
  the tighter and therefore the more generous of the two.

## What is unknown

* **Whether a 2xATR stop pays.** Everything here is the brief's 1xATR stop. At
  2xATR, EURUSD at 15m costs 0.099R and the whole FX book comes back into
  scope - a different trade, not measured.
* **Whether the CFD reopen is special.** The reopen arm is the only positive
  pooled ORB reading and it has no control, because a continuously-quoted
  synthetic has no reopen to borrow.
* **Whether a maker entry changes the arithmetic.** Every cost here is a taker
  round trip. The desk's own maker fee is unmeasured and
  [limitfills.md](limitfills.md) found parking has no edge at 15 minutes;
  nothing was run at 1 to 5.
* **Whether order flow would have helped.** It is not measurable on this feed at
  all. The question is open and this venue cannot answer it.
* **FX cost on a weekday**, per the defect above.
* **Whether a per-cell coin twin is adequate below ~1,000 trades.** One coin
  draw on a 281-trade cell moves between -0.173 and -0.099R across four seeds,
  which is the size of the effects being chased. The pooled comparisons are over
  tens of thousands of trades and are unaffected; the small per-instrument cells
  would need the 200-draw form.

## Re-running it

```sh
./.secrets/lab.sh run research/harness/scalp_pull.py     # 300,000 M1 bars a symbol
./.secrets/lab.sh run research/harness/scalp_cost.py     # the screen; run it on a weekday
./.secrets/lab.sh run research/harness/scalps.py         # 207 cells, about seven minutes
./.secrets/lab.sh run research/harness/scalp_orb.py      # the focused opening-range run
uv run pytest tests/test_scalps.py -q
```

`CLOCKS`, `FAMILIES` and `SYMBOLS` narrow the sweep; a symbol with a space in
its name cannot be passed through `lab.sh run`, which splits its environment
arguments on whitespace.
