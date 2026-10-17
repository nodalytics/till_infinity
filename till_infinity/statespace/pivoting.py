"""Pivots by directional change: scale-free, alternating, and checkable against a law.

Asked for on 2026-10-17 - "create a very good pivot detector", "the best".

`inputs.pivots` is a fixed-span fractal detector and it is correct about the
hard part: a pivot at bar `k` is only knowable at `k + span`, so it is marked
there. Everything else about it is a compromise, and all four compromises are
the same compromise - **a span is a number of bars, and a swing is a distance
in price**:

* **scale-blind.** A five-bar span finds about the same number of pivots in a
  quiet regime as in a violent one, so in the quiet one it is marking noise and
  in the violent one it is missing structure.
* **magnitude-blind.** A 0.1-sigma wiggle and a 5-sigma reversal are the same
  event to it.
* **a fixed confirmation lag.** A violent reversal waits exactly as long to be
  confirmed as a hesitant one, although the evidence for it arrived much
  sooner.
* **no alternation.** Nothing in it makes a peak follow a trough, so a caller
  building swings from its output has to impose that itself.

## What this does instead

A **directional change**. One threshold, in volatility units: while price is
making new highs the leg extends, and the peak is confirmed the moment price
has retraced `threshold` units from it. Then the direction flips and the same
rule looks for a trough.

That fixes all four at once. It is scale-free because the threshold is in
volatility units; it is magnitude-aware because the threshold *is* a magnitude;
its confirmation lag is **adaptive**, since a sharp reversal crosses the
threshold in one bar and a slow one takes many; and peaks and troughs alternate
by construction, because the state machine has nowhere else to go.

It is also causal in the strict sense this package needs: the confirmation time
is the bar on which the retracement completed, and the extreme's own time is
kept separately. `Pivot` carries both, like `displacements.Displacement`, so a
caller can never accidentally use the one that knows the future.

**This is v1's turn detector, generalised.** `structures/cycles.py` marks a
turn when price retraces `TURN_SIGMAS = 2.0` of its leg - which is this, at one
fixed threshold. So the two detectors this desk has been using are the same
family at different parameters, and `research/docs/dispersion-forecast.md`'s
note that they are "different events" is about the parameter and not about the
method.

## Why it is the best available rather than merely different

Because it can be **checked against a law it did not fit**. Directional-change
events are the intrinsic-time framework of Glattfelder, Dupuis and Olsen
(2011), *Patterns in high-frequency FX data: discovery of 12 empirical scaling
laws*, and two of those laws are predictions about any correct detector:

1. the number of events scales as `N(threshold) ~ threshold ** -E` with
   **E close to 1**;
2. the **overshoot** - how far price runs past a confirmation before the next
   extreme - averages about **one threshold**.

`scaling()` measures both. A detector that reproduces them is doing what it
claims on the data in front of it; one that does not is mis-implemented, and
that is a far better test than looking at a chart. Neither law is fitted here
and neither is used to choose a parameter, so passing them is evidence rather
than tautology.

## The threshold is a choice and the unit may vary

`threshold` is the one parameter and it has no best value: it selects a
**scale**, and which scale matters is the caller's question. What this module
refuses to do is pretend otherwise by hiding a default - so `scaling()` exists
to show what a threshold buys before one is picked.

`unit` may be a scalar or one value per bar. A per-bar unit makes the threshold
track the regime, which is the whole point of measuring a swing in volatility
units, and it is read at the bar where the retracement is **tested** rather
than where the leg began - because that is the information available then.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

#: What kind of reversal a pivot is. The same constants `displacements.py`
#: uses, so a `Pivot` and a `Node` can be read by the same code.
PEAK = 1
TROUGH = -1

#: The threshold a caller gets if it names none, in volatility units. **Not a
#: measured best** - there is no best, because the threshold selects a scale.
#: Two is v1's `TURN_SIGMAS`, so this default makes the detector agree with the
#: turn detector the desk has been running, which is the one choice here that
#: is better than arbitrary.
THRESHOLD = 2.0


@dataclass(frozen=True, slots=True)
class Pivot:
    """One confirmed reversal, with the two times kept apart.

    `at` is when the extreme happened and `confirmed` is when it became
    knowable. A feature built on `at` knows the future; this is the same
    discipline `displacements.Displacement` carries and for the same reason.
    """

    at: float
    confirmed: float
    level: float
    kind: int
    #: Bar of the extreme, and of its confirmation.
    index: int
    confirmed_index: int
    #: Bars from the extreme to its confirmation. **Adaptive**, which is the
    #: thing a fixed span cannot be: a sharp reversal confirms in one bar.
    lag: int
    #: How far the retracement had run when it confirmed, in threshold units.
    #: One means it confirmed exactly on the threshold; more means the bar that
    #: crossed it ran further, which is a gap or a violent bar.
    crossed: float

    @property
    def peak(self) -> bool:
        return self.kind == PEAK


def _units(unit: float | Sequence[float], n: int) -> list[float]:
    """One unit per bar, from a scalar or a sequence. Non-positive is refused."""
    if isinstance(unit, int | float):
        if unit <= 0:
            raise ValueError("unit has to be positive")
        return [float(unit)] * n
    out = [float(v) for v in unit]
    if len(out) != n:
        raise ValueError(f"unit has {len(out)} values for {n} bars")
    if any(v <= 0 or not math.isfinite(v) for v in out):
        raise ValueError("every unit has to be positive and finite")
    return out


def pivots(
    times: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    *,
    unit: float | Sequence[float],
    threshold: float = THRESHOLD,
) -> list[Pivot]:
    """Confirmed reversals by directional change, alternating and causal.

    The first leg's direction is not known in advance, so the detector starts
    undecided and takes whichever side crosses the threshold first. That costs
    one pivot at the beginning and is the honest start: assuming a direction
    would plant one.
    """
    n = len(highs)
    if n != len(lows) or n != len(times):
        raise ValueError("times, highs and lows have to be the same length")
    if threshold <= 0:
        raise ValueError("threshold has to be positive")
    scale = _units(unit, n)
    if n < 2:
        return []

    out: list[Pivot] = []
    # `looking` is +1 while tracking a high (and so hunting a peak), -1 while
    # tracking a low, and 0 before either side has moved enough to say.
    looking = 0
    top = bottom = float(highs[0])
    bottom = float(lows[0])
    top_at = bottom_at = 0

    for i in range(1, n):
        high, low, step = float(highs[i]), float(lows[i]), scale[i]
        if high > top:
            top, top_at = high, i
        if low < bottom:
            bottom, bottom_at = low, i

        if looking >= 0:
            # A peak is confirmed when price has fallen `threshold` from the top.
            fallen = (top - low) / step
            if fallen >= threshold:
                out.append(
                    Pivot(
                        at=float(times[top_at]),
                        confirmed=float(times[i]),
                        level=top,
                        kind=PEAK,
                        index=top_at,
                        confirmed_index=i,
                        lag=i - top_at,
                        crossed=fallen / threshold,
                    )
                )
                looking = -1
                bottom, bottom_at = low, i
                continue
        if looking <= 0:
            risen = (high - bottom) / step
            if risen >= threshold:
                out.append(
                    Pivot(
                        at=float(times[bottom_at]),
                        confirmed=float(times[i]),
                        level=bottom,
                        kind=TROUGH,
                        index=bottom_at,
                        confirmed_index=i,
                        lag=i - bottom_at,
                        crossed=risen / threshold,
                    )
                )
                looking = 1
                top, top_at = high, i
    return out


def overshoots(
    found: Sequence[Pivot], *, unit: float | Sequence[float], threshold: float = THRESHOLD
) -> list[float]:
    """How far price ran past each confirmation, in thresholds, before the next extreme.

    The quantity Glattfelder, Dupuis and Olsen's overshoot law is about: it
    should average **about one threshold**.

    **Measured from the trigger price, not from the previous extreme.** The
    first version of this took the whole peak-to-trough leg, which is the
    retracement *plus* the overshoot - so if the law holds it reads about
    **two**, and it did: 1.67 to 1.78 at the larger thresholds. That is the law
    being satisfied and the measurement naming the wrong quantity, which is
    worse than a wrong number because it looks like a failure.

    The trigger is one threshold below a peak, or above a trough, since that is
    where the retracement completed and the directional change was declared.
    """
    if len(found) < 2:
        return []
    out: list[float] = []
    for a, b in itertools.pairwise(found):
        scale = float(unit if isinstance(unit, int | float) else unit[a.confirmed_index])
        if scale <= 0:
            continue
        trigger = a.level - threshold * scale if a.peak else a.level + threshold * scale
        # **In thresholds, not in volatility units**, because that is what the
        # law is stated in and what this docstring promises. Returning units
        # and leaving the division to the caller is how the two get confused:
        # it read 6.46 where the law wants 1, and 6.46 / 8 is 0.81.
        out.append(abs(b.level - trigger) / scale / threshold)
    return out


def scaling(
    times: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    *,
    unit: float | Sequence[float],
    thresholds: Sequence[float] = (0.5, 1.0, 2.0, 4.0, 8.0),
) -> dict[str, float | list[float]]:
    """Measure the two scaling laws, which is how this detector is validated.

    Returns the event count at each threshold, the fitted exponent `E` in
    `N ~ threshold ** -E`, and the mean overshoot in thresholds. The
    predictions, neither of them fitted here:

    * `E` about **1**;
    * mean overshoot about **1** threshold.

    A reading far from either is a statement about the implementation or about
    the series, and in both cases it is worth knowing before any pivot of it is
    used for anything.
    """
    counts: list[float] = []
    over: list[float] = []
    for threshold in thresholds:
        found = pivots(times, highs, lows, unit=unit, threshold=threshold)
        counts.append(float(len(found)))
        got = overshoots(found, unit=unit, threshold=threshold)
        over.append(float(sum(got) / len(got)) if got else float("nan"))

    # Least squares on the logs, over the thresholds that found anything.
    pairs = [
        (math.log(t), math.log(c))
        for t, c in zip(thresholds, counts, strict=True)
        if c > 0 and t > 0
    ]
    exponent = float("nan")
    if len(pairs) >= 2:
        mean_x = sum(x for x, _ in pairs) / len(pairs)
        mean_y = sum(y for _, y in pairs) / len(pairs)
        spread = sum((x - mean_x) ** 2 for x, _ in pairs)
        if spread > 0:
            slope = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / spread
            # `N ~ threshold ** -E`, so the fitted slope is `-E`.
            exponent = -slope
    return {
        "thresholds": list(thresholds),
        "counts": counts,
        "exponent": exponent,
        "overshoots": over,
    }


def fractal(
    times: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    *,
    span: int,
) -> list[Pivot]:
    """The fixed-span detector, in this module's type, so the two are comparable.

    Same rule as `inputs.pivots` - a strict extreme of its own window,
    confirmed `span` bars later - wrapped so a harness can swap detectors
    without changing anything else. It does **not** alternate, and that is a
    true statement about it rather than something to paper over here: two peaks
    in a row are what a fixed span produces when price makes a lower high
    without a qualifying trough between them.
    """
    n = len(highs)
    out: list[Pivot] = []
    if span < 1:
        return out
    for k in range(span, n - span):
        high, low = float(highs[k]), float(lows[k])
        up = all(float(highs[j]) < high for j in range(k - span, k + span + 1) if j != k)
        down = all(float(lows[j]) > low for j in range(k - span, k + span + 1) if j != k)
        if not (up or down):
            continue
        out.append(
            Pivot(
                at=float(times[k]),
                confirmed=float(times[k + span]),
                level=high if up else low,
                kind=PEAK if up else TROUGH,
                index=k,
                confirmed_index=k + span,
                lag=span,
                crossed=float("nan"),
            )
        )
    return out
