"""Re-verify the `reward_to_risk` gate against the live journal.

[magnitude.md](../magnitude.md) measured on 2026-08-17, over a replay of stored
bars, that this gate selects losing trades out of a winning population - and
`docs/todo.md` 0f has said "remove it" ever since. It is still live, and it is
the single largest source of refusals in production.

Before removing a live gate on a ten-day-old replay, this re-runs the question
against what actually happened since. Different data and a different method:
production signals joined to production outcomes through the journal's own
parent link, rather than a replay of bars through the engine.

The join is the point. Every outcome names the observation that produced it, so
the `reward_to_risk` a call was published with can be set against the push that
call actually realised - no reconstruction, no assumption about which signal
became which touch.

Usage: python -m research.harness.rr_gate [journal.db]
"""

import json
import sqlite3
import sys

#: The live thresholds, so the table answers the question actually being asked.
LIVE_STRUCTURES = 1.0
LIVE_TRADING = 1.2


def paired(db):
    """Every resolved touch with the reward_to_risk its signal carried."""
    con = sqlite3.connect(db)
    signals = {}
    q = "select id,context from entries where actor='structures' and kind='observation'"
    for entry_id, ctx in con.execute(q):
        d = json.loads(ctx or "{}")
        rr = d.get("reward_to_risk")
        if rr is not None:
            signals[entry_id] = float(rr)

    out = []
    q = "select parent,context from entries where actor='structures' and kind='outcome'"
    for parent, ctx in con.execute(q):
        rr = signals.get(parent)
        if rr is None:
            continue
        d = json.loads(ctx or "{}")
        push = d.get("push_vol")
        if push is None:
            continue
        out.append((rr, abs(float(push)), float(d.get("excursion_vol") or 0.0)))
    return out


def mean(values):
    return sum(values) / len(values) if values else 0.0


def r_of(push, excursion, stop=0.5, target=0.75):
    """R under a fixed stop-and-target rule. Stop wins ties.

    Used instead of mean |push| because |push| counts a large move *against*
    the trade as a good outcome - it measures how far price went, not whether
    the trade made money. A gate is not worth removing on a number that cannot
    tell those apart.
    """
    if excursion >= stop:
        return -1.0
    return (target / stop) if push >= target else 0.0


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = paired(db)
    print(f"{len(rows):,} resolved touches joined to the signal that produced them\n")
    if len(rows) < 500:
        print("not enough to say anything")
        return

    print("mean R at a 0.5v stop, and mean |push| beside it")
    print(f"{'rule':>28s} {'n':>8s} {'R':>8s} {'push':>8s}")
    print("-" * 56)
    rows_all = [(r_of(p, e), p) for _, p, e in rows]
    print(
        f"{'every call, no gate':>28s} {len(rows_all):>8,} "
        f"{mean([r for r, _ in rows_all]):>8.3f} {mean([p for _, p in rows_all]):>8.3f}"
    )
    for name, floor in (
        ("gated at RR >= 1.0", LIVE_STRUCTURES),
        ("gated at RR >= 1.2 (trading)", LIVE_TRADING),
        ("gated at RR >= 2.0", 2.0),
    ):
        kept = [(r_of(p, e), p) for rr, p, e in rows if rr >= floor]
        if not kept:
            continue
        print(
            f"{name:>28s} {len(kept):>8,} "
            f"{mean([r for r, _ in kept]):>8.3f} {mean([p for _, p in kept]):>8.3f}"
        )

    print("\nwhat the gate keeps against what it throws away, in R")
    for floor in (LIVE_STRUCTURES, LIVE_TRADING):
        kept = [r_of(p, e) for rr, p, e in rows if rr >= floor]
        tossed = [r_of(p, e) for rr, p, e in rows if rr < floor]
        print(
            f"  RR >= {floor}: keeps {len(kept):,} at {mean(kept):.3f}R, "
            f"rejects {len(tossed):,} at {mean(tossed):.3f}R"
        )

    print("\nthe mechanism: is a high ratio just a tight stop?")
    ordered = sorted(rows, key=lambda r: r[0])
    size = len(ordered) // 10
    low, high = ordered[:size], ordered[-size:]
    lo_exc = mean([e for _, _, e in low])
    hi_exc = mean([e for _, _, e in high])
    print(f"  bottom decile RR {low[0][0]:.2f}-{low[-1][0]:.2f}: excursion {lo_exc:.3f}v")
    print(f"  top decile    RR {high[0][0]:.2f}-{high[-1][0]:.2f}: excursion {hi_exc:.3f}v")
    print("  the tight-stop mechanism predicts the top decile excursing LESS")


if __name__ == "__main__":
    main()
