"""Can momentum say which of the two directional bets to take?

Every scalping strategy here is one of two wagers. `level-scalp` and its
refinements bet the level **holds** - price turned up to it and will turn away.
`inverse` bets it **fails**. They are the same call read two ways, and nothing
so far chooses between them; `inverse` runs as a control precisely because the
choice was never made on evidence.

The proposal under test: momentum makes that choice. Price drifting into a
level is a level being tested and likely to hold; price *running* into one is a
move in progress and more likely to go through. If that is true, momentum is
not only a timing filter - it is a regime classifier, and the strategy to use
is a function of it.

`approach_vol` is the recorded proxy: how far price ran on its way into the
level, in volatility units. This asks whether it separates the outcome classes,
and whether it separates the R a trade would have taken on each side of the
bet.

**What would make the proposal true**: breaks rising with approach, and the
against-the-level trade beating the with-the-level trade in the top deciles.
Anything less and momentum is a filter, not a classifier.

Usage: python -m research.harness.regime [journal.db]
"""

import json
import sqlite3
import sys
from collections import Counter

#: Outcomes where the level did not hold. `trap` is deliberately excluded from
#: both sides: price went through and came back, which is the level holding
#: *after* failing, and is the one class where "which bet won" depends entirely
#: on where the stop was.
BROKE = ("break",)
HELD = ("reject",)


def load(db):
    con = sqlite3.connect(db)
    q = "select context from entries where actor='structures' and kind='outcome'"
    out = []
    for (ctx,) in con.execute(q):
        d = json.loads(ctx or "{}")
        if d.get("approach_vol") is None or d.get("push_vol") is None:
            continue
        if d.get("excursion_vol") is None:
            continue
        out.append(
            {
                "approach": abs(float(d["approach_vol"])),
                "push": float(d["push_vol"]),
                "excursion": abs(float(d["excursion_vol"])),
                "outcome": d.get("outcome") or "",
            }
        )
    return out


def r_of(touch, stop, target):
    """R for the with-the-level trade. Stop wins ties."""
    if touch["excursion"] >= stop:
        return -1.0
    return (target / stop) if abs(touch["push"]) >= target else 0.0


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = load(db)
    print(f"{len(rows):,} resolutions carrying an approach\n")
    if len(rows) < 500:
        print("not enough to say anything")
        return

    rows.sort(key=lambda r: r["approach"])
    bands, size = 10, len(rows) // 10
    print("momentum into the level, against what happened there")
    print(f"{'approach v':>14s} {'n':>7s} {'held':>7s} {'broke':>7s} {'R with':>8s}")
    print("-" * 50)
    for i in range(bands):
        chunk = rows[i * size : (i + 1) * size] if i < bands - 1 else rows[(bands - 1) * size :]
        if not chunk:
            continue
        kinds = Counter(t["outcome"] for t in chunk)
        held = sum(kinds[k] for k in HELD)
        broke = sum(kinds[k] for k in BROKE)
        decided = held + broke
        share = broke / decided if decided else 0.0
        with_level = sum(r_of(t, 0.5, 0.75) for t in chunk) / len(chunk)
        lo, hi = chunk[0]["approach"], chunk[-1]["approach"]
        print(
            f"{lo:>6.2f}-{hi:<7.2f} {len(chunk):>7,} {held:>7,} {broke:>7,} "
            f"{with_level:>8.3f}   break {share:>5.1%}"
        )

    print("\nIf momentum classified the regime, break share would climb with")
    print("approach and the with-the-level R would fall as it did.")


if __name__ == "__main__":
    main()
