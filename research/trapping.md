# Traps: the majority outcome, and how much of it is predictable

`SideStats.traps` has counted false breakouts since it was written, and
`sweeps.sweep_rate` publishes a per-level trap rate on every call. Neither had
ever been added up. Measured 2026-09-07 across the live level book and the
journal.

## Traps are what usually happens when a level is attacked

Decayed effective counts across the whole level book:

| | count | share of resolutions |
| --- | --- | --- |
| rejects | 47,827 | 84.3% |
| **traps** | **5,707** | **10.1%** |
| breaks | 3,204 | 5.6% |
| backchecks | 5,851 | 10.3% |
| chops | 1,418 | 2.5% |

**Traps are 64% of all attempts** - breaks plus traps - and traps outnumber
breaks outright. That is the first thing worth saying, because
`breaking.py` models P(break) and nothing models this.

And it is steeply conditional on timeframe. From the journal's 48,470 resolved
attempts, taking the later half by time:

| interval | attempts | trap share |
| --- | --- | --- |
| 1m | 13,616 | 36.4% |
| 3m | 5,049 | 49.2% |
| 5m | 4,432 | 49.9% |
| 15m | 748 | 83.0% |
| 30m | 261 | **94.6%** |

On 30m, a level that gets attacked comes back nineteen times in twenty. A
strategy that trades breaks on the higher timeframes is taking the wrong side
of that by a wide margin, and nothing in the book currently knows it.

## The better-posed question

`breaking.py` asks P(break) against a 6.8% base rate, and
[calibration.md](../till_infinity/structures/learning/calibration.py) measured
what that costs: log loss 0.3624 against 0.2493 for a constant. A rare class is
a hard thing to be calibrated about.

**Conditional on an attempt, is this a break or a trap** is the same evidence
asked a better question: 48,470 examples, 57.6% traps, near-balanced classes,
and the counterfactual observed either way. It is also the question a trader
actually has - price is going through, do I follow it.

## What predicts it, and the number that did not

Scored the way [force.md](force.md) scores the break model: AUC per feature,
out of sample by time, on the later half.

**The pooled table said `interval_log`, AUC 0.6187 - and that is not skill.**
`interval_log` is the timeframe, and the table above is exactly what it was
finding. Scored **within each interval and pooled by weight**, it collapses to
**0.5026**, which is nothing.

That is the third time this repository has caught the same shape: `edge` turned
out to be `side` wearing a distance ([prior.md](prior.md)), and 84-88% accuracy
turned out to be reproducing a definition ([similarity.md](similarity.md)). A
feature that encodes the population is not a feature.

Within interval, what is left:

| feature | AUC | |
| --- | --- | --- |
| `experience` | **0.5671** | the level's own record |
| `strength` | 0.5644 | **r = +0.963 with `experience`** - the same signal |
| `depth_vol` | 0.5255 | r = +0.096, so it adds rather than restates |
| `regime` | 0.4672 | weakly the other way |
| everything else | 0.49-0.51 | nothing |

So: **one signal at about 0.567, plus `depth_vol` at 0.526 that is genuinely
uncorrelated with it.** A level's own history is what says whether an attempt
on it traps.

For scale, `slowing` earned its place in the break model at **AUC 0.5237**,
purely because its correlation with `approach_vol` was +0.008. Both of these
clear that bar.

## What this does not say

**It is not 0.658.** The break model's two strongest inputs separate hold from
break at 0.658 over 10,904 touches. Trap-from-break at 0.567 is a weaker
question answered less well, and the gap should be stated rather than smoothed:
knowing an attempt is coming is worth more than knowing which kind it is.

**`experience` and `strength` are one input, not two.** At r = +0.963 a model
given both is given the same number twice, which is how a fit acquires
confidence it has not earned.

**And the timeframe finding is a base rate, not an edge.** 94.6% traps on 30m
is a fact about the population, and a strategy that simply faded every 30m
attempt would be taking the base rate, not a prediction. Whether *that* is
tradable is a separate question about cost - the attempt has to be entered
somewhere, and the spread and the stop decide it, which is what
[paying.md](paying.md) prices.

## What would follow

In the order this book usually takes:

1. **Publish `trap_probability` beside `break_probability`**, read by nothing,
   the way `break_probability` itself was published for weeks before anything
   acted. The features are already on every call.
2. **Score it against the constant** the way `calibration.py` scored the break
   model, because a 57.6% base rate is easy to beat on accuracy and hard to
   beat on log loss.
3. **Then the gate that follows is a refusal, not a trade**: `sweep-aware`
   already trades traps, and the first use of a trap probability is declining
   the ones it is wrong about.
4. The adversarial reading in [reading.md](reading.md#game-theory-and-the-question-this-desk-never-asks)
   starts here too - a false breakout is mechanically the obvious trade losing,
   which is what an exploitative strategy looks like from the other side.
