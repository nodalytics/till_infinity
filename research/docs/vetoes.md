# Spread, rollover and news vetoes: what the gates buy, and where

Harness: [`research/harness/vetoes.py`](../harness/vetoes.py). Lab run 2026-09-29.

## The question

[`game-theory.md`](game-theory.md) ranked spread-, rollover- and news-aware vetoes first: the
dealer's spread is the one game-theoretic idea that pays here. Production already has most of the
gates. Are they right, are they set in the right place, and should the rollover veto extend to the
Sunday open?

## The gates in production

| gate | rule | default | where | evidence |
|---|---|---|---|---|
| `max_spread_risk_fraction` | refuse when spread / risk > 0.16 | 0.16 | `risk.py` | [`winning.md`](winning.md): +0.369R cheap minus expensive, p < 0.001 |
| `max_spread_fraction` | refuse when spread / reward > limit | 0.25 (plans: 0.15 / 0.25 / 0.35) | `risk.py` | `winning.md`: it uses the wrong denominator |
| `max_spread_ratio` | our spread above 2.5x the venue group's, or above 2.5x this instrument's usual for the hour | 2.5 | `context.py` | [`intraday.md`](intraday.md) |
| `max_dislocation_bps` | our quote more than 8 bps from the venue median | 8 | `context.py` | |
| `news_before` / `news_after` | stand aside around importance-HIGH releases | 600 / 900 s | `context.py` | |
| `quiet_hours` | no new entries in these UTC hours | **empty** | `risk.py` | `intraday.md` proposes 20-23 |
| `loss_cooldown` | no re-entry on a feed after a loss | 900 s | | |

## Method

Two samples:

- **A, the desk's own closes.** 308 attributed closes in the lab's journal snapshot
  (2026-08-27 to 09-10), joined to their decisions as [`winning.py`](../harness/winning.py) does.
  R comes from prices, spread / risk from `spread_at_entry / risk_price`, and gross R = net R +
  spread / risk. This sample is real but small, and mostly Deriv.
- **B, every production zone touch from the [`indicators.md`](indicators.md) replay:** the fade at
  the touch, H = 5 and 20 bars. Each touch is joined to its seqlab bar's **recorded spread**,
  expressed in bar volatilities, and charged as the cost. This sample is large and has real spread
  states. It covers about 22k FX touches, 5.8k metals and 24k Deriv as a market, each scored at both horizons. **The control** is our
  generated walks' zone touches, with a synthetic spread drawn *independently of price*: there a
  spread veto can only help by arithmetic.

**Crypto is excluded from the spread tests.** Its bar spread is in points whose size cannot be
inferred from the closes (they print whole), which gave impossible costs (7.9 vol at p80). The
broker's `digits` would fix this.

Each veto is scored on:

- the share of trades vetoed;
- the mean net and gross R of vetoed against kept trades, with a 95% day-bootstrap CI of the
  difference;
- the change in total net and in max drawdown;
- both halves;
- a random veto at the same rate (the share of 1,000 it beats).

A veto **helps** if the vetoed trades are worse net (CI excludes 0), the total improves, it beats at
least 95% of random vetoes, and it holds in both halves. It **selects** if the vetoed trades are
also worse *gross* (CI excludes 0), i.e. it does more than save its own cost. These rules were fixed
before the run.

## Results

### (a) Spread against risk: the cap saves cost, it does not pick losers

**A, the desk's trades,** by spread / risk at entry:

| spread / risk | n | net R | gross R | stopped |
|---|---|---|---|---|
| ≤ 0.05 | 136 | -0.088 | -0.060 | 10% |
| 0.05-0.10 | 66 | -0.286 | -0.212 | 35% |
| 0.10-0.16 | 31 | -0.069 | +0.060 | 32% |
| 0.16-0.25 | 31 | -0.517 | -0.332 | 45% |
| > 0.25 | 41 | -0.398 | **+0.064** | 51% |

| veto | share | vetoed - kept, net [CI] | gross [CI] | beats random | verdict |
|---|---|---|---|---|---|
| > 0.12 | 28.9% | -0.220 [-0.538, -0.019] | +0.037 [-0.285, +0.224] | 100% | helps |
| **> 0.16 (production)** | 23.4% | **-0.314 [-0.622, -0.198]** | -0.026 [-0.411, +0.084] | 100% | **helps**, both halves |
| > 0.25 | 13.3% | -0.219 [-0.877, -0.113] | +0.174 [-0.334, +0.279] | 97% | no (second half empty) |

Walk-forward (the cap chosen on the first 60%, scored on the last 40%) picks **0.06**. On the last
40% that gives -4.4R, against -14.5R at 0.16 and -17.1R with no cap. The difference rests on about
120 trades and one bin (0.05-0.10), whose loss is *gross*, not cost.

**B, the zone touches.** Every spread cap "helps" in every family: FX, metals, Deriv, and **our
walks**, where the spread is independent of price. The vetoed trades' *gross* is never worse (every
CI spans 0):

| family, H = 5 | veto spread > p90 | vetoed - kept net | gross |
|---|---|---|---|
| FX | 0.108 vol | -0.297 [-0.440, -0.161] | +0.025 [-0.114, +0.163] |
| metals | 0.237 vol | -0.157 [-0.411, +0.085] | +0.098 [-0.163, +0.357] |
| Deriv | 0.092 vol | -0.129 [-0.254, -0.012] | -0.074 [-0.194, +0.055] |
| walks (control) | 0.491 vol | -0.569 [-0.702, -0.436] | +0.036 [-0.087, +0.158] |

Gross R by spread decile is flat in every family (FX H=5: +0.05 -0.07 +0.01 +0.09 +0.01 +0.01
-0.06 -0.04 +0.09 +0.03).

### (b) Spread state: an abnormally wide quote is the same cost story

This compares each spread with its own trailing median. On the desk's trades the spread barely
varies (1 of 142 trades above 1.5x), so there is nothing to test. On the FX touches, spread above
2x its median (3.6% of touches) is worse net by -0.767 [-0.944, -0.593] at H=5 and -1.035 at H=20.
Gross is -0.056 [-0.232, +0.110] and -0.324 [-0.761, +0.085]: not significant. Metals and Deriv
show nothing. The walks "gain" the same way (-0.995). This is the cost, again, and it is what
`max_spread_ratio` already refuses on live quotes.

### (c) Time windows: 20-23 UTC and the Sunday open, for FX only

| window, H = 5 | FX | metals | Deriv | walks |
|---|---|---|---|---|
| 20-23 UTC | **-0.427 [-0.595, -0.260]**, 8.9%, helps | -0.153 [-0.435, +0.117] | +0.092 [+0.003, +0.179] (better) | -0.029 [-0.147, +0.077] |
| Sunday open (17-18 NY) | **-1.201 [-1.638, -0.830]**, gross **-0.435 [-0.824, -0.068]**, helps + selects | - | -0.042 | +0.203 |
| 16:55-17:10 NY | -0.323 [-0.641, -0.012], gross +0.345, beats 94%, no | - | +0.235 | +0.050 |

The table shows vetoed minus kept net R [CI] and the share vetoed. At H=20: FX 20-23 UTC -0.452
[-0.734, -0.187] and the Sunday open -1.495 [-2.447, -0.710] also help, in both halves. The desk's
own trades hold 19 entries in 20-23 UTC (mostly Deriv), which are **better**: +0.290 [-0.026,
+0.514].

### (d) News: no blackout width helps

| FX, H = 5 | share | vetoed - kept net | gross |
|---|---|---|---|
| high, -10/+15 min (production) | 2.8% | -0.048 [-0.293, +0.212] | -0.090 [-0.334, +0.168] |
| high, ±60 min | 9.9% | +0.185 [-0.001, +0.381] | +0.146 [-0.039, +0.345] |
| medium+high, ±30 min | 19.1% | +0.123 [+0.011, +0.227] | +0.091 |

Wider windows make the total worse, and metals are the same. Around releases the vetoed touches
are, if anything, *better*: metals medium+high -10/+15 at H=20, gross +0.478 [+0.051, +0.917].
The desk's trades hold 1-6 entries near a release, which is too few to judge.

## What this means

- **The spread gate is right, and what it buys is cost.** `max_spread_risk_fraction` = 0.16 passes
  every test on the desk's own trades. But across every family, and on walks whose spread is
  independent of price, the vetoed trades are no worse *before* costs. `winning.md`'s separator is
  the spread itself: a trade with no edge loses what it pays, so vetoing the dearest trades always
  helps, by arithmetic. The cap therefore trades cost saved against the trades lost. With these
  entries' gross edge near zero, the saving dominates.
- **Don't lower the cap yet.** Walk-forward's 0.06 beats 0.16 out of sample (-4.4R against
  -14.5R), but on about 120 trades, and the gain comes from one bin whose loss is gross, not cost.
- **The time windows are FX-specific, and the evidence is on the touches, not the desk's trades.**
  - FX entries in 20-23 UTC lose 0.43-0.45 vol more, in both halves and at both horizons.
  - FX Sunday-open entries lose 1.2-1.5 vol more, and at H=5 are worse even gross.
  - Deriv, metals and the walks are flat or better in the same hours, so a *global*
    `quiet_hours` would veto Deriv trades that do fine.
- **The news blackout does not measurably help,** at any width. Bars cannot see news slippage or a
  momentary spread spike, so it may still be worth keeping as a risk control, at its current
  narrow width.

## Proposed settings

Not applied. These are proposals only.

1. **Keep `max_spread_risk_fraction` at 0.16.** Revisit 0.06-0.10 once the journal holds 500 or
   more closes; the harness re-runs as is.
2. **Keep `max_spread_ratio` at 2.5.** Spread state is the same cost story, and the gate already
   exists.
3. **Add an FX-only quiet window, anchored to New York:** no new FX entries 16:00-18:59 New York,
   which is 20:00-22:59 UTC in summer and 21:00-23:59 in winter. This needs `quiet_hours` to take
   a family, or a separate FX setting. A global `TRADING_QUIET_HOURS=20,21,22` would cost the
   Deriv trades that do better there.
4. **Add an FX Sunday-open veto:** no new FX entries in the first hour after the Sunday 17:00
   New York open. It vetoes 0.9% of FX touches, which lose 1.2-1.5 vol more and are worse gross.
   This extends the rollover mask's reasoning to the open, as `game-theory.md` ranked second.
5. **Leave the news blackout as it is** (high only, -10/+15 min); do not widen it. It costs about
   3% of FX entries for no measured gain, and is kept only as a guard against slippage the bars
   cannot see.
6. **Placement in the planned confirmation layer:**
   - **Pre-model:** the time windows (3, 4) and news (5) need only the clock and the calendar,
     so they belong in the pre-model veto stage.
   - **After the plan:** spread / risk needs the planned stop, so it stays in `risk.py`.
   - **Where it is:** the spread ratio needs a live quote, so it stays in `context.py`.
7. **Fix crypto's spread units** (from the broker's `digits`) before any crypto spread veto is
   studied.
