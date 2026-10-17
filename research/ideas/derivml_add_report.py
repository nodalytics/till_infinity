"""Deriv ML addendum: the metrics (derivml_addendum.json) for the price, return, volatility, range-breakout,
forward-trend and sequence-model results, with day-bootstrap intervals, behavioural (real minus null) skill
and the combined Benjamini-Hochberg family (main rule secondaries + addendum).

Reads OUT/add/*.pkl, OUT/seq/*.pkl, OUT/pred/*.pkl (our own pickles) and OUT/report/bh.csv; writes
OUT/report/add_*.csv, OUT/report/vol_metrics.csv, OUT/report/bh_all.csv, OUT/report/add_summary.json.

  OUT=... python research/ideas/derivml_add_report.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import derivml_data as D  # noqa: E402
import derivml_models as M  # noqa: E402
import derivml_report as R  # noqa: E402

OUT = D.OUT
REP = OUT / "report"
ADDD = OUT / "add"
SEQD = OUT / "seq"
PRICE = ("c1", "h1", "l1", "ck")
RETS = ("lr1", "lr3", "lr6", "lr12", "oc1")
JUMPYRB = ("JUMPY", "RB")


def load_add(tf, grp, src):
    p = ADDD / f"{tf}_{grp}_{src}.pkl"
    return pd.read_pickle(p) if p.exists() else None  # our own pickle


def load_seq(tf, grp, src):
    p = SEQD / f"{tf}_{grp}_{src}.pkl"
    return pd.read_pickle(p) if p.exists() else None  # our own pickle


SEQ_MAP = {"z1": "lr1", "zk": "ck", "tr_sgn20": "tr_sgn20", "tr_slope20": "tr_slope20", "bup5": "bup5",
           "bdn5": "bdn5", "rup50_5": "rup50_5", "rdn50_5": "rdn50_5"}


def preds_for(add, seq, tgt):
    P = dict(add["targets"][tgt]["pred"])
    if seq is not None:
        inv = {v: k for k, v in SEQ_MAP.items()}
        h = inv.get(tgt)
        if h in seq["heads"]:
            j = seq["heads"].index(h)
            for kind in ("lstm", "gru"):
                P[kind] = seq["pred"][kind][:, j]
    return P


def masks(add, tgt, grp, c, spike):
    tg = add["targets"][tgt]
    sel = tg["masks"]["conf"] & np.isfinite(tg["y"])
    if c != "POOL":
        sel &= add["cls"] == c
    if spike == "without":
        hh = add["hz"][tgt]
        col = f"spkwin{hh}"
        if col in add["extra"]:
            sel &= ~add["extra"][col].to_numpy(bool)
    return sel


def spikes_for(grp):
    return ("with", "without") if grp in JUMPYRB else ("with",)


def boots():
    B = {}
    for tf in D.TFS:
        for g in D.GROUPS:
            if (OUT / f"ds_{tf}_{g}_real.pkl").exists():
                B[(tf, g)] = R.boots_for(tf, g)[0]
    return B


# ------------------------------------------------------------------------------------------ regression

def mz(y, p):
    ok = np.isfinite(y) & np.isfinite(p)
    if ok.sum() < 30 or np.std(p[ok]) == 0:
        return np.nan, np.nan
    b, a = np.polyfit(p[ok], y[ok], 1)
    return float(a), float(b)


def reg_tables(Bs):
    rows, beh = [], []
    for (tf, g), B in Bs.items():
        for spike in spikes_for(g):
            for c in R.classes(g):
                stats = {}
                for s in D.SOURCES[g]:
                    add, seq = load_add(tf, g, s), load_seq(tf, g, s)
                    if add is None:
                        continue
                    for tgt, tg in add["targets"].items():
                        if tg["kind"] != "reg":
                            continue
                        sel = masks(add, tgt, g, c, spike)
                        if sel.sum() < 100:
                            continue
                        ts = add["ts"][sel]
                        y = tg["y"][sel].astype(float)
                        P = preds_for(add, seq, tgt)
                        is_price = tgt in PRICE
                        is_ret = tgt in RETS
                        ref0 = P["naive"][sel].astype(float) if "naive" in P else np.zeros(len(y))
                        refm = P["mean"][sel].astype(float) if "mean" in P else None
                        if tgt.startswith("tr_slope"):
                            ref0 = np.zeros(len(y))
                            pers = add["extra"][f"pers_slope{tgt[8:]}"].to_numpy(float)[sel]
                            refm = pers
                        if tgt.startswith("tr_R"):
                            ref0 = np.full(len(y), np.nan)
                            refm = add["extra"][f"pers_R{tgt[4:]}"].to_numpy(float)[sel]
                        unit = add["extra"]["unit"].to_numpy(float)[sel]
                        for nm, f in P.items():
                            if nm in ("naive", "mean"):
                                continue
                            p = f[sel].astype(float)
                            ok = np.isfinite(p) & np.isfinite(y)
                            if ok.sum() < 100:
                                continue
                            e2 = (p - y) ** 2
                            r = dict(tf=tf, group=g, cls=c, spike=spike, source=s, target=tgt, model=nm, n=int(ok.sum()),
                                     rmse=float(np.sqrt(np.nanmean(e2[ok]))), mae=float(np.nanmean(np.abs(p - y)[ok])),
                                     corr=float(np.corrcoef(p[ok], y[ok])[0, 1]) if np.std(p[ok]) > 0 else np.nan,
                                     r2=float(1 - np.nansum(e2[ok]) / np.nansum((y[ok] - y[ok].mean()) ** 2)))
                            r["mz_a"], r["mz_b"] = mz(y, p)
                            if is_price or is_ret or tgt.startswith("tr_slope"):
                                r["da"] = float(np.mean(np.sign(p[ok]) == np.sign(y[ok])))
                            for refname, ref in (("zero", ref0), ("mean", refm)):
                                if ref is None or not np.isfinite(ref).any():
                                    continue
                                n2 = (ref - y) ** 2
                                pt, dr = B.ratio(ts, np.where(ok, e2, np.nan), np.where(ok, n2, np.nan))
                                lo, hi = R.ci(-dr)
                                r[f"r2os_{refname}"], r[f"r2os_{refname}_lo"], r[f"r2os_{refname}_hi"] = -pt, lo, hi
                                r[f"p_{refname}"] = R.p_le0(-dr)
                                stats[(s, tgt, nm, refname)] = (-pt, -dr)
                                # Diebold-Mariano: day-clustered t of the loss differential
                                dd = pd.Series(e2 - n2)[ok].groupby(ts[ok] // 86400).mean()
                                r[f"dm_t_{refname}"] = float(dd.mean() / (dd.std(ddof=1) / np.sqrt(len(dd)))) if len(dd) > 2 else np.nan
                            if is_price:
                                # levels: price = C_t + ATR_t x move; ATR_t / C_t = unit
                                cl = 1.0
                                lev_y = cl + y * unit
                                lev_p = cl + p * unit
                                lev_n = cl + ref0 * unit
                                r["theil_u"] = float(np.sqrt(np.nanmean(e2[ok]) / np.nanmean(((ref0 - y) ** 2)[ok])))
                                r["mape"] = float(np.nanmean(np.abs((lev_p - lev_y) / lev_y)[ok]))
                                r["mape_naive"] = float(np.nanmean(np.abs((lev_n - lev_y) / lev_y)[ok]))
                            rows.append(r)
                # behavioural R2_OS: real minus each null, per target and model
                for (s, tgt, nm, refname), (pt, dr) in list(stats.items()):
                    if s != "real":
                        continue
                    for w in R.nulls(g):
                        if (w, tgt, nm, refname) in stats:
                            pw, dw = stats[(w, tgt, nm, refname)]
                            lo, hi = R.ci(dr - dw)
                            beh.append(dict(tf=tf, group=g, cls=c, spike=spike, target=tgt, model=nm, ref=refname,
                                            null=w, r2os_real=pt, r2os_null=pw, diff=pt - pw, lo=lo, hi=hi,
                                            p=R.p_le0(dr - dw)))
    return pd.DataFrame(rows), pd.DataFrame(beh)


def level_r2_table(Bs):
    """Level R2 on raw prices for c1: the model and naive both near 1 (the point the desk asked to state)."""
    rows = []
    for (tf, g), _ in Bs.items():
        for s in D.SOURCES[g]:
            add = load_add(tf, g, s)
            if add is None or "c1" not in add["targets"]:
                continue
            m = pd.read_pickle(OUT / f"ds_{tf}_{g}_{s}.pkl")["rows"][["close", "atr"]]  # our own pickle
            tg = add["targets"]["c1"]
            sel = tg["masks"]["conf"] & np.isfinite(tg["y"])
            C, A = m["close"].to_numpy(float)[sel], m["atr"].to_numpy(float)[sel]
            y = C + tg["y"][sel] * A
            for nm in ("hgb", "linear", "naive"):
                p = C + tg["pred"][nm][sel].astype(float) * A
                ok = np.isfinite(p) & np.isfinite(y)
                # per series (prices are not comparable across indices), averaged
                r2s = []
                for sym in np.unique(add["sym"][sel]):
                    k = ok & (add["sym"][sel] == sym)
                    if k.sum() > 30:
                        r2s.append(1 - np.sum((p[k] - y[k]) ** 2) / np.sum((y[k] - y[k].mean()) ** 2))
                rows.append(dict(tf=tf, group=g, source=s, model=nm, level_r2_mean=float(np.mean(r2s)),
                                 level_r2_min=float(np.min(r2s)), n_series=len(r2s)))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------ IC and long-short

def ic_tables(Bs):
    rows, ls = [], []
    for (tf, g), B in Bs.items():
        for s in D.SOURCES[g]:
            add, seq = load_add(tf, g, s), load_seq(tf, g, s)
            if add is None:
                continue
            cost = pd.read_pickle(OUT / f"ds_{tf}_{g}_{s}.pkl")["rows"]["cost_atr"].to_numpy(float)  # our own pickle
            for tgt in RETS + tuple(f"tr_slope{H}" for H in (5, 10, 20, 50, 100)):
                if tgt not in add["targets"]:
                    continue
                tg = add["targets"][tgt]
                sel = tg["masks"]["conf"] & np.isfinite(tg["y"])
                ts = add["ts"]
                P = preds_for(add, seq, tgt)
                for nm, f in P.items():
                    if nm in ("naive", "mean"):
                        continue
                    df = pd.DataFrame({"ts": ts[sel], "p": f[sel].astype(float), "y": tg["y"][sel].astype(float),
                                       "cost": cost[sel], "unit": add["extra"]["unit"].to_numpy(float)[sel]}).dropna()
                    g_ = df.groupby("ts")
                    cnt = g_["y"].transform("size")
                    df = df[cnt >= 3]
                    if len(df) < 300:
                        continue
                    ic = df.groupby("ts").apply(lambda x: x["p"].corr(x["y"]) if x["p"].std() > 0 else np.nan)
                    ric = df.groupby("ts").apply(lambda x: x["p"].rank().corr(x["y"].rank()) if x["p"].std() > 0 else np.nan)
                    tsu = ic.index.to_numpy(np.int64)
                    for nm2, ser in (("ic", ic), ("rank_ic", ric)):
                        pt, dr = B.mean(tsu, ser.to_numpy(float))
                        lo, hi = R.ci(dr)
                        rows.append(dict(tf=tf, group=g, source=s, target=tgt, model=nm, stat=nm2, value=pt, lo=lo,
                                         hi=hi, p=R.p_le0(dr), n_times=int(np.isfinite(ser).sum())))
                    if tgt in ("lr1", "lr6"):
                        kk = int(tgt[2:])

                        def leg(x):
                            q = x["p"].rank(pct=True)
                            lo_, hi_ = x[q <= 1 / 3], x[q >= 2 / 3]
                            # raw log return = scaled y x unit; cost = half spread per leg per change, as log
                            r_ = hi_["y"].mul(hi_["unit"]).mean() - lo_["y"].mul(lo_["unit"]).mean()
                            c_ = (hi_["cost"].mul(hi_["unit"]).mean() + lo_["cost"].mul(lo_["unit"]).mean()) / kk
                            return pd.Series({"gross": r_ / kk, "net": r_ / kk - c_})
                        L = df.groupby("ts").apply(leg)
                        tsl = L.index.to_numpy(np.int64)
                        ann = np.sqrt(365 * 86400 / D.SEC[tf])
                        for col in ("gross", "net"):
                            x = L[col].to_numpy(float)
                            day = pd.Series(x).groupby(tsl // 86400).sum()
                            sh = float(day.mean() / day.std() * np.sqrt(365)) if day.std() > 0 else np.nan
                            rng = np.random.default_rng(7)
                            dv = day.to_numpy()
                            bs = [np.mean(v) / np.std(v) * np.sqrt(365) for v in
                                  (dv[rng.integers(0, len(dv), len(dv))] for _ in range(300)) if np.std(v) > 0]
                            ls.append(dict(tf=tf, group=g, source=s, target=tgt, model=nm, kind=col, sharpe=sh,
                                           lo=float(np.quantile(bs, 0.05)), hi=float(np.quantile(bs, 0.95)),
                                           mean_bar=float(np.mean(x)), n_times=len(x)))
                        del ann
    return pd.DataFrame(rows), pd.DataFrame(ls)


# ------------------------------------------------------------------------------------------ classification

def auc_multi(B, ts, y, P):
    """One-vs-rest macro AUC for 3 classes, with day-bootstrap draws."""
    pts, drs = [], []
    for k in range(3):
        pt, dr = B.auc(ts, (y == k).astype(float), P[:, k])
        pts.append(pt)
        drs.append(dr)
    return float(np.nanmean(pts)), np.nanmean(np.stack(drs), 0)


def cls_tables(Bs):
    rows, beh, gap = [], [], []
    for (tf, g), B in Bs.items():
        for spike in spikes_for(g):
            for c in R.classes(g):
                stats = {}
                for s in D.SOURCES[g]:
                    add, seq = load_add(tf, g, s), load_seq(tf, g, s)
                    if add is None:
                        continue
                    for tgt, tg in add["targets"].items():
                        if tg["kind"] == "reg":
                            continue
                        sel = masks(add, tgt, g, c, spike)
                        if sel.sum() < 100:
                            continue
                        ts = add["ts"][sel]
                        y = tg["y"][sel].astype(float)
                        P = preds_for(add, seq, tgt)
                        # persistence baselines for the trend labels
                        if tgt.startswith("tr_sgn"):
                            key = tgt[6:]
                            col = f"pers_slope{key}" if "_" not in key else f"pers_sgn{key}"
                            if col in add["extra"]:
                                P = dict(P, persistence=add["extra"][col].to_numpy(np.float32))
                        if tgt.startswith(("tr_cls", "tr_mcfl")):
                            col = "pers_cls" + tgt[6:] if tgt.startswith("tr_cls") else "pers_mcfl" + tgt[7:]
                            pc = add["extra"][col].to_numpy(float)
                            oh = np.zeros((len(pc), 3), np.float32)
                            okp = np.isfinite(pc)
                            oh[okp, pc[okp].astype(int)] = 1.0
                            P = dict(P, persistence=oh)
                        for nm, f in P.items():
                            f = np.asarray(f)
                            p = f[sel].astype(float)
                            if tg["kind"] == "multi":
                                if p.ndim != 2:
                                    continue
                                pt, dr = auc_multi(B, ts, y, p)
                                br = float(np.mean(((np.eye(3)[np.nan_to_num(y).astype(int)] - p) ** 2).sum(1)))
                            else:
                                if p.ndim != 1:
                                    continue
                                pt, dr = B.auc(ts, y, p)
                                br = float(np.nanmean((p - y) ** 2)) if nm != "persistence" else np.nan
                            lo, hi = R.ci(dr)
                            stats[(s, tgt, nm)] = (pt, dr)
                            rows.append(dict(tf=tf, group=g, cls=c, spike=spike, source=s, target=tgt, model=nm,
                                             n=int(sel.sum()), auc=pt, lo=lo, hi=hi, brier=br, base=float(np.nanmean(y)),
                                             p_auc=R.p_le0(dr - 0.5)))
                        # Brier skill and the calibration gap against the first-passage baseline
                        if "fp" in P:
                            pf = P["fp"][sel].astype(float)
                            for nm in [m for m in P if m not in ("fp", "persistence")]:
                                p = np.asarray(P[nm])[sel].astype(float)
                                if p.ndim != 1:
                                    continue
                                pt, dr = B.ratio(ts, (p - y) ** 2, (pf - y) ** 2)
                                lo, hi = R.ci(-dr)
                                rows.append(dict(tf=tf, group=g, cls=c, spike=spike, source=s, target=tgt, model=nm,
                                                 vs="fp", bss=-pt, lo=lo, hi=hi, p_bss=R.p_le0(-dr)))
                            pt, dr = B.mean(ts, y - pf)
                            gap.append(dict(tf=tf, group=g, cls=c, spike=spike, source=s, target=tgt, gap=pt,
                                            draws=dr, rate=float(y.mean()), fp_mean=float(pf.mean())))
                for (s, tgt, nm), (pt, dr) in list(stats.items()):
                    if s != "real":
                        continue
                    base = "fp" if (s, tgt, "fp") in stats else "persistence" if (s, tgt, "persistence") in stats else None
                    for w in R.nulls(g):
                        if (w, tgt, nm) not in stats:
                            continue
                        pw, dw = stats[(w, tgt, nm)]
                        lo, hi = R.ci(dr - dw)
                        r = dict(tf=tf, group=g, cls=c, spike=spike, target=tgt, model=nm, null=w, auc_real=pt,
                                 auc_null=pw, diff=pt - pw, lo=lo, hi=hi, p=R.p_le0(dr - dw))
                        if base and nm != base and (w, tgt, base) in stats:
                            d2 = (dr - stats[(s, tgt, base)][1]) - (dw - stats[(w, tgt, base)][1])
                            p2 = (pt - stats[(s, tgt, base)][0]) - (pw - stats[(w, tgt, base)][0])
                            r["over_base"], (r["over_base_lo"], r["over_base_hi"]) = p2, R.ci(d2)
                            r["p_over_base"] = R.p_le0(d2)
                        beh.append(r)
    G = pd.DataFrame(gap)
    out_gap = []
    if len(G):
        for (tf, g, c, spike, tgt), x in G.groupby(["tf", "group", "cls", "spike", "target"]):
            if not (x.source == "real").any():
                continue
            xr = x[x.source == "real"].iloc[0]
            for _, xn in x[x.source != "real"].iterrows():
                d = xr.draws - xn.draws
                lo, hi = R.ci(d)
                out_gap.append(dict(tf=tf, group=g, cls=c, spike=spike, target=tgt, null=xn.source, gap_real=xr.gap,
                                    gap_null=xn.gap, diff=xr.gap - xn.gap, lo=lo, hi=hi,
                                    p=min(R.p_le0(d), R.p_le0(-d)) * 2, rate_real=xr.rate, fp_real=xr.fp_mean))
    return pd.DataFrame(rows), pd.DataFrame(beh), pd.DataFrame(out_gap)


def set_and_cqr_tables():
    srows, crows = [], []
    for tf in D.TFS:
        for g in D.GROUPS:
            for s in D.SOURCES[g]:
                add = load_add(tf, g, s)
                if add is None:
                    continue
                for tgt, tg in add["targets"].items():
                    if "sets" in tg:
                        sel = tg["masks"]["conf"] & np.isfinite(tg["y"])
                        for meth, (i1, i0) in tg["sets"].items():
                            a1, a0, yy = i1[sel], i0[sel], tg["y"][sel]
                            single = (a1.astype(int) + a0.astype(int)) == 1
                            right = single & (np.where(a1, 1.0, 0.0) == yy)
                            srows.append(dict(tf=tf, group=g, source=s, target=tgt, method=meth,
                                              cover=float(np.mean(np.where(yy == 1, a1, a0))),
                                              singleton=float(single.mean()),
                                              single_acc=float(right.sum() / max(single.sum(), 1)), base=float(yy.mean())))
                    if "cqr" in tg:
                        y = tg["y"].astype(float)
                        sel = tg["masks"]["conf"] & np.isfinite(y)
                        for nm, meths in tg["cqr"].items():
                            for meth, (lo, hi) in meths.items():
                                ok = sel & np.isfinite(lo) & np.isfinite(hi)
                                if ok.sum() < 100:
                                    continue
                                crows.append(dict(tf=tf, group=g, source=s, target=tgt, model=nm, method=meth,
                                                  cover=float(np.mean((y[ok] >= lo[ok]) & (y[ok] <= hi[ok]))),
                                                  width=float(np.mean(hi[ok] - lo[ok]))))
    return pd.DataFrame(srows), pd.DataFrame(crows)


def seed_spread():
    rows = []
    for p in sorted(SEQD.glob("*.pkl")):
        q = pd.read_pickle(p)  # our own pickle
        add = load_add(q["tf"], q["group"], q["source"])
        if add is None:
            continue
        ds = pd.read_pickle(OUT / f"ds_{q['tf']}_{q['group']}_{q['source']}.pkl")["rows"]  # our own pickle
        conf = ds["ts"].to_numpy() >= ds["split"].to_numpy()
        for kind, S in q["seeds"].items():
            for j, h in enumerate(q["seed_heads"]):
                for k in range(S.shape[0]):
                    p_ = S[k][:, j].astype(float)
                    if h == "sign1":
                        y = ds["sign1"].to_numpy(float)
                        ok = conf & np.isfinite(y) & np.isfinite(p_)
                        from sklearn.metrics import roc_auc_score
                        val = roc_auc_score(y[ok], p_[ok]) if len(np.unique(y[ok])) > 1 else np.nan
                    else:
                        tg = add["targets"]["lr1"]
                        y = tg["y"].astype(float)
                        ok = tg["masks"]["conf"] & np.isfinite(y) & np.isfinite(p_)
                        val = 1 - np.sum((p_[ok] - y[ok]) ** 2) / np.sum(y[ok] ** 2)
                    rows.append(dict(tf=q["tf"], group=q["group"], source=q["source"], kind=kind, head=h, seed=k,
                                     metric="auc" if h == "sign1" else "r2os_zero", value=float(val), window=q["window"]))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------ B: volatility metrics

def vol_metrics(Bs):
    rows = []
    for (tf, g), B in Bs.items():
        for tgt in ("rvk", "range1", "absret1"):
            for s in D.SOURCES[g]:
                pr = R.load_pred(tf, g, s, tgt)
                if pr is None:
                    continue
                m = R.meta(tf, g, s)
                for c in R.classes(g):
                    sel = R.scored(pr, m, c)
                    if sel.sum() < 100:
                        continue
                    ts = m["ts"].to_numpy(np.int64)[sel]
                    z = M.model_target(tgt, pr["y"][sel].astype(float))
                    ly = np.log(np.maximum(z, M.EPS))
                    refs = {k: np.log(np.maximum(pr["pred"][k][sel].astype(float), M.EPS)) for k in ("har", "gen")
                            if k in pr["pred"]}
                    for nm, f in pr["pred"].items():
                        lp = np.log(np.maximum(f[sel].astype(float), M.EPS))
                        e2 = (lp - ly) ** 2
                        r = dict(tf=tf, group=g, cls=c, source=s, target=tgt, model=nm, n=int(sel.sum()),
                                 r2_log=float(1 - e2.sum() / ((ly - ly.mean()) ** 2).sum()),
                                 qlike=float(np.mean(M.qlike(z, f[sel].astype(float)))),
                                 corr_log=float(np.corrcoef(lp, ly)[0, 1]) if np.std(lp) > 0 else np.nan)
                        r["mz_a"], r["mz_b"] = mz(ly, lp)
                        for k, lr_ in refs.items():
                            if k == nm:
                                continue
                            pt, dr = B.ratio(ts, e2, (lr_ - ly) ** 2)
                            lo, hi = R.ci(-dr)
                            r[f"r2os_{k}"], r[f"r2os_{k}_lo"], r[f"r2os_{k}_hi"], r[f"p_{k}"] = -pt, lo, hi, R.p_le0(-dr)
                        rows.append(r)
    return pd.DataFrame(rows)


def main():
    REP.mkdir(parents=True, exist_ok=True)
    Bs = boots()
    vm = vol_metrics(Bs)
    vm.to_csv(REP / "vol_metrics.csv", index=False)
    print("vol metrics done", flush=True)
    rg, rb = reg_tables(Bs)
    rg.to_csv(REP / "add_reg.csv", index=False)
    rb.to_csv(REP / "add_reg_behavioural.csv", index=False)
    level_r2_table(Bs).to_csv(REP / "add_level_r2.csv", index=False)
    print("regression done", flush=True)
    ic, ls = ic_tables(Bs)
    ic.to_csv(REP / "add_ic.csv", index=False)
    ls.to_csv(REP / "add_longshort.csv", index=False)
    print("ic done", flush=True)
    ct, cb, gp = cls_tables(Bs)
    ct.to_csv(REP / "add_cls.csv", index=False)
    cb.to_csv(REP / "add_cls_behavioural.csv", index=False)
    gp.to_csv(REP / "add_roundnumbers.csv", index=False)
    st, cq = set_and_cqr_tables()
    st.to_csv(REP / "add_sets.csv", index=False)
    cq.to_csv(REP / "add_cqr.csv", index=False)
    seed_spread().to_csv(REP / "add_seeds.csv", index=False)
    print("classification done", flush=True)
    # the combined BH family: the main secondaries plus the addendum
    fam = []
    if (REP / "bh.csv").exists():
        b = pd.read_csv(REP / "bh.csv")
        fam += [dict(kind=r.kind, group=r.group, key=r.key, p=r.p) for r in b.itertuples()]
    for r in rg[rg.source == "real"].itertuples():
        for ref in ("zero", "mean"):
            pv = getattr(r, f"p_{ref}", np.nan)
            if np.isfinite(pv):
                fam.append(dict(kind=f"add r2os>{ref}", group=r.group,
                                key=f"{r.tf} {r.group} {r.cls} {r.spike} {r.target} {r.model} vs {ref}", p=pv))
    for r in rb.itertuples():
        fam.append(dict(kind="add behavioural r2os", group=r.group,
                        key=f"{r.tf} {r.group} {r.cls} {r.spike} {r.target} {r.model} {r.ref} real-{r.null}", p=r.p))
    for r in ct[(ct.source == "real") & ct.get("p_auc", pd.Series(dtype=float)).notna()].itertuples():
        if r.model in ("fp", "persistence"):
            continue
        fam.append(dict(kind="add auc>0.5", group=r.group, key=f"{r.tf} {r.group} {r.cls} {r.spike} {r.target} {r.model}",
                        p=r.p_auc))
    if "p_bss" in ct:
        for r in ct[(ct.source == "real") & ct.p_bss.notna()].itertuples():
            fam.append(dict(kind="add beats first passage", group=r.group,
                            key=f"{r.tf} {r.group} {r.cls} {r.spike} {r.target} {r.model} bss vs fp", p=r.p_bss))
    for r in cb.itertuples():
        fam.append(dict(kind="add behavioural auc", group=r.group,
                        key=f"{r.tf} {r.group} {r.cls} {r.spike} {r.target} {r.model} real-{r.null}", p=r.p))
        if hasattr(r, "p_over_base") and np.isfinite(getattr(r, "p_over_base", np.nan)):
            fam.append(dict(kind="add behavioural over baseline", group=r.group,
                            key=f"{r.tf} {r.group} {r.cls} {r.spike} {r.target} {r.model} over base real-{r.null}",
                            p=r.p_over_base))
    for r in ic[ic.source == "real"].itertuples():
        fam.append(dict(kind=f"add {r.stat}>0", group=r.group, key=f"{r.tf} {r.group} {r.target} {r.model} {r.stat}", p=r.p))
    if len(gp):
        for r in gp.itertuples():
            fam.append(dict(kind="add round numbers", group=r.group,
                            key=f"{r.tf} {r.group} {r.cls} {r.spike} {r.target} gap real-{r.null}", p=r.p))
    F = pd.DataFrame(fam)
    F["bh"] = R.bh(F["p"].to_numpy())
    F.to_csv(REP / "bh_all.csv", index=False)
    summ = dict(bh_tested=int(len(F)), bh_survive=int(F["bh"].sum()),
                by_kind=F.groupby("kind")["bh"].agg(["sum", "count"]).to_dict(),
                survivors=F[F.bh].sort_values("p").head(60).to_dict("records"))
    (REP / "add_summary.json").write_text(json.dumps(summ, indent=1, default=str))
    print(json.dumps({k: v for k, v in summ.items() if k != "survivors"}, indent=1, default=str), flush=True)
    print("survivors:", len(summ["survivors"]), flush=True)


if __name__ == "__main__":
    main()
