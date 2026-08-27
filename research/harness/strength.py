"""Does `strength` predict anything, and should it gate a trade?

It reaches the Telegram alerts and it is on every recorded touch, which makes
it look like a decision input. It is not one: the gate chain in
`LevelStrategy.quality` runs probability, then edge, then base rate, and never
reads it. Its only route into a trade is as one of the features `facto` learns
from, diluted with everything else there.

That is either a gap or a correct omission, and the resolutions can say which.
This buckets resolved touches by strength and asks whether the higher buckets
actually resolve better - both on raw direction and on the R a stop-and-target
rule would have taken - and then asks the harder question: whether strength
still separates *after* probability has had its say. A feature that only looks
predictive because it correlates with one already in the gate chain adds a
refusal without adding information.

Usage: python -m research.harness.strength [journal.db]
"""

import json
import sqlite3
import sys
from collections import defaultdict

from .replay import score

#: Cut points in strength. Read off the observed distribution rather than
#: chosen for roundness - see the quantiles the script prints first.
CUTS = (0.2, 0.4, 0.6, 0.8)


def bucket(value, cuts=CUTS):
    for i, c in enumerate(cuts):
        if value < c:
            return i
    return len(cuts)


def label(i, cuts=CUTS):
    lo = "0.00" if i == 0 else f"{cuts[i - 1]:.2f}"
    hi = "1.00+" if i == len(cuts) else f"{cuts[i]:.2f}"
    return f"{lo}-{hi}"


def quantiles(values, points=(0.1, 0.25, 0.5, 0.75, 0.9, 0.99)):
    ordered = sorted(values)
    if not ordered:
        return {}
    return {p: ordered[min(len(ordered) - 1, int(p * len(ordered)))] for p in points}


def rows_with_probability(db):
    """Every resolved touch with its probability, read in one pass.

    Deliberately not two queries zipped together. `replay.load` and a second
    scan would only line up if SQLite returned identical row order both times
    and both filtered identically - true in practice, unguaranteed in fact, and
    a silent misalignment would attach each probability to the wrong touch and
    invent exactly the kind of relationship this script exists to test for.
    """
    con = sqlite3.connect(db)
    q = "select context from entries where actor='structures' and kind='outcome'"
    out = []
    for (ctx,) in con.execute(q):
        d = json.loads(ctx or "{}")
        push, excursion = d.get("push_vol"), d.get("excursion_vol")
        if push is None or excursion is None:
            continue
        out.append(
            {
                "push": float(push),
                "excursion": abs(float(excursion)),
                "strength": float(d.get("strength") or 0.0),
                "probability_up": d.get("probability_up"),
                "outcome": d.get("outcome") or "",
            }
        )
    return out


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = rows_with_probability(db)
    print(f"{len(rows):,} resolved touches\n")

    qs = quantiles([r["strength"] for r in rows])
    print("strength distribution")
    print("  " + "  ".join(f"p{int(p * 100)}={v:.3f}" for p, v in qs.items()))
    zero = sum(1 for r in rows if r["strength"] == 0.0)
    print(f"  exactly zero: {zero:,} ({zero / len(rows):.1%})\n")

    # Raw separation: does a higher strength resolve in the pushed direction
    # more often, and carry a bigger push when it does.
    by = defaultdict(list)
    for r in rows:
        by[bucket(r["strength"])].append(r)
    print("by strength bucket")
    print(f"{'bucket':>10s} {'n':>8s} {'push |v|':>9s} {'R @1.0/1.5':>11s} {'R @0.5/1.5':>11s}")
    print("-" * 54)
    for i in sorted(by):
        got = by[i]
        push = sum(abs(t["push"]) for t in got) / len(got)
        r10 = sum(score(t, 1.0, 1.5) for t in got) / len(got)
        r05 = sum(score(t, 0.5, 0.75) for t in got) / len(got)
        print(f"{label(i):>10s} {len(got):>8,} {push:>9.2f} {r10:>11.3f} {r05:>11.3f}")

    # The harder question. Inside a single probability band, does strength
    # still separate? If it does not, it is already priced.
    print("\nR @0.5 stop, within probability bands")
    bands = ((0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01))
    print(f"{'probability':>12s} " + " ".join(f"{label(i):>11s}" for i in range(len(CUTS) + 1)))
    print("-" * (13 + 12 * (len(CUTS) + 1)))
    for lo, hi in bands:
        cells = []
        for i in range(len(CUTS) + 1):
            got = [
                t
                for t in rows
                if t.get("probability_up") is not None
                and lo <= float(t["probability_up"]) < hi
                and bucket(t["strength"]) == i
            ]
            if len(got) < 30:
                cells.append(f"{'-':>11s}")
                continue
            cells.append(f"{sum(score(t, 0.5, 0.75) for t in got) / len(got):>11.3f}")
        print(f"{lo:.2f}-{hi:<7.2f} " + " ".join(cells))


if __name__ == "__main__":
    main()
