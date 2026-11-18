"""Wick against body against close, for every turn-point definition.

The operator asked which one the turn points use, 2026-11-17. They used wicks
everywhere, because the supplied pull-origin definition says "the candle's
low"; the operator's own Bjorgum preset says `source of pivots = high/low
body`. Two parts of the desk disagreed, so the answer is a sweep.

A body pivot is a different object and not a tidier version of the same one: at
a 1.5 ATR zigzag on two years of hourly EURUSD it gives **1,449 turns against
5,445**, a gap of 8.6 bars against 3.4, a clearance rate of 0.4720 against
0.4150 - and an arrival coefficient of variation of **0.983 against 1.236**,
which is the difference between memoryless and clustered.

    ./.secrets/lab.sh run research/ideas/leg_source_run.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import leg_sequence  # noqa: E402
from persistence_run import synthetic_argument  # noqa: E402

CATALOGUE = os.environ.get("CATALOGUE", "data/mt5-deep")


def cells() -> list[tuple[str, list[str]]]:
    traded = ["--catalogue", CATALOGUE, "--unit", "5m", "--years", "8"]
    synth = ["--csv", synthetic_argument(), "--unit", "1h", "--years", "8"]
    out: list[tuple[str, list[str]]] = []
    for source in ("wick", "body", "close"):
        out.append(
            (
                f"source {source}, 1h, traded",
                ["--frame", "1h", "--source", source, "--kinds", "pivot,zigzag,fractal",
                 "--arms", "real,shuffled", *traded],
            )
        )
    for source in ("wick", "body"):
        out.append(
            (
                f"source {source}, 1h, synthetics",
                ["--frame", "1h", "--source", source, "--kinds", "pivot,zigzag",
                 "--arms", "real,shuffled", *synth],
            )
        )
        out.append(
            (
                f"source {source}, 15m, traded",
                ["--frame", "15m", "--source", source, "--kinds", "pivot,zigzag",
                 "--arms", "real,shuffled", *traded],
            )
        )
    # The origin detector reads its own low by definition, so what the sweep
    # changes for it is the leg and the barrier, not the turn.
    for source in ("wick", "body"):
        out.append(
            (
                f"origin turns with a {source} leg, 1h",
                ["--frame", "1h", "--source", source, "--kinds", "origin",
                 "--arms", "real,shuffled", *traded],
            )
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
