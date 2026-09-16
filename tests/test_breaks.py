"""The change of character, and the line it happened at.

A run of higher lows ending in a lower low is the market ceasing to be bought
at successively better prices. The price that stopped being defended is the
last higher low, and that line - not the swing that broke it - is the one worth
recording, because price that has traded through a defended level tends to come
back to it.
"""

from __future__ import annotations

import pytest

from till_infinity.structures import breaks as br
from till_infinity.structures.drawing.pips import Point, Swing


def turn(index: int, price: float, swing: Swing) -> Point:
    """One swing, timed a minute per index so `held_for` means something."""
    return Point(
        index=index,
        time=index * 60,
        price=price,
        swing=swing,
        prominence_bps=100.0,
        confirmed=True,
    )


def sequence(*rows: tuple[float, Swing]) -> list[Point]:
    return [turn(i, price, swing) for i, (price, swing) in enumerate(rows)]


class TestTheFlipIsTheEvent:
    def test_higher_lows_then_a_lower_low_breaks_the_last_higher_low(self):
        """The line that was defended and then was not."""
        got = br.last_break(
            sequence(
                (10.0, Swing.LOW),
                (20.0, Swing.HIGH),
                (12.0, Swing.LOW),  # HL - this is the line
                (22.0, Swing.HIGH),
                (11.0, Swing.LOW),  # LL - the flip
            )
        )
        assert got is not None
        assert got.side == br.DOWN
        assert got.price == 12.0

    def test_lower_highs_then_a_higher_high_breaks_the_last_lower_high(self):
        got = br.last_break(
            sequence(
                (20.0, Swing.HIGH),
                (10.0, Swing.LOW),
                (18.0, Swing.HIGH),  # LH - the line
                (9.0, Swing.LOW),
                (19.0, Swing.HIGH),  # HH - the flip
            )
        )
        assert got is not None
        assert got.side == br.UP
        assert got.price == 18.0

    def test_the_side_is_where_the_market_turned_not_where_it_broke(self):
        """A lower low is a break *downward* and a turn *down*; the consumer
        wants to know which way to lean, so that is what `side` says."""
        down = br.last_break(
            sequence((10.0, Swing.LOW), (20.0, Swing.HIGH), (12.0, Swing.LOW), (9.0, Swing.LOW))
        )
        assert down is not None
        assert down.side == br.DOWN


class TestOnlyTheFlip:
    def test_a_trend_that_never_turns_has_no_break(self):
        """Not a trend filter. A market that has simply been going up has not
        changed its mind about anything."""
        assert (
            br.last_break(
                sequence(
                    (10.0, Swing.LOW),
                    (20.0, Swing.HIGH),
                    (12.0, Swing.LOW),
                    (22.0, Swing.HIGH),
                    (14.0, Swing.LOW),
                    (24.0, Swing.HIGH),
                )
            )
            is None
        )

    def test_the_second_lower_low_is_the_move_carrying_on(self):
        """**The continuation is not a second break.** Treating it as one would
        report a break on every leg of a trend, which is the failure this rule
        exists to avoid - and it would put the entry at a line the market has
        already left behind."""
        got = br.last_break(
            sequence(
                (10.0, Swing.LOW),
                (20.0, Swing.HIGH),
                (12.0, Swing.LOW),  # HL
                (22.0, Swing.HIGH),
                (11.0, Swing.LOW),  # LL - the flip, breaking 12.0
                (15.0, Swing.HIGH),
                (8.0, Swing.LOW),  # LL again - aftermath, not an event
            )
        )
        assert got is not None
        assert got.price == 12.0, "the second lower low must not move the line"

    def test_a_later_flip_the_other_way_replaces_it(self):
        """The most recent change of character is the one that matters; an
        older one has been overtaken by events."""
        got = br.last_break(
            sequence(
                (10.0, Swing.LOW),
                (20.0, Swing.HIGH),
                (12.0, Swing.LOW),  # HL
                (18.0, Swing.HIGH),  # LH
                (11.0, Swing.LOW),  # LL - breaks 12.0, turn down
                (19.0, Swing.HIGH),  # HH - breaks 18.0, turn up
            )
        )
        assert got is not None
        assert got.side == br.UP
        assert got.price == 18.0


class TestWhatItCarries:
    def test_it_says_how_long_the_line_stood(self):
        """A level that held for a day is not the one that held for four bars,
        and nothing downstream can tell them apart without this."""
        got = br.last_break(
            sequence(
                (10.0, Swing.LOW),
                (20.0, Swing.HIGH),
                (12.0, Swing.LOW),
                (22.0, Swing.HIGH),
                (11.0, Swing.LOW),
            )
        )
        assert got is not None
        assert got.made == 2 * 60
        assert got.broke == 4 * 60
        assert got.held_for == 120

    def test_it_says_how_far_past_the_line_price_went(self):
        """A break by a hair and a break by a mile are different claims. Where
        the threshold between them sits is the consumer's decision, so the
        distance is reported rather than judged."""
        got = br.last_break(
            sequence(
                (10.0, Swing.LOW),
                (20.0, Swing.HIGH),
                (12.0, Swing.LOW),
                (22.0, Swing.HIGH),
                (11.5, Swing.LOW),
            )
        )
        assert got is not None
        assert got.past == pytest.approx(0.5)


class TestItRefusesRatherThanGuesses:
    def test_nothing_at_all_is_no_break(self):
        assert br.last_break([]) is None

    def test_one_swing_of_each_kind_cannot_flip(self):
        """The first of each kind has nothing to be compared against."""
        assert br.last_break(sequence((10.0, Swing.LOW), (20.0, Swing.HIGH))) is None

    def test_edges_carry_no_structure_and_are_skipped(self):
        """`pips` marks endpoints and points on a straight run as edges; they
        say nothing about where price turned."""
        got = br.last_break(
            sequence(
                (10.0, Swing.LOW),
                (15.0, Swing.EDGE),
                (20.0, Swing.HIGH),
                (12.0, Swing.LOW),
                (22.0, Swing.HIGH),
                (11.0, Swing.LOW),
            )
        )
        assert got is not None
        assert got.price == 12.0
