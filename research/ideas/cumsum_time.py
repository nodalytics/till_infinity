"""Cumulative sums over minutes and hours rather than over bars.

Asked for on 2026-10-11. A cumsum over twenty bars is five hours at 15m and
twenty hours at 1h, so "20-bar momentum" is a different statistic on every feed
it is computed on - the package rule in `statespace/__init__.py`, applied to the
most common feature on any desk.

Two things are measured, and the first is the one that settles it.

## 1. Does the statistic survive changing the feed?

This is a **portability test, and it needs no outcome at all**. Take one
instrument on two feeds - 3m and 15m, or 15m and 1h - and compute the same
cumsum from each at the same timestamps. If the window is a duration, both feeds
are summing the same stretch of the same market and should agree. If the window
is a bar count, they are summing different stretches and should not.

That makes the claim falsifiable without a return, a horizon or a cost model:
either the two feeds agree about what the feature is, or the feature is a
property of the sampling rather than of the market. Every signal built on an
`N`-bar window inherits whatever this says.

## 2. Does it predict anything?

Direction, and the size of the next move, against the nulls this desk insists
on: a matched control that rotates the feature, and - for magnitude - a trailing
standard deviation, which has beaten every volatility model tried here.

## The normalisation, which is the whole trick

A sum over a longer window is bigger for no interesting reason, and a sum from a
denser feed has more terms. Both are fixed by dividing by `unit * sqrt(hours)`
where `unit` is the series' own volatility **per root hour** rather than per bar.
Under a random walk that makes the statistic a `z` whose scale is one at every
window and on every feed, so the numbers are comparable down the column and
across the table. A feature that is not comparable across feeds cannot be
compared across them, which is the trap this is built to avoid.

Windows run from six minutes to a day, which is what "from seconds to days"
means once a feed's own resolution is taken into account: the ladder is filtered
per series by what it can actually resolve, two bars minimum.

Runs on the lab.
"""

from __future__ import annotations

import bisect
import itertools
import math
import os
import statistics
from pathlib import Path

from till_infinity.statespace.inputs import bar_hours, coverage, ema, rolling

HOUR = 3600.0

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
)

#: Feeds, finest first. The pairs compared are consecutive entries.
FRAMES = ("3m", "15m", "1h")

#: Cumsum windows in **hours**: six minutes to a day.
WINDOWS = (0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 24.0)

#: Cumsum windows in **bars**, the way it is usually written. These are what the
#: portability test is against: the same `N` on two feeds is two durations.
BARS = (4, 8, 20, 50)

HORIZONS = (1.0, 4.0, 24.0)

#: At least this many bars in a window before it is resolvable on a feed.
LEAST = 2

SHIFTS = (0.25, 0.5, 0.75)

LIMIT = int(os.environ.get("LIMIT", "40000"))


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: bundle[k][order].tolist() for k in ("time", "close")}
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def logs(prices: list[float]) -> list[float]:
    """Cumulative log return in basis points. Additive and scale-free."""
    out, running = [0.0], 0.0
    for i in range(1, len(prices)):
        if prices[i] > 0 and prices[i - 1] > 0:
            running += math.log(prices[i] / prices[i - 1]) * 10_000
        out.append(running)
    return out


def per_root_hour(series: list[float], bar: float) -> float:
    """The feed's own volatility per root hour, from its bar moves.

    **Per root hour, not per bar.** A 3m bar moves less than a 15m bar, and
    under a random walk by exactly `sqrt(1/5)`, so dividing by a per-bar unit
    leaves the feed's resolution in the number and nothing is comparable.
    """
    alpha = 1.0 - 0.5 ** (1.0 / 60.0)
    average = 0.0
    for i in range(1, len(series)):
        move = abs(series[i] - series[i - 1])
        average = move if i == 1 else average + alpha * (move - average)
    return max(average, 1e-9) / math.sqrt(max(bar, 1e-9))


def over_time(times: list[float], values: list[float], hours: float, unit: float) -> list[float]:
    """`z` of the sum over the last `hours` of **clock time**, at every bar.

    The start of the window is found by timestamp, so a gap in the feed shortens
    the sum rather than silently reaching further back than asked.
    """
    out = [0.0] * len(values)
    span = hours * HOUR
    for i, when in enumerate(times):
        j = bisect.bisect_left(times, when - span)
        if j >= i:
            continue
        got = values[i] - values[j]
        elapsed = max((when - times[j]) / HOUR, 1e-9)
        out[i] = got / (unit * math.sqrt(elapsed))
    return out


def over_bars(values: list[float], count: int, unit: float, bar: float) -> list[float]:
    """`z` of the sum over the last `count` **bars**. The usual way, for contrast."""
    out = [0.0] * len(values)
    for i in range(count, len(values)):
        out[i] = (values[i] - values[i - count]) / (unit * math.sqrt(count * bar))
    return out


def slope_over(times: list[float], values: list[float], span: int, unit: float) -> list[float]:
    """Least-squares slope against the clock, as the move it implies, in `z`.

    The regression is on **real timestamps in hours**, not on bar index, so a
    gap in the feed widens the `x` spacing rather than being treated as though
    the market traded through it. Prefix sums make it `O(1)` a bar.

    A slope is in units per hour and a cumsum is in units, so they are not
    comparable until the slope is multiplied by its window: `slope * W` is the
    move it implies over the window, and dividing by `unit * sqrt(W)` puts it on
    the same `z` scale as everything else here.
    """
    n = len(values)
    hours = [t / HOUR for t in times]
    st = [0.0] * (n + 1)
    stt = [0.0] * (n + 1)
    sv = [0.0] * (n + 1)
    stv = [0.0] * (n + 1)
    for i in range(n):
        st[i + 1] = st[i] + hours[i]
        stt[i + 1] = stt[i] + hours[i] * hours[i]
        sv[i + 1] = sv[i] + values[i]
        stv[i + 1] = stv[i] + hours[i] * values[i]
    out = [0.0] * n
    for i in range(span, n):
        j = i - span + 1
        count = i - j + 1
        sum_t = st[i + 1] - st[j]
        sum_tt = stt[i + 1] - stt[j]
        sum_v = sv[i + 1] - sv[j]
        sum_tv = stv[i + 1] - stv[j]
        denom = count * sum_tt - sum_t * sum_t
        if denom <= 0:
            continue
        rate = (count * sum_tv - sum_t * sum_v) / denom
        window = max(hours[i] - hours[j], 1e-9)
        out[i] = rate * window / (unit * math.sqrt(window))
    return out


def rsi_over(values: list[float], span: int) -> list[float]:
    """RSI over a window, centred on zero so its sign means what the others' do.

    **RSI's window is the most common bar count on any desk** - "RSI 14" - and
    that is the whole reason it is here: fourteen bars is 42 minutes at 3m and
    fourteen hours at 1h, so the same indicator on two feeds of one instrument
    is two different statistics. Stated as a duration it is one.

    Returned as `RSI/50 - 1`, so it runs -1 to +1 with zero at the neutral 50
    and can be scored for direction beside the cumsum and the slope.
    """
    n = len(values)
    steps = [0.0] + [values[i] - values[i - 1] for i in range(1, n)]
    ups = [max(x, 0.0) for x in steps]
    downs = [max(-x, 0.0) for x in steps]
    gain = rolling(ups, span)
    loss = rolling(downs, span)
    out = [0.0] * n
    for i in range(span, n):
        total = gain[i] + loss[i]
        if total <= 0:
            continue
        # RSI = 100 * gain / (gain + loss), then centred and scaled to [-1, 1].
        out[i] = 2.0 * (gain[i] / total) - 1.0
    return out


def wilder(values: list[float], span: int) -> list[float]:
    """RSI with exponential smoothing instead of a flat window.

    Wilder's original, which is an EMA. Here the decay comes from a **half-life
    in hours** converted to a span, so the smoothing is the same per hour on
    every feed rather than the same per bar.
    """
    n = len(values)
    steps = [0.0] + [values[i] - values[i - 1] for i in range(1, n)]
    gain = ema([max(x, 0.0) for x in steps], span)
    loss = ema([max(-x, 0.0) for x in steps], span)
    out = [0.0] * n
    for i in range(n):
        total = gain[i] + loss[i]
        if total > 0:
            out[i] = 2.0 * (gain[i] / total) - 1.0
    return out


def ema_span(hours: float, bar: float) -> int:
    """A span whose EMA has a half-life of `hours`, on a feed of this bar size.

    `ema()` uses `alpha = 2 / (span + 1)`; a half-life of `hours` wants
    `alpha = 1 - 0.5 ** (bar / hours)`. Inverting gives the span to ask for, so
    the decay is a duration and not a bar count.
    """
    alpha = 1.0 - 0.5 ** (max(bar, 1e-9) / max(hours, 1e-9))
    return max(round(2.0 / max(alpha, 1e-9) - 1.0), 1)


def families(
    times: list[float],
    values: list[float],
    hours: float,
    unit: float,
    bar: float,
    cover: float = 1.0,
) -> dict[str, list[float]]:
    """Every feature at one window, all defined by the **duration** `hours`.

    **`coverage` belongs in this conversion and leaving it out broke the
    stride.** A window of `hours` *calendar* hours holds `hours * coverage / bar`
    bars, because a market that trades half the time puts half as many bars in a
    given stretch of clock. The first version divided by `bar` alone, so the
    spans here were `1 / coverage` times longer than the cumsum's own
    timestamp-located window - about twice, on FX - while the evaluation stride
    used the coverage-corrected number. The windows therefore overlapped almost
    completely, and overlapping windows are how this project has produced a
    `t` of -10.8 before. One conversion, used everywhere.
    """
    span = max(round(hours * max(cover, 1e-9) / max(bar, 1e-9)), 2)
    decay = ema_span(hours, bar)
    cumsum = over_time(times, values, hours, unit)
    slope = slope_over(times, values, span, unit)
    return {
        "cumsum": cumsum,
        "cumsum sma": rolling(cumsum, span),
        "cumsum ema": ema(cumsum, decay),
        "slope": slope,
        "slope sma": rolling(slope, span),
        "slope ema": ema(slope, decay),
        "rsi": rsi_over(values, span),
        "rsi ema": wilder(values, decay),
    }


def bar_families(
    times: list[float], values: list[float], count: int, unit: float, bar: float
) -> dict[str, list[float]]:
    """The same features written as **bar counts**. What is usually done."""
    cumsum = over_bars(values, count, unit, bar)
    slope = slope_over(times, values, count, unit)
    return {
        "cumsum": cumsum,
        "cumsum sma": rolling(cumsum, count),
        "cumsum ema": ema(cumsum, count),
        "slope": slope,
        "slope sma": rolling(slope, count),
        "slope ema": ema(slope, count),
        "rsi": rsi_over(values, count),
        "rsi ema": wilder(values, count),
    }


def ranked(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    for rank, i in enumerate(order):
        out[i] = float(rank)
    return out


def spearman(xs: list[float], ys: list[float], shift: int = 0) -> float:
    n = len(xs)
    if n < 30:
        return float("nan")
    rotated = [xs[(i + shift) % n] for i in range(n)]
    rx, ry = ranked(rotated), ranked(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den > 0 else float("nan")


def null_rho(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    got = [spearman(xs, ys, shift=max(int(n * f), 1)) for f in SHIFTS]
    usable = [v for v in got if not math.isnan(v)]
    return statistics.fmean(usable) if usable else float("nan")


def partial(feature: list[float], target: list[float], given: list[float]) -> float:
    """Spearman of `feature` on `target` with `given` removed. Ranks throughout."""
    if len(feature) < 30:
        return float("nan")
    rf, rt, rg = ranked(feature), ranked(target), ranked(given)
    mg, mf = statistics.fmean(rg), statistics.fmean(rf)
    sgg = sum((g - mg) ** 2 for g in rg)
    if sgg <= 0:
        return float("nan")
    beta = sum((f - mf) * (g - mg) for f, g in zip(rf, rg, strict=True)) / sgg
    resid = [f - beta * (g - mg) for f, g in zip(rf, rg, strict=True)]
    mr, mt = statistics.fmean(resid), statistics.fmean(rt)
    num = sum((r - mr) * (t - mt) for r, t in zip(resid, rt, strict=True))
    den = math.sqrt(sum((r - mr) ** 2 for r in resid) * sum((t - mt) ** 2 for t in rt))
    return num / den if den > 0 else float("nan")


def trailing(values: list[float], window: int) -> list[float]:
    """Standard deviation of the last `window` increments. The magnitude null."""
    out = [0.0] * len(values)
    steps = [0.0] + [values[i] - values[i - 1] for i in range(1, len(values))]
    run = runsq = 0.0
    for i in range(1, len(values)):
        run += steps[i]
        runsq += steps[i] * steps[i]
        if i > window:
            run -= steps[i - window]
            runsq -= steps[i - window] * steps[i - window]
        count = min(i, window)
        if count >= 2:
            mean = run / count
            out[i] = math.sqrt(max(runsq / count - mean * mean, 0.0))
    return out


def crossing(a: dict, b: dict) -> list[int]:
    """For each bar of the coarser feed `a`, the latest bar of `b` at or before it.

    `-1` where the finer feed has no bar yet. Matching on **timestamps** is the
    whole point: it is the only way to ask two feeds about the same instant, and
    attaching one feed's value to another's bar by position is the
    cross-resolution lookahead this project has already paid for once.
    """
    out = []
    for when in a["time"]:
        j = bisect.bisect_right(b["time"], when) - 1
        out.append(j)
    return out


def portability(label: str, stem: str) -> None:
    """Does each statistic survive changing the feed? No outcome needed."""
    feeds = {}
    for frame in FRAMES:
        got = load(stem, frame)
        if got is None or len(got["close"]) < 2000:
            continue
        bar = bar_hours(got["time"])
        if bar <= 0:
            continue
        got["bar"] = bar
        got["values"] = logs(got["close"])
        got["unit"] = per_root_hour(got["values"], bar)
        got["cover"] = coverage(got["time"], bar)
        feeds[frame] = got
    names = [f for f in FRAMES if f in feeds]

    def agree(xa: list[float], xb: list[float], at: list[int]) -> float:
        left, right = [], []
        for i, j in enumerate(at):
            if j >= 0 and xa[i] != 0.0 and xb[j] != 0.0:
                left.append(xa[i])
                right.append(xb[j])
        return spearman(left, right)

    for fine, coarse in itertools.pairwise(names):
        a, b = feeds[coarse], feeds[fine]
        at = crossing(a, b)
        paired = sum(1 for j in at if j >= 0)
        print(f"  {label}: {coarse} against {fine}  ({paired} paired)")
        usable = [h for h in WINDOWS if h >= LEAST * max(a["bar"], b["bar"])]
        header = "".join(f"{f'{h:g}h':>8}" for h in usable)
        print(f"    {'by DURATION':<14}{header}")
        rows: dict[str, list[float]] = {}
        for hours in usable:
            fa = families(a["time"], a["values"], hours, a["unit"], a["bar"], a["cover"])
            fb = families(b["time"], b["values"], hours, b["unit"], b["bar"], b["cover"])
            for name in fa:
                rows.setdefault(name, []).append(agree(fa[name], fb[name], at))
        for name, got in rows.items():
            print(f"    {name:<14}" + "".join(f"{v:>8.3f}" for v in got))
        header = "".join(f"{f'{c}b':>8}" for c in BARS)
        print(f"    {'by BAR COUNT':<14}{header}")
        rows = {}
        for count in BARS:
            fa = bar_families(a["time"], a["values"], count, a["unit"], a["bar"])
            fb = bar_families(b["time"], b["values"], count, b["unit"], b["bar"])
            for name in fa:
                rows.setdefault(name, []).append(agree(fa[name], fb[name], at))
        for name, got in rows.items():
            print(f"    {name:<14}" + "".join(f"{v:>8.3f}" for v in got))
        print()


def predictive(label: str, stem: str, frame: str) -> None:
    """Direction and magnitude for every family, against the two nulls."""
    got = load(stem, frame)
    if got is None or len(got["close"]) < 2000:
        return
    times = got["time"]
    bar = bar_hours(times)
    cover = coverage(times, bar)
    if bar <= 0:
        return
    values = logs(got["close"])
    unit = per_root_hour(values, bar)
    print(f"  === {label} {frame}: {len(values)} bars, bar={bar:g}h ===")
    print(
        f"    {'feature':<12}{'window':>7}{'hzn':>5}{'hit':>8}{'ctrl':>8}"
        f"{'z':>7}{'|f|->|move|':>12}{'net sd':>9}{'n':>7}"
    )
    for hours in WINDOWS:
        if hours < LEAST * bar:
            continue
        span = max(round(hours * cover / bar), 2)
        built = families(times, values, hours, unit, bar, cover)
        sd = trailing(values, span)
        for name, feature in built.items():
            for horizon in HORIZONS:
                ahead = max(round(horizon * cover / bar), 1)
                # Step by the longer of the feature's own window and the
                # horizon, so no two rows share a window or an outcome.
                stride = max(span, ahead)
                rows = []
                for i in range(stride, len(values) - ahead, stride):
                    if feature[i] == 0.0:
                        continue
                    move = values[i + ahead] - values[i]
                    rows.append((feature[i], move, abs(move), sd[i]))
                if len(rows) < 200:
                    continue
                f = [r[0] for r in rows]
                signed = [r[1] for r in rows]
                size = [r[2] for r in rows]
                vol = [r[3] for r in rows]
                total = len(rows)
                wins = sum(1 for a, b in zip(f, signed, strict=True) if (a > 0) == (b > 0))
                rate = wins / total
                nulls = []
                for frac in SHIFTS:
                    shift = max(int(total * frac), 1)
                    nulls.append(
                        sum(
                            1
                            for k in range(total)
                            if (f[(k + shift) % total] > 0) == (signed[k] > 0)
                        )
                        / total
                    )
                z = (rate - 0.5) * math.sqrt(total) / 0.5
                mag = spearman([abs(v) for v in f], size)
                net = partial([abs(v) for v in f], size, vol)
                print(
                    f"    {name:<12}{hours:>6g}h{horizon:>4g}h{rate:>8.2%}"
                    f"{statistics.fmean(nulls):>8.2%}{z:>+7.2f}"
                    f"{mag:>+12.3f}{net:>+9.3f}{total:>7}"
                )
    print()


def main() -> None:
    print("Cumulative sums over minutes and hours, not over bars.")
    print(f"windows {'/'.join(f'{w:g}h' for w in WINDOWS)}; bar windows {BARS}.")
    print("Families: cumsum, slope, rsi - each raw, sma and ema. Every span,")
    print("every window and every EMA half-life is a DURATION; the bar-count")
    print("table is the same code with the duration replaced by a bar count.")
    print("Each is divided by the feed's volatility per ROOT HOUR, so the")
    print("statistic is a z comparable across windows and across feeds.\n")

    print("## 1. Portability: the same statistic from two feeds, at the same")
    print("stamps. A duration should survive the change of feed; a bar count")
    print("should not. No outcome is involved - this is the feature against")
    print("itself.\n")
    for label, stem in SYMBOLS:
        portability(label, stem)

    print("## 2. Does it predict? Direction against a rotated control, and")
    print("|z| against a trailing standard deviation over the same window.\n")
    for label, stem in SYMBOLS:
        for frame in ("15m", "1h"):
            predictive(label, stem, frame)


if __name__ == "__main__":
    main()
