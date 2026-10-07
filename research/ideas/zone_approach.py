"""Does the way price comes back to a zone say whether the zone holds?

The desk's hypothesis, 2026-10-07:

    the momentum candles with which it comes back to the zone matters before the
    candlestick pattern - if the candles start becoming choppy as it is getting
    closer back to the zone ... measure the hold rate for these compared to the
    ones where momentum candles were coming back to the zone especially as the
    price was getting closer, so if it does not slow when getting closer to the
    zone, the zone might get voided

It is a well-formed prediction with a sign, which is rarer than it sounds, and it
is cheap to test because the zone study already runs. Four readings of the
approach, every one of them from bars **strictly before** the bar that re-enters
the band:

  app_decel  the near half's speed over the far half's: below 1 is slowing
  app_speed  ATR a bar over the whole approach
  app_body   mean body as a share of range: momentum against chop
  app_run    consecutive bars closing the zone's way at the end

Against two outcomes: the **hold rate** - no close beyond the band's far edge
within the reaction window, a property of the zone and not of any trade - and
the R of the trade actually taken, so a feature that sorts holds but not money
is visible as such.

Each is scored in terciles, with a day-block interval, against a **shuffle of
the same feature within symbol and interval** - which keeps the outcome's own
distribution and destroys only the pairing, so a tercile spread that survives it
is about the feature and not about the sample. Benjamini-Hochberg across every
feature x outcome x interval.

  OUT=.data/zsweep4/base python research/ideas/zone_approach.py
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

OUT = Path(os.environ.get("OUT", ".data/zsweep4/base"))
FEATURES = ["app_decel", "app_speed", "app_body", "app_run"]
TRIGGER = os.environ.get("TRIGGER", "touch")
DRAWS = 2000


def block_ci(v, days, draws=DRAWS, seed=11):
    v = np.asarray(v, float)
    if len(v) < 20:
        return float(v.mean()) if len(v) else np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(np.asarray(days), return_inverse=True)
    sums = np.bincount(inv, weights=v, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    pick = rng.integers(0, len(uniq), size=(draws, len(uniq)))
    got = sums[pick].sum(axis=1) / np.maximum(cnts[pick].sum(axis=1), 1.0)
    return float(v.mean()), float(np.percentile(got, 5)), float(np.percentile(got, 95))


def spread(g: pd.DataFrame, feat: str, col: str) -> float:
    """Top tercile minus bottom, on `col`."""
    q = g[feat].quantile([1 / 3, 2 / 3]).to_numpy()
    lo, hi = g[g[feat] <= q[0]], g[g[feat] > q[1]]
    if len(lo) < 10 or len(hi) < 10:
        return np.nan
    return float(hi[col].mean() - lo[col].mean())


def shuffled_p(g: pd.DataFrame, feat: str, col: str, draws=1000, seed=3) -> float:
    """P(a shuffle of the feature reaches this spread), two-sided on |spread|."""
    want = spread(g, feat, col)
    if not np.isfinite(want):
        return np.nan
    rng = np.random.default_rng(seed)
    x = g[feat].to_numpy()
    got = np.empty(draws)
    for k in range(draws):
        got[k] = spread(g.assign(**{feat: rng.permutation(x)}), feat, col)
    return float((np.abs(got) >= abs(want)).mean())


def main() -> None:
    st = pd.read_pickle(OUT / "setups.pkl.gz")
    tr = pd.read_pickle(OUT / "zone_trades.pkl.gz")
    st = st[~st["sym"].isin(st.loc[st["family"].astype(str).str.startswith("deriv"), "sym"])] \
        if "family" in st else st
    st = st[st["trigger"] == TRIGGER].copy()
    real = tr[(tr["kind"] == "real") & (tr["trigger"] == TRIGGER)
              & (tr["filter"] == "none") & (tr["exit"] == "opp")]
    st = st.merge(real.groupby("sid")["R"].mean().rename("R"), left_on="sid", right_index=True,
                  how="left")
    st = st[~st["sym"].str.contains("Index|Boom|Crash|Jump|Step|Volatility|Drift|Range Break")]
    st["day"] = (st["ts"] // 86400).astype(int)
    st["held"] = st["held"].astype(float)
    rows = []
    for iv, g0 in st.groupby("iv"):
        for feat in FEATURES:
            g = g0[np.isfinite(g0[feat])]
            for col in ("held", "R"):
                gg = g[np.isfinite(g[col])]
                if len(gg) < 60:
                    continue
                q = gg[feat].quantile([1 / 3, 2 / 3]).to_numpy()
                lo, mid, hi = (gg[gg[feat] <= q[0]], gg[(gg[feat] > q[0]) & (gg[feat] <= q[1])],
                               gg[gg[feat] > q[1]])
                m_lo, l_lo, h_lo = block_ci(lo[col], lo["day"])
                m_hi, l_hi, h_hi = block_ci(hi[col], hi["day"])
                rows.append(dict(iv=iv, feature=feat, outcome=col, n=len(gg),
                                 bottom=m_lo, bottom_lo=l_lo, bottom_hi=h_lo,
                                 middle=float(mid[col].mean()) if len(mid) else np.nan,
                                 top=m_hi, top_lo=l_hi, top_hi=h_hi,
                                 spread=m_hi - m_lo, p=shuffled_p(gg, feat, col)))
    out = pd.DataFrame(rows)
    if out.empty:
        print("nothing to score")
        return
    pv = out["p"].fillna(1.0).to_numpy()
    order = np.argsort(pv)
    m = len(pv)
    q = np.empty(m)
    q[order] = np.minimum.accumulate((pv[order] * m / np.arange(1, m + 1))[::-1])[::-1]
    out["q"] = np.minimum(q, 1.0)
    out["passes"] = out["q"] < 0.10
    pd.set_option("display.width", 240)
    pd.set_option("display.max_rows", 200)
    print(f"\n{TRIGGER} trades, real markets, by tercile of the approach:\n")
    print(out.round(3).to_string(index=False))
    print(f"\nhold rate overall: {st.groupby('iv')['held'].agg(['size', 'mean']).round(3).to_string()}")
    print("\nanything surviving the shuffle at q < 0.10:")
    got = out[out["passes"]]
    print(got.round(3).to_string(index=False) if len(got) else "  nothing")
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT / "approach.csv", index=False)
    print(f"\nwritten: {OUT / 'approach.csv'}")


if __name__ == "__main__":
    main()
