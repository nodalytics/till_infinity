"""Five proposed regime gates, against random gating at the same duty cycle.

Five ideas from the reading pile all have the same shape - **one scalar
computed on a rolling window, proposed as a switch for when to trade** - so
they get one harness and one control.

| statistic | the claim | source |
| --- | --- | --- |
| Lempel-Ziv complexity of binarised returns | low LZ means repeating patterns, so "deploy momentum aggressively" | LZ and crypto crises, 2020 |
| Gini of absolute returns | converges to a **universal 0.84 +/- 0.03** in self-organised critical systems; deviations mean-revert and signal transitions | Bak-Tang-Wiesenfeld, via Ghosh |
| Kuramoto order parameter | phase synchronisation across scales; `R -> 1` is a crisis | EMD plus Hilbert, and the chimera papers |
| RQA laminarity | drops sharply as the market goes from coherent to chaotic - "the structural crack before the break" | reversal alphas, no. 13 |
| Wasserstein drift between consecutive windows | a distributional change detector, to be raced against a fitted chain | this package's own `distance.py` |

## The control is the whole harness

A gate that halves the time in the market changes the result whether or not it
knows anything, and the only honest comparison is **against gating at random
with the same duty cycle**. That is not a general scruple: every pause rule
this desk has tested matched random pausing at the same duty cycle, which is
recorded in the strategy-rotation work, and nothing here deserves a weaker
test than those got.

So each gate is scored against 400 random subsets of exactly the same size,
and what is reported is the z-score of the real gate within that distribution.
Anything inside +/- 2 is a duty-cycle effect wearing a physics hat.

## Two targets, because one of them is already known to be findable

* **Direction** - does the next bar continue the last one? Magnitude is
  predictable on this desk and direction is not, so a gate that helps here
  would be new.
* **Magnitude** - is the next bar's absolute move larger than its trailing
  median? Any gate built on a volatility-sensitive statistic will "work" here,
  and most of these are volatility-sensitive, so this column exists to catch
  a gate claiming a directional edge it is getting from clustering.

Reporting both is the point. A gate that moves magnitude and not direction has
rediscovered volatility clustering.

## The Gini claim is tested as a measurement, not a gate

`0.84 +/- 0.03` is an absolute number, so it can simply be computed - and the
test that matters is what it reads on series whose generator is known. The
Gini of the absolute values of a **Gaussian** is `2 Phi(1/sqrt 2) - 1 = 0.52`
analytically, so 0.84 is a real constraint rather than an artefact of taking
absolute values. Whether a market meets it, and whether a Deriv volatility
index with known Gaussian increments meets it, decides whether the anchor
means anything.

Also worth recording: the source describes laminarity as counting **diagonal**
lines in the recurrence matrix. That is determinism. Laminarity counts
**vertical** lines - states that stay put rather than states that repeat a
trajectory. The implementation here uses the vertical definition and a cheap
proxy for it, and says so, because a statistic implemented from a wrong
definition tests nothing.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from pathlib import Path

HOUR = 3600.0
SEED = 20261012
DRAWS = int(os.environ.get("DRAWS", "400"))

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD")
#: Known generators. `Volatility_*` is Gaussian increments, so it fixes what
#: each statistic reads when there is provably no regime to find.
GENERATED = ("Volatility_75_Index", "Volatility_25_Index", "Step_Index", "Jump_100_Index")
FRAMES = tuple(os.environ.get("FRAMES", "1h,4h").split(","))
WINDOW = int(os.environ.get("WINDOW", "120"))
LIMIT = int(os.environ.get("LIMIT", "40000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = np.asarray(bundle["time"], dtype=float)[order]
        closes = np.asarray(bundle["close"], dtype=float)[order]
    keep = closes > 0
    times, closes = times[keep], closes[keep]
    if len(times) > LIMIT:
        times, closes = times[-LIMIT:], closes[-LIMIT:]
    return (times, closes) if len(times) > 3 * WINDOW else None


# ------------------------------------------------------------- the statistics


def lempel_ziv(values) -> float:
    """LZ76 complexity of the sign sequence, normalised by its random value.

    Binarised on the sign of each move, then the Lempel-Ziv production
    complexity: walk the string and count how many times a prefix has to be
    extended because what follows is not already a substring of what came
    before. Normalised by `n / log2(n)`, the asymptotic value for a random
    binary string, so **1.0 means incompressible** and lower means repetition.
    """
    bits = "".join("1" if v > 0 else "0" for v in values)
    n = len(bits)
    if n < 16:
        return float("nan")
    i, complexity, length = 0, 1, 1
    while i + length < n:
        if (
            bits[i + length] in ("0", "1")
            and bits[: i + length].find(bits[i : i + length + 1]) >= 0
        ):
            length += 1
        else:
            complexity += 1
            i += length
            length = 1
    return complexity / (n / math.log2(n))


def gini(values) -> float:
    """Gini coefficient of absolute values. 0.52 for a Gaussian, analytically.

    `2 * sum(i * x_i) / (n * sum(x)) - (n + 1) / n` on the sorted absolute
    values - the standard form, which needs no binning and no window choice
    beyond the sample itself.
    """
    sizes = sorted(abs(float(v)) for v in values)
    n = len(sizes)
    total = sum(sizes)
    if n < 8 or total <= 0.0:
        return float("nan")
    weighted = sum((i + 1) * v for i, v in enumerate(sizes))
    return 2.0 * weighted / (n * total) - (n + 1.0) / n


def kuramoto(values, periods=(4, 8, 16, 32)) -> float:
    """Phase coherence across scales, without EMD.

    The source prescription is EMD into intrinsic modes, then the Hilbert
    phase of each, then `R = |mean(exp(i theta))|`. EMD's modes are
    data-dependent and not reproducible across windows, which makes the
    statistic incomparable between windows - the opposite of what a gate
    needs. So the modes here are **fixed band-pass filters** at the periods
    given: a difference of two moving averages per period, whose phase comes
    from the filtered series and its own one-step difference, which is the
    quadrature pair a Hilbert transform would supply for a narrow band.

    `R -> 1` means every scale is doing the same thing at the same time.
    """
    series = list(values)
    n = len(series)
    if n < max(periods) * 3:
        return float("nan")
    real, imaginary = 0.0, 0.0
    counted = 0
    for period in periods:
        fast = statistics.fmean(series[-period:])
        slow = statistics.fmean(series[-2 * period :])
        band = fast - slow
        previous_fast = statistics.fmean(series[-period - 1 : -1])
        previous_slow = statistics.fmean(series[-2 * period - 1 : -1])
        rate = band - (previous_fast - previous_slow)
        size = math.hypot(band, rate * period)
        if size <= 0.0:
            continue
        angle = math.atan2(rate * period, band)
        real += math.cos(angle)
        imaginary += math.sin(angle)
        counted += 1
    if not counted:
        return float("nan")
    return math.hypot(real, imaginary) / counted


def laminarity(values, tolerance: float = 0.5) -> float:
    """Vertical-line structure in the recurrence plot, as a run length.

    **Laminarity counts vertical lines, not diagonal ones** - the source has
    this wrong, and diagonal lines are determinism. A vertical line means the
    system sat near one state while time passed, so the cheap and exact proxy
    is the **mean length of runs during which the series stays within
    `tolerance` standard deviations of where the run began**. That is what a
    vertical line in the recurrence matrix is, computed in one pass instead of
    `n^2`.
    """
    series = [float(v) for v in values]
    if len(series) < 16:
        return float("nan")
    spread = statistics.pstdev(series)
    if spread <= 0.0:
        return float("nan")
    runs = []
    anchor, length = series[0], 1
    for value in series[1:]:
        if abs(value - anchor) <= tolerance * spread:
            length += 1
        else:
            runs.append(length)
            anchor, length = value, 1
    runs.append(length)
    return statistics.fmean(runs)


def wasserstein_drift(earlier, later) -> float:
    """How far this window's distribution moved from the previous one's."""
    from till_infinity.structures.statespace.distance import wasserstein

    if len(earlier) < 16 or len(later) < 16:
        return float("nan")
    spread = statistics.pstdev(list(earlier) + list(later))
    if spread <= 0.0:
        return float("nan")
    return wasserstein(list(earlier), list(later)) / spread


def avalanches(values):
    """Maximal runs of same-signed moves, as `(sizes, durations)`.

    **The Gini claim is about avalanches and a bar is not an avalanche.** In a
    sandpile the 0.84 is the Gini of *event* sizes - one toppling cascade,
    integrated over however many time steps it lasts - and translating that to
    "the distribution of absolute returns" silently replaces the event with a
    single sample of it. A run of same-signed returns is the nearest thing a
    price series has to a cascade: it starts, it builds, it stops.

    So this is the claim's own statistic rather than a proxy for it, and the
    per-bar version in `gini` is kept beside it because the gap between the
    two is the interesting part - if the sandpile number appears here and not
    there, the claim is fine and the usual translation of it is not.
    """
    sizes, durations = [], []
    total, length, sign = 0.0, 0, 0
    for value in values:
        this = 1 if value > 0 else (-1 if value < 0 else 0)
        if this == 0:
            continue
        if this != sign and length:
            sizes.append(total)
            durations.append(length)
            total, length = 0.0, 0
        sign = this
        total += abs(float(value))
        length += 1
    if length:
        sizes.append(total)
        durations.append(length)
    return sizes, durations


STATISTICS = ("lempel_ziv", "gini", "kuramoto", "laminarity", "wasserstein")
#: Which tail of each statistic the source says is the tradeable one. `"low"`
#: means the claim is about small values. Written down because picking the
#: better tail after seeing the answer would turn every one of these into a
#: two-sided test reported as one-sided.
CLAIMED = {
    "lempel_ziv": "low",  # low complexity = repeating = momentum works
    "gini": "high",  # far from 0.84 = non-equilibrium; see note below
    "kuramoto": "high",  # R -> 1 = synchronised = crisis
    "laminarity": "low",  # collapsing laminarity = the crack before the break
    "wasserstein": "high",  # a big distributional move = a regime change
}


def measure(times, closes):
    """One row per window: the five statistics, and the two targets after it."""
    import numpy as np

    moves = np.diff(np.log(closes))
    n = len(moves)
    rows = []
    step = max(WINDOW // 8, 1)
    start = WINDOW
    while start + 1 < n:
        window = moves[start - WINDOW : start]
        previous = moves[max(0, start - 2 * WINDOW) : start - WINDOW]
        ahead = float(moves[start])
        last = float(moves[start - 1])
        trailing = float(np.median(np.abs(window)))
        rows.append(
            {
                "lempel_ziv": lempel_ziv(window),
                "gini": gini(window),
                "kuramoto": kuramoto(np.cumsum(window)),
                "laminarity": laminarity(np.cumsum(window)),
                "wasserstein": (
                    wasserstein_drift(previous, window) if len(previous) >= 16 else float("nan")
                ),
                # Direction: does the next move continue the last one?
                "continued": 1.0 if ahead * last > 0 else 0.0,
                # Magnitude: is the next move bigger than the window's median?
                "larger": 1.0 if abs(ahead) > trailing else 0.0,
            }
        )
        start += step
    return rows


def gated(rows, name: str, tail: str, share: float = 1.0 / 3.0):
    """The gate's two hit rates, and the z-score of each against random gating.

    `DRAWS` random subsets of exactly the gated size give the distribution a
    duty-cycle effect would produce on its own. The z-score is the real gate's
    distance from the middle of that - **not** its distance from the whole
    sample's mean, which is the comparison that makes every gate look alive.
    """
    usable = [r for r in rows if not math.isnan(r[name])]
    if len(usable) < 200:
        return None
    order = sorted(usable, key=lambda r: r[name], reverse=(tail == "high"))
    take = max(int(len(order) * share), 30)
    picked = order[:take]
    rng = random.Random(SEED)
    out = {"n": len(usable), "k": take, "cut": picked[-1][name]}
    for target in ("continued", "larger"):
        real = statistics.fmean(r[target] for r in picked)
        draws = []
        for _ in range(DRAWS):
            draws.append(statistics.fmean(r[target] for r in rng.sample(usable, take)))
        middle = statistics.fmean(draws)
        spread = statistics.stdev(draws)
        out[target] = real
        out[target + "_z"] = (real - middle) / spread if spread > 0 else float("nan")
        out[target + "_all"] = statistics.fmean(r[target] for r in usable)
    return out


def main() -> None:
    print(
        f"window {WINDOW} bars, frames {FRAMES}, {DRAWS} random draws per gate\n"
        "Each gate takes the claimed tercile of a statistic. 'cont' is how\n"
        "often the next bar continued the last one, 'larg' how often it beat\n"
        "the window's median absolute move. The z columns are against random\n"
        "subsets of the same size - inside +/-2 is a duty-cycle effect.\n"
    )

    print("=" * 104)
    print("ARM 1  the Gini anchor. Per bar, where a Gaussian reads 0.520, and per")
    print("       *avalanche* - a run of same-signed moves, which is the statistic")
    print("       the sandpile 0.84 is actually about.")
    print("=" * 104)
    print(
        f"{'instrument':<22}{'frame':<6}{'windows':>8}{'median gini':>13}{'iqr':>9}"
        f"{'share in 0.84+/-0.03':>22}{'avalanche gini':>16}{'duration':>12}"
        f"{'avalanches':>12}"
    )
    everything: dict[tuple[str, str], list] = {}
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        for name in names:
            for frame in FRAMES:
                found = load(name, frame)
                if found is None:
                    continue
                rows = measure(*found)
                everything[(name, frame)] = rows
                ginis = sorted(r["gini"] for r in rows if not math.isnan(r["gini"]))
                if len(ginis) < 20:
                    continue
                inside = sum(1 for g in ginis if abs(g - 0.84) <= 0.03) / len(ginis)
                low = ginis[len(ginis) // 4]
                high = ginis[3 * len(ginis) // 4]
                import numpy as np

                sizes, spans = avalanches(np.diff(np.log(found[1])))
                print(
                    f"{name:<22}{frame:<6}{len(ginis):>8}"
                    f"{statistics.median(ginis):>13.3f}{high - low:>9.3f}{inside:>22.2f}"
                    f"{gini(sizes):>16.3f}{gini(spans):>12.3f}{len(sizes):>12}"
                )

    print("\n" + "=" * 104)
    print("ARM 2  each statistic as a gate, against random gating at the same duty cycle")
    print("=" * 104)
    collected: dict[str, list] = {}
    for (name, frame), rows in everything.items():
        print(f"\n--- {name} {frame} ---")
        print(
            f"{'statistic':<14}{'tail':<6}{'n':>6}{'k':>6}{'cut':>9}"
            f"{'cont':>8}{'all':>8}{'z':>8}{'larg':>8}{'all':>8}{'z':>8}"
        )
        for statistic in STATISTICS:
            got = gated(rows, statistic, CLAIMED[statistic])
            if got is None:
                continue
            group = "generated" if name in GENERATED else "traded"
            collected.setdefault(f"{group}:{statistic}", []).append(got)
            print(
                f"{statistic:<14}{CLAIMED[statistic]:<6}{got['n']:>6}{got['k']:>6}"
                f"{got['cut']:>9.3f}"
                f"{got['continued']:>8.3f}{got['continued_all']:>8.3f}"
                f"{got['continued_z']:>+8.2f}"
                f"{got['larger']:>8.3f}{got['larger_all']:>8.3f}{got['larger_z']:>+8.2f}"
            )

    print("\n" + "=" * 104)
    print("ARM 3  the verdict: median z across cells, traded against generated")
    print("=" * 104)
    print(
        f"{'group:statistic':<30}{'cells':>7}{'med z direction':>18}{'med z magnitude':>18}"
        f"{'|z|>2 direction':>18}"
    )
    for key in sorted(collected):
        rows = collected[key]
        direction = [r["continued_z"] for r in rows if not math.isnan(r["continued_z"])]
        magnitude = [r["larger_z"] for r in rows if not math.isnan(r["larger_z"])]
        if not direction:
            continue
        print(
            f"{key:<30}{len(rows):>7}{statistics.median(direction):>+18.2f}"
            f"{statistics.median(magnitude):>+18.2f}"
            f"{sum(1 for z in direction if abs(z) > 2) / len(direction):>18.2f}"
        )
    print("\nDONE")


if __name__ == "__main__":
    main()
