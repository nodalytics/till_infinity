"""Does the neural member beat the LTI ones on eurusd, 3m to 1d?

Asked on 2026-10-10: test the state space members across eurusd timeframes, and
`selective` in particular. The prediction on record is that **it loses**, and
this is the harness that either confirms it or embarrasses it.

## Why the prediction is a loss

Gu and Dao's own limitation section (arXiv:2312.00752): the selection mechanism
helps on discrete modalities "but this conversely can impede their performance on
data that LTI SSMs excel on", replacing S4 with S6 "significantly hampers
performance" on long-form audio, and layers nearest a raw continuous signal
"should be LTI". A price series is a continuous-time quantity sampled on a clock,
with no vocabulary and nothing to retrieve by content, so it is the first kind of
data and not the second.

## The comparison this makes, and why it is clean

Four models, and **three of the four are nested**, so a difference is about one
mechanism rather than about four unrelated programmes:

| model | what it adds |
| --- | --- |
| `linear` | three states, integrated jerk - a local Taylor expansion |
| `reverting` | two states, integrated OU - the rate pulls back |
| `selective` at `scale = 0` | **S4D-Real**: four LTI states, spectrum `-(n+1)` |
| `selective` with `scale` free | **S6**: the same, with `delta` reading the input |

The last two differ in exactly one parameter. `scale = 0` makes `delta`
proportional to elapsed time and the recurrence time-invariant, so the fourth row
is the third row plus selection and nothing else. If selection helps here, that
pair shows it; if it hurts, the same pair shows that, and neither answer depends
on `linear` or `reverting` being tuned well.

`selective` at `scale = 0` is worth a name: it is S4D-Real with a fixed read-out,
which is the member the paper's advice actually points at for continuous data,
and this package did not have it until the neural member arrived carrying it as
its own null.

## Method

Fitted on the first half of each series, scored on the **second half**, by
accumulated one-step predictive log-likelihood per point - the same score I5 was
settled on, so these numbers sit beside that one.

Measurements are normalised per timeframe: close-to-close moves in basis points
against an exponential average of their own absolute size, so a 3m bar and a 1d
bar arrive on the same scale and one `noise` grid covers both. Without that the
comparison across timeframes is a comparison of units.

**What this cannot settle.** Bars are not touches. A close moves because price
moved; a level is not supposed to. So this sets the direction and none of the
constants, exactly as the other harnesses here say of themselves. The version on
touches needs the episode record's `entry`, which exists - 250,412 of them - and
is a different harness.

Runs on the lab. Production has two cores and a 2.6GB container limit, and
research on it OOM-killed the live desk three times - see `research/starving.md`.
"""

from __future__ import annotations

import csv
import gzip
import math
import os
import statistics
from pathlib import Path

from till_infinity.structures.statespace.linear import Gaussian
from till_infinity.structures.statespace.reverting import Reverting
from till_infinity.structures.statespace.selective import Selective

#: Where the lab keeps eurusd, by timeframe. Everything from 3m to 1d that
#: exists as a close series; there is no 5m file, and 3m and 15m bracket it.
#: Missing paths are skipped with a line saying so rather than silently.
SERIES: dict[str, str] = {
    # **There is no eurusd 5m on the lab.** `data/fine` carries 5m only for the
    # boom/crash indices; eurusd stops at 15m there. The 3m below is the
    # `seqlab` npz, which brackets 5m from underneath, so "5m to 1d" is covered
    # by 3m/15m rather than exactly.
    "3m": os.environ.get("EURUSD_3M", "data/seqlab/EURUSD.3m.npz"),
    "15m": os.environ.get("EURUSD_15M", "data/fine/eurusd_15m_broker.csv.gz"),
    "30m": os.environ.get("EURUSD_30M", "data/fine/eurusd_30m_broker.csv.gz"),
    "1h": os.environ.get("EURUSD_1H", "data/candles/eurusd_1h_broker.csv.gz"),
    "4h": os.environ.get("EURUSD_4H", "data/candles/eurusd_4h_broker.csv.gz"),
    "1d": os.environ.get("EURUSD_1D", "data/candles/eurusd_1d_broker.csv.gz"),
}

#: Hours per bar, for the elapsed time the filters are driven on. Read from the
#: timestamps where possible; this is the fallback and the sanity check.
HOURS = {"3m": 0.05, "15m": 0.25, "30m": 0.5, "1h": 1.0, "4h": 4.0, "1d": 24.0}

#: Cap on bars per series. The point is comparing models, not using every bar,
#: and a 3m history is two orders of magnitude longer than a 1d one - leaving
#: that uncorrected would compare models on 1d and sample size on 3m.
LIMIT = int(os.environ.get("LIMIT", "6000"))

#: Measurement noise in the normalised units, held fixed across models so the
#: comparison is of dynamics and not of who got a better `R`.
NOISE = float(os.environ.get("NOISE", "0.4"))


def closes(path: Path) -> list[tuple[float, float]]:
    """`(unix seconds, close)`, oldest first. Three shapes on this machine.

    `data/candles` and `data/fine` are gzipped CSV with `ts,open,high,low,
    close,volume`; older extracts carry a `venue` column that has to be
    filtered to FOREXCOM; and `data/seqlab` is an npz with `time` and `close`
    arrays. numpy is imported only on that branch, which is the one that needs
    it.
    """
    if path.suffix == ".npz":
        import numpy as np

        with np.load(path) as bundle:
            stamps = bundle["time"].tolist()
            prices = bundle["close"].tolist()
        return sorted(
            (float(t), float(c))
            for t, c in zip(stamps, prices, strict=True)
            if math.isfinite(t) and math.isfinite(c) and c > 0
        )

    opener = gzip.open if path.suffix == ".gz" else open
    out: list[tuple[float, float]] = []
    with opener(path, "rt") as fh:  # type: ignore[operator]
        for row in csv.DictReader(fh):
            if "venue" in row and row["venue"] not in ("FOREXCOM", "", None):
                continue
            stamp, close = row.get("ts"), row.get("close")
            if not stamp or not close:
                continue
            try:
                out.append((float(stamp), float(close)))
            except ValueError:
                continue
    out.sort()
    return out


def measurements(rows: list[tuple[float, float]]) -> tuple[list[float], list[float]]:
    """Normalise to volatility units of the series' own bar.

    The level is cumulative return in basis points divided by an exponential
    average of absolute bar moves, so every timeframe arrives on one scale -
    which is what makes a single `noise` and a single grid legitimate across six
    of them.
    """
    prices = [c for _t, c in rows]
    alpha = 1.0 - 0.5 ** (1.0 / 60.0)
    average = 0.0
    for i in range(1, len(prices)):
        move = abs(prices[i] - prices[i - 1]) / prices[i - 1] * 10_000
        average = move if i == 1 else average + alpha * (move - average)
    bps = max(average, 0.25)
    times = [t for t, _c in rows]
    values = [(c / prices[0] - 1.0) * 10_000 / bps for c in prices]
    return times, values


def score(build, times: list[float], values: list[float]) -> tuple[float, int]:
    """One pass: accumulated predictive log-likelihood, and points scored.

    Every member answers `loglike` since the family was audited, so this is the
    same call for all four and there is no per-member special case to get wrong.
    """
    engine = build()
    for when, value in zip(times, values, strict=True):
        engine.predict(when)
        engine.update(value, NOISE, when)
    return engine.loglike, engine.seen


def best_of(builds, times, values) -> tuple[float, object]:
    """Fit by grid on this half. Returns the best score and its parameters."""
    best = (-math.inf, None)
    for label, build in builds:
        total, seen = score(build, times, values)
        if not math.isfinite(total) or seen == 0:
            continue
        if total > best[0]:
            best = (total, label)
    return best


def grids():
    """The four models, as (name, [(label, factory), ...]).

    `selective`'s grid is deliberately small and its `read` is pinned at 1.0,
    because `read` and `gain` are not jointly identifiable - one scales the
    state and the other scales the read-out of it - and a grid over both would
    search a ridge rather than a surface.
    """
    jerks = [10.0**e for e in (-6, -5, -4, -3, -2)]
    thetas = (0.1, 0.25, 0.5, 1.0, 2.0)
    sigmas = (0.05, 0.18, 0.5, 1.0)
    drifts = (-2.0, -1.0, 0.0, 0.5413, 1.5)
    scales = (0.0,)
    gains = (0.5, 1.0)
    noises = (0.4, 1.0)

    linear = [(f"jerk={j:.0e}", (lambda j=j: Gaussian(jerk=j))) for j in jerks]
    reverting = [
        (f"theta={t} sigma2={s}", (lambda t=t, s=s: Reverting(theta=t, sigma2=s)))
        for t in thetas
        for s in sigmas
    ]
    lti = [
        (
            f"drift={d} gain={g} noise={n}",
            (lambda d=d, g=g, n=n: Selective(drift=d, scale=0.0, gain=g, noise=n)),
        )
        for d in drifts
        for g in gains
        for n in noises
    ]
    live = [
        (
            f"drift={d} scale={c} gain={g} noise={n}",
            (lambda d=d, c=c, g=g, n=n: Selective(drift=d, scale=c, gain=g, noise=n)),
        )
        for d in drifts
        for c in (0.1, 0.25, 0.5, 1.0)
        for g in gains
        for n in noises
    ]
    _ = scales
    return [
        ("linear (I3 jerk)", linear),
        ("reverting (I2 OU)", reverting),
        ("selective scale=0 (S4D-Real LTI)", lti),
        ("selective (S6, selection on)", live),
    ]


def main() -> None:
    print(f"eurusd, state space members fitted on the first half and scored on the second")
    print(f"noise={NOISE}, up to {LIMIT} bars a timeframe\n")

    table: dict[str, dict[str, float]] = {}
    for name, path_text in SERIES.items():
        path = Path(path_text)
        if not path.exists():
            print(f"  {name:<4} no file at {path}")
            continue
        rows = closes(path)
        if len(rows) > LIMIT:
            rows = rows[-LIMIT:]
        if len(rows) < 400:
            print(f"  {name:<4} only {len(rows)} bars, skipped")
            continue
        times, values = measurements(rows)
        half = len(values) // 2
        gaps = [
            (times[i] - times[i - 1]) / 3600.0
            for i in range(1, min(len(times), 500))
            if times[i] > times[i - 1]
        ]
        median_gap = statistics.median(gaps) if gaps else float("nan")

        print(f"=== {name}: {len(values)} bars, median gap {median_gap:.3f}h ===")
        row: dict[str, float] = {}
        for label, builds in grids():
            fitted, params = best_of(builds, times[:half], values[:half])
            if params is None:
                print(f"  {label:<34} no fit")
                continue
            # Re-run the winner over the held-out half from a fresh state.
            chosen = dict(builds)[params]
            held, seen = score(chosen, times[half:], values[half:])
            per = held / seen if seen else float("nan")
            row[label] = per
            print(f"  {label:<34} held-out {per:+8.4f} /point   ({params})")
        table[name] = row
        if row:
            winner = max(row, key=lambda k: row[k])
            print(f"  -> best: {winner}\n")

    print("=== every timeframe, held-out log-likelihood a point (higher is better) ===")
    labels = [label for label, _ in grids()]
    print(f"  {'timeframe':<10}" + "".join(f"{lab.split(' ')[0][:14]:>16}" for lab in labels))
    for name, row in table.items():
        cells = "".join(f"{row.get(lab, float('nan')):>16.4f}" for lab in labels)
        print(f"  {name:<10}{cells}")

    print("\n=== the one comparison that is a clean experiment ===")
    print("  `selective scale=0` against `selective` with selection on: the same")
    print("  model, one parameter apart. The paper predicts selection loses on a")
    print("  continuous modality like this one.")
    lti_label = "selective scale=0 (S4D-Real LTI)"
    s6_label = "selective (S6, selection on)"
    wins = 0
    for name, row in table.items():
        if lti_label in row and s6_label in row:
            gap = row[s6_label] - row[lti_label]
            wins += gap > 0
            verdict = "selection helps" if gap > 0 else "LTI wins"
            print(f"  {name:<6} selection {gap:+.4f} /point  -> {verdict}")
    print(f"\n  selection helped on {wins} of {len(table)} timeframes")


if __name__ == "__main__":
    main()
