"""The journal as a Nautilus Actor: one writer, off the decision's stack.

A sink, which is why this is an Actor and not a data client: a data client
brings external history *in* and this takes our own reasoning *out*. There is
no `ExecutionClient` for "why we refused".

## Why a buffer rather than a write per message

**Nautilus's bus is synchronous.** `MessageBus.publish` loops over the matched
subscriptions and calls `sub.handler(msg)` directly - checked in
`common/component.pyx`, 1.231 - so this actor's handler runs *inside* the
publisher's call, on the stack of the strategy that just decided something.
Two consequences, and both are the whole design:

* A SQLite write in the handler is a disk write in the middle of a decision.
  [ADR 0005](../../docs/adr/0005-the-journal-is-the-record-not-the-hot-path.md)
  is the rule it would break: the journal is the record, and a hot path never
  waits for it. So `on_entry` validates and appends to a bounded deque, and
  that is all it does.
* A handler that **raises** raises in the publisher. The retired
  `service.record` swallowed every failure for exactly this reason - "a full
  disk should cost you the record, not the collector" - and here the collector
  is a live strategy. So nothing on this path raises, ever: a bad payload, a
  full buffer and a broken disk each produce a tally, and a writer that stays
  broken puts the component into `DEGRADED` where an operator can see it.

The write itself is a repeating `clock.set_timer` handing the batch to
`queue_for_executor`. In live the kernel registers a `ThreadPoolExecutor` and
the write leaves the event loop; in a backtest there is no executor and
`queue_for_executor` runs the call inline, which is the right behaviour - a
measurement should not depend on when a flush happened to land. **Not
`asyncio.to_thread`, not `asyncio.sleep` and not a thread of our own**: the
executor is where Nautilus puts blocking work, the clock is what makes the
actor behave identically in a backtest, and a journal with two writers is not
a journal with one.

## What it does not subscribe to, and why

`events.order.*` and `events.position.*` are real topics on the engine's bus
in 1.231 - `ExecutionEngine` and `OrderEmulator` publish to
`events.order.{strategy_id}`, and `Portfolio` and `RiskEngine` are already
subscribed to both - and this actor deliberately **does not take them**. Three
reasons, in the order they decide it:

1. **Nautilus already persists them, with better attribution.** `Cache` and
   its database hold every order, fill and position carrying the framework's
   own `strategy_id`, and `judge-the-desk-on-the-broker-not-the-journal` is the
   standing rule about which record wins on what happened. ADR 0005 allows two
   stores holding the same facts and names the journal authoritative only
   *after the fact*; copying the engine's events in here would create the
   disagreement without adding a reading.
2. **The value of the journal is the part nothing else has.** A refusal reason,
   the gate that stopped a proposal, the state the choice was made from. An
   order lifecycle is six events per order and would bury them - which is the
   split `strategies/desk.py` already draws between counted and journalled:
   "journal everything and the record is noise".
3. **An event carries no parent, so an entry made from one could never be
   paired.** `Entry.parent` is the only structure that turns a decision and
   what followed into a labelled example, and an outcome with no parent is
   dropped here for that reason. The engine's events belong to an order, not
   to a decision - the strategy that decided is the only thing holding both,
   and it is the thing that should publish.

So the topic list is `utils.topics.JOURNAL` and the subscription goes through
`topics.subscribe`, which is `msgbus.subscribe`. **`subscribe_data_dict` does
not exist on `Actor`** - three modules called it and every test passed because
each assigned the name, and assigning an attribute creates it. `topics.py`
carries that story and `test_nautilus_api.py` is what makes it a test.

`publish_data`/`subscribe_data` are the other framework route and are the wrong
one here: they want a `Data` subclass and a `DataType`, which is right for
market data and wrong for a dict of journal context. `publish_signal` carries a
single scalar. For an arbitrary payload on a named topic the mechanism is the
bus itself, which is what `topics.py` wraps.
"""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig

from till_infinity.utils import topics

from .models import Entry, Kind
from .store import DEFAULT_DB, Journal, get

#: The flush timer's name on the actor's clock. One name, so `on_stop` cancels
#: the timer it set rather than every timer on a shared clock.
FLUSH_TIMER = "journal-flush"


class JournalConfig(ActorConfig, frozen=True):
    """Where the record goes, and how long an entry waits to get there.

    Frozen and `ActorConfig`, which is what makes the actor addable both ways:
    `TradingNode.trader.add_actor` takes the instance and `BacktestRunConfig`
    takes an `ImportableActorConfig` naming these two classes and a dict of
    these fields. An actor that could only be built by hand could go in a live
    node and not in a backtest, and a backtest measuring a different set from
    production is the one failure the whole port exists to prevent.
    """

    #: Topics to journal. `JOURNAL` rather than a literal: `topics.publish`
    #: refuses an undeclared name, which is what catches a typo that would
    #: otherwise publish into silence.
    topics: tuple[str, ...] = (topics.JOURNAL,)
    path: str = DEFAULT_DB
    #: How long an entry can sit in memory before it is written.
    #:
    #: Five seconds, not milliseconds: the journal is read by reports and by
    #: research runs, never by a decision, so latency to the disk buys nothing
    #: and batching buys a single transaction per flush instead of one per
    #: refusal. What it costs is the last five seconds of entries if the
    #: process is killed, which is the trade ADR 0005 already makes.
    flush_seconds: float = 5.0
    #: How many entries may wait. A bound rather than `maxlen`, because an
    #: eviction `deque` performs silently is a lost record nobody counted -
    #: past this the entry is refused and `tally` says how many.
    #:
    #: 2,000 is about two hours of the live desk's journalled rate (hundreds a
    #: day of the refusals worth reading back, per `strategies/desk.py`), so
    #: reaching it means the writer has been failing for hours, not that a
    #: burst arrived.
    max_pending: int = 2_000
    #: Consecutive failed flushes before the component degrades.
    #:
    #: Three and not one, because `Trader._stop` only stops an actor that
    #: `is_running` and `DEGRADED` is not running - so a component that
    #: degrades on a single transient failure would miss its own `on_stop` and
    #: the final flush with it. Three flushes is fifteen seconds at the default
    #: interval, which distinguishes a locked file from a broken disk.
    degrade_after: int = 3


class JournalActor(Actor):
    """Writes down what the desk decided and why, from the bus."""

    def __init__(self, config: JournalConfig) -> None:
        super().__init__(config)
        self._cfg = config
        self._store = Journal(Path(config.path) if config.path else DEFAULT_DB)
        #: Entries waiting for the next flush, oldest first. **The only state
        #: this actor holds**, and it is its own - nothing here is a copy of
        #: anything in `self.cache`, which is where engine state is read from.
        self._pending: deque[Entry] = deque()
        #: Held across a write and across the close. The executor thread and
        #: the loop thread that runs `on_stop` are two threads reaching for one
        #: SQLite connection, and the close is the one that would win a race by
        #: invalidating what the other is using.
        self._lock = Lock()
        self._opened = False
        self._written = 0
        self._dropped = 0
        self._shed = 0
        self._failed: dict[str, int] = {}
        #: Consecutive failed flushes. Read on the loop thread by `_on_timer`
        #: and written on the executor thread by `_write`, which is why the
        #: *state transition* happens on the timer and not at the failure: the
        #: component FSM is the engine's and belongs on the engine's thread.
        self._consecutive_failures = 0

    # ----------------------------------------------------------- the lifecycle

    def on_start(self) -> None:
        """Open the store, subscribe, then start the flush timer.

        The store is opened here and not lazily, so a path that cannot be
        written says so at start rather than on the first refusal an hour in -
        and it is *not* fatal: an actor that cannot open its file still
        subscribes, still counts, and retries the open on each flush. A desk
        that will not trade because it cannot journal has the priority
        backwards.
        """
        self._open_store()
        for topic in self._cfg.topics:
            topics.subscribe(self, topic, self.on_entry)
            self.log.info(f"journalling {topic} to {self._store.path}")
        self.clock.set_timer(
            name=FLUSH_TIMER,
            interval=timedelta(seconds=max(0.1, self._cfg.flush_seconds)),
            callback=self._on_timer,
        )

    def on_stop(self) -> None:
        """Unsubscribe, cancel the timer, flush what is waiting, say the tally.

        The last flush is **direct and not queued**: a batch handed to the
        executor during shutdown would be written after the loop that drains it
        has gone.

        `msgbus.unsubscribe` and not a `topics` helper, because there is no
        helper to wrap it - the registry check `topics.subscribe` performs is
        about a name nothing publishes to, and by here the name is one this
        actor demonstrably subscribed to.
        """
        for topic in self._cfg.topics:
            self.msgbus.unsubscribe(topic=topic, handler=self.on_entry)
        if FLUSH_TIMER in self.clock.timer_names:
            self.clock.cancel_timer(FLUSH_TIMER)
        self._flush(direct=True)
        self.log.info(f"journal: {self.tally}")

    def on_reset(self) -> None:
        """Back to a fresh actor: the buffer and the tally go, the record stays.

        **The file is not touched**, and that is the point of the whole package:
        append-only, no update path, and an outcome is a new entry rather than
        an edit. A reset that emptied the journal would make it something you
        can rewrite by restarting a backtest.
        """
        self._pending.clear()
        self._written = self._dropped = self._shed = 0
        self._consecutive_failures = 0
        self._failed.clear()

    def on_dispose(self) -> None:
        """Release the connection. Terminal, so the last flush happens here too.

        `on_stop` has normally flushed already and this finds nothing; it is
        here because dispose is the one hook that is reached when a stop was
        skipped, and a file handle held by a disposed component is a leak the
        process only notices at the limit.
        """
        self._flush(direct=True)
        with self._lock:
            self._opened = False
            self._store.shut()

    def on_degrade(self) -> None:
        """Said out loud, because the alternative reads as a quiet market.

        A journal that has stopped writing and said nothing is worse than one
        that says so: every later "no entries for that hour" then looks like a
        desk that saw nothing, and this desk has already paid for that shape of
        error - a min-events guard dropped 141 of 146 feeds and made 0.9 sigma
        read as 4.8.
        """
        self.log.error(
            f"journal: DEGRADED after {self._consecutive_failures} failed "
            f"flush(es) to {self._store.path}; {len(self._pending)} entries "
            f"waiting, failures {self._failed}"
        )

    def on_resume(self) -> None:
        self.log.info(f"journal: writing again to {self._store.path}")

    def on_fault(self) -> None:
        """Terminal. Write whatever is still holdable and let go of the file.

        **Nothing here calls `fault()`**, deliberately: it cannot be reversed,
        and no failure this actor can see is irreversible - a full disk is
        emptied, an unmounted volume is mounted, a locked file is unlocked. A
        faulted journal could never resume, so one transient failure would end
        journalling for the life of the process. `degrade()` is the reversible
        half and is what `_on_timer` uses. This hook exists because the kernel
        may fault a component for reasons of its own.
        """
        self._flush(direct=True)
        with self._lock:
            self._opened = False
            self._store.shut()

    def on_save(self) -> dict[str, bytes]:
        """Nothing. The journal's durable state is the journal.

        Flushes first, so a save leaves the record current, and then returns an
        empty state on purpose. Serialising the pending entries into the
        engine's cache database would put the record in a second store that is
        not the record - which is exactly the disagreement ADR 0005 warns about
        when two things hold the same facts. The only state this actor keeps is
        at most `flush_seconds` of unwritten entries, and this makes that zero.

        It is also why `utils/codec.py`'s `ALIASES` needs no entry for anything
        here: nothing in `journal/` is a `Restorable` dataclass, nothing calls
        `codec.registry()` on the package, and the two modules that moved -
        `service.py` and `bus.py` - held functions rather than persisted
        classes.
        """
        self._flush(direct=True)
        return {}

    def on_load(self, state: dict[str, bytes]) -> None:
        """Nothing to restore. Says so if something arrives anyway."""
        if state:
            self.log.warning(
                f"journal: ignoring {sorted(state)} - the record is the file, "
                f"so this actor saves no state to load"
            )

    # -------------------------------------------------------------- the intake

    def on_entry(self, payload: Any) -> None:
        """One bus message. Never raises, and never touches the disk.

        This runs on the publisher's stack - see the module docstring - so the
        cost of journalling a decision is a dict validation and a deque append.
        """
        try:
            entry = Entry.from_message(payload)
            if entry is None:
                self._dropped += 1
                return
            if entry.kind is Kind.OUTCOME and not entry.parent:
                # It could never be paired with the decision it judges, so it
                # is not a training example - just noise. The retired
                # `service.outcome` refused this at the caller; the writer is
                # the right place for it now, because a publisher is a process
                # we did not write.
                self._dropped += 1
                return
            if len(self._pending) >= self._cfg.max_pending:
                self._shed += 1
                self._note_shed()
                return
            self._pending.append(entry)
        except Exception as exc:
            # Nothing above should raise - `from_message` returns None rather
            # than throwing - and this is here because the publisher is a
            # strategy mid-decision and a handler's exception is the
            # publisher's exception.
            self._dropped += 1
            self.log.warning(f"journal: could not read an entry off the bus: {exc}")

    @property
    def tally(self) -> dict[str, int]:
        """Written, dropped, shed and failed - the reading a report wants."""
        return {
            "written": self._written,
            "dropped": self._dropped,
            "shed": self._shed,
            "pending": len(self._pending),
            **self._failed,
        }

    # --------------------------------------------------------------- the write

    def _on_timer(self, event: Any = None) -> None:  # noqa: ARG002 - the TimeEvent is unused
        """The flush timer, then the component's state.

        Never raises: this is called by the engine's clock, on the loop.
        """
        try:
            self._flush()
            self._reconcile_state()
        except Exception as exc:
            self._note_failure("flush", exc)

    def _reconcile_state(self) -> None:
        """Put the component into the state its writer is actually in.

        Here and not at the failure, because `_write` runs on the executor
        thread and the component FSM is the engine's. One tick of latency,
        which against a five-second flush is the right place to pay it.
        """
        if self._consecutive_failures >= self._cfg.degrade_after and self.is_running:
            self.degrade()
        elif self._consecutive_failures == 0 and self.is_degraded:
            self.resume()

    def _flush(self, *, direct: bool = False) -> None:
        if not self._pending:
            return
        batch = list(self._pending)
        self._pending.clear()
        if direct:
            self._write(batch)
        else:
            # Sync and not a coroutine: the executor takes a plain callable and
            # runs them sequentially, which is what a single writer wants. The
            # store's own `async write` would need a loop this thread has not
            # got, and `asyncio.run` per batch would rebind its `asyncio.Lock`
            # to a new loop every time.
            self.queue_for_executor(self._write, (batch,))

    def _write(self, batch: list[Entry]) -> int:
        """Append one batch. Returns how many rows were new.

        A failure costs the batch and is counted. It is **not** retried: a disk
        that refuses one write refuses the next, and a queue that grows until
        it succeeds is how a journal takes down the process it records.
        """
        with self._lock:
            if not self._opened and not self._open_store():
                self._note_failure("unopened", f"no journal at {self._store.path}")
                return 0
            try:
                fresh = self._store.append(self._inherit(batch))
            except Exception as exc:
                self._note_failure(type(exc).__name__, exc)
                return 0
        self._written += fresh
        self._consecutive_failures = 0
        return fresh

    def _open_store(self) -> bool:
        try:
            self._store.connect()
        except Exception as exc:
            self._opened = False
            self.log.error(f"journal: could not open {self._store.path}: {exc}")
            return False
        self._opened = True
        return True

    def _inherit(self, batch: list[Entry]) -> list[Entry]:
        """Give an outcome its decision's tags where it was given none.

        Without this an outcome is invisible to a tag filter, which loses
        exactly the entry an analyst most needs - the one saying the thing it
        is looking at resolved itself last time.

        The parent is looked for **in this batch first**, because a decision and
        its outcome can arrive between two flushes and the decision would not
        be on disk yet. Only then is the store asked, which is a read on the
        executor and not on anybody's hot path.
        """
        if not any(e.kind is Kind.OUTCOME and not e.tags and e.parent for e in batch):
            return batch
        here = {entry.id: entry.tags for entry in batch}
        return [
            replace(entry, tags=here.get(entry.parent) or self._tags_of(entry.parent))
            if entry.kind is Kind.OUTCOME and not entry.tags and entry.parent
            else entry
            for entry in batch
        ]

    def _tags_of(self, parent: str) -> tuple[str, ...]:
        try:
            found = get(self._store.path, parent)
        except Exception:  # the parent may not be readable yet; tags are a bonus
            return ()
        return found.tags if found else ()

    # --------------------------------------------------------------- the noise

    def _note_failure(self, kind: str, detail: object) -> None:
        """Count a failure and log it occasionally.

        Occasionally rather than per failure: a disk that is full produces one
        line per entry otherwise, and a log nobody can read is the same as no
        log. The component state is what carries a persistent failure - see
        `_reconcile_state` - because a log line is not a thing anything else
        can read.
        """
        self._consecutive_failures += 1
        self._failed[kind] = self._failed.get(kind, 0) + 1
        seen = self._failed[kind]
        if seen in (1, 10, 100) or seen % 100 == 0:
            self.log.error(f"journal: {seen} failure(s) of {kind}: {detail}")

    def _note_shed(self) -> None:
        if self._shed in (1, 10, 100) or self._shed % 100 == 0:
            self.log.error(
                f"journal: {self._shed} entr(ies) refused - "
                f"{self._cfg.max_pending} are already waiting to be written"
            )


def publish(component: Any, entry: Entry) -> None:
    """Put one entry on the journal topic, from a strategy or an actor.

    The replacement for the retired `journal.bus.publish`, and the call a
    publisher should make: it is one line, it names the topic once, and
    `topics.publish` refuses a name nothing subscribes to.

    `component` is any `Actor` or `Strategy` - both carry `msgbus`. This does
    not raise on a failed write, because there is no write here: the entry is
    handed to `JournalActor`, which is the only thing that writes.
    """
    topics.publish(component, topics.JOURNAL, entry.to_dict())
