"""Print one window of a lab log, because `lab.sh log` only tails sixty lines.

`./.secrets/lab.sh log <name>` runs `tail -60`, which is right for watching a
run and useless for reading one that printed four hundred lines. This prints
lines `FROM..TO` of another run's log into *its own* log, where `lab.sh log
calibtail` can read them sixty at a time:

    ./.secrets/lab.sh run research/harness/calibtail.py NAME=calibfpr FROM=1 TO=55
    ./.secrets/lab.sh log calibtail

Nothing here computes anything. It exists so that a result measured on the lab
can be read off the lab without a second channel to it.
"""

from __future__ import annotations

import os

NAME = os.environ.get("NAME", "calibfpr")
FROM = int(os.environ.get("FROM", "1"))
TO = int(os.environ.get("TO", "55"))
LOGS = os.environ.get("LOGS", os.path.expanduser("~/till_infinity/logs"))


def main() -> None:
    path = os.path.join(LOGS, f"{NAME}.log")
    with open(path) as fh:
        lines = fh.read().splitlines()
    for line in lines[FROM - 1:TO]:
        print(line)
    print(f"[{NAME}.log lines {FROM}-{min(TO, len(lines))} of {len(lines)}]")


if __name__ == "__main__":
    main()
