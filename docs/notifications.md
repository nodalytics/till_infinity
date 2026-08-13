# Notifications

`till_infinity.notifications` sends alerts to Telegram and Discord. Each
provider fans out to as many channels as you list, so an on-call chat, a team
board and a firehose can all be fed from one call.

```bash
uv run till-infinity notify targets            # what is configured
uv run till-infinity notify chats              # discover Telegram chat ids
uv run till-infinity notify test               # prove the wiring
uv run till-infinity notify send "Gold spread blew out" -l warning
```

## Setup

```bash
export TELEGRAM_BOT_TOKEN=123456:AA...
export TELEGRAM_CHAT_IDS="ops=-1001111|critical, feed=-1002222"
export DISCORD_WEBHOOK_URLS="alerts=https://discord.com/api/webhooks/1/x, https://.../2/y"
```

An entry is `[label=]address[|min-level]`:

| part | |
|---|---|
| `label` | optional name, used in logs and delivery reports |
| `address` | a Telegram chat id, or a Discord webhook URL |
| `min-level` | `info` (default), `warning` or `critical` |

The level filter is what lets one bot serve both an on-call chat and a
firehose: a `critical` channel simply never sees the routine traffic.

A label must be a plain word, which is how `https://…` is never mistaken for
one — a URL always has `:` and `/` before any `=`.

## Finding Telegram chat ids

```bash
uv run till-infinity notify chats
```

asks the bot which chats it can see and prints a ready-made export line. Two
caveats come from the API itself:

- `getUpdates` only covers the **last 24 hours**, so a chat the bot has been
  idle in will not appear — send it a message first;
- it returns **409** while a webhook is registered, since the two delivery
  modes are mutually exclusive.

Set `TELEGRAM_AUTO_CHATS=1` to skip the list entirely and post to every chat
the bot can see. Convenient for a scratch setup, deliberately not the default:
whoever adds the bot to a group then chooses where your alerts go.

## Sending from code

```python
from till_infinity.notifications import Level, Notification, notify

await notify(
    Notification(
        title="Gold spread blew out",
        body="OANDA 4.2bps vs Pepperstone 0.2bps",
        level=Level.WARNING,
        fields={"instrument": "gold", "brokers": "6"},
        url="https://example.com/chart",
    )
)
```

`notify` returns one `Delivery` per channel and never raises — an alert that
reached the ops chat but not the Discord board is a partial success, and the
result says exactly that:

```
✓ telegram[ops]: sent
✗ discord[alerts]: failed (discord[alerts]: HTTP 404 unknown webhook)
```

## What the transports handle

**Rate limits.** Both providers answer 429 with the exact seconds to wait —
Telegram in `parameters.retry_after`, Discord in `retry_after`, either in a
`Retry-After` header. The wait is read from wherever it appears and capped at
`max_retry_after` so a hostile number cannot stall the process.

**Length.** Telegram rejects text over 4096 characters and Discord an embed
description over 4096; neither trims for you, so an over-long alert would
simply never arrive. Messages are truncated with a visible `[…]` marker.

**Escaping.** Telegram messages are HTML, not Markdown, because a stray
underscore or asterisk in a symbol name is a parse error in Markdown — and
instrument names are full of both. Everything interpolated is escaped.

**Failures that look like successes.** Telegram can answer HTTP 200 with
`{"ok": false}`; that is treated as the failure it is. A Discord webhook
answers 204 with an empty body, so there is nothing to parse on success.

## Listening on the bus

Alerts do not have to come from your own code. `notify listen` subscribes to
the `alerts` topic and delivers whatever an agent publishes there:

```bash
uv run till-infinity notify listen --redis redis://localhost:6379
```

Nothing off the bus is trusted: a payload with no title is dropped rather than
sent as an empty alert, `fields` is flattened to strings, and an out-of-range
level is clamped instead of raising. A failed delivery is logged and the loop
continues — one unreachable webhook must not stop the next alert from reaching
the chat that is up. See [bus.md](bus.md).

## Filtering: what a channel accepts

A channel people actually read is quiet most of the time. The detectors are not
quiet — a stale feed re-fires every few seconds for as long as it stays stale,
and a wide spread does the same. All of it belongs in the journal, where it is
evidence. Very little of it belongs on a phone.

Level routing (`info` / `warning` / `critical`) was the only filter there was,
and it is the wrong axis on its own: a stale feed and a level call can both be
`warning` while being completely different things to a reader. Four more, each
answering something the others cannot:

| variable | filters on | example |
|---|---|---|
| `NOTIFY_SHAPES` | kind of finding | `level,drift` — level calls and regime changes, nothing else |
| `NOTIFY_FEEDS` | instrument | `gold,btc` |
| `NOTIFY_COOLDOWN_S` | the same finding again | `900` — at most once per 15 minutes (default) |
| `NOTIFY_MAX_PER_HOUR` | everything, together | `20` (default) |

Shapes are the ones in [structures.md](structures.md#the-four-shapes) —
`level`, `stale`, `spread`, `dislocation`, `drift` — plus the `source` of
anything an agent publishes without one.

```bash
NOTIFY_SHAPES=level,drift
NOTIFY_FEEDS=gold,btc
NOTIFY_COOLDOWN_S=1800
NOTIFY_MAX_PER_HOUR=10
```

Four details that are deliberate:

- **Everything is allowed by default.** An allowlist nobody set is not applied.
  A filter that silently drops things nobody configured is worse than the noise.
- **The cooldown is per finding**, keyed on `(shape, instrument, venue)`. Gold
  going quiet does not silence BTC.
- **A dropped alert does not consume an hourly slot**, so a shape nobody wants
  cannot crowd out one they do.
- **The hour rolls** from each alert rather than resetting on the clock hour,
  which would let twenty through at 10:59 and twenty more at 11:00.

The filter sits in the `notify listen` consumer, not at the publisher. What is
worth *recording* and what is worth *interrupting someone with* are different
questions — the journal keeps everything either way, and a dropped alert is
logged with the reason at `debug`.

## Secrets

Credentials are read from the environment and never stored, logged or printed.
The Telegram token lives in the URL path, which keeps it out of payload dumps.
`notify targets` masks webhook URLs to host plus a short tail, and shows chat
ids in full — a webhook URL is a credential, while a chat id only names a room.
