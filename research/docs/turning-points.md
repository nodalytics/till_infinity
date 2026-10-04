# Turning points: what they share, how violent they are, and whether structure persists

**Measured, 2026-10-03/04. Turns have a real description, but it gives neither a direction nor an entry
better than a random walk.** Major turns carry violent reversal bars far more than ordinary lows do, and
more than matched walks do. Traded with fixed targets or with exits decided by the market, though, the
signature does no better than the same signal on walks. Its lift over "buy every low" is geometry, not
information. The one kind of violence that real markets add beyond walks is a range shock relative to
the bar's own recent ranges. Swing structure (HH/HL against LH/LL) does not persist beyond chance: real
markets make the next extreme *less* often than walks do.

Not to be confused with [turns.md](turns.md), which asks whether a *weekly* major turn can be forecast
from daily state. This page reads the bar at the turn itself.

Every test below was pre-registered in the script's docstring, or in a frozen JSON for the trades,
before it ran. Controls are walks matched to each series (`mcfl.synth.matched_walk`), carrying the real
timestamps and, for the trades, the real costs in ATR units.

> **Correction, 2026-10-04 (found by the sweeps study).** MCFL labels BREACH_REVERT by the side of the swept
> swing: DOWN is a swing low traded through and closed back above, the bullish one. `turn_trade.ups` read
> the UP label, so **T2 in sections 2-3 (and `T_any`, `SIG` in the zone and Deriv studies) took the wrong
> side**: a swing *high* swept at a 12-bar low, which fired on about 15 of 1,658 lows on a test walk against
> 177 for the right side. The table in section 1 lists the same event as "BREACH_REVERT" when it is the
> UP-labelled (bearish) one. **DISPLACE_C (T1) and DELIVERY_SHIFT (T3) are labelled the other way (UP =
> bullish) and are unaffected**, so the result that passed on fresh coins (DISPLACE_C, `turn_confirm_rule.json`)
> stands. `ups()` is fixed; T2 and T_any have not been re-run with the right side.

## 1. What turns share (`ideas/turns.py`)

A **major turn low** is the lowest low of 10 bars either side, after which price rallies 3 ATR before
trading below it. An **ordinary low** is the same low without that rally. Highs are pooled on the
flipped chart. The labels only group bars. The features are MCFL v1 tokens and productions known at
the turn bar's close. The data is MT5, 10 markets on 1h and 4h: 845,402 bars and 21,961 major turns
(25,962 on the walks). The base precision is 0.162 on real data and 0.151 on walks.

| feature at the turn bar | lift, real | lift, walk | excess |
|---|---|---|---|
| DISPLACE_C the turn's way | **3.83** | 1.49 | +2.34 |
| BREACH_REVERT | **2.58** | 0.87 | +1.71 |
| DELIVERY_SHIFT (CISD) | **2.17** | 1.26 | +0.90 |
| DISPLACE_C in the last 5 bars | 1.91 | 1.01 | +0.91 |
| EXTREMELY_LARGE candle | 1.77 | 1.05 | +0.72 |
| OUTSIDE bar, bullish engulf | 1.41-1.43 | 1.13-1.18 | +0.25-0.28 |
| *depleted:* VERY_SMALL / SMALL candle | 0.49 / 0.58 | 0.93 / 0.99 | -0.44 / -0.41 |
| *depleted:* PIN | 0.87 | 1.15 | -0.27 |

The lift is P(feature | major turn) / P(feature | ordinary low). Turns are violent: displacement, a
breach that reverts, and a delivery shift, on large bars. Quiet bars and pins are rarer at real turns
than chance gives. That holds on 1h and on 4h.

## 2. Trading the signature with fixed R: fails (`ideas/turn_trade.py`, `turn_rule.json`)

The rule was frozen before the run. At a 12-bar low knowable at bar t, if bar t completes DISPLACE_C
(T1), BREACH_REVERT (T2) or DELIVERY_SHIFT (T3), or any of them (T_any), enter at t+1's open with a stop
0.1 ATR beyond the 3-bar low. Targets are 1, 2 and 3R, held at most 5 days, with costs. The primary is
T_any at 2R on 12 Binance perpetuals (1h and 4h).

**Primary: -0.015R [-0.036, +0.005]** over 42,885 trades (-0.019 before 2024, -0.011 after). That
fails. Entering at every 12-bar low gives -0.167R, so the signature lifts entries by about 0.15R, but
not to zero. (The walk baseline in this run was broken by cost scaling. Section 3 uses the corrected
walk.)

## 3. Exits decided by the market: fails, and the lift is geometry (`turn_rule2.json`, `MODE=exits`)

The rule was frozen before the run, with the same signal, entry and stop.
- **E1 (primary):** a trailing stop at the best high since entry minus 2 ATR.
- **E2:** exit at the next open after a DELIVERY_SHIFT against the trade.
- Trades are capped at 10 days.

**Amended before the real run:** a smoke test had the trailing exit "earning" +0.6R a trade on
driftless walks built from 8 sub-steps a bar. Coarse paths jumped across stops that were then filled
exactly at the stop. Every stop fill now takes 0.05 ATR of slippage, and walks use 256 sub-steps a bar.

| | E1 R [90%] | E2 R | P(≥1R) | P(≥4R) | P(≥10R) |
|---|---|---|---|---|---|
| Binance T_any, real | **-0.045 [-0.066, -0.026]** | -0.015 | 0.398 | 0.049 | 0.003 |
| Binance T_any, walk | -0.046 | -0.025 | 0.407 | 0.045 | 0.001 |
| Binance all 12-bar lows, real | -0.199 | -0.167 | 0.429 | 0.126 | 0.027 |
| Binance all 12-bar lows, walk | -0.221 | -0.198 | 0.416 | 0.146 | 0.040 |
| MT5 T_any, real | -0.036 | -0.024 | 0.373 | 0.048 | 0.003 |
| MT5 T_any, walk | -0.051 | -0.035 | 0.405 | 0.042 | 0.001 |

**The primary fails.** The signal's lift over all lows (about +0.15R) appears equally on walks
(-0.221 → -0.046). A violent bar at a fresh low means the stop sits close to a just-completed extreme,
and that geometry is what improves the trade, on any random path. The P(N R) curves track the walks.
None of the per-signal or per-timeframe cells clears its walk by a margin that would survive the number
of cells.

## 4. How violent, per timeframe (`ideas/violence.py`)

For every 12-bar low on MT5 and Binance (15m, 1h, 4h, 1d), five force measures of the bar at the low
were split into deciles of P(major turn), real against walks. **VIOLENT** is where the real-minus-walk
excess reaches 80% of its peak. That was the top decile everywhere.

| measure (MT5 threshold) | 15m | 1h | 4h | 1d | P(turn) real vs walk, above it |
|---|---|---|---|---|---|
| range_z (range against the last 10 ranges, in sd) | 2.64 | 3.11 | 2.70 | 2.02 | **0.31-0.34 vs 0.25** |
| body_atr (body / ATR) | 0.76 | 0.74 | 0.66 | 0.70 | 0.56-0.64 vs 0.51-0.54 |
| move_k (the move into the bar, ATR √k) | 1.29 | 1.34 | 1.29 | 1.23 | 0.67-0.74 vs 0.65-0.70 |
| eff3, close_loc | | | | | excess +0.02-0.07 |

- **Only range relative to the bar's own history is real violence.** On walks P(turn) is flat in
  range_z at about 0.25. On real markets it climbs steadily to 0.33. That holds on all four timeframes
  and both venues.
- **Absolute size and travel are mostly geometry.** A bigger body or a longer move into the low is more
  likely to be the extreme on a walk too. The move_k curves lie on top of each other.
- **ATR already does most of the per-timeframe work.** In ATR units the thresholds barely move between
  15m and 1d. Daily needs a smaller range shock (2.0 sd) than 1h (3.1).
- **Caveat:** these walks are iid, so the range_z excess may be volatility clustering, which walks lack,
  rather than information about the side. Section 3, where violent turns traded like walks, fits that
  reading.

## 5. Does structure persist? (`ideas/structure_seq.py`)

MCFL v2 swing labels (HH/LH/EH, LL/HL/EL, known 3 bars after the swing) are read as sentences. Data is
MT5 and Binance on 1h, 4h and 1d. In an UP state (the last high HH, the last low HL) and a DOWN state
(the mirror):

| | real | walk |
|---|---|---|
| the next extreme continues (HH in up, LL in down) | **0.43-0.50** | 0.52-0.54 |
| the next pullback holds (HL in up, LH in down) | 0.53-0.56 | 0.52-0.54 |
| 2 ATR the structure's way first | 0.50-0.52 | 0.48-0.53 |

- **Structure does not predict the side.** 2 ATR the structure's way is a coin flip on every venue and
  timeframe, in both halves.
- **Real trends extend *less* often than walks do.** After an HH, the next high is an HH less often
  than chance. At swing level, trends exhaust more than they extend, and pullbacks hold slightly more
  often. This is consistent, but it shows only between swings.
- **The 97 three-swing contexts** (e.g. `HH HL LH`) differ from walks by at most ±0.08 in P(up first),
  on cells of a few hundred. That is noise.
- The real 5-day move is positive in nearly every context, bearish ones included. That is the sample's
  drift, not structure.

## What this leaves

"Violent" now has a definition per timeframe: a range shock against the bar's own recent ranges,
roughly the top decile (2-3 sd), together with displacement, a breach that reverts, and CISD the turn's
way. It describes turns, and it is the right vocabulary for MCFL. Neither it nor swing structure has yet
given a side or an entry that beats a walk. The open question is whether the range-shock excess survives
walks that keep volatility clustering (GARCH matched). If it does, it is a volatility fact, which this
desk can already forecast ([expansion.md](expansion.md)), not a directional one.

## Re-running

On the lab, with `OUT` and `MT5BT_DB` set:
- `python research/ideas/turns.py`
- `MODE=run|exits|plot python research/ideas/turn_trade.py`
- `MODE=run|plot python research/ideas/violence.py`
- `MODE=run|plot python research/ideas/structure_seq.py`

Plots:
- `violence_curves_{mt5,binance}.png`, `violence_examples.png`
- `structure_persistence.png`, `structure_sentences.png`
- `turn_trades_{winners,losers}.png`
