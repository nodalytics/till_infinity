# till-channels, retired 2026-10-31

Typed channels with a `Sender` and a `Receiver`, in memory or over Redis
streams, with a SQLite outbox. 1,133 lines.

**Retired because Nautilus owns the bus.** Its `MessageBus` is Rust-native,
with optional Redis backing and MessagePack serialisation, and the engine's
`Cache` holds the state this package's outbox existed to protect. Keeping both
would mean two transports with one job.

It had **one production importer**, `till_infinity/bus.py`, which used six
names from it: `bounded`, `redis_channel`, `Sender`, `Receiver`,
`ChannelClosed`, `ChannelFull`. `bus.py` now carries a small in-process queue
of its own for the legacy single-process path, and goes when `stack.py` and
the `prices` CLI group do.

## Worth keeping out of it

Four bugs were found and fixed here in the two days before retirement, by
running the Redis path for the first time. They are recorded because the same
mistakes are available to anyone building a transport, including Nautilus:

**The codec destroyed types.** `_encode` wrote every primitive with `str()`
and `_decode` handed the string back: 9 of 15 representative values came back
wrong, and `False`, `0` and `0.0` all became *truthy* strings. A guard written
`if payload["armed"]:` read one way in process and the other over Redis.

**`publish` wrote nothing without a local subscriber.** It looped the groups
*this* process had opened, and a collector subscribes to nothing it publishes.
The compose topology could not have worked.

**A new consumer group replayed the whole backlog**, because
`xgroup_create(id="0")` starts at the beginning - and here a message is a
notice rather than the data, so a service deployed into a running desk would
have folded ten thousand stale bars as live.

**Anchoring new groups at `$` then lost messages**, because group creation was
lazy: a subscriber that registered and waited had no group in Redis, so `$`
was evaluated at its first *read*. That one presented as a hang rather than a
failure.

And a fifth that was a security finding: **`close()` wrote a marker into the
shared stream**, and the reader that saw it re-published it - so one process
shutting down ended every reader in every other process, permanently. It was
unreachable until `publish` gained a send-only channel, which handed the most
frequently restarted process in the system the ability to stop everything that
listens to it.
