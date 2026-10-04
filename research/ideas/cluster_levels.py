"""Levels built by clustering past swing pivots: do they hold, and do they trade, beyond walks?

Frozen in `cluster_rule.json` before this ran on real data. At every 3/3 pivot's confirmation, the
prices of the pivots (highs and lows) of the last 300 bars are clustered in ATR units (cut at gaps over
0.25 ATR, no cluster wider than 1 ATR); the cluster holding the new pivot is a level of strength n (its
member count; n = 1 is a plain single swing level). On its first touch after price has left it by 1 ATR:
does it reverse 1 ATR before a close 1 ATR beyond (hold), and does a limit at it (bounce) or a close
through it (break) earn R. Against the same levels on geometric iid and GARCH walks matched to each series,
with the costs, exits and pass rule of `tv_rule.json` (helpers from `tv_indicators.py`).

  OUT=... MT5BT_DB=... MODE=run|plot python research/ideas/cluster_levels.py
  SMOKE=EURUSD:4h:real  one series: counts and timings only
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import tv_indicators as T  # noqa: E402
from turn_zones import atr  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/cluster"))
TV_OUT = Path(os.environ.get("TV_OUT", str(OUT.parent / "tv")))
WINDOW, EPS, WMAX = 300, 0.25, 1.0
BINS = ("1", "2", "3", "4+")


def clusters(px, eps, wmax):
    """1-D clusters of sorted prices: cut at neighbour gaps > eps, then split any group wider than wmax
    at its largest internal gap until none is. Returns a label per (sorted) price."""
    n = len(px)
    lab = np.zeros(n, int)
    cuts = list(np.flatnonzero(np.diff(px) > eps) + 1)
    groups = [(a, b) for a, b in zip([0] + cuts, cuts + [n], strict=False)]
    out = []
    while groups:
        a, b = groups.pop()
        if px[b - 1] - px[a] > wmax and b - a > 1:
            k = a + 1 + int(np.argmax(np.diff(px[a:b])))
            groups += [(a, k), (k, b)]
        else:
            out.append((a, b))
    for i, (a, b) in enumerate(sorted(out)):
        lab[a:b] = i
    return lab


def sbin(n):
    return "4+" if n >= 4 else str(n)


def levels(df, cost_px, keep_members=False):
    X = T.arrays(df)
    o, h, l, c = X
    a = atr(df)
    n = len(c)
    ph, pl = T.pivots(h), T.pivots(-l)
    P = np.r_[ph, pl]
    PX = np.r_[h[ph], l[pl]]
    order = np.argsort(P, kind="mergesort")
    P, PX = P[order], PX[order]
    rows = []
    for e in range(len(P)):
        p = P[e]
        b = p + T.PIV
        if b < T.WARM or b >= n - 2 or not a[b] > 0:
            continue
        i0 = int(np.searchsorted(P, b - WINDOW, side="left"))
        j1 = int(np.searchsorted(P, p, side="right"))      # pivots at bar <= p (all known by b)
        idx = np.arange(i0, j1)
        srt = idx[np.argsort(PX[idx], kind="mergesort")]
        lab = clusters(PX[srt], EPS * a[b], WMAX * a[b])
        me = lab[int(np.flatnonzero(srt == e)[0])]
        mem = srt[lab == me]
        mp = PX[mem]
        m, lo, hi, k = float(mp.mean()), float(mp.min()), float(mp.max()), len(mem)
        if m == c[b]:
            continue
        s = 1 if m > c[b] else -1
        Xw = X if s > 0 else T.neg(X)
        mw, low, hiw = s * m, (lo if s > 0 else -hi), (hi if s > 0 else -lo)
        t_brk, u, f = T.level_events(Xw, a, b, mw, low, hiw)
        base = dict(b=b, n_mem=k, bin=sbin(k), span=int(P[mem].max() - P[mem].min()), lvl_m=m, lvl_lo=lo, lvl_hi=hi,
                    level_side=s)
        if keep_members:
            base["members"] = ",".join(str(int(x)) for x in P[mem])
        if f >= 0:
            ow, hw, lw, cw = Xw
            A = a[f]
            end = min(n - 1, f + T.LEVEL_LIFE)
            br = T.first_after(cw >= mw + A, f, end)
            rv = T.first_after(lw <= mw - A, f + 1, end)
            if br < 0 and rv < 0:
                held = np.nan
            elif rv >= 0 and (br < 0 or rv < br):
                held = 1.0
            else:
                held = 0.0
            ex = T.bounce_trade(Xw, a, cost_px, f, mw, hiw)
            rows.append(dict(base, strat="B", var="bounce", side=-s, t=f - 1, f=f, live=u, held=held,
                             entry=-s * ex["entry"], stop=-s * (ex["entry"] - ex["risk"]),
                             **{k_: v_ for k_, v_ in ex.items() if k_ not in ("entry", "risk")}))
        if t_brk >= 0:
            ff, ex = T.break_trade(Xw, a, cost_px, t_brk, low)
            rows.append(dict(base, strat="B", var="break", side=s, t=t_brk, f=ff, entry=s * ex["entry"],
                             stop=s * (ex["entry"] - ex["risk"]),
                             **{k_: v_ for k_, v_ in ex.items() if k_ not in ("entry", "risk")}))
    return rows


def one(job):
    sym, iv, source = job
    t0 = time.time()
    try:
        df, cost_px = T.series(sym, iv, source)
        if df is None:
            return None
        d = pd.DataFrame(levels(df, cost_px, keep_members=source == "real"))
    except Exception as ex:  # one bad series should not sink the run
        import traceback
        print(f"  FAILED {job}: {ex!r}\n{traceback.format_exc()}", flush=True)
        return None
    if not len(d):
        return None
    d.insert(0, "src", source)
    d.insert(0, "iv", iv)
    d.insert(0, "fam", T.family()[sym])
    d["sym"] = sym
    d["ts"] = df["ts"].to_numpy()[d["f"].to_numpy(int)]
    print(f"  {source} {sym} {iv}: {(d['var'] == 'bounce').sum()} touches, {(d['var'] == 'break').sum()} breaks, "
          f"{time.time() - t0:.0f}s", flush=True)
    return d


def cells(d):
    B = (d["var"] == "bounce").to_numpy()
    K = (d["var"] == "break").to_numpy()
    nm = d["n_mem"].to_numpy()
    C = {"bounce n>=3": (B & (nm >= 3), ("E1", "X2")), "bounce n>=2": (B & (nm >= 2), ("E1", "X2")),
         "break n>=3": (K & (nm >= 3), ("E1", "X2")), "break n>=2": (K & (nm >= 2), ("E1", "X2"))}
    for b_ in BINS:
        m = (d["bin"] == b_).to_numpy()
        C[f"bounce n={b_}"] = (B & m, ("E1", "X2"))
        C[f"break n={b_}"] = (K & m, ("E1", "X2"))
    return C


PRIMARY = {"B": ("bounce n>=3", "E1", "bounce n=1")}


def hold_table(d, rng):
    rows = []
    x0 = d[(d["var"] == "bounce") & d["held"].notna()]
    for scope in T.SCOPES:
        xs = x0[T.scope_mask(x0, scope)]
        for src in T.SOURCES:
            for b_ in BINS + ("2+", "3+"):
                if b_ == "2+":
                    x = xs[(xs["src"] == src) & (xs["n_mem"] >= 2)]
                elif b_ == "3+":
                    x = xs[(xs["src"] == src) & (xs["n_mem"] >= 3)]
                else:
                    x = xs[(xs["src"] == src) & (xs["bin"] == b_)]
                r = dict(scope=scope, src=src, bin=b_, n=len(x), hold=x["held"].mean() if len(x) else np.nan)
                if len(x) > 30:
                    bd = T.boot_draws(x, "held", rng, 1000)
                    r.update(lo=np.quantile(bd, 0.05), hi=np.quantile(bd, 0.95))
                rows.append(r)
        # unresolved share
    t = pd.DataFrame(rows)
    u = d[d["var"] == "bounce"].assign(unres=lambda z: z["held"].isna())
    t = t.merge(u.assign(scope="MT5")[u["fam"] != "deriv"].groupby(["src", "bin"])["unres"].mean().rename("unresolved_MT5").reset_index(),
                on=["src", "bin"], how="left")
    return t


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    smoke = os.environ.get("SMOKE")
    if smoke:
        sym, iv, src = smoke.split(":")
        t0 = time.time()
        df, cost_px = T.series(sym, iv, src)
        r = pd.DataFrame(levels(df, cost_px, keep_members=True))
        print(f"{sym} {iv} {src}: {len(df)} bars, {len(r)} rows in {time.time() - t0:.1f}s")
        print(r.groupby(["var", "bin"]).size().to_string())
        print(r.groupby("bin")[["span"]].describe().round(1).to_string())
        print("resolved share at touches:", r.loc[r["var"] == "bounce", "held"].notna().mean().round(3))
        return
    with ProcessPoolExecutor(min(10, int(os.environ.get("WORKERS", 10)))) as pool:
        got = [g for g in pool.map(one, T.jobs(), chunksize=1) if g is not None]
    d = pd.concat(got, ignore_index=True)
    d.to_pickle(OUT / "cluster_trades.pkl.gz")
    score()


def score():
    d = pd.read_pickle(OUT / "cluster_trades.pkl.gz")
    rng = np.random.default_rng(81)
    h = hold_table(d, rng)
    h.round(4).to_csv(OUT / "cluster_hold.csv", index=False)
    t = T.table(d, cells(d), rng)
    t, k = T.bh(t)
    t.round(5).to_csv(OUT / "cluster_cells.csv", index=False)
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 2000)
    print("HOLD RATE at the first touch (reverse 1 ATR before a close 1 ATR beyond), by strength:")
    print(h.round(3).to_string(index=False))
    T.report(d, t, k, PRIMARY)
    tv = TV_OUT / "tv_cells.csv"
    if tv.exists():
        a = pd.read_csv(tv)
        both = pd.concat([a.assign(study="tv"), t.assign(study="cluster")], ignore_index=True)
        both, kk = T.bh(both)
        print(f"\nBenjamini-Hochberg (q = 0.10) over both studies' {kk} real cells; passing with R > 0:")
        cols = ["study", "cell", "exit", "scope", "iv", "n", "R", "lo", "hi", "p", "R_before", "R_after"]
        print(both[(both["src"] == "real") & both["bh"] & (both["R"] > 0)][cols].round(3).to_string(index=False))
        both.round(5).to_csv(OUT / "both_cells_bh.csv", index=False)


def hold_plot(h):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, len(T.SCOPES), figsize=(4 * len(T.SCOPES), 4.5), sharey=True)
    col = {"real": "#1d3557", "iid": "#a8dadc", "garch": "#e9c46a"}
    for ax, scope in zip(axes, T.SCOPES, strict=False):
        for k, src in enumerate(T.SOURCES):
            g = h[(h["scope"] == scope) & (h["src"] == src) & h["bin"].isin(BINS)].set_index("bin").reindex(BINS)
            x = np.arange(len(BINS)) + (k - 1) * 0.08
            ax.errorbar(x, g["hold"], yerr=[g["hold"] - g["lo"], g["hi"] - g["hold"]], fmt="-o", color=col[src],
                        capsize=3, label=f"{src} (n {int(g['n'].sum())})")
        ax.set_xticks(range(len(BINS)))
        ax.set_xticklabels([f"n={b}" for b in BINS])
        ax.set_title(scope, fontsize=10)
        ax.legend(fontsize=7)
    axes[0].set_ylabel("P(reverse 1 ATR before closing 1 ATR beyond)")
    fig.suptitle("Clustered pivot levels: hold rate at the first touch by cluster strength (n = 1: a single swing level), "
                 "real vs walks, 90% day-bootstrap")
    fig.tight_layout()
    fig.savefig(OUT / "cluster_hold.png", dpi=70)
    plt.close(fig)


def draw_b(ax, df, r, ex):
    mem = [int(x) for x in str(r.members).split(",")]
    t, f, xb = int(r.t), int(r.f), int(r[f"{ex}_x"])
    i0, i1 = max(0, min(mem) - 10), min(len(df) - 1, xb + 15)
    w = df.iloc[i0:i1 + 1]
    T.candles(ax, w, np.arange(i0, i1 + 1))
    ax.fill_between([int(r.b), min(i1, int(r.b) + T.LEVEL_LIFE)], r.lvl_lo, r.lvl_hi, color="#457b9d", alpha=0.3)
    ax.hlines(r.lvl_m, min(mem), i1, colors="#1d3557", lw=1)
    for p in mem:
        hp, lp = df["high"].iat[p], df["low"].iat[p]
        ax.plot([p], [hp if abs(hp - r.lvl_m) < abs(lp - r.lvl_m) else lp], "o", color="#1d3557")
    T._trade_marks(ax, r, ex, i1)
    ax.axvline(int(r.b), color="purple", lw=1, ls=":")
    ax.set_title(f"{r.sym} {r.iv} {r['var']} n={int(r.n_mem)} {'long' if r.side > 0 else 'short'} -> {r[ex]:+.2f}R "
                 f"{pd.Timestamp(int(r.ts), unit='s'):%Y-%m-%d}", fontsize=9)


def plot():
    h = pd.read_csv(OUT / "cluster_hold.csv")
    hold_plot(h)
    t = pd.read_csv(OUT / "cluster_cells.csv")
    T.OUT = OUT
    T.pnr_plot(t, {**PRIMARY, "break": ("break n>=3", "E1", "break n=1")}, "cluster_pnr.png",
               "Clustered pivot levels: P(N R) real vs iid, GARCH and single swing levels, per family")
    d = pd.read_pickle(OUT / "cluster_trades.pkl.gz")
    C = cells(d)
    name, ex, _ = PRIMARY["B"]
    for tag in ("winners", "losers"):
        T.gallery(d, C[name][0], ex, tag, draw_b, f"cluster_{tag}.png",
                  "Bounce at a clustered level of >= 3 pivots (dots: the members; blue: the cluster's span; purple: born; "
                  "red: stop; dashed: exit)")
    print("plots written", flush=True)


def main():
    {"run": run, "plot": plot, "score": score}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
