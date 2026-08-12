"""Tests for the SQLite outbox that sits under Redis/Mongo senders."""
import asyncio
import os
import tempfile

import pytest

from till_infinity.channels import Outbox, DurableSender
from till_infinity.channels.errors import ChannelClosed


@pytest.fixture
def outbox_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def test_outbox_stash_and_peek(outbox_path):
    ob = Outbox(outbox_path, "test")
    ob.stash({"x": 1}, "err1")
    ob.stash({"x": 2}, "err2")
    assert ob.pending_count() == 2
    pending = ob.peek(10)
    assert len(pending) == 2
    assert pending[0][1] == {"x": 1}
    assert pending[1][1] == {"x": 2}


def test_outbox_ack_removes_rows(outbox_path):
    ob = Outbox(outbox_path, "test")
    id1 = ob.stash("a")
    id2 = ob.stash("b")
    id3 = ob.stash("c")
    assert ob.pending_count() == 3
    assert ob.ack([id1, id3]) == 2
    assert ob.pending_count() == 1
    remaining = ob.peek(10)
    assert remaining[0][0] == id2


def test_outbox_mark_attempt_increments_counter(outbox_path):
    ob = Outbox(outbox_path, "test")
    ob.stash("a", "first error")
    pending = ob.peek(10)
    ob.mark_attempt([pending[0][0]], "retry failed")
    conn = ob._ensure()
    cur = conn.execute("SELECT attempts, last_error FROM outbox WHERE id = ?", (pending[0][0],))
    attempts, err = cur.fetchone()
    assert attempts == 1
    assert err == "retry failed"


def test_outbox_is_per_channel(outbox_path):
    """Stash on one channel shouldn't appear in another's peek."""
    a = Outbox(outbox_path, "channel_a")
    b = Outbox(outbox_path, "channel_b")
    a.stash("for-a")
    b.stash("for-b")
    assert a.pending_count() == 1
    assert b.pending_count() == 1
    assert a.peek(10)[0][1] == "for-a"
    assert b.peek(10)[0][1] == "for-b"


class _FakePrimary:
    """A stand-in Sender that can be toggled online/offline."""

    def __init__(self):
        self.sent = []
        self.online = True
        self.is_closed = False

    async def send(self, message):
        if not self.online:
            raise ConnectionError("offline")
        self.sent.append(message)

    def try_send(self, message):
        if not self.online:
            raise ConnectionError("offline")
        self.sent.append(message)

    async def close(self):
        self.is_closed = True

    def __len__(self):
        return 0


def test_durable_sender_success_path_skips_outbox(outbox_path):
    async def scenario():
        primary = _FakePrimary()
        ds = DurableSender(primary, Outbox(outbox_path, "ok"))
        await ds.send({"v": 1})
        await ds.send({"v": 2})
        assert primary.sent == [{"v": 1}, {"v": 2}]
        # Nothing stashed on success
        assert ds._outbox.pending_count() == 0

    asyncio.run(scenario())


def test_durable_sender_stashes_when_primary_down(outbox_path):
    async def scenario():
        primary = _FakePrimary()
        ds = DurableSender(primary, Outbox(outbox_path, "down"), replay_interval=0.05)
        primary.online = False

        await ds.send({"lost": 1})
        await ds.send({"lost": 2})
        # Both stashed locally
        assert ds._outbox.pending_count() == 2
        assert primary.sent == []

        # Primary recovers — replay drains the outbox.  The replay
        # loop sleeps ``backoff.delay(attempt)`` between iterations
        # which can exceed a fixed 0.2 s wait under suite load, so
        # poll up to 5 s for the outbox to drain instead of a single
        # hardcoded sleep.
        primary.online = True
        for _ in range(50):
            await asyncio.sleep(0.1)
            if ds._outbox.pending_count() == 0:
                break
        assert primary.sent == [{"lost": 1}, {"lost": 2}]
        assert ds._outbox.pending_count() == 0

    asyncio.run(scenario())


def test_durable_sender_try_send_stashes_on_failure(outbox_path):
    primary = _FakePrimary()
    primary.online = False
    ds = DurableSender(primary, Outbox(outbox_path, "trysync"))
    ds.try_send("msg-a")
    ds.try_send("msg-b")
    assert ds._outbox.pending_count() == 2
    assert primary.sent == []
