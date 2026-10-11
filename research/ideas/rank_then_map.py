"""Does rank-then-map actually transfer? Leave one instrument out.

Scores `statespace/ranking.py` against the three nulls that matter, on the
evaluation the paper itself uses: **condition-disjoint folds**. The ranker is
trained on four instruments and asked about the fifth, which it has never seen,
with a handful of anchors from that fifth instrument's own training period to
set the scale. That is the transferability claim, and it is the only evaluation
in which "predict the order" can beat "predict the value" rather than merely
restate it.

The target is the **magnitude** of the next move. Direction is not tested here
because `research/docs/informatory-pairs.md` established there is no ordering of
it to learn: at most 6 of 45 bin pairs could be ordered by their mean signed
outcome at two standard errors.

## The three nulls

1. **A trailing standard deviation.** The hard one. It has beaten a three-state
   HMM, a fifty-neighbour analogue on 0 of 20 cells, an Ising susceptibility,
   and a panel of stale forecasts, and it reads rho +0.158 on this target.
2. **A per-instrument ranker**, trained only on the held-out instrument's own
   training period. The informatory-pairs test predicts this buys nothing;
   this is the test of that prediction.
3. **One step**, least squares straight onto the value. If predicting the
   quantity directly does as well, the disentangling bought nothing and the
   extra machinery is not earned.

## Causality

Features at bar `i` use data up to `i`; the target is the move after it. The
split is by **time**: the ranker trains on the first `SHARE` of every training
instrument, the anchors come from the held-out instrument's *training* period,
and everything is scored on its later period. Rows are stepped by the longer of
the feature window and the horizon so no two share an outcome.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.structures.statespace.inputs import bar_hours, coverage
from till_infinity.structures.statespace.ranking import Ranker, RankThenMap

HOUR = 3600.0

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
)
FRAMES = ("15m", "1h")

#: Feature windows in hours. The ladder the features are built on.
WINDOWS = (1.0, 4.0, 24.0)

#: Horizons in hours.
HORIZONS = (4.0, 24.0)

#: Share of each series used for training. The rest is held out.
SHARE = 0.6

#: Anchors taken from the held-out instrument's training period. A handful, as
#: the paper uses - the point is that arriving somewhere new is cheap.
ANCHORS = 30

SINCE = float(os.environ.get("SINCE", "1262304000"))  # 2010-01-01
LIMIT = int(os.environ.get("LIMIT", "20000"))


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = bundle["time"][order].tolist()
        closes = bundle["close"][order].tolist()
    first = 0
    while first < len(times) and times[first] < SINCE:
        first += 1
    times, closes = times[first:], closes[first:]
    if len(closes) > LIMIT:
        times, closes = times[-LIMIT:], closes[-LIMIT:]
    return times, closes


def logs(prices: list[float]) -> list[float]:
    out, running = [0.0], 0.0
    for i in range(1, len(prices)):
        if prices[i] > 0 and prices[i - 1] > 0:
            running += math.log(prices[i] / prices[i - 1]) * 10_000
        out.append(running)
    return out


def per_root_hour(values: list[float], bar: float) -> float:
    alpha = 1.0 - 0.5 ** (1.0 / 60.0)
    average = 0.0
    for i in range(1, len(values)):
        move = abs(values[i] - values[i - 1])
        average = move if i == 1 else average + alpha * (move - average)
    return max(average, 1e-9) / math.sqrt(max(bar, 1e-9))


def trailing(values: list[float], span: int) -> list[float]:
    out = [0.0] * len(values)
    steps = [0.0] + [values[i] - values[i - 1] for i in range(1, len(values))]
    run = runsq = 0.0
    for i in range(1, len(values)):
        run += steps[i]
        runsq += steps[i] * steps[i]
        if i > span:
            run -= steps[i - span]
            runsq -= steps[i - span] * steps[i - span]
        count = min(i, span)
        if count >= 2:
            mean = run / count
            out[i] = math.sqrt(max(runsq / count - mean * mean, 0.0))
    return out


NAMES = (
    "cum1h",
    "cum4h",
    "cum24h",
    "sd1h",
    "sd4h",
    "sd24h",
    "quiet",
    "mid",
    "fast",
    "asia",
    "london",
    "newyork",
)


def build(stem: str, frame: str, horizon: float):
    """Rows of `(features, |move| as a z, raw |move|, trailing sd)`.

    **Two targets, and the first run of this harness had only one.** The ranker
    is trained by comparing pairs, and pooling four instruments means comparing
    gold's move against the euro's - so a target in basis points makes the
    comparison mostly "which instrument is this", which is not in the features
    and cannot be learned. The global ranker duly scored +0.05 against +0.22 for
    one trained on a single instrument, which looked like the transferability
    claim failing and was the target not being comparable.

    So ranking uses `|move| / (unit * sqrt(horizon))`, a z, which is the same
    quantity on every series - and the raw value is kept for the mapping step,
    whose entire job is to put the instrument's own scale back.

    Every feature is a `z` or an indicator, so a weight learned on gold means
    the same thing on the euro - which is the precondition for one model
    spanning them, and the thing `informatory-pairs.md` measured before this
    was written.
    """
    got = load(stem, frame)
    if got is None or len(got[1]) < 3000:
        return []
    times, closes = got
    bar = bar_hours(times)
    if bar <= 0:
        return []
    cover = coverage(times, bar)
    values = logs(closes)
    unit = per_root_hour(values, bar)
    spans = {w: max(round(w * cover / bar), 2) for w in WINDOWS}
    sds = {w: trailing(values, spans[w]) for w in WINDOWS}
    ahead = max(round(horizon * cover / bar), 1)
    widest = max(spans.values())
    stride = max(widest, ahead)

    # Volatility terciles, within this series, from its own training period so
    # the cut is not set by data the model has not earned.
    reference = sorted(v for v in sds[WINDOWS[1]][: int(len(values) * SHARE)] if v > 0)
    if len(reference) < 100:
        return []
    low = reference[len(reference) // 3]
    high = reference[2 * len(reference) // 3]

    rows = []
    for i in range(stride, len(values) - ahead, stride):
        here = sds[WINDOWS[1]][i]
        if here <= 0:
            continue
        features = [(values[i] - values[i - spans[w]]) / (unit * math.sqrt(w)) for w in WINDOWS]
        features.extend(sds[w][i] / (unit * math.sqrt(bar)) for w in WINDOWS)
        features.extend(
            [
                1.0 if here < low else 0.0,
                1.0 if low <= here < high else 0.0,
                1.0 if here >= high else 0.0,
            ]
        )
        hour = int((times[i] % 86400) // 3600)
        features.extend(
            [
                1.0 if hour < 7 else 0.0,
                1.0 if 7 <= hour < 13 else 0.0,
                1.0 if hour >= 13 else 0.0,
            ]
        )
        move = abs(values[i + ahead] - values[i])
        rows.append((features, move / (unit * math.sqrt(horizon)), move, here))
    return rows


def spearman(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 30:
        return float("nan")

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        for rank, i in enumerate(order):
            out[i] = float(rank)
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den > 0 else float("nan")


def one_step(rows: list[tuple]) -> list[float]:
    """Least squares straight onto the value. Null three."""
    size = len(rows[0][0])
    matrix = [[0.0] * (size + 1) for _ in range(size)]
    for features, _z, value, _sd in rows:
        for a in range(size):
            for b in range(size):
                matrix[a][b] += features[a] * features[b]
            matrix[a][size] += features[a] * value
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(matrix[r][col]))
        if abs(matrix[pivot][col]) < 1e-10:
            return [0.0] * size
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        for row in range(size):
            if row == col:
                continue
            factor = matrix[row][col] / matrix[col][col]
            for k in range(col, size + 1):
                matrix[row][k] -= factor * matrix[col][k]
    return [matrix[i][size] / matrix[i][i] for i in range(size)]


def fold(held: str, pools: dict) -> str | None:
    """One leave-one-instrument-out fold, as a printable row."""
    rows = pools[held]
    cut = int(len(rows) * SHARE)
    train_rows = [
        r for name, got in pools.items() if name != held for r in got[: int(len(got) * SHARE)]
    ]
    own_train, test = rows[:cut], rows[cut:]
    if len(test) < 200 or len(train_rows) < 1000:
        return None

    # The global ranker: four instruments, never the fifth. The margin stands
    # in for the cost threshold the paper puts inside the loss.
    glob = Ranker(margin=0.1)
    # **Ranking trains on the z, mapping calibrates on the raw value.** The
    # first run trained on basis points, so pooling four instruments asked the
    # ranker to compare gold's move with the euro's.
    glob.fit([(f, z) for f, z, _r, _s in train_rows], epochs=2, pairs=30_000, seed=7)
    own = Ranker(margin=0.1)
    own.fit([(f, z) for f, z, _r, _s in own_train], epochs=2, pairs=30_000, seed=7)
    weights = one_step(train_rows)

    truth = [r for _f, _z, r, _s in test]
    sd = [s for _f, _z, _r, s in test]
    scores = [glob.score(f) for f, _z, _r, _s in test]
    mine = [own.score(f) for f, _z, _r, _s in test]
    direct = [sum(w * x for w, x in zip(weights, f, strict=True)) for f, _z, _r, _s in test]

    model = RankThenMap(ranker=glob)
    step = max(len(own_train) // ANCHORS, 1)
    anchors = own_train[::step][:ANCHORS]
    model.anchor([(f, r) for f, _z, r, _s in anchors])
    mapped = [model.predict(f) for f, _z, _r, _s in test]
    mae = statistics.fmean(abs(a - b) for a, b in zip(mapped, truth, strict=True))
    sd_mae = calibrated(anchors, sd, truth)

    return (
        f"  {held:<10}{len(test):>8}{spearman(scores, truth):>+9.3f}"
        f"{spearman(mine, truth):>+10.3f}{spearman(direct, truth):>+10.3f}"
        f"{spearman(sd, truth):>+9.3f}{mae:>12.3f}{sd_mae:>9.3f}"
    )


def calibrated(anchors: list[tuple], sd: list[float], truth: list[float]) -> float:
    """The sd null's mean absolute error, given the same anchors to scale on.

    Comparing a mapped quantity against a raw standard deviation on MAE would
    be comparing units, so the null gets the same courtesy the model gets: a
    gain and an offset from the same handful of anchors.
    """
    xs = [s for _f, _z, _r, s in anchors]
    ys = [r for _f, _z, r, _s in anchors]
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    var = sum((x - mean_x) ** 2 for x in xs)
    gain = (
        sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / var
        if var > 0
        else 0.0
    )
    return statistics.fmean(
        abs(mean_y + gain * (x - mean_x) - y) for x, y in zip(sd, truth, strict=True)
    )


def main() -> None:
    print("Rank-then-map, scored leave-one-instrument-out.")
    print("The ranker never sees the held-out instrument. Anchors come from")
    print("its own TRAINING period; everything is scored on its later one.")
    print("'sd' is the trailing standard deviation - the null that has beaten")
    print("every volatility model tried on this desk.\n")

    for horizon in HORIZONS:
        for frame in FRAMES:
            pools = {}
            for label, stem in SYMBOLS:
                rows = build(stem, frame, horizon)
                if len(rows) > 500:
                    pools[label] = rows
            if len(pools) < 3:
                continue
            print(f"=== {frame}, horizon {horizon:g}h ===")
            print(
                f"  {'held out':<10}{'n test':>8}{'GLOBAL':>9}{'per-inst':>10}"
                f"{'one-step':>10}{'sd null':>9}{'mapped MAE':>12}{'sd MAE':>9}"
            )
            for held in pools:
                line = fold(held, pools)
                if line:
                    print(line)
            print()

    print("Reading it:")
    print("  GLOBAL is the ranker trained on the OTHER four instruments.")
    print("  per-inst is the same thing trained only on this one, which the")
    print("  informatory-pairs test predicted would buy nothing.")
    print("  one-step predicts the value directly; if it ties, the two-step")
    print("  machinery is not earned.")
    print("  sd null is the trailing standard deviation. Nothing here is worth")
    print("  anything unless it beats that column.")


if __name__ == "__main__":
    main()
