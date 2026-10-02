# Catalogue of trading ideas in `the source`

**Scope.** I covered the whole project: README.md, `api/`, `channels/` and the five-line pytest-cache README. Nothing was modified, and no secret or `.env` value was read.

**Paths.** All paths are relative to the source unless written otherwise. Line numbers follow the file name (for example `ame.py:2632`).

**How this was built.** Eight parallel read-only sub-reads, each covering one module group in full, merged here. Where a primitive is used by several modules it is defined once and cross-referenced.

---

## 0. Findings that change any backtest (read first)

### 0.1 Data and timing as the live system sees it

1. **The analyzer works on a 300-bar window.** Data comes from the Redis candle cache (`get_candles(limit=300)`). Fewer than 50 bars means the symbol is skipped.
2. **The Mongo fallback returns the oldest bars, not the newest.**
   - `analyzer._get_market_data_df` and the AME, usd_confluence, commodity_confluence and resampler readers do `.sort("timestamp",1).limit(N)`.
   - That returns the **oldest** N rows still kept under the per-timeframe TTL. Retention in days: 15m 14, 1h 30, 4h 120, 1d 800.
   - So `usd_confluence` and `commodity_confluence` always run on bars that are about 12, 23, 92 or 630 days old (15m, 1h, 4h, 1d).
3. **The last bar is usually still forming.** No code checks that it is closed.
   - TradingView rewrites the last 200 bars every 300 s, CCXT the last 3 bars every 60 s, and FastBull every 600 s.
   - Deriv WebSocket bars are written only when they close, but its backfill and stale-poll paths include the current candle.
   - **In a backtest, evaluate on closed bars and enter at the next open.**
4. **The `resampler.py` virtual timeframes are unusable.** It builds 30m, 2h, 6h, 8h, 12h and 1d by merging bars by position, not on calendar boundaries. It reads the oldest 500 source bars, so its output freezes, and weekends get merged in. Rebuild calendar-aligned bars yourself.
5. **"ATR" means five different things across the code:**

   | Name | Formula | Used by |
   |---|---|---|
   | ATR-SMA14 | Simple mean of the last 14 true ranges, TR₀ = 0, `min_periods=1` | `shared/atr.py`, AME, compose |
   | SMA-ATR14, expanding start | Same, but `prev_c[0]=c[0]` and an expanding mean for early bars | `smc.atr_series`, impulse |
   | Last-14-TR mean | Mean of the last 14 TR, computed from the last 15 bars | `price_action._atr`, `breakouts._simple_atr`, `key_levels` |
   | Wilder RMA30 | Seeded with the SMA of TR[0..29] | Bjorgum, proximity |
   | Wilder ADX | +DM/−DM Wilder-smoothed, then a **simple** mean of the last 14 DX | `regime.trend_regime` |

6. **Missing modules are swallowed silently.**
   - `pullback_targets` and `statistical_features` exist only in `lab/retired/`, so their ImportErrors are caught.
   - As a result `compose()` receives `atr=0`:
     - the main setup path has no TP ladder and always returns SKIP;
     - the CISD and Bjorgum-breakout primers return only WATCH or None.
   - AME's `expansion_min_atr` is always 1.0, and its accumulation `min_bars` is always 8.
   - `features.py` imports eight more modules that do not exist; all of them become stubs.

### 0.2 Code that is dead or degenerate (nothing to replicate as wired)

| Component | Why it is dead |
|---|---|
| SMC peer (`smc.analyze`) | It calls `fvg(...,lookahead=10)` and `order_blocks(...,lookahead=10)`, which do not accept that argument. The TypeError is caught and the peer always returns neutral. Its key names (`bos[-1]`, "bullish"/"bearish" vs "up"/"bull") would break it even after that fix. The primitives themselves work. |
| breakouts `broken` and `failed` states | Unreachable. Horizontal channels almost never qualify, and channels can never reach `cooking`. |
| AME impulses | Never fire inside `analyze`, because bars are built with `v=0`. So `impulse_zones` is empty and CISD qualification never runs. |
| AME sweep patterns | J (volume imbalance) is impossible. K (turtle soup) is always pre-empted by F. B and C fire only on gaps. |
| AME `sweep_confidence` | The wick and type bonuses read keys that are never emitted. The CISD +15 alignment bonus reads the wrong key. |
| MTF consensus (`mtf.analyze_multi_tf`) | Dead. The README's "multi-TF consensus primary signal" is described but not executed. `analyzer.run_consensus` calls it through a separate path; see A10. |
| `correlation` decoupling flag | Always False (fetch limit 672 vs a requirement of 673). |
| level_reaction meta-grade demotion | Unreachable. |
| Tick-confirm (README "Tick confirmation") | Dead: `zml.get_tick_signal` was removed. |
| `sweep.notify_sweep` | Has no caller. |
| `regime_hint()` / expert weights | Always None, so the per-regime weights are never used. |
| Others | `decision._reverse_pullback_entry` (key bug `bot` vs `bottom`), the key-level rejection boost, `zma_v0.py`, and every FastBull/TradingView microstructure, positioning, scanner, study and news module (orphaned, no runner). |

### 0.3 Live behaviour that surprises

1. **AME's shipped direction is inverted.** A bullish sweep (lows raided, close back above) emits **SELL**, citing an internal audit (n=512, 1-bar horizon, t=+2.28). In random-walk tests a sweep fires on about 94% of bars and EXPANSION on about 33%.
2. **ZMA's "attention" z is effectively a plain 50-bar z.** The softmax over |pct| values is nearly uniform. Its confidence is effectively in [84, 95].
3. **The notifier only dispatches Deriv-source alerts by default.** Non-Deriv sources need `CCXT_NOTIFICATIONS_ENABLED=false→true`.
   - The rate limiter is global, not per user.
   - Non-directional alerts bypass the confidence floor.
   - `format_divergence` is defined twice; the second definition shadows the relative-strength renderer.
4. **The `active_signals` write has no confidence floor per timeframe.** Any ZMA BUY/SELL is written; otherwise the highest-confidence directional surrogate peer is written. The ≥50 floor applies only to the `consensus` row.
5. **Funding recipes are off by default** (`CRYPTO_ALPHA_FUNDING_SIGNALS=false`). The only directional crypto_alpha recipe that is live is `fresh_listing_hot`.

---

## 1. `sage/peers/zma.py`: ZMLite z-score mean-reversion (primary peer, live)

### `zma-zscore` (`attention_z_series` 121-160)
- **Input:** a 50-bar window of closes.
- **Computation:**
  - `pct[0]=0`, `pct[k]=Δc/c_prev`.
  - `w = softmax(|pct|)`, with no temperature.
  - `w_mean = Σw·c`, `w_std = sqrt(Σw(c−w_mean)²)`.
  - `z = (c_last − w_mean)/w_std`, or 0 if `std ≤ 1e-10`.
- **Re-implementation:** roughly `(c − SMA50)/σ50`, using the population standard deviation.

### `zma-thresholds` (`dynamic_thresholds` 173-185)
- Over the last 250 |z| values (NaNs dropped): `strong = P85`, `weak = P65`.
- Fallback 1.5 / 1.0 when there are fewer than 10 values.
- Trailing and causal. The regime-specific percentiles in `ZMA_CONFIGS` (trending 90/70, mean_reverting 80/60) are never used.

### `zma-momentum` (`cumsum_slopes`, `classify_momentum` 211-255)
- `slope_t = (mean(last 25 closes) − mean(first 25 closes of the 50-bar window)) / first_close · 100`.
- `thr = median|slope|` over the last 200 slopes.
- Label:
  - `slope > thr` → "Rising Demand" if `slope > prev_slope`, else "Weakening Demand".
  - `slope < −thr` → "Rising Supply" if `slope < prev`, else "Weakening Supply".
  - Otherwise "Neutral".

### `zma-recommendation` (`recommendation` 258-273)
First match wins:

| # | Condition | Recommendation |
|---|---|---|
| 1 | z < −strong and (RD or WS) | STRONG BUY |
| 2 | z < −weak and (RD or WS) | BUY DIP |
| 3 | z < −strong and (Neutral or WD) | BUY (Oversold) |
| 4 | z < −strong and RS | WAIT (Falling) |
| 5 | Mirror image for z > +strong / +weak | STRONG SELL / SELL RALLY / SELL (Overbought) / WAIT (Rising) |
| 6 | Anything else | WAIT |

(RD = Rising Demand, WS = Weakening Supply, WD = Weakening Demand, RS = Rising Supply.)

- **Direction:** BUY if the recommendation contains BUY or OVERSOLD; SELL if it contains SELL or OVERBOUGHT.

### `zma-confidence` (466-499)
- 0 if `|z| < weak`.
- Otherwise `Φ(|z|)·100`.
  - ×1.10 if momentum is aligned: for z<0, any "Demand" label or WS; for z>0, any "Supply" label or WD.
  - ×0.85 if opposed: z<0 with RS, or z>0 with RD.
- Capped at 95.
- `z_accel` is the OLS slope of the last 6 z values (±0.05). It is informational only.

### `zma-geometry` (432-441), defined in code
| Item | Rule |
|---|---|
| Entry | Close |
| Target `revert_to` | The weighted 50-bar mean |
| `hard_stop` | close ∓ 1·σ |
| Reward:risk | |z| : 1 by construction |

### `zma-applicability-gate` (285-355)
The peer is neutral unless this gate passes.
1. Need ≥ 60 closes. Use log returns over the last min(100, n−1) bars.
2. **Fat tails:** if |skew| > 1.5 or excess kurtosis > 6:
   - Compute bipower variance `BV = (π/2)Σ|r_t||r_{t−1}|` over the last 30 returns, and `σ_c = sqrt(BV/30)`.
   - Drop returns with |r/σ_c| > 3.
   - If at least 20 remain and they pass the skew/kurtosis test, the gate passes immediately, skipping step 3.
   - Otherwise the gate fails.
3. **Trend test:** variance ratio, k=5, using non-overlapping block sums and ddof=1.
   - If VR > 1.05 the gate fails, unless the plain 50-bar |z| ≥ 2.

### Data, risks and how alerts use it
- **Data:** closes only.
- **Magic numbers:** 50, 250, P85/P65, 25, 200, 1.5, 6, 3σ, 1.05, 2.0.
- **Lookahead:** none, provided the bar is closed.
- **Notifier:** sends "MOMENTUM" alerts on any BUY/SELL, but **blocks FX pairs by default** (`NOTIFY_ZMA_BLOCK_FX=true`; the comment says "FX momentum not an edge per lab").

### `zma_v0.py` (unused)
- Expanding-start z50.
- P65/P85 over 200 bars.
- OLS slope of the last 7 closes divided by σ7.
- Volume profile: 200 bars, 50 bins, POC, VA 70%, LVN at or below P20. Signal-free.

---

## 2. `sage/peers/ame.py` (+ `impulse.py`, `shared/participants.py`): Accumulation → Manipulation → Expansion

### 2.0 `ame-state-machine` (`analyze` 2759-3241)

Needs ≥ 30 bars. ATR is ATR-SMA14 and includes the current bar.

Priority order, first match wins:

| # | State | Condition | Direction | Confidence |
|---|---|---|---|---|
| 1 | `expansion` | `_expansion_fires` | **SELL if sweep_signal>0 else BUY** (inverted) | §2.3 |
| 2 | `liquidity_swept` | sweep_signal ≠ 0 | inverted, as above | §2.2 |
| 3 | `accumulating` | `is_accumulating` | None (emits watch and reversal levels) | §2.1 |
| 4 | `precursor` | `any_active` | SSL→BUY, BSL→SELL | `min(60, 25+35·composite)` |

- **HTF filter:** if HTF alignment is "opposed", confidence ×0.7 for states 1 and 2.
- **Geometry:** none in code. The faithful replay is:
  - Enter at the next open; the audit horizon was 1 bar, so exit at the next close.
  - Variants:
    - Stop beyond the signal bar's extreme on the far side.
    - Targets TP1/TP2 from `ame-liquidity-targets` (§2.26).
    - Time stop at 20 bars.

### 2.1 `ame-accumulation-range` (115-376)

Defaults: lookback 60, `AME_ACCUM_MAX_WIDTH_PCT=8.0`, `AME_ACCUM_INSIDE_PCT_FLOOR=0.6`, min_bars 8.

**Window.** `wh/wl/wc = high/low/close[-60:-1]`: 59 bars, excluding the current one.

**Candidate A: Bjorgum zone pair.**
- Take support zones with top < price and resistance zones with bottom > price and bottom > support top.
- `ip` = share of closes in `[s.top, r.bottom]`.
- Keep pairs with `ip > 0.6` and bars ≥ 8. Choose the best `ip`, breaking ties by the narrower pair.
- No width cap.

**Candidate B (only if A fails).** Bjorgum nearest support bottom / resistance top, with the same gate.

**Statistical candidate.**
- `stat_high = P90(wh)`, `stat_low = P10(wl)`.
- Valid if `width% = (hi−lo)/mid·100 < 8`, `inside > 0.6` and bars ≥ 8.

**Decision.**

| Structural | Statistical | Result |
|---|---|---|
| yes | yes | strong (structural range) |
| yes | no | moderate |
| no | yes | weak (stat range) |
| no | no | not accumulating |

**Diagnostics.**
- Entropy (log2, 10 bins of returns).
- `atr_ratio` = mean of (H−L) over the recent half ÷ the older half.
- `vol_contraction` = std of returns, recent half ÷ older half.

### 2.2 `ame-accum-confirmers` (331-355): feature only, unused in scoring
- **BB squeeze:** bandwidth `2σ20/SMA20` (population std) ≤ 1.05·min(last 20).
- **Entropy:** 0 < entropy < 2 bits.
- **Stdev low:** the latest rolling σ11 < P20 of the series.
- **ATR contraction:** `atr_ratio < 0.7`.

### 2.3 `ame-liquidity-pools` (383-497)

Defaults: swing_window 10, cluster_pct effectively 1%, decay 0.95. Needs n ≥ 40.

**Swings collected.**
- Wick swings: strict unique max of H (or min of L) over a centred ±10 window. **Confirmed only 10 bars later.**
- Close swings: centred ±5 window.
- Range pseudo-swings: `lb = min(20, n//3)`; floor = min(close[-lb:-1]) and ceil = max(close[-lb:-1]).

**Clustering.**
- Sort levels by price. Start a new pool when `(p−anchor)/anchor ≥ 1%`.
- Keep pools with at least 2 members. Pool price is the members' mean.
- `equality = max(0, 1−(max−min)/(avg·0.01))`.
- Swing-high pools are BSL (buy-side liquidity); swing-low pools are SSL (sell-side liquidity).

**Nearest pools.** `bsl_nearest` is the lowest BSL above the close; `ssl_nearest` is the highest SSL below it.

### 2.4 `ame-sweep-*` patterns A–M (498-768)

**Notation.** L, H, C are the last bar's low, high, close. `pL, pH, pC` are the previous bar's; `p2*` are two bars back. P is the pool price.
- **Important:** `O* = close[-2]` is used as the "open", so every body test is really close-to-close.

**Order of evaluation.** Pools are visited by distance from price, and **all** pools are tested. The first match sets `sweep_signal` (±1) and `sweep_level`.

| id | Bull (+1) | Bear (−1) | Level |
|---|---|---|---|
| A single_bar | L < P < C (SSL) | H > P > C (BSL) | P |
| B two_candle | pL<P, pC<P, C>P | mirror | P |
| C three_candle | as B, or p2L<P ∧ pC<P ∧ C>P | p2H>P ∧ pC>P ∧ C<P | P |
| D equal_lows/highs | Over the last 20 bars excluding the current one, lows within 0.002·price; eq = mean; L < eq < C, or (pL<eq ∧ pC<eq ∧ C>eq) | mirror on highs | eq |
| E pin_bar | b=\|C−O*\|>0, lower wick ≥ 2b, SSL pool with L ≤ 1.005P and C > P; else L ≤ 1.003·range_floor | upper wick ≥ 2b, BSL with H ≥ 0.995P and C < P | P |
| F prev_candle_raid | L < pL and C > pL | H > pH and C < pH | pL / pH |
| G judas_swing | SSL: pL<P, pC<P, C>pH, C>O* | BSL: pH>P, pC>P, C<pL, C<O* | P |
| H stop_hunt_reversal | prev body ratio \|pC−c₋₃\|/(pH−pL) ≥ 0.5, SSL with pC<P and C>c₋₃ | mirror | P |
| I breaker_block | BSL: pC>P, L ≤ 1.002P, C>P | SSL: pC<P, H ≥ 0.998P, C<P | P |
| J volume_imbalance | dead | dead | — |
| K turtle_soup | L < min20, C > O*, overshoot < 0.5% (shadowed by F) | mirror | min20 / max20 |
| L mitigation_block | BSL: pC>P, L ≤ 1.003P, C>P, C>O* | SSL mirror at 0.997 | P |
| M ote_fib | Last 30 bars, down-leg (high before low); retracement (C−low)/rng ∈ [0.62, 0.79]; a BSL pool within 1% | mirror | P |

- **Random-walk firing rates:** equal_lows 32%, single_bar 30%, equal_highs 15%, judas 5%, prev_candle_raid 4%.
- **Implied SMC geometry:** for +1, go long with the stop below the bar low and target the BSL. **As shipped, the direction is inverted.**

### 2.5 Sweep-quality features
- **`vol_confirmed`** (770-779): the bar's range (H−L) > 1.5 × the mean of the previous 20 ranges. It is range-based, not volume-based.
- **`kramers-fill-prob`** (781-797):
  - σ = std of the last 20 log returns × price; T=20; K=0.0014.
  - `P = 1−exp(−K·dist/(σ√T))`.
  - This is monotone in distance, so it is not really a probability.
- **`pool-fatigue`** (799-813):
  - A bar touches the pool if it overlaps `[level·0.995, level·1.005]`.
  - `score = Σ 0.95^(n−1−t)·touched` over the whole dataframe.
  - Tired when the score > 3.
- **`sweep-aggressiveness`** (815-844):
  - `aggr = (wick_past/ATR) · ((H−L)/ATR)`, ×1.5 if `vol_confirmed`.
  - Classes: hard ≥ 2, standard ≥ 0.5, otherwise soft. Feature only.

### 2.6 `ame-cisd-live` (`cisd_detector` 879-952)
1. Over the last 10 bars, take the body sign (zero bodies inherit the previous sign).
2. `last_dir` = sign of the last bar. `run` = number of consecutive opposite-sign bars just before it; need run ≥ 2.
3. The flip bar needs `|C−O|/(H−L) ≥ 0.4`.
4. Confirmation:
   - Bull: C > H[-2].
   - Bear: C < L[-2].
5. Emits BUY or SELL with strength = min(3, run).
6. **Implied geometry:** stop beyond the extreme of the run plus the flip bar.

### 2.7 `ame-cisd-zones` (`mine_historical_cisd` 955-1053)
- Same rule applied at every bar i ≥ 11 (run up to 10), with a 3-bar cooldown and at most 50 zones.
- Zones:
  - BUY: `[min low of run..i, close_i]`.
  - SELL: `[close_i, max high]`.
- No mitigation is tracked.
- **Implied trade:** buy a retest into the zone, stop below its bottom.

### 2.8 `ame-cisd-qualification` (2902-3004): dead in production
- A zone is qualified if an aligned impulse candle (§2.9) appears in the 8 bars after the pivot **and** `detect_participant_type` returns "institutional" with score ≥ 0.55.
- Env: `CISD_REQUIRE_INSTITUTIONAL=true`, `CISD_INSTITUTIONAL_SCORE_FLOOR=0.55`.
- Repaint: a young zone can become qualified later.
- Second latent bug: participant bars use the keys `o/h/l/c`, but the classifier reads `open` etc.

### 2.9 `impulse-candles` (`impulse.py` 43-111)
- **Conditions:** body > 0, `body/ATR14 ≥ 1.5`, `(upper+lower wick)/body < 0.3`, `v/SMA20(v) ≥ 1.5`, and index ≥ 20.
- ATR and the volume SMA both include the bar itself.
- Tag: "institutional" if body/range > 0.70, otherwise "retail".
- **Data:** OHLC plus volume. With zero volume it never fires.

### 2.10 `impulse-levels` (128-231)
- Zone = the impulse bar's `[low, high]`.
- Up-impulse → BUY demand zone; down-impulse → SELL supply zone.
- Dropped if older than 200 bars or narrower than 0.2·ATR.
- Mitigated by a later **close** through the far edge.
- **Implied trade:** limit entry at the zone, stop on the mitigation rule.

### 2.11 `participant-classifier` (`participants.py`)
- Per bar: institutional if body/range > 0.70.
- Four factors:
  - F1: share of institutional bars.
  - F2: same-colour streak — if ≥ 3, `min(streak/5, 1)`, else 0.2.
  - F3: wick fraction, second half vs first half — < 0.7× gives 0.8, > 1.3× gives 0.2.
  - F4: bodies in the streak non-decreasing (each ≥ 0.9× the prior) gives 0.9.
- Score = mean of the factors. Institutional if > 0.60, retail if < 0.35, otherwise mixed.
- `control_shift` = the first point where three same-type bars follow a different type.

### 2.12 `ame-pullback-detector` (1058-1273)
Not called by AME; only `features.py` uses it.
- **Trend:** EMA20 seeded at close[0].
  - UP if `EMA[-1]−EMA[-5] > 0` and `C > 0.99·EMA`.
  - DOWN if the slope < 0 and `C < 1.01·EMA`.
- **Retracement box:** 20 bars including the current one. Fib levels at .382/.5/.618/.786/.886.
  - Up-trend depth = `(rh−C)/rr`.
- **Levels hit:** within `0.03·rr`. Levels are the fibs, the EMA, and optionally VWAP/POC/sweep, plus Mongo OB zones and golden zones.
- **Zone labels:**
  - OB tag: OTE (0.47–0.65), shallow, deep.
  - Fib zone: shallow (0.35–0.42), mid (0.47–0.53), golden (0.58–0.65), deep (0.75–0.82), extreme (0.85–0.92).
- **Other fields:**
  - Confluence: +3 for an OB, +2 for a sweep or POC, +1 otherwise, +2 extra for the OB tag.
  - `volume_healthy`: last range < 0.8 × the mean of the previous 19.
  - `structure_valid`: `low_t ≥ 0.998·low_{t−2}`.
  - `held`: `C > best_level`, or (touched within 1.005·EMA and C > EMA).
  - `continuation`: held and C > previous close.
  - `is_pullback`: 0.25 < depth < 0.80 and (a level was hit, or |C−EMA| < tol).
- **Implied trade:** long when UP ∧ pullback ∧ continuation. Stop below the pullback level or the 0.886 fib; target `rh`.

### 2.13 Outcome labelling (`label_post_sweep`, `mine_historical_sweeps` 1288-1377)
- Looks 10 bars ahead (**future data, by design**).
- Labels: messy if chop ≥ 3; clean if ≥ 6 directional diffs; otherwise mixed.
- The stored per-symbol rates are full-sample, so they carry lookahead.

### 2.14 `ame-sweep-tracker` (1513-1634)
State machine, horizon 20 bars.
1. Any sweep resets the tracker to `just_swept`. Direction uses the SMC mapping: +1 → BUY.
2. Terminal states persist.
3. `bars_since` > 20 → `none`.
4. **Failed:** the last 2 closes are back through the level.
5. **Direction confirmed** (from `confirming`): close beyond `level ± 1.5·ATR`.
6. **Confirming** (from `just_swept`): ≥ 3 of the last 5 close-diffs point in the trade direction.
- **Implied trade:** enter on confirming or confirmed; stop = 2 closes back through the level; 20-bar time stop.

### 2.15 Precursors
- **`volatility-compression`** (1661-1695): `ratio = mean(TR last 8)/median(TR last 30)`. Active if < 0.6; `score = clip(1−ratio)`.
- **`pool-exhaustion`** (1698-1739): only when there is no sweep. `side_score = clip((fatigue−5)/5)`. BSL → SELL hint, SSL → BUY.
- **`sweep-eta`** (1779-1861): median interval between past `liquidity_swept` states (Mongo, last 30 days, needs ≥ 5). Score is 1 at or beyond the 75th percentile. DB-dependent.
- **`combine_precursors`** (1864-1902): composite = max of the scores. Active if compression, exhaustion ≥ 0.4, or ETA ≥ 0.5.

### 2.16 `ame-sweep-side-predictor` (2045-2228)
Only applies while accumulating. W = 1/7. In `analyze` only factors 1, 2, 4 and 7 are live.

| # | Factor | Formula |
|---|---|---|
| 1 | Pool count | `W·(n_ssl−n_bsl)/Σ` |
| 2 | Fatigue | `W·(ssl−bsl)/Σ` |
| 3 | OFI | 0 |
| 4 | Fill probability | `W·(ssl−bsl)/Σ` |
| 5 | Order blocks | 0 |
| 6 | Trend | 0 |
| 7 | Position | `clip(−2W·(range_pct−0.5), ±W)` |
| 8 | Hilbert phase | 0 |

- If total > 0.05 → SSL side, expansion BUY. If < −0.05 → BSL, SELL.
- `watch_level` = the edge expected to be swept; `reversal_level` = the opposite edge.
- **Implied trade:** wait for the raid beyond `watch_level`, reverse toward `reversal_level`. Stop just beyond the raid extreme.

### 2.17 `ame-expansion-trigger` (2725-2747)
- Same bar as the sweep. Direction must agree:
  - sig > 0 and C_t > C_{t−1}, or
  - sig < 0 and C_t < C_{t−1}.
- Also needs `(H−L)/ATR ≥ 1.0`.
- As shipped this is a **fade of large sweep bars**.

### 2.18 `ame-htf-alignment` (`mtf.htf_alignment`)
- **Timeframe map:** 15m→1h, 30m→4h, 1h→4h, 2h→1d, 4h→1d.
- **DB path:** the first BUY/SELL from stored `analytics_results` within the last 8 hours.
- **Fallback:** HTF close / SMA20 of HTF closes. BUY if > 1.0007, SELL if < 0.9993. If neutral, the same test on the LTF.
- **Backtest:** use the fallback on closed HTF bars.

### 2.19 `ame-range-keylevel-confluence` (2311-2368)
- Bjorgum key levels within 0.3·ATR of a range edge. Feature only.

### 2.20 `ame-liquidity-targets` (2408-2627)
- **Pools:**
  - Upside = `range_high` if price is inside the range, else `bsl_nearest`.
  - Downside = `range_low`, else `ssl_nearest`.
- **Candidates:** LTF and HTF Bjorgum key levels beyond the pool.
- **Distance caps in ATR (cap1 / cap2 / min_sep):**

  | Class | cap1 | cap2 | min_sep |
  |---|---|---|---|
  | synthetic | 4.0 | 5.5 | 0.4 |
  | fx (`frx` prefix) | 4.0 | 6.0 | 0.6 |
  | commodity, crypto, other | 3.0 | 5.0 | 0.5 |

- Plain "EURUSD" is classed as other.
- **Sort order:** (not rejection_confirmed, −rejection_score, distance).
- Pick 1 needs d ≤ cap1. Pick 2 needs d − d1 ≥ min_sep and d ≤ cap2.
- **Use:** TP1/TP2 for AME trades.

### 2.21 Confidence scores
- **Accumulating** (1907-1957). Base 20.
  - bars_inside: ≥25 → +25, ≥15 → +15, ≥8 → +8.
  - inside_pct: ≥0.85 → +25, ≥0.70 → +15, ≥0.55 → +8.
  - width%: <0.5 → +15, <1 → +10, <2 → +5.
  - Natural-log entropy of 29 returns: <1.0 → +15, <1.5 → +8.
  - Strength: strong +15, moderate +8.
  - Capped at 100.
- **Sweep** (1960-2016), as it actually runs. Base 30.
  - +25 if `vol_confirmed`.
  - range/ATR: <0.5 → +20, <1 → +10.
  - +15·equality of the nearest pool on the swept side.
  - +10·volume_signature, where `volume_signature = clip(v₋₂/mean(v[-7:-2])−1) · clip((v₋₁/base−1)/0.5)`.
  - ×0.7 if no CISD.
  - Capped at 100.
- **Expansion** (2019-2042).
  - Start from `min(sweep_conf, 80)`.
  - If CISD: +15 + 3·min(strength, 3).
  - size_atr: ≥2 → +15, ≥1.5 → +10, ≥1 → +5.
  - Volume surge `v/mean(prior 20)` ≥ 1.5: `+10·min(1, surge−1)`.
- Then ×0.7 if the HTF is opposed.

### 2.22 Research metrics (re-exported; `shared/research_metrics.py`)
- **Momentum half-life:**
  - ACF of returns over 200 bars at lags 1–20; fit log-ACF on lag.
  - Fewer than 3 positive lags → half-life 1; λ ≤ 0 → 100.
  - Trend regime if half-life > 10; mean-reversion if < 3.
- **CFAR breakout:**
  - Test |Δclose| of the last bar against 25 reference cells at t−30…t−6 (5-cell guard).
  - Threshold ≈ 4.235 × the mean (pfa 0.02). Direction = sign of Δ.
- **Ising susceptibility:**
  - `M = Σr/Σ|r|` over 20 bars; `χ = var(M)` over 10.
  - z-score against the whole available series. Fires if > 1.5.

### 2.23 AME data and lookahead summary
- **Data:** OHLC. Volume is used for bonuses only.
- **Lookahead:**
  - Centred pivots (±10, ±5; Bjorgum 20/15) must be computed causally.
  - Fatigue, pools and CISD mining depend on the length of the dataframe, so fix it at 300 bars.
  - DB items (ETA, golden/OB zones, sweep stats) are full-sample.
- **Magic numbers:** 60, 8%, 0.6, 1%, 0.002, 1.003–1.005, 0.62–0.79, 1.5, 0.95, 3, 0.4, 1.0 ATR, 20.

---

## 3. `sage/peers/bjorgum.py`: Bjorgum Key Levels (Pine v5 port)

### Primitives (`BjConfig` 33-87)

**Parameters.**

| Parameter | Default | Notes |
|---|---|---|
| `n_piv` | 4 | env `BJORGUM_N_PIV` |
| `mult` | 0.5 | env `BJORGUM_MULT` |
| `src` | HA | env `BJORGUM_SRC` |
| `detect_patterns` | true | env |
| left / right | 20 / 15 | pivot window |
| `atr_len` | 30 | |
| `per_max` | 5% | zone cap |
| lookback / swing | 2 / 5 | |
| TSI | 5 / 25 / 14 | |

The lab config was mult 0.015, src "hilo", n_piv 10.

**Indicators.**
- **ATR:** Wilder RMA30. TR₀ = 0; seed = SMA of TR[0..29].
- **EMA:** seeded with the first value.
- **TSI:** `EMA5(EMA25(Δc)) / EMA5(EMA25(|Δc|))`. Ratio in [−1, 1]; signal = EMA14.
- **Heikin-Ashi source:**
  - `haC = (O+H+L+C)/4`; `haO₀ = (O₀+C₀)/2`; `haO_t = (haO_{t−1}+haC_{t−1})/2`.
  - Pivot source = `max/min(haO, haC)`.

**Pivots.** Strict: the source value must exceed every value in [c−20, c+15]. **Confirmed 15 bars late.**

**Zones** (591-639).
- Half-band = `min(ATR30[c]·mult, 5%·close[c]) / 2`. Pivots before bar 29 fall back to ±2.5%.
- Keep the 4 newest high zones and 4 newest low zones.
- Overlapping zones are snapped together every bar (`_align_zones`).

**Role flip** (648-675).
- Close > top → bull (support). Close < bottom → bear.
- Counters `track_high` / `track_lows` count net flips.
- Quirk: a zone can flip on the bar it is created.

### `bj-zone-sr` (BJ-1)
- Nearest resistance = the top of the nearest non-bull zone above price.
- Nearest support = the bottom of the nearest bull zone below.
- Also emits flipped flags and flip counts. Feature only.
- **Implied trade:** bounce or reject at the zone; stop beyond the far edge.

### `bj-breakout` / `bj-breakdown` (BJ-2, 697-704)
- **Breakout:** `track_high` rose this bar ∧ close = 16-bar highest close ∧ every zone is bull.
- **Breakdown:** mirror.

### `bj-res-break` / `bj-sup-break` (BJ-3, 677-685)
- Fires on the net flip of either counter this bar.

### `bj-false-break` (BJ-4, 796-843)
- **Bull:** a counter dipped within the last 1–2 bars and has recovered to its prior level, **and** within the last 3 bars the close was the 6-bar lowest close.
- **Bear:** mirror.

### `bj-zone-push` (BJ-5, 846-887)
- **Support push:** no res_break this bar, close inside a bull zone, and C > O.
- **Resistance push:** mirror.

### `bj-tsi-curl` (BJ-6, 730-747)
- **Bull:** TSI rising ∧ TSI < signal ∧ close inside a bull zone.
- **Bear:** mirror.

### `bj-candle-patterns` (BJ-7, 291-554)
16 detectors. Not location-filtered, and not used in Bjorgum's own vote. Definitions:

| Pattern | Rule |
|---|---|
| doji | body ≤ 5% of range, both wicks > 0, max wick ≤ 2× min wick |
| dragonfly / gravestone | body ≤ 5%, opposite wick ≤ 5%, main wick ≥ 50% |
| hammer / shooting star | range ≥ 0.1·ATR30, body ≤ 33%, the "other" wick ≤ 5% of body, main wick > body; no colour requirement |
| spinning top | body ≤ 35%, both wicks ≥ body |
| long lower / upper shadow | that wick ≥ 75% of range, range ≥ 0.1·ATR |
| engulfing (body) | bull: prev bear, cur bull, C ≥ prev O and O ≤ prev C |
| tweezer | \|Δlow\| ≤ 5% of the previous range, colours reversed |
| piercing / dark cloud | opens beyond the previous close, closes past the previous body midpoint but not past the previous open |
| harami | the whole current candle sits inside the previous body, opposite colour |

### `bj-peer-vote` (BJ-8, `analyze` 899-1123)
- Needs ≥ 40 bars. Reads only the last bar's flags.
- Bull flags: breakout, res_break, false_break_bull, sup_push, curl_bull. Bear flags are the mirrors.
- Direction = the majority side, needing ≥ 1 flag.
- `conf = min(80, 25+18·n)`: 1 → 43, 2 → 61, 3 → 79.
- **Geometry:** none in code. Via compose: stop 1·ATR, TP 1/2/3·ATR.
- **Data:** OHLC.
- **Risks:** depends on the 300-bar window; last-bar flags repaint on a forming bar.

---

## 4. `sage/peers/smc.py`: SMC primitives (peer dead; primitives usable, `fvg` live in level_reaction)

| id | Rule | Lookahead and notes |
|---|---|---|
| `smc-swings` (86-130) | H[i] = max over the 11 bars i±5; ties allowed | Needs 5 future bars |
| `smc-bos-choch` (285-329) | Register the swing (do this at i+5 for causality). A close > the last swing high is an up event: CHoCH if the trend was down, else BOS. Each swing breaks once. Mirror for down. | Implied: trade the break, stop at the opposite swing |
| `smc-fvg` (136-200) | Bull: `h[i−1] < l[i+1]`, zone `[h[i−1], l[i+1]]`. Bear: `l[i−1] > h[i+1]`. Mitigated on a full fill (low ≤ bottom for bull). | Known at the close of bar i+1. Implied: buy the retrace into the zone, stop below the bottom. |
| `smc-order-block` (206-279) | Bull OB = bearish bar i followed by a bullish bar i+1 with body ≥ 1.5·ATR14. Zone = [l_i, h_i]. Mitigated on any later overlap. | **Uses the ATR at the end of the sample**; a backtest must use ATR at i+1 |
| `smc-liquidity-sweep` (335-387) | "sell_side": a bar with H > swing high and C < it. "buy_side": the mirror. Swings are never consumed. | Inherits the swing lookahead |
| `smc-hidden-supply-demand` (447-665) | Impulse runs of ≥ 3 same-colour bars, body/range ≥ 0.5 (continuation bars ≥ 0.4, one skip allowed). Pause bars inside a run: opposite colour; a small range (< 0.6 × the neighbours); body < 0.4; no new extreme beyond ±0.2·range; or a sideways pair. Zone = the pause bar's [L, H]. Strong if opposite colour or ≥ 2 pauses. Scans the last 50 bars. | Repaints for the last 1–3 bars |
| `smc-composite` (683-867, dead) | Base 40 from the latest BOS. +min(15, 8k) for aligned FVGs within ±ATR; same for OBs; +min(10, 5k) for hidden zones; ×0.7 for a "wrong" sweep. Capped at 85. | Never runs |

---

## 5. `sage/peers/breakouts.py`: patterns, level breaks, retest, cooking

Needs ≥ 50 bars. ATR = mean of the last 14 TR.

### `bo-horizontal-channel` (44-94)
- 60-bar window, top_n = 12.
- The 12 highest highs must span ≤ 0.3·ATR (R = their mean); the 12 lowest lows likewise (S).
- R − S ≥ 1.5·ATR.
- At least 3 touches on each side, within 0.15·ATR.
- Practically never fires.

### `bo-triangle` (97-161)
- 60-bar window. Pivots are ±3 local extrema (ties allowed); the last 3 bars cannot be pivots.
- At least 3 pivots on each side. OLS lines fitted through them.
- Requires slope_hi < 0 and slope_lo > 0, with width at the last bar ≥ 0.5·ATR.
- `apex_bars_ahead = (int_hi−int_lo)/(slope_lo−slope_hi) − x_last`.
- `height` = width at x = 0.

### `bo-classify` (164-200)
- Close beyond the line ± 0.05·ATR.

### `bo-key-level-break` (518-597)
- Used only when no pattern exists.
- Levels = Bjorgum zone mids; `rejection_strength = 1 − width/ATR`.
- BUY if `prev_close ≤ lp+0.1ATR < last_close`. SELL is the mirror.
- If several levels break, take the highest rejection strength.

### `bo-volume-surge` (346-366)
- `v[bo]/mean(v[bo−20:bo])`. Confirmed if ≥ 1.5.

### `bo-retest` (255-324, 625-636)
- Window: the 10 bars after the breakout. tol = 0.3·ATR.
- If any close falls back below the level → failed (unreachable in practice).
- A touch plus a close beyond `level+tol` → `retest_confirmed`.
- Touched only, or fewer than 10 bars have passed → `retest_pending`.
- Otherwise → `retest_confirmed`.
- Effective live states: none, retest_pending, retest_confirmed, pattern_forming, cooking.

### `bo-confidence` (639-669)
- Base by state: broken 55, retest_confirmed 75, retest_pending 45, failed 50, pattern_forming 35.
- Volume: `+min(15, (surge−1)/0.5·15)`.
- Channel touches: +10 for ≥ 4, +5 for ≥ 3. Triangle width ≥ 2 ATR: +5.
- Capped at 85.

### `bo-cooking` (684-812)
Triangles only.
- Take the line nearer to price. BUY if the upper line is nearer.
- Fires if `dist ≤ BREAKOUTS_COOKING_ATR (0.5)·ATR` and `0 < apex ≤ BREAKOUTS_COOKING_APEX_BARS (10)`.
- `conf = 55 + 20(1−d/0.5) + 10(1−apex/10)`, capped at 80.
- Geometry fields: `trigger_level` = the nearer line; `measured_target = trigger ± height`; `measured_rr = height/width`.
- **Implied trade:** stop-entry at the trigger, stop at the opposite line, target the measured move. The code itself calls this "not a validated edge".
- If not cooking: `pattern_forming`, conf 30, no direction.

### `bo-first-target` (371-413)
- The nearest unmitigated opposing AME impulse zone beyond price. Its near edge is the target.
- Dead in production, because impulse zones are always empty (§0.2).

### Implied post-break trade and risks
- **Trade:** enter on the breakout close or on the retest-rejection bar; stop beyond the level; target `first_target` or the measured move.
- **Data:** OHLC plus volume.
- **Repaint:** the pattern is recomputed on a sliding 60-bar window, so a triangle often disappears after the break.

---

## 6. `sage/peers/level_reaction.py` (+ `shared/price_action.py`, `key_levels.py`, `shared/structure.py`, `shared/regime.py`, `shared/kelly.py`): graded level reactions

This is the most complete trade plan in the codebase.

Bars = `df.tail(lookback_for_tf)`: 15m/30m 240, 1h 220, 2h–4h 200, 6h/8h 180, 12h 160, 1d 300, 1w 200. Needs ≥ 40 bars. ATR = mean of the last 14 TR.

### `lr-levels` (550-558)
Three level sources:
- **Bjorgum zone mids** (`key_levels.detect_key_levels_dynamic` 58-119).
  - `touches` = number of flips.
  - `rejection_score = clip(1−width/ATR14)`; confirmed if ≥ 0.5.
  - Deduplicated by price.
- **Hyperliquid liquidation clusters** ≥ $1M (crypto only). **Not OHLC.**
- **Long moving averages** (`LEVEL_MA_LEVELS=true`):
  - SMA200 and SMA50 of daily closes; SMA200 of weekly closes.
  - Requires ≥ 90% of bars present. Includes the developing bar.

### `lr-in-play` (`confirm_reaction` 309-358)
- Distance of the nearest level to the last bar's [L, H] (0 if inside).
- In play if ≤ 0.5·ATR.
- Side: resistance if `lp ≥ close`, else support.

### `lr-confirm-candle` (`confirm_at_level` 56-106)
- A Bjorgum pattern on bar n−1 or n−2 in the right direction: bear at resistance, bull at support.
- Doji and spinning top excluded.
- A bare touch only reaches stage "in_play_unconfirmed" and is not emitted.
- With `LEVEL_CONFIRM_CISD_OR` (default false), a CISD also counts as confirmation.

### `lr-sweep` (`detect_sweep` 109-145)
- Over the last 3 bars, pierce = max(H) − lp at resistance (min L at support).
- Swept if the close is back inside **and** pierce ≥ 0.1·ATR.

### `lr-retest` (234-286)
Off by default (`LEVEL_RETEST_ENABLED=false`).
- Last bar within 0.4·ATR of the level.
- `disp = (close[−4]−lp)/ATR`; needs |disp| ≥ 1.
- `disp > 0` means BUY.
- Kind = "break" if any close in bars[−20:−3] sits beyond the level ∓ 0.3·ATR on the opposite side; otherwise "hold".
- Confirmation uses a pattern on the last bar.
- Stop multiple 0.25.

### `lr-cisd` (148-223), recorded flag
- In the 10 bars before the confirmation bar, find a run of ≥ 2 "delivery" candles (bearish at support).
- The leg's extreme must be within 1.5·ATR of the level.
- The CISD line is the open of the leg's first candle. Confirmed when the close crosses that line.

### `lr-mtf-confluence` (153-192)
- Higher-timeframe rungs:

  | Setup TF | HTF rungs checked |
  |---|---|
  | 15m | 1h, 4h |
  | 30m | 2h, 1d |
  | 1h | 4h, 1d |
  | 2h–12h | 1d |
  | 1d | 1w |

- A rung counts if any of its Bjorgum levels is within `max(0.75·ATR_setup, 0.5·ATR_htf)` of the level.
- The HTF bars include the developing bar; in a backtest truncate to t.
- Exception: on 1d/1w with a sweep, `mtf_count` is set to 1.

### `lr-grade` (`grade_reaction` 289-297)
- Not confirmed, or `mtf_count < 1` → suppressed.
- Swept and mtf ≥ 2 → **S** (base conf 96).
- Swept → **A+** (90).
- Otherwise → **B+** (72).

### `lr-meta-grade` (258-267)
- `META_GRADE_ENABLED=true`. Counts "extras":
  - structure_aligned;
  - USD/commodity complex direction matches;
  - a liquidation cluster within 0.75·ATR;
  - a funding "crowded" tag;
  - a moving-average level within 0.75·ATR.
- A+ with ≥ 2 extras is promoted to S.

### `lr-structure` (`structure.detect_structure` 38-97)
- Last 120 bars, fractal w=3 (strict). **3 bars of lookahead.**
- Trend: up if HH and HL; down if LH and LL; otherwise range.
- Events:
  - Up trend: close > last swing high → BOS_up; close < last swing low → MSS_down.
  - Down trend: the mirror (BOS_down / MSS_up).
  - Range: BOS in either direction.
- Aligned for BUY: trend up, or BOS_up, or MSS_up, and no bearish context.

### `lr-regime-veto` (`regime.trend_regime` 6-71)
- ADX as in §0.1 (simple mean of 14 DX). Direction up if +DI ≥ −DI.
- Strong if ADX ≥ `REGIME_ADX_STRONG` (28).
- A counter-trend trade in a strong regime, without (swept and aligned), is demoted one grade (minimum B+).

### `lr-trade-plan` (604-706), explicit geometry
| Item | Rule |
|---|---|
| Entry | Last close |
| Stop, SELL | lp + 0.5·ATR (retest: 0.25) |
| Stop, BUY | lp − 0.5·ATR |
| Target, SELL | The highest Bjorgum level below the close |
| Target, BUY | The lowest Bjorgum level above the close |
| R:R | reward / risk |

**Kelly gate** (`kelly.conviction` 61-89):
- p from grade priors: S .64, A+ .61, A .57, B+ .55, B .51. Replaced by measured `level_outcomes` hit rates once there are ≥ 20 per grade.
- b = R:R, or 1.5 if unknown.
- `edge = p·b − (1−p)`. Suppress if edge ≤ 0, i.e. R:R ≤ 0.818 for B+, 0.639 for A+, 0.5625 for S.
- `f* = max(0, p−(1−p)/b)`.
- Confidence = `min(99, base·(0.7 + 0.5·min(1, f*/0.25)))`.

**Exit resolution** (`shared/level_outcomes.py`):
- First barrier hit, **checking the stop first** within a bar.
- Horizon in bars: 15m/30m 96, 1h 48, 4h 30, 1d 12, 1w 8.
- Expiry counts as a loss.

**Notifier extras:** a cost gate and the standing re-send poll (§16).

### `lr-sweep-entry` (625-653), context
- σ = population std of 31 simple returns × close.
- Multipliers by class:

  | Class | Distance used |
  |---|---|
  | crypto | σ × 3.0 |
  | Deriv jump indices | ATR × 2.0 |
  | Deriv step indices | σ × 2.5 |
  | other Deriv | σ × 2.2 |
  | forex / tradfi | ATR × 1.5 |

- Estimated entry = lp ± mult·vol beyond the level. Estimated stop = entry ± 0.5·vol.
- The code comment says these mechanical sweep entries backtested **no better than first-touch**, based on 343 setups.

### Observational flags (recorded, never gate)
Useful as conditioning features in a backtest.
- `impulse_origin`, `fvg_confluence` (tol 0.75·ATR).
- `vol_regime`: ATR14/ATR60 ≥ 1.3 is expansion; ≤ 0.75 is contraction.
- `classic_ta_confluence` (492-533):
  - EMA9 > EMA21;
  - RSI14 (simple averages) < 35 or > 65;
  - MACD(12,26,9) histogram sign;
  - Bollinger %B < 0.2 or > 0.8;
  - CCI20 beyond ±100;
  - close vs VWAP anchored at the window start;
  - volume z20 > 2;
  - 20-bar OLS slope;
  - hammer or engulfing on the last bar;
  - round number within 0.5·ATR.
  - `ta_score` = number of these that are true.

### Price-action variants usable stand-alone (`price_action.py`)
- `detect_sweep`: stop beyond the sweep extreme.
- `detect_cisd`: the CISD line is the stop reference.
- `detect_retest`.
- `confirm_at_level`.

---

## 7. `sage/peers/proximity.py`: approaching a key level (meta-peer)

**Distance unit.** ATR = Bjorgum Wilder ATR30. `band = PROXIMITY_ATR (0.5)·ATR`.

**Per-level confidence.** Each qualifying level gets a base score, plus `15·(1−dist/band)`, plus pattern boosts. Capped at 95.

| Level kind | When it is in play | Base and adjustments |
|---|---|---|
| support | Bjorgum nearest support bottom, with price ≥ level and within band | BUY, 50. Flipped zone: +10+5(flips−1) |
| resistance | Mirror | SELL, same scoring |
| impulse_zone | AME unmitigated impulse zone; edge within band, with 0.1·ATR slack on the wrong side | 50. Institutional +10, retail −5. body_atr ≥ 3 → +8, ≥ 2 → +4. bars_ago ≤ 10 → +10, ≤ 30 → +5 |
| reversal_zone | AME CISD zone | 55 + 5·impulse_count, plus the recency bonus |
| HTF variants | Next 3 higher timeframes, via `mtf.fetch_htf_context` | +12 |

**Pattern boosts.**
- LTF Bjorgum pattern within 3 bars: +8 each, capped at 20.
- HTF pattern within 5 bars: +15 each, capped at 30.
- Doji and spinning top are not excluded here.

**Volume boost.** z of the last bar vs the previous 29 bars: ≥ 2 → +12, ≥ 1 → +6.

**Confluence boost.** 2 distinct level families on the same side → +10; 3 or more → +20.

**Direction and confidence.**
- Direction = the side with more qualifying levels; a tie gives None.
- Confidence = mean of the aligned levels' confidences. Emitted if ≥ `PROXIMITY_MIN_CONF` (40). State "approaching".

**Geometry:** none. Implied: a limit at the level, stop 0.5·ATR beyond it, target the opposite nearest level.

**Data:** OHLCV, Bjorgum, AME, HTF analyses. AME impulse and reversal-zone inputs are empty or partly dead in production (§0.2).

---

## 8. `sage/peers/decision.py`: ensemble and setup composer

### `ens-majority-vote` (`combine` 1296-1433)
- **Peers:** zma, ame, breakouts, bjorgum, smc (dead), proximity, crypto_alpha, defi_alpha. `pullbacks` is always None.
- **Weights:** all 1 (the expert table is dormant).
- **Direction:** BUY if `#BUY ≥ 2` and `#BUY > #SELL`; SELL mirrors.
- **Confidence:** `Σc²/Σc` over the agreeing peers.
- **Geometry:** none of its own.

### `ens-expert-moe` (323-347), dormant
| Expert | Weights | min_agreement |
|---|---|---|
| trending_synthetic | zma 1.5, breakouts 1.3, pullbacks 0, ame 0.7 | 1 |
| mean_reverting_synthetic | ame 1.5, smc 1.3, zma 0.6, pullbacks 0.6 | — |
| trending_fx | smc 1.4, pullbacks 1.3, zma 1.1, ame 0.9 | — |
| mean_reverting_fx | ame 1.4, smc 1.3, zma 0.8, pullbacks 0.9, breakouts 0.9 | — |

Testable only if you supply your own regime label.

### `compose-primary` (387-397)
- The ensemble if it is actionable; otherwise the single highest-confidence directional peer.

### `compose-main-setup` (1544-1723)
**Geometry.**
| Item | Rule |
|---|---|
| Entry | Signal price (the latest close) |
| TP1/2/3 | entry ± 1/2/3·ATR |
| SL (priority order) | The primary peer's stop if it is on the right side → ZMA `hard_stop` (±1σ) → entry ∓ 1·ATR |
| R:R | Per TP |

**TAKE gate.**
- conf ≥ `SETUP_CONFIRM_CONF` (65), **and** ≥ 1 agreeing peer (trivially true), **and** `rr_tp2 ≥ SETUP_MIN_RR_TO_TAKE` (1.75).
- "Jumpy" prefixes use 1.3: BOOM, CRASH, 1HZ, R_, JD, STEP, RB, CRY.
- With an ATR stop, `rr_tp2 = 2`, so TAKE reduces to conf ≥ 65.
- Otherwise SKIP.

**Confidence adjustments made after the gate (cosmetic):**
- leader bias ×1.10 / ×0.85;
- MTF alignment ×1.20 / ×0.70;
- kNN blend.

**Expiry:** no explicit expiry. The setup beam drops candidates after 20 bars.

**In production:** ATR is 0, so this path is SKIP (§0.1).

### Primers (WATCH ladder, run only when there is no primary)

**`primer-cisd-impulse`** (830-934)
- AME CISD plus an aligned impulse in the last 5 of 30 bars.
- `conf = min(85, 50 + 5·n_imp + 5·strength)`.
- Geometry: ATR-based. TAKE if conf ≥ 65, else WATCH.

**`primer-breakout-bjorgum-zone`** (937-1059)
- The breakouts peer is in broken or retest states, and a Bjorgum zone mid sits within 0.5·ATR of `broken_level`.
- `conf = min(90, bo_conf + 10 + 3·flips + 5·flipped)`.
- Nearly dead in practice.

**`primer-range-sweep`** (611-725)
- AME accumulating with a predicted sweep side.
- Direction: BUY if SSL is predicted.
- Entry = `reversal_level`, or the range edge.
- SL = range_low − 0.25·ATR (BUY) or range_high + 0.25·ATR (SELL).
- TP = entry ± 1/2/3 × range width.
- Always WATCH. Confidence = AME confidence.

**`primer-breakout-bracket`** (730-818)
- The breakouts peer is `pattern_forming`.
- One-cancels-other at the upper and lower bounds.
- SL = the opposite bound ∓ 0.25·ATR. TPs at 1/2/3 × width.
- The volume ≥ 1.5× trigger is described in text only.

### `ens-buckets` (1104-1293), render-only
- **Statistics:** if |z| ≥ strong, fade it. `conf = min(95, 40 + 25(|z|−strong))`.
- **Momentum votes:**
  - ZMA momentum label: 65 / 50.
  - `dz_dt` beyond ±0.05: `min(70, 50+100|dz|)`.
  - Bjorgum curl: 60.
  - AME expansion: 70.
  - AME impulse counts: `min(75, 45+10Δ)`.
- **Structure:** majority of the peers' directions.

### Unused geometry helpers
- `sl_impulse_zone_refine`: SL = demand zone bottom − 0.2·ATR, if within 3·ATR.
- `tp_impulse_zone_refine`: TPs at the near edges of opposing zones.
- `adaptive_sl_buffer`: 0.25·ATR, ×0.75 with ≥ 2 confluences, ×0.9 after a sweep or expansion.

### Other components
- **`conf-participant-boost`:** off by default. ×1.15 when institutional and control shifts.
- **`knn-in-context`** (`shared/in_context.py`):
  - 16-dimensional feature vector, Euclidean distance, k=5 over `setup_outcomes` (last 90 days).
  - Distance ×0.7 for human reviews marked "good", ×1.5 for "bad".
  - `conf = 0.7·conf + 0.3·(100·neighbour hit rate at TP2)`.
  - **Not backtestable** without a walk-forward outcome store.
- **`setup-beam`:** top 5 per (symbol, timeframe). Match on the same direction and play style with entry within 0.3·ATR. Age out after 20 bars.

---

## 9. `sage/peers/mtf.py` and `sage/peers/correlation.py`

### `mtf.py`
- **`mtf-htf-alignment`:** see §2.18.
- **`mtf-tf-attention`:** `softmax(|z|)` × hierarchy weight (1w 5 … 15m 1.5), giving `attended_z`.
- **`mtf-htf-vote`:** weighted direction vote; agreement = winning side's weight ÷ total.
- **`mtf-htf-context`** (631-784, live):
  - The next 3 higher timeframes; the latest analysis document, but only if fresher than 2 × that timeframe.
  - Verdict: aligned if aligned > opposed and aligned ≥ max(1, rows//2).
  - **Backtest:** run ZMA on the next 3 higher timeframes (closed bars) and take the majority.
- **`analyze_multi_tf`** (dead). Intended multipliers:
  - |az| > 2 → ×1.15; > 1.5 → ×1.05; < 0.5 → ×0.7.
  - Agreement ≥ 80% → ×1.2; < 50% → ×0.7.
  - HTF disagreement → ×0.6; all agree → ×1.1.
  - Capped at 89. Anti-chase ×0.5.

### `correlation.py`
**`corr-leader-bias`** (282-625)
- **Leaders by class:**

  | Class | Leaders |
  |---|---|
  | crypto | BTC, ETH |
  | FX | DXY, EURUSD |
  | commodities | XAUUSD, USOIL |
  | equities / indices | SPX, NDX, VIX |

- Row direction = the leader's latest `active_signals` direction. Rows older than 2 × the timeframe are dropped. Non-directional rows are kept if |z| ≥ 0.5.
- Weights: own timeframe 1, next higher 2. Cached timeframes: 15m, 1h, 4h, 1d.
- **Aligned:** aligned weight > opposed and ≥ 50% of the total → conf ×1.10, capped at 95.
- **Opposed:** conf ×0.85.
- Applied to zma, ame, breakouts, bjorgum, smc, proximity, ensemble and setup.
- **Backtest:** substitute the leader's ZMA direction computed on time-aligned bars.

**`corr-pearson-regime`** (948-1000)
- Return correlation with BTC/ETH over 96 and 672 bars. Aligned by **position**, not timestamp.
- Regime: > 0.7 tight, > 0.3 moderate, > −0.3 decoupled, else inverse.
- Feature only.

---

## 10. Crypto, flow and DeFi peers (`crypto_alpha`, `defi_alpha`, `open_interest`, `tape`, `liquidations`)

None of these define geometry. All emit `{direction, confidence, price=close}`. crypto_alpha, defi_alpha, usd/commodity confluence and divergence can be the surrogate trigger for `active_signals` (A4); the others are panel-only.

### `crypto_alpha.py` (MEXC funding and listings)
- **Data:** Mongo `funding_rates` (last 30 days) and `mexc_listings`.
- **APR:** `rate·(8760/cycle_h)·100`.

| Recipe | Rule | Confidence |
|---|---|---|
| `funding-crowded` (184-267) | Fewer than 10 samples: \|APR\| ≥ 50 → fade the sign, conf 55. Otherwise percentiles of the 30-day rates (latest included). SELL if latest ≥ P90 or APR ≥ 50; BUY if ≤ P10 or APR ≤ −25. | SELL: `50+min(20,5|z|)+5·[APR≥50]`; BUY: `50+min(20,5|z|)`; cap 75 |
| `funding-flipped` (270-310) | Sign changed among the last 6 *samples* → trade opposite to the latest sign | 50 |
| `funding-flip-now` (470-500) | The last two samples have opposite signs → trade opposite to the latest | 55 |
| `market-funding-extreme` (315-423) | Cross-section of ≥ 50 perps with a sample in the last 24h. Symbol APR ≥ P95 → SELL; ≤ P5 → BUY. Bands were calibrated in-sample (P5 ≈ −37%, P95 ≈ +44% APR). | `50+min(30, 10|APR|/band)` |
| `fresh-listing-squeeze` (426-467) | Listed ≤ 72h and APR ≤ −100 → BUY (single-day anecdote) | `60+min(25, 5|APR|/100)` |
| `fresh-listing-hot` (503-542) | Listed ≤ 12h → BUY. **Live by default.** | 55 |
| `exhaustion-fade` (545-581) | crowded_long ∧ `close/close[-24]−1 ≥ 50%` (23 bars) → SELL | 65 |

- **Combination:** the highest-confidence recipe sets the direction; +5 per extra agreeing recipe, capped at 80.
- **Defaults:** every funding recipe is off.
- **Implied geometry:** fade or momentum entry at the close; exit at the next funding settlement or after N bars; ATR stop.

### `defi_alpha.py`
**Volume metrics** (72-168):
- Volume z of the last bar vs the previous 30 bars (population std).
- `slope_3bar = mean(v[-3:])/mean(v[-6:-3]) − 1`.
- `change_pct` = 24-bar % change.
- `vol_usd = v·c` of the last bar.
- Streak of same-colour candles.

| Recipe | Rule | Direction | Confidence |
|---|---|---|---|
| `vol-surge-quiet-price` | z ≥ 2 ∧ \|chg24\| < 1.5% | BUY | `min(75, 55+min(15, 5(z−2)))` |
| `vol-surge-momentum` | z ≥ 2 ∧ \|chg\| ≥ 3% ∧ slope ≥ 0 ∧ same-direction streak ≥ 3 | sign of chg | `55+min(15,5(z−2))+min(10,20·slope)+min(10,2(streak−3))`, cap 85 |
| `fresh-listing-volume-validated` | ≤ 12h ∧ vol_usd ≥ $1M | BUY | `55+15(1−age/12)+10·min(1, usd/5e6)`, cap 80 |
| `tvl-leads-price` | DefiLlama `change_1d ≥ 25%` ∧ \|chg24\| < 0.5·tvl change | BUY | `55+min(15, tvl/10)` |
| `fdv-bomb` | FDV/mcap ≥ 3 ∧ `change_7d ≥ 10` (that field is **TVL** change) | SELL | `min(70, 55+5(r−3))` |
| `mcap-tvl-divergence` | Over 7 days of snapshots: mcap +15% ∧ TVL −10% | SELL | `min(72, 55+(m−t)/5)` |
| `undervalued-vs-tvl` | TVL ≥ $25M ∧ mcap/TVL < 0.5 | BUY | `min(70, 55+30(0.5−r))` |
| `dex-pool-flow` | Pool 24h volume ≥ $5M ∧ 24h change ≥ ±2% (pools collector disabled) | sign of change | `min(70, 55+5·vol/5e6)` |

- **Combination:** the highest-confidence recipe sets the direction; +5 per extra agreeing recipe, capped at 85.
- Only the two volume recipes are pure OHLCV.

### `open_interest.py` (81-214)
- **Data:** MEXC OI every 5 minutes, 30 days, ≥ 30 samples.
- `z(OI)` over the whole series. `oi% ≈ 30h change`. `px% = close/close[-bars_lb]−1`, with `bars_lb = min(12, max(3, n//4))`.
- **Rule:** |z| ≥ 1 ∧ |oi%| ≥ 1% → **direction = sign of px%** (OI never changes the direction).
- `conf = min(80, 35+12(|z|−1))`.
- Backtest with Binance OI metrics.

### `tape.py` (83-203)
- **Data:** the last 20 `trade_tape` snapshots (~30 s each). Stale after 300 s. Needs ≥ 200 trades.
- `ratio = Σbuy/(Σbuy+Σsell)`.
- BUY if ratio ≥ 0.58 and the latest snapshot > 0.5; SELL if ≤ 0.42 and the latest < 0.5.
- `conf = min(80, 40 + 2·skew pct-points)`.
- Selection bias: tape exists only for pump-scanner candidates.

### `liquidations.py` (76-176)
- Wall-clock last 15 minutes. Total ≥ $500k.
- Short-liquidation share ≥ 0.65 → SELL (fade the squeeze top).
- Long-liquidation share ≥ 0.65 → BUY.
- `conf = min(75, 35+min(20, 5(total−5e5)/1e6)+max(0,(skew−0.65)·100))`.
- Stated horizon 30–60 minutes.
- **Data:** Hyperliquid HLP liquidation fills. That feed is reportedly dry; the Bybit path mislabels ordinary trades.

---

## 11. Statistical OHLC peers (panel-only, any asset)

### `rug-setup` (`rug_setup.py` 73-232): blow-off-top short
**Parameters:** 60-bar window, min pump 50%, acceleration window 10, accel ratio ≥ 2, volume z ≥ 2 (unused gate), within 5% of the high, rejection body ≤ 0.40. Needs ≥ 65 bars.

**Computed values.**
- `pct_from_low = close/min(low60) − 1`.
- `accel = (recent_pct/10)/(base_pct/50)`, where recent = c/c[−11] − 1 and base = c[−11]/c[−60] − 1. Equals ∞ if base ≤ 0 and recent rate > 1%/bar.
- `vol_z = (mean v of last 10 − mean v of first 50)/std₁(first 50)`.
- `streak_up` = consecutive up closes, maximum 10.
- `body_pos = (C−L)/(H−L)`.

**Gates.**
- Pump: pct_from_low ≥ 0.5.
- Acceleration: accel ≥ 2 ∧ recent > 0.
- Near top: within 5% of the 60-bar max high.
- Rejected: body_pos ≤ 0.40 ∧ vol_z ≥ 1.5.

**Output.**
- Pump ∧ accel ∧ near top, not rejected → watch; `conf = min(50, 20+6·streak+5·max(0, vz−2))`.
- Rejected → **SELL**; `conf = 60 + min(15, 5·max(0, vz−2)) + min(10, 2·streak) + min(10, 25(0.40−body_pos))`, capped at 90.

**Implied trade:** short at the close, stop above the bar high, target `close[-11]` or 50% of the pump. Tuned on a single token (ESPORTS).

### `cusum` (`cusum.py` 65-182)
- `r = log returns`. `σ = std₁(r[-90:-30])`; `k = 0.5σ`, `h = 5σ`.
- Over the last 30 returns, reset to 0 each evaluation:
  - `S⁺ = max(0, S⁺+r−k)`
  - `S⁻ = min(0, S⁻+r+k)`
- Up-cross only → BUY. Down-cross only → SELL. Both → the later cross wins.
- `conf = min(85, 50+10(peak/h − 1))`.
- **Use only the first bar** it fires; it otherwise repeats for up to 30 bars.
- **Implied trade:** trend-following, 2·ATR stop.

### `anomaly` (`anomaly.py` 48-147)
- `z` = latest pct return vs the previous 60 (ddof 1, needs ≥ 20).
- BUY if z ≥ 3 ∧ body_pos ≥ 0.65. SELL if z ≤ −3 ∧ body_pos ≤ 0.35.
- `conf = min(80, 45+8(|z|−3))`.
- **Implied trade:** continuation at the close, stop at the bar's opposite extreme. The fade variant is also testable.

### `vol-regime` (`regime.py` 59-123): filter only
- `atr% = SMA14(TR)/close`; `ratio = atr%_now / median(atr% of the previous 60)`.
- Bands: < 0.40 dead, < 0.75 low, < 1.50 normal, < 2.50 high, else extreme.
- Trend: mean of the last 5 ÷ the previous 5 − 1, beyond ±10% is expanding/contracting.
- No consumer.

### `divergence` (`divergence.py`): residual relative strength vs BTC/ETH
- 30-bar correlation; skip the leader if r² < 0.3.
- `β = cov30/var30`; residual = `f − β·l`.
- `div` = 5-bar sum of residuals. `z = (div − mean60)/std60` (window includes the current bar).
- Use the leader with the higher r². BUY if z ≥ 1.5; SELL if ≤ −1.5.
- `conf = min(90, 40+25·min(|z|,3)+30r²)`.
- The docstring claims persistence for 3–5 days, from 140 coins × 250 days, in-sample.
- **Implied trade:** hold 3–5 bars on 1d, optionally hedged against β×leader.
- The notifier renders it with the wrong (shadowed) formatter.

---

## 12. Cross-asset confluence peers

### `usd-confluence` (`usd_confluence.py`)
- **Anchor:** EURUSD only, at the primary source (oanda).
- **Majors:** EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCHF, USDCAD.
- **Per pair** (last 120 bars, needs ≥ 30):
  - ATR14 = mean TR.
  - Levels = strict fractals w=3 (confirmed 3 bars later), plus the window max high and min low.
  - Nearest level to the close; "at" if `|lvl−close|/ATR ≤ 0.6`.
  - At resistance the pair leans **up** (break continuation). Convert that to a USD direction.
- **Basket:** n_at ≥ 4 majors.
  - `conf = min(90, 35+8·n_at+25·align)`.
  - If `align ≥ 0.66` → EURUSD SELL when USD is up, BUY when USD is down.
  - Otherwise `usd_coiled`, no direction, conf capped at 55.
- **Implied trade:** trade the break of the nearest level in the dominant direction; stop at the opposite side (0.6·ATR); target 1–2·ATR or the next level.
- **Live it runs on the oldest bars (bug, §0.1).**

### `commodity-confluence` (`commodity_confluence.py`)
- **Anchor:** XAUUSD (oanda).
- **Feeds:** gold, silver and copper (HG1!/COPPER/XCUUSD), from several brokers.
- **Per feed:** same "at level" logic as above; BUY at resistance, SELL at support.
- **Per commodity:** "at" needs ≥ 2 feeds agreeing.
- **Dominant direction:** gold's if gold is at a level, otherwise the majority.
- **Qualifies:** gold alone, or ≥ 2 commodities agreeing.
- **Confidence:** `min(90, 45+15·n_agree+5·Σbrokers)`. Gold-solo is capped at 60. Then −12 per conflicting commodity, floor 30.
- Same stale-bars bug.

---

## 13. `event_gate.py`: economic-calendar gate (no consumer)
- Reads the latest `tradingview_calendar` document.
- Keeps events with importance ≥ 1, country in {US, EZ, GB, JP, CN}, within ±60 minutes of now.
- `imminent` = any match. `conf = 40+min(30, 8·count)`.
- **Intended use:** block new entries within ±60 minutes. Needs a historical calendar.

---

## 14. `sage/analyzer.py`: orchestration rules

| id | Lines | Rule |
|---|---|---|
| A1 stale-bar-gate | 288-301, 768-784 | Skip a symbol/timeframe if the last bar is older than `ANALYZE_STALE_MULT (2) × tf`. |
| A3 zma → active_signals | 795-797, 907-939 | Any ZMA BUY/SELL is upserted and published. **No confidence floor.** |
| A4 surrogate trigger | 881-905 | If ZMA is not actionable, take the highest-confidence directional peer among crypto_alpha, defi_alpha, ensemble, ame, level_reaction, usd_confluence, commodity_confluence, divergence, breakouts. No floor; ties keep list order. In effect an "OR of peers" trade rule. |
| A5 headline | 839-858 | setup → ensemble → zma. Display only. |
| A6 thesis-broken | 385-442 | An opposite-direction write over an existing signal publishes an exit/reverse event. 1800 s cooldown. Effectively stop-and-reverse. |
| A7 proximity alert | 445-499 | proximity is "approaching"; 1800 s cooldown per level. |
| A8 tick-confirm | 972-1069 | Dead. Intended: bar BUY with tick SELL → CONFIRMED ×1.08; same direction → FADING ×0.88 (inverted mean reversion); precision grade upgrades. |
| A9 mtf-sweep-score | 570-675 | See below. |
| A10 consensus write | 1644-1768 | Needs ≥ 2 timeframes. `analyze_multi_tf`, then carry stop and target from the timeframe with the largest \|z\|, then the sweep boost. If conf ≥ 50 → `active_signals(tf="consensus")`. |
| A11 accumulation event | 1771-1843 | ZMLite accumulating ∧ no BUY/SELL ∧ sweep conviction ≥ 0.25. Intended direction: SELL if BSL is predicted, BUY if SSL. Bjorgum S/R attached. Implied: a range sweep-reversal. |
| A12 leader-bias nudge | 1562-1599 | See §9. |

**A9 `mtf-sweep-score` in detail.**
- Per timeframe, from ZMLite: sweep ±1 and level, accumulating flag, trend.
- Timeframe groups: HTF = {1h, 2h, 4h, 6h, 12h, 1d}, MTF = {30m}, LTF = {15m}.
- Direction = the majority of sweeps; ties go to BUY.
- **Strength:**
  - +2 if an HTF is accumulating and 15m/30m swept;
  - +1 if ≥ 2 timeframes swept;
  - +1 if sweep levels sit within 1% of each other;
  - +1 if the HTF trend agrees.
- **Confidence boost:** strength 1 → ×1.15, 2 → ×1.30, 3 → ×1.50, 4+ → ×1.70.
- The consensus recommendation is overridden only when strength ≥ 3.
- **Risk:** per-timeframe signals of different ages are mixed together.

---

## 15. `sage/shared/*`: other indicators, filters and gates

### Volume (`volume.py`; `_ensure_volume` substitutes ones when volume is missing)
| id | Rule |
|---|---|
| E1 volume-weighted z (28-98) | Softmax of \|pct\|·rel_vol. In practice ≈ z50. |
| E2 VWAP bands (103-144) | 50-bar VWAP ± 1.5·σ (volume-weighted). Fade at the bands. |
| E3 volume profile (149-272) | 200 bars, 50 bins. Each bar's whole volume goes to the bin of its typical price. Buy volume if c > o. POC, buy-POC, sell-POC; value area 70% grown from the POC toward the larger neighbour; `vp_position = (C−VAL)/(VAH−VAL)`; delta in the current bin beyond ±20 gives bullish/bearish. |
| E4 volume z (277-304) | Last bar vs the previous 20. > 2 surge, < −1.5 drought. |
| E5 CVD divergence (307-363) | `delta = v(2c−h−l)/(h−l)`. Bull divergence: close < close[−25] while the last-24-bar delta sum > 0. Bear is the mirror. |
| E6 "VPIN" (366-411) | Mean of \|2·CLV − 1\| over 20 bars. "Toxic" if > 0.3. Pure OHLC. |
| E7 Amihud (414-447) | \|Δc\|/v; z vs 20 > 2. |
| E8 MTF POC confluence (506-562, live) | Weighted average POC across timeframes; converged if ≥ max(2, n//2) timeframe POCs lie within 1% of it. |
| E10 absorption (622-742) | Wick delta `((uw−lw)/rng)·v`, z vs the previous 19. **SELL:** z ≥ 1.5 ∧ bearish candle ∧ new 19-bar high ∧ upper wick ≥ 50% of range. **BUY:** mirror. Implied: next-bar entry, stop beyond the wick. |
| E11 volume-weighted pools | Pool within 0.5% of the POC; a sweep confirmed by VP delta beyond ±20. |

### Trend and regime (`trend.py`)
- **Kaufman efficiency ratio**, w=20: > 0.6 trending, < 0.2 ranging.
- **Variance ratio**, k=5 over 100 bars: > 1.1 momentum, < 0.9 reversion.
- **Coiled spring:** DE < 0.3 ∧ one-bar increase in DE > 0.01.

### Other orphan modules
- **`wavelet.py`:** Haar, 5 levels. HF/LF energy ratio > 2 → HF-dominated, < 0.5 → LF-dominated. Alignment shifts bar to bar.
- **`fpc.py` (Fractal Pivot Counter):**
  - Pivot window = max(5, period//7), centred.
  - Expected run length = median of past runs.
  - Catalan-weighted exhaustion score.
  - Targets: `p ∓ amp`, `∓0.618·amp`, `∓1.618·amp`.
  - Implied: counter-swing entry as exhaustion → 1.
- **`attention.py`:** weighting helpers only. `rejection_attention` can serve as a level-rejection score.
- **`session.py` UTC hour table** (hand-set priors, no DST handling):

  | UTC hours | Session | Quality |
  |---|---|---|
  | 0-6 | Asian | 0.35–0.40 |
  | 7-11 | London | 0.60–0.75 |
  | 12-15 | Overlap | 0.75–0.85 |
  | 16-20 | New York | 0.40–0.60 |
  | 21-23 | Off-hours | 0.25 |

  Sweep probability runs from 0.15 to 0.75. Testable as a filter, e.g. quality ≥ 0.6, which is 07–17 UTC.
- **`features.py`:**
  - `model_applicability`: start at 1 and multiply:
    - volatility floor ×0.1 / ×0.5;
    - Hill tail α < 2.5 → ×0.5, < 3 → ×0.7;
    - Hurst 0.48–0.52 → ×0.7, > 0.65 or < 0.35 → ×1.1;
    - fewer than 50 bars → ×0.3.
    - Tradeable if the score ≥ 0.3. In practice always depressed by the stubbed features.
  - Candle OFI proxy: CLV range-weighted over 20 bars, ±0.15. Orphan.
- **`level_snap`:** snap a level to POC/VAH/VAL within 0.5%.
- **`level_fatigue`:** 50-bar extreme; touch within ±0.3%; decay 0.95 over the passed series; tired > 3, fresh < 2.
- **`pivots.py`:** k-bar strict pivots, centred. `detect_pivots_atr_scaled` uses **future closes**, so it is a labelling tool only.

### Outcome gates (reusable exit geometry)
- **`peer_outcomes`** (live dispatch gate):
  - Barriers: the signal's own target and stop, else **±1.5·ATR14**.
  - Same horizon table as level_outcomes. Stop checked first; expiry is a loss.
  - `peer_grade_live`: Wilson lower bound (z = 1.64) over the last 300 resolved trades per (peer, grade).
    - Fewer than 25 samples → allowed (warm-up).
    - LB ≤ 0.5 → suppressed.
    - Shadow peers need n ≥ 40 and LB ≥ 0.53 with auto-promote on (off by default).
  - **Backtest:** a walk-forward meta-filter.
- **`cost_gate`:**
  - Base spreads:

    | Instrument | Base spread |
    |---|---|
    | EURUSD, GBPUSD, AUDUSD, NZDUSD, USDCHF, USDCAD | 0.0001 |
    | USDJPY | 0.01 |
    | XAUUSD | 0.30 |
    | XAGUSD | 0.03 |
    | Copper | 0.003 |

  - Spread estimate = the cross-broker range clipped to [0.5, 2]× the base.
  - `rt = 2·spread`. Fail if reward ≤ rt or `(reward−rt)/(risk+rt) < 1.0`.
  - Applied to level_reaction and breakouts.
- **`kelly`:** see §6.

### `liq_magnet` scan: see §17 C2.

---

## 16. `notifications/`: dispatch rules (how signals become alerts)

The notifier computes no new price signals, apart from the AME ±0.2% buffers and the formatter classifiers.

### Gate order (`worker.py`)
1. **Source filter:** Deriv only unless `CCXT_NOTIFICATIONS_ENABLED`.
2. **Feed freshness:** the last bar must be no older than 3 bars (+60h for 1d and above).
3. **Bar bucket:** the analytics write time floored to the bar.
4. **Co-fire merge.**
5. **Per-peer toggles.**
6. **Peer predicate.**
7. **Per-bar dedup** (24h key).
8. **Continuation suppress:** fire only on the **rising edge**. Suppress if the previous bar had the same (state, direction, grade).
9. **Outcome-calibration gate** (§15).
10. **Cost gate.**
11. **Rollup.**

**Then, per user:**
- Timeframe blacklist: 1m–14m and "consensus" for non-synthetics; 1m and consensus for synthetics.
- Confidence floor = the user's `notifyMinConfidence` (default **60**). AME and level_reaction use 0. Non-directional alerts are never gated.
- FX-hours rule for `frx*` symbols: closed all Saturday and Sunday before 20:00 UTC.
- Global 300-second rate limit per (symbol, source, peer). Ignores timeframe and direction.
- Per-user cap: 2 per 4h per (peer, symbol, timeframe, direction).

### Per-peer predicates
| Peer | Fires when |
|---|---|
| zma | Directional; **FX pairs blocked** |
| ame | `liquidity_swept` or `expansion`; or `accumulating` with conf ≥ `NOTIFY_AME_ACC_MIN_CONF` (45). `precursor` is never sent. |
| orderblocks | `active` (retired) |
| pullbacks | `pullback_golden` or `pullback_deep` |
| breakouts | `cooking` or `retest_confirmed` (+ `retest_pending` / `failed` with an env flag) |
| key_levels | `rejection_confirmed`, `level_break`, `confluence_stack`, `new_cluster`, `proximity_warning` |
| proximity | `approaching` with ≥ 1 level |
| divergence | `diverging_up` / `diverging_down` |
| usd confluence | `ready_up`, `ready_down`, `coiled` |
| commodities | `ready_buy` / `ready_sell` |
| level_reaction | `support_hold`, `resistance_reject`, `*_retest`, with a grade |
| ensemble, crypto_alpha, defi_alpha | Directional |
| setup | `TAKE` or `WATCH` |

### Geometry and logic computed in the notifier
- **AME range state:**
  - Break-up = `range_high·(1+0.2%)`; break-down = `range_low·(1−0.2%)`.
  - Targets = the next two upside/downside key levels.
  - Implied range-breakout OCO.
- **AME swept state:** invalidation on a close beyond `sweep_level ∓ 0.2%`. Not ATR-scaled.
- **level_reaction alert:** shows estimated entry/stop (sweep variant) or target/stop/R:R.
- **setup alert:** entry, SL, TP1–3, R:R, alternative entry.
- **Co-fire** (`_CO_FIRE_PEERS` = ensemble, proximity, breakouts, crypto_alpha, defi_alpha):
  - ≥ 2 qualifying on the same bar with the same direction → "combined" alert with conf = max of the participants. ≥ 3 → "HIGH CONVICTION".
  - Directions disagree → a "divergence" alert, which is never confidence-gated.
  - **Testable as an n-of-m confluence rule**, with disagreement as a no-trade filter.
- **Cross-timeframe rollup:** same (symbol, source, direction) within 180 s across ≥ 2 timeframes → "MULTI-TF" alert at max conf. On bars this means timeframes closing at the same instant.
- **thesis_broken** (off by default):
  - Only 4h/1d, crypto venues or a leader list.
  - Requires structure confirmation (`detect_structure` w=3 aligned with the new direction).
  - Fully OHLC-testable as a ZMA flip plus a structure event, used as a stop-and-reverse.
- **Crypto leader verdict:**
  - Rows filtered to |z| ≥ 0.5; HTF rows weigh 2×.
  - Funding APR ≥ +15% → "overheated" (contrarian short); ≤ −15% → "shorts crowded".

### Crypto-macro regime classifier (`peer_signals._classify_crypto_regime` 3540)
- Inputs are 24h % changes. Buckets: ≥ 2 strong up, ≥ 0.5 up, ≤ −2 strong down, ≤ −0.5 down.
- Rule order is in §17 A5.
- **4h divergence:** 24h change and 4h change of opposite sign with |4h| > 0.3%.
- **Sector exhaustion:** 24h ≥ +20% and 4h < +1% → fade; 24h ≤ −20% and 4h > −1% → buy.
- **Pump:dump regime:** ratio ≥ 2 bullish, ≤ 0.5 bearish (off by default).
- **VIX alert claim:** when VIX is in its top quintile, next-day AUD/NZD ≈ −12 bp and USDCAD ≈ +10 bp.

---

## 17. Collectors: regime classifiers and flow alerts

### A1 `xsec-dispersion-vol-regime` (`collector_market_regime.py:_compute` 91-129)
- **Universe:** top 120 names by latest volume on the most active source; 1h bars over 840h. **Survivorship bias.**
- **Dispersion:** cross-sectional std of log returns (needs ≥ 8 names).
- **Market volatility:** median of per-name Parkinson vol, `sqrt(mean24(ln(H/L)²)/(4ln2))`.
- **Percentile:** share of the last 120 values below the current one.
- **Regime:**
  - `stressed` if dispersion pct ≥ 0.8 or vol pct ≥ 0.8;
  - `calm` if dispersion ≤ 0.3 and vol ≤ 0.4;
  - else `normal`.
- **Exposure:** `clip(median168(mvol)/mvol_now, 0.25, 1.5)`, a vol-target sizing scalar.
- **Dispersion outlook:** falling if pct ≥ 0.8, rising if ≤ 0.2.
- Emitted every 4h; alerts on change. Explicitly "not a buy/sell signal".
- **Tests:** vol-managed sizing, regime filter, dispersion mean reversion.

### A2 `vix-vvix-rf-direction` (`collector_vix_direction.py` 55-116)
- **Data:** Yahoo daily ^VIX, ^VVIX, ^VIX3M, ^GSPC (15 years).
- **Features:**
  - percentile level (252 daily / 60 weekly);
  - z vs SMA60;
  - 5-bar momentum;
  - VIX/VIX3M;
  - SPX return;
  - for VVIX, also the VIX percentile and z.
- **Label:** next value > current.
- **Model:** RandomForest(300 trees, min_samples_leaf 20, random_state 0), refit every 4h on all data.
  - **Bug:** the last row gets a fake 0 label.
  - The weekly series includes the partial current week.
- **Gate:** VIX 252-day percentile ≥ 0.8 → `RISK_OFF`.
- **USD lean:** FIRM if VIX is forecast UP or risk-off.
- **Implied trades:**
  - VIX direction for 1 day or 1 week.
  - Risk-off gate: short AUD/NZD and long USDCAD for one day.
- Must be refit walk-forward.

### A3 `fx-dollar-driver-regime` (`collector_fx_regime.py` 66-139)
- **Data:** FRED DFII10, DTWEXBGS, VIXCLS, plus Taylor-rule inputs; Yahoo FX for 5 majors.
- **Correlations:** 63-day correlation of FX returns with Δreal rate, Δln dollar index, ΔVIX.
- **Risk-off flag:** VIX > its 63-day mean → +1, else −1.
- **Taylor gap:** `0.5 + infl + 0.5(infl−2) − (u−u*) − FEDFUNDS`. Beyond ±0.5 sets the USD direction.
- **Lean score:** `(wr·pair_usd + wk·sign(c_vix)·risk_off + 0.5·sign(mom21)) / (wr+wk+0.5)`.
  - wr = |c_real| + |c_dxy|, wk = |c_vix|.
  - Bullish if > 0.2, bearish if < −0.2.
- **Regime:** the dominant correlation; "decoupled" if it is below 0.2.
- **Alerts:** a `lean_shift` per pair with a 48h cooldown.
- **Implied trade:** daily, follow the lean.
- **Macro data needs vintages (ALFRED)**, otherwise there is lookahead.

### A4 `gold-regime-switch-stance` (`collector_gold_regime.py` 116-207)
The only collector with an explicit position. The comment cites a lab Sharpe of 0.50.
- **Data:** gold GC1! (or GC=F) daily, FRED DFII10.
- `rr_falling` = DFII10 lower than 63 rows ago.
- **Falling real rates (momentum):** `mom_ens` = mean of sign(gold/gold_L − 1) for L ∈ {21, 63, 126, 252}.
  - ≥ 0.5 → LONG; ≤ −0.5 → SHORT; else FLAT.
- **Rising real rates (mean reversion):** `z20 = (P−SMA20)/STD20`.
  - z20 < −2 → LONG; z20 > 2 → SHORT; else FLAT.
- **Position:** +1/0/−1, re-evaluated at each daily close. No stops.
- **Also computed:**
  - lean = 0.5·rate_lean + 0.5·mom21 sign, threshold ±0.25;
  - pre-2022 OLS residual over 3 months;
  - COT z over 104 weeks. COT data needs a 3-day release lag.
- **The cleanest testable regime idea in the codebase** (gold plus DFII10 only).

### A5 `crypto-rotation-regime` (classifier in notifier; storage in `collector_crypto_macro.py` 913-993)
- **Inputs:** 1h bars; 24h % change of TOTAL, TOTAL2, BTC.D (relative %), ETHBTC, TOTALDEFI.
- **Rules, first match wins:**
  1. TOTAL2 strong up ∧ BTC.D strong down → euphoric altseason.
  2. BTC.D up ∧ TOTAL2 down → flight to BTC.
  3. TOTAL down ∧ TOTAL2 down → risk-off.
  4. TOTAL2 up ∧ BTC.D down ∧ ETHBTC up → rotation into alts.
  5. TOTAL2 up ∧ TOTAL flat → rotation forming.
  6. DeFi up ∧ TOTAL2 not up ∧ gap ≥ 1.5 → DeFi rotation.
  7. Payment-coin basket up ∧ TOTAL2 not up ∧ gap ≥ 1.5 → payment-coin rotation.
  8. TOTAL up ∧ TOTAL2 not up → BTC-led.
  9. TOTAL up ∧ TOTAL2 up → broad risk-on.
  10. Otherwise → chop.
- **Use:** an alt-exposure filter, re-evaluated every 4h.

### A6 Crypto-macro triggers (`collector_crypto_macro.py` 251-441)
Checked every 10 minutes; 4h cooldown; they are **state conditions that re-fire every 4h** while true.

| Trigger | Condition |
|---|---|
| ETHBTC breakout | 1h close > max(prior 169 closes)·1.0001 |
| ETHBTC breakdown | Mirror, ·0.9999 |
| BTC.D drop | 24h ≤ −2% ∧ TOTAL2 or TOTAL ≥ −0.5% |
| BTC.D rise | 24h ≥ +2% ∧ TOTAL2 or TOTAL ≤ +0.5% |
| Quiet coil | \|24h\| ≤ 0.5 for BTC.D, ETHBTC and TOTAL2 ∧ TOTAL 168h close range ≤ 3% → breakout/straddle setup |

### A7 Sector leaders and laggards
- **Data:** CoinGecko categories with mcap ≥ $1B.
- **Leader:** top 3 by 24h change.
- **Laggards:** if the leader is ≥ +3%, take coins in that category with mcap ≥ $20M whose 24h change ≤ the sector − 5pp; pick 5. Add 14-day BTC correlation.
- The `sector_leader_confirmed` trigger cannot fire (it needs 3 snapshots in 3h; snapshots come every 4h).
- **Implied trade:** long the laggard basket for 24–72h.
- **Not archived.**

### B1–B5 Flow data
| id | Source | Rule / use |
|---|---|---|
| B1 stablecoin supply | DefiLlama, every 4h | Δ% of supply. Implied: net mint is risk-on. Historical endpoint exists. |
| B2 ETF flows | Farside regex | **Probably parses the wrong number.** |
| B3 whale ERC-20 | Etherscan, 6 addresses, 10 tx per poll | Inflows to exchanges imply sell pressure. Lossy. |
| B4 token unlocks | DefiLlama emissions, 120-day horizon | `pct_circ = tokens/cumulative schedule`. `pct_adv` is buggy (last 30 rows of any timeframe). Implied: short the perp N days before a large cliff unlock, cover at or after it. Backtestable with schedule-revision bias. |
| B5 DeFi TVL/FDV/DEX | DefiLlama, GeckoTerminal | Feeds defi_alpha (§10). |

### C1–C3 Liquidations
- **C1 `hl-liq-clusters`** (`collector_hl_liq_levels.py` 217-272):
  - Hyperliquid wallets (top 120 by account value ≥ $100k, plus recently active traders); positions ≥ $100k.
  - Liquidation price within 50% of mark, bucketed at 0.5% of mark.
  - Side = long-flush or short-squeeze.
  - Top 12 clusters per coin. Feeds level_reaction levels (≥ $1M).
  - **Not archived.**
- **C2 `liq-magnet`** (`collector_liq_magnet.py` + `shared/liq_magnet.py` 105-184):
  - Clusters ≥ $500k (function default $3M) with |distance| ≤ 5% (default 3%).
  - Magnet up if the cluster is above price, down if below.
  - Breadth: rotation if ≥ 3 coins diverge from BTC's magnet, and they are ≥ 50% of coins.
  - Funding APR and OI bias (±2% over 24 rows) attached.
  - 12h cooldown per coin.
  - **Implied trade:** drift toward the magnet; target the cluster price.
- **C3 realized liquidation fade:** see `liquidations.py` in §10.

---

## 18. Collectors: scanners and universe rules

### `mexc-rt-pump-dump` (`collector_mexc_pump_dump.py` 508-765)
**Sampling.** Every 30 s, the MEXC contract ticker: price P and rolling 24h volume V. The last 20 samples are kept.

**Pre-gates.** At least 4 samples; 900 s cooldown per symbol.

**Layers.**
- **L1 volume:**
  - `recent = max(V[-1]−V[-5], 0)`.
  - Baseline = EWMA (α 0.2) of `V[i]−V[i−5]`, floored at 1e-9.
  - Passes if `recent/baseline ≥ 2`. Exactly 5 samples always passes.
- **L2 price:** `chg = P[-1]/P[-10]−1`; ≥ +3% pump, ≤ −3% dump.
- **L3 streak:** ≥ 3 strictly rising (or falling) steps.
- **L4 liquidity:** P·V ≥ $500k. Note that volume24 is in contracts.
- **Direction:** up if pump layers ≥ dump layers (ties go up).
- **Candidate:** ≥ 2 layers passed **and** L1 passed.
- **L5 flow:** taker-buy share of the last 100 *spot* trades. Need ≥ 0.65 on the trade side (sell share for dumps).

**Tier.**
- Flow on the wrong side (< 0.50): suppressed if base < 3, otherwise early warning.
- ≥ 3 layers and flow not False → confirmed.
- base ≥ 2 → early warning.

**Score.** `25·layers + min(10, |chg|−3) + min(10, 2(streak−3)) + min(10, 50(flow−0.65))`, capped at 95.

**Implied trade.** Momentum continuation, horizon about 15 minutes, stop at the window extreme.

**Backtest.** Needs 1m bars plus taker-buy volume.

### `bar-pump-dump` (`collector_market_pump_dump.py` 219-474)
Runs every 60 s on `market_data` for TradingView, FastBull and Deriv sources.

**Price thresholds (% over 9 bars):**

| Asset class | 15m | 1h | 4h | 1d |
|---|---|---|---|---|
| FX (includes oanda metals and nat-gas) | 0.4 | 0.25 | 0.5 | 2.0 |
| Index (includes tvc oil and VIX) | 0.5 | 1.0 | 1.2 | 1.5 |
| Stocks | — | 1.5 | — | 4.0 |
| Deriv | 2.0 | — | — | — |
| Default | 3.0 | — | — | — |

- The metals and energy keys are unreachable.
- **FX soft gate:** ≥ 0.2% with ≥ 4 consecutive bars.

**Layers.**
- The volume layer uses the same cumulative-volume formula on *per-bar* volume, which is buggy.
- **The liquidity layer is always True, so a price-gate pass alone fires.**
- Confirmed if base ≥ 3.
- The score's price bonus subtracts 3.0, so it goes negative for FX.

**Window.** Freshness `max(45 min, 2.5·tf)` and ≤ 20 bars. On 1d only about 4 bars are available. 1800 s cooldown per (source, symbol, timeframe).

**Faithful replay on closed bars.**
- `C[-1]/C[-10]−1 ≥ threshold` (with the soft gate) → fire in that direction.
- Implied: continuation for 1–3 bars, stop at the 9-bar opposite extreme.
- Run separately on unfinished bars to reproduce live.

### Other scanner and universe rules
- **`deriv-tick-up-ratio`** (341-402): ups/(ups+downs) over the last 500 ticks. Ticks are off by default.
- **`pump-regime-breadth`** (771-903): hourly pump vs dump counts; no rule. Implied breadth = (P−D)/(P+D) as a risk filter.
- **`mexc-new-listing`:** `first_seen_at`; an alert per new symbol. Implied: fade or follow the first pump.
- **`ccxt-universe`** (115-229):
  - `/USDT` pairs, excluding tokenized stocks, stablecoins and commodities.
  - Precision check; 24h quote volume ≥ 5000.
  - Top 50, plus always-on BTC, ETH, SOL, BNB, XRP (spot and perp).
  - Rebuild point-in-time for a backtest.
- **`deriv-universe`:** synthetic indices. The priority list was "validated predictable by lab sweep", which is a selection-bias warning.
- **`forex-session-gate`** (`utils/market_hours.py`): FX closed Saturday and Sunday before 20:00 UTC. Applied only to `frx*` symbols in notifications.
- **`mexc-stock-perp-exclusion`:** drops `*STOCK_USDT`. The excluded idea is the Monday cash-open snap-back of tokenized stock perps.

### Orphaned (no runner)
- FastBull microstructure: VWAP; 100-bin profile on 5m×288; POC; VA 70%; HVN ≥ 1.5× mean; LVN ≤ 0.4× mean. The import is broken.
- FastBull retail positioning: long/short ratio and pending-order POC. No history.
- FastBull correlation.
- TradingView screener: US market cap ≥ $1B, top/bottom 10 movers.
- TradingView study: RSI14; **MACD with SMA oscillator and SMA signal**; BB 20/2.
- News feeds.
- TradingView calendar (live data, no rule).

---

## 19. Pure plumbing (one line each)

### `channels/`
- `backbone`: abstract MPMC channel.
- `memory`: in-memory channel.
- `redis`: Redis streams channel.
- `mongo`: durable Mongo queue.
- `persistent`: SQLite outbox.
- `backoff`: retry policies.
- `dlq`: dead-letter queue.
- `serializer`: payload serialisation.
- `metrics`: metric hooks.
- `errors`: error types.

### `infra/`
- `streams` / `consumers` / `publisher` / `pubsub`: named Redis streams and the `signals:new` publisher.
- `candle_cache`: Redis sorted-set candles with a Mongo fallback.
- `db`: Mongo client; per-timeframe TTL retention (15m 14d … 1d 800d); `upsert_active_signal`; `get_symbol_profile` (a learned-parameter DB, read only by orphan `features`).
- `dlq`.
- `stream_metrics`.
- `worker`: base classes.
- `clients/ccxt_client`, `clients/deriv` (WebSocket candles and ticks, `ticks_to_ohlc`), `clients/telegram` (Markdown→HTML), `clients/discord`.

### `collectors/`
- `collector_ccxt`: OHLCV poller and side-car spawner.
- `collector_deriv`: WebSocket bars written on close.
- `collector_mexc_extras`: funding, OI, listings pollers.
- `resampler`: buggy virtual timeframes.
- `dedup`, `watchdog`, `fault_tolerance` (supervisor, retries, circuit breaker).
- `worker`: legacy REST.
- `asset_class.classify`.
- `fastbull/*` and `tradingview/*` clients, collector, symbol catalog, websocket.

### `sage/`
- `worker.py`: analyzer loop, 10 s cycle.
- Analyzer queue, serialisation, lag metrics, scanner snapshot, peer thread pools: 5 s peer timeout, 20 s for heavy peers, so the peer set is nondeterministic.
- `signal_envelope.ModelSignal`.
- `liq_magnet_image`: Pillow rendering.
- `quality_digest`: report.

### `notifications/`
- Formatting and rendering functions.
- `sanitization`: redaction.
- `autodetect`: Telegram chat-ID discovery.
- `core`: rate limiter, routes, WhatsApp sender.
- `__init__`: re-exports.

### `utils/`
- `config`: env defaults.
- `market_hours`: §18.

---

## 20. Ideas that cannot be backtested on OHLC or exchange data

| Idea | Why |
|---|---|
| Hyperliquid liquidation clusters, liq-magnet, level_reaction liquidation levels and meta-extra | Wallet `liquidationPx` snapshots are not archived; the collection is upserted with no history. |
| Realized liquidation fade (`liquidations` peer, C3) | Needs a liquidation tape. The HLP feed is dry; the Bybit path mislabels trades; Binance has no bulk history. |
| `tape` peer, MEXC flow layer (exact) | Needs aggressor trades. Approximate with Binance aggTrades or klines taker-buy volume. Pump-scanner selection bias cannot be reproduced. |
| Deriv tick-up ratio, tick-confirm, `tick_order_flow` | Need ticks. Tick-confirm is dead anyway. |
| crypto_alpha listings and market-funding cross-section | MEXC listing times and universe-wide funding history are not archived. Binance/Bybit funding is an approximation. |
| defi_alpha TVL/FDV/mcap/DEX, B5 | mcap/FDV/DEX history is not freely available. DefiLlama TVL history is. |
| CoinGecko sectors and laggards, payment-coin rotation | Category history is not archived. |
| CRYPTOCAP indices (A5, A6) | TradingView-only. Rebuild from exchange data plus supply, or use TradingView history. ETHBTC is clean. |
| Event gate, TradingView calendar | Need a historical point-in-time economic calendar. |
| FastBull positioning, correlation, news; TradingView news | Live-only, no archive. |
| Whale transfers (B3), ETF flows (B2) | On-chain data, or a separate Farside scrape. Not this code. |
| FX and gold macro leans (A3, A4 lean part) | Testable only with vintage (ALFRED) or lag-shifted macro data, and COT with a 3-day release lag. The A4 *stance* is clean. |
| kNN in-context blend, Kelly calibration, peer-outcome gate, sweep ETA, golden/OB zones, sweep-behaviour stats, MTF primary path (stored `analytics_results`), leader bias (`active_signals` composite) | DB- or path-dependent. Reproducible only by simulating the whole pipeline walk-forward. |
| Notifier runtime artefacts (per-user cap, global rate limit, chat allowlists, 180 s rollup delay, stale-feed guard) | No bar equivalent, beyond the approximations in §16. |

---

## 21. Lookahead, repaint and tuning checklist

### Centred or future-confirmed pivots
These must be lagged in any vectorised backtest:

| Source | Lag |
|---|---|
| Bjorgum (left 20 / right 15) | 15 bars |
| AME wick swings ±10, close swings ±5 | 10 / 5 bars |
| SMC swings ±5 | 5 bars |
| Structure / usd-commodity fractals w=3 | 3 bars |
| Triangle extrema ±3 | 3 bars |
| `key_levels` k=2 | 2 bars |
| FPC pivots | window-dependent |
| `pivots.detect_pivots_atr_scaled` | uses future closes (label only) |

### Other sources of lookahead or repaint
- **End-of-sample values reused historically:** SMC order-block ATR; Ising χ z; OI z; funding percentile (includes the current value); `level_fatigue` and AME fatigue over the whole passed series. Fix the window at 300 bars to match production.
- **Forming bar:** live analyses, the pump scanners and HTF context/level reads all include the unfinished bar. Use closed bars and next-open entry. Rebuild calendar-aligned higher timeframes; do not use the resampler.
- **Future-label tools:** `label_post_sweep`, `mine_historical_sweeps`, CISD qualification (8 bars after the pivot), and stored outcome stats.
- **Repeating states:** CUSUM, undervalued_vs_tvl, crypto-macro triggers, accumulation and the market-scanner gates fire on every bar while true. Take the first bar, or use the notifier's rising-edge rule (§16).

### Hand-tuned or in-sample constants to treat with suspicion
- **AME:** inverted direction (t=2.28 on n=512); 8% accumulation width; 0.002 / 1.003 / 0.62–0.79 sweep tolerances.
- **Setup:** TAKE at 65 with R:R 1.75 / 1.3; stop 1·ATR, TP 1/2/3·ATR.
- **level_reaction:** grade confidences 72 / 90 / 96; stop 0.5·ATR; Kelly priors; sweep-entry multipliers (fitted on 343 setups).
- **Breakouts:** cooking 0.5·ATR / 10 bars.
- **Proximity:** 0.5·ATR band, base 50, +15/+12/+8/+20.
- **ZMA:** P85/P65; VR 1.05.
- **Crypto and flow:** funding P5/P95 (one day of data); squeeze APR ≤ −100 (anecdote); rug parameters (one token); divergence z 1.5 / K 5 (in-sample, 140 coins); pump thresholds (several lowered after non-firing).
- **Collectors and notifier:** regime cut-offs 0.8/0.3/0.4/0.2; VIX RF hyperparameters; gold stance lookbacks; notifier floors 60/45/70; ±15% funding APR; rollup 180 s.
