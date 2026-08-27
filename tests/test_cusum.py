"""The CUSUM filter, and the properties that make it more than a running total."""

from __future__ import annotations

from till_infinity.structures.cusum import Cusum


def _run(prices, unit=1.0, threshold=2.0):
    filt = Cusum(threshold=threshold)
    return filt, filt.feed(list(range(len(prices))), [float(p) for p in prices], unit)


def test_a_steady_climb_fires_upward():
    _, events = _run([100, 100.5, 101, 101.5, 102, 102.5])
    assert events
    assert events[0].side == "up"


def test_a_fall_fires_downward():
    _, events = _run([100, 99.5, 99, 98.5, 98])
    assert events
    assert events[0].side == "down"


def test_nothing_fires_below_the_threshold():
    _, events = _run([100, 100.2, 100.4, 100.3, 100.5, 100.4])
    assert events == []


def test_the_accumulator_never_goes_negative():
    """The floor is the whole mechanism: an upward accumulator can be *held*
    at zero by movement the other way, never driven below it. Without that
    this is a running total of price, which is price."""
    filt, _ = _run([100, 95, 94, 93, 92])
    assert filt.up >= 0.0
    assert filt.down <= 0.0


def test_a_drift_the_other_way_does_not_pay_down_progress_indefinitely():
    """Up 1.5, then down 5, then up 1.5 again. If the up accumulator had gone
    negative on the fall, the second climb would start from a deficit and the
    move would not register."""
    filt = Cusum(threshold=2.0)
    for price in (100, 101.5, 96.5, 98.0):
        filt.push(float(price), unit=1.0)
    # The fall fires downward; what matters is `up` is floored, not negative.
    assert filt.up >= 0.0


def test_firing_resets_both_accumulators():
    """One move produces one signal. The next requires the market to do the
    work again - otherwise every bar after the first event is an event."""
    filt = Cusum(threshold=2.0)
    filt.push(100.0, unit=1.0)
    filt.push(103.0, unit=1.0)  # fires
    assert filt.up == 0.0
    assert filt.down == 0.0


def test_one_move_is_one_event_not_one_per_bar():
    _, events = _run([100, 103, 103.1, 103.2, 103.15, 103.2])
    assert len(events) == 1


def test_the_threshold_is_in_volatility_units():
    """The same series is an event on a quiet instrument and noise on a loud
    one. A fixed price threshold would describe the instrument, not the market."""
    prices = [100, 100.5, 101, 101.5, 102, 102.5]
    assert _run(prices, unit=1.0)[1] != []
    assert _run(prices, unit=50.0)[1] == []


def test_a_zero_volatility_unit_fires_nothing():
    """Dividing by it would make every change infinite."""
    _, events = _run([100, 105, 110], unit=0.0)
    assert events == []


def test_the_first_price_only_establishes_a_baseline():
    """There is no change to accumulate until there are two prices."""
    filt = Cusum()
    assert filt.push(100.0, unit=1.0) is None


def test_pressure_reads_between_events():
    """For anything wanting a continuous measure rather than a trigger."""
    filt = Cusum(threshold=5.0)
    filt.push(100.0, unit=1.0)
    filt.push(101.0, unit=1.0)
    assert filt.pressure > 0
    filt.push(99.0, unit=1.0)
    assert filt.pressure < filt.up + 1e-9


def test_a_slow_accumulation_and_a_fast_one_both_register():
    """The point of having no window: twelve small pushes and one large push
    are the same total, and a mean over a fixed lookback sees only one."""
    slow = _run([100 + i * 0.2 for i in range(12)])[1]
    fast = _run([100, 102.5])[1]
    assert slow
    assert fast
    assert slow[0].side == fast[0].side == "up"
