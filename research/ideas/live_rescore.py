"""Rescore the live strategy records with the frozen keep/kill rule of `strategy-switching.md`.

The rule (frozen in `switch_rule.json`, applied unchanged): a repeated Wald SPRT of H0 mean R = 0
against H1 = +0.10R, alpha 0.05, beta 0.20, Gaussian with the running sd of all closes (1.0 until 20
have closed), on each strategy's full record in close order. LLR <= ln(0.2/0.95) = -1.56 kills (pauses);
LLR >= ln(0.8/0.05) = +2.77 confirms (keeps) or, once killed, resumes. Every crossing resets the LLR.

For each strategy: closes so far, mean R with a day-bootstrap 90% interval, the posterior P(mean R > 0)
(prior N(0, 0.10^2)), the SPRT's LLR and state now (keep / kill / undecided), the close and date of
each kill / confirm / resume, and its best rolling 10-close stretch against what a zero-edge strategy
of the same length produces. Writes `scorecard.csv`, `events.csv`, `traces.pkl` and the figures.

  CLOSES=.data/closes.json OUT=.data/live_rescore IMG=research/docs/img/live-rescore \
    python research/ideas/live_rescore.py

CLOSES takes the export, a journal .db, or several of them comma-separated (merged, each close once).
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import switch as S  # noqa: E402

A, B = math.log(0.8 / 0.05), math.log(0.2 / 0.95)  # +2.77 confirm / resume, -1.56 kill
MU1, BURN = 0.10, 20
POOLED_SD = 0.90  # sd of the pooled replayed production R (strategy-switching.md, 736,071 trades)
# the zero-edge hot-streak table of strategy-switching.md (lab, switch/out/hot.csv): best rolling
# 10-trade mean R, median and 95th percentile, (low, high) over its two zero-edge stream kinds
DOC_HOT10 = {30: ((0.30, 0.33), (0.81, 0.92)), 100: ((0.52, 0.59), (1.08, 1.23)),
             300: ((0.68, 0.81), (1.31, 1.48)), 1000: ((0.84, 1.01), (1.48, 1.74))}
MIN_LIVE = 25  # the frozen live table's floor; smaller records are scored and flagged
# a reading beside the rule, never the rule: a close the frozen R definition mis-sizes, at the R that
# convexity.md measured for it (thesis-only, profit +622.63 on a risk_money of 9.47 -> +65.7R; +0.703R)
CORRECTED = {"thesis-only": (65.0, 0.703)}  # strategy -> (closes above this R, the R they are read at)


def sprt_trace(x):
    """The repeated SPRT of `switch.states`, step by step. Per close: the LLR before any reset (the
    value that is compared with the boundaries), the event ('kill', 'confirm', 'resume', 'reset' or ''),
    the state after the close (True = on), and the one-shot LLR (no resets, for display)."""
    llr, k, mean, m2, on, cum = 0.0, 0, 0.0, 0.0, True, 0.0
    pre, ev, st, one = [], [], [], []
    for r in map(float, x):
        k += 1
        d = r - mean
        mean += d / k
        m2 += d * (r - mean)
        sd = max(math.sqrt(m2 / (k - 1)) if k >= BURN else 1.0, 1e-6)
        inc = MU1 / (sd * sd) * (r - MU1 / 2)
        llr += inc
        cum += inc
        pre.append(llr)
        one.append(cum)
        e = ""
        if on:
            if llr <= B:
                on, llr, e = False, 0.0, "kill"
            elif llr >= A:
                llr, e = 0.0, "confirm"
        else:
            if llr >= A:
                on, llr, e = True, 0.0, "resume"
            elif llr <= B:
                llr, e = 0.0, "reset"
        ev.append(e)
        st.append(on)
    return dict(llr_pre=np.array(pre), event=np.array(ev, dtype=object), on=np.array(st),
                llr_one=np.array(one), llr_now=llr, sd=sd)


def verdict(events, on):
    """keep / kill / undecided from the SPRT's decisions so far."""
    if not on:
        return "kill"
    dec = [e for e in events if e in ("confirm", "resume")]
    return "keep" if dec else "undecided"


def day_boot(x, day, rng, draws=4000):
    days = np.unique(day)
    idx = {d: np.flatnonzero(day == d) for d in days}
    out = np.empty(draws)
    for i in range(draws):
        pick = rng.choice(days, len(days))
        sel = np.concatenate([idx[d] for d in pick])
        out[i] = x[sel].mean()
    return np.quantile(out, [0.05, 0.95])


def best_window(x, N=10):
    if len(x) < N:
        return np.nan, -1
    cs = np.r_[0.0, np.cumsum(x)]
    m = (cs[N:] - cs[:-N]) / N
    i = int(np.argmax(m))
    return float(m[i]), i


def zero_edge_best10(n, rng, paths=4000, pool=None):
    """Best rolling 10-close mean R of zero-edge streams of length n: Gaussian with the pooled sd, or,
    with `pool`, the strategy's own closes centred to zero and resampled (its own R shape, no edge)."""
    if pool is None:
        x = rng.normal(0.0, POOLED_SD, (paths, n))
    else:
        c = pool - pool.mean()
        x = c[rng.integers(0, len(c), (paths, n))]
    cs = np.concatenate([np.zeros((paths, 1)), np.cumsum(x, 1)], 1)
    return ((cs[:, 10:] - cs[:, :-10]) / 10).max(1)


def corrected(strat, x, when):
    """The CORRECTED reading for one strategy (empty for the others)."""
    if strat not in CORRECTED:
        return {}
    above, val = CORRECTED[strat]
    xc = np.where(x > above, val, x)
    tr = sprt_trace(xc)
    k = np.flatnonzero(tr["event"] == "kill")
    return dict(n_corrected=int((x > above).sum()), meanR_corr=float(xc.mean()),
                state_corr=verdict(tr["event"], bool(tr["on"][-1])), llr_corr=float(tr["llr_now"]),
                kill_close_corr=int(k[0] + 1) if len(k) else None,
                kill_date_corr=when[k[0]].strftime("%Y-%m-%d") if len(k) else "",
                best10_corr=best_window(xc)[0])


def score(d, rng):
    rows, events, traces = [], [], {}
    for strat, g in d.groupby("strat"):
        if not strat:
            continue
        g = g.sort_values("t")
        x = g["R"].to_numpy(float)
        t = g["t"].to_numpy(float)
        n = len(x)
        tr = sprt_trace(x)
        st = S.states(x)["SPRT"][1:]
        assert (st == tr["on"]).all(), strat  # the trace is the frozen rule, close for close
        traces[strat] = dict(t=t, R=x, **{k: v for k, v in tr.items() if isinstance(v, np.ndarray)})
        when = pd.to_datetime(t, unit="s", utc=True)
        for j in np.flatnonzero(tr["event"] != ""):
            events.append(dict(strat=strat, close=int(j + 1), date=when[j].strftime("%Y-%m-%d %H:%M"),
                               event=tr["event"][j], llr=float(tr["llr_pre"][j])))
        kills = np.flatnonzero(tr["event"] == "kill")
        day = when.strftime("%Y-%m-%d").to_numpy()
        lo, hi = day_boot(x, day, rng) if len(np.unique(day)) > 1 else (np.nan, np.nan)
        sd_ = max(x.std(ddof=1), 1e-6) if n > 1 else 1.0
        prec = 1 / 0.01 + n / sd_ ** 2
        pm = (x.sum() / sd_ ** 2) / prec
        # closes to the next decision if the mean held (drift of the LLR per close at the current sd)
        drift = MU1 / tr["sd"] ** 2 * (x.mean() - MU1 / 2)
        on = bool(tr["on"][-1])
        if drift < 0:
            to_next = (tr["llr_now"] - B) / -drift if on else np.inf
        elif drift > 0:
            to_next = (A - tr["llr_now"]) / drift
        else:
            to_next = np.inf
        b10, i10 = best_window(x)
        if n >= 10:
            null_g = zero_edge_best10(n, rng)
            null_o = zero_edge_best10(n, rng, pool=x)
            p_g, p_o = float((null_g >= b10).mean()), float((null_o >= b10).mean())
            g50, g95 = np.quantile(null_g, [0.5, 0.95])
            o50, o95 = np.quantile(null_o, [0.5, 0.95])
        else:
            p_g = p_o = g50 = g95 = o50 = o95 = np.nan
        top = np.argmax(x)
        # reading only, not the rule: the same SPRT with the record's single largest close left out
        xt = np.delete(x, top)
        tt = sprt_trace(xt) if n > 1 else None
        kt = np.flatnonzero(tt["event"] == "kill") if tt else []
        when_t = when.delete(top)
        rows.append(dict(
            strat=strat, n=n, flag="" if n >= MIN_LIVE else f"< {MIN_LIVE} closes",
            first=when[0].strftime("%Y-%m-%d"), last_close=when[-1].strftime("%Y-%m-%d %H:%M"),
            meanR=float(x.mean()), lo90=float(lo), hi90=float(hi), totalR=float(x.sum()),
            meanR_ex_top=float(np.delete(x, top).mean()) if n > 1 else np.nan, top_close=float(x[top]),
            P_mu_gt_0=S.norm_cdf(pm * math.sqrt(prec)),
            llr_now=float(tr["llr_now"]), llr_one_shot=float(tr["llr_one"][-1]), sprt_sd=float(tr["sd"]),
            state=verdict(tr["event"], on),
            first_kill_close=int(kills[0] + 1) if len(kills) else None,
            first_kill_date=when[kills[0]].strftime("%Y-%m-%d") if len(kills) else "",
            n_kill=int((tr["event"] == "kill").sum()), n_confirm=int((tr["event"] == "confirm").sum()),
            n_resume=int((tr["event"] == "resume").sum()),
            closes_to_next_decision=float(to_next),
            state_ex_top=verdict(tt["event"], bool(tt["on"][-1])) if tt else "",
            llr_ex_top=float(tt["llr_now"]) if tt else np.nan,
            kill_date_ex_top=when_t[kt[0]].strftime("%Y-%m-%d") if len(kt) else "",
            kill_close_ex_top=int(kt[0] + 1) if len(kt) else None,
            best10_ex_top=best_window(xt)[0] if n > 10 else np.nan,
            **corrected(strat, x, when),
            best10=b10,
            best10_from=when[i10].strftime("%Y-%m-%d") if i10 >= 0 else "",
            best10_to=when[i10 + 9].strftime("%Y-%m-%d") if i10 >= 0 else "",
            zero_p50_gauss=float(g50), zero_p95_gauss=float(g95), p_best10_gauss=p_g,
            zero_p50_own=float(o50), zero_p95_own=float(o95), p_best10_own=p_o))
    return pd.DataFrame(rows).sort_values(["n"], ascending=False), pd.DataFrame(events), traces


def envelope(rng, ns=(10, 15, 20, 30, 45, 60, 80, 100, 150, 200, 300, 450, 600, 800, 1000)):
    rows = []
    for n in ns:
        z = zero_edge_best10(n, rng, paths=6000)
        rows.append(dict(n=n, p50=float(np.median(z)), p90=float(np.quantile(z, 0.9)),
                         p95=float(np.quantile(z, 0.95))))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------- figures

def plots(sc, ev, traces, env, img, data_end):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
    INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    KILL, KEEP, UND = "#e34948", "#1baf7a", "#52514e"
    plt.rcParams.update({"figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": INK2,
                         "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
                         "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
                         "axes.spines.right": False, "font.size": 9, "axes.titlesize": 10,
                         "legend.frameon": False, "lines.linewidth": 2})
    img.mkdir(parents=True, exist_ok=True)
    scol = {"kill": KILL, "keep": KEEP, "undecided": UND}

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(img / name, dpi=110)
        plt.close(fig)
        print("wrote", img / name)

    # 1. SPRT path per strategy
    names = list(sc["strat"])
    cols = 3
    rows_ = math.ceil(len(names) / cols)
    fig, axes = plt.subplots(rows_, cols, figsize=(11, 2.6 * rows_), squeeze=False)
    for ax, s in zip(axes.flat, names):
        tr = traces[s]
        k = np.arange(1, len(tr["R"]) + 1)
        ax.plot(np.r_[0, k], np.r_[0.0, tr["llr_pre"]], color=INK, lw=1.6, label="repeated SPRT LLR")
        ax.plot(np.r_[0, k], np.r_[0.0, tr["llr_one"]], color=SERIES[0], lw=1.0, ls="--", label="one-shot LLR (no reset)")
        ax.axhline(A, color=KEEP, lw=0.9, ls=":")
        ax.axhline(B, color=KILL, lw=0.9, ls=":")
        for e, mk, c in (("kill", "v", KILL), ("confirm", "^", KEEP), ("resume", "^", KEEP), ("reset", "x", KILL)):
            j = np.flatnonzero(tr["event"] == e)
            if len(j):
                ax.scatter(j + 1, tr["llr_pre"][j], marker=mk, s=40, color=c, zorder=3, label=e)
        r = sc.set_index("strat").loc[s]
        ax.set_title(f"{s}  n={int(r['n'])}  {r['state'].upper()}", color=scol[r["state"]], loc="left")
        lo = min(B - 0.5, np.nanmin(tr["llr_one"]), np.nanmin(tr["llr_pre"]))
        hi = max(A + 0.5, np.nanmax(tr["llr_one"]), np.nanmax(tr["llr_pre"]))
        ax.set_ylim(max(lo, -12), min(hi, 12))
        ax.set_xlabel("closes")
    for ax in list(axes.flat)[len(names):]:
        ax.axis("off")
    h, l_ = [], []
    for ax in axes.flat:
        for hh, ll in zip(*ax.get_legend_handles_labels()):
            if ll not in l_:
                h.append(hh)
                l_.append(ll)
    fig.legend(h, l_, loc="lower right", ncol=3, fontsize=8)
    fig.suptitle(f"Frozen SPRT (0 vs +0.10R, alpha 0.05, beta 0.20) on each live record, data to {data_end}. "
                 f"Kill at {B:.2f}, keep/resume at +{A:.2f}", fontsize=10, x=0.01, ha="left")
    save(fig, "sprt_paths.png")

    # 2. Hot-streak envelope with each strategy's best rolling-10
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.fill_between(env["n"], env["p50"], env["p95"], color=SERIES[0], alpha=0.13, lw=0)
    ax.plot(env["n"], env["p50"], color=SERIES[0], lw=1.6, label="zero edge, median (Gaussian, sd 0.90R)")
    ax.plot(env["n"], env["p95"], color=SERIES[0], lw=1.6, ls="--", label="zero edge, 95th pct (Gaussian; light tails, below the table)")
    for n, ((m0, m1), (q0, q1)) in DOC_HOT10.items():
        ax.plot([n, n], [m0, m1], color=INK2, lw=3, solid_capstyle="butt")
        ax.plot([n, n], [q0, q1], color=INK2, lw=3, solid_capstyle="butt")
    ax.plot([], [], color=INK2, lw=3, label="strategy-switching.md table (replayed R / walks)")
    s2 = sc[sc["n"] >= 10]
    top = 1.9
    off = {"confluence-scalp": (8, 6, "left"), "snap": (-8, -2, "right"), "fade-to-value": (-8, -10, "right"), "runner": (6, -12, "left")}
    for _, r in s2.iterrows():
        c = scol[r["state"]]
        ax.plot([r["n"], r["n"]], [r["zero_p50_own"], min(r["zero_p95_own"], top)], color=c, lw=1, alpha=0.6)
        dx, dy, ha = off.get(r["strat"], (6, 3, "left"))
        if r["best10"] > top:  # off the scale: an arrow at the top
            ax.scatter(r["n"], top - 0.04, marker="^", s=60, color=c, zorder=3)
            ax.annotate(f"{r['strat']} {r['best10']:+.2f} (one mis-sized close)", (r["n"], top - 0.04),
                        xytext=(-6, -4), textcoords="offset points", fontsize=8, color=INK, ha="right")
        else:
            ax.scatter(r["n"], r["best10"], s=46, color=c, edgecolor=SURF, linewidth=1.5, zorder=3)
            ax.annotate(f"{r['strat']} {r['best10']:+.2f}", (r["n"], r["best10"]), xytext=(dx, dy),
                        textcoords="offset points", fontsize=8, color=INK, ha=ha)
        if pd.notna(r.get("best10_corr", np.nan)):
            ax.scatter(r["n"], r["best10_corr"], s=46, facecolor=SURF, edgecolor=c, linewidth=1.5, zorder=3)
            ax.annotate(f"{r['best10_corr']:+.2f}, that close at +{CORRECTED[r['strat']][1]}R",
                        (r["n"], r["best10_corr"]), xytext=(6, -10), textcoords="offset points", fontsize=8,
                        color=INK2)
    ax.set_ylim(-0.25, top)
    ax.set_xlim(8, 1300)
    for st, c in scol.items():
        ax.scatter([], [], s=46, color=c, label=f"best rolling-10 mean R, SPRT {st}")
    ax.plot([], [], color=INK2, lw=1, alpha=0.6, label="its own R shape at zero edge, median-95th")
    ax.set_xscale("log")
    ax.set_xlabel("closes in the record")
    ax.set_ylabel("best rolling 10-close mean R")
    ax.set_title(f"How hot does zero edge get? Live records to {data_end}", loc="left")
    ax.legend(fontsize=8, loc="upper left")
    save(fig, "hot_envelope.png")

    # 3. The scorecard: mean R with day-bootstrap 90% interval, coloured by SPRT state
    s3 = sc.sort_values("meanR")
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(s3) + 1.4))
    y = np.arange(len(s3))
    for i, (_, r) in enumerate(s3.iterrows()):
        c = scol[r["state"]]
        ax.plot([r["lo90"], r["hi90"]], [i, i], color=c, lw=2)
        ax.scatter(r["meanR"], i, s=40, color=c, zorder=3)
        ax.annotate(f"n={int(r['n'])}, P(mu>0)={r['P_mu_gt_0']:.2f}, {r['state']}", (np.nanmax([r["hi90"], r["meanR"]]), i),
                    xytext=(6, -3), textcoords="offset points", fontsize=8, color=INK2)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.axvline(MU1, color=KEEP, lw=0.8, ls=":")
    ax.set_yticks(y, s3["strat"])
    ax.set_xlabel("mean R per close (day-bootstrap 90%); dotted: the +0.10R the SPRT is built to find")
    lim = np.nanmax(np.abs(s3[["lo90", "hi90"]].to_numpy()))
    ax.set_xlim(-min(lim, 6) * 1.05, np.nanmax(s3[["hi90", "meanR"]].to_numpy()) + 1.6)
    ax.set_title(f"Live scorecard, data to {data_end}", loc="left")
    save(fig, "scorecard.png")


def main():
    src = os.environ.get("CLOSES", ".data/closes.json")
    out = Path(os.environ.get("OUT", ".data/live_rescore"))
    img = Path(os.environ.get("IMG", "research/docs/img/live-rescore"))
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(29)
    raw = S.read_all_closes(src)
    d = S.live_streams(src)
    data_end = pd.to_datetime(d["t"].max(), unit="s", utc=True).strftime("%Y-%m-%d %H:%M UTC")
    print(f"sources: {src}\nclose records: {len(raw)}; with R: {len(d)}; without a strategy: "
          f"{int((d['strat'] == '').sum())}; data ends {data_end}")
    sc, ev, traces = score(d, rng)
    env = envelope(rng)
    sc.to_csv(out / "scorecard.csv", index=False)
    ev.to_csv(out / "events.csv", index=False)
    env.to_csv(out / "envelope.csv", index=False)
    pd.to_pickle(traces, out / "traces.pkl")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 60)
    print(sc.T.to_string())
    print(ev.to_string(index=False))
    print(env.round(3).to_string(index=False))
    if os.environ.get("PLOTS", "1") != "0":
        plots(sc, ev, traces, env, img, data_end)


if __name__ == "__main__":
    main()
