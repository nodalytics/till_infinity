"""Train and score the band-touch forecaster (`structures/learning/touches.py`) from bar history.

Every FX 15m series is replayed through the production pieces in the order the engine runs them:
- the rollover trim (`structures/rollover.py`);
- the volatility unit (`Ranges.ewma_tr_bps`, what `Volatility.ewma_tr_bps` returns);
- `Touches.advance` and its base features;
- the envelope book (`vol/envelope.py`, AgACI and all, boosted where its model ships);
- `Touches.hold` on the bands just quoted.

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
        # In the engine's order: the features, the envelope reading them (boosted where a model
        # ships), then the touch features on the bands just quoted.
        taken = model.advance(feed, tc.INTERVAL, bar.time, high, low, close, sigma)
        book.observe(
            feed, tc.INTERVAL, close, sigma, model.base(feed, tc.INTERVAL) if taken else None
        )
        env = book.envelopes.get(f"{feed}|{tc.INTERVAL}|{tc.AHEAD}")
        quote = list(env.quote) if env is not None and env.warm else None
        if taken:
            model.hold(feed, tc.INTERVAL, quote)
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


def deciles(
    y: np.ndarray,
    p: np.ndarray,
    when: np.ndarray,
    *,
    bins: int = 10,
    draws: int = 200,
    seed: int = 0,
) -> list[dict[str, float]]:
    """Per predicted-probability decile: mean predicted, realised, n, the relative error, and the
    standard error of (realised - predicted) from a bootstrap over whole days.

    Days, not rows: overlapping 5-bar windows and a fortnight's shared regime make neighbouring
    rows one draw, not many."""
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    which = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, bins - 1)
    days = (when // 86_400).astype(int)
    uniq = np.unique(days)
    by = {d: np.flatnonzero(days == d) for d in uniq}
    rng = np.random.default_rng(seed)
    gaps = np.full((draws, bins), np.nan)
    for k in range(draws):
        idx = np.concatenate([by[d] for d in rng.choice(uniq, len(uniq))])
        for b in range(bins):
            m = idx[which[idx] == b]
            if len(m):
                gaps[k, b] = y[m].mean() - p[m].mean()
    out = []
    for b in range(bins):
        m = which == b
        if not m.any():
            continue
        pred, real = float(p[m].mean()), float(y[m].mean())
        out.append(
            {
                "predicted": round(pred, 4),
                "realised": round(real, 4),
                "n": int(m.sum()),
                "error": round(abs(real - pred) / pred, 4) if pred > 0 else float("nan"),
                "se": round(float(np.nanstd(gaps[:, b])), 4),
            }
        )
    return out


#: A decile is miscalibrated only if its relative error exceeds `CAL_ERROR` AND its gap is more than
#: `CAL_SIGMAS` day-bootstrap standard errors from zero; a model fails calibration with more than
#: `CAL_TOLERATED` such deciles, judged over `CAL_DAYS` out of sample. Set 2026-09-29:
#: - 14 days cannot judge calibration: over the 20 fortnights of a 40% test block a well-calibrated
#:   model (0 failing deciles pooled) failed a fortnight's test about half the time, because a
#:   fortnight's days share one regime and shift every decile together; isotonic recalibration on
#:   the preceding 8 weeks did not help (8-10 of 20 still failed).
#: - 90 days can: older 90-day blocks passed with 0 failing deciles.
#: - one decile tolerated: ten tests at about 2 standard errors produce at least one false failure
#:   about 37% of the time, so zero tolerance rejects good models on multiplicity alone.
CAL_ERROR, CAL_SIGMAS, CAL_TOLERATED, CAL_DAYS = 0.20, 2.0, 1, 90


def miscalibrated(table: list[dict[str, float]]) -> list[dict[str, float]]:
    """The deciles that fail: relative error above `CAL_ERROR` and the gap beyond noise."""
    return [
        d
        for d in table
        if d["error"] > CAL_ERROR and abs(d["realised"] - d["predicted"]) > CAL_SIGMAS * d["se"]
    ]


def calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """The worst decile's |realised - predicted| / predicted, noise and all. Reported, not gated."""
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    worst = 0.0
    for lo, hi in pairwise(edges):
        m = (p >= lo) & (p <= hi)
        if m.sum() > 20 and p[m].mean() > 0:
            worst = max(worst, abs(y[m].mean() - p[m].mean()) / p[m].mean())
    return float(worst)


def score(
    p: np.ndarray,
    p_geo: np.ndarray,
    y: np.ndarray,
    when: np.ndarray,
    *,
    base: float | None = None,
    seed: int = 0,
) -> dict[str, float]:
    """Brier skill over geometry and over the training base rate `base` (the constant a card
    would otherwise print), their standard errors over whole days, and calibration."""
    b_geo = brier(y, p_geo)
    skill = 1.0 - brier(y, p) / b_geo if b_geo > 0 else float("nan")
    p_rate = np.full(len(y), float(y.mean()) if base is None else float(base))
    b_rate = brier(y, p_rate)
    skill_rate = 1.0 - brier(y, p) / b_rate if b_rate > 0 else float("nan")
    days = (when // 86_400).astype(int)
    uniq = np.unique(days)
    rng = np.random.default_rng(seed)
    by = {d: np.flatnonzero(days == d) for d in uniq}
    draws, draws_rate = [], []
    for _ in range(200):
        idx = np.concatenate([by[d] for d in rng.choice(uniq, len(uniq))])
        bg = brier(y[idx], p_geo[idx])
        draws.append(1.0 - brier(y[idx], p[idx]) / bg if bg > 0 else float("nan"))
        br = brier(y[idx], p_rate[idx])
        draws_rate.append(1.0 - brier(y[idx], p[idx]) / br if br > 0 else float("nan"))
    table = deciles(y, p, when, seed=seed)
    return {
        "skill": round(skill, 4),
        "skill_se": round(float(np.nanstd(draws)), 4),
        "skill_rate": round(skill_rate, 4),
        "skill_rate_se": round(float(np.nanstd(draws_rate)), 4),
        "calibration": round(calibration(y, p), 3),
        "miscalibrated_deciles": len(miscalibrated(table)),
        "rate": round(float(y.mean()), 4),
        "n": len(y),
    }
