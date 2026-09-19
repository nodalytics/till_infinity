"""Every service the stack names must actually be reachable."""

from __future__ import annotations

import asyncio
import contextlib
import contextlib as _contextlib
import json
import logging as _logging
import time

import pytest

from till_infinity import stack as st


@_contextlib.contextmanager
def patch_sleep(module, replacement):
    """Swap `asyncio.sleep` as the module sees it, and put it back."""
    import asyncio as _asyncio

    was = _asyncio.sleep
    module.asyncio.sleep = replacement
    try:
        yield
    finally:
        module.asyncio.sleep = was


@_contextlib.contextmanager
def caplog_records(level, name):
    """Collect one logger's messages, without depending on propagation."""
    found = []

    class Grab(_logging.Handler):
        def emit(self, record):
            found.append(record.getMessage())

    logger = _logging.getLogger(name)
    handler = Grab(level)
    logger.addHandler(handler)
    was = logger.level
    logger.setLevel(level)
    try:
        yield found
    finally:
        logger.removeHandler(handler)
        logger.setLevel(was)


@pytest.mark.parametrize("name", st.ORDER)
def test_every_service_in_the_order_has_a_runner(name):
    assert hasattr(st.Stack(st.Plan()), f"_run_{name}")


def test_the_entry_points_each_service_calls_exist():
    """`notifications` died on start for three deploys because `nt.listen` was
    written, tested, and never exported - the stack referenced a name the
    package did not have, and only a running container said so."""
    from till_infinity import agents as ag
    from till_infinity import journal as jr
    from till_infinity import news as nw
    from till_infinity import notifications as nt
    from till_infinity import prices as px
    from till_infinity import structures as sx
    from till_infinity import trading as td

    assert callable(nt.listen)
    assert callable(jr.listen)
    assert callable(ag.watch)
    assert callable(sx.Watcher)
    assert callable(px.collect)
    assert callable(nw.collect)
    assert callable(td.listen)


def test_trading_is_off_unless_asked_for(monkeypatch):
    """The only service that can lose money, so its absence is never a surprise."""
    monkeypatch.delenv("TRADING_ENABLED", raising=False)
    assert not st.Plan.from_env().trading
    monkeypatch.setenv("TRADING_ENABLED", "1")
    assert st.Plan.from_env().trading


def test_enabling_trading_does_not_arm_it(monkeypatch):
    """Two switches, and neither implies the other."""
    from till_infinity import trading as td

    monkeypatch.setenv("TRADING_ENABLED", "1")
    monkeypatch.delenv("TRADING_LIVE", raising=False)
    assert st.Plan.from_env().trading
    assert not td.Settings.from_env().live


def test_a_wanted_trading_service_that_cannot_run_is_reported_not_started(monkeypatch):
    """`check` runs before anything starts, so a misconfiguration is named at
    second zero rather than after a collector has been running for a minute."""
    monkeypatch.setenv("TRADING_BACKEND", "mt5-http")
    monkeypatch.delenv("TRADING_MT5_URL", raising=False)
    reasons = st.check(st.Plan(trading=True, notifications=False))
    assert "trading" in reasons
    assert "TRADING_MT5_URL" in reasons["trading"]


def test_trading_on_paper_is_a_service_that_can_run(monkeypatch):
    monkeypatch.delenv("TRADING_BACKEND", raising=False)
    monkeypatch.delenv("TRADING_MT5_URL", raising=False)
    assert "trading" not in st.check(st.Plan(trading=True, notifications=False))


# ------------------------------------------ the status a healthcheck can read


def test_the_status_says_what_is_running(tmp_path, monkeypatch):
    """A container reporting `healthy` with no trading service is the fault this
    exists for - see `stack.STATUS_FILE`."""
    from till_infinity import stack as st

    target = tmp_path / "stack.json"
    monkeypatch.setattr(st, "STATUS_FILE", target)
    status = st.Status()
    status.running.extend(["structures", "trading"])
    status.publish()

    got = json.loads(target.read_text())
    assert got["running"] == ["structures", "trading"]
    assert got["failed"] == {}
    assert got["written"] > 0


def test_a_service_that_dies_leaves_the_running_list(tmp_path, monkeypatch):
    """The list is what `health` reads, so a dead service must not still appear
    in it - that is the shape of the outage this replaced."""
    from till_infinity import stack as st

    target = tmp_path / "stack.json"
    monkeypatch.setattr(st, "STATUS_FILE", target)
    status = st.Status()
    status.running.extend(["structures", "trading"])
    status.failed["trading"] = "NotConnectedError"
    status.running.remove("trading")
    status.publish()

    got = json.loads(target.read_text())
    assert got["running"] == ["structures"]
    assert got["failed"] == {"trading": "NotConnectedError"}


def test_publishing_cannot_take_the_stack_down(tmp_path, monkeypatch):
    """An alarm that fails during the fault it reports is not an alarm. A status
    file that cannot be written is a debug line, not a stopped stack."""
    from till_infinity import stack as st

    monkeypatch.setattr(st, "STATUS_FILE", tmp_path / "nope" / "x" / "stack.json")
    monkeypatch.setattr(
        st.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only"))
    )
    st.Status().publish()  # must not raise


def test_health_fails_on_a_dead_service(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from till_infinity import stack as st
    from till_infinity.cli import main

    target = tmp_path / "stack.json"
    monkeypatch.setattr(st, "STATUS_FILE", target)
    status = st.Status()
    status.running.append("structures")
    status.publish()
    assert CliRunner().invoke(main, ["health", "--file", str(target)]).exit_code == 0

    status.failed["trading"] = "NotConnectedError"
    status.publish()
    result = CliRunner().invoke(main, ["health", "--file", str(target)])
    assert result.exit_code == 1
    assert "trading stopped" in result.output


def test_health_fails_on_a_stale_status(tmp_path, monkeypatch):
    """A process that is up and no longer writing is not healthy, and this is
    the case a liveness probe can never see."""
    from click.testing import CliRunner

    from till_infinity import stack as st
    from till_infinity.cli import main

    target = tmp_path / "stack.json"
    monkeypatch.setattr(st, "STATUS_FILE", target)
    status = st.Status()
    status.running.append("structures")
    status.publish()

    stale = json.loads(target.read_text())
    stale["written"] = time.time() - 3600
    target.write_text(json.dumps(stale))

    result = CliRunner().invoke(main, ["health", "--file", str(target)])
    assert result.exit_code == 1
    assert "old" in result.output


def test_health_fails_when_nothing_started(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from till_infinity import stack as st
    from till_infinity.cli import main

    target = tmp_path / "stack.json"
    monkeypatch.setattr(st, "STATUS_FILE", target)
    st.Status().publish()
    result = CliRunner().invoke(main, ["health", "--file", str(target)])
    assert result.exit_code == 1
    assert "nothing running" in result.output


async def test_the_status_is_republished_on_a_timer(tmp_path, monkeypatch):
    """Publishing on change alone marks a *healthy* stack unhealthy.

    The staleness check in `health` exists to catch a process that is up and no
    longer doing anything - the one case a liveness probe cannot see. That only
    works if a working stack keeps saying so. The first version of this was
    called on change alone, and a stack where nothing changes is the healthy
    case: nine hours after shipping, seven services running, nothing failed, and
    the container marked unhealthy on a 33,138-second-old file.
    """
    target = tmp_path / "stack.json"
    monkeypatch.setattr(st, "STATUS_FILE", target)
    monkeypatch.setattr(st, "HEARTBEAT", 0.01)

    stack = st.Stack.__new__(st.Stack)
    stack.status = st.Status()
    stack.status.running.append("trading")
    stack.status.publish()
    first = json.loads(target.read_text())["written"]

    beat = asyncio.create_task(stack._beat())
    await asyncio.sleep(0.05)
    beat.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await beat

    assert json.loads(target.read_text())["written"] > first


def test_the_heartbeat_leaves_four_beats_of_room(tmp_path):
    """A slow moment must not read as an outage. Sixty seconds against the
    `health --max-age` default of 300 is four missed beats of margin."""
    assert st.HEARTBEAT * 4 < 300.0


@pytest.mark.asyncio
async def test_sigusr1_dumps_every_task(caplog):
    """**Because inference has a poor record here.**

    The quote feed went dark roughly every forty minutes on 2026-09-16 and
    five deploys were aimed at whichever await seemed likeliest, because the
    process could not be asked what it was standing on. A watchdog answers
    that only after its patience expires and only for the condition it was
    written to notice; this answers it now, for whatever is actually
    happening.
    """
    import asyncio
    import logging
    import os
    import signal

    from till_infinity import stack as st

    with caplog.at_level(logging.WARNING, logger=st.log.name):
        st._arm_task_dump()
        async with asyncio.TaskGroup() as group:
            waiting = group.create_task(asyncio.sleep(0.2), name="a-task-to-find")
            os.kill(os.getpid(), signal.SIGUSR1)
            await waiting

    said = [r.getMessage() for r in caplog.records]
    assert any("dumping on request" in m for m in said), said
    assert any("a-task-to-find" in m for m in said), "and it must name the tasks it found"


@pytest.mark.asyncio
async def test_a_forever_task_that_returns_says_so(caplog):
    """**A child of a task group that returns takes nothing with it.**

    The group only reacts to an exception, so a collector that simply ends
    leaves its siblings running, the actor marked healthy, and nothing in the
    log. That is the shape the quote feed failed in repeatedly on 2026-09-16:
    quotes stopped, bars carried on, every actor read as running, and the task
    was absent from a dump of 248 with no explanation anywhere.
    """
    import asyncio
    import logging

    from till_infinity import stack as st

    async def finishes() -> None:
        return

    with caplog.at_level(logging.ERROR, logger=st.log.name):
        async with asyncio.TaskGroup() as group:
            st._watch_end(group.create_task(finishes(), name="prices:quotes"))

    said = [r.getMessage() for r in caplog.records]
    assert any("prices:quotes returned on its own" in m for m in said), said


@pytest.mark.asyncio
async def test_a_forever_task_that_raises_says_what_of(caplog):
    import asyncio
    import contextlib
    import logging

    from till_infinity import stack as st

    async def breaks() -> None:
        raise RuntimeError("the socket went")

    with caplog.at_level(logging.ERROR, logger=st.log.name), contextlib.suppress(BaseException):
        async with asyncio.TaskGroup() as group:
            st._watch_end(group.create_task(breaks(), name="prices:quotes"))

    said = [r.getMessage() for r in caplog.records]
    assert any("the socket went" in m for m in said), said


@pytest.mark.asyncio
async def test_a_forever_task_that_is_cancelled_says_so(caplog):
    """**The case that actually happened, and the one the first version
    skipped.**

    Returning early on a cancelled task sounds reasonable - a cancellation is
    usually somebody shutting things down on purpose. For a collector that
    should run forever it is not, and on 2026-09-16 it was the only thing that
    ever occurred: `prices:quotes` vanished from a task dump with no log line
    anywhere, because the one callback watching for it treated that case as
    uninteresting.
    """
    import asyncio
    import contextlib
    import logging

    from till_infinity import stack as st

    async def forever() -> None:
        await asyncio.Event().wait()

    with caplog.at_level(logging.ERROR, logger=st.log.name):
        task = asyncio.create_task(forever(), name="prices:quotes")
        st._watch_end(task)
        await asyncio.sleep(0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

    said = [r.getMessage() for r in caplog.records]
    assert any("prices:quotes was cancelled" in m for m in said), said


@pytest.mark.asyncio
async def test_a_collector_that_ends_is_started_again(caplog):
    """**The claim is deliberately smaller than "the cause is fixed".**

    Six fixes went to why one collector died on 2026-09-16 and it kept dying.
    This does not care why: a collector that ends gets started again, loudly,
    which works against a library cancelling something inside httpx as well as
    against a bug here.
    """
    import asyncio
    import logging

    from till_infinity import stack as st

    runs = []

    async def dies() -> None:
        runs.append(True)
        if len(runs) < 3:
            return  # ends on its own, as the quote poll did
        await asyncio.Event().wait()

    with caplog.at_level(logging.ERROR, logger=st.log.name):
        task = asyncio.create_task(st._forever("prices:quotes", dies, settle=0.0))
        for _ in range(400):
            await asyncio.sleep(0)
            if len(runs) >= 3:
                break
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert len(runs) >= 3, f"it was not restarted: {len(runs)} run(s)"
    said = [r.getMessage() for r in caplog.records]
    assert any("returned on its own - restarting" in m for m in said), said[:3]


@pytest.mark.asyncio
async def test_a_cancellation_nobody_asked_for_is_a_death(caplog):
    """The failure exactly as observed: the task ends cancelled, no exception
    is recorded, siblings keep running, every gauge reads healthy."""
    import asyncio
    import logging

    from till_infinity import stack as st

    runs = []

    async def cancelled_from_below() -> None:
        runs.append(True)
        if len(runs) < 2:
            raise asyncio.CancelledError  # nobody asked; it escaped a library
        await asyncio.Event().wait()

    going_down = False

    with caplog.at_level(logging.ERROR, logger=st.log.name):
        task = asyncio.create_task(
            st._forever(
                "prices:quotes", cancelled_from_below, settle=0.0, stopping=lambda: going_down
            )
        )
        for _ in range(400):
            await asyncio.sleep(0)
            if len(runs) >= 2:
                break
        # Only a desk that says it is stopping can stop it now - which is the
        # property under test, so say so before tidying up.
        going_down = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert len(runs) >= 2, "a spurious cancellation killed the supervisor"
    assert any("while the desk was still running" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_real_shutdown_still_stops_a_supervised_collector():
    """A desk that cannot be shut down is a worse bug than the one being
    fixed."""
    import asyncio

    from till_infinity import stack as st

    started = asyncio.Event()

    async def forever() -> None:
        started.set()
        await asyncio.Event().wait()

    # No `stopping` predicate: cannot tell, so it stops - the safe default.
    task = asyncio.create_task(st._forever("prices:quotes", forever))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.asyncio
async def test_a_desk_with_nothing_left_running_ends_loudly():
    """**A clean exit is indistinguishable from a deliberate stop.**

    An actor ends by failing: the supervisor catches it, records it, returns.
    When the last one goes the process would sit publishing a status of nothing
    - or exit zero, which `docker` reads as a bounce and restarts on its
    policy. That happened twice overnight on 2026-09-17 with quotes ninety
    minutes stale, and nothing distinguished a desk that had died from one that
    had been stopped.
    """
    import asyncio
    import logging
    from unittest.mock import patch

    from till_infinity import stack as st

    desk = st.Stack(st.Plan(journal=False))
    desk.status.failed["prices"] = "the quote poll was cancelled"

    with patch.object(st, "HEARTBEAT", 0.01), caplog_records(logging.ERROR, st.log.name) as said:
        await asyncio.wait_for(desk._beat(), timeout=2)

    assert desk._ended is not None
    assert "quote poll was cancelled" in str(desk._ended)
    assert any("every service has ended" in m for m in said)


@pytest.mark.asyncio
async def test_a_desk_still_running_something_keeps_beating():
    """It must not fire while anything is alive, or every ordinary restart of
    one service would take the whole process down."""
    import asyncio
    from unittest.mock import patch

    from till_infinity import stack as st

    desk = st.Stack(st.Plan(journal=False))
    desk.status.running.append("structures")
    desk.status.failed["prices"] = "gone"

    with patch.object(st, "HEARTBEAT", 0.01), contextlib.suppress(TimeoutError):
        await asyncio.wait_for(desk._beat(), timeout=0.2)
    assert desk._ended is None


@pytest.mark.asyncio
async def test_a_desk_that_is_stopping_takes_its_collectors_with_it():
    """The other half of the discrimination: when the desk says it is going
    down, a supervised collector goes down with it rather than restarting into
    a process that is closing."""
    import asyncio

    from till_infinity import stack as st

    started = asyncio.Event()
    going_down = False

    async def forever() -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        st._forever("prices:quotes", forever, settle=0.0, stopping=lambda: going_down)
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    going_down = True
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.asyncio
async def test_a_cancellation_between_attempts_does_not_kill_the_supervisor(caplog):
    """**The hole the first version left, found in production in half an hour.**

    Only the collector was guarded; the wait between attempts was bare. A
    cancellation landing in that window killed the supervisor outright, which
    the log showed as `restarting (attempt 1)` followed immediately by
    `was cancelled - it should run forever`. Every await in `_forever` is a
    place a library can cancel the task, so every await has to be guarded.
    """
    import asyncio
    import logging

    from till_infinity import stack as st

    runs = []
    going_down = False

    async def dies() -> None:
        runs.append(True)
        raise RuntimeError("the collector fell over")

    # A sleep that is cancelled the first time it is waited on - exactly what a
    # cancel scope firing during the backoff looks like.
    real_sleep = asyncio.sleep
    waits = []

    async def hostile(delay, *a, **k):
        waits.append(delay)
        if len(waits) == 1:
            raise asyncio.CancelledError
        await real_sleep(0)

    with caplog.at_level(logging.ERROR, logger=st.log.name), patch_sleep(st, hostile):
        task = asyncio.create_task(
            st._forever("prices:quotes", dies, settle=0.0, stopping=lambda: going_down)
        )
        for _ in range(400):
            await real_sleep(0)
            if len(runs) >= 2:
                break
        going_down = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert len(runs) >= 2, "a cancellation during the backoff killed the supervisor"


@pytest.mark.asyncio
async def test_a_scope_that_keeps_cancelling_does_not_spin_the_supervisor(caplog):
    """**105,021 restarts in four and a half hours - about six a second.**

    An anyio cancel scope belongs to the task that entered it, and once its
    deadline has passed it re-delivers cancellation at *every* checkpoint in
    that task until the scope is exited. Catching the `CancelledError` and
    calling `uncancel` does not exit it, so the backoff was cancelled the
    instant it started, and so was the next attempt's.

    Modelled here exactly that way: the collector marks whichever task it ran
    in as poisoned, and every later sleep *in that task* is cancelled. Run in
    the supervisor's own task the backoff can never complete; run in a task of
    its own the poison dies with it, which is the fix.
    """
    import asyncio
    import logging

    from till_infinity import stack as st

    runs = []
    poisoned = set()
    going_down = False

    async def enters_a_scope_that_outlives_it() -> None:
        # The scope belongs to whatever task is running this.
        mine = asyncio.current_task()
        runs.append(mine)
        poisoned.add(mine)
        raise asyncio.CancelledError

    real_sleep = asyncio.sleep
    finished = []

    async def scoped(delay, *a, **k):
        if asyncio.current_task() in poisoned:
            # The scope re-delivering at this checkpoint.
            raise asyncio.CancelledError
        await real_sleep(0)
        finished.append(delay)

    with caplog.at_level(logging.ERROR, logger=st.log.name), patch_sleep(st, scoped):
        task = asyncio.create_task(
            st._forever(
                "prices:quotes",
                enters_a_scope_that_outlives_it,
                settle=1.0,
                stopping=lambda: going_down,
            )
        )
        for _ in range(600):
            await real_sleep(0)
            if len(runs) >= 3:
                break
        going_down = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert len(runs) >= 2, "the collector should be restarted"
    assert finished, (
        "every backoff was cancelled before it could elapse - the supervisor is spinning"
    )
    assert finished[0] >= 1.0, f"backed off {finished[0]}s, which is not a backoff"


@pytest.mark.asyncio
async def test_it_stops_saying_the_same_thing_a_hundred_thousand_times(caplog):
    """96% of a container's log was this one line, which buried everything.

    A collector restarting in a loop is one fact, not a hundred thousand of
    them, and the line reporting it must not be the reason the log is useless.
    """
    import asyncio
    import logging

    from till_infinity import stack as st

    going_down = False
    runs = []

    async def dies() -> None:
        runs.append(True)
        raise RuntimeError("down again")

    real_sleep = asyncio.sleep

    async def instant(delay, *a, **k):
        await real_sleep(0)

    with caplog.at_level(logging.ERROR, logger=st.log.name), patch_sleep(st, instant):
        task = asyncio.create_task(
            st._forever("prices:quotes", dies, settle=0.0, stopping=lambda: going_down)
        )
        for _ in range(4_000):
            await real_sleep(0)
            if len(runs) >= 40:
                break
        going_down = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    said = [r for r in caplog.records if "restarting (attempt" in r.getMessage()]
    assert len(runs) >= 20, "the fixture needs the collector to restart many times"
    assert len(said) < len(runs), (
        f"logged {len(said)} lines for {len(runs)} restarts - every one of them"
    )
