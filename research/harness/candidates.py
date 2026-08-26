"""Four things not currently measured at a touch, tested on the data we have.

`Features` carries nine numbers and every one describes the level or the
approach. None describes the market the touch is happening in. These four are
collected already and never handed to the model:

  volume      the bar's volume against this series' own recent average
  session     time of day, as the hour in UTC, one-hot into four sessions
  momentum    where price is relative to twenty bars ago, in volatility units
  headroom    distance to the next level beyond this one - is there room to
              run, or a barrier a few units away

Scored on AUC as well as accuracy: the base rate is 78% and accuracy is nearly
blind to a better ranking at that mix, which is what hid the level's own record
in `record.py`.
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from river import linear_model, metrics, preprocessing
from touches import INTERVALS, _bars

from till_infinity.structures import reactions
from till_infinity.structures.engine import Engine

WARM = 150

recent: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=20))
volumes: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=50))
last_bar: dict[tuple[str, str], dict] = {}
snapped: dict[int, dict] = {}
_begin = reactions.Tracker.begin
engine = Engine(intervals=INTERVALS)


def begin(self, level, price, features, when):
    touch = _begin(self, level, price, features, when)
    key = (level.feed, level.interval)
    book = engine.vol.of(level.feed, level.interval)
    closes = recent[key]
    vols = volumes[key]
    bar = last_bar.get(key, {})

    # Where the next level sits beyond this one, on the side price is heading.
    others = [
        abs(other.distance_vol(price, book))
        for other in engine.levels(level.feed, level.interval)
        if other is not level
    ]
    snapped[id(touch)] = {
        "volume_ratio": (bar.get("volume", 0.0) / statistics.fmean(vols))
        if vols and statistics.fmean(vols)
        else 1.0,
        "hour": (when % 86_400) / 3600.0,
        "momentum_vol": (
            (price - closes[0]) / closes[0] * 10_000 / book.bps
            if closes and closes[0] and book.bps
            else 0.0
        ),
        "headroom_vol": min(others) if others else 8.0,
    }
    return touch


reactions.Tracker.begin = begin

rows = []
for bar in _bars():
    key = (bar["feed"], bar["interval"])
    engine.observe_bar(bar)
    last_bar[key] = bar
    recent[key].append(bar["close"])
    volumes[key].append(float(bar.get("volume") or 0.0))
    for _level, touch in engine.drain_resolved():
        seen = snapped.pop(id(touch), None)
        if not touch.push_vol or seen is None:
            continue
        above = touch.features.side.name == "ABOVE"
        hour = seen["hour"]
        rows.append(
            {
                "above": 1.0 if above else 0.0,
                "volume_ratio": min(seen["volume_ratio"], 10.0),
                "momentum_vol": max(-20.0, min(20.0, seen["momentum_vol"])),
                "headroom_vol": min(seen["headroom_vol"], 8.0),
                # Sessions rather than a raw hour, which a linear model reads
                # as "later is more".
                "asia": 1.0 if 0 <= hour < 7 else 0.0,
                "london": 1.0 if 7 <= hour < 12 else 0.0,
                "overlap": 1.0 if 12 <= hour < 16 else 0.0,
                "us": 1.0 if 16 <= hour < 21 else 0.0,
                "_up": touch.push_vol > 0,
                "_held": above == (touch.push_vol > 0),
                "_cell": (touch.feed, touch.interval),
            }
        )

print(f"touches: {len(rows):,}")
print(f"with a volume reading: {sum(1 for r in rows if r['volume_ratio'] != 1.0):,}\n")


def score(keys):
    model = preprocessing.StandardScaler() | linear_model.LogisticRegression()
    auc = metrics.ROCAUC()
    hits = n = 0
    for i, r in enumerate(rows):
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


SESSIONS = ("asia", "london", "overlap", "us")
print(f"{'features':<38} {'n':>6} {'right':>8} {'AUC':>7}")
print("-" * 62)
base_acc, _, base_auc = score(("above",))
print(f"{'side alone':<38} {'':>6} {base_acc:>7.1%} {base_auc:>7.3f}")
for label, keys in (
    ("side + volume", ("above", "volume_ratio")),
    ("side + session", ("above", *SESSIONS)),
    ("side + momentum", ("above", "momentum_vol")),
    ("side + headroom", ("above", "headroom_vol")),
    ("side + all four", ("above", "volume_ratio", "momentum_vol", "headroom_vol", *SESSIONS)),
):
    got, n, auc = score(keys)
    mark = "  <-- better" if auc > base_auc + 0.005 else ""
    print(f"{label:<38} {n:>6} {got:>7.1%} {auc:>7.3f}{mark}")

print("\nheld rate by tercile, within (feed, interval) so it is not an instrument split")
print(f"  {'candidate':<16} {'cells':>6} {'positive':>9} {'median change':>15}")
cells = defaultdict(list)
for r in rows:
    cells[r["_cell"]].append(r)
for name in ("volume_ratio", "momentum_vol", "headroom_vol"):
    deltas = []
    for chunk in cells.values():
        if len(chunk) < 60:
            continue
        ordered = sorted(chunk, key=lambda r: r[name])
        half = len(ordered) // 2
        lo = sum(1 for r in ordered[:half] if r["_held"]) / half
        hi = sum(1 for r in ordered[half:] if r["_held"]) / (len(ordered) - half)
        deltas.append(hi - lo)
    if deltas:
        pos = sum(1 for d in deltas if d > 0)
        med = sorted(deltas)[len(deltas) // 2]
        print(f"  {name:<16} {len(deltas):>6} {pos:>8}/{len(deltas)} {100 * med:>+14.1f}pp")
