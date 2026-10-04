"""DISPLACE_C at a 12-bar low with the structure exit, on data no turn study has seen.

Frozen in `turn_confirm_rule.json` before this ran: the one positive cell of `turn_trade.py`'s exit
test (Binance 4h), re-tested on fresh Binance coins at 4h and 1d against iid and GARCH walks.

  OUT=... MT5BT_DB=... MODE=fetch|run python research/ideas/turn_confirm.py
"""
from __future__ import annotations

import io
import os
import sys
import zipfile
import zlib
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import turn_trade as TT  # noqa: E402

TT.SEC["1d"] = 86400  # the exit test's 10-day cap, in daily bars
OUT = Path(os.environ.get("OUT", ".data/turn_confirm"))
CACHE = Path(os.environ.get("CACHE", ".data/binance_fresh"))
ROOT = "https://data.binance.vision/data/futures/um/monthly"
SET_A = ("BTC ETH SOL AAVE ADA ALGO APE APT AVAX BAT BCH BNB COMP DOGE DOT DASH ETC FIL IMX IOTA LINK "
         "LTC NEO NEAR SAND 1000SHIB TRU TRX UNI XLM XMR XRP XTZ ZEC").split()
SET_B = ("ATOM EOS RUNE KAVA AXS MANA GALA CRV SNX MKR LDO GRT EGLD HBAR ICP THETA VET KSM ZIL CHZ ENJ "
         "1INCH SUSHI YFI OP ARB INJ FTM MATIC QTUM ONT OMG WAVES ICX ZRX COTI").split()
FRESH = tuple(c for c in SET_A + SET_B if c not in TT.COINS)
MONTHS = pd.period_range("2019-09", "2026-09", freq="M")
IVS = ("4h", "1d")
NS = (0.5, 1, 2, 4, 10)


def _get(client, url):
    import httpx
    for _ in range(3):
        try:
            r = client.get(url, timeout=60)
            if r.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    return z.read(z.namelist()[0])
            if r.status_code == 404:
                return None
        except httpx.HTTPError:
            continue
    return None


def fetch_one(job):
    import httpx
    coin, iv = job
    path = CACHE / f"{coin}USDT.{iv}.npz"
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
        print(f"  {sym} {iv}: no candles", flush=True)
        return
    b = pd.concat(k).drop_duplicates("ts").sort_values("ts")
    b = b[b["volume"] > 0]
    np.savez(path, ts=(b["ts"].to_numpy() // 1000).astype(np.int64),
             **{c: b[c].to_numpy(float) for c in ("open", "high", "low", "close", "volume")})
    print(f"  {sym} {iv}: {len(b)} bars", flush=True)


def fetch():
    CACHE.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(fetch_one, [(c, iv) for c in FRESH for iv in IVS]))


def load(venue, sym, iv):
    """The series and its cost per bar in price."""
    if venue == "fresh":
        path = CACHE / f"{sym}USDT.{iv}.npz"
        if not path.exists():
            return None, None
        z = np.load(path)
        df = pd.DataFrame({k: z[k] for k in ("ts", "open", "high", "low", "close", "volume")}).reset_index(drop=True)
        return df, TT.FEE * df["close"].to_numpy(float)
    if venue == "binance":
        try:
            df = TT._bin(sym, iv)
        except OSError:
            return None, None
        return df, TT.FEE * df["close"].to_numpy(float)
    import run as R
    from mt5bt import load_specs
    R.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, iv)
    if df is None:
        return None, None
    df = df.reset_index(drop=True)[["ts", "open", "high", "low", "close", "volume"]]
    spec = load_specs(R.DB).get(sym)
    return df, np.full(len(df), R.spread_floor(sym, spec) * spec.point if spec is not None else 0.0)


def one(job):
    from mcfl import candles, synth
    from mcfl.parse import flip
    venue, sym, iv, source = job
    df, fee_px = load(venue, sym, iv)
    if df is None or len(df) < 300:
        return None
    cost_atr = fee_px / np.maximum(np.asarray(candles.table(df)["atr"], float), 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    if source != "real":
        ts, n = df["ts"].to_numpy(), len(df)
        sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
        seed = zlib.crc32(f"{venue}{sym}{iv}{source}".encode()) % 100000
        gen = synth.walk if source == "walk" else synth.garch
        df = gen(n, sigma=sigma, seed=seed, steps=TT.WALK_STEPS).reset_index(drop=True).iloc[:n]
        df["ts"] = ts[:len(df)]
        df["volume"] = 0.0
        cost_atr = cost_atr[:len(df)]
    rows = []
    for side, frame in ((1, df), (-1, flip(df))):
        rows += TT.trades_exits(frame, side, cost_atr, f"{venue}:{source}", sym, iv)
    print(f"  {venue} {source} {sym} {iv}: {len(rows)}", flush=True)
    return pd.DataFrame(rows)


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("fresh", c, iv, s) for s in ("real", "walk", "garch") for iv in IVS for c in FRESH] + \
           [("binance", c, "1d", s) for s in ("real", "walk", "garch") for c in TT.COINS] + \
           [("mt5", m, "1d", s) for s in ("real", "walk", "garch") for m in TT.MT5]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 20))) as pool:
        got = [g for g in pool.map(one, jobs) if g is not None and len(g)]
    d = pd.concat(got, ignore_index=True)
    d.to_pickle(OUT / "turn_confirm.pkl.gz")
    rng = np.random.default_rng(51)
    rows = []
    for (src, iv), g in list(d.groupby(["src", "iv"])) + [((s, "4h+1d"), g) for s, g in d.groupby("src")]:
        for name in ("all 12-bar lows", "T1"):
            x = g if name == "all 12-bar lows" else g[g["T1"]]
            for ex in ("E2", "E1"):
                y = x.assign(R=x[ex])
                lo, hi = TT.boot(y, rng) if len(y) > 30 else (np.nan, np.nan)
                rows.append(dict(src=src, iv=iv, signal=name, exit=ex, n=len(y), R=y["R"].mean(), lo=lo, hi=hi,
                                 win=(y["R"] > 0).mean(), R_before=y.loc[y["ts"] < TT.SPLIT, "R"].mean(),
                                 R_after=y.loc[y["ts"] >= TT.SPLIT, "R"].mean(),
                                 **{f"P{N}R": (x[f"{ex}_mfe"] >= N).mean() for N in NS}))
    t = pd.DataFrame(rows).round(3)
    t = t[~((t["iv"] == "4h+1d") & ~t["src"].str.startswith("fresh"))]
    t.to_csv(OUT / "turn_confirm.csv", index=False)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 200)
    print(t.to_string(index=False))
    print("1/(N+1):", {N: round(1 / (N + 1), 3) for N in NS})

    def cell(src, name):
        return t[(t["src"] == src) & (t["iv"] == "4h+1d") & (t["signal"] == name) & (t["exit"] == "E2")].iloc[0]
    p, a = cell("fresh:real", "T1"), cell("fresh:real", "all 12-bar lows")
    w, gw = cell("fresh:walk", "T1"), cell("fresh:garch", "T1")
    ok = (p["R"] > 0 and p["lo"] > 0 and p["R_before"] > 0 and p["R_after"] > 0
          and p["R"] > a["R"] and p["R"] > w["R"] and p["R"] > gw["R"])
    print(f"\nPRIMARY (DISPLACE_C, E2, fresh coins 4h+1d): R {p['R']:+.3f} [{p['lo']:+.3f}, {p['hi']:+.3f}] n={p['n']}, "
          f"before {p['R_before']:+.3f}, after {p['R_after']:+.3f}; all lows {a['R']:+.3f}; walk {w['R']:+.3f}; "
          f"garch {gw['R']:+.3f} -> {'PASSES' if ok else 'fails'}")


def main():
    {"fetch": fetch, "run": run}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
