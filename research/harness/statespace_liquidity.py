"""Liquidity from candles: do candle-based liquidity proxies help the zone method, the state
filters' direction, or the next bar's size? EURUSD and V75 at 15m, 1h, 4h, 1d, with walks.

The trader's method (`research/papers/state-space.md`) names "how large is the liquidity zone" as
an input. `statespace.py` follows `zone-fill.md` and sizes a zone by how many recent extremes
cluster at it. Here liquidity is measured the ways a candle allows.

Bar proxies, all from bars already closed (rolling 20 bars unless stated):
  amihud    log mean(|r| / volume)                              Amihud (2002) illiquidity
  cs        Corwin-Schultz (2012) spread from two bars' high-low   price only
  ar        Abdi-Ranaldo (2017) spread from close, high, low      price only
  roll      Roll (1984) spread, 2 sqrt(-cov(dp_t, dp_t-1)), 50 bars   price only
  kyle      price impact: slope of r on signed volume, 50 bars; volume signed by where the
            close sits in its bar (bulk classification)
  volz      log volume minus its 500-bar mean
  rpv       log mean(range / volume)
Zone liquidity:
  zvol      volume of the last 50 bars whose wick reached within a quarter-move of the level,
            over the mean bar volume - the volume resting at the zone
  pvol      volume of the bar that made the level, over the mean bar volume

**Volatility 75's volume is a tick count at a fixed rate** (450 per 15m bar, 1,800 an hour), so
every volume proxy is constant there; only cs, ar and roll mean anything on V75. Bars with a
volume under 10 (EURUSD's early 4h and 1d history) are treated as missing volume.

Tests, fit on the first 60% by time and scored on the last 40%, on real bars, the flip walk
(each bar mirrored about the previous close at random, real volume kept with its bar) and a
GARCH-t walk carrying the real volume sequence:
  1. zone fill and the zone trade's net win: the `zone-fill.md` inputs, then + liquidity
  2. direction: liquidity alone; the HMM and Kalman state alone; state + liquidity
  3. risk: is the next bar large (top decile of |r| / sigma)? EWMA alone, then + liquidity
  4. multi-timeframe: the higher frame's liquidity (from closed higher bars) added to 2 and 3

Run on the lab, with the same BARS as `statespace.py`:
  BARS=<bars> OUT=<out>.json python research/harness/statespace_liquidity.py
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
import statespace as ss
from bars import long_R

OUT = Path(os.environ.get("OUT", "statespace_liquidity.json"))
BAR = ["amihud", "cs", "ar", "roll", "kyle", "volz", "rpv"]
PRICE_ONLY = ["cs", "ar", "roll"]
ZONE = ["zvol", "pvol"]


def load(sym, tf):
    p = ss.BARS / ss.SOURCES[(sym, tf)]
    if p.suffix == ".npz":
        z = np.load(p)
        df = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close", "volume")})
    else:
        df = pd.read_csv(p).rename(columns={"ts": "time"})[["time", "open", "high", "low", "close", "volume"]]
    df = df.drop_duplicates("time").sort_values("time")
    df = df[df.time >= ss.START.get(sym, 0)]
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)].reset_index(drop=True)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    df["volume"] = df.volume.where(df.volume >= 10)
    return df


def walk(df, kind, seed):
    rng = np.random.default_rng(1000 + seed)
    w = ss.flip_walk(df, rng) if kind == "flip" else ss.garch_walk(df, rng)
    w["volume"] = df.volume.to_numpy()
    return w


def proxies(df):
    """Bar liquidity proxies, each known at the close of bar t from bars <= t only."""
    lh, ll, lc = np.log(df.high), np.log(df.low), np.log(df.close)
    v = df.volume
    r = lc.diff()
    out = pd.DataFrame(index=df.index)
    out["amihud"] = np.log((r.abs() / v).rolling(20, min_periods=10).mean() + 1e-18)
    # Corwin-Schultz on bars t-1, t
    beta = (lh - ll) ** 2 + (lh.shift(1) - ll.shift(1)) ** 2
    gamma = (np.maximum(lh, lh.shift(1)) - np.minimum(ll, ll.shift(1))) ** 2
    k = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    cs = (2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))).clip(lower=0)
    out["cs"] = cs.rolling(20, min_periods=10).mean()
    # Abdi-Ranaldo, causal form: close of t-1 against the mids of t-1 and t
    eta = (lh + ll) / 2
    s2 = 4 * (lc.shift(1) - eta.shift(1)) * (lc.shift(1) - eta)
    out["ar"] = np.sqrt(s2.rolling(20, min_periods=10).mean().clip(lower=0))
    dp = lc.diff()
    cov = dp.rolling(50, min_periods=25).cov(dp.shift(1))
    out["roll"] = 2 * np.sqrt((-cov).clip(lower=0))
    span = (df.high - df.low).where(df.high > df.low)
    loc = ((df.close - (df.high + df.low) / 2) / span).fillna(0)
    sv = 2 * loc * np.sqrt(v)
    out["kyle"] = r.rolling(50, min_periods=25).cov(sv) / sv.rolling(50, min_periods=25).var()
    lv = np.log(v)
    out["volz"] = lv - lv.rolling(500, min_periods=100).mean()
    out["rpv"] = np.log((((df.high - df.low) / df.close) / v).rolling(20, min_periods=10).mean() + 1e-18)
    return out


def zone_liq(df, z):
    """Volume resting at each zone row's level, and on the bar that made it."""
    hi_, lo_ = np.log(df.high), np.log(df.low)
    lc = np.log(df.close)
    base = lc.diff().abs().rolling(500, min_periods=250).mean()
    vol = df.volume
    mv = vol.rolling(500, min_periods=100).mean()
    cols = {}
    for side in (1, -1):
        src = hi_ if side > 0 else lo_
        level = src.shift(1).rolling(ss.LOOK).max() if side > 0 else src.shift(1).rolling(ss.LOOK).min()
        band = 0.25 * base
        near = sum((((src.shift(k) >= level - band) if side > 0 else (src.shift(k) <= level + band))
                    .astype(float) * vol.shift(k).fillna(0)) for k in range(1, ss.LOOK + 1))
        made = sum(((src.shift(k) == level).astype(float) * vol.shift(k).fillna(0)) for k in range(1, ss.LOOK + 1))
        cols[side] = (near / mv, made / mv)
    t, s = z.t.to_numpy(), z.side.to_numpy()
    zvol = np.where(s > 0, cols[1][0].to_numpy()[t], cols[-1][0].to_numpy()[t])
    pvol = np.where(s > 0, cols[1][1].to_numpy()[t], cols[-1][1].to_numpy()[t])
    return zvol, pvol


def fit_auc(X, y, tr, te):
    good = np.isfinite(X).all(axis=1)
    if (good & tr).sum() < 200 or (good & te).sum() < 200 or len(np.unique(y[good & tr])) < 2:
        return None
    m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)).fit(X[good & tr], y[good & tr])
    p = m.predict_proba(X[good & te])[:, 1]
    return ss.auc(y[good & te], p)


def usable(P, cols):
    """Drop proxies that are constant or mostly missing on this series (V75's volume ones)."""
    out = []
    for c in cols:
        x = P[c].to_numpy(float)
        x = x[np.isfinite(x)]
        if len(x) > 0.5 * len(P) and np.nanstd(x) > 1e-12:
            out.append(c)
    return out


def zone_part(df, P, cost, use_bar, use_zone):
    z = ss.zone_rows(df)
    idx, Pb = ss.paths(df, z.t.to_numpy(), ss.ZH)
    z = z[z.t.isin(idx)].reset_index(drop=True)
    idx, Pb = ss.paths(df, z.t.to_numpy(), ss.ZH)
    Pb = Pb * z.side.to_numpy()
    reach = z.dist.to_numpy() * z.base.to_numpy()
    z["filled"] = (np.nanmax(Pb.h, 1) >= reach).astype(float)
    R, _ = long_R(Pb, reach, reach)
    z["win"] = ((R - cost / reach) > 0).astype(float)
    z["netR"] = R - cost / reach
    zv, pv = zone_liq(df, z)
    z["zvol"], z["pvol"] = np.log1p(zv), np.log1p(pv)
    for c in use_bar:
        z[c] = P[c].to_numpy()[z.t.to_numpy()]
    base_cols = ["dist", "size", "speed", "velocity", "efficiency"]
    z = z.replace([np.inf, -np.inf], np.nan).dropna(subset=base_cols)
    z["dist"] = np.log(z.dist)
    z["size"] = np.log1p(z["size"])
    te = (z.t >= z.t.quantile(ss.TRAIN)).to_numpy()
    tr = ~te
    out = {}
    for target in ("filled", "win"):
        y = z[target].to_numpy()
        row = {"method": fit_auc(z[base_cols].to_numpy(float), y, tr, te)}
        if use_zone:
            row["+zone_liq"] = fit_auc(z[base_cols + use_zone].to_numpy(float), y, tr, te)
        if use_bar:
            row["+bar_liq"] = fit_auc(z[base_cols + use_bar].to_numpy(float), y, tr, te)
            row["+all_liq"] = fit_auc(z[base_cols + use_bar + use_zone].to_numpy(float), y, tr, te)
        out[target] = row
    # trade the top decile of the profit model with all liquidity inputs, net R
    cols = base_cols + use_bar + use_zone
    good = np.isfinite(z[cols].to_numpy(float)).all(axis=1)
    if (good & tr).sum() > 500:
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)).fit(
            z[cols].to_numpy(float)[good & tr], z.win.to_numpy()[good & tr])
        k = good & te
        p = m.predict_proba(z[cols].to_numpy(float)[k])[:, 1]
        thr = np.quantile(p, 0.9)
        sel = z[k][p >= thr]
        out["top_decile_net_R"] = float(sel.netR.mean())
        out["top_decile_n"] = int(len(sel))
    return out


def direction_and_risk(df, P, use_bar, tf, htfP=None, use_htf=()):
    n = len(df)
    tr_end = int(n * ss.TRAIN)
    r, s, Y = ss.observations(df, "close", tr_end)
    ok = np.isfinite(Y).all(axis=1)
    first = int(np.argmax(ok))
    Yy = np.ascontiguousarray(np.where(np.isfinite(Y), Y, 0.0)[first:])
    # the two fast filters: their forecasts for bar t+1 made at the close of t
    states = {}
    k = ss.fit_kalman(Yy[:tr_end - first])
    p, l_ = np.empty(len(Yy)), np.empty(len(Yy))
    ss.kalman_run(Yy, k["phi"], k["q"], k["rv"], k["b"], k["a"], p, l_)
    states["kalman"] = np.r_[np.full(first, np.nan), p]
    A, mu, sd = ss.fit_hmm(Yy[:tr_end - first][-40000:])
    p, l_, st = np.empty(len(Yy)), np.empty(len(Yy)), np.empty(len(Yy), np.int64)
    ss.hmm_run(Yy, A, mu, sd, p, l_, st)
    states["hmm"] = np.r_[np.full(first, np.nan), p]
    # align: features at the close of t predict bar t+1; the filters' p[t+1] is already that forecast
    up = (np.r_[r[1:], np.nan] > 0).astype(float)
    nxt = np.r_[r[1:], np.nan]
    big_lab = np.abs(nxt) / np.r_[s[1:], np.nan]  # next return over the sigma known at t
    valid = np.isfinite(nxt) & np.isfinite(big_lab)
    tr = valid & (np.arange(n) < tr_end)
    te = valid & (np.arange(n) >= tr_end)
    thr = np.nanquantile(big_lab[tr], 0.9)
    big = (big_lab >= thr).astype(float)
    Xb = P[use_bar].to_numpy(float) if use_bar else np.empty((n, 0))
    if htfP is not None and use_htf:
        Xh = htfP[list(use_htf)].to_numpy(float)
    else:
        Xh = np.empty((n, 0))
    out = {"direction": {}, "risk": {}}
    if use_bar:
        out["direction"]["liquidity"] = fit_auc(Xb, up, tr, te)
    for name, sp in states.items():
        f = np.r_[sp[1:], np.nan][:, None]  # the filter's forecast for t+1, made with data <= t
        out["direction"][name] = fit_auc(f, up, tr, te)
        if use_bar:
            out["direction"][f"{name}+liquidity"] = fit_auc(np.column_stack([f, Xb]), up, tr, te)
        if Xh.shape[1]:
            out["direction"][f"{name}+liquidity+htf_liq"] = fit_auc(np.column_stack([f, Xb, Xh]), up, tr, te)
    # risk: EWMA sigma level and the last |y| are the baseline
    ew = np.log(s)[:, None]
    lasty = np.abs(Y[:, :1])
    base_X = np.column_stack([ew, lasty])
    out["risk"]["ewma"] = fit_auc(base_X, big, tr, te)
    if use_bar:
        out["risk"]["ewma+liquidity"] = fit_auc(np.column_stack([base_X, Xb]), big, tr, te)
    if Xh.shape[1]:
        out["risk"]["ewma+liquidity+htf_liq"] = fit_auc(np.column_stack([base_X, Xb, Xh]), big, tr, te)
    return out


def htf_proxies(df, lt, ht, cols):
    # `aggregate` drops volume: rebuild it by summing lower-bar volume per higher span
    span = ss.MIN[ht] * 60
    g = (df.time // span) * span
    vol = df.volume.groupby(g).sum(min_count=1)
    hdf = ss.aggregate(df, lt, ht)
    hdf["volume"] = vol.reindex(hdf.time).to_numpy()
    hdf["volume"] = hdf.volume.where(hdf.volume >= 10)
    hp = proxies(hdf)[cols]
    close_h = (hdf.time + ss.MIN[ht] * 60).to_numpy()
    close_l = (df.time + ss.MIN[lt] * 60).to_numpy()
    j = np.searchsorted(close_h, close_l, side="right") - 1
    out = pd.DataFrame(np.nan, index=df.index, columns=[f"h_{c}" for c in cols])
    ok = j >= 0
    out.loc[ok, :] = hp.to_numpy()[j[ok]]
    return out


def job(args):
    sym, tf, kind, seed = args
    df = load(sym, tf)
    if kind != "real":
        df = walk(df, kind, seed)
    cost = ss.spread_rel(sym)
    P = proxies(df)
    use_bar = usable(P, BAR)
    has_vol = df.volume.notna().mean() > 0.5 and df.volume.std() > 1e-9 and df.volume.nunique() > 20
    use_zone = ZONE if has_vol else []
    res = dict(sym=sym, tf=tf, kind=kind, proxies=use_bar, zone_liq=use_zone)
    res["zone"] = zone_part(df, P, cost, use_bar, use_zone)
    res["base"] = direction_and_risk(df, P, use_bar, tf)
    res["mtf"] = {}
    for lt, ht in ss.MTF:
        if lt != tf:
            continue
        H = htf_proxies(df, lt, ht, use_bar)
        if H.notna().all(axis=1).sum() < 1000:
            continue
        res["mtf"][ht] = direction_and_risk(df, P, use_bar, tf, H, list(H.columns))
    # the proxies' correlations with each other and with sigma, real bars only, for the write-up
    if kind == "real":
        C = P[use_bar].assign(log_sigma=np.log(ss.observations(df)[1])).corr(method="spearman")
        res["corr"] = C.round(2).to_dict()
    return res


if __name__ == "__main__":
    jobs = [(s, tf, k, sd) for (s, tf) in ss.SOURCES for k, sd in (("real", 0), ("flip", 1), ("garch", 2))]
    out = []
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", "24"))) as ex:
        futs = {ex.submit(job, j): j for j in jobs}
        for f in futs:
            try:
                out.append(f.result())
                print("done", futs[f], flush=True)
            except Exception as e:
                print("FAILED", futs[f], repr(e), flush=True)
            OUT.write_text(json.dumps(ss.clean(out), indent=1))
