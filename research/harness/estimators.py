"""Three origin estimators, ranked by the only property this data can rank them on.

Sections 5, 9 and 13 of the origin-localization specification: implement the
candidates behind one interface, attach every estimate to the *same* events so
no method can pick a friendlier population, and compare them paired.

The estimators:

* **A - baseline.** `origins.Origin.price`, which is the close of the bar the
  turn was found on. Whatever the repository does today.
* **F - fine-resolution transition.** Inside the coarse bar that carries the
  turn, the 1m close that actually begins the departure: the highest close for
  a drop, the lowest for a rally. Specification priority 1.
* **D - directional body edge.** The user hypothesis in section 9. Bodies of
  the turn bar and the one after it; `max(body lows)` for a bullish transition,
  `min(body highs)` for a bearish one, and an explicit miss when the bodies do
  not overlap - section 16 requires that rather than an invented value.

The property being ranked is **stability under an arbitrary sampling grid**,
because that is what this data can measure without a ground truth. There is no
observable "true origin" to compute an error against; there is only the
question of whether an estimator says the same thing when the bars are made to
start a minute later. An estimator that moves less is localizing something the
market did rather than something the chart did.
"""

from __future__ import annotations

import bisect
import os
import random
import sqlite3
import statistics as st
import sys

from till_infinity.structures.context.cusum import Cusum
from till_infinity.structures.learning.focus import Focus
from till_infinity.structures.drawing import origins
from till_infinity.structures.vol.volatility import Volatility

DB = "/app/.data/research/bt1m.db"
COARSE = 15
#: How far the fine closes must run, in volatility units, for the change-point
#: filter to call a transition inside one coarse bar. Swept rather than
#: assumed - see `research/localising.md`.
CHANGE_THRESHOLD = float(os.environ.get("CHANGE_THRESHOLD", "0.5"))


class _Bar:
    __slots__ = ("open", "high", "low", "close", "time")

    def __init__(self, ts, o, h, low, c):
        self.time, self.open, self.high, self.low, self.close = ts, o, h, low, c


def load(conn, feed):
    venue = conn.execute(
        "SELECT venue, COUNT(*) n FROM bars WHERE feed=? AND interval='1m' AND high > low "
        "GROUP BY venue ORDER BY n DESC LIMIT 1",
        (feed,),
    ).fetchone()
    if not venue:
        return []
    rows = conn.execute(
        "SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval='1m' "
        "AND venue=? ORDER BY ts",
        (feed, venue[0]),
    ).fetchall()
    return [_Bar(*r) for r in rows]


def aggregate(fine, size, offset):
    out, bucket = [], []
    for bar in fine:
        if bucket and ((bar.time // 60) - offset) % size == 0:
            out.append(_Bar(
                bucket[0].time, bucket[0].open,
                max(b.high for b in bucket), min(b.low for b in bucket), bucket[-1].close,
            ))
            bucket = []
        bucket.append(bar)
    if bucket:
        out.append(_Bar(
            bucket[0].time, bucket[0].open,
            max(b.high for b in bucket), min(b.low for b in bucket), bucket[-1].close,
        ))
    return out


def warmed(bars):
    vol = Volatility()
    for b in bars:
        vol.update(float(b.close))
        vol.observe_bar(b.open, b.high, b.low, b.close)
    return vol


def body(bar):
    """Open to close, ordered. The traded part rather than the probe."""
    return min(bar.open, bar.close), max(bar.open, bar.close)


def estimate(found, coarse, fine, fine_times, size, unit=0.0):
    """Every estimator's price for every origin, keyed by estimator.

    Origins that one estimator cannot place are dropped from **all** of them,
    so the comparison stays paired - section 13. A body-edge miss must not
    quietly shrink the population it is measured on.
    """
    at = {b.time: i for i, b in enumerate(coarse)}
    out = {"baseline": [], "fine": [], "body": [], "change": [], "focus": [], "agree": []}
    for origin in found:
        index = at.get(float(origin.when))
        if index is None or index + 1 >= len(coarse):
            continue
        turn, nxt = coarse[index], coarse[index + 1]
        down = origin.launched == "down"

        # D - the directional body edge, and its explicit miss.
        (alow, ahigh), (blow, bhigh) = body(turn), body(nxt)
        low, high = max(alow, blow), min(ahigh, bhigh)
        if low > high:
            continue
        edge = high if down else low

        # F - the 1m close that begins the departure, inside the turn bar.
        start = bisect.bisect_left(fine_times, turn.time)
        stop = bisect.bisect_left(fine_times, turn.time + size * 60)
        window = fine[start:stop]
        if len(window) < 2:
            continue
        picked = max(window, key=lambda b: b.close) if down else min(
            window, key=lambda b: b.close
        )

        # H - the change point. Section 6 of the specification, and priority 2
        # of its three highest, which the first pass of this comparison did not
        # run at all.
        #
        # Built on the repository's own `Cusum` rather than a new statistic:
        # it is a symmetric change-point filter over a price series in
        # volatility units, which is exactly what section 6 asks for, and
        # `momentum_leads` already trusts it to say when a regime turned.
        #
        # No lookahead: the filter is fed the bar's own minutes in order and
        # the event it reports is the first crossing, so nothing after t* is
        # used to place t*. Where it never crosses there is no change point and
        # the origin is left where it was - a filter that always fires would be
        # a filter measuring nothing.
        # **The threshold has to suit the question.** `Cusum`'s default is 2.0
        # volatility units, set for a stream that runs for hours; asked to find
        # a change *inside one bar* it almost never crosses - 12.9% of events
        # on the first pass - and falls back to the baseline, so the comparison
        # was rejecting the estimator for a mis-set constant. That is the error
        # `at_bound` already made once here: measuring the container rather
        # than the parameter.
        marks = Cusum(threshold=CHANGE_THRESHOLD).feed(
            [b.time for b in window], [b.close for b in window], unit
        )
        wanted = "down" if down else "up"
        crossed = [m for m in marks if m.side == wanted]
        out["change"].append(crossed[0].price if crossed else origin.price)

        # FOCuS - estimator H done properly. `Cusum` reports where it *tripped*,
        # which is where the run got long enough; FOCuS maximises the exact
        # likelihood ratio over every possible start and reports the **argmax**,
        # which is where the change most likely began. An origin is defined as
        # the price a move began from, so this is the same object rather than a
        # proxy for it.
        detector = Focus(threshold=1e18, up=not down)
        best_at, best_stat = 0, 0.0
        for i in range(1, len(window)):
            detector.update(window[i].close - window[i - 1].close, scale=unit)
            if detector.statistic > best_stat:
                best_stat, best_at = detector.statistic, detector.at
        out["focus"].append(
            window[best_at].close if 0 <= best_at < len(window) else origin.price
        )

        out["baseline"].append(origin.price)
        out["fine"].append(picked.close)
        out["body"].append(edge)
        # Does the change point land on the extreme? Two estimators built from
        # different statistics agreeing is worth more than either alone, and
        # the question is whether F is *more stable* on the events where FOCuS
        # confirms it. If it is, FOCuS augments the origin without replacing
        # anything - a confidence reading rather than a price.
        agreed = abs(out["focus"][-1] - picked.close) <= AGREE_VOL * unit if unit else False
        out["agree"].append(agreed)
    return out


def find(bars, unit):
    return origins.Origins().observe(
        [b.time for b in bars], [b.close for b in bars], unit, bars_at=bars
    )


def gaps(a, b, unit):
    if not a or not b or unit <= 0:
        return []
    return [min(abs(x - y) for y in b) / unit for x in a]


AGREE_VOL = float(os.environ.get("AGREE_VOL", "0.25"))


def run(feeds, seed=3):
    rng = random.Random(seed)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60.0)
    names = ("baseline", "fine", "body", "change", "focus")
    split = {n: {"agreed": [], "apart": []} for n in names}
    shifted = {n: [] for n in names}
    nulls = {n: [] for n in names}
    differs = {"fine": [], "body": [], "change": [], "focus": []}
    print(f"{'feed':10s} {'events':>7s} " + " ".join(f"{n:>10s}" for n in names))
    for feed in feeds:
        fine = load(conn, feed)
        if len(fine) < 5_000:
            continue
        fine_times = [b.time for b in fine]
        base_bars = aggregate(fine, COARSE, 0)
        vol = warmed(base_bars)
        unit = vol.price_units(st.median([b.close for b in base_bars]), 1.0)
        if unit <= 0:
            continue
        base = estimate(find(base_bars, unit), base_bars, fine, fine_times, COARSE, unit)
        if len(base["baseline"]) < 5:
            continue
        # Do the estimators actually differ on the same event? Two that agree
        # on every event are one estimator with two derivations, and ranking
        # them against each other would be ranking rounding error.
        for other in ("fine", "body", "change", "focus"):
            apart = [
                abs(a - b) / unit
                for a, b in zip(base["baseline"], base[other], strict=True)
                if abs(a - b) / unit > 0.01
            ]
            differs[other].append((len(apart), len(base["baseline"])))
        lo = min(b.low for b in base_bars)
        hi = max(b.high for b in base_bars)

        per = {}
        for offset in range(1, COARSE):
            other_bars = aggregate(fine, COARSE, offset)
            other = estimate(
                find(other_bars, warmed(other_bars).price_units(
                    st.median([b.close for b in other_bars]), 1.0
                ) or unit),
                other_bars, fine, fine_times, COARSE, unit,
            )
            for n in names:
                got = gaps(base[n], other[n], unit)
                # The control. If agreement moves **every** estimator by the
                # same amount it is not saying anything about F - it is saying
                # this event was easy, which any estimator would have found.
                if len(got) == len(base["agree"]):
                    for value, ok in zip(got, base["agree"], strict=True):
                        split[n]["agreed" if ok else "apart"].append(value)
                shifted[n] += got
                per.setdefault(n, []).extend(got)
                nulls[n] += gaps(
                    base[n],
                    sorted(rng.uniform(lo, hi) for _ in range(max(1, len(other[n])))),
                    unit,
                )
        print(
            f"{feed:10s} {len(base['baseline']):7d} "
            + " ".join(f"{st.median(per[n]) if per.get(n) else 0:9.3f}v" for n in names)
        )
    print()
    for other, rows in differs.items():
        moved = sum(a for a, _ in rows)
        total = sum(b for _, b in rows)
        print(f"{other:10s} differs from baseline on {moved}/{total} events ({moved / total:.1%})")
    print()
    print(f"{'estimator':10s} {'n':>7s} {'median':>9s} {'null':>9s} {'ratio':>7s} {'<0.25v':>8s}")
    for n in names:
        xs, ns = shifted[n], nulls[n]
        if not xs:
            continue
        m, nm = st.median(xs), st.median(ns)
        near = len([x for x in xs if x <= 0.25]) / len(xs)
        print(f"{n:10s} {len(xs):7d} {m:8.3f}v {nm:8.3f}v {nm / m if m else 0:6.1f}x {near:8.1%}")
    print()
    print(f"Wander split by whether FOCuS lands within {AGREE_VOL}v of the fine estimate:")
    print(f"  {'estimator':10s} {'agreed':>9s} {'apart':>9s} {'gain':>7s}")
    for n in names:
        yes, no = split[n]["agreed"], split[n]["apart"]
        if not yes or not no:
            continue
        a, b = st.median(yes), st.median(no)
        print(f"  {n:10s} {a:8.3f}v {b:8.3f}v {b / a if a else 0:6.2f}x")
    print(f"  n = {len(split['fine']['agreed'])} agreed, {len(split['fine']['apart'])} apart")


if __name__ == "__main__":
    run(sys.argv[1].split(","))
