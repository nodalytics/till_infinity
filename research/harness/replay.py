"""What would each stop and target rule have made, over every recorded touch?

Sixteen live trades across four strategies is about four labels each, which is
not enough to say anything about any of them - let alone enough to fit a rule
that picks a strategy for a regime. But a level strategy is a **deterministic
function** of the call plus a stop and a target, and every resolution already
records what happened afterwards. So the labels can be manufactured: replay the
rules over the touches that have already resolved and the sample goes from
seventeen to tens of thousands without trading anything.

## The geometry, and the one honest compromise in it

Each resolution carries two numbers that decide a stop-and-target trade:

* `excursion_vol` - the furthest price got **through** the level, which is the
  adverse direction for anything trading the level to hold;
* `push_vol` - the resolved push, signed, positive up.

A trade entered at the level in direction `d`, with a stop `S` volatility units
through it and a target `T` units along it, therefore:

* is **stopped** when `excursion_vol >= S`;
* **reaches its target** when `push_vol` points along `d` and `|push_vol| >= T`.

**Both can be true, and the record cannot say which came first.** That is the
compromise, and it is resolved against the trade: if the stop was reached at
all it counts as a stop. That biases every number here *downward*, which is the
direction an honest bias should point when the alternative is flattering a rule
you are about to trade.

## What it cannot answer

Spread and slippage are not on a resolution, so this scores the thesis rather
than the execution - and the live trades say execution is where a good deal of
the loss lives. `approach-scalp` needs the next level in the book and
`fade-to-value` needs the valuation, neither of which is recorded, so only the
level-holding family replays. What comes out is therefore an upper bound on the
family, by regime, and is useful for **comparing rules against each other**
rather than for predicting a return.
"""

import json
import sqlite3
import sys
from collections import defaultdict

#: Stop widths to compare, in volatility units. 1.0 is what production ran for
#: most of its life; 3.0 is the cap the hold scaling now reaches.
STOPS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)

#: Regime buckets. `regime` is where current volatility sits in its own recent
#: history, so these are "unusually quiet" through "unusually busy" for that
#: instrument rather than absolute levels.
BUCKETS = ((0.0, 0.25, "quiet"), (0.25, 0.5, "normal"), (0.5, 0.75, "busy"), (0.75, 1.01, "wild"))


def bucket_of(regime):
    for low, high, name in BUCKETS:
        if low <= regime < high:
            return name
    return "wild"


def load(db):
    """Every resolved touch, reduced to what a stop-and-target rule needs."""
    con = sqlite3.connect(db)
    out = []
    q = "select context from entries where actor='structures' and kind='outcome'"
    for (ctx,) in con.execute(q):
        d = json.loads(ctx or "{}")
        push, excursion = d.get("push_vol"), d.get("excursion_vol")
        if push is None or excursion is None:
            continue
        out.append(
            {
                "push": float(push),
                "excursion": abs(float(excursion)),
                "regime": float(d.get("regime") or 0.0),
                "interval": d.get("interval") or "",
                "feed": d.get("feed") or "",
                "outcome": d.get("outcome") or "",
                "edge": d.get("edge"),
                "actionable": d.get("actionable"),
                "strength": float(d.get("strength") or 0.0),
                "experience": float(d.get("experience") or 0.0),
            }
        )
    return out


def score(touch, stop, target):
    """R for one touch under one rule. Stop wins ties - see the module note."""
    if touch["excursion"] >= stop:
        return -1.0
    reached = abs(touch["push"]) >= target and touch["push"] != 0
    return (target / stop) if reached else 0.0


def table(rows, stop, target_mult):
    """Mean R by regime, for one stop width."""
    by = defaultdict(list)
    for t in rows:
        by[bucket_of(t["regime"])].append(score(t, stop, stop * target_mult))
    return {k: (len(v), sum(v) / len(v)) for k, v in by.items() if v}


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = load(db)
    print(f"{len(rows):,} resolved touches\n")

    # Held fixed at 1.5 so the stop is the only thing varying; the target moves
    # with it because a rule that widens the stop and not the target is a
    # different rule, not a wider version of the same one.
    mult = 1.5
    names = [b[2] for b in BUCKETS]
    print(f"mean R by regime, target = {mult:g}x the stop")
    print(f"{'stop':>5s} " + " ".join(f"{n:>14s}" for n in names) + f" {'all':>9s}")
    print("-" * (6 + 15 * len(names) + 10))
    for stop in STOPS:
        got = table(rows, stop, mult)
        cells = []
        for n in names:
            if n in got:
                count, mean = got[n]
                cells.append(f"{mean:+7.3f} ({count // 1000:2d}k)")
            else:
                cells.append(f"{'-':>14s}")
        every = [score(t, stop, stop * mult) for t in rows]
        print(f"{stop:5.1f} " + " ".join(f"{c:>14s}" for c in cells) + f" {sum(every)/len(every):+9.3f}")

    # The question the edge recording was added for. Only meaningful once
    # touches recorded after that change have resolved.
    scored = [t for t in rows if t["edge"] is not None and t["edge"] != 0.0]
    print(f"\ntouches carrying an edge: {len(scored):,}")
    if len(scored) >= 200:
        print(f"{'|edge|':>10s} {'n':>7s} {'mean R':>9s}  (stop 2.0, target 3.0)")
        print("-" * 42)
        bands = ((0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.25), (0.25, 1.0))
        for low, high in bands:
            band = [t for t in scored if low <= abs(t["edge"]) < high]
            if len(band) < 30:
                continue
            r = [score(t, 2.0, 3.0) for t in band]
            print(f"{low:.2f}-{high:.2f} {len(band):7,} {sum(r)/len(r):+9.3f}")
    else:
        print("  too few to band - the edge is recorded from 2026-08-27 only.")


if __name__ == "__main__":
    main()
