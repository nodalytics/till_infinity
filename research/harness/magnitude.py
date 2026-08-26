"""Does the system know *how far*, and *what it costs to be wrong*?

Run from the repository root:  python research/harness/magnitude.py

[prior.md](../prior.md) established that the directional claim is a
re-encoding of `side`: give the baseline the same side conditioning and what
remains predicts direction at 51.8%, AUC 0.520. It also said what it did **not**
test, which is everything else the system produces:

    expected_push    how far price will go, in volatility units
    risk_vol         distance from the arrival price to the stop
    reward_to_risk   the first over the second, and the gate `actionable` uses

A system can be useful for *how far* while having nothing to say about *which
way*. [features.md](../features.md) §3 has flagged that twice and nobody has
measured it.

## The nulls, chosen before the measurement

Each claim is scored against the cheapest thing that could replace it, because
that is the only comparison that says whether the machinery earns its place -
and in this project the cheap thing keeps winning.

| claim | null |
|---|---|
| `expected_push` ranks realised push | the per-(feed, interval) mean push, accumulated causally |
| `risk_vol` bounds the loss | how often price actually reaches it |
| `reward_to_risk` selects | realised push per unit of risk, by predicted decile |

## What "realised" means here

A call from **above** claiming *up* is the level holding, so its profit is
`+push_vol`; from **below** claiming *down* it is `-push_vol`. `excursion_vol`
is how far price got **beyond** the level, which for that trade is exactly the
adverse excursion - so `excursion_vol >= risk_vol` is a stop-out, measured
rather than assumed.
"""

from __future__ import annotations

import collections
import math
import pickle
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from edge_gate import INTERVALS, bars, key

from till_infinity.structures.engine import Engine

#: The replay costs about fifteen minutes, and every follow-up question about
#: these rows was costing another one.
CACHE = Path(__file__).with_name("magnitude.pkl")

#: Observations before a cell's own mean push is trusted, mirroring the
#: shrinkage `base_rate_for` uses so the null is not handicapped by warm-up.
NULL_WEIGHT = 8.0


class MeanPush:
    """Mean |push| per (feed, interval), accumulated causally.

    The null `expected_push` has to beat: predicting every touch on a series
    with the average size of the last ones, which costs a counter.
    """

    def __init__(self) -> None:
        self._cells: dict[tuple, list[float]] = collections.defaultdict(lambda: [0.0, 0.0])
        self._pooled = [0.0, 0.0]

    def expect(self, feed: str, interval: str) -> float:
        pooled = self._pooled[0] / self._pooled[1] if self._pooled[1] else 0.0
        total, seen = self._cells.get((feed, interval), (0.0, 0.0))
        if not seen:
            return pooled
        return (total + NULL_WEIGHT * pooled) / (seen + NULL_WEIGHT)

    def observe(self, feed: str, interval: str, push: float) -> None:
        cell = self._cells[(feed, interval)]
        cell[0] += abs(push)
        cell[1] += 1.0
        self._pooled[0] += abs(push)
        self._pooled[1] += 1.0


def collect():
    """Replay, pairing every call with what the touch it opened actually did."""
    if CACHE.exists():
        return pickle.loads(CACHE.read_bytes())
    engine = Engine(intervals=INTERVALS)
    nulls = MeanPush()
    pending: dict[tuple, dict] = {}
    paired: list[dict] = []

    for bar in bars(INTERVALS):
        for call in engine.observe_bar(bar):
            touch = engine.tracker.open_touch(call.level)
            if touch is None or touch.started != call.time:
                continue
            inference = call.inference
            # `risk_vol` is measured from the *arrival price*; `excursion_vol`
            # is measured from the *level*. Comparing them directly would be
            # comparing two distances with different origins, which is close
            # enough to look right and is not the same thing. So the stop's
            # distance beyond the level is computed here explicitly.
            vol = engine.vol.of(call.feed, call.interval)
            beyond = 0.0
            if vol is not None:
                stop = call.level.stop_for(touch.features.side, vol)
                price = call.level.price
                if price and vol.bps:
                    beyond = abs((stop - price) / price * 10_000) / vol.bps
            pending[key(call.feed, call.interval, touch.level_price, touch.started)] = {
                "feed": call.feed,
                "interval": call.interval,
                "above": touch.features.side.name == "ABOVE",
                "edge": inference.edge,
                "expected_push": inference.expected_push,
                "risk_vol": inference.risk_vol,
                "reward_to_risk": inference.reward_to_risk,
                "actionable": inference.actionable,
                "stop_beyond": beyond,
                # What the cheap alternative would have said, as of now.
                "null_push": nulls.expect(call.feed, call.interval),
            }
        for _level, touch in engine.drain_resolved():
            row = pending.pop(
                key(touch.feed, touch.interval, touch.level_price, touch.started), None
            )
            nulls.observe(touch.feed, touch.interval, touch.push_vol)
            if row is None or not touch.push_vol:
                continue
            row["push_vol"] = float(touch.push_vol)
            row["excursion_vol"] = float(touch.excursion_vol)
            row["outcome"] = str(touch.outcome).split(".")[-1].lower()
            # Two different trades, and conflating them was the first version
            # of this script. `held` is the trivial rule's trade: the level
            # holds, so a touch from above goes up. `realised` is **the call's
            # own** trade, taken in the direction `edge` claims - which differs
            # from the trivial rule on about a tenth of calls, and that tenth
            # is precisely what a measurement of the model is about.
            push = float(touch.push_vol)
            row["held"] = push if row["above"] else -push
            row["realised"] = push if row["edge"] > 0 else -push
            paired.append(row)
    CACHE.write_bytes(pickle.dumps(paired))
    return paired


def correlation(xs, ys) -> float:
    if len(xs) < 2:
        return 0.0
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    dy = math.sqrt(sum((b - my) ** 2 for b in ys))
    return num / (dx * dy) if dx and dy else 0.0


def deciles(rows, by, label):
    ordered = sorted(rows, key=by)
    size = max(1, len(ordered) // 10)
    print(f"    {'decile':>7} {label:>14} {'n':>6} {'realised |push|':>16} {'realised':>10}")
    print("    " + "-" * 60)
    for i in range(10):
        chunk = ordered[i * size : (i + 1) * size] if i < 9 else ordered[9 * size :]
        if not chunk:
            continue
        print(
            f"    {i + 1:>7} {by(chunk[0]):>14.3f} {len(chunk):>6}"
            f" {statistics.fmean(abs(r['push_vol']) for r in chunk):>16.3f}"
            f" {statistics.fmean(r['realised'] for r in chunk):>10.3f}"
        )


def main() -> None:
    rows = collect()
    print(f"{len(rows):,} calls paired with the outcome of the touch they opened\n")

    print("=== 1. is `expected_push` the right size")
    predicted = statistics.fmean(abs(r["expected_push"]) for r in rows)
    realised = statistics.fmean(abs(r["push_vol"]) for r in rows)
    null = statistics.fmean(r["null_push"] for r in rows)
    print(f"    mean |expected_push|      {predicted:.3f}")
    print(f"    mean |realised push|      {realised:.3f}")
    print(f"    ratio                     {predicted / realised:.2f}   (1.00 = right size)")
    print(f"    the null's mean           {null:.3f}\n")

    print("=== 2. does it *rank* the size, which is what a gate consumes")
    got = correlation([abs(r["expected_push"]) for r in rows], [abs(r["push_vol"]) for r in rows])
    against = correlation([r["null_push"] for r in rows], [abs(r["push_vol"]) for r in rows])
    print(f"    corr(|expected_push|, |realised|)   {got:+.3f}")
    print(f"    corr(null mean push,  |realised|)   {against:+.3f}")
    print(f"    {'expected_push wins' if got > against else 'THE NULL WINS'}\n")

    print("=== 3. realised size by predicted decile")
    deciles(rows, lambda r: abs(r["expected_push"]), "|expected|")

    risk(rows)
    ratio(rows)
    mechanism(rows)
    delivered(rows)


def risk(rows) -> None:
    """Is the stop a real bound, or a distance nobody ever reaches?"""
    print("\n=== 4. does price reach the stop")
    risky = [r for r in rows if r["risk_vol"] > 0]
    stopped = [r for r in risky if r["stop_beyond"] and r["excursion_vol"] >= r["stop_beyond"]]
    print(f"    calls with a stop distance   {len(risky):,}")
    stop = statistics.median(r["risk_vol"] for r in risky)
    print(f"    median risk_vol (from entry) {stop:.3f}")
    past = statistics.median(r["stop_beyond"] for r in risky)
    print(f"    median stop beyond the level {past:.3f}")
    print(
        f"    median adverse excursion     "
        f"{statistics.median(r['excursion_vol'] for r in risky):.3f}"
    )
    print(f"    would have been stopped      {len(stopped):,} ({len(stopped) / len(risky):.1%})")
    beyond = [r for r in risky if r["excursion_vol"] > 0]
    print(f"    ever went beyond the level   {len(beyond):,} ({len(beyond) / len(risky):.1%})")
    stops = [r["stop_beyond"] for r in risky]
    gone = [r["excursion_vol"] for r in risky]
    print(f"    corr(stop distance, excursion) {correlation(stops, gone):+.3f}")


def ratio(rows) -> None:
    """Does the ratio `actionable` gates on order anything."""
    print("\n=== 5. does `reward_to_risk` select anything")
    rated = [r for r in rows if r["reward_to_risk"] > 0]
    print(f"    {len(rated):,} calls with a ratio\n")
    deciles(rated, lambda r: r["reward_to_risk"], "predicted RR")
    print("\n    realised return per unit of risk, by gate")
    print(f"    {'RR at least':>12} {'n':>7} {'share':>7} {'realised':>10} {'per risk':>10}")
    print("    " + "-" * 52)
    for gate in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0):
        kept = [r for r in rated if r["reward_to_risk"] >= gate]
        if not kept:
            continue
        per = statistics.fmean(r["realised"] / r["risk_vol"] for r in kept if r["risk_vol"])
        print(
            f"    {gate:>12.1f} {len(kept):>7} {len(kept) / len(rated):>6.1%}"
            f" {statistics.fmean(r['realised'] for r in kept):>10.3f} {per:>10.3f}"
        )


def mechanism(rows) -> None:
    """Why a high predicted ratio would select badly.

    `reward_to_risk` is `|net_push| / risk_vol`, and the denominator varies far
    more than the numerator. A high ratio is therefore mostly a **small
    `risk_vol`** - a tight zone, which puts the stop close to the level, which
    is where price sits while the level is working. If that is the mechanism,
    the ratio is a measure of how easily a trade is stopped out wearing the
    name of how much it is worth.
    """
    print("\n=== 5b. is the ratio driven by its numerator or its denominator")
    rated = [r for r in rows if r["reward_to_risk"] > 0]
    ratios = [r["reward_to_risk"] for r in rated]
    sizes = [abs(r["expected_push"]) for r in rated]
    stops = [r["risk_vol"] for r in rated]
    print(f"    corr(RR, |expected_push|)  {correlation(ratios, sizes):+.3f}")
    print(f"    corr(RR, risk_vol)         {correlation(ratios, stops):+.3f}")
    ordered = sorted(rated, key=lambda r: r["reward_to_risk"])
    size = max(1, len(ordered) // 10)
    print(f"\n    {'decile':>7} {'RR':>8} {'|expected|':>11} {'risk_vol':>10} {'stopped':>9}")
    print("    " + "-" * 50)
    for i in (0, 4, 8, 9):
        chunk = ordered[i * size : (i + 1) * size] if i < 9 else ordered[9 * size :]
        stopped = sum(
            1 for r in chunk if r["stop_beyond"] and r["excursion_vol"] >= r["stop_beyond"]
        )
        print(
            f"    {i + 1:>7} {statistics.fmean(r['reward_to_risk'] for r in chunk):>8.3f}"
            f" {statistics.fmean(abs(r['expected_push']) for r in chunk):>11.3f}"
            f" {statistics.fmean(r['risk_vol'] for r in chunk):>10.3f}"
            f" {stopped / len(chunk):>8.1%}"
        )


def delivered(rows) -> None:
    """The product, in one number: what a published call is worth."""
    print("\n=== 6. what `actionable` actually delivers")
    passed = [r for r in rows if r["actionable"]]
    share = len(passed) / len(rows)
    print(f"    {len(passed):,} of {len(rows):,} calls pass every gate ({share:.1%})")
    if passed:
        mean = statistics.fmean(r["realised"] for r in passed)
        print(f"    mean realised, the call      {mean:+.3f}")
        held = statistics.fmean(r["held"] for r in passed)
        print(f"    mean realised, hold instead  {held:+.3f}")
        middle = statistics.median(r["realised"] for r in passed)
        print(f"    median realised push         {middle:+.3f}")
        print(
            f"    share that made money        "
            f"{sum(1 for r in passed if r['realised'] > 0) / len(passed):.1%}"
        )
    rest = [r for r in rows if not r["actionable"]]
    if rest:
        others = statistics.fmean(r["realised"] for r in rest)
        print(f"    mean realised, everything else {others:+.3f}")


if __name__ == "__main__":
    main()
