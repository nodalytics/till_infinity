"""Figures for research/docs/deriv-ml.md, from OUT/report/*.csv (derivml_report.py) and OUT/gen_params.json.

  OUT=... IMG=... python research/ideas/derivml_plots.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import derivml_data as D  # noqa: E402

REP = D.OUT / "report"
IMG = Path(os.environ.get("IMG", REP / "img"))
COL = {"real": "#2a78d6", "iid": "#eb6834", "garch": "#1baf7a", "gen": "#8a3ffc", "ref": "#8a8984",
       "VOL2": "#2a78d6", "VOL1": "#eb6834", "VOLHF": "#1baf7a", "POOL": "#0b0b0b",
       "STEP": "#2a78d6", "MSTEP": "#eb6834", "SKEW": "#1baf7a", "BC": "#2a78d6", "JUMP": "#eb6834", "RB": "#2a78d6"}
INK, INK2 = "#0b0b0b", "#52514e"
TFS = ("1h", "4h", "1d")
GROUPS = ("DIFF", "STEP", "JUMPY", "RB")
GNAME = {"DIFF": "Volatility (diffusive)", "STEP": "Step", "JUMPY": "Boom/Crash and Jump", "RB": "Range Break"}
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": INK2,
                     "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "font.size": 9,
                     "axes.titlesize": 10, "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": 0.6,
                     "legend.frameon": False, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})


def save(fig, name):
    IMG.mkdir(parents=True, exist_ok=True)
    fig.savefig(IMG / name, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("  ", name, flush=True)


def csv(name):
    p = REP / name
    return pd.read_csv(p) if p.exists() and p.stat().st_size > 5 else pd.DataFrame()


def dots(ax, labels, vals, los, his, color, off=0.0, label=None, ms=4):
    y = np.arange(len(labels)) + off
    vals, los, his = (np.asarray(x, float) for x in (vals, los, his))
    ax.errorbar(vals, y, xerr=[np.nan_to_num(vals - los), np.nan_to_num(his - vals)], fmt="o", color=color, ms=ms,
                lw=1.4, capsize=0, label=label)
    ax.set_yticks(np.arange(len(labels)))
    ax.set_yticklabels(labels)


def nulls(g):
    return [s for s in D.SOURCES[g] if s != "real"]


# ------------------------------------------------------------------------------------------ the generators

def generator_plots():
    gp = json.loads((D.OUT / "gen_params.json").read_text())["series"]
    # Volatility: realised / named sigma per instrument, by tick rate
    rows = []
    for s, v in gp.items():
        r = v["report"]
        if r.get("group") == "DIFF" and r.get("ratio_disc") is not None:
            ci = r.get("ratio_disc_ci") or [np.nan, np.nan]
            rows.append(dict(sym=s, cls=r["cls"], ratio=r["ratio_disc"], lo=ci[0], hi=ci[1], dt=v.get("dt_s")))
    x = pd.DataFrame(rows)
    if len(x):
        x = x.sort_values(["cls", "sym"])
        fig, ax = plt.subplots(figsize=(7, 0.28 * len(x) + 1))
        for k, c in enumerate(("VOL2", "VOL1", "VOLHF")):
            xs = x[x.cls == c]
            yy = np.flatnonzero((x.cls == c).to_numpy())
            ax.errorbar(xs.ratio, yy, xerr=[np.nan_to_num(xs.ratio - xs.lo), np.nan_to_num(xs.hi - xs.ratio)], fmt="o",
                        color=COL[c], ms=4, lw=1.4, label={"VOL2": "2-second ticks", "VOL1": "1-second ticks",
                                                           "VOLHF": "High Frequency"}[c])
        ax.set_yticks(np.arange(len(x)))
        ax.set_yticklabels([s.replace(" Index", "") for s in x.sym])
        ax.axvline(1, color=INK2, lw=0.8)
        ax.set_xlabel("realised sigma / named sigma (discovery 1h closes, day-bootstrap 90%)")
        ax.set_title("The Volatility indices realise the sigma in their names")
        ax.invert_yaxis()
        ax.legend(loc="lower right")
        save(fig, "gen_vol_sigma.png")
    # Step: up share with interval, run lengths and variance ratio
    rows = []
    for s, v in gp.items():
        r = v["report"]
        if r.get("group") == "STEP":
            rows.append(dict(sym=s, cls=r["cls"], up=r["up_share"], lo=r["up_share_ci90"][0], hi=r["up_share_ci90"][1],
                             vr=r.get("variance_ratio", {}), ru=r.get("run_up_pmf"), rg=r.get("run_up_pmf_geom"),
                             zero=r.get("zero_share"), support=r.get("support"), probs=r.get("probs")))
    x = pd.DataFrame(rows)
    if len(x):
        fig, axs = plt.subplots(1, 3, figsize=(14, 4))
        ax = axs[0]
        for c in ("STEP", "MSTEP", "SKEW"):
            yy = np.flatnonzero((x.cls == c).to_numpy())
            xs = x[x.cls == c]
            ax.errorbar(xs.up, yy, xerr=[xs.up - xs.lo, xs.hi - xs.up], fmt="o", color=COL[c], ms=4, label=c)
        ax.set_yticks(np.arange(len(x)))
        ax.set_yticklabels([s.replace(" Index", "") for s in x.sym])
        ax.axvline(0.5, color=INK2, lw=0.8)
        ax.set_xlabel("share of up ticks (90% Wilson)")
        ax.set_title("Up share per tick")
        ax.invert_yaxis()
        ax.legend(loc="lower right")
        ax = axs[1]
        for _, r in x[x.cls == "STEP"].iterrows():
            ax.plot(range(1, 11), r.ru, "o-", ms=3, lw=1, label=r.sym.replace(" Index", ""))
        r0 = x[x.cls == "STEP"].iloc[0]
        ax.plot(range(1, 11), r0.rg, "k--", lw=1, label="geometric at the measured up share")
        ax.set_yscale("log")
        ax.set_xlabel("length of an up-run (ticks)")
        ax.set_ylabel("share of up-runs")
        ax.set_title("Run lengths, Step 100-500")
        ax.legend(fontsize=7)
        ax = axs[2]
        for _, r in x.iterrows():
            if not r.vr:
                continue
            ks = sorted(int(k) for k in r.vr)
            ax.plot(ks, [r.vr[str(k)] if str(k) in r.vr else r.vr[k] for k in ks], "o-", ms=3, lw=1, color=COL[r.cls])
        ax.axhline(1, color=INK2, lw=0.8)
        ax.set_xscale("log")
        ax.set_xlabel("ticks aggregated")
        ax.set_ylabel("variance ratio")
        ax.set_title("Variance ratio of the tick path")
        save(fig, "gen_step.png")


# ------------------------------------------------------------------------------------------ risk

def risk_plots():
    r = csv("risk.csv")
    if not len(r):
        return
    models = ["hgb", "wf", "sgd", "ridge", "mlp", "har", "garch", "ewma", "envelope", "const", "gen_s"]
    for vs in ("har", "gen"):
        x0 = r[(r.vs == vs) & (r.target == "rvk") & (r.cls == "POOL")]
        if not len(x0):
            continue
        fig, axs = plt.subplots(len(GROUPS), 3, figsize=(13, 3.0 * len(GROUPS)), sharey=False)
        for i, g in enumerate(GROUPS):
            for j, tf in enumerate(TFS):
                ax = axs[i, j]
                x = x0[(x0.group == g) & (x0.tf == tf)]
                labs = [m for m in models if (x.model == m).any() and m != vs]
                if not labs:
                    ax.set_visible(False)
                    continue
                srcs = D.SOURCES[g]
                for k, s in enumerate(srcs):
                    xs = x[x.source == s].set_index("model").reindex(labs)
                    off = (k - (len(srcs) - 1) / 2) * 0.18
                    dots(ax, labs, 100 * xs.rel, 100 * xs.lo, 100 * xs.hi, COL[s], off, s if (i, j) == (0, 0) or j == 0 else None)
                ax.axvline(0, color=INK2, lw=0.8)
                ax.set_title(f"{GNAME[g]}, {tf}")
                ax.invert_yaxis()
                if i == len(GROUPS) - 1:
                    ax.set_xlabel(f"QLIKE vs {'log-HAR-RV' if vs == 'har' else 'the generator constant'}, % (left = better)")
                if j == 0:
                    ax.legend(loc="lower left", fontsize=7)
        fig.suptitle(f"Next-k realised variance: every model against {vs.upper()}, confirmation, real and null", y=1.0)
        fig.tight_layout()
        save(fig, f"risk_rvk_vs_{vs}.png")
    # P1 cells by tick rate
    x = r[(r.group == "DIFF") & (r.target == "rvk") & (r.model == "hgb") & r.vs.isin(["har", "gen"])]
    if len(x):
        fig, axs = plt.subplots(1, 3, figsize=(13, 3.4), sharey=True)
        cells = ["VOL2", "VOL1", "VOLHF", "POOL"]
        for ax, tf in zip(axs, TFS):
            k = 0
            for vs in ("har", "gen"):
                for s in D.SOURCES["DIFF"]:
                    xs = x[(x.tf == tf) & (x.vs == vs) & (x.source == s)].set_index("cls").reindex(cells)
                    off = -0.33 + 0.095 * k
                    dots(ax, cells, 100 * xs.rel, 100 * xs.lo, 100 * xs.hi, COL[s], off,
                         f"{s} vs {vs}" if tf == "1h" else None, ms=3 if vs == "gen" else 5)
                    k += 1
            ax.axvline(0, color=INK2, lw=0.8)
            ax.set_title(f"{tf}: HGB on rvk, by tick rate")
            ax.set_xlabel("QLIKE change, % (big dots vs HAR, small vs the generator)")
            ax.invert_yaxis()
        axs[0].legend(fontsize=6, loc="lower left")
        save(fig, "p1_tickrate.png")


def constvol_plot():
    c = csv("constvol.csv")
    if not len(c):
        return
    for g in ("DIFF", "STEP"):
        fig, axs = plt.subplots(1, 3, figsize=(14, 0.25 * c[(c.group == g) & (c.tf == "1h")].sym.nunique() + 1.5), sharey=True)
        syms = sorted(c[c.group == g].sym.unique(), key=lambda s: (D.REG[s]["cls"], s))
        for ax, tf in zip(axs, TFS):
            for k, s in enumerate(D.SOURCES[g]):
                xs = c[(c.group == g) & (c.tf == tf) & (c.source == s)].set_index("sym").reindex(syms)
                off = (k - (len(D.SOURCES[g]) - 1) / 2) * 0.18
                dots(ax, [s_.replace(" Index", "") for s_ in syms], 100 * xs.hgb_vs_gen, 100 * xs.hgb_lo,
                     100 * xs.hgb_hi, COL[s], off, s if tf == "1h" else None, ms=3)
            ax.axvline(0, color=INK2, lw=0.8)
            ax.set_title(f"{tf}")
            ax.set_xlabel("HGB QLIKE vs the generator's constant volatility, % (left = ML better)")
            ax.invert_yaxis()
        axs[0].legend(fontsize=7, loc="lower left")
        fig.suptitle(f"{GNAME[g]}: the constant-volatility check per instrument (rvk, confirmation)")
        save(fig, f"constvol_{g}.png")


# ------------------------------------------------------------------------------------------ direction

def auc_plots():
    c = csv("classes.csv")
    b = csv("behavioural.csv")
    if not len(c):
        return
    tg = ["sign1", "signk", "nr2L", "nr2S", "first", "tup10", "tdn10", "spk"]
    fig, axs = plt.subplots(len(GROUPS), 3, figsize=(13, 2.9 * len(GROUPS)))
    for i, g in enumerate(GROUPS):
        for j, tf in enumerate(TFS):
            ax = axs[i, j]
            x = c[(c.group == g) & (c.tf == tf) & (c.cls == "POOL") & (c.model == "hgb")]
            labs = [t for t in tg if (x.target == t).any()]
            if not labs:
                ax.set_visible(False)
                continue
            srcs = D.SOURCES[g]
            for k, s in enumerate(srcs):
                xs = x[x.source == s].set_index("target").reindex(labs)
                off = (k - (len(srcs) - 1) / 2) * 0.18
                dots(ax, labs, xs.auc, xs.auc_lo, xs.auc_hi, COL[s], off, s if j == 0 else None, ms=3)
            ax.axvline(0.5, color=INK2, lw=0.8)
            ax.set_title(f"{GNAME[g]}, {tf}: AUC, HGB")
            ax.invert_yaxis()
            if j == 0:
                ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    save(fig, "auc_real_null.png")
    if not len(b):
        return
    # behavioural skill (real minus null) per group and timeframe, direction targets
    dt = ["sign1", "signk", "nr2L", "nr2S", "first", "spk"]
    fig, axs = plt.subplots(len(GROUPS), 3, figsize=(13, 2.7 * len(GROUPS)))
    for i, g in enumerate(GROUPS):
        for j, tf in enumerate(TFS):
            ax = axs[i, j]
            x = b[(b.group == g) & (b.tf == tf) & (b.cls == "POOL") & (b.model == "hgb")]
            labs = [t for t in dt if (x.target == t).any()]
            if not labs:
                ax.set_visible(False)
                continue
            for k, w in enumerate(nulls(g)):
                xs = x[x["null"] == w].set_index("target").reindex(labs)
                off = (k - (len(nulls(g)) - 1) / 2) * 0.2
                dots(ax, labs, xs["diff"], xs.lo, xs.hi, COL[w], off, f"real minus {w}" if j == 0 else None, ms=3)
            ax.axvline(0, color=INK2, lw=0.8)
            ax.set_title(f"{GNAME[g]}, {tf}: behavioural AUC")
            ax.invert_yaxis()
            if j == 0:
                ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    save(fig, "behavioural_auc.png")
    # by class (tick rate inside DIFF, etc.), sign1 and signk
    fig, axs = plt.subplots(1, 3, figsize=(13, 5), sharey=True)
    for ax, tf in zip(axs, TFS):
        labs, vals, los, his, cols = [], [], [], [], []
        for g in GROUPS:
            for cl in D.CLASSES[g] + ("POOL",):
                for t in ("sign1", "signk"):
                    w = "gen"
                    x = b[(b.group == g) & (b.tf == tf) & (b.cls == cl) & (b.model == "hgb") & (b.target == t) &
                          (b["null"] == w)]
                    if not len(x):
                        continue
                    labs.append(f"{g if cl == 'POOL' else cl} {t}")
                    vals.append(x["diff"].iloc[0])
                    los.append(x.lo.iloc[0])
                    his.append(x.hi.iloc[0])
                    cols.append(COL.get(cl, INK) if cl != "POOL" else INK)
        if labs:
            for k in range(len(labs)):
                ax.errorbar(vals[k], k, xerr=[[vals[k] - los[k]], [his[k] - vals[k]]], fmt="o", color=cols[k], ms=3)
            ax.set_yticks(range(len(labs)))
            ax.set_yticklabels(labs, fontsize=7)
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_title(f"{tf}: real minus generator null, AUC")
        ax.invert_yaxis()
    save(fig, "behavioural_by_class.png")


def p2_plot():
    s = json.loads((REP / "summary.json").read_text()) if (REP / "summary.json").exists() else {}
    c = csv("classes.csv")
    if not len(c):
        return
    x = c[(c.group == "DIFF") & (c.tf == "4h") & (c.target == "sign1")]
    cells = ["VOL2", "VOL1", "VOLHF", "POOL"]
    models = ["hgb", "logistic", "mlp", "wf", "sgd"]
    fig, axs = plt.subplots(1, len(cells), figsize=(14, 3), sharey=True)
    for ax, cl in zip(axs, cells):
        for k, src in enumerate(D.SOURCES["DIFF"]):
            xs = x[(x.cls == cl) & (x.source == src)].set_index("model").reindex(models)
            dots(ax, models, xs.auc, xs.auc_lo, xs.auc_hi, COL[src], (k - 1.5) * 0.15, src if cl == "VOL2" else None, ms=3)
        ax.axvline(0.5, color=INK2, lw=0.8)
        ax.axvline(0.51, color=INK2, lw=0.6, ls=":")
        ax.set_title(f"P2 cell {cl}: 4h sign1 AUC" + (" (secondary)" if cl in ("VOLHF", "POOL") else ""))
        ax.invert_yaxis()
    axs[0].legend(fontsize=7, loc="lower left")
    save(fig, "p2_auc.png")


def reliability_plot():
    r = csv("reliability.csv")
    if not len(r):
        return
    pairs = [("DIFF", "tup10"), ("DIFF", "sign1"), ("STEP", "sign1"), ("JUMPY", "spk"), ("JUMPY", "sign1"), ("RB", "sign1")]
    fig, axs = plt.subplots(2, 3, figsize=(12, 7.5))
    for ax, (g, t) in zip(axs.ravel(), pairs):
        x = r[(r.group == g) & (r.target == t) & (r.tf == "1h") & (r.model == "hgb")]
        for s in D.SOURCES[g]:
            xs = x[x.source == s]
            ax.plot(xs.p, xs.y, "o-", ms=3, lw=1, color=COL[s], label=s)
        lim = [min(x.p.min(), x.y.min()) if len(x) else 0, max(x.p.max(), x.y.max()) if len(x) else 1]
        ax.plot(lim, lim, color=INK2, lw=0.8, ls=":")
        ax.set_title(f"{GNAME[g]}, 1h {t}")
        ax.set_xlabel("predicted (decile mean)")
        ax.set_ylabel("observed")
        ax.legend(fontsize=7)
    fig.tight_layout()
    save(fig, "reliability.png")


# ------------------------------------------------------------------------------------------ conformal

def aci_plots():
    m = csv("cqr_months.csv")
    q = csv("cqr.csv")
    if not len(m):
        return
    fig, axs = plt.subplots(2, 2, figsize=(13, 7))
    for ax, g in zip(axs.ravel(), GROUPS):
        x = m[(m.group == g) & (m.tf == "1h") & (m.target == "rvk") & (m.source == "real")]
        for nm, meth, col in (("hgb", "aci", COL["real"]), ("hgb", "split", "#9fc3ee"), ("har", "aci", COL["iid"]),
                              ("hgb", "agaci", COL["garch"]), ("gen", "aci", COL["gen"])):
            xs = x[(x.model == nm) & (x.method == meth)].sort_values("month")
            if len(xs):
                ax.plot(pd.PeriodIndex(xs.month, freq="M").to_timestamp(), xs.cover, lw=1.2, color=col, label=f"{nm} {meth}")
        ax.axhline(0.9, color=INK2, lw=0.8, ls=":")
        ax.set_ylim(0.6, 1.0)
        ax.set_title(f"{GNAME[g]}: 90% interval for 1h next-24-bar RV, coverage by month (real)")
        ax.legend(fontsize=7, loc="lower left")
    fig.tight_layout()
    save(fig, "aci_coverage_time.png")
    if not len(q):
        return
    fig, axs = plt.subplots(1, 4, figsize=(15, 3.6))
    for ax, g in zip(axs, GROUPS):
        x = q[(q.group == g) & (q.target == "rvk") & (q.cls == "POOL") & (q.method == "aci")]
        for s in D.SOURCES[g]:
            for tf, mk in zip(TFS, ("o", "s", "^")):
                xs = x[(x.source == s) & (x.tf == tf)]
                ax.scatter(xs.width, xs.cover, s=18, marker=mk, color=COL[s], label=f"{s} {tf}" if g == "DIFF" else None)
                for _, rr in xs.iterrows():
                    if s == "real":
                        ax.annotate(rr.model, (rr.width, rr.cover), fontsize=6, color=INK2)
        ax.axhline(0.9, color=INK2, lw=0.8, ls=":")
        ax.set_xlabel("mean width (log units)")
        ax.set_ylabel("coverage")
        ax.set_title(f"{GNAME[g]}: ACI intervals, rvk")
    axs[0].legend(fontsize=6)
    fig.tight_layout()
    save(fig, "interval_widths.png")
    w = csv("cqr_width.csv")
    if len(w):
        fig, axs = plt.subplots(1, 3, figsize=(13, 4), sharey=True)
        for ax, tf in zip(axs, TFS):
            x = w[(w.tf == tf) & (w.target == "rvk") & (w.cls == "POOL") & (w.source == "real")]
            labs = [f"{r.group} vs {r.vs}" for r in x.itertuples()]
            dots(ax, labs, 100 * x.width_rel, 100 * x.lo, 100 * x.hi, COL["real"])
            ax.axvline(0, color=INK2, lw=0.8)
            ax.set_title(f"{tf}: HGB+ACI width vs baseline+ACI, rvk")
            ax.set_xlabel("width change, % (left = ML narrower)")
            ax.invert_yaxis()
        save(fig, "aci_width_vs_baselines.png")
    s = csv("sets.csv")
    if len(s):
        fig, axs = plt.subplots(1, 4, figsize=(15, 3.6), sharey=True)
        tg = ["tup05", "tdn05", "tup10", "tdn10", "first", "sign1", "signk", "nr2L", "spk"]
        for ax, g in zip(axs, GROUPS):
            x = s[(s.group == g) & (s.tf == "1h") & (s.cls == "POOL") & (s.model == "hgb") & (s.method == "aci")]
            labs = [t for t in tg if (x.target == t).any()]
            for k, src in enumerate(D.SOURCES[g]):
                xs = x[x.source == src].set_index("target").reindex(labs)
                ax.barh(np.arange(len(labs)) + (k - 1) * 0.2, xs.singleton, height=0.2, color=COL[src], label=src)
            ax.set_yticks(range(len(labs)))
            ax.set_yticklabels(labs)
            ax.set_xlabel("singleton rate (ACI sets, alpha 0.10)")
            ax.set_title(f"{GNAME[g]}, 1h")
            ax.legend(fontsize=7)
        save(fig, "sets_singleton.png")


# ------------------------------------------------------------------------------------------ ablation, P(N R), trades

def ablation_plot():
    a = csv("ablation.csv")
    if not len(a):
        return
    comps = [("hgb:CO", "hgb:OH", "HGB: close-only -> OHLC"), ("lin:CO", "lin:OH", "linear: close-only -> OHLC"),
             ("hgb:all", "hgb:all+Q", "HGB: + polynomial fits"), ("lin:base", "lin:base+Q", "linear: + polynomial fits"),
             ("lin:base", "lin:base+E", "linear: + degree-2 expansion")]
    for tgt in ("sign1", "rvk"):
        fig, axs = plt.subplots(1, len(comps), figsize=(17, 4.2), sharey=True)
        for ax, (bse, var, title) in zip(axs, comps):
            labs, k = [], 0
            for g in GROUPS:
                for tf in TFS:
                    x = a[(a.group == g) & (a.tf == tf) & (a.target == tgt) & (a.cls == "POOL") & (a.base == bse) &
                          (a.variant == var)]
                    if not len(x):
                        continue
                    labs.append(f"{g} {tf}")
                    for s, off, mk in (("real", -0.2, "o"), ("gen", 0.0, "s"), ("real-gen", 0.2, "D")):
                        xs = x[x.source == s]
                        if len(xs):
                            col = COL["real"] if s == "real" else COL["gen"] if s == "gen" else INK
                            ax.errorbar(xs.gain.iloc[0], k + off, xerr=[[xs.gain.iloc[0] - xs.lo.iloc[0]],
                                                                        [xs.hi.iloc[0] - xs.gain.iloc[0]]],
                                        fmt=mk, color=col, ms=3, label=s if k == 0 else None)
                    k += 1
            ax.set_yticks(range(len(labs)))
            ax.set_yticklabels(labs, fontsize=7)
            ax.axvline(0, color=INK2, lw=0.8)
            ax.set_title(title, fontsize=9)
            ax.set_xlabel("gain in AUC" if tgt == "sign1" else "gain in QLIKE (lower loss = positive)")
            ax.invert_yaxis()
        axs[0].legend(fontsize=7)
        fig.suptitle(f"Feature ablations, {tgt}: real, generator null and real minus null (day-bootstrap 90%)")
        save(fig, f"ablation_{tgt}.png")


def pnr_plot():
    t = csv("trades.csv")
    p = csv("pnr.csv")
    NS = (1, 2, 4, 10)
    fig, axs = plt.subplots(1, 4, figsize=(15, 3.6), sharey=True)
    for ax, g in zip(axs, GROUPS):
        if len(p):
            for s in D.SOURCES[g]:
                x = p[(p.group == g) & (p.tf == "1h") & (p.source == s) & (p.cls == "POOL") & (p.side == "L")]
                for sel, ls in (("all", "-"), ("top10", "--")):
                    xs = x[x.sel == sel]
                    if len(xs):
                        ax.plot(NS, [xs[f"P{n}"].iloc[0] for n in NS], ls, marker="o", ms=3, color=COL[s],
                                label=f"{s} {sel}")
        if g in ("DIFF", "STEP"):
            ax.plot(NS, [1 / (n + 1) for n in NS], ":", color=INK2, label="1/(N+1)")
        ax.set_yscale("log")
        ax.set_xscale("log")
        ax.set_xticks(NS)
        ax.set_xticklabels(NS)
        ax.set_xlabel("N (R)")
        ax.set_title(f"{GNAME[g]}, 1h: P(+N R before stop), longs")
        ax.legend(fontsize=6)
    axs[0].set_ylabel("share of trades (bar MFE)")
    save(fig, "pnr_nr.png")
    if not len(t):
        return
    fig, axs = plt.subplots(1, 4, figsize=(15, 3.6), sharey=True)
    for ax, g in zip(axs, GROUPS):
        for tf, mk in zip(TFS, ("o", "s", "^")):
            for s in D.SOURCES[g]:
                x = t[(t.group == g) & (t.tf == tf) & (t.source == s) & (t.cls == "POOL")]
                if len(x):
                    ax.plot(NS, [x[f"P{n}"].iloc[0] for n in NS], "-", marker=mk, ms=3, color=COL[s],
                            label=f"{s} {tf}")
        if g in ("DIFF", "STEP"):
            ax.plot(NS, [1 / (n + 1) for n in NS], ":", color=INK2, label="1/(N+1)")
        ax.set_yscale("log")
        ax.set_xscale("log")
        ax.set_xticks(NS)
        ax.set_xticklabels(NS)
        ax.set_title(f"{GNAME[g]}: trade translation P(N R)")
        ax.legend(fontsize=6)
    save(fig, "pnr_trades.png")
    fig, axs = plt.subplots(1, 4, figsize=(15, 3.6), sharey=False)
    for ax, g in zip(axs, GROUPS):
        x = t[(t.group == g) & (t.cls == "POOL")]
        labs = []
        for k, r in enumerate(x.itertuples()):
            col = COL.get(r.source, INK)
            for e, off, mk in (("nettrail", -0.15, "o"), ("net2", 0.15, "s")):
                ax.errorbar(getattr(r, e), k + off, xerr=[[getattr(r, e) - getattr(r, f"{e}_lo")],
                                                          [getattr(r, f"{e}_hi") - getattr(r, e)]], fmt=mk, color=col, ms=3)
            labs.append(f"{r.tf} {r.source} n={r.n}")
        ax.set_yticks(range(len(labs)))
        ax.set_yticklabels(labs, fontsize=7)
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_xlabel("net mean R (o trailing, s +2R)")
        ax.set_title(f"{GNAME[g]}: the trade after costs")
        ax.invert_yaxis()
    save(fig, "trades_net.png")


def importance_plot():
    i = csv("importance.csv")
    if not len(i):
        return
    fig, axs = plt.subplots(1, 4, figsize=(15, 3.6))
    for ax, g in zip(axs, GROUPS):
        x = i[(i.group == g) & (i.tf == "1h") & (i.model == "hgb") & (i.group == g)]
        x = x[x["group"] == g] if "group" in x else x
        gx = x[x.feature.isin(["B0", "S", "P", "C", "Q", "O", "J"]) & (x.target == "rvk")]
        for k, s in enumerate(("real", "gen")):
            xs = gx[gx.source == s].set_index("feature").reindex(["B0", "S", "P", "C", "Q", "O", "J"]).dropna(subset=["drop"])
            ax.barh(np.arange(len(xs)) + (k - 0.5) * 0.35, xs["drop"], height=0.35, color=COL[s], label=s)
            ax.set_yticks(range(len(xs)))
            ax.set_yticklabels(xs.index)
        ax.set_title(f"{GNAME[g]}, 1h rvk: permutation importance")
        ax.set_xlabel("QLIKE increase when permuted")
        ax.legend(fontsize=7)
    save(fig, "importance_rvk.png")


def main():
    for f in (generator_plots, risk_plots, constvol_plot, auc_plots, p2_plot, reliability_plot, aci_plots,
              ablation_plot, pnr_plot, importance_plot):
        try:
            f()
        except Exception as e:  # noqa: BLE001 - one figure failing must not stop the others
            print(f"  {f.__name__} failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
