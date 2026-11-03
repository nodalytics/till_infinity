"""Are up moves longer and slower, and down moves faster and deeper?

The asymmetry the risk-on / risk-off framing rests on, and the one with the
best prior: Brunnermeier, Nagel and Pedersen, *Carry Trades and Currency
Crashes* (2008) describe a carry trade that builds slowly and unwinds fast.
This measures it on the synthetic JPY and CHF crosses over 19.25 years, splits
it by era so a pattern that is only 2008 cannot pass as a pattern, and nulls it
on the same swing detector.

## The statistic, and why it is on closes

A swing is the stretch between two consecutive confirmed pivots of opposite
side, from `indicators.trend.pivots` at `reach` 3. Per swing: its length in
bars, its size in volatility units, and its **speed**, size over bars. The
claim is three comparisons of up swings against down swings - longer, smaller,
slower - and all three are reported, because "faster and deeper" is two claims
and a statistic that merges them cannot say which failed.

**On closes, not on highs and lows.** `trend.pivots` takes `(high, low, when)`
and the honest input for a synthetic cross is `(close, close, when)`: the
cross's close path is exact and its extremes are bounds inflated about 1.7x on
the JPY pairs (`fear_greed`'s module docstring). A close-pivot swing is a
slightly different object from a wick-pivot swing - it cannot see an intrabar
spike - so the real legs are run **both ways** and the difference is reported,
which is the only way to know what the close-only restriction costs.

The size unit is `fear_greed.unit_for`: the EWMA bar range on a real leg, the
EWMA close step scaled to it on a cross. Scale-free, so a 19-year series whose
level trebles does not report its later swings as larger.

## What a result has to survive, fixed before the run

**The direction is pre-stated and it is one-sided.** Up longer, up smaller, up
slower; equivalently down shorter, down deeper, down faster. A reversed sign on
any of the three is not a weaker version of the claim.

**`bar-shuffle` is the arm that decides**, and
`let-the-shuffled-twin-name-the-mechanical-observables` says why. A shuffle
keeps the marginal return distribution **exactly**, so it keeps the skewness,
and it destroys every bit of path order. If "down faster and deeper" is a fact
about the distribution of one day's return rather than about the sequence of
days, the shuffle reproduces it in full - and then the finding is return
skewness, which is already known and is not what the carry-crash story claims.
The claim is about *paths*: a slow build and a fast unwind is a statement about
order.

**`garch-bars` is Gaussian**, so it has clustering and no skewness. Between the
two arms the asymmetry is attributable: shuffle-only means skewness,
garch-only means clustering, neither means path order, both means it is
over-determined and the study cannot separate them.

**`drift-free` and `sign-flip` are diagnostics, not nulls.** 19 years of AUDJPY
is not drift-free and a trending series has longer up swings for an arithmetic
reason; `drift-free` removes the mean log return and asks whether the asymmetry
survives it. `sign-flip` negates every log return and mirrors every bar: an
asymmetry that is a property of direction must come back with its sign reversed
and its magnitude unchanged, and one that does not has a bug in the statistic
rather than a finding behind it.

**Eras.** Six calendar blocks (`fear_greed.ERAS`) plus a drop of
2008-01-01 to 2009-06-30. A pattern present in one era is one episode.
"""

from __future__ import annotations

import numpy as np

import research.ideas.fear_greed as F
from till_infinity.indicators.trend import REACH, pivots

#: The two swing scales, both fixed before the run and both reported. **Two
#: named rules, not a sweep.**
#:
#: `REACH` 3 is the repo's own (`trend.REACH`) and gives a median swing of 4
#: bars. `SWING_SLOW` 10 is the scale the carry-crash claim is about: the 2008
#: AUDJPY unwind ran 60 bars peak to trough, which a reach-3 detector chops
#: into roughly fifteen swings, so a reach-3 reading cannot see a multi-week
#: build against a multi-week collapse at all. Reporting only the repo's
#: default would have tested the claim at the wrong scale and called it a null.
SWING_REACH = REACH
SWING_SLOW = 10
SWING_REACHES: tuple[int, ...] = (SWING_REACH, SWING_SLOW)

#: The fewest swings a cell needs before its medians are reported. Below this
#: a median of a heavy-tailed quantity is noise, and the skill's "under ~100
#: the prior is noise" applies - so the number is carried with every row and a
#: thin cell is printed as thin rather than dropped, since dropping it is the
#: `pool-events-before-a-per-feed-guard` failure that made 0.9 sigma look
#: like 4.8.
FEWEST_SWINGS = 40


def swings(
    series: F.Series, unit: np.ndarray, *, on_closes: bool, reach: int = SWING_REACH
) -> dict[str, np.ndarray]:
    """Every confirmed swing, as flat arrays.

    `on_closes` feeds `(close, close, when)` to the detector instead of
    `(high, low, when)`. Required on a synthetic cross, where the extremes are
    bounds, and run on the real legs too so the cost of the restriction is a
    measured number rather than an assumption.

    A swing's `size` is divided by the unit **at its start**, not at its end: a
    swing that runs into an expanding-volatility regime would otherwise be
    deflated by the volatility it caused, which is the leverage effect read
    backwards.
    """
    if on_closes:
        window = list(zip(series.close, series.close, series.ts, strict=True))
    else:
        window = list(zip(series.high, series.low, series.ts, strict=True))
    found = pivots(window, reach)
    if len(found) < 2:
        empty = np.empty(0)
        return {k: empty for k in ("side", "bars", "size", "speed", "start", "end")}
    stamp = {float(t): i for i, t in enumerate(series.ts)}
    rows: list[tuple[int, int, float, float, int, int]] = []
    for before, after in zip(found, found[1:], strict=False):
        if before.side == after.side:
            # `pivots` can emit two highs in a row where no low confirmed
            # between them. A high-to-high pair is not a swing, so it is
            # skipped rather than measured as one of length zero.
            continue
        i = stamp.get(float(before.when))
        j = stamp.get(float(after.when))
        if i is None or j is None or j <= i:
            continue
        scale = float(unit[i])
        if not np.isfinite(scale) or scale <= 0.0:
            continue
        move = float(series.close[j] - series.close[i])
        # +1 for a swing that went up: from a pivot low (side -1) to a high.
        side = 1 if before.side < 0 else -1
        bars = j - i
        size = abs(move) / scale
        rows.append((side, bars, size, size / bars, i, j))
    if not rows:
        empty = np.empty(0)
        return {k: empty for k in ("side", "bars", "size", "speed", "start", "end")}
    arr = np.asarray(rows, dtype=float)
    return {
        "side": arr[:, 0].astype(np.int8),
        "bars": arr[:, 1],
        "size": arr[:, 2],
        "speed": arr[:, 3],
        "start": arr[:, 4].astype(np.int64),
        "end": arr[:, 5].astype(np.int64),
    }


def _log_gap(up: np.ndarray, down: np.ndarray) -> float:
    """`mean(log up) - mean(log down)`, or nan without both sides.

    **The mean of logs and not the log of medians**, because a swing's length
    in bars is a small integer: at `reach` 3 the median is 4 bars on 8 of 9
    instruments, so a log-of-medians gap reads exactly 0.000 whatever the
    distributions do, and the day-block standard error on it reads 0.000 too.
    That is the discreteness version of `sweep-thresholds-on-the-mean-not-z` -
    a statistic quantised at the point it is evaluated reports a clean null it
    has no power to refute.

    A log difference rather than a ratio of means, so the three statistics are
    comparable with each other and across instruments whose swings differ in
    size by an order of magnitude. Zero means no asymmetry.
    """
    if len(up) < 2 or len(down) < 2:
        return float("nan")
    a, b = up[up > 0.0], down[down > 0.0]
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    return float(np.log(a).mean() - np.log(b).mean())


def asymmetry(found: dict[str, np.ndarray], keep: np.ndarray | None = None) -> dict:
    """The three log gaps, up against down, over the swings `keep` selects.

    Pre-stated direction: `bars` **positive** (up swings longer), `size`
    **negative** (up swings smaller), `speed` **negative** (up swings slower).
    """
    side = found["side"] if keep is None else found["side"][keep]
    out: dict = {"n_up": int((side > 0).sum()), "n_down": int((side < 0).sum())}
    for name in ("bars", "size", "speed"):
        values = found[name] if keep is None else found[name][keep]
        out[name] = _log_gap(values[side > 0], values[side < 0])
        out[f"{name}_up"] = float(np.median(values[side > 0])) if (side > 0).any() else float("nan")
        out[f"{name}_down"] = (
            float(np.median(values[side < 0])) if (side < 0).any() else float("nan")
        )
    return out


def day_blocks(found: dict[str, np.ndarray], day: np.ndarray, draws: int, rng) -> dict:
    """A day-block bootstrap standard error for each of the three log gaps.

    Whole days resampled with replacement, because swings cluster: a 19-year
    series holds about 500 swings and two that start in the same week share
    their regime, so an ordinary standard error over swings is far too narrow.
    The skill names this as the control that caught a wrong answer here.
    """
    starts = found["start"]
    if len(starts) == 0:
        return {name: float("nan") for name in ("bars", "size", "speed")}
    blocks = day[starts]
    unique = np.unique(blocks)
    if len(unique) < 4:
        return {name: float("nan") for name in ("bars", "size", "speed")}
    index: dict[int, np.ndarray] = {b: np.flatnonzero(blocks == b) for b in unique}
    draws_out: dict[str, list[float]] = {"bars": [], "size": [], "speed": []}
    for _ in range(draws):
        picked = np.concatenate(
            [index[unique[rng.randrange(len(unique))]] for _ in range(len(unique))]
        )
        got = asymmetry(found, picked)
        for name in draws_out:
            if np.isfinite(got[name]):
                draws_out[name].append(got[name])
    return {
        name: float(np.std(values, ddof=1)) if len(values) > 2 else float("nan")
        for name, values in draws_out.items()
    }


def one_series(
    series: F.Series,
    *,
    unit_span: int,
    on_closes: bool,
    draws: int,
    rng,
    reach: int = SWING_REACH,
) -> dict:
    """The whole asymmetry table for one series and one arm: pooled, and per era."""
    unit = F.unit_for(series, unit_span)
    found = swings(series, unit, on_closes=on_closes, reach=reach)
    day = F.days(series.ts)
    era = F.era_of(series.ts)
    out: dict = {
        "feed": series.feed,
        "kind": series.kind,
        "synthetic": series.synthetic,
        "on_closes": on_closes,
        "reach": reach,
        "swings": int(len(found["side"])),
        "pooled": asymmetry(found),
        "se": day_blocks(found, day, draws, rng),
        "eras": {},
    }
    if len(found["side"]):
        starts = found["start"]
        for i, (label, _, _) in enumerate(F.ERAS):
            keep = era[starts] == i
            if keep.sum() >= 4:
                out["eras"][label] = asymmetry(found, keep)
        drop = F.window_mask(series.ts, F.CRASH_DROP_FROM, F.CRASH_DROP_TO)
        out["crash_dropped"] = asymmetry(found, ~drop[starts])
        out["crash_only"] = asymmetry(found, drop[starts])
    return out


def conditioned(
    series: F.Series,
    basket: F.Basket,
    *,
    unit_span: int,
    on_closes: bool,
    reach: int = SWING_REACH,
) -> dict:
    """Does the risk-off reading at a swing's start predict the swing's shape?

    The link between the index and the asymmetry, and the place the coordinator's
    correction bites: the framing's claim is not "JPY crosses fall" but "JPY
    crosses fall **fast when fear is rising**", which is a direction reading
    conditioned on a volatility state and not the standalone direction gate that
    `direction-is-closed-not-just-null` measured closed.

    So three conditioning variables are reported, never one: `volatile_off`,
    `directional_off`, and the **interaction** - `directional_off` within
    terciles of `volatile_off`. Reported as the mean swing speed and the mean
    down-share in the top and bottom tercile of each, so a reader can see the
    size of the conditioning rather than only its significance.
    """
    unit = F.unit_for(series, unit_span)
    found = swings(series, unit, on_closes=on_closes, reach=reach)
    out: dict = {
        "feed": series.feed,
        "reach": reach,
        "swings": int(len(found["side"])),
        "by": {},
    }
    if not len(found["side"]):
        return out
    starts = found["start"]
    for name in ("risk_off", "volatile_off", "directional_off"):
        values = getattr(basket, name)[starts]
        cut = F.strata(values, 3)
        rows: dict[str, dict] = {}
        for band, label in ((0, "low"), (2, "high")):
            keep = cut == band
            if keep.sum() < FEWEST_SWINGS:
                continue
            side = found["side"][keep]
            rows[label] = {
                "n": int(keep.sum()),
                "down_share": float((side < 0).mean()),
                "speed_up": float(np.median(found["speed"][keep][side > 0]))
                if (side > 0).any()
                else float("nan"),
                "speed_down": float(np.median(found["speed"][keep][side < 0]))
                if (side < 0).any()
                else float("nan"),
                **{
                    f"gap_{k}": asymmetry(found, keep)[k] for k in ("bars", "size", "speed")
                },
            }
        out["by"][name] = rows

    # The interaction: `directional_off` terciles **within** each
    # `volatile_off` tercile, which is the conditioning the framing claims and
    # the one a pooled reading of either variable cannot show.
    vol = F.strata(basket.volatile_off[starts], 3)
    inter: dict[str, dict] = {}
    for band in (0, 2):
        here = vol == band
        if here.sum() < 3 * FEWEST_SWINGS:
            continue
        direction = np.full(len(starts), -1, dtype=np.int8)
        direction[here] = F.strata(basket.directional_off[starts][here], 3)
        for sub, label in ((0, "low"), (2, "high")):
            keep = here & (direction == sub)
            if keep.sum() < FEWEST_SWINGS:
                continue
            side = found["side"][keep]
            inter[f"vol_{band}_dir_{label}"] = {
                "n": int(keep.sum()),
                "down_share": float((side < 0).mean()),
                **{f"gap_{k}": asymmetry(found, keep)[k] for k in ("bars", "size", "speed")},
            }
    out["interaction"] = inter
    return out
