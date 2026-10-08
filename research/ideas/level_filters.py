"""Does a particle filter track a level better than the Kalman does?

Asked 2026-10-08: "research how we can use particle filters to improve levels,
we can run it as an alternative to kalman or even run both together".

`research/docs/structures-roadmap.md` lists particle filters among the
alternatives and parks them, on the argument that the multimodality they exist
for is usually **two levels rather than one level with two modes** - and that
the repo's answer to that is `form` and `merge`, which is the multi-object
framing. This measures the part of the claim that does not depend on that
argument: on a single level's own touches, is a particle filter more accurate?

## The control that decides what a win would mean

A particle filter differs from the Kalman in **two** ways at once - it carries a
sample instead of a Gaussian, and it can use any likelihood. If it wins and
only those two arms are run, the win is unattributable.

So there are three:

  kalman    the production filter: Gaussian innovation, exact update
  robust    the same filter with a **Huberised** innovation - same Gaussian
            sample, heavier-tailed likelihood, no particles
  particle  a sample over (price, slope) with a Student-t likelihood

`robust` is the arm that matters. If `particle` only matches it, the answer is
"use a heavier-tailed likelihood" and the particles are machinery for nothing.
Particles earn their place only by beating it.

## What is being predicted

Each filter sees a level's touches in order. After each one it must say where
the **next** touch will land, and how sure it is. Scored on:

* **median |error|**, in volatility units - median because touch errors are
  heavy-tailed and a mean would report the outliers rather than the filter
* **coverage** of its own 90% band, and the **width** it needed. Narrower at
  equal coverage is better; wider at equal coverage is the filter buying its
  coverage rather than earning it

Prediction, not fit. A filter judged on how well it explains touches it has
already folded in would pick whichever arm has the most parameters.

## Where the touches come from

The journal records a level's *estimate* but not the touch that moved it, so
the production filter cannot be replayed from it. Instead touches are
reconstructed from bars: three-bar pivots, clustered within `CLUSTER_VOL` of
each other, and each cluster with at least `MIN_TOUCHES` members is one level.

**That is a proxy for `levels.form`, not the thing itself**, and it is the main
reason to read this as a comparison between filters rather than a statement
about the production book.

  MT5BT_DB=... INTERVALS=1h,4h python research/ideas/level_filters.py
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

INTERVALS = os.environ.get("INTERVALS", "1h,4h,1d").split(",")
#: How close two pivots must be to be the same level, in volatility units.
CLUSTER_VOL = float(os.environ.get("CLUSTER_VOL", 0.75))
#: Touches a cluster needs to be worth scoring. Four gives three predictions.
MIN_TOUCHES = int(os.environ.get("MIN_TOUCHES", 5))
#: Particles.
PARTICLES = int(os.environ.get("PARTICLES", 400))
#: Student-t degrees of freedom for the particle likelihood. Low is heavy.
NU = float(os.environ.get("NU", 3.0))
#: Where the Huber loss switches from square to linear, in sigmas.
HUBER_C = float(os.environ.get("HUBER_C", 1.5))
#: How much a fully-wick turn is distrusted, as a multiple of the base noise.
#: One means a bar that is all wick at the turn is given twice the observation
#: noise of one that closed at its extreme. A guess, and the sweep that would
#: justify it has not been run - it is here as a constant so that is visible.
WICK_PENALTY = float(os.environ.get("WICK_PENALTY", 1.0))

#: Process noise per touch, in volatility units, shared by every arm so the
#: comparison is of the update and not of the tuning.
DRIFT = float(os.environ.get("DRIFT", 0.05))
#: Observation noise, in volatility units. Production uses 0.5.
NOISE = float(os.environ.get("NOISE", 0.5))
BAND = 0.90


def wick_share(open_: float, high: float, low: float, close: float, is_high: bool) -> float:
    """How much of the bar is wick on the side price turned at, in `[0, 1]`.

    One is a bar that is all wick at the turn - price went there and did not
    stay, which is the definition of a probe. Zero is a bar that closed at its
    extreme, so the turn is where trade actually happened.

    **This is the continuous form of a judgement the repo already makes.**
    `observe_touch` takes `done.origin` over `done.extreme` because "the
    extreme is a wick - liquidity taken a fraction beyond the level at a price
    nobody traded around". That is the same statement as a threshold.
    """
    span = high - low
    if span <= 0:
        return 0.0
    body_top, body_bottom = max(open_, close), min(open_, close)
    tail = (high - body_top) if is_high else (body_bottom - low)
    return min(max(tail / span, 0.0), 1.0)


def pivots(
    open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray
) -> list[tuple[int, float, float]]:
    """Three-bar swing highs and lows, as `(index, price, wick share)`."""
    out = []
    for i in range(1, len(high) - 1):
        if high[i] >= high[i - 1] and high[i] >= high[i + 1]:
            out.append((i, float(high[i]), wick_share(open_[i], high[i], low[i], close[i], True)))
        elif low[i] <= low[i - 1] and low[i] <= low[i + 1]:
            out.append((i, float(low[i]), wick_share(open_[i], high[i], low[i], close[i], False)))
    return out


def cluster(
    points: list[tuple[int, float, float]], unit: float
) -> list[list[tuple[int, float, float]]]:
    """Group pivots that sit within `CLUSTER_VOL` units of their running mean."""
    if unit <= 0:
        return []
    groups: list[list[tuple[int, float, float]]] = []
    for point in sorted(points, key=lambda p: p[1]):
        price = point[1]
        if groups and abs(price - np.mean([p for _, p, _ in groups[-1]])) <= CLUSTER_VOL * unit:
            groups[-1].append(point)
        else:
            groups.append([point])
    return [sorted(g) for g in groups if len(g) >= MIN_TOUCHES]


class Kalman:
    """The production shape: Gaussian innovation, exact update."""

    name = "kalman"

    def __init__(self, price: float, unit: float):
        self.mean, self.unit = price, unit
        self.var = (unit * 2.0) ** 2

    def predict(self) -> tuple[float, float]:
        self.var += (DRIFT * self.unit) ** 2
        return self.mean, math.sqrt(self.var + (NOISE * self.unit) ** 2)

    def _gain(self, residual: float) -> float:
        return 1.0

    def update(self, price: float) -> None:
        noise = (NOISE * self.unit) ** 2
        gain = self.var / (self.var + noise)
        residual = price - self.mean
        self.mean += gain * residual * self._gain(residual)
        self.var *= 1.0 - gain


class Robust(Kalman):
    """The same filter, with the innovation Huberised.

    One enormous wick is the thing a Gaussian update cannot survive, and this
    is the cheapest honest answer to it: trust the residual up to `HUBER_C`
    sigmas and only its direction past that. **No particles.**
    """

    name = "robust"

    def _gain(self, residual: float) -> float:
        spread = math.sqrt(self.var + (NOISE * self.unit) ** 2)
        if spread <= 0:
            return 1.0
        z = abs(residual) / spread
        return 1.0 if z <= HUBER_C else HUBER_C / z


class Particle:
    """A sample over `(price, slope)` with a Student-t likelihood."""

    name = "particle"

    def __init__(self, price: float, unit: float, seed: int = 7):
        self.unit = unit
        rng = self.rng = np.random.default_rng(seed)
        self.x = price + rng.normal(0.0, 2.0 * unit, PARTICLES)
        self.v = rng.normal(0.0, DRIFT * unit, PARTICLES)
        self.w = np.full(PARTICLES, 1.0 / PARTICLES)

    def predict(self) -> tuple[float, float]:
        self.x = self.x + self.v
        self.x += self.rng.normal(0.0, DRIFT * self.unit, PARTICLES)
        self.v += self.rng.normal(0.0, DRIFT * self.unit * 0.1, PARTICLES)
        centre = float(np.average(self.x, weights=self.w))
        spread = float(np.sqrt(np.average((self.x - centre) ** 2, weights=self.w)))
        return centre, math.sqrt(spread**2 + (NOISE * self.unit) ** 2)

    def update(self, price: float) -> None:
        scale = NOISE * self.unit
        z = (price - self.x) / max(scale, 1e-12)
        # Student-t: extreme observations happen more often than a Gaussian
        # would like to admit, and a particle far from one is not killed by it.
        like = (1.0 + z * z / NU) ** (-(NU + 1.0) / 2.0)
        w = self.w * like
        total = w.sum()
        self.w = np.full(PARTICLES, 1.0 / PARTICLES) if total <= 0 else w / total
        if 1.0 / np.sum(self.w**2) < PARTICLES / 2:  # systematic resampling
            edges = (self.rng.random() + np.arange(PARTICLES)) / PARTICLES
            take = np.searchsorted(np.cumsum(self.w), edges)
            self.x, self.v = self.x[take], self.v[take]
            self.w = np.full(PARTICLES, 1.0 / PARTICLES)


class Adaptive(Kalman):
    """The Kalman, told how much to trust each observation **before** it lands.

    `observe_touch` in production gives every touch the same observation noise,
    `(0.5v)**2`, whether it was a decisive rejection or a chaotic probe. This
    scales that by how much of the turning bar was wick:

        R = (NOISE * unit * (1 + WICK_PENALTY * wick_share)) ** 2

    **The distinction from `robust` is the whole point of running both.**
    `robust` discounts an observation for landing far from the prediction,
    which is a function of the observation itself - it can only ever say "that
    disagreed, so trust it less", which is circular in a way that flatters the
    filter. This discounts it for **looking** unreliable, from the shape of the
    bar, before anything is known about whether it agrees.

    One is a robust loss; the other is an honest prior on measurement quality.
    Only the second could be computed live without peeking at the residual.
    """

    name = "adaptive"

    def __init__(self, price: float, unit: float):
        super().__init__(price, unit)
        self.quality = 0.0

    def update(self, price: float) -> None:
        noise = (NOISE * self.unit * (1.0 + WICK_PENALTY * self.quality)) ** 2
        gain = self.var / (self.var + noise)
        self.mean += gain * (price - self.mean)
        self.var *= 1.0 - gain


ARMS = (Kalman, Robust, Particle, Adaptive)
#: The multiplier on the predicted spread that a 90% band wants if the spread
#: were Gaussian. Each arm is given the same one, so the coverage column says
#: which arm's spread is honest.
Z90 = 1.6449


def score(touches: list[tuple[float, float]], unit: float) -> list[dict]:
    """One level's touches through every arm, scored on the next touch.

    `touches` is `(price, wick share)`, oldest first. Only `adaptive` reads the
    second element; the rest are given the identical sequence, so any
    difference between them is the update and not the data.
    """
    rows = []
    for arm in ARMS:
        filt = arm(touches[0][0], unit)
        errs, inside, widths = [], [], []
        for price, quality in touches[1:]:
            centre, spread = filt.predict()
            half = Z90 * spread
            errs.append(abs(price - centre) / unit)
            inside.append(abs(price - centre) <= half)
            widths.append(2.0 * half / unit)
            if isinstance(filt, Adaptive):
                filt.quality = quality
            filt.update(price)
        rows.append(
            {
                "arm": filt.name,
                "n": len(errs),
                "err": errs,
                "inside": inside,
                "width": widths,
            }
        )
    return rows


def main() -> None:
    import run as runner
    import survivors

    from till_infinity.structures.vol.volatility import Volatility

    runner.DB = survivors.DB = os.environ.get("MT5BT_DB")
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in runner.FAMILY if s not in runner.FRESH]

    bag: dict[tuple[str, str], dict[str, list]] = {}
    levels = 0
    for iv in INTERVALS:
        for sym in syms:
            got = survivors.book_for(sym, iv)
            if got is None:
                continue
            df = got[0].bars.reset_index(drop=True)
            if len(df) < 300:
                continue
            close = df["close"].to_numpy(float)
            vol = Volatility()
            for p in close:
                vol.update(float(p))
            unit = vol.price_units(float(close[-1]), 1.0)
            if not unit or unit <= 0:
                continue
            found = cluster(
                pivots(
                    df["open"].to_numpy(float),
                    df["high"].to_numpy(float),
                    df["low"].to_numpy(float),
                    close,
                ),
                unit,
            )
            for group in found:
                levels += 1
                for row in score([(p, w) for _, p, w in group], unit):
                    key = (iv, row["arm"])
                    got_bag = bag.setdefault(key, {"err": [], "inside": [], "width": []})
                    for k in ("err", "inside", "width"):
                        got_bag[k] += row[k]

    rows = []
    for (iv, arm), v in sorted(bag.items()):
        err = np.asarray(v["err"], float)
        if len(err) < 50:
            continue
        rows.append(
            {
                "iv": iv,
                "arm": arm,
                "predictions": len(err),
                "median_err": float(np.median(err)),
                "mean_err": float(err.mean()),
                "p90_err": float(np.percentile(err, 90)),
                "coverage": float(np.mean(v["inside"])),
                "width": float(np.mean(v["width"])),
            }
        )
    t = pd.DataFrame(rows)
    if t.empty:
        print("nothing to score")
        return
    pd.set_option("display.width", 200)
    print(f"{levels} levels, {MIN_TOUCHES}+ touches each\n")
    print("error in volatility units; coverage is of each arm's own 90% band.")
    print("narrower at equal coverage is better; wider at equal coverage is the")
    print("filter buying coverage rather than earning it.\n")
    for iv in sorted(t.iv.unique()):
        print(f"--- {iv}")
        print(t[t.iv == iv].drop(columns="iv").round(4).to_string(index=False))
        print()
    print("=== does `particle` beat `robust`, which is the question ===")
    for iv in sorted(t.iv.unique()):
        g = t[t.iv == iv].set_index("arm")
        if {"particle", "robust"} <= set(g.index):
            d = g.loc["particle", "median_err"] - g.loc["robust", "median_err"]
            print(
                f"  {iv}: median error {d:+.4f} units ({'particle' if d < 0 else 'robust'} better)"
            )
    out = Path(os.environ.get("OUT", ".data/levelfilters"))
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "arms.csv", index=False)
    print(f"\nwritten: {out / 'arms.csv'}")


if __name__ == "__main__":
    main()
