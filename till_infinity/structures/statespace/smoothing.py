"""Where the quantity really was, given everything that happened next.

The filter answers `p(state_t | measurements up to t)`. This answers
`p(state_t | all of them)`, which is a different and usually much better estimate
of the same thing - and the distinction is not academic here, it is the line
between what the desk may read and what research may read.

**A live decision can only ever use the filter.** At the moment a level is
touched, nothing later exists. Reading a smoothed estimate in `engine.py` would
be using tomorrow's bars to decide today's trade, which is the mistake
`vol/learned.py` already documents at length about its own training target.

**Every question *about* the filter is asked afterwards.** Where was the level
really? Was that touch a break or a wick? Is `jerk` the right size? All of those
are asked with the whole series in hand, and for all of them the filter's
estimate is needlessly noisy: at time `t` it has thrown away every measurement
after `t`, and those say a great deal about where the state was.

That is why this module exists here and not in `engine.py`. The same model needs
two inference modes with different honesty rules, and only one of them may ever
be read live.

## What it implements

The Rauch-Tung-Striebel recursion: run the filter forward keeping each step's
state and covariance both before and after the update, then sweep backwards

    C_t   = P_t F(dt)' / P_{t+1|t}
    x_t|T = x_t + C_t (x_{t+1|T} - x_{t+1|t})
    P_t|T = P_t + C_t (P_{t+1|T} - P_{t+1|t}) C_t'

which is exact for a linear-Gaussian model and needs no iteration. `dynamax` and
`nchopin/particles` both expose this beside their filters; the arithmetic is one
3x3 solve per step and is written out here rather than taking a dependency, for
the same reason the rest of the package is.

**Not fixed-lag, and that is the next thing.** This smooths a finished series,
so its latency is the length of the series - fine for a study, useless live. The
fixed-lag form bounds the latency by the lag instead, and is the only version a
desk could run; `family.MISSING` records it.

## What it cannot fix

A smoother is the best estimate **under the model**. If `jerk` is wrong the
smoothed path is confidently wrong in a smooth-looking way, which is harder to
spot by eye than a noisy filter. `diagnostics.residuals` on the *filtered*
innovations is still the specification test - a smoother has no innovations of
its own to check, because it has already used every measurement.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .linear import HOUR, Gaussian

#: Pivot below which a 3x3 solve is treated as singular. The predicted
#: covariance is positive definite in theory and can lose a digit to arithmetic
#: in practice, usually when two measurements arrive at the same instant and the
#: step between them is zero.
SINGULAR = 1e-300


@dataclass(frozen=True, slots=True)
class Smoothed:
    """The state at each time, given every measurement."""

    times: tuple[float, ...]
    #: The smoothed value, rate and acceleration at each time.
    value: tuple[float, ...]
    rate: tuple[float, ...]
    accel: tuple[float, ...]
    #: Standard deviation of the smoothed value. Always at most the filter's,
    #: which is the property worth checking and `tests` does.
    sd: tuple[float, ...]
    #: What the filter alone said, for the comparison the module is about.
    filtered: tuple[float, ...]
    filtered_sd: tuple[float, ...]
    #: The filter's accumulated log-likelihood over the same run. The smoother
    #: does not change it - the likelihood is a property of the forward pass -
    #: so it is carried here to save running the filter twice.
    loglike: float

    def __len__(self) -> int:
        return len(self.times)


def _symmetric_3x3_inverse(
    p00: float, p01: float, p02: float, p11: float, p12: float, p22: float
) -> tuple[float, float, float, float, float, float] | None:
    """Inverse of a symmetric 3x3, as six floats, or None if it is singular."""
    c00 = p11 * p22 - p12 * p12
    c01 = p02 * p12 - p01 * p22
    c02 = p01 * p12 - p02 * p11
    det = p00 * c00 + p01 * c01 + p02 * c02
    if abs(det) < SINGULAR or not math.isfinite(det):
        return None
    c11 = p00 * p22 - p02 * p02
    c12 = p02 * p01 - p00 * p12
    c22 = p00 * p11 - p01 * p01
    return (c00 / det, c01 / det, c02 / det, c11 / det, c12 / det, c22 / det)


def _gain(
    cov: tuple[float, ...], inverse: tuple[float, float, float, float, float, float], dt: float
) -> tuple[tuple[float, float, float], ...]:
    """The smoothing gain `C = P_t F(dt)' P_{t+1|t}^-1`, as three rows.

    Extracted rather than nested in the loop: a closure over the loop's own
    variables is a late-binding trap even when it is called immediately, and this
    is arithmetic rather than control flow.
    """
    p00, p01, p02, p11, p12, p22 = cov
    i00, i01, i02, i11, i12, i22 = inverse
    half = 0.5 * dt * dt
    # A = P_t F', so `A[r][c] = sum_k P[r][k] F[c][k]` - the *columns* of A come
    # from the rows of F, which are `(1, dt, half)`, `(0, 1, dt)` and `(0, 0, 1)`.
    #
    # The first version had these columns reversed, which is the kind of mistake
    # that produces a plausible answer: the smoother still smoothed, still beat
    # the filter, and was 18% worse than it should have been. It was caught by
    # the property that a *wrong* `jerk` beat the true one on 25 seeds out of 25
    # - impossible for a correct RTS, whose mean is the minimum-mean-square
    # estimator at the true parameters - and then localised against a dense
    # reference. `tests/test_statespace.py` now holds that reference.
    rows = (
        (p00 + dt * p01 + half * p02, p01 + dt * p02, p02),
        (p01 + dt * p11 + half * p12, p11 + dt * p12, p12),
        (p02 + dt * p12 + half * p22, p12 + dt * p22, p22),
    )
    return tuple(
        (
            r0 * i00 + r1 * i01 + r2 * i02,
            r0 * i01 + r1 * i11 + r2 * i12,
            r0 * i02 + r1 * i12 + r2 * i22,
        )
        for r0, r1, r2 in rows
    )


def _quad(
    cn: tuple[tuple[float, float, float], ...],
    rows: tuple[tuple[float, float, float], ...],
    a: int,
    b: int,
) -> float:
    """Entry `(a, b)` of `C N C'`, given `CN` and the rows of `C`.

    Module level rather than nested in the backward loop: a closure over the
    loop's own variables is a late-binding trap, and this is arithmetic.
    """
    return cn[a][0] * rows[b][0] + cn[a][1] * rows[b][1] + cn[a][2] * rows[b][2]


def smooth(
    times: Sequence[float],
    measured: Sequence[float],
    *,
    jerk: float,
    noise: float,
    burn: int = 3,
) -> Smoothed | None:
    """Filter forward, then smooth backward. None if there is nothing to smooth.

    `noise` is the measurement variance, constant here - a per-measurement `R`
    is a reasonable extension and is not needed by anything yet, so it is not
    written. `jerk` and `burn` mean what they mean on `Gaussian`.
    """
    n = min(len(times), len(measured))
    if n < 2:
        return None

    g = Gaussian(jerk=jerk, burn=burn)
    # Per step: the state and covariance *after* the update, and the predicted
    # ones for the step that follows. The backward pass needs both.
    post: list[tuple[float, float, float, tuple[float, ...]]] = []
    pred: list[tuple[float, float, float, tuple[float, ...]]] = []
    steps: list[float] = []

    for i in range(n):
        t = float(times[i])
        before_at = g.at
        g.predict(t)
        dt = 0.0 if before_at is None else (t - before_at) / HOUR
        steps.append(max(dt, 0.0))
        # The prediction for *this* step is what the previous step's smoothing
        # gain divides by, so it is recorded before the measurement moves it.
        pred.append((g.value, g.rate, g.accel, (g.p00, g.p01, g.p02, g.p11, g.p12, g.p22)))
        g.update(float(measured[i]), noise)
        post.append((g.value, g.rate, g.accel, (g.p00, g.p01, g.p02, g.p11, g.p12, g.p22)))

    filtered = tuple(row[0] for row in post)
    filtered_sd = tuple(math.sqrt(max(row[3][0], 0.0)) for row in post)

    # Backward: the last point is already conditioned on everything.
    sv = [row[0] for row in post]
    sr = [row[1] for row in post]
    sa = [row[2] for row in post]
    sp = [list(row[3]) for row in post]

    for i in range(n - 2, -1, -1):
        dt = steps[i + 1]
        p00, p01, p02, p11, p12, p22 = post[i][3]
        q00, q01, q02, q11, q12, q22 = pred[i + 1][3]
        inverse = _symmetric_3x3_inverse(q00, q01, q02, q11, q12, q22)
        if inverse is None or dt <= 0.0:
            # No step, or a prediction too degenerate to invert: the smoothed
            # estimate here is the filtered one. Silent would be wrong, but so
            # would raising - a zero step is a legitimate thing for two venues
            # to produce.
            continue
        c0, c1, c2 = _gain((p00, p01, p02, p11, p12, p22), inverse, dt)

        dv = sv[i + 1] - pred[i + 1][0]
        dr = sr[i + 1] - pred[i + 1][1]
        da = sa[i + 1] - pred[i + 1][2]
        sv[i] = post[i][0] + c0[0] * dv + c0[1] * dr + c0[2] * da
        sr[i] = post[i][1] + c1[0] * dv + c1[1] * dr + c1[2] * da
        sa[i] = post[i][2] + c2[0] * dv + c2[1] * dr + c2[2] * da

        # P_t|T = P_t + C (P_{t+1|T} - P_{t+1|t}) C', **all six entries**.
        #
        # The first version updated only the value's variance and left the other
        # five at their filtered values, on the reasoning that nothing
        # downstream reads them. The recursion reads them: `sp[i + 1]` is
        # `P_{t+1|T}`, so a partial update feeds the next step back a covariance
        # that is smoothed in one entry and filtered in five. It showed up as a
        # smoother that was *under-confident* - rmse over its own stated sd of
        # 0.745 where a correct one is 1.0 - and, more tellingly, as a wrong
        # `jerk` beating the true one on 25 seeds out of 25. The RTS mean is the
        # minimum-mean-square estimator at the true parameters, so anything
        # beating it is a bug and not a discovery.
        nxt = sp[i + 1]
        n00, n01, n02 = nxt[0] - q00, nxt[1] - q01, nxt[2] - q02
        n11, n12, n22 = nxt[3] - q11, nxt[4] - q12, nxt[5] - q22
        rows = (c0, c1, c2)
        # CN, then (CN)C'. Symmetric by construction, so six of the nine are kept.
        cn = tuple(
            (
                r[0] * n00 + r[1] * n01 + r[2] * n02,
                r[0] * n01 + r[1] * n11 + r[2] * n12,
                r[0] * n02 + r[1] * n12 + r[2] * n22,
            )
            for r in rows
        )

        base = post[i][3]
        sp[i][0] = max(base[0] + _quad(cn, rows, 0, 0), 0.0)
        sp[i][1] = base[1] + _quad(cn, rows, 0, 1)
        sp[i][2] = base[2] + _quad(cn, rows, 0, 2)
        sp[i][3] = max(base[3] + _quad(cn, rows, 1, 1), 0.0)
        sp[i][4] = base[4] + _quad(cn, rows, 1, 2)
        sp[i][5] = max(base[5] + _quad(cn, rows, 2, 2), 0.0)

    return Smoothed(
        times=tuple(float(t) for t in times[:n]),
        value=tuple(sv),
        rate=tuple(sr),
        accel=tuple(sa),
        sd=tuple(math.sqrt(max(row[0], 0.0)) for row in sp),
        filtered=filtered,
        filtered_sd=filtered_sd,
        loglike=g.loglike,
    )
