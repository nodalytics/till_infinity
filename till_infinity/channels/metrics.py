"""Metrics hooks for observability.

Channels call into a MetricsHook on every send/recv/error so you can
wire up Prometheus, StatsD, or any custom sink without touching the
channel code itself. The default is NoOpMetrics (zero overhead).

Usage:
    from channels.metrics import InMemoryMetrics, set_default_metrics
    metrics = InMemoryMetrics()
    set_default_metrics(metrics)

    # after running...
    print(metrics.counters)   # {'sends:market:raw': 1024, 'errors:...': 3}
"""

from __future__ import annotations

import threading
import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class MetricsHook(Protocol):
    def send(self, channel: str, duration_s: float) -> None: ...
    def recv(self, channel: str, duration_s: float) -> None: ...
    def error(self, channel: str, operation: str, error: str) -> None: ...
    def stash(self, channel: str) -> None: ...
    def drain(self, channel: str, count: int) -> None: ...


class NoOpMetrics:
    """Zero-cost default when metrics aren't configured."""

    def send(self, channel: str, duration_s: float) -> None:
        pass

    def recv(self, channel: str, duration_s: float) -> None:
        pass

    def error(self, channel: str, operation: str, error: str) -> None:
        pass

    def stash(self, channel: str) -> None:
        pass

    def drain(self, channel: str, count: int) -> None:
        pass


class InMemoryMetrics:
    """Simple thread-safe in-memory counter — handy for tests and demos."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.timers: dict[str, list[float]] = {}
        self.errors: list[tuple[str, str, str]] = []
        self._lock = threading.Lock()

    def _bump(self, key: str, n: int = 1) -> None:
        with self._lock:
            self.counters[key] = self.counters.get(key, 0) + n

    def _timer(self, key: str, duration_s: float) -> None:
        with self._lock:
            self.timers.setdefault(key, []).append(duration_s)

    def send(self, channel: str, duration_s: float) -> None:
        self._bump(f"sends:{channel}")
        self._timer(f"send_time:{channel}", duration_s)

    def recv(self, channel: str, duration_s: float) -> None:
        self._bump(f"recvs:{channel}")
        self._timer(f"recv_time:{channel}", duration_s)

    def error(self, channel: str, operation: str, error: str) -> None:
        self._bump(f"errors:{channel}:{operation}")
        with self._lock:
            self.errors.append((channel, operation, error))

    def stash(self, channel: str) -> None:
        self._bump(f"stashed:{channel}")

    def drain(self, channel: str, count: int) -> None:
        self._bump(f"drained:{channel}", count)


_default: MetricsHook = NoOpMetrics()


def set_default_metrics(hook: MetricsHook) -> None:
    """Replace the process-wide metrics sink."""
    global _default
    _default = hook


def get_default_metrics() -> MetricsHook:
    return _default


# ──── context manager for timing operations ────
class timed:
    """`with timed(metrics.send, channel): primary.send(msg)`."""

    def __init__(self, hook_fn, channel: str) -> None:
        self._hook_fn = hook_fn
        self._channel = channel
        self._t0 = 0.0

    def __enter__(self) -> timed:
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._hook_fn(self._channel, time.perf_counter() - self._t0)
