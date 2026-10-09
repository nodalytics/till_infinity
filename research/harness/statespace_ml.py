"""Particle and state-space filters as feature extractors for machine learning.

`state-space-filters.md` scored each filter's own forecast. This asks the other question: do the
filters' *states* - the Kalman drift and its uncertainty, the HMM's regime probabilities, the
particle filter's posterior volatility, regime mix and effective sample size, and the same read
from a higher timeframe - give a learned model anything it cannot get from the bars directly?

## Frozen before any number was read

Instruments and data as `statespace_fourier.py`: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF,
NZDUSD, XAUUSD, BTCUSD and Deriv's Volatility 75, 10, 10 (1s), 25, 25 (1s), 15, 15 (1s) and Jump
25, at 15m, 1h, 4h and 1d. Real bars, two flip walks and one GARCH-t walk per cell. FX and gold
rows that touch the 20:00-23:00 UTC rollover, and rows after a gap, are neither trained on nor
scored.

Feature blocks, every value known at the close of bar t:
  bars     the last five returns over EWMA sigma; 5- and 20-bar returns over sigma; 20-bar
           efficiency; log EWMA sigma; the candle's close location, range, body and both wicks
  filters  kalman: drift, drift variance, standardised innovation (full-candle observation)
           hmm: three filtered regime probabilities (states ordered by mean), P(next up)
           particle (3 regimes x stochastic volatility, Student-t, 1,000 particles): P(next up),
           posterior mean log-volatility and its spread, three regime probabilities, effective
           sample size, predictive sd, log predictive density of the last bar (surprise)
  liq      Corwin-Schultz, Abdi-Ranaldo, Roll, Amihud, volume z (`statespace_liquidity.py`)
  htf      the hmm and particle features of the next timeframe up (15m -> 1h, 1h -> 4h,
           4h -> 1d), from higher bars that have closed

Filters are fitted on the first 60% by time and run forward without smoothing. The models -
logistic regression and gradient boosting (sklearn HistGradientBoosting, early stopping on a
random 20% of the training block - inside the 60%, so nothing from the test block reaches it) - are fitted on the same 60% and scored on the last
40%.

Targets: the next bar's direction (primary); the next five bars' direction; the next bar a
top-10% |r| (threshold from training).

**Pass rules.** (1) Direction: gradient boosting on all blocks passes Benjamini-Hochberg (q 0.05,
block-bootstrap p for AUC <= 0.5) over the primary cells, at least 0.005 above its walks.
(2) The filters earn their place if, on a passing cell, bars + filters beats bars alone by at
least 0.003 on the real series and by more than it does on the walks. (3) Risk: the same
comparison on the shock target, against the GARCH walk. Trades: the confident decile of the
all-blocks direction model, held one bar, net of one quoted spread; tail P(>= 4R), P(>= 10R)
before a one-sigma stop against 1/(N+1) and the walks (not for Jump 25, whose stops gap).

Run on the lab (BARS holds `seqlab/`):
  BARS=<bars> OUT=<out>.json python research/harness/statespace_ml.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numba as nb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
import statespace as ss
import statespace_fourier as sf
import statespace_fx as sfx
import statespace_liquidity as sl

warnings.filterwarnings("ignore")
OUT = Path(os.environ.get("OUT", "statespace_ml.json"))
HTF = {"15m": "1h", "1h": "4h", "4h": "1d"}
KINDS = [("real", 0), ("flip", 1), ("flip", 2), ("garch", 3)]


def load(sym, tf):
    z = np.load(ss.BARS / "seqlab" / f"{sym}.{tf}.npz")
    df = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close", "volume")})
    df = df.drop_duplicates("time").sort_values("time")
    if sym in sf.START:
        df = df[df.time >= pd.Timestamp(sf.START[sym]).timestamp()]
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)].reset_index(drop=True)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    df["volume"] = df.volume.where(df.volume >= 10)
    return df


# ---------------------------------------------------------------- filters that report their state

@nb.njit(cache=True, error_model="numpy")
def kalman_states(Y, phi, q, rv0, rv1, b, a, m_out, p_out, z_out):
    D = min(Y.shape[1], 2)
    m, P = 0.0, q / max(1e-6, 1 - phi * phi)
    for t in range(Y.shape[0]):
        m, P = phi * m, phi * phi * P + q
        S = P + rv0
        e = Y[t, 0] - m
        z_out[t] = e / math.sqrt(S)
        K = P / S
        m, P = m + K * e, (1 - K) * P
        if D > 1:
            S2 = b * b * P + rv1
            e2 = Y[t, 1] - a - b * m
            K2 = P * b / S2
            m, P = m + K2 * e2, (1 - K2 * b) * P
        m_out[t], p_out[t] = m, P


@nb.njit(cache=True, error_model="numpy")
def hmm_states(Y, A, mu, sd, probs, pup):
    K = mu.shape[0]
    pi = np.ones(K) / K
    pr = np.empty(K)
    for t in range(Y.shape[0]):
        for k in range(K):
            pr[k] = 0.0
            for j in range(K):
                pr[k] += pi[j] * A[j, k]
        dens = 0.0
        for k in range(K):
            pi[k] = pr[k] * ss.emit(Y[t], mu, sd, k)
            dens += pi[k]
        dens = max(dens, 1e-300)
        for k in range(K):
            pi[k] /= dens
            probs[t, k] = pi[k]
        # the forecast for t+1, made at the close of t
        up = 0.0
        for k in range(K):
            nk = 0.0
            for j in range(K):
                nk += pi[j] * A[j, k]
            up += nk * 0.5 * (1 + math.erf(mu[k, 0] / (sd[k, 0] * math.sqrt(2))))
        pup[t] = up


@nb.njit(cache=True, error_model="numpy")
def pf_states(Y, A, mu, sd, phi, sh, nu, N, seed, out):
    """Columns of out: P(next up), mean h, sd h, p(regime 0..2), ESS / N, predictive sd of the
    next return, log predictive density of this bar."""
    np.random.seed(seed)
    K, D = mu.shape[0], Y.shape[1]
    cum = np.empty((K, K))
    for j in range(K):
        acc = 0.0
        for k in range(K):
            acc += A[j, k]
            cum[j, k] = acc
    s = np.random.randint(0, K, N)
    h = np.random.randn(N) * sh / math.sqrt(max(1e-6, 1 - phi * phi))
    w = np.empty(N)
    lc = math.lgamma((nu + 1) / 2) - math.lgamma(nu / 2) - 0.5 * math.log(nu * math.pi)
    scale_t = math.sqrt((nu - 2) / nu) if nu > 2 else 1.0
    ns = np.empty(N, np.int64)
    nh = np.empty(N)
    for t in range(Y.shape[0]):
        tot, marg = 0.0, 0.0
        for i in range(N):
            u = np.random.rand()
            k = 0
            while k < K - 1 and u > cum[s[i], k]:
                k += 1
            s[i] = k
            h[i] = phi * h[i] + sh * np.random.randn()
            sig = sd[k, 0] * math.exp(0.5 * h[i]) * scale_t
            z = (Y[t, 0] - mu[k, 0]) / sig
            f0 = math.exp(lc - 0.5 * (nu + 1) * math.log(1 + z * z / nu)) / sig
            marg += f0
            for d in range(1, D):
                f0 *= ss.gauss(Y[t, d], mu[k, d], sd[k, d])
            w[i] = f0 + 1e-300
            tot += w[i]
        sw2 = 0.0
        for i in range(N):
            sw2 += (w[i] / tot) ** 2
        out[t, 7] = 1.0 / sw2 / N
        out[t, 9] = math.log(max(marg / N, 1e-300))
        step = tot / N
        u0 = np.random.rand() * step
        j, acc = 0, w[0]
        for i in range(N):
            target = u0 + i * step
            while acc < target and j < N - 1:
                j += 1
                acc += w[j]
            ns[i], nh[i] = s[j], h[j]
        mh, mh2 = 0.0, 0.0
        cnt = np.zeros(K)
        for i in range(N):
            s[i], h[i] = ns[i], nh[i]
            mh += h[i]
            mh2 += h[i] * h[i]
            cnt[s[i]] += 1
        mh /= N
        out[t, 1] = mh
        out[t, 2] = math.sqrt(max(mh2 / N - mh * mh, 0.0))
        for k in range(K):
            out[t, 3 + k] = cnt[k] / N
        # the forecast for t+1 from the posterior at t, by propagating the mixture analytically
        up, m1, m2 = 0.0, 0.0, 0.0
        for k in range(K):
            pk = 0.0
            for jj in range(K):
                pk += out[t, 3 + jj] * A[jj, k]
            sig = sd[k, 0] * math.exp(0.5 * (phi * mh)) * scale_t
            up += pk * 0.5 * (1 + math.erf(mu[k, 0] / (sig * math.sqrt(2))))
            m1 += pk * mu[k, 0]
            m2 += pk * (sig * sig + mu[k, 0] ** 2)
        out[t, 0] = up
        out[t, 8] = math.sqrt(max(m2 - m1 * m1, 1e-12))


def order_states(A, mu, sd):
    o = np.argsort(mu[:, 0])
    return A[np.ix_(o, o)].copy(), mu[o].copy(), sd[o].copy()


def filter_features(df):
    """Fit on the first 60%; return a (n, 17) feature array, NaN where undefined."""
    n = len(df)
    tr_end = int(n * ss.TRAIN)
    r, s, Y = ss.observations(df, "ohlc", tr_end)
    ok = np.isfinite(Y).all(axis=1)
    first = int(np.argmax(ok))
    Yy = np.ascontiguousarray(np.where(np.isfinite(Y), Y, 0.0)[first:])
    m = len(Yy)
    k = ss.fit_kalman(Yy[:tr_end - first])
    km, kp, kz = np.empty(m), np.empty(m), np.empty(m)
    kalman_states(Yy, k["phi"], k["q"], k["rv"][0], k["rv"][1], k["b"], k["a"], km, kp, kz)
    A, mu, sd = order_states(*ss.fit_hmm(Yy[:tr_end - first][-40000:]))
    hp, hu = np.empty((m, 3)), np.empty(m)
    hmm_states(Yy, A, mu, sd, hp, hu)
    pp = ss.fit_particle(Yy[:tr_end - first], (A, mu, sd))
    pf = np.empty((m, 10))
    pf_states(Yy, A, mu, sd, pp["phi"], pp["sh"], pp["nu"], 1000, 11, pf)
    F = np.column_stack([km, np.log(kp), kz, hp, hu, pf])
    out = np.full((n, F.shape[1]), np.nan)
    out[first:] = F
    return out


FILTER_NAMES = (["k_drift", "k_logvar", "k_innov", "hmm_p0", "hmm_p1", "hmm_p2", "hmm_up"]
                + ["pf_up", "pf_h", "pf_hsd", "pf_p0", "pf_p1", "pf_p2", "pf_ess", "pf_predsd", "pf_logdens"])
HTF_COLS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13]  # the hmm and particle features


def bar_features(df):
    r, s, Y = ss.observations(df, "ohlc", int(len(df) * ss.TRAIN))
    y = Y[:, 0]
    c = np.log(df.close.to_numpy())
    o, h, l_ = (np.log(df[k].to_numpy()) for k in ("open", "high", "low"))
    sig = np.sqrt(pd.Series(r ** 2).ewm(alpha=0.06, min_periods=50).mean().to_numpy())  # through t
    cols = [np.r_[np.full(k, np.nan), y[:len(y) - k]] for k in range(5)]
    ret5 = (c - np.r_[np.full(5, np.nan), c[:-5]]) / (sig * np.sqrt(5))
    ret20 = (c - np.r_[np.full(20, np.nan), c[:-20]]) / (sig * np.sqrt(20))
    path = pd.Series(np.abs(r)).rolling(20).sum().to_numpy()
    eff = (c - np.r_[np.full(20, np.nan), c[:-20]]) / path
    body = (c - o) / sig
    up_w = (h - np.maximum(o, c)) / sig
    lo_w = (np.minimum(o, c) - l_) / sig
    return np.column_stack(cols + [ret5, ret20, eff, np.log(sig), Y[:, 1], Y[:, 2], body, up_w, lo_w])


BAR_NAMES = ["y0", "y1", "y2", "y3", "y4", "ret5", "ret20", "eff20", "log_sigma", "c_loc", "c_range",
             "c_body", "c_upwick", "c_lowick"]


def htf_features(df, tf):
    ht = HTF.get(tf)
    if ht is None:
        return None
    hdf = ss.aggregate(df, tf, ht)
    if len(hdf) < 600:
        return None
    F = filter_features(hdf[["time", "open", "high", "low", "close"]].reset_index(drop=True))[:, HTF_COLS]
    close_h = (hdf.time + ss.MIN[ht] * 60).to_numpy()
    close_l = (df.time + ss.MIN[tf] * 60).to_numpy()
    j = np.searchsorted(close_h, close_l, side="right") - 1
    out = np.full((len(df), F.shape[1]), np.nan)
    ok = j >= 0
    out[ok] = F[j[ok]]
    return out


def safe(X):
    """Finite and bounded for the logistic model: a feature at 1e200 is finite, but its variance
    overflows inside the scaler and comes back as NaN (several cells failed that way under load)."""
    return np.clip(np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0), -1e6, 1e6)


def score(X, y, tr, te, kind_model):
    good_tr = tr & np.isfinite(y)
    good_te = te & np.isfinite(y)
    if good_tr.sum() < 300 or good_te.sum() < 200 or len(np.unique(y[good_tr])) < 2:
        return None, None
    if kind_model == "logit":
        Xf = safe(X)
        mdl = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=0.1))
        mdl.fit(Xf[good_tr], y[good_tr])
        p = mdl.predict_proba(Xf)[:, 1]
    else:
        mdl = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                             min_samples_leaf=100, l2_regularization=1.0,
                                             early_stopping=True, validation_fraction=0.2, random_state=0)
        Xg = np.clip(np.where(np.isfinite(X), X, np.nan), -1e6, 1e6)
        mdl.fit(Xg[good_tr], y[good_tr])
        p = mdl.predict_proba(Xg)[:, 1]
    return ss.auc(y[good_te].astype(int), p[good_te]), p


def job(args):
    sym, tf, kind, seed = args
    df = load(sym, tf)
    if len(df) < 600:
        return dict(sym=sym, tf=tf, kind=kind, seed=seed, skipped=f"{len(df)} bars")
    if kind != "real":
        vol = df.volume.to_numpy()
        df = (ss.flip_walk if kind == "flip" else ss.garch_walk)(df, np.random.default_rng(4000 + seed))
        df["volume"] = vol
    n = len(df)
    dur = ss.MIN[tf] * 60
    t = df.time.to_numpy()
    r = np.diff(np.log(df.close.to_numpy()), prepend=np.nan)
    nxt = np.r_[r[1:], np.nan]
    nxt5 = pd.Series(r).rolling(5).sum().shift(-5).to_numpy()
    sig = np.sqrt(pd.Series(r ** 2).ewm(alpha=0.06, min_periods=50).mean().to_numpy())
    contiguous = np.r_[np.diff(t) <= 1.5 * dur, False]
    roll = sfx.overlaps_roll(t, dur) if (sym in sf.ROLLOVER and tf != "1d") else np.zeros(n, bool)
    clean = contiguous & ~roll & ~np.r_[roll[1:], True]
    split = int(n * ss.TRAIN)
    tr = clean & np.isfinite(nxt) & (np.arange(n) < split)
    te = clean & np.isfinite(nxt) & (np.arange(n) >= split)

    B = bar_features(df)
    F = filter_features(df)
    P = sl.proxies(df)
    L = P[[c for c in ("cs", "ar", "roll", "amihud", "volz") if c in sl.usable(P, ["cs", "ar", "roll", "amihud", "volz"])]].to_numpy(float)
    H = htf_features(df, tf)
    blocks = {"bars": B, "bars+filters": np.column_stack([B, F]), "filters": F,
              "bars+filters+liq": np.column_stack([B, F, L])}
    if H is not None:
        blocks["all"] = np.column_stack([B, F, L, H])
    else:
        blocks["all"] = blocks["bars+filters+liq"]

    up = np.where(np.isfinite(nxt), (nxt > 0).astype(float), np.nan)
    up5 = np.where(np.isfinite(nxt5), (nxt5 > 0).astype(float), np.nan)
    absn = np.abs(nxt)
    big = np.where(np.isfinite(absn), (absn >= np.nanquantile(absn[tr], 0.9)).astype(float), np.nan)
    c = sf.cost(sym)
    res = dict(sym=sym, tf=tf, kind=kind, seed=seed, n=n, n_test=int(te.sum()), cost_bps=1e4 * c,
               test_from=str(pd.to_datetime(t[split], unit="s").date()), has_htf=H is not None, targets={})
    p_main = None
    for tname, yv in (("up1", up), ("up5", up5), ("shock", big)):
        row = {}
        for bname, X in blocks.items():
            for mname in ("logit", "gbm"):
                a, p = score(X, yv, tr, te, mname)
                row[f"{bname}|{mname}"] = a
                if tname == "up1" and bname == "all" and mname == "gbm":
                    p_main = p
        res["targets"][tname] = row
    if p_main is not None:
        k = te & np.isfinite(p_main)
        if kind == "real":
            lo, hi, pv = ss.boot_auc(up[k].astype(int), p_main[k], ss.DAYBARS[tf], reps=400)
            res["main_ci"] = dict(lo=lo, hi=hi, p=pv)
        thr = np.nanquantile(np.abs(p_main[tr] - 0.5), 0.9)
        cf = k & (np.abs(p_main - 0.5) >= thr)
        g = np.sign(p_main[cf] - 0.5) * nxt[cf]
        if cf.sum() > 2:
            res["trade"] = dict(n=int(cf.sum()), gross_bps=1e4 * float(np.mean(g)), net_bps=1e4 * float(np.mean(g - c)),
                                t=float(np.mean(g) / (np.std(g) / np.sqrt(len(g)))))
            if sym != "Jump_25_Index" and cf.sum() >= 30:
                res["tail"] = ss.tail(df, np.where(cf)[0], np.sign(p_main[cf] - 0.5), sig[cf], c)
    # which filter features gradient boosting leaned on, real bars only (split-gain proxy:
    # drop-one-block AUC is above; here the logistic weights on standardised filter features)
    if kind == "real":
        Xf = safe(F)
        g_ = tr & np.isfinite(up)
        mdl = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=0.1)).fit(Xf[g_], up[g_])
        res["filter_weights_up1"] = dict(zip(FILTER_NAMES, np.round(mdl[-1].coef_[0], 4).tolist()))
    return res


if __name__ == "__main__":
    jobs = [(s, tf, k, sd) for s in sf.INSTRUMENTS for tf in sf.TFS for k, sd in KINDS]
    only = os.environ.get("ONLY")  # "sym:tf:kind:seed,..." to re-run named cells
    if only:
        keep = {tuple(x.split(":")) for x in only.split(",")}
        jobs = [j for j in jobs if (j[0], j[1], j[2], str(j[3])) in keep]
    out = []
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", "56"))) as ex:
        futs = {ex.submit(job, j): j for j in jobs}
        for f in futs:
            try:
                out.append(f.result())
            except Exception as e:
                print("FAILED", futs[f], repr(e), flush=True)
                continue
            print("done", futs[f], flush=True)
    OUT.write_text(json.dumps(ss.clean(out), indent=1))
    print("wrote", OUT)
