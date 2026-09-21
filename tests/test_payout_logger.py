"""The payout logger's success path, which the live endpoint could not exercise.

Deriv's WebSocket API returned HTTP 520 from three independent hosts when this was written, so
the collector was verified against an outage and not against a quote. **Code that waits for an
outage to end is exactly the code that fails silently when the moment comes**, so the parsing and
arithmetic are pinned here with a fake socket instead.

The one number that matters is `implied = stake / payout`, because every downstream comparison -
margin, calibration, skew - is built on it.
"""

from __future__ import annotations

import asyncio
import json

from research.harness.payout_logger import STAKE, quote


class FakeSocket:
    """Replays a scripted server, and records what was asked."""

    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        if not self.replies:
            raise AssertionError("the logger asked for more messages than the server sent")
        return json.dumps(self.replies.pop(0))


def _run(replies, **kwargs):
    ws = FakeSocket(replies)
    row = asyncio.run(quote(ws, kwargs.get("symbol", "R_75"), kwargs.get("minutes", 5), "CALL"))
    return ws, row


def test_a_quote_becomes_a_row_with_the_implied_probability():
    _ws, row = _run([{"proposal": {"payout": 19.53, "ask_price": 10.0, "spot": 1234.5}}])
    assert row["symbol"] == "R_75"
    assert row["duration_min"] == 5
    assert row["contract"] == "CALL"
    assert row["payout"] == 19.53
    assert row["spot"] == 1234.5
    assert row["error"] == ""
    # The whole point: stake over payout is the broker's implied probability.
    assert abs(row["implied"] - STAKE / 19.53) < 1e-9
    assert abs(row["implied"] - 0.512033) < 1e-5


def test_the_request_is_a_proposal_and_never_a_buy():
    """A property of the code, not a promise about how it is invoked."""
    ws, _row = _run([{"proposal": {"payout": 19.0}}])
    assert len(ws.sent) == 1
    sent = ws.sent[0]
    assert sent["proposal"] == 1
    assert "buy" not in sent
    assert sent["basis"] == "stake"
    assert sent["amount"] == STAKE
    assert sent["duration_unit"] == "m"


def test_both_sides_separate_margin_from_skew():
    """Two quotes at one instant give the margin and the asymmetry, which is the design."""
    call = asyncio.run(quote(FakeSocket([{"proposal": {"payout": 19.53}}]), "R_75", 5, "CALL"))
    put = asyncio.run(quote(FakeSocket([{"proposal": {"payout": 19.53}}]), "R_75", 5, "PUT"))
    margin = call["implied"] + put["implied"] - 1.0
    skew = call["implied"] - put["implied"]
    # A symmetric book: all of the excess is margin and none of it is a directional view.
    assert abs(skew) < 1e-9
    assert margin > 0, "a broker quoting both sides at fair odds would be giving money away"
    assert abs(margin - 0.024066) < 1e-4


def test_an_asymmetric_book_shows_up_as_skew():
    call = asyncio.run(quote(FakeSocket([{"proposal": {"payout": 21.0}}]), "R_75", 5, "CALL"))
    put = asyncio.run(quote(FakeSocket([{"proposal": {"payout": 18.0}}]), "R_75", 5, "PUT"))
    skew = call["implied"] - put["implied"]
    # A cheaper CALL payout would mean the broker thinks up is likelier; here the PUT is
    # dearer, so the implied probability of a rise is the lower of the two.
    assert skew < 0
    assert abs(skew - (STAKE / 21.0 - STAKE / 18.0)) < 1e-9


def test_a_broker_error_is_recorded_rather_than_dropped():
    """An outage has to appear in the data as an outage, not as a gap of unknown cause."""
    _ws, row = _run([{"error": {"code": "MarketIsClosed", "message": "closed"}}])
    assert row["error"] == "MarketIsClosed"
    assert row["payout"] == ""
    assert row["implied"] == ""
    assert row["ts"] > 0


def test_a_zero_payout_does_not_divide_by_zero():
    _ws, row = _run([{"proposal": {"payout": 0}}])
    assert row["implied"] == ""
    assert row["error"] == ""


def test_unrelated_messages_are_skipped_until_the_proposal_arrives():
    """The socket is shared, so ticks and heartbeats arrive between request and reply."""
    _ws, row = _run(
        [
            {"ping": "pong"},
            {"tick": {"quote": 1234.5}},
            {"proposal": {"payout": 20.0, "spot": 1}},
        ]
    )
    assert row["payout"] == 20.0
    assert abs(row["implied"] - 0.5) < 1e-9


def test_a_silent_server_is_recorded_not_hung():
    _ws, row = _run([{"ping": 1}] * 6)
    assert row["error"] == "no_proposal"
