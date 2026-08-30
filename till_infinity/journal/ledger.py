"""What each level made or lost, added up over its own trades.

The question "which levels have been profitable" could not be answered, and the
reason was not missing data - every closed trade already journals its `profit`
and the price it was trading. It was that **a level's price is not its name**.

The Kalman filter moves a level's price whenever it learns something, so one
level traded twice is journalled at two prices, and grouped by price its two
trades become two levels with one trade each. Asked directly, the record said
"117 levels, 119 trades, one traded more than once" - which is a fact about
grouping a drifting number, not about the market.

`structures.levels.Level.id` is the fix and this is what reads it. Grouping is
by identity; the price is reported as whatever the level had last, which is
information about where it is now rather than what to add up by.

## Reads the journal and nothing else

No store, no bus, no engine. A trade's outcome is already the whole record -
the level's name, the strategy that took it, how it ended and what it made - so
this is a query, and a query is the right shape for something a person runs
when they want to know rather than something that runs all the time.

Trades journalled before the level id existed carry no name. They are counted
in the totals and grouped under `""`, reported as *unnamed* rather than folded
into one enormous level or silently dropped - the first would be a lie and the
second would make the totals not add up.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Record:
    """One level's trading record."""

    level_id: str
    feed: str = ""
    interval: str = ""
    #: Where the level was when it was last traded. Not the grouping key - see
    #: the module docstring on why the price is not a name.
    price: float = 0.0
    profits: list[float] = field(default_factory=list)
    strategies: set[str] = field(default_factory=set)
    endings: dict[str, int] = field(default_factory=dict)

    @property
    def trades(self) -> int:
        return len(self.profits)

    @property
    def net(self) -> float:
        return sum(self.profits)

    @property
    def wins(self) -> int:
        return sum(1 for p in self.profits if p > 0)

    @property
    def hit_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def named(self) -> bool:
        """False for trades taken before levels had identities."""
        return bool(self.level_id)

    def __str__(self) -> str:
        who = f"{self.feed} {self.price:.6g} {self.interval}".strip()
        name = self.level_id or "unnamed"
        return f"{name} {who}: {self.net:+.2f} over {self.trades} trade(s), {self.wins} up"


def outcomes(database: str | Path, *, limit: int = 200_000) -> Iterator[dict]:
    """Closed-trade contexts from the journal, oldest first.

    Read-only and tolerant: a row whose context is not JSON is skipped rather
    than raised on, because a reporting query must not be the thing that fails
    when one row is malformed.
    """
    conn = sqlite3.connect(f"file:{Path(database)}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT context FROM entries WHERE actor = 'trading' AND kind = 'outcome'"
            " ORDER BY time ASC LIMIT ?",
            (limit,),
        )
        for (blob,) in rows:
            try:
                found = json.loads(blob or "{}")
            except (ValueError, TypeError):
                continue
            if isinstance(found, dict) and found.get("profit") is not None:
                yield found
    finally:
        conn.close()


def ledger(rows: Sequence[dict] | Iterator[dict]) -> list[Record]:
    """One `Record` per level, richest first."""
    found: dict[str, Record] = {}
    for row in rows:
        try:
            profit = float(row["profit"])
        except (KeyError, TypeError, ValueError):
            continue
        name = str(row.get("level_id") or "")
        record = found.get(name)
        if record is None:
            record = found[name] = Record(level_id=name)
        record.feed = str(row.get("feed") or record.feed)
        record.interval = str(row.get("interval") or record.interval)
        with contextlib.suppress(TypeError, ValueError):
            record.price = float(row.get("level") or record.price)
        record.profits.append(profit)
        if row.get("strategy"):
            record.strategies.add(str(row["strategy"]))
        ending = str(row.get("exit_kind") or row.get("reason") or "")
        if ending:
            record.endings[ending] = record.endings.get(ending, 0) + 1
    return sorted(found.values(), key=lambda r: -r.net)


def totals(records: Sequence[Record]) -> dict[str, float]:
    """The totals, so a caller does not re-derive them and get them different.

    Not called `summary`: `journal.store` already exports one, and two
    differently-shaped functions of that name in one package is how a caller
    ends up importing the other one and getting a plausible wrong answer.
    """
    trades = sum(r.trades for r in records)
    net = sum(r.net for r in records)
    wins = sum(r.wins for r in records)
    named = [r for r in records if r.named]
    repeated = [r for r in named if r.trades > 1]
    return {
        "levels": float(len(records)),
        "named_levels": float(len(named)),
        "levels_traded_more_than_once": float(len(repeated)),
        "trades": float(trades),
        "net": round(net, 2),
        "wins": float(wins),
        "hit_rate": round(wins / trades, 4) if trades else 0.0,
    }


def report(database: str | Path, *, top: int = 12) -> str:
    """The whole thing as text, for a person at a terminal."""
    records = ledger(outcomes(database))
    if not records:
        return "no closed trades recorded"
    counts = totals(records)
    lines = [
        f"{int(counts['trades'])} closed trades over {int(counts['levels'])} level(s), "
        f"net {counts['net']:+.2f}, hit rate {counts['hit_rate']:.0%}",
        f"{int(counts['named_levels'])} carry a level id; "
        f"{int(counts['levels_traded_more_than_once'])} of those were traded more than once",
        "",
        "best",
    ]
    lines += [f"   {record}" for record in records[:top]]
    lines += ["", "worst"]
    lines += [f"   {record}" for record in reversed(records[-top:])]
    return "\n".join(lines)
