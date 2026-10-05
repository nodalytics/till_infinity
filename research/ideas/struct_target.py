"""Does a *structural* target beat a fixed one on the desk's break-and-retest setup?

`lrc-retest.md` settled the fixed targets: for R1 the chance of reaching N R
before -1R is 0.456 / 0.320 / 0.195 / 0.090 at N = 1, 2, 4, 10, against
0.5 / 0.333 / 0.2 / 0.091 from 1/(1+N) and the same on matched walks. A constant
target has no edge at any distance, so moving 2R out to 4R or 6R cannot help and
does not need testing again.

**It does not settle a target that moves with the chart.** The desk's rule is
"take profit past the imbalance, below the chop above" - a distance that differs
per trade. If structure carries information, a trade whose structural target
happens to sit at 3R should reach it more often than 1/(1+3), and one whose
target sits at 1.5R more often than 1/(1+1.5). Pooled P(N R) cannot see that,
because it averages over trades whose own targets are at different distances.

So the test here is conditional, and it is the only thing a fixed-target study
cannot answer:

    P(mfe >= D)  against  1/(1+D),  binned by D, real against walks

where D is the structural target's distance in R and `mfe` is the furthest the
trade actually got before its stop. Both come free with the trade rows.

**On costs, and a correction.** A further target does not dilute the spread.
Cost in R is `cost_px / risk` and `risk` is the stop, so every exit on the same
trade carries the identical cost whatever its target. The published -0.291R is
the cost of a 0.78-ATR stop and moving the target cannot touch it; what a better
target can change is the gross distribution, which is what this measures.

Reads the parts `lrc_retest.run()` wrote; writes `struct_*.csv` into OUT.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lrc_retest as L  # noqa: E402

#: Edges for D, the structural target's distance in R. Wide bins at the far end
#: because few targets land there and a bin of forty trades says nothing.
BINS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 10.0)
RULES = ("R1", "R5", "R5s")
TARGETS = ("XL", "XI", "XF")


def reached(x, col):
    """P(mfe >= D) against 1/(1+D), by D bin, with the count behind each cell."""
    out = []
    d, mfe = x[f"d_{col}"].to_numpy(float), x["mfe"].to_numpy(float)
    ok = np.isfinite(d) & np.isfinite(mfe) & (d > 0)
    d, mfe = d[ok], mfe[ok]
    idx = np.digitize(d, BINS)
    for j in range(len(BINS) + 1):
        m = idx == j
        n = int(m.sum())
        if n < 200:
            continue
        lo = BINS[j - 1] if j else 0.0
        hi = BINS[j] if j < len(BINS) else np.inf
        got = float((mfe[m] >= d[m]).mean())
        # The null uses each trade's own D, not the bin's midpoint: a bin is a
        # range and 1/(1+D) is convex, so a midpoint would bias the comparison.
        null = float(np.mean(1.0 / (1.0 + d[m])))
        out.append(dict(lo=lo, hi=hi, n=n, d_med=float(np.median(d[m])),
                        reached=got, null=null, edge=got - null))
    return pd.DataFrame(out)


def main():
    t, _h, _m = L.collect()
    t = t[t["half"] == "conf"]
    rows, curves = [], []
    for rule in RULES:
        x0 = t[t["rule"] == rule]
        if not len(x0):
            continue
        for pool, xp in L.pools(x0):
            if pool not in ("NONDERIV", "DERIV_1S", "V10_1S"):
                continue
            for src in ("real", "walk", "garch"):
                x = xp[xp["src"] == src]
                if len(x) < 500:
                    continue
                row = dict(rule=rule, pool=pool, src=src, n=len(x),
                           X2=float(x["X2"].mean()))
                for col in TARGETS:
                    r, d = x.get(f"R_{col}"), x.get(f"d_{col}")
                    if r is None:
                        continue
                    ok = np.isfinite(r.to_numpy(float))
                    row[f"n_{col}"] = int(ok.sum())
                    row[col] = float(r[ok].mean()) if ok.any() else np.nan
                    row[f"d_{col}"] = float(d[ok].median()) if ok.any() else np.nan
                    # The fixed target on exactly the trades the structural one
                    # could be formed for, so the two are compared like for like.
                    row[f"X2_{col}"] = float(x["X2"][ok].mean()) if ok.any() else np.nan
                    c = reached(x[ok], col)
                    if len(c):
                        c["rule"], c["pool"], c["src"], c["target"] = rule, pool, src, col
                        curves.append(c)
                rows.append(row)
    tab = pd.DataFrame(rows)
    cur = pd.concat(curves, ignore_index=True) if curves else pd.DataFrame()
    L.OUT.mkdir(parents=True, exist_ok=True)
    tab.to_csv(L.OUT / "struct_means.csv", index=False)
    cur.to_csv(L.OUT / "struct_reached.csv", index=False)
    with pd.option_context("display.width", 200, "display.max_columns", 50):
        print("\n=== mean R by target (confirmation half) ===")
        print(tab.to_string(index=False))
        print("\n=== P(reach) against 1/(1+D) ===")
        print(cur.to_string(index=False) if len(cur) else "no bin reached 200 trades")
    print("struct done", flush=True)


if __name__ == "__main__":
    main()
