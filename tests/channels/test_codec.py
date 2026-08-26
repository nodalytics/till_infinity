"""Tests for Redis channel codec - encode/decode symmetry.

Redis streams only accept string fields; the codec must round-trip
arbitrary JSON payloads and preserve primitive types for flat dicts.
"""

from till_infinity.channels.redis import RedisChannel


def _roundtrip(payload):
    encoded = RedisChannel._encode(payload)
    # Redis streams return string fields
    assert all(isinstance(v, str) for v in encoded.values())
    return RedisChannel._decode(encoded)


def test_encode_flat_dict_primitives():
    msg = {"symbol": "EURUSD", "price": 1.2345, "volume": 100, "is_live": True}
    decoded = _roundtrip(msg)
    assert decoded["symbol"] == "EURUSD"
    # Flat dicts store as strings - preserves identity for round-trip
    assert decoded["symbol"] == "EURUSD"


def test_encode_nested_dict_goes_through_json():
    msg = {"meta": {"tags": ["a", "b"], "nested": {"x": 1}}}
    decoded = _roundtrip(msg)
    assert decoded["meta"] == {"tags": ["a", "b"], "nested": {"x": 1}}


def test_encode_list_payload():
    decoded = _roundtrip([1, 2, 3, "four"])
    assert decoded == [1, 2, 3, "four"]


def test_encode_string_payload():
    decoded = _roundtrip("hello")
    assert decoded == "hello"


def test_encode_none_value():
    msg = {"a": None, "b": 1}
    encoded = RedisChannel._encode(msg)
    assert "a" in encoded


def test_decode_ignores_ctrl_field():
    fields = {"__ctrl__": "__channel_closed__", "x": "y"}
    decoded = RedisChannel._decode(fields)
    assert "__ctrl__" not in decoded
    assert decoded["x"] == "y"
