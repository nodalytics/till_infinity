# Turn Exit Silence

A shipped, always-on shadow that produced **zero** rows in production, and what
the record said about why. Measured 2026-10-16 on 45 days of journal, 2026-08-26
to 2026-10-10.

`trading/turning.py` rides the turn model's exit alongside the real one and
scores both from the same path. It acts on nothing; its whole output is a
journal row and a headline, `gained_r_per_trade`, which the module calls the
whole question. The effect `trading.turn_exit` is declared **always on** for
exactly this reason - a shadow that costs nothing should never be silent, so
silence is a fault rather than a configuration.

It was silent for its entire life. The effect reported inert and not one of
1,825 outcomes carried a scored comparison.

## The two candidates, and the one the record eliminates

The module named both: "either the depth head is never warm on a traded feed or
`turn_price` is not reaching `Intent.features`". The decisions settle the first.

Reproducing `suggestion_from` and `TurnExit.scorable` offline on the decision
records, which carry every field both of them read:

| step | n | share |
|---|---|---|
| decisions in the window | 3,266 | |
| carry a usable `turn_price` | 1,163 | 100% |
| the model agrees on the trade's side | 768 | 66.0% |
| the model names the other side | 395 | 34.0% |
| suggestion behind the entry (< 0.1R) | 364 | 31.3% |
| **scorable** | **404** | **34.7%** |

So the head is warm on traded feeds, the side agreement is near even rather than
systematically refused, and about four hundred trades in forty-five days clear
every gate. Nothing about the model's output explains the silence.

`ahead` over the 768 same-side suggestions, in R: p5 −0.94, p25 −0.28, p50
+0.11, p75 +0.40, p95 +1.07. Two readings worth keeping - 40.9% sit behind the
entry, which is the model saying the move is already over rather than naming an
exit, and only 52.6% land inside `[MIN_AHEAD, MAX_R]`. The same-side share is
also not uniform across strategies: 73-76% for level-scalp, thesis-only,
sweep-aware, runner, confluence-scalp, momentum-scalp and snap, against 50.4%
for cycle-scalp, 48.4% for fade-to-value and 25.4% for inverse. A strategy that
systematically trades against the turn model is a finding about the strategy,
and it is left here rather than acted on.

## The cause

`_turn_exit` had exactly one caller: `_unattributed_context`, the close record
built when **no decision is on record**. An unattributed close has no decision,
so no `turn_price` in its features, so `suggestion_from` returns 0.0 and
`_turn_exit` returns `{}` - every single time. Every attributed close goes
through `_settle`, which never called it.

The comparison was wired exclusively into the one path that cannot satisfy it.

This is the same omission, one field group over, as the one already fixed for
`best_after` and `worst_after`: "`_unattributed_context` has carried these for
that reason and this path did not, so across 1,202 closed trades in the live
journal not one record carried either." Two independent instances of the same
shape is a pattern rather than an accident - a new field gets added where the
author was reading, and the other builder is a separate function far away.

## Why its own test passed

The end-to-end test asserted `any(k.startswith("turn_") for k in context)`.
`Intent.to_context` splats the features onto the close record, so the signal's
own `turn_price` lands there whether or not anything scored it. The test went
green on the raw feature riding through, while nothing had been scored, and its
docstring then drew the opposite conclusion - that the wiring was sound and the
live silence must be environmental.

An assertion that cannot fail for the reason it was written is worse than no
assertion, because it is read as evidence. It now asserts on `turn_suggested_r`
and `turn_took_r`, the fields `report.compare_turn_exits` actually requires, and
it fails on the unfixed service.

## The second defect, which the first one hid

`_reach` reads `_best`, which is process memory that no restart restores. A
position adopted mid-flight is first marked long after it opened, so `best_r`
is a **floor rather than a measurement**, and `_reach` cannot tell that from a
trade that never went in front: both read 0.0. `Trader._partial` records which
tickets those are, at adopt time, before the result exists - and nothing read
it. It was written to the journal and gated nothing.

Scored anyway, a partial row reads "never reached", which sets the suggestion
equal to what the trade took: zero into the numerator of `gained_per_trade` and
one into its denominator. The headline is diluted by exactly the partial share,
which the service measured at 85-94% of closes in October. The number the module
calls the whole question would have read about a tenth of itself, and it would
have read that way from the first row - so fixing the wiring without fixing this
would have replaced a visible silence with a plausible wrong answer.

The journal shows how large the corruption is, using an identity rather than a
model: a stopped trade reached its stop, so `adverse_r` must be at least 1.0.

| check | n | share |
|---|---|---|
| stopped trades | 282 | |
| reporting `adverse_r` < 1, which is impossible | 179 | **63%** |
| closes reporting `adverse_r` exactly 0 | 351 of 1,200 | 29% |

**Dropping only the rows that read short is the tempting half-fix and it is
worse than the bug.** A floor can only understate, so `best_r` clearing `ahead`
does prove the level was crossed, and keeping those rows is sound in isolation.
But the lost peaks belong to winners - a loser never had one - so keeping the
long readings and dropping the short ones selects on the outcome being measured
and biases the headline *upward* instead of down. Partial rows come out
whichever way they read. `rides` still counts them, so how much of the book the
comparison never covered stays visible as `rides` against `scored`.

## What the journal cannot say

The 369 outcomes whose decisions published a `turn_price` all carry the narrow
29-32 key close record - `_settle`'s own fields, no features, no
`excursion_partial`, no `best_after`. The feature-rich close (127-154 keys)
appears on other outcomes in the same window. So the record shape changed
mid-window and no deployed build carried both `turn_price` publication and the
wide close record at once, which means the journal cannot corroborate the wiring
fault directly. The code does: one call site, in the wrong builder.

## What this does not do

It starts the comparison. It still acts on nothing, and
`report.compare_turn_exits` refuses to read a headline under `ENOUGH` scored
rows, so the first honest answer is some weeks out. At 404 scorable decisions in
45 days, minus whatever share of those is partial on the day, that is the rate
to expect rather than one row per close.
