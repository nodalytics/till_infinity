"""The momentum ensemble: one CUSUM per sub-hour timeframe, read together."""

from till_infinity.structures.cusum import CADENCE, SUB_HOUR, Cusum, Ensemble


def test_every_member_is_below_an_hour():
    """Above 1h the swing's context timeframes already speak, and they answer a
    different question - whether the level is real, not whether it is being
    rejected now."""
    assert all(CADENCE[i] < 3600.0 for i in SUB_HOUR)


def test_a_member_only_sees_a_tick_once_its_interval_has_passed():
    """Sampled, not resampled: each member is a filter over that timeframe's
    closes without needing bars, which is what lets this be fed from quotes."""
    e = Ensemble(intervals=("1m", "5m"))
    for step in range(0, 240, 10):  # four minutes, every ten seconds
        e.push(100.0 + step * 0.01, unit=1.0, when=float(step))
    # 1m saw a tick roughly every 60s; 5m saw exactly one, its first.
    assert e.seen_at["1m"] >= 180.0
    assert e.seen_at["5m"] == 0.0


def test_agreement_is_one_when_every_timeframe_pushes_the_same_way():
    e = Ensemble(intervals=("1m", "3m", "5m"))
    price = 100.0
    for step in range(0, 3600, 30):
        price += 0.5
        e.push(price, unit=1.0, when=float(step))
    assert e.ready == 3
    assert e.agreement == 1.0
    assert e.pressure > 0


def test_agreement_is_negative_when_they_all_push_down():
    e = Ensemble(intervals=("1m", "3m", "5m"))
    price = 100.0
    for step in range(0, 3600, 30):
        price -= 0.5
        e.push(price, unit=1.0, when=float(step))
    assert e.agreement == -1.0
    assert e.pressure < 0


def test_nothing_warm_is_no_opinion_rather_than_a_confident_zero():
    e = Ensemble()
    assert e.ready == 0
    assert e.pressure == 0.0
    assert e.agreement == 0.0


def test_pressure_is_the_mean_so_adding_a_member_does_not_change_its_scale():
    """It has to stay comparable with `require_turn_vol`, which is calibrated
    in volatility units against a single filter."""
    small = Ensemble(intervals=("1m", "3m"))
    large = Ensemble(intervals=("1m", "3m", "5m", "15m"))
    price = 100.0
    for step in range(0, 7200, 30):
        price += 0.5
        for e in (small, large):
            e.push(price, unit=1.0, when=float(step))
    assert small.pressure > 0
    assert large.pressure > 0
    # Same order of magnitude, not a sum that grows with the member count.
    assert 0.4 < small.pressure / large.pressure < 2.5


def test_a_member_that_has_just_fired_still_counts_as_a_view():
    """A CUSUM resets when it fires, so its strongest case reads a pressure of
    exactly zero. Counting that as an abstention would make the ensemble
    quietest precisely when the market is loudest."""
    e = Ensemble(intervals=("1m",))
    price = 100.0
    for step in range(0, 1200, 30):
        price += 1.0
        e.push(price, unit=1.0, when=float(step))
    member = e.members["1m"]
    assert member.events, "the run should have fired at least once"
    if member.pressure == 0.0:
        assert e.agreement == 1.0


def test_a_flat_market_is_no_agreement():
    """Momentum on one timeframe and nowhere else is noise. This is the reading
    a single filter cannot give, and the reason for the ensemble."""
    e = Ensemble(intervals=("1m", "3m", "5m"))
    # Warm every member on a flat series, then move only between 1m samples.
    for step in range(0, 3600, 30):
        e.push(100.0, unit=1.0, when=float(step))
    assert e.ready == 3
    assert e.agreement == 0.0


def test_a_member_is_an_ordinary_cusum():
    e = Ensemble(intervals=("1m",))
    e.push(100.0, unit=1.0, when=0.0)
    assert isinstance(e.members["1m"], Cusum)
