"""Watch the instruments that lose, instead of dropping them.

Five instruments came out of `what-loses.md` significantly negative after
Benjamini-Hochberg, and the obvious move was to take them out of
`TRADING_SYMBOLS`. The desk's call on 2026-10-08 was to **watch them first** -
which is right, because the evidence for dropping was a single window and
dropping is the one change that cannot be evaluated afterwards. An instrument
that is not traded produces no record to revisit.

So this reports them on a schedule instead, each against the same two questions:

  is it still losing?   net per position with a day-block interval
  is it getting worse?  the same split into the first and second half of the
                        window, which is how every other claim here is checked

Run it against the broker record, not the journal: `judge-the-desk-on-the-broker`
is a standing rule here, and the journal undercounts positions that span a
restart.

  python research/ideas/instrument_watch.py .data/live/deals.json
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

#: The five from `what-loses.md`, plus the three `cycle-scalp` was bleeding into
#: before it stopped - those are the live question, not a settled one.
WATCH = ["Jump 25 Index", "Volatility 10 (1s) Index", "Volatility 25 Index",
         "Volatility 75 (1s) Index", "BTCUSD", "US SP 500", "Crash 500 Index",
         "Jump 50 Index", "Volatility 100 Index"]


def magic_table():
    src = (ROOT / "till_infinity/trading/config.py").read_text()
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "DEFAULT_MAGIC":
            out["base"] = ast.literal_eval(node.value)
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "MAGIC_ORDER":
            out["order"] = ast.literal_eval(node.value)
    return out


def block_ci(v, days, draws=4000, seed=13):
    v = np.asarray(v, float)
    if len(v) < 8:
        return (float(v.mean()) if len(v) else np.nan), np.nan, np.nan
    rng = np.random.default_rng(seed)
    u, inv = np.unique(np.asarray(days), return_inverse=True)
    s = np.bincount(inv, weights=v, minlength=len(u))
    c = np.bincount(inv, minlength=len(u)).astype(float)
    p = rng.integers(0, len(u), size=(draws, len(u)))
    got = s[p].sum(1) / np.maximum(c[p].sum(1), 1)
    return float(v.mean()), float(np.percentile(got, 5)), float(np.percentile(got, 95))


def positions(path):
    t = magic_table()
    base, order = t["base"], t["order"]
    d = pd.DataFrame(json.load(open(path)))
    d["time"] = pd.to_datetime(pd.to_numeric(d["time"], errors="coerce"), unit="s", utc=True)
    for c in ("profit", "swap", "commission", "fee"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0.0)
    d["net"] = d["profit"] + d["swap"] + d["commission"] + d["fee"]
    p = d.groupby("position_id").agg(net=("net", "sum"), closed=("time", "max"),
                                     sym=("symbol", "first"), magic=("magic", "first"))
    p = p[p.net != 0].dropna(subset=["magic"])
    p["strat"] = [order[int(m) - base - 1] if 1 <= int(m) - base <= len(order) else f"magic:{int(m)}"
                  for m in p.magic]
    p["day"] = p.closed.dt.date
    return p


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else ".data/live/deals.json"
    p = positions(path)
    print(f"{len(p)} closed positions, {p.closed.min().date()} to {p.closed.max().date()}\n")
    mid = p.closed.median()
    rows = []
    for sym in WATCH:
        g = p[p.sym == sym]
        if g.empty:
            print(f"  {sym:<26} no trades in the window")
            continue
        m, lo, hi = block_ci(g.net.to_numpy(), g.day.to_numpy())
        a, b = g[g.closed < mid], g[g.closed >= mid]
        verdict = ("still losing" if hi < 0 else
                   "stopped trading" if len(b) == 0 else
                   "inconclusive" if lo < 0 < hi else "positive")
        print(f"  {sym:<26} n={len(g):>4}  net {g.net.sum():+9.2f}  each {m:+7.3f} "
              f"[{lo:+.3f},{hi:+.3f}]  first {a.net.mean() if len(a) else float('nan'):+7.3f} "
              f"({len(a)})  second {b.net.mean() if len(b) else float('nan'):+7.3f} ({len(b)})"
              f"   {verdict}")
        rows.append(dict(symbol=sym, n=len(g), net=g.net.sum(), each=m, lo=lo, hi=hi,
                         n_first=len(a), n_second=len(b), verdict=verdict))
    out = pd.DataFrame(rows)
    print("\nonly the rows whose whole interval is below zero are evidence to drop on:")
    bad = out[out.hi < 0] if len(out) else out
    print("  " + (", ".join(bad.symbol) if len(bad) else "none"))
    print("\nand the rest of the book, for context:")
    rest = p[~p.sym.isin(WATCH)].groupby("sym").agg(n=("net", "size"), net=("net", "sum"),
                                                    each=("net", "mean")).sort_values("net")
    print(rest[rest.n >= 20].round(3).head(8).to_string())


if __name__ == "__main__":
    main()
