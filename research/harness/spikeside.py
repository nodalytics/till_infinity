"""Is Boom's loss the spike direction, or the instrument?

`instruments.md` records the sharpest instrument-level signal on the book:

| | n | mean R |
| --- | --- | --- |
| Boom 1000 Index | 21 | -0.595 |
| Boom 500 Index | 27 | -0.215 |
| Crash 1000 Index | 22 | +0.053 |

Boom and Crash are the same generator with the sign reversed - Boom grinds down
and spikes **up**, Crash grinds up and spikes **down** - so the obvious
hypothesis is directional: the spike runs against a Boom *sell* and against a
Crash *buy*, and those are the trades bleeding.

`spiking.md` already measured the spike as uncallable: one every 11.9 minutes on
Boom 1000, waiting time with a coefficient of variation of 0.99 against a
memoryless process's 1.00. Nothing can time it. So if the loss is directional,
the fix is a gate and not a model.

**The live record does not support that.** Split by side over the journal's own
outcomes:

    boom   buy   n=25  -0.394R      boom   sell  n=23  -0.367R   <- spike against
    crash  buy   n=10  +0.314R  <-  crash  sell  n=14  -0.195R

Boom loses on *both* sides, near-identically (gap 0.027R). And on Crash the side
the spike runs against is the side that **wins** by half an R, which is the
opposite of the prediction.

Ten to twenty-five trades a cell cannot settle it, which is what this is for: the
same split over every published level call on these feeds, walked forward on 1m
bars with the spread charged, under the shared corrected `walk`.

## What the answers would mean

* **Both sides lose about equally on Boom** - the instrument is unprofitable for
  a level strategy regardless of direction, and the action is to stop trading it
  rather than to gate a side.
* **One side carries it** - a directional gate, and the live sample was too
  small to see it.
* **Boom and Crash differ but not by spike direction** - the asymmetry is
  something else about the generator, and `spiking.md` is the place to look.

Usage:
    JOURNAL=~/till_infinity/data/journal.db BARS=~/till_infinity/data/research.db \\
    HOLD=30 python3 -m research.harness.spikeside
"""

from __future__ import annotations

import bisect
import os
import sqlite3
import statistics as st
from collections import defaultdict

from research.harness.sweepregimes import (
    BARS,
    ITS_OWN_EXIT,
    JOURNAL,
    bars_for,
    candidates,
    spreads,
    walk,
)

SPLIT = float(os.environ.get("SPLIT", "0.6"))
MIN_N = int(os.environ.get("MIN_N", "100"))
#: Every synthetic whose generator is a one-sided jump, and which way it jumps.
FAMILIES = {
    "boom_300_index": ("boom", "up"),
    "boom_500_index": ("boom", "up"),
    "boom_1000_index": ("boom", "up"),
    "crash_300_index": ("crash", "down"),
    "crash_500_index": ("crash", "down"),
    "crash_1000_index": ("crash", "down"),
}


def report(label, rows):
    """Mean R by family and side, and the gap the hypothesis predicts."""
    by = defaultdict(list)
    for r in rows:
        by[(r["family"], "buy" if r["up"] else "sell")].append(r["r"])
    if not by:
        return
    print(f"\n  {label}")
    print(f"    {'family':<8s} {'side':<5s} {'n':>6s} {'mean R':>9s} {'median':>9s} {'win':>7s}")
    for (family, side), rs in sorted(by.items()):
        if len(rs) < MIN_N:
            continue
        # The spike runs against a boom sell and against a crash buy.
        against = (family == "boom" and side == "sell") or (family == "crash" and side == "buy")
        mark = "  <- spike against" if against else ""
        print(
            f"    {family:<8s} {side:<5s} {len(rs):6d} {st.fmean(rs):+9.3f} "
            f"{st.median(rs):+9.3f} {sum(1 for r in rs if r > 0) / len(rs):6.1%}{mark}"
        )
    for family in ("boom", "crash"):
        buys, sells = by.get((family, "buy"), []), by.get((family, "sell"), [])
        if len(buys) >= MIN_N and len(sells) >= MIN_N:
            gap = st.fmean(buys) - st.fmean(sells)
            print(f"    {family}: buy - sell = {gap:+.3f}R")


def run():
    from till_infinity.trading.config import Settings

    settings = Settings.from_env()
    jn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=300.0)
    spread = spreads(jn)
    # Every published level call, not sweep-aware's subset: the loss in
    # `instruments.md` spans strategies, so gating it to one would measure a
    # different question from the one asked.
    trades, seen, _refused = candidates(jn, settings, gate=False)
    jn.close()

    wanted = [t for t in trades if t["feed"] in FAMILIES]
    print(f"{seen} published level calls; {len(wanted)} on a boom or crash feed")

    conn = sqlite3.connect(f"file:{BARS}?mode=ro", uri=True, timeout=300.0)
    by_feed = defaultdict(list)
    for t in wanted:
        by_feed[t["feed"]].append(t)

    done = []
    for feed, part in by_feed.items():
        rows, stamps = bars_for(conn, feed)
        if len(rows) < 500:
            continue
        bps = spread.get(feed, 0.0)
        for t in part:
            start = bisect.bisect_left(stamps, t["when"])
            if start >= len(rows) - 10:
                continue
            got = walk(rows, start, t, t["level"] * bps / 10_000.0, ITS_OWN_EXIT)
            if got is not None:
                t["r"] = got[0]
                t["family"] = FAMILIES[feed][0]
                done.append(t)
    conn.close()
    done.sort(key=lambda t: t["when"])
    print(f"{len(done)} replayed\n")
    if len(done) < 4 * MIN_N:
        print("too few to split")
        return

    report("pooled", done)
    edge = int(len(done) * SPLIT)
    report("discovery", done[:edge])
    report("verify", done[edge:])

    print("\n  per feed, pooled:")
    per = defaultdict(list)
    for t in done:
        per[(t["feed"], "buy" if t["up"] else "sell")].append(t["r"])
    print(f"    {'feed':<22s} {'side':<5s} {'n':>6s} {'mean R':>9s}")
    for (feed, side), rs in sorted(per.items()):
        if len(rs) >= MIN_N:
            print(f"    {feed:<22s} {side:<5s} {len(rs):6d} {st.fmean(rs):+9.3f}")

    print("\nBoom grinds down and spikes up; Crash grinds up and spikes down.")
    print("If the loss is the spike, the marked rows are the ones that bleed.")
    print("If both sides of a family lose alike, the instrument is the problem")
    print("and a directional gate would fix nothing.")


if __name__ == "__main__":
    run()
