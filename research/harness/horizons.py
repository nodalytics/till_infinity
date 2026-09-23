"""Directional models over a period, not the next bar - shorts and longs, several horizons.

`crashlab.py` labelled "a single large bar somewhere in the next H", which is a
size event, and every model it built learned size. A desk does not trade a bar;
it holds a position from now until some time H away. So the labels here are
about the path over that period:

  tb    triple barrier. Barriers at +-B from the entry, B = 1.5 x baseline x sqrt(H).
        +1 if the upper is touched first within H bars, -1 if the lower, 0 if
        neither. A short model is trained on tb == -1, a long model on tb == +1.
        This is literally "does a short with a symmetric stop and target win
        before the clock runs out", so its realised value is an R-multiple:
        the crossing close at a barrier (a close overshoots, so a stop costs more than 1R),
        the H-bar return in B units if neither is touched.
  dd    the worst drop inside the window beats 2B (a crash, whatever happens
        after) and ru, the mirror, a melt-up. These ask about the path's extreme
        rather than who wins the race.

Horizons, in bars: 15m -> 1h, 2h, 5h; 1h -> 1h, 5h, 12h, 24h; 1d -> 1, 5, 20 days.

Features are `crashlab.features` plus time and seasonality:
  hour-of-week seasonal |r| and signed drift (expanding means over prior weeks only),
  session flags (Asia/London/New York by UTC hour), hours to the Friday close,
  day-of-month and month on the circle, turn-of-month flag.

A gradient-boosted model per (label, side, horizon), fit on each series' first 60%
by time, scored on the last 40%. The trade check uses non-overlapping entries
(every H-th bar), and reports the two halves of the test period separately - a
result whose sign flips between them is not one.

Run from the repository root:  .venv-research/bin/python research/harness/horizons.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
from bars import Bars, long_R
from crashlab import features
from spikerisk import DAILY, DB, SERIES, SETUPS, load

HORIZONS = {"15m": (4, 8, 20), "1h": (1, 5, 12, 24), "1d": (1, 5, 20)}
B_MULT = 1.5


def seasonal(o, df, seconds):
    t = pd.to_datetime(df.ts.to_numpy(), unit="s")
    s = pd.DataFrame(index=o.index)
    z = o["_z"]
    if seconds < 86400:
        slot = pd.Series(t.dayofweek * 10_000 + t.hour * 100 + t.minute, index=o.index)
        prior = lambda v: v.groupby(slot).transform(lambda x: x.shift(1).expanding(min_periods=3).mean())
        s["season_vol"] = prior(z.abs())
        s["season_drift"] = prior(z)
        h = t.hour.to_numpy()
        s["asia"] = ((h >= 0) & (h < 7)).astype(float)
        s["london"] = ((h >= 7) & (h < 16)).astype(float)
        s["newyork"] = ((h >= 13) & (h < 21)).astype(float)
        hrs = ((4 - t.dayofweek.to_numpy()) % 7) * 24 + (21 - h - t.minute.to_numpy() / 60)
        s["to_weekend"] = np.log1p(np.clip(hrs, 0, None))
    else:
        s["season_drift"] = z.groupby(t.dayofweek.to_numpy()).transform(lambda x: x.shift(1).expanding(min_periods=20).mean())
        s["dow_s"], s["dow_c"] = np.sin(2 * np.pi * t.dayofweek / 7), np.cos(2 * np.pi * t.dayofweek / 7)
    s["dom_s"], s["dom_c"] = np.sin(2 * np.pi * t.day / 31), np.cos(2 * np.pi * t.day / 31)
    s["mon_s"], s["mon_c"] = np.sin(2 * np.pi * t.month / 12), np.cos(2 * np.pi * t.month / 12)
    s["turn_of_month"] = ((t.day <= 3) | (t.day >= 28)).astype(float)
    return s


def labels(o, H):
    """Path labels over the next H bars, touches read from the wicks (see bars.py)."""
    lc, base = o["_lc"].to_numpy(), o["_base"].to_numpy()
    n = len(lc)
    B = B_MULT * base * np.sqrt(H)
    shift = lambda x, k: np.concatenate([x[k:], np.full(k, np.nan)]) - lc
    P = Bars(*(np.column_stack([shift(o[c].to_numpy(), k) for k in range(1, H + 1)])
               for c in ("_op", "_hi", "_lo", "_lc")))
    R, w = long_R(P, B, B)
    Rs, ws = long_R(P * -1, B, B)
    lo, hi = np.nanmin(P.l, axis=1), np.nanmax(P.h, axis=1)
    valid = ~np.isnan(P.end) & ~np.isnan(B)
    out = pd.DataFrame(index=o.index)
    out["tb_dn"] = np.where(valid, (ws == 1).astype(float), np.nan)   # the short's target first
    out["tb_up"] = np.where(valid, (w == 1).astype(float), np.nan)
    out["dd"] = np.where(valid, (lo <= -2 * B).astype(float), np.nan)
    out["ru"] = np.where(valid, (hi >= 2 * B).astype(float), np.nan)
    out["R"] = np.where(valid, R, np.nan)      # long R; the short's is its own race, below
    out["Rs"] = np.where(valid, Rs, np.nan)
    out["path_lo"] = np.where(valid, lo / B, np.nan)
    out["path_hi"] = np.where(valid, hi / B, np.nan)
    return out


def build(interval, universe):
    seconds, _, long, season = SETUPS[interval]
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    parts = []
    for family, pairs in universe.items():
        for ticker, venue in pairs:
            df = load(conn, ticker, venue, interval)
            if len(df) < long * 3:
                continue
            df = df[df.close > 0].reset_index(drop=True)
            o = features(df, seconds, long, season)
            o = pd.concat([o, seasonal(o, df, seconds)], axis=1)
            for H in HORIZONS[interval]:
                o = pd.concat([o, labels(o, H).add_suffix(f"@{H}")], axis=1)
            o["family"], o["ticker"] = family, ticker
            parts.append(o)
    d = pd.concat(parts, ignore_index=True)
    big = (d["_absz"] > 4).astype(float)
    d["_big4"] = big.groupby(d.ticker).transform(lambda s: s.rolling(4, min_periods=1).max())
    g = d.groupby("ts")
    n = g["_absz"].transform("count")
    d["cx_absz"] = (g["_absz"].transform("sum") - d["_absz"].fillna(0)) / (n - 1).clip(lower=1)
    d["cx_big4"] = (g["_big4"].transform("sum") - d["_big4"]) / (n - 1).clip(lower=1)
    d["cx_mom"] = (g["mom20"].transform("sum") - d["mom20"].fillna(0)) / (n - 1).clip(lower=1)
    d.loc[n < 3, ["cx_absz", "cx_big4", "cx_mom"]] = np.nan
    d = d[d["_base"].notna()].reset_index(drop=True)
    size = d.groupby("ticker").ts.transform("size")
    pos = d.groupby("ticker").cumcount()
    d["split"] = np.select([pos < size * 0.6, pos < size * 0.8], [0, 1], 2)  # train, test-a, test-b
    d["_pos"] = pos
    cols = [c for c in d.columns if not c.startswith("_") and "@" not in c
            and c not in ("ts", "family", "ticker", "split")]
    return d, cols


def gbm():
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=250,
                                          min_samples_leaf=300, l2_regularization=1.0)


def run(interval, universe):
    d, cols = build(interval, universe)
    X = d[cols].to_numpy(dtype=float)
    fam = d.family.to_numpy()
    print(f"\n{'=' * 110}\n{interval}: {d.ticker.nunique()} series, {len(d):,} bars, {len(cols)} features")
    print(f"{'H':>4} {'model':>8} {'base':>6} {'AUC':>6} {'AUC-opp':>7} | top-5% trade, R per trade (non-overlap)"
          f"{'':>6}| test-a    test-b  | by family")
    rows = []
    for H in HORIZONS[interval]:
        R, Rs = d[f"R@{H}"].to_numpy(), d[f"Rs@{H}"].to_numpy()
        slot = (d["_pos"].to_numpy() % H) == 0
        for name, label, opp, side in (("short", "tb_dn", "tb_up", -1), ("long", "tb_up", "tb_dn", 1),
                                       ("crash", "dd", "ru", -1), ("meltup", "ru", "dd", 1)):
            y, yo = d[f"{label}@{H}"].to_numpy(), d[f"{opp}@{H}"].to_numpy()
            ok = ~np.isnan(y)
            tr = ok & (d.split.to_numpy() == 0)
            te = ok & (d.split.to_numpy() > 0)
            p = np.full(len(d), np.nan)
            p[te] = gbm().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
            auc = roc_auc_score(y[te], p[te])
            auc_o = roc_auc_score(yo[te], p[te])
            cut = np.nanquantile(p[te], 0.95)
            alarm = te & (p >= cut) & slot
            Rside = R if side > 0 else Rs
            pnl = Rside[alarm]
            halves = []
            for s in (1, 2):
                k = alarm & (d.split.to_numpy() == s)
                halves.append(Rside[k].mean() if k.sum() else np.nan)
            fams = []
            for f in universe:
                k = alarm & (fam == f)
                if k.sum() >= 15:
                    fams.append(f"{f[:3]} {Rside[k].mean():+.2f}")
            uncond = Rside[te & slot].mean()
            print(f"{H:>4} {name:>8} {y[te].mean():6.1%} {auc:6.3f} {auc_o:7.3f} | {pnl.mean():+.3f} +- "
                  f"{pnl.std() / np.sqrt(max(len(pnl), 1)):.3f} n={len(pnl):>4} win {np.mean(pnl > 0):4.0%}"
                  f" (all {uncond:+.3f}) | {halves[0]:+.2f}  {halves[1]:+.2f} | {', '.join(fams)}")
            rows.append(dict(interval=interval, H=H, model=name, auc=auc, auc_opp=auc_o,
                             R=pnl.mean(), se=pnl.std() / np.sqrt(max(len(pnl), 1)), n=len(pnl),
                             a=halves[0], b=halves[1], uncond=uncond))
    return rows


if __name__ == "__main__":
    out = []
    for interval in ("15m", "1h"):
        out += run(interval, SERIES)
    out += run("1d", DAILY)
    Path(".data/research").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out).to_csv(".data/research/horizons.csv", index=False)
