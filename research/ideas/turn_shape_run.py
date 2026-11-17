"""Every cell of the turn-shape study: the profile, PCA and clustering.

    ./.secrets/lab.sh run research/ideas/turn_shape_run.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import turn_shape  # noqa: E402
from persistence_run import synthetic_argument  # noqa: E402

CATALOGUE = os.environ.get("CATALOGUE", "data/mt5-deep")


def cells() -> list[tuple[str, list[str]]]:
    traded = ["--catalogue", CATALOGUE, "--unit", "5m", "--years", "8"]
    synth = ["--csv", synthetic_argument(), "--unit", "1h", "--years", "8"]
    out: list[tuple[str, list[str]]] = [
        (
            "1h, wick, traded, span 24",
            ["--frame", "1h", "--kinds", "pivot,zigzag,fractal,origin", "--arms", "real,shuffled",
             "--clusters", "3,5", *traded],
        ),
        (
            # A day either side at 1h, so bars -24 and +24 are the same hour and
            # the profile's wings are the diurnal cycle rather than the turn.
            # Twelve bars keeps the window inside half a day.
            "1h, wick, traded, span 12",
            ["--frame", "1h", "--span", "12", "--kinds", "pivot,zigzag", "--arms", "real,shuffled",
             "--clusters", "4", *traded],
        ),
        (
            "1h, body, traded, span 24",
            ["--frame", "1h", "--source", "body", "--kinds", "pivot,zigzag", "--arms", "real,shuffled",
             "--clusters", "4", *traded],
        ),
        (
            "15m, wick, traded, span 24",
            ["--frame", "15m", "--kinds", "pivot,zigzag", "--arms", "real,shuffled",
             "--clusters", "4", *traded],
        ),
        (
            "1h, wick, synthetics, span 24",
            ["--frame", "1h", "--kinds", "pivot,zigzag", "--arms", "real,shuffled",
             "--clusters", "4", *synth],
        ),
    ]
    return out


def main() -> None:
    for title, argv in cells():
        print("\n" + "=" * 78)
        print(f"@@@ {title}")
        print("=" * 78, flush=True)
        sys.argv = ["turn_shape.py", *argv]
        try:
            turn_shape.main()
        except Exception:
            traceback.print_exc()
        sys.stdout.flush()


if __name__ == "__main__":
    main()
