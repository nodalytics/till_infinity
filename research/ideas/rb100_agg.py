"""Tables, verdicts and figures for rb100.py (MODE=agg | plot)."""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

import rb100 as R

OUT = R.OUT
IMG = Path(os.environ.get("IMG", OUT / "img"))
DRAWS = 2000


def load():
    t = pd.concat([pd.read_pickle(f) for f in sorted(glob.glob(str(OUT / "parts" / "*.pkl")))], ignore_index=True)
    sp = t["iv"].map(R.split_of)
    t["period"] = np.where(t["ts"] >= sp, "conf", "disc")
    t["day"] = t["ts"] // 86400
    # halves of each confirmation period, at the midpoint of its own calendar
    t["half"] = ""
    for (inst, iv), g in t[t["period"] == "conf"].groupby(["inst", "iv"]):
        mid = (R.split_of(iv) + g["ts"].max()) / 2
        t.loc[g.index, "half"] = np.where(g["ts"] < mid, "h1", "h2")
    return t


def boot(day, x, seed=0, draws=DRAWS):
    """Day bootstrap of a mean: (lo 5%, hi 95%, one-sided p of mean <= 0)."""
    d = pd.DataFrame({"d": day, "x": x}).dropna()
    if len(d) < 2:
        return np.nan, np.nan, np.nan
    g = d.groupby("d")["x"].agg(["sum", "count"])
    s, c = g["sum"].to_numpy(), g["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(s), (draws, len(s)))
    m = s[idx].sum(1) / c[idx].sum(1)
    return float(np.percentile(m, 5)), float(np.percentile(m, 95)), float((m <= 0).mean())


def boot_means(day, x, seed, draws=DRAWS):
    d = pd.DataFrame({"d": day, "x": x}).dropna()
    g = d.groupby("d")["x"].agg(["sum", "count"])
    s, c = g["sum"].to_numpy(), g["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(s), (draws, len(s)))
    return s[idx].sum(1) / c[idx].sum(1)


def bh(p, q=0.10):
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
    k = np.flatnonzero(passed).max() + 1 if passed.any() else 0
    sel = np.zeros(m, bool)
    sel[o[:k]] = True
    out[np.flatnonzero(ok)] = sel
    return out


def tick_window(t):
    """Tick cells compare like with like: every source restricted to dates the real ticks cover."""
    r = t[(t["src"] == "real") & t["R_tick"].notna()]
    lo = {inst: g["ts"].min() for inst, g in r.groupby("inst")}
    hi = {inst: g["ts"].max() for inst, g in r.groupby("inst")}
    return lo, hi


def cells(t):
    """One row per inst x rule x exit x iv x period x fill, with every source."""
    lo, hi = tick_window(t)
    rows = []
    keys = ["inst", "rule", "exit", "iv", "period"]
    for k, g in t.groupby(keys):
        inst = k[0]
        for fill in ("bar", "tick"):
            col, mfe = (f"R_{fill}", f"mfe_{fill}")
            gg = g[g[col].notna()]
            if fill == "tick" and inst in lo:
                gg = gg[(gg["ts"] >= lo[inst]) & (gg["ts"] <= hi[inst])]
            if fill == "tick" and inst not in lo:
                continue
            row = dict(zip(keys, k), fill=fill)
            for src in ("real",) + R.NULLS:
                s = gg[gg["src"] == src]
                row[f"n_{src}"] = len(s)
                row[f"R_{src}"] = float(s[col].mean()) if len(s) else np.nan
                row[f"Rns_{src}"] = float(s[f"{col}_noswap"].mean()) if len(s) else np.nan
                if src != "real" and len(s):
                    sm = s.groupby("seed")[col].mean()
                    row[f"sd_{src}"] = float(sm.std()) if len(sm) > 1 else np.nan
                for N in (1, 2, 4, 10):
                    row[f"P{N}_{src}"] = float((s[mfe] >= N).mean()) if len(s) else np.nan
            s = gg[gg["src"] == "real"]
            if len(s) >= 2:
                row["lo"], row["hi"], row["p"] = boot(s["day"], s[col], 1)
                for hname in ("h1", "h2"):
                    row[f"R_{hname}"] = float(s.loc[s["half"] == hname, col].mean()) if (s["half"] == hname).any() else np.nan
                if fill == "tick":
                    row["twin"] = float(s["twin"].mean())
                    row["jump_stop_share"] = float(s["jump"].mean())
            rows.append(row)
    return pd.DataFrame(rows)


def diff_ci(t, inst, rule, ex, iv, period, fill, null="rbsim"):
    lo, hi = tick_window(t)
    col = f"R_{fill}"
    g = t[(t["inst"] == inst) & (t["rule"] == rule) & (t["exit"] == ex) & (t["iv"] == iv) & (t["period"] == period) & t[col].notna()]
    if fill == "tick":
        g = g[(g["ts"] >= lo[inst]) & (g["ts"] <= hi[inst])]
    r, s = g[g["src"] == "real"], g[g["src"] == null]
    if len(r) < 2 or len(s) < 2:
        return np.nan, np.nan, np.nan
    d = boot_means(r["day"], r[col], 3) - boot_means(s["seed"] * 100000 + s["day"], s[col], 4)
    return float(np.percentile(d, 5)), float(np.percentile(d, 95)), float(d.mean())


def agg():
    t = load()
    t.to_pickle(OUT / "trades_all.pkl.gz")
    C = cells(t)
    conf = C[(C["period"] == "conf") & (C["n_real"] >= 30)].copy()
    conf["bh"] = False
    for fill in ("bar", "tick"):
        m = conf["fill"] == fill
        conf.loc[m, "bh"] = bh(conf.loc[m, "p"].to_numpy())
    conf["above_walks"] = (conf["R_real"] > conf["R_iid"]) & (conf["R_real"] > conf["R_garch"])
    conf["above_sim"] = conf["R_real"] > conf["R_rbsim"] + conf["sd_rbsim"].fillna(0)
    conf["pass"] = ((conf["R_real"] > 0) & (conf["lo"] > 0) & conf["bh"] & (conf["R_h1"] > 0) & (conf["R_h2"] > 0)
                    & conf["above_walks"] & conf["above_sim"])
    C = C.merge(conf[["inst", "rule", "exit", "iv", "period", "fill", "bh", "above_walks", "above_sim", "pass"]],
                on=["inst", "rule", "exit", "iv", "period", "fill"], how="left")
    C.to_csv(OUT / "cells.csv", index=False)
    # the primary
    P = C[(C["inst"] == "RB100") & (C["rule"] == "bb") & (C["exit"] == "st") & (C["iv"] == "15m") & (C["period"] == "conf")]
    prim = {}
    for _, r in P.iterrows():
        d = diff_ci(t, "RB100", "bb", "st", "15m", "conf", r["fill"])
        prim[r["fill"]] = dict(n=int(r["n_real"]), R=r["R_real"], lo=r["lo"], hi=r["hi"], h1=r["R_h1"], h2=r["R_h2"],
                               R_noswap=r["Rns_real"], rbsim=r["R_rbsim"], rbsim_sd=r["sd_rbsim"], iid=r["R_iid"],
                               garch=r["R_garch"], twin=r.get("twin"), real_minus_rbsim_ci=d,
                               P=[r[f"P{N}_real"] for N in (1, 2, 4, 10)], P_rbsim=[r[f"P{N}_rbsim"] for N in (1, 2, 4, 10)],
                               jump_stop_share=r.get("jump_stop_share"))
    tk = prim.get("tick", {})
    earns = bool(tk and tk["R"] > 0 and tk["lo"] > 0 and tk["h1"] > 0 and tk["h2"] > 0)
    d = tk.get("real_minus_rbsim_ci", (np.nan, np.nan, np.nan))
    explained = bool(d[0] <= 0 <= d[1])
    br = prim.get("bar", {})
    tradeable = bool(earns and br and np.sign(br["R"]) == np.sign(tk["R"]))
    verdict = dict(primary=prim, earns=earns, explained_by_generator=explained, tradeable=tradeable,
                   n_conf_cells=int(len(conf)), bh_tick=int(conf.loc[conf["fill"] == "tick", "bh"].sum()),
                   bh_bar=int(conf.loc[conf["fill"] == "bar", "bh"].sum()), passes=int(conf["pass"].sum()),
                   passing=conf.loc[conf["pass"], ["inst", "rule", "exit", "iv", "fill", "n_real", "R_real", "lo", "R_rbsim"]].to_dict("records"))
    # diff CIs for every confirmation cell with n >= 30 (bar and tick)
    dd = []
    for _, r in conf.iterrows():
        lo_, hi_, m_ = diff_ci(t, r["inst"], r["rule"], r["exit"], r["iv"], "conf", r["fill"])
        dd.append(dict(inst=r["inst"], rule=r["rule"], exit=r["exit"], iv=r["iv"], fill=r["fill"], diff=m_, diff_lo=lo_, diff_hi=hi_))
    D = pd.DataFrame(dd)
    D.to_csv(OUT / "real_minus_sim.csv", index=False)
    verdict["cells_sim_outside"] = int(((D["diff_lo"] > 0) | (D["diff_hi"] < 0)).sum())
    verdict["cells_sim_tested"] = int(len(D))
    (OUT / "verdict.json").write_text(json.dumps(verdict, indent=1, default=float))
    print(json.dumps(verdict, indent=1, default=float))
    # stop fills: walked stops against jumped stops, real tick replay
    s = t[(t["src"] == "real") & (t["how"] == "stop")]
    js = s.groupby(["inst", "jump"])["R_tick_noswap"].describe()
    js.to_csv(OUT / "stop_fills.csv")
    print(js)


# -------------------------------------------------------------------------------------------- plots

def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.dpi": 110, "axes.grid": True, "grid.alpha": 0.3, "font.size": 9})
    return plt


COL = {"real": "#1f4e79", "rbsim": "#c55a11", "iid": "#7f7f7f", "garch": "#a5a5a5"}


def plot_char(plt):
    for inst in R.INST:
        f = OUT / f"char_segments_{inst}.pkl"
        if not f.exists():
            continue
        S = pd.read_pickle(f)
        Sm = pd.read_pickle(OUT / f"sim_segments_{inst}.pkl") if (OUT / f"sim_segments_{inst}.pkl").exists() else None
        fig, ax = plt.subplots(1, 4, figsize=(15, 3.4))
        for name, g, c in (("real discovery", S[S["period"] == "discovery"], COL["real"]),
                           ("real confirmation", S[S["period"] == "confirmation"], "#5b9bd5")):
            ax[0].hist(g["W_exact"].dropna(), bins=np.arange(0, 130, 3), density=True, histtype="step", color=c, label=name, lw=1.4)
            ax[1].hist(np.abs(g["jump"]), bins=np.arange(0, 400, 8), density=True, histtype="step", color=c, lw=1.4)
            ax[2].hist(g["dur_s"] / 60, bins=np.arange(0, 400, 8), density=True, histtype="step", color=c, lw=1.4)
        if Sm is not None:
            ax[0].hist(Sm["W_exact"].dropna(), bins=np.arange(0, 130, 3), density=True, histtype="step", color=COL["rbsim"], label="fitted simulator", lw=1.4, ls="--")
            ax[1].hist(np.abs(Sm["jump"]), bins=np.arange(0, 400, 8), density=True, histtype="step", color=COL["rbsim"], lw=1.4, ls="--")
            ax[2].hist(Sm["n"] / 60, bins=np.arange(0, 400, 8), density=True, histtype="step", color=COL["rbsim"], lw=1.4, ls="--")
        ax[0].set_title("range width (exactly observed), price units")
        ax[1].set_title("break size |jump|, price units")
        ax[2].set_title("range lifetime, minutes")
        ax[0].legend(fontsize=7)
        ct = pd.crosstab(np.sign(S["prev_jump"]), S["cont"])
        lab = ["landing at the\nnew range's far edge", "next break continues\nthe last one", "next break reverses"]
        vals = [S["land_at_edge"].mean(), S["cont"].mean(), 1 - S["cont"].mean()]
        ax[3].bar(lab, vals, color=[COL["real"], "#5b9bd5", "#9dc3e6"])
        if Sm is not None:
            ax[3].scatter(lab, [Sm["land_at_edge"].mean(), Sm["cont"].mean(), 1 - Sm["cont"].mean()], color=COL["rbsim"], zorder=3, label="simulator")
            ax[3].legend(fontsize=7)
        ax[3].set_ylim(0, 1.05)
        ax[3].tick_params(axis="x", labelsize=7)
        ax[3].set_title("after a break")
        fig.suptitle(f"{R.INST[inst][0]}: the generator from its own ticks (discovery = before 2025-10-01)")
        fig.tight_layout()
        fig.savefig(IMG / f"generator_{inst}.png")
        plt.close(fig)
    # an example window of ticks with its ranges
    ms, bid, _ = R.load_ticks("RB100", lo=R.SPLIT_T, hi=R.SPLIT_T + 86400)
    if len(ms):
        k = slice(0, 6 * 3600)
        x = (ms[k] - ms[0]) / 3.6e6
        fig, ax = plt.subplots(figsize=(12, 3.6))
        ax.plot(x, bid[k], lw=0.6, color=COL["real"])
        S = R.segments(bid[k])
        for _, s in S.iterrows():
            seg = bid[k][s["i0"]:s["i1"] + 1]
            ax.fill_between([x[s["i0"]], x[s["i1"]]], seg.min(), seg.max(), color="#c55a11", alpha=0.12, lw=0)
        J = np.flatnonzero(np.abs(np.diff(bid[k])) >= R.JUMP)
        ax.scatter(x[J + 1], bid[k][J + 1], s=12, color="#c00000", zorder=3, label="break (a single jump tick)")
        ax.set_xlabel("hours from 2025-10-01 00:00 UTC")
        ax.set_ylabel("bid")
        ax.legend(fontsize=8)
        ax.set_title("Range Break 100, six hours of 1-second ticks: ranges (shaded) and the jumps between them")
        fig.tight_layout()
        fig.savefig(IMG / "ticks_example.png")
        plt.close(fig)


def plot_vr(plt):
    c = json.loads((OUT / "char.json").read_text())
    v = json.loads((OUT / "sim_validate.json").read_text()) if (OUT / "sim_validate.json").exists() else {}
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.4))
    for i, inst in enumerate(R.INST):
        if inst not in c or "vr" not in c[inst]:
            continue
        for name, ls in (("discovery", "-"), ("confirmation", ":")):
            d = c[inst]["vr"][name]
            ax[i].plot([int(k) for k in d], list(d.values()), ls, color=COL["real"], marker="o", ms=3, label=f"real {name}")
        if inst in v:
            d = v[inst]["vr"]
            ax[i].plot([int(k) for k in d], list(d.values()), "--", color=COL["rbsim"], marker="s", ms=3, label="fitted simulator")
        ax[i].axhline(1, color="k", lw=0.6)
        ax[i].set_xscale("log")
        ax[i].set_xlabel("horizon, seconds")
        ax[i].set_title(f"{inst}: variance ratio against the 1-second step")
        ax[i].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(IMG / "variance_ratio.png")
    plt.close(fig)


def plot_years(plt):
    c = json.loads((OUT / "char.json").read_text())
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.2))
    for inst, mk in (("RB100", "o"), ("RB200", "s")):
        if inst not in c or "by_year" not in c[inst]:
            continue
        y = pd.DataFrame(c[inst]["by_year"])
        g = y[y["iv"] == "1h"]
        if not len(g):
            continue
        ax[0].plot(g["year"], g["range_med"], marker=mk, label=inst)
        ax[1].plot(g["year"], g["sd_dc"], marker=mk, label=inst)
        ax[2].plot(g["year"], g["kurt"], marker=mk, label=inst)
    for a, tt in zip(ax, ("1h bar range, median (price units)", "1h close-to-close sd", "1h close-change kurtosis")):
        a.set_title(tt)
        a.legend(fontsize=7)
    fig.suptitle("Stability: the generator in price units by year (the 2024-01-01 and 2025-10-01 splits fall inside a flat line)")
    fig.tight_layout()
    fig.savefig(IMG / "by_year.png")
    plt.close(fig)


def plot_primary(plt):
    C = pd.read_csv(OUT / "cells.csv")
    fig, ax = plt.subplots(1, 2, figsize=(12, 3.8))
    for i, inst in enumerate(R.INST):
        g = C[(C["inst"] == inst) & (C["period"] == "conf") & (C["iv"] == "15m")]
        if not len(g):
            continue
        labs = []
        x = 0
        for rule, ex in [("bb", "st"), ("z50", "st"), ("kelt", "st"), ("ibs1", "st"), ("R2", "X2"), ("R2", "TR"), ("R5s", "X2"), ("R5s", "TR")]:
            for fill, off in (("bar", -0.2), ("tick", 0.2)):
                r = g[(g["rule"] == rule) & (g["exit"] == ex) & (g["fill"] == fill)]
                if not len(r):
                    continue
                r = r.iloc[0]
                hatch = "" if fill == "bar" else "//"
                ax[i].bar(x + off - 0.1, r["R_real"], 0.2, color=COL["real"], hatch=hatch, label="real" if x == 0 and fill == "bar" else None)
                ax[i].bar(x + off + 0.1, r["R_rbsim"], 0.2, color=COL["rbsim"], hatch=hatch, label="fitted simulator" if x == 0 and fill == "bar" else None)
                if np.isfinite(r.get("lo", np.nan)):
                    ax[i].plot([x + off - 0.1] * 2, [r["lo"], r["hi"]], color="k", lw=1)
            labs.append(f"{rule}\n{ex}")
            x += 1
        ax[i].set_xticks(range(len(labs)), labs, fontsize=7)
        ax[i].axhline(0, color="k", lw=0.7)
        ax[i].set_ylabel("mean R a trade, net of spread and swap")
        ax[i].set_title(f"{inst} 15m, confirmation: bar fill (plain) and tick fill (hatched)")
        ax[i].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(IMG / "bar_vs_tick_15m.png")
    plt.close(fig)


def plot_heat(plt):
    C = pd.read_csv(OUT / "cells.csv")
    for fill in ("bar", "tick"):
        fig, ax = plt.subplots(1, 4, figsize=(15, 4.2))
        k = 0
        for inst in R.INST:
            for src in ("real", "rbsim"):
                g = C[(C["inst"] == inst) & (C["period"] == "conf") & (C["fill"] == fill)]
                if not len(g):
                    k += 1
                    continue
                g = g.assign(cell=g["rule"] + " " + g["exit"])
                m = g.pivot_table(index="cell", columns="iv", values=f"R_{src}")
                m = m.reindex(columns=[c for c in R.IVS if c in m.columns])
                im = ax[k].imshow(np.clip(m.to_numpy(float), -3, 3), cmap="RdBu", vmin=-3, vmax=3, aspect="auto")
                ax[k].set_xticks(range(m.shape[1]), m.columns)
                ax[k].set_yticks(range(m.shape[0]), m.index, fontsize=7)
                for (a, b), v in np.ndenumerate(m.to_numpy(float)):
                    if np.isfinite(v):
                        ax[k].text(b, a, f"{v:+.2f}", ha="center", va="center", fontsize=6)
                ax[k].set_title(f"{inst} {'real' if src == 'real' else 'fitted simulator'}")
                ax[k].grid(False)
                k += 1
        fig.colorbar(im, ax=ax, shrink=0.7, label="mean R (clipped at +/-3)")
        fig.suptitle(f"Every rule, confirmation, {fill} fill, net of spread and swap: real against the fitted simulator")
        fig.savefig(IMG / f"heat_{fill}.png", bbox_inches="tight")
        plt.close(fig)


def plot_pnr(plt):
    C = pd.read_csv(OUT / "cells.csv")
    Ns = (1, 2, 4, 10)
    fig, ax = plt.subplots(1, 4, figsize=(15, 3.4))
    for i, (rule, ex) in enumerate((("bb", "st"), ("ibs1", "st"), ("R2", "X2"), ("R5s", "X2"))):
        g = C[(C["inst"] == "RB100") & (C["rule"] == rule) & (C["exit"] == ex) & (C["period"] == "conf")]
        for fill, ls in (("bar", "-"), ("tick", "--")):
            r = g[g["fill"] == fill]
            if not len(r):
                continue
            w = r["n_real"].to_numpy(float)
            for src in ("real", "rbsim", "iid"):
                y = [np.nansum(r[f"P{N}_{src}"] * (r[f"n_{src}"])) / max(1, r[f"n_{src}"].sum()) for N in Ns]
                ax[i].plot(Ns, y, ls, marker="o", ms=3, color=COL[src], label=f"{src} {fill}")
        ax[i].plot(Ns, [1 / (N + 1) for N in Ns], "k:", label="1/(N+1)")
        ax[i].set_xscale("log")
        ax[i].set_yscale("log")
        ax[i].set_xticks(Ns, [str(n) for n in Ns])
        ax[i].set_title(f"RB100 {rule} ({ex} trades), all timeframes")
        ax[i].set_xlabel("N")
        if i == 0:
            ax[i].set_ylabel("P(+N R before -1R), gross")
            ax[i].legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(IMG / "pnr.png")
    plt.close(fig)


def plot_stops(plt):
    t = pd.read_pickle(OUT / "trades_all.pkl.gz")
    s = t[(t["how"] == "stop") & t["R_tick_noswap"].notna() & (t["exit"].isin(["st", "X2"]))]
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.4))
    for i, src in enumerate(("real", "rbsim")):
        g = s[(s["src"] == src) & (s["inst"] == "RB100")]
        for jump, c, lab in ((False, "#5b9bd5", "stop reached by +/-1 steps"), (True, "#c00000", "stop jumped by a break")):
            x = g.loc[g["jump"] == jump, "R_tick_noswap"].clip(-30, 2)
            if len(x):
                ax[i].hist(x, bins=np.arange(-30, 2.1, 0.5), color=c, alpha=0.6, label=f"{lab} ({len(x) / max(1, len(g)):.0%})")
        ax[i].axvline(-1, color="k", lw=0.8)
        ax[i].set_xlabel("R at the stop fill (tick replay, before swap); clipped at -30")
        ax[i].set_title(f"RB100 {'real ticks' if src == 'real' else 'fitted simulator'}: where a stop is filled")
        ax[i].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(IMG / "stop_fills.png")
    plt.close(fig)


def plot():
    IMG.mkdir(parents=True, exist_ok=True)
    plt = _plt()
    for fn in (plot_char, plot_vr, plot_years, plot_primary, plot_heat, plot_pnr, plot_stops):
        try:
            fn(plt)
            print("plotted", fn.__name__, flush=True)
        except Exception as e:  # noqa: BLE001
            print("plot failed", fn.__name__, repr(e), flush=True)
