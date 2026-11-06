"""The health probe: read what the node wrote, and say whether to believe it.

**Separate from `status.py` because importing it was the most expensive thing
on the box.** `status.py` holds the `Heartbeat` Actor that *writes* the status,
so reading the file meant importing a Nautilus `Actor` -
`nautilus_trader.common.actor` costs 1.60s of import time, with
`nautilus_trader.common.component` at 1.34s and pandas at 0.65s inside it.
Measured on tis 2026-11-06, the `HEALTHCHECK` took 2.0s of wall time and about
**1.2 cores every 60 seconds**: roughly 4% of the machine, continuously, and
the only real CPU spike on it. For comparison the desk it was watching peaked
at 0.238 cores folding 43 feeds. The spike was briefly mistaken for the bar
fold and three live desks were clipped for it.

So this module imports the standard library and nothing else, and the
`HEALTHCHECK` runs it. `status.py` imports these names back, so anything that
already called `status.read` or `status.healthy` is unaffected - the move is
where the code lives, not what may call it.

Everything below is unchanged from `status.py`, including the reasoning: the
whole argument for a file rather than an in-process answer is written there.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

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
        prog="python -m till_infinity.node.probe",
        description="Is the node up, fresh, and trading something?",
    )
    parser.add_argument("--path", default=None, help="status file, if not the default")
    args = parser.parse_args(argv)

    ok, reason = healthy(args.path)
    print(reason)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
