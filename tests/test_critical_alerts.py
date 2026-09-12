"""A critical alert must not be filtered like a topic preference.

**Every trading alarm this desk has ever raised was silently discarded**, and it
was discovered by accident on 2026-09-12 while checking whether a *new* alarm
worked. `Filter.key` falls back to the payload's **source** when there is no
shape field; trading publishes `{title, body, level}` with source `trading`; and
`NOTIFY_SHAPES` says `trade`. So the gate read

    shape 'trading' not in ['agent', 'drift', 'level', 'trade']

and dropped it, at `log.debug`, in a container running at INFO.

That took `AutoTrading is off` with it - the alarm written *because* nine hours
of rejected orders went unnoticed - and `trading is not attached`, and the
broker-unreachable alarm added hours earlier the same day. Three alarms, each
written after an outage the previous silence caused, none of which could ever
have reached anyone.

These tests exist so that cannot come back quietly.
"""

from __future__ import annotations

import logging

import pytest

from till_infinity.notifications.filters import Filter


@pytest.fixture
def narrow(monkeypatch) -> Filter:
    """The production shape list, which names no trading shape at all."""
    monkeypatch.setenv("NOTIFY_SHAPES", "level,drift,agent,trade")
    monkeypatch.setenv("NOTIFY_FEEDS", "gold,volatility_75_index")
    monkeypatch.setenv("NOTIFY_COOLDOWN_S", "900")
    return Filter.from_env()


def alert(title: str, level: str = "critical", source: str = "trading") -> dict:
    return {"title": f"live: {title}", "body": "...", "level": level, "source": source}


@pytest.mark.parametrize(
    "title",
    [
        "the desk cannot reach its terminal",
        "AutoTrading is off",
        "trading is not attached",
    ],
)
def test_every_trading_alarm_gets_through(narrow: Filter, title: str):
    """The three that could not, named individually so a regression says which."""
    assert narrow.rejects(alert(title)) == ""
    assert narrow.accept(alert(title))


def test_the_shape_really_does_fall_back_to_the_source(narrow: Filter):
    """Pin the mechanism, not just the symptom - if `key` stops doing this the
    tests above would pass for the wrong reason."""
    assert narrow.key(alert("anything"))[0] == "trading"


def test_a_non_critical_trading_message_is_still_filtered(narrow: Filter):
    """The bypass is for `critical` alone. A shape filter that stops meaning
    anything is a channel nobody reads, which is the failure it prevents."""
    assert "not in" in narrow.rejects(alert("a routine note", level="info"))
    assert not narrow.accept(alert("a routine note", level="info"))


def test_an_uninteresting_instrument_still_reaches_someone_when_critical(narrow: Filter):
    """A system-level fault has no instrument, and a feed list must not decide
    whether the desk may say it is broken."""
    payload = alert("the desk cannot reach its terminal")
    payload["fields"] = {"instrument": "boom_500_index"}
    assert narrow.accept(payload)


def test_the_spam_guards_still_apply_to_critical(narrow: Filter):
    """Cooldown is a different job from interest. A critical alert repeating
    every heartbeat is its own kind of broken - `_check_autotrading` and
    `_watch_reachable` are both edge-triggered for exactly this reason."""
    assert narrow.accept(alert("AutoTrading is off"))
    assert not narrow.accept(alert("AutoTrading is off")), "the second is a repeat"


def test_a_dropped_critical_is_logged_loudly(narrow: Filter, caplog):
    """A silenced alarm is itself a fault, and at `debug` it is invisible in a
    container running at INFO - which is how this went unnoticed."""
    narrow.accept(alert("AutoTrading is off"))
    with caplog.at_level(logging.WARNING):
        narrow.accept(alert("AutoTrading is off"))
    assert any("dropped" in r.getMessage() for r in caplog.records)


def test_a_dropped_routine_message_stays_quiet(narrow: Filter, caplog):
    """The loud path is for critical only, or the log becomes the noise."""
    with caplog.at_level(logging.WARNING):
        narrow.accept(alert("a routine note", level="info"))
    assert not [r for r in caplog.records if "dropped" in r.getMessage()]
