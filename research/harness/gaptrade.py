"""Trade the FX weekend gap: enter at Friday's close against its last hours, exit at Sunday's open.

`fridayflag.md` found one directional signal in the weekend gap: it reverses Friday's last 4 hours
(rank r -0.242 / -0.234 in the two halves; walks -0.03). The desk's question is whether that trade
pays: enter on Friday before the close, exit at Sunday's open, taking the gap's direction.

The worry is that it is **bid-ask bounce** rather than a reversal. MT5 bars are bid prices, and a
noisy last print at a wide Friday spread would "reverse" at the open without anything tradable
behind it. Two tests separate the cases:

  lag       enter 1 or 2 hours *before* the last close, on the move up to that bar. A real reversal
            survives an earlier entry; a bounce at the final print does not.
  cost      MT5 records each bar's spread. The spread paid is the one at the end of the trade where
            the ask is crossed: at entry for a long (buy at the ask, sell at the bid) and at exit
            for a short. So each trade is charged its own side's recorded spread. The spreads
            around the weekend are several times their weekday median, which is the point.

The trade, per pair and weekend, from 1h bars (j is Friday's last bar, j + 1 Sunday's first):

  signal    side = -sign(log(close[j-lag] / close[j-lag-K])), K = 1, 4, 8 hours and 120 (the week)
  entry     close[j - lag], lag = 0, 1, 2 hours
  exit      "open": Sunday's first open, open[j + 1]
            "1h": the close of Sunday's first hour, close[j + 1], after the opening spread has
            come in
  return    side * log(exit / entry), in basis points and in the pair's slow hourly vol (the
            480-bar mean of an EWMA of |log return|, as `fridayflag.py`)

Reported per variant, pooled over FX pairs, for metals, and per pair:
  - mean gross return (bps and vol) and hit rate;
  - t from a bootstrap over whole weekends (a weekend is shared by every pair), for the pooled
    figures; plain t per pair, one row per weekend;
  - the first 60% and last 40% of weekends;
  - **breakeven**: the round-trip cost in bps at which the mean gross return is zero;
  - the recorded spread each trade would have paid, and the mean net of it.

Swap: holding past Friday's rollover costs a night's swap, which the terminal publishes per symbol
(`/symbols/info`). It is read when the lab can reach the terminal and reported beside the result;
it is not charged, because its sign depends on the side and the pair's carry.

Controls: FX-calendar walks we generate (`fridayflag.walk_frame`: iid Student-t(3) moves and an
independent weekend gap). Every variant must read about zero there. Deriv indices trade through the
weekend and have no gap, so they are not in this study; that is not a verdict on them.

Pre-registered: the trade is worth building if, in pooled FX, the lag-0 variant's mean net of the
recorded spread is positive in both halves with a weekend-bootstrap 95% interval above zero in the
verification half, the lag-1 variant keeps at least half of lag-0's gross, and the walks' intervals
contain zero.

Run on the lab:
  SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/gaptrade.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import fridayflag as ff

SEQLAB = Path(os.environ.get("SEQLAB", ".data/seqlab"))
KS = (1, 4, 8, 120)
LAGS = (0, 1, 2)
EXITS = ("open", "1h")
SPLIT = 0.6


def load(sym: str) -> pd.DataFrame | None:
    """1h bars with MT5's recorded spread (in points), repaired as `spikerisk.load` repairs them."""
    if sym.startswith("walk_"):
        df = ff.walk_frame(int(sym.split("_")[1]))
        df["spread"] = 0.0
        return df
    path = SEQLAB / f"{sym}.1h.npz"
    if not path.exists():
        print(f"  skip {sym}: no bars", flush=True)
        return None
    z = np.load(path)
    df = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close", "spread")})
    df = df.rename(columns={"time": "ts"}).astype({"ts": np.int64})
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df[df["ts"] >= ff.START].reset_index(drop=True)


def point_of(sym: str, closes: np.ndarray) -> tuple[float, dict]:
    """The symbol's point, from the terminal when reachable, else from the prices' decimals."""
    info = {}
    try:
        import feed  # research/harness/feed.py - the key stays inside it

        got = feed._get(f"/symbols/info/{sym}")
        if isinstance(got, dict):
            info = got
            if float(got.get("point") or 0) > 0:
                return float(got["point"]), info
    except Exception:  # noqa: BLE001 - the terminal is optional here
        pass
    sample = closes[np.isfinite(closes)][-2000:]
    digits = 0
    for d in range(7):
        if np.all(np.abs(np.round(sample, d) - sample) < 1e-9 * np.maximum(sample, 1)):
            digits = d
            break
    else:
        digits = 5
    return 10.0**-digits, info


def trades(sym: str, family: str, df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    ts = df["ts"].to_numpy()
    point, info = point_of(sym, c) if family != "walks" else (0.0, {})
    spread_bps = df["spread"].to_numpy() * point / c * 1e4 if point else np.zeros(len(c))
    logr = np.abs(np.diff(np.log(c), prepend=np.log(c[0])))
    vol = pd.Series(logr).ewm(span=24, adjust=False).mean().to_numpy() * np.sqrt(np.pi / 2)
    slow = pd.Series(vol).rolling(480, min_periods=240).mean().to_numpy()
    when = pd.to_datetime(ts, unit="s", utc=True)
    weekday = (when.weekday <= 3) & (when.hour >= 7) & (when.hour < 17)
    edges = {"weekday": float(np.nanmedian(spread_bps[weekday])) if weekday.any() else np.nan}
    fri, sun, sun2 = [], [], []
    rows = []
    for j in np.flatnonzero(np.diff(ts) > 36 * 3600):
        friday = pd.Timestamp(ts[j], unit="s", tz="UTC")
        if friday.weekday() != 4 or j < 480 or j + 1 >= len(c) or not np.isfinite(slow[j]):
            continue
        fri.append(spread_bps[j])
        sun.append(spread_bps[j + 1])
        if j + 2 < len(c):
            sun2.append(spread_bps[j + 2])
        v = slow[j]
        for lag in LAGS:
            e = j - lag
            for k in KS:
                move = np.log(c[e] / c[e - k])
                if move == 0:
                    continue
                side = -np.sign(move)
                # The open is charged Sunday's first bar's spread; the 1h exit, the next bar's -
                # the nearest recorded after the opening hour.
                later = spread_bps[j + 2] if j + 2 < len(spread_bps) else spread_bps[j + 1]
                for exit_name, exit_px, exit_spread in (("open", o[j + 1], spread_bps[j + 1]),
                                                        ("1h", c[j + 1], later)):
                    r = side * np.log(exit_px / c[e])
                    paid = spread_bps[e] if side > 0 else exit_spread
                    rows.append({"sym": sym, "family": family, "time": int(ts[j]),
                                 "weekend": friday.strftime("%Y-%m-%d"), "lag": lag, "k": k,
                                 "exit": exit_name, "bps": r * 1e4, "vol": r / v, "paid": paid})
    edges.update({"friday_last": float(np.nanmedian(fri)) if fri else np.nan,
                  "sunday_first": float(np.nanmedian(sun)) if sun else np.nan,
                  "sunday_second": float(np.nanmedian(sun2)) if sun2 else np.nan})
    swap = {k: info.get(k) for k in ("swap_long", "swap_short", "swap_mode", "swap_rollover3days")
            if k in info}
    return pd.DataFrame(rows), {"sym": sym, "point": point, **edges, **swap}


def summarise(g: pd.DataFrame, pooled: bool) -> dict:
    out = {"n": len(g), "bps": g["bps"].mean(), "vol": g["vol"].mean(), "hit": (g["bps"] > 0).mean(),
           "paid": g["paid"].mean(), "net": (g["bps"] - g["paid"]).mean()}
    if pooled:
        g = g.reset_index(drop=True)
        _, lo, hi = ff.boot(g, lambda d: d["bps"].mean())
        out["t"] = out["bps"] / ((hi - lo) / 3.92) if hi > lo else np.nan
        out["net_ci"] = ff.boot(g.assign(x=g["bps"] - g["paid"]), lambda d: d["x"].mean())[1:]
    else:
        sd = g["bps"].std(ddof=1)
        out["t"] = out["bps"] / (sd / np.sqrt(len(g))) if len(g) > 2 and sd > 0 else np.nan
    return out


def report(df: pd.DataFrame, family: str) -> None:
    cut = df["time"].quantile(SPLIT)
    print(f"\n== {family}: {df['sym'].nunique()} pairs, {df['weekend'].nunique()} weekends"
          f" · bps and hourly-vol units · paid = the recorded spread on the side that crosses it")
    print("   lag  K    exit | discovery: gross bps (t) hit | verification: gross bps (t) hit"
          " | breakeven bps | paid bps | net bps [95%]")
    for (lag, k, ex), g in df.groupby(["lag", "k", "exit"]):
        a = summarise(g[g["time"] < cut], pooled=True)
        b = summarise(g[g["time"] >= cut], pooled=True)
        lo, hi = b["net_ci"]
        print(f"   {lag:3d} {k:4d} {ex:>5s} | {a['bps']:+7.2f} ({a['t']:+5.1f}) {a['hit']:.1%}"
              f" | {b['bps']:+7.2f} ({b['t']:+5.1f}) {b['hit']:.1%}"
              f" | {b['bps']:+7.2f} | {b['paid']:6.2f} | {b['net']:+7.2f} [{lo:+.2f}, {hi:+.2f}]"
              f" | vol {b['vol']:+.3f}")
    if family == "walks":
        return
    print("  per pair, lag 0, K = 4, exit at the open - all weekends:")
    one = df[(df["lag"] == 0) & (df["k"] == 4) & (df["exit"] == "open")]
    for sym, g in one.groupby("sym"):
        s = summarise(g, pooled=False)
        print(f"    {sym:8s} n={s['n']:4d} gross {s['bps']:+7.2f} bps (t {s['t']:+5.1f}) hit {s['hit']:.1%}"
              f" | paid {s['paid']:6.2f} | net {s['net']:+7.2f}")


def main() -> None:
    universes = {"fx": ff.FX, "metals": ff.METALS, "walks": [f"walk_{i}" for i in range(ff.WALKS)]}
    for family, syms in universes.items():
        parts, costs = [], []
        for s in syms:
            df = load(s)
            if df is None or len(df) < 1000:
                continue
            t, info = trades(s, family, df)
            if len(t):
                parts.append(t)
                costs.append(info)
        if not parts:
            print(f"\n== {family}: no data")
            continue
        if family != "walks":
            print(f"\n== {family}: recorded spread in bps (median) - weekday 07-17 UTC | Friday's last bar |"
                  " Sunday's first | Sunday's second; swap as the terminal publishes it")
            for info in costs:
                swap = {k: v for k, v in info.items() if k.startswith("swap")}
                print(f"    {info['sym']:8s} {info['weekday']:6.2f} | {info['friday_last']:6.2f} |"
                      f" {info['sunday_first']:6.2f} | {info['sunday_second']:6.2f}"
                      f"{'  ' + str(swap) if swap else ''}")
        report(pd.concat(parts, ignore_index=True), family)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
