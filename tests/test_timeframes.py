"""Several clocks on one strategy, and the look-ahead that makes it wrong.

Most of this file is about one thing: the H1 bar containing an M15 signal has
not finished when that signal fires, and three quarters of it is in the
future. Reading it is the commonest multi-timeframe bug and it does not
announce itself — the backtest just gets better. So `Frames.ready` drops a
frame whose last close is after the moment asked about, and the tests below
try to get a forming bar out of it several ways.

The rest is the ordering rules. A context frame has to be strictly coarser
than the signal, because a trigger on a coarse frame is a different strategy
on that frame rather than this one with context, and a frame equal to the
signal would fold one series into two states and double its weight.
"""

from __future__ import annotations

import pytest

from till_infinity.strategies.timeframes import Frames, Reading, seconds_of

M15 = "EUR/USD.DERIV-15-MINUTE-LAST-EXTERNAL"
H1 = "EUR/USD.DERIV-1-HOUR-LAST-EXTERNAL"
H4 = "EUR/USD.DERIV-4-HOUR-LAST-EXTERNAL"
D1 = "EUR/USD.DERIV-1-DAY-LAST-EXTERNAL"
TICKS = "EUR/USD.DERIV-100-TICK-LAST-INTERNAL"

HOUR = 3_600.0


def built() -> Frames:
    return Frames(signal=M15, context=(H1, D1))


# ------------------------------------------------------------- reading a clock


#: A perpetual, whose **symbol contains a hyphen**. The regression below.
PERP = "ETHUSDT-PERP.BINANCE-15-MINUTE-LAST-EXTERNAL"

#: A **composite** bar type, M15 aggregated from the M1 feed, as
#: `strategies/structure.py` builds for the BOS rule. The second regression.
COMPOSITE = "XAU/USD.SIM-15-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL"


@pytest.mark.parametrize(
    ("bar_type", "expected"),
    [
        (M15, 900.0),
        (H1, 3_600.0),
        (H4, 14_400.0),
        (D1, 86_400.0),
        (TICKS, 0.0),
        (PERP, 900.0),
        (COMPOSITE, 900.0),
    ],
)
def test_a_time_bar_is_read_off_its_specification(bar_type, expected):
    """Parsed from the bar type rather than from a table of our own, so a
    specification the engine accepts and this does not reads zero rather than
    a wrong number."""
    assert seconds_of(bar_type) == expected


def test_a_composite_bar_type_reads_its_primary_span():
    """**The second regression, and it broke twelve tests.** A composite names
    what it was aggregated from after an `@`, and
    `strategies/structure.py` uses one as its signal frame - M15 built from
    the M1 feed, because the BOS rule is specified that way. Parsing the whole
    string found the aggregation source's fields and refused the frame, so
    every structure test failed to construct a desk.

    The span is the primary spec's; what it was built from does not change how
    long a bar covers. The module's warning about composite frames
    back-filling session gaps is about what to *read as context*, not a reason
    to refuse a signal frame.
    """
    assert seconds_of(COMPOSITE) == 900.0
    assert Frames(signal=COMPOSITE).all == (COMPOSITE,)


def test_a_symbol_containing_a_hyphen_is_still_parsed():
    """**The regression, and it was not a wrong number but a raise.** Splitting
    a bar type from the left read `ETHUSDT-PERP.BINANCE-15-MINUTE-LAST-EXTERNAL`
    as a step of "PERP.BINANCE", so `Frames` refused it as a non-time clock and
    every perpetual desk on Binance and Bybit failed to construct.
    `test_venues.py` caught it; nothing in this file did.

    A bar type is `{instrument}-{step}-{unit}-{price}-{source}`, so the last
    four fields are fixed and the instrument is whatever precedes them -
    which is why it is split from the right.
    """
    assert seconds_of(PERP) == 900.0
    frames = Frames(signal=PERP, context=("ETHUSDT-PERP.BINANCE-1-HOUR-LAST-EXTERNAL",))
    assert len(frames.all) == 2


def test_a_malformed_bar_type_is_not_comparable_rather_than_a_guess():
    assert seconds_of("nonsense") == 0.0
    assert seconds_of("") == 0.0


# ------------------------------------------------------------- the look-ahead


def test_a_frame_that_closes_after_the_signal_is_not_readable():
    """**The invariant.** An H1 bar closing at 13:00 was not knowable at the
    12:15 M15 close, so it is absent from `ready` entirely - not returned with
    a flag, because a caller who has to remember to check a flag is a caller
    who will forget."""
    frames = built()
    frames.observe(H1, closed_at=13 * HOUR, value={"trend": 1})

    assert frames.ready(12 * HOUR + 900) == {}
    assert frames.complete(12 * HOUR + 900) is False


def test_a_frame_that_closed_before_the_signal_is_readable():
    """The control. A guard that refused everything would satisfy the test
    above and be useless."""
    frames = built()
    frames.observe(H1, closed_at=12 * HOUR, value={"trend": 1})
    assert frames.ready(12 * HOUR + 900) == {H1: {"trend": 1}}


def test_a_bar_closing_exactly_at_the_signal_counts_as_known():
    """A bar's close is the instant its values are final, so closed *at* the
    moment asked about is knowable. Excluding it would discard the one H1 bar
    in four that is most current."""
    frames = built()
    frames.observe(H1, closed_at=12 * HOUR, value={"trend": 1})
    assert frames.ready(12 * HOUR) == {H1: {"trend": 1}}


def test_a_later_close_hides_a_frame_that_was_readable_a_moment_before():
    """The sequence that produces the bug in a live run: the H1 bar closes,
    then an M15 bar inside the *next* hour is asked about an earlier moment.
    Replaying a decision has to see what was known then, not what is known
    now."""
    frames = built()
    frames.observe(H1, closed_at=12 * HOUR, value={"trend": 1})
    assert frames.ready(12 * HOUR + 900) == {H1: {"trend": 1}}

    frames.observe(H1, closed_at=13 * HOUR, value={"trend": -1})
    assert frames.ready(12 * HOUR + 900) == {}


def test_partial_context_is_returned_and_named_as_partial():
    """Trading on what is known and waiting for all of it are both legitimate,
    so `ready` gives what there is and `complete` answers the other question.
    One function doing both would force a choice on every caller."""
    frames = built()
    frames.observe(D1, closed_at=0.0, value={"trend": -1})

    assert frames.ready(12 * HOUR) == {D1: {"trend": -1}}
    assert frames.complete(12 * HOUR) is False

    frames.observe(H1, closed_at=12 * HOUR, value={"trend": 1})
    assert frames.complete(12 * HOUR) is True


def test_a_frame_with_no_bar_yet_has_nothing_knowable():
    """The start of a run, and the honest state: a D1 context frame has no
    reading until a day closes, which on a fresh deploy is up to a day."""
    assert built().ready(12 * HOUR) == {}
    assert built().complete(12 * HOUR) is False


def test_a_reading_knows_whether_it_was_knowable():
    found = Reading(bar_type=H1, closed_at=12 * HOUR, value=1)
    assert found.known_by(12 * HOUR) is True
    assert found.known_by(12 * HOUR + 1) is True
    assert found.known_by(12 * HOUR - 1) is False


def test_how_stale_a_causal_reading_is_is_still_reportable():
    """A D1 frame read 20 hours after its close is causal *and* nearly a day
    out of date. Both are facts a decision may want, and `ready` alone cannot
    give the second."""
    frames = built()
    frames.observe(D1, closed_at=0.0, value={"trend": -1})
    frames.observe(H1, closed_at=12 * HOUR, value={"trend": 1})

    aged = frames.stale(12 * HOUR + 900)
    assert aged[H1] == pytest.approx(900.0)
    assert aged[D1] == pytest.approx(12 * HOUR + 900)


def test_staleness_covers_only_what_is_knowable():
    """A frame hidden by the look-ahead guard has no age either - reporting
    one would hand a caller the close it is not allowed to read."""
    frames = built()
    frames.observe(H1, closed_at=13 * HOUR, value={"trend": 1})
    assert frames.stale(12 * HOUR + 900) == {}


# ----------------------------------------------------------- the ordering rules


def test_a_context_frame_must_be_coarser_than_the_signal():
    """A trigger on a coarse frame is a different strategy on that frame, not
    this one with context - so a *finer* context frame is almost always a
    mistake, and one that is silently accepted is a strategy firing on two
    clocks without saying so."""
    with pytest.raises(ValueError, match="finer than the signal frame"):
        Frames(signal=H1, context=(M15,))


def test_the_signal_frame_cannot_also_be_context():
    """It would fold one series into two states and double its weight."""
    with pytest.raises(ValueError, match="is the signal frame"):
        Frames(signal=M15, context=(M15,))


def test_an_equal_but_differently_priced_frame_is_allowed():
    """Same span, different price type, so it is a second series rather than
    the same one twice - and coarser-or-equal is the rule, not strictly
    coarser."""
    mid = "EUR/USD.DERIV-15-MINUTE-MID-EXTERNAL"
    assert Frames(signal=M15, context=(mid,)).context == (mid,)


def test_a_non_time_clock_cannot_be_ordered_against_a_time_one():
    """A tick or volume frame has no span to compare, and
    `clocks-must-pass-an-iid-control` is why that is a refusal rather than a
    default: range time looked best on 8 of 8 markets and invented clustering
    at 5.3x on a process specified to have none."""
    with pytest.raises(ValueError, match="not a time bar"):
        Frames(signal=TICKS)
    with pytest.raises(ValueError, match="cannot be a context frame"):
        Frames(signal=M15, context=(TICKS,))


def test_a_strategy_needs_something_to_fire_on():
    with pytest.raises(ValueError, match="needs a signal frame"):
        Frames(signal="")


def test_every_frame_is_subscribed_signal_first():
    """`all` is what the desk subscribes, and the signal leads because its
    registration order decides which indicator sees the first bar."""
    assert built().all == (M15, H1, D1)
    assert Frames(signal=M15).all == (M15,)


# --------------------------------------------------- the desk carries the frames


def test_a_desk_defaults_to_one_clock():
    """Nothing changes for a strategy that does not ask for context, which is
    every strategy this desk currently runs."""
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.identifiers import InstrumentId

    from till_infinity.strategies.desk import DeskConfig

    config = DeskConfig(
        instrument_id=InstrumentId.from_str("EUR/USD.DERIV"),
        bar_type=BarType.from_str(M15),
    )
    assert config.context_bar_types == ()


def test_a_desk_config_carries_its_context_frames():
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.identifiers import InstrumentId

    from till_infinity.strategies.desk import DeskConfig

    config = DeskConfig(
        instrument_id=InstrumentId.from_str("EUR/USD.DERIV"),
        bar_type=BarType.from_str(M15),
        context_bar_types=(BarType.from_str(H1), BarType.from_str(D1)),
    )
    assert [str(frame) for frame in config.context_bar_types] == [H1, D1]
