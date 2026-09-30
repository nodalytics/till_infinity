"""Market rituals: does the market behave differently around recurring institutional events?

The user's anthropology question: markets have rituals - options expiry, index rebalancing, month-
and quarter-end, central-bank decisions, payrolls, crypto funding and futures expiry - and
participants anticipate them together. This asks whether that *socially coordinated anticipation*
shows in the bars before, on and after the day, beyond what the clock already explains.

Not repeated here (see the docs): the weekday x hour clock (`calendar-returns.md`), release
surprise drift (`surprise.md`), the daily FX rollover (`rollover.md`, `vetoes.md`), weekends
(`fridayflag.md`, `gaptrade.md`). Rituals are the lower-frequency institutional cycles.

## Rituals (dates computed, fetched or read)

  opex          third Friday of each month, excluding the quarterly months
  witching      third Friday of Mar/Jun/Sep/Dec: triple witching and the S&P quarterly rebalance
  msci          last business day of Feb/May/Aug/Nov: MSCI quarterly index reviews
  russell       last Friday of June: the Russell reconstitution (annual, so few events)
  month-end     last business day of a month that is not a quarter end
  quarter-end   last business day of Mar/Jun/Sep/Dec
  fomc          scheduled FOMC decisions (federalreserve.gov historical pages and calendar, cached)
  ecb/boe/boj   decisions from the lab's calendar (2022 on)
  nfp           US non-farm payrolls from the calendar (2022 on)
  crypto-expiry last Friday of Mar/Jun/Sep/Dec (quarterly futures)
  Token unlocks: no data on the lab - untestable here.

## Assets

FX (every pair's |y| pooled, and a USD proxy: the average of the USD legs, signed as USD), metals
(XAU, XAG), crypto (BTC, ETH, SOL), a US stock basket (equal-weighted share CFDs the broker serves -
only from 2025-09, and survivorship-biased: only listed names), Deriv (Volatility and Boom/Crash) as
a market with no institutions - a design comparison, not a null - and walks we generate (iid
Student-t(3), FX-calendar and 24/7), the null.

## Pre-registered tests

Daily event study, window -5..+5 trading days, on y = r / sigma (sigma the daily EWMA of true range,
alpha 1/14, as of the day before), |y|, range / sigma and log volume against its 20-day mean - each
**minus its weekday mean**, so the weekly clock is not re-found as a ritual:

  V-pre   mean |y| on days -3..-1 against baseline: compression is negative
  V-post  mean |y| on days 0..+2 against baseline: expansion is positive
  R0      range on day 0; VOL0 log volume on day 0
  D       drift: turn-of-month sums y over days -1..+3; every other ritual, y on day 0 and on -1

p-values from placebo dates: every event shifted a random 2-8 weeks (same weekday), avoiding the
real events, 500 times; and the same study on the walks. Both halves (events split at the sample's
median date).

Intraday (1h, 2018 on):
  pre-FOMC  the 24 hours before the announcement (14:00 New York; 14:15 before 2013), Lucca &
            Moench 2015, on the USD proxy, gold, BTC and the stock basket. Their S&P drift was
            published in 2011-2015; everything here is after it, so this is a post-publication test.
            A daily proxy (y on day -1) runs from the start of each daily series, split at 2012.
  fix       the month-end WM/Reuters 4pm London fix: FX bars starting 15:00 and 16:00 London on
            month-end days against the same bars on other days (weekday x hour clock removed)
  funding   crypto funding settles at 00/08/16 UTC every day, so the clock absorbs its mean. The
            test is intensity: does the settlement hour's move scale with the funding rate (sign
            and size), beyond the same regression at the other hours?

Risk: does knowing a ritual day in advance improve the next day's |r| forecast beyond the
production sigma times the weekday profile? Multipliers per ritual fitted on the first 60% of days,
relative MSE on the last 40%, in both of its halves. Worth production if below 0.99 in both.

Trade: a drift test that survives Benjamini-Hochberg across every test here is traded out of
sample - its sign from the first 60% of events, the last 40% net of COST_V in daily units - and
passes only with t >= 3 in both halves of the verification events and not on the walks.

Deflation: the largest |t| here against the False Strategy Theorem's expected maximum for the
number of tests (`lopez-de-prado.md`).

Run on the lab:
  SEQLAB=$HOME/till_infinity/data/seqlab OUT=$HOME/till_infinity/data/rituals \\
      python research/harness/rituals.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from math import erf, log, sqrt
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

OUT = Path(os.environ.get("OUT", ".data/rituals"))
SEQLAB = Path(os.environ.get("SEQLAB", ".data/seqlab"))
CALENDAR = Path(os.environ.get("CALENDAR", str(SEQLAB.parent / "surprise" / "calendar.jsonl")))
CROWDING = Path(os.environ.get("CROWDING", str(SEQLAB.parent / "crowding")))
PLACEBOS = int(os.environ.get("PLACEBOS", "300"))
#: Daily series start here: the broker's FX dailies reach back to 1971, with odd early prints.
DAILY_START = pd.Timestamp(os.environ.get("DAILY_START", "2000-01-01"))
WINDOW = range(-5, 6)
NY, LONDON = "America/New_York", "Europe/London"

FX = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "GBPJPY",
      "EURGBP", "AUDJPY", "EURCHF"]
USD_SIGN = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1, "USDCAD": 1, "USDCHF": 1,
            "USDJPY": 1}
FAMILIES = {
    "fx": FX,
    "metals": ["XAUUSD", "XAGUSD"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD"],
    "deriv volatility": ["Volatility_10_Index", "Volatility_25_Index", "Volatility_75_Index",
                         "Volatility_100_Index"],
    "deriv boom/crash": ["Boom_1000_Index", "Crash_1000_Index"],
}
COST_V = {"fx": 0.8, "metals": 0.16, "crypto": 0.5, "usd": 0.8, "stocks": 0.5}  # M5-vol units
DAILY = sqrt(5 / 1440)  # M5 vol units into daily vol units

# ------------------------------------------------------------------------------------------ dates


def business_days(start: str, end: str) -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


def third_friday(year: int, month: int) -> pd.Timestamp:
    first = pd.Timestamp(year=year, month=month, day=1)
    offset = (4 - first.weekday()) % 7
    return first + pd.Timedelta(days=offset + 14)


def last_weekday_of(year: int, month: int, weekday: int) -> pd.Timestamp:
    last = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    return last - pd.Timedelta(days=(last.weekday() - weekday) % 7)


def last_business_day(year: int, month: int) -> pd.Timestamp:
    last = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    while last.weekday() >= 5:
        last -= pd.Timedelta(days=1)
    return last


def computed(start: int, end: int) -> dict[str, list[pd.Timestamp]]:
    out: dict[str, list[pd.Timestamp]] = {k: [] for k in (
        "opex", "witching", "msci", "russell", "month-end", "quarter-end", "turn-of-month",
        "crypto-expiry")}
    for y in range(start, end + 1):
        for m in range(1, 13):
            quarter = m in (3, 6, 9, 12)
            (out["witching"] if quarter else out["opex"]).append(third_friday(y, m))
            if m in (2, 5, 8, 11):
                out["msci"].append(last_business_day(y, m))
            if m == 6:
                out["russell"].append(last_weekday_of(y, 6, 4))
            (out["quarter-end"] if quarter else out["month-end"]).append(last_business_day(y, m))
            out["turn-of-month"].append(last_business_day(y, m))
            if quarter:
                out["crypto-expiry"].append(last_weekday_of(y, m, 4))
    return out


MONTHS = ("January February March April May June July August September October November "
          "December").split()


def fomc_dates() -> list[pd.Timestamp]:
    """Scheduled FOMC decision days: the last day of each scheduled meeting. Fetched once from
    federalreserve.gov and cached, because the lab's calendar only starts in 2022."""
    cache = OUT / "fomc.json"
    if cache.exists():
        return [pd.Timestamp(d) for d in json.loads(cache.read_text())]
    found: set[str] = set()

    def get(url: str) -> str:
        return subprocess.run(["curl", "-s", "-m", "40", "-A", "Mozilla/5.0", url],
                              capture_output=True, text=True).stdout

    pattern = re.compile(r"(" + "|".join(MONTHS) + r")(?:/(" + "|".join(MONTHS) + r"))? "
                         r"(\d{1,2})(?:-(\d{1,2}))? Meeting")
    for year in range(1994, 2021):
        html = get(f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm")
        for m1, m2, d1, d2 in pattern.findall(html):
            month = MONTHS.index(m2 or m1) + 1
            day = int(d2 or d1)
            try:
                found.add(pd.Timestamp(year=year, month=month, day=day).strftime("%Y-%m-%d"))
            except ValueError:
                continue
    html = get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
    parts = re.split(r">(\d{4}) FOMC Meetings<", html)
    for i in range(1, len(parts) - 1, 2):
        year = int(parts[i])
        body = parts[i + 1]
        months = re.findall(r"fomc-meeting__month[^>]*><strong>([A-Za-z/]+)", body)
        dates = re.findall(r"fomc-meeting__date[^>]*>([0-9\-]+)", body)
        for mon, dd in zip(months, dates, strict=False):
            name = mon.split("/")[-1]
            if name not in MONTHS:
                continue
            day = int(dd.split("-")[-1])
            month = MONTHS.index(name) + 1
            try:
                found.add(pd.Timestamp(year=year, month=month, day=day).strftime("%Y-%m-%d"))
            except ValueError:
                continue
    dates = sorted(found)
    OUT.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(dates))
    return [pd.Timestamp(d) for d in dates]


def calendar_dates() -> dict[str, list[pd.Timestamp]]:
    want = {"ecb": ("EU", "ECB Interest Rate Decision"), "boe": ("GB", "BoE Interest Rate Decision"),
            "boj": ("JP", "BoJ Interest Rate Decision"), "nfp": ("US", "Non Farm Payrolls")}
    out: dict[str, list[pd.Timestamp]] = {k: [] for k in want}
    if not CALENDAR.exists():
        return out
    for line in CALENDAR.open():
        d = json.loads(line)
        for key, (country, title) in want.items():
            if d.get("country") == country and d.get("title") == title:
                out[key].append(pd.Timestamp(d["date"]).tz_localize(None).normalize())
    return {k: sorted(set(v)) for k, v in out.items()}


# ------------------------------------------------------------------------------------------ data


def load(sym: str, interval: str) -> pd.DataFrame | None:
    try:
        df = spikerisk.load(None, sym, "SEQLAB", interval)
    except (ValueError, FileNotFoundError):
        return None
    return df if len(df) > 150 else None  # the broker's share CFDs start 2025-09: ~270 days


def prepare(df: pd.DataFrame, intrabar: bool = False) -> pd.DataFrame:
    """y, |y|, range and log volume in the bar's own volatility units. Daily moves are close to
    close, so a gap belongs to its day; hourly moves (`intrabar`) are open to close."""
    o, h, lo, c = (np.log(df[k].to_numpy(float)) for k in ("open", "high", "low", "close"))
    prev = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.column_stack([h - lo, np.abs(h - prev), np.abs(lo - prev)]), axis=1)
    sig = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().shift(1).to_numpy()
    r = c - o if intrabar else c - prev
    vol = df["volume"].to_numpy(float) if "volume" in df else np.full(len(df), np.nan)
    lv = np.log(np.where(vol > 0, vol, np.nan))
    out = pd.DataFrame({"ts": df["ts"].to_numpy(), "r": r, "sig": sig, "y": r / sig,
                        "rng": (h - lo) / sig,
                        "lvol": lv - pd.Series(lv).rolling(20, min_periods=10).mean().shift(1)})
    out["t"] = pd.to_datetime(out["ts"], unit="s", utc=True)
    out = out[np.isfinite(out["y"]) & (out["sig"] > 0) & (out["y"].abs() < 50)]
    return out.reset_index(drop=True)


def daily_family(syms: list[str]) -> pd.DataFrame:
    """Per-day averages across a family's series: y is averaged signed (only meaningful for one
    series), |y|, range and volume pooled."""
    frames = []
    for s in syms:
        df = load(s, "1d")
        if df is None:
            continue
        p = prepare(df)
        p["date"] = p["t"].dt.tz_localize(None).dt.normalize()
        p["sym"] = s
        frames.append(p)
    if not frames:
        return pd.DataFrame()
    allp = pd.concat(frames)
    allp = allp[allp["date"] >= DAILY_START]
    allp["ay"] = allp["y"].abs()
    g = allp.groupby("date")
    return pd.DataFrame({"y": g["y"].mean(), "ay": g["ay"].mean(), "rng": g["rng"].mean(),
                         "lvol": g["lvol"].mean(), "n": g.size()}).reset_index()


def usd_daily() -> pd.DataFrame:
    frames = []
    for s, sign in USD_SIGN.items():
        df = load(s, "1d")
        if df is None:
            continue
        p = prepare(df)
        p["date"] = p["t"].dt.tz_localize(None).dt.normalize()
        p["y"] = p["y"] * sign
        frames.append(p[["date", "y", "rng", "lvol"]])
    allp = pd.concat(frames)
    allp = allp[allp["date"] >= DAILY_START]
    allp["ay"] = allp["y"].abs()
    g = allp.groupby("date")
    return pd.DataFrame({"y": g["y"].mean(), "ay": g["ay"].mean(), "rng": g["rng"].mean(),
                         "lvol": g["lvol"].mean(), "n": g.size()}).reset_index()


def stock_symbols() -> list[str]:
    return sorted({p.name.rsplit(".", 2)[0] for p in SEQLAB.glob("*.1d.npz")
                   if re.search(r"\.(N|OQ)\.1d\.npz$", p.name)})


def walk_daily(kind: str, i: int) -> pd.DataFrame:
    """Our control, daily: iid Student-t(3) days on the FX calendar (weekdays) or every day."""
    rng = np.random.default_rng((3000 if kind == "fx" else 4000) + i)
    days = pd.date_range("2005-01-01", "2026-09-01", freq="D")
    if kind == "fx":
        days = days[days.weekday < 5]
    sd = 0.006 / sqrt(3.0)
    move = rng.standard_t(3, len(days)) * sd
    close = 100 * np.exp(np.cumsum(move))
    open_ = np.r_[100.0, close[:-1]]
    wick = np.abs(rng.standard_t(3, (len(days), 2))) * sd * 0.6
    df = pd.DataFrame({"ts": (days.asi8 // 10**9).astype(np.int64), "open": open_, "close": close,
                       "high": np.maximum(open_, close) * np.exp(wick[:, 0]),
                       "low": np.minimum(open_, close) * np.exp(-wick[:, 1]),
                       "volume": np.exp(rng.normal(0, 0.3, len(days)))})
    p = prepare(df)
    p["date"] = p["t"].dt.tz_localize(None).dt.normalize()
    p["ay"] = p["y"].abs()
    return p[["date", "y", "ay", "rng", "lvol"]].assign(n=1)


def walks(kind: str) -> pd.DataFrame:
    frames = [walk_daily(kind, i) for i in range(6)]
    allp = pd.concat(frames)
    g = allp.groupby("date")
    return pd.DataFrame({"y": g["y"].mean(), "ay": g["ay"].mean(), "rng": g["rng"].mean(),
                         "lvol": g["lvol"].mean(), "n": g.size()}).reset_index()


# ------------------------------------------------------------------------------------------ stats


def pvalue(t: float) -> float:
    return float(2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))) if np.isfinite(t) else 1.0


def bh(p: np.ndarray, q: float = 0.05) -> np.ndarray:
    order = np.argsort(p)
    m = len(p)
    ok = p[order] <= q * np.arange(1, m + 1) / m
    k = np.max(np.flatnonzero(ok)) + 1 if ok.any() else 0
    out = np.zeros(m, bool)
    out[order[:k]] = True
    return out


def expected_max(n: int) -> float:
    """The False Strategy Theorem's expected maximum of n standard normals."""
    if n < 2:
        return 0.0
    g = 0.5772156649
    z = NormalDist()
    return (1 - g) * z.inv_cdf(1 - 1 / n) + g * z.inv_cdf(1 - 1 / (n * np.e))


def adjust(fam: pd.DataFrame) -> pd.DataFrame:
    """Each measure minus its weekday mean: the weekly clock removed."""
    if fam.empty:
        return fam
    f = fam.copy()
    wd = f["date"].dt.weekday
    for col in ("y", "ay", "rng", "lvol"):
        f[col + "_a"] = f[col] - f.groupby(wd)[col].transform("mean")
    return f


def index_of(fam: pd.DataFrame, events: list[pd.Timestamp]) -> np.ndarray:
    """The row of each event day in a family's trading days (the next trading day if it was not
    one), or -1 outside the data."""
    dates = fam["date"].to_numpy()
    out = []
    for e in events:
        i = np.searchsorted(dates, np.datetime64(e))
        out.append(i if i < len(dates) and (dates[i] - np.datetime64(e)) <= np.timedelta64(3, "D")
                   else -1)
    return np.array(out)


MEASURES = {
    "V-pre": ("ay_a", range(-3, 0)), "V-post": ("ay_a", range(0, 3)), "R0": ("rng_a", range(0, 1)),
    "VOL0": ("lvol_a", range(0, 1)), "D0": ("y_a", range(0, 1)), "D-1": ("y_a", range(-1, 0)),
    "D-tom": ("y_a", range(-1, 4)),
}


def stat(fam: pd.DataFrame, rows: np.ndarray, col: str, offsets: range, summed: bool) -> np.ndarray:
    """Per-event value: mean (or sum, for drift windows) of `col` over the offsets."""
    v = fam[col].to_numpy()
    vals = []
    for i in rows:
        if i < 0:
            continue
        idx = [i + k for k in offsets if 0 <= i + k < len(v)]
        if len(idx) != len(offsets):
            continue
        w = v[idx]
        vals.append(np.nansum(w) if summed else np.nanmean(w))
    return np.array(vals)


def placebo(events: list[pd.Timestamp], rng: np.random.Generator) -> list[pd.Timestamp]:
    real = set(e.normalize() for e in events)
    out = []
    for e in events:
        for _ in range(20):
            shift = int(rng.integers(2, 9)) * int(rng.choice([-1, 1]))
            cand = e + pd.Timedelta(weeks=shift)
            if all(abs((cand - r).days) > 2 for r in real if abs((cand - r).days) < 60):
                out.append(cand)
                break
    return out


def study(fam: pd.DataFrame, events: list[pd.Timestamp], ritual: str, label: str,
          rng: np.random.Generator) -> list[dict]:
    """The event study for one ritual on one family, with placebo p-values and both halves."""
    if fam.empty:
        return []
    rows = index_of(fam, events)
    keep = rows >= 0
    if keep.sum() < 8:
        return []
    dates = np.array(events)[keep]
    rows = rows[keep]
    mid = fam["date"].iloc[len(fam) // 2]
    out = []
    names = ["V-pre", "V-post", "R0", "VOL0", "D-1", "D0"] + (["D-tom"] if ritual == "turn-of-month" else [])
    if label in ("fx", "deriv volatility", "deriv boom/crash"):
        names = [n for n in names if not n.startswith("D")]  # a signed average across series is noise
    placebo_rows = [index_of(fam, placebo(list(dates), rng)) for _ in range(PLACEBOS)]
    for name in names:
        col, offs = MEASURES[name]
        if col == "lvol_a" and not np.isfinite(fam[col]).any():
            continue
        summed = name.startswith("D")
        vals = stat(fam, rows, col, offs, summed)
        if len(vals) < 8 or not np.isfinite(vals).any():
            continue
        obs = float(np.nanmean(vals))
        null = np.array([np.nanmean(stat(fam, pr[pr >= 0], col, offs, summed)) for pr in placebo_rows])
        null = null[np.isfinite(null)]
        z = (obs - null.mean()) / null.std(ddof=1) if len(null) > 20 and null.std() > 0 else float("nan")
        p = float(np.mean(np.abs(null - null.mean()) >= abs(obs - null.mean()))) if len(null) > 20 else 1.0
        halves = []
        for part in (rows[[pd.Timestamp(d) < mid for d in dates]], rows[[pd.Timestamp(d) >= mid for d in dates]]):
            hv = stat(fam, part, col, offs, summed)
            halves.append(float(np.nanmean(hv)) if len(hv) else float("nan"))
        out.append({"ritual": ritual, "family": label, "test": name, "n": int(len(vals)),
                    "effect": obs, "placebo_mean": float(null.mean()) if len(null) else float("nan"),
                    "z": z, "p": max(p, 1 / (len(null) + 1)), "h1": halves[0], "h2": halves[1]})
    return out


# ------------------------------------------------------------------------------------------ intraday


def hourly(sym: str) -> pd.DataFrame | None:
    df = load(sym, "1h")
    if df is None:
        return None
    return prepare(df, intrabar=True)


def usd_hourly() -> pd.DataFrame:
    frames = []
    for s, sign in USD_SIGN.items():
        p = hourly(s)
        if p is None:
            continue
        frames.append(p[["ts", "y"]].assign(y=p["y"] * sign))
    allp = pd.concat(frames)
    g = allp.groupby("ts")["y"].mean().reset_index()
    g["t"] = pd.to_datetime(g["ts"], unit="s", utc=True)
    return g


def basket_hourly(syms: list[str]) -> pd.DataFrame:
    frames = []
    for s in syms:
        p = hourly(s)
        if p is not None:
            frames.append(p[["ts", "y"]])
    if not frames:
        return pd.DataFrame(columns=["ts", "y", "t"])
    g = pd.concat(frames).groupby("ts")["y"].mean().reset_index()
    g["t"] = pd.to_datetime(g["ts"], unit="s", utc=True)
    return g


def pre_fomc(series: pd.DataFrame, fomc: list[pd.Timestamp], label: str,
             rng: np.random.Generator) -> dict | None:
    """Summed y over the 24 hourly bars before the announcement, against placebo days."""
    if series.empty:
        return None
    s = series.set_index("t")["y"].sort_index()

    def window(day: pd.Timestamp) -> float:
        # 14:00 New York since 2013, 14:15 before: either way the bar starting 14:00 holds it
        ann = pd.Timestamp(year=day.year, month=day.month, day=day.day, hour=14, tz=NY).tz_convert("UTC")
        w = s[(s.index >= ann - pd.Timedelta(hours=24)) & (s.index < ann)]
        return float(w.sum()) if len(w) >= 12 else float("nan")

    first = s.index.min().tz_convert(None)
    events = [d for d in fomc if d >= first.normalize()]
    vals = np.array([window(d) for d in events])
    vals = vals[np.isfinite(vals)]
    if len(vals) < 5:
        return None
    null = []
    for _ in range(PLACEBOS):
        pv = np.array([window(d) for d in placebo(events, rng)])
        pv = pv[np.isfinite(pv)]
        if len(pv):
            null.append(pv.mean())
    null = np.array(null)
    obs = float(vals.mean())
    z = (obs - null.mean()) / null.std(ddof=1) if len(null) > 20 else float("nan")
    p = float(np.mean(np.abs(null - null.mean()) >= abs(obs - null.mean()))) if len(null) > 20 else 1.0
    half = len(vals) // 2
    return {"ritual": "pre-fomc 24h", "family": label, "test": "D-24h", "n": int(len(vals)),
            "effect": obs, "placebo_mean": float(null.mean()) if len(null) else float("nan"), "z": z,
            "p": max(p, 1 / (len(null) + 1)), "h1": float(vals[:half].mean()),
            "h2": float(vals[half:].mean())}


def fix_study(rng: np.random.Generator) -> list[dict]:
    """The month-end 4pm London fix on FX: bars starting 15:00 and 16:00 London, month-end days
    against other days, the weekday x London-hour clock removed."""
    out = []
    usd = usd_hourly()
    frames = {"usd": usd}
    pooled = []
    for s in FX:
        p = hourly(s)
        if p is not None:
            pooled.append(p[["ts", "y"]].assign(y=p["y"].abs()))
    if pooled:
        g = pd.concat(pooled).groupby("ts")["y"].mean().reset_index()
        g["t"] = pd.to_datetime(g["ts"], unit="s", utc=True)
        frames["fx |y|"] = g
    for label, f in frames.items():
        f = f.copy()
        lt = f["t"].dt.tz_convert(LONDON)
        f["wd"], f["hr"], f["date"] = lt.dt.weekday, lt.dt.hour, lt.dt.tz_localize(None).dt.normalize()
        f["ya"] = f["y"] - f.groupby(["wd", "hr"])["y"].transform("mean")
        ends = set()
        for y in range(2018, 2027):
            for m in range(1, 13):
                ends.add(last_business_day(y, m))
        at = f[f["hr"].isin((15, 16))]
        is_end = at["date"].isin(ends)
        for stat_name, col in (("fix |y|" if label == "usd" else "fix |y| pooled", "abs"),
                               ("fix drift", "signed")):
            if label == "fx |y|" and col == "signed":
                continue
            v = at["ya"].abs() if (col == "abs" and label == "usd") else at["ya"]
            daily = v.groupby(at["date"]).mean()
            ends_v = daily[daily.index.isin(ends)]
            other = daily[~daily.index.isin(ends)]
            if len(ends_v) < 8:
                continue
            obs = float(ends_v.mean() - other.mean())
            null = []
            others = other.index.to_numpy()
            for _ in range(PLACEBOS):
                pick = rng.choice(others, len(ends_v), replace=False)
                null.append(daily.loc[pick].mean() - other.mean())
            null = np.array(null)
            z = (obs - null.mean()) / null.std(ddof=1)
            p = float(np.mean(np.abs(null - null.mean()) >= abs(obs - null.mean())))
            half = len(ends_v) // 2
            out.append({"ritual": "month-end fix", "family": label, "test": stat_name,
                        "n": int(len(ends_v)), "effect": obs, "placebo_mean": float(null.mean()),
                        "z": z, "p": max(p, 1 / (PLACEBOS + 1)),
                        "h1": float(ends_v.iloc[:half].mean() - other.mean()),
                        "h2": float(ends_v.iloc[half:].mean() - other.mean())})
    return out


def funding_study() -> list[dict]:
    """Does the move into and out of a funding settlement scale with the funding rate, beyond the
    same regression at hours with no settlement?"""
    out = []
    for coin, sym in (("BTCUSDT", "BTCUSD"), ("ETHUSDT", "ETHUSD"), ("SOLUSDT", "SOLUSD")):
        path = CROWDING / f"{coin}.npz"
        p = hourly(sym)
        if not path.exists() or p is None:
            continue
        z = np.load(path)
        t = z["t"].astype(np.int64)
        t = t // 1000 if t[0] > 1e12 else t
        fund = pd.Series(z["funding"], index=pd.to_datetime(t, unit="s", utc=True)).sort_index()
        f = p[["t", "y"]].copy()
        f["hr"] = f["t"].dt.hour
        f["ya"] = f["y"] - f.groupby([f["t"].dt.weekday, "hr"])["y"].transform("mean")
        f["rate"] = fund.reindex(f["t"], method="ffill").to_numpy()
        f = f[np.isfinite(f["rate"])]
        sd = f["rate"].std()
        if not sd > 0:
            continue
        f["x"] = f["rate"] / sd
        for name, hours in (("into settlement", (23, 7, 15)), ("out of settlement", (0, 8, 16))):
            for label, mask in (("settlement", f["hr"].isin(hours)),
                                ("other hours", ~f["hr"].isin((23, 7, 15, 0, 8, 16)))):
                g = f[mask]
                if len(g) < 200:
                    continue
                x, yv = g["x"].to_numpy(), g["ya"].to_numpy()
                beta = float(np.cov(x, yv)[0, 1] / np.var(x))
                days = (g["t"].astype("int64") // 86_400_000_000_000).to_numpy()
                resid = yv - beta * x
                by = pd.Series(resid * (x - x.mean())).groupby(days).sum()
                se = float(np.sqrt((by**2).sum()) / ((x - x.mean()) ** 2).sum())
                half = len(g) // 2
                b1 = float(np.cov(x[:half], yv[:half])[0, 1] / np.var(x[:half]))
                b2 = float(np.cov(x[half:], yv[half:])[0, 1] / np.var(x[half:]))
                out.append({"ritual": f"funding {name}", "family": f"{sym} {label}",
                            "test": "slope on funding", "n": int(len(g)), "effect": beta,
                            "placebo_mean": float("nan"), "z": beta / se, "p": pvalue(beta / se),
                            "h1": b1, "h2": b2})
    return out


# ------------------------------------------------------------------------------------------ risk


def risk_test(fam: pd.DataFrame, rituals: dict[str, list[pd.Timestamp]], label: str) -> dict | None:
    """Next-day |y| forecast: the weekday profile against the weekday profile times a ritual
    multiplier fitted on the first 60% of days. Relative MSE on the last 40%, by half."""
    if fam.empty or len(fam) < 500:
        return None
    f = fam[["date", "ay"]].copy()
    f["wd"] = f["date"].dt.weekday
    cut = int(len(f) * 0.6)
    tr, te = f.iloc[:cut], f.iloc[cut:]
    wd_mean = tr.groupby("wd")["ay"].mean()
    f["base"] = f["wd"].map(wd_mean)
    flag = pd.Series("", index=f.index)
    for name, events in rituals.items():
        rows = index_of(f, events)
        for i in rows[rows >= 0]:
            flag.iloc[i] = flag.iloc[i] or name
    f["flag"] = flag
    # geometric: a mean of |y| ratios is dragged by a few outlier days
    ratio = np.log(np.maximum(tr["ay"], 1e-3) / f["base"].iloc[:cut])
    mult = np.exp(ratio.groupby(f["flag"].iloc[:cut]).mean())
    mult = mult / mult.get("", 1.0)
    f["with"] = f["base"] * f["flag"].map(mult).fillna(1.0)
    te = f.iloc[cut:]
    out = []
    for part in (te.iloc[: len(te) // 2], te.iloc[len(te) // 2 :]):
        a = float(np.mean((part["ay"] - part["with"]) ** 2) / np.mean((part["ay"] - part["base"]) ** 2))
        out.append(a)
    top = mult.drop("", errors="ignore").sort_values(ascending=False)
    return {"family": label, "rel_mse": out, "multipliers": {k: round(float(v), 3) for k, v in top.items()}}


# ------------------------------------------------------------------------------------------ trade


def trade(fam: pd.DataFrame, events: list[pd.Timestamp], test: str, label: str) -> dict:
    """A surviving drift test traded out of sample: sign from the first 60% of events, net of
    cost on the rest."""
    col, offs = MEASURES[test]
    rows = index_of(fam, events)
    rows = rows[rows >= 0]
    cut = int(len(rows) * 0.6)
    disc = stat(fam, rows[:cut], "y", offs, True)
    ver = stat(fam, rows[cut:], "y", offs, True)
    sign = np.sign(np.nanmean(disc)) or 1.0
    cost = COST_V.get(label, 0.15) * DAILY * len(offs)
    net = sign * ver - cost
    half = len(net) // 2

    def tt(v):
        return float(v.mean() / (v.std(ddof=1) / sqrt(len(v)))) if len(v) > 3 and v.std() > 0 else float("nan")

    return {"n": int(len(net)), "net": float(net.mean()), "t": tt(net), "t1": tt(net[:half]),
            "t2": tt(net[half:])}


# ------------------------------------------------------------------------------------------ main


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    rituals = computed(1990, 2026)
    rituals["fomc"] = fomc_dates()
    rituals.update(calendar_dates())
    print("rituals:", {k: len(v) for k, v in rituals.items()}, flush=True)
    print(f"fomc dates: {len(rituals['fomc'])}, first {rituals['fomc'][0].date() if rituals['fomc'] else None}",
          flush=True)

    fams: dict[str, pd.DataFrame] = {}
    for label, syms in FAMILIES.items():
        fams[label] = adjust(daily_family(syms))
    fams["usd"] = adjust(usd_daily())
    stocks = stock_symbols()
    fams["stocks"] = adjust(daily_family(stocks))
    fams["walks fx-calendar"] = adjust(walks("fx"))
    fams["walks 24/7"] = adjust(walks("247"))
    for label, f in fams.items():
        if not f.empty:
            print(f"  {label}: {len(f):,} days from {f['date'].min().date()} to {f['date'].max().date()}"
                  f"{f' ({len(stocks)} stocks, survivorship-biased)' if label == 'stocks' else ''}", flush=True)

    # which rituals are asked of which families
    ask = {
        "opex": ["stocks", "usd", "fx", "metals", "crypto"],
        "witching": ["stocks", "usd", "fx", "metals", "crypto"],
        "msci": ["stocks", "usd", "fx", "crypto"],
        "russell": ["stocks", "usd"],
        "month-end": ["usd", "fx", "metals", "crypto", "stocks"],
        "quarter-end": ["usd", "fx", "metals", "crypto", "stocks"],
        "turn-of-month": ["stocks", "usd", "metals", "crypto"],
        "fomc": ["usd", "fx", "metals", "crypto", "stocks"],
        "ecb": ["fx"], "boe": ["fx"], "boj": ["fx"],
        "nfp": ["usd", "fx", "metals", "crypto", "stocks"],
        "crypto-expiry": ["crypto"],
    }
    rows: list[dict] = []
    for ritual, targets in ask.items():
        events = rituals.get(ritual, [])
        for label in targets + ["deriv volatility", "deriv boom/crash", "walks fx-calendar", "walks 24/7"]:
            rows += study(fams.get(label, pd.DataFrame()), events, ritual, label, rng)
        print(f"  {ritual}: {len(events)} dates studied", flush=True)

    # pre-FOMC, daily proxy split at the working paper (2012) - y on day -1 on the USD proxy and gold
    early = [d for d in rituals["fomc"] if d.year < 2012]
    late = [d for d in rituals["fomc"] if d.year >= 2015]
    for label in ("usd", "metals"):
        for name, ev in (("pre-fomc day -1, before 2012", early), ("pre-fomc day -1, 2015 on", late)):
            for r in study(fams[label], ev, name, label, rng):
                if r["test"] == "D-1":
                    rows.append(r)

    # intraday
    intr: list[dict] = []
    for label, series in (("usd", usd_hourly()), ("stocks", basket_hourly(stocks))):
        r = pre_fomc(series, rituals["fomc"], label, rng)
        if r:
            intr.append(r)
    for sym in ("XAUUSD", "BTCUSD"):
        p = hourly(sym)
        if p is not None:
            r = pre_fomc(p[["t", "y"]], rituals["fomc"], sym, rng)
            if r:
                intr.append(r)
    intr += fix_study(rng)
    intr += funding_study()
    rows += intr

    res = pd.DataFrame(rows)
    real = ~res["family"].str.startswith(("walks", "deriv"))
    res["bh"] = False
    res.loc[real, "bh"] = bh(res.loc[real, "p"].to_numpy())
    res.to_csv(OUT / "results.csv", index=False)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 400)
    show = res.copy()
    for c in ("effect", "placebo_mean", "z", "h1", "h2"):
        show[c] = show[c].round(3)
    show["p"] = show["p"].round(4)
    print("\n" + "=" * 110)
    print("EVENT STUDY - effect minus weekday mean; p from placebo dates; halves split at the median date")
    for ritual, g in show.groupby("ritual", sort=False):
        print(f"\n== {ritual}")
        print(g.drop(columns=["ritual"]).to_string(index=False))

    n_tests = int(real.sum())
    emax = expected_max(n_tests)
    best = res[real].assign(az=res["z"].abs()).sort_values("az", ascending=False).head(10)
    print(f"\n{'=' * 110}\nDEFLATION: {n_tests} tests on markets; expected max |z| under the null "
          f"(False Strategy Theorem) {emax:.2f}")
    print(best[["ritual", "family", "test", "n", "effect", "z", "p", "bh", "h1", "h2"]].round(3).to_string(index=False))
    walks_best = res[res["family"].str.startswith("walks")].assign(az=res["z"].abs()).sort_values("az", ascending=False).head(5)
    print("\nlargest |z| on our walks (the null's reach):")
    print(walks_best[["ritual", "family", "test", "n", "z", "p"]].round(3).to_string(index=False))

    # trades for surviving drift tests
    print(f"\n{'=' * 110}\nTRADES - drift tests surviving BH, sign from the first 60% of events, net")
    surv = res[real & res["bh"] & res["test"].str.startswith("D") & ~res["ritual"].str.contains("24h|fix|funding|pre-fomc")]
    if surv.empty:
        print("  none survive BH")
    for _, r in surv.iterrows():
        t = trade(fams[r["family"]], rituals[r["ritual"]], r["test"], r["family"])
        wk = trade(fams["walks fx-calendar"], rituals[r["ritual"]], r["test"], "walks")
        print(f"  {r['ritual']:14s} {r['family']:8s} {r['test']:6s} n={t['n']} net {t['net']:+.3f} "
              f"t {t['t']:+.1f} halves {t['t1']:+.1f}/{t['t2']:+.1f} | walks t {wk['t']:+.1f}")

    # risk
    print(f"\n{'=' * 110}\nRISK - next-day |y|: weekday profile x ritual multiplier against the profile alone")
    rset = {k: rituals[k] for k in ("opex", "witching", "msci", "month-end", "quarter-end", "fomc",
                                     "nfp", "ecb", "boe", "boj", "crypto-expiry")}
    for label in ("usd", "fx", "metals", "crypto", "stocks", "deriv volatility", "walks fx-calendar",
                  "walks 24/7"):
        r = risk_test(fams.get(label, pd.DataFrame()), rset, label)
        if r:
            print(f"  {label:18s} relative MSE {r['rel_mse'][0]:.4f} / {r['rel_mse'][1]:.4f} | "
                  f"multipliers {r['multipliers']}")
    (OUT / "done.json").write_text(json.dumps({"tests": n_tests, "expected_max": emax}))


if __name__ == "__main__":
    main()
