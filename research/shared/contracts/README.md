# Contracts

What both sides of a boundary must agree on.
[ADR 0002](../../docs/adr/0002-services-are-self-contained.md): `shared/` holds
these and not utilities, because a Python library every service links against
is the thing `services/` exists to prevent. A contract one side cannot parse is
not a contract, so these are **files** - JSON and Markdown - rather than Python
objects.

| | |
| --- | --- |
| [`ticks.md`](ticks.md) | the tick corpus on disk: layout, schema, and what `flags` can and cannot say |
| [`bus/`](bus) | one JSON Schema per bus topic, named for the topic |

## The bus schemas

`bus/<topic>.json`, where the file name **is** the topic and `$id` repeats it.
Both are checked against each other, because a renamed file with a stale `$id`
would load and validate the wrong thing.

Read them from Python with `till_infinity.shared.contracts`; read them from Go
by reading the file. That asymmetry is the point.

**`additionalProperties` is `false` almost everywhere.** A schema that tolerates
unknown fields cannot tell you a producer has started sending something, which
is half of what a contract is for.

## What makes these true rather than plausible

`tests/test_bus_contracts.py` validates payloads built by the **real
producers**, not by the test. It also keeps two lists honest, on the same
bargain as `tests/test_service_boundaries.py`'s `DEBTS` - the list can only
shrink, and a stale entry fails too:

* **`UNDECLARED`** - every topic in `bus.TOPICS` with no schema, and why. A new
  topic cannot arrive undeclared.
* **`RISK_DEBTS`** - fields a producer still sends that
  [ADR 0004](../../docs/adr/0004-risk-rules-have-one-owner.md) says it must
  not. `statespace.proposals` carries `stop_vol` and `target_r`, which are risk
  **decisions**: harmless while one Python process owns both ends, and a real
  position sized by untested code the moment the producer is another runtime.
  They are described in the schema as debts and asserted here by name, so
  removing one from the producer is a change that shows up rather than one that
  is forgotten.

## Declared so far

`alerts`, `journal`, `prices.bars`, `prices.quotes`,
`statespace.dispersion`, `statespace.proposals`.

`structures.*` is deliberately absent - that service is being retired, and a
contract for it would be thrown away with it. `statespace.signals` is absent
because its producer was switched off when its only consumer retired. The
`news.*` topics have no cross-language consumer yet.

## Two topics have more than one producer

`alerts` is published by **trading** and, until it retires, by
**structures** - and `journal` by anything that records a decision. That is
where a schema earns its keep: two producers drifting apart on one topic is a
failure nobody notices, because each one keeps working. Both alert shapes are
validated against the same schema in the tests, so a drift fails there.

## Gaps these schemas exposed

Writing them down found three things that were not visible before:

* **`bus.TOPICS` did not declare `statespace.proposals`** - the topic the desk
  now trades on. The subscriber list in `trading.service` had been updated and
  the bus's own registry had not.
* **`Notification.at` cannot be set from the bus.** The field documents that "a
  caller that knows the event's own time should pass it", and
  `notifications.service.from_message` never reads `at` from the payload - so
  every alert is stamped when it was *rendered*, which for a delivery delayed
  by a retry is the retry. The schema does not declare `at` because sending it
  would do nothing.
* **`fields` values are flattened to strings** by the consumer, so a nested
  object sent there arrives as its Python repr. The schema restricts them to
  scalars rather than letting a producer believe otherwise.
