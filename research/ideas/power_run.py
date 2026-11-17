"""Power for the one null that needs it: does the leg geometry add anything.

`full - base` on the pull question is the claim, and a null on it is only worth
reporting with a size attached. The planted effect is drawn over the columns
**`base` cannot see** - the first version drew it over the whole `full` set,
which includes every `base` column, so both arms rose together and the
difference stayed flat at every strength.

    ./.secrets/lab.sh run research/ideas/power_run.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import persistence  # noqa: E402

CATALOGUE = os.environ.get("CATALOGUE", "data/mt5-deep")


def main() -> None:
    traded = ["--catalogue", CATALOGUE, "--unit", "5m", "--years", "8"]
    for target, frame in (("pull", "1h"), ("continuity", "15m")):
        for plant in ("0.0", "0.02", "0.05", "0.10", "0.20"):
            print("\n" + "=" * 78)
            print(f"@@@ {target} {frame}, planted on the spare columns at {plant}")
            print("=" * 78, flush=True)
            sys.argv = [
                "persistence.py", "--target", target, "--frame", frame,
                "--arms", "real", "--plant", plant, *traded,
            ]
            try:
                persistence.main()
            except Exception:
                traceback.print_exc()
            sys.stdout.flush()


if __name__ == "__main__":
    main()
