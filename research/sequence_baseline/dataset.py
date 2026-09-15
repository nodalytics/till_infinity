"""Windowed dataset builder for sequence turn data.

Given per-instrument .npz files produced by data_prep_turns.py, build samples
of fixed-length windows (last K turns) to feed into sequence models.

Outputs train/val/test splits as .npz files in the same folder.
"""
from pathlib import Path
import numpy as np

SRC = Path('.data/research/sequence_baseline')
SRC.mkdir(parents=True, exist_ok=True)

WINDOW = 8  # number of turns per sample
STEP = 1
TRAIN_FRAC = 0.7
VAL_FRAC = 0.15
TEST_FRAC = 0.15


def build_windows(X, y_hold, y_push, window=WINDOW, step=STEP):
    n = len(y_hold)
    windows = []
    holds = []
    pushes = []
    for start in range(0, n - window + 1, step):
        end = start + window
        windows.append(X[start:end])
        # label for sample: hold/push of the last turn in window
        holds.append(y_hold[end - 1])
        pushes.append(y_push[end - 1])
    return np.array(windows), np.array(holds), np.array(pushes)


def split_and_save(slug: str):
    path = SRC / f'{slug}.npz'
    data = np.load(path, allow_pickle=True)
    X = data['X']
    y_hold = data['y_hold']
    y_push = data['y_push']
    windows, holds, pushes = build_windows(X, y_hold, y_push)
    n = len(windows)
    i1 = int(n * TRAIN_FRAC)
    i2 = i1 + int(n * VAL_FRAC)
    out_train = SRC / f'{slug}.train.npz'
    out_val = SRC / f'{slug}.val.npz'
    out_test = SRC / f'{slug}.test.npz'
    np.savez_compressed(out_train, X=windows[:i1], y_hold=holds[:i1], y_push=pushes[:i1])
    np.savez_compressed(out_val, X=windows[i1:i2], y_hold=holds[i1:i2], y_push=pushes[i1:i2])
    np.savez_compressed(out_test, X=windows[i2:], y_hold=holds[i2:], y_push=pushes[i2:])
    print(f'Built {n} samples for {slug}. Saved splits: {out_train}, {out_val}, {out_test}')


def main():
    for npz in sorted(SRC.glob('*.npz')):
        if npz.name.endswith(('.train.npz', '.val.npz', '.test.npz')):
            continue
        slug = npz.stem
        split_and_save(slug)


if __name__ == '__main__':
    main()
