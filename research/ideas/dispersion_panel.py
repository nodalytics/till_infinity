"""Which dispersion is most forecastable, and does topology add anything to it?

Two questions asked on 2026-10-17, both about the same quantity.

**"test tda on dispersion."** `topology.md` already measured topology against
production's *shock* forecaster and found it adds nothing: 4 of 250 incremental
cells passed, 3 survived Benjamini-Hochberg, and none on GARCH walks. The
killer column was the one that looked like a win - volatility-free topology
does separate regimes, FX 15m +0.021 and crypto +0.028, but **GARCH walks gain
the same**, +0.013 to +0.017. So what persistent homology sees is volatility
clustering.

That makes this the natural follow-up rather than a repeat. If topology is a
restatement of volatility, it should predict **dispersion** well - and the only
question worth asking is whether it predicts dispersion better than a
three-term regression on realised variance already does. The prior result makes
a sharp prediction: it will not, and the GARCH control will gain the same.
Running it is how that prediction gets to be wrong.

**The estimator panel.** The second question came with a reference on
statistical measures of spread, and the point it raises is one this desk had
skipped: `dispersion_ml.py` uses log-Parkinson as both the target and the
feature, and Parkinson is one estimator among many. Range, interquartile
range, trim-range, standard deviation, mean absolute deviation, coefficient of
variation and the variance-mean ratio are all measures of the same thing with
different robustness, and they are not interchangeable here - a bar's range
systematically exceeds its close-to-close move, which `one-bar-band.md` already
measured as a reason `Span` must not set the one-bar predictive scale.

So this asks which **definition** of dispersion carries the most structure,
before anything tries to forecast it. That ordering matters: a forecastability
result is about a target as much as about a model, and choosing the target by
convenience is how a weak result gets blamed on the model.

## Arms

* `har` on each **per-bar** estimator's own lags - the null, per target. Only
  per-bar estimators may be targets, and the reason is measured rather than
  assumed: see `PER_BAR`.
* the **other estimators** as extra features, window ones included, which asks
  whether the robust measures see something Parkinson misses rather than merely
  restating it.
* `tda` - Vietoris-Rips H0 and H1 of a delay embedding of returns, reduced to
  persistence-landscape norms, appended to HAR. Scored as the **increment**
  over HAR, because that is the only number that can mean anything here.

## Controls

* **GARCH(1,1)**, the constants already in `statespace/nulls.py`. Clustering by
  construction and no topology beyond it, so an increment here is the
  clustering effect and not a topological one. This is `topology.md`'s own
  control and reproducing its reading is the point.
* **shuffled** returns, which destroys clustering and ordering together. Every
  arm must read about zero.

`ripser` is on the lab and not installed locally, so the import is guarded the
same way `research/harness/topology.py` guards it: a local smoke test runs H0
only, and the real reading comes from the lab.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from pattern_fingerprint import CACHE, classify, load  # noqa: E402

try:  # ripser is on the lab; locally this falls back to H0 from a spanning tree
    from ripser import ripser as _ripser

    HAVE_RIPSER = True
except Exception:  # pragma: no cover - the local path
    _ripser = None
    HAVE_RIPSER = False

FRAMES = ("1h",)
TRADED = ("fx_major", "fx_cross", "metal")
PER_CLASS = 6
LIMIT = 8000
LAGS = (1, 5, 22)
HORIZONS = (5, 20)
#: Bars in the window every estimator and the embedding are computed over.
WINDOW = 100
#: Delay embedding: dimension and lag, as `topology.md` used.
EMBED, DELAY = 3, 1
#: Points subsampled from the window before Rips, because the complex is
#: quadratic in points and the landscape norms are stable under thinning.
CLOUD = 60
RIDGES = (1e-6, 1e-3, 1.0)
#: Bars between rows. At a stride of one, consecutive rows share 99 of their
#: 100 window bars and their forward targets share `horizon - 1` bars, which
#: inflates the row count without adding information and makes the penalty
#: choice noisy. A stride equal to the horizon would make the forward windows
#: disjoint; five is the compromise that keeps enough rows to fit on, and it
#: also divides the Rips cost by five.
STRIDE = 5
GARCH = (0.02, 0.10, 0.88)
SEED = 20261017


# ----------------------------------------------------------- the estimators


#: Estimators defined on a single bar. **Only these may be targets.**
#:
#: A window estimator shares `WINDOW - 1` of its bars with its own next value,
#: so forecasting its forward average is very nearly forecasting itself: on the
#: GARCH control, `har` on a 100-bar standard deviation read **+0.9297** and on
#: a 100-bar MAD **+0.9298**, against **+0.0027** on per-bar Parkinson. That is
#: not a statement about volatility, it is the autocorrelation of an
#: overlapping moving average, and taking it for a result is the trap
#: `overlapping-windows-inflate-permutation-nulls` is already on record about.
#: The window estimators stay, as **features**, where looking back over a
#: window is exactly what a feature is supposed to do.
PER_BAR = ("parkinson", "garman_klass", "rogers_satchell")


def _logs(bars: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """One log-dispersion series per estimator, all over the same window.

    Every one is logged, because a dispersion is positive and a state should
    not be, and every one is a **variance** in log units so the panel is
    comparable: an estimator that returned a standard deviation would read half
    the slope of the others for no reason a reader could see.
    """
    high, low, close, open_ = bars["high"], bars["low"], bars["close"], bars["open"]
    ret = np.diff(np.log(np.maximum(close, 1e-300)), prepend=np.log(max(close[0], 1e-300)))
    span = np.log(np.maximum(high, 1e-300) / np.maximum(low, 1e-300))

    out: dict[str, np.ndarray] = {}
    # Per-bar estimators: one number per bar, no window needed.
    out["parkinson"] = span * span / (4.0 * math.log(2.0))
    # Garman-Klass adds the body, which is what makes it more efficient than
    # the range alone on a driftless bar.
    body = np.log(np.maximum(close, 1e-300) / np.maximum(open_, 1e-300))
    out["garman_klass"] = np.maximum(
        0.5 * span * span - (2.0 * math.log(2.0) - 1.0) * body * body, 1e-300
    )
    # Rogers-Satchell is the one that survives a drift inside the bar.
    hc = np.log(np.maximum(high, 1e-300) / np.maximum(close, 1e-300))
    ho = np.log(np.maximum(high, 1e-300) / np.maximum(open_, 1e-300))
    lc = np.log(np.maximum(low, 1e-300) / np.maximum(close, 1e-300))
    lo = np.log(np.maximum(low, 1e-300) / np.maximum(open_, 1e-300))
    out["rogers_satchell"] = np.maximum(hc * ho + lc * lo, 1e-300)

    # Window estimators over the same WINDOW of returns. These are the ones the
    # spread reference names, and the robust pair is the reason to have them:
    # a trimmed range and a MAD do not move when one bar has a long wick.
    n = len(ret)
    sd = np.full(n, np.nan)
    mad = np.full(n, np.nan)
    iqr = np.full(n, np.nan)
    trim = np.full(n, np.nan)
    cv = np.full(n, np.nan)
    for i in range(WINDOW, n):
        chunk = ret[i - WINDOW + 1 : i + 1]
        centre = float(np.mean(chunk))
        sd[i] = float(np.var(chunk))
        mad[i] = float(np.mean(np.abs(chunk - centre))) ** 2
        q1, q3 = np.percentile(chunk, (25.0, 75.0))
        iqr[i] = float(q3 - q1) ** 2
        kept = np.sort(chunk)[WINDOW // 8 : WINDOW - WINDOW // 8]
        trim[i] = float(kept[-1] - kept[0]) ** 2
        cv[i] = float(np.std(chunk) / abs(centre)) if abs(centre) > 1e-12 else np.nan
    out["sd"] = sd
    out["mad"] = mad
    out["iqr"] = iqr
    out["trim_range"] = trim
    # CV is dimensionless and its denominator is a near-zero mean return, so it
    # is expected to be unstable - the reference says so explicitly. It is here
    # to be shown unstable rather than left out on an argument.
    out["cv"] = cv

    return {k: np.log(np.maximum(v, 1e-300)) for k, v in out.items()}


# ----------------------------------------------------------- the topology


def _landscape(cloud: np.ndarray) -> tuple[float, ...]:
    """Persistence-landscape style summaries of H0 and H1, as six numbers.

    Total persistence, maximum persistence and the count of features with a
    lifetime above the diagram's own median, per homology degree. Six numbers
    rather than a full landscape because the readout is a ridge regression and
    a function-valued feature would be spent on its own discretisation.
    """
    if not HAVE_RIPSER:
        # H0 alone, from the Euclidean minimum spanning tree: H0 lifetimes of a
        # Rips filtration are exactly the MST edge lengths, so this half is
        # exact rather than approximate - only H1 is missing locally.
        from scipy.sparse.csgraph import minimum_spanning_tree
        from scipy.spatial.distance import squareform, pdist

        tree = minimum_spanning_tree(squareform(pdist(cloud))).toarray()
        lives = tree[tree > 0]
        diagrams = [np.column_stack([np.zeros(len(lives)), lives]), np.empty((0, 2))]
    else:
        got = _ripser(cloud, maxdim=1)["dgms"]
        diagrams = [np.asarray(d) for d in got[:2]]

    out: list[float] = []
    for diagram in diagrams:
        if len(diagram) == 0:
            out.extend((0.0, 0.0, 0.0))
            continue
        lives = diagram[:, 1] - diagram[:, 0]
        lives = lives[np.isfinite(lives)]
        if len(lives) == 0:
            out.extend((0.0, 0.0, 0.0))
            continue
        out.extend(
            (
                float(np.sum(lives)),
                float(np.max(lives)),
                float(np.sum(lives > np.median(lives))),
            )
        )
    return tuple(out)


def _spatial(cloud: np.ndarray) -> tuple[float, ...]:
    """Spatial statistics of the point cloud, from Geospatial Analysis (7th ed).

    de Smith, Goodchild and Longley catalogue these for point patterns, and a
    delay embedding **is** a point pattern - so they apply directly, cost
    nothing next to a Rips complex, and each one says something a reader can
    name. They are the cheap rival to the landscape norms, and that is the
    point of having both: if six moments of a cloud match what persistent
    homology buys, then what homology is reading is the cloud's shape and not
    its topology.

    Every one is computed on the **standardised** cloud, so none of them is
    volatility in disguise - the scale is what every other arm already carries.

    * **standard distance** - root mean squared distance from the centroid. The
      cloud's own dispersion, near one by construction here, kept as the
      sanity feature that says the standardisation worked.
    * **ellipse anisotropy** - the ratio of the largest to the smallest
      eigenvalue of the covariance. On a delay embedding this is serial
      correlation made geometric: i.i.d. returns give a round cloud and a
      correlated series gives a tilted, elongated one.
    * **nearest-neighbour index** - observed mean nearest-neighbour distance
      over what complete spatial randomness would give. Below one is
      clustered, above one is regular, and on a trajectory it measures
      recurrence: how often the embedded path returns near where it has been.
    * **Ripley's K ratio** - the same clustering question at two radii at once,
      which is what makes it multi-scale rather than a single contrast.
    """
    middle = cloud.mean(axis=0)
    offsets = cloud - middle
    standard = float(np.sqrt(np.mean(np.sum(offsets * offsets, axis=1))))

    cov = np.cov(cloud, rowvar=False)
    eigen = np.linalg.eigvalsh(cov) if cov.ndim == 2 else np.asarray([float(cov)])
    eigen = np.maximum(eigen, 1e-15)
    anisotropy = float(eigen[-1] / eigen[0])

    gaps = np.sqrt(np.maximum(((cloud[:, None, :] - cloud[None, :, :]) ** 2).sum(axis=2), 0.0))
    np.fill_diagonal(gaps, np.inf)
    near = gaps.min(axis=1)
    n, dim = cloud.shape
    # Expected nearest-neighbour distance under CSR in `dim` dimensions, from
    # the volume of the cloud's bounding box. The constant is the Gamma-function
    # form; the ratio is what is read, so a loose volume estimate biases every
    # window the same way and cancels in the regression.
    extent = float(np.prod(np.maximum(cloud.max(axis=0) - cloud.min(axis=0), 1e-12)))
    density = n / max(extent, 1e-12)
    ball = math.pi ** (dim / 2.0) / math.gamma(dim / 2.0 + 1.0)
    expected = math.gamma(1.0 + 1.0 / dim) / (density * ball) ** (1.0 / dim)
    index = float(np.mean(near) / expected) if expected > 0 else 0.0

    finite = gaps[np.isfinite(gaps)]
    scale = float(np.median(finite)) if len(finite) else 1.0
    inner = float(np.mean(finite < 0.5 * scale)) if len(finite) else 0.0
    outer = float(np.mean(finite < scale)) if len(finite) else 0.0
    ripley = inner / outer if outer > 0 else 0.0

    return (standard, anisotropy, index, ripley)


def _clouds(ret: np.ndarray, at: np.ndarray, rng):
    """The standardised delay-embedding cloud for each index in `at`."""
    for i in at:
        chunk = ret[i - WINDOW + 1 : i + 1]
        points = np.column_stack(
            [chunk[k : len(chunk) - (EMBED - 1 - k) * DELAY] for k in range(EMBED)]
        )
        if len(points) > CLOUD:
            pick = rng.choice(len(points), size=CLOUD, replace=False)
            points = points[np.sort(pick)]
        spread = float(points.std())
        yield points / spread if spread > 1e-15 else points


def _topology(ret: np.ndarray, at: np.ndarray, rng) -> np.ndarray:
    """Topological features of the delay embedding, one row per index in `at`."""
    rows = []
    for i in at:
        chunk = ret[i - WINDOW + 1 : i + 1]
        points = np.column_stack(
            [chunk[k : len(chunk) - (EMBED - 1 - k) * DELAY] for k in range(EMBED)]
        )
        if len(points) > CLOUD:
            pick = rng.choice(len(points), size=CLOUD, replace=False)
            points = points[np.sort(pick)]
        # Standardised, so the topology is of the *shape* and not of the
        # scale - the scale is what every other arm here already carries, and
        # leaving it in would hand topology a volatility feature in disguise.
        spread = float(points.std())
        rows.append(_landscape(points / spread if spread > 1e-15 else points))
    return np.asarray(rows, dtype=float)


# ----------------------------------------------------------- the regressions


def _ridge(x: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    mean = x.mean(axis=0)
    centred = x - mean
    gram = centred.T @ centred
    coef = np.linalg.solve(gram + lam * np.eye(gram.shape[0]), centred.T @ (y - y.mean()))
    return np.concatenate([[float(y.mean() - mean @ coef)], coef])


def _apply(coef: np.ndarray, x: np.ndarray) -> np.ndarray:
    return coef[0] + x @ coef[1:]


def _r2(truth: np.ndarray, guess: np.ndarray, base: float) -> float:
    floor = float(np.sum((truth - base) ** 2))
    return 1.0 - float(np.sum((truth - guess) ** 2)) / floor if floor > 0 else float("nan")


def _fit(x: np.ndarray, y: np.ndarray, cut: int, base: float, purge: int = 0) -> float:
    """Ridge with the penalty chosen inside the training half only.

    `purge` drops the rows straddling the split, so a scored target never
    shares a bar with one the fit has seen.
    """
    best, pick = -math.inf, RIDGES[0]
    inner = max(cut // 2, 1)
    for lam in RIDGES:
        coef = _ridge(x[:inner], y[:inner], lam)
        got = _r2(
            y[inner + purge : cut], _apply(coef, x[inner + purge : cut]), float(y[:inner].mean())
        )
        if got > best:
            best, pick = got, lam
    held = slice(cut + purge, None)
    return _r2(y[held], _apply(_ridge(x[:cut], y[:cut], pick), x[held]), base)


def _garch(n: int, rng) -> dict[str, np.ndarray]:
    """GARCH(1,1): clustering by construction, no topology beyond it.

    **The bar's range is scaled by the bar's sigma and not by its realised
    return**, which is how a real bar behaves and which the first version got
    wrong. Scaling the wick by `abs(return)` makes the Parkinson estimate
    proportional to one standardised draw, so its log carries about 1.1 of
    pure noise and HAR read **+0.0006** on a process that is persistent by
    construction. A control that cannot be forecast is not a control - it
    would have made every topological increment look like a win.
    """
    omega, alpha, beta = GARCH
    var = omega / max(1.0 - alpha - beta, 1e-6)
    sigma = np.empty(n)
    ret = np.empty(n)
    for i in range(n):
        shock = rng.normal(0.0, 1.0)
        sigma[i] = math.sqrt(var) * 1e-3
        ret[i] = sigma[i] * shock
        var = omega + alpha * shock * shock + beta * var
    close = 100.0 * np.exp(np.cumsum(ret))
    wick = np.abs(rng.normal(0.0, 1.0, n)) * sigma
    return {
        "time": np.arange(n, dtype=float) * 3600.0,
        "open": np.concatenate([[close[0]], close[:-1]]),
        "high": close * np.exp(wick),
        "low": close * np.exp(-wick),
        "close": close,
    }


def score(bars: dict[str, np.ndarray], horizon: int, rng, shuffle: bool = False) -> dict:
    """Per-estimator HAR, the cross-estimator panel, and the TDA increment."""
    close = bars["close"]
    ret = np.diff(np.log(np.maximum(close, 1e-300)), prepend=np.log(max(close[0], 1e-300)))
    if shuffle:
        ret = ret[rng.permutation(len(ret))]
        close = 100.0 * np.exp(np.cumsum(ret))
        wick = np.abs(rng.normal(0.0, 1.0, len(ret))) * np.abs(ret)
        bars = {
            "time": bars["time"],
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": close * np.exp(wick),
            "low": close * np.exp(-wick),
            "close": close,
        }

    logs = _logs(bars)
    # `WINDOW + max(LAGS)`, not the max of the two: the window estimators are
    # undefined for their first WINDOW bars, and `lagged` then averages 22 of
    # those - so a row at `WINDOW + 3` silently carries nan through the whole
    # design. The first smoke test read `nan` on every window estimator for
    # exactly this reason.
    start = WINDOW + max(LAGS) + EMBED * DELAY
    stop = len(close) - horizon
    if stop - start < 800:
        return {}
    at = np.arange(start, stop, STRIDE)

    def lagged(series: np.ndarray) -> np.ndarray:
        return np.asarray(
            [[float(np.mean(series[i - lag + 1 : i + 1])) for lag in LAGS] for i in at], dtype=float
        )

    def forward(series: np.ndarray) -> np.ndarray:
        return np.asarray(
            [float(np.mean(series[i + 1 : i + 1 + horizon])) for i in at], dtype=float
        )

    out: dict[str, float] = {}
    usable = {k: v for k, v in logs.items() if np.isfinite(v[start:stop]).all()}
    # Named rather than silently absent. `cv` is expected here: its denominator
    # is a near-zero mean return and the reference says so explicitly, so it is
    # carried in order to be shown unstable rather than left out on an argument.
    out.update({f"dropped:{k}": float("nan") for k in logs if k not in usable})
    # The split is purged: rows whose forward window would reach into the
    # training period are dropped rather than scored, so no test target shares
    # a bar with a bar the fit has seen.
    cut = len(at) // 2
    purge = max(1, horizon // STRIDE + 1)

    # Question one: which definition of dispersion carries the most structure,
    # over the per-bar estimators only - see `PER_BAR`.
    for name in PER_BAR:
        if name not in usable:
            continue
        y = forward(usable[name])
        base = float(y[:cut].mean())
        out[f"har:{name}"] = _fit(lagged(usable[name]), y, cut, base, purge)

    # Question two: do the other estimators add to the best-known one.
    if "parkinson" in usable:
        y = forward(usable["parkinson"])
        base = float(y[:cut].mean())
        wide = np.hstack([lagged(s) for s in usable.values()])
        out["panel:parkinson"] = _fit(wide, y, cut, base, purge)

        # Question three: does the shape of the trajectory add anything, by
        # either route - cheap spatial statistics or persistent homology.
        har_only = lagged(usable["parkinson"])
        space = np.asarray([_spatial(c) for c in _clouds(ret, at, rng)], dtype=float)
        okay = np.isfinite(space).all(axis=0)
        if okay.any():
            out["spatial:parkinson"] = _fit(
                np.hstack([har_only, space[:, okay]]), y, cut, base, purge
            )

        topo = _topology(ret, at, rng)
        good = np.isfinite(topo).all(axis=0)
        if good.any():
            out["tda:parkinson"] = _fit(np.hstack([har_only, topo[:, good]]), y, cut, base, purge)
            out["tda+panel:parkinson"] = _fit(np.hstack([wide, topo[:, good]]), y, cut, base, purge)
            if okay.any():
                out["tda+spatial:parkinson"] = _fit(
                    np.hstack([har_only, topo[:, good], space[:, okay]]), y, cut, base, purge
                )
    return out


def main() -> None:
    print(
        "Which dispersion is forecastable, and does topology add to it?\n"
        f"ripser: {'yes' if HAVE_RIPSER else 'NO - H0 only, this is a smoke test'}\n"
        "R2 out of sample, fitted on each series' first half. `har:X` is the\n"
        "three-lag regression on X's own history; `panel:` adds every other\n"
        "estimator; `tda:` adds the landscape norms to har alone.\n"
        "**The only number that matters for topology is tda minus har**, and\n"
        "the GARCH row is what that increment has to beat.\n"
    )
    rng = np.random.default_rng(SEED)
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)

    for frame in FRAMES:
        for label in ("garch", *TRADED):
            if label != "garch" and label not in groups:
                continue
            for horizon in HORIZONS:
                for shuffle in (False, True):
                    pooled: dict[str, list[float]] = {}
                    names = (
                        [f"garch{k}" for k in range(PER_CLASS)]
                        if label == "garch"
                        else sorted(groups[label])[:PER_CLASS]
                    )
                    for name in names:
                        bars = _garch(LIMIT, rng) if label == "garch" else load(name, frame)
                        if bars is None:
                            continue
                        cut = {k: v[-LIMIT:] for k, v in bars.items()}
                        for key, got in score(cut, horizon, rng, shuffle=shuffle).items():
                            if math.isfinite(got):
                                pooled.setdefault(key, []).append(got)
                    if not pooled:
                        continue
                    tag = f"{label}, {frame}, h={horizon}" + ("  [SHUFFLED]" if shuffle else "")
                    print(f"\n=== {tag}")
                    print(f"  {'arm':<24}{'median R2':>11}{'min':>9}{'max':>9}")
                    for key in sorted(pooled):
                        rows = pooled[key]
                        print(
                            f"  {key:<24}{float(np.median(rows)):>11.4f}"
                            f"{min(rows):>9.4f}{max(rows):>9.4f}"
                        )
                    har = pooled.get("har:parkinson")
                    for which in ("tda", "spatial", "tda+spatial"):
                        got = pooled.get(f"{which}:parkinson")
                        if not (har and got and len(har) == len(got)):
                            continue
                        lift = [a - b for a, b in zip(got, har)]
                        print(
                            f"  --> {which:<12} increment over har: "
                            f"median {float(np.median(lift)):+.4f}, "
                            f"positive on {sum(v > 0 for v in lift)}/{len(lift)}"
                        )


if __name__ == "__main__":
    main()
