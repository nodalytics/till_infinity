"""Pluggable serialization for channel payloads.

The default JSONSerializer handles dicts/lists/primitives. Swap in a
different Serializer when you need msgpack, protobuf, or a strict
schema-enforced format. Every channel accepts an optional serializer
argument; if None, JSONSerializer is used.
"""
from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Serializer(Protocol):
    """Protocol for message codecs."""

    def encode(self, obj: Any) -> bytes: ...
    def decode(self, data: bytes) -> Any: ...


class JSONSerializer:
    """Default: JSON-encoded UTF-8 bytes."""

    def encode(self, obj: Any) -> bytes:
        return json.dumps(obj, default=str, separators=(",", ":")).encode("utf-8")

    def decode(self, data: bytes) -> Any:
        if isinstance(data, str):
            return json.loads(data)
        return json.loads(data.decode("utf-8"))


class StringSerializer:
    """No-op passthrough for dicts with all-string values (Redis native)."""

    def encode(self, obj: Any) -> bytes:
        if isinstance(obj, dict):
            # Assume already string-valued
            return json.dumps(obj).encode("utf-8")
        return str(obj).encode("utf-8")

    def decode(self, data: bytes) -> Any:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


DEFAULT_SERIALIZER: Serializer = JSONSerializer()
