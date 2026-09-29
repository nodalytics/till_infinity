# Which envelope band does price touch first, and does it touch at all? ML over the bands' geometry

Harness: [`research/harness/bandrace.py`](../harness/bandrace.py). Lab runs 2026-09-29.

## The question

The envelope (`structures/vol/envelope.py`) quotes P10 / P50 / P90 of where price *ends* N bars on,
corrected by AgACI ([`conformal.md`](conformal.md)). A trader cares about the path. Which band is
touched first? Is either touched at all? Are both? Can a model forecast that beyond what the bands'
own position already says?

## Method

- **The bands.** AgACI's online P10 / P50 / P90 of the N-bar move, in units of the EWMA of true
  range (the production unit). They are quoted at every bar from that bar's past only, exactly as
  production would quote them, and placed as prices around the close.
- **Targets**, read off the next N bars' highs and lows:
  - **race:** P90 touched before P10 (same-bar ties and "neither" excluded);
  - **touch90** and **touch10:** that band touched at any time within N;
  - **both:** both bands touched within N;
  - **after P50:** the race, split by which side of P50 the first bar closed.
- **Model and baseline.** Gradient boosting, trained on each series' first 60% by time and scored
  on the last 40%. Features: lvol, the unit's percentile, vol of vol, r1 / r5 / r20, range, hour,
  weekend clock, and the band distances d90 and d10 with their asymmetry. **The baseline is geometry
  alone:** the same boosting on d90, d10 and the asymmetry only. So "skill" means the market's state
  adds something beyond where the bands sit. Brier skill = 1 − B_model / B_geometry, with 95%
  intervals from resampling whole days.
- **Scope.** Horizons N = 5, 20, 50 at 15m, and N = 20 at 1h. Families: FX, metals, crypto, and
  Deriv's Volatility, Boom/Crash and Range Break as markets.
- **Controls, walks we generate.** iid Student-t(3), and GARCH(1,1) with t(4) shocks.
- **FX rollover.** The primary FX view has the wick of every bar reaching the 17:00 New York
  rollover cut to the body, as production now does ([`rollover.md`](rollover.md)).

**Two design errors, caught by the walks and fixed before these numbers:**

- **Race trades were chosen with future knowledge.** The first version chose them only among bars
  where a band was later touched. That conditions on the future, and read **+0.23R (t +6.8) on
  memoryless walks**. Trades are now chosen on every bar.
- **Gambler's ruin was the wrong baseline.** The first baseline was ruin, p_up = d10 / (d90 + d10).
  That is not the finite-window answer: given a touch within N, the nearer band is first more
  often. It showed "skill" on the walks too, and is now reported for reference only.

**Pre-registered bars:**

- **race:** Brier skill over geometry ≥ 0.01, with its interval above 0, in both halves of the
  test, and not on the walks.
- **touch and both**, as first written: AUC over the training rate ≥ 0.60, calibrated within ±20%
  per decile, and not on the iid walks. Band geometry alone reaches AUC 0.62-0.72 on the iid walks,
  so that bar could not separate skill from geometry. Touch is judged here on skill over geometry,
  the same measure as race.

## Results

**Race, Brier skill over geometry** [95%], with the halves:

| | 15m N = 5 | 15m N = 20 | 15m N = 50 | 1h N = 20 |
|---|---|---|---|---|
| FX, rollover wick trimmed | **+0.044** [+0.040, +0.049], +0.031 / +0.057 | **+0.021** [+0.015, +0.027], +0.018 / +0.024 | +0.007 [-0.003, +0.017] | +0.005 [+0.001, +0.008] |
| FX, raw bars | +0.051 | +0.032 | +0.010 | +0.006 |
| metals | -0.004 | +0.002 | +0.005 | +0.026 [+0.014, +0.039] |
| crypto | -0.007 | -0.033 | -0.053 | +0.014 [-0.002, +0.028] |
| Deriv Volatility | -0.001 | -0.010 | -0.018 | -0.001 |
| Deriv Boom/Crash | +0.003 | +0.005 | **+0.020** [+0.008, +0.032], +0.019 / +0.022 | +0.000 |
| Deriv Range Break | -0.005 | -0.003 | -0.004 | -0.010 |
| walks (iid t3) | +0.000 | +0.004 [-0.002, +0.009] | -0.002 | +0.002 |
| walks (GARCH) | -0.002 | -0.002 | -0.008 | +0.003 |

**Race as a trade.** On every bar, trade toward the band the model favours beyond geometry, with
the other band as the stop, exiting at N. Net R after costs, with the halves:

| | 15m N = 5 | 15m N = 20 | 15m N = 50 | 1h N = 20 |
|---|---|---|---|---|
| FX, trimmed | +0.063 (t +5.4), **-0.020** / +0.152 | +0.021 (t +1.6), +0.004 / +0.038 | -0.036 (t -1.9) | -0.056 (t -4.6) |
| FX, raw | +0.068 (t +5.8) | +0.070 (t +4.9) | -0.049 | -0.043 |
| metals / crypto | -0.037 / -0.166 | -0.018 / -0.109 | +0.010 / -0.151 | -0.011 / +0.012 |
| Deriv Vol / Boom-Crash / Range | -0.050 / -0.037 / -0.022 | -0.013 / -0.033 / -0.005 | -0.050 / +0.036 / -0.051 | -0.016 / -0.004 / +0.063 |
| walks iid / GARCH | -0.027 / -0.027 | -0.020 / -0.003 | -0.040 / -0.014 | -0.030 / +0.012 |

**Touch, Brier skill over geometry** (touch90 / touch10), with the worst decile calibration error
in brackets:

| | 15m N = 5 | 15m N = 20 | 15m N = 50 | 1h N = 20 |
|---|---|---|---|---|
| FX, trimmed | **+0.087 / +0.059** (16% / 13%) | **+0.075 / +0.056** (20% / 8%) | +0.066 / +0.062 (27% / 93%) | +0.026 / +0.021 (16% / 24%) |
| metals | +0.058 / +0.052 (34% / 28%) | +0.035 / +0.036 (83% / 63%) | +0.038 / +0.029 | +0.037 / +0.028 (29% / 25%) |
| crypto | +0.039 / +0.043 (20% / 22%) | +0.041 / +0.055 (139% / 42%) | +0.039 / +0.025 | +0.043 / +0.039 (20% / 39%) |
| Deriv Volatility | +0.007 / +0.001 | +0.004 / -0.001 | +0.004 / -0.014 | +0.001 / +0.005 |
| Deriv Boom/Crash | +0.010 / +0.012 | +0.015 / +0.012 | +0.017 / +0.010 | +0.008 / +0.005 |
| Deriv Range Break | +0.011 / +0.006 | +0.021 / +0.024 | +0.027 / +0.026 | +0.019 / +0.021 |
| walks (iid t3) | +0.011 / +0.009 | +0.012 / +0.010 | +0.010 / +0.007 | +0.012 / +0.011 |
| walks (GARCH) | +0.003 / +0.004 | +0.006 / +0.007 | +0.009 / +0.016 | +0.005 / +0.008 |

AUC for touch in FX at 15m N = 20: model 0.736 / 0.718 against geometry 0.645 / 0.654.

**Both bands touched** is rare: 1.2-1.6% of FX windows, 0.0-0.2% on Deriv. Its skill over geometry
in FX is +0.020 to +0.033, but its calibration is poor (20-100% error), as expected for so rare an
event.

**After P50 is mechanical.** Having closed the first bar above P50, P90 is first 62-65% of the
time, and 31-36% after closing below. The iid walks read the same, 0.648 / 0.342, because the split
conditions on the first bar's move. It says nothing that isn't already known once that bar closes.

## What this means

- **The rollover spike was a third of FX's apparent direction skill, and most of its trading
  edge.** On raw bars the race trade at 15m N = 20 netted +0.070R (t +4.9). With the rollover wick
  cut as production now cuts it, that falls to +0.021R (t +1.6). Bid-based lows dip when the spread
  widens, and a model given the hour learns to call "P10 first" there. A short's take-profit fills
  at the ask, which does not dip, so that "edge" was never there to take.
- **FX has a short-horizon direction lean the bands don't carry, and it doesn't pay.** It survives
  the trim: race skill +0.044 at N = 5 and +0.021 at N = 20, both halves, walks at zero. It passes
  the race bar at 15m N = 5 and N = 20, and fails it at N = 50 and 1h. As a trade it does not
  survive: +0.063R at N = 5 with a losing first half, and +0.021R at N = 20 with t 1.6. This is the
  FX mean reversion seen before ([`indicators.md`](indicators.md): waiting for a reclaim costs
  0.07-0.13 vol), and it sits inside the spread.
- **Nothing else calls direction.** Metals, crypto and Deriv read zero or negative race skill,
  except Boom/Crash at N = 50 (+0.020, both halves). There the trade does not pay (+0.036R, t 1.4).
  Its one-sided spikes shape which band goes first, but not enough to trade.
- **Whether a band is touched at all is forecastable, and this is the useful half.** FX touch skill
  over geometry is +0.056 to +0.087 at 15m, calibrated within 20% at N = 5 and N = 20. That is five
  to seven times what the walks show. Metals and crypto show +0.03 to +0.06 but calibrate badly at
  N = 20 (up to 139% error). Deriv is at the walks' level.
- **The walks' +0.01 touch "skill" is mechanical, and it is why the touch bar is only met in
  substance.** On an iid walk the EWMA unit fluctuates around the true scale, and lvol says which
  way. That is a better volatility estimate, not market structure. As written, "not on the iid
  walks" is not met at +0.01. FX's +0.06 to +0.09 is well beyond it.

## For production

- **Candidate: touch probabilities on the cards, FX first.** For example: "next 5 bars: P90 touched
  38% · P10 touched 22%". The model is small gradient boosting on features the engine already has,
  frozen and retrained by the pipeline (`models/retrain.py`), exactly as the shock forecaster is.
  Calibrated within 20% at 15m N = 5 and N = 20 on FX. Metals and crypto only after their
  calibration is fixed, and not on Deriv, where it adds nothing beyond the walks. It says nothing
  about direction.
- **Uses beyond the card:**
  - sizing down when both bands are likely to be touched (range expansion);
  - placing stops beyond a band that is unlikely to be touched;
  - widening the envelope's quoted band when a touch is likely.
- **No race trade and no "which band first" call.** The FX lean passes its skill bar but not its
  trade, and everything else is at zero.
- **The trim should be the default for any FX path study.** Every earlier FX result on bid bars
  that involves a touch near 21:00 UTC is suspect in the same way.
