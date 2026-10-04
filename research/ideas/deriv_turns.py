"""Violent turns on Deriv's synthetics: the signature, the turn trade and the turn-origin zones.

Pre-registered 2026-10-04, before any run. Deriv's synthetics are a real market whose generators are
published (`generators.md`, `deriving.md`): the volatility indices are iid Brownian, Step is a fair
coin, Boom/Crash spike at a stated rate, Range Break has a real range. Expectation: every number
equals its walk's, since a known martingale has no turn that tells its side. A difference beyond the
walks means either a property of the generator (Range Break, Drift Switch) or a bias in our method.

  turns     every 12-bar low knowable at t (lowest low of t-2..t at or below the lowest of t-11..t-3),
            on the chart and the flipped chart; major if price rallies 3 ATR before trading below it
            within 60 bars (after the fact; only to group)
  features  T1 DISPLACE_C, T2 BREACH_REVERT, T3 DELIVERY_SHIFT up at t (MCFL v1), T_any, and RZ:
            range_z at or above violence.py's MT5 VIOLENT threshold for the timeframe
  lift      P(major | feature) / P(major | any 12-bar low), real vs iid and GARCH walks
  trade     turn_trade.trades_exits: entry t+1's open, stop 0.1 ATR under the 3-bar low, E1 2-ATR trail,
            E2 opposite DELIVERY_SHIFT, 10 days, 0.05 ATR stop slippage, the broker's spread floor
  zones     turn_zones.zones: [low, low + 0.5 ATR] on the first return, proven / left, E1 and X2
  data      the 15 Deriv synthetics in the broker's database, 1h, 4h, 1d; Boom, Crash, Jump and Range
            Break reported apart (bar fills miss their jumps)

  OUT=... MT5BT_DB=... MODE=run|plot python research/ideas/deriv_turns.py
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import turn_trade as TT  # noqa: E402
import turn_zones as TZ  # noqa: E402

TT.SEC["1d"] = 86400
OUT = Path(os.environ.get("OUT", ".data/deriv_turns"))
JUMPY = ("Boom", "Crash", "Jump", "Range Break")
IVS = ("1h", "4h", "1d")
SOURCES = ("real", "walk", "garch")
NS = (0.5, 1, 2, 4, 10)
FEATS = ("T1", "T2", "T3", "T_any", "RZ")


def symbols():
    import run as R
    return [s for s, f in R.FAMILY.items() if f == "deriv"]


def lows(df):
    """Every 12-bar low: whether it became a major turn and which features fired at it."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(df)
    a = TZ.atr(df)
    low3 = pd.Series(l).rolling(3).min().to_numpy()
    prior = pd.Series(l).shift(3).rolling(9).min().to_numpy()
    rng_ = h - l
    rm = pd.Series(rng_).rolling(10).mean().shift(1).to_numpy()
    rs = pd.Series(rng_).rolling(10).std().shift(1).to_numpy()
    U = TT.ups(df)
    rows = []
    for t in np.flatnonzero(low3 <= prior):
        if t < 30 or t + 2 >= n or not a[t] > 0:
            continue
        major = False
        for k in range(t + 1, min(n, t + 60)):
            if l[k] < low3[t]:
                break
            if h[k] >= low3[t] + 3 * a[t]:
                major = True
                break
        rows.append(dict(t=t, major=major, T1=U["DISPLACE_C"][t], T2=U["BREACH_REVERT"][t],
                         T3=U["DELIVERY_SHIFT"][t], rz=(rng_[t] - rm[t]) / rs[t] if rs[t] > 0 else np.nan))
    return rows


def one(job):
    from mcfl import candles, synth
    from mcfl.parse import flip
    sym, iv, source = job
    df, fee_px = TZ.load("mt5", sym, iv)
    if df is None or len(df) < 300:
        return None
    cost_atr = fee_px / np.maximum(np.asarray(candles.table(df)["atr"], float), 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    if source != "real":
        ts, n = df["ts"].to_numpy(), len(df)
        sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
        seed = zlib.crc32(f"deriv{sym}{iv}{source}".encode()) % 100000
        gen = synth.walk if source == "walk" else synth.garch
        df = gen(n, sigma=sigma, seed=seed, steps=TT.WALK_STEPS).reset_index(drop=True).iloc[:n]
        df["ts"] = ts[:len(df)]
        df["volume"] = 0.0
        cost_atr = cost_atr[:len(df)]
    src = f"deriv:{source}"
    L, T, Z = [], [], []
    for side, frame in ((1, df), (-1, flip(df))):
        L += [dict(r, side=side) for r in lows(frame)]
        T += TT.trades_exits(frame, side, cost_atr, src, sym, iv)
        Z += TZ.zones(frame, side, cost_atr, src, sym, iv)
    tag = dict(src=src, sym=sym, iv=iv)
    print(f"  {sym} {iv} {source}: {len(L)} lows, {len(T)} trades, {len(Z)} zone returns", flush=True)
    return pd.DataFrame(L).assign(**tag), pd.DataFrame(T), pd.DataFrame(Z)


def scope(sym):
    return "jumpy" if sym.startswith(JUMPY) else "diffusive"


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(s, iv, src) for src in SOURCES for iv in IVS for s in symbols()]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 12))) as pool:
        got = [g for g in pool.map(one, jobs) if g is not None]
    L, T, Z = (pd.concat([g[i] for g in got if len(g[i])], ignore_index=True) for i in range(3))
    for d in (L, T, Z):
        d["scope"] = d["sym"].map(scope)
    L["T_any"] = L["T1"] | L["T2"] | L["T3"]
    L["RZ"] = L["rz"] >= L["iv"].map(TZ.RZ)
    Z["SIG_RZ"], Z["ALL"] = Z["SIG"] & Z["RZ"], True
    for name, d in (("lows", L), ("trades", T), ("zones", Z)):
        d.to_pickle(OUT / f"deriv_{name}.pkl.gz")
    rng = np.random.default_rng(61)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 400)

    # 1. the signature's lift
    rows = []
    for (sc, src, iv), g in L.groupby(["scope", "src", "iv"]):
        base = g["major"].mean()
        for f in FEATS:
            x = g[g[f]]
            rows.append(dict(scope=sc, src=src, iv=iv, feature=f, n=len(x), rate=g[f].mean(),
                             p_major=x["major"].mean(), base=base, lift=x["major"].mean() / base if base else np.nan))
    lift = pd.DataFrame(rows).round(3)
    lift.to_csv(OUT / "deriv_lift.csv", index=False)
    print("\nlift of P(major turn) over any 12-bar low:")
    print(lift.pivot_table(index=["scope", "iv", "feature"], columns="src", values="lift").round(3).to_string())

    # 2. the turn trade
    rows = []
    for (sc, src), g in T.groupby(["scope", "src"]):
        for name in ("all 12-bar lows", *TT.SIGNALS):
            x = g if name == "all 12-bar lows" else g[g[name]]
            for ex in ("E1", "E2"):
                y = x.assign(R=x[ex])
                lo, hi = TT.boot(y, rng) if len(y) > 30 else (np.nan, np.nan)
                rows.append(dict(scope=sc, src=src, signal=name, exit=ex, n=len(y), R=y["R"].mean(), lo=lo, hi=hi,
                                 **{f"R_{iv}": y.loc[y["iv"] == iv, "R"].mean() for iv in IVS},
                                 **{f"P{N}R": (x[f"{ex}_mfe"] >= N).mean() for N in NS}))
    tt = pd.DataFrame(rows).round(3)
    tt.to_csv(OUT / "deriv_trades.csv", index=False)
    print("\nturn trade:")
    print(tt.to_string(index=False))

    # 3. the turn-origin zones
    rows = []
    for (sc, src, act), g in Z.groupby(["scope", "src", "act"]):
        for fam in TZ.FAMILIES:
            x = g[g[fam]]
            for ex in ("E1", "X2"):
                y = x.assign(R=x[ex])
                lo, hi = TT.boot(y, rng) if len(y) > 30 else (np.nan, np.nan)
                r = dict(scope=sc, src=src, act=act, family=fam, exit=ex, n=len(y), R=y["R"].mean(), lo=lo, hi=hi,
                         **{f"R_{iv}": y.loc[y["iv"] == iv, "R"].mean() for iv in IVS})
                if ex == "E1":
                    r.update({f"P{N}R": (x["mfe"] >= N).mean() for N in NS})
                rows.append(r)
    zt = pd.DataFrame(rows).round(3)
    zt.to_csv(OUT / "deriv_zones.csv", index=False)
    print("\nturn-origin zones:")
    print(zt.to_string(index=False))
    print("1/(N+1):", {N: round(1 / (N + 1), 3) for N in NS})


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    lift = pd.read_csv(OUT / "deriv_lift.csv")
    tt = pd.read_csv(OUT / "deriv_trades.csv")
    zt = pd.read_csv(OUT / "deriv_zones.csv")
    cols = {"deriv:real": "#1d3557", "deriv:walk": "#a8dadc", "deriv:garch": "#e9c46a"}
    fig, axes = plt.subplots(2, 3, figsize=(22, 10))
    for i, sc in enumerate(("diffusive", "jumpy")):
        for j, iv in enumerate(IVS):
            ax = axes[i, j]
            g = lift[(lift["scope"] == sc) & (lift["iv"] == iv)]
            x = np.arange(len(FEATS))
            for k, (src, col) in enumerate(cols.items()):
                v = g[g["src"] == src].set_index("feature").reindex(FEATS)["lift"]
                ax.bar(x + (k - 1) * 0.27, v, 0.27, color=col, label=src.split(":")[1])
            ax.axhline(1, color="grey", lw=0.8)
            ax.set_xticks(x, FEATS)
            ax.set_title(f"Deriv {sc} {iv}: lift of P(major turn)", fontsize=10)
            ax.legend(fontsize=8)
    fig.suptitle("violent-turn signature on Deriv synthetics: real vs iid and GARCH walks (1 = no better than any 12-bar low)")
    fig.tight_layout()
    fig.savefig(OUT / "deriv_turn_lift.png", dpi=80)
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(16, 10), sharey=True)
    for i, sc in enumerate(("diffusive", "jumpy")):
        ax = axes[i, 0]
        for src, col in cols.items():
            r = tt[(tt["scope"] == sc) & (tt["src"] == src) & (tt["signal"] == "T_any") & (tt["exit"] == "E1")]
            if len(r):
                r = r.iloc[0]
                ax.plot(NS, [r[f"P{N}R"] for N in NS], "-o", color=col, label=f"{src.split(':')[1]}  R {r['R']:+.3f}")
        ax.set_title(f"Deriv {sc}: turn trade T_any, trail", fontsize=10)
        ax = axes[i, 1]
        for src, col in cols.items():
            r = zt[(zt["scope"] == sc) & (zt["src"] == src) & (zt["act"] == "proven") & (zt["family"] == "SIG") & (zt["exit"] == "E1")]
            if len(r):
                r = r.iloc[0]
                ax.plot(NS, [r[f"P{N}R"] for N in NS], "-o", color=col, label=f"{src.split(':')[1]}  R {r['R']:+.3f}")
        ax.set_title(f"Deriv {sc}: turn-origin zone SIG proven, trail", fontsize=10)
        for ax in axes[i]:
            ax.plot(NS, [1 / (N + 1) for N in NS], color="grey", lw=0.8, label="1/(N+1)")
            ax.set_xscale("log")
            ax.set_xlabel("N (R)")
            ax.legend(fontsize=8)
    axes[0, 0].set_ylabel("P(trade reaches N R)")
    fig.suptitle("Deriv synthetics: P(N R) real vs walks; mean R per trade in the legend")
    fig.tight_layout()
    fig.savefig(OUT / "deriv_turn_pnr.png", dpi=80)
    plt.close(fig)
    print("plots written", flush=True)


def main():
    {"run": run, "plot": plot}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
