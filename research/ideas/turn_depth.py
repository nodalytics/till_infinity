"""Does turn depth beat a running mean on real markets, and does timing still fail?

v1's `structures/cycles.py` found that it does: *skill against the running mean
is negative or zero on every simulated arm and positive on 8 of 8 constructed
spreads, +0.03 to +0.19*, while its `when` head *scores positive on the nulls
too, so its positive values are a property of the metric rather than of the
series*. That is one of the few measured-positive results in v1 and the reason
turn depth was the first thing ported into statespace.

`statespace/depths.py` is the port. This is its measurement, and it is **not a
reproduction**: v1 marks a turn when price retraces `TURN_SIGMAS = 2.0` of its
leg, this marks one at a **confirmed pivot** through
`displacements.sequence`, and those are different events. What is being checked
is the shape of the claim - depth beats a causal running mean, timing does not -
on a different detector and on a wider panel than constructed spreads.

## The unit, and the artefact that came from getting it wrong

The first version of this harness passed `unit = 1.0` to
`displacements.sequence` and argued that skill is invariant to it - which is
true for a **constant** unit and is exactly why a constant one is the wrong
choice. A constant unit leaves swing sizes in raw price, and a price level that
drifts drags the sizes with it: a running mean lags a drifting level while an
AR(1) tracks it, so the level's drift is read as depth persistence.

It showed up as **`depth ar1` at +0.3983 on the Deriv volatility synthetics**,
whose generator fixes sigma and therefore has no swing-size structure to find
at all. The gentle walk control did not catch it, because its own level barely
moves - 0.001 a bar over 12,000 bars is a 20% range, where a Volatility 75
index covers several multiples. **A control has to be as volatile as the thing
it is controlling for**, which is the lesson worth keeping.

The fix is to run the detector on **log prices**. A pivot is unchanged by a
monotone transform, so the reversal locations are identical, but a difference
of log prices is a return and is scale-free by construction - so a drifting
level cannot enter the size. The unit is then the series' own return scale, and
the invariance argument above finally holds, for a reason rather than by
assumption.

## Both spaces, because they are different numbers

v1 scored the depth in **raw** volatility units. `depths.py` logs it, which is
the right state for a positive quantity. A skill in one space is not a skill in
the other, so both are reported rather than one being quietly presented as the
comparable figure.

## The arms

* `depth ar1` - online AR(1), the two-parameter model a mean-reverting
  magnitude wants, and the arm the family has no member for.
* `depth walk` - the previous depth. Persistence with no reversion.
* `depth member` - a family member driven on the turn clock.
* `span ar1` - the same on duration. **Expected to fail**, and carried so the
  failure is visible: v1's timing head read positive on its nulls.

## The controls

* a **geometric walk**, where there is no reversion in swing size to find;
* the **constant-sigma synthetics**, whose generator fixes sigma;
* **shuffled depths**, which keeps every depth and destroys their order, so any
  arm reading above zero there is reading its own construction.

The pivot reach is swept, because what counts as a turn is exactly that
parameter and a result that only exists at one value of it is not a result.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.structures.statespace.depths import (  # noqa: E402
    Turn,
    depths,
    from_pivots,
    score,
)
from till_infinity.structures.statespace.displacements import sequence  # noqa: E402
from till_infinity.structures.statespace.pivoting import pivots  # noqa: E402
from till_infinity.structures.statespace.reverting import Reverting  # noqa: E402

FRAMES = ("1h", "4h")
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 8
LIMIT = 12000
#: The fractal detector's confirmation reach, in bars. Swept because it *is*
#: the definition of a turn for that detector.
SPANS = (3, 5, 10)
#: The directional-change detector's threshold, in volatility units. Swept for
#: the same reason, and 2.0 is v1's `TURN_SIGMAS` - so one of these cells is
#: the v1 turn detector exactly.
EDGES = (1.0, 2.0, 4.0)
SEED = 20261017


def _walk(n: int, rng: random.Random, step: float = 0.001) -> dict[str, np.ndarray]:
    """A geometric walk: no reversion in swing size to find.

    `step` is swept, because a control only has power against a level-drift
    artefact if its own level drifts as much as the series it is controlling
    for - and the quiet walk alone did not catch one.
    """
    closes = [100.0]
    for _ in range(n):
        closes.append(closes[-1] * math.exp(rng.gauss(0.0, step)))
    price = np.asarray(closes[1:], dtype=float)
    wick = np.abs(np.asarray([rng.gauss(0.0, step) for _ in range(n)]))
    return {
        "time": np.arange(n, dtype=float) * 3600.0,
        "open": price,
        "high": price * np.exp(wick),
        "low": price * np.exp(-wick),
        "close": price,
    }


def _change(bars: dict[str, np.ndarray], edge: float, logged: bool) -> list[Turn]:
    """Depths from the directional-change detector, on log prices.

    Same log-price treatment as the fractal arm, so the two differ only in how
    a turn is defined and the comparison is about the detector.
    """
    closes = np.asarray(bars["close"], dtype=float)
    if np.any(closes <= 0):
        return []
    logs = {
        k: np.log(np.maximum(np.asarray(bars[k], dtype=float), 1e-300))
        for k in ("close", "high", "low")
    }
    steps = np.abs(np.diff(logs["close"]))
    unit = float(np.mean(steps[steps > 0])) if np.any(steps > 0) else 0.0
    if unit <= 0:
        return []
    found = pivots(
        [float(v) for v in bars["time"]],
        [float(v) for v in logs["high"]],
        [float(v) for v in logs["low"]],
        unit=unit,
        threshold=edge,
    )
    return from_pivots(found, unit=unit, logged=logged)


def _series(bars: dict[str, np.ndarray], span: int, logged: bool) -> list[Turn]:
    """Pivots on **log** prices, so a swing size is a return and not a price.

    The unit is the series' own mean absolute one-bar log return, which puts
    the sizes in volatility units as `sequence` documents. A pivot is unchanged
    by the log, so this changes the sizes and not where the turns are.
    """
    closes = np.asarray(bars["close"], dtype=float)
    if np.any(closes <= 0):
        return []
    logs = {
        k: np.log(np.maximum(np.asarray(bars[k], dtype=float), 1e-300))
        for k in ("close", "high", "low")
    }
    steps = np.abs(np.diff(logs["close"]))
    unit = float(np.mean(steps[steps > 0])) if np.any(steps > 0) else 0.0
    if unit <= 0:
        return []
    moves = sequence(
        [float(v) for v in bars["time"]],
        [float(v) for v in logs["close"]],
        [float(v) for v in logs["high"]],
        [float(v) for v in logs["low"]],
        span=span,
        unit=unit,
    )
    return depths(moves, logged=logged)


def _shuffled(series: list[Turn], rng: random.Random) -> list[Turn]:
    """Every depth kept, their order destroyed. The null for persistence."""
    values = [turn.value for turn in series]
    spans = [turn.span for turn in series]
    rng.shuffle(values)
    rng.shuffle(spans)
    return [
        Turn(when=turn.when, value=v, span=s, direction=turn.direction)
        for turn, v, s in zip(series, values, spans, strict=True)
    ]


def main() -> None:
    print(
        "Turn depth, ported from v1. Skill against a causal running mean, so\n"
        "0.00 is 'no better than the mean seen so far'. v1 read +0.03 to +0.19\n"
        "on 8 of 8 constructed spreads with a different turn detector.\n"
        "`span ar1` is the arm that failed there and has to fail here too.\n"
    )
    rng = random.Random(SEED)
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)

    arms = ("depth ar1", "depth walk", "depth member", "span ar1")
    detectors: list[tuple[str, float]] = [("fractal", float(s)) for s in SPANS]
    detectors += [("change", e) for e in EDGES]
    for frame in FRAMES:
        for kind, setting in detectors:
            for label in ("walk", *TRADED, *CONTROLS):
                if label != "walk" and label not in groups:
                    continue
                for shuffle in (False, True):
                    for logged in (True, False):
                        pooled: dict[str, list[float]] = {}
                        turns: list[int] = []
                        names = (
                            [f"walk{k}" for k in range(PER_CLASS)]
                            if label == "walk"
                            else sorted(groups[label])[:PER_CLASS]
                        )
                        for name in names:
                            # The loud walk is the control that has power
                            # against a level-drift artefact; the quiet one did
                            # not. Half of each.
                            bars = (
                                _walk(LIMIT, rng, 0.001 if int(name[-1]) % 2 else 0.02)
                                if label == "walk"
                                else load(name, frame)
                            )
                            if bars is None:
                                continue
                            cut = {k: v[-LIMIT:] for k, v in bars.items()}
                            series = (
                                _series(cut, int(setting), logged)
                                if kind == "fractal"
                                else _change(cut, setting, logged)
                            )
                            if shuffle:
                                series = _shuffled(series, rng)
                            if len(series) < 60:
                                continue
                            turns.append(len(series))
                            got = score(series, member=Reverting())
                            for arm in arms:
                                value = got.get(arm, float("nan"))
                                if math.isfinite(value):
                                    pooled.setdefault(arm, []).append(value)
                        if not pooled:
                            continue
                        tag = (
                            f"{label}, {frame}, {kind}={setting:g}, {'log' if logged else 'raw'}"
                            + ("  [SHUFFLED]" if shuffle else "")
                        )
                        rows = next(iter(pooled.values()))
                        print(
                            f"\n=== {tag}   n={len(rows)} feeds, "
                            f"median {int(np.median(turns))} turns each"
                        )
                        print(f"  {'arm':<14}{'median':>9}{'min':>9}{'max':>9}{'above 0':>9}")
                        for arm in arms:
                            got_rows = pooled.get(arm)
                            if not got_rows:
                                continue
                            print(
                                f"  {arm:<14}{float(np.median(got_rows)):>9.4f}"
                                f"{min(got_rows):>9.4f}{max(got_rows):>9.4f}"
                                f"{sum(v > 0 for v in got_rows):>6}/{len(got_rows):<3}"
                            )


if __name__ == "__main__":
    main()
