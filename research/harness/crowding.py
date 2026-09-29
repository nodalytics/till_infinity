"""Crowding and reversal: does extreme one-sided positioning precede a move against it?

"Maximum consensus = maximum fragility" (the reflexivity engine in github.com/chrisworsey55/atlas-gic,
`research/docs/atlas.md`). It is the first non-price, non-flow directional hypothesis this desk has
not already tested. Every price-based test and the order-flow test has been null.

Pre-registered, before any data was read:
  H   the more crowded a side, the worse it does next: crowding correlates NEGATIVELY with the
      forward return, and the extremes, faded, make money net of cost against a shifted null.
  and it has to hold BEYOND the past return, because positioning follows price (trend followers
  add as it moves), and "crowded" that only restates "it went up" is momentum or reversal, which is
  price.

Crypto: 10 Binance USDT-M perpetuals, hourly, 2022-01 to 2026-08 (data.binance.vision):
  funding     the last funding rate, the price longs pay shorts
  ls_global   long/short ratio of all accounts
  ls_top      long/short ratio of the top traders' positions
  oi_change   open interest, 24h change
  crowded     the mean of the four, each a z-score against its own trailing 30 days
Each is an hourly z-score against its own trailing 30 days. Forward returns run from the close of
the next hour (one hour of latency) over 8h, 1d, 3d and 7d.

FX: CFTC Commitments of Traders, weekly. Legacy report (non-commercial = speculators), 2000-2026;
the TFF report's leveraged funds 2017-2026 as a cross-check. EUR, JPY, GBP, AUD, CAD, CHF, NZD
futures against the currency's USD pair, sign-aligned so + is the currency up. Crowding is the net
position over open interest as a z-score against its trailing 156 weeks. Tuesday's report is public
on Friday, so the return starts at the first daily close at or after Friday 21:00 UTC. Horizons are
1, 4 and 13 weeks.

Run on the lab:
  PART=fetch OUT=$HOME/till_infinity/data/crowding python research/harness/crowding.py
  OUT=... SEQLAB=... python research/harness/crowding.py
"""
from __future__ import annotations

import io
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

OUT = Path(os.environ.get("OUT", ".data/crowding"))
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]
MONTHS = [str(p) for p in pd.period_range("2022-01", "2026-08", freq="M")]
DAYS = pd.date_range("2022-01-01", "2026-08-31", freq="D")
BV = "https://data.binance.vision/data/futures/um"
CFTC = "https://www.cftc.gov/files/dea/history"
FX = {  # CFTC market keyword -> (USD pair, +1 if the currency is the base)
    "EURO FX - ": ("EURUSD", 1), "JAPANESE YEN - ": ("USDJPY", -1), "BRITISH POUND": ("GBPUSD", 1),
    "AUSTRALIAN DOLLAR - ": ("AUDUSD", 1), "CANADIAN DOLLAR - ": ("USDCAD", -1),
    "SWISS FRANC - ": ("USDCHF", -1), "NEW ZEALAND DOLLAR": ("NZDUSD", 1),
}


def get(url, tries=6):
    """The file, or None if it does not exist. Transient network failures are retried with back-off:
    the first fetch died on one TLS handshake timeout in seventeen thousand requests."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=60).read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if attempt == tries - 1:
                raise
        time.sleep(2 ** attempt)


def csv_from_zip(blob, **kw):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        with z.open(z.namelist()[0]) as fh:
            return pd.read_csv(fh, **kw)


def fetch_coin(sym):
    """Hourly close, funding and metrics for one coin, one parquet-free npz."""
    k, f = [], []
    for m in MONTHS:
        b = get(f"{BV}/monthly/klines/{sym}/1h/{sym}-1h-{m}.zip")
        if b:
            d = csv_from_zip(b, header=None)
            if not str(d.iloc[0, 0]).isdigit():
                d = d.iloc[1:]
            k.append(pd.DataFrame({"t": d[0].astype(np.int64) // 1000, "close": d[4].astype(float)}))
        b = get(f"{BV}/monthly/fundingRate/{sym}/{sym}-fundingRate-{m}.zip")
        if b:
            d = csv_from_zip(b)
            f.append(pd.DataFrame({"t": d["calc_time"].astype(np.int64) // 1000, "funding": d["last_funding_rate"].astype(float)}))

    def day(dd):
        b = get(f"{BV}/daily/metrics/{sym}/{sym}-metrics-{dd:%Y-%m-%d}.zip")
        if not b:
            return None
        d = csv_from_zip(b)
        return pd.DataFrame({"t": pd.to_datetime(d["create_time"]).astype("int64") // 10**9,
                             "oi": pd.to_numeric(d["sum_open_interest_value"], errors="coerce"),
                             "ls_top": pd.to_numeric(d["sum_toptrader_long_short_ratio"], errors="coerce"),
                             "ls_global": pd.to_numeric(d["count_long_short_ratio"], errors="coerce")})
    with ThreadPoolExecutor(8) as ex:
        mets = [x for x in ex.map(day, DAYS) if x is not None]
    k = pd.concat(k).drop_duplicates("t").set_index("t").sort_index()
    f = pd.concat(f).drop_duplicates("t").set_index("t").sort_index()
    mt = pd.concat(mets).drop_duplicates("t").set_index("t").sort_index()
    # hourly: the last funding and metrics known at each hour's close
    hours = k.index.to_numpy()
    close_t = hours + 3600
    out = {"t": hours, "close": k["close"].to_numpy()}
    fi = np.searchsorted(f.index.to_numpy(), close_t, side="right") - 1
    out["funding"] = np.where(fi >= 0, f["funding"].to_numpy()[np.maximum(fi, 0)], np.nan)
    mi = np.searchsorted(mt.index.to_numpy(), close_t, side="right") - 1
    for c in ("oi", "ls_top", "ls_global"):
        out[c] = np.where(mi >= 0, mt[c].to_numpy()[np.maximum(mi, 0)], np.nan)
    np.savez_compressed(OUT / f"{sym}.npz", **out)
    print(f"{sym}: {len(hours):,} hours, funding {len(f):,}, metrics {len(mt):,} rows", flush=True)


def fetch_cftc():
    frames = []
    for y in range(2000, 2027):
        b = get(f"{CFTC}/deacot{y}.zip")
        if b:
            d = csv_from_zip(b, low_memory=False)
            frames.append(pd.DataFrame({
                "market": d["Market and Exchange Names"], "date": d["As of Date in Form YYYY-MM-DD"],
                "oi": pd.to_numeric(d["Open Interest (All)"], errors="coerce"),
                "long": pd.to_numeric(d["Noncommercial Positions-Long (All)"], errors="coerce"),
                "short": pd.to_numeric(d["Noncommercial Positions-Short (All)"], errors="coerce"), "report": "legacy"}))
    for y in range(2017, 2027):
        b = get(f"{CFTC}/fut_fin_txt_{y}.zip")
        if b:
            d = csv_from_zip(b, low_memory=False)
            frames.append(pd.DataFrame({
                "market": d["Market_and_Exchange_Names"], "date": d["Report_Date_as_YYYY-MM-DD"],
                "oi": pd.to_numeric(d["Open_Interest_All"], errors="coerce"),
                "long": pd.to_numeric(d["Lev_Money_Positions_Long_All"], errors="coerce"),
                "short": pd.to_numeric(d["Lev_Money_Positions_Short_All"], errors="coerce"), "report": "tff"}))
    d = pd.concat(frames)
    d.to_csv(OUT / "cftc.csv.gz", index=False)
    print(f"cftc: {len(d):,} rows, {d['report'].value_counts().to_dict()}", flush=True)


# ---------------------------------------------------------------------------------------------- study

COST_BPS = {"deriv": 2.4, "taker": 10.0}
RNG = np.random.default_rng(17)


def z_trailing(x, window, min_periods):
    s = pd.Series(x)
    m = s.rolling(window, min_periods=min_periods).mean().shift(1)
    sd = s.rolling(window, min_periods=min_periods).std().shift(1)
    return ((s - m) / sd).to_numpy()


def coin_panel():
    rows = []
    for sym in COINS:
        p = OUT / f"{sym}.npz"
        if not p.exists():
            continue
        z = dict(np.load(p))
        lc = np.log(z["close"])
        n = len(lc)
        W, MP = 24 * 30, 24 * 10
        feats = {
            "funding": z_trailing(z["funding"], W, MP),
            "ls_global": z_trailing(z["ls_global"], W, MP),
            "ls_top": z_trailing(z["ls_top"], W, MP),
            "oi_change": z_trailing(np.r_[np.full(24, np.nan), np.log(z["oi"][24:] / z["oi"][:-24])], W, MP),
        }
        feats["crowded"] = np.nanmean(np.column_stack(list(feats.values())), axis=1)
        past = {h: np.r_[np.full(h, np.nan), lc[h:] - lc[:-h]] for h in (24, 168)}
        fwd = {}
        for name, h in (("8h", 8), ("1d", 24), ("3d", 72), ("7d", 168)):
            a = np.arange(n) + 1  # one hour of latency
            b = a + h
            ok = b < n
            f = np.full(n, np.nan)
            f[ok] = lc[b[ok]] - lc[a[ok]]
            fwd[name] = f
        d = pd.DataFrame({"sym": sym, "t": z["t"], **feats, "past1d": past[24], "past7d": past[168],
                          **{f"f{k}": v for k, v in fwd.items()}})
        rows.append(d)
    return pd.concat(rows, ignore_index=True)


def spearman(a, b):
    from scipy import stats
    ok = np.isfinite(a) & np.isfinite(b)
    return stats.spearmanr(a[ok], b[ok]).statistic if ok.sum() > 50 else np.nan


def partial(x, y, c):
    """Rank correlation of x and y after removing c (rank-linear) from both."""
    from scipy import stats
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(c)
    rx, ry, rc = (stats.rankdata(v[ok]) for v in (x, y, c))
    ex = rx - np.polyval(np.polyfit(rc, rx, 1), rc)
    ey = ry - np.polyval(np.polyfit(rc, ry, 1), rc)
    return np.corrcoef(ex, ey)[0, 1]


def fade_trade(d, sig, fwd, step, label):
    """Fade the extremes: short when the signal is in its own trailing top decile, long in the bottom,
    per symbol, non-overlapping (one position per `step` rows per symbol); gross and net bps, halves,
    and a null that shifts each symbol's positions by one common random offset."""
    side = np.zeros(len(d))
    for sym, g in d.groupby("sym"):
        v = g[sig]
        hi = v.rolling(24 * 180, min_periods=24 * 30).quantile(0.9).shift(1)
        lo = v.rolling(24 * 180, min_periods=24 * 30).quantile(0.1).shift(1)
        side[g.index] = np.where(v >= hi, -1.0, np.where(v <= lo, 1.0, 0.0))
    d = d.assign(side=side)
    k = (d["side"] != 0) & d[fwd].notna() & ((d["t"] // 3600) % step == 0)
    r = (d.loc[k, "side"] * d.loc[k, fwd]).to_numpy() * 1e4
    mid = d["t"].quantile(0.5)
    half = d.loc[k, "t"].to_numpy() >= mid
    null = []
    for _ in range(200):
        tot = []
        for sym, g in d.groupby("sym"):
            gg = g[g[fwd].notna() & ((g["t"] // 3600) % step == 0)]
            s = np.roll(gg["side"].to_numpy(), RNG.integers(1, max(2, len(gg) - 1)))
            tot.append((s * gg[fwd].to_numpy())[s != 0])
        null.append(np.concatenate(tot).mean() * 1e4)
    null = np.array(null)
    print(f"    {label:<32} n={k.sum():>5} gross {r.mean():+7.1f}bp +- {r.std() / np.sqrt(len(r)):5.1f} "
          f"(halves {r[~half].mean():+6.1f} / {r[half].mean():+6.1f}) net {r.mean() - COST_BPS['deriv']:+7.1f} / "
          f"{r.mean() - COST_BPS['taker']:+7.1f} | shifted-null z {(r.mean() - null.mean()) / null.std():+.1f}")


def crypto():
    d = coin_panel()
    d = d.sort_values(["sym", "t"]).reset_index(drop=True)
    print(f"\n{'=' * 110}\nCROWDING, crypto: {d['sym'].nunique()} perpetuals, {len(d):,} coin-hours, "
          f"{pd.Timestamp(d['t'].min(), unit='s'):%Y-%m} to {pd.Timestamp(d['t'].max(), unit='s'):%Y-%m}")
    sub = d[(d["t"] // 3600) % 8 == 0]  # every 8th hour, to thin the overlap in the correlations
    mid = sub["t"].quantile(0.5)
    print("  rank correlation with the forward return (negative = crowding reverses); [beyond past 7d return]; halves")
    for sig in ("funding", "ls_global", "ls_top", "oi_change", "crowded", "past7d"):
        cells = []
        for h in ("8h", "1d", "3d", "7d"):
            y = sub[f"f{h}"].to_numpy()
            x = sub[sig].to_numpy()
            rho = spearman(x, y)
            part = partial(x, y, sub["past7d"].to_numpy()) if sig != "past7d" else np.nan
            h1 = spearman(x[sub["t"] < mid], y[sub["t"] < mid])
            h2 = spearman(x[sub["t"] >= mid], y[sub["t"] >= mid])
            cells.append(f"{h} {rho:+.3f} [{part:+.3f}] ({h1:+.3f}/{h2:+.3f})")
        print(f"    {sig:<10} " + " | ".join(cells))
    print(f"  n per horizon about {len(sub):,} (every 8th hour); standard error of a correlation about "
          f"{1 / np.sqrt(len(sub) / 24):.3f} after allowing for 3-day overlap")
    print("\n  fading the extremes (own trailing 10%/90% over 180 days), per coin, non-overlapping; net of Deriv / taker")
    for sig in ("funding", "ls_global", "ls_top", "crowded"):
        for fwd, step in (("f1d", 24), ("f7d", 168)):
            fade_trade(d, sig, fwd, step, f"{sig} -> {fwd[1:]}")
    # cross-section: each day, short the 3 most crowded coins, long the 3 least, hold a day
    print("\n  cross-section: daily, short the 3 most crowded by funding z, long the 3 least, hold 1 day")
    day = d[(d["t"] // 3600) % 24 == 0].dropna(subset=["funding", "f1d"])
    res = []
    for t, g in day.groupby("t"):
        if len(g) < 8:
            continue
        g = g.sort_values("funding")
        res.append((t, g["f1d"].iloc[:3].mean() - g["f1d"].iloc[-3:].mean()))
    res = pd.DataFrame(res, columns=["t", "r"])
    r = res["r"].to_numpy() * 1e4
    half = res["t"] >= res["t"].quantile(0.5)
    print(f"    days={len(r)} mean {r.mean():+.1f}bp +- {r.std() / np.sqrt(len(r)):.1f} (halves {r[~half.to_numpy()].mean():+.1f} / "
          f"{r[half.to_numpy()].mean():+.1f}), t {r.mean() / (r.std() / np.sqrt(len(r))):+.2f}; costs two round trips a day "
          f"per leg ({2 * COST_BPS['deriv']:.1f}bp at Deriv)")


def fx():
    c = pd.read_csv(OUT / "cftc.csv.gz")
    c["date"] = pd.to_datetime(c["date"])
    print(f"\n{'=' * 110}\nCROWDING, FX: CFTC positioning vs the currency's move after the report is public")
    for report, lab in (("legacy", "legacy non-commercial (speculators), 2000-2026"), ("tff", "TFF leveraged funds, 2017-2026")):
        rows = []
        for key, (pair, sign) in FX.items():
            m = c[(c["report"] == report) & c["market"].str.upper().str.contains(key.upper(), regex=False)
                  & ~c["market"].str.upper().str.contains("XRATE|/", regex=True)].sort_values("date").drop_duplicates("date")
            if len(m) < 200:
                continue
            net = ((m["long"] - m["short"]) / m["oi"]).to_numpy()
            zz = z_trailing(net, 156, 52)
            chg = z_trailing(np.r_[np.nan, np.diff(net)], 156, 52)
            px = spikerisk.load(None, pair, "SEQLAB", "1d")
            pt = pd.to_datetime(px["ts"].to_numpy(), unit="s", utc=True).tz_localize(None)
            lc = np.log(px["close"].to_numpy()) * sign
            public = m["date"] + pd.Timedelta(days=3, hours=21)  # Tuesday data, released Friday afternoon
            i0 = np.searchsorted(pt.to_numpy(), public.to_numpy())
            out = {"pair": pair, "date": m["date"].to_numpy(), "z": zz, "dz": chg}
            for h, days in (("1w", 7), ("4w", 28), ("13w", 91)):
                j = np.searchsorted(pt.to_numpy(), (public + pd.Timedelta(days=days)).to_numpy())
                ok = (i0 < len(lc)) & (j < len(lc))
                f = np.full(len(m), np.nan)
                f[ok] = lc[j[ok]] - lc[i0[ok]]
                out[h] = f
            j = np.searchsorted(pt.to_numpy(), (public - pd.Timedelta(days=91)).to_numpy())
            ok = (i0 < len(lc)) & (j >= 0) & (i0 < len(lc))
            pastr = np.full(len(m), np.nan)
            pastr[ok] = lc[np.minimum(i0[ok], len(lc) - 1)] - lc[np.maximum(j[ok], 0)]
            out["past13w"] = pastr
            rows.append(pd.DataFrame(out))
        if not rows:
            print(f"  {lab}: no markets matched")
            continue
        d = pd.concat(rows, ignore_index=True).dropna(subset=["z"])
        mid = d["date"].quantile(0.5)
        print(f"\n  {lab}: {len(d):,} currency-weeks, {d['pair'].nunique()} currencies")
        for sig in ("z", "dz", "past13w"):
            cells = []
            for h in ("1w", "4w", "13w"):
                x, y = d[sig].to_numpy(), d[h].to_numpy()
                part = partial(x, y, d["past13w"].to_numpy()) if sig != "past13w" else np.nan
                cells.append(f"{h} {spearman(x, y):+.3f} [{part:+.3f}] ({spearman(x[d['date'] < mid], y[d['date'] < mid]):+.3f}/"
                             f"{spearman(x[d['date'] >= mid], y[d['date'] >= mid]):+.3f})")
            print(f"    {('crowding z' if sig == 'z' else 'weekly change z' if sig == 'dz' else 'past 13w return'):<16} " + " | ".join(cells))
        # fade the extremes: |z| >= 1.5, non-overlapping 4-week holds per currency
        for thr in (1.5, 2.0):
            k = d[np.abs(d["z"]) >= thr].copy()
            k = k.groupby("pair", group_keys=False).apply(lambda g: g.iloc[::4])
            r = (-np.sign(k["z"]) * k["4w"]).dropna().to_numpy() * 1e4
            half = k.dropna(subset=["4w"])["date"] >= mid
            if len(r) > 10:
                print(f"    fade |z|>={thr}: n={len(r)} 4w mean {r.mean():+.0f}bp +- {r.std() / np.sqrt(len(r)):.0f} "
                      f"(halves {r[~half.to_numpy()].mean():+.0f} / {r[half.to_numpy()].mean():+.0f}), hit {np.mean(r > 0):.0%}")
        print("  (standard error of a correlation here about "
              f"{1 / np.sqrt(len(d) / 4):.3f} at 4w after allowing for overlap)")


if __name__ == "__main__":
    part = os.environ.get("PART", "study")
    if part == "fetch":
        OUT.mkdir(parents=True, exist_ok=True)
        which = os.environ.get("WHICH", "all")
        if which in ("all", "cftc"):
            fetch_cftc()
        if which in ("all", "coins"):
            for s in COINS:
                if not (OUT / f"{s}.npz").exists():
                    fetch_coin(s)
    else:
        if part in ("study", "crypto"):
            crypto()
        if part in ("study", "fx"):
            fx()
