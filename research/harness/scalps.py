"""Can anything be scalped on this venue at 1 to 15 minutes?

    ./.secrets/lab.sh run research/harness/scalps.py
    ./.secrets/lab.sh run research/harness/scalps.py CLOCKS=3 FAMILIES=ema_pullback

Run `scalp_cost.py` first; this refuses the cells that screen reports dead.

Four families were asked for. **Two cannot be built from this feed**, so they
are refused here rather than approximated:

* **Order flow and tape reading.** `positioning.md`: the broker feed "gives a
  spread and nothing behind it - no order book, no depth, no resting size". The
  terminal says the same in its own specification: `ticks_bookdepth` reads
  **0** on every symbol asked. There is no DOM to read absorption off and no
  trade tape to read size or speed off. Not attempted and not approximated.
* **VWAP, and the volume-surge confirmation.** `real_volume` is **0 on 80,000
  of 80,000 M1 bars** across four symbols asked directly, and `tick_volume` is
  a count of dealer quote updates, not size: on Step Index it reads median 60,
  min 17, **max 62** a minute, which is a one-per-second publication clock
  rather than activity. A "VWAP" weighted by that is a time-weighted average
  price wearing a volume-weighted one's name, which is the argument
  `node/desks.py` makes when it refuses `VOLUME` bars. So the middle Bollinger
  band is the reversion target and a hold beyond the level is the breakout
  confirmation. Nothing is substituted for volume.

## The rules, frozen

Context is **M15** throughout, read from the last M15 bar that had **closed**
before the execution bar opened. Execution is 1m / 3m / 5m / 15m aggregated
from M1 on wall-clock buckets, so a bucket never spans a session gap and the
15-minute grid is the real one.

| family | long condition on the execution clock |
|---|---|
| `ema_pullback` | EMA9 > EMA21, the bar's low touches EMA9, close back above EMA9 and above EMA21 |
| `candle_momentum` | body >= 1.0 ATR and body/range >= 0.60, up bar |
| `bb_reversion` | close below BB(20,2) lower, next close back inside, RSI(4) <= 25 at the excursion |
| `bb_to_mid` | the same entry, targeting the **middle band** instead of 2 ATR |
| `orb` | first break of the session's opening 15 minutes, with the next bar still closing beyond |
| `level_break` | close beyond the prior 20-bar extreme, with the next bar still closing beyond |

Shorts mirror. Entry is the **next bar's open**, stop **1 ATR(14)** as measured
at the signal bar, target **2 ATR** - 1:2, the geometry the brief names and the
one that makes cost worst. Barriers are checked on the wicks with the **stop
winning a tie**: one bar can span both, and assuming the favourable side is how
a backtest invents an edge. Maximum hold 40 bars, one position at a time, next
signal refused until the open one has exited.

Net R subtracts `round_trip / risk` **per trade**, with the risk that trade
used rather than a median: cost in R is set by the stop and the stop moves with
ATR.

## Arms, and what each one answers

| arm | the question |
|---|---|
| `rule` | the rule as stated, M15 filter on |
| `nofilter` | the same rule with the M15 filter **removed** |
| `inverted` | the same rule with the M15 filter **inverted** |
| `filter_random` | a random filter keeping the M15 filter's own share: the duty-cycle twin, because on a losing book anything that trades less looks better |
| `coin` | the rule's own entry bars, geometry and cost, **random side** |
| `random_time` | random entry bars at the rule's count, sides at the rule's mix |
| `stale` | the rule's signal acted on 3 bars late: if this reads the same, the signal carried no timing |

`rule` and `inverted` partition `nofilter`, so the three together answer whether
the context filter earns its place or only halves the sample.

## What would have gone wrong

A first version read the context with `searchsorted(m15_open, t) - 1`, which at
10:03 returns the M15 bar that opened at 10:00 and closes at **10:15** - a
filter that knows the next twelve minutes. The fix is to search the M15 bars'
*ends*. The same version paired the stale arm's entries with the unfiltered
arm's sides, which silently mislabels every stale trade once the filter rejects
anything.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from research.harness.venue import quoted

HOME = Path.home() / "till_infinity" / "data"
STORES = (HOME / "scalp", HOME / "fastsyn", HOME / "fast")
OUT = Path.home() / "till_infinity" / "logs" / "scalps.json"

CLOCKS = tuple(int(c) for c in os.environ.get("CLOCKS", "1,3,5,15").split(","))
FAMILIES = tuple(
    f.strip()
    for f in os.environ.get(
        "FAMILIES", "ema_pullback,candle_momentum,bb_reversion,bb_to_mid,orb,level_break"
    ).split(",")
    if f.strip()
)
ONLY = tuple(s for s in os.environ.get("SYMBOLS", "").split(",") if s.strip())
ARMS = ("rule", "nofilter", "inverted", "filter_random", "coin", "random_time", "stale")

ATR_N = 14
FAST_N, SLOW_N = 9, 21
BB_N, BB_K = 20, 2.0
RSI_N = 4
RSI_FLOOR = 25.0
BODY_ATR = 1.0
BODY_SHARE = 0.60
BREAK_N = 20
OR_SECONDS = 900
SESSION_GAP = 3600
HOLD = 40
STALE = 3
TARGET_R = 2.0
RISK_LIMIT = 0.16
DRAWS = 2000
TWIN_DRAWS = 500
SEED = 20261108
DAY_LOSS_LIMIT = -3.0
TRADES_PER_DAY = 5
PLANTS = (0.01, 0.02, 0.05, 0.10, 0.20)
MIN_SIGNALS = 40
THIN = 100


# ---------------------------------------------------------------- indicators
# Each is causal: the value at bar i uses bars up to and including i, and the
# entry happens at i+1. `tests/test_scalps.py` pins all four against
# `nautilus_trader`'s own, because a single off-by-one here is the study.


def ema(values: np.ndarray, n: int) -> np.ndarray:
    alpha = 2.0 / (n + 1.0)
    out = np.empty(len(values))
    run = float(values[0])
    for i in range(len(values)):
        run += alpha * (float(values[i]) - run)
        out[i] = run
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev = np.concatenate(([close[0]], close[:-1]))
    return np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = ATR_N) -> np.ndarray:
    """Wilder's ATR, `nan` until warm."""
    tr = true_range(high, low, close)
    out = np.full(len(tr), np.nan)
    if len(tr) <= n:
        return out
    run = float(tr[1 : n + 1].mean())
    out[n] = run
    for i in range(n + 1, len(tr)):
        run = (run * (n - 1) + tr[i]) / n
        out[i] = run
    return out


def rsi(close: np.ndarray, n: int = RSI_N) -> np.ndarray:
    """Wilder's RSI, `nan` until warm, 50.0 on a flat stretch rather than 0/0."""
    out = np.full(len(close), np.nan)
    if len(close) <= n:
        return out
    diff = np.diff(close, prepend=close[0])
    gain = float(np.clip(diff[1 : n + 1], 0, None).mean())
    loss = float(np.clip(-diff[1 : n + 1], 0, None).mean())
    out[n] = 50.0 if gain + loss == 0 else 100.0 * gain / (gain + loss)
    for i in range(n + 1, len(close)):
        gain = (gain * (n - 1) + max(float(diff[i]), 0.0)) / n
        loss = (loss * (n - 1) + max(-float(diff[i]), 0.0)) / n
        out[i] = 50.0 if gain + loss == 0 else 100.0 * gain / (gain + loss)
    return out


def bands(close: np.ndarray, n: int = BB_N, k: float = BB_K):
    """Rolling mean and population sd of the close, `nan` until warm."""
    mid = np.full(len(close), np.nan)
    lower = np.full(len(close), np.nan)
    upper = np.full(len(close), np.nan)
    if len(close) < n:
        return mid, lower, upper
    csum = np.concatenate(([0.0], np.cumsum(close)))
    csq = np.concatenate(([0.0], np.cumsum(close * close)))
    at = np.arange(n - 1, len(close))
    means = (csum[at + 1] - csum[at + 1 - n]) / n
    var = np.maximum((csq[at + 1] - csq[at + 1 - n]) / n - means * means, 0.0)
    sd = np.sqrt(var)
    mid[at], lower[at], upper[at] = means, means - k * sd, means + k * sd
    return mid, lower, upper


# ------------------------------------------------------------------ the bars


def m1_sources() -> dict[str, Path]:
    """One M1 file per symbol, deepest store first so a cell is never measured
    on 20,000 bars when 300,000 exist."""
    found: dict[str, Path] = {}
    for folder in STORES:
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.1m.npz")):
            found.setdefault(path.name[: -len(".1m.npz")], path)
    return {k: v for k, v in found.items() if not ONLY or k in ONLY}


def clock_bars(m1: dict[str, np.ndarray], k: int) -> dict[str, np.ndarray]:
    """k-minute bars on **wall-clock buckets**, not on counts of M1 bars.

    Counting bars lets one bucket span a weekend on an index and misaligns the
    15-minute grid, which is what decides where an opening range starts.
    """
    bucket = (m1["time"] // (k * 60)).astype(np.int64)
    starts = np.flatnonzero(np.concatenate(([True], bucket[1:] != bucket[:-1])))
    ends = np.concatenate((starts[1:], [len(bucket)]))
    return {
        "time": (bucket[starts] * (k * 60)).astype(np.float64),
        "open": m1["open"][starts],
        "high": np.maximum.reduceat(m1["high"], starts),
        "low": np.minimum.reduceat(m1["low"], starts),
        "close": m1["close"][ends - 1],
    }


def context(bars: dict[str, np.ndarray], m15: dict[str, np.ndarray]) -> np.ndarray:
    """+1 / -1 / 0 for the M15 EMA9-vs-EMA21 trend, with no look-ahead.

    Searched on the M15 bars' **ends**. Searching their opens attaches the
    10:00-10:15 bar to a 10:03 execution bar and hands the filter the next
    twelve minutes - the one defect that would have produced an edge here.
    """
    fast, slow = ema(m15["close"], FAST_N), ema(m15["close"], SLOW_N)
    sign = np.sign(fast - slow)
    sign[: SLOW_N * 2] = 0.0
    closed = np.searchsorted(m15["time"] + 900.0, bars["time"], side="right") - 1
    out = np.zeros(len(bars["time"]))
    live = closed >= 0
    out[live] = sign[closed[live]]
    return out


def sessions(m1_time: np.ndarray, clock_time: np.ndarray) -> tuple[np.ndarray, bool]:
    """Each execution bar's session start, and whether the sessions are real.

    A real session boundary is a gap of more than an hour in the M1 feed. A
    Deriv synthetic quotes continuously and has none, so its "session" is a
    midnight this venue does not observe - which makes an opening range on one
    **a control that must read nothing** rather than a strategy. The flag says
    which it is, and the report prints it per cell.
    """
    gaps = np.flatnonzero(np.diff(m1_time) > SESSION_GAP)
    span_days = max((m1_time[-1] - m1_time[0]) / 86400.0, 1.0)
    real = len(gaps) >= span_days * 0.4
    opens = (
        np.concatenate(([m1_time[0]], m1_time[gaps + 1]))
        if real
        else np.unique((clock_time // 86400.0) * 86400.0)
    )
    at = np.searchsorted(opens, clock_time, side="right") - 1
    start = np.where(at >= 0, opens[np.maximum(at, 0)], np.nan)
    return start, bool(real)


# --------------------------------------------------------------- the signals
# Each returns (bar indices, sides) for every signal the rule fires, before any
# context filter, so the filter arms select from one list and cannot differ
# from each other by anything else.


def _pair(up: np.ndarray, down: np.ndarray, f) -> tuple[np.ndarray, np.ndarray]:
    """Indices and sides, dropping bars with no warm stop and bars where both
    sides fire - a rule that is long and short at once has no direction, and
    picking one would be a choice the rule did not make."""
    warm = np.isfinite(f["atr"]) & (f["atr"] > 0)
    both = up & down
    up, down = up & ~both & warm, down & ~both & warm
    index = np.flatnonzero(up | down)
    index = index[index + 2 < len(f["close"])]
    return index, np.where(up[index], 1, -1).astype(int)


def ema_pullback(f):
    fast, slow, close = f["fast"], f["slow"], f["close"]
    up = (fast > slow) & (f["low"] <= fast) & (close > fast) & (close > slow)
    down = (fast < slow) & (f["high"] >= fast) & (close < fast) & (close < slow)
    return _pair(up, down, f)


def candle_momentum(f):
    body = f["close"] - f["open"]
    span = np.maximum(f["high"] - f["low"], 1e-12)
    big = (np.abs(body) >= BODY_ATR * f["atr"]) & (np.abs(body) / span >= BODY_SHARE)
    return _pair(big & (body > 0), big & (body < 0), f)


def bb_reversion(f):
    close, lower, upper, hot = f["close"], f["lower"], f["upper"], f["rsi"]
    out_low = np.concatenate(([False], close[:-1] < lower[:-1]))
    out_high = np.concatenate(([False], close[:-1] > upper[:-1]))
    before = np.concatenate(([np.nan], hot[:-1]))
    up = out_low & (close > lower) & (before <= RSI_FLOOR)
    down = out_high & (close < upper) & (before >= 100.0 - RSI_FLOOR)
    return _pair(up, down, f)


def level_break(f):
    """A close beyond the prior 20-bar extreme that the next bar holds.

    The hold is the confirmation the brief asks for in place of a volume surge,
    and it costs a bar: the signal is dated at the holding bar, so the entry is
    two bars after the break itself.
    """
    high, low, close = f["high"], f["low"], f["close"]
    n = len(close)
    top = np.full(n, np.nan)
    bottom = np.full(n, np.nan)
    if n <= BREAK_N + 2:
        return np.array([], dtype=int), np.array([], dtype=int)
    top[BREAK_N:] = np.lib.stride_tricks.sliding_window_view(high[:-1], BREAK_N).max(axis=1)
    bottom[BREAK_N:] = np.lib.stride_tricks.sliding_window_view(low[:-1], BREAK_N).min(axis=1)
    broke_up, broke_down = close > top, close < bottom
    was_top = np.concatenate(([np.nan], top[:-1]))
    was_bottom = np.concatenate(([np.nan], bottom[:-1]))
    held_up = np.concatenate(([False], broke_up[:-1])) & (close > was_top)
    held_down = np.concatenate(([False], broke_down[:-1])) & (close < was_bottom)
    return _pair(held_up, held_down, f)


def orb(f):
    """First break of the session's opening 15 minutes, held for one bar.

    One attempt a session, whichever side goes first: an opening range that can
    be traded twice is two different claims.
    """
    start, time, high, low = f["session"], f["time"], f["high"], f["low"]
    if start is None or not np.any(np.isfinite(start)):
        return np.array([], dtype=int), np.array([], dtype=int)
    opening = time < start + OR_SECONDS
    top = np.full(len(time), np.nan)
    bottom = np.full(len(time), np.nan)
    current, run_hi, run_lo = None, np.nan, np.nan
    for i in range(len(time)):
        if start[i] != current:
            current, run_hi, run_lo = start[i], np.nan, np.nan
        if opening[i]:
            run_hi = high[i] if np.isnan(run_hi) else max(run_hi, high[i])
            run_lo = low[i] if np.isnan(run_lo) else min(run_lo, low[i])
        else:
            top[i], bottom[i] = run_hi, run_lo
    close = f["close"]
    broke_up, broke_down = close > top, close < bottom
    held_up = np.concatenate(([False], broke_up[:-1])) & broke_up
    held_down = np.concatenate(([False], broke_down[:-1])) & broke_down
    index, side = _pair(held_up, held_down, f)
    keep, seen = [], set()
    for pos, i in enumerate(index):
        day = float(start[i])
        if day in seen:
            continue
        seen.add(day)
        keep.append(pos)
    return index[keep], side[keep]


SIGNALS = {
    "ema_pullback": ema_pullback,
    "candle_momentum": candle_momentum,
    "bb_reversion": bb_reversion,
    "bb_to_mid": bb_reversion,
    "orb": orb,
    "level_break": level_break,
}


# ----------------------------------------------------------------- the trade


def race(f, entry_i: int, side: int, risk: float, target: float, hold: int = HOLD):
    """Gross R and the exit bar, on the wicks, **stop first**.

    One bar can span both barriers; at a 1:2 geometry they sit within two ATR
    of each other so the tie is common, and assuming the favourable one is how
    a backtest invents an edge.
    """
    high, low, close, opens = f["high"], f["low"], f["close"], f["open"]
    entry = opens[entry_i]
    up = entry + side * target
    down = entry - side * risk
    last = min(entry_i + hold, len(close) - 1)
    for k in range(entry_i, last + 1):
        if side > 0:
            if low[k] <= down:
                return -1.0, k
            if high[k] >= up:
                return target / risk, k
        else:
            if high[k] >= down:
                return -1.0, k
            if low[k] <= up:
                return target / risk, k
    return side * (close[last] - entry) / risk, last


def book(f, index, side, trip: float, to_mid: bool = False) -> list[dict]:
    """One position at a time, in time order, each paying its own stop's cost."""
    out: list[dict] = []
    free = -1
    n = len(f["close"])
    for i, way in zip(np.asarray(index, dtype=int), np.asarray(side, dtype=int)):
        if i <= free:
            continue
        risk = float(f["atr"][i])
        entry_i = int(i) + 1
        if not (risk > 0) or entry_i >= n:
            continue
        if to_mid:
            reach = abs(float(f["mid"][i]) - float(f["open"][entry_i]))
            if not np.isfinite(reach) or reach <= 0:
                continue
            target = reach
        else:
            target = TARGET_R * risk
        gross, exit_i = race(f, entry_i, int(way), risk, target)
        out.append(
            {
                "i": int(i),
                "entry": entry_i,
                "exit": int(exit_i),
                "side": int(way),
                "risk": risk,
                "target_r": target / risk,
                "cost_r": trip / risk,
                "gross": float(gross),
                "net": float(gross) - trip / risk,
                "day": int(f["time"][entry_i] // 86400),
            }
        )
        free = exit_i
    return out


# ------------------------------------------------------------------ the maths


def bootstrap(values: np.ndarray, days: np.ndarray, rng) -> tuple[np.ndarray, int]:
    """Day-block bootstrap of the mean, by whole days.

    A 1-minute book takes dozens of trades out of one day's volatility, so an
    ordinary standard error over trades is far too narrow. Done on per-day sums
    and counts rather than by concatenating arrays, which is the same estimator
    and fast enough to run on every arm of every cell.
    """
    order = np.argsort(days, kind="stable")
    values, days = values[order], days[order]
    edges = np.flatnonzero(np.concatenate(([True], days[1:] != days[:-1])))
    sums = np.add.reduceat(values, edges)
    counts = np.diff(np.concatenate((edges, [len(values)])))
    pick = rng.integers(0, len(sums), (DRAWS, len(sums)))
    return sums[pick].sum(axis=1) / counts[pick].sum(axis=1), len(sums)


def compare(left: list[dict], right: list[dict], rng) -> dict:
    """The difference of two arms' mean net R, bootstrapped on whole days.

    The arms are not paired trade by trade - two books with different entries
    exit at different bars - but they run over the same calendar, so the day is
    the unit that can be resampled for both at once, which removes the common
    day-to-day volatility that dominates either arm's own interval.

    **Over the union of days, not the intersection**, and the first version got
    that wrong in a way that looked like a certainty. At 15 minutes an
    opening-range book takes about one trade a day, and on a day where both the
    filtered and the unfiltered arm traded it is the *same trade* - so an
    intersection comparison read `diff +0.0000 [+0.0000, +0.0000]` while the
    two arms' means differed by 0.005R. A filter whose whole effect is skipping
    days cannot be measured on the days it did not skip.

    Ties count as half, so two identical arms return p = 1 rather than p = 0:
    every draw is then exactly zero, `mean(boots <= 0)` is 1.0, and the
    two-sided form would turn that into the most significant result available.
    """
    if not left or not right:
        return {}
    by_day_left: dict[int, list[float]] = defaultdict(list)
    by_day_right: dict[int, list[float]] = defaultdict(list)
    for t in left:
        by_day_left[t["day"]].append(t["net"])
    for t in right:
        by_day_right[t["day"]].append(t["net"])
    days = sorted(set(by_day_left) | set(by_day_right))
    if len(days) < 20:
        return {}
    lsum = np.array([sum(by_day_left.get(d, ())) for d in days])
    lnum = np.array([len(by_day_left.get(d, ())) for d in days])
    rsum = np.array([sum(by_day_right.get(d, ())) for d in days])
    rnum = np.array([len(by_day_right.get(d, ())) for d in days])
    pick = rng.integers(0, len(days), (DRAWS, len(days)))
    boots = lsum[pick].sum(axis=1) / np.maximum(lnum[pick].sum(axis=1), 1) - rsum[pick].sum(
        axis=1
    ) / np.maximum(rnum[pick].sum(axis=1), 1)
    below = float(np.mean(boots < 0.0) + 0.5 * np.mean(boots == 0.0))
    return {
        "days": len(days),
        "both": len(set(by_day_left) & set(by_day_right)),
        "diff": float(lsum.sum() / max(lnum.sum(), 1) - rsum.sum() / max(rnum.sum(), 1)),
        "lo": float(np.percentile(boots, 5)),
        "hi": float(np.percentile(boots, 95)),
        "p": float(2.0 * min(below, 1.0 - below)),
    }


def summarise(trades: list[dict], rng, key: str = "net") -> dict:
    if not trades:
        return {"n": 0}
    values = np.array([t[key] for t in trades], dtype=float)
    days = np.array([t["day"] for t in trades], dtype=np.int64)
    boots, n_days = bootstrap(values, days, rng)
    below = float(np.mean(boots < 0.0) + 0.5 * np.mean(boots == 0.0))
    cost = float(np.mean([t["cost_r"] for t in trades]))
    return {
        "n": len(values),
        "days": n_days,
        "mean": float(values.mean()),
        "se": float(boots.std(ddof=1)),
        "lo": float(np.percentile(boots, 5)),
        "hi": float(np.percentile(boots, 95)),
        "p": float(2.0 * min(below, 1.0 - below)),
        "hit": float(np.mean(values > 0)),
        "reached": float(np.mean([t["gross"] >= t["target_r"] - 1e-9 for t in trades])),
        "target_r": float(np.mean([t["target_r"] for t in trades])),
        "cost_r": cost,
        "breakeven": (1.0 + cost) / 3.0,
        "clocked": float(np.mean([t["exit"] - t["entry"] >= HOLD for t in trades])),
        "thin": len(values) < THIN,
    }


def benjamini_hochberg(cells: list[dict], alpha: float = 0.05) -> set:
    ordered = sorted(
        (c for c in cells if c.get("p") is not None and np.isfinite(c["p"])),
        key=lambda c: c["p"],
    )
    keep: set = set()
    m = len(ordered)
    for rank, cell in enumerate(ordered, start=1):
        if m and cell["p"] <= alpha * rank / m:
            keep = {c["key"] for c in ordered[:rank]}
    return keep


# ------------------------------------------------------------------- the arms


def arms(f, family: str, index, side, trip: float, rng) -> dict[str, list[dict]]:
    ctx = f["ctx"]
    to_mid = family == "bb_to_mid"
    aligned = ctx[index] == side
    against = ctx[index] == -side
    made = {
        "rule": book(f, index[aligned], side[aligned], trip, to_mid),
        "nofilter": book(f, index, side, trip, to_mid),
        "inverted": book(f, index[against], side[against], trip, to_mid),
    }
    share = float(aligned.mean()) if len(index) else 0.0
    pick = rng.random(len(index)) < share
    made["filter_random"] = book(f, index[pick], side[pick], trip, to_mid)

    taken = np.array([t["i"] for t in made["rule"]], dtype=int)
    sides = np.array([t["side"] for t in made["rule"]], dtype=int)
    if len(taken):
        made["coin"] = book(f, taken, rng.choice([-1, 1], len(taken)), trip, to_mid)
        late = taken + STALE
        fits = late + 2 < len(f["close"])
        made["stale"] = book(f, late[fits], sides[fits], trip, to_mid)
        warm = np.flatnonzero(np.isfinite(f["atr"]) & (f["atr"] > 0))
        warm = warm[warm + 2 < len(f["close"])]
        if len(warm) > len(taken):
            when = np.sort(rng.choice(warm, len(taken), replace=False))
            made["random_time"] = book(f, when, rng.choice(sides, len(when)), trip, to_mid)
    return made


def plant(f, trades: list[dict], strength: float) -> dict:
    """The series with a drift of `strength` R **per bar** added while each
    trade is open, its window clipped to the next entry.

    Per bar, not spread over the hold window, and the first version was the
    other way round: a ramp delivering `strength` R over 40 bars gives a trade
    that resolves in three bars about a fourteenth of it, so every strength
    read as blind and the sweep would have reported the harness's own geometry
    as a power limit. A drift is a rate; the plant has to be one too.

    Separated from `planted` so `test_scalps.py` can assert the property that
    matters - that no bar receives two plants - on the array itself rather than
    inferring it from a mean.
    """
    high, low, close = f["high"].copy(), f["low"].copy(), f["close"].copy()
    ends = [t["entry"] for t in trades[1:]] + [len(close)]
    for t, stop_at in zip(trades, ends):
        first = t["entry"]
        last = min(first + HOLD, stop_at - 1, len(close) - 1)
        if last <= first:
            continue
        span = np.arange(first, last + 1)
        ramp = t["side"] * strength * t["risk"] * (span - first)
        high[span] += ramp
        low[span] += ramp
        close[span] += ramp
    return {**f, "high": high, "low": low, "close": close}


def planted(f, trades: list[dict], strength: float, rng) -> dict:
    """Re-race the same entries on a series with a drift planted in their favour.

    A drift of `strength` R **per bar** while the position is open, each window
    **clipped to the next entry** so two plants cannot overlap. An overlapping
    plant compounds and makes every cell significant including the unplanted
    one - a defect this repository has published once already.
    """
    if not trades or strength <= 0:
        return summarise(trades, rng)
    g = plant(f, trades, strength)
    out = []
    for t in trades:
        gross, exit_i = race(g, t["entry"], t["side"], t["risk"], t["target_r"] * t["risk"])
        out.append({**t, "gross": float(gross), "net": float(gross) - t["cost_r"], "exit": exit_i})
    return summarise(out, rng)


def _loss_limit(order: list[dict]) -> np.ndarray:
    keep, run, day = [], 0.0, None
    for t in order:
        if t["day"] != day:
            day, run = t["day"], 0.0
        allowed = run > DAY_LOSS_LIMIT
        keep.append(allowed)
        if allowed:
            run += t["net"]
    return np.array(keep, dtype=bool)


def _trade_cap(order: list[dict]) -> np.ndarray:
    keep, count, day = [], 0, None
    for t in order:
        if t["day"] != day:
            day, count = t["day"], 0
        keep.append(count < TRADES_PER_DAY)
        count += int(keep[-1])
    return np.array(keep, dtype=bool)


def risk_rules(trades: list[dict], rng) -> dict:
    """A daily loss limit and a trade cap, each against stopping at random.

    Both are duty-cycle rules, so the only question is whether they beat a twin
    that trades **the same amount less**. The twin drops the same count *within
    each day*, so it cannot win by skipping a whole bad day the rule traded
    into - which is the comparison that makes a pause rule look clever.
    """
    if len(trades) < THIN:
        return {}
    order = sorted(trades, key=lambda t: t["entry"])
    net = np.array([t["net"] for t in order])
    days = np.array([t["day"] for t in order])
    n = len(order)
    by_day = np.argsort(days, kind="stable")
    net_d, days_d = net[by_day], days[by_day]
    edges = np.flatnonzero(np.concatenate(([True], days_d[1:] != days_d[:-1])))
    counts = np.diff(np.concatenate((edges, [n])))
    offset = np.repeat(edges, counts)
    out = {"n": n, "base_total": float(net.sum()), "base_mean": float(net.mean())}
    for label, keep in (("loss_limit", _loss_limit(order)), ("trade_cap", _trade_cap(order))):
        if not keep.any():
            continue
        mean = float(net[keep].mean())
        per_day = np.repeat(np.add.reduceat(keep[by_day].astype(int), edges), counts)
        # One `lexsort` a draw instead of a loop over days: it groups by day and
        # orders at random inside each group, so the first `k` of each group is
        # a uniform subset of that day of exactly the size the rule kept.
        beats = 0
        for _ in range(TWIN_DRAWS):
            shuffled = np.lexsort((rng.random(n), days_d))
            rank = np.arange(n) - offset
            mask = shuffled[rank < per_day[shuffled]]
            if len(mask) and float(net_d[mask].mean()) >= mean:
                beats += 1
        out[label] = {
            "kept": int(keep.sum()),
            "share": float(keep.mean()),
            "total": float(net[keep].sum()),
            "mean": mean,
            "twin_beats": beats / TWIN_DRAWS,
        }
    return out


# --------------------------------------------------------------------- report


def features(m1: dict[str, np.ndarray], k: int) -> dict:
    bars = clock_bars(m1, k)
    f = dict(bars)
    f["atr"] = atr(bars["high"], bars["low"], bars["close"])
    f["fast"] = ema(bars["close"], FAST_N)
    f["slow"] = ema(bars["close"], SLOW_N)
    f["mid"], f["lower"], f["upper"] = bands(bars["close"])
    f["rsi"] = rsi(bars["close"])
    f["ctx"] = context(bars, clock_bars(m1, 15))
    f["session"], f["real_session"] = sessions(m1["time"], bars["time"])
    return f


def show(name: str, got: dict) -> None:
    if not got.get("n"):
        print(f"      {name:<14} -")
        return
    thin = " THIN" if got["thin"] else ""
    print(
        f"      {name:<14} n {got['n']:>6,} d {got['days']:>4}  net {got['mean']:+7.4f}"
        f" [{got['lo']:+7.4f},{got['hi']:+7.4f}] p {got['p']:.3f}"
        f"  P(hit) {got['reached']:.3f} vs {got['breakeven']:.3f}"
        f"  cost {got['cost_r']:.3f}  clk {got['clocked']:.2f}{thin}"
    )


def main() -> int:
    rng = np.random.default_rng(SEED)
    sources = m1_sources()
    print(
        f"clocks {CLOCKS}  families {FAMILIES}\n"
        f"stop 1 ATR({ATR_N}), target {TARGET_R:g} ATR, hold {HOLD} bars, one at a time.\n"
        f"a cell is measured only where the round trip is <= {RISK_LIMIT:.2f} of a 1-ATR stop.\n"
        "P(hit) is the share reaching the target; read against 1/3 = 0.333 for a 1:2\n"
        "geometry and against (1+cost)/3, printed after 'vs'. THIN is under "
        f"{THIN} trades.\n"
    )
    cells: list[dict] = []
    dead: list[dict] = []
    pool: dict[tuple, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    for symbol, path in sources.items():
        with np.load(path) as data:
            m1 = {
                k: np.asarray(data[k], dtype=np.float64)
                for k in ("time", "open", "high", "low", "close")
            }
        trip = quoted(symbol)
        if not np.isfinite(trip):
            print(f"##### {symbol}: the bridge gave no quote - not screened, not measured")
            continue
        for k in CLOCKS:
            f = features(m1, k)
            unit = float(np.nanmedian(f["atr"]))
            cost = trip / unit if unit > 0 else float("inf")
            if cost > RISK_LIMIT:
                dead.append(
                    {"symbol": symbol, "clock": k, "atr": unit, "trip": trip, "cost": cost}
                )
                continue
            first = dt.datetime.fromtimestamp(f["time"][0], dt.UTC).date()
            last = dt.datetime.fromtimestamp(f["time"][-1], dt.UTC).date()
            print(
                f"\n##### {symbol} {k}m #####  bars {len(f['close']):,}  {first}..{last}"
                f"  ATR {unit:.5g}  trip {trip:.4g}  cost/R {cost:.3f}"
                f"  sessions {'real' if f['real_session'] else 'ARBITRARY - control'}"
            )
            for family in FAMILIES:
                index, side = SIGNALS[family](f)
                if len(index) < MIN_SIGNALS:
                    print(f"    {family:<16} {len(index)} signals, too few to measure")
                    continue
                made = arms(f, family, index, side, trip, rng)
                print(f"    {family:<16} {len(index):,} signals")
                got = {}
                for arm in ARMS:
                    if arm in made:
                        got[arm] = summarise(made[arm], rng)
                        show(arm, got[arm])
                        pool[(family, k, arm)]["trades"] = pool[(family, k, arm)].get(
                            "trades", []
                        ) + made[arm]
                gross = summarise(made["rule"], rng, key="gross")
                if gross.get("n"):
                    print(
                        f"      {'rule, gross':<14} n {gross['n']:>6,}        "
                        f"gross {gross['mean']:+7.4f}"
                        f" [{gross['lo']:+7.4f},{gross['hi']:+7.4f}] p {gross['p']:.3f}"
                    )
                against = {}
                for other in ("nofilter", "inverted", "filter_random", "coin", "random_time", "stale"):
                    if other in made:
                        got_diff = compare(made["rule"], made[other], rng)
                        if got_diff:
                            against[other] = got_diff
                            print(
                                f"      vs {other:<11} diff {got_diff['diff']:+7.4f}"
                                f" [{got_diff['lo']:+7.4f},{got_diff['hi']:+7.4f}]"
                                f" p {got_diff['p']:.3f}  days {got_diff['days']} ({got_diff['both']} both)"
                            )
                power = {}
                for strength in PLANTS:
                    got_plant = planted(f, made["rule"], strength, rng)
                    power[f"{strength:g}"] = {
                        "mean": got_plant.get("mean"),
                        "lands": bool(got_plant.get("lo", 0.0) > 0.0),
                    }
                print(
                    "      power          "
                    + "  ".join(
                        f"{d}:{v['mean']:+.3f}{'*' if v['lands'] else ''}"
                        for d, v in power.items()
                    )
                    + "   (* 90% day-block interval above zero)"
                )
                rules = risk_rules(made["rule"], rng)
                for label in ("loss_limit", "trade_cap"):
                    r = rules.get(label)
                    if r:
                        print(
                            f"      {label:<14} keeps {r['share']:.2f}  mean {r['mean']:+7.4f}"
                            f" vs base {rules['base_mean']:+7.4f}  total {r['total']:+8.1f}"
                            f" vs {rules['base_total']:+8.1f}"
                            f"  random twin beats it {r['twin_beats']:.3f}"
                        )
                half = len(f["close"]) // 2
                splits = {
                    "first": summarise([t for t in made["rule"] if t["entry"] < half], rng).get(
                        "mean"
                    ),
                    "second": summarise([t for t in made["rule"] if t["entry"] >= half], rng).get(
                        "mean"
                    ),
                }
                print(f"      split          first {splits['first']}  second {splits['second']}")
                cells.append(
                    {
                        "key": (symbol, k, family),
                        "symbol": symbol,
                        "clock": k,
                        "family": family,
                        "real_session": bool(f["real_session"]),
                        "signals": int(len(index)),
                        "arms": got,
                        "gross": gross,
                        "power": power,
                        "risk_rules": rules,
                        "split": splits,
                        "against": against,
                        "p": got.get("rule", {}).get("p"),
                    }
                )

    print("\n### dead cells, refused before measurement ###")
    print(f"  {'symbol':<26}{'clock':>6}{'ATR(14)':>11}{'trip':>10}{'cost/R':>9}")
    for row in sorted(dead, key=lambda r: (r["clock"], r["cost"])):
        print(
            f"  {row['symbol']:<26}{row['clock']:>5}m{row['atr']:>11.5g}"
            f"{row['trip']:>10.5g}{row['cost']:>9.3f}"
        )

    kept = benjamini_hochberg(cells)
    print(
        f"\n### {len(cells)} cells measured; Benjamini-Hochberg at 0.05 keeps "
        f"{len(kept)} as different from zero ###"
    )
    for cell in sorted(cells, key=lambda c: c["arms"].get("rule", {}).get("mean", 0.0)):
        r = cell["arms"].get("rule", {})
        if not r.get("n"):
            continue
        print(
            f"  {cell['symbol']:<26}{cell['clock']:>3}m {cell['family']:<16}"
            f" n {r['n']:>6,} net {r['mean']:+7.4f} p {r['p']:.3f}"
            f" {'KEPT' if cell['key'] in kept else ''}"
        )

    print("\n### pooled per family and clock, blocked on the date across instruments ###")
    pooled: dict[str, dict] = {}
    for family in FAMILIES:
        for k in CLOCKS:
            line = None
            for arm in ARMS:
                trades = pool.get((family, k, arm), {}).get("trades") or []
                if not trades:
                    continue
                got = summarise(trades, rng)
                pooled[f"{family}|{k}|{arm}"] = got
                if line is None:
                    members = len({c["symbol"] for c in cells if c["family"] == family and c["clock"] == k})
                    line = f"  {family:<16}{k:>3}m  instruments {members:>2}"
                line += f"  {arm} {got['mean']:+.4f}"
            if line:
                print(line)
                for arm in ARMS:
                    got = pooled.get(f"{family}|{k}|{arm}")
                    if got:
                        print(
                            f"      {arm:<14} n {got['n']:>6,} d {got['days']:>4}"
                            f"  net {got['mean']:+7.4f}"
                            f" [{got['lo']:+7.4f},{got['hi']:+7.4f}] p {got['p']:.3f}"
                            f"  P(hit) {got['reached']:.3f} vs {got['breakeven']:.3f}"
                        )
                rule_trades = pool.get((family, k, "rule"), {}).get("trades") or []
                if rule_trades:
                    got = summarise(rule_trades, rng, key="gross")
                    pooled[f"{family}|{k}|rule_gross"] = got
                    print(
                        f"      {'rule, gross':<14} n {got['n']:>6,} d {got['days']:>4}"
                        f"  gross {got['mean']:+7.4f}"
                        f" [{got['lo']:+7.4f},{got['hi']:+7.4f}] p {got['p']:.3f}"
                    )
                    for other in ARMS[1:]:
                        trades = pool.get((family, k, other), {}).get("trades") or []
                        got_diff = compare(rule_trades, trades, rng) if trades else {}
                        if got_diff:
                            pooled[f"{family}|{k}|rule-{other}"] = got_diff
                            print(
                                f"      vs {other:<11} diff {got_diff['diff']:+7.4f}"
                                f" [{got_diff['lo']:+7.4f},{got_diff['hi']:+7.4f}]"
                                f" p {got_diff['p']:.3f}  days {got_diff['days']} ({got_diff['both']} both)"
                            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "cells": [{**c, "key": list(c["key"])} for c in cells],
                "dead": dead,
                "kept": [list(x) for x in kept],
                "pooled": pooled,
                "settings": {
                    "clocks": list(CLOCKS),
                    "families": list(FAMILIES),
                    "hold": HOLD,
                    "target_r": TARGET_R,
                    "risk_limit": RISK_LIMIT,
                    "stale": STALE,
                    "draws": DRAWS,
                    "seed": SEED,
                    "day_loss_limit": DAY_LOSS_LIMIT,
                    "trades_per_day": TRADES_PER_DAY,
                },
            },
            indent=1,
            default=str,
        )
    )
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
