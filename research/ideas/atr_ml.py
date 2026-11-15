"""Everything in ATR units, and then ask whether a model can learn anything.

**ATR is the equaliser.** `reactive-zones.md` measures why: it is twice the
mean close-to-close move in every instrument-frame cell tested, the shape of
its distribution is stable across years while its level doubles, and a
quantile of it therefore means the same thing in 2019 and in 2026. So every
feature here is divided by the bar's own ATR and every target is a move in ATR
units - which is what lets one model see five instruments and eight years at
once without the loud ones drowning the quiet.

## The controls are the experiment

A model will always produce a number. These are what say whether the number
means anything, and each one has caught a wrong answer in this repository:

* **A time split, never a random one.** Train on 2018-11 to 2024-11, test on
  the two years after. Random cross-validation on a time series leaks the
  future through overlapping windows - `overlapping-outcome-windows-leak`
  records direction AUC of 0.79 collapsing to 0.51 once that was fixed.
* **Shuffled labels, same pipeline.** The floor the fitting procedure produces
  from nothing. An AUC above 0.5 on permuted targets is the measure of how
  much the harness itself invents.
* **Edge in ATR units, not AUC.** `fit-on-the-edge-not-the-raw-score`: fitted
  weights once beat hand-tuned ones on AUC, 0.604 against 0.556, and lost on
  edge, +0.002 against +0.019. A model that ranks well and pays nothing is the
  normal outcome, so the headline number here is what the signal would have
  made, in ATR, per trade.
* **Per instrument, never only pooled.** A pooled answer here once agreed with
  a claim every subgroup refuted.
* **A power curve.** A planted drift of known size, swept, so the run says
  where it goes blind rather than only that it found nothing.

## What is deliberately not here

No cost model, no exits, no position sizing. This asks one question - is there
anything learnable in the bar geometry, expressed in ATR - and a negative
answer closes a family far more cheaply than a backtest does.

Run as:

    uv run --extra train python research/ideas/atr_ml.py --years 8
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reactive_zones import CATALOGUE, Candles, atr, fold, load  # noqa: E402

SYMBOLS = ("EURUSD", "GBPUSD", "GOLD", "USDJPY", "AUDUSD")

#: Bars ahead the target looks. 16 at 15m is four hours, the horizon every
#: other measurement in `reactive-zones.md` uses, so the answers are
#: comparable.
HORIZON = 16

#: Lookbacks for the displacement features, in bars of the execution frame.
REACH = (1, 4, 16, 96)

#: The trailing window the regime quantile is taken over.
QUIET = 200


@dataclass(slots=True)
class Table:
    """One instrument's features, targets and timestamps, already aligned."""

    feed: str
    x: np.ndarray
    y: np.ndarray
    ts: np.ndarray
    names: tuple[str, ...]


def build(bars: Candles, horizon: int = HORIZON) -> Table:
    """Features in ATR units and the forward move in ATR units.

    **Every feature is known at the bar's close and the target starts after
    it.** The one that is easy to get wrong is the regime quantile, whose
    trailing window ends at the previous bar - a quantile that includes the bar
    being judged is a comparison with itself.
    """
    band = atr(bars)
    close, high, low, open_ = bars.close, bars.high, bars.low, bars.open
    span = high - low
    body = close - open_

    columns: list[np.ndarray] = []
    names: list[str] = []

    def add(name: str, values: np.ndarray) -> None:
        columns.append(values)
        names.append(name)

    with np.errstate(invalid="ignore", divide="ignore"):
        add("body", body / band)
        add("range", span / band)
        add("upper_wick", (high - np.maximum(open_, close)) / band)
        add("lower_wick", (np.minimum(open_, close) - low) / band)
        # Where in its own range the bar closed: 0 at the low, 1 at the high.
        add("close_in_range", np.where(span > 0, (close - low) / np.where(span > 0, span, 1), 0.5))
        for reach in REACH:
            moved = np.full(close.size, np.nan)
            moved[reach:] = (close[reach:] - close[:-reach]) / band[reach:]
            add(f"move_{reach}", moved)
            rough = np.full(close.size, np.nan)
            steps = np.abs(np.diff(close, prepend=close[0]))
            cumulative = np.cumsum(steps)
            if reach > 1:
                travel = np.full(close.size, np.nan)
                travel[reach:] = cumulative[reach:] - cumulative[:-reach]
                # Path over net: 1 is a straight line, large is chop.
                rough = np.where(np.abs(moved) > 0, travel / np.abs(moved * band), np.nan)
                add(f"rough_{reach}", rough)
        # Distance to the trailing extremes, which is where a level would be.
        for reach in (96,):
            top = np.full(close.size, np.nan)
            bottom = np.full(close.size, np.nan)
            for i in range(reach, close.size):
                top[i] = high[i - reach : i].max()
                bottom[i] = low[i - reach : i].min()
            add(f"to_high_{reach}", (top - close) / band)
            add(f"to_low_{reach}", (close - bottom) / band)
        # The regime: where this ATR sits in its own trailing distribution.
        rank = np.full(close.size, np.nan)
        for i in range(QUIET, close.size):
            past = band[i - QUIET : i]
            past = past[np.isfinite(past)]
            if past.size >= QUIET // 2 and np.isfinite(band[i]):
                rank[i] = float((past < band[i]).mean())
        add("atr_rank", rank)
        # Short against long volatility, which is the same question faster.
        slow_band = atr(bars, 480)
        add("atr_ratio", band / slow_band)
        # The clock, as two continuous features rather than one discontinuous.
        hour = (bars.ts // 3_600_000_000_000) % 24
        add("hour_sin", np.sin(2 * np.pi * hour / 24))
        add("hour_cos", np.cos(2 * np.pi * hour / 24))

        target = np.full(close.size, np.nan)
        target[:-horizon] = (close[horizon:] - close[:-horizon]) / band[:-horizon]

    x = np.vstack(columns).T
    keep = np.all(np.isfinite(x), axis=1) & np.isfinite(target)
    return Table(bars.symbol, x[keep], target[keep], bars.ts[keep], tuple(names))


# --- the experiment ----------------------------------------------------------


def split(tables: list[Table], cut: float) -> tuple[np.ndarray, ...]:
    """Train before `cut`, test after. **Never a random split.**

    Random cross-validation on a time series leaks the future: the targets
    overlap by `HORIZON` bars, so a neighbouring row in the training set
    contains most of a test row's answer. `overlapping-outcome-windows-leak`
    records a direction AUC of 0.79 collapsing to 0.51 once that was fixed.
    """
    train_x, train_y, test_x, test_y, test_feed = [], [], [], [], []
    for table in tables:
        early = table.ts < cut
        train_x.append(table.x[early])
        train_y.append(table.y[early])
        test_x.append(table.x[~early])
        test_y.append(table.y[~early])
        test_feed.append(np.full((~early).sum(), table.feed))
    return (
        np.vstack(train_x),
        np.concatenate(train_y),
        np.vstack(test_x),
        np.concatenate(test_y),
        np.concatenate(test_feed),
    )


def score(name: str, truth: np.ndarray, guess: np.ndarray, feeds: np.ndarray | None = None) -> None:
    """AUC and - the number that matters - the edge in ATR units.

    `fit-on-the-edge-not-the-raw-score`: fitted weights once beat hand-tuned
    ones on AUC, 0.604 against 0.556, and lost on edge, +0.002 against +0.019.
    A model that ranks well and pays nothing is the normal outcome here, so the
    edge is printed first and the AUC second.
    """
    side = np.sign(guess)
    taken = side != 0
    edge = float(np.mean(truth[taken] * side[taken])) if taken.any() else float("nan")
    up = truth > 0
    order = np.argsort(guess)
    ranks = np.empty(guess.size, dtype=float)
    ranks[order] = np.arange(guess.size, dtype=float)
    positives, negatives = up.sum(), (~up).sum()
    auc = (
        float((ranks[up].sum() - positives * (positives - 1) / 2) / (positives * negatives))
        if positives and negatives
        else float("nan")
    )
    print(f"  {name:<22} edge {edge:+7.4f} ATR   AUC {auc:.4f}   n {taken.sum():,}")
    if feeds is not None:
        for feed in sorted(set(feeds)):
            m = (feeds == feed) & taken
            if m.sum() > 200:
                print(f"      {feed:<8} edge {np.mean(truth[m] * side[m]):+7.4f}   n {m.sum():,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--frame", default="15m")
    parser.add_argument("--horizon", type=int, default=HORIZON)
    parser.add_argument("--plant", type=float, default=0.0, help="plant a drift of this size, in ATR")
    parser.add_argument("--shuffles", type=int, default=8)
    parser.add_argument("--cut-years", type=float, default=2.0, help="train/test boundary, years back")
    parser.add_argument("--test-years", type=float, default=0.0, help="truncate the test window")
    parser.add_argument(
        "--keep-drift",
        action="store_true",
        help="leave each instrument's unconditional drift in the target",
    )
    args = parser.parse_args()

    tables = []
    for symbol in (s for s in args.symbols.split(",") if s):
        bars = fold(load(Path(args.catalogue), symbol), args.frame)
        table = build(bars, args.horizon)
        tables.append(table)
        print(f"{symbol}: {len(table.y):,} rows, {len(table.names)} features")

    # Two years held out, as everywhere else in this work.
    newest = max(int(t.ts[-1]) for t in tables)
    cut = newest - int(args.cut_years * 365.25 * 86_400 * 1e9)
    if args.test_years:
        # A *second* test window, earlier than the first and disjoint from it.
        # One window that shows an edge is a cell; two is the beginning of a
        # claim, and today's held-out run is the reason for the distinction.
        stop = cut + int(args.test_years * 365.25 * 86_400 * 1e9)
        tables = [
            Table(t.feed, t.x[t.ts <= stop], t.y[t.ts <= stop], t.ts[t.ts <= stop], t.names)
            for t in tables
        ]
    train_x, train_y, test_x, test_y, test_feed = split(tables, cut)
    print(f"\ntrain {len(train_y):,} rows, test {len(test_y):,} rows, split at two years back")

    if not args.keep_drift:
        # **Each instrument's own unconditional drift, removed - using only the
        # training period's mean.**
        #
        # Without this the score is beta to whatever trended. Gold's price
        # roughly doubled across the test window, so a model that is simply
        # long gold collects that and reports it as skill: the shuffled-target
        # floor came out at +0.0220 ATR for exactly this reason, and a floor
        # that is not zero makes every number above it unreadable.
        #
        # The mean is taken on the training rows only. Removing the test
        # period's own mean would be using the answer.
        offsets = {}
        for table in tables:
            early = table.ts < cut
            offsets[table.feed] = float(np.mean(table.y[early])) if early.any() else 0.0
        order = [t.feed for t in tables]
        counts = [int((t.ts < cut).sum()) for t in tables]
        train_y = train_y - np.concatenate(
            [np.full(n, offsets[f]) for f, n in zip(order, counts, strict=True)]
        )
        test_y = test_y - np.array([offsets[f] for f in test_feed])
        print("  drift removed per instrument, from the training period only:")
        print("   " + "  ".join(f"{f} {offsets[f]:+.4f}" for f in order))

    if args.plant:
        # **The power check.** A drift of known size, added to the training and
        # test targets alike, so a run that finds nothing can say how large an
        # effect it would have found.
        rng = np.random.default_rng(0)
        mark = rng.standard_normal(train_x.shape[1])
        signal_train = np.sign(train_x @ mark)
        signal_test = np.sign(test_x @ mark)
        train_y = train_y + args.plant * signal_train
        test_y = test_y + args.plant * signal_test
        print(f"planted a drift of {args.plant:+.3f} ATR on a fixed random direction")

    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(train_x)
    a, b = scaler.transform(train_x), scaler.transform(test_x)

    print("\n=== test window, out of sample")
    ridge = Ridge(alpha=1.0).fit(a, train_y)
    score("ridge", test_y, ridge.predict(b), test_feed)

    trees = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, random_state=0)
    trees.fit(train_x, train_y)
    score("gradient boosting", test_y, trees.predict(test_x), test_feed)

    # **The floor, drawn several times.** One permutation is one draw, and the
    # test rows are not independent: targets overlap by `HORIZON` bars and
    # cluster in days, so the effective sample is a small fraction of the row
    # count and a single shuffled number says nothing about its own spread.
    print(f"\n=== the floor: {args.shuffles} draws of the same pipeline on shuffled targets")
    rng = np.random.default_rng(7)
    floors: dict[str, list[float]] = {"ridge": [], "boosting": []}
    for draw in range(args.shuffles):
        noise = rng.permutation(train_y)
        guess = Ridge(alpha=1.0).fit(a, noise).predict(b)
        side = np.sign(guess)
        floors["ridge"].append(float(np.mean(test_y[side != 0] * side[side != 0])))
        trees_n = HistGradientBoostingRegressor(
            max_iter=200, learning_rate=0.05, random_state=draw
        ).fit(train_x, noise)
        guess = trees_n.predict(test_x)
        side = np.sign(guess)
        floors["boosting"].append(float(np.mean(test_y[side != 0] * side[side != 0])))
    for name, values in floors.items():
        arr = np.array(values)
        print(
            f"  {name:<22} floor {arr.mean():+7.4f} +/- {arr.std(ddof=1):.4f} ATR"
            f"   range {arr.min():+.4f} to {arr.max():+.4f}"
        )

    print("\n=== in sample, for the gap")
    score("ridge, train", train_y, ridge.predict(a))
    score("boosting, train", train_y, trees.predict(train_x))


if __name__ == "__main__":
    main()
