"""Print the head of the most recent run's log, since `lab.sh log` only tails 60.

Defaults to the newest log other than its own, because `lab.sh run` executes
remotely and a locally-set environment variable does not follow it there - so a
`WHICH` default is the one thing this cannot be steered by.
"""

from __future__ import annotations

import os
from pathlib import Path

LINES = int(os.environ.get("LINES", "58"))
SKIP = int(os.environ.get("SKIP", "0"))


def main() -> None:
    logs = Path.home() / "till_infinity" / "logs"
    found = [p for p in logs.glob("*.log") if p.stem != "show_head"]
    if not found:
        print(f"no logs in {logs}")
        return
    newest = max(found, key=lambda p: p.stat().st_mtime)
    lines = newest.read_text().splitlines()
    print(f"# {newest.name}, lines {SKIP + 1} to {SKIP + LINES} of {len(lines)}")
    for line in lines[SKIP : SKIP + LINES]:
        print(line)


if __name__ == "__main__":
    main()
