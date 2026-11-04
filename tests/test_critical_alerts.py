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

from till_infinity.notifications.filters import DEFAULT_MAX_PER_HOUR, Filter


@pytest.fixture
def narrow(monkeypatch) -> Filter:
    """The production shape list, which names no trading shape at all.

    **There is no instrument filter any more.** `NOTIFY_FEEDS` was a second
    symbol specification and it was removed on 2026-11-04: it keyed on
    `volatility_75_index` while `sizes.feed_of` produces `volatility 75 index`,
    so the moment the desk took on a symbol with a space in its name every
    alert for it would have been dropped - silently, with the reason logged as
    an instrument "not in" a list. Narrowing is on shapes alone now.
    """
    monkeypatch.setenv("NOTIFY_SHAPES", "level,drift,agent,trade")
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


def test_an_alarm_sent_as_an_ordinal_gets_through_too(narrow: Filter):
    """The same bypass, in the encoding the contract also allows.

    `shared/contracts/bus/alerts.json` says a level is "a name or its
    ordinal", and the bypass compared the payload against the string
    `"critical"` - so a publisher sending `level: 2` was filtered like a topic
    preference. The defect this file is about, in the other encoding, found by
    reading the contract against the gate.
    """
    numeric = alert("AutoTrading is off")
    numeric["level"] = 2
    assert narrow.rejects(numeric) == ""


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


# ------------------------------------------------- and through the Actor

# **The gate above was unit-tested and wired to nothing.** `Filter` was
# applied by `notifications/service.py:listen`, which retired on 2026-11-01,
# and `notifications/actor.py` replaced it with a level check and a
# title-keyed dedupe of its own - so every test in this file passed while the
# live path had no shape gate, no instrument gate, no hourly ceiling and
# therefore no bypass for the one thing they are all wrong about.
#
# These publish through Nautilus's own `MessageBus` into a started actor, so
# what is asserted is the delivery the desk would get on the worst day.


@pytest.fixture
def actor(monkeypatch, narrow: Filter):
    """A started actor reading the same environment `narrow` is built from.

    It builds its own `Filter` in `on_start`, which is why `narrow` is a
    dependency rather than something injected: the environment has to be set
    before the actor starts, the same order a container has.
    """
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    from till_infinity.notifications import Delivery
    from till_infinity.notifications.actor import Notifier, NotifierConfig

    sent: list = []

    async def record(message, **_):
        sent.append(message)
        return [Delivery("telegram[ops]", ok=True)]

    monkeypatch.setattr("till_infinity.notifications.notify", record)
    built = Notifier(NotifierConfig(minimum_level=0))
    bus = TestComponentStubs.msgbus()
    built.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=bus,
        cache=TestComponentStubs.cache(),
        clock=TestComponentStubs.clock(),
    )
    built.start()
    return built, bus, sent


@pytest.mark.parametrize(
    "title",
    [
        "the desk cannot reach its terminal",
        "AutoTrading is off",
        "trading is not attached",
    ],
)
def test_every_trading_alarm_reaches_a_destination_through_the_actor(actor, title: str):
    """The same three, end to end. Named individually so a regression says
    which alarm a node would now swallow."""
    _built, bus, sent = actor
    bus.publish(topic="alerts", msg=alert(title))
    assert [message.title for message in sent] == [f"live: {title}"]


def test_a_routine_trading_message_is_still_filtered_by_the_actor(actor):
    """The bypass is for `critical` alone, on the live path too. A shape filter
    that stops meaning anything is a channel nobody reads."""
    built, bus, sent = actor
    bus.publish(topic="alerts", msg=alert("a routine note", level="info"))
    assert sent == []
    assert built.tally["dropped"] == 1


def test_an_hour_of_chatter_cannot_silence_a_trading_alarm(actor):
    """**Measured failing before it was fixed**, on the live actor path.

    The hourly cap is one budget shared by everything and the noisiest
    producer wins it, which is why `UNCAPPED` exists - and the cap carried the
    same off-by-a-word as the shape gate this file is about: `UNCAPPED` names
    `trade`, `key` falls back to the source, and the source is `trading`. So
    20 gold level calls followed by `AutoTrading is off` gave `20 already sent
    this hour`: the desk down, the channel full of level calls, and the one
    message that mattered refused by the budget.

    The cap is still *counted* against - a burst of alarms correctly quietens
    everything else - and the cooldown still applies, which the test above
    pins."""
    built, bus, sent = actor
    for n in range(DEFAULT_MAX_PER_HOUR + 5):
        bus.publish(
            topic="alerts",
            msg={
                "title": f"gold 1m level {n}",
                "level": "info",
                "fields": {"shape": "level", "instrument": "gold", "ref": str(n)},
            },
        )
    assert built.tally["dropped"] >= 5, "the hourly ceiling never engaged"
    before = len(sent)
    bus.publish(topic="alerts", msg=alert("AutoTrading is off"))
    assert len(sent) == before + 1
