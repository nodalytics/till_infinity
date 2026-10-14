"""Print a slice of a run's log, since `lab.sh log` only tails 60 lines.

`WHICH` and `SKIP` are module constants rather than environment variables
because `lab.sh run` executes remotely and a locally-set variable does not
follow it there - editing the file is what parameterises this.
"""

from __future__ import annotations

from pathlib import Path

WHICH = "origin_zscore"
SKIP = 0
LINES = 58


def main() -> None:
    logs = Path.home() / "till_infinity" / "logs"
    path = logs / f"{WHICH}.log"
    if not path.exists():
        found = [p for p in logs.glob("*.log") if p.stem != "show_head"]
        if not found:
            print(f"no logs in {logs}")
            return
        path = max(found, key=lambda p: p.stat().st_mtime)
    lines = path.read_text().splitlines()
    print(f"# {path.name}, lines {SKIP + 1} to {SKIP + LINES} of {len(lines)}")
    for line in lines[SKIP : SKIP + LINES]:
        print(line)


if __name__ == "__main__":
    main()
