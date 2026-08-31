"""Does the macro stance condition whether a level call is right?

A rate differential's *level* is in the forward curve by covered interest
parity, so it is priced. What is not priced is the change. FRED cannot supply a
daily cross-country differential - every foreign rate series on it is monthly
and lagged - so the change cannot be traded directly here at any useful
frequency.

What it can do is condition. `macro_carry_gap_change` is on every level call,
and every call's outcome is linked to it by parent ref, so the question "do
calls that agree with the macro drift resolve better than calls that fight it"
is a join rather than a rebuild.

**Per horizon band**, because research/similarity.md found the sub-minute
population resolves 100.0% in the direction its side implies - a tautology that
swamps any conditional pooled across it. Macro moves daily, so it can only
matter at the slow end, which is also the thinnest.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"
LIMIT = 400_000

BANDS = (
    ("0-60s", 0.0, 60.0),
    ("60-300s", 60.0, 300.0),
    ("300-1800s", 300.0, 1800.0),
    ("beyond 1800s", 1800.0, float("inf")),
)


def joined() -> list[dict]:
    """Level calls paired with what happened, by parent ref."""
    conn = sqlite3.connect(JOURNAL, uri=True)
    calls: dict[str, dict] = {}
    for ref, blob in conn.execute(
        "SELECT id, context FROM entries WHERE actor='structures' AND kind='decision'"
        " ORDER BY time DESC LIMIT ?",
        (LIMIT,),
    ):
        try:
            d = json.loads(blob or "{}")
        except (ValueError, TypeError):
            continue
        if "level" in d and "macro_carry_gap_change" in d:
            calls[str(ref)] = d

    out = []
    for parent, blob in conn.execute(
        "SELECT parent, context FROM entries WHERE actor='structures' AND kind='outcome'"
        " AND parent IS NOT NULL ORDER BY time DESC LIMIT ?",
        (LIMIT,),
    ):
        call = calls.get(str(parent))
        if call is None:
            continue
        try:
            d = json.loads(blob or "{}")
        except (ValueError, TypeError):
            continue
        push, secs = d.get("push_vol"), d.get("seconds")
        if push is None or secs is None or float(secs) < 0:
            continue
        out.append(
            {
                "drift": float(call["macro_carry_gap_change"]),
                "said": str(call.get("direction") or ""),
                "up": float(push) > 0,
                "seconds": float(secs),
                "feed": str(call.get("feed") or ""),
            }
        )
    return out


def main() -> None:
    rows = joined()
    print(f"{len(rows)} level calls with a macro reading and a linked outcome\n")
    if not rows:
        print("nothing to join yet - the macro features are newer than the outcomes")
        return

    print(f"{'band':14s} {'agreeing':>22s} {'fighting':>22s}")
    for name, low, high in BANDS:
        cut = [r for r in rows if low <= r["seconds"] < high and r["said"] and r["drift"]]
        if len(cut) < 30:
            print(f"{name:14s} {len(cut):5d} calls - too few")
            continue
        groups = defaultdict(list)
        for r in cut:
            # The call says up or down; the macro drift favours the base leg
            # when positive. Agreeing means they point the same way.
            agrees = (r["said"] == "up") == (r["drift"] > 0)
            groups[agrees].append(r["up"] == (r["said"] == "up"))
        parts = []
        for agrees in (True, False):
            got = groups[agrees]
            parts.append(f"{sum(got) / len(got):6.1%} of {len(got):5d}" if got else "        none")
        print(f"{name:14s} {parts[0]:>22s} {parts[1]:>22s}")


if __name__ == "__main__":
    main()
