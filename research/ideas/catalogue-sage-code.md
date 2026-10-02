## Catalogue of the trading logic in `sage` (code at the source)

I read every file in `analysis/`, `peers/` (including `shared/`), `quality/` and `sentiment/`. In `market/` I read `assets`, `calendar`, `config`, `context`, `liquidations`, `models`, `service`, `sessions` and `store`. In `notifications/` I read `filters`, `selection` and `upcoming`, and grepped the rest. I grepped `api/`, `channels/`, `journal/`, `bus`, `stack` and `cli` and found no trading logic in them. I changed nothing.

Every definition below comes from the code. Doc names appear only where the code cites them (or the doc name obviously matches); I did not read the docs. I did not run any code against data. The thresholds and edge cases that I computed myself (rather than read off a constant) are marked "computed".

---

## 0. Runtime conventions a backtest must reproduce

- **Bars.**
  - A `Bar` has `timestamp` = the bar's **open** time (UTC), plus O/H/L/C/volume.
  - The collector stores **closed bars only** (`market/models.py:closed_only` drops the last bar if `ts + span > now`).
  - Volume is traded size on crypto and tick volume on TradingView FX.
- **Bar loader.** `market/store.py:MongoStore.loader(limit=300)` gives **every series to peers as the last 300 closed bars**. That caps every lookback: latent's 400 becomes 300, the profile uses 240, and the 1d series is long enough for a 200-day SMA.
- **When analysis runs.**
  - The collector publishes a bar notice for every (instrument, TF) on **every collection cycle** (default 300 s), even when no new bar was written.
  - So `analysis.service.analyse` re-runs on the same closed bar many times. In a backtest, evaluate **once per bar close**. The only stateful piece this affects is `echoes` (see §3.3).
  - The analysed TF is the one that closed. When several venues quote one instrument, only the "best" venue is announced (`market/service.py:best_of`).
- **Timeframe ladder.**
  - `analysis/service.py:build_frame` loads up to 3 higher TFs from `DEFAULT_TIMEFRAMES = ("15m","1h","4h","1d")`.
  - The collector also stores 1w, but analysis never loads it as a rung, and 1w frames get no ladder.
  - Resulting ladders: 15m → [1h, 4h, 1d]; 1h → [4h, 1d]; 4h → [1d]; 1d → [] (counts as "at top"); 1w → [] (at top).
  - **Backtest rule:** higher-TF bars must be the ones closed at or before the lower-TF bar's close.
- **Companions** (`analysis/service.py:companions`).
  - Crypto: `("BTC/USDT","ETH/USDT")`.
  - Any FX 6-letter pair: the other USD majors from `EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCHF, USDCAD, USDCNH` (same venue prefix), plus the CME futures for both legs (`6E1!, 6J1!, 6B1!, 6A1!, 6N1!, 6C1!, 6S1!`).
  - Indices, metals, synthetics and futures: none.
  - Symbols are venue-qualified (`OANDA:EURUSD`, `BINANCE:BTCUSDT`). The crypto leaders are spelled `BTC/USDT`, so they load only if a CCXT/MEXC series with that exact spelling exists.
- **Three ATR definitions are in use:**
  - `peers/shared/indicators.py:atr(bars, n)`: Wilder RMA of true range, `alpha = 1/n`, **seeded at TR[0]** (not warmed up). TR[0] uses close[0] as the previous close.
  - `analysis/decision.py:average_true_range` and `quality/barriers.py:average_true_range`: **simple mean of the last 14 TRs**.
  - `ema` is likewise seeded at the first value, with `alpha = 2/(n+1)`.
- **`price_sigma(closes, 20)`** (`numeric.py`) = `std(last 20 simple returns) × last close`. It returns 0 if there are fewer than 6 prices.
- **Asset class** (`market/assets.py:classify`) comes from the symbol prefix or the source.
  - The sweep class (`grading.sweep_class`) uses the source venue: `mexc, binance, bybit, okx, gateio, bitget, kucoin` → crypto; `deriv` → jump / step / volatility (by `JUMP`/`STEP` in the name); everything else → `forex_tradfi`.
- **Peer output** (`peers/models.py:ModelSignal`): direction (BUY / SELL / None), confidence 0–100, grade (S > A+ > A > B+ > B > C > none), `supporting` flag, `family`, `sl`, `tp_ladder` (3 rungs), price = last close.
  - "Actionable" means direction is set and confidence > 0.
  - Supporting peers can vote and corroborate but can never lead a setup.
- **Registered peer order:** anomaly, bjorgum, correlation, divergence, latent_levels, level_reaction, smc, structural_setup, usd_confluence, zma.

---

## 1. `peers/shared/` — building blocks (none emits a trade by itself)

### 1.1 `ha-pivots` — `indicators.py:heikin_ashi`, `pivot_source`, `pivot_highs`, `pivot_lows`
- **Heikin-Ashi:**
  - `ha_close = (O+H+L+C)/4`
  - `ha_open[0] = (O0+C0)/2`; `ha_open[i] = (ha_open[i-1] + ha_close[i-1])/2`
- **Pivot sources:**
  - `HA` (default): high series = `max(ha_open, ha_close)`, low series = `min(...)`
  - `body`: max/min of open and close
  - `hilo`: raw high/low
- **Pivot high at i:** `v[i] == max(v[i-left .. i+right])` and every one of the `left` bars before it is strictly lower. Ties on the right side are allowed, so the earliest bar of a flat top wins. Pivot low mirrors this.
- **Lookahead:** none if recomputed every bar. Indices stop at `len-right-1`, so a pivot is confirmed `right` bars late.

### 1.2 `tsi-curl` — `indicators.py:tsi(prices, 13, 25, 13)` and `bjorgum.py:curl`
- `change = diff(close)` with a leading 0.
- `TSI = EMA13(EMA25(change)) / EMA13(EMA25(|change|))`; `signal = EMA13(TSI)`.
- **Curl:**
  - BUY if `TSI[-2] <= sig[-2]` and `TSI[-1] > sig[-1]`
  - SELL on the mirror cross
- Used only as a grading "extra" in bjorgum.

### 1.3 `adx-regime` — `regime.py:read`
- Wilder ADX(14); needs at least 40 bars.
  - `+DM = up` if `up > down` and `up > 0`, where `up = diff(high)` and `down = -diff(low)`; `-DM` mirrors this.
  - `+DI = 100·RMA14(+DM) / RMA14(TR[1:])`; `-DI` likewise.
  - `DX = 100·|+DI − −DI| / (+DI + −DI)`; `ADX = RMA14(DX)[-1]`.
- direction = up if `+DI[-1] >= -DI[-1]`, else down.
- strong = `ADX >= 28` (env `SAGE_REGIME_ADX_STRONG`).
- `opposes(signal)` is true when the trend is strong and points the other way.

### 1.4 `candles` — `candles.py:detect(bars, atr)`
Looks at the last bar (and the one before it).
- **doji:** `body <= 0.1·range`
- **hammer:**
  - `lower_wick >= 2·body` and `upper_wick <= 0.25·range`
  - if `atr > 0`, the range must be at least `0.5·atr`
  - Edge case: a zero body passes the wick test trivially.
- **shooting_star:** the mirror of hammer.
- **dragonfly:** doji and `lower_wick >= 0.6·range` → BUY.
- **gravestone:** mirror of dragonfly → SELL.
- **spinning_top:** `body <= 0.3·range`, both wicks at least `0.25·range` → no lean.
- **bull_engulfing:** previous bar not bullish (`C <= O`), current bar bullish, `C >= prev.O`, `O <= prev.C`, `body > prev.body`.
- **bear_engulfing:** mirror of bull_engulfing.
- **tweezer_bottom:**
  - `|prev.low − low| <= 0.1·(atr or range)`
  - previous bar not bullish, current bar bullish
- **tweezer_top:** mirror of tweezer_bottom.
- **piercing:**
  - previous bar not bullish, current bar bullish
  - `O < prev.C` and `C >= (prev.O + prev.C)/2`
  - There is no "close below previous open" condition, so it overlaps engulfing.
- **Lean:** BUY if only bullish names fired; SELL if only bearish; None if neither or both. Doji and spinning top add no lean.

### 1.5 `reaction-confirm` — `reaction.py:confirm_reaction(bars, levels, atr, tolerance=0.5, lookback=2)`
- **Nearest level:** the level with the smallest distance to the last bar's range (0 if the level is inside `[low, high]`).
- **In play:** `distance/atr <= 0.5`.
- side = resistance if `level >= close`, else support.
- **Confirmed:** scanning `bars[:n]`, then `bars[:n-1]`, `candles.detect(...).lean` must equal the wanted direction (SELL at resistance, BUY at support). The confirming candle may therefore be one bar old.
- Output: the level, side, the name of the first pattern, and the direction.

### 1.6 `sweep-detect` — `grading.py:detect_sweep(bars, level, side, atr, lookback=3, min_pierce=0.1)`
- **Resistance:**
  - `pierce = max(high of last 3 bars) − level`
  - `reclaimed = close[-1] < level`
- **Support:** mirror.
- **Swept:** `reclaimed and pierce >= 0.1·atr`.

### 1.7 `grade-ladder` — `grading.py:confluence_count`, `grade_reaction`, `adjust`, `GRADE_CONFIDENCE`
- **Credit:**
  - `credit` = number of agreeing higher TFs.
  - If that is 0, the frame is at the top of the ladder, and the reaction was swept, credit = 1.
- **Grade:**
  - not confirmed, or credit < 1 → **no signal**
  - not swept → B+
  - swept → A (credit 1), A+ (credit 2), S (credit ≥ 3)
- **adjust:**
  - A+ with at least 2 "extras" → S
  - A+ or S with no extras and not swept → down one rung
  - In practice the second rule never fires, because A+ and S always require a sweep.
- **Base confidence:** B+ 72, A 81, A+ 90, S 96.
- **Consequence (computed):** S needs 3 agreeing higher TFs, which only a 15m frame can have. A 1h frame tops out at A+ unless the extras promote it.

### 1.8 `sweep-zone-stop` — `grading.py:sweep_zone`
This is the stop placement used by bjorgum, level_reaction and smc.

| class | measure × multiple |
|---|---|
| deriv volatility | σ × 2.2 |
| deriv step | σ × 2.5 |
| deriv jump | ATR × 2.0 |
| crypto | σ × 3.0 |
| forex / tradfi | ATR × 1.5 |
| unknown | max(ATR, σ) × 1.3 |

- σ = `price_sigma`.
- `reach = mult·vol`; `buffer = 0.5·vol`.
- **Resistance side** (a short's stop):
  - `est = level + reach`
  - `stop = max(est + buffer, entry + buffer)`
  - if any other level lies in `(est, stop + buffer]`, then `stop = max(those) + buffer`
- **Support side:** mirror.
- `estimated_entry = est` is context only and never used as the entry.
- **Tuned:** the multiples are class medians of overshoot ÷ volatility from 343/440 resolved outcomes.

### 1.9 `target-ladder` — `grading.py:target_ladder(entry, direction, atr, levels, rungs=3)`
- Take the levels strictly beyond entry in the trade direction, sorted by distance.
- Skip any level within `0.5·atr` of the previously chosen rung.
- Take 3. If fewer exist, pad with the last rung ± 1·atr.
- Returns None if no level lies ahead.

### 1.10 `kelly-gate` — `kelly.py:conviction(grade, reward_risk, confidence, calibration)`
- **Win probability p**, in order of preference:
  1. A measured (peer, grade) rate from the live calibration, if it is in (0, 1).
  2. Otherwise linear interpolation of the hit rate against reward:risk, clamped at the ends, through these points: (1.04, .620), (1.71, .507), (2.60, .324), (4.04, .155), (6.38, .127), (12.16, .056).
  3. Otherwise 0.30.
- **Edge and suppression:**
  - `b` = the given reward:risk, or 1.5 if none was given.
  - `edge = p·b − (1−p)`; **suppress if `edge <= 0`**.
  - `f* = max(0, p − (1−p)/b)`; the cap is 0.25 (env `SAGE_KELLY_CAP`).
  - `multiplier = 0.7 + 0.5·min(1, f*/0.25)`; `confidence_out = min(99, confidence·multiplier)`.
- **Computed with no calibration:**
  - The gate passes only when `0.62 <= b <= 3.44`.
  - A setup with no measurable b is always suppressed.
  - `confidence_out >= 65` (the composer's bar) holds only for: B+ when b ≤ 2.39; A when b ≤ 2.79; A+ when b ≤ 3.31; S when b ≤ 3.44.
- **Tuned:** the geometry curve and the 0.30 base were measured on 427–440 outcomes carried over from the old system.

### 1.11 Context readings
These are recorded in structural_setup and smc features. **None of them gates anything.**

- **`crt` — `crt.py:read` / `read_range` / `classify`** (candle range theory; doc SMC_MENTORSHIP_REVIEW.md).
  - Compares the last candle with the previous candle's high/low.
  - Took neither edge → accumulation, no lean.
  - Took both → manipulation if the close is inside the range, expansion if outside; no lean either way.
  - Took one edge and closed inside → manipulation, lean away from the swept side.
  - Took one edge and closed outside → expansion, lean toward the swept side.
  - `read_range` applies the same rules to a band supplied by the caller over the last 20 bars ("AME"; doc name match: ame.md).
- **`cusum-drift` — `cusum.py:read`.**
  - `r` = log returns.
  - σ = std(ddof=1) of the 60 returns **before** the last 30 (no self-contamination).
  - Band `k = 0.5σ`, line `h = 5σ`.
  - Over the last 30 returns: `S_up = max(0, S_up + r − k)` and `S_dn = min(0, S_dn + r + k)`.
  - BUY or SELL on the first crossing; if both sides cross, the more recent one wins.
- **`analogues` — `similarity.py:neighbours`.**
  - The query is the last 20 log returns, z-scored.
  - Candidates are every earlier 20-return window that does not overlap the query and has 10 forward returns available.
  - Distance is Euclidean on z-scored windows; keep the 25 nearest.
  - Lean = sign of the median forward 10-bar log return, if `|median| >= 0.1·std(forward)`.
  - No lookahead, by construction.
- **`volume-profile` — `profile.py:build`** (doc PRICE_GEOMETRY_RESEARCH.md).
  - Last 240 bars, 48 bins between the min low and max high.
  - Each bar's volume is spread uniformly across the bins its own high–low covers.
  - POC = the centre of the heaviest bin.
  - Value area (68.2%) grows outward from the POC, always taking the heavier neighbour.
  - Node at a price: HVN if `bin >= 1.5·mean bin`, LVN if `bin <= 0.5·mean bin`.
- **`excursion-tilt` — `asymmetry.py:excursions`** (doc SYMMETRY_RESEARCH.md).
  - Over the last 100 bars: `up = mean(max(H − prevC, 0))`, `down = mean(max(prevC − L, 0))`.
  - `tilt(long) = clip(down / avg(up, down), 0.6, 1.8)`; a short uses `up`.
  - **This one does change the trade:** it multiplies structural_setup's stop buffer.
- **`clock` — `session.py:read`** (doc SMC_ICT_RESEARCH.md).
  - Session in each centre's local time: Tokyo 09:00–15:00, London 08:00–16:30, New York 09:30–16:00, weekdays.
  - Records the latest-opening centre that is open, an overlap flag, and `at_open` within 60 minutes of an open.
  - It reads the bar's **open** timestamp.
- **`consensus` — `consensus.py:summarise`.** Tallies the readings into quiet / thin / aligned / against / split (quorum 2). Text only.
- **`pips` — `pips.py:find(bars, count, confirm=3, minimum)`.**
  - Perceptually important points on closes.
  - Starts from the endpoints; repeatedly adds the point with the largest vertical distance to the chord between kept points, while that distance exceeds `minimum`.
  - The last `confirm` bars are excluded; endpoints are dropped from the output.
  - A point is a high if `p >= max(neighbours)`.

---

## 2. Peers (`peers/*.py`)

### 2.1 `bjorgum` — `peers/bjorgum.py:analyze` (doc bjorgum.md; family "levels")

**Zones** — `build_zones`, default `Config`:
- `left = 20`, `right = 15`, `keep = 4` per side, `atr_length = 30`, `width = 0.5`, `max_width_percent = 5`, `source = HA`, `proximity = 0.25`.
- Every env override exists (`SAGE_BJORGUM_*` and legacy `BJORGUM_MULT` / `BJORGUM_N_PIV` / `BJORGUM_SRC`).
- **Building:**
  - Find HA pivots with left 20 / right 15.
  - Each pivot becomes a zone `level ± half`, where `half = min(0.5·ATR30[pivot_idx], 0.025·|level|)`. The zone is "resistance" if it came from a pivot high.
  - Merge overlapping same-side zones, newest first: the union is kept and break counts are summed.
  - Keep the 4 newest zones per side.
- **Firing chain** (needs at least 40 bars):
  1. `nz` = the zone nearest to the close; it must satisfy `dist(close, nz) <= 1.0·ATR30` (`0.25 × 4`).
  2. `read_reaction`, using the last bar and the previous close:
     - **break BUY:** `prevC <= top` and `C > top`
     - **break SELL:** `prevC >= bottom` and `C < bottom`
     - **false_break SELL:** `prevC > top` and `bottom <= C <= top`; false_break BUY mirrors it
     - **push SELL:** `H >= bottom` and `C < bottom`, with prevC below the zone
     - **push BUY:** `L <= top` and `C > top`, with prevC above the zone
     - Otherwise there is no direction, and the peer returns nothing.
  3. **Confirmation:** `candles.detect(bars, ATR30).lean == direction`. A false break counts as confirmed automatically.
  4. **Sweep:** `detect_sweep` on `zone.mid`, with side taken from the zone's origin, ATR30, the last 3 bars, and pierce ≥ 0.1 ATR.
     - Consequence (computed): a BUY break of a resistance zone closes above the mid, so it can never count as swept and grades at most B+.
  5. **Higher-TF confluence:** a higher TF agrees if any of its own bjorgum zones (same config) lies within `0.5 × HTF ATR30[-1]` of `zone.mid`.
  6. **Grade:** `grade_reaction`. The only extra is a TSI curl in the same direction, so `adjust` never changes anything in practice.
- **Emits:**
  - direction; confidence = `min(base_conf, 90)`; grade.
  - `supporting = True` when the state is false_break.
  - **SL** = `sweep_zone(zone.mid, side = support if BUY else resistance, ATR30, σ20, entry = close, levels = other zone mids)`.
  - **TP** = `target_ladder(close, dir, ATR30, other zone mids)`.
  - Entry = the close of the signal bar.
  - Features also record `level_touches`, the patterns, and `estimated_entry`.
- **Data:** OHLC on this TF and the higher TFs.
- **Repaint risk:** zones change as pivots confirm 15 bars late and as merges re-form, so compute walk-forward on `bars[:t+1]` (capped at 300).

### 2.2 `level_reaction` — `peers/level_reaction.py:analyze` (family "levels"; doc name match KEY_LEVELS_RESEARCH.md)
- **Config:**
  - `tolerance = 0.5` ATR, `lookback = 2` bars, `stop = 0.5` ATR (env `SAGE_LEVEL_*`).
  - Moving averages: 200-day and 50-day SMA of **daily** closes, which need at least 180 / 45 daily bars. They are read from the frame's 1d series, so they are available on every TF whose ladder includes 1d.
- **Levels:** bjorgum zone mids (bjorgum config) plus the MAs. ATR = Wilder ATR30.
- **Firing chain:**
  1. `confirm_reaction` (§1.5) must be confirmed.
  2. Sweep (§1.6) on `reaction.level`, using the reaction side.
  3. Higher-TF confluence exactly as in bjorgum; grade via §1.7.
  4. **Extras:**
     - "structure": `smc.structure(bars, 5).trend` equals the direction, or the last structure event is a CHoCH in that direction.
     - "the 200d/50d": a moving average within `0.75·ATR` of the level.
     - `adjust`: A+ with both extras → S.
  5. **Counter-trend demotion:** if `ADX14 >= 28`, the trend opposes the direction, and not (swept and structure-aligned) → down one rung (S → A+ → A → B+; B+ stays).
  6. **Tight geometry for the Kelly gate only:**
     - `stop_tight = level ± 0.5·ATR` beyond the level.
     - target = the nearest obstacle (zone mid or MA) beyond the entry.
     - `ratio = reward/risk`. It is None if there is no target or the stop is on the wrong side, and None means suppression.
  7. Kelly (§1.10) with the per-peer calibration if present; **suppress if edge ≤ 0**, which (computed) means `ratio ∉ (0.62, 3.44]`.
- **Emits:**
  - confidence = `base_conf(grade) × Kelly multiplier`.
  - **SL** = `sweep_zone(level, side, ATR30, σ20, entry = close, levels = other zone mids)`. This is wider than the stop the gate judged.
  - **TP** = `target_ladder(close, dir, ATR30, zone mids + MAs)`. Entry = close.
  - Features record funding and open interest, which do not gate.
- **Data:** OHLC (this TF, higher TFs, 1d).
- **Note:** the gate's geometry (tight stop) differs from the emitted geometry (sweep stop), and the composer judges the emitted one.

### 2.3 `smc` — `peers/smc.py:analyze` (doc smc.md, SMC_MENTORSHIP_REVIEW.md; no family set)

**Swings:** `pivot_highs/lows` on raw high/low with `length = 5` both sides (env `SAGE_SMC_SWING`).

**Structure** (`structure`):
- Walk bars in order, tracking the last swing high and last swing low.
- When `close > last_high.level`, log an event `bos` (or `choch` if the trend was down), set the trend to up, and clear `last_high`. Downside mirrors.
- **Repaint risk:** a vectorised full-history version gives different events from the walk-forward version, because a later-confirmed swing replaces `last_high` retroactively. Recompute on `bars[:t+1]`.

**Fair value gaps** (`fair_value_gaps`):
- Bullish when `high[i-1] < low[i+1]`; zone = `[high[i-1], low[i+1]]`, indexed at i.
- Mitigated once any bar from `i+2` onward has `low <= top` and `high >= bottom`.
- Only unmitigated gaps are kept.

**Order blocks** (`order_blocks`):
- Bar i is a bullish block if bar i is bearish (`C < O`), bar i+1 is bullish, and `|C − O|` of bar i+1 is at least `1.5 × ATR14[-1]`.
  - The **current** ATR is applied to all history (a small inconsistency, not lookahead).
- Zone = bar i's high/low. Mitigation is as for FVGs, checked from i+2. Bearish mirrors.
- **QMR:** the most recent **mitigated** order block in the direction.

**Liquidity sweeps** (`liquidity_sweeps`): for each swing, the first bar from `swing.idx + 6` onward with `high > level` and `close <= level` (or the low mirror).

**Protection** (`protection`, the "inducement veto"):
- Take the latest break (way, break_idx, break_level).
- Candidates are opposite swings (lows for an up break) before `break_idx`.
- **Protected swing:** the most recent candidate that swept — a low-side sweep at `at < break_idx`, with `|at − swing.idx| <= 5` and `swing.level <= the swept level`. If none swept, use the last candidate with `swept = False`.
- `leg = |break_level − protected.level|`.
- **Trigger:**
  - Swings at length 2 of the same type, strictly between `protected.idx` and `break_idx`, with level above the protected level (for an up break).
  - Choose the one closest in price to the protected level.
- `depth = |break_level − trigger| / leg`.
- **Shaped:** within ±4 bars of the trigger,
  - `(2nd lowest − lowest) <= 0.5 × window range`, and
  - prominence > 0, i.e. the chord between the window's end lows lies above the trigger low.
- **Held:** swept and a trigger exists and `depth >= 0.5` and shaped.

**Equilibrium** (`equilibrium`, read on the **first higher TF** that returns one):
- Range = from the bar index of the second-to-last structure event (or from 0) to the end.
- `mid = (max high + min low)/2`; premium if the last close > mid.

**Firing chain** (needs at least 30 bars):
1. A latest break exists and is recent: `n − idx <= 10`.
2. `protection` is not None, and if it is not held, the inducement veto (env `SAGE_SMC_INDUCEMENT`, on by default) returns nothing.
3. Zone = the nearest of [unmitigated FVGs and order blocks in the direction, plus the QMR]; it must be within `0.5 × ATR14` of the close.
4. Equilibrium veto (`SAGE_SMC_CONTEXT`, on by default): no BUY in a higher-TF premium, no SELL in a higher-TF discount.
5. `swept` = any liquidity sweep (either side, any swing) at index ≥ `break_idx − 5`.
6. Higher-TF agreement = higher TFs whose `structure(…, 5).trend` equals the way (each needs at least 12 bars). `grade_reaction(True, swept, credit)`.
7. Extras: choch, protected, and qmr (if the zone is a mitigated order block). `adjust` promotes A+ to S.

**Emits:**
- confidence = `base_conf(grade)`.
- **Bug:** the emitted grade is forced to B+ whenever the computed grade is A (only B+, A+ and S pass through), while the confidence stays at 81.
- **SL** = `sweep_zone(zone.mid, side by direction, ATR14, σ20, entry = close)` with no other levels.
- **No TP**, so the composer assigns 1/2/3 × simple ATR14.
- **Computed consequence:** the sweep stop sits at least ~2 ATR beyond the zone mid on forex (1.5 + 0.5) and wider on crypto. A 2-ATR second rung then cannot clear the composer's 1.75R floor, and the first rung cannot clear 1R. **smc cannot lead a composed setup under the default constants**; it only corroborates.
- **Data:** OHLC on this TF and the higher TFs.

### 2.4 `structural_setup` — `peers/structural_setup.py:propose/analyze` (doc SMC_MENTORSHIP_REVIEW.md; family "smc")
- **Config:**
  - `swing = 5`, `tolerance = 0.5` ATR, `stop = 0.5` ATR, `reward = 3.0`, `freshness = 3`, `levels_within = 1.0`, `range_lookback = 20` (env `SAGE_SETUP_*`).
- **Chain** (every step is a veto):
  1. A latest structure break with `n − idx <= 5 × 3 = 15` bars.
  2. Protection must be held, with a trigger (§2.3).
  3. **Higher-TF equilibrium:** a BUY in premium (or a SELL in discount) on the first higher TF is a veto.
  4. **POI** (`point_of_interest`):
     - Candidates: the QMR (latest mitigated order block in the direction), unmitigated order blocks, and unmitigated FVGs.
     - Each needs `zone.mid <= trigger` (bull) or `>= trigger` (bear), and, if the higher-TF equilibrium is known, `zone.mid <= mid_htf` (bull).
     - Pick the one whose mid is nearest the trigger.
  5. **Arrival:** `dist(close, zone) <= 0.5 × ATR14`, measured from the zone's edges.
  6. **Geometry:**
     - entry = `zone.mid`
     - stop = `protected_level ∓ 0.5 × ATR14 × tilt`, with tilt from §1.11
     - `R = |entry − stop|`; ladder = entry ± 1R / 2R / 3R; target = entry ± 3R
     - There is no check that the stop is on the correct side (possible if `zone.mid` sits beyond the protected level).
- **Grade:**
  - credit = higher TFs whose structure trend equals the way.
  - `grade_reaction(True, protected.swept, credit)`; extras = protected (always), choch, qmr, and "at a level" (a bjorgum zone within 1 ATR of the entry). `adjust` applies.
- **Kelly at R:R = 3.0** (computed): p = 0.277, edge +0.108, multiplier 0.77.
  - Confidence: B+ 55.6, A 62.5, A+ 69.5, S 74.
  - So **only A+ and S clear the composer's confidence bar of 65 when alone**.
- **Composer interaction** (computed): the composer uses entry = the **signal close**, not `zone.mid`. Its first-rung check `|tp1 − close| >= |close − stop|` fails whenever the close is still on the far side of the mid. In effect the setup composes only once the **close has reached or passed `zone.mid`** and is still within 0.5 ATR of the zone.
- **Emits:** SL = plan.stop and TP = (1R, 2R, 3R) from `zone.mid`.
  - Features record crt (higher-TF candle), range phase (bjorgum bracket + `crt.read_range` over 20 bars), CUSUM, analogues, clock, volume profile at the entry, tilt and funding. None of these gate.
- **Data:** OHLC and volume (volume only for the profile feature).

### 2.5 `zma` — `peers/zma.py:analyze` (doc zma.md; **supporting = True**, so it never leads)
- **Applicability** (`applicable`; needs at least 60 bars):
  - Over the last 100 log returns: skew ≤ 1.5 and excess kurtosis ≤ 6.0, or else the bipower rescue passes.
  - **Bipower rescue:**
    - On the last 30 returns, `BV = (π/2)·Σ|r_i||r_{i+1}|`; `c = sqrt(BV/30)`.
    - Keep returns with `|r/c| <= 3` (at least 20 required); they must pass the skew/kurtosis limits.
  - **AND** the Lo–MacKinlay variance ratio (k = 5, window 100) must be ≤ 1.5.
- **z-score:**
  - Period 50. Weights = softmax(|pct change|) within the window; z = (close − weighted mean) / weighted population std.
  - Caveat (computed): percentage changes are about 1e-3, so softmax is almost uniform and **this is effectively the plain population z-score over 50 bars**.
- **Thresholds:** strong / weak = the 85th / 65th percentile of |z| over the last 250 values. Fallback 1.5 / 1.0 if fewer than 10 values. The current value is included. The regime-specific percentiles in `REGIME_PERCENTILES` are never used.
- **Momentum** (`classify_momentum`):
  - `slope_t = (mean of the second 25 closes − mean of the first 25) / first close × 100`.
  - `thr = median(|slope|)` over the last 200 slopes.
  - Rising Demand if `slope > thr` and `slope > previous slope`; Weakening Demand if `slope > thr` and not rising; Rising / Weakening Supply mirror these; otherwise Neutral.
- **Recommendation** (`recommend`):

| condition | call | grade |
|---|---|---|
| z < −strong & (RisingDemand or WeakeningSupply) | STRONG BUY | A+ |
| z < −weak & (same momentum) | BUY DIP | B+ |
| z < −strong & (Neutral or WeakeningDemand) | BUY (Oversold) | B |
| z < −strong & RisingSupply | WAIT | — |
| mirrors for the sell side | STRONG SELL (A+) / SELL RALLY (B+) / SELL (Overbought) (B) | |

- **Base confidence:** `100·Φ(|z|)` (two-sided as written: `0.5·erfc(−|z|/√2)`). ×1.10 if momentum is aligned, ×0.85 if opposed; capped at 95; 0 if `|z| < weak`.
- **Vetoes:** ADX ≥ 28 against the direction; then Kelly with `b = |mean − close| / σ = |z|` (computed: passes for |z| in [0.62, 3.44]).
- **Emits:** SL = close ∓ σ (one weighted std); all three TP rungs = the weighted mean.
- **Data:** closes, plus high/low for the ADX.

### 2.6 `anomaly` — `peers/anomaly.py:analyze` (not supporting, no grade, no geometry)
- `r` = log returns. Baseline = the 60 returns **before** the current one (current excluded).
- `z = (r_last − median) / (1.4826·MAD)`; if MAD = 0, fall back to the std; if that is 0, nothing.
- Fires if `|z| >= 5.0` (env `SAGE_ANOMALY_THRESHOLD`). Tuned: 5 is about the 99th percentile on six crypto majors.
- **Body position** `pos = (C − L)/(H − L)`:
  - BUY if `z > 0` and `pos >= 0.65`; SELL if `z < 0` and `pos <= 0.35`.
  - Otherwise the signal has no direction (confidence `min(50, 30 + 5·(|z| − 5))`).
- **Directional confidence:** `min(80, 45 + 8·(|z| − 5))`. It reaches the composer's 65 only when `|z| >= 7.5` (computed).
- **No SL/TP**, so the composer uses a 1 × ATR14 stop and 1/2/3 × ATR targets. The R:R to the second rung is 2.0, which passes.
- **Data:** OHLC.

### 2.7 `divergence` — `peers/divergence.py:analyze` (supporting; leaders BTC/USDT and ETH/USDT)
- Skips the leaders themselves.
- Uses simple returns, aligned **by tail only** (no timestamp join), so a missing bar silently misaligns them.
- **Per leader:**
  - Over the last 30 returns: R² = corr², β = cov/var.
  - The leader is skipped if R² < 0.3.
  - Residual series = follower − β·leader over the whole span (in-sample β).
  - Rolling 5-bar residual sums; `z = (last − mean(last 60)) / std(last 60)`, current value included.
- The leader with the highest R² is chosen. Fires if `|z| >= 1.5`, direction = sign(z) (persistence / momentum, not reversion).
- confidence = `min(90, 40 + 25·min(|z|, 3) + 30·R²)`. No grade, no SL/TP.
- **Data:** the leaders' OHLC on the same TF (cross-asset).

### 2.8 `correlation` — `peers/correlation.py:analyze` (supporting; family "cross_asset"; doc correlation.md)
- Needs at least 2 companions loaded.
- **Per companion:**
  - Regime direction (+DI vs −DI, §1.3) over the last 120 bars ("slow") and the last 40 bars ("quick").
  - If they disagree → no direction. Otherwise that direction; "settled" if both agree.
  - Weight 2.0 if settled, else 1.0.
- Lean = the larger of the weighted up and down totals. Fires if at least 2 companions are readable and `share = max/(up + down) >= 0.66`.
- **Logic flaw (risk):** companion directions are raw price directions, not oriented to the dollar. For a USD-quote pair, the USD-base companions (USDJPY, USDCHF, USDCAD, USDCNH) and the CME futures are counted with the same sign.
- confidence = `min(75, 35 + 30·share + 5·n_settled)`.
- **Data:** cross-asset OHLC.

### 2.9 `usd_confluence` — `peers/usd_confluence.py:analyze` (fires only on EURUSD; not supporting, no grade, no geometry)
- **Config:** `lookback = 120`, `pivot = 10`, `at_level = 0.4` ATR, `minimum = 4`, `alignment = 0.66`.
- Basket: EUR, GBP, AUD, NZD (USD quote) and JPY, CHF, CAD (USD base). CNH is excluded.
- **Per pair:**
  - On the last 120 bars: levels = smc swings (length 10) plus the window's max high and min low (current bar included).
  - Nearest level to the close; at a level if `|level − close| <= 0.4 × ATR14`.
  - `rising = (nearest >= close)`; the dollar is UP if `rising == usd_quoted`.
- Fires if at least 4 pairs are loaded and at least 4 are at a level. If `share >= 0.66`, EURUSD gets SELL when the dollar is up and BUY when it is down; otherwise it emits with no direction.
- confidence = `min(90, 35 + 8·ready + 25·alignment)`, which always clears 65 when directional.
- **Composer consequence:** it composes on EURUSD with a 1-ATR stop and 1/2/3-ATR targets, graded B+.
- **Tuned:** pivot 10 and 0.4 ATR were picked so the peer fires directionally about 12% of the time (OANDA, 7 majors, 1h/4h).
- **Data:** cross-asset FX OHLC.

### 2.10 `latent_levels` — `peers/latent.py:analyze` (supporting; family "levels")
- **Config:**
  - `lookback = 400` (effectively 300), `points = 20`, `confirm = 3`, `merge = 0.5`, `noise = 0.35`, `drift = 0.05`, `floor = 0.15`, `cap = 1.0`, `horizon = 5`, `half_life = 120` bars, `near = 0.35`, `minimum_touches = 4`, `edge = 0.08` (env `SAGE_LATENT_*`).
  - Volatility = ATR14 of the window.
- **Levels:**
  - `pips.find(window, count = 20, confirm = 3, minimum = 0.5·ATR)`.
  - In time order, each turn either merges into the nearest level within 0.5 ATR (Kalman predict with variance += 0.05·ATR, update with noise (0.35·ATR)²) or starts a new level (variance (0.5·ATR)²).
  - Zone half-width = `clip(σ_filter, 0.15·ATR, 1.0·ATR)`.
- **Per level, per side** (bars `1 .. n−6`):
  - On zone entry by the close: `from_above = prevC > level`; `push = (C[i+5] − level)/ATR`.
  - Trapped if the close went through the zone and `C[i+5]` is back inside.
  - Weight = `0.5^(age/120)`.
- `P(up) = (w_up + 0.5·4) / (w + 4)`.
- **Fires when** the nearest level is within 0.35 ATR, the side's raw touches ≥ 4, and `|P − 0.5| >= 0.08`. Direction = BUY if P > 0.5.
- **SL:** BUY = `zone_low − 0.15·ATR`; SELL = `zone_high + 0.15·ATR`. **TP:** `target_ladder` from the other levels.
- confidence = `min(80, 40 + 100·|P − 0.5|)`.
- **Repaint risk:** the PIP set is a global fit over the window, so recompute every bar.
- **Data:** closes (ATR uses OHLC).

---

## 3. `analysis/` — combining and composing (the actual "setup")

### 3.1 `ensemble-vote` — `ensemble.py:combine`
- Takes all actionable signals, **including supporting ones**.
- The expert is chosen by `select_expert(symbol, regime)`, but compose **never passes a regime**. So it is **always the default expert: every weight 1.0, `min_agreement = 2`**.
  - The `EXPERTS` table (weights for "breakouts", "ame", "crypto_alpha", none of which exist as peers) is dead code. Doc name matches: breakouts.md, ame.md, crypto_alpha.md describe peers that are not implemented.
- `weighted[side] = Σ confidence`; the winner is the larger, with BUY winning ties.
- No direction if fewer than 2 agree, **or** if the loser is above 0 and `winner < 1.5·loser` (contested).
- Vote confidence = `min(100, Σconf_win / Σweight_win)`, i.e. the mean confidence of the agreeing signals.

### 3.2 `compose-setup` — `decision.py:compose` (doc decision.md)
1. Needs at least one actionable, **non-supporting** signal.
2. **Vote.** If it has no direction **and anything dissented → no setup.** This means **one opposing actionable peer (zma, divergence, correlation, latent included) vetoes a lone setup.** Otherwise direction = the most confident non-supporting signal.
3. **Leader** (supplies the geometry): among agreeing non-supporting signals, the highest completeness, then the highest confidence.
   - Completeness: 3 = graded with SL and TP; 2 = SL and TP; 0 = otherwise.
   - entry = leader.price (the signal-bar close).
4. **Levels** (`levels`):
   - If the leader lacks SL or TP, fill the missing part: stop = `entry ∓ 1·ATR`, ladder = `entry ± 1, 2, 3·ATR`.
   - ATR here is the simple 14-bar mean.
5. Futures (`currency_futures`, `metal_futures`) never compose unless `SAGE_FUTURES_MODE = standalone`.
6. **`pays_its_risk`:** the first rung must be on the correct side and `|tp1 − entry| >= 1.0·|entry − stop|`.
7. **Reward:risk to the SECOND rung** `>= 1.75`, or `>= 1.3` for synthetics.
8. **Confidence** (the vote's if decided, otherwise the leader's) `>= 65`. This uses the constant; `confirm_confidence()` reads env `SAGE_CONFIRM_CONFIDENCE` but is never called.
9. **Grade** (`grade_for`):
   - Base = the highest grade among agreeing non-supporting signals (the "grader"). If ungraded, B+ when the ratio clears the floor, else B.
   - `score = support − against (+0.5 if ratio >= 1.5 × floor)`.
     - Support = Σ over **families** of the best weight among agreeing peers other than the grader.
     - `weigh(peer)` = 0.25 if unmeasured; 0 if the trust lower bound ≤ 0.5; otherwise `min(1, (LB − 0.5)/0.25)`.
     - Plus echoes (§3.3). Against = the same weighting over dissenters.
   - score ≥ 2 → up two rungs; ≥ 1 → up one; ≤ −1 → down one. Ladder: B, B+, A, A+, S.
- **Output:** `Setup(direction, entry = close, stop, targets, reward_risk to tp2, grade, confidence)`, published as `model = "setup"`.
- **No exit logic** beyond SL and TP. Outcome scoring is in §4.

### 3.3 `echoes` — `echoes.py:Echoes`
- Keeps each peer's last direction per (symbol, source, TF).
- Weight `0.7^age`, depth 4. Age increments **per analysis call**, which in production happens every collection cycle, not every bar.
- A changed direction replaces the old echo.
- Adds to composer support by family, excluding the peers that spoke on this bar.
- In a backtest, use per-bar ages or drop echoes.

### 3.4 Plumbing in `analysis/`
- `context.py`: funding, OI, news, calibration and trust. Covered in §6; feeds features plus the Kelly and trust inputs.
- `store.py`: the latest setup per series.

---

## 4. `quality/` — how the system scores its own signals (a ready-made exit spec)

### 4.1 `outcome-barriers` — `barriers.py:outcome_for` / `barriers`
- target = **tp_ladder[0]** and stop = sl, if the peer placed both.
- Otherwise symmetric **±1.5 × ATR**, using the simple mean of 14 TRs from the last 30 stored bars; fallback ±1% of price.

### 4.2 `outcome-resolution` — `store.py:OutcomeStore.resolve`
- **Horizon in bars:** 15m 96, 30m 96, 1h 48, 2h 36, 4h 30, 1d 12, 1w 8; default 30.
- **Walk:** bars with `timestamp > opened_at`, where `opened_at` is the wall-clock time the signal was recorded.
  - Because timestamps are bar opens, this **skips the bar that opens at the signal's close**; resolution starts one bar later.
- **Per bar:** the stop is checked first (a bar touching both counts as a stop); then rungs are counted in order (`while` loop).
  - A win means the first rung was touched before the stop.
- **Expiry** at the horizon counts as a loss. `reached` and `after_stop` (rungs touched after being stopped) and the MAE/MFE excursions are recorded.
- One prediction per (peer, symbol, source, TF, bar).

### 4.3 `wilson-gate` — `calibration.py:Gate.judge` (doc name match promotion.md)
- Wilson lower bound with one-sided z = 1.64 over the last 300 resolved outcomes.
- Below 25 samples: live (warm-up). If LB ≤ 0.5: held.
- Shadow peers (env `SAGE_SHADOW_PEERS`) are promoted when n ≥ 40 and LB ≥ 0.55.
- Used only by notification delivery.

### 4.4 `calibration` / `trust` — `store.py:calibration`, `store.py:trust`
- Calibration: per-(peer, grade) win rates with n ≥ 25, excluding inherited records unless the peer is listed in `SAGE_INHERIT_CALIBRATION`. This feeds Kelly's p.
- Trust: per-peer Wilson LB with n ≥ 25. This feeds the composer's `weigh`.
- **Path-dependent:** a faithful backtest must either rebuild these online from simulated outcomes or set them empty, which is the default prior behaviour.

### 4.5 Plumbing
`carryover.py` (imports old outcomes), `service.py` (loops), `models.py`.

---

## 5. `notifications/filters.py` — delivery rules (doc NOTIFICATION_FILTER.md, dispatch.md)
These filter which composed setups reach a phone. Treat them as optional portfolio-level filters in a backtest.

- **`grade-floor`:** grade ≥ **A** (`SAGE_NOTIFY_MIN_GRADE`). Tuned on 293 composed setups:

| grade | n | win rate | E[R] |
|---|---|---|---|
| S | 39 | 56% | +0.62 |
| A+ | 12 | 58% | +0.41 |
| A | 111 | 61% | +0.92 |
| B+ | 91 | 25% | −0.23 |
| B | 40 | 23% | −0.28 |

- **`tf-block`:** synthetics block 1m / 3m / 5m / 15m; all other classes block 1m / 3m / 5m.
- **`market-hours`** (`sessions.is_open`):
  - FX, commodities and indices: closed Friday 21:00 UTC to Sunday 21:00 UTC.
  - Equities: 14:30–21:00 UTC on weekdays.
  - Crypto and synthetics: always open.
- **`release-blackout`** (`calendar.blackout`): a High-impact ForexFactory event for either currency leg (index → its currency) within **±30 minutes**.
- **`repeat-cooldown`:** the same (instrument, TF, peer, direction, grade-or-better) within `max(4 h, 2 bars)`.
- **`flip-guard`:**
  - The same level, bucketed at 0.1 ATR via `evidence.level / evidence.atr`, called the opposite way within the same cooldown.
  - Note: `evidence.level` exists only for level_reaction, so other peers fall back to price.
- **`bar-dedup`:** the same signature on the same bar.
- **`rate-cap`:** 5 per 4 h, with A+ and S exempt.
- **Wilson gate** (§4.3).
- `selection.py` holds alerts for 120 s and sends them best first, ranked by (grade, reward:risk, confidence).

---

## 6. `market/` and `sentiment/` context — none of these gate a setup

- **`funding-crowded`** (`analysis/context.py:funding`):
  - `annualised = rate × 365·24 / interval_h`, or `× 1095` if the interval is unknown.
  - `crowded = long / short` if `|annualised| >= 0.25`.
  - Latest MEXC futures sample. Label only.
- **`oi-change`** (`context.py:open_interest`): `(OI_now − OI_24h_ago) / OI_24h_ago`, in contracts. Label only.
- **`news-busy` / `news-tone`** (`context.py:news`, `sentiment/lexicon.py:read`, `sentiment/similarity.py:distinct`):
  - Stories in the last 6 h against a 336 h baseline, after de-duplication (TF-IDF-style cosine > 0.72 counts as one story).
  - `usual = baseline_count × 6/336`; busy if `count >= max(3, 2·usual)`.
  - **Tone:** a headline lexicon (positive / negative word weights of 1.0 / 0.7 / 0.4; a negator flips the next 3 words; average over hits, clipped to ±1; neutral if `|score| < 0.15`).
  - Tone is oriented to the instrument: +1 if the headline names the base currency or asset, −1 if only the quote.
  - Rendered only, and only when at least 3 toned stories average `|tone| >= 0.2`.
  - Uses the **wall-clock** window, so it is not point-in-time for a backtest without an archived news store.
- **`liquidation-shelves`** (`market/liquidations.py:cluster_positions`):
  - Hyperliquid's top 120 wallets (account ≥ $100k); positions ≥ $100k with a liquidation price within 50% of mark.
  - Bucketed at 0.5% of mark and weighted by USD; side = long-flush if long USD ≥ short USD, else short-squeeze; keep the top 12.
  - **Nothing consumes it.**
- **`sessions` / `calendar`:** as in §5.

---

## 7. Lookahead, repaint and implementation risks
1. **Higher-TF bars must be as-of.** bjorgum, level_reaction, smc and structural_setup all read higher-TF zones, structure and equilibrium. Production uses closed bars only, but a backtest must also not use a higher-TF bar that closes after the lower-TF bar's close.
2. **Recompute walk-forward** for: smc structure (retroactive swing replacement), bjorgum zone merging, latent PIPs, and the order-block ATR (`ATR14[-1]` applied to all history). A vectorised full-history pass will repaint.
3. Pivots, PIPs, analogues, CUSUM and the anomaly baseline are lookahead-safe by construction. The zma thresholds and divergence z include the current value (mild in-sample). Divergence uses an in-sample β and tail-aligned series with no timestamp join.
4. **The entry is the signal bar's close.** Production fills at least one collection cycle later, and the outcome walk also skips the next bar.
5. structural_setup **quotes** `zone.mid` as its entry while the composer measures from the close (see §2.4).
6. The emitted grades and confidences of level_reaction, structural_setup and zma depend on the runtime calibration and trust state.
7. **Bugs and dead code:**
   - smc reports grade A as B+.
   - The `EXPERTS` weights, `REGIME_PERCENTILES` and `confirm_confidence()` are never used.
   - correlation does not orient inverse-quoted pairs.
   - The level_reaction Kelly stop differs from its emitted stop.
   - structural_setup does not check which side of the entry its stop is on.

---

## 8. Thresholds that look tuned (from data, not convention)
- Kelly geometry curve; base p 0.30.
- Sweep multiples per class; sweep stop buffer 0.5.
- Anomaly z 5.0.
- zma variance-ratio limit 1.5.
- usd_confluence pivot 10 / 0.4 ATR.
- Delivery grade floor A.
- ADX 28.
- Rate cap 5 per 4 h, priority A+.
- Composer minimum R:R 1.75 / 1.3, confidence 65.
- Trust scale 0.5 → 0.75.
- smc `MIN_DEPTH` 0.5 and minor-swing length 2 (the latter changed after random-walk testing: firing rate 0.2% vs 10.5% unfiltered).
- Bjorgum knobs ("tuned against a live book").

---

## 9. Not backtestable on OHLC/exchange data alone
- **News busy/tone:** needs a point-in-time headline archive; the live window is wall-clock.
- **Liquidation shelves:** a Hyperliquid wallet snapshot with no history, kept 6 h; nothing consumes it.
- **Funding and OI labels:** reconstructable from exchange history, but they are labels only.
- **Release blackout:** needs historical High-impact calendar data; feasible with an archive.
- **Calibration, trust, the Wilson gate and Kelly measured p:** path-dependent on the live outcome ledger and on records inherited from the old system. Simulate them online or use the priors.
- **Notification ledger effects** (cooldown, rate cap, flip guard, 120 s hold): wall-clock and process state.
- **Echoes:** cadence-dependent.
- **Tick spread:** collected but read by nothing.

---

## 10. Pure plumbing (no trading logic)
- `api/app.py, config.py, hub.py, routes.py, service.py, ws.py` — HTTP/WebSocket API.
- `channels/*` — message bus backends (memory, redis, persistent), backoff, dead-letter queue, serializer, metrics.
- `bus.py` — topic names and publish/subscribe.
- `stack.py`, `cli.py`, `logging.py` — process wiring, CLI and logging.
- `journal/*` — decision log.
- `market/ccxt.py, mexc.py, tradingview.py, source.py` — bar, funding and OI fetchers.
- `market/ticks.py` — tick stream.
- `market/news.py` — RSS, TradingView headlines and IMF reserves collector.
- `market/service.py` — collection loop and best-venue announce.
- `market/config.py` — universe and env.
- `market/store.py` — Mongo.
- `market/models.py` — data types, retention and `closed_only`.
- `market/context.py` — side-car scheduler.
- `market/assets.py` — classification.
- `notifications/render.py, sanitize.py, telegram.py, discord.py, notifier.py, record.py, models.py, config.py, calendar.py, upcoming.py, service.py` — formatting, transport and event heads-ups.
- `analysis/store.py`, `quality/carryover.py`, `quality/service.py`, `sentiment/service.py` — storage and loops.

---

## 11. Code-cited docs and name matches
- **Cited in code:** SMC_MENTORSHIP_REVIEW.md (smc, structural_setup, crt), SMC_ICT_RESEARCH.md (session), SYMMETRY_RESEARCH.md (asymmetry), PRICE_GEOMETRY_RESEARCH.md (profile), zma.md, deferred.md (sweep zone, liquidations).
- **Name matches:** bjorgum.md, smc.md, correlation.md, decision.md, mtf.md (higher-TF ladder), NOTIFICATION_FILTER.md, promotion.md, KEY_LEVELS_RESEARCH.md, ame.md (the `crt.read_range` phase only).
- **Docs with no implementing code here:** breakouts.md, crypto_alpha.md, defi_alpha.md, BTC_DOMINANCE.md, CISD.md, proximity.md, SHORT_CANDIDATE_SPEC.md.
