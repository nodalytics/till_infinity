"""Fresh, long-waiting, untested levels: the turn-origin zone's first return, by how long it waited.

Frozen in `aged_zone_rule.json` before this ran. `turn_zones.py` with the zone waiting up to 180 days
for its first return, judged on the 58 fresh coins against iid and GARCH walks.

  OUT=... MT5BT_DB=... CACHE=... MODE=run python research/ideas/aged_zones.py
"""
from __future__ import annotations

import os
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("RET_DAYS", "180")

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import turn_confirm as C  # noqa: E402
import turn_trade as TT  # noqa: E402
import turn_zones as TZ  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/aged_zones"))
EDGES = [0, 2, 10, 30, 90, 180.01]
LABELS = ["0-2d", "2-10d", "10-30d", "30-90d", "90-180d"]
NS = (0.5, 1, 2, 4, 10)
TZ.SEC.setdefault("1d", 86400)


def one(job):
    from mcfl import candles, synth
    from mcfl.parse import flip
    venue, sym, iv, source = job
    df, fee_px = C.load(venue, sym, iv)
    if df is None or len(df) < 300:
        return None
    cost_atr = fee_px / np.maximum(np.asarray(candles.table(df)["atr"], float), 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    if source != "real":
        ts, n = df["ts"].to_numpy(), len(df)
        sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
        seed = zlib.crc32(f"{venue}{sym}{iv}{source}aged".encode()) % 100000
        gen = synth.walk if source == "walk" else synth.garch
        df = gen(n, sigma=sigma, seed=seed, steps=TT.WALK_STEPS).reset_index(drop=True).iloc[:n]
        df["ts"] = ts[:len(df)]
        df["volume"] = 0.0
        cost_atr = cost_atr[:len(df)]
    rows, proven = [], 0
    for side, frame in ((1, df), (-1, flip(df))):
        rows += TZ.zones(frame, side, cost_atr, f"{venue}:{source}", sym, iv)
        proven += live_count(frame, iv)
    print(f"  {venue} {source} {sym} {iv}: {len(rows)} returns of {proven} proven zones", flush=True)
    d = pd.DataFrame(rows)
    d = d[d["act"] == "proven"] if len(d) else d
    return d, dict(src=f"{venue}:{source}", sym=sym, iv=iv, proven=proven)


def live_count(df, iv):
    """Proven zones whose 180-day window lies inside the data (the denominator of 'comes back')."""
    h, l = df["high"].to_numpy(float), df["low"].to_numpy(float)
    n, a = len(df), TZ.atr(df)
    low3 = pd.Series(l).rolling(3).min().to_numpy()
    prior = pd.Series(l).shift(3).rolling(9).min().to_numpy()
    span = int(TZ.RET_DAYS * 86400 / TZ.SEC[iv])
    k = 0
    for t in np.flatnonzero(low3 <= prior):
        if t < 30 or not a[t] > 0:
            continue
        for j in range(t + 1, min(n, t + 1 + TZ.LIVE_BARS)):
            if l[j] < low3[t]:
                break
            if h[j] >= low3[t] + TZ.RALLY["proven"] * a[t]:
                k += j + 1 + span < n
                break
    return k


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("fresh", c, iv, s) for s in ("real", "walk", "garch") for iv in ("4h", "1d") for c in C.FRESH] + \
           [("binance", c, iv, s) for s in ("real", "walk", "garch") for iv in ("4h", "1d") for c in TT.COINS] + \
           [("mt5", m, iv, s) for s in ("real", "walk", "garch") for iv in ("4h", "1d") for m in TT.MT5]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 8))) as pool:
        got = [g for g in pool.map(one, jobs) if g is not None]
    d = pd.concat([g[0] for g in got if len(g[0])], ignore_index=True)
    dens = pd.DataFrame([g[1] for g in got])
    d.to_pickle(OUT / "aged_zones.pkl.gz")
    d["wait_d"] = d["wait"] * d["iv"].map(TZ.SEC) / 86400
    d["bucket"] = pd.cut(d["wait_d"], EDGES, right=False, labels=LABELS)
    d["ALL"] = True
    rng = np.random.default_rng(81)
    rows = []
    for src, g in d.groupby("src"):
        for fam in ("ALL", "SIG"):
            x0 = g[g[fam]]
            for b in [*LABELS, ">=10d"]:
                x = x0[x0["wait_d"] >= 10] if b == ">=10d" else x0[x0["bucket"] == b]
                y = x.assign(R=x["E1"])
                lo, hi = TT.boot(y, rng) if len(y) > 30 else (np.nan, np.nan)
                rows.append(dict(src=src, family=fam, wait=b, n=len(y), R=y["R"].mean(), lo=lo, hi=hi,
                                 X2=x["X2"].mean(), R_before=y.loc[y["ts"] < TT.SPLIT, "R"].mean(),
                                 R_after=y.loc[y["ts"] >= TT.SPLIT, "R"].mean(), away=x["away"].median(),
                                 **{f"P{N}R": (x["mfe"] >= N).mean() for N in NS}))
    t = pd.DataFrame(rows).round(3)
    t.to_csv(OUT / "aged_zones.csv", index=False)
    back = d[d["wait_d"] <= TZ.RET_DAYS].groupby("src").size() / dens.groupby("src")["proven"].sum()
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 300)
    print(t.to_string(index=False))
    print("1/(N+1):", {N: round(1 / (N + 1), 3) for N in NS})
    print("\nshare of proven zones returned to within 180 days (approximate; the counts include zones near the end):")
    print(back.round(3).to_string())

    def cell(src, fam, b):
        return t[(t["src"] == src) & (t["family"] == fam) & (t["wait"] == b)].iloc[0]
    p, s = cell("fresh:real", "ALL", ">=10d"), cell("fresh:real", "ALL", "0-2d")
    w, gw = cell("fresh:walk", "ALL", ">=10d"), cell("fresh:garch", "ALL", ">=10d")
    ok = (p["R"] > 0 and p["lo"] > 0 and p["R_before"] > 0 and p["R_after"] > 0
          and p["R"] > w["R"] and p["R"] > gw["R"] and p["R"] > s["R"])
    print(f"\nPRIMARY (ALL, wait >= 10d, E1, fresh 4h+1d): R {p['R']:+.3f} [{p['lo']:+.3f}, {p['hi']:+.3f}] n={p['n']}, "
          f"before {p['R_before']:+.3f}, after {p['R_after']:+.3f}; walk {w['R']:+.3f}; garch {gw['R']:+.3f}; "
          f"wait < 2d {s['R']:+.3f} -> {'PASSES' if ok else 'fails'}")


def main():
    {"run": run}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
