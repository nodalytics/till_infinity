"""Does the learned volatility forecaster beat the line it is meant to replace?

`vol/learned.py` is one online regressor over the whole book, forecasting the
next bar's realised volatility as a log correction to the standing estimate.
The argument for it is that `har.py` is linear over three lagged magnitudes and
cannot express an interaction between magnitude and candle shape.

An argument is not a measurement, and this package has a standing rule about
that: every threshold divides by one volatility number, and nothing replaces it
on reasoning. So this replays **real bars** through the production objects, in
production order, and asks the only question that matters:

    naive < har < learned ?

`naive` - the last realised value - is the floor. A forecaster that cannot beat
persistence has not earned the CPU whatever else it beats.

Ordering is the part that decides whether this measures anything. Bars are read
across every series and replayed **interleaved in time**, exactly as the live
bus delivers them, because the model is pooled: feeding it one instrument to
completion and then the next would let it learn eurusd, forget it while
learning gold, and be scored on the forgetting.
"""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, "/app")

from till_infinity.structures.context import sessions  # noqa: E402
from till_infinity.structures.vol.volatility import Book  # noqa: E402

DB = os.environ.get("PRICES", "/app/.data/prices/prices.db")
INTERVALS = tuple(os.environ.get("INTERVALS", "5m,15m,1h").split(","))
LIMIT = int(os.environ.get("LIMIT", "400000"))


def run() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=300.0)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(bars)")]
    print(f"bars columns: {cols}\n")

    marks = ",".join("?" for _ in INTERVALS)
    rows = conn.execute(
        f"SELECT feed, interval, ts, open, high, low, close, volume FROM bars "
        f"WHERE interval IN ({marks}) ORDER BY ts ASC LIMIT ?",
        (*INTERVALS, LIMIT),
    ).fetchall()
    print(f"{len(rows):,} bars, interleaved in time, over {len(INTERVALS)} interval(s)")
    feeds = {r[0] for r in rows}
    print(f"{len(feeds)} feed(s)\n")

    book = Book()
    clock = sessions.Clock()
    seen = {}
    used = 0
    for feed, interval, ts, open_, high, low, close, volume in rows:
        if not all(isinstance(v, int | float) and v > 0 for v in (open_, high, low, close)):
            continue
        when = float(ts) / 1000.0 if ts > 10_000_000_000 else float(ts)
        vol = book.of(feed, interval)
        vol.update(float(close))
        realised = vol.observe_bar(float(open_), float(high), float(low), float(close))
        if not realised or realised <= 0:
            continue
        try:
            _, share = clock.volatility(feed, when)
        except Exception:
            share = 1.0
        book.learn(
            feed,
            interval,
            realised,
            open_=float(open_),
            high=float(high),
            low=float(low),
            close=float(close),
            hour=float(sessions.hour_of(when)),
            hour_share=share,
            volume=float(volume) if isinstance(volume, int | float) and volume > 0 else 0.0,
            interval_seconds={"5m": 300.0, "15m": 900.0, "1h": 3600.0}.get(interval, 0.0),
        )
        used += 1
        seen[(feed, interval)] = seen.get((feed, interval), 0) + 1

    learned = book.learned
    print(f"{used:,} bars folded in, {len(seen)} series, {learned._seen:,} learning pairs\n")
    standings = learned.standings()
    if not standings:
        print("cold - no member is warm yet")
        return
    print(f"{'member':10s} {'accuracy':>10s}   (1 - symmetric relative error, larger is better)")
    for name, value in standings:
        print(f"  {name:8s} {value:10.4f}")

    table = dict(standings)
    print()
    if "learned" in table and "naive" in table:
        gap = table["learned"] - table["naive"]
        print(f"learned vs naive: {gap:+.4f}  ->  {'BEATS' if gap > 0 else 'LOSES TO'} persistence")
    if "learned" in table and "har" in table:
        gap = table["learned"] - table["har"]
        print(f"learned vs har:   {gap:+.4f}  ->  {'BEATS' if gap > 0 else 'LOSES TO'} the line")


if __name__ == "__main__":
    run()
