# What the stop and target are worth, over 49,338 touches

Sixteen live trades across four strategies is about four labels each. That is
not enough to say anything about any of them, and nowhere near enough to fit a
rule that picks a strategy for a regime. So the labels were manufactured
instead: a level strategy is a deterministic function of the call plus a stop
and a target, every resolved touch already records what happened afterwards,
and replaying the rules over them takes the sample from seventeen to tens of
thousands without trading anything.

`research/harness/replay.py`, run against the production journal on
2026-08-27.

## The result

Mean R by regime, with the target held at 1.5x the stop:

| stop | quiet | normal | busy | wild | all |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.5 | +0.905 | +0.928 | +0.871 | +0.870 | **+0.898** |
| 1.0 | +0.824 | +0.824 | +0.732 | +0.748 | **+0.792** |
| 1.5 | +0.523 | +0.418 | +0.347 | +0.344 | +0.427 |
| 2.0 | +0.350 | +0.208 | +0.142 | +0.175 | +0.239 |
| 3.0 | +0.175 | -0.015 | -0.035 | -0.020 | +0.047 |
| 4.0 | +0.063 | -0.039 | -0.048 | -0.036 | -0.004 |
| 5.0 | -0.003 | -0.027 | -0.034 | -0.027 | -0.020 |

(17k quiet, 12k normal, 8k busy, 10k wild.)

**Tighter stops are monotonically better, in every regime.** Going from 1.0 to
3.0 - which production ran for about two hours on 2026-08-27 - costs roughly
three quarters of a unit of mean R.

## Why, and why it does not contradict the excursion measurement

Both measurements are right and the reconciliation is the useful part.

`excursion_vol` has a **median of 0.00**: most touches never go through the
level at all, and 34,123 of the 49,338 resolve as clean rejects. A stop placed
*at the level* is therefore rarely reached, while a modest target often is.
Widening the stop widens the target with it, and the push distribution does not
scale to follow - a 4.5v target is rarely reached where a 0.75v one usually is.

The earlier reading of the same field - p75 1.64v and p90 3.68v on 1m - was not
wrong, it was conditional. Those are the percentiles *of the touches that went
anywhere*, and they were used to argue for a stop that survives them. What that
argument missed is that surviving them costs more in unreached targets than it
saves in avoided stops.

**The replay assumes entry at the level. Production does not.** Entry is a
market order and lands wherever price is when the call arrives, routinely more
than a volatility unit past the level, while `excursion_vol` is measured from
the level. That gap is the actual problem: the stop is anchored to the level,
the entry is not, and the distance between them is noise the trade has to
survive before its thesis is even tested.

## What it changed

* **The stop scaling was reverted.** `TRADING_STOP_HOLD_SCALING` back to 0.
  It was switched on that morning on the strength of the excursion percentiles
  and an argument about square-root-of-time scaling, and this measurement says
  it costs about 0.75R of mean.
* **The pullback matters more than it was given credit for.** Waiting for price
  to come back to the level is what makes the replay's geometry the real one,
  rather than an assumption the live path violates.
* **The chase gate is doing the right job.** It refuses precisely the entries
  the replay cannot model - the ones already past the level.

## On regime

Regime separates, and it is a real effect: quiet outperforms wild at every stop
width. It is also **small next to the stop width**, which dominates it by an
order of magnitude. So a regime-aware strategy chooser is a second-order
refinement on top of entry and stop placement, not the lever - and
[edge.md](../docs/edge.md) is the standing caution about reaching for a
dynamic rule before the constant has been got right.

## What this cannot say

Spread and slippage are not recorded on a resolution, so this scores the thesis
and not the execution - and the live trades suggest execution is where a good
deal of the loss lives. `approach-scalp` needs the next level in the book and
`fade-to-value` needs the valuation, neither of which is on the resolution, so
only the level-holding family replays.

And one compromise is built into the scoring: when both the stop and the target
were reached, the record cannot say which came first, so it counts as a stop.
That biases every number here downward, which is the direction a bias should
point when the alternative is flattering a rule you are about to trade.
