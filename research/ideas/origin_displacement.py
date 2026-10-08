"""Filter fade-to-value's own origins by displacement, and see what it buys.

The desk's thesis, 2026-10-08, after reading what `fade-to-value` actually does.
It already trades origins: it refuses unless price is within `REACH_VOL` of one
(`not_at_origin`), checks freshness against `origin_*_revisits`
(`stale_origin`), and anchors its stop beyond the origin rather than beyond the
level. What it does **not** do is ask how the origin was made.

So this is not a new trade. It is **one filter on a population that already
exists**: keep only the origins a displacement left - `PUSH_N` candles of
`PUSH_BODY`+ body, the zone rule's own numbers - and compare against the same
origins without it.

Production's origins are replayed exactly as production finds them, through
`zones_prod` (`structures/drawing/origins.py`, every 4 bars over the last 1,000
at that bar's volatility unit), so the population under test is the one the
strategy really sees - not a research substitute.

The trade is fade-to-value's: enter **at** the origin on its first return, stop
beyond the origin's far edge. Scored on the barrier - did the target come before
the stop - because that is where every other version of this structure died, and
on R with a day-block interval.

  ZONES=prod MT5BT_DB=... python research/ideas/origin_displacement.py
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

OUT = Path(os.environ.get("OUT", ".data/origindisp"))
HOLD = int(os.environ.get("HOLD", 60))
TARGET_R = float(os.environ.get("TARGET_R", 2.0))   # the barrier, in R
BUF = float(os.environ.get("BUF", 0.25))            # stop past the origin, in ATR


def left_by_displacement(o, h, l, c, p, side, n, body):
    """Did `n` candles of `body`+ body leave this origin, the origin's way?"""
    k = list(range(p + 1, p + 1 + n))
    if k[-1] >= len(c):
        return False
    for i in k:
        rng = max(h[i] - l[i], 1e-12)
        if side * (c[i] - o[i]) < body * rng:
            return False
    return True


def one(job):
    import run as R
    import survivors
    import zones as Z
    sym, iv = job
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")
    got = survivors.book_for(sym, iv)
    if got is None:
        return []
    df = got[0].bars.reset_index(drop=True)
    a = P.atr(df, 14)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(df)
    out = []
    for z in Z.zones_prod(df, a):
        if z.ret < 0 or z.ret + 2 >= n or not a[z.p] > 0:
            continue
        side = z.side
        disp = left_by_displacement(o, h, l, c, z.p, side, Z.PUSH_N, Z.PUSH_BODY)
        # fade-to-value's geometry: in at the origin, stop beyond its far edge
        i = z.ret
        entry = z.hi
        stop = z.lo - side * BUF * a[z.p]
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        target = entry + side * TARGET_R * risk
        hit = stopped = None
        for k in range(i, min(n, i + HOLD)):
            if (l[k] <= stop) if side > 0 else (h[k] >= stop):
                stopped = k
                break
            if (h[k] >= target) if side > 0 else (l[k] <= target):
                hit = k
                break
        if stopped is not None:
            r, how = -1.0, "stopped"
        elif hit is not None:
            r, how = TARGET_R, "target"
        else:
            r = side * (c[min(n - 1, i + HOLD)] - entry) / risk
            how = "held"
        out.append(dict(sym=sym, iv=iv, disp=disp, side=side, ts=float(df.ts[i]),
                        r=r, how=how, revisits=z.parts and len(z.parts) or 0))
    return out


def block_ci(v, days, draws=4000, seed=53):
    v = np.asarray(v, float)
    if len(v) < 20:
        return (float(v.mean()) if len(v) else np.nan), np.nan, np.nan
    rng = np.random.default_rng(seed)
    u, inv = np.unique(np.asarray(days), return_inverse=True)
    s = np.bincount(inv, weights=v, minlength=len(u))
    cn = np.bincount(inv, minlength=len(u)).astype(float)
    p = rng.integers(0, len(u), size=(draws, len(u)))
    g = s[p].sum(1) / np.maximum(cn[p].sum(1), 1)
    return float(v.mean()), float(np.percentile(g, 5)), float(np.percentile(g, 95))


def main() -> None:
    import run as R
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    ivs = os.environ.get("INTERVALS", "1h,4h,1d").split(",")
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 14))) as pool:
        rows = [r for got in pool.map(one, [(s, iv) for iv in ivs for s in syms]) for r in got]
    d = pd.DataFrame(rows)
    if d.empty:
        print("no origins returned to")
        return
    d = d[~d.sym.str.contains("Boom|Crash|Jump|Step|Volatility|Drift|Range Break")]
    d["day"] = (d.ts // 86400).astype(int)
    print(f"{len(d)} production origins traded at, {d.sym.nunique()} instruments")
    print(f"target {TARGET_R:g}R, stop {BUF:g} ATR past the origin, hold {HOLD} bars")
    print(f"left by a displacement: {d.disp.mean():.1%} of them\n")
    pd.set_option("display.width", 220)
    for iv in sorted(d.iv.unique()):
        g = d[d.iv == iv]
        if len(g) < 60:
            continue
        print(f"--- {iv}  (n={len(g)})")
        for lab, sub in (("displacement", g[g.disp]), ("no displacement", g[~g.disp])):
            if len(sub) < 25:
                print(f"    {lab:<16} n={len(sub)} - too few")
                continue
            m, lo, hi = block_ci(sub.r, sub.day)
            print(f"    {lab:<16} n={len(sub):>5}  hit {(sub.how == 'target').mean():.1%}  "
                  f"stopped {(sub.how == 'stopped').mean():.1%}  "
                  f"R {m:+.3f} [{lo:+.3f},{hi:+.3f}]")
        a_, b_ = g[g.disp], g[~g.disp]
        if min(len(a_), len(b_)) >= 25:
            print(f"    {'gap':<16} {a_.r.mean() - b_.r.mean():+.3f} R, "
                  f"{(a_.how == 'target').mean() - (b_.how == 'target').mean():+.1%} hit")
        print()
    OUT.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT / "origins.csv", index=False)
    print(f"written: {OUT / 'origins.csv'}")


if __name__ == "__main__":
    main()
