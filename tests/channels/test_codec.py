"""The Redis codec must be an exact inverse, type included.

**This file used to be shaped around a bug instead of catching it.**
`test_encode_flat_dict_primitives` built a payload with a float, an int and a
bool, then asserted on the *string* field only - the same assertion written
twice - and a comment explained that "flat dicts store as strings - preserves
identity for round-trip". They do not. `_encode` wrote every primitive with
`str()` and `_decode` handed the string back, so over Redis:

    1            -> "1"
    4008.37      -> "4008.37"
    0            -> "0"      truthy
    False        -> "False"  truthy
    None         -> ""

Nine of fifteen representative values came back wrong, and three of them
inverted a truthiness test - so `if payload["count"]:` was true for zero over
Redis and false in one process. The declared bus contracts say
`"type": "number"` for prices, so those messages also failed their own schema.

The rule here is the one that was missing: assert the type as well as the
value, on every kind of value the bus carries.
"""

from __future__ import annotations

import pytest
from till_channels.redis import RedisChannel

#: One of each kind of thing a bus payload holds.
CASES: dict[str, object] = {
    "int": 2,
    "float": 4008.37,
    "negative": -0.00012,
    "true": True,
    "false": False,
    "none": None,
    "string": "EURUSD",
    "numeric_string": "123",
    "nested": {"bid": 1.0812, "ask": 1.0814, "deep": {"n": 3}},
    "list": [1, 2.5, "three", None, False],
    "unicode": "sigma 0.38 -> 0.648",
    "big": 1_600_000_000_000,
    "precise": 0.1 + 0.2,
    "empty_string": "",
    "zero": 0,
}


def roundtrip(payload):
    encoded = RedisChannel._encode(payload)
    # Redis stream fields are string -> string. If this breaks, the client
    # raises rather than silently coercing, so it is worth asserting.
    assert all(isinstance(v, str) for v in encoded.values())
    return RedisChannel._decode(encoded)


@pytest.mark.parametrize("name", list(CASES))
def test_a_value_comes_back_as_itself(name):
    """Type and value, which is what the old version of this test skipped."""
    sent = CASES[name]
    got = roundtrip(dict(CASES))[name]
    assert type(got) is type(sent), f"{name}: {type(sent).__name__} -> {type(got).__name__}"
    assert got == sent


@pytest.mark.parametrize("falsy", [False, 0, 0.0, "", None])
def test_a_falsy_value_stays_falsy(falsy):
    """The dangerous shape: `str(False)` and `str(0)` are both truthy.

    A guard written as `if payload["armed"]:` read one way in one process and
    the other way over Redis, which is worse than either being wrong.
    """
    got = roundtrip({"v": falsy})["v"]
    assert not got, f"{falsy!r} came back as {got!r}, which is truthy"


def test_a_whole_payload_survives_at_once():
    assert roundtrip(dict(CASES)) == CASES


def test_a_payload_that_is_not_a_dict_goes_through_one_field():
    assert roundtrip([1, 2, 3, "four"]) == [1, 2, 3, "four"]
    assert roundtrip("hello") == "hello"
    assert roundtrip(7) == 7


def test_decode_ignores_the_control_field():
    """The close sentinel is written straight to the stream, not encoded, so
    it is a bare string and must not be JSON-decoded with the payload."""
    decoded = RedisChannel._decode({"__ctrl__": "__channel_closed__", "x": '"y"'})
    assert "__ctrl__" not in decoded
    assert decoded["x"] == "y"
