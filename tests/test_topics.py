"""The topic names, and that the calls under them actually exist.

**This file exists because a mock hid a missing API.** Three modules called
`Actor.publish_data_dict` / `subscribe_data_dict`, which Nautilus does not
have, and every test passed - because each stubbed the method
(`actor.publish_data_dict = lambda ...`), and assigning an attribute *creates*
it. A node would have raised `AttributeError` on its first publish.

So the tests here assert against `nautilus_trader`'s own classes rather than
against ours. A stub on one of our objects cannot satisfy them.
"""

from __future__ import annotations

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.trading.strategy import Strategy

from till_infinity.utils import topics

# ------------------------------------------------- the API actually exists


def test_the_bus_calls_we_publish_through_exist_on_nautilus():
    """Asserted on the framework's class, so no stub of ours can pass it."""
    from nautilus_trader.common.component import MessageBus

    assert hasattr(MessageBus, "publish")
    assert hasattr(MessageBus, "subscribe")
    assert hasattr(Actor, "msgbus")
    assert hasattr(Strategy, "msgbus")


# The guard pointing the other way - that Nautilus has not since *added*
# `publish_data_dict` and friends - lived here too, asserting exactly what
# `test_nautilus_api.test_the_names_the_sweep_found_still_do_not_exist` already
# asserts for `Actor` and `Strategy`. Two people wrote the same test from the
# same incident. The parametrised one survived because it covers the two names
# this file never knew about, `Actor.create_task` and
# `LiveExecutionClient._uuid4`.


def test_nothing_in_the_tree_calls_the_methods_that_do_not_exist():
    """The check that would have caught it in the first place."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "till_infinity"
    names = ("publish_data_dict", "subscribe_data_dict", "on_data_dict")
    offenders = [
        f"{path.name}:{name}"
        for path in root.rglob("*.py")
        for name in names
        if f".{name}(" in (text := path.read_text()) or f"def {name}(" in text
    ]
    assert not offenders, f"calls a Nautilus method that does not exist: {offenders}"


# ----------------------------------------------------------- the registry


def test_an_undeclared_topic_is_refused_both_ways():
    """A typo publishes into silence, and nothing downstream can tell that
    from a quiet market."""

    class Fake:
        class msgbus:  # noqa: N801 - mimics the attribute, not a class name
            @staticmethod
            def publish(topic, msg):
                raise AssertionError("should not be reached")

            @staticmethod
            def subscribe(topic, handler):
                raise AssertionError("should not be reached")

    with pytest.raises(ValueError, match="not a declared topic"):
        topics.publish(Fake(), "prices.nonsense", {})
    with pytest.raises(ValueError, match="not a declared topic"):
        topics.subscribe(Fake(), "prices.nonsense", print)


def test_a_declared_topic_reaches_the_bus():
    """The power assertion for the refusal above: a `publish` that refused
    everything would satisfy it.

    The bus here is a stub, deliberately - what is under test is the registry
    helper, not Nautilus. That the real `MessageBus` records a subscription is
    `test_notifier_actor.test_the_subscription_is_registered_on_nautilus_own_bus`,
    which is the half a stub cannot answer.
    """
    sent: list[tuple[str, object]] = []
    taken: list[tuple[str, object]] = []

    class Fake:
        class msgbus:  # noqa: N801
            @staticmethod
            def publish(topic, msg):
                sent.append((topic, msg))

            @staticmethod
            def subscribe(topic, handler):
                taken.append((topic, handler))

    topics.publish(Fake(), topics.ALERTS, {"title": "x"})
    topics.subscribe(Fake(), topics.JOURNAL, print)
    assert sent == [("alerts", {"title": "x"})]
    assert taken == [("journal", print)]


def test_every_declared_topic_is_a_distinct_lowercase_name():
    """Two constants with one string is a subscriber receiving another
    subject's messages, and neither end can tell.

    Not "dotted", which this was called: `alerts` and `journal` carry no dot,
    because they are single subjects rather than families. The properties
    actually held are the ones a typo breaks - distinct, non-empty, and with
    no stray whitespace or capital to make two spellings of one topic.
    """
    assert len(set(topics.DECLARED)) == len(topics.DECLARED)
    for name in topics.DECLARED:
        assert name
        assert name == name.strip()
        assert name.islower(), name


def test_the_constants_and_the_registry_agree():
    """A constant missing from `DECLARED` is a publisher that will be refused
    at run time by the very helper meant to protect it."""
    named = {
        value
        for key, value in vars(topics).items()
        if key.isupper() and key != "DECLARED" and isinstance(value, str)
    }
    assert named == set(topics.DECLARED), named.symmetric_difference(topics.DECLARED)
