"""Does a level sitting on an origin resolve better? Measured over the history.

Live, origin proximity is the strongest separation on the board - trades close
to an origin return -0.035R against -0.335R for those far from one - but on 42
trades, which is about one standard error. A conventional test of that gap
needs roughly 180 trades a side, and at the current rate that is weeks.

The resolutions do not need waiting for. Successive `level` prices on one feed
and interval trace where price has been, which is the same series
`research/harness/trend.py` uses, so the origin model can be run over the whole
history and each touch scored against the origins that existed **before** it.

**The scale is taken from the series itself** - the median absolute step
between consecutive levels - because `vol_bps` is written by trading and is not
on a structures outcome. That is the typical distance price moves between
touches on this feed and interval, which is the right denominator for "how far
is this level from that origin" and needs nothing external. Distances below are
in those units, not in the volatility units used elsewhere.

**Only prior levels count**, and that is the whole correctness of this: an
origin computed from a window containing the touch being judged describes the
touch rather than predicting it, which is the trap `push_vol` fell into and
that this file has fallen into twice.

Usage: python -m research.harness.origin_replay [journal.db]
"""

import json
import sqlite3
import sys
from collections import defaultdict, deque

from till_infinity.structures.origins import Origins

from .replay import score

#: How many prior levels the origin model is given.
WINDOW = 60
#: A touch within this many volatility units of an origin counts as near it.
NEAR_VOL = 0.5


def load(db):
    con = sqlite3.connect(db)
    q = (
        "select context from entries where actor='structures' "
        "and kind='outcome' order by time"
    )
    out = []
    for (ctx,) in con.execute(q):
        d = json.loads(ctx or "{}")
        push, excursion = d.get("push_vol"), d.get("excursion_vol")
        level, vol = d.get("level"), d.get("vol_bps")
        if None in (push, excursion, level):
            continue
        out.append(
            {
                "feed": d.get("feed") or "",
                "interval": d.get("interval") or "",
                "level": float(level),
                "push": float(push),
                "excursion": abs(float(excursion)),
                "vol_bps": float(vol) if isinstance(vol, int | float) else 0.0,
            }
        )
    return out


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = load(db)
    print(f"{len(rows):,} resolutions\n")

    history = defaultdict(lambda: deque(maxlen=WINDOW))
    judged = []
    for row in rows:
        key = (row["feed"], row["interval"])
        past = list(history[key])
        history[key].append(row["level"])  # after reading, never before
        if len(past) < 20:
            continue
        # The scale comes from the series, not from `vol_bps` - that field is
        # written by trading and is not on a structures outcome. The median
        # absolute step between consecutive levels is the typical distance
        # price moves between touches here, which is the right denominator for
        # "how far is this level from that origin" and needs nothing external.
        steps = sorted(abs(past[i + 1] - past[i]) for i in range(len(past) - 1))
        unit = steps[len(steps) // 2]
        if unit <= 0:
            continue
        found = Origins().observe(list(range(len(past))), past, unit)
        if not found:
            continue
        nearest = min(found, key=lambda o: abs(o.price - row["level"]))
        judged.append(
            {
                **row,
                "distance_vol": abs(nearest.price - row["level"]) / unit,
                "inside": any(o.holds(row["level"]) for o in found),
                "size_vol": nearest.size_vol,
                "revisits": nearest.revisits,
            }
        )

    print(f"{len(judged):,} of them had enough prior levels to judge\n")
    if len(judged) < 500:
        print("not enough to say anything")
        return

    def mean_r(rows_):
        return sum(score(r, 0.5, 0.75) for r in rows_) / len(rows_) if rows_ else 0.0

    near = [r for r in judged if r["distance_vol"] <= NEAR_VOL]
    far = [r for r in judged if r["distance_vol"] > NEAR_VOL]
    print(f"{'split':>34s} {'n':>8s} {'mean R':>8s}")
    print("-" * 54)
    label = f"within {NEAR_VOL}v of an origin"
    print(f"{label:>34s} {len(near):>8,} {mean_r(near):>8.3f}")
    print(f"{'further away':>34s} {len(far):>8,} {mean_r(far):>8.3f}")

    inside = [r for r in judged if r["inside"]]
    outside = [r for r in judged if not r["inside"]]
    if min(len(inside), len(outside)) > 100:
        print(f"{'inside an origin zone':>34s} {len(inside):>8,} {mean_r(inside):>8.3f}")
        print(f"{'outside every zone':>34s} {len(outside):>8,} {mean_r(outside):>8.3f}")

    print("\nby distance, in volatility units")
    ordered = sorted(judged, key=lambda r: r["distance_vol"])
    size = len(ordered) // 6
    for i in range(6):
        chunk = ordered[i * size : (i + 1) * size] if i < 5 else ordered[5 * size :]
        if chunk:
            print(f"  {chunk[0]['distance_vol']:>6.2f}-{chunk[-1]['distance_vol']:<7.2f} "
                  f"{len(chunk):>7,} {mean_r(chunk):>8.3f}")

    print("\nfreshness: an origin price has already worked through is a weaker claim")
    fresh = [r for r in judged if r["revisits"] == 0]
    worn = [r for r in judged if r["revisits"] >= 2]
    if min(len(fresh), len(worn)) > 100:
        print(f"  never revisited: {len(fresh):>7,} {mean_r(fresh):>8.3f}")
        print(f"  twice or more:   {len(worn):>7,} {mean_r(worn):>8.3f}")
if __name__ == "__main__":
    main()
