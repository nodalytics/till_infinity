"""Tables, verdicts and plots for the geraked EA backtest (`geraked_eas.py`, frozen in `geraked_rule.json`).

Source of the EAs: github.com/geraked/metatrader5 (MIT). Reads the per-series parts under OUT/parts.

  OUT=... MODE=report|plot python research/ideas/geraked_eas.py
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

import geraked_eas as E
import geraked_sim as S

MT5_ND = ("fx", "metal", "index", "energy", "crypto_cfd")
CLASSES = ("fx", "metal", "index", "energy", "crypto_cfd", "binance", "stock", "deriv_diffusive", "deriv_jumpy",
           "range_break")
NS = E.NS
Q = 0.10


def load_parts(out: Path):
    # the parts are this study's own pickles, written by geraked_eas.run on the lab
    tr, g, r, metas, rs, cv = [], [], [], [], {}, {}
    for f in sorted(glob.glob(str(out / "parts" / "*.pkl"))):
        x = pd.read_pickle(f)
        m = x["meta"]
        metas.append(m)
        if m.get("dropped"):
            continue
        if len(x.get("trades", [])):
            tr.append(x["trades"])
        if len(x.get("g", [])):
            g.append(x["g"])
        if len(x.get("r", [])):
            r.append(x["r"])
        key = (m["venue"], m["sym"], m["iv"], m["src"], m["cls"])
        for k, v in x.get("rsamp", {}).items():
            rs[key + k] = v
        for k, v in x.get("curves", {}).items():
            cv[(m["venue"], m["sym"], m["iv"], m["src"]) + k] = v
    t = pd.concat(tr, ignore_index=True)
    for c in ("kind", "ea", "venue", "sym", "iv", "src", "cls", "why"):
        t[c] = t[c].astype(str)
    t = stops_level(t)
    return t, pd.concat(g, ignore_index=True), (pd.concat(r, ignore_index=True) if r else pd.DataFrame()), \
        pd.DataFrame(metas), rs, cv


def stops_level(t):
    """The broker refuses a stop inside SYMBOL_TRADE_STOPS_LEVEL (TRADE_RETCODE_INVALID_STOPS). Applied after the
    run (amendment): MT5 symbols use their spec's stops level (10 points where it is 0), Binance and stocks 1 bp of
    price. Without it a stop a point or two from the fill makes R explode (cost / a near-zero risk)."""
    lvl = {}
    try:
        from mt5bt import load_specs
        import sqlite3
        db = os.environ.get("MT5BT_DB")
        conn = sqlite3.connect(db)
        raw = {s_: json.loads(j) for s_, j in conn.execute("SELECT symbol, spec FROM specs")}
        conn.close()
        for s_, v in raw.items():
            lvl[s_] = max(float(v.get("stops_level") or 0), 10.0) * float(v["point"])
    except Exception as exc:  # noqa: BLE001
        print(f"stops level: no specs ({exc})", flush=True)
    mind = t["sym"].map(lvl).astype(float)
    mind = np.where(np.isfinite(mind) & (t["venue"] == "mt5"), mind, 1e-4 * t["px"].astype(float))
    keep = t["r0"].astype(float).to_numpy() >= mind
    print(f"stops level: {int((~keep).sum())} of {len(t)} trades refused ({(~keep).mean():.2%})", flush=True)
    return t[keep].reset_index(drop=True)


def boot(ts, R, rng, draws=2000):
    """Day bootstrap: resample entry days (every trade that day together). 90% interval and the one-sided p."""
    day = np.asarray(ts) // 86400
    u, inv = np.unique(day, return_inverse=True)
    s = np.bincount(inv, weights=np.asarray(R, float))
    c = np.bincount(inv).astype(float)
    if len(u) < 10:
        return np.nan, np.nan, np.nan
    idx = rng.integers(0, len(u), (draws, len(u)))
    m = s[idx].sum(1) / c[idx].sum(1)
    return float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95)), float((m <= 0).mean())


def bh(p, q=Q):
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    if not ok.any():
        return out
    pv = p[ok]
    o = np.argsort(pv)
    m = len(pv)
    thr = q * np.arange(1, m + 1) / m
    passed = pv[o] <= thr
    k = np.max(np.flatnonzero(passed)) + 1 if passed.any() else 0
    sel = np.zeros(m, bool)
    sel[o[:k]] = True
    out[np.flatnonzero(ok)] = sel
    return out


_IDX = {}


def _index(t):
    """Row positions by (ea, cls, iv, src, kind, sym): every cell is a union of these."""
    key = id(t)
    if key not in _IDX:
        _IDX.clear()
        _IDX[key] = t.groupby(["ea", "cls", "iv", "src", "kind", "sym"], observed=True).indices
    return _IDX[key]


def cell(t, rng, do_boot=True, **filt):
    names = ("ea", "cls", "iv", "src", "kind", "sym")
    want = {k: (set(v) if isinstance(v, (list, tuple, set)) else {v}) for k, v in filt.items() if k in names}
    rest = {k: v for k, v in filt.items() if k not in names}
    pos = [ix for k, ix in _index(t).items() if all(k[names.index(n)] in w for n, w in want.items())]
    if not pos:
        return dict(n=0)
    x = t.iloc[np.sort(np.concatenate(pos))]
    for k, v in rest.items():
        x = x[x[k].isin(v)] if isinstance(v, (list, tuple, set)) else x[x[k] == v]
    if not len(x):
        return dict(n=0)
    lo, hi, p = boot(x["ts"].to_numpy(), x["R"].to_numpy(), rng) if do_boot else (np.nan, np.nan, np.nan)
    return dict(n=len(x), R=float(x["R"].mean()), lo=lo, hi=hi, p=p, win=float((x["R"] > 0).mean()),
                R_before=float(x.loc[x["ts"] < E.SPLIT, "R"].mean()), R_after=float(x.loc[x["ts"] >= E.SPLIT, "R"].mean()),
                **{f"P{N}": float(x[f"P{N}"].mean()) for N in NS})


def mode_s_tables(t, rng):
    rows = []
    # the primary: MT5 non-Deriv, 15m-1d pooled
    for ea in E.EAS:
        base = dict(ea=ea, cls=list(MT5_ND), iv=list(E.TFS))
        r = {"ea": ea, "scope": "PRIMARY mt5 non-deriv 15m-1d"}
        for (src, kind), tag in ((("real", "S"), ""), (("walk", "S"), "iid_"), (("garch", "S"), "garch_"),
                                 (("real", "coin"), "coin_"), (("real", "rev"), "rev_")):
            c = cell(t, rng, src=src, kind=kind, **base)
            r.update({f"{tag}{k}": v for k, v in c.items()} if tag else c)
        rows.append(r)
    prim = pd.DataFrame(rows)
    prim["passes_rules"] = ((prim["R"] > 0) & (prim["lo"] > 0) & (prim["R_before"] > 0) & (prim["R_after"] > 0)
                            & (prim["R"] > prim["iid_R"]) & (prim["R"] > prim["garch_R"]) & (prim["R"] > prim["coin_R"]))
    prim["bh"] = bh(prim["p"].to_numpy())
    prim["PASSES"] = prim["passes_rules"] & prim["bh"]
    # secondary cells: EA x class x timeframe, and EA x class pooled
    rows = []
    for ea in E.EAS:
        for cl in CLASSES:
            for iv in list(E.TFS) + ["all"]:
                f = dict(ea=ea, cls=cl)
                if iv != "all":
                    f["iv"] = iv
                else:
                    f["iv"] = list(E.TFS)
                r = dict(ea=ea, cls=cl, iv=iv)
                c = cell(t, rng, src="real", kind="S", **f)
                if not c["n"]:
                    continue
                r.update(c)
                for src, tag in (("walk", "iid_"), ("garch", "garch_")):
                    x = cell(t, rng, do_boot=False, src=src, kind="S", **f)
                    r.update({f"{tag}R": x.get("R"), **{f"{tag}P{N}": x.get(f"P{N}") for N in NS}})
                for kind, tag in (("coin", "coin_"), ("rev", "rev_")):
                    x = cell(t, rng, do_boot=False, src="real", kind=kind, **f)
                    r.update({f"{tag}R": x.get("R"), **{f"{tag}P{N}": x.get(f"P{N}") for N in NS}})
                rows.append(r)
    sec = pd.DataFrame(rows)
    leaf = sec["iv"] != "all"
    sec["passes_rules"] = ((sec["R"] > 0) & (sec["lo"] > 0) & (sec["R_before"] > 0) & (sec["R_after"] > 0)
                           & (sec["R"] > sec["iid_R"]) & (sec["R"] > sec["garch_R"]) & (sec["R"] > sec["coin_R"]))
    sec["bh"] = False
    sec.loc[leaf, "bh"] = bh(sec.loc[leaf, "p"].to_numpy())
    sec["PASSES"] = sec["passes_rules"] & sec["bh"]
    return prim, sec


def author_tables(t, g, rng):
    rows = []
    for ea, sym, iv in sorted(E.AUTHOR):
        r = dict(ea=ea, sym=sym, iv=iv)
        for src in ("real", "walk", "garch"):
            c = cell(t, rng, src=src, kind="S", ea=ea, sym=sym, iv=iv)
            r[f"{src}_n"], r[f"{src}_R"] = c.get("n"), c.get("R")
            r[f"{src}_P4"] = c.get("P4")
            gg = g[(g["ea"] == ea) & (g["sym"] == sym) & (g["iv"] == iv) & (g["src"] == src) & (g["eq_limit"] == 0)]
            for _, x in gg.iterrows():
                tag = "G1" if abs(x["risk"] - 0.01) < 1e-9 else "Ga"
                r[f"{src}_{tag}_risk"] = x["risk"]
                r[f"{src}_{tag}_cagr"] = x["cagr"]
                r[f"{src}_{tag}_mdd"] = x["mdd"]
                r[f"{src}_{tag}_wdd"] = x["worst_open_dd"]
                r[f"{src}_{tag}_ruin"] = x["ruin_days"]
                r[f"{src}_{tag}_so"] = x["first_stopout_days"]
        rows.append(r)
    return pd.DataFrame(rows)


def mode_g_tables(g):
    g = g[g["eq_limit"] == 0].copy()
    g = g[np.isclose(g["risk"], 0.01)]
    g["ruined"] = g["ruin_days"].notna()
    g["stopped"] = g["first_stopout_days"].notna()
    agg = dict(series=("cagr", "size"), cagr_med=("cagr", "median"), cagr_mean=("cagr", "mean"), mdd_med=("mdd", "median"),
               wdd_med=("worst_open_dd", "median"), ruined=("ruined", "mean"), stopout=("stopped", "mean"),
               days_to_stopout=("first_stopout_days", "median"), maxed=("maxed", "mean"), mean_lvl=("mean_lvl", "mean"),
               profitable=("cagr", lambda x: float((x > 0).mean())))
    g["scope"] = np.where(g["cls"].isin(MT5_ND), "mt5_nd", g["cls"])
    pooled = g[g["iv"].isin(E.TFS)].groupby(["ea", "scope", "src"]).agg(**agg).reset_index()
    per_cls = g[g["iv"].isin(E.TFS)].groupby(["ea", "cls", "src"]).agg(**agg).reset_index()
    per_tf = g[g["cls"].isin(MT5_ND)].groupby(["ea", "iv", "src"]).agg(**agg).reset_index()
    return pooled, per_cls, per_tf


def mode_r_tables(r, rs):
    if r.empty:
        return pd.DataFrame(), pd.DataFrame()
    r = r.copy()
    r["scope"] = np.where(r["cls"].isin(MT5_ND), "mt5_nd", r["cls"])
    rows = []
    for (scope, src, cfg), x in r.groupby(["scope", "src", "config"]):
        w = x["n"].fillna(0)
        row = dict(scope=scope, src=src, config=cfg, n=int(w.sum()), series=len(x),
                   cagr_med=x["cagr"].median(), mdd_med=x["mdd"].median(), wdd_med=x["worst_open_dd"].median())
        if "R" in x and w.sum() > 0 and x["R"].notna().any():
            ok = x["R"].notna()
            row["R"] = float(np.average(x.loc[ok, "R"], weights=w[ok]))
            for N in NS:
                if f"P{N}" in x:
                    row[f"P{N}"] = float(np.average(x.loc[ok, f"P{N}"], weights=w[ok]))
        rows.append(row)
    tab = pd.DataFrame(rows)
    # Monte Carlo ruin, pooled over every EA and series of the scope
    mc = []
    keys = pd.DataFrame([k for k in rs], columns=["venue", "sym", "iv", "src", "cls", "ea", "config"])
    keys["scope"] = np.where(keys["cls"].isin(MT5_ND), "mt5_nd", keys["cls"])
    for (scope, src, cfg), kk in keys.groupby(["scope", "src", "config"]):
        arr = [rs[tuple(k)] for k in kk[["venue", "sym", "iv", "src", "cls", "ea", "config"]].itertuples(index=False)]
        if cfg == "base_Rtp":
            a = np.concatenate(arr)
            p50, pb, _ = S.mc_martingale(a[:, 0], a[:, 1], seed=1)
            mc.append(dict(scope=scope, src=src, config="martingale_mc", P_ruin50=p50, P_below=pb, trades=len(a)))
            p50, pb, _ = S.mc_ruin(0.01 * a[:, 0], seed=1)
            mc.append(dict(scope=scope, src=src, config="base_R_mc", P_ruin50=p50, P_below=pb, trades=len(a)))
            continue
        f = np.concatenate(arr)
        p50, pb, _ = S.mc_ruin(f, seed=1)
        mc.append(dict(scope=scope, src=src, config=cfg, P_ruin50=p50, P_below=pb, trades=len(f)))
    mc = pd.DataFrame(mc)
    tab = tab.merge(mc, on=["scope", "src", "config"], how="left")
    return tab, keys


def report(out: Path):
    rng = np.random.default_rng(11)
    t, g, r, metas, rs, cv = load_parts(out)
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 500)
    pd.set_option("display.max_columns", 60)
    dropped = metas[metas.get("dropped", pd.Series(False, index=metas.index)).fillna(False).astype(bool)]
    dropped = dropped[dropped["src"] == "real"]
    dropped[["venue", "sym", "iv", "cls", "cost_atr"]].to_csv(out / "dropped.csv", index=False)
    print(f"dropped (cost > 0.5 ATR): {len(dropped)} series\n{dropped[['sym', 'iv', 'cost_atr']].round(2).to_string(index=False)}")
    prim, sec = mode_s_tables(t, rng)
    prim.to_csv(out / "mode_s_primary.csv", index=False)
    sec.to_csv(out / "mode_s_cells.csv", index=False)
    cols = ["ea", "n", "R", "lo", "hi", "p", "R_before", "R_after", "iid_R", "garch_R", "coin_R", "rev_R",
            "P1", "iid_P1", "P4", "iid_P4", "garch_P4", "coin_P4", "P10", "iid_P10", "garch_P10", "passes_rules", "bh", "PASSES"]
    print("\nMODE S PRIMARY (MT5 non-Deriv, 15m-1d pooled)\n" + prim[cols].round(4).to_string(index=False))
    print("1/(N+1):", {N: round(1 / (N + 1), 3) for N in NS})
    leaf = sec[sec["iv"] != "all"]
    print(f"\nsecondary cells tried: {len(leaf)}; passing every rule: {int(leaf['passes_rules'].sum())}; after BH: {int(leaf['PASSES'].sum())}")
    print(leaf[leaf["passes_rules"]][["ea", "cls", "iv", "n", "R", "lo", "p", "R_before", "R_after", "iid_R", "garch_R",
                                      "coin_R", "P4", "iid_P4", "bh"]].round(3).to_string(index=False))
    pooled_cls = sec[sec["iv"] == "all"]
    print("\nMODE S by class (all timeframes), real R and walks\n" +
          pooled_cls.pivot(index="ea", columns="cls", values="R").round(3).to_string())
    print(pooled_cls.pivot(index="ea", columns="cls", values="iid_R").round(3).to_string())
    au = author_tables(t, g, rng)
    au.to_csv(out / "author_cells.csv", index=False)
    print("\nAUTHOR CELLS\n" + au.round(3).to_string(index=False))
    gp, gc, gt = mode_g_tables(g)
    gp.to_csv(out / "mode_g_pooled.csv", index=False)
    gc.to_csv(out / "mode_g_class.csv", index=False)
    gt.to_csv(out / "mode_g_tf.csv", index=False)
    print("\nMODE G (risk 1%, leverage 1:100), MT5 non-Deriv pooled: medians across series\n" +
          gp[gp["scope"] == "mt5_nd"].round(3).to_string(index=False))
    print("\nMODE G by class\n" + gp[gp["scope"] != "mt5_nd"].round(3).to_string(index=False))
    rt, _ = mode_r_tables(r, rs)
    rt.to_csv(out / "mode_r.csv", index=False)
    if len(rt):
        print("\nMODE R (all EAs pooled)\n" + rt[rt["scope"] == "mt5_nd"].round(4).to_string(index=False))
        print(rt[rt["scope"] != "mt5_nd"].round(4).to_string(index=False))
        # the interaction test: a factor's change in R on real against the walks'
        b = rt.set_index(["scope", "src", "config"])["R"]
        rows = []
        for (scope, src, cfg), v in b.items():
            if cfg in ("base", "grid", "grid_eq20") or not np.isfinite(v):
                continue
            base = b.get((scope, src, "base"), np.nan)
            rows.append(dict(scope=scope, src=src, config=cfg, dR=v - base))
        d = pd.DataFrame(rows).pivot_table(index=["scope", "config"], columns="src", values="dR").reset_index()
        if {"real", "walk", "garch"} <= set(d.columns):
            d["real_minus_walks"] = d["real"] - d[["walk", "garch"]].mean(1)
        d.to_csv(out / "mode_r_interaction.csv", index=False)
        print("\nMODE R: change in R against base, real vs walks\n" + d.round(4).to_string(index=False))
    # Mode R per EA, MT5 non-Deriv real, for the doc
    if len(r):
        rr = r[r["cls"].isin(MT5_ND)].copy()
        per = rr.groupby(["ea", "src", "config"]).apply(
            lambda x: pd.Series(dict(R=np.average(x["R"].fillna(0), weights=x["n"].fillna(0)) if x["n"].fillna(0).sum() else np.nan,
                                     cagr_med=x["cagr"].median(), mdd_med=x["mdd"].median())), include_groups=False).reset_index()
        per.to_csv(out / "mode_r_per_ea.csv", index=False)
    summary = dict(primary=prim[cols].to_dict("records"), cells_tried=int(len(leaf)),
                   cells_pass_rules=int(leaf["passes_rules"].sum()), cells_pass_bh=int(leaf["PASSES"].sum()))
    (out / "summary.json").write_text(json.dumps(summary, default=float, indent=1))


# --------------------------------------------------------------------------------------- plots
def plot(out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    prim = pd.read_csv(out / "mode_s_primary.csv")
    sec = pd.read_csv(out / "mode_s_cells.csv")
    figdir = out / "plots"
    figdir.mkdir(exist_ok=True)
    ref = [1 / (N + 1) for N in NS]
    style = {"real": ("k", "-", "o"), "iid": ("#1f77b4", "--", "s"), "garch": ("#2ca02c", ":", "^"),
             "coin": ("#ff7f0e", "-.", "v"), "rev": ("#d62728", "--", "x")}
    # 1. P(N R) per EA, per timeframe, MT5 non-Deriv
    t, g, r, metas, rs, cv = load_parts(out)
    nd = t[t["cls"].isin(MT5_ND) & t["iv"].isin(E.TFS)]
    for ea in E.EAS:
        fig, axes = plt.subplots(1, 5, figsize=(24, 4.6), sharey=True)
        for ax, iv in zip(axes, list(E.TFS) + ["pooled"]):
            x = nd[nd["ea"] == ea]
            if iv != "pooled":
                x = x[x["iv"] == iv]
            for name, (src, kind) in {"real": ("real", "S"), "iid": ("walk", "S"), "garch": ("garch", "S"),
                                      "coin": ("real", "coin"), "rev": ("real", "rev")}.items():
                y = x[(x["src"] == src) & (x["kind"] == kind)]
                if len(y):
                    c_, ls, mk = style[name]
                    ax.plot(NS, [y[f"P{N}"].mean() for N in NS], color=c_, ls=ls, marker=mk,
                            label=f"{name}: R {y['R'].mean():+.3f} n {len(y)}")
            ax.plot(NS, ref, color="grey", lw=2, alpha=0.5, label="1/(N+1)")
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.set_title(f"{ea} {iv}")
            ax.set_xlabel("N (R)")
            ax.legend(fontsize=7)
        axes[0].set_ylabel("P(+N R before the stop)")
        fig.suptitle(f"{ea} - Mode S on MT5 non-Deriv: P(reach +N R before the coded stop), real vs iid and GARCH walks, "
                     "coin twin and reversed signal; mean R a trade after costs in the legend")
        fig.tight_layout()
        fig.savefig(figdir / f"pnr_{ea}.png", dpi=75)
        plt.close(fig)
    # 2. EA x timeframe x class heatmap of real - walk mean R
    leaf = sec[sec["iv"] != "all"].copy()
    leaf["edge"] = leaf["R"] - leaf[["iid_R", "garch_R"]].mean(1)
    fig, axes = plt.subplots(2, 5, figsize=(26, 13))
    vmax = 0.3
    for ax, cl in zip(axes.flat, CLASSES):
        m = leaf[leaf["cls"] == cl].pivot(index="ea", columns="iv", values="edge").reindex(index=list(E.EAS), columns=list(E.TFS))
        im = ax.imshow(m.to_numpy(float), cmap="RdBu", vmin=-vmax, vmax=vmax, aspect="auto")
        ax.set_xticks(range(4), E.TFS)
        ax.set_yticks(range(len(E.EAS)), E.EAS)
        for i in range(m.shape[0]):
            for j in range(m.shape[1]):
                v = m.iat[i, j]
                if np.isfinite(v):
                    star = "*" if leaf[(leaf["cls"] == cl) & (leaf["ea"] == m.index[i]) & (leaf["iv"] == m.columns[j])]["PASSES"].any() else ""
                    ax.text(j, i, f"{v:+.2f}{star}", ha="center", va="center", fontsize=7)
        ax.set_title(cl)
    fig.colorbar(im, ax=axes, shrink=0.6, label="mean R real - mean R walks (iid, GARCH avg)")
    fig.suptitle("Mode S: EA x timeframe x asset class, mean R a trade on real data minus matched walks (* passes every rule and BH)")
    fig.savefig(figdir / "heatmap_edge.png", dpi=70)
    plt.close(fig)
    # 3. Mode G equity: author cells and a few others, real vs walks side by side
    cells = [(k[0], k[1], k[2], k[4], k[5]) for k in cv if k[3] == "real"]
    cells = sorted(set(cells), key=lambda c: (c[3], c[1], c[2], c[4]))
    auth = [c for c in cells if (c[3], c[1], c[2]) in E.AUTHOR]
    other = [c for c in cells if (c[3], c[1], c[2]) not in E.AUTHOR and abs(c[4] - 0.01) < 1e-9
             and c[3] in ("BBRSI", "3MAF", "CEZLSMA", "NWERSIASF", "2MACDSTO", "LRCUTB")]
    for tag, cs in (("author", auth), ("others", other[:12])):
        if not cs:
            continue
        fig, axes = plt.subplots(len(cs), 3, figsize=(20, 2.6 * len(cs)), squeeze=False)
        for row, (venue, sym, iv, ea, risk) in enumerate(cs):
            for col, src in enumerate(("real", "walk", "garch")):
                ax = axes[row, col]
                s = cv.get((venue, sym, iv, src, ea, risk))
                if s is None or not len(s):
                    ax.set_axis_off()
                    continue
                ax.plot(s.index, s.to_numpy(), color={"real": "k", "walk": "#1f77b4", "garch": "#2ca02c"}[src], lw=1)
                pk = s.cummax()
                dd = (pk - s) / pk
                j = dd.idxmax()
                ax.fill_between(s.index, s.to_numpy(), pk.to_numpy(), color="red", alpha=0.15)
                ax.axvline(j, color="red", lw=0.8, ls=":")
                ax.set_yscale("log")
                ax.axhline(10_000, color="grey", lw=0.6)
                ax.set_title(f"{ea} {sym} {iv} risk {risk:.2%} - {src}: final {s.iloc[-1]:,.0f}, max DD {dd.max():.0%}", fontsize=8)
        fig.suptitle("Mode G: the author's defaults (grid, no stop) as a 10,000 account at 1:100, real data against matched "
                     "walks; red shading: drawdown from the peak, dotted: the deepest point", fontsize=11)
        fig.tight_layout()
        fig.savefig(figdir / f"mode_g_equity_{tag}.png", dpi=70)
        plt.close(fig)
    # 4. Mode R: factor bars, ruin by sizing, equity fans
    if (out / "mode_r.csv").exists():
        rt = pd.read_csv(out / "mode_r.csv")
        x = rt[rt["scope"] == "mt5_nd"]
        cfgs = [c for c in ("base", "sl_swing", "sl_ar", "sl_mr", "sl_fixed", "trail_0", "trail_25", "trail_50", "trail_75",
                            "size_equity", "size_fixed", "size_min_amount", "martingale", "eq_limit5", "spread_limit",
                            "multi_open", "grid", "grid_eq20") if c in set(x["config"])]
        fig, axes = plt.subplots(2, 1, figsize=(18, 9), sharex=True)
        w = 0.27
        for i, src in enumerate(("real", "walk", "garch")):
            y = x[x["src"] == src].set_index("config").reindex(cfgs)
            axes[0].bar(np.arange(len(cfgs)) + (i - 1) * w, y["R"], w, label=src)
            axes[1].bar(np.arange(len(cfgs)) + (i - 1) * w, y["mdd_med"], w, label=src)
        axes[0].axhline(0, color="k", lw=0.6)
        axes[0].set_ylabel("mean R a trade")
        axes[1].set_ylabel("median max drawdown (account)")
        axes[1].set_xticks(np.arange(len(cfgs)), cfgs, rotation=40, ha="right")
        axes[0].legend()
        fig.suptitle("Mode R: the risk layer one factor at a time on every EA's signals (MT5 non-Deriv, all EAs pooled): "
                     "R moves the same way on walks - the layer reshapes risk, it does not create edge")
        fig.tight_layout()
        fig.savefig(figdir / "mode_r_factors.png", dpi=75)
        plt.close(fig)
        # ruin curves and fans from the pooled samples
        keys = pd.DataFrame([k for k in rs], columns=["venue", "sym", "iv", "src", "cls", "ea", "config"])
        keys = keys[keys["cls"].isin(MT5_ND)]
        fig, axes = plt.subplots(1, 3, figsize=(22, 5.5))
        for ax, src in zip(axes, ("real", "walk", "garch")):
            for cfg_, col in (("base", "k"), ("size_fixed", "#1f77b4"), ("size_min_amount", "#2ca02c"), ("martingale", "#d62728")):
                kk = keys[(keys["src"] == src) & (keys["config"] == ("base_Rtp" if cfg_ == "martingale" else cfg_))]
                if not len(kk):
                    continue
                arr = np.concatenate([rs[tuple(k)] for k in kk.itertuples(index=False)])
                if cfg_ == "martingale":
                    _, _, paths = S.mc_martingale(arr[:, 0], arr[:, 1], seed=2, paths=2000)
                    paths_full = _mart_paths(arr, 2000, 1000)
                else:
                    paths_full = _paths(arr, 2000, 1000)
                ruin = (np.minimum.accumulate(paths_full, axis=1) <= 0.5).mean(0)
                ax.plot(np.arange(1, 1001), ruin, color=col, label=cfg_)
            ax.set_title(f"{src}: P(account has touched -50%) by trade number")
            ax.set_xlabel("trades")
            ax.legend()
        fig.suptitle("Mode R: risk of ruin by sizing mode, resampled trade sequences (MT5 non-Deriv, all EAs)")
        fig.tight_layout()
        fig.savefig(figdir / "mode_r_ruin.png", dpi=75)
        plt.close(fig)
        fig, axes = plt.subplots(2, 3, figsize=(22, 9), sharey="row")
        for j, src in enumerate(("real", "walk", "garch")):
            kk = keys[(keys["src"] == src) & (keys["config"] == "base_Rtp")]
            if not len(kk):
                continue
            arr = np.concatenate([rs[tuple(k)] for k in kk.itertuples(index=False)])
            for i, (name, p) in enumerate((("default 1%", _paths(arr, 300, 1000)), ("martingale", _mart_paths(arr, 300, 1000)))):
                ax = axes[i, j]
                ax.plot(p[:100].T, color="grey", alpha=0.15, lw=0.6)
                for q, ls in ((0.05, ":"), (0.5, "-"), (0.95, ":")):
                    ax.plot(np.quantile(p, q, axis=0), color="k", ls=ls)
                ax.set_yscale("log")
                ax.axhline(1, color="red", lw=0.6)
                ax.set_title(f"{src} - {name}")
        fig.suptitle("Mode R: equity fans (300 resampled 1,000-trade sequences, start = 1): default 1% risk vs the "
                     "martingale option; median and 5/95% lines")
        fig.tight_layout()
        fig.savefig(figdir / "mode_r_fans.png", dpi=75)
        plt.close(fig)
    gallery(out, prim, figdir)
    print("plots written", flush=True)


def _paths(arr, paths, n, seed=3):
    a = arr[:, 0] if arr.ndim == 2 else arr
    if arr.ndim == 2:
        a = 0.01 * a
    rng = np.random.default_rng(seed)
    f = a[rng.integers(0, len(a), (paths, n))]
    return np.cumprod(1 + np.clip(f, -1, None), axis=1)


def _mart_paths(arr, paths, n, seed=3):
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), (paths, n))
    eq = np.ones(paths)
    risk = np.full(paths, 0.01)
    out = np.empty((paths, n))
    for i in range(n):
        R, q = arr[idx[:, i], 0], arr[idx[:, i], 1]
        pnl = risk * eq * R
        prev = eq
        eq = np.maximum(eq + pnl, 0)
        nxt = np.where(q > 0, 2 * risk * prev / np.maximum(eq, 1e-12) / np.where(q > 0, q, 1), 0.0)
        risk = np.where(pnl < 0, np.minimum(nxt, 0.04), 0.01)
        out[:, i] = eq
    return out


def gallery(out, prim, figdir):
    """6 winners and 6 losers of the two best EAs (by primary R) on real charts with their indicators."""
    import matplotlib.pyplot as plt
    best = prim.sort_values("R", ascending=False)["ea"].tolist()
    best = [e for e in best if e != "COT1"][:2]
    t, *_ = load_parts(out)
    rng = np.random.default_rng(9)
    for ea in best:
        x = t[(t["ea"] == ea) & (t["src"] == "real") & (t["kind"] == "S") & t["cls"].isin(MT5_ND) & t["iv"].isin(("1h", "4h"))]
        for tag, sub in (("winners", x[x["R"] > 0]), ("losers", x[x["R"] <= 0])):
            if not len(sub):
                continue
            pick = sub.iloc[rng.choice(len(sub), min(6, len(sub)), replace=False)]
            fig, axes = plt.subplots(2, 3, figsize=(22, 10))
            for ax, (_, r) in zip(axes.flat, pick.iterrows()):
                d = E.load(r["venue"], r["sym"], r["iv"])
                df = d["df"]
                o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
                b = E.Bars(o, h, l, c, df["ts"].to_numpy(np.int64), d["point"], d["day_ts"])
                sig = E.SIGNALS[ea](b)
                ti, e, kx = int(r["t"]), int(r["e"]), int(r["kx"])
                j1 = min(len(c) - 1, kx // 4 + 15)
                i0 = max(0, ti - 50)
                xs = np.arange(i0, j1 + 1)
                up = c[i0:j1 + 1] >= o[i0:j1 + 1]
                ax.vlines(xs, l[i0:j1 + 1], h[i0:j1 + 1], color="#555", lw=0.6)
                ax.bar(xs[up], (c - o)[i0:j1 + 1][up], bottom=o[i0:j1 + 1][up], color="#2a9d8f", width=0.7)
                ax.bar(xs[~up], (c - o)[i0:j1 + 1][~up], bottom=o[i0:j1 + 1][~up], color="#e76f51", width=0.7)
                for name, arr in sig["ind"].items():
                    a = np.asarray(arr, float)[i0:j1 + 1]
                    if np.isfinite(a).any() and np.nanmedian(np.abs(a - c[i0:j1 + 1])) < 0.2 * np.nanmedian(c[i0:j1 + 1]):
                        ax.plot(xs, a, lw=1, label=name)
                s = int(r["side"])
                pin = float(r["px"])
                sl = pin - s * float(r["r0"])
                ax.hlines(sl, e, kx // 4, colors="red", lw=1.2, label="SL")
                if r["tpd"] > 0:
                    ax.hlines(pin + s * float(r["tpd"]), e, kx // 4, colors="green", lw=1.2, label="TP")
                ax.plot([e], [pin], "k^" if s > 0 else "kv", ms=10)
                exit_px = pin + s * float(r["R"]) * float(r["r0"])
                ax.plot([kx // 4], [exit_px], "kx", ms=10)
                ax.legend(fontsize=6, loc="best")
                ax.set_title(f"{ea} {r['sym']} {r['iv']} {'long' if s > 0 else 'short'} {pd.Timestamp(int(r['ts']), unit='s'):%Y-%m-%d %H:%M}"
                             f" -> {r['R']:+.2f}R ({r['why']})", fontsize=9)
            fig.suptitle(f"{ea} Mode S {tag} (1h/4h, MT5 non-Deriv): entry (triangle) at the next open, coded SL (red) and TP "
                         "(green), exit (x, net R); price-scale indicators drawn", fontsize=11)
            fig.tight_layout()
            fig.savefig(figdir / f"gallery_{ea}_{tag}.png", dpi=70)
            plt.close(fig)
