"""`identity-arb`: the arithmetic, the gap, and the staleness guard.

The measurement behind the rule is in `strategies/identity.py`. What is tested
here is the machinery that could be silently wrong: whether the implied rate is
composed in the right orientation, whether one episode produces one trade, and
whether a stale partner refuses rather than trades on an old price.
"""

from __future__ import annotations

import math

import pytest

from till_infinity.strategies.identity import TRIANGLES, Identity, IdentityProfile


def test_every_triangle_is_a_distinct_unordered_pair():
    """Twenty-one pairs from seven non-USD majors, each once."""
    assert len(TRIANGLES) == 21
    assert len({frozenset(t) for t in TRIANGLES}) == 21
    assert not any("USD" in t for t in TRIANGLES)


def test_the_orientation_is_inverted_only_when_the_pair_is_reversed():
    """`EURUSD` is USD per EUR; asked for EUR per USD it must invert.

    **This is the arithmetic the whole rule rests on.** A leg composed the
    wrong way round produces a residual that is a sum where it should be a
    difference, which still has a mean and an sd and still fires - so nothing
    downstream would notice.
    """
    flip = Identity._oriented
    assert flip("EURUSD", ("EUR", "USD"), 1.10) == pytest.approx(1.10)
    assert flip("EURUSD", ("USD", "EUR"), 1.10) == pytest.approx(1 / 1.10)
    assert flip("USDJPY", ("USD", "JPY"), 158.0) == pytest.approx(158.0)
    assert flip("USDJPY", ("JPY", "USD"), 158.0) == pytest.approx(1 / 158.0)
    #: A pair that shares no currency with what was asked for is not a leg.
    assert flip("EURUSD", ("GBP", "USD"), 1.10) is None
    #: A non-positive price cannot be inverted.
    assert flip("EURUSD", ("USD", "EUR"), 0.0) is None


def test_the_implied_rate_composes_to_the_cross():
    """`EURJPY = EURUSD x USDJPY`, exactly, so a consistent triangle has a
    residual of zero. Checked by arithmetic rather than by the rule, because
    this is the identity the rule claims to measure."""
    eurusd, usdjpy = 1.10, 158.0
    implied = Identity._oriented("EURUSD", ("EUR", "USD"), eurusd) * Identity._oriented(
        "USDJPY", ("USD", "JPY"), usdjpy
    )
    assert implied == pytest.approx(eurusd * usdjpy)
    assert math.log(eurusd * usdjpy) - math.log(implied) == pytest.approx(0.0)

    #: And a cross quoted the other way round still composes.
    #: `CHFJPY = USDJPY / USDCHF`, so the USDCHF leg inverts.
    usdchf = 0.82
    chf_jpy = Identity._oriented("USDCHF", ("CHF", "USD"), usdchf) * Identity._oriented(
        "USDJPY", ("USD", "JPY"), usdjpy
    )
    assert chf_jpy == pytest.approx(usdjpy / usdchf)


def test_only_a_cross_gets_a_triangle_and_a_usd_leg_declines():
    """The traded leg is the cross: its direction follows from the arithmetic.
    A USD leg belongs to several triangles with no way to choose, so a desk on
    one must decline rather than pick."""

    def trio_for(symbol: str):
        desk = Identity.__new__(Identity)
        desk._cfg = type(
            "C",
            (),
            {"instrument_id": type("I", (), {"symbol": type("S", (), {"value": symbol})()})()},
        )()
        return Identity._trio(desk)

    #: **The venue's own names, ordered by the traded symbol.** `JPYUSD` and
    #: `CHFUSD` do not exist - the venue lists `USDJPY` and `USDCHF` - and the
    #: first partner must be the base's leg because `_residual` asks it for
    #: `(base, USD)`. Both were wrong in the first cut and both read as a
    #: quiet desk rather than a broken one.
    assert trio_for("EURJPY") == ("EURJPY", "EURUSD", "USDJPY")
    assert trio_for("CHFJPY") == ("CHFJPY", "USDCHF", "USDJPY")
    assert trio_for("EURGBP") == ("EURGBP", "EURUSD", "GBPUSD")
    #: A USD leg, a non-pair and an unlisted combination all decline.
    assert trio_for("EURUSD") is None
    assert trio_for("USDJPY") is None
    assert trio_for("XAUUSD") is None
    assert trio_for("Volatility 75 (1s) Index") is None


def test_the_gap_is_the_horizon_so_one_episode_is_one_trade():
    """**The number that mattered most in the measurement.** Entering on every
    qualifying bar inflated the backtest's edge by 63% - from +2.47 to +6.71 -
    and destroyed the independence behind its `t`. A run above the threshold is
    one episode."""
    assert IdentityProfile.gap_bars == IdentityProfile.hold_bars, (
        "the gap must be the horizon, or the forward windows overlap"
    )
    assert IdentityProfile.gap_bars > 0


def test_the_pre_specified_numbers_are_the_measured_ones():
    """Nothing here was tuned after the measurement. `entry_z` is the harness's
    `ENTRY`, the window is the five days the z was measured over, and the hold
    is the 24 hours the edge was measured at."""
    assert IdentityProfile.entry_z == 3.0
    assert IdentityProfile.window == 480
    assert IdentityProfile.hold_bars == 96
    assert IdentityProfile.stale_bars == 2


def test_the_residual_is_zero_on_a_consistent_triangle_and_signed_when_it_is_not():
    """**The end-to-end check the two naming bugs slipped past.**

    `_oriented` was right and `_trio` handed it legs in the wrong order under
    the venue's wrong names, so `_residual` returned `None` for every triangle
    whose table entry was reversed. Each unit was defensible; the composition
    was dead. This drives the real method.
    """
    desk = Identity.__new__(Identity)
    desk._cfg = type(
        "C",
        (),
        {"instrument_id": type("I", (), {"symbol": type("S", (), {"value": "CHFJPY"})()})()},
    )()
    desk.trio = Identity._trio(desk)
    desk.bars_seen = 10
    desk.tally = {"bars": 0, "resid": 0, "fired": 0, "stale": 0, "gapped": 0, "cold": 0}

    usdchf, usdjpy = 0.82, 158.0
    desk.partners = {"USDCHF": (usdchf, 10.0), "USDJPY": (usdjpy, 10.0)}

    #: A perfectly consistent cross: CHFJPY = USDJPY / USDCHF.
    consistent = usdjpy / usdchf
    assert Identity._residual(desk, consistent) == pytest.approx(0.0, abs=1e-12)

    #: Rich by 10 bp, and the residual says so with a positive sign - which is
    #: the sign the rule sells on.
    rich = consistent * 1.0010
    got = Identity._residual(desk, rich)
    assert got is not None
    assert got == pytest.approx(math.log(1.0010), abs=1e-12)
    assert got > 0

    #: Cheap reads negative.
    assert Identity._residual(desk, consistent * 0.9990) < 0


def test_a_stale_partner_refuses_rather_than_trades_on_an_old_price():
    """A partner quote that has not moved makes the triangle look deviated and
    "revert" when it updates. That is the stale-quote explanation the original
    measurement tested with its entry delay, and it is measurement noise, not
    an inefficiency - so an old leg refuses outright."""
    desk = Identity.__new__(Identity)
    desk._cfg = type(
        "C",
        (),
        {"instrument_id": type("I", (), {"symbol": type("S", (), {"value": "CHFJPY"})()})()},
    )()
    desk.trio = Identity._trio(desk)
    desk.tally = {"bars": 0, "resid": 0, "fired": 0, "stale": 0, "gapped": 0, "cold": 0}
    desk.bars_seen = 100

    fresh = 100.0 - IdentityProfile.stale_bars
    desk.partners = {"USDCHF": (0.82, fresh), "USDJPY": (158.0, fresh)}
    assert Identity._residual(desk, 158.0 / 0.82) is not None

    #: One bar older than the guard allows, and it is refused and counted.
    desk.partners = {"USDCHF": (0.82, fresh - 1), "USDJPY": (158.0, 100.0)}
    assert Identity._residual(desk, 158.0 / 0.82) is None
    assert desk.tally["stale"] == 1

    #: A partner never seen is counted apart from a stale one: a cold start and
    #: a dead feed are different problems.
    desk.partners = {"USDJPY": (158.0, 100.0)}
    assert Identity._residual(desk, 158.0 / 0.82) is None
    assert desk.tally["cold"] == 1
