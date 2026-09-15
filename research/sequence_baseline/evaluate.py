"""Evaluation helpers: accuracy, log loss, MAE."""
import numpy as np


def accuracy(y_true, y_pred):
    yhat = (y_pred >= 0.5).astype(float)
    return float((yhat == y_true).mean())


def log_loss(y_true, p):
    eps = 1e-12
    p = np.clip(p, eps, 1 - eps)
    return float(-(y_true * np.log(p) + (1 - y_true) * np.log(1 - p)).mean())


def mae(y_true, y_pred):
    return float(np.abs(y_pred - y_true).mean())
