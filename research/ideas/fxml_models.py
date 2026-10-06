"""FX and metals ML + adaptive conformal inference: the models, the online learners and the conformal layers.

Frozen in `fxml_rule.json`. One job is (timeframe, source, target[, part]). It reads OUT/ds_<tf>_<source>.pkl
(fxml_data.py) and writes OUT/pred/<tf>_<source>_<target>[_<part>].pkl with, for every row, each model's
prediction, the conformal intervals or sets, and the job's CV / ablation / importance tables.

  OUT=... WORKERS=8 OMP_NUM_THREADS=1 python research/ideas/fxml_models.py            (every job)
  ONLY=1h_real_rvk ... python research/ideas/fxml_models.py                             (one)
"""
from __future__ import annotations

import heapq
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fxml_data as D  # noqa: E402

OUT = D.OUT
PRED = OUT / "pred"
SEED = 20261006
EPS = 1e-4
REG = ("range1", "rvk", "absret1")
CLS = ("tup05", "tdn05", "tup10", "tdn10", "first", "sign1", "signk", "nr2L", "nr2S")
DIRECTION = ("sign1", "signk", "nr2L", "nr2S")
P1 = ("1h", "rvk")
P2 = ("4h", "sign1")
HGB_DEFAULT = dict(learning_rate=0.05, max_iter=300, max_leaf_nodes=31, min_samples_leaf=200, l2_regularization=1.0)
GRID = dict(learning_rate=(0.02, 0.05, 0.1), max_leaf_nodes=(7, 15, 31, 63), min_samples_leaf=(50, 200, 1000),
            l2_regularization=(0.0, 1.0, 10.0), max_iter=(100, 300, 600), max_features=(0.5, 1.0))
N_CONFIGS = 12
ALPHA_REG = 0.10
ALPHA_SET = 0.10
GAMMA = 0.005
GAMMAS = tuple(np.geomspace(0.0005, 0.1, 12))
BUF = 1000
MIN_BUF = 50
LAMBDA = 0.94
WF_MONTHS = 6
SGD_LR, SGD_L2 = 0.05, 1e-4
ABL_TARGETS = ("rvk", "range1", "tup10", "sign1", "signk", "nr2L")
IMP_TARGETS = ("rvk", "tup10", "sign1", "nr2L")
META = {"sym", "cls", "ts", "bar", "cost_atr", "atr", "close"}
TARGET_COLS = {"range1", "absret1", "rvk", "tup05", "tdn05", "tup10", "tdn10", "first", "sign1", "signk",
               "mfeL", "riskL", "tstopL", "mfeS", "riskS", "tstopS", "nr2L", "nr2S", "res_nrL", "res_nrS"}


CORE_E = ["lrc10_sgn", "lrc20_sgn", "lrc50_sgn", "lrc100_sgn", "lrc10_d1", "lrc20_d1", "lrc50_d1", "lrc100_d1",
          "atr_ratio", "lvol_z", "park20", "pc_f1", "pc_res", "pc_res5", "pc_evr1"]


def groups(cols):
    """The frozen feature groups (Q: the amendment's polynomial fits)."""
    S = [c for c in cols if c.startswith(("lrc", "cs", "ema", "mtf"))]
    P = [c for c in cols if c.startswith(("pc_", "spca"))]
    C = [c for c in cols if c.startswith(("pd", "pw")) or c in ("body", "uwick", "lwick", "cloc")]
    Q = [c for c in cols if c.startswith("pf")]
    O = [c for c in cols if c.startswith("o_")]
    B0 = [c for c in cols if c not in S and c not in P and c not in C and c not in Q and c not in O]
    out = dict(B0=B0, S=S, P=P, C=C)
    if Q:
        out["Q"] = Q
    if O:
        out["O"] = O
    return out


OHLC_ONLY_B0 = ("rng", "atr_ratio", "lvol_z", "park20", "gk20")


def close_only(cols):
    """Amendment O's close-only set: features derived from closes (ATR as the unit)."""
    g = groups(cols)
    b0 = [c for c in g["B0"] if c not in OHLC_ONLY_B0]
    return b0 + g["S"] + g["P"] + g.get("Q", [])


def with_ohlc(rows, fit, part):
    """Join the stored O block and its slope PCA (fitted on the fit rows) for the ablation / importance."""
    from sklearn.decomposition import PCA
    O = pd.read_pickle(OUT / f"ds_{part}_O.pkl").reset_index(drop=True)  # our own pickle
    sl = [c for c in O.columns if "lrc" in c and not c.endswith("_R")]
    X = O[sl].to_numpy(np.float32)
    st = Std(X[fit])
    Z = PCA(6, random_state=SEED).fit(st(X[fit])).transform(st(X)).astype(np.float32)
    for i in range(6):
        O[f"o_spca{i + 1}"] = Z[:, i]
    return list(O.columns), O.astype(np.float32)


ABL_MAX_FIT = 200000


def sub_fit(fit):
    """The ablation / importance HGB fits use at most ABL_MAX_FIT fit rows (a fixed random subset, the
    same for every variant of a job), to keep the OHLC-wide fits tractable."""
    ix = np.flatnonzero(fit)
    if len(ix) <= ABL_MAX_FIT:
        return fit
    rng = np.random.default_rng(SEED)
    keep = np.zeros(len(fit), bool)
    keep[rng.choice(ix, ABL_MAX_FIT, replace=False)] = True
    return keep


def expansion(rows, fit, interaction_only):
    """Amendment E: degree-2 expansion of the standardised core, standardised again on the fit rows."""
    from sklearn.preprocessing import PolynomialFeatures
    X = rows[CORE_E].to_numpy(np.float32)
    Z = Std(X[fit])(X)
    E = PolynomialFeatures(2, interaction_only=interaction_only, include_bias=False).fit_transform(Z)
    return Std(E[fit])(E)


# ------------------------------------------------------------------------------------------ preparation

def prep(tf, source):
    # our own pickles, written by fxml_data.py on the lab (never outside data)
    d = pd.read_pickle(OUT / f"ds_{tf}_{source}.pkl")
    rows = d["rows"].reset_index(drop=True)
    hz = d["horizons"]
    # resolution time of each label: ts of bar (t + h) of the same series
    res = {}
    ts = rows["ts"].to_numpy(np.int64)
    starts = rows.groupby("sym", sort=False).indices
    for tgt in list(hz) + ["nr2L", "nr2S"]:
        out = np.full(len(rows), np.iinfo(np.int64).max, np.int64)
        for sym, ix in starts.items():
            ix = np.sort(ix)
            if tgt in hz:
                h = np.full(len(ix), hz[tgt])
            else:
                h = rows[f"res_nr{tgt[-1]}"].to_numpy()[ix]
            j = np.arange(len(ix)) + h
            ok = j < len(ix)
            out[ix[ok]] = ts[ix[j[ok]]]
        res[tgt] = out
    feats = [c for c in rows.columns if c not in META and c not in TARGET_COLS]
    return rows, res, feats


def splits(rows, res_t, y):
    ts = rows["ts"].to_numpy(np.int64)
    main = (rows["cls"] != "HOLD").to_numpy()
    lab = np.isfinite(y)
    disc = lab & (res_t < D.SPLIT)
    conf = lab & (ts >= D.SPLIT)
    t80 = np.quantile(ts[disc & main], 0.8)
    fit = disc & main & (res_t < t80)
    cal = disc & (ts >= t80)
    return dict(main=main, disc=disc, conf=conf, fit=fit, cal=cal, cal_main=cal & main, t80=t80)


class Std:
    def __init__(self, X):
        self.mu = np.nanmean(X, 0)
        sd = np.nanstd(X, 0)
        self.sd = np.where(sd > 0, sd, 1.0)

    def __call__(self, X):
        Z = (X - self.mu) / self.sd
        return np.clip(np.nan_to_num(Z, nan=0.0, posinf=0.0, neginf=0.0), -10, 10).astype(np.float32)


def add_slope_pca(rows, feats, fit):
    from sklearn.decomposition import PCA
    S = groups(feats)["S"]
    X = rows[S].to_numpy(np.float32)
    st = Std(X[fit])
    p = PCA(6, random_state=SEED).fit(st(X[fit]))
    Z = p.transform(st(X)).astype(np.float32)
    for i in range(6):
        rows[f"spca{i + 1}"] = Z[:, i]
    return feats + [f"spca{i + 1}" for i in range(6)], p.explained_variance_ratio_.tolist()


# ------------------------------------------------------------------------------------------ metrics

def qlike(v, f):
    v = np.maximum(v, EPS)
    f = np.maximum(f, EPS)
    return v / f - np.log(v / f) - 1


def auc(y, p):
    from sklearn.metrics import roc_auc_score
    ok = np.isfinite(y) & np.isfinite(p)
    if ok.sum() < 50 or len(np.unique(y[ok])) < 2:
        return np.nan
    return float(roc_auc_score(y[ok], p[ok]))


# ------------------------------------------------------------------------------------------ models

def hgb(kind, cfg, loss=None):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    cfg = dict(cfg)
    if kind == "cls":
        return HistGradientBoostingClassifier(random_state=SEED, early_stopping=False, **cfg)
    return HistGradientBoostingRegressor(loss=loss or "squared_error", random_state=SEED, early_stopping=False, **cfg)


def model_target(tgt, y):
    """What the regression models fit: the variance proxy v (range1^2, rvk) or |r| (absret1)."""
    if tgt == "range1":
        return y.astype(float) ** 2
    return y.astype(float)


def fit_predict_reg(tgt, X, v, fit, cfg):
    """HGB on v (gamma loss for the variance proxies, squared for absret1). Returns predictions of E[v]."""
    loss = "squared_error" if tgt == "absret1" else "gamma"
    m = hgb("reg", cfg, loss)
    m.fit(X[fit], v[fit] + (EPS if loss == "gamma" else 0.0))
    return np.maximum(m.predict(X), EPS), m


def fit_predict_cls(X, y, fit, cfg):
    m = hgb("cls", cfg)
    m.fit(X[fit], y[fit].astype(int))
    return m.predict_proba(X)[:, 1], m


def log_model(Xs, z, fit, kind):
    """Ridge on log v (smearing-corrected) or logistic, on standardised features."""
    from sklearn.linear_model import LogisticRegression, Ridge
    if kind == "cls":
        m = LogisticRegression(C=0.1, max_iter=300)
        m.fit(Xs[fit], z[fit].astype(int))
        return m.predict_proba(Xs)[:, 1], m
    lz = np.log(np.maximum(z, EPS))
    m = Ridge(alpha=1.0).fit(Xs[fit], lz[fit])
    pr = m.predict(Xs)
    smear = float(np.mean(np.exp(lz[fit] - pr[fit])))
    return np.exp(pr) * smear, m


def mlp_model(Xs, z, fit, kind):
    from sklearn.neural_network import MLPClassifier, MLPRegressor
    kw = dict(hidden_layer_sizes=(64, 32), early_stopping=True, alpha=1e-3, max_iter=60, batch_size=512,
              random_state=SEED, validation_fraction=0.1)
    if kind == "cls":
        m = MLPClassifier(**kw).fit(Xs[fit], z[fit].astype(int))
        return m.predict_proba(Xs)[:, 1], m
    lz = np.log(np.maximum(z, EPS))
    m = MLPRegressor(**kw).fit(Xs[fit], lz[fit])
    pr = m.predict(Xs)
    smear = float(np.mean(np.exp(lz[fit] - pr[fit])))
    return np.exp(pr) * smear, m


def walk_forward(tgt, kind, X, z, ts, res_t, lab, main, cfg):
    """HGB refitted every 6 months of confirmation on every main row resolved before the refit."""
    pred = np.full(len(z), np.nan)
    t0 = pd.Timestamp(D.SPLIT, unit="s", tz="UTC")
    edges = []
    t = t0
    while t.timestamp() <= ts.max():
        edges.append(int(t.timestamp()))
        t = t + pd.DateOffset(months=WF_MONTHS)
    edges.append(int(ts.max()) + 1)
    for a, b in zip(edges[:-1], edges[1:]):
        tr = lab & main & (res_t < a)
        sc = (ts >= a) & (ts < b)
        if not sc.any():
            continue
        if kind == "cls":
            m = hgb("cls", cfg).fit(X[tr], z[tr].astype(int))
            pred[sc] = m.predict_proba(X[sc])[:, 1]
        else:
            loss = "squared_error" if tgt == "absret1" else "gamma"
            m = hgb("reg", cfg, loss).fit(X[tr], z[tr] + (EPS if loss == "gamma" else 0.0))
            pred[sc] = np.maximum(m.predict(X[sc]), EPS)
    return pred


def online_sgd(Xs, z, ts, res_t, lab, kind):
    """A linear learner updated bar time by bar time: predict every row at time tau, then learn every
    row whose label has resolved by tau (AdaGrad, L2). Regression on log v with a running variance
    correction; classification with log loss."""
    n, p = Xs.shape
    w = np.zeros(p + 1)
    G = np.full(p + 1, 1e-8)
    target = np.log(np.maximum(z, EPS)) if kind == "reg" else z.astype(float)
    order = np.argsort(ts, kind="stable")
    tsu, first = np.unique(ts[order], return_index=True)
    bounds = np.r_[first, len(order)]
    lo = np.flatnonzero(lab)
    lo = lo[np.argsort(res_t[lo], kind="stable")]
    rt = res_t[lo]
    ptr = 0
    pred = np.full(n, np.nan)
    s2 = 1.0
    for g in range(len(tsu)):
        tau = tsu[g]
        k = np.searchsorted(rt, tau, side="right")
        if k > ptr:
            ix = lo[ptr:k]
            ptr = k
            A = np.c_[Xs[ix], np.ones(len(ix))]
            out = A @ w
            if kind == "cls":
                pr = 1 / (1 + np.exp(-np.clip(out, -30, 30)))
                err = pr - target[ix]
            else:
                err = out - target[ix]
                s2 = 0.999 * s2 + 0.001 * float(np.mean(err ** 2))
            grad = A.T @ err / len(ix) + SGD_L2 * w
            G += grad ** 2
            w -= SGD_LR * grad / np.sqrt(G)
        rix = order[bounds[g]:bounds[g + 1]]
        out = np.c_[Xs[rix], np.ones(len(rix))] @ w
        pred[rix] = 1 / (1 + np.exp(-np.clip(out, -30, 30))) if kind == "cls" else np.exp(out + 0.5 * s2)
    return pred


# ------------------------------------------------------------------------------------------ risk baselines

def ewma_garch(rows, fit_mask, k):
    """Per series: the EWMA (0.94) one-step variance and the GARCH(1,1) k-step variance sum and one-step
    variance, in raw log-return units at each row (after bar t's close)."""
    from scipy.optimize import minimize
    n = len(rows)
    ew = np.full(n, np.nan)
    g1 = np.full(n, np.nan)
    gk = np.full(n, np.nan)
    params = {}
    for sym, ix in rows.groupby("sym", sort=False).indices.items():
        ix = np.sort(ix)
        c = rows["close"].to_numpy(float)[ix]
        r = np.r_[0.0, np.diff(np.log(c))]
        r = np.where(np.isfinite(r), r, 0.0)
        v0 = float(np.var(r[1:200])) if len(r) > 200 else float(np.var(r))
        e = np.empty(len(r))
        s = v0
        for i in range(len(r)):
            s = LAMBDA * s + (1 - LAMBDA) * r[i] ** 2
            e[i] = s
        ew[ix] = e
        fr = r[fit_mask[ix]]
        sc = float(np.std(fr)) if len(fr) > 300 else float(np.std(r))
        sc = sc if sc > 0 else 1.0
        x = r / sc

        def filt(th, x=x):
            om, al, be = th
            h = np.empty(len(x))
            hv = np.var(x[:200]) if len(x) > 200 else 1.0
            for i in range(len(x)):
                h[i] = hv
                hv = om + al * x[i] ** 2 + be * hv
            return h, hv

        def nll(u, xf=x[fit_mask[ix]] if fit_mask[ix].sum() > 300 else x):
            om, al, be = np.exp(u[0]), 1 / (1 + np.exp(-u[1])), 1 / (1 + np.exp(-u[2]))
            if al + be >= 0.999:
                return 1e10
            h, _ = filt((om, al, be), xf)
            return 0.5 * float(np.sum(np.log(h) + xf ** 2 / h))

        try:
            sol = minimize(nll, x0=np.array([np.log(0.05), -2.4, 2.0]), method="Nelder-Mead",
                           options=dict(maxiter=400, xatol=1e-4, fatol=1e-3))
            om, al, be = np.exp(sol.x[0]), 1 / (1 + np.exp(-sol.x[1])), 1 / (1 + np.exp(-sol.x[2]))
        except Exception:  # noqa: BLE001
            om, al, be = 0.05, 0.08, 0.9
        params[sym] = (float(om), float(al), float(be))
        h, _ = filt((om, al, be))
        # h[i] is the variance for r[i] given info to i-1; the next-bar variance after bar i:
        hn = om + al * x ** 2 + be * h
        pers = al + be
        lr = om / (1 - pers) if pers < 1 else float(np.var(x))
        js = np.arange(k)
        mult = (pers ** js).sum()
        g1[ix] = hn * sc ** 2
        gk[ix] = (k * lr + (hn - lr) * mult) * sc ** 2
    return ew, g1, gk, params


def envelope_stats(rows, z, res_t, ts):
    """Production's envelope applied to the target: per series, the mean and the 0.05 / 0.95 quantiles of
    the last 1000 resolved targets (log space for the quantiles)."""
    n = len(rows)
    mean = np.full(n, np.nan)
    qlo = np.full(n, np.nan)
    qhi = np.full(n, np.nan)
    for sym, ix in rows.groupby("sym", sort=False).indices.items():
        ix = np.sort(ix)
        zz = z[ix]
        lz = np.log(np.maximum(zz, EPS))
        # rows resolved by row j: res_t <= ts_j; labels resolve in order within a series for fixed h
        rt = res_t[ix]
        tj = ts[ix]
        avail = np.searchsorted(np.sort(np.where(np.isfinite(zz), rt, np.iinfo(np.int64).max)), tj, side="right")
        s = pd.Series(np.where(np.isfinite(zz), lz, np.nan))
        sv = pd.Series(np.where(np.isfinite(zz), zz, np.nan))
        rm = sv.rolling(BUF, min_periods=100).mean().to_numpy()
        r05 = s.rolling(BUF, min_periods=100).quantile(0.05).to_numpy()
        r95 = s.rolling(BUF, min_periods=100).quantile(0.95).to_numpy()
        # the window ending at the last resolved row (avail - 1)
        j = avail - 1
        ok = j >= 0
        mean[ix[ok]] = rm[j[ok]]
        qlo[ix[ok]] = r05[j[ok]]
        qhi[ix[ok]] = r95[j[ok]]
    return mean, qlo, qhi


# ------------------------------------------------------------------------------------------ conformal

class BOA:
    """Bernstein Online Aggregation, as research/harness/conformal.py (AgACI's aggregation)."""

    def __init__(self, k):
        self.k = k
        self.cum = np.zeros(k)
        self.cum2 = np.zeros(k)

    def weights(self):
        eta = np.minimum(0.5, np.sqrt(np.log(self.k) / (1.0 + self.cum2)))
        logw = -eta * self.cum - eta ** 2 * self.cum2
        logw -= logw.max()
        w = np.exp(logw)
        return w / w.sum()

    def update(self, experts, agg, y, beta):
        g = (1.0 if y <= agg else 0.0) - beta
        loss = g * (experts - agg)
        self.cum += loss
        self.cum2 += loss * loss


def _quant(buf_sorted, level):
    n = len(buf_sorted)
    if level >= 1:
        return np.inf
    if level <= 0:
        return -np.inf
    k = int(np.ceil((n + 1) * level)) - 1
    return buf_sorted[min(max(k, 0), n - 1)]


def cqr(rows, ly, lo, hi, res_t, ts, cal, conf_or_hold, cal_main):
    """Conformalised quantile intervals in log space for one model: split, ACI and AgACI per series.
    Returns dict name -> (lower, upper) arrays (NaN outside the online span)."""
    n = len(rows)
    score = np.maximum(lo - ly, ly - hi)
    sc = score[cal_main & np.isfinite(score)]
    q_split = _quant(np.sort(sc), 1 - ALPHA_REG) if len(sc) else 0.0
    out = {m: (np.full(n, np.nan), np.full(n, np.nan)) for m in ("raw", "split", "aci", "agaci")}
    out["raw"][0][:], out["raw"][1][:] = lo, hi
    out["split"][0][:], out["split"][1][:] = lo - q_split, hi + q_split
    span = cal | conf_or_hold
    G = np.array(GAMMAS)
    for sym, ix in rows.groupby("sym", sort=False).indices.items():
        ix = np.sort(ix)
        ix = ix[span[ix] & np.isfinite(lo[ix]) & np.isfinite(hi[ix])]
        if not len(ix):
            continue
        buf = []
        a_t = ALPHA_REG
        ex = np.full(len(G), ALPHA_REG)
        boa_lo, boa_hi = BOA(len(G)), BOA(len(G))
        pend = []
        quotes = {}
        for i in ix:
            while pend and pend[0][0] <= ts[i]:
                _, j = heapq.heappop(pend)
                if not np.isfinite(ly[j]):
                    continue
                buf.append(score[j])
                if len(buf) > BUF:
                    buf.pop(0)
                ql, qh, el, eh, aggl, aggh = quotes.pop(j)
                err = float(not (ql <= ly[j] <= qh))
                a_t = a_t + GAMMA * (ALPHA_REG - err)
                errs = ((ly[j] < el) | (ly[j] > eh)).astype(float)
                ex = ex + G * (ALPHA_REG - errs)
                boa_lo.update(el, aggl, ly[j], ALPHA_REG / 2)
                boa_hi.update(eh, aggh, ly[j], 1 - ALPHA_REG / 2)
            if len(buf) >= MIN_BUF:
                bs = np.sort(buf)
                q = _quant(bs, 1 - a_t)
                qe = np.array([_quant(bs, 1 - x) for x in ex])
            else:
                q = q_split
                qe = np.full(len(G), q_split)
            ql, qh = lo[i] - q, hi[i] + q
            el, eh = lo[i] - qe, hi[i] + qe
            fin = np.isfinite(el) & np.isfinite(eh)
            elc = np.where(fin, el, lo[i] - q_split)
            ehc = np.where(fin, eh, hi[i] + q_split)
            aggl = float(boa_lo.weights() @ elc)
            aggh = float(boa_hi.weights() @ ehc)
            out["aci"][0][i], out["aci"][1][i] = ql, qh
            out["agaci"][0][i], out["agaci"][1][i] = aggl, aggh
            quotes[i] = (ql, qh, elc, ehc, aggl, aggh)
            heapq.heappush(pend, (res_t[i], i))
    return out


def class_sets(rows, p, y, res_t, ts, cal, conf_or_hold, cal_main, alpha=ALPHA_SET):
    """Conformal prediction sets for a binary label: score 1 - p(y). Returns per row, for split and
    ACI: inc1, inc0 (whether 1 / 0 is in the set)."""
    n = len(rows)
    s_true = np.where(y == 1, 1 - p, p)
    sc = s_true[cal_main & np.isfinite(y) & np.isfinite(p)]
    q_split = _quant(np.sort(sc), 1 - alpha) if len(sc) else 1.0
    out = {"split": (1 - p <= q_split, p <= q_split)}
    inc1 = np.zeros(n, bool)
    inc0 = np.zeros(n, bool)
    span = cal | conf_or_hold
    for sym, ix in rows.groupby("sym", sort=False).indices.items():
        ix = np.sort(ix)
        ix = ix[span[ix] & np.isfinite(p[ix])]
        buf = []
        a_t = alpha
        pend = []
        sets = {}
        q = q_split
        for i in ix:
            changed = False
            while pend and pend[0][0] <= ts[i]:
                _, j = heapq.heappop(pend)
                if not np.isfinite(y[j]):
                    sets.pop(j, None)
                    continue
                buf.append(s_true[j])
                if len(buf) > BUF:
                    buf.pop(0)
                i1, i0 = sets.pop(j)
                err = float(not (i1 if y[j] == 1 else i0))
                a_t = a_t + GAMMA * (alpha - err)
                changed = True
            if len(buf) >= MIN_BUF and changed:
                q = _quant(np.sort(buf), 1 - a_t)
            elif len(buf) < MIN_BUF:
                q = q_split
            i1, i0 = (1 - p[i] <= q), (p[i] <= q)
            inc1[i], inc0[i] = i1, i0
            sets[i] = (i1, i0)
            heapq.heappush(pend, (res_t[i], i))
    out["aci"] = (inc1, inc0)
    return out


# ------------------------------------------------------------------------------------------ tuning

def configs():
    rng = np.random.default_rng(SEED)
    keys = list(GRID)
    out = []
    while len(out) < N_CONFIGS:
        c = {k: GRID[k][rng.integers(len(GRID[k]))] for k in keys}
        if c not in out:
            out.append(c)
    return out


def purged_folds(ts, res_t, fit, horizon_sec):
    """4 time blocks of the fit rows, 3 expanding folds; training rows resolve before the validation
    block starts (purge) and validation starts one label horizon after it (embargo)."""
    t = ts[fit]
    edges = np.quantile(t, [0, 0.25, 0.5, 0.75, 1.0])
    folds = []
    for f in range(1, 4):
        start, end = edges[f], edges[f + 1]
        tr = fit & (res_t < start)
        va = fit & (ts >= start + horizon_sec) & (ts <= end)
        folds.append((tr, va))
    return folds


def tune(tgt, kind, X, Xs, z, y, ts, res_t, fit, horizon_sec, want_choice):
    folds = purged_folds(ts, res_t, fit, horizon_sec)
    rows = []
    for ci, cfg in enumerate(configs()):
        sc = []
        for tr, va in folds:
            if kind == "cls":
                m = hgb("cls", cfg).fit(X[tr], z[tr].astype(int))
                sc.append(auc(z[va], m.predict_proba(X[va])[:, 1]))
            else:
                m = hgb("reg", cfg, "gamma").fit(X[tr], z[tr] + EPS)
                sc.append(float(np.mean(qlike(z[va], np.maximum(m.predict(X[va]), EPS)))))
        rows.append(dict(config=ci, **cfg, score=float(np.mean(sc)), folds=sc))
    cv = pd.DataFrame(rows)
    best = cv.sort_values("score", ascending=(kind != "cls")).iloc[0]
    cfg = {k: (best[k].item() if hasattr(best[k], "item") else best[k]) for k in GRID}
    cfg["max_iter"] = int(cfg["max_iter"])
    cfg["max_leaf_nodes"] = int(cfg["max_leaf_nodes"])
    cfg["min_samples_leaf"] = int(cfg["min_samples_leaf"])
    choice = None
    if want_choice:
        alt = {}
        for name in ("logistic", "mlp"):
            sc = []
            for tr, va in folds:
                if name == "logistic":
                    p, _ = log_model(Xs, z, tr, "cls")
                else:
                    p, _ = mlp_model(Xs, z, tr, "cls")
                sc.append(auc(z[va], p[va]))
            alt[name] = float(np.mean(sc))
        alt["hgb"] = float(best["score"])
        choice = dict(scores=alt, best=max(alt, key=alt.get))
    return cv, cfg, choice


# ------------------------------------------------------------------------------------------ one job

def job(spec):
    tf, source, tgt, part = spec
    t0 = time.time()
    name = f"{tf}_{source}_{tgt}" + (f"_{part}" if part else "")
    path = PRED / f"{name}.pkl"
    if path.exists():
        return name, "cached"
    rows, res, feats = prep(tf, source)
    y = rows[tgt].to_numpy(float)
    res_t = res[tgt]
    sp = splits(rows, res_t, y)
    allf, spca_evr = add_slope_pca(rows, feats, sp["fit"])
    feats = [f for f in allf if not f.startswith("pf")]  # the first-frozen set; Q only in abl / imp
    X = rows[feats].to_numpy(np.float32)
    st = Std(X[sp["fit"]])
    Xs = st(X)
    ts = rows["ts"].to_numpy(np.int64)
    kind = "reg" if tgt in REG else "cls"
    z = model_target(tgt, y) if kind == "reg" else y
    lab = np.isfinite(z)
    fit, cal = sp["fit"], sp["cal"]
    conf_or_hold = sp["conf"]
    out = dict(tf=tf, source=source, target=tgt, part=part, feats=feats, spca_evr=spca_evr, t80=sp["t80"])
    hsec = (D.K[tf] if tgt == "rvk" else D.SIGNK if tgt == "signk" else D.FIRST_H if tgt == "first"
            else 20 if tgt.startswith("nr") else 1) * D.SEC[tf]

    if part == "abl":
        ocols, O_ = with_ohlc(rows, fit, f"{tf}_{source}")
        rows = pd.concat([rows, O_], axis=1)
        allf = allf + ocols
        g = groups(allf)
        XA = rows[allf].to_numpy(np.float32)
        co = close_only(allf)
        oh = co + list(OHLC_ONLY_B0) + g["C"] + g["O"]
        sets = {"B0": g["B0"], "B0+S": g["B0"] + g["S"], "B0+P": g["B0"] + g["P"], "B0+C": g["B0"] + g["C"],
                "all": feats, "all+Q": feats + g["Q"], "CO": co, "OH": oh}
        res_abl = {}
        fs = sub_fit(fit)
        for nm, cols in sets.items():
            ci = [allf.index(c) for c in cols]
            if kind == "cls":
                p, _ = fit_predict_cls(XA[:, ci], z, fs, HGB_DEFAULT)
            else:
                p, _ = fit_predict_reg(tgt, XA[:, ci], z, fs, HGB_DEFAULT)
            res_abl[f"hgb:{nm}"] = p.astype(np.float32)
        XQ = Std(rows[g["Q"]].to_numpy(np.float32)[fit])(rows[g["Q"]].to_numpy(np.float32))
        E = expansion(rows, fit, False)
        Ei = expansion(rows, fit, True)
        lin = {"base": Xs, "base+Q": np.c_[Xs, XQ], "base+E": np.c_[Xs, E], "base+Eint": np.c_[Xs, Ei],
               "base+Q+E": np.c_[Xs, XQ, E]}
        for nm, cols in (("CO", co), ("OH", oh)):
            A = rows[cols].to_numpy(np.float32)
            lin[nm] = Std(A[fit])(A)
        for nm, M in lin.items():
            p, _ = log_model(M, z, fit, "cls" if kind == "cls" else "reg")
            res_abl[f"lin:{nm}"] = p.astype(np.float32)
        out["abl"] = res_abl
    elif part == "imp":
        ocols, O_ = with_ohlc(rows, fit, f"{tf}_{source}")
        rows = pd.concat([rows, O_], axis=1)
        allf = allf + ocols
        g = groups(allf)
        XA = rows[allf].to_numpy(np.float32)
        fs = sub_fit(fit)
        if kind == "cls":
            p, m = fit_predict_cls(XA, z, fs, HGB_DEFAULT)
        else:
            p, m = fit_predict_reg(tgt, XA, z, fs, HGB_DEFAULT)
        idx = np.flatnonzero(sp["conf"] & sp["main"] & lab)
        rng = np.random.default_rng(SEED)
        if len(idx) > 100000:
            idx = np.sort(rng.choice(idx, 100000, replace=False))

        def score(pp):
            return auc(z[idx], pp) if kind == "cls" else float(np.mean(qlike(z[idx], pp)))

        def drop(base, s_):
            return (base - s_) if kind == "cls" else (s_ - base)

        def pred_h(A):
            return m.predict_proba(A)[:, 1] if kind == "cls" else np.maximum(m.predict(A), EPS)

        Xc = XA[idx]
        base = score(pred_h(Xc))
        imp = []
        for gname, cols in list(g.items()) + [(c, [c]) for c in allf]:
            A = Xc.copy()
            ci = [allf.index(c) for c in cols]
            A[:, ci] = A[rng.permutation(len(A))][:, ci]
            imp.append(dict(model="hgb", feature=gname, group=gname in g, drop=drop(base, score(pred_h(A)))))
        # the linear model on base + Q + E, by group
        XQ = Std(rows[g["Q"]].to_numpy(np.float32)[fit])(rows[g["Q"]].to_numpy(np.float32))
        E = expansion(rows, fit, False)
        XO = Std(rows[g["O"]].to_numpy(np.float32)[fit])(rows[g["O"]].to_numpy(np.float32))
        M = np.c_[Xs, XQ, E, XO]
        lin_cols = feats + g["Q"] + [f"E{i}" for i in range(E.shape[1])] + g["O"]
        if kind == "cls":
            from sklearn.linear_model import LogisticRegression
            lm = LogisticRegression(C=0.1, max_iter=300).fit(M[fit], z[fit].astype(int))
            pred_l = lambda A: lm.predict_proba(A)[:, 1]  # noqa: E731
        else:
            from sklearn.linear_model import Ridge
            lz = np.log(np.maximum(z, EPS))
            lm = Ridge(alpha=1.0).fit(M[fit], lz[fit])
            sm = float(np.mean(np.exp(lz[fit] - lm.predict(M[fit]))))
            pred_l = lambda A: np.exp(lm.predict(A)) * sm  # noqa: E731
        Mc = M[idx]
        base_l = score(pred_l(Mc))
        gl = {k_: v_ for k_, v_ in groups(feats).items()}
        gl["Q"] = g["Q"]
        gl["E"] = [c for c in lin_cols if c.startswith("E")]
        gl["O"] = g["O"]
        for gname, cols in gl.items():
            A = Mc.copy()
            ci = [lin_cols.index(c) for c in cols]
            A[:, ci] = A[rng.permutation(len(A))][:, ci]
            imp.append(dict(model="linear", feature=gname, group=True, drop=drop(base_l, score(pred_l(A)))))
        out["imp"] = pd.DataFrame(imp)
        out["imp_base"] = dict(hgb=base, linear=base_l)
    else:
        P = {}
        tuned = (tf, tgt) in (P1, P2)
        cfg = HGB_DEFAULT
        if tuned:
            cv, cfg, choice = tune(tgt, kind, X, Xs, z, y, ts, res_t, fit, hsec, want_choice=(tf, tgt) == P2)
            out["cv"], out["cfg"], out["choice"] = cv, cfg, choice
        if kind == "reg":
            P["hgb"], _ = fit_predict_reg(tgt, X, z, fit, cfg)
            P["ridge"], _ = log_model(Xs, z, fit, "reg")
            if tuned:
                P["mlp"], _ = mlp_model(Xs, z, fit, "reg")
            P["wf"] = walk_forward(tgt, "reg", X, z, ts, res_t, lab, sp["main"], cfg)
            P["sgd"] = online_sgd(Xs, z, ts, res_t, lab, "reg")
            k = D.K[tf] if tgt == "rvk" else 1
            ew, g1, gk, gpar = ewma_garch(rows, fit | ~sp["main"] & sp["disc"], k)
            unit2 = (rows["atr"].to_numpy(float) / rows["close"].to_numpy(float)) ** 2
            base = {"ewma": k * ew / unit2, "garch": (gk if k > 1 else g1) / unit2}
            har_X = np.c_[np.log(rows["rv_p1"].to_numpy(float) + EPS), np.log(rows["rv_pk"].to_numpy(float) + EPS),
                          np.log(rows["rv_p5k"].to_numpy(float) + EPS), rows["is_metal"].to_numpy(float)]
            har_X = np.nan_to_num(har_X, nan=0.0)
            lz = np.log(np.maximum(z, EPS))
            from sklearn.linear_model import LinearRegression
            ok = fit & np.isfinite(har_X).all(1)
            hr = LinearRegression().fit(har_X[ok], lz[ok])
            hp = hr.predict(har_X)
            base["har"] = np.exp(hp) * float(np.mean(np.exp(lz[ok] - hp[ok])))
            if tgt == "absret1":
                base = {k_: np.sqrt(v_) for k_, v_ in base.items()}
            env_mean, env_lo, env_hi = envelope_stats(rows, z, res_t, ts)
            base["envelope"] = env_mean
            # QLIKE-optimal scale for every baseline on the fit rows (mean of z / f), so the comparison is
            # about the shape of the forecast, not its level
            scales = {}
            for nm, f in base.items():
                okf = fit & np.isfinite(f) & (f > 0)
                s = float(np.mean(z[okf] / f[okf])) if tgt != "absret1" else float(
                    np.sum(z[okf] * f[okf]) / np.sum(f[okf] ** 2))
                scales[nm] = s
                P[nm] = f * s
            out["scales"], out["garch_params"] = scales, gpar
            # CQR, log space: rvk and range1
            if tgt in ("rvk", "range1"):
                qm = {}
                for q in (0.05, 0.95):
                    m = hgb("reg", cfg, "quantile")
                    m.set_params(quantile=q)
                    m.fit(X[fit], lz[fit])
                    qm[q] = m.predict(X)
                ints = {"hgb": (np.minimum(qm[0.05], qm[0.95]), np.maximum(qm[0.05], qm[0.95]))}
                for nm in ("har", "garch", "ewma"):
                    lf = np.log(np.maximum(P[nm], EPS))
                    r_ = lz[fit] - lf[fit]
                    r_ = r_[np.isfinite(r_)]
                    ints[nm] = (lf + np.quantile(r_, 0.05), lf + np.quantile(r_, 0.95))
                ints["envelope"] = (env_lo, env_hi)
                C = {}
                for nm, (lo, hi) in ints.items():
                    C[nm] = {m_: (a_.astype(np.float32), b_.astype(np.float32))
                             for m_, (a_, b_) in cqr(rows, lz, lo, hi, res_t, ts, cal, conf_or_hold,
                                                                   sp["cal_main"]).items()}
                out["cqr"] = C
        else:
            P["hgb"], _ = fit_predict_cls(X, z, fit, cfg)
            P["logistic"], _ = log_model(Xs, z, fit, "cls")
            if tuned:
                P["mlp"], _ = mlp_model(Xs, z, fit, "cls")
            P["wf"] = walk_forward(tgt, "cls", X, z, ts, res_t, lab, sp["main"], cfg)
            P["sgd"] = online_sgd(Xs, z, ts, res_t, lab, "cls")
            P["coin"] = np.full(len(z), float(np.mean(z[fit])))
            if tgt.startswith(("tup", "tdn")):
                from scipy.stats import norm
                from sklearn.linear_model import LogisticRegression
                ew, _, _, _ = ewma_garch(rows, fit | ~sp["main"] & sp["disc"], 1)
                sig = np.sqrt(ew) / (rows["atr"].to_numpy(float) / rows["close"].to_numpy(float))
                x = 0.5 if tgt.endswith("05") else 1.0
                pr = np.clip(2 * (1 - norm.cdf(x / np.maximum(sig, 1e-6))), 1e-4, 1 - 1e-4)
                lg = np.log(pr / (1 - pr)).reshape(-1, 1)
                okf = fit & np.isfinite(lg[:, 0])
                pl = LogisticRegression(C=1e6).fit(lg[okf], z[okf].astype(int))
                P["reflect"] = pl.predict_proba(np.nan_to_num(lg))[:, 1]
            best = "hgb"
            if (tf, tgt) == P2 and out.get("choice"):
                best = out["choice"]["best"]
            out["best"] = best
            out["sets"] = {}
            for nm in {best, "hgb", "logistic"}:
                cs = class_sets(rows, P[nm], z, res_t, ts, cal, conf_or_hold, sp["cal_main"])
                out["sets"][nm] = {m_: (a_, b_) for m_, (a_, b_) in cs.items()}
        out["pred"] = {k_: np.asarray(v_, np.float32) for k_, v_ in P.items()}
    out["masks"] = {k_: v_ for k_, v_ in sp.items() if k_ != "t80"}
    out["y"] = y.astype(np.float32)
    out["res_t"] = res_t
    pd.to_pickle(out, path)
    return name, f"done in {time.time() - t0:.0f}s"


def all_jobs():
    js = []
    for tf in D.TFS:
        for src in D.SOURCES:
            for tgt in REG + CLS:
                js.append((tf, src, tgt, ""))
            for tgt in ABL_TARGETS:
                js.append((tf, src, tgt, "abl"))
            for tgt in IMP_TARGETS:
                if src in ("real", "garch"):
                    js.append((tf, src, tgt, "imp"))
    # the primaries (tuning) and 1h first, so the pool drains evenly
    def key(j):
        return (0 if (j[0], j[2]) in (P1, P2) and not j[3] else 1, {"1h": 0, "4h": 1, "1d": 2}[j[0]])
    return sorted(js, key=key)


def main():
    PRED.mkdir(parents=True, exist_ok=True)
    js = all_jobs()
    if os.environ.get("PARTS"):
        parts = os.environ["PARTS"].split(",")
        js = [j for j in js if (j[3] or "main") in parts]
    if os.environ.get("ONLY"):
        keep = os.environ["ONLY"].split(",")
        js = [j for j in js if any(k == "_".join(x for x in j if x) for k in keep)]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 8))) as pool:
        for name, msg in pool.map(job, js, chunksize=1):
            print(f"  {name}: {msg}", flush=True)
    print("models done", flush=True)


if __name__ == "__main__":
    main()
