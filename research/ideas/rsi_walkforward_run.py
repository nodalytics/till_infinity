"""The weekly walk-forward over both clocks, both arms and four years.

    ./.secrets/lab.sh run research/ideas/rsi_walkforward_run.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rsi_walkforward  # noqa: E402

CATALOGUE = os.environ.get("CATALOGUE", "data/mt5-deep")


def main() -> None:
    for years, frames in (("4", "15m"), ("2", "5m"), ("8", "15m")):
        print("\n" + "=" * 78)
        print(f"@@@ {years}y, {frames}")
        print("=" * 78, flush=True)
        sys.argv = [
            "rsi_walkforward.py", "--catalogue", CATALOGUE, "--frames", frames,
            "--years", years, "--arms", "real,shuffled", "--top", "1,3,10",
            "--workers", "10",
        ]
        try:
            rsi_walkforward.main()
        except Exception:
            traceback.print_exc()
        sys.stdout.flush()


if __name__ == "__main__":
    main()
