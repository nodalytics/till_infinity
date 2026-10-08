"""Causal Fourier forecasting (abouttrading.substack.com, "Fourier methods reveal cycles - causal")
on FX majors, gold, bitcoin and Deriv Volatility / Jump indices at 15m, 1h, 4h and 1d.

## The method, as published

At each bar t, on the trailing window of N = 128 log closes only:
1. fit a straight line by least squares and subtract it;
2. take the real FFT of the residual, rank the non-zero frequencies by |X_k| / N and keep the
   K = 5 strongest;
3. rebuild those cosines with amplitude 2|X_k| / N and their phases, evaluated at local index N
   (one step past the window), and add the line extrapolated to N.
The forecast for the next log close minus the current one is the signal. The article reports no
result and suggests the method is better used on volatility, or as band-power features.

**One property is worth stating before measuring.** A DFT reconstruction is periodic with period
N, so its value at index N is its value at index 0: the "cycle" part of a one-step forecast is the
band-limited residual of the *oldest* bar in the window, 128 bars ago. Unless a cycle's period
divides N exactly, extrapolating it is a wrap-around, not a projection. The trend part,
`a N + b - x_t`, is a mix of momentum (the slope) and reversion to the window's line. Both
components are scored separately so the forecast's skill, if any, can be attributed.

## Three ideas tested, frozen before any number was read

1. **Direction (primary).** Signal = forecast - x_t at N = 128, K = 5. Test AUC of
   P(next return > 0) ranked by the signal; ablations: cycle part only, trend part only;
   sensitivity: N in {64, 256}, K in {3, 10}.
2. **Volatility.** The same forecaster applied to log(r^2 + c), forecasting the next bar's log
   squared return. Scored as AUC for "next bar is a top-10% |r|" (threshold from training):
   EWMA variance alone, + Fourier volatility forecast, and, for comparison, + the desk's simple
   hour-of-week profile (training means). On FX and gold this is where intraday seasonality lives.
3. **Band power.** Shares of the window's detrended power in period bands [2,4), [4,8), [8,16),
   [16,32), [32,128] bars and the log total, as features in a logistic model for direction and
   for the next-bar shock (over EWMA).

Instruments: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD, XAUUSD, BTCUSD, Volatility
75, 10, 10 (1s), 25, 25 (1s), 15, 15 (1s), Jump 25. The request named "hump 15", which is not a
Deriv index (Jump comes in 10, 25, 50, 75, 100); Volatility 15 and 15 (1s) are tested as the
nearest reading. Timeframes 15m, 1h, 4h, 1d from the broker's bars. FX and gold from 2005,
bitcoin from 2017. Cells under 600 bars are skipped.

Fit (logistic models, thresholds) on the first 60% by time, score on the last 40%. FX and gold
rows overlapping the 20:00-23:00 UTC rollover, and rows after a gap, are not scored (15m-4h).
Walks: two flip walks (real bars, random sign) and one GARCH-t walk per cell. For direction the
flip walk is the control; for volatility it is not (it keeps the real volatility path), so the
GARCH walk is, and any skill the flip walk shares is real volatility information.

**Pass rules.** Direction: Benjamini-Hochberg at q = 0.05 over the primary cells (instrument x
timeframe), real AUC above 0.5 and at least 0.005 above the mean of its walks. Volatility: the
Fourier forecast adds at least 0.005 AUC over EWMA on the real bars, and more than it adds on the
GARCH walk. Trades: confident decile (threshold from training), held one bar, net of one quoted
spread; tail P(>= 4R), P(>= 10R) before a one-sigma stop against 1/(N+1) and the walks (not for
Jump 25, whose stops gap and cannot be filled from bars).

Run on the lab (BARS holds `seqlab/`):
  BARS=<bars> OUT=<out>.json python research/harness/statespace_fourier.py
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
import statespace as ss
import statespace_fx as sfx

OUT = Path(os.environ.get("OUT", "statespace_fourier.json"))
FX = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
OTHER = ["XAUUSD", "BTCUSD", "Volatility_75_Index", "Volatility_10_Index", "Volatility_10_1s_Index",
         "Volatility_25_Index", "Volatility_25_1s_Index", "Volatility_15_Index", "Volatility_15_1s_Index",
         "Jump_25_Index"]
INSTRUMENTS = FX + OTHER
ROLLOVER = set(FX) | {"XAUUSD"}
START = {**{s: "2005-01-01" for s in FX + ["XAUUSD"]}, "BTCUSD": "2017-01-01"}
TFS = ["15m", "1h", "4h", "1d"]
KINDS = [("real", 0), ("flip", 1), ("flip", 2), ("garch", 3)]
N0, K0 = 128, 5
BANDS = [(2, 4), (4, 8), (8, 16), (16, 32), (32, 129)]


def load(sym, tf):
    z = np.load(ss.BARS / "seqlab" / f"{sym}.{tf}.npz")
    df = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close")})
    df = df.drop_duplicates("time").sort_values("time")
    if sym in START:
        df = df[df.time >= pd.Timestamp(START[sym]).timestamp()]
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)].reset_index(drop=True)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


# Bitcoin's bars quote three decimals, which puts its spread field at $2.4 (0.3 bps); `lagging.md`
# measured the broker's BTC spread at 2.39 bps. The larger, measured figure is used.
COST_OVERRIDE = {"BTCUSD": 2.39e-4}


def cost(sym):
    """Median quoted spread on the 15m bars as a share of price; the point from the price grid."""
    if sym in COST_OVERRIDE:
        return COST_OVERRIDE[sym]
    z = np.load(ss.BARS / "seqlab" / f"{sym}.15m.npz")
    c = z["close"][-5000:]
    # rtol must be 0: allclose's default relative tolerance lets 49275.93 * 10 pass as an integer,
    # which made the point 10-100x too large on every instrument priced in the thousands
    d = next((d for d in range(0, 7) if np.allclose(c * 10 ** d, np.round(c * 10 ** d), rtol=0, atol=1e-4)), 6)
    return float(np.median(z["spread"][-20000:] * 10.0 ** -d / z["close"][-20000:]))


def fourier(x, N, K):
    """Causal one-step Fourier forecast at every t >= N-1: (full, cycle, trend) minus x_t,
    plus band shares and log power of the detrended window. NaN before the first full window."""
    n = len(x)
    W = sliding_window_view(x, N)  # row j covers x[j .. j+N-1], so it ends at t = j + N - 1
    idx = np.arange(N, dtype=float)
    im, iv = idx.mean(), ((idx - idx.mean()) ** 2).sum()
    wm = W.mean(axis=1)
    a = ((W - wm[:, None]) * (idx - im)).sum(axis=1) / iv
    b = wm - a * im
    R = W - (a[:, None] * idx + b[:, None])
    X = np.fft.rfft(R, axis=1)
    amp = np.abs(X) / N
    amp[:, 0] = -np.inf
    top = np.argpartition(-amp, K, axis=1)[:, :K]
    rows = np.arange(len(W))[:, None]
    Xk = X[rows, top]
    freq = top / N
    cyc = (2 * np.abs(Xk) / N * np.cos(2 * np.pi * freq * N + np.angle(Xk))).sum(axis=1)
    trend = a * N + b - W[:, -1]
    power = np.abs(X[:, 1:]) ** 2
    period = N / np.arange(1, X.shape[1])
    tot = power.sum(axis=1) + 1e-300
    bands = np.column_stack([power[:, (period >= lo) & (period < hi)].sum(axis=1) / tot for lo, hi in BANDS]
                            + [np.log(tot)])

    def pad(v):
        out = np.full((n,) + v.shape[1:], np.nan)
        out[N - 1:] = v
        return out

    return pad(cyc + trend), pad(cyc), pad(trend), pad(bands)


def fit_auc(X, y, tr, te):
    X = X if X.ndim == 2 else X[:, None]
    good = np.isfinite(X).all(axis=1) & np.isfinite(y)
    if (good & tr).sum() < 200 or (good & te).sum() < 200 or len(np.unique(y[good & tr])) < 2:
        return None
    m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)).fit(X[good & tr], y[good & tr])
    return ss.auc(y[good & te], m.predict_proba(X[good & te])[:, 1])


def job(args):
    sym, tf, kind, seed = args
    df = load(sym, tf)
    if len(df) < 600:
        return dict(sym=sym, tf=tf, kind=kind, seed=seed, skipped=f"{len(df)} bars")
    if kind == "flip":
        df = ss.flip_walk(df, np.random.default_rng(3000 + seed))
    elif kind == "garch":
        df = ss.garch_walk(df, np.random.default_rng(3000 + seed))
    n = len(df)
    dur = ss.MIN[tf] * 60
    t = df.time.to_numpy()
    x = np.log(df.close.to_numpy())
    r = np.diff(x, prepend=np.nan)
    nxt = np.r_[r[1:], np.nan]
    s = np.sqrt(pd.Series(r ** 2).ewm(alpha=0.06, min_periods=50).mean().to_numpy())  # known at close t
    contiguous = np.r_[np.diff(t) <= 1.5 * dur, False]
    roll = sfx.overlaps_roll(t, dur) if (sym in ROLLOVER and tf != "1d") else np.zeros(n, bool)
    clean = contiguous & ~roll & ~np.r_[roll[1:], True]
    split = int(n * ss.TRAIN)
    base = np.isfinite(nxt) & clean
    tr, te = base & (np.arange(n) < split), base & (np.arange(n) >= split)
    up = (nxt > 0).astype(float)
    c = cost(sym)
    res = dict(sym=sym, tf=tf, kind=kind, seed=seed, n=n, n_test=int(te.sum()),
               test_from=str(pd.to_datetime(t[split], unit="s").date()), cost_bps=1e4 * c, direction={})

    # 1. direction
    full0 = None
    for N, K, tag in ((N0, K0, "main"), (64, K0, "N64"), (256, K0, "N256"), (N0, 3, "K3"), (N0, 10, "K10")):
        if n < 3 * N:
            continue
        full, cyc, trend, bands = fourier(x, N, K)
        row = {}
        for part, sig in (("full", full), ("cycle", cyc), ("trend", trend)):
            k = te & np.isfinite(sig)
            if k.sum() < 200:
                continue
            row[part] = dict(auc=ss.auc(up[k].astype(int), sig[k]))
            if tag == "main" and part == "full" and kind == "real":
                lo, hi, pv = ss.boot_auc(up[k].astype(int), sig[k], ss.DAYBARS[tf], reps=400)
                row[part].update(lo=lo, hi=hi, p=pv)
        if tag == "main":
            full0, bands0 = full, bands
            row["bands"] = fit_auc(bands, up, tr, te)
        res["direction"][tag] = row

    # trade on the main forecast: confident decile by |signal| / sigma
    z = np.abs(full0) / s
    ok_tr = tr & np.isfinite(z)
    if ok_tr.sum() > 200:
        thr = np.nanquantile(z[ok_tr], 0.9)
        k = te & np.isfinite(z) & (z >= thr)
        g = np.sign(full0[k]) * nxt[k]
        res["trade"] = dict(n=int(k.sum()), gross_bps=1e4 * float(np.mean(g)), net_bps=1e4 * float(np.mean(g - c)),
                            t=float(np.mean(g) / (np.std(g) / np.sqrt(len(g)))) if len(g) > 2 else None)
        if sym != "Jump_25_Index" and k.sum() >= 30:
            res["tail"] = ss.tail(df, np.where(k)[0], np.sign(full0[k]), s[k], c)

    # 2. volatility: Fourier on log r^2, against EWMA and the hour-of-week profile
    r2 = r ** 2
    cfloor = 1e-4 * np.nanmedian(r2[np.isfinite(r2)])
    lv = np.log(np.where(np.isfinite(r2), r2, np.nan) + cfloor)
    lv_f = np.where(np.isfinite(lv), lv, np.nanmedian(lv))
    vfull, _, _, _ = fourier(lv_f, N0, K0)
    vfore = lv_f + vfull  # forecast of the next log squared return
    absn = np.abs(nxt)
    thr_big = np.nanquantile(absn[tr], 0.9)
    big = (absn >= thr_big).astype(float)
    big[~np.isfinite(absn)] = np.nan
    ew = np.log(s ** 2)
    how = ((t // 3600) % (24 * 7)) if tf in ("15m", "1h") else ((t // 3600) % (24 * 7)) // 4
    nxt_how = np.r_[how[1:], how[-1]]
    prof = pd.Series(lv[tr]).groupby(nxt_how[tr]).mean()
    hw = prof.reindex(nxt_how).to_numpy()
    res["vol"] = dict(ewma=fit_auc(ew, big, tr, te),
                      ewma_fourier=fit_auc(np.column_stack([ew, vfore]), big, tr, te),
                      ewma_profile=fit_auc(np.column_stack([ew, hw]), big, tr, te),
                      ewma_profile_fourier=fit_auc(np.column_stack([ew, hw, vfore]), big, tr, te),
                      ewma_bands=fit_auc(np.column_stack([ew, bands0]), big, tr, te))
    return res


if __name__ == "__main__":
    jobs = [(s, tf, k, sd) for s in INSTRUMENTS for tf in TFS for k, sd in KINDS]
    out = []
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", "48"))) as ex:
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
