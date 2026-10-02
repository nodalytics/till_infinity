# Trading-idea catalogue: `lab/scripts/` (344 files) and `lab/retired/` (266 .py + 14 .md)

All paths are relative to the source. Everything was read-only.

**How this was built.** I could not spawn helper agents (the concurrency limit was reached), so I did the work myself:
- I extracted the module docstring of every script.
- I read the code for every tradeable or strategy-like script.
- I grepped parameters for the pure diagnostics.
- For `retired/`, I read the READMEs, all strategy `.md` docs, configs and the core detector functions.

**Where results come from.** Most scripts print results at runtime and record none in code. The numbers quoted below are the ones stated in docstrings, comments or the md docs. Detailed result tables live in `lab/docs` and `lab/data/*.parquet`, which belong to other agents.

## 0. Shared primitives, defined once and reused below

| Name | Definition |
|---|---|
| **ATR14** | Wilder: `tr.ewm(alpha=1/14)`. Some scripts use a 14-bar SMA of TR instead. |
| **TSMOM ens** (the "momentum bias", the lab's main edge) | Daily close. `ens = mean(sign(c.pct_change(L)) for L in (7,14,30,60))`. Long if `ens ≥ 0.5`, short if `≤ −0.5` (3 of 4 lookbacks agree). Vol-scaled form: `pos = (ens · (0.10/√365)/sd30).clip(±3).shift(1)`, where sd30 is the 30-day std of daily returns. Cost is 5 bp × \|Δpos\|, equal-weight across coins. |
| **Pivot levels** (level lab) | `PIVW=5` centered extremum. The level is only used from bar p+6 on, so it is causal at use time. |
| **Range position** | `pos = (c − min(low,W)) / (max(high,W) − min(low,W))`, W=20 or 50, includes the current bar. |
| **Event detectors** (`lab/events.py`) | **sweep(24):** high > prior 24-bar max high and close back below it → short (low mirror → long). **z_extreme(24, 2):** \|(c−SMA24)/sd24\| > 2 → fade. **breakout(48):** close > prior 48-bar max close → long. **vol_rollover(12):** close at 12-bar high while mean volume over 3 bars < prior 12-bar mean → short (low mirror → long). |
| **BSBF HMM vol state** | 3-state Gaussian HMM on [ret, realized vol, range]. Emissions are fit on the first 50–65%, then a causal online filter runs. State 0 = low vol, 2 = high vol. |
| **Walk-forward "v4 protocol"** | Fit on 60% train: DEPLOY if hit > 50% and mean > 0, FLIP if hit < 50% and mean < 0. Test on 40%. Three overlapping sub-windows (0–3000, 1000–4000, 2000–5000 bars of 1h data). "Robust" = test hit ≥ 55%, delta ≥ −15 pp, n ≥ 5. Selection across many instrument × signal pairs is a multiple-testing risk. |

**Unit bug in level-lab cost charging.** Many level-lab scripts charge `COST=0.0002` (a fraction of price) as `COST / stop_distance` with the stop in *price units*. That roughly works for FX near 1.0, but it massively undercharges gold, JPY pairs and crypto. Affected: `experiment_bounce_fade*`, `level_*`, `break_*`, `level_cluster`, `orderflow_proxy`. Not affected: `compression_breakout` and `nds_geometry` (correct `COST/(risk/entry)`), and `reversal_trade` (correct).

---

## A. Momentum and trend

### A1 `tsmom-crypto`
- **Files:** `momentum_bt.py`, `momentum_stress.py`, `momentum_synth.py`, `btc_lead_momentum.py`, `cusum_daily.py`, `ml4t_hrp_dsr.py`, `validation.py`.
- **Rule:**
  - Daily binance_3y perps (1h resampled to 1D), vol-scaled TSMOM as in §0, single L ∈ {7,14,30,60,90} or the 7/14/30/60 ensemble.
  - Variants:
    - skip-7 ("12-1"): `sign(c.shift(7).pct_change(30))`
    - long-only / short-only (pos clipped)
    - TS+XS blend
    - leverage to target vol 10/20/40%
    - BTC-gated: keep only positions where `sign == sign(BTC 30d return).shift(1)`
    - CUSUM-agree filter (see A10)
    - HRP across per-coin strategies
- **Exit:** signal-driven, rebalanced daily.
- **Results (docstrings):** TSMOM 7–30d net Sharpe ~0.6, real vs shuffle; momentum Sharpe 0.74 (`ml4t_hrp_dsr` asks whether the DSR is significant); the momentum book has a ~72% drawdown problem (`kswin_validate`).
- **Controls:** shuffle; Deriv R_* synthetics as controls (`momentum_synth`).
- **Data:** daily crypto OHLC. **Lookahead:** none (shift 1). Universe survivorship: delisted coins are absent.

### A2 `xs-momentum-crypto-perps` (the "deployable spec")
- **Files:** `experiment_cross_sectional.py`, `experiment_xs_v2.py`, `experiment_xs_v3.py`, `experiment_xs_v4.py`, `experiment_xs_momentum_hardened.py`, `experiment_xs_sizing.py`, `experiment_xs_leverage.py`, `momentum_bt.py` (xsmom), `experiment_reversal_xsectional.py` (reverse sign).
- **Rule:**
  - 1h perps. Signal `P[t]/P[t−LB] − 1` with LB = 360 h. Rebalance and hold H = 240 h.
  - Long top 30% / short bottom 30%, equal weight, dollar-neutral.
  - Eligibility: ≥ 720 h of history (point-in-time).
  - Cost 4 × 6 bp per rebalance.
  - Funding: shorts earn and longs pay the summed funding over the hold.
- **Grid:** `experiment_cross_sectional` sweeps LB {12…720} × H {12…240}; hardened cells (240,240), (360,240), (168,240), (240,168), (360,168).
- **Overlays:**
  - v2: inverse-vol legs (168 h vol); gross gate = `min(1, median2000(basket vol)/basket vol)`.
  - v3: beta-neutral (beta168 to the equal-weight basket, subtract `net_beta × basket fwd`); crash filter (EW basket more than 15% below its 720 h high → exposure × 0.3).
  - v4: universe restricted to top-N by 720 h average dollar volume (40/30/20); sensitivity dd_cut −10…−25%, scale 0…1, dd lookback 480…1440.
  - Hardened: vol target 25% annualized on the trailing 8-period std, cap 3×.
  - Sizing/leverage: static L, target-vol L*, dynamic vol target, DD-brake (CPPI-like), fractional Kelly; MAR ratio.
- **Results:** raw DD −40%, v2 DD −38%. Deployable spec = "top-40 momentum 360/240 + crash filter".
- **Data:** 1h perp closes, funding (8h, stored in the `open` column of the funding feather), volume. **Lookahead:** none found. Delisted coins are missing.
- **Reversal variant** (`experiment_reversal_xsectional`): rank trailing L ∈ {3,6,12,24} 1h bars; long bottom 20% / short top 20%; hold H ∈ {6,12,24}; 6 bp per leg.

### A3 `accel-early-momentum`
- **Files:** `forming_momentum.py`, `accel_validate.py`, `accel_cost.py`, `gold_strategy.py` (gold version).
- **Rule:**
  - `mom = mean_L(c.pct_change(L)/(vol20·√L))` with vol20 = std of log returns over 20 bars.
  - `accel = mom.diff(3)` (gold: `diff(5)`, L = 21/63/126/252).
  - EARLY position = `sign(accel)` only when `|ens| < 0.5` (trend not yet confirmed), else 0. Daily book, next-day return.
- **Costs:** grid 0/5/10/20 bp. `accel_cost` uses top-15/30 by median dollar volume; taker = 5.5 bp + half-spread (10% of the median daily range, clipped 0.5–4 bp); maker = 2 + 1.5 bp adverse selection.
- **Results:** EARLY gross Sharpe 1.09 vs confirmed 0.65, but IC within noise; turnover-bound, break-even ~10 bp/side.
- **Data:** daily crypto (gold). **Lookahead:** none.

### A4 `donchian-box-breakout` (the "known edge ~+0.14R")
- **Files:** `experiment_frontier_batch1.py`, `experiment_frontier_batch2.py`, `experiment_compression_breakout.py` (ungated arm).
- **Rule:**
  - Box = high/low of the prior 20 bars.
  - The first CLOSE beyond the box within 24 bars → enter at the box edge.
  - Stop 1.0 × box width, target 2.0 × box width, timeout 96 bars; intrabar barrier checks; cost 2 bp; next scan starts at bt+24.
- **Batch1 buckets:** UTC session (Asia 0–8, EU 8–14, US 14–22, late), first vs second half (alpha decay), VIX terciles.
- **Batch2:**
  - Exit variants: fixed 2R; breakeven after +1 box; trail at (high-water − 1 box); scale out half at +1 box then trail; exit when close re-crosses entry.
  - Hawkes intensity `λ = λ·e^(−1/12) + 1{|r| > 2·sd48}` → AUC for a 1.5% move within 24 bars.
  - Bandit: softmax(3 × Sharpe over 500 bars) allocation across `sign(c − SMA50)` streams, rebalanced every 50 bars.
- **Data:** 1h FX/metals/crypto. **Lookahead/fill bias:** the fill is assumed at the box edge although the trigger is a close beyond it, which flatters entries.

### A5 `compression-breakout`
- **File:** `experiment_compression_breakout.py`.
- **Rule:**
  - Compressed when ATR14 ≤ the 30th percentile of the trailing 200 ATRs.
  - Bracket the 20-bar box; first close beyond it within 24 bars → enter at the edge.
  - Stop {0.5, 1} × box, target {1, 2, 3} × box, timeout 96 bars; 2 bp. Compared against an ungated sample every 5 bars.
- **Results:** "quiet label AUC 0.595 (89%)" is the only predictable label.
- **Lookahead:** same edge-fill bias as A4.

### A6 `gold-momentum-macro`
- **Files:** `gold_strategy.py`, `gold_strategy2.py`, `gold_data.py`.
- **Rule:**
  - Daily GC=F. `price_mom = mean sign pct_change L` (L = 21/63/126/252): long ≥ 0.5, short ≤ −0.5.
  - Macro 63-day signals: realrate = −sign(Δ real 10y); dollar = −sign(DXY 63d return); breakeven = +sign; nom2 = −sign(Δ 2y).
  - Composites: "multi" and "macro-confirms-price".
  - Exits: swing (close breaks the 15-bar low for longs / high for shorts), flip, or both. Cost 3 bp/side.
  - Pass 2: best exit = flip; macro-aligned sizing 1.5×/0.6×; flatten longs when the 63-day real-rate rise is above the 70th percentile; classic 12m momentum.
- **Results:** gold-only momentum Sharpe ~0.38 (`metals_xs` docstring).
- **Data:** Treasury real/nominal yields, yfinance.
- **Lookahead:** the gate percentile uses the full sample.

### A7 `metals-xs-momentum`
- **File:** `metals_xs.py`.
- **Rule:** daily GC, SI, PL, PA, HG (plus energy in the broad version); score = mean sign of 21/63/126/252 returns. Long rank ≥ 0.66 / short ≤ 0.34; long-top-half variant. Real-rate switch: long/short when real10 63d is falling, else long-top.

### A8 `equity-xs-momentum`
- **Files:** `tokenized_momentum_robust.py`, `tokenized_momentum_meta.py`, `tokenized_research.py`.
- **Rule:**
  - ~90 US large caps daily; same 4-lookback score.
  - Long top half; market-neutral (top 20% − bottom 20%, 5 bp); long-top beta-hedged vs SPY.
  - Meta-label picks over FW = 5. `tokenized_research` adds TS momentum + swing-trail on shorts (K=15) with flip exits on longs.
- **Results:** 1.58 Sharpe / DSR 1.00 on 23 hand-picked names was survivorship; beta-hedged long momentum validated at 1.08 Sharpe / DSR 0.99.
- **Lookahead:** full-sample hedge beta; survivorship (today's large caps).

### A9 `meta-label-momentum`
- **Files:** `meta_label_wf.py`, `meta_label_indicators.py`, `online_meta.py`, `triple_barrier.py`.
- **Rule:**
  - Side = TSMOM ens. Meta label = `side × sign(fwd 10d) > 0`.
  - LightGBM (200 trees, 15 leaves, min_child 300) on m5, m10, m21, m63, rev1, vol21, volz21, rsi, distEMA20, skew21, kurt21, ens (+ indicator set).
  - Expanding refit every 63 days starting at 40% of dates; take the trade only if P > 0.5. The online river version learns each outcome H days later.
- **Results:** walk-forward 0.81 → 1.08 Sharpe; single split −0.36 → +0.33 (DSR 0.42); frozen model 0.66 → 0.64. **Lookahead:** none.

### A10 `cusum-breakout`
- **Files:** `cusum_test.py` (1h), `cusum_daily.py`.
- **Rule:** sage_lite `cusum_breakout_column` / `cusum_breakdown_column` (returns_window = 24, threshold_k = 2.0). BUY fires when the cumulative up-deviation exceeds k × rolling std. Inputs compared: close / hlc3 / hl. Daily state is long after BUY until SELL; also tested as a filter on TSMOM.
- **Results:** 1h CUSUM dead.

### A11 `peak-filter` / `swing-exit` / `btc-exit` / `mtf-entry` / `cvd`
- **Files:** `peak_momentum.py`, `swing_exit.py`, `lead_lag.py`, `momentum_mtf.py`.
- **Rules:**
  - Peak filter: `ext = (c − EMA20)/c / ATR%14`, volz20. Filters (lagged 1): \|ext\| < 2 or 3; volz > 0; both; avoid climax = NOT(\|ext\| > 3 & volz > 1.5).
  - Swing exit: exit a long when the close breaks the rolling K-bar low (short mirror) vs a fixed H = 10 exit; max hold 60.
  - BTC-gated exit: exit an alt on the alt's own K=5 swing break vs BTC's swing break vs either.
  - MTF entry: limit at next-day open × 0.995 on long-trend days vs the signal-day close (oracle = next-day low).
  - CVD momentum: `delta = 2·taker_buy − volume`, cvd = cumsum, ens sign over 7/14/30/60; price momentum taken only when CVD agrees. Needs Binance taker volume.

### A12 `regime-switch-jump-model`
- **File:** `experiment_regime_switch.py`.
- **Rule:**
  - 1h. Features ER24 = \|c − c[−24]\| / Σ\|Δc\| and vol24.
  - 2-state statistical jump model (k-means + jump penalty λ = 8, standardized), refit every 48 bars on the trailing 600; trend state = higher-ER centroid.
  - Base = sign(c − SMA50): ride it in the trend state, fade it in the range state. Cost 2 bp × \|Δpos\|; OOS on the last 40%.
- **Lookahead:** none (Viterbi on a trailing window; uses the last state).

### A13 `indicator-zoo` (signal-only)
- **File:** `indicator_zoo.py`.
- **Rules (daily crypto, next-day book):**
  - MA_cross sign(SMA20 − SMA50); EMA_cross sign(EMA12 − EMA26); MACD vs signal9; ADX_DI sign(+DI − −DI)(14).
  - Donchian20 (close vs prior 20-bar high/low); ROC20 sign; RSI_MR <30 long / >70 short; RSI_trend sign(RSI − 50).
  - Stoch_MR <20 / >80 (14); CCI_MR ±100 (20); WillR_MR <−80 / >−20; BB_MR %b < 0 / > 1; Zscore_MR z20 ±2; CMF sign (20); MFI_MR <20 / >80 (14).
  - LightGBM over all indicator values, refit every 63 days.
- **Results:** ML direction from indicators −0.96 (docstring).

---

## B. Funding and carry (crypto perps)

### B1 `funding-carry-delta-neutral` (the "validated survivor")
- **Files:** `funding_carry.py`, `funding_carry_wf.py`, `funding_carry_explore.py`, `funding_kalman.py`, `funding_carry_basis.py`, `funding_carry_liquid.py`, `basis_carry.py`, `experiment_carry_refine.py`, `experiment_funding_carry_arb.py`, `funding_carry_meta.py`.
- **Rules:**
  - Base: hold short perp + long spot (or the reverse) by `sign(f_{t−1})`; carry = `sign(f_{t−1}) × f_t` per 8h; flip cost 5 bp × 2 legs.
  - Walk-forward (`funding_carry_wf`): every 14 days select coins with trailing-60d flip rate < 8%, mean > 0 and coverage > 80%; hold the next 14 days; 5 bp × 2 legs per entry/exit.
  - Kalman: local level (q = .02, r = 1) on funding; `pos = sign(Kf) × 1{|Kf| > floor}` with floor 0/3/6/10% annualized.
  - Basis-aware PnL: `s·f_next + s·(mark_ret − perp_ret)_next − cost·flip`.
  - Liquid version: top-N 60/25/15/10 by dollar volume with cost 10/8/7/6 bp.
  - `basis_carry` (Bybit): funding minus Δbasis, basis = (perp − mark)/mark.
  - `carry_refine`: enter when funding/8h ≥ 3 or 5 bp; hold 9/21/63 cycles; fees 0.23% / 0.08% / 0.05% round trip.
  - Pure carry arb: threshold {0, 1, 3, 5} bp, H {3, 9, 21, 63} cycles, 0.23% pair fees.
  - Meta (`funding_carry_meta`): daily; enter when APR ≥ 33%; hold 7 days; net = next-7d funding − 8 bp. Baseline gate flip14 < 0.12 & mean14 > 0, vs HistGB / river meta.
- **Results:** "Sharpe-16 carry" in walk-forward funding-only (`basis_carry` docstring), which is why the basis test exists.
- **Data:** 8h funding, mark price (spot proxy), perp price. Not OHLC-only.
- **Lookahead:** `basis_carry` selects on the full sample; the liquid version ranks liquidity on the full sample.

### B2 `funding-fade-short` (replica of the freqtrade `funding_rate_contrarian`)
- **Files:** `experiment_funding_filters.py`, `experiment_selective_strategy.py`, `experiment_funding_hmm_overlay.py`, `experiment_funding_metalabel.py`, `experiment_funding_carry.py`, `experiment_funding_exit.py`, `experiment_funding_edge.py`, `regime_composite.py`.
- **Entry:**
  - crowded = funding ≥ rolling-720h 90th percentile, OR APR (rate × 1095 × 100) ≥ 50, OR z720 ≥ 2.
  - exhaust = crowded AND 24h return ≥ +50%.
  - leader = BTC and ETH funding z (over 90 funding events) both ≥ 2.
  - Variants: A all bars, B crowded, C exhaust, D leader, E full OR. SELECTIVE = exhaust OR leader.
  - GATE: a BTC 3-state HMM on [r, \|r\|] (fit on the first 40%) must not be in the "normal" regime.
- **Exit (short):**
  - ROI ladder by minutes held: {0: 2.5%, 240: 1.2%, 720: 0.6%, 1440: 0.2%, 2880: 0}.
  - Stop −5%; trailing: once profit ≥ 1.5%, exit on a 0.8% giveback; max 200 bars.
  - Close-based, one position per symbol, funding carry added, cost 6 bp round trip.
- **Simpler variants:**
  - `experiment_funding_carry`: short when funding > 0 and ≥ the trailing-90d 90th percentile; hold 8/24/72h.
  - `experiment_funding_exit`: TP/SL pairs 1.5/3, 2/4, 2.5/5, 3/6 %, max 72h.
  - Kalman fade: \|z30 of funding\| > 1.5 → −sign position.
- **Results:** PF ~1.2–1.5; "the funding edge IS the exit"; causal test says the fade is non-causal (`causal_edges`).
- **Lookahead:** `selective_strategy` and `hmm_overlay` use `hmm.predict` (Viterbi) over the full series, which uses future observations.

### B3 `xs-funding-carry-sleeve`
- **Files:** `experiment_xs_v2.py`, `funding_carry_explore.py`.
- **Rule:** rank by trailing 72h funding sum; long low / short high (30% buckets, H = 240h; inverse-vol and gross gate optional). Alternative: each settlement go long low-funding / short high-funding (rank − 0.5) for one period.

### B4 `fresh-listing-fade`
- **Files:** `fresh_listing_fade.py`, `fresh_listing_robust.py`.
- **Rule:** perps listed more than 30 days after the universe start. Short at day D (3/5/7/14) after listing, cover at D+H (14/30). Robust version: D = 7, H = 30, fee 5 bp/side, plus funding earned by the short. Bucketed by debut pump `c[7]/c[0] − 1` (<0, 0–30%, 30–100%, >100%); early vs late cohorts.
- **Data:** daily perps + funding. **Caveats:** small n, survivorship.

---

## C. Mean reversion and statistical arbitrage

### C1 `bb-sr-kalman-mr` (the FX/index "one survivor")
- **Files:** `bollinger_sr.py`, `fx_sr_backtest.py`, `random_walk_control.py`, `synth_full.py`.
- **Rules (4h bars):**
  - **BB:** z = (c − SMA20)/sd20; long when z < −2, short when z > 2; exit when z crosses 0.
  - **KALMAN:** local-level Kalman fair value (q = 0.01, r = 1); dev z over 20 bars; same thresholds.
  - **SR:** pir = position in the 50-bar range; long < 0.1, short > 0.9; exit at 0.5.
  - **CONFLU:** z < −2 & pir < 0.2 long; z > 2 & pir > 0.8 short; exit at z = 0.
  - `fx_sr_backtest`: L = 50, thr = 0.1, signal at t traded t→t+1, equal-weight majors+crosses; grid L {30, 50, 100} × thr {.05, .10, .15}.
- **Costs and test:** 1.5 bp per unit turnover; last 40% test; circular-shift null; GBM random-walk null.
- **Results:** FX SR net @ 1.5 bp Sharpe +1.69, 100% positive years, beat the GBM null; indices +1.07 (`random_walk_control`).
- **Data:** 4h OHLC (TradingView OANDA). **Lookahead:** none.

### C2 `htf-pullback-range-cycle`
- **Files:** `expanded_cycle.py`, `cost_cycle.py`, `cross_asset_breadth.py`, `swing_premium_discount.py`, `swing_pd_fx.py`, `swing_pd_gauntlet.py`, `rl_premium_discount.py`.
- **Rules:**
  - LTF 4h pos20; HTF 1d dir = sign(c − c[−20]); HTF ER20; HTF lagged 1 bar.
  - TREND = HTF dir. PULLBACK = HTF dir only when LTF is in the counter zone (dir > 0 & pos < 0.34, or dir < 0 & pos > 0.66). RANGE = −sign(pos − 0.5). REGIME = PULLBACK if ER > train median else RANGE.
  - Cost grid 0–3 bp; next-bar returns; equal weight.
  - **Breadth:** db = fraction of the basket with pos < 0.34 (pb mirror). CONFIRM: trade only if ≥ 40% of the basket is in the same zone. DIVERGENCE: a lone hit (≤ 15%) is traded as continuation.
  - **ICT premium/discount:** contrarian sign(0.5 − pos); ALIGNED (LTF and HTF on the same side of 0.5) vs conflict.
  - **RL:** tabular Q on state (LTF zone, HTF zone, HTF c > SMA20, current position); reward = pos·r − 5 bp·\|Δpos\|; 40 epochs, ε .12, α .1, γ .9.
- **Results:** the FX + equity-index cluster is the only place an edge cleared the null; index RANGE gross confirmed; crypto behaves as MOMENTUM.

### C3 `zscore-mr-fx-crosses`
- **Files:** `experiment_meanrev_scope.py`, `experiment_mr_portfolio.py`, `experiment_macro_factor.py`, `experiment_rmt.py`.
- **Rule:**
  - 1h. z = (c − SMA48)/sd48; long z ≤ −2 / short z ≥ 2; exit when z crosses 0; stop \|z\| ≥ 4; max hold 96 bars; cost 2–3 bp.
  - Ex-ante universe: lowest in-sample Hurst (non-major crosses, top 12); inverse-vol weights from in-sample.
  - VIX tercile gating; RMT Marchenko-Pastur-cleaned min-variance portfolio (window 500, rebalance 100).
- **Results:** Pass A +1.8 bps/trade; correlation haircut "25 crosses ≈ 4 real bets".

### C4 `usd-pair-vs-dxy-residual`
- **Files:** `experiment_dxy_statarb.py`, `experiment_macro_factor.py`.
- **Rule:**
  - 1h. beta = rolling cov/var(200) of log pair vs log DXY; spread = lp − beta·ld; z48.
  - Fade \|z\| ≥ 2; exit at z = 0; stop \|z\| ≥ 4; max 96 bars; 3 bp.
  - Pick pairs with residual Hurst < 0.5 in-sample; inverse-vol combine.
  - "DXY-lead" variant: trade the pair `−sign(beta)·sign(zDXY)` when \|zDXY\| ≥ 2.
- **Results:** USDJPY +12.3 bps, USDCAD +2.9 bps per trade (Pass B).

### C5 `currency-strength-factors`
- **Files:** `experiment_currency_factors.py`, `experiment_currency_signals.py`, `experiment_currency_mr_validate.py`, `experiment_factor_density_combo.py`, `fx_factors.py`.
- **Rules:**
  - Currency index = mean(+r if base, −r if quote) over the 28 pairs (1h).
  - XS momentum: every 24h, long the top-2 / short the bottom-2 currencies by trailing lb-hour sum (lb 48/120/240/480); hold 24h; 1.5 bp per leg.
  - XS MR: long the 2 weakest / short the 2 strongest; lb 120–336h.
  - TS currency momentum.
  - Factor residual: `cumsum(r_pair − (LOO base idx − LOO quote idx))`, z48, fade ±2, exit at 0, stop 4, max 96, 1.5 bp.
  - Density gate: ≥ 3 of the last 200 closes within 0.15% of current price.
- **Results:** pairs ≈ base − quote, R² 0.96.

### C6 `crypto-pairs-coint`
- **Files:** `ml4t_pairs.py`, `pairs_strategy.py`, `pairs_robust.py`.
- **Rules (daily log prices):**
  - Engle-Granger p < 0.05 on the first 60%; OLS beta; spread z30; short spread z > 2, long z < −2, exit \|z\| < 0.5; return (ra − β·rb)/(1 + \|β\|); 5 bp.
  - Walk-forward: re-test every 90 days on the trailing 365; Kalman hedge (δ 1e-4, R 1e-3); entry \|z\| > 1, exit at 0, stop 3.5.
  - Robust: sector-only pairs, cointegrated in the last 2 consecutive windows; 90-day OLS hedge; entry 2, exit 0.5, stop 4.
  - Control: never-cointegrated pairs.
- **Results:** the Kalman all-vs-all build washed out (control beat it, −20% DD).

### C7 `pca-eigenportfolio-statarb` (Avellaneda-Lee)
- **File:** `pca_statarb.py`.
- **Rule:**
  - Daily crypto. 60-day z-scored returns → correlation → top K = 5 eigenvectors.
  - Regress each coin on factor returns; cumulative residual → OU fit (AR1 b ∈ (0,1)); s = (X − m)/√var_eq.
  - Short s > 1.25, long s < −1.25, exit \|s\| < 0.5; dollar-neutral normalized; next-day return; 5 bp per turnover; shuffled control.

### C8 `gold-mr`
- **File:** `gold_meanrev.py`.
- **Rule:** daily gold. Oscillators z20, z60, (RSI − 50)/15, Bollinger %b scaled, distMA. Fade \|osc\| > 2. Exits: mean (\|z\| ≤ 0.3), swing K = 15, time 20, or all three. Regime switch: momentum when real10 (63d) is falling, MR when rising. Cost 3 bp.

### C9 `natgas`
- **File:** `natgas_fundamentals.py`.
- **Rules:**
  - Seasonal: monthly position = sign(mean return of the same calendar month in prior years, ≥ 3 observations).
  - MR: −sign(z of log price), with 20d z → 5d forward or 60d z → 20d forward.
  - CL/NG log-ratio z120 → 20-day convergence.

### C10 `kacm-anticor`
- **File:** `k_acm.py`.
- **Rule:** long-only crypto. Anticor (w = 15) on Kalman-filtered prices (q = .05) plus a momentum tilt λ = .25 (softmax of the 15-day return); 10 bp per turnover.

### C11 `tokenized-nav-basis-fade`
- **Files:** `nav_basis_robust.py`, `tokenized_book.py`.
- **Rule:** basis = xStock token / underlying; z20; position −sign(z) lagged 1; trade the token; cost 0–30 bp.
- **Results:** pooled gross +0.78, carried by COINX +2.72.

### C12 `natural-MR-tests` (diagnostic)
- **Files:** `experiment_derf`/`fused_sizer` are in G; `synth_structure.py` (fade last bar); `vol_lead_price.py` (short after a top-decile vol jump; buy after a Q5 vol level).

---

## D. Support/resistance and key levels (scripts)

### D1 `proven-level-fade` (bounce ≥ 4)
- **Files:** `experiment_bounce_fade.py`, `_validate.py`, `_refine.py`, `_breadth.py`, `_hybrid.py`, `_regime.py`, `experiment_bounce_fatigue.py`, `_synthetic.py`, `experiment_why_weak.py`, `experiment_synthetic_levels.py`.
- **Level and touch definition (1h FX 12–14 pairs, gold/silver, 22–24 Binance perps):**
  - Pivot PIVW = 5 high/low. Touch: high ≥ lvl × (1 − 0.0015) for resistance (low ≤ lvl × (1.0015) for support), once per zone visit.
  - Resolution within K = 24 closes: BREAK if a close goes beyond lvl × (1 ± 0.001) first; BOUNCE if the close moves 1.5 ATR away first.
  - The level is killed at its first break; scan up to 600 bars.
- **Trade:** fade (long support / short resistance) only when prior bounces ≥ 4.
  - Locked validate: entry at the touch close, stop 1.0 ATR, target 2.5 ATR, H = 60 (close path).
  - Refined/breadth (locked "corrected"): limit 0.5 ATR deeper than the level, filled within 12 bars; stop 1.0 ATR beyond the level; target 3.0 ATR; H = 80; intrabar barriers.
  - Refine grid: stop {1, 1.5, 2} ATR × target {2.5, 3, 4, 5}; buffer {0…1.5}; level-trailing exit (stop ratchets to each cleared pivot − 0.5/1 ATR, H = 250).
  - Hybrid: bank f ∈ {0.5, 0.7} at T1 ∈ {2, 3} ATR, runner to breakeven, then level-trail.
  - Regime gate: Kaufman ER24 < thr (0.25–0.40, chosen in-sample).
- **Results:**
  - A level with 5 prior bounces breaks only 14% (holds 86%); fresh levels break 57%.
  - Breadth OOS meanR "thin +0.09".
  - Hybrid: the tail lives in crypto (+85R); pure trailing has median R −1.
  - Regime: AUDNZD wins, EURGBP/EURCHF lose when trending.
  - why_weak: the loss is on the path (whipsaw) vs the destination.
  - Synthetic test: memoryless control expected flat.
- **Lookahead:** touches resolved by neither break nor bounce within 24 bars are dropped. Event inclusion therefore depends on the future, a selection bias. Plus the cost unit bug.

### D2 `pivot-level-reversal-asymmetric`
- **File:** `experiment_level_reversal.py`.
- **Rule:** fresh touch within 0.15%; fade at the close; stop {0.3, 0.5, 1.0} ATR beyond the level; target R ∈ {2, 3, 5} × stop; H = 48.
- **Results:** levels hold ~47%.

### D3 `level-breakout` / `retest` / `non-naive` / `probability`
- **Files:** `experiment_level_breakout.py`, `experiment_break_retest.py`, `experiment_break_nonnaive.py`, `experiment_break_probability.py`, `experiment_break_magnitude.py`, `experiment_break_fatigue.py`, `experiment_orderflow_proxy.py`, `experiment_levels_mc_reach.py`.
- **Rules (pivot level, close beyond lvl × (1 ± 0.001)):**
  - Trade with the break (also a fade control): stop {0.5, 1, 1.5} ATR, R {2, 3, 5}, H = 48.
  - Retest: after the break, enter at the close when price returns within {0.5, 0.75} ATR of the level within 48 bars; stop {0.5, 1} ATR; target {3, 4, 5}R.
  - Non-naive modes:
    - naive: stop 0.75, target 2
    - wide: stop 2–3 ATR, target 3–4
    - reclaim: retest within 0.5 ATR, then a close ≥ 0.3 ATR beyond → enter; stop = max(stop ATR, beyond the retest extreme)
    - strength: break-bar range ≥ 1 ATR and close on the right side of SMA20
  - Candle confirmation (bull/bear engulfing, hammer, shooting star at the break bar) and an LGBM meta-model.
  - Order-flow proxies (crypto): volume z48, volume-profile node at the level (400 bars, 50 bins) as HVN/LVN, CMF20, OBV slope, VWAP48, absorption.
  - MC reach: an MC ensemble at the break gives median/p90 MFE in ATR.
- **Results:** breaks are marginal (median continuation +3 ATR, but median MAE −1.5 ATR comes first); random baseline −0.11R; OF baseline ~−0.18R; levels break 52%.

### D4 `clustered-ML-levels`
- **Files:** `experiment_level_cluster.py`, `experiment_reversal_ml_levels.py`, `experiment_knn_level_core.py`, `prototype_level_comparison.py`, `prototype_consolidation_base.py`.
- **Rule:**
  - KMeans (K = 6) / MeanShift (bandwidth = range/8) / DBSCAN (eps .3 sd, min 20) / Agglomerative (6) on the trailing 1000 closes, refit every 200.
  - Fade at a fresh touch within 0.15%: symmetric 1.5 ATR hold test; asymmetric stop 0.5 ATR, target 3R.
  - LGBM regressor of the forward-48 high → short when price is within 0.3 ATR of the predicted top.
  - kNN density peaks vs an expert mark.
- **Results:** hold ~0.48 for every method.

### D5 `impulse-flip-key-levels`
- **Files:** `impulse_verify.py`, `impulse_verify2.py`, `impulse_verify3.py`, `impulse_africa.py`, `bias_level_entry.py`.
- **Level:**
  - v1: impulsive candle body ≥ max(1.0 ATR, 1.5 × median body20).
  - v2: same-colour run ≥ 2 bars, \|c_end − o_start\| ≥ 1.5 ATR, counter-pullback ≤ 50%.
  - Level = midpoint of the impulse origin and an earlier opposite impulse terminal within 0.5 ATR.
  - Strength: touches (bodies within 0.5 ATR over the prior 30 bars) ≥ 3 / ≥ 8, engulfing in the prior 2 bars, sweep (wick within 0.3 ATR).
- **Test:** first return within 0.5 ATR after ≥ 3 bars; bounce = 0.5 ATR away vs through; H = 12; random-level control.
- **bias_level_entry:** with a TSMOM bias, enter within 5 days on a pullback within 0.5 ATR of a prior impulse level vs market entry vs a 3% dip vs a random level; hold 10 days.
- **Results:** FX shows no edge; African equities +0.117 vs control (1 of 7 families).

### D6 `alt-level-sources`
- **Files:** `level_sources.py`, `level_reframe.py`, `level_vol.py`, `experiment_round_number_reaction.py`.
- **Sources:**
  - Volume POC: 30-bin close histogram weighted by volume over 250 bars, every 25 bars.
  - Round grid at 10^(round(log10 median) − 2).
  - Prior-day H/L/C.
  - Floor pivots: PP = (H+L+C)/3, R1 = 2PP − L, S1 = 2PP − H, R2 = PP + (H − L), S2 = PP − (H − L).
- **Reframes:** momentum (sign of 30-bar return) with support within 0.5 ATR below; magnet when a single level is 1–3 ATR away; vol near (< 0.5 ATR) vs far (> 2 ATR).
- **Round-number wick test:** step = closest of {mag/10, mag/20, mag/2, mag, 2·mag} to 1% of price; touch within 10 bp.
- **Lookahead:** the round grid uses the full-sample min/max.

### D7 `nds-0.86-retrace` and `swing-distances`
- **Files:** `experiment_nds_geometry.py`, `experiment_swing_distances.py`.
- **NDS rule:** ZigZag 3 ATR; continuation long at confirmation (+3 ATR off the swing low), stop = swing low − 0.1 ATR, target 1.5R, 2 bp.
- **Swing distances:** pivot k = 5 with +0.5 ATR follow-through → reach distribution in ATR (feeds retired `pullback_targets`). **Lookahead:** the pivot label uses future bars (descriptive only).

### D8 `mtf-geometry`
- **File:** `mtf_geometry.py`.
- **Meanrev rule:** 1h crypto. Daily z20 (prior day) < −2 → long (short mirror). Trigger within 24h: c > c[−1] and c > o. Stop = 12-bar swing low. Target = daily SMA20 or the 20-day extreme. Max 240h.
- **Continuation rule:** side = sign(daily 20d return); pullback c[k−1] < c[k−3] then a bullish trigger; stop swing 12/24/48h. No cost.

---

## E. Liquidity sweep, AME and range ideas (scripts)

### E1 `ame-sweep-expansion-entry`
- **Files:** `ame_entry_test.py` (crypto 1h), `fx_ame.py` (Dukascopy FX D1/H4), `experiment_ame_prod_audit.py`, `backtest.py`.
- **Rule:**
  - Range = prior L-bar high/low (L = 48 crypto, 20 D1, 42 H4), tight if width/c < 8% (5% FX).
  - SSL sweep (low < rl & close > rl) → long; BSL sweep mirror → short; hold H = 24 (10 D1, 24 H4).
  - AME entry = expansion close ≥ 1.0 ATR in the reversal direction within 3 bars; enter at that close.
  - z-exhaustion (z vs SMA100; z60 D1 / z120 H4) ≥ 2 fade, optionally waiting for a same-side sweep + 0.5 ATR follow.
- **Results:** crypto fade loses (trend); "premise alive in FX/metals". The prod audit checks sign inversion per state.

### E2 `range-traverse` (sweep one side, target the other)
- **Files:** `range_traverse.py`, `_online.py`, `_robust.py`, `_liq.py`, `_multi.py`, `_scalp.py`.
- **Rule:**
  - H4 EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, XAUUSD (Dukascopy 2019–26).
  - Range = prior L = 20 bars (14/30); require width ≤ 6 ATR14.
  - Sweep bar: low < Lo & close > Lo → long (mirror short). Entry at the sweep close; stop = sweep extreme ∓ 0.15 × bar range; target = opposite range edge.
  - MAXHOLD 120 (60/240); the time barrier marks to market.
  - Spread round trip in price: EURUSD .00008, GBPUSD .00012, USDJPY .010, USDCHF .00015, AUDUSD .00010, XAUUSD .35.
  - Meta-label features: width/ATR, sweep depth, rejection, position, 60-bar HTF trend, R:R; liquidity features (equal highs/lows, round 0.005/0.50/25, session and prior-day H/L). HGB offline; river Hoeffding online at P > 0.55/0.6, learning each outcome at resolution.
  - Scalp: H4 range swept by an H1 bar (width ≤ 10 ATR_H1); MH 480 H1 bars.
  - Multi: BTC/ETH as a control.
- **Results:** offline AUC 0.659, +0.06R net / +0.14R. **Lookahead:** none (online learner ordered by resolution time).

### E3 `sweep-reversal-long` (@NazXmi)
- **Files:** `sweep_reversal_fx.py`, `sweep_reversal_managed.py`, `sweep_reversal_cost.py`.
- **Rule:** low < min(prior 20 lows) & close > that → long at the close; stop = low − 0.15 × bar range; targets 1/2/3R, max 120 bars.
- **Managed exits (max 200):** fixed 2R; quick 1R; breakeven at +1R ride to 4R; trail 2 ATR after +1R; swing trail (after 10 bars, stop = max(stop, 10-bar low)); half at +1R then breakeven and a 2-ATR trail.
- **Results:** entry breakeven; swing trail +0.05R gross.
- **Data:** FX majors + gold H1/H4. Long side only.

### E4 `bsl-ssl-fatigue`
- **File:** `experiment_fatigue_forex.py`.
- **Rule:**
  - BSL = max(high, 50).shift1; SSL = min(low, 50).shift1. Touch when high ≥ BSL; F = 0.95F + touch.
  - DirectionalAsym: \|F_ssl − F_bsl\| ≥ rolling-500 q0.7 → sign (+ = buy).
  - SweepPredict: F_ssl ≥ q0.8 → buy; F_bsl → sell.
  - FadeSweep: an SSL touch now with F_ssl[t−1] ≥ q0.8 → buy.
  - Evaluated every 24 bars, forward 6 (v4 protocol).
- **Results:** HD FadeSweep 3/3 robust; Tier-1A includes Fat_SweepPred on HD (0.658), KEYENCE, MITSUBISHI, USOIL-flip, CFR-flip.

### E5 `event-fades`
- **Files:** `experiment_fade_graduation.py`, `experiment_fade_expectancy.py`, `experiment_fade_stop.py`, `experiment_event_direction.py`, `experiment_perceptron_ladder.py`.
- **Rule:**
  - Events (§0) faded at the event close; hold H = 5; HMM high-vol context.
  - Graduation: OOS hit > 0.52, deflated p < .05 (n_eff = n/5), n ≥ 150, and the FX control must fail.
  - fade_stop grid: stop {1.5, 2.5, 4} ATR, target {none, 2.5, 3, 4} ATR, max hold {6, 12, 24}; intrabar; one fade per cluster; 10 bp round trip.
  - Event direction: rule vs an ESN ridge on event bars, in all/low/high vol contexts, 65/35 split.
- **Results:** high-vol crypto z-extreme fades win 57–58%, but average loss −215 bps exceeds average win +162 bps.
- **Lookahead:** the ESN input standardization uses the full sample.

### E6 `attention-decay`
- **File:** `experiment_attention_decay_crypto.py`.
- **Rule:** mean volume over 5 bars / prior 5-bar mean < 0.8 AND 5-bar price change > 0 → expect a negative forward return (1/3/5/10 bars). Crypto and high-vol synthetics. Signal only (short).

### E7 `breakout-fakeout-coherence`
- **File:** `experiment_breakout_fakeout_coherence.py`.
- **Rule:** close > prior 20-bar high (or < low) on the LTF; HTF slope of EMA20 on a 5× TF (5m/1h, 15m/4h, 1h/1d). Fakeout = adverse move ≥ 0.5 ATR within 10 bars. Compares coherent vs discoherent.
- **Lookahead (possible):** the HTF slope is interpolated by HTF timestamp, so it may include a still-forming HTF bar.

---

## F. ML direction, reversal and shape models

### F1 `reversal-gbm-top-bottom`
- **Files:** `experiment_reversal_breadth.py`, `_robust.py`, `_paramsweep.py`, `_crypto_stocks.py`, `_macro.py`, `_trade.py`, `_improve.py`, `_metalabel.py`, `_drift.py`, `experiment_rf_labels.py`.
- **Rule:**
  - Features = `lab/metals_ml.causal_features`: log returns 1/3/6/12/24; vol 12/24/48 and ratio; close/EMA20; MACD and signal; boll_z20; RSI14; ATR%; range%; body ratio; range position and distance to the hi/lo over 24/48; skew/kurt 48; ac1_24; volume.
  - Target top = bar is a ±12 ITB extremum with drop ≥ max(3σ, 0.08%) within the next 12 bars (bottom mirrored).
  - LightGBM (300 trees, lr .03, 31 leaves) trained on the dev 80%; threshold = 90th percentile of dev probabilities.
  - Sealed 20%: short when P(top) ≥ thr, long when P(bot) ≥ thr; first passage ±1.5σ, H = 12, cost 3 bp, non-overlapping; random control.
  - `_improve` grid: q .90–.99, cost 0–10 bp, runner 2.5/1.0.
- **Results:** AUC 0.59–0.70 on metals, ~0.60–0.62 universal and config-robust; "real but untradeable", ~random at 3 bp; meta-labeling does not rescue it.
- **Lookahead:** σ is the full-sample 1h std (barrier width and label level).

### F2 `dxy-topbot`
- **Files:** `dxy_topbot.py`, `dxy_topbot_rigorous.py`.
- **Rule:** honest label h[t] == max(h[t : t+24]) vs the leaky centered ITB label (1%, ±12). Strategy sign(P(bot) − P(top)) × forward 24-bar return on the OOS last 30%.
- **Results:** honest daily AUC 0.62–0.68. **Lookahead:** the leaky label is explicit.

### F3 `pattern-analogues`
- **Files:** `cosine_patterns.py`, `cosine_price.py`, `pip_patterns.py`, `pip_indicators.py`, `pip_extensions.py`, `rsi_pip_robust.py`, `rates_shapes.py`, `topo_patterns.py`, `experiment_tda.py`.
- **Rules (daily crypto):**
  - Cosine kNN: W = 24 z-scored log returns (or the price path, z or min-max), K = 50 most similar TRAIN windows, predict the mean forward 5-day return, trade the sign; null = shuffled labels.
  - PIP: W = 24, M = 6 perceptually important points, z-scored; KMeans K = 24 on train; trade clusters with train \|mean fwd5\| > 1.2% (n ≥ 50) by their sign OOS; stride 5; 7 bp.
  - RSI-PIP: the same on RSI14.
  - Extensions: x positions, multiscale, H1 persistence, Markov cluster transitions.
  - TDA: Takens embedding → ripser H1 total persistence.
- **Results:** price PIP +0.53/+0.58 OOS net; RSI-PIP +0.97 (robustness grid W 18/32, M 5/7, FWD 3/10, RSI 10/21, K 16/32, edge .8/1.6%, coin holdout, vs plain RSI < 30 / > 70).

### F4 `panel-ml-direction`
- **Files:** `directional_ml4t.py`, `lstm_directional.py`, `autoencoder_factors.py`, `deprado_labels_features.py`, `triple_barrier.py`, `causal_edges.py`.
- **Rule:**
  - 13-factor library: mom5/10/21/63, rev1/5, vol21, volz, rangez, distma, rsi, skew21, kurt21.
  - Forward 5-day target; long top 20% / short bottom 20% of predictions; rank IC and DSR.
  - Models: LSTM (30-day sequences), conditional autoencoder (K = 5 latent factors).
  - Trend-scanning labels (L 5–20, maximize \|t\|); fractional differentiation; triple barrier ±PT·σ20 / vertical H.
  - DML: momentum vs confounders.
- **Results:** "direction is dead" verdicts (docstrings).

### F5 `itb-highlow-labels`
- **Files:** `experiment_forex_highlow.py`, `experiment_itb_labels.py`, `experiment_label_ideas.py`, `experiment_metals_dl.py`, `experiment_metals_tft.py`, `experiment_metals_features.py`.
- **Rule:**
  - highlow: rise ≥ T% (0.5–1.5%) before falling T × tol within H = 24; two GB models (200 trees, depth 3); score P(high) − P(low).
  - Metals TFT: 48-bar window of 28 certified features; long if P > 0.55, short if < 0.45; PT = SL = 2; cost 0.1R.
  - DL label params: 1h (1%, 12, 12), 5m (.4%, 12, 12), 1d (3%, 10, 10).
- **Results:** only "quiet" is predictable (AUC .595).

### F6 `deepalpha-audit`
- **Files:** `deepalpha_repro.py`, `_leakage_audit.py`, `_causality_check.py`, `_clean_test.py`, `_walkforward.py`, `download_mexc_*.py`.
- **Rule:** third-party LightGBM, 62 features, 3-bar up/down label on MEXC 1h (27 coins); trade long if P(up) > 0.5, hold 3 bars, cost 7–25 bp round trip.
- **Results:** claimed 69% accuracy; rsi_4h, sma_4h_ratio and momentum_4h are leaky (future data).

### F7 `sweep-direction-ml` (production AME support)
- **Files:** `experiment_sweep_direction.py`, `_training.py`, `_sequence.py`, `experiment_esn.py`, `experiment_perceptron.py`, `experiment_pi_analysis.py`, `experiment_imbalance_roc.py`, `experiment_accumulation_ml.py`, `experiment_unsupervised_accumulation.py`, `experiment_method_comparison.py`, `train_models.py`, `train_sweep_predictor.py`.
- **Rule:** in an AME accumulation, which pool (range edge) is swept first within 20–24 bars. Features: fatigue, pool counts and distances, OFI = 2·CLV − 1 and its rate of change, range width, CISD, time encodings.
- **Results:**
  - Hand-made 7-factor formula 21–44% / 52–55%.
  - XGBoost 65.9% → tuned 0.713; RF 0.700; MLP 0.694; perceptron baseline ~77% cited.
  - Gates: ≥ 58% on a disjoint window, ≥ 3 features, ≥ 50% per symbol.
- **Accumulation detectors compared:**
  - Percentile box (30 bars: 90th/10th pct, width < 3%, > 60% inside, ≥ 8 bars).
  - BB squeeze (BW < 30% of the prior-10 average).
  - ATR contraction (< 0.7).
  - Std of returns below the 20th percentile.
  - Hurst R/S 20 < 0.45.
  - Shannon entropy < 2 bits.
  - Darvas box (width < 5%).
  - S/R cluster (≥ 3 touches within 0.2%, 50 bars).
- **Data:** Mongo production analytics plus OHLC.

---

## G. Regime, HMM and "physics" signal stacks (the v4–v9 signal survey)

### G1 `v4-cross-model-stack`
- **Files:** `experiment_model_predictiveness.py` (signal definitions), `experiment_cross_model_v4_full.py`, `experiment_v4_oos.py`, `experiment_v4_walkforward.py`, `experiment_v4_ensemble.py`, `experiment_v4_horizons.py`, `experiment_v5_regime_conditional.py`, `experiment_v5_regime_walkforward.py`, `experiment_v6_oos_sanity.py`, `experiment_japan_*.py`, `experiment_asia_multiregion.py`, `experiment_multiregion_oos_sanity.py`, `experiment_v9_*.py`, `experiment_tier1b_oos_audit.py`, `experiment_gate_validation.py`, `experiment_failure_diagnostic.py`, `experiment_denoiser_comparison.py`.
- **Setup:** 1h; 100-bar window; evaluated every 24 bars; PnL = sign × fwd-6 return. Primitives live in `lab/sage_features`.
- **Signals:**
  - AME / Bjorgum / ZMA analyzer BUY/SELL.
  - Fisher ≥ 1.5 SELL / ≤ −1.5 BUY.
  - BOCPD changepoint prob ≥ 0.01 → fade the 20-bar slope.
  - Crossover with ess_violation > 0 → fade the 20-bar slope.
  - Betti0 trend leaving "stable" → rising +1 / dropping −1.
  - Ising transition imminent → fade the magnetization sign.
  - Hurst(100): > 0.55 follow the 20-bar slope; < 0.45 fade it.
  - PermEnt (order 4) norm < 0.92 → follow the 10-bar slope.
  - Visgraph last degree ≥ 90th percentile of the last 100 → fade the 5-bar slope.
  - SoC α < 2 → fade the 10-bar slope.
  - SpecEnt < 0.9 → follow.
  - Tsallis (q = 2) below its 100 median → follow.
  - Lyapunov ≥ 0.045 → fade.
  - Curie-Weiss: ordering & \|m\| > .1 follow m; disordering fade m.
- **v5 regimes:** HIVOL when ATR50/close ≥ median; TRENDING when ADX50 ≥ 25.
- **Ensembles:** majority / signed sum / all-agree over the top-3 per instrument.
- **Gates (gate_validation):** ac1 ≤ 0.02; trend share ≤ 50% (20-bar slopes with R² > 0.5); no regime break (\|z vs 200 mean\| > 5 then back < 1 within 200).
- **Results:**
  - 73% of pairs survive only 1/3 windows; v5 has 124/309 deployable cells (single split); majority vote +8–13 pp hit vs the best single signal.
  - Tier-1A OOS test hits: AAPL Omori .610; HD Fat_SweepPred .658; USOIL Fat_SweepPred-flip .618; TOYOTA AME .606; MUFG MaxwellCurl .578; SOFTBANK Hurst .577 / Tsallis .625; KEYENCE Omori .592 / FatSweep .594; MITSUBISHI DirAsym .594 / FatSweep .615; SONY Hurst-flip .653; MIZUHO MaxwellCurl .590; HITACHI Omori .594; INFY Hurst .561; TCS MaxwellCurl-flip .566; ICICI SpecEnt-flip .686 / Tsallis-flip .615; HDFC Omori .612; XAGUSD Hurst-flip .583; NVDA MaxwellCurl .590; CFR FatSweep-flip .632; COMI Fisher .733; ETH Hurst .609.
  - HK and RELIANCE fail.
- **Lookahead/overfit:** heavy multiple testing; per-instrument flip selection; some thresholds use expanding/rolling quantiles (OK).

### G2 `papers-2024-signals`
- **Files:** `experiment_papers_2024_v1.py`, `experiment_papers_2024_v2_overlooked.py`.
- **Rules (LOOKBACK 200, STEP 24):**
  - HVG first-passage θ: < 0.6 fade the 10-bar slope, > 1.4 follow.
  - H1 loops (Takens m = 3, 100 log returns) ≥ rolling p90 → fade.
  - POT GPD ξ on negative returns above the 95th percentile ≥ p90 → fade.
  - DHVG KL(in‖out) ≥ p90 → follow.
  - Complexity-entropy (m = 4, 128 bars): H ≤ p25 & C_JS ≥ p75 → follow.
  - Omori p: > median + 0.5 sd fade, < median − 0.5 sd follow.
  - RQA LAM ≥ p75 → follow.
  - LZ76 of sign(r) ≤ p25 → follow.
- **Results:** AUDUSD H1 Loops DEPLOY; DHVG FLIP; RQA FLIP 3/3.
- **Lookahead bug in Omori:** the aftershock window `abs_r[recent_main+1 : recent_main+49]` extends up to 48 bars past the current bar.

### G3 `field-equation-signals`
- **Files:** `experiment_field_equations_forex.py`, `experiment_field_equations.py`; retired `sage_shared/field_equations.py`.
- **Rules:**
  - Damped oscillator: fit d²φ = −γ·dφ − ω²·φ on φ = c − SMA50 over 100 bars; ζ = γ/(2ω) ∈ [0.3, 1] → fade φ.
  - Maxwell curl: OFI = 2(c − l)/(h − l) − 1, B = ΔOFI, curl = SMA5(B) − SMA20(B); a zero-cross in the last 24 bars → trade the new sign.
  - Phase transition: criticality = 1/(\|lag-1 autocorr\| + .01) ≥ p90(500) → follow.
  - Wave dispersion: CV of \|velocity\| of SMA 5/10/20/50/100 ≤ p20 → follow.
  - Entropy production dS: − to + → follow.
  - RG flow ≥ p90 → follow.

### G4 `physics-rule-models`
- **Files:** `experiment_forex_physics_models.py`, `experiment_forex_physics.py`, `experiment_multi_signal_sizing.py`, `experiment_risk_sizing.py`.
- **Rules:**
  - fisher_extreme: Fisher ≥ 1.5 SELL, ≤ −1.5 BUY, forward 6.
  - pdir_extreme: follow when strength ≥ 90th percentile.
  - thermo td ≤ 25th percentile → follow pdir.
  - Betti 0 → nonzero → follow.
  - Kinetic-energy collapse (KE < 50% of its recent peak) → fade pdir.
  - Majority vote.
  - Sizing tests: flat 2/5%, Kelly full/half/quarter, optimal-f, capped martingale, anti-martingale, vol target, risk parity, DD-controlled; CDS / MSK (Σ⁻¹μ half-Kelly) across fisher EURUSD, XAUUSD and inverted USOIL.
- **Results:** fisher_extreme EURUSD 57.9% hit, 423 trades per 5000 bars.
- **Lookahead:** full-sample quantile thresholds.

### G5 `hmm-regime-direction`
- **Files:** `experiment_regime_direction.py`, `experiment_predictive_hmm.py`, `experiment_hmm_regime_suite.py`, `experiment_hmm_directional_walkforward.py`, `experiment_factorial_walkforward.py`, `experiment_esn_hmm_direction.py`, `experiment_iohmm.py`, `experiment_derf.py`, `experiment_gpss.py`, `experiment_fused_sizer.py`, `experiment_signal_rating.py`, `experiment_mc_direction_choice.py`.
- **Rules:**
  - 2-state Gaussian HMM on the trailing 600 1h returns, refit every 48; position = sign of the current state's mean.
  - Predictive versions: 1-step (post·T)·μ and the 24-step sum.
  - BSBF / DERF regime → fused vol-managed long exposure (lagged 1).
  - MC direction: block bootstrap (block 10, 3000 paths, H = 24) → drift sign or first-passage ±2σ sign.
  - Baseline: 120-bar momentum.
- **Results:** in-sample best-regime hit > 56% on JPM/GS/XAGUSD (t > 5), deemed multiple-comparison-inflated; regimes predict vol, not direction.

### G6 `reversal-theories`
- **File:** `experiment_reversal_detection.py`.
- **Theories:**
  - Kinetic-energy collapse (ke/ke[−5] < 0.4).
  - BOCPD signal or cp > 0.2 (60 bars).
  - 20-bar liquidity sweep.
  - RSI divergence (new 20-bar high with RSI < prior max − 2).
  - Topology (Betti simplifying, or persistence entropy dropping 40% over 3 bars).
  - OFI flip (SMA5 of 2CLV − 1 going from < −0.2 to > 0.3 within 3 bars).
  - MTF disagreement (SMA 5/15/60 slopes).
- **Label:** strict pivot within 1/3/5/10 bars (k = 5, ≥ 1 ATR follow-through). The label is lookahead by design.
- **Related:** `experiment_topology_lead_time.py`; `experiment_momentum_filter_compare.py` (EMA vs HMA vs CISD fusion for ZMA's "Weakening" label).

---

## H. Macro and cross-asset (mostly signal-only)

| ID | Files | Definition (key params) | Results | Data |
|---|---|---|---|---|
| `dxy-factor-hunt` | `dxy_factors.py`, `dxy_fxvol.py`, `dxy_ratediff.py`, `dxy_xasset.py`, `cot_dxy.py` | IC/AUC of: IRX 252-day percentile; ΔTNX5; TNX pct60; curve TNX − IRX; ΔlogVIX5; DXY mom20/60; DXY z60; gold mom60; month. Parkinson-20 vol of 6E/6B/6J and the weighted composite (EUR .576, JPY .136, GBP .119). Rate differentials diff10 = US10Y − weighted(DE/JP/GB 10Y), diff2 = US2Y − DE2Y. log(HYG/LQD) Δ20; log(HG/GC) Δ60; DBC 60; MOVE percentile; DXY z252. COT non-commercial net z104 (lagged 1 extra week), contrarian decile 4-week bet. HGB walk-forward 60/40 vs shuffle / circular-shift null. | "DXY efficient / mirage killed" | yfinance, TradingView TVC, CFTC |
| `dxy-relative-equity` | `dxy_releq.py` | Long DXY monthly when log(SPY/EFA, VEU or ACWX) over 3/6/12 months > 0. | Monthly IC +0.077, the strongest DXY factor | monthly ETFs |
| `evz` | `evz_dollar_vol.py`, `evz_tails.py` | EVZ 252-day percentile deciles → forward 20-day EURUSD realized vol, max move, EVZ +40% probability, P(\|day\| > 1.5%). | — | ^EVZ, EURUSD |
| `vix-direction` | `vix_direction.py`, `vix_models.py`, `tv_vix.py` | Next-period VIX/VVIX up from level percentile, z, mom5, VIX/VIX3M, SPX return (HGB / LGB / RF / river). | VVIX weekly AUC 0.70 | yfinance / TradingView |
| `vix-fx` | `vix_fx.py`, `vix_fx_robust.py` | `pos = sign(beta of pair to dVIX) × sign(VIX 120d pct − 0.5)`, shift 1, daily; robustness by period (GFC etc.). | — | daily FX + VIX |
| `vvix-gate` | `vvix_gate.py` | Weekly: hold BTC/ETH/SPX/gold unless the VVIX 52-week percentile ≥ 0.8. | — | weekly |
| `gold-real-rate-daily` | `fed_gold_edge.py`, `fed_gold_backtest.py`, `fed_gold*.py`, `real_gold_now.py`, `gold_tracker.py` | Long gold if DFII10 fell: −sign(Δreal) over 1/5/10/20 days lagged 1, or a threshold \|z60 Δreal\| > 1 / 1.5 held. OLS of the next-day gold return on yesterday's Δreal10, Δnom2, Δreal5, ΔDXY broad, Δbreakeven, ΔVIX and 5-day momentum (fit on 70%); 3 bp. | Gross Sharpe 0.71, but 59%/day turnover → ~0 at 5 bp | FRED + GC=F. Timing caveat: FRED close vs GC settle |
| `fed-usd-2y` | `fed_fx_research.py`, `fed_dxy.py` | Long broad USD the day after the 2y yield rose. | — | FRED |
| `fed-reaction-fn` | `fed_reaction.py`, `fed_benchmark.py`, `fed_agent.py` | Taylor rule, ML cut/hold/hike over 3 months vs the DGS1 − FEDFUNDS proxy; LLM agent. | — | FRED (policy prediction, not price) |
| `fx-real-rate-tracker` | `fx_realrate.py`, `fx_tracker.py` | Monthly lean = (\|rate coupling\| × Fed USD direction by base/quote role + \|risk coupling\| × VIX lean + 0.5 × sign(3-month momentum)) / weights; bullish > 0.2. Taylor gap = 0.5 + π + 0.5(π − 2) − (u − u*) − FF (implemented as 0.5·(−2(u − u*))), > 0.5 hawkish. | — | FRED/OECD |
| `cross-asset-divergence` | `cross_asset_divergence.py` | Live scanner: `risk_off = −polarity × z(lb-return vs own history)`; flag when SPX z ≥ −0.5 and ≥ 4 leads score ≥ 1 (≥ 2 = watch). Ratios VIX/VIX3M, HYG/LQD, RSP/SPY, SOX/NDX. | — | yfinance. Lookahead: z uses the full window including the current bar |
| `dispersion` / `volz-xs` | `dispersion_robust.py`, `price_stats.py`, `semivar_equities.py`, `micro_moments.py` | Crypto x-sectional dispersion: flip-short the market when z60 > 0; exposure clip(1 − 0.5z, 0, 1.5). Long top-30% / short bottom-30% volume z20. Skew30 low-minus-high. Amihud. VR(5) gate. Equities: semivariance signed = (RS+ − RS−)/(RS+ + RS−) over 22 days, long good / short bad. | Dispersion IC −0.029 | — |
| `lead-lag` | `btc_lead_momentum.py`, `lead_lag.py`, `macro_lead.py`, `vol_price_link.py`, `vol_lead_price.py` | BTC t−1 → alts; DXY / US10Y / TIP → BTC, ETH, gold, SPX, EURUSD; vol → next return. | Contemporaneous only | — |

---

## I. Volatility, risk and sizing

- **`har-rv` and vol targeting** (`garch_vs_har.py`, `gold_vol.py`, `gold_vol_m1.py`, `gold_rv_pull.py`, `cs_vol.py`, `experiment_volregime_sizing.py`, `vol_intraday_improve.py`, `derived_vol.py`, `synth_vol_tf.py`, `synth_vol_min.py`)
  - HAR on log RV: (RV_d, mean5, mean22) → next-day RV.
  - Gold vol target: pos = clip(median forecast / forecast vol, ≤ 3). The median uses the full sample, a mild lookahead.
  - Momentum book weight = clip(0.03/rv20.shift1, ≤ 3).
  - Low-vol anomaly: long the bottom-30% RV20 / short the top 30%.
  - Derived vol indices: c2c, hlc3, Parkinson √(mean ln(h/l)²/(4 ln 2)), hi, lo, w = 20; cross-sectional median; direction from 120-day percentile quintiles plus HGB.
  - Results: 1h gold R² 0.03 vs 0.6–0.85 elsewhere.
- **`kswin` / `topo` / `drift` gating** (`kswin_validate.py`, `kswin_vrp.py`, `drift_detect.py`, `topo_vrp.py`, `topo_patterns.py`, `experiment_cusum_vol.py`)
  - River KSWIN (α .002–.01, window 80–150, stat 30–50) on \|ret\| × 100: after a flag, cut exposure to 30% for 10 days.
  - Compared with inverse vol clip(0.03/vol20, .3, 2.5) and \|z60(vol20)\| > 2.
  - CUSUM on variance: S = max(0, S + var − base120 − 0.5·sd).
  - Topology on gold: Takens dim 3 over 30 days, H1 > 93rd percentile within 10 days → skip.
- **`gold-vrp-short-vol`** (`gold_vrp.py`, `gold_vrp_sleeve.py`, `fed_vrp_validate.py`, `kswin_vrp.py`, `topo_vrp.py`)
  - Monthly non-overlapping short straddle proxy = GVZ − next-21-day realized vol (vol points); cost 1 point.
  - Conditional: sell only if GVZ > 1.1 × trailing RV.
  - Hedged: loss capped at −L (16/12/8/6) for a premium of 2× the fair value (full-sample fair value is a lookahead); 21 offsets; DSR.
  - Needs options data.
- **`mc-risk`** (`experiment_mc_*.py`, `experiment_deriv_mc*.py`, `experiment_branching_mc.py`, `deriv_mc_scan.py`, `mc_diag.py`)
  - Engines: block bootstrap, FHS GJR-GARCH-t, + GPD/EVT, Student-t, Merton jump-diffusion, regime-switch, Boom/Crash spec.
  - Kupiec VaR calibration; triple barrier ±2σ / 24 bars. Trade only if all engines agree on the E[R] sign.
  - Meta weighting by recent calibration. Validated as a risk model, not a direction signal.
- **`xs-leverage`, `multi-signal sizing`, `risk sizing`, `HRP`, `RMT`, `PBO/CSCV`:** see A2, G4 and `validation.py` (purged K-fold with embargo).

---

## J. Deriv-synthetics-specific ideas

- **`deriv-structure-tests`** (`synth_structure.py`, `synth_intraday.py`, `synth_microstructure.py`, `synth_full.py`, `synth_mtf_direction.py`, `momentum_synth.py`, `experiment_bounce_fatigue_synthetic.py`, `experiment_synthetic_levels.py`)
  - ac1, VR(10), Hurst, fade-last-bar Sharpe, Roll spread, MR/trend by family (STEP, RANGEBREAK, CRASH/BOOM, JUMP, BULLBEAR, VOL).
  - Verdict: random walk with fat tails, no structure.
- **`boom-crash-spike-timing`** (`synth_spike_predict.py`, `synth_spike_1m.py`, `synth_boom_harvest.py`)
  - Spikes are \|r\| above a threshold; inter-spike CV and hazard; classifier P(spike within K = 50 ticks / 10 min).
  - "Ride the drip" harvest with a 2 bp spread.
  - Verdict: memoryless (flat hazard), EV ≈ 0. Data: ticks / 1m.
- **Retired nautilus Deriv strategies** (tick data, Deriv contracts; all docs say research-grade, do not trade live):
  - **VolBandScalper** (`retired/nautilus_trader/trading/strategies/vol_band_scalper.py` + `.md`)
    - Rule: tick mid; z over 60 ticks; \|z\| > 1.5 fade.
    - Contract: multiplier ×400, $1 stake, server SL $0.80 / TP $0.50.
    - Guards: last 3 ticks revert; σ60/σ600 ∈ [0.5, 2]; drift \|mean r\|/std r over 600 ticks ≤ 0.008. Cooldown 5 s, max 3; half-Kelly optional.
    - Results:
      - Sweep of 256 configs × 5 days: none met DD ≤ $15, WR ≥ 70%, PF ≥ 1.5 and every window positive.
      - Best: +$0.70/day, 5/5 windows positive, M/σ 1.31.
      - The win rate depends on end-of-day-marked opens.
      - An earlier best of +$126 flipped to +$12 / −$70 DD when the windows were shifted 2h.
  - **SwingZFader**
    - Rule: 10 s bars on R_10; z over 40 bars; fire when the peak or current \|z\| during the swing leg > 1.0 AND `Swings(period=3)` confirms a new pivot opposing the stretch.
    - Contract: ×400, SL $0.8, TP $0.5 (breakeven WR 38.5%); cooldown 3 bars, max 3.
    - Results:
      - In-sample: +$8.15, WR 81%, PF 2.57.
      - OOS −14 days: +$21.80, WR 85%, PF 3.28.
      - OOS −21 days: +$16.83, WR 89%.
      - Combined +$46.78 (+$3.12/day per $1 stakes); M/σ 2.76, best of 96 configs; 0/96 configs had 5/5 windows positive.
  - **SpikeAnticipator:** spike = \|Δp\| > 4σ of the last 200 tick changes. When ticks_since_spike / named interval (300/500/900/1000) ≥ 0.7, enter a ×200 multiplier in the spike direction (BOOM up, CRASH down); SL $0.5, TP $0.8. Contradicted by the memoryless-hazard finding.
  - **DigitDriftFader:** binary. 100-tick last-digit χ² > 16.92; P(d > 5) > 0.55 → DIGITUNDER; parity > 0.55 → opposite; 5 ticks; payout 1.95× (breakeven 51.3%).
  - **TickHighLowSniper:** binary TICKHIGH/TICKLOW over 5 ticks; sign-count score over 10 ticks, ±0.4.
  - **BasketDivergenceArb:** binary rise/fall 5m on WLDUSD. z over 600 of (WLDUSD return over 300 ticks − (−mean of AUDUSD, EURUSD, GBPUSD, XAUUSD returns)); z > 2 PUT, < −2 CALL.
- **RDBULL/RDBEAR midnight reset** (`retired/trading/strategies/rdbull_rdbear_deriv.py`, `rdbull_deriv.py`)
  - Rule: both indices reset to 1000.00 at 00:00 UTC. Enter immediately (or after a 10-point break within 60 min) in the designed direction: RDBULL CALL 1h/4h; RDBEAR PUT 1h/4h, or ONETOUCH −2%/−3% on a break > 20 points.
  - Payouts: 1.686 / 1.491 / 1.754 / 1.595 / 3.756 / 12.073. Risk 1% (0.5% on ONETOUCH).
  - Validated by a "30-session alpha study (Finding 56/57)".
  - Binary options; an OHLC proxy is possible on RDBULL/RDBEAR 1m data.
- **Empirical level-fade strategy** (`retired/sage_decision/empirical_strategy.py`, shadow mode)
  - Universe: R_10 / R_100 at 1m/3m/5m; BTC, 1HZ100V and JD50 at 3m/5m.
  - Fade (SELL into an upside / BUY into a downside AME key level) at the closest level 0.5–2.0 ATR away; cluster touches ≥ 3; not an S/R-flip.
  - SL = level edge ± 0.3 ATR.
  - Note: the very nearest level (≤ 0.5 ATR) breaks more often.

---

## K. Retired production peers (`lab/retired/`), OHLC-implementable

### K1 `ame-peer` (`retired/ame/`, plus `ame_consolidated_2026-05-18.py` with identical code)
- **Accumulation** (lookback 60, excluding the current bar): range_high = 90th percentile of highs, range_low = 10th percentile of lows; width% = (H − L)/mid × 100. Accumulating if width < 3% & > 60% of closes inside & bars inside ≥ 8 (5 if BOCPD finds a changepoint in the back half). Confirmers: BB width ≤ 1.05 × its 20-min; entropy < 2; std10 below the 20th percentile; range ratio < 0.7.
- **liquidity_tracker** (swing ±10, close fractals ±5, 20-bar close floor/ceiling):
  - Pools = clusters of ≥ 2 pivots within 1%. Sweep patterns in priority order, all on the current bar:
    - single-bar wick past the pool with a close back
    - two- and three-candle reclaim
    - equal highs/lows (≥ 2 of the last 20 within 0.2%)
    - pin bar (wick ≥ 2 × body, touching within 0.5%)
    - previous-candle raid
    - judas swing
    - stop-hunt reversal (previous body ≥ 50% closed beyond the pool)
    - breaker block (pool count ≥ 2, retest within 0.2%)
    - body-gap volume imbalance ≥ 0.1%
    - turtle soup (new 20-bar high by < 0.5% with a bearish close → SELL)
    - mitigation block (retest within 0.3%)
    - OTE (62–79% retrace of a 30-bar impulse near a pool)
  - Several patterns approximate "open" by the previous close.
  - Fatigue: 0.95-decay touch count within 0.5%. Kramers fill = 1 − e^(−0.0014·D/(σ√20)). Sweep class by wick-past-ATR × range-ATR: hard ≥ 2, standard ≥ 0.5.
- **CISD:** flip candle against ≥ 2 prior opposite-colour candles; body/range ≥ 0.4; close beyond the previous high (bullish) / low (bearish); last 10 bars.
- **States:**
  - EXPANSION: sweep + current close in the sweep direction vs the previous close + bar range ≥ k ATR (k = 1.3 trending / 0.8 mean-reverting / 1.0 neutral) → direction.
  - LIQUIDITY_SWEPT: direction = reversal.
  - ACCUMULATING: no direction; `predict_sweep_side` uses 7–8 factors each weighted 1/7 (pool ratio, fatigue ratio, −OFI, fill ratio, OB zones beyond the range, trend ±0.7W, range position (pct − 0.5)·(−2W), Hilbert PLV phase); total > 0.05 → expect an SSL sweep → BUY.
  - PRECURSOR: TR mean8 / median30 < 0.6; fatigue ≥ 5; sweep ETA.
  - Confidence tweaks: +10 for a volume surge ≥ 1.5×; ×0.7 when the HTF is opposed (HTF map 15m→1h, 30m/1h→4h, 4h→1d).
- **Results / why retired:** the folder was retired 2026-04 with the trading stack. Audits found sweep-fade losing on crypto; hand-made sweep-side accuracy 52–55%; XGBoost 0.713.
- **Lookahead:** none at decision time (pivots only up to n − 1 − w).

### K2 `orderblocks-peer` (`retired/orderblocks/`, `retired/trading/strategies/orderblock_deriv.py`)
- **Zone:** an opposite-colour candle immediately followed by ≥ 2 same-direction candles, each with body/range ≥ 0.6, with a move ≥ 0.3%. Zone = that candle's high/low.
  - Strength: VERY_STRONG ≥ 4 candles, avg body .7, ≥ 0.6%; STRONG ≥ 3, .6, ≥ 0.45%.
  - Invalidated by a later close beyond the zone. Scan the last 50 bars.
- **FVG:** low[t−2] ≥ high[t] or high[t−2] ≤ low[t].
- **Signal:** price inside a zone AND an LTF BOS (the last 3-bar pivot high/low broken by the current high/low). MSS if it runs against the HH/HL trend of the last 8 swings.
  - Entry pattern: engulfing (body ≥ 0.5 of range) or pin (wick ≥ 2 × body).
  - "Approaching" when within 1.5–2.0 ATR.
- **Trader:** zone TFs 15m/30m/1h, entry TFs 1m/3m/5m; SL beyond the zone + 0.1%; TP = LTF swing or the displacement origin; breakeven at +1R; max 2 touches; expiry 100 bars; risk 0.5%.

### K3 `pullbacks-peer` (`retired/pullbacks/`)
- **Rule:** pivots with window 5. Trend HH+HL / LH+LL from the last two pivot highs and lows. Impulse = last swing low → high (or high → low). Retracement zones:
  - 0.1–0.618 forming
  - 0.618–0.786 golden
  - 0.786–0.886 deep
  - > 0.886 invalid
- **Setup primer:** entry at the golden-zone midpoint, SL just past 88.6%.

### K4 `breakouts-peer` (`retired/breakouts/`)
- **Channel** (60 bars): top-n highs within 0.3 ATR, ≥ 3 touches each side within 0.15 ATR, width ≥ 1.5 ATR.
- **Triangle:** linear regression through 3-bar local extremes; upper slope < 0 and lower slope > 0; width ≥ 0.5 ATR; apex projection.
- **Volume surge:** ≥ 1.5 × the 20-bar average.
- **Retest:** within 0.3 ATR inside 10 bars and a close back beyond tol → confirmed; a close back through the level → failed.

### K5 `key-levels` (`retired/key_levels/`, `retired/shared/key_levels.py`)
- **Touch clusters:** reaction points = high, low, body high, body low of each bar; clustered within 0.1% of price; ≥ 6 touches (dynamic: 75th percentile of cluster counts, clamped). Strength MODERATE 6–9, STRONG 10–14, VERY_STRONG 15+. Must sit on a structural anchor (swing, range edge, FVG).
- **Annotations and alternatives:** pin/engulf rejection; volume-profile POC/VAH/VAL; Fibonacci levels; topological (H0) levels; BOCPD changepoint levels; multi-TF levels.
- **FPC:** pivot window max(5, period/7); Catalan exhaustion; projected turns at 1:1, 0.618 and 1.618 of the average amplitude.
- **Triggers:**
  - rejection: engulf/pin at a touched level within ±0.1 ATR
  - break: cross with ≥ 0.1 ATR follow-through
  - confluence: ≥ 2 kinds within 0.2 ATR and within 2 ATR of price
  - new cluster: within 5 bars
  - proximity: within 0.5 ATR
- **Fatigue:** decay touch count at the recent swing high/low.

### K6 `zma-zscore-momentum` (`retired/sage_zma/`)
- **z:** period 50; attention z = (last − weighted mean)/weighted std, weights = softmax(\|pct changes\|) in the window (or a plain rolling z). Thresholds strong/weak = 85th/65th percentile of \|z\| over lookback 200 + period (regime: trending 90/70, mean-reverting 80/60).
- **Momentum:** cumsum split-half slope over 50 (or ROC, or EMA12/26). Label vs the median \|mom\|: Rising/Weakening Demand/Supply.
- **Recommendation matrix:**
  - z < −strong & (Rising Demand or Weakening Supply) → STRONG BUY; z < −weak → BUY DIP; z < −strong & neutral → BUY (Oversold); mirrored for sells.
  - Regime: VR > 1.2 or half-life > 15 = MOMENTUM → TREND BUY/SELL and Trend Exhaustion; VR < 0.85 or half-life < 5 = MR.
- **Chop:** 0.4·wick + 0.35·z-flips + 0.25·momentum flips. < .3 Clean, < .45 Mixed, < .6 Choppy, else Hunting (no trade).
- **Stop:** Clean: mean ± (strong + 0.5)·std. Otherwise the last-5 extreme ± (0.5 or 1) std. Soft stop: 20-bar extreme ∓ k·std (k by vol regime LOW 1.5 / MID 2.0 / HIGH 3.0).
- **TP:** structural levels; fallback mean, mean ± 1σ, mean ± 2σ. SL floor 0.3%.
- **Applicability:** VR < 1.05, \|skew\| < 1.5, excess kurtosis < 6 (jump-filtered retry).
- **Other modules:** OU half-life; ALERT/READY/FIRE timing engine; exhaustion override (TREND SELL at z < −1.5 × strong → BUY) tested in `scripts/experiment_zma_exhaustion_override.py` with gates hit ≥ 55%, Δ ≥ 0.3 ATR, ±30% replication.
- **Lab P&L test:** `experiment_mc_zma_pnl.py`: ZMA entries with a Z-native stop and +2R TP, H = 48, cost 3–6 bp on XAU/XAG/SOL. Lookahead: vol terciles use the full sample.

### K7 `sage-shared indicators` (`retired/sage_shared/`)
- **DeMark TD:** setup = 9 consecutive closes below (above) the close 4 bars earlier, recent within 30 bars; countdown = 13 closes ≤ (≥) the close 2 bars earlier.
- **Fisher transform; Shannon entropy z; BOCPD exit signal.**
- **Physics indicators:**
  - Hawkes cascade (intensity > 2× baseline)
  - Kramers fill
  - Thermodynamic difficulty
  - pdirection (> 0.1 UP)
  - Kinetic-energy collapse (< 50% of the recent peak, window 20)
  - Higuchi fractal dimension
  - RQA
- **Field equations** (G3).
- **Multi-TF gate:** HTF opposed → penalty.
- **TF consensus:** softmax over \|z\| × hierarchy weight, blended 0.4 z / 0.2 regime / 0.4 journal.
- **pullback_targets:** swing reach p50/p75/p95 in ATR per symbol/TF, e.g. R_100 1h 2.55/3.44/4.10; fallback 1h 3.1/4.5/5.9. Used as a TP ladder; p05 is the SL floor. Overshoot < .45 means mean-reverting, > .55 trending.
- **trade_levels:** TP ladders and SL.
- **Not OHLC-simple:** 16-dim regime embedding + kNN cross-asset (`cross_asset.py`, `regime.py`); sequence prediction.

### K8 `setup composer` / ensembles (`retired/sage_decision/`, `retired/ensemble_*.py`)
- **TAKE rule:** primary direction & confidence ≥ 65 & ≥ 1 agreeing peer & R:R to TP2 ≥ 1.75 (1.3 for jumpy symbols).
- **Primers (WATCH):** zone, range (expected sweep side), pullback (golden mid), breakout (both sides at the pattern mid).
- **Peer ensemble:** ≥ 2 of 3 peers agree; confidence = weighted mean; MoE gating by regime × symbol class.
- **Majority / weighted voting.**
- **Beam search over setups; in-context kNN retrieval over historical setups** (needs a DB).

### K9 Retired live traders (`retired/trading/`, `retired/trader_*.py`)
These mostly consume production signals.
- **Consensus trader:** ZMA multi-TF consensus with confidence ≥ 80 (capped 89), R:R ≥ 1.5, breakeven at 0.8R, trail 2 ATR, multiplier ×50. Rejects sweep conviction > 0.7 and symbols with 0% WR on ≥ 5 trades.
- **Retirement notes:**
  - "Swing BUY disabled at 13% WR on 30 trades".
  - Multiplier timeouts lost money.
  - Journal anecdotes: 30m 90% WR vs 4m 27%; post-accumulation expansion 75% WR.
  - Production execution failing 98% of the time (`backfill.py`).
- **Scalper "retracement ride"** (v1 post-sweep version retired 2026-04-15 as "too late"):
  - Rule: during AME accumulation with predicted-side conviction 0.3–0.5/0.6 and duration 10–50 bars, trade toward the predicted sweep edge when ≥ 30% of the range width remains.
  - TP 0.04% before the edge; SL beyond the 20-bar swing × 1.5; exit on a 60% reversal; 60 min max.
  - Notes: low conviction 66% WR; wide ranges 70% WR vs tight 60%.
- **Rise/fall binary** (conf ≥ 75, payout ≥ 1.5, SELL 29% WR on 7 trades), accumulator contracts, exotic DIGIT/RANGE/RUN/LOOKBACK, CCXT paper, MT5.
- **Risk:** exposure 25%, daily loss 5%, 5 losses → 30 min pause, DD throttling, correlation sizing.
- **Contextual-bandit RL gates** (Bayesian linear; trade/contract/size/SL/TP/exit).
- **strategy_tuning:** blocks hours with WR < 30%, Kelly.

---

## L. Plumbing (one line per group)

- **Data pulls:** `deriv_pull.py` (Deriv WS candles), `download_mexc_crypto.py` / `download_mexc_perp.py` (MEXC 1h + funding), `fetch_*` (TradingView 1h panels: Japan/HK/India/Africa/crypto/US IT), `fred_pull.py`, `gold_data.py` (Treasury yields + yfinance), `gold_rv_pull.py` (Dukascopy M1 → daily RV), `tv_vix.py` (TradingView WS client), `gold_refresh.sh`.
- **Import/ETL:** `import_deriv_jsonl.py`, `load_deriv_staging.py` (Mongo exports → parquet), `migrate-atlas-to-local.sh`, `backfill_journal.py`, `compute_symbol_profiles.py` (per-symbol SL buffer, TP hit rates, confidence floor, best TF from the trade journal), `seed-user.sh`, `setup.sh`, `simulate-user.sh`, `force-reanalyze.sh`.
- **Model training CLIs:** `train_models.py`, `train_sweep_predictor.py`; `backtest.py` (AME walk-forward over Mongo, confidence optimizer, A/B).
- **Validation utilities:** `validation.py` (PBO/CSCV, purged K-fold), `random_walk_control.py`, `ml4t_hrp_dsr.py`, `mc_diag.py` (freqtrade sqlite diagnosis).
- **Production signal audits** (event streams, not price rules): `analyze_pump_export.py`, `analyze_forex_pump_export.py`, `analyze_thesis_broken.py`, `experiment_pump_mechanism.py`, `experiment_orderflow_pump.py`, `experiment_deriv_signals.py`, `experiment_ame_prod_audit.py`, `experiment_boom900_setup_blockers.py`, `replay_boom900_improvements.py`, `prototype_zma_key_levels.py`, `prototype_zscore_key_levels.py`.
- **Retired plumbing:** `collectors/` (Yahoo REST, MEXC trades WS, range/tick/volume bar builders), `embeddings/` (regime embeddings), `sage_analyzer/` (queue, per-item pipeline, MTF consensus, snapshot), `sage_loggers/`, `nautilus_trader` `adapters/deriv/*`, `runtime/*` (guard, alerter, paper/live), `backtest/*` (tick history, sweeps), tests, `legacy_config.py`, `performance_tracker.py`, `notifications_trade.py`, `worker.py`, `base.py`.

---

## M. Ideas not backtestable on plain OHLC or exchange bars, and why

- **Deriv binary, digit, accumulator, ONETOUCH, lookback, range and run contracts** (DigitDriftFader, TickHighLowSniper, BasketDivergenceArb, exotic_deriv, accumulator_deriv, risefall_deriv, the RDBULL contracts): payoff-based options with payout tables and tick resolution, not spread trades. RDBULL's directional premise can be proxied on 1m OHLC.
- **Tick-level Deriv multipliers** (VolBandScalper, SwingZFader, SpikeAnticipator): need ticks and USD SL/TP semantics. They can be approximated on 1m/10s bars.
- **Gold VRP short-vol and its KSWIN/topology gates:** need options/implied vol (GVZ) and a straddle P&L model.
- **Funding carry and fade, basis, fresh-listing funding, XS carry:** need 8h funding plus mark/spot, available from exchange data but not OHLC alone.
- **COT positioning, FRED macro, Fed reaction / LLM agent, FX real-rate tracker, EVZ/VIX/VVIX/MOVE, CFTC:** external series.
- **CVD momentum and the MEXC pump order-flow test:** need taker buy volume or trade flow.
- **Production-signal audits, sweep-direction ML on Mongo analytics, AME/ZMA peer confidence, RL bandits, virtual P&L, in-context retrieval, regime-embedding kNN, sequence logger:** need the production signal DB or journal.
- **Tokenized NAV basis:** needs token and underlying prices.
- **Fed policy prediction:** not a price trade.

---

## N. Lookahead and validity flags

1. **Bounce-fade family selection bias:** touches unresolved within the next 24 bars are dropped.
2. **Cost unit bug in the level lab:** a price-fraction cost is divided by a price-unit stop, so gold, JPY pairs and crypto are undercharged.
3. **Box-edge fill on a close trigger:** Donchian, compression and frontier batches.
4. **Omori aftershock window:** reads up to 48 future bars (`experiment_papers_2024_v2_overlooked.py`).
5. **HMM Viterbi `predict()` over the full series:** `experiment_selective_strategy.py`, `experiment_funding_hmm_overlay.py`.
6. **Full-sample statistics used inside rules:**
   - σ in the reversal GBM barriers and labels
   - vol terciles in mc_zma_pnl
   - quantile thresholds in the physics models
   - real-rate gate percentile in gold_strategy2
   - beta in tokenized_momentum_robust
   - hedge fair premium in the VRP sleeve
   - median target vol in gold_vol
   - liquidity rank in funding_carry_liquid
   - persistence selection in basis_carry
   - round-number grid range
   - ESN feature standardization in event_direction
7. **Labels using future pivots** (descriptive, by design): reversal_detection, swing_distances, boom900, the momentum filter, the leaky ITB topbot label.
8. **Possible HTF leakage:** HTF slope interpolation in breakout_fakeout_coherence.
9. **Multiple testing:** the v4–v9 per-instrument DEPLOY/FLIP selection, the zoo and PIP cluster selection. Survivorship: crypto delistings, hand-picked equities.
