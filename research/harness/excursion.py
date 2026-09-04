"""How much room a trade actually needs, from the record rather than a rule.

Answers `research/planned/excursion.md` against the journal's `outcome`
entries. Every stop in this system is placed from a rule - beyond the level,
past the origin's far edge, a multiple of volatility - and none of it from a
measurement of how far price goes against a trade that later wins. That
quantity is `adverse_r`, and it read exactly 0.0 on all 188 closes until the
`_reconcile` fix, which is why this could not be asked before.

Run inside the container, where the journal is:

    docker exec till-infinity python /tmp/excursion.py
"""

from __future__ import annotations

import json
import sqlite3
import statistics as st
from collections import defaultdict

DB = "file:/app/.data/journal/journal.db?mode=ro"


def quantile(values: list[float], share: float) -> float:
    """The value at `share` through a sorted list. Nearest-rank, no smoothing -
    with tens of observations, interpolation invents precision."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return ordered[index]


def load() -> list[dict]:
    db = sqlite3.connect(DB, uri=True)
    out = []
    for (ctx,) in db.execute("select context from entries where kind='outcome'"):
        try:
            row = json.loads(ctx)
        except Exception:
            continue
        # Both readings have to be real. A row missing either predates the fix
        # and cannot be told apart from a trade that genuinely never moved.
        if not isinstance(row.get("adverse_r"), int | float):
            continue
        if not isinstance(row.get("r_multiple"), int | float):
            continue
        out.append(row)
    return out


def describe(name: str, values: list[float]) -> None:
    if not values:
        print(f"  {name:<22} no observations")
        return
    print(
        f"  {name:<22} n={len(values):<4} median={st.median(values):.3f} "
        f"p75={quantile(values, 0.75):.3f} p90={quantile(values, 0.90):.3f} "
        f"max={max(values):.3f}"
    )


def main() -> None:
    rows = load()
    won = [r for r in rows if r["r_multiple"] > 0]
    lost = [r for r in rows if r["r_multiple"] <= 0]
    print(f"closed trades with real excursions: {len(rows)}  ({len(won)} won, {len(lost)} lost)")

    print("\n1. How far winners went against themselves, in units of their own risk")
    describe("winners", [float(r["adverse_r"]) for r in won])
    describe("losers", [float(r["adverse_r"]) for r in lost])
    heat = [float(r["adverse_r"]) for r in won]
    if heat:
        p90 = quantile(heat, 0.90)
        print(
            f"\n   p90 of {p90:.2f} means a stop at 1.0R sits "
            + (
                "well clear of where winners live - the losses are coming from somewhere else."
                if p90 < 0.7
                else "close to where winners live, so widening buys real trades back."
            )
        )

    print("\n2. The same, per instrument - gold is the reason to expect a difference")
    by = defaultdict(list)
    for r in won:
        by[str(r.get("symbol") or "?")].append(float(r["adverse_r"]))
    for symbol, values in sorted(by.items(), key=lambda kv: -len(kv[1]))[:10]:
        describe(symbol[:22], values)

    print("\n3. What a wider stop would have cost, where the record can say")
    # Only losers that were *not* stopped can answer this: a stopped trade's
    # adverse excursion is its stop by construction, so it says nothing about
    # how much further price would have gone. Naming the limit rather than
    # reporting a number that looks like an answer.
    stopped = [r for r in lost if str(r.get("exit_kind")) == "stop"]
    other = [r for r in lost if str(r.get("exit_kind")) != "stop"]
    print(
        f"   {len(stopped)} losers exited at the stop - their adverse_r is the stop, not a reading"
    )
    print(f"   {len(other)} exited another way, so their excursion is informative")
    describe("non-stopped losers", [float(r["adverse_r"]) for r in other])
    print("   A widening study needs bars past the stop, which this table does not hold.")

    print("\n4. How much of the favourable move the book actually kept")
    kept = [
        (float(r["best_r"]), float(r["r_multiple"]))
        for r in rows
        if isinstance(r.get("best_r"), int | float) and float(r["best_r"]) > 0
    ]
    if kept:
        describe("best_r, all trades", [b for b, _ in kept])
        ratios = [got / best for best, got in kept if best > 0 and got > 0]
        describe("captured share", ratios)
        gave = [(b, g) for b, g in kept if b >= 1.0 and g <= 0]
        print(
            f"\n   {len(gave)} trades reached 1R or better and still lost, "
            f"costing {sum(g for _, g in gave):.2f}R between them"
        )
        if gave:
            print(f"   they peaked at a median of {st.median([b for b, _ in gave]):.2f}R")


if __name__ == "__main__":
    main()
