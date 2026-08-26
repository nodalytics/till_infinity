"""Every service the stack names must actually be reachable."""

from __future__ import annotations

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
