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


def test_the_dict_flavoured_methods_still_do_not_exist():
    """A regression guard pointing the other way.

    If a future Nautilus adds `publish_data_dict`, this fails and someone
    should decide whether to use it - rather than three modules quietly
    calling it again because the name reads plausibly.
    """
    for name in ("publish_data_dict", "subscribe_data_dict", "on_data_dict"):
        assert not hasattr(Actor, name), f"Actor gained {name}: revisit utils/topics.py"
        assert not hasattr(Strategy, name), f"Strategy gained {name}"


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


def test_every_declared_topic_is_a_distinct_dotted_name():
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
