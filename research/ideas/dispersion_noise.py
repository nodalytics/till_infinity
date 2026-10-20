"""What measurement variance belongs on a log range estimator, and what the guess costs.

`statespace/config.py` says it plainly: **the one unmeasured constant is
`noise`.** Every member in the package takes a measurement *variance*, the
service's observation is `log(garman_klass(o, h, l, c))`, and nothing here has
ever measured the sampling variance of that. The two standard derivations
disagree by 4.6x:

* a close-to-close square is one chi-square degree of freedom, so
  `Var(log r^2) = pi^2 / 2 = 4.9348`, divided by Garman-Klass's efficiency
  (about 7.4) gives **0.67** - the value shipped;
* the estimator itself is chi-square with `2e = 14.8` degrees of freedom, so
  `Var(log GK) = trigamma(7.4)` gives **0.145**.

Both are delta-method arguments about a quantity nobody sampled, and the gap is
the whole band: a noise too large makes the filter slow and its band wide, a
noise too small makes it confident and wrong.

## Part A settles the constant where the truth is known

A driftless Gaussian walk at fixed sigma has a *constant* latent log variance,
so every wobble in `log GK` is measurement error and its variance is the number
wanted. It is also scale-free - `log(GK / sigma^2)` does not depend on sigma -
so one simulation answers it for every instrument, and the only thing it
depends on is how many ticks the bar was built from. That dependence is the
point rather than a nuisance: a bar's high and low come from finitely many
quotes, a coarser bar under-states the range, and the estimator's error grows
as the bar thins out. So Part A sweeps ticks per bar and reports the curve,
with the bias beside the variance - `log` of a noisy estimate is biased low,
and that bias lands on every published `log_variance` as a constant offset.

## Part B asks what it costs where the truth is not known

On real bars the latent log variance genuinely moves, so the operational
question is not "what is the estimator's sampling variance" but "which `R`
makes the published band hold its coverage". Too small and the filter chases
noise and breaches; too large and it is sluggish and over-wide. The sweep
scores each candidate three ways, one step ahead, against the **next** bar's
observation:

* breach rate of `Readout.covering(c)` against the coverage asked for, at
  0.90, 0.95 and 0.99 - the metric the band was built to serve;
* `Var(surprise)`, which is 1 exactly when the predictive spread is the right
  scale, and is the classic innovation test for `R`;
* CRPS from the published quantiles, which is proper and arm-free.

The **control is the Deriv volatility family**, whose generator holds sigma
fixed. There the latent state is constant, so Part B's pick must land on Part
A's measurement - and if it does not, this harness is measuring something other
than the noise and no reading on FX means anything.
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

from till_infinity.statespace.diagnostics import crps  # noqa: E402
from till_infinity.statespace.engine import dispersion  # noqa: E402
from till_infinity.statespace.facade import Desk  # noqa: E402

#: Ticks per bar in Part A. A broker's 1m bar is tens to hundreds of quote
#: updates and its 1h bar thousands, so the range brackets both ends.
TICKS = (12, 30, 60, 240, 1_440, 5_760)
PATHS = 40_000
SEED = 20261018

#: Garman-Klass's efficiency against close-to-close, as the literature quotes
#: it and as `spanning.py`'s docstring uses it.
EFFICIENCY = 7.4

#: The candidates, with both derivations inside the grid.
NOISES = (0.02, 0.05, 0.1, 0.145, 0.25, 0.4, 0.67, 1.0, 1.6, 2.5)
COVERS = (0.90, 0.95, 0.99)

FRAMES = ("5m", "15m", "1h")
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 4
LIMIT = 12_000
#: Bars folded before anything is scored. `Desk._quantiles` needs
#: `facade.LEAST` residuals before `covering` is measured rather than assumed.
WARM = 500


def trigamma(x: float, terms: int = 24) -> float:
    """`psi'(x)`, by recurrence onto the asymptotic series. No SciPy on the lab."""
    total = 0.0
    while x < terms:
        total += 1.0 / (x * x)
        x += 1.0
    # psi'(x) ~ 1/x + 1/(2x^2) + 1/(6x^3) - 1/(30x^5) + 1/(42x^7)
    inv = 1.0 / x
    return total + inv * (1 + inv * (0.5 + inv * (1 / 6 - inv * inv * (1 / 30 - inv * inv / 42))))


def _bars(rng: np.random.Generator, ticks: int, paths: int) -> tuple[np.ndarray, ...]:
    """OHLC in log price for `paths` bars of unit variance, built from `ticks` steps."""
    step = rng.normal(0.0, 1.0 / math.sqrt(ticks), size=(paths, ticks))
    walk = np.cumsum(step, axis=1)
    zero = np.zeros((paths, 1))
    full = np.hstack([zero, walk])
    return (
        np.zeros(paths),
        full.max(axis=1),
        full.min(axis=1),
        walk[:, -1],
    )


def _estimators(
    o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray
) -> dict[str, np.ndarray]:
    """The three estimators, in log price, as `spanning.py` computes them."""
    span, body = h - lo, c - o
    gk = np.maximum(0.5 * span * span - (2 * math.log(2) - 1) * body * body, 0.0)
    park = span * span / (4.0 * math.log(2.0))
    rs = (h - c) * (h - o) + (lo - c) * (lo - o)
    return {
        "garman_klass": gk,
        "parkinson": park,
        "rogers_satchell": np.maximum(rs, 0.0),
        # The positive control, and the reason any of these numbers can be
        # trusted: a close-to-close square is `sigma^2` times one chi-square
        # degree of freedom, so this column has a closed form the simulation
        # must reproduce - `Var = pi^2 / 2 = 4.9348` and
        # `bias = digamma(0.5) + log 2 = -1.2704` - with no tick-count
        # dependence at all, because it never looks inside the bar.
        "close_close": body * body,
    }


#: Bars per simulation block. `paths * ticks` floats at once, so the widest
#: row here is 4,000 x 5,760 x 8 bytes = 184MB rather than the 1.8GB a single
#: block would ask for - which is the difference between running on the lab
#: and being killed on it.
BLOCK = 4_000


def part_a() -> dict[str, float]:
    """The sampling variance of `log(estimate / truth)` where the truth is fixed."""
    print("## Part A: the sampling variance of a log range estimator, truth held fixed\n")
    print("Driftless Gaussian bars of unit variance, so `log(estimate)` is the error itself.")
    print(
        f"{PATHS:,} bars per row. `bias` lands on every published level; `var` is the R wanted.\n"
    )
    print(f"  pi^2/2 / efficiency = {math.pi**2 / 2 / EFFICIENCY:.4f}   (the shipped 0.67)")
    print(f"  trigamma(efficiency) = {trigamma(EFFICIENCY):.4f}   (the other derivation)")
    print(
        f"  close_close control  = {math.pi**2 / 2:.4f} var, "
        f"{-math.pi / 2 * 0 - 1.2704:.4f} bias   (closed form, must come back)\n"
    )
    head = f"{'ticks/bar':>10}" + "".join(
        f"{k:>28}" for k in ("garman_klass", "parkinson", "rogers_satchell", "close_close")
    )
    print(head)
    print(f"{'':>10}" + "".join(f"{'bias':>12}{'var':>8}{'zeros':>8}" for _ in range(4)))
    rng = np.random.default_rng(SEED)
    last: dict[str, float] = {}
    for ticks in TICKS:
        totals: dict[str, list[float]] = {}
        done = 0
        while done < PATHS:
            take = min(BLOCK, PATHS - done)
            done += take
            for name, est in _estimators(*_bars(rng, ticks, take)).items():
                good = est > 0
                err = np.log(est[good])
                sums = totals.setdefault(name, [0.0, 0.0, 0.0, 0.0])
                sums[0] += float(err.sum())
                sums[1] += float((err * err).sum())
                sums[2] += int(good.sum())
                sums[3] += int((~good).sum())
        row = f"{ticks:>10,}"
        for name in ("garman_klass", "parkinson", "rogers_satchell", "close_close"):
            total, square, n, zeros = totals[name]
            mean = total / n
            var = square / n - mean * mean
            row += f"{mean:>12.4f}{var:>8.4f}{zeros / (n + zeros):>8.3f}"
            last[name] = float(var)
        print(row, flush=True)
    print(
        "\nThe variance is the measurement noise `R` for this observation, and it is"
        "\nread off the row whose tick count matches the interval being folded."
    )
    return last


def _score(bars: dict, frame: str, feed: str, noise: float) -> dict[str, float]:
    """One pass of the service's own path at one candidate noise."""
    desk = Desk()
    when = bars["time"]
    o, h, lo, c = bars["open"], bars["high"], bars["low"], bars["close"]
    breaches = dict.fromkeys(COVERS, 0)
    sources: dict[str, int] = {}
    seen = 0
    scored = 0
    total_crps = 0.0
    zs: list[float] = []
    prev = None
    for i in range(len(c)):
        value = dispersion(float(o[i]), float(h[i]), float(lo[i]), float(c[i]))
        if value is None:
            continue
        seen += 1
        if prev is not None and seen > WARM:
            scored += 1
            for cover in COVERS:
                band = prev.covering(cover)
                if not band.low <= value <= band.high:
                    breaches[cover] += 1
                if cover == COVERS[0]:
                    sources[band.source] = sources.get(band.source, 0) + 1
            if prev.quantiles:
                total_crps += crps(prev.quantiles, value)
        got = desk.read(feed, frame, float(when[i]), value, noise)
        if seen > WARM:
            zs.append(got.surprise)
        prev = got
    if scored < 1_000:
        return {}
    out = {f"breach_{int(100 * cover)}": breaches[cover] / scored for cover in COVERS}
    out["zvar"] = float(np.var(zs)) if zs else float("nan")
    out["crps"] = total_crps / scored
    out["n"] = float(scored)
    out["measured"] = sources.get("measured", 0) / max(scored, 1)
    return out


def part_b() -> None:
    """Which candidate holds its coverage on real bars, by class and interval."""
    print("\n\n## Part B: which R holds the band's coverage, one step ahead on real bars\n")
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = {k: v[:PER_CLASS] for k, v in groups.items() if k in TRADED + CONTROLS}
    print("classes:", ", ".join(f"{k} ({len(v)})" for k, v in sorted(wanted.items())), flush=True)

    for frame in FRAMES:
        rows: dict[tuple[str, float], list[dict[str, float]]] = {}
        for klass, names in sorted(wanted.items()):
            for name in names:
                bars = load(name, frame)
                if bars is None:
                    continue
                bars = {k: v[-LIMIT:] for k, v in bars.items()}
                for noise in NOISES:
                    got = _score(bars, frame, name, noise)
                    if got:
                        rows.setdefault((klass, noise), []).append(got)
        if not rows:
            print(f"\n=== {frame}: nothing loaded", flush=True)
            continue
        for klass in sorted({k for k, _ in rows}):
            print(f"\n=== {frame}, {klass}")
            print(
                f"{'R':>8}{'n':>9}{'breach .90':>12}{'breach .95':>12}{'breach .99':>12}"
                f"{'x .95':>8}{'var z':>9}{'CRPS':>9}{'measured':>10}"
            )
            best = (float("inf"), 0.0)
            for noise in NOISES:
                got = rows.get((klass, noise))
                if not got:
                    continue
                take = lambda key: float(np.median([g[key] for g in got]))  # noqa: E731
                ratio = take("breach_95") / 0.05
                score = take("crps")
                best = min(best, (score, noise))
                print(
                    f"{noise:>8.3f}{int(sum(g['n'] for g in got)):>9,}"
                    f"{take('breach_90'):>12.4f}{take('breach_95'):>12.4f}{take('breach_99'):>12.4f}"
                    f"{ratio:>8.2f}{take('zvar'):>9.3f}{score:>9.4f}{take('measured'):>10.2f}",
                    flush=True,
                )
            print(f"  lowest CRPS at R = {best[1]:g}")


def main() -> None:
    print(
        "What measurement variance belongs on log(garman_klass)?\n"
        "Part A measures it where the latent variance is constant by construction.\n"
        "Part B asks which candidate holds the published band's coverage on real\n"
        "bars, one step ahead, with the constant-sigma family as the control.\n",
        flush=True,
    )
    measured = part_a()
    part_b()
    print(
        "\n\n## Read it in this order\n"
        f"Part A's garman_klass variance at the matching tick count ({measured.get('garman_klass', float('nan')):.4f}\n"
        "at the densest row here) is the physical constant. Part B's control class\n"
        "has a constant latent sigma, so its lowest-CRPS R must agree with it. Only\n"
        "then does the traded classes' pick mean anything - and where they differ\n"
        "from the control, the difference is latent movement the filter must absorb,\n"
        "which is a `Q` statement rather than an `R` one.",
        flush=True,
    )


if __name__ == "__main__":
    main()
