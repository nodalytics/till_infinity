"""TA indicator strategies on real ticks, alone and aligned with a higher candle timeframe.

ta_battery.py trades 21 textbook rules on broker bars with bar fills. This asks the same of short
candles built from real bid/ask ticks, filled on the ticks themselves, and adds the timeframe
alignment the desk asked for: take a lower-timeframe signal only when the same rule on the next
candle timeframe up points the same way.

Pre-registered (2026-10-02), before any run.

  ticks     Drift Switch Index 10 and Jump 50 Index, 2026-02-13 to 2026-10-02; EURUSD, XAUUSD,
            BTCUSD and US 500, the last 30 days (MT5 bridge, research/mt5bt/fetch.py)
  candles   1m, 5m, 15m, 1h and 4h, built from the ticks (bid OHLC, ask OHLC, tick counts)
  rules     ta_battery.py's 19 plus ema_9_21 and ema_20_50 crosses; signals at a candle's close
  variants  plain: on 1m, 5m and 15m
            aligned: the same, kept only when the rule's last signal on the candle timeframe up
            (1m -> 15m, 5m -> 1h, 15m -> 4h), as of its last *closed* candle, has the same side
  exits     stop 2 ATR, trailing 3 ATR, out on the opposite signal, 200 candles at most; every
            fill on ticks (entries at the tick's ask or bid, stops where the tick was)
  nulls     a coin twin of every cell (same entries and exits, random side)
  survives  a cell (instrument x rule x timeframe x variant) beating its coin with a day-bootstrap
            p < 0.05 after Benjamini-Hochberg across every cell, positive in both halves, net > 0
"""
from __future__ import annotations

import json
import os
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "harness"))
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT))

import ta_battery as tb  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/ta_ticks"))
INSTRUMENTS = {"Drift Switch Index 10": None, "Jump 50 Index": None,
               "EURUSD": 30, "XAUUSD": 30, "BTCUSD": 30, "US 500": 30}  # days back; None = all held
TRADE = ("1m", "5m", "15m")
UP = {"1m": "15m", "5m": "1h", "15m": "4h"}


def state(sig: pd.Series) -> pd.Series:
    """The side of the rule's last signal, carried forward."""
    return sig.replace(0, np.nan).ffill().fillna(0)


def one(sym: str) -> list[dict]:
    from mt5bt import Book, Costs, bars_from_ticks, load_specs, load_ticks, run

    db = os.environ.get("MT5BT_DB")
    spec = load_specs(db)[sym]
    days = INSTRUMENTS[sym]
    end = pd.Timestamp.now(tz="UTC").timestamp()
    start = end - days * 86400 if days else pd.Timestamp("2026-02-13", tz="UTC").timestamp()
    ticks = load_ticks(sym, start, end, db)
    ticks = ticks.dropna().drop_duplicates("ts_ms").sort_values("ts_ms").reset_index(drop=True)
    if len(ticks) < 50_000:
        print(f"  {sym}: only {len(ticks)} ticks", flush=True)
        return []
    candles = {iv: bars_from_ticks(ticks, iv, spec) for iv in ("1m", "5m", "15m", "1h", "4h")}
    rows = []
    for iv in TRADE:
        bars = candles[iv]
        book = Book(sym, bars, spec, iv, feed=sym.lower())
        book.ticks = ticks
        sigs = tb.signals(book.bars)
        up = candles[UP[iv]]
        upsig = tb.signals(Book(sym, up, spec, UP[iv], feed=sym.lower()).bars)
        # the higher candle's state as of its last *closed* candle at each lower candle's close
        close_lo = book.bars["ts"].to_numpy() + tb_seconds(iv)
        close_up = up["ts"].to_numpy() + tb_seconds(UP[iv])
        pos = np.searchsorted(close_up, close_lo, side="right") - 1
        mid = book.bars["ts"].iat[len(book.bars) // 2]
        for rule, sg in sigs.items():
            st_up = state(upsig[rule]).to_numpy()
            aligned_side = np.where(pos >= 0, st_up[np.clip(pos, 0, None)], 0)
            variants = {"plain": sg, "aligned": sg.where(sg.to_numpy() == aligned_side, 0)}
            for var, s in variants.items():
                for coin in (False, True):
                    od = tb.orders(book.bars, s, coin, zlib.crc32(f"{sym}{iv}{rule}{var}".encode()))
                    if od.empty:
                        continue
                    t, _ = run(book, None, Costs(fill="ticks"), equity=1e7, risk=0.001,
                               one_per_symbol=True, signals={sym: od})
                    if t.empty:
                        continue
                    rows.append(pd.DataFrame({"sym": sym, "interval": iv, "rule": rule, "variant": var,
                                              "coin": coin, "R": t["R"].to_numpy(),
                                              "gross": (t["gross"] / t["risk_money"]).to_numpy(),
                                              "ticks": (t["fill"] == "ticks").to_numpy(),
                                              "day": (t["entry_ts"] // 86400).to_numpy(),
                                              "second": (t["entry_ts"] >= mid).to_numpy()}))
        print(f"  {sym} {iv} done ({len(ticks):,} ticks)", flush=True)
    return rows


def tb_seconds(iv: str) -> int:
    from mt5bt.engine import SECONDS
    return SECONDS[iv]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(len(INSTRUMENTS)) as pool:
        parts = [r for rows in pool.map(one, list(INSTRUMENTS)) for r in rows]
    df = pd.concat(parts, ignore_index=True)
    df.to_pickle(OUT / "trades.pkl.gz")  # our own output
    rng = np.random.default_rng(83)
    cells = []
    for (sym, iv, rule, var), g in df.groupby(["sym", "interval", "rule", "variant"]):
        s, c = g[~g["coin"]], g[g["coin"]]
        if len(s) < 30 or len(c) < 30:
            continue
        sd = {d: x["R"].to_numpy() for d, x in s.groupby("day")}
        cd = {d: x["R"].to_numpy() for d, x in c.groupby("day")}
        days = np.array(sorted(set(sd) | set(cd)))
        diffs = []
        for _ in range(500):
            pick = rng.choice(days, len(days))
            a = np.concatenate([sd[d] for d in pick if d in sd] or [np.array([0.0])])
            b = np.concatenate([cd[d] for d in pick if d in cd] or [np.array([0.0])])
            diffs.append(a.mean() - b.mean())
        diffs = np.array(diffs)
        cells.append(dict(sym=sym, interval=iv, rule=rule, variant=var, n=len(s), R=s["R"].mean(),
                          coin_R=c["R"].mean(), diff=s["R"].mean() - c["R"].mean(),
                          p=float((diffs <= 0).mean()), first=s.loc[~s["second"], "R"].mean(),
                          second=s.loc[s["second"], "R"].mean(), gross=s["gross"].mean(),
                          tick_fills=s["ticks"].mean()))
    cells = pd.DataFrame(cells)
    m = len(cells)
    order = np.argsort(cells["p"].to_numpy())
    q = np.empty(m)
    q[order] = np.minimum.accumulate((cells["p"].to_numpy()[order] * m / np.arange(1, m + 1))[::-1])[::-1]
    cells["q"] = np.minimum(q, 1.0)
    cells["survives"] = (cells["q"] < 0.05) & (cells["first"] > 0) & (cells["second"] > 0) & (cells["R"] > 0)
    cells.to_csv(OUT / "cells.csv", index=False)
    al = cells.pivot_table(index=["sym", "interval", "rule"], columns="variant", values="diff").dropna()
    summary = {
        "cells": m, "survivors": int(cells["survives"].sum()),
        "positive_net": int((cells["R"] > 0).sum()),
        "mean_R_by_variant": cells.groupby("variant")["R"].mean().round(4).to_dict(),
        "mean_diff_by_variant": cells.groupby("variant")["diff"].mean().round(4).to_dict(),
        "aligned_beats_plain_share": round(float((al["aligned"] > al["plain"]).mean()), 3) if len(al) else None,
        "by_sym_mean_R": cells.groupby("sym")["R"].mean().round(4).to_dict(),
        "by_interval_mean_R": cells.groupby("interval")["R"].mean().round(4).to_dict(),
        "by_rule_mean_diff": cells.groupby("rule")["diff"].mean().round(4).sort_values(ascending=False).to_dict(),
        "best_cells": cells.sort_values("q").head(15).round(4).to_dict(orient="records"),
    }
    print(json.dumps(summary, indent=1, default=str), flush=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
