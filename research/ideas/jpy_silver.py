"""USDJPY against XAGUSD: is there a pair there, and how long does it take?

Asked on 2026-10-11: can the two be paired, does one rise when the other
falls, how long does it take, and is any of it seasonal.

## The confound that has to be cleared first

**Both are quoted in dollars.** USDJPY rises when the dollar strengthens
against the yen; XAGUSD falls when the dollar strengthens against silver. So
a dollar move alone pushes them in opposite directions, and *any* two
dollar-quoted instruments will show a relationship that is nothing but the
shared leg.

A naive correlation here will come back negative and look like a finding. The
question is whether anything survives removing the common dollar, so every
arm below is run twice: raw, and on the residual after a dollar factor built
from the other majors is taken out. `panel.py` exists for exactly this
decomposition - a factor plus reverting idiosyncratics - and the share of
variance it puts in the factor is the answer to "is this just the dollar".

## What "can they be paired" actually asks

Not whether they correlate. A tradeable pair needs a **stationary spread**:
the hedged combination has to come back when it wanders, or the position is
just two directional bets with extra cost. So the test is `relating` for the
hedge ratio - which carries it as a state rather than fitting it once - and
then a reverting model against a random walk **on the spread**. If the walk
wins, there is no pair, whatever the correlation says.

A half-life only means something if the reverting model won first. Reporting
a half-life from a fit to a random walk is how every spurious pair gets its
headline number: an unconstrained fit always returns some half-life.

## How long does it take

Cross-correlation across lags **in hours**, not bars, so the answer is the
same at 1h and 4h. Two readings: where the correlation peaks, and whether the
peak beats a rotated control - because a smooth cross-correlation function
has a maximum somewhere by construction, and the location of a maximum in
noise is not a lead.

Beside it the **Levy area**, `(1/2) * integral(x dy - y dx)`, which is the
signed area a two-asset path encloses. Its sign says which leg leads, an
asymmetry a correlation cannot express, and it needs no library.

## Controls

* **rotated** - the same series, alignment destroyed, everywhere;
* **a pair of generated markets** - two Deriv volatility indices are
  independent processes, so a machinery that reports a relationship there is
  reporting its own bias;
* **cost** - 1.5 spreads round trip, because a conditional mean smaller than
  the cost is not a trade whatever its t-statistic;
* **cell counting** - the seasonal arm sweeps 24 hours and 5 weekdays, so 29
  cells, and one in twenty clears 2 sigma by chance.

Runs on the lab.
"""

from __future__ import annotations

import itertools
import math
import os
import statistics
from pathlib import Path

HOUR = 3600.0

LEFT = os.environ.get("LEFT", "USDJPY")
RIGHT = os.environ.get("RIGHT", "XAGUSD")

#: The other majors, to build a dollar factor. Expressed so that a rise means
#: a **stronger dollar** in every one, which is what makes the average a
#: dollar reading rather than a mixture of two conventions.
DOLLAR = (("EURUSD", -1), ("GBPUSD", -1), ("AUDUSD", -1), ("USDCHF", 1), ("USDCAD", 1))

#: Two independent generated processes, as a false-positive check.
PLACEBO = ("Volatility_75_Index", "Volatility_100_Index")

FRAMES = tuple(os.environ.get("FRAMES", "1h,4h,1d").split(","))

#: Lead-lag reach and the forward horizons, both in hours.
LAGS_HOURS = (-48, -24, -12, -6, -3, -1, 0, 1, 3, 6, 12, 24, 48)
HORIZONS = (1, 3, 6, 12, 24, 48, 120)

#: How big a move counts as a fall, in trailing standard deviations.
THRESHOLD = 1.5

#: Round-trip cost, in spreads. The desk's own gate.
COST_SPREADS = 1.5

SINCE = float(os.environ.get("SINCE", "1262304000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str):
    import numpy as np

    for path in (CACHE / f"{name}.{frame}.npz", Path(f"data/seqlab/{name}.{frame}.npz")):
        if not path.exists():
            continue
        with np.load(path) as bundle:
            keys = set(bundle.keys())
            if not {"time", "close"} <= keys:
                continue
            order = np.argsort(bundle["time"])
            out = {
                "time": bundle["time"][order].tolist(),
                "close": bundle["close"][order].tolist(),
            }
            if "spread" in keys:
                out["spread"] = bundle["spread"][order].tolist()
        first = 0
        while first < len(out["time"]) and out["time"][first] < SINCE:
            first += 1
        return {k: v[first:] for k, v in out.items()}
    return None


def align(left: dict, right: dict) -> tuple[list[float], list[float], list[float]]:
    """Inner join on the stamp.

    **Not a forward fill.** Filling one series' gaps with its last value and
    then correlating would manufacture agreement out of the stale readings:
    the filled leg stops moving while the other continues, which reads as a
    relationship and is an artefact of the fill. An inner join loses bars and
    keeps the question honest.
    """
    index = dict(zip(right["time"], right["close"], strict=True))
    times: list[float] = []
    ours: list[float] = []
    theirs: list[float] = []
    for when, close in zip(left["time"], left["close"], strict=True):
        other = index.get(when)
        if other is None or close <= 0 or other <= 0:
            continue
        times.append(float(when))
        ours.append(float(close))
        theirs.append(float(other))
    return times, ours, theirs


def returns(values: list[float]) -> list[float]:
    return [
        math.log(values[i] / values[i - 1]) if values[i] > 0 and values[i - 1] > 0 else 0.0
        for i in range(1, len(values))
    ]


def correlate(xs: list[float], ys: list[float]) -> float:
    """Pearson on returns. Pearson rather than Spearman here because the
    hedge ratio and the Levy area are both linear quantities, and mixing a
    rank statistic with them would make the three numbers incomparable."""
    n = min(len(xs), len(ys))
    if n < 30:
        return float("nan")
    xs, ys = xs[:n], ys[:n]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return num / den if den > 0 else float("nan")


def rotated(xs: list[float], ys: list[float]) -> float:
    """The matched control: three rotations, averaged."""
    n = min(len(xs), len(ys))
    if n < 30:
        return float("nan")
    got = []
    for fraction in (0.25, 0.5, 0.75):
        shift = max(int(n * fraction), 1)
        spun = [xs[(i + shift) % n] for i in range(n)]
        value = correlate(spun, ys[:n])
        if not math.isnan(value):
            got.append(value)
    return statistics.fmean(got) if got else float("nan")


def _area(xs: list[float], ys: list[float]) -> float:
    """`(1/2) * sum(x dy - y dx)` over the cumulative paths, unnormalised."""
    path_x = list(itertools.accumulate(xs))
    path_y = list(itertools.accumulate(ys))
    area = 0.0
    for i in range(1, len(path_x)):
        area += path_x[i - 1] * (path_y[i] - path_y[i - 1])
        area -= path_y[i - 1] * (path_x[i] - path_x[i - 1])
    return 0.5 * area


def levy(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """The signed area the two-asset path encloses, **and its own null**.

    A positive area is supposed to mean `x` moves first and `y` follows. The
    trouble is that the Levy area of two *independent* paths is not near zero:
    it is the classical Levy stochastic area, mean zero but with a spread
    growing like the sample length, so one reading of it says nothing at all.

    A first version of this harness divided by `sd(x) * sd(y) * n` and
    reported the result. The placebo caught it: two independent Deriv
    volatility indices returned 0.26 to 0.64 where the pair under test
    returned 0.21 to 0.73 - indistinguishable, because the normalisation
    bounds the magnitude without concentrating it.

    So the reading is a **z-score against rotations of one leg**, which keeps
    both series' distributions and autocorrelations and destroys only the
    alignment. Returned with the spread, so a caller can see how wide the null
    is rather than trusting the ratio.
    """
    n = min(len(xs), len(ys))
    if n < 200:
        return float("nan"), float("nan")
    xs, ys = xs[:n], ys[:n]
    here = _area(xs, ys)
    spun = []
    for k in range(1, 16):
        shift = (k * n) // 16
        spun.append(_area([xs[(i + shift) % n] for i in range(n)], ys))
    middle = statistics.fmean(spun)
    spread = statistics.pstdev(spun)
    if spread <= 0:
        return float("nan"), float("nan")
    return (here - middle) / spread, spread


def dollar_factor(frame: str, times: list[float]) -> list[float] | None:
    """A dollar return per stamp, averaged over the other majors.

    Each leg is signed so a rise means a stronger dollar, so the average is a
    dollar reading rather than two conventions cancelling. `USDJPY` and
    `XAGUSD` are both excluded, because a factor that contains the legs being
    tested would remove the thing under test along with the dollar.
    """
    pools: list[dict[float, float]] = []
    for name, sign in DOLLAR:
        found = load(name, frame)
        if found is None:
            continue
        steps = returns(found["close"])
        pools.append(dict(zip(found["time"][1:], [sign * s for s in steps], strict=True)))
    if len(pools) < 3:
        return None
    out: list[float] = []
    for when in times[1:]:
        got = [pool[when] for pool in pools if when in pool]
        out.append(statistics.fmean(got) if len(got) >= 3 else 0.0)
    return out


def residual(xs: list[float], factor: list[float]) -> list[float]:
    """What is left of `xs` once its best multiple of the factor is removed.

    One regression over the whole sample, which is in-sample by construction -
    acceptable here because the factor is being *removed* rather than used to
    forecast, and removing slightly too much makes the surviving relationship
    smaller rather than larger. The conservative direction.
    """
    n = min(len(xs), len(factor))
    if n < 30:
        return list(xs)
    num = sum(a * b for a, b in zip(xs[:n], factor[:n], strict=True))
    den = sum(b * b for b in factor[:n])
    beta = num / den if den > 0 else 0.0
    return [a - beta * b for a, b in zip(xs[:n], factor[:n], strict=True)]


def half_life(spread: list[float], hours: float) -> tuple[float, float]:
    """An AR(1) on the spread, as a half-life in hours, with its own slope.

    Returned together because **the half-life is only meaningful if the slope
    is negative**: an unconstrained fit to a random walk returns a slope near
    zero and so a half-life near infinity, and reporting the half-life alone
    hides that.
    """
    if len(spread) < 60:
        return float("nan"), float("nan")
    xs = spread[:-1]
    ys = [spread[i] - spread[i - 1] for i in range(1, len(spread))]
    mx = statistics.fmean(xs)
    num = sum((a - mx) * b for a, b in zip(xs, ys, strict=True))
    den = sum((a - mx) ** 2 for a in xs)
    slope = num / den if den > 0 else 0.0
    if slope >= 0 or slope <= -1:
        return float("nan"), slope
    return math.log(2.0) / -math.log1p(slope) * hours, slope


def _slope_t(spread: list[float]) -> tuple[float, float]:
    """The AR(1) slope on the spread and its t, the Dickey-Fuller statistic.

    Regress `d(spread)` on `spread` lagged. A slope of zero is a unit root -
    the spread never comes back - and a negative slope is reversion. The `t`
    is the thing with a known null, and the null is **not** the normal one,
    which is why `_critical` simulates it.
    """
    if len(spread) < 120:
        return float("nan"), float("nan")
    xs = spread[:-1]
    ys = [b - a for a, b in itertools.pairwise(spread)]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((a - mx) ** 2 for a in xs)
    if den <= 0:
        return float("nan"), float("nan")
    slope = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True)) / den
    intercept = my - slope * mx
    resid = [b - intercept - slope * a for a, b in zip(xs, ys, strict=True)]
    sigma2 = sum(r * r for r in resid) / max(len(resid) - 2, 1)
    error = math.sqrt(sigma2 / den) if sigma2 > 0 else 0.0
    return slope, (slope / error if error > 0 else float("nan"))


def _critical(length: int, seed: int, draws: int = 200) -> tuple[float, float]:
    """The 5th percentile of the same `t` on random walks of the same length.

    **The null for a stationarity test is not a normal distribution.** Under a
    unit root the slope's `t` is skewed strongly negative - the Dickey-Fuller
    distribution - with a 5% critical value near -2.9 rather than -1.65, so
    judging it against a normal would call a third of random walks
    cointegrated. Simulating it costs a second and removes the need to trust a
    table.

    The median is returned beside the critical value so the shape of the null
    is visible rather than assumed.
    """
    import random

    rng = random.Random(seed)
    got = []
    for _ in range(draws):
        walk = list(itertools.accumulate(rng.gauss(0.0, 1.0) for _ in range(length)))
        _, t = _slope_t(walk)
        if not math.isnan(t):
            got.append(t)
    if len(got) < 50:
        return float("nan"), float("nan")
    got.sort()
    return got[max(int(0.05 * len(got)) - 1, 0)], statistics.median(got)


def pairable(times: list[float], left: list[float], right: list[float], hours: float):
    """Can they be paired: a stationary spread, tested without the leak.

    **The first version of this leaked and the placebo caught it.** It built
    the spread as `y - r(t)*x` with `r` a live state from `Relating`, then
    scored a reverting model against a walk on that. `Relating` adapts `r` to
    keep the current residual small, so the residual is mean-reverting by
    construction of the filter and not by any property of the pair - and the
    arm duly reported a reverting model beating a walk by +99,342 on two
    *independent* generated indices, which cannot be cointegrated.

    Two leak-free forms instead:

    * **lagged** - the hedge ratio as of the previous reading, so it cannot
      absorb the point it is being tested on;
    * **split** - one ratio fitted by least squares on the first half of the
      sample and held fixed through the second, which is the version a trade
      would actually use, because a tradeable hedge ratio has to be known
      before the position is opened.

    The placebo has to come back near zero in both for either to mean
    anything.
    """
    from till_infinity.statespace.relating import Relating

    logs_left = [math.log(v) for v in left]
    logs_right = [math.log(v) for v in right]
    unit = statistics.pstdev(returns(left)) or 1e-6

    hedge = Relating(legs=1, centre=True)
    ratios: list[float] = []
    for when, y, x in zip(times, logs_left, logs_right, strict=True):
        ratios.append(hedge.ratio)
        hedge.predict(when)
        hedge.update(y, unit, when, against=x)

    lagged = [y - r * x for y, x, r in zip(logs_left, logs_right, ratios, strict=True)]

    half = len(times) // 2
    mx = statistics.fmean(logs_right[:half])
    my = statistics.fmean(logs_left[:half])
    num = sum((x - mx) * (y - my) for x, y in zip(logs_right[:half], logs_left[:half], strict=True))
    den = sum((x - mx) ** 2 for x in logs_right[:half])
    fixed = num / den if den > 0 else 0.0
    split = [y - fixed * x for y, x in zip(logs_left[half:], logs_right[half:], strict=True)]

    lagged_slope, lagged_t = _slope_t(lagged)
    split_slope, split_t = _slope_t(split)
    edge, middle = _critical(min(len(lagged), 4000), 20261011)
    return {
        "ratio": statistics.median(ratios[len(ratios) // 4 :]),
        "ratio_sd": statistics.pstdev(ratios[len(ratios) // 4 :]),
        "fixed": fixed,
        "lagged_t": lagged_t,
        "lagged_life": half_life_from(lagged_slope, hours),
        "split_t": split_t,
        "split_life": half_life_from(split_slope, hours),
        "critical": edge,
        "null_median": middle,
    }


def half_life_from(slope: float, hours: float) -> float:
    """A half-life in hours, only where the slope is a reverting one.

    Returns `nan` rather than a number when the slope is not negative,
    because an unconstrained fit to a random walk still produces a
    half-life and reporting it is how a spurious pair gets its headline.
    """
    if math.isnan(slope) or slope >= 0 or slope <= -1:
        return float("nan")
    return math.log(2.0) / -math.log1p(slope) * hours


def lead_lag(times: list[float], xs: list[float], ys: list[float], bar_hours: float):
    """Cross-correlation across lags in hours, with the rotated control at each.

    A positive lag means `xs` leads: `xs` at `t` against `ys` at `t + lag`.
    The control matters more here than anywhere else, because a smooth
    cross-correlation function has a maximum *somewhere* by construction and
    the location of a maximum in noise is not a lead.
    """
    out = []
    for hours in LAGS_HOURS:
        step = round(hours / bar_hours)
        if abs(step) >= len(xs) // 4:
            continue
        if step >= 0:
            a, b = xs[: len(xs) - step], ys[step:]
        else:
            a, b = xs[-step:], ys[: len(ys) + step]
        out.append((hours, correlate(a, b), rotated(a, b)))
    _ = times
    return out


def conditional(
    times: list[float],
    xs: list[float],
    moves: list[float],
    bar_hours: float,
    costs: list[float] | None,
):
    """If one falls hard, what does the other do, and for how long?

    `moves` is the trigger leg's returns and `xs` the other leg's **prices**.
    The trigger is a move past `THRESHOLD` trailing standard deviations, which
    is a magnitude in the series' own units rather than a fixed number of pips
    - the only version that means the same thing on silver and on a currency.

    Both directions are reported. "If silver falls the other rises" is only a
    finding if the mirror case also holds; a one-sided result on a
    dollar-quoted pair is usually the dollar.
    """
    span = max(round(24 / bar_hours), 5)
    rolling: list[float] = [0.0] * len(moves)
    for i in range(span, len(moves)):
        window = moves[i - span : i]
        rolling[i] = statistics.pstdev(window) or 1e-9

    cost = 0.0
    if costs:
        usable = [c for c in costs if c > 0]
        if usable:
            cost = COST_SPREADS * statistics.median(usable)

    rows = []
    for horizon in HORIZONS:
        ahead = round(horizon / bar_hours)
        if ahead < 1 or ahead >= len(xs) // 10:
            continue
        for sign, label in ((-1, "fell"), (1, "rose")):
            got: list[float] = []
            for i in range(span, len(moves) - ahead):
                if rolling[i] <= 0:
                    continue
                if sign * moves[i] < THRESHOLD * rolling[i]:
                    continue
                here, later = xs[i + 1], xs[i + 1 + ahead]
                if here > 0 and later > 0:
                    got.append(math.log(later / here))
            if len(got) < 30:
                continue
            middle = statistics.fmean(got)
            spread = statistics.pstdev(got) or 1e-12
            # **Overlapping windows, so the t is inflated.** The stride that
            # would fix it is the horizon itself, and dividing by the root of
            # the overlap is the standard correction - applied here rather
            # than reporting a t that is too large by a factor of five.
            overlap = math.sqrt(max(ahead, 1))
            t = middle / (spread / math.sqrt(len(got))) / overlap
            rows.append((label, horizon, len(got), middle, t, cost))
    _ = times
    return rows


def seasonal(
    times: list[float],
    xs: list[float],
    ys: list[float],
    clean: tuple[list[float], list[float]] | None = None,
):
    """The relation by hour of day and weekday, raw **and net of the dollar**.

    The net column is the whole point. If the hourly pattern is the shared
    dollar leg becoming more or less dominant with the session, then removing
    the dollar should flatten it; if something survives the removal with the
    same shape, the pattern is the pair's own.

    29 cells, so one or two clearing two sigma is the expectation rather than
    a finding. The prior is unkind: `statespace-borrowed-claims.md` already
    measured a Thursday effect on this desk's data and it was null.
    """
    import datetime as dt

    tables: dict[str, dict[int, list[list[float]]]] = {"hour": {}, "weekday": {}}
    net_left, net_right = clean if clean else ([], [])
    has_net = len(net_left) >= len(xs)
    for i, (when, a, b) in enumerate(zip(times[1:], xs, ys, strict=False)):
        stamp = dt.datetime.fromtimestamp(when, tz=dt.UTC)
        for name, key in (("hour", stamp.hour), ("weekday", stamp.weekday())):
            cell = tables[name].setdefault(key, [[], [], [], []])
            cell[0].append(a)
            cell[1].append(b)
            if has_net:
                cell[2].append(net_left[i])
                cell[3].append(net_right[i])

    rows = []
    for name in ("hour", "weekday"):
        for key in sorted(tables[name]):
            left, right, nl, nr = tables[name][key]
            if len(left) < 100:
                continue
            rows.append(
                (
                    name,
                    key,
                    len(left),
                    correlate(left, right),
                    rotated(left, right),
                    correlate(nl, nr) if len(nl) >= 30 else float("nan"),
                )
            )
    return rows


def bar_hours(times: list[float]) -> float:
    gaps = [times[i] - times[i - 1] for i in range(1, min(len(times), 500))]
    return (statistics.median(gaps) / HOUR) if gaps else 1.0


def run(left_name: str, right_name: str, frame: str) -> dict | None:
    left = load(left_name, frame)
    right = load(right_name, frame)
    if left is None or right is None:
        return None
    times, ours, theirs = align(left, right)
    if len(times) < 500:
        return None
    hours = bar_hours(times)
    ours_steps = returns(ours)
    theirs_steps = returns(theirs)

    factor = dollar_factor(frame, times)
    cleaned = (
        (residual(ours_steps, factor), residual(theirs_steps, factor)) if factor else (None, None)
    )

    costs = None
    if left.get("spread"):
        index = dict(zip(left["time"], left["spread"], strict=False))
        costs = [index[t] / c for t, c in zip(times, ours, strict=True) if t in index and c > 0]

    return {
        "cell": f"{left_name} vs {right_name} {frame}",
        "n": len(times),
        "hours": hours,
        "raw": correlate(ours_steps, theirs_steps),
        "raw_control": rotated(ours_steps, theirs_steps),
        "net": correlate(*cleaned) if cleaned[0] else float("nan"),
        "net_control": rotated(*cleaned) if cleaned[0] else float("nan"),
        "levy": levy(ours_steps, theirs_steps)[0],
        "pair": pairable(times, ours, theirs, hours),
        "lags": lead_lag(times, ours_steps, theirs_steps, hours),
        "fell": conditional(times, ours, theirs_steps, hours, costs),
        "season": seasonal(times, ours_steps, theirs_steps, cleaned) if frame == "1h" else [],
    }


def main() -> None:
    print(f"{LEFT} against {RIGHT}, frames {FRAMES}\n")

    found = []
    for frame in FRAMES:
        got = run(LEFT, RIGHT, frame)
        if got:
            found.append(got)
    placebo = [run(PLACEBO[0], PLACEBO[1], f) for f in FRAMES]
    placebo = [p for p in placebo if p]

    print("== the relationship, raw and net of a dollar factor")
    print(f"{'cell':<44}{'n':>7}{'raw':>8}{'ctrl':>7}{'net':>8}{'ctrl':>7}{'levy':>8}")
    for row in found + placebo:
        print(
            f"{row['cell']:<44}{row['n']:>7}{row['raw']:>8.3f}{row['raw_control']:>7.3f}"
            f"{row['net']:>8.3f}{row['net_control']:>7.3f}{row['levy']:>8.3f}"
        )

    print("\n== can they be paired: is the hedged spread stationary?")
    print("   Dickey-Fuller t on the spread. lagged = hedge ratio as of the previous")
    print("   reading; split = one ratio fitted on the first half, held through the")
    print("   second - the only form a trade could use. The critical value is")
    print("   simulated from random walks of the same length, not read off a table.")
    print(
        f"{'cell':<44}{'hedge':>8}{'sd':>7}{'lagged t':>10}{'life h':>8}"
        f"{'split t':>9}{'life h':>8}{'5% crit':>9}"
    )
    for row in found + placebo:
        p = row["pair"]
        one = "-" if math.isnan(p["lagged_life"]) else f"{p['lagged_life']:.0f}"
        two = "-" if math.isnan(p["split_life"]) else f"{p['split_life']:.0f}"
        print(
            f"{row['cell']:<44}{p['ratio']:>8.3f}{p['ratio_sd']:>7.3f}"
            f"{p['lagged_t']:>10.2f}{one:>8}{p['split_t']:>9.2f}{two:>8}"
            f"{p['critical']:>9.2f}"
        )

    print("\n== how long does it take: cross-correlation by lag in hours")
    for row in found:
        print(f"\n{row['cell']}  (positive lag = {LEFT} leads)")
        print(f"{'lag h':>7}{'corr':>8}{'rotated':>9}")
        for hours, value, control in row["lags"]:
            mark = "  <-- peak" if abs(value) == max(abs(v) for _, v, _ in row["lags"]) else ""
            print(f"{hours:>7}{value:>8.3f}{control:>9.3f}{mark}")

    print(f"\n== if {RIGHT} moves {THRESHOLD} sigma, what does {LEFT} do next")
    for row in found:
        if not row["fell"]:
            continue
        print(f"\n{row['cell']}")
        print(f"{'trigger':<9}{'horizon h':>10}{'n':>7}{'mean':>10}{'t':>7}{'cost':>10}{'':>8}")
        for label, horizon, count, middle, t, cost in row["fell"]:
            verdict = "under cost" if abs(middle) < cost else ""
            print(
                f"{label:<9}{horizon:>10}{count:>7}{middle:>10.5f}{t:>7.2f}"
                f"{cost:>10.5f}{verdict:>12}"
            )

    _seasons(found)


def _seasons(found) -> None:
    print("\n== seasonality: the relation by hour and weekday, 29 cells")
    for row in found:
        if not row["season"]:
            continue
        print(f"\n{row['cell']}")
        print(f"{'kind':<9}{'key':>5}{'n':>8}{'corr':>8}{'rotated':>9}{'net':>8}")
        strong = 0
        spread_raw, spread_net = [], []
        for name, key, count, value, control, net in row["season"]:
            shown = "-" if math.isnan(net) else f"{net:8.3f}"
            print(f"{name:<9}{key:>5}{count:>8}{value:>8.3f}{control:>9.3f}{shown:>8}")
            if abs(value) > abs(row["raw"]) + 0.1:
                strong += 1
            if name == "hour":
                spread_raw.append(value)
                if not math.isnan(net):
                    spread_net.append(net)
        if spread_raw:
            print(
                f"hour range raw {min(spread_raw):.3f} to {max(spread_raw):.3f} "
                f"(span {max(spread_raw) - min(spread_raw):.3f})"
            )
        if spread_net:
            print(
                f"hour range net {min(spread_net):.3f} to {max(spread_net):.3f} "
                f"(span {max(spread_net) - min(spread_net):.3f})"
            )
        print(f"cells more than 0.1 above the pooled correlation: {strong} of {len(row['season'])}")


if __name__ == "__main__":
    main()
