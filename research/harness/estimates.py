"""Do the estimators predict what the trades actually did?

Everything built on 2026-08-27 records rather than decides: each decision
carries what the hold, reach, trend and origin models thought, and none of
them sizes or gates on it. This is the check that has to pass before any of
them is allowed to.

The question is not whether an estimate is *reasonable* - they all are - but
whether it separates outcomes. For each, trades are split at the median of the
estimate and the two halves compared on realised R. A separation of nothing is
the answer for most features most of the time, and saying so is the point.

**R is profit over the money the trade was sized to risk**, not over the stop
distance, because that is what the account actually experienced.

Usage: python -m research.harness.estimates [journal.db]
"""

import json
import sqlite3
import sys

#: Fewest trades on each side of a split before it is worth printing.
FEWEST = 8

FEATURES = (
    ("expected_hold_s", "how long a touch here usually takes"),
    ("efficiency", "trending vs ranging around the level"),
    ("pressure_vol", "momentum running into the trade"),
    ("origin_distance_vol", "distance to the nearest origin"),
    ("origin_size_vol", "size of the move that origin launched"),
    ("in_origin", "the level sits inside an origin zone"),
    ("reach_depth_vol", "how far price usually penetrates here"),
    ("reach_stop_vol", "how far a stop must clear here"),
    ("strength", "the level's own strength"),
    ("probability", "the model's confidence"),
)


def load(db):
    con = sqlite3.connect(db)
    q = "select context from entries where actor='trading' and kind='outcome'"
    out = []
    for (ctx,) in con.execute(q):
        d = json.loads(ctx or "{}")
        risk, profit = d.get("risk_money"), d.get("profit")
        if not risk or profit is None:
            continue
        d["_r"] = float(profit) / float(risk)
        out.append(d)
    return out


def split(rows, name):
    """Mean R either side of the median of `name`, or None."""
    got = [r for r in rows if isinstance(r.get(name), int | float)]
    if len(got) < FEWEST * 2:
        return None
    got.sort(key=lambda r: float(r[name]))
    half = len(got) // 2
    low, high = got[:half], got[half:]
    if min(len(low), len(high)) < FEWEST:
        return None
    return (
        len(got),
        float(got[half][name]),
        sum(r["_r"] for r in low) / len(low),
        sum(r["_r"] for r in high) / len(high),
    )


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = load(db)
    print(f"{len(rows)} closed trades with a risk figure\n")
    if rows:
        every = sum(r["_r"] for r in rows) / len(rows)
        print(f"mean R across all of them: {every:+.3f}\n")

    header = f"{'feature':>22s} {'n':>4s} {'split at':>10s} {'R below':>9s}"
    print(header + f" {'R above':>9s} {'gap':>7s}")
    print("-" * 68)
    for name, _note in FEATURES:
        got = split(rows, name)
        if got is None:
            print(f"{name:>22s}    -          -         -         -        not enough yet")
            continue
        n, at, low, high = got
        print(f"{name:>22s} {n:>4d} {at:>10.3f} {low:>9.3f} {high:>9.3f} {high - low:>+7.3f}")

    print("\nA gap near zero is the honest answer for most of these, and the")
    print("reason to record before wiring. Nothing here is significant at these")
    print("counts - this says which are worth watching, not which are true.")


if __name__ == "__main__":
    main()
