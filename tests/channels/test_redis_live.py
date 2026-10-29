"""The Redis transport, against a real Redis.

**Nothing exercised this path before.** The one test that named Redis built a
`Bus(redis_url=...)` and asserted on `backend` and `key` - it never connected,
published or received, and the `redis` client was not even installed in the
dev environment. That is how a codec that turned every number into a string
and every `False` into a truthy `"False"` stayed green: the only code that
would have noticed was never run.

So these connect. They skip where there is no Redis, and CI provides one as a
service container, which is the arrangement that makes the skip honest rather
than permanent. `test_the_live_tests_are_not_skipped_in_ci` fails if CI ever
starts skipping them.
"""

from __future__ import annotations

import os
import uuid

import pytest

from till_infinity import bus as topics
from till_infinity.bus import Bus

URL = os.environ.get("TILL_TEST_REDIS_URL", "redis://localhost:6379")

pytest.importorskip("redis", reason="the redis extra is not installed")


def reachable(url: str) -> bool:
    import redis

    try:
        redis.from_url(url, socket_connect_timeout=2).ping()
    except Exception:
        return False
    return True


@pytest.fixture(scope="module")
def url() -> str:
    if not reachable(URL):
        pytest.skip(f"no Redis at {URL}")
    return URL


@pytest.fixture
def key() -> str:
    """A fresh stream per test, so one test cannot read another's backlog."""
    return f"probe.{uuid.uuid4().hex[:12]}"


PAYLOAD = {
    "symbol": "EURUSD",
    "close": 1.08123,
    "volume": 0,
    "live": False,
    "spread": None,
    "meta": {"interval": "1m", "bars": [1, 2.5]},
}


async def test_a_payload_crosses_redis_unchanged(url, key):
    """Exact types through a real stream, not just through the codec."""
    from till_channels import redis_channel

    sender, receiver = redis_channel(f"till:{key}", group="one", url=url)
    await sender.send(PAYLOAD)
    got = await receiver.recv()
    assert got == PAYLOAD
    # Spelled out because `==` alone would pass on the strings the old codec
    # produced: `"0" == 0` is False, but `"0"` is truthy and `0` is not, and it
    # was the truthiness that flipped behaviour in the consumers.
    assert got["volume"] == 0
    assert not got["volume"]
    assert got["live"] is False
    assert got["spread"] is None


async def test_every_group_sees_every_message(url, key):
    """The fan-out `Bus.publish` depends on: one stream, a group per reader.

    This is why `bus.key()` must not include the group - if it did, each
    reader would get its own stream and the publisher would have to write
    once per subscriber.
    """
    from till_channels import redis_channel

    a_send, a_recv = redis_channel(f"till:{key}", group="alpha", url=url)
    _, b_recv = redis_channel(f"till:{key}", group="beta", url=url)

    await a_send.send({"n": 1})
    await a_send.send({"n": 2})

    assert [(await a_recv.recv())["n"] for _ in range(2)] == [1, 2]
    assert [(await b_recv.recv())["n"] for _ in range(2)] == [1, 2]


async def test_a_group_joining_late_does_not_replay_the_backlog(url, key):
    """Otherwise every restart re-delivers the history as though it were new,
    and the desk acts twice on bars it already saw."""
    from till_channels import redis_channel

    sender, _ = redis_channel(f"till:{key}", group="early", url=url)
    await sender.send({"n": "before"})

    late_send, late_recv = redis_channel(f"till:{key}", group="late", url=url)
    await late_send.send({"n": "after"})
    assert (await late_recv.recv())["n"] == "after"


async def test_a_group_that_already_exists_still_catches_up(url, key):
    """The other half of the previous test, and the one that keeps it honest.

    A new group skipping the backlog must not mean a *restarting* service
    skips what it missed. The group persists in Redis with its own
    last-delivered-id, so a second reader on the same group name resumes
    there - which is why `xgroup_create` failing for an existing group is the
    normal case and is suppressed.
    """
    from till_channels import redis_channel

    sender, first_reader = redis_channel(f"till:{key}", group="restarts", url=url)
    await sender.send({"n": 1})
    assert (await first_reader.recv())["n"] == 1

    # The service is down here, and two messages arrive without it.
    await sender.send({"n": 2})
    await sender.send({"n": 3})

    _, after_restart = redis_channel(f"till:{key}", group="restarts", url=url)
    caught_up = [(await after_restart.recv())["n"] for _ in range(2)]
    assert caught_up == [2, 3], "a restart must not skip what arrived while it was down"


async def test_a_publisher_with_no_local_subscriber_still_writes(url, key):
    """The bug that made the compose topology impossible.

    `publish` looped the groups *this* process had opened. A collector
    subscribes to nothing it publishes, so the loop body never ran: nothing
    reached Redis and the log filled with "nobody subscribed". A publisher
    must not need to know its readers - that is the whole property a stream
    provides, and the one a Go service depends on.
    """
    namespace = f"test{uuid.uuid4().hex[:8]}"
    reader = Bus(redis_url=url, namespace=namespace)
    writer = Bus(redis_url=url, namespace=namespace)
    try:
        # The reader registers first, as a separate process would.
        subscription = reader.subscribe(topics.QUOTES, group="consumer")
        assert writer.groups(topics.QUOTES) == [], "the writer subscribes to nothing"

        assert await writer.publish(topics.QUOTES, {"bid": 1.0812}) == 1

        message = await subscription.next()
        assert message is not None
        assert message.payload["bid"] == 1.0812
    finally:
        await reader.close()
        await writer.close()


async def test_two_buses_are_one_bus_over_redis(url):
    """The point of the whole slice: a publisher and a subscriber that share
    no memory. This is what a service in another language joins."""
    namespace = f"test{uuid.uuid4().hex[:8]}"
    publisher = Bus(redis_url=url, namespace=namespace)
    subscriber = Bus(redis_url=url, namespace=namespace)
    try:
        subscription = subscriber.subscribe(topics.QUOTES, group="reader")
        assert await publisher.publish(topics.QUOTES, {"bid": 1.0812, "stale": False}) == 1

        message = await subscription.next()
        assert message is not None
        assert message.payload["bid"] == 1.0812
        assert message.payload["stale"] is False, "a falsy flag must survive the bus"
    finally:
        await publisher.close()
        await subscriber.close()


@pytest.mark.skipif(not os.environ.get("CI"), reason="only meaningful in CI")
def test_the_live_tests_are_not_skipped_in_ci():
    """A skip that becomes permanent is a deleted test with extra steps."""
    assert reachable(URL), (
        f"CI must provide Redis at {URL} - these tests are the only thing that "
        f"has ever run the transport"
    )
