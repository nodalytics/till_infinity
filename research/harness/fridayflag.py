"""Can Friday's state predict the FX weekend gap, and is flattening before the weekend worth it?

The FX week ends on Friday about 21:00 UTC and reopens on Sunday about 21:00. News lands in between,
and a stop cannot bound the move it causes: a gap fills at the open, wherever that is. A "Friday
flag" would flatten or shrink positions when a large gap is likely. That is only worth having if
the gap is predictable from what is known at the Friday close.

Per pair and weekend, from 1h bars: the gap is log(Sunday open / Friday close), in units of the
pair's slow causal hourly volatility (the 480-bar mean of an EWMA of |log return|, scaled to a
standard deviation). The slow vol, not the fast one: a gap divided by the fast vol that a feature
also reads is "predictable" by arithmetic, and the control caught exactly that (AUC 0.61 on
memoryless walks). Friday state at the close, in the same units:

  week      the last 120 bars' log return (about the trading week), in hourly-vol units
  friday    the last 24 bars' log return
  late      the last 4 bars' log return
  range     the last 6 bars' high-low range over the hourly vol
  vol       the hourly vol against its own 480-bar mean (about four weeks): is it a hot week?
  absweek   |week|, the "big week" reading that a sign-agnostic gap might follow

Targets:
  big       |gap| > 2x the median |gap|. The median comes from the discovery half, so the
            threshold is not fit on what it scores
  signed    the gap itself: does it continue or reverse Friday's move?

Scores, per family, in both halves of a 60/40 split by time:
  - AUC for `big` of each single feature, oriented on discovery;
  - AUC of a logistic model on all features, fit on discovery and scored on verification;
  - the rank (Spearman) correlation of the signed gap with week / friday / late; Pearson's
    bootstrap is unreliable on heavy tails.
Confidence intervals come from a bootstrap over weekends (a weekend is common to every pair, so
pairs are not independent draws). All t-stats are clustered by weekend.

The flag: flatten before the weekend when the model's big-gap probability is in the top quartile of
discovery. It is scored on a position held in the direction of the week's move, and on one held
against it, over every weekend of the verification half:
  avoided   the weekend losses beyond 2x the median |gap| that the flag stepped out of
  forgone   the weekend gains the flag stepped out of
  cost      a round trip per flattening: COST_V (0.8 M5-vol units for FX, 0.16 for metals),
            scaled by sqrt(5/60) into hourly-vol units
  net       the P&L change against always holding

Control: FX-calendar walks we generate. The moves are iid Student-t(3) through the week, and the
weekend gap is an independent t(3) draw at sqrt(48) hourly scales. Nothing on Friday can predict
it, so the AUC must read 0.5 within its interval. That checks the harness, not the market. Deriv
indices and crypto trade through the weekend and have no gap, so they are not in this study.

Pre-registered: the flag is worth building if the verification AUC for `big` is at least 0.60 with
a bootstrap 95% interval above 0.5 in both halves, the control's interval contains 0.5, and the
flag's net P&L after costs is positive in the verification half with a weekend-bootstrap
95% interval above zero. A signed gap is called predictable
only if |correlation| >= 0.1 with an interval excluding 0 in both halves.

Run on the lab:
  SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/fridayflag.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

START = pd.Timestamp(os.environ.get("START", "2015-01-01"), tz="UTC").timestamp()
SPLIT = 0.6
BOOT = int(os.environ.get("BOOT", "300"))
FX = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY",
      "EURGBP", "AUDJPY", "CHFJPY", "EURCHF", "EURAUD", "GBPAUD", "CADJPY", "NZDJPY", "AUDNZD"]
METALS = ["XAUUSD", "XAGUSD"]
COST_V = {"fx": 0.8, "metals": 0.16, "walks": 0.15}
FEATURES = ("week", "friday", "late", "range", "vol", "absweek")
WALKS = int(os.environ.get("WALKS", "6"))


# ---------------------------------------------------------------------------------------- the bars

def walk_frame(i: int, end: str | None = None) -> pd.DataFrame:
    """Our control: an FX-calendar hourly walk (Sunday 22:00 to Friday 21:00 UTC). The moves are iid
    Student-t(3); the weekend gap is an independent t(3) draw at sqrt(48) hourly scales."""
    rng = np.random.default_rng(500 + i)
    hours = pd.date_range(pd.Timestamp(START, unit="s", tz="UTC"),
                          pd.Timestamp(end or os.environ.get("END", "2026-09-01"), tz="UTC"),
                          freq="1h")
    wd, hr = hours.weekday, hours.hour
    open_ = ~((wd == 5) | ((wd == 4) & (hr >= 21)) | ((wd == 6) & (hr < 22)))
    hours = hours[open_]
    sd = 0.001 / np.sqrt(3.0)
    moves = rng.standard_t(3, len(hours)) * sd
    first = np.r_[True, np.diff(hours.asi8 // 10**9) > 24 * 3600]  # first bar after a weekend
    moves[first] = rng.standard_t(3, first.sum()) * sd * np.sqrt(48)
    close = 1.1 * np.exp(np.cumsum(moves))
    # The gap sits between the previous close and this open, so the open carries the jump and the
    # bar's own move is a normal hourly one.
    open_px = np.where(first, close / np.exp(rng.standard_t(3, len(close)) * sd), np.r_[1.1, close[:-1]])
    wick = np.abs(rng.standard_t(3, (len(close), 2))) * sd * 0.5
    return pd.DataFrame({"ts": (hours.asi8 // 10**9).astype(np.int64), "open": open_px,
                         "high": np.maximum(open_px, close) * np.exp(wick[:, 0]),
                         "low": np.minimum(open_px, close) * np.exp(-wick[:, 1]), "close": close})


def load(sym: str) -> pd.DataFrame | None:
    if sym.startswith("walk_"):
        return walk_frame(int(sym.split("_")[1]))
    try:
        df = spikerisk.load(None, sym, "SEQLAB", "1h")
    except (ValueError, FileNotFoundError) as exc:
        print(f"  skip {sym}: {str(exc)[:60]}", flush=True)
        return None
    return df[df["ts"] >= START].reset_index(drop=True)


# ---------------------------------------------------------------------------------------- weekends

def weekends(sym: str, family: str, df: pd.DataFrame) -> pd.DataFrame:
    c, o, h, lo = (df[k].to_numpy() for k in ("close", "open", "high", "low"))
    ts = df["ts"].to_numpy()
    logr = np.abs(np.diff(np.log(c), prepend=np.log(c[0])))
    vol = pd.Series(logr).ewm(span=24, adjust=False).mean().to_numpy() * np.sqrt(np.pi / 2)
    vol_norm = pd.Series(vol).rolling(480, min_periods=240).mean().to_numpy()
    rows = []
    for j in np.flatnonzero(np.diff(ts) > 36 * 3600):  # j = last bar before a gap of 1.5 days+
        friday = pd.Timestamp(ts[j], unit="s", tz="UTC")
        if friday.weekday() != 4 or j < 480 or not np.isfinite(vol_norm[j]) or vol[j] <= 0:
            continue
        # Everything in the slow (480-bar) vol. Dividing by the fast vol that the `vol` feature
        # reads made a quiet Friday a "big" gap by arithmetic: AUC 0.61 on memoryless walks.
        v = vol_norm[j]
        week = np.log(c[j] / c[j - 120]) / v
        rows.append({
            "sym": sym, "family": family, "time": int(ts[j]), "weekend": friday.strftime("%Y-%m-%d"),
            "gap": np.log(o[j + 1] / c[j]) / v,
            "week": week, "friday": np.log(c[j] / c[j - 24]) / v, "late": np.log(c[j] / c[j - 4]) / v,
            "range": (h[j - 5: j + 1].max() - lo[j - 5: j + 1].min()) / c[j] / v,
            "vol": vol[j] / v, "absweek": abs(week),
            "cost": COST_V[family] * np.sqrt(5 / 60),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------- scoring

def auc(y: np.ndarray, p: np.ndarray) -> float:
    pos, neg = y > 0.5, y <= 0.5
    if not pos.any() or not neg.any():
        return float("nan")
    r = pd.Series(p).rank().to_numpy()
    return float((r[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * neg.sum()))


def boot(df: pd.DataFrame, stat, n: int = BOOT, seed: int = 1) -> tuple[float, float, float]:
    """The statistic and a 95% interval from resampling whole weekends."""
    rng = np.random.default_rng(seed)
    groups = {w: g.index.to_numpy() for w, g in df.groupby("weekend")}
    keys = list(groups)
    got = []
    for _ in range(n):
        pick = np.concatenate([groups[k] for k in rng.choice(keys, len(keys))])
        got.append(stat(df.loc[pick]))
    got = np.array(got)
    got = got[np.isfinite(got)]
    if not len(got):
        return stat(df), float("nan"), float("nan")
    return stat(df), float(np.percentile(got, 2.5)), float(np.percentile(got, 97.5))


def logistic(train: pd.DataFrame, cols=FEATURES):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    x = train[list(cols)].to_numpy()
    scale = StandardScaler().fit(x)
    model = LogisticRegression(max_iter=1000).fit(scale.transform(x), train["big"].to_numpy())
    return lambda d: model.predict_proba(scale.transform(d[list(cols)].to_numpy()))[:, 1]


def flag_pnl(test: pd.DataFrame, flagged: np.ndarray, side: np.ndarray, threshold: float) -> dict:
    pnl = side * test["gap"].to_numpy()
    cost = test["cost"].to_numpy()
    loss_tail = pnl < -threshold
    return {
        "flagged": float(flagged.mean()),
        "tail_caught": float((flagged & loss_tail).sum() / max(loss_tail.sum(), 1)),
        "avoided": float(-pnl[flagged & (pnl < 0)].sum()),
        "forgone": float(pnl[flagged & (pnl > 0)].sum()),
        "cost": float(cost[flagged].sum()),
        "net": float(-pnl[flagged].sum() - cost[flagged].sum()),
        "per_weekend": float((-pnl[flagged].sum() - cost[flagged].sum()) / max(len(pnl), 1)),
        "sd_hold": float(pnl.std()), "sd_flag": float(np.where(flagged, 0.0, pnl).std()),
    }


def study(df: pd.DataFrame, family: str) -> None:
    df = df.sort_values("time").reset_index(drop=True)
    cut = df["time"].quantile(SPLIT)
    train, test = df[df["time"] < cut].copy(), df[df["time"] >= cut].copy()
    threshold = 2 * train["gap"].abs().median()
    for d in (train, test):
        d["big"] = (d["gap"].abs() > threshold).astype(float)
    print(f"\n== {family}: {len(df):,} pair-weekends ({df['weekend'].nunique()} weekends), "
          f"big = |gap| > {threshold:.2f} hourly vol, base rate {train['big'].mean():.1%} / "
          f"{test['big'].mean():.1%}; median |gap| {df['gap'].abs().median():.2f}")

    print("  AUC for a big gap, single features (oriented on discovery) - discovery | verification [95%]:")
    for f in FEATURES:
        sign = 1.0 if auc(train["big"].to_numpy(), train[f].to_numpy()) >= 0.5 else -1.0
        a_tr = auc(train["big"].to_numpy(), sign * train[f].to_numpy())
        a, lo, hi = boot(test, lambda d, f=f, sign=sign: auc(d["big"].to_numpy(), sign * d[f].to_numpy()))
        print(f"    {f:8s} {'+' if sign > 0 else '-'}  {a_tr:.3f} | {a:.3f} [{lo:.3f}, {hi:.3f}]")
    predict = logistic(train)
    a_tr = auc(train["big"].to_numpy(), predict(train))
    a, lo, hi = boot(test, lambda d: auc(d["big"].to_numpy(), predict(d)))
    print(f"    {'model':8s}    {a_tr:.3f} (in-sample) | {a:.3f} [{lo:.3f}, {hi:.3f}]")

    print("  signed gap: rank correlation with Friday's moves - discovery [95%] | verification [95%]:")
    for f in ("week", "friday", "late"):
        parts = []
        for d in (train, test):
            r, rl, rh = boot(d, lambda x, f=f: float(x[f].corr(x["gap"], method="spearman")))
            parts.append(f"{r:+.3f} [{rl:+.3f}, {rh:+.3f}]")
        print(f"    {f:8s} {parts[0]} | {parts[1]}")

    cutoff = np.quantile(predict(train), 0.75)
    test["flag"] = predict(test) >= cutoff
    flagged = test["flag"].to_numpy()
    print("  the flag (flatten when the model is in its top quartile), verification half, hourly-vol units:")
    for name, side in (("with the week", np.sign(test["week"].to_numpy())),
                       ("against the week", -np.sign(test["week"].to_numpy()))):
        got = flag_pnl(test, flagged, side, threshold)
        test["side"] = side
        _, lo, hi = boot(test, lambda d: flag_pnl(d, d["flag"].to_numpy(), d["side"].to_numpy(),
                                                  threshold)["per_weekend"])
        print(f"    {name:17s} flags {got['flagged']:.1%} | tail losses caught {got['tail_caught']:.1%}"
              f" | avoided {got['avoided']:.1f} forgone {got['forgone']:.1f} cost {got['cost']:.1f}"
              f" | net {got['net']:+.1f} ({got['per_weekend']:+.3f}/weekend [{lo:+.3f}, {hi:+.3f}])"
              f" | weekend sd {got['sd_hold']:.2f} -> {got['sd_flag']:.2f}")


def main() -> None:
    universes = {"fx": FX, "metals": METALS, "walks": [f"walk_{i}" for i in range(WALKS)]}
    for family, syms in universes.items():
        parts = [weekends(s, family, df) for s in syms if (df := load(s)) is not None and len(df) > 1000]
        parts = [p for p in parts if len(p)]
        if not parts:
            print(f"\n== {family}: no data")
            continue
        study(pd.concat(parts, ignore_index=True), family)


if __name__ == "__main__":
    main()
