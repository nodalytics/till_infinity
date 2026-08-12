# The message bus

`till_infinity.bus` is how services talk to each other. Collectors announce
what they just stored, agents consume it and publish alerts, notifications
deliver those.

```
prices  ──┐                        ┌──▶ notifications
          ├──▶ bus ──▶ agents ──▶ bus
news    ──┘
```

## What it carries

**A notice that something happened, not the data itself.** The SQLite stores
stay the source of truth; the bus says "gold moved on OANDA" and the subscriber
reads the store for the detail. That is why a dropped message costs latency
rather than history — nothing is lost, the consumer just finds out by querying
instead of by being told.

| topic | published when | payload |
|---|---|---|
| `prices.bars` | a candle sweep wrote or corrected rows | source, feed, venue, ticker, interval, inserted, updated, time, close, closed |
| `prices.quotes` | a broker's top of book changed | source, feed, venue, ticker, bid, ask, mid, spread_bps, time |
| `news.articles` | a headline is seen for the first time | source, provider, title, url, published, symbols, urgency |
| `news.events` | a calendar entry appears, **and again when it prints** | source, country, title, time, importance, actual, forecast, previous, unit, released |
| `news.macro` | a macro pull changed rows | source, inserted, updated, rows |
| `structures.signals` | an online model found something unusual | shape, feed, venue, score, detail, features, interval |
| `alerts` | an agent or a model wants a human told | title, body, level, url, fields |

Macro is a count rather than a row per observation on purpose: one IMF pull is
~15,000 rows of historic reserves, and announcing each would be noise. The
notice says the series changed; `reserves()` says what it changed to.

## Publishing

Collectors publish **in addition to** storing, and always **after** the store
write. Nothing is announced that cannot already be read back.

```bash
uv run till-infinity prices collect --publish redis://localhost:6379
uv run till-infinity news collect   --publish redis://localhost:6379
uv run till-infinity notify listen  --redis   redis://localhost:6379
```

Without `--publish` there is no bus at all — the seam costs nothing when
nobody is listening. Bare `--publish` falls back to `TILL_REDIS_URL`, and to an
in-process bus when that is unset (useful only when publisher and subscriber
share a process).

## Fan-out is per group, not per subscriber

A channel's `recv()` is **work-sharing**: two consumers reading one channel
split the messages between them. That is right for scaling one consumer across
workers and wrong for two different services watching the same topic. So each
group gets its own channel, and `publish()` writes to every one:

```python
agents = bus.subscribe(bus.QUOTES, group="agents")  # sees every quote
audit = bus.subscribe(bus.QUOTES, group="audit")  # also sees every quote
```

Two readers in the *same* group still share the work, which is how you run the
consumer on more than one worker. It is exactly Redis consumer-group semantics,
which the Redis backend gives for free — one stream per topic, one group per
subscriber.

## A slow consumer never stalls a collector

Publishing is `try_send`: if a subscriber's channel is full the message is
dropped with a warning and the collector carries on. A quote stream that
outruns an agent must not become backpressure on the socket that feeds it.

Raise `capacity` if you would rather buffer more:

```python
Bus(capacity=10_000)
```

## From code

```python
import asyncio
from till_infinity.bus import ALERTS, QUOTES, Bus


async def main():
    bus = Bus(redis_url="redis://localhost:6379")

    async for message in bus.subscribe(QUOTES, group="agents"):
        if (message.payload.get("spread_bps") or 0) > 10:
            await bus.publish(
                ALERTS,
                {
                    "title": f"{message.payload['venue']} spread blew out",
                    "body": f"{message.payload['spread_bps']:.1f}bps on {message.payload['feed']}",
                    "level": "warning",
                },
                source="agents",
            )


asyncio.run(main())
```

`Message` carries `topic`, `payload`, `source` and `time`. `Message.from_dict`
returns `None` on junk rather than raising — anything can write to a Redis
stream, so nothing off the wire is trusted. The same applies to `alerts`: a
payload with no title is dropped rather than delivered as an empty message, and
`fields` is flattened to strings before a notifier ever sees it.

## Deduplication

The stores dedup on write but report only counts, so the news publisher keeps
its own bounded LRU of what it has announced — otherwise every poll would
re-announce the whole feed. Calendar events are marked on `(source, id, actual)`
rather than `(source, id)`, so an event announced as upcoming is announced again
the moment it prints. That second announcement is usually the interesting one.

## Who consumes what

| consumer | subscribes to | publishes |
|---|---|---|
| `structures watch` | `prices.quotes`, `prices.bars` | `structures.signals`, `alerts` |
| `agents watch` | `prices.quotes`, `prices.bars`, `news.events`, `news.articles` | `alerts` |
| `notify listen` | `alerts` | — |

`structures` reaches `alerts` directly, bypassing `agents`, for findings that
interpret themselves — a dead feed needs no model and no calendar, and should
not depend on one being reachable. See [structures.md](structures.md).

`news.macro` is deliberately not consumed: reserves move monthly, so a bulk row
count is not a reason to wake anything. See [agents.md](agents.md).

## Backends

| | in-memory | Redis |
|---|---|---|
| reaches | this process | any process |
| durability | none | Redis Streams |
| set with | default | `--publish redis://…` or `TILL_REDIS_URL` |

Redis is an optional dependency; install it with `uv add redis` if you need
cross-process delivery.
