# What a different target would have made, and why we cannot say yet

**Built 2026-10-08.** The supervisor's first object, and the first thing it
found was a hole in the record.

## The idea

[`the supervisor plan`](../../docs/plans/2026-10-08-opportunity-as-supervisor.md)
argues that `opportunity` should correct the other strategies rather than
compete with them, and that **geometry is the only correction worth starting
with**, because of an asymmetry nobody had named:

* *"your reward should be 1.5, not 1.25"* has a **recoverable counterfactual** -
  same entry, same stop, did price get there first
* *"do not take this trade"* destroys its own evidence - the trade is never
  taken and nothing can ever score the advice

So this does not model which strategy is best. It models **the value of a
correction**, which has a label.

## The counterfactual needs no bars

Each outcome records `best_r`, the furthest the trade ever ran in its favour,
so any target at or below it was reached before the exit - the exit is what
ended the recording. For a proposed reward `rr`:

| | |
|---|---|
| `rr <= best_r` | `+rr` - reached, before whatever ended it |
| `rr > best_r`, stopped | `-1.0` - a further target changes nothing |
| `rr > best_r`, held out | `r_multiple` - never reached, same clock, same exit |
| `rr > best_r`, took target | **censored** - it would have run on, unseen |

Lowering a target is exactly computable; raising one is only computable when
the trade did not reach its own.

**And the path stays valid when the target moves**, which is the objection to
answer: `break_even_at` and `trail_vol` both trigger on **R reached**, not on
where the target sits, so the stop behaves identically under a different target
and the recorded excursion still applies.

## The decision interval is a bootstrap, not a conformal one

The plan this came from got that wrong and it is worth correcting in public.
Conformal gives a **per-trade** prediction interval - how much regret the next
trade might see. The question is *"is the mean regret of this correction above
zero"*, which is a confidence interval on a mean, so it gets the day-block
bootstrap this repository uses everywhere else.

Conformal still has a job here and it is the second one: reporting the spread a
desk would live through. It is not the thing that decides.

## What it found instead

**`best_r` is unusable, and in the worst possible way.**

It reads exactly zero on **45% of closes** and 81-94% per day since
2026-10-05, and **34.6% of those zeros closed positive** - which no trade can
do without having been in front. The cause is in
[`trading-service.md`](trading-service.md): the excursion trackers are process
memory and nothing restores them.

The trap is that **the damage is correlated with the outcome**:

* a winner that loses its peak is visible - it finishes above its own recorded
  best, which is impossible
* a loser that loses its peak is invisible - `max(0, r_multiple)` is zero for a
  loser and `best_r` is never below zero

So dropping the impossible rows drops **51.9% of winners and 0% of losers**,
and the win rate of what survives falls from 46.1% to 29.2%. Keeping them
leaves losers carrying a fabricated zero, which says the trade was never in
front and suppresses the value of any earlier target.

**There is no third option on this data.** Filtering biases it one way, not
filtering biases it the other. The first run - before the bias was found -
reported a positive correction for every strategy at every reward, 26 of 40
cells, which is what a bias looks like and what gave it away.

## So it refuses

`telemetry()` runs first and prints either way, and the "corrections to act on"
list is withheld while the unrecorded share is above `MAX_UNRECORDED`. The
cells are still printed, labelled as biased, so the size of the mistake is
visible rather than hidden.

That is the deliverable: **the model is correct and the question is
unanswerable until the record is.** `excursion_partial` makes the record say
which rows to drop, at adopt time, independent of the outcome - and once it has
run for a while this becomes answerable without changing a line here.

## One thing worth keeping from the broken run

The mechanism the regret model is looking for is real even if the measurement
is not: a trade that reaches `best_r` and exits lower has given back open
profit, and `opportunity.py` says as much in its own scale-out note - *"the
direct answer to giving back an open profit, which `best_r` can finally
measure"*. It cannot measure it yet. That is the same sentence from the other
side.
