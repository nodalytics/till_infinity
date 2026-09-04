# Features that ship, configure, log correctly, and do nothing

Four in one day on 2026-09-03, and more the day after. Each passed its tests,
each described itself accurately in the logs, and each changed nothing about
the running system. They are collected here because the pattern is now the most
common defect in this repository and the individual write-ups bury it.

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

## The fifth, and the one that reported a result — 2026-09-04

| what | why it did nothing | how long |
| --- | --- | --- |
| `max_spread` / `min_days` on the ccxt board | `fetch_tickers` carries neither field, and `_rejects` skips a zero reading on purpose | since written |
| `drift.py`'s "settled" report | read `models.pkl`, which stopped being the live state when the store moved to msgpack | ~12 hours |

The first is the familiar shape. Measured against the live Binance board, all
762 rows came back `bid=0, ask=0` and `listed_days=0`, so a `max_spread` of
1e-9 rejected nothing and a `min_days` of 10,000 rejected nothing, while a
control `min_volume` of 1e12 correctly rejected all 762. Two of six filters were
decoration, and the fixtures hid it by setting both fields by hand.

**The second is worse than inert and belongs in a category of its own: it
produced a confident, specific, wrong answer, and I relayed it.** `drift.py`
watches the break model's weights and reports whether they are settling. Its
path was hardcoded to `models.pkl`. When the store moved to msgpack that file
stopped being written, and from 07:05 onwards every check compared one frozen
snapshot against itself. Movement came out at exactly 0.000 three times running
and it announced the model **SETTLED**.

It had not settled. Against the live state the weights were

    approach_vol -0.371 · depth_vol -0.285 · slowing -0.153
    prior_slope  +0.121 · interval_log -0.078 · slope  +0.057

against the stale file's `-0.166 / -0.492 / +0.011 / -0.138 / +0.067 / -0.100`:
three signs flipped, the ordering changed, total movement **1.135**.

Everything above this section is about a feature that goes quiet. This one
*spoke*, and what it said was the strongest possible version of the claim it
was built to test. **A monitor reading a stale source does not fall silent - it
reports perfect stability**, because an unchanging file is indistinguishable
from a converged model by every measure the monitor has. That is the most
dangerous form of this defect, since silence invites a check and a clean result
ends one.

The same script also killed the link alert it rode on. It unpickled by hand
rather than through `store.load`, so once `structures/` grew subpackages it
died with `No module named 'till_infinity.structures.anomaly'` - and because it
ran last over ssh, **its exit code became the link's**. The watcher reported the
host unreachable for an hour while the host was answering every request. A
failing component inside a health check is reported as the health of the whole.

### What it added to the list

* **A watcher needs a check that it is watching.** Movement is now only counted
  when the state file's mtime has changed; otherwise it says so. Two checks
  inside one save window read identical bytes and would otherwise score a
  perfect 0.000 - the same trap one level down.
* **Operational scripts rot faster than code and are tested by nobody.** These
  two lived only in `/tmp` on the box. Nothing imported them, no test ran them,
  and the refactor that moved `structures/` could not have known they existed.
  They are in `research/harness/` now.
* **Zero movement is not evidence of convergence.** It is evidence of *nothing
  having been read*, until the source is shown to have changed.

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
4. **A false alarm, chased rather than dismissed.** `drift.py` was found only
   because a link-down alert fired while the link was demonstrably up. The
   alert was wrong, the thing it was wrong about was real, and the twelve
   hours of "SETTLED" would still be uncorrected if the noisy alert had been
   silenced instead of explained.

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
