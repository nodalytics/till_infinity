"""Pullback inside a trend, or a level inside a range - does it change the bet?

`regime.py` asked whether momentum *into* a level says the level will fail, and
found the opposite: a harder approach rejects more often, and the money does
not move either way. But that measure is taken at the level, over the approach
itself, and it cannot see the thing the question was really about - whether the
market is trending through this area or oscillating inside it.

`regime` in the journal is no help: it is where **volatility** sits in its own
recent history, not direction.

So this builds the missing measure from what is recorded. Each resolution
carries the `level` it happened at, and successive levels on one feed trace
where price has been. Over a window of them:

    efficiency = |net displacement| / sum of absolute steps

One means every step went the same way - a trend. Zero means the steps
cancelled - a range. It is the standard efficiency ratio, and it is the
longer-horizon momentum the todo lists as missing.

**The look-back is strictly prior.** Only resolutions before the one being
classified count, which is what keeps this a prediction rather than a
restatement - the trap `push_vol` fell into, where a quantity signed by the
outcome was tested against the outcome.

**What would make the proposal true**: breaks rising with efficiency, because a
level standing in the way of a trend should give way more often than one being
tested inside a range.

Usage: python -m research.harness.trend [journal.db]
"""

import json
import sqlite3
import sys
from collections import Counter, defaultdict, deque

#: How many prior resolutions on the same feed define the context.
WINDOW = 12


def load(db):
    con = sqlite3.connect(db)
    q = "select context from entries where actor='structures' and kind='outcome' order by rowid"
    out = []
    for (ctx,) in con.execute(q):
        d = json.loads(ctx or "{}")
        if d.get("level") is None or d.get("push_vol") is None:
            continue
        if d.get("excursion_vol") is None:
            continue
        out.append(
            {
                "feed": d.get("feed") or "",
                "interval": d.get("interval") or "",
                "level": float(d["level"]),
                "push": float(d["push_vol"]),
                "excursion": abs(float(d["excursion_vol"])),
                "outcome": d.get("outcome") or "",
            }
        )
    return out


def efficiency(levels):
    """|net| / sum|steps| over a sequence of prices. 1 trends, 0 ranges."""
    if len(levels) < 3:
        return None
    steps = [levels[i + 1] - levels[i] for i in range(len(levels) - 1)]
    travelled = sum(abs(s) for s in steps)
    if travelled <= 0:
        return None
    return abs(sum(steps)) / travelled


def classify(rows, window=WINDOW):
    """Attach each resolution's prior-only trend context."""
    seen = defaultdict(lambda: deque(maxlen=window))
    out = []
    for row in rows:
        key = (row["feed"], row["interval"])
        history = seen[key]
        ratio = efficiency(list(history))
        if ratio is not None:
            out.append({**row, "efficiency": ratio})
        history.append(row["level"])
    return out


def r_of(touch, stop, target):
    if touch["excursion"] >= stop:
        return -1.0
    return (target / stop) if abs(touch["push"]) >= target else 0.0


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = classify(load(db))
    print(f"{len(rows):,} resolutions with {WINDOW} prior levels on their own feed\n")
    if len(rows) < 1000:
        print("not enough to say anything")
        return

    rows.sort(key=lambda r: r["efficiency"])
    bands, size = 10, len(rows) // 10
    print("trending vs ranging, against what happened at the level")
    print(f"{'efficiency':>14s} {'n':>7s} {'break':>7s} {'R with':>9s}")
    print("-" * 44)
    for i in range(bands):
        chunk = rows[i * size : (i + 1) * size] if i < bands - 1 else rows[(bands - 1) * size :]
        if not chunk:
            continue
        kinds = Counter(t["outcome"] for t in chunk)
        decided = kinds["reject"] + kinds["break"]
        share = kinds["break"] / decided if decided else 0.0
        with_level = sum(r_of(t, 0.5, 0.75) for t in chunk) / len(chunk)
        lo, hi = chunk[0]["efficiency"], chunk[-1]["efficiency"]
        print(f"{lo:>6.3f}-{hi:<7.3f} {len(chunk):>7,} {share:>6.1%} {with_level:>9.3f}")

    print("\n0 ranges, 1 trends. If a trend runs levels over, break share")
    print("should climb and the with-the-level trade should get worse.")


if __name__ == "__main__":
    main()
