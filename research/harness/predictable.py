"""Volatility is predictable. Is momentum?

The question matters because a great deal here rests on the answer. Volatility
being persistent is why `garch`, `har`, `ranges` and `consensus_vol` exist and
why sizing in volatility units works at all. If direction were persistent in
the same way, momentum would deserve the same apparatus - its own estimators,
its own ensemble, arguably its own service. If it is not, momentum can only
ever be a filter on a thesis that comes from somewhere else, which is what it
currently is.

The test is the same for both, which is what makes it a fair comparison:
**lag-1 autocorrelation within a feed and interval**, computed over the
sequence of resolved touches.

* **Magnitude** - `|push|` - stands in for volatility. A positive
  autocorrelation is volatility clustering: big moves follow big moves.
* **Direction** - the change in `level` from one resolution to the next -
  stands in for momentum. A positive autocorrelation means price moving one
  way tends to keep moving that way.

**Direction is taken from `level`, not from `push_vol`, and the difference
decides whether this measures anything.** `push_vol` is signed by the outcome
together with the approach side, which is an identity: consecutive touches on
one level usually share an approach side, so its sign autocorrelates by
construction. Measured that way the answer comes out at rho 0.30 for direction
against 0.16 for magnitude - momentum apparently twice as persistent as
volatility, which is the sound of a variable being scored against itself.
Successive `level` prices are just where price has been.

Both are measured on the same rows, the same way, so the comparison is not
confounded by sample or method. Series shorter than `FEWEST` are skipped
because an autocorrelation on six points is noise with a decimal point.

Usage: python -m research.harness.predictable [journal.db]
"""

import json
import sqlite3
import sys
from collections import defaultdict

#: Shortest series worth measuring an autocorrelation on.
FEWEST = 30


def load(db):
    con = sqlite3.connect(db)
    q = "select time,context from entries where actor='structures' and kind='outcome' order by time"
    series = defaultdict(list)
    for _t, ctx in con.execute(q):
        d = json.loads(ctx or "{}")
        push, level = d.get("push_vol"), d.get("level")
        if push is None or level is None:
            continue
        key = (d.get("feed") or "", d.get("interval") or "")
        series[key].append((float(push), float(level)))
    return series


def autocorr(values):
    """Lag-1 autocorrelation. None when the series says nothing."""
    n = len(values)
    if n < FEWEST:
        return None
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values)
    if var <= 0:
        return None
    cov = sum((values[i] - mean) * (values[i + 1] - mean) for i in range(n - 1))
    return cov / var


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    series = load(db)
    rows = {k: v for k, v in series.items() if len(v) >= FEWEST}
    print(f"{len(rows)} feed/interval series of at least {FEWEST} resolutions")
    print(f"{sum(len(v) for v in rows.values()):,} resolutions in them\n")

    measures = {
        "|push| (volatility)": [],
        "level change (momentum)": [],
        "its sign only": [],
    }
    for values in rows.values():
        pushes = [p for p, _ in values]
        levels = [lv for _, lv in values]
        steps = [levels[i + 1] - levels[i] for i in range(len(levels) - 1)]
        for name, prepared in (
            ("|push| (volatility)", [abs(p) for p in pushes]),
            ("level change (momentum)", steps),
            ("its sign only", [1.0 if s0 > 0 else -1.0 for s0 in steps if s0 != 0]),
        ):
            got = autocorr(prepared)
            if got is not None:
                measures[name].append(got)

    print(f"{'measure':>26s} {'series':>7s} {'mean rho':>9s} {'share > 0':>10s}")
    print("-" * 56)
    for name, values in measures.items():
        if not values:
            continue
        mean = sum(values) / len(values)
        share = sum(1 for v in values if v > 0) / len(values)
        print(f"{name:>26s} {len(values):>7d} {mean:>9.3f} {share:>9.0%}")

    print("\nIf volatility clusters and direction does not, the first row is")
    print("clearly positive and the other two sit near zero. That is the")
    print("classic result; this says whether it holds on our own instruments.")


if __name__ == "__main__":
    main()
