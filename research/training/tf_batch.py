"""Batch-train TensorFlow models on the candle panel, against the same controls.

Run from the repository root:

    .venv-research/bin/python research/training/tf_batch.py --family triple
    .venv-research/bin/python research/training/tf_batch.py --family speed --net conv

Two networks, answering two different questions:

* `mlp` - a dense net on the same tabular features `sk_batch.py` uses. Its only
  job is to say whether depth buys anything over gradient boosting on identical
  inputs. Usually it does not, and that is worth knowing rather than assuming.
* `conv` - a 1D convolution over `candles.WINDOW` bars of normalised candle
  shape. This is the candlestick-pattern idea done without the picture: the same
  geometry a chart shows, as numbers, with the price level and the volatility
  scale divided out so the network cannot learn which decade it is looking at.

## The comparison is the deliverable, not the network

A deep model that beats the majority class is not interesting; a deep model that
beats **gradient boosting on the same rows and the same folds** would be. So this
prints the same four numbers in the same shape as `sk_batch.py`, including the
block-shuffled null, and the two outputs are meant to be read side by side.

## Where the honesty lives in a neural net specifically

* **The validation split is the end of the training window, never random.**
  Keras defaults `validation_split` to the last rows of whatever it is handed,
  which is only correct because the rows arrive in time order - and they do,
  because the fold indices are sorted. Shuffling before splitting would put
  future rows in the validation set and early stopping would then select for
  having seen them.
* **Class weights, not resampling.** Oversampling a minority class duplicates
  rows whose forward windows already overlap, which inflates the effective sample
  and makes early stopping fire late.
* **Seeded, and the seed is reported.** A network that only works on one seed is
  a coin flip with extra steps, so `--seeds` runs several and prints the spread.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

# Keras is chatty and none of it is information. Set before the import.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "harness"))

import candles  # noqa: E402
import splits  # noqa: E402
from sk_batch import COST  # noqa: E402

#: Rows per gradient step. Large enough that a batch is a representative sample
#: of a very imbalanced label, small enough to still take enough steps.
BATCH = 512

#: Passes over the training data. Early stopping almost always ends it sooner.
EPOCHS = 60


def dense(shape: int, classes: int, seed: int):
    """A plain three-layer net. Dropout because this sample is small for a net."""
    import tensorflow as tf

    tf.keras.utils.set_random_seed(seed)
    return tf.keras.Sequential(
        [
            tf.keras.layers.Input(shape=(shape,)),
            tf.keras.layers.Normalization(),
            tf.keras.layers.Dense(128, activation="relu"),
            tf.keras.layers.Dropout(0.3),
            tf.keras.layers.Dense(64, activation="relu"),
            tf.keras.layers.Dropout(0.3),
            tf.keras.layers.Dense(classes, activation="softmax"),
        ]
    )


def conv(window: int, channels: int, classes: int, seed: int):
    """A small 1D convolution over candle shape.

    Kernels of 3 and 5 bars because that is the span of the patterns anyone
    actually names - engulfing, three soldiers, the operator's run of same-coloured
    candles with one long one in it. Global pooling rather than a flatten, so the
    net reads *whether* a shape occurred in the window rather than exactly where,
    which is the property that makes a pattern a pattern.
    """
    import tensorflow as tf

    tf.keras.utils.set_random_seed(seed)
    return tf.keras.Sequential(
        [
            tf.keras.layers.Input(shape=(window, channels)),
            tf.keras.layers.Conv1D(32, 3, padding="same", activation="relu"),
            tf.keras.layers.Conv1D(32, 5, padding="same", activation="relu"),
            tf.keras.layers.MaxPooling1D(2),
            tf.keras.layers.Conv1D(64, 3, padding="same", activation="relu"),
            tf.keras.layers.GlobalAveragePooling1D(),
            tf.keras.layers.Dropout(0.3),
            tf.keras.layers.Dense(64, activation="relu"),
            tf.keras.layers.Dense(classes, activation="softmax"),
        ]
    )


def weights(y: np.ndarray, classes: int) -> dict[int, float]:
    """Inverse-frequency class weights, so the flat class cannot win by volume."""
    counts = np.bincount(y, minlength=classes).astype(float)
    counts[counts == 0] = 1.0
    return {i: float(len(y) / (classes * counts[i])) for i in range(classes)}


def fit_once(net, xtrain, ytrain, classes: int):
    import tensorflow as tf

    net.compile(
        optimizer=tf.keras.optimizers.Adam(1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    # The first layer adapts to the training data only. Adapting on everything
    # would leak the test period's mean and variance into training.
    first = net.layers[0]
    if isinstance(first, tf.keras.layers.Normalization):
        first.adapt(xtrain)
    net.fit(
        xtrain,
        ytrain,
        batch_size=BATCH,
        epochs=EPOCHS,
        # The last tenth of an already time-ordered array: the most recent rows
        # before the test period, which is the only honest validation set here.
        validation_split=0.1,
        shuffle=False,
        class_weight=weights(ytrain, classes),
        verbose=0,
        callbacks=[
            tf.keras.callbacks.EarlyStopping(
                monitor="val_loss", patience=8, restore_best_weights=True
            )
        ],
    )
    return net


def score(net, x, y, ret, classes: list[str]) -> dict[str, float]:
    from sklearn.metrics import accuracy_score, balanced_accuracy_score

    said = np.argmax(net.predict(x, batch_size=BATCH, verbose=0), axis=1)
    out = {
        "acc": float(accuracy_score(y, said)),
        "bal": float(balanced_accuracy_score(y, said)),
    }
    took = said != 1  # the neutral middle class, in every family
    out["call_share"] = float(took.mean()) if len(said) else 0.0
    if took.any():
        side = np.where(said[took] == len(classes) - 1, 1.0, -1.0)
        paid = side * ret[took] - COST
        out["edge"] = float(paid.mean())
        out["edge_se"] = float(paid.std(ddof=1) / max(np.sqrt(len(paid)), 1.0))
    else:
        out["edge"] = out["edge_se"] = 0.0
    return out


def run(panel, seq, which: str, folds: int, seeds: int, *, shuffled: bool = False):
    """Walk-forward the chosen network, over every seed."""
    y = splits.block_shuffle(panel.y, panel.when, panel.horizon) if shuffled else panel.y
    classes = max(len(panel.classes), int(y.max()) + 1)
    x = seq if which == "conv" else panel.x
    rows = []
    for train, test in splits.walk_forward(panel.when, panel.horizon, folds=folds):
        if len(np.unique(y[train])) < 2:
            continue
        for seed in range(seeds):
            net = (
                conv(x.shape[1], x.shape[2], classes, seed)
                if which == "conv"
                else dense(x.shape[1], classes, seed)
            )
            fit_once(net, x[train], y[train], classes)
            rows.append(score(net, x[test], y[test], panel.ret[test], panel.classes))
    return rows


def table(title: str, rows: list[dict[str, float]], majority: float) -> None:
    print(f"\n{title}")
    if not rows:
        print("  nothing fitted - not enough data for a purged walk-forward")
        return
    mean = {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}
    worst = min(r["edge"] for r in rows)
    best = max(r["edge"] for r in rows)
    t = mean["edge"] / mean["edge_se"] if mean["edge_se"] else 0.0
    print(f"  {'acc':>7} {'bal':>7} {'calls':>7} {'edge/call':>11} {'t':>6}")
    print(
        f"  {mean['acc']:>7.3f} {mean['bal']:>7.3f} {mean['call_share']:>6.1%} "
        f"{mean['edge']:>+11.5f} {t:>6.2f}"
    )
    print(f"  across {len(rows)} fits the edge ranged {worst:+.5f} to {best:+.5f}")
    print(f"  majority class is {majority:.1%}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--family", default="banded")
    ap.add_argument("--net", default="mlp", choices=("mlp", "conv"))
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--where", default=".secrets")
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--band", type=float, default=1.0)
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--skip-null", action="store_true")
    args = ap.parse_args()

    paths = candles.find(args.where, args.interval)
    if not paths:
        print(f"no {args.interval} candle files in {args.where}")
        return 1

    print(f"{len(paths)} files, family={args.family} net={args.net} horizon={args.horizon}")
    if args.net == "conv":
        seq, panel = candles.sequences(
            paths, family=args.family, horizon=args.horizon, band=args.band
        )
    else:
        seq, panel = (
            None,
            candles.build(
                paths, family=args.family, horizon=args.horizon, band=args.band, verbose=False
            ),
        )
    if not len(panel):
        print("no usable rows")
        return 1
    print(f"{len(panel):,} rows over {len(set(panel.groups.tolist()))} instruments")

    table(
        f"{args.net}, walk-forward, {args.folds} purged folds x {args.seeds} seeds",
        run(panel, seq, args.net, args.folds, args.seeds),
        panel.majority,
    )
    if not args.skip_null:
        table(
            "the same on block-shuffled labels - what this apparatus scores on noise",
            run(panel, seq, args.net, args.folds, args.seeds, shuffled=True),
            panel.majority,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
