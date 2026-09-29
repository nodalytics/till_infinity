"""Train and score the band-touch forecaster (`structures/learning/touches.py`) from bar history.

Every FX 15m series is replayed through the production pieces in the order the engine runs them:
- the rollover trim (`structures/rollover.py`);
- the volatility unit (`Ranges.ewma_tr_bps`, what `Volatility.ewma_tr_bps` returns);
- the envelope book (`vol/envelope.py`, AgACI and all);
- `Touches`.

So a retrained model is trained on exactly the features and bands the engine will hand it. The
labels are whether the next `AHEAD` bars' highs reach the P90 quoted at the bar's close, and their
lows the P10. The reference is **geometry**: the same boosting on the band distances alone
(`touches.GEOMETRY`), so skill is what the market adds beyond how far away the bands are.
Measured first in `research/docs/bandrace.md`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise

import numpy as np

from ..prices.models import Bar
from ..structures import rollover as ro
from ..structures.learning import touches as tc
from ..structures.vol import envelope as ev
from ..structures.vol.ranges import Ranges

SECONDS = 900.0
GEOMETRY_COLUMNS = [tc.NAMES.index(n) for n in tc.GEOMETRY]


@dataclass
class Rows:
    """One row per scored bar: when, which series, the features, both labels."""

    when: list[float] = field(default_factory=list)
    key: list[str] = field(default_factory=list)
    x: list[list[float]] = field(default_factory=list)
    touch90: list[float] = field(default_factory=list)
    touch10: list[float] = field(default_factory=list)

    def arrays(self):
        return (
            np.array(self.when),
            np.array(self.x, dtype=float),
            np.array(self.touch90),
            np.array(self.touch10),
        )


def _series(symbol: str, bars: Sequence[Bar], out: Rows) -> None:
    """One series through the production pieces, its rows appended to `out`.

    A function per series, not a generator expression inside a comprehension: those bind the
    series name late (the bug `shocks_train._stream` records)."""
    feed = symbol.lower()
    ranges, book, model = Ranges(), ev.Book(), tc.Touches()
    pending: list[tuple[float, list[float], float, float]] = []  # when, x, P90, P10 prices
    highs: list[float] = []
    lows: list[float] = []
    for bar in bars:
        high, low, close = ro.trimmed(
            feed, bar.time, bar.time + SECONDS, bar.open, bar.high, bar.low, bar.close
        )
        ranges.observe(bar.open, high, low, close)
        highs.append(high)
        lows.append(low)
        bps = ranges.ewma_tr_bps
        if not (bps > 0 and close > 0):
            pending.append((0.0, [], 0.0, 0.0))
            continue
        sigma = bps / 10_000
        book.observe(feed, tc.INTERVAL, close, sigma)
        env = book.envelopes.get(f"{feed}|{tc.INTERVAL}|{tc.AHEAD}")
        quote = list(env.quote) if env is not None and env.warm else None
        model.observe(feed, tc.INTERVAL, bar.time, high, low, close, sigma, quote)
        s = model.series.get(f"{feed}|{tc.INTERVAL}")
        if s is None or not s.latest or quote is None:
            pending.append((0.0, [], 0.0, 0.0))
            continue
        pending.append(
            (
                float(bar.time),
                list(s.latest),
                close * math.exp(quote[2] * sigma),
                close * math.exp(quote[0] * sigma),
            )
        )
    for i, (when, x, up, down) in enumerate(pending):
        if not x or i + tc.AHEAD >= len(pending):
            continue
        out.when.append(when)
        out.key.append(feed)
        out.x.append(x)
        out.touch90.append(1.0 if max(highs[i + 1 : i + 1 + tc.AHEAD]) >= up else 0.0)
        out.touch10.append(1.0 if min(lows[i + 1 : i + 1 + tc.AHEAD]) <= down else 0.0)


def dataset(series: Mapping[tuple[str, str], Sequence[Bar]]) -> Rows:
    """Features and both labels for every FX 15m series given; everything else is skipped."""
    out = Rows()
    for (symbol, interval), bars in series.items():
        if tc.applies(symbol.lower(), interval):
            _series(symbol, bars, out)
    return out


def train(x: np.ndarray, y: np.ndarray, *, rows: int = 800_000, seed: int = 0) -> dict:
    """Gradient boosting on the rows given, exported as a `shared/frozen.py` spec."""
    from sklearn.ensemble import HistGradientBoostingClassifier  # training only

    pick = np.random.default_rng(seed).choice(len(y), min(rows, len(y)), replace=False)
    model = HistGradientBoostingClassifier(
        max_depth=4, max_iter=200, learning_rate=0.05, min_samples_leaf=300
    )
    model.fit(x[pick], y[pick])
    spec = {
        "recipe": tc.RECIPE,
        "names": list(tc.NAMES),
        "baseline": float(np.ravel(model._baseline_prediction)[0]),
        "trees": [
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
        ],
        "base_rate": round(float(y.mean()), 6),
        "ahead": tc.AHEAD,
        "trained": datetime.now(UTC).strftime("%Y-%m-%d"),
    }
    spec["_sklearn"] = model  # for the exactness check; dropped before the spec is written
    return spec


def geometry(x: np.ndarray, y: np.ndarray, *, seed: int = 0):
    """The reference: the same boosting on the band distances alone. Returns a predict function
    taking full feature rows."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    model = HistGradientBoostingClassifier(
        max_depth=4, max_iter=200, learning_rate=0.05, min_samples_leaf=300, random_state=seed
    )
    model.fit(x[:, GEOMETRY_COLUMNS], y)
    return lambda rows: model.predict_proba(rows[:, GEOMETRY_COLUMNS])[:, 1]


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """The worst decile's |realised - predicted| / predicted."""
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    worst = 0.0
    for lo, hi in pairwise(edges):
        m = (p >= lo) & (p <= hi)
        if m.sum() > 20 and p[m].mean() > 0:
            worst = max(worst, abs(y[m].mean() - p[m].mean()) / p[m].mean())
    return float(worst)


def score(
    p: np.ndarray, p_geo: np.ndarray, y: np.ndarray, when: np.ndarray, *, seed: int = 0
) -> dict[str, float]:
    """Brier skill over geometry, its standard error over whole days, and calibration."""
    b_geo = brier(y, p_geo)
    skill = 1.0 - brier(y, p) / b_geo if b_geo > 0 else float("nan")
    days = (when // 86_400).astype(int)
    uniq = np.unique(days)
    rng = np.random.default_rng(seed)
    by = {d: np.flatnonzero(days == d) for d in uniq}
    draws = []
    for _ in range(200):
        idx = np.concatenate([by[d] for d in rng.choice(uniq, len(uniq))])
        bg = brier(y[idx], p_geo[idx])
        draws.append(1.0 - brier(y[idx], p[idx]) / bg if bg > 0 else float("nan"))
    return {
        "skill": round(skill, 4),
        "skill_se": round(float(np.nanstd(draws)), 4),
        "calibration": round(calibration(y, p), 3),
        "rate": round(float(y.mean()), 4),
        "n": len(y),
    }
