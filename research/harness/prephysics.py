"""Part K (research/docs/ideas.md): pre-expansion physics - fatigue, rheology, foreshocks, and the
smallest state that keeps the information.

Pre-registered (2026-10-02), before any run. Rows: expansion_build.py's compressed bars (real
markets, 15m and 1h), each instrument's first 60% by time trains, the rest scores, both halves; the
same on GARCH walks.

  K4 fatigue     failed breakouts (a close beyond the 16-bar box, back inside within 4 bars) and
                 boundary tests (a high or low within 0.1 ATR of the box edge), each decayed with
                 rho = 0.9 a bar
  K1 rheology    compliance: the median over 16 bars of |bar move| / tick volume, against its
                 500-bar median (log); elastic recovery: the share of the last 64 bars' excursions
                 beyond the box that closed back inside within 2 bars
  K3 foreshocks  bars in the last 32 with range z > 2 (100-bar norm) while the series is compressed;
                 acceleration: their count in the last 8 bars over the 24 before
  question 1     does each group add >= 0.005 held-out AUC, both halves, to the alert's own 16
                 features, predicting expansion within 16 bars? (and not on walks)
  question 2     at the breakout (escape.py's events from these rows), does it separate clean escapes
                 from whipsaws beyond the martingale geometry (p_null)? AUC, both halves, vs walks
  K14            the smallest subset of the alert's 16 features whose held-out AUC is within 0.005 of
                 all 16 (greedy backward elimination on the training rows' own validation split)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "harness"))
sys.path.insert(0, str(ROOT))

import escape as es  # noqa: E402
import expansion_build as eb  # noqa: E402
from till_infinity.models import expansion_train as et  # noqa: E402
from till_infinity.models.shocks_train import auc  # noqa: E402
from till_infinity.structures.learning import expansion as ex  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/prephysics"))
SECONDS = {"15m": 900, "1h": 3600}
GROUPS = {"K4_fatigue": ["failed_breaks", "boundary_tests"],
          "K1_rheology": ["compliance", "elastic"],
          "K3_foreshocks": ["foreshocks", "fore_accel"]}


def frame(bars) -> pd.DataFrame:
    return pd.DataFrame([(b.time, b.open, b.high, b.low, b.close, b.volume or 0.0) for b in bars],
                        columns=["time", "open", "high", "low", "close", "volume"])


def physics(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = (df[k].astype(float) for k in ("open", "high", "low", "close"))
    pc = c.shift()
    atr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1).ewm(alpha=1 / 14, adjust=False).mean()
    bh, bl = h.rolling(16).max().shift(), l.rolling(16).min().shift()
    outside = (c > bh) | (c < bl)
    back = pd.Series(False, index=c.index)
    for k in range(1, 5):
        back |= outside.shift(k, fill_value=False) & (c <= bh.shift(k)) & (c >= bl.shift(k))
    failed = back.astype(float)
    tests = ((bh - h).abs() <= 0.1 * atr) | ((l - bl).abs() <= 0.1 * atr)

    def decay(x):
        v, acc = x.to_numpy(float), 0.0
        out = np.empty(len(v))
        for i, xi in enumerate(v):
            acc = 0.9 * acc + (0.0 if np.isnan(xi) else xi)
            out[i] = acc
        return out

    move = np.log(c / pc).abs()
    vol = df["volume"].astype(float).replace(0, np.nan)
    comp = (move / vol).rolling(16, min_periods=8).median()
    comp_rel = np.log(comp / comp.rolling(500, min_periods=100).median())
    snap = pd.Series(np.nan, index=c.index)
    exc = outside.astype(float)
    snapped = pd.Series(False, index=c.index)
    for k in (1, 2):
        snapped |= outside.shift(k, fill_value=False) & (c <= bh.shift(k)) & (c >= bl.shift(k))
    snap = snapped.astype(float).rolling(64, min_periods=16).sum() / exc.rolling(64, min_periods=16).sum().replace(0, np.nan)
    rng = np.log(h / l)
    rz = (rng - rng.rolling(100).mean()) / rng.rolling(100).std()
    fore = (rz > 2).astype(float)
    return pd.DataFrame({"time": df["time"].astype(np.int64), "failed_breaks": decay(failed),
                         "boundary_tests": decay(tests.astype(float)), "compliance": comp_rel.to_numpy(),
                         "elastic": snap.to_numpy(), "foreshocks": fore.rolling(32).sum().to_numpy(),
                         "fore_accel": (fore.rolling(8).sum() / 8 - fore.shift(8).rolling(24).sum() / 24).to_numpy()})


def fit_auc(Xtr, ytr, Xte, yte, s2):
    from sklearn.ensemble import HistGradientBoostingClassifier
    Xtr, Xte = Xtr.copy(), Xte.copy()
    empty = np.all(np.isnan(Xtr), axis=0)
    Xtr[:, empty], Xte[:, empty] = 0.0, 0.0
    m = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, min_samples_leaf=300).fit(Xtr, ytr)
    p = m.predict_proba(Xte)[:, 1]
    return dict(auc=round(auc(yte, p), 4), halves=[round(auc(yte[~s2], p[~s2]), 4), round(auc(yte[s2], p[s2]), 4)])


def rows_for(series: dict, frames: dict):
    rows = et.dataset(series, intervals=("15m", "1h"))
    when, kinds, x, y = rows.arrays()
    keys = np.array(rows.key)
    P = np.full((len(y), 6), np.nan)
    cols = [c for g in GROUPS.values() for c in g]
    train = np.zeros(len(y), bool)
    second = np.zeros(len(y), bool)
    for k in np.unique(keys):
        m = np.flatnonzero(keys == k)
        f = frames.get(k)
        if f is not None:
            P[m] = f.set_index(f["time"] + SECONDS[k.split("|")[1]])[cols].reindex(when[m]).to_numpy()
        cut = np.quantile(when[m], 0.6)
        train[m] = when[m] < cut
        te = m[when[m] >= cut]
        second[te] = when[te] >= np.median(when[te])
    return when, kinds, x, y, keys, P, train, second, cols


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    res = {}
    for kind in ("market", "walk"):
        series, frames = {}, {}
        if kind == "market":
            for sym, fam in eb.FAMILY.items():
                if fam == "deriv":
                    continue
                for iv in ("15m", "1h", "4h"):
                    bars = eb.load(sym, iv)
                    if len(bars) > 2_000:
                        series[(sym, iv)] = bars
                        if iv in SECONDS:
                            df = frame(bars)
                            frames[f"{sym}|{iv}"] = physics(df)
        else:
            walks = et.walks(8, 20_000, garch=True)
            for (s, iv), bars in walks.items():
                series[(s, iv)] = bars
                if iv in SECONDS:
                    df = frame(bars)
                    frames[f"{s}|{iv}"] = physics(df)
        when, kinds, x, y, keys, P, train, second, cols = rows_for(series, frames)
        te = ~train
        s2 = second[te]
        base = fit_auc(x[train], y[train], x[te], y[te], s2)
        q1 = {"base": base}
        for g, gc in GROUPS.items():
            idx = [cols.index(c) for c in gc]
            X = np.column_stack([x, P[:, idx]])
            v = fit_auc(X[train], y[train], X[te], y[te], s2)
            v["counts"] = bool(min(v["halves"][i] - base["halves"][i] for i in (0, 1)) >= 0.005)
            q1[g] = v
        X = np.column_stack([x, P])
        q1["all"] = fit_auc(X[train], y[train], X[te], y[te], s2)
        res[f"{kind}/expansion"] = q1
        print(kind, "expansion", json.dumps(q1), flush=True)
        # K14: the smallest subset of the alert's own features, on the training rows' validation split
        if kind == "market":
            tr_idx = np.flatnonzero(train)
            cut = np.quantile(when[tr_idx], 0.75)
            fit_m, val_m = tr_idx[when[tr_idx] < cut], tr_idx[when[tr_idx] >= cut]
            keep = list(range(x.shape[1]))
            full = fit_auc(x[fit_m][:, keep], y[fit_m], x[val_m][:, keep], y[val_m], np.zeros(len(val_m), bool))["auc"]
            improved = True
            while improved and len(keep) > 1:
                improved = False
                best = None
                for j in keep:
                    trial = [k for k in keep if k != j]
                    a = fit_auc(x[fit_m][:, trial], y[fit_m], x[val_m][:, trial], y[val_m], np.zeros(len(val_m), bool))["auc"]
                    if a >= full - 0.005 and (best is None or a > best[1]):
                        best = (j, a)
                if best is not None:
                    keep.remove(best[0])
                    improved = True
            small = fit_auc(x[train][:, keep], y[train], x[te][:, keep], y[te], s2)
            res["K14_minimal"] = dict(features=[ex.NAMES[k] for k in keep], held_out=small, all16=base)
            print("K14", json.dumps(res["K14_minimal"]), flush=True)
    (OUT / "prephysics.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1), flush=True)


if __name__ == "__main__":
    main()
