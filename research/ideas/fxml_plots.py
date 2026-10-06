"""Figures for research/docs/fx-metals-ml.md, from OUT/report/*.csv (fxml_report.py).

  OUT=... MODE=plot python research/ideas/fxml_report.py
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import fxml_report as R  # noqa: E402

COL = {"real": "#2a78d6", "iid": "#eb6834", "garch": "#1baf7a", "ref": "#8a8984", "4": "#eda100",
       "5": "#e87ba4", "6": "#008300", "7": "#4a3aa7"}
INK, INK2 = "#0b0b0b", "#52514e"
TFS = ("1h", "4h", "1d")
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": INK2,
                     "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "font.size": 9,
                     "axes.titlesize": 10, "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": 0.6,
                     "legend.frameon": False, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})


def save(fig, name):
    R.IMG.mkdir(parents=True, exist_ok=True)
    fig.savefig(R.IMG / name, dpi=130, bbox_inches="tight")
    plt.close(fig)


def dots(ax, labels, vals, los, his, color, off=0.0, label=None):
    y = np.arange(len(labels)) + off
    ax.errorbar(vals, y, xerr=[np.array(vals) - np.array(los), np.array(his) - np.array(vals)], fmt="o",
                color=color, ms=4, lw=1.5, capsize=0, label=label)
    ax.set_yticks(np.arange(len(labels)))
    ax.set_yticklabels(labels)


def p1_plot():
    r = pd.read_csv(R.REP / "risk.csv")
    r = r[(r.vs == "har") & (r.cls == "POOL") & (r.target == "rvk")]
    models = ["hgb", "wf", "sgd", "ridge", "mlp", "garch", "ewma", "envelope"]
    fig, axs = plt.subplots(1, 3, figsize=(12, 3.6), sharey=True)
    for ax, tf in zip(axs, TFS):
        x = r[r.tf == tf]
        labs = [m for m in models if (x.model == m).any()]
        for k, (s, off) in enumerate((("real", -0.2), ("iid", 0.0), ("garch", 0.2))):
            xs = x[x.source == s].set_index("model").reindex(labs)
            dots(ax, labs, 100 * xs.rel, 100 * xs.lo, 100 * xs.hi, COL[s], off, s if tf == "1h" else None)
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_title(f"{tf}: next-k realised variance")
        ax.set_xlabel("QLIKE vs log-HAR-RV, % (left = better)")
        ax.invert_yaxis()
    axs[0].legend(loc="lower left")
    save(fig, "risk_qlike_vs_har.png")


def behavioural_plot():
    b = pd.read_csv(R.REP / "behavioural.csv")
    tg = ["sign1", "signk", "nr2L", "nr2S", "first", "tup10", "tdn10"]
    fig, axs = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
    for ax, tf in zip(axs, TFS):
        x = b[(b.tf == tf) & (b.cls == "POOL") & (b.model == "hgb")]
        for s, off in (("iid", -0.15), ("garch", 0.15)):
            xs = x[x.walk == s].set_index("target").reindex(tg)
            dots(ax, tg, xs["diff"], xs.lo, xs.hi, COL[s], off, f"real minus {s} twin" if tf == "1h" else None)
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_title(f"{tf}: real-minus-walk (behavioural) AUC, HGB")
        ax.set_xlabel("AUC difference, day-bootstrap 90%")
        ax.invert_yaxis()
    axs[0].legend(loc="lower left")
    save(fig, "behavioural_auc.png")
    # per class
    fig, axs = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
    for ax, tf in zip(axs, TFS):
        x = b[(b.tf == tf) & (b.model == "hgb") & (b.walk == "garch")]
        for k, (c, off) in enumerate((("FX", -0.2), ("METAL", 0.0), ("HOLD", 0.2))):
            xs = x[x.cls == c].set_index("target").reindex(tg)
            dots(ax, tg, xs["diff"], xs.lo, xs.hi, [COL["real"], COL["4"], COL["7"]][k], off,
                 c if tf == "1h" else None)
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_title(f"{tf}: real minus GARCH twin, by class")
        ax.set_xlabel("AUC difference, day-bootstrap 90%")
        ax.invert_yaxis()
    axs[0].legend(loc="lower left")
    save(fig, "behavioural_auc_class.png")


def auc_plot():
    c = pd.read_csv(R.REP / "classes.csv")
    tg = ["sign1", "signk", "nr2L", "nr2S", "first", "tup05", "tup10", "tdn10"]
    fig, axs = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
    for ax, tf in zip(axs, TFS):
        x = c[(c.tf == tf) & (c.cls == "POOL") & (c.model == "hgb")]
        for s, off in (("real", -0.2), ("iid", 0.0), ("garch", 0.2)):
            xs = x[x.source == s].set_index("target").reindex(tg)
            dots(ax, tg, xs.auc, xs.auc_lo, xs.auc_hi, COL[s], off, s if tf == "1h" else None)
        ax.axvline(0.5, color=INK2, lw=0.8)
        ax.set_title(f"{tf}: HGB AUC on confirmation")
        ax.set_xlabel("AUC")
        ax.invert_yaxis()
    axs[0].legend(loc="lower right")
    save(fig, "auc_vs_walks.png")


def reliability_plot():
    r = pd.read_csv(R.REP / "reliability.csv")
    fig, axs = plt.subplots(2, 3, figsize=(12, 7.2))
    for j, tf in enumerate(TFS):
        ax = axs[0, j]
        for mdl, ls in (("hgb", "-"), ("reflect", "--")):
            x = r[(r.tf == tf) & (r.target == "tup10") & (r.model == mdl) & (r.source == "real")]
            ax.plot(x.p, x.y, ls, marker="o", ms=4, color=COL["real"] if mdl == "hgb" else COL["4"], lw=2,
                    label=f"{mdl} (real)")
        lim = max(0.01, r[(r.tf == tf) & (r.target == "tup10")][["p", "y"]].max().max())
        ax.plot([0, lim], [0, lim], color=INK2, lw=0.8)
        ax.set_title(f"{tf}: next bar's high reaches +1 ATR")
        ax.set_xlabel("predicted")
        ax.set_ylabel("observed")
        ax.legend()
        ax = axs[1, j]
        for s in ("real", "iid", "garch"):
            x = r[(r.tf == tf) & (r.target == "sign1") & (r.model == "hgb") & (r.source == s)]
            ax.plot(x.p, x.y, marker="o", ms=4, color=COL[s], lw=2, label=s)
        x = r[(r.tf == tf) & (r.target == "sign1")]
        lo, hi = x[["p", "y"]].min().min(), x[["p", "y"]].max().max()
        ax.plot([lo, hi], [lo, hi], color=INK2, lw=0.8)
        ax.set_title(f"{tf}: next bar up (HGB deciles)")
        ax.set_xlabel("predicted")
        ax.set_ylabel("observed")
        ax.legend()
    fig.tight_layout()
    save(fig, "reliability.png")


def aci_time_plot():
    s = pd.read_csv(R.REP / "cqr_months.csv")
    fig, axs = plt.subplots(1, 3, figsize=(13, 3.6), sharey=True)
    for ax, tf in zip(axs, TFS):
        x = s[(s.tf == tf) & (s.target == "rvk") & (s.source == "real")]
        for (mdl, meth), col in ((("hgb", "split"), COL["4"]), (("hgb", "aci"), COL["real"]),
                                 (("hgb", "agaci"), COL["7"]), (("har", "aci"), COL["garch"]),
                                 (("envelope", "agaci"), COL["iid"])):
            xs = x[(x.model == mdl) & (x.method == meth)].sort_values("month")
            ax.plot(pd.PeriodIndex(xs.month, freq="M").to_timestamp(), xs.cover, color=col, lw=1.6,
                    label=f"{mdl} {meth}")
        ax.axhline(0.9, color=INK2, lw=0.8)
        ax.set_title(f"{tf}: 90% interval for next-k RV, monthly coverage")
        ax.tick_params(axis="x", rotation=30)
    axs[0].legend(loc="lower left", fontsize=8)
    save(fig, "aci_coverage_time.png")


def width_plot():
    c = pd.read_csv(R.REP / "cqr.csv")
    c = c[(c.cls == "POOL") & (c.source == "real")]
    fig, axs = plt.subplots(2, 3, figsize=(13, 6.6))
    for i, tgt in enumerate(("rvk", "range1")):
        for j, tf in enumerate(TFS):
            ax = axs[i, j]
            x = c[(c.tf == tf) & (c.target == tgt)]
            for k, mdl in enumerate(("hgb", "har", "garch", "ewma", "envelope")):
                for meth, mk in (("split", "s"), ("aci", "o"), ("agaci", "^")):
                    xs = x[(x.model == mdl) & (x.method == meth)]
                    if len(xs):
                        ax.scatter(xs.width, xs.cover, color=[COL["real"], COL["garch"], COL["iid"], COL["4"],
                                                              COL["7"]][k], marker=mk, s=40,
                                   label=f"{mdl}" if meth == "aci" else None)
            ax.axhline(0.9, color=INK2, lw=0.8)
            ax.set_title(f"{tf} {tgt}: coverage vs width (log units)")
            ax.set_xlabel("mean width of the 90% interval, log")
            ax.set_ylabel("coverage")
            if i == 0 and j == 0:
                ax.legend(fontsize=8, title="square split, circle ACI, triangle AgACI", title_fontsize=7)
    fig.tight_layout()
    save(fig, "width_comparison.png")


def sets_plot():
    s = pd.read_csv(R.REP / "sets.csv")
    s = s[(s.cls == "POOL") & (s.method == "aci") & (s.model == "hgb")]
    tg = ["sign1", "signk", "nr2L", "first"]
    fig, axs = plt.subplots(1, 2, figsize=(11, 3.6))
    for ax, col, lab in ((axs[0], "singleton", "share of bars with a one-side set"),
                         (axs[1], "single_acc", "accuracy when the set is one side")):
        w = 0.25
        for k, src in enumerate(("real", "iid", "garch")):
            vals = [s[(s.tf == tf) & (s.target == "sign1") & (s.source == src)][col].mean() for tf in TFS]
            ax.bar(np.arange(3) + (k - 1) * w, vals, w * 0.9, color=COL[src], label=src)
        ax.set_xticks(range(3))
        ax.set_xticklabels(TFS)
        ax.set_title(f"next-bar sign, ACI set (alpha 0.10): {lab}")
        if col == "single_acc":
            ax.axhline(0.5, color=INK2, lw=0.8)
            ax.set_ylim(0.45, 0.56)
    axs[0].legend()
    save(fig, "direction_sets.png")


def pnr_plot():
    p = pd.read_csv(R.REP / "pnr.csv")
    ns = np.array(R.NS)
    fig, axs = plt.subplots(1, 3, figsize=(12, 3.6), sharey=True)
    for ax, tf in zip(axs, TFS):
        for s in ("real", "iid", "garch"):
            x = p[(p.tf == tf) & (p.source == s) & (p.cls == "POOL") & (p.sel == "top10")]
            if not len(x):
                continue
            v = np.array([x[f"P{n}"].mean() for n in ns])
            ax.plot(ns, v, marker="o", color=COL[s], lw=2, label=f"{s}, model top decile")
        x = p[(p.tf == tf) & (p.source == "real") & (p.cls == "POOL") & (p.sel == "all")]
        if len(x):
            ax.plot(ns, [x[f"P{n}"].mean() for n in ns], "--", color=COL["real"], lw=1.2, label="real, every bar")
        ax.plot(ns, 1 / (ns + 1), color=INK2, lw=1, ls=":", label="1/(N+1)")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xticks(ns)
        ax.set_xticklabels(ns)
        ax.set_title(f"{tf}: P(+N R before -1R), 3-bar structural stop")
        ax.set_xlabel("N")
    axs[0].legend(fontsize=8)
    save(fig, "pnr.png")


def ablation_plot():
    a = pd.read_csv(R.REP / "ablation.csv")
    a = a[a.cls == "POOL"]
    var = ["hgb:B0+S", "hgb:B0+P", "hgb:B0+C", "hgb:all+Q", "hgb:OH", "lin:base+Q", "lin:base+E", "lin:base+Q+E", "lin:OH"]
    tg = ["rvk", "tup10", "sign1", "nr2L"]
    fig, axs = plt.subplots(len(tg), 3, figsize=(13, 2.6 * len(tg)), sharey=True)
    for i, t in enumerate(tg):
        for j, tf in enumerate(TFS):
            ax = axs[i, j]
            x = a[(a.tf == tf) & (a.target == t)]
            for s, off in (("real", -0.2), ("iid", 0.0), ("garch", 0.2)):
                xs = x[x.source == s].drop_duplicates("variant").set_index("variant").reindex(var)
                dots(ax, var, xs.gain, xs.lo, xs.hi, COL[s], off, s if (i == 0 and j == 0) else None)
            ax.axvline(0, color=INK2, lw=0.8)
            unit = "QLIKE drop" if t == "rvk" else "AUC gain"
            ax.set_title(f"{tf} {t}: {unit} over its base", fontsize=9)
            ax.invert_yaxis() if j == 0 else None
    axs[0, 0].legend(fontsize=8)
    fig.tight_layout()
    save(fig, "ablation.png")


def importance_plot():
    im = pd.read_csv(R.REP / "importance.csv")
    if not len(im):
        return
    g = im[im.group & (im.model == "hgb") & (im.source == "real")]
    groups_ = ["B0", "S", "P", "C", "Q", "O"]
    fig, axs = plt.subplots(1, 4, figsize=(14, 3.4))
    for ax, t in zip(axs, ("rvk", "tup10", "sign1", "nr2L")):
        w = 0.27
        for k, tf in enumerate(TFS):
            x = g[(g.tf == tf) & (g.target == t)].set_index("feature").reindex(groups_)
            ax.bar(np.arange(len(groups_)) + (k - 1) * w, x["drop"], w * 0.9,
                   color=[COL["real"], COL["iid"], COL["garch"]][k], label=tf)
        ax.set_xticks(range(len(groups_)))
        ax.set_xticklabels(groups_)
        ax.set_title(f"{t}: permutation drop by group")
    axs[0].legend()
    save(fig, "importance_groups.png")
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.6))
    for ax, (tf, t) in zip(axs, (("1h", "rvk"), ("4h", "sign1"))):
        x = im[~im.group & (im.model == "hgb") & (im.source == "real") & (im.tf == tf) & (im.target == t)]
        x = x.sort_values("drop", ascending=False).head(15)
        ax.barh(x.feature[::-1], x["drop"][::-1], color=COL["real"])
        ax.set_title(f"{tf} {t}: top features, permutation on confirmation")
    fig.tight_layout()
    save(fig, "importance_top.png")


def trades_plot():
    t = pd.read_csv(R.REP / "trades.csv")
    if not len(t):
        return
    t = t[t.cls == "POOL"]
    ex = ["net1", "net2", "net4", "net10", "nettrail"]
    fig, axs = plt.subplots(1, 3, figsize=(12, 3.4), sharey=True)
    for ax, tf in zip(axs, TFS):
        for s, off in (("real", -0.2), ("iid", 0.0), ("garch", 0.2)):
            x = t[(t.tf == tf) & (t.source == s)]
            if not len(x):
                continue
            x = x.iloc[0]
            dots(ax, ex, [x[e] for e in ex], [x[f"{e}_lo"] for e in ex], [x[f"{e}_hi"] for e in ex], COL[s], off,
                 s if tf == "1h" else None)
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_title(f"{tf}: conformal-set trades, net R")
        ax.invert_yaxis()
    axs[0].legend()
    save(fig, "trades.png")


def main():
    for f in (p1_plot, behavioural_plot, auc_plot, reliability_plot, aci_time_plot, width_plot, sets_plot,
              pnr_plot, ablation_plot, importance_plot, trades_plot):
        try:
            f()
            print("plotted", f.__name__, flush=True)
        except Exception as exc:  # noqa: BLE001
            print("plot failed", f.__name__, exc, flush=True)
    print(json.dumps(sorted(p.name for p in R.IMG.glob("*.png"))))
