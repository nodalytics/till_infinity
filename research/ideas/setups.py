"""Entry and exit rules a competent retail trader would use, scored against geometry.

Asked across 2026-10-17: *"keep testing different entry and exit conditions
until we get what we want in RR and the win rate is high too"*, with OHLCV,
multi-timeframe and fractality available, and then *"we can start from the
mindset and approaches and improve on it fast"*.

So this starts from the approach rather than from a model: higher-timeframe
bias, an entry on a pullback, a stop beyond the swing that would disprove the
idea, and a target at a fixed reward or at the next structure. Every piece of
that is a rule here, and every rule is scored the same way.

## The one number, and why it is the only one

**A win rate and a reward are not independent.** On a driftless market the
chance of reaching the target before the stop is exactly `1 / (1 + r)`: 33% at
1:2, 25% at 1:3, 9% at 1:10. So "a high win rate **at** a high reward" is not a
setup to be found among entry rules - it is directional edge under another
name. Every row below therefore reports

    win - geometric

where `geometric` is averaged over each trade's **own** realised reward, since
a structural stop makes every trade's geometry different. That difference is
the only quantity that can be an edge. A rule with a 70% win rate at 1:0.4 and
a rule with a 9% win rate at 1:10 are **the same rule** by this measure, and
the point of the column is that it says so.

## The nulls

* **the flip.** Every setup is scored again with its side reversed. If a rule
  has no directional content, flipping pays the same, and the pair straddles
  zero. This is the sharpest null available for an entry rule and it costs
  nothing.
* **`all`.** Taking every bar, same geometry. A rule that does not beat
  "always on" has selected nothing.
* **the walk.** Generated bars through the identical pipeline, where every
  reading must collapse to the geometry.

## What is deliberately not here

No level-based entry, because `magnets.md` measured twenty-one kinds against a
story-free control and every one sat inside its noise. No named candle pattern,
because `sweep_bos_engulf.py` found them level with geometry-preserving twins.
What is here is **structure** - the directional-change decomposition, which is
scale-free and is v1's own turn rule generalised - and **dispersion**, which is
the one forecastable quantity on this desk.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from dispersion_ml import SIZE, _apply, _ridge, parkinson  # noqa: E402
from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.structures.statespace.pivoting import pivots  # noqa: E402

FRAME = "1h"
#: The higher timeframe, for bias. Multi-timeframe is the first thing a
#: competent retail approach does, so it is an arm rather than an assumption.
HIGHER = "4h"
TRADED = ("fx_major", "fx_cross", "metal")
PER_CLASS = 8
LIMIT = 12000
#: Directional-change thresholds, in volatility units. **Fractality**: the same
#: rule at several scales, which is what the intrinsic-time framework is for.
EDGES = (1.0, 2.0, 4.0)
#: Reward multiples, and the hold in bars.
REWARDS = (1.0, 2.0, 3.0, 5.0)
HOLD = 120
#: Round-trip cost in volatility units. Not zero, because
#: `exotic-spreads-are-a-whole-bar-range` makes cost decisive.
COST = 0.05
SEED = 20261017


def _unit(closes: np.ndarray) -> float:
    steps = np.abs(np.diff(closes))
    return float(np.mean(steps[steps > 0])) if np.any(steps > 0) else 0.0


def _dispersion(logvar: np.ndarray) -> np.ndarray:
    """Forecast forward dispersion with the arm that measured best, causally."""
    start, stop = SIZE, len(logvar) - HOLD
    if stop - start < 400:
        return np.full(len(logvar), np.nan)
    rows = np.asarray(
        [[float(logvar[i - k]) for k in range(SIZE)] for i in range(start, stop)], dtype=float
    )
    want = np.asarray(
        [float(np.mean(logvar[i + 1 : i + 1 + HOLD])) for i in range(start, stop)], dtype=float
    )
    cut = len(want) // 2
    coef, _ = _ridge(rows[:cut], want[:cut], 1e-4)
    out = np.full(len(logvar), np.nan)
    out[start:stop] = _apply(coef, rows)
    return out


def _structure(bars: dict[str, np.ndarray], edge: float) -> list:
    """Directional-change pivots on log prices, so a swing is scale-free."""
    closes = np.asarray(bars["close"], dtype=float)
    if np.any(closes <= 0):
        return []
    logs = {
        k: np.log(np.maximum(np.asarray(bars[k], dtype=float), 1e-300))
        for k in ("close", "high", "low")
    }
    unit = _unit(logs["close"])
    if unit <= 0:
        return []
    return pivots(
        [float(v) for v in bars["time"]],
        [float(v) for v in logs["high"]],
        [float(v) for v in logs["low"]],
        unit=unit,
        threshold=edge,
    )


def _bias(higher: list, when: float) -> int:
    """The higher timeframe's last **confirmed** direction at `when`, or 0.

    Confirmed, not current: a pivot is knowable only at its confirmation time,
    and using the extreme's own time is the leak `pivoting.Pivot` carries two
    timestamps to prevent.
    """
    side = 0
    for one in higher:
        if one.confirmed > when:
            break
        # A confirmed peak ends an up-leg, so the bias after it is down.
        side = -1 if one.peak else 1
    return side


def run(bars: dict[str, np.ndarray], higher: dict[str, np.ndarray], rng) -> dict:
    """Every entry rule by every exit geometry, with the flip arm beside it."""
    closes = np.asarray(bars["close"], dtype=float)
    highs = np.asarray(bars["high"], dtype=float)
    lows = np.asarray(bars["low"], dtype=float)
    unit = _unit(closes)
    if unit <= 0 or len(closes) < 2000:
        return {}
    logvar = parkinson(highs, lows)
    logvar = np.where(np.isfinite(logvar), logvar, np.nanmedian(logvar[np.isfinite(logvar)]))
    forecast = _dispersion(logvar)
    loud = float(np.nanquantile(forecast, 0.75)) if np.isfinite(forecast).any() else np.inf

    out: dict[tuple[str, float, float], list[tuple[float, float]]] = {}
    for edge in EDGES:
        here = _structure(bars, edge)
        there = _structure(higher, edge)
        marks = {one.confirmed_index: one for one in here}
        for at in range(SIZE + 1, len(closes) - HOLD - 1):
            one = marks.get(at)
            when = float(bars["time"][at])
            price = float(closes[at])
            # The structural stop: beyond the swing that would disprove it.
            if one is None:
                continue
            side = -1 if one.peak else 1
            # **Back to price.** The detector ran on log prices so a swing is
            # scale-free, which means every level it reports is a log price -
            # and comparing one to a close in price units made every risk about
            # 95 and every candidate fail its own filter. The conversion is
            # unconditional, not a guess from the sign.
            invalid = math.exp(one.level)
            risk = abs(price - invalid)
            if risk <= 0.2 * unit or risk > 8.0 * unit:
                continue
            bias = _bias(there, when)
            rules = {
                "structure": True,
                "agree": bias == side,
                "against": bias == -side,
                "loud": bool(np.isfinite(forecast[at]) and forecast[at] >= loud),
                "agree+loud": bias == side
                and bool(np.isfinite(forecast[at]) and forecast[at] >= loud),
            }
            for reward in REWARDS:
                stop = price - side * risk
                target = price + side * reward * risk
                got = _settle(highs, lows, at, side, stop, target, reward)
                flip = _settle(
                    highs,
                    lows,
                    at,
                    -side,
                    price + side * risk,
                    price - side * reward * risk,
                    reward,
                )
                for name, passes in rules.items():
                    if not passes:
                        continue
                    out.setdefault((name, edge, reward), []).append((got, reward))
                    out.setdefault((f"{name}~flip", edge, reward), []).append((flip, reward))
    return out


def _settle(
    highs: np.ndarray,
    lows: np.ndarray,
    at: int,
    side: int,
    stop: float,
    target: float,
    reward: float,
) -> float:
    """Realised R over the hold: `reward` on a win, -1 on a loss, 0 unresolved.

    A bar that reaches both is charged as a loss, because assuming the
    favourable order is how a backtest invents edge.
    """
    for k in range(at + 1, min(at + 1 + HOLD, len(highs))):
        hit = highs[k] >= target if side > 0 else lows[k] <= target
        out = lows[k] <= stop if side > 0 else highs[k] >= stop
        if hit and out:
            return -1.0
        if hit:
            return reward
        if out:
            return -1.0
    return 0.0


def main() -> None:
    print(
        "Entry and exit rules, scored against the geometry they carry.\n"
        f"{FRAME} entries with {HIGHER} bias, structural stops, hold {HOLD} bars,\n"
        f"cost {COST} of the stop. `win-geom` is the realised win rate less\n"
        "1/(1+r) - the only column that can be an edge. `~flip` is the same\n"
        "setup with the side reversed and must straddle zero with it.\n"
    )
    rng = random.Random(SEED)
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob(f"*.{FRAME}.npz")):
        name = path.name[: -len(f".{FRAME}.npz")]
        groups.setdefault(classify(name), []).append(name)

    for label in TRADED:
        if label not in groups:
            continue
        pooled: dict[tuple[str, float, float], list[tuple[float, float]]] = {}
        for name in sorted(groups[label])[:PER_CLASS]:
            bars = load(name, FRAME)
            above = load(name, HIGHER)
            if bars is None or above is None:
                continue
            cut = {k: v[-LIMIT:] for k, v in bars.items()}
            top = {k: v[-LIMIT:] for k, v in above.items()}
            for key, rows in run(cut, top, rng).items():
                pooled.setdefault(key, []).extend(rows)
        if not pooled:
            continue
        print(f"\n=== {label}, {FRAME}")
        print(
            f"  {'rule':<16}{'edge':>5}{'r':>4}{'n':>7}{'win':>7}{'geom':>7}{'win-geom':>10}{'mean R':>9}{'net':>8}"
        )
        for key in sorted(pooled, key=lambda k: (k[0], k[1], k[2])):
            name, edge, reward = key
            rows = pooled[key]
            if len(rows) < 60:
                continue
            wins = sum(1 for v, _ in rows if v > 0)
            resolved = sum(1 for v, _ in rows if v != 0)
            if resolved < 40:
                continue
            win = wins / resolved
            geom = 1.0 / (1.0 + reward)
            mean = sum(v for v, _ in rows) / len(rows)
            print(
                f"  {name:<16}{edge:>5.1f}{reward:>4.0f}{len(rows):>7}{win:>7.3f}{geom:>7.3f}"
                f"{win - geom:>+10.4f}{mean:>+9.4f}{mean - COST:>+8.4f}"
            )


if __name__ == "__main__":
    main()
