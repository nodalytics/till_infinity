"""The options book, and the assumption that must not be baked in."""

from __future__ import annotations

import pytest

from till_infinity.prices import options


def _row(strike, kind, oi=100.0, gamma=0.0002, spot=80_000.0, expiry=1_800_000_000_000):
    """A ccxt option row shaped the way Deribit returns one."""
    return {
        "symbol": f"BTC-{int(strike)}-{kind[0].upper()}",
        "strike": strike,
        "optionType": kind,
        "openInterest": oi,
        "expiry": expiry,
        "timestamp": 1_788_000_000_000,
        "greeks": {"gamma": gamma},
        "info": {"underlying_price": spot, "mark_iv": 55.0},
    }


class _Exchange:
    def __init__(self, board, has=True):
        self.has = {"fetchOptionChain": has}
        self._board = board

    async def fetch_option_chain(self, underlying):
        return self._board


# ------------------------------------------------------------ the observation


def test_gamma_size_is_unsigned_because_that_part_is_a_fact():
    """Who holds the open interest is not published. Signing it here would turn
    an observation into a guess wearing an observation's units."""
    one = options.Strike(
        feed="btc",
        underlying="BTC",
        strike=80_000.0,
        expiry=0.0,
        kind="call",
        open_interest=100.0,
        gamma=0.0002,
        spot=80_000.0,
    )

    assert one.gamma_size == pytest.approx(0.02)
    assert one.gamma_size > 0
    assert one.notional_gamma == pytest.approx(0.02 * 80_000**2 * 0.01)


def test_the_dealer_sign_is_a_parameter_with_a_stated_default():
    """Every "GEX" chart assumes dealers are short calls and long puts. On
    crypto, where covered-call selling is a large share of the flow, that is
    arguably backwards - so it is a parameter, not arithmetic in a sum."""
    assert options.dealer_sign("call") == -1
    assert options.dealer_sign("put") == 1
    assert options.dealer_sign("call", dealers_short_calls=False) == 1
    assert options.dealer_sign("put", dealers_short_calls=False) == -1


def test_moneyness_is_signed_so_the_side_survives():
    below = options.Strike(
        feed="btc",
        underlying="BTC",
        strike=72_000.0,
        expiry=0.0,
        kind="put",
        open_interest=1.0,
        spot=80_000.0,
    )

    assert below.moneyness == pytest.approx(-0.1)


# ------------------------------------------------------------- the collection


async def test_a_far_out_strike_is_dropped():
    """A 200%-out-of-the-money strike has a gamma indistinguishable from zero
    and an open interest that is somebody's lottery ticket."""
    board = [_row(80_000, "call"), _row(200_000, "call")]

    got = await options.chain(_Exchange(board), {"BTC": "btc"})

    assert [s.strike for s in got] == [80_000.0]


async def test_a_strike_nobody_holds_is_dropped():
    board = [_row(80_000, "call", oi=0.0), _row(81_000, "call", oi=50.0)]

    got = await options.chain(_Exchange(board), {"BTC": "btc"})

    assert [s.strike for s in got] == [81_000.0]


async def test_the_spot_comes_from_the_board_not_a_second_call():
    """Two calls would put the moneyness of a fast underlying a few seconds
    out - the kind of small wrongness that survives review."""
    got = await options.chain(_Exchange([_row(80_000, "call")]), {"BTC": "btc"})

    assert got[0].spot == 80_000.0
    assert got[0].moneyness == 0.0


async def test_an_exchange_without_a_chain_returns_nothing():
    got = await options.chain(_Exchange([_row(80_000, "call")], has=False), {"BTC": "btc"})

    assert got == []


# ---------------------------------------------------------------- the profile


def _strike(k, kind, gamma=0.0002, oi=100.0, spot=80_000.0):
    return options.Strike(
        feed="btc",
        underlying="BTC",
        strike=k,
        expiry=0.0,
        kind=kind,
        open_interest=oi,
        gamma=gamma,
        spot=spot,
        time=1.0,
    )


def test_the_profile_is_a_distribution_rather_than_a_number():
    """The single figure everyone quotes is a sum over a distribution, and the
    distribution is the part with information in it."""
    got = options.profile([_strike(79_000, "put"), _strike(81_000, "call")])

    assert len(got) == 1
    assert sorted(got[0].by_strike) == [79_000.0, 81_000.0]
    # Under the default convention: long put gamma, short call gamma.
    assert got[0].by_strike[79_000.0] > 0
    assert got[0].by_strike[81_000.0] < 0


def test_the_peak_is_the_strike_hedging_clusters_at():
    got = options.profile([_strike(79_000, "put", oi=10.0), _strike(78_000, "put", oi=900.0)])

    assert got[0].peak == 78_000.0


def test_the_flip_is_none_when_the_sign_never_changes():
    """ "No flip" has to read as absent rather than as a price."""
    got = options.profile([_strike(79_000, "put"), _strike(78_000, "put")])

    assert got[0].flip() is None


def test_the_flip_is_found_where_the_running_total_crosses():
    got = options.profile([_strike(78_000, "put", oi=100.0), _strike(82_000, "call", oi=900.0)])

    assert got[0].flip() == 82_000.0


def test_flipping_the_assumption_flips_the_profile():
    """The whole reason it is a parameter: the answer depends on it, so a
    reader has to be able to see which way it was set."""
    strikes = [_strike(79_000, "put"), _strike(81_000, "call")]

    usual = options.profile(strikes)[0]
    other = options.profile(strikes, dealers_short_calls=False)[0]

    assert usual.total == pytest.approx(-other.total)
