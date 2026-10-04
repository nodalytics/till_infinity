"""DISPLACE_C on alts as a signal to buy the market: the historical check of `market_mirror_rule.json`.

Signal sources are the 12 original Binance coins (the variant was read on the 131 fresh coins); each
daily T1 long signal buys BTCUSDT at the next open and exits when the alt's own E2 trade exits.
Compared with the same holds entered on random days (a random-entry twin).

  OUT=... python research/ideas/market_mirror.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import turn_trade as TT  # noqa: E402

TT.SEC["1d"] = 86400
OUT = Path(os.environ.get("OUT", ".data/market_mirror"))
FEE_BPS = 7.0
HOLD_B = 5


def exits(df):
    """The alt's T1 long trades with their exit bar index (E2), from turn_trade's exit logic, re-walked."""
    from mcfl import candles
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(df)
    atr = np.asarray(candles.table(df)["atr"], float)
    low3 = pd.Series(l).rolling(3).min().to_numpy()
    prior = pd.Series(l).shift(3).rolling(9).min().to_numpy()
    U = TT.ups(df, both=True)
    H = 10
    out = []
    for t in np.flatnonzero((low3 <= prior) & U["DISPLACE_C"]):
        if t + 1 >= n or not atr[t] > 0:
            continue
        stop0 = low3[t] - 0.1 * atr[t]
        x = None
        for j in range(t + 1, min(n, t + 1 + H)):
            if l[j] <= stop0:
                x = j  # out during bar j at the stop
                break
            if U["DELIVERY_SHIFT_DOWN"][j] and j + 1 < n:
                x = j + 1  # out at the next open
                break
        if x is None:
            x = min(n - 1, t + H)
        out.append((int(df["ts"].iat[t]), int(df["ts"].iat[t + 1]), int(df["ts"].iat[x])))
    return out


def source(coin):
    """A signal source's daily bars: the 12 original coins from turn_trade, or SET_D from the cache."""
    if os.environ.get("SET") != "D":
        return TT._bin(coin, "1d")
    z = np.load(Path(os.environ["CACHE"]) / f"{coin}USDT.1d.npz")
    return pd.DataFrame({k: z[k] for k in ("ts", "open", "high", "low", "close", "volume")}).reset_index(drop=True)


def coins():
    if os.environ.get("SET") != "D":
        return [c for c in TT.COINS if c != "BTC"]
    import json
    rule = json.load(open(HERE / "market_mirror_rule.json"))
    cache = Path(os.environ["CACHE"])
    return [c for c in rule["addendum_set_d"]["coins"] if (cache / f"{c}USDT.1d.npz").exists()]


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    btc = TT._bin("BTC", "1d").set_index("ts")
    sig = []
    for coin in coins():
        df = source(coin)
        if len(df) < 60:
            continue
        for t, entry_ts, exit_ts in exits(df):
            sig.append(dict(coin=coin, ts=t, entry=entry_ts, exit=exit_ts))
    s = pd.DataFrame(sig)
    o = btc["open"]

    def ret(e, x):
        if e not in o.index or x not in o.index:
            return np.nan
        return (o[x] / o[e] - 1) * 1e4 - FEE_BPS

    s["bps"] = [ret(e, x) for e, x in zip(s["entry"], s["exit"])]
    s = s.dropna()
    # random-entry twin: the same holds on uniformly drawn days
    rng = np.random.default_rng(7)
    days = o.index.to_numpy()
    hold = ((s["exit"] - s["entry"]) // 86400).astype(int).to_numpy()
    tw = []
    for _ in range(200):
        idx = rng.integers(0, len(days) - 11, len(hold))
        tw.append(np.nanmean([(o.iat[i + k] / o.iat[i] - 1) * 1e4 - FEE_BPS for i, k in zip(idx, hold)]))
    # breadth B: >= 3 coins signal on the same close
    cnt = s.groupby("ts").size()
    bd = cnt[cnt >= 3].index
    bb = [((o.iat[i + HOLD_B] / o.iat[i] - 1) * 1e4 - FEE_BPS) for i in
          (o.index.get_loc(t + 86400) for t in bd if t + 86400 in o.index) if i + HOLD_B < len(o)]

    def boot(x, by):
        d = pd.DataFrame({"x": x, "g": by}).groupby("g")["x"].agg(["sum", "count"])
        b = [d["sum"].values[k].sum() / d["count"].values[k].sum()
             for k in (rng.integers(0, len(d), len(d)) for _ in range(2000))]
        return np.quantile(b, [0.05, 0.95])

    lo, hi = boot(s["bps"].to_numpy(), s["ts"].to_numpy())
    split = (pd.Timestamp("2024-01-01", tz="UTC").timestamp() if os.environ.get("SET") != "D"
             else float(np.median(np.unique(s["ts"]))))  # SET_D: the halves of its own signal dates
    before, after = s.loc[s["ts"] < split, "bps"].mean(), s.loc[s["ts"] >= split, "bps"].mean()
    s.to_csv(OUT / "mirror_trades.csv", index=False)
    ok = s["bps"].mean() > 0 and lo > 0 and before > 0 and after > 0 and s["bps"].mean() > np.quantile(tw, 0.95)
    print(f"M1 ({'SET_D' if os.environ.get('SET') == 'D' else '12 original coins'} -> BTC, 1d): n={len(s)} on {s['ts'].nunique()} days; net {s['bps'].mean():+.1f} bps "
          f"[{lo:+.1f}, {hi:+.1f}]; before 2024 {before:+.1f}, after {after:+.1f}; random-entry twin mean "
          f"{np.mean(tw):+.1f} (95th pct {np.quantile(tw, 0.95):+.1f}) -> {'PASSES' if ok else 'fails'}")
    print(f"B (>= 3 coins on a close, hold {HOLD_B}d): n={len(bb)} days; net {np.mean(bb):+.1f} bps" if bb else "B: no days")
    print(s.groupby("coin")["bps"].agg(["count", "mean"]).round(1).to_string())


if __name__ == "__main__":
    run()
