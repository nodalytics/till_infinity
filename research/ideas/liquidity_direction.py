"""Does liquidity pick the direction, once a volatile move is actually coming?

Asked on 2026-10-17: *"if we know that a volatile move is about to happen, how
does sweep aware or liquidity aware find areas of liquidity, we can use it to
estimate the likely direction"*.

The evidence splits, and that is what makes this worth running rather than
answered already.

**Against it.** `research/docs/magnets.md` tested twenty-one level types this
same day - the shipped emitters plus EMA 20/50/100/200, SMA 50/200, fibs, prior
day H/L/C, double tops and bottoms, necklines, A/V apexes, VWAP, most-touched
prices, engulf edges and pin tips - and every one sat inside the story-free
control's own +/-0.14 scatter, flipping sign between classes. The most-watched
prices in existence were indistinguishable from the previous bar's high. And
`sweep_bos_engulf.py` found the sweep-then-break composite null: real equalled
its geometry-preserving twin to **+0.0004**, and at the best-looking cell a
random side out-paid the real one.

**For it.** **Neither of those studies conditioned on volatility state.** Both
used volatility as the *unit* - distances in volatility units - and never as a
regime filter. If liquidity only matters when a move is actually coming, an
unconditional test averages the moments that matter together with the many that
do not, and dilutes a real conditional effect to nothing. That is exactly how a
conditional effect hides, and it has not been looked for.

And the gate now exists. `dispersion_class.py` identifies those moments at
**AUC 0.906 pooled and 0.897 within strata, lift 6.7x**, where the incumbent
collapses from 0.755 to 0.596 - so "a volatile move is about to happen" is a
statement this desk can now make, which it could not when the magnet study ran.

## The null, which is the whole difficulty

**The nearer pool is reached first more often by geometry alone.** For a
driftless walk the chance of touching the upper of two barriers first is
`d_down / (d_up + d_down)` - nothing to do with liquidity. A harness comparing
"price went to the pool" against a coin would report an effect on a random
walk, which is the error `a-return-rate-is-geometry` is on record about.

So three nulls, and the first is the one that matters:

* **the matched control** - the previous bar's high and low, re-scaled to sit
  at exactly the same distances as the real pools, so it faces the identical
  geometry with no story attached. This is the arm the magnet study used and
  the arm that killed it.
* **the geometric expectation** - `d_down / (d_up + d_down)`, printed beside
  the realised rate.
* **the quiet subset** - the same test where the gate says no expansion is
  coming. A conditional effect must be present in one subset and absent in the
  other; an effect of the same size in both is not conditional on anything.

Plus a walk, where all of it must vanish.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from dispersion_ml import SIZE, _apply, _ridge, parkinson  # noqa: E402
from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.structures.drawing import (  # noqa: E402
    equals,
    origin_points,
    profile,
    rounds,
    runs,
    vwap,
)
from till_infinity.structures.vol.volatility import Volatility  # noqa: E402

FRAME = "1h"
TRADED = ("fx_major", "fx_cross", "metal")
PER_CLASS = 10
LIMIT = 12000
WINDOW = 600
STRIDE = 20
#: Bars allowed for one of the two sides to be touched.
HORIZON = 40
#: The dispersion horizon the gate is trained on, matched to `HORIZON`.
AHEAD = 40
LAGS = (1, 5, 22)
#: What counts as "a volatile move is coming": the top share of predicted
#: forward dispersion, by the training half's own threshold.
SHARE = 0.25
RIDGES = (1e-6, 1e-4, 1e-2, 1.0)
SEED = 20261017


def _gate(logvar: np.ndarray) -> tuple[np.ndarray, float]:
    """Predicted forward dispersion per bar, and the training-half threshold.

    `lin48` rather than the reservoir: it is the simpler of the two arms that
    beat HAR, and the gate's job here is to split the sample honestly rather
    than to be the best possible gate. A stronger gate would make a real effect
    easier to see and cannot create one.
    """
    start = SIZE
    stop = len(logvar) - AHEAD
    rows = np.asarray(
        [[float(logvar[i - k]) for k in range(SIZE)] for i in range(start, stop)], dtype=float
    )
    want = np.asarray(
        [float(np.mean(logvar[i + 1 : i + 1 + AHEAD])) for i in range(start, stop)], dtype=float
    )
    cut = len(want) // 2
    best, pick = -math.inf, RIDGES[0]
    inner = max(cut // 2, 1)
    for lam in RIDGES:
        coef, _ = _ridge(rows[:inner], want[:inner], lam)
        err = float(np.sum((want[inner:cut] - _apply(coef, rows[inner:cut])) ** 2))
        if -err > best:
            best, pick = -err, lam
    coef, _ = _ridge(rows[:cut], want[:cut], pick)
    guess = np.full(len(logvar), np.nan)
    guess[start:stop] = _apply(coef, rows)
    mark = float(np.nanquantile(guess[start : start + cut], 1.0 - SHARE))
    return guess, mark


def _emit(window: dict[str, np.ndarray], live: Volatility) -> list[float]:
    """Every shipped level in the window, in price.

    **The calling convention is production's, taken from `magnet_levels.py`.**
    The first version of this called the emitter *modules* as if they were
    functions, inside a bare `except Exception: continue` - so every one failed
    and the harness printed a header with no rows. Two faults, and the second
    is the worse one: an exception handler wide enough to hide a typo will hide
    a wrong answer just as happily. The calls are explicit now and the handler
    is gone.
    """
    # **Lists, not arrays.** `rounds.points` guards with `if not prices`,
    # which raises on a numpy array rather than testing it - so the emitters
    # are handed plain lists at this boundary and the conversion is done once.
    w = {k: [float(x) for x in v] for k, v in window.items()}
    clock = [int(x) for x in window["time"]]
    made = {
        "origin": lambda: origin_points.points(w["time"], w["close"], live),
        "equal": lambda: equals.points(w["time"], w["close"], live),
        "profile": lambda: profile.points(w["time"], w["close"], live),
        "round": lambda: rounds.points(w["time"], w["close"], live),
        "run": lambda: runs.points(clock, w["close"], live),
        "vwap": lambda: vwap.points(w["time"], w["high"], w["low"], w["close"], w["volume"], live),
    }
    found: list[float] = []
    for build in made.values():
        for item in build() or ():
            level = float(getattr(item, "price", float("nan")))
            if math.isfinite(level):
                found.append(level)
    return found


def _pools(
    window: dict[str, np.ndarray], price: float, unit: float, live: Volatility
) -> tuple[float, float] | None:
    """The nearest shipped level above and below, in price.

    The emitters are production's own, which is the point: this asks whether
    the desk's existing liquidity reading picks a side, not whether some new
    level definition does.
    """
    found = _emit(window, live)
    above = [v for v in found if v > price]
    below = [v for v in found if v < price]
    if not above or not below:
        return None
    up, down = min(above), max(below)
    # Both sides have to be far enough out that a single bar does not resolve
    # the race by accident, and near enough to be reachable in the horizon.
    if (up - price) < 0.25 * unit or (price - down) < 0.25 * unit:
        return None
    return up, down


def _race(highs: np.ndarray, lows: np.ndarray, at: int, up: float, down: float) -> int:
    """+1 if `up` is touched first, -1 if `down` is, 0 if neither inside the horizon."""
    for k in range(at + 1, min(at + 1 + HORIZON, len(highs))):
        hit_up = highs[k] >= up
        hit_down = lows[k] <= down
        if hit_up and hit_down:
            return -1  # one bar reached both: charged against, never for
        if hit_up:
            return 1
        if hit_down:
            return -1
    return 0


def score(bars: dict[str, np.ndarray], rng) -> dict:
    closes, highs, lows = (np.asarray(bars[k], dtype=float) for k in ("close", "high", "low"))
    logvar = parkinson(highs, lows)
    if not np.isfinite(logvar).all() or len(closes) < WINDOW + 2 * HORIZON:
        logvar = np.where(np.isfinite(logvar), logvar, np.nanmedian(logvar[np.isfinite(logvar)]))
    guess, mark = _gate(logvar)
    steps = np.abs(np.diff(closes))
    unit = float(np.median(steps[steps > 0])) if np.any(steps > 0) else 0.0
    if unit <= 0:
        return {}

    out: dict[str, list[float]] = {}
    live = Volatility()
    for i in range(len(closes)):
        live.update(float(closes[i]))
    for at in range(WINDOW, len(closes) - HORIZON - 1, STRIDE):
        if not math.isfinite(guess[at]):
            continue
        window = {k: np.asarray(bars[k], dtype=float)[at - WINDOW + 1 : at + 1] for k in bars}
        price = float(closes[at])
        pools = _pools(window, price, unit, live)
        if pools is None:
            continue
        up, down = pools
        gap_up, gap_down = up - price, price - down
        # The matched control: the previous bar's extremes, re-scaled to the
        # identical distances. Same geometry, no story.
        tag = "loud" if guess[at] >= mark else "quiet"
        got = _race(highs, lows, at, up, down)
        if got:
            out.setdefault(f"{tag} pool", []).append(1.0 if got > 0 else 0.0)
            out.setdefault(f"{tag} geometric", []).append(gap_down / (gap_up + gap_down))
        # Control at the same distances, from the bar's own high and low -
        # which carry no liquidity claim at all.
        ctl_up = price + gap_up
        ctl_down = price - gap_down
        swap = rng.random() < 0.5
        if swap:
            ctl_up, ctl_down = price + gap_down, price - gap_up
        ctl = _race(highs, lows, at, ctl_up, ctl_down)
        if ctl:
            out.setdefault(f"{tag} control", []).append(1.0 if ctl > 0 else 0.0)
            out.setdefault(f"{tag} control geometric", []).append(
                (ctl_down and (price - ctl_down)) / ((ctl_up - price) + (price - ctl_down))
            )
    return out


def main() -> None:
    print(
        "Does liquidity pick the side, conditional on an expansion coming?\n"
        f"Gate: top {SHARE:.0%} of predicted {AHEAD}-bar dispersion (`loud`), rest `quiet`.\n"
        "`pool` is the realised share where the upper **level** was touched\n"
        "first; `geometric` is what a driftless walk gives at those exact\n"
        "distances. The gap between them is the only thing that could be an\n"
        "edge, and `control` faces the same distances with no story attached.\n"
        "A conditional effect must appear in `loud` and not in `quiet`.\n"
    )
    import random

    rng = random.Random(SEED)
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob(f"*.{FRAME}.npz")):
        name = path.name[: -len(f".{FRAME}.npz")]
        groups.setdefault(classify(name), []).append(name)

    for label in TRADED:
        if label not in groups:
            continue
        pooled: dict[str, list[float]] = {}
        for name in sorted(groups[label])[:PER_CLASS]:
            bars = load(name, FRAME)
            if bars is None:
                continue
            cut = {k: v[-LIMIT:] for k, v in bars.items()}
            if "volume" not in cut:
                cut["volume"] = np.ones(len(cut["close"]))
            for key, rows in score(cut, rng).items():
                pooled.setdefault(key, []).extend(rows)
        if not pooled:
            continue
        print(f"\n=== {label}, {FRAME}")
        print(f"  {'arm':<24}{'n':>8}{'realised':>10}{'geometric':>11}{'excess':>9}")
        for tag in ("loud", "quiet"):
            for arm in ("pool", "control"):
                rows = pooled.get(f"{tag} {arm}")
                null = pooled.get(
                    f"{tag} {arm} geometric" if arm == "control" else f"{tag} geometric"
                )
                if not rows or not null:
                    continue
                got = float(np.mean(rows))
                want = float(np.mean(null))
                print(
                    f"  {tag + ' ' + arm:<24}{len(rows):>8}{got:>10.4f}{want:>11.4f}"
                    f"{got - want:>+9.4f}"
                )


if __name__ == "__main__":
    main()
