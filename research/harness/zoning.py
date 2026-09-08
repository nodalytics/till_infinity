"""Is the indicator's logic tradeable, or only readable?

`research/tradingview/focus_zones.pine` draws a zone where a move began and
shades it by how many timeframes agree. Everything measured about it so far is
about **location** - how precisely a price can be pinned - and location is not
edge. This asks the trading question directly.

## The rules, which are the indicator's and not a tuned variant

1. FOCuS on the **anchor** timeframe finds a change, at the adaptive threshold
   `base + k * ln(anchor / tf)` with `k = 3` (`calibrating.py`).
2. The origin is refined to the **extreme close** inside the anchor bar at the
   refinement timeframe, and the zone is that finer bar's own high and low.
   Estimator F, the one that won in `localising.md`.
3. The agreement count is how many rungs between the refinement and the anchor
   called the same direction inside the window.
4. **A zone is traded on return, not on formation.** A down-launched origin is
   resistance and is sold into; an up-launched one is support and is bought.
   Entry is the *near* edge, which is the price a returning move touches first
   and the worse of the two fills - taking the far edge would be assuming a
   fill nobody offered.
5. The stop is beyond the far edge by `BUFFER` of the zone width. The target is
   `REWARD` times the stop distance. Whichever is touched first inside
   `HOLD` bars wins; otherwise the trade is closed at the last price.

## The nulls, and there are two

* **Random zones.** The same count of zones, the same widths and the same
  entry rule, at times drawn uniformly. This is what says whether the *place*
  matters or only the geometry - a 1:2 stop and target has an expectancy under
  a random walk before costs, and it is not zero.
* **Shuffled agreement.** Real zones with their agreement counts permuted,
  which is what says whether the filter earns its refusals.

## What is not modelled

No spread, no slippage, no commission, no overnight funding. Results are in R
before costs, and `research/reachable.md` and the ~3.5% taker fee are what turn
one into a number a book would see. A result here that does not clear its null
by a wide margin is not worth costing.
"""

from __future__ import annotations

import bisect
import math
import os
import random
import statistics as st
import sqlite3
import sys

from till_infinity.structures.learning.focus import Focus

DB = os.environ.get("MULTI_DB", "/app/.data/research/multi.db")
ANCHOR = int(os.environ.get("ANCHOR", "60"))
REFINE = int(os.environ.get("REFINE", "5"))
BASE = float(os.environ.get("BASE", "3.0"))
KFACTOR = float(os.environ.get("KFACTOR", "3.0"))
#: Rungs between the refinement and the anchor, inclusive.
LADDER = (5, 15, 30, 60, 120, 240, 480, 1440)
WINDOW_BARS = float(os.environ.get("WINDOW_BARS", "6"))
DECAY = 0.02
WARMUP = 60
#: Trade management, in multiples of the zone's own width.
BUFFER = float(os.environ.get("BUFFER", "0.25"))
REWARD = float(os.environ.get("REWARD", "2.0"))
#: How long a zone stays live, and how long a trade may run, in 1m bars.
LIFE = int(os.environ.get("LIFE", str(60 * 24 * 3)))
HOLD = int(os.environ.get("HOLD", "480"))


class _Bar:
    __slots__ = ("close", "high", "low", "time")

    def __init__(self, ts, h, low, c):
        self.time, self.high, self.low, self.close = ts, h, low, c


def load(conn, feed):
    venue = conn.execute(
        "SELECT venue, COUNT(*) n FROM bars WHERE feed=? GROUP BY venue ORDER BY n DESC LIMIT 1",
        (feed,),
    ).fetchone()
    if not venue:
        return []
    rows = conn.execute(
        "SELECT ts, high, low, close FROM bars WHERE feed=? AND venue=? ORDER BY ts",
        (feed, venue[0]),
    ).fetchall()
    return [_Bar(*r) for r in rows]


def aggregate(fine, size):
    """Coarse bars, stamped with the time they **opened**, keeping the extremes."""
    out, bucket = [], []
    for bar in fine:
        if bucket and (bar.time // 60) % size == 0:
            out.append(_Bar(
                bucket[0].time,
                max(b.high for b in bucket),
                min(b.low for b in bucket),
                bucket[-1].close,
            ))
            bucket = []
        bucket.append(bar)
    if bucket:
        out.append(_Bar(
            bucket[0].time,
            max(b.high for b in bucket),
            min(b.low for b in bucket),
            bucket[-1].close,
        ))
    return out


def nats_for(secs):
    """The adaptive threshold. `k = 3` is measured, not derived - see calibrating.py."""
    return BASE + KFACTOR * max(0.0, math.log(ANCHOR * 60 / secs))


def calls(bars, threshold):
    """(time, up) for every discrete change this series announced."""
    up, down = Focus(threshold=threshold), Focus(threshold=threshold, up=False)
    scale, out = 0.0, []
    for i, bar in enumerate(bars):
        if i == 0:
            continue
        step = bar.close - bars[i - 1].close
        scale = abs(step) if scale <= 0 else scale * (1 - DECAY) + abs(step) * DECAY
        if scale <= 0 or i < WARMUP:
            continue
        if up.update(step, scale=scale):
            up.reset()
            out.append((bar.time, True, i))
        if down.update(step, scale=scale):
            down.reset()
            out.append((bar.time, False, i))
    return out


def build_zones(fine):
    """Every zone the indicator would have drawn, with its agreement count."""
    anchor = aggregate(fine, ANCHOR)
    if len(anchor) < WARMUP + 20:
        return []
    refine = aggregate(fine, REFINE)
    refine_times = [b.time for b in refine]
    anchor_secs = ANCHOR * 60

    # Every rung's calls, for the agreement count.
    ladder = {}
    for size in LADDER:
        if size < REFINE or size > ANCHOR:
            continue
        bars = aggregate(fine, size)
        if len(bars) < WARMUP + 20:
            continue
        got = calls(bars, nats_for(size * 60))
        ladder[size] = (
            sorted(t for t, up, _ in got if up),
            sorted(t for t, up, _ in got if not up),
        )

    zones = []
    for when, up, index in calls(anchor, nats_for(anchor_secs)):
        # The anchor bar the change started in.
        start = anchor[index].time if index < len(anchor) else when
        stop = start + anchor_secs
        lo = bisect.bisect_left(refine_times, start)
        hi = bisect.bisect_left(refine_times, stop)
        window = refine[lo:hi]
        if len(window) < 2:
            continue
        # Estimator F: the extreme close inside the anchor bar.
        pick = min(window, key=lambda b: b.close) if up else max(window, key=lambda b: b.close)
        if pick.high <= pick.low:
            continue
        floor = when - WINDOW_BARS * anchor_secs
        agreed = 0
        for size, (ups, downs) in ladder.items():
            stamps = ups if up else downs
            left = bisect.bisect_right(stamps, floor)
            right = bisect.bisect_right(stamps, when)
            agreed += 1 if right > left else 0
        zones.append({
            "at": when,
            "up": up,
            "low": pick.low,
            "high": pick.high,
            "agreed": agreed,
        })
    return zones


def trade(fine, times, zone, *, entry_edge=True):
    """Take the zone on the first return after it was knowable. R, or None."""
    width = zone["high"] - zone["low"]
    if width <= 0:
        return None
    up = zone["up"]
    # The near edge - what a returning move touches first, and the worse fill.
    entry = zone["high"] if up else zone["low"]
    if not entry_edge:
        entry = (zone["high"] + zone["low"]) / 2
    stop = (zone["low"] - BUFFER * width) if up else (zone["high"] + BUFFER * width)
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    target = entry + REWARD * risk if up else entry - REWARD * risk

    # **A zone is not knowable until the anchor bar that carried it has closed.**
    #
    # This is the whole difference between a result and a fantasy. The zone's
    # edges are the extreme of the refinement bars *inside* that anchor bar, so
    # allowing entry from the bar's open lets the trade fill at a price chosen
    # with the rest of the bar already seen. The first version did exactly that
    # and returned +1.363R at an 80.8% win rate on btc against a null of
    # +0.046R - a number good enough to be obviously wrong.
    #
    # Entry is therefore looked for from the anchor bar's **close**, which is
    # the first moment a person could have drawn the zone at all.
    begin = bisect.bisect_right(times, zone["at"] + ANCHOR * 60)
    for i in range(begin, min(begin + LIFE, len(fine))):
        bar = fine[i]
        touched = bar.low <= entry <= bar.high
        if not touched:
            continue
        # In the trade. Walk forward to the first of stop and target.
        for j in range(i, min(i + HOLD, len(fine))):
            step = fine[j]
            if up:
                if step.low <= stop:
                    return -1.0
                if step.high >= target:
                    return REWARD
            else:
                if step.high >= stop:
                    return -1.0
                if step.low <= target:
                    return REWARD
        last = fine[min(i + HOLD, len(fine)) - 1].close
        return ((last - entry) if up else (entry - last)) / risk
    return None


def randomised(fine, zones, rng):
    """The same geometry somewhere else. The first null."""
    out = []
    for zone in zones:
        i = rng.randrange(WARMUP, max(WARMUP + 1, len(fine) - LIFE - HOLD))
        mid = fine[i].close
        width = zone["high"] - zone["low"]
        out.append({
            "at": fine[i].time,
            "up": zone["up"],
            "low": mid - width / 2,
            "high": mid + width / 2,
            "agreed": zone["agreed"],
        })
    return out


def report(name, rows):
    if len(rows) < 20:
        print(f"  {name:28s} {len(rows):5d} trades - too few to report")
        return
    wins = sum(1 for r in rows if r > 0)
    print(
        f"  {name:28s} {len(rows):5d} trades  mean {st.fmean(rows):7.3f}R  "
        f"median {st.median(rows):7.3f}R  won {wins / len(rows):5.1%}"
    )


def run(feeds, seed=13):
    rng = random.Random(seed)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120.0)
    real, null, shuffled_filter = [], [], []
    by_agree: dict[int, list[float]] = {}
    print(
        f"anchor {ANCHOR}m, refinement {REFINE}m, base {BASE} nats, k {KFACTOR}, "
        f"buffer {BUFFER} of width, reward {REWARD}R, hold {HOLD} bars\n"
    )
    print(f"{'feed':10s} {'zones':>7s} {'taken':>7s} {'mean R':>9s}")
    for feed in feeds:
        fine = load(conn, feed)
        if len(fine) < 20_000:
            continue
        times = [b.time for b in fine]
        zones = build_zones(fine)
        if not zones:
            continue
        took = []
        for zone in zones:
            got = trade(fine, times, zone)
            if got is None:
                continue
            took.append(got)
            real.append(got)
            by_agree.setdefault(zone["agreed"], []).append(got)
        for zone in randomised(fine, zones, rng):
            got = trade(fine, times, zone)
            if got is not None:
                null.append(got)
        print(
            f"{feed:10s} {len(zones):7d} {len(took):7d} "
            f"{st.fmean(took) if took else 0:8.3f}R"
        )
    print()
    report("real zones", real)
    report("random zones (null)", null)
    print()
    print("  by how many timeframes agreed:")
    for k in sorted(by_agree):
        report(f"    agreed {k}", by_agree[k])
    # The filter's own null: real trades, agreement labels permuted.
    labels = [k for k, v in by_agree.items() for _ in v]
    values = [r for v in by_agree.values() for r in v]
    rng.shuffle(labels)
    fake: dict[int, list[float]] = {}
    for k, r in zip(labels, values):
        fake.setdefault(k, []).append(r)
    print("\n  the same trades with the agreement labels shuffled:")
    for k in sorted(fake):
        report(f"    agreed {k}", fake[k])
    del shuffled_filter


def sweep(feeds, seed=13):
    """Does the agreement split reappear as the stop loosens?

    `focusing.md` measured the filter passing its control by a factor of
    fourteen for **location** and vanishing for **trade outcomes**, and named
    the stop as the likeliest reason: that measurement had no stop, and this
    one puts it a quarter of a zone-width beyond the far edge, which is hit by
    exactly the move-and-return that leaves a forward number intact.

    So the stop is the variable, not the signal. If the split is real and the
    geometry is spending it, a wider stop should bring it back; if it never
    appears, the filter does not survive contact with a trade.

    Reported against the shuffled-label control at every width, because a split
    that grows in both is a wider stop flattering everything.
    """
    global BUFFER
    rng = random.Random(seed)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120.0)
    loaded = []
    for feed in feeds:
        fine = load(conn, feed)
        if len(fine) >= 20_000:
            loaded.append((feed, fine, [b.time for b in fine]))
    print(f"anchor {ANCHOR}m, refinement {REFINE}m, reward {REWARD}R, hold {HOLD} bars")
    print(f"{len(loaded)} instruments\n")
    print(
        f"{'stop':>6s} {'n':>5s} {'real':>8s} {'null':>8s} {'edge':>8s}  "
        f"{'1-2 tf':>8s} {'3+ tf':>8s} {'split':>8s} {'p(perm)':>9s}"
    )
    for width in (0.25, 0.5, 1.0, 2.0, 4.0):
        BUFFER = width
        real, null = [], []
        low_tf, high_tf = [], []
        for _feed, fine, times in loaded:
            zones = build_zones(fine)
            if not zones:
                continue
            for zone in zones:
                got = trade(fine, times, zone)
                if got is None:
                    continue
                real.append(got)
                (high_tf if zone["agreed"] >= 3 else low_tf).append(got)
            for zone in randomised(fine, zones, rng):
                got = trade(fine, times, zone)
                if got is not None:
                    null.append(got)
        if len(real) < 40 or len(low_tf) < 20 or len(high_tf) < 20:
            print(f"{width:6.2f} {len(real):5d}  too few")
            continue
        # **A permutation test, not one shuffle.** A single draw is itself a
        # random variable: the first version of this table showed a shuffled
        # split of +0.368R at one stop width and near zero at the others, which
        # is one unlucky draw being read as evidence against the effect. What
        # is wanted is how often chance alone produces a split this large.
        split = st.fmean(high_tf) - st.fmean(low_tf)
        values = low_tf + high_tf
        cut = len(low_tf)
        beaten = 0
        draws = 500
        for _ in range(draws):
            rng.shuffle(values)
            fake = st.fmean(values[cut:]) - st.fmean(values[:cut])
            beaten += 1 if fake >= split else 0
        print(
            f"{width:6.2f} {len(real):5d} {st.fmean(real):7.3f}R {st.fmean(null):7.3f}R "
            f"{st.fmean(real) - st.fmean(null):7.3f}R  "
            f"{st.fmean(low_tf):7.3f}R {st.fmean(high_tf):7.3f}R "
            f"{split:7.3f}R {beaten / draws:9.3f}"
        )


if __name__ == "__main__":
    if os.environ.get("SWEEP"):
        sweep(sys.argv[1].split(","))
    else:
        run(sys.argv[1].split(","))
