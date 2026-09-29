"""Train and score the shock forecaster (`structures/learning/shocks.py`) from bar history.

The features are computed by running every series through the production `Shocks` class itself,
in time order, so a retrained model is trained on exactly what the engine will hand it. The label
is whether a shock - a bar beyond `SHOCK_MULTIPLE` times the trailing mean |return| - arrives
within the next `AHEAD` bars of the same series. Measured in `research/docs/anomalies.md`; the
research harnesses are `research/harness/shocktrain.py` and `shockreplay.py`.
"""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from ..prices.models import Bar
from ..structures.learning import shocks as sh

SECONDS = {"15m": 900.0, "1h": 3600.0}

#: Words that mark a Deriv synthetic - an index whose shocks are published as memoryless, so a model
#: that "predicts" them is fitting noise. They are the retraining's control.
SYNTHETIC = ("Volatility", "Boom", "Crash", "Jump", "Step", "Range Break", "DEX", "Drift Switch")


def kind(symbol: str) -> str:
    return "synthetic" if any(word in symbol for word in SYNTHETIC) else "real"


@dataclass
class Rows:
    """One row per scored bar: when, which series, which kind, the features, the label."""

    when: list[float] = field(default_factory=list)
    key: list[str] = field(default_factory=list)
    kind: list[str] = field(default_factory=list)
    x: list[list[float]] = field(default_factory=list)
    y: list[float] = field(default_factory=list)

    def arrays(self):
        return (
            np.array(self.when),
            np.array(self.kind),
            np.array(self.x, dtype=float),
            np.array(self.y),
        )


def _stream(symbol: str, iv: str, bars: Sequence[Bar]):
    """One series' bars keyed by close time.

    A function, not a generator expression inside the comprehension: that reads `symbol` and `iv`
    late, and labels every bar with the last series."""
    for bar in bars:
        yield bar.time + SECONDS[iv], symbol, iv, bar


def dataset(series: Mapping[tuple[str, str], Sequence[Bar]]) -> Rows:
    """Features and labels for every bar of every series, replayed in time order."""
    streams = [_stream(symbol, iv, bars) for (symbol, iv), bars in series.items() if iv in SECONDS]
    model = sh.Shocks()
    per_key: dict[str, list[tuple[float, float, list[float] | None]]] = {}
    for when, symbol, iv, bar in heapq.merge(*streams, key=lambda r: r[0]):
        model.observe(symbol, iv, SECONDS[iv], when, bar.high, bar.low, bar.close)
        s = model.series.get(f"{symbol}|{iv}")
        if s is None or not s.shocks:
            continue
        per_key.setdefault(f"{symbol}|{iv}", []).append(
            (when, s.shocks[-1], list(s.latest) if s.latest else None)
        )
    out = Rows()
    for key, rows in per_key.items():
        flags = [r[1] for r in rows]
        symbol = key.split("|", 1)[0]
        for i, (when, _, x) in enumerate(rows):
            if x is None or i + sh.AHEAD >= len(rows):
                continue
            out.when.append(when)
            out.key.append(key)
            out.kind.append(kind(symbol))
            out.x.append(x)
            out.y.append(1.0 if max(flags[i + 1 : i + 1 + sh.AHEAD]) > 0 else 0.0)
    return out


def train(x: np.ndarray, y: np.ndarray, *, rows: int = 800_000, seed: int = 0) -> dict:
    """Gradient boosting on the rows given, exported as a `shared/frozen.py` spec."""
    from sklearn.ensemble import HistGradientBoostingClassifier  # training only, never at runtime

    pick = np.random.default_rng(seed).choice(len(y), min(rows, len(y)), replace=False)
    model = HistGradientBoostingClassifier(
        max_depth=4, max_iter=200, learning_rate=0.05, min_samples_leaf=300
    )
    model.fit(x[pick], y[pick])
    trees = [
        [
            [
                int(n["feature_idx"]),
                float(n["num_threshold"]),
                int(n["left"]),
                int(n["right"]),
                int(n["is_leaf"]),
                float(n["value"]),
                int(n["missing_go_to_left"]),
            ]
            for n in predictors[0].nodes
        ]
        for predictors in model._predictors
    ]
    spec = {
        "recipe": sh.RECIPE,
        "names": list(sh.NAMES),
        "baseline": float(np.ravel(model._baseline_prediction)[0]),
        "trees": trees,
        "base_rate": round(float(y.mean()), 6),
        "ahead": sh.AHEAD,
        "shock_multiple": sh.SHOCK_MULTIPLE,
        "trained": datetime.now(UTC).strftime("%Y-%m-%d"),
    }
    spec["_sklearn"] = model  # for the exactness check; dropped before the spec is written
    return spec


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Area under the ROC curve by ranks (ties averaged), without a training library."""
    pos, neg = y > 0.5, y <= 0.5
    if not pos.any() or not neg.any():
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    # average ranks over ties
    sorted_p = p[order]
    start = 0
    for end in range(1, len(p) + 1):
        if end == len(p) or sorted_p[end] != sorted_p[start]:
            ranks[order[start:end]] = (start + 1 + end) / 2.0
            start = end
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * neg.sum()))


def score(predict, x: np.ndarray, y: np.ndarray, kinds: np.ndarray) -> dict[str, float]:
    """AUC on real markets and on the synthetic controls, and the top decile's realised over
    predicted rate - the calibration a card relies on."""
    p = np.array([predict(list(row)) for row in x])
    out = {}
    for name in ("real", "synthetic"):
        m = kinds == name
        if m.sum() > 50:
            out[name] = round(auc(y[m], p[m]), 4)
    real = kinds == "real"
    if real.sum() > 50:
        top = real & (p >= np.quantile(p[real], 0.9))
        out["calibration"] = round(float(y[top].mean() / max(p[top].mean(), 1e-9)), 3)
    out["n"] = len(y)
    return out
