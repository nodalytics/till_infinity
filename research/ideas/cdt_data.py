"""Data for the crypto daily trend study (`cdt.py`): Binance USDT-perpetual klines and funding from
data.binance.vision, cached as npz/csv under DATA.

  DATA=.data/cdt/data python research/ideas/cdt_data.py            # every set the rule names
"""
from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DATA = Path(os.environ.get("DATA", ".data/cdt/data"))
ROOT = "https://data.binance.vision/data/futures/um/monthly"
MONTHS = pd.period_range("2019-09", "2026-09", freq="M")

CORE = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "TRX")
SET_A = ("BTC ETH SOL AAVE ADA ALGO APE APT AVAX BAT BCH BNB COMP DOGE DOT DASH ETC FIL IMX IOTA LINK "
         "LTC NEO NEAR SAND 1000SHIB TRU TRX UNI XLM XMR XRP XTZ ZEC").split()
SET_B = ("ATOM EOS RUNE KAVA AXS MANA GALA CRV SNX MKR LDO GRT EGLD HBAR ICP THETA VET KSM ZIL CHZ ENJ "
         "1INCH SUSHI YFI OP ARB INJ FTM MATIC QTUM ONT OMG WAVES ICX ZRX COTI").split()
SET_C = ("1000LUNC 1000XEC ALICE ALPHA ANKR API3 ARPA AR ATA BAKE BAL BAND BEL BLZ BNX C98 CELO CELR CHR CTK CTSI CVC "
         "CVX DAR DENT DGB DUSK DYDX ENS FLM FLOW FTT GMT GTC HOT IOST IOTX JASMY KLAY KNC LINA LIT LPT LRC LUNA2 MASK "
         "MTL NKN OCEAN OGN ONE PEOPLE QNT RAY REEF REN RLC ROSE RSR RVN SC SFP SKL SPELL STG STMX STORJ TLM TRB UNFI "
         "WOO XEM ZEN").split()  # turn_confirm.SET_C, copied so this module imports nothing heavy
FRESH58 = tuple(c for c in SET_A + SET_B if c not in CORE)
SETC = tuple(SET_C)
FRESH131 = FRESH58 + SETC
SETD = tuple(json.load(open(HERE / "market_mirror_rule.json"))["addendum_set_d"]["coins"])


def _get(client, url):
    import httpx
    for _ in range(4):
        try:
            r = client.get(url, timeout=60)
            if r.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    return z.read(z.namelist()[0])
            if r.status_code == 404:
                return None
        except (httpx.HTTPError, zipfile.BadZipFile):
            continue
    return None


def kpath(coin, iv):
    return DATA / "klines" / f"{coin}USDT.{iv}.npz"


def fpath(coin):
    return DATA / "funding" / f"{coin}USDT.csv"


def fetch_klines(job):
    import httpx
    coin, iv = job
    path = kpath(coin, iv)
    if path.exists():
        return
    sym, k = f"{coin}USDT", []
    with httpx.Client() as client:
        for m in MONTHS:
            raw = _get(client, f"{ROOT}/klines/{sym}/{iv}/{sym}-{iv}-{m}.zip")
            if raw:
                d = pd.read_csv(io.BytesIO(raw), header=None)
                if str(d.iloc[0, 0]).startswith("open_time"):
                    d = d.iloc[1:]
                k.append(d.iloc[:, :6].astype(float).set_axis(["ts", "open", "high", "low", "close", "volume"], axis=1))
    if not k:
        print(f"  {sym} {iv}: none", flush=True)
        return
    b = pd.concat(k).drop_duplicates("ts").sort_values("ts")
    b = b[b["volume"] > 0]
    ts = b["ts"].to_numpy()
    ts = np.where(ts > 1e14, ts // 1000, ts)  # some 2025+ files are in microseconds
    tmp = path.with_suffix(".tmp.npz")
    np.savez(tmp, ts=(ts // 1000).astype(np.int64), **{c: b[c].to_numpy(float) for c in ("open", "high", "low", "close", "volume")})
    tmp.rename(path)
    print(f"  {sym} {iv}: {len(b)} bars", flush=True)


def fetch_funding(coin):
    import httpx
    path = fpath(coin)
    if path.exists():
        return
    sym, k = f"{coin}USDT", []
    with httpx.Client() as client:
        for m in MONTHS:
            raw = _get(client, f"{ROOT}/fundingRate/{sym}/{sym}-fundingRate-{m}.zip")
            if raw:
                d = pd.read_csv(io.BytesIO(raw))
                k.append(pd.DataFrame({"ts": d.iloc[:, 0].astype(np.int64), "rate": d.iloc[:, 2].astype(float)}))
    f = pd.concat(k).drop_duplicates("ts").sort_values("ts") if k else pd.DataFrame({"ts": [], "rate": []})
    f.to_csv(path, index=False)
    print(f"  {sym} funding: {len(f)}", flush=True)


def jobs():
    j = [(c, "1d") for c in CORE + FRESH131 + SETD]
    j += [(c, iv) for iv in ("4h", "1h") for c in CORE + FRESH131]
    j += [(c, "15m") for c in CORE]
    return j


def main():
    (DATA / "klines").mkdir(parents=True, exist_ok=True)
    (DATA / "funding").mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(int(os.environ.get("THREADS", 8))) as pool:
        list(pool.map(fetch_klines, jobs()))
        list(pool.map(fetch_funding, CORE + FRESH131))
    print("fetch done", flush=True)


MT5_COST = {"BTCUSD": 2.424, "ETHUSD": 1.58, "SOLUSD": 0.14}  # run.spread_floor x point, in price (lab, 2026-10-05)
MT5_START = pd.Timestamp("2019-01-01", tz="UTC").timestamp()
MT5_SOL_15M_END = pd.Timestamp("2025-08-01", tz="UTC").timestamp()
_MT5 = {}


def load_mt5(sym, iv):
    """The broker's bars exported from the lab's mt5bt db (bars_<iv>.csv), from 2019 (the Binance sample's
    era: the fixed spread is many ATR on the 2011-2016 BTC bars); SOLUSD 15m stops at 2025-08-01."""
    if iv not in _MT5:
        f = DATA / "mt5" / f"bars_{iv}.csv"
        _MT5[iv] = pd.read_csv(f) if f.exists() else None
    a = _MT5[iv]
    if a is None:
        return None
    d = a[(a["symbol"] == sym) & (a["ts"] >= MT5_START)].drop(columns=["symbol", "spread"])
    if sym == "SOLUSD" and iv == "15m":
        d = d[d["ts"] < MT5_SOL_15M_END]
    d = d.drop_duplicates("ts").sort_values("ts")
    d = d[(d["close"] > 0) & (d["low"] > 0) & (d["high"] >= d["low"])]
    return d.reset_index(drop=True).astype({"ts": np.int64})


_ALL = {}


def mt5x_specs():
    """Symbol -> (family, point, spread floor in points) for the broker's other classes (lab export)."""
    f = DATA / "mt5" / "specs.jsonl"
    if not f.exists():
        return {}
    out = {}
    for line in f.read_text().splitlines():
        r = json.loads(line)
        if r["family"] != "crypto":
            fam = "range_break" if r["symbol"] == "Range Break 100 Index" else r["family"]
            out[r["symbol"]] = (fam, r["point"], r["floor"])
    return out


def load_mt5x(sym, iv):
    """Other classes (FX, metals, indices, energy, Deriv) from the broker's bars, every date, 1d and 4h."""
    if iv not in _ALL:
        f = DATA / "mt5" / f"all_{iv}.csv"
        _ALL[iv] = pd.read_csv(f) if f.exists() else None
    a = _ALL[iv]
    if a is None:
        return None
    d = a[a["symbol"] == sym].drop(columns=["symbol"]).drop_duplicates("ts").sort_values("ts")
    d = d[(d["close"] > 0) & (d["high"] >= d["low"])] if not sym.startswith(("Volatility", "Step", "Range", "Drift", "Jump", "Boom", "Crash")) else d[d["high"] >= d["low"]]
    return d.reset_index(drop=True).astype({"ts": np.int64}) if len(d) >= 400 else None


def mt5x_cost(sym, df):
    """run.spread_floor x point; where the floor is 0, the median bar spread (as tv_indicators)."""
    fam, point, floor = mt5x_specs()[sym]
    if not floor > 0:
        floor = float(np.nanmedian(df["spread"].to_numpy(float)))
    return floor * point


def load(coin, iv):
    """Bars (ts in seconds, open time) for one coin ('mt5:SYM' for the broker's crypto CFDs, 'mt5x:SYM'
    for its other classes), or None."""
    if coin.startswith("mt5:"):
        return load_mt5(coin[4:], iv)
    if coin.startswith("mt5x:"):
        return load_mt5x(coin[5:], iv)
    p = kpath(coin, iv)
    if not p.exists():
        return None
    z = np.load(p)
    d = pd.DataFrame({k: z[k] for k in ("ts", "open", "high", "low", "close", "volume")})
    d = d.drop_duplicates("ts").sort_values("ts")
    d = d[(d["close"] > 0) & (d["low"] > 0) & (d["high"] >= d["low"])]
    return d.reset_index(drop=True)


def funding(coin):
    """(settlement ts in seconds, rate) or None."""
    p = fpath(coin)
    if not p.exists():
        return None
    f = pd.read_csv(p)
    if not len(f):
        return None
    ts = f["ts"].to_numpy(np.int64)
    ts = np.where(ts > 1e14, ts // 1000, ts)
    return ts // 1000, f["rate"].to_numpy(float)


if __name__ == "__main__":
    main()
