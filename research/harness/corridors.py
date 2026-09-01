"""The barrier trade, measured on replayed history rather than live touches.

research/barriers.md measured this on 1,391 setups drawn from journalled level
calls - and the higher timeframes were thin because resolutions accumulate only
as the desk runs: 46 setups at 1h, 17 at 4h. Boundaries were moved on those
numbers, which is thinner than it should be.

The candles were never the constraint. The store holds 1,884 4h bars per feed
back to 2024 and 1,318 weekly bars back to 2020. This replays them through the
same engine production runs, captures the corridor at each touch, and walks the
bars forward for the barrier outcome.

Two passes, because they need different things: the replay is sequential and
the barrier walk needs bars *after* the touch.
"""

from __future__ import annotations

import pickle
import sqlite3
import statistics as st
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path

INTERVALS = ("1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d")
CACHE = Path(__file__).with_name("corridors.pkl")

#: How close to a level a touch has to be for the corridor to be the trade.
AT_VOL = 0.5
#: The stop, back through the level that was touched, in volatility units.
STOP_VOL = 1.0
#: The vertical barrier per interval, from what each style is allowed to hold.
HORIZON = {
    "1m": 1800.0,
    "5m": 1800.0,
    "15m": 1800.0,
    "30m": 1800.0,
    "1h": 21600.0,
    "2h": 21600.0,
    "4h": 21600.0,
    "1d": 21600.0,
}


def bars():
    from till_infinity.prices.config import FEEDS

    owner = {}
    for name, feed in FEEDS.items():
        for group in feed.symbols.values():
            for sym in group:
                owner[(sym.venue.upper(), sym.ticker.upper())] = name
    conn = sqlite3.connect("file:.data/prices/prices.db?mode=ro", uri=True)
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


def setups() -> list[dict]:
    """Replay once, and capture the corridor each touch sat in."""
    if CACHE.exists():
        return pickle.loads(CACHE.read_bytes())

    from till_infinity.structures.engine import Engine

    engine = Engine(intervals=INTERVALS)
    out = []
    for bar in bars():
        engine.observe_bar(bar)
        for _level, touch in engine.drain_resolved():
            feed, interval = touch.feed, touch.interval
            vol = engine.vol.of(feed, interval)
            if not vol.warm or vol.bps <= 0:
                continue
            price = touch.level_price
            unit = abs(price * vol.bps / 10_000)
            if unit <= 0:
                continue
            # The nearest level either side, which is the corridor.
            near = [x.price for x in engine.levels(feed, interval) if abs(x.price - price) > unit]
            above = min((p for p in near if p > price), default=None)
            below = max((p for p in near if p < price), default=None)
            if above is None or below is None:
                continue
            # Price has to be standing at one end for the corridor to be a trade.
            at_top = abs(above - price) < abs(price - below)
            entry, target = (above, below) if at_top else (below, above)
            if abs(entry - price) / unit > AT_VOL:
                continue
            out.append(
                {
                    "feed": feed,
                    "interval": interval,
                    "when": float(touch.started),
                    "entry": entry,
                    "target": target,
                    "short": at_top,
                    "unit": unit,
                    "corridor": abs(above - below) / unit,
                }
            )
    CACHE.write_bytes(pickle.dumps(out))
    return out


def series(wanted, since):
    conn = sqlite3.connect("file:.data/prices/prices.db?mode=ro", uri=True)
    held = defaultdict(lambda: ([], [], []))
    for feed, interval, ts, high, low in conn.execute(
        "select feed, interval, ts, high, low from bars where ts >= ? order by ts asc",
        (since,),
    ):
        key = (str(feed), str(interval))
        if key not in wanted:
            continue
        times, highs, lows = held[key]
        times.append(float(ts))
        highs.append(float(high))
        lows.append(float(low))
    return held


def outcome(s, times, highs, lows, start) -> str:
    limit = HORIZON.get(s["interval"], 1800.0)
    stop = s["entry"] + (STOP_VOL * s["unit"] if s["short"] else -STOP_VOL * s["unit"])
    for i in range(start, len(times)):
        if times[i] - s["when"] > limit:
            break
        if s["short"]:
            if lows[i] <= s["target"]:
                return "far"
            if highs[i] >= stop:
                return "back"
        elif highs[i] >= s["target"]:
            return "far"
        elif lows[i] <= stop:
            return "back"
    return "neither"


def main() -> None:
    got = setups()
    print(f"{len(got)} setups from the replay\n")
    if not got:
        return
    bars_by = series({(s["feed"], s["interval"]) for s in got}, min(s["when"] for s in got) - 3600)

    per = defaultdict(Counter)
    widths = defaultdict(list)
    for s in got:
        held = bars_by.get((s["feed"], s["interval"]))
        if not held:
            continue
        times, highs, lows = held
        per[s["interval"]][outcome(s, times, highs, lows, bisect_left(times, s["when"]))] += 1
        widths[s["interval"]].append(s["corridor"])

    print(f"{'interval':9s} {'n':>7s} {'far':>8s} {'back':>8s} {'neither':>9s} {'corridor':>9s}")
    for iv in INTERVALS:
        row = per.get(iv)
        if not row:
            continue
        n = sum(row.values())
        if n < 30:
            continue
        w = st.median(widths[iv]) if widths[iv] else 0.0
        print(
            f"{iv:9s} {n:7d} {row['far'] / n:8.1%} {row['back'] / n:8.1%}"
            f" {row['neither'] / n:9.1%} {w:8.1f}v"
        )
    total = Counter()
    for row in per.values():
        total.update(row)
    n = sum(total.values())
    if n:
        print(
            f"\npooled  n={n}  far {total['far'] / n:.1%}  back {total['back'] / n:.1%}"
            f"  neither {total['neither'] / n:.1%}"
        )


main()
