"""Topic names, and the two calls that put a message on Nautilus's bus.

## Why this module exists at all

The names are the contract between a publisher and a subscriber, and a name
only one module can spell is not a contract. There used to be a
`till_infinity/topics.py` whose docstring said the names were "read by a Go
service" and therefore had to be constants rather than an enum; there is no Go
service now, so that reason is gone and the module moved here, where
infrastructure lives and anything may import it.

## Why the helpers are here too, and what they replace

**`Actor.publish_data_dict` and `Actor.subscribe_data_dict` do not exist.**
Three modules called them - `statespace/actor.py`, `notifications/actor.py` and
`strategies/basket.py` - and every one would have raised `AttributeError` the
first time a node ran. Checked against 1.231: `Actor` has `publish_data`,
`subscribe_data`, `publish_signal`, `subscribe_signal` and `msgbus`, and
nothing with `_dict` in the name.

Worse, the tests passed. They stubbed the method -
`actor.publish_data_dict = lambda topic, payload: ...` - which **creates** the
attribute rather than checking one exists, so a mock stood in for an API that
was never there. That is the failure this module is shaped to prevent: one
place does the publishing, `test_topics.py` asserts the underlying call exists
on Nautilus's own class, and a stub cannot satisfy that.

## The mechanism

`publish_data` wants a `DataType` and a `Data` subclass, which is right for
market data and wrong for a dict of journal context. `publish_signal` takes a
name and a scalar. For an arbitrary payload on a named topic the mechanism is
the bus itself: `msgbus.publish(topic, msg)` and
`msgbus.subscribe(topic, handler)`. That is what Nautilus's own components use
internally, and it carries any object.
"""

from __future__ import annotations

from typing import Any

# ──── prices ────
BARS = "prices.bars"
QUOTES = "prices.quotes"

# ──── news ────
ARTICLES = "news.articles"
EVENTS = "news.events"
MACRO = "news.macro"

# ──── structures ────
RESOLUTIONS = "structures.resolutions"
SIGNALS = "structures.signals"

# ──── statespace ────
DISPERSION = "statespace.dispersion"
PROPOSALS = "statespace.proposals"
STATESPACE_SIGNALS = "statespace.signals"

# ──── the desk ────
ALERTS = "alerts"
JOURNAL = "journal"

#: What the promotion ladder decided, for the one thing it cannot do itself.
#:
#: `node/pipeline.step` decides and does not act, deliberately - "the node
#: holds the `Trader`, so this decides and the caller acts". An `Actor` cannot
#: reach the `Trader` either: it has the bus, the cache, the clock and the
#: portfolio, and stopping a strategy is a `Trader` call. So the actor publishes
#: here and `node/live` subscribes a handler that holds both the trader and the
#: risk engine. One hop, and it puts the capital change where the engine is
#: rather than behind a second copy of the arithmetic.
LADDER = "ladder"

#: Every topic this desk declares. A publisher using a name not in here is
#: publishing where nothing listens, which is the failure a registry catches
#: and a literal does not.
#:
#: **Declared is not the same as wired.** Only `ALERTS` and `JOURNAL` have a
#: publisher and a subscriber in the ported desk; the rest were the retired
#: services' and are kept because the names are the contract a producer would
#: have to publish on. Declaring one does not mean something is listening.
DECLARED: tuple[str, ...] = (
    ALERTS,
    LADDER,
    ARTICLES,
    BARS,
    DISPERSION,
    EVENTS,
    JOURNAL,
    MACRO,
    PROPOSALS,
    QUOTES,
    RESOLUTIONS,
    SIGNALS,
    STATESPACE_SIGNALS,
)


def publish(component: Any, topic: str, payload: Any) -> None:
    """Put `payload` on `topic`, through Nautilus's own bus.

    `component` is any `Actor` or `Strategy` - both carry `msgbus`. The topic
    is checked against `DECLARED`, because a typo publishes into silence and
    nothing downstream can tell that from a quiet market.
    """
    if topic not in DECLARED:
        raise ValueError(
            f"{topic!r} is not a declared topic, so nothing subscribes to it. "
            f"Declared: {', '.join(DECLARED)}."
        )
    component.msgbus.publish(topic=topic, msg=payload)


def subscribe(component: Any, topic: str, handler: Any) -> None:
    """Take `topic` off the bus into `handler`.

    The handler receives the payload alone - Nautilus's bus does not pass the
    topic - so a component listening on several topics either uses one handler
    per topic or reads the topic out of the payload.
    """
    if topic not in DECLARED:
        raise ValueError(
            f"{topic!r} is not a declared topic, so nothing publishes to it. "
            f"Declared: {', '.join(DECLARED)}."
        )
    component.msgbus.subscribe(topic=topic, handler=handler)
