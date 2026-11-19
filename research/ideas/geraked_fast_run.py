"""The 13 EAs at 5m and 15m, over two years, three months and seven days.

    ./.secrets/lab.sh run research/ideas/geraked_fast_run.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geraked_fast  # noqa: E402

CATALOGUE = os.environ.get("CATALOGUE", "data/mt5-deep")


def main() -> None:
    for title, argv in (
        ("5m and 15m, every window, all five markets", ["--frames", "5m,15m", "--windows", "730,90,7"]),
        ("1h for comparison with the frozen study", ["--frames", "1h", "--windows", "730,90"]),
        ("the long sample at 5m, where the study had none", ["--frames", "5m", "--windows", "2920"]),
    ):
        print("\n" + "=" * 78)
        print(f"@@@ {title}")
        print("=" * 78, flush=True)
        sys.argv = ["geraked_fast.py", "--catalogue", CATALOGUE, "--unit", "5m", "--show", "13", *argv]
        try:
            geraked_fast.main()
        except Exception:
            traceback.print_exc()
        sys.stdout.flush()


if __name__ == "__main__":
    main()
