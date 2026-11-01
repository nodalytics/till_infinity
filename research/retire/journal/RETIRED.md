# `journal/service.py` and `journal/bus.py`, retired 2026-11-01

307 lines, and the **last two modules of that shape on the desk's write
path**: `statespace/service.py` is now the only `service.py` left in the tree,
and it is a fold that publishes a reading rather than anything that writes. A *partial* retirement, like `news`: the store, the entry and the
ledger stayed in `till_infinity/journal/`, because they are the record and the
record is not going anywhere. What went is everything that was about being a
service - the helper per entry kind, and a transport.

Replaced by `till_infinity/journal/actor.py`, a Nautilus `Actor`.

## What replaced what

| retired | replaced by |
|---|---|
| `service.record`'s bus-or-write choice | `JournalActor`, the only writer there is |
| `service.decide` / `observe` / `outcome` / `note` | `Entry(kind=...)` and `actor.publish`, one call |
| `service.open_journal`'s `None` for "off" | not adding the actor |
| `service._inherited_tags` | `JournalActor._inherit`, which also reads the pending batch |
| `service.outcome`'s parentless guard | the same rule in `on_entry`, enforced at the writer |
| `service.record`'s "never take down the caller" | `on_entry` and `_write`, which cannot raise at all |
| `bus.publish` | `actor.publish`, which is `topics.publish` |
| `bus.listen`'s loop over a `Carrier` | `topics.subscribe` plus a `clock.set_timer` flush |
| `bus.from_message` / `to_message` | `Entry.from_message` and the existing `Entry.to_dict` |
| `bus.DEFAULT_GROUP` | nothing: Nautilus's bus has no consumer groups |

## Three guarantees had to be re-earned, not just moved

This is the part worth reading. Each of these was a property of the retired
code that nothing in the Actor gave for free.

**"Never take down the caller" got stronger, because the caller got closer.**
`record` logged and returned on failure so that "a full disk should cost you
the record, not the collector". Nautilus's bus is **synchronous** -
`MessageBus.publish` calls each `sub.handler(msg)` directly, checked in
`common/component.pyx` for 1.231 - so the handler now runs *on the stack of the
strategy that just decided something*. A raise in `on_entry` is a raise inside
a live `decide`. The same sentence, with the collector replaced by the desk.

**The context copy moved into `Entry`.** `decide` did `dict(context or {})`,
and that copy is the difference between a dataset and a leak: the stores keep
moving, and an entry holding the caller's dict describes whatever the world
looked like whenever the row was finally written. Two of the three ways to
build an `Entry` copied and the third - calling the constructor, which is what
a test and a script do - did not. It is `Entry.__post_init__` now, and it
matters *more* than it did: an entry waits up to `flush_seconds` in the
actor's buffer, where `record` wrote it on the next line.

**Tag inheritance had to learn about the batch.** `_inherited_tags` read the
store for the parent's tags, and the store was current because `record` wrote
the decision before returning. The Actor batches, so a decision and a fast
outcome can arrive between two flushes - and a store-only lookup would have
silently dropped the tags of exactly the quickest resolutions, which is the
subset an analyst is most likely to be looking at.

## What the Actor does that the service could not

**The flush is a `clock.set_timer`, so a backtest and a live node behave
identically.** The retired path was a `listen()` coroutine a CLI command had to
run - `journal listen` - which is why there was a second way to run the desk at
all. `till.env needs a container recreate` is the lesson about two ways to
change one thing: one goes silently stale.

**A writer that stays broken degrades the component.** `record` logged a
warning per failure and that was the whole signal. Three consecutive failed
flushes now put the actor into Nautilus's `DEGRADED` state, which is a thing
something other than a log reader can see - and a journal that has silently
stopped writing is worse than one that says so, because every later "no
entries that hour" reads as a quiet market.

Three and not one, for a measured reason: `Trader._stop` only stops an actor
that `is_running`, and `DEGRADED` is not running. A component that degraded on
a single transient failure would skip its own `on_stop` and the final flush
with it. `degrade()` and never `fault()`, because a fault cannot be undone: one
full disk would end journalling for the life of the process.

**It writes one transaction per flush rather than one per entry.** 500
journalled refusals cost 500 dict validations and one `executemany`.

## Why the Actor does not subscribe to `events.order.*`

Asked and decided against, and the reasoning is in the module docstring. In
short: the engine already persists orders, fills and positions with its own
`strategy_id`, `judge-the-desk-on-the-broker-not-the-journal` says that is the
record of what *happened*, and ADR 0005 makes the journal authoritative only
after the fact. The journal's value is the half nothing else holds - the
refusal, the gate, the state the choice was made from - and an order event
carries no `parent`, so an entry made from one could never be paired with the
decision it followed.

## The tests

15 of the 31 tests in `tests/test_journal.py` were about these two modules and
are in `tests/test_journal_service.py` beside them. The suite kept 22 (the
store and the entry, rewritten to construct an `Entry` rather than reach
through three modules to get one) and gained 32 in
`tests/test_journal_actor.py`.

## Left behind, and flagged rather than quietly removed

* **`journal` has no publisher in the live tree.** Nothing in
  `till_infinity/` calls `topics.publish(..., topics.JOURNAL, ...)`: the desk's
  refusals are counted in `Desk.passed_over` and logged at debug, and
  `strategies/desk.py` says in prose which ones "the journal records" without
  anything recording them. That is a topic with a subscriber and no producer -
  the mirror of the bug shape `statespace.proposals` and
  `statespace.signals` have both been through - and it is the one piece of work
  this retirement leaves open. `actor.publish` is the one-line call site for
  it.
* **The journal actor is not registered by any node.** `node/desks.py` has
  both shapes an actor needs (`actors` for the live node, `importable_actors`
  for a backtest) and neither names `JournalActor` yet.
  `test_journal_actor.py::test_the_config_is_importable_so_a_backtest_can_name_it`
  is what makes the second one possible.
* **Eight already-retired files now have a dead import of these two
  modules**, found with
  `grep -rln 'journal\.bus\|journal import.*decide' research/retire/`:
  `agents/{service,tools}.py`, `bus/tests/{test_bus_contracts,test_trading}.py`,
  `strategies/service.py`, `structures/engine/service.py` and
  `structures/strategies/test_{scalper,swing}_strategies.py`. Every one is
  already out of CI and every one already imports something else that has gone,
  which is the state `research/retire/structures/tests/` has been in since
  2026-10-31. Nothing live imports either module - checked with
  `grep -rn 'journal' --include=*.py till_infinity/ tests/`.
* **`shared/contracts/bus/journal.json`** in `research/retire/bus/` is the wire
  schema for this topic. The payload is unchanged - it is `Entry.to_dict()`,
  the same dict `to_message` returned - so the schema still describes what goes
  on the bus, now through Nautilus's.
* **`ledger.py` stayed and has no live caller.** It reads closed-trade outcomes
  out of the journal by SQL and is the answer to "which levels have been
  profitable"; its only importer was the retired CLI. Kept because it reads the
  record rather than running beside it, which is the shape ADR 0005 says
  belongs on the journal.
