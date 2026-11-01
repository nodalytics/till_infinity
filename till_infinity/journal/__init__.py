"""The decision journal: what we decided, and why we decided it then.

An append-only record of choices, the reasoning behind them, and the state they
were made from. Two audiences:

- **Whoever is looking at a live desk**, which otherwise has the orders and the
  fills and no record of the refusals. Nautilus persists what happened; the
  journal is the only thing that holds *why*.
- **Whatever gets built later.** A decision, the state it was made from, and
  what happened afterwards is a labelled example. Collecting those from the
  start costs almost nothing; reconstructing them a year later is impossible,
  because the reasoning was never written down.

## Writing

One writer, and it is a Nautilus Actor. A strategy publishes and returns:

```python
from till_infinity.journal import Entry, Kind
from till_infinity.journal.actor import publish

publish(
    self,
    Entry(
        title="Refused gold at the spread",
        kind=Kind.DECISION,
        actor="EdgeEntry-GOLD",
        rationale="30bps against a 0.3bps 24h average, no calendar entry",
        context={"venue": "OANDA", "spread_bps": 30.0, "avg_bps": 0.3},
        tags=("gold", "OANDA"),
        confidence=0.9,
    ),
)
```

`JournalActor` validates, buffers and writes on a timer, so publishing costs a
decision a dict and a deque append -
[ADR 0005](../../docs/adr/0005-the-journal-is-the-record-not-the-hot-path.md).
`Journal.write` is still there and is what a script or a test uses, because
recording something should not require a node to be running.

**`service.py` and `bus.py` are retired** to `research/retire/journal/` -
`decide`, `observe`, `outcome`, `note`, `record`, `open_journal`, `listen` and
the `Carrier` transport. The Actor is the writer and `Entry` carries its own
validation; see that directory's `RETIRED.md`.

## Reading

`read`, `get`, `summary` and `export` open the file `mode=ro`, so nothing that
analyses history can rewrite it. **Nothing here imports Nautilus** - the engine
is in `actor.py` and nowhere else - so a research harness can read the record
without building a node.

Entries are content-addressed and written `INSERT OR IGNORE`, so recording the
same decision twice is one entry. Nothing is ever updated: an outcome is a new
entry pointing back at its parent. A journal you can edit is not a journal.
"""

from __future__ import annotations

from .models import Entry, Kind
from .store import DEFAULT_DB, MAX_ROWS, Journal, export, get, read, read_only, summary

__all__ = [
    "DEFAULT_DB",
    "MAX_ROWS",
    "Entry",
    "Journal",
    "Kind",
    "export",
    "get",
    "read",
    "read_only",
    "summary",
]
