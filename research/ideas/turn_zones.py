"""The origin of a violent turn, marked as a zone and traded on its first return.

Frozen in `turn_zone_rule.json` before this ran. `turning-points.md` found that violent turns are real
(beyond walks) but that entering at the turn trades like a walk. This asks whether the turn's origin
holds when price comes back to it: against the origin of an ordinary low, and against iid and GARCH
walks matched to each series.

  OUT=... MT5BT_DB=... MODE=run|plot python research/ideas/turn_zones.py
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

from turn_trade import COINS, FEE, MT5, SPLIT, _bin, boot, ups  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/turn_zones"))
SEC = {"1h": 3600, "4h": 14400, "1d": 86400}
RZ = {"1h": 3.109, "4h": 2.699, "1d": 2.022}  # violence.py's MT5 VIOLENT thresholds
WIDTH, STOP_PAD, SLIP = 0.5, 0.1, 0.05
RALLY = {"proven": 3.0, "left": 1.5}
LIVE_BARS = 60
NS = (0.5, 1, 2, 4, 10)
WALK_STEPS = 256
FAMILIES = ("ALL", "SIG", "RZ", "SIG_RZ")


def atr(df, n=14):
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def exits(o, h, l, c, f, top, stop, a_t, cost_atr_f, hold):
    """A limit buy at `top` filled on bar f, its stop at `stop`: E1 (the fill bar's stop, then a 2-ATR trail
    behind completed bars' best high), the most R it reached, and X2 (a fixed 2R target, on the fill bar
    only if it closes there). R against the nominal risk top - stop, net of cost."""
    n = len(c)
    risk = top - stop
    entry = min(o[f], top)
    cost = cost_atr_f / risk
    res = {}
    # E1: the fill bar's stop, then a 2-ATR trail behind completed bars' best high
    R, mfe, best, st = None, max(0.0, (c[f] - entry) / risk), max(entry, c[f]), stop
    if l[f] <= stop:
        R = (min(entry, stop) - SLIP * a_t - entry) / risk
    else:
        for j in range(f + 1, min(n, f + 1 + hold)):
            st = max(st, best - 2 * a_t)
            if l[j] <= st:
                R = (min(o[j], st) - SLIP * a_t - entry) / risk
                break
            best = max(best, h[j])
            mfe = max(mfe, (h[j] - entry) / risk)
        if R is None:
            R = (c[min(n - 1, f + hold)] - entry) / risk
    res["E1"], res["mfe"] = R - cost, mfe
    # X2: a fixed 2R target; on the fill bar only if it closes there
    tgt = entry + 2 * risk
    if l[f] <= stop:
        R = (min(entry, stop) - SLIP * a_t - entry) / risk
    elif c[f] >= tgt:
        R = 2.0
    else:
        R = None
        for j in range(f + 1, min(n, f + 1 + hold)):
            if l[j] <= stop:
                R = (min(o[j], stop) - SLIP * a_t - entry) / risk
                break
            if h[j] >= tgt:
                R = (max(o[j], tgt) - entry) / risk
                break
        if R is None:
            R = (c[min(n - 1, f + hold)] - entry) / risk
    res["X2"] = R - cost
    return res


def zones(df, side, cost_atr, src, sym, iv):
    """One row per (12-bar low, activation) that is returned to: the zone, its fill and both exits."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy()
    n = len(df)
    a = atr(df)
    low3 = pd.Series(l).rolling(3).min().to_numpy()
    prior = pd.Series(l).shift(3).rolling(9).min().to_numpy()
    rng_ = h - l
    rm = pd.Series(rng_).rolling(10).mean().shift(1).to_numpy()
    rs = pd.Series(rng_).rolling(10).std().shift(1).to_numpy()
    U = ups(df)
    ret_bars = int(20 * 86400 / SEC[iv])
    hold = max(1, int(10 * 86400 / SEC[iv]))
    rows = []
    for t in np.flatnonzero(low3 <= prior):
        if t < 30 or t + 2 >= n or not a[t] > 0:
            continue
        bottom = low3[t]
        top, stop = bottom + WIDTH * a[t], bottom - STOP_PAD * a[t]
        risk = top - stop
        sig = bool(U["DISPLACE_C"][t] or U["BREACH_REVERT"][t] or U["DELIVERY_SHIFT"][t])
        rz = bool(rs[t] > 0 and (rng_[t] - rm[t]) / rs[t] >= RZ[iv])
        for act, k in RALLY.items():
            live = None
            for j in range(t + 1, min(n, t + 1 + LIVE_BARS)):
                if l[j] < bottom:
                    break
                if h[j] >= bottom + k * a[t]:
                    live = j + 1
                    break
            if live is None or live >= n:
                continue
            f = next((j for j in range(live, min(n, live + ret_bars)) if l[j] <= top), None)
            if f is None:
                continue
            res = exits(o, h, l, c, f, top, stop, a[t], cost_atr[f] * a[f], hold)
            rows.append(dict(src=src, sym=sym, iv=iv, side=side, t=t, live=live, f=f, ts=int(ts[f]), act=act,
                             SIG=sig, RZ=rz, wait=f - live, **res))
    return rows


def load(venue, sym, iv):
    """The series and its cost per bar in price."""
    if venue == "binance":
        try:
            df = _bin(sym, iv)
        except OSError:
            return None, None
        return df, FEE * df["close"].to_numpy(float)
    import run as R
    from mt5bt import load_specs
    R.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, iv)
    if df is None:
        return None, None
    df = df.reset_index(drop=True)[["ts", "open", "high", "low", "close", "volume"]]
    spec = load_specs(R.DB).get(sym)
    return df, np.full(len(df), R.spread_floor(sym, spec) * spec.point if spec is not None else 0.0)


def one(job):
    from mcfl import synth
    from mcfl.parse import flip
    venue, sym, iv, source = job
    df, fee_px = load(venue, sym, iv)
    if df is None or len(df) < 200:
        return None
    cost_atr = fee_px / np.maximum(atr(df), 1e-12)  # the real series' cost, in ATR
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    if source != "real":
        ts, n = df["ts"].to_numpy(), len(df)
        sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
        seed = zlib.crc32(f"{venue}{sym}{iv}{source}".encode()) % 100000
        gen = synth.walk if source == "walk" else synth.garch
        df = gen(n, sigma=sigma, seed=seed, steps=WALK_STEPS).reset_index(drop=True).iloc[:n]
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
    jobs = [(v, s, iv, src) for src in ("real", "walk", "garch") for iv in SEC
            for v, syms in (("binance", COINS), ("mt5", MT5)) for s in syms]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 20))) as pool:
        got = [g for g in pool.map(one, jobs) if g is not None and len(g)]
    d = pd.concat(got, ignore_index=True)
    d.to_pickle(OUT / "turn_zones.pkl.gz")
    d["ALL"] = True
    d["SIG_RZ"] = d["SIG"] & d["RZ"]
    rng = np.random.default_rng(41)
    rows = []
    for (src, act), g in d.groupby(["src", "act"]):
        for fam in FAMILIES:
            x = g[g[fam]]
            for ex in ("E1", "X2"):
                y = x.assign(R=x[ex])
                lo, hi = boot(y, rng) if len(y) > 30 else (np.nan, np.nan)
                r = dict(src=src, act=act, family=fam, exit=ex, n=len(y), R=y["R"].mean(), lo=lo, hi=hi,
                         win=(y["R"] > 0).mean(), R_before=y.loc[y["ts"] < SPLIT, "R"].mean(),
                         R_after=y.loc[y["ts"] >= SPLIT, "R"].mean(),
                         **{f"R_{iv}": y.loc[y["iv"] == iv, "R"].mean() for iv in SEC})
                if ex == "E1":
                    r.update({f"P{N}R": (x["mfe"] >= N).mean() for N in NS})
                rows.append(r)
    t = pd.DataFrame(rows).round(3)
    t.to_csv(OUT / "turn_zones.csv", index=False)
    pd.set_option("display.width", 280)
    pd.set_option("display.max_rows", 300)
    print(t.to_string(index=False))
    print("1/(N+1):", {N: round(1 / (N + 1), 3) for N in NS})

    def cell(src, fam):
        return t[(t["src"] == src) & (t["act"] == "proven") & (t["family"] == fam) & (t["exit"] == "E1")].iloc[0]
    p, a = cell("binance:real", "SIG"), cell("binance:real", "ALL")
    w, gw = cell("binance:walk", "SIG"), cell("binance:garch", "SIG")
    ok = (p["R"] > 0 and p["lo"] > 0 and p["R_before"] > 0 and p["R_after"] > 0
          and p["R"] > a["R"] and p["R"] > w["R"] and p["R"] > gw["R"])
    print(f"\nPRIMARY (SIG, proven, E1, Binance): R {p['R']:+.3f} [{p['lo']:+.3f}, {p['hi']:+.3f}] n={p['n']}, "
          f"before {p['R_before']:+.3f}, after {p['R_after']:+.3f}; ALL {a['R']:+.3f}; walk {w['R']:+.3f}; "
          f"garch {gw['R']:+.3f} -> {'PASSES' if ok else 'fails'}")


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mcfl.parse import flip
    t = pd.read_csv(OUT / "turn_zones.csv")
    # P(N R) curves: proven E1, each family, real against both walks, per venue
    fig, axes = plt.subplots(2, 4, figsize=(22, 9), sharey=True)
    for i, venue in enumerate(("binance", "mt5")):
        for j, fam in enumerate(FAMILIES):
            ax = axes[i, j]
            for src, st in (("real", "-o"), ("walk", "--s"), ("garch", ":^")):
                r = t[(t["src"] == f"{venue}:{src}") & (t["act"] == "proven") & (t["family"] == fam) & (t["exit"] == "E1")]
                if len(r):
                    r = r.iloc[0]
                    ax.plot(NS, [r[f"P{N}R"] for N in NS], st, label=f"{src}  R {r['R']:+.3f} (n {int(r['n'])})")
            ax.plot(NS, [1 / (N + 1) for N in NS], color="grey", lw=0.8, label="1/(N+1)")
            ax.set_xscale("log")
            ax.set_title(f"{venue} {fam} (proven, trail)", fontsize=10)
            ax.legend(fontsize=7)
            ax.set_xlabel("N (R)")
    axes[0, 0].set_ylabel("P(trade reaches N R)")
    fig.suptitle("turn-origin zones, first return: P(N R) real vs iid and GARCH walks; mean R per trade in the legend")
    fig.tight_layout()
    fig.savefig(OUT / "turn_zones_pnr.png", dpi=80)
    plt.close(fig)
    # a gallery of real Binance SIG proven trades, winners and losers
    d = pd.read_pickle(OUT / "turn_zones.pkl.gz")
    d = d[(d["src"] == "binance:real") & d["SIG"] & (d["act"] == "proven") & (d["iv"] == "4h")]
    rng = np.random.default_rng(5)
    for tag, sub in (("winners", d[d["E1"] > 0]), ("losers", d[d["E1"] <= 0])):
        pick = sub.iloc[rng.choice(len(sub), min(6, len(sub)), replace=False)]
        fig, axes = plt.subplots(2, 3, figsize=(21, 10))
        for ax, (_, r) in zip(axes.flat, pick.iterrows(), strict=False):
            df = _bin(r.sym, r.iv)
            frame = df if r.side > 0 else flip(df)
            a = atr(frame)
            t0, f = int(r.t), int(r.f)
            i0, i1 = max(0, t0 - 25), min(len(df) - 1, f + 40)
            w = df.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            bottom = frame["low"].iloc[t0 - 2:t0 + 1].min()
            top, stop = bottom + WIDTH * a[t0], bottom - STOP_PAD * a[t0]
            s = r.side
            lo_, hi_ = sorted((s * bottom, s * top))
            ax.fill_between([t0 - 2, f + 1], lo_, hi_, color="#457b9d", alpha=0.25)
            ax.hlines(s * stop, f, i1, colors="red", lw=1)
            ax.axvline(t0, color="purple", lw=1, ls=":")
            ax.axvline(int(r.live), color="#999", lw=0.8, ls="--")
            ax.plot([f], [s * min(frame["open"].iat[f], top)], "k>", ms=9)
            ax.set_title(f"{r.sym}USDT {r.iv} {'long' if s > 0 else 'short'}  {'+RZ ' if r.RZ else ''}"
                         f"-> {r.E1:+.2f}R trail, {r.X2:+.2f}R at 2R  {pd.Timestamp(r.ts, unit='s'):%Y-%m-%d}", fontsize=9)
        fig.suptitle(f"turn-origin zones ({tag}): purple dotted - the violent turn bar; blue - the zone; grey dashed - "
                     "live after a 3-ATR rally; black arrow - the fill on the first return; red - stop", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"turn_zones_{tag}.png", dpi=80)
        plt.close(fig)
    print("plots written", flush=True)


def main():
    {"run": run, "plot": plot}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
