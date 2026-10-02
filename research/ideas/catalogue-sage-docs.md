# Catalogue of testable trading ideas in `the source docs`

Source dir: the source (39 files, all read; nothing modified).

Conventions used below:
- **Side**: L = long, S = short, B = both (mirror).
- **Data**: OHLC, OHLCV (needs volume), FUND (funding), OI, DOM (BTC.D/ETH.D/TOTAL/TOTAL2/TOTAL3/TOTALDEFI/ETHBTC), or OTHER.
- **"Doc result"**: what the docs report. Internal names in backticks (for example `factor_zoo_ta`) are memory-bank or lab study names that the docs cite. Their raw data is not in these docs.
- **Default** is my most faithful resolution where the doc does not specify something.
- Common primitives used throughout, so they are defined once:
  - **ATR**: length is not specified anywhere. Default Wilder ATR(14). proximity.md says it "returns neutral when df shorter than 14 bars", which supports 14.
  - **Pivot high/low** (shared with bjorgum, SMC_MENTORSHIP_REVIEW): bar *i* is a pivot high if its high is strictly greater than the highs of the `left` bars before it, and ≥ (or >) the `right` bars after it. The doc says the bars to the left must be **strictly lower**, so a flat top reports only once. The pivot is confirmed only `right` bars later, so there is **no lookahead** before confirmation. Default left = right = 5 (`SAGE_SMC_SWING=5`, `SMC_SWING_WINDOW=5`).

---

## 1. SMC / ICT

### 1.1 `smc-bos-fvg`: BOS with a same-direction FVG
- **Source**: smc.md
- **Rule**:
  - **BOS up**: close > the most recent confirmed swing high (pivot window 5).
  - **FVG** (3-candle imbalance): bullish if low[c3] > high[c1]. Gap size must be ≥ `SMC_FVG_MIN_ATR_FRACTION` = 0.3 × ATR. The FVG must be unmitigated (no later wick has traded back into it).
  - **Entry**: BOS up AND a bullish FVG formed within the last 3 bars → BUY. Mirror for SELL.
  - Confidence base 70.
- **Stop/target**: not given in smc.md.
  - Default A: stop beyond the FVG's far edge or the broken swing, with a 1.5 ATR symmetric barrier.
  - Default B: the flywheel's default symmetric ±1.5 ATR triple barrier (`PEER_OC_BARRIER_ATR`).
- **Timeframes**: 15m–1d. **Instruments**: crypto (BTC examples), FX.
- **Doc result**: the whole SMC/ICT family is "killed" (`smc_ict_crt_exhausted`: "all forms negative under a proper harness").
- **Data**: OHLC.
- **Ambiguities**:
  - "within last 3 bars" means FVG middle candle index ≥ t−3.
  - Whether the reasoning string's "retest" (entry on a retest into the FVG) is required. Default: test both variants, (a) market entry at the BOS close and (b) a limit at the FVG top.

### 1.2 `smc-choch`: change of character
- **Source**: smc.md, PRICE_ACTION_SIGNIFICANCE.md
- **Rule**:
  - After an established downtrend (LH/LL pivot sequence), the first close above the last lower high → BUY (base 65). Mirror for SELL.
  - PRICE_ACTION_SIGNIFICANCE defines it as "first HL broken in an uptrend" warning of reversal.
- **Data**: OHLC.
- **Ambiguities**: "established trend" is undefined. Default: at least 2 consecutive LH and LL pivots (pivot window 5).

### 1.3 `smc-liquidity-sweep`: equal-high/low stop hunt
- **Source**: smc.md, PRICE_ACTION_SIGNIFICANCE.md (Tier 1 #3), bjorgum `_false_break`
- **Rule**:
  - A recent equal-low cluster is taken by a wick (low < cluster), then the bar closes back above it ("reverse close") → BUY (base 70). Mirror for SELL.
  - PRICE_ACTION_SIGNIFICANCE requires a confirming snap-back candle at a real level. Its warning: do NOT naive-fade breaks (`pump_fade_falsified`: "most pokes CONTINUE").
- **Doc result**: `liquidity_sweep_predictor`, 73k ranges over 2 years. Direction accuracy 50.7%, **−6.2 bp/alert net**, OOS decay 0.546→0.513. Reported as killed.
- **Data**: OHLC. smc.md says the sweep detector "also reads volume" (exact use not given).
- **Ambiguities**:
  - Equal-high/low tolerance is not given. joshyattridge's `liquidity()` uses `range_percent`. Default: pivots within 0.1 × ATR of each other, at least 2 touches, lookback 50 bars.
  - Reversal window: `reversed_after_n_bars`. Default: same-bar close back inside, with a variant allowing ≤ 3 bars.

### 1.4 `smc-ob-retest`: order block retest with a candle
- **Source**: smc.md, SMC_MENTORSHIP_REVIEW.md (video 4)
- **Rule**:
  - OB = the last opposite-direction candle before an aggressive impulse. Bullish OB = the last bearish candle before an up impulse.
  - The live implementation is "ATR-impulse, no volume". Impulse default: the next bar's body > 1.5 × ATR (matches the impulse utility). Zone = that candle's [low, high].
  - Entry when price retests the zone and prints a hammer or bullish engulfing → BUY (base 75). Mirror: shooting star / bearish engulfing → SELL.
  - Mitigation = a wick touch (the looser reading). The `close_mitigation` variant is from joshyattridge.
- **Doc result**: OB is "killed" (`factor_zoo_ta` 0/120 survive FDR+DSR; `price_geometry_edges_exhausted`).
- **Data**: OHLC. A volume-strength variant is optional.

### 1.5 `smc-hidden-sd`: hidden supply/demand zones
- **Source**: smc.md
- **Rule**: an institutional accumulation/distribution zone marked by a **volume spike + tight range**. "Price approaching bullish hidden demand zone" → BUY (60). Mirror for SELL.
- **Data**: OHLCV.
- **Ambiguities**: the thresholds are not given. Default:
  - volume ≥ 2× SMA20(volume) and range ≤ 0.5 × ATR on the same bar;
  - zone = that bar's range;
  - "approaching" = within 0.5 × ATR (the proximity default).

### 1.6 `smc-confluence`: combined score
- **Source**: smc.md
- **Rule**: 2+ of the recipes above fire in the same direction → confidence +5 per extra alignment, cap 90. A BOS alone gives no direction.
- **Test**: whether a stack of ≥ 2 recipes beats single recipes.

### 1.7 `cisd`: change in state of delivery
- **Sources**: CISD.md, SMC_ICT_RESEARCH.md (D), SAGE_QUALITY_ROADMAP.md, ame.md
- **Rule (support / bull flip)**:
  1. A level price L is given (a support level).
  2. Search the last `lookback=10` bars (excluding the confirm bar) for the **last delivery leg** into the level's extreme: a run of ≥ `min_leg=2` **consecutive down candles** (close < open).
  3. The leg's extreme (its low) must be within `near_atr=1.5` × ATR of L.
  4. **CISD line = the OPEN of the first candle of that leg.**
  5. Trigger: the latest candle **CLOSES above** the line (wicks don't count) → BUY.
  - Mirror (resistance): up-candle leg into the high; a close below the first candle's open → SELL.
- **Intended test**: "Does a `swept + CISD-close` setup beat `swept` alone on realized, forward-walked outcomes?" CISD overlaps `impulse_origin`, so measure its **marginal** edge.
- **Stop/target**: not given. Default: stop beyond the leg extreme (+0.5 ATR buffer), target 1.5 ATR symmetric or 2R/3R.
- **Doc result**: none. It is "instrumented, untrusted".
- **Data**: OHLC.
- **Ambiguities**: CISD needs a level. Default: use a bjorgum pivot zone (§2.1) or a swept prior swing. A standalone variant uses the nearest pivot low/high within 1.5 ATR.

### 1.8 `structural-setup`: the full mentorship method priced in advance
- **Sources**: SMC_MENTORSHIP_REVIEW.md (videos 1–5, 7, 8), SMC_MENTORSHIP_RESULTS.md, ENV_VARS.md (structural_setup + SMC sections), SYMMETRY_RESEARCH.md
- **Rule (long; mirror for short)**:
  1. **Sweep**: a swing low (pivot len 5) wicks below a prior swing low and the bar rejects (closes back above it). That swept low becomes the **protected low**. A low that was not swept is not protected.
  2. **Break**: a later close above the prior swing high → bullish swing structure. It must be the **major** break (see §1.10). The live implementation approximates this with pivot length only.
  3. **Structural liquidity (trigger)**: the last swing low between the protected low and the BOS. It is found with a pivot length of half the swing (5/2 → 2 or 3).
     - Validity (a), proximity: it must sit at or below the 50% Fib of the leg from the BOS high to the protected low (`MIN_DEPTH` = 0.5, measured from the BOS high).
     - Validity (b), shape: an "obvious multi-candle A/V". Implemented as `_shaped()` = a spike-share test plus PIPs `prominence()` (perpendicular distance from the chord through the neighbourhood). `MAX_SPIKE_SHARE` is not given. Default: no single bar contributes > 50% of the swing's depth, and the swing has ≥ 3 bars on each side.
  4. **Inducement veto** (`SAGE_SMC_INDUCEMENT=1`): if no structural low exists, skip. The protected low will be re-swept.
  5. **POI**: the QMR (an order block that price swept on its way out, i.e. a "failed" OB = breaker) if it sits above the structural liquidity and in the discount half. Otherwise use the next unmitigated OB up. Each candidate is measured at the zone's middle.
  6. **Context** (`SAGE_SMC_CONTEXT=1`): on the **next higher timeframe**, anchor a Fib to the last major break leg (high to low). Buys only in the discount half (below 50%), sells only in premium. The doc measured that reading this on the same TF mutes the signal (it fired 10.5% → 0.2% on random walks; HTF reading 5.8%).
  7. **Entry**: a limit at the POI. Price must come within `SAGE_SETUP_TOLERANCE=0.5` ATR of the zone.
  8. **Stop**: `SAGE_SETUP_STOP=0.5` ATR beyond the **protected swing**, scaled by `stop_tilt` (§2.17).
  9. **Target**: fixed `SAGE_SETUP_REWARD=3.0` R.
  10. **Freshness**: the break stays tradeable for 3 × swing length = 15 bars.
  - Optional backing: a bjorgum pivot zone within 1.0 ATR of the entry (`SAGE_SETUP_LEVELS_WITHIN`).
- **Timeframes**: source used 1H–weekly. Live: 1h/4h/1d/1w. **Instruments**: FX in the source (GBPUSD, AUDUSD, EURGBP, AUDCHF, EURCAD, DAX). Live: all.
- **Doc results**:
  - Source claims "80%+ on publicly-posted setups since February" at 1:3, self-reported and unaudited.
  - Random-walk firing: 10.5% without vetoes, about 5.8% with both.
  - "Fires once a week". No real-chart outcomes yet.
- **Data**: OHLC (two timeframes).
- **Ambiguities**:
  - Which swing low counts as "prior" for the sweep. Default: the most recent confirmed pivot low before the sweep bar.
  - "Rejects" = closes back above the swept low on the same bar.
  - The QMR "swept on its way out" means an OB whose low was wicked by the sweep leg.

### 1.9 `inducement-veto-filter`: the one researchable thread
- **Source**: SMC_MENTORSHIP_RESULTS.md
- **Rule (filter on an existing swept-level setup)**:
  - `has_structural_liq` (bool): between the protected low and the BOS there is an intervening swing low that (i) sits at ≤ 50% of the break-to-low Fib and (ii) is an A/V with a pivot width of ≥ 3 candles on each side ("*our* threshold").
  - `struct_liq_depth_pct`: where it sits in the leg, 0–100%, as a continuous feature.
  - Hypothesis: setups with `true` have a higher "swept-then-continuation" rate and net R than `false` setups.
- **Test design given**: about 25–40 resolved rows per class, then a daily-portfolio test plus permutation. "pooled significance does not count".
- **Doc result**: #50 backfill, 782 resolved level setups. **28% of losses were swept-then-reversed** (direction right, stop hunted). Prior stated as LOW.
- **Data**: OHLC.

### 1.10 `major-vs-minor-bos`
- **Source**: SMC_MENTORSHIP_REVIEW.md (video 5)
- **Rule**:
  - In a bearish sequence, structure turns bullish only when price closes above the **previous lower high**, i.e. the last pivot high that made a lower high. Breaking any later minor high is a "minor break" that is often liquidity to reach the LH and then sell.
  - Testable as: (a) minor break → short at the prior LH (scalp fade); (b) major break → long continuation. Compare the two.
- **Doc result**: "major-vs-minor BOS as direction" is killed (`smc_ict_crt_exhausted`). Not built.
- **Data**: OHLC.

### 1.11 `premium-discount-filter` (HTF)
- **Sources**: SMC_MENTORSHIP_REVIEW.md (videos 7–8), ENV_VARS.md
- **Rule**:
  - HTF Fib anchored to the last major break leg. Buys only if price < 50%, sells only if > 50%.
  - A second pass one TF higher still (e.g. weekly) checks for a reaction off an HTF wick/OB; it is used to size up.
- **Doc result**: `smc_premium_discount_exhausted` — "no MR edge survives full history + costs + GBM null". The source's anecdote: the same 1H pattern failed in 4H premium and worked in 4H discount.
- **Data**: OHLC (two timeframes).

### 1.12 `qmr-vs-ob`
- **Source**: SMC_MENTORSHIP_REVIEW.md
- **Rule**: compare entries at a QMR (an OB that was swept, i.e. a breaker block) against an untouched OB. The live rule is "a swept block beats an untouched one".
- **Data**: OHLC.

### 1.13 `formation-type`
- **Source**: SMC_MENTORSHIP_REVIEW.md
- **Rule**:
  - Type 1 = sweep → break → break (two same-way breaks; structural liquidity after the 2nd break).
  - Type 2 = sweep → low → break (structural low forms before the break).
  - Type 3 = structure exists but the structural low has not printed yet → wait.
- Descriptive only. Test whether outcomes differ by type.
- **Data**: OHLC.

### 1.14 `transactional-liquidity-correction`
- **Source**: SMC_MENTORSHIP_REVIEW.md
- **Rule**: once the BOS takes the prior swing high (transactional liquidity), expect a pullback into the zone. Testable as P(retrace to the 50%/discount zone within N bars after a BOS). Not built.
- **Data**: OHLC. Default N = 20 bars.

### 1.15 `confirmation-entry-ltf`
- **Source**: SMC_MENTORSHIP_REVIEW.md
- **Rule**: when an HTF POI is marked but has no structural liquidity, wait for price to tap the POI, then re-run the full sweep → break → structural liquidity → POI checklist one timeframe down (for example 4h POI → 1h). Not built.
- **Data**: OHLC (two timeframes).

### 1.16 `ob-derivatives`: breaker, mitigation, propulsion, IFVG, BPR, unicorn
- **Source**: SMC_ICT_RESEARCH.md (A)
- **Definitions**:
  - Breaker = an OB that price broke through, traded from the other side.
  - Mitigation block = an old OB retested, traded as continuation.
  - Propulsion = an OB inside another OB.
  - IFVG = an FVG that price closed through, traded inverted.
  - BPR = two overlapping opposing FVGs.
  - Unicorn = an FVG overlapping a breaker.
- **Verdict**: "do not build" (same primitive as `factor_zoo_ta`). Listed because each can be coded.
- **Data**: OHLC.

### 1.17 `ame-liquidity-patterns`: 13 sweep patterns
- **Source**: ame.md
- **Named only**: single_bar, two/three_candle, equal_lows/highs, pin_bar, prev_candle_raid, judas_swing, stop_hunt_reversal, breaker_block, volume_imbalance, turtle_soup, mitigation_block, ote_fib.
- **Defaults** (no parameters are given in the docs):
  - turtle_soup: a new 20-bar low, then a close back above the prior 20-bar low within 1–3 bars.
  - prev_candle_raid: low < prior bar low, close > prior bar low.
  - judas_swing: the session-open move fades (see §7.1).
  - ote_fib: entry in the 0.62–0.79 retracement.
- **Data**: OHLC, plus OHLCV for volume_imbalance.

### 1.18 `ame-phases`: Accumulation → Manipulation → Expansion
- **Sources**: ame.md, breakouts.md, decision.md
- **Rule**:
  1. **Accumulation range**: choose a support/resistance pair from bjorgum zones with sup.top < price < res.bottom.
     - inside_pct = share of closes inside [sup.top, res.bottom] over the window, must be > 0.6.
     - bars_inside ≥ 8 (5 after a BOCPD low-vol changepoint).
     - Pick the pair with the highest inside_pct, ties to the narrower pair.
     - Statistical-only fallback: a rolling box with width < 8% (`AME_ACCUM_MAX_WIDTH_PCT`).
     - Strength: structural+statistical = strong, structural = moderate, statistical = weak.
  2. **Manipulation**: a sweep beyond one edge of the range (one of the patterns in §1.17), then a reversal.
  3. **Expansion**: direction fires only when the sweep is followed by impulse follow-through in the **opposite** direction to the sweep (`_expansion_fires`).
- Precursors: volatility_compression, pool_exhaustion, sweep_eta. `predict_sweep_side` is an 8-factor heuristic whose factors are not listed.
- **Doc result**: "structural phase (AME's reading)" is a measured null (`price_geometry_edges_exhausted`).
- **Data**: OHLC. A BOCPD variant is optional.
- **Ambiguities**:
  - The range window is not given. Default: the last 20 bars (`SAGE_SETUP_RANGE_LOOKBACK=20`).
  - "Impulse follow-through": default is a bar with body > 1.5 × ATR closing back inside, then beyond the opposite edge, within 10 bars.

### 1.19 `crt`: candle range theory, two-bar state
- **Sources**: ENV_VARS.md, toolbox.md, SMC_MENTORSHIP_REVIEW.md
- **Rule**: classify each bar relative to the previous bar's range. It is "exhaustive — every bar lands in exactly one state". Default states: inside; outside; swept the high and closed back inside (bearish); swept the low and closed back inside (bullish); broke and closed above; broke and closed below.
- **Doc result**: measured null (`smc_ict_crt_exhausted`).
- **Data**: OHLC.

### 1.20 `impulse-candle` / displacement
- **Sources**: engine.md, PRICE_ACTION_SIGNIFICANCE.md, SAGE_QUALITY_ROADMAP.md, proximity.md
- **Rule**: body > 1.5 × ATR AND tight (one-sided) wicks AND volume > 1.5 × SMA(volume).
  - Uses: `impulse_origin` flag at a level; `_cisd_impulse_setup` (CISD flip + a recent impulse in the predicted direction).
  - proximity bonuses for impulse zones: +8 if body ≥ 3 × ATR, +4 if ≥ 2 × ATR.
- **Data**: OHLCV.
- **Ambiguities**:
  - "Tight wicks" default: the opposite wick < 25% of the range.
  - The volume SMA length defaults to 20.

### 1.21 `impulse-zones`: supply/demand from past impulse bars
- **Sources**: ame.md, proximity.md
- **Rule**: an impulse bar's range defines an unmitigated zone. A first return to it is a reaction entry: BUY at a demand zone, with "price ≥ zone bottom − 0.1 ATR" as not yet broken. The zone becomes mitigated once price trades into it.
- **Data**: OHLCV.

### 1.22 `sweep-overshoot-stops`: stop-placement calibration
- **Source**: deferred.md
- **Finding** (440 resolved level outcomes over 9 days):
  - Overshoot beyond a level: the median stops at about 1.5 × ATR, and 4 × ATR covers only 70%.
  - In 19% of cases price never reaches the level.
  - CV 2.17, mean about 4× the median.
  - No estimator beats the constant (MAE 3.93 vs 3.89 oracle).
  - Stop buffer = reach + 0.5 × vol (flat coefficient, uncalibrated).
- **Test**: the stop-buffer coefficient per instrument class.
- **Data**: OHLC.

### 1.23 `ten-trades-sizing` (money management, not a signal)
- **Source**: SMC_MENTORSHIP_REVIEW.md (video 6)
- **Rule**: risk per trade = max drawdown / 10, fixed. Never reduce size after losses. Fixed 1:3 R. Stop and review after 9–10 consecutive losses.
- **Doc**: rejected; contradicts `risk_engine_doctrine`.
- Testable as a sizing overlay against equity-scaled de-risking on any strategy.

---

## 2. Key levels / price geometry / symmetry

### 2.1 `bjorgum-pivot-zones`
- **Sources**: bjorgum.md, KEY_LEVELS_RESEARCH.md, proximity.md
- **Rule**:
  - For each confirmed pivot: band = min(ATR(atr_len) × mult, close × per_max%) / 2, with mult = 0.015 and per_max = 5%. Zone = [pivot − band, pivot + band], which is close to a line.
  - Keep the n_piv = 10 most recent zones per side.
  - **Role flip**: when price closes through a zone, a support becomes resistance and vice versa. `flipped = original role ≠ current role`. `flip_count` is tracked. Flipped zones are claimed to be "stronger".
  - Nearest support = the closest support zone whose bottom < price (use its bottom). Nearest resistance = the closest resistance zone whose top > price (use its top).
  - Pine-default variant: mult = 0.5 with Heikin-Ashi source.
- **Data**: OHLC.
- **Ambiguities**:
  - left/right/atr_len are not given. Default: 5/5 and ATR 14.
  - Close-through vs wick flip: default close-through.

### 2.2 `bjorgum-flags`: directional detectors
- **Source**: bjorgum.md
- **Flags**: breakout, breakdown, break_up, break_dn, false_break_bull/bear, sup_push, res_push, curl_bull/bear (TSI curl), plus candle patterns.
- **Defaults** (definitions are not given):
  - breakout / res_break: close > the top of the nearest resistance zone.
  - false_break_bull: low < support bottom, close > support top.
  - sup_push: a bounce candle closing up from inside a support zone.
  - TSI: (25, 13) with signal 13. `curl_bull` = TSI turns up (TSI[t] > TSI[t−1] < TSI[t−2]) below zero, or crosses its signal line.
- **Data**: OHLC.

### 2.3 `candle-patterns-at-level`: level-reaction confirmation
- **Sources**: coverage.md, PRICE_ACTION_SIGNIFICANCE.md, KEY_LEVELS_RESEARCH.md (Phase 3), bjorgum.md
- **Patterns**:
  - Bullish: hammer, bullish engulfing, tweezer bottom, piercing, dragonfly.
  - Bearish: shooting star, bearish engulfing, tweezer top, gravestone (also dark cloud).
  - Neutral: doji, spinning top.
  - Also harami, long_upper/lower shadow.
- **Rule**: the bar touches a level (support for longs) AND prints a pattern in the reaction direction. `Patterns.lean` gives a direction only if all shapes on the bar agree; mixed shapes = unconfirmed. Indecision candles are excluded.
- Significance order claimed: sweep > engulfing/outside bar > pin/rejection wick > two-bar reversals.
- **Data**: OHLC.
- **Ambiguities**: pattern geometry thresholds are not given. Default: hammer = lower wick ≥ 2 × body and upper wick ≤ 0.25 × range; engulfing = body engulfs the prior body.

### 2.4 `level-reaction-grade`: the S/A+/A/B+ ladder
- **Sources**: coverage.md (newest, ported), PRICE_ACTION_SIGNIFICANCE.md (older), ENV_VARS.md
- **Rule (coverage.md)**: requires a confirmed candle at the level.
  - S: swept AND ≥ 3 higher TFs carry a level at the same price.
  - A+: swept and 2 HTFs.
  - A: swept and 1 HTF.
  - B+: not swept and ≥ 1 HTF.
  - 0 HTF = nothing. No candle = nothing.
  - On the top collected TF, a swept reaction is credited once (reaches A at most).
  - "Swept" = poked through the level and closed back inside (`detect_sweep`, wrapping `_false_break`).
  - HTF agreement = an HTF bjorgum zone at that price. Look only upward (1h → 4h, 1d, 1w).
- **Older ladder (PRICE_ACTION_SIGNIFICANCE)**: S = sweep + 2+ HTF; A+ = sweep + ≥ 1 HTF; A = sweep only; B+ = candle + ≥ 1 HTF; B = candle only. ENV_VARS: "Grades are B+/A+/S only".
  - **Ambiguity**: the ladders conflict. Default to coverage.md and test both.
- **Stop/target**: R:R comes from the level structure (not detailed). Default: stop past the sweep extreme + 0.5 × ATR, target the next opposite zone. Variant: the symmetric 1.5 ATR barrier.
- **Timeframes**: 1h/4h/1d/1w. **Instruments**: all. A cost gate kills FX/commodity setups with net R:R < 1.0 after spread.
- **Doc result**: "fifty-six [S] went out in a day" under the old ladder (too common). No win rates given.
- **Data**: OHLC (multiple timeframes).

### 2.5 `regime-veto-adx`
- **Sources**: SAGE_QUALITY_ROADMAP.md, ENV_VARS.md
- **Rule**: a Wilder ADX/DI trend tag. ADX > 28 = strong trend. A level reaction against a strong trend (buying support with −DI > +DI and ADX > 28, or the mirror) is downgraded one rung, floored at B+, never removed. Bypassed if swept and structure-aligned.
- **Test**: do counter-trend reactions lose?
- **Data**: OHLC. Default ADX length 14.

### 2.6 `meta-confluence-grade`
- **Sources**: SAGE_QUALITY_ROADMAP.md, ENV_VARS.md
- **Rule**: count independent directional confluences:
  - structure-aligned (MSS/trend agrees);
  - USD or commodity complex agrees (§4.4, §4.5);
  - the level is a liquidation-cluster magnet;
  - funding crowded in the trade-supporting direction;
  - `at_ma` (§2.7).
  - ≥ `META_PROMOTE_N` = 2 → A+ promoted to S. A lone A+/S (no extras, no sweep) is demoted.
- **Data**: OHLC plus FUND, and liquidations for one component.

### 2.7 `ma-levels`
- **Source**: ENV_VARS.md (`LEVEL_MA_LEVELS`)
- **Rule**: treat 200-week SMA, 200-day SMA and 50-day SMA as key levels. Claim: "200W has marked real bear bottoms". Reaction at the MA, plus the candle-confirmation rule.
- **Data**: OHLC (1d/1w). SMA vs EMA is not given; default SMA.

### 2.8 `level-hold-stats` / zone reliability (Phase 1 harness)
- **Source**: KEY_LEVELS_RESEARCH.md
- **Rule**: for each zone:
  - on first touch, P(hold/reject) vs P(break);
  - average excursion after the touch;
  - decay with touch count (fatigue) and zone age.
  - Compare against GBM random-walk and circular-shift nulls.
  - Score = hold rate × freshness × strength. Alert only on the top-reliability zones.
- **Expectation stated**: raw reaction ~ null; the gain is from ranking.
- **Data**: OHLC.
- **Ambiguities**: hold/break definitions are not given. Default: hold = price moves 1 ATR away in the reaction direction before closing 0.5 ATR through.

### 2.9 `level-fatigue`
- **Source**: KEY_LEVELS_RESEARCH.md
- **Rule**: down-weight levels by touch count. A 4th touch is "near exhaustion"; fresh untested levels are "prime".
- **Data**: OHLC.

### 2.10 `level-types-enrichment`
- **Source**: PRICE_ACTION_SIGNIFICANCE.md (Tier 1 #2)
- **Significance ranking claimed**: prior swing H/L > prior day/week/month H/L > round/psychological numbers > session opens > VWAP/value area (POC/VAH/VAL).
- Weight rises with touches, timeframe, recency, and confluence (several types at one price).
- **Test**: reaction rates by level type, and stacking.
- **Data**: OHLC; OHLCV for VWAP/VP.
- **Ambiguity**: round-number granularity. Default: a price-scaled grid (e.g. 00/50 pips in FX, $1000 for BTC).

### 2.11 `momentum-volume-modifiers`
- **Source**: PRICE_ACTION_SIGNIFICANCE.md (Tier 3)
- **Modifiers**:
  - (a) TSI divergence at a level (price makes a new extreme, TSI does not).
  - (b) Volume z on the confirmation bar.
  - (c) Wide-range/climactic bar plus volume: a thrust confirms a break; a climactic bar *into* a level means exhaustion.
  - (d) Compression/inside bars precede expansion (readiness, no direction).
- **Data**: OHLCV.

### 2.12 `confluence-flags-at-level`
- **Sources**: PRICE_ACTION_SIGNIFICANCE.md, SAGE_QUALITY_ROADMAP.md
- **Flags**:
  - `impulse_origin`: an impulse candle at the level.
  - `fvg_confluence`: an unmitigated FVG at or near the level.
  - `vol_regime`: ATR percentile expansion vs contraction.
- **Hypotheses**:
  - levels hold in low-vol ranges and break in high-vol trends;
  - a sweep during vol expansion favours continuation over reversal.
- **Test**: same grade with vs without the flag, against a label-shuffle null plus costs.
- **Data**: OHLCV.

### 2.13 `retest-pullback-tier`
- **Source**: PRICE_ACTION_SIGNIFICANCE.md (task #30). Off by default (`LEVEL_RETEST_ENABLED=false`).
- **Rule**: after the first move away from a held level, enter on the pullback back to it. Break-and-retest: old resistance becomes new support. Tighter stop, so better R:R.
- **Data**: OHLC.

### 2.14 `proximity-score`
- **Sources**: proximity.md, engine.md
- **Rule**:
  - Levels: bjorgum S/R, AME impulse zones, CISD reversal zones, LTF and HTF.
  - In play if within 0.5 × ATR, on the correct side.
  - Confidence per level:
    - bjorgum base 50, +10 + 5·(flips − 1) if flipped, +15·(1 − dist/band);
    - pattern boost LTF min(20, 8·n) (patterns ≤ 3 bars old), HTF min(30, 15·n) (≤ 5 HTF bars);
    - HTF level +12;
    - volume z vs the prior 29 bars: ≥ 2 gives +12, ≥ 1 gives +6;
    - confluence of distinct kind families: 2 gives +10, 3+ gives +20;
    - cap 95.
  - Direction = majority count of aligned levels (tie = none). Confidence = mean of aligned levels, minimum 40.
- **Doc**: always assumes rejection, never a sweep-through.
- **Data**: OHLCV (multiple timeframes).

### 2.15 `fpc-fractal-pivot-counter`
- **Source**: KEY_LEVELS_RESEARCH.md
- **Rule**: swing-cycle exhaustion plus measured-move targets of 1:1, 0.618 and 1.618 of the prior swing.
- Exhaustion count is not defined. Default: count consecutive same-direction pivot legs; exhaustion at ≥ 5 (Elliott-like).
- **Data**: OHLC.

### 2.16 `volume-profile-nodes`
- **Sources**: PRICE_GEOMETRY_RESEARCH.md, ENV_VARS.md, fastbull_collector.md, fastbull_api.md, ame.md (pullback_detector)
- **Rule**:
  - Bin typical price (h+l+c)/3 over a lookback into N = 100 bins, assigning each bar's volume.
  - POC = the maximum bin. Value area = the contiguous 70% around POC (VAH/VAL).
  - HVN = bins ≥ 1.5 × mean. LVN = bins ≤ 0.4 × mean, non-zero.
  - Record whether the entry sits on an HVN, LVN, mid, or outside; whether it is inside the VA; and the distance to POC in ATR.
  - **Hypothesis**: setups at HVNs resolve differently from LVNs. Claimed to be "the remaining gap". Never tested.
  - Also VWAP plus bands, and VAH/VAL tails as S/R.
- **Data**: OHLCV. FX volume is tick count, so split by `volume_source`.
- **Ambiguity**: `LOOKBACK` is not given. Default: session range (fastbull) or 100 bars.

### 2.17 `asymmetric-stop-tilt`
- **Sources**: ENV_VARS.md, SYMMETRY_RESEARCH.md
- **Rule**:
  - Over the last 100 bars, take the mean upward reach (high − prev close) and the mean downward reach (prev close − low).
  - stop_tilt = adverse reach / mean of both reaches (centred on 1.0), clamped to 0.6–1.8.
  - Multiply the stop buffer by it.
- **Data**: OHLC.
- **Ambiguity**: the exact normalisation. Default as above.

### 2.18 `zma-zscore-reversion`
- **Sources**: zma.md, toolbox.md, NOTIFICATION_FILTER.md, engine.md
- **Rule**:
  - z = (close − SMA20) / std20 (`ZMA_WINDOW=20`).
  - z > 2.0 → SELL; z < −2.0 → BUY. |z| ≥ 3.0 = STRONG.
  - **Target = the rolling mean; stop = 1σ beyond on the other side** (from toolbox.md), so R:R ≈ |z|.
  - Variants:
    - "Rally"/"Bounce": the z trigger plus a 3-bar reversal pattern.
    - "Dip"/"Decline": the z trigger inside an HTF uptrend/downtrend.
    - "STRONG": z extreme plus momentum aligned with the reversion direction.
  - Current guard: refuse reversion against a strong prevailing trend (`regime`), plus the Kelly no-edge gate.
- **Doc result (strong negative)**:
  - **17% win over 256 resolved**, average R:R 2.54, random-walk baseline 28%, **expectancy −0.40R**.
  - Shorts 142 at 11%, longs 114 at 25%.
  - The variance-ratio gate at 1.05 classified 39% of random walks as trending (null sd 0.28). An exponential ramp scores VR = 1.0.
  - Only 2 stopped setups later reached target.
- **Proposed improvements**: Kalman smoothing before z (validated as a technique elsewhere); use the nearest level (`latent`) as target instead of the mean; CRT "stretch stopped" confirmation.
- **Data**: OHLC.
- **Ambiguities**:
  - The "3-bar reversal" default: 2 bars in the trend direction, then a bar closing beyond the prior bar's open.
  - "HTF uptrend" default: next-TF close > SMA50.
  - "Momentum" default: the sign of z_accel.

### 2.19 `pullback-detector`
- **Sources**: ame.md, decision.md (`_pullback_primed_setup`)
- **Rule**: a retracement into confluence of Fib + EMA + VWAP + POC, entered on a directional bar.
- **Defaults** (none given): Fib 0.5–0.618 of the last swing, EMA21, session VWAP, 100-bar POC; at least 2 within 0.5 ATR.
- **Data**: OHLCV.

### 2.20 `one-source-ta-family` (listed as dead; testable)
- **Source**: PRICE_GEOMETRY_RESEARCH.md
- **Covers**: Bollinger, %B, Keltner, Donchian, envelopes; chart patterns; harmonics (Gartley/bat/butterfly); Gann; Elliott (not falsifiable); pivots, Fibonacci, trendlines.
- **Doc result**: `factor_zoo_ta` — 40 variants × 3 timeframes on Bybit perps, FDR+DSR, **0 of 120 survive**. Reversion is worst (RSI, CCI, %B, VWAP-reversion, pivots).
  - A follow-up asked whether indicator agreement improves an already-selected setup. It does not; on the short-fade sleeve it was mildly negative (deferred.md).
  - The 10 classic flags from deferred.md (EMA alignment, RSI, MACD, BB, CCI, VWAP, volume z, slope, candle reversal, round number) are not ported.
- BB width is only a volatility estimate ("ATR percentile with extra steps").
- **Data**: OHLC.

### 2.21 `event-time-bars`
- **Source**: PRICE_GEOMETRY_RESEARCH.md
- **Idea**: Renko, range, point-and-figure, volume or dollar bars as a sampling clock (closer to IID returns). Re-run estimators on them. "Genuinely open, and expensive."
- **Data**: OHLCV; ideally ticks.

### 2.22 `skew-conditioned-shorts`
- **Source**: SYMMETRY_RESEARCH.md
- **Rule**: compute the trailing realized skew per symbol. Hypothesis: shorts on right-skewed symbols resolve worse.
- Literature cited:
  - large caps are more left-skewed, small caps more right-skewed;
  - downside shocks are transitory, upside shocks persist;
  - higher average skew predicts lower future returns cross-sectionally.
- **Data**: OHLC. Default window 90 daily bars.

### 2.23 `leverage-effect` / gain-loss asymmetry (vol modelling)
- **Source**: SYMMETRY_RESEARCH.md
- **Testable**: GJR-GARCH/EGARCH asymmetry; time to −X% shorter than time to +X%; direction-split stop-hit rates for ATR stops.
- **Data**: OHLC.

### 2.24 `code-symmetry-test` (methodology)
- **Source**: SYMMETRY_RESEARCH.md
- **Rule**: mirror the chart by negating price and swapping high/low. Every detector must produce the same grade in the opposite direction. Assert a minimum firing rate (the first run fired 0 times on 400 walks and passed vacuously).
- Use as a unit test for every backtest signal.

---

## 3. Breakouts

### 3.1 `chart-pattern-breakouts`
- **Sources**: breakouts.md, NOTES.md
- **Rule** (pattern formation ≥ `BREAKOUTS_MIN_PATTERN_BARS`=15, last ~150 bars):
  - Ascending triangle break up → BUY; descending triangle break down → SELL. Volume on the break required.
  - Double bottom/top neckline break → BUY/SELL. A retest scores higher.
  - Bull/bear flag: impulse leg + flag consolidation + break.
  - Inverse H&S → BUY; H&S → SELL.
  - Cup-and-handle → BUY.
  - **Volume confirmation**: break-bar volume / SMA20(volume) ≥ 1.5.
  - **Retest**: within `BREAKOUTS_RETEST_BARS`=5 bars after the break, price returns to the level and rejects.
  - Live states: `cooking`, `retest_confirmed` (fire); `retest_pending`, `failed`.
- **Triangle measured move** (NOTES.md):
  - height = base height (intercept_hi − intercept_lo at the widest point);
  - target = break level ∓ height;
  - measured_rr = base height / current width;
  - triangles should break before the apex; coiling into the apex = downgrade.
- **Doc result**: chart patterns are killed (`factor_zoo_ta`, `price_geometry_edges_exhausted`). Measured target "NOT a validated edge".
- **Data**: OHLCV.
- **Ambiguities**: pattern geometry. Default: fit upper/lower lines through ≥ 2 pivots each (pivot 5). Asc = flat top (slope within 0.1 ATR per 10 bars) with a rising bottom. Stop = the opposite line at the break; target = measured move.

### 3.2 `level-break-volume`
- **Source**: breakouts.md
- **Rule**: close beyond a bjorgum pivot zone or an AME impulse zone with volume ≥ 1.5 × SMA20 → direction of the break. Optional retest/reject within 5 bars.
- **Data**: OHLCV.

### 3.3 `breakout-zone-setup` (composer primer #2)
- **Sources**: decision.md, breakouts.md
- **Rule**: `breakouts.recent_break` aligned with the nearest bjorgum **flipped** zone. Example: a break up through resistance that has flipped to support; buy the retest. Described as "the most common TAKE setup".
- **Data**: OHLCV.

### 3.4 `range-primed` and `breakout-primed` setups (composer)
- **Source**: decision.md
- **Rules**:
  - range_primed: AME accumulation range complete (§1.18) + ZMA directional signal at one edge (BUY at the bottom edge with z < −2).
  - breakout_primed: a clean break with volume confirmation.
- **Plan**: entry = current price; SL from `resolve_sl` (impulse-zone aware); TP ladder tp1/tp2/tp3 (unspecified).
- **TAKE gate**: conf ≥ 80 AND ≥ 1 agreeing peer AND RR(tp2) ≥ 2.0 (FX/crypto) or 1.5 (synthetics). WATCH if conf ≥ 60. USING_SIGNALS says CONFIRM is ~70 and RR ≥ 1.5 (conflicting).
- **Ambiguity**: TP ladder default 1R/2R/3R.
- **Data**: OHLCV.

### 3.5 `volatility-compression-precursor`
- **Sources**: ame.md, PRICE_ACTION_SIGNIFICANCE.md
- **Rule**: contracting range before expansion (readiness, no direction).
- Default: ATR(14) percentile over 100 bars < 20 → expect |next N-bar move| > baseline. Test as a volatility forecast, or as a filter for breakouts.
- **Data**: OHLC.

### 3.6 `quiet-regime-fakeout`
- **Source**: BTC_DOMINANCE.md
- **Claim**: in the quiet regime (§4.7), breakouts are likely fakeouts and scalps are chop.
- **Test**: breakout success rate conditional on the quiet flag.
- **Data**: DOM + OHLC.

---

## 4. Correlation / regime / crypto

### 4.1 `leader-bias`
- **Sources**: correlation.md, USING_SIGNALS.md, engine.md
- **Rule**:
  - Leaders by asset class: crypto BTC, ETH; FX DXY, EURUSD; commodities XAUUSD, USOIL; equities/indices SPX, NDX, VIX.
  - The leader's direction on the same TF (and the next HTF rung at 2× weight) comes from its own signal (ZMA/active signal).
  - verdict = aligned if the leaders agree with the trade, opposed if they disagree.
  - Confidence ×1.10 if aligned, ×0.85 if opposed. Usage advice: skip alt longs during BTC/ETH coordinated dumps.
- **Backtest**: filter any alt signal by the leaders' direction.
- **Data**: OHLC (multi-asset).
- **Ambiguity**: the leader "direction" depends on ZMA, which is a weak signal. Default alternative: leader trend = sign of (close − SMA20) or the 20-bar return sign.

### 4.2 `divergence-relative-weakness`
- **Sources**: ENV_VARS.md, SHORT_CANDIDATE_SPEC.md
- **Rule**:
  - Relative strength of a coin vs BTC/ETH: `DIVERGENCE_WINDOW`=30 bars, horizon `DIVERGENCE_K`=5, fire at |z| ≥ 1.5.
  - The short version requires a regression fit R² ≥ 0.3.
  - Negative divergence (coin underperforming) → SELL.
- **Doc result**: "G/H relative weakness — VALIDATED (persists 3-5d)".
- **Data**: OHLC (coin plus BTC/ETH).
- **Ambiguity**: exact construction. Default:
  - regress coin returns on BTC returns over 30 bars;
  - residual = coin's 5-bar return − β × BTC's 5-bar return;
  - z of that residual against its 30-bar history;
  - R² of the regression ≥ 0.3;
  - z ≤ −1.5 → short; hold 3–5 days.

### 4.3 `xsmom-majors`
- **Source**: SMC_ICT_RESEARCH.md
- **Rule**: cross-sectional momentum, market-neutral sleeve on majors. "Sharpe 1.69 net, needs forward-paper". Parameters are not given.
- Default: rank the universe on 7- or 30-day returns; long the top tercile, short the bottom tercile; rebalance weekly.
- **Data**: OHLC.

### 4.4 `usd-confluence`
- **Sources**: KEY_LEVELS_RESEARCH.md, ENV_VARS.md, deferred.md
- **Rule**: fire only when the USD complex coils at levels together. A major counts as at-level when ≥ 3 of 7 brokers agree on the same USD direction. With one source (the ported default) the cross-broker check is dropped.
- **Default operationalisation**: among EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF and NZDUSD, count the pairs at a bjorgum level within `USDCONF_NEAR_ATR` (not given; default 0.5 ATR) whose implied USD reaction direction agrees. Fire at ≥ `USDCONF_MIN_AT` (not given; default 3).
- **Data**: OHLC.

### 4.5 `commodity-confluence`
- **Source**: ENV_VARS.md
- **Rule**:
  - Gold, silver and copper; each "at level" within 0.6 × ATR of a level built from 120 bars.
  - Fire when ≥ 2 commodities agree on direction.
  - Gold alone qualifies (bellwether) unless another commodity conflicts.
- **Data**: OHLC.

### 4.6 `btcd-ethbtc-triggers`
- **Source**: BTC_DOMINANCE.md
- **Rules**:
  - ETHBTC breaks its 7-day high → large-cap alts risk-on (long ETH/large alts). 7-day low → alts capitulating (short alts vs BTC).
  - BTC.D falls ≥ 2% in 24h AND TOTAL2 (fallback TOTAL) 24h change > −0.5% → rotation into alts (long alts).
  - BTC.D rises ≥ 2% in 24h AND TOTAL2 24h change < −0.5% → flight to BTC (short alts or avoid alt longs).
- Claim: "Everyone waiting is herding — by the time BTC.D drops decisively, rotation moves are 30–50% in. Track ETHBTC + sector momentum to front-run."
- Historical claim: BTC.D 85%→33% (2017) and 70%→40% (2020–21) coincided with altseasons; 2024–25 BTC.D stayed at 55–65% with a muted altseason.
- **Data**: DOM (24h deltas; "≥2%" probably relative % change, not percentage points).
- **Ambiguity**: % vs pp. Default: relative % change of the index value. Holding period not given; default 24h–7d.

### 4.7 `quiet-regime`
- **Source**: BTC_DOMINANCE.md
- **Rule**: BTC.D, ETHBTC and TOTAL2 all within ±0.5% over 24h AND TOTAL's 7-day high-low range < 3% → coiling. It is a label, not a trade.
- **Data**: DOM.

### 4.8 `crypto-regime-classifier`
- **Sources**: BTC_DOMINANCE.md, CRYPTO_REGIME_PATTERNS.md
- **Buckets on 24h Δ** for TOTAL, TOTAL2, BTC.D, ETHBTC, TOTALDEFI and a payment basket:
  - |Δ| < 0.5% flat; 0.5–2% up/down; ≥ 2% strong.
- **States**:
  - EUPHORIC ALTSEASON: TOTAL2 ≥ +2% AND BTC.D ≤ −2%. Hint: trim.
  - ROTATION INTO ALTS: TOTAL2 up AND BTC.D down AND ETHBTC up. Hint: large-cap alts first.
  - ROTATION FORMING: TOTAL2 up AND TOTAL flat.
  - DEFI ROTATION: TOTALDEFI up AND TOTAL2 flat/down AND ΔDEFI − ΔTOTAL2 ≥ 1.5pp. Hint: long DeFi.
  - PAYMENT-COIN ROTATION: an mcap-weighted CoinGecko basket (Payment Solutions, Privacy, Bitcoin Forks: BCH, LTC, XMR, ZEC, XLM, XRP…) up AND TOTAL2 flat/down AND spread ≥ 1.5pp.
  - BTC-LED RALLY: TOTAL up AND TOTAL2 flat/down.
  - BROAD RISK-ON: TOTAL up AND TOTAL2 up.
  - FLIGHT TO BTC: BTC.D up AND TOTAL2 down.
  - BROAD RISK-OFF: TOTAL down AND TOTAL2 down. Hint: cash until TOTAL reclaims.
  - COILING/CHOP: default.
- Evaluation order is not fully given. Default: the listed order, first match wins.
- **Doc results** (888 hourly snapshots, 2026-05-29 → 06-22, ~24 days, "working hypotheses"):
  - Shares: risk-off 32.3%, risk-on 31.9%, chop 14.3%, payment rotation 7.0%, rotation forming 4.5%, flight to BTC 4.2%, BTC-led 2.8%, DeFi 2.1%, into alts 0.5%.
  - Average spell lengths: risk-off 10.6h (max 43), risk-on 9.4h (max 53), chop 4.9h, payment 3.9h, flight 3.7h, forming 2.9h, DeFi 2.4h, BTC-led 1.9h.
  - Transitions: chop ⇄ risk-off (11+10); risk-on → forming (9); forming → risk-on (8); risk-off ⇄ flight (9+8); risk-on → payment (8); chop → BTC-led (6); BTC-led → risk-on (7).
  - "Bullish ladder": coil → BTC-led → risk-on → rotation/payment.
- **Testable**: regime persistence (does a risk-on/off label predict the next 1–10h TOTAL/alt returns?); transition-based entries (chop → BTC-led → long alts); long the payment basket in payment-rotation.
- **Data**: DOM + OHLC. CoinGecko sector data for payment/DeFi; TOTALDEFI is available from TradingView.

### 4.9 `dominance-4h-divergence`
- **Source**: BTC_DOMINANCE.md
- **Rule**: for BTC.D, ETHBTC, TOTAL2 or TOTALDEFI, a 4h move ≥ 0.3% opposing the 24h direction is a leading signal that the 24h regime is about to flip.
- **Test**: does it predict the next regime label or the next 24h Δ sign?
- **Data**: DOM.

### 4.10 `sector-narrative`
- **Sources**: BTC_DOMINANCE.md, CRYPTO_REGIME_PATTERNS.md
- **Rule**: top sectors with ≥ 3% 24h gain show which narratives are accumulating, even in chop. Data-quality note: micro-cap sectors (Arcade Games 36.6%, Echo Launchpad 29.3% of hourly leadership) dominate. Proposed: an mcap floor of $500M.
- **Test**: sector momentum persistence.
- **Data**: OTHER (sector market caps).

### 4.11 `funding-crowded`
- **Sources**: crypto_alpha.md, engine.md
- **Rules**: APR = rate × 3 × 365.
  - crowded_long → SELL: the symbol's latest funding ≥ its 95th percentile over ~30 days OR APR ≥ 50%.
  - crowded_short → BUY: ≤ 5th percentile OR APR ≤ −25%.
  - Thin history (< 10 rates): the hard APR cutoff alone, sign-of-rate direction.
  - market_extreme_long/short: the symbol's APR ≥ 95th / ≤ 5th percentile of all perps' latest APR.
  - Confidence: 50 + min(20, 5|z|) (+5 if hard), cap 75/70.
- **Doc results**:
  - SHORT_CANDIDATE_SPEC: **funding fade vs follow — FADE −26 bp/day, FOLLOW +18 bp/day**. Fading crowded longs loses; the validated direction is FOLLOW. Test both signs.
  - Funding standalone is now off (`CRYPTO_ALPHA_FUNDING_SIGNALS=false`). Funding-derived entry filters were tested 6 times; all null (`funding_oi_dynamics` etc.).
  - `funding_carry_kalman` is cited as "our strongest edge": maxDD ≈ 0%, 100% positive years. No parameters given; presumably delta-neutral funding carry with Kalman-smoothed funding.
- **Holding period**: not given. Default 1–5 days (per bp/day framing).
- **Data**: FUND.

### 4.12 `exhaustion-fade`
- **Source**: crypto_alpha.md
- **Rule**: 24h move > +50% AND funding crowded-long → SELL.
- **Doc result**: `pump_fade_falsified`: shorting parabolic moves hits **58%**, positive median, **mean −4.8% over 5 days** (negative-skew trap).
- **Data**: OHLC + FUND.

### 4.13 `fresh-listing`
- **Sources**: crypto_alpha.md, defi_alpha.md, SYMMETRY_RESEARCH.md
- **Rules**:
  - BUY when listed < 12h on MEXC with non-zero 24h volume (defi variant: 24h volume ≥ $1M).
  - Opposite: `fresh_listing_short_fade_validated`: **+11.6% edge, skew −2, squeeze tail, small size only**.
- **Data**: listing timestamp (the first bar of the series approximates it) + OHLCV.
- **Ambiguity**: short-fade entry/hold not given. Default: short at the first close after N hours, hold 7 days.

### 4.14 `token-unlock-dump`
- **Sources**: SHORT_CANDIDATE_SPEC.md (Family B), SYMMETRY_RESEARCH.md
- **Rule**: short ahead of an unlock worth a large % of daily volume within N days.
- **Doc result**: skew −2 to −3; the biggest unlocks **squeeze up**; refused.
- **Data**: OTHER (unlock calendar).

### 4.15 `pump-dump-scanner`
- **Source**: USING_SIGNALS.md
- **Five layers**:
  1. volume > 2× EWMA baseline;
  2. |price change| ≥ 3%;
  3. ≥ 3 consecutive same-direction cycles (30 s polls);
  4. 24h volume ≥ $500k;
  5. flow ratio (buy share for a pump) favours the direction.
- Score 0–95. Confirmed ≥ 75 (4–5 layers); early warning 50–70.
- Usage: pump → momentum long / trailing scalp; dump → short on the first pullback.
- **Data**: OHLCV at 1-min resolution as a 30 s proxy. Flow layer needs taker buy/sell volume (Binance klines have taker-buy volume).
- **Ambiguity**: price-change window. Default: change over a rolling 5–15 min.

### 4.16 `pump-dump-breadth-regime`
- **Source**: USING_SIGNALS.md
- **Rule**: over the last 60 min, count of pumps / count of dumps ≥ 2.0 → bullish-dominant; ≤ 0.5 → bearish-dominant. Use as macro context.
- **Data**: OHLCV across the universe.

### 4.17 `defi-volume-recipes` (OHLCV parts testable on any crypto)
- **Source**: defi_alpha.md
- **Rules**:
  - quiet_volume_surge: volume z ≥ 2.0 (30-bar baseline) AND |daily change| < 1.5% → "accumulation". Direction is "inferred from move" (default: sign of the day's change).
  - momentum_volume: volume z ≥ 2 AND |daily move| ≥ 3% → follow the move.
  - dex_pool_volume: top DEX pool 24h volume ≥ $5M AND |DEX price change| ≥ 2% → follow (needs DEX data).
- **Data**: OHLCV.

### 4.18 `defi-valuation-recipes`
- **Source**: defi_alpha.md
- **Rules**:
  - tvl_leads_price: 1d TVL change ≥ 25% AND |price change| < 0.5 × TVL change → BUY.
  - fdv_bomb: FDV/mcap > 3 AND price +10% over 7d → SELL.
  - mcap_tvl_divergence: mcap +15% over 7d AND TVL ≤ −10% → SELL.
  - undervalued_vs_tvl: mcap/TVL < 0.5 AND TVL ≥ $25M → BUY.
- **Data**: OTHER (DefiLlama TVL, FDV) + OHLC.

### 4.19 `liquidation-magnet`
- **Sources**: ENV_VARS.md, deferred.md, SAGE_QUALITY_ROADMAP.md
- **Rule**: cluster Hyperliquid liquidations over 24–72h. A cluster ≥ $0.5–1M is a level. Fire when price is within 5% of it (12h per-coin cooldown).
- **Doc result**: shelves were 24–43% away with 30 wallets — "not magnets for this week". Unproven.
- **Data**: OTHER (liquidation positions/prices).

### 4.20 `fx-retail-positioning`
- **Sources**: fastbull_api.md §12, fastbull_collector.md
- **Rule**: from FastBull per-price-bin retail pending orders and open positions (FX majors, XAU, XAG, WTI):
  - long/short ratio = Σbuy / Σsell (> 1 = retail net-long; contrarian reading implied);
  - POC as a magnet;
  - near-price cumulative delta within ±N bins.
- No trading rule is stated; implied: contrarian to retail, magnet to the pending-order POC.
- **Data**: OTHER (snapshot only; no history).

### 4.21 `correlation-regime-break`
- **Sources**: fastbull_api.md §11, fastbull_collector.md
- **Idea**: a rolling correlation collapse, e.g. EURUSD vs DXY collapsing in a risk-off shock, flags a regime break.
- Computable from OHLC (rolling Pearson on returns at 5m/15m/1h/4h/1d/1w).
- **Data**: OHLC.

### 4.22 `thesis-broken` (momentum flip)
- **Sources**: ENV_VARS.md, NOTIFICATION_FILTER.md
- **Rule**: a prior direction is invalidated when the signal flips direction AND a market-structure shift (MSS) confirms in the same new direction. 4h/1d only; priority crypto.
- Use as an exit rule (exit a long when a bearish MSS + flip occurs).
- **Data**: OHLC.
- **Ambiguity**: MSS = close through the last opposite swing (pivot 5).

### 4.23 `gold-regime`
- **Source**: ENV_VARS.md
- Re-alert when gold drifts ≥ 2% since the last alert. No stance rule is given. Informational only.

### 4.24 `correlated-dedup`
- **Source**: SAGE_QUALITY_ROADMAP.md
- **Rule**: BTC and ETH firing the same setup = one macro signal. Cluster correlated symbols and count one.
- Relevant for portfolio backtests (effective N).
- **Data**: OHLC.

### 4.25 `open-interest` / `tape` / `liquidations` / `rug_setup` / `anomaly` peers
- **Source**: USING_SIGNALS.md
- Named only:
  - `rug_setup` = "blow-off-top SELL";
  - `anomaly` = bar-level z-score outlier;
  - `cusum` = Page CUSUM change point;
  - `open_interest`, `tape`, `liquidations`, `event_gate`, `regime` (vol regime).
- No rules given. See §7.3–7.5 for defaults on cusum/anomaly/regime.

---

## 5. Multi-timeframe

### 5.1 `mtf-alignment-verdict`
- **Sources**: mtf.md, USING_SIGNALS.md
- **Rule**:
  - HTF ladder: 15m, 30m, 1h, 2h, 4h, 1d, 1w. Take the next 3 higher rungs (15m → 30m, 1h, 2h; 4h → 1d, 1w).
  - Each rung's direction is BUY, SELL or WAIT (from the HTF analysis, mostly ZMA).
  - aligned if #agree > #oppose AND #agree ≥ floor(n/2); opposed mirror; else mixed.
  - Confidence ×1.20 aligned, ×0.70 opposed. Combined with leader-aligned: 60 → about 79–82.
- **Test**: an LTF signal filtered by HTF agreement. Note the HTF signal would be ZMA, which is weak. Alternative default: HTF trend = close vs SMA50 or the last BOS direction.
- **Data**: OHLC (multiple timeframes).

### 5.2 `htf-level-confluence`
- **Sources**: coverage.md, KEY_LEVELS_RESEARCH.md, PRICE_ACTION_SIGNIFICANCE.md
- **Rule**: a level that also exists (within band/ATR tolerance) on 1–3 higher TFs is worth more. Look only upward; a lower TF agreeing does not count.
- **Test**: reaction quality by the number of agreeing HTFs.
- **Data**: OHLC.
- **Ambiguity**: tolerance. Default: the HTF zone overlaps the LTF level ± 0.5 LTF ATR.

### 5.3 `htf-pattern-backing`
- **Source**: proximity.md
- **Rule**: an HTF candle pattern (≤ 5 HTF bars old) in the reaction direction adds +15 per pattern (cap 30), versus +8 (cap 20) for LTF patterns.
- **Data**: OHLC.

### 5.4 `htf-premium-discount`: see §1.11. `ltf-confirmation-entry`: see §1.15.

### 5.5 `tf-selection-rule`
- **Source**: USING_SIGNALS.md
- **Claim**: "Don't use 15m setups in low-volume crypto … most signal lives on 1h + 4h". 15m was about 10% of directional setups.
- **Test**: compare per-TF expectancy.
- **Data**: OHLC.

### 5.6 `ensemble-vote`
- **Source**: decision.md
- **Rule**: weighted peer vote with min_agreement = 2 (1 for synthetic-trending).
- Expert weights by regime:
  - trending synthetic: zma 1.5, breakouts 1.3;
  - mean-reverting synthetic: ame 1.5, smc 1.3;
  - trending FX: smc 1.4, pullbacks 1.3;
  - mean-reverting FX: ame 1.4, smc 1.3.
- Testable only once the component signals are built. Low value.

---

## 6. Short candidates

### 6.1 `short-candidate-composite`
- **Source**: SHORT_CANDIDATE_SPEC.md
- **Rule**: SELL when ≥ 2 independent families agree ("conviction = family stacking"):
  - **G/H relative weakness** (highest weight; validated): negative divergence vs BTC/ETH, R² ≥ 0.3 (§4.2).
  - **F derivatives**: funding extreme positive + OI record or diverging + a dense long-liquidation cluster below ("the unwind-down setup").
  - **A momentum rollover** (down-weighted; context only, never lead): a vertical move stalling.
  - **E flow**: whales net-short, taker sell share rising.
  - **B unlocks**, **E exchange netflow**: new data.
- **Entry quality gate**:
  - clean vs crowded/squeeze risk (funding + positioning);
  - liquidity: thin if < ~$5M daily volume, pushed down;
  - trackable (OKX/HL/Binance) vs MEXC-only.
  - A lone crowded-short pump (example VANRY) is the weakest case.
- **Doc results**:
  - family A "pumped + positive funding fade" is a LOSING trade (FADE −26 bp/day);
  - G/H persists 3–5 days;
  - F is "validated-ish".
- **Data**: OHLC + FUND + OI; liquidations/flow are OTHER.
- **Default backtestable core**: G/H + F, with
  - F = funding ≥ 95th percentile over 30 days AND OI at a 30-day high while price fails to make a new high;
  - hold 3–5 days;
  - exclude 24h quote volume < $5M.

### 6.2 `fdv-bomb` / `mcap-tvl-divergence` (§4.18), `exhaustion-fade` (§4.12), `token-unlock` (§4.14), `fresh-listing-short-fade` (§4.13), `skew-conditioned` (§2.22), `rug_setup` blow-off-top (§4.25).

---

## 7. Other

### 7.1 `time-of-day-session`: the only "untested axis"
- **Sources**: SMC_ICT_RESEARCH.md (B), ENV_VARS.md (time axis), PRICE_GEOMETRY_RESEARCH.md
- **Rule**: tag every signal with:
  - UTC hour and weekday;
  - session: tokyo / london / new_york / off_hours, computed in each centre's local time with DST;
  - overlap: more than one centre open (London/NY);
  - at_open: a bell within the hour;
  - weekend.
- **Test**: whether structural setups resolve differently by session. Example filter: "only in the 4 hours around a major equity open".
- **Specific literature claims** to test on crypto:
  - (a) BTC realised volatility peaks around the 3 major equity opens.
  - (b) Overnight returns are positive and trading-hour returns slightly negative (reversal). **Returns at 22:00 and 23:00 UTC dominate** (Quantpedia "overnight seasonality in Bitcoin"). Default test: long BTC from 22:00 to 00:00 UTC.
  - (c) Effects are localised, asset-specific and non-persistent.
- ICT time constructs also in scope: killzones, Silver Bullet (fixed 1-hour windows), macros (~20 min windows), Power of Three / Judas swing (daily accumulate → manipulate → distribute).
  - Window times are not given. Defaults in NY time: Asia 20:00–00:00; London killzone 02:00–05:00; NY killzone 07:00–10:00; Silver Bullet 03–04, 10–11 and 14–15.
  - Judas swing default: the first move after the NY midnight/London open in one direction is faded; trade the reversal after a sweep of the Asia high/low.
- **Prior**: "not high". Six entry-filter nulls. Higher vol at the open also means worse costs.
- **Data**: OHLC (intraday, 15m/1h).

### 7.2 `vol-target-exposure`
- **Source**: PRICE_GEOMETRY_RESEARCH.md (`regime_detection`)
- **Rule**: continuous volatility targeting (exposure scalar ∝ target vol / realised vol).
- **Doc result**: improved Sharpe −0.34 → −0.13. Discrete de-risk-on-high-vol gates failed.
- **Data**: OHLC.

### 7.3 `cusum-drift`
- **Sources**: ENV_VARS.md, SMC_MENTORSHIP_REVIEW.md
- **Rule**: Page CUSUM on returns. Flag when accumulated drift exceeds what noise explains; used as context agreeing with the setup direction.
- **Doc result**: failed for timing entries (`kalman_cusum_multitf`); untested as context.
- **Data**: OHLC.
- **Default**: k = 0.5σ, h = 5σ.

### 7.4 `knn-similarity` / analogue retrieval
- **Sources**: toolbox.md, decision.md, deferred.md
- **Rule**: kNN over the symbol's own history ("what happened last time this chart looked like this"). Composer blend: conf = 0.7 × parametric + 0.3 × kNN win rate (k = 5, min 3 matches).
- Caveat: overlapping windows are not independent.
- **Data**: OHLC.

### 7.5 `kelly-no-edge-gate`
- **Source**: KEY_LEVELS_RESEARCH.md (Phase 4)
- **Rule**: edge = p·b − (1 − p), with b = R:R and p from per-grade priors, later measured. Suppress if edge ≤ 0. Size at a quarter-Kelly cap (0.25).
- A sizing/filter overlay for any graded strategy.

### 7.6 `kalman-smoothing-before-signal`
- **Source**: toolbox.md
- **Claim**: "Kalman denoising beat blind slowdown at matched turnover in this project's own work."
- **Test**: Kalman-filtered price into the z-score versus raw price.
- **Data**: OHLC.

### 7.7 `evaluation-standards` (not ideas; adopt for scoring)
- **Sources**: promotion.md, SAGE_QUALITY_ROADMAP.md, ENV_VARS.md
- **Scoring rules**:
  - Triple-barrier outcome: the signal's own stop/target, else a symmetric ±1.5 ATR barrier (null win rate 0.5).
  - Suppress if n ≥ 25 and the Wilson lower bound ≤ 0.5.
  - Promote if n ≥ 40 and the Wilson LB ≥ 0.55 (ENV says 0.53), over the last 300 outcomes. Roughly: a raw win rate of ~70% is needed at n = 40, ~59% at 300+.
  - Do not score a directional-magnitude claim against symmetric barriers it never proposed (the `latent_levels` example: 111/256 = 0.434, LB 0.384, void).
  - Count evidence by *family*, not by peer.
  - Daily-portfolio test plus permutation; GBM and circular-shift nulls; FDR/DSR for multiple variants; set thresholds against null distributions (e.g. variance ratio).

---

## Ideas that cannot be backtested on OHLC/exchange data (and why)

| Idea | Source | Why not |
|---|---|---|
| A/V shape "must be obvious" as stated | SMC_MENTORSHIP_REVIEW/RESULTS | Eyeball judgement with no threshold. Any implementation (prominence/spike-share, ≥3-bar pivots) is our construct, not the source's. Testable only as our proxy. |
| Footprint-chart confirmation at the POI | SMC_MENTORSHIP_REVIEW (video 7) | Needs footprint/order-flow (bid/ask volume per price) data. |
| "80%+ win rate since February" | SMC_MENTORSHIP_REVIEW | Self-reported and selectively posted; no trade list to reproduce. |
| Fed/CB event gating; coverage of SEK/NOK/MXN/ZAR/SGD/CHF | coverage.md | Needs an economic calendar (FastBull/TradingView calendar). Not OHLC, though a historical calendar would make it testable. |
| Token unlocks (Family B) | SHORT_CANDIDATE_SPEC | Unlock calendar (TokenUnlocks/DeFiLlama) plus FDV; not exchange data. |
| Exchange netflow, whale net-short, taker sell share (Family E) | SHORT_CANDIDATE_SPEC | On-chain (CryptoQuant/Glassnode/Arkham) and Hyperliquid wallet data. Taker share is partly available from Binance klines. |
| Fundamental decay (TVL/fees), event/catalyst (Families C, D) | SHORT_CANDIDATE_SPEC | Out of scope; no feed. |
| DeFi TVL/FDV/mcap recipes (tvl_leads_price, fdv_bomb, mcap_tvl_divergence, undervalued_vs_tvl, dex_pool_volume) | defi_alpha.md | DefiLlama/GeckoTerminal history needed; FDV coverage ~50%. |
| Liquidation-cluster magnets, `liq_level` flag | ENV_VARS, deferred.md | Hyperliquid per-wallet liquidation prices; no historical archive here. |
| Payment-coin rotation regime, sector narrative leader | BTC_DOMINANCE, CRYPTO_REGIME_PATTERNS | CoinGecko category market-cap history (could be approximated with a hand-built mcap-weighted basket from OHLC × supply). |
| Retail positioning (pending orders / open positions per bin) | fastbull_api §12 | FastBull snapshot-only endpoint; no history. |
| FastBull correlation endpoints | fastbull_api §11 | The vendor series itself is not reconstructible, but equivalents are computable from OHLC (§4.21). |
| Cross-broker "at level on ≥3 of 7 brokers" (usd_confluence), best-execution venue | ENV_VARS, deferred.md | Needs the same instrument from several brokers; the single-source variant is testable. |
| Elliott wave | PRICE_GEOMETRY_RESEARCH | "not falsifiable in the form usually stated". |
| Gann angles/squares | PRICE_GEOMETRY_RESEARCH | Depend on chart scaling, not a market fact. |
| 10-trades rule "psychology" component (stop after 9–10 losses = system broken) | SMC_MENTORSHIP_REVIEW | Discretionary review step. The sizing part is testable (§1.23). |
| Trader `reviewVerdict` weighting in kNN | decision.md | Needs human labels. |
| `predict_sweep_side` 8 factors, AME precursors (pool_exhaustion, sweep_eta), `participant` institutional/retail tag, empirical-strategy shadow | ame.md, decision.md | Factors and definitions are not given in the docs; source code under `api/` would be needed. |
| `xsmom_majors`, `funding_carry_kalman`, `funding_fade_vs_follow`, `fresh_listing_short_fade_validated`, `pump_fade_falsified`, `liquidity_sweep_predictor` exact specs | various | Referenced as memory-bank or lab results; parameters are not in these docs. Testable only with assumed defaults (given above). |
| VIX direction (RandomForest beat river-ARF) | deferred.md | Only mentioned; no spec. |

## Files with no trading idea (infrastructure only)

- **tradingview_api.md**: TradingView protocol reference. Useful facts only: max 5000 bars per fetch, about 20 years of daily history; FX/spot-commodity volume = tick count; crypto volume in base units.
- **tradingview_collector.md**: collector wiring.
- **fastbull_api.md**: API reference. The only trading-adjacent content is §11–13 (correlation, positioning, volume profile), catalogued above.
- **fastbull_collector.md**: collector wiring; volume-profile and positioning metrics catalogued in §2.16 and §4.20.
- **dispatch.md**, **NOTIFICATION_FILTER.md**: alert routing and dedup.
- **ENV_VARS.md**: settings. Its parameter values are folded into the entries above.
- **NOTES.md**: ops and cron. The exception is the triangle measured move (§3.1).
- **README.md**, **peers.md**: indexes.
- **engine.md**: architecture. Restates the funding, defi and leader-bias pipelines and the impulse definition.
- **USING_SIGNALS.md**: consumer reference. The pump/dump scanner and breadth regime are catalogued (§4.15–4.16).
- **promotion.md**: evaluation methodology (§7.7).
- **coverage.md**: instrument universe — 29 FX, 25 Deriv synthetics, 7 CME currency futures, 6 indices (SPX, NDX, DJI, DAX, FTSE, N225), 5 crypto (BTC, ETH, SOL, BNB, XRP), 3 COMEX metals, XAU/XAG; timeframes 1h/4h/1d/1w. Its grade ladder is in §2.4.
- **deferred.md**: port decisions. Sweep-overshoot statistics are in §1.22.
- **SAGE_QUALITY_ROADMAP.md**: process. Its flags are folded into §2.5, §2.6 and §2.12.

## Conflicts between docs to be aware of

1. **Grade ladder**: coverage.md (S needs 3 HTFs; 0 HTF = nothing) vs PRICE_ACTION_SIGNIFICANCE.md (S needs 2+; a single-TF B exists).
2. **TAKE/CONFIRM threshold**: decision.md (conf ≥ 80, RR ≥ 2.0 FX/crypto) vs USING_SIGNALS.md (~70, RR ≥ 1.5).
3. **Promotion Wilson-LB**: promotion.md 0.55 vs ENV_VARS 0.53.
4. **Impulse definition**: "body > 1.5×ATR + tight wicks + 1.5× volume" (engine.md) vs "body > k·ATR + one-sided wicks + volume > SMA" (PRICE_ACTION_SIGNIFICANCE.md).
5. **ZMA**: the README calls it "z-score momentum", but the rule is mean reversion (z > 2 → SELL).
6. **Funding**: the crypto_alpha recipes fade crowding, but the lab result says FOLLOW (+18 bp/day) beats FADE (−26 bp/day).
