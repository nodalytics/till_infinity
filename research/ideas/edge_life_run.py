"""The decay curve at every window length, with its three control arms.

    ./.secrets/lab.sh run research/ideas/edge_life_run.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_life  # noqa: E402

CATALOGUE = os.environ.get("CATALOGUE", "data/mt5-deep")


def main() -> None:
    cells = [
        ("15m, 4y, hours to days", ["--frame", "15m", "--years", "4", "--windows", "1,4,24,120"]),
        ("5m, 2y, the short end", ["--frame", "5m", "--years", "2", "--windows", "0.5,1,4,24"]),
        ("15m, 8y, the long sample", ["--frame", "15m", "--years", "8", "--windows", "4,24,120"]),
        ("the cost ladder", ["--cost-ladder", "--years", "4"]),
    ]
    for title, argv in cells:
        print("\n" + "=" * 78)
        print(f"@@@ {title}")
        print("=" * 78, flush=True)
        sys.argv = [
            "edge_life.py", "--catalogue", CATALOGUE, "--unit", "5m",
            "--arms", "real,shuffled-scenarios,shuffled-bars,within-volatility", *argv,
        ]
        try:
            edge_life.main()
        except Exception:
            traceback.print_exc()
        sys.stdout.flush()


if __name__ == "__main__":
    main()
