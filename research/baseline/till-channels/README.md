# till-channels

Typed channels with a `Sender` and a `Receiver`, backed by asyncio in one
process or by Redis streams across several, plus a SQLite outbox that makes a
send survive the process that made it.

**Why this is a package and not part of `till-platform`.**
[ADR 0002](../../docs/adr/0002-services-are-self-contained.md) admits
infrastructure to `packages/` when removing it would leave two services
wanting the same thing. Channels passes that test - it is what `bus.py` is
built on, so every service depends on it transitively - but it is a different
*kind* of thing from the rest of the platform, and it has a dependency the
platform does not: `redis`. Folding it in would make every service that only
ever logs carry a Redis client in its manifest, as an extra it never asked
for. A package per dependency boundary is the cheaper arrangement.

**Why it is not a service.** `services/` is for things that run. A transport
nothing starts is a library.

## The Redis flip depends on this

The bus already takes a `redis_url` and swaps `bounded()` for
`redis_channel()` when it is set, which is what makes slice 5 of the
[layout spec](../../docs/specs/2026-10-28-services-layout-design.md) "one
variable". It is also the precondition for a service in another language: a Go
process cannot join an in-process Python channel, so until the bus speaks
Redis, `services/ticks` can only be the kind of job that never subscribes to
anything.

## The import name is `till_channels`, deliberately

The distribution is `till-channels` and the module is `till_channels`, not the
bare `channels` the old docstrings showed.

`channels` is Django Channels on PyPI, and a bare top-level name is a name
anyone can take. That is not hypothetical here: moving `statespace` out of the
desk promoted it to a top-level name, where it collided with one of the 375
single-word modules in `research/harness/` and broke the suite in a way that
depended on pytest's collection order. `till_platform` is prefixed for the
same reason, and the matching guards in
`tests/test_service_boundaries.py` assert that each one resolves to the
package in this directory rather than merely that it imports.

## What is here

| module | what it is |
| --- | --- |
| `backbone.py` | the `Channel`, `Sender` and `Receiver` protocols everything else implements |
| `memory.py` | `bounded()` and `unbounded()`, asyncio queues, one process |
| `redis.py` | `redis_channel()`, Redis streams with consumer groups |
| `persistent.py` | `Outbox` and `DurableSender`: a SQLite spool, drained on reconnect |
| `dlq.py` | where a message goes when it cannot be delivered |
| `backoff.py` | the retry policies the senders take |
| `serializer.py` | JSON and string codecs for the payloads |
| `metrics.py` | counters, with an in-memory default |
| `errors.py` | `ChannelClosed`, `ChannelEmpty`, `ChannelFull` |
