"""How many independent bets, and does the stretched residual revert? PCA statistical arbitrage on crypto.

A quant article on trading randomness argues that a market is a few shared forces plus noise: take the
market, sector and style factors out with PCA and the stretched residual mean-reverts (Avellaneda-Lee).
Frozen in `pca_rule.json` before any real-data run. The discovery choice (k, thresholds, half-life bound)
is picked by a frozen procedure on the 12 coins before 2024 and committed in `pca_selected.json` before
the confirmation runs.

  MODE=fetch      1h and 15m klines and funding for the 131 fresh coins (data.binance.vision)
  MODE=smoke      the pipeline on purely simulated panels (one factor + OU or iid residuals)
  MODE=spectra    study A: rolling PCA, variance shares, effective bets, Marchenko-Pastur, crash spikes
  MODE=discover   study B on the 12 coins, real data, every grid cell; writes pca_selected.json
  MODE=confirm    study B with the selected cell: real, OU control, iid null, shuffle null
  MODE=displace   study C: DISPLACE_C trades split into market beta and residual
  MODE=report     tables and verdicts from the saved runs
  MODE=plot       the figures

  OUT=... DATA=... CACHE=... BINANCE=... MT5BT_DB=... WORKERS=... python research/ideas/pca_residuals.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import zipfile
import zlib
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import turn_confirm as TC  # noqa: E402
import turn_trade as TT  # noqa: E402

RULE = json.loads((HERE / "pca_rule.json").read_text())
OUT = Path(os.environ.get("OUT", ".data/pca"))
DATA = Path(os.environ.get("DATA", ".data/pca_data"))
CACHE = Path(os.environ.get("CACHE", os.path.expanduser("~/till_infinity/data/binance_fresh")))
SELECTED = HERE / "pca_selected.json"
TC.CACHE = CACHE
IVSEC = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
FEE = RULE["costs"]["fee_per_side"]
SPLIT = TT.SPLIT
CORE = tuple(TT.COINS)
FRESH58 = tuple(c for c in TC.SET_A + TC.SET_B if c not in TT.COINS)
SETC = tuple(TC.SET_C)
FRESH = FRESH58 + SETC
ALL = CORE + FRESH
FX = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP",
      "AUDJPY", "USDCNH")
MACRO = ("XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "XCUUSD", "US SP 500", "US Tech 100", "Wall Street 30",
         "Germany 40", "UK 100", "Japan 225", "Australia 200", "US Oil", "UK Brent Oil")
DERIV = ("Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index", "Volatility 75 Index",
         "Volatility 100 Index", "Jump 50 Index", "Boom 1000 Index", "Crash 1000 Index", "Step Index",
         "Step Index 200", "Step Index 500", "Range Break 100 Index", "Drift Switch Index 10",
         "Drift Switch Index 20", "Drift Switch Index 30")
NS = (0.5, 1, 2, 4, 10)


# ------------------------------------------------------------------------------------------ the math

def mp_edges(q):
    """Marchenko-Pastur support of a correlation matrix's eigenvalues for N/T = q (unit variance)."""
    return (1 - np.sqrt(q)) ** 2, (1 + np.sqrt(q)) ** 2


def mp_density(x, q):
    lo, hi = mp_edges(q)
    d = np.zeros_like(x, dtype=float)
    m = (x > lo) & (x < hi)
    d[m] = np.sqrt((hi - x[m]) * (x[m] - lo)) / (2 * np.pi * q * x[m])
    return d


def bets(evals):
    """Effective number of independent bets: exp(entropy) of the eigenvalue shares, and the
    participation ratio (sum lambda)^2 / sum lambda^2. Both are N for an identity matrix, 1 for one factor."""
    lam = np.clip(np.asarray(evals, float), 0, None)
    p = lam / lam.sum()
    p = p[p > 0]
    return float(np.exp(-(p * np.log(p)).sum())), float(lam.sum() ** 2 / (lam ** 2).sum())


def eig_corr(R):
    """Eigen-decomposition of the correlation matrix of the columns of R (T x n), descending,
    with the columns' standard deviations."""
    mu, sd = R.mean(0), R.std(0)
    Z = (R - mu) / sd
    C = Z.T @ Z / len(R)
    ev, V = np.linalg.eigh(C)
    return ev[::-1], V[:, ::-1], sd


def ou_fit(cum):
    """AR(1) of each column of a cumulated residual X (T x n): X[t+1] = a + b X[t] + zeta.
    Returns b, a, var(zeta). The OU parameters follow: kappa = -ln b a bar, m = a / (1 - b),
    sigma_eq = sqrt(var(zeta) / (1 - b^2))."""
    x0, x1 = cum[:-1], cum[1:]
    m0, m1 = x0.mean(0), x1.mean(0)
    v0 = ((x0 - m0) ** 2).mean(0)
    b = ((x0 - m0) * (x1 - m1)).mean(0) / np.where(v0 > 0, v0, np.nan)
    a = m1 - b * m0
    z = x1 - a - b * x0
    return b, a, (z ** 2).mean(0)


def residual_step(R, k, w_ou):
    """One bar of Avellaneda-Lee on a trailing window R (W x n log returns, no gaps).

    PCA of the correlation matrix over the whole window; eigenportfolios Q_j = v_j / sigma; over the
    last `w_ou` bars each coin's returns are regressed on the k eigenportfolio returns (with an
    intercept); the residuals are cumulated and fitted as an OU process; the s-score is
    (X_last - m_centered) / sigma_eq with m centred across the valid coins (A-L)."""
    ev, V, sd = eig_corr(R)
    Q = (V[:, :k] / sd[:, None]).T  # k x n
    Rw = R[-w_ou:]
    F = Rw @ Q.T
    X = np.column_stack([np.ones(len(Rw)), F])
    coef, *_ = np.linalg.lstsq(X, Rw, rcond=None)
    eps = Rw - X @ coef
    cum = np.cumsum(eps, 0)
    b, a, vz = ou_fit(cum)
    valid = np.isfinite(b) & (b > 0) & (b < 1) & (vz > 0)
    bb = np.where(valid, b, 0.5)
    kappa = -np.log(bb)
    m = a / (1 - bb)
    seq = np.sqrt(vz / (1 - bb ** 2))
    mc = m - (m[valid].mean() if valid.any() else 0.0)
    s = np.where(valid, (cum[-1] - mc) / np.where(seq > 0, seq, np.nan), np.nan)
    hl = np.where(valid, np.log(2) / kappa, np.inf)
    return dict(ev=ev, Q=Q, beta=coef[1:], s=s, hl=hl, valid=valid & np.isfinite(s), m=m, seq=seq, b=b)


def hedge(pos, beta, Q):
    """Net coin weights of residual positions: each unit long residual in coin i is +1 coin i and
    -beta_ji units of eigenportfolio j. Rows normalised to unit gross."""
    raw = pos - (pos @ beta.T) @ Q
    g = np.abs(raw).sum(1, keepdims=True)
    return np.where(g > 0, raw / np.where(g > 0, g, 1), 0.0)


def atr14(H, L, C):
    pc = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    tr = np.nanmax(np.stack([H - L, np.abs(H - pc), np.abs(L - pc)]), 0)
    return pd.DataFrame(tr).rolling(RULE["r_trade"]["atr"], min_periods=RULE["r_trade"]["atr"]).mean().to_numpy()


def sharpe(x, per_year=365):
    x = np.asarray(x, float)
    s = x.std()
    return float(x.mean() / s * np.sqrt(per_year)) if s > 0 else np.nan


def block_boot(x, stat, rng, draws=None, block=None):
    """Circular block bootstrap of a daily series (or rows of a 2D array): 90% interval and the
    one-sided p of stat <= 0."""
    draws = draws or RULE["stats"]["boot_draws"]
    block = block or RULE["stats"]["block_days"]
    x = np.asarray(x)
    n = len(x)
    nb = int(np.ceil(n / block))
    out = np.empty(draws)
    for d in range(draws):
        st = rng.integers(0, n, nb)
        idx = (st[:, None] + np.arange(block)[None, :]).ravel()[:n] % n
        out[d] = stat(x[idx])
    out = out[np.isfinite(out)]
    return float(np.quantile(out, 0.05)), float(np.quantile(out, 0.95)), float((out <= 0).mean())


def max_dd(r):
    eq = np.cumsum(r)
    return float((eq - np.maximum.accumulate(np.concatenate([[0], eq]))[1:]).min())


# ------------------------------------------------------------------------------------------ data

def _get(client, url):
    import httpx
    for _ in range(3):
        try:
            r = client.get(url, timeout=60)
            if r.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    return z.read(z.namelist()[0])
            if r.status_code == 404:
                return None
        except (httpx.HTTPError, zipfile.BadZipFile):
            continue
    return None


def fetch_one(job):
    import httpx
    coin, what = job
    sym = f"{coin}USDT"
    if what == "funding":
        path = DATA / "funding" / f"{sym}.funding.csv"
    else:
        path = DATA / "klines" / f"{sym}.{what}.npz"
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    with httpx.Client() as client:
        for m in TC.MONTHS:
            if what == "funding":
                raw = _get(client, f"{TC.ROOT}/fundingRate/{sym}/{sym}-fundingRate-{m}.zip")
                if raw:
                    d = pd.read_csv(io.BytesIO(raw))
                    parts.append(pd.DataFrame({"ms": d.iloc[:, 0].astype(np.int64), "rate": d.iloc[:, -1].astype(float)}))
            else:
                raw = _get(client, f"{TC.ROOT}/klines/{sym}/{what}/{sym}-{what}-{m}.zip")
                if raw:
                    d = pd.read_csv(io.BytesIO(raw), header=None)
                    if str(d.iloc[0, 0]).startswith("open_time"):
                        d = d.iloc[1:]
                    parts.append(d.iloc[:, :6].astype(float).set_axis(["ts", "open", "high", "low", "close", "volume"], axis=1))
    if what == "funding":
        f = pd.concat(parts).drop_duplicates("ms").sort_values("ms") if parts else pd.DataFrame(columns=["ms", "rate"])
        f.to_csv(path, index=False)
        print(f"  {sym} funding: {len(f)}", flush=True)
        return
    if not parts:
        print(f"  {sym} {what}: no candles", flush=True)
        return
    b = pd.concat(parts).drop_duplicates("ts").sort_values("ts")
    b = b[b["volume"] > 0]
    np.savez(path, ts=(b["ts"].to_numpy() // 1000).astype(np.int64),
             **{c: b[c].to_numpy(float) for c in ("open", "high", "low", "close", "volume")})
    print(f"  {sym} {what}: {len(b)} bars", flush=True)


def fetch():
    jobs = [(c, w) for w in ("funding", "1h", "15m") for c in FRESH]
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(fetch_one, jobs))
    (OUT / "fetch.done").parent.mkdir(parents=True, exist_ok=True)
    (OUT / "fetch.done").write_text("ok")


def load_coin(coin, iv):
    if coin in CORE:
        p = TT.BIN / f"{coin}USDT.klines.{iv}.npz"
        tkey = "time"
    elif iv in ("4h", "1d"):
        p, tkey = CACHE / f"{coin}USDT.{iv}.npz", "ts"
    else:
        p, tkey = DATA / "klines" / f"{coin}USDT.{iv}.npz", "ts"
    if not p.exists():
        return None
    z = np.load(p)
    d = pd.DataFrame({"ts": z[tkey].astype(np.int64), **{k: z[k] for k in ("open", "high", "low", "close")}})
    d = d.drop_duplicates("ts").sort_values("ts")
    d = d[(d["close"] > 0) & (d["low"] > 0)]
    return d.reset_index(drop=True)


def load_funding(coin):
    p = TT.BIN / f"{coin}USDT.funding.csv" if coin in CORE else DATA / "funding" / f"{coin}USDT.funding.csv"
    if not p.exists():
        return None
    f = pd.read_csv(p)
    return f.iloc[:, 0].to_numpy(np.int64) // 1000, f.iloc[:, 1].to_numpy(float)


def panel(coins, iv):
    """Aligned T x N arrays on a regular grid of bar opens; NaN where a coin has no bar. `fund[t]` is
    the funding a long pays at the settlements in (open t, close t]."""
    step = IVSEC[iv]
    frames = {c: d for c in coins if (d := load_coin(c, iv)) is not None and len(d) > 300}
    names = [c for c in coins if c in frames]
    t0 = min(int(d["ts"].iloc[0]) for d in frames.values())
    t1 = max(int(d["ts"].iloc[-1]) for d in frames.values())
    ts = np.arange(t0 - t0 % step, t1 + 1, step, dtype=np.int64)
    T, N = len(ts), len(names)
    arr = {k: np.full((T, N), np.nan) for k in ("open", "high", "low", "close")}
    fund = np.zeros((T, N))
    for j, c in enumerate(names):
        d = frames[c]
        idx = ((d["ts"].to_numpy() - ts[0]) // step).astype(np.int64)
        ok = (idx >= 0) & (idx < T) & (d["ts"].to_numpy() % step == ts[0] % step)
        for k in arr:
            arr[k][idx[ok], j] = d[k].to_numpy()[ok]
        f = load_funding(c)
        if f is not None and len(f[0]):
            # settlement s belongs to the bar whose close (open + step) is the first at or after s
            b = np.ceil((f[0] - ts[0] - step) / step).astype(np.int64)
            m = (b >= 0) & (b < T)
            np.add.at(fund[:, j], b[m], f[1][m])
    return dict(ts=ts, coins=names, iv=iv, fund=fund, **arr)


# ------------------------------------------------------------------------------------- synthetic panels

def _ewm_sigma(lr):
    hl = RULE["synthetic"]["vol_halflife"]
    s = pd.DataFrame(lr).ewm(halflife=hl, min_periods=hl, ignore_na=True).std().shift(1).to_numpy()
    return s


def factor_split(lr):
    """Full-sample factor model of a real panel, used only to build the synthetic panels: returns
    standardised by their own trailing EWMA volatility; K eigenvectors of the pairwise correlation;
    each bar's factor scores by a cross-sectional least squares on the coins present; residual."""
    K = RULE["synthetic"]["factors"]
    sig = _ewm_sigma(lr)
    z = lr / sig
    z[~np.isfinite(z)] = np.nan
    C = pd.DataFrame(z).corr(min_periods=RULE["windows"]["pca"]).fillna(0.0).to_numpy()
    np.fill_diagonal(C, 1.0)
    ev, V = np.linalg.eigh(C)
    V = V[:, ::-1][:, :K]
    T, N = z.shape
    f = np.zeros((T, K))
    eps = np.full((T, N), np.nan)
    for t in range(T):
        a = np.isfinite(z[t])
        if a.sum() >= K + 2:
            ft, *_ = np.linalg.lstsq(V[a], z[t, a], rcond=None)
            f[t] = ft
            eps[t, a] = z[t, a] - V[a] @ ft
        elif a.any():
            eps[t, a] = z[t, a]
    return sig, z, V, f, eps


def synth_panel(P, kind, seed):
    """A synthetic panel on the real one's clock and gaps, with the real factor scores and loadings
    (so the real covariance, crashes and volatility clustering) and one of three residuals:
      ou       each coin's residual is an OU process in level, half-life `synthetic.ou_halflife` bars
               (the positive control: the trade is built for this)
      iid      Gaussian iid residual increments (a random walk residual: the null)
      shuffle  the coin's real residuals permuted in time within its own life (kills any reversion,
               keeps the factor cross-section bar by bar and the residuals' fat tails)
    Highs and lows come from a 16-step Brownian bridge inside each bar; the open is the last close."""
    rng = np.random.default_rng(seed)
    C = P["close"]
    lr = np.log(C[1:] / C[:-1])
    lr = np.vstack([np.full((1, C.shape[1]), np.nan), lr])
    sig, z, V, f, eps = factor_split(lr)
    T, N = z.shape
    avail = np.isfinite(z)
    sd = np.array([np.nanstd(eps[:, j]) if avail[:, j].any() else 1.0 for j in range(N)])
    if kind == "ou":
        phi = 2 ** (-1.0 / RULE["synthetic"]["ou_halflife"])
        x = np.zeros((T, N))
        nz = rng.standard_normal((T, N))
        for t in range(1, T):
            x[t] = phi * x[t - 1] + nz[t]
        e = np.diff(x, axis=0, prepend=0.0)
        e = e / np.sqrt(2 / (1 + phi)) * sd  # var(dX) = 2 var(eta) / (1 + phi)
    elif kind == "iid":
        e = rng.standard_normal((T, N)) * sd
    elif kind == "shuffle":
        e = np.full((T, N), np.nan)
        for j in range(N):
            idx = np.flatnonzero(avail[:, j])
            e[idx, j] = eps[rng.permutation(idx), j]
    else:
        raise ValueError(kind)
    zs = f @ V.T + e
    lrs = np.where(avail, sig * zs, np.nan)
    out = dict(P)
    close = np.full((T, N), np.nan)
    high = np.full((T, N), np.nan)
    low = np.full((T, N), np.nan)
    opn = np.full((T, N), np.nan)
    nsub = 16
    frac = np.arange(1, nsub + 1) / nsub
    rows = np.arange(T)
    for j in range(N):
        fc = np.isfinite(C[:, j])
        av = avail[:, j]
        # a bar with a real price but no synthetic return (the coin's first bars, or the bar after a
        # gap) starts the path again from the real price
        reset = fc & ~av
        if not reset.any():
            continue
        x = np.where(av, lrs[:, j], 0.0)
        cx = np.cumsum(x)
        g = np.maximum.accumulate(np.where(reset, rows, -1))
        ok = fc & (g >= 0)
        gi = np.where(g >= 0, g, 0)
        p = np.log(np.where(fc, C[:, j], 1.0))[gi] + cx - cx[gi]
        close[ok, j] = np.exp(p[ok])
        r = np.flatnonzero(ok & av)
        pprev = p[r] - x[r]
        w = np.cumsum(rng.standard_normal((len(r), nsub)) * (sig[r, j] / np.sqrt(nsub))[:, None], 1)
        br = w - frac[None, :] * (w[:, -1:] - x[r][:, None])
        opn[r, j] = np.exp(pprev)
        high[r, j] = np.exp(pprev + np.maximum(0.0, br.max(1)))
        low[r, j] = np.exp(pprev + np.minimum(0.0, br.min(1)))
        rr = np.flatnonzero(ok & ~av)
        opn[rr, j] = high[rr, j] = low[rr, j] = close[rr, j]
    out.update(open=opn, high=high, low=low, close=close)
    return out


def sim_panel(T, N, kind, seed, iv="4h", hl=None, beta_sd=0.5, resid_sd=0.02, mkt_sd=0.02):
    """A purely simulated panel (no real data): one market factor plus an OU or iid residual."""
    rng = np.random.default_rng(seed)
    hl = hl or RULE["synthetic"]["ou_halflife"]
    beta = 1 + beta_sd * rng.standard_normal(N)
    m = mkt_sd * rng.standard_normal(T)
    if kind == "ou":
        phi = 2 ** (-1.0 / hl)
        x = np.zeros((T, N))
        nz = rng.standard_normal((T, N)) * resid_sd * np.sqrt(2 / (1 + phi))
        for t in range(1, T):
            x[t] = phi * x[t - 1] + nz[t]
        e = np.diff(x, axis=0, prepend=0.0)
    else:
        e = rng.standard_normal((T, N)) * resid_sd
    lr = m[:, None] * beta[None, :] + e
    lr[0] = 0
    close = 100 * np.exp(np.cumsum(lr, 0))
    opn = np.vstack([close[:1], close[:-1]])
    # highs and lows from a 16-step Brownian bridge inside each bar (coarse ranges let stops miss)
    sd = np.sqrt(mkt_sd ** 2 + resid_sd ** 2)
    w = np.cumsum(rng.standard_normal((T, N, 16)) * sd / 4, 2)
    br = w - np.arange(1, 17)[None, None, :] / 16 * (w[:, :, -1:] - lr[:, :, None])
    hi = opn * np.exp(np.maximum(0.0, br.max(2)))
    lo = opn * np.exp(np.minimum(0.0, br.min(2)))
    ts = np.arange(T, dtype=np.int64) * IVSEC[iv] + 1_600_000_000 // 86400 * 86400
    return dict(ts=ts, coins=[f"S{j}" for j in range(N)], iv=iv, fund=np.zeros((T, N)), open=opn, high=hi,
                low=lo, close=close)


# ------------------------------------------------------------------------------------------ study B

def grid():
    g = RULE["grid"]
    return [(k, e, x, h) for k in g["k"] for e in g["entry"] for x in g["exit"] for h in g["hl_max"]]


def run_pass(P, k, cells, tradeable=None, keep_s=False):
    """One walk forward through the panel with k factors, every (entry, exit, hl_max) cell at once.

    At each bar t's close, with the trailing windows only: the residual step on the coins with a full
    window; each cell's positions move by the s-score rule; the book's weights (hedged, unit gross) are
    held over bar t+1. Records per cell and bar: gross, funding, turnover; and the single-name trades
    (entry signal bar, exit signal bar, side, coin)."""
    W, Wo = RULE["windows"]["pca"], RULE["windows"]["ou"]
    C = P["close"]
    T, N = C.shape
    lr = np.vstack([np.full((1, N), np.nan), np.log(C[1:] / C[:-1])])
    ret = np.nan_to_num(np.vstack([np.zeros((1, N)), C[1:] / C[:-1] - 1]), nan=0.0, posinf=0.0, neginf=0.0)
    fund = P["fund"]
    fin = np.isfinite(lr).astype(np.int32)
    cs = np.vstack([np.zeros((1, N), np.int32), np.cumsum(fin, 0)])
    cnt = np.zeros((T, N), np.int32)
    cnt[W:] = cs[W + 1:] - cs[1:T - W + 1]  # returns t-W+1..t
    trad = np.ones(N, bool) if tradeable is None else np.asarray(tradeable, bool)
    nc = len(cells)
    E = np.array([c[0] for c in cells])[:, None]
    X = np.array([c[1] for c in cells])[:, None]
    HL = np.array([c[2] for c in cells])[:, None]
    pos = np.zeros((nc, N), np.int8)
    wprev = np.zeros((nc, N))
    gross = np.zeros((nc, T))
    fpay = np.zeros((nc, T))
    turn = np.zeros((nc, T))
    nlong = np.zeros((nc, T), np.int16)
    nshort = np.zeros((nc, T), np.int16)
    pc1 = np.zeros(T)
    ew = np.zeros(T)
    share1 = np.full(T, np.nan)
    ncoin = np.zeros(T, np.int16)
    S = np.full((T, N), np.nan, np.float32) if keep_s else None
    t_open = np.full((nc, N), -1, np.int64)
    trades = []
    minc = max(k + 3, RULE["min_coins"])
    for t in range(W, T - 1):
        u = np.flatnonzero(cnt[t] == W)
        u = u[lr[t - W + 1:t + 1, u].std(0) > 1e-12]
        newpos = np.zeros((nc, N), np.int8)
        w = np.zeros((nc, N))
        if len(u) >= minc:
            st = residual_step(lr[t - W + 1:t + 1, u], k, Wo)
            s, hl, valid = st["s"], st["hl"], st["valid"]
            ok = valid & trad[u]
            p = pos[:, u]
            sv = np.where(valid, s, 0.0)[None, :]
            enter = (p == 0) & ok[None, :] & (hl[None, :] <= HL)
            el = enter & (sv < -E)
            es = enter & (sv > E)
            keepl = (p == 1) & ok[None, :] & (sv <= -X)
            keeps = (p == -1) & ok[None, :] & (sv >= X)
            q = np.zeros_like(p)
            q[el | keepl] = 1
            q[es | keeps] = -1
            newpos[:, u] = q
            if q.any():
                w[:, u] = hedge(q.astype(float), st["beta"], st["Q"])
            q1 = st["Q"][0] / st["Q"][0].sum()
            pc1[t + 1] = q1 @ ret[t + 1, u]
            ew[t + 1] = ret[t + 1, u].mean()
            share1[t] = st["ev"][0] / st["ev"].sum()
            ncoin[t] = len(u)
            if keep_s:
                S[t, u] = s
        # trade bookkeeping
        opened = (pos == 0) & (newpos != 0)
        closed = (pos != 0) & (newpos != pos)
        for c, i in zip(*np.nonzero(closed)):
            trades.append((c, i, int(pos[c, i]), int(t_open[c, i]), t))
            t_open[c, i] = -1
        for c, i in zip(*np.nonzero(opened)):
            t_open[c, i] = t
        pos = newpos
        drift = wprev * (1 + ret[t])
        turn[:, t] = np.abs(w - drift).sum(1)
        gross[:, t + 1] = w @ ret[t + 1]
        fpay[:, t + 1] = w @ fund[t + 1]
        nlong[:, t] = (pos == 1).sum(1)
        nshort[:, t] = (pos == -1).sum(1)
        wprev = w
    for c, i in zip(*np.nonzero(pos)):
        trades.append((c, i, int(pos[c, i]), int(t_open[c, i]), T - 1))
    # a position cannot flip (an entry needs a flat book), so every close is followed by a flat bar.
    # Costs are booked on the bar the trade happens (at t's close); P&L at t+1
    tr = np.array(trades, np.int64).reshape(-1, 5)
    return dict(ts=P["ts"], iv=P["iv"], coins=P["coins"], cells=cells, k=k, gross=gross, fund=fpay, turn=turn,
                nlong=nlong, nshort=nshort, pc1=pc1, ew=ew, share1=share1, ncoin=ncoin, S=S, trades=tr)


def daily(res, c, start=None, end=None):
    """A cell's bar series summed to UTC days (bars wholly inside a day). Net = gross - fee x turnover
    - funding."""
    ts = res["ts"]
    day = ts // 86400
    d = pd.DataFrame({"day": day, "gross": res["gross"][c], "cost": FEE * res["turn"][c], "fund": res["fund"][c],
                      "turn": res["turn"][c], "pc1": res["pc1"], "ew": res["ew"],
                      "npos": res["nlong"][c] + res["nshort"][c]})
    g = d.groupby("day").agg(gross=("gross", "sum"), cost=("cost", "sum"), fund=("fund", "sum"), turn=("turn", "sum"),
                             pc1=("pc1", "sum"), ew=("ew", "sum"), npos=("npos", "mean"))
    first = np.flatnonzero(res["ncoin"] > 0)
    if len(first):
        g = g[g.index >= ts[first[0]] // 86400]
    if start is not None:
        g = g[g.index >= start // 86400]
    if end is not None:
        g = g[g.index < end // 86400]
    g["net"] = g["gross"] - g["cost"] - g["fund"]
    return g


def r_trades(P, tr, cell):
    """The book's entries as single-name trades on the coin itself: entry at the next open, a stop
    at the trigger bar's extreme + 0.1 ATR (risk at least 0.25 ATR), out at the open after the book
    closes it, or at the stop (0.05 ATR slippage). Costs 0.07% a side. P(N R): +N R before -1R
    within 100 bars, whatever the exit."""
    rt = RULE["r_trade"]
    O, H, L, C = P["open"], P["high"], P["low"], P["close"]
    atr = atr14(H, L, C)
    T = len(C)
    rows = []
    for c, i, side, t0, t1 in tr[tr[:, 0] == cell]:
        if t0 + 1 >= T or not np.isfinite(atr[t0, i]) or atr[t0, i] <= 0:
            continue
        a = atr[t0, i]
        o, h, l = O[t0 + 1:, i], H[t0 + 1:, i], L[t0 + 1:, i]
        entry = o[0]
        if not np.isfinite(entry):
            continue
        if side > 0:
            stop = L[t0, i] - rt["stop_atr"] * a
            risk = max(entry - stop, rt["min_risk_atr"] * a)
            stop = entry - risk
            hit_stop = l <= stop
            fav = (h - entry) / risk
        else:
            stop = H[t0, i] + rt["stop_atr"] * a
            risk = max(stop - entry, rt["min_risk_atr"] * a)
            stop = entry + risk
            hit_stop = h >= stop
            fav = (entry - l) / risk
        if not risk > 0:
            continue
        n_hold = max(1, t1 - t0)  # bars t0+1 .. t1 held; out at open t1+1
        hs = hit_stop[:n_hold]
        if hs.any():
            j = int(np.argmax(hs))
            px = (stop if j == 0 else (min(o[j], stop) if side > 0 else max(o[j], stop)))
            px = px - side * rt["slip_atr"] * a
            R = side * (px - entry) / risk
            how = "stop"
        else:
            j = n_hold
            px = o[j] if j < len(o) and np.isfinite(o[j]) else C[min(T - 1, t1), i]
            R = side * (px - entry) / risk
            how = "signal"
        R -= 2 * FEE * entry / risk
        win = slice(0, rt["pnr_bars"])
        hsw, fw = hit_stop[win], np.nan_to_num(fav[win], nan=-np.inf)
        first_stop = int(np.argmax(hsw)) if hsw.any() else 10 ** 9
        reach = {}
        for N_ in NS:
            hit = fw >= N_
            first = int(np.argmax(hit)) if hit.any() else 10 ** 9
            reach[f"P{N_}R"] = first < first_stop  # a bar touching both counts as the stop
        rows.append(dict(coin=P["coins"][i], side=side, t=t0, ts=int(P["ts"][t0]), R=R, how=how, risk_atr=risk / a,
                         bars=j, **reach))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------- jobs

def _save(res, name):
    (OUT / "runs").mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / "runs" / f"{name}.npz", **{k: v for k, v in res.items()
                                                       if k not in ("cells", "coins", "iv", "S") and v is not None},
                        coins=np.array(res["coins"]), cells=np.array(res["cells"], float), iv=res["iv"])
    if res.get("S") is not None:
        np.save(OUT / "runs" / f"{name}.S.npy", res["S"])


def load_run(name):
    z = np.load(OUT / "runs" / f"{name}.npz", allow_pickle=False)
    d = {k: z[k] for k in z.files}
    d["coins"] = list(d["coins"])
    d["cells"] = [tuple(c) for c in d["cells"]]
    d["iv"] = str(d["iv"])
    return d


def job(spec):
    """spec: (universe, iv, source, k, cells, keep_s, rcell)."""
    uni, iv, source, k, cells, keep_s, rcell = spec
    coins = CORE if uni == "u12" else ALL
    P = panel(coins, iv)
    if source != "real":
        P = synth_panel(P, source, zlib.crc32(f"{uni}{iv}{source}".encode()) % 2 ** 31)
    trad = None if uni == "u12" else np.array([c in FRESH for c in P["coins"]])
    res = run_pass(P, k, [c[1:] for c in cells], trad, keep_s)
    name = f"{uni}_{iv}_{source}_k{k}"
    _save(res, name)
    if rcell is not None:
        rt = r_trades(P, res["trades"], rcell)
        rt.to_pickle(OUT / "runs" / f"{name}.rtrades.pkl")
    print(f"  done {name}: {len(P['coins'])} coins, {len(P['ts'])} bars, {len(res['trades'])} trades", flush=True)
    return name


def _pool(specs):
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 12))) as pool:
        return list(pool.map(job, specs))


def discover():
    """Every grid cell on the 12 coins, real data, 1d and 4h; the cell with the best pooled net Sharpe
    before 2024-01-01 is written to pca_selected.json (and committed before `confirm`)."""
    OUT.mkdir(parents=True, exist_ok=True)
    G = grid()
    specs = [("u12", iv, "real", k, [c for c in G if c[0] == k], False, None) for iv in ("1d", "4h") for k in RULE["grid"]["k"]]
    _pool(specs)
    rows = []
    for k in RULE["grid"]["k"]:
        r1, r4 = load_run(f"u12_1d_real_k{k}"), load_run(f"u12_4h_real_k{k}")
        for ci, cell in enumerate(r1["cells"]):
            a = daily(r1, ci, end=SPLIT)
            b = daily(r4, ci, end=SPLIT)
            pooled = pd.concat([a["net"], b["net"]], axis=1).fillna(0).mean(1)
            pg = pd.concat([a["gross"], b["gross"]], axis=1).fillna(0).mean(1)
            rows.append(dict(k=k, entry=cell[0], exit=cell[1], hl_max=cell[2], sharpe_net=sharpe(pooled),
                             sharpe_gross=sharpe(pg), ann_net=pooled.mean() * 365, ann_gross=pg.mean() * 365,
                             sharpe_1d=sharpe(a["net"]), sharpe_4h=sharpe(b["net"]),
                             turn_day=(a["turn"].mean() + b["turn"].mean()) / 2))
    t = pd.DataFrame(rows).sort_values("sharpe_net", ascending=False)
    t.round(4).to_csv(OUT / "discovery.csv", index=False)
    pd.set_option("display.width", 220)
    print(t.round(3).to_string(index=False))
    best = t.iloc[0]
    sel = dict(selected_on="12 coins (turn_trade.COINS), real, before 2024-01-01, 1d and 4h pooled, net Sharpe",
               k=int(best["k"]), entry=float(best["entry"]), exit=float(best["exit"]), hl_max=float(best["hl_max"]),
               discovery_sharpe_net=round(float(best["sharpe_net"]), 3),
               discovery_sharpe_gross=round(float(best["sharpe_gross"]), 3), cells_tried=len(t))
    SELECTED.write_text(json.dumps(sel, indent=2) + "\n")
    (OUT / "pca_selected.json").write_text(json.dumps(sel, indent=2) + "\n")
    print(json.dumps(sel, indent=2))


def confirm():
    OUT.mkdir(parents=True, exist_ok=True)
    sel = json.loads(SELECTED.read_text())
    ks = sel["k"]
    scell = (ks, sel["entry"], sel["exit"], sel["hl_max"])
    G = grid()
    specs = []
    # real, the whole universe (fresh coins traded): every grid cell at 1d and 4h for the BH family
    for iv in ("1d", "4h"):
        for k in RULE["grid"]["k"]:
            cells = [c for c in G if c[0] == k]
            rc = cells.index(scell) if scell in cells else None
            specs.append(("u143", iv, "real", k, cells, k == ks, rc))
    for iv in ("1h", "15m"):
        specs.append(("u143", iv, "real", ks, [scell], False, 0))
    for iv in ("1d", "4h", "1h", "15m"):
        specs.append(("u12", iv, "real", ks, [scell], iv in ("1d", "4h"), 0))
    for src in ("ou", "iid", "shuffle"):
        for uni in ("u143", "u12"):
            for iv in ("1d", "4h", "1h", "15m"):
                specs.append((uni, iv, src, ks, [scell], False, 0))
    # the heavy ones first
    specs.sort(key=lambda s: ({"15m": 0, "1h": 1, "4h": 2, "1d": 3}[s[1]], s[0] != "u143"))
    only = os.environ.get("ONLY")
    if only:
        specs = [s for s in specs if f"{s[0]}_{s[1]}_{s[2]}" in only.split(",")]
    _pool(specs)
    (OUT / "confirm.done").write_text("ok")


def smoke():
    """The pipeline on simulated panels: it must earn on OU residuals and lose about the costs on iid."""
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for kind in ("ou", "iid"):
        P = sim_panel(3000, 30, kind, seed=7 if kind == "ou" else 8, iv="1d")
        res = run_pass(P, 1, [(1.25, 0.5, 20.0), (2.0, 0.75, 10.0)])
        for c in range(2):
            g = daily(res, c)
            rt = r_trades(P, res["trades"], c)
            rows.append(dict(kind=kind, cell=res["cells"][c], sharpe_gross=sharpe(g["gross"]), sharpe_net=sharpe(g["net"]),
                             ann_gross=g["gross"].mean() * 365, ann_net=g["net"].mean() * 365, turn=g["turn"].mean(),
                             trades=len(rt), R=rt["R"].mean() if len(rt) else np.nan,
                             P1R=rt["P1R"].mean() if len(rt) else np.nan))
    t = pd.DataFrame(rows)
    print(t.round(3).to_string(index=False))
    t.to_csv(OUT / "smoke.csv", index=False)


# ------------------------------------------------------------------------------------------ study A

def mt5_panel(symbols, iv):
    """Broker bars on the intersection of the symbols' clocks (rows where every symbol has a bar)."""
    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    px = {}
    for s in symbols:
        df = R.load(s, iv)
        if df is not None:
            px[s] = pd.Series(df["close"].to_numpy(float), index=df["ts"].to_numpy(np.int64))
    d = pd.DataFrame(px).sort_index().dropna()
    return d.index.to_numpy(), list(d.columns), d.to_numpy()


def spectra_one(spec):
    name, kind, iv, W, step = spec
    if kind == "crypto":
        P = panel(ALL, iv)
        ts, names, C = P["ts"], P["coins"], P["close"]
    else:
        ts, names, C = mt5_panel({"fx": FX, "macro": MACRO, "deriv": DERIV}[kind], iv)
    lr = np.vstack([np.full((1, C.shape[1]), np.nan), np.log(C[1:] / C[:-1])])
    fin = np.isfinite(lr)
    rows, pooled = [], []
    last_pooled = -10 ** 9
    for t in range(W, len(ts), step):
        u = np.flatnonzero(fin[t - W + 1:t + 1].all(0))
        if len(u) < 5:
            continue
        R = lr[t - W + 1:t + 1, u]
        R = R[:, R.std(0) > 0]
        ev, _, _ = eig_corr(R)
        n = R.shape[1]
        ent, pr = bets(ev)
        lo, hi = mp_edges(n / W)
        rows.append(dict(ts=int(ts[t]), n=n, **{f"pc{j + 1}": ev[j] / ev.sum() for j in range(min(5, n))},
                         enb=ent, pr=pr, above_mp=int((ev > hi).sum()), lam_plus=hi, lam1=ev[0]))
        if t - last_pooled >= W:
            pooled.append(np.column_stack([ev, np.full(len(ev), n / W)]))
            last_pooled = t
    d = pd.DataFrame(rows)
    (OUT / "spectra").mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT / "spectra" / f"{name}.csv", index=False)
    np.save(OUT / "spectra" / f"{name}.eig.npy", np.vstack(pooled) if pooled else np.zeros((0, 2)))
    print(f"  spectra {name}: {len(d)} windows, median n {d['n'].median() if len(d) else 0}", flush=True)
    return name


def spectra():
    a = RULE["study_a"]
    specs = []
    for kind, ivs in (("crypto", ("1d", "4h")), ("fx", ("1d", "4h")), ("macro", ("1d", "4h")), ("deriv", ("1d", "4h"))):
        for iv in ivs:
            W = a["window_days"] * 86400 // IVSEC[iv]
            step = max(1, 86400 // IVSEC[iv])
            if kind in ("fx", "macro") and iv == "4h":  # ~6 bars a trading day
                W = a["window_days"] * 6 * 5 // 7
            specs.append((f"{kind}_{iv}", kind, iv, W, step))
    specs.append(("crypto_4h_short", "crypto", "4h", a["spike_window_days"] * 6, 6))
    specs.append(("crypto_1d_short", "crypto", "1d", a["spike_window_days"], 1))
    with ProcessPoolExecutor(min(len(specs), int(os.environ.get("WORKERS", 12)))) as pool:
        list(pool.map(spectra_one, specs))
    (OUT / "spectra.done").write_text("ok")


# ------------------------------------------------------------------------------------------ study C

def displace_one(job_):
    """DISPLACE_C at a 12-bar low, E2 structure exit, exactly as turn_confirm (and checked against
    turn_trade.trades_exits trade by trade), with the bar each trade's exit price was taken on."""
    from mcfl import candles
    from mcfl.parse import flip
    coin, iv = job_
    df, fee_px = TC.load("fresh", coin, iv)
    if df is None or len(df) < 300:
        return None
    cost_atr = fee_px / np.maximum(np.asarray(candles.table(df)["atr"], float), 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    rows = []
    for side, frame in ((1, df), (-1, flip(df))):
        ref = pd.DataFrame(TT.trades_exits(frame, side, cost_atr, "fresh:real", coin, iv))
        ref = ref[ref["T1"]] if len(ref) else ref
        o, h, l, c = (frame[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        n = len(frame)
        atr = np.asarray(candles.table(frame)["atr"], float)
        low3 = pd.Series(l).rolling(3).min().to_numpy()
        U = TT.ups(frame, both=True)
        H = max(1, int(10 * 86400 / IVSEC[iv]))
        for _, r in ref.iterrows():
            t = int(r["t"])
            entry, stop0 = o[t + 1], low3[t] - 0.1 * atr[t]
            risk = entry - stop0
            cost = cost_atr[t] * atr[t] / risk
            R, e = None, None
            for j in range(t + 1, min(n, t + 1 + H)):
                if l[j] <= stop0:
                    R = ((min(o[j], stop0) if j > t + 1 else stop0) - TT.SLIP * atr[t] - entry) / risk
                    e = j
                    break
                if U["DELIVERY_SHIFT_DOWN"][j] and j + 1 < n:
                    R, e = (o[j + 1] - entry) / risk, j  # out at j+1's open: the market move to j's close
                    break
            if R is None:
                e = min(n - 1, t + H)
                R = (c[e] - entry) / risk
            R -= cost
            assert abs(R - r["E2"]) < 1e-9, (coin, iv, side, t, R, r["E2"])
            rows.append(dict(coin=coin, iv=iv, side=side, t=t, ts=int(frame["ts"].iat[t]), t_exit=e,
                             ts_exit=int(frame["ts"].iat[e]), R=R, risk_frac=risk / abs(entry),
                             set="fresh58" if coin in FRESH58 else "setC"))
    print(f"  displace {coin} {iv}: {len(rows)}", flush=True)
    return pd.DataFrame(rows)


def displace():
    OUT.mkdir(parents=True, exist_ok=True)
    TC.CACHE = CACHE
    jobs = [(c, iv) for iv in ("4h", "1d") for c in FRESH]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 12))) as pool:
        got = [g for g in pool.map(displace_one, jobs) if g is not None and len(g)]
    d = pd.concat(got, ignore_index=True)
    # the market over each trade: the equal-weight index of all 143 coins, and BTC
    beta_w = RULE["study_c"]["beta_window"]
    out = []
    for iv, g in d.groupby("iv"):
        P = panel(ALL, iv)
        C = P["close"]
        lr = np.vstack([np.full((1, C.shape[1]), np.nan), np.log(C[1:] / C[:-1])])
        mk = {"ew": np.nan_to_num(np.nanmean(lr, 1)), "btc": np.nan_to_num(lr[:, P["coins"].index("BTC")])}
        pos = {int(x): i for i, x in enumerate(P["ts"])}
        cum = {m: np.concatenate([[0], np.cumsum(v)]) for m, v in mk.items()}
        for _, r in g.iterrows():
            j = P["coins"].index(r["coin"])
            ti, te = pos.get(int(r["ts"])), pos.get(int(r["ts_exit"]))
            if ti is None or te is None or ti < beta_w:
                continue
            y = lr[ti - beta_w + 1:ti + 1, j]
            row = r.to_dict()
            for m, v in mk.items():
                x = v[ti - beta_w + 1:ti + 1]
                ok = np.isfinite(y)
                if ok.sum() < beta_w // 2 or x[ok].var() == 0:
                    row[f"beta_{m}"] = np.nan
                    continue
                b = np.cov(x[ok], y[ok])[0, 1] / x[ok].var(ddof=1)
                M = np.exp(cum[m][te + 1] - cum[m][ti + 1]) - 1  # close t .. close of the exit bar
                row[f"beta_{m}"] = b
                row[f"mkt_{m}"] = M
                row[f"Rbeta_{m}"] = r["side"] * b * M / r["risk_frac"]
                row[f"Rres_{m}"] = r["R"] - row[f"Rbeta_{m}"]
            out.append(row)
    d = pd.DataFrame(out)
    d.to_pickle(OUT / "displace.pkl.gz")
    print(f"{len(d)} DISPLACE_C trades with a market split", flush=True)
    (OUT / "displace.done").write_text("ok")


def main():
    {"fetch": fetch, "smoke": smoke, "spectra": spectra, "discover": discover, "confirm": confirm,
     "displace": displace}[os.environ.get("MODE", "smoke")]()


if __name__ == "__main__":
    main()
