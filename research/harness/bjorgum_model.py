"""Can a model pick which bjorgum zones to trade, better than one rule can?

Zones from `bjorgum.py` — the port of **Bjorgum Key Levels**, by Bjorgum on
TradingView, https://www.tradingview.com/script/CapG3ivf-Bjorgum-Key-Levels/.
That harness measured each of its ideas alone: freshness separates a break from
a hold by 27 points at 15m, role-flipping by 24. This asks the next question -
whether a learner reading all of them together beats the best single one, and
whether the combination is worth anything a fixed threshold is not.

## Why this is not a bandit, said once more

research/bandits.md gives the test: *if you would have learned the outcome
anyway, whatever you chose, it is not a bandit problem*. Every zone visit
resolves on the stored bars whether or not anything traded it, so every arm
reports on every decision. That is full information, and exponential weights or
plain supervised learning is the right family - a bandit would be paying
exploration for a counterfactual already in hand.

The bandit framing survives in exactly one place, and it is not decided here:
whether a **resting order at a zone actually fills**, and at what spread. Bars
cannot answer that; only trading it can.

## What is scored

Predict-then-update, one pass in time order, so every score is out of sample -
the same discipline `structures/breaking.py` is scored under. Against:

* each feature alone, as a single-threshold rule;
* all of them together;
* the synthetic control, where a generated process should yield nothing.
"""

import sqlite3
import sys
from collections import Counter, defaultdict

import numpy as np
from bjorgum import (  # type: ignore[import-not-found]
    MAX_BARS,
    MAX_FEEDS,
    atr,
    build,
    merge,
    pivots,
    visits_and_outcomes,
)
from river import compose, linear_model, preprocessing


def auc(scores: list[float], labels: list[bool]) -> float:
    s, y = np.asarray(scores), np.asarray(labels, dtype=bool)
    if y.all() or not y.any():
        return float("nan")
    order = np.argsort(s)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, s.size + 1)
    n1, n0 = y.sum(), (~y).sum()
    return (ranks[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def family(feed: str) -> str:
    low = feed.lower()
    if any(k in low for k in ("volatility", "step", "jump", "range_break")):
        return "synthetic control"
    if any(k in low for k in ("boom", "crash")):
        return "boom/crash"
    return "real market"


def gather(interval: str) -> dict[str, list[tuple[int, dict[str, float], bool]]]:
    q = sqlite3.connect("file:/app/.data/prices/prices.db?mode=ro", uri=True)
    feeds = [
        r[0] for r in q.execute("select distinct feed from bars where interval = ?", (interval,))
    ]
    rows: dict[str, list] = defaultdict(list)
    quota: Counter = Counter()
    for feed in feeds:
        fam = family(feed)
        if quota[fam] >= MAX_FEEDS:
            continue
        bars = list(
            q.execute(
                "select high, low, close from bars where feed=? and interval=? "
                "order by ts desc limit ?",
                (feed, interval, MAX_BARS),
            )
        )[::-1]
        if len(bars) < 300:
            continue
        quota[fam] += 1
        high = np.array([b[0] for b in bars], dtype=float)
        low = np.array([b[1] for b in bars], dtype=float)
        close = np.array([b[2] for b in bars], dtype=float)
        band = atr(high, low, close)
        hi_p, lo_p = pivots(high, low)
        zones = merge(
            [z for z in (build(high, low, close, i, True, band) for i in hi_p) if z]
            + [z for z in (build(high, low, close, i, False, band) for i in lo_p) if z]
        )
        for zone in zones:
            width = (zone.top - zone.bottom) / max(zone.mid, 1e-9)
            for n, (at, broke, above) in enumerate(visits_and_outcomes(high, low, close, zone), 1):
                rows[fam].append(
                    (
                        at,
                        {
                            "visit": float(n),
                            "fresh": 1.0 if n == 1 else 0.0,
                            "flipped": 1.0 if zone.flipped else 0.0,
                            "crossings": float(zone.breaks),
                            "width": width * 1000,
                            "age": float(at - zone.index),
                            "from_above": 1.0 if above else 0.0,
                        },
                        broke,
                    )
                )
    for visits in rows.values():
        visits.sort(key=lambda r: r[0])
    return rows


def score(data, keys: list[str], burn: int = 200) -> tuple[float, int]:
    model = compose.Pipeline(preprocessing.StandardScaler(), linear_model.LogisticRegression())
    got, lab = [], []
    for i, (_, feats, broke) in enumerate(data):
        x = {k: feats[k] for k in keys}
        if i > burn:
            got.append(model.predict_proba_one(x).get(True, 0.5))
            lab.append(broke)
        model.learn_one(x, broke)
    return auc(got, lab), len(got)


def main() -> None:
    interval = sys.argv[1] if len(sys.argv) > 1 else "15m"
    rows = gather(interval)
    every = ["visit", "fresh", "flipped", "crossings", "width", "age", "from_above"]
    print(f"interval {interval}\n")
    for fam in ("real market", "boom/crash", "synthetic control"):
        data = rows.get(fam)
        if not data or len(data) < 400:
            continue
        base = sum(1 for r in data if r[2]) / len(data)
        print(f"=== {fam}: {len(data):,} visits, base break rate {base:.1%}")
        print(f"    {'features':28s} {'AUC':>7s} {'scored':>8s}")
        for one in every:
            a, n = score(data, [one])
            print(f"    {one:28s} {a:7.4f} {n:8,d}")
        a, n = score(data, every)
        print(f"    {'ALL TOGETHER':28s} {a:7.4f} {n:8,d}")
        print()


if __name__ == "__main__":
    main()
