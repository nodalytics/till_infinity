# redis

The broker the bus runs on. **Configuration, no code.**

[ADR 0002](../../docs/adr/0002-services-are-self-contained.md) puts a broker
here rather than in `packages/`: `services/` is for things that run, and this
runs - it just is not something we write. The client side is
[`packages/till-channels`](../../packages/till-channels/README.md); this is
the server it talks to.

## What it is for

One Redis stream per topic, one consumer group per subscriber, which is how
`Bus.publish` fans out to several readers without copying. `bus.key(topic)`
is the stream name (`till:prices.quotes`), and the group is the subscriber's
own name - so the key deliberately does **not** include the group.

## Why this exists at all

With `TILL_REDIS_URL` unset the bus is an in-process asyncio queue, which is
correct for one `till-infinity run` and useless across processes. Two things
need more than that:

1. **One process per service**, so a crash in one does not take the desk down.
2. **A service in another language.** A Go process cannot join an in-process
   Python channel. Until the bus speaks Redis, `services/ticks` can only be
   the kind of job that never subscribes to anything.

## The settings that are decisions rather than defaults

`appendonly` and `appendfsync everysec`, because collectors do not resend:
`publish` uses `try_send`, so a dropped message is gone and nothing replays
it.

`maxmemory-policy noeviction`, so a subscriber that stops reading produces a
visible write error rather than Redis silently dropping entries of whichever
key it chooses. For a bus, eviction means losing messages with no record of
which ones.

See the comments in `redis.conf` for the rest.
