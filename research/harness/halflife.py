"""Does a shorter volatility half-life make the *calls* better?

[volatility.md](../volatility.md) found `HALF_LIFE = 60` well past the optimum
for forecasting the next move — 7 to 10 wins at every interval — and stopped
there deliberately. The forecast is not what the estimate is for. Levels,
touches and directional calls are, and the downstream effect measured in counts
(3% more touches, 14% fewer levels) cannot say whether any of it got better.

This runs the same pairing `edge_gate.py` does — every call matched to the
outcome of the touch it opened — at each half-life, and scores what actually
matters:

  direction   how often the sign of `edge` matched the realised push
  holds       the trivial rule from features.md, which the model has never beaten
  push        realised push in volatility units, signed positive when right
  separation  direction above |edge| 0.20 minus direction below 0.11, which is
              what a gate actually consumes
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sqlite3

from till_infinity.prices.config import FEEDS
from till_infinity.structures.engine import Engine
from till_infinity.structures.volatility import Book as VolBook

DB = ".data/prices/prices.db"
INTERVALS = ("1m", "5m", "15m", "1h")


def bars():
    owner = {}
    for name, feed in FEEDS.items():
        for group in feed.symbols.values():
            for sym in group:
                owner[(sym.venue.upper(), sym.ticker.upper())] = name
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
                "feed": feed, "venue": venue, "interval": interval, "time": int(ts),
                "high": float(high), "low": float(low), "close": float(close),
            }


def collect(half_life: float) -> list[dict]:
    """Every call paired with the outcome of the touch it opened."""
    engine = Engine(intervals=INTERVALS)
    engine.vol = VolBook(half_life=half_life)
    assert engine.vol.of("probe", "5m").half_life == half_life
    open_calls: dict[tuple, dict] = {}
    paired: list[dict] = []
    for bar in bars():
        for call in engine.observe_bar(bar):
            touch = engine.tracker.open_touch(call.level)
            if touch is None or touch.started != call.time:
                continue
            open_calls[
                (call.feed, call.interval, round(touch.level_price, 8), touch.started)
            ] = {
                "edge": call.inference.edge,
                "above": touch.features.side.name == "ABOVE",
            }
        for _level, touch in engine.drain_resolved():
            found = open_calls.pop(
                (touch.feed, touch.interval, round(touch.level_price, 8), touch.started), None
            )
            if found is None or not touch.push_vol:
                continue
            found["push_vol"] = touch.push_vol
            paired.append(found)
    return paired


def score(rows, lo=0.0):
    kept = [r for r in rows if abs(r["edge"]) >= lo]
    decided = [r for r in kept if r["edge"] and r["push_vol"]]
    if not decided:
        return 0.0, 0.0, 0.0, 0
    right = sum(1 for r in decided if (r["edge"] > 0) == (r["push_vol"] > 0))
    holds = sum(1 for r in kept if r["above"] == (r["push_vol"] > 0))
    push = [
        abs(r["push_vol"]) * (1 if (r["edge"] > 0) == (r["push_vol"] > 0) else -1)
        for r in decided
    ]
    return right / len(decided), holds / len(kept), sum(push) / len(push), len(decided)


def main() -> None:
    print("%-10s %7s %10s %9s %8s %11s" % (
        "half_life", "calls", "direction", "holds", "push", "separation"))
    print("-" * 60)
    for half in (60.0, 20.0, 10.0, 7.0):
        rows = collect(half)
        direction, holds, push, n = score(rows)
        high, _, _, _ = score(rows, 0.20)
        low_rows = [r for r in rows if abs(r["edge"]) < 0.11]
        low = score(low_rows)[0] if low_rows else 0.0
        print("%-10g %7d %9.1f%% %8.1f%% %8.2f %10.1fpp" % (
            half, n, 100 * direction, 100 * holds, push, 100 * (high - low)))
    print("\n`holds` is 'assume the level holds' on the same rows. The model has")
    print("never beaten it (features.md 3); the question here is whether the gap")
    print("narrows. `separation` is what a gate consumes.")


if __name__ == "__main__":
    main()
