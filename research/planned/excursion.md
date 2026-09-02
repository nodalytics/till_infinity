# How much room a trade actually needs

A measurement nobody has taken, and the field it needs is not being written.

## The question

Every stop in this system is placed from a rule — beyond the level, past the
origin's far edge, a multiple of volatility. None of it is placed from a
measurement of how far price *goes against a trade that later wins*.

That quantity has a name in the outcome schema already: `adverse_r`, the
maximum adverse excursion in units of the trade's own risk. A winner with
`adverse_r` of 0.4 never came close to its stop; a winner at 0.95 was one tick
from being cut. The distribution of that number across winners is exactly the
stop width the book should be using, and the distribution across losers says
what widening would have cost.

## What is blocking it

**`adverse_r` and `best_r` read 0.0 on every outcome inspected on 2026-09-02.**
The heat tracking is not populating. `_heat()` and `_heat_vol()` exist in
`trading/service.py` and the fields reach the journal, so this is the familiar
shape: computed somewhere, arriving as a constant, and never contradicted
because zero is a legal value.

First step is therefore not a measurement at all — find why the field is zero,
fix it, and let a few dozen trades accumulate. Nothing below can start until
that is done.

## What to measure once it populates

1. **The winners' excursion distribution.** Median, p75, p90 of `adverse_r`
   over trades that reached target. If p90 is 0.6, stops at 1.0R are wider than
   they need to be and the losses are coming from somewhere else. If p90 is
   0.95, the stop is sitting exactly where winners live and every widening buys
   real trades back.
2. **The same, split by instrument.** Gold is the reason to expect this to
   differ: 9 of 9 of its stopped trades reached target afterwards, and 62% of
   its stopped trades reached target after being stopped against 26%
   book-wide. If gold's winners routinely excurse past 1.0R its stop is simply
   in the wrong place, and that is an instrument-level constant, not a strategy
   one.
3. **The counterfactual cost.** For each loser, how far past the stop did price
   go? Widening from 1.0R to 1.4R converts some losers into winners and makes
   the rest 40% more expensive. The trade-off is computable from the same two
   distributions and does not need a replay.
4. **`best_r` against the exit.** How much of the favourable excursion the
   trade actually captured. A book whose winners routinely reach 2R and exit at
   0.66R has an exit problem, not an entry one — which is what `thesis-only`'s
   +0.66R mean target exit hints at and nothing yet confirms.

## What would falsify the stop-widening story

If winners' `adverse_r` clusters well below 1.0, then stops are not cutting
winners and the post-stop recovery in [failing.md](../failing.md) is the random
walk arriving late rather than the trade being right early. That is the same
doubt [null.md](null.md) exists to settle, reached from the other side — and
the two agreeing would be worth more than either alone.

## Why this is the better instrument

The post-stop replay asks a counterfactual of the *market*: what would have
happened after an exit that did happen. This asks a fact about trades that were
actually held: how much heat they took while being right. No horizon has to be
chosen, no null has to be constructed, and the answer arrives per instrument
rather than as a book-wide average.

## Related

* [null.md](null.md) — the other half of the same question.
* [stops.md](../stops.md) — what stop placement currently rests on.
* [failing.md](../failing.md) — the measurement both of these qualify.
