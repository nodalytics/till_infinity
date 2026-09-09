"""sweep-aware's own entries, under its exit and under ride's, with spread.

sweep-aware is the best live performer on this book (+104 in a day) and runs
the **third-worst exit policy** in the table `Ride` was built from - target at
1x the modelled push, no trail, measured at -0.041R against ride's +0.404R over
31,820 replayed touches.

So its edge looks like the entry filter, not the exit. The obvious change is to
give it ride's exit. The obvious change is also exactly what `Ride`'s docstring
warns against: *"the replay models no spread, which is precisely what sinks
fast entries live"* - and sweep-aware trades from 1m.

Its own 30 closes cannot settle it; only 14 carry a stop and a target. So this
replays **its entry rule** over the published call stream, which is 52,376
calls in 7 days, and walks 1m bars forward under both exits **with the spread
charged**.

## What is modelled and what is not

* **Entry** at the level, which is where it rests. Crossed at half the spread.
* **Exit** crossed at half the spread again, so a round trip pays one spread.
* **No slippage beyond the spread**, no commission, no overnight funding.
* **No queue position.** A resting entry is assumed filled when price touches
  the level, which flatters both policies equally and flatters the resting one
  more - `never filled` was 3.9% of its live attempts.
"""
from __future__ import annotations

import bisect
import json
import os
import sqlite3
import statistics as st
import time

MULTI = os.environ.get("MULTI_DB", "/app/.data/research/multi.db")
JOURNAL = "/app/.data/journal/journal.db"
DAYS = float(os.environ.get("DAYS", "7"))
#: How long a trade may run, in 1m bars.
HOLD = int(os.environ.get("HOLD", "1440"))
ENTRIES = ("1m", "3m", "5m", "15m", "30m")


def spreads(conn, since):
    """Median observed spread per feed, in basis points."""
    book: dict[str, list[float]] = {}
    for (ctx,) in conn.execute(
        "SELECT context FROM entries WHERE actor='structures' AND kind='decision' AND time>=?",
        (since,),
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("spread_bps"), (int, float)):
            if d["spread_bps"] > 0:
                book.setdefault(str(d.get("feed") or ""), []).append(float(d["spread_bps"]))
    return {f: st.median(xs) for f, xs in book.items() if len(xs) >= 5}


def entries_of(conn, since, settings):
    """Every call sweep-aware's rule would accept."""
    out, seen, refused = [], 0, {"interval": 0, "swept_often": 0, "in_front": 0}
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries WHERE actor='structures' AND kind='decision' AND time>=?",
        (since,),
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if not isinstance(d, dict) or not d.get("level"):
            continue
        seen += 1
        if str(d.get("interval")) not in ENTRIES:
            refused["interval"] += 1
            continue
        swept, swept_n = float(d.get("sweep_rate") or 0), float(d.get("sweep_n") or 0)
        if swept_n >= settings.sweep_min_history and swept >= settings.sweep_max_rate:
            refused["swept_often"] += 1
            continue
        risk_vol = abs(float(d.get("risk_vol") or 0))
        beyond = float(d.get("liquidity_beyond_vol") or 0)
        if beyond > 0 and risk_vol / beyond >= settings.sweep_max_exposure:
            refused["in_front"] += 1
            continue
        direction = str(d.get("direction") or "")
        if direction not in ("up", "down"):
            continue
        out.append(
            {
                "when": float(when),
                "feed": str(d.get("feed") or ""),
                "interval": str(d.get("interval")),
                "up": direction == "up",
                "level": float(d["level"]),
                "unit": float(d["level"]) * float(d.get("vol_bps") or 0) / 10_000.0,
                "risk_vol": max(risk_vol, settings.min_stop_vol),
                "push_vol": abs(float(d.get("expected_push_vol") or 0)),
            }
        )
    return out, seen, refused


def bars_for(conn, feed):
    venue = conn.execute(
        "SELECT venue, COUNT(*) n FROM bars WHERE feed=? GROUP BY venue ORDER BY n DESC LIMIT 1",
        (feed,),
    ).fetchone()
    if not venue:
        return [], []
    rows = conn.execute(
        "SELECT ts, high, low, close FROM bars WHERE feed=? AND venue=? ORDER BY ts",
        (feed, venue[0]),
    ).fetchall()
    return rows, [r[0] for r in rows]


def walk(rows, start, trade, target_mult, trail_vol, protect_r, cost):
    """R multiple under one exit policy, or None if the window ran out."""
    up, unit = trade["up"], trade["unit"]
    if unit <= 0 or trade["push_vol"] <= 0:
        return None
    risk = trade["risk_vol"] * unit
    entry = trade["level"] + (cost / 2 if up else -cost / 2)
    stop = entry - risk if up else entry + risk
    target = entry + trade["push_vol"] * target_mult * unit * (1 if up else -1)
    best = entry
    for i in range(start, min(start + HOLD, len(rows))):
        _ts, high, low, close = rows[i]
        if high is None or low is None:
            continue
        best = max(best, high) if up else min(best, low)
        if protect_r and ((best - entry) if up else (entry - best)) >= protect_r * risk:
            stop = max(stop, entry) if up else min(stop, entry)
        if trail_vol:
            pull = best - trail_vol * unit if up else best + trail_vol * unit
            stop = max(stop, pull) if up else min(stop, pull)
        hit_stop = low <= stop if up else high >= stop
        hit_target = high >= target if up else low <= target
        if hit_stop and hit_target:
            hit_target = False          # assume the worse order within the bar
        if hit_stop:
            out = stop - (cost / 2 if up else -cost / 2)
            return ((out - entry) if up else (entry - out)) / risk
        if hit_target:
            out = target - (cost / 2 if up else -cost / 2)
            return ((out - entry) if up else (entry - out)) / risk
    if start < len(rows):
        last = rows[min(start + HOLD, len(rows)) - 1][3]
        out = last - (cost / 2 if up else -cost / 2)
        return ((out - entry) if up else (entry - out)) / risk
    return None


def run():
    from till_infinity.trading.config import Settings

    settings = Settings.from_env()
    now = time.time()
    since = now - DAYS * 86400
    jn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=180.0)
    spread = spreads(jn, since)
    trades, seen, refused = entries_of(jn, since, settings)
    print(f"{seen} published calls, {len(trades)} pass sweep-aware's rule")
    print(f"  refused: {refused}")
    print(f"  spread known for {len(spread)} feeds "
          f"(median {st.median(list(spread.values())) if spread else float('nan'):.3f}bps)\n")

    conn = sqlite3.connect(f"file:{MULTI}?mode=ro", uri=True, timeout=180.0)
    by_feed: dict[str, list] = {}
    for t in trades:
        by_feed.setdefault(t["feed"], []).append(t)

    results = {"its own exit": [], "ride's exit": [], "no spread, its own": []}
    missing = 0
    for feed, part in by_feed.items():
        rows, stamps = bars_for(conn, feed)
        if len(rows) < 500:
            missing += len(part)
            continue
        bps = spread.get(feed)
        for t in part:
            start = bisect.bisect_left(stamps, t["when"])
            if start >= len(rows) - 10:
                continue
            cost = t["level"] * (bps or 0.0) / 10_000.0
            a = walk(rows, start, t, 1.0, 0.0, 0.0, cost)
            b = walk(rows, start, t, 6.0, 0.5, 1.0, cost)
            c = walk(rows, start, t, 1.0, 0.0, 0.0, 0.0)
            if a is not None and b is not None:
                results["its own exit"].append(a)
                results["ride's exit"].append(b)
                results["no spread, its own"].append(c)
    print(f"{len(results['its own exit'])} replayed, {missing} skipped for want of bars\n")
    print(f"  {'policy':22s} {'n':>6s} {'mean R':>9s} {'median':>9s} {'win':>7s}")
    for name, rs in results.items():
        if len(rs) < 30:
            continue
        print(f"  {name:22s} {len(rs):6d} {st.fmean(rs):+9.3f} {st.median(rs):+9.3f} "
              f"{sum(1 for r in rs if r > 0)/len(rs):6.1%}")
    a, b = results["its own exit"], results["ride's exit"]
    if len(a) >= 30:
        paired = [y - x for x, y in zip(a, b)]
        print(f"\n  paired difference (ride minus its own): mean {st.fmean(paired):+.3f}R, "
              f"median {st.median(paired):+.3f}R, better on "
              f"{sum(1 for d in paired if d > 0)/len(paired):.1%} of the same trades")


if __name__ == "__main__":
    run()
