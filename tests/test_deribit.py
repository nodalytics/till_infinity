"""Deribit's wire format, and the one unit that has already bitten this repo.

Every timestamp Deribit sends is in milliseconds. `prices` already carries a
seconds/milliseconds split between `bars.ts` and `quotes.ts`, and a query written
against both without knowing that is wrong in a way that looks plausible. So the
boundary normalises, and these tests are what hold it there.
"""

from __future__ import annotations

from research.harness.deribit import FIELDS, parse_summary

#: One row shaped exactly like `get_book_summary_by_currency` returns, with the
#: field set observed on 2026-09-24.
SUMMARY = {
    "instrument_name": "BTC-24SEP26-71000-C",
    "mark_iv": 40.6,
    "mark_price": 0.0123,
    "bid_price": 0.0120,
    "ask_price": 0.0126,
    "mid_price": 0.0123,
    "underlying_price": 84000.0,
    "open_interest": 12.0,
    "volume": 958.2,
    "creation_timestamp": 1789891252000,
}

#: The same instrument as `get_instruments` describes it. The two calls are
#: separate, and everything but the quote comes from this one.
LISTING = {
    "BTC-24SEP26-71000-C": {
        "instrument_name": "BTC-24SEP26-71000-C",
        "expiration_timestamp": 1790236800000,
        "strike": 71000.0,
        "option_type": "call",
        "base_currency": "BTC",
    }
}


def test_the_expiry_is_seconds_not_milliseconds():
    rows = parse_summary({"result": [SUMMARY]}, instruments=LISTING, at=1790233483.0)
    assert len(rows) == 1
    # 1790236800000 ms is 1790236800 s. Read as seconds it would be 20,699,613
    # days away, which is the shape of the mistake.
    assert rows[0].expiry == 1790236800.0
    assert 0 < rows[0].expiry - rows[0].at < 86400 * 2


def test_a_strike_with_no_book_is_dropped_not_zeroed():
    """A zero bid recorded as a number is an option that looks free."""
    thin = dict(SUMMARY, bid_price=None, ask_price=None)
    rows = parse_summary({"result": [thin]}, instruments=LISTING, at=1790233483.0)
    assert rows == []


def test_an_instrument_absent_from_the_listing_is_dropped():
    """The summary and the listing are fetched separately and can disagree."""
    rows = parse_summary({"result": [SUMMARY]}, instruments={}, at=1790233483.0)
    assert rows == []


def test_an_error_body_yields_no_rows_and_does_not_raise():
    """Deribit answers 200 with a JSON-RPC error. That must not look like a quiet market."""
    rows = parse_summary(
        {"error": {"code": 10028, "message": "too_many_requests"}},
        instruments={},
        at=1790233483.0,
    )
    assert rows == []


def test_fields_matches_the_dataclass():
    """`FIELDS` is the CSV header, so drift here silently reorders stored columns."""
    assert FIELDS[0] == "instrument"
    assert "expiry" in FIELDS
    assert len(FIELDS) == 13


def test_a_zero_bid_or_ask_is_dropped_too_not_only_a_missing_one():
    """The other half of "absent or zero", which the first version of this missed.

    `_number(0.0)` is a perfectly good float, so a book quoted at zero on both sides
    survived as a row and produced a cost of exactly zero. That is not harmless: it
    is the detection floor the whole phase is gated on, and mixing fifty empty books
    into fifty real ones halves the median. Deribit sends `null` today, so this was
    latent rather than live - which is the only reason it shipped.
    """
    for bid, ask in ((0.0, 0.0), (0.0, 0.0126), (0.0120, 0.0)):
        thin = dict(SUMMARY, bid_price=bid, ask_price=ask)
        rows = parse_summary({"result": [thin]}, instruments=LISTING, at=1790233483.0)
        assert rows == [], f"bid={bid} ask={ask} should not be recorded"


def test_a_zero_mark_is_dropped():
    """The floor divides by mark, so a zero there has no cost fraction at all."""
    thin = dict(SUMMARY, mark_price=0.0)
    rows = parse_summary({"result": [thin]}, instruments=LISTING, at=1790233483.0)
    assert rows == []
