"""Spread-, rollover- and news-aware vetoes: validate and calibrate the gates production has.

`game-theory.md` ranked this first: the dealer's spread is the one game-theoretic idea that pays on
this desk. `winning.md` found spread as a share of risk the one feature separating winners from
losers (+0.369R cheap-minus-expensive, p < 0.001), and `intraday.md` found the 20-23 UTC rollover
hours carrying 45% of a period's losses. Production already acts on both. This checks each gate on
data it has not been tuned on, before anything new is proposed.

## The gates in production (till_infinity/trading)

  max_spread_risk_fraction 0.16   refuse when spread / risk > 0.16 (risk.py; winning.md)
  max_spread_fraction      0.25   refuse when spread / reward > 0.25 (risk.py; plans: 0.15 / 0.25
                                  / 0.35 by risk plan)
  max_spread_ratio         2.5    refuse when our spread > 2.5x the venue group's, or with fewer
                                  than three venues > 2.5x this instrument's usual at this hour
                                  (context.py)
  max_dislocation_bps      8      refuse when our quote sits > 8 bps from the venue median
  news_before / news_after 600 / 900 s   stand aside around importance >= HIGH releases
  quiet_hours              ()     refuse entries in these UTC hours; empty by default
                                  (intraday.md proposes 20-23)
  loss_cooldown            900 s  no re-entry on a feed after a loss
  min_reward_to_risk 0.0, min_edge 0.15   not spread gates; listed for completeness

## Data

  A  the desk's own closes in the lab's journal snapshot (data/journal.db, read only), joined to
     their decisions as `winning.py` does: R from prices, spread_at_entry / risk_price, the entry
     time. Real, and small.
  B  every production zone touch the indicators study replayed (data/indicators/*.pkl.gz: the fade
     at the touch, signed return over H = 5 and 20 bars in bar volatilities), joined to the
     seqlab bar's **recorded spread** at the entry bar. Large, with real spread states, and the
     place to separate cost from selection. Deriv is a market here.
     Control: our generated walks' zone touches (walks.pkl.gz) with a synthetic spread process
     drawn independently of price - there a spread veto can only help net by arithmetic and must
     leave gross untouched.

## Tests, pre-registered

  (a) spread to risk     A: spread_at_entry / risk_price; B: the entry spread in bar volatilities.
                         Bins with day-bootstrap CIs, gross and net; cap chosen on the first 60% by
                         total net, scored on the last 40% against the current 0.16.
  (b) spread state       spread over its own trailing median (causal): ratio > 1.5 / 2 / 3.
                         Does it add to (a)? Scored on trades (a) keeps.
  (c) rollover / Sunday  entries in 16:55-17:10 New York, in 20-23 UTC, and in the first hour
                         after the Sunday open (17:00-18:00 New York on Sunday).
  (d) news               entries within w minutes before / after a medium-or-high (and high-only)
                         release of either currency of the pair: w chosen on the first 60%,
                         scored on the last 40% against the current 10 / 15.

For every veto: share vetoed, mean net and gross R of vetoed against kept with a day-bootstrap CI
of the difference, the change in total net and in max drawdown, both halves, and a random veto at
the same rate (share of 1,000 random vetoes doing at least as well). A veto **helps** if vetoed
trades are worse net by a CI excluding zero, total net improves, it beats >= 95% of random vetoes,
and it holds in both halves. It **selects** (not just saves cost) if vetoed trades are also worse
*gross* with a CI excluding zero.

Run on the lab:
  JOURNAL=$HOME/till_infinity/data/journal.db SEQLAB=$HOME/till_infinity/data/seqlab \\
  OUT=$HOME/till_infinity/data python research/harness/vetoes.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

JOURNAL = os.path.expanduser(os.environ.get("JOURNAL", "~/till_infinity/data/journal.db"))
SEQLAB = Path(os.path.expanduser(os.environ.get("SEQLAB", "~/till_infinity/data/seqlab")))
DATA = Path(os.path.expanduser(os.environ.get("OUT", "~/till_infinity/data")))
CALENDAR = DATA / "surprise" / "calendar.jsonl"
NY = ZoneInfo("America/New_York")
RNG = np.random.default_rng(0)
BOOT = 1000
CURRENT_CAP = 0.16
CURRENT_NEWS = (10, 15)  # minutes before, after
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY", "GBPJPY", "XAUUSD", "XAGUSD",
           "BTCUSD", "ETHUSD", "Volatility_75_Index", "Volatility_25_Index", "Jump_50_Index",
           "Step_Index", "Boom_1000_Index", "Crash_1000_Index"]


# ---------------------------------------------------------------------------------------- time

def ny_windows(ts: np.ndarray) -> dict[str, np.ndarray]:
    """Rollover (16:55-17:10 New York), 20-23 UTC, and the Sunday open's first hour."""
    t = pd.to_datetime(ts, unit="s", utc=True)
    ny = t.tz_convert(NY)
    minutes = np.asarray(ny.hour) * 60 + np.asarray(ny.minute)
    weekday = np.asarray(ny.weekday)
    return {
        "rollover": (minutes >= 16 * 60 + 55) & (minutes <= 17 * 60 + 10),
        "utc20_23": np.isin(np.asarray(t.hour), [20, 21, 22]),
        "sunday_open": (weekday == 6) & (minutes >= 17 * 60) & (minutes < 18 * 60),
    }


def currencies(feed: str) -> tuple[str, ...]:
    f = feed.lower()
    if f.startswith(("xau", "xag", "btc", "eth")):
        return ("USD",)
    if len(f) == 6 and f.isalpha():
        return (f[:3].upper(), f[3:].upper())
    return ()


def releases(min_importance: int) -> dict[str, np.ndarray]:
    """Release times (epoch seconds) per currency."""
    by: dict[str, list[float]] = {}
    if not CALENDAR.exists():
        return {}
    for line in CALENDAR.open():
        r = json.loads(line)
        if r.get("importance") is None or r["importance"] < min_importance or not r.get("date"):
            continue
        cur = r.get("currency")
        if not cur:
            continue
        t = datetime.fromisoformat(r["date"].replace("Z", "+00:00")).timestamp()
        by.setdefault(cur, []).append(t)
    return {k: np.sort(np.array(v)) for k, v in by.items()}


def minutes_to_release(feeds: np.ndarray, ts: np.ndarray, rel: dict[str, np.ndarray]) -> np.ndarray:
    """Signed minutes from each entry to the nearest release of its currencies (negative: the
    release is still ahead). NaN where the feed has none."""
    out = np.full(len(ts), np.nan)
    for i, (feed, t) in enumerate(zip(feeds, ts, strict=True)):
        best = np.nan
        for cur in currencies(str(feed)):
            arr = rel.get(cur)
            if arr is None or not len(arr):
                continue
            j = np.searchsorted(arr, t)
            for k in (j - 1, j):
                if 0 <= k < len(arr):
                    d = (t - arr[k]) / 60.0
                    if np.isnan(best) or abs(d) < abs(best):
                        best = d
        out[i] = best
    return out


# ---------------------------------------------------------------------------------------- scoring

def day_boot_diff(a: np.ndarray, a_day: np.ndarray, b: np.ndarray, b_day: np.ndarray):
    """mean(a) - mean(b), with a 95% interval resampling days."""
    if len(a) < 3 or len(b) < 3:
        return float("nan"), (float("nan"), float("nan"))
    days = np.unique(np.concatenate([a_day, b_day]))
    ia = {d: a[a_day == d] for d in days}
    ib = {d: b[b_day == d] for d in days}
    diffs = []
    for _ in range(BOOT):
        pick = RNG.choice(days, len(days))
        xa = np.concatenate([ia[d] for d in pick])
        xb = np.concatenate([ib[d] for d in pick])
        if len(xa) and len(xb):
            diffs.append(xa.mean() - xb.mean())
    return float(a.mean() - b.mean()), tuple(np.quantile(diffs, [0.025, 0.975]))


def max_drawdown(x: np.ndarray) -> float:
    c = np.cumsum(x)
    return float(np.max(np.maximum.accumulate(np.r_[0.0, c])[1:] - c)) if len(c) else 0.0


def judge(name: str, veto: np.ndarray, net: np.ndarray, gross: np.ndarray, day: np.ndarray,
          t: np.ndarray) -> str:
    """One veto, scored. `net`, `gross` per trade in time order."""
    n, k = len(net), int(veto.sum())
    if k < 5 or k > n - 5:
        return f"    {name:34s} vetoes {k} of {n} - too few to judge"
    d_net, ci_net = day_boot_diff(net[veto], day[veto], net[~veto], day[~veto])
    d_gross, ci_gross = day_boot_diff(gross[veto], day[veto], gross[~veto], day[~veto])
    saved = -net[veto].sum()
    dd_all, dd_kept = max_drawdown(net), max_drawdown(net[~veto])
    rand = np.array([-net[RNG.choice(n, k, replace=False)].sum() for _ in range(BOOT)])
    beats = float(np.mean(rand <= saved))
    cut = np.quantile(t, 0.5)
    halves = []
    for part in (t < cut, t >= cut):
        v, kept = veto & part, ~veto & part
        halves.append(net[v].mean() - net[kept].mean() if v.sum() >= 3 and kept.sum() >= 3 else float("nan"))
    helps = (ci_net[1] < 0) and saved > 0 and beats >= 0.95 and all(h < 0 for h in halves)
    selects = ci_gross[1] < 0
    verdict = ("HELPS" if helps else "no") + (" + SELECTS" if selects else "")
    return (f"    {name:34s} vetoes {k:6,} ({k / n:5.1%}) | vetoed-kept net {d_net:+.3f} "
            f"[{ci_net[0]:+.3f}, {ci_net[1]:+.3f}] gross {d_gross:+.3f} [{ci_gross[0]:+.3f}, "
            f"{ci_gross[1]:+.3f}] | total {saved:+.1f} | dd {dd_all:.1f}->{dd_kept:.1f} | beats "
            f"{beats:.0%} random | halves {halves[0]:+.3f}/{halves[1]:+.3f} | {verdict}")


def walk_forward_cap(x: np.ndarray, net: np.ndarray, t: np.ndarray, grid) -> str:
    """Choose `veto x > cap` on the first 60% by total net; score it on the last 40%."""
    cut = np.quantile(t, 0.6)
    first, last = t < cut, t >= cut
    best = max(grid, key=lambda c: net[first & ~(x > c)].sum())
    def total(c, part):
        return net[part & ~(x > c)].sum()
    return (f"    walk-forward: cap chosen on first 60% = {best:g}; last 40% total net at it "
            f"{total(best, last):+.1f}, at the current {CURRENT_CAP:g} {total(CURRENT_CAP, last):+.1f}, "
            f"with no cap {net[last].sum():+.1f}")


# ---------------------------------------------------------------------------------------- A: trades

def part_a() -> None:
    import winning

    attributed, _ = winning.load(JOURNAL)
    rows = []
    for r in attributed:
        d = r.get("_decision") or {}
        spread, risk = d.get("spread_at_entry"), d.get("risk_price")
        if r.get("R") is None or not isinstance(spread, int | float) or not risk:
            continue
        entered = r["_t"] - float(r.get("seconds") or 0)
        rows.append({"t": entered, "feed": str(r.get("feed") or ""), "net": float(r["R"]),
                     "sr": float(spread) / float(risk), "spread": float(spread)})
    df = pd.DataFrame(rows).sort_values("t").reset_index(drop=True)
    print(f"A. DESK TRADES: {len(df)} attributed closes with R and spread at entry "
          f"({pd.to_datetime(df['t'].min(), unit='s'):%Y-%m-%d} to {pd.to_datetime(df['t'].max(), unit='s'):%Y-%m-%d})")
    if len(df) < 20:
        print("   too few to judge")
        return
    df["gross"] = df["net"] + df["sr"]  # one spread per round trip, in R
    df["day"] = (df["t"] // 86_400).astype(int)
    # spread state: this trade's spread over the feed's trailing median of earlier decisions
    df["ratio"] = np.nan
    for feed, g in df.groupby("feed"):
        med = g["spread"].expanding().median().shift(1)
        df.loc[g.index, "ratio"] = (g["spread"] / med).where(g["spread"].expanding().count().shift(1) >= 5)
    net, gross, day, t = (df[c].to_numpy() for c in ("net", "gross", "day", "t"))
    print("\n  (a) spread / risk, by bin: n | mean net | mean gross | stopped-ish (net <= -0.9R)")
    for lo, hi in ((0, 0.05), (0.05, 0.1), (0.1, 0.16), (0.16, 0.25), (0.25, 10)):
        m = (df["sr"] > lo) & (df["sr"] <= hi)
        if m.sum():
            print(f"    ({lo:.2f}, {hi:.2f}] n={int(m.sum()):4d} net {df.loc[m, 'net'].mean():+.3f} "
                  f"gross {df.loc[m, 'gross'].mean():+.3f} stopped {np.mean(df.loc[m, 'net'] <= -0.9):.0%}")
    for cap in (0.08, 0.12, 0.16, 0.2, 0.25):
        print(judge(f"spread/risk > {cap:g}", df["sr"].to_numpy() > cap, net, gross, day, t))
    print(walk_forward_cap(df["sr"].to_numpy(), net, t, (0.06, 0.08, 0.1, 0.12, 0.16, 0.2, 0.25, 0.3, 10)))
    kept = df["sr"] <= CURRENT_CAP
    print("\n  (b) spread over its own trailing median, on trades the 0.16 cap keeps")
    k = df[kept & df["ratio"].notna()]
    for r in (1.5, 2.0, 3.0):
        print(judge(f"ratio > {r:g}", k["ratio"].to_numpy() > r, *(k[c].to_numpy() for c in ("net", "gross", "day", "t"))))
    print("\n  (c) time windows")
    for name, m in ny_windows(df["t"].to_numpy()).items():
        print(judge(name, m, net, gross, day, t))
    print("\n  (d) news: entries within w minutes of a release of either currency")
    for imp, label in ((0, "medium+high"), (1, "high")):
        mins = minutes_to_release(df["feed"].to_numpy(), df["t"].to_numpy(), releases(imp))
        for before, after in ((5, 5), (10, 15), (30, 30), (60, 60)):
            m = (mins >= -before) & (mins <= after)
            print(judge(f"{label} -{before}/+{after} min", m, net, gross, day, t))


# ---------------------------------------------------------------------------------------- B: touches

def point_size(close: np.ndarray) -> float:
    for d in range(9):
        scaled = close[:5000] * 10**d
        if np.mean(np.abs(scaled - np.round(scaled)) < 1e-6) > 0.99:
            return 10.0**-d
    return 1e-8


def bar_frame(sym: str, iv: str) -> pd.DataFrame | None:
    path = SEQLAB / f"{sym}.{iv}.npz"
    if not path.exists():
        return None
    z = np.load(path)
    if "spread" not in z:
        return None
    df = pd.DataFrame({k: z[k] for k in ("time", "close", "spread")})
    df["time"] = df["time"].astype(np.int64)
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    c = df["close"]
    vol = np.log(c).diff().abs().ewm(span=14, adjust=False).mean() * np.sqrt(np.pi / 2)
    spread_price = df["spread"] * point_size(c.to_numpy())
    df["cost_vol"] = (spread_price / c) / vol
    df["ratio"] = df["spread"] / df["spread"].rolling(500, min_periods=100).median().shift(1)
    return df[["time", "cost_vol", "ratio"]]


def synthetic_spread(n: int) -> tuple[np.ndarray, np.ndarray]:
    """A spread process independent of price: lognormal around 0.3 vol, with rare spikes."""
    base = np.exp(RNG.normal(np.log(0.3), 0.35, n))
    spikes = RNG.random(n) < 0.02
    cost = np.where(spikes, base * RNG.uniform(3, 10, n), base)
    return cost, cost / 0.3


def part_b() -> None:
    lower = {s.lower(): s for s in SYMBOLS}
    rel = {imp: releases(imp) for imp in (0, 1)}
    print("\n\nB. ZONE TOUCHES (indicators replay), fade at the touch, joined to the bar's recorded spread")
    for universe in ("real", "deriv", "walks"):
        path = DATA / "indicators" / f"{universe}.pkl.gz"
        if not path.exists():
            continue
        d = pd.read_pickle(path)  # our own lab output (indicators.py), not untrusted input
        d = d[(d["kind"] == "zone") & (d["rule"] == "touch")].copy()
        if universe == "walks":
            cost, ratio = synthetic_spread(len(d))
            d["cost_vol"], d["ratio"] = cost, ratio
        else:
            parts = []
            for (feed, iv), g in d.groupby(["feed", "interval"]):
                sym = lower.get(feed)
                bars = bar_frame(sym, iv) if sym else None
                if bars is None:
                    continue
                parts.append(pd.merge_asof(g.sort_values("time"), bars, on="time", direction="backward"))
            if not parts:
                continue
            d = pd.concat(parts, ignore_index=True)
        d = d[np.isfinite(d["cost_vol"])].reset_index(drop=True)  # labels are positions below
        d["netr"] = d["gross"] - d["cost_vol"]  # the recorded spread, not a constant
        d["day"] = (d["time"] // 86_400).astype(int)
        mins = {imp: minutes_to_release(d["feed"].to_numpy(), d["time"].to_numpy(), rel[imp]) for imp in (0, 1)}
        wins = ny_windows(d["time"].to_numpy())
        for (family, h), g in d.groupby(["family", "h"]):
            g = g.sort_values("time")
            if len(g) < 200:
                continue
            net, gross, day, t = (g[c].to_numpy() for c in ("netr", "gross", "day", "time"))
            cv = g["cost_vol"].to_numpy()
            print(f"\n  == {universe} · {family} · H={h} · n={len(g):,} · mean gross {gross.mean():+.3f} "
                  f"net {net.mean():+.3f} · median spread {np.median(cv):.3f} vol")
            q = np.quantile(cv, [0.5, 0.8, 0.9, 0.95])
            print("    gross by spread decile (selection?): " + " ".join(
                f"{np.mean(gross[(cv >= a) & (cv <= b)]):+.2f}" for a, b in
                zip(np.quantile(cv, np.linspace(0, 0.9, 10)), np.quantile(cv, np.linspace(0.1, 1, 10)), strict=True)))
            for p, cap in zip((50, 80, 90, 95), q, strict=True):
                print(judge(f"spread > p{p} ({cap:.3f} vol)", cv > cap, net, gross, day, t))
            print(walk_forward_cap(cv, net, t, tuple(np.quantile(cv, [0.5, 0.7, 0.8, 0.9, 0.95, 0.99])) + (1e9,)))
            r = g["ratio"].to_numpy()
            ok = np.isfinite(r)
            for k in (1.5, 2.0, 3.0):
                print(judge(f"ratio > {k:g}", ok & (r > k), net, gross, day, t))
            sel = g.index.to_numpy()
            for name, m in wins.items():
                print(judge(name, m[sel], net, gross, day, t))
            for imp, label in ((0, "med+high"), (1, "high")):
                mm = mins[imp][sel]
                for before, after in ((10, 15), (30, 30), (60, 60)):
                    print(judge(f"news {label} -{before}/+{after}", (mm >= -before) & (mm <= after),
                                net, gross, day, t))


if __name__ == "__main__":
    part = os.environ.get("PART", "all")
    if part in ("all", "a"):
        part_a()
    if part in ("all", "b"):
        part_b()
