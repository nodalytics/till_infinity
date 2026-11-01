"""What the node writes down about itself, so a probe reads the venue's word.

## Why a file at all

`Dockerfile`'s `HEALTHCHECK` runs `till-infinity health`, and that command had
nothing to read. The history in `lifecycle.py` says why it matters: three
deploys on 2026-10-09 were built, tagged, deployed, health-checked and
reported up **while running none of the code they claimed**, because every
check read our own side of the wire. One of them was then measured as having
no effect, which is what code that is not running looks like.

So a probe that answers from inside the process is worthless - it proves a
process is alive, which Docker already knew. What it has to read is the claim
`lifecycle.wait_until_up` produced, including which step it stalled on, and it
has to be able to tell a *stale* claim from a current one. Hence a file: the
node writes what it has established and when, and `health` refuses anything
older than `STALE_AFTER`.

## Why an Actor writes it

Because the node's clock is the only thing that knows the node is still
running. A thread would keep writing a cheerful file after the kernel had
stopped dispatching, which is the failure this module exists to prevent
wearing a different hat - and `Actor` gets `clock.set_timer` for free, so the
heartbeat stops exactly when the component does.

## What "healthy" means here

Up, fresh, **and trading something**. A node with no strategies connects,
reconciles, reports up and trades nothing, which is the shape `live.build`
already refuses at construction - this is the same refusal where a monitoring
system can see it. Armed is reported and **not** required: an unarmed node is
a deliberate state (`TRADING_LIVE` unset puts the risk engine in `HALTED`),
and a probe that failed on it would make a dry run impossible.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig

#: Where the node writes it. `/app/.data` is the image's volume, so the file
#: survives a restart and a probe can tell "not yet up" from "up two minutes
#: ago and now gone".
DEFAULT_PATH = Path(os.environ.get("TILL_STATUS_PATH") or "/app/.data/status.json")

#: Seconds before a written status stops counting as evidence.
#:
#: Three heartbeats. The `HEALTHCHECK` interval is 60s with 3 retries, so a
#: node that has genuinely stopped writing fails on the third probe rather
#: than the first - a single missed write is a loaded box, not an outage.
STALE_AFTER = 180.0

#: How often the node refreshes it.
HEARTBEAT = 30.0


class HeartbeatConfig(ActorConfig, frozen=True):
    """Where to write, and how often.

    Frozen `ActorConfig` like every other actor here, so it can be carried as
    an `ImportableActorConfig` - a `TradingNodeConfig` holds importable
    configs rather than instances, and an actor that can only be built by hand
    cannot go in one.
    """

    path: str = str(DEFAULT_PATH)
    seconds: float = HEARTBEAT


class Heartbeat(Actor):
    """Writes the node's own status on the node's own clock."""

    def __init__(self, config: HeartbeatConfig | None = None) -> None:
        config = config or HeartbeatConfig()
        super().__init__(config)
        self._cfg = config
        self._path = Path(config.path)
        self._wrote = 0
        self._failed = 0

    def on_start(self) -> None:
        # Written once immediately, so a probe in the start period sees
        # "starting" rather than nothing - the difference between a node that
        # is warming up and one that never began.
        self._write()
        self.clock.set_timer(
            name="till-status",
            interval=_interval(self._cfg.seconds),
            callback=lambda _event: self._write(),
        )

    def on_stop(self) -> None:
        # A last write on the way down, so the file says stopped rather than
        # going stale and reading as a crash. A clean stop and a kill are
        # different events and a deploy wants to tell them apart.
        self._write(running=False)

    def _write(self, running: bool = True) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self.reading(running=running), indent=2))
            self._wrote += 1
        except OSError as exc:
            # Counted and said once per failure, never raised: a node must not
            # come down because it could not describe itself.
            self._failed += 1
            self.log.warning(f"status: could not write {self._path}: {exc}")

    def reading(self, running: bool = True) -> dict[str, Any]:
        """The claims, each with its source.

        `strategies` and `actors` come from the trader, `venue` from whether
        an execution client reports connected - **the venue's word and not
        ours**, which is the whole argument of `lifecycle.py`.
        """
        venue = False
        try:
            clients = self.cache.exec_clients() if hasattr(self.cache, "exec_clients") else []
            venue = any(getattr(client, "is_connected", False) for client in clients)
        except Exception:  # pragma: no cover - cache shape is the framework's
            venue = False
        return {
            "at": time.time(),
            "running": running,
            "trader": str(self.trader_id),
            "venue_connected": venue,
            "strategies": len(self._strategy_ids()),
            "armed": self._armed(),
            "wrote": self._wrote,
            "write_failures": self._failed,
        }

    def _strategy_ids(self) -> list[str]:
        try:
            return [str(found) for found in self.cache.strategy_ids()]
        except Exception:  # pragma: no cover
            return []

    def _armed(self) -> bool:
        """Is the risk engine letting orders through?

        Reported rather than required: `TRADING_LIVE` unset puts the engine in
        `HALTED` deliberately, and a probe that failed on it would make a dry
        run impossible.
        """
        from till_infinity.utils.env import flag

        return flag("TRADING_LIVE")


def read(path: Path | str | None = None) -> dict[str, Any]:
    """The last status the node wrote, or `{}` if there is none to read."""
    found = Path(path or DEFAULT_PATH)
    try:
        body = json.loads(found.read_text())
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def healthy(
    path: Path | str | None = None,
    now: float | None = None,
    stale_after: float = STALE_AFTER,
) -> tuple[bool, str]:
    """Is the node up, fresh and trading something? And the reason if not.

    The reason is the point. "Unhealthy" sends somebody to the logs; "up two
    minutes ago, 0 strategies" tells them which of three different problems
    they have - and `lifecycle.py`'s whole argument is that "failed to start"
    is not an answer.
    """
    found = read(path)
    if not found:
        return False, f"no status at {path or DEFAULT_PATH}: the node has not written one"
    if not found.get("running", False):
        return False, "the node wrote that it was stopping"
    age = (now if now is not None else time.time()) - float(found.get("at") or 0.0)
    if age > stale_after:
        return (
            False,
            f"status is {age:.0f}s old, past {stale_after:.0f}s - the node stopped writing",
        )
    strategies = int(found.get("strategies") or 0)
    if strategies < 1:
        # The recorded failure, caught where a monitoring system can see it: a
        # node with no strategies connects, reconciles and trades nothing.
        return False, "0 strategies: the node is up and trading nothing"
    if not found.get("venue_connected", False):
        return False, "no execution client is connected: the venue has not answered"
    armed = "armed" if found.get("armed") else "unarmed (TRADING_LIVE is not set)"
    return True, f"up, {strategies} strateg{'y' if strategies == 1 else 'ies'}, {armed}"


def main(argv: list[str] | None = None) -> int:
    """The health probe, as a module rather than a console script.

    **Deliberately not a CLI with a `run` command.** `pyproject.toml` records
    the decision and the reason: the 2,852-line original grew around services
    that no longer exist and the replacement was a *second way to run the
    desk*, and `till.env needs a container recreate` is the lesson about two
    ways to change one thing - one of them goes silently stale. So the node is
    started by `python -m till_infinity.node.live` and nothing here duplicates
    that. This module answers a question; it does not start anything.

    The reason goes to stdout because `docker inspect` keeps a probe's output:
    "up two minutes ago, 0 strategies" tells somebody which of three problems
    they have, where "unhealthy" sends them to the logs.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m till_infinity.node.status",
        description="Is the node up, fresh, and trading something?",
    )
    parser.add_argument("--path", default=None, help="status file, if not the default")
    args = parser.parse_args(argv)

    ok, reason = healthy(args.path)
    print(reason)
    return 0 if ok else 1


def _interval(seconds: float):
    """Seconds as the `timedelta` Nautilus's timer wants."""
    from datetime import timedelta

    return timedelta(seconds=max(1.0, float(seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
