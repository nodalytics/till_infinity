"""How long one bar of each timeframe lasts.

This is a **contract**, which is why it is here rather than in a service. An
interval is a string on the bus - `"5m"`, `"1h"` - and every service that reads
one has to agree on what it means. `strategies/profile.py` and `domain/models.py`
convert holds and half-lives with it, `notifications/filters.py` rate-limits
with it, and the structures engine decayed level evidence with it.

It lived in `structures/levels.py` until 2026-10-28, which made four services
import a level model to find out how long five minutes is. `utils/` holds the
things that must be identical on both sides of a boundary, and a unit of time
is the plainest example there is. [ADR 0003](../../docs/adr/0003-python-and-go.md)
is still accepted and names a Go tick service, which would need this table in
both languages agreeing; no Go has been written, so that is a reason to keep
the table honest rather than a thing it is waiting for.

**Spellings are not aliases to normalise away.** `1d`/`daily` and `1w`/`weekly`
are both in use on the bus, from different producers, and a reader that knows
only one of each silently finds nothing for the other - so both are kept and a
lookup takes whichever it is handed.
"""

from __future__ import annotations

#: Seconds in one bar of each timeframe.
SECONDS: dict[str, float] = {
    "1m": 60.0,
    "3m": 180.0,
    "5m": 300.0,
    "15m": 900.0,
    "30m": 1_800.0,
    "1h": 3_600.0,
    "2h": 7_200.0,
    "4h": 14_400.0,
    "1d": 86_400.0,
    "daily": 86_400.0,
    "1w": 604_800.0,
    "weekly": 604_800.0,
}

__all__ = ["SECONDS"]
