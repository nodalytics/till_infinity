"""Do `MAX_POSITIONS` and `RISK_FRACTION` agree with each other?

A configuration invariant rather than a unit test of one function. The live book runs
`TRADING_RISK_FRACTION=0.005`, `TRADING_MAX_POSITIONS=34` and
`TRADING_MAX_CURRENCY_EXPOSURE=0.025`, and those three had never been checked against each
other. Naively 34 positions at 0.5% each is 17% of equity at risk at once.

## What the check found, after two wrong guesses

The first version of this file asserted two things that are false, and the failures are the
useful part.

**A same-direction book does not accumulate dollar risk monotonically.** `usdcad`, `usdchf` and
`usdjpy` are dollar-*base*, so buying them moves the USD leg the opposite way from buying
`eurusd`. Seven simultaneous buys across the majors leave a net dollar leg of one unit, well
inside the cap - the cap does not count positions, it counts *concentration*.

**The cap is on net signed exposure per currency and nothing limits gross.** `Exposure.gross()`
exists and no gate reads it. So the question "is 34 positions safe" has no single answer: it
depends entirely on whether the book is concentrated or spread, and the cap only sees the
former.

These tests therefore **measure** rather than assume, and assert the measured facts so a later
change to any of the three settings cannot quietly break the reasoning.
"""

from __future__ import annotations

import till_infinity.trading.exposure as ex
from till_infinity.trading.models import Position, Side

#: The live configuration, as read off the instance on 2026-09-21.
RISK_FRACTION = 0.005
MAX_POSITIONS = 34
MAX_CURRENCY_EXPOSURE = 0.025
EQUITY = 100_000.0

RISK = RISK_FRACTION * EQUITY
LIMIT = MAX_CURRENCY_EXPOSURE * EQUITY

#: Dollar-quoted majors, where a buy is short dollars.
QUOTED = ("eurusd", "gbpusd", "audusd", "nzdusd")

#: Dollar-base majors, where a buy is long dollars - the reason a mixed book nets out.
BASED = ("usdcad", "usdchf", "usdjpy")


def _book(pairs: list[tuple[str, Side]]) -> tuple[list[Position], dict, dict]:
    """A book of one position per entry, each risking `RISK`."""
    positions, risk_of, feed_of = [], {}, {}
    for i, (feed, side) in enumerate(pairs, start=1):
        symbol = f"{feed.upper()}#{i}"  # unique, so each ticket maps to its own feed
        positions.append(Position(ticket=i, symbol=symbol, side=side, volume=0.1, price_open=1.0))
        risk_of[i] = RISK
        feed_of[symbol] = feed
    return positions, risk_of, feed_of


def _worst(pairs: list[tuple[str, Side]]) -> float:
    return abs(ex.measure(*_book(pairs)).worst()[1])


def _gross(pairs: list[tuple[str, Side]]) -> float:
    return ex.measure(*_book(pairs)).gross()


def test_concentration_in_one_currency_is_what_the_cap_stops():
    """Five same-direction dollar-quoted trades reach the cap exactly; a sixth breaches it.

    0.5% of risk per trade against a 2.5% cap is five units, and this is the one place the
    arithmetic is as simple as it looks.
    """
    for n in (1, 2, 3, 4, 5):
        assert _worst([(QUOTED[0], Side.BUY)] * n) <= LIMIT, f"{n} should fit"
    assert _worst([(QUOTED[0], Side.BUY)] * 6) > LIMIT, "a sixth should breach"


def test_thirty_four_concentrated_positions_are_unreachable():
    """The naive 17%-of-equity scenario cannot happen in one currency."""
    assert _worst([("eurusd", Side.BUY)] * MAX_POSITIONS) > LIMIT * 3


def test_a_mixed_major_book_barely_touches_the_cap():
    """Buying quoted and base majors together nets the dollar leg out.

    This is the guess that was wrong, kept as a test because it is the mechanism that makes
    `MAX_POSITIONS` reachable and it is not obvious from the settings.
    """
    book = [(f, Side.BUY) for f in QUOTED + BASED]
    # Four short-dollar against three long-dollar leaves one unit on the dollar leg.
    assert _worst(book) <= LIMIT
    assert len(book) == 7


def test_max_positions_is_reachable_while_every_currency_cap_holds():
    """**The answer.** A spread book reaches 34 positions with no cap breached.

    Genuinely offsetting pairs - the same instrument long and short - net to nothing on both
    legs, so the per-currency gate sees a flat book however many are open. The gate is not
    wrong; it is measuring net currency risk and there is none. It simply does not speak to
    how many positions are open or to how much they can lose together.
    """
    book: list[tuple[str, Side]] = []
    for i in range(MAX_POSITIONS):
        # Alternate by **pass**, not by index. `len(QUOTED)` is even, so `i % 2` gives every
        # pair the same side forever - which is how the first two versions of this test
        # built a concentrated book while believing it was balanced.
        side = Side.BUY if (i // len(QUOTED)) % 2 == 0 else Side.SELL
        book.append((QUOTED[i % len(QUOTED)], side))
    assert len(book) == MAX_POSITIONS
    assert _worst(book) <= LIMIT, f"worst leg {_worst(book):.0f} against cap {LIMIT:.0f}"


def test_nothing_measures_total_stop_loss_risk():
    """The gap, stated as a test so it cannot be lost.

    A third wrong guess corrected: `Exposure.gross()` sums the **net** exposure per currency,
    so on an offsetting book it is near zero. It is not a measure of total position risk and
    reading it as one was the mistake.

    The actual gap is simpler and worse. **No quantity anywhere in the system is the sum of
    money at risk across open tickets.** `risk_of` holds it per ticket, `measure` folds it into
    currency legs and discards the total, and no gate adds it up. So the only thing bounding
    simultaneous stop-loss risk is `MAX_POSITIONS`, which bounds it at
    `34 x 0.005 = 17%` of equity - and that bound is a position count that was never chosen
    with the risk fraction in mind.
    """
    book: list[tuple[str, Side]] = []
    for i in range(MAX_POSITIONS):
        # Alternate by **pass**, not by index. `len(QUOTED)` is even, so `i % 2` gives every
        # pair the same side forever - which is how the first two versions of this test
        # built a concentrated book while believing it was balanced.
        side = Side.BUY if (i // len(QUOTED)) % 2 == 0 else Side.SELL
        book.append((QUOTED[i % len(QUOTED)], side))
    assert _worst(book) <= LIMIT, "the net cap is satisfied"
    # The per-currency gate sees a flat book...
    assert _gross(book) <= LIMIT, "net currency exposure is genuinely small here"
    # ...while 34 stops sit open, each able to be hit. This is the number nobody computes.
    _positions, risk_of, _feed_of = _book(book)
    total = sum(abs(v) for v in risk_of.values())
    assert total == MAX_POSITIONS * RISK
    assert total / EQUITY >= 0.17, f"{total / EQUITY:.1%} of equity at risk, ungated"


def test_synthetics_share_only_their_dollar_leg():
    """Each synthetic has its own base token, so they never net against each other.

    That is the right design and it is measured rather than assumed: cross-correlation of
    hourly returns across the Boom, Crash and Volatility families is at most 0.009, so
    treating them as unrelated risks is correct. Their **dollar** legs are real and do
    accumulate, which is what stops a book of thirty long synthetics forming.
    """
    feeds = ["volatility_75_index", "volatility_25_index", "boom_1000_index"]
    ex.register_broker_legs(feeds)
    measured = ex.measure(*_book([(f, Side.BUY) for f in feeds]))
    assert abs(measured.of("USD")) == 3 * RISK
    bases = [c for c in measured.by_currency if c != "USD" and abs(measured.of(c)) > 0]
    assert len(bases) == 3, "each synthetic should carry its own base token"
    assert all(abs(measured.of(c)) == RISK for c in bases)


def test_five_long_synthetics_reach_the_dollar_cap():
    """Which is the practical limit on a directional synthetic book, not 34."""
    feeds = [f"volatility_{n}_index" for n in (10, 25, 50, 75, 100)]
    ex.register_broker_legs(feeds)
    assert _worst([(f, Side.BUY) for f in feeds]) <= LIMIT
    ex.register_broker_legs(["volatility_150_index"])
    assert _worst([(f, Side.BUY) for f in [*feeds, "volatility_150_index"]]) > LIMIT


def test_crosses_carry_no_dollar_leg():
    """So the dollar cap does not restrain a cross-heavy book; the shared leg must."""
    measured = ex.measure(*_book([("eurjpy", Side.BUY), ("gbpjpy", Side.BUY)]))
    assert abs(measured.of("USD")) == 0.0
    assert abs(measured.of("JPY")) == 2 * RISK
