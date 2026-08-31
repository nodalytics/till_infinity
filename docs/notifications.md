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
one - a URL always has `:` and `/` before any `=`.

## Finding Telegram chat ids

```bash
uv run till-infinity notify chats
```

asks the bot which chats it can see and prints a ready-made export line. Two
caveats come from the API itself:

- `getUpdates` only covers the **last 24 hours**, so a chat the bot has been
  idle in will not appear - send it a message first;
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

`notify` returns one `Delivery` per channel and never raises - an alert that
reached the ops chat but not the Discord board is a partial success, and the
result says exactly that:

```
✓ telegram[ops]: sent
✗ discord[alerts]: failed (discord[alerts]: HTTP 404 unknown webhook)
```

## What the transports handle

**Rate limits.** Both providers answer 429 with the exact seconds to wait -
Telegram in `parameters.retry_after`, Discord in `retry_after`, either in a
`Retry-After` header. The wait is read from wherever it appears and capped at
`max_retry_after` so a hostile number cannot stall the process.

**Length.** Telegram rejects text over 4096 characters and Discord an embed
description over 4096; neither trims for you, so an over-long alert would
simply never arrive. Messages are truncated with a visible `[…]` marker.

**Escaping.** Telegram messages are HTML, not Markdown, because a stray
underscore or asterisk in a symbol name is a parse error in Markdown - and
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
continues - one unreachable webhook must not stop the next alert from reaching
the chat that is up. See [bus.md](bus.md).

## How a message is laid out

The first character says what kind of finding it is, because severity does not:
a stale feed and a level call are both `warning` and a reader wants to know
which before reading a word. Direction wins over shape when a signal claims one.

| | |
|---|---|
| 📈 📉 | a directional call, up or down |
| 📊 | a level finding with no direction claimed |
| 🌊 | the volatility regime changed |
| 💤 | a feed has stopped moving |
| ↔️ | a spread blew out |
| ⚡ | one venue is away from the consensus |
| 🧭 | the [score](../research/planned/score.md), when it exists |
| 🤖 | an agent finding |
| • ▲ ■ | nothing claimed - falls back to severity |

**The instrument's own symbol follows it**, because the two answer different
questions - *what happened*, and *to what* - and a phone notification is read
at a glance, where `📈 ₿` separates from `📈 €` before a word of the title has
been:

| | | | |
|---|---|---|---|
| 🥇 gold | ₿ btc | Ξ eth | ◎ sol |
| € eurusd | £ gbpusd | ¥ usdjpy | ₣ usdchf |
| A$ audusd | C$ usdcad | NZ$ nzdusd | 元 usdcnh |
| NDX us100 | SPX spx500 | | |

Currency signs where one exists, since that is what the instrument is called in
print. The dollar pairs carry their prefix - `A$`, `C$`, `NZ$` - because a bare
`$` would say nothing at the moment the distinction matters. **`元` for
offshore yuan rather than `¥`**, which would collide with the yen at exactly
the glance this exists for; a test pins that no two instruments share a symbol.
The indices take their tickers instead, because there is no symbol for an index
and a flag would say only "American", twice.

An instrument with no symbol keeps the plain icon rather than a placeholder
standing in for an answer we do not have.

Then the instrument, timeframe and direction lead the headline, and the
evidence sits underneath, one claim per line:

```
📉 🥇 GOLD 4h - down
level 3421.5

down 77% - against a 53% base rate
expected push -1.87v · risk 0.62v
9 touches here + 12 similar · strength 0.94
```

Two details worth stating. The probability is for **the direction being
claimed** - quoting P(up) beside a down call reads as the confidence in down
when it is the confidence against it - and the base rate moves with it, or the
pair is not a comparison. And the fields the filter routes on (`shape`,
`instrument`, `venue`, `direction`) are never printed back: they are already in
the headline, so `instrument: gold` under a line containing "GOLD" is the
machine talking to itself.

## Why a quiet channel may be a working one

Two changes deliberately reduce volume, and both look identical to a fault from
the outside.

**Costs.** An expected push is charged the median quoted spread before it is
allowed to qualify ([levels.md](levels.md#costs-come-off-before-anything-is-claimed)),
so edges that sit inside the spread no longer arrive. They were never takeable;
they only looked it.

**Confluence.** Three timeframes agreeing on one price now send **one** message
rather than three. Volume drops without a single finding being lost.

The check when a quiet channel worries you is `structures levels` and
`structures zones`: levels forming and calls logged means the gates are working.
The log line for each delivered alert also carries the first body line, so what
was *sent* can be compared against what was computed.

## Filtering: what a channel accepts

A channel people actually read is quiet most of the time. The detectors are not
quiet - a stale feed re-fires every few seconds for as long as it stays stale,
and a wide spread does the same. All of it belongs in the journal, where it is
evidence. Very little of it belongs on a phone.

Level routing (`info` / `warning` / `critical`) was the only filter there was,
and it is the wrong axis on its own: a stale feed and a level call can both be
`warning` while being completely different things to a reader. Four more, each
answering something the others cannot:

| variable | filters on | example |
|---|---|---|
| `NOTIFY_SHAPES` | kind of finding | `level,drift` - level calls and regime changes, nothing else |
| `NOTIFY_FEEDS` | instrument | `gold,btc` |
| `NOTIFY_COOLDOWN_S` | the same finding again | `900` - at most once per 15 minutes (default) |
| `NOTIFY_MAX_PER_HOUR` | everything, together | `20` (default) |

Shapes are the ones in [structures.md](structures.md#the-four-shapes) -
`level`, `stale`, `spread`, `dislocation`, `drift` - plus **`agent`**, which is
what an [agent](agents.md) finding carries. That last one matters: agents
publish to the same `alerts` topic, so a channel narrowed to `level,drift` drops
every analysis silently, which is the worst way for one to fail. Anything
publishing without a shape falls back to its `source`, taking the part before
the slash, so `agents/analyst` matches a filter naming `agents`.

```bash
NOTIFY_SHAPES=level,drift,agent
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
questions - the journal keeps everything either way, and a dropped alert is
logged with the reason at `debug`.

## Secrets

Credentials are read from the environment and never stored, logged or printed.
The Telegram token lives in the URL path, which keeps it out of payload dumps.
`notify targets` masks webhook URLs to host plus a short tail, and shows chat
ids in full - a webhook URL is a credential, while a chat id only names a room.
