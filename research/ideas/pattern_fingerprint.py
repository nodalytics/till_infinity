"""Which process does an instrument's pattern vocabulary look like?

Every pattern study on this desk ends the same way: the pattern is found
exactly, and it occurs at the rate a walk produces it. `sweeps.md` has every
sweep form at 0.94-1.02x an iid walk's rate on the diffusive indices;
`bos-predict.md` has break geometry at AUC 0.75 on walks as well as markets;
`smc-conjunctions.md` has every primitive inside its own walk.

That is a dead end as a search for edge and a **starting point** as a
measurement. If pattern rates are set by the generating process, then the
vector of pattern rates is a **fingerprint of that process** - and an
instrument can be matched to the family whose fingerprint it reproduces.

Two things follow, and neither is a trading signal:

1. **A better null per instrument.** Testing a new pattern against a generic
   Gaussian walk is testing it against the wrong process. Matching first, then
   nulling against the matched family, is a sharper test.
2. **A targeted residual.** Where a real instrument departs from its own
   best-fit family, that departure is the structure, and it says which
   statistic to look at rather than leaving the whole space open.

## The bars have to be generated, not decorated

Pattern rates depend on wick structure, so OHLC cannot be a close series with
wicks bolted on - that choice would decide the answer. Every family here is
simulated at **sub-bar resolution** and aggregated, so the high and the low
emerge from the same process that makes the close. An earlier harness used
`close +/- |N(0, sigma/2)|` for wicks, which is a free parameter sitting
directly on top of every statistic being measured.

## The statistics, and why these

Seventeen numbers, each scale-free so a family is compared on shape rather than
size: pattern rates (engulf, inside bar, doji, CRT, external sweep, structure
shift, imbalance, displacement origin), candle shape (body share, the engulfing
bar's range against the median, wick asymmetry), dependence (return and
absolute-return autocorrelation, the two-bar variance ratio), distribution
(skew, excess kurtosis), and the origin return rate at a hundred bars that
`origin-return-rates.md` measured.

## The control that decides whether any of it means anything

**A matcher that cannot recover a known family is noise.** Each family is
simulated many times; the library is built from all but one replicate and the
held-out one is matched back. The confusion matrix is reported before any real
instrument is named, and if its diagonal is weak nothing below it should be
read.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from till_infinity.structures.statespace.behaving import classify  # noqa: E402

CACHE = Path.home() / "till_infinity/data/seqlab"
FRAMES = ("1h", "4h")
LIMIT = 40000
#: Bars simulated per replicate, and sub-bar steps each is built from.
BARS = 20000
SUB = 24
#: Replicates per family. One is held out at a time for the confusion matrix.
REPLICATES = 10
#: Instruments per class.
PER_CLASS = 20
SEED = 20261015
#: GARCH(1,1), the constants already in `statespace/nulls.py`.
GARCH = (0.02, 0.10, 0.88)
#: Horizon for the origin return rate, matching `origin-return-rates.md`.
ORIGIN_HORIZON = 100
UNIT_BACK = 100


def _ar_one(rho: float, count: int, rng) -> np.ndarray:
    """An AR(1) path, by recursive filter rather than a Python loop."""
    from scipy.signal import lfilter

    return lfilter([1.0], [1.0, -float(rho)], rng.normal(0.0, 1.0, count))


def steps_for(family: str, count: int, rng) -> np.ndarray:
    """Sub-bar log returns for one family, scaled to unit standard deviation.

    Scaled because every statistic downstream is scale-free, so the level of
    volatility is not part of the fingerprint and should not be allowed to
    leak into one.
    """
    if family == "gaussian":
        out = rng.normal(0.0, 1.0, count)
    elif family == "student_t":
        out = rng.standard_t(4.0, count)
    elif family == "garch":
        constant, shock, memory = GARCH
        out = np.empty(count)
        variance = constant / max(1.0 - shock - memory, 1e-6)
        previous = 0.0
        for i in range(count):
            variance = constant + shock * previous**2 + memory * variance
            previous = math.sqrt(variance) * rng.normal()
            out[i] = previous
    elif family == "jump":
        out = rng.normal(0.0, 1.0, count)
        hit = rng.random(count) < 0.002
        out[hit] += rng.normal(0.0, 12.0, int(hit.sum()))
    elif family == "ou":
        # Mean reversion in the **level**, not in the returns: the price is
        # pulled back toward a centre, so the series is range-bound. That is a
        # different process from `reversal`, which puts the AR(1) on the
        # returns and wanders freely.
        level = _ar_one(1.0 - 0.004, count, rng)
        out = np.diff(np.concatenate(([0.0], level)))
    elif family == "drift":
        out = rng.normal(0.02, 1.0, count)
    elif family == "momentum":
        # **0.90, not 0.25, and the difference is aggregation.** The AR(1) runs
        # at sub-bar resolution and a bar is 24 of those, so a coefficient of
        # 0.25 leaves a bar-level autocorrelation of +0.003 - a momentum family
        # indistinguishable from Gaussian, which would have been a confusion in
        # the matrix rather than a property of the world. Swept: 0.50 gives
        # +0.028, 0.70 gives +0.050, 0.85 gives +0.176 and 0.90 gives +0.244.
        out = _ar_one(0.90, count, rng)
    elif family == "reversal":
        # The mirror does not mirror: -0.90 gives a bar-level -0.099 where
        # +0.90 gives +0.244, because alternating sub-steps cancel inside a bar
        # instead of accumulating. -0.95 is the strongest available and reaches
        # -0.137, which is the floor this family can be built at.
        out = _ar_one(-0.95, count, rng)
    elif family == "regime":
        out = np.empty(count)
        quiet = True
        for i in range(count):
            if rng.random() < (0.002 if quiet else 0.01):
                quiet = not quiet
            out[i] = rng.normal(0.0, 0.5 if quiet else 2.5)
    elif family == "lattice":
        out = rng.choice((-1.0, 1.0), count)
    else:
        raise ValueError(family)
    spread = float(np.std(out))
    return out / spread if spread > 0 else out


FAMILIES = (
    "gaussian",
    "student_t",
    "garch",
    "jump",
    "ou",
    "drift",
    "momentum",
    "reversal",
    "regime",
    "lattice",
)


def simulate(family: str, bars: int, sub: int, rng) -> dict[str, np.ndarray]:
    """OHLC aggregated from a sub-bar path, so wicks come from the process."""
    steps = steps_for(family, bars * sub, rng) * 0.0004
    path = 1.0 * np.exp(np.cumsum(steps))
    grid = path.reshape(bars, sub)
    opens = grid[:, 0]
    closes = grid[:, -1]
    return {
        "open": opens,
        "high": grid.max(axis=1),
        "low": grid.min(axis=1),
        "close": closes,
        "time": np.arange(bars, dtype=float) * 3600.0,
    }


def load(name: str, frame: str):
    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "open", "high", "low", "close"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
    keep = (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 4000:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def true_range(bars) -> np.ndarray:
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    prior = np.concatenate(([closes[0]], closes[:-1]))
    return np.maximum.reduce([highs - lows, np.abs(highs - prior), np.abs(lows - prior)])


def origin_rate(bars, horizon: int) -> float:
    """Share of displacement origins price returns to, by the desk's rule."""
    opens, highs = bars["open"], bars["high"]
    lows, closes = bars["low"], bars["close"]
    span = true_range(bars)
    unit = np.full(len(span), np.nan)
    csum = np.cumsum(span)
    unit[UNIT_BACK:] = (csum[UNIT_BACK:] - csum[:-UNIT_BACK]) / UNIT_BACK
    back = came = 0
    for i in range(UNIT_BACK, len(closes) - horizon - 4):
        here = unit[i]
        reach = highs[i] - lows[i]
        if not (here > 0) or reach <= 0:
            continue
        if not (0.10 <= abs(closes[i] - opens[i]) / reach <= 0.60):
            continue
        side = 1 if closes[i + 1] > opens[i + 1] else -1
        ok = True
        for j in (i + 1, i + 2):
            width = highs[j] - lows[j]
            if width <= 0 or side * (closes[j] - opens[j]) < 0.65 * width:
                ok = False
                break
        if not ok or abs(closes[i + 2] - opens[i + 1]) < 1.5 * here:
            continue
        low, high = float(lows[i]), float(highs[i])
        if (high - low) >= 2.0 * here:
            top, bottom = float(opens[i]), float(closes[i])
            if top != bottom:
                low, high = min(top, bottom), max(top, bottom)
        start = i + 3
        back += 1
        window = slice(start, min(start + horizon + 1, len(highs)))
        if np.any((lows[window] <= high) & (highs[window] >= low)):
            came += 1
    return came / back if back else float("nan")


def fingerprint(bars) -> dict[str, float]:
    """Seventeen scale-free statistics: the vocabulary this series speaks in."""
    opens, highs = bars["open"], bars["high"]
    lows, closes = bars["low"], bars["close"]
    reach = highs - lows
    good = reach > 0
    body = np.abs(closes - opens)
    out: dict[str, float] = {}

    bigger = (
        (highs[1:] >= highs[:-1]) & (lows[1:] <= lows[:-1]) & (reach[1:] > reach[:-1])
    )
    out["engulf"] = float(bigger.mean())
    out["inside bar"] = float(
        ((highs[1:] <= highs[:-1]) & (lows[1:] >= lows[:-1])).mean()
    )
    out["doji"] = float((body[good] / reach[good] < 0.10).mean())
    out["body share"] = float(np.median(body[good] / reach[good]))
    middle = float(np.median(reach[good]))
    where = np.flatnonzero(bigger) + 1
    out["engulf width"] = float(np.median(reach[where]) / middle) if len(where) else float("nan")

    upper = highs - np.maximum(opens, closes)
    lower = np.minimum(opens, closes) - lows
    out["wick tilt"] = float(np.median(upper[good] - lower[good]) / middle)

    # Candle Range Theory: take out the prior bar's extreme, close back inside.
    crt_up = (highs[1:] > highs[:-1]) & (closes[1:] < highs[:-1]) & (closes[1:] > lows[:-1])
    crt_down = (lows[1:] < lows[:-1]) & (closes[1:] > lows[:-1]) & (closes[1:] < highs[:-1])
    out["CRT"] = float((crt_up | crt_down).mean())

    # External sweep: past a twenty-bar extreme, closing back inside.
    roll_high = np.full(len(highs), np.nan)
    roll_low = np.full(len(lows), np.nan)
    for i in range(1, len(highs)):
        roll_high[i] = highs[max(i - 20, 0) : i].max()
        roll_low[i] = lows[max(i - 20, 0) : i].min()
    swept = ((highs > roll_high) & (closes < roll_high)) | ((lows < roll_low) & (closes > roll_low))
    out["sweep"] = float(np.nanmean(swept[20:]))

    # Three-bar imbalance.
    out["imbalance"] = float(
        ((lows[:-2] > highs[2:]) | (highs[:-2] < lows[2:])).mean()
    )

    steps = np.diff(np.log(np.maximum(closes, 1e-12)))
    spread = float(np.std(steps))
    if spread > 0:
        centred = (steps - steps.mean()) / spread
        out["skew"] = float((centred**3).mean())
        out["kurtosis"] = float((centred**4).mean() - 3.0)
        out["return ac"] = float(np.corrcoef(steps[:-1], steps[1:])[0, 1])
        size = np.abs(steps)
        out["size ac"] = float(np.corrcoef(size[:-1], size[1:])[0, 1])
        pair = steps[: len(steps) // 2 * 2].reshape(-1, 2).sum(axis=1)
        out["variance ratio"] = float(np.var(pair) / (2.0 * np.var(steps)))
    else:
        for key in ("skew", "kurtosis", "return ac", "size ac", "variance ratio"):
            out[key] = float("nan")

    # The run length of same-direction closes, in bars.
    sign = np.sign(steps)
    flips = np.flatnonzero(sign[1:] != sign[:-1])
    out["run length"] = float(np.median(np.diff(flips))) if len(flips) > 2 else float("nan")

    out["origin return"] = origin_rate(bars, ORIGIN_HORIZON)
    return out


STATS = (
    "engulf",
    "inside bar",
    "doji",
    "body share",
    "engulf width",
    "wick tilt",
    "CRT",
    "sweep",
    "imbalance",
    "skew",
    "kurtosis",
    "return ac",
    "size ac",
    "variance ratio",
    "run length",
    "origin return",
)


def library(rng) -> dict[str, list[dict[str, float]]]:
    """`REPLICATES` fingerprints per family."""
    out: dict[str, list[dict[str, float]]] = {}
    for family in FAMILIES:
        for _ in range(REPLICATES):
            out.setdefault(family, []).append(fingerprint(simulate(family, BARS, SUB, rng)))
    return out


def profile(found: list[dict[str, float]]) -> dict[str, tuple[float, float]]:
    """`(mean, sd)` per statistic over replicates of one family."""
    out = {}
    for stat in STATS:
        values = [f[stat] for f in found if f[stat] == f[stat]]
        if len(values) < 2:
            out[stat] = (float("nan"), float("nan"))
            continue
        out[stat] = (float(np.mean(values)), float(np.std(values, ddof=1)))
    return out


def distance(got: dict[str, float], shape: dict[str, tuple[float, float]]) -> float:
    """Mean squared z-distance, each statistic scaled by its own sampling spread.

    A statistic that wanders between replicates of the same family carries less
    weight automatically, which is what makes this comparable across
    statistics measured in different things.
    """
    total = count = 0.0
    for stat in STATS:
        mean, spread = shape[stat]
        value = got.get(stat, float("nan"))
        if value != value or mean != mean or not (spread > 0):
            continue
        total += ((value - mean) / spread) ** 2
        count += 1
    return total / count if count else float("inf")


def nearest(got: dict[str, float], shapes: dict[str, dict]) -> list[tuple[float, str]]:
    return sorted((distance(got, shape), name) for name, shape in shapes.items())


def offenders(got: dict[str, float], shape: dict[str, tuple[float, float]], top: int = 3):
    """The statistics contributing most of the distance, as `(stat, z, real, family)`.

    **This is the output that matters when nothing matches.** A distance of 1
    means the instrument sits inside the family's own replicate scatter; a
    distance of 300 says the best of ten families is still far away, and the
    only useful follow-up is *which statistic puts it there*. A family library
    that fails uniformly is uninformative; one that fails on two named
    statistics says what a better library needs.
    """
    rows = []
    for stat in STATS:
        mean, spread = shape[stat]
        value = got.get(stat, float("nan"))
        if value != value or mean != mean or not (spread > 0):
            continue
        rows.append((abs(value - mean) / spread, stat, value, mean))
    rows.sort(reverse=True)
    return rows[:top]


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"Pattern fingerprints: {len(STATS)} scale-free statistics, "
        f"{len(FAMILIES)} families, {REPLICATES} replicates of {BARS:,} bars\n"
        f"built from {SUB} sub-bar steps each.\n"
    )
    built = library(rng)

    print("=" * 100)
    print("The families, as they read")
    print("=" * 100)
    print(f"  {'stat':<16}" + "".join(f"{f[:9]:>10}" for f in FAMILIES))
    shapes = {name: profile(found) for name, found in built.items()}
    for stat in STATS:
        row = f"  {stat:<16}"
        for family in FAMILIES:
            mean, _spread = shapes[family][stat]
            row += f"{mean:>10.3f}" if mean == mean else f"{'-':>10}"
        print(row)

    print("\n" + "=" * 100)
    print("CONTROL  can the matcher recover a family it has seen only held out?")
    print("=" * 100)
    print(f"  {'true':<12}" + "".join(f"{f[:9]:>10}" for f in FAMILIES) + "   hit")
    hits = 0
    total = 0
    for truth in FAMILIES:
        counts = dict.fromkeys(FAMILIES, 0)
        for index in range(REPLICATES):
            held = built[truth][index]
            rest = {
                name: profile(
                    [f for j, f in enumerate(found) if not (name == truth and j == index)]
                )
                for name, found in built.items()
            }
            pick = nearest(held, rest)[0][1]
            counts[pick] += 1
            total += 1
            hits += pick == truth
        row = f"  {truth:<12}" + "".join(f"{counts[f]:>10}" for f in FAMILIES)
        print(row + f"{counts[truth] / REPLICATES:>7.2f}")
    print(
        f"\n  recovered {hits}/{total} = {hits / total:.2f} "
        f"against {1 / len(FAMILIES):.2f} by chance."
    )
    if hits / total < 0.5:
        print("  **The matcher does not identify. Nothing below should be read.**")

    print("\n" + "=" * 100)
    print("Real instruments, matched to the family they speak like")
    print("=" * 100)
    for frame in FRAMES:
        groups: dict[str, list[str]] = {}
        for path in sorted(CACHE.glob(f"*.{frame}.npz")):
            name = path.name[: -len(f".{frame}.npz")]
            groups.setdefault(classify(name), []).append(name)
        print(f"\n  --- {frame}")
        head = f"  {'class':<14}{'feeds':>6}  best family (share)"
        print(head + "    runner-up        median distance")
        for label in sorted(groups):
            picked = sorted(groups[label])[:PER_CLASS]
            votes: dict[str, int] = {}
            spans: list[float] = []
            blame: dict[str, list[float]] = {}
            examples: dict[str, tuple[float, float]] = {}
            for name in picked:
                bars = load(name, frame)
                if bars is None:
                    continue
                got = fingerprint(bars)
                order = nearest(got, shapes)
                votes[order[0][1]] = votes.get(order[0][1], 0) + 1
                spans.append(order[0][0])
                for zed, stat, value, mean in offenders(got, shapes[order[0][1]], top=4):
                    blame.setdefault(stat, []).append(zed)
                    examples[stat] = (value, mean)
            if not votes:
                continue
            ranked = sorted(votes.items(), key=lambda kv: -kv[1])
            feeds = sum(votes.values())
            second = f"{ranked[1][0]} ({ranked[1][1]})" if len(ranked) > 1 else "-"
            worst = sorted(
                ((float(np.median(z)), stat) for stat, z in blame.items() if len(z) >= 2),
                reverse=True,
            )[:3]
            print(
                f"  {label:<14}{feeds:>6}  {ranked[0][0]:<12}"
                f"({ranked[0][1] / feeds:.2f})      {second:<16}{np.median(spans):>10.1f}"
            )
            for zed, stat in worst:
                value, mean = examples[stat]
                print(
                    f"      {stat:<18}z {zed:>8.1f}   instrument {value:>9.3f}"
                    f"   family {mean:>9.3f}"
                )
    print(
        "\n  `median distance` is the mean squared z-gap to the best family, in units of\n"
        "  that family's own replicate-to-replicate spread. A distance near 1 means the\n"
        "  instrument sits inside the family's own scatter; a large one means the best\n"
        "  match is still a poor one, and no family in this library describes it.\n"
    )


if __name__ == "__main__":
    main()
