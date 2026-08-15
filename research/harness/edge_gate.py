"""Is 0.08 the right place to put the gate, and should it be a constant at all?

`|edge| >= 0.08` decides whether a level call is said out loud. `edge` is
`probability_up - base_rate_up`: how far the conditional sits from the
unconditional, in probability. The number was never derived from anything.

Deriving it was tried before and failed, for a reason worth repeating: on
pre-fix data the direction was called correctly 99.9% of the time at *every*
level of |edge|, because inflated touch counts made a level's history and its
next outcome the same move counted twice. A gate cannot be placed on a
measurement that says everything works.

So this runs in four steps and the first is a gate on the other three:

  0. is the data still degenerate? if direction accuracy is near 100%, stop.
  1. where does 0.08 sit in the distribution of |edge| it is applied to?
  2. does |edge| separate outcomes at all — bigger edge, better call?
  3. fixed constant against a causal rolling quantile, on the same calls.

Bars only. Production also drives touches from quotes, so this is the level
machinery rather than the whole system, and the counts here are not the
production rate.
"""

import sqlite3
import sys
from collections import defaultdict

from till_infinity.prices.config import FEEDS
from till_infinity.structures.engine import Engine

DB = ".data/prices/prices.db"  # run from the repository root
INTERVALS = ("1m", "5m", "15m", "1h")
GATE = 0.08


def bars(intervals):
    owner = {}
    for name, feed in FEEDS.items():
        for group in feed.symbols.values():
            for sym in group:
                owner[(sym.venue.upper(), sym.ticker.upper())] = name

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    marks = ",".join("?" * len(intervals))
    rows = conn.execute(
        f"select ts, ticker, venue, interval, high, low, close from bars"
        f" where interval in ({marks}) order by ts",
        intervals,
    )
    for ts, ticker, venue, interval, high, low, close in rows:
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


def key(feed, interval, price, when):
    return (feed, interval, round(price, 8), when)


def collect():
    """Replay, pairing every call with the outcome of the touch it opened."""
    engine = Engine(intervals=INTERVALS)
    edges: dict[tuple, dict] = {}
    paired: list[dict] = []
    seen = 0

    for bar in bars(INTERVALS):
        calls = engine.observe_bar(bar)
        seen += 1
        for call in calls:
            touch = engine.tracker.open_touch(call.level)
            if touch is None or touch.started != call.time:
                continue
            edges[key(call.feed, call.interval, touch.level_price, touch.started)] = {
                "edge": call.inference.edge,
                "expected_push": call.inference.expected_push,
                "own_touches": call.inference.own_touches,
                "neighbours": call.inference.neighbours,
                "base_rate_up": call.inference.base_rate_up,
                "feed": call.feed,
                "interval": call.interval,
                "when": touch.started,
            }
        # Drain as we go, so `_resolved` never hits its cap and drops pairs.
        for _level, touch in engine.drain_resolved():
            found = edges.pop(
                key(touch.feed, touch.interval, touch.level_price, touch.started), None
            )
            if found is None:
                continue
            found["push_vol"] = touch.push_vol
            found["outcome"] = str(touch.outcome).split(".")[-1].lower()
            paired.append(found)

    return paired, seen, len(edges)


def hit(row):
    """Did the direction the edge claimed actually happen?"""
    if not row["edge"] or not row["push_vol"]:
        return None
    return (row["edge"] > 0) == (row["push_vol"] > 0)


def rate(rows):
    calls = [hit(r) for r in rows]
    decided = [c for c in calls if c is not None]
    return (sum(decided) / len(decided) if decided else 0.0), len(decided)


def quantiles(values, points):
    ordered = sorted(values)
    return [ordered[min(int(p * len(ordered)), len(ordered) - 1)] for p in points]


def main():  # noqa: PLR0915 - a report, and splitting it would hide the order
    paired, seen, unresolved = collect()
    print(f"bars replayed        : {seen:,}")
    print(f"calls paired         : {len(paired):,}   (unresolved at the end: {unresolved:,})")
    if len(paired) < 200:
        print("\nToo few paired calls to say anything. Stopping.")
        return

    # ---- 0. is the data still degenerate?
    overall, decided = rate(paired)
    print(f"\n=== 0. sanity: direction called correctly {overall:.1%} of {decided:,} decided")
    if overall > 0.95:
        print("    Still degenerate — a gate cannot be placed on this. Stopping.")
        return
    print("    Plausible, so the rest of this means something.")

    edges = [abs(r["edge"]) for r in paired]
    below = sum(1 for e in edges if e < GATE) / len(edges)
    print(f"\n=== 1. where {GATE} sits")
    print(f"    {below:.1%} of calls fall below it, so it passes {1 - below:.1%}")
    ps = [0.5, 0.75, 0.9, 0.95, 0.975, 0.99]
    for p, v in zip(ps, quantiles(edges, ps), strict=True):
        print(f"    p{p * 100:<5g} of |edge| = {v:.4f}")

    # ---- 2. does a bigger edge mean a better call?
    print("\n=== 2. outcome by |edge| decile")
    print(f"    {'decile':<8} {'|edge| from':>12} {'n':>6} {'direction':>10} {'mean push':>10}")
    ordered = sorted(paired, key=lambda r: abs(r["edge"]))
    size = len(ordered) // 10
    for d in range(10):
        chunk = ordered[d * size : (d + 1) * size] if d < 9 else ordered[9 * size :]
        if not chunk:
            continue
        got, n = rate(chunk)
        pushed = [abs(r["push_vol"]) * (1 if hit(r) else -1) for r in chunk if hit(r) is not None]
        mean = sum(pushed) / len(pushed) if pushed else 0.0
        print(f"    {d + 1:<8} {abs(chunk[0]['edge']):>12.4f} {n:>6} {got:>9.1%} {mean:>10.2f}")

    # ---- 3. thresholds
    print("\n=== 3. what each threshold would pass")
    print(f"    {'threshold':>10} {'passed':>8} {'share':>7} {'direction':>10} {'mean push':>10}")
    for t in (0.0, 0.02, 0.04, 0.06, GATE, 0.10, 0.14, 0.20, 0.30):
        kept = [r for r in paired if abs(r["edge"]) >= t]
        if not kept:
            continue
        got, n = rate(kept)
        pushed = [abs(r["push_vol"]) * (1 if hit(r) else -1) for r in kept if hit(r) is not None]
        mean = sum(pushed) / len(pushed) if pushed else 0.0
        mark = "  <- current" if t == GATE else ""
        print(
            f"    {t:>10.2f} {len(kept):>8} {len(kept) / len(paired):>6.1%}"
            f" {got:>9.1%} {mean:>10.2f}{mark}"
        )

    # ---- 4. constant against a causal rolling quantile
    print("\n=== 4. a rolling quantile per (feed, interval), causal")
    history: dict[tuple, list] = defaultdict(list)
    for q in (0.80, 0.90, 0.95):
        kept, warm = [], 0
        for row in sorted(paired, key=lambda r: r["when"]):
            past = history[(row["feed"], row["interval"])]
            if len(past) >= 50:
                threshold = quantiles(past[-500:], [q])[0]
                if abs(row["edge"]) >= threshold:
                    kept.append(row)
            else:
                warm += 1
            past.append(abs(row["edge"]))
        history.clear()
        if not kept:
            print(f"    q{q:.2f}: nothing passed")
            continue
        got, n = rate(kept)
        pushed = [abs(r["push_vol"]) * (1 if hit(r) else -1) for r in kept if hit(r) is not None]
        mean = sum(pushed) / len(pushed) if pushed else 0.0
        print(
            f"    q{q:.2f}: passed {len(kept):>5} ({len(kept) / len(paired):.1%}),"
            f" direction {got:.1%}, mean push {mean:.2f}   [{warm} still warming]"
        )

    fixed = [r for r in paired if abs(r["edge"]) >= GATE]
    got, _ = rate(fixed)
    print(
        f"\n    fixed {GATE}: passed {len(fixed)}"
        f" ({len(fixed) / len(paired):.1%}), direction {got:.1%}"
    )

    print("\n=== per (feed, interval), what the fixed gate does")
    print(f"    {'cell':<18} {'calls':>6} {'passed':>7} {'share':>7} {'p90 |edge|':>11}")
    cells = defaultdict(list)
    for row in paired:
        cells[(row["feed"], row["interval"])].append(row)
    for cell, rows in sorted(cells.items(), key=lambda kv: -len(kv[1]))[:12]:
        passed = sum(1 for r in rows if abs(r["edge"]) >= GATE)
        p90 = quantiles([abs(r["edge"]) for r in rows], [0.9])[0]
        print(
            f"    {cell[0] + ' ' + cell[1]:<18} {len(rows):>6} {passed:>7}"
            f" {passed / len(rows):>6.1%} {p90:>11.4f}"
        )


if __name__ == "__main__":
    sys.exit(main())
