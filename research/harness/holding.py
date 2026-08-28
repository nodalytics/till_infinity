"""Can we estimate how long a touch will take to resolve?

`stop_hold_scaling` widens the stop by the square root of the hold, because
`vol_bps` is one bar of the entry interval and a trade held for many bars
wanders further than one. It uses the strategy's **configured** hold, which is
a constant chosen by hand - 1800 seconds for the scalpers, 120 for `snap`.

The trade does not care what was configured. It cares how long *this* touch
takes, and if that is forecastable the stop can be sized against it rather than
against a constant. This asks whether it is.

Three things, in order of how much they would buy:

1. **How much does it vary?** If every touch resolves in about the same time,
   a constant is already right and there is nothing to estimate.
2. **Is it persistent?** Lag-1 autocorrelation within a feed and interval - if
   slow touches follow slow touches, the recent past is an estimator.
3. **Is it structural?** How much of the spread is explained by which feed and
   interval a touch is on, which is knowable before the trade rather than
   after.

Usage: python -m research.harness.holding [journal.db]
"""

import json
import sqlite3
import statistics
import sys
from collections import defaultdict

FEWEST = 30


def load(db):
    con = sqlite3.connect(db)
    q = "select context from entries where actor='structures' and kind='outcome' order by time"
    series = defaultdict(list)
    for (ctx,) in con.execute(q):
        d = json.loads(ctx or "{}")
        seconds = d.get("seconds")
        if seconds is None or float(seconds) <= 0:
            continue
        series[(d.get("feed") or "", d.get("interval") or "")].append(float(seconds))
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


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    series = {k: v for k, v in load(db).items() if len(v) >= FEWEST}
    every = [s for v in series.values() for s in v]
    print(f"{len(every):,} resolutions across {len(series)} feed/interval series\n")

    ordered = sorted(every)
    print("how long a touch takes, overall")
    for q in (0.25, 0.5, 0.75, 0.9, 0.99):
        print(f"  p{q * 100:g}: {ordered[int(q * len(ordered))]:>8.0f}s")
    fast, slow = ordered[int(0.25 * len(ordered))], ordered[int(0.9 * len(ordered))]
    print(f"  spread p25 to p90: {slow / fast:.0f}x")

    # Persistence: does a slow touch follow a slow touch?
    rhos = [r for r in (autocorr(v) for v in series.values()) if r is not None]
    # On the log, because the raw distribution is long-tailed enough that one
    # outlier dominates the covariance.
    import math

    logs = [
        r for r in (autocorr([math.log(s) for s in v]) for v in series.values()) if r is not None
    ]
    print(f"\npersistence (lag-1 autocorrelation), {len(rhos)} series")
    print(
        f"  raw seconds: mean rho {sum(rhos) / len(rhos):+.3f}, "
        f"positive in {sum(1 for r in rhos if r > 0) / len(rhos):.0%}"
    )
    print(
        f"  log seconds: mean rho {sum(logs) / len(logs):+.3f}, "
        f"positive in {sum(1 for r in logs if r > 0) / len(logs):.0%}"
    )

    # Structure: how different are the series from each other?
    medians = {k: statistics.median(v) for k, v in series.items()}
    lo = min(medians.values())
    hi = max(medians.values())
    print(f"\nstructure: median hold ranges {lo:.0f}s to {hi:.0f}s ({hi / lo:.0f}x)")
    print("  slowest and fastest:")
    for key in sorted(medians, key=lambda k: -medians[k])[:3]:
        print(f"    {key[0]:<8s} {key[1]:<4s} {medians[key]:>7.0f}s  (n={len(series[key])})")
    for key in sorted(medians, key=lambda k: medians[k])[:3]:
        print(f"    {key[0]:<8s} {key[1]:<4s} {medians[key]:>7.0f}s  (n={len(series[key])})")


if __name__ == "__main__":
    main()
