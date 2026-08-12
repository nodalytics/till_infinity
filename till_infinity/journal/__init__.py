"""The decision journal: what we decided, and why we decided it then.

An append-only record of choices, the reasoning behind them, and the state they
were made from. Two audiences:

- **The agents**, which otherwise judge every window with no memory of what
  they concluded an hour ago. `recent()` gives an analyst its own history.
- **Whatever gets built later.** A decision, the state it was made from, and
  what happened afterwards is a labelled example. Collecting those from the
  start costs almost nothing; reconstructing them a year later is impossible,
  because the reasoning was never written down.

```python
from till_infinity.journal import Journal, decide, outcome

async with Journal() as journal:
    ref = await decide(
        journal,
        "Alerted on OANDA gold spread",
        rationale="30bps against a 0.3bps 24h average, no calendar entry to explain it",
        context={"venue": "OANDA", "spread_bps": 30.0, "avg_bps": 0.3},
        tags=("gold", "OANDA"),
        confidence=0.9,
    )
    await outcome(journal, ref, "Spread normalised within 4 minutes",
                  context={"spread_bps": 0.31})
```

Entries are content-addressed and written `INSERT OR IGNORE`, so recording the
same decision twice is one entry. Nothing is ever updated: an outcome is a new
entry pointing back at its parent. A journal you can edit is not a journal.
"""

from __future__ import annotations

from .models import Entry, Kind
from .service import decide, note, observe, open_journal, outcome, record
from .store import DEFAULT_DB, MAX_ROWS, Journal, export, get, read, read_only, summary

__all__ = [
    "DEFAULT_DB",
    "MAX_ROWS",
    "Entry",
    "Journal",
    "Kind",
    "decide",
    "export",
    "get",
    "note",
    "observe",
    "open_journal",
    "outcome",
    "read",
    "read_only",
    "record",
    "summary",
]
