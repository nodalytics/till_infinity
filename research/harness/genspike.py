"""Boom and Crash: is the grind deterministic, and does the arithmetic close?

`research/spiking.md` measured one instrument and left the family open. It found
the spike arrival memoryless - coefficient of variation 0.99 against 1.00 - so
nothing can call one, and it found the *grind* nearly deterministic: on Boom 500
the whole per-minute down-leg distribution sat inside a 0.24 band.

A memoryless arrival still has a rate, and a rate plus a grind plus a spike size
is a complete description of the instrument. So the question here is not
prediction, it is **whether the arithmetic closes**:

    E[move per tick] = (1 - p) * (-grind) + p * E[spike]

If that is zero, the generator is a fair martingale, the grind is exactly paid
for by the spike, and there is no directional trade on Boom or Crash at any
horizon - which would be the single most useful null available, because the
spike indices are 20% of trades and 42% of the loss (`docs/todo.md`).

If it is *not* zero by more than the spread, that is a drift on an instrument
whose cost to cross is 0.13-0.19v (`research/catalogue.md`) and it is directly
sizeable.

Three things get measured that spiking.md could not:

1. **The whole family.** boom/crash 300, 500 and 1000. The documented rates are
   one spike per 300, 500 and 1000 ticks, so the *ratios* between them are a
   prediction that does not depend on where a detector's threshold sits: Boom
   300 must spike 3.33 times as often as Boom 1000.
2. **Ticks, not bars.** 24 hours of ticks resolve individual spikes, where a 1m
   bar merges a spike with the grind around it. The grind step and the spike
   size are separate objects at tick resolution.
3. **The stop.** A short on Boom has a bounded gain per tick and an unbounded
   loss, so the question of what a stop is worth is not statistical: it is
   whether a single tick jumps through it. That is measurable directly.

## What would count as failure, written before running

* **The family claim fails** if the measured spike rates do not order 300 <
  500 < 1000 in waiting time, or if the ratio of rates is far from the ratio of
  names.
* **The grind-determinism claim fails** if the coefficient of variation of the
  grind step is not small - say above 0.2 - at tick resolution.
* **The drift claim dies** (and this is the expected outcome) if the mean per-bar
  return is within two standard errors of zero in *both* halves of the split
  sample and smaller than the spread.
* **The run is void** if the mean move lands on exactly 0.0.

## The control

`volatility_75_index` measured identically. It has no spike mechanism at all, so
its spike count under the same detector is the false-positive rate of the
detector, and its drift is what a series with no mechanism produces on this
sample size. A Boom drift is only a finding if it is larger than that.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics as st

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/genspike.json"))

BOOM = ["boom_300_index", "boom_500_index", "boom_1000_index"]
CRASH = ["crash_300_index", "crash_500_index", "crash_1000_index"]
JUMP = ["jump_10_index", "jump_25_index", "jump_50_index", "jump_75_index", "jump_100_index"]
CONTROL = ["volatility_75_index", "volatility_100_index"]
FEEDS = BOOM + CRASH + JUMP + CONTROL

#: The published rate, in ticks between spikes, from the instrument's own name.
DOCUMENTED = {
    "boom_300_index": 300, "boom_500_index": 500, "boom_1000_index": 1000,
    "crash_300_index": 300, "crash_500_index": 500, "crash_1000_index": 1000,
}

#: A spike is a tick whose move is this many times the median absolute move.
#: Reported at three thresholds, because a rate that depends on the threshold is
#: a detector artefact rather than a property of the generator.
THRESHOLDS = (5.0, 10.0, 20.0)


def ticks(conn, feed: str):
    rows = conn.execute(
        "SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts ASC", (feed,)
    ).fetchall()
    return [
        (int(ts), (float(b) + float(a)) / 2.0, float(a) - float(b))
        for ts, b, a in rows
        if b is not None and a is not None and b > 0
    ]


def bars(conn, feed: str):
    rows = conn.execute(
        "SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval='1m' ORDER BY ts ASC",
        (feed,),
    ).fetchall()
    return [
        (int(ts), float(o), float(h), float(lo), float(c))
        for ts, o, h, lo, c in rows
        if None not in (o, h, lo, c) and o > 0
    ]


def mean_se(xs) -> tuple[float, float]:
    n = len(xs)
    if n < 2:
        return float("nan"), float("nan")
    m = st.fmean(xs)
    return m, st.pstdev(xs) / math.sqrt(n)


def quant(xs, q):
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def cv(xs) -> float:
    if len(xs) < 3:
        return float("nan")
    m = st.fmean(xs)
    return st.pstdev(xs) / abs(m) if m else float("nan")


def tick_study(feed: str, rows) -> dict:
    if len(rows) < 5000:
        return {"feed": feed, "skipped": True, "n": len(rows)}
    moves = [m1 - m0 for (_, m0, _), (_, m1, _) in zip(rows, rows[1:], strict=False)]
    stamps = [t for (t, _, _), _ in zip(rows[1:], moves, strict=False)]
    spreads = [s for _, _, s in rows]
    absm = [abs(m) for m in moves if m != 0]
    med = st.median(absm) if absm else float("nan")

    up = [m for m in moves if m > 0]
    dn = [-m for m in moves if m < 0]
    got = {
        "feed": feed,
        "n_ticks": len(rows),
        "per_sec": len(rows) / ((rows[-1][0] - rows[0][0]) / 1000.0),
        "median_abs_move": med,
        "spread_median": st.median(spreads),
        "spread_in_median_moves": st.median(spreads) / med if med else float("nan"),
        "up": {"n": len(up), "median": st.median(up) if up else float("nan"),
               "cv": cv(up), "p99": quant(up, 0.99), "max": max(up) if up else float("nan")},
        "down": {"n": len(dn), "median": st.median(dn) if dn else float("nan"),
                 "cv": cv(dn), "p99": quant(dn, 0.99), "max": max(dn) if dn else float("nan")},
        "thresholds": {},
    }
    mean_move, se_move = mean_se(moves)
    got["mean_move_per_tick"] = mean_move
    got["se_move_per_tick"] = se_move
    got["z_move_per_tick"] = mean_move / se_move if se_move else float("nan")

    for mult in THRESHOLDS:
        cut = mult * med
        idx = [i for i, m in enumerate(moves) if abs(m) > cut]
        sizes = [moves[i] for i in idx]
        gaps_ticks = [b - a for a, b in zip(idx, idx[1:], strict=False)]
        gaps_min = [(stamps[b] - stamps[a]) / 60_000.0 for a, b in zip(idx, idx[1:], strict=False)]
        grind = [m for i, m in enumerate(moves) if abs(m) <= cut]
        gm, gse = mean_se(grind)
        sm, sse = mean_se(sizes)
        rate = len(idx) / len(moves) if moves else float("nan")
        got["thresholds"][mult] = {
            "cut": cut,
            "n_spikes": len(idx),
            "ticks_per_spike": (len(moves) / len(idx)) if idx else float("inf"),
            "min_per_spike": st.fmean(gaps_min) if gaps_min else float("nan"),
            "gap_cv": cv(gaps_min),
            "gap_ticks_cv": cv(gaps_ticks),
            "spike_mean": sm,
            "spike_median": st.median(sizes) if sizes else float("nan"),
            "spike_max": max(sizes, key=abs) if sizes else float("nan"),
            "grind_mean": gm,
            "grind_median": st.median(grind) if grind else float("nan"),
            "grind_cv_signed": cv([g for g in grind if g != 0]),
            "grind_p01": quant(grind, 0.01),
            "grind_p99": quant(grind, 0.99),
            # The arithmetic: does grind * (1-p) + spike * p come to zero?
            "closure": (1 - rate) * gm + rate * sm if not math.isnan(gm) else float("nan"),
            "closure_over_se": ((1 - rate) * gm + rate * sm) / se_move if se_move else float("nan"),
        }
    return got


def bar_study(feed: str, rows, spread: float) -> dict:
    """Sixty days of 1m bars - the sample the drift question actually needs.

    Twenty-four hours of ticks is 86,400 observations of a per-tick move whose
    standard error is still large next to a grind. Sixty days of minutes is the
    horizon a position is held over anyway.
    """
    if len(rows) < 5000:
        return {"feed": feed, "skipped": True}
    half = len(rows) // 2
    out = {"feed": feed, "n_bars": len(rows), "halves": {}}
    for name, part in (("all", rows), ("first30", rows[:half]), ("last30", rows[half:])):
        chg, lr, up_leg, dn_leg = [], [], [], []
        for (t0, _, _, _, c0), (t1, o1, h1, l1, c1) in zip(part, part[1:], strict=False):
            if t1 - t0 != 60_000:
                continue
            chg.append(c1 - c0)
            lr.append(math.log(c1 / c0))
            up_leg.append(h1 - o1)
            dn_leg.append(o1 - l1)
        m, se = mean_se(chg)
        lm, lse = mean_se(lr)
        out["halves"][name] = {
            "n": len(chg),
            "mean_chg": m, "se_chg": se, "z_chg": m / se if se else float("nan"),
            "mean_logret": lm, "se_logret": lse, "z_logret": lm / lse if lse else float("nan"),
            "drift_per_hour": m * 60,
            "drift_per_hour_in_spreads": (m * 60 / spread) if spread else float("nan"),
            "up_leg": {q: quant(up_leg, q) for q in (0.5, 0.9, 0.99)},
            "down_leg": {q: quant(dn_leg, q) for q in (0.5, 0.9, 0.99)},
            "up_leg_max": max(up_leg) if up_leg else float("nan"),
            "down_leg_max": max(dn_leg) if dn_leg else float("nan"),
        }
    # What a stop is worth: how often a single bar's adverse leg jumps past it.
    legs_up, legs_dn = [], []
    for (t0, _, _, _, _), (t1, o1, h1, l1, _) in zip(rows, rows[1:], strict=False):
        if t1 - t0 == 60_000:
            legs_up.append(h1 - o1)
            legs_dn.append(o1 - l1)
    typical_dn = st.median(legs_dn) if legs_dn else float("nan")
    typical_up = st.median(legs_up) if legs_up else float("nan")
    out["gap_through"] = {}
    for mult in (2, 5, 10, 20, 50):
        # For a short (the Boom trade): the adverse leg is the up-leg. Scale the
        # stop in units of the *typical* grind, which is the down-leg on Boom.
        stop_short = mult * typical_dn
        stop_long = mult * typical_up
        out["gap_through"][mult] = {
            "stop_short": stop_short,
            "frac_bars_through_short": sum(1 for u in legs_up if u > stop_short) / len(legs_up),
            "stop_long": stop_long,
            "frac_bars_through_long": sum(1 for d in legs_dn if d > stop_long) / len(legs_dn),
        }
    return out


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    results = []
    for feed in FEEDS:
        t = tick_study(feed, ticks(conn, feed))
        spread = t.get("spread_median", float("nan"))
        b = bar_study(feed, bars(conn, feed), spread)
        results.append({"feed": feed, "ticks": t, "bars": b})
        print(f"processed {feed}", flush=True)

    with open(OUT, "w") as fh:
        json.dump(results, fh, indent=1, default=str)
    print(f"wrote {OUT}\n")

    print("=== tick-level shape (24h of ticks) ===")
    print(f"{'feed':24s} {'ticks':>7s} {'t/s':>6s} {'med|m|':>9s} {'spread':>9s} {'sprd/mv':>8s} "
          f"{'up n':>7s} {'dn n':>7s} {'up cv':>7s} {'dn cv':>7s}")
    for r in results:
        t = r["ticks"]
        if t.get("skipped"):
            print(f"{r['feed']:24s} skipped ({t['n']})")
            continue
        print(f"{t['feed']:24s} {t['n_ticks']:7d} {t['per_sec']:6.3f} {t['median_abs_move']:9.5f} "
              f"{t['spread_median']:9.5f} {t['spread_in_median_moves']:8.2f} "
              f"{t['up']['n']:7d} {t['down']['n']:7d} {t['up']['cv']:7.3f} {t['down']['cv']:7.3f}")

    for mult in THRESHOLDS:
        print(f"\n=== spike detection at {mult:g}x the median move ===")
        print(f"{'feed':24s} {'doc':>5s} {'spikes':>7s} {'ticks/spk':>10s} {'ratio':>7s} "
              f"{'min/spk':>8s} {'gapCV':>6s} {'grind':>10s} {'spike':>10s} {'closure':>11s} {'/se':>7s}")
        for r in results:
            t = r["ticks"]
            if t.get("skipped"):
                continue
            d = t["thresholds"][mult]
            doc = DOCUMENTED.get(r["feed"])
            ratio = (d["ticks_per_spike"] / doc) if doc else float("nan")
            print(f"{r['feed']:24s} {(str(doc) if doc else '-'):>5s} {d['n_spikes']:7d} "
                  f"{d['ticks_per_spike']:10.1f} {ratio:7.3f} {d['min_per_spike']:8.2f} "
                  f"{d['gap_cv']:6.3f} {d['grind_median']:10.5f} {d['spike_median']:10.5f} "
                  f"{d['closure']:+11.3e} {d['closure_over_se']:+7.2f}")

    print("\n=== drift on 60 days of 1m bars, split sample, spread charged ===")
    print(f"{'feed':24s} {'half':8s} {'n':>7s} {'mean chg':>12s} {'z':>7s} "
          f"{'drift/hr':>11s} {'in spreads':>11s}")
    for r in results:
        b = r["bars"]
        if b.get("skipped"):
            continue
        for name in ("first30", "last30", "all"):
            h = b["halves"][name]
            print(f"{r['feed']:24s} {name:8s} {h['n']:7d} {h['mean_chg']:+12.3e} "
                  f"{h['z_chg']:+7.2f} {h['drift_per_hour']:+11.4f} "
                  f"{h['drift_per_hour_in_spreads']:+11.3f}")

    print("\n=== what a stop is worth: fraction of single bars that jump through it ===")
    print(f"{'feed':24s} " + " ".join(f"{m}x-short" for m in (2, 5, 10, 20, 50)))
    for r in results:
        b = r["bars"]
        if b.get("skipped"):
            continue
        print(f"{r['feed']:24s} " + " ".join(
            f"{b['gap_through'][m]['frac_bars_through_short']:8.5f}" for m in (2, 5, 10, 20, 50)))
    print(f"\n{'feed':24s} " + " ".join(f"{m}x-long " for m in (2, 5, 10, 20, 50)))
    for r in results:
        b = r["bars"]
        if b.get("skipped"):
            continue
        print(f"{r['feed']:24s} " + " ".join(
            f"{b['gap_through'][m]['frac_bars_through_long']:8.5f}" for m in (2, 5, 10, 20, 50)))


if __name__ == "__main__":
    main()
