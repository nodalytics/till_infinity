"""Figures for boomcrash-trend.md. Real data in blue, the fitted constant-hazard null in grey bands,
the positive control and second series in orange, a third in aqua."""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import boomcrash_agg as A  # noqa: E402
import boomcrash_trend as B  # noqa: E402

IMG = Path(os.environ.get("IMG", B.OUT / "img"))
BLUE, ORANGE, AQUA, GREY, INK, MUTED = "#2a78d6", "#eb6834", "#1baf7a", "#b9b8b0", "#1f1f1e", "#6b6a64"
plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
                     "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e6e5df", "grid.linewidth": 0.6, "figure.dpi": 130})
TFS = list(B.TFS)


def save(fig, name):
    IMG.mkdir(parents=True, exist_ok=True)
    fig.savefig(IMG / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  plot", name, flush=True)


def fig_primary(rep):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4))
    for ax, key in zip(axes, ("P1", "P2")):
        P = rep[key]
        nv = np.array([x for x in P["null_conf"] if np.isfinite(x)])
        ax.hist(nv, bins=15, color=GREY, edgecolor="white", label=f"fitted null, {len(nv)} paths")
        ax.axvline(P["real_conf"], color=BLUE, lw=2, label=f"real {P['real_conf']:.3f}")
        lo, hi = P["ci90"]
        ax.axvspan(lo, hi, color=BLUE, alpha=0.12, label=f"real 90% day-bootstrap [{lo:.3f}, {hi:.3f}]")
        for i, c in enumerate(P["ctrl_conf"]):
            ax.axvline(c, color=ORANGE, lw=1.2, ls="--", label="positive control (1.25x)" if i == 0 else None)
        ax.axvline(1.0, color=INK, lw=0.6)
        ax.set_title(f"{key}: {P['label']}\nconfirmation, six indices pooled, z = {P['z']:+.2f}", fontsize=9)
        ax.set_xlabel("spike hazard ratio")
        ax.legend(fontsize=7, frameon=False)
    save(fig, "primary.png")


def per_index_ratio(R, nulls, var, num, den, kind="rate"):
    fn = A.ratio_rate if kind == "rate" else A.ratio_size
    out = {}
    for sl in R:
        r = fn(R[sl].agg[var][1], num, den)
        nv = np.array([fn(n.agg[var][1], num, den) for n in nulls[sl]])
        nv = nv[np.isfinite(nv)]
        out[sl] = (r, np.quantile(nv, [0.05, 0.5, 0.95]) if len(nv) else [np.nan] * 3)
    return out


def fig_forest(R, nulls, kind="rate", name="forest.png", what="spike hazard ratio, aligned / counter"):
    fig, axes = plt.subplots(2, 3, figsize=(11, 5.6), sharey=True)
    x = np.arange(len(TFS))
    for ax, sl in zip(axes.ravel(), R):
        vals, bands = [], []
        for tf in TFS:
            d = per_index_ratio({sl: R[sl]}, {sl: nulls[sl]}, f"{tf}|full|dir", [0], [1], kind)[sl]
            vals.append(d[0]), bands.append(d[1])
        bands = np.array(bands)
        ax.fill_between(x, bands[:, 0], bands[:, 2], color=GREY, alpha=0.6, lw=0, label="null 5-95%")
        ax.plot(x, bands[:, 1], color=MUTED, lw=1)
        ax.plot(x, vals, "o", color=BLUE, ms=6, label="real, confirmation")
        ax.axhline(1, color=INK, lw=0.6)
        ax.set_xticks(x, TFS)
        ax.set_title(A.PRETTY[sl], fontsize=9)
    axes[0, 0].legend(fontsize=7, frameon=False)
    axes[0, 0].set_ylabel(what)
    axes[1, 0].set_ylabel(what)
    fig.suptitle(f"Full-series LRC(100) trend of the last closed bar: {what}", fontsize=10)
    save(fig, name)


def fig_mtf(rep):
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
    cc = rep["count_curve"]
    x = np.arange(7)
    nv = np.array(cc["null"], float)
    ax = axes[0]
    ax.fill_between(x, np.nanquantile(nv, 0.05, 0), np.nanquantile(nv, 0.95, 0), color=GREY, alpha=0.6, lw=0, label="null 5-95%")
    ax.plot(x, cc["real"], "o-", color=BLUE, lw=2, ms=6, label="real, confirmation")
    ax.axhline(1, color=INK, lw=0.6)
    for i, s in enumerate(cc["share"]):
        ax.annotate(f"{100 * s:.0f}%", (i, 0), xycoords=("data", "axes fraction"), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=7, color=MUTED)
    ax.set_xlabel("aligned timeframes of six (share of time at the foot)")
    ax.set_ylabel("spike hazard, observed / expected")
    ax.set_title("Alignment count, six indices pooled", fontsize=9)
    ax.legend(fontsize=7, frameon=False)
    ax = axes[1]
    labels = ["both\naligned", "HTF aligned\nLTF counter", "HTF counter\nLTF aligned", "both\ncounter"]
    keys = list(rep["nested"])
    w = 0.8 / len(keys)
    for j, k in enumerate(keys):
        d = rep["nested"][k]
        nv = np.array(d["null"], float)
        xs = np.arange(4) + (j - len(keys) / 2 + 0.5) * w
        ax.vlines(xs, np.nanquantile(nv, 0.05, 0), np.nanquantile(nv, 0.95, 0), color=GREY, lw=3)
        ax.plot(xs, d["real"], "o", color=BLUE if k != "4h/15m" else ORANGE, ms=3.5 if k != "4h/15m" else 6,
                label="4h / 15m (P2)" if k == "4h/15m" else ("other HTF / LTF pairs" if j == 0 else None))
    ax.axhline(1, color=INK, lw=0.6)
    ax.set_xticks(np.arange(4), labels)
    ax.set_title("Nested states, nine HTF/LTF pairs (grey: null 5-95%)", fontsize=9)
    ax.legend(fontsize=7, frameon=False)
    save(fig, "mtf.png")


def fig_cluster(rep, real, nulls):
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
    ax = axes[0]
    cols = [BLUE, ORANGE, AQUA, "#e87ba4", "#eda100", "#008300"]
    for c, sl in zip(cols, real):
        i = real[sl]["spikes"]["i"]
        g = np.diff(i).astype(float)
        m = g.mean()
        xs = np.linspace(0, 6 * m, 60)
        surv = [(g > v).mean() for v in xs]
        ax.semilogy(xs / m, surv, color=c, lw=1.6, label=A.PRETTY[sl])
    xs = np.linspace(0, 6, 60)
    ax.semilogy(xs, np.exp(-xs), color=INK, lw=1, ls="--", label="memoryless (geometric)")
    ax.set_xlabel("gap between spikes, in units of the mean gap (ticks)")
    ax.set_ylabel("share of gaps longer")
    ax.set_title("Inter-arrival survival, all ticks", fontsize=9)
    ax.legend(fontsize=7, frameon=False)
    ax = axes[1]
    keys = ["cv", "fano_15m", "fano_1h", "fano_1d"]
    for j, sl in enumerate(real):
        for k, key in enumerate(keys):
            nv = np.array([n.res["clu"][1][key] for n in nulls[sl]])
            xx = k + (j - 2.5) * 0.12
            ax.vlines(xx, np.quantile(nv, 0.05), np.quantile(nv, 0.95), color=GREY, lw=3)
            ax.plot(xx, real[sl]["clu"][1][key], "o", color=cols[j], ms=4)
    ax.axhline(1, color=INK, lw=0.6)
    ax.set_xticks(range(4), ["gap CV", "dispersion 15m", "dispersion 1h", "dispersion 1d"])
    ax.set_title("Clustering, confirmation: real (dots) against the null (grey 5-95%)", fontsize=9)
    save(fig, "cluster.png")


def fig_mech(rep):
    fig, ax = plt.subplots(figsize=(7, 3.4))
    x = np.arange(len(TFS))
    for key, col, lab in (("causal", BLUE, "last CLOSED bar (the study)"), ("noncausal", ORANGE, "bar CONTAINING the minute (look-ahead)")):
        nv = np.array([rep["mech"][tf][f"null_{key}"] for tf in TFS], float)
        ax.fill_between(x, np.nanquantile(nv, 0.05, 1), np.nanquantile(nv, 0.95, 1), color=col, alpha=0.15, lw=0)
        ax.plot(x, [rep["mech"][tf][key] for tf in TFS], "o-", color=col, lw=1.8, label=f"{lab}: real; band = null")
    ax.axhline(1, color=INK, lw=0.6)
    ax.set_xticks(x, TFS)
    ax.set_ylabel("aligned / counter hazard, pooled")
    ax.set_title("Causal reading (the study) against a look-ahead reading that contains the spike", fontsize=9)
    ax.legend(fontsize=7, frameon=False)
    save(fig, "mechanical.png")


def fig_trade(rep):
    P = rep["trades_pooled"]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    Ns = list(A.NS)
    ax.plot(Ns, [1 / (n + 1) for n in Ns], color=INK, ls="--", lw=1, label="1/(N+1)")
    for v, col in (("T-all", BLUE), ("T-with", ORANGE), ("T-against", AQUA)):
        if v not in P[1]:
            continue
        ax.plot(Ns, [P[1][v][f"p{n}"] for n in Ns], "o-", color=col, lw=1.8, label=f"{v} real (net mean {P[1][v]['net']:+.3f}R)")
        ax.plot(Ns, [P["null"][1][v][f"p{n}"] for n in Ns], "x:", color=col, lw=1, label=f"{v} fitted null")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks(Ns, [str(n) for n in Ns])
    ax.set_xlabel("N")
    ax.set_ylabel("P(R >= N), net of spread and swap")
    ax.set_title("Catching the spike: long Boom / short Crash at each 15m close, confirmation, pooled", fontsize=9)
    ax.legend(fontsize=7, frameon=False)
    save(fig, "trade.png")


def fig_example():
    """Boom 1000 and Crash 1000, three days of 1m bars: the full series and the ex-spike series."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4))
    for ax, sl in zip(axes, ("boom_1000", "crash_1000")):
        cache = B.OUT / "cache" / sl
        ms = np.load(cache / "ms.npy", mmap_mode="r")
        bid = np.load(cache / "bid.npy", mmap_mode="r")
        a = int(np.searchsorted(ms, (int(ms[-1]) // 86400000 - 10) * 86400000))
        b = int(np.searchsorted(ms, (int(ms[-1]) // 86400000 - 7) * 86400000))
        m, x = np.asarray(ms[a:b]), np.asarray(bid[a:b])
        s = B.side(sl)
        theta = A.load(cache / "null.pkl")["theta"]
        first, last, J, ex, _, _ = B.detect(m, x, s, theta)
        T, o, h, l, c, _, _ = B.minute_bars(m, x)
        _, _, _, _, ec, _, _ = B.minute_bars(m, ex)
        hours = (T - T[0]) / 3600
        ax.plot(hours, c, color=BLUE, lw=1, label="bid (full series)")
        ax.plot(hours, ec + (c[0] - ec[0]), color=ORANGE, lw=1.2, label="ex-spike (the grind alone)")
        ax.set_title(f"{A.PRETTY[sl]}: three days of 1m closes, {len(first)} spikes", fontsize=9)
        ax.set_xlabel("hours")
        ax.legend(fontsize=7, frameon=False)
    save(fig, "example.png")


def main(rep, real, R, nulls):
    fig_primary(rep)
    fig_forest(R, nulls)
    fig_forest(R, nulls, "size", "size.png", "mean spike size ratio, aligned / counter")
    fig_mtf(rep)
    fig_cluster(rep, real, nulls)
    fig_mech(rep)
    fig_trade(rep)
    fig_example()
