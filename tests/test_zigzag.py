"""Legs between confirmed turns, and the three ways a zigzag lies.

A zigzag is the most-drawn indicator there is and almost every published one
repaints, so most of this file is about causality rather than arithmetic.

**It lies about its last leg.** The pivot that will end the leg in progress is
not fixed, so its side, extent and duration can all still change. `legs`
returns confirmed legs only and the test below changes a forming leg's
direction under it to prove the point.

**It lies about retracement ratios.** Every leg a detector records is at
least its threshold, so a ratio of two such legs is a ratio of truncated
quantities. `research/docs/asking.md` gives the diagnostic - sweep the
threshold and see whether the reading moves - and the test below runs it.

**It lies about asymmetry being structure.** Up and down legs genuinely
differ, and a random walk produces the same difference. That test is the one
most worth having here, because the asymmetry is real, is measured on this
desk at z -4.56, and carries no information about what comes next.
"""

from __future__ import annotations

import random

import pytest

from till_infinity.indicators.levels import Sided
from till_infinity.indicators.trend import Pivot
from till_infinity.indicators.zigzag import (
    Forecast,
    Leg,
    Prediction,
    Shape,
    Source,
    Zigzag,
    legs_from,
)

HOUR = 3_600.0


def walk(bars: int = 400, seed: int = 11, sigma: float = 0.004) -> list[tuple[float, float, float]]:
    """A random walk as `(high, low, when)`, hourly."""
    rng = random.Random(seed)
    out, price = [], 100.0
    for i in range(bars):
        price *= 1.0 + rng.gauss(0.0, sigma)
        out.append((price * 1.003, price * 0.997, i * HOUR))
    return out


def fed(bars: list[tuple[float, float, float]], **kwargs) -> Zigzag:
    found = Zigzag(**kwargs)
    for high, low, when in bars:
        found.update_raw(high, low, when)
    return found


def pivot(side: int, price: float, when: float, confirmed: float) -> Pivot:
    return Pivot(side=side, price=price, when=when, confirmed=confirmed)


# ------------------------------------------------------------- the legs themselves


def test_consecutive_pivots_become_legs():
    """`n` pivots give `n - 1` legs, each spanning one adjacent pair."""
    found = [
        pivot(-1, 100.0, 0.0, 3 * HOUR),
        pivot(+1, 110.0, 10 * HOUR, 13 * HOUR),
        pivot(-1, 104.0, 20 * HOUR, 23 * HOUR),
    ]
    built = legs_from(found)

    assert len(built) == 2
    assert [leg.side for leg in built] == [+1, -1]
    assert built[0].extent == pytest.approx(10.0)
    assert built[1].extent == pytest.approx(6.0)


def test_a_leg_is_dated_by_the_pivot_that_ends_it():
    """**The causality.** A leg becomes knowable when its *closing* pivot is
    confirmed, so that is the time it carries - and `lag` is the gap a study
    has to respect between the extreme printing and the leg existing."""
    built = legs_from([pivot(-1, 100.0, 0.0, 3 * HOUR), pivot(+1, 110.0, 10 * HOUR, 13 * HOUR)])
    leg = built[0]

    assert leg.ended == 10 * HOUR
    assert leg.confirmed == 13 * HOUR
    assert leg.lag == pytest.approx(3 * HOUR)


def test_extent_is_a_scale_and_never_a_signal():
    """Non-negative whichever way the leg ran, so it cannot be read as a
    direction by accident."""
    up = legs_from([pivot(-1, 100.0, 0.0, 1.0), pivot(+1, 110.0, HOUR, 2 * HOUR)])[0]
    down = legs_from([pivot(+1, 110.0, 0.0, 1.0), pivot(-1, 100.0, HOUR, 2 * HOUR)])[0]
    assert up.extent == down.extent == pytest.approx(10.0)


def test_an_extent_in_volatility_units_is_the_comparable_form():
    """A leg on gold and a leg on eurusd are not the same quantity in price."""
    leg = legs_from([pivot(-1, 100.0, 0.0, 1.0), pivot(+1, 110.0, HOUR, 2 * HOUR)])[0]
    assert leg.units(2.5) == pytest.approx(4.0)
    assert leg.units(0.0) == 0.0, "an unusable unit reads zero rather than dividing"


def test_speed_is_zero_over_no_time_rather_than_infinite():
    """Two pivots on one bar is a real thing at a small reach."""
    leg = legs_from([pivot(-1, 100.0, HOUR, HOUR), pivot(+1, 110.0, HOUR, 2 * HOUR)])[0]
    assert leg.span == 0.0
    assert leg.speed() == 0.0


# ---------------------------------------------------- the lie about the last leg


def test_the_forming_leg_is_not_among_the_confirmed_ones():
    """**The repainting guard.** Price has left the last confirmed turn and
    has not fixed the next one, so the leg in progress is not a leg."""
    found = fed(walk())
    side, start, extent = found.forming()

    assert extent > 0.0, "price has moved away from the last turn"
    assert all(leg.ended <= found.legs[-1].ended for leg in found.legs)
    assert side == -found.legs[-1].side, "the forming leg faces the other way"
    assert start == found.legs[-1].end


def test_a_forming_leg_changes_while_confirmed_legs_do_not():
    """Which is why the forming leg is not returned as a leg. Fed six bars
    further, `forming` reads differently while every leg confirmed in the
    shorter run is still present, unchanged, in the longer one."""
    bars = walk(bars=200)
    early = fed(bars[:-6], keep=64)
    later = fed(bars, keep=64)

    settled = {(leg.ended, leg.extent) for leg in early.legs}
    assert settled <= {(leg.ended, leg.extent) for leg in later.legs}, "a confirmed leg moved"
    assert early.forming() != later.forming()


def test_nothing_is_published_before_a_leg_is_confirmed():
    """A pivot needs `2 * reach + 1` bars and a leg needs two pivots, so a
    fresh indicator has nothing to say for a while - and says nothing rather
    than a provisional something."""
    found = Zigzag(reach=3, span=60)
    for high, low, when in walk(bars=6):
        found.update_raw(high, low, when)

    assert found.legs == []
    assert found.latest is None
    assert found.shape is None
    assert found.forming() is None
    assert found.initialized is False
    assert found.has_inputs is True


# ----------------------------------------------- the lie about retracement ratios


def test_retracement_moves_with_the_threshold():
    """**The published diagnostic, made executable.** Every leg a detector
    records is at least its threshold, so a ratio of two of them is a ratio of
    truncated quantities - and `asking.md` says to sweep the threshold and see
    whether the reading moves. On one fixed series it does, which means the
    constant is partly the detector and any study quoting a retracement has to
    report the sweep."""
    bars = walk(bars=600)
    readings = {}
    for reach in (2, 3, 5):
        found = fed(bars, reach=reach, span=240, keep=64)
        ratios = [
            Shape(prior=a, latest=b).retracement
            for a, b in zip(found.legs, found.legs[1:], strict=False)
        ]
        readings[reach] = sum(ratios) / len(ratios)

    assert len({round(v, 3) for v in readings.values()}) > 1, readings


def test_a_retracement_against_a_zero_leg_is_zero_not_a_division():
    flat = Leg(side=+1, start=100.0, end=100.0, began=0.0, ended=HOUR, confirmed=2 * HOUR)
    other = Leg(side=-1, start=100.0, end=98.0, began=HOUR, ended=2 * HOUR, confirmed=3 * HOUR)
    assert Shape(prior=flat, latest=other).retracement == 0.0


def test_a_new_extreme_is_the_impulse_reading():
    """`extends` is `crash-timing.md`'s `impulse`, measured there at AUC 0.562
    at 15m and nothing at 1h or 1d. Exposed so a study reuses that reading
    rather than re-deriving it."""
    base = pivot(-1, 100.0, 0.0, HOUR)
    high = pivot(+1, 110.0, HOUR, 2 * HOUR)
    beyond = pivot(-1, 95.0, 2 * HOUR, 3 * HOUR)
    short = pivot(-1, 104.0, 2 * HOUR, 3 * HOUR)

    assert Shape(*legs_from([base, high, beyond])).extends() is True
    assert Shape(*legs_from([base, high, short])).extends() is False


def test_two_same_side_pivots_are_reported_rather_than_corrected():
    """A reach that admits a tie can place them, and a caller filtering on
    `alternates` is making a choice rather than fixing a bug."""
    same = legs_from(
        [pivot(-1, 100.0, 0.0, 1.0), pivot(+1, 110.0, HOUR, 2.0), pivot(+1, 112.0, 2 * HOUR, 3.0)]
    )
    assert Shape(prior=same[0], latest=same[1]).alternates is False


# -------------------------------------------- the lie about asymmetry being structure


def test_a_gaussian_walk_produces_no_systematic_leg_asymmetry():
    """**The control, and it corrected a claim of mine.**

    `fear-greed.md` measured up legs 21% longer in bars and down legs 33%
    faster per bar, audusd at z -4.56 and negative in 6 of 6 eras - and found
    a memory-free **bar shuffle of the real series** reproduced it on all
    fourteen instruments at 80 draws.

    I first wrote this test asserting a Gaussian walk does the same. It does
    not: measured over 40 walks, up legs were longer on 17 and down legs
    faster on 16, with both holding on **11 of 40** - a coin flip.

    Which sharpens the finding rather than weakening it. A bar shuffle
    preserves the real return distribution's skewness; a Gaussian walk has
    none. So the asymmetry lives in the **shape of the return distribution**,
    not in the path order and not in volatility clustering - which is what
    that study independently concluded when Gaussian GARCH read -0.093 to
    +0.081 across all fourteen.

    The consequence for anything built on it: a per-side leg parameter fits a
    real distributional asymmetry that carries no information about which leg
    comes next.
    """
    both = 0
    for seed in range(20):
        sided = fed(walk(bars=600, seed=seed), reach=3, span=240, keep=64).sided()
        longer = sided.get("up_bars", 0.0) > sided.get("down_bars", 0.0)
        faster = sided.get("down_speed", 0.0) > sided.get("up_speed", 0.0)
        both += longer and faster

    assert 1 <= both <= 14, (
        f"both held on {both} of 20 Gaussian walks. Measured at 11 of 40, so a "
        f"reading at either extreme means the walk fixture has acquired a skew "
        f"it should not have, and the control is no longer a control."
    )


def test_the_sides_are_reported_apart():
    """Pooling would hide a real asymmetry that happens to carry no path
    information, which is worth seeing rather than averaging away."""
    sided = fed(walk(bars=600), reach=3, span=240, keep=64).sided()
    assert {"up_n", "up_extent", "up_bars", "up_speed"} <= set(sided)
    assert {"down_n", "down_extent", "down_bars", "down_speed"} <= set(sided)


def test_a_side_with_no_legs_is_absent_rather_than_zero():
    """Zero legs and legs averaging zero are different statements."""
    found = Zigzag(reach=3, span=60)
    found.legs = [Leg(side=+1, start=100.0, end=110.0, began=0.0, ended=HOUR, confirmed=2 * HOUR)]
    sided = found.sided()
    assert sided["up_n"] == 1.0
    assert "down_n" not in sided


# --------------------------------------------------------------- the asymmetry knob


def test_the_reach_may_differ_per_side():
    """Through `Sided`, so the geometric mean is unchanged and switching the
    asymmetry on cannot move the average detection scale."""
    found = Zigzag(reach=Sided(3.0, 4.0), span=240)
    assert found.reach.for_side(1) == pytest.approx(6.0)
    assert found.reach.for_side(-1) == pytest.approx(1.5)


def test_a_tilt_of_one_is_exactly_the_scalar():
    """A capability whose neutral setting is not neutral reparameterises every
    existing deployment."""
    bars = walk(bars=300)
    plain = fed(bars, reach=3, span=240)
    neutral = fed(bars, reach=Sided(3.0, 1.0), span=240)
    assert [leg.ended for leg in plain.legs] == [leg.ended for leg in neutral.legs]
    assert [leg.extent for leg in plain.legs] == [leg.extent for leg in neutral.legs]


def test_two_reaches_are_told_apart_by_the_identity():
    assert repr(Zigzag(reach=3)) != repr(Zigzag(reach=Sided(3.0, 4.0)))


# ---------------------------------------------------------------- the plumbing


def test_a_window_too_short_for_a_confirmation_is_refused():
    """It would publish nothing for ever while reading as configured."""
    with pytest.raises(ValueError, match="cannot hold a pivot"):
        Zigzag(reach=10, span=12)


def test_an_inverted_bar_is_refused_rather_than_folded():
    found = fed(walk(bars=300))
    before = [leg.ended for leg in found.legs]
    found.update_raw(90.0, 110.0, found.when + HOUR)
    assert [leg.ended for leg in found.legs] == before


def test_the_book_is_capped():
    """`keep` bounds it, checked on the live object rather than the
    declaration - `restore-drops-deque-maxlen` is the recorded failure."""
    found = fed(walk(bars=1200), reach=2, span=240, keep=8)
    assert len(found.legs) <= 8


def test_a_reset_forgets_the_legs_and_the_window():
    found = fed(walk(bars=300))
    assert found.legs
    found.reset()

    assert found.legs == []
    assert found.forming() is None
    assert found.has_inputs is False


def test_registering_it_for_quotes_says_why_not():
    with pytest.raises(NotImplementedError, match="register_indicator_for_bars"):
        Zigzag().handle_quote_tick(object())


# ------------------------------------------- one leg ahead, and it refuses itself


def forecast_on(seed: int, gain: float = 0.2, unit: float = 0.3) -> tuple[Forecast, Zigzag]:
    found, ahead, seen = Zigzag(reach=3, span=240, keep=64), Forecast(gain=gain), 0
    for high, low, when in walk(bars=900, seed=seed):
        found.update_raw(high, low, when)
        if len(found.legs) > seen:
            for leg in found.legs[seen - len(found.legs) :]:
                ahead.observe(leg, unit)
            seen = len(found.legs)
    return ahead, found


def test_the_side_is_determined_and_not_predicted():
    """A zigzag alternates by construction, so the next leg must face the
    other way. There is no forecasting content in saying so, which is why
    `side` is carried and never scored."""
    ahead, found = forecast_on(7)
    pred = ahead.predict(found.latest)
    assert pred.side == -found.latest.side


def test_the_forecast_carries_its_own_error_as_an_interval():
    """A point forecast with no error is not a probabilistic statement, and
    magnitude with an interval is what sizing and stops consume."""
    ahead, found = forecast_on(7)
    pred = ahead.predict(found.latest)
    low, high = pred.interval(1.0)

    assert pred.error > 0.0
    assert low == pytest.approx(max(0.0, pred.extent - pred.error))
    assert high == pytest.approx(pred.extent + pred.error)


def test_an_interval_cannot_go_negative():
    """An extent is a distance, so a negative bound is a different quantity
    rather than a wider interval."""
    pred = Prediction(side=1, extent=0.5, error=2.0, n=10)
    assert pred.interval(1.0)[0] == 0.0


def test_the_correction_reads_no_skill_on_a_walk():
    """**The test that can refuse the whole object.** Leg extents on a walk
    are exchangeable given the threshold, so the running mean is the optimal
    forecast and an adaptive estimate should earn nothing. A positive skill
    here would mean the estimator is measuring its own fitting."""
    scores = []
    for seed in range(6):
        ahead, _ = forecast_on(seed)
        scores += [s for s in (ahead.skill(1), ahead.skill(-1)) if s is not None]

    assert scores, "no skill was scored at all"
    assert abs(sum(scores) / len(scores)) < 0.15, scores


def test_the_error_is_scored_one_step_ahead_and_out_of_sample():
    """Scored *before* the leg is folded in. Folding first would score the
    estimate against a leg it had already seen, which is how a predictor comes
    to look accurate."""
    ahead = Forecast(gain=0.5)
    first = Leg(side=1, start=100.0, end=103.0, began=0.0, ended=HOUR, confirmed=2 * HOUR)
    ahead.observe(first, unit=1.0)
    assert ahead.skill(1) is None, "one leg produces no out-of-sample error"

    ahead.observe(
        Leg(side=1, start=100.0, end=109.0, began=0.0, ended=HOUR, confirmed=2 * HOUR), 1.0
    )
    assert ahead.skill(1) is not None


def test_a_leg_with_no_usable_unit_is_skipped():
    """Folding at price scale would put a gold leg and a eurusd leg in one
    mean."""
    ahead = Forecast()
    ahead.observe(
        Leg(side=1, start=100.0, end=110.0, began=0.0, ended=HOUR, confirmed=2 * HOUR), 0.0
    )
    assert (
        ahead.predict(Leg(side=-1, start=0.0, end=0.0, began=0.0, ended=0.0, confirmed=0.0)) is None
    )


def test_the_two_sides_are_forecast_apart():
    ahead, _ = forecast_on(7)
    assert ahead.state[1]["estimate"] != ahead.state[-1]["estimate"]


def test_a_gain_outside_its_range_is_refused():
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="not a correction weight"):
            Forecast(gain=bad)


# ---------------------------------------------------- which prices a turn reads


def bodies(
    bars: list[tuple[float, float, float]], seed: int = 3
) -> list[tuple[float, float, float, float, float]]:
    """`(open, high, low, close, when)` with the body placed asymmetrically.

    **Asymmetrically, because a centred body changes nothing.** A body centred
    in the range is a monotone transform of the midpoint series, so it turns on
    exactly the same bars whatever its width - measured at body shares of 0.1,
    0.5 and 0.9, all giving identical pivot times. The two sources diverge only
    when the body sits off-centre, which is what a real bar does when price
    runs a high and closes near its low.

    An earlier version alternated the offset every bar, which manufactured
    turns in the body series. This draws it independently.
    """
    rng = random.Random(seed)
    out = []
    for high, low, when in bars:
        span = high - low
        top = low + span * rng.uniform(0.45, 0.95)
        bottom = low + span * rng.uniform(0.05, 0.45)
        out.append((bottom, high, low, top, when))
    return out


def test_the_two_sources_do_not_find_the_same_legs():
    """**The property that matters, and the only one that holds in general.**
    A wick is where price traded and failed; a body is where it settled. Which
    is read changes what the legs are, so a study must say which it used.

    Which source is *quieter* is a fact about the data rather than the
    detectors - it depends on how the body sits in the range - so it is not
    asserted. Measured while writing this: a centred body of any width gives
    identical turns, and a body alternating above and below the midpoint makes
    the body series the *noisier* of the two.
    """
    built = bodies(walk(bars=600))
    extreme = Zigzag(reach=3, span=240, keep=64, source=Source.EXTREME)
    body = Zigzag(reach=3, span=240, keep=64, source=Source.BODY)
    for open_, high, low, close, when in built:
        extreme.update_raw(high, low, when, open_=open_, close=close)
        body.update_raw(high, low, when, open_=open_, close=close)

    assert extreme.legs, "the extreme detector found nothing, so nothing is compared"
    assert body.legs, "the body detector found nothing, so nothing is compared"
    assert [leg.ended for leg in extreme.legs] != [leg.ended for leg in body.legs]


def test_a_body_zigzag_refuses_a_bar_without_its_body():
    """**Rather than silently reading the extremes.** A detector quietly
    answering a different question is the failure this module is written
    against - the wick is where price traded and failed, the body is where it
    settled, and they are not the same turn."""
    with pytest.raises(ValueError, match="needs the open and the close"):
        Zigzag(source=Source.BODY).update_raw(101.0, 99.0, 0.0)


def test_the_extreme_source_ignores_a_body_it_is_given():
    """So feeding one detector's bars to the other cannot change its answer."""
    bars = walk(bars=300)
    plain = fed(bars, reach=3, span=240, keep=64)

    withbody = Zigzag(reach=3, span=240, keep=64, source=Source.EXTREME)
    for high, low, when in bars:
        withbody.update_raw(high, low, when, open_=low, close=high)

    assert [leg.ended for leg in plain.legs] == [leg.ended for leg in withbody.legs]


def test_two_sources_are_told_apart_by_the_identity():
    assert repr(Zigzag(source=Source.EXTREME)) != repr(Zigzag(source=Source.BODY))


# ------------------------------------- what the next leg's forecast carries


def test_the_prediction_carries_duration_impulse_and_a_velocity():
    """Direction, how long, whether it makes a new extreme, and how fast -
    with the velocity **derived** from extent and span rather than forecast
    separately, because two estimates of a ratio and its parts would disagree
    silently."""
    ahead, found = forecast_on(7)
    for index in range(1, len(found.legs)):
        ahead.observe(
            found.legs[index],
            0.3,
            extended=Shape(prior=found.legs[index - 1], latest=found.legs[index]).extends(),
        )
    pred = ahead.predict(found.latest)

    assert pred.span > 0.0
    assert 0.0 <= pred.impulse <= 1.0
    assert pred.bars(3_600.0) == pytest.approx(pred.span / 3_600.0)
    assert pred.speed() == pytest.approx(pred.extent / (pred.span / 3_600.0))


def test_a_velocity_needs_a_duration():
    """Zero rather than a division, since a leg spanning no time is real at a
    small reach."""
    assert Prediction(side=1, extent=2.0, error=0.1, n=5, span=0.0).speed() == 0.0
    assert Prediction(side=1, extent=2.0, error=0.1, n=5, span=0.0).bars(3_600.0) == 0.0


def test_impulse_stays_zero_when_it_is_never_observed():
    """It is optional on `observe`, so a caller not tracking new extremes gets
    a zero rate rather than a fabricated one."""
    ahead, found = forecast_on(7)
    pred = ahead.predict(found.latest)
    assert pred.impulse == 0.0
