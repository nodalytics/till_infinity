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
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp.npz")
    np.savez(tmp, ts=(b["ts"].to_numpy() // 1000).astype(np.int64),
             **{c: b[c].to_numpy(float) for c in ("open", "high", "low", "close", "volume")})
    os.replace(tmp, path)
    print(f"  {sym} {what}: {len(b)} bars", flush=True)


def fetch():
    whats = os.environ.get("FETCH_WHAT", "funding,1h,15m").split(",")
    coins = FRESH[::-1] if os.environ.get("FETCH_REVERSE") else FRESH
    jobs = [(c, w) for w in whats for c in coins]
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(fetch_one, jobs))
    (OUT / "fetch.done").parent.mkdir(parents=True, exist_ok=True)
    (OUT / f"fetch{os.environ.get('FETCH_WHAT', '')}.done").write_text("ok")


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
            pooled = _pooled(a, b, "net")
            pg = _pooled(a, b, "gross")
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
    ups = TT.ups
    for side, frame in ((1, df), (-1, flip(df))):
        U = ups(frame, both=True)
        TT.ups = lambda _df, both=False, _U=U: _U  # one MCFL parse a side, shared with trades_exits
        try:
            ref = pd.DataFrame(TT.trades_exits(frame, side, cost_atr, "fresh:real", coin, iv))
        finally:
            TT.ups = ups
        ref = ref[ref["T1"]] if len(ref) else ref
        o, h, l, c = (frame[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        n = len(frame)
        atr = np.asarray(candles.table(frame)["atr"], float)
        low3 = pd.Series(l).rolling(3).min().to_numpy()
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



# ------------------------------------------------------------------------------------------ report

def _cell(res, sel):
    want = (sel["entry"], sel["exit"], sel["hl_max"])
    for i, c in enumerate(res["cells"]):
        if np.allclose(c, want):
            return i
    raise KeyError(want)


def _pooled(a, b, col="net"):
    return pd.concat([a[col], b[col]], axis=1).sort_index().fillna(0).mean(1)


def book_row(name, g, rng, start=None, end=None):
    x = g
    if start is not None:
        x = x[x.index >= start // 86400]
    if end is not None:
        x = x[x.index < end // 86400]
    if not len(x):
        return dict(cell=name)
    lo, hi, p = block_boot(x["net"].to_numpy(), sharpe, rng)
    return dict(cell=name, days=len(x), sharpe_gross=sharpe(x["gross"]), sharpe_net=sharpe(x["net"]), lo=lo, hi=hi, p=p,
                ann_gross=x["gross"].mean() * 365, ann_fee=x["cost"].mean() * 365, ann_fund=x["fund"].mean() * 365,
                ann_net=x["net"].mean() * 365, turn_day=x["turn"].mean(), npos=x["npos"].mean() if "npos" in x else np.nan,
                maxdd=max_dd(x["net"].to_numpy()))


def _daily_sel(name, sel):
    r = load_run(name)
    return daily(r, _cell(r, sel)), r


def bh(p, q=0.10):
    p = np.asarray(p, float)
    o = np.argsort(p)
    m = len(p)
    thr = q * (np.arange(1, m + 1)) / m
    ok = p[o] <= thr
    k = np.flatnonzero(ok).max() + 1 if ok.any() else 0
    rej = np.zeros(m, bool)
    rej[o[:k]] = True
    return rej


def crash_days(ew_daily, n=10, gap=7):
    s = ew_daily.sort_values()
    out = []
    for d, v in s.items():
        if all(abs(d - e) >= gap for e in out):
            out.append(d)
        if len(out) == n:
            break
    return sorted(out)


def _above_adj(d):
    """Eigenvalues (of the top 5) above the Marchenko-Pastur edge once PC1's variance is taken out of the
    noise bulk (Laloux et al.: the bulk's variance is 1 - lambda1 / N)."""
    edge = (1 - d["pc1"]) * d["lam_plus"]
    return sum((d[c] * d["n"] > edge).astype(int) for c in ("pc1", "pc2", "pc3", "pc4", "pc5") if c in d)


def report():
    rng = np.random.default_rng(61)
    sel = json.loads(SELECTED.read_text())
    ks = sel["k"]
    lines = []
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_rows", 300)

    def emit(title, t):
        lines.append(f"\n## {title}\n")
        lines.append(t if isinstance(t, str) else t.to_string(index=False))
        print(lines[-2], lines[-1], sep="\n", flush=True)

    # --- study A
    rows = []
    for f in sorted((OUT / "spectra").glob("*.csv")):
        d = pd.read_csv(f)
        if not len(d):
            continue
        rows.append(dict(universe=f.stem, windows=len(d), n=d["n"].median(), enb=d["enb"].median(), pr=d["pr"].median(),
                         enb_frac=(d["enb"] / d["n"]).median(), pc1=d["pc1"].median(), pc1_p90=d["pc1"].quantile(0.9),
                         pc2=d["pc2"].median(), pc3=d["pc3"].median(), pc4=d.get("pc4", pd.Series([np.nan])).median(),
                         pc5=d.get("pc5", pd.Series([np.nan])).median(), top5=d[[c for c in ("pc1", "pc2", "pc3", "pc4", "pc5") if c in d]].sum(1).median(),
                         above_mp=d["above_mp"].median(), above_mp_adj=_above_adj(d).median(),
                         lam1_over_edge=(d["lam1"] / d["lam_plus"]).median()))
    A = pd.DataFrame(rows).round(3)
    emit("A. Effective number of bets (medians over rolling windows)", A)
    for f in sorted((OUT / "spectra").glob("crypto_1d.csv")):
        d = pd.read_csv(f)
        d["year"] = pd.to_datetime(d["ts"], unit="s").dt.year
        emit("A. crypto 1d by year", d.groupby("year")[["n", "pc1", "enb", "pr", "above_mp"]].median().round(3).reset_index())

    # crash spikes: PC1 share (30-day windows) the day before each of the 10 worst equal-weight days
    # against 7 days after
    P1 = panel(ALL, "1d")
    C1 = P1["close"]
    ewd = pd.Series(np.nanmean(C1[1:] / C1[:-1] - 1, 1), index=P1["ts"][1:] // 86400).dropna()
    ewd = ewd[ewd.index >= 18262]  # from 2020: enough coins for an index
    cds = crash_days(ewd, RULE.get("crash_n", 10))
    sp = {}
    for nm in ("crypto_4h_short", "crypto_1d_short", "crypto_1d"):
        f = OUT / "spectra" / f"{nm}.csv"
        if f.exists():
            d = pd.read_csv(f)
            sp[nm] = pd.Series(d["pc1"].to_numpy(), index=d["ts"].to_numpy() // 86400)
    rows = []
    for cd in cds:
        r = dict(day=str(pd.Timestamp(cd * 86400, unit="s").date()), ew=ewd.loc[cd])
        for nm, s_ in sp.items():
            before = s_[s_.index < cd]
            after = s_[(s_.index >= cd) & (s_.index <= cd + 7)]
            r[f"{nm}_before"] = before.iloc[-1] if len(before) else np.nan
            r[f"{nm}_after"] = after.max() if len(after) else np.nan
            r[f"{nm}_pctile_after"] = (s_ < r[f"{nm}_after"]).mean() if len(after) else np.nan
        rows.append(r)
    crash = pd.DataFrame(rows)
    emit("A. PC1 share around the 10 worst equal-weight crypto days (after = max over the next 7 days)", crash.round(3))

    # --- study B
    disc = pd.read_csv(OUT / "discovery.csv")
    emit("B. Discovery (12 coins, before 2024, 1d+4h pooled, net): top 10 of 36 cells", disc.head(10).round(3))
    emit("B. selected", json.dumps(sel))

    books = {}
    for uni in ("u143", "u12"):
        for src in ("real", "ou", "iid", "shuffle"):
            for iv in ("1d", "4h", "1h", "15m"):
                nm = f"{uni}_{iv}_{src}_k{ks}"
                if (OUT / "runs" / f"{nm}.npz").exists():
                    books[(uni, src, iv)] = _daily_sel(nm, sel)[0]
    rows = []
    for (uni, src, iv), g in books.items():
        if uni == "u12":
            rows.append(dict(universe=uni, source=src, iv=iv, sample="2024+", **book_row("", g, rng, start=SPLIT)))
            rows.append(dict(universe=uni, source=src, iv=iv, sample="pre-2024", **book_row("", g, rng, end=SPLIT)))
        else:
            rows.append(dict(universe=uni, source=src, iv=iv, sample="all", **book_row("", g, rng)))
    for uni in ("u143", "u12"):
        for src in ("real", "ou", "iid", "shuffle"):
            if (uni, src, "1d") in books and (uni, src, "4h") in books:
                a, b = books[(uni, src, "1d")], books[(uni, src, "4h")]
                pooled = pd.DataFrame({c: _pooled(a, b, c) for c in ("gross", "cost", "fund", "net", "turn", "npos")})
                books[(uni, src, "pool")] = pooled
                if uni == "u12":
                    rows.append(dict(universe=uni, source=src, iv="1d+4h", sample="2024+", **book_row("", pooled, rng, start=SPLIT)))
                    rows.append(dict(universe=uni, source=src, iv="1d+4h", sample="pre-2024", **book_row("", pooled, rng, end=SPLIT)))
                else:
                    rows.append(dict(universe=uni, source=src, iv="1d+4h", sample="all", **book_row("", pooled, rng)))
                    rows.append(dict(universe=uni, source=src, iv="1d+4h", sample="pre-2024", **book_row("", pooled, rng, end=SPLIT)))
                    rows.append(dict(universe=uni, source=src, iv="1d+4h", sample="2024+", **book_row("", pooled, rng, start=SPLIT)))
    B = pd.DataFrame(rows).drop(columns=["cell"]).round(4)
    B.to_csv(OUT / "books.csv", index=False)
    emit("B. Books with the selected cell (Sharpe annualised on days; ann_* are yearly returns on unit gross)", B)

    # primary
    prim = books[("u143", "real", "pool")]
    r1 = load_run(f"u143_1d_real_k{ks}")
    pc1d = daily(r1, _cell(r1, sel))["pc1"]
    j = pd.concat([prim["net"], pc1d], axis=1, keys=["y", "x"]).dropna()
    X = np.column_stack([np.ones(len(j)), j["x"].to_numpy()])
    coef = np.linalg.lstsq(X, j["y"].to_numpy(), rcond=None)[0]

    def alpha(rows_):
        Xb = np.column_stack([np.ones(len(rows_)), rows_[:, 1]])
        return np.linalg.lstsq(Xb, rows_[:, 0], rcond=None)[0][0] * 365

    alo, ahi, ap = block_boot(j[["y", "x"]].to_numpy(), alpha, rng)
    s_lo, s_hi, s_p = block_boot(prim["net"].to_numpy(), sharpe, rng)
    sh = sharpe(prim["net"])
    pre = sharpe(prim["net"][prim.index < SPLIT // 86400])
    post = sharpe(prim["net"][prim.index >= SPLIT // 86400])
    nul = sharpe(books[("u143", "iid", "pool")]["net"])
    ok = sh > 0 and s_lo > 0 and pre > 0 and post > 0 and sh > nul and alo > 0
    prim_txt = (f"PRIMARY (selected cell k={ks} entry {sel['entry']} exit {sel['exit']} hl<={sel['hl_max']}; fresh coins, "
                f"PCA on 143, 1d+4h pooled, net): Sharpe {sh:+.2f} [{s_lo:+.2f}, {s_hi:+.2f}], gross Sharpe "
                f"{sharpe(prim['gross']):+.2f}; ann gross {prim['gross'].mean() * 365:+.2%}, fees {prim['cost'].mean() * 365:.2%}, "
                f"funding {prim['fund'].mean() * 365:+.2%}, net {prim['net'].mean() * 365:+.2%}; before 2024 {pre:+.2f}, after "
                f"{post:+.2f}; iid null {nul:+.2f}; alpha on PC1 {coef[0] * 365:+.2%}/yr [{alo:+.2%}, {ahi:+.2%}], beta "
                f"{coef[1]:+.3f} -> {'PASSES' if ok else 'fails'}")
    emit("B. PRIMARY", prim_txt)

    # BH across the secondary cells
    sec = []
    for k in RULE["grid"]["k"]:
        a_, b_ = load_run(f"u143_1d_real_k{k}"), load_run(f"u143_4h_real_k{k}")
        for ci, cell in enumerate(a_["cells"]):
            if k == ks and np.allclose(cell, (sel["entry"], sel["exit"], sel["hl_max"])):
                continue
            pooled = _pooled(daily(a_, ci), daily(b_, ci))
            sec.append(dict(cell=f"u143 1d+4h k{k} e{cell[0]} x{cell[1]} hl{cell[2]:g}", sharpe=sharpe(pooled),
                            p=block_boot(pooled.to_numpy(), sharpe, rng, draws=500)[2]))
    for uni, iv in (("u143", "1h"), ("u143", "15m"), ("u12", "1d"), ("u12", "4h"), ("u12", "1h"), ("u12", "15m")):
        if (uni, "real", iv) in books:
            g = books[(uni, "real", iv)]
            if uni == "u12":
                g = g[g.index >= SPLIT // 86400]
            sec.append(dict(cell=f"{uni} {iv} selected" + (" 2024+" if uni == "u12" else ""), sharpe=sharpe(g["net"]),
                            p=block_boot(g["net"].to_numpy(), sharpe, rng, draws=500)[2]))
    S_ = pd.DataFrame(sec)
    S_["bh_reject"] = bh(S_["p"].to_numpy(), RULE.get("bh_q", 0.10))
    emit(f"B. Secondary cells: {len(S_)} tried, {int(S_['bh_reject'].sum())} survive BH at q=0.10",
         S_.sort_values("p").round(4))

    # tails of the primary book
    ewp = pd.Series(daily(r1, _cell(r1, sel))["ew"])
    j2 = pd.concat([prim["net"], ewp], axis=1, keys=["book", "ew"]).dropna()
    worst = j2["ew"] <= j2["ew"].quantile(0.01)
    wk = j2.groupby(j2.index // 7).sum()
    dn, up = j2[j2["ew"] < 0], j2[j2["ew"] > 0]
    bdn = np.polyfit(dn["ew"], dn["book"], 1)[0]
    bup = np.polyfit(up["ew"], up["book"], 1)[0]
    tail = [f"max drawdown {max_dd(prim['net'].to_numpy()):+.2%} (unit gross, summed returns); worst day "
            f"{prim['net'].min():+.2%} on {pd.Timestamp(prim['net'].idxmin() * 86400, unit='s').date()}; worst week {wk['book'].min():+.2%}",
            f"on the 1% worst equal-weight days ({int(worst.sum())}): book mean {j2.loc[worst, 'book'].mean():+.3%} a day "
            f"(all days {j2['book'].mean():+.3%}); index mean {j2.loc[worst, 'ew'].mean():+.2%}",
            f"beta to the index on down days {bdn:+.3f}, on up days {bup:+.3f}; skew of daily net {pd.Series(prim['net']).skew():+.2f}"]
    s4 = sp.get("crypto_4h_short")
    if s4 is not None:
        sw = s4.groupby(s4.index // 7).last().diff()
        top = sw[sw >= sw.quantile(0.95)].index
        bw = prim["net"].groupby(prim.index // 7).sum()
        tail.append(f"weeks with the top 5% rise in the 30-day PC1 share ({len(top)}): book {bw.reindex(top).mean():+.3%} a week "
                    f"against {bw.mean():+.3%} on all weeks")
    for cd in cds:
        day_ = pd.Timestamp(cd * 86400, unit='s').date()
        if cd < prim.index.min():
            tail.append(f"  crash {day_}: index {ewd.loc[cd]:+.1%}; before the book's first day")
            continue
        w_ = prim["net"][(prim.index >= cd) & (prim.index < cd + 7)]
        tail.append(f"  crash {day_}: index {ewd.loc[cd]:+.1%}; book that day "
                    f"{prim['net'].get(cd, np.nan):+.2%}, next 7 days {w_.sum():+.2%}")
    emit("B. Tails of the primary book", "\n".join(tail))

    # R trades
    rows = []
    for uni in ("u143", "u12"):
        for src in ("real", "ou", "iid", "shuffle"):
            for iv in ("1d", "4h", "1h", "15m"):
                f = OUT / "runs" / f"{uni}_{iv}_{src}_k{ks}.rtrades.pkl"
                if not f.exists():
                    continue
                x = pd.read_pickle(f)
                if uni == "u12":
                    x = x[x["ts"] >= SPLIT]
                if not len(x):
                    continue
                lo, hi = TT.boot(x, rng) if len(x) > 30 else (np.nan, np.nan)
                rows.append(dict(universe=uni, source=src, iv=iv, n=len(x), R=x["R"].mean(), lo=lo, hi=hi,
                                 win=(x["R"] > 0).mean(), stop=(x["how"] == "stop").mean(), long_R=x.loc[x["side"] > 0, "R"].mean(),
                                 short_R=x.loc[x["side"] < 0, "R"].mean(), **{f"P{N}R": x[f"P{N}R"].mean() for N in NS}))
    RT = pd.DataFrame(rows).round(3)
    RT.to_csv(OUT / "rtrades.csv", index=False)
    emit("B. Single-name R trades (u12: 2024+). 1/(N+1): " + ", ".join(f"{N}R {1 / (N + 1):.3f}" for N in NS), RT)

    # --- study C
    f = OUT / "displace.pkl.gz"
    if f.exists():
        d = pd.read_pickle(f)
        rows = []
        for (st, iv, side), g in d.groupby(["set", "iv", "side"]):
            rows.append(_c_row(st, iv, side, g, rng))
        for (iv, side), g in d.groupby(["iv", "side"]):
            rows.append(_c_row("all131", iv, side, g, rng))
        for side, g in d.groupby("side"):
            rows.append(_c_row("all131", "4h+1d", side, g, rng))
        for st, g in d.groupby("set"):
            rows.append(_c_row(st, "4h+1d", 0, g, rng))
        rows.append(_c_row("all131", "4h+1d", 0, d, rng))
        Ct = pd.DataFrame(rows).round(4)
        Ct.to_csv(OUT / "displace.csv", index=False)
        emit("C. DISPLACE_C (E2) split into market beta and residual, in R (side 0 = both)", Ct)
        emit("C. Market timing and the signal traded on the market itself", _c_timing(d, rng))
    (OUT / "report.txt").write_text("\n".join(lines))


def _c_timing(d, rng):
    """Does the trade's side time the common market move over its holding period, and does the same
    signal traded on the market (the equal-weight basket, or BTC) keep the edge? Returns per trade in
    basis points of notional: the alt as traded (R x risk), the market with the same side and holding
    period. Costs: the alt's as in turn_confirm (0.07% once); the market 0.07% a side."""
    out = []
    for iv in ("4h", "1d", "4h+1d"):
        g = d if iv == "4h+1d" else d[d["iv"] == iv]
        for side in (1, -1, 0):
            x = g if side == 0 else g[g["side"] == side]
            x = x.dropna(subset=["mkt_ew", "mkt_btc"])
            if len(x) < 30:
                continue
            r = dict(iv=iv, side=side, n=len(x))
            if side == 0:  # regress the side on the index's return over the trade
                for m in ("ew", "btc"):
                    M = x[f"mkt_{m}"].to_numpy()
                    b = np.polyfit(M / M.std(), x["side"].to_numpy(), 1)[0]
                    r[f"slope_side_on_{m}_per_sd"] = b
                    r[f"hit_{m}"] = float((np.sign(M) == x["side"]).mean())
            alt = x["R"] * x["risk_frac"] * 1e4
            r["alt_bps"] = alt.mean()
            lo, hi = TT.boot(x.assign(R=alt), rng)
            r.update(alt_lo=lo, alt_hi=hi)
            for m in ("ew", "btc"):
                gm = x["side"] * x[f"mkt_{m}"] * 1e4
                net = gm - 2 * FEE * 1e4
                r[f"{m}_gross_bps"] = gm.mean()
                r[f"{m}_net_bps"] = net.mean()
                lo, hi = TT.boot(x.assign(R=net), rng)
                r[f"{m}_net_lo"], r[f"{m}_net_hi"] = lo, hi
            r["alt_cost_bps"] = (FEE * 1e4)  # turn_confirm: 0.07% of price once a trade
            out.append(r)
    return pd.DataFrame(out).round(3)


def _c_row(st, iv, side, g, rng):
    g = g if side == 0 else g[g["side"] == side]
    r = dict(set=st, iv=iv, side=side, n=len(g), R=g["R"].mean())
    lo, hi = TT.boot(g.assign(R=g["R"]), rng) if len(g) > 30 else (np.nan, np.nan)
    r.update(lo=lo, hi=hi)
    for m in ("ew", "btc"):
        if f"Rres_{m}" in g:
            x = g.dropna(subset=[f"Rres_{m}"])
            r[f"beta_{m}"] = x[f"beta_{m}"].mean()
            r[f"Rbeta_{m}"] = x[f"Rbeta_{m}"].mean()
            r[f"Rres_{m}"] = x[f"Rres_{m}"].mean()
            if len(x) > 30:
                rl, rh = TT.boot(x.assign(R=x[f"Rres_{m}"]), rng)
                r[f"res_lo_{m}"], r[f"res_hi_{m}"] = rl, rh
    r["R_before"] = g.loc[g["ts"] < SPLIT, "R"].mean()
    r["R_after"] = g.loc[g["ts"] >= SPLIT, "R"].mean()
    if "Rres_ew" in g:
        r["res_before"] = g.loc[g["ts"] < SPLIT, "Rres_ew"].mean()
        r["res_after"] = g.loc[g["ts"] >= SPLIT, "Rres_ew"].mean()
    return r



def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sel = json.loads(SELECTED.read_text())
    ks = sel["k"]
    PL = OUT / "plots"
    PL.mkdir(parents=True, exist_ok=True)
    day = lambda x: pd.to_datetime(np.atleast_1d(np.asarray(x)) * 86400, unit="s")  # noqa: E731
    P1 = panel(ALL, "1d")
    C1 = P1["close"]
    ewd = pd.Series(np.nanmean(C1[1:] / C1[:-1] - 1, 1), index=P1["ts"][1:] // 86400).dropna()
    cds = crash_days(ewd[ewd.index >= 18262], 10)

    # 1. spectra against Marchenko-Pastur
    names = ["crypto_1d", "crypto_4h", "fx_1d", "fx_4h", "macro_1d", "macro_4h", "deriv_1d", "deriv_4h"]
    fig, axes = plt.subplots(2, 4, figsize=(22, 9))
    for ax, nm in zip(axes.flat, names):
        f = OUT / "spectra" / f"{nm}.eig.npy"
        if not f.exists():
            ax.set_visible(False)
            continue
        e = np.load(f)
        if not len(e):
            continue
        q = float(np.median(e[:, 1]))
        lo, hi = mp_edges(q)
        top = e[:, 0][e[:, 0] > 3 * hi]
        xs = e[:, 0][e[:, 0] <= 3 * hi]
        ax.hist(xs, bins=60, density=True, color="#8ab", alpha=0.8, label="eigenvalues (every window)")
        x = np.linspace(max(lo, 1e-4), hi, 400)
        scale = len(e) / max(len(xs), 1)
        ax.plot(x, mp_density(x, q) * scale, "r-", lw=1.5, label=f"Marchenko-Pastur q={q:.2f}")
        ax.axvline(hi, color="r", ls=":", lw=1)
        d = pd.read_csv(OUT / "spectra" / f"{nm}.csv")
        v = float((1 - d["pc1"]).median())  # the bulk's variance once the market is out (Laloux et al.)
        xa = np.linspace(max(lo, 1e-4) * v, hi * v, 400)
        ax.plot(xa, mp_density(xa / v, q) / v * scale, "m--", lw=1.2, label=f"MP with the market out (var {v:.2f})")
        ax.set_title(f"{nm}: median N {d['n'].median():.0f}; λ1 median {d['lam1'].median():.1f} (edge {hi:.2f}); "
                     f"{len(top)} values > 3x edge", fontsize=9)
        ax.legend(fontsize=7)
    fig.suptitle("Correlation eigenvalues in non-overlapping 90-day windows against the random-matrix bulk "
                 "(values beyond 3x the edge are counted, not drawn)")
    fig.tight_layout()
    fig.savefig(PL / "spectra_mp.png", dpi=80)
    plt.close(fig)

    # 2. PC1 share over time with crashes; 3. effective bets
    fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)
    for nm, col in (("crypto_1d", "C0"), ("crypto_4h_short", "C1"), ("fx_1d", "C2"), ("macro_1d", "C3"), ("deriv_1d", "C4")):
        f = OUT / "spectra" / f"{nm}.csv"
        if not f.exists():
            continue
        d = pd.read_csv(f)
        t = day(d["ts"] // 86400)
        axes[0].plot(t, d["pc1"], color=col, lw=0.8, label=nm)
        axes[1].plot(t, d["enb"], color=col, lw=0.8, label=f"{nm} exp(entropy)")
        axes[1].plot(t, d["pr"], color=col, lw=0.8, ls="--")
        axes[2].plot(t, d["enb"] / d["n"], color=col, lw=0.8, label=nm)
    for cd in cds:
        for ax in axes:
            ax.axvline(day(cd)[0], color="k", lw=0.6, ls=":")
    axes[0].set_ylabel("PC1 share of variance")
    axes[0].set_title("PC1 share (crypto: 90-day and 30-day windows; dotted: the 10 worst equal-weight crypto days)")
    axes[1].set_ylabel("effective bets")
    axes[1].set_yscale("log")
    axes[1].set_title("Effective number of independent bets: exp(entropy) solid, participation ratio dashed")
    axes[2].set_ylabel("exp(entropy) / N")
    for ax in axes:
        ax.legend(fontsize=7, ncol=3)
    fig.tight_layout()
    fig.savefig(PL / "pc1_share_and_bets.png", dpi=80)
    plt.close(fig)

    # 4. s-score examples
    nm = f"u143_1d_real_k{ks}"
    r = load_run(nm)
    S = np.load(OUT / "runs" / f"{nm}.S.npy")
    ci = _cell(r, sel)
    tr = r["trades"][r["trades"][:, 0] == ci]
    counts = pd.Series(tr[:, 1]).value_counts()
    fig, axes = plt.subplots(2, 1, figsize=(16, 9))
    for ax, i in zip(axes, counts.index[:2]):
        t = day(r["ts"] // 86400)
        ax.plot(t, S[:, i], lw=0.7, color="#456")
        for v, c in ((sel["entry"], "r"), (-sel["entry"], "g"), (sel["exit"], "r"), (-sel["exit"], "g")):
            ax.axhline(v, color=c, lw=0.8, ls="-" if abs(v) == sel["entry"] else ":")
        for _, _, side, t0, t1 in tr[tr[:, 1] == i]:
            ax.plot(t[t0], S[t0, i], "^" if side > 0 else "v", color="g" if side > 0 else "r", ms=6)
            ax.plot(t[t1], S[t1, i] if np.isfinite(S[t1, i]) else 0, "x", color="k", ms=5)
        ax.set_title(f"{r['coins'][i]}USDT 1d s-score (k={ks}); triangles: entries (long up, short down), x: exits")
        ax.set_ylim(-5, 5)
    fig.tight_layout()
    fig.savefig(PL / "sscore_examples.png", dpi=80)
    plt.close(fig)

    # 5. equity curves; 6. drawdowns
    books = {}
    for uni in ("u143", "u12"):
        for src in ("real", "ou", "iid", "shuffle"):
            try:
                a, b = (_daily_sel(f"{uni}_{iv}_{src}_k{ks}", sel)[0] for iv in ("1d", "4h"))
            except (OSError, FileNotFoundError):
                continue
            books[(uni, src)] = pd.DataFrame({c: _pooled(a, b, c) for c in ("gross", "net")})
    panels = (("discovery: 12 coins, before 2024", "u12", None, SPLIT), ("confirmation: 12 coins, 2024+", "u12", SPLIT, None),
              ("confirmation: 131 fresh coins (PCA on 143)", "u143", None, None))
    fig, axes = plt.subplots(2, 3, figsize=(22, 10))
    for col, (title, uni, st, en) in enumerate(panels):
        for row, kind in enumerate(("gross", "net")):
            ax = axes[row, col]
            ax2 = ax.twinx()
            for src, c in (("real", "k"), ("iid", "C0"), ("shuffle", "C2"), ("ou", "C3")):
                g = books.get((uni, src))
                if g is None:
                    continue
                x = g[kind]
                if st is not None:
                    x = x[x.index >= st // 86400]
                if en is not None:
                    x = x[x.index < en // 86400]
                (ax2 if src == "ou" else ax).plot(day(x.index), x.cumsum(), color=c, lw=1.2 if src == "real" else 0.9,
                                                  ls="--" if src == "ou" else "-", label=f"{src} (Sharpe {sharpe(x):+.2f})")
            ax.set_title(f"{title}, {kind}, 1d+4h pooled", fontsize=10)
            ax.legend(loc="upper left", fontsize=8)
            ax2.legend(loc="lower right", fontsize=8)
            ax2.set_ylabel("OU positive control (right axis)", color="C3", fontsize=8)
            ax.axhline(0, color="#999", lw=0.5)
    fig.suptitle(f"Residual book (k={ks}, entry {sel['entry']}, exit {sel['exit']}, half-life <= {sel['hl_max']:g}): "
                 "summed daily returns on unit gross")
    fig.tight_layout()
    fig.savefig(PL / "equity.png", dpi=80)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(16, 5))
    for (uni, src), c in ((("u143", "real"), "k"), (("u12", "real"), "C1"), (("u143", "iid"), "C0")):
        g = books.get((uni, src))
        if g is None:
            continue
        eq = g["net"].cumsum()
        ax.fill_between(day(eq.index), eq - eq.cummax(), 0, color=c, alpha=0.3, label=f"{uni} {src} net")
    for cd in cds:
        ax.axvline(day(cd)[0], color="r", lw=0.6, ls=":")
    ax.set_title("Drawdown of the pooled residual book, net (dotted: the 10 worst equal-weight crypto days)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PL / "drawdown.png", dpi=80)
    plt.close(fig)

    # 7. DISPLACE_C beta / residual
    f = OUT / "displace.csv"
    if f.exists():
        c = pd.read_csv(f)
        c = c[c["set"] == "all131"]
        fig, ax = plt.subplots(figsize=(13, 5))
        labs, xs = [], np.arange(0)
        rows = [(iv, sd) for iv in ("4h", "1d", "4h+1d") for sd in (1, -1, 0)]
        for j, (iv, sd) in enumerate(rows):
            x = c[(c["iv"] == iv) & (c["side"] == sd)]
            if not len(x):
                continue
            x = x.iloc[0]
            ax.bar(j - 0.27, x["R"], 0.25, color="#555", label="total R" if j == 0 else None)
            ax.bar(j, x["Rbeta_ew"], 0.25, color="C0", label="market (beta) part" if j == 0 else None)
            ax.bar(j + 0.27, x["Rres_ew"], 0.25, color="C3", label="residual" if j == 0 else None)
            if np.isfinite(x.get("res_lo_ew", np.nan)):
                ax.errorbar(j + 0.27, x["Rres_ew"], [[x["Rres_ew"] - x["res_lo_ew"]], [x["res_hi_ew"] - x["Rres_ew"]]], color="k", capsize=3)
            labs.append(f"{iv} {'long' if sd > 0 else 'short' if sd < 0 else 'both'}\nn={int(x['n'])}")
            xs = np.append(xs, j)
        ax.set_xticks(xs, labs, fontsize=8)
        ax.axhline(0, color="k", lw=0.6)
        ax.set_ylabel("mean R a trade")
        ax.set_title("DISPLACE_C at a 12-bar low, structure exit, 131 fresh coins: market beta (equal-weight index) against residual (90% day-bootstrap)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(PL / "displace_split.png", dpi=80)
        plt.close(fig)

    # 8. P(N R)
    f = OUT / "rtrades.csv"
    if f.exists():
        t = pd.read_csv(f)
        fig, axes = plt.subplots(1, 2, figsize=(15, 5))
        for ax, uni in zip(axes, ("u143", "u12")):
            for src, c in (("real", "k"), ("iid", "C0"), ("shuffle", "C2"), ("ou", "C3")):
                x = t[(t["universe"] == uni) & (t["source"] == src)]
                if not len(x):
                    continue
                w = x["n"] / x["n"].sum()
                ax.plot(NS, [(x[f"P{N}R"] * w).sum() for N in NS], "o-", color=c, label=f"{src} (n={int(x['n'].sum())})")
            ax.plot(NS, [1 / (N + 1) for N in NS], "k:", label="1/(N+1)")
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.set_xlabel("N")
            ax.set_ylabel("P(+N R before -1R)")
            ax.set_title(f"{uni}: single-name trades, every timeframe pooled" + (" (2024+)" if uni == "u12" else ""))
            ax.legend()
        fig.tight_layout()
        fig.savefig(PL / "pnr.png", dpi=80)
        plt.close(fig)
    print("plots written", flush=True)


def main():
    {"fetch": fetch, "smoke": smoke, "spectra": spectra, "discover": discover, "confirm": confirm,
     "displace": displace, "report": report, "plot": plot}[os.environ.get("MODE", "smoke")]()


if __name__ == "__main__":
    main()
