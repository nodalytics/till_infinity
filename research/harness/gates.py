"""Do the probability, base-rate and edge gates separate outcomes at all?

Each of them refuses trades, and each is defended by an argument rather than a
measurement. The question is not whether the numbers are meaningful - they are
model outputs and they mean something - but whether trades above the floor
actually do better than trades below it. A gate that does not separate is not
neutral: it costs every trade it refuses and returns nothing.

Reported as mean R under a stop-and-target rule, by decile of each gate's own
quantity, over every resolved touch in the journal. If a gate works, R should
climb across its deciles. If it is flat, the floor is refusing trades for a
number that does not predict.

Usage: python -m research.harness.gates [journal.db]
"""

import json
import sqlite3
import sys

from .replay import score


def load(db):
    con = sqlite3.connect(db)
    q = "select context from entries where actor='structures' and kind='outcome'"
    out = []
    for (ctx,) in con.execute(q):
        d = json.loads(ctx or "{}")
        if d.get("push_vol") is None or d.get("excursion_vol") is None:
            continue
        out.append(
            {
                "push": float(d["push_vol"]),
                "excursion": abs(float(d["excursion_vol"])),
                "probability": d.get("probability_up"),
                "base_rate": d.get("base_rate_up"),
                "edge": d.get("edge"),
            }
        )
    return out


def deciles(rows, key, stop=0.5, target=0.75, bands=10):
    """Mean R by decile of `key`, with the band edges printed."""
    got = [r for r in rows if r.get(key) is not None]
    if len(got) < bands * 20:
        return None
    got.sort(key=lambda r: float(r[key]))
    size = len(got) // bands
    out = []
    for i in range(bands):
        chunk = got[i * size : (i + 1) * size] if i < bands - 1 else got[(bands - 1) * size :]
        if not chunk:
            continue
        rs = [score(t, stop, target) for t in chunk]
        out.append(
            (
                float(chunk[0][key]),
                float(chunk[-1][key]),
                len(chunk),
                sum(rs) / len(rs),
            )
        )
    return out


def show(name, table):
    if table is None:
        print(f"\n{name}: not enough data")
        return
    print(f"\n{name}: mean R by decile (0.5v stop, 0.75v target)")
    print(f"{'from':>10s} {'to':>10s} {'n':>7s} {'R':>8s}")
    print("-" * 39)
    for lo, hi, n, r in table:
        print(f"{lo:>10.4f} {hi:>10.4f} {n:>7,} {r:>8.3f}")
    spread = max(r for *_, r in table) - min(r for *_, r in table)
    first, last = table[0][3], table[-1][3]
    print(f"  spread across deciles {spread:.3f}, bottom {first:.3f} -> top {last:.3f}")


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = load(db)
    print(f"{len(rows):,} resolved touches")
    print("\nA gate that works climbs across its deciles. A flat column is a")
    print("floor refusing trades for a number that does not predict.")
    for name in ("probability", "base_rate", "edge"):
        show(name, deciles(rows, name))


if __name__ == "__main__":
    main()
