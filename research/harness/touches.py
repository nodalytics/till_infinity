"""Replay once, cache the resolved touches, so the model comparisons are cheap."""

import pickle
import sqlite3
from pathlib import Path

CACHE = Path(__file__).with_name("touches.pkl")
INTERVALS = ("1m", "5m", "15m", "1h")
FIELDS = (
    "approach_vol",
    "depth_vol",
    "strength",
    "run_vol",
    "experience",
    "pivot",
    "backcheck",
    "regime",
)


def _bars():
    from till_infinity.prices.config import FEEDS

    owner = {}
    for name, feed in FEEDS.items():
        for group in feed.symbols.values():
            for sym in group:
                owner[(sym.venue.upper(), sym.ticker.upper())] = name
    conn = sqlite3.connect("file:.data/prices/prices.db?mode=ro", uri=True)
    marks = ",".join("?" * len(INTERVALS))
    for ts, ticker, venue, interval, high, low, close, volume in conn.execute(
        f"select ts, ticker, venue, interval, high, low, close, volume from bars"
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
                # Not consumed by the engine, which ignores it — carried so
                # experiments can ask whether volume at a touch says anything.
                "volume": float(volume) if volume is not None else 0.0,
            }


def load():
    """Per touch, in time order:

    (numeric features, went_up, feed, interval, resolved, raw features, push_vol)
    """
    if CACHE.exists():
        return pickle.loads(CACHE.read_bytes())

    from till_infinity.structures.engine import Engine

    engine = Engine(intervals=INTERVALS)
    rows = []
    for bar in _bars():
        engine.observe_bar(bar)
        for _level, touch in engine.drain_resolved():
            if not touch.push_vol:
                continue
            x = {f: float(getattr(touch.features, f)) for f in FIELDS}
            x["above"] = 1.0 if touch.features.side.name == "ABOVE" else 0.0
            # `facto` takes the raw shape, with the side and interval as names
            # for it to one-hot itself, plus the target it was built to
            # regress: the realised push rather than its direction.
            raw = {
                **{f: float(getattr(touch.features, f)) for f in FIELDS},
                "side": str(touch.features.side),
                "interval": touch.interval,
            }
            rows.append(
                (
                    x,
                    touch.push_vol > 0,
                    touch.feed,
                    touch.interval,
                    touch.resolved,
                    raw,
                    float(touch.push_vol),
                )
            )
    rows.sort(key=lambda r: r[4])
    CACHE.write_bytes(pickle.dumps(rows))
    return rows


if __name__ == "__main__":
    rows = load()
    print(f"cached {len(rows):,} resolved touches with a direction")
    print(f"share going up: {sum(1 for r in rows if r[1]) / len(rows):.1%}")
