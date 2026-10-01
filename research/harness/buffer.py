"""The buffer disappearing while the range stays calm: order-book and flow precursors of expansion.

research/docs/expansion.md: of 15 bar-based sensors, only the calendar adds to the expansion
alert. The best untested hypothesis needs data bars do not carry - the market's ability to absorb
pressure (depth), who is trading (count against size), and flow piling up against a trapped price.
Binance USD-M perpetuals carry all three (binance_archive.py).

Pre-registered (2026-10-01), before any run.

  universe  12 perpetuals (BTC ETH SOL BNB XRP DOGE ADA AVAX LINK LTC DOT TRX), 15m and 1h,
            2023-03 on (where depth exists); klines from 2021 for warm-up. Volume = trade count.
  base      the production alert's 16 features (compression, range, calendar, higher timeframe,
            tick volume), computed by `structures/learning/expansion.py` itself
  sensors   H1 buffer      depth_rel: log(depth within +-1% / its 30-day median); depth_slope:
                           slope of log depth over 16 bars, in its own sd; depth_asym:
                           (bid - ask) / (bid + ask) at 1%; depth5_rel the same at 5%
            H2 composition count_z, size_z (log quote volume per trade), and size_z - count_z
                           (capital against participation), each against 100 bars
            H3 flow        imb16: net taker quote volume over 16 bars / total; imb_resid: imb16
                           minus its fitted dependence on the 16-bar return (flow price has not
                           expressed), absolute values for the expansion question
            H4 positioning oi16: log change of open interest over 16 bars; oi_z; log taker
                           long/short volume ratio; log top-trader long/short ratio
  judged    held-out AUC of base + each group, both halves of each series' last 40%; a group
            counts if it adds >= 0.005 in both halves. Placebo: the same group shifted 30 days
            within its own symbol, which must not count.
  direction among compressed bars that did expand, does sign(imb16) or depth_asym call the sign
            of the 16-bar return after? AUC against 0.5, with the 30-day placebo.
  trades    only for a group that counts: the trailing bracket (energy.py B_primary) armed when
            the alert fires and the group's sensor is in its top fifth, against the alert alone;
            costs 0.05% a side (taker) and funding ignored (holds are hours).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from till_infinity.models import expansion_train as et  # noqa: E402
from till_infinity.models.shocks_train import auc  # noqa: E402
from till_infinity.prices.models import Bar  # noqa: E402

DATA = Path(os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))) / "binance"
OUT = Path(os.environ.get("OUT", ".data/buffer"))
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
           "AVAXUSDT", "LINKUSDT", "LTCUSDT", "DOTUSDT", "TRXUSDT"]
SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
FROM = pd.Timestamp(os.environ.get("FROM", "2023-03-01"), tz="UTC").timestamp()
GROUPS = {
    "H1_buffer": ["depth_rel", "depth_slope", "depth_asym", "depth5_rel"],
    "H2_composition": ["count_z", "size_z", "size_minus_count"],
    "H3_flow": ["imb16_abs", "imb_resid_abs"],
    "H4_positioning": ["oi16", "oi_z", "taker_ratio", "top_ratio"],
}


def klines(sym: str, iv: str) -> pd.DataFrame | None:
    f = DATA / f"{sym}.klines.{iv}.npz"
    if not f.exists():
        return None
    z = np.load(f)
    return pd.DataFrame({k: z[k] for k in z.files}).dropna(subset=["close"]).sort_values("time")


def resample(df: pd.DataFrame, seconds: int, how: dict) -> pd.DataFrame:
    """15m (or 5m) rows to bars of `seconds`, keyed by bar open time."""
    g = df.groupby((df["time"] // seconds) * seconds)
    return g.agg(how)


def zscore(x: pd.Series, n: int = 100) -> pd.Series:
    return (x - x.rolling(n, min_periods=30).mean()) / x.rolling(n, min_periods=30).std()


def sensors(sym: str, iv: str, k: pd.DataFrame) -> pd.DataFrame:
    sec = SECONDS[iv]
    out = pd.DataFrame(index=k["time"].astype(np.int64).to_numpy())
    close = k["close"].to_numpy()
    lc = np.log(close)
    r16 = pd.Series(lc).diff(16).to_numpy()
    sig = pd.Series(np.abs(np.diff(lc, prepend=lc[0]))).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    # H2 composition
    cnt = np.log(np.maximum(k["count"].to_numpy(float), 1))
    size = np.log(np.maximum(k["quote_volume"].to_numpy(float), 1) / np.maximum(k["count"].to_numpy(float), 1))
    out["count_z"] = zscore(pd.Series(cnt)).to_numpy()
    out["size_z"] = zscore(pd.Series(size)).to_numpy()
    out["size_minus_count"] = out["size_z"] - out["count_z"]
    # H3 flow
    q = k["quote_volume"].to_numpy(float)
    net = 2 * k["taker_buy_quote_volume"].to_numpy(float) - q
    imb16 = pd.Series(net).rolling(16).sum() / pd.Series(q).rolling(16).sum()
    out["imb16"] = imb16.to_numpy()
    out["ret16_sig"] = r16 / np.maximum(sig * 4, 1e-12)
    # H1 buffer
    bf = DATA / f"{sym}.book15m.npz"
    if bf.exists():
        z = np.load(bf)
        b = pd.DataFrame({c: z[c] for c in z.files})
        b = resample(b, sec, {c: "mean" for c in b.columns if c.endswith("_mean")})
        d1 = (b["bid1_mean"] + b["ask1_mean"]).reindex(out.index)
        d5 = (b["bid5_mean"] + b["ask5_mean"]).reindex(out.index)
        per_month = int(30 * 86400 / sec)
        ld1 = np.log(d1)
        out["depth_rel"] = (ld1 - ld1.rolling(per_month, min_periods=per_month // 4).median()).to_numpy()
        ld5 = np.log(d5)
        out["depth5_rel"] = (ld5 - ld5.rolling(per_month, min_periods=per_month // 4).median()).to_numpy()
        kx = np.arange(16) - 7.5
        sl = ld1.rolling(16).apply(lambda w: np.dot(w - w.mean(), kx) / np.dot(kx, kx), raw=True)
        out["depth_slope"] = (sl / ld1.diff().rolling(100, min_periods=30).std()).to_numpy()
        out["depth_asym"] = ((b["bid1_mean"] - b["ask1_mean"]) / (b["bid1_mean"] + b["ask1_mean"])).reindex(out.index).to_numpy()
    # H4 positioning
    mf = DATA / f"{sym}.metrics.npz"
    if mf.exists():
        z = np.load(mf)
        m = pd.DataFrame({c: z[c] for c in z.files})
        m = resample(m, sec, {"sum_open_interest": "last", "sum_taker_long_short_vol_ratio": "mean",
                              "sum_toptrader_long_short_ratio": "last"})
        # a metric stamped at t describes the window ending at t: shift one bar so a bar only
        # sees what was published by its own close
        m = m.shift(1).reindex(out.index)
        loi = np.log(m["sum_open_interest"])
        out["oi16"] = loi.diff(16).to_numpy()
        out["oi_z"] = zscore(loi, 500).to_numpy()
        out["taker_ratio"] = np.log(m["sum_taker_long_short_vol_ratio"]).to_numpy()
        out["top_ratio"] = np.log(m["sum_toptrader_long_short_ratio"]).to_numpy()
    out.index = out.index + sec  # keyed by close time, like the dataset rows
    return out


def bars_of(k: pd.DataFrame) -> list[Bar]:
    return [Bar(int(t), float(o), float(h), float(lo), float(c), float(n))
            for t, o, h, lo, c, n in zip(k["time"], k["open"], k["high"], k["low"], k["close"], k["count"], strict=True)]


def fit_auc(Xtr, ytr, Xte, yte):
    from sklearn.ensemble import HistGradientBoostingClassifier
    Xtr, Xte = Xtr.copy(), Xte.copy()
    empty = np.all(np.isnan(Xtr), axis=0)
    Xtr[:, empty], Xte[:, empty] = 0.0, 0.0
    m = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05,
                                       min_samples_leaf=200).fit(Xtr, ytr)
    return m.predict_proba(Xte)[:, 1]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    series, sens = {}, {}
    for sym in SYMBOLS:
        for iv in ("15m", "1h", "4h", "1d"):
            k = klines(sym, iv)
            if k is None or len(k) < 2000:
                continue
            series[(sym, iv)] = bars_of(k)
            if iv in ("15m", "1h"):
                sens[f"{sym}|{iv}"] = sensors(sym, iv, k)
    print(f"{len(series)} series, {len(sens)} with sensors", flush=True)
    rows = et.dataset(series, intervals=("15m", "1h"))
    when, _, x, y = rows.arrays()
    keys = np.array(rows.key)
    names = [n for g in GROUPS.values() for n in g] + ["imb16", "ret16_sig"]
    S = np.full((len(y), len(names)), np.nan)
    for key in np.unique(keys):
        m = np.flatnonzero(keys == key)
        if key in sens:
            S[m] = sens[key].reindex(when[m]).reindex(columns=names).to_numpy()
    df = pd.DataFrame(S, columns=names)
    keep = when >= FROM
    when, x, y, keys, df = when[keep], x[keep], y[keep], keys[keep], df[keep].reset_index(drop=True)
    # the flow price has not expressed: imb16 minus its fit on the 16-bar return (fit on training)
    train = np.zeros(len(y), bool)
    second = np.zeros(len(y), bool)
    for key in np.unique(keys):
        m = np.flatnonzero(keys == key)
        cut = np.quantile(when[m], 0.6)
        train[m] = when[m] < cut
        te_m = m[when[m] >= cut]
        second[te_m] = when[te_m] >= np.median(when[te_m])
    ok = train & df["imb16"].notna().to_numpy() & df["ret16_sig"].notna().to_numpy()
    beta = np.polyfit(df.loc[ok, "ret16_sig"], df.loc[ok, "imb16"], 1)
    df["imb16_abs"] = df["imb16"].abs()
    df["imb_resid_abs"] = (df["imb16"] - np.polyval(beta, df["ret16_sig"])).abs()
    te = ~train
    s2 = second[te]
    res: dict = {"rows": int(len(y)), "base_rate": round(float(y.mean()), 4),
                 "coverage": {g: round(float(df[c].notna().all(axis=1).mean()), 3) for g, c in GROUPS.items()}}

    def score(X):
        p = fit_auc(X[train], y[train], X[te], y[te])
        return dict(auc=round(auc(y[te], p), 4), first_half=round(auc(y[te][~s2], p[~s2]), 4),
                    second_half=round(auc(y[te][s2], p[s2]), 4))

    out = {"base": score(x)}
    b0 = out["base"]
    print("  base", b0, flush=True)
    rng = np.random.default_rng(5)
    for g, cols in list(GROUPS.items()) + [("all", [c for v in GROUPS.values() for c in v])]:
        X = np.column_stack([x, df[cols].to_numpy()])
        v = score(X)
        v["counts"] = bool(v["first_half"] - b0["first_half"] >= 0.005 and v["second_half"] - b0["second_half"] >= 0.005)
        # placebo: the group's values shifted 30 days within each series
        P = df[cols].copy()
        for key in np.unique(keys):
            m = np.flatnonzero(keys == key)
            iv = key.split("|")[1]
            shift = int(30 * 86400 / SECONDS[iv])
            order = m[np.argsort(when[m])]
            P.iloc[order] = df[cols].iloc[np.roll(order, shift)].to_numpy()
        pv = score(np.column_stack([x, P.to_numpy()]))
        v["placebo"] = pv
        out[g] = v
        print(f"  {g:16s} {v}", flush=True)
    res["expansion"] = out

    # direction: among compressed bars that did expand, does flow or depth asymmetry call the sign?
    direction = {}
    sym_close = {}
    for key in np.unique(keys):
        sym, iv = key.split("|")
        k = klines(sym, iv)
        sym_close[key] = pd.Series(np.log(k["close"].to_numpy()), index=k["time"].astype(np.int64).to_numpy() + SECONDS[iv])
    fwd = np.full(len(y), np.nan)
    for key in np.unique(keys):
        m = np.flatnonzero(keys == key)
        sc = sym_close[key]
        f16 = sc.shift(-16) - sc
        fwd[m] = f16.reindex(when[m]).to_numpy()
    sel = te & (y > 0.5) & ~np.isnan(fwd)
    up = (fwd[sel] > 0).astype(float)
    for col in ("imb16", "depth_asym", "taker_ratio", "oi16"):
        vals = df[col].to_numpy()[sel]
        okv = ~np.isnan(vals)
        if okv.sum() > 200:
            direction[col] = dict(n=int(okv.sum()), auc=round(auc(up[okv], vals[okv]), 4))
    res["direction_after_expansion"] = direction
    print(json.dumps(res, indent=1, default=str), flush=True)
    (OUT / "buffer.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
