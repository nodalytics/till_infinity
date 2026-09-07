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

#: WAL so a reader never blocks the writer, NORMAL because a lost transaction
#: on a crash costs one bar and fsync-per-write costs every bar, and a busy
#: timeout because several services share a disk and a lock held for a moment
#: should be waited on rather than raised over.
PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=10000",
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
