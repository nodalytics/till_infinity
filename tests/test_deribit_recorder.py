"""The recorder, against a fake transport.

It is the third collector in this repository and it inherits their rule: a
failure is written down, not skipped, so an outage in the data reads as an
outage rather than a gap of unknown cause. What it must never do is write a
file that looks like a successful sweep of a quiet market when the venue
actually refused.
"""

from __future__ import annotations

import ast
import gzip
from pathlib import Path

import httpx

from research.harness.deribit_recorder import sweep, writer

INSTRUMENTS = [
    {
        "instrument_name": "BTC-24SEP26-71000-C",
        "expiration_timestamp": 1790236800000,
        "strike": 71000.0,
        "option_type": "call",
        "base_currency": "BTC",
    }
]
BOOK = [
    {
        "instrument_name": "BTC-24SEP26-71000-C",
        "mark_iv": 40.6,
        "mark_price": 0.0123,
        "bid_price": 0.0120,
        "ask_price": 0.0126,
        "underlying_price": 84000.0,
        "open_interest": 12.0,
        "volume": 958.2,
    }
]


def transport(instruments, book):
    def handler(request: httpx.Request) -> httpx.Response:
        if "get_instruments" in request.url.path:
            return httpx.Response(200, json={"result": instruments})
        return httpx.Response(200, json={"result": book})

    return httpx.MockTransport(handler)


def test_a_good_sweep_returns_rows():
    with httpx.Client(transport=transport(INSTRUMENTS, BOOK)) as client:
        rows = sweep(client, "BTC", at=1790233483.0)
    assert len(rows) == 1
    assert rows[0].instrument == "BTC-24SEP26-71000-C"


def test_an_error_body_returns_no_rows_rather_than_raising():
    """200 with a JSON-RPC error. The recorder must survive and say nothing was got."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"code": 10028, "message": "no"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows = sweep(client, "BTC", at=1790233483.0)
    assert rows == []


def test_an_empty_listing_skips_the_second_call():
    """No instruments means nothing to quote, and the book call is wasted."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return httpx.Response(200, json={"result": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows = sweep(client, "BTC", at=1790233483.0)
    assert rows == []
    assert not any("get_book_summary" in path for path in asked)


def test_a_transport_failure_is_survived():
    """A collector that dies on one refused request stops collecting."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert sweep(client, "BTC", at=1790233483.0) == []


def test_the_header_is_written_once(tmp_path):
    with httpx.Client(transport=transport(INSTRUMENTS, BOOK)) as client:
        rows = sweep(client, "BTC", at=1790233483.0)
    write = writer(tmp_path)
    write(rows)
    write(rows)
    path = next(tmp_path.glob("deribit_*.csv.gz"))
    with gzip.open(path, "rt") as handle:
        text = handle.read()
    assert text.count("instrument,underlying") == 1
    assert text.count("BTC-24SEP26-71000-C") == 2


def test_no_rows_writes_no_file(tmp_path):
    """An empty sweep must not create a file that reads as a quiet market."""
    writer(tmp_path)([])
    assert list(tmp_path.glob("*.csv.gz")) == []


def test_there_is_no_private_endpoint_anywhere_in_this_file():
    """The 'never trades' property, asserted rather than promised.

    Checked against the module's **string literals** rather than its raw text.
    A grep cannot tell a call from a mention, and the first version of this test
    failed on the docstring that documents the property - which would have left
    only two ways out, both bad: delete the documentation, or delete the test.
    """
    source = Path("research/harness/deribit_recorder.py").read_text()
    tree = ast.parse(source)
    # Bare string statements are docstrings and comments; everything else is a
    # value the code actually uses.
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    assert literals, "no string literals found - the AST walk is broken, not the module"
    for text in literals:
        assert "private/" not in text
        assert "api_key" not in text.lower()
