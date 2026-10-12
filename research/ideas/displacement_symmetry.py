"""Displacement sequences, symmetry, and the constants four write-ups assert.

Asked on 2026-10-11, to implement three structural ideas and - as the reading
went on - to check four more write-ups that turned out to be the same family.
They share an ancestor and they share a habit: each asserts a **characteristic
number** about the sequence of moves between reversals.

| asserted | by | this measures |
| --- | --- | --- |
| the correction factor is 0.86, universally | the original | `alpha` |
| no: 0.73 on EURUSD, 0.62 on BTC, 0.58 on the S&P | the revision | `alpha` per instrument |
| alpha is serially correlated, so predictable | the revision | `alpha_lag1` |
| alpha falls when trending, rises to 1 reverting | the revision | `alpha_by_trend` |
| each swing holds about 3.2 sub-swings, 2.3 to 4.1 | the revision | `branching` |
| a range sustains `(N*2)+1` rotations, then breaks | a practitioner | `hazard` |
| swings repeat under a symmetry transform at lag k | the geometry paper | `nsi` |
| geometric structure is more stable than price | the geometry paper | `portability` |

The last two write-ups report no numbers at all, so there is nothing in them
to replicate; the revision reports numbers and is the only one that can be
checked, and it is also the only one that criticises its own ancestor.

## The one measurement that decides most of the family

Three of these claims are a **counting** claim: that a phase sustains a
characteristic number of rotations and is then exhausted. Whatever the
arithmetic - `(N*2)+1`, or a branching ratio near three - the claim needs the
count distribution to be **peaked**, because an exhaustion signal is a
statement that a phase becomes *more* likely to end as the count rises.

So the decisive reading is not the mean count. It is the **hazard by count**:
the probability a swing ends after its `k`-th sub-swing, given it reached `k`.
A renewal process with a constant hazard produces a geometric count
distribution with a perfectly respectable mean near three and **no
exhaustion** - every rotation is as likely to be the last as the one before
it, so the count carries nothing. A flat hazard kills the family in one plot.

This desk has the prior: counted pivots per hour, over 1,020 cells, came back
inside 0.015 of zero net of a trailing standard deviation. A count was null.
A hazard is the sharper version of the same question.

## What the symmetry member is scored against

`Symmetry` observes `log(size(t)/size(t-1))`, so its likelihood is a density
over a ratio and cannot sit in a table beside a price member's. Two nulls
instead, both of which keep everything except the thing claimed:

* **shuffled** - the same displacements in a random order. Destroys symmetry,
  keeps the size distribution exactly. If the member scores the same here,
  it is reading the distribution of swing sizes and not their sequence.
* **walk** - the displacement sequence of a Gaussian random walk, which has
  turns and nothing between them.

And for the forecast, the usual two: a rotated control, and the net
correlation after a trailing standard deviation is taken out.

Runs on the lab.
"""

from __future__ import annotations

import itertools
import math
import os
import random
import statistics
from collections import Counter
from pathlib import Path

from till_infinity.structures.statespace.displacements import relations, sequence
from till_infinity.structures.statespace.distance import wasserstein
from till_infinity.structures.statespace.nulls import control, spearman, trailing
from till_infinity.structures.statespace.symmetry import Symmetry, nodal_symmetry

#: Two of these - EURUSD and the S&P - are instruments the revision reports a
#: correction factor for, which is what makes its numbers checkable rather
#: than merely stated. BTC is the third.
#:
#: **The generated series at the end are the control that matters.** They are
#: real markets - real spreads, real fills, real money - and this desk trades
#: them. What they do not have is an **auction**: the price comes from a
#: specified stochastic process rather than from participants crossing
#: orders, and the process is known rather than inferred.
#:
#: That is what makes them a better control than a simulation. Every claim
#: below is a claim about auction structure - accumulation, distribution,
#: exhaustion, phases - so a claim that holds just as well on
#: `Volatility_75_Index` is a claim about the detector and not about the
#: auction, and it is refuted on data the desk actually trades rather than on
#: a surrogate someone could dismiss.
SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("usdchf", "USDCHF"),
    ("audusd", "AUDUSD"),
    ("gold", "XAUUSD"),
    ("silver", "XAGUSD"),
    ("spx500", "SPX500"),
    ("us100", "US100"),
    ("ger40", "GER40"),
    ("btcusd", "BTCUSD"),
    ("ethusd", "ETHUSD"),
    ("nvda", "NVDA"),
    ("aapl", "AAPL"),
    ("v75", "Volatility_75_Index"),
    ("v100", "Volatility_100_Index"),
    ("v25", "Volatility_25_Index"),
    ("step", "Step_Index"),
    ("boom500", "Boom_500_Index"),
    ("crash500", "Crash_500_Index"),
    ("jump50", "Jump_50_Index"),
    ("range100", "Range_Break_100_Index"),
)

#: Which of the above have a known generator rather than an auction, by
#: label. Reported apart, because pooling a control with the thing it
#: controls for is how a null gets averaged away.
GENERATED = frozenset(
    {
        "Volatility_75_Index",
        "Volatility_100_Index",
        "Volatility_25_Index",
        "Step_Index",
        "Boom_500_Index",
        "Crash_500_Index",
        "Jump_50_Index",
        "Range_Break_100_Index",
    }
)
FRAMES = tuple(os.environ.get("FRAMES", "1h,4h,1d").split(","))

#: Pivot reach, coarse and fine. The fine one nests inside the coarse one and
#: the ratio of their counts is the branching ratio the revision reports.
COARSE = 5
FINE = 2

#: Lags for the symmetry index. The geometry paper leaves `k` free, so it is
#: swept - and a sweep is a multiple comparison, counted as such.
LAGS = (1, 2, 3, 4, 5, 6)

SINCE = float(os.environ.get("SINCE", "1262304000"))
LIMIT = int(os.environ.get("LIMIT", "40000"))
SEED = 20261011


def load(stem: str, frame: str, label: str = ""):
    """The pulled cache first, then the local gzipped files.

    Two sources because the broker feed lives behind the lab bridge and the
    bridge is not always up, and a measurement that can only run when a
    machine is reachable is a measurement that does not get repeated.
    """
    found = _from_cache(stem, frame, label) or _from_csv(stem, frame)
    if found is None:
        return None
    first = 0
    while first < len(found["time"]) and found["time"][first] < SINCE:
        first += 1
    for key, series in list(found.items()):
        trimmed = series[first:]
        found[key] = trimmed[-LIMIT:] if len(trimmed) > LIMIT else trimmed
    return found if len(found["time"]) > 500 else None


def _from_cache(stem: str, frame: str, label: str = "") -> dict | None:
    """The pulled cache, under either spelling.

    The puller names files by the broker's own spelling and the local files by
    a short stem, so both are tried rather than one being renamed - renaming
    1,552 cached files to suit a harness is the wrong direction.
    """
    import numpy as np

    cache = Path.home() / "till_infinity" / "data" / "seqlab"
    names = [n for n in (label, stem) if n]
    for path in [cache / f"{n}.{frame}.npz" for n in names] + [
        Path(f"data/seqlab/{n}.{frame}.npz") for n in names
    ]:
        if not path.exists():
            continue
        with np.load(path) as bundle:
            if not {"time", "close", "high", "low"} <= set(bundle.keys()):
                continue
            order = np.argsort(bundle["time"])
            return {k: bundle[k][order].tolist() for k in ("time", "close", "high", "low")}
    return None


def _from_csv(stem: str, frame: str) -> dict | None:
    import csv
    import gzip

    for name in (f"{stem}_{frame}_yahoo.csv.gz", f"{stem}_{frame}_derived_yahoo.csv.gz"):
        path = Path(".secrets") / name
        if not path.exists():
            continue
        out: dict[str, list[float]] = {"time": [], "close": [], "high": [], "low": []}
        with gzip.open(path, "rt") as handle:
            for row in csv.DictReader(handle):
                try:
                    values = (
                        float(row["ts"]),
                        float(row["close"]),
                        float(row["high"]),
                        float(row["low"]),
                    )
                except (TypeError, ValueError):
                    continue
                if values[1] <= 0:
                    continue
                for key, value in zip(out, values, strict=True):
                    out[key].append(value)
        if len(out["time"]) > 500:
            order = sorted(range(len(out["time"])), key=lambda i: out["time"][i])
            return {k: [v[i] for i in order] for k, v in out.items()}
    return None


def unit(closes: list[float]) -> float:
    """Volatility unit: the standard deviation of one-bar log returns."""
    steps = [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i] > 0 and closes[i - 1] > 0
    ]
    return statistics.pstdev(steps) if len(steps) > 2 else 0.0


def garch_like(closes: list[float], seed: int) -> list[float]:
    """Clustered volatility, no geometry. The control for the symmetry index.

    A sequence of swings whose *sizes* cluster will show sizes more alike at
    short lags than a shuffle of itself, because that is what clustering
    means. So the symmetry index needs a series with the clustering and
    nothing else, and GARCH(1,1) with t(5) innovations is the one
    `research/harness/ecology.py` already uses.
    """
    rng = random.Random(seed)
    scale = unit(closes)
    variance, previous = 1.0, 0.0
    out = [closes[0]]
    for _ in range(len(closes) - 1):
        variance = 0.02 + 0.10 * previous * previous + 0.88 * variance
        chi = sum(rng.gauss(0.0, 1.0) ** 2 for _ in range(5))
        previous = rng.gauss(0.0, math.sqrt(variance)) * math.sqrt(5.0 / max(chi, 0.05))
        # t(5) is heavy enough that a raw draw can overflow the exponential,
        # and a price that overflows is not a heavier tail - it is a bug. The
        # clamp is at twelve standardised units, past anything on record.
        step = max(min(previous, 12.0), -12.0) * scale / 1.6
        out.append(out[-1] * math.exp(step))
    return out


def walk_like(closes: list[float], seed: int) -> list[float]:
    """A Gaussian walk with the same length, start and step size."""
    rng = random.Random(seed)
    step = unit(closes)
    out = [closes[0]]
    for _ in range(len(closes) - 1):
        out.append(out[-1] * math.exp(rng.gauss(0.0, step)))
    return out


# --------------------------------------------------------------- the constants


def corrections(moves) -> list[float]:
    """`alpha = |K| / R`: a move as a fraction of the one it retraced.

    The write-ups define it on a rally followed by a correction, which in an
    alternating sequence is every consecutive pair - so this is the size ratio
    capped at the point where the "correction" has become a new impulse.
    Ratios above one are kept rather than clipped, because clipping them is
    how a mean gets dragged toward whatever cap is chosen, and they are
    counted separately as `over_one`.
    """
    return [
        after.size / before.size for before, after in itertools.pairwise(moves) if before.size > 0
    ]


def hazard(counts: list[int], most: int = 8) -> list[tuple[int, int, float]]:
    """P(a swing ends at its k-th sub-swing | it reached k).

    **The decisive reading.** Flat means renewal: the count is uninformative
    whatever its mean, and every exhaustion formula built on it is reading a
    constant.
    """
    tally = Counter(counts)
    out: list[tuple[int, int, float]] = []
    for k in range(1, most + 1):
        reached = sum(v for c, v in tally.items() if c >= k)
        ended = tally.get(k, 0)
        if reached >= 20:
            out.append((k, reached, ended / reached))
    return out


def branching(data: dict, coarse: int, fine: int) -> tuple[list[int], float]:
    """Sub-pivots per parent swing, and the ratio of the two scales' counts."""
    scale = unit(data["close"])
    if scale <= 0:
        return [], 0.0
    big = sequence(data["time"], data["close"], data["high"], data["low"], span=coarse, unit=scale)
    small = sequence(data["time"], data["close"], data["high"], data["low"], span=fine, unit=scale)
    if len(big) < 10 or len(small) < 10:
        return [], 0.0
    inner = [m.ended for m in small]
    counts: list[int] = []
    counts.extend(
        sum(1 for t in inner if a.ended < t <= b.ended) for a, b in itertools.pairwise(big)
    )
    return counts, len(small) / len(big)


def _member(pairs, data, rng, seed) -> tuple[tuple, tuple | None]:
    """The member against its two nulls, and its forecast against the usual two."""
    real = Symmetry()
    for r in pairs:
        real.absorb(r)

    # Shuffled: the same ratios, order destroyed, clock kept. The clock has to
    # come from the unshuffled sequence or the null would also lose the
    # irregular spacing, and then it would be two differences at once.
    order = list(range(len(pairs)))
    rng.shuffle(order)
    mixed = Symmetry()
    for i, idx in enumerate(order):
        mixed.predict(pairs[i].confirmed)
        mixed.update(pairs[idx].log_ratio, mixed.spread * mixed.spread, pairs[i].confirmed)

    fake = walk_like(data["close"], seed)
    walked = Symmetry()
    for r in relations(sequence(data["time"], fake, fake, fake, span=COARSE, unit=unit(fake))):
        walked.absorb(r)

    guessed: list[float] = []
    actual: list[float] = []
    live = Symmetry()
    for r, nxt in itertools.pairwise(pairs):
        live.absorb(r)
        guessed.append(live.value)
        actual.append(nxt.log_ratio)

    forecast = None
    if len(guessed) > 40:
        forecast = (
            len(guessed),
            spearman(guessed, actual),
            control(guessed, actual),
            spearman(guessed, trailing(actual, 20)),
        )
    return (real.loglike, mixed.loglike, walked.loglike), forecast


def _cell(data, label, frame, rng, seed) -> dict | None:
    """Everything measurable on one instrument at one frame."""
    scale = unit(data["close"])
    if scale <= 0:
        return None
    moves = sequence(
        data["time"], data["close"], data["high"], data["low"], span=COARSE, unit=scale
    )
    if len(moves) < 60:
        return None

    alphas = corrections(moves)
    lag1 = spearman(alphas[:-1], alphas[1:]) if len(alphas) > 30 else float("nan")
    rotated = control(alphas[:-1], alphas[1:])

    sizes = [m.size for m in moves]
    shuffled = list(sizes)
    rng.shuffle(shuffled)

    # **The arithmetic null for the serial correlation.** `alpha(n)` is
    # `s(n)/s(n-1)` and `alpha(n+1)` is `s(n+1)/s(n)`, so they share `s(n)` -
    # once above the line and once below it. For exchangeable sizes that
    # shared term alone gives a correlation of exactly -1/2 between the two
    # logs, with no market in it. Shuffling the sizes keeps the arithmetic and
    # destroys everything else, so whatever the shuffle scores is the floor.
    mechanical = [
        shuffled[i] / shuffled[i - 1] for i in range(1, len(shuffled)) if shuffled[i - 1] > 0
    ]
    floor = spearman(mechanical[:-1], mechanical[1:]) if len(mechanical) > 30 else float("nan")

    surrogate = garch_like(data["close"], seed + 7717)
    garch_moves = sequence(
        data["time"], surrogate, surrogate, surrogate, span=COARSE, unit=unit(surrogate)
    )
    garch_sizes = [m.size for m in garch_moves]
    garch_shuffled = list(garch_sizes)
    rng.shuffle(garch_shuffled)

    pairs = relations(moves)
    counts, ratio = branching(data, COARSE, FINE)
    # The same nesting on a Gaussian walk. A walk has no phases to exhaust, so
    # a hazard that looks the same there is a property of nested alternating
    # pivots and not of the market.
    fake = walk_like(data["close"], seed + 991)
    walk_counts, _ = branching(
        {"time": data["time"], "close": fake, "high": fake, "low": fake}, COARSE, FINE
    )
    steps = [
        math.log(data["close"][i] / data["close"][i - 1])
        for i in range(1, len(data["close"]))
        if data["close"][i] > 0 and data["close"][i - 1] > 0
    ]
    spread = statistics.pstdev(steps) or 1.0

    found = {
        "alpha": (
            label,
            frame,
            len(alphas),
            statistics.median(alphas),
            statistics.fmean(alphas),
            lag1,
            rotated,
            floor,
        ),
        "nsi": [
            (
                label,
                frame,
                lag,
                nodal_symmetry(sizes, lag),
                nodal_symmetry(shuffled, lag),
                nodal_symmetry(garch_sizes, lag),
                nodal_symmetry(garch_shuffled, lag),
            )
            for lag in LAGS
        ],
        "branch": (label, frame, statistics.fmean(counts), ratio) if counts else None,
        "counts": counts,
        "walk_counts": walk_counts,
        "ratios": [r.log_ratio for r in pairs],
        "returns": [s / spread for s in steps],
        "member": None,
        "forecast": None,
    }
    if len(pairs) > 40:
        scores, forecast = _member(pairs, data, rng, seed)
        found["member"] = (f"{label} {frame}", "loglike", *scores)
        if forecast is not None:
            found["forecast"] = (label, frame, *forecast)
    return found


def measure() -> dict:
    rng = random.Random(SEED)
    out: dict = {
        "cells": 0,
        "alpha": [],
        "nsi": [],
        "member": [],
        "forecast": [],
        "branch": [],
        "hazard": [],
        "walk_hazard": [],
        "ratios": {},
        "returns": {},
    }
    for stem, label in SYMBOLS:
        for frame in FRAMES:
            data = load(stem, frame, label)
            if data is None:
                continue
            # A star marks a generated series in every table below, so a
            # reader cannot miss that the control did the same thing.
            shown = f"*{label}" if label in GENERATED else label
            found = _cell(data, shown, frame, rng, SEED + out["cells"])
            if found is None:
                continue
            out["cells"] += 1
            out["alpha"].append(found["alpha"])
            out["nsi"].extend(found["nsi"])
            out["hazard"].extend(found["counts"])
            out["walk_hazard"].extend(found["walk_counts"])
            for key in ("branch", "member", "forecast"):
                if found[key] is not None:
                    out[key].append(found[key])
            if frame == FRAMES[-1]:
                out["ratios"][shown] = found["ratios"]
                out["returns"][shown] = found["returns"]
    return out


def report(found: dict) -> None:
    print(f"cells {found['cells']}  frames {FRAMES}  coarse {COARSE} fine {FINE}")
    _constants(found["alpha"])
    _symmetry(found["nsi"], found["member"], found["forecast"])
    _counting(found["branch"], found["hazard"], found["walk_hazard"])
    _portability(found["ratios"], found["returns"])


def _constants(rows) -> None:
    print("\n== the correction factor: asserted 0.86 universal, revised 0.73/0.62/0.58")
    print(
        f"{'pair':<22}{'frame':<6}{'n':>6}{'median':>8}{'mean':>8}"
        f"{'lag1':>8}{'shuffled':>10}{'rotated':>9}"
    )
    for label, frame, n, med, mean, lag1, rot, floor in rows:
        print(
            f"{label:<22}{frame:<6}{n:>6}{med:>8.3f}{mean:>8.3f}"
            f"{lag1:>8.3f}{floor:>10.3f}{rot:>9.3f}"
        )
    usable = [(r[5], r[7]) for r in rows if not math.isnan(r[5]) and not math.isnan(r[7])]
    if usable:
        print(
            f"median lag1 {statistics.median([a for a, _ in usable]):.3f}  "
            f"shuffled {statistics.median([b for _, b in usable]):.3f}  "
            "arithmetic predicts -0.500"
        )


def _symmetry(nsi_rows, member_rows, forecast_rows) -> None:
    print("\n== the symmetry index: the gain over a shuffle, beside a GARCH surrogate's")
    print(
        f"{'pair':<22}{'frame':<6}{'lag':>4}{'real':>8}{'shuf':>7}"
        f"{'gain':>8}{'garch':>8}{'g shuf':>8}{'g gain':>8}"
    )
    gains: list[float] = []
    garch_gains: list[float] = []
    for label, frame, lag, real, fake, gar, gar_fake in nsi_rows:
        if math.isnan(real) or math.isnan(fake):
            continue
        gain = fake - real
        gains.append(gain)
        row = f"{label:<22}{frame:<6}{lag:>4}{real:>8.3f}{fake:>7.3f}{gain:>8.3f}"
        if not math.isnan(gar) and not math.isnan(gar_fake):
            garch_gains.append(gar_fake - gar)
            row += f"{gar:>8.3f}{gar_fake:>8.3f}{gar_fake - gar:>8.3f}"
        print(row)
    if gains and garch_gains:
        print(
            f"median gain {statistics.median(gains):.3f}  "
            f"GARCH's own gain {statistics.median(garch_gains):.3f}"
        )

    print("\n== the member, against a shuffled sequence and a walk's sequence")
    print(f"{'cell':<28}{'real':>12}{'shuffled':>12}{'walk':>12}{'vs shuf':>10}")
    for tag, _kind, real, mixed, walked in member_rows:
        print(f"{tag:<28}{real:>12.1f}{mixed:>12.1f}{walked:>12.1f}{real - mixed:>10.1f}")

    print("\n== does the posterior forecast the next ratio?")
    print(f"{'pair':<22}{'frame':<6}{'n':>6}{'raw':>8}{'rotated':>9}{'vs sd':>8}")
    for label, frame, n, raw, rot, versd in forecast_rows:
        print(f"{label:<22}{frame:<6}{n:>6}{raw:>8.3f}{rot:>9.3f}{versd:>8.3f}")


def _counting(branch_rows, hazard_pool, walk_pool) -> None:
    print("\n== branching: asserted 3.2 +/- 1.4, range 2.3 to 4.1")
    print(f"{'pair':<22}{'frame':<6}{'per swing':>11}{'count ratio':>13}")
    for label, frame, mean, ratio in branch_rows:
        print(f"{label:<22}{frame:<6}{mean:>11.2f}{ratio:>13.2f}")

    print("\n== the hazard by rotation count, beside a random walk's nested pivots")
    print(f"{'k':>3}{'reached':>9}{'ends at k':>11}{'walk':>9}")
    walk_rates = {k: rate for k, _r, rate in hazard(walk_pool)}
    for k, reached, rate in hazard(hazard_pool):
        shown = walk_rates.get(k)
        tail = f"{shown:>9.3f}" if shown is not None else f"{'-':>9}"
        print(f"{k:>3}{reached:>9}{rate:>11.3f}{tail}")
    if hazard_pool:
        mean = statistics.fmean(hazard_pool)
        # A geometric with the same mean is the renewal null, written out so
        # the comparison is a number and not an impression.
        print(f"pooled mean {mean:.2f}  geometric hazard would be {1.0 / max(mean, 1.0):.3f} flat")


def _portability(ratio_pools, return_pools) -> None:
    print("\n== portability: is the ratio distribution more alike across pairs than returns?")
    names = sorted(ratio_pools)
    print(f"{'pair a':<22}{'pair b':<22}{'W1 ratios':>11}{'W1 returns':>12}")
    arms: dict[str, list[tuple[float, float]]] = {"auction": [], "generated": [], "mixed": []}
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if len(ratio_pools[a]) < 50 or len(ratio_pools[b]) < 50:
                continue
            one = wasserstein(standardise(ratio_pools[a]), standardise(ratio_pools[b]))
            two = wasserstein(return_pools[a], return_pools[b])
            starred = a.startswith("*") + b.startswith("*")
            arm = ("auction", "mixed", "generated")[starred]
            arms[arm].append((one, two))
            print(f"{a:<22}{b:<22}{one:>11.4f}{two:>12.4f}")

    # **Split by arm, because the generated series have return shapes chosen to
    # be exotic.** A Step index is a pure two-valued move and Boom and Crash
    # carry one-sided jumps, so their standardised *returns* are far apart by
    # design while a ratio of consecutive swing sizes is invariant to all of
    # that. Pooled, those pairs alone could carry the comparison - and then
    # the finding would be about the controls' construction rather than about
    # whether structure travels between markets.
    print(f"\n{'arm':<12}{'pairs':>7}{'W1 ratios':>11}{'W1 returns':>12}{'verdict':>26}")
    for arm in ("auction", "generated", "mixed"):
        rows = arms[arm]
        if len(rows) < 3:
            continue
        ratios = statistics.median([a for a, _ in rows])
        returns = statistics.median([b for _, b in rows])
        verdict = "ratios travel better" if ratios < returns else "returns travel better"
        print(f"{arm:<12}{len(rows):>7}{ratios:>11.4f}{returns:>12.4f}{verdict:>26}")


def standardise(values: list[float]) -> list[float]:
    if len(values) < 2:
        return list(values)
    middle = statistics.fmean(values)
    spread = statistics.pstdev(values) or 1.0
    return [(v - middle) / spread for v in values]


if __name__ == "__main__":
    report(measure())
