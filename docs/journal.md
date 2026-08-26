# The journal

An append-only record of what was decided, **why it was decided at that
moment**, and what the world looked like when the decision was made.

```bash
uv run till-infinity journal list                 # recent entries
uv run till-infinity journal show <id>            # one entry, and what followed
uv run till-infinity journal add "Widened the spread threshold to 12bps" \
    --why "8bps fired six times overnight on TVC, none of which were real" \
    --kind decision --tag gold
uv run till-infinity journal export -o data/journal.jsonl
```

## Why it exists

Two audiences, and they want the same thing for different reasons.

**The agents.** Without a journal an analyst judges every window with no memory
of what it concluded an hour ago, so it reports the same dislocation sixty
times and never learns that the last one resolved itself. `recent` is a tool on
every role for exactly this.

**Whatever gets built later.** A decision, the state it was made from, and what
happened afterwards is a labelled example. Collecting those from the start
costs almost nothing. Reconstructing them a year later is impossible - not
because the prices are gone, but because *the reasoning was never written
down*, and the reasoning is the only part that cannot be recomputed.

## Point-in-time, not by reference

`context` holds the state the decision was made from, **copied in**:

```python
context = {"venue": "OANDA", "spread_bps": 30.0, "avg_bps": 0.3}
```

Not a pointer to the quotes table. This is the difference between a dataset and
a leak. The stores keep moving: bars get corrected, an event's `actual` lands, a
quote is superseded a second later. An entry that said *"see the quotes table"*
would, a month on, describe a world that no longer exists - and a model trained
on it would be learning from information the decision never had.

## Append-only, and it is enforced

- Writes are `INSERT OR IGNORE` on a content-addressed id, so recording the
  same decision twice is one entry - a watcher that restarts and re-judges a
  window does not double-count.
- There is no update path. An outcome is a **new** entry pointing back at the
  decision it judges.
- Reads open the file `mode=ro`, so an analyst reading its own history cannot
  rewrite it.

A journal you can edit is not a journal: the value of "why we thought that at
the time" is entirely in nobody having tidied it up afterwards.

## The four kinds

| kind | what it is | why it is kept |
|---|---|---|
| `decision` | we chose to do or say something | carries the rationale |
| `observation` | we looked and did **not** act | the negative example |
| `outcome` | what happened after an earlier entry | the label |
| `note` | human context - why a threshold changed | the part no code knows |

`observation` matters more than it looks. A dataset of only the times we acted
teaches a model when to act and nothing at all about when to hold off, and
holding off is most of the job.

## Closing the loop

A decision without what happened next is half a training example, so `decide()`
returns an id and `outcome()` takes it:

```python
from till_infinity.journal import Journal, decide, outcome

async with Journal() as journal:
    ref = await decide(
        journal,
        "Alerted on OANDA gold spread",
        rationale="30bps against a 0.3bps 24h average, nothing on the calendar to explain it",
        context={"venue": "OANDA", "spread_bps": 30.0, "avg_bps": 0.3},
        tags=("gold", "OANDA"),
        confidence=0.9,
    )

    # ... four minutes later ...
    await outcome(
        journal,
        ref,
        "Spread normalised within 4 minutes",
        rationale="Back to 0.31bps, so it was a momentary feed gap, not a dislocation",
        context={"spread_bps": 0.31},
    )
```

An outcome inherits its decision's tags unless given its own - otherwise a
filter on `gold` would hide the very entry saying the gold situation resolved
itself.

## What structures records automatically

The levels model produces the one thing here with **unambiguous ground truth**:
a touch resolves, and the resolution says what price did. So every level call
is journalled and its result attached when it arrives.

```
decision    gold 4401.78: up from above, p=71% vs 48% base, push +1.6v
  outcome   gold 4401.7: reject, up 15.57v      (parent -> the decision)
```

**Calls that were not acted on are recorded too**, as observations. Only
`actionable` calls become alerts, and a dataset containing only the calls we
acted on is the worst possible sample to learn from: it cannot say when holding
off was right, because holding off never appears in it. Same features, same
outcome attached later, no alert.

One replay of stored history produced 2 decisions, 19 observations and 20
outcomes - twenty complete `(state, action, outcome)` triples across rejects,
breaks, a trap and a back check.

Two details that had to be right for any of this to work:

- The pairing key is the level price **recorded with the touch**, not the
  level's current one. The Kalman mean moves when the touch is folded in, and
  that happens before the outcome is written - so looking up by the level's
  price searches for a key that no longer exists. This produced zero outcomes
  until it was found.
- Only level calls wait for an outcome. A wide spread has no comparable moment
  of being proven right or wrong, and inventing one would fill the record with
  labels nobody could check.

## What the agents record automatically

`agents watch` journals every window it takes to a model:

- an **alert** becomes a `decision`, with the finding's reasoning, its evidence,
  the trigger that woke the model and the confidence;
- a window that woke the model and produced **nothing** becomes an
  `observation` - something crossed the arithmetic gate, a model looked at it
  properly, and decided it was nothing;
- a quiet window records nothing at all. That was arithmetic, not a decision.

Turn it off with `--no-journal` or `JOURNAL=0`.

## Exporting

```bash
uv run till-infinity journal export -o data/journal.jsonl --kind decision
```

JSON lines, **oldest first** - the order a sequence model wants - one object per
line, which every dataframe loader reads without arguments. `context` stays
nested rather than flattened, because flattening here would bake in one guess
about which features matter.

```python
import pandas as pd

df = pd.read_json("data/journal.jsonl", lines=True)
features = pd.json_normalize(df["context"])
```

Join decisions to outcomes on `parent` to get `(state, action, result)` triples.

## The journal is a service

Everything else talks over the bus, and the journal used to be the exception -
a library each service called in-process, so `agents` and `structures` each held
their own connection to the same file.

```bash
uv run till-infinity journal listen --redis redis://localhost:6379
```

Now they publish to the `journal` topic and one process records:

```
agents ─────┐
structures ─┼──▶ journal ──▶ journal listen ──▶ journal.db
anything ───┘
```

One writer, and a service on another machine can record a decision at all.

**The direct path stays.** `Journal.write` is still there and is what tests and
one-off scripts use - a bus is a dependency, and recording a decision should not
require one to be running. A caller passing both gets the bus, since a single
writer is the point.

**Nothing off the bus is trusted.** An entry arrives as a dict from a process we
did not write, so it is validated rather than assumed: a missing title is
dropped, a `context` that is not a mapping becomes empty, a `confidence` that is
not a number becomes None. The `id` on the wire is ignored and recomputed from
the content, so a sender cannot claim an id that does not match what it sent -
and two services publishing the same decision still collapse to one row.

## Environment

| | |
|---|---|
| `JOURNAL_DB` | where it lives (default `.data/journal/journal.db`) |
| `JOURNAL` | `0` to switch journalling off |
