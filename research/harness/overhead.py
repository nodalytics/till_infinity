"""Does a sell do worse when unfilled interest sits above it?

The observation: a Volatility 10 sell whose *side* was right but whose entry
was early, because there was still an imbalance above that price would likely
revisit first.

The system already computes that object. An **origin** is where a violent move
began, so an origin above price is selling interest that was placed and not
filled - and `origin_above_low` and `origin_above_vol` are on every call.

So the question is directly answerable: conditioned on a touch, does the
outcome differ with how far the nearest origin sits above?

Two readings are possible and they point opposite ways, which is why this is
worth measuring rather than reasoning about:

* **Resistance.** Unfilled selling above caps a rally, so a sell into it is
  *safer* - the level has help.
* **A magnet.** Unfilled interest is somewhere price wants to go, so a sell
  placed under one is early and gets run over on the way up.
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics as st
import time

DB = "/app/.data/journal/journal.db"
DAYS = float(os.environ.get("DAYS", "7"))


def run():
    now = time.time()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=180.0)
    since = now - DAYS * 86400

    decisions: dict[str, dict] = {}
    keys = set()
    for entry_id, ctx in conn.execute(
        "SELECT id, context FROM entries WHERE actor='structures' AND kind='decision' AND time>=?",
        (since,),
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if isinstance(d, dict):
            decisions[str(entry_id)] = d
            keys.update(k for k in d if "origin" in k)
    print("origin fields seen on decisions:", ", ".join(sorted(keys)) or "(none)")

    rows = []
    for parent, ctx in conn.execute(
        "SELECT parent, context FROM entries WHERE actor='structures' AND kind='outcome' "
        "AND time>=? AND parent IS NOT NULL",
        (since,),
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if not isinstance(d, dict) or str(d.get("outcome")) not in ("reject", "break"):
            continue
        parent_ctx = decisions.get(str(parent))
        if parent_ctx is None:
            continue
        rows.append((parent_ctx, d))
    print(f"{len(rows)} decisive touches joined to their decision\n")

    def report(name, subset, field):
        vals = [
            (float(p[field]), str(o.get("outcome")) == "reject")
            for p, o in subset
            if isinstance(p.get(field), (int, float))
        ]
        if len(vals) < 200:
            print(f"  {name}: only {len(vals)} carry {field}")
            return
        edges = st.quantiles([v for v, _ in vals], n=5)
        book: dict[int, list] = {}
        for value, held in vals:
            slot = sum(1 for e in edges if value >= e)
            book.setdefault(slot, []).append(1 if held else 0)
        print(f"  {name}  ({len(vals)} touches, by {field})")
        for k in sorted(book):
            v = book[k]
            lo = "0" if k == 0 else f"{edges[k - 1]:.2f}"
            hi = "inf" if k == len(edges) else f"{edges[k]:.2f}"
            print(f"    {lo:>6s} .. {hi:<6s}v  {len(v):5d}  held {st.fmean(v):6.1%}")

    for direction, label in (("down", "sells (down calls)"), ("up", "buys (up calls)")):
        subset = [(p, o) for p, o in rows if str(p.get("direction")) == direction]
        print(f"=== {label}: {len(subset)} touches ===")
        report("distance to the origin ABOVE", subset, "origin_above_vol")
        report("distance to the origin BELOW", subset, "origin_below_vol")
        print()

    # And whether price is standing inside an origin at all.
    print("=== inside an origin, by direction ===")
    for direction, label in (("down", "sells"), ("up", "buys")):
        subset = [(p, o) for p, o in rows if str(p.get("direction")) == direction]
        book: dict[str, list] = {}
        for p, o in subset:
            flag = p.get("in_origin")
            if not isinstance(flag, (int, float)):
                continue
            book.setdefault("inside" if flag else "outside", []).append(
                1 if str(o.get("outcome")) == "reject" else 0
            )
        line = "  ".join(f"{k}: {st.fmean(v):.1%} ({len(v)})" for k, v in sorted(book.items()))
        print(f"  {label:8s} {line}")


if __name__ == "__main__":
    run()
