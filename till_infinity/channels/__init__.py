"""channels — async multi-producer / multi-consumer channels.

Inspired by Rust `async-channel` and Drakkar-Software/Async-Channel.
Pluggable backends: in-memory (default) and Redis Streams.

Quickstart:

    from channels import bounded, unbounded

    tx, rx = bounded(32)
    await tx.send({"event": "tick", "price": 1.2345})
    msg = await rx.recv()

Redis backbone (durable, cross-process):

    from channels import redis_channel

    tx, rx = redis_channel("market:ticks", group="analyzer")
    await tx.send({"symbol": "EURUSD", "price": 1.2})
    msg = await rx.recv()

The API surface stays the same regardless of backend.
"""

from .backbone import Backbone, Channel, Receiver, Sender
from .backoff import DEFAULT_BACKOFF, BackoffPolicy, ExponentialBackoff, FixedBackoff
from .dlq import DeadLetterQueue
from .errors import ChannelClosed, ChannelEmpty, ChannelFull
from .memory import bounded, unbounded
from .metrics import (
    InMemoryMetrics,
    MetricsHook,
    NoOpMetrics,
    get_default_metrics,
    set_default_metrics,
)
from .persistent import DurableSender, Outbox, wrap_with_outbox
from .redis import redis_channel
from .serializer import DEFAULT_SERIALIZER, JSONSerializer, Serializer, StringSerializer

__all__ = [
    "DEFAULT_BACKOFF",
    "DEFAULT_SERIALIZER",
    # core
    "Backbone",
    # policies
    "BackoffPolicy",
    "Channel",
    "ChannelClosed",
    "ChannelEmpty",
    "ChannelFull",
    "DeadLetterQueue",
    "DurableSender",
    "ExponentialBackoff",
    "FixedBackoff",
    "InMemoryMetrics",
    "JSONSerializer",
    # metrics
    "MetricsHook",
    "NoOpMetrics",
    # durability
    "Outbox",
    "Receiver",
    "Sender",
    # serialization
    "Serializer",
    "StringSerializer",
    # factories
    "bounded",
    "get_default_metrics",
    "redis_channel",
    "set_default_metrics",
    "unbounded",
    "wrap_with_outbox",
]
