"""After touching one origin, does price travel to the other?

barriers.md measured the corridor and the typical move and inferred that the
far barrier is out of reach. Inference is not measurement. This walks the bars
forward from each touch and asks which barrier price actually hits first - the
triple-barrier label, taken rather than reasoned about.

Three outcomes per setup:

* **far**  - reached the opposite origin. The trade as designed.
* **back** - came back through the origin it touched, by a stop's width. The
  trade as it fails.
* **neither** - the vertical barrier expired first, which is `max_hold`.
"""

import json
import sqlite3
import statistics as st
from bisect import bisect_left
from collections import Counter, defaultdict

JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"
PRICES = "file:/app/.data/prices/prices.db?mode=ro"

#: The vertical barrier, in seconds, **per entry interval**.
#:
#: A flat 1,800 was wrong and produced a finding that was an artefact of it:
#: "at 1h the vertical barrier decides the trade 52.2% of the time". That is
#: the scalpers' ceiling. The strategies that actually trade 15m, 30m and 1h
#: ask for their own hold - `origin-swing` and `swing-level` take 21,600s, and
#: `runner`, `fade-to-value` and `approach-scalp` take 14,400s - so a 1h setup
#: in production gets four to six hours, not thirty minutes.
#:
#: Taken from what those strategies declare rather than from `max_hold`, which
#: is only the ceiling for a strategy that names no hold of its own.
HORIZON = {
    "1m": 1800.0,
    "3m": 1800.0,
    "5m": 1800.0,
    "15m": 14400.0,
    "30m": 14400.0,
    "1h": 14400.0,
    "2h": 21600.0,
    "4h": 21600.0,
}
DEFAULT_HORIZON = 1800.0

#: What a 48-72 hour hold on the higher timeframes would give, for comparison.
LONG = {
    "1m": 1800.0,
    "3m": 1800.0,
    "5m": 1800.0,
    "15m": 48 * 3600.0,
    "30m": 48 * 3600.0,
    "1h": 48 * 3600.0,
    "2h": 72 * 3600.0,
    "4h": 72 * 3600.0,
}
#: How far back through the entry origin counts as stopped, in volatility units.
STOP_VOL = 1.0
#: Only touches this close to an origin count as having arrived at it.
AT_VOL = 0.5


def setups() -> list[dict]:
    c = sqlite3.connect(JOURNAL, uri=True)
    out = []
    for when, blob in c.execute(
        "select time, context from entries where actor = ? and kind = ?"
        " order by time desc limit 400000",
        ("structures", "decision"),
    ):
        try:
            d = json.loads(blob or "{}")
        except (ValueError, TypeError):
            continue
        try:
            above, below = float(d["origin_above_low"]), float(d["origin_below_high"])
            level, vol = float(d["level"]), float(d.get("vol_bps") or 0)
            feed, interval = str(d["feed"]), str(d.get("interval") or "")
        except (KeyError, TypeError, ValueError):
            continue
        if above <= below or vol <= 0 or level <= 0 or not feed or not interval:
            continue
        unit = level * vol / 10_000
        if unit <= 0:
            continue
        # Which barrier is price at? It has to be at one to be a trade.
        near_above = abs(above - level) / unit
        near_below = abs(level - below) / unit
        if min(near_above, near_below) > AT_VOL:
            continue
        at_top = near_above < near_below
        out.append(
            {
                "when": float(when),
                "feed": feed,
                "interval": interval,
                "unit": unit,
                "entry": above if at_top else below,
                "target": below if at_top else above,
                "short": at_top,
            }
        )
    return out


def series(conn, wanted, since):
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


def main() -> None:
    got = setups()
    print(f"{len(got)} setups: price between two origins and standing at one\n")
    if not got:
        return
    prices = sqlite3.connect(PRICES, uri=True)
    floor = min(s["when"] for s in got) - 3600
    bars = series(prices, {(s["feed"], s["interval"]) for s in got}, floor)
    print(f"{len(bars)} series loaded")

    for horizon, name in ((HORIZON, "production holds"), (LONG, "48-72h holds")):
        walk(got, bars, horizon, name)


def walk(got, bars, horizon, title) -> None:
    print(f"\n=== {title} ===")
    label = Counter()
    per_interval = defaultdict(Counter)
    reached_after = []
    for s in got:
        held = bars.get((s["feed"], s["interval"]))
        if not held:
            label["no bars"] += 1
            continue
        times, highs, lows = held
        start = bisect_left(times, s["when"])
        stop = s["entry"] + (STOP_VOL * s["unit"] if s["short"] else -STOP_VOL * s["unit"])
        outcome = label_one(s, times, highs, lows, start, stop, horizon, reached_after)
        label[outcome] += 1
        per_interval[s["interval"]][outcome] += 1
    report(label, per_interval, reached_after)


def label_one(s, times, highs, lows, start, stop, horizon, reached_after) -> str:
    """Which barrier is hit first, or "neither" when the clock wins."""
    limit = horizon.get(s["interval"], DEFAULT_HORIZON)
    for i in range(start, len(times)):
        if times[i] - s["when"] > limit:
            break
        if s["short"]:
            if lows[i] <= s["target"]:
                reached_after.append(times[i] - s["when"])
                return "far"
            if highs[i] >= stop:
                return "back"
        else:
            if highs[i] >= s["target"]:
                reached_after.append(times[i] - s["when"])
                return "far"
            if lows[i] <= stop:
                return "back"
    return "neither"


def report(label, per_interval, reached_after) -> None:
    total = sum(v for k, v in label.items() if k != "no bars")
    print(f"which barrier first, over {total} judgeable setups:")
    for name in ("far", "back", "neither", "no bars"):
        n = label.get(name, 0)
        if n:
            share = f"{n / max(total, 1):6.1%}" if name != "no bars" else "      "
            print(f"   {name:9s} {n:6d} {share}")
    if reached_after:
        print(f"   reached the far origin after a median {st.median(reached_after):.0f}s")
    print("   by interval:")
    for iv in ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h"):
        row = per_interval.get(iv)
        if not row:
            continue
        n = sum(row.values())
        if n < 20:
            continue
        print(
            f"      {iv:4s} n={n:5d}   far {row['far'] / n:6.1%}"
            f"   back {row['back'] / n:6.1%}   neither {row['neither'] / n:6.1%}"
        )


main()
