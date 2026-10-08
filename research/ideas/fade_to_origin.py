"""Fade the displacement, target its origin candle.

The desk's thesis, 2026-10-08. `fade-to-value` fades a move back toward value;
give "value" a definition - **the origin candle of a displacement** - and the
displacement research becomes a target rather than an entry.

This is the other side of the structure `order-block-zones.md` measured. That
study waited for price to **return** to the origin and then traded **with** the
displacement, and it lost everywhere - 1h -0.147R over 721 trades, and a barrier
test of 48.7% against a 48.6% base rate. Nothing in it tested the trade *toward*
the origin, and the `flip` arm is not that trade: `flip` was the opposite side
entered at market with the same stop and target *distances*, not a trade aimed at
a structural level.

It also turns the one number that study could not use into the number that
decides this one. **Price returns to the origin 77-81% of the time**
(`zone_returns.py`), flat across 1h, 4h, 1d and 1w. As an entry signal that rate
means nothing, because `EXPIRE` is 300 bars and 300 bars wanders back to most
prices. As the **hit rate of a target** it is the whole trade.

So the test is a barrier one, not a hit rate:

  entry   at the break of structure, against the displacement
  target  the origin candle - its body edge (`line`) and its far edge (`lo`),
          run as two arms because which one a desk would use is not obvious
  stop    beyond the leg extreme, at `STOP_PAD` of the leg's own size
  hold    `HOLD` bars, after which it is closed wherever it is

Reported against a coin twin on the same fills and the same geometry, because a
rule that aims at a level four times out of five will look magnificent on hit
rate alone.

  MT5BT_DB=... SYMBOLS=... INTERVALS=1h,4h,1d python research/ideas/fade_to_origin.py
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
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

import prims as P  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/fadeorigin"))
STOP_PAD = float(os.environ.get("STOP_PAD", 0.25))   # of the leg, beyond its extreme
HOLD = int(os.environ.get("HOLD", 60))               # bars before it is closed where it stands
DRAWS = 4000


#: Stops to try, as a share of the leg beyond the extreme it already made. The
#: first run used 0.25 alone and the stop turned out to be the whole result -
#: 89-91% of fades were stopped before a target that price reaches 77-81% of the
#: time. Breakeven is `1 / (1 + RR)`, and a wider stop trades hit rate against
#: RR directly, so there may be a pad where the two cross. If none does, the
#: thesis is dead rather than mis-parameterised.
PADS = tuple(float(x) for x in os.environ.get("PADS", "0.25,0.5,1.0,2.0,4.0").split(","))

#: When to fade. `live` is the break of structure - the earliest a reader could
#: act and the dumbest version of the idea, since it sells into a move that is
#: still going. The rest wait for the move to stop first, which is what a desk
#: fading a displacement would actually do.
#: How much body an `impulse_back` candle needs. 0.70 is the displacement
#: definition the zone work uses, but a candle turning a fade is not the same
#: object as one starting a leg, so the bar it has to clear is an open question
#: rather than a constant to inherit.
IMPULSES = tuple(float(x) for x in os.environ.get("IMPULSES", "0.45,0.5,0.6,0.7").split(","))
TURNS = ("live", "close_against", "two_against") + tuple(
    f"impulse_back:{b:g}" for b in IMPULSES
)


def _turn(o, h, l, c, start, stop_at, side, kind):
    """The bar to enter on, or None if the market never turned inside the window.

    `side` is the fade's direction, so a bar closing the fade's way is a bar
    that went against the displacement.
    """
    if kind == "live":
        return start
    run = 0
    for k in range(start + 1, stop_at):
        against = (c[k] < o[k]) if side < 0 else (c[k] > o[k])
        if kind == "close_against" and against:
            return k
        if kind == "two_against":
            run = run + 1 if against else 0
            if run >= 2:
                return k
        if kind.startswith("impulse_back") and against:
            body = abs(c[k] - o[k]) / max(h[k] - l[k], 1e-12)
            if body >= float(kind.split(":")[1]):
                return k
    return None


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
    for z in Z.zones_ob(df, a):
        if z.live + 2 >= n or not a[z.p] > 0:
            continue
        side = -z.side
        for turn in TURNS:
            i = _turn(o, h, l, c, z.live, min(n - 1, z.live + 20), side, turn)
            if i is None or i + 2 >= n:
                continue
            entry = c[i]
            # the extreme **as of entry**, since it can extend while we wait
            ext = h[z.p:i + 1].max() if side < 0 else l[z.p:i + 1].min()
            leg = abs(ext - z.lo)
            if leg <= 0:
                continue
            for pad in PADS:
                stop = ext - side * pad * leg
                for arm, target in (("line", z.line), ("far", z.lo)):
                    risk = abs(entry - stop)
                    if risk <= 0 or side * (target - entry) <= 0:
                        continue
                    reward = abs(target - entry)
                    hit = stopped = None
                    for k in range(i + 1, min(n, i + 1 + HOLD)):
                        up, dn = h[k], l[k]
                        if (up >= stop) if side < 0 else (dn <= stop):
                            stopped = k
                            break
                        if (dn <= target) if side < 0 else (up >= target):
                            hit = k
                            break
                    if stopped is not None:
                        r, how = -1.0, "stopped"
                    elif hit is not None:
                        r, how = reward / risk, "target"
                    else:
                        r = side * (c[min(n - 1, i + HOLD)] - entry) / risk
                        how = "held"
                    out.append(dict(sym=sym, iv=iv, turn=turn, pad=pad, arm=arm,
                                    ts=float(df.ts[i]), rr=reward / risk, r=r, how=how))
    return out


def block_ci(v, days, draws=DRAWS, seed=47):
    v = np.asarray(v, float)
    if len(v) < 20:
        return (float(v.mean()) if len(v) else np.nan), np.nan, np.nan
    rng = np.random.default_rng(seed)
    u, inv = np.unique(np.asarray(days), return_inverse=True)
    s = np.bincount(inv, weights=v, minlength=len(u))
    cn = np.bincount(inv, minlength=len(u)).astype(float)
    p = rng.integers(0, len(u), size=(draws, len(u)))
    got = s[p].sum(1) / np.maximum(cn[p].sum(1), 1)
    return float(v.mean()), float(np.percentile(got, 5)), float(np.percentile(got, 95))


def main() -> None:
    import run as R
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    ivs = os.environ.get("INTERVALS", "1h,4h,1d").split(",")
    jobs = [(s, iv) for iv in ivs for s in syms]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 14))) as pool:
        rows = [r for got in pool.map(one, jobs) for r in got]
    d = pd.DataFrame(rows)
    if d.empty:
        print("no trades")
        return
    d = d[~d.sym.str.contains("Boom|Crash|Jump|Step|Volatility|Drift|Range Break")]
    d["day"] = (d.ts // 86400).astype(int)
    print(f"{len(d)} fades, {d.sym.nunique()} instruments, "
          f"stop {STOP_PAD:g} of the leg beyond its extreme, hold {HOLD} bars\n")
    pd.set_option("display.width", 240)
    pd.set_option("display.max_rows", 300)
    rows = []
    for (iv, turn, pad, arm), g in d.groupby(["iv", "turn", "pad", "arm"]):
        if len(g) < 40 or arm != "line":
            continue
        m, lo, hi = block_ci(g.r, g.day)
        rr = g.rr.median()
        rows.append(dict(iv=iv, turn=turn, pad=pad, n=len(g), rr=round(rr, 2),
                         hit=(g.how == "target").mean(),
                         needs=1.0 / (1.0 + rr), stopped=(g.how == "stopped").mean(),
                         R=m, lo=lo, hi=hi))
    t = pd.DataFrame(rows)
    t["gap"] = t.hit - t.needs
    print("target `line`. `needs` is the hit rate breakeven asks for at that RR;")
    print("`gap` is what the trade actually gets minus what it needs.\n")
    for iv in sorted(t.iv.unique()):
        print(f"--- {iv}")
        print(t[t.iv == iv].sort_values("gap", ascending=False)
              .drop(columns="iv").round(4).to_string(index=False))
        print()
    best = t.sort_values("gap", ascending=False).head(5)
    print("=== closest to breaking even, any timeframe ===")
    print(best.round(4).to_string(index=False))
    print(f"\npositive R cells: {(t.lo > 0).sum()} of {len(t)}")
    OUT.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT / "fades.csv", index=False)
    print(f"\nwritten: {OUT / 'fades.csv'}")


if __name__ == "__main__":
    main()
