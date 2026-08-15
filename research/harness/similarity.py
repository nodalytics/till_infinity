"""Where does similarity stop carrying information?

`Memory.neighbours` returns the k nearest touches regardless of distance, so a
level with no comparable history still gets twelve neighbours — distant ones.
To replace that with a radius, the radius has to come from somewhere, and the
honest place is the data: at what `Features.distance` does a neighbour stop
predicting which way the touch under test went?

For every resolved touch, every *earlier* resolved touch on the same side is a
candidate neighbour. Agreement is whether the neighbour's realised direction
matched this touch's. Binned by distance, the point where agreement decays to
the base rate is where similarity stops being evidence.
"""

import math
import sys
from collections import defaultdict
from itertools import pairwise

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))

from till_infinity.prices.config import FEEDS
from till_infinity.structures.engine import Engine

DB = ".data/prices/prices.db"  # run from the repository root
INTERVALS = ("1m", "5m", "15m", "1h")


def bars():
    owner = {}
    for name, feed in FEEDS.items():
        for group in feed.symbols.values():
            for sym in group:
                owner[(sym.venue.upper(), sym.ticker.upper())] = name
    import sqlite3

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    marks = ",".join("?" * len(INTERVALS))
    for ts, ticker, venue, interval, high, low, close in conn.execute(
        f"select ts, ticker, venue, interval, high, low, close from bars"
        f" where interval in ({marks}) order by ts",
        INTERVALS,
    ):
        feed = owner.get((venue.upper(), ticker.upper()))
        if feed:
            yield {
                "feed": feed,
                "venue": venue,
                "interval": interval,
                "time": int(ts),
                "high": float(high),
                "low": float(low),
                "close": float(close),
            }


engine = Engine(intervals=INTERVALS)
touches = []
for bar in bars():
    engine.observe_bar(bar)
    for _level, touch in engine.drain_resolved():
        if touch.push_vol:
            touches.append(touch)

print(f"resolved touches with a direction: {len(touches):,}")
touches.sort(key=lambda t: t.resolved)

# Every earlier touch is a candidate. Bounded to the most recent 3,000, which is
# what `MEMORY` holds anyway.
BANDS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 1e9]
agree = defaultdict(lambda: [0, 0])
for i, touch in enumerate(touches):
    up = touch.push_vol > 0
    for other in touches[max(0, i - 3000) : i]:
        d = touch.features.distance(other.features)
        if math.isnan(d) or math.isinf(d):
            continue
        for lo, hi in pairwise(BANDS):
            if lo <= d < hi:
                cell = agree[(lo, hi)]
                cell[1] += 1
                cell[0] += (other.push_vol > 0) == up
                break

base = sum(1 for t in touches if t.push_vol > 0) / len(touches)
print(f"unconditional share going up: {base:.1%}")
print(f"\n{'distance':<14} {'pairs':>10} {'agreement':>10} {'lift':>8}")
print("-" * 46)
for lo, hi in pairwise(BANDS):
    hits, n = agree[(lo, hi)]
    if not n:
        continue
    rate = hits / n
    chance = base**2 + (1 - base) ** 2  # two draws agreeing by luck alone
    label = f"{lo:.2f}-{hi:.2f}" if hi < 1e8 else f"{lo:.2f}+"
    print(f"{label:<14} {n:>10,} {rate:>9.1%} {rate - chance:>+8.1%}")
print(f"\nagreement expected from chance alone: {base**2 + (1 - base) ** 2:.1%}")
