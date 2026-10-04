# Liquidity sweeps, protected highs and lows and broken zones: identified exactly, and predicting nothing

**Measured, 2026-10-04. Every sweep form is found exactly, occurs on Deriv at the rate our own walks
produce it, and predicts nothing - on Deriv or in any of six real asset classes.** On the Deriv diffusive
indices the rate of every pattern is 0.94-1.02x a matched iid walk's. Real markets do show more wick
sweeps than Gaussian walks (1.14-1.21x), but fewer than their own bars shuffled (0.88-0.98x): the excess
is fat-tailed bars, not anyone running stops. The frozen primary - sweep + displacement (SWEEP_SHIFT)
traded on the Deriv diffusive indices, 15m to 1d pooled - **fails at -0.021R [-0.030, -0.012]** over 65,104
trades. Not one of 2,629 pattern x symbol x timeframe cells (675 Deriv, 1,954 real) survives
Benjamini-Hochberg, and every pooled pattern in every class loses money. After every pattern, price goes
1 ATR the trade's way first 49-52% of the time - a coin. Protected (strong) lows hold until the next break
of structure 61% of the time, sweep-strong ones 65%, weak ones 60% - and walks give the same numbers.
Boom and Crash spikes are memoryless (next-minute AUC 0.49-0.50). The two things that beat their walks are
Drift Switch's drift regimes (a generator property) and a sweep-prediction gain of +0.0006 AUC.

Script: [`ideas/sweeps.py`](../ideas/sweeps.py) (`MODE=run|report|plot`). Rule, frozen and committed
before any real-data run and amended once before it (the desk's asset classes, below):
[`ideas/sweep_rule.json`](../ideas/sweep_rule.json). Entities: [`mcfl/sweeps.py`](../mcfl/sweeps.py),
specified in [mcfl.md](mcfl.md#sweeps-failed-breaks-sweep-and-shift-inducement-broken-structures-protected-levels).
This follows [stophunt.md](stophunt.md) (a sweep entry on production's zones: no better than the
touch, and walks show the same stop-then-right rate), [turning-points.md](turning-points.md) (BREACH_REVERT
and DISPLACE_C at turns; real levels break slightly less often than walk levels),
[bos-predict.md](bos-predict.md) (the side of the next break is geometry) and
[origin-zones.md](origin-zones.md) (the look-ahead lessons).

## Why Deriv, and what to expect

Deriv's synthetics are exactly their published generators ([generators.md](generators.md),
[deriving.md](deriving.md)): the Volatility indices are iid Brownian, Step is a fair coin, Boom and
Crash spike at a stated, memoryless rate, Jump indices jump, Range Break has a real range. There is
no counterparty running stops, so a "stop hunt" on Deriv can only be what a random path draws. On a
martingale every stop and target rule earns minus its costs. The honest expectation, written into the
rule before the run, was that every sweep pattern occurs on Deriv at the rate our own walks produce
it and predicts nothing; the value of the study is an exact taxonomy (MCFL entities a parser can
find), the base rates, and the proof either way, with real markets in six asset classes as the
positive control. Deriv is a market here, never a control: the nulls are walks we generate.

## The taxonomy, exactly

Every pattern is written for the up side (a low swept, an up zone) and run on the chart and on the
chart flipped. Every one is an MCFL entity with a `known_at`, under the truncation and flip tests.

| # | pattern | MCFL | definition | traded |
|---|---|---|---|---|
| 1 | wick sweep, swing failure (SFP) | BREACH_REVERT | the first bar after a 3/3 swing low is known (3 bars after it) that trades under it and closes at or above it, before any close under it | long at the next open |
| 2 | close-beyond failure ("turtle soup") | CLOSE_REVERT (new) | the swing's first close under it, and a close back at or above it within 3 bars | long |
| 3 | equal highs / lows swept | POOL_TAKEN[SWEPT] | two or more standing swing lows within 0.1 ATR (a pool); the first bar under the pool's level, closing back | long |
| 4 | candle-range sweep (CRT) | PURGE | the bar trades under the previous bar's low and closes back inside its range | long |
| 5a | session raid | SESSION_EXTREME_TAKEN[ASIA, closed back] | the Asian session's (22:00-07:00 UTC) low taken before the next Asian session, the bar closing back above it; 15m and 1h | long |
| 5b | Judas swing | SESSION_FIRST_MOVE[LONDON] | the London session's first swing; faded (a first swing high is sold); 15m and 1h | against the first move |
| 6 | sweep + displacement | SWEEP_SHIFT (new) | a BREACH_REVERT or CLOSE_REVERT of a low and, on its bar or within 3 bars, a DISPLACE_C or DELIVERY_SHIFT (CISD) up; the first per sweep | long |
| 7 | inducement | INDUCEMENT (new) | at an MCFL ZONE's first revisit, a swing above the zone taken within the 10 bars before | a limit at the zone's near edge, against every first revisit |
| 8a | breaker / inverse-FVG retest | BREAKER_RETEST (new) | a ZONE broken by a close beyond its far edge (FAIL), or a FVG by VOID_INVERTED; its first return to the far edge within 100 bars, closing on the broken side | against the old structure |
| 8b | failed break | RECLAIM (new) | the same first return, closing back inside | with the old structure |
| 9 | protected highs and lows | PROTECTED (new) | below | not traded; held or lost |
| 10 | Boom / Crash spikes, Jump jumps | (one-minute bars) | a bar whose close - open is beyond 8 robust sigmas | not traded; rate, clustering, predictability |

**Protected highs and lows.** After a break of structure the trader calls the swing low that started
the breaking leg *protected* (or *strong*): price left it and broke the prior high, so a trade below it
says the up structure has failed. A swing low whose leg did not break anything is *weak*: it is
expected to be taken. The strongest is a low that first swept the previous low, then displaced and broke
structure. In MCFL, for the leg away from every swing low p:

- **STRONG**: the leg's close went above the last swing high known at p (the BREAK; the BOS when it is
  WITH the structure) without trading under p;
- **SWEEP_STRONG**: STRONG, and the low at p swept the previous swing low (SWEEP_PROTECTED, the DAX
  course's protected low) and the leg displaced 2 ATR at or before the break;
- **WEAK**: the leg ran 20 bars without breaking and without trading under p.

Each is known when graded (STRONG at its break, WEAK at the leg's end). It **held** if the next break
of structure the same way became known before any low traded under the level, and was **lost** if
PROTECTED_TAKEN came first.

## Method (frozen in `sweep_rule.json`)

- **Data.** The broker's bars (`mt5bt.db`) on 15m, 1h, 4h and 1d, each series cut to its last 100,000
  bars. Deriv: the 15 synthetics in the database, in three classes - **diffusive** (Volatility 10/25/50/75/100,
  Step, Step 200, Step 500, Drift Switch 10/20/30), **jumpy** (Boom 1000, Crash 1000, Jump 50) and **Range
  Break 100** on its own. Real markets, each class a full secondary result (amended before the run at the
  desk's request): **FX** (12 pairs), **metals** (XAU, XAG, XPT, XPD), **indices** (7), **energy** (US Oil,
  UK Brent), **crypto CFDs** (BTC, ETH, SOL, XRP, LTC, BNB) and **Binance USDT perpetuals** (12 coins).
  948 series x source jobs.
- **Nulls, per series.** An iid Gaussian walk and a GARCH(1,1) walk with the series' close-to-close sd
  (256 sub-steps a bar, the real timestamps), and an **iid bar bootstrap** (the series' own bars, relative
  to their open, drawn with replacement and chained) - the exact null for a memoryless generator, jumps
  included. Volatility indices also get a walk at the **published** sigma. Walks pay the real series'
  cost in ATR at the same bar.
- **(a) Base rates**: events per 1,000 bars, both directions.
- **(b) Prediction** (mirrors [bos-predict.md](bos-predict.md)): at sampled bars, the nearest standing
  swing low below the close (known, never traded under); targets: swept within 10 bars (traded under on a
  bar that closes back - its BREACH_REVERT), taken at all, and swept given taken. Geometry G0 (distance in
  ATR, its log and square, timeframe) against G0 + G1 (pool size, swing age, wick history, volatility
  state, recent takes, 20-bar drift). Logistic regression per class and source; trained before each
  series' time midpoint, scored after; AUC gain with a 1,000-draw day bootstrap.
- **(c) After the pattern.** Gross: P(1 or 2 ATR the trade's way before as much against). The trade: entry
  at the next open (E; a limit back at the swept level, L, secondary), stop beyond the sweep's wick (the
  extreme low from the sweep bar to the signal bar) minus 0.1 ATR, trades under 0.2 ATR of risk skipped;
  exits a 2-ATR trail (E1, primary) and a fixed 2R (X2), at most 10 days; the broker's spread floor
  (Binance 0.07%), 0.05 ATR of slippage on every stop. **Jumpy indices** (Boom, Crash, Jump, Range Break)
  are judged on E1w: a stop on the jump side (Boom's shorts, Crash's longs, both on Jump and Range Break)
  fills at the stopped bar's extreme, since a bar fill misses the jump ([deriving.md](deriving.md)
  measured +13.96R of spike-side slippage at a 5-spread stop on boom_500).
- **Pass rule (any cell).** R > 0 with its 90% day-bootstrap interval above 0, positive in both halves,
  above the same cell on the iid and GARCH walks, and significant after Benjamini-Hochberg at q = 0.10
  (within the 675 Deriv cells, the frozen family, and separately within the 1,954 real-class cells).
- **Primary.** SWEEP_SHIFT, E then E1, Deriv diffusive, 15m-1d pooled.
- **Spikes** (pattern 10). research.db's 60 days of one-minute bars of Boom/Crash 300/500/1000 and Jump
  10-100: a spike is a bar whose close - open is beyond 8 robust sigmas.

All MCFL inputs are read at their `known_at`; entry is always after it (the next open, or a limit that
fills later). P7's limit fills on the revisit bar, where the inducement's take has already happened (the
inducement swing lies between price and the zone).

## (a) Base rates: Deriv draws sweeps at a walk's rate; real markets at their own bars' rate

Events per 1,000 bars on the real series divided by the same on its iid walk (mean over symbols and the
four timeframes; `base_rates_pivot.csv`, per timeframe in `base_rates_by_tf.csv`):

| pattern | Deriv diffusive | jumpy | Range Break | FX | metals | indices | energy | crypto CFD | Binance |
|---|---|---|---|---|---|---|---|---|---|
| P1 wick sweep (SFP) | **0.98** | 0.88 | 0.55 | 1.14 | 1.19 | 1.14 | 1.16 | 1.16 | 1.21 |
| P2 close-beyond failure | 0.97 | 0.98 | 0.78 | 0.98 | 0.98 | 0.96 | 0.99 | 0.96 | 1.00 |
| P3 pool swept | 0.98 | 0.84 | 0.44 | 1.11 | 1.06 | 1.13 | 1.17 | 1.02 | 1.07 |
| P4 candle-range sweep | 1.00 | 0.87 | 0.53 | 0.97 | 0.99 | 0.95 | 0.95 | 0.98 | 1.01 |
| P5 Asian-range raid | 0.97 | 0.86 | 0.40 | 1.17 | 1.23 | 1.25 | 1.31 | 1.11 | 1.13 |
| P5 Judas (London first swing) | 1.01 | 1.02 | 1.04 | 1.05 | 1.00 | 1.04 | 1.11 | 1.04 | 1.04 |
| P6 sweep + shift | **0.98** | 0.97 | 0.78 | 1.01 | 1.04 | 1.02 | 1.04 | 0.95 | 0.95 |
| P7 inducement | 0.95 | 1.02 | 0.86 | 0.83 | 0.80 | 0.82 | 0.87 | 0.80 | 0.83 |
| P8 breaker (zone) | 0.94 | 0.98 | 0.56 | 0.84 | 0.81 | 0.80 | 1.12 | 0.77 | 0.80 |
| P8 failed break (zone) | 0.99 | 1.14 | 0.96 | 0.71 | 0.66 | 0.77 | 0.71 | 0.66 | 0.68 |
| P9 strong low | 0.99 | 1.03 | 0.85 | 0.97 | 0.96 | 0.99 | 0.96 | 0.90 | 0.92 |
| P9 sweep-strong low | 0.99 | 0.94 | 1.07 | 1.25 | 1.23 | 1.19 | 1.42 | 1.17 | 1.13 |
| P9 weak low | 1.02 | 0.97 | 1.13 | 1.29 | 1.36 | 1.25 | 1.42 | 1.70 | 1.55 |

Raw rates on Deriv diffusive: 81 SFPs, 87 close-beyond failures, 9.3 pool sweeps, 402 candle-range sweeps,
47.5 sweep + shifts, 72 strong, 8.8 sweep-strong and 17.6 weak lows per 1,000 bars.

- **Deriv diffusive equals its walk** on every pattern (0.94-1.02), and its published-sigma walk too
  (0.99 on the SFP). Sessions mean nothing on a 24/7 generator, and the Asian raid and the Judas swing occur
  at the walk's rate (0.97, 1.01): the session names are clock labels.
- **Real markets sweep more than Gaussian walks** - SFPs 1.14-1.21x, pool sweeps up to 1.17x, Asian raids
  1.11-1.31x, sweep-strong lows 1.13-1.42x - **but not more than their own bars shuffled**: against the iid
  bar bootstrap the SFP ratio is 0.88-0.98 in every real class. A sweep is a long wick, real bars have fat
  tails, and the bootstrap, which keeps the bars and removes everything between them, makes as many or
  more. Nothing in the order of real bars adds sweeps. Real markets make fewer zones, voids and failed
  breaks than walks (0.66-0.89), the volatility clustering a walk lacks.
- **Jumpy and Range Break** differ from Gaussian walks by construction (jumpy SFPs 0.88x, Range Break
  0.40-0.78x on most patterns: its real range makes swings that are rarely traded through and closed back)
  and are close to their own bar bootstrap (jumpy 0.97-1.06 on the sweeps).

## (b) Prediction: geometry, plus nothing usable

Held-out AUC of P(the nearest standing swing low is swept within 10 bars), geometry alone (G0) and the
gain from the causal features (G1), real against both walks (`predict.csv`):

| class | base rate | AUC G0 | gain, real [90%] | iid walk | GARCH walk |
|---|---|---|---|---|---|
| **Deriv diffusive (primary)** | 0.165 | 0.751 | **+0.0006 [+0.0004, +0.0008]** | +0.0005 | +0.0002 |
| Deriv jumpy | 0.142 | 0.751 | +0.0004 [-0.0001, +0.0010] | +0.0002 | -0.0000 |
| Range Break | 0.081 | 0.753 | -0.0033 [-0.0055, -0.0010] | +0.0003 | -0.0010 |
| FX | 0.178 | 0.743 | +0.0014 [+0.0010, +0.0019] | +0.0004 | +0.0002 |
| metals | 0.177 | 0.745 | +0.0024 [+0.0013, +0.0036] | +0.0002 | -0.0001 |
| indices | 0.177 | 0.741 | +0.0037 [+0.0028, +0.0048] | +0.0006 | -0.0006 |
| energy | 0.170 | 0.741 | +0.0004 [-0.0029, +0.0038] | -0.0000 | +0.0000 |
| crypto CFDs | 0.171 | 0.734 | +0.0010 [+0.0003, +0.0017] | +0.0003 | +0.0001 |
| Binance | 0.173 | 0.739 | +0.0018 [+0.0014, +0.0022] | +0.0007 | +0.0002 |

Whether a sweep comes is 0.75 AUC from distance alone, the same on walks (0.751) - arithmetic. Given the
level is taken, whether the take closes back (a sweep) or through (a break) is a coin from geometry
(AUC 0.50-0.51 on every real class) and G1 adds +0.006 to +0.009 on FX, metals, crypto and Binance.

The Deriv diffusive cell **formally passes** the frozen bar (interval above 0, above both walks) at
+0.0006 AUC; so does sweep-given-taken (+0.0079 [+0.0046, +0.0107] against -0.0030 and 0.0000). As the
rule required, it was checked before believing it. Split by family (the same model refitted per family on the lab, each G1 feature dropped in turn): on the Volatility and
Step indices the gain is +0.0001 to +0.0003, the walks' size; **it is Drift Switch** (+0.0021 on the sweep,
+0.0154 on sweep-given-taken, almost all from the lower-wick share of the last ten bars). Drift Switch
switches between drift regimes; in an up-drift the bars carry lower wicks and lows that are taken close
back. That is the published generator, not a sweep mechanism, and it is far too small to trade
(+0.0006 AUC). No feature reads past its bar (every G1 input is known at t; labels start at t+1). Real
markets' +0.001 to +0.004 pass too and are of the size bos-predict found for its timing target: real
but useless.

## (c) After the sweep: a coin, and every trade loses

Mean R a trade, next-open entry, 2-ATR trail (E1; jumpy and Range Break E1w), pooled over symbols and
timeframes, real against its walks (`trades_pooled.csv`; per timeframe there too):

| pattern | Deriv diffusive real | iid | GARCH | boot | jumpy (E1w) | FX | metals | indices | energy | crypto CFD | Binance |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 SFP | -0.142 | -0.186 | -0.200 | -0.152 | -0.607 | -0.360 | -0.243 | -0.185 | -0.217 | -0.191 | -0.279 |
| P2 close-beyond failure | -0.050 | -0.087 | -0.100 | -0.094 | -0.262 | -0.199 | -0.146 | -0.111 | -0.124 | -0.069 | -0.139 |
| P3 pool swept | -0.140 | -0.175 | -0.215 | -0.113 | -0.616 | -0.367 | -0.316 | -0.163 | -0.246 | -0.201 | -0.279 |
| P4 candle-range sweep | -0.124 | -0.179 | -0.178 | -0.156 | -0.567 | -0.460 | -0.311 | -0.241 | -0.248 | -0.230 | -0.329 |
| P5 Asian raid | -0.136 | -0.139 | -0.187 | -0.146 | -0.505 | -0.319 | -0.260 | -0.118 | -0.201 | -0.156 | -0.236 |
| P5 Judas fade | -0.066 | -0.090 | -0.055 | -0.070 | -0.247 | -0.165 | -0.167 | -0.083 | -0.145 | -0.114 | -0.156 |
| **P6 sweep + shift** | **-0.021** | -0.059 | -0.058 | -0.057 | -0.163 | -0.155 | -0.125 | -0.077 | -0.111 | -0.053 | -0.095 |
| P7 zone, first revisit | -0.158 | -0.139 | -0.151 | -0.161 | -0.479 | -0.252 | -0.140 | -0.145 | -0.169 | -0.113 | -0.189 |
| P7 with inducement | -0.157 | -0.136 | -0.157 | -0.167 | -0.501 | -0.247 | -0.127 | -0.140 | -0.207 | -0.115 | -0.191 |
| P8 breaker (zone) | -0.096 | -0.158 | -0.116 | -0.134 | -0.581 | -0.376 | -0.325 | -0.184 | -0.189 | -0.123 | -0.288 |
| P8 inverse FVG | -0.109 | -0.180 | -0.151 | -0.153 | -0.498 | -0.438 | -0.294 | -0.184 | -0.301 | -0.208 | -0.314 |
| P8 failed break (zone) | -0.026 | -0.045 | -0.101 | -0.076 | -0.255 | -0.135 | -0.120 | -0.084 | -0.109 | -0.044 | -0.122 |
| P8 failed break (FVG) | -0.043 | -0.093 | -0.083 | -0.089 | -0.234 | -0.205 | -0.146 | -0.092 | -0.113 | -0.089 | -0.142 |

Every pooled pattern in every class loses. P(1 ATR the trade's way before 1 ATR against) is
**0.477-0.531** after every pattern in every class (0.49-0.52 outside Range Break and energy's raids; walks the same): a sweep says nothing about the next
move. The limit entry back at the swept level (L) is worse everywhere (P6 Deriv -0.174R), and inducement
changes a zone's first revisit by nothing (-0.157 against -0.158). Range Break loses -0.13 to -1.2R a trade
under the jump fill.

**The primary fails.** SWEEP_SHIFT on Deriv diffusive, 15m-1d pooled, E1: **-0.021R [-0.030, -0.012]**,
n = 65,104; halves -0.015 / -0.027; 15m -0.020, 1h -0.024, 4h -0.023, 1d +0.019 (15m-4h: -0.022); X2 -0.035.
iid walk -0.059, GARCH -0.058, bar bootstrap -0.057, published-sigma walk -0.036.

**P(N R)** (E1, primary): 0.617, 0.416, 0.190, 0.045, 0.001 at N = 0.5, 1, 2, 4, 10, against 1/(N+1) =
0.667, 0.5, 0.333, 0.2, 0.091 and the walk's 0.609, 0.407, 0.183, 0.042, 0.001. Like every trail here it
reaches small R more often than large R; the desk's 4R happens 4.5% of the time and 10R 0.1%. The curves
for every pattern and class are in `sweeps_pnr_<class>.png`: real and walk lie on each other.

**Cells.** 2,629 cells (13 patterns x symbol x timeframe with at least 30 trades): **0 BH-significant, 0
pass** - 675 Deriv, 1,954 real. 384 cells have R > 0 and 19 have their interval above 0 (expected by
chance at this count), scattered over classes and patterns with no two adjacent timeframes agreeing
(Drift Switch 10 15m P2/P6/P8 reclaim; AUDUSD 1d failed-break zone, n = 55; GBPJPY 4h/1d breaker, n = 53-88;
XAUUSD 1d CRT; BNBUSD 15m; SOL 1d turtle soup; AVAX 4h P6). None survives the correction.

**Why Deriv diffusive loses less than its walks.** Real -0.021 against -0.059 on the primary looks like
something; it is one family. By symbol (cells, all patterns): **Drift Switch 10/20/30 beat their walks by
+0.13 to +0.18R** (mostly on 15m, where the walks lose -0.35 to -0.61R and the real series -0.05 to
-0.24R), while Volatility and Step lose as much as their walks or more (-0.06 to +0.00). A 2-ATR trail
rides a drift regime; Drift Switch has drift regimes by design. It is still negative. The walks also pay
more cost than the real series (0.145R against 0.109R on the SFP): costs are the real series' ATR units,
and a constant-sigma arithmetic walk mismatches a geometric index's ATR over its history.

## Protected highs and lows: the label does not change the odds

P(held until the next break of structure the same way), decided cases, pooled (`protected.csv`):

| class | WEAK | STRONG | STRONG with BOS | SWEEP_STRONG | walk WEAK / STRONG / SWEEP_STRONG |
|---|---|---|---|---|---|
| Deriv diffusive | 0.608 | 0.616 | 0.578 | 0.641 | 0.601 / 0.616 / 0.654 |
| Deriv jumpy | 0.605 | 0.615 | 0.577 | 0.647 | 0.601 / 0.611 / 0.653 |
| Range Break | 0.550 | 0.589 | 0.534 | 0.622 | 0.601 / 0.617 / 0.677 |
| FX | 0.619 | 0.602 | 0.577 | 0.656 | 0.603 / 0.616 / 0.648 |
| metals | 0.614 | 0.598 | 0.567 | 0.646 | 0.607 / 0.620 / 0.645 |
| indices | 0.625 | 0.596 | 0.566 | 0.633 | 0.595 / 0.616 / 0.655 |
| energy | 0.651 | 0.603 | 0.575 | 0.650 | 0.605 / 0.617 / 0.648 |
| crypto CFDs | 0.624 | 0.608 | 0.580 | 0.650 | 0.605 / 0.614 / 0.647 |
| Binance | 0.623 | 0.607 | 0.583 | 0.654 | 0.601 / 0.612 / 0.654 |

Hundreds of thousands of graded lows (Deriv diffusive 98,388 strong, 11,677 sweep-strong, 24,744 weak).
A sweep-strong low holds a little more often than a strong one (0.64-0.66 against 0.60-0.62), and a strong
low WITH the structure (the textbook BOS) a little less (0.57-0.58) - **on walks exactly the same**: the
ordering is geometry (a sweep-strong low sits further from price when graded, 2.9 ATR against 2.7). On
real markets weak lows hold slightly *more* often than on walks (0.61-0.65 against 0.60) and strong
ones slightly less (0.60 against 0.62) - the opposite of the trader's reading, and small. Real markets
also make 1.25-1.70x as many weak lows as walks (the base-rate table). P(not traded under within 50
bars) is 0.41-0.50 for every grade, real and walk alike.

## Spikes: Boom and Crash are memoryless, as published

One-minute bars, 60 days (`spikes.csv`):

| feed | minutes a spike | waiting-time CV | memoryless CV | hourly var/mean | next-minute AUC | shuffled |
|---|---|---|---|---|---|---|
| boom_300 | 11.7 | 1.02 | 0.96 | 1.25 | 0.500 | 0.495 |
| boom_500 | 10.1 | 0.97 | 0.95 | 0.88 | 0.500 | 0.500 |
| boom_1000 | 18.4 | 0.99 | 0.97 | 0.92 | 0.494 | 0.491 |
| crash_300 | 7.6 | 0.92 | 0.93 | 0.85 | 0.494 | 0.504 |
| crash_500 | 10.2 | 0.94 | 0.95 | 0.91 | 0.502 | 0.503 |
| crash_1000 | 18.6 | 0.98 | 0.97 | 0.91 | 0.493 | 0.500 |
| jump_10 .. jump_100 | 430-561 | 1.00-1.53 | 1.00 | 0.98-1.12 | 0.42-0.62 | 0.48-0.53 |

The venue's own "manipulation" arrives as a Poisson clock: waiting times have the geometric CV, hourly
counts are Poisson, and the time since the last spike, the last hour's count and the recent bar size do
not predict the next one (AUC 0.493-0.502, the shuffled indicator's range). At 8 robust sigmas the Jump
indices yield only about 190 events in 60 days - far fewer than their documented jumps (one every ~20
minutes, [generators.md](generators.md)), so the threshold catches the tail of diffusion plus the largest
jumps; with ~95 held-out events their AUCs (0.42 to 0.62, two above and one below 0.5) are noise around
a coin, and this page draws nothing from them.

## Verdicts

- **Identification: done.** Ten sweep forms are MCFL entities with exact definitions, `known_at`,
  truncation and flip tests; five are new (CLOSE_REVERT, SWEEP_SHIFT, INDUCEMENT, BREAKER_RETEST/RECLAIM,
  PROTECTED/PROTECTED_TAKEN).
- **Base rates: Deriv = walk.** Real markets sweep more than Gaussian walks and no more than their own
  bars reshuffled.
- **Prediction: geometry.** Beyond distance the features add +0.0006 AUC on Deriv (Drift Switch's drift)
  and +0.001-0.004 on real markets; nothing tradable.
- **The primary fails** (-0.021R [-0.030, -0.012]). 0 of 2,629 cells pass. After a sweep, the next ATR is
  a coin in every class.
- **Protected levels:** strong, weak and sweep-strong hold at the walk's rates.
- **Boom/Crash spikes:** memoryless.
- **Anything beat walks?** Drift Switch (trades and the prediction gain) - a published generator
  property, still losing money - and a +0.0006 AUC that is the same property. Each was checked for
  look-ahead (every input is known at its bar; entry is the next open) and traced to its family before
  being reported.

## Plots (`.data/sweeps/`)

`sweeps_base_rates.png` and `sweeps_base_ratio.png` (per class: rates, and real / walk and real /
bootstrap per timeframe), `sweeps_predict.png` (AUC gains per class, real vs walks), `sweeps_pnr_<class>.png`
(P(N R) per pattern, real vs walks, one per class), `sweeps_R_by_class.png` (mean R with intervals per
pattern and class), `sweeps_protected.png`, `sweeps_spikes.png`, and `sweeps_gallery_<pattern>.png` (six
Deriv trades for each of eight patterns, three winners and three losers, with the swept level, the wick,
the entry, the stop and the trailing exit).

## A bug found on the way

`turn_trade.ups` (used by [turning-points.md](turning-points.md)'s turn trade and `deriv_turns.py`) counts
BREACH_REVERT↑ as a turn up at a 12-bar low. MCFL's BREACH_REVERT keeps the breach's direction:
BREACH_REVERT↑ is a swing *high* traded through and closed back under - the bearish one. On a 5,000-bar
walk it fires at 15 of 1,658 12-bar lows against 177 for BREACH_REVERT↓. So the T2 signal of those
studies was the wrong side and nearly empty; T_any was carried by DISPLACE_C and DELIVERY_SHIFT, whose
direction is the reversal's. This study uses the breach's convention throughout (a low swept, BREACH_REVERT↓,
is a long).

## Caveats

- **Bar fills.** Every fill is read from bars. On the jumpy indices E1w puts a jump-side stop at the bar's
  extreme - a bound, not a measurement; the plain bar fill (E1) is in the tables too and also loses.
- **Walk fidelity.** Arithmetic walks with one sigma mismatch a geometric index whose price level moved
  for years; the walks paid more cost in R than the real series. The bar bootstrap and the published-sigma
  walk bracket it; no verdict changes with the null.
- **Real-market costs** are the broker's spread floor (median tick spread where ticks exist, else the quoted
  spread); swaps and commissions are left out, which would only lower R.
- **The Judas swing** here is the first 3/3 swing of the London window faded at the next open; the
  time core's other readings (killzones) were not traded.
- **Binance 15m** is its last 100,000 bars (from late 2023); every other series is complete.
- **Prediction rows** are sampled (15m every 6th bar, 1h every 3rd) and both sides of a bar are rows, so
  the day bootstrap carries the dependence.
- **Inducement** uses MCFL's strict ZONE (origin, displacement, void, break); a looser zone could differ.
