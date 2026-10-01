"""Trade *with* extreme funding: one pre-registered shot on data no earlier test saw.

research/freqtrade/README.md: fading extreme funding on Bybit (2024-01 to 2026-10) did 0.114% a
trade worse than a coin, in both halves - so the crowd paying extreme funding was, if anything,
right over the next day. That is a hypothesis, made by looking; it is tested once, here, on a venue
and a year the Bybit test never touched.

Pre-registered (2026-10-01), before any run.

  data      Binance USD-M perps from the public archive (data.binance.vision), 12 symbols, 15m
            klines and 8-hourly funding, signals in 2023 only (2022-10 on for the 90-day warm-up)
  signal    a funding stamp whose rate is in the top 5% of its own last 270 stamps (90 days):
            LONG, with the longs who pay; bottom 5%: SHORT
  trade     enter at the open of the first 15m bar starting at or after the stamp; stop 3 ATR(14)
            from entry (a bar through the stop exits there, or at the open if it gapped); exit at
            the close of bar 96 (24h). Taker fee 0.05% a side. Funding at every stamp held: a long
            pays the rate, a short receives it.
  compare   the same entries with a seeded coin for the side; and the fade side (the Bybit rule)
  counts if the with-crowd trade is net positive and beats its coin in both halves of 2023, with
            the difference's 95% interval (whole days resampled) above zero over the year
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

ROOT = "https://data.binance.vision/data/futures/um/monthly"
DATA = Path(os.environ.get("DATA", ".data/binance2023"))
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
           "AVAXUSDT", "LINKUSDT", "LTCUSDT", "DOTUSDT", "TRXUSDT"]
MONTHS = pd.period_range("2022-10", "2024-01", freq="M")  # 2024-01 so trades opened in late 2023 can finish
FEE = 0.0005
HOLD, STOP_ATR = 96, 3.0
KCOLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
         "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
RNG = np.random.default_rng(41)


def fetch(client, url: str) -> pd.DataFrame | None:
    for attempt in range(5):
        try:
            r = client.get(url, timeout=90)
            break
        except httpx.HTTPError:
            if attempt == 4:
                raise
    if r.status_code != 200:
        return None
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = z.read(z.namelist()[0])
    return pd.read_csv(io.BytesIO(raw), header=None)


def load(sym: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    kf, ff = DATA / f"{sym}.15m.csv", DATA / f"{sym}.funding.csv"
    if not kf.exists():
        with httpx.Client() as c:
            ks, fs = [], []
            for m in MONTHS:
                k = fetch(c, f"{ROOT}/klines/{sym}/15m/{sym}-15m-{m}.zip")
                if k is not None:
                    if str(k.iloc[0, 0]).startswith("open_time"):
                        k = k.iloc[1:]
                    ks.append(k.iloc[:, :12])
                f = fetch(c, f"{ROOT}/fundingRate/{sym}/{sym}-fundingRate-{m}.zip")
                if f is not None:
                    if str(f.iloc[0, 0]).startswith("calc_time"):
                        f = f.iloc[1:]
                    fs.append(f.iloc[:, :3])
        k = pd.concat(ks).set_axis(KCOLS, axis=1).apply(pd.to_numeric, errors="coerce")
        k = k.drop_duplicates("open_time").sort_values("open_time")
        f = pd.concat(fs).set_axis(["calc_time", "hours", "rate"], axis=1).apply(pd.to_numeric, errors="coerce")
        f = f.drop_duplicates("calc_time").sort_values("calc_time")
        DATA.mkdir(parents=True, exist_ok=True)
        k.to_csv(kf, index=False)
        f.to_csv(ff, index=False)
    return pd.read_csv(kf), pd.read_csv(ff)


def trades(sym: str) -> pd.DataFrame:
    k, f = load(sym)
    t = k["open_time"].to_numpy(np.int64)
    o, h, l, c = (k[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    prev = np.r_[c[0], c[:-1]]
    atr = pd.Series(np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))).rolling(14).mean().to_numpy()
    f = f.copy()
    f["pct"] = f["rate"].rolling(270, min_periods=90).rank(pct=True)
    stamp_t, stamp_r = f["calc_time"].to_numpy(np.int64), f["rate"].to_numpy(float)
    rows = []
    for st, pct, rate in zip(f["calc_time"], f["pct"], f["rate"], strict=True):
        if np.isnan(pct) or not (pct >= 0.95 or pct <= 0.05):
            continue
        when = pd.Timestamp(st, unit="ms", tz="UTC")
        if when.year != 2023:
            continue
        j = int(np.searchsorted(t, st - 1000))  # the first bar starting at/after the stamp (calc_time lags by ms)
        if j + HOLD >= len(t) or not atr[j - 1] > 0:
            continue
        crowd = 1 if pct >= 0.95 else -1  # longs pay when the rate is high: be long with them
        coin = 1 if RNG.random() < 0.5 else -1
        for label, side in (("with", crowd), ("fade", -crowd), ("coin", coin)):
            entry = o[j]
            stop = entry - side * STOP_ATR * atr[j - 1]
            exit_px, k_end = c[j + HOLD - 1], j + HOLD - 1
            for kk in range(j, j + HOLD):
                if kk > j and ((side > 0 and o[kk] <= stop) or (side < 0 and o[kk] >= stop)):
                    exit_px, k_end = o[kk], kk
                    break
                if (side > 0 and l[kk] <= stop) or (side < 0 and h[kk] >= stop):
                    exit_px, k_end = stop, kk
                    break
            gross = side * (exit_px / entry - 1)
            held = (stamp_t > t[j]) & (stamp_t <= t[k_end] + 900_000)
            funding = -side * stamp_r[held].sum()  # a long pays a positive rate
            rows.append(dict(symbol=sym, rule=label, stamp=when, side=side, gross=gross,
                             funding=funding, net=gross + funding - 2 * FEE,
                             stopped=k_end < j + HOLD - 1))
    return pd.DataFrame(rows)


def ci_days(x: pd.DataFrame, col: str) -> tuple[float, float]:
    groups = [g[col].to_numpy() for _, g in x.groupby(x["stamp"].dt.floor("D"))]
    means = [np.concatenate([groups[i] for i in RNG.integers(0, len(groups), len(groups))]).mean()
             for _ in range(2000)]
    return tuple(np.percentile(means, [2.5, 97.5]))


def main() -> None:
    with ThreadPoolExecutor(4) as pool:
        df = pd.concat(pool.map(trades, SYMBOLS), ignore_index=True)
    df["half"] = np.where(df["stamp"] < pd.Timestamp("2023-07-01", tz="UTC"), "H1", "H2")
    res = {}
    for rule, g in df.groupby("rule"):
        lo, hi = ci_days(g, "net")
        res[rule] = dict(n=len(g), net_pct=round(100 * g["net"].mean(), 4),
                         ci_pct=[round(100 * lo, 4), round(100 * hi, 4)],
                         gross_pct=round(100 * g["gross"].mean(), 4),
                         funding_pct=round(100 * g["funding"].mean(), 4),
                         H1=round(100 * g.loc[g["half"] == "H1", "net"].mean(), 4),
                         H2=round(100 * g.loc[g["half"] == "H2", "net"].mean(), 4),
                         stopped=round(float(g["stopped"].mean()), 3))
    w = df[df["rule"] == "with"].reset_index(drop=True)
    cn = df[df["rule"] == "coin"].reset_index(drop=True)
    diff = w[["stamp"]].assign(d=w["net"].to_numpy() - cn["net"].to_numpy(), half=w["half"])
    lo, hi = ci_days(diff, "d")
    res["with_minus_coin"] = dict(pct=round(100 * diff["d"].mean(), 4), ci_pct=[round(100 * lo, 4), round(100 * hi, 4)],
                                  H1=round(100 * diff.loc[diff["half"] == "H1", "d"].mean(), 4),
                                  H2=round(100 * diff.loc[diff["half"] == "H2", "d"].mean(), 4))
    W = res["with"]
    res["counts"] = bool(W["H1"] > 0 and W["H2"] > 0 and res["with_minus_coin"]["H1"] > 0
                         and res["with_minus_coin"]["H2"] > 0 and lo > 0)
    res["by_symbol_with"] = {s: round(100 * g["net"].mean(), 3) for s, g in w.groupby("symbol")}
    print(json.dumps(res, indent=1))
    (DATA / "funding_with.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
