"""Stale forecasts at lags of 1 to 12 hours: does their agreement signal anything?

Asked on 2026-10-11. A member fitted up to time `t - L` has an opinion about
where the value is *now*. Run that at several lags at once and you have a panel
of opinions about the same instant, formed at different distances from it, and
three readings fall out of it that no single forecast has:

* **agreement** - do the stale forecasts agree on which side of the current
  price the value sits? A twelve-hour-old opinion and a one-hour-old one
  pointing the same way is a different state of the world from them splitting.
* **overlap** - do their uncertainty bands intersect? Two forecasts can agree on
  a sign while being incompatible about the magnitude, and the band is the only
  thing that distinguishes "the same claim seen twice" from "two claims".
* **disagreement** - how far apart they are, in volatility units. This is the
  panel's own spread, and unlike a single member's `sd` it is not a model
  output: it cannot be flattered by a member that reports a confident band.

**Lags are hours, not bars.** `L` is converted per series from its own median
spacing and trading coverage, so "the opinion from four hours ago" means the
same thing at 15m and at 1h - the package rule in `statespace/__init__.py`, and
the mistake this harness would otherwise repeat for the fourth time.

## The lookahead this could have, and does not

The obvious way to build the panel is to walk back `k` bars from `i` and read
the member - and there is no way to do that in one pass, so the temptation is to
re-read the member's *current* state and call it the lagged one. That is the
cross-resolution bug from `statespace_symbols_timeframes.py`, where a 15m
innovation got attached to 3m bars of the same stamp and produced `t = +20.8`
on five symbols.

So the panel is written **forward**. At bar `j` the member projects to
`time[j] + L` and the result is stored against the bar that lands on, which is
`j + k`. Every entry read at bar `i` was therefore computed strictly before `i`,
by construction rather than by an off-by-one that has to be argued about. The
reference price is `values[i]`, known when the panel is read, and the target
starts there.

## The nulls

Direction is the one every candidate here has died on, so it is scored against
a **matched control**: the same feature series circularly shifted, which keeps
its distribution and autocorrelation and destroys only its alignment with the
outcome. A hit rate that the control matches is the feature's marginal, not a
signal. The magnitude arm is scored the same way.

Overlapping windows inflate `t` - `slope_fade.py` produced `-10.8` entirely out
of overlap - so evaluation steps by `max(longest lag, horizon)`.

Runs on the lab. Production has two cores and research on it has OOM-killed the
live desk three times.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.structures.statespace import members
from till_infinity.structures.statespace.inputs import bar_hours, coverage

HOUR = 3600.0

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
)
FRAMES = ("15m", "1h")

#: The panel, in **hours** of staleness. One to twelve, as asked.
LAGS = (1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0)

#: Forecast horizons, in hours.
HORIZONS = (1.0, 4.0, 24.0)

#: Members. `kalman` is the baseline, `reverting` is the only one that has
#: beaten the random walk here, and `swarm` is the only one whose far-out band
#: is honest - which matters, because `overlap` is a statement about bands.
MODELS = ("kalman", "reverting", "swarm")

#: Measurement variance in the normalised units, by the `Filter` contract.
NOISE = float(os.environ.get("NOISE", "0.16"))

LIMIT = int(os.environ.get("LIMIT", "12000"))

#: Fractions of the series to rotate the feature by for the matched control.
#: **A fixed count is wrong**, and the first run of this harness proved it: a
#: shift of 1013 on 999 independent points is a shift of 14, which destroys no
#: alignment, so every control landed on top of the statistic it was supposed to
#: null and the table read as "no signal" for a reason that had nothing to do
#: with the data. Fractions of `n` cannot have that failure, and three of them
#: averaged gives a null that does not depend on one arbitrary offset.
SHIFTS = (0.25, 0.5, 0.75)


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


def normalise(prices: list[float]) -> list[float]:
    """Cumulative **log** return in basis points over this series' own bar move.

    **Arithmetic return from a fixed base is wrong here and the first run showed
    it.** `(c / p0 - 1)` has increments proportional to the current price, so on
    a series that has trended a long way the later bars move more in these units
    than the early ones *for the same proportional move*. Both "how far apart are
    the stale forecasts" and "how big is the next move" then scale with the price
    level, and the correlation between them is the trend rather than anything
    predictive. It showed as the effect being strongest on exactly the two
    series that trend hardest - v75 1h at rho +0.288 and xauusd 1h at +0.363.

    Log returns are additive and scale-free, so a 1% move is the same number of
    units wherever the price is.
    """
    alpha = 1.0 - 0.5 ** (1.0 / 60.0)
    average = 0.0
    steps = [0.0]
    for i in range(1, len(prices)):
        if prices[i] <= 0 or prices[i - 1] <= 0:
            steps.append(0.0)
            continue
        step = math.log(prices[i] / prices[i - 1]) * 10_000
        steps.append(step)
        average = abs(step) if i == 1 else average + alpha * (abs(step) - average)
    unit = max(average, 0.25)
    out, running = [], 0.0
    for step in steps:
        running += step / unit
        out.append(running)
    return out


def panel(build, times: list[float], values: list[float], steps: dict[float, int]):
    """One pass, writing each projection forward to the bar it lands on.

    Returns `{lag: [(value, spread) or None per bar]}`. An entry at index `i`
    was computed at `i - steps[lag]`, so reading it at `i` cannot see `i`.
    """
    engine = build()
    out = {lag: [None] * len(values) for lag in steps}
    for j, (when, value) in enumerate(zip(times, values, strict=True)):
        engine.predict(when)
        engine.update(value, NOISE, when)
        for lag, step in steps.items():
            i = j + step
            if i >= len(values):
                continue
            ahead = when + lag * HOUR
            low, high = engine.band(ahead, 1.0)
            spread = max((high - low) / 2.0, 1e-9)
            # The band is the **state**; a reading also carries `R`, and
            # comparing two state bands would call two members compatible
            # whenever both were confident about different things.
            out[lag][i] = (
                float(engine.at_time(ahead)),
                math.sqrt(spread * spread + NOISE),
            )
    return out


def readings(column: list[tuple[float, float] | None], now: float):
    """`(signed agreement, overlap share, disagreement)` from one panel column.

    * signed agreement is the mean sign of "the value is above the price", so
      `+1` is unanimous above and `0` is a clean split.
    * overlap is the share of lag **pairs** whose one-sigma bands intersect.
      Pairs rather than a global intersection, because one outlying forecast
      would otherwise take the whole reading to zero.
    * disagreement is the spread of the panel's point forecasts, in volatility
      units.
    """
    got = [p for p in column if p is not None]
    if len(got) < 3:
        return None
    gaps = [value - now for value, _s in got]
    signed = statistics.fmean([1.0 if g > 0 else -1.0 if g < 0 else 0.0 for g in gaps])
    pairs = touching = 0
    for a in range(len(got)):
        for b in range(a + 1, len(got)):
            (va, sa), (vb, sb) = got[a], got[b]
            pairs += 1
            if abs(va - vb) <= sa + sb:
                touching += 1
    overlap = touching / pairs if pairs else float("nan")
    return signed, overlap, statistics.pstdev(gaps) if len(gaps) > 1 else 0.0


def trailing(values: list[float], window: int) -> list[float]:
    """Standard deviation of the last `window` increments, at every bar.

    **The null `disagreement` has to beat.** A panel of stale forecasts spreads
    out when the member's state has been moving, so its spread is largely
    `|recent slope| x the spread of the lags` - which makes it a volatility
    proxy, and "a volatility proxy forecasts volatility" is the one thing this
    desk already knows. The question is whether the panel adds anything to the
    plainest estimator of the same thing.
    """
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


def ranked(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    for rank, i in enumerate(order):
        out[i] = float(rank)
    return out


def partial(feature: list[float], target: list[float], given: list[float]) -> float:
    """Spearman of `feature` against `target`, with `given` taken out of both.

    Rank-transform all three, regress the feature's ranks on the control's,
    correlate the residual with the target's ranks. What is left is whatever the
    feature knows that the trailing estimator does not.
    """
    if len(feature) < 30:
        return float("nan")
    rf, rt, rg = ranked(feature), ranked(target), ranked(given)
    mg = statistics.fmean(rg)
    sgg = sum((g - mg) ** 2 for g in rg)
    if sgg <= 0:
        return float("nan")
    mf = statistics.fmean(rf)
    beta = sum((f - mf) * (g - mg) for f, g in zip(rf, rg, strict=True)) / sgg
    resid = [f - beta * (g - mg) for f, g in zip(rf, rg, strict=True)]
    mr, mt = statistics.fmean(resid), statistics.fmean(rt)
    num = sum((r - mr) * (t - mt) for r, t in zip(resid, rt, strict=True))
    den = math.sqrt(sum((r - mr) ** 2 for r in resid) * sum((t - mt) ** 2 for t in rt))
    return num / den if den > 0 else float("nan")


def hit(feature: list[float], target: list[float], shift: int = 0) -> tuple[float, int]:
    """Signed hit rate where the feature takes a side, and the count.

    `shift` rotates the feature for the matched control: same distribution, same
    autocorrelation, no alignment.
    """
    n = len(feature)
    wins = seen = 0
    for i in range(n):
        f = feature[(i + shift) % n]
        if f == 0.0 or target[i] == 0.0:
            continue
        seen += 1
        if (f > 0) == (target[i] > 0):
            wins += 1
    return (wins / seen if seen else float("nan")), seen


def spearman(xs: list[float], ys: list[float], shift: int = 0) -> float:
    n = len(xs)
    if n < 30:
        return float("nan")
    rotated = [xs[(i + shift) % n] for i in range(n)]

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        for rank, i in enumerate(order):
            out[i] = float(rank)
        return out

    rx, ry = ranks(rotated), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den > 0 else float("nan")


def null_hit(feature: list[float], target: list[float]) -> float:
    """Mean hit rate over several rotations. The matched control for direction."""
    n = len(feature)
    got = [hit(feature, target, shift=max(int(n * f), 1))[0] for f in SHIFTS]
    usable = [v for v in got if not math.isnan(v)]
    return statistics.fmean(usable) if usable else float("nan")


def null_rho(xs: list[float], ys: list[float]) -> float:
    """Mean rank correlation over several rotations. The control for magnitude."""
    n = len(xs)
    got = [spearman(xs, ys, shift=max(int(n * f), 1)) for f in SHIFTS]
    usable = [v for v in got if not math.isnan(v)]
    return statistics.fmean(usable) if usable else float("nan")


def score(rows: list[tuple[float, ...]]) -> list[str]:
    """One line per feature: direction against its control, magnitude likewise."""
    if len(rows) < 200:
        return [f"  too few independent points ({len(rows)})"]
    signed = [r[0] for r in rows]
    overlap = [r[1] for r in rows]
    disagree = [r[2] for r in rows]
    direction = [r[3] for r in rows]
    size = [r[4] for r in rows]
    vol = [r[5] for r in rows]
    lines = []

    rate, seen = hit(signed, direction)
    control = null_hit(signed, direction)
    z = (rate - 0.5) * math.sqrt(seen) / 0.5 if seen else float("nan")
    lines.append(
        f"  agreement -> direction   {rate:>7.2%} vs control {control:>7.2%}"
        f"   z{z:>+6.2f}  n={seen}"
    )
    lines.append(
        f"  trailing sd  -> |move|  rho{spearman(vol, size):>+6.3f}"
        f"   <- the null the panel has to beat"
    )
    for name, feature in (("overlap", overlap), ("disagreement", disagree)):
        rho = spearman(feature, size)
        null = null_rho(feature, size)
        net = partial(feature, size, vol)
        lines.append(
            f"  {name:<12} -> |move|  rho{rho:>+6.3f} vs control rho{null:>+6.3f}"
            f"  net of sd{net:>+6.3f}  n={len(rows)}"
        )
    # Agreement as a magnitude signal too: unanimity may mark a quiet market
    # rather than a direction, and that is the reading this panel is most
    # likely to actually have.
    rho = spearman([abs(s) for s in signed], size)
    null = null_rho([abs(s) for s in signed], size)
    lines.append(f"  |agreement|  -> |move|  rho{rho:>+6.3f} vs control rho{null:>+6.3f}")
    return lines


def main() -> None:
    print("Stale forecasts at 1-12 hours: agreement, band overlap, disagreement.")
    print(
        f"lags {'/'.join(f'{x:g}h' for x in LAGS)}, horizons "
        f"{'/'.join(f'{h:g}h' for h in HORIZONS)}, noise={NOISE:g} (variance)."
    )
    print("Every panel entry was computed before the bar it is read at.")
    print("'control' is the same feature rotated by a quarter, a half and three")
    print("quarters of the sample and averaged: same distribution, same")
    print("autocorrelation, no alignment. A reading its control matches is a")
    print("marginal, not a signal.\n")

    family = members()
    for label, stem in SYMBOLS:
        for frame in FRAMES:
            bars = load(stem, frame)
            if bars is None or len(bars["close"]) < 2000:
                continue
            times = bars["time"]
            bar = bar_hours(times)
            cover = coverage(times, bar)
            if bar <= 0:
                continue
            values = normalise(bars["close"])
            steps = {lag: max(round(lag * cover / bar), 1) for lag in LAGS}
            # The null, over the panel's own longest reach so it sees the same
            # stretch of history the panel does.
            sd = trailing(values, max(steps.values()))
            # Lags that collapse onto the same bar are one lag, not several.
            seen: dict[int, float] = {}
            for lag, step in steps.items():
                seen.setdefault(step, lag)
            steps = {lag: step for step, lag in seen.items()}
            print(
                f"=== {label} {frame}: {len(values)} bars, bar={bar:g}h, "
                f"lags->bars {sorted(steps.values())} ==="
            )
            for name in MODELS:
                build = family[name]
                column = panel(build, times, values, steps)
                for hours in HORIZONS:
                    ahead = max(round(hours * cover / bar), 1)
                    # Independence: step by the longer of the panel's reach and
                    # the horizon, so no two rows share an outcome window.
                    reach = max(steps.values())
                    stride = max(reach, ahead)
                    rows = []
                    for i in range(reach, len(values) - ahead, stride):
                        got = readings([column[lag][i] for lag in steps], values[i])
                        if got is None:
                            continue
                        move = values[i + ahead] - values[i]
                        rows.append((got[0], got[1], got[2], move, abs(move), sd[i]))
                    print(f"  -- {name} at {hours:g}h, {len(rows)} independent points")
                    for line in score(rows):
                        print(line)
            print()


if __name__ == "__main__":
    main()
