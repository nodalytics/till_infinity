"""Which way should a trade at a level go, and does anything actually know?

Six of the seven strategies take their side straight from the direction the
call carries:

    side = Side.from_direction(payload["direction"])

That is the half of the signal this repository has measured down to nothing,
three separate times. `edge.md` §1 found the direction a coin flip below the
edge step. `sweeps.py` records sweep direction at 50.7% over 73,000 ranges,
negative net of costs. And `reactions.MIN_EDGE` carries the flattest finding of
all: **"assume the level holds" still beats the published direction at every
gate except the highest, where they tie.**

Meanwhile the *location* half is strong - 49,338 resolutions, a two-fold spread
across instruments, real regime structure. So the architecture inherits the
weak half and re-derives nothing, and this asks what the alternatives would
have been worth.

## The circularity check comes first

A first pass at this reported that the approach side predicts the sign of the
push 92% of the time from above and 95% from below. Taken at face value that is
an extraordinary edge, and it contradicts every direction measurement above -
which is the reason to distrust it rather than publish it.

The suspicion is that `push_vol` is signed *by the outcome*, and the outcome is
mostly rejection: 34,123 of 49,338 touches reject, and a rejection from above
pushes up by construction. If so the 92% is a definition restated, not a
forecast, and a rule built on it would be trading an identity.

So step one decomposes the claim **within each outcome**. If approach side
still separates the push inside a fixed outcome, it is carrying information; if
it collapses to the same number everywhere, it was the outcome talking all
along and the whole exercise stops there.

## The rules

* `hold` - the level holds, so the side is away from the approach. This is the
  one the repository already measured as the best of the published set.
* `break` - the level fails, so the side continues through it. The complement,
  included because a rule and its opposite cannot both be uninformative.
* `momentum` - hard arrivals break, gentle ones bounce. `approach_vol` is how
  hard price came in and is on every resolution, so this is testable without
  new data. This is the rule the us30 trade argues for: the price was right and
  the side was wrong, and nothing in the current path could have said so.
* `coin` - the honest baseline. Any rule that cannot beat this is not a rule.
"""

import json
import sqlite3
import sys
from collections import defaultdict

#: Arrivals harder than this take the continuation side under `momentum`. The
#: median approach is near 1v, so this asks for a genuinely fast arrival rather
#: than an ordinary one.
HARD_ARRIVAL = 1.5


def load(db):
    con = sqlite3.connect(db)
    out = []
    q = "select context, tags from entries where actor='structures' and kind='outcome'"
    for ctx, tags in con.execute(q):
        d = json.loads(ctx or "{}")
        tg = json.loads(tags or "[]")
        push, side = d.get("push_vol"), d.get("side")
        if push is None or not side:
            continue
        out.append(
            {
                "push": float(push),
                "side": str(side),
                "outcome": str(d.get("outcome") or ""),
                "approach": float(d.get("approach_vol") or 0.0),
                "excursion": abs(float(d.get("excursion_vol") or 0.0)),
                "feed": (tg[0] if tg else ""),
                "regime": float(d.get("regime") or 0.0),
            }
        )
    return out


def circular(rows):
    """Does the approach side separate the push *within* one outcome?"""
    print("Is the approach side telling us anything the outcome has not already?")
    print(f"\n{'outcome':10s} {'from':6s} {'n':>7s} {'push up':>9s}")
    print("-" * 36)
    by = defaultdict(list)
    for r in rows:
        if r["push"]:
            by[(r["outcome"], r["side"])].append(r["push"])
    for outcome in ("reject", "trap", "break", "backcheck"):
        for side in ("above", "below"):
            v = by.get((outcome, side))
            if not v or len(v) < 100:
                continue
            up = sum(1 for p in v if p > 0) / len(v)
            print(f"{outcome:10s} {side:6s} {len(v):7,} {up:9.1%}")
    print(
        "\nIf the two rows of an outcome differ, the approach side carries\n"
        "information. If they agree, the earlier 92% was the outcome talking."
    )


def side_of(rule, r):
    """+1 for a long, -1 for a short, 0 to stand aside."""
    away = 1 if r["side"] == "above" else -1
    if rule == "hold":
        return away
    if rule == "break":
        return -away
    if rule == "momentum":
        return -away if r["approach"] >= HARD_ARRIVAL else away
    if rule == "coin":
        # Deterministic and arbitrary, which is what a baseline should be:
        # alternating by a property unrelated to the outcome.
        return 1 if len(r["feed"]) % 2 else -1
    return 0


def score(r, want, stop, target):
    if r["excursion"] >= stop:
        return -1.0
    if not r["push"]:
        return 0.0
    reached = abs(r["push"]) >= target and (1 if r["push"] > 0 else -1) == want
    return (target / stop) if reached else 0.0


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = load(db)
    print(f"{len(rows):,} resolutions\n")
    circular(rows)

    print(f"\n\nSide rules, stop 1.0v, target 1.5v ({len(rows):,} touches)")
    print(f"{'rule':10s} {'n':>7s} {'right':>8s} {'mean R':>9s}")
    print("-" * 37)
    for rule in ("hold", "break", "momentum", "coin"):
        taken = [(r, side_of(rule, r)) for r in rows]
        taken = [(r, w) for r, w in taken if w]
        right = sum(1 for r, w in taken if r["push"] and (1 if r["push"] > 0 else -1) == w)
        rs = [score(r, w, 1.0, 1.5) for r, w in taken]
        print(f"{rule:10s} {len(taken):7,} {right/len(taken):8.1%} {sum(rs)/len(rs):+9.3f}")

    print("\nmomentum, split by how hard price arrived:")
    print(f"{'arrival':14s} {'n':>7s} {'hold R':>9s} {'break R':>9s}")
    print("-" * 42)
    for low, high, name in ((0.0, 0.75, "gentle"), (0.75, 1.5, "ordinary"), (1.5, 99.0, "hard")):
        band = [r for r in rows if low <= r["approach"] < high]
        if len(band) < 200:
            continue
        h = [score(r, side_of("hold", r), 1.0, 1.5) for r in band]
        b = [score(r, side_of("break", r), 1.0, 1.5) for r in band]
        print(f"{name:14s} {len(band):7,} {sum(h)/len(h):+9.3f} {sum(b)/len(b):+9.3f}")


if __name__ == "__main__":
    main()
