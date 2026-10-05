"""The LRC research rules' trades as return streams: exact exit times and the regime gate's inputs.

For `strategy-switching.md`. Reads `lrc_retest.py`'s trade table (R1, R4, R5s; exit X2) and, per series,
rebuilds the bars exactly as `lrc_retest.one` did (real from the same loaders; walks regenerated from the
same seeds), then adds per trade, from bars before the entry bar f only:

  exit_ts    the X2 exit bar's close time (so a rule only learns an outcome once it is known)
  vol_ratio  ATR(14)[f-1] over its rolling 500-bar median
  eff        |c[f-1] - c[f-25]| / sum |dc| over those 24 bars
  trend_with sign(c[f-1] - c[f-25]) * side

  LRC_DIR=... OUT=... TRADES=.../lrc_trades.pkl.gz MT5BT_DB=... python research/ideas/switch_lrc.py
"""
from __future__ import annotations

import os
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LRC_DIR = Path(os.environ.get("LRC_DIR", str(HERE)))
for p in (str(HERE.parents[1]), str(HERE.parent), str(HERE), str(LRC_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import lrc_retest as L  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/switch_lrc"))
TRADES = Path(os.environ.get("TRADES", ".data/lrc/lrc_trades.pkl.gz"))
RULES = ("R1", "R4", "R5s")
COLS = ["rule", "f", "ts", "x2_bar", "X2", "mfe", "risk_atr", "side", "venue", "sym", "iv", "src", "cls", "half"]


def bars(venue, sym, iv, source):
    """The bars `lrc_retest.one` traded on, rebuilt the same way."""
    df, cost_px = L.load(venue, sym, iv)
    if df is None:
        return None
    if source == "real":
        return df
    from mcfl import synth
    c = df["close"].to_numpy(float)
    ts, n = df["ts"].to_numpy(), len(df)
    sigma = float(np.std(np.diff(c)))
    seed = zlib.crc32(f"{venue}{sym}{iv}{source}lrc".encode()) % 100000
    gen = synth.walk if source == "walk" else synth.garch
    w = gen(n, sigma=sigma, seed=seed, steps=L.WALK_STEPS).reset_index(drop=True).iloc[:n]
    w["ts"] = ts[:len(w)]
    return w


def one(args):
    key, t = args
    venue, sym, iv, source = key
    df = bars(venue, sym, iv, source)
    if df is None:
        return None
    ts = df["ts"].to_numpy(np.int64)
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    a = L.atr(h, l, c)
    med = pd.Series(a).rolling(500, min_periods=100).median().to_numpy()
    dc = np.abs(np.diff(c, prepend=c[0]))
    path = pd.Series(dc).rolling(24).sum().to_numpy()
    f = t["f"].to_numpy(int)
    xb = np.minimum(t["x2_bar"].to_numpy(int), len(ts) - 1)
    ok = (f >= 26) & (f < len(ts))
    t = t[ok].copy()
    f, xb = f[ok], xb[ok]
    t["exit_ts"] = ts[xb] + L.SEC[iv]
    t["vol_ratio"] = a[f - 1] / med[f - 1]
    move = c[f - 1] - c[f - 25]
    with np.errstate(divide="ignore", invalid="ignore"):
        t["eff"] = np.abs(move) / path[f - 1]
    t["trend_with"] = np.sign(move) * t["side"].to_numpy()
    # the bar rebuild must reproduce the traded bars: entry timestamps agree
    t["ts_check"] = ts[f] == t["ts"].to_numpy(np.int64)
    return t


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t = pd.read_pickle(TRADES)  # our own lab output (lrc_retest agg)
    t = t[t["rule"].isin(RULES) & (t["cls"] != "KNOWN_BAD") & t["cls"].notna()][COLS]
    groups = [(k, g.reset_index(drop=True)) for k, g in t.groupby(["venue", "sym", "iv", "src"], sort=False)]
    del t
    out = []
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        for r in pool.map(one, groups, chunksize=1):
            if r is not None:
                out.append(r)
    s = pd.concat(out, ignore_index=True)
    print("rows", len(s), "ts reproduced", float(s["ts_check"].mean()), flush=True)
    s = s[s["ts_check"]].drop(columns="ts_check")
    s.to_pickle(OUT / "lrc_streams.pkl.gz")
    print(s.groupby(["rule", "iv", "src"]).agg(n=("X2", "size"), R=("X2", "mean")).round(3).to_string())


if __name__ == "__main__":
    main()
