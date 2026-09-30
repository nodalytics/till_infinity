"""Information flow in market structure: is a feature novel, and does flow warn of transitions?

The desk forecasts risk and not direction (`research/docs/findings.md`). Two questions, borrowed
from information theory and network science, both pre-registered here.

## 1. Novelty: how much *new* information does a feature add to the state we already have?

`novelty(y, x, z)` estimates the conditional mutual information I(Y; X | Z) in bits, where Z is
the production state. A feature that only repackages what Z already says scores zero, however
well it correlates with Y on its own.

- **Estimator:** plug-in entropies on quantile bins with the Miller-Madow correction.
- **Bias:** the null mean from shuffling X *within* Z-cells (which keeps X's relation to Z and
  breaks only X's link to Y given Z) is subtracted, leaving the excess.
- **Standard error:** a block jackknife over 10 contiguous stretches of each series, so the time
  structure the shuffle ignores still enters the error.
- **Also reported:** I(Y; X) unconditional, the same way, and the redundancy 1 - CMI/MI: the share
  of what X says about Y that Z already said.
- **Targets Y:** next-bar |return| (in the production unit), the shock label (a bar beyond 4x the
  trailing mean |r| within the next 4 bars, as `structures/learning/shocks.py`), and next-bar sign.
- **Candidates X:**
  - the tested indicators: RSI(14), stochastic %K, Bollinger z, MACD histogram, EMA(9) distance;
  - the ZMA-style stretch;
  - recent moves r1/r5/r20 and range;
  - tick-volume z;
  - bar-based VPIN (bulk volume classification).
- **State Z:** the volatility unit's regime (lvol), the hour-of-week clock, the unit's percentile
  over 500 bars, and recent shock count.
- **Sanity checks, known in advance:** lvol and the shock count carry information about |r| (they
  are the shock forecaster's heart); indicators carry about none about the sign.
- **Deriv** is a market, scored as its own family.

## 2. Directed information networks: does flow change *before* regime transitions?

- **Panel:** returns in each asset's own unit, on rolling windows.
- **Networks:**
  - transfer entropy TE(i -> j) = I(y_j,t+1; y_i,t | y_j,t) on terciles, less the same with the
    source circularly shifted;
  - Granger as a baseline (partial correlation of the source with the target's next move, own lag
    removed).
- **Network measures per window:**
  - total flow, density above the window's shifted-source 95th percentile;
  - out-flow Gini, top node's share, spectral radius, modularity;
  - Granger density;
  - and the correlation network's topology: minimum-spanning-tree length, the largest eigenvalue's
    share, and the absorption ratio (Kritzman et al. 2011).
- **Targets, over the next step:**
  - a volatility-regime transition: the basket's mean |y| over the next step against the window's,
    top decile on the training block;
  - a cross-asset shock: the share of assets with a 4x bar in the next step, top quintile.
- **Baseline:** the shock forecaster's state at basket level (lvol, the unit's percentile, recent
  shocks, the recent-vs-window volatility ratio, weekday).
- **Pass bar:** logistic regression, fit on the first 60% of windows and scored on the last 40%.
  Network sets are added to the baseline, in levels and in 5-window changes. A set passes only if
  its incremental AUC is >= 0.01, the block-bootstrap CI is above 0 in both halves of the test
  block, and it does not pass on the controls:
  - **factor walks we generate:** common and own GARCH volatility, t(3) shocks, cross-correlation
    and no lead-lag, so TE ~ 0;
  - **the real panel with each asset circularly shifted:** cross-structure destroyed.
- **Deriv** runs as its own node set, joined to the real panel, as a sanity check: its flows
  should sit at the null.
- **Deflation:** BH across the study's tests, and deflation against the expected maximum of its
  trials (`lopez-de-prado.md`).

Run on the lab (parallel parts), then PART=report:
  PART=cmi INTERVAL=1h SEQLAB=... python research/harness/infoflow.py
  PART=net INTERVAL=1h ...
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import minimum_spanning_tree
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

PART = os.environ.get("PART", "cmi")
INTERVAL = os.environ.get("INTERVAL", "1h")
OUT = Path(os.environ.get("OUT", ".data/infoflow"))
LOG2 = math.log(2)

FAMILIES = {
    "fx": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY",
           "EURGBP"],
    "metals": ["XAUUSD", "XAGUSD"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD"],
    "deriv": ["Volatility_75_Index", "Volatility_25_Index", "Boom_1000_Index", "Crash_1000_Index",
              "Jump_50_Index", "Step_Index"],
}
REAL = FAMILIES["fx"] + FAMILIES["metals"] + FAMILIES["crypto"]
X_NAMES = ["rsi14", "stochk", "bbz20", "macd", "ema9", "zma50", "r1", "r5", "r20", "rng", "volz",
           "vpin50"]
Z_NAMES = ["lvol", "clock", "trrank", "shocks100"]


# ------------------------------------------------------------------------------------ the estimator

def _codes(v: np.ndarray, bins: int) -> np.ndarray:
    """Quantile-bin codes 0..bins-1 (ties share a bin)."""
    edges = np.unique(np.quantile(v, np.linspace(0, 1, bins + 1)[1:-1]))
    return np.searchsorted(edges, v, side="right").astype(np.int64)


def _joint(*codes: np.ndarray) -> np.ndarray:
    out = np.zeros(len(codes[0]), dtype=np.int64)
    for c in codes:
        out = out * (int(c.max()) + 1) + c
    return out


def _entropy(code: np.ndarray) -> float:
    """Plug-in entropy in nats with the Miller-Madow bias correction."""
    counts = np.bincount(np.unique(code, return_inverse=True)[1])
    n = counts.sum()
    p = counts / n
    return float(-(p * np.log(p)).sum() + (len(counts) - 1) / (2 * n))


def _cmi(y: np.ndarray, x: np.ndarray, z: np.ndarray) -> float:
    return (_entropy(_joint(x, z)) + _entropy(_joint(y, z)) - _entropy(_joint(x, y, z))
            - _entropy(z))


def _mi(y: np.ndarray, x: np.ndarray) -> float:
    return _entropy(x) + _entropy(y) - _entropy(_joint(x, y))


def _shuffle_within(x: np.ndarray, z: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """x permuted within each z-cell: keeps x's relation to z, breaks its link to y given z."""
    by_z = np.argsort(z, kind="stable")
    shuffled = np.lexsort((rng.random(len(z)), z))
    out = np.empty_like(x)
    out[shuffled] = x[by_z]
    return out


def novelty(y, x, z, *, blocks=None, ybins: int = 6, xbins: int = 6, zbins: int = 3,
            discrete_y: bool = False, reps: int = 10, seed: int = 0) -> dict[str, float]:
    """How much new information x adds about y beyond the state z, in bits.

    `y`, `x`: 1-d arrays; `z`: 2-d array (rows x state columns) or None; `blocks`: optional
    contiguous-stretch ids for the jackknife (default 10 equal stretches in row order).
    Returns the excess conditional and unconditional mutual information, the jackknife standard
    error and t of the conditional one, H(Y|Z), the share of it X explains, and the redundancy.
    """
    y, x = np.asarray(y, float), np.asarray(x, float)
    zz = np.zeros((len(y), 0)) if z is None else np.asarray(z, float).reshape(len(y), -1)
    ok = np.isfinite(y) & np.isfinite(x) & np.isfinite(zz).all(axis=1)
    y, x, zz = y[ok], x[ok], zz[ok]
    if blocks is None:
        blocks = (np.arange(len(y)) * 10 // max(len(y), 1))
    else:
        blocks = np.asarray(blocks)[ok]
    if len(y) < 500:
        return {"n": len(y)}
    yc = y.astype(np.int64) if discrete_y else _codes(y, ybins)
    xc = _codes(x, xbins)
    zc = _joint(*[_codes(zz[:, k], zbins) for k in range(zz.shape[1])]) if zz.shape[1] else \
        np.zeros(len(y), dtype=np.int64)
    rng = np.random.default_rng(seed)

    def excess(idx):
        obs = _cmi(yc[idx], xc[idx], zc[idx])
        null = np.mean([_cmi(yc[idx], _shuffle_within(xc[idx], zc[idx], rng), zc[idx])
                        for _ in range(reps)])
        return obs - null

    full = np.arange(len(y))
    cmi_x = excess(full)
    mi_obs = _mi(yc, xc)
    mi_null = np.mean([_mi(yc, rng.permutation(xc)) for _ in range(reps)])
    mi_x = mi_obs - mi_null
    # Jackknife over contiguous stretches: each leave-one-out uses fewer null reps (cost).
    uniq = np.unique(blocks)
    loo = []
    for b in uniq:
        idx = np.flatnonzero(blocks != b)
        obs = _cmi(yc[idx], xc[idx], zc[idx])
        null = np.mean([_cmi(yc[idx], _shuffle_within(xc[idx], zc[idx], rng), zc[idx])
                        for _ in range(max(2, reps // 5))])
        loo.append(obs - null)
    loo = np.array(loo)
    k = len(loo)
    se = math.sqrt((k - 1) / k * ((loo - loo.mean()) ** 2).sum()) if k > 1 else float("nan")
    h_y_z = _entropy(_joint(yc, zc)) - _entropy(zc)
    return {
        "n": int(len(y)),
        "cmi_bits": cmi_x / LOG2,
        "cmi_se_bits": se / LOG2,
        "t": cmi_x / se if se > 0 else float("nan"),
        "mi_bits": mi_x / LOG2,
        "h_y_given_z_bits": h_y_z / LOG2,
        "share_of_remaining": cmi_x / h_y_z if h_y_z > 0 else float("nan"),
        "redundancy": 1 - max(cmi_x, 0.0) / mi_x if mi_x > 1e-12 else float("nan"),
    }


# ------------------------------------------------------------------------------------ the frames

def frame(sym: str, iv: str) -> pd.DataFrame:
    """One series' bars with targets, candidates and state, in the production volatility unit."""
    df = spikerisk.load(None, sym, "SEQLAB", iv)
    c = np.log(df["close"])
    h, lo = np.log(df["high"]), np.log(df["low"])
    prev = c.shift(1)
    tr = pd.concat([h - lo, (h - prev).abs(), (lo - prev).abs()], axis=1).max(axis=1)
    sig = tr.ewm(alpha=1 / 14, adjust=False).mean()
    r = c.diff()
    y = r / sig.shift(1)
    shock = (r.abs() > 4 * r.abs().rolling(100).mean().shift(1)).astype(float)
    out = pd.DataFrame({"ts": df["ts"].to_numpy()})
    out["absy_next"] = (r.shift(-1) / sig).abs().to_numpy()
    nxt = (r.shift(-1) / sig).to_numpy()
    out["sign_next"] = np.where(nxt > 0, 1.0, np.where(nxt < 0, 0.0, np.nan))
    ahead = pd.concat([shock.shift(-k) for k in range(1, 5)], axis=1).max(axis=1)
    out["shock_next4"] = ahead.to_numpy()
    out.loc[out.index[-4:], "shock_next4"] = np.nan
    # the production state
    out["lvol"] = np.log(sig / sig.rolling(500).mean()).to_numpy()
    out["trrank"] = sig.rolling(500).rank(pct=True).to_numpy()
    out["shocks100"] = shock.rolling(100).sum().to_numpy()
    when = pd.to_datetime(df["ts"], unit="s")
    out["week_hour"] = (when.dt.weekday * 24 + when.dt.hour).to_numpy()
    out["y_abs"] = y.abs().to_numpy()
    # candidates
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    out["rsi14"] = (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
    ll, hh = lo.rolling(14).min(), h.rolling(14).max()
    out["stochk"] = (100 * (c - ll) / (hh - ll)).rolling(3).mean().to_numpy()
    out["bbz20"] = ((c - c.rolling(20).mean()) / c.rolling(20).std()).to_numpy()
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    out["macd"] = ((macd - macd.ewm(span=9, adjust=False).mean()) / sig).to_numpy()
    out["ema9"] = ((c - c.ewm(span=9, adjust=False).mean()) / sig).to_numpy()
    out["zma50"] = ((c - c.rolling(50).mean()) / c.rolling(50).std()).to_numpy()
    out["r1"] = y.to_numpy()
    out["r5"] = ((c - c.shift(5)) / sig).to_numpy()
    out["r20"] = ((c - c.shift(20)) / sig).to_numpy()
    out["rng"] = ((h - lo) / sig).to_numpy()
    lv = np.log(df["volume"].replace(0, np.nan))
    out["volz"] = ((lv - lv.rolling(500).mean()) / lv.rolling(500).std()).to_numpy()
    zr = r / r.rolling(500).std()
    imb = (2 * norm.cdf(zr.fillna(0)) - 1).__abs__()
    vol = df["volume"].fillna(0)
    out["vpin50"] = ((vol * imb).rolling(50).sum() / vol.rolling(50).sum()).to_numpy()
    out["block"] = np.arange(len(out)) * 10 // len(out)
    return out


def with_clock(f: pd.DataFrame, cut: int) -> pd.DataFrame:
    """The hour-of-week volatility multiplier, learned on rows before `cut` (production learns it
    online; this is the out-of-sample stand-in)."""
    prof = f.iloc[:cut].groupby("week_hour")["y_abs"].mean()
    f["clock"] = f["week_hour"].map(prof / f["y_abs"].iloc[:cut].mean()).to_numpy()
    return f


# ------------------------------------------------------------------------------------ part 1

def run_cmi() -> None:
    results = []
    for fam, syms in FAMILIES.items():
        parts = []
        for s in syms:
            try:
                f = frame(s, INTERVAL)
            except (ValueError, FileNotFoundError) as exc:
                print(f"  skip {s}: {str(exc)[:60]}", flush=True)
                continue
            f = with_clock(f, int(0.6 * len(f))).iloc[500:].reset_index(drop=True)
            f["half"] = np.where(np.arange(len(f)) < 0.6 * len(f), "first60", "last40")
            f["block"] = f["block"] + 10 * len(parts)
            parts.append(f)
        if not parts:
            continue
        allf = pd.concat(parts, ignore_index=True)
        print(f"\n== {fam} {INTERVAL}: {len(allf):,} rows", flush=True)
        # sanity: the state's own parts about |r|, given the clock only
        for name in ("lvol", "shocks100"):
            got = novelty(allf["absy_next"], allf[name], allf[["clock"]], blocks=allf["block"])
            results.append({"family": fam, "interval": INTERVAL, "y": "absy_next", "x": name,
                            "given": "clock", "half": "all", **got})
            print(f"  sanity {name:9s} -> |r| | clock: {got.get('cmi_bits', float('nan')):.4f} bits "
                  f"(t {got.get('t', float('nan')):+.1f})", flush=True)
        for half in ("first60", "last40"):
            g = allf[allf["half"] == half]
            for yname, disc in (("absy_next", False), ("shock_next4", True), ("sign_next", True)):
                for xname in X_NAMES:
                    got = novelty(g[yname], g[xname], g[Z_NAMES], blocks=g["block"],
                                  discrete_y=disc, seed=hash((fam, half, yname, xname)) % 2**31)
                    results.append({"family": fam, "interval": INTERVAL, "y": yname, "x": xname,
                                    "given": "state", "half": half, **got})
                    if "cmi_bits" in got:
                        print(f"  {half:7s} {yname:11s} {xname:7s} CMI {got['cmi_bits']*1000:+7.3f} mbit "
                              f"(t {got['t']:+5.1f}) | MI {got['mi_bits']*1000:+7.3f} | share "
                              f"{got['share_of_remaining']*100:+.3f}% | redundancy {got['redundancy']:+.2f}",
                              flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"cmi_{INTERVAL}.json").write_text(json.dumps(results, default=float))


# ------------------------------------------------------------------------------------ part 2

def panel_returns(syms: list[str], iv: str) -> pd.DataFrame:
    cols = {}
    for s in syms:
        try:
            df = spikerisk.load(None, s, "SEQLAB", iv)
        except (ValueError, FileNotFoundError):
            continue
        cols[s] = pd.Series(np.log(df["close"].to_numpy()), index=df["ts"].to_numpy()).diff()
    return pd.DataFrame(cols).dropna(how="any")


def factor_walks(n: int, t: int, seed: int = 3) -> pd.DataFrame:
    """Our control: a common and own GARCH(1,1) volatility, t(3) shocks, cross-correlated through
    the common factor, no lead-lag."""
    rng = np.random.default_rng(seed)

    def garch(k):
        e = rng.standard_t(3, (t, k)) / math.sqrt(3)
        out = np.empty((t, k))
        var = np.full(k, 1.0)
        for i in range(t):
            out[i] = math.sqrt(1) * np.sqrt(var) * e[i]
            var = 0.02 + 0.08 * out[i] ** 2 + 0.9 * var
        return out

    f = garch(1)[:, 0]
    own = garch(n)
    beta = rng.uniform(0.3, 0.8, n)
    r = f[:, None] * beta + own * np.sqrt(1 - beta**2)
    return pd.DataFrame(r * 1e-3, columns=[f"walk{i}" for i in range(n)])


def _gini(v: np.ndarray) -> float:
    v = np.sort(np.clip(v, 0, None))
    if v.sum() <= 0:
        return 0.0
    n = len(v)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(v) / (n * v.sum()))


def _te_from_counts(counts: np.ndarray, k: int) -> np.ndarray:
    """TE in nats from joint counts over (a = target next, b = target now, s = source now)."""
    n = counts.shape[0]
    p = counts.reshape(n, k, k, k) / counts.sum(axis=1)[:, None, None, None]
    pbs = p.sum(axis=1)
    pab = p.sum(axis=3)
    pb = p.sum(axis=(1, 3))
    with np.errstate(divide="ignore", invalid="ignore"):
        term = p * np.log(p * pb[:, None, :, None] / (pab[:, :, :, None] * pbs[:, None, :, :]))
    return np.nansum(term, axis=(1, 2, 3))


def _te_matrix(codes: np.ndarray, k: int) -> np.ndarray:
    """TE(i -> j) in nats for every pair, lag 1, from codes 0..k-1 (rows x assets).

    One bincount per target: the source index is folded into the bin, so every source is counted
    in a single pass."""
    t, n = codes.shape
    a, b, s = codes[1:], codes[:-1], codes[:-1]
    shift = np.arange(n)[None, :] * k**3
    te = np.zeros((n, n))
    for j in range(n):
        joint = a[:, j][:, None] * k * k + b[:, j][:, None] * k + s + shift
        counts = np.bincount(joint.ravel(), minlength=n * k**3).reshape(n, k**3)
        te[:, j] = _te_from_counts(counts, k)
    np.fill_diagonal(te, 0.0)
    return te


def _te_row(source: np.ndarray, codes: np.ndarray, k: int) -> np.ndarray:
    """TE(source -> j) for every target j, in one bincount."""
    n = codes.shape[1]
    a, b = codes[1:], codes[:-1]
    joint = a * k * k + b * k + source[:-1][:, None] + np.arange(n)[None, :] * k**3
    counts = np.bincount(joint.ravel(), minlength=n * k**3).reshape(n, k**3)
    return _te_from_counts(counts, k)


def _te_with_null(codes: np.ndarray, k: int, rng: np.random.Generator, W: int):
    """Observed TE, and a shifted-source null per pair (each source rolled, the target kept)."""
    te = _te_matrix(codes, k)
    null = np.zeros_like(te)
    for i in range(codes.shape[1]):
        null[i] = _te_row(np.roll(codes[:, i], int(rng.integers(50, W - 50))), codes, k)
    np.fill_diagonal(null, 0.0)
    return te, null


def _granger(y: np.ndarray) -> np.ndarray:
    """Squared partial correlation of y_i,t with y_j,t+1, y_j,t removed (with intercept)."""
    a, b = y[1:], y[:-1]
    n = y.shape[1]
    g = np.zeros((n, n))
    for j in range(n):
        X = np.column_stack([np.ones(len(b)), b[:, j]])
        pinv = np.linalg.pinv(X)
        ra = a[:, j] - X @ (pinv @ a[:, j])
        rs = b - X @ (pinv @ b)
        num = (rs * ra[:, None]).sum(axis=0)
        den = np.sqrt((rs**2).sum(axis=0) * (ra**2).sum())
        g[:, j] = (num / np.where(den > 0, den, np.nan)) ** 2
    np.fill_diagonal(g, 0.0)
    return np.nan_to_num(g)


def _modularity(w: np.ndarray) -> float:
    try:
        import networkx as nx
        from networkx.algorithms.community import greedy_modularity_communities, modularity
    except ImportError:  # the lab has it; a bare local venv may not
        return float("nan")

    sym = (w + w.T) / 2
    if sym.sum() <= 0:
        return 0.0
    graph = nx.from_numpy_array(sym)
    try:
        comms = greedy_modularity_communities(graph, weight="weight")
        return float(modularity(graph, comms, weight="weight"))
    except Exception:
        return 0.0


def _net_stats(eff: np.ndarray, prefix: str) -> dict[str, float]:
    out_strength = eff.sum(axis=1)
    total = out_strength.sum()
    return {
        f"{prefix}_total": float(eff.sum()),
        f"{prefix}_gini": _gini(out_strength),
        f"{prefix}_top": float(out_strength.max() / total) if total > 0 else 0.0,
        f"{prefix}_spectral": float(np.max(np.abs(np.linalg.eigvals(eff)))),
        f"{prefix}_modularity": _modularity(eff),
    }


def window_features(r: pd.DataFrame, W: int, S: int, seed: int = 0) -> pd.DataFrame:
    """Network, topology and baseline features at each window end, and next-step targets.

    Two directed networks per window:
    - **sign-TE** on the sign of the move (directional information);
    - **magnitude-TE** on terciles of |move| (volatility information, which a shared volatility
      factor produces on its own, so the walk control is what judges it).

    Densities use a threshold pooled over every window's shifted-source nulls.
    """
    rng = np.random.default_rng(seed)
    absr = r.abs()
    sig = absr.ewm(alpha=1 / 14, adjust=False).mean().shift(1)
    y = (r / sig).to_numpy()
    shock = (absr > 4 * absr.rolling(100).mean().shift(1)).to_numpy(float)
    lvol = np.log(sig / sig.rolling(500).mean()).to_numpy()
    trrank = sig.rolling(500).rank(pct=True).to_numpy()
    shocks100 = pd.DataFrame(shock).rolling(100).sum().to_numpy()
    ts = r.index.to_numpy()
    rows, raw = [], []
    start = max(W, 600)
    for e in range(start, len(r) - S, S):
        win = y[e - W:e]
        if not np.isfinite(win).all():
            continue
        off = ~np.eye(win.shape[1], dtype=bool)
        sign = (win > 0).astype(np.int64)
        mag = np.column_stack([_codes(np.abs(win[:, k]), 3) for k in range(win.shape[1])])
        te_s, null_s = _te_with_null(sign, 2, rng, W)
        te_m, null_m = _te_with_null(mag, 3, rng, W)
        g = _granger(win)
        rolled = np.column_stack([np.roll(win[:, k], int(rng.integers(50, W - 50)))
                                  for k in range(win.shape[1])])
        g_null = _granger(rolled)
        raw.append((te_s[off], null_s[off], te_m[off], null_m[off], g[off], g_null[off]))
        corr = np.corrcoef(win.T)
        eig = np.sort(np.linalg.eigvalsh(corr))[::-1]
        kk = math.ceil(len(eig) / 5)
        dist = np.sqrt(np.clip(2 * (1 - corr), 0, None))
        nxt = np.abs(y[e:e + S])
        when = pd.Timestamp(int(ts[e - 1]), unit="s")
        rows.append({
            "ts": int(ts[e - 1]),
            **_net_stats(np.clip(te_s - null_s, 0, None) * ~np.eye(len(te_s), dtype=bool), "tes"),
            **_net_stats(np.clip(te_m - null_m, 0, None) * ~np.eye(len(te_m), dtype=bool), "tem"),
            "mst": float(minimum_spanning_tree(dist).sum()),
            "lam1": float(eig[0] / len(eig)),
            "absorption": float(eig[:kk].sum() / eig.sum()),
            "b_lvol": float(np.nanmean(lvol[e - 1])),
            "b_trrank": float(np.nanmean(trrank[e - 1])),
            "b_shocks": float(np.nanmean(shocks100[e - 1])),
            "b_ratio": float(np.nanmean(np.abs(win[-S:])) / np.nanmean(np.abs(win))),
            "b_wday_s": math.sin(2 * math.pi * when.weekday() / 7),
            "b_wday_c": math.cos(2 * math.pi * when.weekday() / 7),
            "t_ratio": float(np.nanmean(nxt) / np.nanmean(np.abs(win))),
            "t_share": float((shock[e:e + S].max(axis=0) > 0).mean()),
        })
    wf = pd.DataFrame(rows)
    if len(raw):
        thr_s = np.quantile(np.concatenate([x[1] for x in raw]), 0.95)
        thr_m = np.quantile(np.concatenate([x[3] for x in raw]), 0.95)
        thr_g = np.quantile(np.concatenate([x[5] for x in raw]), 0.95)
        wf["tes_density"] = [float((x[0] > thr_s).mean()) for x in raw]
        wf["tem_density"] = [float((x[2] > thr_m).mean()) for x in raw]
        wf["gr_density"] = [float((x[4] > thr_g).mean()) for x in raw]
    return wf


SIGN_SET = ["tes_total", "tes_density", "tes_gini", "tes_top", "tes_spectral", "tes_modularity",
            "gr_density"]
MAG_SET = ["tem_total", "tem_density", "tem_gini", "tem_top", "tem_spectral", "tem_modularity"]
CORR_SET = ["mst", "lam1", "absorption"]
BASE = ["b_lvol", "b_trrank", "b_shocks", "b_ratio", "b_wday_s", "b_wday_c"]


def _auc_gain(wf: pd.DataFrame, target: str, extra: list[str], seed: int = 0) -> dict:
    """Walk-forward 60/40: AUC of base+extra over base, with block-bootstrap CIs, per test half."""
    f = wf.copy()
    extra = [c for c in extra if c in f and f[c].notna().any()]
    for col in extra:
        f[col + "_d5"] = f[col] - f[col].shift(5)
    extra = extra + [c + "_d5" for c in extra]
    extra = [c for c in extra if f[c].notna().any()]  # modularity is NaN without networkx
    f = f.dropna(subset=BASE + extra + [target]).reset_index(drop=True)
    cut = int(0.6 * len(f))
    tr, te = f.iloc[:cut], f.iloc[cut:]
    q = {"t_ratio": 0.9, "t_share": 0.8}[target]
    thr = tr[target].quantile(q)
    ytr, yte = (tr[target] > thr).astype(int), (te[target] > thr).astype(int)
    if ytr.nunique() < 2 or yte.nunique() < 2:
        return {"n_test": len(te)}

    def fit(cols):
        mu, sd = tr[cols].mean(), tr[cols].std().replace(0, 1)
        m = LogisticRegression(C=1.0, max_iter=2000).fit((tr[cols] - mu) / sd, ytr)
        return m.predict_proba((te[cols] - mu) / sd)[:, 1]

    p0, p1 = fit(BASE), fit(BASE + extra)
    rng = np.random.default_rng(seed)
    out = {"n_test": len(te), "base_rate": float(yte.mean()),
           "auc_base": roc_auc_score(yte, p0), "auc_full": roc_auc_score(yte, p1)}
    out["gain"] = out["auc_full"] - out["auc_base"]
    y_arr = yte.to_numpy()
    for name, idx in (("h1", np.arange(len(te) // 2)), ("h2", np.arange(len(te) // 2, len(te)))):
        yy, a0, a1 = y_arr[idx], p0[idx], p1[idx]
        if yy.sum() < 10 or (1 - yy).sum() < 10:
            out[name] = {"events": int(yy.sum()), "too_few": True}
            continue
        g = roc_auc_score(yy, a1) - roc_auc_score(yy, a0)
        boots = []
        nb = max(1, len(idx) // 10)
        for _ in range(500):
            pick = np.concatenate([np.arange(b * 10, min((b + 1) * 10, len(idx)))
                                   for b in rng.integers(0, nb, nb)])
            if len(np.unique(yy[pick])) < 2:
                continue
            boots.append(roc_auc_score(yy[pick], a1[pick]) - roc_auc_score(yy[pick], a0[pick]))
        lo, hi = np.quantile(boots, [0.025, 0.975])
        out[name] = {"gain": g, "lo": float(lo), "hi": float(hi), "se": float(np.std(boots))}
    return out


def run_net() -> None:
    W, S = {"1h": (480, 24), "15m": (960, 96)}[INTERVAL]
    real = panel_returns(REAL, INTERVAL)
    deriv = panel_returns(FAMILIES["deriv"], INTERVAL)
    print(f"real panel {real.shape}, deriv panel {deriv.shape}, W={W}, S={S}", flush=True)
    rng = np.random.default_rng(11)
    shifted = real.copy()
    for col in shifted.columns:
        shifted[col] = np.roll(shifted[col].to_numpy(),
                               int(rng.integers(len(shifted) // 10, len(shifted) - len(shifted) // 10)))
    walks = factor_walks(real.shape[1], len(real))
    walks.index = real.index
    panels = {"real": real, "shifted": shifted, "walks": walks}
    results = {}
    for name, p in panels.items():
        wf = window_features(p, W, S)
        wf.to_csv(OUT / f"net_{INTERVAL}_{name}.csv", index=False)
        print(f"\n== {name}: {len(wf)} windows | density (null 0.05): sign-TE "
              f"{wf['tes_density'].mean():.3f}, magnitude-TE {wf['tem_density'].mean():.3f}, Granger "
              f"{wf['gr_density'].mean():.3f}", flush=True)
        for target in ("t_ratio", "t_share"):
            for label, extra in (("sign flow", SIGN_SET), ("magnitude flow", MAG_SET),
                                 ("corr topology", CORR_SET)):
                got = _auc_gain(wf, target, list(extra))
                results[f"{name}|{target}|{label}"] = got
                h1, h2 = got.get("h1") or {}, got.get("h2") or {}
                print(f"  {target:8s} {label:14s} base AUC {got.get('auc_base', float('nan')):.3f} "
                      f"-> {got.get('auc_full', float('nan')):.3f} (gain {got.get('gain', float('nan')):+.3f}) "
                      f"| h1 {h1.get('gain', float('nan')):+.3f} [{h1.get('lo', float('nan')):+.3f}, "
                      f"{h1.get('hi', float('nan')):+.3f}] | h2 {h2.get('gain', float('nan')):+.3f} "
                      f"[{h2.get('lo', float('nan')):+.3f}, {h2.get('hi', float('nan')):+.3f}] "
                      f"| n {got.get('n_test')} base rate {got.get('base_rate', float('nan')):.2f}",
                      flush=True)
    # The Deriv sanity: flow among Deriv indices, and from Deriv to the real panel, against the
    # pooled shifted-source null. Published generators are independent, so both should sit at 5%.
    both = real.join(deriv, how="inner")
    if len(both) > W + S + 600:
        yy = both.to_numpy()
        n_real = real.shape[1]
        obs = {"sign": [], "mag": []}
        nulls = {"sign": [], "mag": []}
        blocks = {"sign": [], "mag": []}
        for e in range(W, len(both) - S, S * 4):
            win = yy[e - W:e]
            if not np.isfinite(win).all():
                continue
            sd = np.nanstd(win, axis=0)
            win = win / np.where(sd > 0, sd, 1)
            for kind, codes, kk in (("sign", (win > 0).astype(np.int64), 2),
                                    ("mag", np.column_stack([_codes(np.abs(win[:, c]), 3)
                                                             for c in range(win.shape[1])]), 3)):
                te, null = _te_with_null(codes, kk, rng, W)
                obs[kind].append(te)
                nulls[kind].append(null)
        for kind in ("sign", "mag"):
            n_all = both.shape[1]
            off = ~np.eye(n_all, dtype=bool)
            thr = np.quantile(np.concatenate([nl[off] for nl in nulls[kind]]), 0.95)
            d2r = np.mean([(te[n_real:, :n_real] > thr).mean() for te in obs[kind]])
            d2d = np.mean([(te[n_real:, n_real:][~np.eye(n_all - n_real, dtype=bool)] > thr).mean()
                           for te in obs[kind]])
            r2r = np.mean([(te[:n_real, :n_real][~np.eye(n_real, dtype=bool)] > thr).mean()
                           for te in obs[kind]])
            print(f"== {kind}-TE density (null 0.05): real->real {r2r:.3f} | deriv->deriv {d2d:.3f} "
                  f"| deriv->real {d2r:.3f} over {len(obs[kind])} windows", flush=True)
            results[f"density_{kind}"] = {"real_real": r2r, "deriv_deriv": d2d, "deriv_real": d2r}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"net_{INTERVAL}.json").write_text(json.dumps(results, default=float))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    run_net() if PART == "net" else run_cmi()
