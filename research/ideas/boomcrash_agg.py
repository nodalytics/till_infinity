"""Verdicts, tables and plots for boomcrash_trend.py (frozen in bc_rule.json).

Reads only the pickles boomcrash_trend.py wrote into its own OUT directory.
"""
from __future__ import annotations

import json
import pickle
from math import erf, sqrt

import numpy as np
from scipy.stats import t as student_t

import boomcrash_trend as B

F = B
CONF, DISC = 1, 0
NS = (1, 2, 4, 10)
PRETTY = {"boom_300": "Boom 300", "boom_500": "Boom 500", "boom_1000": "Boom 1000", "crash_300": "Crash 300",
          "crash_500": "Crash 500", "crash_1000": "Crash 1000"}


def load(p):
    with open(p, "rb") as f:   # our own pickles only
        return pickle.load(f)


def pnorm2(z):
    return 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2)))) if np.isfinite(z) else np.nan


def bh(p, q=0.10):
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    if not ok.any():
        return out
    idx = np.flatnonzero(ok)
    ps = p[idx]
    o = np.argsort(ps)
    m = len(ps)
    thr = q * np.arange(1, m + 1) / m
    passed = ps[o] <= thr
    if passed.any():
        k = np.max(np.flatnonzero(passed))
        out[idx[o[:k + 1]]] = True
    return out


# ------------------------------------------------------------------------------------- data shaping

class Run:
    """One path's aggregates collapsed to halves: agg[var] -> [2, K, F]; tot -> [2, 2]."""

    def __init__(self, res, meta):
        self.res = res
        if res["by_day"]:
            nd = meta["day_end"] - meta["day0"] + 1
            half = (np.arange(nd) + meta["day0"] >= meta["split_day"]).astype(int)
            self.half_of_day = half
            self.agg = {k: np.stack([v[half == h].sum(0) for h in (0, 1)]) for k, v in res["agg"].items()}
            self.tot = np.stack([res["tot"][half == h].sum(0) for h in (0, 1)])
        else:
            self.agg = {k: v.astype(float) for k, v in res["agg"].items()}
            self.tot = res["tot"]

    def rate(self, h):
        return self.tot[h, 1] / self.tot[h, 0]


def ratio_rate(a, num, den):
    """a: [K, F]; ratio of spikes per tick, categories num over den."""
    t1, s1 = a[num, F.F_TICKS].sum(), a[num, F.F_SPK].sum()
    t2, s2 = a[den, F.F_TICKS].sum(), a[den, F.F_SPK].sum()
    if t1 <= 0 or t2 <= 0 or s2 <= 0:
        return np.nan
    return (s1 / t1) / (s2 / t2)


def ratio_size(a, num, den):
    n1, z1 = a[num, F.F_SPK].sum(), a[num, F.F_SIZE].sum()
    n2, z2 = a[den, F.F_SPK].sum(), a[den, F.F_SIZE].sum()
    if n1 < 5 or n2 < 5:
        return np.nan
    return (z1 / n1) / (z2 / n2)


def pooled_rate(runs, var, num, den, h):
    """O/E pooled across indices: expected = ticks x the index's own rate over the half."""
    o1 = e1 = o2 = e2 = 0.0
    for r in runs:
        a = r.agg[var][h]
        lam = r.rate(h)
        o1 += a[num, F.F_SPK].sum()
        e1 += a[num, F.F_TICKS].sum() * lam
        o2 += a[den, F.F_SPK].sum()
        e2 += a[den, F.F_TICKS].sum() * lam
    if e1 <= 0 or e2 <= 0 or o2 <= 0:
        return np.nan
    return (o1 / e1) / (o2 / e2)


def pooled_size(runs, var, num, den, h):
    a = sum(r.agg[var][h] for r in runs)
    return ratio_size(a, num, den)


def share(a, cats):
    t = a[:, F.F_TICKS].sum()
    return a[cats, F.F_TICKS].sum() / t if t > 0 else 0.0


def boot_pooled(reals, var, num, den, meta, draws=1000, seed=0, size=False):
    """Day-bootstrap 90% interval of the pooled ratio, confirmation days resampled jointly across indices."""
    rng = np.random.default_rng(seed)
    nd = meta["day_end"] - meta["day0"] + 1
    days = np.flatnonzero(np.arange(nd) + meta["day0"] >= meta["split_day"])
    A = [r.res["agg"][var][days].astype(float) for r in reals]
    T = [r.res["tot"][days] for r in reals]
    out = np.empty(draws)
    for d in range(draws):
        idx = rng.integers(0, len(days), len(days))
        if size:
            a = sum(x[idx].sum(0) for x in A)
            out[d] = ratio_size(a, num, den)
            continue
        o1 = e1 = o2 = e2 = 0.0
        for x, t in zip(A, T):
            a = x[idx].sum(0)
            tt = t[idx].sum(0)
            lam = tt[1] / tt[0]
            o1 += a[num, F.F_SPK].sum()
            e1 += a[num, F.F_TICKS].sum() * lam
            o2 += a[den, F.F_SPK].sum()
            e2 += a[den, F.F_TICKS].sum() * lam
        out[d] = (o1 / e1) / (o2 / e2)
    return float(np.nanquantile(out, 0.05)), float(np.nanquantile(out, 0.95))


def zscore(real, null, log=True, sd_floor=0.0):
    """Predictive z of the real value against the null paths: (f(real) - mean) / (sd x sqrt(1 + 1/n)), with
    sd = max(the paths' sd, sd_floor) (sd_floor: the Poisson sd of a log rate ratio, sqrt(1/s1 + 1/s2)).
    Returns (z, null mean on the original scale, sd, two-sided p from Student t with n - 1 df)."""
    null = np.asarray([x for x in null if np.isfinite(x) and (x > 0 or not log)], float)
    if not np.isfinite(real) or len(null) < 10 or (log and real <= 0):
        return np.nan, np.nan, np.nan, np.nan
    f = np.log if log else (lambda v: v)
    mu, sd = f(null).mean(), max(f(null).std(ddof=1), sd_floor)
    n = len(null)
    z = (f(real) - mu) / (sd * np.sqrt(1 + 1 / n)) if sd > 0 else np.nan
    back = np.exp if log else (lambda v: v)
    p = float(2 * student_t.sf(abs(z), n - 1)) if np.isfinite(z) else np.nan
    return z, float(back(mu)), float(sd), p


def poisson_sd(a, num, den):
    s1, s2 = a[num, F.F_SPK].sum(), a[den, F.F_SPK].sum()
    return float(np.sqrt(1 / s1 + 1 / s2)) if s1 > 0 and s2 > 0 else 0.0


def poisson_slope(rows):
    """rows: list of (count level c, spikes y, expected E). MLE of y ~ Poisson(E exp(a + b c)); returns b."""
    c = np.array([r[0] for r in rows], float)
    y = np.array([r[1] for r in rows], float)
    E = np.array([r[2] for r in rows], float)
    k = E > 0
    c, y, E = c[k], y[k], E[k]
    if len(np.unique(c)) < 2 or y.sum() < 10:
        return np.nan
    a, b = np.log(y.sum() / E.sum()), 0.0
    for _ in range(50):
        mu = E * np.exp(a + b * c)
        g = np.array([(y - mu).sum(), ((y - mu) * c).sum()])
        Hm = np.array([[mu.sum(), (mu * c).sum()], [(mu * c).sum(), (mu * c * c).sum()]])
        try:
            step = np.linalg.solve(Hm, g)
        except np.linalg.LinAlgError:
            return np.nan
        a, b = a + step[0], b + step[1]
        if np.abs(step).max() < 1e-10:
            break
    return float(b)


def count_slope(runs, var, h, K=7):
    rows = []
    for r in runs:
        a = r.agg[var][h]
        lam = r.rate(h)
        for c in range(K):
            rows.append((c, a[c, F.F_SPK], a[c, F.F_TICKS] * lam))
    return poisson_slope(rows)


# ------------------------------------------------------------------------------------------- trades

def trade_summary(T, h):
    """T: trade rows; per variant: n, mean R net, mean R gross, P(R >= N)."""
    if T is None or not len(T):
        return {}
    T = T[T[:, 1] == h]
    out = {}
    for name, m in (("T-all", np.ones(len(T), bool)), ("T-with", T[:, 5] == 1), ("T-against", T[:, 5] == -1),
                    ("T-with-ex", T[:, 6] == 2)):
        x = T[m]
        if not len(x):
            continue
        out[name] = dict(n=int(len(x)), net=float(x[:, 2].mean()), gross=float(x[:, 3].mean()),
                         **{f"p{N}": float((x[:, 2] >= N).mean()) for N in NS},
                         pstop=float((x[:, 4] == 0).mean()), held_min=float(np.median(x[:, 7]) / 60))
    return out


def boot_mean(t, v, draws=1000, seed=0):
    rng = np.random.default_rng(seed)
    day = (t // 86400).astype(np.int64)
    u, inv = np.unique(day, return_inverse=True)
    s = np.bincount(inv, weights=v)
    k = np.bincount(inv).astype(float)
    if len(u) < 10:
        return np.nan, np.nan
    m = np.empty(draws)
    for i in range(draws):
        idx = rng.integers(0, len(u), len(u))
        m[i] = s[idx].sum() / k[idx].sum()
    return float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95))


# --------------------------------------------------------------------------------------------- main

def main(mode):
    OUT = B.OUT
    meta = json.loads((OUT / "meta.json").read_text())
    sl_all = [B.slug(s) for s in B.SYMS]
    real = {sl: load(OUT / f"real_{sl}.pkl") for sl in sl_all}
    R = {sl: Run(real[sl], meta) for sl in sl_all}
    nulls = {sl: [] for sl in sl_all}
    ctrl = {sl: [] for sl in sl_all}
    ntr = {sl: [] for sl in sl_all}
    for sl in sl_all:
        for k in range(B.N_NULL):
            p = OUT / "sim" / f"null_{sl}_{k:03d}.pkl"
            if p.exists():
                res = load(p)
                ntr[sl].append({h: trade_summary(res.pop("trades", None), h) for h in (0, 1)})
                nulls[sl].append(Run(res, meta))
        for k in range(B.N_CTRL):
            p = OUT / "sim" / f"ctrl_{sl}_{k:03d}.pkl"
            if p.exists():
                res = load(p)
                res.pop("trades", None)
                ctrl[sl].append(Run(res, meta))
    npath = min(len(v) for v in nulls.values())
    ncp = min(len(v) for v in ctrl.values())
    print(f"null paths {npath}, control paths {ncp}", flush=True)
    rep = dict(meta=meta, npath=npath, ncp=ncp)

    # --- rates, detector, bridge check
    rates = {}
    for sl in sl_all:
        r = real[sl]
        rates[sl] = dict(ticks=r["n_ticks"], spikes=r["n_spikes"], tps_disc=1 / r["rate"][0], tps_conf=1 / r["rate"][1],
                         name=B.NAME_RATE[sl], deriving=B.DERIVING[sl], theta=r["theta"], sub=r["sub"],
                         outage=r["n_outage"], medJ=r["medJ"], check=r["check"],
                         kill_rate=bool(abs((1 / r["rate"][0]) / B.DERIVING[sl] - 1) > 0.15),
                         null_tps=float(np.mean([1 / n.rate(0) for n in nulls[sl]])) if nulls[sl] else np.nan)
    rep["rates"] = rates

    # --- ex-spike degeneracy
    exd = {}
    for sl in sl_all:
        exd[sl] = {}
        for tf in B.TFS:
            a = R[sl].agg[f"{tf}|ex|dir"][CONF]
            spk = a[:, F.F_SPK]
            exd[sl][tf] = dict(tick_share_aligned=share(a, [0]), spike_share_aligned=float(spk[0] / spk.sum()) if spk.sum() else np.nan,
                               mcfl_mixed=share(R[sl].agg[f"{tf}|ex|mcfl"][CONF], [2]))
    rep["ex_degenerate"] = exd

    reals = [R[sl] for sl in sl_all]

    def primary(var, num, den, label):
        rr = {h: pooled_rate(reals, var, num, den, h) for h in (0, 1)}
        nn = {h: [pooled_rate([nulls[sl][k] for sl in sl_all], var, num, den, h) for k in range(npath)] for h in (0, 1)}
        a1 = sum(r.agg[var][1] for r in reals)
        a0 = sum(r.agg[var][0] for r in reals)
        z, mu, sd, p = zscore(rr[1], nn[1], sd_floor=poisson_sd(a1, num, den))
        zd, mud, _, _ = zscore(rr[0], nn[0], sd_floor=poisson_sd(a0, num, den))
        lo, hi = boot_pooled(reals, var, num, den, meta)
        cc = [pooled_rate([ctrl[sl][k] for sl in sl_all], var, num, den, 1) for k in range(ncp)]
        ccw = [pooled_rate([ctrl[sl][k] for sl in sl_all], var, num, den, 0) for k in range(ncp)]
        clo = chi = np.nan
        if ncp:
            clo, chi = boot_pooled([ctrl[sl][0] for sl in sl_all], var, num, den, meta)
        passed = bool(np.isfinite(z) and abs(z) >= 1.645 and not (lo <= mu <= hi) and np.sign(zd) == np.sign(z))
        per = {sl: dict(real=ratio_rate(R[sl].agg[var][1], num, den),
                        null=[ratio_rate(n.agg[var][1], num, den) for n in nulls[sl]]) for sl in sl_all}
        for sl in sl_all:
            per[sl]["z"], per[sl]["null_mean"], _, _ = zscore(per[sl]["real"], per[sl]["null"],
                                                              sd_floor=poisson_sd(R[sl].agg[var][1], num, den))
            per[sl]["null_band"] = [float(np.nanquantile(per[sl]["null"], q)) for q in (0.05, 0.95)] if per[sl]["null"] else [np.nan] * 2
            per[sl]["null"] = None
        return dict(label=label, real_conf=rr[1], real_disc=rr[0], ci90=[lo, hi], null_mean=mu, null_sd_log=sd, z=z, p=p,
                    null_mean_disc=mud, z_disc=zd, null_conf=nn[1], passed=passed, ctrl_conf=cc, ctrl_disc=ccw,
                    ctrl_ci90_path0=[clo, chi], per_index=per,
                    ctrl_ok=bool(ncp and np.mean(cc) >= 1.10 and clo > 1.0))
    rep["P1"] = primary("4h|full|dir", [0], [1], "4h full-series LRC(100) aligned / counter")
    rep["P2"] = primary("nest|4h|15m", [0], [3], "4h and 15m both aligned / both counter")
    # the requested primary, on the ex-spike series
    rep["P1_ex"] = {sl: exd[sl]["4h"] for sl in sl_all}
    print("P1", {k: rep["P1"][k] for k in ("real_conf", "real_disc", "ci90", "null_mean", "z", "z_disc", "passed", "ctrl_conf", "ctrl_ok")}, flush=True)
    print("P2", {k: rep["P2"][k] for k in ("real_conf", "real_disc", "ci90", "null_mean", "z", "z_disc", "passed", "ctrl_conf")}, flush=True)

    # --- secondary cells
    cells = []

    def add(family, idx, tf, ser, what, var, num, den, kind="rate"):
        agg_real = R[idx].agg[var] if idx != "pooled" else None
        if idx == "pooled":
            fn = pooled_rate if kind == "rate" else pooled_size
            real_c = fn(reals, var, num, den, 1)
            real_d = fn(reals, var, num, den, 0)
            nul = [fn([nulls[sl][k] for sl in sl_all], var, num, den, 1) for k in range(npath)]
            a = sum(r.agg[var][1] for r in reals)
        else:
            fn = ratio_rate if kind == "rate" else ratio_size
            real_c = fn(agg_real[1], num, den)
            real_d = fn(agg_real[0], num, den)
            nul = [fn(n.agg[var][1], num, den) for n in nulls[idx]]
            a = agg_real[1]
        sn, sd_ = share(a, num), share(a, den)
        degenerate = bool(sn < 0.01 or sd_ < 0.01)
        fl = poisson_sd(a, num, den) if kind == "rate" else 0.0
        z, mu, _, p = zscore(real_c, nul, sd_floor=fl) if not degenerate else (np.nan, np.nan, np.nan, np.nan)
        cells.append(dict(family=family, index=idx, tf=tf, series=ser, what=what, kind=kind, real=real_c, disc=real_d,
                          null_mean=mu, z=z, p=p, degenerate=degenerate,
                          n_spk_num=float(a[num, F.F_SPK].sum()), n_spk_den=float(a[den, F.F_SPK].sum())))

    for idx in sl_all + ["pooled"]:
        for tf in B.TFS:
            for ser in ("full", "ex"):
                add("S1 direction", idx, tf, ser, "aligned/counter", f"{tf}|{ser}|dir", [0], [1])
                add("S2 structure", idx, tf, ser, "MCFL aligned/counter", f"{tf}|{ser}|mcfl", [0], [1])
                add("S2 structure", idx, tf, ser, "MCFL mixed/trend", f"{tf}|{ser}|mcfl", [2], [0, 1])
                add("S4 size", idx, tf, ser, "size aligned/counter", f"{tf}|{ser}|dir", [0], [1], "size")
            v = f"{tf}|full|dirxbs"
            add("S3 strength", idx, tf, "full", "|b|/ATR strong/weak, aligned", v, [2], [0])
            add("S3 strength", idx, tf, "full", "|b|/ATR strong/weak, counter", v, [5], [3])
            add("S4 size", idx, tf, "full", "size |b|/ATR strong/weak, aligned", v, [2], [0], "size")
            v = f"{tf}|full|dirxR"
            add("S3 strength", idx, tf, "full", "|R| strong/weak, aligned", v, [2], [0])
            add("S3 strength", idx, tf, "full", "|R| strong/weak, counter", v, [5], [3])
            add("S3 strength", idx, tf, "full", "LRC range (weak |R|)/rest", f"{tf}|full|R", [0], [1, 2])
            for nm in ("bs", "R", "grind"):
                add("S3 strength", idx, tf, "ex", f"ex {nm} strong/weak", f"{tf}|ex|{nm}", [2], [0])
        add("S6 multi-TF", idx, "all", "full", "score top/bottom quintile", "mtf|full|score", [4], [0])
        add("S6 multi-TF", idx, "all", "full", "count 6/0 aligned", "mtf|full|count", [6], [0])
        for H in B.HTF:
            for Lt in B.LTF:
                v = f"nest|{H}|{Lt}"
                add("S7 nested", idx, f"{H}/{Lt}", "full", "both aligned/both counter", v, [0], [3])
                add("S7 nested", idx, f"{H}/{Lt}", "full", "pullback/both aligned", v, [1], [0])
                add("S7 nested", idx, f"{H}/{Lt}", "full", "HTF counter LTF aligned/both counter", v, [2], [3])
    # multi-TF count slope
    for idx in sl_all + ["pooled"]:
        rr = [R[s] for s in sl_all] if idx == "pooled" else [R[idx]]
        b_real = count_slope(rr, "mtf|full|count", 1)
        b_null = [count_slope([nulls[s][k] for s in sl_all] if idx == "pooled" else [nulls[idx][k]], "mtf|full|count", 1)
                  for k in range(npath)]
        z, mu, _, p = zscore(b_real, b_null, log=False)
        cells.append(dict(family="S6 multi-TF", index=idx, tf="all", series="full", what="log-hazard slope per aligned TF",
                          kind="slope", real=b_real, disc=count_slope(rr, "mtf|full|count", 0), null_mean=mu, z=z,
                          p=p, degenerate=False, n_spk_num=np.nan, n_spk_den=np.nan))
    # clustering
    for sl in sl_all:
        for key in ("cv", "fano_15m", "fano_1h", "fano_1d", "acf_1m", "acf_15m"):
            rv = real[sl]["clu"][1][key]
            nv = [n.res["clu"][1][key] for n in nulls[sl]]
            z, mu, _, p = zscore(rv, nv, log=False)
            cells.append(dict(family="S8 clustering", index=sl, tf="-", series="full", what=key, kind="value", real=rv,
                              disc=real[sl]["clu"][0][key], null_mean=mu, z=z, p=p, degenerate=False,
                              n_spk_num=np.nan, n_spk_den=np.nan))
        for key in ("cv", "fano_1h"):
            a_, c_ = (f"cv_al", "cv_co") if key == "cv" else ("fano_1h_al", "fano_1h_co")
            rv = real[sl]["clu"][1][a_] - real[sl]["clu"][1][c_]
            nv = [n.res["clu"][1][a_] - n.res["clu"][1][c_] for n in nulls[sl]]
            z, mu, _, p = zscore(rv, nv, log=False)
            cells.append(dict(family="S8 clustering", index=sl, tf="4h", series="full", what=f"{key} aligned - counter",
                              kind="value", real=rv, disc=real[sl]["clu"][0][a_] - real[sl]["clu"][0][c_], null_mean=mu,
                              z=z, p=p, degenerate=False, n_spk_num=np.nan, n_spk_den=np.nan))
    tested = [c for c in cells if not c["degenerate"] and np.isfinite(c["p"])]
    flags = bh([c["p"] for c in tested])
    for c, f in zip(tested, flags):
        c["bh"] = bool(f)
    for c in cells:
        c.setdefault("bh", False)
    rep["cells"] = cells
    rep["n_tested"] = len(tested)
    rep["bh_survivors"] = [c for c in cells if c["bh"]]
    print(f"secondary cells {len(cells)}, tested {len(tested)}, BH survivors {len(rep['bh_survivors'])}", flush=True)
    for c in rep["bh_survivors"]:
        print("  BH:", c["family"], c["index"], c["tf"], c["series"], c["what"], round(c["real"], 4), "null", round(c["null_mean"], 4), "z", round(c["z"], 2), "disc", c["disc"])

    # clustering kill check (discovery)
    kc = {}
    for sl in sl_all:
        k_ = {}
        for key in ("cv", "fano_1h"):
            nv = np.array([n.res["clu"][0][key] for n in nulls[sl]])
            rv = real[sl]["clu"][0][key]
            k_[key] = dict(real=rv, band=[float(np.quantile(nv, 0.05)), float(np.quantile(nv, 0.95))],
                           inside=bool(np.quantile(nv, 0.05) <= rv <= np.quantile(nv, 0.95)))
        kc[sl] = k_
    rep["null_check"] = kc

    # S10 mechanical, pooled, causal vs non-causal
    mech = {}
    for tf in B.TFS:
        mech[tf] = dict(
            causal=pooled_rate(reals, f"{tf}|full|dir", [0], [1], 1),
            noncausal=pooled_rate(reals, f"{tf}|full|nc", [0], [1], 1),
            null_causal=[pooled_rate([nulls[s][k] for s in sl_all], f"{tf}|full|dir", [0], [1], 1) for k in range(npath)],
            null_noncausal=[pooled_rate([nulls[s][k] for s in sl_all], f"{tf}|full|nc", [0], [1], 1) for k in range(npath)])
    rep["mech"] = mech

    # alignment count curve and nested states, pooled O/E per level
    def oe_levels(runs, var, K, h):
        out = []
        for c in range(K):
            o = e = 0.0
            for r in runs:
                a = r.agg[var][h]
                o += a[c, F.F_SPK]
                e += a[c, F.F_TICKS] * r.rate(h)
            out.append(o / e if e > 0 else np.nan)
        return out
    rep["count_curve"] = dict(real=oe_levels(reals, "mtf|full|count", 7, 1),
                              null=[oe_levels([nulls[s][k] for s in sl_all], "mtf|full|count", 7, 1) for k in range(npath)],
                              share=[float(sum(r.agg["mtf|full|count"][1][c, F.F_TICKS] for r in reals) /
                                           sum(r.agg["mtf|full|count"][1][:, F.F_TICKS].sum() for r in reals)) for c in range(7)])
    rep["nested"] = {f"{H}/{Lt}": dict(real=oe_levels(reals, f"nest|{H}|{Lt}", 4, 1),
                                        null=[oe_levels([nulls[s][k] for s in sl_all], f"nest|{H}|{Lt}", 4, 1) for k in range(npath)])
                     for H in B.HTF for Lt in B.LTF}

    # next 1m / 15m probabilities, pooled raw (per index too)
    nxt = {}
    for sl in sl_all:
        nxt[sl] = {}
        for tf in ("15m", "4h"):
            a = R[sl].agg[f"{tf}|full|dir"][1]
            p1 = [a[c, F.F_HIT] / a[c, F.F_MIN] for c in (0, 1)]
            t15 = real[sl]["p15"][tf][1]
            p15 = [t15[c, 1] / t15[c, 0] if t15[c, 0] else np.nan for c in (0, 1)]
            lam = R[sl].rate(1)
            tpm = R[sl].tot[1, 0] / sum(R[sl].agg[f"{tf}|full|dir"][1][:, F.F_MIN])
            nxt[sl][tf] = dict(p1m=p1, p15m=p15, const_p1m=float(1 - (1 - lam) ** tpm), const_p15m=float(1 - (1 - lam) ** (15 * tpm)))
    rep["next"] = nxt

    # trades
    trades = {}
    walks = {sl: load(B.OUT / f"walk_{sl}.pkl") for sl in sl_all if (B.OUT / f"walk_{sl}.pkl").exists()}
    allT = []
    for sl in sl_all:
        T = real[sl].get("trades")
        if T is None:
            continue
        allT.append(T)
        trades[sl] = {h: trade_summary(T, h) for h in (0, 1)}
        trades[sl]["null"] = {h: {v: {k: float(np.mean([x[h][v][k] for x in ntr[sl] if v in x[h]]))
                                      for k in ("net", "gross", "p1", "p2", "p4", "p10", "pstop")}
                                  for v in ("T-all", "T-with", "T-against", "T-with-ex")} for h in (0, 1)}
        if sl in walks:
            trades[sl]["walks"] = {nm: {f"p{N}": float((w[w[:, 1] == 1][:, 2] >= N).mean()) for N in NS} |
                                   {"net": float(w[w[:, 1] == 1][:, 2].mean())} for nm, w in walks[sl].items()}
    TT = np.concatenate(allT)
    pooled_tr = {h: trade_summary(TT, h) for h in (0, 1)}
    for v, m in (("T-all", np.ones(len(TT), bool)), ("T-with", TT[:, 5] == 1), ("T-against", TT[:, 5] == -1),
                 ("T-with-ex", TT[:, 6] == 2)):
        x = TT[m & (TT[:, 1] == 1)]
        pooled_tr[1][v]["ci90"] = boot_mean(x[:, 0], x[:, 2])
    pooled_tr["null"] = {h: {v: {k: float(np.mean([np.mean([ntr[sl][j][h][v][k] for sl in sl_all if v in ntr[sl][j][h]])
                                                   for j in range(npath)])) for k in ("net", "p1", "p2", "p4", "p10")}
                             for v in ("T-all", "T-with", "T-against", "T-with-ex")} for h in (0, 1)}
    rep["trades"] = trades
    rep["trades_pooled"] = pooled_tr

    # sizes in ATR (reported only)
    rep["size_atr"] = {sl: {c: float(R[sl].agg["4h|full|dir"][1][c, F.F_SATR] / max(R[sl].agg["4h|full|dir"][1][c, F.F_SPK], 1))
                            for c in (0, 1)} for sl in sl_all}

    (B.OUT / "report.json").write_text(json.dumps(rep, indent=1, default=lambda o: float(o) if isinstance(o, np.floating) else int(o) if isinstance(o, np.integer) else str(o)))
    print("wrote report.json", flush=True)
    if mode == "plot":
        import boomcrash_plots
        boomcrash_plots.main(rep, real, R, nulls)
