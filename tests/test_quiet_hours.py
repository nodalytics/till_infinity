"""No new positions while the broker's quotes are widest.

Predicted from the spread and only then checked against outcomes, which is the
ordering that makes it a finding rather than the worst of twenty-four hours picked
after the fact. Median spread at 21:00 UTC is 15.4x the day's median, 10.7x at 22:00
and 2.5x at 23:00; 142 of 989 closed trades were opened between 20:00 and 23:00 and
they carry -661 of the -1,470 total loss.
"""

from __future__ import annotations

import datetime as dt

from till_infinity.trading import Settings
from till_infinity.trading.models import Intent, Side
from till_infinity.trading.risk import Guard


def at(hour: int) -> float:
    """A timestamp at this UTC hour, on a fixed day."""
    return dt.datetime(2026, 9, 20, hour, 30, tzinfo=dt.UTC).timestamp()


def desk(**over) -> Guard:
    made = Settings()
    for k, v in over.items():
        setattr(made, k, v)
    guard = Guard(made, currency="USD")
    guard.roll(10_000.0, now=at(9))
    return guard


def intent() -> Intent:
    return Intent(
        feed="gold",
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.05,
        entry=4400.0,
        stop=4390.0,
        target=4420.0,
        interval="15m",
        risk_money=22.0,
    )


class TestTheGate:
    def test_it_refuses_inside_a_quiet_hour(self):
        guard = desk(quiet_hours=(20, 21, 22, 23))
        for hour in (20, 21, 22, 23):
            stopped = guard.allows(intent(), positions=[], now=at(hour))
            assert stopped is not None, hour
            assert stopped.gate == "quiet_hour", (hour, stopped.gate)
            assert f"{hour:02d}:00" in stopped.detail, stopped.detail

    def test_it_allows_every_other_hour(self):
        guard = desk(quiet_hours=(20, 21, 22, 23))
        for hour in (0, 6, 9, 13, 19):
            stopped = guard.allows(intent(), positions=[], now=at(hour))
            assert stopped is None or stopped.gate != "quiet_hour", (hour, stopped)

    def test_empty_means_every_hour_trades(self):
        """Off by default. The window is measured on one broker's quoting, and
        another's rollover sits elsewhere."""
        assert Settings().quiet_hours == ()
        guard = desk()
        for hour in range(24):
            stopped = guard.allows(intent(), positions=[], now=at(hour))
            assert stopped is None or stopped.gate != "quiet_hour", hour

    def test_it_is_checked_before_the_signal_is_examined(self):
        """It is a fact about the clock, so it should not cost the arithmetic. A
        refusal here names the hour rather than whatever the signal happened to be
        weakest at."""
        guard = desk(quiet_hours=(21,), min_reward_to_risk=99.0)
        stopped = guard.allows(intent(), positions=[], now=at(21))
        assert stopped is not None
        assert stopped.gate == "quiet_hour", stopped.gate

    def test_a_halt_still_outranks_it(self):
        """The day's stop is the more important fact and is checked first."""
        guard = desk(quiet_hours=(21,))
        guard.halted = "the day is done"
        stopped = guard.allows(intent(), positions=[], now=at(21))
        assert stopped is not None
        assert stopped.gate == "halted", stopped.gate

    def test_the_refusal_is_counted_like_every_other_gate(self):
        guard = desk(quiet_hours=(21,))
        guard.allows(intent(), positions=[], now=at(21))
        guard.allows(intent(), positions=[], now=at(21))
        assert guard.refusals.get("quiet_hour") == 2, guard.refusals


class TestTheSetting:
    def test_it_ignores_nonsense_rather_than_refusing_to_start(self):
        """A typo in an environment variable must not stop the desk trading - the
        mistake a mis-set base-rate floor already made here once."""
        import os

        keep = os.environ.get("TRADING_QUIET_HOURS")
        try:
            os.environ["TRADING_QUIET_HOURS"] = "20, 21, banana, 99, -3, 23"
            got = Settings.from_env().quiet_hours
            assert got == (20, 21, 23), got
        finally:
            if keep is None:
                os.environ.pop("TRADING_QUIET_HOURS", None)
            else:
                os.environ["TRADING_QUIET_HOURS"] = keep
