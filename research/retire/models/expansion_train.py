"""Train and score the compression-to-expansion alert (`structures/learning/expansion.py`).

Every series is replayed through the production `Expansion` class itself, in time order and with
its higher timeframes interleaved, so a retrained model sees exactly what the engine hands it. A
row is a bar at which the series is compressed; its label is whether the true-range percentile
reaches `EXPANDED` within the next `AHEAD` bars. Validated in `research/docs/expansion.md`.

Two kinds of walk we generate ourselves are scored beside the markets:

  control  iid Student-t(3) walks. Memoryless, but not featureless: from a deep compression the
           smoothed range takes longer to climb back, so some skill here is mechanical and correct.
           The gate is that markets beat it by a clear margin, not that it sits at 0.5.
  garch    GARCH(1,1) walks, which cluster volatility as markets do. Reported, not gated: it shows
           how much of the skill is plain volatility clustering.
"""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from ..prices.models import Bar
from ..structures.learning import expansion as ex
from .shocks_train import auc, kind

SECONDS = {"15m": 900.0, "1h": 3600.0, "4h": 14400.0, "1d": 86400.0}
CONTROL, GARCH = "~control", "~garch"


def kind_of(symbol: str) -> str:
    if symbol.startswith(GARCH):
        return "garch"
    return kind(symbol)


def _aggregate(bars: list[Bar], k: int) -> list[Bar]:
    out = []
    for a in range(0, len(bars) - k + 1, k):
        part = bars[a : a + k]
        out.append(
            Bar(
                part[0].time,
                part[0].open,
                max(b.high for b in part),
                min(b.low for b in part),
                part[-1].close,
                None,
            )
        )
    return out


def walks(n: int = 6, bars: int = 12_000, seed: int = 0, garch: bool = False):
    """15m walks with their 1h and 4h aggregates, so the higher-timeframe feature exists."""
    rng = np.random.default_rng(seed + (1000 if garch else 0))
    out = {}
    for w in range(n):
        sub = 16
        z = rng.standard_t(3, (bars, sub)) / np.sqrt(3.0) / np.sqrt(sub)
        sig = np.full(bars, 0.001)
        if garch:
            zbar, var = z.sum(axis=1), 0.001**2
            for k in range(bars):
                sig[k] = np.sqrt(var)
                var = 0.001**2 * 0.02 + 0.06 * (sig[k] * zbar[k]) ** 2 + 0.92 * var
        path = 100.0 * np.exp(np.cumsum((z * sig[:, None]).ravel())).reshape(bars, sub)
        opens = np.r_[100.0, path[:-1, -1]]
        t0 = 1_700_000_000
        got = [
            Bar(
                t0 + 900 * k,
                float(opens[k]),
                float(max(path[k].max(), opens[k])),
                float(min(path[k].min(), opens[k])),
                float(path[k, -1]),
                None,
            )
            for k in range(bars)
        ]
        name = f"{GARCH if garch else CONTROL}-{w}"
        out[(name, "15m")] = got
        out[(name, "1h")] = _aggregate(got, 4)
        out[(name, "4h")] = _aggregate(got, 16)
        out[(name, "1d")] = _aggregate(got, 96)
    return out


def _stream(symbol: str, iv: str, bars: Sequence[Bar]):
    """One series keyed by close time. A function so `symbol` and `iv` bind now."""
    for bar in bars:
        yield bar.time + SECONDS[iv], symbol, iv, bar


@dataclass
class Rows:
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


def dataset(
    series: Mapping[tuple[str, str], Sequence[Bar]], intervals: Sequence[str] = ex.INTERVALS
) -> Rows:
    """Features and labels at every compressed bar of every series at a scored interval."""
    streams = [_stream(s, iv, b) for (s, iv), b in series.items() if iv in SECONDS]
    model = ex.Expansion()
    per_key: dict[str, list[tuple[float, float, bool, list[float] | None]]] = {}
    for when, symbol, iv, bar in heapq.merge(*streams, key=lambda r: r[0]):
        model.observe(symbol, iv, SECONDS[iv], when, bar.high, bar.low, bar.close, bar.volume)
        if iv not in intervals:
            continue
        s = model.series.get(f"{symbol}|{iv}")
        if s is None or not s.warm:
            continue
        per_key.setdefault(f"{symbol}|{iv}", []).append(
            (when, s.pct, s.compressed, list(s.latest) if s.compressed and s.latest else None)
        )
    out = Rows()
    for key, rows in per_key.items():
        pct = np.array([r[1] for r in rows])
        symbol = key.split("|", 1)[0]
        for i, (when, _, compressed, x) in enumerate(rows):
            if not compressed or x is None or i + ex.AHEAD >= len(rows):
                continue
            out.when.append(when)
            out.key.append(key)
            out.kind.append(kind_of(symbol))
            out.x.append(x)
            out.y.append(1.0 if pct[i + 1 : i + 1 + ex.AHEAD].max() >= ex.EXPANDED else 0.0)
    return out


def train(x: np.ndarray, y: np.ndarray, *, rows: int = 800_000, seed: int = 0) -> dict:
    """Gradient boosting, exported as a `shared/frozen.py` spec (logit link)."""
    from sklearn.ensemble import HistGradientBoostingClassifier  # training only

    pick = np.random.default_rng(seed).choice(len(y), min(rows, len(y)), replace=False)
    model = HistGradientBoostingClassifier(
        max_depth=4, max_iter=200, learning_rate=0.05, min_samples_leaf=300
    )
    fit = x[pick].copy()
    fit[:, np.all(np.isnan(fit), axis=0)] = 0.0
    model.fit(fit, y[pick])
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
        "recipe": ex.RECIPE,
        "names": list(ex.NAMES),
        "baseline": float(np.ravel(model._baseline_prediction)[0]),
        "trees": trees,
        "base_rate": round(float(y.mean()), 6),
        "ahead": ex.AHEAD,
        "trained": datetime.now(UTC).strftime("%Y-%m-%d"),
    }
    spec["_sklearn"] = model
    return spec


def score(predict, x: np.ndarray, y: np.ndarray, kinds: np.ndarray) -> dict[str, float]:
    """AUC per kind, the top decile's lift and calibration on real markets."""
    p = np.array([predict(list(row)) for row in x])
    out: dict[str, float] = {}
    for name in ("real", "deriv", "control", "garch"):
        m = kinds == name
        if m.sum() > 50 and 0 < y[m].mean() < 1:
            out[name] = round(auc(y[m], p[m]), 4)
    real = kinds == "real"
    if real.sum() > 50:
        top = real & (p >= np.quantile(p[real], 0.9))
        out["calibration"] = round(float(y[top].mean() / max(p[top].mean(), 1e-9)), 3)
        out["top_lift"] = round(float(y[top].mean() / max(y[real].mean(), 1e-9)), 3)
        out["base_rate_real"] = round(float(y[real].mean()), 4)
    out["n"] = len(y)
    return out
