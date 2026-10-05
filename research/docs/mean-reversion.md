# Mean reversion: twelve classic rules, pairs and the gap fade, against walks: no edge, and one bid-bar artefact

Measured 2026-10-04 on the lab with [`mean_reversion.py`](../ideas/mean_reversion.py), frozen in
[`mr_rule.json`](../ideas/mr_rule.json) before any real-data run. The confirmation cell was picked by a
frozen procedure and committed in [`mr_selected.json`](../ideas/mr_selected.json) before the confirmation
was read. The tick replay of that cell is [`gapfade_replay.py`](../ideas/gapfade_replay.py), registered in
[`gapfade_replay_rule.json`](../ideas/gapfade_replay_rule.json) before any tick was fetched.

## Answer

- **Every textbook reversion rule finds reversion where it exists.** On the OU and AR(−0.2) positive
  controls, each rule earns gross. On real markets after costs, every rule loses, in every asset class
  and on every timeframe. The one exception is the gap fade.
- **Primary 1, Connors RSI(2) with the 200-day filter on MT5 indices daily, fails.** It made +0.272R
  [−0.445, +0.989] over 216 trades, but its first half was −0.68 and the GARCH walk made +0.63.
- **Primary 2 passed as frozen and is not real.** The frozen procedure picked the FX 1h weekend-gap fade
  (Hurst ≥ 0.45). It passed its confirmation at +0.461R [+0.384, +0.531] over 585 trades, and both
  registered spread checks. The broker's own ticks at the reopen then show that the bars' opening price
  could not be traded. Entering at the first executable price, it makes **−0.410R [−0.510, −0.312]**.
  It is negative at every later entry too. The pass was a fill error on bid bars: a measurement
  artefact in the literal sense.
- **Tails:** no rule beats the walks' P(≥4R) or P(≥10R) by more than 0.03, except the gap fade, which
  is the same artefact.
- **Pairs:** a cointegrated positive control earns +0.86R a trade. Real pairs lose −0.08R, and the
  independent walks lose −0.02R.

This agrees with every earlier reversion result: [battery.md](battery.md),
[imported-ideas.md](imported-ideas.md), [chan.md](chan.md), [zma.md](zma.md) and
[gaptrade.md](gaptrade.md) (where "the Sunday spread eats the reversal").

## The design (frozen)

**Rules.** Longs are shown; shorts are the same code on the negated chart. The signal comes at the
close, and the entry is at the next open.

| rule | entry | own exit |
|---|---|---|
| `rsi2_ma` (Connors) | RSI(2) < 10 and close > SMA200 | close > SMA5 |
| `rsi2` | RSI(2) < 10 | close > SMA5 |
| `bb` (z20 is the same rule) | close < SMA20 − 2 sd | close ≥ SMA20 |
| `z50` / `z50_ou` | z50 < −2 (z50_ou: OU half-life on the trailing 200 bars ≤ 50) | close ≥ SMA50 |
| `kelt` | close < EMA20 − 2 ATR10 | close ≥ EMA20 |
| `vwap` (15m, 1h) | (close − rolling-day VWAP)/sd < −2 | close ≥ VWAP |
| `ibs1` / `ibsrev` | IBS < 0.2 | after one bar / first IBS > 0.8 |
| `down3/4/5` | the Nth consecutive lower close | first higher close |
| `gap` (15m, 1h; FX, metals, indices, energy) | first bar after a hole in the clock opens ≥ 0.5 ATR below the prior close | a limit at the prior close, or 8 hours |
| `pair`, `pair_coint` | rolling-OLS log spread z ≤ −2 (fit on the trailing 500 bars, re-fit every 25; `coint` adds DF t < −2.86) | z crosses 0; stop at abs(z) ≥ 4; 100 bars |

- **Regime splits.** Every rule is also split at VR(4) < 0.9 or ≥ 0.9 and Hurst < 0.45 or ≥ 0.45,
  measured on the trailing 100 bars at the signal. That gives 65 single-series variants, plus the 2
  pair variants.
- **Exits.**
  - **own:** the rule's own exit, with a 20-bar time stop and no price stop.
  - **st:** the same plus a structural stop, 0.1 ATR beyond the signal bar's extreme, with 0.05 ATR
    of slippage.
  - R for both is measured against that stop distance.
  - **P(N R)** is the share of trades that reach +N R before −1R within 100 bars, whatever the exit.
- **Costs.**
  - MT5: the spread floor, falling back to the median bar spread for the zero-spread crypto CFDs.
    Binance: 0.07%.
  - A symbol-timeframe whose median cost is above 0.5 ATR was dropped. That removed 19, mostly
    15m crypto CFDs (TRU, XTZ, SHB, MLN, NER, LTC, TRX), plus XPT and XPD at 15m and 1h, and USDCNH at 15m.
- **Data.**
  - MT5: FX 12, metals 5, indices 7, energy 2, crypto CFDs 35, Deriv 15.
  - Binance: 12 coins at 15m, 1h, 4h and 1d.
  - Discovery is everything before 2024. Confirmation is 2024 on, plus the 131 fresh coins (4h, 1d).
  - MT5 indices, energy and every 15m series start in 2024, so they have confirmation data only.
  - The broker database has no stock bars.
- **Controls.**
  - iid and GARCH(0.08, 0.90) walks on each series' own timestamps, with its hour-of-day volatility
    and gaps, 256 sub-steps per bar, the real cost in ATR and the real volume.
  - A coin twin (random side, same exit timing) and the momentum mirror.
  - Positive controls: an OU process (half-life 20 bars) and AR(1) with phi −0.2, on EURUSD, XAUUSD,
    US SP 500 and BTCUSDT timestamps at every timeframe.

## Positive controls: the rules work

Gross mean R per trade, own exit, all timeframes of the panel:

| rule | AR(−0.2) | OU | iid walk |
|---|---|---|---|
| rsi2 | +1.26 | +0.74 | +0.02 |
| rsi2_ma | +1.24 | **−0.43** | +0.07 |
| bb | +1.56 | +3.18 | −0.07 |
| z50 | +1.23 | +5.44 | +0.01 |
| kelt | +1.72 | +4.59 | −0.01 |
| vwap | +1.11 | +6.14 | +0.02 |
| ibs1 / ibsrev | +0.82 / +1.42 | +0.07 / +0.47 | 0.00 |
| down3 / 4 / 5 | +0.73 / +0.75 / +0.77 | +0.21 / +0.28 / +0.31 | ~0 |

- **Every rule earns on at least one control.** The 200-MA filter is a trend filter, so it is wrong on
  an OU with a single mean. It is right on AR(−).
- **Cointegrated pairs** earn +0.896 gross and +0.857 net. Independent walks earn −0.002 gross.
- **With the structural stop, the controls earn only +0.1 to +0.2R gross** (OU band rules +0.3 to
  +0.6), and the cost makes most of them negative. A tight stop under the signal bar costs about
  0.2 to 0.9R a trade in spread at 1h and below. That geometry cannot carry the spread even when
  the reversion is real.

## Real markets: per asset class (all timeframes pooled, net R)

**Confirmation, own exit:**

| rule | FX | metals | indices | energy | crypto CFD | Binance | pooled |
|---|---|---|---|---|---|---|---|
| rsi2_ma | −0.36 | −0.37 | −0.12 | −0.01 | −0.24 | −0.47 | −0.31 |
| rsi2 | −0.45 | −0.56 | −0.19 | −0.14 | −0.36 | −0.61 | −0.43 |
| bb | −0.25 | −0.97 | −0.07 | −0.23 | −0.48 | −0.71 | −0.48 |
| z50 | −0.52 | −1.45 | +0.07 | −0.43 | −0.71 | −0.91 | −0.68 |
| kelt | −0.17 | −0.76 | −0.05 | +0.05 | −0.51 | −0.85 | −0.49 |
| vwap | −0.42 | −1.63 | −0.11 | −0.38 | −0.66 | −0.84 | −0.65 |
| ibs1 | −0.87 | −0.76 | −0.35 | −0.49 | −0.65 | −0.87 | −0.72 |
| down3 | −0.52 | −0.48 | −0.18 | −0.32 | −0.37 | −0.47 | −0.41 |
| gap | **+0.40** | +0.09 | +0.15 | −0.01 | – | – | +0.21 |
| pair | −0.04 | −0.23 | +0.03 | −0.27 | −0.12 | −0.07 | −0.07 |

The structural-stop exit is worse everywhere (pooled −0.50 to −0.84), except the gap fade. **Fresh
coins** (4h, 1d) give the same picture: every rule ≤ +0.08R (`rsi2_ma` 4h +0.075 [−0.07, +0.22]),
and the band rules lose −0.4 to −1.7R.

**Against the walks.**
- Real minus walk is positive in most cells: about +0.1 to +0.3R with the stop, and largest at 15m
  and 1h.
- Two things make it up:
  - **Cost scaling.** Real signal bars give wider structural stops than walk bars, so cost in R is
    lower (bb 15m: 0.61R real against 0.81R on walks).
  - **A small genuine short-horizon reversal.** Gross own-exit R at 15m and 1h is +0.09 to +0.30 for
    rsi2, rsi2_ma, ibs1 and down3, against about 0 on walks. Real P(+1R before −1R) is 0.37 to 0.40
    against 0.33 to 0.36.
- This is the bid-ask bounce already documented in [sequencing.md](sequencing.md). It is smaller than
  the spread, and at 4h and 1d it vanishes or turns negative. Fading bands at 1d loses gross, which
  is momentum.

**Tails.** P(≥4R) real minus walks, pooled: −0.008 to +0.016 for every rule, and P(≥10R) the same.
The largest are ibs on crypto CFDs (+0.03) and the gap fade (+0.04 to +0.10, the artefact below).
Nothing shows tail excess.

**Deriv, reported apart (all dates):**
- **Diffusive** (Volatility, Step, Drift Switch): every rule loses −0.5 to −1.2R, at or below its
  walk. Drift Switch 20 and 30 are worst, about −2R own exit, because their drift regimes run
  against a fade.
- **Jumpy** (Jump 50, Boom 1000, Crash 1000): stop exits +0.02 to +0.20R against walks around −0.3.
  Boom and Crash fades of spikes make +0.2 to +0.6 on the own exit. That is the published spike
  generator, not a market edge.
- **Range Break 100** is the expected positive. With the structural stop it makes **+1.0 to +3.0R** a
  trade (bb +2.89 [+2.73, +3.04], z50 +3.03, ibs1 +1.22) against walks around −0.15, with P(≥4R)
  0.37 to 0.42 against 0.20. It is strongest at 15m and 1h and fades by 1d. This is the generator's
  sub-diffusive range ([deriving.md](deriving.md)), seen through a tight stop. It is reported as a
  property of the instrument and kept out of every pool.

## Selection, BH and the two primaries

**Discovery.**
- 2,644 cells were defined. 1,525 had n ≥ 30 (FX, metals, crypto CFDs, Binance).
- BH at q = 0.10 rejects 10. All 10 also beat both walks and the twin in both halves.
- 9 of the 10 are FX 1h gap-fade variants. The tenth is `rsi2_ma|VR>=0.9`, FX 1d, at +0.452R.
- The frozen rule picks the top one: `gap|H>=0.45`, FX, 1h, own exit, at +0.470R (iid −0.07,
  GARCH −0.15, twin −0.07).

**Confirmation.** 2,837 cells with n ≥ 30, BH rejects 36. They are reported, not judged. Most are
own-exit band fades on 30 to 400 trades, whose R carries a few 10 to 20R exits from tiny stops.

| primary | n | R [90%] | halves | iid | GARCH | twin | P4R (iid) | verdict |
|---|---|---|---|---|---|---|---|---|
| P1 rsi2_ma, indices 1d, own | 216 | +0.272 [−0.445, +0.989] | −0.68 / +1.21 | +0.26 | +0.63 | −0.89 | 0.227 (0.183) | **fails** |
| P1, with the structural stop | 216 | −0.084 [−0.365, +0.197] | | −0.16 | +0.10 | | | |
| P2 gap\|H≥0.45, FX 1h, own | 585 | +0.461 [+0.384, +0.531] | +0.47 / +0.45 | −0.14 | −0.10 | −0.14 | 0.285 (0.187) | **passes as frozen** |
| (2nd discovery cell) rsi2_ma\|VR≥0.9, FX 1d | 257 | −0.861 [−1.74, +0.02] | | | | | | does not replicate |

## Why the gap fade's pass is not an edge

The selected cell raised a concern before its confirmation was read: bars are bid prices, and the
spread at the weekend reopen is wide. A check was registered for it.

**1. The registered checks pass.** On FX 1h confirmation trades:
- **Frozen:** +0.461.
- **(a)** Charging the reopen bar's recorded spread: +0.266 [+0.189, +0.334].
- **(b)** Entering at the reopen bar's close: +0.177 [+0.083, +0.263].

**2. The trade is lopsided in a way no price process explains.**
- Gap-down trades (longs) outnumber gap-ups about 5 to 1, and only the longs pay: +0.58 against −0.06.
- On mid prices, gaps up and down would be equally common.
- A bid that opens below Friday's close because the spread is wide is exactly a "gap down" that
  "fills" as the spread narrows.

**3. The broker's ticks settle it.**
- 1,166 reopens across the 12 pairs, fetched read-only through the lab's bridge (ticks exist from
  November 2024). The median first-tick spread is:
  - **13 pips, 0.89 ATR(1h)**;
  - 3.4 times the bar's recorded spread field (which is the bar's minimum);
  - 9.7 times the weekday floor.
- It is still 0.44 ATR an hour in. The gap threshold is 0.5 ATR, so the trigger is largely the
  spread itself.
- Replaying the 396 confirmation trades that have ticks, buying at the ask and selling at the bid,
  with levels and exits as frozen:

| version (same 396 trades) | R [90%] |
|---|---|
| frozen | +0.397 [+0.306, +0.485] |
| (a) bar spread | +0.197 [+0.111, +0.281] |
| (b) entry at the bar's close | +0.184 [+0.058, +0.298] |
| **T0: first executable price** | **−0.410 [−0.510, −0.312]** |
| T5 (identical: first ticks come 5 to 10 minutes after the bar's open) | −0.410 |
| T15 (30 trades skipped as already filled or stopped) | −0.255 [−0.356, −0.163] |
| T60 (97 skipped) | −0.157 [−0.254, −0.065] |

- **Every pair is negative at T0**, from −0.02 for EURUSD to −0.89 for NZDUSD.
- **The registered verdict:** no executable entry keeps R > 0, so the frozen pass is the bid-bar fill
  at the reopen.
- **Check (b) was not enough.** At the reopen bar's close the median spread is still 0.1 ATR, and the
  trades it keeps were selected by a spread-made gap.

**Follow-up.**
- [`paper_gapfade.py`](../ideas/paper_gapfade.py) logs every reopen live from the bridge: Friday's
  close, the first bid and ask, the gap, Hurst and the frozen signal, plus the spreads an hour
  later. It has a `score` mode.
- It is running on the lab from the 2026-10-04 reopen. Its smoke run on the 2026-09-27 reopen fired
  on exactly the 5 pairs the backtest traded, with the same Hurst values.
- On that one reopen, all 12 pairs opened below Friday's close on the bid, 10 of them by more than
  0.5 ATR.

## What this means

- **Classic mean reversion has no edge on these markets at these costs.** Not overall, not per asset
  class or timeframe, not in its tails, and not inside a variance-ratio or Hurst regime. The regime
  splits are as flat as in [chan.md](chan.md).
- **The rules are not broken.** They earn on OU and AR(−). Real series give a short-horizon reversal at
  15m and 1h (bid-ask bounce) that is smaller than the spread.
- **The literature's classic, Connors on daily indices, does not confirm.** Its sample is two years of
  CFD data, and it does not beat the GARCH walk.
- **Pairs:** the rolling cointegration filter works on a truly cointegrated pair. Real FX, metals,
  index, energy and crypto pairs are not cointegrated at a tradeable speed, as in chan.md.
- **For method:** a frozen pipeline with walks, a twin and BH still selected an artefact. Only the
  executable price caught it. Any rule that trades at a session open on bid bars needs an ask-side
  replay before it counts. "Artefact" is the right word here: it was a fill error, not a pattern
  that matched the walks.

## Caveats

- **Own-exit R is noisy.** Its unit is the structural stop, often 0.2 to 0.5 ATR, so a reversion to a
  20 or 50-bar mean can be 10 to 20R. Band-rule cells on a few hundred trades swing by ±2R, which is
  why the BH rejections in confirmation are not believed.
- **15m data exist for 2024 on only**, and MT5 indices and energy for 2024 on only.
- **The tick replay covers November 2024 on** (396 of 585 trades). After its 3-hour window, a short's
  ask is approximated as bid plus the weekday spread.
- **Everything was computed in one pass.** The discovery tables were built from rows dated before 2024
  only, and the confirmation was read after `mr_selected.json` was committed.
- **Per-class reporting was added before any result was read** (an `amended_before_run` note in the
  rule file).

## Re-running

On the lab, with `OUT`, `MT5BT_DB` and `PYTHONPATH` set:
- `MODE=discover`, then `confirm`, `gapcheck` and `plot`: `python research/ideas/mean_reversion.py`
- `MODE=fetch|measure|replay python research/ideas/gapfade_replay.py` (fetch needs the bridge env)
- `MODE=loop|smoke|score python research/ideas/paper_gapfade.py`

Plots, in `.data/mr/`:
- `mr_pnr_{fx,metal,index,energy,crypto,binance,fresh,all,DERIV_*,RANGE_BREAK_100}.png`
- `mr_heatmap_{own,st,deriv}.png`
- `mr_controls.png`
- `mr_pairs.png`
- `mr_gallery_P{1,2}_{winners,losers}.png`
