"""Splits that a forward-looking label cannot leak through.

A label computed `horizon` bars ahead makes a plain train/test cut wrong, and
wrong in a direction that flatters the model. Cut at time `T` and the last
`horizon` training rows carry labels built from bars *after* `T` - inside the test
period. The model is then scored on a stretch it was partly shown the answer to.

Two mechanics fix it, and both are needed:

* **purge** - drop the training rows whose forward window reaches into the test
  period. `horizon` rows at the boundary, exactly.
* **embargo** - drop test rows immediately after the training period too, because
  features are built from trailing windows up to `WARMUP` bars long, so an early
  test row is largely a function of bars the model trained on.

Neither is a refinement. On a five-bar horizon with daily bars the purge is one
week, and a week of the answer is enough to turn a null result into a result.

## Why leave-one-instrument-out is here as well

Every standard control passed on the daily-to-monthly momentum work - clustered
standard errors, parameter robustness, a synthetic control, a shuffled null - and
the effect was still nothing but bitcoin. **Only leave-one-group-out caught it.**
So it ships next to the walk-forward rather than as an optional extra: the
walk-forward answers "does it survive time", and this answers "does it survive
being asked about an instrument it never saw".
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

#: Trailing bars the longest feature window reaches back. Must match
#: `candles.WARMUP` - the embargo is derived from it.
WARMUP = 120


def walk_forward(
    when: np.ndarray, horizon: int, folds: int = 5, embargo: int | None = None
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Expanding-window folds in time order, purged and embargoed.

    Yields `(train, test)` index arrays. The training window always starts at the
    beginning - an expanding window rather than a sliding one - because the
    question is what a desk running since the start would know by then, and a
    sliding window answers a different and less useful question.
    """
    order = np.argsort(when, kind="stable")
    n = len(order)
    if n < folds * 4:
        return
    gap = WARMUP if embargo is None else embargo
    span = max(1, n // (folds + 1))
    edges = [int(n * (i + 1) / (folds + 1)) for i in range(folds)]
    for cut in edges:
        # Purge: the last `horizon` training rows are labelled from test bars.
        train = order[: max(0, cut - horizon)]
        # Embargo: **shift** the test window past the gap rather than trimming the
        # window down to it. Trimming was the first version and it is the kind of
        # bug this repository specialises in - with a 120-bar embargo and a fold
        # shorter than that, every test slice came out empty and the walk-forward
        # silently produced no folds at all, which reads exactly like a clean run.
        start = cut + gap
        stop = min(n, start + span)
        test = order[start:stop]
        if len(train) < 100 or len(test) < 50:
            continue
        yield train, test


def leave_one_out(
    groups: np.ndarray,
    when: np.ndarray,
    horizon: int,  # noqa: ARG001 - kept so both splitters take the same arguments
) -> Iterator[tuple[str, np.ndarray, np.ndarray]]:
    """Train on every instrument but one, test on the one held out.

    Yields `(held_out, train, test)`. **The time cut is kept inside this too.**
    Training on one instrument's future to predict another's past would be a
    perfectly good way to discover that markets are correlated and a useless way
    to discover anything tradeable, so the held-out instrument is only tested on
    the period after the training data ends.
    """
    for name in sorted(set(groups.tolist())):
        held = groups == name
        others = ~held
        if others.sum() < 500 or held.sum() < 100:
            continue
        # Train on the others' first 70% by time; test the held-out one after it.
        rest = np.flatnonzero(others)
        rest = rest[np.argsort(when[rest], kind="stable")]
        train = rest[: int(len(rest) * 0.7)]
        boundary = when[train].max() if len(train) else when.min()
        mine = np.flatnonzero(held)
        test = mine[when[mine] > boundary]
        if len(train) < 500 or len(test) < 100:
            continue
        yield str(name), train, test


def block_shuffle(y: np.ndarray, when: np.ndarray, horizon: int, seed: int = 0) -> np.ndarray:
    """Labels permuted in contiguous blocks, for a null with the right structure.

    A plain element-wise shuffle destroys the autocorrelation in the labels, which
    makes the null too easy to beat: overlapping forward windows mean neighbouring
    labels are genuinely similar, and a model can score above chance on that alone.
    Shuffling whole blocks keeps that structure and removes only the alignment
    between features and labels, which is the thing being tested.
    """
    rng = np.random.default_rng(seed)
    order = np.argsort(when, kind="stable")
    size = max(horizon * 4, 20)
    blocks = [order[i : i + size] for i in range(0, len(order), size)]
    rng.shuffle(blocks)
    shuffled = np.concatenate(blocks) if blocks else order
    out = np.empty_like(y)
    out[order] = y[shuffled]
    return out


def breakeven(cost: float, band: float, tr: float) -> float:
    """The accuracy a two-sided call must reach before it pays for itself.

    `0.5 + S / (2B)` - cost over twice the barrier, added to a coin flip. With a
    band of one true range at 60bp and a round-trip cost of 2bp, that is 0.517,
    and the distance between 51.7% and the 51.6% the live desk actually achieves
    is the entire argument about whether any of this is worth trading.
    """
    barrier = max(band * tr, 1e-9)
    return 0.5 + cost / (2.0 * barrier)
