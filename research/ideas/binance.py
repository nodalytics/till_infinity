"""The crypto survivors replicated on Binance USD-M perpetuals: another venue, another feed, real funding.

Pre-registered (2026-10-02), before any run. Everything in survivors.py was measured on one broker's
CFD bars with its spread and swap. Here the same rules are traded on Binance's own daily candles
(data.binance.vision), paying a taker fee and slippage on each side and the actual 8-hourly funding.
Delisted contracts are kept for as long as they traded, so the universe is not only the winners.

  sets     A  the coins the CFD study used (34 of the 35 - MLN has no perpetual): a replication
           B  36 perpetuals no idea here was built, scored or validated on: a fresh test
  costs    0.05% taker + 0.02% slippage a side; funding paid or received at each settlement held
  tsmom    the book exactly as portfolio.py builds it (sign ensemble of 7/14/30/60-day returns, 10%
           volatility target per coin, cap 3), daily, net of fees on turnover and funding. Judged
           by portfolio.judge: positive in both halves and above 95% of random-sign books. Also its
           beta to the equal-weight basket of the same coins and the residual Sharpe
  cusum    long and short apart, k 0.5 / h 5 (the validated setting) with 10R target and the FOCuS
           exit, then the k x h neighbourhood at 10R; each against random-time trades (the same
           side and geometry in ATR at a random bar, 10 draws a trade). It replicates if the long
           side beats random-time longs on both sets and in both halves, with day-bootstrap p < 0.05
  fills    signal at a daily close, entry at the next open; stop 2 ATR from the signal close, gaps
           fill at the open, stop first when a bar touches both; 300-day cap; open trades on a
           contract's last bar close there

  OUT=... MODE=fetch|tsmom|cusum python research/ideas/binance.py
"""
from __future__ import annotations

import io
import os
import sys
import zipfile
import zlib
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import portfolio as PF  # noqa: E402
import prims as P  # noqa: E402
from score import boot_p  # noqa: E402
from survivors import cusum  # noqa: E402

ROOT = "https://data.binance.vision/data/futures/um/monthly"
OUT = Path(os.environ.get("OUT", ".data/binance_survivors"))
CACHE = Path(os.environ.get("CACHE", ".data/binance_perps"))
SET_A = ("BTC ETH SOL AAVE ADA ALGO APE APT AVAX BAT BCH BNB COMP DOGE DOT DASH ETC FIL IMX IOTA LINK "
         "LTC NEO NEAR SAND 1000SHIB TRU TRX UNI XLM XMR XRP XTZ ZEC").split()
SET_B = ("ATOM EOS RUNE KAVA AXS MANA GALA CRV SNX MKR LDO GRT EGLD HBAR ICP THETA VET KSM ZIL CHZ ENJ "
         "1INCH SUSHI YFI OP ARB INJ FTM MATIC QTUM ONT OMG WAVES ICX ZRX COTI").split()
FEE = 0.0005 + 0.0002
MONTHS = pd.period_range("2019-09", "2026-09", freq="M")
MAXHOLD, FOCUS_TH = 300, 12.0 + 3.0 * np.log(3600.0 / 86400)


# --------------------------------------------------------------------------------------- data

def _get(client, url):
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


def fetch_one(coin):
    sym = f"{coin}USDT"
    path = CACHE / f"{sym}.pkl"
    if path.exists():
        return
    k, f = [], []
    with httpx.Client() as client:
        for m in MONTHS:
            raw = _get(client, f"{ROOT}/klines/{sym}/1d/{sym}-1d-{m}.zip")
            if raw:
                d = pd.read_csv(io.BytesIO(raw), header=None)
                if str(d.iloc[0, 0]).startswith("open_time"):
                    d = d.iloc[1:]
                k.append(d.iloc[:, :6].astype(float).set_axis(["ts", "open", "high", "low", "close", "volume"], axis=1))
            raw = _get(client, f"{ROOT}/fundingRate/{sym}/{sym}-fundingRate-{m}.zip")
            if raw:
                d = pd.read_csv(io.BytesIO(raw))
                f.append(pd.DataFrame({"ts": d.iloc[:, 0].astype(float), "rate": d.iloc[:, -1].astype(float)}))
    if not k:
        print(f"  {sym}: no candles", flush=True)
        return
    bars = pd.concat(k).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    bars["ts"] = (bars["ts"] // 1000).astype(int)
    fund = pd.concat(f).drop_duplicates("ts").sort_values("ts") if f else pd.DataFrame(columns=["ts", "rate"])
    pd.to_pickle((bars, fund), path)
    print(f"  {sym}: {len(bars)} days, {len(fund)} fundings", flush=True)


def fetch():
    CACHE.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(fetch_one, SET_A + SET_B))


def load(coin):
    path = CACHE / f"{coin}USDT.pkl"
    if not path.exists():
        return None
    bars, fund = pd.read_pickle(path)  # our own cache, written by fetch_one
    day = pd.to_datetime(fund["ts"], unit="ms", utc=True).dt.normalize()
    daily = fund.groupby(day)["rate"].sum()  # the funding a long pays over the day (negative: receives)
    t = pd.to_datetime(bars["ts"], unit="s", utc=True)
    bars["funding"] = daily.reindex(t).fillna(0.0).to_numpy()
    return bars[bars["volume"] > 0].reset_index(drop=True)


# -------------------------------------------------------------------------------------- tsmom

def panel(coins):
    px, fd = {}, {}
    for c in coins:
        b = load(c)
        if b is None:
            continue
        t = pd.to_datetime(b["ts"], unit="s", utc=True)
        px[c] = pd.Series(b["close"].to_numpy(), index=t)
        fd[c] = pd.Series(b["funding"].to_numpy(), index=t)
    return pd.DataFrame(px).sort_index(), pd.DataFrame(fd).sort_index()


def tsmom_book(px, fund):
    rets = px.pct_change(fill_method=None)
    ens = PF.ensemble(px, (7, 14, 30, 60))
    pos = (ens * (0.10 / np.sqrt(252)) / rets.rolling(30).std()).clip(-3, 3) / px.shape[1]
    pos = pos.where(np.isfinite(pos), 0.0).where(px.notna(), 0.0)  # flat once a contract stops trading
    return pos, rets


def net(pos, rets, fund):
    cost = pd.Series(FEE, index=pos.columns)
    return PF.book_returns(pos, rets.fillna(0.0), cost) - (pos.shift(1).fillna(0.0) * fund.fillna(0.0)).sum(axis=1)


def tsmom():
    rows, rng = [], np.random.default_rng(11)
    for label, coins in (("A", SET_A), ("B", SET_B), ("A+B", SET_A + SET_B)):
        px, fund = panel(coins)
        pos, rets = tsmom_book(px, fund)
        pnl = net(pos, rets, fund)
        null = [net(pos * np.sign(rng.standard_normal(pos.shape)), rets, fund) for _ in range(200)]
        PF.judge(f"{label} tsmom ({px.shape[1]} perps)", pnl, null, 365, rows)
        basket = rets.mean(axis=1)
        x = pd.DataFrame({"b": basket, "p": pnl}).dropna()
        x = x[x.index >= x.index[0] + pd.Timedelta(days=90)]
        beta = float(np.cov(x["p"], x["b"])[0, 1] / x["b"].var())
        res = x["p"] - beta * x["b"]
        funding_paid = float((pos.shift(1).fillna(0.0) * fund.fillna(0.0)).sum(axis=1).mean() * 365)
        rows[-1].update(beta=round(beta, 3), residual_sharpe=round(float(res.mean() / res.std() * np.sqrt(365)), 3),
                        funding_per_year=round(funding_paid, 4),
                        gross_sharpe=round(PF.sharpe(PF.book_returns(pos, rets.fillna(0.0), pd.Series(0.0, index=pos.columns)), 365), 3))
        live = pnl[pnl.index >= pnl.index[0] + pd.Timedelta(days=90)]
        for year, g in live.groupby(live.index.year):
            rows.append(dict(book=f"{label} tsmom {year}", sharpe=round(PF.sharpe(g, 365), 3),
                             ann_return=round(float(g.mean() * 365), 4), days=len(g)))
        print(rows[-1], flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "tsmom.csv", index=False)
    pd.set_option("display.width", 220)
    print(out.to_string(index=False))


# -------------------------------------------------------------------------------------- cusum

def focus_fires(bars):
    c = bars["close"].to_numpy()
    r = np.r_[0, np.diff(c)]
    scale = pd.Series(r).abs().ewm(span=100).mean().shift(1).to_numpy() * np.sqrt(np.pi / 2)
    th = max(FOCUS_TH, 3.0)
    return P.focus_series(r, scale, th, True)[0], P.focus_series(r, scale, th, False)[0]


def simulate(bars, i, side, stop_d, mult, hold):
    """One trade: in at bar i+1's open; out at the stop, the target (mult R, 0 for none), or the open
    after `hold` bars; R net of fees and the funding of every day held."""
    o, h, l, c, fd = (bars[k].to_numpy() for k in ("open", "high", "low", "close", "funding"))
    n = len(bars)
    e = i + 1
    if e >= n or stop_d <= 0:
        return None
    entry = o[e]
    stop = entry - side * stop_d
    target = entry + side * mult * stop_d if mult else np.nan
    last = min(n - 1, e + MAXHOLD, i + hold if hold else n)
    out, k = None, e
    for k in range(e, last + 1):
        if k == i + hold and hold and k > e:  # the FOCuS exit: out at the open after the opposite fire
            out = o[k]
            break
        if side * (o[k] - stop) <= 0 and k > e:
            out = o[k]
            break
        if side * ((l[k] if side > 0 else h[k]) - stop) <= 0:
            out = stop
            break
        if mult and side * ((h[k] if side > 0 else l[k]) - target) >= 0:
            out = max(o[k], target) if side > 0 else min(o[k], target)
            break
    if out is None:
        out, k = c[last], last
    funding = side * float(np.sum(fd[e:k + 1] * c[e:k + 1]))  # a long pays positive funding
    pnl = side * (out - entry) - FEE * (entry + out) - funding
    return dict(R=pnl / stop_d, days=k - e + 1, funding_R=-funding / stop_d, fee_R=-FEE * (entry + out) / stop_d)


def hold_of(i, side, up, dn):
    against = dn if side > 0 else up
    j = np.searchsorted(against, i, side="right")
    return int(against[j] - i + 1) if j < len(against) else MAXHOLD


def cusum_one(coin):
    bars = load(coin)
    if bars is None or len(bars) < 200:
        return []
    a = P.atr(bars, 14)
    fu, fdn = (np.flatnonzero(x) for x in focus_fires(bars))
    rng = np.random.default_rng(zlib.crc32(coin.encode()))
    ok = np.flatnonzero(a[:-2] > 0)
    ok = ok[ok > 100]
    rows = []
    specs = [(0.5, 5.0, "t10"), (0.5, 5.0, "focus"), (0.5, 5.0, "t4")] + \
            [(k, h, "t10") for k in (0.25, 0.5, 0.75) for h in (3, 4, 5, 6, 7) if (k, h) != (0.5, 5.0)]
    for k_, h_, exit_ in specs:
        sig = cusum(bars, a, k_, h_)
        mult = int(exit_[1:]) if exit_ != "focus" else 0
        for s in sig.itertuples():
            stop_d = s.side * (bars["close"].iat[s.i] - s.stop_px)
            hold = hold_of(s.i, s.side, fu, fdn) if exit_ == "focus" else 0
            t = simulate(bars, s.i, s.side, stop_d, mult, hold)
            if t is None:
                continue
            base = dict(coin=coin, k=k_, h=h_, exit=exit_, side=s.side, ts=int(bars["ts"].iat[s.i]))
            rows.append(dict(kind="real", **base, **t))
            for _ in range(10):  # the same side and geometry in ATR, at a random bar of this coin
                j = int(rng.choice(ok))
                hold = hold_of(j, s.side, fu, fdn) if exit_ == "focus" else 0
                t = simulate(bars, j, s.side, stop_d * a[j] / a[s.i], mult, hold)
                if t is not None:
                    rows.append(dict(kind="random_time", **{**base, "ts": int(bars["ts"].iat[j])}, **t))
    print(f"  cusum {coin}: {sum(r['kind'] == 'real' for r in rows)} trades", flush=True)
    return rows


def cusum_all():
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 8))) as pool:
        got = list(pool.map(cusum_one, SET_A + SET_B))
    df = pd.DataFrame([r for g in got for r in g])
    df["set"] = np.where(df["coin"].isin(SET_A), "A", "B")
    df["day"] = df["ts"] // 86400
    df.to_pickle(OUT / "cusum_trades.pkl.gz")
    rng = np.random.default_rng(5)
    rows = []
    for (st, k_, h_, exit_, side), g in df.groupby(["set", "k", "h", "exit", "side"]):
        r, n_ = g[g["kind"] == "real"], g[g["kind"] == "random_time"]
        if len(r) < 20:
            continue
        mid = r["ts"].median()
        rows.append(dict(set=st, k=k_, h=h_, exit=exit_, side="long" if side > 0 else "short", n=len(r),
                         R=r["R"].mean(), random_time_R=n_["R"].mean(),
                         first=r.loc[r["ts"] < mid, "R"].mean(), second=r.loc[r["ts"] >= mid, "R"].mean(),
                         first_rt=n_.loc[n_["ts"] < mid, "R"].mean(), second_rt=n_.loc[n_["ts"] >= mid, "R"].mean(),
                         p4=(r["R"] >= 4).mean(), p10=(r["R"] >= 10).mean(), funding_R=r["funding_R"].mean(),
                         fee_R=r["fee_R"].mean(), days=r["days"].median(), p=boot_p(r, n_, rng, 200)))
    cells = pd.DataFrame(rows)
    cells["edge"] = cells["R"] - cells["random_time_R"]
    cells["replicates"] = ((cells["first"] > cells["first_rt"]) & (cells["second"] > cells["second_rt"])
                           & (cells["edge"] > 0) & (cells["p"] < 0.05))
    cells.to_csv(OUT / "cusum.csv", index=False)
    pd.set_option("display.width", 250)
    head = cells[(cells["k"] == 0.5) & (cells["h"] == 5.0)]
    print(head.round(3).to_string(index=False))
    nb = cells[cells["exit"] == "t10"]
    for (st, side), g in nb.groupby(["set", "side"]):
        print(f"\n{st} {side} t10 neighbourhood: beats random time in {int((g['edge'] > 0).sum())} of {len(g)} cells, "
              f"mean edge {g['edge'].mean():+.3f}R, {int(g['replicates'].sum())} replicate")
        print(g.pivot_table(index="k", columns="h", values="edge").round(2).to_string())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    {"fetch": fetch, "tsmom": tsmom, "cusum": cusum_all}[os.environ.get("MODE", "fetch")]()


if __name__ == "__main__":
    main()
