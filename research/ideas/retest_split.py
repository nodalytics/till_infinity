"""The retest entry at 4h and 1d, with the development instruments held apart.

The retest needs a displacement **and** a pullback on top of a zone population
that is already only 328 trades at 4h and 144 at 1d, so on the sixteen
development instruments it leaves 33 and nothing. Measuring it there at all means
running every instrument - which would ordinarily spend the held-out set.

It does not have to. The same run gives both answers if the split is kept: the
sixteen development instruments are where the rule was built, and the other sixty
are instruments it has never seen. Reported separately, in that order, the second
is a confirmation rather than a larger sample.

What to look for, in this order:

  1. do the two halves agree in sign? If not, nothing else matters
  2. does the first/second half of the *period* agree? The 1h run was +0.993
     then -0.296, which is what killed it there
  3. only then, the size

  MT5BT_DB=... OUT=.data/zrtall/base python research/ideas/retest_split.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

OUT = Path(os.environ.get("OUT", ".data/zrtall/base"))
DEV = ("EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD EURJPY GBPJPY EURGBP "
       "AUDJPY USDCNH XAUUSD XAGUSD BTCUSD ETHUSD").split()
TRIGS = ("touch", "pin", "wick", "retest", "retest_line", "retest_pin")


def block_ci(v, days, draws=2000, seed=71):
    v = np.asarray(v, float)
    ok = np.isfinite(v)
    v, days = v[ok], np.asarray(days)[ok]
    if len(v) < 20:
        return (float(v.mean()) if len(v) else np.nan), np.nan, np.nan
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(np.asarray(days), return_inverse=True)
    sums = np.bincount(inv, weights=v, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    pick = rng.integers(0, len(uniq), size=(draws, len(uniq)))
    got = sums[pick].sum(axis=1) / np.maximum(cnts[pick].sum(axis=1), 1.0)
    return float(v.mean()), float(np.percentile(got, 5)), float(np.percentile(got, 95))


def main() -> None:
    d = pd.read_pickle(OUT / "zone_trades.pkl.gz")
    d = d[~d["family"].astype(str).str.startswith("deriv")]
    d["group"] = np.where(d["sym"].isin(DEV), "development", "held out")
    rows = []
    for iv in sorted(d["iv"].unique()):
        for trig in TRIGS:
            for exit_ in ("opp", "t4", "trail"):
                for grp in ("development", "held out"):
                    g = d[(d["iv"] == iv) & (d["trigger"] == trig) & (d["filter"] == "none")
                          & (d["exit"] == exit_) & (d["group"] == grp)]
                    r = g[g["kind"] == "real"]
                    if len(r) < 20:
                        continue
                    m, lo, hi = block_ci(r["R"], r["day"])
                    mid = r["entry_ts"].median()
                    f = r.loc[r["entry_ts"] < mid, "R"].mean()
                    s = r.loc[r["entry_ts"] >= mid, "R"].mean()
                    co = g[g["kind"] == "coin"]["R"].mean()
                    rows.append(dict(iv=iv, trigger=trig, exit=exit_, group=grp, n=len(r),
                                     R=m, lo=lo, hi=hi, first=f, second=s,
                                     win=float((r["R"] > 0).mean()), coin=co,
                                     syms=int(r["sym"].nunique())))
    t = pd.DataFrame(rows)
    if t.empty:
        print("nothing reached 20 trades")
        return
    pd.set_option("display.width", 240)
    pd.set_option("display.max_rows", 400)
    print(t.round(3).to_string(index=False))
    print("\n=== the retest family only, both groups side by side ===")
    r = t[t["trigger"].str.startswith("retest")]
    for iv in sorted(r["iv"].unique()):
        print(f"\n{iv}")
        print(r[r["iv"] == iv].pivot_table(index=["trigger", "exit"], columns="group",
                                           values=["n", "R"]).round(3).to_string())
    print("\n=== does it agree out of sample, and across the period? ===")
    for _, g in r.groupby(["iv", "trigger", "exit"]):
        if set(g["group"]) != {"development", "held out"}:
            continue
        dv = g[g["group"] == "development"].iloc[0]
        ho = g[g["group"] == "held out"].iloc[0]
        agree = "yes" if np.sign(dv.R) == np.sign(ho.R) else "NO"
        halves = "yes" if (ho.first > 0) == (ho.second > 0) else "NO"
        print(f"  {dv.iv:>2} {dv.trigger:<12} {dv.exit:<5} dev {dv.R:+.3f} (n={int(dv.n):>4})  "
              f"held out {ho.R:+.3f} (n={int(ho.n):>4}) [{ho.lo:+.3f},{ho.hi:+.3f}]  "
              f"sign agrees: {agree}   held-out halves agree: {halves}")
    t.to_csv(OUT / "retest_split.csv", index=False)
    print(f"\nwritten: {OUT / 'retest_split.csv'}")


if __name__ == "__main__":
    main()
