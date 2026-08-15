"""Does the level's own record predict direction, once side is already known?

Two of today's results appear to contradict each other.

  strength.md   a level's own same-side record separates holds from fails by
                +32.8 points, the strongest signal found anywhere
  features.md   nothing in `Features` predicts direction beyond `side`

For a touch from above, "the level held" and "price went up" are the same
event, so those cannot both be true — unless the record is not among the
features. It is not. `Features` carries `strength`, the composite that
strength.md found loses to its own best term, and `experience`, a bare count.
The record itself is never handed to the model.

This snapshots the per-side record **at the moment the touch opens**, before
the outcome is folded in, and asks whether it adds anything to side.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sqlite3

from river import linear_model, metrics, preprocessing
from touches import INTERVALS, _bars

from till_infinity.structures import reactions
from till_infinity.structures.engine import Engine

WARM = 150

snapped: dict[int, dict] = {}
_begin = reactions.Tracker.begin


def begin(self, level, price, features, when):
    touch = _begin(self, level, price, features, when)
    # Before `record` folds this touch in, which is what makes it point in time.
    stats = level.sides.get(features.side)
    snapped[id(touch)] = (
        {
            "touches": stats.touches,
            "ups": stats.ups,
            "rejects": stats.rejects,
            "traps": stats.traps,
            "breaks": stats.breaks,
            "push_mean": stats.push_sum / stats.touches if stats.touches else 0.0,
        }
        if stats
        else None
    )
    return touch


reactions.Tracker.begin = begin

engine = Engine(intervals=INTERVALS)
rows = []
for bar in _bars():
    engine.observe_bar(bar)
    for _level, touch in engine.drain_resolved():
        seen = snapped.pop(id(touch), None)
        if not touch.push_vol or seen is None:
            continue
        above = touch.features.side.name == "ABOVE"
        n = seen["touches"]
        rows.append(
            {
                "above": 1.0 if above else 0.0,
                # The record, expressed the way a model can use it.
                "record_touches": n,
                "record_up_rate": (seen["ups"] / n) if n else 0.5,
                "record_hold_rate": ((seen["rejects"]) / n) if n else 0.5,
                "record_trap_rate": (seen["traps"] / n) if n else 0.0,
                "record_push_mean": seen["push_mean"],
                # Same-side agreement: did this side usually push the way it is
                # about to be asked to again.
                "record_agrees": (
                    ((seen["ups"] / n) > 0.5) == above if n else False
                ) * 1.0,
                "_up": touch.push_vol > 0,
            }
        )

print(f"touches with a record snapshot: {len(rows):,}")
with_history = [r for r in rows if r["record_touches"] > 0]
print(f"of those, the level had prior same-side history: {len(with_history):,}\n")


def score(keys, subset=None):
    data = subset if subset is not None else rows
    model = preprocessing.StandardScaler() | linear_model.LogisticRegression()
    auc = metrics.ROCAUC()
    hits = seen_n = 0
    for i, r in enumerate(data):
        x = {k: r[k] for k in keys}
        said = model.predict_one(x)
        proba = model.predict_proba_one(x)
        if said is not None and i >= WARM:
            seen_n += 1
            hits += said == r["_up"]
            if proba:
                auc.update(r["_up"], proba.get(True, 0.0))
        model.learn_one(x, r["_up"])
    return (hits / seen_n if seen_n else 0.0), seen_n, auc.get()


RECORD = (
    "record_touches", "record_up_rate", "record_hold_rate",
    "record_trap_rate", "record_push_mean", "record_agrees",
)

print(f"{'features':<40} {'n':>6} {'right':>8} {'AUC':>7}")
print("-" * 64)
for label, keys in (
    ("side alone", ("above",)),
    ("the record alone", RECORD),
    ("side + the record", ("above", *RECORD)),
    ("side + up-rate only", ("above", "record_up_rate")),
    ("side + does the record agree", ("above", "record_agrees")),
):
    got, n, auc = score(keys)
    print(f"{label:<40} {n:>6} {got:>7.1%} {auc:>7.3f}")

print("\nrestricted to touches where the level had prior same-side history")
print(f"{'features':<40} {'n':>6} {'right':>8} {'AUC':>7}")
print("-" * 64)
for label, keys in (
    ("side alone", ("above",)),
    ("side + the record", ("above", *RECORD)),
):
    got, n, auc = score(keys, with_history)
    print(f"{label:<40} {n:>6} {got:>7.1%} {auc:>7.3f}")

deep = [r for r in rows if r["record_touches"] >= 3]
print(f"\nand where it had three or more ({len(deep):,} touches)")
for label, keys in (
    ("side alone", ("above",)),
    ("side + the record", ("above", *RECORD)),
):
    got, n, auc = score(keys, deep)
    print(f"{label:<40} {n:>6} {got:>7.1%} {auc:>7.3f}")
