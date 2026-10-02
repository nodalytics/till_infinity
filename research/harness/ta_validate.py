"""Validate the TA battery's survivors on instruments and data that played no part in picking them.

ta_battery.py: 15 of 323 cells survived (beat their coin after Benjamini-Hochberg, both halves
positive, net > 0, not positive on walks). 12 were crypto trend rules at 4h and 1d on three
instruments (BTC, ETH, SOL), one was stocks at 1h (sma_20_50), two were Deriv at 15m (Range Break
and Crash fill artefacts, plus Drift Switch, which ta_ticks.py tests on ticks). Choosing 15 of 323
is itself a selection, so the survivors are re-tested here, unchanged, on fresh instruments.

Pre-registered (2026-10-02), before any run.

  A crypto  the 12 crypto cells (1d: donchian55, donchian20, bb_break, cci, obv; 4h: supertrend,
            keltner, donchian55, bb_break, donchian20, cci, macd), exactly as in the battery, on
            Binance USD-M perps from the public archive, 2021-01 to 2026-09. The 9 coins outside
            BTC, ETH and SOL are the test; those three are reported apart (same coins, other venue).
            Costs: taker 0.05% a side as the spread; funding charged at every 8-hourly stamp held
            (the archive's own rates); swap off.
  B stocks  sma_20_50 at 1h on 100 stocks the battery did not use (a seeded pick of the lab's 1h
            stock files), with the broker's bar spreads and its stock-CFD spec (tick 0.01, 1-share
            lots, swap -7.4% a year; every stock fetched so far has exactly this spec).
  passes    a cell whose net R beats its coin with a day-bootstrap p < 0.05 after Benjamini-
            Hochberg across the 13 cells, positive in both halves, net > 0, on the fresh instruments
"""
from __future__ import annotations

import io
import json
import os
import sys
import zipfile
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

OUT = Path(os.environ.get("OUT", ".data/ta_validate"))
BIN = Path(os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))) / "binance"
SEQLAB = Path(os.environ.get("SEQLAB", ".data/seqlab"))
FRESH = ["BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "DOTUSDT", "TRXUSDT"]
SEEN = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
CRYPTO_CELLS = [("1d", r) for r in ("donchian55", "donchian20", "bb_break", "cci", "obv")] + \
               [("4h", r) for r in ("supertrend", "keltner", "donchian55", "bb_break", "donchian20", "cci", "macd")]
BATTERY_STOCKS = {"AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "JPM", "XOM", "AMD", "NFLX",
                  "AVGO", "COST", "LLY", "UNH", "V", "MA", "BAC", "WMT", "ORCL"}
FEE = 0.0005


def funding(sym: str) -> pd.DataFrame:
    """The archive's 8-hourly funding rates, cached."""
    f = BIN / f"{sym}.funding.csv"
    if f.exists():
        return pd.read_csv(f)
    import httpx
    parts = []
    with httpx.Client() as c:
        for m in pd.period_range("2021-01", "2026-08", freq="M"):
            for _ in range(4):
                try:
                    r = c.get(f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{m}.zip", timeout=90)
                    break
                except Exception:
                    continue
            if r.status_code != 200:
                continue
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                x = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), header=None)
            if str(x.iloc[0, 0]).startswith("calc_time"):
                x = x.iloc[1:]
            parts.append(x.iloc[:, [0, 2]])
    out = pd.concat(parts).set_axis(["ms", "rate"], axis=1).apply(pd.to_numeric, errors="coerce").dropna()
    out = out.drop_duplicates("ms").sort_values("ms")
    out.to_csv(f, index=False)
    return out


def crypto_book(sym: str, iv: str):
    from mt5bt import Book
    from till_infinity.trading.models import SymbolSpec

    z = np.load(BIN / f"{sym}.klines.{iv}.npz")
    k = pd.DataFrame({c: z[c] for c in ("time", "open", "high", "low", "close", "count")})
    k = k[(k["time"] >= pd.Timestamp("2021-01-01", tz="UTC").timestamp())].dropna()
    point = 10.0 ** np.floor(np.log10(k["close"].median()) - 5)
    spec = SymbolSpec(symbol=sym, digits=8, point=point, tick_size=point, tick_value=point,
                      volume_min=1e-6, volume_step=1e-6, volume_max=1e12, contract_size=1)
    bars = pd.DataFrame({"ts": k["time"].astype(np.int64), "open": k["open"], "high": k["high"],
                         "low": k["low"], "close": k["close"], "volume": k["count"],
                         # the taker fee, both sides, charged as one spread a round trip
                         "spread": 2 * FEE * k["close"] / point})
    return Book(sym, bars, spec, iv, feed=sym.lower())


def stock_book(path: Path):
    from mt5bt import Book, load_bars
    from till_infinity.trading.models import SymbolSpec

    sym = path.name[: -len(".1h.npz")]
    spec = SymbolSpec(symbol=sym, digits=2, point=0.01, tick_size=0.01, tick_value=0.01,
                      volume_min=1, volume_step=1, volume_max=1e9, contract_size=1,
                      swap_long=-7.4, swap_short=0.0, swap_mode=5, swap_triple_day=5)
    return Book(sym, load_bars(sym, "1h", "seqlab", str(SEQLAB)), spec, "1h", feed=sym.lower())


def trade(book, rule: str, fund: pd.DataFrame | None, swap: bool) -> list[pd.DataFrame]:
    from mt5bt import Costs, run

    sig = tb.signals(book.bars)[rule]
    mid = book.bars["ts"].iat[len(book.bars) // 2]
    out = []
    for coin in (False, True):
        od = tb.orders(book.bars, sig, coin, zlib.crc32(f"{book.symbol}{book.interval}{rule}".encode()))
        if od.empty:
            continue
        t, _ = run(book, None, Costs(swap=swap), equity=1e7, risk=0.001, one_per_symbol=True,
                   signals={book.symbol: od})
        if t.empty:
            continue
        R = t["R"].to_numpy().copy()
        if fund is not None:
            ms, rate = fund["ms"].to_numpy(), fund["rate"].to_numpy()
            csum = np.r_[0.0, np.cumsum(rate)]
            a = np.searchsorted(ms, t["entry_ts"].to_numpy() * 1000, side="right")
            b = np.searchsorted(ms, t["exit_ts"].to_numpy() * 1000, side="right")
            paid = (csum[b] - csum[a]) * t["side"].to_numpy()  # a long pays a positive rate
            R = R - paid * t["entry"].to_numpy() * t["volume"].to_numpy() / t["risk_money"].to_numpy()
        out.append(pd.DataFrame({"sym": book.symbol, "interval": book.interval, "rule": rule, "coin": coin,
                                 "R": R, "day": (t["entry_ts"] // 86400).to_numpy(),
                                 "second": (t["entry_ts"] >= mid).to_numpy()}))
    return out


def crypto_job(sym: str) -> list[pd.DataFrame]:
    fund = funding(sym)
    rows = []
    for iv, rule in CRYPTO_CELLS:
        rows += trade(crypto_book(sym, iv), rule, fund, swap=False)
    print(f"  {sym} done", flush=True)
    return rows


def stock_job(path: str) -> list[pd.DataFrame]:
    try:
        return trade(stock_book(Path(path)), "sma_20_50", None, swap=True)
    except Exception as exc:  # a malformed file is skipped, not guessed
        print(f"  skip {path}: {exc}", flush=True)
        return []


def judge(df: pd.DataFrame, rng) -> dict:
    s, c = df[~df["coin"]], df[df["coin"]]
    sd = {d: x["R"].to_numpy() for d, x in s.groupby("day")}
    cd = {d: x["R"].to_numpy() for d, x in c.groupby("day")}
    days = np.array(sorted(set(sd) | set(cd)))
    diffs = []
    for _ in range(1000):
        pick = rng.choice(days, len(days))
        a = np.concatenate([sd[d] for d in pick if d in sd] or [np.array([0.0])])
        b = np.concatenate([cd[d] for d in pick if d in cd] or [np.array([0.0])])
        diffs.append(a.mean() - b.mean())
    return dict(n=len(s), R=round(s["R"].mean(), 4), coin_R=round(c["R"].mean(), 4),
                diff=round(s["R"].mean() - c["R"].mean(), 4), p=float((np.array(diffs) <= 0).mean()),
                first=round(s.loc[~s["second"], "R"].mean(), 4), second=round(s.loc[s["second"], "R"].mean(), 4))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stocks = sorted(p for p in SEQLAB.glob("*.*.1h.npz") if p.name.split(".")[0] not in BATTERY_STOCKS)
    rng = np.random.default_rng(97)
    pick = [str(p) for p in rng.choice(stocks, min(100, len(stocks)), replace=False)]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", "32"))) as pool:
        crypto = [r for rows in pool.map(crypto_job, FRESH + SEEN) for r in rows]
        stock = [r for rows in pool.map(stock_job, pick) for r in rows]
    cr, st = pd.concat(crypto, ignore_index=True), pd.concat(stock, ignore_index=True)
    rng = np.random.default_rng(101)
    cells = []
    for (iv, rule), g in cr[cr["sym"].isin(FRESH)].groupby(["interval", "rule"]):
        cells.append(dict(test="crypto_fresh", interval=iv, rule=rule) | judge(g, rng))
    cells.append(dict(test="stocks_fresh", interval="1h", rule="sma_20_50") | judge(st, rng))
    seen = [dict(test="crypto_btc_eth_sol_binance", interval=iv, rule=rule) | judge(g, rng)
            for (iv, rule), g in cr[cr["sym"].isin(SEEN)].groupby(["interval", "rule"])]
    cells = pd.DataFrame(cells)
    m = len(cells)
    order = np.argsort(cells["p"].to_numpy())
    q = np.empty(m)
    q[order] = np.minimum.accumulate((cells["p"].to_numpy()[order] * m / np.arange(1, m + 1))[::-1])[::-1]
    cells["q"] = np.minimum(q, 1.0)
    cells["passes"] = (cells["q"] < 0.05) & (cells["first"] > 0) & (cells["second"] > 0) & (cells["R"] > 0)
    per_coin = (cr[~cr["coin"]].groupby(["interval", "rule", "sym"])["R"].mean().unstack("sym").round(3))
    res = {"cells": cells.round(4).to_dict(orient="records"), "seen_coins_on_binance": seen,
           "stocks_used": len(pick), "per_coin": per_coin.reset_index().to_dict(orient="records")}
    pd.set_option("display.width", 220)
    print(cells.round(4).to_string(index=False), flush=True)
    print(pd.DataFrame(seen).round(4).to_string(index=False), flush=True)
    (OUT / "ta_validate.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
