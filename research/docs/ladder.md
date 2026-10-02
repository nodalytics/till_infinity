# The direction ladder: no rung adds a side

Measured 2026-10-02 with [`ladder.py`](../harness/ladder.py), the experiment that ideas.md Part L (L13)
registered before the run.

## The question

`structures` asks P(up | level), and that fails ([`skill.md`](skill.md), [`triage.md`](triage.md)).
The proposal was that the level is the wrong conditioning, not that direction is unavailable. The
side might enter through:
- the way price arrives;
- the state around the level;
- the expansion state;
- the level's own sequence of tests.

So the side is predicted from progressively richer information, and each rung's gain is measured:

| Rung | Adds | Features |
|---|---|---|
| D0 | the level | side; the engine's P(up), base rate, edge, expected push and risk; the level's record, strength, experience, own touches, neighbours |
| D1 | approach morphology | approach speed, run, depth, slowing, the two slopes; from the last 16 bars, velocity (4 and 16 bars), acceleration, range contraction, persistence, efficiency, wick asymmetry, distance to the level |
| D2 | state | regime; the call's context (changing timeframes, learned readings, envelope, clock, touch); the higher timeframe (returns over 64 and 256 bars, position in the 256-bar range) |
| D3 | expansion | the shock and expansion readings |
| D4 | the level's history | its last four resolved touches on this side: push, adverse, outcome, approach, duration; the trend across them; time since the last |

## How it was run

- **Touches:** the production engine replayed from 2025-01-01 at 15m and 1h, one row per touch at
  first contact.
- **Families:**
  - real markets: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY, XAUUSD, BTCUSD, ETHUSD;
  - Deriv: Volatility 75, Jump 50, Drift Switch 10, Crash 500, Boom 500, Step (a market);
  - nine GARCH(1,1) t(3) walks built from sub-steps (the control).
- **Label:** a symmetric race from the touch bar's close, ±1.5 ATR(14) within 32 bars; whether up
  wins. On a martingale this is 0.5 whatever the state, so only side information can lift it.
- **Model:** HistGB per rung, trained on the first 60% of touches by time and scored on the last
  40%, with day-bootstrap intervals for each rung's gain.

## Results

AUC on the race, held out:

| Family | Test touches | D0 | D1 | D2 | D3 | D4 | D4 − D0 (95% CI) |
|---|---|---|---|---|---|---|---|
| Real | 13,081 | 0.502 | 0.498 | 0.506 | 0.507 | 0.505 | +0.003 (−0.007, +0.014) |
| Deriv | 11,734 | 0.510 | 0.502 | 0.499 | 0.495 | 0.488 | −0.022 (−0.038, −0.007) |
| Walks | 15,628 | 0.500 | 0.504 | 0.501 | 0.504 | 0.503 | +0.003 (−0.011, +0.018) |

- **No rung passes.** The largest gain on real markets is state (D2 − D1: +0.008, halves +0.010
  and +0.005, interval −0.002 to +0.018). That is under the 0.01 bar in one half, and its interval
  includes zero.
- **Information over the base rate is negative at every rung, in every family** (−0.002 to −0.008
  bits per touch). The models fit noise and pay for it out of sample.
- **The confident fifth earns nothing:** −0.033 to +0.005R on the race on real markets, as on
  walks.
- **On Deriv, more information is worse** (D4 0.488). Richer models overfit a market with no side
  to find.

**The engine's own outcome label is an identity, not a forecast.** Scored on `push` (the
resolution's sign), every rung reads 0.93-0.96 AUC, on the walks as well (0.952). The sign of
the push follows from the side and the outcome by construction ([`structures-reactions.md`](structures-reactions.md),
`Forward`), so any feature that knows the side "predicts" it. Only the symmetric race asks a real
question.

## What this closes

- **Approach morphology, the higher-timeframe state, the expansion and shock readings and the
  level's sequence of tests carry no side at a level touch.** This holds alone (each rung) and in
  combination (D4), on real markets and on Deriv, at 15m and 1h.
- **Trajectory-aware similarity (L12) is closed with it.** A flexible model on these features
  finds nothing, so a distance built from them cannot.
- **The branch "high hazard + strong directional transition → one-sided trade" has no input.** No
  rung produces a strong transition probability, so that branch has nothing to act on, and the
  other branch (the bracket) already fails (L3).

The levels stay what [`findings.md`](findings.md) says they are: a structural map that forecasts
risk well and direction not at all.
