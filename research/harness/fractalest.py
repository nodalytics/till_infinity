"""Fractal and multifractal estimators, vectorised over a rolling causal window.

The estimators the fractal literature actually offers a time series, as opposed
to the Mandelbrot renderers that dominate a search for "fractal code":
Higuchi's fractal dimension, box counting on the price graph, detrended
fluctuation analysis, rescaled range, and the curvature of the structure-function
scaling exponent, which is multifractality.

**Every function here returns one number per window and reads only that window.**
A caller gets `(n_windows,)` from `windows(x, width, stride)`, whose last column
is bar `t`, so a reading is usable at the close of `t` with no look-ahead. That
is the whole reason these are written strided rather than taken from a library:
`research/docs/overlapping-outcome-windows-leak` records a direction AUC of 0.79
collapsing to 0.51 once the outcome windows stopped overlapping, and an estimator
that quietly reads one bar ahead produces the same shape of wrong answer.

**Amplitude is divided out of every shape statistic, deliberately.** `higuchi`
is scale-free because `L(k)` is homogeneous of degree one in the series, so the
log-log slope cannot see the amplitude; `box_dimension` normalises each window
to the unit square; `dfa`, `rescaled_range` and `structure_scaling` are ratios
of a statistic at two scales. Without that a "fractal dimension" is a volatility
reading with a fractal's name on it, which is the failure
`research/docs/topology.md` reports for levels, ranges and shapes and the one
`auc-is-free-on-volatility-targets` prices: AUC 0.805 on a constant-volatility
process against 0.525 within volatility strata. Normalising does not make these
statistics independent of volatility - that is the measured question - it only
stops the dependence being arithmetic.

**The estimators are biased at these window lengths and the bias is the point.**
A 128-bar window gives four or five usable scales, so a log-log slope over them
has a standard error of order 0.05 and a bias that depends on the scale set. A
textbook `H = 0.5` is therefore not the null for any of these; the null is the
same estimator run over a walk with the same bar geometry, which is what
`research/docs/statespace-fractals.md` found when its roughness estimator
returned 0.141 for a process whose true exponent was 0.5.
"""

from __future__ import annotations

import numpy as np

#: Below this many bars a window has too few scales for a log-log slope: at
#: width 32 the dyadic scale set is {4, 8} and two points fit a line exactly,
#: so the residual carries no information and the slope is a difference of two
#: noisy numbers.
LEAST_WIDTH = 48

#: Guard for a logarithm of a statistic that can be exactly zero. A flat window
#: - every close identical, which `Step Index` produces and a dead FX hour does
#: too - gives `R/S = 0` and `F(s) = 0`, and `log 0` would poison the slope
#: rather than the one window.
FLOOR = 1e-12


def windows(x: np.ndarray, width: int, stride: int = 1) -> np.ndarray:
    """A read-only `(n, width)` view whose row `i` **ends** at bar `i * stride + width - 1`.

    The last column is the newest bar, so every statistic below is causal at
    that bar. `stride` thins the sample without changing any window's contents.
    """
    x = np.asarray(x, dtype=float)
    if width < 2 or len(x) < width:
        return np.empty((0, width), dtype=float)
    view = np.lib.stride_tricks.sliding_window_view(x, width)
    return view[::stride]


def _slope(log_scale: np.ndarray, log_stat: np.ndarray) -> np.ndarray:
    """Least-squares slope of each row of `log_stat` against the shared `log_scale`.

    Closed form rather than `polyfit` in a loop: the scales are identical for
    every window, so the design matrix is shared and the whole panel is one
    pair of dot products.
    """
    centred = log_scale - log_scale.mean()
    denominator = float(centred @ centred)
    if denominator <= 0.0:
        return np.full(log_stat.shape[0], np.nan)
    return (log_stat - log_stat.mean(axis=1, keepdims=True)) @ centred / denominator


def _dyadic(width: int, smallest: int = 4, largest_fraction: int = 4) -> list[int]:
    """Scales that divide `width`, from `smallest` up to `width // largest_fraction`.

    Divisors only, so a window reshapes into whole chunks and no tail is
    silently dropped - a dropped tail makes the largest scale's statistic read
    a different sample from the smallest's.
    """
    top = max(width // largest_fraction, smallest)
    return [s for s in (2**k for k in range(2, 20)) if smallest <= s <= top and width % s == 0]


def higuchi(win: np.ndarray, k_max: int = 8) -> np.ndarray:
    """Higuchi's fractal dimension of each window of a **series** (not its returns).

    `L(k)`, the mean normalised length of the series sampled every `k`th point,
    falls as `k**-D`. A straight line gives `D = 1`, a random walk about 1.5 and
    white noise about 2.
    """
    win = np.asarray(win, dtype=float)
    if win.size == 0:
        return np.empty(0)
    n = win.shape[0]
    width = win.shape[1]
    scales: list[int] = []
    lengths: list[np.ndarray] = []
    for k in range(1, k_max + 1):
        if (width - 1) // k < 2:
            continue
        total = np.zeros(n)
        used = 0
        for start in range(k):
            index = np.arange(start, width, k)
            if len(index) < 2:
                continue
            steps = len(index) - 1
            # `k * k`, not `k`. One factor rescales the subsampled length back
            # onto the full index range; the second is the one that makes the
            # exponent a dimension. With a single `k` every reading comes out
            # **exactly 1.0 too low** - a line reads 0, a walk 0.495 and white
            # noise 0.998 - which is a plausible-looking number for a quantity
            # whose whole range is 1 to 2, and the three anchors are the only
            # thing that catches it.
            total += (
                np.abs(np.diff(win[:, index], axis=1)).sum(axis=1)
                * (width - 1)
                / (steps * k * k)
            )
            used += 1
        if used:
            scales.append(k)
            lengths.append(total / used)
    if len(scales) < 3:
        return np.full(n, np.nan)
    stat = np.log(np.maximum(np.stack(lengths, axis=1), FLOOR))
    return -_slope(np.log(np.asarray(scales, dtype=float)), stat)


def box_dimension(win: np.ndarray, boxes: tuple[int, ...] = (2, 4, 8, 16, 32)) -> np.ndarray:
    """Box-counting dimension of the **graph** of each window, on the unit square.

    Each window is mapped to `[0, 1]**2` - index across, value scaled by the
    window's own range - and the boxes of side `1/m` the curve touches are
    counted column by column. A monotone line touches about `m` boxes and gives
    1; a curve that fills the square touches about `m**2` and gives 2.

    **Normalising by the window's own range is what makes this a shape
    statistic.** Without it the count rises with the amplitude and the
    "dimension" is a volatility reading.
    """
    win = np.asarray(win, dtype=float)
    if win.size == 0:
        return np.empty(0)
    n, width = win.shape
    low = win.min(axis=1, keepdims=True)
    span = win.max(axis=1, keepdims=True) - low
    flat = span[:, 0] <= 0.0
    unit = (win - low) / np.where(span > 0.0, span, 1.0)
    usable = [m for m in boxes if m <= width // 2 and width % m == 0]
    if len(usable) < 3:
        return np.full(n, np.nan)
    counts: list[np.ndarray] = []
    for m in usable:
        columns = unit.reshape(n, m, width // m)
        # A column's boxes are the rows between its own low and high. `floor`
        # of a value that lands exactly on 1.0 would index one box past the
        # grid, so the top edge is clipped into the last box.
        top = np.minimum(np.floor(columns.max(axis=2) * m), m - 1)
        bottom = np.minimum(np.floor(columns.min(axis=2) * m), m - 1)
        counts.append((top - bottom + 1.0).sum(axis=1))
    stat = np.log(np.maximum(np.stack(counts, axis=1), FLOOR))
    out = _slope(np.log(np.asarray(usable, dtype=float)), stat)
    out[flat] = np.nan
    return out


def dfa(win: np.ndarray, order: int = 1) -> np.ndarray:
    """Detrended fluctuation analysis exponent of each window of **increments**.

    The increments are integrated, cut into chunks of `s`, each chunk detrended
    by a polynomial of `order`, and the root-mean-square residual `F(s)` fitted
    as `s**H`. White noise gives 0.5, a persistent series more.

    Pass returns here, not prices: `dfa` integrates internally, so passing a
    price integrates twice and reads about one higher.
    """
    win = np.asarray(win, dtype=float)
    if win.size == 0:
        return np.empty(0)
    n, width = win.shape
    scales = _dyadic(width)
    if len(scales) < 3:
        return np.full(n, np.nan)
    walk = np.cumsum(win - win.mean(axis=1, keepdims=True), axis=1)
    stat: list[np.ndarray] = []
    for s in scales:
        chunks = walk.reshape(n, width // s, s)
        grid = np.arange(s, dtype=float)
        design = np.vander(grid, order + 1)
        # One pseudo-inverse per scale, shared by every window and every chunk:
        # the chunk length sets the design matrix and nothing else does.
        projection = design @ np.linalg.pinv(design)
        residual = chunks - chunks @ projection.T
        stat.append(np.sqrt(np.maximum((residual**2).mean(axis=(1, 2)), 0.0)))
    fluctuation = np.log(np.maximum(np.stack(stat, axis=1), FLOOR))
    return _slope(np.log(np.asarray(scales, dtype=float)), fluctuation)


def rescaled_range(win: np.ndarray) -> np.ndarray:
    """Hurst exponent by rescaled range - the statistic R/S analysis is built on.

    Each window of **increments** is cut into chunks of `s`; within a chunk the
    mean-adjusted cumulative sum's range is divided by the chunk's standard
    deviation, averaged over chunks, and fitted as `s**H`.

    **Biased high at these lengths.** The small-sample bias of R/S is well known
    and upward - Anis-Lloyd exists to correct it - so a reading of 0.57 on a
    128-bar window is not evidence of persistence. The shuffled arm of the same
    window length is the reference.
    """
    win = np.asarray(win, dtype=float)
    if win.size == 0:
        return np.empty(0)
    n, width = win.shape
    # `largest_fraction=2`, so a 64-bar window gets the scales {8, 16, 32}
    # rather than {8, 16}. R/S needs a chunk of at least 8 to have a range at
    # all, and at `width // 4` a 64-bar window affords only two scales - two
    # points fit a line exactly, the function returned **all-NaN at width 64**,
    # and a whole column of a power table read `nan` with no error raised.
    scales = _dyadic(width, smallest=8, largest_fraction=2)
    if len(scales) < 3:
        return np.full(n, np.nan)
    stat: list[np.ndarray] = []
    for s in scales:
        chunks = win.reshape(n, width // s, s)
        deviation = np.cumsum(chunks - chunks.mean(axis=2, keepdims=True), axis=2)
        spread = deviation.max(axis=2) - deviation.min(axis=2)
        scale = chunks.std(axis=2)
        ratio = np.where(scale > 0.0, spread / np.where(scale > 0.0, scale, 1.0), np.nan)
        stat.append(np.nanmean(ratio, axis=1))
    with np.errstate(invalid="ignore"):
        fluctuation = np.log(np.maximum(np.stack(stat, axis=1), FLOOR))
    return _slope(np.log(np.asarray(scales, dtype=float)), fluctuation)


#: The moment orders the structure function is fitted over. Positive only, and
#: `research/docs/statespace-fractals.md` is why: a negative moment of a price
#: increment divides by a number that is exactly zero whenever the quote did not
#: move, which `Step Index` and a dead FX hour both produce, so `h(-4)` reports
#: the quote grid rather than the market. The curvature below needs no negative
#: arm.
MOMENTS = (0.5, 1.0, 2.0, 3.0, 4.0)


def structure_scaling(
    win: np.ndarray, moments: tuple[float, ...] = MOMENTS
) -> tuple[np.ndarray, np.ndarray]:
    """`(hurst, curvature)` from the structure function of each window of a **series**.

    `S_q(s) = mean |x(t + s) - x(t)|**q` scales as `s**zeta(q)`, and the
    multifractal random walk gives `zeta(q) = q H - lambda**2 q (q - 1) / 2`. So
    a quadratic in `q` through the fitted exponents returns `H` and
    `lambda**2` - the **curvature is the multifractality**, and a monofractal
    series has `zeta` linear and a curvature of zero.

    This is the rolling form of the statistic `statespace-fractals.md` measured
    once per instrument, where traded markets read `lambda**2` of 0.076 against
    0.001 to 0.010 for every control. That study fitted the whole series; this
    fits one window, so it is far noisier and is **not** comparable in level.
    """
    win = np.asarray(win, dtype=float)
    if win.size == 0:
        return np.empty(0), np.empty(0)
    n, width = win.shape
    scales = [s for s in (2**k for k in range(0, 20)) if 1 <= s <= width // 4]
    if len(scales) < 3:
        return np.full(n, np.nan), np.full(n, np.nan)
    orders = np.asarray(moments, dtype=float)
    log_scale = np.log(np.asarray(scales, dtype=float))
    # **Each window is normalised by its own one-step scale, and `FLOOR` is why.**
    # The moment taken is `mean |increment|**q`, so on a log-price series whose
    # 15-minute increments are 4e-4 the `q = 4` moment is 2.6e-14 - below an
    # absolute floor of 1e-12, which then clamps it. Measured: the same planted
    # series read a curvature of 0.019 on a wide scale and **0.188** on a
    # realistic one, a tenfold error driven entirely by the units, and real FX
    # sits on the clamped side. Dividing a window by a constant shifts every
    # `log S_q(s)` by `-q log c` at every `s`, so the slope in `log s` - which
    # is all `zeta` is - cannot change: the normalisation is free.
    one_step = np.abs(np.diff(win, axis=1)).mean(axis=1)
    dead = one_step <= 0.0
    unit = win / np.where(dead, 1.0, one_step)[:, None]
    log_moment = np.empty((n, len(orders), len(scales)))
    for j, s in enumerate(scales):
        step = np.abs(unit[:, s:] - unit[:, :-s])
        for i, q in enumerate(orders):
            log_moment[:, i, j] = np.log(np.maximum((step**q).mean(axis=1), FLOOR))
    centred = log_scale - log_scale.mean()
    zeta = (log_moment - log_moment.mean(axis=2, keepdims=True)) @ centred / float(centred @ centred)
    # `zeta(q) = q H - (lambda^2 / 2) q (q - 1)`, so regressing zeta on the two
    # columns `q` and `-q(q-1)/2` returns `H` and `lambda^2` directly.
    design = np.stack([orders, -orders * (orders - 1.0) / 2.0], axis=1)
    fitted = zeta @ np.linalg.pinv(design).T
    hurst, curvature = fitted[:, 0].copy(), fitted[:, 1].copy()
    hurst[dead] = np.nan
    curvature[dead] = np.nan
    return hurst, curvature


def fbm(count: int, hurst: float, rng: np.random.Generator) -> np.ndarray:
    """Fractional Brownian **increments** with exponent `hurst`, exactly.

    Davies-Harte: embed the fractional-Gaussian-noise autocovariance in a
    circulant matrix, take its spectrum, and a complex Gaussian scaled by the
    root of that spectrum transforms back to a path with the right covariance.
    Exact rather than approximate, which matters because this is the **plant**
    for the power curve - an approximate generator makes a blind test look
    sensitive and a sensitive one look blind.

    The embedding needs a non-negative spectrum; it is non-negative for every
    `hurst` in `(0, 1)` for fractional Gaussian noise, and the `maximum` below
    only guards floating-point noise at the ends.
    """
    if not 0.0 < hurst < 1.0:
        raise ValueError(f"hurst {hurst} is not strictly inside (0, 1)")
    size = 1
    while size < count:
        size *= 2
    lag = np.arange(size + 1, dtype=float)
    two = 2.0 * hurst
    gamma = 0.5 * (
        np.abs(lag - 1.0) ** two - 2.0 * np.abs(lag) ** two + np.abs(lag + 1.0) ** two
    )
    circulant = np.concatenate([gamma, gamma[-2:0:-1]])
    spectrum = np.maximum(np.fft.fft(circulant).real, 0.0)
    noise = rng.standard_normal(2 * size) + 1j * rng.standard_normal(2 * size)
    path = np.fft.fft(np.sqrt(spectrum / (2 * size)) * noise).real
    return path[:count]


def bars_from_path(path: np.ndarray, per_bar: int) -> dict[str, np.ndarray]:
    """OHLC bars whose high and low are the **path's own extremes** over `per_bar` steps.

    `research/docs/excursion-scaling.md` spent three control failures on this:
    a generator that set `high = max(open, close) + |N(0, 1)| * sigma` is a walk
    *plus independent noise*, which inflates a one-bar range far more than a
    ninety-six-bar one and returned a scaling exponent of 0.42 to 0.45 where the
    truth was 0.5. Aggregating real path steps is the fix, and both walks then
    read 0.505 to 0.527.
    """
    steps = np.asarray(path, dtype=float)
    usable = (len(steps) // per_bar) * per_bar
    level = np.cumsum(steps[:usable]).reshape(-1, per_bar)
    opens = np.concatenate([[0.0], level[:-1, -1]])
    return {
        "open": opens,
        "high": np.maximum(level.max(axis=1), opens),
        "low": np.minimum(level.min(axis=1), opens),
        "close": level[:, -1],
    }
