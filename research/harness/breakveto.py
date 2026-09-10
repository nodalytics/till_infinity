"""Is `break_risk` an independent reading, or should it veto the call?

A v100(1s) alert fired on 2026-09-05 at 840.32 reading **down 84% against a
63% base rate** and, three lines lower, **break risk 91%**. It resolved as a
`trap` within three hours, the engine flipped to `up` at the same level, and
price spent 80% of the next five days above it.

Two numbers that both sound like confidence, pointing opposite ways, in the
same alert. Either they measure genuinely different things - the direction of
the next push, and whether the level survives at all - or one of them should
have stopped the other from being published.

The question is answerable from the record because both are stamped on every
call and the outcome arrives attached to its parent. Three things get measured:

* **Calibration.** When `break_risk` says 90%, does the level break 90% of the
  time? An uncalibrated risk is not a veto candidate, it is a number.
* **Does it predict the break?** Held rate bucketed by `break_risk`. Flat means
  it knows nothing, whatever it is named.
* **Does it predict the *call* failing?** A level can break and the directional
  call still pay - a `down` call wants the level to give way. So the two are
  only in conflict where the call is *against* the break.

`reject` is the level holding and `break` is it giving way; everything else is
not decisive and is dropped, which is the same filter `regime.py` uses.
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics as st
import time
from collections import Counter, defaultdict

DB = os.environ.get("LEVELWATCH_DB", "/app/.data/journal/journal.db")
DAYS = float(os.environ.get("DAYS", "5"))
SCAN = int(os.environ.get("SCAN", "600000"))


def bucket(value: float, edges: list[float]) -> int:
    for i, edge in enumerate(edges):
        if value < edge:
            return i
    return len(edges)


def run() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=300.0)
    since = time.time() - DAYS * 86400

    decisions: dict[str, dict] = {}
    for entry_id, ctx in conn.execute(
        "SELECT id, context FROM entries WHERE actor='structures' AND kind='decision' "
        "AND time>=? LIMIT ?",
        (since, SCAN),
    ):
        try:
            got = json.loads(ctx or "{}")
        except Exception:
            continue
        if isinstance(got.get("break_risk"), int | float):
            decisions[str(entry_id)] = got

    rows = []
    for parent, ctx in conn.execute(
        "SELECT parent, context FROM entries WHERE actor='structures' AND kind='outcome' "
        "AND time>=? AND parent IS NOT NULL LIMIT ?",
        (since, SCAN),
    ):
        try:
            got = json.loads(ctx or "{}")
        except Exception:
            continue
        outcome = str(got.get("outcome") or "")
        if outcome not in ("reject", "break"):
            continue
        made = decisions.get(str(parent))
        if made is None:
            continue
        rows.append((float(made["break_risk"]), made, outcome == "reject"))

    print(f"{len(rows):,} decisive touches carrying break_risk, {DAYS:g} days\n")
    if len(rows) < 200:
        print("not enough to report")
        return

    risks = [r[0] for r in rows]
    edges = [st.quantiles(risks, n=5)[i] for i in range(4)]
    book = defaultdict(list)
    for risk, _, held in rows:
        book[bucket(risk, edges)].append(1 if held else 0)
    print("held rate by break_risk (higher risk should mean lower held rate):")
    print(f"  edges {[round(e, 3) for e in edges]}")
    for k in sorted(book):
        got = book[k]
        lo = "-inf" if k == 0 else f"{edges[k - 1]:.3f}"
        hi = "+inf" if k == len(edges) else f"{edges[k]:.3f}"
        print(f"    {lo:>7s} .. {hi:<7s} {len(got):6d}  held {st.fmean(got):6.1%}")

    print("\ncalibration - break_risk against the break rate it implies:")
    cal = defaultdict(list)
    for risk, _, held in rows:
        cal[round(risk * 10) / 10].append(0 if held else 1)
    for band in sorted(cal):
        got = cal[band]
        if len(got) < 50:
            continue
        print(f"    says {band:.0%}  ->  broke {st.fmean(got):6.1%}   ({len(got)} touches)")

    # The conflict case: a call whose direction needs the level to hold, made
    # while break_risk was high. That is where a veto would have bitten.
    print("\nwhere the two disagree - high break_risk with a call needing the hold:")
    conflict = [
        (risk, made, held)
        for risk, made, held in rows
        if risk >= 0.8 and str(made.get("direction") or "")
    ]
    if not conflict:
        print("    none")
    else:
        by_dir = Counter()
        held_by_dir = defaultdict(list)
        for risk, made, held in conflict:
            d = str(made.get("direction"))
            by_dir[d] += 1
            held_by_dir[d].append(1 if held else 0)
        for d, n in by_dir.most_common():
            print(f"    break_risk>=0.80, direction {d:5s}: {n:5d} touches, "
                  f"held {st.fmean(held_by_dir[d]):6.1%}")
        low = [(r, m, h) for r, m, h in rows if r < 0.5 and str(m.get("direction") or "")]
        if low:
            print(f"    for contrast, break_risk<0.50: {len(low):5d} touches, "
                  f"held {st.fmean([1 if h else 0 for _, _, h in low]):6.1%}")


if __name__ == "__main__":
    run()
