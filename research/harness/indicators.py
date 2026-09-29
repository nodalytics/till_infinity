"""Do lagging indicators time entries at structure zones better than taking the touch?

The desk's framing: nobody trades support and resistance as such. A level is a *zone of interest*,
and an indicator is what times the entry inside it. Structures supplies the zones; this measures
whether EMA, SMA, RSI, stochastic, stoch-RSI, Bollinger bands, MACD or a Fibonacci retracement add
anything to the entry.

Zones: every touch the production `Engine` opens, replayed over the lab's bars exactly as `skill.py`
does (15m and 1h interleaved in time, one engine per universe). The trade fades the arrival - long
when price came down onto the level, short when it came up - the direction a zone entry takes. The
break direction is the same numbers with the sign flipped.

Entries, each on the zone's touch at bar i, entering at the close of the trigger bar j in
[i, i + WINDOW], no trade if it never triggers (long shown; short mirrors):

  touch      j = i                                                    the baseline
  rsi        RSI(14) crosses up through 30
  stoch      %K(14,3) crosses above %D(3) with %K below 20
  stochrsi   stochastic of RSI(14), %K(3) above %D(3) with %K below 20
  bb         a close back inside the lower band (20, 2) after a close below it
  ema        close crosses above EMA(9)
  sma        close crosses above SMA(20)
  macd       the MACD(12, 26) line crosses above its signal(9)
  fib        j = i, only when the level sits within FIB_TOL of the 38.2 / 50 / 61.8% retracement of
             the swing over the last SWING bars - a zone filter, not a trigger
  fib+rsi    both

Outcome: the signed log return from the entry close over H = 5 and 20 bars, in units of the bar's
causal volatility (EWMA of |log return|, scaled to a standard deviation), less the round-trip cost.
A target/stop label is not used: a barrier trade earns only drift, so the signed return is the P&L.

Each indicator is compared, on the same family, interval and horizon, with two baselines. Both are
unbiased on a martingale, because they only count returns *after* the entry bar (optional
stopping):

  vs touch   every touch, entered at the touch
  vs wait    every touch, entered after a delay drawn from the indicator's own delays but
             independent of the path: is it the signal that helps, or only the waiting?

(A first version split each result into "selection" and "timing" by re-entering the triggered
touches at the touch or at shuffled delays. Those returns span the path that fired the trigger, so
they are biased by construction: on memoryless walks they read t = 12-25. They were dropped.)

Controls:

  walks      the same engine, indicators and scoring on walks we generate ourselves - iid
             Student-t(3) returns at a fixed scale, memoryless by construction. Deriv synthetics
             are **not** a control; they are scored as a market ("deriv")
  placebo    random bars, fading the last 5 bars' move as a touch fades the approach, instead of
             the engine's zones

Pre-registered: an indicator improves entries on a family if its net mean beats both baselines by
at least 0.05 vol with t >= 3 (standard errors clustered by series-day), beats the touch in both halves of the time split, and the
walks show no such improvement.

Run on the lab (one process per universe):
  UNIVERSE=real  SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/indicators.py
  UNIVERSE=deriv ...    UNIVERSE=walks ...    then  PART=report
"""
from __future__ import annotations

import heapq
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

from till_infinity.structures.engine import Engine

UNIVERSE = os.environ.get("UNIVERSE", "real")
PART = os.environ.get("PART", "run")
OUT = Path(os.environ.get("OUT", ".data/indicators"))
START = pd.Timestamp(os.environ.get("START", "2025-01-01"), tz="UTC").timestamp()
INTERVALS = ("15m", "1h")
MINUTES = {"15m": 15, "1h": 60}

FAMILY = {
    "EURUSD": "fx", "GBPUSD": "fx", "USDJPY": "fx", "AUDUSD": "fx", "USDCAD": "fx", "EURJPY": "fx",
    "GBPJPY": "fx", "XAUUSD": "metals", "XAGUSD": "metals", "BTCUSD": "crypto", "ETHUSD": "crypto",
    "Volatility_75_Index": "deriv", "Volatility_25_Index": "deriv", "Jump_50_Index": "deriv",
    "Step_Index": "deriv", "Boom_1000_Index": "deriv", "Crash_1000_Index": "deriv",
}
SYMBOLS = {
    "real": [s for s, f in FAMILY.items() if f != "deriv"],
    "deriv": [s for s, f in FAMILY.items() if f == "deriv"],
    "walks": [f"walk_{i}" for i in range(6)],
}
#: Round-trip cost in units of 5-minute volatility, scaled to the interval by sqrt(5 / minutes).
COST_V = {"fx": 0.8, "metals": 0.16, "crypto": 0.5, "deriv": 0.15, "walks": 0.15}

WINDOW = 8
HORIZONS = (5, 20)
SWING = 50
FIB_TOL = 0.5  # in bar volatilities of price
RULES = ("touch", "rsi", "stoch", "stochrsi", "bb", "ema", "sma", "macd", "fib", "fib+rsi")
PLACEBO_PER_SERIES = 3_000


# ---------------------------------------------------------------------------------------- the bars

def walk_frame(i: int, interval: str) -> pd.DataFrame:
    """Our own control: iid Student-t(3) moves at one scale, with wicks, from START to END."""
    rng = np.random.default_rng(1_000 * i + MINUTES[interval])
    step = MINUTES[interval] * 60
    n = int((pd.Timestamp(os.environ.get("END", "2026-09-01"), tz="UTC").timestamp() - START) // step)
    close = 100 * np.exp(np.cumsum(rng.standard_t(3, n) * 0.001 * np.sqrt(MINUTES[interval] / 15)))
    open_ = np.r_[100.0, close[:-1]]
    wick = np.abs(rng.standard_t(3, (n, 2))) * 0.0005 * np.sqrt(MINUTES[interval] / 15)
    return pd.DataFrame({
        "ts": (START + step * np.arange(n)).astype(np.int64),
        "open": open_, "close": close,
        "high": np.maximum(open_, close) * np.exp(wick[:, 0]),
        "low": np.minimum(open_, close) * np.exp(-wick[:, 1]),
    })


def frame(sym: str, iv: str) -> pd.DataFrame | None:
    if sym.startswith("walk_"):
        return walk_frame(int(sym.split("_")[1]), iv)
    try:
        df = spikerisk.load(None, sym, "SEQLAB", iv)
    except (ValueError, FileNotFoundError) as exc:
        print(f"  skip {sym} {iv}: {str(exc)[:60]}", flush=True)
        return None
    return df[df["ts"] >= START].reset_index(drop=True)


def bars_of(sym, iv, df):
    """A function, so `sym` and `iv` bind now, not after the loop has moved on."""
    for t, h, lo, c in zip(df["ts"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy(),
                           df["close"].to_numpy(), strict=True):
        yield {"feed": sym.lower(), "venue": "SEQLAB", "interval": iv, "time": int(t),
               "high": float(h), "low": float(lo), "close": float(c)}


# ---------------------------------------------------------------------------------------- the zones

def zones(frames: dict) -> list[dict]:
    """Every touch the production engine opens, in time order across all series."""
    engine = Engine(intervals=INTERVALS)
    engine.consensus.single_source = frozenset(s.lower() for s, _ in frames)
    stream = heapq.merge(*(bars_of(s, iv, df) for (s, iv), df in frames.items()),
                         key=lambda b: (b["time"], b["interval"]))
    out, seen = [], set()
    for n, bar in enumerate(stream):
        for call in engine.observe_bar(bar):
            touch = engine.tracker.open_touch(call.level)
            if touch is None or touch.started != call.time:
                continue
            k = (call.feed, call.interval, round(touch.level_price, 8), touch.started)
            if k in seen:
                continue
            seen.add(k)
            out.append({"feed": call.feed, "interval": call.interval, "time": int(call.time),
                        "level": float(touch.level_price),
                        "above": touch.features.side.name == "ABOVE"})
        if n % 50_000 == 0:
            print(f"  {n:,} bars, {len(out):,} touches", flush=True)
    return out


# ---------------------------------------------------------------------------------------- indicators

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down.replace(0, np.nan))


def indicators(df: pd.DataFrame) -> dict[str, np.ndarray]:
    c, h, lo = df["close"], df["high"], df["low"]
    r = rsi(c)
    k = 100 * (c - lo.rolling(14).min()) / (h.rolling(14).max() - lo.rolling(14).min())
    k = k.rolling(3).mean()
    rk = 100 * (r - r.rolling(14).min()) / (r.rolling(14).max() - r.rolling(14).min())
    rk = rk.rolling(3).mean()
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    logr = np.log(c).diff().abs()
    vol = logr.ewm(span=14, adjust=False).mean().shift(0) * np.sqrt(np.pi / 2)
    return {
        "close": c.to_numpy(), "vol": vol.to_numpy(), "rsi": r.to_numpy(),
        "k": k.to_numpy(), "d": k.rolling(3).mean().to_numpy(),
        "rk": rk.to_numpy(), "rd": rk.rolling(3).mean().to_numpy(),
        "bb_lo": (mid - 2 * sd).to_numpy(), "bb_hi": (mid + 2 * sd).to_numpy(),
        "ema": c.ewm(span=9, adjust=False).mean().to_numpy(), "sma": mid.to_numpy(),
        "macd": macd.to_numpy(), "signal": macd.ewm(span=9, adjust=False).mean().to_numpy(),
        "hh": h.rolling(SWING).max().to_numpy(), "ll": lo.rolling(SWING).min().to_numpy(),
    }


def triggered(rule: str, x: dict, j: int, s: int) -> bool:
    """Whether `rule` fires on bar j for a trade in direction s (+1 long, -1 short)."""
    if j < 1:
        return False
    c = x["close"]
    if rule == "rsi":
        lo, hi = (30, 70)
        return (x["rsi"][j - 1] < lo <= x["rsi"][j]) if s > 0 else (x["rsi"][j - 1] > hi >= x["rsi"][j])
    if rule in ("stoch", "stochrsi"):
        kk, dd = (x["k"], x["d"]) if rule == "stoch" else (x["rk"], x["rd"])
        crossed = s * (kk[j] - dd[j]) > 0 >= s * (kk[j - 1] - dd[j - 1])
        return bool(crossed and ((kk[j] < 20) if s > 0 else (kk[j] > 80)))
    if rule == "bb":
        band = x["bb_lo"] if s > 0 else x["bb_hi"]
        return bool(s * (c[j - 1] - band[j - 1]) < 0 <= s * (c[j] - band[j]))
    if rule in ("ema", "sma"):
        m = x[rule]
        return bool(s * (c[j - 1] - m[j - 1]) <= 0 < s * (c[j] - m[j]))
    if rule == "macd":
        g = x["macd"] - x["signal"]
        return bool(s * g[j - 1] <= 0 < s * g[j])
    raise ValueError(rule)


def near_fib(x: dict, i: int, level: float) -> bool:
    hh, ll = x["hh"][i], x["ll"][i]
    if not np.isfinite(hh) or not np.isfinite(ll) or hh <= ll:
        return False
    tol = FIB_TOL * x["vol"][i] * x["close"][i]
    return any(abs(level - (hh - f * (hh - ll))) <= tol for f in (0.382, 0.5, 0.618))


def entry(rule: str, x: dict, i: int, s: int, level: float) -> int | None:
    """The bar a rule enters on for the touch at bar i, or None."""
    if rule == "touch":
        return i
    if rule == "fib":
        return i if near_fib(x, i, level) else None
    if rule == "fib+rsi":
        return entry("rsi", x, i, s, level) if near_fib(x, i, level) else None
    for j in range(i, min(i + WINDOW + 1, len(x["close"]))):
        if triggered(rule, x, j, s):
            return j
    return None


# ---------------------------------------------------------------------------------------- scoring

def signed(x: dict, j: int, s: int, h: int) -> float | None:
    c, v = x["close"], x["vol"]
    if j + h >= len(c) or not np.isfinite(v[j]) or v[j] <= 0:
        return None
    return float(s * np.log(c[j + h] / c[j]) / v[j])


def trades(frames: dict, touches: list[dict], universe: str) -> list[dict]:
    """One row per (touch, rule, horizon), with the controls needed for the decomposition."""
    xs = {(s.lower(), iv): (indicators(df), df["ts"].to_numpy()) for (s, iv), df in frames.items()}
    fam_of = {s.lower(): (FAMILY.get(s, "walks")) for s, _ in frames}
    rng = np.random.default_rng(7)
    rows = []

    def add(kind, feed, iv, t, i, s, level):
        x, _ = xs[(feed, iv)]
        cost = COST_V[fam_of[feed]] * np.sqrt(5 / MINUTES[iv])
        for rule in RULES:
            j = entry(rule, x, i, s, level)
            if j is None:
                continue
            for h in HORIZONS:
                at_entry = signed(x, j, s, h)
                if at_entry is None:
                    continue
                rows.append({"kind": kind, "family": fam_of[feed], "feed": feed, "interval": iv,
                             "time": t, "rule": rule, "h": h, "delay": j - i, "i": i, "s": s,
                             "gross": at_entry, "net": at_entry - cost, "cost": cost})

    for z in touches:
        # A pivot level ("daily") is touched on the bar series that fired it: the bar series
        # with a bar at that time, shortest first.
        options = [z["interval"]] if z["interval"] in MINUTES else list(INTERVALS)
        for iv in options:
            if (z["feed"], iv) not in xs:
                continue
            x, ts = xs[(z["feed"], iv)]
            i = int(np.searchsorted(ts, z["time"]))
            if i < len(ts) and ts[i] == z["time"] and i >= SWING:
                add("zone", z["feed"], iv, z["time"], i, 1 if z["above"] else -1, z["level"])
                break
    for (feed, iv), (x, ts) in xs.items():  # placebo: random bars, fading the last 5 bars' move
        span = np.arange(SWING, len(ts) - 25)
        for i in rng.choice(span, min(PLACEBO_PER_SERIES, len(span)), replace=False):
            s = -1 if x["close"][i] > x["close"][i - 5] else 1
            add("placebo", feed, iv, int(ts[i]), int(i), s, float(x["close"][i]))
    # the random-wait baselines: every touch, entered after a delay drawn from each rule's delays,
    # independent of the path
    df = pd.DataFrame(rows)
    waits = []
    for (kind, rule, h), g in df.groupby(["kind", "rule", "h"]):
        if rule in ("touch", "fib"):
            continue
        base = df[(df["kind"] == kind) & (df["rule"] == "touch") & (df["h"] == h)]
        delays = rng.choice(g["delay"].to_numpy(), len(base))
        for (_, b), d in zip(base.iterrows(), delays, strict=True):
            x, _ = xs[(b["feed"], b["interval"])]
            got = signed(x, int(b["i"] + d), int(b["s"]), int(h))
            if got is not None:
                waits.append({**b.to_dict(), "rule": f"wait:{rule}", "delay": int(d),
                              "gross": got, "net": got - b["cost"]})
    df = pd.concat([df, pd.DataFrame(waits)], ignore_index=True)
    return df.drop(columns=["i"]).to_dict("records")


def run() -> None:
    frames = {}
    for sym in SYMBOLS[UNIVERSE]:
        for iv in INTERVALS:
            df = frame(sym, iv)
            if df is not None and len(df) > 2 * SWING:
                frames[(sym, iv)] = df
    print(f"{UNIVERSE}: {len(frames)} series", flush=True)
    touches = zones(frames)
    print(f"{UNIVERSE}: {len(touches):,} zone touches", flush=True)
    rows = trades(frames, touches, UNIVERSE)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_pickle(OUT / f"{UNIVERSE}.pkl.gz")
    print(f"{UNIVERSE}: {len(rows):,} trade rows written", flush=True)


def _mean_se(g: pd.DataFrame) -> tuple[float, float, int]:
    """Mean of `net` and its standard error clustered by series-day: overlapping horizons and
    touches on the same day are not independent draws."""
    g = g[np.isfinite(g["net"])]
    if len(g) < 3:
        return float("nan"), float("nan"), len(g)
    m = g["net"].mean()
    cluster = g["feed"] + "|" + g["interval"] + "|" + (g["time"] // 86_400).astype(str)
    sums = (g["net"] - m).groupby(cluster).sum()
    return float(m), float(np.sqrt((sums**2).sum()) / len(g)), len(g)


def welch(a: pd.DataFrame, b: pd.DataFrame) -> tuple[float, float]:
    """Difference of means and its t, from clustered standard errors."""
    ma, sa, na = _mean_se(a)
    mb, sb, nb = _mean_se(b)
    if na < 3 or nb < 3:
        return float("nan"), float("nan")
    return ma - mb, (ma - mb) / np.sqrt(sa**2 + sb**2)


def report() -> None:
    df = pd.concat([pd.read_pickle(p) for p in sorted(OUT.glob("*.pkl.gz"))], ignore_index=True)
    cut = df["time"].quantile(0.6)
    print("net mean return after costs, in bar volatilities; zone touches unless marked placebo")
    print("vs touch / vs wait: difference from every touch entered at the touch / after a random wait")
    for (kind, family, iv, h), g in df.groupby(["kind", "family", "interval", "h"]):
        base = g[g["rule"] == "touch"]
        print(f"\n== {kind} · {family} · {iv} · H={h} · touch n={len(base):,}"
              f" net {base['net'].mean():+.3f} · hit {np.mean(base['net'] > 0):.1%}")
        for rule in RULES[1:]:
            r = g[g["rule"] == rule]
            if len(r) < 50:
                continue
            dt, tt = welch(r, base)
            wait = g[g["rule"] == f"wait:{rule}"]
            dw, tw = welch(r, wait) if len(wait) else (float("nan"), float("nan"))
            halves = []
            for part in (g[g["time"] < cut], g[g["time"] >= cut]):
                halves.append(welch(part[part["rule"] == rule], part[part["rule"] == "touch"])[0])
            print(f"  {rule:9s} n={len(r):7,} ({len(r) / max(len(base), 1):5.1%})"
                  f" net {r['net'].mean():+.3f}"
                  f" | vs touch {dt:+.3f} (t {tt:+.1f}) | vs wait {dw:+.3f} (t {tw:+.1f})"
                  f" | halves {halves[0]:+.3f} / {halves[1]:+.3f} | hit {np.mean(r['net'] > 0):.1%}"
                  f" | delay {r['delay'].mean():.1f}")


if __name__ == "__main__":
    report() if PART == "report" else run()
