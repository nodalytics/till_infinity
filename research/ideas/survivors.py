"""The crypto momentum survivors: how robust, what they cost to hold, and what they are together.

Pre-registered (2026-10-02), before any run. Universe: the 35 crypto CFDs (BTC, ETH, SOL and the
32 validation coins), daily, the broker's bars and spread floor, swap charged.

  grid    cusum_follow over drift k in {0.25, 0.5, 0.75} sigma and line h in {3, 4, 5, 6, 7} sigma;
          anomaly over z in {3, 4, 5, 6} and close position in {0.5, 0.65, 0.8}; each with
          targets 4/6/8/10/12/15/20R, the FOCuS exit and the 2-ATR trail, against its coin twin.
          Robust if most of each rule's neighbourhood around the validated setting is positive in
          both halves and above its coin - a lone good cell is a fit, a plateau is an effect
  costs   for the validated settings: holding time, swap and spread in R, how many exits are
          gaps, and the result with swap doubled
  book    the sleeves on one account (risk 0.5% a trade, compounding): cusum 10R, cusum FOCuS,
          anomaly 10R, the battery's crypto 4h CCI, and the time-series momentum book. Their
          daily-return correlation and effective number of bets, how many fire on one day, and
          the combined book at max open positions unlimited / 10 / 5, equal risk per sleeve

  OUT=... MT5BT_DB=... MODE=grid|costs|book python research/ideas/survivors.py
"""
from __future__ import annotations

import os
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "harness"))
sys.path.insert(0, str(HERE.parents[1]))

import prims as P  # noqa: E402
import run as R  # noqa: E402
import setups as S  # noqa: E402
from score import boot_p  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/survivors"))
DB = os.environ.get("MT5BT_DB")
CRYPTO = ["BTCUSD", "ETHUSD", "SOLUSD", *R.FRESH]
TARGETS = (4, 6, 8, 10, 12, 15, 20)


# ------------------------------------------------------------------------------------- the rules

def cusum(df, a, k=0.5, h=5.0):
    """Both sides of `setups.cusum_follow`, parametrised: the first bar the up (down) sum of log
    returns, drift k sigma, crosses h sigma; stop 2 ATR."""
    c = df["close"].to_numpy()
    r = np.r_[0, np.diff(np.log(np.maximum(c, 1e-12)))]
    sig = pd.Series(r).shift(30).rolling(60).std().to_numpy()
    rows = []
    for side in (1, -1):
        s, armed = 0.0, True
        x = side * r
        for i in range(100, len(df)):
            if not np.isfinite(sig[i]) or sig[i] <= 0:
                continue
            s = max(0.0, s + x[i] - k * sig[i])
            if s > h * sig[i]:
                if armed and a[i] > 0:
                    rows.append(dict(i=i, side=side, stop_px=c[i] - side * 2 * a[i]))
                armed, s = False, 0.0
            elif s == 0.0:
                armed = True
    return pd.DataFrame(rows, columns=["i", "side", "stop_px"])


def anomaly(df, a, z_th=5.0, pos_th=0.65):
    """Both sides of `setups.anomaly`, parametrised: a return beyond z_th robust sigmas of the last
    60, closing beyond pos_th of its range; stop just past the bar."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    r = pd.Series(np.r_[0, np.diff(np.log(np.maximum(c, 1e-12)))])
    med = r.shift(1).rolling(60).median()
    mad = (r - med).abs().shift(1).rolling(60).median() * 1.4826
    z = ((r - med) / mad.replace(0, np.nan)).to_numpy()
    pos = (c - l) / np.maximum(h - l, 1e-12)
    rows = []
    for i in np.flatnonzero((z >= z_th) & (pos >= pos_th)):
        if a[i] > 0:
            rows.append(dict(i=i, side=1, stop_px=l[i] - 0.1 * a[i]))
    for i in np.flatnonzero((z <= -z_th) & (pos <= 1 - pos_th)):
        if a[i] > 0:
            rows.append(dict(i=i, side=-1, stop_px=h[i] + 0.1 * a[i]))
    return pd.DataFrame(rows, columns=["i", "side", "stop_px"])


def cci4h(df, a):
    """The battery's crypto 4h CCI(20) +-100 cross, its own geometry: stop 2 ATR, trail 3 ATR, out
    on the opposite signal (`harness/ta_battery.py`)."""
    import ta_battery as tb
    sg = tb.signals(df)["cci"]
    return tb.orders(df, sg, False, 0)


def mt5_frame(raw, bars, a, exit_, min_stop, focus=None):
    raw = raw.assign(entry=np.nan, limit=0, expires=1, tag="")
    if exit_.startswith("t") and exit_[1:].isdigit():
        sig = R.to_mt5(raw, bars, a, "trail", min_stop)
        sig["trail"] = 0.0
        sig["target"] = int(exit_[1:]) * sig["stop"]
        return sig
    return R.to_mt5(raw, bars, a, exit_, min_stop, focus)


# --------------------------------------------------------------------------------------- loading

def book_for(sym, iv="1d"):
    from mt5bt import Book, Costs, load_specs
    df = R.load(sym, iv)
    spec = load_specs(DB).get(sym)
    if df is None or spec is None:
        return None
    floor = R.spread_floor(sym, spec)
    costs = Costs(spread_mult=R.SPREAD_MULT, spread_points=floor, spread_floor_points=floor)
    book = Book(sym, df, spec, iv, feed=sym.lower())
    return book, costs, 2 * floor * spec.point


def focus_of(book):
    ctx = S.Ctx(book.symbol, "crypto", book.interval, R.SEC[book.interval], book.bars)
    return (S._focus(ctx, book.bars, True)[0], S._focus(ctx, book.bars, False)[0])


# ------------------------------------------------------------------------------------------ grid

def grid_one(sym):
    got = book_for(sym)
    if got is None:
        return []
    book, costs, min_stop = got
    bars = book.bars
    a = P.atr(bars, 14)
    fz = focus_of(book)
    out = []
    specs = [("cusum", dict(k=k, h=h)) for k in (0.25, 0.5, 0.75) for h in (3, 4, 5, 6, 7)] + \
            [("anomaly", dict(z_th=z, pos_th=p)) for z in (3, 4, 5, 6) for p in (0.5, 0.65, 0.8)]
    for rule, kw in specs:
        raw = cusum(bars, a, **kw) if rule == "cusum" else anomaly(bars, a, **kw)
        if raw.empty:
            continue
        for exit_ in [f"t{t}" for t in TARGETS] + ["focus", "trail"]:
            sig = mt5_frame(raw, bars, a, exit_, min_stop, fz)
            t = R.trade(book, sig, costs)
            if t.empty:
                continue
            # the coin twin: the same fills at market with a random side, the same stop and exit
            ts = bars["ts"].to_numpy()
            j = np.searchsorted(ts, t["entry_ts"].to_numpy(), side="right") - 1
            mult = int(exit_[1:]) if exit_[1:].isdigit() else 0
            trail = R.TRAIL_ATR * a[np.clip(j - 1, 0, None)] if exit_ == "trail" else 0.0
            cs = R.coin(book, t.assign(target_d=t["stop_d"] * mult, trail_d=trail), a,
                        zlib.crc32(f"{sym}{rule}{kw}{exit_}".encode()))
            if exit_ == "focus":
                cs["hold"] = R.focus_hold(cs, *fz)
            ct = R.trade(book, cs, costs)
            rt = R.trade(book, random_time(sig, bars, a, rng_for(sym, rule, kw, exit_), fz if exit_ == "focus" else None), costs)
            for kind, x in (("real", t), ("coin", ct), ("random_time", rt)):
                if x.empty:
                    continue
                out.append(pd.DataFrame({"kind": kind, "sym": sym, "rule": rule, "params": str(kw),
                                         "exit": exit_, "R": x["R"].to_numpy(), "side": x["side"].to_numpy(),
                                         "entry_ts": x["entry_ts"].to_numpy()}))
    print(f"  grid {sym}", flush=True)
    return out


def rng_for(sym, rule, kw, exit_):
    return np.random.default_rng(zlib.crc32(f"rt{sym}{rule}{kw}{exit_}".encode()))


def random_time(sig: pd.DataFrame, bars: pd.DataFrame, a: np.ndarray, rng, focus=None) -> pd.DataFrame:
    """The null for a rule that may lean one way: each signal moved to a random bar of the same
    coin, keeping its side, its stop and target in ATR, and its exit. A long-only rule in a rising
    market beats a random-side coin by being long; it beats this only by its timing."""
    if sig.empty:
        return sig
    ok = np.flatnonzero(a[:-2] > 0)
    ok = ok[ok > 100]
    if not len(ok):
        return sig.iloc[0:0]
    out = sig.sample(frac=1.0, random_state=int(rng.integers(1 << 31))).reset_index(drop=True)
    i0 = out["i"].to_numpy(int)
    j = np.sort(rng.choice(ok, len(out), replace=len(ok) < len(out)))
    scale = a[j] / np.maximum(a[i0], 1e-12)  # each signal's geometry, in its own ATR, moved to bar j
    out["i"] = j
    for col in ("stop", "target", "trail"):
        out[col] = out[col].to_numpy() * scale
    out["entry"], out["limit"] = np.nan, 0
    if focus is not None:
        out["hold"] = R.focus_hold(out, *focus)
    return out


def grid():
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 20))) as pool:
        parts = [p for got in pool.map(grid_one, CRYPTO) for p in got]
    df = pd.concat(parts, ignore_index=True)
    df["day"] = (df["entry_ts"] // 86400).astype(int)
    rng = np.random.default_rng(3)
    rows = []
    df.to_pickle(OUT / "grid_trades.pkl.gz")
    for side_name, side_mask in (("both", None), ("long", 1), ("short", -1)):
        sub = df if side_mask is None else df[df["side"] == side_mask]
        for (rule, params, exit_), g in sub.groupby(["rule", "params", "exit"]):
            r, n_ = g[g["kind"] == "real"], g[g["kind"] == "random_time"]
            if len(r) < 30 or len(n_) < 30:
                continue
            mid = r["entry_ts"].median()
            rows.append(dict(side=side_name, rule=rule, params=params, exit=exit_, n=len(r), R=r["R"].mean(),
                             first=r.loc[r["entry_ts"] < mid, "R"].mean(),
                             second=r.loc[r["entry_ts"] >= mid, "R"].mean(),
                             random_time_R=n_["R"].mean(), coin_R=g.loc[g["kind"] == "coin", "R"].mean(),
                             p4=(r["R"] >= 4).mean(), p=boot_p(r, n_, rng, 200)))
    cells = pd.DataFrame(rows)
    cells["good"] = ((cells["first"] > 0) & (cells["second"] > 0) & (cells["R"] > cells["random_time_R"])
                     & (cells["p"] < 0.05))
    cells.to_csv(OUT / "grid.csv", index=False)
    pd.set_option("display.width", 220)
    for side_name in ("both", "long", "short"):
        for rule in ("cusum", "anomaly"):
            g = cells[(cells["rule"] == rule) & (cells["side"] == side_name)]
            if g.empty:
                continue
            print(f"\n{rule} [{side_name}]: {int(g['good'].sum())} of {len(g)} cells positive in both halves "
                  f"and beat longs/shorts taken at random times")
            print("R:\n" + g.pivot_table(index="params", columns="exit", values="R").round(2).to_string())
            print("random-time R:\n" + g.pivot_table(index="params", columns="exit", values="random_time_R").round(2).to_string())


# ----------------------------------------------------------------------------------------- costs

def costs():
    from mt5bt import run
    rows = []
    for rule, kw, exit_ in (("cusum", {}, "t10"), ("cusum", {}, "focus"), ("anomaly", {}, "t10")):
        for sym in CRYPTO:
            got = book_for(sym)
            if got is None:
                continue
            book, cst, min_stop = got
            bars = book.bars
            a = P.atr(bars, 14)
            raw = cusum(bars, a, **kw) if rule == "cusum" else anomaly(bars, a, **kw)
            if raw.empty:
                continue
            sig = mt5_frame(raw, bars, a, exit_, min_stop, focus_of(book) if exit_ == "focus" else None)
            t, _ = run(book, None, cst, equity=1e9, risk=0.001, signals={sym: sig.drop(columns=["tag"])})
            if t.empty:
                continue
            t = t.assign(rule=f"{rule} {exit_}", sym=sym)
            rows.append(t)
    t = pd.concat(rows, ignore_index=True)
    t["hold_days"] = (t["exit_ts"] - t["entry_ts"]) / 86400
    t["swap_R"] = t["swap_cost"] / t["risk_money"]
    t["spread_R"] = t["spread_cost"] / t["risk_money"]
    t["gross_R"] = t["gross"] / t["risk_money"]
    t["gap"] = t["reason"].astype(str).str.endswith("_gap")
    t["R_swap2"] = t["R"] - t["swap_R"]
    summary = t.groupby("rule").agg(n=("R", "size"), R=("R", "mean"), gross_R=("gross_R", "mean"),
                                    spread_R=("spread_R", "mean"), swap_R=("swap_R", "mean"),
                                    R_with_swap_doubled=("R_swap2", "mean"),
                                    hold_days_median=("hold_days", "median"), hold_days_p90=("hold_days", lambda x: x.quantile(0.9)),
                                    gap_exits=("gap", "mean"))
    summary.to_csv(OUT / "costs.csv")
    print(summary.round(3).to_string())
    print(t.groupby(["rule", "reason"]).size().unstack(fill_value=0).to_string())


# ------------------------------------------------------------------------------------------ book

def sleeve_trades(name, max_open):
    """One sleeve on one account across all 35 coins: compounding, 0.5% risk a trade."""
    from mt5bt import run
    books, sigs, cst = [], {}, None
    iv = "4h" if name == "cci 4h" else "1d"
    for sym in CRYPTO:
        got = book_for(sym, iv)
        if got is None:
            continue
        book, cst_, min_stop = got
        bars = book.bars
        a = P.atr(bars, 14)
        if name == "cci 4h":
            od = cci4h(bars, a)
            if od.empty:
                continue
            sig = od
        else:
            rule, exit_ = name.split()
            raw = cusum(bars, a) if rule == "cusum" else anomaly(bars, a)
            raw = raw[raw["side"] > 0]  # long only: the short side loses, with or without timing
            if raw.empty:
                continue
            sig = mt5_frame(raw, bars, a, exit_, min_stop, focus_of(book) if exit_ == "focus" else None)
            sig = sig.drop(columns=["tag"])
        books.append(book)
        sigs[sym] = sig
        cst = cst_
    # one Costs for the sleeve: each book's own floor matters most; take the median floor
    cst.spread_floor_points = cst.spread_points = 0.0
    floors = {b.symbol: book_for(b.symbol, iv)[1].spread_floor_points for b in books}
    for b in books:
        b.bars["spread"] = np.maximum(b.bars["spread"].fillna(0).to_numpy(float), floors[b.symbol])
    t, _ = run(books, None, cst, equity=100_000, risk=0.005, max_open=max_open, signals=sigs)
    return t


def daily_returns(t: pd.DataFrame) -> pd.Series:
    """A sleeve's P&L marked to market every day, as a return on the equity the trade was sized
    from. Booking each trade on its exit day hides what the book holds while it holds it, so a
    sleeve that is long crypto for weeks would look uncorrelated with crypto."""
    if t.empty:
        return pd.Series(dtype=float)
    import portfolio as PF
    from mt5bt import load_specs
    PF.DB = DB
    specs = load_specs(DB)
    px = PF.closes(sorted(t["symbol"].unique()), "1d")
    out = pd.Series(0.0, index=px.index)
    for row in t.itertuples(index=False):
        spec = specs[row.symbol]
        per_price = spec.tick_value / spec.tick_size * row.volume
        c = px[row.symbol].dropna()
        d0 = pd.Timestamp(row.entry_ts, unit="s", tz="UTC").normalize()
        d1 = pd.Timestamp(row.exit_ts, unit="s", tz="UTC").normalize()
        path = c[(c.index >= d0) & (c.index < d1)]
        marks = np.r_[row.entry, path.to_numpy(), row.exit]
        days = list(path.index) + [d1]
        pnl = row.side * np.diff(marks) * per_price
        pnl[-1] += row.net - row.side * (row.exit - row.entry) * per_price  # spread, swap, commission
        for day, v in zip(days, pnl, strict=True):
            if day in out.index:
                out[day] += v / row.equity_before
    return out


def tsmom_returns() -> pd.Series:
    import portfolio as PF
    PF.DB = DB
    px = PF.closes(CRYPTO, "1d").dropna(how="all")
    cost = PF.spread_bps(list(px.columns), px)
    rets = px.pct_change(fill_method=None)
    ens = PF.ensemble(px, (7, 14, 30, 60))
    pos = (ens * (0.10 / np.sqrt(252)) / rets.rolling(30).std()).clip(-3, 3) / px.shape[1]
    pos = pos.where(np.isfinite(pos), 0.0)
    return PF.book_returns(pos, rets, cost)


def basket_returns() -> pd.Series:
    """Equal weight long every coin, rebalanced daily: what being long crypto alone earned."""
    import portfolio as PF
    PF.DB = DB
    px = PF.closes(CRYPTO, "1d").dropna(how="all")
    return px.pct_change(fill_method=None).mean(axis=1)


def stats(r: pd.Series) -> dict:
    r = r.dropna()
    eq = (1 + r).cumprod()
    return dict(sharpe=round(float(r.mean() / r.std() * np.sqrt(365)), 3) if r.std() > 0 else np.nan,
                ann=round(float(r.mean() * 365), 4), max_dd=round(float((eq / eq.cummax() - 1).min()), 4),
                days=len(r))


def book():
    rows, rets = [], {}
    for max_open in (0, 10, 5):
        sl = {}
        for name in ("cusum t10", "cusum focus", "anomaly t10", "cci 4h"):
            t = sleeve_trades(name, max_open)
            sl[name] = daily_returns(t)
            if max_open == 0 and not t.empty:
                d = pd.to_datetime(t["entry_ts"], unit="s", utc=True).dt.normalize()
                per_day = d.value_counts()
                rows.append(dict(sleeve=name, trades=len(t), R=round(float(t["R"].mean()), 3),
                                 days_with_entries=len(per_day), max_entries_one_day=int(per_day.max()),
                                 share_of_trades_on_days_with_5plus=round(float(per_day[per_day >= 5].sum() / len(t)), 3)))
        sl["tsmom"] = tsmom_returns()
        sl["buy and hold basket"] = basket_returns()
        idx = pd.date_range(min(s.index.min() for s in sl.values() if len(s)), max(s.index.max() for s in sl.values() if len(s)), freq="D")
        M = pd.DataFrame({k: v.reindex(idx).fillna(0.0) for k, v in sl.items()})
        M = M[M.index >= "2021-01-01"]
        if max_open == 0:
            corr = M.corr().round(3)
            lam = np.linalg.eigvalsh(M.corr().to_numpy())
            print(f"\ncorrelation of daily returns (unlimited positions):\n{corr.to_string()}")
            print(f"effective number of independent sleeves: {lam.sum() ** 2 / (lam ** 2).sum():.2f} of {len(lam)}")
            # how much of each sleeve is the basket: beta and the residual's Sharpe
            b = M["buy and hold basket"]
            for k in M:
                if k == "buy and hold basket":
                    continue
                beta = float(np.cov(M[k], b)[0, 1] / b.var())
                res = M[k] - beta * b
                print(f"  {k}: beta to the basket {beta:.3f}, residual Sharpe "
                      f"{res.mean() / res.std() * np.sqrt(365):.2f} (raw {M[k].mean() / M[k].std() * np.sqrt(365):.2f})")
            corr.to_csv(OUT / "sleeve_corr.csv")
        # equal risk per sleeve: scale each to the same daily volatility, then average
        vol = M.std().replace(0, np.nan)
        trade = M.drop(columns=["buy and hold basket"])
        combo = (trade / vol[trade.columns] * vol[trade.columns].mean()).mean(axis=1)
        for k in M:
            rows.append(dict(sleeve=k, max_open=max_open, **stats(M[k])))
        rows.append(dict(sleeve="combined, equal risk", max_open=max_open, **stats(combo)))
        rets[max_open] = combo
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "book.csv", index=False)
    print(out.to_string(index=False))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    mode = os.environ.get("MODE", "grid")
    {"grid": grid, "costs": costs, "book": book}[mode]()


if __name__ == "__main__":
    main()
