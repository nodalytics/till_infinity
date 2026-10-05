"""Figures for `strategy-switching.md`, from the tables `switch.py` writes.

  IN=<dir with switch.py's csv / pickles> LIVE=<dir with live.csv, live_traces.pkl> \
  IMG=research/docs/img/switching python research/ideas/switch_plot.py
"""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

IN = Path(os.environ.get("IN", ".data/switch"))
LIVE = Path(os.environ.get("LIVE", str(IN)))
IMG = Path(os.environ.get("IMG", "research/docs/img/switching"))
SRC_C = {"real": "#2a78d6", "walk": "#eb6834", "garch": "#1baf7a"}
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
RULES = ("EQ20", "EQ50", "DD", "CUSUM", "PH", "SPRT", "BAYES_ALL", "BAYES_100", "REGIME_VOL", "REGIME_TREND")
CLASSES = ("FX", "METAL", "INDEX", "ENERGY", "CRYPTO_CFD", "BINANCE", "FRESH", "DERIV_1S", "DERIV_DIFFUSIVE",
           "DERIV_JUMPY")
NS = (0.5, 1, 2, 4, 10)

plt.rcParams.update({"figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "text.color": INK, "axes.grid": True,
                     "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
                     "font.size": 9, "axes.titlesize": 10, "legend.frameon": False, "lines.linewidth": 2})


def save(fig, name):
    IMG.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(IMG / name, dpi=110)
    plt.close(fig)
    print("wrote", IMG / name)


def nec_plot():
    pt = pd.read_csv(IN / "nec_pooled.csv")
    pt = pt[(pt["half"] == "conf")]
    groups = ["PROD BOOK, all strategies", "PROD CELL, all non-RB cells", "LRC, all non-RB cells"]
    groups += [f"PROD {c}" for c in CLASSES]
    groups += [f"LRC all non-RB {iv}" for iv in ("15m", "1h", "4h", "1d")]
    groups += [f"LRC {c} {iv}" for c in CLASSES for iv in ("15m", "1h", "4h", "1d")]
    pt = pt.set_index("group")
    groups = [g for g in groups if g in pt.index]
    fig, ax = plt.subplots(figsize=(8, max(4, 0.2 * len(groups) + 1)))
    y = np.arange(len(groups))[::-1]
    for k, src in enumerate(("real", "walk", "garch")):
        if src not in pt:
            continue
        v = pt.loc[groups, src].to_numpy(float)
        lo = pt.loc[groups, f"{src}_lo"].to_numpy(float)
        hi = pt.loc[groups, f"{src}_hi"].to_numpy(float)
        yy = y + (k - 1) * 0.25
        ax.errorbar(v, yy, xerr=[v - lo, hi - v], fmt="o", ms=3.5, color=SRC_C[src], elinewidth=1, label=src)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(groups, fontsize=6.5)
    ax.set_xlabel("pred_30: correlation of a trade's R with the mean R of the 30 trades closed before it (confirmation, 90% day-bootstrap)")
    ax.legend(loc="lower right")
    ax.set_title("Is a strategy's next R predictable from its own recent record? Real against matched walks")
    save(fig, "nec_pred30.png")
    cells = pd.read_csv(IN / "nec_cells.csv")
    cells = cells[(cells["half"] == "conf") & (cells["scope"] == "CELL") & (cells["cls"] != "RANGE_BREAK")]
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.3))
    for ax, col, lab in zip(axes, ("pred_30", "ac1", "runs_z", "month_pers"),
                            ("pred_30", "lag-1 autocorrelation", "runs z (negative = streaky)",
                             "month-to-month persistence"), strict=True):
        bins = np.linspace(np.nanquantile(cells[col], 0.01), np.nanquantile(cells[col], 0.99), 40)
        for src in ("real", "walk", "garch"):
            x = cells[cells["src"] == src][col].dropna()
            ax.hist(x, bins=bins, histtype="step", color=SRC_C[src], lw=1.6, density=True,
                    label=f"{src} med {x.median():+.3f}")
        ax.set_title(lab)
        ax.legend(fontsize=7)
    fig.suptitle("Per-cell serial-dependence statistics, confirmation (every strategy x class x timeframe cell with >= 100 trades)")
    save(fig, "nec_cells.png")


def rules_plot():
    pt = pd.read_csv(IN / "rules_pooled.csv")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, pool in zip(axes, ("PROD BOOK", "LRC CELL"), strict=True):
        sub = pt[pt["pool"] == pool]
        y = np.arange(len(RULES))[::-1]
        for k, (src, half, lab) in enumerate((("real", "conf", "real, confirmation"), ("real", "disc", "real, discovery"),
                                              ("walk", "conf", "iid walk, confirmation"),
                                              ("garch", "conf", "GARCH walk, confirmation"))):
            v, lo, hi, yy = [], [], [], []
            for i, r in enumerate(RULES):
                row = sub[(sub["rule"] == r) & (sub["half"] == half)]
                if not len(row) or f"{src}_timing" not in row:
                    continue
                row = row.iloc[0]
                v.append(row[f"{src}_timing"])
                lo.append(row[f"{src}_t_lo"])
                hi.append(row[f"{src}_t_hi"])
                yy.append(y[i] + (1.5 - k) * 0.18)
            v, lo, hi = (np.array(a, float) for a in (v, lo, hi))
            col = SRC_C[src] if half == "conf" else "#4a3aa7"
            ax.errorbar(v, yy, xerr=[np.nan_to_num(v - lo), np.nan_to_num(hi - v)], fmt="o", ms=3.5, color=col,
                        elinewidth=1, label=lab)
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_yticks(y)
        ax.set_yticklabels(RULES)
        ax.set_title(f"{pool}: timing value, R per opportunity")
        ax.set_xlabel("switched minus random-pause twin (90% day-bootstrap)")
    axes[0].legend(fontsize=7, loc="lower left")
    save(fig, "rules_timing.png")
    # by class heat table
    for fam in ("PROD", "LRC"):
        rows = [f"{fam} {c}" for c in CLASSES + ("RANGE_BREAK",)]
        if fam == "LRC":
            rows += [f"LRC {iv}" for iv in ("15m", "1h", "4h", "1d")]
        M = np.full((len(rows), len(RULES)), np.nan)
        S = np.zeros_like(M, bool)
        for i, p in enumerate(rows):
            for j, r in enumerate(RULES):
                row = pt[(pt["pool"] == p) & (pt["rule"] == r) & (pt["half"] == "conf")]
                if len(row):
                    M[i, j] = row.iloc[0]["real_timing"]
                    S[i, j] = row.iloc[0]["real_t_lo"] > 0 or row.iloc[0]["real_t_hi"] < 0
        keep = ~np.all(np.isnan(M), axis=1)
        M, S, rows = M[keep], S[keep], [r for r, k in zip(rows, keep, strict=True) if k]
        lim = np.nanmax(np.abs(M)) if np.isfinite(M).any() else 0.05
        fig, ax = plt.subplots(figsize=(10, 0.38 * len(rows) + 1.6))
        from matplotlib.colors import LinearSegmentedColormap
        cmap = LinearSegmentedColormap.from_list("div", ["#d95926", "#f0efec", "#2a78d6"])
        im = ax.imshow(M, cmap=cmap, vmin=-lim, vmax=lim, aspect="auto")
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                if np.isfinite(M[i, j]):
                    ax.text(j, i, f"{M[i, j]:+.3f}{'*' if S[i, j] else ''}", ha="center", va="center", fontsize=6.5,
                            color=INK)
        ax.set_xticks(range(len(RULES)))
        ax.set_xticklabels(RULES, rotation=30, ha="right")
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels(rows)
        ax.grid(False)
        fig.colorbar(im, ax=ax, label="timing value, R per opportunity")
        ax.set_title(f"{fam}: timing value by class, real data, confirmation (* = 90% interval excludes 0)")
        save(fig, f"rules_classes_{fam.lower()}.png")
    # kill value against pause fraction
    cells = pd.read_csv(IN / "rules_cells.csv")
    cells = cells[(cells["half"] == "conf") & (cells["cls"] != "RANGE_BREAK") & (cells["scope"] == "CELL")]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for src in ("walk", "garch", "real"):
        x = cells[cells["src"] == src]
        axes[0].scatter(x["paused"], x["over_on"], s=4, alpha=0.35, color=SRC_C[src], label=src)
        axes[1].scatter(x["paused"], x["timing"], s=4, alpha=0.35, color=SRC_C[src], label=src)
    axes[0].set_xlabel("share of trades paused")
    axes[0].set_ylabel("switched minus always-on (R per opportunity)")
    axes[0].set_title("Value over always-on: pausing a losing stream saves its loss")
    axes[1].set_xlabel("share of trades paused")
    axes[1].set_ylabel("switched minus random-pause twin")
    axes[1].set_title("Timing value: what the timing adds beyond pausing as often")
    axes[0].legend(markerscale=3)
    save(fig, "rules_kill_vs_timing.png")


def power_plot():
    p = pd.read_csv(IN / "power.csv")
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6), sharey=True)
    for ax, blk in zip(axes, (50, 200, 500), strict=True):
        sub = p[p["block"] == blk]
        for k, r in enumerate(("EQ20", "EQ50", "DD", "CUSUM", "PH", "SPRT", "BAYES_ALL", "BAYES_100")):
            ax.plot(sub["amp"], sub[r], "-o", ms=3.5, color=SERIES[k % 8], label=r)
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set_title(f"mean switches between +a and -a every {blk} trades\n"
                     f"(pred_30 it produces: {', '.join(f'{v:.2f}' for v in sub['pred_30'])})", fontsize=8)
        ax.set_xlabel("regime size a (R per trade, sd 1R)")
    axes[0].set_ylabel("timing value over the twin, R per trade")
    axes[0].legend(fontsize=7, ncol=2)
    fig.suptitle("Positive control: what the rules earn when regimes do exist")
    save(fig, "power.png")


def kill_plot():
    k = pd.read_csv(IN / "kill.csv")
    k = k[k["shape"] == "empirical"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    ax = axes[0]
    rules = ["SPRT one-shot", "BAYES_ALL", "BAYES_P05", "CUSUM", "DD", "EQ20"]
    mus = sorted(k["mu"].unique())
    w = 0.13
    for i, r in enumerate(rules):
        sub = k[k["rule"] == r].set_index("mu").reindex(mus)
        x = np.arange(len(mus)) + (i - 2.5) * w
        ax.errorbar(x, sub["p50"], yerr=[sub["p50"] - sub["p10"], sub["p90"] - sub["p50"]], fmt="o", ms=4,
                    color=SERIES[i], elinewidth=1, label=r)
    ax.set_yscale("log")
    ax.set_xticks(range(len(mus)))
    ax.set_xticklabels([f"{m:+.2f}R" for m in mus])
    ax.set_xlabel("true edge per trade")
    ax.set_ylabel("closes to the first pause / decision (p10-p50-p90)")
    ax.legend(fontsize=7)
    ax.set_title("How long each rule takes to act (empirical R shape)")
    ax = axes[1]
    s = k[k["rule"] == "SPRT one-shot"].set_index("mu").reindex(mus)
    ax.bar(np.arange(len(mus)) - 0.2, s["dead"], 0.38, color="#e34948", label="called dead (mu <= 0)")
    ax.bar(np.arange(len(mus)) + 0.2, s["alive"], 0.38, color="#1baf7a", label="called alive (mu >= +0.10R)")
    ax.set_xticks(range(len(mus)))
    ax.set_xticklabels([f"{m:+.2f}R" for m in mus])
    ax.set_ylabel("share of 3,000-close paths")
    ax.set_title("SPRT (0 vs +0.10R, alpha 0.05, beta 0.20): what it decides")
    ax.legend(fontsize=7)
    save(fig, "kill_sample_size.png")


def hot_plot():
    h = pd.read_csv(IN / "hot.csv")
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6))
    for ax, stat, lab in zip(axes, ("best20", "win_run", "best_cum"),
                             ("best rolling 20-trade mean R", "longest winning run", "best run-up (R)"), strict=True):
        for kind, col in (("walk_blocks", "#eb6834"), ("iid_empirical", "#2a78d6")):
            sub = h[(h["stat"] == stat) & (h["kind"] == kind)].sort_values("length")
            ax.plot(sub["length"], sub["p50"], "-o", ms=3.5, color=col, label=f"{kind} median")
            ax.plot(sub["length"], sub["p95"], "--", color=col, lw=1.4, label=f"{kind} 95th pct")
        ax.set_xscale("log")
        ax.set_xlabel("trades in the stream")
        ax.set_title(f"{lab}, zero edge")
    axes[0].legend(fontsize=7)
    fig.suptitle("What 'hot' looks like on a strategy with no edge at all")
    save(fig, "hot_streaks.png")


def live_plot():
    tr = pd.read_pickle(LIVE / "live_traces.pkl")  # our own output
    names = list(tr)
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    show = ("EQ20", "DD", "CUSUM", "SPRT", "BAYES_ALL")
    for ax, nm in zip(axes.flat, names, strict=False):
        d = tr[nm]
        x = np.arange(1, len(d["R"]) + 1)
        ax.plot(x, np.cumsum(d["R"]), color=INK, lw=1.8, label="cumulative R")
        top = np.cumsum(d["R"]).max() + 1
        for i, r in enumerate(show):
            off = ~d[r].astype(bool)
            yy = top + 0.9 * (i + 1)
            ax.scatter(x[off], np.full(off.sum(), yy), s=7, marker="s", color=SERIES[i], label=f"{r} paused")
        ax.set_title(f"{nm} (n={len(x)}, mean {d['R'].mean():+.3f}R)")
        ax.set_xlabel("close number")
    axes.flat[0].legend(fontsize=6, loc="lower left")
    fig.suptitle("Live closes export: each strategy's record, and when each rule would have paused it")
    save(fig, "live_rules.png")


def hedge_plot():
    curves = pd.read_pickle(IN / "hedge_curves.pkl.gz")  # our own output
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    for ax, src in zip(axes, ("real", "walk", "garch"), strict=True):
        key = (f"PROD {src}", "HEDGE_10")
        if key not in curves:
            continue
        days, always, port, twin, cash = curves[key]
        t = pd.to_datetime(days * 86400, unit="s")
        ax.plot(t, np.cumsum(always), color=INK2, lw=1.4, label="always on (every strategy)")
        ax.plot(t, np.cumsum(port), color=SRC_C[src], label="Hedge, eta 0.10, with cash")
        ax.plot(t, np.cumsum(twin), "--", color="#4a3aa7", lw=1.2, label="Hedge's weights, time-shifted")
        ax.axvline(pd.Timestamp("2024-01-01"), color=INK2, lw=0.8, ls=":")
        ax.set_title(f"PROD book, {src}")
        ax.set_ylabel("cumulative R")
    axes[0].legend(fontsize=7)
    save(fig, "hedge.png")


def pnr_plot():
    cells = pd.read_csv(IN / "rules_cells.csv")
    b = cells[(cells["scope"] == "BOOK") & (cells["half"] == "all") & (cells["rule"] == "EQ20")]
    strats = sorted(b["strat"].unique())
    nrow = int(np.ceil(len(strats) / 5))
    fig, axes = plt.subplots(nrow, 5, figsize=(14, 2.8 * nrow), sharey=True, squeeze=False)
    for ax, s in zip(axes.flat, strats, strict=False):
        for src in ("real", "walk", "garch"):
            r = b[(b["strat"] == s) & (b["src"] == src)]
            if len(r):
                r = r.iloc[0]
                ax.plot(NS, [r[f"P{N}_on"] for N in NS], "-o", ms=3, color=SRC_C[src],
                        label=f"{src} {r['always']:+.3f}R")
        ax.plot(NS, [1 / (N + 1) for N in NS], color=INK2, lw=0.9, ls=":", label="1/(N+1)")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_ylim(0.003, 1)
        ax.set_title(s, fontsize=8)
        ax.legend(fontsize=5.5, loc="lower left")
    for ax in axes.flat[len(strats):]:
        ax.set_visible(False)
    fig.suptitle("Production strategies replayed: P(+N R before the stop, within the hold) against 1/(N+1) and the walks; legend: mean R after costs")
    save(fig, "pnr_prod.png")


def main():
    for f in (nec_plot, rules_plot, power_plot, kill_plot, hot_plot, live_plot, hedge_plot, pnr_plot):
        try:
            f()
        except Exception as exc:  # noqa: BLE001 - one missing table must not stop the rest
            print("skip", f.__name__, exc)


if __name__ == "__main__":
    main()
