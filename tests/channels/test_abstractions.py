"""Tests for the pluggable channel abstractions:
serializer, backoff, metrics, DLQ."""

import asyncio
import contextlib
import os
import tempfile

import pytest

from till_infinity.channels import (
    DeadLetterQueue,
    ExponentialBackoff,
    FixedBackoff,
    InMemoryMetrics,
    JSONSerializer,
    StringSerializer,
    get_default_metrics,
    set_default_metrics,
    wrap_with_outbox,
)


@pytest.fixture
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)


# ════════ Serializer ════════
def test_json_serializer_roundtrip():
    s = JSONSerializer()
    for payload in [{"a": 1}, [1, 2, 3], "hello", 42, None, {"nested": {"x": [1, 2]}}]:
        assert s.decode(s.encode(payload)) == payload


def test_json_serializer_returns_bytes():
    s = JSONSerializer()
    out = s.encode({"a": 1})
    assert isinstance(out, bytes)


def test_string_serializer_passes_text_through():
    s = StringSerializer()
    decoded = s.decode(s.encode("plain text"))
    assert decoded == "plain text"


def test_string_serializer_parses_json_when_present():
    s = StringSerializer()
    assert s.decode(b'{"a": 1}') == {"a": 1}


# ════════ Backoff ════════
def test_fixed_backoff_is_constant():
    b = FixedBackoff(seconds=2.5)
    assert b.delay(0) == 2.5
    assert b.delay(10) == 2.5


def test_exponential_backoff_grows():
    b = ExponentialBackoff(initial=1.0, multiplier=2.0, max_delay=100.0)
    assert b.delay(0) == 1.0
    assert b.delay(1) == 2.0
    assert b.delay(2) == 4.0
    assert b.delay(3) == 8.0


def test_exponential_backoff_caps_at_max():
    b = ExponentialBackoff(initial=1.0, multiplier=2.0, max_delay=5.0)
    assert b.delay(10) == 5.0
    assert b.delay(100) == 5.0


def test_exponential_backoff_jitter_stays_in_range():
    b = ExponentialBackoff(initial=1.0, multiplier=1.0, max_delay=10.0, jitter=0.2)
    for _ in range(50):
        d = b.delay(0)
        assert 0.8 <= d <= 1.2


# ════════ Metrics ════════
def test_inmemory_metrics_counts_sends():
    m = InMemoryMetrics()
    m.send("ch1", 0.01)
    m.send("ch1", 0.02)
    m.send("ch2", 0.01)
    assert m.counters["sends:ch1"] == 2
    assert m.counters["sends:ch2"] == 1


def test_inmemory_metrics_records_errors():
    m = InMemoryMetrics()
    m.error("ch1", "send", "boom")
    assert ("ch1", "send", "boom") in m.errors
    assert m.counters["errors:ch1:send"] == 1


def test_default_metrics_is_swappable():
    original = get_default_metrics()
    try:
        custom = InMemoryMetrics()
        set_default_metrics(custom)
        assert get_default_metrics() is custom
    finally:
        set_default_metrics(original)


# ════════ DLQ ════════
def test_dlq_parks_messages(tmp_db):
    dlq = DeadLetterQueue(tmp_db, "test-ch")
    dlq.park({"bad": 1}, "err")
    dlq.park({"bad": 2}, "err")
    assert dlq.size() == 2
    listing = dlq.list()
    assert len(listing) == 2


def test_dlq_requeue_removes(tmp_db):
    dlq = DeadLetterQueue(tmp_db, "test-ch")
    ids = [dlq.park(f"msg-{i}", "err") for i in range(3)]
    assert dlq.size() == 3
    dlq.requeue(ids[:2])
    assert dlq.size() == 1


# ════════ DurableSender with DLQ + backoff + metrics ════════
class _FlakyPrimary:
    def __init__(self):
        self.fail_count = 0
        self.is_closed = False

    async def send(self, msg):
        raise ConnectionError("always offline")

    def try_send(self, msg):
        raise ConnectionError("always offline")

    async def close(self):
        self.is_closed = True

    def __len__(self):
        return 0


def test_durable_sender_parks_to_dlq_after_max_attempts(tmp_db):
    """A message that fails max_attempts times goes to DLQ."""

    async def scenario():
        metrics = InMemoryMetrics()
        dlq = DeadLetterQueue(tmp_db, "flaky")
        tx = wrap_with_outbox(
            _FlakyPrimary(),
            tmp_db,
            "flaky",
            dlq=dlq,
            max_attempts=2,
            backoff=FixedBackoff(0.01),
            metrics=metrics,
        )
        # First send fails → stashed
        await tx.send({"n": 1})
        # Wait for the replay loop to retry past max_attempts
        for _ in range(20):
            await asyncio.sleep(0.05)
            if dlq.size() >= 1:
                break

        assert dlq.size() >= 1
        # Metrics captured the failures
        assert metrics.counters.get("errors:flaky:send", 0) >= 1

    asyncio.run(scenario())


def test_durable_sender_records_success_metrics(tmp_db):
    class _OkPrimary:
        is_closed = False
        sent = []

        async def send(self, m):
            self.sent.append(m)

        def try_send(self, m):
            self.sent.append(m)

        async def close(self):
            pass

        def __len__(self):
            return 0

    async def scenario():
        metrics = InMemoryMetrics()
        tx = wrap_with_outbox(
            _OkPrimary(),
            tmp_db,
            "ok-ch",
            metrics=metrics,
        )
        await tx.send({"a": 1})
        await tx.send({"a": 2})
        assert metrics.counters["sends:ok-ch"] == 2
        assert len(metrics.timers["send_time:ok-ch"]) == 2

    asyncio.run(scenario())
