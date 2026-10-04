"""The aged-zone tests (aged, return manner + HTF, stop at return volatility) on FX, metals and Deriv.

Frozen in `aged_markets_rule.json` before this ran. Reuses `aged_zones.one`, `aged_context.one` and
`aged_volstop.one` on the broker's bars, and scores each market set apart.

  OUT=... MT5BT_DB=... MODE=run|plot python research/ideas/aged_markets.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("RET_DAYS", "180")

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import aged_context as X  # noqa: E402
import aged_volstop as V  # noqa: E402
import aged_zones as A  # noqa: E402
import turn_trade as TT  # noqa: E402
import turn_zones as TZ  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/aged_markets"))
SETS = {
    "FX_UNSEEN": "AUDUSD USDCAD USDCHF NZDUSD EURJPY GBPJPY EURGBP AUDJPY USDCNH".split(),
    "METAL_UNSEEN": "XAGUSD XPTUSD XPDUSD XCUUSD".split(),
    "DERIV_DIFFUSIVE": ["Volatility 75 Index", "Volatility 25 Index", "Step Index", "Drift Switch Index 10",
                        "Volatility 10 Index", "Volatility 50 Index", "Volatility 100 Index", "Step Index 200",
                        "Step Index 500", "Drift Switch Index 20", "Drift Switch Index 30"],
    "FX_SEEN": "EURUSD GBPUSD USDJPY".split(),
    "XAUUSD": ["XAUUSD"],
    "DERIV_JUMPY": ["Jump 50 Index", "Boom 1000 Index", "Crash 1000 Index", "Range Break 100 Index"],
}
JUDGED = ("FX_UNSEEN", "METAL_UNSEEN", "DERIV_DIFFUSIVE")
SCOPE = {s: k for k, v in SETS.items() for s in v}
NS = (0.5, 1, 2, 4, 10)


def pool(fn, jobs):
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 8))) as p:
        return [g for g in p.map(fn, jobs) if g is not None]


def boot_row(x, col, rng, **tag):
    y = x.assign(R=x[col])
    lo, hi = TT.boot(y, rng) if len(y) > 30 else (np.nan, np.nan)
    return dict(**tag, n=len(y), R=y["R"].mean(), lo=lo, hi=hi,
                R_before=y.loc[y["ts"] < TT.SPLIT, "R"].mean(), R_after=y.loc[y["ts"] >= TT.SPLIT, "R"].mean())


def verdict(t, test, scope, cell, base):
    """cell / base: (column filter dict); the frozen pass conditions."""
    def pick(src, **kw):
        m = (t["test"] == test) & (t["scope"] == scope) & (t["src"] == src)
        for k, v in kw.items():
            m &= t[k] == v
        r = t[m]
        return r.iloc[0] if len(r) else None
    p, w, g, b = pick("real", **cell), pick("walk", **cell), pick("garch", **cell), pick("real", **base)
    if p is None or w is None or g is None or b is None:
        return "n/a"
    ok = (p["R"] > 0 and p["lo"] > 0 and p["R_before"] > 0 and p["R_after"] > 0
          and p["R"] > w["R"] and p["R"] > g["R"] and p["R"] > b["R"])
    return (f"R {p['R']:+.3f} [{p['lo']:+.3f}, {p['hi']:+.3f}] n={int(p['n'])}; walk {w['R']:+.3f}; garch {g['R']:+.3f}; "
            f"base {b['R']:+.3f} -> {'PASSES' if ok else 'fails'}")


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("mt5", s, iv, src) for src in ("real", "walk", "garch") for iv in ("4h", "1d") for s in SCOPE]
    got = pool(A.one, jobs)
    z = pd.concat([g[0] for g in got if len(g[0])], ignore_index=True)
    z.to_pickle(OUT / "aged_markets_zones.pkl.gz")
    keys = [(src, sym, iv, g) for (src, sym, iv), g in z.groupby(["src", "sym", "iv"])]
    cx = pd.concat(pool(X.one, keys), ignore_index=True)
    vs = pd.concat(pool(V.one, keys), ignore_index=True)
    cx["scope"] = cx["sym"].map(SCOPE)
    cx = X.terciles(cx, ["scope", "iv"])
    cx["manner"] = cx["manner2"]
    for d in (z, cx, vs):
        d["scope"] = d["sym"].map(SCOPE)
        d["source"] = d["src"].str.split(":").str[1]
        d["wait_d"] = d["wait"] * d["iv"].map(TZ.SEC) / 86400
    cx.to_pickle(OUT / "aged_markets_context.pkl.gz")
    vs.to_pickle(OUT / "aged_markets_volstop.pkl.gz")
    rng = np.random.default_rng(111)
    rows = []
    for (scope, src), g in z.groupby(["scope", "source"]):
        for b, m in (("0-2d", g["wait_d"] < 2), (">=10d", g["wait_d"] >= 10), ("30-180d", g["wait_d"] >= 30)):
            r = boot_row(g[m], "E1", rng, test="aged", scope=scope, src=src, cell=b)
            r.update({f"P{N}R": (g[m]["mfe"] >= N).mean() for N in NS})
            rows.append(r)
    for (scope, src), g in cx.groupby(["scope", "source"]):
        sa = (g["manner"] == "SLOW") & (g["htf"] == "ALIGNED")
        cells = [("SLOW & ALIGNED", sa), ("rest", ~sa)] + [(m, g["manner"] == m) for m in ("SLOW", "MEDIUM", "FAST")] + \
                [(h, g["htf"] == h) for h in ("ALIGNED", "NEUTRAL", "COUNTER")]
        for name, m in cells:
            r = boot_row(g[m], "E1", rng, test="context", scope=scope, src=src, cell=name)
            r.update({f"P{N}R": (g[m]["mfe"] >= N).mean() for N in NS})
            rows.append(r)
    for (scope, src), g in vs.groupby(["scope", "source"]):
        for b, m in (("0-2d", g["wait_d"] < 2), (">=10d", g["wait_d"] >= 10)):
            r = boot_row(g[m], "V1_E1", rng, test="volstop", scope=scope, src=src, cell=b)
            r.update({f"P{N}R": (g[m]["V1_mfe"] >= N).mean() for N in NS})
            rows.append(r)
    t = pd.DataFrame(rows).round(3)
    t.to_csv(OUT / "aged_markets.csv", index=False)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 600)
    print(t.to_string(index=False))
    print("1/(N+1):", {N: round(1 / (N + 1), 3) for N in NS})
    print("\nVERDICTS (judged sets):")
    for scope in JUDGED:
        print(f"  {scope:16s} aged    {verdict(t, 'aged', scope, dict(cell='>=10d'), dict(cell='0-2d'))}")
        print(f"  {scope:16s} context {verdict(t, 'context', scope, dict(cell='SLOW & ALIGNED'), dict(cell='rest'))}")
        print(f"  {scope:16s} volstop {verdict(t, 'volstop', scope, dict(cell='>=10d'), dict(cell='0-2d'))}")


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = pd.read_csv(OUT / "aged_markets.csv")
    tests = (("aged", ">=10d"), ("context", "SLOW & ALIGNED"), ("volstop", ">=10d"))
    scopes = list(SETS)
    fig, axes = plt.subplots(len(tests), len(scopes), figsize=(26, 12), sharey=True)
    for i, (test, cell) in enumerate(tests):
        for j, scope in enumerate(scopes):
            ax = axes[i, j]
            for src, st in (("real", "-o"), ("walk", "--s"), ("garch", ":^")):
                r = t[(t["test"] == test) & (t["scope"] == scope) & (t["src"] == src) & (t["cell"] == cell)]
                if len(r):
                    r = r.iloc[0]
                    ax.plot(NS, [r[f"P{N}R"] for N in NS], st, label=f"{src}  R {r['R']:+.3f} (n {int(r['n'])})")
            ax.plot(NS, [1 / (N + 1) for N in NS], color="grey", lw=0.8, label="1/(N+1)")
            ax.set_xscale("log")
            ax.set_title(f"{scope}: {test} ({cell})", fontsize=9)
            ax.legend(fontsize=7)
    for ax in axes[:, 0]:
        ax.set_ylabel("P(trade reaches N R)")
    fig.suptitle("aged zones on FX, metals and Deriv: P(N R) real vs iid and GARCH walks; mean R per trade in the legend")
    fig.tight_layout()
    fig.savefig(OUT / "aged_markets_pnr.png", dpi=75)
    plt.close(fig)
    print("plots written", flush=True)


def main():
    {"run": run, "plot": plot}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
