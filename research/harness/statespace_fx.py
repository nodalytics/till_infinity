"""Confirmation: does the EURUSD short-term reversal in `state-space-filters.md` hold on the other
FX majors?

The finding being confirmed: 13 of 96 cells passed Benjamini-Hochberg, all EURUSD 15m-4h, AUC
0.510-0.523 against walks at 0.49-0.51 - a Kalman AR(1) drift with phi = -0.02 to -0.04 (the next
bar partly undoes this one), sharpened on 1h and 4h by where the close sits in its candle. It was
found on EURUSD, so EURUSD cannot confirm it. This test is frozen before any number is read.

## Frozen rules

Pairs: GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD (EURUSD re-run through the same pipeline
as the reference, not counted).
Timeframes: 15m and 1h from the broker's bars (2024-09 and 2018-09 onward, 50,000 each); 4h and
1d aggregated from the 1h bars in UTC.
Models, exactly the three forms that passed: kalman on closes, kalman on the full candle, hmm on
the full candle (`statespace.py`, unchanged). Fit on the first 60% by time, score on the last 40%.
Walks: two flip walks (real bars mirrored about the previous close with a random sign) and one
GARCH-t walk, per cell.

**The rollover is excluded before scoring.** Bar times are UTC (the week opens Sunday 21:00 or
22:00; the 15m spread is 2 points every hour except 21:00, where it is 8). A row - features at the
close of bar t, forecast for bar t+1 - is scored only if neither bar t nor bar t+1 overlaps
20:00-23:00 UTC and bar t+1 follows bar t without a gap (weekends, holidays). Daily bars contain
the rollover by construction, so 1d is reported but scored unmasked, with that caveat. The
unmasked AUC is reported beside the masked one for every cell, so the rollover's share is visible.

Primary statistic: test AUC of P(next return > 0), block-bootstrap one-sided p for AUC <= 0.5
(whole days resampled; weeks on 1d).
**A cell passes** if it survives Benjamini-Hochberg at q = 0.05 over all 72 cells (6 pairs x 4
timeframes x 3 models) **and** beats the mean of its three walks by at least 0.005.
**The reversal is confirmed** if at least four of the six pairs have a passing cell at 15m or 1h
(where EURUSD passed with every model), with the sign the same as EURUSD's (AUC above 0.5 from a
negative phi).
**It pays** only if the confident decile (threshold from training, one round trip per trade, held
one bar) is net positive at each pair's quoted spread, and is reported again at 1 pip round trip,
a standard retail account.

Run on the lab (BARS holds `pipeline_bars/`):
  BARS=<bars> OUT=<out>.json python research/harness/statespace_fx.py
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import statespace as ss

OUT = Path(os.environ.get("OUT", "statespace_fx.json"))
PAIRS = ["GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURUSD"]
TFS = ["15m", "1h", "4h", "1d"]
KINDS = [("real", 0), ("flip", 1), ("flip", 2), ("garch", 3)]
MODELS = [("kalman", "close"), ("kalman", "ohlc"), ("hmm", "ohlc")]
ROLL = (20, 23)  # UTC hours [20:00, 23:00)


def load(pair, tf):
    src = "15m" if tf == "15m" else "1h"
    z = np.load(ss.BARS / "pipeline_bars" / f"{pair}.{src}.npz")
    df = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close")})
    df = df.drop_duplicates("time").sort_values("time")
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)].reset_index(drop=True)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    if tf in ("4h", "1d"):
        df = ss.aggregate(df, "1h", tf)[["time", "open", "high", "low", "close"]].reset_index(drop=True)
    return df


def costs(pair):
    z = np.load(ss.BARS / "pipeline_bars" / f"{pair}.15m.npz")
    point, pip = (1e-3, 1e-2) if pair.endswith("JPY") else (1e-5, 1e-4)
    quoted = float(np.median(z["spread"] * point / z["close"]))
    retail = float(pip / np.median(z["close"]))
    return quoted, retail


def overlaps_roll(start, dur):
    """Does [start, start + dur) overlap ROLL on its UTC day (or the next, for long bars)?"""
    s = pd.to_datetime(start, unit="s")
    day = s.normalize()
    out = np.zeros(len(s), bool)
    for d in (pd.Timedelta(0), pd.Timedelta(days=1), -pd.Timedelta(days=1)):
        a = (day + d + pd.Timedelta(hours=ROLL[0])).astype("int64") // 10**9
        b = (day + d + pd.Timedelta(hours=ROLL[1])).astype("int64") // 10**9
        out |= (start < b.to_numpy()) & (start + dur > a.to_numpy())
    return out


def forecasts(df):
    n = len(df)
    tr_end = int(n * ss.TRAIN)
    out = {}
    for model, obs in MODELS:
        r, s, Y = ss.observations(df, obs, tr_end)
        ok = np.isfinite(Y).all(axis=1)
        first = int(np.argmax(ok))
        Yy = np.ascontiguousarray(np.where(np.isfinite(Y), Y, 0.0)[first:])
        p = np.empty(len(Yy))
        l_ = np.empty(len(Yy))
        if model == "kalman":
            k = ss.fit_kalman(Yy[:tr_end - first])
            ss.kalman_run(Yy, k["phi"], k["q"], k["rv"], k["b"], k["a"], p, l_)
            info = {"phi": k["phi"]}
        else:
            A, mu, sd = ss.fit_hmm(Yy[:tr_end - first][-40000:])
            st = np.empty(len(Yy), np.int64)
            ss.hmm_run(Yy, A, mu, sd, p, l_, st)
            info = {"mu": mu[:, 0].tolist()}
        full = np.r_[np.full(first, np.nan), p]
        # p[t] is the forecast for bar t made through t-1; as a feature at the close of t for t+1:
        out[f"{model}_{obs}"] = (np.r_[full[1:], np.nan], info)
    return out


def job(args):
    pair, tf, kind, seed = args
    df = load(pair, tf)
    if kind == "flip":
        df = ss.flip_walk(df, np.random.default_rng(2000 + seed))
    elif kind == "garch":
        df = ss.garch_walk(df, np.random.default_rng(2000 + seed))
    n = len(df)
    dur = ss.MIN[tf] * 60
    t = df.time.to_numpy()
    r = np.diff(np.log(df.close.to_numpy()), prepend=np.nan)
    nxt = np.r_[r[1:], np.nan]
    contiguous = np.r_[np.diff(t) <= 1.5 * dur, False]
    roll = overlaps_roll(t, dur) if tf != "1d" else np.zeros(n, bool)
    clean = contiguous & ~roll & ~np.r_[roll[1:], True]
    te = (np.arange(n) >= int(n * ss.TRAIN)) & np.isfinite(nxt)
    tr = (np.arange(n) < int(n * ss.TRAIN)) & np.isfinite(nxt)
    quoted, retail = costs(pair)
    res = dict(pair=pair, tf=tf, kind=kind, seed=seed, n=n, n_test=int((te & clean).sum()),
               test_from=str(pd.to_datetime(t[int(n * ss.TRAIN)], unit="s").date()), models={})
    for name, (p, info) in forecasts(df).items():
        row = dict(info=info)
        for label, mask in (("masked", te & clean), ("unmasked", te)):
            k = mask & np.isfinite(p)
            up = (nxt[k] > 0).astype(int)
            row[label] = dict(auc=ss.auc(up, p[k]), n=int(k.sum()))
            if label == "masked" and kind == "real":
                lo, hi, pv = ss.boot_auc(up, p[k], ss.DAYBARS[tf], reps=400)
                row[label].update(lo=lo, hi=hi, p=pv)
        # the trade, masked rows only: always-in gross, and the confident decile net
        k = te & clean & np.isfinite(p)
        g = np.sign(p[k] - 0.5) * nxt[k]
        thr = np.nanquantile(np.abs(p[tr & clean & np.isfinite(p)] - 0.5), 0.9)
        c = k & (np.abs(p - 0.5) >= thr)
        gc = np.sign(p[c] - 0.5) * nxt[c]
        row["trade"] = dict(gross_bps=1e4 * float(np.mean(g)), conf_n=int(c.sum()),
                            conf_gross_bps=1e4 * float(np.mean(gc)) if c.sum() else None,
                            conf_net_quoted_bps=1e4 * float(np.mean(gc - quoted)) if c.sum() else None,
                            conf_net_retail_bps=1e4 * float(np.mean(gc - retail)) if c.sum() else None,
                            conf_t=float(np.mean(gc) / (np.std(gc) / np.sqrt(c.sum()))) if c.sum() > 2 else None)
        res["models"][name] = row
    res["cost_bps"] = dict(quoted=1e4 * quoted, retail=1e4 * retail)
    return res


if __name__ == "__main__":
    jobs = [(p, tf, k, s) for p in PAIRS for tf in TFS for k, s in KINDS]
    out = []
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", "32"))) as ex:
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
