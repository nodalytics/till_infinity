"""Can a major turn be seen before it happens.

Run from the repository root:  python research/harness/turns.py

[todo.md](../../docs/todo.md) §6a asks for the reversal that matters over weeks,
not the next touch — and asks for the falsification to be written before the
model, because major turns are rare and a dozen observations will produce a
confident-looking number from anything.

## What is being predicted

    On a day when the instrument is in an established uptrend near its highs,
    will it fall by `DROP` of its own daily move units within `HORIZON` days?

Every part of that is deliberate.

**"Near its highs, in an uptrend"** is the universe, and it is what makes this
a question about *turns* rather than about declines. §6a asks whether a signal
"separates it from the far more numerous moments that looked similar and
continued", so the comparison set has to be moments that looked similar. A
model that learns to tell a bull market from a bear market has answered a
different and much easier question.

**Units, not percent.** btc moves 1.48% on a median day and eurusd 0.31%. A
percentage threshold would mean "a routine week" for one and "a generational
move" for the other, and pooling them would be pooling two different questions.

**A forward drawdown, not a zigzag pivot.** A swing pivot is only *confirmed*
some days after the extreme — a median of 29 days at this size — so a model
trained on pivot labels is being asked when a pivot will be confirmed, which is
not the same as when the turn happens. The forward drawdown has no confirmation
lag and no ambiguity about which day the turn "was".

## The refusal, designed first

Three things here manufacture a good-looking answer from nothing, and each has
a guard:

1. **Overlapping windows.** Two days a week apart share 53 of their 60 forward
   days, so 691 positive days are nowhere near 691 observations. Everything is
   counted and resampled in **episodes** — contiguous runs of the label — and
   the bootstrap resamples whole episodes rather than days.
2. **Leakage across the split.** A training day at t and a test day at t+10
   share most of a forward window, so an ordinary walk-forward split leaks the
   answer backwards. Training rows within `HORIZON` days of the test set are
   **purged**.
3. **One instrument carrying it.** Reported leave-one-instrument-out, because
   six instruments over twenty years is not six independent studies but it is
   the only cross-section there is.

If the AUC interval includes 0.5, the answer is no and no amount of model
selection changes that.
"""

from __future__ import annotations

import itertools
import math
import random
import statistics
import sys
import time
from pathlib import Path

import numpy

sys.path.insert(0, str(Path(__file__).parent))
from cycles import daily

#: How far price must fall, in the instrument's own median daily moves, for the
#: turn to count as major. Twenty units is about 11% for the median instrument
#: here — a real reversal rather than a pullback.
DROP = 20.0

#: And within how many trading days.
HORIZON = 60

#: The universe: price within this of its running high, and rising.
HIGH_WINDOW = 250
NEAR_HIGH = 0.03
RISING_OVER = 60

#: Bars of history needed before any feature is well defined.
WARM = 250

#: Resamples for the episode bootstrap.
RESAMPLES = 2000


def units(closes: list[float]) -> float:
    """The instrument's median absolute daily log return."""
    returns = [math.log(b / a) for a, b in itertools.pairwise(closes) if a > 0 and b > 0]
    return statistics.median(abs(r) for r in returns) or 1e-9


def episodes(flags: list[bool]) -> int:
    """Contiguous runs of the label. The sample size that actually counts."""
    return sum(1 for key, _ in itertools.groupby(flags) if key)


def features(closes: list[float], t: int, unit: float) -> dict[str, float]:
    """What is knowable at the close of day `t`, in the instrument's own units.

    Closes only. Highs and lows would add a truer range and are not collected
    into the daily series this reads; that is a collection question, noted in
    the write-up rather than worked around here.
    """
    window = closes[t - HIGH_WINDOW : t + 1]
    high = max(window)
    low = min(window)
    recent = closes[t - 60 : t + 1]

    path = sum(abs(b - a) for a, b in itertools.pairwise(recent))
    net = recent[-1] - recent[0]

    short = [math.log(b / a) for a, b in itertools.pairwise(closes[t - 20 : t + 1]) if a > 0]
    long = [math.log(b / a) for a, b in itertools.pairwise(closes[t - 100 : t + 1]) if a > 0]
    short_vol = statistics.pstdev(short) if len(short) > 1 else 0.0
    long_vol = statistics.pstdev(long) if len(long) > 1 else 0.0

    last_20 = math.log(closes[t] / closes[t - 20])
    prior_20 = math.log(closes[t - 20] / closes[t - 40])

    return {
        # How directional the last quarter was. High means a clean trend.
        "efficiency": abs(net) / path if path else 0.0,
        # How far the trend has carried, and for how long.
        "extension": math.log(closes[t] / closes[t - HIGH_WINDOW]) / unit,
        "off_low": math.log(closes[t] / low) / unit,
        "since_low": (t - (t - HIGH_WINDOW + window.index(low))) / HIGH_WINDOW,
        # Where price sits against its own long mean.
        "above_mean": math.log(closes[t] / statistics.fmean(closes[t - 200 : t])) / unit,
        # How far below the running high — a turn may already be underway.
        "drawdown": math.log(closes[t] / high) / unit,
        # Volatility now, and whether it is expanding.
        "vol": short_vol / unit,
        "vol_ratio": short_vol / long_vol if long_vol else 1.0,
        # Is the push fading.
        "decel": (last_20 - prior_20) / unit,
        "up_days": sum(1 for r in short if r > 0) / len(short) if short else 0.5,
    }


def build() -> list[dict]:
    """Every day in the universe, with its features and its forward label.

    Positive days are grouped into **episodes** as they are built: consecutive
    universe days that are all labelled are one turn seen from several days
    out, not several turns. Everything downstream counts and resamples these.
    """
    series = daily()
    rows: list[dict] = []
    for feed in sorted(series):
        stamps, closes = series[feed]
        unit = units(closes)
        episode = 0
        previous = False
        for t in range(max(WARM, HIGH_WINDOW), len(closes) - HORIZON):
            high = max(closes[t - HIGH_WINDOW : t + 1])
            rising = math.log(closes[t] / closes[t - RISING_OVER]) > 0
            if closes[t] < high * (1 - NEAR_HIGH) or not rising:
                previous = False
                continue
            forward = min(closes[t + 1 : t + HORIZON + 1])
            turned = math.log(forward / closes[t]) <= -DROP * unit
            if turned and not previous:
                episode += 1
            previous = turned
            rows.append(
                {
                    **features(closes, t, unit),
                    "feed": feed,
                    "when": stamps[t],
                    "turned": turned,
                    # Negatives are blocked by feed and calendar quarter, so the
                    # bootstrap resamples correlated stretches of them too
                    # rather than treating every day as independent.
                    "episode": f"{feed}-{episode}"
                    if turned
                    else f"{feed}-q{stamps[t] // (90 * 86400)}",
                }
            )
    rows.sort(key=lambda r: r["when"])
    return rows


def auc(scored: list[tuple[float, bool]]) -> float:
    """Rank AUC, ties sharing the average rank."""
    if not scored:
        return 0.5
    values = numpy.fromiter((s for s, _ in scored), dtype=float, count=len(scored))
    labels = numpy.fromiter((y for _, y in scored), dtype=bool, count=len(scored))
    return _auc(values, labels)


def _auc(values, labels) -> float:
    """The same, on arrays. Called a few million times by the bootstrap.

    In pure Python this was the whole runtime: thirty bootstrap calls, two
    thousand resamples each, a sort of fifteen thousand rows every time. The
    arithmetic is identical — average ranks for ties, Mann-Whitney — and it is
    two orders of magnitude faster, which is the difference between running
    this and not.
    """
    positives = int(labels.sum())
    negatives = labels.size - positives
    if not positives or not negatives:
        return 0.5
    order = numpy.argsort(values, kind="stable")
    ordered = values[order]
    # Average rank within each run of equal scores, or a model that outputs one
    # constant scores something other than 0.5.
    ranks = numpy.empty(ordered.size, dtype=float)
    starts = numpy.flatnonzero(numpy.concatenate(([True], ordered[1:] != ordered[:-1])))
    ends = numpy.append(starts[1:], ordered.size)
    for start, end in zip(starts, ends, strict=True):
        ranks[start:end] = (start + end - 1) / 2 + 1
    total = ranks[labels[order]].sum()
    return float((total - positives * (positives + 1) / 2) / (positives * negatives))


def bootstrap(
    scored: list[tuple[float, bool, str]], resamples: int = RESAMPLES
) -> tuple[float, float]:
    """A 95% interval on AUC, resampling **episodes** rather than days.

    Resampling days would treat two observations a week apart as independent
    when they share 53 of their 60 forward days, and would return an interval
    several times too narrow. What is resampled has to be what is independent,
    and here that is at best the turn.
    """
    grouped: dict[str, list[tuple[float, bool]]] = {}
    for score, label, block in scored:
        grouped.setdefault(block, []).append((score, label))
    keys = list(grouped)
    values = [
        numpy.fromiter((s for s, _ in grouped[k]), dtype=float, count=len(grouped[k])) for k in keys
    ]
    labels = [
        numpy.fromiter((y for _, y in grouped[k]), dtype=bool, count=len(grouped[k])) for k in keys
    ]
    rng = numpy.random.default_rng(7)
    seen = []
    for _ in range(resamples):
        drawn = rng.integers(0, len(keys), len(keys))
        picked_labels = numpy.concatenate([labels[i] for i in drawn])
        hits = int(picked_labels.sum())
        if not hits or hits == picked_labels.size:
            continue
        seen.append(_auc(numpy.concatenate([values[i] for i in drawn]), picked_labels))
    if not seen:
        return 0.0, 1.0
    seen.sort()
    return seen[int(0.025 * len(seen))], seen[int(0.975 * len(seen))]


def fit(train: list[dict], keys: tuple[str, ...]):
    """Logistic regression, trained by several passes over the training rows.

    Batch rather than the online walk-forward the other harnesses use, because
    the split here has to be **purged**: training rows whose forward window
    overlaps the test set have to be removed, and an online model that has
    already seen them cannot unsee them.
    """
    from river import linear_model, optim, preprocessing

    model = preprocessing.StandardScaler() | linear_model.LogisticRegression(
        optimizer=optim.SGD(0.05)
    )
    order = list(train)
    rng = random.Random(11)
    for _ in range(8):
        rng.shuffle(order)
        for row in order:
            model.learn_one({k: row[k] for k in keys}, row["turned"])
    return model


def purged_folds(rows: list[dict], folds: int = 5):
    """Expanding-window splits with the overlap removed.

    A training day at t and a test day at t+10 share most of a forward window,
    so an ordinary time split leaks the answer backwards across the boundary.
    Every training row within `HORIZON` days of the test set is dropped —
    which costs sample and is the only thing that makes the number mean
    anything.
    """
    ordered = sorted(rows, key=lambda r: r["when"])
    size = len(ordered) // (folds + 1)
    gap = HORIZON * 86400
    for k in range(1, folds + 1):
        test = ordered[k * size : (k + 1) * size]
        if not test:
            continue
        opens = test[0]["when"]
        train = [r for r in ordered[: k * size] if r["when"] < opens - gap]
        if train and test:
            yield train, test


KEYS = (
    "efficiency",
    "extension",
    "off_low",
    "since_low",
    "above_mean",
    "drawdown",
    "vol",
    "vol_ratio",
    "decel",
    "up_days",
)


def evaluate(rows: list[dict], keys: tuple[str, ...] = KEYS) -> tuple[float, float, float, int]:
    """Walk-forward AUC over purged folds, with its episode interval."""
    scored: list[tuple[float, bool, str]] = []
    for train, test in purged_folds(rows):
        if len({r["turned"] for r in train}) < 2:
            continue
        model = fit(train, keys)
        for row in test:
            probability = model.predict_proba_one({k: row[k] for k in keys}).get(True, 0.5)
            scored.append((probability, row["turned"], row["episode"]))
    if not scored:
        return 0.5, 0.0, 1.0, 0
    area = auc([(s, y) for s, y, _ in scored])
    lo, hi = bootstrap(scored)
    return area, lo, hi, len({b for _, y, b in scored if y})


def main() -> None:
    rows = build()
    positives = [r for r in rows if r["turned"]]
    turns = {r["episode"] for r in positives}
    print(f"{len(rows):,} days in the universe, {len(positives)} labelled")
    print(f"base rate {len(positives) / len(rows):.1%} of days, but **{len(turns)} turns**\n")

    print("=== 0. the sample, counted in turns rather than days")
    print(f"    {'feed':<10} {'days':>7} {'labelled':>9} {'turns':>7}")
    print("    " + "-" * 36)
    for feed in sorted({r["feed"] for r in rows}):
        mine = [r for r in rows if r["feed"] == feed]
        hit = [r for r in mine if r["turned"]]
        print(f"    {feed:<10} {len(mine):>7} {len(hit):>9} {len({r['episode'] for r in hit}):>7}")

    print("\n=== 1. one signal at a time, ranked by AUC over the whole sample")
    print("    In-sample and unpurged on purpose: this is the most generous")
    print("    reading any of them will get, so a feature flat here is dead.\n")
    print(f"    {'signal':<14} {'AUC':>7} {'95% by episode':>20}")
    print("    " + "-" * 44)
    solo = []
    for key in KEYS:
        area = auc([(r[key], r["turned"]) for r in rows])
        lo, hi = bootstrap([(r[key], r["turned"], r["episode"]) for r in rows], 600)
        solo.append((abs(area - 0.5), key, area, lo, hi))
    for _, key, area, lo, hi in sorted(solo, reverse=True):
        mark = "" if lo <= 0.5 <= hi else " *"
        print(f"    {key:<14} {area:>7.3f} {f'{lo:.3f} - {hi:.3f}':>20}{mark}")

    print("\n=== 2. the model, walk-forward over purged folds")
    area, lo, hi, tested = evaluate(rows)
    print(f"    all {len(KEYS)} signals: AUC {area:.3f}, 95% by episode {lo:.3f} - {hi:.3f}")
    print(f"    {tested} turns fell in a test fold")
    print(
        f"    {'separates from chance' if not lo <= 0.5 <= hi else 'DOES NOT separate from chance'}"
    )

    print("\n=== 2b. fewer signals, same purged walk-forward")
    print("    `features.md` found `side` alone beating all nine together. Ten")
    print("    correlated signals over 131 turns is the shape that produces it.\n")
    print(f"    {'signals':<28} {'AUC':>7} {'95% by episode':>20} {'':>2}")
    print("    " + "-" * 60)
    subsets = {
        "since_low alone": ("since_low",),
        "vol alone": ("vol",),
        "extension alone": ("extension",),
        "vol_ratio alone": ("vol_ratio",),
        "the four that separated": ("since_low", "vol", "extension", "vol_ratio"),
        "age and extension": ("since_low", "extension"),
        "all ten": KEYS,
    }
    for label, keys in subsets.items():
        area, lo, hi, _ = evaluate(rows, keys)
        mark = "" if lo <= 0.5 <= hi else " *"
        print(f"    {label:<28} {area:>7.3f} {f'{lo:.3f} - {hi:.3f}':>20}{mark}")

    print("\n=== 3. leave one instrument out")
    print(f"    {'held out':<10} {'AUC':>7} {'95% by episode':>20} {'turns':>7}")
    print("    " + "-" * 48)
    for feed in sorted({r["feed"] for r in rows}):
        rest = [r for r in rows if r["feed"] != feed]
        mine = [r for r in rows if r["feed"] == feed]
        model = fit(rest, KEYS)
        scored = [
            (
                model.predict_proba_one({k: r[k] for k in KEYS}).get(True, 0.5),
                r["turned"],
                r["episode"],
            )
            for r in mine
        ]
        area = auc([(s, y) for s, y, _ in scored])
        lo, hi = bootstrap(scored, 600)
        mark = "" if lo <= 0.5 <= hi else " *"
        print(
            f"    {feed:<10} {area:>7.3f} {f'{lo:.3f} - {hi:.3f}':>20}"
            f" {len({b for _, y, b in scored if y}):>7}{mark}"
        )


def eras(rows: list[dict], count: int = 4) -> None:
    """Whether the in-sample relationship is the same relationship over time."""
    print("\n=== 4. is it the same relationship in every era")
    ordered = sorted(rows, key=lambda r: r["when"])
    size = len(ordered) // count
    chunks = [
        ordered[k * size : (k + 1) * size] if k < count - 1 else ordered[k * size :]
        for k in range(count)
    ]
    spans = [f"{time.strftime('%Y-%m', time.gmtime(c[0]['when']))}" for c in chunks]
    print(f"    {'signal':<14} " + " ".join(f"{s:>10}" for s in spans) + f" {'spread':>9}")
    print("    " + "-" * 68)
    for key in ("since_low", "vol", "extension", "vol_ratio"):
        values = [auc([(r[key], r["turned"]) for r in c]) for c in chunks]
        print(
            f"    {key:<14} "
            + " ".join(f"{v:>10.3f}" for v in values)
            + f" {max(values) - min(values):>9.3f}"
        )
    print()
    for chunk, span in zip(chunks, spans, strict=True):
        hit = [r for r in chunk if r["turned"]]
        print(
            f"    from {span}: {len(chunk):>5} days, {len(hit):>4} labelled"
            f" ({len(hit) / len(chunk):>5.1%}), {len({r['episode'] for r in hit}):>3} turns"
        )


def power(rows: list[dict]) -> None:
    """How many turns it would take to settle this, measured rather than assumed.

    **Only the downward arm is valid.** Resampling *more* episodes than exist
    duplicates the ones there are and adds no information, so the interval
    stops narrowing and the curve flattens for a reason that has nothing to do
    with statistics. Subsampling down is real; extrapolating up from it is the
    honest direction.
    """
    print("\n=== 5. what sample would settle it")
    scored: list[tuple[float, bool, str]] = []
    for train, test in purged_folds(rows):
        if len({r["turned"] for r in train}) < 2:
            continue
        model = fit(train, KEYS)
        scored.extend(
            (
                model.predict_proba_one({k: row[k] for k in KEYS}).get(True, 0.5),
                row["turned"],
                row["episode"],
            )
            for row in test
        )
    blocks: dict[str, list[tuple[float, bool]]] = {}
    for score, label, block in scored:
        blocks.setdefault(block, []).append((score, label))
    positive = [b for b in blocks if any(y for _, y in blocks[b])]
    negative = [b for b in blocks if b not in positive]
    rng = random.Random(3)
    print(f"    {'turns':>7} {'median half-width of the 95% interval':>40}")
    print("    " + "-" * 49)
    for fraction in (0.25, 0.5, 1.0):
        widths = []
        for _ in range(40):
            drawn = [rng.choice(positive) for _ in range(max(2, int(len(positive) * fraction)))]
            drawn += [rng.choice(negative) for _ in range(max(2, int(len(negative) * fraction)))]
            sub = [(s, y, b) for b in drawn for s, y in blocks[b]]
            lo, hi = bootstrap(sub, 300)
            widths.append((hi - lo) / 2)
        print(f"    {int(len(positive) * fraction):>7} {statistics.median(widths):>40.3f}")
    print("\n    Narrowing more slowly than 1/sqrt(n), because episodes are")
    print("    themselves correlated and unequal in size. Reaching a half-width")
    print("    of 0.05 therefore needs **several hundred** out-of-sample turns")
    print(f"    against the {len(positive)} available, and probably more.")


if __name__ == "__main__":
    main()
