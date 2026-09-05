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

## The sixth: a gate that has never rejected anything — 2026-09-05

`Inference.actionable` is four gates, and the first is

```python
self.own_touches + self.neighbours >= 8
```

Its docstring explains the reasoning well: *"a big edge on four touches is
noise"*. It cannot enforce that. `neighbours` is the kNN's `DEFAULT_K = 12`,
returned in full whenever the model is warm - which it always is, because it
pools across instruments - so the sum clears 8 on borrowed evidence alone
before the level's own record is consulted at all.

Measured over 20,000 level calls:

| | |
| --- | --- |
| `neighbours == 12` | 19,992 of 20,000 |
| passes `own + neighbours >= 8` | **20,000 of 20,000 (100%)** |
| calls with **zero** own touches | 2,559 (13%) |

It has never rejected a call. It surfaced because 250 ccxt feeds were
registered on 2026-09-04 and immediately produced level alerts reading
`0 touches here + 12 similar` - the gate reporting eight touches' worth of
evidence for a level that had never been touched.

### And the obvious fix is not supported by the record

Requiring the touches be the level's own is the reading the docstring invites,
so it was measured before being written. Over 141,857 resolved touches:

```
actionable only    n       median |push|    held
own 0            1,252          2.272      90.2%
own 8+           5,825          2.222      91.7%
```

**1.5 points of held rate across the entire range, and the median push is
flat.** A level's own touch count barely separates how its next touch resolves,
so tightening the gate on it would refuse a seventh of all calls to buy almost
nothing.

That is the same trap `actionable` already documents at the top of its own
docstring - `MIN_REWARD_TO_RISK` was "the most principled of the set" and was
measured to *invert* the expected return. An inert gate is worth recording; it
is not on its own an argument for a stricter one.

**What was fixed instead** is the thing that actually did harm: the alert
budget. `NOTIFY_MAX_PER_HOUR` is 15, and eight of them went to DRAM, FARTCOIN,
MUU and MSTR inside four minutes - instruments with no broker behind them,
because nothing trades ccxt. A message no action can follow is spending
attention that a tradable instrument needed, so `NOTIFY_FEEDS` now allows only
the traded set. The signal keeps being recorded and learned from; it stops
interrupting anybody.

## The seventh, eighth and ninth: state that was never kept — 2026-09-05

Three faults, one cause. **The trading service persisted nothing at all** -
every dict on it was in memory only - and each of these looked like a separate
bug until the third one made the pattern obvious.

| what | why it did nothing | how long |
| --- | --- | --- |
| `break_even_at` on a restarted position | `_best` reset, so a trade at 2R looked like one at its entry | every restart |
| the daily loss limit | a fresh `Guard` cleared `realised` and `halted` and re-based `opening_equity` | every restart |
| the strategy ranking | `policy` and the untaken record started empty | every restart |

The first cost money and can be counted: **nine trades reached 1R or better and
lost anyway, six of them closing at a full stop** - break-even never proposed on
a move already earned. It also hid its own size, because `best_r` on the close
is read from the same dict, so any give-back measured after a restart records
only the peak since the restart.

The second is worse in kind, because it is a **risk control that silently
resets**. `Guard.roll`'s docstring rejects carrying a halt "until someone
restarts the process", and the code had the opposite failure: a deploy cleared
the day's realised loss, lifted the halt, and set `opening_equity` to the
already-reduced equity - a lower base, from which another full daily loss was
allowed. There were ten deploys that day.

### What made it invisible

Everything downstream **kept working on a defensible default**. An empty
`_best` is not an error; it is a position nobody has quoted yet, which is a
real state on the first tick after adoption. A zero `realised` is a day that
has not lost anything, which is true every morning. An empty ranking is a
desk that has not learned yet, which is true on a first run. Each reset
produced a legal value that the code was already written to handle.

> Nothing here failed. Everything here started again, and starting again looks
> exactly like starting.

### And the same shape, one level down

Fixing it introduced a fresh instance of the pattern within the hour. The new
`state_dir` defaulted to `.data/trading`, a real directory in the repository,
so every test that built a `Trader` wrote the day's total there and the next
test read it back. `realised` came out at 103.8 where the test had earned 59.4;
the other 44.4 belonged to a different test. One shared temporary directory
had the same fault - it has to be per call.

A test that reads state it did not write is not testing the thing it names.

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
