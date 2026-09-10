"""Is the changepoint threshold hiding higher-timeframe origins?

Two things stop a coarse origin from ever getting a changepoint reading, and
only one of them is the number everyone reaches for.

**The threshold.** `focus.THRESHOLD` is 12.0 nats, and `_note_change` *adds* to
it on faster rungs - `nats = THRESHOLD + CHANGE_K * ln(slowest/mine)` - so 5m is
asked for about 19.5 and only the slowest rung in the ladder keeps 12. The
TradingView indicator that renders the same idea defaults to **1.0**. Those two
numbers cannot both be right, and the gap is a factor of twelve.

**The ladder.** `CHANGE_INTERVALS = ("5m", "15m", "30m", "1h")`. There is **no
detector above 1h at all**, so 2h, 4h and 1d origins get no reading whatever the
threshold is set to. If the aim is capturing HTF origins, this is the binding
constraint and the threshold is a second-order question.

## What this measures

For each coarse interval, replay its bars through `Focus` at a range of
thresholds and ask three things in order, because a yes to the first two is
worthless without the third:

1. **How many changepoints does each threshold produce?** A threshold low
   enough to fire on everything has not found anything.
2. **Do they land on origins?** Match detections against the origins the engine
   actually recorded, within a tolerance of one bar.
3. **Does a confirmed origin behave differently from an unconfirmed one?**
   This is the only question that justifies a change. `origins.md` measured
   freshness as worth something real - 1.136R for a never-revisited origin
   against 0.822R twice-revisited - so if FOCuS confirmation separates origins
   the same way, lowering the threshold buys something. If confirmed and
   unconfirmed origins behave identically, a lower threshold just produces more
   labels.

A threshold that fires more often will *always* score better on (2) alone. That
is why (3) exists, and why the report prints detections per origin beside the
hit rate - a rate that rises while detections-per-origin rises faster is a
detector getting less selective, not more useful.
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics as st
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.environ.get("REPO", os.path.expanduser("~/till_infinity/repo")))

from till_infinity.structures.learning.focus import Focus  # noqa: E402

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
JOURNAL = os.path.join(DATA, "journal.db")
#: Bars come from the research store by default. It is 60 days deep on every
#: coarse rung, carries the 1s series production's collector loses, and is
#: indexed on (feed, interval, ts) - which is how this queries. `prices.db`
#: leads its index on (source, venue, ticker), so the same query there scans
#: 21 million rows and sorts them.
#:
#: The **origins** still come from the journal: they are what the engine
#: actually recorded, and no price store has them.
PRICES = os.environ.get("DB", os.path.join(DATA, "research.db"))

#: The coarse rungs. `1h` is in the live ladder; the rest are not, which is the
#: point of including them.
INTERVALS = tuple(os.environ.get("INTERVALS", "1h,2h,4h,1d").split(","))
THRESHOLDS = tuple(float(x) for x in os.environ.get("NATS", "1,3,6,12,20").split(","))
DAYS = float(os.environ.get("DAYS", "60"))
FEEDS = tuple(f for f in os.environ.get("FEEDS", "").split(",") if f)
#: Fall back to whatever the store actually holds when a (feed, interval) pair
#: has origins in the journal but no bars here - which is most of the FX book,
#: since `research.db` was filled from the broker's synthetic list.
REPORT_MISSING = os.environ.get("REPORT_MISSING", "1") not in ("0", "false")


def origins_from_journal(conn, since: float) -> dict[tuple[str, str], list[float]]:
    """(feed, interval) -> times the engine recorded an origin."""
    out = defaultdict(list)
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries WHERE actor='structures' AND time>=? "
        "ORDER BY time ASC",
        (since,),
    ):
        try:
            got = json.loads(ctx or "{}")
        except Exception:
            continue
        feed, iv = str(got.get("feed") or ""), str(got.get("interval") or "")
        if not feed or iv not in INTERVALS:
            continue
        # An origin shows up on a call as its band; the presence of one is what
        # is being matched, not its price.
        if got.get("origin_below_high") is not None or got.get("origin_above_low") is not None:
            out[(feed, iv)].append(float(when))
    return out


def bars(conn, feed: str, interval: str, since: float):
    rows = conn.execute(
        "SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval=? AND ts>=? "
        "ORDER BY ts ASC",
        (feed, interval, int(since * 1000)),
    ).fetchall()
    out = []
    for ts, o, h, low, c in rows:
        if not all(isinstance(v, int | float) and v > 0 for v in (o, h, low, c)):
            continue
        out.append((ts / 1000.0 if ts > 1e11 else float(ts), float(o), float(h),
                    float(low), float(c)))
    return out


def detect(series, nats: float) -> list[float]:
    """Times at which FOCuS fires on this series at this threshold.

    Two detectors, one per direction, reset on firing - the same shape
    `_note_change` uses, so what is measured is what production would do.
    """
    if len(series) < 30:
        return []
    up, down = Focus(threshold=nats), Focus(threshold=nats, up=False)
    fired = []
    closes = [c for _t, _o, _h, _l, c in series]
    # Scale by a rough absolute-move unit so `nats` means the same thing across
    # instruments, which is what the live path does with `vol.bps`.
    steps = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    unit = st.median([s for s in steps if s > 0] or [1.0])
    for i in range(1, len(series)):
        step = closes[i] - closes[i - 1]
        hit = False
        if up.update(step, scale=unit):
            up.reset()
            hit = True
        if down.update(step, scale=unit):
            down.reset()
            hit = True
        if hit:
            fired.append(series[i][0])
    return fired


def run() -> None:
    jc = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=600.0)
    pc = sqlite3.connect(f"file:{PRICES}?mode=ro", uri=True, timeout=600.0)
    since = time.time() - DAYS * 86400

    found = origins_from_journal(jc, since)
    keys = sorted(found, key=lambda k: -len(found[k]))
    if FEEDS:
        keys = [k for k in keys if k[0] in FEEDS]
    keys = keys[: int(os.environ.get("TOP", "40"))]
    print(f"{len(keys)} (feed, interval) pairs with origins in {DAYS:g} days")
    print(f"intervals {INTERVALS}, thresholds {THRESHOLDS}\n")

    print(f"  {'interval':>8s} {'nats':>6s} {'series':>7s} {'bars':>8s} "
          f"{'fires':>7s} {'origins':>8s} {'matched':>8s} {'hit%':>7s} {'fires/orig':>11s} "
          f"{'chance':>8s} {'lift':>7s}")
    for iv in INTERVALS:
        mine = [k for k in keys if k[1] == iv]
        if not mine:
            print(f"  {iv:>8s}  (no origins recorded)")
            continue
        loaded, absent = {}, []
        for feed, _iv in mine:
            got = bars(pc, feed, iv, since)
            if len(got) >= 60:
                loaded[feed] = got
            else:
                absent.append(feed)
        if absent and REPORT_MISSING:
            # A harness that quietly reports on the feeds it happens to have is
            # how a measurement ends up describing a different book from the one
            # it names. Say what was dropped.
            print(f"  {iv:>8s}  {len(absent)} feed(s) had origins but no bars here"
                  f" - e.g. {', '.join(sorted(absent)[:4])}")
        if not loaded:
            print(f"  {iv:>8s}  (no bars)")
            continue
        span = st.median([b[0][0] for b in loaded.values()]) if loaded else 0
        for nats in THRESHOLDS:
            fires = origins = matched = total_bars = 0
            for feed, series in loaded.items():
                at = detect(series, nats)
                fires += len(at)
                total_bars += len(series)
                theirs = found.get((feed, iv), [])
                origins += len(theirs)
                if not at or not theirs:
                    continue
                # One bar of tolerance either way.
                width = (series[1][0] - series[0][0]) if len(series) > 1 else 3600.0
                for t in theirs:
                    if any(abs(t - f) <= width for f in at):
                        matched += 1
            hit = matched / origins if origins else 0.0
            per = fires / origins if origins else 0.0
            # **What a detector with no knowledge would score.** A fire lands on
            # a given bar with probability `fires/bars`; the match window is the
            # bar either side, so three chances. Anything at or below this is
            # hitting origins by volume, not by finding them - which is the only
            # way to read a hit rate that rises with the firing rate.
            rate = fires / total_bars if total_bars else 0.0
            chance = 1.0 - (1.0 - min(rate, 1.0)) ** 3
            lift = (hit / chance) if chance > 0 else float("nan")
            print(f"  {iv:>8s} {nats:6.1f} {len(loaded):7d} {total_bars:8d} "
                  f"{fires:7d} {origins:8d} {matched:8d} {hit:6.1%} {per:11.2f} "
                  f"{chance:8.1%} {lift:7.2f}")
        print()

    print("`chance` is what a detector firing at the same rate but knowing nothing")
    print("would score. `lift` is hit% over that. **A lift near 1.0 at every")
    print("threshold means the detections carry no information about origins** -")
    print("the hit rate is the firing rate and nothing else.\n")
    print("A lower threshold always matches more origins - it fires more often.")
    print("Read `hit%` against `fires/orig`: a hit rate rising slower than the")
    print("fire rate is a detector getting less selective, not more useful.")
    print("Whether a matched origin *behaves* differently is the next test and")
    print("the only one that justifies changing the live threshold.")


if __name__ == "__main__":
    run()
