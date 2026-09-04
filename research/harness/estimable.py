"""Which recorded quantities are worth estimating, and which are not.

Two properties decide it, and they are the ones that justified the volatility
apparatus:

* **it varies** - if every observation is much the same, a constant is already
  right and an estimator buys nothing;
* **it persists** - if what happened recently says nothing about what happens
  next, there is nothing to estimate from.

Volatility has both (+0.159 lag-1, and a wide spread) and has five estimators.
Direction has the first and not the second (-0.013) and correctly has none.
Hold time has both (+0.269, 163x) and had none until this week.

This screens every numeric field on a resolution the same way, so the next
estimator is chosen from a ranking rather than from whichever quantity came up
in conversation.

**Persistence is measured on the log where the quantity is positive**, because
these distributions are long-tailed enough that one outlier dominates a
covariance - which is how hold time first looked less persistent than it is.

Usage: python -m research.harness.estimable [journal.db]
"""

import json
import math
import sqlite3
import sys
from collections import defaultdict

FEWEST = 30

#: Fields that are identities, labels or already-known constants rather than
#: quantities to forecast. `push_vol` is signed by the outcome and the approach
#: side together, which is why it is not here - see replay.md.
SKIP = {"level", "when", "seconds", "push_vol"}


def load(db):
    con = sqlite3.connect(db)
    q = "select context from entries where actor='structures' and kind='outcome' order by time"
    series = defaultdict(lambda: defaultdict(list))
    for (ctx,) in con.execute(q):
        d = json.loads(ctx or "{}")
        key = (d.get("feed") or "", d.get("interval") or "")
        for name, value in d.items():
            if name in SKIP or not isinstance(value, int | float) or isinstance(value, bool):
                continue
            series[name][key].append(float(value))
    return series


def autocorr(values):
    n = len(values)
    if n < FEWEST:
        return None
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values)
    if var <= 0:
        return None
    return sum((values[i] - mean) * (values[i + 1] - mean) for i in range(n - 1)) / var


def spread_of(values):
    """p90 over p25, a scale-free measure of how much room an estimator has."""
    ordered = sorted(v for v in values if v > 0)
    if len(ordered) < 20:
        return None
    low = ordered[len(ordered) // 4]
    return ordered[int(0.9 * len(ordered))] / low if low > 0 else None


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    fields = load(db)
    rows = []
    for name, series in fields.items():
        usable = [v for v in series.values() if len(v) >= FEWEST]
        if len(usable) < 3:
            continue
        rhos, spreads = [], []
        for values in usable:
            positive = all(v > 0 for v in values)
            prepared = [math.log(v) for v in values] if positive else values
            got = autocorr(prepared)
            if got is not None:
                rhos.append(got)
            width = spread_of(values)
            if width is not None:
                spreads.append(width)
        if not rhos:
            continue
        rows.append(
            (
                name,
                len(usable),
                sum(rhos) / len(rhos),
                sum(spreads) / len(spreads) if spreads else 0.0,
            )
        )

    rows.sort(key=lambda r: -r[2])
    print(f"{len(rows)} quantities with at least 3 usable series\n")
    print(f"{'quantity':>22s} {'series':>7s} {'rho':>8s} {'p90/p25':>9s}  verdict")
    print("-" * 66)
    for name, count, rho, spread in rows:
        if rho > 0.15 and spread > 2.0:
            verdict = "worth estimating"
        elif rho > 0.15:
            verdict = "persists, little room"
        elif spread > 2.0:
            verdict = "varies, unforecastable"
        else:
            verdict = "leave it alone"
        print(f"{name:>22s} {count:>7d} {rho:>+8.3f} {spread:>9.1f}  {verdict}")


if __name__ == "__main__":
    main()
