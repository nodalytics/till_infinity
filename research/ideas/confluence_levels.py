"""Confluence: does a price named by several frameworks behave differently?

    ./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=overlap
    ./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=run
    ./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=power
    ./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=cost
    ./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=calibrate
    ./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=sweep
    ./.secrets/lab.sh run research/ideas/confluence_levels.py MODE=lifesweep
    MODE=report uv run python research/ideas/confluence_levels.py   # tables from the npz
    MODE=smoke  uv run python research/ideas/confluence_levels.py   # seconds, generated bars

`MODE=overlap` writes `$OUT/overlap.csv` - per framework a firing rate and a
level density, and the full pairwise agreement matrix - and is **the first
deliverable**: if the four frameworks name the same prices then a confluence
count is one framework counted four times and the rest of the study is
arithmetic. `MODE=run` writes `$OUT/cells.csv` (one row per instrument,
interval, arm and `k` bucket, with every statistic the write-up quotes),
`$OUT/obs.npz` (every observation, as columns) and `$OUT/overlap.csv`.
`MODE=power` writes `$OUT/power.csv`; `MODE=cost` writes `$OUT/cost.csv`.
`MODE=report` re-prints every table from `obs.npz` without recomputing it.

## The claim, as a class

A piece of gold commentary called $3,977 a "high-conviction decision point"
because a Square-of-9 45 degree angle, a Fibonacci 62-79% zone, a prior swing
low / double bottom and the $4,000 round number land together; that the outcome
there is **bimodal** (defend and revert, or break and trend); and that breaking
it triggers a **stop cascade**. One level on one instrument at one moment is an
anecdote, so the measurable class is: **over every instrument and all available
history, does a price named by `k` frameworks behave differently from one named
by 1, and from a price named by none?**

This is not the magnet claim and not the shield claim, both of which are
closed. `magnet.md`: a level is reached 44.9% of the time inside twenty bars
against 49.5% for an arbitrary price the same distance away, so a level does
not attract. `level-shield.md`: 1 of 210 cells beats its hardest null arm, so a
level in the path does not block. `a-magnet-is-a-shared-reference` names what
neither tested - **watchedness**, the claim that liquidity rests where many
participants compute the same price - and a confluence count is the only direct
observable of it this desk can build.

`strength.md` measured the adjacent version and it is a different claim.
Confluence **breadth across timeframes** - one framework, several clocks - does
not separate: AUC 0.476 and 0.452, four runs and four orderings, and
`Zone.strength`'s `1 + 0.15*(depth-1)` multiplier is unearned on that evidence.
Breadth across *frameworks* is what is open, because four frameworks are four
populations of screens where one framework on four clocks is one population
looking at four charts.

## The four frameworks, all causal

Each emits a price and the bar it became **knowable**, never the bar it
describes. A pivot is knowable `SWING` bars after it prints; a Fibonacci level
of a swing is knowable when the swing's second extreme is confirmed. Taking
either earlier is the lookahead that made an open-gap filter read +0.50R a
trade.

| framework | the level | knowable at |
|---|---|---|
| `swing` | a confirmed pivot high or low, flagged `doubled` when a second pivot lands within `TOL_VOL` of an earlier one - the double bottom the commentary names | pivot bar + `SWING` |
| `fib` | `FIB_RATIOS` retracements of a **completed** leg between two confirmed opposite pivots, the leg at least `MIN_LEG_VOL` units | the later pivot's confirmation |
| `gann` | the Square-of-9 wheel from **each** confirmed pivot, `((sqrt(a*s) + deg/180)^2)/s` for `deg` in `GANN_DEGREES`, both signs, each rung alive for `LIFE` bars - so the live wheel is the superposition of every anchor inside the last `LIFE` bars, which is most of why this framework is the densest of the four | the anchor pivot's confirmation |
| `round` | the whole and half steps of the smallest power of ten at least `STEP_VOL` units wide | always; it needs no history at all |

`gann` is in the study **precisely because it is the most arbitrary of the
four**. A Square of 9 has no mechanism, so if it adds information the first
hypothesis is a bug in this file.

**Two densities are matched by construction, deliberately.** The round grid and
the Gann wheel are both tuned to a step of about `STEP_VOL` volatility units -
the round grid by choosing the power of ten, the wheel by choosing the power of
ten it scales the price by before drawing. A framework that emits a level every
half unit agrees with everything, so comparing grids of different density
measures the density. `MODE=overlap` prints the realised density beside the
agreement so this can be checked rather than taken.

## The arms, and what each one is for

| arm | what it is | the property it carries |
|---|---|---|
| `real` | the market's own bars, split by `k` | the claim |
| `placebo` | an arrival at a price **no framework names**, matched on the signed displacement from the previous close and on the volatility stratum, one per real observation | geometry without a level. Without it a level study measures mean reversion and reports it as structure |
| `walkpath` | a driftless Brownian-bridge walk resampling this series' own steps, through the identical detectors | **the arm that decides.** A walk has swings, retracements, wheels and round numbers too, and `k` counts them the same way, so a `k` effect that is arithmetic appears here at full size |
| `garchpath` | the same bridge driven by GARCH(1,1)-t(5) steps | clustered volatility, still no participants |

Both surrogate arms build the **path**, not a bar envelope.
`node/surrogates.walk_with_bar_geometry` is not a barrier null: it re-hangs
real bar shapes on a synthetic close path, so a stop fires where the path never
went, and it gaps 0.60-0.64 of a bar range on every bar against the market's
median `|gap|` of 0.0000 on 71-79% of bars. The bridge here is
`research/harness/entry_timing.walk_path`'s, whose docstring measures the
difference: `-0.1985R` on walk-geometry bars where optional stopping requires
exactly zero, against `+0.0003R` on real bars.

## The three outcomes, in order, all direction-free

1. **Hold rate on the arriving side**, the primary. Price arrives at `p` from
   one side; does it travel `HOLD_VOL` units back the way it came before
   `HOLD_VOL` units through? On a martingale this is 0.5 whatever `k` is, so it
   needs no drift model and no cost assumption.
2. **Bimodality.** Conditional on arrival, is the next-`SHAPE_N`-bar return
   distribution bimodal against a unimodal null? Excess kurtosis, Sarle's
   bimodality coefficient, Silverman's critical-bandwidth mode count with a
   smoothed bootstrap, and two Gaussians against one by EM. **The direction is
   stated before the run**: bimodality means *negative* excess kurtosis and a
   *location*-separated mixture. A fat-tailed unimodal return - which is what
   this desk measures everywhere, kurtosis 47-74 on traded instruments - beats
   one Gaussian with a **scale** mixture, one mean and two variances, and that
   is the opposite of the claim. So the mixture reports the mean separation and
   not only the likelihood.
3. **The cascade.** Conditional on *breaking*, the continuation race, the
   realised volatility and the excursion over the next `CASCADE_N` bars,
   against the placebo break and against the walk. `focal-points.md` has
   already run the round-number version: FX accelerates after crossing a big
   figure 56.7% against the placebo's 54.1%, and the random walks do it 53.7%
   against 52.5%, so the market's own share is about 1.4 points. An overshoot
   at an extreme is partly definitional, which is why the comparison is the
   highest-powered shuffled arm and not each arm's own
   (`let-the-shuffled-twin-name-the-mechanical-observables`).

## Where this kind of study leaks, and what is done about it

* **Overlapping observations.** A short skip rule with a long forward window
  gave direction AUC 0.79 that collapsed to 0.51, and anchor overlap turned a
  level finding at p 0.015 into nothing. Every arm and every `k` bucket is its
  own **de-overlapped stream**: an observation is accepted only `HOLD_H` bars
  after the last one accepted in that stream, so no two observations **within
  a stream** share an outcome bar. Two streams still can - the `k = 1` and
  `k >= 2` streams are drawn from the same bars - and that dependence is priced
  by the day-block bootstrap, which resamples whole UTC days across both arms
  at once. A touch is also a *first* touch - sitting
  inside a level for forty bars is one observation, which is the correction
  that turned a published 0.6365 into 0.5092.
* **Pooling.** Every rate is reported per instrument and per interval, and the
  pooled figure is a **stratified** average over volatility quintiles: AUC is
  free on volatility targets, 0.805 on a constant-volatility process against
  0.525 within strata, and a pooled median here once agreed with a claim every
  subgroup refuted.
* **Multiplicity.** Benjamini-Hochberg over every instrument-interval cell.
* **Positive control.** `Range Break 100 Index` and `Range Break 200 Index` are
  a range by construction, so their boundaries are levels that exist and a
  study that misses them is broken. `Volatility 25 Index` and `Volatility 75
  Index` are the independent placebo pair and must read nothing.
* **Power.** `MODE=power` plants two effects. The **label** plant overwrites a
  share of `k>=2` outcomes with a hold and sweeps the share, which prices the
  estimator's blindness in hold-rate points. The **geometric** plant reflects a
  share of a generated path's sub-steps at a grid specified *independently of
  the path* - the round grid - and runs the whole four-framework pipeline on
  the result, which asks whether the detectors can see a barrier at all.
"""

from __future__ import annotations

import bisect
import csv
import math
import os
import random
import sys
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

OUT = Path(os.environ.get("OUT", ".data/confluence"))
MODE = os.environ.get("MODE", "run")


def _f(name: str, fallback: float) -> float:
    return float(os.environ.get(name, fallback))


def _i(name: str, fallback: int) -> int:
    return int(os.environ.get(name, fallback))


def _tuple(name: str, fallback: tuple[float, ...]) -> tuple[float, ...]:
    """A comma-separated float tuple from the environment.

    `FIB_RATIOS` and `GANN_DEGREES` are overridable because the study's main
    weakness is density: four frameworks at their own published densities name
    98% of all prices, so the interesting re-run is a **sparse** configuration
    where a confluence is rare. That is a different set of rules rather than a
    different parameter, so it is stated in full on the command line:

        MODE=run ARMS=real,walkpath TOL_VOL=0.15 LIFE=150 MIN_LEG_VOL=4.0 \
            FIB_RATIOS=0.618,0.786 GANN_DEGREES=45,90
    """
    raw = os.environ.get(name)
    if not raw:
        return fallback
    return tuple(float(x) for x in raw.split(",") if x.strip())


# ───────────────────────────── the frozen rules ─────────────────────────────

#: Pivot reach, left and right, as `indicators/trend.pivots` and the breaker
#: study both use it. The confirmation lag is the same number.
SWING = _i("SWING", 10)

#: Two prices are the same price within this many volatility units. The unit is
#: a causal EWMA of the bar range (`drive-q-from-the-range`), so the tolerance
#: scales with the regime rather than with the instrument's decimal places.
TOL_VOL = _f("TOL_VOL", 0.25)

#: How long a level stays live, in bars. A level nobody has looked at for five
#: hundred bars is not what the commentary means by a decision point, and a
#: level that never expires makes the book grow without bound.
LIFE = _i("LIFE", 500)

#: How far from the close a level is reported as live, in volatility units, and
#: how dense the round grid and the Gann wheel are. Both are `rounds.py`'s own
#: constants, kept so the grid here is the grid the package would draw.
REACH_VOL = _f("REACH_VOL", 12.0)
STEP_VOL = _f("STEP_VOL", 5.0)

#: The retracement ratios. The OTE zone the commentary names is 0.618-0.786.
FIB_RATIOS = _tuple("FIB_RATIOS", (0.382, 0.5, 0.618, 0.786))

#: A leg smaller than this is noise rather than a swing, so its retracements
#: are not levels. In volatility units at the later pivot's confirmation.
MIN_LEG_VOL = _f("MIN_LEG_VOL", 2.0)

#: The Square-of-9 wheel, in degrees either side of the anchor. One full
#: rotation adds 2 to the square root of the price, so `deg` adds `deg/180`.
GANN_DEGREES = _tuple("GANN_DEGREES", (45.0, 90.0, 135.0, 180.0, 270.0, 360.0))

#: The race: how far back and how far through, in volatility units, and how
#: many bars it has. On a martingale the hold rate is 0.5 at any `HOLD_VOL`.
HOLD_VOL = _f("HOLD_VOL", 1.0)
HOLD_H = _i("HOLD_H", 48)

#: The forward windows for the shape test and for the cascade.
SHAPE_N = _i("SHAPE_N", 20)
CASCADE_N = _i("CASCADE_N", 20)

#: Volatility strata: the causal quantile rank of the unit within the previous
#: `STRATA_W` bars, cut into `STRATA` buckets.
STRATA = _i("STRATA", 5)
STRATA_W = _i("STRATA_W", 500)

#: EWMA span for the volatility unit, and the warmup before anything is
#: emitted - long enough for `STRATA_W` to be defined as well.
UNIT_SPAN = _i("UNIT_SPAN", 64)
WARMUP = _i("WARMUP", 600)

#: Fewer bars than this and the cell is not reported, the floor
#: `lab-seqlab-is-much-bigger-than-seven` arrived at.
MIN_BARS = _i("MIN_BARS", 1200)

#: Day blocks in the bootstrap, and the seed. Nearby observations share outcome
#: bars across streams even after de-overlapping within one, and regimes
#: persist for hours, so whole UTC days are resampled.
DRAWS = _i("DRAWS", 1000)
SEED = _i("SEED", 20261110)

#: Sub-steps per bar in the Brownian bridge. `entry_timing.walk_path` swept
#: this and the race stopped moving past about sixty.
SUBSTEPS = _i("SUBSTEPS", 60)

#: Every `SAMPLE_EVERY`-th bar enters the agreement matrix. The matrix is a
#: description of the book rather than an outcome, so a subsample is honest and
#: a full scan costs an hour for the same numbers.
SAMPLE_EVERY = _i("SAMPLE_EVERY", 20)

SEC = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
INTERVALS = tuple(os.environ.get("INTERVALS", "15m,1h,4h,1d").split(","))
HOME = Path(os.environ.get("BARS_HOME", Path.home() / "till_infinity" / "data"))

FRAMEWORKS = ("swing", "fib", "gann", "round")
ARMS = tuple(os.environ.get("ARMS", "real,placebo,walkpath,garchpath").split(","))
BUCKETS = ("k0", "k1", "k2", "k3")

#: Instruments, by store, deepest first - the breaker study's universe widened
#: to every FX store the lab holds, which is this venue's book as it stands.
DEEP = ("EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDJPY", "USDCHF", "NZDUSD",
        "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURCHF", "AUDNZD", "EURAUD",
        "EURCAD", "AUDCAD", "CADJPY", "CHFJPY", "NZDJPY", "XAUUSD", "XAGUSD",
        "BTCUSD")
WIDE = ("US SP 500", "US Tech 100", "Wall Street 30", "Germany 40", "UK 100",
        "Japan 225", "Australia 200", "Europe 50", "France 40", "Hong Kong 50",
        "US Oil", "UK Brent Oil", "XPTUSD", "XCUUSD", "ETHUSD")
SYNTH = ("Boom 500 Index", "Boom 1000 Index", "Crash 500 Index", "Crash 1000 Index",
         "Drift Switch Index 10", "Drift Switch Index 20", "Drift Switch Index 30",
         "Range Break 100 Index", "Range Break 200 Index", "Step Index",
         "Volatility 25 Index", "Volatility 75 Index", "Jump 75 Index")

FAMILY = {
    **{s: "fx" for s in ("EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDJPY", "USDCHF",
                         "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURCHF",
                         "AUDNZD", "EURAUD", "EURCAD", "AUDCAD", "CADJPY", "CHFJPY",
                         "NZDJPY")},
    **{s: "metal" for s in ("XAUUSD", "XAGUSD", "XPTUSD", "XCUUSD")},
    **{s: "crypto" for s in ("BTCUSD", "ETHUSD")},
    **{s: "index" for s in ("US SP 500", "US Tech 100", "Wall Street 30", "Germany 40",
                            "UK 100", "Japan 225", "Australia 200", "Europe 50",
                            "France 40", "Hong Kong 50")},
    **{s: "energy" for s in ("US Oil", "UK Brent Oil")},
    **{s: "deriv" for s in SYNTH},
}

#: The two synthetic arms with a job. `Range Break` is a range by construction,
#: so it is the level positive control; the two volatility indices are the
#: independent placebo pair and must read nothing.
POSITIVE = ("Range Break 100 Index", "Range Break 200 Index")
PLACEBO_PAIR = ("Volatility 25 Index", "Volatility 75 Index")

#: The columns one observation carries. Everything is a float so the whole
#: panel is one `npz` and the report needs no row objects: three million
#: observations as dicts is five gigabytes and as columns is six hundred
#: megabytes.
COLUMNS = ("series", "arm", "bucket", "bar", "day", "side", "k", "stratum",
           "unit", "displacement", "width", "hold", "took", "shape",
           "cascade_went", "cascade_realised", "cascade_far", "doubled",
           *(f"has_{f}" for f in FRAMEWORKS))


# ───────────────────────────────── bars ─────────────────────────────────


def sources() -> dict[str, Path]:
    """One 15m store per name, deepest first, so a name is never read at 50,000
    bars when 294,000 exist. `breaker_blocks.sources`, unchanged."""
    found: dict[str, Path] = {}
    for folder in (HOME / "seqlab", HOME / "btc", HOME / "syn"):
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.15m.npz")):
            found.setdefault(path.name[: -len(".15m.npz")], path)
    return found


def read(path: Path) -> tuple[dict[str, np.ndarray], int]:
    """One store's 15m bars, oldest first, de-duplicated by timestamp.

    The de-duplication is unconditional and the drop is reported: a duplicate
    bar doubles a detector's firing rate in silence, and two daily stores in
    this repository were found duplicated on 2026-11-10.
    """
    with np.load(path) as z:
        got = {k: z[k].astype(float) for k in ("open", "high", "low", "close")}
        got["ts"] = z["time"].astype(np.int64)
    order = np.argsort(got["ts"], kind="stable")
    got = {k: v[order] for k, v in got.items()}
    keep = np.r_[True, np.diff(got["ts"]) > 0]
    return {k: v[keep] for k, v in got.items()}, int((~keep).sum())


def fold(bars: dict[str, np.ndarray], sec: int) -> dict[str, np.ndarray]:
    """15m bars into `sec`-second bars by **timestamp bucket**, not by index.

    Index folding walks across the weekend and puts Friday's close in the same
    bar as Monday's open; a timestamp bucket just yields fewer bars. The daily
    bar is therefore a UTC day rather than the broker's session.
    """
    if sec <= 900:
        return bars
    key = bars["ts"] // sec
    start = np.r_[0, np.flatnonzero(np.diff(key)) + 1]
    end = np.r_[start[1:], len(key)]
    return {
        "ts": key[start] * sec,
        "open": bars["open"][start],
        "high": np.maximum.reduceat(bars["high"], start),
        "low": np.minimum.reduceat(bars["low"], start),
        "close": bars["close"][end - 1],
    }


def unit_of(bars: dict[str, np.ndarray], span: int = UNIT_SPAN) -> np.ndarray:
    """The volatility unit: a causal EWMA of the true range, **lagged one bar**.

    `drive-q-from-the-range` is why the range and not the close - the
    range-vs-close estimator ratio is 0.648 within strata on FX and 0.667 on
    371 of 392 equities. The lag is what makes it usable at bar `i`: `unit[i]`
    is a function of bars strictly before `i`, so nothing a level is measured
    against was measured with the bar it is being measured on.
    """
    prev = np.r_[bars["close"][0], bars["close"][:-1]]
    tr = np.maximum(bars["high"], prev) - np.minimum(bars["low"], prev)
    alpha = 2.0 / (span + 1.0)
    out = np.empty(len(tr))
    acc = float(np.nanmean(tr[: min(span, len(tr))])) or 1e-12
    for i in range(len(tr)):
        out[i] = acc
        acc += alpha * (tr[i] - acc)
    return np.maximum(out, 1e-12)


def strata_of(unit: np.ndarray, buckets: int = STRATA, window: int = STRATA_W) -> np.ndarray:
    """The causal quantile rank of the unit within the previous `window` bars.

    A stratum is a regime label rather than a signal, but it is still computed
    from the past only: a stratum that knows the future would let a comparison
    inside it condition on the outcome. Computed in blocks because the full
    comparison matrix is a hundred and fifty megabytes a series and this runs
    twenty-four to a box.
    """
    n = len(unit)
    out = np.zeros(n, dtype=np.int8)
    if n <= window + 1:
        return out
    view = sliding_window_view(unit, window)
    for lo in range(window, n, 20_000):
        hi = min(lo + 20_000, n)
        rank = (view[lo - window:hi - window] < unit[lo:hi, None]).mean(axis=1)
        out[lo:hi] = np.clip((rank * buckets).astype(np.int8), 0, buckets - 1)
    return out


# ───────────────────────────── the four frameworks ─────────────────────────────


def pivot_flags(high: np.ndarray, low: np.ndarray, reach: int = SWING):
    """`indicators/trend.pivots`' definition, vectorised: strictly beyond the
    `reach` bars before and at or beyond the `reach` after, so a flat top
    reports once."""
    n = len(high)
    ph = np.zeros(n, bool)
    pl = np.zeros(n, bool)
    if n < 2 * reach + 1:
        return ph, pl
    wh = sliding_window_view(high, 2 * reach + 1)
    wl = sliding_window_view(low, 2 * reach + 1)
    mid = slice(reach, n - reach)
    ph[mid] = (high[mid] > wh[:, :reach].max(axis=1)) & (high[mid] >= wh[:, reach + 1:].max(axis=1))
    pl[mid] = (low[mid] < wl[:, :reach].min(axis=1)) & (low[mid] <= wl[:, reach + 1:].min(axis=1))
    return ph, pl


def gann_scale(price: float, unit: float, target: float = STEP_VOL) -> float:
    """The power of ten the price is multiplied by before the wheel is drawn.

    **A Square of 9 is not scale-free, and this is where its arbitrariness
    lives.** One 45 degree step is about `0.5*sqrt(price/s)` wide, which at
    `s = 1` is $31 on gold and 0.52 on EURUSD - half the price. Practitioners
    rescale by eye. This file rescales by a rule: the power of ten whose step
    is closest to `target` volatility units, which is the density the round
    grid is drawn at, so neither grid can agree with the other merely by being
    finer.
    """
    want = max(target * unit, 1e-12)
    ideal = price / (4.0 * want * want)
    return 10.0 ** round(math.log10(max(ideal, 1e-300)))


def round_step(unit: float, target: float = STEP_VOL) -> float:
    """The smallest power of ten at least `target` volatility units wide.

    `rounds.py`'s rule, and its reason: "ends in zero" is meaningless without a
    scale, and a table of steps per instrument is the thing this repository
    keeps finding bugs in - a new instrument arrives, nobody adds a row, and
    the formation silently draws nothing for it.
    """
    return 10.0 ** math.ceil(math.log10(max(target * unit, 1e-12)))


def confirmed_pivots(bars) -> list[tuple[int, float, int]]:
    """`(born, price, side)` in the order the pivots became knowable."""
    n = len(bars["close"])
    ph, pl = pivot_flags(bars["high"], bars["low"])
    found = [(int(i) + SWING, float(bars["high"][i]), +1) for i in np.flatnonzero(ph)]
    found += [(int(i) + SWING, float(bars["low"][i]), -1) for i in np.flatnonzero(pl)]
    found.sort()
    return [p for p in found if WARMUP <= p[0] < n]


def levels_for(bars, unit: np.ndarray) -> dict[str, np.ndarray]:
    """`swing`, `fib` and `gann` as `(price, born, die, flag)` rows.

    `round` is not here: it is analytic, because it needs no history. Keeping
    it as rows would mean re-emitting the same grid every few bars and then
    de-duplicating a million of them for the same answer a division gives.

    The `flag` column carries the framework's own subtype - `doubled` for a
    swing that repeats a previous one, the ratio index for a fib, the degree
    index for a wheel rung - so a confluence's composition can be reported
    without a second pass.
    """
    n = len(bars["close"])
    pivots = confirmed_pivots(bars)
    out: dict[str, list[tuple[float, int, int, int]]] = {"swing": [], "fib": [], "gann": []}

    seen: dict[int, list[float]] = {+1: [], -1: []}
    for born, price, side in pivots:
        tol = TOL_VOL * unit[born]
        prior = seen[side]
        doubled = int(any(abs(price - q) <= tol for q in prior[-8:]))
        prior.append(price)
        out["swing"].append((price, born, min(born + LIFE, n), doubled))

    # Fibonacci. The leg is complete *because both ends are confirmed*, which
    # is the whole reason the emission bar is the later confirmation and not
    # the later pivot: a retracement of a swing still forming is a level drawn
    # from a high that has not happened yet.
    for j in range(1, len(pivots)):
        born, price, side = pivots[j]
        _prev_born, prev_price, prev_side = pivots[j - 1]
        if side == prev_side:
            continue
        leg = price - prev_price
        if abs(leg) < MIN_LEG_VOL * unit[born]:
            continue
        for r, ratio in enumerate(FIB_RATIOS):
            out["fib"].append((price - ratio * leg, born, min(born + LIFE, n), r))

    # **Every pivot is an anchor, not only the latest.** A practitioner redraws
    # the wheel when the swing changes, so the live book is the superposition of
    # the anchors inside the last `LIFE` bars rather than one wheel - which is
    # most of why this framework is the densest of the four at 1.63 levels per
    # volatility unit, and the reason the density is reported beside the
    # agreement rather than left to be assumed.
    for born, price, _side in pivots:
        if price <= 0:
            continue
        s = gann_scale(price, float(unit[born]))
        root = math.sqrt(price * s)
        for d, deg in enumerate(GANN_DEGREES):
            for sign in (+1, -1):
                r = root + sign * deg / 180.0
                if r > 0:
                    out["gann"].append(((r * r) / s, born, min(born + LIFE, n), d))

    return {f: (np.asarray(rows, dtype=float) if rows else np.zeros((0, 4)))
            for f, rows in out.items()}


def dedupe(rows: np.ndarray, unit: np.ndarray) -> np.ndarray:
    """Drop a level a live one of the same framework already names.

    Without this the Gann wheel counts the same price once per anchor, so a
    density figure and an agreement share both mean nothing. The surviving row
    keeps the **earliest** birth, so a re-emission cannot make a level younger
    than it is. The lookup is bucketed on a fixed grid - the tolerance at the
    median unit - and the comparison inside the bucket still uses the
    tolerance at the row's own birth, so the bucketing is housekeeping and
    not a measurement.
    """
    if len(rows) == 0:
        return rows
    rows = rows[np.argsort(rows[:, 1], kind="stable")]
    grid = max(TOL_VOL * float(np.median(unit)), 1e-12)
    live: dict[int, list[tuple[float, int]]] = {}
    keep = np.zeros(len(rows), bool)
    for idx in range(len(rows)):
        price, born, die = rows[idx, 0], int(rows[idx, 1]), int(rows[idx, 2])
        tol = TOL_VOL * unit[min(born, len(unit) - 1)]
        key = int(price // grid)
        # **The scan width is derived from the row's own tolerance**, not fixed
        # at one bucket. The bucket grid is the tolerance at the *median* unit,
        # and on a series whose volatility spans an order of magnitude - BTCUSD
        # does - a late row's tolerance is several buckets wide, so a
        # fixed one-bucket scan silently stops de-duplicating in exactly the
        # regime with the most levels. It changes the reported level counts and
        # densities only: `k` and every outcome come from `Book.names`, which
        # searches a price window with the bar's own tolerance and never
        # consults this grid.
        span = int(tol / grid) + 1
        hit = False
        for near in range(key - span, key + span + 1):
            bucket = live.get(near)
            if not bucket:
                continue
            bucket[:] = [(q, d) for q, d in bucket if d > born]
            if any(abs(price - q) <= tol for q, _d in bucket):
                hit = True
                break
        if hit:
            continue
        keep[idx] = True
        live.setdefault(key, []).append((price, die))
    return rows[keep]


# ───────────────────────── the book, and the count k ─────────────────────────


class Book:
    """Every framework's levels, indexed for the one question this study asks:
    *at bar `i`, does framework `f` name a price within `tol` of `p`?*

    Sorted by price with a binary search, because the touch-driven scan asks it
    a few hundred thousand times a series and a linear scan over a live list
    turned a four-minute job into an hour.
    """

    def __init__(self, rows: dict[str, np.ndarray], unit: np.ndarray):
        self.unit = unit
        self.rows: dict[str, np.ndarray] = {}
        for f, got in rows.items():
            self.rows[f] = got[np.argsort(got[:, 0], kind="stable")] if len(got) else got

    def _round_flag(self, price: float, bar: int, tol: float) -> int:
        half = round_step(float(self.unit[bar])) / 2.0
        m = round(price / half)
        if abs(price - m * half) > tol:
            return -1
        return 0 if m % 2 == 0 else 1

    def names(self, f: str, price: float, bar: int, tol: float) -> int:
        """-1 when the framework names nothing there, else the matching row's
        flag."""
        if f == "round":
            return self._round_flag(price, bar, tol)
        got = self.rows[f]
        if len(got) == 0:
            return -1
        lo = int(np.searchsorted(got[:, 0], price - tol, side="left"))
        hi = int(np.searchsorted(got[:, 0], price + tol, side="right"))
        for idx in range(lo, hi):
            if got[idx, 1] <= bar < got[idx, 2]:
                return int(got[idx, 3])
        return -1

    def live_near(self, f: str, price: float, bar: int, reach: float) -> np.ndarray:
        """Every live level of `f` within `reach` of `price`, for the density
        and agreement report."""
        if f == "round":
            half = round_step(float(self.unit[bar])) / 2.0
            lo = math.ceil((price - reach) / half)
            hi = math.floor((price + reach) / half)
            return np.arange(lo, hi + 1) * half
        got = self.rows[f]
        if len(got) == 0:
            return np.zeros(0)
        lo = int(np.searchsorted(got[:, 0], price - reach, side="left"))
        hi = int(np.searchsorted(got[:, 0], price + reach, side="right"))
        window = got[lo:hi]
        if len(window) == 0:
            return np.zeros(0)
        return window[(window[:, 1] <= bar) & (bar < window[:, 2]), 0]


def touches_of_rows(rows: np.ndarray, bars) -> list[tuple[int, float]]:
    """First touches of each level: `(bar, price)`.

    A touch is the bar whose range contains the price when the previous bar's
    did not, so sitting inside a level for forty bars is one observation and
    not forty.
    """
    high, low = bars["high"], bars["low"]
    n = len(high)
    found: list[tuple[int, float]] = []
    for idx in range(len(rows)):
        price, born, die = rows[idx, 0], int(rows[idx, 1]), int(rows[idx, 2])
        a, b = max(born, 1), min(die, n)
        if b <= a:
            continue
        inside = (low[a - 1:b] <= price) & (high[a - 1:b] >= price)
        for i in np.flatnonzero(inside[1:] & ~inside[:-1]):
            found.append((int(i) + a, float(price)))
    return found


def touches_of_round(bars, unit: np.ndarray) -> list[tuple[int, float]]:
    """First touches of the round grid, which is analytic and always live."""
    high, low = bars["high"], bars["low"]
    n = len(high)
    found: list[tuple[int, float]] = []
    for i in range(max(WARMUP, 1), n):
        half = round_step(float(unit[i])) / 2.0
        lo = math.ceil(low[i] / half)
        hi = math.floor(high[i] / half)
        if hi < lo:
            continue
        for m in range(lo, hi + 1):
            price = m * half
            if not (low[i - 1] <= price <= high[i - 1]):
                found.append((i, price))
    return found


def named_prices(book: Book, bars, unit: np.ndarray):
    """Every first touch of a named price, as `(bar, price, k, flags)`.

    Two touches at the same bar within one tolerance are the same price, so the
    group is the unit of observation and `k` is the number of **distinct
    frameworks** naming it. Several levels of one framework in a group count
    once: a confluence of four Fibonacci ratios is one framework, which is the
    arithmetic this study exists to separate from four frameworks.
    """
    events: list[tuple[int, float]] = []
    for f in FRAMEWORKS:
        events.extend(touches_of_round(bars, unit) if f == "round"
                      else touches_of_rows(book.rows[f], bars))
    events = sorted(set(events))
    out: list[tuple[int, float, int, tuple[int, ...]]] = []
    group: list[float] = []
    at = -1
    for bar, price in events:
        if bar != at:
            at, group = bar, []
        tol = TOL_VOL * unit[bar]
        if any(abs(price - q) <= tol for q in group):
            continue
        group.append(price)
        flags = tuple(book.names(f, price, bar, tol) for f in FRAMEWORKS)
        k = sum(1 for flag in flags if flag >= 0)
        if k:
            out.append((bar, price, k, flags))
    return out


# ───────────────────────────── the race, settled ─────────────────────────────


def race(bars, bar: int, price: float, side: int, dist: float,
         horizon: int | None = None) -> tuple[int, int]:
    """`(outcome, bars)`: +1 hold, -1 break, 0 censored.

    `side` is the arriving side: +1 when price fell to `price` from above, so a
    hold is a move of `dist` back **up**. The settlement is stated here because
    it is where a barrier study leaks:

    * the arrival bar contributes its **close only**. Its extremes cannot be
      ordered against the touch - OHLC does not say whether the high came
      before the low - so using them would be the harness choosing an intrabar
      path, and an arm built that way moves with the choice;
    * from the next bar the extremes count, and when both barriers are
      reachable in one bar the **break** wins. There are no ticks to break the
      tie and resolving it against the claim is the conservative direction.
    """
    horizon = HOLD_H if horizon is None else horizon
    close, high, low = bars["close"], bars["high"], bars["low"]
    hold_at = price + side * dist
    break_at = price - side * dist
    if (close[bar] - break_at) * side <= 0:
        return -1, 0
    if (close[bar] - hold_at) * side >= 0:
        return +1, 0
    stop = min(bar + horizon, len(close) - 1)
    for j in range(bar + 1, stop + 1):
        through = low[j] <= break_at if side > 0 else high[j] >= break_at
        back = high[j] >= hold_at if side > 0 else low[j] <= hold_at
        if through:
            return -1, j - bar
        if back:
            return +1, j - bar
    return 0, horizon


def continuation(bars, bar: int, price: float, side: int, dist: float,
                 horizon: int | None = None) -> tuple[int, float, float]:
    """The cascade, after a break: `(went_further, realised, excursion)`.

    `went_further` races another `dist` through against a return to `price`,
    which on a martingale is 0.5 by symmetry. `realised` is the root mean
    square close-to-close step over the window in price, so divided by the unit
    a cascade shows as a number above 1.0. `excursion` is the furthest the move
    got through, in price.
    """
    horizon = CASCADE_N if horizon is None else horizon
    close, high, low = bars["close"], bars["high"], bars["low"]
    stop = min(bar + horizon, len(close) - 1)
    onward = price - side * 2.0 * dist
    got = 0
    for j in range(bar + 1, stop + 1):
        hit_on = low[j] <= onward if side > 0 else high[j] >= onward
        hit_back = high[j] >= price if side > 0 else low[j] <= price
        if hit_on:
            got = 1
            break
        if hit_back:
            got = -1
            break
    steps = np.diff(close[bar:stop + 1])
    realised = float(np.sqrt(np.mean(steps * steps))) if len(steps) else float("nan")
    far = (price - low[bar:stop + 1].min()) if side > 0 else (high[bar:stop + 1].max() - price)
    return got, realised, float(far)


# ─────────────────────────── the de-overlapped streams ───────────────────────────


def bucket_of(k: int) -> str:
    return "k1" if k == 1 else ("k2" if k == 2 else "k3")


def _row(bars, unit, strata, bar: int, price: float, side: int, k: int,
         flags: tuple[int, ...], *, plant: float, rng) -> dict[str, float]:
    prev = bars["close"][bar - 1]
    dist = HOLD_VOL * unit[bar]
    outcome, took = race(bars, bar, price, side, dist)
    if plant > 0.0 and k >= 2 and rng is not None and rng.random() < plant:
        outcome, took = +1, max(took, 1)
    row = {
        "bar": float(bar), "day": float(bars["ts"][bar] // 86400), "side": float(side),
        "k": float(k), "stratum": float(strata[bar]), "unit": float(unit[bar]),
        "displacement": float((prev - price) / unit[bar]),
        # **The arrival bar's range over the *lagged* unit.** This is the
        # candidate mechanism for the `k` ladder and it is recorded so the
        # question can be asked rather than argued: a `k >= 2` price needs
        # several frameworks' levels inside one tolerance, which is likelier
        # in a bar that is wide for its regime - and in a wide bar the race's
        # barriers, which are set from the *lagged* unit, are both close, so
        # whichever the close is nearer to wins more often.
        "width": float((bars["high"][bar] - bars["low"][bar]) / unit[bar]),
        "hold": float("nan") if outcome == 0 else float(outcome > 0),
        "took": float(took),
        "shape": float(side * (bars["close"][bar + SHAPE_N] - price) / unit[bar]),
        "doubled": float(flags[0] > 0),
    }
    for f, flag in zip(FRAMEWORKS, flags, strict=True):
        row[f"has_{f}"] = float(flag >= 0)
    if outcome < 0:
        went, realised, far = continuation(bars, bar + took, price, side, dist)
        row["cascade_went"] = float(went)
        row["cascade_realised"] = realised / float(unit[bar])
        row["cascade_far"] = far / float(unit[bar])
    else:
        row["cascade_went"] = 0.0
        row["cascade_realised"] = float("nan")
        row["cascade_far"] = float("nan")
    return row


def observe(bars, unit, strata, named, *, plant: float = 0.0, rng=None):
    """One de-overlapped stream per `k` bucket, and the outcome on each.

    **A stream per bucket, not one stream.** With a single stream the buckets
    compete for slots and the rarest bucket - which is the high-`k` one, the
    claim - loses every contest to one that fires ten times as often. Each
    bucket is scanned on its own and accepted only `HOLD_H` bars after its own
    last acceptance, so no two observations in a comparison share an outcome
    bar. Within a bar the nearest price to the previous close is taken, because
    that is the one price would have reached first.
    """
    n = len(bars["close"])
    out: dict[str, list[dict[str, float]]] = {b: [] for b in BUCKETS}
    last: dict[str, int] = {}
    order = sorted(named, key=lambda r: (r[0], abs(r[1] - bars["close"][max(r[0] - 1, 0)])))
    for bar, price, k, flags in order:
        if bar < WARMUP or bar + HOLD_H >= n or bar + SHAPE_N >= n or bar < 1:
            continue
        prev = bars["close"][bar - 1]
        side = 1 if prev > price else (-1 if prev < price else 0)
        if side == 0:
            continue
        key = bucket_of(k)
        if bar < last.get(key, -(10 ** 9)) + HOLD_H:
            continue
        last[key] = bar
        out[key].append(_row(bars, unit, strata, bar, price, side, k, flags,
                             plant=plant, rng=rng))
    return out


def placebo_of(bars, unit, strata, book: Book, real: list[dict[str, float]], rng):
    """One matched arrival at an unnamed price per real observation.

    Matched on the **signed displacement** from the previous close - so the
    approach side and the distance travelled to get there are the same - and on
    the volatility stratum. The price must be named by no framework at that
    bar, which is what makes it a `k = 0` control rather than a second level.
    `fade-to-value`'s 82% return rate was matched by exactly this kind of
    placebo on every class and a walk reads 0.825, so without it a level study
    measures mean reversion and reports it as structure.

    **The rejection counts are returned and reported**, because the binding
    constraint here is a finding rather than a nuisance: at the density four
    frameworks draw at, most prices are named by something, so a `k = 0`
    arrival is a selected state. `level-shield.md` hit the same wall from the
    other side - its clear arm was 7-9% of anchors and "a clear path is a
    regime of its own" - and a control that is itself a regime has to be read
    beside the walk rather than instead of it.
    """
    n = len(bars["close"])
    idx = np.arange(n)
    usable = (idx >= max(WARMUP, 1)) & (idx + HOLD_H < n) & (idx + SHAPE_N < n)
    pools = {s: np.flatnonzero(usable & (strata == s)) for s in range(STRATA)}
    out: list[dict[str, float]] = []
    taken: list[int] = []
    why = {"overlap": 0, "outside_bar": 0, "named": 0, "flat": 0, "exhausted": 0}
    # The stream is capacity-bound: de-overlapping at `HOLD_H` admits at most
    # `n / HOLD_H` placebos however many are asked for, so once a run of
    # draws has found nothing the pool is full rather than unlucky and the
    # search stops instead of spending four hundred tries per remaining row.
    dry = 0
    for src in real:
        if dry >= 40:
            why["exhausted"] += 1
            continue
        pool = pools.get(int(src["stratum"]))
        if pool is None or len(pool) == 0:
            continue
        delta = src["displacement"]
        drawn = False
        for _try in range(400):
            bar = int(pool[rng.randrange(len(pool))])
            at = bisect.bisect_left(taken, bar)
            near = ((at > 0 and bar - taken[at - 1] < HOLD_H)
                    or (at < len(taken) and taken[at] - bar < HOLD_H))
            if near:
                why["overlap"] += 1
                continue
            prev = bars["close"][bar - 1]
            price = prev - delta * unit[bar]
            if not (bars["low"][bar] <= price <= bars["high"][bar]):
                why["outside_bar"] += 1
                continue
            tol = TOL_VOL * unit[bar]
            if any(book.names(f, price, bar, tol) >= 0 for f in FRAMEWORKS):
                why["named"] += 1
                continue
            side = 1 if prev > price else (-1 if prev < price else 0)
            if side == 0:
                why["flat"] += 1
                continue
            taken.insert(at, bar)
            out.append(_row(bars, unit, strata, bar, price, side, 0,
                            (-1,) * len(FRAMEWORKS), plant=0.0, rng=None))
            drawn = True
            break
        dry = 0 if drawn else dry + 1
        if not drawn:
            why["exhausted"] += 1
    return out, why


# ───────────────────────────── the surrogate paths ─────────────────────────────


def bridge_path(steps: np.ndarray, ts: np.ndarray, start: float, rng,
                sub: int = SUBSTEPS, reflect: tuple[float, float] | None = None):
    """A series whose high and low are the **path's own** extremes.

    Each bar is a Brownian bridge of `sub` sub-steps pinned to a close-to-close
    step, so `open == previous close` exactly and the extremes are the running
    extremes of the path the closes trace. `entry_timing.walk_path` is where
    this came from and why: a surrogate that draws a close from a walk and then
    a *shape* resampled independently of it fires a stop where the price never
    went, and measured at zero edge, where optional stopping requires exactly
    zero, it pays `-0.1985R` against `+0.0003R` on real bars.

    `reflect` is `(step, probability)` and is used **only** by `MODE=power`: a
    sub-step crossing a multiple of `step` is reflected about the line with
    that probability, which plants a barrier on a grid specified independently
    of the path. With `reflect=None` the closes are a martingale up to the
    discreteness of the path, which is what `sub` controls.
    """
    n = len(steps) + 1
    sigma = float(np.std(steps)) or 1e-12
    gen = np.random.default_rng(rng.randrange(1 << 30))
    weights = np.arange(1, sub + 1, dtype=float) / sub
    high = np.empty(n)
    low = np.empty(n)
    base = np.empty(n)
    base[0] = high[0] = low[0] = start
    at = start
    chunk = 8192
    for s0 in range(0, n - 1, chunk):
        s1 = min(s0 + chunk, n - 1)
        rows = s1 - s0
        walk = np.cumsum(gen.normal(0.0, sigma / math.sqrt(sub), size=(rows, sub)), axis=1)
        bridge = walk - np.outer(walk[:, -1], weights) + np.outer(steps[s0:s1], weights)
        if reflect is None:
            # The fast path: the closes are the cumulative sum of the drawn
            # steps, so the bridge only has to supply each bar's extremes.
            ends = at + np.cumsum(steps[s0:s1])
            opens = np.r_[at, ends[:-1]]
            path = opens[:, None] + bridge
            base[s0 + 1:s1 + 1] = ends
            high[s0 + 1:s1 + 1] = np.maximum(opens, path.max(axis=1))
            low[s0 + 1:s1 + 1] = np.minimum(opens, path.min(axis=1))
            at = float(ends[-1])
            continue
        step_grid, prob = reflect
        for r in range(rows):
            path = _reflect_row(at, bridge[r], step_grid, prob, gen)
            i = s0 + r + 1
            base[i] = float(path[-1])
            high[i] = max(at, float(path.max()))
            low[i] = min(at, float(path.min()))
            at = base[i]
    return {"ts": np.asarray(ts[:n], dtype=np.int64), "open": np.r_[start, base[:-1]],
            "high": high, "low": low, "close": base}


def _reflect_row(start: float, bridge: np.ndarray, step: float, prob: float,
                 gen) -> np.ndarray:
    """Reflect one bar's sub-steps at multiples of `step`.

    A crossing is mirrored about the line it crossed, with probability `prob`.
    This is a real barrier: it changes where the path goes rather than what the
    harness records about it, so the detectors have to find it rather than be
    told. Reflection and not absorption, because an absorbing barrier also
    removes volatility and would be two plants at once.
    """
    out = np.empty(len(bridge))
    inc = np.diff(np.r_[0.0, bridge])
    at = start
    for idx in range(len(inc)):
        want = at + inc[idx]
        line = math.floor(at / step) * step
        hit = None
        if want > line + step:
            hit = line + step
        elif want < line:
            hit = line
        if hit is not None and gen.random() < prob:
            want = 2.0 * hit - want
        out[idx] = at = want
    return out


def garch_steps(steps: np.ndarray, rng) -> np.ndarray:
    """GARCH(1,1) with t(5) innovations, matched on the unconditional variance.

    Clustered volatility and fat tails, no participants and so no levels. The
    parameters are the standard (0.05, 0.90) pair rather than a fit: a fitted
    GARCH would be a model of this series, and the arm's job is to carry
    clustering rather than to be a forecast.
    """
    n = len(steps)
    var = float(np.var(steps)) or 1e-24
    alpha, beta = 0.05, 0.90
    omega = var * (1.0 - alpha - beta)
    gen = np.random.default_rng(rng.randrange(1 << 30))
    z = gen.standard_t(5, size=n) / math.sqrt(5.0 / 3.0)
    out = np.empty(n)
    h = var
    for i in range(n):
        out[i] = math.sqrt(h) * z[i]
        h = omega + alpha * out[i] * out[i] + beta * h
    return out - out.mean()


def surrogate(bars, name: str, rng, reflect=None):
    """The arm's bars. Both arms demean their steps.

    **A surrogate called driftless and not demeaned makes a barrier race pay:**
    `+0.1219R` at 240 sub-steps with the mean left in, and it did not shrink as
    the path was refined, so it was never the stop's overshoot.
    """
    steps = np.diff(bars["close"])
    if len(steps) < 2:
        return bars
    steps = steps - steps.mean()
    steps = (garch_steps(steps, rng) if name == "garchpath"
             else np.asarray(rng.choices(steps.tolist(), k=len(steps)), dtype=float))
    return bridge_path(steps, bars["ts"], float(bars["close"][0]), rng, reflect=reflect)


# ────────────────────────────────── statistics ──────────────────────────────────


def block_ci(values: np.ndarray, days: np.ndarray, draws: int = DRAWS, seed: int = SEED):
    """Mean, block-bootstrap standard error and a 95% interval, resampling
    whole UTC days.

    An ordinary standard error is too narrow: observations are de-overlapped
    within a stream but two streams' observations on one day share bars, and
    regimes persist for hours.
    """
    values = np.asarray(values, dtype=float)
    days = np.asarray(days)
    ok = np.isfinite(values)
    values, days = values[ok], days[ok]
    if len(values) == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")
    mean = float(values.mean())
    uniq, inverse = np.unique(days, return_inverse=True)
    if len(uniq) < 5:
        return mean, float("nan"), float("nan"), float("nan")
    order = np.argsort(inverse, kind="stable")
    sorted_vals = values[order]
    bounds = np.r_[0, np.cumsum(np.bincount(inverse, minlength=len(uniq)))]
    gen = np.random.default_rng(seed)
    got = np.empty(draws)
    for b in range(draws):
        pick = gen.integers(0, len(uniq), size=len(uniq))
        total = 0.0
        count = 0
        for d in pick:
            seg = sorted_vals[bounds[d]:bounds[d + 1]]
            total += seg.sum()
            count += len(seg)
        got[b] = total / max(count, 1)
    return mean, float(got.std(ddof=1)), float(np.quantile(got, 0.025)), float(
        np.quantile(got, 0.975))


def paired_gap(a, a_days, b, b_days, draws: int = DRAWS, seed: int = SEED):
    """The difference of two means, resampling **the same days** in both arms.

    The arms come from one series, so a day that was violent is violent in
    both. Resampling days independently would widen the interval by the common
    component and hide a real difference; resampling rows would narrow it by
    the shared bars.
    """
    a, b = np.asarray(a, float), np.asarray(b, float)
    a_days, b_days = np.asarray(a_days), np.asarray(b_days)
    ka, kb = np.isfinite(a), np.isfinite(b)
    a, a_days, b, b_days = a[ka], a_days[ka], b[kb], b_days[kb]
    if len(a) == 0 or len(b) == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")
    gap = float(a.mean() - b.mean())
    uniq = np.unique(np.concatenate([a_days, b_days]))
    if len(uniq) < 5:
        return gap, float("nan"), float("nan"), float("nan")
    pos = {d: i for i, d in enumerate(uniq)}
    ia = np.array([pos[d] for d in a_days])
    ib = np.array([pos[d] for d in b_days])
    sa, sb = np.argsort(ia, kind="stable"), np.argsort(ib, kind="stable")
    va, vb = a[sa], b[sb]
    ba = np.r_[0, np.cumsum(np.bincount(ia, minlength=len(uniq)))]
    bb = np.r_[0, np.cumsum(np.bincount(ib, minlength=len(uniq)))]
    gen = np.random.default_rng(seed)
    got = []
    for _draw in range(draws):
        pick = gen.integers(0, len(uniq), size=len(uniq))
        ta = sum(va[ba[d]:ba[d + 1]].sum() for d in pick)
        na = sum(ba[d + 1] - ba[d] for d in pick)
        tb = sum(vb[bb[d]:bb[d + 1]].sum() for d in pick)
        nb = sum(bb[d + 1] - bb[d] for d in pick)
        if na and nb:
            got.append(ta / na - tb / nb)
    if len(got) < 10:
        return gap, float("nan"), float("nan"), float("nan")
    arr = np.asarray(got)
    return gap, float(arr.std(ddof=1)), float(np.quantile(arr, 0.025)), float(
        np.quantile(arr, 0.975))


def gap_of_gaps(panel, a_hi, a_lo, b_hi, b_lo, draws: int = DRAWS, seed: int = SEED):
    """`(real gap - null gap)`, resampling **the same days across all four
    streams**.

    This is the headline, and it has to be a difference of differences because
    the level of a hold rate is not comparable between arms: the construction
    marks its race from a touched price rather than from where the path is, so
    every arm carries an offset of its own (`MODE=calibrate` measures it). What
    is comparable is how much `k` moves the rate, and the question is whether
    it moves it further on the market than on a walk whose levels nobody
    computes.

    The four streams come from the same bars, so a day that was violent is
    violent in all four and the day is the block.
    """
    parts = [(panel["hold"][m], panel["day"][m]) for m in (a_hi, a_lo, b_hi, b_lo)]
    if any(int(np.isfinite(v).sum()) < 30 for v, _d in parts):
        return float("nan"), float("nan"), float("nan"), float("nan")
    clean = []
    for v, d in parts:
        ok = np.isfinite(v)
        clean.append((v[ok], np.asarray(d)[ok]))
    point = ((clean[0][0].mean() - clean[1][0].mean())
             - (clean[2][0].mean() - clean[3][0].mean()))
    uniq = np.unique(np.concatenate([d for _v, d in clean]))
    if len(uniq) < 5:
        return point, float("nan"), float("nan"), float("nan")
    pos = {d: i for i, d in enumerate(uniq)}
    packed = []
    for v, d in clean:
        key = np.array([pos[x] for x in d])
        order = np.argsort(key, kind="stable")
        packed.append((v[order], np.r_[0, np.cumsum(np.bincount(key, minlength=len(uniq)))]))
    gen = np.random.default_rng(seed)
    got = []
    for _draw in range(draws):
        pick = gen.integers(0, len(uniq), size=len(uniq))
        means = []
        for vals, bounds in packed:
            total = sum(vals[bounds[d]:bounds[d + 1]].sum() for d in pick)
            count = sum(bounds[d + 1] - bounds[d] for d in pick)
            if not count:
                means = []
                break
            means.append(total / count)
        if len(means) == 4:
            got.append((means[0] - means[1]) - (means[2] - means[3]))
    if len(got) < 10:
        return point, float("nan"), float("nan"), float("nan")
    arr = np.asarray(got)
    return point, float(arr.std(ddof=1)), float(np.quantile(arr, 0.025)), float(
        np.quantile(arr, 0.975))


def bh(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Benjamini-Hochberg. Picking the best of 43 instruments gives a winner
    every time, so the cell count is part of the test."""
    items = sorted((p, k) for k, p in pvalues.items() if np.isfinite(p))
    out = dict.fromkeys(pvalues, False)
    if not items:
        return out
    m = len(items)
    passing = 0
    for rank, (p, _k) in enumerate(items, start=1):
        if p <= alpha * rank / m:
            passing = rank
    for _p, k in items[:passing]:
        out[k] = True
    return out


def two_sided(z: float) -> float:
    return float(math.erfc(abs(z) / math.sqrt(2.0)))


def n_modes(x: np.ndarray, h: float, grid: int = 1024) -> int:
    """Modes of a Gaussian kernel density at bandwidth `h`, on a fixed grid."""
    lo, hi = float(x.min()) - 3 * h, float(x.max()) + 3 * h
    if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
        return 1
    edges = np.linspace(lo, hi, grid + 1)
    counts, _ = np.histogram(x, bins=edges)
    step = (hi - lo) / grid
    span = max(int(math.ceil(4.0 * h / step)), 1)
    kernel = np.exp(-0.5 * ((np.arange(-span, span + 1) * step) / h) ** 2)
    dens = np.convolve(counts.astype(float), kernel, mode="same")
    rising = np.diff(dens) > 0
    return int(np.sum(rising[:-1] & ~rising[1:]))


def _critical_bandwidth(x: np.ndarray, sd: float, steps: int = 30) -> float:
    lo, hi = 1e-3 * sd, 6.0 * sd
    for _step in range(steps):
        mid = math.sqrt(lo * hi)
        if n_modes(x, mid) <= 1:
            hi = mid
        else:
            lo = mid
    return hi


def silverman(x: np.ndarray, draws: int = 200, seed: int = SEED) -> tuple[float, float]:
    """Silverman's critical bandwidth test for one mode against more.

    Returns `(h_crit / sd, p)`. The critical bandwidth is the smallest `h` at
    which the kernel density has a single mode, and a bimodal sample needs a
    large one. The p-value is a **smoothed bootstrap** under the unimodal null:
    resample from the density at `h_crit`, which is unimodal by construction,
    and count how often it needs a bandwidth at least as large. There is no
    `diptest` on the lab and this is the unimodality test that needs no
    package.
    """
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 200:
        return float("nan"), float("nan")
    if len(x) > 20_000:
        x = x[np.linspace(0, len(x) - 1, 20_000).astype(int)]
    sd = float(x.std(ddof=1)) or 1e-12
    h = _critical_bandwidth(x, sd)
    gen = np.random.default_rng(seed)
    n = len(x)
    beat = 0
    for _draw in range(draws):
        pick = x[gen.integers(0, n, size=n)]
        got = (pick + h * gen.standard_normal(n)) / math.sqrt(1.0 + (h / sd) ** 2)
        beat += int(_critical_bandwidth(got, float(got.std(ddof=1)) or 1e-12) >= h)
    return h / sd, (beat + 1) / (draws + 1)


def mixture(x: np.ndarray, iters: int = 200) -> dict[str, float]:
    """Two Gaussians against one, by EM, and **what kind** of two.

    The likelihood ratio is not the claim. A two-component mixture with one
    mean and two variances is a fat tail, which this desk measures everywhere -
    kurtosis 47-74 on traded instruments - and it beats a single Gaussian on
    every return series ever recorded. Bimodality is a *location* mixture, so
    `separation` - the distance between the fitted means in pooled standard
    deviations - is the number that answers the claim, and `dbic` only says the
    mixture fits better than one Gaussian for some reason.
    """
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 200:
        return {"dbic": float("nan"), "separation": float("nan"), "weight": float("nan")}
    sd = float(x.std(ddof=1)) or 1e-12
    mu = np.array([float(np.quantile(x, 0.25)), float(np.quantile(x, 0.75))])
    var = np.array([sd * sd, sd * sd])
    pi = np.array([0.5, 0.5])
    for _it in range(iters):
        dens = pi / np.sqrt(2 * math.pi * var) * np.exp(-0.5 * (x[:, None] - mu) ** 2 / var)
        tot = np.maximum(dens.sum(axis=1, keepdims=True), 1e-300)
        resp = dens / tot
        nk = resp.sum(axis=0) + 1e-12
        pi = nk / n
        mu = (resp * x[:, None]).sum(axis=0) / nk
        var = np.maximum((resp * (x[:, None] - mu) ** 2).sum(axis=0) / nk, 1e-24)
    dens = pi / np.sqrt(2 * math.pi * var) * np.exp(-0.5 * (x[:, None] - mu) ** 2 / var)
    ll2 = float(np.log(np.maximum(dens.sum(axis=1), 1e-300)).sum())
    ll1 = float(np.sum(-0.5 * np.log(2 * math.pi * sd * sd) - 0.5 * ((x - x.mean()) / sd) ** 2))
    dbic = (2 * math.log(n) - 2 * ll1) - (5 * math.log(n) - 2 * ll2)
    return {"dbic": dbic, "separation": float(abs(mu[0] - mu[1]) / sd),
            "weight": float(min(pi))}


def shape_stats(x: np.ndarray, *, silv: bool = True) -> dict[str, float]:
    """Everything the bimodality claim is tested with, for one sample."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    blank = {"n": float(len(x)), "kurtosis": float("nan"), "skew": float("nan"),
             "bc": float("nan"), "hcrit": float("nan"), "silverman_p": float("nan"),
             "dbic": float("nan"), "separation": float("nan"), "weight": float("nan")}
    if len(x) < 200:
        return blank
    sd = float(x.std(ddof=1)) or 1e-12
    z = (x - x.mean()) / sd
    skew = float(np.mean(z ** 3))
    kurt = float(np.mean(z ** 4)) - 3.0
    n = len(x)
    # Sarle's bimodality coefficient. A uniform distribution reads exactly
    # 5/9 = 0.5556 and that is the usual flag; a heavy-tailed unimodal sample
    # reads far below it, which is the direction this study expects.
    bc = (skew * skew + 1.0) / (kurt + (3.0 * (n - 1) ** 2) / ((n - 2) * (n - 3)))
    hcrit, p = silverman(x) if silv else (float("nan"), float("nan"))
    return {"n": float(n), "kurtosis": kurt, "skew": skew, "bc": float(bc),
            "hcrit": hcrit, "silverman_p": p, **mixture(x)}


# ──────────────────────────────── the unit of work ────────────────────────────────


def prepare(bars):
    """Bars to `(unit, strata, book, named)` - the whole causal pipeline."""
    unit = unit_of(bars)
    strata = strata_of(unit)
    rows = {f: dedupe(got, unit) for f, got in levels_for(bars, unit).items()}
    book = Book(rows, unit)
    return unit, strata, book, named_prices(book, bars, unit), rows


def one_series(job: tuple):
    """One (instrument, interval): every arm's observations and the book's
    description. The unit of parallel work."""
    sym, iv, path, plant = job
    rng = random.Random(f"{sym}/{iv}/{SEED}")
    try:
        raw, dropped = read(Path(path))
    except Exception as exc:                                        # noqa: BLE001
        return [], [{"sym": sym, "iv": iv, "error": repr(exc)[:120]}]
    bars = fold(raw, SEC[iv])
    if len(bars["close"]) < MIN_BARS:
        return [], [{"sym": sym, "iv": iv, "bars": len(bars["close"]), "error": "short"}]

    out: list[tuple[str, str, str, list[dict[str, float]]]] = []
    books: list[dict] = []
    for arm in ARMS:
        if arm == "placebo":
            continue
        use = bars if arm == "real" else surrogate(bars, arm, rng)
        unit, strata, book, named, rows = prepare(use)
        got = observe(use, unit, strata, named,
                      plant=plant if arm == "real" else 0.0, rng=rng)
        for bucket, got_rows in got.items():
            if got_rows:
                out.append((f"{sym}/{iv}", arm, bucket, got_rows))
        if arm == "real":
            books.append(describe(sym, iv, bars, unit, book, rows, named, dropped))
            if "placebo" in ARMS:
                flat = [r for b in ("k1", "k2", "k3") for r in got[b]]
                flat.sort(key=lambda r: r["bar"])
                extra, why = placebo_of(bars, unit, strata, book, flat, rng)
                books[-1].update({f"placebo_{k}": v for k, v in why.items()})
                books[-1]["placebo_drawn"] = len(extra)
                books[-1]["placebo_wanted"] = len(flat)
                if extra:
                    out.append((f"{sym}/{iv}", "placebo", "k0", extra))
    return out, books


def describe(sym: str, iv: str, bars, unit, book: Book, rows, named, dropped: int) -> dict:
    """The first deliverable, per series: firing rate, density and the full
    pairwise agreement matrix.

    Agreement is **the share of each pair's union** on which both frameworks
    name a price within one tolerance - a Jaccard over named prices, not a
    correlation of counts, because two frameworks that each emit six levels a
    bar and never the same price have a high count correlation and zero
    agreement. Computed on every `SAMPLE_EVERY`-th bar within `REACH_VOL` of
    the close, which is the book a desk would be looking at.
    """
    n = len(bars["close"])
    at = np.arange(WARMUP, n, SAMPLE_EVERY)
    out: dict[str, float | str | int] = {
        "sym": sym, "iv": iv, "family": FAMILY.get(sym, "?"),
        "bars": n, "dup_dropped": dropped, "sampled": len(at),
    }
    fires = dict.fromkeys(FRAMEWORKS, 0)
    density = dict.fromkeys(FRAMEWORKS, 0.0)
    pairs = [(a, b) for a in FRAMEWORKS for b in FRAMEWORKS if a < b]
    union = dict.fromkeys(pairs, 0)
    both = dict.fromkeys(pairs, 0)
    for i in at:
        price, u = float(bars["close"][i]), float(unit[i])
        reach, tol = REACH_VOL * u, TOL_VOL * u
        live = {f: book.live_near(f, price, int(i), reach) for f in FRAMEWORKS}
        for f, got in live.items():
            fires[f] += int(len(got) > 0)
            density[f] += len(got) / (2.0 * REACH_VOL)
        for a, b in pairs:
            xa, xb = live[a], live[b]
            if len(xa) == 0 and len(xb) == 0:
                continue
            hit_a = int(np.sum(np.min(np.abs(xb[None, :] - xa[:, None]), axis=1) <= tol)
                        ) if len(xa) and len(xb) else 0
            hit_b = int(np.sum(np.min(np.abs(xa[None, :] - xb[:, None]), axis=1) <= tol)
                        ) if len(xa) and len(xb) else 0
            shared = min(hit_a, hit_b)
            union[(a, b)] += len(xa) + len(xb) - shared
            both[(a, b)] += shared
    for f in FRAMEWORKS:
        out[f"fires_{f}"] = fires[f] / max(len(at), 1)
        out[f"density_{f}"] = density[f] / max(len(at), 1)
        out[f"levels_{f}"] = len(rows[f]) if f in rows else -1
    for a, b in pairs:
        out[f"agree_{a}_{b}"] = both[(a, b)] / max(union[(a, b)], 1)
    counts = np.array([r[2] for r in named]) if named else np.zeros(0)
    out["named_events"] = len(counts)
    for k in (1, 2, 3, 4):
        out[f"share_k{k}"] = float(np.mean(counts == k)) if len(counts) else float("nan")
    return out


# ─────────────────────────────── the panel, as columns ───────────────────────────────


class Panel:
    """Every observation as columns, with the keys interned.

    Three million observations as dictionaries is five gigabytes and as
    `float64` columns is six hundred megabytes, which is the difference between
    this running and being killed.
    """

    def __init__(self) -> None:
        self.series: list[str] = []
        self.arm: list[str] = []
        self.bucket: list[str] = []
        self.data: dict[str, list[np.ndarray]] = {}
        self.index: list[tuple[int, int]] = []
        self._at = 0

    def add(self, series: str, arm: str, bucket: str, rows: list[dict[str, float]]) -> None:
        for key in COLUMNS[3:]:
            self.data.setdefault(key, []).append(
                np.asarray([r.get(key, float("nan")) for r in rows], dtype=float))
        self.series.append(series)
        self.arm.append(arm)
        self.bucket.append(bucket)
        self.index.append((self._at, self._at + len(rows)))
        self._at += len(rows)

    @property
    def count(self) -> int:
        return self._at

    def finish(self) -> dict[str, np.ndarray]:
        got = {k: np.concatenate(v) if v else np.zeros(0) for k, v in self.data.items()}
        total = self._at
        label = {"series": np.empty(total, dtype=object), "arm": np.empty(total, dtype=object),
                 "bucket": np.empty(total, dtype=object)}
        for j, (lo, hi) in enumerate(self.index):
            label["series"][lo:hi] = self.series[j]
            label["arm"][lo:hi] = self.arm[j]
            label["bucket"][lo:hi] = self.bucket[j]
        return {**label, **got}


def save(panel: dict[str, np.ndarray], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **{k: (v.astype(str) if v.dtype == object else v)
                                 for k, v in panel.items()})
    print(f"wrote {path} ({len(panel['arm'])} observations)")


def load(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


# ─────────────────────────────────── the modes ───────────────────────────────────


def use_arms(names: tuple[str, ...]) -> None:
    """Narrow the arm list for a mode that needs only some of it.

    Assigning to the module global and **not** to `os.environ`: `ARMS` is read
    once at import, so setting the variable afterwards changes nothing and the
    mode quietly runs every arm. That shape - a configuration read at import
    and set at call time - is the one `till.env needs a container recreate` is
    about, and it reads as healthy either way.
    """
    globals()["ARMS"] = names


def jobs(plant: float = 0.0) -> list[tuple]:
    src = sources()
    want = [s for s in (*DEEP, *WIDE, *SYNTH) if s in src]
    only = os.environ.get("ONLY")
    if only:
        want = [s for s in want if s in only.split(",")]
    return [(s, iv, str(src[s]), plant) for s in want for iv in INTERVALS]


def run_pool(todo: list[tuple]):
    import multiprocessing as mp                                    # noqa: PLC0415
    workers = max(min(_i("WORKERS", 20), len(todo)), 1)
    panel = Panel()
    books: list[dict] = []
    done = 0
    if workers <= 1:
        for job in todo:
            got, book = one_series(job)
            for series, arm, bucket, rows in got:
                panel.add(series, arm, bucket, rows)
            books.extend(book)
        return panel.finish(), books
    with mp.Pool(workers) as pool:
        for got, book in pool.imap_unordered(one_series, todo, chunksize=1):
            for series, arm, bucket, rows in got:
                panel.add(series, arm, bucket, rows)
            books.extend(book)
            done += 1
            print(f"  .. {done}/{len(todo)} series, {panel.count} observations", flush=True)
    return panel.finish(), books


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    keys: list[str] = []
    for row in rows:
        for k in row:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")


def mode_overlap() -> None:
    print("== firing rates, density and the pairwise agreement matrix ==", flush=True)
    use_arms(("real",))
    _panel, books = run_pool(jobs())
    write_csv(OUT / "overlap.csv", books)
    show_overlap(books)


def show_overlap(books: list[dict]) -> None:
    good = [b for b in books if "error" not in b]
    if not good:
        print("every series errored")
        return
    print(f"\n{len(good)} series")
    print("framework     fires   density/unit    levels")
    for f in FRAMEWORKS:
        print(f"{f:<10} {np.nanmean([b[f'fires_{f}'] for b in good]):7.3f} "
              f"{np.nanmean([b[f'density_{f}'] for b in good]):11.3f} "
              f"{np.nansum([b[f'levels_{f}'] for b in good]):11.0f}")
    print("\npair agreement (share of the pair's union naming one price)")
    for a in FRAMEWORKS:
        for b in FRAMEWORKS:
            if a < b:
                print(f"  {a:>6} vs {b:<6} "
                      f"{np.nanmean([x[f'agree_{a}_{b}'] for x in good]):.4f}")
    print("\nk of a named price, over first touches")
    for k in (1, 2, 3, 4):
        print(f"  k={k}  {np.nanmean([b[f'share_k{k}'] for b in good]):.4f}")


def mode_run() -> None:
    print("== the three outcomes ==", flush=True)
    panel, books = run_pool(jobs())
    save(panel, OUT / "obs.npz")
    write_csv(OUT / "overlap.csv", books)
    show_overlap(books)
    report(panel)


def mode_power() -> None:
    rows: list[dict] = []
    print("== label plant: the minimum detectable hold-rate gap ==", flush=True)
    use_arms(("real",))
    for strength in (0.0, 0.01, 0.02, 0.05, 0.10, 0.20):
        panel, _books = run_pool(jobs(plant=strength))
        for bucket in ("k1", "k2", "k3"):
            sel = (panel["arm"] == "real") & (panel["bucket"] == bucket)
            mean, se, lo, hi = block_ci(panel["hold"][sel], panel["day"][sel])
            n = int(np.isfinite(panel["hold"][sel]).sum())
            rows.append({"plant": strength, "kind": "label", "bucket": bucket,
                         "n": n, "hold": mean, "se": se, "lo": lo, "hi": hi})
            print(f"  plant {strength:.2f} {bucket}: {mean:.4f} +- {se:.4f} on {n}",
                  flush=True)
        a = (panel["arm"] == "real") & np.isin(panel["bucket"], ("k2", "k3"))
        b = (panel["arm"] == "real") & (panel["bucket"] == "k1")
        gap, se, lo, hi = paired_gap(panel["hold"][a], panel["day"][a],
                                     panel["hold"][b], panel["day"][b])
        rows.append({"plant": strength, "kind": "label-gap", "bucket": "k2+ - k1",
                     "n": int(a.sum()), "hold": gap, "se": se, "lo": lo, "hi": hi})
        print(f"  plant {strength:.2f} gap: {gap:+.4f} +- {se:.4f} "
              f"[{lo:+.4f}, {hi:+.4f}]", flush=True)
    print("\n== geometric plant: can the detectors see a barrier at all? ==", flush=True)
    rows.extend(geometric_power())
    write_csv(OUT / "power.csv", rows)


def geometric_power() -> list[dict]:
    """A reflecting grid planted on a generated path, found by the detectors.

    The grid is the **round** grid, which is a function of the price and the
    volatility unit and so does not depend on the path - no circularity. The
    path is reflected at it with probability `prob`, the whole four-framework
    pipeline runs on the result, and the question is whether the hold rate at
    prices the `round` framework names rises while the rate at prices it does
    not stays flat.
    """
    src = sources()
    want = [s for s in ("EURUSD", "XAUUSD", "BTCUSD", "US SP 500") if s in src]
    out: list[dict] = []
    # **The sweep is of the realised lift, not of the nominal probability.** A
    # sub-step reflected with probability `p` is retried by the next sub-step,
    # so sixty sub-steps a bar leak a barrier badly: measured here, `p = 0.6`
    # moves the hold rate at a planted line by nothing and `p = 0.9` moves it
    # by eleven points. The reported unit is therefore the hold rate itself.
    for prob in (0.0, 0.5, 0.9, 0.99):
        for sym in want:
            rng = random.Random(f"{sym}/plant/{prob}/{SEED}")
            raw, _dropped = read(src[sym])
            bars = fold(raw, SEC["1h"])
            # Half the step, so **every** round level is planted: the whole
            # grid alone leaves the half-steps unplanted and dilutes the lift
            # by half.
            step = round_step(float(np.median(unit_of(bars)))) / 2.0
            use = surrogate(bars, "walkpath", rng, reflect=(step, prob))
            unit, strata, _book, named, _rows = prepare(use)
            got = observe(use, unit, strata, named, rng=rng)
            flat = [r for b in ("k1", "k2", "k3") for r in got[b]]
            for has in (1.0, 0.0):
                sel = [r for r in flat if r["has_round"] == has]
                hold = np.array([r["hold"] for r in sel])
                days = np.array([r["day"] for r in sel])
                mean, se, lo, hi = block_ci(hold, days, draws=400)
                out.append({"plant": prob, "kind": "geometric", "sym": sym,
                            "has_round": has, "n": int(np.isfinite(hold).sum()),
                            "hold": mean, "se": se, "lo": lo, "hi": hi})
                print(f"  prob {prob:.2f} {sym:<12} round={has:.0f}: {mean:.4f} "
                      f"+- {se:.4f} on {out[-1]['n']}", flush=True)
    return out


def mode_sweep() -> None:
    """The whole grid, reported whole rather than at its best cell.

    Four parameters are chosen in this file and each could be the reason for a
    result: the tolerance that makes two prices one price, the race distance,
    the life of a level and the number of volatility strata. Every cell is
    printed with both arms, because a sweep that reports only the real arm
    turns a grid into a search.
    """
    use_arms(("real", "walkpath"))
    grid = [
        ("base", {}),
        ("tol 0.10", {"TOL_VOL": 0.10}),
        ("tol 0.50", {"TOL_VOL": 0.50}),
        ("dist 0.5", {"HOLD_VOL": 0.5}),
        ("dist 2.0", {"HOLD_VOL": 2.0}),
        ("life 150", {"LIFE": 150}),
        ("life 1500", {"LIFE": 1500}),
        ("strata 10", {"STRATA": 10}),
        ("swing 20", {"SWING": 20}),
    ]
    base = {k: globals()[k] for k in ("TOL_VOL", "HOLD_VOL", "LIFE", "STRATA", "SWING")}
    rows: list[dict] = []
    for name, changes in grid:
        globals().update(base)
        globals().update(changes)
        panel, _books = run_pool(jobs())
        fam = _family(panel)
        traded = fam != "deriv"
        line = {"cell": name, **{k: globals()[k] for k in base}}
        for arm in ("real", "walkpath"):
            hi = traded & (panel["arm"] == arm) & np.isin(panel["bucket"], ("k2", "k3"))
            lo = traded & (panel["arm"] == arm) & (panel["bucket"] == "k1")
            gap, se, _a, _b = paired_gap(panel["hold"][hi], panel["day"][hi],
                                         panel["hold"][lo], panel["day"][lo], draws=400)
            line[f"{arm}_gap"] = gap
            line[f"{arm}_se"] = se
            line[f"{arm}_n"] = int(np.isfinite(panel["hold"][hi]).sum())
            line[f"{arm}_hold_k2"] = float(np.nanmean(panel["hold"][hi]))
        a_hi = traded & (panel["arm"] == "real") & np.isin(panel["bucket"], ("k2", "k3"))
        a_lo = traded & (panel["arm"] == "real") & (panel["bucket"] == "k1")
        b_hi = traded & (panel["arm"] == "walkpath") & np.isin(panel["bucket"], ("k2", "k3"))
        b_lo = traded & (panel["arm"] == "walkpath") & (panel["bucket"] == "k1")
        got, se, lo_ci, hi_ci = gap_of_gaps(panel, a_hi, a_lo, b_hi, b_lo, draws=400)
        line.update(excess=got, excess_se=se, excess_lo=lo_ci, excess_hi=hi_ci)
        rows.append(line)
        print(f"{name:<10} real {line['real_gap']:+.4f} +- {line['real_se']:.4f}  "
              f"walk {line['walkpath_gap']:+.4f} +- {line['walkpath_se']:.4f}  "
              f"excess {got:+.4f} [{lo_ci:+.4f}, {hi_ci:+.4f}]  n {line['real_n']}",
              flush=True)
        write_csv(OUT / "sweep.csv", rows)
    globals().update(base)


def mode_lifesweep() -> None:
    """The level-life axis on its own, because it is the one knob under which
    the market's `k` gap and a walk's move in **opposite** directions.

    `MODE=sweep` found the excess changing sign with the tolerance, which
    disqualifies it: an effect cannot depend on what counts as "the same price".
    The life knob is different in kind - it is how long a level stays in the
    book, which is the closest thing in this harness to *how long anybody is
    still watching* - and over 150, 500 and 1500 bars the market's gap went
    +0.0191, +0.0156, +0.0097 while the walk's went +0.0022, +0.0170, +0.0279.

    That is either the watchedness claim showing itself at short life or two
    geometry terms crossing, and three points cannot tell. **The prediction is
    stated here before the run**: if it is recency, the market's gap keeps
    rising as the life shortens and the walk's keeps falling, monotonically,
    through 50 and 100 bars. If either series turns over, it is neither.
    """
    use_arms(("real", "walkpath"))
    base = {k: globals()[k] for k in ("TOL_VOL", "HOLD_VOL", "LIFE", "STRATA", "SWING")}
    rows: list[dict] = []
    for life in (50, 100, 150, 300, 500, 1000, 1500):
        globals().update(base)
        globals()["LIFE"] = life
        panel, books = run_pool(jobs())
        fam = _family(panel)
        traded = fam != "deriv"
        good = [x for x in books if "error" not in x]
        line: dict[str, float | str] = {"cell": f"life {life}", "LIFE": life}
        line["share_k2plus"] = float(np.nanmean(
            [1.0 - x["share_k1"] for x in good])) if good else float("nan")
        for f in FRAMEWORKS:
            line[f"density_{f}"] = float(np.nanmean([x[f"density_{f}"] for x in good]))
        for arm in ("real", "walkpath"):
            hi = traded & (panel["arm"] == arm) & np.isin(panel["bucket"], ("k2", "k3"))
            lo = traded & (panel["arm"] == arm) & (panel["bucket"] == "k1")
            gap, se, _a, _b = paired_gap(panel["hold"][hi], panel["day"][hi],
                                         panel["hold"][lo], panel["day"][lo], draws=400)
            line[f"{arm}_gap"] = gap
            line[f"{arm}_se"] = se
            line[f"{arm}_n"] = int(np.isfinite(panel["hold"][hi]).sum())
        a_hi = traded & (panel["arm"] == "real") & np.isin(panel["bucket"], ("k2", "k3"))
        a_lo = traded & (panel["arm"] == "real") & (panel["bucket"] == "k1")
        b_hi = traded & (panel["arm"] == "walkpath") & np.isin(panel["bucket"], ("k2", "k3"))
        b_lo = traded & (panel["arm"] == "walkpath") & (panel["bucket"] == "k1")
        got, se, lo_ci, hi_ci = gap_of_gaps(panel, a_hi, a_lo, b_hi, b_lo, draws=400)
        line.update(excess=got, excess_se=se, excess_lo=lo_ci, excess_hi=hi_ci)
        rows.append(line)
        print(f"life {life:<5} k>=2 share {line['share_k2plus']:.3f}  "
              f"real {line['real_gap']:+.4f} +- {line['real_se']:.4f}  "
              f"walk {line['walkpath_gap']:+.4f} +- {line['walkpath_se']:.4f}  "
              f"excess {got:+.4f} [{lo_ci:+.4f}, {hi_ci:+.4f}]  n {line['real_n']}",
              flush=True)
        write_csv(OUT / "lifesweep.csv", rows)
    globals().update(base)


def mode_calibrate() -> None:
    """What the construction reads at **random anchors**, where there is no
    level and no detector.

    This exists because the walk arm does not read 0.5 and the reason has to be
    named rather than absorbed. The race is marked from the level `p`, but the
    path is at the arrival bar's **close** when the race starts, and a bar that
    dipped to `p` and closed is on average displaced back toward the side it
    came from - so the hold barrier is nearer than the break barrier by a
    fraction of a bar range before anything has happened. That is a property of
    marking a race from a touched price, not of levels.

    Two columns separate it, on generated bars with **random anchors so the
    detector cannot be the cause** - the same control
    `entry_timing.walk_path`'s docstring uses:

    * `from_level` - barriers at `p +- dist`, which is what the study measures;
    * `from_close` - barriers at `close +- dist`, which is a martingale race and
      owes exactly 0.5.

    If `from_close` reads 0.5 and `from_level` reads above it, the offset is the
    construction and every arm carries it equally, which is why the study's
    verdict rests on differences between arms and never on the level of one.
    """
    rows: list[dict] = []
    gen = np.random.default_rng(SEED)
    for name, kind in (("bridge-iid", "iid"), ("bridge-garch", "garch")):
        for trial in range(_i("CALIB_TRIALS", 4)):
            rng = random.Random(f"{name}/{trial}/{SEED}")
            n = _i("CALIB_BARS", 60_000)
            steps = gen.normal(0.0, 1.0, size=n - 1)
            if kind == "garch":
                steps = garch_steps(steps, rng)
            bars = bridge_path(steps, np.arange(n, dtype=np.int64) * 3600, 1000.0, rng)
            unit = unit_of(bars)
            at_level: list[float] = []
            at_close: list[float] = []
            for bar in range(WARMUP, n - HOLD_H - 1, HOLD_H):
                prev_hi, prev_lo = bars["high"][bar - 1], bars["low"][bar - 1]
                lo, hi = bars["low"][bar], bars["high"][bar]
                # A price this bar reached and the previous one did not, which
                # is exactly the arrival condition the detector produces.
                span = [(lo, min(hi, prev_lo)), (max(lo, prev_hi), hi)]
                span = [(a, b) for a, b in span if b > a]
                if not span:
                    continue
                a, b = span[gen.integers(0, len(span))]
                price = float(gen.uniform(a, b))
                prev = bars["close"][bar - 1]
                side = 1 if prev > price else (-1 if prev < price else 0)
                if side == 0:
                    continue
                dist = HOLD_VOL * unit[bar]
                got, _took = race(bars, bar, price, side, dist)
                if got:
                    at_level.append(float(got > 0))
                shifted = float(bars["close"][bar])
                got, _took = race(bars, bar, shifted, side, dist)
                if got:
                    at_close.append(float(got > 0))
            for label, got in (("from_level", at_level), ("from_close", at_close)):
                arr = np.asarray(got)
                rows.append({"series": name, "trial": trial, "marked": label,
                             "n": len(arr), "hold": float(arr.mean()) if len(arr) else
                             float("nan"),
                             "se": float(arr.std(ddof=1) / math.sqrt(len(arr)))
                             if len(arr) > 2 else float("nan")})
                print(f"  {name:<13} {trial} {label:<11} {rows[-1]['hold']:.4f} "
                      f"+- {rows[-1]['se']:.4f} on {len(arr)}", flush=True)
    write_csv(OUT / "calibrate.csv", rows)
    for label in ("from_level", "from_close"):
        got = [r["hold"] for r in rows if r["marked"] == label]
        print(f"{label:<11} pooled {np.mean(got):.4f} over {len(got)} series")


def mode_cost() -> None:
    """The venue's own round trip, in R at this study's stop.

    The ceiling is 0.16 of risk. The `spread` column on stored bars is in
    **points, not price**, and is not a fallback: this repository measured it as
    zero on 7-35% of bars and a median 3-8x below the terminal's quote, so a
    cost taken from it is the one number that looks like a measurement and is
    not.
    """
    # **Found rather than assumed.** The harness is staged outside
    # `~/till_infinity/repo` - `lab.sh sync` rsyncs with `--delete` and would
    # remove it from under a running job - so `__file__`'s parent is not the
    # repository and the sibling path misses. Every `sys.path` root is tried,
    # which covers both the in-repo layout and the staged one.
    for root in [str(Path(__file__).resolve().parents[1]), *sys.path]:
        if (Path(root) / "harness" / "venue.py").exists():
            sys.path.insert(0, str(Path(root) / "harness"))
            break
        if (Path(root) / "research" / "harness" / "venue.py").exists():
            sys.path.insert(0, str(Path(root) / "research" / "harness"))
            break
    from venue import quoted                                        # noqa: PLC0415

    src = sources()
    rows: list[dict] = []
    for sym in ("XAUUSD", "EURUSD", "BTCUSD", "US SP 500", "XAGUSD"):
        if sym not in src:
            continue
        trip = quoted(sym)
        raw, _dropped = read(src[sym])
        for iv in INTERVALS:
            bars = fold(raw, SEC[iv])
            u = float(np.nanmedian(unit_of(bars)))
            rows.append({"sym": sym, "iv": iv, "round_trip_px": trip, "unit_px": u,
                         "stop_px": HOLD_VOL * u, "cost_r": trip / max(HOLD_VOL * u, 1e-12)})
            print(f"  {sym:<12} {iv:<4} trip {trip:.6g} px, stop {HOLD_VOL * u:.6g} px, "
                  f"{rows[-1]['cost_r']:.4f} R", flush=True)
    write_csv(OUT / "cost.csv", rows)


# ──────────────────────────────────── reporting ────────────────────────────────────


def stratified(panel, sel: np.ndarray) -> float:
    """The hold rate averaged over volatility strata with equal weight.

    Not the pooled rate. AUC is free on volatility targets - 0.805 on a
    constant-volatility process against 0.525 within strata - so a difference
    between two arms with different regime mixes is a difference in the mix
    until it is shown within strata.
    """
    got = []
    for s in range(STRATA):
        hold = panel["hold"][sel & (panel["stratum"] == s)]
        hold = hold[np.isfinite(hold)]
        if len(hold) >= 30:
            got.append(hold.mean())
    return float(np.mean(got)) if got else float("nan")


def _family(panel) -> np.ndarray:
    return np.array([FAMILY.get(s.split("/")[0], "?") for s in panel["series"]])


def report(panel=None) -> None:
    panel = panel if panel is not None else load(OUT / "obs.npz")
    if len(panel["arm"]) == 0:
        print("no observations")
        return
    fam = _family(panel)
    traded = fam != "deriv"
    cells: list[dict] = []

    print("\n=== 1. hold rate on the arriving side, traded instruments ===")
    print("arm/bucket        n      hold      se          [95%]        stratified   "
          "mean |displacement|")
    for arm in ("real", "placebo", "walkpath", "garchpath"):
        for bucket in BUCKETS:
            sel = traded & (panel["arm"] == arm) & (panel["bucket"] == bucket)
            if int(np.isfinite(panel["hold"][sel]).sum()) < 50:
                continue
            mean, se, lo, hi = block_ci(panel["hold"][sel], panel["day"][sel])
            n = int(np.isfinite(panel["hold"][sel]).sum())
            disp = float(np.nanmean(np.abs(panel["displacement"][sel])))
            print(f"{arm:>9}/{bucket:<4} {n:7d}  {mean:.4f}  {se:.4f}  "
                  f"[{lo:.4f}, {hi:.4f}]   {stratified(panel, sel):.4f}      {disp:.3f}")
            cells.append({"scope": "traded", "arm": arm, "bucket": bucket, "n": n,
                          "hold": mean, "se": se, "lo": lo, "hi": hi,
                          "stratified": stratified(panel, sel), "displacement": disp,
                          "censored": float(np.mean(~np.isfinite(panel["hold"][sel])))})

    print("\nthe comparison that decides: k>=2 against k=1, same days")
    for arm in ("real", "walkpath", "garchpath"):
        a = traded & (panel["arm"] == arm) & np.isin(panel["bucket"], ("k2", "k3"))
        b = traded & (panel["arm"] == arm) & (panel["bucket"] == "k1")
        if int(np.isfinite(panel["hold"][a]).sum()) < 50:
            continue
        gap, se, lo, hi = paired_gap(panel["hold"][a], panel["day"][a],
                                     panel["hold"][b], panel["day"][b])
        print(f"  {arm:<10} {gap:+.4f} +- {se:.4f}  [{lo:+.4f}, {hi:+.4f}]")
        cells.append({"scope": "traded", "arm": arm, "bucket": "k2+ - k1",
                      "n": int(a.sum()), "hold": gap, "se": se, "lo": lo, "hi": hi})
    for arm in ("real",):
        a = traded & (panel["arm"] == arm) & np.isin(panel["bucket"], ("k2", "k3"))
        b = traded & (panel["arm"] == "placebo")
        gap, se, lo, hi = paired_gap(panel["hold"][a], panel["day"][a],
                                     panel["hold"][b], panel["day"][b])
        print(f"  real k>=2 against the matched placebo: {gap:+.4f} +- {se:.4f} "
              f"[{lo:+.4f}, {hi:+.4f}]")
        cells.append({"scope": "traded", "arm": "real", "bucket": "k2+ - placebo",
                      "n": int(a.sum()), "hold": gap, "se": se, "lo": lo, "hi": hi})

    print("\nper framework: alone against joined by at least one other")
    for arm in ("real", "walkpath", "garchpath"):
        for f in FRAMEWORKS:
            base = traded & (panel["arm"] == arm) & (panel[f"has_{f}"] == 1.0)
            alone = base & (panel["k"] == 1.0)
            joined = base & (panel["k"] >= 2.0)
            na = int(np.isfinite(panel["hold"][alone]).sum())
            nb = int(np.isfinite(panel["hold"][joined]).sum())
            if na < 50 or nb < 50:
                continue
            gap, se, lo, hi = paired_gap(panel["hold"][joined], panel["day"][joined],
                                         panel["hold"][alone], panel["day"][alone])
            ma = float(np.nanmean(panel["hold"][alone]))
            mb = float(np.nanmean(panel["hold"][joined]))
            print(f"  {arm:<9} {f:<6} alone {ma:.4f} ({na})  joined {mb:.4f} ({nb})  "
                  f"gap {gap:+.4f} +- {se:.4f} [{lo:+.4f}, {hi:+.4f}]")
            cells.append({"scope": "framework", "arm": arm, "bucket": f, "n": nb,
                          "hold": mb, "se": se, "lo": lo, "hi": hi, "alone": ma,
                          "stratified": stratified(panel, joined)})

    print("\nthe headline: how much further k moves the market than it moves a null")
    for null in ("walkpath", "garchpath"):
        a_hi = traded & (panel["arm"] == "real") & np.isin(panel["bucket"], ("k2", "k3"))
        a_lo = traded & (panel["arm"] == "real") & (panel["bucket"] == "k1")
        b_hi = traded & (panel["arm"] == null) & np.isin(panel["bucket"], ("k2", "k3"))
        b_lo = traded & (panel["arm"] == null) & (panel["bucket"] == "k1")
        got, se, lo, hi = gap_of_gaps(panel, a_hi, a_lo, b_hi, b_lo)
        print(f"  real gap minus {null:<10} {got:+.4f} +- {se:.4f} [{lo:+.4f}, {hi:+.4f}]")
        cells.append({"scope": "headline", "arm": f"real-{null}", "bucket": "k2+ - k1",
                      "n": int(a_hi.sum()), "hold": got, "se": se, "lo": lo, "hi": hi})
    for f in FRAMEWORKS:
        a_hi = traded & (panel["arm"] == "real") & (panel[f"has_{f}"] == 1.0) & (
            panel["k"] >= 2.0)
        a_lo = traded & (panel["arm"] == "real") & (panel[f"has_{f}"] == 1.0) & (
            panel["k"] == 1.0)
        b_hi = traded & (panel["arm"] == "walkpath") & (panel[f"has_{f}"] == 1.0) & (
            panel["k"] >= 2.0)
        b_lo = traded & (panel["arm"] == "walkpath") & (panel[f"has_{f}"] == 1.0) & (
            panel["k"] == 1.0)
        got, se, lo, hi = gap_of_gaps(panel, a_hi, a_lo, b_hi, b_lo)
        print(f"  {f:<6} joined-minus-alone, real minus walkpath {got:+.4f} +- {se:.4f} "
              f"[{lo:+.4f}, {hi:+.4f}]")
        cells.append({"scope": "headline", "arm": "real-walkpath", "bucket": f,
                      "n": int(a_hi.sum()), "hold": got, "se": se, "lo": lo, "hi": hi})

    print("\ndouble bottoms and tops, against a single swing (real arm)")
    base = traded & (panel["arm"] == "real") & (panel["has_swing"] == 1.0)
    for flag, name in ((1.0, "doubled"), (0.0, "single")):
        sel = base & (panel["doubled"] == flag)
        n = int(np.isfinite(panel["hold"][sel]).sum())
        if n < 50:
            continue
        mean, se, lo, hi = block_ci(panel["hold"][sel], panel["day"][sel])
        print(f"  {name:<8} {mean:.4f} +- {se:.4f} [{lo:.4f}, {hi:.4f}] on {n}")
        cells.append({"scope": "doubled", "arm": "real", "bucket": name, "n": n,
                      "hold": mean, "se": se, "lo": lo, "hi": hi})

    print("\n=== the controls that must read something, and nothing ===")
    for name, want in (("Range Break, positive control", POSITIVE),
                       ("Volatility 25/75, placebo pair", PLACEBO_PAIR)):
        pick = np.isin([s.split("/")[0] for s in panel["series"]], want)
        for arm in ("real", "walkpath"):
            for bucket in ("k1", "k2", "k3"):
                sel = pick & (panel["arm"] == arm) & (panel["bucket"] == bucket)
                n = int(np.isfinite(panel["hold"][sel]).sum())
                if n < 50:
                    continue
                mean, se, _lo, _hi = block_ci(panel["hold"][sel], panel["day"][sel])
                print(f"  {name:<32} {arm:<9} {bucket}: {mean:.4f} +- {se:.4f} on {n}")
                cells.append({"scope": name, "arm": arm, "bucket": bucket, "n": n,
                              "hold": mean, "se": se})

    print("\n=== per instrument and interval, k>=2 minus k=1, BH over cells ===")
    pvals: dict[str, float] = {}
    detail: dict[str, tuple] = {}
    for series in sorted(set(panel["series"].tolist())):
        at = panel["series"] == series
        a = at & (panel["arm"] == "real") & np.isin(panel["bucket"], ("k2", "k3"))
        b = at & (panel["arm"] == "real") & (panel["bucket"] == "k1")
        na = int(np.isfinite(panel["hold"][a]).sum())
        nb = int(np.isfinite(panel["hold"][b]).sum())
        if na < 50 or nb < 50:
            continue
        gap, se, lo, hi = paired_gap(panel["hold"][a], panel["day"][a],
                                     panel["hold"][b], panel["day"][b], draws=300)
        if not np.isfinite(se) or se <= 0:
            continue
        pvals[series] = two_sided(gap / se)
        detail[series] = (gap, se, lo, hi, na, nb)
    survivors = bh(pvals)
    print(f"  {len(pvals)} cells, {sum(1 for v in detail.values() if v[0] > 0)} positive, "
          f"{sum(1 for v in detail.values() if v[2] > 0)} with a lower bound above zero, "
          f"{sum(survivors.values())} BH survivors")
    # **Every cell goes to the CSV, not only the printed ones.** The first
    # version wrote the ten largest gaps, so a Benjamini-Hochberg survivor with
    # a small gap and a large sample - which is the only kind worth having -
    # was counted in the summary line and absent from the file, and nobody
    # could audit which cell it was.
    for key, (gap, se, lo, hi, na, nb) in detail.items():
        cells.append({"scope": "cell", "arm": "real", "bucket": key, "n": na,
                      "n_alone": nb, "hold": gap, "se": se, "lo": lo, "hi": hi,
                      "p": pvals[key], "bh": int(bool(survivors.get(key)))})
    shown = sorted(detail, key=lambda k: -detail[k][0])[:10]
    for key in [*shown, *(k for k in detail if survivors.get(k) and k not in shown)]:
        gap, se, lo, hi, na, nb = detail[key]
        print(f"    {key:<32} {gap:+.4f} +- {se:.4f} [{lo:+.4f}, {hi:+.4f}] "
              f"{na}/{nb}{'  BH' if survivors.get(key) else ''}")

    print(f"\n=== 2. bimodality: the next-{SHAPE_N}-bar return, signed by the "
          "arriving side ===")
    print("arm/bucket        n     skew  kurtosis       bc  h_crit/sd  silv_p"
          "     dBIC  separation  weight")
    for arm in ("real", "placebo", "walkpath", "garchpath"):
        for bucket in BUCKETS:
            sel = traded & (panel["arm"] == arm) & (panel["bucket"] == bucket)
            got = panel["shape"][sel]
            if np.isfinite(got).sum() < 500:
                continue
            s = shape_stats(got)
            print(f"{arm:>9}/{bucket:<4} {int(s['n']):6d} {s['skew']:8.3f} "
                  f"{s['kurtosis']:9.3f} {s['bc']:8.4f} {s['hcrit']:10.4f} "
                  f"{s['silverman_p']:7.3f} {s['dbic']:8.1f} {s['separation']:11.3f} "
                  f"{s['weight']:7.3f}")
            cells.append({"scope": "shape", "arm": arm, "bucket": bucket, **s})

    print("\n=== 3. the cascade, conditional on breaking ===")
    print("arm/bucket        n   went_on       se   realised/unit   excursion/unit")
    for arm in ("real", "placebo", "walkpath", "garchpath"):
        for bucket in BUCKETS:
            sel = (traded & (panel["arm"] == arm) & (panel["bucket"] == bucket)
                   & (panel["hold"] == 0.0))
            if sel.sum() < 50:
                continue
            went = panel["cascade_went"][sel]
            decided = went != 0.0
            mean, se, _lo, _hi = block_ci((went[decided] > 0).astype(float),
                                          panel["day"][sel][decided], draws=400)
            print(f"{arm:>9}/{bucket:<4} {int(sel.sum()):6d}  {mean:.4f}  {se:.4f}   "
                  f"{np.nanmean(panel['cascade_realised'][sel]):10.4f}  "
                  f"{np.nanmean(panel['cascade_far'][sel]):10.4f}")
            cells.append({"scope": "cascade", "arm": arm, "bucket": bucket,
                          "n": int(sel.sum()), "hold": mean, "se": se,
                          "realised": float(np.nanmean(panel["cascade_realised"][sel])),
                          "excursion": float(np.nanmean(panel["cascade_far"][sel]))})

    print("\n=== the mechanism: the arrival's own geometry ===")
    print("Each arrival is marked from a price the bar touched, so where in the bar")
    print("that price sits decides how far the race already is before it starts.")
    print("arm       decile of |displacement|   k=1       k>=2      gap")
    edges = np.nanquantile(np.abs(panel["displacement"][traded]), np.linspace(0, 1, 6))
    for arm in ("real", "walkpath"):
        gaps = []
        for j in range(len(edges) - 1):
            band = (traded & (panel["arm"] == arm)
                    & (np.abs(panel["displacement"]) >= edges[j])
                    & (np.abs(panel["displacement"]) < edges[j + 1]))
            hi = band & np.isin(panel["bucket"], ("k2", "k3"))
            lo = band & (panel["bucket"] == "k1")
            nhi = int(np.isfinite(panel["hold"][hi]).sum())
            nlo = int(np.isfinite(panel["hold"][lo]).sum())
            if nhi < 100 or nlo < 100:
                continue
            a = float(np.nanmean(panel["hold"][lo]))
            c = float(np.nanmean(panel["hold"][hi]))
            gaps.append(c - a)
            print(f"{arm:<9} [{edges[j]:.3f}, {edges[j + 1]:.3f})      "
                  f"{a:.4f}    {c:.4f}   {c - a:+.4f}   ({nlo}/{nhi})")
            cells.append({"scope": "displacement", "arm": arm,
                          "bucket": f"[{edges[j]:.3f},{edges[j + 1]:.3f})",
                          "n": nhi, "hold": c, "alone": a, "se": float("nan")})
        if gaps:
            print(f"{arm:<9} equal-weight gap within deciles: {np.mean(gaps):+.4f}")
            cells.append({"scope": "displacement", "arm": arm, "bucket": "within",
                          "n": len(gaps), "hold": float(np.mean(gaps))})

    if "width" in panel:
        print("\narm       quintile of bar range / lagged unit   k=1       k>=2      gap")
        wedges = np.nanquantile(panel["width"][traded], np.linspace(0, 1, 6))
        for arm in ("real", "walkpath"):
            gaps = []
            for j in range(len(wedges) - 1):
                band = (traded & (panel["arm"] == arm)
                        & (panel["width"] >= wedges[j]) & (panel["width"] < wedges[j + 1]))
                hi = band & np.isin(panel["bucket"], ("k2", "k3"))
                lo = band & (panel["bucket"] == "k1")
                nhi = int(np.isfinite(panel["hold"][hi]).sum())
                nlo = int(np.isfinite(panel["hold"][lo]).sum())
                if nhi < 100 or nlo < 100:
                    continue
                a = float(np.nanmean(panel["hold"][lo]))
                c = float(np.nanmean(panel["hold"][hi]))
                gaps.append(c - a)
                print(f"{arm:<9} [{wedges[j]:.3f}, {wedges[j + 1]:.3f})      "
                      f"{a:.4f}    {c:.4f}   {c - a:+.4f}   ({nlo}/{nhi})")
                cells.append({"scope": "width", "arm": arm,
                              "bucket": f"[{wedges[j]:.3f},{wedges[j + 1]:.3f})",
                              "n": nhi, "hold": c, "alone": a})
            if gaps:
                print(f"{arm:<9} equal-weight gap within quintiles: {np.mean(gaps):+.4f}")
                cells.append({"scope": "width", "arm": arm, "bucket": "within",
                              "n": len(gaps), "hold": float(np.mean(gaps))})
        for arm in ("real", "walkpath"):
            w = panel["width"][traded & (panel["arm"] == arm)]
            k = panel["k"][traded & (panel["arm"] == arm)]
            print(f"{arm:<9} mean bar width at k=1 {np.nanmean(w[k == 1.0]):.3f}, "
                  f"at k>=2 {np.nanmean(w[k >= 2.0]):.3f}")

    print("\n=== by family, k>=2 hold rate (a regime split is information) ===")
    for family in sorted(set(fam.tolist())):
        sel = (fam == family) & (panel["arm"] == "real") & np.isin(panel["bucket"],
                                                                  ("k2", "k3"))
        n = int(np.isfinite(panel["hold"][sel]).sum())
        if n < 100:
            continue
        mean, se, _lo, _hi = block_ci(panel["hold"][sel], panel["day"][sel], draws=400)
        print(f"  {family:<8} {mean:.4f} +- {se:.4f} on {n}")
        cells.append({"scope": "family", "arm": "real", "bucket": family, "n": n,
                      "hold": mean, "se": se})

    write_csv(OUT / "cells.csv", cells)


# ─────────────────────────────────── the smoke run ───────────────────────────────────


def smoke() -> None:
    """Seconds, on generated bars. Proves the chain is exercised, which is the
    rule a count of zero beside a non-zero statistic exists for."""
    rng = random.Random(7)
    n = 20_000
    gen = np.random.default_rng(11)
    steps = gen.normal(0.0, 1.0, size=n - 1)
    ts = np.arange(n, dtype=np.int64) * 3600
    bars = bridge_path(steps, ts, 1000.0, rng)
    assert np.allclose(bars["open"][1:], bars["close"][:-1]), "the bridge must be continuous"
    unit, strata, book, named, rows = prepare(bars)
    print("levels per framework:", {f: len(rows.get(f, [])) for f in FRAMEWORKS})
    print("named first touches:", len(named), " k histogram:",
          {k: sum(1 for r in named if r[2] == k) for k in (1, 2, 3, 4)})
    got = observe(bars, unit, strata, named, rng=rng)
    print("observations by bucket:", {b: len(v) for b, v in got.items()})
    flat = [r for b in ("k1", "k2", "k3") for r in got[b]]
    hold = np.array([r["hold"] for r in flat])
    print(f"hold rate on a bridge walk: {np.nanmean(hold):.4f} on "
          f"{int(np.isfinite(hold).sum())} (a martingale owes 0.5)")
    flat.sort(key=lambda r: r["bar"])
    extra, why = placebo_of(bars, unit, strata, book, flat, rng)
    ph = np.array([r["hold"] for r in extra]) if extra else np.zeros(0)
    print(f"placebo: {len(extra)} drawn of {len(flat)} wanted, hold "
          f"{np.nanmean(ph) if len(ph) else float('nan'):.4f}, rejections {why}")
    told = describe("SMOKE", "1h", bars, unit, book, rows, named, 0)
    print("agreement:", {k: round(v, 4) for k, v in told.items() if k.startswith("agree")})
    print("fires:", {k: round(v, 3) for k, v in told.items() if k.startswith("fires")})
    print("density:", {k: round(v, 3) for k, v in told.items() if k.startswith("density")})
    print("shape:", {k: round(v, 4) for k, v in
                     shape_stats(np.array([r["shape"] for r in flat]), silv=False).items()})


MODES = {
    "smoke": smoke,
    "overlap": mode_overlap,
    "run": mode_run,
    "power": mode_power,
    "cost": mode_cost,
    "calibrate": mode_calibrate,
    "sweep": mode_sweep,
    "lifesweep": mode_lifesweep,
    "report": report,
}

if __name__ == "__main__":
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, "1")
    OUT.mkdir(parents=True, exist_ok=True)
    MODES[MODE]()
