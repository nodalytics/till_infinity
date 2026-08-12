"""Tests for the in-memory channel backend."""
import asyncio

import pytest

from till_infinity.channels import (
    ChannelClosed,
    ChannelEmpty,
    ChannelFull,
    bounded,
    unbounded,
)


def run(coro):
    return asyncio.run(coro)


def test_bounded_send_recv_roundtrip():
    async def scenario():
        tx, rx = bounded(4)
        await tx.send({"n": 1})
        await tx.send({"n": 2})
        assert await rx.recv() == {"n": 1}
        assert await rx.recv() == {"n": 2}
    run(scenario())


def test_unbounded_accepts_many():
    async def scenario():
        tx, rx = unbounded()
        for i in range(100):
            await tx.send(i)
        assert len(tx) == 100
        for i in range(100):
            assert await rx.recv() == i
    run(scenario())


def test_bounded_capacity_zero_rejected():
    with pytest.raises(ValueError):
        bounded(0)


def test_try_send_raises_when_full():
    async def scenario():
        tx, _rx = bounded(2)
        tx.try_send("a")
        tx.try_send("b")
        with pytest.raises(ChannelFull):
            tx.try_send("c")
    run(scenario())


def test_try_recv_raises_when_empty():
    async def scenario():
        _tx, rx = bounded(4)
        with pytest.raises(ChannelEmpty):
            rx.try_recv()
    run(scenario())


def test_close_prevents_further_sends():
    async def scenario():
        tx, _rx = bounded(4)
        await tx.close()
        with pytest.raises(ChannelClosed):
            await tx.send("x")
        with pytest.raises(ChannelClosed):
            tx.try_send("x")
    run(scenario())


def test_close_drains_remaining_then_raises():
    async def scenario():
        tx, rx = bounded(4)
        await tx.send("a")
        await tx.send("b")
        await tx.close()
        assert await rx.recv() == "a"
        assert await rx.recv() == "b"
        with pytest.raises(ChannelClosed):
            await rx.recv()
    run(scenario())


def test_mpmc_multiple_producers():
    async def scenario():
        # Unbounded so producers don't block the gather waiting for recv.
        tx, rx = unbounded()

        async def producer(n):
            for i in range(10):
                await tx.send((n, i))

        await asyncio.gather(*(producer(p) for p in range(4)))
        received = []
        while len(received) < 40:
            received.append(await rx.recv())
        assert len(received) == 40
    run(scenario())


def test_mpmc_multiple_consumers():
    async def scenario():
        tx, rx = unbounded()
        for i in range(20):
            await tx.send(i)
        await tx.close()

        results = []
        async def consumer():
            while True:
                try:
                    results.append(await rx.recv())
                except ChannelClosed:
                    return

        await asyncio.gather(consumer(), consumer(), consumer())
        # All 20 messages consumed exactly once across consumers
        assert sorted(results) == list(range(20))
    run(scenario())


def test_receiver_async_iteration():
    async def scenario():
        tx, rx = bounded(8)
        for i in range(5):
            await tx.send(i)
        await tx.close()

        collected = []
        async for msg in rx:
            collected.append(msg)
        assert collected == [0, 1, 2, 3, 4]
    run(scenario())


def test_len_tracks_queue_depth():
    async def scenario():
        tx, rx = bounded(4)
        assert len(tx) == 0
        await tx.send("a")
        assert len(tx) == 1
        await tx.send("b")
        assert len(rx) == 2
        await rx.recv()
        assert len(rx) == 1
    run(scenario())
