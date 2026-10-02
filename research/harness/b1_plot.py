"""B1, drawn: the expansion-alert straddle's trades on the chart, and its net profit.

Re-runs two of the tested versions exactly as `energy.py` builds them, on the same held-out alert
rows (`OUT/test_predictions.csv`, lift >= 2.5), keeping the trades this time:

  B1        the original (expansion.md): a buy stop over and a sell stop under the 16-bar box,
            resting 16 bars, one cancels the other; stop at the opposite edge; no target; out
            after 16 bars
  B_trail   Part G's best-shaped version: the same bracket, then a stop trailing 2 sigma behind
            the best completed bar; 96 bars at most

Then for a few markets, four trades each with the box, both resting orders, the fill, the stop and
the exit; and each version's cumulative R, net of spread and swap, by the exit time.

  OUT=.../expansion SEQLAB=... MT5BT_DB=... PLOTS=... python research/harness/b1_plot.py
"""
from __future__ import annotations

import os
import sys
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import energy as E  # noqa: E402

PLOTS = Path(os.environ.get("PLOTS", ".data/b1_plots"))
VERSIONS = {"B1": dict(trail_k=0.0, hold=E.BOX), "B_trail": dict(trail_k=2.0, hold=E.MAXHOLD)}
SHOW = ("EURUSD|1h", "XAUUSD|1h", "GBPUSD|15m", "BTCUSD|1h", "USDJPY|15m", "Volatility_75_Index|1h")


def main():
    from mt5bt import Book, Costs, load_bars, load_specs, run
    pred = pd.read_csv(E.OUT / "test_predictions.csv")
    pred = pred[pred["test"] & pred["kind"].isin(["real", "deriv"])]
    wf = __import__("json").loads((E.OUT / "expansion_wf.json").read_text())
    if "lift" not in pred:
        pred["lift"] = pred["p"] / wf["base_rate"]
    specs = load_specs(os.environ.get("MT5BT_DB"))
    trades = {v: [] for v in VERSIONS}
    keep = {}
    for key, g in pred.groupby("key"):
        sym, iv = key.split("|")
        spec = E.spec_for(specs, sym)
        if spec is None:
            continue
        bars = load_bars(sym, iv, "seqlab", E.SEQLAB)
        book = Book(key, bars, spec, iv, feed=sym.replace("_", " ").lower(), meta={"family": g["family"].iloc[0]})
        st = E.state(book.bars)
        ts = book.bars["ts"].to_numpy()
        idx = np.searchsorted(ts, (g["when"].to_numpy() - E.SECONDS[iv]).astype(np.int64))
        ok = (idx < len(ts)) & (ts[np.minimum(idx, len(ts) - 1)] == g["when"].to_numpy() - E.SECONDS[iv])
        idx, lift = idx[ok], g["lift"].to_numpy()[ok]
        arms = idx[lift >= 2.5]
        for name, v in VERSIONS.items():
            sig = E.orders(book.bars, st, arms, two_sided=True, buffer=0.0, trail_k=max(v["trail_k"], 1e-9),
                           confirm=False)
            if sig.empty:
                continue
            if v["trail_k"] == 0.0:
                sig["trail"] = 0.0
            sig["hold"] = v["hold"]
            t, _ = run(book, None, Costs(), equity=1e7, risk=0.001, one_per_symbol=False, signals={key: sig})
            if len(t):
                trades[name].append(t.assign(key=key, family=book.meta["family"], interval=iv))
                if key in SHOW:
                    keep.setdefault(key, (book, sig))
                    keep[key + "|" + name] = (book, sig, t)
        print(f"  {key}: {len(arms)} alerts", flush=True)
    PLOTS.mkdir(parents=True, exist_ok=True)
    tt = {k: pd.concat(v, ignore_index=True) for k, v in trades.items() if v}
    pd.to_pickle(tt, PLOTS / "b1_trades.pkl.gz")
    for k, t in tt.items():
        print(f"{k}: n {len(t)}, mean R {t['R'].mean():+.4f}, net R total {t['R'].sum():+.1f}, "
              f"win {(t['R'] > 0).mean():.3f}, P(R>=4) {(t['R'] >= 4).mean():.3f}", flush=True)
    draw(keep, tt)


def draw(keep, tt):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    # net profit, both versions, real markets and Deriv apart
    fig, ax = plt.subplots(1, 2, figsize=(16, 5))
    for n_, fam in enumerate(("real", "deriv")):
        for k, t in tt.items():
            x = t[(t["family"] == "deriv") == (fam == "deriv")].sort_values("exit_ts")
            if len(x):
                ax[n_].plot(pd.to_datetime(x["exit_ts"], unit="s"), x["R"].cumsum().to_numpy(),
                            label=f"{k}: {len(x)} trades, {x['R'].mean():+.3f}R each")
        ax[n_].axhline(0, color="k", lw=0.6)
        ax[n_].set_title(f"cumulative R, net of spread and swap - {'Deriv' if fam == 'deriv' else 'real markets'}")
        ax[n_].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(PLOTS / "b1_net_R.png", dpi=80)
    plt.close(fig)

    for key in SHOW:
        for name in VERSIONS:
            got = keep.get(key + "|" + name)
            if got is None:
                continue
            book, sig, t = got
            b = book.bars.reset_index(drop=True)
            rng = np.random.default_rng(zlib.crc32((key + name).encode()))
            pick = t.iloc[np.sort(rng.choice(len(t), min(4, len(t)), replace=False))]
            fig, axes = plt.subplots(2, 2, figsize=(18, 11))
            ts = b["ts"].to_numpy()
            for ax, (_, tr) in zip(axes.flat, pick.iterrows(), strict=False):
                i = int(tr["signal_bar"])
                e = int(np.searchsorted(ts, tr["entry_ts"]))
                x_ = int(min(len(b) - 1, np.searchsorted(ts, tr["exit_ts"]) ))
                i0, i1 = max(0, i - E.BOX - 10), min(len(b) - 1, x_ + 15)
                w = b.iloc[i0:i1 + 1]
                xs = np.arange(i0, i1 + 1)
                up = (w["close"] >= w["open"]).to_numpy()
                ax.vlines(xs, w["low"], w["high"], color="#555", lw=0.6)
                ax.bar(xs[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
                ax.bar(xs[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
                hi, lo = b["high"].iloc[i - E.BOX + 1:i + 1].max(), b["low"].iloc[i - E.BOX + 1:i + 1].min()
                ax.add_patch(Rectangle((i - E.BOX + 0.5, lo), E.BOX, hi - lo, color="#457b9d", alpha=0.2))
                ax.axvline(i, color="purple", lw=1, ls=":")
                ax.annotate("alert", (i, hi), color="purple", fontsize=8)
                both = sig[sig["i"] == i]
                for _, o in both.iterrows():
                    ax.hlines(o["entry"], i, i + E.BOX, colors="green" if o["side"] > 0 else "red",
                              linestyles="--", lw=1)
                ax.scatter([e], [tr["entry"]], marker="^" if tr["side"] > 0 else "v", s=120,
                           color="green" if tr["side"] > 0 else "red", zorder=5)
                ax.hlines(tr["entry"] - tr["side"] * tr["stop_d"], e, x_, colors="red", lw=1)
                ax.scatter([x_], [tr["exit"]], marker="x", s=100, color="k", zorder=5)
                ax.set_title(f"{key} {name} {'long' if tr['side'] > 0 else 'short'}  R {tr['R']:+.2f}  "
                             f"exit: {tr['reason']}  {pd.Timestamp(ts[i], unit='s'):%Y-%m-%d %H:%M}", fontsize=10)
            fig.suptitle("blue: the 16-bar box  purple: the alert  dashed: buy stop over / sell stop under (16 bars, "
                         "one cancels the other)  triangle: the fill  red: the stop  x: the exit", fontsize=11)
            fig.tight_layout()
            fig.savefig(PLOTS / f"b1_{key.replace('|', '_').replace(' ', '_')}_{name}.png", dpi=80)
            plt.close(fig)


if __name__ == "__main__":
    main()
