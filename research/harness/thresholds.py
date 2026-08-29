"""Are these three thresholds fixed numbers pretending to be universal?

The CUSUM threshold was: 2.0 volatility units was silent through 47.5% of all
moves, because volatility units normalise how far an instrument travels per bar
and not how far it goes once it starts. The same question, asked of three more.

Each is measured against the quantity it is actually compared with, per feed,
so the answer is "does one number serve every instrument" rather than "is the
number nice".

* **`stale_quote_after`** (300s) decides a market is shut. The thing it is
  compared with is how long an instrument goes without trading *while open* -
  measured as gaps between consecutive 1m bars, since a missing 1m bar is a
  minute in which nothing traded. If a thin instrument routinely gaps past the
  threshold during its own session, the shut gate fires on a live market.

* **`max_against_vol`** (1.5-3.0 by strategy) refuses a trade with too much
  momentum against it. Compared with `pressure_vol` at decision time.

* **`candle_tolerance_vol`** (0.25) decides whether a bar came close enough to
  the level to have touched it. Compared with `approach_vol`, the distance of
  the approach, which `structures` already records on every resolution.
"""

from __future__ import annotations

import json
import sqlite3
import statistics as st
from collections import defaultdict

PRICES = "file:/app/.data/prices/prices.db?mode=ro"
JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"

#: Feeds with enough history to say anything about.
MIN_SAMPLES = 200


def quantiles(vals: list[float]) -> tuple[float, float, float, float]:
    vals = sorted(vals)

    def q(p: float) -> float:
        return vals[min(len(vals) - 1, int(p * len(vals)))]

    return q(0.5), q(0.9), q(0.99), q(1.0)


def stale_quote_after() -> None:
    """How long instruments go without trading, while trading."""
    print("\n=== stale_quote_after: gaps between 1m bars, per feed ===")
    print("   a gap is a minute in which nothing traded; the setting is 300s\n")
    c = sqlite3.connect(PRICES, uri=True)
    rows = c.execute(
        "select feed, venue, ts from bars where interval='1m' order by feed, venue, ts"
    )
    gaps: dict[str, list[float]] = defaultdict(list)
    last: tuple[str, str] | None = None
    last_ts = 0
    for feed, venue, ts in rows:
        key = (feed, venue)
        if last == key and ts > last_ts:
            gap = float(ts - last_ts)
            # Weekends and session breaks are the thing being measured, but a
            # multi-day gap is the market being shut rather than thin, and
            # including it would answer a different question.
            if gap <= 6 * 3600:
                gaps[feed].append(gap)
        last, last_ts = key, ts

    over = []
    for feed, vals in sorted(gaps.items()):
        if len(vals) < MIN_SAMPLES:
            continue
        med, p90, p99, worst = quantiles(vals)
        share = sum(1 for v in vals if v > 300.0) / len(vals)
        if share > 0.001:
            over.append((share, feed, med, p90, p99, worst))
    over.sort(reverse=True)
    if not over:
        print("   no feed gaps past 300s inside a session - the fixed value holds")
        return
    print(f"   {'feed':12s} {'median':>8s} {'p90':>8s} {'p99':>8s} {'worst':>9s}   over 300s")
    for share, feed, med, p90, p99, worst in over[:12]:
        print(f"   {feed:12s} {med:7.0f}s {p90:7.0f}s {p99:7.0f}s {worst:8.0f}s   {share:6.2%}")


def _decision_features() -> dict[str, list[float]]:
    c = sqlite3.connect(JOURNAL, uri=True)
    out: dict[str, list[float]] = defaultdict(list)
    rows = c.execute(
        "select context from entries where actor='trading' order by time desc limit 120000"
    )
    for (blob,) in rows:
        d = json.loads(blob or "{}")
        feed = str(d.get("feed") or "")
        p = d.get("pressure_vol")
        if feed and isinstance(p, int | float):
            out[feed].append(abs(float(p)))
    return out


def max_against_vol() -> None:
    print("\n=== max_against_vol: |pressure_vol| at decision time, per feed ===")
    print("   the setting is 1.5 on most strategies, 3.0 on one\n")
    per = _decision_features()
    rows = [(f, v) for f, v in per.items() if len(v) >= MIN_SAMPLES]
    if not rows:
        print("   not enough decisions carrying pressure_vol yet")
        return
    print(f"   {'feed':12s} {'median':>8s} {'p90':>8s} {'p99':>8s}   over 1.5v")
    for feed, vals in sorted(rows, key=lambda kv: -st.median(kv[1]))[:12]:
        med, p90, p99, _ = quantiles(vals)
        share = sum(1 for v in vals if v > 1.5) / len(vals)
        print(f"   {feed:12s} {med:8.2f} {p90:8.2f} {p99:8.2f}   {share:6.2%}")


def candle_tolerance_vol() -> None:
    print("\n=== candle_tolerance_vol: approach_vol on resolutions, per feed ===")
    print("   how close the approach came to the level; the setting is 0.25v\n")
    c = sqlite3.connect(JOURNAL, uri=True)
    per: dict[str, list[float]] = defaultdict(list)
    rows = c.execute(
        "select context from entries where actor='structures' and kind='outcome' "
        "order by time desc limit 120000"
    )
    for (blob,) in rows:
        d = json.loads(blob or "{}")
        feed = str(d.get("feed") or "")
        a = d.get("approach_vol")
        if feed and isinstance(a, int | float):
            per[feed].append(abs(float(a)))
    rows2 = [(f, v) for f, v in per.items() if len(v) >= MIN_SAMPLES]
    if not rows2:
        print("   not enough resolutions carrying approach_vol yet")
        return
    print(f"   {'feed':12s} {'median':>8s} {'p90':>8s} {'p99':>8s}   under 0.25v")
    for feed, vals in sorted(rows2, key=lambda kv: -st.median(kv[1]))[:12]:
        med, p90, p99, _ = quantiles(vals)
        share = sum(1 for v in vals if v < 0.25) / len(vals)
        print(f"   {feed:12s} {med:8.2f} {p90:8.2f} {p99:8.2f}   {share:6.2%}")


if __name__ == "__main__":
    stale_quote_after()
    max_against_vol()
    candle_tolerance_vol()
