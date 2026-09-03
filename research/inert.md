# Features that ship, configure, log correctly, and do nothing

Four in one day, 2026-09-03. Each passed its tests, each described itself
accurately in the logs, and each changed nothing about the running system. They
are collected here because the pattern is now the most common defect in this
repository and the individual write-ups bury it.

## The four

| what | why it did nothing | how long |
| --- | --- | --- |
| `slowing` capped at 10.0 | the standardiser's running mean was 141,380,329 and `Scaler` has no decay, so the cap needed ~1e11 samples to matter | ~1 hour |
| `NOTIFY_MIN_INTERVAL=15m` | the alert carried no `interval`, so the filter's "missing means keep" rule fired every time | ~1 hour |
| `STRUCTURES_FORMATION` | `Watcher.load` replaced the configured engine with the pickled one | its whole life |
| `best_r` / `adverse_r` | `_best`/`_worst` were popped on the line *above* the code that reads them | every close ever made |

Two more from the same week: eleven new synthetic feeds polled by nothing and
then warmed by nothing, and `confluence` absent from every outcome so 12,504
resolutions recorded zero agreeing timeframes.

## What they have in common

**The output is a legal value.** Zero is a legal `best_r`. Keeping an alert is
a legal filter decision. A standardised feature near zero is a legal input.
Nothing raises, nothing warns, and every downstream consumer keeps working on a
number that means "nothing happened" when the truth is "this was never
measured".

**The tests were right and tested the wrong end.** `best_r` had tests that
called `_reach` directly, where the ticket is still tracked - they passed
throughout. The notification floor had seven tests that drove the filter with a
hand-made payload. The filter was correct; the *alert* was missing the field
the filter reads.

> Assert against the thing that writes the record, not against a method that
> feeds it.

**The safe default is what hides it.** Every one of these had a deliberate,
correct fallback - keep the alert when the interval is unknown, return 0.0 when
a ticket is missing, use the class default when the setting is absent. Each is
the right behaviour for the case it was written for, and each converts "this is
broken" into "this is quiet".

## What actually finds them

Not tests, in every case so far. What found them:

1. **Asking whether the record is being written.** Three of the four were
   caught by querying the journal for the field after deploying, rather than
   trusting the deploy. The question is always the same: *does this reach the
   thing that reads it?*
2. **A watcher on something that should move.** The `slowing` mean was found
   because a weight watcher armed for an unrelated reason reported
   `approach_vol` moving 0.279 in half an hour. It was looking for whether new
   features earned their place and found a feature that had been mute for
   weeks.
3. **A result that makes no sense under your own explanation.** The
   notification floor was caught because a probe said "1h kept: False". Under
   the story I was telling, that was impossible - and it was the *wrong*
   answer, from a probe that was itself wrong, that made me look again.

## The verification that is worth doing

Cheap, and it would have caught all four:

* **Build the payload the way production builds it.** The first check of the
  notification floor invented a dict with `shape` at the top level, where the
  filter reads it from `fields`. Everything was rejected on shape, the floor
  was never reached, and `1m rejected: True` was true for the wrong reason. The
  second used the real `Signal` and the real `alert_payload`, and immediately
  showed `fields.interval` was absent.
* **Read the state, not the output.** The break model's weights looked
  plausible for weeks. Its standardiser's running mean was eight orders of
  magnitude out and had never been looked at.
* **Check on the far side.** A reverse SSH tunnel bound to the wrong address is
  indistinguishable from a working one on the side that opened it. The same is
  true of every producer/consumer pair here.

## The one that has no fix yet

`Scaler` silently ignores a vector whose length it does not recognise, and
`apply` then returns raw values. That is how adding two features left the
standardiser stale. `RECIPE` handles an input **changing meaning**, and a
length change is handled by rebuilding - but the silent-return remains, and
some other model will find it.
