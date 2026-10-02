# Trading-signal catalogue for `the source` (my share)

**Root:** the source. Nothing was modified, and no secrets or `.env` files were read.

**How this was produced.** I read the range_strat range/meta family myself: `range_engine`, `adaptive_range`, the meta/wf/hook/tick/synth/rb/book scripts and the docs. Four sub-agents read the rest, every file in full. Their reports are folded in below and condensed only in wording; the formulas, parameters and results are kept.

**Two of those reports are stored verbatim on disk**, if you need finer detail:
- nn / datacollector / top-level: (appendix)
- range_strat part B (SMC, patterns, momentum, stat-arb, carry, RL, microstructure): (appendix)

**Cross-cutting warnings**
- **Deriv used as a null.** Many scripts treat Deriv R_x / RB / JD / stpRNG as "random-walk controls". That conflicts with your saved rule that Deriv is a real market. Treat Deriv results as market results and use your own GBM or GARCH walks for nulls. `crt/squeeze_vol.garch_df` and `nn/dataset.garch_df` already do this: GARCH(1,1) with ω=3e-7, α=0.07, β=0.86, 8 sub-steps per bar, shocks clipped at ±6σ.
- **No bid/ask anywhere.** Every cost is a flat bp per side or per unit of turnover.
- **Unclosed last bar.** ccxt, Deriv `end:latest` and the TradingView WS all return the still-forming bar last.
- **Box-only paths.** Scripts import nimble from (lab path) and read data from `/tmp/*.csv`, neither of which exists on this machine. Results come from the box.

---

# 1. range_strat — range fade/breakout engine family (my own read)

## 1.0 Shared conventions

**Data**
- Crypto: Binance 1m from data.binance.vision, resampled to 15m (`resample` first/max/min/last/sum, label = bar open).
- FX and metals: Dukascopy 15m (`*_du15.csv`) or 1m (`*_1m.csv`, `*_pre1m.csv`).
- Deriv synthetics: Deriv WS candles (`*_15m.csv`, `*_1m.csv`, volume = 0).
- Macro: FRED CSVs.
- Funding: Binance futures CDN. OI, long/short ratio and taker ratio: Binance metrics CDN.

**Cost model (`MK`)**
- maker = 0 bp, taker = 5 bp + 2 bp slip = 7 bp.
- `cost_mode="maker"`: entry maker, TP maker, SL taker. So the cost is 0 on a TP exit and 7 bp on an SL exit.
- `cost_mode="taker"`: 2 × 7 = 14 bp round trip.
- The "honest 1m" harnesses use `FADE_C` = 1 bp on entry, `TAKER_C` = 7 bp on a stop, and taker fees on both legs of a breakout.

**Metrics:** PF, win rate, expectancy, equity product, per-year PF, geometric mean of yearly PFs, fraction of positive years.

---

## 1.1 `fixed-window-range` (fade / breakout / adaptive) — `range_engine.py:backtest`

**Signature:** `backtest(df, form_window_min, mode, sl_mult=0.25, tp_mult=1.0, fade_tp_frac=1.0, cost_mode, stale_min=720, arm_frac=0.15, min_range_pct=0.002, max_range_pct=0.10, squeeze_q=None, squeeze_lookback=720, regime=None, adapt_thr=0.15)`.

**Range definition (bars, not minutes)**
- w = `form_window_min` bars. `R = rolling max(high, w)` and `S = rolling min(low, w)`, both including bar i.
- `H = R − S`, `M = (R + S)/2`, `rp = H/M`.

**State machine**
1. **FORM.** At bar i, freeze R, S, H, M.
   - Require `min_range_pct ≤ rp ≤ max_range_pct`.
   - If `squeeze_q` is set, also require rp ≤ the rolling `squeeze_lookback`-bar quantile(`squeeze_q`) of rp. min_periods is lookback/2.
   - Then go to ARMED.
2. **ARMED.** Return to FORM if more than `stale_min` bars have passed since anchor.
   - **Arm** once `S + arm_frac·H ≤ close ≤ R − arm_frac·H`.
   - Once armed, a **touch** is `high ≥ R` or `low ≤ S`. If both touch on the same bar, go back to FORM.
   - **Regime gate** (non-adaptive modes): `regime = (measure, lookback, lo, hi)`. If the measure value at bar i is outside [lo, hi], skip and re-form.
3. **Entry**, filled intrabar at the level:
   - **FADE.** Touch R: short at R, TP = R − fade_tp_frac·H, SL = R + sl_mult·H. Touch S: mirror.
   - **BREAKOUT.** Touch R: long at R, TP = R + tp_mult·H, SL = M. Touch S: mirror.
   - **ADAPTIVE.** Breakout if the regime value at bar i is ≥ `adapt_thr`, otherwise fade.
4. **Exit.** Checked from the next bar, intrabar. SL is checked first on an ambiguous bar. There is no time stop.
   - Return = side·(exit − entry)/entry − cost.
   - After the exit the range is re-formed immediately (FORM).

**Regime measures**
- `er_series` (Kaufman ER): `|c − c[−n]| / Σ|Δc|` over n.
- `hurst_series`: R/S on log returns over the lookback, `log(R/S)/log(n)`.
- `adx_series`: Wilder ADX using ewm α = 1/period.

**Lookahead:** none in the signals. The range is set at a bar's close, and touches are checked on later bars. Limit fills exactly at the level are optimistic: no queue, and a gap-through still fills at the level.

**Configs used**
- 1m data: w = 720 (12h); `run_range` sweeps w = 120/240/360/720.
- 15m data: WB = 48 bars (12h), `stale_min = squeeze_lookback = 48`.
- Hurst gates: <0.5 or <0.45 for fade; >0.5 for breakout (lookback 720 or WB).
- ER gates: <0.30 for fade; >0.40 / >0.25 / >0.10–0.40 for breakout.
- `adapt_thr`: 0.12 / 0.15 / 0.18. `refine_a` compares ER@0.12, Hurst@0.5, ADX@20 and ADX@25.

**Reported results (README / docs)**
- 1m BTC/ETH, Jan 2025–May 2026:
  - 12h window is best; maker fees roughly halve the drag.
  - ETH fade with Hurst<0.5, sl = 1.0H, TP at the opposite bound: +0.167%/trade, 1.19x.
  - 2023: ETH fade with maker 1.48x. The Hurst gate HURTS here (0.69x).
- 15m ETH breakout with maker: 2023 1.14x, 2025-26 2.45x (PF 1.21).
  - ER>0.10: 1.58x / 3.01x.
  - ER>0.25–0.30: PF 1.4–1.9.
- Deriv 15m: RB100/RB200 breakout PF 1.3–1.6, fade fails. R_75 breakout 2.07x vs R_100 0.33x.
- Per-year BTC 2019–26 (`per_year`):
  - Raw breakout PF 0.84–1.12 each year.
  - Fade wins in 2019, 2020 and 2025.
  - Adaptive ER@0.12: geometric-mean PF 1.07, 7/8 years positive. Breakout alone 0.98 (4/8), fade alone 0.97 (3/8).
  - ADX does not beat ER.
- 15m by side (`run_side`):
  - FX majors lose on both sides; EURUSD/GBPUSD PF 0.4–0.7.
  - Silver breakout 1.15x.
- Dukascopy 3y FX/metals: both sides lose, test PF 0.5–0.9.
- DXY: fade 0.51, breakout 0.71.
- VIX: fade PF 1.09 (1.32x), breakout 1.08.

---

## 1.2 `adaptive-de-range` (DE-gated event-driven range) — `adaptive_range.py:backtest`

**Signature:** `backtest(df, form=48, de_max=0.30, k_break=0.5, atr_period=48, max_life=288, mode="fade", sl_mult=0.25, fade_tp_frac=1.0, tp_mult=1.0, cost_mode="maker", min_range_pct=0.002, max_range_pct=0.10, arm_frac=0.15, confirm=None, entry_offset=0.0, over_tol=None, close_inside=False, hook_ratio=None, hook_lookback=24, htf_mult=1, htf_gate=False, htf_prem=False, nodal_decr=False, nodal_trend=False, node_theta_k=0.5, node_theta_fixed=None, htf_tp=False, htf_adaptive=False, trail=False, trail_at=0.5, trail_far=True, deep_retr=None, min_pierce=None)`.

**Inputs**
- `DE = er_series(close, form)`, i.e. ER over `form` bars.
- `ATR`: Wilder EWM with α = 1/48, min_periods 48.

**State machine**
1. **SEEK.** When DE[i] ≤ de_max (and ATR is valid), a range is born: R = rolling max(high, form)[i], S = rolling min(low, form)[i]. Require min_range_pct ≤ H/M ≤ max_range_pct. Go to ACTIVE with born = i.
2. **ACTIVE**
   - **Death:** `close > R + k_break·ATR` or `close < S − k_break·ATR` (a confirmed breakout), or `i − born > max_life` → back to SEEK.
   - **Arm:** as in 1.1, with arm_frac 0.15.
   - **Touch:** `high ≥ R − entry_offset·H` or `low ≤ S + entry_offset·H`. If both touch, skip the bar but keep the range alive.
3. **FADE filters**, applied in this order. All of them use bar i, the touch bar.
   - `confirm` mask: bearish at R, bullish at S (see 1.3). Combine masks with `+` (AND) or `|` (OR).
   - `over_tol`: skip if the wick goes beyond R + over_tol·H.
   - `min_pierce` (failed-break variant): require high ≥ R + min_pierce·H. Usually paired with close_inside.
   - `close_inside`: require close < R for a short, or close > S for a long.
   - **HTF context.** hw = form·htf_mult. If `htf_adaptive`, use hw = htf_mult × the median spacing of big nodes (θ = 2·ATR) instead, clipped to [form, n/3].
     - `htf_gate`: require DE(hw) ≤ de_max.
     - `htf_prem`: pos = (c − LL_hw)/(HH_hw − LL_hw). Short only if pos ≥ 0.5; long only if pos ≤ 0.5.
   - **Nodes** (`_nodes`, a causal zigzag with θ = node_theta_k·ATR or node_theta_fixed·price; a leg is appended on the confirmation bar):
     - `nodal_decr`: require |last leg| < |previous leg|.
     - `nodal_trend`: trend = sign(sum of the last 3 signed legs). Do not short when trend > 0; do not long when trend < 0.
   - `deep_retr`: impulse = R − min(low over the last 24 bars) (or the long mirror). Require impulse ≥ thr·|last node leg|. thr can be a float or a callable.
4. **FADE geometry.** Entry is at the limit level eoR / eoS. SL = R + sl_mult·H (mirror for longs). TP, in priority order:
   - `htf_tp`: the HTF mid, (HH_hw + LL_hw)/2, if it lies beyond entry.
   - `hook_ratio`: entry − ratio·impulse, with impulse measured over 24 bars. The ratio may be a callable.
   - otherwise entry ∓ fade_tp_frac·H.
   - `trail`: TP = the far bound. Once price reaches entry ± trail_at·H, move SL to breakeven.
5. **BREAKOUT.** `confirm` is a continuation mask: bullish at R. Long at R, TP = R + tp_mult·H, SL = M.
6. **Exit.** SL first, as in 1.1. After an SL go to SEEK; after a TP go to ACTIVE (re-arm).
   - `return_levels=True` returns the entry-time (R, S, H) per trade for the 1m/tick replay harnesses.

**LOOKAHEAD, confirmed in code and admitted in docs §17 and §20**
- Every bar-close filter is evaluated on the touch bar while the fill is intrabar at the level: `close_inside`, all `confirm` masks, `htf_prem`'s pos (which uses c[i]), DE/ATR death, and `nodal_*` on bar i. A real limit at R fills before the close is known.
- `htf_adaptive` takes the median cycle length over the FULL sample.
- Faithful fix:
  - evaluate the filters on bar i's close and enter on the next bar at the limit or at close[i]; or
  - use the tick/1m-confirmed rejection (1.7).

**Reported results (README, design doc §7–§16, multi-cycle 2019–26 BTC/ETH 15m, maker)**
- **Base (form 48, de 0.30):**
  - Fixed-window fade: BTC geoPF 0.97 (3/8 years), ETH 0.85.
  - Adaptive: BTC 1.19, 24% win, 7/8 years; ETH 1.16, 7/8 years.
- **Confirmations** (`run_adaptive_confirm`):
  - BTC: candle 1.43, 100% of years positive; updown 1.39.
  - ETH: updown 1.34.
  - OR-combination `updown|candle`: BTC 1.42, ETH 1.31.
- **close_inside:** BTC 1.16→1.35, ETH 1.12→1.26, RB200 1.37→1.60.
- **candle + close_inside:** RB200 2.59, R_50 2.18, BTC 1.45, ETH 1.41.
- **entry_offset hurts everywhere.**
- **Timeframe:** crypto is best at 1h (BTC 2.47, ETH 1.89); synthetics are best at 15m.
- **htf_prem (htf_mult 4):** RB200 2.59→4.17, BTC 1.61, ETH 1.56. `htf_gate` is inconsistent.
- **nodal_trend:** RB200 1.60→2.21, ETH 1.26→1.50.
- **nodal_decr:** RB200 2.52, but it hurts crypto.
- **Scale ×3 is best:** RB200 4.04.
- **Trail (breakeven at 0.3, run to the far bound):** BTC +25.7→+46.4 bp, PF 1.45→2.25.
- **Capstone (`best_config`):**
  - BTC stack: PF 2.24, +46 bp, 100% of years.
  - ETH: 1.92.
- **Synthetics:** RB200 4.04, R_50 2.67, JD25 2.31, R_75 1.81, CRASH500 1.77.
- **Tight SL 0.05H:** BTC PF 2.63, RR 10.6. With the trail: 3.35, RR 19. This is a **15m proxy artifact** (§17).
- **The decay of these numbers under honest execution is in 1.7.**

---

## 1.3 Confirmation library — `adaptive_range._confirmations(o, h, l, c, v)`

Each entry gives the bullish mask, then the bearish mask. All are causal at the bar's close.

**Candle anatomy** (used in the definitions below):
- body = |c − o|
- rng = h − l
- upper wick = h − max(o, c)
- lower wick = min(o, c) − l

**Reversal-type confirmations**
- `updown`: c > o (bull) / c < o (bear).
- `candle`: (hammer OR bull engulf) / (shooting star OR bear engulf).
  - hammer: lower wick ≥ 2·body and h − c ≤ 0.35·rng.
  - shooting star: upper wick ≥ 2·body and c − l ≤ 0.35·rng.
  - bull engulf: c > o, previous bar down, c ≥ prev o, o ≤ prev c. Bear engulf is the mirror.
- `wick`: lower wick ≥ body / upper wick ≥ body.
- `rsi`: Wilder RSI14 < 35 / > 65.
- `bb`: low < SMA20 − 2·sd20 / high > SMA20 + 2·sd20.
- `stoch`: %K over 14 bars < 20 / > 80.
- `fractal`: low < both previous 2 lows / high > both previous 2 highs.
- `tweezer`: |l − prev l| ≤ 0.1·rng and an up bar (mirror for tops).

**Direction-agnostic or continuation confirmations**
- `inside`: h ≤ prev h and l ≥ prev l (both directions).
- `volspike`: v ≥ 1.5 × SMA20(v).
- `body`: up and body ≥ 0.6·rng / down and body ≥ 0.6·rng.
- `closeloc`: h − c ≤ 0.25·rng / c − l ≤ 0.25·rng.
- `doji`: body ≤ 0.1·rng.
- `marubozu`: body ≥ 0.85·rng, signed by direction.
- `outside`: h > prev h, l < prev l, and an up bar (mirror for down).

**ΔPF vs base on the fade (README):**
- updown: RB200 +0.57, BTC +0.20, ETH +0.49.
- candle: RB200 +0.90.
- rsi: BTC −0.24, ETH −0.33.
- stoch: −0.19.
- candle+bb: ETH 1.72.

**Breakout continuation:**
- BOOM1000: candle → 1.75, wick 1.43, body 1.32.
- ETH: only wick rescues it (1.10).
- The base adaptive breakout loses on RB, BTC and ETH.

---

## 1.4 Hook TP and online give-back learners — `hook_test.py`, `hook_online.py:run`, `hook_learn.py:run`

**Hook TP**
- impulse = R − min(low over 24 bars), for a short at R.
- TP = R − ratio·impulse.
- Stage 1 sweeps ratio ∈ {0.5, 0.62, 0.786, 0.86, 0.95}.
- Config: form 96, de 0.15, sl 0.20, arm 0.15, close_inside.

**Online variants, all with r0 = 0.86**
- `online` EWMA: α = 0.05, `r̂ ← (1−α)·r̂ + α·clip(MFE/impulse, 0.3, 1.2)`.
- `online_reg` SGD: x = [1, DE, voln, impulse/H, HTF pos], where voln = std20(r)/std500(r) and HTF pos uses a 384-bar window. Learning rate 0.02. The ratio is clip(w·x, 0.3, 1.2).
- `regime`: a separate EWMA per DE bucket, with buckets split at 0.06 and 0.10.
- `phold`: online logistic P(hold). Gate on P(hold) ≥ τ.

**LOOKAHEAD (a real leak)**
- The learner is updated at ENTRY time, using the MFE over the NEXT 48 bars (`mfe_h = 48`).
- Any later trade within 48 bars therefore uses a ratio that already contains future price action.
- `close_inside` also has the same-bar lookahead from 1.2.
- Fix: delay each update until bar i + 48, or until the trade closes, whichever is right for the learner.

**Results (README)**
- BTC with close_inside and a fixed ratio: 1.16→1.50; ETH: 1.58.
- OOS second half:

| | fixed 0.86 | EWMA online | online regression | per-regime EWMA | P(hold) gate |
|---|---|---|---|---|---|
| R_50 | 1.80 | 2.18 | | 1.96 | 3.35 (64% win, thin) |
| BTC | 1.61 | 1.56 | 1.69 | 1.68 | 1.23 |
| ETH | | | | 1.32 | |
| RB200 | | | 1.17 | | |

---

## 1.5 Hook as an entry — `hook_entry.py`, `hook_break.py`

**`hook_entry`** (15m range form 48, de 0.30, 1m replay, 3-day horizon)
- I = the impulse into the boundary over 24 15m bars.
- **Naive fade:** at R, TP = S, SL = R + 0.15H.
- **Hook-bounce:** buy the pullback at R − hk·I, TP = R, SL = pull − 0.10I.
- **Hook-continuation:** buy the pullback, TP = R + I, SL = pull − 0.15I.
- hk ∈ {0.5, 0.62, 0.786, 0.86, 1}.

**`hook_break`**
- The break is confirmed at R + 0.05H on 1m.
- **Naive:** entry at R + 0.05H, TP = R + H, SL = M.
- **Hook retest:**
  - push_hi = the max high over the 6h after the break; retest = push_hi − hk·(push_hi − R);
  - TP = push_hi + (push_hi − R); SL = R − 0.15H.
  - **LOOKAHEAD:** push_hi uses the full 6h window, but the retest-fill search starts at the break bar.
- Unresolved trades are dropped (there is no time exit).

**Results (§24, §24b):** NEGATIVE everywhere.
- BTC naive +7.3 bp vs the best hook-bounce +0.8.
- CRASH500 naive break +42 bp vs hook-retest +2.

---

## 1.6 Nested-hook entry / SL and the "honest 1m" books

**Files:** `nested_hook.py`, `fracgate_val.py`, `final_book.py`, `fx_geom.py`, `xsec_fx.py`, `walkforward.py`, `multifold.py`, `book_portfolio.py`.

**Detection**
- `AR.backtest(b15, return_levels=True, form 48 or 96, de 0.30 or 0.15, arm 0.15, min_range 0.0005)`, with no close_inside.
- These are the candidate touches, at the 15m bar open timestamp.

**Confirmed rejection (A1), short at R; longs mirror**
1. On 1m, within 2h of the touch bar's open, find the first high ≥ R.
2. Track E = the running max high.
3. Wait for the first 1m low ≤ R − pull·H, with pull = 0.15 or 0.20.
4. Entry at R − pull·H, with SL = E + BUF·H.
   - In `fracgate_val`: BUF = 0.03. In `final_book`: SL_FIX = 0.08H.
   - TP = S (the full range), or R − tpf·H with tpf = 0.5.
5. Exit scan on 1m from the next bar, horizon 3 days. Unresolved trades are DROPPED.
6. **COST CAVEAT:** the code charges maker 1 bp on entry, but a short triggered when price DROPS to R − pull·H is a **sell-stop (taker)**, not a resting limit.

**Nested entry (A2)**
- i = |E − pull_px|.
- After the pullback, wait for a bounce to pull_px + 0.4·i and short there. This one is a genuine resting limit.
- SL = E + slf·H, with slf = 0.08 (sometimes 0.15). TP = S, or R − tpf·H.

**Confirmed break (A3), long; shorts mirror**
- Trigger: the first 1m high ≥ R + conf·H, conf = 0.05 (0.02 in `tick_break`, 0.10 in `xsec`).
- Entry R + conf·H, TP = R + ext·H with ext = 1.0, SL = M.
- Taker 7 bp on both legs.

**Nested SL:** SL = E + k·i, k ∈ {0.1, 0.25, 0.5}. Null (§27).

**Fractal gate**
- Fade the "fade-signed" instruments (EURUSD, R_50, DXY, BTC) and break the "follow-signed" ones (USDJPY, XAUUSD, CRASH500).
- The signs come from `fractality_test` run on the same data, so this is in-sample selection.

**Results**
- §26 fractal gate: PF 1.04, +2.0 bp, n = 344. Uniform fade −10.4, uniform break −9.6.
- §27 nested entry: R_50 +25.6 bp (PF 1.61), BTC +4.2.
- §28 final book: +1.9 bp, PF 1.03, n = 1043. R_50 +30, CRASH500 break +36, FX all losing.
- §29 risk-parity book Sharpe 1.25. **Overfit.**
- §30 walk-forward (60/40, best of a 24–48-config grid on train):
  - BTC OOS −3.3 bp (n = 233); R_50 −75; XAUUSD −46.
  - OOS portfolio Sharpe −1.51.
- §31 `xsec_fx`: ONE fixed fade config (form 96, de 0.15, pull 0.2, slf 0.08, tpf 0.5, nested) over 25 instruments (FX, indices, WTI/Brent/Copper):
  - pooled OOS +14.2 bp, PF 1.81, n = 147;
  - the train-routed gate −22 bp; uniform break −24.
- §32–34 `multifold` over 6 time folds, with more history added at each step:
  - +24.7 → +7.8 → finally **+3.2 bp, 4/6 folds**;
  - every neighbouring config negative (tp1.0 −3.7, form48 −2.6, pull0.1 −2.2).
  - **Final verdict: no deployable range-fade edge.**

**Lookahead / validity**
- `book_portfolio` risk-parity weights use full-sample vol.
- The fractal-gate sign is chosen in-sample.
- Dropping unresolved trades biases the results.
- AR's own simulated exits decide when the next touch is eligible, so 1m trades can overlap.

**Data:** 1m bars. BTC comes from Binance. FX, indices and commodities from Dukascopy (`*_1m.csv`, `*_pre1m.csv`). R_50 and CRASH500 from Deriv 1m.

---

## 1.7 Tick-execution harnesses — `tick_exec.py`, `tick_reject.py`, `tick_stack.py`, `tick_break.py`

**Data**
- Binance aggTrades for BTC/ETH (`/tmp/BTC_ticks_YYYY-MM.parquet`).
- Deriv 1m bars as the stand-in for spike synthetics.

**`tick_exec`:** the same 15m detection (with close_inside), replayed on ticks, sl ∈ {0.05, 0.1, 0.2}, TP 0.75H.
- Tick PF 0.74 / 0.46 / 0.26, against the 15m proxy at 1.23 / 0.96 / 0.72 (§17).

**`tick_reject`** (no close_inside)
- **Naive:** limit at R, SL R + 0.10H, TP 0.75H.
- **Confirmed rejection:** after the touch, wait for a pullback to R − 0.15H, enter at that tick, SL = rejection extreme + 0.03H.
- 8 months: naive PF 1.04, rejection PF 1.00 (§18).

**`tick_stack`** — the corrected look-ahead-free version
- Entry cost is taker 7 bp, or maker 1 bp tested. TP maker, stop taker.
- **Causal gates** taken from the prior closed bar:
  - trend = sign(c[i−1] − c[i−33]);
  - HTF pos from the 144-bar window ending at i−1;
  - shorts need pos ≥ 0.5 (premium).
- **Results:**
  - §19: TP 1.0H, taker PF 1.12 (+7.4 bp); maker 1.22 (+13.4 bp, n ≈ 109).
  - §20, 12 months: HTF-pos gate PF 1.14 (+9.2 bp).
  - §21: BTC 17 months 1.13 (+8 bp, n = 186); ETH 1.10. With a taker entry, about breakeven.

**`tick_break`** (spike synthetics, 1m execution)
- Break confirmed at R + 0.02H within an hour of the touch; entry there (taker); SL = M; TP 0.5H or 1.0H.
- **Results (§22):**
  - CRASH500 TP1.0 PF 1.47 (+28 bp); BOOM300N TP0.5 1.25; BOOM500 1.26.
  - CRASH300N and BOOM1000 lose.
  - About 104 days only.

---

## 1.8 Range-break synthetics

**Files:** `rb_test.py`, `rb_rrr.py`, `rb_sleeve.py`, `rb_sleeve_paper.py`, `synth_best.py`, `synth_configs.py`, `synth_oos.py`, `structure_search.py`, `multi_asset_adaptive.py`, `best_config.py`.

**`rb_test`:** adaptive fade (form 48, de 0.30, sl 0.20, tp 0.75, arm 0.15, max_life 288, close_inside), TF 1m→4h; variants over_tol 0.5, min_pierce 0.05, nodal_decr.
- RB200 15m PF 2.37 (+16 bp), 1h 1.92 (+27.7 bp), 5/5 folds (§53). *These still carry the close_inside lookahead.*

**`rb_rrr`:** tight SL plus trail.
- Fade capped at about RR 7.7.
- Breakout tp = 8H: RR 13.6, but 8% win and n = 12.
- Breakout tp = 2H: RR 3.35, +32.6 bp (§54).

**`rb_sleeve`** (`rb_sleeve_paper` is the forward paper version, hourly cron on the Deriv WS, last 2000 15m candles)
- 15m fade (as above) plus 15m breakout tp_mult 2.0 (no close_inside).
- Daily P&L, each leg vol-targeted to 10% (EWM span 30, shifted, clip 0–6), combined 50/50.
- **Results (§55):** fade +16 bp, break +32.6 bp, correlation −0.54. Sleeve Sharpe 8.48; under stress cost (15 bp) 5.96. About 36 trading days.

**`synth_best`:** grid search, keeping only configs with PF > 1 in all three chronological blocks.
- RB200: adaptive fade form 96, de 0.15, sl 0.2, tp 0.75, arm 0.15. Blocks 1.17 / 1.25 / 2.50, about 1 trade a week.
- CRASH500: breakout form 48, sl 0.25, tp 1.0.

**`synth_configs` / `synth_oos`:** select on the first 60% (IS), test on the last 40% (OOS).
- RB200 adaptive form 48, de 0.2, sl 0.25: IS 1.89 → OOS 1.98.
- RB100 1.10; CRASH 1.2–1.4.
- Vols / JD / step / BOOM collapse to 0.6–1.3.

**`structure_search`:** best-of-grid on the failing synthetics; selection-biased (§16).
- BOOM500 breakout with body confirm, sl 0.05: PF 1.97.
- CRASH300N breakout with wick confirm: 1.63.
- R_100 fade with updown confirm, sl 0.30: 1.67.

**`multi_asset_adaptive`:** default params, min_range 0.001.
- RB200 1.89, R_75 1.14, CRASH1000 1.17, COPPER 1.07.
- FX < 1.

---

## 1.9 Meta-labelling on range trades

**Files:** `meta_label.py`, `meta_multi.py`, `meta_fx.py`, `meta_crypto.py`, `wf_crypto.py`, `wf_sig.py`, `wf_informative.py`, `wf_funding.py`, `oi_test.py`, `mtf_test.py`, `untried_test.py`, `meta_inform.py`, `meta_silver.py`, `meta_fxcross.py`, `meta_macro.py`, `fx_macro.py`, `mc_robust.py`, `tackle_exec.py`, `adaptive_meta.py`, `refine_b.py`, `breakout_split.py`, `alt_split.py`, `link_confirm.py`, `rf_check.py`, `gnn_test.py`, `graph_discover.py`, `corr_tree.py`, `test_graph_causal.py`, `synth_graph.py`, `synth_real.py`, `sim_test.py`, `liq_test.py`, `regime_label_test.py`.

**Primary model:** `RE.backtest(d15, 48, "breakout" or "fade" or "adaptive", maker)`.

**Features at the entry bar**
- `NF.build(ohlcv, period=48, full_period=192)`, about 50 nimble features (listed in 4.D2). `sim_test` adds `ts_sim=True`.
- Plus `NF.cross_symbol(ref, 48)` for each informative reference: rel_strength, ref_corr, ref_beta, spread_z, ref_align and ref_cos.
- Extras, depending on the script:
  - **funding:** funding, chg3, z30, rolling sum over 21 periods (7 days);
  - **OI:** oi_z96, oi pct_chg8, ls_ratio, ls_chg8, taker_ratio;
  - **macro:** FRED DGS2/DGS10/DFII10/T10YIE/DFF/NFCI/UMCSENT/MICH/UNRATE/CPI/GASREGW plus derived slope, Δ and YoY;
  - **HTF:** mtf 1h/4h;
  - **nested:** 192-bar HTF position, width, side, room;
  - **session:** sin/cos of hour, day of week;
  - **lead-lag:** basket returns at lags 1–3.

**Label and model**
- y = 1[net trade return > 0].
- LightGBM: 400 trees, lr 0.03, 31 leaves, min_child 40, subsample/colsample 0.8, λ 1.
- Take the trade if p ≥ 0.55.

**Validation**
- 70/30 split; or the block walk-forward: start at 40% of trades, retrain every 20 trades on all prior trades.
- Null: 25 shuffle-label walk-forward seeds (sometimes 20 or 15). "REAL" means at or above the 90th percentile and PF > 1.
- **Mode-split:** separate models per mode (fade vs breakout, `refine_b`), per direction (long/short), or per regime (ER ≥ 0.12), each needing ≥ 40 training rows.

**Informative references**
- Crypto proxies: MKT = equal-weight 8-coin index exp(cumsum of mean log return); ALT3 = the alts only.
- MST neighbour: Mantegna distance √(2(1 − corr)) on 15m returns, then a minimum spanning tree.

**LOOKAHEAD**
1. Features are read at the entry bar's row (bar-open timestamp), but they include that bar's close/high/low, while the fill happened intrabar at the touch. That is same-bar lookahead. Fix: use features from bar i−1.
2. FRED daily values are reindexed with ffill onto that date's 00:00. They are released after the close, so this leaks about a day.
3. The MST neighbour and correlation graph are computed on the full sample.
4. `meta_inform` / `topfeats` importance is fit on all trades (reporting only).
5. The MKT/ALT3 proxies exist only for the 2025-26 window, so pooled 2023 trades are dropped.
6. The engine allows no overlapping trades, so labels are known before the next entry; walk-forward is fine on that axis.

**Reported results**

*Crypto breakout*
- ETH single split: PF 1.16 → 1.74 (shuffle 1.28). BTC 1.08 → 2.29.
- Walk-forward significance:
  - BTC bare 1.45 (96th percentile) → with informative references 1.65 (100th).
  - ETH 1.78 (96th) → 2.27 (100th).
  - Alts are within the null.
- ETH + funding + market: 3.06 (100th). BTC + market: 1.70 (100th). OI is about neutral.
- Multi-cycle 2019–26 (`mc_robust`): **80th percentile, not significant.** Positive in 5/6 years; ETH train 2019–22 → test 2023–26 gives 1.04 → 1.48.
- Taker cost (`tackle_exec`): BTC stays at the 100th percentile.

*Adaptive, mode-split and alts*
- Adaptive with a single meta-model: 4th percentile (anti-selects).
- Mode-split (`refine_b`): ETH 1.62 (96th), all 6 years positive. BTC null.
- Breakout split: BTC by direction 1.39 (100th); ETH by regime 1.42 (96th).
- LINK multi-cycle, regime split: 1.32 (100th).

*FX and metals*
- Silver fade, bare: PF 3.82 (100th). Silver with gold-only references, breakout: 1.61 (95th). The full reference set destroys it.
- Dollar confirmation: GBPUSD breakout 1.37 (100th), USDJPY 1.30.
- Macro: borderline.

*Models and features*
- MST neighbour lift +0.105 vs a random reference +0.019 (7/8 targets).
- GCN / GAT / soft trees are no better than LightGBM. RandomForest reproduces the results.
- `sim_test`: ETH with the ts features 1.90 (100th). `liq_coil` is the top feature on RB200.
- Regime-label predictability (`regime_label_test`, labels hurst_regime / er_regime at horizon 48): printed only.

---

## 1.10 Variations, fractality, levers

**`fractality_test`** (A5)
- Bull: (bull engulf OR hammer with lower wick ≥ 2·body and c > o) AND (c − min(low, 48)) ≤ 0.5·ATR14 (SMA of TR).
- Bear: the mirror, near the 48-bar high.
- Forward return over 8 bars in ATR units, on TFs 1/3/5/15/30/60/240m.
- Score = mean/std of the edge across TFs.
- **Results:** R_50 +1.20 / +1.47; EURUSD +1.60; USDJPY −1.08; XAUUSD −1.18; BTC resistance −0.39.
- No stops; this is a measurement.

**`variations`** (15m, close_inside lookahead)
1. **Failed break:** min_pierce 0.05 plus close_inside. Helps XAU (+9.4 bp).
2. **Volatility switch:** ATR% = SMA96(TR/c); fade when below the median, break when above. **The median is full-sample (lookahead).**
3. **Session:** Asia 0–7, London 7–13, NY 13–21 UTC. FX fades are best in NY, DXY in Asia.
4. **Fractal gate.**

**`exit_opt`, `sl_fine`, `rr_max`, `scale_test`, `deep_test`, `node_test`, `mtf_range`, `candle_confirm`, `rejection_zone`:** parameter sweeps over 1.2, with the results quoted there.
- `rr_max` expectancy-maximising geometry:
  - R_75 sl 0.3 / tp 1.5H, +117 bp;
  - BTC sl 0.3 / tp 0.5H, +43 bp;
  - ETH sl 0.2 / tp 0.75, +49 bp.
- All carry the close_inside / confirm lookahead.

**Trader guides** (`docs/range_strategy_for_traders.md`, `range_cheatsheet.md`)
- Discretionary version of A1 / A2 with a 15m box over 12–24h, a rejection candle, a limit on the pullback, SL beyond the wick, TP at the far edge, breakeven at the midline, and an HTF premium/discount filter at about 3× zoom.

**`boom_crash_breakout_guide.md`**
- The A3 recipe: a 15m box, break confirmed by a close beyond the edge, stop-entry, SL at the midline, TP of one box width, and breakeven halfway to target.
- Instruments: BOOM500, CRASH500, BOOM300.

---

## 1.11 Plumbing (one line each)

- **Binance:**
  - `fetch_binance_vision` / `fetch_binance_multi` / `fetch_bn2224` / `fetch_mc` / `fetch_link_mc`: Binance CDN 1m klines → `/tmp/*_1m.csv`.
  - `fetch_1m`: MEXC via ccxt.
  - `fetch_funding`: Binance funding.
  - `fetch_oi`: Binance metrics (oi, ls_ratio, taker_ratio at 5 minutes).
- **Dukascopy:** `fetch_dukascopy` (15m) / `fetch_dukascopy_1m` / `fetch_inform` / `fetch_fxmore` / `fetch_crosses` / `fetch_real2526` / `fetch_stocks` / `fetch_stocks_full`.
- **FRED:** `fetch_macro`.
- **TradingView:** `fetch_tv_fx` / `fetch_total`.
- **Deriv:** `deriv_fetch` / `fetch_deriv_1m` / `fetch_deriv_ticks` / `fetch_deriv_fx` / `fetch_synth_more` (Deriv WS candles or ticks).
- **Run scripts:** `run_*`, `per_year`, `adaptive_raw`, `refine_a`, `run_adaptive_*` are drivers.

---

# 2. range_strat part B — SMC, patterns, momentum, stat-arb, carry, RL, microstructure (sub-agent; results are from design doc §35–84)

**Conventions**
- 1m Dukascopy-like files are resampled UTC to 1h / 4h / 1D. Timestamps are bar open.
- UNIV (11): EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, XAUUSD, SPX500, NAS100, DAX, WTI, COPPER.
- COSTBP per side:

| instrument | EURUSD | GBPUSD | USDJPY | AUDUSD | USDCAD | XAU | SPX | NAS | DAX | WTI | COPPER | BTC | RB200 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bp per side | 0.5 | 0.6 | 0.5 | 0.6 | 0.7 | 1.0 | 1.0 | 1.0 | 1.5 | 2.0 | 2.0 | 5 | 2 |

- ATR48 = SMA48(TR), min_periods 1.

**The `SP.bt` exit engine (`smc_parts.bt`)**
- Entry at the signal-bar close.
- SL = entry − s·1·ATR48(1h); TP = entry + s·1.5·ATR48.
- Scan from the next bar, SL first. No max hold; trades still open at the end are dropped.
- One position at a time. Cost 2 × COSTBP.
- Persistent signals re-enter after each exit.
- "OOS" = the last 40% of pooled trades; folds = 5 time folds.

## A. SMC / structure

**Primitives**
- `smc_setup.swings(close, k=2)`: close pivots, i.e. close[i] = the max over ±k with close[i] > close[i−1]. Confirmed at i + k (causal).
- `structure(df4, k=2, eq_thr=0.5)`: bias +1 if the last two swing highs and the last two swing lows are both rising; −1 if both falling.
  - EQH: if the last two highs are within 0.5·ATR48(4h), use the higher; otherwise the last high. EQL mirrors this.
- `fvgs(fvg_thr=0.25)`: latest unfilled FVG per side.
  - Bull: l[i] > h[i−2], gap > 0.25·ATR48, zone [h[i−2], l[i]].
  - Invalidated when low < zone low.
- `confirm`: bull engulf (c ≥ prev o, o ≤ prev c, previous bar down) OR hammer (lower wick ≥ 1.5·body and c > o). Bear mirrors.
- `structure_engine.analyze(df, k=5, eq_thr=0.4)`:
  - Pivots use ≥ / ≤ against the previous bar and are confirmed at i + k.
  - Close > the unused swing high: BOS if trend ≥ 0, otherwise CHoCH; trend = +1.
  - Bull OB: walk back from the break bar toward the swing-high index; take the last down candle, zone [min(o, c), max(o, c)]. Fallback: o[i] / l[i].
  - OB dies on a close beyond it.
  - prem = (c − sl)/(sh − sl).
- **MTF merge:** the 4h state is stamped at its close (ts + 4h) and merged into 1h with merge_asof backward. Causal.

**`smc_v1_sweep_fvg_bias` — `smc_run.backtest(k=2, eq 0.5, fvg 0.25, sweepM=8, min_rr=1.5)`**
- **Long** needs all of:
  - 4h bias ≥ 0;
  - min(low over bars i−8..i) < EQL and close > EQL;
  - low ≤ fvg_hi and close ≥ fvg_lo of the bull FVG;
  - a bull confirm candle.
- Geometry: entry at close, SL = min(low over bars i−8..i) − 0.1·ATR48(4h), TP = EQH. Requires RR ≥ 1.5.
- Shorts mirror this.
- Results:
  - §40: 6 instruments, +1.4 bp.
  - §43: all 11, PF 0.88, −3.3 bp, n = 542, 2/5 folds.

**`smc_v2` — `smc_run2(k=5)`**
- Long needs:
  - 4h trend ≥ 0;
  - prem ≤ 0.55;
  - (sweep OR OB tap);
  - an in-FVG condition;
  - a confirm candle.
- SL = min(min low over 9 bars, OB bottom) − 0.05·(EQH − EQL), TP = EQH, RR ≥ 1.5.
- Results: IS +15.5 bp, **OOS −5.6** (n = 78). Overfit (§41).

**SMC parts (`smc_parts.signals`, k=5) with the `SP.bt` exit**
- **The parts:**
  - FVG: trend ≥ 0 and price in a bull FVG.
  - SWEEP: min(low over 9 bars) < EQL and close > EQL.
  - OB tap.
  - BOS / CHoCH: the first 1h bar at which the merged 4h flag turns non-zero.
  - PremDisc: prem < 0.3 long, > 0.7 short.
- **Results (§44):**

| part | FVG | SWEEP | OB | CHoCH | PremDisc | **BOS** |
|---|---|---|---|---|---|---|
| bp | −2.1 | −1.8 | −2.6 | −1.1 | −2.2 | **+0.5 (OOS +1.2)** |

  - Combination BOS + FVG: +2.0 bp.

**`structural_decomp`** adds these parts:
- `BOS_int`: 1h internal BOS, from `analyze` with k=2.
- `ict_ote`: long if internal trend ≥ 0, low ≤ sw_hi − 0.62·leg and close ≥ sw_hi − 0.79·leg.
- `ict_displacement`: range > 1.5·ATR48, in the body's direction.
- `crt_sweep_reverse`: sweep of the previous 4h bar's high/low with a close back inside; one extra bar of lag.
- Results (§46): BOS + OTE +6.6 bp (OOS +7.0, n = 190). Nested gate negative.
- §47: the honest `nested_hook_bos` (4h BOS → 1h pullback to an EWMA-learned give-back band ±0.05·I → confirm candle; entry at close; SL = entry − 0.5·I; TP = B + 1.5·I; 48h wait) gives **−7.4 bp, 1/5 folds**.
  - `nested_hook_bos` was in my share: it updates the ratio after each event over the full wait window when there is no entry, so there is a minor leak.

**`sr_fvg_fade` — `sr_fvg.backtest(k=3, fvg_win=4, tol=0.3, buf=0.3)`**
- A swing low (close pivot) becomes support if a bull FVG with gap > 0.2·ATR appears within [pivot, pivot + 4] bars.
- Short when high ≥ R − 0.3·ATR, close < R and a bear confirm candle. SL = R + 0.3·ATR, TP = the nearest support.
- **1-bar lookahead:** FVG validation runs 4 bars past the pivot but the pivot is confirmed after 3.
- Results (§48): PF 0.44, −4.6 bp, n = 67k. §50 (FVG-entry variant): −4.7 bp.

**`sr_fvg_breakout`**
- Long when c[i−1] ≤ r < c[i] − 0.1·ATR and (c − o) > 0.3·ATR.
- SL = level − 0.3·ATR, TP = 2R.
- Result: −2.3 bp, 0/5 folds (§49).

**`volume_profile_fade` — `vol_sr`**
- Profile: 120 bars, 30 bins, body-spread, non-contiguous 70% VA, lagged 2 bars.
- Short when high ≥ VAH − 0.3·ATR, close < VAH and a bear confirm. SL VAH + 0.3·ATR, TP POC.
- Result: −2.7 bp (§51). Needs volume.

**`level_odds`**
- Levels: close pivots (k=3, last 200 bars) clustered within 0.25·ATR, ≥ 2 touches, re-clustered every 24 bars.
- Event: approach within 0.25·ATR, 48-bar cooldown.
- Outcome within 48 bars: HOLD if price closes bounce·ATR in the fade direction; BREAK if it closes brk·ATR beyond.
- Results (§68): crypto P(hold) 0.419, EV +0.042 ATR before cost. RB200 0.46.

**`level_confluence` / `gate`** (FVG continuation)
- Bull FVG l[i] > h[i−2], active 200 bars. Event = re-entry; entry at close.
- TP = entry + 1·ATR; SL = zone far edge − 0.4·ATR.
- **TP is checked before SL** (optimistic); overlapping trades allowed.
- `gate` results (§72) with costs:

| group | crypto | FX | gold | RB200 |
|---|---|---|---|---|
| bp | −4.2 | −1.2 | −0.3 | −7.4 |

**`level_density` / `density2`**
- Ratio-OHLC construction is invalid (§70).
- The beta-neutral raw-alt version shows +3.7 / +7.9 bp before stop and cost, and vanishes with a stop and cost (§71–72).
- `level_odds.load` crypto timestamps are degenerate (int64 // 1e9 issue).

## B. Patterns (1h, `SP.bt` exit, UNIV + RB200)

**`bulkowski.patterns`** — 35 candlesticks. Exact definitions are in the stored report.
- Helpers: ab = SMA20(body); trend = c vs SMA50.
- Examples: TwoWhiteGapping, BeltHoldBull (o == l, body > ab), 3LineStrike (sign inverted), MatchingLow (contrarian).
- Results (§57):
  - Real markets: TwoWhiteGapping OOS +12.8 bp (3/5) but later fragile (§58); BeltHoldBull +2.0 (4/5, n = 1547).
  - RB200: EveningStar +12.4 bp (n = 26).
  - All reversal patterns negative.

**`winners_abcd`** — ABCD:
- Last 4 close pivots (k=3) alternating H, L, H, L.
- |CD − AB|/AB < 0.30; 0.38 < BC/AB < 0.90.
- Enter at D + 3.
- Result: −0.8 bp.

**`harmonics`**
- 5 pivots XABCD. Uses only AB/XA and retD = (A − D)/XA.

| pattern | Gartley | Bat | Butterfly | Crab | Cypher |
|---|---|---|---|---|---|
| AB/XA | 0.55–0.68 | 0.35–0.55 | 0.70–0.90 | 0.35–0.68 | 0.35–0.65 |
| retD | 0.70–0.90 | 0.82–0.95 | 1.15–1.70 | 1.50–1.90 | 0.70–0.90 |

- Results: flat to negative (Cypher OOS +5.7, 2/5).

**`bulkowski_chart`**
- Eq = 0.4%. Patterns: DoubleTop/Bottom, Ascending/Descending Triangle, Rectangle, Head & Shoulders (0.8% shoulder tolerance).
- Persistent signals.
- Results: all −1 to −2.8 bp.

## C. Turns

**`turn_points`** — fade statistical extremes:
- z = (c − EMA50)/std50 > 2 / 2.5 / 3 (optionally plus a candle);
- RSI 30/70 or 20/80;
- Bollinger on EMA50 ± 2·std50;
- climax: range > 2.5·ATR.
- All negative; more extreme is worse (z > 3: −5.9 bp). §62.

**`topbot_ml`**
- 10 clean features: z, RSI, (c − EMA50)/ATR, ret 5/10/20, rvol20, Donchian20 position, velocity, acceleration.
- Model: HistGradientBoosting (150 iterations, depth 3), trained on 60%.
- Labels: low[i] is the minimum of the window, with window sym / fwd / past and K ∈ {3, 6, 12, 24}.
- Trade: the top decile of predictions (**threshold taken from the test set**), hold K bars.
- Results: clean AUC 0.58–0.70; a leaky twin 0.87; PnL ≈ 0 (§65).

**`topbot_trade`:** riding the detected turn gives excess return over drift of about 0 (§66).

**`momentum_turn_exit`:** using the turn detector as an exit on daily TSMOM is no better than random exits (§67).

## D. Momentum (daily)

**`tsmom_v1`**
- pos = sign(P/P[−L] − 1) / (std60·√252), clipped ±3, applied the next day.
- Cost 1 bp·|Δpos|.
- Results (§35): Sharpe 0.66; L20 0.90, L60 0.84, L250 0.84; 4/5 folds.

**`tsmom_v2` (deployed)**
- Inputs: P = union grid with ffill up to 3 days; vol = ewm60 std; LSET = {20, 60, 120, 250}.
- **TS leg:** mean of sign over LSET × 0.10/(vol·√252·√N), applied next day, clip ±3.
- **XS leg:** mean of returns over LSET, demeaned, divided by Σ|·|, × 0.10/(vol·√252)·√N.
- **Portfolio:** vol-target 10% (ewm60, shifted, clip 0–4).
- Cost: COSTBP·|Δpos|. Scale changes are not costed.
- Results (§36): TS 0.64, XS 0.31, **COMBINED 0.74** (maxDD −13%, 88% of years, 5/5 folds).

**`tsmom_vol`**
- Volume variants, all lagged: obv-align (sign(OBV − OBV[−120]) agrees with mom) gives **0.71 (5/5)**; filter, weight and voltrend are worse.
- An unshifted version gave 3.70 (lookahead, fixed).

**`mom_estimators`**
- Estimators: RET = sign(x − x[−L]); SLOPE (OLS); TSMOM z; ATTN = sign(softmax(|r|)·r), which is nearly uniform weights.
- Data: Binance 10 coins; cost 7 bp·|Δsig|.
- Results: 4h all negative; 1d RET L=40 Sharpe 0.54 (OOS 0.74).

**Stocks** (`stock_mom`, `combo_mom`, `xs_stock`, `decomp_stock`)
- After the §82/83 date-alignment fix: US momentum negative; the earlier numbers were beta / bug.
- `stock_mom` also picks L by OOS Sharpe (selection on the test set).

**`momentum_paper`:** forward paper trading of D2. No results yet.

## E. Stat-arb / lead-lag

**`stat_arb`**
- Price-level spread A − βB with β fit on the first 60%; half-life 2–120 bars.
- Enter at |z| > 2, exit at |z| < 0.5, no stop.
- Result: daily OOS Sharpe −0.95.

**`crypto_statarb`**
- Pairs with correlation > 0.55, log β ∈ (0.2, 5), half-life 3–90 days: Sharpe −0.53.
- Residual cross-sectional reversal: −0.4 to −1.6.

**`lead_lag`**
- Sign of Σ (train correlation × lagged leader return); ffill across asynchronous markets creates artifacts.
- Results: hourly −4.85 bp/bar.

## F. Carry and book

**`combine_book.carry_daily`**
- Funding Kalman local-level (q = 0.02, r = 1, roughly an EWMA with α 0.13).
- Signal sign(filtered funding), lagged one period. Per 8h: s·(F + mark_ret − perp_ret) − 15 bp per flip. Equal weight across 60 coins.
- Results (§37–38): funding-only Sharpe 13.4; explicit basis **8.75**, maxDD −1.2%. Short basis-vol tail (§45).
- Needs perp funding, mark and perp history.

**Book combinations**
- 65/35 momentum/carry: Sharpe 2.19, maxDD −11%.
- Risk-parity uses full-sample std (lookahead).

**`fx_carry_v3`:** static rate snapshot; top-6 vs bottom-6 by carry, with an RL exposure timer. **Lookahead:** state features built from shift(−1) returns. No results.

**`sage_exec`**
- Fractional Kelly 0.25, capped at 2%; drawdown ramp between 5% and 15%; maker/taker placement logic.
- `rb200_fade_adapter`: 1h, 48-bar hi/lo; short when close ≥ hi − 0.15·range; TP mid; SL 0.20·range beyond the boundary; p = 0.46.
- Dry run only.

**`sync_carry`, `book_paper`:** plumbing (`sync_carry` uses `.pem` keys under `.secrets`, not read).

## G. RL (nimble `RL`; no documented results)

**Training scheme:** Double-DQN, 60/15/25 split, early stopping on validation Sharpe, reward × 1000. Portfolio models use A2C over {−1, 0, 1} per asset.

| id | notes |
|---|---|
| `fx_unified_rl` v1 | **Lookahead:** context features built from forward returns |
| `fx_unified_rl` v2 | 57 actions, static carry, per-pair spread |
| `fx_portfolio_multi` | |
| `synth_portfolio_rl` / `multi` | reward spreads each trade's final P&L over its holding bars, so it is **not implementable** |
| `regime_switch_rl` | choose mom = sign(c − c[−48]), rev = −sign(c − SMA48), or flat; rule baseline ER(48) ≥ 0.30 → mom; baselines reported without cost. README: always-momentum BTC 15m Sharpe 1.18 beats the RL agent and the ER gate |

## H. Microstructure

- **`liq_edge`:** follow liquidation spikes (≥ the full-sample 90th percentile, **lookahead**), hold 1–8 15m bars. Net at 7 bp only H = 8 is positive (+1.5 bp); at 15 bp all negative (§76). Needs the liquidation stream.
- **`slow_feat`:** IC of 24h net liquidations +0.024 (33 days, noise).
- **`vrp_regime`:** DVOL − RV24; IC(VRP) +0.005; IC(DVOL) +0.049 (40 days).

---

# 3. crt/, fastbull/, tradingview/ (sub-agent)

**Shared `sim()` exit engine** (crt_layers, v2, refine, vp, zm, algovision, tc2021)
- Geometry guard: T > E > S for a long (`crt_core` lacks it, so it books fake wins).
- Risk = |E − S|.
- Scan bars start+1 … start+win, where start is the entry bar. A bar touching both T and S scores −1R; T scores +Rt; S scores −1.
- Timeout marked at close[end−1]. Cost subtracted as cost·E/risk in R.
- Costs (round-trip fraction of price):

| crypto | indices | Deriv | FX (`squeeze_vol`) | forward-edge scripts | `crt_core` / `crt_layers` |
|---|---|---|---|---|---|
| 0.0006 | 0.0003 | 0.0006 | 0.0003 | 0.0004 | none |

- Entry at the confirmation bar's close. Trades overlap.
- 70/30 IS/OOS evaluation split; nothing is fitted.

**Forward-edge metric** (pattern_alpha, tsi, fib, keylevels, geo)
- edge = dir·(c[i+H] − c[i])/ATR14 − cost·c/ATR14, with ATR14 = SMA of TR. No stop.
- The t-stat is inflated by overlapping windows.

**Data**
- ccxt MEXC swaps (3000 bars); Deriv WS (5000).
- yfinance: 15m 1mo; 1h/4h 3mo or 730d; 1d 2y. 4h is resampled UTC from 1h.
- TradingView WS (5000 bars): BINANCE BTC/ETH/SOL, SP:SPX, NASDAQ:NDX, DJ:DJI, OANDA EURUSD/GBPUSD/USDJPY/XAUUSD.

**`crt-core-sweep-revert` — `crt_core.backtest(win=6)`**
- Range candle = bar i (any bar); sweep and confirmation candle = i+1.
- Bull: l[i+1] < l[i] and c[i+1] > l[i]. Bear mirrors. Outside bars that sweep both sides are skipped.
- Geometry: E = c[i+1], S = the swept extreme, T = the opposite extreme of bar i. Window 6 bars. No guard, no cost.
- Nulls: reversed side and random side.
- Results:
  - win rate about 50%, expectancy about 0R;
  - **daily FX inverted:** EURUSD/GBPUSD 1d win rate about 27%, the reversed trade +0.17 / +0.24R.

**`crt-funnel` — `crt_layers.funnel`** (core with the geometry guard, then cumulative layers)
- +HTF: c[i] vs SMA50 on the same timeframe.
- +POI: the swept price lies inside a same-side FVG whose middle bar is within the prior 40 bars. Mitigation is NOT checked.
- +MSS: within 4 bars, c[j] > h[i+1]; entry c[j], window 6.
- Results (R):

| market | CORE | +HTF | +POI | +MSS |
|---|---|---|---|---|
| crypto | −0.03 | | +0.06 (n = 2277) | |
| idx | +0.15 | +0.22 (n = 181) | | |
| fx | −0.15 | | | |

  - The pre-guard "MSS 82–100% win" was an artifact.

**`crt-v2`**
- HTF pairs: 15m→1h, 1h→4h, 4h→1d. Bias SMA50.
- HTF FVG zone valid from formation until a close through it.
- MSS entry within 4 bars.
- Target = the nearest external swing (fractal sw = 4, confirmed) beyond E; otherwise the range projection RH + (RH − RL). Window 12.
- Index session filter: 07–16 UTC, **probably a bug**.
- **LOOKAHEAD:** an HTF FVG becomes usable at the third candle's OPEN instead of its close, and invalidation is stamped at the breaking bar's open.
- Results: crypto IS −0.052 / OOS −0.041; Deriv −0.056 / −0.100.

**`crt-refine`**
- Base: z20 crossing ±2 (fade); SL = the 4-bar extreme; TP = SMA20; 24 bars.
- Book C: CRT-MSS entry within 8 bars.
- Results: crypto A −0.408R, C −0.145; Deriv C −0.018.

**`vprofile`** (helper)
- 24 bins; volume spread across each bar's [l, h]; POC bin; 70% VA grown from the POC toward the larger neighbour, ties up.

**`crt-vp`**
- Sweep must reach beyond VAL / VAH of a 60-bar profile; MSS entry; T = POC.
- Results: crypto OOS −0.237, idx −0.349.

**`vp_only`**
- Profile over 40 bars; event = first close outside the VA.
- FADE: T = POC, S = E ± w with w = VA width. BREAKOUT: T = E ± w, S = POC. 16 bars.
- Results: crypto fade OOS −0.067; idx breakout IS +0.405 / OOS −0.222.

**`zm_confluence`** (layers on the VP fade)
- delta over 9 bars, using buy share (c − l)/(h − l), threshold ±15;
- momentum deceleration, (c − c[−5]) vs the prior 5 bars;
- MTF attention z over 40/120/360 bars.
- Continuation variant (CONT): crypto OOS +0.043 (n = 227); Deriv +0.045.

**`tc2021`** (2-candle breakout)
- Indicators: 20-bar rolling VWAP of hlc3; Wilder RSI14.
- Long when:
  - c[i−2] and c[i−1] are both above VWAP;
  - c[i−1] > c[i−2];
  - 50 ≤ RSI[i−1] ≤ 75;
  - c[i] > max(h[i−1], h[i−2]);
  - vol[i−1] + vol[i−2] > 1.1 × 2 × SMA20(vol) (skipped on Deriv).
- SL = l[i−2]; TP = 2R; 24 bars.
- Results: crypto OOS −0.002; idx OOS +0.013 (n = 476). The closest to breakeven.

**`crt-algovision`**
- Core plus "midnight" = open of the UTC day; long only when E < mid.
- Results: idx OOS +0.061. Midnight should really be NY time.

**`pattern_alpha`** (H = 3, ATR units)
- 16 patterns: big_body ±0.8·ATR, strong/weak close (0.85 / 0.15), hammer, star, engulf, inside, 3-bar streak, range expansion (> 1.6 × avg), gap, bigmove_fade (> 2·ATR over 3 bars).
- Results, all OOS:
  - fading 1–2-bar patterns works in crypto/FX (bull_engulf crypto −0.15, t −4.7; strong_close fx −0.20, t −8.2);
  - indices: bearish patterns fail (bear_engulf −0.35);
  - FX: big moves continue (−0.20 for the fade).

**`novel_discovery`**
- Spearman IC of candle features vs the 3-bar forward return / ATR.
- ret3 in crypto: IC −0.040; streak in FX: −0.031.

**`tsi_test`**
- TSI = 100·EMA13(EMA25(Δc))/EMA13(EMA25(|Δc|)); signal = EMA13(TSI). Events: zero-cross, signal-cross, ±25 fades. H = 5.
- Results: noise; ob_fade in indices −0.53.

**`fib_test`**
- Fractal sw = 5; retracement taps of fib vs non-fib levels.
- All levels negative, fib not special.
- **LOOKAHEAD:** the search starts before the pivot is confirmed.

**`keylevels_test`**
- Breakout / false-break / backcheck vs random levels, with lag-correct scanning.
- Results: noise; the false-break on Deriv is +0.18.

**`geo_test`**
- Squeeze: ATR14 < 0.7·ATR14[−20]; box over 11 bars; first close beyond within 10 bars.
- Triangle: high slope < 0 and low slope > 0 over 21 bars.
- Breakout direction not robust. Squeeze → expansion is real (1.19× FX).

**`squeeze_vol` straddle**
- Buy/sell stops at the 11-bar box, valid 6 bars; SL = the opposite edge; TP = 1 / 1.5 / 2·height; 12-bar exit.
- OOS +0.03 to +0.07R, **but GARCH gives +0.11 to +0.17**, so it is killed (pure geometry).
- Optimism: exact fills through gaps.

**`phase2_cone`** (risk model, not a signal)
- Band = 1.645·σ·√H; switch to σ100 when in a squeeze.
- Conditional exception rate about 9–10%.

**fastbull / tradingview analytics**
- `microstructure`: VWAP; volume profile at the typical-price bin; VA; HVN ≥ 1.5 × mean, LVN ≤ 0.4 × mean; 288 5m bars. Broken import.
- `positioning`: retail long/short ratio. Snapshot only, not backtestable.
- `correlation`: vendor values.
- `quotes`: movers. `scanner`: snapshot screen.
- `study`: TradingView RSI14 / MACD 12-26-9 (SMA types) / BB 20-2, for parity checks.
- The rest is plumbing: WS / HTTP clients, search, calendar, news, collectors to Mongo.
- TradingView calendar has actual / forecast, so surprises might be historical (unverified).

---

# 4. sage_features/, nimble/, notebook, bjorgum.pine, indicators/ (sub-agent)

## A. sage_features (all causal unless noted)

**Orchestrator bugs that produce constant columns**
- `sage_vr_momentum`: key mismatch.
- `sage_half_life`: needs 201 bars, gets 51.
- `sage_cfar_*`: needs 61, gets 51.
- `phx_pdir_dom`: case mismatch.
- `phx_topo_plv`: needs 120, gets 101.
- `phx_topo_complexity`: "MED" vs "MEDIUM".
- `phx_stat_fisher_trigger`: meaningless.
- `phx_stat_bocpd_action`: case mismatch.
- `phx_thermo`: degenerate.

**trend**
- ER over 20: trending > 0.6, ranging < 0.2.
- Variance ratio (k = 5, w = 100): momentum regime > 1.1, reversion < 0.9.
- DE = ER(20); acceleration = ΔDE; coiled spring = DE < 0.3 and acceleration > 0.01.

**level_fatigue**
- resist = max(high over 50), support = min(low over 50).
- A touch is within 0.3%; score = score·0.95 + touch.
- tired > 3 ("break"), fresh < 2 ("hold").

**research_metrics**
- Momentum half-life: from the ACF over lags 1–20; trend regime > 10, MR < 3.
- CFAR on |Δc|: 50-bar window, guard 5, pfa 0.02. Breakout bar when the test cell exceeds the threshold.
- Ising: m = Σr/Σ|r| over 20; χ = var of m over 10; transition when chi_z > 1.5.

**atr**
- SMA of TR (not Wilder despite the docstring).

**physics**
- Hawkes: μ 0.0034, α 0.259, β 0.275. Events = |Δc| > p70. `cascade_active` is near-always on.
- Kramers: distance in raw price units, so meaningless.
- thermodynamic_difficulty: always N/2 = 15 (degenerate).
- pdirection: ≈ sign of the 20-bar move.
- Kinetic energy: KE = 0.5·(Δ20c/20)²/var(Δc); collapse when KE < 0.5·max(KE over 10).
- Higuchi D: < 1.2 trend … > 1.8 noise.
- RQA: DET / LAM.

**physics2** (unused by the orchestrators)
- Hurst R/S: > 0.55 trending, < 0.45 mean-reverting.
- Permutation entropy (order 4); visibility graph; Hill tail exponent; spectral and Tsallis entropy; Lyapunov; Curie–Weiss order.

**statistical**
- Shannon entropy z < −2 → compressed.
- Fisher transform: no smoothing, and a bug biases its direction.
- Pseudo-BOCPD: EXIT at P > 0.7, TIGHTEN at P > 0.3. A possible exit rule.
- feature_bocpd.

**topology**
- strategy_crossover: price units inside exp() make it saturate.
- Betti-0 drop; phase-locking value; persistent homology (needs ripser).
- Docstring claims (86–100% hit, p-values) are not reproducible.

**denoisers**
- linreg candles: formula bug extrapolates about 5 bars ahead.
- Heikin-Ashi; median filter; Kalman 1D (causal).
- **wavelet_denoise: two-sided, LOOKAHEAD.**

**`zma` (ZMA peer, with full geometry)**
- **Attention z:** softmax(|pct change|) weights over 50 bars; z = (c − μ_w)/σ_w.
- **Thresholds:** strong = p85 and weak = p65 of |z| over 250 bars.
- **cumsum slope:** (mean of the last 25 − mean of the first 25)/c_first·100.
- **Momentum classes:** threshold = median |slope| over 200. Classes: Rising/Weakening Demand, Rising/Weakening Supply, Neutral.
- **Recommendation:**
  - STRONG BUY: z < −strong and (Rising Demand or Weakening Supply);
  - BUY DIP: z < −weak and the same momentum;
  - BUY oversold: z < −strong and Neutral or Weakening Demand;
  - WAIT: z < −strong and Rising Supply;
  - sells mirror this.
- **Trade:** entry at close; TP = μ_w; SL = price ∓ 1·σ_w.
- **Applicability gate:** skew, kurtosis, VR (VR is disabled in the lab copy).

**`bjorgum`** (Bjorgum Key Levels, Python port; causal, pivots created at c + right)
- Defaults: left 20, right 15, n_piv 10, Wilder ATR30, mult 0.015, max zone 5%, src hilo.
- Zone = pivot ± min(ATR·mult, 5%·c)/2. Colour flips on a close beyond the zone.
- Flags:
  - breakout: move above, close is the max of 16 closes, and all zones bull;
  - false break, support/resistance push, TSI curl (TSI 25/5/14);
  - 18 candle patterns.
- **Decision:** BUY if there are more bull flags than bear; confidence = min(80, 25 + 18·#flags).
- **Implied geometry:** SL at the nearest support zone, TP at the nearest resistance.
- Pine differences: Pine defaults nPiv 4, mult 0.5, src HA; Pine uses overlap hits and gates patterns.

**`ame`** (Accumulation → Manipulation → Expansion). Many inputs fall back in the lab: no zones, no Mongo, `close[−2]` used as the open.
- **Accumulation:** P10 low / P90 high over 60 bars (excluding t); width < 8%; inside > 60%; ≥ 8 bars inside.
- **Liquidity pools:** swings ±10, clustered at 1%. 13 sweep patterns: single-bar, two-candle, equal lows/highs, pin bar, judas, turtle soup (20-bar extreme, overshoot < 0.5%, opposite close), OTE, and others.
- **CISD:** a colour flip after ≥ 2 opposite bars, body ≥ 40%, close beyond the previous extreme.
- **EXPANSION:** a sweep on bar t, close beyond the previous close, and range ≥ 1.0·ATR14 (1.3 trending, 0.8 mean-reverting).
- **Implied trade:** entry at close; SL beyond the sweep wick; TP at the opposing pool or 2R.
- **Sweep tracker exits:**
  - fail after 2 closes back through the level;
  - confirm at +1.5·ATR;
  - time stop after 20 bars.
- **Precursors:** compression = mean of the last 8 TRs / median of 30 < 0.6; pool exhaustion.
- **Dead code:** `volume_imbalance` never fires; the CISD +15 bonus is never applied.

## B. `bjorgum.pine`
- Pine defaults as above.
- Signals: breakout / breakdown / resistance break / support break / false break / push / curl / 9 pattern families.
- No stops or targets.

## C. `indicators/*.md`

**ZMOMENTUM guide**
- Attention z (period 50; strong/weak = p85/p65 over 200 bars).
- Momentum = linreg slope over 7 bars vs the average of the slopes 7 and 14 bars back.
- Volume profile: 200 bars, 50 bins, delta ±20.
- MTF attended z over 15m/1h/4h/D/5m/W.
- Fade when 3–5 agree: |z| > strong, weakening momentum, outside the VA, confirming delta. TP = z_mean / POC.

**`notes.md`:** a Copper discretionary example, plus non-OHLC idea lists (VIX term structure, credit, breadth, GEX, skew, COT, funding/OI).

## D. nimble

**`features.build(period=50, full_period=250)`**
- **Momentum / ZMA:** ret, ret5, ret20, zma_attn_z, z, cumsum_slope, cumret (start-dependent).
- **Kalman:** kalman_dev, kalman_ret (local-level q 0.02, r 1, ≈ EMA α 0.132).
- **Polynomial:** slope, curvature, r², acceleration (cubic over 50).
- **Swing structure:** retracement depth, lower lows, buyer taps, at 50 and fp = min(250, len/3), so fp depends on dataset length.
- **Regime:** hurst (R/S over 64), er, fractal_align (5/16/50), alpha_corr, disp_contract (zigzag at 2·vol50).
- **Liquidity (sw 12):** coil = log1p(Σ|Δc|/|Δ12c|); drain; ofi; expand.
- **Cosine:** cos_trend, cos_prev. Optional ts_sim: SBD, matrix-profile novelty, analog / SAX forward returns of past windows (causal).
- **S/R:** dist_res, dist_sup, touches, floor-pivot R1/S1 over 25.
- **Profile (50 bars, 24 bins):** poc_dist, va_width, va_pos, in_value.
- **SMC:**
  - fvg; displacement = |c − o|/mean50(h − l);
  - bos vs the prior 20-bar high/low;
  - sweep;
  - prem_disc;
  - ote = exp(−((depth − 0.705)/0.1)²);
  - close_loc, body_ratio, range_atr.
- **Vol / other:** rvol20, parkinson20, hl, co, pos_in_range, rsi (SMA RSI14, not Wilder), volz.
- **MTF:** HTF bars shifted 1 then ffilled (causal).
- **Cross-symbol:** as in 1.9.

**`labels`**

| scheme | definition |
|---|---|
| binary | sign of the forward return |
| ternary | ±0.5·std20·√h band |
| fixed | ±0.5% band |
| quantile | **full-sample edges, LOOKAHEAD** |
| vol | 5 classes of forward z |
| triple_barrier | h 10, ±1·std20, close-path only |
| atr_stop | TP +2·ATR14 (Wilder), SL −1·ATR14, intrabar, 10 bars, tie goes to the stop |
| range | |
| meta | |
| hurst_regime / er_regime | forward 48 bars; ER > 0.15 |

**Models**
- LSTM-attention (hidden 48); ESN (200 units); DeepESN; soft / attention trees; GCN / GAT.
- LightGBM (400 trees, 0.03, 31 leaves) and RandomForest (400 trees, min_leaf 20).

**`predictions.run`**
- Single 70/30 split, **no purge** (the purged walk-forward exists but is unused).
- Scalers fit on train. Sequence models use rows [t−24, t).
- Shuffle control.
- Cost: 6 bp charged per bar.
- The classification equity plot maps class 2 to +3 (bug).
- `importance` selects features on the test split (leak).
- README: about 50% directional accuracy, IC ≈ 0.

**`rl`**
- `sizing_streams`: S = size·next return − λ·size²·std20.
- DQN / Double DQN / Dueling, A2C, PortfolioA2C; 60/15/25 split; early stopping on validation Sharpe.
- Annualisation hardcoded to 15m (96·365 bars).

**`graph`:** MST on full-sample correlation (lookahead if used for selection).

## E. Notebook `Model1(LSTM+Attention)_nimble.ipynb`
- Predicts the next close level with a shuffled split and a full-sample scaler. R² 0.99 means nothing.

## F. Lookahead summary for this section
- Notebook; wavelet; quantile labels; full-sample graph; selection on the test split; no embargo.
- Minor bfills.
- Pivots everywhere are lag-confirmed (Bjorgum at c + 15, AME at ±10).

---

# 5. nn/, datacollector/, top-level files (sub-agent)

**Conventions**
- Implied trade: sign(pred) at the close of bar i, exit at the close of i+H, 6 bp round trip.
- ATR14 = SMA of TR (Wilder in metals_ml and trade_calculator).
- y_vol = log √mean(r²) over i+1…i+H; y_ret = lc[i+H] − lc[i].
- LGBM-dir: 300 trees, 0.02, 15 leaves, min_child 200–400, λ 5.
- UNIVERSE (TradingView 1h / 4h): BTC, ETH, SOL, BNB, XRP; SPX, NDX, DJI; EURUSD, GBPUSD, USDJPY, XAUUSD, AUDUSD.

**`nn/dataset.build(H=12)` features**
- Returns: ret1, aret1, ret3, ret5, accel.
- Vol: log rv over 5/10/22/66, vov = std22 of rv5, atr_p, range_z.
- Candle: upper / lower wick, body_ratio, close_pos, streak, gap/ATR, squeeze = ATR/ATR[−20].
- Trend: dist to EMA20 / EMA50 over ATR. Time: hour, day of week.
- Optional VP (48 bars): vwap, vstd, dpoc, pos, above, below, delta.
- Labels: y_dip / y_up = the 6-bar MAE / MFE in ATR.
- Split: per-series 70/30 with an H embargo, pooled. Clean.

**Models and rules**

| id | rule / model | reported result |
|---|---|---|
| vol-lgbm-har | | R² 0.826 vs HAR 0.799 (iid ≈ 0). Use for sizing / stops |
| dir-ml-price | | 50.2%, −4 bp |
| limit-entry-dip | limit at close − clip(0.6·pred_dip, 0, 1.5)·ATR, else market at i+6 | loses (adverse selection) |
| funding-fade-rule | short when fr_z30 > 1, long when < −1, hold 3 funding periods | +30 bp is a drift artifact |
| cvd-dir | | ≈ 49% |
| pump-dump | | AUC 0.63 (volatility only) |
| regime-follow-fade | eff6 > train median → follow sign(lc − lc[−6]), else fade; hold 6 | **pooled-row split leak** |
| hmm-side | | Viterbi over the full series, deliberate lookahead |
| xs-reversal-crypto | 30 coins, w = −z(L-bar return), dollar-neutral, rebalance every L, 6 bp × turnover | negative |
| xs-rank-ls | | statistic only |
| triple-rsi | RSI 7/14/21 all < 35 / > 65 | pooled split |
| bb-meanrev | %B < 0.02 / > 0.98 | pooled split |
| bb-breakout | %B > 1 / < 0 | pooled split |
| tda-crash | H1 persistence of 8 coins over 40 days, as a de-risk filter | |
| vol-forecaster-rv | RV / BV / jump HAR features, horizon-stacked LGBM | no embargo |
| vol-ridge-export | closed-form ridge, coefficients in the stored report | |
| ofi-sign-1to5m | sign of taker imbalance, earn the next 1–5m bar | needs taker volume |
| cosine-analog | | cross-asset contemporaneous leak |
| lstm-attn-dir | | 51.4% |

The three nn notebooks are leaky (random split, full-sample scaler, price-level target).

**datacollector**
- `hawkes_liq` liquidation-imbalance direction on 15m: needs the OKX liquidation stream.
- `dvol_vol_test`: DVOL lift on 24h vol.
- Backfills of taker-buy klines and RV; forward collector for OI, long/short and taker ratio, and DVOL.

**`events.py`** (causal)
- **sweep-fade:** high > the prior 24-bar max with a close below it → short (mirror for longs).
  - Best geometry: SL 2.5·ATR, TP 4·ATR, 24-bar time stop, high-vol tercile, one fade per cluster. +45.9 bp, PF 1.33 (best of a 16-cell grid).
  - **freqtrade 3-year OOS: −97.99%, Sharpe −2.91.**
- **z-extreme fade:** |z24| > 2. Hit 0.583 in high vol; net −6.7 bp.
- **breakout48:** close > the prior 48-bar max close. Negative.
- **vol-rollover:** passes on the FX control, so killed.

**`esn_models`**
- 300 units, ρ 0.9, leak 0.3, ridge λ 5. HMM variants. No edge.

**`hmm_models`**
- **GHMM / sticky:** Viterbi and smoothed posteriors over the full input, plus full-sample z-scoring (lookahead).
- **BSBF:** causal tempered forward filter, p_stay 0.97, surprise guard.
- **Factorial trend × vol:** fails.
- **IOHMM; DERF:** Dempster–Shafer, decision threshold 0.6.
- **`fused-regime-sizer`:** long exposure E = benign × no-doubt × conflict × agreement, EMA3, lagged one bar.
  - Lower maxDD on 16/16, but Sharpe better on only 6/16.
- **GPSS:** full-sample quantile bands.

**`monte_carlo.derive_zma_states`**
- Return z over 50 bars; |z| ≥ the p85 of the last 50 |z| values → trade the side of z (momentum).
- SL = −k·σ20, TP = +2k·σ20, k = 1.5 / 2 / 3 by vol tercile. **The terciles are full-sample (lookahead).** 48-bar horizon.
- Realised P(stop) 0.56–0.59 (SOL / XAU / XAG).
- The MC engines (bootstrap, FHS-GJR-t, EVT, t, jump, VG, regime, Hawkes, boom/crash) are risk tools.
- `optimal_exit` lift is in-model and optimistic.

**`trade_calculator`** (MC ticket)
- Stop = the p70 of MAE; targets = the p50 / p75 / p90 of MFE over H = 24; size = min(stop-based, CVaR5-based) at 2% risk.

**`momentum_scanner` (Donchian-20)**
- close > max(high[−21..−2]) → long; mirror for short.
- Stop = the MC p70 MAE; target = the p75 MFE; trade only if RR ≥ 1.2; 24 bars.
- About +0.14R on crypto / metals; skip FX.
- Live data includes the unclosed bar.

**`mc_path_plot`:** engine-consensus sign, which is effectively trailing drift.

**metals**
- `causal_features`: about 30 features.
- `funding_features`: + 0.0024 AUC.
- `triple_barrier` ±2σ24 (σ shifted), vertical 24: TFT / GBM no edge.
- `topbot` reversal labels (centred ±12, ≥ 1%): label only.
  - Model AUC 0.59–0.70, but the trade gives −0.196R, worse than random entry.
- `TFTLite`: 4-fold walk-forward with embargo.

**Top-level docs**
- **PHILOSOPHY:** only three things are deployed — cross-asset momentum (Sharpe 0.74), Kalman funding-carry, and the RB200 fade. Range fades, SMC/ICT/CRT, candles, chart patterns, harmonics, lead-lag, stat-arb and turns are below the noise floor.
- **TODO** (ideas, no code): Darvas box, kNN levels, imbalance rate of change, checkpoints, Wyckoff, OBV divergence, 3-state HMM, Sample Entropy.

---

# 6. Not backtestable on OHLC alone (consolidated)

- **Crypto exchange data:**
  - funding history (`combine_book` carry, `wf_funding`, `funding_dir`, metals funding);
  - OI, long/short and taker ratio (Binance keeps only ~30 days; `forward_collect`);
  - taker-buy volume for CVD / OFI (Binance klines only);
  - liquidation streams (`liq_edge`, `slow_feat`, `hawkes_liq`);
  - Deribit DVOL (`vrp_regime`, `dvol_vol_test`).
- **Macro and rates:** FRED macro (`meta_macro`, `fx_macro`; daily, ffill leak); time-varying FX swap rates (`fx_carry_v3` uses a static snapshot).
- **Retail and news:** FastBull retail positioning, keywords, news; TradingView news; calendar surprises (maybe historical, unverified).
- **Other infrastructure:** LLM text embeddings (`cosine_dir`, `text_embed_vol`); Mongo-backed AME and production sweep-side features; live bid/ask (quotes); tick data for honest fade execution (Binance aggTrades; Deriv keeps only 1 day of ticks).
- **Not realisable as trades:** `synth_portfolio_*` reward streams.

# 7. Lookahead to fix when re-implementing (highest impact first)

1. **Same-bar close filters with intrabar limit fills in `adaptive_range`.** This covers close_inside, confirm, htf_prem, nodal and DE. It also covers meta-label features read at the entry bar. Fix: decide at close[i], enter at bar i+1, or use the confirmed-rejection entry.
2. **Hook online learners update on the next 48 bars' MFE at entry time.**
3. **Forward-return features in RL state:** `fx_carry_v3` and `fx_unified_rl`.
4. **Full-sample fitting or thresholds:**
   - HMM Viterbi / smoothing / z-scoring;
   - ZMA-MC vol terciles;
   - `htf_adaptive` cycle length;
   - variations vol median;
   - MST / graph selection;
   - risk-parity weights;
   - `liq_edge` spike quantile;
   - GPSS bands;
   - quantile labels;
   - wavelet denoise.
5. **Test-set thresholds or selection:** `topbot_ml`, `momentum_turn_exit`, `stock_mom` best L, nimble importance selection.
6. **Leaky splits:** pooled-row splits in nn (regime_side, indicator_test, cosine, geom, text); no embargo (nimble, vol_forecaster, return_horizon, lstm).
7. **Pivot / level timing:** `crt_v2` HTF FVG usable at the open (should be the close); `sr_fvg` 1-bar validation lookahead; `fib_test` unconfirmed pivots.
8. **Fill optimism:**
   - TP checked before SL in `gate` / `level_confluence`;
   - straddle fills through gaps;
   - unresolved trades dropped (1m harnesses, `SP.bt`);
   - "maker" entries that are really stop-entries (the A1 pullback short);
   - `crt_core` missing geometry guard.
9. **Unclosed live bars:** ccxt, Deriv, TradingView.
10. **FRED daily ffill to 00:00.**

# 8. Bottom line from the repo's own validation

What survived honest testing:
- **Daily cross-asset momentum.** TSMOM + XSMOM combined, Sharpe 0.74, config-robust. The obv-align variant reaches 0.71 on the TS leg alone.
- **Kalman funding carry** (explicit basis Sharpe 8.75, but short basis-vol tail).
- **RB200 / Deriv range-break fade + breakout** (thin sample; bar results carry the close_inside lookahead).
- **Spike-synthetic confirmed breakout:** CRASH500 / BOOM500 / BOOM300N, 1m execution, about 104 days.
- **Weaker and execution-sensitive:**
  - BTC/ETH tick-confirmed rejection fade, PF about 1.1 with maker fills only;
  - crypto breakout meta-label, 80th percentile multi-cycle;
  - ETH adaptive + mode-split meta, 96th percentile.

Everything else is at or below the noise floor per the repo's own docs: the range fade under full validation, SMC/ICT/CRT, candlestick/chart/harmonic patterns, turns, stat-arb, lead-lag, ML direction models and the HMM direction models.


---

# Appendix A: nn, datacollector, top-level

# Catalogue: `the source`, my share (nn/, datacollector/, top-level model files)

Everything was read-only; nothing was modified. I read all of `nn/*.py`, `nn/LEAKAGE_CHECKLIST.md`, all of `datacollector/`, and the top-level `esn_models.py`, `events.py`, `hmm_models.py` (all 1136 lines), `mc_path_plot.py`, `metals_dl.py`, `metals_ml.py`, `metals_tft.py`, `momentum_scanner.py`, `monte_carlo.py` and `trade_calculator.py`. I skimmed the code cells of the three nn notebooks and the top-level README, PHILOSOPHY and TODO.

These files are research harnesses, not a strategy book. Most of them define an ML model whose prediction becomes a trade only implicitly. That implied trade is `sign(pred)` at the close of bar i, held H bars, exit at the close of bar i+H, minus a flat cost (usually 6 bps round trip, with no bid/ask).

I also pulled reported results from four study docs that discuss these exact files: `docs/studies/NN_MODELS.md`, `HMM_REGIME_SUITE.md`, `METALS_ML.md` and `MONTE_CARLO_ZMA.md`/`MC_TRADE_PIPELINE.md`. They are marked **[doc]** below.

**Common conventions** (they apply unless an entry says otherwise):
- **ATR14** in the nn scripts is the simple 14-bar rolling mean of true range, `max(h-l, |h-c[-1]|, |l-c[-1]|)`. In `metals_ml.py` and `trade_calculator.py` it is Wilder-style instead: `ewm(alpha=1/14)`.
- **Returns** are log returns, `r = diff(log c)`.
- **"Forward vol" label**: `y_vol = log(sqrt(mean(r[i+1..i+H]^2)) + 1e-9)`.
- **"Forward return" label**: `y_ret = log c[i+H] - log c[i]`.
- **Standard LightGBM regressor** ("LGBM-dir"): `n_estimators=300, lr=0.02, num_leaves=15, min_child_samples=200–400, reg_lambda=5, subsample/colsample=0.8`.
- **Standard MLP**: two hidden layers (64/32, 48/16 or 32/8), ReLU, dropout 0.2–0.3, Adam, MSE on the standardised target. The last 15% of train is used for early stopping, with patience 15–18.
- **Universe `UNIVERSE`** (in `nn/dataset.py`), fetched via TradingView `fetch_tv` at 1h and 4h:
  - crypto: BINANCE:BTC/ETH/SOL/BNB/XRP USDT
  - idx: SP:SPX, NASDAQ:NDX, DJ:DJI
  - fx: OANDA:EURUSD, GBPUSD, USDJPY, XAUUSD, AUDUSD

---

## A. Reported-results context (README / PHILOSOPHY / TODO / LEAKAGE_CHECKLIST)

- **README.md** describes the production 7-factor sweep-side score, which is **not implemented in my files** (it lives in production `enrichments.py`): `s = (1/7)(s_pool + s_fatigue + s_ofi + s_fill + s_ob + s_trend + s_position)`, direction = sign(s), conviction = |s|, threshold 0.05.
  - Live: 65–83% sweep fire rate, 21–44% direction accuracy.
  - The XGBoost sweep-direction model reports 65.9% vs a 37% baseline. Its code is not in my share.
- **PHILOSOPHY.md**: the only things deployed are cross-asset momentum (Sharpe 0.74), Kalman funding-carry and the RB200 fade on a Deriv synthetic. It lists as below the noise floor: range fades, SMC/ICT/CRT, about 35 candlestick patterns, chart patterns, ABCD, harmonics, lead-lag, stat-arb and turn prediction. None of the deployed edges are in my files.
- **TODO.md**: ideas with no code in my share:
  - kNN-density key levels
  - OFI/CVD rate-of-change ("imbalance ROC")
  - profit checkpoints (re-check imbalance at TP1/2/3 = 1R/2R/3R; close if it flipped)
  - perceptron
  - Darvas box (new N-bar high, 3 bars without exceeding it = box top; lowest low = box bottom; confirmed after 3 bars without breaking the bottom)
  - Sample Entropy
  - Wyckoff SC/Spring/ST volume divergence
  - OBV divergence
  - 3-state HMM regime
- **LEAKAGE_CHECKLIST.md** states four traps: a random split, predicting the price level, a scaler fit on the full series, and no control/cost. Its calibration anchors:
  - honest direction ≈ 50–51%
  - honest vol R² ≈ 0.80–0.83
  - anything above 55% on daily direction is presumed to be a leak

---

## B. `nn/` — shared foundation

### B0. `nn/dataset.py` — the shared feature and label factory (used by vol_model, dir_model, entry_model, pump_dump, lstm_*, vol_*, deriv_synth)

`build(df, H=12, with_time=True, with_vp=False)` computes the following at bar i, using data ≤ i only.

**Price features:**

| Feature | Definition |
|---|---|
| `ret1` | `r` |
| `aret1` | `|r|` |
| `ret3` | `lc - lc[-3]` |
| `ret5` | `lc - lc[-5]` |
| `accel` | `(lc - lc[-3]) - (lc[-3] - lc[-6])` |

**Volatility features:**

| Feature | Definition |
|---|---|
| `rv5`, `rv10`, `rv22`, `rv66` | `log(rolling std(r, w, ddof=1) + 1e-9)` |
| `vov` | rolling std over 22 bars of the **raw** rv5 std |
| `atr_p` | `ATR14 / c` |
| `range_z` | `(h-l) / ATR14` |

**Candle-shape and trend features:**

| Feature | Definition |
|---|---|
| `upper_wick` | `(h - max(o,c)) / (h-l)` |
| `lower_wick` | `(min(o,c) - l) / (h-l)` |
| `body_ratio` | `(c-o) / (h-l)` |
| `close_pos` | `(c-l) / (h-l)` |
| `streak` | consecutive same-sign return count (signed: +n up, −n down) |
| `gap` | `(o - c[-1]) / ATR14` |
| `squeeze` | `ATR14 / ATR14[-20]` |
| `dist_ema20` | `(c - EMA20) / ATR14`, with `ewm(span, adjust=False)` |
| `dist_ema50` | `(c - EMA50) / ATR14` |
| `hour`, `dow` | UTC hour and day of week, raw integers |

**Volume-profile features** (`with_vp`, LB = 48), with `tp = (h+l+c)/3` and `v` = volume (or 1 if missing):

| Feature | Definition |
|---|---|
| (helper) `vwap` | `Σ(tp·v) / Σv` over 48 bars |
| (helper) `vstd` | `sqrt(Σ(tp²v)/Σv - vwap²)` |
| `vp_dpoc` | `(c - vwap) / ATR` |
| `vp_pos` | `(c - vwap) / vstd` |
| `vp_above` | `c > vwap + vstd` |
| `vp_below` | `c < vwap - vstd` |
| `vp_delta` | `Σ(v · ((c-l) - (h-c))/(h-l)) / Σv` over 48 bars |

**Labels:**
- `y_vol` and `y_ret` over H, as defined in the conventions; `y_dir = sign(y_ret)`.
- With K = 6 fixed (it does not follow H):
  - `y_dip = (c - min(l[i+1..i+6])) / ATR`
  - `y_up = (max(h[i+1..i+6]) - c) / ATR`
  - `runK = (c - c[i+6]) / ATR`

**Synthetic controls:** iid Gaussian (vol 0.004 per sub-step, 8 sub-steps per bar, 5000 bars) and GARCH(1,1) (ω=3e-7, α=0.07, β=0.86, shocks clipped at ±6σ). Both use 12 seeds.

**Split — `walk_forward(meta, H, train_frac=0.70)`:** per series, the first 70% is train, minus the last H rows as an embargo; the last 30% is test. There is a single fold, not a rolling walk-forward. All series are pooled into one model.

**Lookahead notes:** wrapped `np.roll` values at the series start fall in rows that are dropped (rv66 needs 66 bars), so the features are clean. Pooling is cross-sectional: train holds BTC's first 70% while test holds ETH's last 30%, which is calendar-aligned, so no contemporaneous leak there.

---

### B1. `vol-lgbm-har` — `nn/vol_model.py:eval_source`
- **Target:** `y_vol`, H = 12. Features: all 23 `FEATURES`. 1h + 4h, crypto/idx/fx pooled.
- **Models compared:**
  - persistence (`pred = rv22`)
  - HAR (OLS on rv5/rv22/rv66)
  - LightGBM (500 trees, lr 0.03, 31 leaves, min_child 200, λ 2)
  - MLP 64-32
- **Metrics:** OOS R² on log-vol, and QLIKE.
- **Data:** OHLC (plus timestamps).
- **Reported [doc NN_MODELS]:**

| | persist | HAR | LGBM | NN |
|---|---|---|---|---|
| real R² | 0.757 | 0.799 | **0.826** | 0.816 |
| iid control R² | −0.56 | ≈0 | ≈0 | ≈0 |

  QLIKE is 0.41 (LGBM) vs 0.51 (HAR). Top features: rv66, hour/dow, ATR, vov, squeeze.
- **Trade use:** none directly; it is a sizing/stop input. The implied geometry is a stop or position size scaled by the predicted σ.
- **Lookahead:** none found. The scaler is fit on train only.

### B2. `dir-ml-price` — `nn/dir_model.py:eval_source`
- **Target:** `y_ret`, H = 12. Features: the 23 `FEATURES`.
- **Models:** OLS linear on z-scored features; LightGBM (300 trees, lr 0.02, 15 leaves, min_child 400, λ 5); MLP 48-16.
- **Trade:** long/short `sign(pred)` at the close of bar i, exit at close i+12, cost 6 bps per trade.
- **Metrics:** accuracy, rank-IC, net bps.
- **Controls:** GARCH, and shuffled labels.
- **Reported [doc]:** real LGBM 50.2%, IC +0.002, **−4 bps**. GARCH control 50.7%, shuffle 50.5%.
  - By group: crypto 47.7%, fx 49.1%, idx 56.3% vs always-long 57.7%, so the index result is drift.
- **Lookahead:** none found.

### B3. `limit-entry-dip` — `nn/entry_model.py:policy_improvement`
- **Setup:** direction is assumed long (decided elsewhere). Predict `y_dip`, the maximum adverse excursion in ATR over the next 6 bars, using LGBM (400 trees) or the MLP.
- **Geometry:**
  1. Place a limit at `close_i - off·ATR14`, where `off = clip(0.6·pred_dip, 0, 1.5)`.
  2. Filled if the realised dip ≥ off; the improvement is then `off`.
  3. Otherwise enter at market at `close_{i+6}`; the improvement is `runK = (c_i - c_{i+6}) / ATR`.
  4. Subtract a cost of 0.02 ATR.
- **Baselines:** market-now, and a fixed 0.5-ATR offset.
- **Reported [doc]:** real −0.058 ATR, iid −0.126, garch −0.118. Limit entry loses to market entry because of adverse selection.
- **Data:** OHLC.

### B4. `funding-fade-rule` and `funding-dir-ml` — `nn/funding_dir.py`
- **Data:** MEXC perpetual funding history (8h) for 10 coins (BTC, ETH, SOL, BNB, XRP, DOGE, AVAX, LINK, LTC, ADA), plus MEXC 4h OHLCV. Each funding timestamp is merged `asof backward` to the 4h bar whose open is ≤ the funding time. The timeline is the 8h funding events.
- **Features:**

| Group | Feature | Definition |
|---|---|---|
| Funding | `fr` | the funding rate |
| | `fr_abs` | `|fr|` |
| | `fr_sign` | `sign(fr)` |
| | `fr_z` | `(fr - mean30) / std30` (30 funding events ≈ 10 days) |
| | `fr_ema` | EMA, span 10 |
| | `fr_chg` | `fr - fr[-3]` |
| | `fr_cum` | rolling sum over 9 |
| Flow | `vol_z` | `(v - mean30) / std30` |
| | `delta` | `((c-l) - (h-c)) / (h-l)`, on the merged 4h bar |
| Price | `ret1`, `ret3` | returns on the funding timeline |
| | `rv` | rolling std of ret1, window 10 |

- **Label:** `y = lc[i+H] - lc[i]` with H = 3 funding periods (24h).
- **Rule — `funding-fade-rule`:** signal −1 if `fr_z > 1`, +1 if `fr_z < −1`, otherwise flat. Enter at the close of the merged bar, exit 3 funding periods later; cost 6 bps.
- **ML:** LGBM and MLP 32-8 on four feature sets (PRICE, FUND, FUND+FLOW, ALL); per-series 70/30 split with a 3-row embargo.
- **Reported [doc]:** the shuffle control reproduces the apparent +30 bps edge, so it is a drift artifact; faint IC +0.047 (≈1.7σ); data-limited to 156 days.
- **Implementable:** yes, with a historical funding feed (Binance/Bybit/MEXC) and OHLC.

### B5. `cvd-dir-ml` — `nn/cvd_dir.py:feats`
- **Data:** Binance USD-M klines with taker-buy base volume (kline field 9), 1h or 4h, 10 symbols, 2 years, from `cvd_backfill.py`.
- **Base quantities:** `delta = 2·taker_buy - vol`; `cvd = cumsum(delta)`.
- **PRICE features:**

| Feature | Definition |
|---|---|
| `ret1` | `r` |
| `ret3` | 3-bar log return |
| `ret6` | 6-bar log return |
| `rv` | 12-bar std of r |
| `atr_p` | `ATR14 / c` |

- **CVD features:**

| Feature | Definition |
|---|---|
| `cvd_ratio` | `delta / vol` |
| `cvd_slope` | `(cvd - cvd[-6]) / Σvol over 6 bars` |
| `cvd_slope_l` | the same over 24 bars |
| `cvd_z` | 48-bar z-score of `cvd_ratio` |
| `cvd_ema` | EMA span 12 of `cvd_ratio` |
| `cvd_accel` | `cvd_slope - cvd_slope[-6]` |
| `cvd_div` | `sign(ret6) - sign(cvd_slope)` |

- **Label:** `y_ret`, H = 6 (default). Trade: sign(pred), hold H, cost 6 bps.
- **Reported [doc]:** ≈49% at H = 1/3/6 (gross too); CVD-only equals the shuffle control.

### B6. `pump-dump-clf` — `nn/pump_dump.py:eval_source`
- **Labels:** pump `y_up > τ`, dump `y_dip > τ`, with τ = 2 ATR over the next 6 bars.
- **Model:** LGBM classifier on `FEATURES`, or `FEATURES + FEATURES_VP`.
- **Metrics:** AUC; `corr(p_pump, p_dump)`; spread-IC = `rank-corr(p_pump - p_dump, y_ret)`.
- **Implied trades:**
  - a straddle-like vol trade when p_pump and p_dump are high
  - direction = `sign(p_pump - p_dump)`, hold 12 bars
- **Reported [doc]:** AUC ≈ 0.63 (this is volatility), corr(p,d) = 0.74, spread-IC ≈ 0; the VP features add nothing.

### B7. `regime-follow-fade` — `nn/regime_side.py:main`
- **Features** (K = 6):

| Feature | Definition |
|---|---|
| `eff` (Kaufman efficiency ratio) | `|c - c[-6]| / Σ|Δc| over 6 bars` |
| `ac1` | rolling 30-bar lag-1 autocorrelation of r |
| `vr` | `(Σ r over 6)² / (6 · mean(r²) over 6)` |
| `trend` | `(c - SMA50) / ATR14` |
| `rv` | 22-bar std of r |
| `recent` | `lc - lc[-6]` |

- **Rule:**
  - if `eff > median(eff over train)`: signal = `sign(recent)` (follow)
  - otherwise: signal = `-sign(recent)` (fade)
  - Hold H = 6 bars, cost 6 bps.
- **Variant:** only on bars with `rv ≥ train 66th percentile`.
- **ML variant:** LGBM on the 6 regime features.
- **Universe:** BTC, ETH, SOL, SPX, NDX, EURUSD, XAUUSD; 1h and 4h.
- **Lookahead/split flaw:** all series are concatenated and the split is a single row-fraction (`cut = 0.7·n` of the pooled rows). The test set is therefore the *last symbols*, not the last time period, and train/test share calendar time across correlated assets.
- **Results:** printed only; no doc number found.

### B8. `hmm-side` — `nn/hmm_side.py:run`
- **Model:** GaussianHMM with 2, 3 or 4 states, diagonal covariance, observations `[r, |r|, rv12]`, fit on the first 70%.
- **Mapping:** each state maps to the sign of its *train* mean 6-bar forward return. The prediction is that sign.
- **Explicit lookahead:** states are decoded by **Viterbi over the full series** (`hmm.predict(obs)`). The file says this is lookahead-optimistic on purpose: if even this cannot beat 50%, a causal version cannot.
- **Trade:** sign by state, hold 6 bars.

### B9. `next-bar-bigmove-clf` — `nn/when_bigmove.py`
- **Label:** `|r[i+1]| > 2 · std(r over the last 20 bars)`.
- **Features:**
  - seasonality: sin/cos of hour and of day of week
  - volatility: `rv12`, `|r|`, `range_z`, `squeeze`, 3-bar mean of `|r|`
- **Model:** LGBM classifier; AUC compared across seasonality-only, vol-only and all.
- **Split flaw:** the same pooled row-fraction split as B7.
- **Use:** a vol/timing filter, not direction.

### B10. `xs-reversal-crypto` — `nn/xs_reversal.py:main` (a genuine portfolio backtest)
- **Universe:** 30 Binance USDT spot pairs (BTC … ALGO) on 4h or 1h. Uses closes only.
- **Rebalance step:** at each rebalance bar t, for L ∈ {3, 6, 12, 24}:
  1. `past = lc_t - lc_{t-L}`
  2. `z` = cross-sectional z-score of `past`
  3. `w = -z`, demeaned, then normalised so `Σ|w| = 1` (dollar-neutral reversal: long losers, short winners)
- **Hold and cost:** hold L bars with non-overlapping rebalances (step L). Cost is `6 bps × turnover`, where turnover = `Σ|w_t - w_prev|`.
- **Metrics:** net per rebalance; annualised Sharpe (`sqrt(rebalances per year)`); break-even cost = `mean gross / mean turnover`. Control: a randomly permuted `w`.
- **Split:** test is the last 30% of time (no fitting at all).
- **Reported [doc METALS_ML §7, a related experiment]:** short-term XS reversal loses net of cost in nearly every (L,H) cell, Sharpe −3 to +0.2. Longer-horizon XS **momentum** is the deployed edge (not in my files).

### B11. `xs-rank-ls` (momentum or reversal) — `nn/cross_sectional.py`
- **Universe:** the 10 cvd_data symbols, 4h/1h closes.
- **Signal:** for L ∈ {3, 6, 12, 24, 48}, rank `past` cross-sectionally; weights `w = (rank - mean rank)`, normalised so `Σ|w| = 1`. The forward horizon is H = 6.
- **Metrics:** cross-sectional rank-IC each bar and long/short net = `Σ w·fwd - cost·Σ|w|`, divided by H.
- **Caveat:** this is computed every bar with overlapping H-bar windows, and cost is charged on gross exposure rather than turnover. It is a statistic, not a trade simulation.
- **Rule:** IC > 0 means momentum, IC < 0 means reversal.

### B12. `deriv-synth-check` — `nn/deriv_synth.py`
- **Data:** Deriv R_100, R_75, R_50, R_25, R_10 at 1h and 4h, via `fetch_deriv_v`.
- **Tests (dataset features, H = 12):**
  - vol R² (LGBM)
  - big-move AUC (`y_up > 2 ATR`)
  - direction accuracy/IC (LGBM-dir)
- **Comments:** real markets give vol R² ≈ 0.6–0.8 and AUC ≈ 0.6–0.67.

### B13. `triple-rsi`, `bb-meanrev` and `bb-breakout` — `nn/indicator_test.py`
- **Indicator definitions:**
  - RSI: Wilder, `ewm(alpha=1/n, adjust=False)` on the up/down diffs.
  - Bollinger: SMA20 ± 2·std20 (ddof=1); `pctB = (c - lower) / (upper - lower)`; `bw = (upper - lower) / mid`.
  - `rsi_slope = rsi14 - rsi14[-3]`.
- **Rules** (enter at the close of bar i, hold H = 6 bars, cost 6 bps):
  - `triple-rsi`: long if RSI7, RSI14 and RSI21 are **all < 35**; short if all > 65.
  - `bb-meanrev`: long if %B < 0.02; short if %B > 0.98.
  - `bb-breakout`: long if %B > 1.0; short if %B < 0.0.
- **ML:** LGBM and MLP on `[rsi7, rsi14, rsi21, pctB, bw, rsi_slope, atr_p]`.
- **Universe:** BTC, ETH, SOL, SPX, NDX, EURUSD, GBPUSD, XAUUSD; 1h and 4h.
- **Split flaw:** the pooled row-fraction split (as in B7). The rule evaluation has no fitting, so the rules themselves are clean, but they are only scored on the "test" rows (the last symbols). The shuffle control also permutes the test labels, which is unusual.

### B14. `tda-crash-warning` — `nn/tda_crash.py`
- **Data:** daily closes for 8 crypto (BTC, ETH, SOL, BNB, XRP, DOGE, AVAX, LINK).
- **Signal (W = 40, K = 10):**
  1. Standardise the last 40 days of returns per asset; this gives a 40×8 point cloud.
  2. Run ripser on it; take the H1 persistence diagram.
  3. `instab_t = Σ(death - birth)`, the L1 persistence.
- **Label:** forward 10-day max drawdown of the equal-weight index; "crash" = the bottom decile.
- **Metrics:** rank-IC and AUC, against a permutation control.
- **Implied geometry:** a de-risking / flat filter when instability is high.
- **Lookahead:** the crash threshold is a full-sample decile, which affects evaluation only.

### B15. `tda-vol-feature` — `nn/tda_vol.py`
- **Signal:** time-delay embedding of 1h returns (dim 3, delay 2), rolling 40-point H1 L1 persistence, logged.
- **Use:** an added feature in the 24h forward-vol LGBM. Base features: rv5/22/66, `atr_p` (here = 14-bar mean |r|), range_z, vov, hour.
- **Universe:** 8 Binance crypto, 1h. Per-series 70/30 split, no embargo.

### B16. `crypto-1m-rv` — `nn/crypto_1m_vol.py`
- **Data:** MEXC 1-minute swap OHLCV for 30 days.
- **Construction:** hourly `RV = Σ` of intra-hour 1-minute r² (the cross-hour return is reset to 0).
- **Comparison** (target: 24h forward vol):
  - close-to-close HAR: log std of 1h returns over 6/24/72
  - 1m-RV HAR: log mean RV over 6/24/72
- **Data needed:** 1-minute bars.

### B17. `crypto-vol-improve` — `nn/crypto_vol_improve.py`
- **Base features:** rv5/10/22/66, atr_p, range_z, aret1, vov, hour.
- **Additions:**

| Group | Feature | Definition |
|---|---|---|
| Range estimators | Parkinson | `log(mean over 12 of ln(h/l)² / (4 ln 2))` |
| | Garman–Klass | `log|mean over 12 of 0.5·ln(h/l)² - (2 ln 2 - 1)·ln(c/o)²|` |
| Leverage | `downsemi` | log 22-bar std of `min(r, 0)` |
| | `lev` | `mean10(r) · |r|` |
| Spillover | `btc_rv` | BTC log rv22 |
| | `rv_vs_btc` | `rv22 - btc_rv` |

- **Universe:** 10 alts at 1h; target is 24h forward vol.

### B18. `geom-fractal` — `nn/geom_vol.py`
- **Features** (on rv_data hourly; computed over the previous W points, excluding the current):

| Feature | Definition |
|---|---|
| `h_ret` | rolling R/S Hurst of returns, W = 64: `log(R/S)/log(n)` |
| `h_vol` | Hurst of log RV, W = 64 |
| `higuchi` | Higuchi fractal dimension of log close, W = 48, kmax = 6 |
| `vratio` | `var(4-bar sums) / (4 · var(r))` over 64 |

- **Targets:** 24h forward vol (R²) and 24h direction (classification).
- **Split flaw:** a pooled row-fraction split across symbols.

### B19. `cosine-analog-vol` and `cosine-analog-dir` — `nn/cosine_analog_vol.py`, `nn/cosine_dir.py`
- **Analog step:**
  1. z-score the HAR-RV feature vector (lrv, rv6, rv24, rv168, bv24, jump, vov, atr_p, hour, dow) using reference-set stats.
  2. Take cosine similarity to the "reference" rows.
  3. Average the realised forward-vol label (or 24h return) of the K = 50 most similar rows; that average is the feature.
- **Split / lookahead:** the "reference" is the first 40% of **pooled rows**, i.e. other symbols, not earlier time. Training is rows 40–70%, test the last 30%. This is a contemporaneous cross-asset leak: the reference labels can cover the same calendar time as the test bars.
- **`cosine_dir` extras:**
  - adds embeddings from mxbai-embed-large of verbal 8-hour return strings, reduced by PCA(16) fit on train
  - LGBM classifier
  - trade = long if p > 0.5 else short, hold 24h, cost 6 bps
- **Data:** a local Ollama embedding server, for the text part.

### B20. `imbalance-predictability` — `nn/imbalance_predict.py`
- **Quantity:** `imb = clip(2·taker_buy/vol - 1, -1, 1)` on 1h bars.
- **Tests:**
  1. `imb_t` from same-bar price features (tautological)
  2. `imb_{t+1}` from price
  3. `imb_{t+1}` from its own lags (l1, l2, l3) and a 6-bar mean
  4. both together
- **Metric:** R², with a shuffle control.
- **Data:** taker-buy volume.

### B21. `ofi-sign-1to5m` — `nn/ofi_1to5m.py:sig`
- **Data:** Binance USD-M 1-minute klines with taker-buy volume (field 9), 21 days, for BTC, ETH, SOL, BNB, DOGE. Aggregated to 1, 3 or 5 minutes.
- **Signal:** `imb = 2·taker_buy/vol - 1`; cumulative variant `cof = Σ imb over 5 bars`.
- **Trade:** position = `sign(imb_t)`, earning the next bar's log return. Effectively one round trip per bar.
- **Costs and metrics:** IC, direction accuracy, gross bps per bar, and net at 5 or 10 bps per round trip; also imbalance autocorrelation and a shuffle IC.

### B22. `return-multi-horizon` — `nn/return_horizon.py`
- **Model:** LGBM-dir on the HAR-RV features (rv_data, crypto 1h) for H ∈ {1, 4, 6, 12, 24, 48, 72, 168} hours.
- **Trade and metrics:** sign(pred), cost 6 bps; reports always-long bps alongside.
- **Split:** per series 70/30, **no embargo**. The boundary overlaps by H rows; this matters at H = 168.

### B23. `semivar-harq` — `nn/semivar_harq.py`
- **Data:** MEXC 1-minute, 28 days, aggregated to hourly (n ≥ 30 one-minute bars per hour).
- **Hourly quantities:**

| Quantity | Definition |
|---|---|
| RV | `Σr²` |
| BV | `(π/2) Σ|r_t||r_{t-1}|` |
| RQ | `(n/3) Σ r⁴` |
| RSM | `Σ r² · 1[r < 0]` |

- **Features:** lrv; log rv6 and rv24 (means); `dshare = RSM/RV`; `lrsm`; `lrq`; `rqx = sqrt(RQ) · lrv`.
- **Target:** `0.5 · log(mean RV over H)` for H ∈ {4, 12, 24}.

### B24. `text-embed-vol` — `nn/text_embed_vol.py`
- **Signal:** mxbai embeddings of raw-number or verbal 8-hour return windows, reduced by PCA(16) fit on train, added to HAR-RV features for 24h vol.
- **Split:** pooled-row split (as in B7).
- **Data:** needs a local LLM embedding server.

### B25. `vol-by-group`, `vol-horizon` and `vol-ridge-export` — `nn/vol_bygroup.py`, `vol_horizon.py`, `vol_export.py`
- **`vol_bygroup`:** per-asset-class vol R² and big-move AUC (`y_up > 2`). Within each group the split is a pooled-row 70% with a 12-row gap.
- **`vol_horizon`:** daily-bar forward vol for H = 1, 3, 5, 7 bars; HAR vs LGBM; iid control.
- **`vol_export`:** a closed-form ridge (λ = 10) on z-scored features, exported to `nn/vol_coefs.json` for container use.
  - Features: rv5, rv10, rv22, rv66, atr_p, vov, squeeze, range_z, aret1, plus sin/cos of hour and day of week; H = 12.
  - Exported intercept and weights, in that feature order: `W = [-5.695, 0.065, -0.023, 0.282, 0.586, 0.141, -0.132, 0.019, 0.048, -0.015, 0.021, -0.014, 0.023, 0.026]` (the first entry is the intercept; mu/sd are stored in the JSON).
  - This is directly re-implementable as a σ forecast: `y = log σ_per-bar` over the next 12 bars.

### B26. `vol-forecaster` (horizon-conditioned) — `nn/vol_forecaster.py:train/forecast_vol`
- **Model:** one LGBM (600 trees, lr 0.03, 48 leaves, min_child 200) on the dataset `FEATURES` plus `horizon`, stacked over H ∈ {4, 6, 12, 24, 48, 72, 120, 168} on 1h bars.
- **Output:** `forecast_vol(df_1h, H)` returns (log σ per bar, σ); scale by √H for the full move.
- **Split:** per (series, horizon) 70/30, **no embargo**.
- **Use:** stop/target/size scaling.

### B27. `vol-forecaster-rv` (production candidate) — `nn/vol_forecaster_rv.py:features`
- **Data:** hourly bars carrying RV/BV/RQ/RSM from `rv_backfill.py` (Binance 1-minute).
- **Features:**

| Feature | Definition |
|---|---|
| `lrv` | `log RV` |
| `rv6`, `rv24`, `rv168` | log of mean RV over 6/24/168 hours |
| `bv24` | log of mean BV over 24 hours |
| `jump` | `log(max(RV - BV, 0)) - bv24` |
| `vov` | 24-hour std of lrv |
| `atr_p` | ATR14 / c |
| `hour`, `dow` | time of day / week |
| optional: `dshare`, `lrq`, `rqx` | as in B23 |

- **Model and split:** the target, horizon stacking and model are as in B26. Per-series 70/30 split, no embargo.

---

### B28. Notebooks (`Model1(LSTM+Attention).ipynb`, `LSTM_Plus_Attention.ipynb`, `LSTM_plus_Attn_Adv.ipynb`) — **all leaky; documented as fake**
- **`nb-lstm-level`:** predicts the **next close level** (MinMax-scaled) from the previous close (1 step), or a 60-step window. Data:
  - AAPL daily 2020–2024
  - AAPL 15m over 60 days
  - a sine-plus-noise toy series
  Flaws (each present in at least one version): `train_test_split(random_state=42)` (a random split); `scaler.fit_transform` on the **full series**; level-target RMSE/MSE. One cell in `Model1` uses a chronological 80/20 split but still scales on the full series.
  Printed: MSE 0.0238 (sine); 10.55 → 5.90 and 9.22 → 5.53 on AAPL levels; 0.244 and 0.263 (15m); Adv test loss 0.0049, MAE 0.067, RMSE 0.070 on the scaled level. It also produced a 4-day "forecast" of 172.08 → 173.75.
- **`nb-ud-pattern`:** `Movement` = U if close > open, D if close < open. Features are a single bar's OHLCV (MinMax on the full series); the label is the 16-class `next_4` U/D pattern of the next 4 bars. LSTM+attention classifier with a random split. No accuracy was printed in the outputs.
- **Honest replacement:** `nn/lstm_attention.py` (B29).

### B29. `lstm-attn-dir` and `lstm-attn-vol` — `nn/lstm_attention.py`, `nn/lstm_vol.py`
- **Inputs:** sequences of the last L = 24 bars of the 23 `FEATURES`.
- **Model:** LSTM (h = 48 for direction, 64 for vol) → softmax attention pooling → dropout → linear.
- **Targets:** `y_ret` (H = 12) or `y_vol` (H = 12).
- **Split and scaling:** chronological 70/30 per series, **no embargo**; the scaler is fit on train.
- **Trade (direction):** sign(pred), hold 12 bars, 6 bps cost.
- **Reported [LEAKAGE_CHECKLIST]:** direction 51.4%. Vol: the LSTM R² ≈ 0.81 does not beat LGBM's 0.826.
- **Caveat:** the sequence for target i uses rows t−24 … t−1, so the current bar's features are excluded, an extra one-bar lag.

---

## C. `datacollector/` — data plumbing, plus two tests

- **`cvd_backfill.py`** (plumbing): Binance USD-M klines for 10 symbols, 1h/4h, about 730 days. Writes `ts, o, h, l, c, vol, taker_buy` to `cvd_{SYM}_{tf}.parquet`.
- **`rv_backfill.py`** (plumbing): Binance 1-minute klines aggregated to hourly OHLCV plus RV, BV, RQ (= `n/3·Σr⁴`), RSM and n, keeping hours with n ≥ 30, into `rv_{SYM}.parquet`. The cross-hour return is zeroed.
- **`forward_collect.py`** (plumbing, hourly cron): Binance open-interest history (1h), global long/short account ratio, taker buy/sell ratio for 10 symbols, plus Deribit DVOL (BTC/ETH, 1h). Appends to `oi`, `longshort`, `taker_ratio` and `dvol` parquets.
- **`liq_stream.py`** (plumbing): OKX `liquidation-orders` WebSocket for all swaps. Writes `{ts, symbol (instFamily), posSide, side, sz, px = bkPx}` to daily jsonl files.
- **`hawkes_liq.py`** — `liq-imbalance-dir`:
  1. Bin liquidations into 15-minute bars: `long_liq` = USD of posSide=long liquidations (forced selling); `short_liq` likewise.
  2. `imbalance = (short_liq - long_liq) / (short_liq + long_liq)`; `intensity = log1p(total)`.
  3. Trade `sign(imbalance)` at the bar's close, earn the next 15-minute bar's log return, cost 6 bps.
  4. Also tests IC of intensity → next intensity (self-excitation) and intensity → |forward return|.
  - Alert threshold: `IC_dir > 0.03`, more than 3× the shuffle IC, and PnL > 0. Guarded by ≥ 10 days of data.
  - Price comes from Bybit 15m klines, `limit=1000`, so only about 10 days are tested.
  - **Not backtestable historically on OHLC** — it needs a liquidation feed (OKX/Binance forceOrder).
  - Causality looks fine: a bin is keyed by the kline open, and its liquidations are known by that bar's close.
- **`dvol_vol_test.py`** — `dvol-vol-lift`: OLS HAR (log std of 1h returns over 6/24/72) vs HAR plus log DVOL and a 24-hour change in log DVOL; target 24h forward vol; 70/30 split.
  - "Confirmed" if the average R² lift is > 0.02.
  - Needs Deribit DVOL history (it is also available historically from Deribit's API).
- **`dvol_cron.sh`, `hawkes_cron.sh`**: weekly wrappers that write an ALERT file when the test passes.

---

## D. `events.py` — causal event triggers (the only directional lead in the HMM suite)

All arrays align to the log-return index: event t uses close[t+1] of the raw frame and data ≤ that bar. Each detector returns `(mask, direction)`.

### D1. `sweep-fade` — `detect_sweep(df, lookback=24)`
- **Definitions:**
  - `prior_max = rolling max(high, 24).shift(1)`
  - `prior_min = rolling min(low, 24).shift(1)`
  - swept high: `high > prior_max and close < prior_max` → **short**
  - swept low: `low < prior_min and close > prior_min` → **long**
- **Reported [doc HMM §8.13–8.18]** (crypto, high-vol gated, 5-bar hold):
  - hit 0.577 (n = 850, deflated p = 0.027); FX control null
  - net at 10 bps with a 5-bar hold: +6.9 bps pooled, but Sharpe −0.27 and −85% max DD when non-overlapping
- **Best geometry from the docs (§8.16, `scripts/experiment_fade_stop.py`):**
  - entry at the event close; stop **2.5·ATR**; target **4·ATR**; time stop **24 bars**
  - intrabar high/low checks; one fade per cluster (no re-entry while open)
  - gated to the high-vol regime (realised vol in the top tercile; this stands in for the HMM high-vol state)
  - Result: 449 OOS trades, +45.9 bps per trade net of 10 bps, PF 1.33, Sharpe 2.50, max DD −38.6%; FX control −11 bps. This was the best of a 16-cell grid on one 7-month, 19-coin window.
- **But: the freqtrade 3-year OOS** (`trading/user_data/strategies/sweep_fade.py`, 21 pairs, 2022–26, 0.1% per side plus funding, 1% risk at the stop) gave **−97.99%, Sharpe −2.91**. ATR stop-outs (1611 trades, −4.24% average) swamped the targets and time stops.

### D2. `zextreme-fade` — `detect_z_extreme(df, window=24, thr=2.0)`
- **Signal:** `z = (c - SMA24(c)) / std24(c)` (the window includes the current bar). If `|z| > 2`, fade: short when z > 0, long when z < 0.
- **Reported [doc]:**
  - crypto high-vol: hit 0.583 (n = 1358, p = 0.0037); all-vol crypto 0.530
  - cost check at a 5-bar hold: gross +3.3 bps, average win +162 / loss −215, net at 10 bps −6.7 bps; one-per-cluster non-overlap Sharpe 0.75, −38% DD

### D3. `breakout-continuation` — `detect_breakout(df, lookback=48)`
- **Signal:** close > rolling max(close, 48).shift(1) → long; close < rolling min.shift(1) → short.
- **Reported:** negative everywhere [doc §8.13].

### D4. `vol-rollover-fade` — `detect_vol_rollover(df, lookback=12)`
- **Signal:**
  - new high: `c ≥ rolling max(c, 12)` (window includes the current bar); new low likewise
  - `vol_now = mean(volume over the last 3 bars, including current)`
  - `vol_ref = mean(volume over 12).shift(1)`
  - rollover: `vol_now < vol_ref`
  - new high plus rollover → short; new low plus rollover → long
- **Data:** volume.
- **Reported:** "passes" on the FX control too (p = 0.004), so it was **killed** [doc §8.14].

---

## E. `esn_models.py` — Echo State Network direction (plus HMM hybrids)

### E1. `esn-dir` / `esn+regime` / `esn+gated` — `ESNHMMDirection.evaluate`
- **Reservoir** (`ESNReservoir`): N = 300; `W_in ~ U(-0.5, 0.5)`; `W ~ U(-1, 1)` with 10% density, scaled to spectral radius 0.9; bias `~ U(-0.1, 0.1)`. Leaky update: `x = 0.7·x + 0.3·tanh(W_in u + W x + b)`. Deterministic with seed 42.
- **Readout:** ridge, `β = (XᵀX + λI)⁻¹ Xᵀy`, λ = 5 (the ridge default is 1.0 but the class uses 5.0). Target: forward h-bar return.
- **Variants:**
  - `esn+regime`: append the HMM regime belief vector to the inputs.
  - `esn+gated`: a separate readout per HMM regime state (fallback to the global readout if fewer than 50 train or 5 test rows).
- **Evaluation:** a single `train_end` split. Call = sign(pred). Baseline = always the sign of the train mean.
- **Inputs:** `U` (standardised features) is supplied by the caller, i.e. scripts outside my share.
- **Lookahead:** the reservoir is causal. If the caller standardises `U` on the full sample, or passes a full-sample HMM belief/Viterbi state, those leak.
- **Reported [doc §8.12]:** no edge over drift at any horizon or variant; FX controls show larger spurious edges. At events, the naive fade (+1.35 pp) beats the ESN (+0.70 pp).

---

## F. `hmm_models.py` (read fully) — regime models, mostly vol, plus one sizing overlay

### F0. Features
- **`make_features(df, multivariate, standardize=True, vol_window=12)`:**
  - univariate: `[logret]`
  - multivariate: `[logret, log rolling-std(logret, 12, min_periods=2).bfill(), log rolling-mean((h-l)/c, 12).bfill()]`
  - **Lookahead:** z-scored with **full-sample mean/std**, and `.bfill()` back-fills the first row from later data (minor).
- **`make_trend_features(df, fast=12, slow=48)`:** `[rolling-mean logret over 12, rolling-mean over 48]`, with bfill and a full-sample z-score.
- **`make_transition_covariates`:** these are the IOHMM transition inputs:

| Covariate | Definition |
|---|---|
| `vol_of_vol` | `|Δ rv12|` |
| `range_exp` | `((h-l)/c) / rolling-median-50((h-l)/c)` |
| `ret_shock` | `|r|` |
| `hour_sin`, `hour_cos` | time of day |

  All are full-sample z-scored. The function needs a `timestamp` column.

### F1. `ghmm-uni`, `ghmm-multi`, `sticky-hmm` — `fit_gaussian_hmm`
- **Model:** hmmlearn GaussianHMM, k = 3, full covariance, n_iter 100, `min_covar = covars_prior = 1e-2`. The sticky variant uses a Dirichlet `transmat_prior = 1 + κ·I`.
- **Ordering:** states are sorted by the variance of the return dimension, so 0 = low vol and 2 = high vol.
- **Outputs:** the **Viterbi path** (`model.predict`) and **smoothed posteriors** (`predict_proba`), both **fit on and decoded over the whole input**.
- **Lookahead:** this is smoothing / full-sample lookahead unless the caller fits on a past window and decodes causally. The doc says BSBF's causal label agrees with Viterbi 77% of the time, so "Viterbi overstates callability by about 23%".
- **Reported [doc §6.1]** (17 instruments × 5000 1h bars):

| Model | Dwell (bars) | Switch rate |
|---|---|---|
| ghmm_uni | 5 | 0.526 (94–98% on stocks/DXY) |
| sticky | 19 | — |
| bsbf | 22 | — |

  Forward vol differs by regime (Kruskal–Wallis p ≈ 0).
  - Directional "best-regime hit" ≈ 54%, which falls apart in walk-forward; only GS survives [§6.6].
- **Implied use:** a vol-regime filter or position-size scaler; not direction.

### F2. `bsbf` (Bayesian Sticky Belief Filter, causal) — `BayesianStickyBeliefFilter`
- **Emissions:** means come from a sorted GHMM fit; covariances are recomputed from that fit's Viterbi-decoded states.
- **Transitions** (k regimes × dp = 2 duration phases, giving negative-binomial dwell):
  - a non-final phase advances with `p_stay = 0.97`, or self-loops with `1 - p_stay`
  - the final phase returns to phase 0 with 0.97, or leaves to each other regime's phase 0 with `0.03 / (k-1)`
- **Forward filter (each bar):**
  1. `pred = Aᵀ bel`
  2. evidence uses the untempered likelihood; `surprise = -log(evidence)`
  3. the belief update uses the tempered likelihood `L^0.25`
- **Guard:** `surprise_z` = causal rolling z-score (window 100, min periods 25, window includes the current bar). If `z > 2.5`:
  - `λ = clip(0.6·(z - 2.5)/2.5, 0, 0.6)`
  - `bel = (1-λ)·bel + λ·π_stationary`
- **Output:** `map_state = argmax belief`; the filter is causal.
- **Lookahead:** the emission parameters are fit (EM plus Viterbi) on whatever window is passed in. The docs' experiments fit them on the first 50%.

### F3. `factorial-trend-vol` — `FactorialRegimeModel.fit_filter`
- **Construction:** two independent BSBFs:
  - a trend chain on `make_trend_features`, re-sorted by mean so 0 = down, 2 = up; `p_stay = 0.98`
  - a vol chain on the multivariate features; `p_stay = 0.97`
- **Joint state:** `trend·3 + vol`.
- **Implied rule:** long in the up state, short in the down state, perhaps gated by the vol state.
- **Reported [doc §8.5]:** candidate edge −1.05 pp vs drift; controls +6.8 pp (spurious); the down-trend state is followed by +38 bps (mean-reverting). Passes on zero instruments.

### F4. `iohmm` — `InputOutputHMM`
- **Fit:** emissions from the base fit. The static transition matrix is empirical counts (+1 smoothing) on the decoded path. For each source state, a multinomial logistic regression (C = 1) maps `u_t` → `state_{t+1}` (needs ≥ 40 rows).
- **Filter:** causal forward recursion with a per-bar `A_t`.
- **`score_nextstate`:** OOS next-state log-loss vs the static matrix.
- **Use:** predicting regime switches, a vol-timing filter.
- **Lookahead:** the target states come from a Viterbi decode of a full-sample fit.

### F5. `derf` (Doubt-First Evidential Filter, Dempster–Shafer) — `DoubtFirstEvidentialFilter.filter`
- **Initial state:** singleton masses `m` = 0; `m_Θ` = 1.
- **Per bar:**
  1. Predict: `m = Aᵀ m` with sticky A (`p_stay = 0.97`); move `(1 - α)·Σm` to Θ, with α = 0.9.
  2. Evidence: `p` = softmax of the log-likelihoods; `γ = clip(1 - H(p)/log k, 0, 1)`; `e_sing = γ·p`; `e_Θ = 1 - γ`.
  3. Dempster combination over {singletons, Θ}. `K = 1 - total` is the conflict. If `total ≤ 1e-6`, reset to Θ.
  4. Decide: the regime is `argmax m` if `m* ≥ τ = 0.6` and `m_Θ ≤ ι = 0.6`; otherwise −1 (DOUBT).
- **Reported:** doubt concentrates at transitions (lift +0.206, positive on 16/16).

### F6. `fused-regime-sizer` (an exposure overlay, a testable long-only strategy) — `FusedRegimeSizer.exposure`
- **Exposure:**
  - `benign = b_low·1 + b_normal·0.5 + b_high·0`, using BSBF beliefs
  - `E = benign × 1[DERF ≠ DOUBT] × clip(1 - conflict/0.4, 0, 1) × (1 if DERF decision == BSBF argmax else 0.6)`
  - then EMA (span 3), clipped to [0, 1]
- **Trade:** hold long notional `E_t` from close t to close t+1 (the exposure is lagged one bar). Rebalance every bar; costs are not modelled in the code.
- **Reported [doc §8.8]:** emissions fit on the first 50%, OOS second half across 16 instruments:
  - max DD lower on 16/16 (mean −66%)
  - Sharpe better on only 6/16 (mean Δ −0.44)
  - annualised return about −0.25 lower
  - it is a drawdown tool, not alpha
- **Data:** OHLC.

### F7. `gpss` (state-space Gaussian process / Kalman vol filter) — `GPStateSpaceRegimeFilter`
- **Model:** a Kalman filter plus RTS smoother on a 1-D series y (the latent vol level; the caller supplies y, presumably log realised vol), using kickscore kernels (Constant, Wiener, Exponential, Matern32/52, Affine, PiecewiseConstant).
- **Selection:** grid over lengthscales {10, 20, 40, 80, 160}; pick by marginal likelihood; `obs_noise = 0.3`.
- **Outputs:** the filtered mean and std (causal), the smoothed pair (lookahead), `surprise = |v/√S|`.
- **Regime bands:** `np.digitize(mean_f, quantiles(mean_f, [1/3, 2/3]))`.
- **Lookahead:**
  - the regime thresholds are **full-sample quantiles** of the filtered mean
  - the kernel/lengthscale are selected on the full series
  - PiecewiseConstant bounds use the series length
- **Reported:** Matérn-5/2 wins 13 of 16.

---

## G. `monte_carlo.py` — ZMA entries, MC path engines and barrier tools

### G1. `zma-zscore-momentum` (a signal with full trade geometry) — `derive_zma_states(close, z_period=50, vol_period=20, thresh_pct=85, rr=2.0)`
- **Signal at return index t** (t − 1 is the last completed return; entry at `close[t]`):
  1. `z = (ret[t-1] - mean(ret[t-50 .. t-1])) / std(same window)` (the window includes ret[t-1] itself)
  2. Append `|z|` to a history; require at least 50 values.
  3. Threshold = the **85th percentile** of the last 50 `|z|` values (including the current one).
  4. If `|z| ≥ threshold`, enter with **side = sign(z)** (momentum) at the close.
- **Stop and target:**
  - `σ = rolling std(ret, 20)` at t−1 (population std)
  - regime: LOW if σ < 33rd percentile, HIGH if σ ≥ 66th percentile, otherwise MID
  - `k = {LOW: 1.5, MID: 2.0, HIGH: 3.0}`
  - **stop** at a log return of `-side·k·σ` from entry; **TP** at `+side·rr·k·σ` with rr = 2
  - horizon: 48 bars in the docs' experiment (`first_passage`: timeout marked to market at the last bar; a gap-through stop books the actual overshoot)
- **Lookahead:** the **LOW/MID/HIGH cut points are global percentiles over the full series** (the code says so). For a causal backtest, use trailing percentiles.
- **Reported [doc MONTE_CARLO_ZMA §9]** (1h, 2000 paths, 48-bar horizon, TP +2R):

| Instrument | Signals | Realised P(stop) |
|---|---|---|
| SOL | 793 | 0.585 |
| XAU | 791 | 0.583 |
| XAG | 782 | 0.560 |

  The MC-predicted P(stop) passes Kupiec on all three. With P(stop) ≈ 0.56–0.59 at TP = 2R, this is marginal or negative before costs; no EV was reported.
- **Data:** closes only.

### G2. MC path engines (risk tools, not signals; all return a matrix of forward returns, shape `(n_paths, H)`)

| Engine | Definition |
|---|---|
| `block_bootstrap` | random-start circular blocks of 10 |
| `fhs_paths` | GJR-GARCH(1,1)-t (arch, returns × 100, zero mean); bootstrap standardised residuals × the forecast conditional-vol path |
| `fhs_paths(evt=True)` | as above; tails beyond the 95% / 5% residual quantiles drawn from a fitted GPD, only if ξ > 0.03 |
| `student_t_paths` | MLE t, df floored at 2.5 |
| `jump_diffusion_paths` | top 2% |r| = jumps (Gaussian), the rest diffusion, plus a Bernoulli jump arrival; pure Gaussian if excess kurtosis < 1 |
| `variance_gamma_paths` | ν = kurtosis/3, θ = skew·σ/3, moment-matched |
| `regime_switch_paths` | 2 states split at the 75th percentile of |r|; empirical transition matrix; t(4) innovations |
| `hawkes_jump_paths` | jumps beyond the 97th percentile; `λ = λ0 + 0.6·exc`; `exc` decays by e^−1.5 per bar |
| `deriv_boom_crash` | Gaussian body plus a one-sided spike with probability 1/spike_every and size `spike_size·U(0.5, 1.5)` |

### G3. Barrier and exit tools
- **`first_passage`:** ZMA stop/TP first touch; gap-aware R; timeout marked at the last bar.
- **`triple_barrier`:** Lopez de Prado labels on paths. Upper `+pt·σ`, lower `−sl·σ`, oriented by side; vertical barrier V.
- **`branching_tree` + `optimal_exit`:** a scenario tree (branch 8 × depth 4 × 6 bars per stage), solved by backward induction: value = max(exit now, E[children]), cost 5 bps.
  - **Reported [doc §15]:** optimal exit beats fixed-horizon exit by +0.37% (gold), +0.12% (CRASH1000) and +0.64% (R_100).
  - **Bias:** E[continue] is estimated from the same 8 children, so the lift is in-model, and taking the max of noisy estimates makes it optimistic. On driftless iid increments the true lift is about 0.
- **`kupiec_pof`:** a calibration test; plumbing.

---

## H. `trade_calculator.py`, `momentum_scanner.py`, `mc_path_plot.py`

### H1. `mc-trade-ticket` (geometry only; the user supplies direction) — `trade_calculator.trade_ticket`
- **Paths:** pool all engines (G2), 10,000 paths each, H = 24 bars, fit on the last 1200 returns. Hawkes is added for crypto and synthetics.
- **Per path:** `fav = side·(exp(cum) - 1)`; MFE = max fav; MAE = max(−fav).
- **Stop:** distance `stp = quantile(MAE, 0.70)`; stop price `= P·(1 - side·stp)`.
- **Targets:** `td = quantile(MFE, q)` for q = 0.5 (realistic), 0.75 (stretch), 0.9 (runner). `RR = td/stp`, `P(win)` = first touch of target before stop.
- **EV in R:** RR on a win, −1 on a loss, `side·terminal/stp` on neither.
- **Size:** `min(risk$/stop distance, risk$/CVaR5)`, where CVaR5 is the mean of the worst 5% of terminal P&L; default risk 2% of equity.
- **Portfolio mode:** total risk is split into N equal parts. Positions are scaled by `risk_total / joint 5% CVaR` of `H`-bar forward returns (overlapping, full history).
- **Doc framing:** EV ≈ 0 by construction.
- **Lookahead:** in `--live` mode, the Deriv WS `ticks_history end:"latest"` candles include the **current unclosed candle**, and price = `c[-1]`.

### H2. `donchian20-breakout-mc` (a full strategy) — `momentum_scanner.momentum` plus H1
- **Signal:**
  - **long** if `close[-1] > max(high[-21 .. -2])` (the prior 20 bars' highs, excluding the current bar)
  - **short** if `close[-1] < min(low[-21 .. -2])`
- **Geometry:**
  - entry at the close
  - stop = the MC 70th-percentile MAE distance (H1)
  - target = the **stretch** (75th-percentile MFE) target
  - **RR gate:** take the trade only if stretch RR ≥ **1.2**
  - horizon 24 bars (1h data)
  - size = min(stop-based, CVaR-based) at 2% risk
- **Data:** 1h files covering forex_yf, metals_yf, Deriv history and Binance 3-year futures (top 30 symbols), or Deriv live.
- **Reported [doc MC_TRADE_PIPELINE]:** "mild momentum ~+0.14 R on trending assets (crypto/metals); skip forex (reverts)". The RR gate thins trades but does not add EV.
- **Lookahead:** in live mode the last bar may be unclosed. The MC is fit on the trailing 1200 bars, which is fine.

### H3. `mc-ensemble-consensus` — `mc_path_plot.main`
- **Signal:** run the six engines (no Hawkes), 10,000 paths, H = `round(24h / tf)` bars (default tf 4h, so H = 6). Each engine votes the sign of its median terminal return; consensus is UP/DOWN/SPLIT by majority, with an agreement %.
- **Implied rule:** trade the consensus side if agreement ≥ x, hold H.
- **Effectively** a sign-of-trailing-drift (momentum) signal, because driftless engines centre on the historical mean (bootstrap/t/VG use the sample mean μ).
- **Data:** Deriv WS/parquet, or MEXC.
- **Lookahead:** live candles include the forming bar.

---

## I. Metals ML stack — `metals_ml.py`, `metals_dl.py`, `metals_tft.py`

### I1. `metals-causal-features` — `metals_ml.causal_features`
About 30 OHLCV features:

| Group | Features |
|---|---|
| Returns | `ret_k = log c - log c[-k]`, k ∈ {1, 3, 6, 12, 24} |
| Vol | `vol_w = std(r, w)`, w ∈ {12, 24, 48}; `vol_ratio_12_48` |
| Trend | `close_ema20 = c/EMA20 - 1`; `macd = (EMA12 - EMA26)/c`; `macd_sig = EMA9(EMA12 - EMA26)/c` (EMAs `adjust=True` with min_periods) |
| Oscillators | `boll_z = (c - SMA20)/std20`; `rsi_14/100` (Wilder) |
| Range | `atr_pct` (Wilder ATR14 / c); `range_pct = (h-l)/c`; `body_ratio` |
| Position | `rng_pos_n = (c - LL_n)/(HH_n - LL_n)`; `dist_hi_n = (c - HH_n)/c`; `dist_lo_n = (c - LL_n)/c`, n ∈ {24, 48}, high/low windows include the current bar |
| Moments | `skew_48`, `kurt_48`; `ac1_24` (lag-1 autocorrelation of r) |
| Volume | `vol_z` (48-bar z of volume, 0 if constant); `vol_mom = v/mean24(v) - 1` |

`certify_causality` is a truncate-and-recompute check (relative tolerance 1e-3) that drops non-causal columns.

### I2. `funding-features` — `metals_ml.funding_features`
- **Input:** the last published funding rate, forward-filled onto each bar (1h).
- **Features:**

| Feature | Definition |
|---|---|
| `funding`, `funding_abs`, `funding_sign` | the rate, its absolute value and sign |
| `funding_ema_w` | EMA over w ∈ {8, 24, 72} bars |
| `funding_cum_w` | rolling sum over w ∈ {8, 24, 72} |
| `funding_delta_24` | `fr - fr[-24]` |
| `funding_z` | 168-bar z-score |
| `funding_vs_ret` | `sign(fr)·sign(ret24)` |
| `funding_apr` | `fr × 3 × 365` |

- **Reported [doc METALS_ML §3]:** on 60 alts × 3 years, funding adds +0.0024 AUC, i.e. negligible.

### I3. `triple-barrier-meta` — `metals_ml.triple_barrier_labels(pt=2, sl=2, vertical=24, vol_window=24)`
- **Definition:** `σ = std(r, 24).shift(1)`. Entry at close i; upper `+2σ`, lower `−2σ` in cumulative log return; vertical barrier at 24 bars.
- **Label:** +1 / −1 / 0; `meta_up = 1[label == +1]`.
- **Trade:** long when `P(meta_up)` exceeds a threshold, with a symmetric 2σ stop/target and a 24-bar time stop.
- **Reported [doc §2]:** TFT/GBM on 1h XAU/XAG: accuracy 0.46–0.52, net R −0.25 to +0.01, base rate ≈ 0.52, so no edge. The DeepAlpha leaky version had shown 69% / +0.3R from a 4h-feature lookahead.
- **Caveat:** barrier hits are checked on closes only (not intrabar high/low).

### I4. `topbot-reversal` (label and model) — `metals_dl.topbot_labels`, `topbot_labels_causal`, `near_extremum_target`
- **`topbot_labels(level=0.01, window=12)`:** bar i is a top if `close[i] = max(close[i-12 .. i+12])` and `(close[i] - min(segment))/close[i] ≥ 1%`. A bottom is symmetric. This is a **centered window**, so it is lookahead by design — a label only.
- **`topbot_labels_causal`:** the same test, confirmed at bar `j + window` (12 bars late). It is safe to use as a feature.
- **`near_extremum_target(horizon=12)`:** y = 1 if a (centered) top occurs in `i+1 .. i+12`. The label's effective look-forward is therefore `horizon + window` = 24 bars, so purging must embargo at least 24.
- **Models:** `LSTMClf` (2×64 + LayerNorm head), `CNNClf` (dilated 1D, dilations 1/2/4), `TransformerClf` (d = 64, 4 heads, 2 layers, sinusoidal positions), `TFTLite` (I5). All are sequence → logit.
- **Implied trade:** short when P(top) > a threshold; long when P(bottom) > a threshold; exit on a vol-scaled triple barrier.
- **Reported [doc METALS_ML §5–7]:**
  - sealed-holdout reversal AUC 0.59–0.70 (gold 5m 0.70), against direction AUC 0.52–0.56
  - across 120 instruments: mean AUC 0.595, 76% above 0.55; crypto 0.632
  - **tradeable test:** 3337 trades, mean R **−0.196**, PF 0.65, 47% win — **worse than the random-entry control** (−0.167)
  - meta-labelling, rolling retraining and cross-sectional variants all failed
  - LightGBM beat the deep nets

### I5. `tft-lite` — `metals_tft.TFTLite`
- **Architecture:** variable-selection network (per-feature Linear(1, d) embeddings plus a softmax weight from a GRN), LSTM, GLU gate plus LayerNorm, causal-masked multi-head attention (4 heads), GRN, MLP head on the last step, d = 48. Classifies `meta_up` with a 48-bar window.
- **Validation:** 4-fold expanding walk-forward with an embargo.
- **Results:** see I3.

---

## J. Pure plumbing (one line each)
- `nn/dataset.py`: `iid_df`, `garch_df`, `assemble`, `walk_forward` — synthetic controls and the pooling/split helpers.
- `nn/vol_export.py` → `vol_coefs.json` — the exported ridge vol model (coefficients in B25).
- `nn/vol_forecaster*.py`: `load`, `forecast_vol*` — pickle loaders and inference.
- `nn/*:train_mlp`, `met`, `rankic`, `r2`, `qlike` — training and metric helpers.
- `datacollector/*`: backfills, the forward collector, the liquidation streamer and cron wrappers (Section C).
- `monte_carlo.py`: `_rolling_std`, `_fit_gjr_t`, `_make_resid_sampler`, `risk_metrics`, `triple_barrier_metrics`, `kupiec_pof`.
- `trade_calculator.py`: `deriv_sym`, `_ws_candles`, `fetch_live`, `_load`, `print_ticket`, `atr_of` (Wilder-style ATR14).
- `mc_path_plot.py`: `_ws_closes`, `fetch_mexc`, `get_closes`, and the plotting.
- `momentum_scanner.crypto_watchlist` — the first 30 Binance 3-year feather symbols.
- `hmm_models.py`: `HMMFit`/`*Result` dataclasses, `_score_aic_bic`, `_sorted_by_return_variance`, `_gauss_logemission`, `_kalman_filter_smoother`, `_rolling_z`.
- `esn_models.py`: `ESNReservoir`, `ridge_fit`, `ridge_predict`.
- `metals_ml.certify_causality` and `build_dataset` — causality audit and assembly.
- The notebooks' MEXC futures symbol lister and multi-symbol OHLCV fetcher (ccxt, 743 symbols) — data fetch only.

---

## K. Ideas that cannot be backtested on OHLC alone
- **Need exchange-specific historical data** (feasible but not plain OHLC):
  - Funding-rate models B4 and I2 — funding history.
  - CVD/OFI models B5, B20 and B21 — taker-buy volume per kline. Binance has it; Deriv, FX and indices do not.
  - DVOL lift (Deribit implied-vol index).
  - Open interest, long/short account ratio and taker ratio (`forward_collect`) — Binance only keeps about 30 days of these; the collector was built to accumulate them going forward.
- **Need liquidation event streams:** `hawkes_liq` (OKX/Binance forceOrder; no deep history), and `liq_stream`.
- **Need 1-minute data:** realised-variance vol models B16, B23 and B27. Usable as features but expensive; Deriv 1m candles exist.
- **Need a local LLM embedding server:** text-embedding features B19 and B24.
- **Need production MongoDB features:** the README 7-factor sweep-side score (pool asymmetry, fatigue, OFI, fill probability, order blocks, HTF trend, range position) has no code in my share.
- **Synthetic-only (not tradeable):** `deriv_boom_crash` and the other MC engines generate paths; they are not signals.

---

## L. Lookahead / validity summary (ranked by severity)
1. **The notebooks:** random split, full-series MinMax scaler, price-level target. The results are fake (as documented).
2. **`hmm_side.py`:** Viterbi over the full series, deliberately.
3. **`hmm_models.fit_gaussian_hmm`:** Viterbi plus smoothed posteriors over the whole input; full-sample z-scoring in `make_features`, `make_trend_features` and `make_transition_covariates`; `.bfill()` on rolling windows. GPSS regime bands use full-sample quantiles and full-series kernel selection. BSBF, DERF, IOHMM and the fused sizer inherit emission parameters from whatever window is fit. The filters themselves are causal.
4. **`monte_carlo.derive_zma_states`:** LOW/MID/HIGH vol terciles are global (full-sample) percentiles, so the stop multiplier k carries lookahead.
5. **Pooled row-fraction splits:** `regime_side`, `when_bigmove`, `indicator_test`, `geom_vol`, `text_embed_vol`, `cosine_*`, `vol_bygroup` concatenate symbols and cut at 70% of rows. The test set is the last symbols, not the last time period, so train and test overlap in calendar time across correlated assets. The cosine "reference" set is other symbols' forward labels covering the same calendar time.
6. **No embargo** in the per-series 70/30 splits of `vol_forecaster*`, `return_horizon`, `lstm_*`, `crypto_*_vol`, `tda_vol` and `semivar_harq`. Up to 168 overlapping label bars at the boundary.
7. **Centered top/bottom labels** (`metals_dl.topbot_labels`, `near_extremum_target`): fine as targets only; embargo ≥ horizon + window. Never use them as features — use `topbot_labels_causal`.
8. **Unclosed bars:** the live Deriv WS candles in `trade_calculator`, `momentum_scanner` and `mc_path_plot` include the forming bar.
9. **`optimal_exit` lift:** in-model, and optimistic because the children used to estimate E[continue] are the same paths it is scored on.
10. **Cost model:** costs are a flat 6 bps (sometimes 10) in return space everywhere. There is no bid/ask, and no spread differences for FX, Deriv or indices. `cross_sectional.py` charges gross exposure on overlapping windows; `ofi_1to5m` flips every bar.
11. **Clean by construction** (verified):
    - `nn/dataset.build` features, `walk_forward` with an H embargo, train-only scaling (vol_model, dir_model, entry_model, funding_dir, cvd_dir)
    - `events.py` detectors (shift(1) on prior extremes)
    - `metals_ml.causal_features` and `triple_barrier_labels` (σ shifted by 1)
    - `momentum_scanner.momentum` (prior 20 bars exclude the current one)
    - `xs_reversal` (non-overlapping rebalances, turnover cost)


---

# Appendix B: range_strat part B

# Catalogue of the SMC/structure, patterns, momentum, stat-arb, carry, RL and microstructure files in `range_strat`

**Folder:** the source. I read all 49 files in full. Results come from `docs/range_regime_design.md` §35–§84; the section number is given with each item.

**Helper code I read:**
- `lab/nimble/nimble/features.py`, imported as `NF`.
- `lab/nimble/nimble/rl.py`, imported as `RL`.
- The scripts import these from (lab path), which does not exist on this machine. The box copy may differ from the local copy.
- `adaptive_range.backtest` is in the other agent's share. I note only the parameters these files call it with.

**Not documented:** the RL files (`fx_carry_v3`, `fx_unified_rl`, `fx_unified_rl_v2`, `fx_portfolio_multi`, `synth_portfolio_rl`, `synth_portfolio_multi`, `regime_switch_rl`) have no results anywhere in the docs.

---

## 0. Shared conventions (many items refer back here)

**Data**
- **Bars:** almost every intraday script reads `/tmp/{NAME}_pre1m.csv` plus `/tmp/{NAME}_1m.csv`.
  - These are 1m OHLC(V) files with unix-second `timestamp`; they look like Dukascopy data.
  - They are resampled with pandas to 1h, 4h or 1D: `first/max/min/last`, plus a volume sum where it is used, then `dropna`.
  - Bins are UTC-anchored and the `timestamp` is the bar OPEN time.
- **11-instrument real universe (`UNIV`, `SP.UNIV`):** EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, XAUUSD, SPX500, NAS100, DAX, WTI, COPPER.
- **RB200:** `/tmp/RB200_1m.csv` in `bulkowski.py`. `level_odds.load("RB200")` instead pulls the last 5000 1h candles over the Deriv WebSocket.
- **Crypto via `level_odds.load`:** `~/dqlab/lab/data/binance_3y/{SYM}-1h-futures.feather`, 12 perps listed in `LO.CRYPTO`.
  - Its `timestamp` is degenerate: `.view(int64)//1e9` on a datetime column collapses to about 1640-scale values (§71 found this).
  - So in `gate.py`, the crypto OOS split and fold edges run on a coarse, nearly tied clock.

**COSTBP (bp of price, charged per side)**

| EURUSD | GBPUSD | USDJPY | AUDUSD | USDCAD | XAUUSD | SPX500 | NAS100 | DAX | WTI | COPPER | BTC | RB200 (bulkowski) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.5 | 0.6 | 0.5 | 0.6 | 0.7 | 1.0 | 1.0 | 1.0 | 1.5 | 2.0 | 2.0 | 5.0 | 2.0 |

- Trade-based scripts subtract `2*COSTBP/1e4` per trade.
- Portfolio scripts charge `COSTBP/1e4 * |Δposition|`.
- There is no bid/ask series anywhere; every price is a mid/bid close.

**ATR (unless stated):** `ATR48 = SMA_48(TR)` with `min_periods=1`, where TR = max(h−l, |h−pc|, |l−pc|).

**`SP.bt` — the fixed-R exit engine (`smc_parts.bt`).** Used by smc_parts, structural_decomp, bulkowski, bulkowski_chart, harmonics, winners_abcd and turn_points.
- **Entry:** close of the signal bar i, with `s = sig[i] ∈ {±1}`.
- **Stop and target:** SL = entry − s·1·ATR48, TP = entry + s·1.5·ATR48, both on the ENTRY timeframe (1h). The docstring says "ATR4", but the code uses the 1h ATR.
- **Exit scan:** from bar i+1. If both levels fall inside the same bar, the STOP is taken first (conservative).
- **No max hold.** A trade still open at the end of data is DROPPED (a small survivorship effect).
- **One position at a time.** After an exit at bar j, the next possible entry is bar j+1.
- **Return** = s·(exit−entry)/entry − 2·COSTBP.
- **Persistent signals:** level-type signals that stay on bar after bar are re-entered on the first eligible bar after each exit.

**Harness metrics**
- PF and win%; exp = mean bp per trade.
- "OOS" = the last 40% of pooled trades by timestamp. Nothing is refit on it; it is a time-split readout.
- "folds" = 5 equal-count time folds, counting those with mean > 0.

---

## A. SMC / market-structure family

### A1. Primitives (not strategies, but needed to rebuild every A-item)

**`smc_setup.swings(close, k=2)`** — close-based ("line chart") pivots.
- Bar i is a high pivot if `close[i] == max(close[i-k..i+k])` and `close[i] > close[i-1]`. Lows mirror this.
- Each pivot is recorded as `(confirm_idx = i+k, price, ±1, i)` and is only used from bar i+k onward. That is causal.

**`structure_engine._pivots(src, k)`** — the same rule but with `>=` / `<=` against the previous bar. It returns `(confirm_idx = i+k, actual_idx = i, price, type)`.

**`smc_setup.structure(df4, k=2, eq_thr=0.5)`** — per-4h-bar state.
- `bias = +1` if the last two confirmed swing highs AND the last two swing lows are both rising (HH+HL); −1 if both are falling; otherwise 0.
- `eqh`: if the last two swing highs are within `eq_thr·ATR48(4h)`, use the higher of them; otherwise use the last swing high. `eql` mirrors this with the lower of the lows.
- So the "liquidity pool" is often just the most recent swing.

**`smc_setup.fvgs(df, fvg_thr=0.25)`** — latest unfilled FVG per side.
- Bull FVG at i: `l[i] > h[i-2]` and the gap `l[i] − h[i-2] > 0.25·ATR48`. The zone is [h[i-2], l[i]].
- Bear FVG mirrors it: `h[i] < l[i-2]`, zone [h[i], l[i-2]].
- Only the most recent FVG per side is kept.
- A bull FVG is invalidated when `l < zone_low`; a bear FVG when `h > zone_high`.
- Known at the close of the third bar.

**`smc_setup.confirm(df)`** — confirmation candle.
- Bull: an engulfing bar (`c>o`, previous bar down, `c ≥ prev open`, `o ≤ prev close`), OR a hammer (`lower wick ≥ 1.5·body` and `c>o`).
- Bear mirrors it: engulfing, OR `upper wick ≥ 1.5·body` and `c<o`.

**`structure_engine.analyze(df, k=5, eq_thr=0.4)`** — one causal pass that outputs `trend, bos, choch, sw_hi, sw_lo, eqh, eql, prem` and the bull/bear order-block top and bottom.
- **Swing ingestion:** swings are taken at their confirm index (k bars late). The standing swing high `sh` and swing low `sl` are marked "unused" when they arrive.
- **BOS / CHoCH:** when `close > sh` (unused), it is a BOS +1 if the current trend is ≥ 0, otherwise a CHoCH +1. Then trend = +1 and `sh` is marked used. Lows mirror this with `close < sl`.
  - The event is stamped on the break bar, on a CLOSE break.
- **Bull order block:** on the break bar, walk back from i toward the swing-high's actual index and take the last DOWN candle (c<o). The zone is [min(o,c), max(o,c)].
  - If no down candle is found, the code uses the candle at `sh_i` if that candle is down; otherwise it falls back to (top = o[i], bottom = l[i]) of the break bar.
  - Note the search window runs from the swing high to the break, not from the swing low (LuxAlgo searches from the low).
- **Bear order block:** mirrors the bull case (last UP candle back to `sl_i`) with no fallback.
- **OB invalidation:** a bull OB dies when `close < OB_bottom`; a bear OB when `close > OB_top`.
- **EQH / EQL:** as in `structure()`, with eq_thr = 0.4·ATR48.
- **Premium/discount:** `prem = (c − sl)/(sh − sl)` using the latest confirmed swing levels, used or not. It can fall outside [0, 1].
- **Trend** starts at 0. Downstream, `tup = trend ≥ 0` and `tdn = trend ≤ 0`, so trend 0 allows both sides.

**MTF merge (smc_run, smc_run2, smc_parts, structural_decomp)**
- The 4h state is stamped at its CLOSE (`timestamp + 4h`) and joined to 1h bars with `merge_asof(backward)` on the 1h OPEN time.
- So a 1h bar opening at T sees only 4h bars that closed at or before T, and the trade enters at that 1h bar's close. Causal.

### A2. `smc_v1_sweep_fvg_bias` — `smc_run.backtest(name, k=2, eq_thr=0.5, fvg_thr=0.25, sweepM=8, min_rr=1.5, require_fvg=True, require_sweep=True)`
**Setup (1h execution, 4h structure from `smc_setup.structure`)**
- **LONG** needs all of:
  - 4h bias ≥ 0;
  - eql and eqh both exist;
  - **sweep:** `min(low[i-8..i]) < eql` and `close[i] > eql`;
  - **in-FVG:** a bull FVG exists, `low[i] ≤ fvg_hi` and `close[i] ≥ fvg_lo`;
  - a bull confirm candle on bar i.
- **Geometry:**
  - entry = close[i];
  - SL = min(low[i-8..i]) − 0.1·ATR48(4h);
  - TP = eqh;
  - require TP > entry > SL and RR = (TP−entry)/(entry−SL) ≥ 1.5.
- **SHORT** mirrors it (bias ≤ 0, sweep of eqh, bear FVG, bear confirm). It is only checked if the long did not qualify.
- **Exit and cost:** first touch of SL or TP, SL checked first in the same bar, no max hold, dropped if unresolved, one trade at a time, cost 2×COSTBP.

**Lookahead:** none found. Pivots are confirmed k bars late and the 4h state comes from completed bars.

**Results**
- §40, 6 hand-picked instruments: PF 1.07, 62% win, +1.4 bp, n=287; OOS train +1.4 / test +1.5. No-FVG −2.3, no-sweep 0.0.
- §43, all 11 instruments (`smc_multifold.py`, same function, multi-fold): PF 0.88, 63% win, **−3.3 bp**, n=542, 2/5 folds positive.
  - Every config was negative: no-FVG −4.5, rr2.0 −5.6, no-sweep ≈0.
  - Verdict: the earlier result was subset luck.

### A3. `smc_v2_engine_ob_pd` — `smc_run2.backtest(name, k=5, fvg_thr=0.25, sweepM=8, min_rr=1.5, use_ob, use_sweep, use_fvg, use_pd)`
**Setup (4h structure from `structure_engine.analyze` with k=5, eq 0.4)**
- **LONG** needs all of:
  - 4h trend ≥ 0;
  - premium/discount `prem ≤ 0.55`;
  - a trigger: either the sweep (as in v1, against eql) OR an OB tap (`low ≤ OB_bull_top` and `close ≥ OB_bull_bot`);
  - the in-FVG condition (1h FVG, as in v1);
  - a bull confirm candle.
- **Geometry:**
  - entry = close;
  - base = min(min low over 9 bars, OB bottom);
  - SL = base − 0.05·(eqh − eql);
  - TP = eqh;
  - RR ≥ 1.5.
- **SHORT** mirrors it with `prem ≥ 0.45`.
- **Exit:** same as A2.

**Results (§41):** in-sample +15.5 bp (train +30.2) but OOS test **−5.6 bp**, n=78. Only no-FVG is high-n (n=902), and it is −2.7. Verdict: overfit.

### A4. SMC parts (each traded alone with the `SP.bt` fixed 1.5R exit) — `smc_parts.signals(name, k=5, fvg_thr=0.25, sweepM=8)`
All parts are on the 1h bar and use the 4h `analyze` state. No confirmation candle is required.

| id | Long condition (short mirrors) | Notes |
|---|---|---|
| `smc_part_fvg` | trend ≥ 0, a bull 1h FVG exists, low ≤ fvg_hi and close ≥ fvg_lo | persistent |
| `smc_part_sweep` | trend ≥ 0, min(low over 9 bars) < eql and close > eql | |
| `smc_part_ob` | trend ≥ 0, low ≤ OB_bull_top and close ≥ OB_bull_bot | |
| `smc_part_bos` | first 1h bar on which the merged 4h `bos` changes to a non-zero value; direction = sign | fires roughly once per 4h BOS. Two consecutive same-sign 4h BOS bars do NOT re-trigger. |
| `smc_part_choch` | same, for `choch` (a reversal) | |
| `smc_part_premdisc` | prem < 0.3 → long; prem > 0.7 → short (no trend filter) | persistent |

**2-part combos:** both parts fire the same sign on the same bar (an AND). Pairs tested: FVG+SWEEP, FVG+OB, FVG+CHoCH, SWEEP+OB, CHoCH+FVG, BOS+FVG.

**Results (§44)**

| part | pooled | OOS |
|---|---|---|
| FVG | −2.1 bp (n≈21,945) | −2.2 |
| SWEEP | −1.8 | −2.4 |
| OB | −2.6 | −2.3 |
| CHoCH | −1.1 | −2.0 |
| PremDisc | −2.2 (n≈53k) | −2.7 |
| **BOS** | **+0.5** | **+1.2** |

Combos: BOS+FVG +2.0 (best), FVG+OB +0.9, the rest negative.

### A5. Unified decomposition — `structural_decomp.build(name, k_ext=5, k_int=2, fvg_thr=0.25, disp_k=1.5)`, all exits via `SP.bt`
**Parts re-used from A4:** external (4h) `BOS`, `CHoCH`, `FVG`, `SWEEP`, `OB`, `PremDisc`. The sweep window is fixed at 9 bars.

**New parts**
- **`BOS_int`:** the BOS transition from `analyze(df1h, k=2)`, i.e. internal 1h structure.
- **`ict_ote`:** uses the internal (1h, k=2) state. Let leg = sw_hi − sw_lo (the latest confirmed swing high minus the latest confirmed swing low; there is no ordering check that they form one leg).
  - Long if internal trend ≥ 0, leg > 0, `low ≤ sw_hi − 0.62·leg` and `close ≥ sw_hi − 0.79·leg`.
  - Short if internal trend ≤ 0, `high ≥ sw_lo + 0.62·leg` and `close ≤ sw_lo + 0.79·leg`.
- **`ict_displacement`:** `(h−l) > 1.5·ATR48(1h)`, direction of the candle body.
- **`crt_sweep_reverse`:** long if `low < PL` and `close > PL`; short if `high > PH` and `close < PH`.
  - PH/PL are the high/low of the 4h bar BEFORE the last completed one (`shift(1)` plus the +4h close stamp gives one extra candle of lag). Not lookahead, just stale.

**Combos**
- Internal ANDs: BOS+DISPLACE, BOS+OTE, BOS+FVG, DISPLACE+FVG, BOS_int+DISPLACE, OTE+FVG, CRT+FVG.
- **Nested gate:** take an internal signal (BOS_int, DISPLACE, OTE, FVG or CRT) only if it agrees with `edir` = the forward-fill of the last external BOS transition sign.
- `gate()` in the file is a no-op stub.

**Results (§46)**
- Parts alone: only BOS is positive (+0.5, OOS +1.2). BOS_int −2.3, OTE −2.7, DISPLACE −2.1, CRT −2.1.
- **BOS+OTE +6.6 bp, OOS +7.0 (n=76 OOS, n=190 total)**; BOS+FVG +2.0 / OOS +1.3 (n=410). The nested gate is negative everywhere.
- §47: the honest implementation is in `nested_hook_bos.py`, which is not in my list. Its rules: 4h BOS → wait for the 1h pullback → confirmation candle → impulse-scaled SL/TP. It gave **−7.4 bp, 1/5 folds** (adaptive version −8.0). §47 concludes BOS+OTE was a same-bar coincidence artifact.

### A6. `sr_fvg_fade` — `sr_fvg.backtest(name, k=3, fvg_win=4, tol=0.3, buf=0.3, tf="1h", require_fvg=True, fvg_entry=False)`
**Levels**
- Close pivots with k=3, confirmed at i+3.
- A swing LOW becomes a support if a bull FVG appears in bars [actual_idx, actual_idx+4]. Here the FVG test is simply `l[i] > h[i-2]` with gap > 0.2·ATR48.
- A swing HIGH becomes a resistance if a bear FVG appears in the same window.
- Levels are never removed (the lists only grow).

**Entry (signal bar i)**
- R = nearest resistance above close; Su = nearest support below. Both must exist.
- **Short:** `high ≥ R − 0.3·ATR`, `close < R`, and a bear confirm candle. SL = R + 0.3·ATR, TP = Su.
- **Long** mirrors it.
- `fvg_entry=True` also requires an FVG of the trade's side within bars i−2..i. This is the "FVG+S/R confluence" variant in §50.
- **Exit:** first touch, SL first, no max hold, 2×cost, one trade at a time (`pos_until`).

**Lookahead:** the FVG validation window runs 4 bars past the pivot while confirmation is only 3 bars late. That is **1 bar of lookahead in level validation** at the defaults; there is none with k=5.

**Results**
- §48: PF 0.44, **−4.6 bp, n=67,197**, OOS −4.9, 0/5 folds. No validation −5.5; 4h −6.1.
- §50 (fvg_entry): PF 0.42, −4.7 bp, n=12,193; 4h −7.3.

### A7. `sr_fvg_breakout` — `sr_fvg_break.backtest(name, k=3, fvg_win=4, margin=0.1, buf=0.3, rr=2.0, tf, require_fvg, require_mom)`
- **Levels:** the same validated S/R as A6, with the same 1-bar lookahead.
- **Long break:** some resistance r satisfies `c[i-1] ≤ r < c[i] − 0.1·ATR`, AND the bar is a momentum candle `(c−o) > 0.3·ATR`.
  - Uses lvl = the highest such r. Entry = close, SL = lvl − 0.3·ATR, TP = entry + 2·(entry − SL).
  - The broken level is consumed.
- **Short** mirrors it.
- **Results (§49):** PF 0.87, **−2.3 bp, n=18,355**, OOS −1.8, 0/5 folds, every config negative.

### A8. `volume_profile_fade` — `vol_sr.run_profile(name, tol=0.3, buf=0.3)` (needs bar volume; for FX this is Dukascopy tick volume)
**Profile (`profile_levels`, W=120, nb=30, va=0.70)**
- Over bars [i−120, i−1], split [min low, max high] into 30 bins.
- Each bar's volume is spread uniformly across the bins its BODY spans.
- POC = midpoint of the heaviest bin.
- The value area is built by adding bins in descending volume until 70% of the total. These bins need not be contiguous. VAH/VAL = the max/min bin midpoint included.
- The result is then `np.roll`'d by one more bar, so the profile is lagged by two bars.

**Entry**
- **Short:** `high ≥ VAH − 0.3·ATR`, `close < VAH`, and a bear confirm candle. SL = VAH + 0.3·ATR, TP = POC.
- **Long** mirrors it at VAL.
- **Exit:** first touch, SL first, 2×cost, one trade at a time.
- The "wick-liquidity sweep" (B) described in the docstring is NOT implemented.

**Results (§51):** PF 0.84, **−2.7 bp, n=8,670**, OOS −2.0, 0/5 folds.

### A9. Level-hold probability — `level_odds.analyze(df, brk=0.5, bounce=1.0)`
This is a research measurement rather than a P&L backtest. The implied trade is a fade at clustered levels.

**Levels**
- Close pivots with k=3, confirmed within the last 200 bars.
- 1-D single-linkage clustering: sort the pivot prices and merge neighbours within 0.25·ATR48 (SMA TR, min 10).
- Keep clusters with at least 2 touches; level = cluster mean. Re-cluster every 24 bars.

**Event**
- A fresh approach: `|c−lvl|/ATR < 0.25` and the previous bar's distance was ≥ 0.25.
- Per-level cooldown of 48 bars.
- The level is a resistance if mean(c[i−5:i]) < lvl.

**Outcome (close-based, within 48 bars)**
- BREAK: close beyond the level by brk·ATR(i).
- HOLD: close back by bounce·ATR in the fade direction.
- RANGE: neither.
- EV (ATR units, pre-cost) = P(hold)·bounce − P(break)·(brk + 0.15).
- A volatility flag records whether any bar range exceeded 2·ATR in the window. The efficiency ratio ER(20) splits trend from range.

**Results (§68)**
- Crypto (n=30k): P(hold) 0.419, P(break) 0.580, EV +0.042 ATR.
- RB200: hold 0.46, EV +0.109.
- Touch-count strength does not help.
- Tighter stops (brk 0.1–0.2) raise EV in ATR units (crypto +0.135; RB200 peak +0.264 at brk 0.2 / bounce 1.5), but all pre-cost.

### A10. FVG-continuation confluence — `level_confluence.analyze(df)`
Uses 1h data from `LO.load` (crypto) or RB200.

**FVG detection**
- Bull FVG if `l[i] > h[i-2]`, with NO size threshold.
- impulse = (c[i] − c[i-2])/ATR; strong if > 1.5.
- BOS flag: `c[i] > max(h[i-20 .. i-3])`.
- An FVG stays active for 200 bars. "fresh" = re-entered within 48 bars.

**Event and simulation**
- The event is the first bar after creation whose low is ≤ zone top (bull).
- `patt` = the re-entry bar closes in the FVG direction.
- Entry = close of that bar.
- Continuation sim: TP = entry + 1·ATR, SL = zone_low − 0.4·ATR, result in R (+1 or −risk/ATR).
- A reversal-null sim takes the opposite bet against the same zone.
- Same-bar ambiguity goes to TP first (optimistic). Trades unresolved after 200 bars are DROPPED.
- No cost.

**Results (§69):** continuation edge over the null is +0.01 to +0.03 ATR (geometry-thin); the "+pattern" condition gives −0.056 R. On RB200 the null is positive and continuation loses.

### A11. Density / pairing — `level_density.py` and `level_density2.py`
**v1 (A10 run on synthetic ratio OHLC)**
- Constructions: alt_OHLC / BTC_close, and alt / an equal-weight alt-index level `exp(mean(log c − log c0))`.
- Invalid by construction: the denominator moves inject fake FVGs, and the degenerate-timestamp join exploded n (§70, §71).

**v2 (`level_density2.analyze`)**
- Same FVG and event rules on the RAW alt.
- Outcome = d·(12-bar forward alt return) and d·(alt − BTC 12-bar return); no stop, no cost, in-sample.
- Results (§71): base +3.7 bp edge over the beta-neutral baseline; with impulse and BOS +7.9 (n=11k).
- §72 then showed it disappears with a stop and costs.

### A12. THE GATE — `gate.analyze(df, cost_bp)`: FVG continuation with dynamic SL/TP and cost
- **Detection and event:** the same as A10.
- **Geometry:** entry = re-entry bar close; TP = entry + d·1.0·ATR48; SL = zone far edge ∓ 0.4·ATR.
  - The trade is skipped if entry is already beyond SL.
- **Exit scan** over 200 bars:
  - **TP is checked BEFORE SL** in the same bar, which is optimistic.
  - On timeout the trade is marked to market at c[i+200].
- **No position limit:** overlapping trades from several FVGs are allowed.
- **Cost:** one charge, treated as round-trip: crypto 7 bp, EURUSD 1.5, GBPUSD 1.8, USDJPY 1.5, XAU 2.5, RB 7, BOOM/CRASH 10.
- **Subset:** "impulse + BOS + fresh" (impulse > 1.5).

**Results (§72)**

| group | base | confluence |
|---|---|---|
| CRYPTO | −4.2 bp, 0/5 | −2.5, 2/5 |
| FX | −1.2 | −2.2 |
| GOLD | −0.3 | −4.8 (OOS −18) |
| SYNTH (RB200) | −7.4 | −7.8 |

All negative, and this is even with the TP-first optimism.

---

## B. Candlestick, chart and harmonic patterns

All B-items run on 1h bars (`bulkowski.load`, TFMIN=60) and exit via `SP.bt` (1·ATR stop, 1.5·ATR target, SL first, 2×cost). The universe is the 11 real instruments plus RB200.

### B1. Bulkowski candlesticks — `bulkowski.patterns(df)` (35 signals)
**Notation**
- up = c>o, dn = c<o; body = |c−o|; rng = h−l; uw/lw = upper/lower wick; mid = (o+c)/2.
- ab = SMA20(body) (min 5) on the current bar.
- sma = SMA50(close) (min 10); tup = c > sma, tdn = c < sma.
- Sk(x) = the value k bars back.
- doji: body < 0.1·rng. small: body < 0.3·rng.
- The signal fires on the last bar of the pattern; entry at that bar's close.

| pattern | condition | trade sign |
|---|---|---|
| 3WhiteSoldiers | up, S1 up, S2 up, c > S1c > S2c, uw < body | +1 |
| 3BlackCrows | mirror, lw < body | −1 |
| MorningStar | S2 body > ab, S2 dn, S1 body < 0.5·S2 body, up, c > S2 mid | +1 |
| EveningStar | S2 body > ab, S2 up, S1 body < 0.5·S2 body, dn, c < S2 mid | −1 |
| BullEngulf | up, S1 dn, c ≥ S1o, o ≤ S1c | +1 |
| BearEngulf | mirror | −1 |
| BullHarami | S1 dn, S1 body > ab, up, h ≤ S1o, l ≥ S1c | +1 |
| BearHarami | S1 up, S1 body > ab, dn, h ≤ S1c, l ≥ S1o | −1 |
| Piercing | tdn, S1 dn, S1 body > ab, up, o < S1l, S1mid < c < S1o | +1 |
| DarkCloud | tup, S1 up, S1 body > ab, dn, o > S1h, S1o < c < S1mid | −1 |
| Hammer | tdn, lw ≥ 2·body, uw < body, small | +1 |
| HangingMan | the same shape in tup | −1 |
| InvHammer | tdn, uw ≥ 2·body, lw < body, small | +1 |
| ShootingStar | the same shape in tup | −1 |
| DragonflyDoji | doji, lw ≥ 2·uw, uw < 0.1·rng | +1 |
| GravestoneDoji | doji, uw ≥ 2·lw, lw < 0.1·rng | −1 |
| TweezerBottom | tdn, \|l − S1l\| < 0.05·ab, S1 dn, up | +1 |
| TweezerTop | tup, \|h − S1h\| < 0.05·ab, S1 up, dn | −1 |
| BeltHoldBull | tdn, up, o == l, body > ab, lw < 0.02·rng | +1 |
| BeltHoldBear | tup, dn, o == h, body > ab, uw < 0.02·rng | −1 |
| 3InsideUp | S2 dn, S2 body > ab, S1 up, S1h ≤ S2o, up, c > S2o | +1 |
| 3InsideDown | mirror | −1 |
| 3OutsideUp | S2 dn, S1 up, S1o ≤ S2c, S1c ≥ S2o, up, c > S1c | +1 |
| 3OutsideDown | mirror | −1 |
| UpTasukiGap | tup, S2 up, S1 up, S1o > S2c, dn, S1o < o < S1c, c > S2c | +1 |
| DownTasukiGap | mirror | −1 |
| WhiteMarubozu | up, body > 0.95·rng | +1 |
| BlackMarubozu | dn, body > 0.95·rng | −1 |
| TwoBlackGapping | tdn, S1 dn, dn, S1h < S2l | −1 |
| TwoWhiteGapping | tup, S1 up, up, S1l > S2h | +1 |
| SeparatingBull | `& 0`, so disabled (never fires) | — |
| MatchingLow | tdn, dn, S1 dn, \|c − S1c\| < 0.05·ab | **−1** (contrarian, as Bulkowski measured) |
| MatchingHigh | tup, up, S1 up, \|c − S1c\| < 0.05·ab | **+1** |
| HomingPigeon | tdn, S1 dn, S1 body > ab, dn, inside S1 body | +1 |
| KickBull | S1 dn, up, o > S1o, body > 0.8·rng, S1 body > 0.8·S1 rng | +1 |
| KickBear | mirror | −1 |
| 3LineStrikeBull | 3 down closes, then an up bar with c > S3o | **−1** |
| 3LineStrikeBear | mirror | **+1** |

The signs on the last two rows are swapped relative to the names, which is intentional per Bulkowski's measured behaviour.

**Ranking (`eval_group`):** patterns are ranked by OOS bp; a "<<" flag marks OOS > 0 with at least 3/5 folds. Picking the best of 35 × 2 groups carries selection bias.

**Results (§57)**
- Real markets: TwoWhiteGapping OOS +12.8 (3/5, n=252); BeltHoldBull +2.0 (4/5, n=1,547); DarkCloud +4.8 (n=88). All reversal patterns negative.
- RB200: EveningStar +12.4 (PF 2.6, 73% win, 4/5, n=26); 3OutsideDown +7.4 (n=63).

### B2. Pattern winner re-tests — `winners_abcd.py`
**`twg` variants**
- `notrend`: drops the tup filter.
- `strict`: requires `S1l > 1.001·S2h`.
- Note the variant in this file omits the `tup` filter only when `notrend=True`. It uses the sma/tup definition from B1 otherwise.

**`es` variants:** star body < 0.3 × first body; `needgap` requires S1o > S2c.

**Results (§58)**
- TwoWhiteGapping folds [−8 −7 +1 +14 +11]: recent-only, fragile.
- EveningStar on RB200: +9.2 bp, 4/5 folds; the body<0.3 variant +8.9, 4/5; n=26.

### B3. ABCD — `winners_abcd.abcd_signals(df, k=3, ratio_tol=0.30, bc_min=0.38, bc_max=0.90)`
- Uses the last 4 close pivots (k=3), in the order the pivots were produced. They do NOT have to alternate globally; the type sequence is checked explicitly.
- **Bullish:** A high, B low, C high, D low, with:
  - AB = A−B, CD = C−D, BC = C−B;
  - |CD−AB|/AB < 0.30;
  - 0.38 < BC/AB < 0.90;
  - C < A and D < B.
- **Signal:** BUY on D's confirmation bar (D's actual bar + 3); entry at that close. Bearish mirrors it.
- **Results (§58):** real markets −0.8 bp, 2/5, n=2,688; negative at tolerances 0.15 and 0.5 too. Too few on RB200.

### B4. Harmonics — `harmonics.harmonic_signals(df, k=3)`
- **Pivots:** the last 5 close pivots (k=3) must have types (−1,+1,−1,+1,−1) for bullish (X low, A high, B low, C high, D low), or the mirror for bearish.
- **Ratios:**
  - XA = A − X;
  - AB_r = (A−B)/XA;
  - retD = (A−D)/XA.
  - C is NOT used, and neither are BC or CD.

| pattern | AB band | retD band |
|---|---|---|
| Gartley | 0.55–0.68 | 0.70–0.90 |
| Bat | 0.35–0.55 | 0.82–0.95 |
| Butterfly | 0.70–0.90 | 1.15–1.70 |
| Crab | 0.35–0.68 | 1.50–1.90 |
| Cypher (proxy) | 0.35–0.65 | 0.70–0.90 |

- Gartley and Cypher bands overlap. "ANY-harmonic" = the sign of the sum across patterns.
- **Signal:** reversal at D, entry at the close of D's confirmation bar (D + 3).
- **Results (§60):** Gartley +0.0 (OOS +2.4, 3/5, n=290); Cypher +0.5 (OOS +5.7, 2/5, n=606); Butterfly −1.4; Crab −0.5; Bat −5.7. Too few on RB200.

### B5. Chart patterns — `bulkowski_chart.chart_signals(df, k=3, eq=0.004)`
**Inputs:** close pivots (k=3), confirmed only. h1, h2 = the last two swing highs; l1, l2 = the last two swing lows.
- eqh = |h1−h2|/h1 < 0.4%; eql likewise for the lows.

**Signals.** Each fires on EVERY bar while its condition holds (not just at the cross), so `SP.bt` re-enters after each exit.

| pattern | condition |
|---|---|
| DoubleTop | eqh and close < min(l1, l2) → short |
| DoubleBot | eql and close > max(h1, h2) → long |
| AscTri | eqh, l2 > l1, close > max(h1, h2) → long |
| DescTri | eql, h2 < h1, close < min(l1, l2) → short |
| Rect | eqh and eql → break either side |
| HSTop | last 3 highs with H2 the highest, \|H1−H3\|/H1 < 0.8%, close < min(l1, l2) → short |
| HSBot | mirror → long |

The necklines are the last two lows/highs, not strictly the intervening ones.

**Results (§59):** all negative on real markets (−1.0 to −2.8 bp, 0/5 folds). RB200 DoubleTop is flat (+0.2, OOS +2.6).

---

## C. Turn-point / top-bottom family

### C1. Statistical-extreme fades — `turn_points.signals(df)` (1h, `SP.bt` exit)
**Indicators**
- z = (c − EMA50)/rolling std50 (min 20).
- RSI: Wilder-style, `ewm(alpha=1/14)`.
- Bollinger: EMA50 ± 2·std50.
- ATR48.

**Signals** (all persistent while true)

| id | rule |
|---|---|
| `z>2`, `z>2.5`, `z>3` | z above threshold → short; below −threshold → long |
| `z>3+candle` | as `z>3`, plus a candle against the extension |
| `RSI30/70`, `RSI20/80` | fade the RSI extreme |
| `Boll2` | high ≥ upper band → short; low ≤ lower band → long |
| `Climax2.5` | (h−l) > 2.5·ATR → fade the candle direction |
| `z>2.5+climax` | z > 2.5, (h−l) > 1.5·ATR, and a bear candle → short; mirror for long |

**Results (§62):** all negative on real markets, and worse when more extreme (RSI −2.2, Boll −2.7, z>2 −3.4, z>3 −5.9 with n=3,063). RB200 also negative (z>2 −4.0, z>2.5 −8.6).

### C2. ML top/bottom detector — `topbot_ml.build(df, K, mode)` and `fit_eval`
**Clean features (10):** z, RSI, (c−EMA50)/ATR, ret5, ret10, ret20, rvol20, Donchian position over 20 bars, vel = Δc/ATR, acc = Δvel.
- The "leaky twin" adds the forward K-bar return.

**Labels**
- bottom: low[i] is the minimum of the window; top: high[i] is the maximum.
- Windows: `sym` = [i−K, i+K]; `fwd` = [i, i+K]; `past` = [i−K, i].

**Model:** sklearn HistGradientBoosting (150 iterations, depth 3, lr 0.06, l2 = 1.0). Trained on the first 60% of bars, tested on the rest.

**Trade:** go long where p_bot > the q-quantile and short where p_top > the q-quantile, hold K bars close-to-close, no cost.

**Configs:** (6, sym), (6, fwd), (6, past), (3, fwd), (12, fwd), (24, fwd), all at q = 0.90; plus (12, fwd) at 0.97. Instruments: RB200, EURUSD, SPX500, XAUUSD.

**Lookahead**
- The signal threshold is the quantile of the TEST-set predictions (an in-sample threshold).
- No purge/embargo: labels near the cut use bars past it.
- `sym`/`past` labels are backward-determined. That is the point of the diagnostic.

**Results (§65):** clean AUC with fwd labels is 0.58–0.70; the leaky twin gets 0.87–0.89; OOS fade PnL ≈ 0 for every config.

### C3. Ride the detected turn — `topbot_trade.collect(insts, K, minmove)`
- **Model:** as C2 with fwd labels. With minmove > 0, a bottom label additionally requires max(c[i..i+K]) − c[i] > minmove·ATR (tops mirror this).
- **Configs:** (K=12, mm=0) and (K=24, mm=1.0).
- **Measurement:** forward return at H ∈ {3, 6, 12, 24, 48} on 1h bars, at top-decile predicted bottoms and tops, versus the unconditional drift over the test bars.
- **Universe:** EURUSD, SPX500, XAUUSD, GBPUSD, WTI, plus RB200.
- **Result (§66):** the raw ride gave +5 bp at 48 bars, but the EXCESS over drift is about 0 to −1.6 bp. It was all drift.

### C4. Turn detector as an exit on momentum — `momentum_turn_exit.py` (daily bars from 1m, 12 instruments including BTC)
- **Base position:** sign(pct_change(60)) · clip(0.008/rv20, 0, 3), applied the next day (`shift(1)`).
- **Turn exit:** with C2 models (K=10, fwd labels), zero a long when p_top > the q-quantile of test predictions, and zero a short when p_bot > the q-quantile.
- **Control:** random exits at the same rate (averaged over 5 seeds).
- **Portfolio:** equal-mean across assets, NO cost, evaluated on the last 40% of dates.
- **Lookahead:** the same test-quantile threshold and missing embargo as C2.
- **Results (§67)**

| q | turn-exit Sharpe | random Sharpe | turn beat random |
|---|---|---|---|
| 0.80 | 0.38 | 0.21 | 1/4 folds |
| 0.85 | 0.28 | 0.21 | 1/4 |
| 0.90 | 0.11 | 0.18 | 1/4 |

- Baseline Sharpe ≈ 0.08. Verdict: the gain is generic de-risking.

---

## D. Momentum family (daily unless stated)

### D1. `tsmom_v1` — `tsmom.tsmom(px, L)`
- **Data:** daily last close from 1m, 11 instruments plus BTC (`/tmp/BTCUSDT_mc_1m.csv` and `BTCUSDT_1m.csv`).
- **Signal and size:** pos = sign(P/P.shift(L) − 1) / (std(r, 60)·√252), clipped to ±3, applied next day (`shift(1)`). This targets roughly 100% annualised vol per instrument in raw units.
- **Return:** ret = pos·r − 1 bp·|Δpos|; equal-weight mean across instruments. Base L = 120; sweep L ∈ {20, 60, 120, 250}.
- **Results (§35):** portfolio Sharpe 0.66, 4/5 folds; L20 0.90, L60 0.84, L120 0.66, L250 0.84; ex-commodity 0.67.

### D2. `tsmom_v2_ts`, `xsmom_v2`, `mom_combined` — `tsmom_v2.py` (the deployed momentum core)
**Inputs:** P = daily closes on a union date grid, forward-filled up to 3 days; R = pct change; vol_i = R.ewm(span=60).std(); N = number of instruments; LSET = {20, 60, 120, 250}.

**TSMOM leg**
- mom = mean over LSET of sign(P/P.shift(L) − 1), so mom ∈ {−1, −0.5, 0, 0.5, 1}.
- ts_pos = mom · 0.10/(vol_i·√252·√N), applied next day, clipped to ±3.

**XSMOM leg**
- momc = mean over LSET of (P/P.shift(L) − 1).
- z = momc − its cross-sectional mean; w = z/Σ|z| (dollar-neutral).
- xs_pos = w · 0.10/(vol_i·√252) · √N, applied next day, clipped to ±3.

**Portfolio vol-target (`target_vol`)**
- net0 = Σ pos·R − Σ|Δpos|·COSTBP/1e4.
- scale = 0.10/(net0.ewm(60).std()·√252), shifted one day, clipped to [0, 4].
- net = net0·scale.
- Caveat: the cost is computed on the UNSCALED positions, and changes in scale are never costed, so cost is understated when scale > 1.

**COMBINED:** the mean of the TS and XS net series, re-vol-targeted the same way. It is dumped to `/tmp/mom_daily.csv`.

**Results (§36)**

| sleeve | Sharpe | maxDD | positive years | annRet | other |
|---|---|---|---|---|---|
| TSMOM | 0.64 | −15% | 75% | | gross 0.70; avg turnover 0.27 |
| XSMOM | 0.31 | | | | |
| COMBINED | **0.74** | −13% | 88% | 7.9% | 5/5 folds |

### D3. Volume-confirmed TSMOM — `tsmom_vol.py`
- **Base:** the D2 TSMOM position. Volume = the daily sum of 1m volume (tick volume for FX).
- **Variants** (every gate is lagged one day):

| variant | rule |
|---|---|
| `filter` | base · 1[V > SMA60(V)] |
| `weight` | base · clip(V/SMA60(V), 0.3, 3), then clipped to ±4 |
| `obv-align` | base · 1[obv_mom == mom], where obv = cumsum(sign(R)·V) and obv_mom = sign(obv − obv.shift(120)) |
| `voltrend` | base · 1[SMA20(V) > SMA60(V)] |

- Subtlety in `obv-align`: mom is the blended mean of signs, so equality with ±1 holds only when ALL 4 lookbacks agree AND OBV agrees.
- **Results (§52):** base 0.64; **obv-align 0.71 (5/5 folds)**; filter 0.54; weight 0.50; voltrend 0.24.
  - An un-shifted version gave 3.70; that was lookahead, caught and fixed.

### D4. Momentum estimators — `mom_estimators.estimators(x, L)` (x = log close)
| estimator | formula |
|---|---|
| RET | sign(x_t − x_{t−L}) |
| SLOPE | sign of the OLS slope over x[t−L : t] (excludes bar t) |
| TSMOM | clip(ret/(std_L(r)·√L), ±3) |
| ATTN ("ZMA core") | sign(Σ softmax(\|r\|)·r over r[t−L : t]) |

- **ATTN observation:** the softmax is applied to raw |r| values of about 0.01–0.05, so the weights are nearly uniform. ATTN is therefore approximately the sign of the mean return, i.e. RET lagged one bar.
- **Book:** position = sig.shift(1)·ret − 7 bp·|Δsig|, mean across coins.
- **Data:** ccxt binanceusdm, last 1,500 bars for 10 coins (BTC, ETH, SOL, BNB, XRP, ADA, DOGE, LINK, AVAX, LTC). TFs 4h and 1d; L ∈ {10, 20, 40}.
- **Results (§74, re-verified §83):**
  - 4h: all negative (−0.9 to −4).
  - 1d RET L=40: Sharpe 0.54, OOS 0.81 (0.74 after the fix), 4/5 folds.
  - ATTN L=20: 0.35. TSMOM L=20: 0.40. SLOPE L=40: 0.23.

### D5. Stock momentum — `stock_mom.py`
- **Data:** Dukascopy stock CFD files at `~/dqlab/lab/data/{us|forex_nasdaq|forex_nyse|uk|germany|france|japan|switzerland|africa}_*_1h.parquet`, resampled to daily.
- **Costs:** US 3 bp; Europe/Japan 5 bp; Africa 15 bp.
- **Signals and book:** D4's estimators and book, with L ∈ {10, 20, 40, 60}.
- **Lookahead:** the "best L" is chosen by OOS Sharpe, which is selection on the test set.
- **Results**
  - §78–80 numbers are void: they came from a position-alignment bug.
  - §83 (fixed): US RET daily −0.24; all estimators negative.

### D6. Combined estimators — `combo_mom.py` (US/UK/FR/JP, L=10)
| combo | rule |
|---|---|
| RET | the RET sign |
| ATTN | the ATTN sign |
| AGREE | (RET + ATTN)/2 ∈ {−1, 0, 1} |
| OR | +1 if either is long, else −1 |
| AVG | clip((TSMOM + ATTN)/2, ±1) |

- **Results:** §80 (pre-fix) had AGREE as the best OOS at 0.40. After the §83 fix, all are negative.

### D7. Cross-sectional US equity momentum — `xs_stock.py`
- **Panel:** log daily prices for about 270 US names; keep days where at least 50% of names are present.
- **Weights:** mom = 10-day log return; w = (mom − cross-sectional mean)/Σ|·|, applied next day.
- **P&L:** Σ w·R − 3 bp·turnover.
- **Result (§81):** Sharpe −0.59, versus +0.57 for equal-weight long beta.

### D8. Direction decomposition — `decomp_stock.py` (L=10)
- **TS book:** equal weight across active positions: (Σ w·R)/Σ|w| − cost·turnover/Σ|w|.
- **Variants:** both sides, longs only, shorts only, all-long (beta); XS neutral, XS long leg only, XS short leg only.
- **Results (§82):** TS both −0.37; longs only 0.11; shorts only −0.71; beta +0.57; XS −0.59; XS legs −0.52 / −0.86.

### D9. Live momentum paper — `momentum_paper.py`
- **Signal:** the same as D2, with target = 0.5·TS + 0.5·XS on the last row.
- **Data:** Dukascopy daily BID closes, last 430 days, 11 instruments.
- **Process:** mark yesterday's positions to today, rebalance, cost = Σ|Δpos|·COSTBP. State is kept in `~/paper/mom_state.json` and the ledger in `~/paper/mom_ledger.csv`.
- **Status (§39, §56):** started 2026-07; no results yet.

---

## E. Stat-arb and lead-lag

### E1. Macro pairs stat-arb — `stat_arb.trade_pair(A, B, ...)`
- **Data:** the 12 instruments at 1D and 1h, forward-filled up to 2 bars, all pairs.
- **Spread:** on PRICE LEVELS (not logs). β = cov(A, B)/var(B) on the first 60%; require β > 0. spread = A − βB.
- **Half-life:** fit Δs = φ·s_{t−1}; hl = −ln2/ln(1+φ). Require 2 ≤ hl ≤ 120 bars.
- **z-score:** using the train mean and sd.
- **Trading (OOS only):**
  - enter short spread at z > 2, long at z < −2;
  - exit when |z| < 0.5;
  - no stop.
- **P&L:** pnl_t = pos_{t−1}·Δspread/(|A| + β|B|)_{t−1} − |Δpos|·(COST_a + β·COST_b)/(1+β).
- **Results (§63):** daily pooled OOS Sharpe −0.95, 8/33 pairs positive. Hourly: no pairs passed the filter.

### E2. Crypto pairs and residual reversal — `crypto_statarb.py`
- **Data:** up to 90 Binance perps, daily from `binance_3y` 1h feather files.
- **Pair filter:** train daily-return correlation > 0.55, measured on the first 60% of the panel.
- **Pair rules:** log prices; β ∈ (0.2, 5); half-life 3–90 days; same z rules as E1.
- **P&L:** pnl = pos_{t−1}·(dlogA − β·dlogB)/(1+β) − |Δpos|·10 bp.
- **Lookahead:** each pair's own cut is at 60% of its history, which can differ from the panel cut used for the correlation filter. A mild leak.
- **Residual reversal:**
  - resid = R − cross-sectional mean of R; m = rolling L-day sum of resid;
  - w = −(m − mean)/Σ|·|, applied next day;
  - P&L = Σ w·R − 10 bp·turnover; OOS = last 40%.
- **Results (§64):** pairs pooled OOS Sharpe −0.53, 46% of pairs positive, 1/5 folds. Residual reversal L = 1/3/5/10: −1.62 / −0.81 / −0.97 / −0.44.

### E3. Lead-lag — `lead_lag.run(tf, lag=1)`
- **Fit (train, first 60%):** LL[A, B] = corr(R_A lagged by one bar, R_B).
- **Trade (test):** pos_B = sign(Σ_A LL[A, B]·R_A(t−1)) over leaders with |LL| > 0.02.
- **P&L:** Σ pos·R − |Δpos|·COSTBP.
- **Data:** hourly and daily, 12 instruments.
- **Lookahead/realism:** forward-filling across non-synchronous closes (SPX/DAX closed hours, BTC 24/7, UTC-day bins) creates stale-price "lead" artifacts.
- **Results (§61):** hourly −4.85 bp/bar (Sharpe −7.7); daily −5.56 bp/bar.

---

## F. Carry, book construction and execution

### F1. Kalman funding carry, basis-aware — `combine_book.carry_daily(explicit=True)`
**Data:** up to 60 coins from binance_3y:
- `*-1h-funding_rate.feather`: column `open` = funding rate, sampled at 00/08/16 UTC;
- `*-1h-futures.feather`: perp close;
- `*-1h-mark.feather`: mark close (used as the spot proxy), forward-filled onto the funding grid.

**Kalman filter (causal local-level):** q = 0.02, r = 1.0, P0 = 1. Effectively an EWMA with steady-state gain ≈ 0.13.

**Signal and P&L**
- sig = sign(Kalman-filtered funding); position s = sig shifted one funding period.
- Per 8h: pnl = s·(F + mark_ret − perp_ret) − 15 bp·1[sig flip]. The position is long spot / short perp when funding is positive.
- Equal-weight mean across coins, then summed to daily.
- The funding-only variant: s·F − 10 bp·flip.
- A flip is also charged on the first row (NaN comparison).

**Results (§37–38)**
- Funding-only: Sharpe 13.4.
- Explicit basis: **8.75**, annRet 5.1%, maxDD −1.2%.
- §45: skew +1.64, but described as structurally short basis-vol (a peso problem).

### F2. Book combinations — `combine_book.py` main
- Each sleeve is vol-targeted: scale = 0.10/(ewm60 std·√252), shifted one day, clipped to [0, 6].
- **Books:**
  - equal-vol;
  - risk-parity, with inverse FULL-SAMPLE std weights (mild lookahead);
  - **65/35 momentum/carry**.
- **Results (§38):** corr(MOM, CARRY) = +0.03. 65/35 Sharpe 2.19, annRet 23.2%, maxDD −11.3%. Risk-parity Sharpe 6.39 with maxDD −20.9%.
- The tail report computes skew, CVaR5%, tail ratio and the longest losing run.

### F3. Paper book — `book_paper.py`
- Reads the momentum, carry and RB200 ledgers.
- Each leg is scaled to 10% vol using its full-sample std. The book is an equal-risk mean, or 65/35 per the docstring.
- §56: the early forward Sharpes are seed-window, not results.

### F4. FX carry basket with RL risk-off timer — `fx_carry_v3.py` (28 FX pairs, 15m Dukascopy files `/tmp/{s}_du15.csv`, plus VIX and DXY)
**Basket**
- Rates are a STATIC snapshot (USD 4.5, EUR 2.5, GBP 3.5, JPY −0.1, AUD 3.2, CAD 3.5, CHF 1.0, NZD 4.0) applied over the whole history. That is anachronistic.
- Carry per bar = (r_base − r_quote)/100/(96·252).
- Long the top-6 pairs by carry, short the bottom-6, static.
- basket_t = mean over longs of (fwd_ret + carry) minus mean over shorts of (fwd_ret + carry).

**RL controller**
- Actions: exposure ∈ {0, 0.5, 1}; cost = mean half-spread × |Δexposure|.
- Features:
  - VIX/SMA500 − 1; VIX 20-bar % change; DXY 20-bar log change;
  - basket rolling std over 96 bars; basket drawdown versus its 480-bar max;
  - cross-pair dispersion; London (7–16 UTC) and NY (12–21 UTC) session flags.
- Algorithm: Double-DQN, 60/15/25 split.

**LOOKAHEAD (serious):** `rets` are next-bar returns (`shift(-1)`). As a result:
- `disp` = cross-sectional std of NEXT-bar returns;
- `bvol` and `bdd` include the next basket return.
The state therefore peeks at the reward. **No documented results.**

### F5. SAGE execution layer — `sage_exec.py`
**Kelly sizing**
- Binary: f = clip(0.25·(p(b+1) − 1)/b, 0, 0.02).
- Continuous: f = min(0.25·Sharpe·0.10, 0.02).
- Drawdown soft cap: size ramps linearly to 0 between 5% and 15% drawdown.

**Risk rails:** hard stop at 15% drawdown; daily-loss cap 2%; portfolio cap; category cap. Sizing is against available capital, not gross.

**Order placement (`place`)**
- Skip if the edge does not clear (taker 5 bp / maker 0 bp) + 2 bp safety.
- For a buy: if ask ≤ reference price, cross as taker; otherwise post a maker bid at min(ref, bid). Sells mirror this.

**Signal adapters**
- **`rb200_fade_adapter`** — a 1h RB200 boundary fade:
  - range = high/low of the last 48 1h bars; mid = their midpoint;
  - if close ≥ hi − 0.15·range: short at reference hi, TP = mid, SL = 0.20·range beyond the boundary (long mirrors this at lo);
  - assumed p = 0.46 and spread ±5 bp.
  - This is a simpler stand-in for the deployed RB200 fade.
- **`crypto_mom_adapter`:** sign(c_t/c_{t−480} − 1) on 1h data (20 days) for BTC/ETH/SOL, with Sharpe hard-coded at 0.74.
- **`carry_signals`:** hard-coded dummy values.

**Status (§73):** dry run only.

### F6. Carry ledger sync — `sync_carry.py`
- Plumbing. It SSHes using .pem keys under `.secrets` (I did not read them).
- It parses `MARK equity=$X` log lines into daily returns and copies them to the box over scp.

---

## G. RL models (nimble `RL`) — none have documented results

**Common training scheme (`RL.train_rl`)**
- Split 60/15/25 train/val/OOS by time; features z-scored with TRAIN mean and sd.
- Double-DQN: MLP with dropout, γ = 0.95, ε-greedy decaying to 0.05, buffer 50k, batch 256, target sync every 500 steps, Huber loss, Adam lr 1e-3, weight decay 1e-5, rewards ×1000.
- Early stopping on the validation Sharpe of the greedy policy.
- State = features plus the previous action. Reward = stream[i, a] − cost.
  - Cost is 1[a ≠ prev] × cost, or the per-action spread for close + open, or cost·|Δpos| when action_pos is given.
- Greedy evaluation starts from "the last action is flat". That convention is wrong for the files where stream 0 is flat.
- OOS Sharpe is computed on the reward, so it includes any risk penalty.

**Portfolio A2C (`RL.train_portfolio`)**
- Each asset gets its own categorical action over {−1, 0, +1} (factored policy).
- Reward = mean_i(w_i·r_i) − cost·mean|Δw| − λ·mean(|w|·vol_i).
- vol_i = rolling-20 std of the forward returns themselves (a small lookahead in the penalty).
- Whole-trajectory REINFORCE with a value baseline and entropy bonus 0.01.

**NF features used (period 48)**
| feature | definition |
|---|---|
| er | \|c_t − c_{t−48}\| / Σ\|Δc\| over 48 bars |
| rvol | std of the last 20 log returns |
| pos_in_range | (c − min low over 48)/(max high over 48 − min low over 48) |
| cos_trend | Σr/(√48·‖r‖) over 48 log returns |
| liq_coil | log1p(Σ\|Δc\| over 12 / \|c_t − c_{t−12}\|) |
| rsi | SMA-14 RSI |
| hurst | R/S over 64 bars |
| fractal_align | mean of sign(Δlog p) over 5, 16 and 48 bars |

All causal. `NF.build` drops a row if any of about 50 features is NaN.

| id | file | universe | actions | reward | notes |
|---|---|---|---|---|---|
| `fx_unified_rl_v1` | fx_unified_rl | 9 traded (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, XAU, XAG, COPPER) + context DXY, BRENT, SP500, VIX; 15m | flat or (asset, long/short): 19 actions | ±next-bar log return − 0.3·rolling-20 std; switch cost 2e-4 | **LOOKAHEAD:** `ctx_basket`, `ctx_dxy`, `ctx_disp` are built from forward returns |
| `fx_unified_rl_v2` | fx_unified_rl_v2 | 28 pairs + 4 context series; 15m | flat or (pair, long/short): 57 actions | ±(fwd return + static carry) − 0.2·vol | per-pair half-spread on close + open; time features sin/cos hour, day-of-week, sessions |
| `fx_portfolio_multi` | fx_portfolio_multi | 28 pairs | {−1, 0, 1} per pair | A2C: fwd return + carry; cost 4e-4; λ = 0.15 | |
| `synth_portfolio_rl` | synth_portfolio_rl | 13 Deriv synthetics: RB200, RB100, R_25/50/75/100, stpRNG, BOOM/CRASH 500/1000, JD50/100; `/tmp/{s}_15m.csv` | pick which synthetic's fade to run, or flat | MTM of `adaptive_range.backtest(form=96, de_max=0.15, mode="fade", sl_mult=0.20, fade_tp_frac=0.75, arm_frac=0.15, min_range_pct=0.0005, maker, taker 5 bp, slip 2 bp)` | **NOT implementable:** each trade's FINAL net return is spread evenly over its holding bars, so the stream depends on the trade's future outcome, and "joining" mid-trade is credited the original entry. Only the always-RB200 baseline is meaningful. |
| `synth_portfolio_multi` | synth_portfolio_multi | same | {−1, 0, 1} per synthetic | A2C; cost 2e-4; λ = 0.05 | same MTM reward flaw |
| `regime_switch_rl` | regime_switch_rl | one `/tmp/{STEM}.csv` (default BTC_15m) | momentum / mean-reversion / flat | mom = sign(c − c_{t−48})·next return; rev = −sign(c − SMA48)·next return | switch cost 3e-4 per action change. Features: er, hurst, liq_coil, rvol, pos_in_range, cos_trend, fractal_align. Rule baseline `er_gate_rule` = mom if ER(48) ≥ 0.30 else rev. **The baselines are reported WITHOUT cost.** |

---

## H. Microstructure, flow and volatility

### H1. Follow the liquidation spike — `liq_edge.py`
- **Data:** Binance forceOrder stream at `~/liqdata/liq_*.jsonl` (ts, symbol, side, p, v), about 90k events over 33 days; top 6 symbols; 15m klines via ccxt.
- **Aggregation:** sell_usd and buy_usd per 15m bar. "Sell" = a long liquidated.
- **Spike:** the bar's value ≥ the 90th percentile of the nonzero bars. This uses the FULL-SAMPLE quantile (lookahead in the threshold).
- **Trade:** after a sell spike, go SHORT; after a buy spike, go LONG. Hold H ∈ {1, 2, 4, 8} bars close-to-close.
- **Cost:** 2×7 bp or 2×15 bp.
- **Results (§76):** gross +0.8 to +15.5 bp; net at 7 bp only H=8 is positive (+1.5); net at 15 bp everything is negative; 0–3/5 folds.

### H2. Slow liquidation-imbalance feature — `slow_feat.py`
- **Features:** mom24 = 24h return; netliq24 = 24h sum of (buy − sell) liquidation USD. Both z-scored per symbol over the full sample.
- **Target:** forward 24h return on 1h bars, overlapping windows.
- **Measurement:** IC only.
- **Results (§77):** IC(mom) +0.036; IC(netliq) +0.024; correlation between them −0.69; combined IC +0.076. About 33 independent days, so statistically noise.

### H3. VRP regime — `vrp_regime.py`
- **Data:** Deribit DVOL at `~/datacollector/data/dvol.parquet`; Binance 1h klines for BTC and ETH.
- **Variables:** RV = std of the last 24 hourly returns, annualised ×100; VRP = DVOL − RV.
- **Measurement:** IC against the forward 24h return, plus terciles cut on the full sample.
- **Results (§75):** IC(DVOL) +0.049; IC(VRP) +0.005; terciles non-monotonic. About 40 days of data.

---

## Pure plumbing (one line each)

- `smc_run/smc_run2/smc_parts.load`, `bulkowski.load`, `vol_sr.load1h`, `gate.load`, `level_odds.load/resample`: 1m CSV, feather or Deriv WebSocket → OHLC resample.
- `smc_multifold.py`: multi-fold and config driver over `smc_run.backtest`.
- `pf`, `desc`, `de`, `d`, `multifold`, `mf`, `eval_group`, `report`, `rep`, `summarize`, `metrics`, `stats`, `st`, `sharpe`, `tail_report`: metric helpers.
- `structure_engine.__main__`: sanity print of the engine.
- `momentum_paper.py`, `book_paper.py`, `sync_carry.py`: paper-ledger state, sync and combination.
- `sage_exec.apply_rails/place/size_and_place`: execution and risk wrapper, no alpha.
- `RL.TradingEnv`, `train_rl`, `train_portfolio`, `export_numpy`: training infrastructure.
- `level_density.make_ratio`/`series`/`to_df`, `level_density2.load_pair`: series construction.

## Ideas not backtestable on OHLC / exchange bars alone

- `liq_edge`, `slow_feat`: need the Binance liquidation stream. Only 33 days were collected, and there is no history API.
- `vrp_regime`: needs Deribit DVOL history.
- `combine_book` carry: needs perp funding history and mark/index prices; spot-borrow and basis-capacity effects are not modelled.
- `fx_carry_v3`, `fx_unified_rl_v2`, `fx_portfolio_multi` carry: need a time-varying short-rate/swap history (the code uses a static snapshot), and the first two need VIX/DXY series.
- `sage_exec.place`: needs a live bid/ask and fill model.
- `synth_portfolio_*`: their reward stream cannot be realised as trades; only the underlying `adaptive_range` fade can be backtested.
- `momentum_paper`/`book_paper`: forward-only.
- `vol_sr`: needs real volume. FX and CFD volume here is Dukascopy tick volume, which is a weak proxy.
- `stock_mom`, `xs_stock`, `decomp_stock`, `combo_mom`: need the Dukascopy stock-CFD parquet universe (the files are on the box only).

## Main lookahead and realism flags

1. **`fx_carry_v3`** state features (`disp`, `bvol`, `bdd`) and **`fx_unified_rl`** context features (`ctx_basket`, `ctx_dxy`, `ctx_disp`) are built from `shift(-1)` forward returns. That is direct lookahead.
2. **`synth_portfolio_rl/multi`:** the MTM-spread reward depends on each trade's future outcome and cannot be traded.
3. **`sr_fvg` / `sr_fvg_break`:** 1-bar lookahead in FVG validation (window +4 bars versus k=3 confirmation).
4. **`gate.py` and `level_confluence`:** TP is checked before SL in the same bar (optimistic). `level_confluence` also drops trades unresolved after 200 bars, and `gate` allows overlapping positions.
5. **Test-set thresholds:** `topbot_ml/trade` and `momentum_turn_exit` set thresholds as quantiles of test predictions and have no purge/embargo. `liq_edge` uses a full-sample spike quantile.
6. **`stock_mom`** picks the best L by OOS Sharpe. The pre-§83 stock results were inflated by the position-alignment bug.
7. **`tsmom_v2` / `tsmom_vol`:** portfolio vol scaling is applied after costs are computed, so scale changes are uncosted.
8. **Full-sample normalisation:** `combine_book` risk-parity and `book_paper` vol-matching use full-sample std. `slow_feat` uses full-sample z-scores.
9. **`lead_lag`:** forward-filling across asynchronous markets creates spurious lead.
10. **`level_odds.load` timestamps are degenerate (§71).** This affects the crypto time split in `gate.py` and is the reason for `level_density`'s join explosion.
11. **No lookahead found in** structure_engine, smc_run, smc_run2, smc_parts, structural_decomp, bulkowski*, harmonics, ABCD, turn_points, tsmom*, mom_estimators, stat_arb, combine_book Kalman (it is a filter). These all use pivots confirmed k bars late, 4h state stamped at bar close, and entry at the signal-bar close.
12. **No bid/ask anywhere.** All costs are flat bp per side or per unit of turnover.
