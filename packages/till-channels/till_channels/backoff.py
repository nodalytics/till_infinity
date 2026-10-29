"""Retry / backoff policies for channel operations.

Used by DurableSender (and anywhere else that retries) to compute
delays between retry attempts. Supports:

  - Fixed delay
  - Exponential backoff with cap
  - Exponential backoff with jitter

Usage:
    policy = ExponentialBackoff(initial=0.5, multiplier=2, max_delay=30, jitter=0.1)
    for attempt in range(10):
        try:
            ...
            break
        except Exception:
            await asyncio.sleep(policy.delay(attempt))
"""

from __future__ import annotations

import random
from typing import Protocol, runtime_checkable


@runtime_checkable
class BackoffPolicy(Protocol):
    def delay(self, attempt: int) -> float: ...


class FixedBackoff:
    def __init__(self, seconds: float = 1.0) -> None:
        self.seconds = seconds

    def delay(self, attempt: int) -> float:
        return self.seconds


class ExponentialBackoff:
    """`initial * multiplier^attempt`, capped at max_delay, with optional jitter."""

    def __init__(
        self,
        initial: float = 0.5,
        multiplier: float = 2.0,
        max_delay: float = 30.0,
        jitter: float = 0.0,  # fraction, 0.1 → ±10%
    ) -> None:
        self.initial = initial
        self.multiplier = multiplier
        self.max_delay = max_delay
        self.jitter = jitter

    def delay(self, attempt: int) -> float:
        base = min(self.initial * (self.multiplier ** max(0, attempt)), self.max_delay)
        if self.jitter > 0:
            span = base * self.jitter
            return max(0.0, base + random.uniform(-span, span))
        return base


DEFAULT_BACKOFF: BackoffPolicy = ExponentialBackoff(
    initial=0.5,
    multiplier=2.0,
    max_delay=30.0,
    jitter=0.1,
)
