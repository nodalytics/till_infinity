"""Every service the stack names must actually be reachable."""

from __future__ import annotations

import json
import time

import pytest

from till_infinity import stack as st


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
