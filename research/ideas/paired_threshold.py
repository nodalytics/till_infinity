"""What `Paired`'s threshold costs in false alarms, and buys in delay.

`learning/focus.py` sets `THRESHOLD = 12.0` and says so plainly:

> The statistic is a log likelihood ratio, so a threshold is "how many nats of
> evidence before this is worth saying". **Chosen to be conservative rather
> than fitted**: `drift.py` records that a false alarm discounts real
> evidence.

`statespace-stat-arb-and-volume.md` lists the missing measurement as a debt:
"`Paired`'s threshold is still uncalibrated against a stationary stream, which
`focus.py` names as the right measurement and skips."

This is that measurement, and it needs **both halves**. A threshold is a
trade-off, and a note reporting only the false-alarm rate would let someone
pick a very high one and think they had improved something.

## The two numbers a changepoint threshold has

* **ARL-zero**, the average run length to a false alarm on a stream with no
  change in it. This is what the desk is buying: "one spurious alarm every so
  many bars".
* **ARL-one**, the average delay before a *real* change of a given size is
  detected. This is what the desk is paying.

Both are in observations, and an observation here is one bar, so they convert
to time by the bar length. A threshold with an ARL-zero of 2,000 on 1h bars
false-alarms about once every twelve weeks.

## The stream is standard normal, and that is not an assumption

`Paired` feeds the detector `last_standardised` - the innovation divided by its
own predictive spread - so **under a correctly specified member that series is
standard normal by construction**. Which makes an i.i.d. N(0,1) stream the
exactly right stationary null rather than a convenient one, and it is why this
calibration transfers to every member rather than needing redoing per member.

The one caveat is in that sentence: *correctly specified*. The members here are
not - `statespace-backtest.md` measures `kalman`'s residual autocorrelation at
-0.45 - so a real member's innovations are **not** i.i.d. normal and its true
false-alarm rate will be worse than this table. So the table is a **floor** on
the false-alarm interval, and the second arm measures how far a real member's
residuals move it.

## Two detectors, not one

`Paired` runs an up instance and a down instance, because "moves got bigger"
and "moves got smaller" are different events. Two detectors watching the same
stream alarm about twice as often as one, so the pair's ARL-zero is roughly
half each instance's, and that factor is reported rather than left for the
reader to remember.

Runs anywhere - it is generated data.
"""

from __future__ import annotations

import itertools
import math
import os
import random
import statistics

#: Thresholds in nats. The shipped default is 12.0 and sits in the middle, so
#: the table says what it bought rather than only what the alternatives cost.
THRESHOLDS = (4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 20.0, 25.0)

#: Change sizes for the delay arm, in standard deviations of the stream. A
#: half-sigma shift in the mean of the standardised innovations is a member
#: that has drifted; two sigma is one that has broken.
SHIFTS = (0.25, 0.5, 1.0, 2.0)

#: Runs per cell, and the cap on a single run's length. The cap matters: a
#: high threshold on a stationary stream may never alarm, and a mean taken
#: over only the runs that finished would be biased down badly.
RUNS = int(os.environ.get("RUNS", "400"))
CAP = int(os.environ.get("CAP", "200000"))

SEED = 20261012


def run_length(threshold: float, *, shift: float, seed: int, up: bool) -> tuple[int, bool]:
    """Observations until the detector alarms, and whether it did.

    Returns the cap and `False` when it did not, so the caller can report a
    censored mean rather than silently dropping the runs that never fired -
    which is the bias this arm exists to avoid.
    """
    from till_infinity.structures.learning.focus import Focus

    rng = random.Random(seed)
    detector = Focus(threshold=threshold, up=up, scale=1.0)
    for step in range(1, CAP + 1):
        if detector.update(rng.gauss(shift, 1.0)):
            return step, True
    return CAP, False


def _one(job: tuple[float, float, int, bool]) -> tuple[int, bool]:
    threshold, shift, seed, up = job
    return run_length(threshold, shift=shift, seed=seed, up=up)


def arl(threshold: float, *, shift: float, runs: int, up: bool, pool=None) -> dict:
    """Average run length, with the censoring made visible.

    **Parallel, because the stationary arm is expensive.** One run at the
    shipped threshold of 12 nats takes about sixty thousand observations and
    three seconds, so the nine thresholds at four hundred runs each would be
    three hours serially. The lab has sixty-four cores and this is embarrassingly
    parallel, so it uses them - a thin sample would have given an average run
    length with a standard error of a third, which is not a calibration.
    """
    jobs = [
        (threshold, shift, SEED + index * 7919 + int(threshold * 13), up) for index in range(runs)
    ]
    got = list(pool.map(_one, jobs)) if pool is not None else [_one(j) for j in jobs]
    lengths = [length for length, _hit in got]
    fired = sum(1 for _length, hit in got if hit)
    share = fired / runs
    # **The censored cells need an estimate, not a capped mean.** At the
    # shipped threshold 40% of runs reach the cap without alarming and at 20
    # nats none of them alarm, so the raw mean is bounded by the cap and
    # reports 200,000 for anything above it.
    #
    # A CUSUM-type run length on a stationary stream is close to exponential,
    # so the fraction that fired by the cap gives the mean directly:
    # `P(fire by C) = 1 - exp(-C/mean)`, hence `mean = -C / ln(1 - p)`. The
    # assumption is **checked rather than assumed** - `ratio` below is
    # median/mean, which an exponential puts at ln 2 = 0.693, and the
    # uncensored cells come in at 0.68 to 0.73.
    if share >= 1.0:
        fitted = statistics.fmean(lengths)
    elif share <= 0.0:
        fitted = float("inf")
    else:
        fitted = -CAP / math.log(1.0 - share)
    mean = statistics.fmean(lengths)
    return {
        "mean": mean,
        "median": statistics.median(lengths),
        "fitted": fitted,
        "ratio": statistics.median(lengths) / mean if mean > 0 else float("nan"),
        "fired": share,
        "censored": 1.0 - share,
    }


def main() -> None:
    from concurrent.futures import ProcessPoolExecutor

    workers = min(os.cpu_count() or 4, 48)
    print(
        f"runs {RUNS}  cap {CAP}  workers {workers}\n"
        "ARL-zero: observations to a false alarm on a stationary N(0,1) stream.\n"
        "ARL-one: observations to detect a real shift of that many sigmas.\n"
        "An observation is one bar, so divide by 24 for days at 1h.\n"
    )

    with ProcessPoolExecutor(max_workers=workers) as pool:
        print(
            f"{'threshold':>10}{'capped':>10}{'fitted ARL-0':>14}{'med/mean':>10}"
            f"{'censored':>10}{'days at 1h':>12}{'pair, days':>12}"
        )
        quiet = {}
        for threshold in THRESHOLDS:
            got = arl(threshold, shift=0.0, runs=RUNS, up=True, pool=pool)
            quiet[threshold] = got
            mark = " <- shipped" if threshold == 12.0 else ""
            shown = (
                f"{got['fitted']:>14.0f}"
                if math.isfinite(got["fitted"])
                else f"{'> ' + str(CAP):>14}"
            )
            days = got["fitted"] / 24.0 if math.isfinite(got["fitted"]) else float("inf")
            print(
                f"{threshold:>10.1f}{got['mean']:>10.0f}{shown}"
                f"{got['ratio']:>10.2f}{got['censored']:>10.2f}"
                + (
                    f"{days:>12.0f}{days / 2.0:>12.0f}"
                    if math.isfinite(days)
                    else f"{'-':>12}{'-':>12}"
                )
                + mark
            )

        print(
            "\n   The last column halves the interval, because `Paired` runs an\n"
            "   up instance and a down instance on the same stream and either\n"
            "   can alarm. `med/mean` checks the exponential assumption the\n"
            "   fitted column rests on: 0.693 is what an exponential gives."
        )

        print("\n== ARL-one: observations to detect a real shift")
        print(f"{'threshold':>10}" + "".join(f"{str(s) + ' sigma':>12}" for s in SHIFTS))
        for threshold in THRESHOLDS:
            row = []
            for shift in SHIFTS:
                got = arl(threshold, shift=shift, runs=RUNS, up=True, pool=pool)
                row.append(got["mean"])
            mark = " <- shipped" if threshold == 12.0 else ""
            print(f"{threshold:>10.1f}" + "".join(f"{v:>12.1f}" for v in row) + mark)

    print(
        "\n== reading the pair together\n"
        f"{'threshold':>10}{'false alarm':>14}{'delay at 1 sigma':>18}{'ratio':>10}"
    )
    for threshold in THRESHOLDS:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            fast = arl(threshold, shift=1.0, runs=RUNS, up=True, pool=pool)
        slow = quiet[threshold]["fitted"]
        if not math.isfinite(slow):
            print(f"{threshold:>10.1f}{'> ' + str(CAP):>14}{fast['mean']:>18.1f}{'-':>10}")
            continue
        print(
            f"{threshold:>10.1f}{slow:>14.0f}{fast['mean']:>18.1f}"
            f"{slow / max(fast['mean'], 1e-9):>10.0f}"
        )
    print(
        "\n   The ratio is how many bars of quiet the detector buys per bar of\n"
        "   delay, which is the quantity a threshold actually trades. A higher\n"
        "   ratio is a better detector rather than a more or less cautious one."
    )
    _real()


def _real() -> None:
    print("\n== and on a real member's innovations, which are not i.i.d. normal")
    print(
        f"{'series':<14}{'n':>7}{'lag-1':>8}{'sd':>6}"
        + "".join(f"{t:>10.0f}" for t in THRESHOLDS[:6])
    )
    rows = []
    for name, frame in (
        ("EURUSD", "1h"),
        ("XAUUSD", "1h"),
        ("BTCUSD", "1h"),
        ("Volatility_75_Index", "1h"),
    ):
        got = real_rate(name, frame)
        if got is None:
            continue
        rows.append(got)
        for tag in ("as_is", "rescaled", "trailing"):
            shown = f"{name[:13]:<14}" if tag == "as_is" else f"{'  ' + tag:<14}"
            print(
                f"{shown}{got['n']:>7}{got['lag1']:>8.3f}{got['sd']:>6.2f}"
                + "".join(
                    f"{got[(tag, t)]:>10.0f}" if math.isfinite(got[(tag, t)]) else f"{'none':>10}"
                    for t in THRESHOLDS[:6]
                )
            )
    print(
        "\n   Observations per alarm on a real series, against the i.i.d. floor\n"
        "   of 170, 894, 5122, 36997, 216788 and 1898244 for the same\n"
        "   thresholds. A real member's residuals carry autocorrelation, so a\n"
        "   CUSUM on them wanders further than on an independent stream and\n"
        "   alarms sooner - but that is not the main effect. The `sd` column\n"
        "   is: these residuals have a standard deviation of 0.71, not 1.0, so\n"
        "   the member's predictive spread is about forty percent too wide and\n"
        "   a detector told `scale=1.0` is measuring in the wrong units. The\n"
        "   `rescaled` row divides by a constant and makes it worse; the\n"
        "   `trailing` row divides by a causal trailing spread, which is what\n"
        "   `focus.update`'s own `scale` argument exists for."
    )


def real_rate(name: str, frame: str, thresholds=THRESHOLDS) -> dict | None:
    """The alarm rate on a **real member's** innovations, against the i.i.d. floor.

    **This is what makes the table above usable rather than decorative.** The
    calibration assumes the stream is i.i.d. standard normal, which it is only
    under a correctly specified member - and `statespace-backtest.md` measures
    `kalman`'s residual autocorrelation at -0.45 and the walk's at -0.013. A
    stream with autocorrelation wanders further than an independent one, so a
    CUSUM on it alarms sooner, and the i.i.d. numbers are a **floor** on the
    false-alarm interval rather than an estimate of it.

    The question is how far off. If a real member alarms ten times as often as
    the table says, the table is a curiosity; if twice, it is a calibration
    with a stated correction.
    """
    from pathlib import Path

    import numpy as np

    from till_infinity.structures.learning.focus import Focus
    from till_infinity.structures.statespace.nulls import Walk

    for base in (
        Path.home() / "till_infinity" / "data" / "seqlab",
        Path("data/seqlab"),
    ):
        path = base / f"{name}.{frame}.npz"
        if not path.exists():
            continue
        with np.load(path) as bundle:
            if not {"time", "close"} <= set(bundle.keys()):
                continue
            order = np.argsort(bundle["time"])
            times = np.asarray(bundle["time"], dtype=float)[order].tolist()
            closes = np.asarray(bundle["close"], dtype=float)[order].tolist()
        break
    else:
        return None
    if len(times) < 5000:
        return None

    values = [math.log(c) for c in closes if c > 0]
    if len(values) != len(times):
        return None
    steps = [b - a for a, b in itertools.pairwise(values)]
    spread = statistics.pstdev(steps) or 1e-12

    # The walk, because it is the best-calibrated member measured so far - its
    # residual autocorrelation is -0.013 against kalman's -0.45 - so this is
    # the **most favourable** real case and still an upper bound on how well
    # the i.i.d. table transfers.
    member = Walk(noise=spread)
    residuals = []
    for when, value in zip(times, values, strict=True):
        member.predict(when)
        member.update(value, spread * spread, when)
        if member.seen > 10:
            residuals.append(member.last_standardised)

    sd = statistics.pstdev(residuals) or 1.0
    out = {
        "name": name,
        "frame": frame,
        "n": len(residuals),
        "lag1": _lag_one(residuals),
        "sd": sd,
    }
    # Two arms. The first feeds the detector `scale=1.0`, which is what
    # `Paired` does, on the grounds that a standardised innovation is already
    # unit variance. The second feeds the residuals' **own measured** scale.
    #
    # The difference is the whole repair. A standardised innovation is unit
    # variance only under a correctly specified member, and these come in at
    # 0.71 - the member's predictive spread is about forty percent too wide,
    # which is the same fact as the walk over-covering at one sigma in
    # `statespace-backtest.md`. A CUSUM told the scale is 1.0 when it is 0.71
    # is measuring in the wrong units.
    #
    # **Rescaling by a constant turned out to make it worse**, which is the
    # measurement correcting the guess: dividing by 0.71 scales every residual
    # up by 1.41 and the CUSUM crosses sooner. The under-dispersion was
    # protecting the detector.
    #
    # The third arm is the one `focus.py` itself asks for. Its `update` takes
    # a `scale` per observation and says why: "volatility moves and a detector
    # calibrated to last week's is measuring the wrong thing this week". So
    # `trailing` divides each residual by a **trailing** spread of the last
    # 240 of them, which is the repair the module anticipated and `Paired`
    # does not use.
    for threshold in thresholds:
        for tag, stream in (
            ("as_is", residuals),
            ("rescaled", [v / sd for v in residuals]),
            ("trailing", _trailing(residuals, 240)),
        ):
            alarms = 0
            detector = Focus(threshold=threshold, up=True, scale=1.0)
            for value in stream:
                if detector.update(value):
                    alarms += 1
                    detector.reset()
            out[(tag, threshold)] = len(residuals) / alarms if alarms else float("inf")
    return out


def _trailing(values: list[float], span: int) -> list[float]:
    """Each residual over a trailing spread of the preceding `span` of them.

    Causal: the spread at `i` uses only values before `i`, so this is a stream
    a live detector could be fed.
    """
    # Incremental, because the obvious version recomputes a `pstdev` over a
    # 240-wide window per point and that is `O(n * span)` - twelve million
    # operations per instrument here, which dominated the whole harness.
    # Running sums give the same numbers in `O(n)`.
    out: list[float] = []
    total = square = 0.0
    for i, value in enumerate(values):
        count = min(i, span)
        if count > 10:
            mean = total / count
            variance = max(square / count - mean * mean, 0.0)
            spread = math.sqrt(variance) or 1.0
        else:
            spread = 1.0
        out.append(value / spread)
        total += value
        square += value * value
        if i >= span:
            dropped = values[i - span]
            total -= dropped
            square -= dropped * dropped
    return out


def _lag_one(values: list[float]) -> float:
    if len(values) < 10:
        return float("nan")
    middle = statistics.fmean(values)
    num = sum((a - middle) * (b - middle) for a, b in itertools.pairwise(values))
    den = sum((a - middle) ** 2 for a in values)
    return num / den if den > 0 else float("nan")


if __name__ == "__main__":
    main()
