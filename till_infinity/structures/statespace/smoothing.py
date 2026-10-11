"""Where the quantity really was, given everything that happened next.

The filter answers `p(state_t | measurements up to t)`. This answers
`p(state_t | all of them)`, which is a different and usually much better
estimate of the same thing - and the distinction is not academic here, it is the
line between what the desk may read and what research may read.

**A live decision can only ever use the filter.** At the moment a level is
touched, nothing later exists. Reading a smoothed estimate in `engine.py` would
be using tomorrow's bars to decide today's trade, which is the mistake
`vol/learned.py` already documents at length about its own training target.

**Every question *about* the filter is asked afterwards.** Where was the level
really? Was that touch a break or a wick? Is the process noise the right size?
All of those are asked with the whole series in hand, and for all of them the
filter's estimate is needlessly noisy: at time `t` it has thrown away every
measurement after `t`, and those say a great deal about where the state was.

That is why this module exists here and not in `engine.py`. The same model needs
two inference modes with different honesty rules, and only one of them may ever
be read live.

## It smooths any member, which it did not used to

The first version built a `linear.Gaussian` itself, so it could not smooth
`reverting.Reverting` - **the member that actually wins**. It takes a factory
now, and a member joins by being able to answer three questions:

| | |
| --- | --- |
| `state()` | the state vector |
| `covariance()` | the full covariance, dense |
| `transition(dt)` | `F(dt)` |

**The third is why a factory alone was not enough.** The Rauch-Tung-Striebel
gain is `C_t = P_t F(dt)' P_{t+1|t}^-1`, so a smoother needs the transition and
not merely the ability to run the filter forward. A member that cannot state its
own `F` cannot be smoothed, and that is a true statement about the member rather
than a shortcoming here.

Dimension is read from the member, so two-state and three-state members go
through the same recursion.

## What it implements

Run the filter forward keeping each step's state and covariance both before and
after the update, then sweep backwards:

    C_t   = P_t F(dt)' / P_{t+1|t}
    x_t|T = x_t + C_t (x_{t+1|T} - x_{t+1|t})
    P_t|T = P_t + C_t (P_{t+1|T} - P_{t+1|t}) C_t'

Exact for a linear-Gaussian model, no iteration. `dynamax` and
`nchopin/particles` both expose this beside their filters; the arithmetic is one
small dense solve per step and is written out here rather than taking a
dependency, for the same reason the rest of the package is.

**`smooth` is the whole-series form and `lagged` is the fixed-lag one.** This
one smooths a finished series, so its latency is the length of the series - fine
for a study, useless live. `lagged` bounds the latency by the lag instead and is
the version a desk could run: it answers *where was this a lag ago, given what
has happened since*, which is a better basis for placing a stop than where the
filter thought it was at the time.

## What it cannot fix

A smoother is the best estimate **under the model**. If the process noise is
wrong the smoothed path is confidently wrong in a smooth-looking way, which is
harder to spot by eye than a noisy filter. `diagnostics.residuals` on the
*filtered* innovations is still the specification test - a smoother has no
innovations of its own to check, because it has already used every measurement.

And it was wrong itself, for exactly one commit. `_gain` built the columns of
`P F'` in reverse, which still smoothed and still beat the filter and was 19%
worse than it should have been. What exposed it was the property that a wrong
process noise beat the true one on 25 seeds out of 25 - impossible for a correct
RTS, whose mean is the minimum-mean-square estimator at the true parameters.
`tests/test_statespace.py` holds the dense reference that localised it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .linear import HOUR

#: Pivot below which a solve is treated as singular. The predicted covariance is
#: positive definite in theory and can lose a digit to arithmetic in practice,
#: usually when two measurements arrive at the same instant and the step between
#: them is zero.
SINGULAR = 1e-300

Matrix = Sequence[Sequence[float]]


def _transpose(a: Matrix) -> list[list[float]]:
    return [list(col) for col in zip(*a, strict=True)]


def _matmul(a: Matrix, b: Matrix) -> list[list[float]]:
    cols = list(zip(*b, strict=True))
    return [[sum(x * y for x, y in zip(row, col, strict=True)) for col in cols] for row in a]


def _matvec(a: Matrix, v: Sequence[float]) -> list[float]:
    return [sum(x * y for x, y in zip(row, v, strict=True)) for row in a]


def _inverse(a: Matrix) -> list[list[float]] | None:
    """Inverse by Gauss-Jordan with partial pivoting, or None if singular.

    General in the dimension, because the members are not all the same size:
    `linear` carries three states and `reverting` two. It replaced a
    hand-written 3x3 cofactor expansion that could only ever serve one of them.
    """
    n = len(a)
    work = [
        [float(v) for v in row] + [1.0 if i == j else 0.0 for j in range(n)]
        for i, row in enumerate(a)
    ]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(work[r][col]))
        if abs(work[pivot][col]) < SINGULAR:
            return None
        work[col], work[pivot] = work[pivot], work[col]
        scale = work[col][col]
        work[col] = [v / scale for v in work[col]]
        for row in range(n):
            if row == col:
                continue
            factor = work[row][col]
            if factor:
                work[row] = [v - factor * w for v, w in zip(work[row], work[col], strict=True)]
    return [row[n:] for row in work]


@dataclass(frozen=True, slots=True)
class Smoothed:
    """The state at each time, given every measurement."""

    times: tuple[float, ...]
    #: The smoothed state at each time, in the member's own `NAMES` order.
    states: tuple[tuple[float, ...], ...]
    #: What the member calls its components, so a caller need not guess.
    names: tuple[str, ...]
    #: Standard deviation of the **first** component, the observed one. Always
    #: at most the filter's, which is the property worth checking and `tests`
    #: does.
    sd: tuple[float, ...]
    #: What the filter alone said about that first component, for the comparison
    #: the module is about.
    filtered: tuple[float, ...]
    filtered_sd: tuple[float, ...]
    #: The filter's accumulated log-likelihood over the same run. The smoother
    #: does not change it - the likelihood is a property of the forward pass -
    #: so it is carried here to save running the filter twice.
    loglike: float

    def __len__(self) -> int:
        return len(self.times)

    @property
    def value(self) -> tuple[float, ...]:
        """The observed component at each time. Every member's first state."""
        return tuple(row[0] for row in self.states)

    @property
    def rate(self) -> tuple[float, ...]:
        """The second component. Every member written here has one."""
        return tuple(row[1] for row in self.states)

    def component(self, name: str) -> tuple[float, ...]:
        """One named component, or `KeyError` if this member has no such state.

        `reverting` has no acceleration, so asking it for one has to fail rather
        than return a zero that reads like a measurement.
        """
        try:
            at = self.names.index(name)
        except ValueError as exc:
            raise KeyError(f"{name!r} is not a state of this member: {self.names}") from exc
        return tuple(row[at] for row in self.states)


def smooth(
    build: Callable[[], object],
    times: Sequence[float],
    measured: Sequence[float],
    *,
    noise: float,
) -> Smoothed | None:
    """Filter forward with a fresh `build()`, then smooth backward.

    `build` returns a configured filter - `lambda: Gaussian(jerk=...)` or
    `lambda: Reverting(sigma2=..., theta=...)`. **A factory rather than an
    instance**, because a filter that has already seen measurements would fold
    that history into the result and the caller would have no way to tell.

    `noise` is the measurement variance, constant here. A per-measurement `R` is
    a reasonable extension and nothing needs it yet, so it is not written.

    None when there is nothing to smooth, or when the member cannot state its
    own transition - which is how a member declines to be smoothed.
    """
    n = min(len(times), len(measured))
    if n < 2:
        return None

    filt = build()
    for needed in ("state", "covariance", "transition", "update", "predict"):
        if not callable(getattr(filt, needed, None)):
            return None
    names = tuple(getattr(filt, "NAMES", ()) or ())

    post: list[tuple[list[float], list[list[float]]]] = []
    pred: list[tuple[list[float], list[list[float]]]] = []
    steps: list[float] = []

    for i in range(n):
        t = float(times[i])
        before = getattr(filt, "at", None)
        filt.predict(t)
        steps.append(max(0.0, 0.0 if before is None else (t - before) / HOUR))
        # The prediction for *this* step is what the previous step's smoothing
        # gain divides by, so it is recorded before the measurement moves it.
        pred.append((list(filt.state()), [list(r) for r in filt.covariance()]))
        filt.update(float(measured[i]), noise)
        post.append((list(filt.state()), [list(r) for r in filt.covariance()]))

    filtered = tuple(row[0][0] for row in post)
    filtered_sd = tuple(math.sqrt(max(row[1][0][0], 0.0)) for row in post)

    # Backward: the last point is already conditioned on everything.
    smooth_x = [list(row[0]) for row in post]
    smooth_p = [[list(r) for r in row[1]] for row in post]

    for i in range(n - 2, -1, -1):
        dt = steps[i + 1]
        inverse = _inverse(pred[i + 1][1]) if dt > 0.0 else None
        if inverse is None:
            # No step, or a prediction too degenerate to invert: the smoothed
            # estimate here is the filtered one. Silent would be wrong, but so
            # would raising - a zero step is a legitimate thing for two venues
            # to produce.
            continue
        gain = _matmul(_matmul(post[i][1], _transpose(filt.transition(dt))), inverse)

        delta = [a - b for a, b in zip(smooth_x[i + 1], pred[i + 1][0], strict=True)]
        moved = _matvec(gain, delta)
        smooth_x[i] = [a + b for a, b in zip(post[i][0], moved, strict=True)]

        spread = [
            [a - b for a, b in zip(row_s, row_p, strict=True)]
            for row_s, row_p in zip(smooth_p[i + 1], pred[i + 1][1], strict=True)
        ]
        correction = _matmul(_matmul(gain, spread), _transpose(gain))
        smooth_p[i] = [
            [a + b for a, b in zip(row_p, row_c, strict=True)]
            for row_p, row_c in zip(post[i][1], correction, strict=True)
        ]

    return Smoothed(
        times=tuple(float(t) for t in times[:n]),
        states=tuple(tuple(row) for row in smooth_x),
        names=names,
        sd=tuple(math.sqrt(max(row[0][0], 0.0)) for row in smooth_p),
        filtered=filtered,
        filtered_sd=filtered_sd,
        loglike=float(getattr(filt, "loglike", 0.0)),
    )


@dataclass(slots=True)
class Lagged:
    """One fixed-lag estimate: the state at `when`, given `lag` steps after it.

    `delay` is how many measurements were used beyond `when`, which is `lag`
    once the window has filled and fewer while it is filling. A caller acting
    on this is acting `delay` bars late on purpose.
    """

    when: float
    #: The smoothed state at `when`, in the member's `NAMES` order.
    state: tuple[float, ...]
    #: Standard deviation of the first component, the observed one.
    sd: float
    #: What the filter alone said at `when`, for the comparison that matters.
    filtered: float
    filtered_sd: float
    delay: int

    @property
    def value(self) -> float:
        return self.state[0] if self.state else 0.0

    @property
    def revision(self) -> float:
        """How far hindsight moved the estimate. The quantity worth watching.

        A revision much larger than `filtered_sd` means the filter was
        confidently wrong at the time, which is a statement about the process
        noise rather than about the smoother.
        """
        return self.value - self.filtered


def lagged(
    build: Callable[[], object],
    times: Sequence[float],
    measured: Sequence[float],
    *,
    noise: float,
    hours: float | None = None,
    lag: int = 10,
) -> list[Lagged] | None:
    """Fixed-lag smoothing: the estimate at each time, `lag` steps late.

    **The version a live desk can run**, where `smooth` is not. `smooth`
    conditions on the whole series, so its answer for ten minutes ago is not
    available until the series ends; this conditions on exactly `lag`
    measurements past each point, so the answer for ten minutes ago arrives
    `lag` bars after it - late, bounded, and usable.

    The recursion is the same Rauch-Tung-Striebel sweep, run over a window
    instead of over everything, so this is not an approximation of a different
    algorithm - it is the same algorithm conditioned on less. Two consequences
    worth stating because they are easy to assume away:

    * it is **not** equal to `smooth` at the same point. It conditions on `lag`
      future measurements rather than all of them, which is the definition
      rather than a shortfall, and it converges on `smooth` as `lag` grows. The
      test asserts that convergence, which is the only honest check of it.
    * the first `lag` points come back with a smaller `delay`, because there is
      less future to use yet. They are returned rather than dropped, with the
      `delay` that was actually available, so a caller can decide.

    **Pass `hours`, not `lag`.** `hours` is converted to observations from the
    series' own median spacing, so "revise what I believed two hours ago" means
    that on every timeframe; `lag` is kept for the case where a caller genuinely
    means a number of observations.

    Cost is `O(n * lag)` against `smooth`'s `O(n)`, with a window of `lag + 1`
    states held rather than the series. For `lag = 10` on three states that is
    about thirty numbers.

    None on the same terms as `smooth`: nothing to smooth, or a member that
    cannot state its own transition.
    """
    n = min(len(times), len(measured))
    if n < 2:
        return None

    # **`hours` is the portable parameter and `lag` is the fallback.** A lag of
    # ten observations is two and a half hours at 15m and ten days at 1d, so
    # stated that way it is not a latency budget - it is a latency budget times
    # a timeframe. `__init__.py` carries this as a package rule; this is the
    # one place that was still counting bars after it was written.
    if hours is not None:
        gaps = sorted(
            (float(times[i]) - float(times[i - 1])) / HOUR
            for i in range(1, min(n, 500))
            if times[i] > times[i - 1]
        )
        if gaps:
            middle = gaps[len(gaps) // 2]
            lag = max(round(hours / middle), 1) if middle > 0 else lag
    if lag < 1:
        return None

    filt = build()
    for needed in ("state", "covariance", "transition", "update", "predict"):
        if not callable(getattr(filt, needed, None)):
            return None

    # The rolling window: post-update and pre-update states, and the step that
    # separates each from its predecessor. Held as plain lists and trimmed, so
    # the memory is the lag rather than the series.
    post: list[tuple[list[float], list[list[float]]]] = []
    pred: list[tuple[list[float], list[list[float]]]] = []
    steps: list[float] = []
    stamps: list[float] = []

    out: list[Lagged] = []

    for i in range(n):
        t = float(times[i])
        before = getattr(filt, "at", None)
        filt.predict(t)
        steps.append(max(0.0, 0.0 if before is None else (t - before) / HOUR))
        pred.append((list(filt.state()), [list(r) for r in filt.covariance()]))
        filt.update(float(measured[i]), noise)
        post.append((list(filt.state()), [list(r) for r in filt.covariance()]))
        stamps.append(t)

        if len(post) > lag + 1:
            post.pop(0)
            pred.pop(0)
            steps.pop(0)
            stamps.pop(0)

        # Emit for the oldest point in the window once it has any future, and
        # at the end flush what is left so nothing is silently dropped.
        if len(post) < 2:
            continue
        if i < n - 1 and len(post) <= lag:
            continue

        window = len(post)
        smooth_x = [list(row[0]) for row in post]
        smooth_p = [[list(r) for r in row[1]] for row in post]
        for k in range(window - 2, -1, -1):
            dt = steps[k + 1]
            inverse = _inverse(pred[k + 1][1]) if dt > 0.0 else None
            if inverse is None:
                continue
            gain = _matmul(_matmul(post[k][1], _transpose(filt.transition(dt))), inverse)
            delta = [a - b for a, b in zip(smooth_x[k + 1], pred[k + 1][0], strict=True)]
            moved = _matvec(gain, delta)
            smooth_x[k] = [a + b for a, b in zip(post[k][0], moved, strict=True)]
            spread = [
                [a - b for a, b in zip(row_s, row_p, strict=True)]
                for row_s, row_p in zip(smooth_p[k + 1], pred[k + 1][1], strict=True)
            ]
            correction = _matmul(_matmul(gain, spread), _transpose(gain))
            smooth_p[k] = [
                [a + b for a, b in zip(row_p, row_c, strict=True)]
                for row_p, row_c in zip(post[k][1], correction, strict=True)
            ]

        out.append(
            Lagged(
                when=stamps[0],
                state=tuple(smooth_x[0]),
                sd=math.sqrt(max(smooth_p[0][0][0], 0.0)),
                filtered=post[0][0][0],
                filtered_sd=math.sqrt(max(post[0][1][0][0], 0.0)),
                delay=window - 1,
            )
        )

        # At the end, walk the rest of the window out so the tail is covered
        # with whatever future each point had.
        if i == n - 1:
            # To `window`, not `window - 1`: the last measurement has no
            # future at all, so its fixed-lag estimate *is* its filtered one -
            # and emitting it at `delay = 0` keeps the output aligned with the
            # input, which a caller zipping the two will assume.
            out.extend(
                Lagged(
                    when=stamps[drop],
                    state=tuple(smooth_x[drop]),
                    sd=math.sqrt(max(smooth_p[drop][0][0], 0.0)),
                    filtered=post[drop][0][0],
                    filtered_sd=math.sqrt(max(post[drop][1][0][0], 0.0)),
                    delay=window - 1 - drop,
                )
                for drop in range(1, window)
            )

    return out
