"""The penetration shortfall, matched on distance **and** the volatility state.

The distance-only comparison on 8 years of five markets at 1h said a real
market clears its previous turn point **less** often than a day-shuffled one:
`-0.0152` on swing pivots, 90% `[-0.0247, -0.0050]`, and `-0.0114` on an ATR
zigzag, `[-0.0154, -0.0078]`. That reproduces
[`turning-points.md`](../docs/turning-points.md)'s "real trends make the next
extreme less often than walks", distance-matched for the first time.

**And it has a competing explanation that is not a barrier.** The distance to
the prior turn point is in ATR of the turn's own bar. Real ATR mean-reverts, a
shuffled series' does not, so a turn formed in a volatility burst is followed by
a quieter leg which covers less of the ATR it was measured against. The tell is
already in the distance-only table: the **shuffled** arm's legs travel further
in ATR. This run crosses the distance bins with the volatility quantile at the
turn, which is the cut that separates the two readings.

    ./.secrets/lab.sh run research/ideas/leg_matched_run.py
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
    for frame in ("1h", "15m"):
        for source in ("wick", "body"):
            out.append(
                (
                    f"{frame}, {source}, traded",
                    ["--frame", frame, "--source", source, "--kinds", "pivot,zigzag,fractal,origin",
                     "--arms", "real,shuffled", *traded],
                )
            )
    out.append(
        (
            "1h, wick, synthetics",
            ["--frame", "1h", "--source", "wick", "--kinds", "pivot,zigzag,fractal",
             "--arms", "real,shuffled", *synth],
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
