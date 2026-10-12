# Second windows: reachable now, and below the cost floor

Asked on 2026-10-12: the ladder supports minutes, hours, days and weeks, and
with quote data it should support **seconds** - an EMA over thirty seconds
beside one over three minutes, and the pairs that follow.

## What was already there, and what was not

`inputs.LADDER` has carried `10s` and `30s` rungs for a long time and **no
feed could ever reach them.** The finest series this desk stored was 1m, and
`resolvable` correctly refused a 10s window on it: two bars is the floor and
ten seconds is a sixth of a 1m bar. The rungs were aspiration.

Tick stores change that, and `1s` and `5s` are added, because ticks arrive
every tenth of a second on the traded pairs and every second or two on the
synthetics. The bound still works at the fine end, which is the point of
having bounds rather than a ladder per feed:

| feed | finest rung reached | refused |
| --- | --- | --- |
| 1d bars | `1d` | everything in seconds, and `30m` |
| 5s bars | `10s` | `1s`, `5s` |
| 1s bars | **`5s`** | `1s` |
| 0.2s bars | **`1s`** | - |

A 1s feed is refused `1s` for the same reason a 1d feed is refused `30m`: a
window the length of one bar reports that bar's own extremes under a name
claiming a horizon.

## The reading that decides the scale

A rung being reachable is not a rung being useful, and at this scale the
question is not information but **cost**. A round trip pays the spread, and a
five-second move may be smaller than the spread.

Median absolute move over each rung, divided by the instrument's own median
spread, from 1s bars built out of ticks:

| rung | XAUUSD | BTCUSD | `Volatility_75_Index` |
| --- | --- | --- | --- |
| 5s | **2.00** | **1.92** | **0.82** |
| 10s | 2.87 | 3.44 | 1.17 |
| 30s | 5.27 | 6.99 | 2.05 |
| 1m | 8.00 | 10.39 | - |
| 3m | 16.13 | 16.56 | - |
| 5m | 22.60 | 22.69 | - |

Spreads: XAUUSD 0.34 bp, BTCUSD 0.31 bp, `Volatility_75_Index` 3.51 bp.

**At five seconds the move is twice the spread on the traded pairs and
smaller than the spread on a volatility index.** A round trip at 1.5 spreads
against a 2.0-spread move needs 75% of the whole move captured to break even,
which no hit rate delivers. At thirty seconds the cost is 28% of the move; at
one minute 15 to 19%; at three minutes 9%.

So the cost floor sits between **one and three minutes**, and the second rungs
are structurally below it. That is not a statement about signal - it holds
whatever the signal is.

`Volatility_75_Index` is the sharp case: its spread is ten times XAUUSD's in
basis points, so its five-second move is **smaller than its own spread**. The
same instrument at thirty seconds reaches only 2.05. An instrument's tradeable
horizon is set by its spread, and this is the table that says where.

## The pair arm

The question as asked - a fast EMA against a slow one. For each ordered pair
of rungs from `5s` to `15m`, the fast EMA less the slow against the forward
move over the slow rung's own horizon, strided by that horizon so the windows
do not overlap:

**0 of 30 traded pairs beat their rotated control by 0.1.** Raw correlations
run from -0.047 to +0.097 and the controls from -0.032 to +0.089 - the same
range. The largest raw reading, XAUUSD's `30s` against `1m` at +0.097, has a
control of -0.030, which is the only pair where the gap even reaches 0.13, on
327 observations.

And the two failure modes are separate here, which is worth noting: **all 30
pairs had a move worth more than twice the round-trip cost**, because their
slow horizons are 10s and longer. So the moves were large enough and the
signal was absent, rather than the signal being present and eaten by cost.

## What the second rungs are for

They are reachable, measurable, and not a trade horizon. The distinction
matters because it is easy to read the above as "seconds are useless" and
that is wrong:

* **As a measurement scale they are the best thing available.**
  `statespace-touches.md` got its best-powered band test at ten-second
  intervals - about a hundred ticks inside each one to describe the path -
  and could not have done it at one minute, where the same five hours of
  XAUUSD leaves 165 observations.
* **As an input to something slower they are untested and plausible.** A
  realised volatility over 30s feeding a 1m or 5m member is a different claim
  from trading the 30s rung, and the fractal arm already showed volatility
  estimated over short windows is mostly estimation noise - which the second
  rungs would let us measure directly rather than infer.
* **As a holding period they are below the cost floor**, by the table above,
  and no signal changes that.

## Limits

EURUSD's tick store is corrupt, so the pair the desk trades most is absent.
The spans are about five hours for XAUUSD and ten for BTCUSD, which is why
the pair arm's longer horizons have 64 to 108 observations and nothing is
claimed from them beyond the control comparison.

The harness is `research/ideas/seconds_windows.py`.
