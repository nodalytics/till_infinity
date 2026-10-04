"""Fuzzy-logic trading: an expert Mamdani rule base (FIS-1) and a learned Wang-Mendel one (FIS-2).

Frozen in `fuzzy_rule.json` before any real-data run. Inputs are causal at bar t's close (trend, momentum,
volatility state, position in the 20-bar range, the MCFL fuzzy candle of bar t, distance to the last
confirmed swings); breakpoints are percentiles of the pre-2024 MT5 (non-Deriv, real) bars. FIS-1's score
is long strength minus short strength, the short side being the same rules on the flipped chart. FIS-2
learns rules on the same fuzzy sets from pre-2024 MT5 bars (target: which side moves 1.5 ATR first within
24 bars) and is compared with a logistic regression on the same crisp inputs. Trades: next open in the
score's direction when |score| crosses a threshold, stop beyond the last 3-bar extreme + 0.1 ATR, E1 a
2-ATR trail (primary) or X2 a fixed 2R, 10 days at most. Controls: iid and GARCH walks matched to each
series (256 sub-steps, real timestamps, the real cost in ATR), a coin twin, and the crisp rule base.

  OUT=... MT5BT_DB=... MODE=run|plot|smoke python research/ideas/fuzzy_trade.py
"""
from __future__ import annotations

import json
import os
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

from turn_trade import COINS, FEE, SPLIT, _bin  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/fuzzy"))
RULE = json.loads((HERE / "fuzzy_rule.json").read_text())
SEC = {"1h": 3600, "4h": 14400, "1d": 86400}
NS = (0.5, 1, 2, 4, 10)
SLIP, PAD, WALK_STEPS = RULE["trade"]["slip_atr"], RULE["trade"]["stop_pad_atr"], RULE["controls"]["walk_steps"]
FIS1_GRID = tuple(RULE["fis1"]["threshold_grid"])
FIS1_THR = RULE["fis1"]["threshold"]
Q_GRID = tuple(RULE["fis2"]["threshold_quantile_grid"])
Q_THR = RULE["fis2"]["threshold_quantile"]
WM_INPUTS = tuple(RULE["fis2"]["inputs"])
H_LABEL, K_LABEL = RULE["fis2"]["label_bars"], RULE["fis2"]["label_atr"]


def family(venue, sym):
    if venue == "binance":
        return "binance"
    import run as R
    return R.FAMILY.get(sym, "other")


def mt5_symbols():
    import run as R
    return list(R.FAMILY)


# ---------------------------------------------------------------- inputs

def wilder(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def inputs(df):
    """The crisp inputs, each known at bar t's close; NaN in the warm-up."""
    from mcfl import candles
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    a14, a5, a50 = wilder(tr, 14), wilder(tr, 5), wilder(tr, 50)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(a14 > 0, a14, np.nan)
        ema = pd.Series(c).ewm(span=50, adjust=False).mean().to_numpy()
        X = {"TR": (c - ema) / a, "SLOPE": (ema - np.r_[np.full(5, np.nan), ema[:-5]]) / (5 * a)}
        d = np.diff(c, prepend=c[0])
        up, dn = wilder(np.maximum(d, 0), 14), wilder(np.maximum(-d, 0), 14)
        tot = up + dn
        X["MOM"] = np.where(tot > 0, 100 * up / np.where(tot > 0, tot, 1) - 50, 0.0)
        X["VOL"] = np.log(a5 / a50)
        lo20 = pd.Series(l).rolling(20).min().to_numpy()
        hi20 = pd.Series(h).rolling(20).max().to_numpy()
        w = hi20 - lo20
        X["RPOS"] = np.where(w > 0, (c - lo20) / np.where(w > 0, w, 1), 0.5)
        rng_ = h - l
        pos = rng_ > 0
        safe = np.where(pos, rng_, 1)
        X["CDIR"] = np.where(pos, (c - o) / safe, 0.0)
        X["CLOC"] = np.where(pos, (c - l) / safe, 0.5)
        for k, v in (("CFORCE", np.abs(c - o) / a), ("CSIZE", rng_)):  # MCFL's rolling 10-bar z, current bar in
            m, s = candles._rolling(v, candles.PERIOD, candles.INCLUDE_CURRENT)
            X[k] = np.where(s > 0, (v - m) / np.where(s > 0, s, 1), 0.0)
            X[k][np.isnan(m)] = np.nan
        # swings: a pivot is the extreme of 3 bars either side, known 3 bars after it
        pl = (pd.Series(l).rolling(7, center=True).min().to_numpy() == l)
        ph = (pd.Series(h).rolling(7, center=True).max().to_numpy() == h)
        last_l = pd.Series(np.where(pl, l, np.nan)).shift(3).ffill().to_numpy()
        last_h = pd.Series(np.where(ph, h, np.nan)).shift(3).ffill().to_numpy()
        X["DSL"], X["DSH"] = (c - last_l) / a, (last_h - c) / a
        tot = np.abs(X["DSL"]) + np.abs(X["DSH"])
        X["SWING"] = np.where(tot > 0, (X["DSL"] - X["DSH"]) / np.where(tot > 0, tot, 1), 0.0)
    warm = np.arange(n) < RULE["inputs"]["warmup_bars"]
    for k in X:
        X[k] = np.where(warm, np.nan, X[k])
    X["ATR"] = a14
    return X


def label(df, a):
    """+1 when the high reaches close + 1.5 ATR before the low reaches close - 1.5 ATR within 24 bars,
    -1 the other way, 0 neither or both on one bar."""
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    n = len(c)
    y = np.zeros(n, np.int8)
    up_t, dn_t = c + K_LABEL * a, c - K_LABEL * a
    hit_u = np.full(n, H_LABEL + 1)
    hit_d = np.full(n, H_LABEL + 1)
    for k in range(H_LABEL, 0, -1):
        hh = np.r_[h[k:], np.full(k, np.nan)]
        ll = np.r_[l[k:], np.full(k, np.nan)]
        hit_u = np.where(hh >= up_t, k, hit_u)
        hit_d = np.where(ll <= dn_t, k, hit_d)
    y[(hit_u < hit_d)] = 1
    y[(hit_d < hit_u)] = -1
    y[np.arange(n) >= n - H_LABEL] = 0
    return y


# ---------------------------------------------------------------- membership

def ramp(x, a, b):
    """0 at or below a, 1 at or above b, linear between."""
    return np.clip((x - a) / (b - a), 0.0, 1.0)


def sets(X, bp):
    """The named fuzzy sets FIS-1 reads (for the long side; the short side reads the flipped chart)."""
    S = {}
    for k in ("TR", "SLOPE", "MOM"):
        b, c = bp[k]["b"], bp[k]["c"]
        S[f"{k}_POS"], S[f"{k}_NEG"] = ramp(X[k], 0, b), ramp(-X[k], 0, b)
        S[f"{k}_EXT_POS"], S[f"{k}_EXT_NEG"] = ramp(X[k], b, c), ramp(-X[k], b, c)
    v = bp["VOL"]
    S["VOL_COMPRESSED"], S["VOL_EXPANDED"] = 1 - ramp(X["VOL"], v["q10"], v["q50"]), ramp(X["VOL"], v["q50"], v["q90"])
    S["RPOS_LOW"], S["RPOS_HIGH"] = 1 - ramp(X["RPOS"], 0.2, 0.5), ramp(X["RPOS"], 0.5, 0.8)
    S["BULL"], S["BEAR"] = ramp(X["CDIR"], 0, 0.5), ramp(-X["CDIR"], 0, 0.5)
    S["FORCE_STRONG"] = ramp(X["CFORCE"], 0, 1.0)
    S["CLOSE_HIGH"], S["CLOSE_LOW"] = ramp(X["CLOC"], 0.5, 1.0), ramp(1 - X["CLOC"], 0.5, 1.0)
    d = bp["DIST"]
    for k, nm in (("DSL", "NEAR_SUPPORT"), ("DSH", "NEAR_RESIST")):
        x = X[k]
        S[nm] = np.where(x >= 0, 1 - ramp(x, d["q25"], d["q50"]), 1 - ramp(-x, 0, d["q25"]))
    return S


def crispen(S):
    return {k: (v >= 0.5).astype(float) for k, v in S.items()}


def fis1_long(S):
    """Each rule's firing strength (min for AND, 1 - mu for NOT) and the long strength
    L = sum(w c) / (w0 + sum(w))."""
    nan = np.isnan(S["TR_POS"]) | np.isnan(S["MOM_POS"]) | np.isnan(S["VOL_EXPANDED"]) | \
        np.isnan(S["FORCE_STRONG"]) | np.isnan(S["NEAR_SUPPORT"]) | np.isnan(S["NEAR_RESIST"])
    S = {k: np.nan_to_num(v) for k, v in S.items()}
    sb = np.minimum.reduce([S["BULL"], S["FORCE_STRONG"], S["CLOSE_HIGH"]])
    sr = np.minimum.reduce([S["BEAR"], S["FORCE_STRONG"], S["CLOSE_LOW"]])
    up = np.minimum(S["SLOPE_POS"], 1 - S["TR_NEG"])
    W = {
        "L1_pullback_in_uptrend": np.minimum.reduce([up, S["RPOS_LOW"], 1 - S["MOM_NEG"]]),
        "L2_trend_momentum": np.minimum.reduce([up, S["MOM_POS"], 1 - S["MOM_EXT_POS"]]),
        "L3_bull_candle_at_support": np.minimum.reduce([1 - S["SLOPE_NEG"], S["NEAR_SUPPORT"], sb]),
        "L4_compression_breakout": np.minimum.reduce([S["VOL_COMPRESSED"], S["RPOS_HIGH"], sb]),
        "L5_oversold_reversal": np.minimum(S["MOM_EXT_NEG"], sb),
        "L6_exhaustion": np.minimum.reduce([S["TR_POS"], S["TR_EXT_POS"], sr]),
        "L7_downtrend": np.minimum(S["SLOPE_NEG"], S["TR_NEG"]),
        "L8_overbought_at_resistance": np.minimum(S["MOM_EXT_POS"], S["NEAR_RESIST"]),
        "L9_expanding_selloff": np.minimum(S["VOL_EXPANDED"], sr),
    }
    cons = {r["name"]: r["then"] for r in RULE["fis1"]["rules"]}
    num = sum(W[k] * cons[k] for k in W)
    den = RULE["fis1"]["background_weight"] + sum(W.values())
    L = num / den
    L[nan] = np.nan
    return L, W


def fis1(df, bp, crisp=False):
    """score = L(chart) - L(flipped chart), in [-1, 1]; with the rule strengths of both sides."""
    from mcfl.parse import flip
    out = []
    for frame in (df, flip(df)):
        S = sets(inputs(frame), bp)
        out.append(fis1_long(crispen(S) if crisp else S))
    (Lu, Wu), (Ld, Wd) = out
    return Lu - Ld, Wu, Wd


# ---------------------------------------------------------------- FIS-2: Wang-Mendel

def wm_peaks(bp):
    P = {}
    for k in ("TR", "SLOPE", "MOM"):
        P[k] = (-bp[k]["b"], 0.0, bp[k]["b"])
    P["VOL"] = (bp["VOL"]["q10"], bp["VOL"]["q50"], bp["VOL"]["q90"])
    P["RPOS"] = (0.2, 0.5, 0.8)
    P["CDIR"] = (-0.5, 0.0, 0.5)
    P["CFORCE"] = (-1.0, 0.0, 1.0)
    P["SWING"] = (-0.5, 0.0, 0.5)
    return P


def ruspini(x, p):
    """Three triangular sets peaking at p (shoulders outside): the lower active set and its membership;
    the upper active set (lower + 1) carries 1 - mu."""
    x = np.clip(np.nan_to_num(x, nan=p[1]), p[0], p[2])
    lo = np.where(x <= p[1], 0, 1)
    left = np.where(lo == 0, p[0], p[1])
    right = np.where(lo == 0, p[1], p[2])
    mu_lo = (right - x) / (right - left)
    return lo, mu_lo


def wm_corners(X, P):
    """For each of the 2^d corners: the cell index (base 3) and the product membership."""
    d = len(WM_INPUTS)
    los, mus = zip(*(ruspini(X[k], P[k]) for k in WM_INPUTS))
    for corner in range(2 ** d):
        idx = np.zeros(len(los[0]), np.int64)
        mu = np.ones(len(los[0]))
        for i in range(d):
            hi = (corner >> i) & 1
            idx = idx * 3 + los[i] + hi
            mu = mu * (1 - mus[i] if hi else mus[i])
        yield idx, mu


def wm_learn(X, y, P):
    """Wang-Mendel: each sample builds the rule of its max-membership cell with degree = product of those
    memberships; conflicts are resolved by the degree-weighted mean of the consequents (+1 long first,
    -1 short first, 0 neither). Cells with total degree under `min_support` get no rule."""
    los, mus = zip(*(ruspini(X[k], P[k]) for k in WM_INPUTS))
    idx = np.zeros(len(y), np.int64)
    deg = np.ones(len(y))
    for lo, mu in zip(los, mus, strict=True):
        pick_lo = mu >= 0.5
        idx = idx * 3 + np.where(pick_lo, lo, lo + 1)
        deg = deg * np.where(pick_lo, mu, 1 - mu)
    ncell = 3 ** len(WM_INPUTS)
    wsum = np.bincount(idx, deg, ncell)
    ysum = np.bincount(idx, deg * y, ncell)
    cons = np.where(wsum >= RULE["fis2"]["min_support"], ysum / np.where(wsum > 0, wsum, 1), np.nan)
    return cons, wsum


def wm_score(X, P, cons):
    num = np.zeros(len(X["TR"]))
    den = np.zeros(len(X["TR"]))
    has = np.isfinite(cons)
    c0 = np.nan_to_num(cons)
    for idx, mu in wm_corners(X, P):
        num += mu * c0[idx]
        den += mu * has[idx]
    s = np.where(den > 0, num / np.where(den > 0, den, 1), 0.0)
    bad = np.zeros(len(s), bool)
    for k in WM_INPUTS:
        bad |= np.isnan(X[k])
    return np.where(bad, np.nan, s)


def logit_score(X, model):
    Z = np.column_stack([(X[k] - m) / s for k, m, s in zip(WM_INPUTS, model["mean"], model["sd"], strict=True)])
    z = Z @ np.asarray(model["coef"]) + model["intercept"]
    return 2 / (1 + np.exp(-z)) - 1


# ---------------------------------------------------------------- trades

def exits(o, h, l, c, a, t, H):
    """A long entered at o[t+1], stop under the last 3 bars' low with a pad: E1 (2-ATR trail behind
    completed bars' best high), X2 (fixed 2R), the most R reached under E1, and E1's exit bar and price."""
    n = len(c)
    entry, stop0 = o[t + 1], l[t - 2:t + 1].min() - PAD * a[t]
    risk = entry - stop0
    if not risk > 0:
        return None
    stop, best, R, mfe, xj, xp = stop0, entry, None, 0.0, None, None
    for j in range(t + 1, min(n, t + 1 + H)):
        if j > t + 1:
            stop = max(stop, best - 2 * a[t])
        if l[j] <= stop:
            xp = (min(o[j], stop) if j > t + 1 else stop) - SLIP * a[t]
            R, xj = (xp - entry) / risk, j
            break
        best = max(best, h[j])
        mfe = max(mfe, (h[j] - entry) / risk)
    if R is None:
        xj = min(n - 1, t + H)
        xp = c[xj]
        R = (xp - entry) / risk
    e1 = R
    tgt, R2 = entry + 2 * risk, None
    for j in range(t + 1, min(n, t + 1 + H)):
        if l[j] <= stop0:
            R2 = ((min(o[j], stop0) if j > t + 1 else stop0) - SLIP * a[t] - entry) / risk
            break
        if h[j] >= tgt:
            R2 = (max(o[j], tgt) - entry) / risk
            break
    if R2 is None:
        R2 = (c[min(n - 1, t + H)] - entry) / risk
    return dict(E1=e1, X2=R2, mfe=mfe, risk=risk, entry=entry, stop=stop0, xj=xj, xp=xp)


def entries(score, thr):
    """Bars where |score| first reaches thr on a side (a crossing); the side."""
    s = np.where(np.abs(np.nan_to_num(score)) >= thr, np.sign(np.nan_to_num(score)), 0)
    prev = np.r_[0, s[:-1]]
    t = np.flatnonzero((s != 0) & (s != prev))
    return t, s[t].astype(int)


def load(venue, sym, iv):
    if venue == "binance":
        try:
            df = _bin(sym, iv)
        except OSError:
            return None, None
        return df, FEE * df["close"].to_numpy(float)
    import run as R
    from mt5bt import load_specs
    R.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, iv)
    if df is None:
        return None, None
    df = df.reset_index(drop=True)[["ts", "open", "high", "low", "close", "volume"]]
    spec = load_specs(R.DB).get(sym)
    return df, np.full(len(df), R.spread_floor(sym, spec) * spec.point if spec is not None else 0.0)


def series(job):
    """The real series or its matched walk, and the real cost per bar in ATR units."""
    from mcfl import synth
    venue, sym, iv, source = job
    df, fee_px = load(venue, sym, iv)
    if df is None or len(df) < 400:
        return None, None
    tr = np.maximum(df["high"], df["close"].shift().fillna(df["close"])) - np.minimum(df["low"], df["close"].shift().fillna(df["close"]))
    cost_atr = fee_px / np.maximum(wilder(tr.to_numpy(float), 14), 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    if source != "real":
        ts, n = df["ts"].to_numpy(), len(df)
        sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
        seed = zlib.crc32(f"{venue}{sym}{iv}{source}".encode()) % 100000
        gen = synth.walk if source == "walk" else synth.garch
        df = gen(n, sigma=sigma, seed=seed, steps=WALK_STEPS).reset_index(drop=True).iloc[:n]
        df["ts"] = ts[:len(df)]
        cost_atr = cost_atr[:len(df)]
    return df, cost_atr


def train_rows(job):
    """Stage 1: the crisp inputs and label of every bar of a real series (for breakpoints and FIS-2)."""
    df, _ = series(job)
    if df is None:
        return None
    X = inputs(df)
    y = label(df, X["ATR"])
    keys = sorted(set(WM_INPUTS) | {"TR", "SLOPE", "MOM", "VOL", "DSL", "DSH"})
    d = pd.DataFrame({k: X[k].astype(np.float32) for k in keys})
    d["y"], d["ts"], d["iv"], d["sym"] = y, df["ts"].to_numpy(), job[2], job[1]
    d["ts_end"] = np.r_[df["ts"].to_numpy()[H_LABEL:], np.full(H_LABEL, np.iinfo(np.int64).max)]
    return d.dropna()


def one(args):
    """Stage 2: every system's trades on one series, and a sample of per-bar scores and labels."""
    job, bp, model = args
    from mcfl.parse import flip
    venue, sym, iv, source = job
    df, cost_atr = series(job)
    if df is None:
        return None
    fam = family(venue, sym)
    src = f"{venue}:{source}"
    X = inputs(df)
    a = X["ATR"]
    y = label(df, a)
    P = {k: tuple(v) for k, v in model["peaks"].items()}
    cons = np.asarray(model["wm_cons"], float)
    scores = {"FIS1": fis1(df, bp), "CRISP": fis1(df, bp, crisp=True)}
    Wu, Wd = scores["FIS1"][1], scores["FIS1"][2]
    sc = {k: v[0] for k, v in scores.items()}
    sc["FIS2"] = wm_score(X, P, cons)
    sc["LOGIT"] = logit_score(X, model["logit"])
    frames = {1: df, -1: flip(df)}
    arr = {s: tuple(f[k].to_numpy(float) for k in ("open", "high", "low", "close")) for s, f in frames.items()}
    H = max(1, int(10 * 86400 / SEC[iv]))
    n = len(df)
    ts = df["ts"].to_numpy()
    cache = {}

    def outcome(t, side):
        if (t, side) not in cache:
            cache[t, side] = exits(*arr[side], a, t, H) if 3 <= t < n - 1 and a[t] > 0 else None
        return cache[t, side]

    thr = {"FIS1": FIS1_GRID, "CRISP": FIS1_GRID,
           "FIS2": tuple(model["fis2_thr"][str(q)] for q in Q_GRID),
           "LOGIT": tuple(model["logit_thr"][str(q)] for q in Q_GRID)}
    tag = {"FIS1": FIS1_GRID, "CRISP": FIS1_GRID, "FIS2": Q_GRID, "LOGIT": Q_GRID}
    rng = np.random.default_rng(zlib.crc32(f"coin{venue}{sym}{iv}{source}".encode()))
    rows = []
    for name, s in sc.items():
        for th, tg in zip(thr[name], tag[name], strict=True):
            tt, sides = entries(s, th)
            coin = rng.choice((-1, 1), len(tt))
            for kind, sd in ((name, sides), (f"COIN:{name}", coin)):
                for t, side in zip(tt, sd, strict=True):
                    r = outcome(int(t), int(side))
                    if r is None:
                        continue
                    row = dict(src=src, source=source, venue=venue, family=fam, sym=sym, iv=iv, sys=kind, thr=float(tg),
                               t=int(t), ts=int(ts[t]), side=int(side), score=float(s[t]), risk_atr=r["risk"] / a[t],
                               E1=r["E1"] - cost_atr[t] * a[t] / r["risk"], X2=r["X2"] - cost_atr[t] * a[t] / r["risk"],
                               mfe=r["mfe"], xj=int(r["xj"]),
                               entry=side * r["entry"], stop=side * r["stop"], xp=side * r["xp"])
                    if kind == "FIS1" and source == "real":
                        W = Wu if side > 0 else Wd
                        Wo = Wd if side > 0 else Wu
                        row["fired"] = ";".join(f"{k.split('_')[0]}:{W[k][t]:.2f}" for k in W if W[k][t] >= 0.2)
                        row["fired_opp"] = ";".join(f"{k.split('_')[0]}:{Wo[k][t]:.2f}" for k in Wo if Wo[k][t] >= 0.2)
                    rows.append(row)
    keep = np.random.default_rng(zlib.crc32(f"s{sym}{iv}{source}".encode())).random(n) < RULE["report"]["sample_share"]
    keep &= np.isfinite(sc["FIS1"]) & np.isfinite(sc["FIS2"])
    samp = pd.DataFrame({"src": src, "source": source, "venue": venue, "family": fam, "sym": sym, "iv": iv,
                         "ts": ts[keep], "y": y[keep], **{k: v[keep].astype(np.float32) for k, v in sc.items()}})
    print(f"  {src} {sym} {iv}: {len(rows)} trades", flush=True)
    return pd.DataFrame(rows), samp


# ---------------------------------------------------------------- scoring

def boot_draws(x, rng, draws=2000):
    d = x.groupby(x["ts"] // 86400)["R"].agg(["sum", "count"])
    s, k = d["sum"].to_numpy(), d["count"].to_numpy()
    idx = rng.integers(0, len(d), (draws, len(d)))
    return s[idx].sum(1) / k[idx].sum(1)


def pools(d):
    """(pool name, mask) pairs: MT5 non-Deriv pooled, each MT5 family, Deriv, Binance."""
    mt5 = (d["venue"] == "mt5") & (d["family"] != "deriv")
    out = [("MT5", mt5)]
    out += [(f"MT5:{f}", mt5 & (d["family"] == f)) for f in ("fx", "metal", "index", "energy", "crypto")]
    out += [("DERIV", (d["venue"] == "mt5") & (d["family"] == "deriv")), ("BINANCE", d["venue"] == "binance")]
    return out


def summarise(d, rng):
    rows = []
    for pool, m in pools(d):
        for (source, sys_, thr), g in d[m].groupby(["source", "sys", "thr"]):
            for ex in ("E1", "X2"):
                y = g.assign(R=g[ex])
                b = boot_draws(y, rng) if len(y) > 30 else np.array([np.nan])
                r = dict(pool=pool, source=source, sys=sys_, thr=thr, exit=ex, n=len(y), R=y["R"].mean(),
                         lo=np.nanquantile(b, 0.05), hi=np.nanquantile(b, 0.95), p=float(np.mean(b <= 0)),
                         win=(y["R"] > 0).mean(), R_before=y.loc[y["ts"] < SPLIT, "R"].mean(),
                         R_after=y.loc[y["ts"] >= SPLIT, "R"].mean(), n_before=int((y["ts"] < SPLIT).sum()),
                         **{f"R_{iv}": y.loc[y["iv"] == iv, "R"].mean() for iv in SEC})
                r.update({f"P{N}R": (g["mfe"] >= N).mean() for N in NS})
                rows.append(r)
    return pd.DataFrame(rows)


def bh(p, q):
    p = np.asarray(p, float)
    order = np.argsort(p)
    m = len(p)
    ok = p[order] <= q * np.arange(1, m + 1) / m
    k = np.flatnonzero(ok).max() + 1 if ok.any() else 0
    out = np.zeros(m, bool)
    out[order[:k]] = True
    return out


def auc(score, y):
    from sklearn.metrics import roc_auc_score
    m = np.isfinite(score) & (y != 0)
    return roc_auc_score(y[m] > 0, score[m]) if m.sum() > 100 and len(np.unique(y[m])) == 2 else np.nan


# ---------------------------------------------------------------- stages

def jobs_all():
    J = []
    for src in ("real", "walk", "garch"):
        for iv in SEC:
            J += [("mt5", s, iv, src) for s in mt5_symbols()]
            J += [("binance", c, iv, src) for c in COINS]
    return J


def pool_map(fn, jobs):
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 8))) as p:
        return list(p.map(fn, jobs, chunksize=1))


def fit():
    """Stage 1: breakpoints from pre-2024 MT5 non-Deriv real bars; FIS-2 and the logistic fit on them."""
    from sklearn.linear_model import LogisticRegression
    jobs = [("mt5", s, iv, "real") for iv in SEC for s in mt5_symbols() if family("mt5", s) != "deriv"]
    tr = pd.concat([g for g in pool_map(train_rows, jobs) if g is not None and len(g)], ignore_index=True)
    pre = tr[tr["ts_end"] < SPLIT]
    print(f"training bars (pre-2024, label inside): {len(pre)} from {pre['sym'].nunique()} symbols", flush=True)
    q = RULE["inputs"]["breakpoint_quantiles"]
    bp = {k: {"b": float(np.quantile(np.abs(pre[k]), q["signed_b"])), "c": float(np.quantile(np.abs(pre[k]), q["signed_c"]))}
          for k in ("TR", "SLOPE", "MOM")}
    bp["VOL"] = {f"q{int(100 * x)}": float(np.quantile(pre["VOL"], x)) for x in q["vol"]}
    dist = np.r_[pre["DSL"].to_numpy(), pre["DSH"].to_numpy()]
    dist = dist[dist > 0]
    bp["DIST"] = {f"q{int(100 * x)}": float(np.quantile(dist, x)) for x in q["dist"]}
    P = wm_peaks(bp)
    X = {k: pre[k].to_numpy(float) for k in WM_INPUTS}
    y = pre["y"].to_numpy(float)
    cons, wsum = wm_learn(X, y, P)
    s_tr = wm_score(X, P, cons)
    Z = np.column_stack([pre[k].to_numpy(float) for k in WM_INPUTS])
    mu, sd = Z.mean(0), Z.std(0)
    res = pre["y"].to_numpy() != 0
    lr = LogisticRegression(C=1.0, max_iter=1000).fit(((Z - mu) / sd)[res], y[res] > 0)
    model = {"bp": bp, "peaks": {k: list(v) for k, v in P.items()}, "wm_cons": [None if not np.isfinite(c) else float(c) for c in cons],
             "wm_rules": int(np.isfinite(cons).sum()), "wm_cells_seen": int((wsum > 0).sum()),
             "logit": {"mean": mu.tolist(), "sd": sd.tolist(), "coef": lr.coef_[0].tolist(), "intercept": float(lr.intercept_[0])},
             "n_train": int(len(pre)), "n_train_resolved": int(res.sum())}
    model["wm_cons"] = [np.nan if c is None else c for c in model["wm_cons"]]
    s_lr = logit_score(X, model["logit"])
    model["fis2_thr"] = {str(x): float(np.quantile(np.abs(s_tr), x)) for x in Q_GRID}
    model["logit_thr"] = {str(x): float(np.quantile(np.abs(s_lr), x)) for x in Q_GRID}
    model["auc_train"] = {"FIS2": auc(s_tr, pre["y"].to_numpy()), "LOGIT": auc(s_lr, pre["y"].to_numpy())}
    print("breakpoints:", json.dumps(bp), flush=True)
    print(f"WM rules {model['wm_rules']} of {model['wm_cells_seen']} cells seen; train AUC {model['auc_train']}", flush=True)
    print("logit coef:", dict(zip(WM_INPUTS, np.round(lr.coef_[0], 4), strict=True)), flush=True)
    js = dict(model)
    js["wm_cons"] = [None if not np.isfinite(c) else c for c in model["wm_cons"]]
    (OUT / "fuzzy_model.json").write_text(json.dumps(js, indent=1))
    return bp, model


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    bp, model = fit()
    got = [g for g in pool_map(one, [(j, bp, model) for j in jobs_all()]) if g is not None]
    d = pd.concat([g[0] for g in got if len(g[0])], ignore_index=True)
    smp = pd.concat([g[1] for g in got if len(g[1])], ignore_index=True)
    d.to_pickle(OUT / "fuzzy_trades.pkl.gz")
    smp.to_pickle(OUT / "fuzzy_samples.pkl.gz")
    report(d, smp, model)


def report(d=None, smp=None, model=None):
    if d is None:
        d = pd.read_pickle(OUT / "fuzzy_trades.pkl.gz")
        smp = pd.read_pickle(OUT / "fuzzy_samples.pkl.gz")
        model = json.loads((OUT / "fuzzy_model.json").read_text())
    rng = np.random.default_rng(71)
    t = summarise(d, rng).round(4)
    pd.set_option("display.width", 320)
    pd.set_option("display.max_rows", 2000)
    pd.set_option("display.max_columns", 40)

    def cell(pool, source, sys_, thr, ex="E1"):
        r = t[(t["pool"] == pool) & (t["source"] == source) & (t["sys"] == sys_) & np.isclose(t["thr"], thr) & (t["exit"] == ex)]
        return r.iloc[0] if len(r) else None
    # AUC on held-out bars (2024 onward), real
    arows = []
    for pool, m in pools(smp):
        for source in ("real", "walk", "garch"):
            g = smp[m & (smp["source"] == source)]
            for half, hm in (("held-out", g["ts"] >= SPLIT), ("pre-2024", g["ts"] < SPLIT)):
                h = g[hm]
                arows.append(dict(pool=pool, source=source, half=half, n=int((h["y"] != 0).sum()),
                                  **{k: auc(h[k].to_numpy(float), h["y"].to_numpy()) for k in ("FIS1", "CRISP", "FIS2", "LOGIT")}))
    A = pd.DataFrame(arows).round(4)
    A.to_csv(OUT / "fuzzy_auc.csv", index=False)
    # Benjamini-Hochberg over every real secondary cell
    sec = t[(t["source"] == "real") & ~t["sys"].str.startswith("COIN")].copy()
    prim = (sec["pool"] == "MT5") & (sec["sys"] == "FIS1") & np.isclose(sec["thr"], FIS1_THR) & (sec["exit"] == "E1")
    sec = sec[~prim & sec["p"].notna() & (sec["n"] > 30)]
    sec["bh"] = bh(sec["p"].to_numpy(), RULE["report"]["bh_q"])

    def controls(r):
        c = cell(r["pool"], "real", f"COIN:{r['sys']}", r["thr"], r["exit"])
        w = cell(r["pool"], "walk", r["sys"], r["thr"], r["exit"])
        g = cell(r["pool"], "garch", r["sys"], r["thr"], r["exit"])
        return pd.Series(dict(coin=c["R"] if c is not None else np.nan, walk=w["R"] if w is not None else np.nan,
                              garch=g["R"] if g is not None else np.nan))
    sec = pd.concat([sec, sec.apply(controls, axis=1)], axis=1)
    sec["beats_controls"] = (sec["R"] > sec[["coin", "walk", "garch"]].max(axis=1))
    sec.to_csv(OUT / "fuzzy_secondary.csv", index=False)
    t.to_csv(OUT / "fuzzy_trade.csv", index=False)
    show = ["pool", "source", "sys", "thr", "exit", "n", "R", "lo", "hi", "p", "win", "R_before", "R_after", "R_1h", "R_4h", "R_1d",
            *[f"P{N}R" for N in NS]]
    main = t[t["sys"].isin(["FIS1", "CRISP", "COIN:FIS1"]) & np.isclose(t["thr"], FIS1_THR)]
    print("\n== FIS-1 at its frozen threshold, the crisp version and the coin twin, every pool\n")
    print(main[show].to_string(index=False))
    print("\n== FIS-2 and the logistic at their frozen quantile\n")
    print(t[t["sys"].isin(["FIS2", "LOGIT", "COIN:FIS2", "COIN:LOGIT"]) & np.isclose(t["thr"], Q_THR)][show].to_string(index=False))
    print("1/(N+1):", {N: round(1 / (N + 1), 3) for N in NS})
    print("\n== AUC (side that moves 1.5 ATR first within 24 bars)\n")
    print(A.to_string(index=False))
    print(f"\ntrain AUC: {model['auc_train']}; WM rules {model['wm_rules']}")
    print(f"\n== secondary: {len(sec)} real cells; BH at q={RULE['report']['bh_q']}: {int(sec['bh'].sum())} survive; "
          f"{int((sec['bh'] & sec['beats_controls']).sum())} also beat coin, walk and GARCH")
    print(sec.sort_values("p").head(25)[["pool", "sys", "thr", "exit", "n", "R", "lo", "hi", "p", "bh", "R_before", "R_after",
                                          "coin", "walk", "garch", "beats_controls"]].to_string(index=False))
    p, c = cell("MT5", "real", "FIS1", FIS1_THR), cell("MT5", "real", "COIN:FIS1", FIS1_THR)
    w, g, k = cell("MT5", "walk", "FIS1", FIS1_THR), cell("MT5", "garch", "FIS1", FIS1_THR), cell("MT5", "real", "CRISP", FIS1_THR)
    ok = (p["R"] > 0 and p["lo"] > 0 and p["R_before"] > 0 and p["R_after"] > 0 and p["R"] > c["R"] and p["R"] > w["R"]
          and p["R"] > g["R"] and p["R"] > k["R"])
    print(f"\nPRIMARY (FIS-1 |score|>={FIS1_THR}, MT5 non-Deriv, all timeframes, E1): R {p['R']:+.4f} [{p['lo']:+.4f}, {p['hi']:+.4f}] "
          f"n={int(p['n'])}; before {p['R_before']:+.4f} (n {int(p['n_before'])}), after {p['R_after']:+.4f}; coin {c['R']:+.4f}; "
          f"walk {w['R']:+.4f}; garch {g['R']:+.4f}; crisp {k['R']:+.4f} -> {'PASSES' if ok else 'fails'}")


# ---------------------------------------------------------------- plots

def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = pd.read_csv(OUT / "fuzzy_trade.csv")
    A = pd.read_csv(OUT / "fuzzy_auc.csv")
    smp = pd.read_pickle(OUT / "fuzzy_samples.pkl.gz")
    d = pd.read_pickle(OUT / "fuzzy_trades.pkl.gz")
    plist = ["MT5", "MT5:fx", "MT5:metal", "MT5:index", "MT5:energy", "MT5:crypto", "DERIV", "BINANCE"]
    # 1. P(N R): FIS-1 at the frozen threshold, E1, real vs walks vs coin vs crisp
    fig, axes = plt.subplots(2, 4, figsize=(24, 10), sharey=True)
    for ax, pool in zip(axes.flat, plist, strict=True):
        for (source, sys_), st, lab in ((("real", "FIS1"), "-o", "real"), (("walk", "FIS1"), "--s", "iid walk"),
                                        (("garch", "FIS1"), ":^", "GARCH"), (("real", "COIN:FIS1"), "-.x", "coin twin"),
                                        (("real", "CRISP"), "-d", "crisp rules")):
            r = t[(t["pool"] == pool) & (t["source"] == source) & (t["sys"] == sys_) & np.isclose(t["thr"], FIS1_THR) & (t["exit"] == "E1")]
            if len(r):
                r = r.iloc[0]
                ax.plot(NS, [r[f"P{N}R"] for N in NS], st, label=f"{lab}  R {r['R']:+.3f} (n {int(r['n'])})")
        ax.plot(NS, [1 / (N + 1) for N in NS], color="grey", lw=0.8, label="1/(N+1)")
        ax.set_xscale("log")
        ax.set_title(f"{pool}: FIS-1 |score|>={FIS1_THR}, 2-ATR trail", fontsize=10)
        ax.legend(fontsize=7)
        ax.set_xlabel("N (R)")
    for ax in axes[:, 0]:
        ax.set_ylabel("P(trade reaches N R)")
    fig.suptitle("Fuzzy trading (FIS-1): P(N R) real vs iid and GARCH walks, coin twin and crisp rules; mean R per trade in the legend")
    fig.tight_layout()
    fig.savefig(OUT / "fuzzy_pnr.png", dpi=75)
    plt.close(fig)
    # 2. score distribution and hit rate by score decile, MT5 non-Deriv
    m = (smp["venue"] == "mt5") & (smp["family"] != "deriv")
    fig, axes = plt.subplots(2, 4, figsize=(24, 9))
    for j, sys_ in enumerate(("FIS1", "CRISP", "FIS2", "LOGIT")):
        ax = axes[0, j]
        for source, col in (("real", "k"), ("walk", "C0"), ("garch", "C1")):
            x = smp.loc[m & (smp["source"] == source), sys_].dropna()
            ax.hist(x, bins=60, histtype="step", density=True, color=col, label=source)
        ax.set_title(f"{sys_} score distribution (MT5 non-Deriv)", fontsize=10)
        ax.set_yscale("log")
        ax.legend(fontsize=8)
        ax = axes[1, j]
        for source, col in (("real", "k"), ("walk", "C0"), ("garch", "C1")):
            g = smp[m & (smp["source"] == source) & (smp["y"] != 0)].dropna(subset=[sys_])
            if len(g) < 100:
                continue
            q = pd.qcut(g[sys_].rank(method="first"), 10, labels=False)
            hit = g.groupby(q)["y"].apply(lambda v: (v > 0).mean())
            ax.plot(np.arange(1, 11), hit.to_numpy(), "-o", color=col, label=source)
        ax.axhline(0.5, color="grey", lw=0.8)
        ax.set_title(f"{sys_}: P(up 1.5 ATR first) by score decile", fontsize=10)
        ax.set_xlabel("score decile (1 = most short)")
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "fuzzy_scores.png", dpi=75)
    plt.close(fig)
    # 3. AUC: FIS-2 vs logistic (and FIS-1, crisp), held out and pre-2024, by pool
    fig, axes = plt.subplots(1, 2, figsize=(20, 6), sharey=True)
    for ax, half in zip(axes, ("pre-2024", "held-out"), strict=True):
        g = A[(A["half"] == half) & A["pool"].isin(["MT5", "DERIV", "BINANCE"])]
        labels = [f"{r.pool}\n{r.source}" for r in g.itertuples()]
        x = np.arange(len(g))
        for i, k in enumerate(("FIS1", "CRISP", "FIS2", "LOGIT")):
            ax.bar(x + (i - 1.5) * 0.2, g[k] - 0.5, 0.2, bottom=0.5, label=k)
        ax.axhline(0.5, color="grey", lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_ylim(0.45, 0.56)
        ax.set_title(f"AUC, {half} bars (FIS-2 and the logistic fit on pre-2024 MT5 real)")
        ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "fuzzy_auc.png", dpi=75)
    plt.close(fig)
    # 4. gallery: six winners and six losers, real MT5 non-Deriv, FIS-1 at the frozen threshold
    g = d[(d["source"] == "real") & (d["venue"] == "mt5") & (d["family"] != "deriv") & (d["sys"] == "FIS1")
          & np.isclose(d["thr"], FIS1_THR) & (d["iv"] != "1d")]
    rng = np.random.default_rng(9)
    cache = {}
    for tag, sub in (("winners", g[g["E1"] > 1]), ("losers", g[g["E1"] <= -0.5])):
        pick = sub.iloc[rng.choice(len(sub), min(6, len(sub)), replace=False)]
        fig, axes = plt.subplots(2, 3, figsize=(22, 11))
        for ax, (_, r) in zip(axes.flat, pick.iterrows(), strict=False):
            if (r.sym, r.iv) not in cache:
                cache[r.sym, r.iv] = load("mt5", r.sym, r.iv)[0]
            df = cache[r.sym, r.iv]
            t0, xj = int(r.t), int(r.xj)
            i0, i1 = max(0, t0 - 40), min(len(df) - 1, xj + 15)
            w = df.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            ax.axvline(t0, color="purple", lw=1, ls=":")
            ax.plot([t0 + 1], [r.entry], "k>" if r.side > 0 else "k<", ms=10)
            ax.hlines(r.stop, t0 + 1, xj, colors="red", lw=1)
            ax.plot([xj], [r.xp], "bx", ms=10, mew=2)
            ax.text(0.01, 0.98, f"score {r.score:+.2f}\n{'long' if r.side > 0 else 'short'} rules: {r.fired or '-'}\n"
                    f"against: {r.fired_opp or '-'}", transform=ax.transAxes, va="top", fontsize=8,
                    bbox=dict(facecolor="white", alpha=0.8, lw=0))
            ax.set_title(f"{r.sym} {r.iv} {'long' if r.side > 0 else 'short'} {pd.Timestamp(r.ts, unit='s'):%Y-%m-%d %H:%M}"
                         f"  -> {r.E1:+.2f}R trail, {r.X2:+.2f}R at 2R", fontsize=9)
        fig.suptitle(f"FIS-1 trades ({tag}), MT5: purple dotted - the signal bar; arrow - entry at the next open; red - the "
                     "structural stop; blue x - the 2-ATR trail's exit. Rules: L1 pullback in uptrend, L2 trend momentum, "
                     "L3 bull candle at support, L4 compression breakout, L5 oversold reversal, L6-L9 against", fontsize=10)
        fig.tight_layout()
        fig.savefig(OUT / f"fuzzy_{tag}.png", dpi=75)
        plt.close(fig)
    print("plots written", flush=True)


def smoke():
    """One iid walk, breakpoints from the walk itself: the rule base fires, trades are built."""
    from mcfl import synth
    df = synth.walk(20000, sigma=1.0, seed=1, steps=WALK_STEPS)
    df["ts"] = 1_600_000_000 + 3600 * np.arange(len(df))
    X = inputs(df)
    q = RULE["inputs"]["breakpoint_quantiles"]
    bp = {k: {"b": float(np.nanquantile(np.abs(X[k]), q["signed_b"])), "c": float(np.nanquantile(np.abs(X[k]), q["signed_c"]))}
          for k in ("TR", "SLOPE", "MOM")}
    bp["VOL"] = {f"q{int(100 * x)}": float(np.nanquantile(X["VOL"], x)) for x in q["vol"]}
    dist = np.r_[X["DSL"], X["DSH"]]
    dist = dist[dist > 0]
    bp["DIST"] = {f"q{int(100 * x)}": float(np.quantile(dist, x)) for x in q["dist"]}
    s, Wu, _ = fis1(df, bp)
    sc, _, _ = fis1(df, bp, crisp=True)
    print("bp", bp)
    print("score quantiles", np.nanquantile(s, [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]).round(3))
    print("rule mean strength", {k: round(float(np.nanmean(v)), 3) for k, v in Wu.items()})
    for th in FIS1_GRID:
        print(th, "fuzzy entries", len(entries(s, th)[0]), "crisp", len(entries(sc, th)[0]))
    y = label(df, X["ATR"])
    print("label shares", {k: round(float((y == k).mean()), 3) for k in (-1, 0, 1)}, "AUC fis1", auc(s, y))
    tt, sd = entries(s, FIS1_THR)
    from mcfl.parse import flip
    arr = {1: tuple(df[k].to_numpy(float) for k in ("open", "high", "low", "close")),
           -1: tuple(flip(df)[k].to_numpy(float) for k in ("open", "high", "low", "close"))}
    R = [exits(*arr[int(x)], X["ATR"], int(t), 240) for t, x in zip(tt, sd, strict=True) if t >= 3 and t < len(df) - 1]
    R = [r for r in R if r]
    print("trades", len(R), "E1", np.mean([r["E1"] for r in R]).round(3), "X2", np.mean([r["X2"] for r in R]).round(3),
          "P4R", np.mean([r["mfe"] >= 4 for r in R]).round(3))
    P = wm_peaks(bp)
    yy = y.astype(float)
    ok = np.isfinite(X["TR"]) & np.isfinite(X["CFORCE"]) & np.isfinite(X["SWING"])
    cons, w = wm_learn({k: X[k][ok] for k in WM_INPUTS}, yy[ok], P)
    print("WM rules", int(np.isfinite(cons).sum()), "score q", np.nanquantile(wm_score(X, P, cons), [0.05, 0.5, 0.95]).round(3))


def main():
    {"run": run, "plot": plot, "report": report, "smoke": smoke}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
