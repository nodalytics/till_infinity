"""Does the force arriving at a level decide whether it breaks?

The desk claim: a level can be good and still fail, because what matters is not
only the level's own record but **how hard price is coming at it**. Arrive
gently and it holds; arrive with a run behind you and it goes.

Two features already carry that - `approach_vol`, how fast price was travelling
into the level in volatility units per bar, and `run_vol`, how far the leg had
already travelled. Neither has ever been asked this question, because until
research/horizon.md the answer would have been measured on a population where
a touch resolving inside a minute resolves in the direction its side implies
100.0% of the time. There was nothing to separate.

At 300-1,800s the side is right about 68% of the time, so a third of the
touches are breaks and the question has an answer.

Read straight off `outcome`, which labels this directly - reject, backcheck,
break, trap, chop - rather than inferring it from the push.
"""

from __future__ import annotations

import json
import sqlite3
import statistics as st

JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"
LOW, HIGH = 300.0, 1800.0

HELD = ("reject", "backcheck")
BROKE = ("break", "trap")


def rows() -> list[dict]:
    conn = sqlite3.connect(JOURNAL, uri=True)
    out = []
    for (blob,) in conn.execute(
        "SELECT context FROM entries WHERE actor='structures' AND kind='outcome'"
        " ORDER BY time DESC LIMIT 400000"
    ):
        try:
            d = json.loads(blob or "{}")
        except (ValueError, TypeError):
            continue
        outcome, secs = str(d.get("outcome") or ""), d.get("seconds")
        if secs is None or outcome not in HELD + BROKE:
            continue
        try:
            secs = float(secs)
        except (TypeError, ValueError):
            continue
        if not (LOW <= secs < HIGH):
            continue
        got = {"broke": outcome in BROKE}
        for name in ("approach_vol", "run_vol", "up_rate", "strength", "depth_vol", "experience"):
            try:
                got[name] = float(d.get(name) or 0.0)
            except (TypeError, ValueError):
                got[name] = 0.0
        out.append(got)
    return out


def by_decile(seen: list[dict], name: str, buckets: int = 5) -> None:
    """Break rate across the range of one feature, weakest first."""
    ordered = sorted(seen, key=lambda r: r[name])
    step = len(ordered) // buckets
    if step < 10:
        print(f"   {name}: too few")
        return
    print(f"   {name:14s}", end="")
    rates = []
    for i in range(buckets):
        cut = ordered[i * step : (i + 1) * step] if i < buckets - 1 else ordered[i * step :]
        rate = sum(1 for r in cut if r["broke"]) / len(cut)
        rates.append(rate)
        print(f" {rate:6.1%}", end="")
    lo, hi = rates[0], rates[-1]
    print(f"   spread {hi - lo:+6.1%}")


def auc(seen: list[dict], name: str) -> float:
    """AUC of the feature predicting a break. 0.5 is no separation."""
    scored = sorted(((r[name], r["broke"]) for r in seen), key=lambda kv: kv[0])
    positives = sum(1 for _s, b in scored if b)
    negatives = len(scored) - positives
    if not positives or not negatives:
        return 0.5
    ranks = {}
    i = 0
    while i < len(scored):
        j = i
        while j + 1 < len(scored) and scored[j + 1][0] == scored[i][0]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = shared
        i = j + 1
    got = sum(ranks[k] for k, (_s, b) in enumerate(scored) if b)
    return (got - positives * (positives + 1) / 2.0) / (positives * negatives)


def main() -> None:
    seen = rows()
    broke = sum(1 for r in seen if r["broke"])
    print(
        f"{len(seen)} resolved touches in {LOW:.0f}-{HIGH:.0f}s, {broke} of them breaks "
        f"({broke / max(len(seen), 1):.1%})\n"
    )
    if len(seen) < 200:
        print("too few to say anything")
        return

    print("break rate across each feature, weakest fifth to strongest:")
    for name in ("approach_vol", "run_vol", "depth_vol", "strength", "experience"):
        by_decile(seen, name)

    print("\nseparation, as AUC of the feature predicting a break (0.5 is nothing):")
    for name in ("approach_vol", "run_vol", "depth_vol", "strength", "experience", "up_rate"):
        print(f"   {name:14s} {auc(seen, name):.4f}")

    fast = [r for r in seen if r["approach_vol"] > st.median(x["approach_vol"] for x in seen)]
    slow = [r for r in seen if r["approach_vol"] <= st.median(x["approach_vol"] for x in seen)]
    for label, cut in (("arriving fast", fast), ("arriving slow", slow)):
        if cut:
            rate = sum(1 for r in cut if r["broke"]) / len(cut)
            print(f"\n{label:14s} {len(cut):5d} touches, {rate:.1%} break")


if __name__ == "__main__":
    main()
