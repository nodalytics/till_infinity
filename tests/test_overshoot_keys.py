"""The stop-overshoot book is keyed by feed, and the two spellings must meet.

## The bug these tests pin

`DEFAULT_STOP_OVERSHOOT` is written `boom_500_index.sell`. The feed it is
looked up by comes from `strategies.sizes.feed_of`, which **keeps the spaces**
in a broker's name - `boom 1000 index` - and whose docstring says of the
underscored form that it "would be the tidier answer and is the wrong one".

So the lookup asked for `boom 1000 index.sell`, the book held
`boom_1000_index.sell`, and every entry fell through to the 1.0 default:
**the whole boom and crash stop-overshoot mitigation was dead config for as
long as it existed.** `instruments.md` measured why it exists - Boom 500 stops
deliver at a median -1.25R with 60% past 1.1R against -1.00R and 0% for the
volatility indices, because a jump instrument can leapfrog a stop rather than
fill it - and the mitigation for that was never applied.

Nothing caught it because the only test near the function passed bare strings
it wrote itself, so both halves of the comparison used the same spelling and
the mismatch could not appear.

## What is asserted here

The production shapes, end to end: a feed name from `feed_of`, a side from
`domain.models.Side`, and the real `DEFAULT_STOP_OVERSHOOT`. A test that
builds its own book proves only that the function is self-consistent.
"""

from __future__ import annotations

import pytest
from nautilus_trader.model.identifiers import InstrumentId

from till_infinity.domain.models import Side
from till_infinity.risk.scaling import by_slippage, overshoot_for
from till_infinity.strategies.config import DEFAULT_STOP_OVERSHOOT
from till_infinity.strategies.sizes import feed_of


def feed(symbol: str) -> str:
    """The feed name production keys on, not one written by hand."""
    return feed_of(InstrumentId.from_str(f"{symbol}.MT5"))


class TestTheDefaultBookReachesTheFeedsItNames:
    """**These are the regression.** Each asserted against the real default."""

    @pytest.mark.parametrize("symbol", ["Boom 300 Index", "Boom 500 Index", "Boom 1000 Index"])
    def test_a_boom_sell_is_halved(self, symbol: str) -> None:
        """Boom spikes up, so the gapped stop is a sell's."""
        got = overshoot_for(DEFAULT_STOP_OVERSHOOT, feed(symbol), Side.SELL)
        assert got == 2.0
        assert by_slippage(got) == 0.5

    @pytest.mark.parametrize("symbol", ["Crash 300 Index", "Crash 500 Index", "Crash 1000 Index"])
    def test_a_crash_buy_is_halved(self, symbol: str) -> None:
        """Crash spikes down, so it is the buy that cannot fill."""
        got = overshoot_for(DEFAULT_STOP_OVERSHOOT, feed(symbol), Side.BUY)
        assert got == 2.0
        assert by_slippage(got) == 0.5

    def test_the_other_side_is_untouched(self) -> None:
        """The point of a side-keyed entry. A Boom buy's stop is on the side
        the instrument does not jump, so it fills like any other."""
        assert overshoot_for(DEFAULT_STOP_OVERSHOOT, feed("Boom 1000 Index"), Side.BUY) == 1.0
        assert overshoot_for(DEFAULT_STOP_OVERSHOOT, feed("Crash 1000 Index"), Side.SELL) == 1.0

    def test_a_feed_nobody_named_is_not_scaled(self) -> None:
        assert overshoot_for(DEFAULT_STOP_OVERSHOOT, feed("EURUSD"), Side.SELL) == 1.0


class TestEitherSpelling:
    """An operator may write `TRADING_STOP_OVERSHOOT` in either form, because
    both live in this repository for the reason `feed_of` explains."""

    @pytest.mark.parametrize("written", ["jump 75 index", "jump_75_index", "Jump 75 Index"])
    def test_a_configured_key_resolves_however_it_is_written(self, written: str) -> None:
        book = ((written, 1.25),)
        assert overshoot_for(book, feed("Jump 75 Index"), Side.SELL) == 1.25

    @pytest.mark.parametrize("written", ["boom 500 index.sell", "boom_500_index.sell"])
    def test_a_sided_key_resolves_however_it_is_written(self, written: str) -> None:
        book = ((written, 3.0),)
        assert overshoot_for(book, feed("Boom 500 Index"), Side.SELL) == 3.0
        assert overshoot_for(book, feed("Boom 500 Index"), Side.BUY) == 1.0


class TestProtectionForSharesTheVocabulary:
    """`test_the_side_words_are_the_ones_the_rest_of_the_desk_writes` says these
    two lookups read one vocabulary. Its default book is empty, so this one was
    latent rather than dead - an operator's key would have been ignored in
    silence."""

    @pytest.mark.parametrize("written", ["boom 1000 index", "boom_1000_index"])
    def test_either_spelling_is_found(self, written: str) -> None:
        from till_infinity.strategies.exits import protection_for

        book = ((written, "sentinel"),)
        assert protection_for(book, feed("Boom 1000 Index")) == "sentinel"

    def test_a_feed_nobody_named_is_still_none(self) -> None:
        """`None` means nothing names this feed, which the docstring
        distinguishes from a deliberate request for the defaults."""
        from till_infinity.strategies.exits import protection_for

        assert protection_for((("boom_1000_index", "x"),), feed("EURUSD")) is None
