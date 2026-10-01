"""Bars, ticks and symbol specs, from wherever the broker's history was put.

MT5 bars are **bid** bars. Each carries `spread`, in points, which is how the ask is rebuilt:
ask = bid + spread x point. MetaTrader stores one spread per bar (the bar's lowest, on most
servers), so a bar-mode backtest charges a spread that is, if anything, too kind. Tick mode
uses every tick's real bid and ask instead (`Book.ticks`).

Sources, all returning the same frame - `ts` (epoch seconds, bar open), `open`, `high`, `low`,
`close` (bid), `volume` (tick volume) and `spread` (points):

  sqlite   the `mt5bt` database `fetch.py` writes (bars with their spread, ticks, specs)
  seqlab   the lab's `$SEQLAB/<TICKER>.<interval>.npz`; these carry no spread, so pass one
  csv      any export with those columns (MT5's own "Export bars" works once renamed)
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from till_infinity.trading.models import SymbolSpec

DB = os.environ.get("MT5BT_DB", os.path.expanduser("~/till_infinity/data/mt5bt.db"))

COLUMNS = ["ts", "open", "high", "low", "close", "volume", "spread"]
EXTRA = ["ask_open", "ask_high", "ask_low", "ask_close", "spread_mean", "spread_max"]


@dataclass
class Book:
    """One symbol's history and contract: what a run needs, and nothing it could peek at."""

    symbol: str
    bars: pd.DataFrame
    spec: SymbolSpec
    interval: str = "15m"
    #: Optional (ts_ms, bid, ask) ticks; when present, a bar touching both stop and target is
    #: resolved by which tick came first, instead of assuming the stop.
    ticks: pd.DataFrame | None = None
    #: The feed slug production uses, for swap fallbacks (`trading/swap.py`).
    feed: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.bars = enrich(clean(self.bars), self.spec)
        if not self.feed:
            self.feed = self.symbol.lower()


def enrich(df: pd.DataFrame, spec: SymbolSpec) -> pd.DataFrame:
    """Both sides of the book on every bar, and tick volume under its own name.

    `open..close` are the bid (MT5's convention). `ask_open..ask_close` add the bar's spread,
    which is exact for bars built from ticks (`bars_from_ticks` keeps both sides) and an
    approximation for MT5 bars, which carry one spread a bar. `spread` stays in points,
    `spread_price` is the same in price, `mid_*` halfway between. `tick_volume` is MT5's tick
    count (`volume`), the only volume a CFD has.
    """
    df = df.copy()
    sp = df["spread"].to_numpy(float) * spec.point
    df["spread_price"] = sp
    for k in ("open", "high", "low", "close"):
        if f"ask_{k}" not in df or df[f"ask_{k}"].isna().all():
            df[f"ask_{k}"] = df[k] + sp
        df[f"mid_{k}"] = (df[k] + df[f"ask_{k}"]) / 2
    df["tick_volume"] = df["volume"]
    return df


def bars_from_ticks(ticks: pd.DataFrame, interval: str, spec: SymbolSpec) -> pd.DataFrame:
    """Bars from (ts_ms, bid, ask) ticks with both sides kept: bid OHLC, ask OHLC, the spread's
    min (MT5's convention, in `spread`), mean and max in points, and the tick count."""
    from .engine import SECONDS

    t = ticks.copy()
    t["ts"] = (t["ts_ms"] // 1000 // SECONDS[interval]) * SECONDS[interval]
    t["sp"] = (t["ask"] - t["bid"]) / spec.point
    g = t.groupby("ts")
    out = pd.DataFrame({
        "open": g["bid"].first(), "high": g["bid"].max(), "low": g["bid"].min(),
        "close": g["bid"].last(),
        "ask_open": g["ask"].first(), "ask_high": g["ask"].max(), "ask_low": g["ask"].min(),
        "ask_close": g["ask"].last(),
        "spread": g["sp"].min(), "spread_mean": g["sp"].mean(), "spread_max": g["sp"].max(),
        "volume": g["bid"].size().astype(float),
    }).reset_index()
    return out


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Oldest first, no duplicates, and every bar contains its own open and close."""
    missing = [c for c in ("ts", "open", "high", "low", "close") if c not in df]
    if missing:
        raise ValueError(f"bars are missing {missing}")
    df = df.copy()
    if "volume" not in df:
        df["volume"] = 0.0
    if "spread" not in df:
        df["spread"] = np.nan
    df = df[COLUMNS + [c for c in EXTRA if c in df]].drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df["ts"] = df["ts"].astype(np.int64)
    if df["ts"].max() > 1e11:  # milliseconds
        df["ts"] = df["ts"] // 1000
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


def load_bars(symbol: str, interval: str, source: str = "sqlite", path: str | None = None,
              start: str | None = None, end: str | None = None) -> pd.DataFrame:
    if source == "sqlite":
        conn = sqlite3.connect(path or DB)
        df = pd.read_sql_query(
            "SELECT ts, open, high, low, close, volume, spread FROM bars"
            " WHERE symbol = ? AND interval = ? ORDER BY ts", conn, params=(symbol, interval))
        conn.close()
    elif source == "seqlab":
        root = Path(path or os.environ.get("SEQLAB", ".data/seqlab"))
        z = np.load(root / f"{symbol}.{interval}.npz")
        df = pd.DataFrame({"ts": z["time"], "open": z["open"], "high": z["high"], "low": z["low"],
                           "close": z["close"], "volume": z["volume"]})
    elif source == "csv":
        df = pd.read_csv(path or f"{symbol}.{interval}.csv")
        if "ts" not in df and "time" in df:
            df["ts"] = pd.to_datetime(df["time"], utc=True).astype("int64") // 10**9
    else:
        raise ValueError(f"unknown source {source!r}")
    if df.empty:
        raise ValueError(f"no bars for {symbol} {interval} from {source}")
    df = clean(df)
    if start:
        df = df[df["ts"] >= pd.Timestamp(start, tz="UTC").timestamp()]
    if end:
        df = df[df["ts"] < pd.Timestamp(end, tz="UTC").timestamp()]
    return df.reset_index(drop=True)


def load_ticks(symbol: str, start: float, end: float, path: str | None = None) -> pd.DataFrame:
    """Ticks in [start, end) epoch seconds, as `ts_ms`, `bid`, `ask`."""
    conn = sqlite3.connect(path or DB)
    df = pd.read_sql_query(
        "SELECT ts_ms, bid, ask FROM ticks WHERE symbol = ? AND ts_ms >= ? AND ts_ms < ?"
        " ORDER BY ts_ms", conn, params=(symbol, int(start * 1000), int(end * 1000)))
    conn.close()
    return df


def load_specs(path: str | None = None) -> dict[str, SymbolSpec]:
    """Specs saved by `fetch.py specs` (the broker's own symbol info, parsed as production does)."""
    if path and path.endswith(".json"):
        raw = json.loads(Path(path).read_text())
    else:
        conn = sqlite3.connect(path or DB)
        raw = {s: json.loads(j) for s, j in conn.execute("SELECT symbol, spec FROM specs")}
        conn.close()
    return {s: SymbolSpec(**v) for s, v in raw.items()}


#: Contracts for the walks and the tests, shaped like this broker's. Real runs use the broker's
#: own specs; these exist so the engine can be checked where the truth is known.
EXAMPLE_SPECS = {
    "EURUSD": SymbolSpec(symbol="EURUSD", digits=5, point=1e-5, tick_size=1e-5, tick_value=1.0,
                         volume_min=0.01, volume_step=0.01, contract_size=100_000,
                         swap_long=-9.7, swap_short=4.2, swap_mode=1, swap_triple_day=3),
    "XAUUSD": SymbolSpec(symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01, tick_value=1.0,
                         volume_min=0.01, volume_step=0.01, contract_size=100,
                         swap_long=-55.0, swap_short=30.0, swap_mode=1, swap_triple_day=3),
    "US 500": SymbolSpec(symbol="US 500", digits=2, point=0.01, tick_size=0.01, tick_value=0.01,
                         volume_min=0.1, volume_step=0.1, contract_size=1,
                         swap_long=-6.0, swap_short=-2.0, swap_mode=5, swap_triple_day=5),
}
