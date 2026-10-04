# Three TradingView indicators traded, and levels built by clustering swing pivots

**Measured, 2026-10-04. Every primary fails. None of the four strategies beats its baseline and both
walks after costs.** The strategies are Zeiierman's "Levels Likely to Break", MarkitTick's Weinstein
Stage Cycle Tracker, Neblok's FVG Magnet Engine, and a bounce at clustered pivot levels. Each was traded
as the strategy it implies on the broker's bars: 76 non-Deriv MT5 markets on 1h, 4h and 1d.

Two things did show up, and neither is the indicator's claim:
- **Real levels hold a little more than walk levels.** On the first touch, 58-59% of real levels reverse
  1 ATR before a close 1 ATR beyond, against 56.5% on walks. That holds for single swings and for
  clusters alike. Clustering adds nothing to it.
- **Daily 30-bar breakouts held to the end of the stage earn about +0.2R.** That comes from crypto longs
  in a bull market (+1.06R real against about 0 on driftless walks). Without crypto it is −0.002R. The
  stage condition adds +0.004R over plain breakouts.

Scripts: [`ideas/tv_indicators.py`](../ideas/tv_indicators.py) (Part A) and
[`ideas/cluster_levels.py`](../ideas/cluster_levels.py) (Part B). Rules, frozen and committed before
any real-data run: [`ideas/tv_rule.json`](../ideas/tv_rule.json) and
[`ideas/cluster_rule.json`](../ideas/cluster_rule.json). This follows [bos-predict.md](bos-predict.md),
where the same three indicators, rebuilt as feature groups, added nothing to the side of a break beyond
geometry.

## The question

Do the three indicators earn R when traded the way their descriptions suggest? The bar is set by three
comparisons:
- a baseline that removes the indicator's claimed information;
- iid and GARCH walks matched to each series;
- the broker's costs.

Part B asks the same of levels built by clustering past swing pivots. It also asks whether those levels
hold more often than single swing levels, and more often than on walks.

## Frozen rules (full text in the JSONs)

**Data:**
- The broker's bars (`mt5bt`) for every symbol in `run.FAMILY`, on 1h, 4h and 1d. There are 272 series;
  XCUUSD has no 1d.
- The pass is judged on the pooled MT5 non-Deriv set: fx 12, metal 5, index 7, energy 2, crypto 35.
- The 15 Deriv synthetics are reported apart and never used as a control.

**Costs:**
- `run.spread_floor` × point, charged once per trade.
- Where that floor is 0 (the 32 fresh crypto CFDs, XPT, XPD and XCU), the median of the bars' own spread
  column is used instead. This was amended in the freeze, before the run.
- Every stop fill takes 0.05 ATR of slippage.

**Walks:**
- `synth.walk` and `synth.garch` (α 0.08, β 0.90), 256 sub-steps a bar, real timestamps, `synth.ticks`
  volume.
- They are **geometric**: sigma is the sd of log changes, exponentiated from the real first close.
  Weinstein's default slope is a % change, and the crypto CFDs moved 10-100×. The walks carry the real
  series' cost in ATR units.

**Common:**
- Pivots are 3/3 swings.
- Shorts are simulated on the negated chart.
- Exits:
  - **E1:** `turn_zones.exits`, a 2-ATR trail.
  - **X2:** a fixed 2R target.
  - Every exit holds at most 300 bars.
- Every structural stop sits at least 0.25 ATR from the entry.
- Intervals come from a day bootstrap: 2,000 draws, 90%.

**Pass:** R > 0 with its interval above 0, R > 0 before and after 2024-01-01, and R above the baseline,
the iid walk and the GARCH walk.

| | strategy (primary in bold) | baseline |
|---|---|---|
| **Z** | **On a close beyond the far edge of a repeated-pivot level whose break pressure at the bar before is in the top decile, enter the break's way at the next open. Stop at the near edge ∓ 0.1 ATR. Exit E1.** Pressure is the equal-weight mean of BOS G2's seven components (proximity, move toward, relative volume, close location, absorption, compression, fresh touches). The decile cut-off is learnt per source and interval from pre-2024 breaks. | every break |
| **W** | **Long at the next open on entering Stage 2, short on entering Stage 4, with the indicator's % slope (±0.5% over 4 bars). Stop at SMA30 ∓ 0.1 ATR. Exit STG: out at the next open once the stage ends.** The secondary uses BOS's ATR-z slope. | every fresh 30-bar breakout and breakdown, same stop and exits |
| **F** | **At the nearest live FVG (by distance to its CE) at least 1 ATR away, with learned CE-fill odds ≥ 70%, enter toward it at the next open. Target the CE, put the stop at the same distance on the other side, and exit at the gap's 150-bar expiry. Exit BR.** The odds are per series and per (direction, size bucket). They are age-adjusted and Laplace-corrected, need n ≥ 30, and are learnt only from gaps whose window has closed (the BOS version leaned toward fills). | the nearest-gap entry ignoring the odds; a coin twin (same times, random side) |
| **B** | **Each pivot's confirmation clusters the last 300 bars of pivot prices (cut at gaps over 0.25 ATR, no cluster wider than 1 ATR); the pivot's cluster is a level. On its first touch after price has left it by 1 ATR, place a limit at the centre against it, with the stop at the far edge + 0.1 ATR. Clusters of n ≥ 3 members, E1.** | the same at single swing levels (n = 1) |

## Primaries: all four fail

All rows are MT5 non-Deriv, with 1h, 4h and 1d pooled.

| | R [90%] | n | before / after 2024 | baseline | iid | GARCH | |
|---|---|---|---|---|---|---|---|
| Z top-decile break, E1 | **−0.683 [−0.797, −0.572]** | 9,142 | −0.328 / −0.838 | −0.716 | −0.598 | −0.723 | fails |
| W Stage 2/4 (% slope), STG | **−0.113 [−0.139, −0.088]** | 59,208 | +0.018 / −0.173 | −0.100 | −0.160 | −0.162 | fails |
| F ≥ 70% odds, CE bracket | **−0.278 [−0.298, −0.256]** | 110,006 | −0.093 / −0.353 | −0.260 | −0.293 | −0.297 | fails |
| B bounce at n ≥ 3, E1 | **−1.342 [−1.426, −1.259]** | 164,354 | −0.557 / −1.734 | −1.785 (n = 1) | −1.284 | −1.260 | fails |

P(N R) is the share of trades whose best excursion reaches N R. Its references are 1/(N+1) = 0.667,
0.5, 0.333, 0.2 and 0.091.

| | P(0.5R) | P(1R) | P(2R) | P(4R) | P(10R) | P(R≥4) | P(R≥10) |
|---|---|---|---|---|---|---|---|
| Z top decile, real / iid / GARCH | 0.535 / 0.520 / 0.534 | 0.427 / 0.439 / 0.445 | 0.291 / 0.304 / 0.309 | 0.150 / 0.164 / 0.160 | 0.036 / 0.035 / 0.039 | 0.050 / 0.051 / 0.057 | 0.010 / 0.013 / 0.013 |
| W % slope STG, real / iid / GARCH | 0.475 / 0.458 / 0.465 | 0.318 / 0.293 / 0.298 | 0.166 / 0.143 / 0.144 | 0.061 / 0.040 / 0.043 | 0.009 / 0.002 / 0.003 | 0.022 / 0.015 / 0.016 | 0.003 / 0.001 / 0.001 |
| F CE bracket, real / iid / GARCH | 0.634 / 0.637 / 0.635 | 0.493 / 0.499 / 0.497 | (capped at 1R) | | | | |
| B bounce n ≥ 3, real / iid / GARCH | 0.473 / 0.436 / 0.440 | 0.406 / 0.373 / 0.377 | 0.308 / 0.290 / 0.292 | 0.194 / 0.190 / 0.191 | 0.067 / 0.069 / 0.070 | 0.057 / 0.063 / 0.063 | 0.021 / 0.023 / 0.024 |

Every curve sits under 1/(N+1) and on top of its walks. W's tail is slightly fatter than the walks'
(P(4R) 0.061 against 0.040), and that tail is the daily crypto trend described below.

**Per family, and Deriv** (`tv_run.log` and `cluster_run.log`): every primary fails in every family.
The only intervals that reach above 0 belong to cells whose point R is still negative: Z index −0.05,
Z deriv −0.04, W energy −0.02 and W deriv −0.01.

## What each indicator's information is worth

- **Z, break pressure.** The top decile beats every break by 0.03R (−0.683 against −0.716). The same
  split on the iid walk is worth more: −0.598 against −0.825. So pressure is geometry (near, compressed,
  moving toward), not information. The **fade** of low-pressure levels is worse than fading every touch
  (−1.99 against −1.89R). Both are worse than on walks (−1.73 and −1.55).
- **W, stages.** With the filters off, every breakout outside Stage 2 enters Stage 2. The stage's
  information is therefore which breakouts to skip and when to leave. It is worth −0.013R against plain
  breakouts. The default % slope barely moves on 1h FX: EURUSD 1h spends 0.1% of bars in Stage 3 and
  52% in Stage 4. So on short timeframes the tracker is a 30-bar Donchian with a breakdown exit.
- **F, the magnet.** The odds tell almost nothing, because nearly every gap qualifies. At entry the
  predicted CE odds are 0.86-0.93, and 78% of the nearest-gap entries clear 70%. The odds are roughly
  calibrated, on real data and on walks alike: at birth, real predicted 0.928 against 0.919 realised and
  0.868 against 0.893. Walks fill just as often (0.90-0.91). Gaps fill because price wanders, not
  because it is pulled. And a filled CE is not a won bracket: the bracket wins 46-49% across every odds
  bin, real and walk, which is the coin twin's rate. Toward the gap −0.278, nearest gap −0.260, coin
  twin −0.275. See `tv_fvg_calibration.png`.

## Part B: do clustered levels hold?

The hold rate at the first touch is the share of resolved touches that reverse 1 ATR from the centre
before a close 1 ATR beyond it. Nearly every touch resolved within 300 bars.

| MT5 non-Deriv | n = 1 (single) | n = 2 | n = 3 | n = 4+ |
|---|---|---|---|---|
| real | **0.589** [0.583, 0.595] | 0.586 | 0.581 | 0.583 |
| iid | 0.566 | 0.566 | 0.567 | 0.565 |
| GARCH | 0.564 | 0.562 | 0.563 | 0.566 |

- **Real levels hold about 2 points more than walk levels.** It is clearest in fx and crypto, and in
  metals for n ≥ 3. In index and energy the intervals overlap. It is the same fact BOS found from the other side: real swing
  levels break less often than walk levels.
- **Clustering adds nothing.** Strength does not raise the hold rate on real data: 0.589 for singles,
  0.582 for n ≥ 3. Metals are the only family that trends up, from 0.580 to 0.598, with overlapping
  intervals. See `cluster_hold.png`.
- **Deriv** holds *less* than its walks (0.545-0.555 against 0.56-0.57). It is reported, not
  interpreted, and it mixes jump indices with diffusive ones.

**Traded, both fail.** The real hold excess does not survive a tight stop:
- **Bounce n ≥ 3:** −1.342R against −1.28 (iid) and −1.26 (GARCH). It does better than singles
  (−1.785), but walks show the same ordering.
- **Break n ≥ 3:** −0.438R, against −0.503 (iid) and −0.502 (GARCH).

Real bounces reach +0.5R more often than walk bounces (0.473 against 0.436), but the overshoots beyond
the far edge stop them out.

## Secondary cells and multiplicity

Part A has 440 real cells with a bootstrap p and n > 30; Part B has 312, for **752 in all**. These span
strategies and variants, exits, families and intervals, with Deriv apart. Under Benjamini-Hochberg at
q = 0.10 across all 752, four pass with R > 0, all from Part A, all W on 1d with the STG exit, MT5
pooled:

| cell (1d, STG) | R [90%] | n | before / after | iid | GARCH |
|---|---|---|---|---|---|
| W % slope, stage entries | +0.199 [+0.111, +0.294] | 4,776 | +0.224 / +0.137 | −0.024 | −0.031 |
| W % slope, fresh breakouts (its baseline) | +0.195 [+0.140, +0.255] | 10,259 | +0.249 / +0.048 | −0.011 | −0.034 |
| W ATR slope, stage entries | +0.175 [+0.105, +0.252] | 4,926 | +0.188 / +0.143 | −0.032 | −0.039 |
| W ATR slope, fresh breakouts | +0.129 [+0.084, +0.174] | 10,259 | +0.156 / +0.055 | −0.032 | −0.052 |

The first row clears every clause of the pass rule taken alone, but by 0.004R over its baseline. And it
is **crypto long drift**: crypto stage-2 longs make +1.06R (929 trades), against +0.19 (iid) and −0.01
(GARCH) on driftless walks. Crypto shorts make −0.04R. Without crypto the cell is −0.002R, against
−0.047 (iid) and −0.003 (GARCH). The same cell with the E1 trail is −0.017R. It is a 2021-2025 crypto
bull run that a long-biased trend rule caught, not something the stages know. Nothing in Part B passes
BH with R > 0.

## Cost sensitivity (not pre-registered)

The frozen fallback cost is absurd for XTZUSD (4.4 ATR on 1h) and TRUUSD (18 ATR), and it is 0.9 ATR for
SHBUSD. The walks carry the same cost in ATR, so the comparisons are fair, but the levels of R are not.
Excluding the three symbols:

| primary | R [90%] | baseline | iid | GARCH | |
|---|---|---|---|---|---|
| Z | −0.291 [−0.352, −0.230] | −0.236 | −0.243 | −0.195 | fails |
| W | −0.004 [−0.028, +0.021] | −0.022 | −0.039 | −0.036 | fails |
| F | −0.092 [−0.105, −0.080] | −0.094 | −0.084 | −0.087 | fails |
| B | −0.515 [−0.536, −0.494] | −0.654 | −0.438 | −0.430 | fails |

W comes closest. It beats its baseline and both walks by 0.02-0.035R, but its interval includes 0 and
after 2024 it is −0.018R. This is not a pass.

## Verdict

- **Z, Levels Likely to Break: fails.** −0.683R. Pressure is geometry, and it sorts walks too.
- **W, Weinstein stages: fails.** −0.113R. Its information over plain breakouts is −0.013R. The one
  BH-surviving family of cells (daily) is crypto drift.
- **F, FVG magnet: fails.** −0.278R. The odds are calibrated but uninformative: gaps fill about 90% of
  the time on walks too, and toward-the-gap equals the coin twin.
- **B, clustered levels: fails as a trade.** −1.342R, −0.515R without the three cost outliers. As a
  description, real levels hold 2 points more than walk levels, with single swings and clusters alike.
  This is the first level fact on this desk that beats walks, and it is too small to survive a stop
  placed at the level.

It joins every zone family before it: these trade like walks after costs.

## Caveats

- **These are re-implementations from the public descriptions, not the indicators' source.**
  - Zeiierman's pressure weights are ours (equal), and so are its pivot lengths (3/3) and match
    tolerances (BOS's).
  - The Weinstein machine is BOS's, including "MA stops rising requires it rose within the stage".
  - The FVG minimum size (0.25 ATR), window (150 bars), age thresholds and sample minimum (30) are ours.
  - The real indicators may differ in ways that matter.
- **One natural strategy per indicator.** Other entries (Z with an ATR buffer, W with the ADX and
  volume filters on, F with limit entries) were not tried.
- **Costs.**
  - The bar-spread fallback is wrong for a few crypto CFDs (see the sensitivity section).
  - MT5 bars carry the bar's *lowest* spread, so it is still a floor.
  - Swap is not charged. That flatters W's multi-week daily holds.
- **The walks are driftless.** Any trend-following cell on assets that rose (crypto 2021-2025) beats them
  through drift. The W daily cells are exactly that.
- **Overlap.** Z and B spawn a level per pivot, so trades over the same prices overlap, and the day
  bootstrap understates the dependence. The F baseline and F share most trades.
- **Indices and energy start on 2024-01-22.** They have no "before" half. Their 1d series (843 bars)
  learn little.
- **No volume-at-price (KDE) levels** were built (CFD tick volume is a range proxy). Part B is pivot
  clustering only.

## Re-running

On the lab (about 10 minutes for each run, 10 workers):

    OUT=out/tv MT5BT_DB=... MODE=run python research/ideas/tv_indicators.py      # then MODE=plot
    OUT=out/cluster TV_OUT=out/tv MT5BT_DB=... MODE=run python research/ideas/cluster_levels.py   # then MODE=plot
    SMOKE=EURUSD:1h:real python research/ideas/tv_indicators.py   # one series: counts, exit and machine checks

Outputs:
- **Tables:** `tv_cells.csv` and `cluster_cells.csv` (every cell × exit × scope × source × interval:
  n, R, interval, p, BH flag, halves, P(N R), P(R ≥ 4), P(R ≥ 10)); `tv_calibration.csv`; `tv_zcut.csv`;
  `cluster_hold.csv`; `both_cells_bh.csv`.
- **Data:** `tv_trades.pkl.gz`, `tv_gaps.pkl.gz` and `cluster_trades.pkl.gz`.
- **Plots:**
  - `tv_pnr.png` (primaries) and `tv_pnr_secondary.png` (Z fade, W ATR, F full): P(N R) real against
    iid, GARCH and baseline, per family;
  - `tv_Z_winners.png` / `_losers.png` (levels with pressure), `tv_W_*.png` (MA coloured by stage),
    `tv_F_*.png` (gaps with odds), `cluster_winners.png` / `_losers.png` (members, centre and span);
  - `tv_fvg_calibration.png`;
  - `cluster_hold.png` (hold rate by strength, real against walks);
  - `cluster_pnr.png`.
