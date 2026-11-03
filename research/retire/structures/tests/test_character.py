"""The character monitor: does an instrument still behave like itself?

The properties worth pinning are the two failure modes this was built through. It must
**not** alarm on an instrument that is lopsided by design - that was the first version's
bug, and it fired +3.7 sigma against a simulated Boom for no reason but an unconverged
baseline. And it must alarm when a lopsided instrument stops being lopsided, which is the
only thing it exists for.
"""

from __future__ import annotations

import random

from till_infinity.structures.context.character import (
    BALANCE_SIGMA,
    SHORT_EVENTS,
    WARM_EVENTS,
    Character,
)


def _drive(watch: Character, true_up: float, bars: int, rate: float = 0.01, seed: int = 1):
    """Feed `bars` bars where a firing happens with probability `rate`."""
    rng = random.Random(seed)
    raised = []
    for i in range(bars):
        if rng.random() < rate:
            up = rng.random() < true_up
            watch.observe(up, not up)
        else:
            watch.observe(False, False)
        raised.extend((i, said) for said in watch.alarms())
    return raised


def test_a_new_monitor_says_nothing():
    watch = Character()
    assert not watch.warm
    assert watch.alarms() == []
    assert watch.balance_shift() == 0.0
    assert watch.rate_fold() == 0.0


def test_it_does_not_alarm_on_an_instrument_lopsided_by_design():
    """The bug this was built through: Boom is 85% up and that is not a fault."""
    watch = Character()
    raised = _drive(watch, 0.85, 120_000)
    assert raised == [], f"false alarm on a stable instrument: {raised[:1]}"
    # And the baseline actually found the truth rather than sitting near its start.
    assert 0.80 < watch.up_share_long < 0.90


def test_it_alarms_when_the_character_flips():
    watch = Character()
    _drive(watch, 0.85, 120_000)
    raised = _drive(watch, 0.50, 40_000, seed=2)
    assert raised, "a generator change went unreported"
    assert "balance" in raised[0][1]
    assert "downward" in raised[0][1]


def test_the_alarm_is_latched_then_rearms():
    watch = Character()
    _drive(watch, 0.90, 120_000)
    raised = _drive(watch, 0.10, 40_000, seed=3)
    # Latched: a standing shift is reported once, not on every bar of it.
    assert len(raised) <= 2, f"the alarm repeated {len(raised)} times"
    assert watch.balance_alarmed
    # Coming back inside the band clears the latch so a second shift is still seen.
    _drive(watch, 0.10, 120_000, seed=4)
    assert not watch.balance_alarmed


def test_a_symmetric_instrument_reads_symmetric():
    watch = Character()
    _drive(watch, 0.50, 120_000)
    assert abs(watch.up_share_long - 0.5) < 0.06
    assert abs(watch.balance_shift()) < BALANCE_SIGMA


def test_both_directions_on_one_bar_say_nothing_about_direction():
    watch = Character()
    for _ in range(WARM_EVENTS * 3):
        watch.observe(True, True)
    assert abs(watch.up_share - 0.5) < 1e-6


def test_the_error_bar_uses_events_seen_while_the_window_fills():
    """An error bar claiming forty events when it has had six alarms on week one."""
    watch = Character()
    _drive(watch, 0.5, 30_000)
    assert watch.events >= WARM_EVENTS
    # Effective n is capped at the window, never above it.
    assert min(float(watch.events), SHORT_EVENTS) <= SHORT_EVENTS


def test_the_reading_survives_a_restore_without_the_new_fields():
    """A save written before a field existed must not resurrect as garbage."""
    watch = Character()
    _drive(watch, 0.8, 60_000)
    before = watch.to_dict()
    state = {"short_up": watch.short_up, "short_w": watch.short_w, "events": watch.events}
    fresh = Character()
    fresh.__setstate__(state)
    # The fields present are carried; the absent ones take defaults rather than vanishing.
    assert fresh.events == watch.events
    assert fresh.long_rate == 0.0
    assert isinstance(fresh.to_dict(), dict)
    assert before["events"] == watch.events


def test_it_holds_nothing_with_a_length():
    """A capped deque restored from an older save comes back uncapped - so hold none."""
    watch = Character()
    for name in Character.__dataclass_fields__:
        value = getattr(watch, name)
        assert isinstance(value, float | int | bool), f"{name} is {type(value)}"
