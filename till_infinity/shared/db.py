"""Opening a SQLite file the way all four stores already open it.

`prices`, `news` and `journal` each carried these four lines, identical to the
character:

    sqlite3.connect(path, check_same_thread=False, timeout=30.0)
    PRAGMA journal_mode=WAL
    PRAGMA synchronous=NORMAL
    PRAGMA busy_timeout=10000

Identical is the argument for moving them. Three copies that agree today are
three copies that can disagree tomorrow, and the way that failure shows up -
one collector locking under load while its neighbour does not - is expensive
to trace back to a missing PRAGMA.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

#: Cap on the write-ahead log **file**, in bytes. 64 MiB.
#:
#: **Added 2026-09-23 after this cost the desk a day.** `prices.db-wal` reached **13.07 GB** beside
#: a 29.5 GB database, on a box with 3 GB of memory, and the prices service then died in a loop -
#: `OperationalError: database is locked`, a failing health check 157 times over - while
#: `structures` went 2.5 hours without a decision and `trading` over a day.
#:
#: **This limit is necessary and it is not sufficient. Corrected 2026-09-23, same day, after
#: measuring it on production rather than reasoning about it.** An earlier version of this comment
#: claimed the mechanism was purely cosmetic - that `wal_autocheckpoint` was doing its job and only
#: the *file* failed to shrink. That is wrong. After the reclaim took the database from 27.75 GiB to
#: 5.52 GiB, with this limit live in the deployed image, the log grew 83 -> 164 MB in fifteen
#: minutes and a hand checkpoint reported:
#:
#:     pragma wal_checkpoint(PASSIVE) -> (0, 41764, 11085)
#:
#: Read that as: not blocked (0), 41,764 frames in the log, **11,085 reclaimed**. Checkpoints are
#: completing only partially, so frames accumulate. And `journal_size_limit` truncates only after a
#: checkpoint reclaims the whole log - so while that is happening, the limit is inert. It cannot
#: cap a log that the checkpointer cannot drain.
#:
#: The cause of the partial drain is continuous read pressure: a passive checkpoint stops at the
#: oldest frame any live reader still needs, and `structures` reads this database without pause, so
#: a new snapshot opens before the last one is done with. That much is mechanism. **What is not
#: established** is whether it is a backfill-only condition. The reading above was taken while
#: `structures` was warming at 91% CPU on two cores; steady state may drain fine, and the 13 GB log
#: may have needed the 29.5 GB database to make each read slow enough to hold its snapshot open.
#: That is a prediction with a measurement attached - see `docs/recovering-a-grown-wal.md` - and
#: until it is checked, **the log size under load is the thing to watch, not this constant.**
#:
#: 64 MiB is large enough for a burst across thirty-odd symbols and several intervals, and small
#: enough that opening it costs nothing on a 3 GB box. It takes effect on the next checkpoint
#: rather than immediately, so an existing oversized WAL still has to be truncated once by hand.
WAL_LIMIT = 64 * 1024 * 1024

#: WAL so a reader never blocks the writer, NORMAL because a lost transaction
#: on a crash costs one bar and fsync-per-write costs every bar, a busy
#: timeout because several services share a disk and a lock held for a moment
#: should be waited on rather than raised over, and a size limit because
#: without one the log file only ever grows - see `WAL_LIMIT`.
PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=10000",
    f"PRAGMA journal_size_limit={WAL_LIMIT}",
)


def connect(path: Path | str, *, timeout: float = 30.0) -> sqlite3.Connection:
    """A writable connection with the settled PRAGMAs applied.

    `check_same_thread=False` because every service here hands its connection
    between the loop and whatever thread the driver used, and the alternative
    is a connection per call on a box with one disk.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=timeout)
    for pragma in PRAGMAS:
        conn.execute(pragma)
    return conn


def read_only(path: Path | str, *, timeout: float = 10.0) -> sqlite3.Connection:
    """A connection that cannot write, for anything analysing rather than collecting.

    Enforced at the driver rather than by remembering: a reader that can write
    is one stray statement away from being a writer, and these files are the
    evidence every measurement in `research/` is computed from.
    """
    return sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True, timeout=timeout)
