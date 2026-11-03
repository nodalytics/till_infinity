"""Planted effects and their strength sweeps: where each test in this study goes blind.

`show-power-before-reporting-a-null` is not optional here, because three of the
four questions are expected to come back null and a null without a power
statement is a sentence rather than a measurement.

Four plants, one per claim.

## `plant_skew` - negative return skewness

The mechanism that *would* produce "down faster and deeper" without any time
structure at all. Swept so the write-up can say how much skewness the swing
statistic sees, and - more usefully - that **`bar-shuffle` sees exactly the
same amount**, which is what makes the shuffle the deciding arm rather than a
formality.

## `plant_up_share` - the marginal version, and what the statistic does see

More up bars than down bars, same magnitudes. Longer up runs and shorter down
runs follow mechanically, which is most of "up longer, down shorter" - and it
is a property of the marginal, so a shuffle sees it in full. Carried so the
verdict can name one sweep the statistic tracks and one it cannot see.

## `plant_sign_clustering` - the path version, and **it failed its own control**

Built to be the pure **order** effect: the series' exact multiset of signed
returns, every return used once so the mean, variance, skewness and kurtosis
are unchanged to the last digit, reordered by a two-state Markov chain of
persistence `p`. `p` 0.5 is i.i.d. and should plant nothing.

**It does not read nothing at `p` 0.5.** Measured on audjpy at `reach` 10 with
its matched `log_shuffle` twin, the duration-gap excess is **-0.180 +- 0.038
(z -4.76) where no effect is planted**, and the sweep above it is flat
(-0.179, -0.261, -0.178, -0.160) with no dose response. The cause is the
construction: drawing signs from a 50/50 chain while consuming from fixed up
and down pools is not a permutation of the real sign sequence, and
`log_shuffle` of the same returns reads +0.200 where this plant reads +0.020.

So **the arm is rejected and nothing is inferred from its sweep.**
`finding-edges` is the rule - a control that *must* come back empty catches
what a control that should merely come back smaller does not - and the
consequence is recorded in `research/docs/fear-greed.md`: a bar shuffle
reproducing the asymmetry is established, and "there is therefore nothing in
the order" is **not**, because this study could not build a calibrated test for
it. The function is kept so the failure is reproducible rather than described.

## `plant_label_hold` - **rejected: the plant destroys what it plants**

A walk with its own causal book: every step that would carry price across a
**crash-labelled** level is reflected about it with probability `strength`,
spike-labelled levels left alone. 0 is a plain walk, 1 is hard walls at the
fear levels only.

**Measured on audusd / `pivots` at 2 draws a strength, it fails both ways.**
The zero cell recovers a gap of **+0.0971** where it must recover 0, and a book
of hard walls at every crash level recovers **-0.0008** - no dose response at
any strength.

The cause is structural rather than noise. Reflecting price about
crash-labelled levels **changes the path**, and the measurement then recomputes
the book *and the shape labels* on the planted series, where different bars are
crash bars and different prices are levels. So the association being planted is
destroyed by the act of planting. `level_shield.py`'s barrier plant does not
hit this because it reflects at every level in the book and has no label to
reassign; a label-conditional plant has no such escape.

Kept so the failure is reproducible rather than described. A working arm needs
the label to hang off something the reflection cannot move, or the path and the
labels generated jointly.

## `plant_trade_edge` - a conditional drift inside the fear state

On a walk, the `H` bars after the gate fires are given a downward drift of
`k` volatility units. This is the coordinator's correction made testable:
direction conditioned on a volatility state is an open question, so the trade
arm needs to say what size of conditional drift it would have found. Swept in
units of the stop, so the answer is directly in R.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable

import numpy as np

import research.ideas.fear_greed as F
import research.ideas.fear_greed_asym as A
import research.ideas.fear_greed_trade as T

#: Skewness strengths swept by `plant_skew`, as the share of steps whose
#: magnitude is redistributed from the up side to the down side.
SKEWS: tuple[float, ...] = (0.0, 0.05, 0.10, 0.20, 0.35)

#: Sign persistence swept by `plant_sign_clustering`. 0.5 is i.i.d.
PERSISTENCE: tuple[float, ...] = (0.50, 0.55, 0.60, 0.70, 0.80)

#: Excess up-bar share swept by `plant_up_share`. 0.0 is a fair walk, 0.10 is
#: 60% of bars up - well beyond anything in this store, where the up share
#: runs 49-51%.
UP_SHARES: tuple[float, ...] = (0.0, 0.02, 0.05, 0.10)

#: Reflection strengths swept by `plant_label_hold`.
STRENGTHS: tuple[float, ...] = (0.0, 0.10, 0.25, 0.50, 0.75, 1.00)

#: Conditional drifts swept by `plant_trade_edge`, in volatility units **per
#: horizon**, so 0.5 means the gated window drifts half a stop's distance.
DRIFTS: tuple[float, ...] = (0.0, 0.10, 0.25, 0.50, 1.00)


def plant_skew(series: F.Series, k: float, rng: random.Random) -> F.Series:
    """A walk with this series' volatility and a planted negative skewness.

    Built from i.i.d. draws of the real step magnitudes, with the sign drawn so
    that a share `k` more of the *large* magnitudes land on the down side. The
    variance is held by rescaling, so what is swept is skewness and not size -
    `refit-the-parameter-a-lever-multiplies`, a multiplier whose mean is not 1
    changes the average too and reversed a +1192 result to -24 on this desk.
    """
    steps = np.abs(np.diff(series.close))
    n = len(series.close)
    draw = np.asarray([steps[rng.randrange(len(steps))] for _ in range(n - 1)])
    big = draw >= np.quantile(draw, 1.0 - max(k, 1e-9))
    sign = np.where(
        np.asarray([rng.random() for _ in range(n - 1)]) < 0.5, 1.0, -1.0
    )
    # Large steps are forced negative with probability k, which both skews and
    # shifts the mean; the shift is removed so the sweep is of skewness alone.
    forced = big & (np.asarray([rng.random() for _ in range(n - 1)]) < k)
    sign = np.where(forced, -1.0, sign)
    moved = draw * sign
    moved = moved - moved.mean()
    scale = float(np.std(np.diff(series.close))) / max(float(np.std(moved)), 1e-300)
    close = np.empty(n)
    close[0] = float(series.close[0])
    close[1:] = close[0] + np.cumsum(moved * scale)
    pick = np.asarray([rng.randrange(n) for _ in range(n)])
    return F._shaped(series, close, pick)


def plant_sign_clustering(series: F.Series, p: float, rng: random.Random) -> F.Series:
    """The series' exact signed returns, reordered so signs persist with prob `p`.

    **Marginal-preserving by construction.** Every real log return is used once,
    so the mean, variance, skewness and kurtosis are identical to the original
    to the last digit and only the order changes. At `p` 0.5 this is an i.i.d.
    permutation; above it, negatives cluster.

    Where a pool runs out the other sign is taken, so the tail of the series
    is a single run - which is why the statistic is read over the whole series
    and the exhausted tail is a known and bounded distortion rather than a
    silent one. With the up and down counts within a few percent of each other
    on every feed here, the exhausted stretch is under 2% of bars at `p` 0.80.
    """
    rets = np.diff(np.log(np.maximum(series.close, 1e-12)))
    ups = [r for r in rets if r > 0.0]
    downs = [r for r in rets if r <= 0.0]
    rng.shuffle(ups)
    rng.shuffle(downs)
    order: list[float] = []
    want_up = rng.random() < 0.5
    for _ in range(len(rets)):
        pool = ups if want_up else downs
        other = downs if want_up else ups
        if not pool:
            pool, other = other, pool
            want_up = not want_up
        if not pool:
            break
        order.append(pool.pop())
        if rng.random() >= p:
            want_up = not want_up
    moved = np.asarray(order)
    close = np.empty(len(moved) + 1)
    close[0] = float(series.close[0])
    close[1:] = close[0] * np.exp(np.cumsum(moved))
    pick = np.asarray([rng.randrange(len(series.close)) for _ in range(len(close))])
    trimmed = F.Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts[: len(close)],
        open=series.open[: len(close)],
        high=series.high[: len(close)],
        low=series.low[: len(close)],
        close=series.close[: len(close)],
        synthetic=series.synthetic,
        kind=series.kind,
    )
    return F._shaped(trimmed, close, pick % len(close))


def plant_up_share(series: F.Series, k: float, rng: random.Random) -> F.Series:
    """An i.i.d. walk whose step is up with probability `0.5 + k`.

    The plant that shows what the swing statistic **is** sensitive to, and it
    is the complement of `plant_sign_clustering`. More up bars than down bars
    with the same magnitudes gives longer up runs and shorter down runs
    mechanically, which is most of "up longer, down shorter" - and it is a
    property of the **marginal**, so a bar shuffle sees it in full.

    Carrying both plants is what makes the asymmetry verdict interpretable:
    one strength sweep the statistic tracks, one it cannot see at any
    strength.
    """
    steps = np.abs(np.diff(series.close))
    n = len(series.close)
    draw = np.asarray([steps[rng.randrange(len(steps))] for _ in range(n - 1)])
    sign = np.asarray(
        [1.0 if rng.random() < 0.5 + k else -1.0 for _ in range(n - 1)]
    )
    moved = draw * sign
    close = np.empty(n)
    close[0] = float(series.close[0])
    close[1:] = close[0] + np.cumsum(moved)
    pick = np.asarray([rng.randrange(n) for _ in range(n)])
    return F._shaped(series, close, pick)


#: Each plant, its strength grid, and **the shuffle arm matched to how it
#: builds its path**.
#:
#: The twin has to be matched or the paired excess is contaminated by the
#: arithmetic-against-log confound `fear_greed.log_shuffle` documents.
#: `plant_skew` and `plant_up_share` accumulate *absolute* steps, so
#: `bar_shuffle` is their twin; `plant_sign_clustering` accumulates *log*
#: returns, so `log_shuffle` is. The first version used `bar_shuffle` for all
#: three, and at persistence 0.5 - where the plant is an i.i.d. log
#: permutation and its twin should agree with it exactly - the two read
#: **+0.020 against +0.188** on audjpy's duration gap. That gap was the
#: mismatch, not the planted effect.
PLANTS: dict[str, tuple[tuple[float, ...], Callable, Callable]] = {
    "skew": (SKEWS, plant_skew, F.bar_shuffle),
    "up_share": (UP_SHARES, plant_up_share, F.bar_shuffle),
    "sign_clustering": (PERSISTENCE, plant_sign_clustering, F.log_shuffle),
}


def sweep_asymmetry(
    series: F.Series,
    *,
    unit_span: int,
    reach: int,
    draws: int,
    rng: random.Random,
) -> dict:
    """The three asymmetry plants, swept, each with its own bar-shuffle arm.

    The shuffle is run **inside** every cell rather than once, because the
    whole point is the excess. `plant_skew` and `plant_up_share` should move
    the real reading **and its shuffle together** - they are marginal effects.
    `plant_sign_clustering` holds the marginal exactly and changes only the
    order, so an excess there would be the statistic seeing path structure.

    A sweep without the per-cell shuffle cannot show that difference, and the
    difference is the result: it is what separates "there is no path effect"
    from "this statistic cannot see one".
    """
    out: dict = {}
    for name, (grid, make, twin_of) in PLANTS.items():
        out[name] = [
            _cell(series, strength, (make, twin_of), unit_span, reach, draws, rng)
            for strength in grid
        ]
    return out


def _cell(
    series: F.Series,
    strength: float,
    plant,
    unit_span: int,
    reach: int,
    draws: int,
    rng,
) -> dict:
    """One strength, averaged over `draws` independent plants.

    **Averaged, not one plant per strength.** The first version planted once
    per strength and the sweep came back non-monotone with the zero-strength
    cell reading speed -0.216 on audjpy, because one plant's own sampling noise
    on a 270-swing series is about the size of the effect being swept. A dose
    response measured at one draw per dose is not a dose response, and it is
    the same mistake as reading a single cell off a grid.

    Each plant carries its **own** bar-shuffle twin, so the excess is a paired
    difference within one realisation and the plant-to-plant variation cancels
    out of it.
    """
    names = ("bars", "size", "speed")
    real: dict[str, list[float]] = {n: [] for n in names}
    twin: dict[str, list[float]] = {n: [] for n in names}
    excess: dict[str, list[float]] = {n: [] for n in names}
    swings: list[int] = []
    make, twin_of = plant
    for _ in range(max(2, draws)):
        built = make(series, strength, rng)
        unit = F.unit_for(built, unit_span)
        here = A.asymmetry(A.swings(built, unit, on_closes=True, reach=reach))
        shuffled = twin_of(built, random.Random(rng.randrange(1 << 30)))
        there = A.asymmetry(
            A.swings(shuffled, F.unit_for(shuffled, unit_span), on_closes=True, reach=reach)
        )
        swings.append(int(here["n_up"] + here["n_down"]))
        for name in names:
            if np.isfinite(here[name]):
                real[name].append(here[name])
            if np.isfinite(there[name]):
                twin[name].append(there[name])
            if np.isfinite(here[name]) and np.isfinite(there[name]):
                excess[name].append(here[name] - there[name])
    row: dict = {
        "strength": strength,
        "swings": int(np.mean(swings)) if swings else 0,
        "plants": len(excess["speed"]),
    }
    for name in names:
        row[name] = float(np.mean(real[name])) if real[name] else float("nan")
        row[f"{name}_shuffle"] = float(np.mean(twin[name])) if twin[name] else float("nan")
        got = excess[name]
        row[f"{name}_excess"] = float(np.mean(got)) if got else float("nan")
        # The standard error of the **paired** excess across plants, which is
        # what the dose response has to be read against.
        sd = float(np.std(got, ddof=1)) / math.sqrt(len(got)) if len(got) > 2 else float("nan")
        row[f"{name}_excess_se"] = sd
        row[f"{name}_z"] = (
            row[f"{name}_excess"] / sd if sd and np.isfinite(sd) and sd > 0 else float("nan")
        )
    return row


def plant_trade_edge(
    series: F.Series,
    basket: F.Basket,
    drift: float,
    *,
    unit_span: int,
    horizon: int,
    quantile: float,
    rng: random.Random,
) -> F.Series:
    """A walk whose gated windows drift down by `drift` units over `horizon` bars.

    The planted conditional edge. The gate is computed on the **real** basket
    index, so the planted effect sits exactly where the test will look for one,
    and the price path is a surrogate so nothing else about it is real.

    `drift` is in volatility units per horizon, so at a stop of 1.0 unit a
    drift of 0.25 is a quarter of a stop over the hold - which is the size a
    mean R of about +0.25 on the short arm would correspond to.
    """
    walk = F.walk_geometry(series, rng)
    unit = F.unit_for(walk, unit_span)
    fires = T.gate(basket.volatile_off, quantile)
    n = len(walk.close)
    push = np.zeros(n)
    per_bar = drift / max(1, horizon)
    for i in np.flatnonzero(fires):
        stop = min(n, i + horizon + 1)
        push[i + 1 : stop] -= per_bar * unit[i]
    close = walk.close + np.cumsum(push)
    offset = close - walk.close
    return F.Series(
        feed=walk.feed,
        venue=walk.venue,
        interval=walk.interval,
        ts=walk.ts,
        open=walk.open + offset,
        high=walk.high + offset,
        low=walk.low + offset,
        close=close,
        synthetic=series.synthetic,
        kind=series.kind,
    )


def sweep_trade(
    series: F.Series,
    basket: F.Basket,
    *,
    unit_span: int,
    horizon: int,
    quantile: float,
    target: float,
    stop: float,
    draws: int,
    rng: random.Random,
) -> list[dict]:
    """`plant_trade_edge` swept, scored by the study's own trade arm.

    Reported in R, which is the unit the verdict is in, so the sweep answers
    the question a reader asks of a null trade result: *how big an edge would
    this have found?*
    """
    out: list[dict] = []
    for drift in DRIFTS:
        got: list[float] = []
        for _ in range(max(1, draws)):
            built = plant_trade_edge(
                series,
                basket,
                drift,
                unit_span=unit_span,
                horizon=horizon,
                quantile=quantile,
                rng=rng,
            )
            unit = F.unit_for(built, unit_span)
            fires = T.gate(basket.volatile_off, quantile)
            raced = T.races(
                built, unit, fires, side=-1, target=target, stop=stop, horizon=horizon
            )
            if len(raced["r"]) >= 8:
                got.append(float(raced["r"].mean()))
        out.append(
            {
                "drift": drift,
                "mean_r": float(np.mean(got)) if got else float("nan"),
                "sd": float(np.std(got, ddof=1)) if len(got) > 2 else float("nan"),
                "draws": len(got),
            }
        )
    return out


def plant_label_hold(
    series: F.Series,
    strength: float,
    *,
    unit_span: int,
    book: str,
    rng: random.Random,
) -> F.Series:
    """A walk whose **crash-labelled** levels reflect price with prob `strength`.

    The planted level effect. A plain `walk-geometry` surrogate is built, its
    own causal book and shape labels are read off it, and then every step that
    would carry price across a crash-labelled level is reflected about that
    level with probability `strength`. Spike-labelled and unlabelled levels are
    left alone, so what is planted is the **label gap** and not a general
    barrier - a plant that made every level hold would measure
    `level-shield.md`'s question over again rather than this one.

    `strength` 0 is a plain walk and has to read nothing. That is the arm that
    must come back empty, which `finding-edges` says catches what a control
    that should merely come back smaller does not.
    """
    import research.ideas.fear_greed_levels as L

    walk = F.walk_geometry(series, rng)
    unit = F.unit_for(walk, unit_span)
    labels = F.shape_labels(walk)
    found = L.formations(walk, book, unit, unit_span=unit_span)
    fear = {
        float(p): int(a)
        for p, a in zip(found["price"], found["at"], strict=True)
        if labels[int(a)] == F.CRASH
    }
    if not fear or strength <= 0.0:
        return walk
    close = walk.close.copy()
    shift = 0.0
    for i in range(1, len(close)):
        here = close[i] + shift
        before = close[i - 1] + shift
        for price, born in fear.items():
            if born >= i:
                continue
            if (here - price) * (before - price) < 0.0 and rng.random() < strength:
                shift += 2.0 * (price - here)
                here = close[i] + shift
        close[i] += shift
    offset = close - walk.close
    return F.Series(
        feed=walk.feed,
        venue=walk.venue,
        interval=walk.interval,
        ts=walk.ts,
        open=walk.open + offset,
        high=walk.high + offset,
        low=walk.low + offset,
        close=close,
        synthetic=walk.synthetic,
        kind=walk.kind,
    )


def sweep_levels(
    series: F.Series,
    basket: F.Basket,
    *,
    unit_span: int,
    horizon: int,
    book: str,
    draws: int,
    rng: random.Random,
) -> list[dict]:
    """`plant_label_hold` swept, scored by the study's own level arm.

    Reports the recovered fear-minus-greed hold gap and the class counts, so
    the write-up can say both the gap size the test sees and the sample it saw
    it on - a `Levels` book publishes about 300 levels over 4,980 days and the
    crash class is 3-5% of bars, so the sample is the binding constraint and
    has to be in the table.
    """
    import research.ideas.fear_greed_levels as L

    out: list[dict] = []
    for strength in STRENGTHS:
        gaps: list[float] = []
        counts: list[int] = []
        for _ in range(max(1, draws)):
            built = plant_label_hold(
                series, strength, unit_span=unit_span, book=book, rng=rng
            )
            got = L.one_series(
                built, basket, book=book, unit_span=unit_span, horizon=horizon
            )
            gap = got.get("gaps", {}).get("fear_minus_greed_pooled", float("nan"))
            if np.isfinite(gap):
                gaps.append(float(gap))
                counts.append(int(got["hold"]["crash"]["n"]))
        out.append(
            {
                "strength": strength,
                "book": book,
                "gap": float(np.mean(gaps)) if gaps else float("nan"),
                "sd": float(np.std(gaps, ddof=1)) if len(gaps) > 2 else float("nan"),
                "crash_n": float(np.mean(counts)) if counts else float("nan"),
                "draws": len(gaps),
            }
        )
    return out
