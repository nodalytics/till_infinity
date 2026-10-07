"""How often does price come back to the zone at all, and how long does it take?

The return rate is a property of the **zone population**, not of any trade, so it
cannot be read off the trade tables: `setups` drops a zone that never returned,
which is exactly the case being counted. This builds the zones and counts them.

Reported per interval, for both builders:

  zones       found by the rule
  returned    price traded back into the band within `EXPIRE` bars
  bars        median bars from the zone going live to that return
  held        of those that returned, no close beyond the far edge afterwards

Read the return rate against `docs/magnet.md` first: levels are not magnets, and
a long enough window wanders back to most places. A rate near 100% over 300 bars
is a statement about 300 bars.

  MT5BT_DB=... SYMBOLS=... INTERVALS=1h,4h,1d,1w python research/ideas/zone_returns.py
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


def one(job):
    import run as R
    import survivors
    import zones as Z
    sym, iv, builder = job
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")
    got = Z.book_at(sym, iv)
    if got is None:
        return []
    df = got[0].bars.reset_index(drop=True)
    a = P.atr(df, 14)
    zs = (Z.zones_ob if builder == "ob" else Z.zones_chain)(df, a)
    out = []
    for z in zs:
        held = Z.zone_held(df if z.side > 0 else Z.flip(df), a,
                           z if z.side > 0 else Z.Zone(
                               side=1, p=z.p, lo=-z.lo, hi=-z.hi, bos=z.bos,
                               bos_level=-z.bos_level, fvg=z.fvg, live=z.live,
                               leg_extreme=-z.leg_extreme, clean=z.clean, push=z.push,
                               push_hi=z.push_hi, ob=z.ob, line=-z.line, ret=z.ret,
                               rank=z.rank)) if z.ret >= 0 else False
        out.append(dict(sym=sym, iv=iv, builder=builder, side=z.side, rank=z.rank,
                        returned=z.ret >= 0, bars=(z.ret - z.live) if z.ret >= 0 else np.nan,
                        held=held))
    return out


def main() -> None:
    import run as R
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    ivs = os.environ.get("INTERVALS", "1h,4h,1d,1w").split(",")
    jobs = [(s, iv, b) for b in ("ob", "chain") for iv in ivs for s in syms]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        rows = [r for got in pool.map(one, jobs) for r in got]
    d = pd.DataFrame(rows)
    if d.empty:
        print("no zones")
        return
    pd.set_option("display.width", 200)
    g = d.groupby(["builder", "iv"]).agg(
        zones=("returned", "size"), returned=("returned", "mean"),
        bars=("bars", "median"), long=("side", lambda x: (x > 0).mean()))
    g["held_of_returned"] = d[d["returned"]].groupby(["builder", "iv"])["held"].mean()
    print("\n=== return rate ===")
    print(g.round(3).to_string())
    print("\n=== by rank (chain) ===")
    c = d[(d["builder"] == "chain") & (d["rank"] > 0)]
    if len(c):
        print(c.groupby(["iv", "rank"]).agg(zones=("returned", "size"),
                                            returned=("returned", "mean"),
                                            bars=("bars", "median")).round(3).to_string())
    out = Path(os.environ.get("OUT", ".data/zreturns"))
    out.mkdir(parents=True, exist_ok=True)
    d.to_csv(out / "returns.csv", index=False)
    print(f"\nwritten: {out / 'returns.csv'}")


if __name__ == "__main__":
    main()
