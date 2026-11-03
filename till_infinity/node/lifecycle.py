"""Bringing a node up, proving it is up, and taking it down.

`stack.py` did a narrower version: it supervised coroutines in one process,
keyed on `*_ENABLED` flags, and its idea of "up" was that nothing had raised
yet. Nautilus owns the supervision now, so what is left is the part it has no
opinion about - what counts as up, and what a stop does to a book.

**A launch that reports success without checking is the failure this exists to
prevent.** Three deploys on 2026-10-09 were built, tagged, deployed,
health-checked and reported up while running none of the code they claimed;
one of them was then measured as having no effect, which is what code that is
not running looks like. And `lab.sh run` printed "launched" whether or not the
code had synced.

So `up` is a sequence of claims, each with a source, and the one that matters
comes from the venue rather than from us: `judge-the-desk-on-the-broker-not-
the-journal`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

#: How long to wait on a step before saying which one we were waiting for.
#: Not a failure deadline - `desk-handlers-arm-after-backfill` records that
#: `armed=0` straight after a deploy is normal, so arming is waited on rather
#: than failed on.
DEFAULT_DEADLINE = 180.0


class Step(StrEnum):
    """The claims that together mean "up", in the order they can be made."""

    PROCESS = "process alive"
    #: The execution client answered an account query. **The venue's word.**
    VENUE = "venue answered"
    INSTRUMENTS = "instruments loaded"
    #: First bar or quote per subscribed feed.
    DATA = "data flowing"
    #: Reconciliation finished against the broker's positions and orders.
    RECONCILED = "reconciled"
    ARMED = "strategies armed"


class Stop(StrEnum):
    """What a stop does to an open book. Named at stop time, never configured.

    The right answer depends on *why* the node is coming down, so it is not a
    setting: a restart for a code change must not close a book, and a halt
    must not leave one open.
    """

    #: Stop the node; leave positions and resting orders alone. The default,
    #: because a deploy is not a reason to realise a position.
    LEAVE = "leave"
    #: Cancel resting orders, keep positions. For a change to order logic.
    CANCEL = "cancel"
    #: Close everything, then stop. For a halt, and never implicit.
    FLATTEN = "flatten"

    @property
    def trading_state(self) -> str:
        """The Nautilus `TradingState` this implies while winding down.

        Reusing the engine's own mechanism rather than inventing a wind-down:
        `REDUCING` stops anything new from opening while positions close.
        """
        return "REDUCING" if self is not Stop.LEAVE else "ACTIVE"


@dataclass(slots=True)
class Check:
    """One step, its answer, and where the answer came from."""

    step: Step
    #: Returns True when the claim holds. Called repeatedly until it does.
    probe: Callable[[], bool]
    #: Who is being asked. `venue` means the broker; anything else is us.
    source: str = "node"
    satisfied: bool = False
    waited: float = 0.0

    def note(self) -> str:
        mark = "ok" if self.satisfied else f"waiting {self.waited:.0f}s"
        return f"{self.step.value} [{self.source}]: {mark}"


@dataclass(slots=True)
class Report:
    """What happened, in enough detail to act on."""

    checks: list[Check] = field(default_factory=list)
    up: bool = False
    stalled_on: Step | None = None

    def lines(self) -> list[str]:
        return [check.note() for check in self.checks]

    def summary(self) -> str:
        if self.up:
            return "up: " + "; ".join(c.step.value for c in self.checks)
        where = self.stalled_on.value if self.stalled_on else "nothing"
        return f"not up - still waiting on {where}. " + "; ".join(self.lines())


async def wait_until_up(
    checks: list[Check],
    *,
    deadline: float = DEFAULT_DEADLINE,
    interval: float = 1.0,
    now: Callable[[], float] | None = None,
) -> Report:
    """Wait for every claim in order, and say which one did not arrive.

    **In order, and not in parallel.** A node whose data is flowing but whose
    venue never answered is not three-quarters up, it is misleading - and
    checking concurrently would report exactly that.

    **"Failed to start" is not an answer.** The deadline produces the name of
    the step still outstanding, because that is the difference between a
    bridge that is down, a backfill that is slow and a strategy that never
    armed - and they take different actions.
    """
    clock = now or asyncio.get_event_loop().time
    report = Report(checks=checks)
    for check in checks:
        started = clock()
        while True:
            try:
                if check.probe():
                    check.satisfied = True
                    break
            except Exception:
                pass
            check.waited = clock() - started
            if check.waited >= deadline:
                report.stalled_on = check.step
                return report
            await asyncio.sleep(interval)
    report.up = True
    return report


def plan_stop(policy: Stop) -> list[str]:
    """The steps a stop takes, in order, as Nautilus operations.

    Returned rather than executed: the node holds the `Trader` and the clients,
    and a function that both decides and acts cannot be tested without a
    kernel. Every verb here is the engine's own.
    """
    steps: list[str] = []
    if policy is Stop.FLATTEN:
        steps.append("set TradingState.REDUCING")
        steps.append("cancel_all_orders")
        steps.append("close_all_positions")
    elif policy is Stop.CANCEL:
        steps.append("set TradingState.REDUCING")
        steps.append("cancel_all_orders")
    # **Confirmed against the venue before the node is called down.** A stop
    # that leaves a resting order nobody is supervising is worse than no stop,
    # and our own record is not evidence about the broker.
    steps.append("generate_order_status_reports (confirm with the venue)")
    steps.append("node.stop")
    steps.append("node.dispose")
    return steps


def retire_strategy(reason: str) -> list[str]:
    """Taking one strategy off a running node, rather than the whole node.

    The engine has the verbs - `stop_strategy` then `remove_strategy` - and
    `promotion.retire` decides whether the reason is sufficient. This is only
    the order they go in, which matters: removing before stopping leaves the
    strategy's orders unowned.
    """
    return [
        f"promotion.retire(reason={reason})",
        "set TradingState.REDUCING for the strategy's instruments",
        "trader.stop_strategy",
        "generate_order_status_reports (confirm nothing is resting)",
        "trader.remove_strategy",
    ]
