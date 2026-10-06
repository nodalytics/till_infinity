"""FX and metals ML + ACI: aggregation, day bootstrap, Benjamini-Hochberg, trade translation and plots.

Reads OUT/ds_*.pkl, OUT/bars_*.pkl and OUT/pred/*.pkl (our own pickles, written by fxml_data.py and
fxml_models.py on the lab) and writes OUT/report/*.csv, OUT/report/summary.json and the figures in
OUT/report/img/.

  OUT=... MODE=agg|plot python research/ideas/fxml_report.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fxml_data as D  # noqa: E402
import fxml_models as M  # noqa: E402

OUT = D.OUT
REP = OUT / "report"
IMG = REP / "img"
B_PRIMARY, B_SEC = 1000, 300
SEED = 7
CLASSES = ("POOL", "FX", "METAL", "HOLD")
NS = (1, 2, 4, 10)
WALKS = ("iid", "garch")


def load_pred(tf, src, tgt, part=""):
    p = OUT / "pred" / (f"{tf}_{src}_{tgt}" + (f"_{part}" if part else "") + ".pkl")
    return pd.read_pickle(p) if p.exists() else None  # our own pickle


_ROWS = {}


def meta(tf, src):
    """Per-row columns the report needs (our own pickle)."""
    key = (tf, src)
    if key not in _ROWS:
        d = pd.read_pickle(OUT / f"ds_{tf}_{src}.pkl")["rows"]
        cols = ["sym", "cls", "ts", "bar", "cost_atr", "atr", "close", "atr_ratio", "hour", "mfeL", "mfeS",
                "riskL", "riskS", "tstopL", "tstopS"]
        _ROWS[key] = d[cols].reset_index(drop=True)
    return _ROWS[key]


def cls_mask(m, c):
    if c == "POOL":
        return (m["cls"] != "HOLD").to_numpy()
    return (m["cls"] == c).to_numpy()


# ------------------------------------------------------------------------------------------ bootstrap

class Boot:
    """Day bootstrap: resample whole UTC days of the confirmation rows, shared across sources (walks sit
    on the real timestamps, so the same days are resampled for real and walk rows)."""

    def __init__(self, ts, draws, seed=SEED):
        self.days = np.unique(ts // 86400)
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, len(self.days), (draws, len(self.days)))
        self.C = np.stack([np.bincount(r, minlength=len(self.days)) for r in idx]).astype(np.float64)
        self.draws = draws

    def day(self, ts):
        return np.searchsorted(self.days, ts // 86400)

    def mean(self, ts, x):
        """(point, draws) of the mean of x."""
        ok = np.isfinite(x)
        d = self.day(ts[ok])
        s = np.bincount(d, weights=x[ok], minlength=len(self.days))
        n = np.bincount(d, minlength=len(self.days)).astype(float)
        return s.sum() / max(n.sum(), 1), (self.C @ s) / np.maximum(self.C @ n, 1)

    def ratio(self, ts, x, y):
        """(point, draws) of mean(x) / mean(y) - 1 on rows where both are finite."""
        ok = np.isfinite(x) & np.isfinite(y)
        d = self.day(ts[ok])
        sx = np.bincount(d, weights=x[ok], minlength=len(self.days))
        sy = np.bincount(d, weights=y[ok], minlength=len(self.days))
        return sx.sum() / sy.sum() - 1, (self.C @ sx) / (self.C @ sy) - 1

    def auc(self, ts, y, p):
        """(point, draws) of the AUC, with day weights."""
        ok = np.isfinite(y) & np.isfinite(p)
        y, p, d = y[ok], p[ok], self.day(ts[ok])
        if len(y) < 50 or len(np.unique(y)) < 2:
            return np.nan, np.full(self.draws, np.nan)
        o = np.argsort(p, kind="stable")
        p, y, d = p[o], y[o], d[o]
        starts = np.r_[0, np.flatnonzero(np.diff(p)) + 1]
        pos = y == 1

        def one(w):
            wp = np.add.reduceat(np.where(pos, w, 0.0), starts)
            wn = np.add.reduceat(np.where(pos, 0.0, w), starts)
            cn = np.cumsum(wn) - wn
            P, N = wp.sum(), wn.sum()
            return float((wp * (cn + 0.5 * wn)).sum() / (P * N)) if P > 0 and N > 0 else np.nan

        point = one(np.ones(len(y)))
        dr = np.array([one(self.C[b][d]) for b in range(self.draws)])
        return point, dr


def ci(dr, point):
    dr = dr[np.isfinite(dr)]
    if not len(dr):
        return np.nan, np.nan, np.nan
    return float(np.quantile(dr, 0.05)), float(np.quantile(dr, 0.95)), None


def p_le0(dr):
    """One-sided bootstrap p of the statistic being <= 0."""
    dr = dr[np.isfinite(dr)]
    return float((dr <= 0).mean()) if len(dr) else np.nan


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


# ------------------------------------------------------------------------------------------ scoring rows

def scored(pr, m, c):
    """Confirmation rows of class c with a finite label."""
    mk = pr["masks"]
    return mk["conf"] & cls_mask(m, c) & np.isfinite(pr["y"])


def brier(y, p):
    return (p - y) ** 2


def logloss(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


# ------------------------------------------------------------------------------------------ risk

def risk_tables(boots):
    rows, p1 = [], {}
    for tf in D.TFS:
        for tgt in ("rvk", "range1", "absret1"):
            prs = {s: load_pred(tf, s, tgt) for s in D.SOURCES}
            if any(v is None for v in prs.values()):
                continue
            for c in CLASSES:
                rel = {}
                for s in D.SOURCES:
                    pr, m = prs[s], meta(tf, s)
                    sel = scored(pr, m, c)
                    if sel.sum() < 100:
                        continue
                    ts = m["ts"].to_numpy(np.int64)[sel]
                    z = M.model_target(tgt, pr["y"][sel])
                    B = boots[tf][1 if (tf, tgt) == M.P1 and c == "POOL" else 0]
                    loss = {}
                    for nm, f in pr["pred"].items():
                        ff = f[sel].astype(float)
                        if tgt == "absret1":
                            loss[nm] = (ff - z) ** 2
                        else:
                            loss[nm] = M.qlike(z, ff)
                        mse = (ff - z) ** 2
                        rows.append(dict(tf=tf, target=tgt, cls=c, source=s, model=nm, n=int(sel.sum()),
                                         loss=float(np.nanmean(loss[nm])), mse=float(np.nanmean(mse))))
                    ref = "har"
                    for nm in loss:
                        if nm == ref:
                            continue
                        pt, dr = B.ratio(ts, loss[nm], loss[ref])
                        rel[(s, nm)] = (pt, dr)
                        lo, hi, _ = ci(dr, pt)
                        rows.append(dict(tf=tf, target=tgt, cls=c, source=s, model=nm, vs="har", rel=pt,
                                         lo=lo, hi=hi, p=1 - p_le0(dr)))
                # market part: real relative change minus the GARCH walk's
                for nm in ("hgb", "wf", "sgd", "ridge", "mlp", "garch", "ewma", "envelope"):
                    if ("real", nm) in rel and ("garch", nm) in rel:
                        d = rel[("real", nm)][1] - rel[("garch", nm)][1]
                        pt = rel[("real", nm)][0] - rel[("garch", nm)][0]
                        lo, hi, _ = ci(d, pt)
                        rows.append(dict(tf=tf, target=tgt, cls=c, source="real-garch", model=nm, vs="har",
                                         rel=pt, lo=lo, hi=hi, p=1 - p_le0(d)))
                        if (tf, tgt) == M.P1 and c == "POOL" and nm == "hgb":
                            pa, da = rel[("real", "hgb")]
                            p1 = dict(rel_real=pa, rel_real_ci=ci(da, pa)[:2], rel_garch=rel[("garch", "hgb")][0],
                                      rel_garch_ci=ci(rel[("garch", "hgb")][1], 0)[:2],
                                      rel_iid=rel.get(("iid", "hgb"), (np.nan,))[0],
                                      diff=pt, diff_ci=(lo, hi),
                                      pass_a=bool(ci(da, pa)[1] < 0), pass_b=bool(hi < 0))
                            p1["pass"] = p1["pass_a"] and p1["pass_b"]
    return pd.DataFrame(rows), p1


# ------------------------------------------------------------------------------------------ classes

def class_tables(boots):
    rows, p2, rel_rows = [], {}, []
    for tf in D.TFS:
        for tgt in M.CLS:
            prs = {s: load_pred(tf, s, tgt) for s in D.SOURCES}
            if any(v is None for v in prs.values()):
                continue
            for c in CLASSES:
                aucs = {}
                for s in D.SOURCES:
                    pr, m = prs[s], meta(tf, s)
                    sel = scored(pr, m, c)
                    if sel.sum() < 100:
                        continue
                    ts = m["ts"].to_numpy(np.int64)[sel]
                    y = pr["y"][sel].astype(float)
                    prim = (tf, tgt) == M.P2 and c == "POOL"
                    B = boots[tf][1 if prim else 0]
                    for nm, f in pr["pred"].items():
                        p = f[sel].astype(float)
                        a_pt, a_dr = B.auc(ts, y, p) if nm != "coin" else (0.5, np.full(B.draws, 0.5))
                        aucs[(s, nm)] = (a_pt, a_dr)
                        lo, hi, _ = ci(a_dr, a_pt)
                        bs = brier(y, p)
                        bc = brier(y, prs[s]["pred"]["coin"][sel].astype(float))
                        bss_pt, bss_dr = B.ratio(ts, bs, bc)
                        rows.append(dict(tf=tf, target=tgt, cls=c, source=s, model=nm, n=int(sel.sum()),
                                         auc=a_pt, auc_lo=lo, auc_hi=hi, brier=float(np.nanmean(bs)),
                                         logloss=float(np.nanmean(logloss(y, p))), bss=-bss_pt,
                                         bss_lo=-ci(bss_dr, 0)[1], bss_hi=-ci(bss_dr, 0)[0],
                                         p_auc=p_le0(a_dr - 0.5) if nm != "coin" else np.nan,
                                         base=float(np.nanmean(y))))
                # real-minus-walk (behavioural) skill per model
                for nm in prs["real"]["pred"]:
                    if nm == "coin":
                        continue
                    for w in WALKS:
                        if ("real", nm) in aucs and (w, nm) in aucs:
                            d = aucs[("real", nm)][1] - aucs[(w, nm)][1]
                            pt = aucs[("real", nm)][0] - aucs[(w, nm)][0]
                            lo, hi, _ = ci(d, pt)
                            rel_rows.append(dict(tf=tf, target=tgt, cls=c, model=nm, walk=w,
                                                 auc_real=aucs[("real", nm)][0], auc_walk=aucs[(w, nm)][0],
                                                 diff=pt, lo=lo, hi=hi, p=p_le0(d)))
                if (tf, tgt) == M.P2 and c == "POOL":
                    best = prs["real"].get("best", "hgb")
                    out = dict(model=best, choice=prs["real"].get("choice"))
                    a_pt, a_dr = aucs[("real", best)]
                    out["auc_real"], out["auc_real_ci"] = a_pt, ci(a_dr, a_pt)[:2]
                    ok = a_pt >= 0.510
                    for w in WALKS:
                        wb = prs[w].get("best", "hgb")
                        wpt, wdr = aucs[(w, wb)]
                        d = a_dr - wdr
                        out[f"auc_{w}"] = wpt
                        out[f"twin_model_{w}"] = wb
                        out[f"diff_{w}"] = a_pt - wpt
                        out[f"diff_{w}_ci"] = ci(d, a_pt - wpt)[:2]
                        ok = ok and out[f"diff_{w}_ci"][0] > 0
                    out["pass"] = bool(ok)
                    p2 = out
    return pd.DataFrame(rows), pd.DataFrame(rel_rows), p2


def reliability(tf, tgt, model="hgb", bins=10):
    out = []
    for s in D.SOURCES:
        pr = load_pred(tf, s, tgt)
        if pr is None:
            continue
        m = meta(tf, s)
        sel = scored(pr, m, "POOL")
        p = pr["pred"][model][sel].astype(float)
        y = pr["y"][sel].astype(float)
        q = np.quantile(p, np.linspace(0, 1, bins + 1))
        b = np.clip(np.searchsorted(q, p, side="right") - 1, 0, bins - 1)
        for k in range(bins):
            mm = b == k
            if mm.sum():
                out.append(dict(tf=tf, target=tgt, source=s, model=model, bin=k, p=float(p[mm].mean()),
                                y=float(y[mm].mean()), n=int(mm.sum())))
    return out


# ------------------------------------------------------------------------------------------ conformal

def cqr_tables():
    rows, series = [], []
    for tf in D.TFS:
        for tgt in ("rvk", "range1"):
            for s in D.SOURCES:
                pr = load_pred(tf, s, tgt)
                if pr is None or "cqr" not in pr:
                    continue
                m = meta(tf, s)
                ly = np.log(np.maximum(M.model_target(tgt, pr["y"].astype(float)), M.EPS))
                vt = pd.qcut(m["atr_ratio"].rank(method="first"), 3, labels=["calm", "normal", "volatile"])
                hr = m["hour"].to_numpy()
                sess = np.where(hr < 7, "asia", np.where(hr < 12, "london", np.where(hr < 16, "overlap",
                                np.where(hr < 21, "ny", "late"))))
                month = pd.to_datetime(m["ts"], unit="s").dt.to_period("M").astype(str).to_numpy()
                for c in ("POOL", "FX", "METAL", "HOLD"):
                    sel0 = scored(pr, m, c)
                    for nm, meths in pr["cqr"].items():
                        for meth, (lo, hi) in meths.items():
                            lo = lo.astype(float)
                            hi = hi.astype(float)
                            sel = sel0 & np.isfinite(lo) & np.isfinite(hi) & np.isfinite(ly)
                            if sel.sum() < 100:
                                continue
                            cov = (ly[sel] >= lo[sel]) & (ly[sel] <= hi[sel])
                            w = hi[sel] - lo[sel]
                            a = M.ALPHA_REG
                            wink = w + (2 / a) * np.maximum(lo[sel] - ly[sel], 0) + (2 / a) * np.maximum(ly[sel] - hi[sel], 0)
                            r = dict(tf=tf, target=tgt, source=s, cls=c, model=nm, method=meth, n=int(sel.sum()),
                                     cover=float(cov.mean()), width=float(np.mean(w)), winkler=float(np.mean(wink)))
                            for lab in ("calm", "normal", "volatile"):
                                mm = (vt.to_numpy()[sel] == lab)
                                r[f"cover_{lab}"] = float(cov[mm].mean()) if mm.any() else np.nan
                            if tf == "1h":
                                for lab in ("asia", "london", "overlap", "ny", "late"):
                                    mm = sess[sel] == lab
                                    r[f"cover_{lab}"] = float(cov[mm].mean()) if mm.any() else np.nan
                            mo = pd.Series(cov).groupby(month[sel]).mean()
                            r["cover_month_sd"] = float(mo.std())
                            r["cover_month_min"] = float(mo.min())
                            rows.append(r)
                            if c == "POOL":
                                for k_, v_ in mo.items():
                                    series.append(dict(tf=tf, target=tgt, source=s, model=nm, method=meth,
                                                       month=k_, cover=float(v_)))
    return pd.DataFrame(rows), pd.DataFrame(series)


def set_tables():
    rows = []
    for tf in D.TFS:
        for tgt in M.CLS:
            for s in D.SOURCES:
                pr = load_pred(tf, s, tgt)
                if pr is None or "sets" not in pr:
                    continue
                m = meta(tf, s)
                y = pr["y"].astype(float)
                for c in CLASSES:
                    sel = scored(pr, m, c)
                    if sel.sum() < 100:
                        continue
                    for nm, meths in pr["sets"].items():
                        for meth, (i1, i0) in meths.items():
                            a1, a0 = i1[sel], i0[sel]
                            yy = y[sel]
                            size = a1.astype(int) + a0.astype(int)
                            cov = np.where(yy == 1, a1, a0)
                            single = size == 1
                            call = np.where(a1, 1.0, 0.0)
                            right = (call == yy) & single
                            rows.append(dict(tf=tf, target=tgt, source=s, cls=c, model=nm, method=meth,
                                             n=int(sel.sum()), cover=float(cov.mean()), size=float(size.mean()),
                                             singleton=float(single.mean()), empty=float((size == 0).mean()),
                                             single_acc=float(right.sum() / max(single.sum(), 1)),
                                             single_up=float((single & a1).mean()),
                                             single_up_acc=float(((call == yy) & single & a1).sum() / max((single & a1).sum(), 1)),
                                             single_dn_acc=float(((call == yy) & single & a0).sum() / max((single & a0).sum(), 1)),
                                             base=float(yy.mean())))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------ ablation, importance, CV

def ablation_tables(boots):
    rows = []
    for tf in D.TFS:
        for tgt in M.ABL_TARGETS:
            prs = {s: load_pred(tf, s, tgt, "abl") for s in D.SOURCES}
            if any(v is None for v in prs.values()):
                continue
            kind = "reg" if tgt in M.REG else "cls"
            for c in ("POOL", "FX", "METAL"):
                stats = {}
                for s in D.SOURCES:
                    pr, m = prs[s], meta(tf, s)
                    sel = scored(pr, m, c)
                    if sel.sum() < 100:
                        continue
                    ts = m["ts"].to_numpy(np.int64)[sel]
                    y = pr["y"][sel].astype(float)
                    z = M.model_target(tgt, y) if kind == "reg" else y
                    B = boots[tf][0]
                    for nm, f in pr["abl"].items():
                        p = f[sel].astype(float)
                        if kind == "cls":
                            stats[(s, nm)] = B.auc(ts, z, p)
                        else:
                            stats[(s, nm)] = B.mean(ts, M.qlike(z, p))
                for s in D.SOURCES:
                    for fam, base, variants in (("hgb", "hgb:B0", ("hgb:B0+S", "hgb:B0+P", "hgb:B0+C", "hgb:all", "hgb:all+Q")),
                                                ("hgb", "hgb:all", ("hgb:all+Q",)),
                                                ("hgb", "hgb:CO", ("hgb:OH",)),
                                                ("lin", "lin:base", ("lin:base+Q", "lin:base+E", "lin:base+Eint", "lin:base+Q+E")),
                                                ("lin", "lin:CO", ("lin:OH",))):
                        if (s, base) not in stats:
                            continue
                        for v in variants:
                            if (s, v) not in stats:
                                continue
                            sign = 1 if kind == "cls" else -1  # gain: AUC up, QLIKE down
                            g_pt = sign * (stats[(s, v)][0] - stats[(s, base)][0])
                            g_dr = sign * (stats[(s, v)][1] - stats[(s, base)][1])
                            lo, hi, _ = ci(g_dr, g_pt)
                            r = dict(tf=tf, target=tgt, cls=c, source=s, base=base, variant=v,
                                     score_base=stats[(s, base)][0], score=stats[(s, v)][0], gain=g_pt, lo=lo, hi=hi,
                                     p=p_le0(g_dr))
                            rows.append(r)
                            if s == "real":
                                for w in WALKS:
                                    if (w, v) in stats and (w, base) in stats:
                                        wg_dr = sign * (stats[(w, v)][1] - stats[(w, base)][1])
                                        wg_pt = sign * (stats[(w, v)][0] - stats[(w, base)][0])
                                        lo2, hi2, _ = ci(g_dr - wg_dr, g_pt - wg_pt)
                                        rows.append(dict(tf=tf, target=tgt, cls=c, source=f"real-{w}", base=base,
                                                         variant=v, gain=g_pt - wg_pt, lo=lo2, hi=hi2,
                                                         p=p_le0(g_dr - wg_dr)))
    return pd.DataFrame(rows)


def importance_tables():
    out = []
    for tf in D.TFS:
        for tgt in M.IMP_TARGETS:
            for s in ("real", "garch"):
                pr = load_pred(tf, s, tgt, "imp")
                if pr is None:
                    continue
                d = pr["imp"].assign(tf=tf, target=tgt, source=s)
                out.append(d)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def cv_tables():
    rows = []
    for tf, tgt in (M.P1, M.P2):
        for s in D.SOURCES:
            pr = load_pred(tf, s, tgt)
            if pr is None or "cv" not in pr:
                continue
            cv = pr["cv"]
            better_low = tgt in M.REG
            best = cv["score"].min() if better_low else cv["score"].max()
            rows.append(dict(tf=tf, target=tgt, source=s, best=best, median=float(cv["score"].median()),
                             allowance=float(abs(best - cv["score"].median())), cfg=json.dumps(pr["cfg"]),
                             choice=json.dumps(pr.get("choice"))))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------ P(N R) and trades

def pnr_diag():
    rows = []
    for tf in D.TFS:
        for side, tgt in (("L", "nr2L"), ("S", "nr2S")):
            for s in D.SOURCES:
                pr = load_pred(tf, s, tgt)
                if pr is None:
                    continue
                m = meta(tf, s)
                p = pr["pred"]["hgb"].astype(float)
                thr = np.nanquantile(p[pr["masks"]["cal_main"]], 0.9)
                mfe = m[f"mfe{side}"].to_numpy(float)
                for c in CLASSES:
                    base = pr["masks"]["conf"] & cls_mask(m, c) & np.isfinite(mfe)
                    for sel_name, sel in (("all", base), ("top10", base & (p >= thr))):
                        if sel.sum() < 30:
                            continue
                        r = dict(tf=tf, side=side, source=s, cls=c, sel=sel_name, n=int(sel.sum()))
                        for n_ in NS:
                            r[f"P{n_}"] = float((mfe[sel] >= n_).mean())
                        rows.append(r)
    return pd.DataFrame(rows)


def simulate(bars, entries):
    """Trades from entries [(t, side)] on one series' bars: entry O_{t+1}, the 3-bar structural stop
    (0.1 ATR pad, 0.25 ATR minimum risk); exits at fixed +N R (N in NS) and a trailing structural stop
    (3-bar low / high - 0.1 ATR, never loosened), 500-bar cap. Returns per trade: risk_atr, cost_R,
    gross R per exit, MFE."""
    o, h, l, c = (bars[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = bars["atr"].to_numpy(float)
    cost_atr = bars["cost_atr"].to_numpy(float)
    n = len(c)
    out = []
    for t, side in entries:
        if t + 1 >= n or not np.isfinite(a[t]):
            continue
        if side < 0:
            oo, hh, ll, cc = -o, -l, -h, -c
        else:
            oo, hh, ll, cc = o, h, l, c
        E = oo[t + 1]
        stop0 = min(ll[max(t - 2, 0):t + 1]) - D.PAD * a[t]
        risk = E - stop0
        if risk < D.MIN_RISK * a[t]:
            risk = D.MIN_RISK * a[t]
        stop0 = E - risk
        if not risk > 0:
            continue
        res = {f"x{n_}": None for n_ in NS}
        trail = stop0
        tr_res = None
        mfe = 0.0
        stopped = False
        for j in range(1, D.NR_CAP + 1):
            b = t + j
            if b >= n:
                break
            up = cc[b] >= oo[b]
            # fixed targets share the initial stop
            if not stopped:
                gap = oo[b] <= stop0
                hit = ll[b] <= stop0
                fav = (hh[b] - E) / risk
                if gap:
                    stopped = True
                    stop_px = oo[b]
                elif hit and up:
                    stopped = True
                    stop_px = stop0
                else:
                    mfe = max(mfe, fav)
                    if hit:
                        stopped = True
                        stop_px = stop0
                for n_ in NS:
                    if res[f"x{n_}"] is None:
                        if mfe >= n_:
                            res[f"x{n_}"] = (float(n_), False)
                        elif stopped:
                            res[f"x{n_}"] = ((stop_px - E) / risk, True)
            if tr_res is None:
                if oo[b] <= trail:
                    tr_res = ((oo[b] - E) / risk, True)
                elif ll[b] <= trail:
                    tr_res = ((trail - E) / risk, True)
                else:
                    trail = max(trail, min(ll[max(b - 2, 0):b + 1]) - D.PAD * a[b])
            if stopped and tr_res is not None and all(v is not None for v in res.values()):
                break
        last = min(t + D.NR_CAP, n - 1)
        for n_ in NS:
            if res[f"x{n_}"] is None:
                res[f"x{n_}"] = ((cc[last] - E) / risk, False)
        if tr_res is None:
            tr_res = ((cc[last] - E) / risk, False)
        cost_R = cost_atr[t] * a[t] / risk
        slip_R = 0.05 * a[t] / risk
        r = dict(t=t, side=side, risk_atr=risk / a[t], cost_R=cost_R, mfe=mfe)
        for n_ in NS:
            g, st = res[f"x{n_}"]
            r[f"g{n_}"] = g
            r[f"net{n_}"] = g - cost_R - (slip_R if st else 0.0)
        r["gtrail"] = tr_res[0]
        r["nettrail"] = tr_res[0] - cost_R - (slip_R if tr_res[1] else 0.0)
        out.append(r)
    return out


def trades(boots):
    """The frozen trade translation on the sign1 ACI sets (singleton {up} long, {down} short)."""
    rows = []
    allt = []
    for tf in D.TFS:
        for s in D.SOURCES:
            pr = load_pred(tf, s, "sign1")
            if pr is None:
                continue
            m = meta(tf, s)
            bars = pd.read_pickle(OUT / f"bars_{tf}_{s}.pkl")  # our own pickle
            best = pr.get("best", "hgb")
            i1, i0 = pr["sets"][best]["aci"]
            conf = pr["masks"]["conf"]
            long_ = conf & i1 & ~i0
            short = conf & i0 & ~i1
            for sym, ix in m.groupby("sym", sort=False).indices.items():
                if sym not in bars:
                    continue
                b = bars[sym].reset_index(drop=True)
                bar = m["bar"].to_numpy()
                ent = [(int(bar[i]), 1) for i in ix if long_[i]] + [(int(bar[i]), -1) for i in ix if short[i]]
                tr = simulate(b, ent)
                for r in tr:
                    r.update(tf=tf, source=s, sym=sym, cls=m["cls"].iloc[ix[0]], ts=int(b["ts"].iloc[r["t"]]))
                allt += tr
    T = pd.DataFrame(allt)
    if not len(T):
        return T, pd.DataFrame()
    for tf in D.TFS:
        for c in CLASSES:
            for s in D.SOURCES:
                x = T[(T.tf == tf) & (T.source == s) & (cls_mask(T, c) if c != "POOL" else (T.cls != "HOLD"))]
                if len(x) < 30:
                    continue
                B = boots[tf][0]
                r = dict(tf=tf, cls=c, source=s, n=len(x), risk_atr=float(x.risk_atr.median()),
                         cost_R=float(x.cost_R.mean()))
                for ex in [f"net{n_}" for n_ in NS] + ["nettrail", "gtrail"] + [f"g{n_}" for n_ in NS]:
                    pt, dr = B.mean(x.ts.to_numpy(np.int64), x[ex].to_numpy(float))
                    lo, hi, _ = ci(dr, pt)
                    r[ex], r[f"{ex}_lo"], r[f"{ex}_hi"] = pt, lo, hi
                for n_ in NS:
                    r[f"P{n_}"] = float((x.mfe >= n_).mean())
                rows.append(r)
    return T, pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------ main

def agg():
    REP.mkdir(parents=True, exist_ok=True)
    boots = {}
    for tf in D.TFS:
        m = meta(tf, "real")
        ts = m["ts"].to_numpy(np.int64)
        ts = ts[ts >= D.SPLIT]
        boots[tf] = (Boot(ts, B_SEC), Boot(ts, B_PRIMARY))
    risk, p1 = risk_tables(boots)
    risk.to_csv(REP / "risk.csv", index=False)
    print("risk done", flush=True)
    cls_t, rel_t, p2 = class_tables(boots)
    cls_t.to_csv(REP / "classes.csv", index=False)
    rel_t.to_csv(REP / "behavioural.csv", index=False)
    print("classes done", flush=True)
    rel = []
    for tf in D.TFS:
        for tgt in ("tup05", "tdn05", "tup10", "tdn10", "first", "sign1", "signk", "nr2L"):
            rel += reliability(tf, tgt, "hgb")
            if tgt.startswith("t"):
                rel += reliability(tf, tgt, "reflect")
    pd.DataFrame(rel).to_csv(REP / "reliability.csv", index=False)
    cq, cqs = cqr_tables()
    cq.to_csv(REP / "cqr.csv", index=False)
    cqs.to_csv(REP / "cqr_months.csv", index=False)
    st = set_tables()
    st.to_csv(REP / "sets.csv", index=False)
    print("conformal done", flush=True)
    ab = ablation_tables(boots)
    ab.to_csv(REP / "ablation.csv", index=False)
    imp = importance_tables()
    imp.to_csv(REP / "importance.csv", index=False)
    cv = cv_tables()
    cv.to_csv(REP / "cv.csv", index=False)
    print("ablation done", flush=True)
    pn = pnr_diag()
    pn.to_csv(REP / "pnr.csv", index=False)
    T, tt = trades(boots)
    T.to_pickle(REP / "trades.pkl")
    tt.to_csv(REP / "trades.csv", index=False)
    print("trades done", flush=True)
    # Benjamini-Hochberg over the secondary family
    fam = []
    r = risk[risk.get("vs", pd.Series(dtype=object)) == "har"] if "vs" in risk else pd.DataFrame()
    for _, x in r.iterrows():
        if (x.tf, x.target) == M.P1 and x.cls == "POOL" and x.model == "hgb" and x.source in ("real", "real-garch"):
            continue
        if x.source in ("real", "real-garch"):
            fam.append(dict(kind="risk", key=f"{x.tf} {x.target} {x.cls} {x.source} {x.model} vs har", p=x.p))
    for _, x in rel_t.iterrows():
        if (x.tf, x.target) == M.P2 and x.cls == "POOL":
            continue
        fam.append(dict(kind="behavioural", key=f"{x.tf} {x.target} {x.cls} {x.model} real-{x.walk}", p=x.p))
    for _, x in cls_t[(cls_t.source == "real") & (cls_t.model != "coin")].iterrows():
        fam.append(dict(kind="auc>0.5", key=f"{x.tf} {x.target} {x.cls} {x.model}", p=x.p_auc))
    for _, x in ab[ab.source.isin(["real", "real-iid", "real-garch"])].iterrows():
        fam.append(dict(kind="ablation", key=f"{x.tf} {x.target} {x.cls} {x.source} {x.variant} over {x.base}", p=x.p))
    F = pd.DataFrame(fam)
    F["bh"] = bh(F["p"].to_numpy())
    F.to_csv(REP / "bh.csv", index=False)
    summ = dict(P1=p1, P2=p2, bh_tested=int(len(F)), bh_survive=int(F["bh"].sum()),
                bh_by_kind=F.groupby("kind")["bh"].agg(["sum", "count"]).to_dict())
    with open(REP / "summary.json", "w") as f:
        json.dump(summ, f, indent=1, default=lambda o: o if not isinstance(o, np.generic) else o.item())
    print(json.dumps(summ, indent=1, default=str), flush=True)


if __name__ == "__main__":
    mode = os.environ.get("MODE", "agg")
    if mode == "agg":
        agg()
    else:
        import fxml_plots
        fxml_plots.main()
