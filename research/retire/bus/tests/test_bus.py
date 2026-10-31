"""The bus, and the seams that publish onto it."""

from __future__ import annotations

import asyncio
import contextlib
import logging as _logging

import pytest

from till_infinity import bus as topics
from till_infinity.bus import Bus, Message
from till_infinity.news.models import Article, Event
from till_infinity.news.models import WriteResult as NewsWrite
from till_infinity.news.service import Announcer
from till_infinity.notifications.service import from_message
from till_infinity.prices.models import Bar, Quote, QuoteKey, SeriesKey, Symbol, WriteResult
from till_infinity.prices.quotes import announce_quote, publishing
from till_infinity.prices.service import announce_bars


@contextlib.contextmanager
def caplog_at(level, name):
    """Collect records from one logger, without depending on caplog's
    propagation rules."""
    found = []

    class Grab(_logging.Handler):
        def emit(self, record):
            found.append(record)

    logger = _logging.getLogger(name)
    handler = Grab(level)
    logger.addHandler(handler)
    was = logger.level
    logger.setLevel(level)
    try:
        yield found
    finally:
        logger.removeHandler(handler)
        logger.setLevel(was)


KEY = SeriesKey("tradingview", "gold", Symbol("OANDA", "XAUUSD"), "1h")
QKEY = QuoteKey("tradingview", "gold", Symbol("PEPPERSTONE", "XAUUSD"))


# ------------------------------------------------------------------ the bus


async def test_publish_without_subscribers_is_free():
    bus = Bus()
    assert await bus.publish(topics.QUOTES, {"feed": "gold"}) == 0


async def test_every_group_gets_the_message():
    """The point of keying channels on (topic, group): fan-out, not work-sharing."""
    bus = Bus()
    agents = bus.subscribe(topics.QUOTES, group="agents")
    audit = bus.subscribe(topics.QUOTES, group="audit")

    assert await bus.publish(topics.QUOTES, {"bps": 4.2}, source="prices") == 2

    first, second = await agents.next(), await audit.next()
    assert first.payload == second.payload == {"bps": 4.2}
    assert first.source == "prices"


async def test_two_readers_of_one_group_share_the_work():
    """Same group is deliberately *not* fan-out - that is how you scale a consumer."""
    bus = Bus()
    bus.subscribe(topics.QUOTES, group="workers")
    for n in range(2):
        await bus.publish(topics.QUOTES, {"n": n})

    got = await asyncio.gather(
        bus.receive(topics.QUOTES, "workers"), bus.receive(topics.QUOTES, "workers")
    )
    assert sorted(m.payload["n"] for m in got) == [0, 1]


async def test_a_full_channel_drops_rather_than_stalls():
    bus = Bus(capacity=2)
    bus.subscribe(topics.BARS, group="slow")
    sent = [await bus.publish(topics.BARS, {"n": n}) for n in range(5)]
    assert sent == [1, 1, 0, 0, 0]


async def test_close_ends_iteration_and_silences_publish():
    bus = Bus()
    sub = bus.subscribe(topics.ALERTS, group="notifications")
    await bus.publish(topics.ALERTS, {"title": "hi"})

    seen = asyncio.create_task(_drain(sub))
    await asyncio.sleep(0)
    await bus.close()

    assert await asyncio.wait_for(seen, 2) == ["hi"]
    assert await bus.publish(topics.ALERTS, {"title": "after"}) == 0


async def _drain(sub) -> list[str]:
    return [m.payload["title"] async for m in sub]


@pytest.mark.parametrize("junk", [None, "text", 42, {}, {"payload": {}}])
def test_junk_off_the_wire_is_dropped_not_raised(junk):
    assert Message.from_dict(junk) is None


def test_a_message_survives_the_round_trip():
    original = Message(topic=topics.BARS, payload={"close": 4008.0}, source="prices")
    assert Message.from_dict(original.to_dict()) == original


def test_redis_shares_one_stream_across_groups():
    """Groups fan out via Redis consumer groups, so the key must not include them."""
    bus = Bus(redis_url="redis://localhost:6379")
    assert bus.backend == "redis"
    assert bus.key(topics.QUOTES) == "till:prices.quotes"


# --------------------------------------------------------------- the seams


def test_bars_payload_carries_the_latest_candle():
    old = Bar(time=1_000, open=1, high=2, low=0.5, close=1.5)
    new = Bar(time=4_600, open=1.5, high=3, low=1.4, close=2.9)
    payload = announce_bars(KEY, [old, new], WriteResult(inserted=2))

    assert payload["venue"] == "OANDA"
    assert payload["interval"] == "1h"
    assert payload["time"] == new.time
    assert payload["close"] == new.close
    assert payload["inserted"] == 2


def test_quote_payload_carries_the_derived_spread():
    payload = announce_quote(QKEY, Quote(time=1.0, bid=99.5, ask=100.5))
    assert payload["mid"] == 100.0
    assert payload["spread_bps"] == pytest.approx(100.0)


async def test_publishing_wraps_the_sink_and_still_writes():
    """Store first, announce after - the store stays the source of truth."""
    bus = Bus()
    sub = bus.subscribe(topics.QUOTES, group="agents")
    written: list[QuoteKey] = []

    async def sink(key, _quote):
        written.append(key)
        return WriteResult(inserted=1)

    result = await publishing(sink, bus)(QKEY, Quote(time=1.0, bid=1.0, ask=1.1))

    assert result.inserted == 1
    assert written == [QKEY]
    assert (await sub.next()).payload["venue"] == "PEPPERSTONE"


async def test_publishing_works_without_a_store():
    """A snapshot run has no sink; announcing must not depend on one."""
    bus = Bus()
    sub = bus.subscribe(topics.QUOTES, group="agents")
    assert (await publishing(None, bus)(QKEY, Quote(time=1.0, bid=1.0, ask=1.1))).touched == 0
    assert (await sub.next()).payload["bid"] == 1.0


# ----------------------------------------------------------- news announcer


def _article(ident: str) -> Article:
    return Article(source="rss", id=ident, title=f"story {ident}", url="http://x")


async def test_a_headline_is_announced_once():
    """The stores dedup but report only counts, so the announcer keeps its own memory."""
    bus = Bus()
    sub = bus.subscribe(topics.ARTICLES, group="agents")
    announcer = Announcer(bus)

    await announcer.articles([_article("a"), _article("b")])
    await announcer.articles([_article("a"), _article("b")])  # same poll, re-fetched

    assert [(await sub.next()).payload["title"] for _ in range(2)] == ["story a", "story b"]
    assert await bus.publish(topics.ARTICLES, {"sentinel": True}) == 1
    assert (await sub.next()).payload == {"sentinel": True}  # nothing queued between


async def test_the_announcer_memory_is_bounded():
    bus = Bus(capacity=10_000)
    bus.subscribe(topics.ARTICLES, group="agents")
    announcer = Announcer(bus, limit=10)
    await announcer.articles([_article(str(n)) for n in range(50)])
    assert len(announcer._seen) == 10


def _event(actual: str) -> Event:
    return Event(source="ff", id="nfp", title="Non-Farm Payrolls", time=1.0, actual=actual)


async def test_an_event_is_re_announced_when_it_prints():
    bus = Bus()
    sub = bus.subscribe(topics.EVENTS, group="agents")
    announcer = Announcer(bus)

    await announcer.events([_event("")])  # upcoming
    await announcer.events([_event("")])  # still upcoming, no news
    await announcer.events([_event("150K")])  # printed

    assert (await sub.next()).payload["released"] is False
    printed = await sub.next()
    assert printed.payload["released"] is True
    assert printed.payload["actual"] == "150K"


async def test_macro_announces_a_count_not_every_row():
    """One IMF pull is thousands of historic rows; the notice is the count."""
    bus = Bus()
    sub = bus.subscribe(topics.MACRO, group="agents")
    announcer = Announcer(bus)

    await announcer.macro("imf", NewsWrite(), rows=0)  # nothing changed, nothing said
    await announcer.macro("imf", NewsWrite(inserted=18_843), rows=18_843)

    payload = (await sub.next()).payload
    assert payload == {"source": "imf", "inserted": 18_843, "updated": 0, "rows": 18_843}


# --------------------------------------------------------- alerts consumer


def test_an_alert_becomes_a_notification():
    notification = from_message(
        {"title": "Gold spread blew out", "level": "warning", "fields": {"bps": 4.2}}
    )
    assert notification.title == "Gold spread blew out"
    assert notification.level.name == "WARNING"
    assert notification.fields == {"bps": "4.2"}  # flattened - notifiers render text


@pytest.mark.parametrize("payload", [{}, {"title": "   "}, {"body": "no title"}])
def test_a_titleless_alert_is_dropped(payload):
    assert from_message(payload) is None


def test_a_hostile_payload_cannot_break_the_notifier():
    """Alerts come from an agent, so nothing in them is trusted."""
    notification = from_message({"title": "x", "fields": ["not", "a", "dict"], "level": 99})
    assert notification.fields == {}
    assert notification.level.name == "CRITICAL"  # clamped, not crashed


def test_every_new_bar_reaches_the_bus_not_only_the_newest():
    """The live path used to see less than the store, silently.

    One notice went out per sweep carrying only the newest bar, so any sweep
    that wrote more than one - after a gap, a restart, or on an interval slower
    than the sweep cadence - formed levels from a subset of the series and
    counted touches on a subset of the interactions. Same shape as the
    close-only bug, and just as quiet.
    """
    from till_infinity.prices.service import notices

    bars = [
        Bar(time=1_700_000_000 + i * 300, open=10.0, high=11.0, low=9.0, close=10.5, volume=3)
        for i in range(4)
    ]
    out = notices(KEY, bars, WriteResult(inserted=3))
    assert len(out) == 3, "three bars were written, three should be announced"
    # Oldest first, so a consumer folds them in the order they happened.
    assert [n["time"] for n in out] == [b.time for b in bars[1:]]


def test_a_backfill_is_capped_rather_than_replayed_onto_the_bus():
    """`structures` seeds from the store for bulk; this path is for keeping up."""
    from till_infinity.prices.service import MAX_NOTICES, notices

    bars = [
        Bar(time=1_700_000_000 + i * 300, open=10.0, high=11.0, low=9.0, close=10.5, volume=3)
        for i in range(50)
    ]
    out = notices(KEY, bars, WriteResult(inserted=50))
    assert len(out) == MAX_NOTICES
    # And it keeps the newest, which are the ones still worth acting on.
    assert out[-1]["time"] == bars[-1].time


def test_a_single_new_bar_still_announces_once():
    from till_infinity.prices.service import notices

    bar = Bar(time=1_700_000_000, open=10.0, high=11.0, low=9.0, close=10.5, volume=3)
    assert len(notices(KEY, [bar], WriteResult(inserted=1))) == 1


@pytest.mark.asyncio
async def test_publishing_with_nobody_subscribed_says_so():
    """**Publishing into a void is silent and looks exactly like working.**

    The publisher's counters go up, its journal fills, its logs read normally,
    and the consumer sits in its pump with nothing arriving - so the failure
    presents as a desk that has simply gone quiet. On 2026-09-16 structures
    published 18,565 signals in twenty-five minutes while trading recorded
    none, and nothing anywhere said the two were not connected.
    """
    import logging

    from till_infinity import bus as b

    line = b.Bus()
    with caplog_at(logging.WARNING, b.log.name) as records:
        sent = await line.publish("nobody.listens", {"a": 1})
        assert sent == 0
    assert any("nobody subscribed" in r.getMessage() for r in records), [
        r.getMessage() for r in records
    ]


@pytest.mark.asyncio
async def test_a_topic_with_a_subscriber_says_nothing():
    """It has to stay quiet in the ordinary case, or it is noise that gets
    filtered and then misses the one time it matters."""
    import logging

    from till_infinity import bus as b

    line = b.Bus()
    line.subscribe("somebody.listens", "a-group")
    with caplog_at(logging.WARNING, b.log.name) as records:
        assert await line.publish("somebody.listens", {"a": 1}) == 1
    assert not [r for r in records if "nobody subscribed" in r.getMessage()]


async def test_both_sweeps_report_bars_that_never_reached_the_live_path(caplog):
    """**The derived-spread sweep announced without counting what it dropped.**

    `notices` truncates to `MAX_NOTICES`, and the collection sweep logged the
    shortfall while the spread sweep published the batch and said nothing - so a
    spread catching up on more than eight bars lost its oldest ones silently,
    which is the one shape `MAX_NOTICES` documents a warning against. Both now
    go through `announce`.
    """
    import logging

    from till_infinity.prices.service import MAX_NOTICES, announce

    class Recorder:
        def __init__(self):
            self.sent = []

        async def publish(self, topic, payload, source=""):
            self.sent.append(payload)

    extra = 4
    bars = [
        Bar(time=1_700_000_000 + i * 300, open=10.0, high=11.0, low=9.0, close=10.5, volume=3)
        for i in range(MAX_NOTICES + extra)
    ]
    bus = Recorder()

    with caplog.at_level(logging.WARNING, logger="till_infinity.prices"):
        await announce(bus, KEY, bars, WriteResult(inserted=len(bars)))

    assert len(bus.sent) == MAX_NOTICES, len(bus.sent)
    assert bus.sent[-1]["time"] == bars[-1].time
    said = caplog.text
    assert "never reached the live path" in said, said
    assert str(extra) in said, said


def test_nothing_publishes_a_notice_without_going_through_announce():
    """Structural, deliberately. The defect was not a wrong line but a *second*
    call site that did not repeat the accounting, so what needs guarding is that
    no third one appears - which the behavioural test above cannot see."""
    import inspect

    from till_infinity.prices import service

    source = inspect.getsource(service)
    publishes = [
        line.strip()
        for line in source.splitlines()
        if "bus.publish(BARS" in line or "publish(BARS" in line
    ]
    inside_announce = inspect.getsource(service.announce)

    for line in publishes:
        assert line in inside_announce, f"a BARS notice is published outside announce(): {line}"
