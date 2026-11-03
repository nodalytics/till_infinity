"""What the stop-anchor harness must get right, and what breaks if it does not.

Run explicitly - `research/` is outside `testpaths`:

    uv run pytest research/ideas/test_stop_anchor.py -q

Ordered by what a failure costs. Causality comes first: a book that can see a
bar past the anchor makes every number in the study a lookahead, and a stop
rule is exactly the place that would not show up as an implausible result -
it would show up as a stop that is never hit.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

import research.ideas.stop_anchor_book as B
from till_infinity.indicators.grouping import Anchor, cluster
from till_infinity.indicators.trend import pivots


def wiggle(n: int, *, seed: int = 7) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`(high, low, close)` for a walk with ranges, so pivots actually form.

    A fixture with structure in it, not a straight line: a flat series has no
    pivots, so every assertion about a book would pass on an empty book.
    """
    rng = random.Random(seed)
    close = np.cumsum([100.0] + [rng.gauss(0.0, 1.0) for _ in range(n - 1)])
    span = np.asarray([abs(rng.gauss(0.8, 0.3)) + 0.1 for _ in range(n)])
    low = close - span * 0.5
    return low + span, low, close


# ───────────────────────────── causality ─────────────────────────────


def test_the_book_reads_no_bar_past_the_anchor():
    """Every reading on bar `i` is a function of bars 0..i and nothing later.

    Checked by prefix, the way `tests/test_structure_bos.py` checks `Fold`: run
    the first `k` bars alone and require the readings to equal the first `k` of
    the full run. A book that peeked would disagree with itself here, and a
    stop anchored on a level confirmed by a bar that has not printed is a stop
    that is never hit - which looks like a result, not like a bug.
    """
    high, low, close = wiggle(400)
    full = B.book_path(high, low, close, unit_span=20)
    for k in (120, 250, 399):
        part = B.book_path(high[:k], low[:k], close[:k], unit_span=20)
        for pick in ("near", "beyond"):
            for field in ("below_low", "below_centre", "above_high", "unit"):
                a = getattr(full[pick], field)[:k]
                b = getattr(part[pick], field)
                assert np.allclose(a, b, equal_nan=True), f"{pick}.{field} diverged at k={k}"


def test_the_walkers_pivots_are_the_production_detectors():
    """The book's touches are `trend.pivots`', bar for bar and price for price.

    A level is a price *price turned at*, and this repo has exactly one causal
    definition of a turn. If the walker drifted from it - a tie admitted, a
    confirmation off by a bar - the study would anchor stops on prices that
    nothing else on this desk calls a level, and the write-up would be about a
    different object than `indicators/levels.py` builds.
    """
    high, low, close = wiggle(600, seed=11)
    ts = np.arange(len(close), dtype=float) * 900.0
    walker = B.Walker(unit_span=20)
    mine = []
    for i in range(len(close)):
        for bar, price, side in walker.update(float(high[i]), float(low[i])):
            mine.append((bar - 1, round(price, 10), side))
    window = list(zip(high.tolist(), low.tolist(), ts.tolist(), strict=True))
    at = {t: i for i, t in enumerate(ts.tolist())}
    theirs = [(at[p.confirmed], round(p.price, 10), p.side) for p in pivots(window, B.BOOK_REACH)]
    assert theirs, "the fixture produced no pivots, so this test asserts nothing"
    assert sorted(mine) == sorted(theirs)


# ──────────────────────── the arithmetic the claim rests on ────────────────────


def test_a_clusters_floor_is_outside_its_touches_and_its_centre_is_inside():
    """The one thing the claim gets right, asserted through `Group.price`.

    The desk's worked example: four touches weighted 1,3,4,2 give a centre of
    99.969 against a floor of 99.800. A stop below the *centre* of a support
    cluster is still above three of its four touches, so the level has to break
    before the stop is reached - which is the opposite of what a stop is for.
    This test is what stops a later change to `cluster` from quietly making the
    two anchors the same number and the study unfalsifiable.
    """
    prices = [99.80, 99.95, 100.00, 100.02]
    groups = cluster(prices, 0.35, weights=[1, 3, 4, 2])
    assert len(groups) == 1
    group = groups[0]
    assert group.price(Anchor.FLOOR) == pytest.approx(99.800)
    assert group.price(Anchor.CENTRE) == pytest.approx(99.969, abs=5e-4)
    centre = group.price(Anchor.CENTRE)
    below = [p for p in prices if p < centre]
    above = [p for p in prices if p > centre]
    assert below and above, "a centre with touches on only one side is not inside the body"
    assert len(below) == 2, f"the worked example has two touches under the centre, not {below}"
    assert all(p >= group.price(Anchor.FLOOR) for p in prices), "a touch below the floor"


def test_anchor_sided_names_the_levels_own_side_and_not_the_trades():
    """`Anchor.SIDED` is keyed on how the level formed, which is not the claim.

    The stop claim is written in the **trade's** side - the floor for a long -
    and `SIDED` reads `levels.Level.side`, the pivot side that formed the
    level. Where they disagree, a long is handed the group's *ceiling*: a price
    above its own entry, which is not a stop at all. The harness therefore
    passes the trade's side explicitly and reports the disagreement rate, and
    this test pins the divergence so a future change to either definition fails
    here rather than silently making the two agree.
    """
    group = cluster([10.0, 10.2], 1.0)[0]
    assert group.price(Anchor.SIDED, side=-1) == group.price(Anchor.FLOOR)
    assert group.price(Anchor.SIDED, side=+1) == group.price(Anchor.CEILING)
    assert group.price(Anchor.SIDED, side=0) == group.price(Anchor.CENTRE)


# ─────────────────────────── the race and the arms ───────────────────────────


def test_the_anchor_bars_own_range_cannot_stop_the_trade():
    """The forward window starts at `i + 1`, and being off by one flatters tight
    arms most.

    The entry is bar `i`'s close, so bar `i` has already printed and its low is
    not a future event. Including it would stop every trade whose anchor bar
    had a wick past the stop - which is a larger share of the tight arms than
    of the wide ones, so the error would read as "wide stops are better" and
    that is the exact confound this study exists to separate.
    """
    close = np.full(5, 100.0)
    low = np.array([90.0, 100.0, 100.0, 100.0, 90.0])
    high = np.full(5, 100.0)
    hit, r = B.race(high, low, close, np.full(5, 95.0), 1, 2)
    assert not bool(hit[0]), "bar 0's own low of 90 is at the entry, not after it"
    assert r[0] == pytest.approx(0.0), "a flat forward path at the entry is 0R, not a stop-out"
    # The control: bar 4's low of 90 *is* in bar 2's forward window, so the
    # same price does stop a later anchor. Without this the test above would
    # pass on a race that never stops anything.
    assert bool(hit[2]), "bar 4's low of 90 is two bars after anchor 2 and must stop it"
    assert r[2] == pytest.approx(-1.0)


def test_a_wider_stop_is_stopped_less_often_on_the_same_path():
    """The control: the race responds to width, so a null between arms means
    something.

    Without this, "no difference between the arms" is indistinguishable from
    "the race cannot tell two stop distances apart". Every gate needs a control
    showing it lets something through, and for a measurement the control is
    that the measurement moves when the thing it measures does.
    """
    high, low, close = wiggle(500, seed=3)
    unit = np.full(len(close), 1.0)
    rates = []
    for width in (0.5, 1.0, 2.0, 4.0):
        hit, _r = B.race(high, low, close, close - width * unit, 1, 20)
        rates.append(hit[:-25].mean())
    assert rates == sorted(rates, reverse=True), f"not monotone in width: {rates}"
    assert rates[0] > rates[-1] + 0.2, f"width barely moves the stop-out rate: {rates}"


def test_the_matched_placebo_keeps_the_width_distribution_and_breaks_the_pairing():
    """The decisive arm must differ from `floor` in **one** thing.

    If the permutation changed the set of widths, the arm would differ from
    `floor` in width as well as in which anchor got which width - and the study
    could not tell "the anchor carries information" from "this arm is wider",
    which is the whole question. `a-return-rate-is-geometry` is the recorded
    case: a distance-matched placebo reproduced an 82% return rate on every
    class, and a walk reads 0.825.
    """
    values = np.asarray([1.0, 2.0, 3.0, 4.0, 5.0, np.nan])
    mask = np.array([True, True, True, True, True, False])
    moved = B.permute(values, mask, random.Random(1))
    assert sorted(moved[mask].tolist()) == sorted(values[mask].tolist())
    assert np.isnan(moved[~mask]).all(), "the placebo must not fill an anchor it was not given"
    draws = [tuple(B.permute(values, mask, random.Random(s))[mask]) for s in range(40)]
    assert len(set(draws)) > 1, "a permutation that never permutes is not a placebo"


def test_every_arm_is_scored_on_the_same_anchors():
    """One anchor set for every arm, or a cell compares different samples.

    `usable` intersects the arms, so an arm whose book was empty does not get
    scored on the anchors where it had something to say while another arm is
    scored on all of them. An arm that fell back to the volatility stop
    instead would be a mixture of two rules under one name - the defect `one
    column, one unit` names, where a feature silently falling back to another
    scale puts one journal column in two units and both readings look fine.
    """
    high, low, close = wiggle(500, seed=5)
    books = B.book_path(high, low, close, unit_span=20)
    unit = books["near"].unit
    stops = {
        a.name: B.distances(books, close, unit, a, 1)
        for a in B.arms()
        if a.kind != "matched"
    }
    ok = B.usable(stops, unit, 20)
    assert ok.sum() > 50, "the fixture left too few anchors for this to assert anything"
    for name, values in stops.items():
        found = values[ok]
        assert np.isfinite(found).all(), f"{name} has a non-finite stop on a kept anchor"
        assert (found > 0.0).all(), f"{name} has a non-positive stop on a kept anchor"
        assert (found <= B.MAX_VOL * unit[ok]).all(), f"{name} exceeds the cap on a kept anchor"


def test_the_beyond_book_clears_the_incumbent_distance_and_the_near_book_does_not():
    """The two readings of the claim are different rules, and the near one is a
    *tighter* stop than the incumbent rather than a wider one.

    Measured on 19.2 years of daily eurusd: the nearest cluster's floor sits
    0.427 volatility units below the close against `SurpriseProfile.stop_vol`
    of 2.0. Anchoring on it multiplies `cost_px / risk` by four to five, which
    is a cost statement and not an edge one. This test is what keeps the two
    books from being conflated in a later change, because their numbers are not
    comparable and the write-up reports them separately for that reason.
    """
    high, low, close = wiggle(800, seed=9)
    books = B.book_path(high, low, close, unit_span=20, beyond=B.MIN_VOL)
    unit = books["near"].unit
    far = (close - books["beyond"].below_low) / unit
    found = far[np.isfinite(far)]
    assert found.size > 100, "the fixture produced too few `beyond` readings"
    assert (found >= B.MIN_VOL - 1e-9).all(), "a `beyond` anchor failed to clear MIN_VOL"
    near = (close - books["near"].below_low) / unit
    assert np.nanmedian(near) < np.nanmedian(far), "the two books returned the same level"
