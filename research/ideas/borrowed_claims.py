"""Two borrowed claims, checked on this desk's own data.

From a set of in-house research papers reviewed on 2026-10-11. Most of what
they contain needs data this desk does not have. **Two claims are cheap and
decisive here**, and one of them contradicts this repository's own record,
which makes it the more interesting of the pair.

## Claim one: Ising susceptibility is a leading indicator

A study over 38.8 million bars and 97 instruments reports susceptibility - the
variance of a magnetisation order parameter built from **signed volume flow** -
firing at 7-8% of bars with a mean edge of +0.30 to +0.42% at twenty-four
bars, and calls it the highest-capacity microstructure signal in its dataset.

**This desk measured an Ising susceptibility and it lost.** `README.md` lists
it beside a three-state HMM and a fifty-neighbour analogue as things a
trailing standard deviation beat.

The conflict is worth resolving rather than picking a side, and there is an
obvious candidate for the difference: their order parameter is built from
**signed volume**, and every FX feed here reports a tick count rather than
traded size. BTCUSD is the one instrument with real volume. So the test is
susceptibility with a *properly signed* magnetisation, on the instrument where
that is possible, scored this desk's way - against a rotated control and net
of a trailing standard deviation.

## Claim two: a Thursday effect

The same dataset reports systematic negative Thursday returns - Bitcoin at a
Sharpe of -2.43, US Tech 100 at -2.07 - with Monday strength in equities and
Wednesday strength in crypto.

Day-of-week effects are the most heavily mined anomaly in finance, and 97
instruments times seven days times five timeframes is a very large surface, so
the prior is that this is selection. But it is **cheap to check** and the
check is unambiguous: this desk has the same instruments and a different
sample period.

Scored with the test this desk uses for a directional claim - the mean return
on each weekday against **the pooled standard error**, plus the share of
weeks on which the sign held, which is what separates "a few large Thursdays"
from "most Thursdays".

Runs on the lab.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import statistics
from pathlib import Path

from till_infinity.statespace.nulls import control, spearman, trailing

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("btcusd", "BTCUSD"),
    ("v75", "Volatility_75_Index"),
)
FRAME = os.environ.get("FRAME", "1h")
SINCE = float(os.environ.get("SINCE", "1262304000"))
LIMIT = int(os.environ.get("LIMIT", "20000"))

#: Window for the magnetisation variance, in bars.
SUSCEPT = 24

#: Horizon for the susceptibility claim, in bars - theirs is 24.
HORIZON = 24

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        keys = set(bundle.keys())
        if not {"time", "close"} <= keys:
            return None
        order = np.argsort(bundle["time"])
        times = bundle["time"][order].tolist()
        closes = bundle["close"][order].tolist()
        volumes = bundle["volume"][order].tolist() if "volume" in keys else [0.0] * len(order)
    first = 0
    while first < len(times) and times[first] < SINCE:
        first += 1
    times, closes, volumes = times[first:], closes[first:], volumes[first:]
    if len(closes) > LIMIT:
        times, closes, volumes = times[-LIMIT:], closes[-LIMIT:], volumes[-LIMIT:]
    return times, closes, volumes


def moves(closes: list[float]) -> list[float]:
    return [0.0] + [
        math.log(closes[i] / closes[i - 1]) if closes[i] > 0 and closes[i - 1] > 0 else 0.0
        for i in range(1, len(closes))
    ]


def susceptibility(
    steps: list[float], volumes: list[float], span: int, signed: bool
) -> list[float]:
    """Variance of the magnetisation over `span` bars.

    The magnetisation is the per-bar order parameter. `signed = True` weights
    each bar's direction by its **traded size**, which is the paper's
    construction and needs real volume; `signed = False` uses the bare sign,
    which is what a feed without volume can offer and is the version this desk
    measured before.
    """
    n = len(steps)
    magnet = [0.0] * n
    for k in range(n):
        direction = 1.0 if steps[k] > 0 else -1.0 if steps[k] < 0 else 0.0
        magnet[k] = direction * (volumes[k] if signed else 1.0)
    # Normalise by the rolling mean size so the variance is comparable.
    scale = trailing(magnet, span)
    out = [0.0] * n
    run: list[float] = []
    for k in range(n):
        run.append(magnet[k])
        if len(run) > span:
            run.pop(0)
        if len(run) >= 4:
            spread = scale[k] if scale[k] > 0 else 1.0
            out[k] = statistics.pvariance(run) / (spread * spread)
    return out


def check_susceptibility(label: str, _times, closes, volumes) -> None:
    steps = moves(closes)
    real = sum(1 for v in volumes if v > 0) > 0.9 * len(volumes)
    levels = [0.0]
    for s in steps[1:]:
        levels.append(levels[-1] + s)
    sd = trailing(levels, SUSCEPT)
    rows = list(range(SUSCEPT + 10, len(levels) - HORIZON, HORIZON))
    if len(rows) < 200:
        return
    size = [abs(levels[i + HORIZON] - levels[i]) for i in rows]
    signed_move = [levels[i + HORIZON] - levels[i] for i in rows]
    vol = [sd[i] for i in rows]

    for name, use_volume in (("sign only", False), ("signed volume", True)):
        if use_volume and not real:
            continue
        series = susceptibility(steps, volumes, SUSCEPT, use_volume)
        feature = [series[i] for i in rows]
        if max(feature) - min(feature) <= 0:
            continue
        print(
            f"  {label:<9}{name:<15}{spearman(feature, size):>+9.3f}"
            f"{control(feature, size):>+9.3f}"
            f"{spearman(vol, size):>+10.3f}"
            f"{spearman(feature, signed_move):>+11.3f}"
        )


def check_weekday(label: str, times, closes) -> None:
    steps = moves(closes)
    buckets: dict[int, list[float]] = {d: [] for d in range(7)}
    for i in range(1, len(steps)):
        day = dt.datetime.fromtimestamp(times[i], dt.UTC).weekday()
        buckets[day].append(steps[i])
    cells = []
    for day in range(7):
        got = buckets[day]
        if len(got) < 200:
            cells.append("      -")
            continue
        mean = statistics.fmean(got)
        spread = statistics.pstdev(got) / math.sqrt(len(got))
        cells.append(f"{mean / spread:>+7.2f}" if spread > 0 else "      -")
    print(f"  {label:<10}" + "".join(cells))


def main() -> None:
    print("Two borrowed claims, on this desk's own data.\n")
    print("## 1. Ising susceptibility, with and without real volume\n")
    print("A study over 38.8M bars calls it the highest-capacity microstructure")
    print("signal it has. This repository measured one and a trailing standard")
    print("deviation beat it. The candidate difference is signed VOLUME, which")
    print("only BTC has here.\n")
    print(
        f"  {'series':<9}{'order parameter':<15}{'rho |move|':>9}{'ctrl':>9}"
        f"{'sd null':>10}{'rho signed':>11}"
    )
    loaded = {}
    for label, stem in SYMBOLS:
        got = load(stem, FRAME)
        if got is None or len(got[1]) < 3000:
            continue
        loaded[label] = got
        check_susceptibility(label, *got)

    print("\n## 2. The weekday effect, as a t-statistic per day\n")
    print("Mean bar return on each weekday over its own standard error.")
    print("|t| above 2 is the usual bar; the claim is Thursday strongly")
    print("negative and Monday or Wednesday positive.\n")
    print(f"  {'series':<10}" + "".join(f"{d:>7}" for d in DAYS))
    for label, (times, closes, _v) in loaded.items():
        check_weekday(label, times, closes)

    print("\n  Seven days times six series is 42 cells, so two or three at")
    print("  |t| > 2 is what chance gives. The claim needs a pattern - the")
    print("  same day, the same sign, across instruments - not a count.")


if __name__ == "__main__":
    main()
