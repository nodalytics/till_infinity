"""Aged zones with the risk sized to the volatility at the return.

Frozen in `aged_volstop_rule.json` before this ran. The same trades as `aged_zones.py` (same zones and
fills); only the stop, trail and slippage are re-sized to ATR at the bar before the fill.

  OUT=... MT5BT_DB=... CACHE=... python research/ideas/aged_volstop.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import aged_context as X  # noqa: E402
import aged_zones as A  # noqa: E402
import turn_confirm as C  # noqa: E402
import turn_trade as TT  # noqa: E402
import turn_zones as TZ  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/aged_zones"))
NS = (0.5, 1, 2, 4, 10)


def one(key):
    from mcfl import candles
    from mcfl.parse import flip
    src, sym, iv, rows = key
    venue, source = src.split(":")
    df = X.series(venue, sym, iv, source)
    real, fee_px = C.load(venue, sym, iv)
    if df is None or real is None:
        return None
    cost_atr = fee_px / np.maximum(np.asarray(candles.table(real)["atr"], float), 1e-12)  # as aged_zones.one
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))[:len(df)]
    hold = max(1, int(10 * 86400 / TZ.SEC[iv]))
    out = []
    for side in (1, -1):
        frame = df if side > 0 else flip(df)
        g = rows[rows["side"] == side]
        if not len(g):
            continue
        o, h, l, c = (frame[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        a = TZ.atr(frame)
        low3 = pd.Series(l).rolling(3).min().to_numpy()
        for _, r in g.iterrows():
            t, f = int(r.t), int(r.f)
            bottom = low3[t]
            top = bottom + TZ.WIDTH * a[t]
            now = a[f - 1]
            if not now > 0:
                continue
            res = {}
            for name, stop in (("V1", top - 0.6 * now), ("V2", min(bottom - 0.1 * now, top - 0.6 * now))):
                e = TZ.exits(o, h, l, c, f, top, stop, now, cost_atr[f] * a[f], hold)
                res.update({f"{name}_E1": e["E1"], f"{name}_X2": e["X2"], f"{name}_mfe": e["mfe"]})
            out.append(dict(src=src, sym=sym, iv=iv, side=side, ts=r.ts, SIG=r.SIG, wait=r.wait,
                            vol_ratio=now / a[t], **res))
    print(f"  {src} {sym} {iv}: {len(out)}", flush=True)
    return pd.DataFrame(out)


def run():
    d = pd.read_pickle(OUT / "aged_zones.pkl.gz")  # our own output, written by aged_zones.py
    keys = [(src, sym, iv, g) for (src, sym, iv), g in d.groupby(["src", "sym", "iv"])]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 8))) as pool:
        got = [g for g in pool.map(one, keys) if g is not None and len(g)]
    x = pd.concat(got, ignore_index=True)
    x["wait_d"] = x["wait"] * x["iv"].map(TZ.SEC) / 86400
    x["bucket"] = pd.cut(x["wait_d"], A.EDGES, right=False, labels=A.LABELS)
    x.to_pickle(OUT / "aged_volstop.pkl.gz")
    rng = np.random.default_rng(101)
    rows = []
    for src, g in x.groupby("src"):
        for fam in ("ALL", "SIG"):
            x0 = g[g["SIG"]] if fam == "SIG" else g
            for b in [*A.LABELS, ">=10d"]:
                xb = x0[x0["wait_d"] >= 10] if b == ">=10d" else x0[x0["bucket"] == b]
                for v in ("V1", "V2"):
                    y = xb.assign(R=xb[f"{v}_E1"])
                    lo, hi = TT.boot(y, rng) if len(y) > 30 else (np.nan, np.nan)
                    rows.append(dict(src=src, family=fam, wait=b, variant=v, n=len(y), R=y["R"].mean(), lo=lo, hi=hi,
                                     X2=xb[f"{v}_X2"].mean(), R_before=y.loc[y["ts"] < TT.SPLIT, "R"].mean(),
                                     R_after=y.loc[y["ts"] >= TT.SPLIT, "R"].mean(), vol_ratio=xb["vol_ratio"].median(),
                                     **{f"P{N}R": (xb[f"{v}_mfe"] >= N).mean() for N in NS}))
    t = pd.DataFrame(rows).round(3)
    t.to_csv(OUT / "aged_volstop.csv", index=False)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 600)
    print(t.to_string(index=False))
    print("1/(N+1):", {N: round(1 / (N + 1), 3) for N in NS})

    def cell(src, b):
        return t[(t["src"] == src) & (t["family"] == "ALL") & (t["wait"] == b) & (t["variant"] == "V1")].iloc[0]
    p, s = cell("fresh:real", ">=10d"), cell("fresh:real", "0-2d")
    w, gw = cell("fresh:walk", ">=10d"), cell("fresh:garch", ">=10d")
    ok = (p["R"] > 0 and p["lo"] > 0 and p["R_before"] > 0 and p["R_after"] > 0
          and p["R"] > w["R"] and p["R"] > gw["R"] and p["R"] > s["R"])
    print(f"\nPRIMARY (ALL, wait >= 10d, V1, E1, fresh 4h+1d): R {p['R']:+.3f} [{p['lo']:+.3f}, {p['hi']:+.3f}] n={p['n']}, "
          f"before {p['R_before']:+.3f}, after {p['R_after']:+.3f}; walk {w['R']:+.3f}; garch {gw['R']:+.3f}; "
          f"wait < 2d {s['R']:+.3f} -> {'PASSES' if ok else 'fails'}")


if __name__ == "__main__":
    run()
