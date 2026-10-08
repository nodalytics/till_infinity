"""Do `activity` and `vol_bps` beat trading less, or only trade less?

`win_rate.py` found two fields that survive Benjamini-Hochberg over 120: bars
with above-median `activity` win 57.1% against 43.9% below, and `vol_bps` 56.2%
against 44.9%. Both are volatility-state readings the desk already publishes, and
both suggest the same rule - stand down in quiet conditions.

On a book that loses, **any** rule which trades less looks like an improvement,
so the headline number carries no information at all. `strategy-rotation-is-not-timeable`
is the standing record of that on this desk: every pause rule tested improved the
book by 200-1,456 and every one of them matched random pausing at the same duty
cycle.

So the control is the whole test. A gate that keeps the top `d` share of bars by
`activity` is scored against **4,000 random gates that keep the same share**,
drawn by shuffling the field within day - which preserves how many trades each
day contributes and destroys only which ones are kept. Reported per unit traded,
not per day, because a total is just the duty cycle again.

  python research/ideas/duty_cycle.py .data/live/journal_full.csv
"""
from __future__ import annotations

import csv
import json
import sys

import numpy as np
import pandas as pd

csv.field_size_limit(10 ** 7)
FIELDS = ("activity", "vol_bps", "forecast_bps", "garch_bps", "ewma_tr_bps")
KEEP = (0.75, 0.50, 0.25)
DRAWS = 4000


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["kind"] != "outcome":
                continue
            try:
                d = json.loads(r["context"])
            except Exception:
                continue
            d["_t"] = float(r["time"])
            rows.append(d)
    d = pd.DataFrame(rows)
    d["r"] = pd.to_numeric(d.get("r_multiple"), errors="coerce")
    d = d[np.isfinite(d.r)].copy()
    d["win"] = (d.r > 0).astype(float)
    d["day"] = (d._t // 86400).astype(int)
    return d


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else ".data/live/journal_full.csv"
    d = load(path)
    print(f"{len(d)} closed positions, {d.day.nunique()} days")
    print(f"ungated: win {d.win.mean():.1%}, mean R {d.r.mean():+.3f}, total R {d.r.sum():+.1f}\n")
    rng = np.random.default_rng(31)
    for field in FIELDS:
        if field not in d:
            continue
        v = pd.to_numeric(d[field], errors="coerce")
        g = d[np.isfinite(v)].copy()
        g["v"] = v[g.index]
        if len(g) < 150:
            print(f"{field}: only {len(g)} rows\n")
            continue
        print(f"=== {field}: {len(g)} trades, {g.day.nunique()} days, "
              f"ungated win {g.win.mean():.1%} / R {g.r.mean():+.3f}")
        day = g.day.to_numpy()
        groups = [np.flatnonzero(day == u) for u in np.unique(day)]
        win, r, val = g.win.to_numpy(), g.r.to_numpy(), g.v.to_numpy()
        for keep in KEEP:
            cut = np.quantile(val, 1 - keep)
            sel = val >= cut
            if sel.sum() < 40:
                continue
            real_w, real_r = win[sel].mean(), r[sel].mean()
            # the same duty cycle, chosen at random within each day
            nw = np.empty(DRAWS)
            nr = np.empty(DRAWS)
            for k in range(DRAWS):
                y = val.copy()
                for ix in groups:
                    if len(ix) > 1:
                        y[ix] = rng.permutation(val[ix])
                s = y >= np.quantile(y, 1 - keep)
                nw[k] = win[s].mean()
                nr[k] = r[s].mean()
            pw = float((nw >= real_w).mean())
            pr = float((nr >= real_r).mean())
            print(f"   keep top {keep:>4.0%}  n={int(sel.sum()):>4}   "
                  f"win {real_w:.1%} against random {nw.mean():.1%} "
                  f"[{np.percentile(nw, 5):.1%},{np.percentile(nw, 95):.1%}]  p={pw:.3f}   "
                  f"R {real_r:+.3f} against {nr.mean():+.3f} p={pr:.3f}")
        print()


if __name__ == "__main__":
    main()
