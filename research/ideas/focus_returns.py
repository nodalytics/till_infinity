"""Do FOCuS change-point levels get revisited faster than geometry alone?

Return rates grow with the horizon. That is not a finding, it is recurrence: a
driftless walk returns to any level with probability 1 given enough time, and
`a-return-rate-is-geometry` measured the consequence - the displacement
origin's 82% return rate is matched by a **distance-matched placebo on every
class**, and a walk reads 0.825. So a bare rate, and the growth of a bare rate
with the horizon, say nothing.

`a-magnet-is-a-shared-reference` prescribes the time exponent instead. This
goes one better, because for this particular question the walk's answer is
known in closed form rather than only in its scaling.

## The collapse, which is an exact prediction rather than a fitted exponent

For Brownian motion, the probability of touching a level within time `h`
starting `d` standard deviations away is

    P = erfc( d / sqrt(2 h) )

so it depends on the distance and the horizon **only through `h / d^2`**. Every
`(d, h)` cell with the same `h / d^2` must give the same `P`, and the whole
two-dimensional grid must collapse onto one curve.

That makes the test sharp in a way a rate is not:

* a **rate** grows with `h` for any process, so it cannot discriminate;
* an **exponent** has to be fitted, and `sweep-thresholds-on-the-mean-not-z`
  records a z-grid faking a ridge where the mean grid was monotone;
* the **collapse** is a prediction with no free parameter, and a process whose
  cells do not collapse - or collapse onto a curve above the walk's - has
  structure the walk does not.

So the reported statistic is `P` per `(d, h)` cell, grouped by `h / d^2`, and
the number that matters is `focus` minus the distance-matched placebo at the
same `h / d^2`.

## FOCuS has to be fed correctly or it finds nothing, for ever

`research/docs/delivering.md` records the defect: `Focus` divides each
observation by a `scale` whose default is 1.0 and applies a Gaussian statistic,
so one-minute log returns of order 1e-4 give a statistic of order 1e-8 that
clears no threshold at all. It is also **one-sided** - `up=True` is blind to
half the change points there are. Scaled by the returns' own standard deviation
and run in both directions it found 1,488 change points on the same series.

Both corrections are applied here: returns are divided by a trailing standard
deviation, and two instances run with `up=True` and `up=False`.

## The arms

* **focus** - levels at the change points FOCuS reports.
* **placebo** - the same number of anchors at random times, carried through the
  identical distance ladder. This is the arm that killed the origin's 82%, and
  `the-placebo-arm-selects-the-null` is the standing instruction to reject any
  null a placebo also passes.
* **shuffled** - the feed's own returns block-shuffled, so bar geometry and the
  marginal survive and only the ordering dies.
* **walk** - Brownian paths, where the collapse must hold exactly and `P` must
  match `erfc(d / sqrt(2h))`. This is the arm that catches an implementation
  error rather than a market effect, and the closed form means it needs no
  separate calibration.

A cell is only reported once it holds `LEAST_EVENTS` anchors, and the guard is
applied **after** pooling across feeds rather than per feed:
`pool-events-before-a-per-feed-guard` records a min-events guard dropping 141
of 146 feeds and making 0.9 sigma look like 4.8.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pattern_fingerprint import CACHE  # noqa: E402

FRAME = os.environ.get("FRAME", "1h")
#: Distances from the level, in trailing standard deviations.
DISTANCES = (1.0, 2.0, 3.0)
#: Horizons, in bars, measured from the moment the distance is first reached.
HORIZONS = (5, 10, 20, 40, 80, 160)
VOL_WINDOW = 50
THRESHOLD = float(os.environ.get("THRESHOLD", "15.0"))
LEAST_EVENTS = 200
BLOCK = 16
SEED = 20261026

NAMES = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "NZDUSD",
    "EURJPY",
    "GBPJPY",
    "EURGBP",
    "XAUUSD",
    "XAGUSD",
    "Germany_40",
    "UK_100",
    "Japan_225",
    "US_Oil",
    "BTCUSD",
    "ETHUSD",
)


def _resolve(name: str) -> Path | None:
    exact = CACHE / f"{name}.{FRAME}.npz"
    if exact.exists():
        return exact
    hits = sorted(CACHE.glob(f"{name}.*.{FRAME}.npz"))
    return hits[0] if hits else None


def _load(name: str) -> np.ndarray | None:
    path = _resolve(name)
    if path is None:
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        close = np.asarray(bundle["close"], dtype=float)[order]
    close = close[close > 0]
    return close if len(close) >= VOL_WINDOW + max(HORIZONS) + 500 else None


def _trailing_sd(returns: np.ndarray, window: int = VOL_WINDOW) -> np.ndarray:
    """Trailing sd of the `window` returns strictly before each point."""
    squared = returns * returns
    kernel = np.ones(window, dtype=float) / window
    rolled = np.convolve(squared, kernel, mode="valid")[:-1]
    out = np.full(len(returns), np.nan)
    out[window:] = np.sqrt(np.maximum(rolled, 0.0))
    return out


def changepoints(returns: np.ndarray, sd: np.ndarray) -> tuple[list[int], list[int]]:
    """(where the change was, where it was detected), both as array indices.

    `delivering.md`: unscaled and one-sided it reports nothing for ever, so the
    stream is divided by a trailing sd and two instances run in both
    directions.

    **Two lists, because the difference is the whole problem.** FOCuS is an
    exact likelihood ratio over all change points, so it reports not only that
    a change happened but `at`, where it most likely was - and that is earlier
    than the bar the statistic cleared its threshold on. Anchoring on the
    detection bar made every distance rung collapse onto one bar: price was
    already past 3 sd by the time the evidence arrived, 2,552 change points
    produced zero usable cells, and the tell was a focus column identical
    across distances while the placebo column fell correctly.

    `at` counts observations fed, not array positions, and observations with no
    usable scale are skipped - so the mapping back is kept rather than assumed.
    """
    from till_infinity.structures.learning.focus import Focus

    engines = [Focus(threshold=THRESHOLD, up=True), Focus(threshold=THRESHOLD, up=False)]
    fed: list[int] = []
    where: list[int] = []
    seen: list[int] = []
    for i, value in enumerate(returns):
        scale = sd[i]
        if not np.isfinite(scale) or scale <= 0:
            continue
        fed.append(i)
        for engine in engines:
            if engine.update(float(value), scale=float(scale)):
                at = int(engine.at)
                where.append(fed[at] if 0 <= at < len(fed) else i)
                seen.append(i)
                for other in engines:
                    other.reset()
                break
    return where, seen


def _rates(
    closes: np.ndarray,
    sd: np.ndarray,
    anchors: list[int],
) -> dict[tuple[float, int], tuple[int, int]]:
    """(touched, total) per (distance, horizon) cell.

    From each anchor the level is that bar's close. The clock starts not at the
    anchor but at the bar where price is first `d` standard deviations away,
    which is what makes the cell comparable to the walk's closed form and what
    makes the placebo distance-matched rather than merely time-matched.
    """
    out: dict[tuple[float, int], tuple[int, int]] = {}
    span = len(closes)
    for anchor in anchors:
        level = closes[anchor]
        scale = sd[anchor]
        if not np.isfinite(scale) or scale <= 0 or level <= 0:
            continue
        unit = scale * level
        for distance in DISTANCES:
            want = distance * unit
            start = -1
            stop = min(anchor + 1 + max(HORIZONS) * 2, span)
            for i in range(anchor + 1, stop):
                if abs(closes[i] - level) >= want:
                    start = i
                    break
            if start < 0:
                continue
            # **Binned on the REALISED displacement, not the requested one.**
            # FOCuS fires late - the statistic needs a run of evidence - so by
            # the time it reports, price is often already past 3 sd, and then
            # the "first bar at least d sd away" is the *same bar* for every d.
            # The first version of this harness did exactly that and its focus
            # column was identical across distances (0.072 / 0.071 / 0.069 at
            # h=5) while the placebo column fell correctly (0.315 / 0.168 /
            # 0.082). The two arms were being started from different places,
            # which is the one thing a distance-matched placebo exists to
            # prevent, and the flat column was the only tell.
            realised = abs(closes[start] - level) / unit
            if realised >= distance + 0.5:
                # Overshot this rung. Counted at the rung it actually reached,
                # if there is one, and otherwise dropped - rather than being
                # recorded at a distance it was never at.
                continue
            side = 1.0 if closes[start] > level else -1.0
            for horizon in HORIZONS:
                end = start + horizon
                if end >= span:
                    continue
                window = closes[start : end + 1]
                # Returning means crossing back to the level, from whichever
                # side price left on.
                back = bool((window * side <= level * side).any())
                touched, total, seen = out.get((distance, horizon), (0, 0, 0.0))
                out[(distance, horizon)] = (
                    touched + int(back),
                    total + 1,
                    seen + realised,
                )
    return out


def _walk_rates(rng, paths: int = 400, bars: int = 4000) -> dict:
    out: dict[tuple[float, int], tuple[int, int]] = {}
    for _ in range(paths):
        steps = rng.normal(0.0, 0.001, bars)
        closes = 100.0 * np.exp(np.cumsum(steps))
        sd = np.full(bars, 0.001)
        anchors = list(range(VOL_WINDOW, bars - max(HORIZONS) * 3, 200))
        got = _rates(closes, sd, anchors)
        for key, (touched, total, seen) in got.items():
            was = out.get(key, (0, 0, 0.0))
            out[key] = (was[0] + touched, was[1] + total, was[2] + seen)
    return out


def _merge(into: dict, got: dict) -> None:
    for key, (touched, total, seen) in got.items():
        was = into.get(key, (0, 0, 0.0))
        into[key] = (was[0] + touched, was[1] + total, was[2] + seen)


def _show(label: str, cells: dict) -> None:
    print(f"\n=== {label}")
    print(f"{'d':>4s} {'real d':>7s} {'h':>5s} {'h/d^2':>8s} {'P':>7s} {'erfc':>7s} {'n':>7s}")
    for distance in DISTANCES:
        for horizon in HORIZONS:
            touched, total, seen = cells.get((distance, horizon), (0, 0, 0.0))
            if total < LEAST_EVENTS:
                continue
            real = seen / total
            # `erfc` is evaluated at the **realised** distance, so the closed
            # form is compared against where price actually was.
            closed = math.erfc(real / math.sqrt(2.0 * horizon))
            print(
                f"{distance:>4.1f} {real:>7.2f} {horizon:>5d} "
                f"{horizon / (real * real):>8.2f} "
                f"{touched / total:>7.3f} {closed:>7.3f} {total:>7d}"
            )


def main() -> None:
    print(__doc__.split("\n\n")[0])
    print(
        f"\nframe {FRAME}, FOCuS threshold {THRESHOLD}, both directions, "
        f"returns scaled by a {VOL_WINDOW}-bar trailing sd.\n"
        f"`P` is the share returning to the level within `h` bars of first "
        f"reaching `d` sd away.\n`erfc` is the Brownian closed form, which "
        f"depends on `d` and `h` only through `h/d^2`.\n"
    )
    rng = np.random.default_rng(SEED)
    focus: dict = {}
    late: dict = {}
    placebo: dict = {}
    shuffled: dict = {}
    latency: list[int] = []
    counted = 0
    for name in NAMES:
        closes = _load(name)
        if closes is None:
            continue
        returns = np.diff(np.log(closes))
        sd = _trailing_sd(returns)
        padded = np.concatenate(([np.nan], sd))
        found, detected = changepoints(returns, sd)
        if not found:
            continue
        counted += len(found)
        latency.extend(d - w for w, d in zip(found, detected, strict=True))
        _merge(focus, _rates(closes, padded, found))
        _merge(late, _rates(closes, padded, detected))
        # Distance-matched placebo: the same number of anchors, at random times.
        where = rng.choice(
            np.arange(VOL_WINDOW + 1, len(closes) - max(HORIZONS) * 3),
            size=min(len(found), len(closes) // 4),
            replace=False,
        )
        _merge(placebo, _rates(closes, padded, sorted(int(x) for x in where)))
        # Block-shuffled: bar geometry and marginal survive, ordering dies.
        blocks = [returns[i : i + BLOCK] for i in range(0, len(returns), BLOCK)]
        rng.shuffle(blocks)
        spun = np.concatenate(blocks)[: len(returns)]
        rebuilt = closes[0] * np.exp(np.cumsum(spun))
        _merge(shuffled, _rates(rebuilt, padded, found))
    print(f"{counted} change points across the loaded feeds")
    if latency:
        order = sorted(latency)
        print(
            f"detection latency: median {order[len(order) // 2]} bars, "
            f"p90 {order[int(0.9 * len(order))]} bars. **This is why the "
            f"anchor is `at` and not the detection bar.**"
        )

    _show("WALK (P must match erfc, and the grid must collapse on h/d^2)", _walk_rates(rng))
    _show("focus change points, anchored where FOCuS says the change WAS", focus)
    _show("the same, anchored on the DETECTION bar (the latency's cost)", late)
    _show("placebo (distance-matched, random anchors)", placebo)
    _show("block-shuffled returns, focus anchors", shuffled)

    print("\n=== focus minus placebo, by h/d^2")
    print(
        f"{'d':>4s} {'h':>5s} {'focus d':>8s} {'plac d':>7s} "
        f"{'focus':>7s} {'placebo':>8s} {'gap':>7s}"
    )
    for distance in DISTANCES:
        for horizon in HORIZONS:
            ft, fn, fs = focus.get((distance, horizon), (0, 0, 0.0))
            pt, pn, ps = placebo.get((distance, horizon), (0, 0, 0.0))
            if fn < LEAST_EVENTS or pn < LEAST_EVENTS:
                continue
            # **The two realised-distance columns are the audit.** If they
            # disagree the gap is a mismatch and not a result, which is how the
            # first run of this harness read -0.24 to -0.36.
            print(
                f"{distance:>4.1f} {horizon:>5d} {fs / fn:>8.2f} {ps / pn:>7.2f} "
                f"{ft / fn:>7.3f} {pt / pn:>8.3f} {ft / fn - pt / pn:>+7.3f}"
            )
    print(
        "\nA gap near zero means the level is doing nothing a distance-matched\n"
        "anchor does not - which is what `a-return-rate-is-geometry` measured\n"
        "for the displacement origin, where a walk read 0.825 against its 82%."
    )


if __name__ == "__main__":
    main()
