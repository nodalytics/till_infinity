"""Carry and safe haven: does the interest differential pay this desk, and do the havens move first?

## Carry

The classic FX carry trade is long the high-yielding currency against the low-yielding one: it earns
the interest differential and is known for a crash-prone left tail in risk-off. The questions:

- does it pay after spread and the **broker's** financing?
- is its price component noise, or does it carry its famous crash?

Rates are FRED's OECD 3-month interbank series, `IR3TIB01{cc}M156N`, for USD, EUR, GBP, JPY, CHF,
AUD, NZD and CAD. They are monthly averages, so a month's value is used only from the first day of
the month after next, allowing for publication lag. The broker does not pay the interbank
differential: its nightly swap (MT5 `swap_long` / `swap_short`) is the differential less a markup.
The bridge serves only today's swap, so today's markup (differential minus the broker's annualised
swap, per pair and side) is measured and charged historically as a haircut on both sides. Pairs are
the lab's daily FX with both rates, from 2002-06 (JPY's series start).

- **cross-sectional:** at each month end, rank the pairs by differential (base - quote) and hold
  long the top 3 and short the bottom 3 for the month, equal weight
- **time-series:** each pair long when its differential is positive and short when negative,
  monthly
- **returns:** daily log price return plus the carry accrual over the calendar days elapsed, less
  the markup, less the spread (today's broker spread per pair) on every position change

Controls:

- **random ranking:** 500 random monthly rankings, same structure and costs
- **walks we generate:** each pair's price return replaced by iid Student-t(3) at its own daily sd,
  with the same accrual and costs, which shows what the accrual alone does

Pre-registered: carry pays if the cross-sectional portfolio's net Sharpe exceeds 0.3 in both halves
and beats the 95th percentile of random rankings.

## Safe haven

Risk-off is an S&P 500 (Yahoo `^GSPC`) daily return below -2 sd, where the sd is the prior 250 days'.
The havens are JPY (USDJPY inverted), CHF (USDCHF inverted), gold (XAUUSD) and the dollar (DXY,
Yahoo `DX-Y.NYB`). Their mean return on risk-off days is measured on the same day and the next day,
with a bootstrap CI over days, against placebo random days, in both halves.

Intraday, the bridge's `US SP 500` CFD at 1h and 15m defines shock bars (a bar return below -2 sd
of the prior 500 bars). Each haven's return is measured on the same bar and on the next bar, net of
its spread, with t clustered by day. Pre-registered: a tradeable lead-lag needs a positive net
next-bar return with t >= 3 in both halves, beating placebo bars.

Deriv's indices have no interest rate and no risk linkage by construction. They are excluded from
carry, with their broker swap reported, and checked on risk-off days, where they should read zero.

Run on the lab:
  PART=data  PYTHONPATH=repo python research/harness/carry.py   (downloads; uses the bridge)
  PART=carry ...   PART=haven ...
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

OUT = Path(os.environ.get("OUT", ".data/carry"))
PART = os.environ.get("PART", "all")
JOURNAL = os.path.expanduser(os.environ.get("JOURNAL", "~/till_infinity/data/journal.db"))
PAIRS = ["AUDJPY", "AUDUSD", "CHFJPY", "EURAUD", "EURCHF", "EURGBP", "EURJPY", "EURUSD", "GBPJPY",
         "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY"]
CCY = {"USD": "US", "EUR": "EZ", "GBP": "GB", "JPY": "JP", "CHF": "CH", "AUD": "AU", "NZD": "NZ",
       "CAD": "CA"}
DERIV = ["Volatility 75 Index", "Boom 1000 Index", "Crash 1000 Index", "Jump 50 Index", "Step Index"]
DERIV_SEQLAB = ["Volatility_75_Index", "Boom_1000_Index", "Crash_1000_Index", "Jump_50_Index",
                "Step_Index"]
START = pd.Timestamp("2002-06-01")
TOP = 3
RANDOM_DRAWS = 500
RNG = np.random.default_rng(11)


# ------------------------------------------------------------------------------------ data

def _get(url: str, tries: int = 5) -> str:
    """A download through curl: FRED answers curl in under a second and stalls Python's urllib
    until it times out, from the same machine."""
    import subprocess
    import time

    last = ""
    for attempt in range(tries):
        got = subprocess.run(["curl", "-s", "-f", "-m", "60", url], capture_output=True, text=True)
        if got.returncode == 0 and got.stdout:
            return got.stdout
        last = got.stderr or f"curl exit {got.returncode}"
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def data() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = {}
    for ccy, cc in CCY.items():
        sid = f"IR3TIB01{cc}M156N"
        text = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}")
        got = {}
        for rec in csv.reader(io.StringIO(text)):
            if len(rec) == 2 and rec[0][:2] in ("19", "20"):
                try:
                    got[rec[0]] = float(rec[1])
                except ValueError:
                    continue
        rows[ccy] = got
        print(f"  {ccy} {sid}: {len(got)} months, {min(got)} to {max(got)}", flush=True)
    (OUT / "rates.json").write_text(json.dumps(rows))

    import yfinance as yf

    for ticker, name in (("^GSPC", "spx"), ("^VIX", "vix"), ("DX-Y.NYB", "dxy")):
        d = yf.download(ticker, start="1990-01-01", interval="1d", progress=False, auto_adjust=False)
        close = d["Close"].squeeze()
        close.index = pd.to_datetime(close.index).tz_localize(None)
        close.to_csv(OUT / f"{name}.csv")
        print(f"  yahoo {ticker}: {len(close)} days", flush=True)

    from research.harness import feed

    info = {}
    for sym in PAIRS + ["XAUUSD"] + DERIV:
        try:
            i = feed._get("/symbols/info", {"symbol": sym})
            info[sym] = {k: i.get(k) for k in ("swap_long", "swap_short", "swap_mode", "point",
                                                "digits", "spread", "trade_contract_size",
                                                "currency_base", "currency_profit", "bid", "ask")}
        except Exception as exc:  # noqa: BLE001
            info[sym] = {"error": str(exc)[:80]}
    (OUT / "info.json").write_text(json.dumps(info, indent=1))
    print(f"  broker info for {len(info)} symbols", flush=True)
    for sym, iv in (("US SP 500", "1h"), ("US SP 500", "15m"), ("DXYUSD", "1h"), ("DXYUSD", "15m")):
        try:
            b = feed.bars(sym, iv, 50_000)
            pd.DataFrame(b).to_csv(OUT / f"{sym.replace(' ', '_')}.{iv}.csv", index=False)
            print(f"  bridge {sym} {iv}: {len(b)} bars", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  bridge {sym} {iv}: {exc}", flush=True)


# ------------------------------------------------------------------------------------ helpers

def daily_rates() -> pd.DataFrame:
    """Annual % per currency by calendar day, each month's value from the first of month + 2."""
    raw = json.loads((OUT / "rates.json").read_text())
    out = {}
    for ccy, got in raw.items():
        s = pd.Series(got, dtype=float)
        s.index = pd.to_datetime(s.index) + pd.offsets.MonthBegin(2)
        out[ccy] = s
    days = pd.date_range("1990-01-01", pd.Timestamp.today().normalize(), freq="D")
    return pd.DataFrame(out).reindex(days).ffill()


def closes(sym: str, interval: str = "1d") -> pd.Series:
    df = spikerisk.load(None, sym, "SEQLAB", interval)
    s = pd.Series(df["close"].to_numpy(), index=pd.to_datetime(df["ts"].to_numpy(), unit="s"))
    if interval == "1d":
        s.index = s.index.normalize()
    return s[~s.index.duplicated()]


def spread_bps(info: dict, sym: str, floor: float = 0.5) -> float:
    i = info.get(sym, {})
    try:
        price = (float(i["bid"]) + float(i["ask"])) / 2 if i.get("bid") else None
        sp = float(i["spread"]) * float(i["point"])
        if price:
            return max(sp / price * 1e4, floor)
    except (KeyError, TypeError, ValueError):
        pass
    return 1.0


def broker_carry(info: dict, sym: str, price: float) -> tuple[float, float] | None:
    """The broker's annualised % for holding long and short, from points-mode swaps."""
    i = info.get(sym, {})
    if i.get("swap_mode") != 1 or not i.get("point"):
        return None
    per_night = lambda pts: float(pts) * float(i["point"]) / price * 100 * 365  # noqa: E731
    return per_night(i["swap_long"]), per_night(i["swap_short"])


def sharpe(r: pd.Series) -> float:
    r = r.dropna()
    return float(r.mean() / r.std() * math.sqrt(252)) if len(r) > 20 and r.std() > 0 else float("nan")


def max_dd(r: pd.Series) -> float:
    eq = r.fillna(0).cumsum()
    return float((eq - eq.cummax()).min())


def describe(label: str, r: pd.Series, spx: pd.Series, riskoff: pd.Index) -> str:
    r = r.dropna()
    mid = r.index[len(r) // 2]
    h1, h2 = r[r.index < mid], r[r.index >= mid]
    monthly = r.resample("ME").sum()
    ro = r.reindex(riskoff).dropna()
    corr = r.corr(spx.reindex(r.index))
    return (f"    {label:30s} ann {r.mean() * 252 * 100:+6.2f}% vol {r.std() * math.sqrt(252) * 100:5.2f}% "
            f"Sharpe {sharpe(r):+.2f} (halves {sharpe(h1):+.2f} / {sharpe(h2):+.2f}) | maxDD "
            f"{max_dd(r) * 100:+.1f}% | skew d {r.skew():+.2f} m {monthly.skew():+.2f} | worst month "
            f"{monthly.min() * 100:+.1f}% | on {len(ro)} risk-off days {ro.mean() * 1e4:+.1f} bps | corr SPX {corr:+.2f}")


# ------------------------------------------------------------------------------------ carry

def carry() -> None:
    info = json.loads((OUT / "info.json").read_text())
    rates = daily_rates()
    spx = pd.read_csv(OUT / "spx.csv", index_col=0, parse_dates=True).squeeze().rename("spx")
    spx_r = np.log(spx).diff()
    sd = spx_r.rolling(250).std().shift(1)
    riskoff = spx_r[spx_r < -2 * sd].index

    px = pd.DataFrame({p: closes(p) for p in PAIRS}).sort_index()
    px = px[px.index >= START]
    ret = np.log(px).diff()
    gap = pd.Series(px.index, index=px.index).diff().dt.days.fillna(1)
    diff = pd.DataFrame({p: rates[p[:3]].reindex(px.index) - rates[p[3:]].reindex(px.index)
                         for p in PAIRS})  # annual %, base - quote, as known that day

    print("CARRY: rates known at each date (lagged); broker markup from today's swaps\n")
    print("  broker swap against the interbank differential, annual %, today:")
    markup = {}
    for p in PAIRS:
        last = px[p].dropna().iloc[-1]
        theo = float(diff[p].dropna().iloc[-1])
        got = broker_carry(info, p, last)
        if got is None:
            markup[p] = 1.0
            print(f"    {p}: no points-mode swap, markup assumed 1.0%")
            continue
        long_a, short_a = got
        m = ((theo - long_a) + (-theo - short_a)) / 2
        markup[p] = max(m, 0.0)
        print(f"    {p}: differential {theo:+.2f} | broker long {long_a:+.2f} short {short_a:+.2f} | "
              f"markup per side {m:+.2f} | spread {spread_bps(info, p):.2f} bps")
    for sym in DERIV + ["XAUUSD"]:
        i = info.get(sym, {})
        print(f"    {sym}: swap_long {i.get('swap_long')} swap_short {i.get('swap_short')} mode {i.get('swap_mode')}")

    cost = {p: spread_bps(info, p) / 1e4 for p in PAIRS}

    def run(positions: pd.DataFrame, price_ret: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Daily portfolio return: price + carry accrual - markup - spread on changes."""
        pos = positions.reindex(px.index).ffill().fillna(0.0)
        held = pos.shift(1).fillna(0.0)  # decided at a close, earned from the next day
        acc = held * diff / 100 * gap.to_numpy()[:, None] / 365
        mk = held.abs() * pd.Series(markup) / 100 * gap.to_numpy()[:, None] / 365
        change = pos.diff().abs().fillna(pos.abs())
        tc = change * pd.Series(cost) / 2
        n = held.abs().sum(axis=1).replace(0, np.nan)
        price = (held * price_ret).sum(axis=1) / n
        accrual = (acc - mk).sum(axis=1) / n
        costs = tc.sum(axis=1) / pos.abs().sum(axis=1).replace(0, np.nan)
        total = price.fillna(0) + accrual.fillna(0) - costs.fillna(0)
        return total, price, accrual

    month_ends = px.groupby(px.index.to_period("M")).tail(1).index

    def cross(scores: pd.DataFrame) -> pd.DataFrame:
        pos = pd.DataFrame(0.0, index=month_ends, columns=PAIRS)
        for d in month_ends:
            s = scores.loc[d].dropna()
            if len(s) < 2 * TOP:
                continue
            order = s.sort_values()
            pos.loc[d, order.index[-TOP:]] = 1.0
            pos.loc[d, order.index[:TOP]] = -1.0
        return pos

    xs_pos = cross(diff)
    ts_pos = np.sign(diff.loc[month_ends]).fillna(0.0)
    xs, xs_price, xs_acc = run(xs_pos, ret)
    ts, ts_price, ts_acc = run(ts_pos, ret)
    print(f"\n  {px.index[0].date()} to {px.index[-1].date()}, {len(PAIRS)} pairs, {len(riskoff)} S&P risk-off days in range")
    print(describe("cross-sectional, net", xs, spx_r, riskoff))
    print(describe("  price component", xs_price, spx_r, riskoff))
    print(describe("  carry accrual less markup", xs_acc, spx_r, riskoff))
    print(describe("time-series, net", ts, spx_r, riskoff))
    print(describe("  price component", ts_price, spx_r, riskoff))

    draws = []
    for _ in range(RANDOM_DRAWS):
        fake = pd.DataFrame(RNG.standard_normal(diff.loc[month_ends].shape), index=month_ends, columns=PAIRS)
        r, _, _ = run(cross(fake), ret)
        draws.append(sharpe(r))
    draws = np.array(draws)
    print(f"\n  random ranking: Sharpe median {np.nanmedian(draws):+.2f}, 95th pct {np.nanpercentile(draws, 95):+.2f}"
          f" | carry's {sharpe(xs):+.2f} beats {np.mean(draws < sharpe(xs)):.1%} of them")

    sdev = ret.std()
    walk = pd.DataFrame({p: RNG.standard_t(3, len(ret)) / math.sqrt(3) * sdev[p] for p in PAIRS},
                        index=ret.index)
    w, w_price, w_acc = run(xs_pos, walk)
    print(describe("walks, same carry and costs", w, spx_r, riskoff))
    print(describe("  walks' price component", w_price, spx_r, riskoff))

    print("\n  per pair, time-series carry (net Sharpe, halves, mean differential)")
    for p in PAIRS:
        r, _, _ = run(ts_pos[[p]].reindex(columns=PAIRS, fill_value=0.0), ret)
        mid = r.dropna().index[len(r.dropna()) // 2]
        print(f"    {p}: Sharpe {sharpe(r):+.2f} ({sharpe(r[r.index < mid]):+.2f} / {sharpe(r[r.index >= mid]):+.2f})"
              f" | mean |diff| {diff[p].abs().mean():.2f}%")


# ------------------------------------------------------------------------------------ haven

def boot(values: np.ndarray, n: int = 2000) -> tuple[float, float, float]:
    v = values[np.isfinite(values)]
    if len(v) < 5:
        return float("nan"), float("nan"), float("nan")
    means = [RNG.choice(v, len(v)).mean() for _ in range(n)]
    return float(v.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def haven() -> None:
    info = json.loads((OUT / "info.json").read_text())
    spx = pd.read_csv(OUT / "spx.csv", index_col=0, parse_dates=True).squeeze()
    dxy = pd.read_csv(OUT / "dxy.csv", index_col=0, parse_dates=True).squeeze()
    r = np.log(spx).diff()
    sd = r.rolling(250).std().shift(1)
    riskoff = r[r < -2 * sd].index
    havens = {"JPY (USDJPY inverted)": -np.log(closes("USDJPY")).diff(),
              "CHF (USDCHF inverted)": -np.log(closes("USDCHF")).diff(),
              "gold (XAUUSD)": np.log(closes("XAUUSD")).diff(),
              "dollar (DXY)": np.log(dxy).diff()}
    for sym in DERIV_SEQLAB:
        try:
            havens[f"Deriv {sym}"] = np.log(closes(sym)).diff()
        except (ValueError, FileNotFoundError):
            continue
    print("SAFE HAVEN, daily: mean return on S&P risk-off days (< -2 sd), bps [95% CI]; placebo random days")
    for name, h in havens.items():
        h = h.dropna()
        days = riskoff[(riskoff >= h.index[0]) & (riskoff <= h.index[-1])]
        mid = h.index[len(h) // 2]
        line = [f"  {name:30s} n={len(days):3d}"]
        for lag, label in ((0, "same day"), (1, "next day")):
            shifted = h.shift(-lag)
            v = shifted.reindex(days).to_numpy()
            m, lo, hi = boot(v)
            plac = [shifted.dropna().sample(len(days), random_state=int(RNG.integers(1e9))).mean()
                    for _ in range(500)] if len(days) else [np.nan]
            p = np.mean(np.array(plac) >= m) if np.isfinite(m) else float("nan")
            halves = [np.nanmean(shifted.reindex(days[(days < mid) if k == 0 else (days >= mid)]).to_numpy())
                      for k in (0, 1)]
            line.append(f"{label} {m * 1e4:+6.1f} [{lo * 1e4:+.1f}, {hi * 1e4:+.1f}] halves "
                        f"{halves[0] * 1e4:+.1f}/{halves[1] * 1e4:+.1f} placebo p {p:.3f}")
        print(" | ".join(line))

    print("\nSAFE HAVEN, intraday: haven return on the S&P CFD's shock bars (< -2 sd of prior 500), net of spread")
    for iv in ("1h", "15m"):
        path = OUT / f"US_SP_500.{iv}.csv"
        if not path.exists():
            print(f"  {iv}: no S&P CFD bars")
            continue
        s = pd.read_csv(path)
        sp = pd.Series(s["close"].to_numpy(), index=pd.to_datetime(s["time"], unit="s"))
        sr = np.log(sp).diff()
        ssd = sr.rolling(500).std().shift(1)
        shocks = sr[sr < -2 * ssd].index
        span = f"{sp.index[0].date()} to {sp.index[-1].date()}"
        print(f"  {iv}: {len(sp):,} S&P bars {span}, {len(shocks)} shock bars")
        intraday = {"JPY": ("USDJPY", -1), "CHF": ("USDCHF", -1), "gold": ("XAUUSD", 1)}
        dpath = OUT / f"DXYUSD.{iv}.csv"
        for name, (sym, sign) in intraday.items():
            h = sign * np.log(closes(sym, iv)).diff()
            cost = spread_bps(info, sym) / 1e4
            report_bars(name, h, shocks, cost, sp.index)
        if dpath.exists():
            d = pd.read_csv(dpath)
            dx = pd.Series(d["close"].to_numpy(), index=pd.to_datetime(d["time"], unit="s"))
            report_bars("dollar (DXYUSD)", np.log(dx).diff(), shocks, 1.0 / 1e4, sp.index)

    hedge()


def report_bars(name: str, h: pd.Series, shocks: pd.Index, cost: float, universe: pd.Index) -> None:
    h = h[~h.index.duplicated()]
    common = shocks[shocks.isin(h.index)]
    if len(common) < 10:
        print(f"    {name:18s} too few aligned shocks ({len(common)})")
        return
    pos = h.index.get_indexer(common)
    same = h.iloc[pos].to_numpy()
    nxt_idx = pos + 1
    ok = nxt_idx < len(h)
    nxt = h.iloc[nxt_idx[ok]].to_numpy()
    days = common[ok].normalize()

    def clustered_t(v: np.ndarray, d: pd.Index) -> float:
        df = pd.DataFrame({"v": v, "d": d})
        g = df.groupby("d")["v"].sum()
        m = v.mean()
        se = math.sqrt(((g - df.groupby("d")["v"].count() * m) ** 2).sum()) / len(v)
        return float(m / se) if se > 0 else float("nan")

    net = nxt - cost
    mid = common[len(common) // 2]
    halves = [net[(common[ok] < mid)].mean(), net[(common[ok] >= mid)].mean()]
    placebo_pool = h.dropna()
    plac = [placebo_pool.sample(len(nxt), random_state=int(RNG.integers(1e9))).mean() for _ in range(500)]
    p = float(np.mean(np.array(plac) >= nxt.mean()))
    print(f"    {name:18s} n={len(common):4d} | same bar {np.nanmean(same) * 1e4:+6.2f} bps | next bar gross "
          f"{np.nanmean(nxt) * 1e4:+6.2f} net {np.nanmean(net) * 1e4:+6.2f} (t {clustered_t(net, days):+.1f}, cost "
          f"{cost * 1e4:.2f}) halves {halves[0] * 1e4:+.2f}/{halves[1] * 1e4:+.2f} | placebo p {p:.3f}")


def hedge() -> None:
    """The desk's daily P&L on risk-off days, from the journal, if there are any in its span."""
    try:
        conn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=120)
        rows = conn.execute("SELECT time, context FROM entries WHERE kind='outcome' AND actor='trading'").fetchall()
    except sqlite3.Error as exc:
        print(f"\nHEDGE: no journal ({exc})")
        return
    pnl = pd.Series([json.loads(c).get("profit") or 0.0 for _, c in rows],
                    index=[pd.Timestamp(t, unit="s").normalize() for t, _ in rows]).groupby(level=0).sum()
    spx = pd.read_csv(OUT / "spx.csv", index_col=0, parse_dates=True).squeeze()
    r = np.log(spx).diff()
    sd = r.rolling(250).std().shift(1)
    riskoff = r[r < -2 * sd].index
    inside = riskoff[(riskoff >= pnl.index.min()) & (riskoff <= pnl.index.max())]
    print(f"\nHEDGE: journal P&L on {len(pnl)} days ({pnl.index.min().date()} to {pnl.index.max().date()}); "
          f"S&P risk-off days inside that span: {len(inside)}"
          + ("" if len(inside) >= 5 else " - too few to test whether a haven would have cut the desk's drawdowns"))
    if len(inside):
        print(f"  desk P&L on those days: {pnl.reindex(inside).fillna(0).round(2).to_dict()}")


if __name__ == "__main__":
    if PART in ("data",):
        data()
    if PART in ("carry", "all"):
        carry()
    if PART in ("haven", "all"):
        haven()
