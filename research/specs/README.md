# Specs

Designs agreed before implementation, so the reasoning can be argued with while
it is still cheap to change. A spec here is a decision and its evidence, not a
plan - the plan is the commits that follow it.

Each says what problem it solves, what it deliberately leaves out, how it can
fail, and what would count as it not working.

| | status | |
| --- | --- | --- |
| [replay kernel](2026-09-11-replay-kernel-design.md) | **implemented** `1188e12` | One forward walk, in the package where CI lints it and the suite covers it. Written because a harness reported a policy at +1.335R against +0.344R, passing a split sample, a shuffled control and a Simpson check, and it was a look-ahead. The re-check it demanded found the number behind `sweep-aware`'s shipping exit was **inflated about tenfold** |
| [field liveness](2026-09-11-field-liveness-design.md) | **implemented** `249a379` | `run_vol` and `pivot` are identically zero across 20,000 production outcomes, and a research direction was nearly built on an option field that is dead at the source. Nothing systematically asks whether a column carries anything |
| [conditioning by default](2026-09-11-conditioning-by-default-design.md) | **implemented** `249a379` | Simpson's paradox has reversed a pooled figure here **four times**. The rule is correct and does not survive contact with a new question, so it becomes mechanical: cut within strata by default, and shout when the ordering flips |
| [VIX as an ensemble member](2026-09-11-vix-ensemble-member-design.md) | **built, measured, shipped off** | The only positive result in this folder, unwired. Built, then measured over 20 years before being switched on - and it **loses**: `har` wins every series and `vix` is last on half. It is informative and *biased*, because test one refit a coefficient at every step and an ensemble of point forecasts does not. Ships off; the fix is a member that fits its own scale |

## The order

The first three are measurement work and the fourth is an edge. That sequence is
deliberate: on 2026-09-11 three conclusions died to instrument faults rather
than to the market, and one of them nearly shipped. Searching harder for an edge
with a harness that can manufacture one is how you find an edge that is not
there.

## What is not here yet

* **The live-journal cross-check.** A replay that disagrees with the live record
  should say so - 98% stop against 81% timeout was the tell that the exit
  replay could not see what the live desk was doing. Designing *what counts as
  disagreement* is the hard part and it has not been done.
* **The inert exit.** `sweep-aware`'s break-even sits at 1.0R against a median
  peak of 0.445R and its trail is uncapped, so on nine trades in ten neither can
  engage. The arithmetic is in [giveback.md](../giveback.md); it waits on the
  cross-check, because the only harness that could verify a change is the one
  that cannot see the effect.
* **The resident cost.** Bounding the state took the file from 218MB to 103MB,
  but holding it still costs 1.27GB - a factor of **six**, unchanged and
  unexplained beyond "Python objects".
