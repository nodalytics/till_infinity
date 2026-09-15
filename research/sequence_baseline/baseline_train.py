#!/usr/bin/env python3
"""Train a tiny baseline without external ML deps.

- Classification: simple logistic regression trained with SGD on flattened windows
- Regression: linear regression (pseudo-inverse) on flattened windows

This is intentionally small and dependency-free so it can run in the repo's CI
without adding scikit-learn/lightgbm. It gives baseline numbers to compare
against future sequence models.
"""
from pathlib import Path
import numpy as np
from math import exp
from evaluate import accuracy, log_loss, mae

SRC = Path('.data/research/sequence_baseline')
INSTRUMENTS = ['gold', 'btc', 'v75', 'v100']
WINDOW = 8
LR = 0.1
EPOCHS = 50


def load_split(slug: str):
    train = np.load(SRC / f'{slug}.train.npz', allow_pickle=True)
    val = np.load(SRC / f'{slug}.val.npz', allow_pickle=True)
    test = np.load(SRC / f'{slug}.test.npz', allow_pickle=True)
    return train['X'], train['y_hold'], train['y_push'], val['X'], val['y_hold'], val['y_push'], test['X'], test['y_hold'], test['y_push']


def flatten_windows(X):
    # X: (N, W, F) -> (N, W*F)
    N, W, F = X.shape
    return X.reshape(N, W * F)


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -50, 50)))


def train_logistic_sgd(X, y, lr=LR, epochs=EPOCHS):
    Xb = np.hstack([np.ones((X.shape[0], 1)), X])
    w = np.zeros(Xb.shape[1], dtype=float)
    for epoch in range(epochs):
        # stochastic shuffle
        idx = np.random.permutation(Xb.shape[0])
        for i in idx:
            xi = Xb[i]
            yi = y[i]
            p = sigmoid(np.dot(w, xi))
            grad = (p - yi) * xi
            w -= lr * grad
    return w


def predict_logistic(w, X):
    Xb = np.hstack([np.ones((X.shape[0], 1)), X])
    probs = sigmoid(Xb.dot(w))
    return probs


def train_linear_regression(X, y):
    # closed-form via pseudo-inverse
    Xb = np.hstack([np.ones((X.shape[0], 1)), X])
    w = np.linalg.pinv(Xb).dot(y)
    return w


def predict_linear(w, X):
    Xb = np.hstack([np.ones((X.shape[0], 1)), X])
    return Xb.dot(w)


def single_instrument_baseline(slug: str):
    X_tr, y_tr_hold, y_tr_push, X_val, y_val_hold, y_val_push, X_te, y_te_hold, y_te_push = load_split(slug)
    Xtr = flatten_windows(X_tr)
    Xv = flatten_windows(X_val)
    Xte = flatten_windows(X_te)

    # classification
    w_clf = train_logistic_sgd(Xtr, y_tr_hold, lr=LR, epochs=EPOCHS)
    p_val = predict_logistic(w_clf, Xv)
    p_test = predict_logistic(w_clf, Xte)
    val_acc = accuracy(y_val_hold, p_val)
    val_ll = log_loss(y_val_hold, p_val)
    test_acc = accuracy(y_te_hold, p_test)
    test_ll = log_loss(y_te_hold, p_test)

    # regression
    w_reg = train_linear_regression(Xtr, y_tr_push)
    pred_val_push = predict_linear(w_reg, Xv)
    pred_test_push = predict_linear(w_reg, Xte)
    val_mae = mae(y_val_push, pred_val_push)
    test_mae = mae(y_te_push, pred_test_push)

    out = {
        'slug': slug,
        'clf_val_acc': val_acc,
        'clf_val_logloss': val_ll,
        'clf_test_acc': test_acc,
        'clf_test_logloss': test_ll,
        'reg_val_mae': val_mae,
        'reg_test_mae': test_mae,
    }
    return out


def main():
    results = []
    for slug in INSTRUMENTS:
        if not (SRC / f'{slug}.train.npz').exists():
            print(f'skipping {slug}: dataset missing')
            continue
        print(f'Running baseline for {slug}...')
        res = single_instrument_baseline(slug)
        print('->', res)
        results.append(res)
    print('\nAll results:')
    for r in results:
        print(r)

if __name__ == '__main__':
    main()
