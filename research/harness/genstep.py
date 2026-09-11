"""Step Index moves in fixed increments - so is the walk exactly what it says?

Deriv's subtitle for Step Index is the most specific claim on the whole book:
*"equal probability of up/down movement in a price series with a fixed step size
of 0.1"*. Everything follows from that if it is true:

* the move distribution is not estimated, it is **known** - one value, two signs;
* reachability of a level in N ticks is a gambler's-ruin computation with exact
  probabilities rather than a statistical one;
* and a symmetric barrier trade has an exactly computable expectancy, which -
  with a fair coin - is **minus the spread and nothing else**.

That last consequence is why this is worth running even though its likely
answer is a null. `research/exiting.md` found the spread was worth 0.363R on the
replayed population; here the spread can be expressed in *steps*, which is a
unit that does not need a volatility estimate to interpret.

The interesting result would be either of the two ways the claim can fail:

* the coin is **not fair** - a persistent up-fraction away from 0.5 is a drift,
  and a drift on a known step size is directly sizeable;
* the signs are **not independent** - serial correlation in the sign sequence is
  an edge whose size is computable in steps and therefore directly comparable
  with the spread.

## What would count as failure, written before running

* The **fixed-step claim fails** if the tick-to-tick differences are not
  concentrated on one magnitude.
* The **fair-coin claim survives** (and the edge dies) if the up-fraction is
  within three standard errors of 0.5 *in both halves* and every sign
  autocorrelation from lag 1 to 30 is inside +-3/sqrt(n).
* The **run is void** if a statistic lands on exactly its null - an
  autocorrelation of precisely 0.0000 means a dead input.

## The control

`gold` measured identically. A real feed's tick sign sequence must show the
bid-ask bounce as strong *negative* lag-1 autocorrelation. If it does not, the
sign extraction is broken and nothing about Step Index can be read from it.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics as st
from collections import Counter

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/genstep.json"))

FEEDS = ["step_index", "range_break_100_index", "range_break_200_index", "gold", "eurusd"]

#: Twenty-four hours of ticks is 86,393 coin flips, and the standard error on
#: the up-fraction is 0.0017 - just too coarse to rule out the 0.005 bias a
#: 100-step barrier would need to break even. Sixty days of one-minute bars are
#: 5.2 million flips of the same coin, seen through their sums, and settle it.
#: `BARS_PER_TICK_RATE` is how many ticks fall in a minute at 1/s.
TICKS_PER_MINUTE = 60
LAGS = tuple(range(1, 31))


def ticks(conn, feed: str):
    return conn.execute(
        "SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts ASC", (feed,)
    ).fetchall()


def acf(xs, lag: int) -> float:
    n = len(xs)
    if n <= lag + 10:
        return float("nan")
    m = st.fmean(xs)
    num = sum((xs[i] - m) * (xs[i + lag] - m) for i in range(n - lag))
    den = sum((x - m) ** 2 for x in xs)
    return num / den if den else float("nan")


def runs_z(signs: list[int]) -> float:
    """Wald-Wolfowitz runs test on the sign sequence.

    Catches dependence the lag-1 autocorrelation can miss - alternation and
    long persistent stretches both show up here.
    """
    seq = [s for s in signs if s != 0]
    n = len(seq)
    if n < 100:
        return float("nan")
    n_pos = sum(1 for s in seq if s > 0)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    runs = 1 + sum(1 for a, b in zip(seq, seq[1:], strict=False) if a != b)
    mu = 2 * n_pos * n_neg / n + 1
    var = (mu - 1) * (mu - 2) / (n - 1) if n > 1 else 0
    return (runs - mu) / math.sqrt(var) if var > 0 else float("nan")


def analyse(feed: str, rows) -> dict:
    mids = [(int(ts), (float(b) + float(a)) / 2.0, float(a) - float(b))
            for ts, b, a in rows if b is not None and a is not None and b > 0]
    if len(mids) < 1000:
        return {"feed": feed, "n": len(mids), "skipped": True}
    spreads = [s for _, _, s in mids]
    diffs = [round(m1 - m0, 10) for (_, m0, _), (_, m1, _) in zip(mids, mids[1:], strict=False)]
    nz = [d for d in diffs if d != 0]
    mag = Counter(round(abs(d), 8) for d in nz)
    top = mag.most_common(12)
    total_nz = sum(mag.values())
    step = top[0][0] if top else float("nan")

    signs = [1 if d > 0 else (-1 if d < 0 else 0) for d in diffs]
    nzsigns = [s for s in signs if s != 0]
    n = len(nzsigns)
    up = sum(1 for s in nzsigns if s > 0)
    p_up = up / n if n else float("nan")
    se = math.sqrt(0.25 / n) if n else float("nan")

    half = len(nzsigns) // 2
    halves = {}
    for name, part in (("first", nzsigns[:half]), ("second", nzsigns[half:])):
        m = len(part)
        u = sum(1 for s in part if s > 0)
        halves[name] = {
            "n": m,
            "p_up": u / m if m else float("nan"),
            "se": math.sqrt(0.25 / m) if m else float("nan"),
            "z": ((u / m) - 0.5) / math.sqrt(0.25 / m) if m else float("nan"),
            "acf1": acf(part, 1),
            "runs_z": runs_z(part),
        }

    # Gaps between ticks - does it really tick once a second?
    gaps = [t1 - t0 for (t0, _, _), (t1, _, _) in zip(mids, mids[1:], strict=False)]
    gaps_ms = Counter(g for g in gaps if 0 < g < 20_000)

    return {
        "feed": feed,
        "n_ticks": len(mids),
        "n_moves": n,
        "zero_moves": len(diffs) - len(nz),
        "step_mode": step,
        "step_share": (top[0][1] / total_nz) if top else float("nan"),
        "magnitudes": [(k, v, v / total_nz) for k, v in top],
        "p_up": p_up,
        "p_up_se": se,
        "p_up_z": (p_up - 0.5) / se if se else float("nan"),
        "acf": {lag: acf(nzsigns, lag) for lag in LAGS},
        "acf_band": 3 / math.sqrt(n) if n else float("nan"),
        "runs_z": runs_z(nzsigns),
        "halves": halves,
        "spread_median": st.median(spreads),
        "spread_p90": sorted(spreads)[int(0.9 * len(spreads))],
        "spread_in_steps": (st.median(spreads) / step) if step else float("nan"),
        "tick_gap_modes": gaps_ms.most_common(5),
        "tick_per_sec": len(mids) / ((mids[-1][0] - mids[0][0]) / 1000.0),
    }


def reachability(step: float, spread: float, p_up: float) -> list[dict]:
    """Gambler's ruin on the measured coin, with the spread charged.

    A symmetric k-step target and k-step stop. With a fair coin the hit
    probability is exactly 0.5 whatever k is - that is the point of the exercise,
    and it is arithmetic rather than a fit. The spread enters as a fixed cost in
    steps, paid once, which shifts the *effective* barriers rather than the
    probabilities: crossing costs `spread` before anything is won.
    """
    out = []
    q = 1 - p_up
    for k in (1, 2, 5, 10, 20, 50, 100):
        if abs(p_up - 0.5) < 1e-12:
            hit = 0.5
        else:
            r = q / p_up
            hit = (1 - r**k) / (1 - r ** (2 * k))
        # Gross payoff in price: win k*step, lose k*step. Spread paid on entry.
        gross = hit * (k * step) - (1 - hit) * (k * step)
        out.append({
            "k": k,
            "hit": hit,
            "gross": gross,
            "net": gross - spread,
            "gross_in_steps": gross / step,
            "net_in_steps": (gross - spread) / step,
            "breakeven_hit": 0.5 + spread / (2 * k * step),
        })
    return out


def bar_drift(conn, feed: str, step: float) -> dict:
    """The same fair-coin test, read off sixty days of minutes instead of a day
    of ticks.

    A minute is a sum of `TICKS_PER_MINUTE` steps, so the mean per-minute change
    is `step * ticks * (2p - 1)` and the bias inverts directly. This is the
    tighter of the two tests by a factor of about eight, and it is the one that
    decides whether the large-k barrier in the table above is real or is the
    tick sample's own noise amplified.
    """
    rows = conn.execute(
        "SELECT ts, close FROM bars WHERE feed=? AND interval='1m' ORDER BY ts ASC", (feed,)
    ).fetchall()
    chg = [
        float(c1) - float(c0)
        for (t0, c0), (t1, c1) in zip(rows, rows[1:], strict=False)
        if int(t1) - int(t0) == 60_000 and c0 and c1
    ]
    n = len(chg)
    if n < 1000:
        return {"n": n, "skipped": True}
    m = st.fmean(chg)
    se = st.pstdev(chg) / math.sqrt(n)
    flips = n * TICKS_PER_MINUTE
    bias = m / (step * TICKS_PER_MINUTE)          # = 2p - 1
    bias_se = se / (step * TICKS_PER_MINUTE)
    half = n // 2
    halves = {}
    for name, part in (("first30", chg[:half]), ("last30", chg[half:])):
        mm = st.fmean(part)
        ss = st.pstdev(part) / math.sqrt(len(part))
        halves[name] = {
            "n": len(part),
            "p_up": 0.5 + mm / (2 * step * TICKS_PER_MINUTE),
            "z": mm / ss if ss else float("nan"),
        }
    return {
        "n_minutes": n,
        "implied_flips": flips,
        "mean_chg": m,
        "se_chg": se,
        "z": m / se if se else float("nan"),
        "p_up": 0.5 + bias / 2,
        "p_up_se": bias_se / 2,
        "halves": halves,
    }


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    results = []
    for feed in FEEDS:
        rows = ticks(conn, feed)
        got = analyse(feed, rows)
        results.append(got)
        if got.get("skipped"):
            print(f"{feed}: {got['n']} ticks, skipped")
            continue
        print(
            f"\n=== {feed} ===  {got['n_ticks']} ticks, {got['tick_per_sec']:.3f}/s, "
            f"{got['zero_moves']} zero moves"
        )
        print(f"  step magnitudes (top): " + ", ".join(
            f"{k:g}x{v} ({s:.4%})" for k, v, s in got["magnitudes"][:8]))
        print(f"  mode step {got['step_mode']:g} carries {got['step_share']:.4%} of moves")
        print(f"  p(up) = {got['p_up']:.6f}  se {got['p_up_se']:.6f}  z = {got['p_up_z']:+.2f}")
        for name, h in got["halves"].items():
            print(f"    {name:6s} n={h['n']:7d} p_up={h['p_up']:.6f} z={h['z']:+.2f} "
                  f"acf1={h['acf1']:+.5f} runs_z={h['runs_z']:+.2f}")
        band = got["acf_band"]
        exceed = [(l, v) for l, v in got["acf"].items() if not math.isnan(v) and abs(v) > band]
        print(f"  sign acf band +-{band:.5f}; lags outside: "
              + (", ".join(f"L{l}={v:+.5f}" for l, v in exceed) if exceed else "none"))
        print("  acf L1..L10: " + " ".join(f"{got['acf'][l]:+.5f}" for l in range(1, 11)))
        print(f"  runs z = {got['runs_z']:+.3f}")
        print(f"  spread median {got['spread_median']:g} = {got['spread_in_steps']:.3f} steps, "
              f"p90 {got['spread_p90']:g}")
        print(f"  tick gaps (ms, top): {got['tick_gap_modes']}")

        if feed in ("step_index", "range_break_100_index", "range_break_200_index"):
            d = bar_drift(conn, feed, got["step_mode"])
            got["bar_drift"] = d
            if not d.get("skipped"):
                print(f"  --- the same coin over 60 days of 1m bars ---")
                print(f"  {d['n_minutes']} minutes = {d['implied_flips']} implied flips")
                print(f"  p(up) = {d['p_up']:.6f} +- {d['p_up_se']:.6f}  "
                      f"(mean 1m change {d['mean_chg']:+.5e}, z {d['z']:+.2f})")
                for name, h in d["halves"].items():
                    print(f"    {name}: p_up={h['p_up']:.6f} z={h['z']:+.2f}")

        if feed == "step_index":
            print("\n  --- symmetric barrier, measured coin, spread charged ---")
            print(f"  {'k steps':>8s} {'p(hit)':>9s} {'gross':>11s} {'net':>11s} "
                  f"{'net/step':>9s} {'breakeven p':>12s}")
            for r in reachability(got["step_mode"], got["spread_median"], got["p_up"]):
                print(f"  {r['k']:8d} {r['hit']:9.6f} {r['gross']:+11.5f} {r['net']:+11.5f} "
                      f"{r['net_in_steps']:+9.3f} {r['breakeven_hit']:12.6f}")

    with open(OUT, "w") as fh:
        json.dump(results, fh, indent=1, default=str)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
