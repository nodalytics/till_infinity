# Structures scores the same on random walks: its Brier skill is the geometry of the touch

Measured 2026-09-29 on the lab with [`skill.py`](../harness/skill.py). The production
`structures.Engine` and the production break model (`learning.breaking.Breaks`, read at publish
and observed at resolution exactly as `structures/service.py` does) were replayed from 2025-01-01
over the lab's broker bars at 15m and 1h, interleaved in time:
- **real markets:** EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY, XAUUSD, BTCUSD and ETHUSD,
  30,723 resolved touches;
- **random walks:** Deriv Volatility 10/25/50/75/100 and Step, which are exact random walks
  ([`generators.md`](generators.md)), 17,119 resolved touches, in a separate engine.

The models learn online and predict before they learn, so every forecast is out of sample.

One departure from production: each series comes from one broker, where production takes a median
across three or more venues for FX. The feeds are marked `single_source` so the engine forms
levels at all.

## The question

Does `structures` have skill, and does a Brier score mean anything for it? A probability can only
show skill against a reference. The references here are:
- **the base rate:** the engine's own per-(feed, interval) `base_rate_up`;
- **the side rule, "the level holds":** P(up | arrived from above), accumulated causally;
- **the random-walk control:** the same code on a market with nothing in it to know. Whatever the
  engine achieves there is the geometry of how a touch is defined and resolved.

## The answer: everything it achieves, it achieves on random walks

All touches. The two halves of the period agree on every row:

| | real markets | random walks |
| --- | --- | --- |
| the level holds (P(up) from above / from below) | **88.6%** (0.889 / 0.116) | **87.3%** (0.870 / 0.124) |
| **P(up) model** Brier / log loss | 0.1055 / 0.3458 | 0.1113 / 0.3574 |
| its skill vs the base rate, Brier (log loss) | **+0.581** (+0.504) | **+0.557** (+0.487) |
| its skill vs the side rule | -0.173 (-0.214) | -0.145 (-0.189) |
| its AUC overall / within each arrival side | 0.939 / 0.776, 0.773 | 0.932 / 0.776, 0.781 |
| its reliability / resolution | 0.0082 / 0.1516 | 0.0064 / 0.1440 |
| **side rule** Brier, skill vs base rate | 0.0899, +0.643 | 0.0972, +0.613 |
| **the level's own record** (`record_hold`), AUC within side | 0.465 / 0.459 | 0.476 / 0.481 |
| **P(break) raw**: AUC, skill vs the running break rate | 0.811, +0.112 | 0.810, +0.127 |
| P(break) Platt-calibrated: skill vs running rate | +0.114 | +0.129 |
| **`expected_push`**: rank correlation with realised, signed / size | +0.546 / +0.111 | +0.545 / +0.088 |
| "level holds" trade, mean push | +1.42v | +1.29v |

- **The hold rate is geometry.** Price that arrives at a level "holds" 88.6% of the time on real
  markets and 87.3% on random walks. The 73% of [`features.md`](features.md), and this replay's
  88.6%, is what the touch definition does to any path: where a touch opens relative to the level,
  and how far each resolution boundary sits from it.
- **The P(up) model is calibrated, and its skill is the geometry's.** Its reliability term is
  small (0.008), so its numbers mean what they say. Its Brier skill against the base rate, +0.58,
  is matched on random walks (+0.56). Against the side rule it is *worse* on both (-0.17 and
  -0.15). What it ranks within a side (AUC 0.776) it ranks identically on random walks (0.776 and
  0.781).
- **The break model's AUC of 0.81 is also geometry:** 0.811 against 0.810. Its skill over the
  running rate is slightly *larger* on the random walks. Platt calibration changes the skill score
  by 0.002. The raw model is already calibrated in this replay, unlike the 0.3624-against-0.2493
  failure recorded in `calibration.py`. Why the two differ was not separated. One candidate is
  the all-zeros-input bug that `engine.py` notes was fixed; another is this replay's higher break
  rate (11% against 6.8%).
- **A level's own hold record anti-ranks slightly (AUC 0.46-0.48 within side) on both.** That is
  regression: a level that has held unusually often is, on the next touch, just a level.
- **`expected_push` is the same on both** (+0.546 against +0.545). It is the one positive in
  [`magnitude.md`](magnitude.md), and it is geometry too.
- **Push is a label, not a P&L.** The "level holds" trade shows +1.29v on a random walk, where
  [`barrier-geometry-is-irrelevant.md`](barrier-geometry-is-irrelevant.md) proves every tradeable
  rule earns zero before costs. Whatever the exact mechanism, the random walk proves that a positive mean
  `push_vol` is not money, and no replay should score a strategy by it.

The real-minus-random differences are small and mostly the size of what separates two samples: a
1.3-point higher hold rate, +0.024 of skill against the base rate, and +0.023 of `expected_push`
rank correlation on size. None of them is a direction.

## What this settles

- **Does structures show skill?** Against the base rate, a large skill (+0.58 Brier skill score).
  Against the right reference, the same engine on a random walk, **essentially none**: 88.6%
  against 87.3%, 0.811 against 0.810, and +0.546 against +0.545.
- **Does Brier mean anything to it?** Brier says the probabilities are honest: reliability is 0.008
  for P(up) and 0.0015 for P(break), and calibration is not the problem. But Brier cannot say
  whether they know anything about the *market*. Scored against a base rate, it rewards the
  touch definition's own geometry, which a random walk reproduces. **The only meaningful Brier
  for this engine is the skill score against its own random-walk replay.** Every future change to
  `structures` should be measured that way before it is believed.
- **Is it thinking in the right direction?** As a description of where price reacts, yes, and it
  is calibrated. As a source of edge, no. What it describes is what any random path does around
  any line drawn on it. The direction question has nothing left in it here. The engine's
  defensible jobs are the ones that do not need an edge: risk geometry (where a stop sits in
  volatility units, how often a stop at that distance is touched) and the timing of volatility.
