"""Does price *slow down* into a level it is about to respect?

research/force.md measured the force arriving at a level and found it predicts
a break - AUC 0.560 for `approach_vol`, 0.658 with depth. But `approach_vol` is
a single reading taken when the touch opens, and the desk describes a
**sequence**: price comes in, slows, pushes back, rejects, comes back.

Only the first frame of that is stored. This reconstructs the second from bars.

For each resolved touch, take the speed over the `NEAR` bars immediately before
it arrived and the speed over the `FAR` bars before those. Their ratio is
deceleration: below one means price was slowing into the level, above one means
it was still accelerating.

The claim to test: **a level being defended shows price slowing before it
turns**, which a snapshot at the moment of arrival cannot see.
"""

from __future__ import annotations

import json
import sqlite3
import statistics as st
from bisect import bisect_left

JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"
PRICES = "file:/app/.data/prices/prices.db?mode=ro"
LOW, HIGH = 300.0, 1800.0
HELD, BROKE = ("reject", "backcheck"), ("break", "trap")

#: Bars either side of the split. Short, because a level is approached over a
#: few bars and averaging over twenty would measure the trend instead.
NEAR, FAR = 3, 3

#: Bars to load per series. The touches measured are recent; loading the whole
#: store for every series is what made the first attempt time out.
BARS = 20_000


def touches(limit: int = 400_000) -> list[dict]:
    conn = sqlite3.connect(JOURNAL, uri=True)
    out = []
    for when, blob in conn.execute(
        "SELECT time, context FROM entries WHERE actor='structures' AND kind='outcome'"
        " ORDER BY time DESC LIMIT ?",
        (limit,),
    ):
        try:
            d = json.loads(blob or "{}")
        except (ValueError, TypeError):
            continue
        outcome = str(d.get("outcome") or "")
        feed, interval = str(d.get("feed") or ""), str(d.get("interval") or "")
        secs = d.get("seconds")
        if outcome not in HELD + BROKE or not feed or not interval or secs is None:
            continue
        try:
            secs = float(secs)
            approach = float(d.get("approach_vol") or 0.0)
        except (TypeError, ValueError):
            continue
        if not (LOW <= secs < HIGH):
            continue
        out.append(
            {
                "feed": feed,
                "interval": interval,
                "started": float(when) - secs,
                "broke": outcome in BROKE,
                "approach_vol": approach,
            }
        )
    return out


def series(conn, wanted: set[tuple[str, str]]) -> dict[tuple[str, str], tuple[list, list]]:
    """Every series loaded once, as parallel time and close lists.

    One query per *series* rather than per touch. The first version issued a
    query for each of ten thousand touches and did not finish in ten minutes;
    there are only a few hundred distinct series behind them.
    """
    out: dict[tuple[str, str], tuple[list, list]] = {}
    for feed, interval in sorted(wanted):
        # Bounded, and reversed back into order. Without the limit this loads
        # every bar the store holds for every series, and there is no index on
        # (feed, interval, ts) - it did not finish in ten minutes. The touches
        # being measured are recent, so recent bars are all that is needed.
        rows = conn.execute(
            "SELECT ts, close FROM bars WHERE feed=? AND interval=? ORDER BY ts DESC LIMIT ?",
            (feed, interval, BARS),
        ).fetchall()
        rows.reverse()
        if len(rows) > NEAR + FAR + 1:
            out[(feed, interval)] = ([float(t) for t, _ in rows], [float(c) for _, c in rows])
    return out


def slowing(held: tuple[list, list], started: float) -> float | None:
    """Speed over the bars just before arrival, over the speed before those.

    Below one means price was decelerating into the level. None when there are
    not enough bars, or when the earlier leg did not move - a ratio against
    nothing is not a deceleration.
    """
    times, prices = held
    at = bisect_left(times, started)
    if at < NEAR + FAR + 1:
        return None
    closes = prices[at - (NEAR + FAR + 1) : at]
    early = closes[: FAR + 1]
    late = closes[FAR:]
    far = abs(early[-1] - early[0]) / max(len(early) - 1, 1)
    near = abs(late[-1] - late[0]) / max(len(late) - 1, 1)
    if far <= 0:
        return None
    return near / far


def auc(scored: list[tuple[float, bool]]) -> float:
    scored = sorted(scored, key=lambda kv: kv[0])
    positives = sum(1 for _s, b in scored if b)
    negatives = len(scored) - positives
    if not positives or not negatives:
        return 0.5
    ranks, i = {}, 0
    while i < len(scored):
        j = i
        while j + 1 < len(scored) and scored[j + 1][0] == scored[i][0]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = shared
        i = j + 1
    got = sum(ranks[k] for k, (_s, b) in enumerate(scored) if b)
    return (got - positives * (positives + 1) / 2.0) / (positives * negatives)


def ladder(rows: list[dict], name: str, buckets: int = 5) -> None:
    ordered = sorted(rows, key=lambda r: r[name])
    step = len(ordered) // buckets
    if step < 10:
        print(f"   {name}: too few")
        return
    print(f"   {name:14s}", end="")
    for i in range(buckets):
        cut = ordered[i * step : (i + 1) * step] if i < buckets - 1 else ordered[i * step :]
        print(f" {sum(1 for r in cut if r['broke']) / len(cut):6.1%}", end="")
    print()


def main() -> None:
    seen = touches()
    print(f"{len(seen)} resolved touches in {LOW:.0f}-{HIGH:.0f}s\n")
    prices = sqlite3.connect(PRICES, uri=True)

    loaded = series(prices, {(r["feed"], r["interval"]) for r in seen})
    print(f"{len(loaded)} series loaded")
    got = []
    for r in seen:
        held = loaded.get((r["feed"], r["interval"]))
        if held is None:
            continue
        ratio = slowing(held, r["started"])
        if ratio is None:
            continue
        r["slowing"] = ratio
        got.append(r)

    print(f"{len(got)} had enough bars either side to measure deceleration")
    if len(got) < 300:
        print("too few to say anything")
        return
    broke = sum(1 for r in got if r["broke"])
    print(f"{broke} of them broke ({broke / len(got):.1%})\n")

    print("break rate across each feature, slowest fifth to fastest:")
    ladder(got, "slowing")
    ladder(got, "approach_vol")

    print("\nseparation, as AUC of the feature predicting a break:")
    print(f"   {'slowing':14s} {auc([(r['slowing'], r['broke']) for r in got]):.4f}")
    print(f"   {'approach_vol':14s} {auc([(r['approach_vol'], r['broke']) for r in got]):.4f}")

    mid = st.median(r["slowing"] for r in got)
    for label, cut in (
        ("decelerating", [r for r in got if r["slowing"] <= mid]),
        ("accelerating", [r for r in got if r["slowing"] > mid]),
    ):
        rate = sum(1 for r in cut if r["broke"]) / len(cut)
        print(f"\n{label:14s} {len(cut):5d} touches, {rate:.1%} break")

    # Is it saying something `approach_vol` does not?
    pairs = [(r["slowing"], r["approach_vol"]) for r in got]
    mx = st.fmean(p[0] for p in pairs)
    my = st.fmean(p[1] for p in pairs)
    sx = st.pstdev(p[0] for p in pairs) or 1.0
    sy = st.pstdev(p[1] for p in pairs) or 1.0
    corr = st.fmean((a - mx) * (b - my) for a, b in pairs) / (sx * sy)
    print(f"\ncorrelation with approach_vol: {corr:+.3f}")


if __name__ == "__main__":
    main()
