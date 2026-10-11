"""How many orderings actually change between conditions? The pre-test.

From Kretschmer et al., *Times are changing but order matters* (Nature Methods,
2026), adapted. Predicting chromatographic retention times across laboratories,
they ask a question before building anything: for each **pair** of compounds,
does their retention *order* ever change between chromatographic systems? The
answer is that 93.8% of pairs never change order, so only 6.16% of pairs can
carry any information about the system at all - and a condition-aware model
cannot beat a condition-agnostic one on the rest, which is knowable without
training either.

This desk has several open ideas that condition on something: regime-gated
execution, per-instrument models, session-aware thresholds, volatility-regime
splits. **All of them are bets that orderings change between conditions**, and
that bet is testable directly, cheaply, with no model.

## The design

An "item" here is a **bin of a feature**, because our features are continuous
and no single observation recurs under two conditions. Bins are deciles of the
pooled distribution, so a bin means the same thing in every condition. The
"retention time" is the mean outcome in that bin, and the "chromatographic
system" is one of five condition types:

* **instrument** - does the feature-to-outcome map transfer across symbols?
  This is the closest analogue to the paper's own question, and it is the one
  that decides whether the rank-then-map architecture is viable at all.
* **timeframe** - the same question across resolutions.
* **volatility regime** - terciles of the trailing standard deviation.
* **session** - Asia, London, New York by UTC hour.
* **era** - first against second half of the sample, which is the
  non-stationarity question rather than a regime one.

## The control, without which this measures nothing

Orderings also flip because the estimates are noisy, and with enough noise
everything looks informatory. So two guards:

1. **A threshold on the pair.** The paper compares only compounds whose
   retention times differ by more than ten seconds - closer than that and the
   comparison is of measurement error. Here a pair counts as *resolved* in a
   condition only when the two bin means differ by more than `SIGMAS` standard
   errors of their difference.
2. **A matched noise baseline.** The same computation with the conditions
   replaced by **random halves of the same data**, which have no condition
   difference by construction. Whatever flip rate that produces is the floor.

The informatory share is the excess of the first over the second. If a condition
type comes back at its own noise baseline, conditioning on it buys nothing, and
every idea resting on it is already answered.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from pathlib import Path

from till_infinity.structures.statespace.inputs import bar_hours, coverage

HOUR = 3600.0

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
)
FRAMES = ("15m", "1h")

#: Feature windows and forecast horizons, in hours.
WINDOWS = (1.0, 4.0, 24.0)
HORIZONS = (4.0, 24.0)

#: Bins of the pooled feature distribution. Ten, like the paper's compounds,
#: gives 45 pairs - enough to be a rate rather than an anecdote.
BINS = 10

#: A pair is **resolved** in a condition only when its two bin means differ by
#: more than this many standard errors of the difference. Below it the
#: comparison is of estimation error, which is the paper's ten-second rule.
SIGMAS = 2.0

#: Fewest observations in a bin before its mean is used at all.
LEAST = 50

#: Fewest **resolved pairs** before a share is printed as a number. A share of
#: one pair is not a weak measurement, it is one pair, and the first run of this
#: harness duly printed "100.0% informatory" off a single resolved comparison -
#: the same shape `slope_fade.py` produced with a `t` on ten points.
LEAST_PAIRS = 8

#: Provenance filter, as in `slope_fade.py`: the daily and 4h FX files reach
#: back to 1971, decades before the instruments existed.
SINCE = float(os.environ.get("SINCE", "1262304000"))  # 2010-01-01

LIMIT = int(os.environ.get("LIMIT", "20000"))

SEED = 20261011


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


def rows_for(label: str, stem: str, frame: str, window: float, horizon: float):
    """Independent rows of `(feature, signed, size, conditions...)`."""
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
    span = max(round(window * cover / bar), 2)
    ahead = max(round(horizon * cover / bar), 1)
    sd = trailing(values, span)
    stride = max(span, ahead)

    out = []
    for i in range(stride, len(values) - ahead, stride):
        if sd[i] <= 0:
            continue
        # The feature: the cumsum over the window, as a z. Scale-free, so the
        # bins mean the same thing on gold and on the euro.
        feature = (values[i] - values[i - span]) / (unit * math.sqrt(window))
        move = values[i + ahead] - values[i]
        hour = int((times[i] % 86400) // 3600)
        session = "asia" if hour < 7 else ("london" if hour < 13 else "newyork")
        out.append(
            {
                "feature": feature,
                "signed": move,
                "size": abs(move),
                "instrument": label,
                "timeframe": frame,
                "session": session,
                "sd": sd[i],
                "when": times[i],
            }
        )
    return out


def tag_regimes(rows: list[dict]) -> None:
    """Volatility terciles and era, assigned within each instrument+timeframe.

    **Within**, not pooled: a tercile of the pooled standard deviation would be
    mostly a label for which instrument a row came from, and the question here
    is whether the *regime* changes the ordering, not whether gold differs from
    the euro - which the `instrument` condition asks separately.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["instrument"], row["timeframe"]), []).append(row)
    for members in groups.values():
        order = sorted(members, key=lambda r: r["sd"])
        third = max(len(order) // 3, 1)
        for k, row in enumerate(order):
            row["volatility"] = "quiet" if k < third else ("mid" if k < 2 * third else "fast")
        by_time = sorted(members, key=lambda r: r["when"])
        half = len(by_time) // 2
        for k, row in enumerate(by_time):
            row["era"] = "early" if k < half else "late"


def edges(values: list[float]) -> list[float]:
    """Decile boundaries of the pooled feature distribution."""
    ordered = sorted(values)
    return [ordered[int(len(ordered) * k / BINS)] for k in range(1, BINS)]


def place(value: float, bounds: list[float]) -> int:
    lo, hi = 0, len(bounds)
    while lo < hi:
        mid = (lo + hi) // 2
        if value >= bounds[mid]:
            lo = mid + 1
        else:
            hi = mid
    return lo


def summarise(rows: list[dict], bounds: list[float], target: str):
    """`{bin: (mean, standard error)}` for one condition's rows."""
    buckets: dict[int, list[float]] = {}
    for row in rows:
        buckets.setdefault(place(row["feature"], bounds), []).append(row[target])
    out = {}
    for key, got in buckets.items():
        if len(got) < LEAST:
            continue
        spread = statistics.pstdev(got)
        out[key] = (statistics.fmean(got), spread / math.sqrt(len(got)))
    return out


def flips(tables: list[dict[int, tuple[float, float]]]) -> tuple[int, int]:
    """`(informatory, resolved)` pairs across a list of per-condition tables.

    A pair is **resolved** when at least two conditions separate its two bins by
    more than `SIGMAS` standard errors; it is **informatory** when those
    resolved conditions do not agree on the order. Unresolved pairs are counted
    in neither, because a pair nobody can order says nothing about conditions.
    """
    informatory = resolved = 0
    for first in range(BINS):
        for second in range(first + 1, BINS):
            signs = []
            for table in tables:
                if first not in table or second not in table:
                    continue
                (mean_a, se_a), (mean_b, se_b) = table[first], table[second]
                gap = mean_a - mean_b
                spread = math.sqrt(se_a * se_a + se_b * se_b)
                if spread <= 0 or abs(gap) < SIGMAS * spread:
                    continue
                signs.append(1 if gap > 0 else -1)
            if len(signs) < 2:
                continue
            resolved += 1
            if len(set(signs)) > 1:
                informatory += 1
    return informatory, resolved


def baseline(rows: list[dict], bounds: list[float], target: str, parts: int):
    """The same count with conditions replaced by random splits of one pool.

    This is the floor. Any flip rate at or below it is estimation noise, and a
    condition type that does not clear it is a condition the data cannot see.
    """
    rng = random.Random(SEED)
    shuffled = list(rows)
    rng.shuffle(shuffled)
    chunk = len(shuffled) // parts
    tables = [
        summarise(shuffled[k * chunk : (k + 1) * chunk], bounds, target) for k in range(parts)
    ]
    return flips(tables)


def main() -> None:
    print("How many orderings change between conditions? The pre-test.")
    print(f"Feature: the cumsum z over the window. {BINS} bins, {BINS * (BINS - 1) // 2} pairs.")
    print(f"A pair is resolved at {SIGMAS:g} standard errors; below that the")
    print("comparison is of estimation error, not of the market.")
    print("'noise' is the same count over random splits of one pool, which have")
    print("no condition difference by construction. A condition type at its own")
    print("noise floor is one the data cannot see.\n")

    for window in WINDOWS:
        for horizon in HORIZONS:
            rows: list[dict] = []
            for label, stem in SYMBOLS:
                for frame in FRAMES:
                    rows.extend(rows_for(label, stem, frame, window, horizon))
            if len(rows) < 5000:
                continue
            tag_regimes(rows)
            bounds = edges([r["feature"] for r in rows])

            print(f"=== window {window:g}h, horizon {horizon:g}h, {len(rows)} rows ===")
            # **How many pairs can be ordered at all**, pooled, before any
            # condition is involved. For direction this is the whole story: a
            # map whose bins cannot be put in order is not a map, and no
            # condition can make one informatory.
            total = BINS * (BINS - 1) // 2
            for target in ("signed", "size"):
                whole = summarise(rows, bounds, target)
                _, orderable = flips([whole, whole])
                print(
                    f"  pooled, {target:<7} {orderable}/{total} pairs orderable "
                    f"at {SIGMAS:g} standard errors"
                )
            print(
                f"  {'target':<8}{'condition':<12}{'levels':>7}{'resolved':>10}"
                f"{'informatory':>13}{'noise':>9}{'excess':>9}"
            )
            for target in ("signed", "size"):
                for condition in ("instrument", "timeframe", "volatility", "session", "era"):
                    groups: dict[str, list[dict]] = {}
                    for row in rows:
                        groups.setdefault(row[condition], []).append(row)
                    if len(groups) < 2:
                        continue
                    tables = [summarise(got, bounds, target) for got in groups.values()]
                    informatory, resolved = flips(tables)
                    if resolved == 0:
                        continue
                    if resolved < LEAST_PAIRS:
                        print(
                            f"  {target:<8}{condition:<12}{len(groups):>7}{resolved:>10}"
                            f"{'too few to read':>31}"
                        )
                        continue
                    noisy, noisy_resolved = baseline(rows, bounds, target, len(groups))
                    share = informatory / resolved
                    floor = noisy / noisy_resolved if noisy_resolved else float("nan")
                    print(
                        f"  {target:<8}{condition:<12}{len(groups):>7}{resolved:>10}"
                        f"{share:>12.1%}{floor:>9.1%}{share - floor:>+9.1%}"
                    )
            print()

    print("Reading it:")
    print("  'resolved' counts pairs at least two conditions could order at all.")
    print("  'informatory' is the share of those whose order DISAGREES between")
    print("  conditions - the only pairs on which a condition-aware model can")
    print("  beat a condition-agnostic one.")
    print("  'excess' over the noise floor is the real quantity. At or below")
    print("  zero, conditioning on that variable buys nothing, and every idea")
    print("  resting on it is answered without training a model.")


if __name__ == "__main__":
    main()
