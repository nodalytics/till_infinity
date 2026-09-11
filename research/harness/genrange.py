"""Range Break: does the price really bounce N times before it breaks, and can
the bounce be faded for more than the spread?

Deriv's Range Break 100 and 200 are documented as range-bound processes that
break out of the range after, on average, 100 and 200 range-bound periods. Two
different claims sit in that sentence and they have very different values:

* **The rate.** If the break is memoryless like the Boom spike
  (`research/spiking.md`), a known rate is all it gives, and the rate alone does
  not make a trade.
* **The range.** If price is genuinely *reverting* inside a band, that is a
  directional edge conditioned on position within the band, and it is the only
  thing on this page that would pay directly. `research/catalogue.md` prices
  Range Break 200 at 0.116v to cross - the second cheapest instrument the broker
  offers - so the bar it has to clear is low.

The two indices give each other a control that does not depend on a detector:
whatever "a range-bound period" means operationally, **RB100 must break twice as
often as RB200**. A measurement where they break at the same rate is measuring
the detector.

## What would count as failure, written before running

* **The family claim fails** if the ratio of break rates between RB100 and
  RB200 is far from 2, at every threshold tried.
* **The fade dies** if the mean move after an extreme is within two standard
  errors of zero, or if it is smaller than the median spread - which is the
  `research/exiting.md` rule: an edge smaller than the cost of taking it is not
  an edge.
* **The run is void** if the post-extreme excursion is exactly 0.0.

## The controls

* **`volatility_75_index` and `volatility_100_index`**, which have no range
  mechanism, run through the identical detector and the identical fade. They
  give the false-positive rate of both.
* **A shuffle of each series' own tick moves**, which keeps the marginal
  distribution and destroys the ordering. Any reversion has to beat what the
  shuffle produces.
* **Split sample** by time, first half against second.
"""

from __future__ import annotations

import json
import math
import os
import random
import sqlite3
import statistics as st

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity"))
DB = os.environ.get("DB", os.path.join(os.path.expanduser("~/till_infinity/data"), "research.db"))
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/genrange.json"))

FEEDS = ["range_break_100_index", "range_break_200_index",
         "volatility_75_index", "volatility_100_index", "step_index"]

#: Zigzag thresholds, in multiples of the median absolute tick move. A property
#: of the generator should not depend much on which one is used; one that does
#: is a property of the detector.
ZIGZAG = (3.0, 5.0, 10.0)
#: Lookbacks for "a new extreme", in ticks, and horizons to measure after it.
LOOKBACKS = (60, 300, 900)
HORIZONS = (10, 30, 60, 300)


def ticks(conn, feed: str):
    rows = conn.execute(
        "SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts ASC", (feed,)
    ).fetchall()
    return [
        (int(ts), (float(b) + float(a)) / 2.0, float(a) - float(b))
        for ts, b, a in rows
        if b is not None and a is not None and b > 0
    ]


def mean_se(xs):
    n = len(xs)
    if n < 2:
        return float("nan"), float("nan")
    return st.fmean(xs), st.pstdev(xs) / math.sqrt(n)


def cv(xs):
    if len(xs) < 3:
        return float("nan")
    m = st.fmean(xs)
    return st.pstdev(xs) / abs(m) if m else float("nan")


def turning_points(mids: list[float], theta: float) -> list[tuple[int, float, int]]:
    """Zigzag: a turn is recorded when price retraces `theta` from the extreme.

    Returns (index, price, direction) where direction is the leg that just
    ended: +1 for a swing high, -1 for a swing low.
    """
    if not mids:
        return []
    pts = []
    ext_i, ext_p, direction = 0, mids[0], 0
    for i, p in enumerate(mids):
        if direction >= 0 and p >= ext_p:
            ext_i, ext_p = i, p
        elif direction <= 0 and p <= ext_p:
            ext_i, ext_p = i, p
        if direction >= 0 and ext_p - p >= theta:
            pts.append((ext_i, ext_p, +1))
            direction, ext_i, ext_p = -1, i, p
        elif direction <= 0 and p - ext_p >= theta:
            pts.append((ext_i, ext_p, -1))
            direction, ext_i, ext_p = +1, i, p
    return pts


def breaks_and_bounces(pts, tol: float) -> dict:
    """A turn that stays inside the band the last two turns set is a bounce; one
    that clears it by more than `tol` is a break. The band is rebuilt after a
    break, which is what "a new range forms" means operationally.
    """
    empty = {"bounces": 0, "breaks": 0, "bounces_per_break": float("nan"), "turns": len(pts),
             "run_mean": float("nan"), "run_cv": float("nan"),
             "gap_ticks_mean": float("nan"), "gap_ticks_cv": float("nan")}
    if len(pts) < 4:
        return empty
    lo = min(pts[0][1], pts[1][1])
    hi = max(pts[0][1], pts[1][1])
    bounces = breaks = 0
    since = 0
    runs = []
    gaps_idx = []
    last_break_i = pts[1][0]
    for i, p, _ in pts[2:]:
        if p > hi + tol or p < lo - tol:
            breaks += 1
            runs.append(since)
            gaps_idx.append(i - last_break_i)
            last_break_i = i
            since = 0
            lo = hi = p  # a new range starts from the breakout point
        else:
            bounces += 1
            since += 1
            lo, hi = min(lo, p), max(hi, p)
    return {
        "bounces": bounces,
        "breaks": breaks,
        "bounces_per_break": (bounces / breaks) if breaks else float("nan"),
        "turns": len(pts),
        "run_mean": st.fmean(runs) if runs else float("nan"),
        "run_cv": cv(runs),
        "gap_ticks_mean": st.fmean(gaps_idx) if gaps_idx else float("nan"),
        "gap_ticks_cv": cv(gaps_idx),
    }


def fade(mids: list[float], lookback: int, horizons, spread: float) -> dict:
    """When price makes a new `lookback`-tick extreme, what happens next?

    A range-bound process reverts: the mean move after a new high is negative
    and after a new low is positive. A martingale gives zero. The number that
    matters is not the sign but whether |mean| clears the spread.
    """
    n = len(mids)
    out = {}
    if n < lookback + max(horizons) + 1000:
        return out
    highs, lows = [], []
    for i in range(lookback, n - max(horizons)):
        w = mids[i - lookback : i]
        p = mids[i]
        if p > max(w):
            highs.append(i)
        elif p < min(w):
            lows.append(i)
    for h in horizons:
        after_hi = [mids[i + h] - mids[i] for i in highs]
        after_lo = [mids[i + h] - mids[i] for i in lows]
        mh, sh = mean_se(after_hi)
        ml, sl = mean_se(after_lo)
        # The fade: short the high, long the low. Both legs signed as profit.
        fade_pnl = [-x for x in after_hi] + [x for x in after_lo]
        mf, sf = mean_se(fade_pnl)
        out[h] = {
            "n_high": len(highs), "n_low": len(lows),
            "mean_after_high": mh, "se_after_high": sh,
            "mean_after_low": ml, "se_after_low": sl,
            "fade_gross": mf, "fade_se": sf,
            "fade_z": mf / sf if sf else float("nan"),
            "fade_net": mf - spread,
            "fade_in_spreads": (mf / spread) if spread else float("nan"),
        }
    return out


def variance_ratio(rets, q):
    n = len(rets)
    if n < q * 50:
        return float("nan")
    v1 = st.pvariance(rets)
    agg = [sum(rets[i : i + q]) for i in range(0, n - q + 1, q)]
    if len(agg) < 30 or v1 == 0:
        return float("nan")
    return st.pvariance(agg) / (q * v1)


def study(feed: str, rows) -> dict:
    if len(rows) < 10_000:
        return {"feed": feed, "skipped": True, "n": len(rows)}
    mids = [m for _, m, _ in rows]
    spreads = [s for _, _, s in rows]
    spread = st.median(spreads)
    moves = [b - a for a, b in zip(mids, mids[1:], strict=False)]
    med = st.median([abs(m) for m in moves if m != 0])

    got = {
        "feed": feed, "n_ticks": len(rows), "median_abs_move": med,
        "spread_median": spread, "spread_in_moves": spread / med if med else float("nan"),
        "zigzag": {}, "fade": {}, "vr": {q: variance_ratio(moves, q) for q in (2, 5, 10, 30, 60)},
    }
    for mult in ZIGZAG:
        theta = mult * med
        pts = turning_points(mids, theta)
        got["zigzag"][mult] = breaks_and_bounces(pts, theta)

    half = len(mids) // 2
    for lb in LOOKBACKS:
        got["fade"][lb] = {
            "all": fade(mids, lb, HORIZONS, spread),
            "first": fade(mids[:half], lb, HORIZONS, spread),
            "second": fade(mids[half:], lb, HORIZONS, spread),
        }

    rnd = random.Random(20260911)
    shuf = moves[:]
    rnd.shuffle(shuf)
    walk = [mids[0]]
    for m in shuf:
        walk.append(walk[-1] + m)
    got["shuffled"] = {
        "vr": {q: variance_ratio(shuf, q) for q in (2, 5, 10, 30, 60)},
        "fade": {lb: fade(walk, lb, HORIZONS, spread) for lb in LOOKBACKS},
        "zigzag": {mult: breaks_and_bounces(turning_points(walk, mult * med), mult * med)
                   for mult in ZIGZAG},
    }
    return got


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    results = [study(f, ticks(conn, f)) for f in FEEDS]
    for r in results:
        print("processed", r["feed"], flush=True)
    with open(OUT, "w") as fh:
        json.dump(results, fh, indent=1, default=str)
    print(f"wrote {OUT}\n")

    for mult in ZIGZAG:
        print(f"\n=== zigzag at {mult:g}x median move: bounces per break ===")
        print(f"{'feed':24s} {'turns':>7s} {'bounces':>8s} {'breaks':>7s} {'b/break':>8s} "
              f"{'runCV':>6s} {'gapCV':>6s} | {'shuf b/break':>12s}")
        for r in results:
            if r.get("skipped"):
                continue
            z, s = r["zigzag"][mult], r["shuffled"]["zigzag"][mult]
            print(f"{r['feed']:24s} {z['turns']:7d} {z['bounces']:8d} {z['breaks']:7d} "
                  f"{z['bounces_per_break']:8.3f} {z['run_cv']:6.3f} {z['gap_ticks_cv']:6.3f} "
                  f"| {s['bounces_per_break']:12.3f}")

    print("\n=== variance ratios on tick moves (1.0 = martingale) ===")
    print(f"{'feed':24s} " + " ".join(f"q={q:<7d}" for q in (2, 5, 10, 30, 60)) + "| shuf q=10")
    for r in results:
        if r.get("skipped"):
            continue
        print(f"{r['feed']:24s} " + " ".join(f"{r['vr'][q]:.5f} " for q in (2, 5, 10, 30, 60))
              + f"| {r['shuffled']['vr'][10]:.5f}")

    print("\n=== fade a new extreme: mean move after, spread charged ===")
    print(f"{'feed':24s} {'lb':>5s} {'h':>5s} {'n':>7s} {'gross':>11s} {'z':>7s} "
          f"{'spread':>9s} {'net':>11s} {'in spreads':>10s} | {'shuf gross':>11s}")
    for r in results:
        if r.get("skipped"):
            continue
        for lb in LOOKBACKS:
            allf = r["fade"][lb]["all"]
            shuf = r["shuffled"]["fade"][lb]
            for h in HORIZONS:
                if h not in allf:
                    continue
                f = allf[h]
                sg = shuf.get(h, {}).get("fade_gross", float("nan"))
                print(f"{r['feed']:24s} {lb:5d} {h:5d} {f['n_high'] + f['n_low']:7d} "
                      f"{f['fade_gross']:+11.5f} {f['fade_z']:+7.2f} {r['spread_median']:9.5f} "
                      f"{f['fade_net']:+11.5f} {f['fade_in_spreads']:+10.3f} | {sg:+11.5f}")

    print("\n=== fade, split sample (gross, in spreads) ===")
    print(f"{'feed':24s} {'lb':>5s} {'h':>5s} {'first':>10s} {'second':>10s}")
    for r in results:
        if r.get("skipped"):
            continue
        sp = r["spread_median"]
        for lb in LOOKBACKS:
            for h in HORIZONS:
                a = r["fade"][lb]["first"].get(h)
                b = r["fade"][lb]["second"].get(h)
                if not a or not b:
                    continue
                print(f"{r['feed']:24s} {lb:5d} {h:5d} "
                      f"{a['fade_gross'] / sp:10.3f} {b['fade_gross'] / sp:10.3f}")


if __name__ == "__main__":
    main()
