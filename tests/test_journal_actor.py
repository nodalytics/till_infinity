"""`JournalActor`: the single writer, and what it must not be able to break.

The last `service.py` in the tree became this on 2026-11-01. What these tests
are for is the part that is *ours*: that the subscription is real, that an entry
published on the engine's bus lands in the store, and - the property the whole
shape exists for - that publishing a decision costs the strategy that decided
it nothing it can notice and nothing it can be killed by.

**Nautilus's bus is synchronous.** `MessageBus.publish` calls each matched
`sub.handler(msg)` on the publisher's stack, so `on_entry` runs *inside* the
decision. Every test below that says "does not take the desk down" is about
that: a handler that raises raises in the strategy, and the desk is what is
lost. `research/retire/journal/tests/test_journal_service.py` holds the same
guarantee as it was written against `service.record`.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorFactory, ImportableActorConfig
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.trading.strategy import Strategy

from till_infinity.journal import Entry, Kind, read
from till_infinity.journal.actor import FLUSH_TIMER, JournalActor, JournalConfig, publish
from till_infinity.utils import topics

ACTOR_FILE = (
    pathlib.Path(__file__).resolve().parent.parent / "till_infinity" / "journal" / "actor.py"
)
ACTOR_SOURCE = ACTOR_FILE.read_text()
#: Parsed and not matched. The line form of this check read "asyncio.sleep"
#: out of the module *docstring* - the paragraph saying it is not used - and
#: called it a breach. A docstring that names a mechanism in order to rule it
#: out is not that mechanism, and only a parser knows the difference;
#: `test_service_boundaries.desk_imports` learned the same thing.
ACTOR_TREE = ast.parse(ACTOR_SOURCE, filename=str(ACTOR_FILE))


def imported_in_the_actor() -> set[str]:
    """Top-level module names `journal/actor.py` imports."""
    found: set[str] = set()
    for node in ast.walk(ACTOR_TREE):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            found.add((node.module or "").split(".")[0])
    return found


def self_attributes_in_the_actor() -> set[str]:
    """Every `self.x` the module touches, read or written."""
    return {
        node.attr
        for node in ast.walk(ACTOR_TREE)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    }


def journal_actor(tmp_path, **settings) -> tuple[BacktestEngine, JournalActor]:
    """A registered, started actor over a scratch journal.

    Registered through a `BacktestEngine` rather than constructed alone,
    because an unregistered `Actor` has no `msgbus` - and a test that stubbed
    one would be testing the stub. This is the mechanism `test_topics.py` and
    `test_nautilus_api.py` exist to keep honest.
    """
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="TESTER-001",
            logging=LoggingConfig(bypass_logging=True),
        )
    )
    actor = JournalActor(JournalConfig(path=str(tmp_path / "journal.db"), **settings))
    engine.add_actor(actor)
    actor.start()
    return engine, actor


def decision(title: str = "d", **fields) -> Entry:
    base = {"title": title, "kind": Kind.DECISION, "rationale": "r"}
    return Entry(**(base | fields))


class Failing:
    """A store that will not write. Counts what it was asked to do."""

    def __init__(self, path, error: Exception | None = None) -> None:
        self.path = path
        # Built here and not in the signature: an exception instance in a
        # default argument is one object shared by every test in the file,
        # which is also what B008 is about.
        self.error = error or OSError("no space left on device")
        self.calls = 0

    def connect(self) -> None:
        pass

    def shut(self) -> None:
        pass

    def append(self, batch) -> int:
        self.calls += 1
        raise self.error


class Counting:
    """A store that writes nowhere and says how often it was asked."""

    def __init__(self, path) -> None:
        self.path = path
        self.calls = 0
        self.rows = 0

    def connect(self) -> None:
        pass

    def shut(self) -> None:
        pass

    def append(self, batch) -> int:
        self.calls += 1
        self.rows += len(batch)
        return len(batch)


# ------------------------------------------------------------ the subscription


def test_the_journal_is_an_actor_and_not_a_strategy(tmp_path):
    """It writes a record and places no orders, so it has no `strategy_id` to
    attribute anything to - and an Actor is what Nautilus calls that.
    """
    _, actor = journal_actor(tmp_path)
    assert isinstance(actor, Actor)
    assert not isinstance(actor, Strategy)
    assert not hasattr(actor, "order_factory")


def test_it_subscribes_through_the_bus_and_not_a_method_nautilus_lacks(tmp_path):
    """`Actor.subscribe_data_dict` does not exist, and three modules called it.

    Every test passed, because each one *assigned* the name - and assigning an
    attribute creates it. So this reads the subscription off Nautilus's own
    `MessageBus`, which a stub cannot satisfy.
    """
    assert not hasattr(Actor, "subscribe_data_dict"), "revisit utils/topics.py"

    engine, actor = journal_actor(tmp_path)
    ours = [
        sub
        for sub in engine.kernel.msgbus.subscriptions()
        if getattr(sub.handler, "__self__", None) is actor
    ]
    assert [sub.topic for sub in ours] == [topics.JOURNAL]
    assert ours[0].handler == actor.on_entry


def test_it_does_not_journal_the_frameworks_own_order_and_position_events(tmp_path):
    """The decision, not the lifecycle - and the reason is which record wins.

    `events.order.*` and `events.position.*` are real topics in 1.231, and
    `Portfolio` and `RiskEngine` are already on both of them: the engine's
    `Cache` persists every order, fill and position with the framework's own
    `strategy_id`. `judge-the-desk-on-the-broker-not-the-journal` says that is
    the record of what happened, and ADR 0005 makes the journal authoritative
    only after the fact - so copying those events in here would buy a
    disagreement and no reading.

    What the engine has no field for is *why*: the refusal, the gate, the state
    the choice was made from. And an order event carries no `parent`, so an
    entry made from one could never be paired with the decision it followed -
    which is the same rule `test_an_outcome_with_no_parent_is_refused` holds.
    """
    engine, actor = journal_actor(tmp_path)
    framework = [
        sub.topic for sub in engine.kernel.msgbus.subscriptions() if sub.topic.startswith("events.")
    ]
    assert framework, "the engine publishes these, so the premise still holds"

    ours = [
        sub.topic
        for sub in engine.kernel.msgbus.subscriptions()
        if getattr(sub.handler, "__self__", None) is actor
    ]
    assert not [topic for topic in ours if topic.startswith("events.")]
    # And it could not reach them by accident: the registry refuses a name
    # nothing of ours publishes, which is what makes this a decision rather
    # than an omission.
    assert not [name for name in topics.DECLARED if name.startswith("events.")]
    with pytest.raises(ValueError, match="not a declared topic"):
        topics.subscribe(actor, "events.order.*", actor.on_entry)


# ----------------------------------------------------------------- the record


def test_an_entry_published_on_the_bus_reaches_the_store(tmp_path):
    _, actor = journal_actor(tmp_path)
    entry = decision("Refused gold at the spread", actor="EdgeEntry-GOLD", tags=("gold",))

    publish(actor, entry)
    actor._on_timer()

    stored = read(actor._store.path)
    assert [e.title for e in stored] == ["Refused gold at the spread"]
    assert stored[0].rationale == "r"
    assert stored[0].tags == ("gold",)
    assert actor.tally["written"] == 1


def test_the_flush_timer_is_what_writes_it(tmp_path):
    """The handler never writes, so if the timer is not wired nothing is ever
    recorded - and the actor would look healthy, because its own tally counts
    what it *accepted*. That is how `statespace.proposals` went unconsumed for
    weeks.
    """
    _, actor = journal_actor(tmp_path, flush_seconds=5.0)
    assert FLUSH_TIMER in actor.clock.timer_names

    publish(actor, decision("one"))
    for handler in actor.clock.advance_time(actor.clock.timestamp_ns() + 6_000_000_000):
        handler.handle()

    assert [e.title for e in read(actor._store.path)] == ["one"]


def test_two_publishers_of_one_decision_make_one_row(tmp_path):
    """Ids are recomputed from content, so a duplicate collapses.

    The id on the wire is ignored on purpose: a sender cannot claim one that
    does not match what it sent, and two strategies publishing the same call
    still make one entry.
    """
    _, actor = journal_actor(tmp_path)
    entry = decision("same call", actor="EdgeEntry-GOLD", time=1_000.0)

    publish(actor, entry)
    publish(actor, entry)
    actor._on_timer()

    assert len(read(actor._store.path)) == 1


def test_stopping_writes_what_is_still_waiting(tmp_path):
    """Up to `flush_seconds` of entries are in memory at any moment, and a
    clean stop is the one case where losing them is avoidable.
    """
    _, actor = journal_actor(tmp_path)
    publish(actor, decision("last thing before the stop"))
    assert actor.tally["pending"] == 1

    actor.stop()

    assert [e.title for e in read(actor._store.path)] == ["last thing before the stop"]
    assert FLUSH_TIMER not in actor.clock.timer_names


# --------------------------------------------------------------- the hot path


def test_journalling_a_decision_does_not_touch_the_disk(tmp_path):
    """ADR 0005: the journal is the record, and a decision never waits for it.

    The bus is synchronous, so this handler runs inside the publisher - the
    `pending` count being 1 the instant `publish` returns is that fact. What
    the decision pays is a dict validation and a deque append; the row appears
    only once the flush runs.
    """
    _, actor = journal_actor(tmp_path)

    publish(actor, decision("a decision mid-bar"))

    assert actor.tally["pending"] == 1, "the handler ran on the publisher's stack"
    assert actor.tally["written"] == 0
    assert read(actor._store.path) == [], "nothing was written on the decision's stack"

    actor._on_timer()
    assert len(read(actor._store.path)) == 1


def test_five_hundred_entries_are_one_transaction(tmp_path):
    """The reason to buffer rather than write per message, as a number.

    500 journalled refusals cost 500 dict validations and **one** SQLite
    transaction. Written per message they would be 500, each one a commit on
    the stack of whichever strategy was deciding at the time.
    """
    _, actor = journal_actor(tmp_path)
    store = Counting(actor._store.path)
    actor._store = store

    for n in range(500):
        publish(actor, decision(f"refusal {n}", time=float(n)))

    assert store.calls == 0, "not one write while the desk was deciding"
    assert actor.tally["pending"] == 500

    actor._on_timer()
    assert store.calls == 1
    assert store.rows == 500


# -------------------------------------------------------------- the resilience


def test_a_write_failure_does_not_take_the_desk_down(tmp_path):
    """A full disk should cost you the record, not the strategy writing it.

    `service.record` carried this guarantee as "never take down the caller",
    and the caller is now literally on the other end of a synchronous bus
    call: an exception out of `on_entry` or out of the flush is an exception
    inside a strategy's `decide`.
    """
    _, actor = journal_actor(tmp_path)
    store = Failing(actor._store.path)
    actor._store = store

    publish(actor, decision("the disk is full"))  # must not raise
    actor._on_timer()

    assert store.calls == 1
    assert actor.tally["written"] == 0
    assert actor.tally["OSError"] == 1

    # And it is still taking entries, rather than having wedged itself.
    publish(actor, decision("the next one"))
    assert actor.tally["pending"] == 1


def test_a_failed_batch_is_not_retried_forever(tmp_path):
    """A queue that grows until the write succeeds is how a journal takes down
    the process it is recording. The batch is counted and dropped.
    """
    _, actor = journal_actor(tmp_path)
    actor._store = Failing(actor._store.path)

    publish(actor, decision("one"))
    actor._on_timer()
    actor._on_timer()

    assert actor._store.calls == 1, "the second flush had nothing left to try"
    assert actor.tally["pending"] == 0


def test_the_buffer_is_bounded_when_the_writer_keeps_failing(tmp_path):
    """Otherwise an unwritable disk is a memory leak with a tally.

    The bound is an explicit refusal rather than a `deque(maxlen=...)`: an
    eviction a deque performs is a lost record nobody counted, and
    `restore-drops-deque-maxlen` is the standing warning about trusting a
    declared bound.
    """
    _, actor = journal_actor(tmp_path, max_pending=5)
    actor._store = Failing(actor._store.path)

    for n in range(20):
        publish(actor, decision(f"refusal {n}", time=float(n)))

    assert actor.tally["pending"] == 5
    assert actor.tally["shed"] == 15


def test_a_journal_that_cannot_be_opened_does_not_stop_the_node(tmp_path):
    """A desk that will not trade because it cannot journal has the priority
    backwards. The failure is loud in the log and a number in the tally.
    """
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("")

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="TESTER-001",
            logging=LoggingConfig(bypass_logging=True),
        )
    )
    actor = JournalActor(JournalConfig(path=str(blocked / "journal.db")))
    engine.add_actor(actor)
    actor.start()  # must not raise

    publish(actor, decision("nowhere to put this"))
    actor._on_timer()

    assert actor.tally["written"] == 0
    assert actor.tally["unopened"] == 1


def test_junk_on_the_bus_is_counted_not_written(tmp_path):
    """Nothing off the bus is trusted: a publisher is a process we did not
    write, and a malformed message must not become a half-written row.

    `None` is deliberately not in the list - `MessageBus.publish` raises
    `TypeError: 'msg' argument was None` before any handler is reached, which
    this test found by trying it. `Entry.from_message(None)` is still checked
    in `test_journal.py`, because the Actor is not the only caller.
    """
    _, actor = journal_actor(tmp_path)

    for payload in ("text", 42, {}, {"title": "  "}, {"kind": "decision"}):
        actor.msgbus.publish(topic=topics.JOURNAL, msg=payload)

    assert actor.tally["dropped"] == 5
    assert actor.tally["pending"] == 0

    actor._on_timer()
    assert read(actor._store.path) == []


# ----------------------------------------------------------------- the pairing


def test_an_outcome_with_no_parent_is_refused(tmp_path):
    """It could never be paired with the decision it judges, so it is not a
    training example - just noise.

    `service.outcome` refused this at the caller. The writer is the right place
    for it now: the caller is a different process as far as this is concerned.
    """
    _, actor = journal_actor(tmp_path)

    publish(actor, Entry(title="something happened", kind=Kind.OUTCOME))
    actor._on_timer()

    assert read(actor._store.path) == []
    assert actor.tally["dropped"] == 1


def test_an_outcome_inherits_its_decisions_tags(tmp_path):
    """Otherwise a tag filter hides the entry saying the thing resolved itself,
    which is exactly the entry an analyst most needs.
    """
    _, actor = journal_actor(tmp_path)
    made = decision("Alerted on gold", tags=("gold", "OANDA"), time=1_000.0)

    publish(actor, made)
    actor._on_timer()  # the decision is on disk before the outcome arrives
    publish(actor, Entry(title="Normalised in 4 minutes", kind=Kind.OUTCOME, parent=made.id))
    actor._on_timer()

    tagged = read(actor._store.path, tag="gold")
    assert [str(e.kind) for e in tagged] == ["outcome", "decision"]


def test_an_outcome_inherits_tags_from_a_decision_in_the_same_batch(tmp_path):
    """The parent may not be on disk yet, which the retired path could assume.

    `service._inherited_tags` read the store, and the store was current because
    `record` wrote the decision before returning. The Actor batches, so a fast
    resolution can arrive between two flushes - and reading the store alone
    would silently drop the tags of exactly the quickest outcomes.
    """
    _, actor = journal_actor(tmp_path)
    made = decision("Alerted on gold", tags=("gold",), time=1_000.0)

    publish(actor, made)
    publish(actor, Entry(title="Normalised in seconds", kind=Kind.OUTCOME, parent=made.id))
    actor._on_timer()  # one batch, holding both

    tagged = read(actor._store.path, tag="gold")
    assert [str(e.kind) for e in tagged] == ["outcome", "decision"]


def test_explicit_outcome_tags_win(tmp_path):
    _, actor = journal_actor(tmp_path)
    made = decision("Alerted on gold", tags=("gold",), time=1_000.0)

    publish(actor, made)
    publish(
        actor,
        Entry(title="Normalised", kind=Kind.OUTCOME, parent=made.id, tags=("btc",)),
    )
    actor._on_timer()

    assert read(actor._store.path, tag="gold")[0].kind is Kind.DECISION
    assert read(actor._store.path, tag="btc")[0].kind is Kind.OUTCOME


def test_an_unknown_parent_costs_the_tags_and_not_the_entry(tmp_path):
    """Tags are a bonus; the outcome is the label. A parent this journal has
    never seen - a restart, a different file - must not lose the row.
    """
    _, actor = journal_actor(tmp_path)

    publish(
        actor,
        Entry(title="resolved something older", kind=Kind.OUTCOME, parent="deadbeefdeadbeef"),
    )
    actor._on_timer()

    stored = read(actor._store.path)
    assert [e.title for e in stored] == ["resolved something older"]
    assert stored[0].tags == ()


# ------------------------------------------------------- the framework's shape
#
# These are the product owner's checklist for a Nautilus Actor, as tests. Each
# one asserts against the **framework's** class or the framework's own
# machinery, because `hasattr` on our object cannot tell an override from an
# attribute a test assigned - which is the whole lesson of
# `test_nautilus_api.py`.


#: The hooks this actor overrides. Every one has to be a name Nautilus calls,
#: or the override is a method nothing invokes - which looks exactly like a
#: lifecycle that works.
HOOKS = (
    "on_start",
    "on_stop",
    "on_reset",
    "on_dispose",
    "on_degrade",
    "on_resume",
    "on_fault",
    "on_save",
    "on_load",
    "on_entry",
)


def test_every_lifecycle_hook_this_actor_defines_is_one_nautilus_calls():
    """An `on_` method the framework does not know about never runs.

    `on_entry` is ours and is excluded for that reason: it is a bus handler,
    registered by name with `msgbus.subscribe`, not a framework hook. Every
    other name here must exist on `Actor` itself.
    """
    ours = {name for name in vars(JournalActor) if name.startswith("on_")}
    assert ours == set(HOOKS), ours.symmetric_difference(HOOKS)

    missing = [name for name in HOOKS if name != "on_entry" and not hasattr(Actor, name)]
    assert not missing, f"{missing} are not framework hooks - they would never be called"


def test_there_is_no_start_or_run_of_our_own():
    """A custom `start()` is a lifecycle something else has to remember to call.

    `Component.start`, `stop`, `reset`, `dispose`, `degrade` and `resume` are
    the framework's and are documented "do not override" - the subclass
    supplies the `on_*` half. The retired `service.py` was the other shape: a
    `listen()` coroutine a CLI command had to run, which is how
    `journal listen` became a second way to run the desk.
    """
    defined = set(vars(JournalActor))
    assert not defined & {"start", "stop", "reset", "dispose", "degrade", "resume", "run"}


def test_the_config_is_importable_so_a_backtest_can_name_it(tmp_path):
    """`BacktestRunConfig` is serialisable and holds an importable config, not
    an instance. An actor that can only be built by hand goes in a live node
    and not in a backtest - and a backtest measuring a different set from
    production is the single failure the whole port is for.

    `node/desks.py` already has both shapes (`actors` and `importable_actors`);
    this is what makes the journal eligible for the second one.
    """
    built = ActorFactory.create(
        ImportableActorConfig(
            actor_path=f"{JournalActor.__module__}:{JournalActor.__name__}",
            config_path=f"{JournalConfig.__module__}:{JournalConfig.__name__}",
            config={"path": str(tmp_path / "journal.db"), "flush_seconds": 1.0},
        )
    )
    assert isinstance(built, JournalActor)
    assert built._cfg.flush_seconds == 1.0
    # Serialisable both ways, which is what being carried in a run config means.
    assert JournalConfig.parse(JournalConfig(path="x").json()).path == "x"


def test_the_clock_is_the_frameworks_and_there_is_no_sleep_loop():
    """An `asyncio.sleep` loop silently does nothing useful in a backtest.

    The clock is what makes the actor behave identically in both, and
    `test_the_flush_timer_is_what_writes_it` drives it by advancing a
    `TestClock` - which only works because the timer is the clock's. This half
    is the negative: the module reaches for no timing mechanism of its own.
    """
    imported = imported_in_the_actor()
    assert "asyncio" not in imported, "a sleep loop does nothing useful in a backtest"
    assert "time" not in imported
    # `threading` is imported, for a `Lock` and not for a `Thread`: the executor
    # and the loop are two threads reaching for one SQLite connection, and the
    # lock is what keeps the close from winning that race.
    assert "threading" in imported
    assert "Thread" not in {
        alias.name
        for node in ast.walk(ACTOR_TREE)
        if isinstance(node, ast.ImportFrom) and node.module == "threading"
        for alias in node.names
    }


def test_logging_goes_through_the_components_own_logger(tmp_path):
    """The framework's logger carries the component id, which is what makes a
    line attributable. `judge-the-desk-on-the-broker-not-the-journal` is this
    desk's record of what mis-attribution costs: `DEFAULT_MAGIC` off by one
    relabelled every strategy as its neighbour.
    """
    assert "get_logger" not in {
        alias.name
        for node in ast.walk(ACTOR_TREE)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }, "a module-level logger has no component id"
    assert "log" in self_attributes_in_the_actor()

    _, actor = journal_actor(tmp_path)
    assert actor.log.name == "JournalActor"


def test_blocking_work_goes_to_the_executor_and_not_the_handler(tmp_path):
    """`queue_for_executor` is the framework's mechanism for exactly this.

    It is on `Actor`; `create_task` is **not** - that is on
    `LiveExecutionClient`, and the first version of the notifier called it. In
    a backtest there is no executor and the call runs inline, which is why
    `test_journalling_a_decision_does_not_touch_the_disk` measures the handler
    rather than the flush.
    """
    assert hasattr(Actor, "queue_for_executor")
    assert not hasattr(Actor, "create_task")

    _, actor = journal_actor(tmp_path)
    queued: list[tuple] = []
    actor._store = Counting(actor._store.path)
    publish(actor, decision("off the handler"))

    # The flush hands the batch over rather than writing it here. Patched on
    # the instance **and asserted to have existed first**, because assigning a
    # name creates it.
    original = actor.queue_for_executor
    actor.queue_for_executor = lambda func, args=None: queued.append((func, args))
    actor._flush()
    actor.queue_for_executor = original

    assert len(queued) == 1
    assert queued[0][0] == actor._write
    assert actor._store.calls == 0, "the write did not happen on the caller"


def test_the_cache_is_the_frameworks_and_nothing_here_shadows_it(tmp_path):
    """Engine state is read from `self.cache`, never copied.

    `Actor.cache` is read-only on the Cython class, so a test cannot replace it
    either - the assertion below is what that looks like. The journal keeps one
    piece of state, its own unwritten entries, and nothing derived from an
    order, a position or an instrument.
    """
    _, actor = journal_actor(tmp_path)
    with pytest.raises(AttributeError, match="not writable"):
        actor.cache = object()
    assert "cache" not in self_attributes_in_the_actor(), "the journal reads no engine state"


def test_saving_flushes_and_carries_no_state(tmp_path):
    """The journal's durable state is the journal.

    Writing the buffer into the engine's cache database would put the record in
    a second store that is not the record - the disagreement ADR 0005 warns
    about when two things hold the same facts. So `on_save` makes the file
    current and returns nothing, and `utils/codec.py`'s `ALIASES` needs no
    entry: nothing in `journal/` is a `Restorable` dataclass, and the two
    modules that moved held functions rather than persisted classes.
    """
    _, actor = journal_actor(tmp_path)
    publish(actor, decision("unsaved"))

    assert actor.on_save() == {}
    assert [e.title for e in read(actor._store.path)] == ["unsaved"]

    actor.on_load({"pending": b"anything"})  # says so rather than restoring


def test_a_reset_clears_the_buffer_and_keeps_the_record(tmp_path):
    """Append-only is the package's whole claim, so a reset must not empty it.

    A reset that cleared the file would make the journal something a restarted
    backtest can rewrite.
    """
    _, actor = journal_actor(tmp_path)
    publish(actor, decision("recorded", time=1.0))
    actor._on_timer()
    publish(actor, decision("still waiting", time=2.0))

    actor.stop()
    actor.reset()

    assert actor.tally == {"written": 0, "dropped": 0, "shed": 0, "pending": 0}
    # Newest first, which is what `read` gives: the stop flushed the second.
    assert [e.title for e in read(actor._store.path)] == ["still waiting", "recorded"]


def test_disposing_releases_the_file(tmp_path):
    """A connection held by a disposed component is a leak the process only
    notices at its descriptor limit.
    """
    _, actor = journal_actor(tmp_path)
    actor.stop()
    actor.dispose()

    assert actor.is_disposed
    assert actor._store._conn is None


# ------------------------------------------------------- failure, said out loud


def test_a_writer_that_keeps_failing_degrades_the_component(tmp_path):
    """A journal that has silently stopped writing is worse than one that says
    so: every later "no entries that hour" then reads as a quiet market.

    `degrade()` and not a swallowed exception, because the component state is
    the one signal something other than a log reader can act on.
    """
    _, actor = journal_actor(tmp_path, degrade_after=3)
    actor._store = Failing(actor._store.path)

    for n in range(3):
        publish(actor, decision(f"refusal {n}", time=float(n)))
        actor._on_timer()

    assert actor._store.calls == 3
    assert actor.is_degraded
    assert not actor.is_running


def test_one_failed_flush_does_not_degrade_the_component(tmp_path):
    """`Trader._stop` only stops an actor that `is_running`, and `DEGRADED` is
    not running - so a component that degraded on a single transient failure
    would skip its own `on_stop` and the final flush with it. Three flushes is
    fifteen seconds at the default interval.
    """
    _, actor = journal_actor(tmp_path, degrade_after=3)
    actor._store = Failing(actor._store.path)

    publish(actor, decision("one bad write"))
    actor._on_timer()

    assert actor.tally["OSError"] == 1
    assert actor.is_running


def test_it_resumes_once_the_disk_comes_back(tmp_path):
    """Reversible on purpose, which is why this uses `degrade()` and never
    `fault()`: a fault cannot be undone, so one transient failure would end
    journalling for the life of the process.
    """
    _, actor = journal_actor(tmp_path, degrade_after=1)
    real = actor._store
    actor._store = Failing(real.path)

    publish(actor, decision("while the disk was full"))
    actor._on_timer()
    assert actor.is_degraded

    actor._store = real
    publish(actor, decision("after it was emptied"))
    actor._on_timer()

    assert actor.is_running
    assert [e.title for e in read(real.path)] == ["after it was emptied"]
