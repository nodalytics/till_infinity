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
from .backoff import BackoffPolicy, ExponentialBackoff, FixedBackoff, DEFAULT_BACKOFF
from .dlq import DeadLetterQueue
from .errors import ChannelClosed, ChannelEmpty, ChannelFull
from .memory import bounded, unbounded
from .metrics import (
    InMemoryMetrics, MetricsHook, NoOpMetrics,
    get_default_metrics, set_default_metrics,
)
from .persistent import Outbox, DurableSender, wrap_with_outbox
from .redis import redis_channel
from .serializer import JSONSerializer, Serializer, StringSerializer, DEFAULT_SERIALIZER

__all__ = [
    # core
    "Backbone", "Channel", "Receiver", "Sender",
    "ChannelClosed", "ChannelEmpty", "ChannelFull",
    # factories
    "bounded", "unbounded", "redis_channel",
    # durability
    "Outbox", "DurableSender", "wrap_with_outbox", "DeadLetterQueue",
    # policies
    "BackoffPolicy", "ExponentialBackoff", "FixedBackoff", "DEFAULT_BACKOFF",
    # serialization
    "Serializer", "JSONSerializer", "StringSerializer", "DEFAULT_SERIALIZER",
    # metrics
    "MetricsHook", "NoOpMetrics", "InMemoryMetrics",
    "get_default_metrics", "set_default_metrics",
]
