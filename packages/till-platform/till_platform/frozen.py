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
from collections.abc import Sequence
from pathlib import Path
from typing import Any

#: Where the shipped models live, or `None` until something says.
#:
#: **Not guessed from this file's location, which is how it broke.** This read
#: `Path(__file__).parent.parent / "models"` while it lived in
#: `till_infinity/shared/`, where that happened to be the desk's own `models/`
#: directory. When this became a package on 2026-10-29 the same expression
#: pointed at `packages/till-platform/models`, which does not exist - so every
#: shipped model silently stopped being found and seven tests failed with "the
#: model is not found" rather than with anything about a path.
#:
#: A platform package does not know where a service keeps its data. Whoever
#: ships the files says so: `till_infinity/__init__.py` calls `ship()`.
PACKAGED: Path | None = None


def ship(directory: Path) -> None:
    """Name the directory holding the shipped models.

    Idempotent and last-call-wins, because the alternative - refusing a second
    call - would make an import order a hard error for no benefit.

    **A module attribute, rather than a container this rebinds into.** Ruff
    dislikes the `global` and it is right in general, but three tests reach for
    `monkeypatch.setattr(frozen, "PACKAGED", ...)` to ask what happens when the
    shipped copy is absent - and monkeypatch restores an attribute while a
    mutated container would leak that state into the next test. Test isolation
    is worth more here than the style rule.
    """
    global PACKAGED  # noqa: PLW0603 - patchable by monkeypatch; see above
    PACKAGED = Path(directory)


#: Seconds between checks for a changed model file.
RECHECK = 300.0


def models_dir() -> Path:
    return Path(os.environ.get("TI_MODELS_DIR", ".data/models"))


_cache: dict[str, tuple[float, float, str, dict[str, Any] | None]] = {}


def _source(name: str) -> Path | None:
    # `PACKAGED` is `None` when nothing has shipped any, which is a real state
    # for a service installed on its own rather than an error.
    for base in (models_dir(), PACKAGED):
        if base is None:
            continue
        path = base / f"{name}.json"
        if path.is_file():
            return path
    return None


def vector(spec: dict, names: Sequence[str], values: Sequence[float]) -> list[float] | None:
    """`values`, given in `names` order, rearranged into the spec's own order.

    **The subset check in `load` is what makes this necessary.** A file whose
    `names` are a subset of the caller's is accepted on purpose - that is what
    lets a recipe gain a feature without stranding every model already in
    service - but a caller that then feeds a vector built positionally from its
    own constant hands the model the wrong value in every slot after the first
    difference. Nothing raises; the numbers are simply wrong.

    This is the positional form of what `envelope.model_quantiles` does with a
    dict, and it is the same rule: a model is fed what it was trained on, not
    what the module currently believes the recipe to be. `activity` becoming the
    fifteenth envelope feature on 2026-10-09 is the case it exists for - the
    shipped files have fourteen, and the envelope kept working because it
    reorders. The three callers that did not would have shifted every feature by
    one and gone on publishing.

    None means this caller cannot feed this model: the spec wants a name that is
    not on offer, which is the one genuinely unsafe case.
    """
    wanted = tuple(spec.get("names") or ())
    order = tuple(names)
    if not wanted or wanted == order:
        return list(values)
    row = dict(zip(order, values, strict=False))
    if any(name not in row for name in wanted):
        return None
    return [float(row[name]) for name in wanted]


def load(
    name: str,
    *,
    recipe: str | Sequence[str],
    names: tuple[str, ...] | list[str],
    now: float | None = None,
) -> dict | None:
    """The model called `name`, or None if there is none this caller can feed.

    Cached, and re-read when its file changes (checked at most every `RECHECK` seconds).

    **The names check is a subset, not an equality, and that is the point.** The
    safety property is "never feed a model an input it was not trained on" -
    which is satisfied as long as every name the spec declares is one the caller
    can supply. Demanding *equality* adds nothing to that and costs a great deal:
    it means adding one feature to a recipe rejects every model already in
    service, so the engine falls back to its history envelope until a retrain
    lands. A model that needs fewer inputs than are on offer is a perfectly good
    model; a model that needs one we do not have is the only unsafe case, and a
    subset check is exactly the test for it.

    Callers must therefore build the feature vector from **the spec's own
    `names`**, in the spec's order, rather than from their module constant -
    `envelope.model_quantiles` is the worked example.

    `recipe` may be several, newest first, so a recipe can be superseded without
    stranding the models trained on the one before it.
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
    allowed = (recipe,) if isinstance(recipe, str) else tuple(recipe)
    if spec is not None and (
        spec.get("recipe") not in allowed
        or not set(spec.get("names") or ()) <= set(names)
        or not spec.get("names")
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
