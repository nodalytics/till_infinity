"""A red candle in the midst of rising greens (a green among falling reds), as a zone.

Frozen in `candle_zone_rule.json` before this ran. The one bar where a run paused is marked from its
low to its open; traded on the first return with the run's direction, against any red candle with the
same departure and against iid and GARCH walks. Trades as `turn_zones.exits`.

  OUT=... MT5BT_DB=... MODE=run|plot python research/ideas/candle_zones.py
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

OUT = Path(os.environ.get("OUT", ".data/candle_zones"))
IVS = ("1h", "4h", "1d")
SEC = {"1h": 3600, "4h": 14400, "1d": 86400}
SOURCES = ("real", "walk", "garch")
FAMILIES = ("K3", "K2", "K2_BIG", "ANY")
LEAVE, LIVE_BARS, PAD = 1.0, 60, 0.1
NS = (0.5, 1, 2, 4, 10)


def deriv_symbols():
    import run as R
    return [s for s, f in R.FAMILY.items() if f == "deriv"]


def run_len(green, r, k, before):
    """Whether the k bars before (or after) r are all green."""
    idx = range(r - k, r) if before else range(r + 1, r + 1 + k)
    return all(0 <= i < len(green) and green[i] for i in idx)


def zones(df, side, cost_atr, src, sym, iv):
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy()
    n = len(df)
    a = TZ.atr(df)
    green, red = c > o, c < o
    ret_bars = int(20 * 86400 / SEC[iv])
    hold = max(1, int(10 * 86400 / SEC[iv]))
    rows = []
    for r in np.flatnonzero(red):
        if r < 30 or r + 4 >= n or not a[r] > 0:
            continue
        k2 = run_len(green, r, 2, True) and run_len(green, r, 2, False)
        k3 = k2 and run_len(green, r, 3, True) and run_len(green, r, 3, False)
        fam = dict(K3=k3, K2=k2, K2_BIG=k2 and (o[r] - c[r]) >= 0.5 * a[r], ANY=True)
        K = 3 if k3 else 2  # the bars it takes to know the run around r; ANY uses 2, as K2
        bottom, top = l[r], o[r]
        stop = bottom - PAD * a[r]
        live = None
        for j in range(r + 1, min(n, r + LIVE_BARS)):
            if l[j] < bottom:
                break
            if h[j] >= top + LEAVE * a[r]:
                live = max(j, r + K) + 1
                break
        if live is None or live >= n:
            continue
        f = next((j for j in range(live, min(n, live + ret_bars)) if l[j] <= top), None)
        if f is None:
            continue
        res = TZ.exits(o, h, l, c, f, top, stop, a[r], cost_atr[f] * a[f], hold)
        rows.append(dict(src=src, sym=sym, iv=iv, side=side, r=r, live=live, f=f, ts=int(ts[f]),
                         risk_atr=(top - stop) / a[r], **fam, **res))
    return rows


def one(job):
    from mcfl import candles, synth
    from mcfl.parse import flip
    venue, sym, iv, source = job
    df, fee_px = TZ.load("binance" if venue == "binance" else "mt5", sym, iv)
    if df is None or len(df) < 300:
        return None
    cost_atr = fee_px / np.maximum(np.asarray(candles.table(df)["atr"], float), 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    if source != "real":
        ts, n = df["ts"].to_numpy(), len(df)
        sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
        seed = zlib.crc32(f"{venue}{sym}{iv}{source}cz".encode()) % 100000
        gen = synth.walk if source == "walk" else synth.garch
        df = gen(n, sigma=sigma, seed=seed, steps=TT.WALK_STEPS).reset_index(drop=True).iloc[:n]
        df["ts"] = ts[:len(df)]
        df["volume"] = 0.0
        cost_atr = cost_atr[:len(df)]
    rows = []
    for side, frame in ((1, df), (-1, flip(df))):
        rows += zones(frame, side, cost_atr, f"{venue}:{source}", sym, iv)
    print(f"  {venue} {source} {sym} {iv}: {len(rows)} returns", flush=True)
    return pd.DataFrame(rows)


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    universe = (("binance", TT.COINS), ("mt5", TT.MT5), ("deriv", tuple(deriv_symbols())))
    jobs = [(v, s, iv, src) for src in SOURCES for iv in IVS for v, syms in universe for s in syms]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 12))) as pool:
        got = [g for g in pool.map(one, jobs) if g is not None and len(g)]
    d = pd.concat(got, ignore_index=True)
    d.to_pickle(OUT / "candle_zones.pkl.gz")
    rng = np.random.default_rng(71)
    rows = []
    for src, g in d.groupby("src"):
        for fam in FAMILIES:
            x = g[g[fam]]
            for ex in ("E1", "X2"):
                y = x.assign(R=x[ex])
                lo, hi = TT.boot(y, rng) if len(y) > 30 else (np.nan, np.nan)
                r = dict(src=src, family=fam, exit=ex, n=len(y), R=y["R"].mean(), lo=lo, hi=hi,
                         win=(y["R"] > 0).mean(), risk_atr=y["risk_atr"].median(),
                         R_before=y.loc[y["ts"] < TT.SPLIT, "R"].mean(), R_after=y.loc[y["ts"] >= TT.SPLIT, "R"].mean(),
                         **{f"R_{iv}": y.loc[y["iv"] == iv, "R"].mean() for iv in IVS})
                if ex == "E1":
                    r.update({f"P{N}R": (x["mfe"] >= N).mean() for N in NS})
                rows.append(r)
    t = pd.DataFrame(rows).round(3)
    t.to_csv(OUT / "candle_zones.csv", index=False)
    pd.set_option("display.width", 280)
    pd.set_option("display.max_rows", 300)
    print(t.to_string(index=False))
    print("1/(N+1):", {N: round(1 / (N + 1), 3) for N in NS})

    def cell(src, fam):
        return t[(t["src"] == src) & (t["family"] == fam) & (t["exit"] == "E1")].iloc[0]
    p, a = cell("binance:real", "K3"), cell("binance:real", "ANY")
    w, gw = cell("binance:walk", "K3"), cell("binance:garch", "K3")
    ok = (p["R"] > 0 and p["lo"] > 0 and p["R_before"] > 0 and p["R_after"] > 0
          and p["R"] > a["R"] and p["R"] > w["R"] and p["R"] > gw["R"])
    print(f"\nPRIMARY (K3, E1, Binance): R {p['R']:+.3f} [{p['lo']:+.3f}, {p['hi']:+.3f}] n={p['n']}, "
          f"before {p['R_before']:+.3f}, after {p['R_after']:+.3f}; ANY {a['R']:+.3f}; walk {w['R']:+.3f}; "
          f"garch {gw['R']:+.3f} -> {'PASSES' if ok else 'fails'}")


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mcfl.parse import flip
    t = pd.read_csv(OUT / "candle_zones.csv")
    fig, axes = plt.subplots(3, 4, figsize=(22, 13), sharey=True)
    for i, venue in enumerate(("binance", "mt5", "deriv")):
        for j, fam in enumerate(FAMILIES):
            ax = axes[i, j]
            for src, st in (("real", "-o"), ("walk", "--s"), ("garch", ":^")):
                r = t[(t["src"] == f"{venue}:{src}") & (t["family"] == fam) & (t["exit"] == "E1")]
                if len(r):
                    r = r.iloc[0]
                    ax.plot(NS, [r[f"P{N}R"] for N in NS], st, label=f"{src}  R {r['R']:+.3f} (n {int(r['n'])})")
            ax.plot(NS, [1 / (N + 1) for N in NS], color="grey", lw=0.8, label="1/(N+1)")
            ax.set_xscale("log")
            ax.set_title(f"{venue} {fam} (trail)", fontsize=10)
            ax.legend(fontsize=7)
            ax.set_xlabel("N (R)")
    for ax in axes[:, 0]:
        ax.set_ylabel("P(trade reaches N R)")
    fig.suptitle("counter-candle zones (a red among rising greens / a green among falling reds), first return: "
                 "P(N R) real vs iid and GARCH walks")
    fig.tight_layout()
    fig.savefig(OUT / "candle_zones_pnr.png", dpi=80)
    plt.close(fig)
    d = pd.read_pickle(OUT / "candle_zones.pkl.gz")  # our own output
    d = d[(d["src"] == "binance:real") & d["K3"] & (d["iv"] == "4h")]
    rng = np.random.default_rng(6)
    for tag, sub in (("winners", d[d["E1"] > 0]), ("losers", d[d["E1"] <= 0])):
        pick = sub.iloc[rng.choice(len(sub), min(6, len(sub)), replace=False)]
        fig, axes = plt.subplots(2, 3, figsize=(21, 10))
        for ax, (_, z) in zip(axes.flat, pick.iterrows(), strict=False):
            df = TT._bin(z.sym, z.iv)
            frame = df if z.side > 0 else flip(df)
            a = TZ.atr(frame)
            r, f = int(z.r), int(z.f)
            i0, i1 = max(0, r - 20), min(len(df) - 1, f + 40)
            w = df.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            bottom, top = frame["low"].iat[r], frame["open"].iat[r]
            stop = bottom - PAD * a[r]
            s = z.side
            lo_, hi_ = sorted((s * bottom, s * top))
            ax.fill_between([r - 0.4, f + 1], lo_, hi_, color="#457b9d", alpha=0.25)
            ax.hlines(s * stop, f, i1, colors="red", lw=1)
            ax.axvline(r, color="purple", lw=1, ls=":")
            ax.axvline(int(z.live), color="#999", lw=0.8, ls="--")
            ax.plot([f], [s * min(frame["open"].iat[f], top)], "k>", ms=9)
            ax.set_title(f"{z.sym}USDT {z.iv} {'long' if s > 0 else 'short'}  risk {z.risk_atr:.2f} ATR "
                         f"-> {z.E1:+.2f}R trail, {z.X2:+.2f}R at 2R  {pd.Timestamp(z.ts, unit='s'):%Y-%m-%d}", fontsize=9)
        fig.suptitle(f"counter-candle zones K3 ({tag}): purple dotted - the counter candle; blue - its zone (low to open); "
                     "grey dashed - live after leaving 1 ATR; black arrow - the fill on the first return; red - stop", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"candle_zones_{tag}.png", dpi=80)
        plt.close(fig)
    print("plots written", flush=True)


def main():
    {"run": run, "plot": plot}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
