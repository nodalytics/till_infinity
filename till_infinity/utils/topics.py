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

#: Which instruments are currently volatile enough to scalp, as a ranking.
#:
#: Its own topic rather than a field on a reading, for the reason `PROPOSALS`
#: is separate from `DISPERSION`: a ranking changes on a slow timer and is read
#: by every desk, while a reading changes per bar and is read by one.
VOLATILE = "screen.volatile"
STATESPACE_SIGNALS = "statespace.signals"

# ──── the desk ────

#: Findings, for a person. The notifier subscribes and nothing acts on one.
#:
#: **This topic used to carry commands as well**, and the two spoke different
#: payload languages on one bus: `ExitMechanism.on_alert` read a *top-level*
#: `shape` to recognise a close request, while `notifications.filters` reads
#: `fields.shape` to route a message. A payload in the wrong one was dropped
#: in silence by whichever reader it was not written for - three times in two
#: days, each discovered by accident:
#:
#: * `basket.close` is correct for the command reader and invisible to the
#:   notifier;
#: * `proposing.proposal_for` stamps a top-level `shape` and its own comment
#:   claims it is "routed on by `notifications/filters.py`", recording that it
#:   had already been dropped once;
#: * the first version of `ExitMechanism._announce` published top level and
#:   was dropped as `shape '' not in [...]`.
#:
#: So commands moved to `COMMANDS` and this carries notifications only. One
#: reader, one schema, and a payload that goes to the wrong place now goes
#: nowhere loudly rather than quietly.
ALERTS = "alerts"

#: Asking another component of this desk to do something.
#:
#: Distinct from `ALERTS` because the reader acts rather than reports, and a
#: close request that is merely *announced* is the failure `basket.py` records
#: in its own docstring: "`alerts` had one subscriber, the Telegram notifier,
#: so this published a close request that became a message and never an
#: order - the log said 'closing all N position(s)' and the counter agreed".
COMMANDS = "commands"

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

#: Whether the venue will accept an order **right now**, published by the
#: execution client because it is the only component holding a bridge.
#:
#: The heartbeat has to report this and cannot read it: an `Actor` has the bus,
#: the cache, the clock and the portfolio, and no transport. On 2026-11-04 the
#: terminal's AutoTrading was off and every order came back `10027` while
#: `/account/health`, `/terminal/ping` and the **account's own**
#: `trade_allowed` all read green - so the desk could not place an order and
#: nothing it published said so.
VENUE_TRADING = "venue.trading"

#: Every topic this desk declares. A publisher using a name not in here is
#: publishing where nothing listens, which is the failure a registry catches
#: and a literal does not.
#:
#: **Declared is not the same as wired.** Only `ALERTS`, `COMMANDS` and
#: `JOURNAL` have a
#: publisher and a subscriber in the ported desk; the rest were the retired
#: services' and are kept because the names are the contract a producer would
#: have to publish on. Declaring one does not mean something is listening.
DECLARED: tuple[str, ...] = (
    ALERTS,
    COMMANDS,
    LADDER,
    VENUE_TRADING,
    ARTICLES,
    BARS,
    DISPERSION,
    EVENTS,
    JOURNAL,
    MACRO,
    PROPOSALS,
    QUOTES,
    VOLATILE,
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


def alert(
    *,
    shape: str,
    title: str,
    body: str = "",
    source: str = "",
    level: str = "info",
    instrument: str = "",
    **fields: Any,
) -> dict[str, Any]:
    """One alert payload, built here so no publisher has to remember the shape.

    **`shape` belongs inside `fields` and three publishers put it outside.**
    `filters.Filter.key` reads `fields.get("shape") or source`, so a top-level
    one is invisible and the alert is dropped as `shape '' not in [...]` with
    nothing logged where it was published. That happened to
    `proposing.proposal_for` - whose own comment records it - and again to the
    first version of `ExitMechanism._announce`, and it is why `basket.close`,
    correct for the command reader it was written for, never reached a person.

    `level` rides at the top, where `from_message` reads it, and not in
    `fields`, which is the structured block a destination renders. Keeping
    both facts in one function is the point: a caller that gets the schema
    wrong now cannot, because it does not write the schema.

    `instrument` is named rather than left to `**fields` because the repeat
    check keys on it beside the shape, and two feeds that leave it empty
    silence each other.
    """
    named = {str(k): str(v) for k, v in fields.items() if v is not None and v != ""}
    named["shape"] = str(shape)
    if instrument:
        named["instrument"] = str(instrument)
    return {
        "title": str(title),
        "body": str(body),
        "source": str(source or shape),
        "level": str(level),
        "fields": named,
    }


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
