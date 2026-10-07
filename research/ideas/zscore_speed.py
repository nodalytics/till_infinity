"""Not the z-score's level - the speed it got there, and the speed it is leaving.

Asked for 2026-10-07:

    can we observe in the same rolling window manner if the zscore rises or
    crashes with fast speed or rate e.g. window 1 produce zscore of 2 and window
    2 gives 0.5

That is a state the level alone cannot name. A bar at z = 0.5 that arrived from
z = 2 is still extended and already failing; a bar at z = 0.5 that arrived from
z = -1 is a move beginning. Both read 0.5.

So for each lookback `N`, beside `z[t]`:

    dz1[t] = z[t] - z[t-1]      one bar of change
    dz2[t] = z[t] - z[t-2]      two

and the question is asked **inside** buckets of the level, because `dz` and `z`
are not independent - a high z is usually a z that just rose. A 3 x 3 of
(level, speed) separates "extended and still rising" from "extended and
crashing", which is the pair the desk named.

Everything is computed from bars at or before `t`. The outcome is the move from
`t` to `t+h` over the ATR at `t`.

  MT5BT_DB=... SYMBOLS=... IV=4h python research/ideas/zscore_speed.py
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

import prims as P  # noqa: E402

WINDOWS = tuple(int(x) for x in os.environ.get("WINDOWS", "4,6,8,12,20,36").split(","))
HORIZONS = (1, 3, 6, 12)
IV = os.environ.get("IV", "4h")
OUT = Path(os.environ.get("OUT", ".data/zspeed"))
#: The level and speed cuts. 1.0 is a round number and not a fitted one; the
#: ceiling `(N-1)/sqrt(N)` means it is unreachable below N = 3, which is why the
#: windows here start at 4.
CUT = float(os.environ.get("CUT", 1.0))


def zscores(c: np.ndarray, n: int) -> np.ndarray:
    s = pd.Series(c)
    sd = s.rolling(n).std(ddof=1)
    return ((s - s.rolling(n).mean()) / sd.replace(0.0, np.nan)).to_numpy()


def one(sym):
    import run as R
    import survivors
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, IV)
    if df is None:
        return None
    df = df.reset_index(drop=True)
    c = df["close"].to_numpy()
    o, hi_, lo_ = (df[k].to_numpy() for k in ("open", "high", "low"))
    a = P.atr(df, 14)
    rng = np.maximum(hi_ - lo_, 1e-12)
    out = {"sym": sym, "day": (df["ts"].to_numpy() // 86400).astype(int),
           "body70": (np.abs(c - o) / rng) >= 0.70}
    for n in WINDOWS:
        z = zscores(c, n)
        out[f"z{n}"] = z
        out[f"d1_{n}"] = np.r_[np.nan, np.diff(z)]
        out[f"d2_{n}"] = np.r_[np.nan, np.nan, z[2:] - z[:-2]]
    for h in HORIZONS:
        fwd = np.full(len(c), np.nan)
        fwd[:-h] = c[h:] - c[:-h]
        with np.errstate(invalid="ignore", divide="ignore"):
            out[f"f{h}"] = np.where(a > 0, fwd / a, np.nan)
    return pd.DataFrame(out)


def block_ci(v, days, draws=2000, seed=23):
    v = np.asarray(v, float)
    ok = np.isfinite(v)
    v, days = v[ok], np.asarray(days)[ok]
    if len(v) < 50:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(days, return_inverse=True)
    sums = np.bincount(inv, weights=v, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    pick = rng.integers(0, len(uniq), size=(draws, len(uniq)))
    got = sums[pick].sum(axis=1) / np.maximum(cnts[pick].sum(axis=1), 1.0)
    return float(v.mean()), float(np.percentile(got, 5)), float(np.percentile(got, 95))


def band(x, cut):
    return np.where(x >= cut, "high", np.where(x <= -cut, "low", "mid"))


def main() -> None:
    import run as R
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        parts = [p for p in pool.map(one, syms) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    print(f"{len(d):,} {IV} bars over {d['sym'].nunique()} instruments, cut at +-{CUT:g}\n")
    pd.set_option("display.width", 230)
    pd.set_option("display.max_rows", 400)

    rows = []
    for n in WINDOWS:
        for speed in ("d1_", "d2_"):
            zc, dc = f"z{n}", f"{speed}{n}"
            g = d[np.isfinite(d[zc]) & np.isfinite(d[dc])].copy()
            g["lvl"] = band(g[zc].to_numpy(), CUT)
            g["spd"] = band(g[dc].to_numpy(), CUT)
            for h in HORIZONS:
                gg = g[np.isfinite(g[f"f{h}"])]
                for lvl in ("high", "mid", "low"):
                    for spd in ("high", "mid", "low"):
                        sub = gg[(gg["lvl"] == lvl) & (gg["spd"] == spd)]
                        m_, l_, h_ = block_ci(sub[f"f{h}"], sub["day"])
                        rows.append(dict(N=n, speed=speed.rstrip("_"), h=h, level=lvl, dz=spd,
                                         n=len(sub), fwd=m_, lo=l_, hi=h_))
    t = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    t.to_csv(OUT / "zspeed.csv", index=False)

    for speed in ("d1", "d2"):
        for h in (3, 6):
            print(f"\n=== {speed}: forward move at h = {h}, in ATR  (rows: z level, cols: dz) ===")
            cut = t[(t["speed"] == speed) & (t["h"] == h)]
            print(cut.pivot_table(index=["N", "level"], columns="dz", values="fwd")
                  .reindex(columns=["low", "mid", "high"]).round(3).to_string())
            print("  counts")
            print(cut.pivot_table(index=["N", "level"], columns="dz", values="n")
                  .reindex(columns=["low", "mid", "high"]).fillna(0).astype(int).to_string())

    print("\n=== the desk's pair: extended and still rising, against extended and crashing ===")
    for speed in ("d1", "d2"):
        for h in HORIZONS:
            cut = t[(t["speed"] == speed) & (t["h"] == h) & (t["level"] == "high")]
            up = cut[cut["dz"] == "high"].set_index("N")
            dn = cut[cut["dz"] == "low"].set_index("N")
            for n in WINDOWS:
                if n not in up.index or n not in dn.index:
                    continue
                a_, b_ = up.loc[n], dn.loc[n]
                print(f"  {speed} N={n:>2} h={h:>2}  rising {a_.fwd:+.3f} "
                      f"[{a_.lo:+.3f},{a_.hi:+.3f}] n={int(a_.n):>6}   "
                      f"crashing {b_.fwd:+.3f} [{b_.lo:+.3f},{b_.hi:+.3f}] n={int(b_.n):>6}   "
                      f"gap {a_.fwd - b_.fwd:+.3f}")
    print(f"\nwritten: {OUT / 'zspeed.csv'}")


if __name__ == "__main__":
    main()
