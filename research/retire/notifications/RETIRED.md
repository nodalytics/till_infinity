# notifications/service.py, retired 2026-11-01

The notifications service's bus loop: `listen`, pulling `alerts` off a
`Carrier`, parsing, filtering, delivering and logging a per-channel tally -
plus the `notifications.delivered` effect declaration that sat beside it.

**Replaced by `till_infinity/notifications/actor.py`**, a Nautilus `Actor`.
This is a **partial** retirement, like `news`: 238 lines came out of the
package and 49 of them retired. The other 189 are the Telegram and Discord
fan-out, which no framework replaces - there is no `ExecutionClient` for
Telegram - so they moved rather than retiring.

| was | is |
|---|---|
| `listen`'s subscribe loop | `Notifier.on_start` → `topics.subscribe` → `msgbus.subscribe` |
| `await notify(...)` inside the loop | `queue_for_executor(self._deliver, ...)` |
| `notify`, `send_one`, `build_notifiers`, `discover_telegram_chats`, `NOTIFIERS` | `notifications/delivery.py` |
| `from_message`, `_image`, `MAX_IMAGE_BYTES` | `notifications/models.py`, beside the `to_dict` that is its inverse |
| `alert_filter.accept(payload)` | `Notifier._wanted`, on `self.clock` |
| `effects.declare("notifications.delivered")` | declared on the actor, fired when a channel accepted |
| the per-alert `log.info` tally | `Notifier.tally`, plus `degrade()` when nothing is being delivered |

**Why an Actor and not a data client**, which is the opposite of the call
`news` made. A sink, not a source: adapters bring external data *in* and this
takes the desk's own events *out*, so there is nothing for `_request` to
replay. The thing that *could* have gone wrong - a backtest posting to the
real ops chat - is handled by the executor running the send immediately and by
the node not configuring a token, not by the layer the code sits in.

## What the port had got wrong, and how it was found

Three defects, all of them invisible because **the actor had no tests at
all**. It is now `tests/test_notifier_actor.py`, 29 of them, every one
publishing through `nautilus_trader`'s own `MessageBus`.

* **`int(payload["level"])`.** The bus carries the level as a *word* -
  `Notification.to_dict` writes `"CRITICAL"`, every trading alarm publishes
  `"critical"` - so this raised `ValueError` on every real alert. Measured on
  a started actor: `tally == {"sent": 0, "dropped": 0, "prepare": 1}`. The
  alarm was counted as a parsing failure and gone. Fixed once in `_level` and
  it moved one method along, raising inside `from_message` on the executor
  instead; both now call `models.read_level`, which keeps an unreadable level
  as `WARNING` rather than raising.
* **`_emit` discarded what `notify` returned.** An alert whose every channel
  answered "HTTP 404 unknown webhook" was tallied as `sent`. The one reading
  that says whether anybody was told said yes.
* **The filter was wired to nothing.** `Filter` - the shape gate, the
  instrument gate, the hourly ceiling and the `critical` bypass that
  `tests/test_critical_alerts.py` is entirely about - was applied by `listen`.
  The actor replaced it with a level check and a title-keyed `_seen` dict of
  its own, which was also unbounded: a node up for a month held every alert
  title it had ever sent.

## Worth keeping out of it

**The hourly cap was refusing the alarm, and the cap is not retired.** Wiring
`Filter` back onto the live path immediately failed a new test, and the cause
is the same off-by-a-word that `test_critical_alerts.py` exists for:
`UNCAPPED` names `trade`, `Filter.key` falls back to the payload's **source**
when there is no shape field, and trading's source is `trading`. Measured - 20
gold level calls in an hour and then `AutoTrading is off` - the filter
answered `20 already sent this hour`. The desk down, the channel full of level
calls, and the budget refusing the one message that mattered. A `critical`
alert is now outside the cap and still counts against it, so a burst of alarms
correctly quietens everything else. The cooldown still applies to `critical`,
which is a different job and is pinned by its own test.

**The bypass only recognised one of the two encodings the contract allows.**
`shared/contracts/bus/alerts.json` says a level is "a name or its ordinal",
and the bypass read `str(payload["level"]).lower() == "critical"` - so a
publisher sending `level: 2` got no bypass and was filtered like a topic
preference. Found by reading the contract against the gate rather than by a
failure. `Filter` and `from_message` now share one `models.read_level`.

**Two things the contract should say and does not.** `at` is read from the
payload by `Notifier._deliver` and the schema declares no `at` under
`additionalProperties: false`, so a producer stamping its own event time is
sending a field the contract forbids and the consumer uses - the note in
`shared/contracts/README.md` saying "sending it would do nothing" is now
false. And every `notifications.service.*` reference in the schema's prose
points at this file.

**`listen` awaited the send inside the loop, and that is the structural
difference.** One Telegram timeout stalled every alert queued behind it, and
an exception anywhere in the body ended the loop and with it the service -
`Level.parse` on one misspelled level would have done it. The Actor returns
from the handler before the send starts and counts a failure instead, because
the handler is on the path that decides trades and an alert is worth less than
the desk it is about.

**No test came here.** Every live test of this file tested the delivery half,
which moved, and the tests that exercised `listen` itself were already
retired: `research/retire/bus/tests/test_stack.py` (which asserts
`callable(nt.listen)` and will now fail if anyone runs it) and
`research/retire/structures/tests/test_notification_filters.py`. So
`research/retire/notifications/` has no `tests/` directory - the claim "it
worked when it was removed" is checkable by reading, and `listen` imports the
live package rather than a frozen copy of it.
