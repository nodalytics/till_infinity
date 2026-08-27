"""What the replay says about the stop and target we actually place.

Every positive number in this file's other harnesses was measured at a **0.5v
stop and 0.75v target**. Production places a median **1.05v stop and 2.53v
target**. Those are not the same trade, and quoting the first as evidence for
the second is the mistake this script exists to stop.

Scored over resolved touches: mean R, win share, and the total R a policy of
taking every call would return, across a grid of stop and target in volatility
units. The live pair is marked.

Usage: python -m research.harness.settings_grid [journal.db]
"""

import sys

from .replay import load

#: What production actually places, from 57 live decisions.
LIVE_STOP, LIVE_TARGET = 1.05, 2.53

STOPS = (0.5, 0.75, 1.0, 1.05, 1.5, 2.0, 3.0)
TARGETS = (0.75, 1.5, 2.0, 2.53, 3.5, 5.0)


def score(touch, stop, target):
    """R for one touch. The stop wins ties - it is checked first."""
    if touch["excursion"] >= stop:
        return -1.0
    return (target / stop) if abs(touch["push"]) >= target else 0.0


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = load(db)
    print(f"{len(rows):,} resolved touches\n")
    print("mean R by stop and target, in volatility units")
    print(f"{'stop':>6s} " + " ".join(f"{t:>9.2f}v" for t in TARGETS))
    print("-" * (7 + 10 * len(TARGETS)))
    for stop in STOPS:
        cells = []
        for target in TARGETS:
            rs = [score(t, stop, target) for t in rows]
            mark = "*" if (stop == LIVE_STOP and target == LIVE_TARGET) else " "
            cells.append(f"{sum(rs) / len(rs):>9.3f}{mark}")
        print(f"{stop:>5.2f}v " + " ".join(cells))
    print("\n* is what production places (median stop 1.05v, target 2.53v)")

    live = [score(t, LIVE_STOP, LIVE_TARGET) for t in rows]
    tight = [score(t, 0.5, 0.75) for t in rows]
    print(f"\n  at the live pair:      {sum(live) / len(live):+.3f}R per touch")
    print(f"  at the quoted pair:    {sum(tight) / len(tight):+.3f}R per touch")
    won = sum(1 for r in live if r > 0) / len(live)
    print(f"\n  win share at the live pair: {won:.1%}")
    print("  a wider stop is hit less often, and pays a target it reaches less often")


if __name__ == "__main__":
    main()
