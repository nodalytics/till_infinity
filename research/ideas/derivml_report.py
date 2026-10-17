"""Deriv synthetics ML + ACI: aggregation, day bootstrap, Benjamini-Hochberg, the trade translation (bar fills
on DIFF/STEP, tick fills on BC/JUMP/RB) and the verdicts. Copied in structure from fx-metals-ml's
`fxml_report.py`, with groups, several nulls per group, the generator baselines and tick fills.

Reads OUT/ds_*.pkl, OUT/bars_*.pkl and OUT/pred/*.pkl (our own pickles, written by derivml_data.py and
derivml_models.py on the lab) and writes OUT/report/*.csv and OUT/report/summary.json.

  OUT=... MODE=agg python research/ideas/derivml_report.py
  OUT=... MODE=trades WORKERS=4 python research/ideas/derivml_report.py     (the trade translation)
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import derivml_data as D  # noqa: E402
import derivml_models as M  # noqa: E402

OUT = D.OUT
REP = OUT / "report"
IMG = REP / "img"
B_PRIMARY, B_SEC = 1000, 300
SEED = 7
NS = (1, 2, 4, 10)
TICK0 = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp())
TICK_FILL = ("BC", "JUMP", "RB")
CELLS = ("VOL2", "VOL1")


def nulls(grp):
    return [s for s in D.SOURCES[grp] if s != "real"]


def classes(grp):
    return ("POOL",) + D.CLASSES[grp]


def load_pred(tf, grp, src, tgt, part=""):
    p = OUT / "pred" / (f"{tf}_{grp}_{src}_{tgt}" + (f"_{part}" if part else "") + ".pkl")
    return pd.read_pickle(p) if p.exists() else None  # our own pickle


_ROWS = {}


def meta(tf, grp, src):
    key = (tf, grp, src)
    if key not in _ROWS:
        d = pd.read_pickle(OUT / f"ds_{tf}_{grp}_{src}.pkl")["rows"]  # our own pickle
        cols = ["sym", "cls", "ts", "bar", "split", "cost_atr", "atr", "close", "atr_ratio", "hour", "mfeL", "mfeS",
                "riskL", "riskS", "tstopL", "tstopS"]
        _ROWS[key] = d[cols].reset_index(drop=True)
    return _ROWS[key]


def cls_mask(m, c):
    if c == "POOL":
        return np.ones(len(m), bool)
    return (m["cls"] == c).to_numpy()


# ------------------------------------------------------------------------------------------ bootstrap (fxml)

class Boot:
    """Day bootstrap: whole UTC days of the confirmation rows, shared across sources (the nulls sit on the
    real timestamps, so the same days are resampled for real and null rows)."""

    def __init__(self, ts, draws, seed=SEED):
        self.days = np.unique(ts // 86400)
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, len(self.days), (draws, len(self.days)))
        self.C = np.stack([np.bincount(r, minlength=len(self.days)) for r in idx]).astype(np.float64)
        self.draws = draws

    def day(self, ts):
        return np.clip(np.searchsorted(self.days, ts // 86400), 0, len(self.days) - 1)

    def mean(self, ts, x):
        ok = np.isfinite(x)
        d = self.day(ts[ok])
        s = np.bincount(d, weights=x[ok], minlength=len(self.days))
        n = np.bincount(d, minlength=len(self.days)).astype(float)
        return s.sum() / max(n.sum(), 1), (self.C @ s) / np.maximum(self.C @ n, 1)

    def ratio(self, ts, x, y):
        ok = np.isfinite(x) & np.isfinite(y)
        d = self.day(ts[ok])
        sx = np.bincount(d, weights=x[ok], minlength=len(self.days))
        sy = np.bincount(d, weights=y[ok], minlength=len(self.days))
        return sx.sum() / sy.sum() - 1, (self.C @ sx) / (self.C @ sy) - 1

    def auc(self, ts, y, p):
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


def ci(dr, level=0.90):
    dr = dr[np.isfinite(dr)]
    if not len(dr):
        return np.nan, np.nan
    a = (1 - level) / 2
    return float(np.quantile(dr, a)), float(np.quantile(dr, 1 - a))


def p_le0(dr):
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


def scored(pr, m, c):
    return pr["masks"]["conf"] & cls_mask(m, c) & np.isfinite(pr["y"])


def brier(y, p):
    return (p - y) ** 2


def logloss(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def boots_for(tf, grp):
    m = meta(tf, grp, "real")
    ts = m["ts"].to_numpy(np.int64)
    ts = ts[ts >= m["split"].to_numpy(np.int64)]
    return Boot(ts, B_SEC), Boot(ts, B_PRIMARY)


def is_primary(tf, grp, tgt, c, which):
    P = M.P1 if which == 1 else M.P2
    return (tf, tgt) == P and grp == M.PRIMARY_GROUP and c in CELLS


# ------------------------------------------------------------------------------------------ risk

RISK_MODELS = ("hgb", "wf", "sgd", "ridge", "mlp", "garch", "ewma", "har", "envelope", "const", "gen_s", "gen")


def risk_tables(boots):
    rows, p1 = [], {}
    for (tf, grp), (Bs, Bp) in boots.items():
        for tgt in ("rvk", "range1", "absret1"):
            prs = {s: load_pred(tf, grp, s, tgt) for s in D.SOURCES[grp]}
            if any(v is None for v in prs.values()):
                continue
            for c in classes(grp):
                rel = {}
                for s in D.SOURCES[grp]:
                    pr, m = prs[s], meta(tf, grp, s)
                    sel = scored(pr, m, c)
                    if sel.sum() < 100:
                        continue
                    ts = m["ts"].to_numpy(np.int64)[sel]
                    z = M.model_target(tgt, pr["y"][sel])
                    loss = {}
                    for nm, f in pr["pred"].items():
                        ff = f[sel].astype(float)
                        loss[nm] = (ff - z) ** 2 if tgt == "absret1" else M.qlike(z, ff)
                        rows.append(dict(tf=tf, group=grp, target=tgt, cls=c, source=s, model=nm, n=int(sel.sum()),
                                         loss=float(np.nanmean(loss[nm])), mse=float(np.nanmean((ff - z) ** 2))))
                    for ref in ("har", "gen"):
                        if ref not in loss:
                            continue
                        prim = is_primary(tf, grp, tgt, c, 1)
                        B = Bp if prim else Bs
                        for nm in loss:
                            if nm == ref:
                                continue
                            pt, dr = B.ratio(ts, loss[nm], loss[ref])
                            rel[(s, nm, ref)] = (pt, dr)
                            lo, hi = ci(dr)
                            lo95, hi95 = ci(dr, 0.95)
                            rows.append(dict(tf=tf, group=grp, target=tgt, cls=c, source=s, model=nm, vs=ref, rel=pt,
                                             lo=lo, hi=hi, lo95=lo95, hi95=hi95, p=1 - p_le0(dr)))
                # behavioural part of the risk comparison: real relative change minus each null's
                for nl in nulls(grp):
                    for (s, nm, ref), (pt, dr) in list(rel.items()):
                        if s != "real" or (nl, nm, ref) not in rel:
                            continue
                        d = dr - rel[(nl, nm, ref)][1]
                        dp = pt - rel[(nl, nm, ref)][0]
                        lo, hi = ci(d)
                        rows.append(dict(tf=tf, group=grp, target=tgt, cls=c, source=f"real-{nl}", model=nm, vs=ref,
                                         rel=dp, lo=lo, hi=hi, p=1 - p_le0(d)))
                if is_primary(tf, grp, tgt, c, 1) and ("real", "hgb", "har") in rel:
                    pa, da = rel[("real", "hgb", "har")]
                    pg, dg = rel.get(("real", "hgb", "gen"), (np.nan, np.full(2, np.nan)))
                    out = dict(cell=c, beats_har=pa, beats_har_ci90=ci(da), beats_har_ci95=ci(da, 0.95),
                               vs_gen=pg, vs_gen_ci90=ci(dg), vs_gen_ci95=ci(dg, 0.95),
                               har_vs_gen=rel.get(("real", "har", "gen"), (np.nan,))[0])
                    out["pass_a"] = bool(out["beats_har_ci95"][1] < 0)
                    out["pass_b"] = bool(out["vs_gen_ci95"][1] < 0)
                    out["pass"] = out["pass_a"] and out["pass_b"]
                    chk = {}
                    for nl in nulls(grp):
                        if (nl, "hgb", "gen") in rel:
                            pn, dn = rel[(nl, "hgb", "gen")]
                            chk[nl] = dict(vs_gen=pn, ci90=ci(dn), leak=bool(ci(dn)[1] < 0))
                        if (nl, "hgb", "har") in rel:
                            chk.setdefault(nl, {})["beats_har"] = rel[(nl, "hgb", "har")][0]
                    out["method_check"] = chk
                    p1[c] = out
    return pd.DataFrame(rows), p1


def const_vol_check(boots):
    """Per instrument (DIFF and STEP): HGB, HAR and the const baseline against the generator's constant
    volatility on rvk, real and null, with realised / named sigma."""
    gp = D.gen_params()["series"]
    rows = []
    for (tf, grp), (Bs, _) in boots.items():
        if grp not in ("DIFF", "STEP"):
            continue
        for s in D.SOURCES[grp]:
            pr = load_pred(tf, grp, s, "rvk")
            if pr is None:
                continue
            m = meta(tf, grp, s)
            sel0 = pr["masks"]["conf"] & np.isfinite(pr["y"])
            z = pr["y"].astype(float)
            for sym, ix in m.groupby("sym", sort=False).indices.items():
                sel = np.zeros(len(m), bool)
                sel[ix] = True
                sel &= sel0
                if sel.sum() < 50:
                    continue
                ts = m["ts"].to_numpy(np.int64)[sel]
                lg = M.qlike(z[sel], pr["pred"]["gen"][sel].astype(float))
                r = dict(tf=tf, group=grp, source=s, sym=sym, cls=D.REG[sym]["cls"], n=int(sel.sum()),
                         qlike_gen=float(np.mean(lg)),
                         rv_over_gen=float(np.mean(z[sel]) / np.mean(pr["pred"]["gen"][sel].astype(float))))
                for nm in ("hgb", "har", "const", "wf"):
                    if nm not in pr["pred"]:
                        continue
                    pt, dr = Bs.ratio(ts, M.qlike(z[sel], pr["pred"][nm][sel].astype(float)), lg)
                    lo, hi = ci(dr)
                    r[f"{nm}_vs_gen"], r[f"{nm}_lo"], r[f"{nm}_hi"] = pt, lo, hi
                rep = gp.get(sym, {}).get("report", {})
                r["sigma_ratio_disc"] = rep.get("ratio_disc")
                r["up_share"] = rep.get("up_share")
                rows.append(r)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------ classes

def class_tables(boots):
    rows, p2, rel_rows = [], {}, []
    for (tf, grp), (Bs, Bp) in boots.items():
        for tgt in M.CLS:
            prs = {s: load_pred(tf, grp, s, tgt) for s in D.SOURCES[grp]}
            if any(v is None for v in prs.values()):
                continue
            for c in classes(grp):
                aucs = {}
                prim = is_primary(tf, grp, tgt, c, 2)
                B = Bp if prim else Bs
                for s in D.SOURCES[grp]:
                    pr, m = prs[s], meta(tf, grp, s)
                    sel = scored(pr, m, c)
                    if sel.sum() < 100:
                        continue
                    ts = m["ts"].to_numpy(np.int64)[sel]
                    y = pr["y"][sel].astype(float)
                    for nm, f in pr["pred"].items():
                        p = f[sel].astype(float)
                        a_pt, a_dr = B.auc(ts, y, p) if nm != "coin" else (0.5, np.full(B.draws, 0.5))
                        aucs[(s, nm)] = (a_pt, a_dr)
                        lo, hi = ci(a_dr)
                        bs = brier(y, p)
                        bc = brier(y, prs[s]["pred"]["coin"][sel].astype(float))
                        bss_pt, bss_dr = B.ratio(ts, bs, bc)
                        rows.append(dict(tf=tf, group=grp, target=tgt, cls=c, source=s, model=nm, n=int(sel.sum()),
                                         auc=a_pt, auc_lo=lo, auc_hi=hi, brier=float(np.nanmean(bs)),
                                         logloss=float(np.nanmean(logloss(y, p))), bss=-bss_pt,
                                         bss_lo=-ci(bss_dr)[1], bss_hi=-ci(bss_dr)[0],
                                         p_auc=p_le0(a_dr - 0.5) if nm != "coin" else np.nan,
                                         p_bss=p_le0(-bss_dr) if nm != "coin" else np.nan, base=float(np.nanmean(y))))
                for nm in prs["real"]["pred"]:
                    if nm == "coin":
                        continue
                    for w in nulls(grp):
                        if ("real", nm) in aucs and (w, nm) in aucs:
                            d = aucs[("real", nm)][1] - aucs[(w, nm)][1]
                            pt = aucs[("real", nm)][0] - aucs[(w, nm)][0]
                            lo, hi = ci(d)
                            rel_rows.append(dict(tf=tf, group=grp, target=tgt, cls=c, model=nm, null=w,
                                                 auc_real=aucs[("real", nm)][0], auc_null=aucs[(w, nm)][0],
                                                 diff=pt, lo=lo, hi=hi, p=p_le0(d)))
                if prim and ("real", prs["real"].get("best", "hgb")) in aucs:
                    best = prs["real"].get("best", "hgb")
                    out = dict(cell=c, model=best, choice=prs["real"].get("choice"))
                    a_pt, a_dr = aucs[("real", best)]
                    out["auc_real"], out["auc_real_ci90"] = a_pt, ci(a_dr)
                    ok = a_pt >= 0.510
                    for w in nulls(grp):
                        wb = prs[w].get("best", "hgb")
                        if (w, wb) not in aucs:
                            ok = False
                            continue
                        wpt, wdr = aucs[(w, wb)]
                        d = a_dr - wdr
                        out[f"auc_{w}"] = wpt
                        out[f"twin_model_{w}"] = wb
                        out[f"diff_{w}"] = a_pt - wpt
                        out[f"diff_{w}_ci90"] = ci(d)
                        out[f"diff_{w}_ci95"] = ci(d, 0.95)
                        ok = ok and out[f"diff_{w}_ci95"][0] > 0
                    out["pass"] = bool(ok)
                    p2[c] = out
    return pd.DataFrame(rows), pd.DataFrame(rel_rows), p2


def reliability(tf, grp, tgt, model="hgb", bins=10):
    out = []
    for s in D.SOURCES[grp]:
        pr = load_pred(tf, grp, s, tgt)
        if pr is None or model not in pr["pred"]:
            continue
        m = meta(tf, grp, s)
        sel = scored(pr, m, "POOL")
        p = pr["pred"][model][sel].astype(float)
        y = pr["y"][sel].astype(float)
        if len(p) < 100:
            continue
        q = np.quantile(p, np.linspace(0, 1, bins + 1))
        b = np.clip(np.searchsorted(q, p, side="right") - 1, 0, bins - 1)
        for k in range(bins):
            mm = b == k
            if mm.sum():
                out.append(dict(tf=tf, group=grp, target=tgt, source=s, model=model, bin=k, p=float(p[mm].mean()),
                                y=float(y[mm].mean()), n=int(mm.sum())))
    return out


# ------------------------------------------------------------------------------------------ conformal

def cqr_tables(boots):
    rows, series, widths = [], [], []
    for (tf, grp), (Bs, _) in boots.items():
        for tgt in ("rvk", "range1"):
            for s in D.SOURCES[grp]:
                pr = load_pred(tf, grp, s, tgt)
                if pr is None or "cqr" not in pr:
                    continue
                m = meta(tf, grp, s)
                ts_all = m["ts"].to_numpy(np.int64)
                ly = np.log(np.maximum(M.model_target(tgt, pr["y"].astype(float)), M.EPS))
                vt = pd.qcut(m["atr_ratio"].rank(method="first"), 3, labels=["calm", "normal", "volatile"]).to_numpy()
                month = pd.to_datetime(m["ts"], unit="s").dt.to_period("M").astype(str).to_numpy()
                for c in classes(grp):
                    sel0 = scored(pr, m, c)
                    covw = {}
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
                            r = dict(tf=tf, group=grp, target=tgt, source=s, cls=c, model=nm, method=meth,
                                     n=int(sel.sum()), cover=float(cov.mean()), width=float(np.mean(w)),
                                     winkler=float(np.mean(wink)))
                            for lab in ("calm", "normal", "volatile"):
                                mm = vt[sel] == lab
                                r[f"cover_{lab}"] = float(cov[mm].mean()) if mm.any() else np.nan
                            mo = pd.Series(cov).groupby(month[sel]).mean()
                            r["cover_month_sd"] = float(mo.std())
                            r["cover_month_min"] = float(mo.min())
                            rows.append(r)
                            if meth == "aci":
                                ww = np.full(len(m), np.nan)
                                ww[sel] = w
                                covw[nm] = (ww, float(cov.mean()))
                            if c == "POOL":
                                for k_, v_ in mo.items():
                                    series.append(dict(tf=tf, group=grp, target=tgt, source=s, model=nm, method=meth,
                                                       month=k_, cover=float(v_)))
                    # ML + ACI narrower than baseline + ACI at matched coverage (both within 0.88-0.92)
                    if "hgb" in covw:
                        for nm, (wb, cb) in covw.items():
                            if nm == "hgb":
                                continue
                            wh, ch = covw["hgb"]
                            ok = np.isfinite(wh) & np.isfinite(wb)
                            if ok.sum() < 100:
                                continue
                            pt, dr = Bs.ratio(ts_all[ok], wh[ok], wb[ok])
                            lo, hi = ci(dr)
                            widths.append(dict(tf=tf, group=grp, target=tgt, source=s, cls=c, vs=nm, width_rel=pt,
                                               lo=lo, hi=hi, p=1 - p_le0(dr), cover_hgb=ch, cover_base=cb,
                                               matched=bool(0.88 <= ch <= 0.92 and 0.88 <= cb <= 0.92)))
    return pd.DataFrame(rows), pd.DataFrame(series), pd.DataFrame(widths)


def set_tables():
    rows = []
    for tf in D.TFS:
        for grp in D.GROUPS:
            for tgt in M.CLS:
                for s in D.SOURCES[grp]:
                    pr = load_pred(tf, grp, s, tgt)
                    if pr is None or "sets" not in pr:
                        continue
                    m = meta(tf, grp, s)
                    y = pr["y"].astype(float)
                    for c in classes(grp):
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
                                rows.append(dict(tf=tf, group=grp, target=tgt, source=s, cls=c, model=nm, method=meth,
                                                 n=int(sel.sum()), cover=float(cov.mean()), size=float(size.mean()),
                                                 singleton=float(single.mean()), empty=float((size == 0).mean()),
                                                 single_acc=float(right.sum() / max(single.sum(), 1)), base=float(yy.mean())))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------ ablation, importance, CV

def ablation_tables(boots):
    rows = []
    for (tf, grp), (Bs, _) in boots.items():
        for tgt in M.ABL_TARGETS:
            prs = {s: load_pred(tf, grp, s, tgt, "abl") for s in D.SOURCES[grp]}
            if any(v is None for v in prs.values()):
                continue
            kind = "reg" if tgt in M.REG else "cls"
            for c in classes(grp):
                stats = {}
                for s in D.SOURCES[grp]:
                    pr, m = prs[s], meta(tf, grp, s)
                    sel = scored(pr, m, c)
                    if sel.sum() < 100:
                        continue
                    ts = m["ts"].to_numpy(np.int64)[sel]
                    y = pr["y"][sel].astype(float)
                    z = M.model_target(tgt, y) if kind == "reg" else y
                    for nm, f in pr["abl"].items():
                        p = f[sel].astype(float)
                        stats[(s, nm)] = Bs.auc(ts, z, p) if kind == "cls" else Bs.mean(ts, M.qlike(z, p))
                comps = (("hgb:B0", ("hgb:B0+S", "hgb:B0+P", "hgb:B0+C", "hgb:all", "hgb:all+Q", "hgb:all+J")),
                         ("hgb:all", ("hgb:all+Q", "hgb:all+J")), ("hgb:CO", ("hgb:OH",)),
                         ("lin:base", ("lin:base+Q", "lin:base+E", "lin:base+Eint", "lin:base+Q+E")),
                         ("lin:CO", ("lin:OH",)))
                for s in D.SOURCES[grp]:
                    for base, variants in comps:
                        if (s, base) not in stats:
                            continue
                        for v in variants:
                            if (s, v) not in stats:
                                continue
                            sign = 1 if kind == "cls" else -1
                            g_pt = sign * (stats[(s, v)][0] - stats[(s, base)][0])
                            g_dr = sign * (stats[(s, v)][1] - stats[(s, base)][1])
                            lo, hi = ci(g_dr)
                            rows.append(dict(tf=tf, group=grp, target=tgt, cls=c, source=s, base=base, variant=v,
                                             score_base=stats[(s, base)][0], score=stats[(s, v)][0], gain=g_pt,
                                             lo=lo, hi=hi, p=p_le0(g_dr)))
                            if s == "real":
                                for w in nulls(grp):
                                    if (w, v) in stats and (w, base) in stats:
                                        wg_dr = sign * (stats[(w, v)][1] - stats[(w, base)][1])
                                        wg_pt = sign * (stats[(w, v)][0] - stats[(w, base)][0])
                                        lo2, hi2 = ci(g_dr - wg_dr)
                                        rows.append(dict(tf=tf, group=grp, target=tgt, cls=c, source=f"real-{w}",
                                                         base=base, variant=v, gain=g_pt - wg_pt, lo=lo2, hi=hi2,
                                                         p=p_le0(g_dr - wg_dr)))
    return pd.DataFrame(rows)


def importance_tables():
    out = []
    for tf in D.TFS:
        for grp in D.GROUPS:
            for tgt in M.IMP_TARGETS:
                for s in ("real", "gen"):
                    pr = load_pred(tf, grp, s, tgt, "imp")
                    if pr is None:
                        continue
                    out.append(pr["imp"].assign(tf=tf, group=grp, target=tgt, source=s))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def cv_tables():
    rows = []
    for tf, tgt in (M.P1, M.P2):
        for s in D.SOURCES[M.PRIMARY_GROUP]:
            pr = load_pred(tf, M.PRIMARY_GROUP, s, tgt)
            if pr is None or "cv" not in pr:
                continue
            cv = pr["cv"]
            best = cv["score"].min() if tgt in M.REG else cv["score"].max()
            rows.append(dict(tf=tf, target=tgt, source=s, best=best, median=float(cv["score"].median()),
                             allowance=float(abs(best - cv["score"].median())), cfg=json.dumps(pr["cfg"]),
                             choice=json.dumps(pr.get("choice"))))
    return pd.DataFrame(rows)


def pnr_diag():
    rows = []
    for tf in D.TFS:
        for grp in D.GROUPS:
            for side, tgt in (("L", "nr2L"), ("S", "nr2S")):
                for s in D.SOURCES[grp]:
                    pr = load_pred(tf, grp, s, tgt)
                    if pr is None:
                        continue
                    m = meta(tf, grp, s)
                    p = pr["pred"]["hgb"].astype(float)
                    thr = np.nanquantile(p[pr["masks"]["cal_main"]], 0.9)
                    mfe = m[f"mfe{side}"].to_numpy(float)
                    for c in classes(grp):
                        base = pr["masks"]["conf"] & cls_mask(m, c) & np.isfinite(mfe)
                        for sel_name, sel in (("all", base), ("top10", base & (p >= thr))):
                            if sel.sum() < 30:
                                continue
                            r = dict(tf=tf, group=grp, side=side, source=s, cls=c, sel=sel_name, n=int(sel.sum()))
                            for n_ in NS:
                                r[f"P{n_}"] = float((mfe[sel] >= n_).mean())
                            rows.append(r)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------ the trade translation

def swap_per_night(sym, price):
    """Swap cost per rollover held, in price units (the bridge's symbol info)."""
    info = json.loads((D.DDATA / "info.json").read_text()).get(sym, {})
    mode = info.get("swap_mode")
    sl = abs(float(info.get("swap_long", 0.0) or 0.0))
    if mode == 5:
        return sl / 100 / 365 * price
    if mode == 1:
        return sl * float(info.get("point", 0.1))
    return 0.0


def nights(t0, t1):
    return int(max(0, t1 // 86400 - t0 // 86400))


def simulate_bars(bars, entries, swap_px):
    """fxml's bar replay (no jumps: DIFF, STEP), plus swap. Returns per trade dicts."""
    o, h, l, c = (bars[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = bars["atr"].to_numpy(float)
    cost_atr = bars["cost_atr"].to_numpy(float)
    tsb = bars["ts"].to_numpy(np.int64)
    sec = int(np.median(np.diff(tsb)))
    n = len(c)
    out = []
    for t, side in entries:
        if t + 1 >= n or not np.isfinite(a[t]):
            continue
        oo, hh, ll, cc = (-o, -l, -h, -c) if side < 0 else (o, h, l, c)
        E = oo[t + 1]
        stop0 = min(ll[max(t - 2, 0):t + 1]) - D.PAD * a[t]
        risk = max(E - stop0, D.MIN_RISK * a[t])
        stop0 = E - risk
        res = {n_: None for n_ in NS}
        trail, tr_res, mfe, stopped, stop_px = stop0, None, 0.0, False, None
        tstop = None
        for j in range(1, D.NR_CAP + 1):
            b = t + j
            if b >= n:
                break
            up = cc[b] >= oo[b]
            if not stopped:
                gap = oo[b] <= stop0
                hit = ll[b] <= stop0
                if gap:
                    stopped, stop_px = True, oo[b]
                elif hit and up:
                    stopped, stop_px = True, stop0
                else:
                    mfe = max(mfe, (hh[b] - E) / risk)
                    if hit:
                        stopped, stop_px = True, stop0
                for n_ in NS:
                    if res[n_] is None:
                        if mfe >= n_:
                            res[n_] = (float(n_), False, b)
                        elif stopped:
                            res[n_] = ((stop_px - E) / risk, True, b)
            if tr_res is None:
                if oo[b] <= trail:
                    tr_res = ((oo[b] - E) / risk, True, b)
                elif ll[b] <= trail:
                    tr_res = ((trail - E) / risk, True, b)
                else:
                    trail = max(trail, min(ll[max(b - 2, 0):b + 1]) - D.PAD * a[b])
            if stopped and tr_res is not None and all(v is not None for v in res.values()):
                break
        last = min(t + D.NR_CAP, n - 1)
        for n_ in NS:
            if res[n_] is None:
                res[n_] = ((cc[last] - E) / risk, False, last)
        if tr_res is None:
            tr_res = ((cc[last] - E) / risk, False, last)
        cost_R = cost_atr[t] * a[t] / risk
        slip_R = 0.05 * a[t] / risk
        t_in = tsb[t] + sec
        r = dict(t=t, side=side, risk_atr=risk / a[t], cost_R=cost_R, mfe=mfe, fill="bar")
        for n_ in NS:
            g, st, bx = res[n_]
            sw = nights(t_in, tsb[bx] + sec) * swap_px[t] / risk
            r[f"g{n_}"] = g
            r[f"net{n_}"] = g - cost_R - (slip_R if st else 0.0) - sw
        g, st, bx = tr_res
        sw = nights(t_in, tsb[bx] + sec) * swap_px[t] / risk
        r["gtrail"] = g
        r["nettrail"] = g - cost_R - (slip_R if st else 0.0) - sw
        out.append(r)
    return out


class Tape:
    """A tick tape (ms, bid, ask) for one series and source, from the tick store (real) or regenerated
    from the seeded null path (gen), over [t0, t1)."""

    def __init__(self, sym, src, bars, gp):
        self.sym, self.src, self.gp = sym, src, gp
        self.cache = {}
        if src == "gen":
            if gp["kind"] == "rb":
                z = np.load(OUT / "null" / f"gen_{D.slug(sym)}_sec.npz")
                self.rb_day0, self.rb_P = int(z["day0"]), z["P"]
            else:
                z = np.load(OUT / "null" / f"gen_{D.slug(sym)}.npz")
                self.day0, self.lev = int(z["day0"]), z["lev"]
                self.g = D.TickGen(sym, gp, int(z["seed"]))
        else:
            self.files = {int(np.datetime64(f.stem, "D").astype(np.int64)): f for f in D.tick_dir(sym).glob("*.npz")}

    def day(self, d):
        if d in self.cache:
            return self.cache[d]
        if len(self.cache) > 40:
            self.cache.pop(next(iter(self.cache)))
        if self.src == "gen":
            if self.gp["kind"] == "rb":
                a = (d - self.rb_day0) * 86400
                if a < 0 or a + 86400 > len(self.rb_P):
                    r = None
                else:
                    P = self.rb_P[a:a + 86400].astype(float)
                    r = (d * 86400000 + np.arange(86400, dtype=np.int64) * 1000, P)
            else:
                i = d - self.day0
                r = self.g.ticks(d, float(self.lev[i])) if 0 <= i < len(self.lev) else None
        else:
            f = self.files.get(d)
            if f is None:
                r = None
            else:
                z = np.load(f)
                ok = (z["bid"] > 0) & (z["ask"] > 0)
                r = (z["ms"][ok], z["bid"][ok], z["ask"][ok]) if ok.any() else None
        self.cache[d] = r
        return r


def tick_trade(tape, bars, t, side, spread_px, swap_px):
    """One trade filled on ticks: entry at the first tick after bar t's close (long at the ask, short at
    the bid), the 3-bar structural stop (0.1 ATR pad, 0.25 ATR minimum risk) set from the bars, fixed
    targets +N R and the trailing structural stop updated at each bar close; a stop or target fills at the
    first tick at or through it at that tick's price. Null tapes have no ask: ask = bid + the real spread
    in ATR units."""
    tsb = bars["ts"].to_numpy(np.int64)
    sec = int(np.median(np.diff(tsb[-200:])))
    h, l = bars["high"].to_numpy(float), bars["low"].to_numpy(float)
    a = bars["atr"].to_numpy(float)
    n = len(tsb)
    t_in = (tsb[t] + sec) * 1000
    cap_ms = (tsb[min(t + D.NR_CAP, n - 1)] + sec) * 1000
    d0 = t_in // 86400000
    lows = l if side > 0 else -h
    stop0_bar = min(lows[max(t - 2, 0):t + 1]) - D.PAD * a[t]
    E = None
    res = {n_: None for n_ in NS}
    trail = None
    tr_res = None
    mfe, mfe_g = 0.0, 0.0
    bnext = t + 1                          # the bar whose close next moves the trail
    d = d0
    while True:
        day = tape.day(d)
        if day is None:
            if d * 86400000 > cap_ms:
                break
            d += 1
            if d - d0 > 800:
                break
            continue
        if len(day) == 2:
            ms, bid = day
            ask = bid + spread_px
        else:
            ms, bid, ask = day
        k = (ms >= t_in) & (ms < cap_ms)
        ms, bid, ask = ms[k], bid[k], ask[k]
        if len(ms):
            if side > 0:
                ex, en, mid = bid, ask, (bid + ask) / 2
            else:
                ex, en, mid = -ask, -bid, -(bid + ask) / 2
            if E is None:
                E, Em = en[0], mid[0]
                sp_entry = float(en[0] - ex[0])
                risk = max(E - stop0_bar, D.MIN_RISK * a[t])
                stop0 = E - risk
                trail = stop0
                ms, ex, mid = ms[1:], ex[1:], mid[1:]
            # the trail moves at bar closes: split this day's ticks by the bar they fall in
            bar_ix = np.searchsorted(tsb * 1000, ms, side="right") - 1
            for b in np.unique(bar_ix):
                mk = bar_ix == b
                exb, msb, mdb = ex[mk], ms[mk], mid[mk]
                while bnext <= b - 1 and bnext < n:     # bars closed before this one: update the trail
                    if tr_res is None:
                        trail = max(trail, min(lows[max(bnext - 2, 0):bnext + 1]) - D.PAD * a[bnext])
                    bnext += 1
                if any(v is None for v in res.values()):
                    hit = np.flatnonzero(exb <= stop0)
                    i_st = hit[0] if len(hit) else len(exb)
                    if i_st > 0:
                        mfe = max(mfe, float((exb[:i_st].max() - E) / risk))
                        mfe_g = max(mfe_g, float((mdb[:i_st].max() - Em) / risk))
                    for n_ in NS:
                        if res[n_] is None:
                            tg = np.flatnonzero(exb[:i_st] >= E + n_ * risk)
                            if len(tg):
                                j = tg[0]
                                res[n_] = ((exb[j] - E) / risk, (mdb[j] - Em) / risk, False, msb[j])
                            elif i_st < len(exb):
                                res[n_] = ((exb[i_st] - E) / risk, (mdb[i_st] - Em) / risk, True, msb[i_st])
                if tr_res is None:
                    hit = np.flatnonzero(exb <= trail)
                    if len(hit):
                        j = hit[0]
                        tr_res = ((exb[j] - E) / risk, (mdb[j] - Em) / risk, True, msb[j])
                if tr_res is not None and all(v is not None for v in res.values()):
                    break
            if tr_res is not None and all(v is not None for v in res.values()):
                break
        d += 1
        if d * 86400000 > cap_ms:
            break
    if E is None:
        return None
    last_ex = ex[-1] if len(ms) else E
    last_md = mid[-1] if len(ms) else Em
    for n_ in NS:
        if res[n_] is None:
            res[n_] = ((last_ex - E) / risk, (last_md - Em) / risk, False, cap_ms)
    if tr_res is None:
        tr_res = ((last_ex - E) / risk, (last_md - Em) / risk, False, cap_ms)
    r = dict(t=t, side=side, risk_atr=risk / a[t], cost_R=sp_entry / risk, mfe=mfe, mfe_mid=mfe_g, fill="tick")
    for n_ in NS:
        net, g, st, msx = res[n_]
        sw = nights(t_in // 1000, msx // 1000) * swap_px / risk
        r[f"g{n_}"], r[f"net{n_}"], r[f"stop{n_}"] = g, net - sw, st
    net, g, st, msx = tr_res
    sw = nights(t_in // 1000, msx // 1000) * swap_px / risk
    r["gtrail"], r["nettrail"], r["stoptrail"] = g, net - sw, st
    return r


def trade_job(job):
    tf, grp, s, sym = job
    gp = D.gen_params()["series"][sym]
    pr = load_pred(tf, grp, s, "sign1")
    if pr is None:
        return []
    m = meta(tf, grp, s)
    bars = pd.read_pickle(OUT / f"bars_{tf}_{grp}_{s}.pkl")[sym].reset_index(drop=True)  # our own pickle
    best = pr.get("best", "hgb")
    i1, i0 = pr["sets"][best]["aci"]
    conf = pr["masks"]["conf"]
    ix = np.flatnonzero((m["sym"] == sym).to_numpy())
    bar = m["bar"].to_numpy()
    ent = [(int(bar[i]), 1) for i in ix if conf[i] and i1[i] and not i0[i]] + \
          [(int(bar[i]), -1) for i in ix if conf[i] and i0[i] and not i1[i]]
    c = bars["close"].to_numpy(float)
    swap_px = np.array([swap_per_night(sym, x) for x in c[:1]])[0] / c[0] * c   # proportional (mode 5) or flat
    info = json.loads((D.DDATA / "info.json").read_text()).get(sym, {})
    if info.get("swap_mode") == 1:
        swap_px = np.full(len(c), swap_per_night(sym, 0.0))
    out = []
    cls = D.REG[sym]["cls"]
    if cls in TICK_FILL:
        tape = Tape(sym, s, bars, gp)
        tsb = bars["ts"].to_numpy(np.int64)
        for t, side in ent:
            if tsb[t] < TICK0:
                continue
            spread_px = float(bars["cost_atr"].iloc[t] * bars["atr"].iloc[t]) if s != "real" else 0.0
            r = tick_trade(tape, bars, t, side, spread_px, float(swap_px[t]))
            if r is not None:
                out.append(r)
    else:
        out = simulate_bars(bars, ent, swap_px)
    tsb = bars["ts"].to_numpy(np.int64)
    for r in out:
        r.update(tf=tf, group=grp, source=s, sym=sym, cls=cls, ts=int(tsb[r["t"]]))
    return out


def trades():
    REP.mkdir(parents=True, exist_ok=True)
    jobs = []
    for tf in D.TFS:
        for grp in D.GROUPS:
            for s in D.SOURCES[grp]:
                p = OUT / f"ds_{tf}_{grp}_{s}.pkl"
                if not p.exists() or load_pred(tf, grp, s, "sign1") is None:
                    continue
                for sym in meta(tf, grp, s)["sym"].unique():
                    jobs.append((tf, grp, s, sym))
    allt = []
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 4))) as pool:
        for tr in pool.map(trade_job, jobs, chunksize=1):
            allt += tr
    T = pd.DataFrame(allt)
    T.to_pickle(REP / "trades.pkl")
    print(f"trades: {len(T)}", flush=True)


def trade_tables(boots):
    p = REP / "trades.pkl"
    if not p.exists():
        return pd.DataFrame()
    T = pd.read_pickle(p)  # our own pickle
    rows = []
    for (tf, grp), (Bs, _) in boots.items():
        for c in classes(grp):
            for s in D.SOURCES[grp]:
                x = T[(T.tf == tf) & (T.group == grp) & (T.source == s)]
                if c != "POOL":
                    x = x[x.cls == c]
                if len(x) < 30:
                    continue
                r = dict(tf=tf, group=grp, cls=c, source=s, n=len(x), fill=x.fill.iloc[0],
                         risk_atr=float(x.risk_atr.median()), cost_R=float(x.cost_R.mean()))
                for ex in [f"net{n_}" for n_ in NS] + ["nettrail", "gtrail"] + [f"g{n_}" for n_ in NS]:
                    pt, dr = Bs.mean(x.ts.to_numpy(np.int64), x[ex].to_numpy(float))
                    lo, hi = ci(dr)
                    r[ex], r[f"{ex}_lo"], r[f"{ex}_hi"] = pt, lo, hi
                for n_ in NS:
                    r[f"P{n_}"] = float((x.mfe >= n_).mean())
                rows.append(r)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------ main

def agg():
    REP.mkdir(parents=True, exist_ok=True)
    boots = {}
    for tf in D.TFS:
        for grp in D.GROUPS:
            if (OUT / f"ds_{tf}_{grp}_real.pkl").exists():
                boots[(tf, grp)] = boots_for(tf, grp)
    risk, p1 = risk_tables(boots)
    risk.to_csv(REP / "risk.csv", index=False)
    cv_ = const_vol_check(boots)
    cv_.to_csv(REP / "constvol.csv", index=False)
    print("risk done", flush=True)
    cls_t, rel_t, p2 = class_tables(boots)
    cls_t.to_csv(REP / "classes.csv", index=False)
    rel_t.to_csv(REP / "behavioural.csv", index=False)
    print("classes done", flush=True)
    rel = []
    for tf, grp in boots:
        for tgt in ("tup05", "tdn05", "tup10", "tdn10", "first", "sign1", "signk", "nr2L", "spk"):
            rel += reliability(tf, grp, tgt, "hgb")
            if tgt.startswith("t"):
                rel += reliability(tf, grp, tgt, "reflect")
    pd.DataFrame(rel).to_csv(REP / "reliability.csv", index=False)
    cq, cqs, cw = cqr_tables(boots)
    cq.to_csv(REP / "cqr.csv", index=False)
    cqs.to_csv(REP / "cqr_months.csv", index=False)
    cw.to_csv(REP / "cqr_width.csv", index=False)
    st = set_tables()
    st.to_csv(REP / "sets.csv", index=False)
    print("conformal done", flush=True)
    ab = ablation_tables(boots)
    ab.to_csv(REP / "ablation.csv", index=False)
    imp = importance_tables()
    imp.to_csv(REP / "importance.csv", index=False)
    cvt = cv_tables()
    cvt.to_csv(REP / "cv.csv", index=False)
    print("ablation done", flush=True)
    pn = pnr_diag()
    pn.to_csv(REP / "pnr.csv", index=False)
    tt = trade_tables(boots)
    tt.to_csv(REP / "trades.csv", index=False)
    print("trades done", flush=True)
    # Benjamini-Hochberg over the secondary family
    fam = []
    for _, x in risk[risk.get("vs").notna()].iterrows() if "vs" in risk else []:
        prim = (x.tf, x.target) == M.P1 and x.group == M.PRIMARY_GROUP and x.cls in CELLS and x.model == "hgb"
        if prim or not (x.source == "real" or str(x.source).startswith("real-")):
            continue
        fam.append(dict(kind=f"risk vs {x.vs}", group=x.group,
                        key=f"{x.tf} {x.group} {x.target} {x.cls} {x.source} {x.model} vs {x.vs}", p=x.p))
    for _, x in rel_t.iterrows():
        if (x.tf, x.target) == M.P2 and x.group == M.PRIMARY_GROUP and x.cls in CELLS:
            continue
        fam.append(dict(kind="behavioural", group=x.group,
                        key=f"{x.tf} {x.group} {x.target} {x.cls} {x.model} real-{x.null}", p=x.p))
    for _, x in cls_t[(cls_t.source == "real") & (cls_t.model != "coin")].iterrows():
        fam.append(dict(kind="auc>0.5", group=x.group, key=f"{x.tf} {x.group} {x.target} {x.cls} {x.model}", p=x.p_auc))
    for _, x in ab[ab.source.astype(str).str.startswith("real")].iterrows() if len(ab) else []:
        fam.append(dict(kind="ablation", group=x.group,
                        key=f"{x.tf} {x.group} {x.target} {x.cls} {x.source} {x.variant} over {x.base}", p=x.p))
    for _, x in cw[cw.source == "real"].iterrows() if len(cw) else []:
        fam.append(dict(kind="aci width", group=x.group,
                        key=f"{x.tf} {x.group} {x.target} {x.cls} hgb+aci vs {x.vs}+aci", p=x.p))
    F = pd.DataFrame(fam)
    F["bh"] = bh(F["p"].to_numpy())
    F.to_csv(REP / "bh.csv", index=False)
    summ = dict(P1=p1, P2=p2, bh_tested=int(len(F)), bh_survive=int(F["bh"].sum()),
                bh_by_kind=F.groupby("kind")["bh"].agg(["sum", "count"]).to_dict(),
                bh_by_group=F.groupby("group")["bh"].agg(["sum", "count"]).to_dict())
    with open(REP / "summary.json", "w") as f:
        json.dump(summ, f, indent=1, default=lambda o: o.item() if isinstance(o, np.generic) else str(o))
    print(json.dumps(summ, indent=1, default=str), flush=True)


if __name__ == "__main__":
    mode = os.environ.get("MODE", "agg")
    if mode == "agg":
        agg()
    elif mode == "trades":
        trades()
