"""How wide the pipeline may run here, asked of the machine.

A discovery sweep is a burst of exactly the work a live node needs cores for,
and this desk has the outage on record: a research job silently starved the
service on tis, which has two. So the width of a sweep is not a constant in a
config file - it is derived from what this box has and what it is already
doing, and on the box that trades the answer is zero.

**Three ways of asking the machine give three different answers, and only one
is right inside a container.**

`os.cpu_count()` reports the host's cores even when the process is pinned to
two of them, so `sched_getaffinity` is used instead - it respects a cpuset and
a `--cpus` limit. `/proc/meminfo` reports the *host's* memory inside a
container, so the cgroup limit is read first; `deployed-compose-diverges-from-
the-file` is the neighbouring lesson, where the lab bridge ran on 4GiB while
the compose file said 1G. Ask the daemon, not the file.

**Headroom is the point, not a safety margin.** A box with four cores does not
get four workers: the live node, the bridge and the terminal are all doing
something, and the failure mode of taking the last core is not a slow backtest
but a desk that stops answering.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path

#: Hosts that run the live desk. A sweep here gets zero workers.
TRADING_HOSTS = ("tis",)

#: Cores left for everything that is not this sweep.
RESERVED_CORES = 1

#: Memory a single backtest engine wants, before data. Measured loosely and
#: deliberately generous: a run that is killed by the OOM reaper halfway
#: through tells you nothing, and the cost of over-reserving is a slower
#: sweep rather than a lost one.
ENGINE_MEMORY_MB = 512

#: Fraction of available memory a sweep may use at once.
MEMORY_SHARE = 0.6


def cores() -> int:
    """Cores this process may actually use.

    `sched_getaffinity` rather than `cpu_count`, because a container limited to
    two cores still sees the host's count - and sizing a sweep off a number
    four times too large is how a two-core box gets eight workers.
    """
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):  # pragma: no cover - not Linux
        return max(1, os.cpu_count() or 1)


def _cgroup_limit() -> int | None:
    """The container's memory ceiling, if there is one."""
    for path, unlimited in (
        (Path("/sys/fs/cgroup/memory.max"), "max"),  # cgroup v2
        (Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"), None),  # v1
    ):
        try:
            raw = path.read_text().strip()
        except OSError:
            continue
        if unlimited is not None and raw == unlimited:
            return None
        try:
            value = int(raw)
        except ValueError:
            continue
        # cgroup v1 reports a sentinel near 2^63 for "no limit".
        if value <= 0 or value > (1 << 62):
            return None
        return value
    return None


def memory_bytes() -> int:
    """Memory available to this process.

    The cgroup limit first, because inside a container `/proc/meminfo`
    describes the host - a 1GiB container on a 64GiB box would otherwise size
    a sweep for 64GiB and be killed for it.
    """
    limit = _cgroup_limit()
    if limit is not None:
        return limit
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):  # pragma: no cover
        pass
    return 2 * 1024**3  # a conservative floor rather than a guess upward


def on_trading_host() -> bool:
    return any(h in socket.gethostname() for h in TRADING_HOSTS)


@dataclass(frozen=True, slots=True)
class Budget:
    """What this machine will allow, and why.

    `why` is carried rather than logged because the number alone is not
    actionable: "one worker" reads as a bug on a sixteen-core box until it says
    it found one core available.
    """

    workers: int
    #: Trials that may be in flight at once. Never more than `workers`.
    concurrent: int
    #: Windows a sweep may try. Narrowed on a small box, because a window
    #: sweep multiplies the trial count and the runtime together.
    windows: int
    cores_seen: int
    memory_mb: int
    why: str

    @property
    def may_run(self) -> bool:
        return self.workers > 0


def measure(*, windows_wanted: int = 12, allow_here: bool | None = None) -> Budget:
    """Size a sweep for this machine.

    `allow_here` overrides the trading-host refusal, for the case where
    somebody means it. It defaults to the `ALLOW_BACKTEST_HERE` environment
    variable, so the override is visible in a deployment rather than in an
    argument somebody passed once.
    """
    seen = cores()
    memory_mb = memory_bytes() // (1024 * 1024)
    override = bool(os.environ.get("ALLOW_BACKTEST_HERE")) if allow_here is None else allow_here

    if on_trading_host() and not override:
        return Budget(
            workers=0,
            concurrent=0,
            windows=0,
            cores_seen=seen,
            memory_mb=memory_mb,
            why=(
                f"{socket.gethostname()} runs the live desk. A sweep is a burst of "
                f"exactly the work the node needs cores for, and a research job has "
                f"already starved it on this box. Set ALLOW_BACKTEST_HERE=1 to mean it."
            ),
        )

    by_cores = max(0, seen - RESERVED_CORES)
    by_memory = int((memory_mb * MEMORY_SHARE) // ENGINE_MEMORY_MB)
    workers = max(1, min(by_cores, by_memory)) if min(by_cores, by_memory) > 0 else 1

    # A narrow box runs fewer windows, because a sweep multiplies windows by
    # candidates in both trials and runtime - and the trial count is what the
    # deflated Sharpe charges for.
    windows = max(1, min(windows_wanted, workers * 3))

    binding = "cores" if by_cores <= by_memory else "memory"
    return Budget(
        workers=workers,
        concurrent=workers,
        windows=windows,
        cores_seen=seen,
        memory_mb=memory_mb,
        why=(
            f"{seen} core(s) and {memory_mb}MB available: {by_cores} by cores "
            f"(reserving {RESERVED_CORES}), {by_memory} by memory at "
            f"{ENGINE_MEMORY_MB}MB an engine - {binding} is binding"
        ),
    )


def chunks(items: list, budget: Budget) -> list[list]:
    """Split work into batches this machine can hold at once.

    Returned rather than executed: `BacktestNode` takes a list of configs and
    runs them, so the batching belongs to whoever calls it. A function that
    both sizes and runs cannot be tested without a kernel.
    """
    if not budget.may_run:
        return []
    width = max(1, budget.concurrent)
    return [items[i : i + width] for i in range(0, len(items), width)]


def describe() -> str:
    """One line for a log or a CLI, naming the limit rather than the number."""
    budget = measure()
    if not budget.may_run:
        return f"sweeps refused here: {budget.why}"
    return f"{budget.workers} worker(s), {budget.windows} window(s) at a time; {budget.why}"
