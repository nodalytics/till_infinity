"""Does the magnitude model survive the three tests it has not had?

`zscore-magnitude.md` found the one positive result in the z-score work: strip
the sign and a boosted model predicts **|forward move| over the ATR** at IC
+0.078, with ten monotone deciles and beating every single feature fourfold. It
was fitted once, on one horizon, at 4h, on the sixteen development instruments.

Three things decide whether it is real:

  walk_forward    refit each calendar year and score the next. A single date
                  split can be lucky about where the split fell
  held_out        train on the sixteen development instruments and score on the
                  other sixty. Instruments it has never seen
  horizon         1h and 1d as well as 4h. A result on one bar size is a result
                  about that bar size

Each is scored the same way: Spearman IC and the top-minus-bottom decile spread
in ATR, with a day-block interval, against the same model refit on a target
shuffled within symbol.

  MT5BT_DB=... IV=4h python research/ideas/magnitude_validate.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

import zscore_ml2 as Z  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/zmagval"))
DEV = ("EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD EURJPY GBPJPY EURGBP "
       "AUDJPY USDCNH XAUUSD XAGUSD BTCUSD ETHUSD").split()
SEC = {"1h": 3600, "4h": 14400, "1d": 86400}


def score(pred, te, col="absy"):
    y = te[col].to_numpy()
    ok = np.isfinite(pred) & np.isfinite(y)
    p, t, dd = pred[ok], y[ok], te["day"].to_numpy()[ok]
    if len(p) < 200 or np.ptp(p) == 0:
        return None
    ic = float(pd.Series(p).corr(pd.Series(t), method="spearman"))
    hi_, lo_ = np.quantile(p, [0.9, 0.1])
    m_t, l_t, h_t = Z.block_ci(t[p >= hi_], dd[p >= hi_])
    m_b, _, _ = Z.block_ci(t[p <= lo_], dd[p <= lo_])
    return dict(n=len(p), ic=ic, top=m_t, top_lo=l_t, top_hi=h_t, bottom=m_b,
                spread=m_t - m_b)


def shuffled(tr, rng):
    y = tr["absy"].to_numpy().copy()
    syms = tr["sym"].to_numpy()
    for s in np.unique(syms):
        w = np.flatnonzero(syms == s)
        y[w] = rng.permutation(y[w])
    return y


def load(iv):
    import run as R
    os.environ["IV"] = iv
    import importlib
    importlib.reload(Z)
    syms = [s for s in R.FAMILY if s not in R.FRESH]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 14))) as pool:
        parts = [p for p in pool.map(Z.one, syms) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    d = d[np.isfinite(d["y"])].dropna(subset=Z.FEATURES).reset_index(drop=True)
    d["day"] = (d["ts"] // 86400).astype(int)
    d["absy"] = d["y"].abs()
    d["year"] = pd.to_datetime(d["ts"], unit="s").dt.year
    return d.sort_values("ts").reset_index(drop=True)


def main() -> None:
    rows = []
    rng = np.random.default_rng(7)
    for iv in os.environ.get("INTERVALS", "4h,1h,1d").split(","):
        d = load(iv)
        dev, rest = d[d["sym"].isin(DEV)], d[~d["sym"].isin(DEV)]
        print(f"\n########## {iv}: {len(d):,} rows, {d['sym'].nunique()} instruments "
              f"({len(dev):,} development / {len(rest):,} held out)")

        print("\n-- walk forward, refit each calendar year, development instruments")
        for y in sorted(dev["year"].unique())[2:]:
            a, b = dev[dev["year"] < y], dev[dev["year"] == y]
            if len(a) < 20000 or len(b) < 2000:
                continue
            _, p = Z.fit(a, b, a["absy"].to_numpy(), seed=1)
            r = score(p, b)
            _, ps = Z.fit(a, b, shuffled(a, rng), seed=2)
            rs = score(ps, b)
            if r:
                print(f"   {y}  n={r['n']:>6}  IC {r['ic']:+.4f}  spread {r['spread']:+.3f}  "
                      f"top {r['top']:.3f} [{r['top_lo']:.3f},{r['top_hi']:.3f}]   "
                      f"shuffled IC {rs['ic']:+.4f} spread {rs['spread']:+.3f}")
                rows.append(dict(iv=iv, test="walk_forward", key=str(y), **r,
                                 shuf_ic=rs["ic"], shuf_spread=rs["spread"]))

        print("\n-- held-out instruments: trained on the development sixteen")
        if len(rest) > 5000:
            _, p = Z.fit(dev, rest, dev["absy"].to_numpy(), seed=3)
            r = score(p, rest)
            _, ps = Z.fit(dev, rest, shuffled(dev, rng), seed=4)
            rs = score(ps, rest)
            if r:
                print(f"   n={r['n']:>7}  IC {r['ic']:+.4f}  spread {r['spread']:+.3f}  "
                      f"top {r['top']:.3f} [{r['top_lo']:.3f},{r['top_hi']:.3f}]   "
                      f"shuffled IC {rs['ic']:+.4f} spread {rs['spread']:+.3f}")
                rows.append(dict(iv=iv, test="held_out", key="all", **r,
                                 shuf_ic=rs["ic"], shuf_spread=rs["spread"]))
                # per family, so one group cannot carry it
                rest2 = rest.assign(pred=p)
                for fam, g in rest2.groupby(rest2["sym"].str[:3]):
                    if len(g) < 3000:
                        continue
                    rr = score(g["pred"].to_numpy(), g)
                    if rr:
                        print(f"      {fam:<4} n={rr['n']:>6} IC {rr['ic']:+.4f} "
                              f"spread {rr['spread']:+.3f}")

        print("\n-- the plain date split, for comparison with the published figure")
        cut = d["ts"].quantile(0.70)
        gap = max(Z.H, Z.BARS) * SEC[iv]
        a, b = d[d["ts"] <= cut - gap], d[d["ts"] > cut]
        _, p = Z.fit(a, b, a["absy"].to_numpy(), seed=5)
        r = score(p, b)
        if r:
            print(f"   n={r['n']:>7}  IC {r['ic']:+.4f}  spread {r['spread']:+.3f}")
            rows.append(dict(iv=iv, test="date_split", key="all", **r,
                             shuf_ic=np.nan, shuf_spread=np.nan))
    t = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    t.to_csv(OUT / "validate.csv", index=False)
    pd.set_option("display.width", 220)
    print("\n\n=== everything ===")
    print(t.round(4).to_string(index=False))
    print(f"\nwritten: {OUT / 'validate.csv'}")


if __name__ == "__main__":
    main()
