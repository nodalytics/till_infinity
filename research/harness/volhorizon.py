"""Is the learner losing, or is it being asked the wrong question?

`volmodel.py` scores every forecaster against **the next single bar's** realised
volatility, and on real bars the winner is `naive` - reuse the last value.

That result is suspicious in a specific way. One bar's realised volatility is a
very noisy draw around a slowly-moving scale, and volatility clustering means
consecutive draws are *correlated noise*. A forecaster that simply repeats the
last draw therefore scores well by tracking the noise, and a smoothed estimate
is penalised for not reproducing it.

Nothing downstream wants the next print. A stop is placed for the next hour, a
target for the next session, and `vol_bps` - the number every threshold in the
package divides by - is itself a smoothed quantity. So the honest question is
whether the forecasters beat persistence on the horizon that is actually used.

This scores all three against the mean realised volatility over the next **k**
bars, for k in 1, 5, 10, 20, on the same replay and the same bars.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections import deque

sys.path.insert(0, "/app")

from till_infinity.structures.context import sessions  # noqa: E402
from till_infinity.structures.vol.consensus_vol import MAD_TO_SIGMA, Score  # noqa: E402
from till_infinity.structures.vol.volatility import Book  # noqa: E402

DB = os.environ.get("PRICES", "/app/.data/prices/prices.db")
INTERVALS = tuple(os.environ.get("INTERVALS", "5m,15m,1h").split(","))
LIMIT = int(os.environ.get("LIMIT", "250000"))
#: Bars to skip first. The point of the exercise is a **disjoint** window: the
#: k=20 result that made the learner interesting came from the first 250,000
#: bars, and one win out of twelve comparisons is exactly the arithmetic that
#: produces a false positive. A second window is what tells them apart.
OFFSET = int(os.environ.get("OFFSET", "0"))
#: Restrict to a fixed instrument universe. **Required for a split-sample test
#: to mean anything.** The first attempt at one took the next 250,000 bars by
#: timestamp and compared them with the first 250,000, which changed the feed
#: count from 42 to 364 and the span from seven months to seven days: the two
#: halves were different instrument universes over different horizons, so the
#: forecasters were being compared on two unrelated problems and the result
#: read as a period effect. Holding the feeds and intervals fixed and splitting
#: on time is what makes the halves comparable.
FEEDS = tuple(f for f in os.environ.get("FEEDS", "").split(",") if f)
#: Which half of the (filtered, time-ordered) bars to use: "first", "second",
#: or empty for all of them.
HALF = os.environ.get("HALF", "")
HORIZONS = (1, 5, 10, 20)
SECONDS = {"1m": 60.0, "5m": 300.0, "15m": 900.0, "30m": 1800.0, "1h": 3600.0}


def run() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=300.0)
    marks = ",".join("?" for _ in INTERVALS)
    where = f"interval IN ({marks})"
    args: list = list(INTERVALS)
    if FEEDS:
        where += f" AND feed IN ({','.join('?' for _ in FEEDS)})"
        args += list(FEEDS)
    rows = conn.execute(
        f"SELECT feed, interval, ts, open, high, low, close, volume FROM bars "
        f"WHERE {where} ORDER BY ts ASC LIMIT ? OFFSET ?",
        (*args, LIMIT, OFFSET),
    ).fetchall()
    if HALF:
        cut = len(rows) // 2
        rows = rows[:cut] if HALF == "first" else rows[cut:]
    import datetime as _dt

    if rows:
        def _when(t):
            return _dt.datetime.utcfromtimestamp(t / 1000 if t > 1e11 else t)

        lo, hi = _when(min(r[2] for r in rows)), _when(max(r[2] for r in rows))
        print(
            f"{len(rows):,} bars interleaved in time, "
            f"{len({r[0] for r in rows})} feeds, {lo:%Y-%m-%d} .. {hi:%Y-%m-%d}\n"
        )

    book = Book()
    clock = sessions.Clock()
    # Per series: forecasts still waiting for their horizon to fill.
    pending: dict[tuple, deque] = {}
    scores: dict[tuple[int, str], Score] = {}
    counts: dict[int, int] = {}

    for feed, interval, ts, open_, high, low, close, volume in rows:
        if not all(isinstance(v, int | float) and v > 0 for v in (open_, high, low, close)):
            continue
        when = float(ts) / 1000.0 if ts > 10_000_000_000 else float(ts)
        key = (feed, interval)
        vol = book.of(feed, interval)
        vol.update(float(close))
        realised = vol.observe_bar(float(open_), float(high), float(low), float(close))
        if not realised or realised <= 0:
            continue

        # Every forecast still waiting sees this bar as one more of its future.
        queue = pending.setdefault(key, deque())
        for item in queue:
            item["seen"] += 1
            item["total"] += realised
        # Snapshot **before** popping. Taking it afterwards left the longest
        # horizon permanently unset - the item reaching `seen == max` was
        # removed in the same pass that would have recorded it, so k=20 scored
        # zero observations and silently reported nothing.
        for item in queue:
            for k in HORIZONS:
                if item["seen"] == k:
                    item["at"][k] = item["total"] / k
        while queue and queue[0]["seen"] >= max(HORIZONS):
            done = queue.popleft()
            for k in HORIZONS:
                actual = done["at"][k]
                if actual <= 0:
                    continue
                counts[k] = counts.get(k, 0) + 1
                for name, said in done["said"].items():
                    if said > 0:
                        scores.setdefault((k, name), Score()).record(said, actual)

        try:
            _, share = clock.volatility(feed, when)
        except Exception:
            share = 1.0
        book.learn(
            feed, interval, realised,
            open_=float(open_), high=float(high), low=float(low), close=float(close),
            hour=float(sessions.hour_of(when)), hour_share=share,
            volume=float(volume) if isinstance(volume, int | float) and volume > 0 else 0.0,
            interval_seconds=SECONDS.get(interval, 0.0),
        )
        learned = book.learned
        said = learned._by_key.get(f"{feed}|{interval}")
        if said is not None and said.said:
            queue.append({
                "seen": 0, "total": 0.0, "at": dict.fromkeys(HORIZONS, 0.0),
                "said": {
                    "naive": float(said.said.get("naive") or 0.0),
                    "har": float(said.said.get("har") or 0.0),
                    "learned": float(said.said.get("learned") or 0.0),
                },
            })

    print(f"{'horizon':>8s} {'scored':>10s}  " + "  ".join(f"{n:>9s}" for n in ("naive", "har", "learned")))
    for k in HORIZONS:
        row = []
        for name in ("naive", "har", "learned"):
            got = scores.get((k, name))
            row.append(f"{got.accuracy:9.4f}" if got and got.warm else f"{'-':>9s}")
        print(f"{k:>8d} {counts.get(k, 0):>10,}  " + "  ".join(row))

    print("\nwinner by horizon:")
    for k in HORIZONS:
        table = {
            n: scores[(k, n)].accuracy
            for n in ("naive", "har", "learned")
            if (k, n) in scores and scores[(k, n)].warm
        }
        if not table:
            continue
        best = max(table, key=table.get)
        gap = table[best] - max(v for n, v in table.items() if n != best)
        print(f"  k={k:<3d} {best:8s} by {gap:+.4f}")


if __name__ == "__main__":
    run()
