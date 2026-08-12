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

## Secrets

Credentials are read from the environment and never stored, logged or printed.
The Telegram token lives in the URL path, which keeps it out of payload dumps.
`notify targets` masks webhook URLs to host plus a short tail, and shows chat
ids in full — a webhook URL is a credential, while a chat id only names a room.
