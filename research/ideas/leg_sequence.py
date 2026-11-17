"""Turn points as a sequence: does a leg take out the previous one.

The operator, 2026-11-17: *"do turn points, enable other turn points, does leg
penetrate previous turn points before they turn again or reverse"* - and
*"anything that concerns leg(s) analysis, we are in, the data we are using has
to do with legs, so turn points, etc are important to us."*

So four turn-point definitions rather than one, and one question asked of each:
when a leg leaves a turn point, does it clear the **previous opposite turn
point** before reversing, or stop short?

    origin   the supplied pull-origin detector, confirmed - a 15-bar pivot with
             a 1.5 ATR fall into it, then a 3 ATR directional rise that never
             revisits the low. Confirmed about 5-6 candles late, so the turn is
             known at `i + waited`, never at `i`.
    pivot    a plain swing pivot: the lowest low of `--left` before and
             `--right` after. Known at `i + right`.
    zigzag   an ATR zigzag - the running extreme, flipped when price retraces
             `--reversal` ATR from it. Known at the flip.
    fractal  Williams' five-bar fractal. Known at `i + 2`.

**The distance is the whole null.** A leg clears the previous high when the
previous high is near and does not when it is far, and that is geometry before
it is structure - `a-return-rate-is-geometry` measured an 82% return rate
matched by a distance-matched placebo on every asset class, with a walk at
0.825. So nothing here is reported as a rate on its own: every rate is cut by
the **distance to the prior turn point in ATR**, and read beside the same cut on
day-shuffled bars.

What is already settled, and what this is distinct from:
[`turning-points.md`](../docs/turning-points.md) found HH/HL structure is a coin
flip **for the side** and that real trends make the next extreme *less* often
than walks. That is the unconditional version. This conditions on the distance
and asks it of four definitions, which is the cut that study did not make.

Run as:

    uv run python research/ideas/leg_sequence.py --kinds origin,pivot,zigzag,fractal
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from persistence import SYMBOLS, pull_origins, trailing_rank, true_range  # noqa: E402
from reactive_zones import (  # noqa: E402
    CATALOGUE,
    Candles,
    atr,
    fold,
    load,
    load_csv,
    shuffled,
    window,
)


def extremes(bars: Candles, source: str) -> tuple[np.ndarray, np.ndarray]:
    """The upper and lower series a turn point is read off.

    **The desk disagrees with itself here, which is why it is swept.** The
    supplied pull-origin definition says "the candle's **low** is the lowest of
    the 15 candles before it", so it is a wick reading; the operator's Bjorgum
    preset sets `source of pivots = high/low body`, so the production level
    detector is a body reading (`zones.PivotSource.HIGH_LOW_BODY`). They are
    different objects: a wick pivot sits further out, so it is harder to
    penetrate and easier to sweep, and the stop autopsy in
    [`stops-and-entries.md`](../docs/stops-and-entries.md) measured **51.3% of
    stops taken by a wick** with a different outcome on each side (holding
    through a wick kill averages -0.59R against -1.56R through a body kill).

        wick   high and low - the extreme the market printed
        body   max/min of open and close - the extreme it was willing to hold
        close  the close alone, which is the only one with no intrabar path
    """
    if source == "wick":
        return bars.high, bars.low
    if source == "body":
        return np.maximum(bars.open, bars.close), np.minimum(bars.open, bars.close)
    if source == "close":
        return bars.close, bars.close
    raise SystemExit(f"unknown pivot source {source}")


@dataclass(slots=True)
class Turns:
    """Turn points in time order, each with the bar it becomes **known** at.

    `known` is what keeps this honest: every definition here needs bars after
    the turn to confirm it, and a study that places the turn at `at` and then
    measures from `at` has read those bars twice. The leg is measured from
    `known`, so a definition that takes longer to confirm pays for it.
    """

    at: np.ndarray
    known: np.ndarray
    side: np.ndarray
    price: np.ndarray


def _pivots(bars: Candles, left: int, right: int, source: str = "wick") -> Turns:
    """Swing pivots: the lowest low of `left` before and `right` after."""
    n = len(bars)
    tops, bottoms = extremes(bars, source)
    at, known, side, price = [], [], [], []
    for i in range(left, n - right):
        low, high = float(bottoms[i]), float(tops[i])
        if low < bottoms[i - left : i].min() and low <= bottoms[i + 1 : i + 1 + right].min():
            at.append(i), known.append(i + right), side.append(1), price.append(low)
        elif high > tops[i - left : i].max() and high >= tops[i + 1 : i + 1 + right].max():
            at.append(i), known.append(i + right), side.append(-1), price.append(high)
    return Turns(
        at=np.asarray(at, dtype=np.int64),
        known=np.asarray(known, dtype=np.int64),
        side=np.asarray(side, dtype=np.int8),
        price=np.asarray(price, dtype=np.float64),
    )


def _fractals(bars: Candles, source: str = "wick") -> Turns:
    """Williams' five-bar fractal: `right=2` and `left=2`, nothing else."""
    return _pivots(bars, left=2, right=2, source=source)


def _zigzag(bars: Candles, band: np.ndarray, reversal: float, source: str = "wick") -> Turns:
    """An ATR zigzag: the running extreme, flipped on a `reversal` ATR retrace.

    The threshold is in ATR of the bar being tested, so one setting spans gold
    at 1,300 and EURUSD at 1.08 and spans a decade of either - ATR is twice the
    mean close-to-close move in every instrument-frame cell `reactive-zones.md`
    tried, and its level doubles over these years while its shape does not.
    """
    n = len(bars)
    tops, bottoms = extremes(bars, source)
    at, known, side, price = [], [], [], []
    cur, ext_val, ext_idx = 0, float(bars.close[0]), 0
    for i in range(n):
        unit = band[i]
        if not np.isfinite(unit) or unit <= 0:
            continue
        high, low = float(tops[i]), float(bottoms[i])
        if cur >= 0 and high > ext_val:
            ext_val, ext_idx = high, i
        if cur <= 0 and low < ext_val:
            ext_val, ext_idx = low, i
        if cur == 1 and ext_val - low >= reversal * unit:
            at.append(ext_idx), known.append(i), side.append(-1), price.append(ext_val)
            cur, ext_val, ext_idx = -1, low, i
        elif cur == -1 and high - ext_val >= reversal * unit:
            at.append(ext_idx), known.append(i), side.append(1), price.append(ext_val)
            cur, ext_val, ext_idx = 1, high, i
        elif cur == 0:
            if high - ext_val >= reversal * unit:
                cur, ext_val, ext_idx = 1, high, i
            elif ext_val - low >= reversal * unit:
                cur, ext_val, ext_idx = -1, low, i
    return Turns(
        at=np.asarray(at, dtype=np.int64),
        known=np.asarray(known, dtype=np.int64),
        side=np.asarray(side, dtype=np.int8),
        price=np.asarray(price, dtype=np.float64),
    )


def _origins(bars: Candles, band: np.ndarray, args: argparse.Namespace) -> Turns:
    """The supplied detector's confirmed origins, placed at their low.

    `known` is the bar the 3 ATR rise completed on, which is the supplied
    definition's own "confirmed about 5-6 candles after the low".
    """
    found = pull_origins(
        bars,
        band,
        left=args.left,
        approach=args.approach,
        reach=args.reach,
        ahead=args.ahead,
        behind=args.behind,
        share=args.share,
        displacement=args.displacement,
        pad=args.pad,
    )
    picked = np.flatnonzero((found.label > 0.5) & np.isfinite(found.waited))
    # The detector's side is the side of the **turn**: a bullish origin is a
    # low, so the leg leaving it is up. `_pivots` uses the same convention.
    return Turns(
        at=picked,
        known=picked + found.waited[picked].astype(np.int64),
        side=found.side[picked],
        price=np.where(found.side[picked] == 1, bars.low[picked], bars.high[picked]),
    )


def turns_of(bars: Candles, band: np.ndarray, kind: str, args: argparse.Namespace) -> Turns:
    if kind == "origin":
        # The supplied definition is explicit about the candle's low, so the
        # origin is always read off the wick whatever `--source` says, and the
        # sweep applies to the leg and the barrier instead.
        return _origins(bars, band, args)
    if kind == "pivot":
        return _pivots(bars, args.left, args.right, args.source)
    if kind == "fractal":
        return _fractals(bars, args.source)
    if kind == "zigzag":
        return _zigzag(bars, band, args.reversal, args.source)
    raise SystemExit(f"unknown turn kind {kind}")


def alternating(turns: Turns) -> Turns:
    """Collapse runs of same-side turns to the most extreme of each run.

    Every definition here can emit two lows with no high between them, and a
    "previous opposite turn point" is only defined on an alternating sequence.
    Keeping the **extreme** of a run rather than the first or last is the
    choice a chartist makes drawing the leg, and it is the conservative one
    here: it puts the prior barrier as far away as the run allows.
    """
    keep: list[int] = []
    for k in range(turns.at.size):
        if keep and turns.side[keep[-1]] == turns.side[k]:
            previous = keep[-1]
            better = (
                turns.price[k] < turns.price[previous]
                if turns.side[k] == 1
                else turns.price[k] > turns.price[previous]
            )
            if better:
                keep[-1] = k
            continue
        keep.append(k)
    index = np.asarray(keep, dtype=np.int64)
    return Turns(
        at=turns.at[index], known=turns.known[index], side=turns.side[index], price=turns.price[index]
    )


@dataclass(slots=True)
class Penetration:
    """One leg's attempt on the previous opposite turn point."""

    reach_atr: np.ndarray
    cleared: np.ndarray
    overshoot: np.ndarray
    took: np.ndarray
    extent: np.ndarray
    day: np.ndarray
    side: np.ndarray
    regime: np.ndarray
    turn: np.ndarray


def penetrate(bars: Candles, band: np.ndarray, turns: Turns, source: str = "wick") -> Penetration:
    """For each leg, whether its extreme cleared the prior opposite turn point.

    The leg runs from where turn `k` became **known** to where turn `k+1`
    became known, and its extreme is taken over that stretch. The barrier is
    turn `k-1`, the previous opposite one, which for an up leg is the last high
    before this low.

    `reach_atr` is the distance from the turn's own price to that barrier in
    ATR, and it is the quantity everything is cut by: whether a leg clears the
    previous high is first a statement about how far away the previous high is.
    """
    tops, bottoms = extremes(bars, source)
    # **The volatility state at the turn, because the barrier is in ATR of
    # that bar.** Real ATR mean-reverts and a shuffled series' does not, so a
    # turn formed in a burst is followed by a quieter leg that travels less in
    # units of the ATR it was measured with - which produces a shortfall
    # against the shuffled arm with no barrier anywhere in it. Matching on this
    # as well as on distance is what separates the two.
    state = trailing_rank(band)
    reach, cleared, overshoot, took, extent, day, side, regime = [], [], [], [], [], [], [], []
    # **Which turn each leg belongs to, carried rather than re-derived.** A
    # caller that wants to join a description of the turn onto the leg's
    # outcome has to reproduce every `continue` in this loop to keep a counter
    # in step, and the first version of `turn_shape.py` reproduced one of four -
    # so the outcomes were silently attached to the wrong turns.
    owner: list[int] = []
    for k in range(1, turns.at.size - 1):
        if turns.side[k - 1] == turns.side[k]:
            continue
        start, stop = int(turns.known[k]), int(turns.known[k + 1])
        if stop <= start or stop >= len(bars):
            continue
        unit = band[int(turns.at[k])]
        if not np.isfinite(unit) or unit <= 0:
            continue
        here, barrier = float(turns.price[k]), float(turns.price[k - 1])
        up = turns.side[k] == 1
        span = (barrier - here) if up else (here - barrier)
        if span <= 0:
            # The prior high is already below this low, so there is nothing to
            # penetrate. Counted out rather than scored as a clearance: it is a
            # different configuration and scoring it as a win inflates the rate
            # by whatever share of the sequence is already trending.
            continue
        far = float(tops[start:stop].max()) if up else float(bottoms[start:stop].min())
        travelled = (far - here) if up else (here - far)
        reach.append(span / unit)
        cleared.append(1.0 if travelled >= span else 0.0)
        overshoot.append((travelled - span) / unit)
        took.append(stop - start)
        extent.append(travelled / unit)
        day.append(float(bars.ts[start] // 86_400_000_000_000))
        side.append(float(1 if up else -1))
        regime.append(float(state[int(turns.at[k])]))
        owner.append(k)
    return Penetration(
        reach_atr=np.asarray(reach),
        cleared=np.asarray(cleared),
        overshoot=np.asarray(overshoot),
        took=np.asarray(took, dtype=np.float64),
        extent=np.asarray(extent),
        day=np.asarray(day),
        side=np.asarray(side),
        regime=np.asarray(regime),
        turn=np.asarray(owner, dtype=np.int64),
    )


def clustering(turns: Turns, bars: Candles) -> str:
    """Do turns arrive in clusters: the gap's coefficient of variation.

    A memoryless process gives exactly 1.00, above it is clustered and below it
    is regular. `spiking.md` used the same statistic on the Boom spike and read
    0.99 against 1.00, which is how that one was closed.
    """
    if turns.at.size < 50:
        return "too few turns"
    gaps = np.diff(turns.known).astype(float)
    gaps = gaps[gaps > 0]
    if gaps.size < 50 or gaps.mean() <= 0:
        return "too few gaps"
    hours = float(np.median(np.diff(bars.ts[:1000]))) / 3_600_000_000_000 if len(bars) > 1000 else 0.0
    return (
        f"{turns.at.size:,} turns, gap mean {gaps.mean():.1f} bars "
        f"({gaps.mean() * hours:.1f}h), median {np.median(gaps):.0f}, CV {gaps.std() / gaps.mean():.3f} "
        f"against a memoryless 1.000"
    )


def table(found: Penetration, cells: int = 6) -> None:
    """The clearance rate by distance to the barrier, which is the whole cut."""
    if found.reach_atr.size < 100:
        print(f"      {found.reach_atr.size} legs, too few")
        return
    edges = np.percentile(found.reach_atr, np.linspace(0, 100, cells + 1))
    print(
        f"      {found.reach_atr.size:,} legs, cleared {found.cleared.mean():.4f}, "
        f"median reach {np.median(found.reach_atr):.2f} ATR, median hold {np.median(found.took):.0f} bars"
    )
    print("      reach ATR         n   cleared   median overshoot   mean extent")
    for c in range(cells):
        lo, hi = edges[c], edges[c + 1]
        pick = (found.reach_atr >= lo) & (found.reach_atr < hi) if c < cells - 1 else (found.reach_atr >= lo)
        if pick.sum() < 20:
            continue
        print(
            f"      {lo:5.2f}..{hi:6.2f} {pick.sum():>7,}   {found.cleared[pick].mean():.4f}   "
            f"{np.median(found.overshoot[pick]):+15.2f}   {found.extent[pick].mean():11.2f}"
        )
    for arm, name in ((1.0, "up legs"), (-1.0, "down legs")):
        pick = found.side == arm
        if pick.sum() > 50:
            print(f"      {name}: n {pick.sum():,}, cleared {found.cleared[pick].mean():.4f}")


def interval(found: Penetration, draws: int = 400, seed: int = 41) -> tuple[float, float]:
    """A day-block bootstrap of the clearance rate."""
    days = np.unique(found.day)
    if days.size < 20:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    index = {d: np.flatnonzero(found.day == d) for d in days}
    rates = [
        float(found.cleared[np.concatenate([index[d] for d in rng.choice(days, days.size, True)])].mean())
        for _ in range(draws)
    ]
    return float(np.percentile(rates, 5)), float(np.percentile(rates, 95))


def alphabet(turns: Turns, bars: Candles) -> str:
    """The HH/HL/LH/LL grammar, measured **within each side**.

    Each turn is one letter against the previous turn on its own side: a low
    above the last low is `HL`, below it `LL`; a high above the last high is
    `HH`, below it `LH`. That is the whole vocabulary chartists read a leg
    sequence with, and it is the smallest alphabet one has.

    **Within each side, because across sides the grammar is free.** A turn
    sequence alternates by construction, so the previous letter says with
    certainty whether the next comes from the low pair or the high pair -
    exactly one bit of a two-bit alphabet. Measured across sides the zigzag
    "saved" **+1.1213 bits** against [`grammar.md`](../docs/grammar.md)'s
    +0.04 to +0.06 for a real bar-shape grammar, which is the tell: an effect
    twenty times the size of the one a careful study found is usually the
    apparatus. Within a side the alphabet is one bit and the alternation
    cannot contribute.

    [`chart-patterns.md`](../docs/chart-patterns.md) is the standing warning on
    anything in this family: a random walk reproduced the published break-out
    direction rates on 18 of 18 patterns.
    """
    lows: list[int] = []
    highs: list[int] = []
    last_low, last_high = np.nan, np.nan
    for k in range(turns.at.size):
        here = float(turns.price[k])
        if turns.side[k] == 1:
            if np.isfinite(last_low):
                lows.append(0 if here > last_low else 1)
            last_low = here
        else:
            if np.isfinite(last_high):
                highs.append(0 if here > last_high else 1)
            last_high = here
    _ = bars
    out = []
    for name, letters in (("lows HL/LL", lows), ("highs HH/LH", highs)):
        if len(letters) < 100:
            out.append(f"{name} {len(letters)} too few")
            continue
        seen = np.asarray(letters)
        share = np.bincount(seen, minlength=2).astype(float)
        share /= share.sum()
        independent = -float(np.sum(share[share > 0] * np.log2(share[share > 0])))
        pairs = np.zeros((2, 2))
        for a, b in zip(seen[:-1], seen[1:], strict=False):
            pairs[a, b] += 1.0
        conditional = 0.0
        for a in range(2):
            row = pairs[a]
            if row.sum() < 10:
                continue
            q = row / row.sum()
            conditional += (row.sum() / pairs.sum()) * -float(np.sum(q[q > 0] * np.log2(q[q > 0])))
        out.append(
            f"{name} n {seen.size:,} higher {share[0]:.3f} H1 {independent:.4f} "
            f"saved {independent - conditional:+.4f}"
        )
    return "   ".join(out)


def revisits(turns: Turns, bars: Candles, band: np.ndarray, tol: float = 0.25) -> str:
    """How many later legs end at a turn point, against a shifted placebo node.

    **The one graph statistic in this family that is not already closed.**
    [`level-graph.md`](../docs/level-graph.md) measured *centrality* on a level
    graph and found real below its hardest null in 226 of 231 cells;
    [`topology.md`](../docs/topology.md) found persistent homology reads
    volatility clustering. Neither tested **degree over turn points**, which is
    the watchedness reformulation `a-magnet-is-a-shared-reference` leaves open:
    a price many participants compute should be where more legs end.

    The placebo node is the same turn point moved by a uniform 1 to 3 ATR,
    which keeps the distance scale and the forward window and removes only the
    claim that *this* price is the shared one. `the-placebo-arm-selects-the-
    null` is why it is reported beside the real degree rather than instead.
    """
    if turns.at.size < 50:
        return "too few turns"
    rng = np.random.default_rng(23)
    real, fake = [], []
    # Bounded to the next `ahead` turns: counting every later turn to the end
    # of the series makes the statistic mostly a function of how much sample
    # is left, which is matched between the arms but swamps the thing measured.
    ahead = 50
    for k in range(turns.at.size - 1):
        unit = band[int(turns.at[k])]
        if not np.isfinite(unit) or unit <= 0:
            continue
        price = float(turns.price[k])
        offset = float(rng.uniform(1.0, 3.0)) * unit * (1.0 if rng.random() < 0.5 else -1.0)
        later = turns.price[k + 1 : k + 1 + ahead]
        if later.size < ahead:
            continue
        real.append(int(np.sum(np.abs(later - price) <= tol * unit)))
        fake.append(int(np.sum(np.abs(later - (price + offset)) <= tol * unit)))
    if len(real) < 50:
        return "too few scored"
    _ = bars
    a, b = np.asarray(real, dtype=float), np.asarray(fake, dtype=float)
    spread = np.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size)
    return (
        f"later turns within {tol} ATR: real {a.mean():.3f} against placebo {b.mean():.3f}, "
        f"difference {a.mean() - b.mean():+.3f} +/- {1.96 * spread:.3f}"
    )


def _cells(values: np.ndarray, count: int) -> list[tuple[float, float]]:
    edges = np.percentile(values, np.linspace(0, 100, count + 1))
    return [(edges[c], edges[c + 1] if c < count - 1 else np.inf) for c in range(count)]


def matched(
    real: Penetration, other: Penetration, cells: int = 6, regimes: int = 1, seed: int = 53
) -> None:
    """Two arms' clearance rates inside **shared** bins, printed and bootstrapped.

    A pooled rate cannot compare the arms: a day-shuffled series has its own
    distribution of distances to the prior turn point, so the two pooled
    numbers differ for the same reason the deciles do. The bin edges come from
    the real arm and both arms are cut by them, which is the only way the
    column means the same thing twice.

    With `regimes > 1` the bins are **distance crossed with the volatility
    quantile at the turn**, which is the control that decides what the
    shortfall is. The barrier is a distance in ATR of the turn's own bar; real
    ATR mean-reverts and a shuffled series' does not, so a turn formed in a
    burst is followed by a quieter leg that covers less of that ATR. Measured on
    8 years of five markets at 1h, the distance-only difference is **-0.0152**
    on swing pivots and **-0.0114** on an ATR zigzag, and the shuffled arm's
    legs travel *further* in ATR - which is the shape volatility decay makes
    and not the shape a barrier makes.
    """
    if real.reach_atr.size < 200 or other.reach_atr.size < 200:
        print("      matched: too few legs")
        return
    distance = _cells(real.reach_atr, cells)
    state = _cells(real.regime[np.isfinite(real.regime)], regimes) if regimes > 1 else [(-np.inf, np.inf)]
    rng = np.random.default_rng(seed)
    label = "distance" if regimes == 1 else f"distance x {regimes} volatility"
    print(f"      {label} bins:  real n / real rate / other n / other rate / difference")
    groups: list[tuple[np.ndarray, np.ndarray, str]] = []
    for lo, hi in distance:
        for qlo, qhi in state:
            a = (real.reach_atr >= lo) & (real.reach_atr < hi)
            b = (other.reach_atr >= lo) & (other.reach_atr < hi)
            if regimes > 1:
                a &= (real.regime >= qlo) & (real.regime < qhi)
                b &= (other.regime >= qlo) & (other.regime < qhi)
            if a.sum() < 30 or b.sum() < 30:
                continue
            tag = f"{lo:5.2f}..{min(hi, 99.0):6.2f}" + (f"  q {qlo:.2f}" if regimes > 1 else "")
            groups.append((a, b, tag))
    if not groups:
        print("      no shared bins")
        return
    weighted = sum((real.cleared[a].mean() - other.cleared[b].mean()) * a.sum() for a, b, _ in groups)
    total = sum(a.sum() for a, _, _ in groups)
    for a, b, tag in groups:
        first, second = real.cleared[a].mean(), other.cleared[b].mean()
        print(
            f"      {tag} {a.sum():>8,}  {first:.4f} {b.sum():>8,}  {second:.4f}  {first - second:+.4f}"
            f"   extent {real.extent[a].mean():.2f} / {other.extent[b].mean():.2f}"
        )
    # **Whole days, resampled once per draw and then re-binned.** The first
    # version resampled rows inside each bin independently, which treats
    # overlapping legs on the same day as independent observations and gives an
    # interval far too narrow - the exact fault the skill's block-bootstrap rule
    # exists for. Legs cluster in days and a day carries several of them, so the
    # day is the unit; the bin weights stay at their original sizes so a draw
    # cannot reweight the comparison as well as resample it.
    # **Whole days, resampled once per draw.** The first version resampled
    # rows inside each bin independently, which treats overlapping legs on the
    # same day as independent observations and gives an interval about two and
    # a half times too narrow - the exact fault the skill's block-bootstrap
    # rule exists for. Legs cluster in days and a day carries several, so the
    # day is the unit.
    #
    # Counted with `bincount` over a precomputed bin id rather than by
    # re-testing 24 masks per draw: at 278,023 legs the mask version is about
    # 2e9 comparisons and did not finish.
    real_days, other_days = np.unique(real.day), np.unique(other.day)
    if real_days.size < 20 or other_days.size < 20:
        print(f"      {label}-matched difference {weighted / total:+.4f}, too few days to bootstrap")
        return
    width = len(groups)
    real_bin = np.full(real.cleared.size, -1, dtype=np.int64)
    other_bin = np.full(other.cleared.size, -1, dtype=np.int64)
    mass = np.zeros(width)
    for b, (a, other_mask, _) in enumerate(groups):
        real_bin[a] = b
        other_bin[other_mask] = b
        mass[b] = float(a.sum())

    def resample(day: np.ndarray, days: np.ndarray, where: dict, bins: np.ndarray, won: np.ndarray):
        rows = np.concatenate([where[d] for d in rng.choice(days, days.size, replace=True)])
        ids = bins[rows]
        live = ids >= 0
        ids, values = ids[live], won[rows][live]
        counts = np.bincount(ids, minlength=width).astype(float)
        totals = np.bincount(ids, weights=values, minlength=width)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(counts >= 10, totals / np.where(counts > 0, counts, np.nan), np.nan)

    real_where = {d: np.flatnonzero(real.day == d) for d in real_days}
    other_where = {d: np.flatnonzero(other.day == d) for d in other_days}
    draws = []
    for _ in range(300):
        first = resample(real.day, real_days, real_where, real_bin, real.cleared)
        second = resample(other.day, other_days, other_where, other_bin, other.cleared)
        usable = np.isfinite(first) & np.isfinite(second)
        if not usable.any():
            continue
        draws.append(float(np.sum((first - second)[usable] * mass[usable]) / np.sum(mass[usable])))
    if len(draws) < 50:
        print(f"      {label}-matched difference {weighted / total:+.4f}, bootstrap failed")
        return
    print(
        f"      {label}-matched difference {weighted / total:+.4f}, "
        f"90% [{np.percentile(draws, 5):+.4f}, {np.percentile(draws, 95):+.4f}]  "
        f"over {len(groups)} bins and {total:,} legs"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--csv", default="")
    parser.add_argument("--unit", default="5m")
    parser.add_argument("--frame", default="1h")
    parser.add_argument("--years", type=float, default=0.0)
    parser.add_argument("--kinds", default="origin,pivot,zigzag,fractal")
    parser.add_argument("--arms", default="real,shuffled")
    parser.add_argument("--left", type=int, default=15)
    parser.add_argument("--right", type=int, default=5)
    parser.add_argument("--reversal", type=float, default=1.5)
    parser.add_argument("--approach", type=float, default=1.5)
    parser.add_argument("--reach", type=float, default=3.0)
    parser.add_argument("--ahead", type=int, default=24)
    parser.add_argument("--behind", type=int, default=24)
    parser.add_argument("--share", type=float, default=0.5)
    parser.add_argument("--displacement", type=float, default=1.0)
    parser.add_argument("--pad", type=float, default=0.25)
    parser.add_argument("--tol", type=float, default=0.25, help="ATR within a turn point that counts as it")
    parser.add_argument(
        "--source",
        default="wick",
        choices=("wick", "body", "close"),
        help="what a turn point and a penetration are read off",
    )
    args = parser.parse_args()

    sources: list[tuple[str, Candles]] = []
    if args.csv:
        for pair in args.csv.split(","):
            name, _, path = pair.partition("=")
            sources.append((name, load_csv(Path(path), name, args.unit)))
    else:
        for symbol in (s for s in args.symbols.split(",") if s):
            sources.append((symbol, load(Path(args.catalogue), symbol)))

    print(
        f"frame {args.frame}  source {args.source}  left {args.left}  right {args.right}  "
        f"reversal {args.reversal}"
    )
    for kind in (k.strip() for k in args.kinds.split(",") if k.strip()):
        print(f"\n{'=' * 70}\n### {kind}\n{'=' * 70}")
        by_arm: dict[str, Penetration] = {}
        for arm in (a.strip() for a in args.arms.split(",") if a.strip()):
            print(f"\n  --- {arm}")
            pooled: list[Penetration] = []
            for name, base in sources:
                series = shuffled(base, seed=19) if arm == "shuffled" else base
                if args.years > 0:
                    series = window(series, args.years)
                bars = fold(series, args.frame, unit=args.unit)
                band = atr(bars)
                raw = turns_of(bars, band, kind, args)
                turns = alternating(raw)
                print(f"\n    {name}: {clustering(turns, bars)}")
                print(f"      grammar: {alphabet(turns, bars)}")
                print(f"      degree:  {revisits(turns, bars, band, args.tol)}")
                found = penetrate(bars, band, turns, args.source)
                table(found)
                lo, hi = interval(found)
                if np.isfinite(lo):
                    print(f"      day-block 90% on the rate [{lo:.4f}, {hi:.4f}]")
                pooled.append(found)
            if len(pooled) > 1:
                every = Penetration(
                    **{
                        field: np.concatenate([getattr(one, field) for one in pooled])
                        for field in (
                            "reach_atr",
                            "cleared",
                            "overshoot",
                            "took",
                            "extent",
                            "day",
                            "side",
                            "regime",
                            "turn",
                        )
                    }
                )
                print("\n    pooled")
                table(every)
                lo, hi = interval(every)
                if np.isfinite(lo):
                    print(f"      day-block 90% on the rate [{lo:.4f}, {hi:.4f}]")
                by_arm[arm] = every
            elif pooled:
                by_arm[arm] = pooled[0]
        if "real" in by_arm and "shuffled" in by_arm:
            print(f"\n  --- {kind}: real against shuffled, inside the real arm's bins")
            matched(by_arm["real"], by_arm["shuffled"])
            matched(by_arm["real"], by_arm["shuffled"], regimes=4)


if __name__ == "__main__":
    main()
