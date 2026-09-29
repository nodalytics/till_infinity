"""Markets move on the gap between expectations and reality: the macro surprise, measured.

The claim (Lock Stock Finance, "How the $7 Trillion Currency Market ACTUALLY Works"): "If
everybody already expects the Fed to raise rates, the dollar might not move much ... If inflation
comes in higher than expected ... the dollar could strengthen quickly. Markets move based on the gap
between expectations and reality."

PART=fetch  weekly windows of TradingView's economic calendar (the provider the desk already polls,
            `news/calendar.py`) from 2022 to 2026-09, G10 plus China, saved raw as JSON lines.
PART=study  the questions (see the study section).

Run on the lab:
  PART=fetch OUT=$HOME/till_infinity/data/surprise python research/harness/surprise.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

OUT = Path(os.environ.get("OUT", ".data/surprise"))
URL = "https://economic-calendar.tradingview.com/events?from={a}&to={b}&countries={c}"
COUNTRIES = "US,EU,DE,FR,IT,GB,JP,AU,NZ,CA,CH,CN"
START, END = datetime(2022, 1, 3, tzinfo=UTC), datetime(2026, 9, 14, tzinfo=UTC)


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fetch():
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "calendar.jsonl"
    seen = set()
    if dest.exists():
        seen = {json.loads(line)["id"] for line in dest.open()}
    t = START
    with dest.open("a") as fh:
        while t < END:
            u = t + timedelta(days=7)
            req = urllib.request.Request(URL.format(a=stamp(t), b=stamp(u), c=COUNTRIES), headers={
                "Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/",
                "User-Agent": "Mozilla/5.0"})
            for attempt in range(4):
                try:
                    rows = json.load(urllib.request.urlopen(req, timeout=60))["result"]
                    break
                except Exception as exc:  # transient; back off and retry
                    print(f"  {t:%Y-%m-%d} attempt {attempt}: {exc}", flush=True)
                    time.sleep(10 * (attempt + 1))
            else:
                rows = []
            new = 0
            for r in rows:
                if r["id"] in seen:
                    continue
                r.pop("comment", None)
                fh.write(json.dumps(r) + "\n")
                seen.add(r["id"])
                new += 1
            print(f"{t:%Y-%m-%d}: {len(rows)} events, {new} new", flush=True)
            t = u
            time.sleep(1.5)


# ---------------------------------------------------------------------------------------------- study
#
# Surprise = actual - forecast, divided by the standard deviation of that indicator's own earlier
# surprises (strictly before the release, at least MIN_PAST of them): a z-score that is comparable
# across indicators and uses nothing from the future. Signed so that + is good for the currency:
# higher is good except unemployment, jobless claims and claimant counts. Energy inventories are
# dropped (not a currency's news). Releases for one currency at one minute are one event, with the
# importance-weighted mean z. Each event's reaction is the mean over every pair carrying that
# currency (base +1, quote -1; gold and silver as USD-quoted), in units of each pair's trailing mean
# |15m return|, so one release is one observation however many pairs it touches.
MIN_PAST = 6
INVERT = ("unemployment", "jobless", "claimant")
DROP_CATEGORY = ("engy",)
PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "GBPJPY", "EURGBP",
         "AUDJPY", "EURAUD", "CHFJPY", "EURCHF", "USDCNH", "XAUUSD", "XAGUSD"]
COST_15M = 0.8 / np.sqrt(3)  # fx spread in 15m baseline units (COST_V convention); news-time is taken as 2x


def events():
    rows = [json.loads(line) for line in (OUT / "calendar.jsonl").open()]
    d = pd.DataFrame(rows)
    d = d[d["actual"].notna() & d["forecast"].notna() & d["currency"].notna()].copy()
    d = d[~d["category"].isin(DROP_CATEGORY)]
    d["t"] = pd.to_datetime(d["date"], utc=True)
    d = d.drop_duplicates(["ticker", "t"]).sort_values("t")
    d["s"] = d["actual"].astype(float) - d["forecast"].astype(float)
    # revision check: is this release's actual what the next release reports as previous?
    nxt = d.groupby("ticker")["previous"].shift(-1)
    d["revised_later"] = nxt.notna() & (np.abs(nxt.astype(float) - d["actual"].astype(float)) > 1e-9)
    past = d.groupby("ticker")["s"].transform(lambda x: x.shift(1).expanding(MIN_PAST).std())
    d["z"] = d["s"] / past.replace(0, np.nan)
    sign = np.where(d["title"].str.lower().str.contains("|".join(INVERT)), -1.0, 1.0)
    d["z"] = d["z"] * sign
    return d[np.isfinite(d["z"])]


def pair_bars(pair):
    df = spikerisk.load(None, pair, "SEQLAB", "15m")
    lc = np.log(df["close"].to_numpy())
    r = np.diff(lc, prepend=np.nan)
    base = pd.Series(np.abs(r)).rolling(500, min_periods=250).mean().to_numpy()
    return pd.Series(lc, index=pd.to_datetime(df["ts"].to_numpy(), unit="s", utc=True)), base


def reactions(ev):
    """For each (currency, minute): aligned returns across pairs, in baseline units."""
    bars = {p: pair_bars(p) for p in PAIRS}
    horizons = {"pre4h": (-16, 0), "r0": (0, 1), "d1h": (1, 5), "d4h": (1, 17), "d1d": (1, 97)}
    out = []
    groups = ev.assign(w=ev["importance"].astype(float) + 2).groupby(["currency", "t"])
    for (cur, t), g in groups:
        z = np.average(g["z"], weights=g["w"])
        res = {k: [] for k in horizons}
        for p, (lc, base) in bars.items():
            ccy = {"XAUUSD": ("XAU", "USD"), "XAGUSD": ("XAG", "USD")}.get(p, (p[:3], p[3:]))
            expo = 1.0 if ccy[0] == cur else (-1.0 if ccy[1] == cur else 0.0)
            if not expo:
                continue
            i = lc.index.searchsorted(t)  # the bar opening at the release (or the first after)
            if i < 1 or i + 97 >= len(lc) or lc.index[int(i)] - t > pd.Timedelta("15min") or not np.isfinite(base[i - 1]):
                continue
            ref = i - 1  # the bar that closed at the release: the last price before it
            for k, (a, b) in horizons.items():
                res[k].append(expo * (lc.iloc[ref + b] - lc.iloc[ref + a]) / base[i - 1])
        if res["r0"]:
            out.append(dict(currency=cur, t=t, z=z, n=len(g), importance=g["importance"].max(),
                            category=g["category"].fillna("none").mode().iloc[0], revised=g["revised_later"].mean(),
                            **{k: np.mean(v) for k, v in res.items()}))
    return pd.DataFrame(out)


def study():
    from scipy import stats
    ev = events()
    print(f"\n{'=' * 110}\nSURPRISE - {len(ev):,} releases with a standardisable surprise, {ev['ticker'].nunique()} indicators; "
          f"share whose actual was later revised {ev['revised_later'].mean():.1%}")
    R = reactions(ev)
    R = R[R["t"] >= pd.Timestamp("2024-09-15", tz="UTC")]
    placebo = reactions(ev.assign(t=ev["t"] - pd.Timedelta("1D")))  # same clock time, the day before
    placebo = placebo[placebo["t"] >= pd.Timestamp("2024-09-15", tz="UTC")]
    mid = R["t"].quantile(0.5)
    print(f"  {len(R):,} currency-events on 15m bars, {R['t'].min():%Y-%m-%d} to {R['t'].max():%Y-%m-%d}; halves split at {mid:%Y-%m-%d}")

    def line(name, d, col):
        h1, h2 = d[d["t"] < mid], d[d["t"] >= mid]
        rho = stats.spearmanr(d["z"], d[col]).statistic
        big = d[np.abs(d["z"]) >= 1]
        hit = np.mean(np.sign(big["z"]) == np.sign(big[col])) if len(big) else np.nan
        return (f"    {name:<44} rho {rho:+.3f} ({stats.spearmanr(h1['z'], h1[col]).statistic:+.3f} / "
                f"{stats.spearmanr(h2['z'], h2[col]).statistic:+.3f}) | |z|>=1: n={len(big)}, sign agrees {hit:.1%}, "
                f"aligned mean {np.mean(np.sign(big['z']) * big[col]):+.3f}")

    for imp, lab in ((-1, "all importance"), (0, "medium and high"), (1, "high only")):
        d = R[R["importance"] >= imp]
        print(f"\n  {lab}: {len(d):,} events")
        print(line("E1 release bar (first 15m)", d, "r0"))
        print(line("E1 placebo: same time, day before", placebo[placebo["importance"] >= imp], "r0"))
        print(line("E4 before: 4h into the release", d, "pre4h"))
        for c in ("d1h", "d4h", "d1d"):
            print(line(f"E2 after the first 15m: {c[1:]}", d, c))
    d = R[R["importance"] >= 0]
    print("\n  E1 does the expected part move? mean |first 15m| by |z| (medium and high):")
    for lo_, hi_ in ((0, 0.25), (0.25, 0.75), (0.75, 1.5), (1.5, 3), (3, 99)):
        m = (np.abs(d["z"]) >= lo_) & (np.abs(d["z"]) < hi_)
        pm = (np.abs(placebo["z"]) >= lo_) & (np.abs(placebo["z"]) < hi_) & (placebo["importance"] >= 0)
        print(f"    |z| {lo_:>4}-{hi_:<4} n={m.sum():>4}  |r0| {np.abs(d['r0'][m]).mean():.2f}  aligned r0 "
              f"{np.mean(np.sign(d['z'][m]) * d['r0'][m]):+.2f}   (placebo |r0| {np.abs(placebo['r0'][pm]).mean():.2f})")
    print("\n  E3 by category (medium and high), first 15m and the 4h after:")
    for cat, g in d.groupby("category"):
        if len(g) >= 40:
            print(f"    {cat:<6} n={len(g):>4} r0 rho {stats.spearmanr(g['z'], g['r0']).statistic:+.3f} | "
                  f"4h after rho {stats.spearmanr(g['z'], g['d4h']).statistic:+.3f}")
    print("\n  E2 as a trade: with the surprise when |z| >= 1, entered at the close of the release bar, net of 2x spread")
    for c in ("d1h", "d4h", "d1d"):
        for thr in (1.0, 2.0):
            k = d[np.abs(d["z"]) >= thr]
            g = np.sign(k["z"]) * k[c]
            null = [np.mean(RNG.permutation(np.sign(k["z"].to_numpy())) * k[c].to_numpy()) for _ in range(500)]
            print(f"    {c[1:]:<3} |z|>={thr:.0f} n={len(k):>4} gross {g.mean():+.3f} +- {g.std() / np.sqrt(len(g)):.3f} "
                  f"(halves {g[k['t'] < mid].mean():+.3f} / {g[k['t'] >= mid].mean():+.3f}) net {g.mean() - 2 * COST_15M:+.3f} "
                  f"| shuffled-sign p {np.mean(np.array(null) >= g.mean()):.3f}")


RNG = np.random.default_rng(5)


def fast():
    """What a bot could catch: on 3m bars (the last five months only), the first 3 minutes against what
    follows from +3m, the earliest a desk polling bars could act."""
    from scipy import stats
    ev = events()
    ev = ev[ev["importance"] >= 0]
    bars = {}
    for p in PAIRS:
        df = spikerisk.load(None, p, "SEQLAB", "3m")
        lc = np.log(df["close"].to_numpy())
        base = pd.Series(np.abs(np.diff(lc, prepend=np.nan))).rolling(500, min_periods=250).mean().to_numpy()
        bars[p] = (pd.Series(lc, index=pd.to_datetime(df["ts"].to_numpy(), unit="s", utc=True)), base)
    first = min(v[0].index[0] for v in bars.values()) + pd.Timedelta("3D")
    windows = {"0-3m": (0, 1), "3-15m": (1, 5), "3-60m": (1, 20), "15-60m": (5, 20)}
    out = []
    for (cur, t), g in ev[ev["t"] >= first].assign(w=lambda x: x["importance"] + 2).groupby(["currency", "t"]):
        res = {k: [] for k in windows}
        for p, (lc, base) in bars.items():
            ccy = {"XAUUSD": ("XAU", "USD"), "XAGUSD": ("XAG", "USD")}.get(p, (p[:3], p[3:]))
            expo = 1.0 if ccy[0] == cur else (-1.0 if ccy[1] == cur else 0.0)
            i = int(lc.index.searchsorted(t))
            if not expo or i < 1 or i + 21 >= len(lc) or lc.index[i] - t > pd.Timedelta("3min") or not np.isfinite(base[i - 1]):
                continue
            for k, (a, b) in windows.items():
                res[k].append(expo * (lc.iloc[i - 1 + b] - lc.iloc[i - 1 + a]) / base[i - 1])
        if res["0-3m"]:
            out.append(dict(z=np.average(g["z"], weights=g["w"]), **{k: np.mean(v) for k, v in res.items()}))
    R = pd.DataFrame(out)
    print(f"\n  FAST - 3m bars, {len(R)} medium/high currency-events since {first:%Y-%m-%d}; units = trailing mean |3m return|")
    for k in windows:
        big = R[np.abs(R["z"]) >= 1]
        print(f"    {k:<7} rho {stats.spearmanr(R['z'], R[k]).statistic:+.3f} | |z|>=1 n={len(big)} aligned "
              f"{np.mean(np.sign(big['z']) * big[k]):+.2f} +- {np.std(np.sign(big['z']) * big[k]) / np.sqrt(len(big)):.2f}, "
              f"sign agrees {np.mean(np.sign(big['z']) == np.sign(big[k])):.1%}")
    print(f"    (spread in these units, normal / news-time 2x: {0.8:.2f} / {1.6:.2f})")

if __name__ == "__main__":
    part = os.environ.get("PART", "study")
    fetch() if part == "fetch" else fast() if part == "fast" else study()
