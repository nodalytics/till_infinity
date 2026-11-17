"""Every cell of the turn-point sequence study, one log.

    ./.secrets/lab.sh run research/ideas/leg_sequence_run.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import leg_sequence  # noqa: E402
from persistence_run import SYNTHETIC, synthetic_argument  # noqa: E402

CATALOGUE = os.environ.get("CATALOGUE", "data/mt5-deep")
KINDS = "origin,pivot,zigzag,fractal"


def cells() -> list[tuple[str, list[str]]]:
    traded = ["--catalogue", CATALOGUE, "--unit", "5m", "--years", "8"]
    synth = ["--csv", synthetic_argument(), "--unit", "1h", "--years", "8"]
    out = [
        (
            f"turn points {frame}, traded",
            ["--frame", frame, "--kinds", KINDS, "--arms", "real,shuffled", *traded],
        )
        for frame in ("1h", "15m")
    ]
    out.append(
        (
            f"turn points 1h, synthetics ({', '.join(SYNTHETIC)})",
            ["--frame", "1h", "--kinds", KINDS, "--arms", "real,shuffled", *synth],
        )
    )
    # The zigzag threshold is the one free parameter that changes what a leg
    # *is*, so it is swept rather than chosen: 1.0 ATR gives many small legs
    # and 3.0 gives few large ones, and a rate that only holds at one of them
    # is a property of the setting.
    out.extend(
        (
            f"turn points 1h, zigzag reversal {reversal}",
            ["--frame", "1h", "--kinds", "zigzag", "--reversal", reversal, "--arms", "real,shuffled",
             *traded],
        )
        for reversal in ("1.0", "2.0", "3.0")
    )
    return out


def main() -> None:
    for title, argv in cells():
        print("\n" + "=" * 78)
        print(f"@@@ {title}")
        print("=" * 78, flush=True)
        sys.argv = ["leg_sequence.py", *argv]
        try:
            leg_sequence.main()
        except Exception:
            traceback.print_exc()
        sys.stdout.flush()


if __name__ == "__main__":
    main()
