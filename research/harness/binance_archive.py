"""Download Binance USD-M futures history from the public archive (data.binance.vision).

The API is blocked from the desk's network; the archive is not (see research/freqtrade/README.md).
For the order-book and flow study (`buffer.py`), per symbol:

  klines    15m, 1h, 4h, 1d candles with the trade count and taker-buy volume (monthly files,
            daily for the current month)
  bookDepth snapshots of cumulative depth within +-1..5% of price, about every 30 s, aggregated here
            to 15m: the mean and the last snapshot of bid and ask notional at 1%, 2% and 5%
  metrics   open interest, top-trader and global long/short ratios, taker long/short volume ratio

Writes $DATA/binance/<SYMBOL>.<what>.npz. Spaced, threaded, resumable (a symbol already written is
skipped), and run niced on the lab.
"""
from __future__ import annotations

import io
import os
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

ROOT = "https://data.binance.vision/data/futures/um"
DATA = Path(os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))) / "binance"
SYMBOLS = os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,"
                         "AVAXUSDT,LINKUSDT,LTCUSDT,DOTUSDT,TRXUSDT").split(",")
START = pd.Timestamp(os.environ.get("START", "2023-01-01"))
END = pd.Timestamp(os.environ.get("END", "2026-09-30"))
KLINE_FROM = pd.Timestamp(os.environ.get("KLINE_FROM", "2021-01-01"))
INTERVALS = ("15m", "1h", "4h", "1d")
KCOLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
         "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def get(client: httpx.Client, url: str) -> bytes | None:
    for _ in range(3):
        try:
            r = client.get(url, timeout=60)
            if r.status_code == 200:
                return r.content
            if r.status_code == 404:
                return None
        except httpx.HTTPError:
            continue
    return None


def csv_of(blob: bytes, names=None) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw), header=None if names else "infer")
    if names:
        if str(df.iloc[0, 0]).startswith("open_time"):
            df = df.iloc[1:]
        df.columns = names[: df.shape[1]]
    return df


def klines(client, sym: str, iv: str) -> pd.DataFrame:
    parts = []
    months = pd.period_range(KLINE_FROM, END, freq="M")
    for m in months[:-1]:
        blob = get(client, f"{ROOT}/monthly/klines/{sym}/{iv}/{sym}-{iv}-{m}.zip")
        if blob:
            parts.append(csv_of(blob, KCOLS))
    for d in pd.date_range(months[-1].start_time, END, freq="D"):  # the last month by day
        blob = get(client, f"{ROOT}/daily/klines/{sym}/{iv}/{sym}-{iv}-{d:%Y-%m-%d}.zip")
        if blob:
            parts.append(csv_of(blob, KCOLS))
    df = pd.concat(parts, ignore_index=True).apply(pd.to_numeric, errors="coerce")
    return df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)


def book_day(client, sym: str, day: pd.Timestamp) -> pd.DataFrame | None:
    blob = get(client, f"{ROOT}/daily/bookDepth/{sym}/{sym}-bookDepth-{day:%Y-%m-%d}.zip")
    if not blob:
        return None
    df = csv_of(blob)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df[df["percentage"].abs().isin([1, 2, 5])]
    wide = df.pivot_table(index="timestamp", columns="percentage", values="notional")
    wide.columns = [f"{'bid' if p < 0 else 'ask'}{abs(int(p))}" for p in wide.columns]
    bucket = wide.index.floor("15min")
    mean = wide.groupby(bucket).mean().add_suffix("_mean")
    last = wide.groupby(bucket).last().add_suffix("_last")
    return mean.join(last)


def metrics_day(client, sym: str, day: pd.Timestamp) -> pd.DataFrame | None:
    blob = get(client, f"{ROOT}/daily/metrics/{sym}/{sym}-metrics-{day:%Y-%m-%d}.zip")
    if not blob:
        return None
    df = csv_of(blob)
    df["create_time"] = pd.to_datetime(df["create_time"])
    return df.drop(columns=["symbol"]).set_index("create_time")


def save(path: Path, df: pd.DataFrame, time_col: str | None = None) -> None:
    out = {}
    if time_col is None:
        out["time"] = (df.index.astype("int64") // 10**9).to_numpy()
        cols = df.columns
    else:
        out["time"] = (df[time_col].to_numpy(np.int64) // 1000)
        cols = [c for c in df.columns if c not in (time_col, "close_time", "ignore")]
    for c in cols:
        out[c] = pd.to_numeric(df[c], errors="coerce").to_numpy(float)
    np.savez_compressed(path, **out)


def one(sym: str) -> None:
    with httpx.Client(headers={"User-Agent": "till-infinity-research"}) as client:
        for iv in INTERVALS:
            path = DATA / f"{sym}.klines.{iv}.npz"
            if not path.exists():
                save(path, klines(client, sym, iv), "open_time")
        days = pd.date_range(START, END, freq="D")
        for what, fn in (("book15m", book_day), ("metrics", metrics_day)):
            path = DATA / f"{sym}.{what}.npz"
            if path.exists():
                continue
            parts = [p for p in (fn(client, sym, d) for d in days) if p is not None]
            if parts:
                save(path, pd.concat(parts).sort_index())
    print(f"  {sym} done", flush=True)


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(int(os.environ.get("THREADS", "6"))) as pool:
        list(pool.map(one, SYMBOLS))
    for f in sorted(DATA.glob("*.npz")):
        z = np.load(f)
        print(f"  {f.name:32s} {len(z['time']):8d} rows")


if __name__ == "__main__":
    sys.exit(main())
