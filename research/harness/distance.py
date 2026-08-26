"""Should `up_rate` join `Features.distance`, or only the model?

Being a useful *model* feature and being a useful *distance dimension* are
different claims. The first says it predicts; the second says two touches with
similar values are worth comparing. edge.md §6 found the current distance
orders neighbours no better than random, so there is little to lose - but
"little to lose" is not a measurement.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from river import metrics
from touches import INTERVALS, _bars

from till_infinity.structures import reactions
from till_infinity.structures.engine import Engine

K = 12
WARM = 150
BASE = (
    "approach_vol",
    "depth_vol",
    "strength",
    "run_vol",
    "experience",
    "pivot",
    "backcheck",
    "regime",
)

engine = Engine(intervals=INTERVALS)
rows = []
for bar in _bars():
    engine.observe_bar(bar)
    for _level, touch in engine.drain_resolved():
        if not touch.push_vol:
            continue
        f = touch.features
        rows.append(
            {
                "above": f.side.name == "ABOVE",
                "v": {k: float(getattr(f, k)) for k in BASE},
                "up_rate": float(f.up_rate),
                "_up": touch.push_vol > 0,
            }
        )
print(f"touches: {len(rows):,}")
spread = sorted(r["up_rate"] for r in rows)
print(
    f"up_rate: p25 {spread[len(spread) // 4]:.2f}  median {spread[len(spread) // 2]:.2f}"
    f"  p75 {spread[3 * len(spread) // 4]:.2f}"
)


def dist(a, b, with_rate, weight=1.0):
    total = sum((a["v"][k] - b["v"][k]) ** 2 for k in BASE)
    if with_rate:
        total += (weight * (a["up_rate"] - b["up_rate"])) ** 2
    return math.sqrt(total)


def run(with_rate, weight=1.0):
    auc = metrics.ROCAUC()
    hits = n = 0
    for i, row in enumerate(rows):
        if i < WARM:
            continue
        window = [r for r in rows[max(0, i - 3000) : i] if r["above"] == row["above"]]
        if len(window) < K * 3:
            continue
        near = sorted(window, key=lambda r: dist(row, r, with_rate, weight))[:K]
        share = sum(1 for r in near if r["_up"]) / K
        n += 1
        hits += (share > 0.5) == row["_up"]
        auc.update(row["_up"], share)
    return (hits / n if n else 0.0), n, auc.get()


print(f"\n{'neighbour vote, distance over':<38} {'n':>6} {'right':>8} {'AUC':>7}")
print("-" * 62)
for label, with_rate, weight in (
    ("the eight features (current)", False, 1.0),
    ("+ up_rate, weight 1", True, 1.0),
    ("+ up_rate, weight 2", True, 2.0),
    ("+ up_rate, weight 4", True, 4.0),
):
    got, n, auc = run(with_rate, weight)
    print(f"{label:<38} {n:>6} {got:>7.1%} {auc:>7.3f}")
