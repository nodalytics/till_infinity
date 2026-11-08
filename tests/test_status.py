"""What the health probe answers, and why each answer is a different problem.

The `HEALTHCHECK` had nothing to read: it ran `till-infinity health`, a
subcommand of a console script this project does not declare. Before that it
ran `--version`, which **reported healthy for three hours with no trading
service** - because a probe answering from inside the process only proves a
process is alive, which Docker already knew.

So every branch below is one of those three hours. The verdict matters less
than the reason: `docker inspect` keeps a probe's output, and "up two minutes
ago, 0 strategies" tells somebody which problem they have where "unhealthy"
sends them to the logs.
"""

from __future__ import annotations

import json
import time

from till_infinity.node import status


def written(tmp_path, **fields):
    """A status file with `fields` over a working default."""
    body = {
        "at": time.time(),
        "running": True,
        "trader": "TILL-001",
        "venue_connected": True,
        "strategies": 4,
        "armed": True,
    }
    body.update(fields)
    path = tmp_path / "status.json"
    path.write_text(json.dumps(body))
    return path


def test_a_node_that_is_up_and_trading_is_healthy(tmp_path):
    """The control, and the strategy count is part of it.

    `docker inspect` keeps a probe's output, so "4 strategies" is what tells
    somebody reading an unhealthy container later that the node had built its
    desks at all. A probe that answered a bare `True` would make every
    refusal below indistinguishable from a working one.
    """
    ok, reason = status.healthy(written(tmp_path))
    assert ok is True
    assert "4 strategies" in reason


def test_an_unarmed_node_is_still_healthy(tmp_path):
    """**Reported, not required.** `TRADING_LIVE` unset is a deliberate state -
    the risk engine sits in `HALTED` and denies every order - and a probe that
    failed on it would make a dry run impossible. It says so in the reason, so
    nobody mistakes an unarmed node for an armed one."""
    ok, reason = status.healthy(written(tmp_path, armed=False))
    assert ok is True
    assert "unarmed" in reason
    assert "TRADING_LIVE" in reason


def test_a_node_with_no_strategies_is_not_healthy(tmp_path):
    """**The recorded failure, caught where a monitoring system can see it.**
    Three deploys on 2026-10-09 were built, tagged, deployed, health-checked
    and reported up while running none of the code they claimed. A node with
    no strategies connects, reconciles, reports up and trades nothing."""
    ok, reason = status.healthy(written(tmp_path, strategies=0))
    assert ok is False
    assert "0 strategies" in reason
    assert "trading nothing" in reason


def test_a_node_whose_venue_never_answered_is_not_healthy(tmp_path):
    """`judge-the-desk-on-the-broker-not-the-journal`: our own side of the
    wire is not evidence about the account. A node that is up with no
    execution client connected can decide and cannot act."""
    ok, reason = status.healthy(written(tmp_path, venue_connected=False))
    assert ok is False
    assert "venue has not answered" in reason


def test_a_stale_status_is_not_healthy(tmp_path):
    """The file surviving on the volume is what makes this necessary: without
    a freshness check, a node that died two days ago reads exactly like one
    that is running."""
    old = written(tmp_path, at=time.time() - 10_000)
    ok, reason = status.healthy(old)
    assert ok is False
    assert "stopped writing" in reason


def test_a_status_inside_the_window_is_fresh_enough(tmp_path):
    """Three heartbeats of slack. The probe runs every 60s with 3 retries, so
    a single missed write is a loaded box rather than an outage."""
    recent = written(tmp_path, at=time.time() - status.HEARTBEAT * 2)
    assert status.healthy(recent)[0] is True


def test_a_clean_stop_is_distinguishable_from_a_crash(tmp_path):
    """`on_stop` writes `running: false`, so a deploy can tell a node that
    came down deliberately from one that stopped writing."""
    ok, reason = status.healthy(written(tmp_path, running=False))
    assert ok is False
    assert "stopping" in reason


def test_no_file_at_all_says_the_node_never_wrote_one(tmp_path):
    """Which is a different problem from a stale file, and the two take
    different actions: one is a node that never started, the other is one that
    stopped."""
    ok, reason = status.healthy(tmp_path / "absent.json")
    assert ok is False
    assert "has not written one" in reason


def test_unreadable_contents_do_not_raise(tmp_path):
    """A half-written file is what a probe reads if it lands mid-write. It has
    to be unhealthy rather than a traceback, because a probe that crashes is
    an unhealthy container with no reason attached."""
    path = tmp_path / "status.json"
    path.write_text("{not json")
    ok, reason = status.healthy(path)
    assert ok is False
    assert "has not written one" in reason


def test_the_probe_exits_non_zero_when_unhealthy(tmp_path, capsys):
    """The exit code is the whole contract with Docker, and the printed reason
    is the whole contract with a person."""
    assert status.main(["--path", str(tmp_path / "absent.json")]) == 1
    assert "has not written one" in capsys.readouterr().out
    assert status.main(["--path", str(written(tmp_path))]) == 0


def test_what_the_writer_writes_is_what_the_probe_reads(tmp_path):
    """**The round trip, which is the thing that can silently drift.** A
    writer and a probe that disagree about one key is a probe that always
    fails, and neither half's own tests would notice.

    Driven through a registered `Heartbeat` on a real kernel rather than a
    hand-built dict, because the keys come from `reading()` and the point is
    that nothing hand-written stands between the two.
    """
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    from till_infinity.node.status import Heartbeat, HeartbeatConfig

    path = tmp_path / "status.json"
    actor = Heartbeat(HeartbeatConfig(path=str(path)))
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=TestComponentStubs.clock(),
    )
    actor._write()

    assert path.exists(), "the writer produced a file"
    body = json.loads(path.read_text())
    # Every key `healthy` branches on has to be present, or the probe reads a
    # default and answers about something other than the node.
    for key in ("at", "running", "venue_connected", "strategies", "armed"):
        assert key in body, f"{key} is read by healthy() and was not written"

    # And the probe reaches a verdict on it rather than erroring. This node has
    # no strategies, so the honest answer is unhealthy - which is the same
    # refusal `live.build` makes at construction.
    ok, reason = status.healthy(path)
    assert ok is False
    assert "0 strategies" in reason


def test_a_node_builds_with_no_status_path_configured(monkeypatch):
    """**The regression, and the way I caused it.** `live.py` passed
    `HeartbeatConfig(path=... or None)`, and `None` reached `Path(None)` and
    raised `TypeError` - so the node could not build at all unless
    `TILL_STATUS_PATH` was set, and unset is the default case.

    It went in because my own smoke test set the variable, so it exercised the
    configured path and never the default. Fifteen tests failed on it and an
    agent working elsewhere reported them before I did.

    `status.DEFAULT_PATH` reads the environment itself, so there was never
    anything for the caller to pass on.
    """
    import asyncio

    monkeypatch.delenv("TILL_STATUS_PATH", raising=False)
    monkeypatch.setenv("TRADING_SYMBOLS", "EURUSD")
    monkeypatch.setenv("TRADING_ENTRIES", "edge")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    for name in ("TRADING_VENUES", "STATESPACE_BARS"):
        monkeypatch.delenv(name, raising=False)

    made = asyncio.new_event_loop()
    asyncio.set_event_loop(made)
    try:
        from till_infinity.node import live

        node = live.build()
        try:
            assert "Heartbeat" in {str(actor.id) for actor in node.trader.actors()}
        finally:
            node.dispose()
    finally:
        asyncio.set_event_loop(None)
        made.close()


def test_the_default_path_is_a_real_path_without_the_variable(monkeypatch):
    """The narrower half of the same thing, with no node to build: the default
    has to be usable on its own, because that is what production runs."""
    from till_infinity.node.status import Heartbeat, HeartbeatConfig

    monkeypatch.delenv("TILL_STATUS_PATH", raising=False)
    config = HeartbeatConfig()
    assert isinstance(config.path, str)
    assert config.path
    # Constructing the actor is where `Path(...)` is called.
    assert Heartbeat(config) is not None


def test_a_venue_that_cannot_trade_is_reported_and_the_node_is_still_healthy(tmp_path):
    """**Reported, not required** - the same argument `armed` won.

    A terminal with AutoTrading off cannot fill anything, and it is also what
    every weekend looks like. Failing the container healthcheck on it would
    mark a correctly idle desk unhealthy every Saturday, and the `exec_clients`
    fault already showed what a check nobody trusts is worth. So this exists so
    that a person or an alert can see a desk that is **up and unable to
    trade** - which on 2026-11-04 no signal showed, while `/account/health`,
    `/terminal/ping` and the account's own `trade_allowed` all read green.

    The payload is the execution client's own, published on the client's own
    topic: a hand-built dict here would pass while the two ends disagreed,
    which is the `publish_data_dict` lesson one level down.
    """
    import json

    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    from till_infinity.node.status import Heartbeat, HeartbeatConfig
    from till_infinity.utils.topics import VENUE_TRADING

    path = tmp_path / "status.json"
    actor = Heartbeat(HeartbeatConfig(path=str(path), registered=4))
    bus = TestComponentStubs.msgbus()
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=bus,
        cache=TestComponentStubs.cache(),
        clock=TestComponentStubs.clock(),
    )
    actor.on_start()

    # Nothing has said either way yet, and that is a third answer.
    assert actor.reading()["can_trade"] is None, (
        "a node that has not asked must not claim the venue is shut: "
        "`None` and `False` are different facts"
    )

    bus.publish(VENUE_TRADING, {"can_trade": False, "cause": "retcode 10027 on an order"})
    found = actor.reading()
    assert found["can_trade"] is False
    assert "10027" in found["can_trade_cause"]
    assert found["can_trade_at"] is not None, "a flag with no time cannot be told from a stale one"

    actor._write()
    body = json.loads(path.read_text())
    assert body["can_trade"] is False, "the probe reads the file, so it has to be in the file"

    bus.publish(VENUE_TRADING, {"can_trade": True, "cause": "terminal_info on connect"})
    assert actor.reading()["can_trade"] is True, "the flag has to be able to come back"

    # **And the verdict does not move.** The control, on an otherwise working
    # node - this actor's own `venue_connected` is false because a stub cache
    # holds no account, which would have made the assertion pass for the wrong
    # reason.
    ok, reason = status.healthy(written(tmp_path, can_trade=False))
    assert ok is True, f"a weekend must not read as unhealthy: {reason}"


def test_a_malformed_venue_flag_is_ignored_rather_than_believed(tmp_path):
    """A message that is not the contract leaves the last good reading alone.

    Believing a stray publish would let anything on the bus mark the desk
    unable to trade, and `None` is the one value that means "nobody said".
    """
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    from till_infinity.node.status import Heartbeat, HeartbeatConfig
    from till_infinity.utils.topics import VENUE_TRADING

    actor = Heartbeat(HeartbeatConfig(path=str(tmp_path / "status.json")))
    bus = TestComponentStubs.msgbus()
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=bus,
        cache=TestComponentStubs.cache(),
        clock=TestComponentStubs.clock(),
    )
    actor.on_start()

    bus.publish(VENUE_TRADING, {"can_trade": True, "cause": "connect"})

    # Through the bus for anything it will carry. It refuses `None` outright
    # (`TypeError: 'msg' argument was None`), so that one reaches the handler
    # directly - the handler is what is under test, and it must not assume the
    # bus filtered anything for it.
    for junk in ("off", {}, {"trade_allowed": False}, 0):
        bus.publish(VENUE_TRADING, junk)
        assert actor.reading()["can_trade"] is True, f"{junk!r} overwrote a good reading"
    actor._venue_trading(None)
    assert actor.reading()["can_trade"] is True, "None overwrote a good reading"


def test_the_count_is_what_was_registered_not_what_has_traded(tmp_path):
    """**The healthcheck called every healthy fresh desk "trading nothing".**

    `reading()` counted `cache.strategy_ids()`, which is empty until a strategy
    has an order. Measured on a built node: `trader.strategies()` reads 4 where
    `cache.strategy_ids()` reads 0. So a desk that had just started - twelve
    strategies registered, no fills yet - reported `0 strategies: the node is
    up and trading nothing` and Docker marked the container unhealthy.

    That is a false alarm on the one check meant to be trusted, and it fired
    within an hour of the same check correctly catching a real outage. An
    `Actor` cannot reach the trader - it has `trader_id` and nothing else - so
    the count is handed over at construction by the caller that registered
    them.
    """
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    from till_infinity.node.status import Heartbeat, HeartbeatConfig, healthy

    where = tmp_path / "s.json"
    actor = Heartbeat(HeartbeatConfig(path=str(where), registered=12))
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=TestComponentStubs.clock(),
    )
    found = actor.reading()

    assert found["strategies"] == 12, "what the node registered"
    assert found["with_orders"] == 0, "and nothing has traded yet, reported beside it"

    # Through the file, which is what the probe actually reads. The venue is
    # a separate condition and a stub has no execution client, so what is
    # asserted is that **the strategy count is no longer the reason** - not
    # full health, which would need a connected venue this fixture cannot have.
    actor._write()
    _, why = healthy(where)
    assert "0 strategies" not in why, f"the false alarm is back: {why!r}"
    assert "trading nothing" not in why, f"the false alarm is back: {why!r}"


def test_a_node_that_registered_nothing_is_still_caught(tmp_path):
    """**The control.** The check exists because three deploys were health
    checked while running none of the code they claimed, and an environment
    naming retired rules put the live desk into a 27-restart loop. Counting
    registrations rather than orders must not soften that."""
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    from till_infinity.node.status import Heartbeat, HeartbeatConfig, healthy

    where = tmp_path / "s.json"
    actor = Heartbeat(HeartbeatConfig(path=str(where), registered=0))
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=TestComponentStubs.clock(),
    )
    actor._write()

    ok, why = healthy(where)
    assert ok is False
    assert "0 strategies" in why


def test_the_venue_check_reads_something_that_exists(tmp_path):
    """**The check could never pass.**

    `reading()` did `self.cache.exec_clients() if hasattr(self.cache,
    "exec_clients") else []`, and `Cache` has no `exec_clients` method - so the
    guard turned a missing method into an empty list, `any([])` into `False`,
    and `venue_connected` into a value that was **permanently false whatever
    the venue was doing**. The container reported `unhealthy` from the day it
    shipped, with the execution client logging `Connected` and an account with
    equity on the line above.

    An account is the right source and is still the venue's word: it arrives
    from the execution client's own reply, so its presence means the venue
    answered. Asserted against the real `Cache` so a framework rename fails
    here rather than in production.
    """
    from nautilus_trader.cache.cache import Cache

    assert not hasattr(Cache, "exec_clients"), (
        "if this ever exists, the original code was merely unlucky rather than "
        "wrong - and this test should be revisited"
    )
    assert hasattr(Cache, "accounts"), "the replacement has to exist"


def test_an_account_with_a_balance_is_the_venue_answering(tmp_path):
    """A stub cache holds no account, so the reading is false - which is
    correct, and is the state that made the old bug invisible: the answer was
    right for the wrong reason until a real venue connected."""
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    from till_infinity.node.status import Heartbeat, HeartbeatConfig

    actor = Heartbeat(HeartbeatConfig(path=str(tmp_path / "s.json"), registered=14))
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=TestComponentStubs.clock(),
    )
    found = actor.reading()

    assert found["venue_connected"] is False, "no account in a stub cache"
    assert found["strategies"] == 14, "and the count is unaffected by it"


def test_the_probe_costs_nothing_to_import():
    """**The healthcheck was the largest CPU consumer on the box.**

    `python -m till_infinity.node.status` imports `Heartbeat`, which is a
    Nautilus `Actor`, which costs 1.60s of import time -
    `nautilus_trader.common.component` 1.34s and pandas 0.65s inside that -
    to read one JSON file. Measured on tis 2026-11-06 the probe took 2.0s of
    wall time and about **1.2 cores, every 60 seconds**: roughly 4% of the
    machine, continuously, and the only real CPU spike on it. The trading
    workload it was watching peaked at 0.238 cores.

    So the reader lives apart from the writer and the probe imports neither
    Nautilus nor pandas. Asserted in a subprocess because this process has
    already imported both.
    """
    import subprocess
    import sys

    code = (
        "import sys, till_infinity.node.probe as probe;"
        "heavy = sorted({m.split('.')[0] for m in sys.modules"
        " if m.split('.')[0] in ('nautilus_trader', 'pandas', 'numpy')});"
        "print(','.join(heavy));"
        "sys.exit(1 if heavy else 0)"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)

    assert done.returncode == 0, (
        f"the probe pulled in {done.stdout.strip()} - a healthcheck that imports the "
        f"trading stack costs more CPU than the desk it is checking"
    )


def test_the_healthcheck_runs_the_probe_and_not_the_writer():
    """The Dockerfile has to name the light module, or the split buys nothing."""
    import re
    from pathlib import Path

    text = Path(__file__).resolve().parents[1].joinpath("Dockerfile").read_text()
    # Anchored to the directive: the word also appears in a comment near the
    # top of the file, and matching that captured `HEALTHCHECK` alone.
    found = re.search(r"^HEALTHCHECK(?:[^\n]*\\\n)*[^\n]*", text, re.M)
    assert found, "no HEALTHCHECK in the Dockerfile"
    line = found.group(0)
    assert "till_infinity.node.probe" in line, f"HEALTHCHECK does not run the probe: {line}"
    assert "node.status" not in line, (
        f"HEALTHCHECK still runs the writer's module, which imports Nautilus: {line}"
    )


def test_the_writer_still_exposes_the_reader():
    """`status.read` and `status.healthy` keep working: the move is where the
    code lives, not what anything may call."""
    from till_infinity.node import probe, status

    assert status.read is probe.read
    assert status.healthy is probe.healthy
    assert status.STALE_AFTER == probe.STALE_AFTER
    assert status.DEFAULT_PATH == probe.DEFAULT_PATH


# ------------------------------------------------- the one-shot startup alert


def test_a_fully_up_node_announces_itself_once():
    """**A notification path that has never delivered is indistinguishable from
    one that works.**

    On 2026-11-08, hours before the desk's first expected fill, the notifier
    tally read `0 sent, 1 dropped` and had never sent anything on that
    deploy - so whether the Telegram token was valid was unknown, and the
    first message ever attempted would have been the fill alert itself.

    Announcing on start makes every deploy prove the path while somebody is
    watching. `critical` because the shape filter and the hourly cap are
    bypassed only for urgent alerts, and `NOTIFY_SHAPES` is set in production
    to a list this shape is not on - so any other level would be dropped by
    the very filter this message exists to test.
    """
    got = status.startup_alert(
        {"running": True, "venue_connected": True, "strategies": 90, "armed": True},
        elapsed=status.ANNOUNCE_AFTER,
    )
    assert got is not None
    assert got["level"] == "critical"
    assert "90" in got["title"] + got["body"]
    assert got["fields"]["shape"] == "desk"


def test_a_node_that_is_not_up_yet_announces_nothing():
    """Absent is not zero. A node with no strategies, or a venue that has not
    answered, is still starting - announcing then would make the message mean
    "the process exists", which is what the old `--version` healthcheck
    reported for three hours over a desk that was not trading."""
    assert (
        status.startup_alert(
            {"running": True, "venue_connected": True, "strategies": 0, "armed": True},
            elapsed=status.ANNOUNCE_AFTER,
        )
        is None
    )
    assert (
        status.startup_alert(
            {"running": True, "venue_connected": False, "strategies": 90, "armed": True},
            elapsed=status.ANNOUNCE_AFTER,
        )
        is None
    )
    assert (
        status.startup_alert(
            {"running": False, "venue_connected": True, "strategies": 90, "armed": True},
            elapsed=status.ANNOUNCE_AFTER,
        )
        is None
    )


def test_the_announcement_waits_for_the_notifier_to_subscribe():
    """**A one-shot alert published before its subscriber exists is lost.**

    Measured on the live desk, 2026-11-08. The heartbeat registered at
    18:49:09 and its `on_start` wrote immediately, so the announcement went
    out then - while the notifier logged "notifying on alerts" at **18:49:53**,
    44 seconds later. The alert reached a topic with no subscriber, vanished,
    and `_announced` stopped it retrying: the notifier reported `0 sent` and
    nothing in the log said why.

    So it waits. The window is generous rather than tight, because being late
    costs a late message and being early costs the message entirely.
    """
    up = {"running": True, "venue_connected": True, "strategies": 90, "armed": True}
    assert status.startup_alert(up, elapsed=0.0) is None
    assert status.startup_alert(up, elapsed=status.ANNOUNCE_AFTER - 1.0) is None
    assert status.startup_alert(up, elapsed=status.ANNOUNCE_AFTER) is not None
    assert status.ANNOUNCE_AFTER >= 60.0, "44s was the observed gap; leave real margin"
