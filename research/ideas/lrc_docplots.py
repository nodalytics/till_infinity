"""The figures embedded in `research/docs/lrc-retest.md`, drawn from the result tables.

  DATA=.data/lrc python research/ideas/lrc_docplots.py   ->  research/docs/img/lrc/*.png

Reads lrc_table.csv, lrc_strength.csv, lrc_holds.csv (lrc_retest.py MODE=agg) and fade/fade_table.csv
(lrc_fade.py MODE=agg); copies the desk-example gallery.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("DATA", ROOT / ".data/lrc"))
OUT = ROOT / "research/docs/img/lrc"
NS = (0.5, 1, 2, 4, 10)
COL = {"real": "#1d3557", "walk": "#e76f51", "garch": "#2a9d8f", "twin": "#9b5de5", "reversed": "#8d99ae"}
LAB = {"real": "real", "walk": "iid walk", "garch": "GARCH walk", "twin": "coin twin", "reversed": "reversed trade"}
CLASSES = ["NONDERIV", "FX", "METAL", "INDEX", "ENERGY", "CRYPTO_CFD", "BINANCE", "FRESH", "DERIV_1S", "V10_1S",
           "DERIV_DIFFUSIVE", "DERIV_JUMPY", "RANGE_BREAK"]
NAMES = {"NONDERIV": "non-Deriv pool", "V10_1S": "Volatility 10 (1s)", "CRYPTO_CFD": "crypto CFDs",
         "DERIV_1S": "Deriv 1s indices", "DERIV_DIFFUSIVE": "Deriv diffusive", "DERIV_JUMPY": "Deriv jumpy",
         "RANGE_BREAK": "Range Break 100", "FRESH": "fresh coins", "ALL_NONDERIV": "non-Deriv pool"}


def pnr(ax, rows, title):
    for src, r in rows:
        ax.plot(NS, [r[f"P{N}"] for N in NS], "-o", ms=4, color=COL[src],
                label=f"{LAB[src]}  {r['R']:+.3f}R  (n {int(r['n']):,})")
    ax.plot(NS, [1 / (N + 1) for N in NS], color="k", lw=0.9, ls="--", label="1/(N+1)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks(NS)
    ax.set_xticklabels([str(n) for n in NS])
    ax.set_xlabel("N (R)")
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=7.5, loc="lower left")
    ax.grid(alpha=0.3, which="both")


def fig_pnr(tab, stab, fade):
    fig, axes = plt.subplots(1, 4, figsize=(22, 5.5), sharey=True)
    pick = lambda src: tab[(tab["rule"] == "R1") & (tab["cls"] == "NONDERIV") & (tab["iv"] == "ALL")  # noqa: E731
                           & (tab["half"] == "conf") & (tab["exit"] == "X2") & (tab["src"] == src)].iloc[0]
    pnr(axes[0], [(s, pick(s)) for s in ("real", "walk", "garch", "twin")],
        "R1, non-Deriv pool, 15m-1d, confirmation")
    for ax, ter in zip(axes[1:3], ("STRONG", "WEAK")):
        rows = [(s, stab[(stab["rule"] == "R1") & (stab["cls"] == "NONDERIV") & (stab["iv"] == "ALL") & (stab["half"] == "conf")
                         & (stab["src"] == s) & (stab["tercile"] == ter)].iloc[0]) for s in ("real", "walk", "garch")]
        pnr(ax, rows, f"R1, {ter} tercile, confirmation")
    rows = [(s, fade[(fade["variant"] == "GATED") & (fade["cls"] == "ALL_NONDERIV") & (fade["iv"] == "ALL") & (fade["src"] == s)].iloc[0])
            for s in ("real", "walk", "garch", "twin", "reversed")]
    pnr(axes[3], rows, "R4b, production's fade-to-value, 15m+30m\n(+N R within its 4h hold)")
    axes[0].set_ylabel("P(+N R before -1R)")
    fig.suptitle("P(+N R before -1R) against 1/(N+1): real trades sit on their walks; legend: mean R a trade after costs",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "pnr.png", dpi=72)
    plt.close(fig)


def fig_r1_classes(tab):
    fig, ax = plt.subplots(figsize=(15, 5.5))
    x = np.arange(len(CLASSES))
    for i, cls in enumerate(CLASSES):
        g = tab[(tab["rule"] == "R1") & (tab["cls"] == cls) & (tab["iv"] == "ALL") & (tab["half"] == "conf") & (tab["exit"] == "X2")]
        r = g[g["src"] == "real"]
        if not len(r):
            continue
        r = r.iloc[0]
        ax.errorbar(i, r["R"], yerr=[[r["R"] - r["lo"]], [r["hi"] - r["R"]]], fmt="o", color=COL["real"], ms=8,
                    capsize=4, label="real, 90% day-bootstrap interval" if i == 0 else None)
        for src, mk in (("walk", "x"), ("garch", "+")):
            w = g[g["src"] == src]
            if len(w):
                ax.plot(i + 0.18, w.iloc[0]["R"], mk, color=COL[src], ms=10, mew=2, label=LAB[src] if i == 0 else None)
        ax.text(i, r["hi"] + 0.02, f"n {int(r['n']):,}", ha="center", fontsize=7)
    ax.axhline(0, color="k", lw=0.7)
    ax.axvspan(-0.5, 0.5, color="#ffd166", alpha=0.25)
    ax.set_xticks(x)
    ax.set_xticklabels([NAMES.get(c, c) for c in CLASSES], rotation=30, ha="right")
    ax.set_ylabel("mean R a trade after costs (2R exit)")
    ax.set_title("R1 by class, confirmation (2024+): every class sits on its walks; the loss is the cost of a 0.78-ATR stop")
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "r1_classes.png", dpi=72)
    plt.close(fig)


def fig_r4b(fade):
    classes = ["ALL_NONDERIV", "FX", "METAL", "INDEX", "ENERGY", "CRYPTO_CFD", "BINANCE", "DERIV_1S", "V10_1S",
               "DERIV_DIFFUSIVE", "DERIV_JUMPY"]
    fig, axes = plt.subplots(1, 3, figsize=(22, 5.5), sharey=True)
    for ax, iv in zip(axes, ("15m", "30m", "ALL")):
        for i, cls in enumerate(classes):
            g = fade[(fade["variant"] == "GATED") & (fade["cls"] == cls) & (fade["iv"] == iv)]
            r = g[g["src"] == "real"]
            if not len(r):
                continue
            r = r.iloc[0]
            if np.isfinite(r["lo"]):
                ax.errorbar(i, r["R"], yerr=[[r["R"] - r["lo"]], [r["hi"] - r["R"]]], fmt="o", color=COL["real"], ms=7,
                            capsize=3, label="real (90% interval)" if i == 0 else None)
            else:
                ax.plot(i, r["R"], "o", color=COL["real"], ms=7)
            for src, mk, dx in (("walk", "x", 0.15), ("garch", "+", 0.15), ("reversed", "s", -0.18)):
                w = g[g["src"] == src]
                if len(w):
                    ax.plot(i + dx, w.iloc[0]["R"], mk, color=COL[src], ms=8, mew=2, mfc="none",
                            label=LAB[src] if i == 0 else None)
        ax.axhline(0, color="k", lw=0.7)
        ax.set_xticks(range(len(classes)))
        ax.set_xticklabels([NAMES.get(c, c) for c in classes], rotation=35, ha="right", fontsize=9)
        ax.set_title(f"{'15m + 30m' if iv == 'ALL' else iv} entries")
        ax.grid(axis="y", alpha=0.3)
        ax.legend(fontsize=8, loc="lower left")
    axes[0].set_ylabel("mean R a trade after costs")
    fig.suptitle("R4b, production's fade-to-value replayed through its own code (GATED): it loses, between its iid and GARCH "
                 "walks, and the reversed trade loses too", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "r4b_classes.png", dpi=72)
    plt.close(fig)


def fig_holds(h):
    classes = ["NONDERIV", "FX", "METAL", "INDEX", "CRYPTO_CFD", "BINANCE", "FRESH", "V10_1S", "DERIV_DIFFUSIVE"]
    types = [("SWING", "plain swing"), ("BOS", "BOS"), ("CHOCH", "CHoCH"), ("OTHER", "broken, neither")]
    fig, ax = plt.subplots(figsize=(17, 5.5))
    w = 0.2
    shade = {"SWING": 0.35, "BOS": 1.0, "CHOCH": 0.75, "OTHER": 0.55}
    for i, cls in enumerate(classes):
        for j, (typ, nm) in enumerate(types):
            g = h[(h["cls"] == cls) & (h["iv"] == "ALL") & (h["split"] == "all") & (h["type"] == typ)]
            r = g[g["src"] == "real"]
            if not len(r):
                continue
            xpos = i + (j - 1.5) * w
            ax.bar(xpos, r.iloc[0]["hold"] - 0.5, w * 0.9, bottom=0.5, color=COL["real"], alpha=shade[typ],
                   label=f"real: {nm}" if i == 0 else None)
            wk = g[g["src"].isin(["walk", "garch"])]["hold"].mean()
            ax.plot([xpos - w * 0.45, xpos + w * 0.45], [wk, wk], color=COL["walk"], lw=2,
                    label="walks (iid and GARCH mean)" if i == 0 and j == 0 else None)
    ax.set_ylim(0.5, 0.66)
    ax.set_xticks(range(len(classes)))
    ax.set_xticklabels([NAMES.get(c, c) for c in classes], rotation=20, ha="right")
    ax.set_ylabel("P(1 ATR away before a close 1 ATR through)")
    ax.set_title("hold rate on the first touch: real levels hold more than walk levels (~0.60 against ~0.565); BOS, CHoCH "
                 "and other broken levels alike, plain swings a little less")
    ax.legend(fontsize=8, ncol=5, loc="upper right")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "holds.png", dpi=72)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tab = pd.read_csv(DATA / "lrc_table.csv")
    stab = pd.read_csv(DATA / "lrc_strength.csv")
    h = pd.read_csv(DATA / "lrc_holds.csv")
    fade = pd.read_csv(DATA / "fade_table.csv")
    fig_pnr(tab, stab, fade)
    fig_r1_classes(tab)
    fig_r4b(fade)
    fig_holds(h)
    shutil.copy(DATA / "lrc_gallery_desk_example_picked.png", OUT / "desk_example.png")
    print("written:", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
