"""Entering deeper than the level: better R when filled, filled less often.

The stop sits beyond the level and the entry sits at it, so the distance
between them is the risk. Moving the entry *toward* the stop shrinks that risk
on the same thesis - which is what entering at the origin zone rather than at
the level would do.

It is fully measurable from what the journal holds, because a deeper entry
changes three things and each is a function of push and excursion:

* **the fill** - price must actually reach the deeper price, so the trade only
  happens when `excursion >= depth`;
* **the risk** - the stop does not move, so risk falls from `stop` to
  `stop - depth`;
* **the reward** - the target does not move either, so the run from entry to
  target grows from `push` to `push + depth`.

The stop-out condition is unchanged: the stop is at the same *price*, so it is
hit when `excursion >= stop` whatever the entry was.

**Unfilled signals score zero, not nothing.** A deeper entry that never fills
is a trade not taken, and a comparison that quietly drops those measures the
fills it happened to get rather than the rule. That is the mistake that makes
every "wait for a better price" rule look free.

Usage: python -m research.harness.deeper [journal.db]
"""

import sys

from .replay import load

#: How far past the level to enter, in volatility units.
DEPTHS = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)
#: Where the stop sits beyond the level.
STOP = 1.0
#: Where the target sits beyond the level.
TARGET = 1.5


def outcome(touch, depth, stop=STOP, target=TARGET):
    """R for one touch entered `depth` beyond the level, or None if unfilled."""
    excursion, push = touch["excursion"], abs(touch["push"])
    if excursion < depth:
        return None  # price never came that deep
    risk = stop - depth
    if risk <= 0:
        return None  # the entry has passed the stop
    if excursion >= stop:
        return -1.0  # stopped, and the stop did not move
    return (target + depth) / risk if push >= target else 0.0


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = load(db)
    print(f"{len(rows):,} resolved touches")
    print(f"stop {STOP}v beyond the level, target {TARGET}v, entry moved toward the stop\n")

    print(f"{'entry depth':>12s} {'filled':>8s} {'fill rate':>10s} "
          f"{'R per fill':>11s} {'R per signal':>13s}")
    print("-" * 60)
    for depth in DEPTHS:
        scored = [outcome(t, depth) for t in rows]
        filled = [r for r in scored if r is not None]
        if not filled:
            continue
        per_fill = sum(filled) / len(filled)
        # Every signal counts. An unfilled one earns nothing, which is the
        # cost of waiting and the thing a fills-only comparison hides.
        per_signal = sum(filled) / len(scored)
        print(f"{depth:>11.2f}v {len(filled):>8,} {len(filled) / len(scored):>9.1%} "
              f"{per_fill:>11.3f} {per_signal:>13.3f}")

    print("\nR per fill rises because the risk shrinks and the run grows.")
    print("R per signal is what the account sees, and it is the one that decides.")


if __name__ == "__main__":
    main()
