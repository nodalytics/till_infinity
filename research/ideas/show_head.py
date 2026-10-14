"""Print the head of another run's log, since `lab.sh log` only tails 60 lines."""

from __future__ import annotations

import os
from pathlib import Path

WHICH = os.environ.get("WHICH", "gold_cost")
LINES = int(os.environ.get("LINES", "40"))


def main() -> None:
    path = Path.home() / "till_infinity" / "logs" / f"{WHICH}.log"
    if not path.exists():
        print(f"no log at {path}")
        return
    for line in path.read_text().splitlines()[:LINES]:
        print(line)


if __name__ == "__main__":
    main()
