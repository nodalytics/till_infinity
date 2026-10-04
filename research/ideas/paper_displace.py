"""Paper log for the one turn result that passed: DISPLACE_C at a 12-bar low, structure exit.

`turn_confirm_rule.json` passed on 58 fresh coins (+0.049R, 4h and 1d). This logs the signal forward,
as it would have been seen live, on those coins and the second replication's 73 (`SET_C`), so the
result can be judged on bars that did not exist when it was found. Prices come from Bybit's public
klines (bytick.com) on this machine, or with SOURCE=binance from Binance spot and OKX on the research
machine, which cannot reach Bybit.

  MODE=once   check the last closed 4h (and, at 00:00 UTC, 1d) bar of every coin; append new signals
  MODE=loop   the same after every 4h close, forever (nohup it; it stops when this machine sleeps)
  MODE=score  re-fetch each logged signal's bars and trade it as `turn_trade.trades_exits` does
              (entry at the next open, stop 0.1 ATR beyond the 3-bar extreme, E2 and E1, 10 days)

  OUT=.data/paper python research/ideas/paper_displace.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import turn_confirm as C  # noqa: E402
import turn_trade as TT  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/paper"))
LOG = OUT / "displace_signals.csv"
API = "https://api.bytick.com/v5/market/kline"
IV = {"4h": ("240", 14400), "1d": ("D", 86400)}
COINS = tuple(dict.fromkeys(C.FRESH + tuple(C.SET_C)))
LOOKBACK = 300
CATCH_UP = 3  # also check the bars before the last closed one, in case a run was missed


SOURCE = os.environ.get("SOURCE", "bybit")  # "binance" on the research machine (Bybit is blocked there)
SPOT = "https://data-api.binance.vision/api/v3/klines"
OKX = "https://www.okx.com/api/v5/market/candles"
SPOT_NAME = {"1000LUNC": "LUNC", "1000XEC": "XEC", "1000SHIB": "SHIB", "LUNA2": "LUNA"}
SPOT_IV = {"4h": "4h", "1d": "1d"}
OKX_IV = {"4h": "4H", "1d": "1Dutc"}


def _get(client, url, params):
    for _ in range(3):
        try:
            r = client.get(url, params=params, timeout=20)
            return r.json() if r.status_code == 200 else None
        except Exception:  # noqa: BLE001 - a flaky public endpoint; retry, then skip the coin
            time.sleep(2)
    return None


def _frame(rows, sec):
    if not rows:
        return None
    d = pd.DataFrame([x[:6] for x in rows], columns=["ts", "open", "high", "low", "close", "volume"]).astype(float)
    d["ts"] = (d["ts"] // 1000).astype(np.int64)
    d = d.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    return d[d["ts"] + sec <= time.time()].reset_index(drop=True)


def klines(client, coin, iv, start=None, limit=LOOKBACK):
    """Closed bars, oldest first; None if the source does not list the coin. Bybit perpetuals by default;
    with SOURCE=binance, Binance spot (its public market-data mirror; the prices track the perpetual
    within a fraction of a percent, and R is scale-free) and OKX perpetuals for coins Binance spot lacks."""
    code, sec = IV[iv]
    if SOURCE == "bybit":
        params = dict(category="linear", symbol=f"{coin}USDT", interval=code, limit=limit)
        if start is not None:
            params["start"] = int(start * 1000)
        r = _get(client, API, params)
        if not r or r.get("retCode") != 0:
            return None
        return _frame(r.get("result", {}).get("list") or [], sec)
    name = SPOT_NAME.get(coin, coin)
    params = dict(symbol=f"{name}USDT", interval=SPOT_IV[iv], limit=min(limit, 1000))
    if start is not None:
        params["startTime"] = int(start * 1000)
    r = _get(client, SPOT, params)
    if isinstance(r, list) and r:
        return _frame(r, sec)
    if start is not None:  # OKX's recent-candles endpoint has no start; it serves the last 300 bars only
        return None
    r = _get(client, OKX, dict(instId=f"{name}-USDT-SWAP", bar=OKX_IV[iv], limit=min(limit, 300)))
    if not r or r.get("code") != "0":
        return None
    return _frame(r.get("data") or [], sec)


def signals(df):
    """DISPLACE_C at a 12-bar low on the last CATCH_UP closed bars, both sides (shorts on the flipped chart)."""
    from mcfl import candles
    from mcfl.parse import flip
    out = []
    for side, frame in ((1, df), (-1, flip(df))):
        l = frame["low"].to_numpy(float)
        low3 = pd.Series(l).rolling(3).min().to_numpy()
        prior = pd.Series(l).shift(3).rolling(9).min().to_numpy()
        atr = np.asarray(candles.table(frame)["atr"], float)
        U = TT.ups(frame)
        for t in range(max(0, len(frame) - CATCH_UP), len(frame)):
            if low3[t] <= prior[t] and U["DISPLACE_C"][t] and atr[t] > 0:
                stop = low3[t] - 0.1 * atr[t]
                out.append(dict(side=side, bar_ts=int(df["ts"].iat[t]), close=float(df["close"].iat[t]),
                                atr=float(atr[t]), stop=float(side * stop)))
    return out


def once(ivs):
    import httpx
    OUT.mkdir(parents=True, exist_ok=True)
    seen = set()
    if LOG.exists():
        old = pd.read_csv(LOG)
        seen = set(zip(old["sym"], old["iv"], old["side"], old["bar_ts"]))
    new = []
    with httpx.Client() as client:
        for iv in ivs:
            for coin in COINS:
                df = klines(client, coin, iv)
                if df is None or len(df) < 100:
                    continue
                for s in signals(df):
                    if (coin, iv, s["side"], s["bar_ts"]) not in seen:
                        new.append(dict(logged_at=int(time.time()), sym=coin, iv=iv, **s,
                                        lag_s=int(time.time()) - s["bar_ts"] - IV[iv][1]))
    if new:
        pd.DataFrame(new).to_csv(LOG, mode="a", header=not LOG.exists(), index=False)
    print(f"{pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} {','.join(ivs)}: {len(new)} new signals", flush=True)


def loop():
    while True:
        now = time.time()
        nxt = (now // 14400 + 1) * 14400 + 120  # two minutes after the next 4h close
        time.sleep(max(1.0, nxt - now))
        hour = pd.Timestamp(nxt, unit="s", tz="UTC").hour
        try:
            once(("4h", "1d") if hour == 0 else ("4h",))
        except Exception as e:  # noqa: BLE001 - keep logging through a bad cycle
            print(f"cycle failed: {e!r}", flush=True)


def score():
    import httpx
    log = pd.read_csv(LOG)
    rows = []
    with httpx.Client() as client:
        for (sym, iv), g in log.groupby(["sym", "iv"]):
            sec = IV[iv][1]
            df = klines(client, sym, iv, start=g["bar_ts"].min() - 200 * sec, limit=1000)
            if df is None:
                continue
            fee_atr = TT.FEE * df["close"].to_numpy(float)
            from mcfl import candles
            from mcfl.parse import flip
            cost_atr = fee_atr / np.maximum(np.asarray(candles.table(df)["atr"], float), 1e-12)
            for side, frame in ((1, df), (-1, flip(df))):
                tr = pd.DataFrame(TT.trades_exits(frame, side, cost_atr, "paper", sym, iv))
                if not len(tr):
                    continue
                tr = tr[tr["T1"]]
                for _, s in g[g["side"] == side].iterrows():
                    hit = tr[tr["ts"] == s["bar_ts"]]
                    done = df["ts"].iat[-1] >= s["bar_ts"] + 10 * 86400
                    if len(hit):
                        rows.append(dict(sym=sym, iv=iv, side=side, bar_ts=s["bar_ts"], E2=hit["E2"].iat[0],
                                         E1=hit["E1"].iat[0], mfe=hit["E2_mfe"].iat[0], complete=done))
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "displace_scored.csv", index=False)
    if len(d):
        c = d[d["complete"]]
        print(f"{len(log)} logged, {len(d)} matched, {len(c)} complete; E2 mean {c['E2'].mean():+.3f}R, "
              f"E1 {c['E1'].mean():+.3f}R; P(>=4R) {(c['mfe'] >= 4).mean():.3f}")


def main():
    mode = os.environ.get("MODE", "once")
    if mode == "once":
        hour = pd.Timestamp.now(tz="UTC").hour
        once(("4h", "1d") if hour < 4 else ("4h",))
    else:
        {"loop": loop, "score": score}[mode]()


if __name__ == "__main__":
    main()
