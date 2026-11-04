"""Does the adverse excursion grow as the square root of the horizon?

Runs `research/docs/excursion-scaling-prereg.md`. Read the pre-registration
first; this file does not restate the claim or the pass rule.

**The excursion itself is `stop_coverage.excursions`, unchanged.** That is the
point rather than convenience: `stop-coverage.md` is the study this one is an
increment on, and the two numbers have to be the same quantity or the claim
"the exponent is not 0.5" is a claim about two different definitions. The null
arms come from `level_shield.py` for the same reason.

## What is fitted

For each (feed, side), the `TAU` quantile of the adverse excursion at each
horizon, then `log q(H) = k log H + c` by least squares. `k` is the exponent;
a driftless walk gives **exactly 0.5** by the reflection principle, which is
where `sqrt(H)` in `stop_coverage.py` comes from.

Windows are **non-overlapping** - stride `H` - because overlapping ones share
`H - 1` bars and `overlapping-windows-inflate-permutation-nulls` records a
level finding at p 0.015 that turned out to be anchor overlap.

## Why `bar-shuffle` is both the null and the control

Shuffling bars destroys serial dependence while keeping the marginal
distribution, so it **must** return `k = 0.5`. An estimator that reads 0.47 on
shuffled real bars is reporting its own bias, and every real reading inherits
that bias. So the arm is checked in that direction before any real cell is
read, which is cheaper than discovering it afterwards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

import research.ideas.level_shield as shield
import research.ideas.stop_coverage as cover

#: Horizons the exponent is fitted over, in bars. Seven points spanning two
#: decades of horizon: a line through fewer is a slope with no residual to look
#: at, and the pre-registration's own table runs to 96.
HORIZONS: tuple[int, ...] = (1, 2, 5, 10, 20, 48, 96)

#: The quantile the stop claims. `stop_coverage.TAU`, so the two studies are
#: calibrating the same thing.
TAU = cover.TAU

#: Draws per null arm. Sixteen: `fear-greed.md` measured a hardest-of-N test at
#: four draws reading +0.093 where sixteen read -0.037.
DRAWS = 16

ARMS: tuple[str, ...] = ("bar-shuffle", "walk-geometry", "garch-bars")

#: Two Deriv volatility indices, carried in every cell.
#: `the-placebo-arm-selects-the-null` rejects any null a placebo passes.
PLACEBO: tuple[str, ...] = ("nzdusd", "usdcad")

#: Generated controls. Both **must** return 0.5: the exponent is a property of
#: the dependence, not of the marginal, so fat tails must not move it. If they
#: do, the estimator is reading kurtosis.
CONTROLS: tuple[str, ...] = ("gen_walk", "gen_fat")

FEEDS: tuple[str, ...] = (
    "eurusd",
    "gbpusd",
    "audusd",
    "usdcad",
    "usdchf",
    "usdjpy",
    "usdcnh",
    "nzdusd",
    "gold",
)

#: The coverage spread `t-sqrt-h` leaves, measured in `stop-coverage.md`:
#: 0.133 at H=1 rising to 0.170 at H=48. Criterion 4 asks for less than this.
SQRT_SPREAD = 0.037


def seed_for(*parts: object) -> int:
    """A seed stable across processes.

    `hash()` of a tuple containing a string is salted per process, so a
    surrogate seeded with one is not reproducible and two workers draw
    different arms for the same cell. Four harnesses here had that defect.
    """
    text = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


@dataclass(frozen=True, slots=True)
class Fit:
    """One (feed, side) exponent, and what it was fitted on."""

    feed: str
    venue: str
    interval: str
    arm: str
    draw: int
    side: int
    half: str
    #: The fitted exponent. A walk gives 0.5.
    k: float
    #: Intercept, which is the one-bar quantile in logs.
    c: float
    #: Mean absolute residual of the fit in logs. A large one means the single
    #: power law is the wrong shape and `k` is an average of two regimes.
    residual: float
    #: Quantiles actually fitted, and how many windows each rested on.
    points: int
    fewest: int
    #: Coverage spread across horizons under each rule, `max - min`.
    spread_sqrt: float
    spread_fitted: float
    #: The fitted points themselves, `"H:q"` joined. **Reported because the
    #: slope alone cannot be diagnosed.** The generated walk read k = 0.41
    #: where it must read 0.5, and no amount of looking at the slope says
    #: which horizon is out of line; the curve does.
    curve: str
    #: Coverage spread on the **second** half, under an exponent fitted on the
    #: **first**. This is criterion 4 done honestly.
    #:
    #: The in-sample version fits `k` and scores it on the same windows, and
    #: the first panel read a near-halving of the drift that way - gbpusd 0.084
    #: to 0.036 - while `k` itself was indistinguishable from 0.5 inside its
    #: own surrogate spread. A parameter that improves calibration in sample
    #: and cannot be told from the null is `fit-on-the-edge-not-the-raw-score`
    #: waiting to happen, so the split is the number that decides it.
    spread_out_sqrt: float
    spread_out_fitted: float
    #: The slope refitted with the one-bar point dropped. `stop-coverage.md`
    #: records H = 1 as a known special case - a bar observed only at its own
    #: extremes measures `Phi(-a)` where a continuous path gives `2 Phi(-a)` -
    #: so it is the point most likely to be the wrong shape, and the pair says
    #: whether the exponent depends on it.
    k_no_one: float

    @property
    def deviation(self) -> float:
        return abs(self.k - 0.5)


#: Bars in a generated control. **200,000 and not 6,000, and the reason is a
#: measurement.** At 6,000 bars H = 96 leaves 62 non-overlapping windows, and a
#: 0.90 quantile off 62 draws is mostly its own sampling error: the walk's
#: fitted curve came out **non-monotone** - `5:5.3398` then `10:5.2423`, a
#: quantile falling as the horizon doubled, which no excursion distribution
#: does - and the exponent read 0.396 where it must read 0.5.
#:
#: A control that cannot resolve the value it exists to confirm validates
#: nothing, and length is free in a generator. 200,000 bars gives 2,083 windows
#: at the longest horizon.
CONTROL_BARS = 200_000


#: Path steps inside one bar. The bar's high and low are the **true running
#: extremes of those steps**, which is what makes the control a control.
TICKS_PER_BAR = 20


def generated(feed: str, n: int = CONTROL_BARS) -> shield.Series:
    """A walk whose excursion exponent is known to be 0.5.

    `gen_walk` is Gaussian; `gen_fat` has Student-t innovations at the same
    variance. **Both must read 0.5**, because the exponent is a property of the
    dependence and these have none - so a reading that moves between them is
    the estimator responding to kurtosis.

    **The bars are aggregated from a finer path, not decorated with a wick.**
    The first version set `high = max(open, close) + |N(0,1)| * sigma`, an
    independent wick, and that is not a walk observed at bar resolution - it is
    a walk plus noise. The extra term inflates the one-bar excursion far more
    than the ninety-six-bar one, so `q(H) / sqrt(H)` fell smoothly from 2.39 to
    1.76 across the range and the fitted exponent read **0.424 to 0.446 where
    it must read 0.5**, on a clean monotone curve off 2,081 windows.

    That is `a-control-is-only-for-a-named-property` exactly: the control was
    built to isolate the scaling and its bar geometry smuggled in a second
    effect. Aggregating twenty path steps a bar makes the high and the low the
    path's own extremes, which is what a venue's bar is.

    Priced at 1,000 rather than 1.0: `a-synthetic-at-price-one-hides-scale-
    bugs` records relative sd and price offset coinciding at unity.
    """
    rng = np.random.default_rng(seed_for("control", feed))
    sigma = 0.004 / math.sqrt(TICKS_PER_BAR)
    total = n * TICKS_PER_BAR
    if feed == "gen_fat":
        dof = 4.0
        raw = rng.standard_t(dof, size=total)
        steps = raw / math.sqrt(dof / (dof - 2.0)) * sigma
    else:
        steps = rng.standard_normal(total) * sigma

    path = 1000.0 * np.exp(np.cumsum(steps))
    grid = path.reshape(n, TICKS_PER_BAR)
    return shield.Series(
        feed=feed,
        venue="GENERATED",
        interval="1d",
        ts=np.arange(n, dtype=float) * 86_400.0,
        open=grid[:, 0],
        high=grid.max(axis=1),
        low=grid.min(axis=1),
        close=grid[:, -1],
    )


def quantiles(series: shield.Series, sigma: np.ndarray, side: int, *, part: str = "all"):
    """`{H: (quantile, windows)}` over `HORIZONS`, non-overlapping.

    `part` takes the first or second half of the anchors, for the era check the
    pre-registration asks for: an exponent is supposed to be a property of the
    process, so it should survive being fitted on one half.
    """
    # **Every horizon is read off the same number of windows.**
    #
    # The window count falls as `1 / H`, and the empirical `TAU` quantile of a
    # small sample is biased **downward** - the 90th percentile of 60 draws
    # understates the true one more than the 90th of 6,000 does. So the bias
    # grows with the horizon, which tilts the fitted slope down, and it is not
    # a small effect: before this, a **Gaussian walk read k = 0.409 and 0.419
    # where it must read 0.5**, and a fat-tailed walk 0.428 and 0.457. The
    # control caught it before any real cell was read, which is what it is for.
    #
    # Equalised by subsampling evenly **across the span** rather than taking
    # the first `m`: the first 60 windows at H=1 are sixty bars of one era
    # while at H=96 they are the whole history, so truncating would trade a
    # quantile bias for a calendar one.
    raw: dict[int, np.ndarray] = {}
    for horizon in HORIZONS:
        found = cover.excursions(series, sigma, horizon, step=horizon)
        values = found.side(side)
        if part != "all" and len(values) >= 8:
            middle = len(values) // 2
            values = values[:middle] if part == "A" else values[middle:]
        values = values[np.isfinite(values)]
        # Twelve: a quantile at TAU 0.90 off fewer is the largest of a handful
        # and moves by its own sampling rather than by the horizon.
        if len(values) >= 12:
            raw[horizon] = values
    if not raw:
        return {}
    fewest = min(len(v) for v in raw.values())

    out: dict[int, tuple[float, int]] = {}
    for horizon, found in raw.items():
        values = found
        if len(found) > fewest:
            picked = np.linspace(0, len(found) - 1, fewest).round().astype(int)
            values = found[np.unique(picked)]
        out[horizon] = (float(np.quantile(values, TAU)), len(values))
    return out


def fit_exponent(points: dict[int, tuple[float, int]]) -> tuple[float, float, float]:
    """`(k, c, mean |residual|)` from `log q = k log H + c`.

    Least squares in logs, which is the right space: the claim is a power law,
    and fitting it in levels would weight the long horizons by their size
    rather than by their information.
    """
    if len(points) < 3:
        return float("nan"), float("nan"), float("nan")
    xs = np.log(np.array(sorted(points), dtype=float))
    ys = np.log(np.array([points[h][0] for h in sorted(points)], dtype=float))
    if not np.all(np.isfinite(ys)):
        return float("nan"), float("nan"), float("nan")
    k, c = np.polyfit(xs, ys, 1)
    residual = float(np.mean(np.abs(ys - (k * xs + c))))
    return float(k), float(c), residual


def coverage_spread(
    series: shield.Series,
    sigma: np.ndarray,
    side: int,
    *,
    exponent: float,
    one_bar: float,
    part: str = "all",
) -> float:
    """`max - min` of realised stop-out rate across horizons under `H^exponent`.

    **This is criterion 4 and the only number that decides whether a different
    exponent is a better stop.** An exponent that differs from 0.5 and does not
    flatten this is a fact about the series rather than an improvement, and
    `fit-on-the-edge-not-the-raw-score` is why it is scored here rather than on
    the fit: fitted weights once won on AUC 0.604 against 0.556 and **lost on
    edge, +0.002 against +0.019**.
    """
    rates: list[float] = []
    for horizon in HORIZONS:
        found = cover.excursions(series, sigma, horizon, step=horizon)
        values = found.side(side)
        if part != "all" and len(values) >= 8:
            middle = len(values) // 2
            values = values[:middle] if part == "A" else values[middle:]
        values = values[np.isfinite(values)]
        if len(values) < 12:
            continue
        stop = one_bar * (horizon**exponent)
        rates.append(float(np.mean(values >= stop)))
    return (max(rates) - min(rates)) if len(rates) >= 3 else float("nan")


def measure(series: shield.Series, arm: str, draw: int) -> list[Fit]:
    """Both sides, three halves (whole, A, B), for one series."""
    sigma = cover.sigma_close(series)
    out: list[Fit] = []
    for side in (1, -1):
        for half in ("all", "A", "B"):
            points = quantiles(series, sigma, side, part=half)
            k, c, residual = fit_exponent(points)
            if math.isnan(k):
                continue
            one_bar = points.get(1, (math.exp(c), 0))[0] if 1 in points else math.exp(c)
            spread_sqrt = (
                coverage_spread(series, sigma, side, exponent=0.5, one_bar=one_bar)
                if half == "all"
                else float("nan")
            )
            spread_fit = (
                coverage_spread(series, sigma, side, exponent=k, one_bar=one_bar)
                if half == "all"
                else float("nan")
            )
            without = {h: v for h, v in points.items() if h != 1}
            k_no_one, _, _ = fit_exponent(without)
            # Fit on A, score on B. `half == "all"` carries it because that
            # is the row the verdict reads; the A and B rows keep their own
            # in-sample fits for the era check.
            out_sqrt = out_fit = float("nan")
            if half == "all":
                first = quantiles(series, sigma, side, part="A")
                k_a, _, _ = fit_exponent(first)
                if not math.isnan(k_a):
                    anchors_b = quantiles(series, sigma, side, part="B")
                    base_b = anchors_b.get(1, (math.exp(c), 0))[0]
                    out_sqrt = coverage_spread(
                        series, sigma, side, exponent=0.5, one_bar=base_b, part="B"
                    )
                    out_fit = coverage_spread(
                        series, sigma, side, exponent=k_a, one_bar=base_b, part="B"
                    )
            out.append(
                Fit(
                    feed=series.feed,
                    venue=series.venue,
                    interval=series.interval,
                    arm=arm,
                    draw=draw,
                    side=side,
                    half=half,
                    k=k,
                    c=c,
                    residual=residual,
                    points=len(points),
                    fewest=min((int(n) for _, n in points.values()), default=0),
                    spread_sqrt=spread_sqrt,
                    spread_fitted=spread_fit,
                    spread_out_sqrt=out_sqrt,
                    spread_out_fitted=out_fit,
                    curve=" ".join(f"{h}:{points[h][0]:.4f}" for h in sorted(points)),
                    k_no_one=k_no_one,
                )
            )
    return out


def surrogate(name: str, series: shield.Series, rng: random.Random, fitted):
    """One arm, dispatched by name.

    A function rather than a dict of lambdas: a lambda built inside the draw
    loop closes over that loop's `rng`, and the same shape in
    `anchored_states_run.py` was a closure `ProcessPoolExecutor` could not
    pickle at all. Dispatching by name has neither problem and an unknown arm
    raises instead of falling through.
    """
    if name == "bar-shuffle":
        return shield.bar_shuffle(series, rng)
    if name == "walk-geometry":
        return shield.walk_geometry(series, rng)
    if name == "garch-bars":
        return shield.garch_bars(series, rng, fitted)
    raise ValueError(f"{name!r} is in ARMS and has no branch here")


def job(args: tuple) -> list[dict]:
    feed, interval, store, draws = args
    rows: list[dict] = []
    try:
        if feed in CONTROLS:
            series = generated(feed)
        else:
            con = sqlite3.connect(store, uri=True)
            series = cover.load(con, feed, interval)
            con.close()
        if series is None:
            return [{"kind": "error", "feed": feed, "interval": interval, "error": "no series"}]

        rows.extend({"kind": "fit", **asdict(f)} for f in measure(series, "real", 0))

        fitted = None
        try:
            fitted = shield.fit_garch(np.diff(np.log(series.close)))
        except Exception as exc:
            rows.append(
                {
                    "kind": "note",
                    "feed": feed,
                    "note": f"garch unfitted: {exc!r}"[:160],
                }
            )

        for name in ARMS:
            for draw in range(draws):
                rng = random.Random(seed_for(feed, interval, name, draw))
                made = surrogate(name, series, rng, fitted)
                rows.extend({"kind": "fit", **asdict(f)} for f in measure(made, name, draw))
    except Exception as exc:
        import traceback

        rows.append(
            {
                "kind": "error",
                "feed": feed,
                "interval": interval,
                "error": repr(exc),
                "where": traceback.format_exc(limit=4).splitlines()[-3:],
            }
        )
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--store", default=cover.STORE)
    ap.add_argument("--draws", type=int, default=DRAWS)
    ap.add_argument("--feeds", default="")
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--controls", action="store_true", help="add the two generated walks")
    args = ap.parse_args(argv)

    feeds = tuple((args.feeds or " ".join(FEEDS)).replace(",", " ").split())
    if args.controls:
        feeds = feeds + CONTROLS

    where = Path(args.out)
    where.mkdir(parents=True, exist_ok=True)
    sink = where / "fits.jsonl"

    jobs = [(feed, args.interval, args.store, args.draws) for feed in feeds]
    print(
        f"{len(jobs)} jobs, {args.draws} draws an arm, horizons {HORIZONS}, "
        f"{args.workers} workers -> {sink}",
        file=sys.stderr,
    )
    started = time.time()
    done = 0
    with sink.open("w") as fh:
        if args.workers <= 1:
            streams = (job(one) for one in jobs)
        else:
            from concurrent.futures import ProcessPoolExecutor

            streams = ProcessPoolExecutor(max_workers=args.workers).map(job, jobs)
        for rows in streams:
            done += 1
            for row in rows:
                fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(f"  {done}/{len(jobs)} {time.time() - started:.0f}s", file=sys.stderr, flush=True)
    print(f"wrote {sink}")


if __name__ == "__main__":
    main()
