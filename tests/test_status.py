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
