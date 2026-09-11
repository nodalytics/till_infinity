"""If the process is known and the game is fair, the spread is the whole
expectancy - so is the broker's spread priced against the volatility the
instrument *has*, or against the one in its name?

Two results make this question answerable exactly rather than statistically.
`research/generators.md` established that a `Volatility N Index` realises N to
within 0.49%, and that a `Jump N Index` realises **1.322 x N** on all five feeds
(1.3128 to 1.3382). So for seventeen instruments the volatility is known to
three figures, the spread is quoted, and the comparison between them is
arithmetic.

That matters because of the theorem on the rest of this page. A predictable
position on a martingale has zero gross expectancy, so `E[net] = -cost` and the
only three ways a fully known process can pay are:

1. an **asymmetry in the generator** - ruled out by `generators.md` four ways;
2. a **payoff whose value differs from its price**;
3. a **cost mispriced against the known volatility**.

(3) cannot by itself make expectancy positive - a cheaper spread makes the loss
smaller, not the sign different. What it can do is prove that the venue prices
off the *name*. And if the venue prices anything **convex** off the name, (2)
follows immediately and is worth a computable amount, because a `Jump N` option
priced at `N` on a process that runs at `1.322 N` is mispriced by a factor that
grows with how far out of the money it is.

## What is derived

* the **cost of a crossing in units of the known process**: `c / sigma`, and the
  horizon `t* = (c/sigma)^2` at which the standard deviation of the move first
  equals the spread. Both are exact once `sigma` is known;
* the **value ratio of a one-touch** priced at the name against its true value:
  `Phi(-x) / Phi(-1.322 x)` where `x = a / (sigma_real sqrt(T))`;
* the **barrier shift from discrete monitoring**, `0.5826 * sigma * sqrt(dt)`,
  which moves every touch price in the venue's favour and is derived in
  `derivegbm.py`.

## What would count as failure, written before running

1. **The name hypothesis dies** if spread-per-unit-of-*stated*-volatility is no
   more constant within the Jump family than spread-per-unit-of-*realised*
   volatility. The claim is specifically that the venue's formula uses N.
2. **The premise dies** if the Volatility family - where name and process agree -
   does not come out with a flat cost per unit of volatility. That family is the
   control: it has no gap to find, so any structure there is my estimator.
3. **The touch arithmetic dies** if the measured touch frequency on the Jump
   feeds is not above what name-sigma predicts, or if it is above what realised
   sigma predicts on the Volatility feeds, where the two coincide.
4. **The run is void** if the realised volatilities here do not reproduce
   `generators.md` to within its own 0.5%.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3

import numpy as np
from scipy.stats import norm

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/derivecost.json"))

MINUTES_PER_YEAR = 365 * 24 * 60
SECONDS_PER_YEAR = 365 * 24 * 3600
BETA = 0.5825971579

NAME = {
    "volatility_10_index": 10.0, "volatility_25_index": 25.0,
    "volatility_50_index": 50.0, "volatility_75_index": 75.0,
    "volatility_100_index": 100.0, "volatility_10_1s_index": 10.0,
    "volatility_25_1s_index": 25.0, "volatility_50_1s_index": 50.0,
    "volatility_75_1s_index": 75.0, "volatility_100_1s_index": 100.0,
    "volatility_150_1s_index": 150.0, "volatility_250_1s_index": 250.0,
    "jump_10_index": 10.0, "jump_25_index": 25.0, "jump_50_index": 50.0,
    "jump_75_index": 75.0, "jump_100_index": 100.0,
}
FAMILY = {f: ("jump" if f.startswith("jump") else "vol") for f in NAME}
OTHER = ["boom_300_index", "boom_500_index", "boom_1000_index",
         "crash_300_index", "crash_500_index", "crash_1000_index",
         "step_index", "range_break_100_index", "range_break_200_index"]
REAL = ["gold", "eurusd", "btc", "us100", "usdjpy", "silver"]

#: 1440-minute windows were tried and dropped: 60 non-overlapping windows in
#: 60 days cannot measure a probability of a few percent.
TOUCH_T = [15, 60, 240]
TOUCH_X = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]


def bars(feed: str):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT close FROM bars WHERE feed=? AND interval='1m' ORDER BY ts",
                        (feed,)).fetchall()
    conn.close()
    c = np.array([r[0] for r in rows if r[0] and r[0] > 0], dtype=float)
    return c


def tickinfo(feed: str):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts", (feed,)).fetchall()
    conn.close()
    if not rows:
        return None
    ts = np.array([r[0] for r in rows], dtype=float)
    b = np.array([r[1] for r in rows], dtype=float)
    a = np.array([r[2] for r in rows], dtype=float)
    ok = (b > 0) & (a >= b)
    ts, b, a = ts[ok], b[ok], a[ok]
    mid = (a + b) / 2.0
    dur = (ts[-1] - ts[0]) / 1000.0
    return {"n": len(mid), "price": float(np.median(mid)),
            "spread": float(np.median(a - b)),
            "spread_log": float(np.median((a - b) / mid)),
            "rate_per_s": len(mid) / dur}


def realised_ann(c: np.ndarray) -> float:
    r = np.diff(np.log(c))
    return float(r.std(ddof=1) * math.sqrt(MINUTES_PER_YEAR))


def touch_measured(c: np.ndarray, sigma_min: float, x: float, T: int) -> float:
    """Fraction of non-overlapping T-minute windows whose running maximum
    reaches `x` window-sigmas above the start, monitored on closes."""
    lg = np.log(c)
    k = (len(lg) - 1) // T
    if k < 200:
        return float("nan"), 0
    a = x * sigma_min * math.sqrt(T)
    seg = lg[1: k * T + 1].reshape(k, T)
    start = lg[np.arange(k) * T]
    hits = int(((seg - start[:, None]).max(axis=1) >= a).sum())
    return hits / k, k


def main() -> None:
    out = {"feeds": {}}
    print("=" * 122)
    print("THE SPREAD AGAINST THE KNOWN PROCESS - is it priced off the name or off the process?")
    print("=" * 122)

    rows = []
    for feed in list(NAME) + OTHER + REAL:
        ti = tickinfo(feed)
        c = bars(feed)
        if ti is None or len(c) < 1000:
            continue
        sig_ann = realised_ann(c)
        sig_sec = sig_ann / math.sqrt(SECONDS_PER_YEAR)
        sig_min = sig_ann / math.sqrt(MINUTES_PER_YEAR)
        cl = ti["spread_log"]
        tick_s = 1.0 / ti["rate_per_s"]
        r = {"feed": feed, "name": NAME.get(feed), "family": FAMILY.get(feed, "other"),
             "price": ti["price"], "spread": ti["spread"], "spread_log": cl,
             "spread_bps": 1e4 * cl, "realised_ann_pct": 100 * sig_ann,
             "sigma_min": sig_min, "sigma_sec": sig_sec,
             "rate_per_s": ti["rate_per_s"],
             "c_over_sigma_sec": cl / sig_sec,
             "t_breakeven_s": (cl / sig_sec) ** 2,
             "c_in_minute_sigmas": cl / sig_min,
             "c_in_tick_sigmas": cl / (sig_sec * math.sqrt(tick_s)),
             "ticks_to_pay": (cl / (sig_sec * math.sqrt(tick_s))) ** 2}
        if r["name"]:
            r["bps_per_name"] = r["spread_bps"] / r["name"]
            r["realised_over_name"] = 100 * sig_ann / r["name"]
        rows.append(r)
        out["feeds"][feed] = r

    print("\n[1] THE COST OF A CROSSING, IN UNITS OF THE PROCESS")
    print("    t* is the horizon at which the standard deviation of the move first equals")
    print("    the spread - the exact version of 'how long must this be held to pay for itself'.")
    print(f"{'feed':26s} {'name':>6s} {'realised':>9s} {'r/name':>7s} {'spread bps':>11s}"
          f" {'c/sigma_s':>10s} {'t* (s)':>9s} {'c in 1m sd':>11s} {'ticks to pay':>13s}")
    for r in rows:
        if r["family"] == "other" and r["feed"] in REAL:
            continue
        print(f"{r['feed']:26s} {(r['name'] or 0):6.0f} {r['realised_ann_pct']:9.2f}"
              f" {(r.get('realised_over_name') or 0):7.4f} {r['spread_bps']:11.3f}"
              f" {r['c_over_sigma_sec']:10.3f} {r['t_breakeven_s']:9.2f}"
              f" {r['c_in_minute_sigmas']:11.4f} {r['ticks_to_pay']:13.2f}")
    print("    real instruments, as the control catalogue.md used:")
    for r in rows:
        if r["feed"] not in REAL:
            continue
        print(f"{r['feed']:26s} {'-':>6s} {r['realised_ann_pct']:9.2f} {'-':>7s}"
              f" {r['spread_bps']:11.3f} {r['c_over_sigma_sec']:10.3f} {r['t_breakeven_s']:9.2f}"
              f" {r['c_in_minute_sigmas']:11.4f} {r['ticks_to_pay']:13.2f}")

    print("\n[2] THE NAME TEST - spread per unit of STATED volatility, by family")
    print(f"{'feed':26s} {'name N':>7s} {'bps':>9s} {'bps / N':>9s} {'bps / realised N':>17s}")
    fam = {"vol": [], "jump": []}
    for r in rows:
        if not r.get("name"):
            continue
        per_real = r["spread_bps"] / r["realised_ann_pct"]
        fam[r["family"]].append((r["bps_per_name"], per_real))
        print(f"{r['feed']:26s} {r['name']:7.0f} {r['spread_bps']:9.3f}"
              f" {r['bps_per_name']:9.5f} {per_real:17.5f}")
    print(f"\n{'family':10s} {'n':>3s} {'mean bps/N':>11s} {'cv':>7s} {'mean bps/realised':>18s} {'cv':>7s}")
    for k, v in fam.items():
        if not v:
            continue
        a = np.array([x[0] for x in v])
        b = np.array([x[1] for x in v])
        print(f"{k:10s} {len(v):3d} {a.mean():11.5f} {a.std(ddof=1)/a.mean():7.4f}"
              f" {b.mean():18.5f} {b.std(ddof=1)/b.mean():7.4f}")
        out.setdefault("family", {})[k] = {
            "n": len(v), "bps_per_name_mean": float(a.mean()),
            "bps_per_name_cv": float(a.std(ddof=1) / a.mean()),
            "bps_per_realised_mean": float(b.mean()),
            "bps_per_realised_cv": float(b.std(ddof=1) / b.mean())}
    print("\n    the sharper form of the same question. If the spread were a fixed multiple")
    print("    of the volatility in the NAME, then c / sigma_realised would sit at that")
    print("    multiple divided by 1.322 on the Jump family and at the multiple itself on")
    print("    the Volatility family. It does not:")
    for k in ("vol", "jump"):
        v = [r["c_over_sigma_sec"] for r in rows if r.get("name") and r["family"] == k
             and r["feed"] not in ("volatility_150_1s_index", "volatility_250_1s_index")]
        a = np.array(v)
        print(f"    {k:8s} c / sigma_1s = {a.mean():.4f} +- {a.std(ddof=1):.4f}  "
              f"(range {a.min():.3f} to {a.max():.3f}, n={len(v)})")
        out.setdefault("c_over_sigma", {})[k] = {"mean": float(a.mean()),
                                                 "sd": float(a.std(ddof=1)),
                                                 "min": float(a.min()), "max": float(a.max())}
    if fam["vol"] and fam["jump"]:
        vj = np.array([x[1] for x in fam["vol"]]).mean() / np.array([x[1] for x in fam["jump"]]).mean()
        print(f"\n    per unit of REALISED volatility the Volatility family costs {vj:.2f}x "
              f"what the Jump family costs.")
        out["vol_over_jump_cost"] = float(vj)

    # exclude the two coarsely-quoted feeds, which are a quote artefact and not a price
    print("\n    the same table without volatility_150_1s and volatility_250_1s, whose quote")
    print("    grids twins.md flagged as too coarse to read:")
    for k in ("vol", "jump"):
        v = [(r["bps_per_name"], r["spread_bps"] / r["realised_ann_pct"]) for r in rows
             if r.get("name") and r["family"] == k
             and r["feed"] not in ("volatility_150_1s_index", "volatility_250_1s_index")]
        a = np.array([x[0] for x in v]); b = np.array([x[1] for x in v])
        print(f"    {k:8s} n={len(v)}  bps/N {a.mean():.5f} (cv {a.std(ddof=1)/a.mean():.4f})"
              f"   bps/realised {b.mean():.5f} (cv {b.std(ddof=1)/b.mean():.4f})")

    print("\n[3] MEASURED - do the Jump feeds touch as often as their NAME says, or as often")
    print("    as their PROCESS says? The Volatility family is the control, where the two")
    print("    predictions coincide and both must fit.")
    print(f"{'feed':24s} {'T':>5s} {'x':>4s} {'measured':>9s} {'at name':>9s} {'at realised':>12s}"
          f" {'realised+disc':>14s} {'meas/name':>10s}")
    tres = []
    for feed in list(NAME):
        c = bars(feed)
        if len(c) < 5000:
            continue
        sig_real = realised_ann(c) / math.sqrt(MINUTES_PER_YEAR)
        sig_name = (NAME[feed] / 100.0) / math.sqrt(MINUTES_PER_YEAR)
        for T in TOUCH_T:
            for x in TOUCH_X:
                # the barrier is fixed in absolute terms by the realised sigma,
                # so `x` means the same distance for both predictions
                a = x * sig_real * math.sqrt(T)
                m, k = touch_measured(c, sig_real, x, T)
                if m != m:
                    continue
                p_name = 2.0 * norm.cdf(-a / (sig_name * math.sqrt(T)))
                p_real = 2.0 * norm.cdf(-a / (sig_real * math.sqrt(T)))
                p_disc = 2.0 * norm.cdf(-(a / sig_real + BETA) / math.sqrt(T))
                row = {"feed": feed, "family": FAMILY[feed], "T": T, "x": x, "meas": m, "k": k,
                       "p_name": p_name, "p_real": p_real, "p_disc": p_disc,
                       "ratio": m / p_name if p_name > 0 else float("nan")}
                tres.append(row)
                if x in (1.0, 2.0, 3.0) and T == 60:
                    print(f"{feed:24s} {T:5d} {x:4.1f} {m:9.4f} {p_name:9.4f} {p_real:12.4f}"
                          f" {p_disc:14.4f} {row['ratio']:10.2f}")
    out["touch"] = tres
    print("\n    cells with at least 200 windows and a predicted probability between 0.05")
    print("    and 0.90, so that neither the sample nor the boundary decides the answer:")
    for famk in ("vol", "jump"):
        sub = [r for r in tres if r["family"] == famk and 0.05 < r["p_disc"] < 0.90
               and r["k"] >= 200]
        if not sub:
            continue
        en = float(np.mean([abs(r["meas"] / r["p_name"] - 1) for r in sub]))
        ed = float(np.mean([abs(r["meas"] / r["p_disc"] - 1) for r in sub]))
        print(f"    {famk:5s}: {len(sub)} cells. mean |error| against the NAME "
              f"{100*en:6.1f}%,  against the PROCESS (discretely corrected) {100*ed:5.1f}%")
        out.setdefault("touch_err", {})[famk] = {"n": len(sub), "err_name": en, "err_disc": ed}
    print(f"\n    by barrier distance, measured / predicted-from-the-process:")
    print(f"{'x':>6s} {'vol':>9s} {'jump':>9s} {'vol cells':>10s} {'jump cells':>11s}")
    for x in TOUCH_X:
        r = {}
        for famk in ("vol", "jump"):
            sub = [q for q in tres if q["family"] == famk and q["x"] == x
                   and q["k"] >= 200 and q["p_disc"] > 0.01]
            r[famk] = (float(np.mean([q["meas"] / q["p_disc"] for q in sub])), len(sub)) if sub else (float("nan"), 0)
        print(f"{x:6.1f} {r['vol'][0]:9.3f} {r['jump'][0]:9.3f} {r['vol'][1]:10d} {r['jump'][1]:11d}")

    print("\n[4] DERIVED - what a one-touch on a Jump index is worth if it is priced at the name")
    print("    value ratio = Phi(-x) / Phi(-1.322 x), x = barrier in realised window-sigmas")
    print(f"{'x':>6s} {'P(touch) at name':>17s} {'P(touch) true':>14s} {'true/name':>10s}"
          f" {'no-touch at name':>17s} {'no-touch true':>14s} {'true/name':>10s}")
    K = 1.3226
    gap = []
    for x in TOUCH_X + [4.0, 5.0]:
        pn = 2.0 * norm.cdf(-K * x)
        pr = 2.0 * norm.cdf(-x)
        nn, nr = 1.0 - pn, 1.0 - pr
        print(f"{x:6.1f} {pn:17.6f} {pr:14.6f} {pr/pn:10.2f} {nn:17.6f} {nr:14.6f} {nr/nn:10.4f}")
        gap.append({"x": x, "touch_name": pn, "touch_true": pr, "ratio": pr / pn,
                    "notouch_name": nn, "notouch_true": nr, "notouch_ratio": nr / nn})
    out["value_gap"] = gap

    print("\n[5] DERIVED - the discrete-monitoring shift, which moves every touch the other way")
    print("    a barrier monitored on ticks behaves like one 0.5826 tick-sigmas further out.")
    print(f"{'feed':26s} {'tick sd (log)':>14s} {'shift (bps)':>12s} {'shift / spread':>15s}")
    for r in rows:
        if not r.get("name"):
            continue
        tick_s = 1.0 / r["rate_per_s"]
        tsd = r["sigma_sec"] * math.sqrt(tick_s)
        print(f"{r['feed']:26s} {tsd:14.3e} {1e4*BETA*tsd:12.4f} {BETA*tsd/r['spread_log']:15.4f}")

    print("\n[6] THE RANKING - cost per unit of the volatility you actually get")
    print("    E[net] = -cost for every position on every one of these, so this orders the")
    print("    losses and nothing else.")
    rank = sorted([r for r in rows], key=lambda r: r["t_breakeven_s"])
    print(f"{'feed':26s} {'t* (s)':>9s} {'c/sigma_s':>10s} {'c in 1m sd':>11s}")
    for r in rank:
        print(f"{r['feed']:26s} {r['t_breakeven_s']:9.2f} {r['c_over_sigma_sec']:10.3f}"
              f" {r['c_in_minute_sigmas']:11.4f}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(json.loads(json.dumps(out, default=float)), fh, indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
