"""Four names for one object, and the two numbers that are actually claimed about it.

Several bodies of work point at the same thing from different directions, and
each of them names it something else:

| name | the point it marks | what confirms it |
| --- | --- | --- |
| ZigZag pivot | a local extreme | price retracing `theta` |
| FOCuS change point | where the distribution changed | its statistic clearing a bound |
| perceptually important point | whose removal most distorts the series | a distance criterion |
| change in state of delivery | the open of the run that began the prior move | a close beyond it |
| order block origin | the same candle under a different name | - |
| this desk's `Level` | a price repeatedly turned at | decisive interactions |

**They are all "the last price at which the market changed its mind", and every
one of them is knowable only after a delay.** The claim attached to all of them
is also the same: *price comes back to that point and is rejected there*. That
is one hypothesis with four detectors, not four hypotheses, and this harness
treats it that way - one scoring rule, one control, four ways of nominating the
level.

## Two specific numbers are on the table, from different sources

**Rejection on return: 63-65%, 60-63%, 52-55%** for ZigZag, FOCuS and a
derivative detector, with real levels beating matched-random ones by **14-23
points** across seven instruments and two independent panels. That result also
carries the warning this harness is built around: scoring the first retest from
the bar after the extreme, rather than from the bar the detector could first
have known, is worth **6.5 to 16.7 points** of pure look-ahead, and the slower
the detector the more it steals. Everything here is scored from confirmation.

**"Cycles close in the area of 86% of the previous leg."** A precise, falsifiable
claim and, as far as this folder knows, never tested. It is the second half of
this harness, and it matters beyond itself: `structures/cycles.py`'s depth head
predicts how far price runs before turning **in volatility units**, and if the
retracement is really a fraction of the previous leg then the wrong quantity is
being predicted.

A fourth detector is added because its source publishes **no statistics at all**
- not a win rate, not a sample size - while being specific enough to implement:
the level is the open of the candle that began the run that produced the prior
move, and the event is a close beyond it after a liquidity sweep.

    ./.secrets/lab.sh run research/harness/delivering.py
"""

from __future__ import annotations

import itertools
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from till_infinity.structures.learning.focus import Focus

DB = os.environ.get("PRICES_DB", ".data/prices/prices.db")

#: Retracement that confirms a ZigZag pivot, in units of the series' own per-bar
#: standard deviation. Swept, because a detector whose answer depends on its one
#: parameter has not found anything.
THETAS = (1.0, 2.0, 4.0)

#: How close price has to come to count as a return to the level, and how far it
#: then has to travel to count as rejected or as passed through. Both in the
#: same per-bar units, so "reject" and "break" are symmetric claims and the
#: outcome cannot be manufactured by making one easier than the other.
TOUCH = 0.5
RESOLVE = 2.0

#: How long a level is watched for a return. Beyond this the level has not been
#: tested, which is a third outcome and not a failure.
PATIENCE = 500

#: Fewest resolved returns before a cell is reported.
FEWEST = 50

#: Evidence, in nats, before FOCuS calls a change point. Swept, because one
#: value found almost nothing: the statistic is applied to **returns**, whose
#: mean is near zero and rarely shifts, so a threshold set for a level series is
#: far too high here. A detector that finds nothing at every threshold is a
#: result; one that finds nothing at the only threshold tried is a setting.
FOCUS_NATS = (2.0, 5.0, 12.0)

#: Bars a CISD run may span, and how long after a sweep the confirming close may
#: arrive. The source specifies neither - it says "a series of candles" and
#: "quickly" - so both are swept rather than chosen.
RUNS = (3, 5, 10)
PROMPTNESS = 20


@dataclass(slots=True)
class Level:
    """One nominated price, and the bar the detector could first have known it."""

    price: float
    known_at: int
    side: int  # +1 a level below price (support), -1 above (resistance)


# ------------------------------------------------------------------ detectors


def zigzag_levels(prices: np.ndarray, theta: float) -> list[Level]:
    """Confirmed alternating extremes, dated at **confirmation** not at the extreme.

    Three explicit states, because a version that tracked one extreme and moved
    it toward price on both sides while undecided produced exactly one turn per
    series - the distance from price to the extreme was always zero, so no
    reversal could accumulate and the direction never resolved.
    """
    n = len(prices)
    if n < 3 or theta <= 0:
        return []
    out: list[Level] = []
    hi = lo = float(prices[0])
    direction = 0
    for i in range(1, n):
        p = float(prices[i])
        if direction >= 0 and p > hi:
            hi = p
        if direction <= 0 and p < lo:
            lo = p
        # The extreme itself is in the past; the bar it became *knowable* is
        # this one, and that is the date every level here carries.
        if direction in (0, 1) and p <= hi - theta:
            out.append(Level(hi, i, -1))
            direction, lo = -1, p
        elif direction in (0, -1) and p >= lo + theta:
            out.append(Level(lo, i, +1))
            direction, hi = 1, p
    return out


def focus_levels(prices: np.ndarray, threshold: float = 12.0) -> list[Level]:
    """Change points from the shipped exact-CUSUM detector, dated at detection.

    The shipped implementation rather than a paraphrase: a test of a paraphrase
    is a test of the paraphrase. Two things it needs that are easy to get wrong
    and that a first version of this got wrong, silently, on every arm:

    * **`scale` is not optional.** `Focus` divides each observation by it before
      applying a Gaussian statistic, and the default is 1.0. Fed raw log returns
      of about 1e-4, the statistic is of order 1e-8 and **never clears any
      threshold** - the detector returns nothing for ever and looks like a
      series with no change points in it.
    * **It is one-sided.** `up=True` looks for an increase in the mean and
      nothing else, so a single instance is blind to half the change points
      there are. Two are run.
    """
    rets = np.diff(np.log(np.maximum(prices, 1e-12)))
    if len(rets) < 200:
        return []
    scale = float(np.std(rets))
    if scale <= 0:
        return []
    up, down = (
        Focus(threshold=threshold, scale=scale, up=True),
        Focus(threshold=threshold, scale=scale, up=False),
    )
    out: list[Level] = []
    for i, r in enumerate(rets):
        rose = up.update(float(r))
        fell = down.update(float(r))
        if not (rose or fell):
            continue
        at = i + 1
        # Detected on the way up means the level is behind and below.
        out.append(Level(float(prices[at]), at, -1 if rose else +1))
        up.reset()
        down.reset()
    return out


def derivative_levels(prices: np.ndarray, span: int = 5) -> list[Level]:
    """Slope sign changes over a centred window - the weak baseline.

    **Dated at the bar the window closes, not at the extreme in its middle.**
    A centred window cannot be evaluated until `span` bars after its centre, and
    scoring from the centre is precisely the look-ahead that inflated an earlier
    version of this measurement by up to 16.7 points.
    """
    n = len(prices)
    if n < 2 * span + 3:
        return []
    out: list[Level] = []
    for i in range(span, n - span):
        left = prices[i] - prices[i - span]
        right = prices[i + span] - prices[i]
        if left > 0 > right:
            out.append(Level(float(prices[i]), i + span, -1))
        elif left < 0 < right:
            out.append(Level(float(prices[i]), i + span, +1))
    return out


def cisd_levels(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    *,
    run: int = 5,
    promptness: int = PROMPTNESS,
) -> list[Level]:
    """Change in state of delivery, implemented from the only precise part of it.

    The source is specific about two things and vague about everything else. The
    level is **an opening price** - the open of the candle that initiated the
    run producing the prior move - and the event is a **close beyond it**. It
    says nothing about how many candles a run is, what breaks one, how quickly
    "quickly" is, or when the setup expires, so `run` and `promptness` are swept
    rather than chosen, and this note is here so nobody reads the result as a
    test of a specification that does not exist.

    Implemented as: a sweep of the last `run`-bar extreme that closes back
    inside, then a close beyond the open of the first candle of the run that
    reached that extreme.
    """
    n = len(closes)
    if n < run + 3:
        return []
    out: list[Level] = []
    for i in range(run + 1, n - 1):
        window = slice(i - run, i)
        prior_low = float(lows[window].min())
        prior_high = float(highs[window].max())
        # Bullish: swept the low and closed back above it.
        if lows[i] < prior_low <= closes[i]:
            start = i - run + int(np.argmin(lows[window]))
            level = float(opens[max(start, 0)])
            for j in range(i + 1, min(i + 1 + promptness, n)):
                if closes[j] > level:
                    out.append(Level(level, j, +1))
                    break
        elif highs[i] > prior_high >= closes[i]:
            start = i - run + int(np.argmax(highs[window]))
            level = float(opens[max(start, 0)])
            for j in range(i + 1, min(i + 1 + promptness, n)):
                if closes[j] < level:
                    out.append(Level(level, j, -1))
                    break
    return out


def depth_to_turn(prices: np.ndarray, theta: float) -> tuple[np.ndarray, np.ndarray]:
    """From any bar inside a leg, how much further does price go before turning.

    **The question a target has to answer**, and it is not the same as the size
    of the leg. A leg's total travel is known once it is over; what a desk needs
    at the moment it is in one is the *remaining* distance, and the average leg
    length overstates that badly - by the length already spent, which on a
    randomly chosen bar inside a leg is about half of it.

    Returned in units of the series' own per-bar standard deviation, and paired
    with how far the leg had already run when the reading was taken, so the two
    can be looked at together.
    """
    n = len(prices)
    if n < 100 or theta <= 0:
        return np.asarray([]), np.asarray([])
    unit = float(np.std(np.diff(prices))) or 1.0
    turns: list[tuple[int, float]] = []
    hi = lo = float(prices[0])
    hi_at = lo_at = 0
    direction = 0
    for i in range(1, n):
        p = float(prices[i])
        if direction >= 0 and p > hi:
            hi, hi_at = p, i
        if direction <= 0 and p < lo:
            lo, lo_at = p, i
        if direction in (0, 1) and p <= hi - theta:
            turns.append((hi_at, hi))
            direction, lo, lo_at = -1, p, i
        elif direction in (0, -1) and p >= lo + theta:
            turns.append((lo_at, lo))
            direction, hi, hi_at = 1, p, i
    remaining: list[float] = []
    spent: list[float] = []
    for (a_at, a_px), (b_at, b_px) in itertools.pairwise(turns):
        if b_at <= a_at:
            continue
        for i in range(a_at, b_at):
            remaining.append(abs(b_px - float(prices[i])) / unit)
            spent.append(abs(float(prices[i]) - a_px) / unit)
    return np.asarray(remaining), np.asarray(spent)


def random_levels(prices: np.ndarray, count: int, rng) -> list[Level]:
    """The control: as many levels, at random times, at the price prevailing then.

    Matched on count and on the price distribution, which is what makes the
    comparison about *where* the detector puts a level rather than about how
    many it puts or how far from price they sit.
    """
    if count <= 0 or len(prices) < 100:
        return []
    when = rng.choice(
        np.arange(50, len(prices) - 50), size=min(count, len(prices) - 100), replace=False
    )
    return [
        Level(float(prices[i]), int(i), 1 if rng.random() < 0.5 else -1)
        for i in sorted(int(w) for w in when)
    ]


# -------------------------------------------------------------------- scoring


def rejection_rate(prices: np.ndarray, levels: list[Level], unit: float) -> dict:
    """Of the levels price returned to, how many rejected rather than broke.

    **Scored from `known_at`.** A level is watched only from the bar its
    detector could first have named it, which is the correction worth 6.5 to
    16.7 points depending on how slow the detector is.

    Reject and break are the same distance in opposite directions, so the answer
    cannot be moved by making one of them easier to reach.
    """
    if not levels or unit <= 0:
        return {}
    touched = rejected = broke = 0
    for level in levels:
        start = level.known_at + 1
        stop = min(start + PATIENCE, len(prices))
        if start >= stop:
            continue
        found = -1
        for i in range(start, stop):
            if abs(prices[i] - level.price) <= TOUCH * unit:
                found = i
                break
        if found < 0:
            continue
        touched += 1
        # Away from the level on the side price arrived from is a rejection;
        # through it by the same distance is a break.
        away = level.price + level.side * RESOLVE * unit
        through = level.price - level.side * RESOLVE * unit
        for i in range(found + 1, min(found + 1 + PATIENCE, len(prices))):
            if (level.side > 0 and prices[i] >= away) or (level.side < 0 and prices[i] <= away):
                rejected += 1
                break
            if (level.side > 0 and prices[i] <= through) or (
                level.side < 0 and prices[i] >= through
            ):
                broke += 1
                break
    resolved = rejected + broke
    if resolved < FEWEST:
        return {"levels": len(levels), "touched": touched, "resolved": resolved}
    return {
        "levels": len(levels),
        "touched": touched,
        "resolved": resolved,
        "rejected": rejected / resolved,
    }


def retracements(prices: np.ndarray, theta: float) -> np.ndarray:
    """Each leg's depth as a fraction of the leg before it.

    The quantity the 86% claim is about. Measured between consecutive confirmed
    ZigZag extremes, so a "leg" is what the detector says it is rather than what
    somebody drew.
    """
    turns = []
    n = len(prices)
    hi = lo = float(prices[0])
    hi_at = lo_at = 0
    direction = 0
    for i in range(1, n):
        p = float(prices[i])
        if direction >= 0 and p > hi:
            hi, hi_at = p, i
        if direction <= 0 and p < lo:
            lo, lo_at = p, i
        if direction in (0, 1) and p <= hi - theta:
            turns.append((hi_at, hi))
            direction, lo, lo_at = -1, p, i
        elif direction in (0, -1) and p >= lo + theta:
            turns.append((lo_at, lo))
            direction, hi, hi_at = 1, p, i
    out = []
    for a, b, c in zip(turns, turns[1:], turns[2:], strict=False):
        leg = abs(b[1] - a[1])
        back = abs(c[1] - b[1])
        if leg > 0:
            out.append(back / leg)
    return np.asarray(out)


# -------------------------------------------------- when the mother cycle breaks


def cycle_breaks(prices: np.ndarray, slow: float) -> dict:
    """Does breaking the cycle above mean the trend has changed.

    **A different claim from alignment, and a better-posed one.** Agreement
    between timeframes is weak and continuous - `research/streaming.md`
    measured three versions of it at nothing. *Invalidation* is discrete: the
    mother cycle has a last confirmed pivot, and price taking that pivot out is
    an event with a date.

    The test has to be about what happens **after** the break, because "the
    trend changed" is a statement about the future and not a relabelling of the
    past. Two things are measured on the same bars:

    * **Continuation.** After a mother-cycle pivot is broken, does price keep
      going that way further than it does after a matched non-break bar?
    * **What it does to the cycle below.** Is the fast reversion call worse
      immediately after a break than it is at other times? If the big structure
      has genuinely changed, fading the small one into it should be punished.

    The matched comparison is against bars drawn from the same series with the
    same distribution of recent movement, so "after a break" is not simply
    "after a large move".
    """
    coarse = zigzag_levels(prices, slow)
    if len(coarse) < 12:
        return {}

    # **The level that can actually be broken is two pivots back, not one.**
    # Two versions of this found zero breaks on every series, and the reason is
    # structural rather than a coding slip: if price re-crosses the last
    # confirmed pivot before the next one confirms, the ZigZag simply extends
    # that leg and no intervening pivot ever exists. So between consecutive
    # confirmed pivots the previous one is unbreakable **by construction**, and
    # a window drawn there cannot contain the event however it is scored.
    #
    # What can be broken is the pivot the market has already moved past: in an
    # up leg, the low before the standing one. That is the higher low an uptrend
    # is made of, and price taking it out is the change of character the claim
    # is about.
    breaks: list[tuple[int, int]] = []
    lows: list[float] = []
    highs: list[float] = []
    at = 0
    for level in coarse:
        watch_low = lows[-1] if lows else None
        watch_high = highs[-1] if highs else None
        for i in range(at, min(level.known_at, len(prices))):
            p = float(prices[i])
            if watch_low is not None and p < watch_low:
                breaks.append((i, -1))
                watch_low = None
            elif watch_high is not None and p > watch_high:
                breaks.append((i, +1))
                watch_high = None
        if level.side < 0:
            highs.append(level.price)
        else:
            lows.append(level.price)
        at = level.known_at

    if len(breaks) < 20:
        return {"breaks": len(breaks)}

    horizon = 50
    moved = []
    for at, way in breaks:
        stop = min(at + horizon, len(prices) - 1)
        if stop <= at:
            continue
        moved.append(way * math.log(prices[stop] / prices[at]))

    # The matched control: bars with a comparable recent move, break or not.
    rets = np.abs(np.diff(np.log(np.maximum(prices, 1e-12))))
    scale = float(np.mean(rets)) if len(rets) else 0.0
    rng = np.random.default_rng(3)
    broken_at = {a for a, _ in breaks}
    pool = [
        i
        for i in range(60, len(prices) - horizon)
        if i not in broken_at and abs(math.log(prices[i] / prices[i - 20])) > 4 * scale
    ]
    control = []
    if pool:
        picks = rng.choice(pool, size=min(len(breaks), len(pool)), replace=False)
        for pick in picks:
            at = int(pick)
            way = 1 if prices[at] > prices[at - 20] else -1
            ahead = prices[min(at + horizon, len(prices) - 1)]
            control.append(way * math.log(ahead / prices[at]))

    out = {
        "breaks": len(breaks),
        "after_break": float(np.mean(moved)) / (scale + 1e-12) if moved else float("nan"),
        "after_match": float(np.mean(control)) / (scale + 1e-12) if control else float("nan"),
    }
    if moved and control:
        pooled = math.sqrt(
            float(np.var(moved)) / len(moved) + float(np.var(control)) / len(control)
        )
        out["z"] = (float(np.mean(moved)) - float(np.mean(control))) / (pooled + 1e-15)
    return out


# ----------------------------------------------------------------- the series


def bars_for(conn: sqlite3.Connection, feed: str, venue: str, interval: str, limit: int = 20000):
    """One instrument at one venue. **Venue matters and is not optional.**

    A query selecting on feed alone returns several venues' rows interleaved by
    timestamp, and the alternation between two quotes of one asset is itself a
    violently reverting series - it produced a VR(8) of 0.145 in one earlier
    test and an AUC of 0.86 in another, both silently.
    """
    rows = conn.execute(
        "SELECT open, high, low, close FROM bars WHERE feed=? AND venue=? AND interval=?"
        " AND close>0 ORDER BY ts LIMIT ?",
        (feed, venue, interval, limit),
    ).fetchall()
    if len(rows) < 2000:
        return None
    got = np.array(rows, dtype=float)
    return got[:, 0], got[:, 1], got[:, 2], got[:, 3]


def gbm(n: int, sigma: float, rng, start: float = 100.0):
    return start * np.exp(np.cumsum(rng.normal(0.0, sigma, n)))


def ou(n: int, theta: float, sigma: float, rng, start: float = 100.0):
    x = np.empty(n)
    x[0] = start
    shocks = rng.normal(0.0, sigma, n)
    for i in range(1, n):
        x[i] = x[i - 1] + theta * (start - x[i - 1]) + shocks[i]
    return x


def synth_ohlc(closes: np.ndarray):
    """Opens and extremes for a simulated close series, so CISD can be run on it.

    Open is the previous close and the extremes are the two endpoints - the same
    limitation `prices/spreads.py` documents, and stated here because a CISD
    level is an **open**, so a simulated arm is testing a weaker version of the
    detector than a real-bar arm is.
    """
    opens = np.concatenate([[closes[0]], closes[:-1]])
    return opens, np.maximum(opens, closes), np.minimum(opens, closes), closes


def detectors(o, h, lo, c, unit: float, rng) -> dict[str, list[Level]]:
    found: dict[str, list[Level]] = {}
    for theta in THETAS:
        found[f"zigzag {theta:g}"] = zigzag_levels(c, theta * unit)
    for nats in FOCUS_NATS:
        found[f"focus {nats:g}"] = focus_levels(c, threshold=nats)
    found["derivative"] = derivative_levels(c)
    for run in RUNS:
        found[f"cisd {run}"] = cisd_levels(o, h, lo, c, run=run)
    typical = int(np.median([len(v) for v in found.values() if v]) or 0)
    found["random (control)"] = random_levels(c, typical, rng)
    return found


def report(name: str, o, h, lo, c, rng) -> None:
    unit = float(np.std(np.diff(c))) or 1.0
    print(f"\n{name}  ({len(c):,} bars, unit {unit:.6g})")
    print(f"  {'detector':18} {'levels':>7} {'touched':>8} {'resolved':>9} {'rejected':>9}")
    for label, levels in detectors(o, h, lo, c, unit, rng).items():
        got = rejection_rate(c, levels, unit)
        if not got:
            print(f"  {label:18}  nothing found")
            continue
        rate = got.get("rejected")
        shown = f"{rate:.4f}" if rate is not None else "[too few]"
        print(
            f"  {label:18} {got['levels']:>7,} {got['touched']:>8,} "
            f"{got['resolved']:>9,} {shown:>9}"
        )


def question_one(conn, rng, minute: float) -> None:
    """Does price come back to the level and get rejected there."""
    print("Four names for one object: does price come back to it and get rejected?\n")
    print("Every level is scored from the bar its own detector could first have named it.")
    print("Scoring from the extreme instead is worth 6.5 to 16.7 points of look-ahead,")
    print("and the slower the detector the more it steals. Reject and break are the same")
    print("distance in opposite directions, so neither outcome is the easier one.")
    for label, closes in (
        ("GBM (null)", gbm(20000, 0.75 * minute, rng)),
        ("OU theta=0.05 (control)", ou(20000, 0.05, 0.5, rng)),
    ):
        report(label, *synth_ohlc(closes), rng)
    if conn is None:
        return
    for feed, venue, interval in (
        ("btc_binance_coinbase", "SPREAD", "1m"),
        ("btc_binance_kraken", "SPREAD", "1m"),
        ("btc", "BINANCE", "1m"),
        ("gold", "OANDA", "15m"),
        ("eurusd", "PEPPERSTONE", "15m"),
        ("spx500", "OANDA", "1h"),
    ):
        got = bars_for(conn, feed, venue, interval)
        if got is None:
            print(f"\n{feed} @ {venue} {interval}  [not enough bars]")
            continue
        report(f"{feed} @ {venue} {interval}", *got, rng)


def question_two(conn, rng, minute: float) -> None:
    """Does the market retrace 86% of the previous leg."""
    print("\n\nDoes the market retrace 86% of the previous leg?\n")
    print("Between consecutive confirmed ZigZag extremes, so a leg is what the detector")
    print("says it is. A claim about a *mode* has to beat what a random walk's legs do.\n")
    print(f"  {'series':34} {'theta':>6} {'n':>7} {'median':>8} {'in .80-.92':>11} {'>1':>7}")
    arms = [
        ("GBM (null)", gbm(40000, 0.75 * minute, rng)),
        ("OU theta=0.05 (control)", ou(40000, 0.05, 0.5, rng)),
    ]
    if conn is not None:
        for feed, venue, interval in (
            ("btc_binance_coinbase", "SPREAD", "1m"),
            ("btc", "BINANCE", "1m"),
            ("gold", "OANDA", "15m"),
            ("spx500", "OANDA", "1h"),
        ):
            got = bars_for(conn, feed, venue, interval)
            if got is not None:
                arms.append((f"{feed} @ {venue} {interval}", got[3]))
    for label, closes in arms:
        unit = float(np.std(np.diff(closes))) or 1.0
        for theta in (1.0, 2.0, 4.0):
            got = retracements(closes, theta * unit)
            if len(got) < 100:
                continue
            band = float(((got >= 0.80) & (got <= 0.92)).mean())
            print(
                f"  {label[:34]:34} {theta:>6.1f} {len(got):>7,} "
                f"{float(np.median(got)):>8.3f} {band:>11.4f} {float((got > 1).mean()):>7.3f}"
            )


def question_three(conn, rng, minute: float) -> None:
    """Does breaking the cycle above mean the trend has changed."""
    print("\n\nDoes breaking the cycle above mean the trend has changed?\n")
    print("The mother cycle's last confirmed pivot, taken out. Measured forward 50 bars in")
    print("units of the series' own mean absolute return, against bars matched on how far")
    print("price had just moved - so 'after a break' is not merely 'after a large move'.\n")
    print(f"  {'series':30} {'cycle':>5} {'breaks':>7} {'after break':>12} {'matched':>9} {'z':>7}")
    arms = [
        ("GBM (null)", gbm(40000, 0.75 * minute, rng)),
        ("OU theta=0.05 (control)", ou(40000, 0.05, 0.5, rng)),
    ]
    if conn is not None:
        for feed, venue, interval in (
            ("btc", "BINANCE", "1m"),
            ("gold", "OANDA", "15m"),
            ("eurusd", "PEPPERSTONE", "15m"),
            ("spx500", "OANDA", "1h"),
            ("btc_binance_coinbase", "SPREAD", "1m"),
        ):
            got = bars_for(conn, feed, venue, interval)
            if got is not None:
                arms.append((f"{feed} @ {venue} {interval}", got[3]))
    for label, closes in arms:
        unit = float(np.std(np.diff(closes))) or 1.0
        # Swept: how big the "cycle above" is decides how many breaks there are
        # to count, and on five thousand bars a large one leaves a dozen.
        for coarse in (3.0, 5.0, 8.0):
            got = cycle_breaks(closes, coarse * unit)
            if not got or "after_break" not in got:
                print(f"  {label[:30]:30} {coarse:>5.1f} {got.get('breaks', 0):>7}  [too few]")
                continue
            print(
                f"  {label[:30]:30} {coarse:>5.1f} {got['breaks']:>7} "
                f"{got['after_break']:>12.3f} {got['after_match']:>9.3f} "
                f"{got.get('z', float('nan')):>7.2f}"
            )
    print("\n  Positive 'after break' with a positive z is continuation: the break said")
    print("  something. Both columns alike is a break saying only that price moved.")


def question_four(conn, rng, minute: float) -> None:
    """How much further does price go before it turns."""
    print("\n\nHow much depth is left before the turn?\n")
    print("From a bar inside a leg, the *remaining* distance to the turn, in units of the")
    print("series' own per-bar standard deviation. Not the leg's length: at a randomly")
    print("chosen bar inside a leg about half of it is already spent, so leg length")
    print("overstates what is still on the table by roughly a factor of two.\n")
    print(
        f"  {'series':34} {'theta':>6} {'n':>8} {'median':>8} {'mean':>7} "
        f"{'p75':>7} {'p90':>7} {'spent':>7}"
    )
    arms = [
        ("GBM (null)", gbm(40000, 0.75 * minute, rng)),
        ("OU theta=0.05 (control)", ou(40000, 0.05, 0.5, rng)),
    ]
    if conn is not None:
        for feed, venue, interval in (
            ("btc_binance_coinbase", "SPREAD", "1m"),
            ("btc", "BINANCE", "1m"),
            ("gold", "OANDA", "15m"),
            ("eurusd", "PEPPERSTONE", "15m"),
            ("spx500", "OANDA", "1h"),
        ):
            got = bars_for(conn, feed, venue, interval)
            if got is not None:
                arms.append((f"{feed} @ {venue} {interval}", got[3]))
    for label, closes in arms:
        unit = float(np.std(np.diff(closes))) or 1.0
        for theta in (2.0, 4.0):
            left, spent = depth_to_turn(closes, theta * unit)
            if len(left) < 500:
                continue
            print(
                f"  {label[:34]:34} {theta:>6.1f} {len(left):>8,} "
                f"{float(np.median(left)):>8.2f} {float(np.mean(left)):>7.2f} "
                f"{float(np.quantile(left, 0.75)):>7.2f} "
                f"{float(np.quantile(left, 0.90)):>7.2f} "
                f"{float(np.median(spent)):>7.2f}"
            )
    print("\n  The median is what a target should be sized against; p90 is what a trail")
    print("  gives away by holding for. `spent` is how far the leg had already run.")


def main() -> int:
    rng = np.random.default_rng(23)
    minute = math.sqrt(1.0 / (365 * 24 * 60))
    try:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        print(f"[no bars at {DB}: {exc}]")
        conn = None
    try:
        question_one(conn, rng, minute)
        question_two(conn, rng, minute)
        question_three(conn, rng, minute)
        question_four(conn, rng, minute)
    finally:
        if conn is not None:
            conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
