"""Models trained offline and shipped as data: where they are read from, and how they are evaluated.

Most models on this desk learn online, predict-then-learn. Some should not: the shock forecaster
(`structures/learning/shocks.py`) lost half its signal learning live, and the same boosted model
trained offline kept it. This is the production half of moving a model from online to offline. The
other half, retraining on a schedule and promoting only a challenger that beats the model in
service, is `research/pipeline/`.

## Where a model is read from

`MODELS_DIR/<name>.json` first (`TI_MODELS_DIR`, default `.data/models`) - where the retraining
pipeline delivers a promoted model without a code change - and the copy shipped in
`till_infinity/models/<name>.json` otherwise. A model file that changes on disk is picked up without
a restart: the file's modification time is checked at most every `RECHECK` seconds.

## What a model file is

JSON with at least `recipe` (what the features mean), `names` (the features, in order) and the model
itself. A consumer states the recipe and feature names it computes, and a file trained on anything
else is **not used** - a number from the wrong features is worse than no number.

`Trees` evaluates a gradient-boosted model exported from sklearn's `HistGradientBoosting*` as plain
nodes, so production needs no training library: a classifier (logistic link) or a regressor
(identity link). `Quantiles` holds one regressor per quantile level, for the envelope.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

#: The shipped models, inside the package.
PACKAGED = Path(__file__).resolve().parent.parent / "models"

#: Seconds between checks for a changed model file.
RECHECK = 300.0


def models_dir() -> Path:
    return Path(os.environ.get("TI_MODELS_DIR", ".data/models"))


_cache: dict[str, tuple[float, float, str, dict[str, Any] | None]] = {}


def _source(name: str) -> Path | None:
    for base in (models_dir(), PACKAGED):
        path = base / f"{name}.json"
        if path.is_file():
            return path
    return None


def load(
    name: str, *, recipe: str, names: tuple[str, ...] | list[str], now: float | None = None
) -> dict | None:
    """The model called `name`, or None if there is none trained on `recipe` with `names`.

    Cached, and re-read when its file changes (checked at most every `RECHECK` seconds).
    """
    now = time.time() if now is None else now
    held = _cache.get(name)
    if held is not None and now - held[0] < RECHECK:
        return held[3]
    path = _source(name)
    if path is None:
        _cache[name] = (now, 0.0, "", None)
        return None
    mtime = path.stat().st_mtime
    if held is not None and held[1] == mtime and held[2] == str(path):
        _cache[name] = (now, mtime, str(path), held[3])
        return held[3]
    try:
        spec = json.loads(path.read_text())
    except (OSError, ValueError):
        spec = None
    if spec is not None and (
        spec.get("recipe") != recipe or list(spec.get("names", [])) != list(names)
    ):
        spec = None
    _cache[name] = (now, mtime, str(path), spec)
    return spec


def forget_cache() -> None:
    """Drop every cached model - for tests, and for a caller that knows a file just changed."""
    _cache.clear()


class Trees:
    """A gradient-boosted model exported as plain trees.

    Each node is `[feature, threshold, left, right, is_leaf, value, missing_go_to_left]`, exactly
    sklearn's `HistGradientBoosting*` predictor nodes: go left when `x <= threshold` (or when the
    value is missing and `missing_go_to_left`), and a leaf's value already carries the learning
    rate. The raw score is the baseline plus every tree's leaf. `link` says what it means:
    `logit` (the default, and every classifier shipped before regression existed) returns the
    logistic of it, a probability; `identity` returns it as it is, a regressor's prediction.
    """

    def __init__(self, spec: dict[str, Any]) -> None:
        self.baseline = float(spec["baseline"])
        self.trees = spec["trees"]
        self.link = str(spec.get("link", "logit"))

    def raw(self, x: list[float]) -> float:
        total = self.baseline
        for nodes in self.trees:
            i = 0
            while not nodes[i][4]:
                feature, threshold, left, right, _, _, missing_left = nodes[i][:7]
                v = x[feature]
                go_left = missing_left if math.isnan(v) else v <= threshold
                i = left if go_left else right
            total += nodes[i][5]
        return total

    def predict(self, x: list[float]) -> float:
        raw = self.raw(x)
        if self.link == "identity":
            return raw
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, raw))))


class Quantiles:
    """Several regressors, one per quantile level, from one spec: `levels` and `models`, each model
    `{baseline, trees}` read with the identity link. `predict` returns the quantiles in level
    order, sorted so they never cross - a quantile model fitted level by level can, rarely."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self.levels = [float(v) for v in spec["levels"]]
        self.models = [Trees({**m, "link": "identity"}) for m in spec["models"]]

    def predict(self, x: list[float]) -> list[float]:
        return sorted(m.raw(x) for m in self.models)
