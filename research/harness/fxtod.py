"""FX time-of-day drift: do currencies weaken during their own working hours (Ranaldo 2009)?

Ranaldo (2009, "Segmentation and time-of-day patterns in foreign exchange markets") found that a
currency tends to depreciate during its home market's working hours and appreciate during foreign
hours. It is attributed to home-currency buying and selling by domestic firms and to order flow
segmented by time zone. If it holds out of sample, it is a small, directionless-by-construction
drift that a session-aware sizer or entry timer could lean on.

The pattern is fixed here, before any run. These are each currency's home hours in UTC, on standard
time; daylight saving moves them an hour for part of the year, which only blurs the test:

  JPY 00-07     AUD, NZD 22-06     EUR, CHF, GBP 07-15     USD, CAD 13-21

For a pair BASE/QUOTE in hour h, the signal is s = -1 if BASE is at home and QUOTE is not (BASE
weakens, so the pair falls), s = +1 if QUOTE is at home and BASE is not, and 0 otherwise. The return
is the hour's log return over the slow causal hourly volatility, known before the hour: the 480-bar
mean of an EWMA of |log return| as of the previous bar.

Scores, in both halves of a 60/40 split by time:
  - pooled   mean of s x return over every hour with s != 0, per pair and pooled, with t-stats
             clustered by calendar day. Clustering is by day rather than pair-day because pairs
             share currencies, so pairs on the same day are not independent draws
  - currency the same, split by which currency's home hours produced the signal
  - profile  per pair, the mean return by UTC hour, and the correlation of the discovery-half
             and verification-half 24-hour profiles: does *any* hour pattern persist, Ranaldo's or
             not?
  - trade    hold s through each block of hours it is non-zero and pay a round trip per block:
             COST_V (0.8 M5-vol units for FX) scaled by sqrt(5/60) into hourly-vol units. Net
             mean per pair-day

Control: FX-calendar walks we generate (iid Student-t(3) hourly moves, as in `fridayflag.py`),
given FX pair names so the same signal applies. The signal's pooled t must be within +-2 there.
Deriv indices and crypto have no home currency or working hours, so they are outside this question
rather than controls.

Pre-registered: the Ranaldo pattern holds if the pooled mean of s x return is positive with
clustered t >= 3 in both halves and the control's |t| < 2. It is worth trading only if the net
session trade is positive in the verification half with t >= 2.

Run on the lab:
  SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/fxtod.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from fridayflag import walk_frame

START = pd.Timestamp(os.environ.get("START", "2015-01-01"), tz="UTC").timestamp()
SPLIT = 0.6
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY",
         "EURGBP", "AUDJPY", "CHFJPY", "EURCHF", "EURAUD", "GBPAUD", "CADJPY", "NZDJPY", "AUDNZD"]
HOME = {"JPY": range(0, 7), "AUD": [22, 23, 0, 1, 2, 3, 4, 5], "NZD": [22, 23, 0, 1, 2, 3, 4, 5],
        "EUR": range(7, 15), "CHF": range(7, 15), "GBP": range(7, 15),
        "USD": range(13, 21), "CAD": range(13, 21)}
COST = 0.8 * np.sqrt(5 / 60)  # a round trip, in hourly-vol units
WALK_NAMES = ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD", "EURJPY"]


def signal(pair: str, hour: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Ranaldo's sign for each hour, and which currency's home hours produced it."""
    base, quote = pair[:3], pair[3:6]
    b = np.isin(hour, list(HOME.get(base, [])))
    q = np.isin(hour, list(HOME.get(quote, [])))
    s = np.where(b & ~q, -1, np.where(q & ~b, 1, 0))
    who = np.where(b & ~q, base, np.where(q & ~b, quote, ""))
    return s, who


def frame(sym: str, universe: str) -> pd.DataFrame | None:
    if universe == "walks":
        df = walk_frame(WALK_NAMES.index(sym) + 100)
    else:
        try:
            df = spikerisk.load(None, sym, "SEQLAB", "1h")
        except (ValueError, FileNotFoundError) as exc:
            print(f"  skip {sym}: {str(exc)[:60]}", flush=True)
            return None
        df = df[df["ts"] >= START].reset_index(drop=True)
    if len(df) < 2000:
        return None
    c = df["close"].to_numpy()
    logr = np.diff(np.log(c), prepend=np.log(c[0]))
    fast = pd.Series(np.abs(logr)).ewm(span=24, adjust=False).mean() * np.sqrt(np.pi / 2)
    slow = fast.rolling(480, min_periods=240).mean().shift(1).to_numpy()
    ts = df["ts"].to_numpy()
    gap = np.r_[False, np.diff(ts) > 3 * 3600]  # the first hour after a weekend or outage is a gap
    hour = pd.to_datetime(ts, unit="s", utc=True).hour.to_numpy()
    s, who = signal(sym, hour)
    out = pd.DataFrame({"pair": sym, "universe": universe, "time": ts, "hour": hour,
                        "day": ts // 86_400, "r": logr / slow, "s": s, "who": who})
    return out[np.isfinite(out["r"]) & ~gap].reset_index(drop=True)


def clustered(values: pd.Series, day: pd.Series) -> tuple[float, float, int]:
    ok = np.isfinite(values)
    v, d = values[ok], day[ok]
    if len(v) < 30:
        return float("nan"), float("nan"), len(v)
    m = v.mean()
    sums = (v - m).groupby(d).sum()
    se = np.sqrt((sums**2).sum()) / len(v)
    return float(m), float(m / se) if se > 0 else float("nan"), len(v)


def session_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Hold s through each block of consecutive hours where it is non-zero, and pay a round trip
    per block. One row per pair-day: gross and net, in hourly-vol units."""
    rows = []
    for (pair, day), g in df.groupby(["pair", "day"]):
        s = g["s"].to_numpy()
        blocks = int(((s != 0) & (np.r_[0, s[:-1]] != s)).sum())
        gross = float((s * g["r"].to_numpy()).sum())
        rows.append({"pair": pair, "day": day, "time": g["time"].iloc[0], "gross": gross,
                     "net": gross - COST * blocks, "blocks": blocks})
    return pd.DataFrame(rows)


def study(df: pd.DataFrame, universe: str) -> None:
    cut = df["time"].quantile(SPLIT)
    halves = {"discovery": df[df["time"] < cut], "verification": df[df["time"] >= cut]}
    print(f"\n== {universe}: {df['pair'].nunique()} pairs, {len(df):,} hours")

    print("  s x return, mean in hourly-vol units (t clustered by day) - discovery | verification")
    for pair in ["(pooled)", *sorted(df["pair"].unique())]:
        cells = []
        for part in halves.values():
            g = part if pair == "(pooled)" else part[part["pair"] == pair]
            g = g[g["s"] != 0]
            m, t, n = clustered(g["s"] * g["r"], g["day"])
            cells.append(f"{m:+.4f} (t {t:+5.1f}, n {n:,})")
        print(f"    {pair:9s} {cells[0]} | {cells[1]}")

    print("  by the currency whose home hours give the signal (pooled across pairs):")
    for who in sorted(set(df["who"]) - {""}):
        cells = []
        for part in halves.values():
            g = part[part["who"] == who]
            m, t, n = clustered(g["s"] * g["r"], g["day"])
            cells.append(f"{m:+.4f} (t {t:+5.1f}, n {n:,})")
        print(f"    {who}  {cells[0]} | {cells[1]}")

    print("  hour profiles: correlation of the 24-hour mean-return profile, discovery vs verification")
    for pair in sorted(df["pair"].unique()):
        prof = [p[p["pair"] == pair].groupby("hour")["r"].mean().reindex(range(24))
                for p in halves.values()]
        corr = prof[0].corr(prof[1])
        top = prof[0].abs().sort_values(ascending=False).index[:3].tolist()
        print(f"    {pair:9s} r = {corr:+.2f} | discovery's largest hours {top}: "
              f"{', '.join(f'{prof[0][h]:+.3f}->{prof[1][h]:+.3f}' for h in top)}")

    print("  the session trade (hold s through each block, a round trip per block), per pair-day:")
    for name, part in halves.items():
        tr = session_trades(part)
        mg, tg, _ = clustered(tr["gross"], tr["day"])
        mn, tn, n = clustered(tr["net"], tr["day"])
        print(f"    {name:12s} gross {mg:+.4f} (t {tg:+.1f}) | net {mn:+.4f} (t {tn:+.1f}) | "
              f"{n:,} pair-days, {tr['blocks'].mean():.1f} blocks a day")


def main() -> None:
    for universe, names in (("fx", PAIRS), ("walks", WALK_NAMES)):
        parts = [f for p in names if (f := frame(p, universe)) is not None]
        if not parts:
            print(f"\n== {universe}: no data")
            continue
        study(pd.concat(parts, ignore_index=True), universe)


if __name__ == "__main__":
    main()
