# Catalogue of testable trading ideas in `the source` docs and Pine files

**Coverage.** Every file in the scope was read:
- the 165 files under `docs/`, including `archive/` and `models/`;
- `README`, `PHILOSOPHY` and `TODO`;
- `indicators/*.md`;
- `bjorgum.pine`, `indicators/zmomentum_attention.pine` and `zmomentum_attention_old.pine`.

I split the files into 9 batches and merged the results here. Three batch catalogues hold more detail than fits below and are saved verbatim in my scratchpad. Their formula-level detail is cited by section where this catalogue compresses it:
- (appendix) covers ACCUMULATION…EXOTIC_CONTRACTS.
- `…/scratchpad/cat_g1.md` covers EXPERIMENT_RESULTS…ML_FORECAST.
- `…/scratchpad/cat_g5.md` covers studies L…R.

The other batches are merged in full below. Nothing in the repo was modified.

**Status key**
- **SURVIVOR**: positive and out-of-sample (OOS), net of costs or close to it.
- **WEAK**: positive but thin, in-sample, gross, or small n.
- **FAILED**: tested and negative or null. Do not re-test blindly.
- **CHARTER**: proposed only, no results.
- **SHIPPED-UNVALIDATED**: in production with no backtest.

---

## 0. Read this first: shared protocols and two lookahead bugs I found in the code

### 0.1 Cross-model / "verified signal" protocol
Used by PER_INSTRUMENT_*, OOS_V4, WALK_FORWARD_V4, REGIME_V5, SIGNAL_SWEEP_V6, JAPAN_V7, ASIA_V8, V9 and VERIFIED_LOOKUP_TIER1.

**Data.** About 5000 1h bars per instrument (TradingView). The core 17:
- FX: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, NZDUSD
- Metals: XAUUSD, XAGUSD
- USOIL, DXY
- Stocks: NVDA, AAPL, TSLA, MSFT, JPM, HD, GS

Later panels added Japan, HK, India, Africa and crypto names.

**Evaluation** (`scripts/experiment_model_predictiveness.py`):
- Every 24 bars, compute a signal in {−1, 0, +1} from the last 100 bars.
- A hit means sign(close[t+6] − close[t]) equals the signal.
- No costs, no stop, a fixed 6-bar hold.

**Direction choice and gates:**
- On the train split, DEPLOY if hit > .5 and mean > 0. FLIP if hit < .5 and mean < 0.
- OOS = 60/40 split.
- "Walk-forward 3/3" uses three sub-windows of 3000 bars at offsets 0, 1000 and 2000. **They overlap**: bars 2000–3000 sit in all three, so the windows are not independent.
- A window passes if test hit ≥ .55, Δ ≥ −15pp and n ≥ 5.
- Tier 1A additionally needs n ≥ 30 (V9 uses n ≥ 15) and Δ ≥ −5 (V9: −10).

**Signal rules** (code-confirmed; "slope" is the polyfit slope of the last k closes):

| Signal | Rule |
|---|---|
| Fisher | period 10, unsmoothed. x = 2(c−LL10)/(HH10−LL10) − 1, clipped to ±.999. F = .5·ln((1+x)/(1−x)). F ≥ 1.5 → SELL; F ≤ −1.5 → BUY. |
| BOCPD | cp_prob ≥ 0.01 (about p93) → fade slope20 |
| Lyapunov | λ ≥ .045 → fade slope10 |
| Hurst | H > .55 → follow slope20; H < .45 → fade |
| PermEnt | order 4, pe_norm < .92 → follow slope10 |
| SpecEnt | norm < .9 → follow slope10 |
| Tsallis | q = 2, below the median of its last 100 evaluations → follow slope10 |
| Visgraph | last-bar degree (last_k 50) ≥ p90 of its last 100 evaluations → fade slope5 |
| SoC | tail α < 2 → fade slope10 |
| Ising | transition_imminent → fade magnetisation |
| CurieWeiss | if \|m\| > .1: "ordering" → follow m; "disordering" → fade m |
| Betti0 | trend label leaves stable: →rising = BUY, →dropping = SELL |
| Crossover | crowded-trend crossover with ess_violation > 0 → fade slope20 |
| AME / Bjorgum / ZMA | the production analyzers |

**Fatigue family** (`experiment_fatigue_forex.py`):
- BSL = rolling 50-bar max(high) shifted 1; SSL = rolling 50-bar min(low) shifted 1.
- A touch is high ≥ BSL or low ≤ SSL.
- F = .95·F + touch, per side; asym = F_ssl − F_bsl.
- **DirAsym**: \|asym\| ≥ rolling-500 q70 → sign(asym).
- **SweepPred**: F_ssl ≥ q80 → +1; else F_bsl ≥ q80 → −1.
- **FadeSweep**: an SSL touch now with F_ssl[t−1] ≥ q80 → +1. The BSL mirror is −1.

**Field and paper signals:**
- **WaveDisp**: dispersion = std/mean of \|ΔSMA_k\|/SMA_k for k = 5, 10, 20, 50, 100. If it is ≤ rolling p20 → follow slope10.
- **EntropyProd**: Shannon entropy of 20 log-returns; when dS goes from − to + → follow slope10.
- **H1_Loops**: Takens embedding m = 3, τ = 1 on 100 log-returns; ripser H1 total persistence ≥ rolling p90 → fade slope10.
- **DHVG_KL**: KL(in‖out degree) on 100 closes ≥ p90 → follow slope10.
- **POT_Tail**: GPD ξ on negative returns above p95 over 500 bars, ξ ≥ p90 → fade slope10.
- **RQA_LAM**: m = 3, τ = 1, 200 returns, LAM ≥ p75 → follow slope10.
- **v1/v2 gate bug (doc-acknowledged):** the rolling quantile over a mostly-zero array let the gate pass everywhere. Fixed by dropping zeros before the quantile.

**⚠ Two lookahead bugs I found in the code, not flagged in any doc:**
- **MaxwellCurl** (`experiment_field_equations_forex.py::signal_maxwell_curl`):
  - OFI = 2(c−l)/(h−l) − 1, B = diff(OFI), curl = SMA5(B) − SMA20(B). It fires if the sign crossed within the last 24 bars, trading the new sign.
  - Index alignment: `cross[i−1]` uses B[i] = OFI[i+1] − OFI[i], which is **bar i+1**, inside the 6-bar forward window.
  - Every "verified" MaxwellCurl row is suspect: MUFG, MIZUHO, SMFG, TCS-flip, NVDA, DXY.
- **Omori_p** (`experiment_papers_2024_v2_overlooked.py::signal_omori`):
  - Mainshock = \|r\| > rolling p95 within the last 48 bars. The aftershock window is `abs_r[main+1 : main+49]` and is **not truncated at bar i**, so it reads up to 47 future bars.
  - p = −slope of log(cumulative exceedances / t) against log t, with exceedance threshold p80. Fade if p > median + .5·std; follow if p < median − .5·std.
  - Every Omori-p "verified" row is suspect: AAPL, MSFT, XAGUSD, HITACHI, KEYENCE, HDFC, HRHO.
- Other checks: H1_Loops, DHVG, POT, RQA, EntropyProd and the fatigue signals looked causal.
- BREAKOUT_FAKEOUT (g1 B1) aligns the HTF EMA slope with `np.interp`, which is also lookahead.
- The FIELD_EQUATIONS doc uses a centred convolution for the curl, which leaks future bars.

### 0.2 Programme-level verdicts (stated repeatedly across docs)
- Direction is near-random on 1h bars.
- Volatility, regime and excursion are predictable.
- The surviving edges are structural: cross-sectional momentum, funding carry, volatility.
- PHILOSOPHY lists as failed: range fades, SMC/ICT/CRT, about 35 candle patterns, chart patterns, ABCD, 5 harmonics, cross-asset lead-lag, stat-arb, turn prediction and a confluence FVG model.
- Deployed per PHILOSOPHY: cross-asset momentum (Sharpe .74), Kalman funding carry, RB200 fade (rule not given), live funding fade.

---

## 1. SURVIVORS: the strongest candidates

### 1.1 `xs-mom-crypto` (CROSS_SECTIONAL_MOMENTUM)
**Data.** Binance 1h USDT perps, 2022-01 to 2026-01. 57 coins, 74 point-in-time (only coins with at least 30 days of history are ranked).

**Rule:**
- Rank coins by trailing return over L hours.
- Long the top 30%, short the bottom 30%, equal-weight, dollar-neutral.
- Hold and rebalance every H hours.
- Cost 6bp per leg.

**Results:**

| L/H (hours) | Sharpe | OOS (last 40%) | Ann. return | MaxDD |
|---|---|---|---|---|
| 360/240 | 1.23 | 1.74 | +47% | −41% |
| 240/240 | 1.21 | 1.37 | — | −28% |
| 120/240 | .84 | 2.23 | — | — |
| 360/168 | 1.00 | 1.66 | — | — |

- Cost sensitivity: 1.23 at 6bp, .88 at 15bp, .50 at 25bp.
- Walk-forward thirds: [.05, 1.74, 1.90].
- Point-in-time universe, 360/240: 1.31, OOS 2.03, MaxDD −38%.

**Hardening:**
- Funding P&L: 1.31 → 1.27 (small drag). Funding is stored in the `open` column of the 8h feather file.
- **Crash filter:** cut exposure to ×0.3 when the equal-weight basket is more than 15% below its 30-day high. Sharpe .79 → 1.11, MaxDD −36% → −26%, Calmar 1.75.
  - Plateau: cuts of −15% to −20% all help.
  - Lookback 45 days is best: Sharpe 1.30, MaxDD −18%.
- Top-40 by 30-day dollar volume: 1.16, OOS 1.22.

**Failed add-ons:**
- inverse-vol weighting (1.22)
- gross market-vol gate (1.16)
- beta-neutralising (no change)
- funding-carry cross-sectional sleeve (Sharpe −.03)
- 8-period vol targeting with a 3× cap
- reactive DD brake / vol target on compounding (CAGR 27–42%, worse)

**Sizing:**
- Base volatility is 40.6%. Target 20% vol means ×0.49: +23% a year, MaxDD −13%.
- Static L = 2: +96%, MaxDD −47%. Full Kelly is 2.85, quarter Kelly .71.
- Vol targeting with ≥16-period trailing vol and a cap ≤ 2.5 lifts 1.16 → 1.33.

**Related evidence:**
- DIRECTIONAL_SWEEP / DEPRADO: momentum is causal in Double-ML (+.0143, t = 5.8); probability of backtest overfitting .34; DSR < .95.
- META_LABEL: walk-forward meta-label 0.81 → 1.08, with indicators 1.15.

**Data:** OHLCV plus funding.

### 1.2 `funding-carry-delta-neutral` (FUNDING_CARRY, FUNDING_ANATOMY §4b, DIRECTIONAL_SWEEP)
**Rule:** long spot plus short perp on coins with persistent positive funding (sign-flip rate < 8%).

**Results:**
- Naive all-coin carry: −3.9% a year, Sharpe −5.5. FAILED.
- With selection: +12% a year, Sharpe 12.3.
- Walk-forward (60-day trailing selection, reselect every 14 days): +10.1% a year, Sharpe 16.3, MaxDD −1.6%, positive every year.
- Basis-aware (Bybit mark price as the spot proxy, 14 coins, about 200 days): +11.9% a year, Sharpe 5.4, basis drift ≈ 0.

**Entry/exit variant** (fees .23% round trip):
- Enter at ≥ .03% per 8h (about 33% APR), hold 21 days: 87% win, +16% a year.
- Enter at ≥ .05%, hold 21 days: 89% win, +23%.
- With maker/BNB fees: 92–98% win, +18–41% APR.
- **Executor spec:** enter when APR ≥ 33%, hold 3–7 days, exit on normalisation, maker orders only.

**Data:** funding history plus spot and perp prices.

### 1.3 Metals volatility (GOLD_DRIVERS, OPTIONS_IV_SOURCING, NN_MODELS)
**HAR-RV forecast** on session-clean 5-minute RV (London + NY hours, opening jump removed), Dukascopy 1m data 2023–25:
- OOS R² .43 for gold, .48 for silver. Naive: .23 / .31.
- Vol-targeting overlay: gold Sharpe 2.32 → 2.72, MaxDD −10% → −6%.

**Gold VRP short-vol** (GVZ against forward RV, monthly, 2008–26):
- Sharpe .77 (range .70–.83 across 21 offsets), DSR .77.
- Worst months −32 and −27 vol points.
- With a put cap at −12 to −16 points: Sharpe unchanged, DSR .79.
- Silver (VXSLV 2011–22): .47, DSR .41.
- Needs IV data (and option prices for P&L).

**`vol-lgbm`:** forward log-RV R² .826 against HAR .799 and persistence .757. The iid control gives about 0.

### 1.4 `gold-realrate-switch` (GOLD_MEANREV, GOLD_MOMENTUM)
- Gold futures (GC=F) daily, 2008–2026, 3bp per side.
- When the real 10-year yield's 63-day trend is falling: momentum ensemble = sign of the 21/63/126/252-day returns, enter when ≥ 3 of 4 agree, exit on signal flip.
- When it is rising: mean-reversion = fade z20 (close vs the 20-day mean), exit at the mean.
- Result: Sharpe .50, DSR .72, MaxDD −28%.
- Components: momentum alone .38 (MaxDD −40%); MR alone −.12. MR is wrong in a falling-rate regime (−.37) and right in a rising one (+.14).
- A swing-trail exit is worse on gold: K = 40 gives .29.

### 1.5 Fixed-fractional / risk rules (accepted principles)
- Risk 0.5–1% (at most 2%) per trade.
- Kelly must be friction-adjusted: b_net = (avgW − φ)/(avgL + φ). At 51% with 4bp moves and φ = 2bp, Kelly is negative.

---

## 2. Cross-sectional momentum variants (other assets)
- **`beta-hedged-mom`** (TOKENIZED_STOCKS) — **SURVIVOR candidate.** Long the top half by momentum (lookback unstated; default 12-1 month, monthly) in 23 tokenized-stock underlyings, short SPY.
  - Sharpe 1.08, DSR .99, MaxDD −7%.
  - Unhedged long-top 1.58, but SPY-beta .93. Long/short .28, and −.34 on 79 stocks: FAILED.
- **`xs-mom-metals`** — FAILED. Long/short .12; equal-weight .49.
- **`xs-commodity`** — FAILED. Front-month roll artifact.
- **`xs-lowvol`** (crypto) — FAILED. Sharpe .69 but flips sign by year.
- **`xs-skew`**, **`xs-amihud`**, **`xs-short-term-reversal`** — all FAILED. Reversal breakeven is about 0.6bp against a 6bp cost.
- **`hrp-mom`** — neutral.
- **Momentum tilts** (WEAK; sizing only):
  - Negative-skew regime .87 vs .70.
  - Variance ratio > 1: .80.
  - EU session > Asia > US.
  - High VIX > low VIX.
  - Structure exit .126 vs .112.
  - FAILED: trailing / scale-out / breakeven exits; BTC-gated exits; BTC leading alts (corr −.04).
- **`mom-ts-ens` with `swing-short-exit`** (MOMENTUM_EXITS) — **SURVIVOR-ish, 1d only.**
  - Binance futures, 58 pairs, 2022–26. Lookbacks 7/14/30/60 days.
  - Longs exit on trend flip; shorts exit on close above the 10-bar swing high.
  - Freqtrade: +181%, Sharpe .81 (trend-flip-only exit .40). DD about 72% leveraged.
  - Every 4h variant loses −70% to −83%.
- **`donchian-breakout`** in trend on crypto and metals: about +0.14R. Compression box breakout +.14 to +.23R (LABEL_CATALOG); the "quiet" gate adds nothing. The NDS retrace-continuation is the same edge (its +6.45R was lookahead). WEAK.
- **`mom-metalabel`** (META_LABEL, INDICATOR_ZOO):
  - Walk-forward, refit every 63 days: .81 → 1.08; with 12 price + 12 indicator features, 1.15 (DSR .85).
  - Frozen model FAILED. Online Hoeffding tree .85. Online logistic FAILED.
- **`real-rate-momentum-gold`** (GOLD_DRIVERS) — DECAYED/FAILED.
  - Rule: long gold when the real 10-year yield fell yesterday. Gross Sharpe .71 (shuffled control .08); net .28 at 3bp; DSR .854.
  - 10-day / \|z\| > 1 version: net .42, DSR .40.
  - 2023–25 negative. Multi-factor next-day OLS: net −.27.

---

## 3. Funding / crypto structure
- **`funding-fade-decomposition`** (FUNDING_ANATOMY). Exit used throughout: ROI target decaying 2.5% → 0 over 48h, 5% stop, trailing stop.
  - **A**, short everything: n = 79,319, 73.5% win, PF 1.17. This is the exit plus carry, not skill.
  - **B**, crowded funding (≥ p90, or APR ≥ 50%, or z ≥ 2): PF 1.22.
  - **C**, crowded plus a +50% 24h pump (exhaustion fade): n = 89, +2.43% per trade, PF 2.90.
  - **D**, leader filter (BTC and ETH funding z ≥ 2): n = 1457, PF 1.51.
  - 3-state BTC-vol HMM gate excluding "normal": PF 1.26, DD −7.1 → −5.5R.
  - Meta-label: PF 1.34 → 1.14 (FAILED).
  - Live SelectiveFundingFade: −3.37%.
  - Double-ML (DEPRADO): the fade's sign flips once confounders are controlled, so it is associational.
  - Funding as a direction feature: AUC .53 (FAILED).
- **CRYPTO_ALPHA_DESIGN recipes** — CHARTER/SHIPPED-UNVALIDATED (g0 H1–H6):
  - funding ≥ p90 of own 30 days or APR ≥ 50% → SELL; ≤ p10 or ≤ −25% → BUY
  - cross-sectional top/bottom 5% APR
  - listing < 72h and APR ≤ −100% → BUY
  - funding sign flip → trade against the latest sign
  - hot listing < 12h → BUY
  - volume z ≥ 2 with \|Δp\| < 1.5% → BUY
- **`fresh-listing-fade`** (TOKENIZED_STOCKS): short a new perp on days 5–7, hold 14–30 days.
  - +8%, 70% win (n = 44).
  - First-week pump > 30%: +21.7%. Mild 0–30% pump: −16.6%.
  - 2022–23 −16.3%, 2024–26 +32.9%. Regime-dependent, WEAK.
- **EDGE_MINTER graveyard** — all FAILED:
  - fade-the-pump (5 variants); dump-continuation intraday
  - trend-follow short with funding "FUEL"
  - breakout long (+2.55 over 148 days, −2.2 over 588)
  - breakout scalp
  - trailing-Sharpe self gate
  - per-coin graduation (rank correlation .04)
- **`crypto-attention-decay-short`** (EXPERIMENT_RESULTS Exp 13) — WEAK, tiny n.
  - Rule: mean volume of the last 5 bars / prior 5 < .8 AND 5-bar Δclose > 0 → SHORT, hold 5.
  - Delta −.151%, 58% win; on 1h about 13 fires per symbol.
  - The later vol-rollover variant (new 12-bar close high on falling volume) FAILED the FX control (HMM §8.14).
- **`stock-perp-weekend-snap`** (STOCK_PERP_FILTER): MEXC *STOCK perps drift on weekends and snap 2–5% at Monday 13:30 UTC. Observation only. Suggested gate: trade only during US cash hours. Needs perp and cash data.
- **DEEPALPHA audit** — FAILED. The 68% accuracy came from leaky 4h features; clean accuracy .501, −.20% net. The truncate-and-recompute causality test is the lesson.
- **Directional sweep (DIRECTIONAL_SWEEP)**, binance 42 coins, decile long/short:
  - GBM .35; LSTM −.66; conditional autoencoder .47; triple-barrier −.42; trend-scan .86 (DSR .65); fracdiff false positive.
  - PCA stat-arb −.90. **All FAILED.**
- **`pairs-coint`** — WEAK.
  - Engle-Granger on 60% train, fixed β, fade \|z\| > 2, exit < .5.
  - OOS Sharpe 1.11; Kalman β plus re-selection .63 (and the control wins); robust version .32.
- **Pump scanner:**
  - MEXC 15m alerts FAILED (49%).
  - By asset class (1 week): NASDAQ alerts 76% at +2h (dumps 86%); OANDA inverse 61% (untested). WEAK.

---

## 4. Event-conditional fades (sweeps, z-extremes): the main falsification story

**`sweep-fade-highvol-crypto`** (HMM_REGIME_SUITE §8.13–8.18; LIQUIDITY_PRECISION §4–13) — **FAILED OOS.**
- Event: the bar's wick pokes beyond the prior 24-bar high/low but the close is back inside. Fade it.
- z-extreme event: \|c − SMA24\|/std24 > 2, fade.
- Gate: realised vol (std of 12 log-returns) > rolling-500 p66.
- In-lab (19 coins, 7 months): hit .577–.583.
- Stop 2.5 ATR, target 4 ATR, 24-bar hold: Sharpe 2.50 (best of a 16-cell grid).
- **Freqtrade 3 years, 21 pairs, 10bp fees plus funding: −98%, PF .84.** Both sides lose.
- Variants:

| Variant | PF | Return |
|---|---|---|
| Trend-aligned (EMA50/200) | .72 | −94% |
| Counter-trend | .70 | — |
| 5m bars | .38 | — |
| 1m bars | .40 | — |
| Maker fees | .60 | — |

- Entry triggers swapped in (all about 46% win):

| Trigger | Rule | PF |
|---|---|---|
| RSI cross | crosses 40/60 | .69 |
| Donchian | 20-bar | .60 |
| EMA20 touch | — | .54 |

**`ame-liquidity-swept-inverted`** (AME_AUDIT) — WEAK, gross only.
- AME's emitted direction loses: 46.8%, −22bp, t = −2.07.
- Inverted, fading the sweep: 52.3%, +20.9bp gross.
- NYSE 15m looks better than crypto.

**`level-break` family** (REVERSAL_AND_LEVELS; forex, metals and crypto 1h, 70–215k events, 2bp) — all FAILED:
- Pivot fade (hold about .48).
- Clustering finders.
- ML-predicted top.
- Meta-label.
- Breakout with the break: −.14 to −.51R.
- Fade the break: −.07 to −.36R.
- Break-retest entry: −.20 to −.48R.
- Wide stop (3/4 ATR): −.109R against a random control of −.155R.
- Candle confirmation at the break: −.221R vs −.179R for all breaks.
- GBM P(break): AUC .512.
- Fatigue fact: P(break) by touch number is .578 / .566 / .566 / .563 / .561 / .534. More touches make a level *stronger*.
- After a break: median continuation 3.05 ATR, P(≥ 2 ATR) 66%, but median MAE −1.52 ATR comes first.

**`proven-level-fade`** (PROVEN_LEVEL_FADE) — FAILED.
- Rule: 5-bar swing levels; fade a touch after ≥ 4 prior bounces (bounce = 1.5 ATR away before any close beyond). Limit entry .5 ATR deeper, stop 1 ATR, target 3 ATR, intrabar barriers.
- Sealed OOS +.092R (20% win), n = 7979, mostly forex crosses (AUDNZD +1.49R).
- The close-only +.266R was an artifact. The bounce-fatigue decline also appears on constant-vol synthetic data (an artifact).

**`impulse/OB/flip levels`** (IMPULSE_LEVELS) — FAILED.
- Respect rate .626 vs a random-level control .619, across all markets.
- Also failed against random: POC (.585 vs .615), round numbers, PDH/PDL/PDC, floor pivots.
- Levels as magnet: .448. Levels as entry timing: worse than market.
- Asymmetric drift finding: waiting for a rally helps shorts (+.98% vs +.30%); waiting for a dip hurts longs.

**`candle-patterns`** (CANDLE_PATTERNS; H = 3 bars, 4bp, 70/30, R_100 control). The textbook direction is backwards:
- Fading 1–2 bar patterns (hammer, engulfing, strong close) wins .13–.21 ATR per 3 bars in crypto and FX (t = 2.6–8).
- Big 3-bar moves (> 2 ATR) continue in FX (fading them: −.20).
- Indices: bearish patterns fail (bear engulf −.35, 3-bar down streak −.29), i.e. buy the dip.
- TSI, Fibonacci retracements and Bjorgum pivot S/R all FAILED against random.
- Squeeze (ATR now < 0.7 × ATR 20 bars ago) leads to range expansion 1.13–1.19× vs 1.04× in the control. This is a volatility effect only.
- **WEAK edges (pre-cost-scale), useful only as features.**

**CRT/SMC suite** (CRT_SMC) — all FAILED net of costs and OOS:
- CRT core (bar i+1 sweeps bar i's low and closes back inside; stop at the swept extreme; target the opposite end): about 0R.
- Daily FX fade-of-CRT: +.17 / +.24R (an artifact of trend).
- The MSS "85% win" was a target-behind-entry bug.
- v2 crypto: −.04R OOS.
- VP-edge fade (POC target): −.237R, worse than control.
- Full zmomentum confluence: n collapses 589 → 13.
- TC2021 two-candle continuation (with VWAP, RSI 50–75, volume surge, 2R target): crypto −.002R; indices +.013R OOS (n = 476).
- AlgoVision midnight filter: −.30R.

**`fisher_extreme`** (FOREX_ML_RESULTS, ALPHA_DECAY, THIN_EDGE, SIGNAL_DIRECTION) — WEAK, decaying.
- EURUSD 1h, 423 trades: 57.9% hit, +.034% per trade at 6 bars, gross.
- Tertiles 55.3 / 66.0 / **52.5**% (decaying).
- By session: Asia 54%, London 59.6%, overlap 54.7%, NY 59.5%, late 63.6%. Proposed gate: hours 7–12 and 16–23 UTC.
- \|F\| quartiles on EURUSD: 52 / 56 / 57 / 67%, monotonic. XAU and USOIL are not monotonic.
- Polarity is instrument-specific: USOIL is trend (47.1% revert hit, −.18%); XAU 50%.
- Decay watchdog: wr50 / wr200 < .85 → alert; < .70 → pause.
- Kalman-smoothed visgraph lifts EURUSD 57 → 83%, but the average across 9 pairs is +2pp (in-sample).

**`zscore-reversion` baselines** — FAILED broadly:
- Crypto z = (c − SMA)/std beyond ±2 → fade: 14% win, −.4R (CRT refine).
- FX crosses z48 \|z\| ≥ 2: portfolio Sharpe −.97 (MEAN_REVERSION_SCOPE).
- DXY residual stat-arb FAILED.
- Indicator-zoo MR oscillators −.13 to −.50.
- Daily-z fade with a 1h entry: PF .86.
- RSI < 30 / > 70 on daily crypto: OOS +1.02 in 2024–26, +.23 full sample. WEAK.
- PIP shape clustering: reduces to RSI MR (FAILED).

**`zma-exhaustion-skip`** (ZMA_REGIME_SWITCH) — WEAK, shipped behind a flag.
- Momentum regime is VR > 1.2 or half-life > 15. TREND BUY/SELL calls at \|z\| > 1.5 × strong are bad: −.35 ATR at h = 10 (n = 97).
- Downgrading them to WAIT passes the gates.
- Flipping them FAILED: +.61 ATR, but Gate 1 and stability missed.

---

## 5. Per-instrument "verified signal" lookups (§0.1 protocol: gross, 6-bar hit, heavy multiple testing)
All WEAK. Re-test with costs. Discount the MaxwellCurl and Omori rows (lookahead).

**Tier 1A, OOS 60/40** (VERIFIED_LOOKUP_TIER1, V7, V8, V9):

| Instrument | Signal | Direction | OOS hit (n) |
|---|---|---|---|
| AAPL | Omori⚠ | — | .610 (59) |
| HD | Fat_SweepPred | — | .658 (38) |
| TOYOTA | AME | — | .606 (66) |
| MUFG | MaxwellCurl⚠ | — | .578 (83) |
| MIZUHO | MaxwellCurl⚠ | — | .590 (83) |
| HITACHI | Omori⚠ | — | .594 (64) |
| KEYENCE | Omori⚠ | — | .592 (71) |
| KEYENCE | Fat_SweepPred | — | .594 (32) |
| MITSUBISHI | Fat_DirAsym | — | .594 (32) |
| MITSUBISHI | Fat_SweepPred | — | .615 (39) |
| SOFTBANK | Hurst | — | .577 (71) |
| SOFTBANK | Tsallis | — | .625 (32) |
| SONY | Hurst | FLIP | .653 (49) |
| INFY | Hurst | — | .561 (66) |
| TCS | MaxwellCurl⚠ | FLIP | .566 (83) |
| HDFC | Omori⚠ | — | .612 (67) |
| ICICI | SpecEnt | FLIP | .686 (35) |
| ICICI | Tsallis | FLIP | .615 (52) |
| USOIL | Fat_SweepPred | FLIP | .618 (34) |
| CFR | Fat_DirAsym | FLIP | .615 (26) |
| CFR | Fat_SweepPred | FLIP | .632 (38) |
| COMI | Fisher | — | .733 (15) |
| ETH | Hurst | — | .609 (64) |
| XAGUSD | Hurst | FLIP | .583 (60) |
| USOIL | AME @ LOWVOL/RANGING | — | .621 (29) |
| NVDA | MaxwellCurl⚠ | — | .590 (83) |

**Tier 2 / regime cells:**

| Instrument | Signal | Regime / direction | Hit (n) |
|---|---|---|---|
| DXY | SpecEnt | LOWVOL/RANGING | .727 (11) |
| DXY | Tsallis | LOWVOL/RANGING | .842 (19) |
| GBPUSD | PermEnt | HIVOL/RANGING, flip | .750 (12) |
| HD | Hurst | LOWVOL/RANGING, flip | .765 (17) |
| EURUSD | WaveDisp | flip | .667 (18) |
| AAPL | BOCPD | — | .643 (14) |
| TSLA | BOCPD | — | .571 (14) |
| HD | FadeSweep | — | .769 (13) |
| HD | DirAsym | — | .679 (28) |
| AUDUSD | DHVG | flip | .875 (8) |
| MUFG | H1 | — | .786 (14) |
| INFY | DHVG | — | .722 (18) |
| INFY | EntropyProd | — | .714 (14) |
| TCS | H1 | — | .688 (16) |
| HD | RQA_LAM | — | .655 (29) |
| XAUUSD | DHVG | — | .667 (9) |
| NZDUSD | POT | — | .667 (15) |

- Regime tags (REGIME_CONDITIONAL_V5): HIVOL if 50-bar ATR/close ≥ its rolling-500 median; TRENDING if 50-bar ADX ≥ 25.
- Walk-forward v4: only 3/118 pass 3/3 (BOCPD-AAPL, BOCPD-TSLA, Hurst-XAGUSD flip). v5: 5/186.
- OOS v4 overall: train hit 60.7% → test 52.1%. The models that held up: Bjorgum, Fisher, Betti0, PermEnt.
- **Ensembles** (ENSEMBLE_V4, ASIA_V8, V9): majority-of-3 lifts hit 8–13pp at about ⅓ of the fires (e.g. GBPUSD 60.5 → 69%). A signed sum gives 3–7× more fires at about −2pp (INFY .627 n = 83).
- **Forward horizons** (FORWARD_HORIZONS_V4): Bjorgum-EURUSD .75 flat to 24h; ZMA-XAU .75 at 12–48h; BOCPD-stocks decay after 6h.
- **Gates FAILED:** forensic 3-rule gate (ac1 ≤ .02, trend_share ≤ 50%, no regime break). It passed 40% of the known failures, and the regime-break rule was anti-predictive.
- **Data:** OHLC only. Bjorgum, AME and ZMA require porting (see §8 for Bjorgum and ZMomentum).

---

## 6. Regime / HMM / volatility-state tools: risk only, never direction
- **HMM suite** (HMM_REGIME_SUITE), 17 instruments, 1h:
  - Production 1-D Gaussian HMM switches state 94–98% of bars on stocks and DXY. FAILED.
  - Fix: features [return, 12-bar realised vol, 12-bar range], z-scored, sticky transmat prior 1 + 50·I. Dwell rises to about 19 bars.
  - BSBF online filter (p_stay .97, negative-binomial duration with 2 phases, emission temper β .25, surprise guard): dwell 22.
  - Direction by regime: only GS survives walk-forward (+2.8pp, p .021). FX controls show *larger* spurious edges. FAILED.
  - Factorial trend chain FAILED.
  - IOHMM: hour of day drives switches (14/16).
  - DERF: doubt mass concentrates at transitions (16/16).
  - **Fused sizer** (benign belief × not-in-doubt × (1 − conflict), lagged one bar, long-only): MaxDD reduced on 16/16, mean −66%, but Sharpe rose on only 6/16. A risk tool.
  - KickScore, ESN and the MLP ladder: all FAILED for direction.
- **Other regime detectors:**
  - FAILED: jump model (k-means + jump penalty), CUSUM, TDA Betti (equal to trailing vol), Hawkes big-move (AUC .48), KSWIN drift gate (Sharpe .66 vs .68 ungated), bandit allocation.
  - **`label: quiet`** (all moves < 0.4% over the next 24 bars): AUC .595, breadth 89%. vol_expansion AUC .726. These track trailing vol and do not convert to trades.
  - Topological crypto stress (N-coin H1 persistence): 1.36× crash lead. WEAK.
- **MC risk engine** (MC_FRAMEWORK, MONTE_CARLO_ZMA):
  - 8 engines: bootstrap, FHS-GJR-GARCH-t, FHS+EVT (ξ-gated), Student-t, Merton, Variance-Gamma, regime-switching, Hawkes.
  - Kupiec-calibrated VaR: Gaussian fails at 99%; jump-diffusion and VG pass 11/12 FX pairs; a pooled 10k-path ensemble passes (95%: 3.7%, 99%: .9%).
  - Rules: size so CVaR5 equals the risk budget; put the stop beyond the MC adverse band; TP at percentiles of the MC MFE.
  - Boom/Crash stops must be **side-dependent**: Crash longs have a −31R tail vs −2R for shorts.
  - Optimal-exit tree (8 branches × depth 4): WEAK, in-model only.
  - MC side consensus FAILED.
- **Squeeze cone** (SQUEEZE_VOL): during a squeeze, size with σ = max(std over 20 bars, std over 300 bars). Exceptions fall 20% → 9–10%. A squeeze straddle (stops at the box edges) FAILED: a GARCH control beats it.

---

## 7. Sizing studies (on the EURUSD fisher_extreme stream: in-sample, gross unless noted)
- **RISK_SIZING_DESIGN, 11 methods:**

| Method | Return | MaxDD | Notes |
|---|---|---|---|
| optimal_f (Vince, grid .01–.5) | +419% | 24% | — |
| vol_target | +349% | — | — |
| kelly_full (bp − q)/b | +218% | 17% | — |
| kelly_half | +83% | — | — |
| anti_martingale (double after win, reset on loss) | +40% | 3% | best Sharpe |
| dd_controlled (4%; 2% at 10% DD; 1% at 20% DD) | +33% | — | — |
| martingale_capped (5 steps) | **−34%** | 45% | FAILED |

- **NOVEL_SIZING:**
  - FAK (friction-adjusted Kelly): +218% → +63%.
  - EDK (edge-decay Kelly, κ from the gap between 200- and 20-trade half-life win rates): +13.5%.
  - CDS correlation scaling.
  - DRS: f = f_base·√(peak/equity − 1) + floor.
  - MSK (Σ⁻¹μ with 0.5 shrinkage) FAILED, 96% DD.
- **THIN_EDGE:**
  - Tiered by \|F\| (skip Q1, Q2/Q3 at 2–3%, Q4 at 5–8%): +39.9%, MaxDD 3.8%.
  - Growth per trade ≈ edge²·payoff/2.
  - Phases 0–4 bootstrap protocol (in g6 detail above).
- **MULTI_SIGNAL_POOLING:** EURUSD_rev + XAU_rev + USOIL_trend at half-Kelly: +927% (solo +123%), but MaxDD 64%. No friction.
- **SIGNAL_QUALITY** (SHIPPED-UNVALIDATED): last-20-trades win rate < 30% → size −50%; 30–40% → −30%; > 70% → +10%.
- **TRADER:** half-Kelly from the journal clamped to .5–5%; confidence 60–100 maps linearly to ×.5–1.
- **PHILOSOPHY:** drawdown soft-cap ramps size linearly to 0 between 5% and 15% DD, with a hard stop at 15%.
- **MT5 reference:** grid / martingale is the same thing as martingale_capped (FAILED). Stop types: swing / average range / max range.

---

## 8. Indicator ports (Pine)

### 8.1 `zmomentum_attention.pine`
The old and current files are logically identical. The only difference is the `vp_enabled` default: false in the old file, true in the current one. All of the following is OHLC(V) and evaluated at bar close.

**Attention z (period 50, includes the current bar):**
- w_i = exp(\|c_i/c_{i+1} − 1\|), with the oldest bar's weight = 1.
- μ = Σw·c/Σw; σ² = Σ(w/Σw)(c − μ)²; z = (c − μ)/σ. This is almost a plain z-score.
- μ is the "Revert To" target.

**Thresholds:** strong = 85th and weak = 65th percentile (linear interpolation) of \|z\| over 200 bars including the current one. With fewer than 2 values, both are 1.5.

**Momentum (L = 7):**
- slope = linreg(100·c/c[L−1], L, 0) − linreg(…, 1).
- sc = slope now; comp = average of the slope L and 2L bars ago (if bar ≥ 3L).
- at = median of \|sc\| over 200 bars.
- sc > at: Rising Demand if sc > comp, else Weakening Demand.
- sc < −at: Rising Supply if sc < comp, else Weakening Supply.
- Otherwise Neutral.

**Recommendation, first match wins:**

| Condition | Signal |
|---|---|
| z < −S and (RD or WS) | STRONG BUY |
| z < −W and (RD or WS) | BUY DIP |
| z < −S and (N or WD) | BUY (Oversold) |
| z < −S and RS | WAIT (Falling) |
| z > S and (RS or WD) | STRONG SELL |
| z > W and (RS or WD) | SELL RALLY |
| z > S and (N or WS) | SELL (Overbought) |
| z > S and RD | WAIT (Rising) |
| otherwise | WAIT |

There are no exits. Defaults: opposite signal, cross of μ, or the turning-point stop.

**MTF consensus:**
- z and momentum on 15m, 1h, 4h, D, 5m and W; w = softmax(\|z_k\|); attended_z = Σw·z.
- Dominant momentum is that of the argmax-weight timeframe; thresholds are the 85/65th percentiles of \|attended_z\| over 200 bars.
- `request.security` with lookahead off and no [1]. In a backtest, use completed HTF bars aligned at the HTF close.

**Volume profile (200 bars, 50 bins):**
- Each bar's volume goes to the bin of its hlc3. Buy volume if close > open, otherwise sell.
- POC, buy-POC and sell-POC are the max bins.
- Value area 70%: expand from the POC toward the larger neighbour.
- Delta is computed only in the close's bin: (buy − sell)/total, with ±20 tags.
- Position = (c − VAL)/(VAH − VAL).

**VP confluence (14 ordered rules):** for example, BUY + c < HTF-POC[1] + (Δ > 20 or near buy-POC < .1·VA width) gives ✅ Strong. Alerts fire on ✅ and on divergence.

**Turning points:**
- pivots(7, 7); amplitude and swing length via EMA α = .3.
- Levels anchor ∓ {1, .618, 1.618}·amplitude, snapped to a VP node within 2·ATR14. The 1.618 level is the "stop".
- Implied trade: after a pivot high, limit buy at turn_1, stop at turn_ext, target the anchor.

**Other levels:**
- Catalan exhaustion count; damped-zigzag projection.
- Harmonic S/R at lo + {.25, .333, .5, .667, .75}·range over 200 bars.
- Compression zones: runs of ≥ 2 bars with range < .9 × the median range over 400 bars; demand if below the POC, supply if above.

**Status:** no results. CRT_SMC Findings 6–8 tested proxies of this confluence and found it FAILED (VP fade −.24R OOS; confluence shrinks n to 13).

**Data note:** Deriv volume is 0, so substitute a constant volume (TPO-style).

### 8.2 `bjorgum.pine`
Single timeframe. **Pivot confirmation lags 15 bars.**

**Inputs:** left 20, right 15, 4 zones per side, ATR30 (RMA) × .5 capped at 5% of close, pivot source Heikin-Ashi body (max/min of HA open/close).

**Zones:**
- At confirmation, zone = pivot ± half of min(ATR × .5, 5% of close).
- Highs start as resistance, lows as support. FIFO of 4 per side.
- Align step: the newest zone snaps to an overlapping older zone.

**Flip:** close > top makes the zone support (counter +1); close < bottom makes it resistance (counter −1). One counter per side, each starting at 4.

**Signals:**
- **Breakout:** pivot-high counter ↑, close = highest close of 15 bars, and every zone is support.
- **Breakdown:** the mirror.
- **False break:**
  - Bull: a counter dipped within 1–2 bars and recovered this bar, AND close was the lowest of 5 bars on one of the last 3 bars.
  - Bear: the mirror.
- **bullCheck:** no resistance break now or on the previous bar, the bar overlaps a support zone, and close > open.
- **bearCheck:** the mirror.
- Significance filters: at most 1 lower low in 10 bars (≥ 9 for highs).
- **TSI curl:** TSI(5, 25) with signal 14 (slow: 13, 25, 13). Bull when tsi rises below its signal line inside a bull touch.

**Candle patterns** come from an external library that is not in the file. Default to textbook definitions (doji ≤ 5% body; hammer ≤ 33% body).

**No stops or targets.** Default: enter at the next open, stop beyond the zone.

**Evidence:**
- Bjorgum-style pivot S/R breakout / false-break / backcheck: FAILED against a random-level null (CANDLE_PATTERNS).
- The Bjorgum zone fade holds about .48 (REVERSAL_AND_LEVELS).
- The "Bjorgum" cross-model peer looked good in-sample (EURUSD 75%, n = 16), but EURUSD failed walk-forward.

---

## 9. Deriv synthetics
- **`rdb-prereset-convergence`** (BUSINESS_PLAN, ENV_VARS) — CHARTER/UNVALIDATED.
  - Claim: RDBULL and RDBEAR reset to 1000 at 00:00 UTC.
  - Entry 23:05–23:15 UTC if \|price − 1000\| ≥ 5, side toward 1000, Rise/Fall 60 min.
  - Exit when within ±1.5 of 1000 after 45 s, abort on 10 points of drift, hard exit at 00:02.
  - Size 5%.
  - Win-rate claims are unvalidated (12 signals). The doc's CALL/PUT labels are inconsistent. Verify the reset on 1m bars first.
- **`rdb-postreset-breakout`** — CHARTER.
  - Enter in the designed direction in the first 3 minutes, or on a ±10-point break of 1000 within 60 minutes. Risk 3%.
- **`boomcrash-spike-hazard`** — CHARTER, needs ticks.
  - Spike = \|Δ\| ≥ 8–10 × ATR(1m).
  - States by ticks since the last spike: primed .7N–1.3N, overdue > 1.3N. BUY Boom / SELL Crash when primed.
  - Test the memoryless null first.
  - Related: the scalper excludes Boom/Crash; the swing trader went 0% on BOOM500.
- **Exotic contracts** (EXOTIC_CONTRACTS) — CHARTER; payouts are not in OHLC:
  - Digit skew on 500 closes, ≥ 12pp deviation (gambler's fallacy prior).
  - RANGE during accumulation (conviction ≤ .3, ≥ 15 bars, barriers ±2%, 10 min).
  - RUNHIGH/LOW (conviction ≤ .25).
  - Lookback float (conviction .35–.6).
- **SAGE_ACCUMULATION** (126 virtual positions over 2 days, in-sample):
  - Conviction > .7 wins 38%; .15–.3 wins 67%.
  - Range width ≥ 1% wins 70%.
  - Post-accumulation signals win 75% (n = 12).
  - By timeframe: 30m 90% (n = 10), 4m 27%.
  - OTC and volatility indices are better than Crash/Boom.
- **Accumulation detector** (`accum-percentile-box`; g0 D1, g2 Theme 1):
  - Window of the last 30–60 bars excluding the current bar.
  - Box = 90th-percentile high / 10th-percentile low; width < threshold (default 3%, code 8%); > 60% of closes inside; ≥ 8 bars (5 after a BOCPD changepoint).
  - Accumulation-quality XGBoost: 50% = baseline (FAILED).
- **Sweep-side prediction** (which side of the accumulation box gets swept):
  - Linear 7/8-factor model 21–44% (FAILED).
  - XGBoost 65.9% vs an always-SSL base rate of 65.6% (no edge).
  - Deriv 30m study: XGBoost .713 (depth 4, lr .01, 200 trees) vs heuristic .55 (SWEEP_DIRECTION_TRAINING).
  - These are classification accuracies, not P&L. Shipped behind a flag.
- **Key levels** (EMPIRICAL_TRADING_STRATEGY, STRUCTURAL_LEVELS_ARC):
  - A logistic break/hold classifier beats touches/(touches + 5) on 19/20 cells (about 33h of data, in-sample).
  - Rules: use levels .5–2 ATR away; skip the nearest level if < .3 ATR; stop at the cluster extreme ± .3 ATR.
  - Stop-hunt detector:
    - Pattern: bar high > level high, close ≤ level high, then within ≤ 3 bars a close < level low. The doc says "BUY"; it reads as a SELL.
    - Score 30 + …
    - Poke/confirm thresholds: synthetics .20/.40 ATR, FX .10/.20, crypto .15/.30.
  - CHARTER.
- **TRADER / CORE_PRINCIPLES rules** (SHIPPED-UNVALIDATED):
  - Confidence 80–89 is "the only profitable bucket"; BUY disabled at 13% win.
  - Breakeven at .8–1R; ATR × 2 trail; 30-minute or 1h timeout.
  - SELL only in the top 40% of the range, BUY only in the bottom 40%.
  - Multiplier tiers by confidence.
  - Kill any strategy/side/symbol with negative expectancy over 20+ trades.
  - Swing-trader post-mortem: −$623, 26% win (stops were sent as prices and dropped). The same signals on binaries won about 53%.
  - Hold-time extension (78% of timed-out trades were profitable): outcome not reported.

---

## 10. Order blocks, sweeps (A–M), CISD, pullbacks (models/*): all CHARTER/UNVALIDATED (full formulas in g2 Themes 3–6)
- **Pools:** swing levels greedily clustered within 1%; pool = cluster mean with ≥ 2 members.
- **Sweep patterns:**

| Pattern | Rule (bull; bear mirrors) |
|---|---|
| A, single bar | l < P, c > P, c > o |
| B, two candles | — |
| C, three candles | — |
| D, equal lows | within .2% |
| E, pin | wick > 2/3/4 × body |
| F, previous-candle raid | — |
| G, Judas | — |
| H, stop-hunt reversal block | — |
| I, breaker | — |
| J, body gap | — |
| K, turtle soup | 20-bar low pierced by < .5%, close back above |
| L, mitigation | — |
| M, OTE | in .618–.786 of the impulse |

  Literature reliability tiers only; no backtests.
- **CISD:** ≥ 2 opposite candles, then body ratio > .4 and close > prior high.
- **Order block:** last opposite candle before a displacement:
  - displacement ≥ 2 candles with average body ratio > .6, moving 1% (2 candles) / .5% (3) / .3% (4+);
  - must sit near a pool or range edge;
  - expires after 100 bars or 2 touches;
  - entry on an LTF BOS plus an engulf or pin back in the zone;
  - SL beyond the zone + max(.1%, 1.5 × average wick); TP1 at the LTF swing (50% off); breakeven at 1R.
  - Calibration only: 20 of 29 zones were noise.
- **FVG:** low[t−2] ≥ high[t] (bearish) and the mirror. Hidden supply/demand pause candles.
- **Pullback:** depth .25–.80 with level confluence, scored +3 OB / +2 sweep or POC / +1 Fib, EMA or VWAP. OB + Fib "OTE" routing.
- **Learned golden zone** = median retracement depth of winning pullbacks (V75 52.3%). Fit on train only.
- **Stops:** clamp(ATR14 × p75(lower wick/ATR), .05%, .25%) beyond the 2-bar extreme.
- **TP selection:** argmax R:R × P with P .7/.5/.3.
- **MTF hierarchy:** HTF vote sets direction; LTF agreement ≥ 70% → ×1.2, < 40% → skip.
- **Evidence elsewhere:** ICT/SMC levels, FVG POI and OB levels FAILED against random controls (§4).

---

## 11. Reversal indicators, field equations, misc features (EXPERIMENT_RESULTS etc.; g1 detail)
- All scored as F1 lift on k = 5 pivots:
  - **Betti0 topology** gives +.025–.036 F1 lift but no lead time (4.67 vs 4.73 bars). Regime feature only.
  - KE collapse: lags.
  - RSI divergence (new 20-bar high with RSI below its max − 2): about 0.
  - 20-bar sweep reversal: negative.
  - MTF disagreement: negative.
  - BOCPD and OFI flip: zero fires (untuned).
- **Field equations:** MaxwellCurl sign flipped between windows (52.9% → 44%); entropy production 45%; phase transition (lag-1 autocorrelation ≈ 0) lost its edge. All FAILED as triggers.
- **Breakout fakeout by TF coherence** (Exp 11):
  - Breakout = close beyond the 20-bar extreme; HTF = 5× timeframe EMA20 slope; fakeout = adverse ≥ .5 ATR within 10 bars.
  - Discoherent 70.2% fakeouts vs coherent 52.8%. Not replicated, and the code has lookahead.
  - CANDIDATE: re-test causally.
- **Round-number rejection** FAILED (p = .27).
- **Swing reach** (Exp 14): median 3–4 ATR, p95 6–12 ATR, lognormal. TP ladder at p50/p75/p95. Descriptive only.
- **PULLBACK_TARGET_RESEARCH:** reach-target framework (lognormal CDF, damped cosine, cubic turning point t* = (−a₂ ± √(a₂² − 3a₃a₁))/(3a₃), Ehlers sine, OU percentiles, Bachelier null). TP1/2/3 at the 50/70/85th percentiles. CHARTER.
- **REVERSAL_RESEARCH:** 7-theory formulas (KE exhaustion ratio < .3, CLV-OFI flip, MTF coherence C = \|Σw·s\|/Σw). Results are in EXPERIMENT_RESULTS above.
- **Signal-quality overlays** (FEATURES, SIGNAL_QUALITY): confidence multipliers for Kramers, TD, Hawkes, PLV, DeMark, CFAR, compression and pullback contexts, applicability gate, regime-embedding kNN. All SHIPPED-UNVALIDATED (tables in g1 I3–I8, g2 Theme 9).
- **Denoisers:** Kalman pre-smoothing helps physics signals (+2pp on average) and kills structural ones (crossover from 10 calls to 0).
- **Forex ML** (FOREX_ML):
  - High-low barrier label (+.5% before −.5% within 24 bars): EURUSD low-side AUC .695 (±.16).
  - Metals: jump bar gives .17–.20σ of 6h separation.
  - Physics-tag ML is gated. WEAK.
- **Topology / BOCPD / Z-forecast / Merton / Spectral-crash / Whale / Z-entry-timing / Key-level-forecast / Pivot-sharpness / Liquidity-fatigue / kNN-levels:** CHARTERS with formulas.
  - Spectral crash: multivariate Hawkes spectral radius; CR > .9 → halve size; CR > .95 → block entries.
  - Whale: vol_z ≥ 3; absorption vol_z ≥ 2 with range ≤ .5 ATR.
  - Z-entry timing: OU E[T] = ln(z0/z1)/θ; time stop at p95.
  - Full detail is in g1, g7 and the g6 sections above.
- **RESEARCH_PAPERS_2024_2026:** feature proposals (HVG θ, signatures, transfer entropy / Kramers-Moyal, H1 Wasserstein, ESN R² gate, POT gate, DHVG, cross-sectional variance + Moran's I, LZ76, Omori, RQA-LAM, complexity-entropy plane). Partly tested via V6 (above).

---

## 12. Instrument-specific forensic claims (LLM research narratives; unverified; mostly need non-OHLC data)
Twelve dimensions (A–L) each, plus a verdict. Only calendar and OHLC-testable fragments are listed.

| Report | OHLC/calendar-testable claims and rules |
|---|---|
| GE | Post-split: 6 of 8 earnings days closed lower despite beats; T+1..5 drift −1.9%; +.6% in the 2 sessions before BA delivery prints; Monday gap-down 58%; long Safran / short GE pair |
| HD | 6 fade/fatigue signals; gaps > .4% close by 10:30 ET 58% of the time; skip ±2 days around earnings; kill switch on mortgage rate < 5.5% |
| INFY | Disable on earnings ±1d; flatten if USDINR > ±.5%; delay if Nasdaq overnight > 1.5%; pause if 20-day Hurst > .55 or hit < 55% |
| KEYENCE | Opens > 30bp from the prior close revert ~60% of the gap by 10:30 JST; suspend on USDJPY 5-min vol > .6σ; pause if FA-basket corr < .4 |
| KMI | Monday gaps fade 60% by 11:30; −.3% at the ex-dividend open |
| SoftBank | Arm overnight move → TSE open drift (β .55–.65); 12:30 lunch reopen reverts 58% after a > 2σ morning |
| Toyota | Disable when USDJPY 30-min RV > p95; MR windows 10:30 and 14:30 JST |
| USOIL | Pause MR longs when SMA100 < SMA200; EIA-Wednesday window; OPEC Sunday gaps |
| MUFG v2 | Fade ADR-vs-Tokyo gaps > 80bp; exclude Morgan Stanley earnings days |
| Mitsubishi | USDJPY shock and basket-correlation filters |
| Echo | Non-market data (launchpad flows) |

Generic rule from the GE and KMI reports: a mean-reversion bias toward the 200/500-bar mean.

INTEL_BRIEF holds dated discretionary trades: USDMXN long, WTI short, AMAT short, ORLY 15m VWAP fade. These are single trades only (g1 K).

---

## 13. Ideas that cannot be backtested on OHLC/exchange data, and why
- **Options IV / gamma / skew:** VRP P&L, GEX walls and Vol Trigger, put skew, COIN risk reversals, implied-move edges. Need option chains / IV.
- **COT, CFTC positioning:** COT1 EA, USOIL resume rule, crowding filter.
- **Macro / rates / FRED:** Fed simulator (the market-implied 1y spread .723 beats macro .492), real-rate switch inputs (DFII10 is free on FRED), HD mortgage kill switch, FX-factor real-rate monitor, JGB kill switches.
- **Fundamentals / storage / weather:** EIA storage surprise, NOAA HDD/CDD (NatGas price-only seasonality .27 vs a null of .47, FAILED; z-score MR and oil/gas ratio FAILED).
- **News and calendars:** earnings blackouts, OPEC, BoJ, PBOC fix, MT5 news filter, pre/post-news windows.
- **Order book / tick / trade-signed volume:** VPIN, true CVD and OFI, block trades, MEXC depth imbalance, Boom/Crash tick hazard, digit contracts, Merton bipower jump labels (need intrabar data), liquidation maps (IMPULSE_LEVELS says real levels need this).
- **On-chain / social / attention:** exchange flows, launchpad escrow (Echo), Google Trends / X mentions, counter-meme, GIF sentiment.
- **Funding / OI history:** carry and fade (exchange data, but not OHLC). OI loadup is not stored.
- **Broker product payoffs:** Deriv Rise/Fall, ONETOUCH, RANGE, RUN, LOOKBACK, accumulator, multiplier tiers. RDB reset P&L.
- **House-internal outputs:** AME conviction, consensus confidence, regime embedding, RL bandits (49-dimensional), notification logs, setup corpus, XGBoost sweep artefacts, pump-scanner alert logs. Rebuildable only approximately from OHLC.
- **Undefined metrics:** `visionary_ideas.md` (85 LLM hypotheses, no index defined); K1 field-equation raw features (formulas not given).
- **Volume-dependent on Deriv / FX:** Deriv volume is 0 and FX volume is tick count, so volume-profile, OBV, absorption and Wyckoff ideas are only testable on crypto or stocks.

## 14. Files with no testable trading idea (one line each)
- `docs/README.md`: docs index.
- `studies/README.md`: studies index and promotion criteria.
- `MODULE_NAMING_CONVENTIONS.md`: Python import naming policy.
- `PEER_VS_FEATURE_PROVIDER_REFACTOR.md`: code-structure refactor proposal.
- `models/MODEL_ARCHITECTURE.md`: peer-architecture overview.
- `INTEGRATION_TESTS.md`: test-harness spec.
- `DATA_BACKFILLER.md`: Deriv backfill tool (Deriv keeps ~90 days of 30m/1h/4h and ~24h of 1m; volume is 0).
- `BYBIT_TRADFI_API_RESEARCH.md`: venue/API survey.
- `OPTIONS_IV_SOURCING.md`: IV data sources only (VRP idea in §1.3).
- `ENV_VARS.md`: configuration (strategy parameters folded into §9).
- `FEATURE_SHIPPING_PRINCIPLES.md`: Gate 1–4 governance (replicate on 60d and 90d; ≥ 3pp edge, no sign flip).
- `FORENSIC_METHODOLOGY.md`: dossier template (its gate FAILED, §5).
- `RESEARCH_FRAMEWORK.md`: Q1–Q4 epistemic template. Its seeds: round-number asymmetry and TF-coherence fakeout are testable; attention, options expiry and IV decay need other data.
- `RL_ARCHITECTURE.md`: bandit infrastructure (arms listed in §13).
- `LLM_CONCEPTS_RESEARCH.md`: mostly UX; the kNN confidence and regime-MoE thresholds are in g1.
- `LIQUIDITY_NOTIFICATION_RESEARCH.md`: mostly wording; the messy/clean post-sweep classifier is in g1.
- `CALCULUS_TOOLKIT.md`: methods only.
- `BUSINESS_PLAN.md`: fund and product plan beyond the RDB strategy.
- `CONTENT_NOTES_X_ACCOUNT.md`: social-post digest of other studies.
- `ML_OVERLAY_VERDICT.md`, `RESEARCH_SUMMARY.md`, `MC_FRAMEWORK.md`, `MC_TRADE_PIPELINE.md`: summaries of results catalogued above.
- `PHILOSOPHY.md` / `README.md` / `TODO.md`: creed, status table and backlog (darvas box, SampEn, Wyckoff, OBV, imbalance-ROC and profit checkpoints are backlog ideas; profit checkpoints FAILED in Exp 5: 67% of early exits hurt).
- `visionary_ideas.md`: not implementable.
- `ECHO_LAUNCHPAD_FORENSIC.md`: non-market data.
- `DEPRADO_METHODOLOGY.md`: methodology (PBO .34, purged CV .517).

**Bottom line for a cost-aware OHLC backtest:**
1. Highest prior: cross-sectional crypto momentum with the crash filter; delta-neutral funding carry (needs funding data); gold real-rate momentum/MR switch; 1d crypto TS-momentum with a swing exit on shorts; beta-hedged equity momentum.
2. Worth re-testing causally and net of costs: the Tier-1A per-instrument cells (§5), excluding or fixing MaxwellCurl and Omori first; fisher_extreme EURUSD with a session gate; TF-coherence breakout fakeout; inverted AME sweep.
3. Treat as closed unless new data arrives: everything level-, pattern-, SMC/CRT- or z-fade-based on its own.

---

# Appendix cat_g0.md

# Catalogue of trading ideas in 19 lab docs

Base folder: the source. I read all 19 files in full. Every idea below gets a status:
- **FAILED**: the doc reports a negative result.
- **UNVALIDATED**: proposed or deployed, but no result reported.
- **CLAIMED**: a number is reported, but it is in-sample, small, or gross of costs.

I grepped `api/api/sage/peers/ame.py` once to pin down the percentile box the docs leave vague. `ENV_VARS.md` contains a literal demo token value; I did not reproduce it.

---

## Theme A — Deriv RDBULL/RDBEAR midnight reset (calendar / structural)

### A1 `rdb-prereset-convergence`: bet on convergence to 1000 before the reset
- **Sources:** BUSINESS_PLAN.md §2.1–2.5, §6.2, §10.1–10.2, Slides 3–4, §18.6; ENV_VARS.md "Pre-reset convergence" and "Pre-reset force-close monitor".
- **Premise:** RDBULL and RDBEAR are said to reset to exactly 1000.00 at 00:00 UTC every day. RDBULL drifts up during the day and RDBEAR drifts down.
- **Entry window:** 55 to 45 minutes before midnight, i.e. 23:05–23:15 UTC (`PRE_RESET_ENTRY_START=55`, `PRE_RESET_ENTRY_END=45`).
- **Distance filter:** require |price − 1000| ≥ 5 points (`PRE_RESET_MIN_DELTA=5`).
- **Side:** toward 1000. RDBULL above 1000 → PUT. RDBEAR below 1000 → CALL.
- **Contract:** Rise/Fall, strike = entry spot, duration 60 min (`PRE_RESET_DURATION=60`), so expiry falls about 5–15 minutes after midnight.
- **Exit (force-close monitor):**
  - "Target hit" means price within 1000 ± 1.5 points (`PRE_RESET_CLOSE_TOLERANCE=1.5`).
  - After the first touch, wait 45 s, then sell early (`PRE_RESET_CLOSE_DELAY_SEC=45`).
  - Abort the wait and sell immediately if price drifts 10 points from 1000 during it (`PRE_RESET_DRIFT_ABORT_PTS=10`).
  - Hard sell 2 minutes after midnight regardless (`POST_RESET_LOCK_IN_MIN=2.0`).
  - Also sell when the contract is 55 minutes old (`PRE_RESET_EXPIRY_BUFFER_MIN=55`).
- **Sizing:** 5% of balance per trade (`PRE_RESET_RISK_PCT=5.0`). Live ramp plan: 2% → 3% after 14 days → 5% after 28 days.
- **Payouts quoted:**
  - "RDBULL CALL 1h 1.686×; RDBEAR PUT 1h 1.754×; RDBULL CALL 4h 1.491×; RDBEAR PUT 4h 1.595×"
  - "RDBEAR ONETOUCH −2% (4h) 3.756×; −3% (4h) 12.073×"
- **Results/claims:**
  - The force-close "captures ~93% of theoretical max payout, ~8pp better than selling immediately or holding to expiry."
  - EV at an assumed 90% win rate: +51.7% (RDBULL) and +57.9% (RDBEAR) per stake. Projected 5.5%/day, haircut to "2–5%/day, central 3%."
  - These are not measured. In the doc's words: "Win rate estimate is not validated… only 12 actionable signals over 48 hours… could be anywhere from 75% to 98%." The demo-validation targets (≥80% win rate, ≥2%/day, max drawdown ≤15%) have no reported outcome.
- **Data needed:** Deriv 1m OHLC (or ticks) for RDBULL and RDBEAR around 23:00–00:15 UTC, plus Deriv Rise/Fall payout quotes and early-sell quotes. Bars alone can verify the direction and the reset; they cannot verify payouts.
- **Ambiguities:**
  - The payout table labels RDBULL as **CALL** and RDBEAR as **PUT**, while the trade table says RDBULL → **PUT** and RDBEAR → **CALL**. The EV block labels "RDBULL PUT 0.686". The labels are inconsistent.
  - The text says both "2 trades/day" and "4 trades/day."
  - Faithful default: side = sign(1000 − price); payout ≈ 1.69–1.75× on stake; first check on bars that the 00:00 open is 1000.
- **Status:** UNVALIDATED.

### A2 `rdb-postreset-breakout`
- **Sources:** ENV_VARS.md "Post-reset breakout (00:00–01:00 UTC)"; BUSINESS_PLAN.md §2.5, §10.1.
- **Immediate entry** (`RESET_IMMEDIATE_ENTRY=true`): within the first 3 minutes after midnight (`RESET_IMMEDIATE_WINDOW_MIN=3`), enter in the "designed direction": RDBULL CALL (up), RDBEAR PUT (down).
- **Break entry:** after minute 3 and up to 60 minutes after midnight (`RESET_ENTRY_WINDOW_MIN=60`), enter when price is ≥10 points from the 1000 open (`RESET_BREAK_THRESHOLD=10`), in the break direction.
- **Contracts and sizing:** CALL/PUT at 3% of balance (`RESET_RISK_PCT=3.0`); ONETOUCH barrier at 1.5% (`RESET_RISK_ONETOUCH_PCT=1.5`). Barriers of −2% and −3% (4h) appear in the payout table.
- **Claim:** "1–2% daily EV." The doc also says: "assumes a directional drift after reset. This is statistical, not mechanical."
- **Data needed:** Deriv 1m OHLC for 00:00–01:00 UTC, plus payout quotes.
- **Ambiguities:** CALL/PUT duration is not stated (default 60 min). Whether the break is measured on close or tick is not stated (default: 1m close).
- **Status:** UNVALIDATED.

### A3 Risk overlay used with A1/A2 and the general trader
- **Sources:** BUSINESS_PLAN.md §6.2, §14.3, §14.4; ENV_VARS.md "Rule-based Trader."
- **Rules:**
  - Max daily loss 5% → halt for the day.
  - Max 3 consecutive losses → cool down.
  - Max 5 concurrent positions.
  - Minimum R:R 1.5.
  - Per-symbol cooldown 300 s.
  - Base risk 1.0% per trade, "Kelly-adjusted by confidence."
  - `MIN_CONFIDENCE` 60.
- **Fund-level triggers:**
  - Fund A halts at 20% drawdown from high-water mark.
  - Fund C liquidates to 50% cash at 35% drawdown.
  - Fund D: soft trigger at 15% (continue at reduced risk), hard halt at 25%.
- **Claimed drawdown:** at 75% win rate, expected 90-day max drawdown 45%; at 90% win rate, 25% (model, not measured).
- **Status:** rules only.

---

## Theme B — Deriv BOOM/CRASH spikes

### B1 `boomcrash-spike-hazard`: countdown entry on a renewal process
- **Source:** BOOM_CRASH_SPIKE_RESEARCH.md.
- **Mechanic:** BOOM<N> has up-spikes roughly every N ticks and drifts down between them. CRASH<N> is the mirror (down-spikes, drifts up).
- **Symbols:** BOOM150N, BOOM300, BOOM500, BOOM600, BOOM900, BOOM1000; CRASH50, CRASH150N, CRASH300N, CRASH500, CRASH900, CRASH1000.
- **Spike label:** |Δprice_tick| ≥ K × ATR_1m, with K = 8–10 (elsewhere "K = 10–20 probably safe"). A BOOM900 spike is typically 10–30× the 1m ATR. Validate by eye on 100 spikes per symbol.
- **Model A, empirical hazard:** Kaplan–Meier P(spike in next tick | M ticks since last spike) for M in 1..2N.
- **Model A states, by m = ticks since last spike:**
  - `post_spike`: m < 0.3N (cooldown)
  - `neutral`: 0.3N–0.7N
  - `primed`: 0.7N–1.3N (alertable)
  - `overdue`: m > 1.3N
- **Signal:** BUY on BOOM*, SELL on CRASH* when state is primed or overdue. Stop below entry. Do not trade during the spike itself.
- **Model B:** Weibull or Gamma parametric hazard, accepted if the chi-squared fit gives p > 0.05.
- **Model C:** logistic regression or XGBoost on ticks-since-spike plus micro-features: tick arrival rate, slowing drift velocity, compression of 5s-bar range, volume.
- **Model D:** CNN or boosted tree on 30s/15s/5s candles.
- **Success criteria:**
  - Primed precision > 60% on BOOM900/CRASH900 and > 70% on shorter-cadence symbols.
  - Median lead time ≥ 50 ticks (target 50–200).
  - Calibration within ±σ.
  - False-alert rate tracked.
- **Results:** none. "Parked" pending 30+ days of historical ticks; `market_ticks` has a 1-day TTL.
- **Data needed:** ticks. 1m OHLC is a crude proxy only: spikes are visible as bars with range ≫ ATR, but the tick count is lost (use bar count × ticks per bar).
- **Ambiguities:** whether the stated cadence is the true mean is untested. Note: under a memoryless (geometric) spike process the hazard is flat and "primed" carries no information. That is the null to test first.
- **Status:** UNVALIDATED (scoping).
- **Related negatives:** the scalper excluded BOOM/CRASH because "spike indices don't retrace cleanly" (CORE_TRADING_PRINCIPLES). The swing trader lost on BOOM500: 0% win rate, −$175 (SWING_TRADER_POST_MORTEM). EMPIRICAL_TRADING_STRATEGY excludes CRASH/BOOM from level trading because "jump dynamics make level detection noisy."

---

## Theme C — Deriv exotic contracts (EXOTIC_CONTRACTS.md, deployed 2026-04-16)

**Common rules for C1–C4** (EXOTIC_CONTRACTS.md "Risk", "Configuration"):
- 0.3% of balance per trade.
- Max 8 concurrent positions.
- 120 s cooldown per symbol.
- 15 s scan cycle.
- Up to 3 candidates per scan.
- Validation plan: first 30 trades per strategy. No results are reported.

### C1 `digit-frequency-skew`
- **Universe:** R_10, R_25, R_50, R_75, R_100.
- **Rule:** over the last 500 1m closes, count the last digit 0–9 (uniform = 10% each). If a digit deviates by ≥ 12% (`EXOTIC_DIGIT_MIN_EDGE=0.12`):
  - Over-represented digit (example: "7" at 22%) → DIGITOVER with barrier 6.
  - Under-represented digit (example: "3" at 2%) → DIGITUNDER with barrier 4.
- **Contract:** 5-tick duration; skip if payout < 1.5×.
- **Target:** win rate > 55%.
- **Ambiguities:**
  - "≥12% deviation" could be absolute (22% vs 10%) or relative. The example implies absolute percentage points.
  - The barrier mapping is only given by example.
  - The claim "generator internal state skews digits" is the gambler's fallacy for an i.i.d. RNG.
- **Data needed:** Deriv ticks/closes and digit-contract payouts. A null of uniform i.i.d. digits is testable on OHLC closes.
- **Status:** UNVALIDATED. Strong prior that it fails.

### C2 `range-hold` (RANGE contract)
- **Arming conditions:**
  - is_accumulating (see D1)
  - sweep conviction ≤ 0.3
  - bars_inside ≥ 15
  - price inside the range
- **Barriers:** range_high × (1 + 2%) and range_low × (1 − 2%). The 2% buffer is `EXOTIC_RANGE_BARRIER_BUFFER_PCT=0.02`.
- **Duration:** 10 min.
- **Confidence score:** 50 + bars_inside + (1 − conviction) × 30.
- **Target:** win rate > 65%.
- **Data needed:** OHLC. Approximate the payoff as "high and low stay inside the barriers for 10 min." Payout quotes are needed.
- **Ambiguity:** "sweep conviction" comes from a proprietary model. Faithful default: drop it, or use the accumulation score.

### C3 `run-inverse-sweep` (RUNLOW/RUNHIGH)
- **Arming conditions:** accumulating; conviction ≤ 0.25; bars_inside ≥ 15; the model has a predicted side.
- **Contract:** SSL predicted → RUNLOW with barrier = range_low. BSL predicted → RUNHIGH with barrier = range_high.
- **Duration and payout:** 15 min; payout ≥ 1.4×.
- **Target:** win rate > 60% (breakeven about 42% at 1.4×).
- **Status:** UNVALIDATED.

### C4 `lookback-float`
- **Arming conditions:** accumulating; conviction in [0.35, 0.6]; distance to target ≥ 30% of range.
- **Contract:** SSL predicted → LBFLOATPUT (pays high − close). BSL predicted → LBFLOATCALL (pays close − low).
- **Duration:** 15 min.
- **Success test:** captures ≥ 80% of the theoretical move compared with the scalper.
- **Data needed:** OHLC gives max/min within 15 min. The lookback premium is not observable.
- **Status:** UNVALIDATED.

### C5 Conviction-band routing map (EXOTIC_CONTRACTS "How This Complements"; CORE_TRADING_PRINCIPLES §2)
- Conviction > 0.6 → swing multiplier (post-sweep expansion).
- 0.3–0.6 → retracement scalper multiplier; lookback uses 0.35–0.6.
- ≤ 0.3 → Range.
- ≤ 0.25 → Run.
- CORE_TRADING_PRINCIPLES gives the bands as: multiplier 0.3–0.6, range ≤ 0.3, run ≤ 0.25, lookback 0.35–0.6.

---

## Theme D — Accumulation / compression detection

### D1 `accum-percentile-box` (production baseline; ACCUMULATION_RESEARCH "Current State", Exp 4; confirmed in `ame.py:115–275`)
- **Window:** the last `lookback` bars excluding the current bar. Lookback was 30, changed to 60 (deployed after Exp 0).
- **Box:** range_high = 90th percentile of highs; range_low = 10th percentile of lows.
- **Width:** width% = (high − low) / mid × 100, which must be < `range_threshold`. The code default is 8.0% (env `AME_ACCUM_MAX_WIDTH_PCT`).
- **Inside count:** inside_pct = fraction of closes within [low, high], which must be > 0.6. bars_inside must be ≥ 8.
- **BOCPD relaxation (code):** min_bars drops to 5 when the last BOCPD changepoint lies in the latter half of the lookback.
- **Structural override (code):** when support/resistance zone pairs are supplied, choose the pair with the highest inside_pct.
- **Quality grade (code, approximate):** inside_pct thresholds of 0.85, 0.70 and 0.55.
- **Results claimed:** virtual tracker win rate 61% on accumulation signals and 75% on post-accumulation signals (12 signals), from about 126 virtual positions. No costs and no out-of-sample test.
- **Exp 4 grid, planned per family:**
  - range_threshold 1.0–5.0% in 0.5% steps
  - inside_pct 0.4–0.8 in 0.1 steps
  - min_bars 4–12 in steps of 2
  - lookback 15–50 in steps of 5
  - Families: vol indices, frx, OTC indices, crash/boom, crypto.
  - Hypotheses: crash/boom needs a larger width; forex needs fewer min bars; vol indices need a shorter lookback.
- **Data needed:** OHLC.
- **Known gaps listed:** horizontal ranges only; no volume; binary output.

### D2 `accum-xgb-quality` — FAILED
- **Source:** ACCUMULATION_RESEARCH "Experiment 0" (2026-04-18).
- **Result:** XGBoost predicting whether a window leads to a profitable trade from OHLC features got "50% accuracy (= baseline)."
- **Feature importances:** atr_ratio 0.039, return_std_30 0.039, close_vs_midrange 0.039, vol_contraction 0.039, upper_wick_mean 0.038. inside_pct_10 was last at 0.010.
- **Conclusion quoted:** "OHLC alone can't predict outcomes."
- **Status:** FAILED as a predictor. The features were still added to Sage.

### D3 `range-compression-RC` with `dRC/dt` squeeze-release trigger
- **Source:** ACCUMULATION_RESEARCH appendix.
- **Definitions:** RC = σ_short / σ_long, where σ_w = sqrt(mean r² over w bars), r = log return, n_s = 10, n_l = 50.
- **States:** compression when RC < θ_c ≈ 0.6; release when RC > 1 + ε.
- **Trigger:** first bar with RC(t−1) < θ_c AND dRC/dt > κ.
- **Unset parameters:** κ and ε. Default: the discrete ΔRC above its 80th percentile, or RC crossing 1.
- **Direction:** not specified. Default: the direction of the release bar, or a breakout of the box.
- **Status:** UNVALIDATED.

### D4 `absorption-score-A`
- **Formulas:** ρ_vp = corr over window W of (volume, |r|). A = (1 − RC) · max(0, 1 − ρ_vp). Accumulation if A > θ_A, with θ_A unset.
- **Data needed:** volume (meaningless on Deriv, where stored volume is 0).
- **Status:** UNVALIDATED.

### D5 `bb-kc-squeeze-scalar` (TTM/Carr squeeze, made continuous)
- **Formulas:** BB_width = 4·σ_20; KC_width = 3·ATR(14, Wilder); SQ = BB_width / KC_width. Squeeze when SQ < 1; d = consecutive bars with SQ < 1.
- **Release hazard:** h = 1 − exp(−λd); E[τ] = 1/λ, λ fitted by maximum likelihood. The doc cites "squeezes rarely exceed ~20 bars."
- **Bollinger baseline:** BB_width = (upper − lower) / μ_n, below its 20th percentile.
- **Status:** UNVALIDATED.

### D6 `accum-logistic-prob`
- **Model:** P = σ(β₀ + β·x) with x = [1−RC, 1−ρ_vp, 1−SQ, d/d_max, inside_pct], fitted on hand-labelled windows.
- **Status:** UNVALIDATED.

### D7 `expansion-target`: take-profit sizing after release
- **Model:** E[|Δp| / ATR | duration d] = α·d^φ, fitted per family. Expected φ ≈ ½ for vol indices and φ ≈ 1 for crash/boom.
- **Use:** TP1/TP2 placement.
- **Status:** UNVALIDATED.

### D8 Baseline filters
- **Variance ratio** (Lo–MacKinlay): VR(q) = Var(q-bar returns) / (q·Var(1-bar returns)). VR < 1 means mean-reverting, which is accumulation-compatible. The doc says any detector must beat "variance-ratio + bar count."
- **GARCH(1,1)** low conditional variance as a squeeze proxy.
- **Wyckoff phases A–E:** qualitative only.
- **Status:** baselines.

### D9 `accum-shape-classes` (Exp 3)
- **Features:** slope of the regression through range midpoints; start/end width ratio (<1 converging); volume front- or back-loaded.
- **Method:** k-means with k = 4 (horizontal, ascending, descending, triangular). Measure sweep rate, time to sweep, sweep magnitude and expansion.
- **Hypothesis:** ascending (Darvas-like) has higher sweep rates; triangles break fastest.
- **Planned methods:** 16 detection methods (Darvas Box, Wyckoff, S/R cluster, Volume Profile, OBV, VPIN, …) over 30 days, ensembles with k-of-n voting (k = 3, 4, 5 of 6), weighted thresholds (0.4/0.5/0.6) and stacked logistic regression (70/30 split).
- **Targets:** win rate > 70%, false-positive rate < 25%.
- **Status:** no results reported.

### D10 `bocpd-early-accum` (Exp 5)
- **Hypothesis:** BOCPD flags the range start 3–8 bars before the box confirms.
- **Rule:** accumulation_start = BOCPD changepoint(t) AND box confirmed at t + δ, with δ to be fitted.
- **Status:** UNVALIDATED. Partly in code as the min_bars 8 → 5 relaxation.

### D11 `consolidation-base-levels`
- **Source:** CONSOLIDATION_BASE_DETECTOR_RESEARCH.md.
- **Rule:** over a lookback of 100 bars, group consecutive bars whose body midpoints lie within band_pct of each other. Allow about 1 intruding bar before splitting. Require ≥ min_bars bars in the zone.
- **Zone values:** floor = min(min(open, close)); ceiling = max(max(open, close)); density = bars_in_zone / window. Score = density × bars_in_zone × age; keep the top K per side.
- **Role relative to current price:** floor > price → supply; ceiling < price → demand. The doc trades the body bound, not the wick tip. Test case: Vol100 15m, 2026-04-26, supply 740.62 vs wick about 748.
- **Per-class parameters (min_bars / band_pct / density_min):**
  - synthetic: 4 / 0.0010 / 0.20
  - crypto: 5 / 0.0020 / 0.25
  - fx: 6 / 0.0008 / 0.30
  - commodity: 5 / 0.0015 / 0.25
  - other: 5 / 0.0020 / 0.25
- **Validation plan:** wick-rejection rate on touches (wick into the zone, close back outside within N bars) and rejection magnitude, compared with wick-cluster levels.
- **Status:** UNVALIDATED (doc only). The doc says a null result would be "clean."

---

## Theme E — Change-point / BOCPD forecasting (BOCPD_FORECAST_RESEARCH.md)

### E1 `bocpd-forecast` methods 1–4
Input: the Adams–MacKay run-length posterior P(r_t | x).
- **M1:** project forward with each regime's ρ, weighted by the posterior.
- **M2:** OU fitted per run-length bucket: μ_r(k) = x_t·e^{−θ_r k} + m_r(1 − e^{−θ_r k}), and E = Σ P(r)·μ_r(k).
- **M3:** full mixture forecast.
- **M4:** gate. If P(r_t = 0) > 0.7, use a flat forecast; otherwise use OU.
- **Horizons and test:** k ∈ {3, 5, 10, 20}; 90 days of data.
- **Promotion rule:** must beat BOCPD-agnostic OU by ≥ 5pp direction accuracy on bars with r_t ≤ 3. Nulls: random walk and plain OU.
- **Status:** "TO BUILD"; no results.
- **Prior result cited:** BOCPD passes Gate 2 "as a reversal indicator… only as a prevalence feature — not a timing trigger" (EXPERIMENT_RESULTS §9+§10, not in my file set).

### E2 Derived signals
- **k-step changepoint probability:** q_k = 1 − Σ P(r)·Π_{j<k}(1 − H(r + j)).
- **Mixture mean:** (1 − q_k)μ_cur + q_k·μ_new.
- **Early warning:** g(t) = ΔP(r_t = 0), confirmed by g'(t) > 0. Equilibrium P(r = 0) = h/(1 + h).
- **Rule:** fire when g crosses a calibrated threshold with g' > 0.
- **Baselines:** CUSUM S_t = max(0, S_{t−1} + x − μ₀ − k), alarm when S > h; Shiryaev–Roberts R_t = (1 + R_{t−1})·L₁/L₀.
- **Status:** UNVALIDATED.

---

## Theme F — Key levels / support-resistance

### F1 `dynamic-min-touches`
- **Source:** DYNAMIC_KEY_LEVEL_TOUCHES_RESEARCH.md.
- **Rule:** threshold = clamp(int(P75 of touch counts across candidate clusters), 2, 6). If fewer than 10 clusters exist, fall back to a static threshold of 3.
- **Lookback by timeframe:** 1m = 1000 bars, 1d = 100.
- **Alternatives:**
  - (B) Random-walk null: 95th percentile of cluster touch counts over 200 simulated paths at matching volatility.
  - (C) Learned from reaction quality, where a reaction means wick plus close back inside within N bars.
- **Status:** shipped for AME; A/B test running, no result reported.

### F2 `level-break-hold-classifier`
- **Source:** EMPIRICAL_TRADING_STRATEGY_2026-04-29 Finding 1.
- **Model:** logistic regression on about 11 features: z, z-velocity, dist_atr, touches, level_kind, age, last_reaction_*, institutional_signature, path_obstacles.
- **Result:** beat the heuristic touches/(touches + 5) on 19 of 20 combos. Mean heuristic accuracy 0.34 vs LR f1 0.78. Examples:
  - R_10 3m: 0.17 → 0.90
  - R_100 1m: 0.28 → 0.90
  - cryBTCUSD 5m: 0.29 → 0.88
  - 1HZ100V 5m: 0.34 → 0.81
  - JD50 3m: 0.35 → 0.84
- **Caveats:** about 33 hours of data, in-sample, and accuracy is compared against f1. Not a trading P&L.
- **Status:** CLAIMED.

### F3 `dist-atr-negative`
- **Finding 2:** coefficients −1.88 (R_10 3m), −0.92, −0.96, −1.10, −1.01. Nearer levels break more often.
- **Rule:** use levels 0.5–2.0 ATR away; skip the nearest level if it is < 0.3 ATR away.

### F4 `last-reaction-sharp` — FAILED as a global rule
- Signs flip by cell: R_100 3m +1.97, R_100 5m −1.76, 1HZ100V 3m −2.93, 1HZ100V 5m +1.77.
- The doc's instruction: "do not condition trades on reaction quality."

### F5 `stop-anchor-at-extreme`
- **Finding 4:** place stops at the cluster's price_high (SELL) or price_low (BUY) ± 0.3 ATR, not at the centroid.
- Example: R_100 centroid 779.83 vs extreme 790.00 (> 1 ATR apart).

### F6 `stop-hunt-pattern`
- **Finding 5, BSL hunt → trade (as written: "becomes BUY"):**
  - bar i: high > level.price_high and close ≤ level.price_high
  - then within N ≤ 3 bars: close < level.price_low
- **Ambiguity:** the doc says "becomes BUY," but the closes run downward through the level, so it reads as a SELL/short setup. Faithful default: short after the breakdown confirmation; mirror for SSL.
- **Status:** detector not built.

### F7 `ame-level-filter-strategy`
- **Source:** EMPIRICAL_TRADING_STRATEGY "Strategy specification."
- **Universe:** R_10 and R_100 on 1m/3m/5m; cryBTCUSD, 1HZ100V and JD50 on 3m/5m.
- **Entry, all required:**
  1. AME directional signal with confidence ≥ 65.
  2. Price 0.5–2.0 ATR from a key level on the trade side.
  3. Level has ≥ 6 touches, or is a pivot high/low.
  4. Level is not an S/R flip.
  5. Skip if the nearest level is < 0.3 ATR away.
- **Stop:** level extreme ± 0.3 ATR.
- **Target:** TP ladder with minimum R:R at TP2 of 1.3 for synthetics and 1.75 otherwise.
- **Skip:** < 200 bars of history, 4h/1d, CRASH/BOOM, or a strong opposing level right next to price.
- **Status:** "ready for backtest," untested.
- **Dependency:** relies on the AME direction, which G1 found inverted.

---

## Theme G — AME production audit

### G1 `ame-liquidity-swept-inverted` (AME_AUDIT_2026-06-05)
- **As emitted: FAILED.** Pooled over 14 days, all asset classes and timeframes:
  - liquidity_swept, horizon 1 bar: n = 410, hit 46.8%, −22.4 bps, t = −2.07
  - liquidity_swept, h = 16: n = 27, 37.0%, −135 bps, t = −2.33
  - All directional signals: n = 512, 46.9%, −20.9 bps, t = −2.28
- **Inverted:** 52.3%, +20.9 bps, t = +2.28.
- **Rule implied:** AME labels a sweep above a prior high as BUY. Trade the opposite (fade the sweep): high sweep → SELL, low sweep → BUY. Enter at bar close, exit after 1 bar (also tested at 4 and 16 bars).
- **Faithful OHLC default:** bar high > prior swing-high pool → SELL at close; mirror for lows.
- **Caveats:** gross bps, no cost model ("20 bps gross edge needs ≥10 bps round-trip + slippage"); no multiple-testing correction; 1,490 raw signals → 506 usable.
- **Per-cell results** (direction as emitted, Sharpe):

  | State | Venue | TF | h | n | Hit | bps | Sharpe |
  |---|---|---|---|---|---|---|---|
  | liquidity_swept | nasdaq | 1h | 1 | 32 | 34.4% | −20.5 | −2.04 |
  | liquidity_swept | mexc | 4h | 1 | 82 | 35.4% | −79.8 | −1.68 |
  | liquidity_swept | nyse | 15m | 1 | 35 | 54.3% | +10.1 | +1.34 |

  Stocks look better than crypto.
- **State-only mean raw forward return:**
  - liquidity_swept −50.3 bps (n = 415)
  - accumulating −31.2 bps (n = 78)
  - expansion −11.4 bps (n = 95)
  - precursor −166.6 bps (n = 4)
  - The doc reads this as AME "firing at local tops." It suggests a short-after-any-state test, which may be biased by the sample period.
- **Status:** inverted version is CLAIMED, gross only. Data needed: OHLC.

---

## Theme H — Crypto funding / listing / volume (CRYPTO_ALPHA_DESIGN.md)

Data for this theme comes from MEXC: funding every 5 min (423,680 samples, about 887 perps, about 36 hours) and listings.

### H1 `funding-extreme-fade`
- **SELL (fade crowded longs)** when latest funding ≥ 90th percentile of its own 30-day history OR APR ≥ 50%.
- **BUY (squeeze crowded shorts)** when funding ≤ 10th percentile OR APR ≤ −25%.
- **APR** = rate × (365 × 24 / cycle_hours) × 100, with cycle default 8h.
- **Status:** deployed, no performance reported.

### H2 `market-funding-extreme` (2026-05-16)
- **Rule:** cross-sectional. APR in the top 5% of the whole MEXC perp universe → SELL; bottom 5% → BUY. Recomputed every 5 min.
- **Snapshot percentiles:** 1st −187%, 5th −37%, 25th −8%, 50th +6%, 75th +11%, 95th +44%, 99th +91%. About 45 symbols sit in the tails at any time.
- **Status:** UNVALIDATED.

### H3 `fresh-listing-squeeze`
- **Rule:** listing ≤ 72 hours old AND APR ≤ −100% → BUY.
- **Observation:** IRYS reached −2029% APR.
- **Status:** UNVALIDATED.

### H4 `funding-flip`
- **Original:** sign changed within the last 6 funding cycles → trade opposite to the latest sign.
- **Sharpened (`funding_flip_now`):** sign changed between the last two samples.
- **Why:** about 98% of symbols keep the same sign across 24 hours of 5-minute samples.
- **Status:** UNVALIDATED.

### H5 Listing-age recipes
- **Hot listing:** < 12 hours since first seen → BUY ("discovery").
- **Exhaustion fade:** 24-hour move > +50% AND crowded longs → SELL.
- **Confluence:** +5 per agreeing recipe, capped at +15.
- **Status:** UNVALIDATED. Cross-check with I1/I2 below: fading pumps FAILED there, which directly contradicts the exhaustion fade.

### H6 defi_alpha volume recipes
- **Volume z-score:** against a 30-bar baseline.
- **Recipes:**
  - Volume surge, quiet price: vol z ≥ 2 AND |change| < 1.5% → BUY ("accumulation").
  - Fresh listing with volume: < 12 hours old AND volume ≥ $1M → BUY.
  - Flow conviction: vol z ≥ 2 AND |change| ≥ 3% AND 3-bar slope > 0 → BUY, or the mirror → SELL.
- **Borrowed filters:**
  - Buy ratio: buy volume / total > 65% (needs trade tape).
  - ≥ 3 consecutive candles in the same direction.
- **Not built:** "quiet OI loadup" (OI not stored); cross-venue funding/arb.
- **Status:** UNVALIDATED.

---

## Theme I — Edge doctrine and the graveyard (EDGE_MINTER.md, 2026-07-30)

### Failed ideas (I1–I7)
- **I1 `fade-the-pump`: FAILED in 5 variants:** hold, fixed barrier, reversion exit (−17%), trailing stop, scalp. The doc calls it a "negative-skew trap." Rule: the short side of crypto pumps and dumps does not pay at any horizon.
- **I2 `dump-continuation-short`: FAILED.** +3.2% on daily bars, "dead intraday (granularity artifact)."
- **I3 `trend-follow-short`** (the inplay_lag spec plus a funding "FUEL" cross-signal): **FAILED.** "FUEL was backwards."
- **I4 `breakout-long-trend-ride`: FAILED long-window.** Sharpe +2.55 over 148 days, −2.2 over 588 days. A BTC-regime gate did not rescue it; the doc blames a newer-coin selection artifact.
- **I5 `breakout-scalp`: FAILED.** Negative on both windows with all fast exits.
- **I6 `self-referential-regime-gate`** (trade only while trailing Sharpe > 0, 60-day scale): **FAILED for real edges.** Full-period Sharpe change was −0.3 for MOM and BRK. It only helped defensively on the anti-edge (kept REV off about 75% of the time).
- **I7 `per-instance-graduation-gate`** (trade a coin's pattern after it worked K times): **FAILED per instance.** Rank correlation of past vs future breakout success = +0.04. It works only at the aggregate/regime level ("is the pattern hot market-wide"), and must be lookahead-free.

### Deployed book, named but not specified in my files (I8)
- Crypto momentum (long).
- Kalman funding-carry.
- RB200 fade.
- Live funding-fade.

### Validation rules (I9)
- Measure the raw effect before building signals.
- Test at execution granularity.
- Sweep costs (taker fee + spread + slippage).
- Out-of-sample, including a bear market.
- Portfolio and capacity test.
- Correlation against the existing book.
- Null model.
- Liquidity buckets.
- Deflated Sharpe ratio, FDR correction, purged and embargoed walk-forward, a locked hold-out, and an economic prior.
- Positive-skew families (trend, breakout, breadth) are harvestable; negative-skew families blow up.

---

## Theme J — Execution, risk and trader post-mortems

### J1 `swing-multiplier-trader` — FAILED
- **Source:** archive/SWING_TRADER_POST_MORTEM.md.
- **Result:** −$623, 26% win rate on 69 trades (true loss is worse: 101 of 108 timeout exits recorded $0).
- **Timeline:** 2026-04-15 win rate 33%; BUY side 13% (on 30 trades, per CORE_TRADING_PRINCIPLES) and disabled; MIN_CONFIDENCE raised to 80; fully disabled 2026-04-17.
- **Causes:**
  - The stop was passed as a price, rejected by Deriv, and the order was then retried with no stop at all.
  - No signal-freshness gate.
  - Consensus confidence ≥ 100: 53 trades lost −$554.45. "High confidence = late entry."
  - Volatile symbols: cryBTCUSD 0% / −$243, BOOM500 0% / −$175, 1HZ50V 0% / −$153.
- **Leverage and risk:** multipliers x100–x300, 1.0% risk per trade.
- **Fixes required before re-enabling:**
  - Stop in USD: usd_loss = stake × |entry − sl| / entry × multiplier.
  - 120 s freshness gate.
  - Forex and OTC indices only.
  - Multiplier ≤ x50.
  - An R:R gate.
- **Same signals on Rise/Fall binaries: ~53% win rate** (CLAIMED, no sample size). Settings: 0.6% risk, payout ≥ 1.5×, 120 s freshness, about 15-minute expiry. Winners on OTC_NDX and frxEURNZD.
- **Lesson:** binaries tolerate timing error; multipliers get stopped out by wicks.

### J2 Core gates (CORE_TRADING_PRINCIPLES.md)
- Confidence must be 80–89, "the only profitable bucket." Reject ≥ 90 ("reactive").
- Reject conviction > 0.7 (late) and conviction ≥ 0.7 with confidence ≥ 90.
- Position in range: SELL only in the top 40% of the range, BUY only in the bottom 40%.
- R:R ≥ 1.5.
- Momentum filter: reject if the last 2 bars fight the thesis.
- Thesis-invalidation exits: the accumulation broke, the prediction flipped, or an opposing sweep occurred.
- 30-minute timeout.
- **Stops and targets:** structural stop at the opposite range edge plus an adaptive buffer; a tighter pivot stop when local structure confirms; move stop to breakeven at +1R; dynamic TP when a sweep in progress is detected.
- **Leverage and risk:** multiplier x30/x80/x150 by setup quality; risk 0.3% (scalper) / 1.0% (swing).
- **Symbol blacklist:** cryBTCUSD, BOOM500, 1HZ50V. BOOM/CRASH also excluded from the scalper.
- **Kill rule:** disable any strategy, direction or symbol with negative expectancy over 20+ trades; review every 50 trades.
- **Retired:** post-sweep entry (scalper v1), "too late."
- **Status:** rules. Only the confidence-bucket claim has evidence, and it is anecdotal.

### J3 `hold-time-extension` (archive/HOLD_TIME_TUNING.md, 2026-04-17)
- **Evidence:** 78% of positions that expired at the lookback limit were still profitable. TP hit rate was 27% (53/195).
- **Virtual max holds, before → after:**
  - 1–4m: 30 min → 1 h
  - 5m: 30 min → 2 h
  - 10m/15m: 2 h → 4 h
  - 30m/1h: 12 h → 24 h
  - 2h/4h: 3 days → 5 days
  - 6h/1d: 7 days (unchanged)
- **Real traders:** scalper 30 → 60 min; OB trader 1 → 2 h.
- **Pass criteria:** TP hit rate > 35%; lookback win rate stays ≥ 75% (revert if < 60%); Sage avg_reward rises above 0.20.
- **Status:** outcome not reported.
- **Note:** this conflicts with the 30-minute timeout in J2.

### J4 Trader defaults (ENV_VARS.md)
- Multiplier default 100.
- Binary duration 15 min.
- Crypto paper trader: risk 1.0%, max hold 14,400 s (4 h), timeframes 15m/1h/4h consensus.
- Notifications only on timeframes ≥ 5m.
- Crypto alert format: 4 equal TP legs.
- RL bandits: exploration 0.15; cold start at 30 trades per arm; exit threshold 0.3.

---

## Theme K — Physics / field-equation features (ENSEMBLE_READINESS.md)

### K1 `field-equation-threshold-events` — FAILED
- **Events tested:** entropy_production, phase_transition (`transition=True`, `critical=True`) and maxwell_curl (`curl_crossing=True`).
- **Result:** "no reproducible edge." The hand-tuned weights were removed in commit 3d418334.
- **Still untested:** the 7 raw continuous values (entropy_rate, susceptibility, order_parameter, coupling, curl, rotation_strength, bars_ordering) as XGBoost/perceptron inputs, walk-forward, against a 22-feature base.
- **Prior given:** 15% chance of > 2pp gain, 60% no change, 25% harm.
- **Rule:** drop the features if there is no lift. The doc does not define the formulas, so they cannot be re-implemented from it.

---

## Theme L — Candidate features from CALCULUS_TOOLKIT.md (methodology, untested)
- **L1 `pivot-sharpness`:** |v'(t_pivot)| = |second difference of price| at a k-bar pivot (where v(t−1)·v(t+1) < 0). Take high-conviction reversals on sharp pivots and be wary of slow ones.
- **L2 `hawkes-criticality`:** crash_risk from the spectral radius of α/β in a multivariate Hawkes fit, which "explodes" as the branching ratio → 1. Proposed as a pre-crash signal. Needs event or tick timestamps; bar-level jump events are a possible proxy.
- **L3 AR(1)–OU bridge:** θ ≈ (1 − φ)/Δt. A single θ fitted on 1m applied to all timeframes; needing to refit signals disagreement across scales.
- **L4 Fatigue hazard:** h(F) = h₀(1 − e^{−βF}). Survival S = exp(−∫h). P(break within N) = 1 − S(t+N)/S(t). First-passage E[T_L] = L²/σ².
- **L5 Reach-CDF density:** f(x) = [F(x+ε) − F(x−ε)] / 2ε, for quoting pullback reach in ATR.
- **Others named but not specified here:** Malliavin, fractional (Hurst), Almgren–Chriss.

---

## (a) Ideas that cannot be backtested on OHLC/exchange bars alone, and why
- **A1/A2 RDBULL/RDBEAR:** direction can be checked on Deriv 1m bars. P&L needs Deriv Rise/Fall and ONETOUCH payout quotes and early-sell quotes, which are not in OHLC.
- **B1 spike hazard:** needs ticks (tick counts since the last spike); Deriv keeps only about 24 hours of 1m history. Bar-based proxies lose resolution.
- **C1 digit:** needs tick last digits and digit-contract payouts.
- **C2–C4 Range/Run/Lookback:** the path can be checked on bars, but payout and premium are unobservable. Arming also uses the proprietary "sweep conviction."
- **D4 absorption score, H6 buy ratio, D9 OBV/VPIN/volume profile:** need real volume or trade tape. Deriv volume is stored as 0.
- **H1–H4 funding and listing recipes:** need funding-rate history and listing dates. Exchange data, so feasible if funding history is collected; MEXC only so far. "Quiet OI loadup" needs OI history, which is not stored.
- **G1 AME, F2/F7 level classifier, J2 confidence/conviction gates:** depend on proprietary model outputs (AME state, Sage confidence, sweep conviction, institutional_signature). Only approximate OHLC re-definitions are possible.
- **K1:** formulas not given in the doc.
- **L2 Hawkes criticality:** needs event-time data.
- **Sentiment/news:** none in these files.

## (b) Files with no testable trading idea
- **BYBIT_TRADFI_API_RESEARCH.md:** venue and data survey. xStocks spot has about 12 months of history; TradFi perps about 2 months and an unconfirmed API; MT5 CFDs. Recommendation: keep TradingView for data.
- **DATA_BACKFILLER.md:** Deriv candle backfill tool. Deriv keeps about 90 days of 30m/1h/4h and about 24 hours of 1m; volume is stored as 0; forex returns about 60–67% of bars because of market closures.
- **CALCULUS_TOOLKIT.md:** methodology only; its candidate features are listed under L.
- **BUSINESS_PLAN.md:** apart from the RDBULL/RDBEAR material (A1–A3), this is fund products, legal, marketing and term sheets, with no further trading ideas. Its return figures are projections, not results.
- **ENV_VARS.md:** configuration reference; its strategy parameters are folded into A1, A2, A3 and J4.
- **ENSEMBLE_READINESS.md:** only the failed K1.
- **EDGE_MINTER.md:** mainly process doctrine; its graveyard is recorded under I.


---

# Appendix cat_g1.md

# Catalogue of testable trading ideas: 18 lab docs

Base: the source. I read all 18 files in full. Where a doc left a rule vague, I grepped the code briefly to confirm it. Those confirmations are marked **[code]**, with the path relative to the source.

**Status key**
- FAILED: tested and negative or null.
- WEAK/UNREPLICATED: some evidence, but it did not pass replication.
- CANDIDATE: a positive result that has not been replicated.
- UNTESTED: a proposal only.
- SHIPPED-UNVALIDATED: in production with no backtest behind it.

**Global caveats**
- None of the EXPERIMENT_RESULTS numbers are net of bid/ask. All are gross forward-return, win-rate or F1 against a random-bar null.
- Only the freqtrade sweep studies (LIQUIDITY_PRECISION) include fees and funding.
- Exp 8 says the random baseline drifts −0.07% over 5 bars, "indicating bid-ask friction / sample selection".
- The usual panel is R_50, R_100, 1HZ50V, frxEURUSD, frxGBPUSD, BOOM500, BTC/USDT and ETH/USDT, on 5m/15m/1h, over 60–90 days.
- **Data-retention trap:** 5m retention was 2 days, so many "90d" 5m results really cover about 1.5 days. 1h data was about 9 days and 4h about 22 days at the time. Treat every 5m number in EXPERIMENT_RESULTS as tiny-sample.
- **The consolidated summary table in EXPERIMENT_RESULTS (around line 706) contradicts the detailed sections:**
  - Exp 1: the summary says "K-means 3 regimes"; the detail says GMM with 4 clusters.
  - Exp 4: the summary says "No"; the detail says it was deployed.
  - Exp 5: the summary says "Early-exit at +30/+50 improves expectancy, shipped"; the detail says "Not deployed, Sharpe worse".
  - Exp 6: the summary says "66% accuracy"; the detail says 58.6%.
  - Trust the detailed sections.

---

## THEME A: Liquidity sweep / stop-hunt systems (the most rigorous tests in this file set)

### A1. `sweep_fade_both`: sweep reversal with no trend filter. FAILED
- **Sources:** LIQUIDITY_PRECISION_SWING_ANALYSIS.md §4, §11 ("both" mode). It cross-references HMM_REGIME_SUITE §8.18, which is not one of my files.
- **Rule** ([code] `trading/user_data/strategies/sweep_momentum.py`), on 1h bars:
  - `prior_high = rolling max(high, 24).shift(1)`; `prior_low = rolling min(low, 24).shift(1)`.
  - `swept_low = low < prior_low AND close > prior_low` → LONG.
  - `swept_high = high > prior_high AND close < prior_high` → SHORT.
  - Vol gate "highvol": `rv = std(log-return, 12)`; require `rv > rolling 500-bar 66th percentile of rv` (min_periods 100).
  - Stop = 2.5 × ATR(14) from entry, which is 1R.
  - Move the stop to breakeven at +1R, then trail 2.0 × ATR behind price, never below breakeven.
  - Max hold 240h. No fixed target.
  - Size: 1% of equity at risk per trade. Limit entries at the level.
- **Result:** 3 years (2022–2026), 21 crypto perpetual pairs, 0.1%/side fees plus funding. Return −98.0%, Sharpe −3.19, PF 0.69, win 45.7%, max DD 98.1%. It "survived in-sample but lost −98% OOS because it faded into trends".
- **Data:** OHLC, plus funding for perps.

### A2. `sweep_trend_align`: sweep plus HTF momentum filter, scalp-to-swing management. FAILED, though the filter itself helps
- **Sources:** LIQUIDITY_PRECISION §4–§6, §10, §11.
- **Rule:** A1, with longs only when `close > EMA200 AND EMA50 > EMA200` (uptrend), and shorts only when `close < EMA200 AND EMA50 < EMA200`. Everything else as A1.
- **Result** (3y, 21 pairs, 1h): −94.3%, Sharpe −3.09, **PF 0.72**, win 48.2%, DD 94.5%. Roughly 1,900 trades, about 1.4 per day.
- Q1-2024 alone gave +10% and PF 2.57. The doc calls this a "favourable-window mirage".
- **Conclusion:** the ordering trend_align (0.72) > none (0.69) > counter (0.70) shows the momentum filter is directionally right, but every mode has PF < 1.

### A3. `sweep_counter`: fade exhaustion against the trend. FAILED
- **Source:** §11.
- **Rule:** long sweeps only in a downtrend; short sweeps only in an uptrend.
- **Result:** −98.0%, Sharpe −3.16, PF 0.70, win 45.5%, DD 98.1%.

### A4. `sweep_mtf_resolution`: true H4 bias, entries on 1h/5m/1m, taker vs maker fees. FAILED
- **Source:** §12. [code] `trading/user_data/strategies/sweep_mtf.py`.
- **Rule:** A2, but the trend comes from 4h EMA50/EMA200 (`htf_up = close_4h > EMA200_4h AND EMA50_4h > EMA200_4h`), merged causally via `@informative`.
- **Results:**

| Resolution | Fee | Universe | PF | Return | Trades/day |
|---|---|---|---|---|---|
| 1h | taker 10 bps | 21 pairs, 3y | 0.72 | −94% | 1.4 |
| 5m | taker 10 bps | 5 pairs, 1.5y | 0.38 | −98% | 2.4 |
| 1m | taker 10 bps | 3 pairs, 6mo | 0.40 | −98% | 10.5 |
| 5m | **maker 2 bps** | 5 pairs, 1.5y | 0.60 | −98% | 5.4 |

- **Findings:** finer resolution is worse, maker fills help materially, and nothing clears PF 1.0.
- **Data:** Binance futures OHLC.

### A5. `entry_trigger_bakeoff`: same trend-aligned management, entry trigger swapped. FAILED
- **Source:** §13. [code] `trading/user_data/strategies/entry_triggers.py`. 1h, 3y, 21 pairs.
- **Management:** A2 management and trend filter (EMA50/200) are held fixed. The triggers drop the highvol gate; only the sweep trigger keeps A2's definition.
- **Triggers:**
  - Sweep (A2 definition): PF 0.68, −98%.
  - RSI pullback, RSI(14): long when RSI crosses up through 40 (`rsi > 40 AND rsi[-1] ≤ 40`); short when it crosses down through 60. PF 0.69, −98%.
  - Donchian breakout: long when close > max(high, 20).shift(1); short when close < min(low, 20).shift(1). PF 0.60, −98%.
  - EMA pullback, EMA20: long when `low ≤ EMA20 AND close > EMA20` in an uptrend (short mirrored). PF 0.54, −98%.
- All four land near 46% win.
- **Doc conclusion:** "no simple, mechanical, price-only directional edge at 1h-and-finer on this crypto universe that survives realistic costs". The outcome is dominated by the ATR trail (it gives back too much) plus cost drag. The doc explicitly says to stop tweaking on the same OHLC inputs because of multiple-comparisons risk.
- **What survived as "keep":** the trend filter, maker/limit execution, and fixed-fractional sizing.

### A6. `discretionary_64R_gold_M1`: XAUUSD M1 precision sweep with a sub-10-pip stop. Not systematically reproducible; FAILED as a mechanical rule
- **Source:** §0–§3, §5, §8.
- **The single trade claimed:** BUY 5 lots at 4428.734, SL 4428.215 (0.519 = 5.2 pips), risk $259.50, open profit $16,504 = 63.6R, notional about $2.21M. This is one survivor trade.
- **Proposed system:**
  1. Statistics gate: z ≥ 2.5–3, or a clean sweep of a meaningful level, and the macro tape is not adverse.
  2. Limit entry at the swept level or order block; stop just beyond the sweep.
  3. HTF momentum alignment.
  4. LTF (M1/M5) entry with an HTF (H1/H4/D) target.
  5. Breakeven at 1R, then a structure trail.
  6. Risk 0.5–1% of equity (never above 2%).
  - Top-down funnel: HTF (W/D/H4) sets bias and target, MTF (H1/M15) sets the zone, LTF (M5/M1) sets the trigger and invalidation. Trade only when all three align.
- **Costs cited:** gold spread 1.5–4 pips normally, 5–10 pips in the Asian session. M1 noise wicks are 5–15 pips. London/NY AM and 09:50 NY are cited as the clean windows.
- **Ambiguity:** "structure trail" and "meaningful level" are not defined. A faithful default is the A4 rules on M1/M5 with an H4 bias and explicit spread.
- **Status:** the M1 crypto proxy in A4 failed. Gold M1 with real spread is untested.

### A7. `fixed_fractional_risk` / risk-of-ruin. Sizing rule (accepted principle, not an alpha)
- **Source:** §3.4, §5.6.
- **Rule:** risk a fixed 0.5–1% (max 2%) of current equity. Six losses in a row cost about 6% at 1% risk versus about 47% at 10% risk.
- Also proposed (§9.7): a thesis-level kill switch on max drawdown or losing streak. No number is given.

### A8. `sweep_direction_ML`: which side (BSL vs SSL) gets swept after accumulation. SHIPPED; in-sample, unreplicated
- **Source:** EXPERIMENT_RESULTS Exp 2, plus the accuracy-progression table.
- **Target:** given an accumulation window, does buy-side liquidity (above the range) or sell-side liquidity (below) get swept within 24h?
  - 547 samples: 342 SSL, 183 BSL, 234 no sweep.
  - Exp 3's 584 samples have an always-SSL baseline of 65.6%.
- **Results:**
  - Linear 7-factor model: 35.5–37.0%. XGBoost on 17 features: 63.6–65.9%.
  - The always-SSL baseline (about 65.6%) is about as good as XGBoost. The "+29%" is against a weak linear model, not the base rate.
  - Later: 630 samples gave 76.3%, and adding imbalance ROC gave 77.7%. The doc attributes the jump to more data.
- **Top features:** day_of_week 0.144, symbol_family 0.140, ssl_score 0.082, bsl_score 0.078, hour 0.078, z_score 0.075, conviction 0.072, tf_minutes 0.071, bars_inside 0.071, inside_pct 0.069.
- **Zero-importance features:** vol_contraction, entropy, duration_bars, confirmers, atr_ratio.
- **Ambiguities:** the train/test split is not stated, and the sweep definition and accumulation detector are in other docs. Default: time-ordered split; sweep = wick beyond the range high/low.
- **Data:** OHLC plus calendar features. Deriv, 14 symbols × 15m/1h/4h.

### A9. `profit_checkpoints`: early exit on OFI reversal at checkpoints. FAILED (not deployed)
- **Source:** EXPERIMENT_RESULTS Exp 5. The consolidated summary wrongly says "Yes".
- **Rule:** on simulated SWEEP-signal trades, checkpoints at 25% of TP1, 50% of TP1, TP1 and TP2. Exit early if the OFI imbalance reverses.
- **Result** (160 trades), static vs checkpoint:

| Metric | Static | Checkpoint |
|---|---|---|
| Win rate | 39.4% | 44.4% |
| Avg PnL | 0.173% | 0.152% |
| Sharpe | 3.21 | 2.87 |
| PF | 2.10 | 2.19 |

- Of 36 checkpoint exits, 24 (67%) hurt.
- Incidentally reports static TP/SL on SWEEP signals with PF 2.10 and Sharpe 3.21. The TP/SL definitions are not given, it is gross, and n=160.

### A10. `liquidity_fatigue`: decayed touch-count per pool. UNTESTED (charter only)
- **Source:** LIQUIDITY_FATIGUE_RESEARCH.md §1–§7. FEATURES.md "Level Fatigue": tired when > 3.
- **Definition:** `F(t+1) = λ·F(t) + 1[touch at t+1]`, with 0 < λ < 1 (not given). There is one series for the SSL pool and one for the BSL pool.
- **Features:** ssl_fatigue, bsl_fatigue, 20-bar deltas, asymmetry `A = F_ssl − F_bsl`, n_ssl, n_bsl, z, ATR, variance ratio, accumulation flag, volume z.
- **Candidate targets:**
  1. Sweep within k ∈ {3, 5, 10, 20} bars.
  2. Break-and-run vs reject.
  3. Max ATR reach over 20 bars in each direction.
  4. Bars to a 1σ reversal.
  5. False-sweep rate (back inside the range within 5 bars).
  6. P/L of trades opened near high-fatigue pools.
  7. Magnet level: which of N levels is reached first within 30 bars.
- **Proposed models:**
  - Hazard: `h = h0·(1 − e^(−βF))`.
  - Magnet multinomial logit: `u_k = −α·d_k(ATR) + β·F_k + γ·q_k`.
  - Simplest directional baseline: A > 0 → bullish drift.
  - Nulls: Brownian first-passage `P(T_L ≤ t) = 2(1 − Φ(L/(σ√t)))` and a Pólya urn.
- **Gates:** beat the shuffle-null by ≥ 5%; replicate on a disjoint 30-day window; fatigue SHAP in the top 5; 300 live events per TF.
- **Ambiguities:** λ, the touch tolerance and the pool definition are unspecified. Default: pools = 20-bar swing highs/lows; touch = wick within 0.1 ATR; λ = 0.9.
- **Data:** OHLC.

### A11. `sweep_messy_clean`: post-sweep behaviour classifier. UNTESTED
- **Source:** LIQUIDITY_NOTIFICATION_RESEARCH.md "messy/clean classifier".
- **Rule:** for each range that ended in a sweep, look at the next 10 bars:
  - "messy" if chop_bars ≥ 3 (bars that reversed direction 2+ times);
  - else "clean" if ≥ 6 bars moved in the reversal direction;
  - else "mixed".
  - Per symbol/TF rates (example: messy 0.72, clean 0.22, mixed 0.06, n=147, which is illustrative). Skip if fewer than 30 sweeps.
- **Validation:** Brier score against a flat 50/50.
- **Related:** sweep aggressiveness = `wick_past_level/ATR × volume_surge_ratio`, bucketed hard/soft (hard example: wick 1.8× average). Reversal invalidation is a close back beyond the level (example: 0.2% past it). Range-break invalidation example: 0.45–0.5% beyond the edge.
- **Ambiguity:** "chop_bars reversed direction 2+ times" is ill-defined. Default: the count of sign changes in close-to-close over 10 bars.

### A12. `post_sweep_confirmation_state_machine`. UNTESTED
- **Source:** same doc, Phase 4.
- **Rule:** states run just swept → confirming (a bar closes cleanly in the reversal direction, holding beyond the swept level) → confirmed or failed. This is an entry trigger on confirmation.
- **Ambiguity:** "cleanly" is undefined. Default: close beyond the swept level and in the reversal direction, with body > 50% of range.

---

## THEME B: Breakout and multi-timeframe coherence

### B1. `breakout_fakeout_tf_coherence`: fade or skip breakouts that fight the HTF trend. CANDIDATE (single sample; replication invalid)
- **Sources:** EXPERIMENT_RESULTS Exp 11 plus the replication attempt; FEATURE_SHIPPING_PRINCIPLES addendum.
- **Rule** ([code] `lab/scripts/experiment_breakout_fakeout_coherence.py`):
  - Breakout UP if `close[t] > max(high[t−20 : t−1])`; DOWN if `close[t] < min(low[t−20 : t−1])`.
  - HTF = about 5× the LTF; pairs are (5m, 1h), (15m, 4h), (1h, 1d).
  - HTF trend = sign of the bar-to-bar change of EMA(span 20) of HTF close.
  - Coherent = breakout direction equals HTF slope sign.
  - Fakeout if, within the next 10 bars (closes c[t..t+10]), the adverse move from the broken level ≥ 0.5 × ATR(14): for UP, `lookback_high − min(close)`; for DOWN, `max(close) − lookback_low`.
- **Results** (466 breakouts): coherent fakeout 52.8% (n=335); discoherent 70.2% (n=131); delta +17.4pp.

| Pair | Discoherent fakeout | Coherent fakeout |
|---|---|---|
| 5m/1h | 72.2% (n=90) | 48.3% (n=205) |
| 15m/4h | 65.8% (n=38) | 60.6% (n=99) |
| 1h/1d | 66.7% (n=3) | 58.1% (n=31) |

- **Replication:** the 60d run was byte-identical to the 90d run because of 2-day 5m retention, so Gate 2 was never tested. The doc decided on paper mode plus live logging only.
- **Proposed trade:** counter-trend (fade) discoherent breakouts, or just skip them.
- **Ambiguities and lookahead flags:**
  - The script aligns the HTF slope with `np.interp`, which linearly interpolates between HTF timestamps. That uses the next HTF bar, so it has lookahead. A faithful re-test should use the last completed HTF bar.
  - "Fakeout" is measured on closes, not a trade P/L.
  - The fade trade itself (entry, stop, target) is unspecified. Default: enter at the close against the breakout, stop beyond the breakout bar's extreme, target the opposite side of the 20-bar range or 1 ATR.
- **Data:** OHLC, Deriv plus crypto.

### B2. `wave_dispersion_multiTF`. UNTESTED
- **Source:** FIELD_EQUATIONS_MARKET_MODELS.md §4.
- **Rule:** for SMA windows {5, 10, 20, 50, 100}, phase velocity = mean |pct change of the SMA| over the last 10 bars. `dispersion = std(velocities)/mean(velocities)`. Low means a coherent trend; high means accumulation or reversal.
- No thresholds are given.

### B3. `mtf_coherence_reversal`: see C5. FAILED

### B4. `consensus_multiTF_attention`: production consensus signal. SHIPPED-UNVALIDATED
- **Source:** FEATURES.md "Consensus as Primary Signal".
- **Per-TF signal:** each TF (default 15m, 1h, 4h) computes z and confidence.
- **TF weights:** 70% from |z| magnitude (normalised) plus 30% from cosine similarity of each TF's 16-dim regime embedding to the cross-TF mean.
- **Combination:** attended_z = weighted mean of z; recommendation comes from attended_z; confidence = weighted mean of confidences, then:
  - × 1.15 if |z| > 2; × 1.05 if |z| > 1.5; × 0.70 if |z| < 0.5;
  - × 1.20 if ≥ 80% of TFs agree; × 0.70 if < 50% agree;
  - × 0.70 if regime conflict > 0.4; × 1.15 if similarity > 0.7.
- **Active signal:** BUY/SELL with confidence ≥ 50.
- **Results:** none.
- **Ambiguity:** z is the ZMA-style z (see I1).

---

## THEME C: Reversal-detection indicators (Exp 9 and 10)

**Common setup:**
- 8 symbols × 5m/15m/1h × 90d, replicated on 60d (with the retention caveat).
- Pivot label: strict extremum over [t−5, t+5], plus follow-through `|close[t+5] − close[t]| ≥ m × ATR(14)`. The doc says m = 0.5; [code] the default is `atr_mult=1.0`, and I did not check the call site.
- Metric: F1 lift over a random null at horizons {1, 3, 5, 10}.
- **None of these is a P/L test.**

### C1. `topology_betti0`: recurrence-graph component collapse. WEAK; replicated as a regime/prevalence feature but no timing edge, so FAILED as a trigger
- **Sources:** EXPERIMENT_RESULTS Exp 9, the 60d replication, Exp 10; FEATURES.md (production −20% confidence when simplifying; the "reversal stack" claims a 10–20 bar lead).
- **Rule** ([code] `lab/sage_features/topology.py` `rolling_betti0`, window 30 in the experiment):
  - Take the last W closes. ε = 0.5 × std(diff(closes)).
  - Adjacency: |p_i − p_j| < ε. betti0 = number of connected components.
  - Recompute on the previous W closes. "Dropping" if current < 0.8 × previous; topo_simplifying = dropping.
  - The experiment also fires if persistence entropy (entropy of component sizes) drops: `pe[t−3] > 0.5 AND pe[t] < 0.6 × pe[t−3]`.
- **Results:**
  - F1 lift, 90d / 60d: h1 +0.024 / +0.027; h3 +0.036 / +0.032; h5 +0.025 / +0.016; h10 +0.025 / +0.008. 1,515 fires.
  - Precision 10 → 28 → 44 → 67% by horizon; recall about 27–30%.
  - Exp 10 lead time to the next pivot within 10 bars: topology mean 4.67 / median 4, random 4.73 / median 4. The percentiles are identical (n = 1,017 vs 1,034).
- **Verdict:** "NOT a reversal-entry trigger … regime-density feature."
- FEATURES.md separately claims "BTC p=0.034, β0 drops 5–10 bars before reversals" from an external repo. Exp 10 contradicts that lead-time claim.

### C2. `kinetic_energy_collapse`. FAILED as an entry; maybe an exit confirm
- **Sources:** Exp 9; FEATURES.md.
- **Rule:** `KE = 0.5 × Vnet²/σ²`. ke_collapse when directed motion is low relative to volatility. The experiment used window 20 and ratio threshold 0.4.
- **Result:** F1 lift h1 −0.022/−0.027, h3 −0.008/+0.007, h5 +0.002/+0.014, h10 +0.017/+0.017. 2,966 fires: "lags, doesn't lead".
- **Production weights (unvalidated):** collapse −50% (−25% in pullback context), rising +15%, falling −15% (+10% in pullback context).

### C3. `rsi_divergence`. FAILED (near-zero lift)
- **Rule** [code]: bearish if price makes a new 20-bar high and `RSI14[t] < max(RSI over the prior 20) − 2`; bullish mirrored with +2.
- **Result:** lift h1 +0.000/−0.029, h3 +0.010/−0.003, h5 −0.017/−0.005, h10 +0.002/+0.000. 368 fires. Precision 5 → 25 → 41 → 62%.

### C4. `liquidity_sweep_reversal` (20-bar). FAILED as a reversal predictor
- **Rule:** a bar takes out the previous 20-bar high (or low) and closes back inside.
- **Result:** lift h1 −0.038/−0.027, h3 −0.035/−0.013, h5 +0.001/−0.022, h10 −0.002/+0.006. 492 fires. Its 63% precision at h10 is a prevalence artefact.
- Consistent with A1.

### C5. `mtf_coherence_disagreement`. FAILED
- **Rule:** signs of the SMA slopes for windows (5, 15, 60); fire if any non-zero signs disagree.
- **Result:** negative lift at all horizons in both windows (e.g. h1 −0.020/−0.024, h10 −0.021/−0.017). 2,204 fires. Dropped.

### C6. `bocpd_reversal`. FAILED (zero fires; untuned)
- **Rule:** BOCPD changepoint prob > 0.2 with the signal flag, window 60. Zero fires in both windows.
- Production use: "EXIT −70%, TIGHTEN −30%" confidence on live trades (FEATURES.md).

### C7. `ofi_flip`. FAILED (zero fires; untuned)
- **Rule:** OFI = 2·CLV − 1, where `CLV = (close − low)/(high − low)`, smoothed over 3–5 bars.
  - Flip up: the last 3 bars had min < −0.2 and now > 0.3. Flip down mirrored.
- Zero fires. The doc says "Zero-fire indicators are a bug, not a result."

---

## THEME D: Physics / field-equation indicators

### D1. `maxwell_curl`: OFI fast/slow momentum crossover. FAILED (sign flipped between windows)
- **Sources:** FIELD_EQUATIONS §2; EXPERIMENT_RESULTS Exp 8; FEATURE_SHIPPING_PRINCIPLES.
- **Rule:** `ofi = 2(close − low)/(high − low + ε) − 1`; `B = diff(ofi)`; `curl = SMA5(B) − SMA20(B)`. Signal at a zero-crossing (bullish when crossing up).
  - The doc uses a centred convolution (`mode='same'`), which leaks future bars. Use trailing SMAs.
- **Results:**
  - Bullish win_rate_5: 44.04% at 60d vs 52.86% at 90d (random 46.31% / 48.00%). Win_rate_10 at 60d was 38.73%.
  - Bearish short-win: 42.51% (60d) and 48.57% (90d). 160 fires each.
- The production ±10% weight was removed on 2026-04-21.

### D2. `entropy_production_transition`. FAILED
- **Sources:** FIELD_EQUATIONS §5; Exp 8.
- **Rule:** S = Shannon entropy (10 bins, log2) of the last 20 log-returns; dS = diff(S). Fire when `dS[t−1] < −0.1 AND dS[t] > 0` (accumulation ending, expansion start, claimed to lead the sweep by 1–3 bars).
- **Result:** 69 fires. Win_rate_5 45.63% (60d) and 44.61% (90d), against random 46.31% / 48.00%. Demoted to logged-only.

### D3. `phase_transition_criticality`: lag-1 autocorrelation near zero. FAILED (edge vanished)
- **Sources:** FIELD_EQUATIONS §3; Exp 8; FEATURES.md "Ising Susceptibility".
- **Rule:**
  - a = rolling-20 lag-1 autocorrelation of log-returns.
  - Criticality = 1/(|a| + 0.01). Fire when it exceeds the 90th percentile (use a trailing percentile; the doc's whole-series percentile has lookahead).
  - Order parameter m = mean(sign(returns over N)).
- **Result:** win_rate_5 49.76% (60d, +3.5pp) and 47.56% (90d, −0.4pp). 263 fires. The weight was cut from 10% to 5%.
- **Production (unvalidated):** Ising transition imminent → ×0.7, or ×1.2 in compression context.

### D4. `damped_oscillator_KG`: damping ratio ζ and natural period. UNTESTED
- **Source:** FIELD_EQUATIONS §1.
- **Rule:** φ = close − SMA50. Regress d²φ on [dφ, φ]: γ = −β₀, ω² = −β₁, ζ = γ/(2ω), period = 2π/ω.
  - ζ < 1: underdamped, ranging. ζ > 1: trending.
  - Leading signal: ζ dropping below 1 → accumulation starting.
- No window or threshold is given. Default: rolling 100 bars.

### D5. `gauge_momentum`: `(dP/dt)/P − σ²/2`. UNTESTED (it is just the GBM log drift)
- **Source:** FIELD_EQUATIONS §6.

### D6. `rg_flow_velocity`: cross-scale change in moment statistics. UNTESTED
- **Source:** FIELD_EQUATIONS §7.
- **Rule:** for scales {5, 10, 20, 50, 100}, compute std, skew, kurtosis and lag-1 autocorrelation of returns at that scale. Flow = mean over adjacent scales of the Euclidean norm of the differences. A spike means breakout. No threshold is given.

### D7. Kramers escape, thermodynamic difficulty, Pdirection, Hawkes cascade, strategy crossover, PLV. SHIPPED-UNVALIDATED confidence weights
- **Source:** FEATURES.md.
- **Weights:**
  - Kramers `P = a·exp(−b|D|)`: P > 0.5 when approaching → +25%; P ≈ 0 → −20%.
  - TD = S_kinetic/σ²: bottom 10% → +30%; top 10% → −30%.
  - Pdirection = `sign(net)·(0.5 + 0.5·DE^0.05)`: confirms +15%, opposes −15%.
  - Hawkes `λ = μ + Σ α·e^(−β(t − ti))`: cascade +35%.
  - Strategy crossover (an "H4 evolutionary game", claimed "6/6 validated, 86–100% reversal rate after crossover", external repo): −50%; crowded trend −15%; crowded reversion +15%.
  - PLV breakdown (claimed "100% precision 19/19", external): −50%.
- **Exp 3 / Exp 7 on these:** Kramers was overconfident (mean 0.979; 97.3% above 0.7). PLV phase-sync added only +0.7pp to sweep-direction accuracy, and PLV > 0.5 was added as factor 8.
- **Status:** none of these has a null-controlled backtest in my files. The external claims are not verified here.

---

## THEME E: Accumulation / regime detection and ML architecture results

### E1. `accumulation_unsupervised`. Descriptive
- **Source:** Exp 1. 484 windows, 14 Deriv symbols × 15m/1h/4h. The rule-based accumulation rate is 54.5%.
- **Results:**
  - GMM (4 clusters) finds a cluster with a 100% accumulation rate, separated by range_width_pct (1.29% vs 6.75%).
  - The MLP clusters run 3.7 → 58.3 → 79.0 → 100%.
  - DBSCAN: 30 windows at 100%, but 93.8% flagged as noise.
  - Isolation Forest failed (40% vs 60.8%).
  - Autoencoder: accumulation has lower reconstruction error (0.43 vs 0.54), meaning "regular state".
  - GMM detects accumulation 5–120 bars later than the rule.
- **Implied rule:** accumulation = range width ≈ 1.3% of price. The rule-based "percentile box" detector is defined elsewhere.

### E2. `pi_features`: cyclical time, Hilbert phase, FFT, PLV, Gaussian CDF for sweep direction. FAILED (except PLV +0.7pp)
- **Source:** Exp 3. 584 samples; base 64.5%.
- **Results:**
  - +cyclical time 64.0%; +Hilbert 64.7%; +FFT 63.2%; **+PLV 65.2%**; +Gaussian CDF 64.5%; all of them together 62.8%.
  - Standalone, all are below the 65.6% always-SSL baseline.
- **PLV:** Hilbert phase at 10/20/40-bar smoothing; fires when PLV > 0.5.

### E3. `ofi_roc_features`. Marginal (+1.4pp)
- **Source:** Exp 4. 629 samples. Base 76.3% → 77.7% with 35 features. ROC alone 73.5%; raw OFI 73.9%.
- **Top features:** cvd_roc 0.049, pressure_10 0.042, ofi_last 0.036, cum_ofi 0.035, pressure_accel_10 0.035.
- OFI is a bar-CLV proxy, so OHLC is enough; CVD needs volume.

### E4. `esn_reservoir`. FAILED
- **Source:** Exp 6. 200 neurons, spectral radius 0.95.
- **Result:** 58.6% vs XGBoost 78.7%; ensemble 77.9%.

### E5. `perceptron_variants`. Informational
- **Source:** Exp 7. About 640 samples, 17 features.
- **Results:** single-layer backprop 71.0% (72.4% in a rerun); hidden-16 no-backprop 72.8%; XGBoost 68.9%; 30-path "path integral" 69.8%; Metropolis "physics" 49.6–59%; quantum 30.7–42.4%.
- **Claim:** "problem is essentially linearly separable."
- The single-layer perceptron is shipped as an ensemble member with XGBoost.
- **Caveat:** the 65.6% always-SSL base rate makes all of these modest.

### E6. `ml_z_forecast`: regress future z_{t+3,5,10,20}. UNTESTED
- **Source:** ML_FORECAST_RESEARCH.md.
- **Setup:**
  - Features: about 100 columns including z, μ, σ, ATR, last 10 returns, KE, Kramers, fatigue, betti0/1, BOCPD posterior and a 16-dim regime embedding.
  - Targets clipped to [−5, 5]. Time-ordered 70/15/15 split.
  - XGBoost: max_depth 4, 200 trees, lr 0.05, with monotone constraints in mean-reverting regimes.
  - MLP: Adam lr 1e-3, batch 64, dropout 0.2.
  - Variant F adds `r_OU = z(t) + θ·z(t−1)·Δt`.
- **Gates:** ≥ 3pp direction accuracy at k=5 over OU, ≥ 10% lower MAE, ΔAUC ≥ 0.02 vs shuffle, 200 live events.
- **Tradable use:** sign of the predicted z_{t+5} as a mean-reversion direction.

---

## THEME F: Behavioural / anchoring

### F1. `round_number_rejection`. FAILED (null)
- **Source:** Exp 12. [code] `lab/scripts/experiment_round_number_reaction.py`.
- **Rule:**
  - Round step ≈ 1% of price, rounded to 1, 0.5 or 0.1 of the order of magnitude.
  - A touch is a high or low within 10 bps of the nearest round level.
  - Wick ratio = (high − max(o, c))/range for an up-touch, (min(o, c) − low)/range for a down-touch.
  - Compare against non-round touches.
- **Result:** 2,941 touches. Mean wick 0.2423 (round) vs 0.2333 (non-round); Welch t = 1.105, p = 0.27.
- **Suggested redo:** hand-curated anchors (whole thousands for BTC, whole cents for EURUSD, a 50-point grid for R_xx), a session-open filter, and per-symbol tests.

### F2. `crypto_attention_decay_short`. CANDIDATE (tiny n)
- **Source:** Exp 13. [code] `lab/scripts/experiment_attention_decay_crypto.py`.
- **Rule:** `mean(volume over the last 5 bars) / mean(volume over the prior 5 bars) < 0.8` AND 5-bar close change > 0 → SHORT. Hold h bars.
- **Results** (4 crypto pairs × 3 TFs × 90d):
  - Cross-symbol h=5: fire −0.112% vs null +0.039% (delta −0.151%); down-win 58.0%. h=10 delta −0.110%, 53.5%.
  - 1h, h=5:

| Symbol | Delta | Down-win |
|---|---|---|
| BTC | −0.519% | 76.9% |
| ETH | −0.116% | 78.6% |
| XRP | −0.675% | 78.6% |
| SOL | −0.297% | 46.2% |

  - Only 13–14 fires per symbol at 1h; no p-values. The 1h data may really be about 9 days (retention).
- **Data:** OHLCV. Suggested enhancements: funding, Google Trends, X mentions.

---

## THEME G: Targets, exits and reach distributions

### G1. `swing_reach_ATR_lognormal` → TP ladder. Descriptive (Gate 1 only)
- **Source:** Exp 14.
- **Swing definition:** pivots are an 11-bar extremum (k=5) with follow-through m = 0.5 ATR. Reach = |p1 − p0|/ATR[t0] between consecutive opposite pivots. 286 swings.
- **Results:**
  - Median reach about 3–4 ATR (p50 coefficient of variation 0.20); p95 6–12 ATR; log-normal fit within 2%.
  - Selected rows (p50 / p75 / p95 / overshoot):

| Symbol / TF | p50 | p75 | p95 | Overshoot |
|---|---|---|---|---|
| R_50 5m | 3.5 | 4.5 | 6.9 | 0.42 |
| R_50 1h | 2.9 | 3.4 | 4.0 | 0.44 |
| BOOM500 5m | 5.3 | 7.3 | 10.9 | 0.54 |
| BTC 5m | 3.5 | 5.4 | 9.7 | 0.40 |
| ETH 1h | 4.7 | 5.6 | 7.7 | 0.56 |
| EURUSD 1h | 3.2 | 5.6 | 11.7 | 0.86 |
| GBPUSD 5m | 4.1 | 4.6 | 8.0 | 0.71 |

  - Overshoot (beats the prior swing) is mostly 0.4–0.55.
- **Proposed rule:** TP1 = p50 (about 3 ATR), TP2 = p75 (4–6 ATR), TP3 = p95 (6–11 ATR). Invalidation if reach < p05 (about 1.8–2.5 ATR against).
- **Caveats:**
  - Reach is measured pivot-to-pivot, so it is not achievable from entry.
  - Small n per cell (7–27); 4h is too sparse.
  - The doc says "do NOT ship as a hard rule".
- Proposed 14b: overshoot by regime (ADX/Hurst), hypothesis > 60% trending, < 40% ranging.

### G2. `key_level_reach_reaction_penetration`. UNTESTED
- **Source:** KEY_LEVELS_FORECAST_RESEARCH.md.
- **Setup:** levels within 1% of price, from topology, BOCPD, multi-TF or cluster detectors. Labels over N bars: reached, reaction (max opposite move after the touch), penetration (close beyond).
- **Models:**
  - Strength score `S = α·log(1 + n_touches)·ρ^β·e^(−λ·Δτ)·V/(V + V0)`, where ρ is persistence and Δτ is bars since the last touch.
  - Bounce: `σ(γ0 + γ1·logS + γ2·|v_a|/σ − γ3·|z| + γ4·overlap)`, with `v_a = (p_t − p_{t−k})/k`.
  - Penetration hazard: `h0·(1 − e^(−β|v_a|/σ))/(1 + S)`. Cox PH baseline.
- **Trading rules proposed:**
  - TP at the nearest level with reach prob > 60%, else the G1 percentile.
  - Do not anchor the stop on a level with penetration prob > 30%; widen beyond the next low-penetration level.
  - Boost confidence when a signal aligns with a high-reach, low-penetration level.
- **Priors:** many touches plus high persistence → strong reaction; fresh levels react harder; low-persistence levels are noise.

### G3. `kde_volume_profile_magnets`. UNTESTED
- **Source:** KEY_LEVELS §9.
- **Rule:** `f(p) = (1/(n·h))·Σ K((p − p_i)/h)·v_i`, Gaussian kernel, Silverman h = 1.06·σ_p·n^(−1/5). Magnets are local maxima. POC = argmax; VA = 70% highest-density interval. Feature: overlap(L) = ∫ f over [p_L − ε, p_L + ε].
- **Data:** OHLCV. For Deriv (no volume), use unweighted density, which is the same as H2.

### G4. `learned_fib_golden_zone`. UNTESTED (parked)
- **Source:** LEARNED_FIB_ZONES_RESEARCH.md.
- **Baseline:** the classical constants (0.236, 0.382, 0.5, 0.618, 0.786, 0.886); golden zone 0.618–0.786; invalidation 0.886.
- **Proposal:** per (symbol, TF), collect impulses. Retrace depth = deepest retracement before resumption (price exceeds the impulse end within N bars) or invalidation (breaks the impulse start).
  - Learned golden zone = p50–p75 of resumed retracements.
  - Learned invalidation = 25th percentile of the invalidated retracements.
  - Requires ≥ 100 resumed samples.
- **Test:** first-half/second-half time split; success = ≥ 3pp higher hit rate than classical.
- **Ambiguities:** the impulse definition and N are unspecified. Default: impulses from H1; N = 2× impulse length.

### G5. `breakeven_1R_plus_ATR_trail`: see A2. FAILED as part of the full system
- §13 blames the ATR trail for giving back too much.

---

## THEME H: Key-level detection methods

### H1. `impulse_orderblock_flip_levels`: ICT/SMC engine spec. UNTESTED (build prompt only)
- **Source:** impulse_key_levels_prompt.md. Config defaults are in parentheses.
- **Impulsive candle** (body only): body ≥ max(k_atr·ATR14 (1.0), k_med·median_body20 (1.5)). Noise if body < 0.1·ATR.
- **Impulsive move:** a single impulsive candle, or ≥ min_run (1) same-direction candles with net |close_end − open_start| ≥ 1.5·ATR and max counter-pullback ≤ 0.5 of the move.
- **Order block (origin zone):** the open–close band of the last opposite candle before the displacement.
- **Engulfing** (body): bullish if current bullish, prior bearish, `open ≤ prior.close` and `close ≥ prior.open`. "Momentum engulfing" if it is also impulsive. A preceding tight small-candle cluster counts as confirmation.
- **FVG:** bullish if `low[c3] > high[c1]`, bearish if `high[c3] < low[c1]`. A body-edges mode is available.
- **Flip key level:** take the most recent impulse origin O. Search backward for an opposite impulse whose terminal price (or origin) is within 0.5·ATR of O.
  - Role: support if close > level, resistance if close < level.
  - Broken when a close is beyond by 0.25·ATR; it then flips role.
  - Lifecycle: untested → tested → respected → broken → flipped.
- **Structural level:** after an impulsive reversal plus a retracement within 5 bars, DBSCAN (eps 0.5·ATR, min_samples 2) over candidate prices between the swept extreme and the impulse extreme. The densest cluster gives the centroid zone.
- **Sweep tag:** equal highs/lows within 0.5·ATR, swept and then reversed with an impulse.
- **Strength 0–1:** range present (30-bar lookback), touch count and average reaction, both-side impulse magnitude, confluence, recency `exp(−0.01·bars)`, volume. Weights unspecified.
- **No trade rule is given.** The natural test is a limit order at flip/OB levels in the trend direction (see A2's caution). Requires strict as-of evaluation (no lookahead).

### H2. `knn_density_levels`. Phase 0 passed (a sanity check only, not predictive)
- **Source:** KNN_AS_LEVEL_CORE_RESEARCH.md.
- **Rule:** point cloud = closes, all OHLC, or wicks (highs plus lows) over the lookback. For each grid price p, `density = K/d_K(p)` (distance to the K-th nearest point). Levels are local maxima, normalised by the max density. K ∈ {5, 10, 20, 50}. Optional time-decay and volume weights.
- **Results** (BOOM600 4h, 30 days):
  - Missed a forward fib-extension target (5384.908) by 4–6%; no other detector got within 1% either (best hl_pivots, 1.65%).
  - Found its own density peak 5700.592 at 0.0072% error, which is circular.
  - 8 of 12 configs land at 5697–5710, the rest at 6034–6080.
- **Planned tests:**
  - Phase 1: about 30 expert levels touched ≥ 3 times.
  - Phase 3: touch rate within ±0.2 ATR over the next 100 bars.
- Complements forward projections; cannot see untouched levels.

### H3. `knn_level_smoothing`: adaptive-K centroid of pivot candidates. Validated on n=1 only
- **Source:** KNN_LEVEL_NOISE_CANCELLATION_RESEARCH.md.
- **Rule:** sort candidate pivot prices by distance to a target or current level. Take the nearest, then add the next ones (up to K = 3) while each is within 0.5 × ATR of the running mean. The estimate is the mean.
- **Result** (R_100 15m, 192h, target 740.62):

| Method | K=1 error | K=3 error | Effect |
|---|---|---|---|
| hl_pivots | 0.05 | 0.0267 | halved |
| l_pivots | 0.05 | 0.433 | worse |
| consolidation | 0.18 | 0.253 | worse |

- Not a signal by itself; a level-refinement step.

### H4. `level_fatigue_tired`: FEATURES.md Tier 1. SHIPPED-UNVALIDATED
- Touch count with exponential decay; > 3 means "about to break". The rest is as A10.

---

## THEME I: Mean-reversion z-score signals and the confidence engine

### I1. `ZMA_strong_z_fade`: attention-weighted z extreme plus momentum matrix. SHIPPED, no backtest in my files
- **Sources:** INTEL_BRIEF appendix and §2. [code] `api/api/sage/peers/zma.py`.
- **z:** over a 50-bar window (period 50; lookback 200 for thresholds), weights = softmax(|pct change|) per bar. z = (last − weighted mean)/weighted std.
- **Thresholds:** strong and weak = rolling percentiles of |z| over the lookback, by regime:

| Regime | Strong pctl | Weak pctl |
|---|---|---|
| trending | 90 | 70 |
| mean-reverting | 80 | 60 |
| neutral | 85 | 65 |

- **Momentum:** split-half slope = (mean of 2nd half − mean of 1st half)/first price × 100, over the window.
  - Above the median |slope| of the lookback: "Rising Demand" if increasing, else "Weakening Demand". Below −median: "Rising/Weakening Supply". Otherwise "Neutral".
- **Rules:**

| Condition | Signal |
|---|---|
| z < −strong AND (Rising Demand or Weakening Supply) | STRONG BUY |
| z < −weak AND same momentum | BUY DIP |
| z < −strong AND (Neutral or Weakening Demand) | BUY (Oversold) |
| z < −strong AND Rising Supply | WAIT |
| z > strong AND (Rising Supply or Weakening Demand) | STRONG SELL |
| z > weak AND same momentum | SELL RALLY |
| z > strong AND (Neutral or Weakening Supply) | SELL (Overbought) |
| z > strong AND Rising Demand | WAIT |

- **Exits and stops:** not defined here. The INTEL_BRIEF uses discretionary targets.
- **Claims:** only anecdotal live prints (ORLY 15m z = 2.92, AMAT 1d 2.56, URI 1h 2.31, LRCX 1d 2.25, ABBV 4h 2.23, EQIX 15m −1.99, USDNOK 1h 1.88). No outcomes are reported.
- **Gate claim:** "SPX above the gamma Vol Trigger → ZMA z > 1.9σ fades work mechanically." This needs options data.

### I2. `multi_peer_convergence`: ensemble plus ZMA agree. SHIPPED, no outcomes
- **Source:** INTEL_BRIEF §2.2 and appendix.
- **Rule:** ensemble direction equals ZMA direction (both BUY or SELL) with ensemble confidence ≥ 79, which means ≥ 3 agreeing peers. The ensemble is a 1.0/1.5/0.6 regime-weighted vote across 9 peers, defined elsewhere.
- 15 live examples are listed, with no results.

### I3. `compression_context_flip`. SHIPPED-UNVALIDATED
- **Source:** FEATURES.md.
- **Detection:** (Shannon entropy compressed AND (coiled spring OR Garman-Klass vol contracting)) OR (coiled spring AND (ranging OR GK contracting)).
- **Multiplier changes** (normal → compression):

| Signal | Normal | Compression |
|---|---|---|
| Kaufman ER "ranging" | ×0.5 | ×1.1 |
| GK contracting | ×0.85 | ×1.15 |
| Ising transition | ×0.7 | ×1.2 |
| VR reversion | ×0.85 | ×1.0 |
| Half-life mean reversion | ×0.8 | ×1.0 |
| Shannon compressed | ×1.3 | ×1.4 |
| Coiled spring | ×1.2 | ×1.35 |
| CFAR breakout | ×1.15 | ×1.3 |

- **Claim:** one V75 M15 trade on 9 Apr 2026 (SSL sweep at 30,100, breakout to 33,200) scored 100 instead of 16, for +10%. n = 1.
- **Ambiguities:** "coiled spring" (directional-efficiency state), the entropy "compressed" threshold and the CFAR parameters are undefined in the doc.

### I4. `pullback_context_buy_dip`. SHIPPED-UNVALIDATED
- **Source:** FEATURES.md.
- **Detection:** VR momentum regime (VR > 1) AND no strategy crossover AND |z| > 1.5 AND ≥ 1 confirmer (Pdirection agrees, f_trend > 0.6, half-life trend regime, or KE falling without collapse).
- **Effects:** base ×1.2; Fisher-opposes, DE-diffusive and Pdirection-opposes neutralised to ×1.0; KE falling ×1.1; KE collapse ×0.75.
- **Claim:** one V75 M5 trade on 10 Apr (32,100 → 33,500, pullback to 32,430) for +2.9%, scoring 100 instead of 47. n = 1.
- **Testable version:** trend (VR > 1 or EMA) plus z beyond 1.5 against the trend → enter with the trend.

### I5. Tier 1–3 feature weights. SHIPPED-UNVALIDATED
- **Source:** FEATURES.md.
- **Weights:**
  - Fisher crossover ±15%.
  - DeMark TD Sequential 9/13 exhaustion +20%.
  - Directional efficiency: ballistic +10%, diffusive −20%, coiled +20%.
  - GK vol: expanding +10%, contracting −15%.
  - Half-life (OU ACF decay): trend +10%, MR −20%.
  - CFAR adaptive breakout +15%.
  - SSL/BSL sweep confirms ±30%.
  - Volume surge +25%, drought −30%.
  - CVD divergence ±20%.
  - VPIN toxic −25%.
  - Amihud spike −20%.
  - Volume-confirmed pool sweep +30%.
- **Parameters:** not given for any of these.
- **Status:** per FEATURE_SHIPPING_PRINCIPLES they should not carry hand weights without a ≥ 3pp replicated edge. None was tested in my files.

### I6. `model_applicability_gate`: no-trade regime filter. SHIPPED-UNVALIDATED
- **Source:** FEATURES.md.
- **Multipliers** (tradeable = false if the product < 0.3):

| Check | Condition | Multiplier |
|---|---|---|
| Vol floor | normalised std < 1e-6 | ×0.1 |
| Vol floor | normalised std < 1e-5 | ×0.5 |
| Tail exponent | α < 2.5 | ×0.5 |
| Tail exponent | α < 3.0 | ×0.7 |
| Hurst | H ∈ [0.48, 0.52] | ×0.7 |
| Hurst | H > 0.65 or H < 0.35 | ×1.1 |
| Feature coverage | < 50% valid | ×0.4 |
| Feature coverage | < 70% valid | ×0.7 |
| Cross-TF conflict | > 0.5 | ×0.5 |
| Bars | < 50 | ×0.3 |
| Bars | < 100 | ×0.7 |

- Usable as a filter test: Hurst-band exclusion and power-law tail gate.

### I7. `timing_state_machine`. SHIPPED-UNVALIDATED
- **Source:** FEATURES.md.
- **States:** IDLE (0 converging signals), ALERT (1–2), READY (≥ 3 and ETA < 20 bars), FIRE (≥ 3, ETA < 5, z extreme).
- **15 converging inputs:** z approach rate, pool proximity, DeMark count, entropy compression, ballistic DE, Ising, Fisher, GK expansion, KE collapse, Hawkes, BOCPD, strategy crossover, β0 simplifying, PLV, sweep happened.
- The ETA method is not defined.

### I8. `regime_embedding_knn_precedent`. SHIPPED-UNVALIDATED
- **Source:** FEATURES.md.
- **Rule:** a 16-dim vector (11 stored as uint8) of KE, TD, Kramers, Hawkes, BOCPD, DE, VR, GK_vol, Shannon, half-life, Fisher, Pdirection. Find the k = 20 nearest by cosine similarity among up to 1,500 history points, using fwd5 and fwd10 returns.
  - STRONG confirms +30%; STRONG opposes −40%; MODERATE ±15/−20%; none plus anomaly > 0.5 → −30%.
  - The STRONG/MODERATE cutoffs are undefined.
- uint8 compression keeps 90.2% neighbour overlap (4,305 embeddings).
- **Testable as an analog/kNN forecaster:** standardise features, find 20 nearest neighbours, trade the sign of the mean fwd5 if ≥ 70% agree. Must be strictly causal: only neighbours whose forward window has closed.

### I9. `in_context_knn_setup_confidence`. UNTESTED
- **Source:** LLM_CONCEPTS §3.2.
- **Rule:** k = 5 nearest past setups (L2 on features, ≤ 90 days old, ≥ 3 required). New confidence = 0.7·parametric + 0.3·(fraction that hit TP2 within 20 bars) × 100.
- **Gate:** Brier score ≥ 10% lower on a 70/30 time split.

### I10. `regime_MoE_thresholds`. UNTESTED
- **Source:** LLM_CONCEPTS §3.3.
- **Rule:** AME expansion threshold of 1.5·ATR when trending, 0.8 when mean-reverting, 1.0 when neutral.
- **Gate:** ≥ 5pp precision lift in at least one regime.

### I11. Other LLM-concept ideas. UNTESTED, low trading content
- Multi-head attention blend of bar weights (volatility, volume, time-decay τ = 50); expected 10–30% more reversals in the top decile.
- Beam-search setup tracking (width 5, max age 20 bars); expected 10–30% WATCH-to-TAKE conversion.
- Self-consistency: N = 5–10 noisy runs, act only if ≥ K agree.
- Peer dropout and temperature knobs.
- Mostly engineering, not OHLC rules.

---

## THEME J: Jump-diffusion (Merton tweaks). All UNTESTED
- **Source:** MERTON_JUMP_DIFFUSION_TWEAKS.md.
- **J1 Jump labelling:**
  - RV = Σr², BV = (π/2)·Σ|r_s||r_{s−1}| over intrabar returns; JV = max(RV − BV, 0).
  - Jump bar if |Z_jump| > 3, or use the Lee-Mykland test.
  - Needs sub-bar data: lower-TF bars or ticks.
- **J2 Tweak 10 classifier:** P(jump at t+1 | x) via logistic regression or XGBoost on σ, ATR, z, OFI, spread and fatigue asymmetry. Gate: ΔAUC ≥ 0.05 vs a Poisson null.
- **J3 Asymmetric jumps:** separate λ+ and λ− (Kou double-exponential). Use up- or down-jump probability as a directional signal.
- **J4 Hawkes jump clustering:** λ(t) = μ + Σα·e^(−β(t − τ)), stationary if α/β < 1, fitted by MLE. Use: aftershock risk.
- **J5 Regime-conditional** parameters (HMM/BOCPD) and **J6 Bates SV** (short vol after a jump, long vol before a breakout).
- **J7 Post-jump mean reversion:** `μ_R = −η(S − S_jump_close)` for τ bars. This is a sweep-and-reclaim fade. Testable: after a labelled jump bar, fade toward the jump-bar close for τ bars. η and τ are unspecified; default τ = 5.
- **J8 Intraday seasonality:** λ(t) = λ̄[1 + A1·cos(2π(t − t1)/24h) + A2·cos(2π(t − t2)/168h)]. Rule: at peak λ, widen stops and halve size.
- **J9 Contagion:** after a BTC jump, pause correlated entries for 1/β_kj bars.
- **J10 Liquidity-scaled jump size:** σ_J = σ_J0·(1 + γ1·spread/median + γ2/depth + γ3·max fatigue). Top decile → halve size. Needs spread and depth data.
- **J11 Fat tails:** Student-t jumps (ν = 3) → 95% reach about 1.5× Gaussian, so widen stops.
- **Gates:** ΔAIC ≥ 10 per tweak; disjoint-window stability within 50%; 200 live events.

---

## THEME K: Macro / discretionary trade ideas (INTEL_BRIEF_2026-06-04)
These are dated one-off trades, not systematic rules. No outcomes are reported. The listed parts are OHLC-checkable as single trades only.

- **K1. USD/MXN long:** entry 19.30–19.50, stop below 18.95, targets 19.95 / 20.40 / 21.20, hold 2–4 weeks. Catalysts: USMCA deadline Jul 1, tariffs. COT: MXN specs +58,154 net long, not crowded, which "confirms". Risk 1%.
- **K2. WTI short into OPEC+ Jun 7:** entry $61–62, stop $64.20, targets 58.50 / 56.80 / 54.50, hold 3–7 days. Size cut to 0.5% because managed money is at a 2-month-low long (squeeze risk).
- **K3. Semicap fade:** AMAT short at 215–220, stop 232, targets 202 / 192 / 182. LRCX Jul $340/$320 put spread, about $6 debit, stop on a daily close > 352. Kill if TSMC raises capex or ASML pre-announces.
- **K4. TOTAL3 long / BTC short** (dominance rotation): $5k each leg; stop when BTC.D > 60.5; target payment-coin basket +15–25% vs BTC.
- **K5. ORLY 15m fade** (intraday only): sell rips above the 15m VWAP; stop at the day high + 0.5·ATR; targets VWAP, day open, prior close; exit by the close; never hold overnight against 4h/1d momentum.
  - **Generalisable rule:** a 15m ZMA STRONG SELL with an opposing 4h ensemble BUY → intraday-only VWAP fade. Testable on intraday OHLCV.
- **K6. Gamma framework:** Call Wall acts as a ceiling (about 83% hold rate per SpotGamma); Put Wall as a floor (about 92%). Below the Vol Trigger, fades stop working. Example: SPX 7,599.96, Call Wall 8,000, Put Wall 7,500, Vol Trigger 7,439–7,537, GEX +$50–73B, VIX 16.1 vs RV 10.3.
- **K7. PBOC fix tell:** a fix stronger than the Reuters estimate is risk-on for Asia; a weaker fix is risk-off for AUD/KRW/EM/copper. Example: 10 days in a row, 400–530 bp weaker.
- **K8. COT crowding filter:** skip longs where specs are at a > 1σ or 52-week extreme short (CAD −68,882, JPY −114,667 at a 22-month extreme, TY record short).
- **K9. Copper/gold vs 10Y regime:** 60-day correlation 0.08 vs a 0.85 baseline, treated as a regime break. The 3.77σ yield-gap claim was refuted 0–3.
- **K10. Watch triggers:** USD/CAD long on a daily close > 1.385 plus EURCAD flipping to BUY (later SKIP). META 1h SELL needs a 4h confirmation at confidence ≥ 75. NVDA short needs an earnings catalyst plus 30D put skew at or above the 90th percentile.
- **Refuted list (do not trade):** Cu/Au yield gap at 3.77σ; "sharper yield drop"; DXY vs Broad Dollar divergence; EM dollar amplification 116.5 vs 128.4; gold/silver ratio < 50; silver > $90 squeeze.

---

## THEME L: Rule-gating from forensics. FAILED
- **L1. `forensic_3rule_gate`**
  - **Source:** FORENSIC_METHODOLOGY.md "Empirical-test gate". [code] `lab/scripts/experiment_gate_validation.py`.
  - **Rule:** accept a signal only if lag-1 autocorrelation ≤ 0.02 AND trend_share ≤ 50% AND no regime break. The trend_share and regime-break definitions are in the script.
  - **Result:** tested on 24 verified Tier-1A signals plus 5 known-fail controls. It accepted only 37.5% of verified signals and passed 40% of failures. The regime-break gate was **anti-predictive**: broken-regime signals had higher out-of-sample hits.
  - **Lesson:** "Forensic insights motivate hypotheses, not deployment rules."

---

## (a) Ideas that cannot be backtested on OHLC or exchange data alone
- **Gamma walls, Vol Trigger, GEX, IV−RV spread, put skew (K6, K10 NVDA):** need options open interest, dealer positioning and the IV surface (SpotGamma or similar).
- **COT crowding (K8):** needs CFTC weekly data. It is public, so it is testable with that data added, but it is not exchange OHLC.
- **PBOC fix vs Reuters estimate (K7):** needs fix and consensus-estimate history.
- **Macro and catalyst theses (K1–K4, K9):** USMCA, tariffs, OPEC+, ETF flows, BTC.D/TOTAL3 index data. Event- and narrative-driven one-offs; TOTAL3/BTC.D need a CryptoCap index.
- **Forensic depth dimensions A–L** (ownership, 10b5-1, dark-pool share, management pay, regulatory dockets): fundamental, alternative and legal data.
- **Merton J1/J2/J10:** bipower jump labels need intrabar or tick returns (approximable with lower-TF bars). Tweak 9 needs book depth and spread history. OFI and whale-print features need order flow.
- **VPIN, true CVD and OFI:** need trade-signed volume. The docs use bar-CLV proxies, which OHLC can approximate. Deriv synthetics have no volume.
- **Attention decay with real attention data (F2 extension):** Google Trends, X mentions, funding.
- **Discretionary 64R M1 edge (A6):** the doc itself calls the human pattern-recognition part unfalsifiable. Only the mechanical proxy is testable, and it needs realistic gold M1 bid/ask.
- **Regime-embedding precedent, ensemble/peer convergence, timing engine, in-context confidence (I2, I7–I9):** depend on the internal peer stack (AME, OB, regime classifier, ensemble weights), which is undefined in these docs. They can be rebuilt only approximately.
- **Notification wording and chain-of-thought / UX items:** not trading rules.

## (b) Files with little or no testable trading idea
- **INTEGRATION_TESTS.md:** spec for strategy integration tests (stubs, lifecycle phases). No trading idea.
- **FEATURE_SHIPPING_PRINCIPLES.md:** research-governance rules. Gate 2: random-bar null, ≥ 3 families × 3 TFs × ≥ 60d, replicate on 60d + 90d. Gate 3: hand weight only if the edge is ≥ 3pp in two independent windows with no sign flip across families. Also the data-retention trap and retention minimums. Methodology only, but useful as test criteria.
- **FORENSIC_METHODOLOGY.md:** qualitative depth standard for equity forensic reports. Its only testable content is the failed gate (L1).
- **LLM_CONCEPTS_RESEARCH.md:** mostly architecture/UX. The testable parts are I9, I10 and the attention-blend claim.
- **LIQUIDITY_NOTIFICATION_RESEARCH.md:** mostly notification wording. Testable parts are A11, A12 and the sweep-aggressiveness metric.
- **impulse_key_levels_prompt.md:** a build spec (H1) with full parameters but no entry/exit rule and no results.


---

# Appendix cat_g5.md

# Catalogue G5 — testable trading ideas in docs/studies (LIT_SCAN … RESEARCH_SUMMARY)

Base: the source. All 36 assigned files read in full. Where a doc left a signal undefined, I checked the defining script with a short grep (cited as "script:").

Abbreviations: **XM** = cross-model protocol (`scripts/experiment_model_predictiveness.py`: 1h bars (~5000), every STEP=24 bars a signal on the last LOOKBACK=100 bars, hit = sign of the 6-bar forward return matches the signal). "slope10" / "slope20" = sign of the OLS slope of the last 11 / 21 closes. **R** = an R-multiple (PnL / initial risk). **IS/OOS** = in-sample / out-of-sample.

---

## 0. Shared methodologies (described once)

### 0.1 Per-instrument lookup protocol (v1 → v4 → OOS-v4 → v5 → v6)
- Universe (17 instruments, 1h, ~5000 bars ≈ 3y): EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, NZDUSD, XAUUSD, XAGUSD (OANDA), USOIL (TVC), DXY (Capital.com), NVDA, AAPL, TSLA, MSFT (NASDAQ), JPM, HD, GS (NYSE).
- Signals are evaluated with XM. The PnL per call is `sign × close.pct_change(6).shift(-6)`, gross, with no costs anywhere in this family. "mean" = the mean signed 6-bar return.
- **Action rule (v4 onward):** DEPLOY if hit>50% and mean>0; FLIP (invert the sign) if hit<50% and mean<0; otherwise DROP. v4 ranks by `(effective_hit−50)×sqrt(n)`. v1 ranked by `(hit−50%)×n×mean`.
- **OOS-v4 split:** choose the action on the first 3000 bars and apply it to the last 2000. Robust if test hit ≥55%, train→test Δ ≥ −15pp and test n ≥ 8.
- **Walk-forward (v5/v6, script-confirmed):** 3 overlapping sub-windows of 3000 bars starting at bars 0, 1000 and 2000. Each window uses a 60/40 train/test split and the DEPLOY/FLIP decision is made on the train part. A window counts as robust if test hit ≥0.55, Δ ≥ −15pp and test n ≥5. Results are reported as "k/3". v6 adds an **"OOS sanity"** check: a single 60/40 split on the full 5000 bars.
- **Regime tags (v5):** vol_regime = HIVOL if the 50-bar ATR/close ≥ its rolling 500-bar median, else LOWVOL. trend_regime = TRENDING if the 50-bar ADX ≥25, else RANGING. Together they form a 2×2 grid.
- **Known flaws to replicate or avoid:**
  - Multiple comparisons: 16 models × 17 instruments × 4 regimes ≈ 1088 cells.
  - The v1/v2 "paper" signals had a gate bug: a sparse metric array meant the rolling p90 was 0, so the gate passed everywhere. The fix drops zeros before taking the quantile.
  - Small n.
  - No costs.

### 0.2 Forensic-report methodology (MUFG v1/v2, Mitsubishi Corp)
- Produced by research agents. Each report is a fundamental and microstructure narrative written to explain *why* lab intraday mean-reversion (MR) or "fatigue" signals converged OOS on one stock.
- Sections: corporate profile, microstructure/liquidity, 2023–26 regime, cross-asset behaviour, why MR works, lab implications (monitor/kill-switch table), and a buy/sell view.
- v2 adds lettered sections C–L: options structure, intraday windows, compensation, capital allocation, reflexivity, analogs, constraints, category check.
- None of the reports backtests anything new. The tradeable content is (i) the kill-switch/event filters and (ii) a few event-reversion priors. Hit-rate claims come from the v6 lookup (§1).

### 0.3 Monte Carlo (MC) VaR-calibration protocol (MC docs)
- Walk-forward and causal: refit on a trailing window at each non-overlapping test point.
- Each engine predicts the H-bar 95%/99% VaR and CVaR. The Kupiec POF test checks breach frequency (p>0.05 = calibrated).
- Over-prediction is treated as safe; under-prediction as unsafe.

---

## 1. Per-instrument "physics/statistical" signal lookup (XM family)

### 1.1 Signal definitions (from docs + script grep; all XM-evaluated, 1h, 6-bar hold)

| id | rule (direction output) | default params |
|---|---|---|
| **Fisher** (`fisher_extreme`) | Fisher transform of the 100-bar window (close/high/low). Fisher ≥ +1.5 → SELL; ≤ −1.5 → BUY (revert) | threshold 1.5 |
| **BOCPD** (v4 tuned) | Bayesian online changepoint posterior `changepoint_prob` ≥ 0.01 (≈p93, fires ~5%) → FADE slope20 | 0.01. The v1 gate ≥0.6 FOLLOW never fired. FOLLOW gave 17% hit on EURUSD and 39% on GBPUSD; FADE gave 83% and 61% |
| **Lyapunov** (v4 tuned) | λ > 0.045 (≈p85) → FADE the recent direction | Old gate λ<−0.01 never fired |
| **Hurst** | H>0.55 → follow slope20; H<0.45 → fade | window 100 |
| **PermEnt** | permutation entropy (order 4) pe_norm <0.92 → follow slope10 | |
| **SpecEnt** | normalised spectral entropy <0.9 → follow slope10 | |
| **Tsallis** | Tsallis q=2 entropy low (vs its history) → follow slope; high → no signal | low-threshold percentile not in doc |
| **Visgraph** | visibility-graph last_degree (last_k=50) in the top decile of its history → fade the recent move | |
| **SoC** | power-law tail exponent α<2.0 → fade the recent move (slope10) | |
| **CurieWeiss** | phase "ordering" & \|m\|>0.1 → follow magnetisation sign; "disordering" → fade | |
| **Ising** | susceptibility `transition_imminent` → predict reversal of the current magnetisation | |
| **Crossover** | topology `strategy_crossover` = crowded-trend crossover True → fade the trend slope | |
| **Betti0** | rolling Betti-0 trend label goes from 'stable' to 'rising' → BUY, or to 'dropping' → SELL | |
| **AME** | production `sage/peers/ame.py`: Accumulation→Manipulation (liquidity sweep)→Expansion (1-ATR expansion candle), ICT power-of-three; BUY/SELL | internal |
| **Bjorgum** | production peer `bjorgum_analyze` BUY/SELL | internals not in docs (ambiguous) |
| **ZMA** | Z-Momentum-Attention peer: TF-attention-weighted momentum z-score (`z_score_period=50`), BUY when \|z\| crosses the dynamic 85th percentile of the \|z\| history (65th = strong tier); vol regime LOW/MID/HIGH over `vol_period=20`; Z-native stop k = {LOW 1.5, MID 2.0, HIGH 3.0}σ; TP at `price_confluence` zones (S/R+S/D+Fib) | see MONTE_CARLO_ZMA §2 |

v6 additions (scripts confirmed):

| id | rule |
|---|---|
| **Fatigue base** | BSL = max(high) over the prior 50 bars (shift 1); SSL = min(low) over the prior 50. Touch = high≥BSL / low≤SSL. Fatigue F(t) = 0.95·F(t−1) + touch. Asymmetry = F_ssl − F_bsl |
| **Fatigue DirectionalAsym** | \|asym\| ≥ rolling-500 q70 of \|asym\| → sign(asym) (+ = SSL tested repeatedly → BUY) |
| **Fatigue SweepPredict** | F_ssl ≥ rolling-500 q80 → BUY; else F_bsl ≥ q80 → SELL |
| **Fatigue FadeSweep** | this bar touches SSL and F_ssl(t−1) ≥ q80 → BUY (reclaim); BSL touch with F_bsl high → SELL |
| **MaxwellCurl** | OFI_bar = 2(close−low)/(high−low) − 1; B = diff(OFI); curl = mean5(B) − mean20(B). Any curl zero-crossing in the last 24 bars: up-cross → BUY, down-cross → SELL (trade the new sign) |
| **WaveDispersion** | velocities \|ΔSMA_tf\|/SMA_tf for tf ∈ {5,10,20,50,100}; dispersion = std/mean across tf. Fires when dispersion ≤ rolling-500 q20 → follow slope10 |
| **EntropyProd** | S = Shannon entropy (10 bins) of the last 20 log-returns; fires when dS goes from <0 to >0 (−→+) → follow slope10 |
| **Omori-p** | mainshock = \|r\| > rolling-500 p95 within the last 48 bars; aftershocks = \|r\| > p80. Fit p from log(cum-exceed rate) vs log t. If p > rolling median + 0.5·std → FADE slope10; if p < median − 0.5·std → FOLLOW |
| **RQA-LAM (fixed)** | RQA laminarity (m=3, τ=1) of 199 log-returns over a 200-bar window. LAM ≥ rolling q75 (zeros removed) → follow slope10 |
| **DHVG-KL (fixed)** | KL divergence of the in- vs out-degree distributions of the directed horizontal visibility graph on 100 closes. ≥ rolling p90 → follow slope10 |
| **POT_TailGate (fixed)** | GPD ξ fit to excesses over p95 of the last 500 negative log-returns. ξ ≥ rolling p90 → FADE slope10 |
| **H1_Loops** | persistent-homology H1 gate → follow slope (passed only because of the bug) |

Data needed: OHLC only.

### 1.2 v1 lookup (PER_INSTRUMENT_BEST_MODEL.md) — IS only, 6 models
Status: superseded and not OOS-validated (its own caveat says so).

| Instrument | best model | hit | n | mean/call |
|---|---|---|---|---|
| GS | crossover | 80.0% | 10 | +1.12% |
| EURUSD | bjorgum | 75.0% | 16 | +0.07% |
| NVDA | bjorgum | 72.2% | 18 | +0.43% |
| JPM | fisher | 70.0% | 20 | +0.93% |
| TSLA | crossover | 63.6% | 11 | +1.91% |
| XAUUSD | betti | 63.6% | 33 | +0.42% |
| MSFT | crossover | 63.6% | 11 | +0.20% (betti 61%, +0.32%) |
| USOIL | betti | 61.0% | 41 | +0.24% |
| DXY | ame | 51.9% | 181 | +0.02% |
| HD | NONE | — | — | — |
| AAPL | bjorgum | 60.0% | 25 | −0.16% (suppress: asymmetric loss) |

- **HD, all models:** AME 50.0% / +0.04%, Bjorgum 26.3% / −0.57% (n=19), Fisher 45.8% / +0.14%, Crossover 36.4% / −0.40%, Betti 41.2% / −0.12%.
- **Crossover on AAPL:** 42% / −0.92%.
- **Per-model averages (forex / stock):** Bjorgum 59.8 / 55.9; Betti 57.4 / 53.4; Crossover 56.1 / 54.5; AME 50.2 / 50.6; Fisher 48.1 / 53.8; BOCPD 0 calls.
- **Proposed gating:** tier "high" if hit>65% and mean>0; "normal" if 55–65%. min_conf 0.55–0.65.

### 1.3 v4 lookup (PER_INSTRUMENT_BEST_MODEL_V4.md) — IS, 16 models, flip discipline (✓ as-is / 🔄 flip)

| Inst | #1 | #2 | #3 |
|---|---|---|---|
| EURUSD | ✓BOCPD 83.3% (12) | ✓Bjorgum 75.0% (16) | ✓Lyapunov 64.5% (31) |
| GBPUSD | 🔄AME 56.3% (183) | 🔄Lyapunov 58.7% (46) | ✓ZMA 66.7% (12) |
| USDJPY | 🔄Ising 76.5% (17) | ✓SpecEnt 60.2% (98) | 🔄Visgraph 66.7% (15) |
| AUDUSD | 🔄Bjorgum 63.9% (36) | 🔄Ising 69.2% (13) | ✓Hurst 55.0% (149) |
| USDCAD | ✓Tsallis 58.8% (80) | ✓PermEnt 56.1% (132) | 🔄Bjorgum 62.1% (29) |
| NZDUSD | 🔄Visgraph 70.6% (17) | 🔄Fisher 66.7% (18) | ✓AME 54.7% (179) |
| XAUUSD | ✓Betti0 63.6% (33) | 🔄CurieWeiss 65.2% (23) | ✓Bjorgum 62.5% (32) |
| XAGUSD | 🔄Bjorgum 78.9% (19) | 🔄Hurst 59.3% (145) | 🔄Fisher 66.7% (18) |
| USOIL | 🔄ZMA 77.8% (27) | ✓AME 56.2% (178) | ✓Betti0 61.0% (41) |
| DXY | ✓ZMA 72.7% (22) | ✓Tsallis 57.6% (85) | 🔄PermEnt 54.7% (150) |
| NVDA | ✓CurieWeiss 72.0% (25) | ✓BOCPD 68.6% (35) | ✓Bjorgum 72.2% (18) |
| AAPL | ✓BOCPD 71.4% (28) | 🔄ZMA 70.6% (17) | ✓CurieWeiss 66.7% (12) |
| TSLA | ✓BOCPD 61.1% (36) | 🔄SpecEnt 56.2% (80) | ✓Crossover 63.6% (11) |
| MSFT | ✓Betti0 61.1% (36) | ✓ZMA 63.6% (22) | ✓AME 54.3% (184) |
| JPM | 🔄PermEnt 58.5% (159) | ✓Fisher 70.0% (20) | 🔄SpecEnt 58.8% (85) |
| HD | ✓SoC 62.7% (161) | 🔄Tsallis 62.6% (99) | 🔄PermEnt 60.3% (141) |
| GS | ✓BOCPD 75.0% (20) | ✓Crossover 80.0% (10) | ✓SoC 56.4% (172) |

- Claims: 21 of 51 cells are flipped (41%). The durable "spine" is AME (7 top-3 appearances), BOCPD (5), Bjorgum (5) and ZMA (5).
- Status: IS only. Superseded by the OOS check below.

### 1.4 OOS validation of v4 (OOS_VALIDATION_V4.md) — 60/40, the honest version
- **Aggregate:** 180 pairs. Average train hit 60.7% → test 52.1% (Δ −8.6pp, median −6.3pp). 74/180 have test hit ≥55%.
- **Per-model decay (n instruments, avg Δpp, avg test hit):**

| model | n | avg Δ (pp) | avg test hit |
|---|---|---|---|
| Betti0 | 11 | −1.7 | 55.3 |
| PermEnt | 12 | −2.6 | 52.8 |
| AME | 14 | −3.3 | 50.3 |
| Fisher | 11 | −3.8 | 57.0 |
| Tsallis | 13 | −6.4 | 49.9 |
| Hurst | 11 | −6.6 | 49.1 |
| Bjorgum | 10 | −6.6 | 62.7 |
| SoC | 11 | −7.0 | 48.5 |
| CurieWeiss | 10 | −9.2 | 52.2 |
| SpecEnt | 12 | −10.6 | 46.2 |
| Crossover | 7 | −11.3 | 56.5 |
| Lyapunov | 11 | −11.8 | 49.9 |
| Ising | 8 | −12.5 | 51.9 |
| BOCPD | 13 | −12.7 | 52.9 |
| ZMA | 14 | −14.6 | 53.7 |
| Visgraph | 12 | −17.6 | 47.9 |

- **Robust-pair filter** (test ≥55%, Δ ≥ −15, n ≥ 8): 54/180 pass. Top-3 per instrument (OOS test hit):

| Sym | #1 | #2 | #3 |
|---|---|---|---|
| EURUSD | ✓Bjorgum 75.0% (8) | ✓Lyapunov 71.4% (14) | ✓Visgraph 66.7% (9) |
| GBPUSD | 🔄AME 60.5% (76) | ✓Tsallis 58.7% (46) | 🔄Lyapunov 57.1% (21) |
| USDJPY | 🔄Crossover 62.5% (8) | ✓Hurst 57.4% (54) | 🔄Tsallis 57.1% (49) |
| AUDUSD | ✓SpecEnt 59.1% (44) | 🔄Betti0 57.1% (14) | 🔄SoC 56.8% (37) |
| USDCAD | ✓ZMA 62.5% (8) | 🔄Lyapunov 58.3% (12) | ✓PermEnt 57.4% (54) |
| XAUUSD | none | | |
| XAGUSD | 🔄Bjorgum 83.3% (6) | 🔄Fisher 77.8% (9) | 🔄Hurst 58.3% (60) |
| USOIL | 🔄ZMA 76.9% (13) | ✓Betti0 66.7% (18) | — |
| DXY | ✓Tsallis 60.0% (50) | — | — |
| NVDA | ✓BOCPD 72.7% (11) | ✓Bjorgum 70.0% (10) | ✓Betti0 66.7% (18) |
| AAPL | ✓BOCPD 64.3% (14) | — | — |
| TSLA | ✓Tsallis 58.3% (36) | ✓BOCPD 57.1% (14) | 🔄PermEnt 55.4% (56) |
| MSFT | ✓BOCPD 64.3% (14) | ✓Betti0 63.6% (11) | ✓AME 56.6% (76) |
| JPM | ✓Fisher 80.0% (10) | 🔄SpecEnt 65.7% (35) | 🔄PermEnt 60.3% (63) |
| HD | 🔄Bjorgum 77.8% (9) | 🔄PermEnt 70.9% (55) | 🔄CurieWeiss 63.6% (11) |
| GS | ✓Bjorgum 77.8% (9) | ✓Fisher 77.8% (9) | ✓BOCPD 69.2% (13) |
| NZDUSD | none | | |

- Note: the XAGUSD Bjorgum n=6 row is below the stated n≥8 filter but is listed in the doc.
- Claim: "boring" models (Bjorgum, Fisher, Betti0, PermEnt) hold up; BOCPD and Visgraph were curve-fit.
- Elsewhere (WALK_FORWARD_STABILITY_V4, not my file, quoted in v5): only **3/118** v4 pairs survive 3/3 walk-forward — BOCPD-AAPL, BOCPD-TSLA, Hurst-XAGUSD (flip).

### 1.5 v5 regime-conditional (REGIME_CONDITIONAL_V5.md)
- **Single-split:** 17/17 instruments had at least one robust regime cell. Examples:
  - EURUSD PermEnt FLIP, HIVOL/TRENDING: 88.9% (9), +24.2pp
  - USDJPY PermEnt, HIVOL/RANGING: 88.9% (9), +36.5pp
  - GBPUSD AME FLIP, HIVOL/TRENDING: 81.8% (11), +29.6pp
  - GS AME, LOWVOL/TRENDING: 88.9% (9), +26.4pp
  - DXY Tsallis, LOWVOL/RANGING: 84.2% (19), +19.9pp
  - NVDA Betti0, LOWVOL/RANGING: 100% (6), +28.6pp
- **Walk-forward:** 1/3 windows = 144 cells (77.4%); 2/3 = 37 (19.9%); **3/3 = 5 (2.7%)**. Without regime conditioning v4 managed 3/118 (2.5%), so regime conditioning is no rescue.
- **Combined 3/3-robust list (v4+v5):**

| Sym | Signal | Regime | Dir |
|---|---|---|---|
| AAPL | BOCPD | all | as-is |
| TSLA | BOCPD | all | as-is |
| XAGUSD | Hurst | all | flip |
| DXY | SpecEnt | LOWVOL/RANGING | as-is |
| DXY | Tsallis | LOWVOL/RANGING | as-is |
| GBPUSD | PermEnt | HIVOL/RANGING | flip |
| HD | Hurst | LOWVOL/RANGING | flip |
| USOIL | AME | LOWVOL/RANGING | as-is |

- Claim: entropy/physics signals work best in LOWVOL/RANGING.
- Untested next ideas in the doc:
  - Session tagging (Bjorgum-EURUSD in London only).
  - 4 tuned models instead of 16.
  - Cross-instrument transfer.
  - A vol-of-vol (ATR rate-of-change) regime.

### 1.6 v6 sweep (NEW_SIGNAL_SWEEP_V6.md) — fatigue + field equations + papers

**Verified 3/3 (OOS sanity on full 5000 bars, 60/40):**

| Sym | Signal | Dir | Test hit (n) | Δ |
|---|---|---|---|---|
| HD | Fatigue FadeSweep | as-is | 0.769 (13) | +13.3pp |
| USOIL | Fatigue SweepPredict | FLIP | 0.618 (34) | +18.3pp |
| EURUSD | WaveDispersion | FLIP | WF 0.60/0.70/0.64 | — |
| NVDA | MaxwellCurl | as-is | WF 0.56/0.56/0.55 | — |

**2/3 with positive OOS sanity:**

| Sym | Signal | Dir | OOS test hit |
|---|---|---|---|
| HD | Fatigue DirectionalAsym | as-is | 0.679 (28, +11.8pp) |
| HD | Fatigue SweepPredict | as-is | 0.658 (38, +9.2pp) |
| AAPL | Omori-p | as-is | 0.610 (59, +10pp; train 0.510) |
| DXY | MaxwellCurl | as-is | WF 0.52→0.56 |
| DXY | EntropyProd | as-is | WF 0.67/0.71 |
| AUDUSD | WaveDispersion | as-is | WF 0.64/0.60 |
| JPM | WaveDispersion | as-is | WF 0.69/0.75 |
| NVDA | EntropyProd | as-is | WF 0.62/0.71 |
| HD | WaveDispersion | FLIP | WF 0.91/0.91 |
| AAPL | WaveDispersion | FLIP | WF 0.57/0.64 |

**Omori-p, other instruments:**
- XAGUSD 0.579 → 0.544 (n=57, −3.5pp): borderline.
- MSFT 0.602 → 0.524 (n=63, −7.8pp): fails.

**Post-gate-fix addendum:**
- AUDUSD: RQA_LAM 1/3, H1_Loops 1/3, DHVG_KL 2/3. DHVG_KL FLIP OOS 0.600 → **0.875 (n=8, +27.5pp)**.
- **HD RQA-LAM is 3/3:** W1 0.56 (18), W2 0.64 (14), W3 0.65 (17). OOS 0.537 → 0.655 (n=29, +11.9pp).
- New 2/3 with OOS:
  - NZDUSD POT_TailGate as-is: 0.667 (15, −3.3pp)
  - XAUUSD DHVG_KL as-is: 0.667 (9, +7.6pp)
  - AAPL DHVG_KL: 0.533 (15, +1.3pp), borderline
- **Final "19 verified signals / 10 instruments" lookup:**
  - AAPL BOCPD as-is; AAPL Omori-p as-is
  - AUDUSD DHVG-KL flip
  - DXY SpecEnt and DXY Tsallis (both LOWVOL/RANGING, as-is)
  - EURUSD WaveDispersion flip
  - GBPUSD PermEnt flip (HIVOL/RANGING)
  - HD FadeSweep, DirectionalAsym, SweepPredict, RQA-LAM (all as-is); HD Hurst flip (LOWVOL/RANGING)
  - NVDA MaxwellCurl as-is
  - NZDUSD POT_TailGate as-is
  - TSLA BOCPD as-is
  - USOIL AME as-is (LOWVOL/RANGING); USOIL Fatigue SweepPredict flip
  - XAGUSD Hurst flip
  - XAUUSD DHVG-KL as-is
- **HD kill switch:** disable HD if the 30-yr mortgage rate < 5.5% (external macro data).

**FAILED in v6:**
- These never fired: HVG-θ (Sikorski 2025; first-passage Hill-MLE gate on a 200-bar window), LZ76 (Niu 2015), C-E plane (Rosso; needs low H and high C together), DampedOsc (Klein-Gordon; 0.3≤ζ≤1.0 gate on a 100-bar window), RG Flow.
- The H1/DHVG/RQA trio on USOIL fails OOS (0.564 → 0.482, −8.2pp).
- GS POT_TailGate fails OOS (−30.6pp).
- The AUDUSD "trio convergence" was the gate bug: all three gave the same 0.554 hit on the same 200 bars.

**Caveats:**
- n is tiny (8–59).
- No costs.
- MUFG v2 explicitly says the four MUFG signals "are not independent confirmations… treat them as one signal".
- Overall status: **in-sample-selected; treat as hypotheses.** The meta-docs (RESEARCH_SUMMARY, NN_MODELS) conclude that price-based direction is ≈50% everywhere.

### 1.7 Forensic-report instrument findings (methodology §0.2)
- **MUFG (8306.T / NYSE ADR MUFG), v1 + v2.**
  - Claimed signals: Maxwell-curl, liquidity-fatigue DirAsym, H1 persistent loops, Omori-p. Hit 0.59–0.68 at n=49–50 across 3 windows. v2 claims an expected edge of ~12–18 bp per trade net in non-event sessions; this is an asserted prior, not a backtest.
  - Rules/filters:
    - Position cap < 0.5% of ADR ADV.
    - KILL if \|Δ 10-yr JGB yield\| > 15bp/day.
    - PAUSE if USDJPY moves >1.5% intraday.
    - FLATTEN the day before a BoJ MPC, JGB auction or rinban change.
    - KILL on Morgan Stanley earnings days (third Wednesday of Jan/Apr/Jul/Oct, US pre-market). v2 says to exclude those 4 days per year as expected-loss days.
    - Kill on USTR/tariff headlines.
    - Re-test if foreign ownership drops.
    - Don't run trend signals.
  - Event priors (testable with daily data plus an event calendar):
    - After a YCC band change, 8306 is +3 to +5% on the day and mean-reverts ~60% over 5 sessions.
    - The ADR-vs-8306 overnight gap is faded beyond ~80bp (a claimed no-arb band).
    - Afternoon opening prints overshoot after lunch-break (11:30–12:30 JST) news.
    - The MOC imbalance at month/quarter-end is large.
    - A 9:00–9:30 auction gap-fill.
    - Round-yen strike pinning at ¥2,900/3,000/3,100.
    - Long-term: buy BoJ-driven sell-offs >5%.
  - Falsifiers (v2):
    - A >40bp single-day JGB move.
    - The cross-share sell-down < ¥150B by 30 Sep 2026.
    - Q1 FY26 flat/down ex-MS.
    - MS net income −20% YoY twice.
  - Data: tick/intraday JST, an event calendar, and JGB/MS data. Mostly not OHLC-only.
- **Mitsubishi Corp (8058.T).**
  - Claimed: DirectionalAsym +6.6pp (n=32) and SweepPredict +16.9pp (n=39), both OOS. "Deploy as Tier-1A."
  - Monitors:
    - Suspend during the post-earnings buyback blackout.
    - Bypass Berkshire stake-disclosure days (every 0.5% increment).
    - Auto-throttle on abrupt JPY appreciation.
    - Disable if Henry Hub or iron ore moves >2σ.
    - Re-evaluate if the 20-day correlation to 8031/8001/8053/8002 collapses.
    - Cap combined DirAsym+SweepPred gross at the single-signal max.
  - Long-term: hold, add on commodity-led drawdowns ≥10%.
  - Data: daily/intraday JP equities, commodities, filings.
- **HD** (referenced via v6, its own report not in my list): it is a multi-signal hub, killed when the mortgage rate < 5.5%.

---

## 2. Mean-reversion family

### 2.1 fx-cross-zscore-mr (MEAN_REVERSION_SCOPE.md Pass A + build pass) — FAILED as a portfolio
- **Rule:** z = (close − SMA48)/std48. Fade when \|z\| ≥ 2. Exit when z reverts (doc: "exit on revert"; most faithful default is z crossing 0), on a stop at \|z\| ≥ 4, or after 96 bars. Bar timeframe is not stated (likely 1h).
- **Universe:** 28 FX crosses. Ex-ante filter on the IS 60%: Hurst, AR(1) half-life, variance ratio.
- **Pass A (2bp cost, OOS 40%):**
  - corr(Hurst, OOS profit) = −0.25.
  - Hurst<0.5 (25 crosses): +1.8 bps/trade, 18/25 positive. Hurst ≥0.5 (USDJPY, EURUSD, USDCHF): −3.9 bps, 1/3 positive.
  - Best crosses: AUDCHF +8.6, NZDCHF +6.4, CADCHF +5.9, AUDUSD +4.2 bps. Win rates 59–73%.
- **Portfolio build** (12 lowest-IS-Hurst non-USD crosses, vol-normalised equal weight, 3bp spread, OOS):
  - Per-cross Sharpe average −0.47, 2/12 positive.
  - Average pairwise correlation +0.15 (4.5 effective bets).
  - **Portfolio Sharpe −0.97, −2.2%/yr, maxDD −4.2%.**
- **Status: FAILED.** Hurst does not pick the OOS winners, and a 3bp cost kills the edge. Verdict: "Do not pursue as a systematic forex-MR strategy."

### 2.2 dxy-residual-statarb (MEAN_REVERSION_SCOPE.md) — FAILED (one pair only)
- **Rule:** USD pair vs DXY with a rolling hedge; z-fade the residual. Residual Hurst used as the selector.
- **Results (OOS):**
  - USDJPY +11.3 bps, Sharpe +0.83 (59 trades).
  - USDCAD +1.9, Sharpe −0.26.
  - EURUSD/GBPUSD/AUDUSD/NZDUSD/USDCHF negative (Sharpe −0.6 to −2.9).
  - Residual Hurst ≈0.90 for every pair, so the selector picks nothing.
  - Pass B pooled: −6.6 bps (USDJPY +12.3, USDCAD +2.9).
- **Status: FAILED.** USDJPY is likely a BoJ-intervention artifact.
- **Data:** DXY series.

### 2.3 dxy-lead-lag / outright-usd-mr (MEAN_REVERSION_SCOPE Pass B) — FAILED
- **Rules:**
  - Lead-lag: a DXY basket z-score → trade the pair in the implied direction.
  - Outright MR on USD majors.
- **Results (OOS, 2024–26):**
  - Lead-lag −2.4 bps pooled with a 59% win rate (the trend tail kills it).
  - Outright MR −3.7 bps.
- **Untested:** a VIX gate (calm bucket n=6; needs VIX forward-filled to FX hours).
- **Status: regime-dependent, not validated.**

### 2.4 proven-level-fade (PROVEN_LEVEL_FADE.md) — FAILED / SHELVED; mechanism is an artifact
- **Rule:**
  - Levels are 5-bar swing (pivot) highs/lows.
  - A touch is a bounce if price moves 1.5 ATR away before breaking; a break if the close clears the level. Stop counting at the first break.
  - Fade at a touch (short resistance / long support) only when prior bounces ≥4.
  - Stop 1.0 ATR beyond the level. Target 2.5 ATR; 3.0 in the best config.
  - Best config: limit entry 0.5 ATR deeper than the level, stop 1.0 ATR beyond the level, target 3.0 ATR, barriers checked intrabar. Cost 2bp round trip.
- **Results:**
  - P(break \| k prior bounces): 0.573, 0.437, 0.317, 0.220, 0.172, 0.142, 0.077 for k = 0…6+. Based on 215k touches.
  - First pass +0.266R with close-only barriers. **Do not cite.**
  - Intrabar: baseline +0.019R (32% win); buffer config +0.092 ± 0.062R (20% win), sealed OOS 30%.
  - Breadth: OOS all n=7,979, +0.091. Random control −0.567. Forex +0.099. Crypto −0.998 (n=64).
  - Winners: AUDNZD +1.49 (735), AUDCHF +1.18, AUDCAD +1.05. Losers: EURGBP −0.259 (2081), EURCHF −0.646 (843).
- **Variants:**
  - Hybrid exit (bank at 3 ATR, runner to breakeven plus level-trail): +0.000 ± 0.116.
  - Level-trail exit: maxR +85 but median −1.
  - Kaufman ER<0.3 gate: OOS +0.105 vs +0.101 ungated, i.e. no effect.
- **Mechanism figures:** median MAE past a level is −1.5 ATR; 47% of losses are whipsaws; breaks run 2.2× the stop.
- **Status: FAILED.** The bounce-count decline is a selection artifact. Slope of P(break) over k=0..4:
  - Constant-vol synthetic GBM: −0.041
  - Boom/Crash: −0.105
  - Real FX: −0.027
  - Real metals: −0.024
  - Real crypto: +0.002
- **Data:** OHLC.

### 2.5 pip-pattern-discovery (PIP_PATTERNS.md) — FAILED (reduces to RSI-MR)
- **Rule:**
  - Daily crypto (21 Binance coins). Window W=24 bars → M=6 perceptually important points (PIPs, by vertical distance) → z-scored shape vector.
  - KMeans k=24 fitted on train. Forward 5-day return, non-overlapping (stride = 5).
  - Select clusters with \|train edge\| > 1.2%. Trade OOS at 7bps.
- **Results:**
  - Naive version (stride 3, k=40): 10/40 clusters significant, an artifact of overlapping windows.
  - Disciplined version: 3/22 clusters with \|t\| > 2.49, vs a circular-shift null (×30) of mean 0.4, 95th percentile 2, max 2.
  - Traded: 8 patterns, 903 trades, +0.92%/trade, 52% win, **OOS net Sharpe +0.58**.
  - Example shapes:
    - [+0.7 +0.9 −0.4 +0.6 −0.1 −1.7] → bullish +3.3%, 66% win.
    - [+0.5 −0.1 +1.4 −0.5 +0.2 −1.5] → bullish +3.5%, 60% win.
    - [+1.3 +1.1 −0.9 −0.1 −1.1 −0.3] → bearish −3.1%.
- **Descriptor variants (base +0.53):**

| descriptor | OOS net Sharpe |
|---|---|
| + x-positions | +0.38 |
| multi-scale | −0.18 |
| + topo | +0.53 |
| **RSI-PIP** | **+0.97 (+1.73%/trade)** |
| Markov transitions | −0.49 |

- **PIPs on other indicators:** OBV +0.33, MFI +0.24, ROC +0.12, BBpctB −0.22, Stoch −0.34, WillR −0.34, CMF −0.35, MACDhist −0.55, CCI −1.15. RSI beats its null (95th percentile 0.54).
- **Robustness (RSI-PIP):**
  - Holdout coins: +0.68.
  - Costs 0→15bps: 0.73→0.63.
  - Each year 2024–26 positive.
  - **Parameter-fragile:** grid median +0.30, min −1.68. Neighbours: M=5 −0.45, M=7 −0.30, FWD=3 −1.68, W=32 −0.07, rsi=10 −0.27.
  - **Plain RSI-MR (RSI<30 long / RSI>70 short) = +1.02**, which beats it.
- **Status: FAILED** (pattern geometry adds nothing).

### 2.6 rsi-mr (PIP_PATTERNS.md) — WEAK / regime-dependent
- **Rule:** daily crypto; long when RSI<30, short when RSI>70. Hold 5 days is the default implied by the PIP harness. RSI period presumably 14 (a neighbour test used rsi=10).
- **Results:** Sharpe +1.02 in 2024–26 vs +0.23 full-sample (indicator_zoo).
- **Status:** regime-dependent and not deployed.

### 2.7 fx-sweep-exhaustion-fade & AME entry (PRICE_EDGE_SWEEP.md)
- **Rule:** fade a liquidity sweep or a z≥2 overbought/oversold (exhaustion fade). AME variant: wait for the 1-ATR expansion candle after the sweep.
- **Results (mean per trade):**

| panel | post-sweep vs base | AME vs sweep-only | z-fade now vs wait-for-AME |
|---|---|---|---|
| Crypto 1h | −0.115% vs +0.009% (sweeps continue) | −0.093% | −0.191% vs −0.188% |
| FX D1 | **+0.075% vs +0.008%** | 0.060 < 0.072 | **+0.091% (51%) vs +0.063% (48%)** |
| FX H4 | +0.020 vs +0.005 | −0.019 | +0.028 vs −0.011 |

- **Status:** FX D1 exhaustion fade is real but thin (DSR≈0, Sharpe ≈0.05; the spread eats much of it). AME confirmation FAILS (degrades entries). The crypto fade FAILS.

### 2.8 mtf-geometry (MTF_GEOMETRY.md) — FAILED
- **Setup:** Binance 1h entries off 1d setups; tight LTF-swing stop; HTF target; first-touch simulation.
  - MR archetype: daily z>2 vs 20d MA → fade toward the HTF mean or extreme.
  - Continuation archetype: 20d momentum + LTF pullback → target the HTF extreme.
- **Results (gross):**

| archetype / config | n | win% | avgWin | avgR | PF |
|---|---|---|---|---|---|
| MR → mean | 6540 | 21% | +3.23R | −0.11 | 0.86 |
| MR → extreme | 6544 | 19% | +3.71R | −0.11 | 0.87 |
| Cont → extreme, stop 12h | 48659 | 24% | +3.07R | −0.03 | 0.95 |
| Cont → extreme, stop 24h | 26731 | 30% | +2.19R | −0.03 | 0.95 |
| Cont → extreme, stop 48h | 14106 | 37% | +1.56R | −0.03 | 0.95 |
| Cont → mean, stop 12h | 11159 | 40% | +1.41R | −0.04 | 0.93 |

- LTF timing improved MR from −0.17 to −0.11R.
- **Status: FAILED** (net negative). Keeper: in crypto, go with the HTF trend.
- **Ambiguity:** "stop 12h/24h/48h" presumably means the LTF-swing lookback for the stop.

### 2.9 reversal-ml (METALS_ML.md §5–7) — FAILED to trade (AUC real)
- **Label:** a top or bottom forms within the horizon (ITB-style), vol-adaptive level ≈3σ.
- **Model:** LightGBM (beats LSTM/CNN/Transformer/TFT).
- **Held-out AUC:** gold 1h 0.64, silver 1h 0.59, gold 5m 0.70, silver 5m 0.65, gold 1d 0.62, silver 1d 0.65. Direction AUC is 0.52–0.56.
- **Breadth (120 instruments, mean AUC):** forex 0.595, index 0.599, synthetic 0.593, metal 0.595. 76% have AUC >0.55.
  - Top: EURJPY 0.76, S&P 0.76, RDBULL 0.74, USDJPY 0.70, R_10 0.70.
  - By class: crypto 0.632 (86 alts), stocks 0.591, VIX 0.645, DXY 0.634, NDX/SPX 0.53.
  - Regularised 4-window walk-forward: 0.610, 96% >0.55. Config sweep 0.574–0.609.
- **Trade test:** short predicted tops, long predicted bottoms; dev-calibrated thresholds; vol-scaled triple-barrier exit; 3bp cost.
  - 3,337 trades: meanR −0.196, PF 0.65, 47% win vs random −0.167.
  - Rolling retrain every 800 bars, by era: −0.17, −0.12, −0.17, −0.19, −0.14, −0.14 (overall −0.156 vs random −0.115).
  - Meta-label: −0.176 vs all −0.131 vs random −0.159.
- **Status: FAILED.**

### 2.10 xs-short-term-reversal (METALS_ML §7, RESEARCH_SUMMARY) — FAILED
- **Rule:** long/short the crypto panel on short-term relative reversal, across an (L, H) grid.
- **Results:** Sharpe −3 to +0.2 net. IC beats shuffle ~4× but breakeven is ~0.6bps vs 6bps cost.
- 1–2-bar reversal is everywhere but only ~0.05–0.25 ATR, which is sub-cost.

### 2.11 nds-deep-retrace-continuation (MARKET_GEOMETRY_NDS_AUDIT.md) — FAILED
- **Rule:** ZigZag swings (3·ATR reversal). Enter the trend after the correction low.
- **Results:**
  - Look-ahead entry at the swing low: +6.45R, 80% win.
  - Causal entry at the confirmation bar: **+0.11R, 46% win** (≈ Donchian box breakout +0.14R, i.e. plain momentum).
  - The claimed correction ratio K = 0.86·R is false. Over 1569 swings / 22 instruments: mean 0.83, median 0.79, std 0.33, only 11% in [0.80, 0.92], p10 0.41, p90 1.30.
- Also FAILED (no new test; previously falsified): Point-Z polynomial reversals (cubic+exp fit, T'=0 & T''>0, 3 lower lows + 2 buyer interventions); polynomial regression + RL/LSTM.

---

## 3. Momentum family (crypto 1d mainly)

### 3.1 momentum-ts-ensemble + swing-trail exit (MOMENTUM_EXITS.md)
- **Base:** "momentum TS-ensemble" on Binance futures, 1d, lookbacks 7/14/30/60 bars.
  - Ambiguity: the exact ensemble is not given. Most faithful default: the average of sign(return over L) for L ∈ {7,14,30,60}, long if >0 and short if <0.
  - The live baseline `MomentumTSEnsDynLev3` uses a trend-flip exit (exit when the ensemble sign flips).
- **Swing-trail exit:** exit a long when close < the rolling K-bar low; exit a short when close > the rolling K-bar high. K ≈ 5–10.
- **Lab per-trade results (gross):**

| side / exit | exp | win% | avgW | avgL | R:R | perTradeSh |
|---|---|---|---|---|---|---|
| LONG fixed H=10 | +1.53% | 45% | +16.2% | −10.6% | 1.52 | +0.07 |
| LONG swing K=5 | +1.88% | 26% | +28.5% | −7.3% | 3.93 | +0.07 |
| SHORT fixed H=10 | +0.23% | 52% | +10.4% | −10.9% | 0.96 | +0.02 |
| SHORT swing K=10 | +4.62% | 26% | +35.4% | −6.2% | 5.75 | +0.15 |

- **Freqtrade portfolio (58 pairs, 2022–26, 1d):**

| variant | total | Sharpe | long | short | abs DD |
|---|---|---|---|---|---|
| DynLev3 (trend-flip) | +129.9% | 0.40 | +215.7% | −85.8% | 28.4k |
| Swing both sides | +87.3% | 0.45 | | −38.2% | 20.2k |
| **SwingShort** (swing on shorts only, trend-flip on longs) | **+181.0%** | **0.81** | +193.5% | −12.5% | 22.1k |

- 4h: all variants lose −70% to −83%.
- **Status:** deployable on 1d (`MomentumTSEnsSwingShort`). Single backtest, DD ~72%, leveraged.
- Related exit ideas:
  - Avoid-climax entry filter (mentioned, not defined).
  - From RESEARCH_FRONTIERS: fixed exit has the best meanR (+0.138); trail/scale-out/breakeven hurt.
  - "Structure-exit" (exit on momentum failure): Sharpe +0.126 vs fixed +0.112.

### 3.2 momentum-meta-label (META_LABEL.md)
- **Rule:** keep momentum's side; a secondary classifier gates P(side right) > 0.5. 24 features from `meta_features.py` (price + classic indicators). Label horizon H=10 days. Daily data.
- **Results (Sharpe):**
  - Walk-forward refit every 63 days (expanding): 0.81 → 1.08 (DSR 0.69 → 0.83). Adding indicators: 1.15 (DSR 0.85).
  - **Frozen** HistGB trained <2024 and applied to 2024–26: 0.66 → 0.64 (FAILED).
  - Online (river) after 2024: Hoeffding 0.53 → 0.85; ARF 0.82. Online logistic −0.04 (hurts).
- **Caveats:** gross; all below DSR 0.95.
- Note: ML_OVERLAY_VERDICT says meta-labelling the *funding* fade hurt (PF 1.34 → 1.14 OOS).

### 3.3 momentum regime tilts (PRICE_EDGE_SWEEP #3b/#4b; RESEARCH_FRONTIERS scoreboard)
- **Results:**
  - Base momentum Sharpe +0.66. Negative-skew regime +0.87 vs positive-skew +0.70. Variance ratio >1 +0.80 vs VR<1 +0.70.
  - By session: EU +0.112 > Asia +0.071 > US +0.024 (meanR per trade).
  - By VIX tercile: high +0.081 > low +0.059.
  - Alpha decay, first vs second half: −0.029, but the edge persists (+0.124).
- Use only as sizing tilts, not filters.
- **Ambiguity:** skew/VR lookback windows are not given.

### 3.4 Cross-sectional and portfolio variants
- **xs-crypto-momentum:** Sharpe 0.94 vs single-asset TS 0.74 (from METALS_XS). It is the deployed XS rebalancer; details live elsewhere.
- **vol-targeting the momentum book** (PRICE_EDGE_SWEEP #1): 0.78 → 0.80. NULL.
- **HRP vs equal-weight** (ML4T_IDEAS): 0.56 vs 0.60. FAILED.
- **DSR of momentum:** annualised SR 0.76 → DSR 0.73–0.83 at N = 10/30/100 trials. Kurtosis 10.4. Not significant.
- **xs-metals-momentum (METALS_XS.md)** — FAILED:
  - 13 assets (GC, SI, PL, PA, HG, GDX, GDXJ, SIL, NEM, GOLD, FNV, AEM, WPM), 2008–26.
  - Results:

| book | Sharpe | DSR | maxDD |
|---|---|---|---|
| L/S | 0.12 | 0.18 | −53% |
| Long top-half | 0.36 | 0.49 | −63% |
| Equal-weight | 0.49 | 0.70 | −60% |
| Gold-only TS momentum | 0.32 | 0.42 | −39% |

  - 21 broad commodities: L/S −0.47, long-top 0.32, EW 0.40. This needs roll-adjusted data.
  - Keeper (elsewhere): the gold real-rate switch, Sharpe 0.50, DSR 0.72.
- **low-vol anomaly** (L low-RV / S high-RV crypto): Sharpe +0.69, but by year 2022 +2.3, 2023 −1.3, 2024 −0.1, 2025 +2.0, 2026 −5.2. FAILED (beta tilt).
- **skew/lottery XS** (L low-skew / S high-skew): Sharpe −0.31, DSR 0.06. FAILED.
- **Amihud illiquidity XS:** Sharpe −0.29, DSR 0.06. FAILED.
- **BTC→alt lead-lag:** corr(alt_t, BTC_{t−1}) = −0.04. A BTC-gated exit is worse than the alt's own swing exit (LONG R:R 3.98 self vs 2.49 BTC; SHORT Sharpe 0.12 vs 0.03). FAILED.
- **PCA residual momentum, Kalman trend:** untested ("MAYBE").
- **Bandit allocation across strategies:** Sharpe −0.31 vs equal-weight −0.26. FAILED.

### 3.5 MC "direction choice" (MC_FRAMEWORK §6) — FAILED
- **Rule:** simulate, evaluate long vs short, pick the better side.
- **Result:** agrees with recent-drift momentum ~67% of the time and doesn't beat it.

---

## 4. Pairs / relative value (PAIRS_TRADING.md, ML4T_IDEAS.md) — REAL BUT FRAGILE
- **Rule (simple version):**
  - Crypto daily, Binance 3y, 23 coins.
  - Engle–Granger cointegration on train (60%). Fixed OLS hedge β.
  - Spread z-score: enter when \|z\| > 2 (fade), exit when \|z\| < 0.5.
  - 593 OOS days.
- **Results (OOS net):**

| version | Sharpe | control (non-coint) | DD |
|---|---|---|---|
| Fixed OLS β, coint pairs (16 of 23 coins) | **+1.11** (CAGR 11% at 10% vol) | −0.22 | −9.3% |
| Kalman β + quarterly walk-forward reselection (`pairs_strategy.py`) | +0.63 | **+0.97 beats it** (2025 = −1.1) | −20.4% |
| Robust: regularised rolling β + persistence filter + sector pairs (`pairs_robust.py`) | +0.32 | +0.02 | −13.7% |

- Planned risk rules:
  - z-stop at \|z\| > 3 (cointegration broke).
  - Half-life max-hold.
  - Per-pair vol-target.
  - Cap on concurrent pairs.
- **Status:** "real but modest / fragile; not deploy-ready".
- **Data:** OHLC of both legs.

---

## 5. Monte Carlo risk engine (MC_FRAMEWORK, MC_FOREX_METALS, MC_TRADE_PIPELINE, MONTE_CARLO_ZMA)

### 5.1 Engines
1. Block bootstrap.
2. FHS GJR-GARCH(1,1)-t: standardised residuals block-bootstrapped and re-inflated by the conditional-vol forecast.
3. EVT splice: GPD fitted peaks-over-threshold on the residual tail, applied only if ξ > 0.
4. Student-t (MLE).
5. Merton jump-diffusion.
6. Variance-Gamma.
7. 2-state Markov regime switching (empirical transition matrix, in-regime t draws).
8. Hawkes self-exciting jumps.

Gating rules: jumps and Hawkes are turned off when excess kurtosis < 1. Hawkes is used only for crypto and Boom/Crash.

### 5.2 Calibration results
- **Deriv synthetics:** 90/90 calibrated. Bootstrap 89/90.
- **Forex (12 pairs, 24h horizon, 1500 paths, 8 engines):**

| engine | br95 | br99 | calibrated |
|---|---|---|---|
| Gaussian | 4.9% | 1.8% | fails the 99% tail; 10/12 |
| jump_diff | 5.0% | 1.5% | 11/12 |
| var_gamma | 4.4% | 1.5% | 11/12 |
| fhs_evt | 3.5% | 1.0% | 8/12 (p .85 at 99%) |
| student_t | 3.6% | 1.0% | 8/12 |
| bootstrap / regime_sw | ~5.5% | ~1.8% | 7/12 |
| hawkes | 2.1% | 0.5% | 1/12 |

- **Metals:** Gaussian br99 3.2%; student_t, var_gamma and regime_sw calibrate 2/2.
- **Pooled ensemble:**
  - 1500 paths: br95 4.0% (p .006), br99 1.2% (p .17).
  - 10k paths, 647 OOS windows: br95 3.7% (p .12), br99 0.9% (p .85).
  - Meta-weighted (recency calibration weighting): br95 4.2% (p .32), br99 0.9%; Hawkes weight 0.54.
- **Earlier real-Deriv validation:** 95% VaR breached 3–9%, 99% VaR 1–3%. regime_sw 5/5, var_gamma 4/5.
- **Path convergence (CRASH1000 CVaR99):** relative error 5k ≈ 1.5–3%, 10k ≈ 1–2.5%, 100k ≈ 0.2–0.5%. Default is 10k.
- **Rule: never size with Gaussian VaR.**

### 5.3 Applications (testable risk rules)
- **mc-cvar-sizing:** size so the 5% tail CVaR equals the risk budget. Live in `SelectiveFundingFadeMC`.
- **Portfolio CVaR:** joint 5% CVaR from aligned history. 3 EUR longs → 0.65× diversification; an all-short-USD basket → 0.72×.
- **reach-cone target:** TP at the q-th percentile of MC max favourable excursion (realistic / stretch / runner).
  - At level breaks: median 2.5 ATR, 90th percentile 8.0 ATR, P(≥2 ATR) 57%. Realised median 2.0 ATR, so MC over-predicts slightly.
  - Breaks do not expand vol: break reach 1.99 vs random-point 1.94 ATR.
- **noise-aware stop:** place the stop beyond the MC adverse band.
- **RR gate:** keep trades with RR ≥ threshold. This only thins trades (EV ~0).
- **optimal-exit (branching tree):** branch 8 × depth 4 = 4096 leaves over 24h; backward induction with value = max(exit now, E[continue]).

| symbol | optimal dynamic-exit E[R] | fixed-horizon E[R] | lift |
|---|---|---|---|
| gold | +0.30% | −0.06% | +0.37% |
| CRASH1000 | +0.20% | +0.08% | +0.12% |
| R_100 | −0.05% | −0.69% | +0.64% |

  These are in-model results; OOS is untested.
- **multi-engine consensus rule:** 5 engines × 5000 paths, triple barrier ±2σ / 24h. Take a side only if all engines agree on the sign of E[R]. Result: stands aside on R_25 and Boom/Crash; agreement only on R_100, stpRNG and silver (~0.08R, sample drift).
- **mc-direction:** sign(drift) hit 49.3%, sign(skew) 50.2%, meta-model AUC 0.521. FAILED.

### 5.4 ZMA + MC (MONTE_CARLO_ZMA §9)
- **Setup:** 2000 paths, 48-bar horizon, TP +2R, real 1h data. Signal = z-score + dynamic 85th-percentile trigger + tercile vol regime.
- **Realised P(stop) and calibration:** SOL 0.585 (793 signals), XAU 0.583 (791), XAG 0.560 (782). All generators pass Kupiec.
- **Worst R, bootstrap vs fhs_evt:** SOL −5.49 vs −7.96; XAU −7.87 vs −11.62; XAG −9.08 vs −14.12.
- **Crash-1000 spec simulation:** long side worst R −31.45, P(gap-through-stop) 0.62; short side −2.13. A symmetric k is ~15× wrong.
- **Proposed (untested):**
  - Recalibrate vol_k per regime to a target premature stop-out of ≤30%.
  - Fire on the lower CI of the bootstrapped 85th-percentile threshold.
  - Use a side-dependent k on Boom/Crash.
  - Veto signals with high P(gap) or bad CVaR5.
  - Fractional Kelly on the MC R-distribution with a CVaR cap.

### 5.5 Triple-barrier base rates (MONTE_CARLO_ZMA §11)
- Vol-scaled barriers: upper +pt·σ, lower −sl·σ, vertical 48 bars.

| inst | side | pt/sl | MC E[R] | realised E[R] |
|---|---|---|---|---|
| XAU | long | 1/1 | +0.09 | +0.16 |
| XAU | long | 3/1 | +0.20 | +0.25 |
| XAU | short | 3/1 | −0.17 | −0.21 |
| XAG | long | 1/1 | +0.16 | +0.01 |
| XAG | long | 3/1 | +0.35 | +0.28 |
| XAG | short | 3/1 | −0.34 | −0.10 |
| SOL | long | 3/1 | −0.14 | −0.14 |
| SOL | short | 3/1 | +0.14 | +0.17 |

- These reflect sample drift (2024–26 metals bull, SOL bear), not an edge.

### 5.6 Deriv structural facts (MONTE_CARLO_ZMA §12)
- **Skew:** CRASH900 −1.82, CRASH500 −1.41. On Crash the long side carries the tail (triple-barrier worst R −2.2/−2.4 vs short −1.3/−1.5). Only 150 bars of 15m data.
- **R_100 / R_25:** skew ≈0, GPD ξ < 0 (thin-tailed, essentially constant-vol GBM).
- **Fat tails are in Step and Range Break:** stpRNG ξ +6.30 / +6.39 (down / up), RB100 +4.40 / +4.34; excess kurtosis 6–10.
- **Boom/Crash CVaR:** Crash long −2.0…−3.7 vs short −1.6; Boom is the reverse.
- **Live pipeline signals (612, one week):** triple barrier ±2σ / 8 bars; meanR +0.056. By confidence: <60 +0.01, 60–75 +0.03, 75–85 +0.28, 85+ +0.20. SELL +0.13 vs BUY −0.03. Sanity check only.
- **Metals, signal-free:**
  - Kurtosis: gold 24.4, silver 35.9. GPD ξ down/up: gold 0.31/0.21, silver 0.30/0.11.
  - 1-month CVaR99, FHS vs Gaussian: gold 15.0% vs 17.1%, silver 32.2% vs 34.3%, SOL 85% vs 39%.
  - $10k long for 1 month (EVT): gold median +$518, 1%-worst −$1,505; silver +$1,594 / −$3,374.

### 5.7 MC_TRADE_PIPELINE (system)
- **Steps:** momentum Donchian breakout on trending assets (crypto/metals; skip forex) = WHERE + WHICH WAY → MC reach-cone target + VaR size → RR gate.
- **Claimed edge ceiling:** ~+0.14R (from the Donchian momentum).
- The Donchian lookback is not given in this doc.

---

## 6. Sizing and risk rules

| id | formula / rule | result |
|---|---|---|
| **EDK** edge-decay Kelly | p̂_long = EW win rate, half-life 200 trades; p̂_short = half-life 20; σ_p = √(p̂(1−p̂)/n_recent); κ = clip(1 − 2\|p̂_long − p̂_short\| / max(σ_p, 0.05), 0, 1); f = κ·Kelly(p̂_long) | EURUSD fisher_extreme, 423 trades: avg size 1.6%, +13.5%, Sharpe 6.9, DD 4.9% (insurance cost) |
| **TGS** tier-graduated Kelly | f = ((b_t·p_t − (1 − p_t))/b_t)·c(tier); c: confirmed 1.0, early_warning 0.4, speculative 0.1 | untested |
| **CDS** correlation-dedup | scale = min(1, f_max/√(fᵀRf)), R = rolling corr of pnl% | in the pool test it does nothing at ρ≈0 |
| **FAK** friction Kelly | avg_win − φ, avg_loss + φ; b = ratio; f = (b·p − (1 − p))/b | φ=0.02%: avg 8.2%, +63.4% (vs theoretical +218%), Sharpe 8.3, DD 10.9%; Kelly ~17% → 8%. "Most actionable" |
| **DRS** drawdown recovery | ρ = peak/equity; f = f_base·√(ρ − 1) + f_floor | avg 5.0%, +8.4%, Sharpe 13.6, DD 1.6% (rarely active) |
| **MSK** multi-signal Kelly | f = Σ⁻¹μ, Ledoit-style shrink α=0.5, ×0.25, cap 15% | pool test: +507%, **DD 95.7%**. FAILED/unsafe |
| **naive pooled half-Kelly** | each signal at its own half-Kelly, shared capital | see below |
| martingale / grid (GerEA) | add a same-direction leg at a worse price with vol×GridVolMult (1.0–1.5), up to GridMaxLvl 20–50, close the basket at average-entry profit | FAILED: −34% on a 57.9%-win stream (RISK_SIZING_DESIGN) |
| RISK_MARGIN_FREE | % of free margin | avoid (sizes up on streaks) |
| equity-DD circuit breaker | stop and close all when DD > X% | recommended (≈ dd_controlled) |
| SpreadLimit / MarginLimit gates | block entries when spread > X points / margin level < Y% | infrastructure |
| trailing at % of TP | once price reaches N% of TP, trail the SL | untested |
| SL modes | swing high/low; Average Range × m; Max Range × m; fixed points | untested |

**Multi-signal pooling (MULTI_SIGNAL_POOLING.md):** 1h, 5000 bars each, $100K start.

- Signal streams:

| signal | polarity | trades | win | avg |
|---|---|---|---|---|
| EURUSD_rev (fisher_extreme) | reversion | 423 | 57.9% | +0.034% |
| XAUUSD_rev | reversion | 430 | 50.2% | −0.018% (half-Kelly 0) |
| USOIL_trend | fisher inverted | 408 | 52.0% | +0.176% |

- Pairwise correlations: max \|ρ\| 0.033. Half-Kelly: EURUSD 11.32%, USOIL 6.73%.
- Outcomes:

| book | return | Sharpe | DD |
|---|---|---|---|
| EURUSD solo | +123% | 8.7 | 13% |
| USOIL solo | +355% | 4.0 | 64% |
| naive pool | +927% | 5.4 | 64% |
| CDS | +904% | 5.4 | 63% |
| MSK | +507% | 4.8 | 95.7% |

- Caveats: no friction (re-run with 0.02% pending); Sharpe values are implausibly high (overlapping/in-sample).
- Other fisher_extreme facts (RESEARCH_FRONTIERS, citing ALPHA_DECAY_AND_SESSIONS):
  - EURUSD win rate fell 66% → 52% in the last third.
  - Win rate by session: London/NY/late 60–64%, Asia 54%.

---

## 7. MT5 EA reference strategies (MT5_STRATEGIES_REFERENCE.md) — UNTESTED in lab

Shared defaults: risk 3% per trade, grid on by default. Parameters as listed in the doc; full logic is in the source repo geraked/metatrader5.

| EA | rule | params |
|---|---|---|
| CEZLSMA | Heikin-Ashi candles; Chandelier Exit crossover aligned with ZLSMA slope; trend continuation | CE ATR period 1, mult 0.75; ZLSMA 50 |
| 3MAF | long if MA60 > MA350 > MA600 and a bullish Williams fractal forms (mirror for short) | 60/350/600 |
| BBRSI | buy when previous bar's RSI < lower band and close < BB lower, then current bar's RSI breaks back above and close is back above the BB mid | BB 500, RSI 7 |
| DHLAOS | break of yesterday's high/low confirmed by Andean Oscillator direction (scalper) | AOS 50/9 |
| 3MACD | three MACD histograms (different periods) aligned | not given |
| 2MACDSTO | two MACDs cross the same way and Stoch %K leaves OB/OS | Stoch 7/3 |
| 2MAAOS | MA cross + AOS confirmation | 50/200, AOS 50/9 |
| AFAOSMD | Average Force + AOS + MACD agree | AF 20, AOS 50/9 |
| NWERSIASF | fade at the Nadaraya-Watson envelope with an RSI extreme; ATR SL finder | NWE mult 3.0, ASF 0.75 |
| LRCUTB | Linear Regression Candles slope + UT Bot trailing flip | LR 11/7, UTB ATR 1 |
| COT1 | CFTC COT net-positioning bias + SuperTrend flip in that direction | ST 10, 3 |
| LRCMACD | LRC trend + MACD histogram direction | LR 11/5 |
| 2MOMEMA | EMA10/EMA34 cross + momentum filter | 10/34 |

Indicators worth porting:
- Andean Oscillator (bull/bear envelopes + EMA signal).
- Average Force = (close − previous open) × volume.
- Linear Regression Candles.
- NW envelope to replace the static 1.5σ Fisher threshold.
- Chandelier Exit, SuperTrend, UT Bot, Darvas boxes, Kijun envelope, round-number Boxline, order blocks.

Ambiguity: the exact AOS formula and NW bandwidth are not given; use the TradingView originals.

---

## 8. Direction prediction via ML / regime — all FAILED (record so they aren't retested blindly)

| id | setup | result |
|---|---|---|
| metals-tft/gbm (METALS_ML §2) | 28 causal OHLCV features, triple-barrier `meta_up` over 48 bars, 4-fold expanding walk-forward, XAU/XAG 1h, 5000 bars | TFT acc / netR: XAU 0.460 / −0.25, XAG 0.522 / +0.01. GBM: XAU 0.495 / −0.13, XAG 0.497 / −0.06 |
| funding-features direction (§3) | 13 funding features; 60 alts, 3y, 178,732 samples; LightGBM 5-fold walk-forward | OHLCV AUC 0.531, funding 0.508, both 0.533 (+0.0024) |
| DeepAlpha | 4h-feature lookahead | faked 69% / +0.3R |
| NN direction (NN_MODELS) | H-bar forward return | acc 50.2%, IC +0.002, −4 bps net. Controls: garch 50.7%, shuffle 50.5%. Index 56.3% but always-long 57.7% |
| entry/limit model | limit on predicted dip | −0.058 ATR vs market (controls −0.126 / −0.118): **enter at market** |
| funding-dir (MEXC, 156d) | | +30bps is a drift artifact; IC +0.047 |
| pump/dump model | | AUC 0.63 for a big move, but pump_p ≈ dump_p (corr 0.74) |
| CVD direction (Binance taker volume, 2y, 10 symbols) | | ≈49% at H = 1/3/6 |
| order-flow at pump (RESEARCH_FRONTIERS #7, 5,399 events) | flow_ratio | AUC 0.526; score 0.554; score+flow 0.597; corr −0.02; high-flow tercile 47% vs low-flow 53%. The 0.809 headline was a vol_ratio artifact |
| detection HMM (trade the current state's mean) | | OOS Sharpe: FX +0.06, metals +0.95, crypto −0.04 (momentum 0.56; metals buy-and-hold 1.22) |
| predictive HMM | | crypto −0.3 |
| CUSUM scalper | | 37% win, lost |
| CUSUM-on-RV vol prediction (AUC) | | vol expansion 0.625 vs trailing vol 0.723; big move 0.596 vs 0.778 |
| jump-model strategy switching (k-means + jump penalty; mom ↔ MR on sign(close − SMA)) | | switched vs better single: FX −2.32 vs MR −1.27; metals −1.05 vs mom +0.08; crypto −0.83 vs mom −0.14 |
| TDA Betti prediction (AUC) | | vol-regime 0.755 vs trailing 0.747; big move 0.752 vs 0.766; direction 0.50 |
| Hawkes big-move | | AUC 0.484 vs trailing vol 0.743 |
| RMT covariance cleaning (min-var) | | hurt |
| funding-fade meta-label | | PF 1.34 → 1.14 OOS |

Literature-backed gate (REGIME_DETECTION_VERDICT): a jump-model 0/1 S&P risk gate improved MDD from −55% to −27% and Sharpe from 0.48 to 0.68 (1990–2023 OOS, with costs). This is cited from the literature, not tested by the lab. Use it as a de-risk gate, never for direction.

---

## 9. Volatility forecasting (testable; feeds sizing/stops)

- **vol-lgbm (NN_MODELS):** forward log realised vol, purged walk-forward.
  - R²: persistence 0.757, HAR-RV 0.799, **LGBM 0.826**, NN 0.816. iid control ≈0.
  - QLIKE: 0.41 vs 0.51 for HAR.
  - Top features: rv66, hour/day-of-week, ATR, vol-of-vol, squeeze.
  - Per asset class R² 0.58–0.72 (RESEARCH_SUMMARY). Vol peaks ~13–17 UTC.
- **LIT_SCAN_2026 candidates (vs HAR-RV OOS R² 0.67–0.86):**
  - Realised semivariance RS⁺/RS⁻ from 1m returns.
  - HARQ with RQ = (n/3)Σr⁴.
  - DVOL/VIX1D as a feature (options data).
  - Cross-asset panel HAR-cov.
  - PatchTST (~5% MSE gain at h=22 only).
  - Status: proposed; results not reported.
- **Squeeze → expansion:** real (cited SQUEEZE_VOL).
- **Topology turbulence lead (PIP_PATTERNS):**
  - Setup: Gidea-Katz H1 persistence of an N-coin returns point cloud, window 40.
  - Results: corr with forward vol +0.11 vs trailing −0.08; incremental t +3.42, R² 0.005 → 0.018; crash-lead 34% vs 25% base (1.36×).
  - Single-asset gold version for a VRP de-risk gate: FAILED (18% vs 20%).
- **Cross-sectional HAR:** naive R² 0.95 is an overlapping-window inflation. The real metals non-overlapping R² is 0.43.

---

## 10. Pump scanner (PUMP_SCANNER_PREDICTIVENESS, PUMP_SCANNER_BY_ASSET_CLASS)

- **Scanner:** production volume + consecutive-bar + price layers (thresholds not in docs). Tiers: confirmed (score ~75–95), early_warning (45–60). layers_passed 3 or 4.
- **MEXC crypto, 15m (7,205 events / 2 days, 30% joinable):**

| horizon | hit | mean signed return | UP hit | DOWN hit |
|---|---|---|---|---|
| +15m | 49.3% | −0.0002% | 48.1% | 51.6% |
| +30m | 49.0% | +0.054% | 47.3% | 52.1% |
| +60m | 48.8% | +0.114% | 46.2% | 53.6% (+0.216%) |

  - Score Q4 at +60m: 53.6%, +0.63%.
  - Layers at +30m: 3 layers 49.4% (n=1744) vs 4 layers 46.9% (n=358).
  - Status: FAILED, descriptive.
- **Non-crypto, 1h, +2h (1,674 events / 7 days):**

| source | n | hit | mean | up / down hit |
|---|---|---|---|---|
| NASDAQ | 210 | 76.2% | +1.14% | 71.2 / 85.9 |
| NYSE | 158 | 67.7% | +1.00% | 57.5 / 80.3 |
| FX (TV) | 63 | 66.7% | +0.07% | 55.2 / 76.5 |
| OANDA | 662 | 38.8% | −0.10% | 47.9 / 28.2 |
| TVC | 139 | 41.0% | −0.20% | 29.2 / 51.4 |

  - All sources: +1h 49.4%, +2h 50.4%, +4h 54.5% (+0.38%).
  - Proposals: promote stock alerts (especially dumps); invert or raise thresholds on OANDA; disable TVC.
  - Caveats: 7 days, in-sample, no costs.
- **Reproducible on OHLC** if the scanner logic is re-implemented. A crude default: a volume z-spike plus N consecutive same-direction bars plus a price move above a threshold.

---

## 11. Literature direction ideas (LIT_SCAN_2026 B)
- **OFI:** (buy − sell vol)/total, plus depth and spread. 1–5 min horizon, 51–55% accuracy, Sharpe 0.8–1.2, survives 10bps. Mean-reverts within 15–30 min.
- **On-chain exchange flows:** ETH net inflow (negative for returns and vol), USDT→exchange inflow (positive for BTC/ETH) at 1–6h. No net-of-cost OOS reported.
- **OFI at up to 7-day lag** with nonlinear ML.
- None of these were tested by the lab, except that CVD at 1h+ failed (§8).

---

## 12. RESEARCH_FRONTIERS untested hypotheses (beyond those scored above)
- **Half-life of edge:** fit wr(t) = wr_long + (wr_init − wr_long)·e^(−t/τ). Track rolling avg_move_after_fire as a saturation measure.
- **Pre/post-news windows:** hypothesis that post-news favours trend and ±12h favours reversion. Also day-of-week and month-end (last 3 trading days).
- **Macro tags for fisher_extreme:** VIX terciles, BTC vol regime, DXY momentum.
- **Info-theory:** mutual information and transfer entropy (DXY → EURUSD), PE of residuals. Doc says DOA.
- **Thompson sampling / LinUCB** across signals (bandit tested: failed).
- **Scale-in:** half on signal, half at Fisher threshold + 0.5σ. Deriv multipliers or options for bounded loss.
- **MEXC depth imbalance:** (bid_top10 − ask_top10)/total over 30s → a >0.5% move in 5 min.
- **Counter-meme:** X mention spikes over 4h → fade.
- **Percolation:** largest connected component of a 28-pair correlation graph.
- **SOC:** power-law α flattening as a large-move lead.
- **Hawkes on liquidations** for pump/dump asymmetry (RESEARCH_SUMMARY: the one open direction idea; data accruing).

---

## (a) Ideas not backtestable on OHLC/exchange data, and why
- LIT_SCAN:
  - On-chain exchange flows: need an on-chain feed.
  - OFI and depth at 1–5 min: need order-book/tick data.
  - DVOL/VIX1D vol feature: needs options IV.
- RESEARCH_FRONTIERS:
  - MEXC depth imbalance: order book.
  - Counter-meme: X/Telegram mentions.
  - Pre/post-news windows: economic calendar.
  - Hawkes on liquidations: liquidation feed.
  - Deriv multiplier/option payoffs: product terms.
- MT5:
  - COT1: CFTC COT data.
  - News filter: calendar.
- Forensic reports (MUFG v1/v2, Mitsubishi): JGB yields, MS earnings calendar, BoJ/MPC calendar, USTR feed, ownership data, Berkshire filings, Henry Hub/iron ore, options OI/IV, the JST intraday auction structure, and the ADR-vs-Tokyo gap (needs both venues intraday). HD kill: mortgage rates.
- METALS_ML §3, NN funding_dir, ML_OVERLAY funding meta-label: need funding history. This is exchange data, so backtestable for crypto perps only.
- CVD / order flow at pumps: needs taker-volume data (Binance, exchange-available) and pump-event logs.
- Pump scanner: needs the scanner's event logs unless re-implemented. Live-signal confidence monotonicity: needs the pipeline's notification logs.
- MEAN_REVERSION_SCOPE: VIX gate (VIX series) and DXY (index data, obtainable).
- Commodity XS momentum: needs roll-adjusted futures total returns.
- Online meta-labelling: needs online-learning simulation (vectorised backtests can't do it).

## (b) Files with no trading idea of their own
- README.md: index of the studies folder plus promotion criteria; no ideas.
- RESEARCH_SUMMARY.md: master "predictability map" summary; it only restates results catalogued above (vol R² 0.83, sub-cost reversal, the direction wall, open Hawkes-on-liquidations).
- ML_OVERLAY_VERDICT.md: verdict/summary doc. Its only new number is the funding meta-label PF 1.34 → 1.14 (in §8).
- REGIME_DETECTION_VERDICT.md: mostly verdict, but it contains the tests catalogued in §8.
- MITSUBISHI_CORP_FORENSIC_REPORT.md / MUFG v1 / v2: narrative due-diligence reports; their only tradeable content is the filters and priors in §1.7.
- MT5_STRATEGIES_REFERENCE.md: a reference catalogue (README marks it "no findings"); its strategies are listed in §7 as untested.
- MARKET_GEOMETRY_NDS_AUDIT.md: an audit (falsification) of external NDS docs; entries in §2.11.
