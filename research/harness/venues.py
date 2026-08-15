"""Does cross-venue disagreement at the moment of touch predict anything?

This project exists to measure disagreement between venues — `features.Book`
computes each venue's deviation from the consensus, and `anomaly.Detector`
alerts on it. None of it is ever handed to the level model. `Features` carries
nine numbers and every one of them describes the level or the approach; not one
describes the state of the market the touch is happening in.

So the first thing to try is the thing already collected: how far apart the
venues were on the bar the touch opened on.

Measured against AUC as well as accuracy, because the base rate is 78% and
accuracy is nearly blind to a better ranking at that mix — which is what made
the level's own record look useless in `record.py` until AUC was added.
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from river import linear_model, metrics, preprocessing
from touches import INTERVALS, _bars

from till_infinity.structures import engine as eng
from till_infinity.structures import reactions
from till_infinity.structures.engine import Engine

WARM = 150

# Dispersion of the venue closes on the most recent bar of each (feed, interval).
spread: dict[tuple[str, str], float] = {}
_observe = eng.Consensus.observe


def observe(self, feed, interval, venue, when, high, low, close):
    got = _observe(self, feed, interval, venue, when, high, low, close)
    at = self._bars.get((feed, interval), {}).get(when, {})
    closes = [c for _, _, c in at.values()]
    if len(closes) > 1:
        middle = statistics.median(closes)
        if middle:
            spread[(feed, interval)] = (max(closes) - min(closes)) / middle * 10_000
    return got


eng.Consensus.observe = observe

snapped: dict[int, dict] = {}
_begin = reactions.Tracker.begin


def begin(self, level, price, features, when):
    touch = _begin(self, level, price, features, when)
    vol = None
    snapped[id(touch)] = {
        "venue_bps": spread.get((level.feed, level.interval), 0.0),
        "vol": vol,
    }
    return touch


reactions.Tracker.begin = begin

engine = Engine(intervals=INTERVALS)
rows = []
for bar in _bars():
    engine.observe_bar(bar)
    for level, touch in engine.drain_resolved():
        seen = snapped.pop(id(touch), None)
        if not touch.push_vol or seen is None:
            continue
        book = engine.vol.of(touch.feed, touch.interval)
        rows.append(
            {
                "above": 1.0 if touch.features.side.name == "ABOVE" else 0.0,
                # Raw, and in volatility units — the only form comparable across
                # instruments, which is the whole argument of levels.md §10b.
                "venue_bps": seen["venue_bps"],
                "venue_vol": seen["venue_bps"] / book.bps if book.bps else 0.0,
                "feed": touch.feed,
                "interval": touch.interval,
                # The interaction. "Venues disagree" predicts *holding*, and
                # holding is direction combined with side — so a linear model
                # cannot use it without the product.
                "gap_x_side": (seen["venue_bps"] / book.bps if book.bps else 0.0)
                * (1.0 if touch.features.side.name == "ABOVE" else -1.0),
                "_up": touch.push_vol > 0,
            }
        )

print(f"touches: {len(rows):,}")
live = [r for r in rows if r["venue_bps"] > 0]
print(f"with more than one venue on the bar: {len(live):,}")
if live:
    vals = sorted(r["venue_vol"] for r in live)
    print(
        "cross-venue gap in volatility units: "
        f"p25 {vals[len(vals) // 4]:.2f}  median {vals[len(vals) // 2]:.2f}"
        f"  p75 {vals[3 * len(vals) // 4]:.2f}"
    )


def score(keys, data):
    model = preprocessing.StandardScaler() | linear_model.LogisticRegression()
    auc = metrics.ROCAUC()
    hits = n = 0
    for i, r in enumerate(data):
        x = {k: r[k] for k in keys}
        said = model.predict_one(x)
        proba = model.predict_proba_one(x)
        if said is not None and i >= WARM:
            n += 1
            hits += said == r["_up"]
            if proba:
                auc.update(r["_up"], proba.get(True, 0.0))
        model.learn_one(x, r["_up"])
    return (hits / n if n else 0.0), n, auc.get()


print(f"\n{'features':<34} {'n':>6} {'right':>8} {'AUC':>7}")
print("-" * 58)
for label, keys in (
    ("side alone", ("above",)),
    ("side + venue gap (bps)", ("above", "venue_bps")),
    ("side + venue gap (vol units)", ("above", "venue_vol")),
    ("venue gap alone", ("venue_vol",)),
    ("side + gap x side (interaction)", ("above", "gap_x_side")),
    ("side + gap + interaction", ("above", "venue_vol", "gap_x_side")),
):
    got, n, auc = score(keys, live)
    print(f"{label:<34} {n:>6} {got:>7.1%} {auc:>7.3f}")

if live:
    ordered = sorted(live, key=lambda r: r["venue_vol"])
    third = len(ordered) // 3
    print("\nhow often the level holds, by how far apart the venues were")
    print(f"  {'band':<16} {'n':>6} {'level held':>12}")
    for name, chunk in (
        ("agreeing", ordered[:third]),
        ("middle", ordered[third : 2 * third]),
        ("disagreeing", ordered[2 * third :]),
    ):
        held = sum(1 for r in chunk if (r["above"] > 0.5) == r["_up"])
        print(f"  {name:<16} {len(chunk):>6} {held / len(chunk):>11.1%}")


# The confound: venue gaps are far wider on some instruments than others —
# 3.46 volatility units on spx500 against 0.05 on gold — so a tercile split
# across all of them may just be an instrument split. Redone within each cell.
print("\nwithin (feed, interval), so the split cannot be an instrument split")
print(f"  {'cell':<16} {'n':>5} {'agreeing held':>14} {'disagreeing held':>17} {'gap':>7}")
from collections import defaultdict  # noqa: E402

cells = defaultdict(list)
for r in live:
    cells[(r["feed"], r["interval"])].append(r)
deltas = []
for cell, chunk in sorted(cells.items(), key=lambda kv: -len(kv[1])):
    if len(chunk) < 60:
        continue
    chunk.sort(key=lambda r: r["venue_vol"])
    half = len(chunk) // 2
    lo, hi = chunk[:half], chunk[half:]
    lo_held = sum(1 for r in lo if (r["above"] > 0.5) == r["_up"]) / len(lo)
    hi_held = sum(1 for r in hi if (r["above"] > 0.5) == r["_up"]) / len(hi)
    deltas.append(hi_held - lo_held)
    print(f"  {cell[0] + ' ' + cell[1]:<16} {len(chunk):>5} {lo_held:>13.1%}"
          f" {hi_held:>16.1%} {100 * (hi_held - lo_held):>+6.1f}pp")
if deltas:
    print(f"\n  cells where disagreement helped: {sum(1 for d in deltas if d > 0)}/{len(deltas)}")
    print(f"  median change: {100 * sorted(deltas)[len(deltas) // 2]:+.1f}pp")
