"""Reversion as a cycle: at what horizon, if any, does variance stop scaling?

Reversion has been refuted here **as a distance effect**. The shuffled twin
took +0.111 of a +0.137 trailing-z-score effect
(`trailing-zscore-fakes-reversion`); the origin's 82% return rate is matched by
a distance-matched placebo and a walk reads 0.825
(`a-return-rate-is-geometry`); and tonight's cross-section had `reversal 1d` at
**t -1.89** and `reversal 1d | illiquid` at **t -2.41** on 433 daily equities -
short-horizon reversal is *negative*, it is continuation.

"Reversion is a short-term cycle" is a different claim, and it needs a
different instrument. A cycle is not "price far from its mean comes back", it
is "variance stops accumulating at some horizon and starts cancelling". That
is the **variance ratio**:

    VR(k) = Var(k-bar return) / (k * Var(1-bar return))

which is exactly **1** for a walk at every k, **below 1** where increments
cancel, and **above 1** where they compound. Sweeping k traces the time scale
directly, so the k that minimises VR *is* the reversion horizon - the lens
asked for, rather than a threshold on a distance.

It is also the right instrument because nothing is smoothed. A periodogram or a
band-pass would invite Slutsky-Yule, where a moving average of noise
manufactures a cycle that was never there, and
`null-structure-claims-on-the-same-detector` would then require running the
walk through the identical filter to say anything at all. VR needs no filter.

## Four arms, and the shortest lag is the dangerous one

* **shuffled** - the feed's own returns permuted. Kills all ordering, keeps the
  marginal distribution exactly, so the fat tails and the unconditional
  variance are untouched. VR must read 1, and the spread of 200 shuffles is the
  standard error every z here is formed against. This is the null, not a
  Gaussian approximation, because `overlapping-windows-inflate-permutation-
  nulls` applies to the overlapping k-bar windows the numerator uses.
* **block** - a block bootstrap at length 8. It preserves dependence *shorter*
  than a block and destroys everything longer, so comparing it against
  `shuffled` localises the horizon of whatever is found rather than only
  detecting it.
* **walk** - GBM at matched length and bar count. VR must read 1 at every k,
  and it is the arm that catches an implementation error rather than a market
  effect.
* **deseasonalised** - each return divided by its own hour-of-day standard
  deviation before VR. `seasonality-belongs-on-q` put the intraday pattern in
  volatility, FX peaking 14-15 UTC at 3x, and
  `a-pair-of-bars-needs-the-hour-of-day-null` found ordering suppressing
  two-bar statistics by 0.046-0.072 with **half of it the daily cycle**. A
  seasonal in variance does not cancel between VR's numerator and denominator,
  so without this arm a session pattern reads as a reversion cycle.

## Bid-ask bounce imitates reversion at EVERY horizon, not just the shortest

This was measured rather than assumed, and it refuted the obvious guess. Bounce
puts a negative first-order autocorrelation into close-to-close returns
mechanically - the close prints alternately at bid and ask - and the natural
expectation is a dent at `k=2` that decays away. It does not decay. Planted on
a walk with a half-spread of half the bar sigma, this harness's own estimator
reads:

| k | 2 | 3 | 5 | 8 | 13 | 21 | 34 | 55 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bounce on a walk | 0.836 | 0.781 | 0.742 | 0.718 | 0.706 | 0.697 | 0.688 | 0.685 |

**It falls monotonically**, because the bounce adds a fixed `2s^2` to every
k-bar sum's variance while the denominator's `k * Var(1)` grows linearly in k.
So `VR -> sigma^2 / (sigma^2 + 2 s^2)`, a floor of 0.667 at these parameters,
and the table lands on it. A VR curve declining from 0.84 to 0.69 is exactly
what a reversion result is supposed to look like.

**The discriminator is the shape, not the level.** A genuinely mean-reverting
price has no floor - the OU arm above reads 0.346 at k=55 and is still falling,
because a stationary price must drive VR to zero. Bounce flattens onto its
floor. So the two are separable, but only by sweeping k far enough to see
whether the curve bottoms out.

### The mid-of-range arm was a worse artefact, and is kept only as a warning

`(high + low) / 2` was the obvious bounce-free price - neither extreme is a
transaction-side print - and it is **invalid**. In a directional bar the high
sits near the close and the low near the open, so the mid is about `(O + C)/2`;
with no gaps `O[t+1] = C[t]`, which makes

    mid[t+1] - mid[t] = (C[t+1] - O[t]) / 2

**half a two-bar overlapping return**. Overlapping returns are positively
autocorrelated by construction, so VR climbs mechanically: this harness read
**1.249 at k=2 rising to 1.411 at k=21, z +225**, on a pooled traded set whose
closes read 0.984. The docstring above argues VR is the right instrument
*because nothing is smoothed*, and the arm smoothed it.

**The tell was available and unused: the mid arm was never run on the
controls.** `Volatility_N_Index` is i.i.d. by construction, so a mid arm there
reads the same inflation and exposes it immediately. The arm is therefore
retained and now computed on every generated series too, where any reading
away from 1.0 is the artefact and nothing else - a control needs its own
control.

### The bounce test that works is cross-instrument

Bounce scales with the half-spread relative to the bar's own volatility, so if
the VR deficit is microstructure it must **order instruments by that ratio**.
The ranking needs no unit conversion, which is what makes it safe:
`spread-column-is-in-points` records EURUSD reading a 476% round trip from
converting that column to price, and the error reorders instruments by cost.
Used as a rank against a rank, the column cannot do that damage.

The 1h run already hints at the answer. EURGBP, the widest spread relative to
its own volatility of any pair carried, is the most negative at **0.845** by
k=55, while USDJPY and Germany_40 - both tight relative to volatility - are the
only series that *trend*. If that ordering holds, close-based reversion here is
a cost, not an edge.

## The two known generators that decide whether the detector works

* **`Range_Break_100_Index` / `Range_Break_200_Index`** - a range by
  construction, so genuinely mean-reverting with a characteristic time. This is
  the **positive control**, and at 1h it **did not fire**: 1.001 at k=2 to
  0.978 at k=55, essentially nothing. The estimator is not blind - the OU arm
  in the smoke test reads 0.346 - so this is a frame mismatch, those ranges
  cycling far faster than an hour. A null from this harness at 1h is therefore
  **not licensed**, per `show-power-before-reporting-a-null`, until the control
  fires at a frame it can fire in. `FRAME` is an environment variable for
  exactly that reason.
* **`Volatility_N_Index`** - constant nominal volatility, i.i.d. increments. The
  **negative control**: VR must read 1 at every k. Tonight's
  `regime-granularity.md` measured these as having no cross-sectional structure
  whatever, so anything found here is in the time axis alone.

Boom, Crash, Jump and Step are carried as further generated arms rather than as
controls for this property, because none of them is specified as range-bound
and `a-control-is-only-for-a-named-property` is the standing reason not to
label them as though it were.

## What a result would and would not license

A VR below 1 at some k, surviving `shuffled`, `block`, `deseasonalised` and the
`mid` arm, says increments cancel at that horizon. It does **not** say a trade
exists: `direction-is-closed-not-just-null` has the directional gate earning 2%
of a spread while correctly finding a planted drift at z +2.90, and tonight's
57 cross-sectional cells were all dead against 74.91 bp of spread. The cost
test is separate and comes second - but a measured reversion horizon would tell
the exit work *which* horizon to manage on, which is worth having on its own.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pattern_fingerprint import CACHE  # noqa: E402

FRAME = os.environ.get("FRAME", "1h")
#: Horizons swept. Roughly Fibonacci so the log spacing is even and a minimum
#: is locatable without a hundred columns.
LAGS = (2, 3, 5, 8, 13, 21, 34, 55)
BLOCK = 8
REPS = 200
LEAST_BARS = 4000
SEED = 20261026

TRADED = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "NZDUSD",
    "EURJPY",
    "GBPJPY",
    "EURGBP",
    "XAUUSD",
    "XAGUSD",
    "Germany_40",
    "UK_100",
    "Japan_225",
    "US_Oil",
    "NGAS",
    "BTCUSD",
    "ETHUSD",
)
GENERATED = {
    "range break (POSITIVE control: range by construction)": (
        "Range_Break_100_Index",
        "Range_Break_200_Index",
    ),
    "deriv volatility (NEGATIVE control: iid, constant nominal vol)": (
        "Volatility_10_Index",
        "Volatility_25_Index",
        "Volatility_75_Index",
        "Volatility_100_Index",
    ),
    "step (generated)": ("Step_Index", "Step_Index_200"),
    "boom/crash (generated)": ("Boom_500_Index", "Crash_500_Index"),
    "jump (generated)": ("Jump_25_Index", "Jump_100_Index"),
}


def _resolve(name: str) -> Path | None:
    exact = CACHE / f"{name}.{FRAME}.npz"
    if exact.exists():
        return exact
    hits = sorted(CACHE.glob(f"{name}.*.{FRAME}.npz"))
    return hits[0] if hits else None


def _load(name: str) -> dict[str, np.ndarray] | None:
    path = _resolve(name)
    if path is None:
        return None
    with np.load(path) as bundle:
        need = {"time", "high", "low", "close"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
        if "spread" in bundle:
            got["spread"] = np.asarray(bundle["spread"], dtype=float)[order]
    keep = (got["close"] > 0) & (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    return got if len(got["close"]) >= LEAST_BARS else None


def variance_ratio(returns: np.ndarray, lag: int) -> float:
    """Var(k-bar) / (k * Var(1-bar)), on overlapping k-bar sums.

    Overlapping windows are used for power and are the reason the null is a
    shuffle rather than a formula - `overlapping-windows-inflate-permutation-
    nulls`. Both arms use the identical estimator, so the overlap cancels.
    """
    if lag < 2 or len(returns) < lag * 4:
        return float("nan")
    one = float(returns.var())
    if one <= 0:
        return float("nan")
    kernel = np.ones(lag, dtype=float)
    summed = np.convolve(returns, kernel, mode="valid")
    return float(summed.var() / (lag * one))


def _shuffled(returns: np.ndarray, rng) -> np.ndarray:
    return rng.permutation(returns)


def _blocked(returns: np.ndarray, rng, block: int = BLOCK) -> np.ndarray:
    size = len(returns)
    starts = rng.integers(0, size - block, size=size // block + 1)
    drawn = np.concatenate([returns[s : s + block] for s in starts])
    return drawn[:size]


def _deseasonalised(returns: np.ndarray, when: np.ndarray) -> np.ndarray:
    """Divide each return by its own hour-of-day standard deviation."""
    hour = ((when[1:] // 3600) % 24).astype(int)
    out = returns.copy()
    for h in range(24):
        pick = hour == h
        if pick.sum() < 50:
            continue
        sd = out[pick].std()
        if sd > 0:
            out[pick] = out[pick] / sd
    return out


def _walk(bars: int, rng) -> np.ndarray:
    return rng.normal(0.0, 0.001, bars)


def _cost_ratio(bars: dict[str, np.ndarray]) -> tuple[float, float, float] | None:
    """(spread bp, typical bar move bp, their ratio) for this feed.

    The cache's spread is in **points**, and the point size differs per
    instrument, so the column is useless across feeds until it is scaled. The
    tick is inferred from the data as the smallest non-zero close-to-close
    change, which is measurable rather than assumed - and `spread bp` is
    printed so a wrong inference is visible instead of silently reordering the
    instruments, which is the damage `spread-column-is-in-points` records.
    """
    if "spread" not in bars:
        return None
    closes = bars["close"]
    steps = np.abs(np.diff(closes))
    live = steps[steps > 0]
    if len(live) < 100:
        return None
    tick = float(np.quantile(live, 0.001))
    if tick <= 0:
        return None
    spread = float(np.median(bars["spread"])) * tick
    level = float(np.median(closes))
    if level <= 0:
        return None
    move = float(np.median(np.abs(np.diff(np.log(closes)))))
    if move <= 0:
        return None
    spread_bp = spread / level * 1e4
    move_bp = move * 1e4
    return spread_bp, move_bp, spread_bp / move_bp


def _row(label: str, series: list[np.ndarray], rng) -> tuple[str, list[str]]:
    """One row, as the **mean of per-series VR** rather than VR of the pool.

    Concatenating returns across feeds would mix variance scales and invent a
    join between every pair, and the z would then be driven by whichever feed
    is largest. Averaging the per-series statistic keeps each feed's own
    denominator, which is what makes VR comparable across instruments at all.
    The null is averaged the same way, so the two sides stay matched.
    """
    cells = []
    for lag in LAGS:
        reals = [variance_ratio(one, lag) for one in series]
        reals = [v for v in reals if np.isfinite(v)]
        if not reals:
            cells.append("        -")
            continue
        real = float(np.mean(reals))
        draws = np.empty(REPS, dtype=float)
        for rep in range(REPS):
            spun = [variance_ratio(_shuffled(one, rng), lag) for one in series]
            spun = [v for v in spun if np.isfinite(v)]
            draws[rep] = float(np.mean(spun)) if spun else np.nan
        live = draws[np.isfinite(draws)]
        sd = float(live.std(ddof=1)) if len(live) > 1 else 0.0
        z = (real - float(live.mean())) / sd if sd > 0 else float("nan")
        cells.append(f"{real:.3f}/{z:+.0f}")
    return label, cells


def main() -> None:
    print(__doc__.split("\n\n")[0])
    print(
        f"\nframe {FRAME}, VR = Var(k-bar) / (k * Var(1-bar)).\n"
        f"Each cell is **VR / z against {REPS} shuffles of that same series**.\n"
        f"VR = 1 and z = 0 is a walk. Below 1 is cancelling, above 1 compounding.\n"
    )
    rng = np.random.default_rng(SEED)
    head = "  ".join(f"k={k:<7d}"[:9] for k in LAGS)
    print(f"{'series':46s} {head}")

    def show(label: str, cells: list[str]) -> None:
        print(f"{label:46s} " + "  ".join(f"{c:>9s}" for c in cells))

    # The walk first: every cell must read 1.000/+0 or the estimator is wrong.
    show(*_row("WALK (must read 1.000 at every k)", [_walk(50000, rng) for _ in range(8)], rng))
    print()

    arms: dict[str, list[np.ndarray]] = {}
    bounce: list[tuple[str, float, float, float, float]] = []
    for name in TRADED:
        bars = _load(name)
        if bars is None:
            continue
        ret = np.diff(np.log(bars["close"]))
        show(*_row(name, [ret], rng))
        cost = _cost_ratio(bars)
        if cost is not None:
            bounce.append((name, variance_ratio(ret, 2), *cost))
        arms.setdefault("traded: close", []).append(ret)
        # The bounce arm. Neither extreme is a transaction-side print, so a
        # VR(2) that is low on closes and not on mids is microstructure.
        arms.setdefault("traded: mid of high/low (no bounce)", []).append(
            np.diff(np.log((bars["high"] + bars["low"]) / 2.0))
        )
        arms.setdefault("traded: deseasonalised by hour", []).append(
            _deseasonalised(ret, bars["time"])
        )
        arms.setdefault("traded: block-8 bootstrap", []).append(_blocked(ret, rng))

    print()
    for label, parts in arms.items():
        if parts:
            show(*_row(label.upper(), parts, rng))

    print()
    for label, names in GENERATED.items():
        parts, mids = [], []
        for name in names:
            bars = _load(name)
            if bars is not None:
                parts.append(np.diff(np.log(bars["close"])))
                mids.append(np.diff(np.log((bars["high"] + bars["low"]) / 2.0)))
        if parts:
            show(*_row(label, parts, rng))
        if mids:
            # Any reading away from 1.0 here is the mid arm's own artefact and
            # nothing else - these generators have no microstructure at all.
            show(*_row("  ^ same, MID (artefact gauge)", mids, rng))

    # Does the VR deficit order instruments by their cost? Ranks only, so no
    # unit conversion can reorder them.
    if len(bounce) >= 6:
        print("\n=== is the close-based deficit bounce? rank VR(2) against spread/move")
        print(f"{'feed':14s} {'VR(2)':>7s} {'spread bp':>10s} {'move bp':>8s} {'spread/move':>12s}")
        for name, vr, spread_bp, move_bp, ratio in sorted(bounce, key=lambda r: r[4]):
            print(f"{name:14s} {vr:>7.3f} {spread_bp:>10.2f} {move_bp:>8.1f} {ratio:>12.3f}")
        vrs = np.array([r[1] for r in bounce])
        ratios = np.array([r[4] for r in bounce])
        rank_vr = np.argsort(np.argsort(vrs))
        rank_ratio = np.argsort(np.argsort(ratios))
        rho = float(np.corrcoef(rank_vr, rank_ratio)[0, 1])
        print(
            f"\nSpearman rho(VR(2), spread/move) = {rho:+.3f} over {len(bounce)} feeds.\n"
            "Strongly NEGATIVE means the cheapest feeds revert least and the\n"
            "dearest revert most, which is bid-ask bounce rather than an edge."
        )


if __name__ == "__main__":
    main()
