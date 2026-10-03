"""How violent must a turn be, and does the answer depend on the timeframe?

Pre-registered 2026-10-03, before any run. `turns.py` found that real turning points are violent -
forceful reversal bars mark major turns far more than ordinary lows, beyond matched walks - and the
turn-signature trade (`turn_trade.py`) used MCFL v1's fixed STRONG / EXTREMELY_LARGE cut-offs. This
measures violence per timeframe instead of assuming it.

  bars      every 12-bar low knowable at its bar (the lowest low of t-2..t at or below t-11..t-3), on
            the chart and the flipped chart (a 12-bar high, in the low's terms)
  label     major turn: price rallies 3 ATR before trading below that low within 60 bars (after
            the fact; only to group bars)
  force     at bar t, the turn's way, each known at t's close:
              body_atr   (close - open) / ATR(14)
              range_z    (high - low - mean of the last 10 ranges) / their sd
              move_k     max over k = 1..3 of (close - the lowest low of the last k bars) / (ATR sqrt k)
              eff3       net close change over 3 bars / summed |close changes|
              close_loc  (close - low) / (high - low)
  curves    P(major turn | force in decile d), deciles of the pooled real 12-bar lows per timeframe;
            the same on GARCH-free iid walks matched to each series, 256 sub-steps a bar
  VIOLENT   per timeframe and measure: the lowest decile from which the real-minus-walk excess stays
            at or above 80% of its largest value - reported as a threshold in the measure's own units
  data      MT5 (10 markets: FX, gold, indices, oil, BTC, ETH) on 15m (from 2024-07), 1h, 4h, 1d;
            Binance (12 perpetuals) on the same, from 2021 - each timeframe's threshold is set on
            MT5 and read again on Binance and in both halves of time

  OUT=... MT5BT_DB=... MODE=run|plot python research/ideas/violence.py
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

OUT = Path(os.environ.get("OUT", ".data/violence"))
BIN = Path(os.environ.get("BINANCE", os.path.expanduser("~/till_infinity/data/binance")))
COINS = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "TRX")
MT5 = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US SP 500", "US Tech 100", "Germany 40", "US Oil", "BTCUSD", "ETHUSD")
TFS = ("15m", "1h", "4h", "1d")
MEASURES = ("body_atr", "range_z", "move_k", "eff3", "close_loc")
RALLY, HORIZON, WALK_STEPS = 3.0, 60, 256


def atr(df, n=14):
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def table(df):
    """One row per 12-bar low of this chart: its force measures and whether it became a major turn."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy()
    a = atr(df)
    n = len(df)
    low3 = pd.Series(l).rolling(3).min().to_numpy()
    prior = pd.Series(l).shift(3).rolling(9).min().to_numpy()
    cand = np.flatnonzero((low3 <= prior) & (a > 0))
    cand = cand[(cand > 30) & (cand < n - 2)]
    rng_ = h - l
    rm = pd.Series(rng_).rolling(10).mean().shift(1).to_numpy()
    rs = pd.Series(rng_).rolling(10).std().shift(1).to_numpy()
    absd = np.r_[0.0, np.abs(np.diff(c))]
    rows = []
    for t in cand:
        lo = low3[t]
        major = False
        target = lo + RALLY * a[t]
        for k in range(t + 1, min(n, t + HORIZON)):
            if l[k] < lo:
                break
            if h[k] >= target:
                major = True
                break
        mk = max((c[t] - l[t - k + 1:t + 1].min()) / (a[t] * np.sqrt(k)) for k in (1, 2, 3))
        rows.append(dict(t=t, ts=int(ts[t]), major=major, body_atr=(c[t] - o[t]) / a[t],
                         range_z=(rng_[t] - rm[t]) / rs[t] if rs[t] > 0 else np.nan, move_k=mk,
                         eff3=(c[t] - c[t - 3]) / max(absd[t - 2:t + 1].sum(), 1e-12),
                         close_loc=(c[t] - l[t]) / max(h[t] - l[t], 1e-12)))
    return pd.DataFrame(rows)


def load(venue, sym, tf):
    if venue == "binance":
        z = np.load(BIN / f"{sym}USDT.klines.{tf}.npz")
        d = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close")}).rename(columns={"time": "ts"})
        return d.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    d = R.load(sym, tf)
    return None if d is None else d.reset_index(drop=True)[["ts", "open", "high", "low", "close"]]


def one(job):
    from mcfl import synth
    venue, sym, tf, source = job
    try:
        df = load(venue, sym, tf)
    except OSError:
        return None
    if df is None or len(df) < 300:
        return None
    if source == "walk":
        ts = df["ts"].to_numpy()
        df = synth.matched_walk(df, seed=zlib.crc32(f"v{venue}{sym}{tf}".encode()) % 100000, steps=WALK_STEPS)
        df = df.reset_index(drop=True)
        df["ts"] = ts[:len(df)]
    flip = df.assign(open=-df["open"], close=-df["close"], high=-df["low"], low=-df["high"])
    out = pd.concat([table(df).assign(side=1), table(flip).assign(side=-1)], ignore_index=True)
    print(f"  {venue} {source} {sym} {tf}: {len(out)} lows, {int(out['major'].sum())} major", flush=True)
    return out.assign(venue=venue, sym=sym, tf=tf, source=source)


def curves(d, edges_by):
    """P(major) by decile of each measure (edges from the pooled real lows of the same venue and tf)."""
    rows = []
    for (venue, tf), g in d.groupby(["venue", "tf"]):
        for m in MEASURES:
            edges = edges_by[(venue, tf, m)]
            for src, x in g.groupby("source"):
                b = np.searchsorted(edges, x[m].to_numpy(), side="right")
                p = pd.Series(x["major"].to_numpy(float)).groupby(b).agg(["mean", "size"])
                for dec, r in p.iterrows():
                    rows.append(dict(venue=venue, tf=tf, measure=m, source=src, decile=int(dec), p=r["mean"], n=int(r["size"])))
    return pd.DataFrame(rows)


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("mt5", s, tf, src) for src in ("real", "walk") for tf in TFS for s in MT5] + \
           [("binance", s, tf, src) for src in ("real", "walk") for tf in TFS for s in COINS]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 24))) as pool:
        got = [g for g in pool.map(one, jobs) if g is not None and len(g)]
    d = pd.concat(got, ignore_index=True)
    d.to_pickle(OUT / "violence.pkl.gz")
    edges_by = {}
    for (venue, tf), g in d[d["source"] == "real"].groupby(["venue", "tf"]):
        for m in MEASURES:
            edges_by[(venue, tf, m)] = np.nanquantile(g[m], np.linspace(0.1, 0.9, 9))
    cv = curves(d, edges_by)
    cv.to_csv(OUT / "curves.csv", index=False)
    piv = cv.pivot_table(index=["venue", "tf", "measure", "decile"], columns="source", values="p")
    piv["excess"] = piv["real"] - piv["walk"]
    rows = []
    for (venue, tf, m), g in piv.groupby(level=[0, 1, 2]):
        ex = g["excess"].to_numpy()
        top = np.nanmax(ex)
        dec = g.index.get_level_values(3).to_numpy()
        ok = ex >= 0.8 * top
        # the lowest decile from which the excess stays at or above 80% of its largest value
        start = next((i for i in range(len(ex)) if ok[i:].all()), len(ex) - 1)
        d_star = dec[start]
        edges = edges_by[(venue, tf, m)]
        thr = edges[d_star - 1] if d_star >= 1 else -np.inf
        rows.append(dict(venue=venue, tf=tf, measure=m, violent_from_decile=int(d_star), threshold=thr,
                         p_real_above=g["real"].to_numpy()[start:].mean(), p_walk_above=g["walk"].to_numpy()[start:].mean(),
                         excess_max=top, p_real_bottom=g["real"].to_numpy()[0], p_walk_bottom=g["walk"].to_numpy()[0]))
    th = pd.DataFrame(rows).round(3)
    th.to_csv(OUT / "violent_thresholds.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 100)
    print(th.to_string(index=False))
    # MT5 thresholds read on Binance, and on each half of time
    rows = []
    mid = pd.Timestamp("2024-01-01", tz="UTC").timestamp()
    for tf in TFS:
        for m in MEASURES:
            r = th[(th["venue"] == "mt5") & (th["tf"] == tf) & (th["measure"] == m)]
            if r.empty:
                continue
            thr = float(r["threshold"].iloc[0])
            for venue in ("mt5", "binance"):
                for src in ("real", "walk"):
                    x = d[(d["venue"] == venue) & (d["tf"] == tf) & (d["source"] == src)]
                    if x.empty:
                        continue
                    v = x[m] >= thr
                    rows.append(dict(tf=tf, measure=m, threshold=round(thr, 3), venue=venue, source=src,
                                     share=v.mean(), p_violent=x.loc[v, "major"].mean(), p_rest=x.loc[~v, "major"].mean(),
                                     p_violent_first=x.loc[v & (x["ts"] < mid), "major"].mean(),
                                     p_violent_second=x.loc[v & (x["ts"] >= mid), "major"].mean()))
    chk = pd.DataFrame(rows).round(3)
    chk.to_csv(OUT / "violent_check.csv", index=False)
    print("\nMT5 thresholds, read again on Binance and by half (P(major) above vs below the threshold):")
    print(chk.to_string(index=False))


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cv = pd.read_csv(OUT / "curves.csv")
    th = pd.read_csv(OUT / "violent_thresholds.csv")
    for venue in ("mt5", "binance"):
        fig, axes = plt.subplots(len(MEASURES), len(TFS), figsize=(20, 3.2 * len(MEASURES)), squeeze=False)
        for i, m in enumerate(MEASURES):
            for j, tf in enumerate(TFS):
                ax = axes[i, j]
                g = cv[(cv["venue"] == venue) & (cv["tf"] == tf) & (cv["measure"] == m)]
                for src, style in (("real", "-o"), ("walk", "--s")):
                    x = g[g["source"] == src].sort_values("decile")
                    ax.plot(x["decile"] + 1, x["p"], style, label=src, ms=3)
                r = th[(th["venue"] == venue) & (th["tf"] == tf) & (th["measure"] == m)]
                if len(r):
                    ax.axvline(int(r["violent_from_decile"].iloc[0]) + 1, color="purple", ls=":", lw=1)
                    ax.set_title(f"{tf} {m}  VIOLENT >= {r['threshold'].iloc[0]:.2f}", fontsize=9)
                ax.set_xticks(range(1, 11))
                if i == len(MEASURES) - 1:
                    ax.set_xlabel("force decile (1 weakest .. 10 most violent)", fontsize=8)
                if j == 0:
                    ax.set_ylabel("P(major turn)", fontsize=8)
        axes[0, 0].legend(fontsize=7)
        fig.suptitle(f"{venue}: P(a 12-bar low becomes a major turn) by force decile at the low's bar - real (solid) vs "
                     "matched walk (dashed); purple: where VIOLENT starts", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"violence_curves_{venue}.png", dpi=75)
        plt.close(fig)
    # example violent turns per timeframe (MT5 real, move_k above its threshold, major)
    d = pd.read_pickle(OUT / "violence.pkl.gz")
    rng = np.random.default_rng(8)
    fig, axes = plt.subplots(2, len(TFS), figsize=(22, 9))
    for j, tf in enumerate(TFS):
        r = th[(th["venue"] == "mt5") & (th["tf"] == tf) & (th["measure"] == "move_k")]
        if r.empty:
            continue
        thr = float(r["threshold"].iloc[0])
        x = d[(d["venue"] == "mt5") & (d["tf"] == tf) & (d["source"] == "real") & (d["move_k"] >= thr)]
        for row_i, (label, sub) in enumerate((("became a major turn", x[x["major"]]), ("did not", x[~x["major"]]))):
            if sub.empty:
                continue
            e = sub.iloc[rng.integers(len(sub))]
            df = load("mt5", e["sym"], tf)
            if e["side"] < 0:
                df = df.assign(open=-df["open"], close=-df["close"], high=-df["low"], low=-df["high"])
            t = int(e["t"])
            w = df.iloc[max(0, t - 30):t + 40]
            xs = np.arange(len(w))
            up = (w["close"] >= w["open"]).to_numpy()
            ax = axes[row_i, j]
            ax.vlines(xs, w["low"], w["high"], color="#555", lw=0.6)
            ax.bar(xs[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(xs[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            ax.axvline(t - max(0, t - 30), color="purple", ls=":")
            ax.set_title(f"{e['sym']} {tf} {'low' if e['side'] > 0 else 'high (flipped)'} - {label}; "
                         f"move {e['move_k']:.2f} >= {thr:.2f}", fontsize=8)
    fig.suptitle("violent reversals at a 12-bar extreme, per timeframe (top: became a major turn, bottom: did not); "
                 "shorts drawn flipped", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "violence_examples.png", dpi=75)
    plt.close(fig)
    print("plots written", flush=True)


def main():
    {"run": run, "plot": plot}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
