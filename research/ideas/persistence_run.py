"""Every cell of the persistence study, one log.

Split from `persistence.py` so the harness stays a harness and the grid stays
readable. `CATALOGUE` and `SYNTH` are environment variables because the deep
bar catalogue and the broker candle exports live outside the repository and
`computation-runs-in-the-lab` says the run does not live where they do.

    ./.secrets/lab.sh run research/ideas/persistence_run.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import persistence  # noqa: E402

CATALOGUE = os.environ.get("CATALOGUE", "data/mt5-deep")
SYNTH = os.environ.get("SYNTH", "data/broker-deep")

#: Hourly synthetic feeds. `step` is the arm that **must** read nothing: Deriv
#: generates it with a fixed step, so there is no volatility clustering in it
#: and no leg structure beyond what a walk has.
SYNTHETIC = {
    "V75": "volatility_75_index_1h_broker.csv.gz",
    "BOOM1000": "boom_1000_index_1h_broker.csv.gz",
    "CRASH1000": "crash_1000_index_1h_broker.csv.gz",
    "STEP": "step_index_1h_broker.csv.gz",
}

CONTINUITY_FEATURES = "past_worst_run,past_stalls,past_travel,past_efficiency,tr_cv,last_tr,atr_q,atr_ratio"
PULL_FEATURES = (
    "cushion,remaining,approach,approach_efficiency,pivot_strength,reject_wick,"
    "bar_size,close_in_range,past_travel,past_efficiency,tr_cv,atr_q,atr_ratio,range_pos,round_dist"
)


def synthetic_argument() -> str:
    return ",".join(f"{name}={Path(SYNTH) / file}" for name, file in SYNTHETIC.items())


def cells() -> list[tuple[str, list[str]]]:
    traded = ["--catalogue", CATALOGUE, "--unit", "5m", "--years", "8"]
    synth = ["--csv", synthetic_argument(), "--unit", "1h", "--years", "8"]
    out: list[tuple[str, list[str]]] = []

    for frame in ("1h", "15m"):
        out.append(
            (
                f"continuity {frame}, traded",
                ["--target", "continuity", "--frame", frame, "--arms", "real,shuffled", *traded,
                 "--deciles", CONTINUITY_FEATURES],
            )
        )
    out.append(
        (
            "continuity 1h, synthetics",
            ["--target", "continuity", "--frame", "1h", "--arms", "real,shuffled", *synth,
             "--deciles", CONTINUITY_FEATURES],
        )
    )
    # How much stalling is allowed changes the question, so it is swept rather
    # than chosen: `--allowed 0` is "every bar moves" and 3 is "mostly moves".
    for allowed in ("0", "3"):
        out.append(
            (
                f"continuity 15m, allowed {allowed}",
                ["--target", "continuity", "--frame", "15m", "--allowed", allowed, "--arms", "real",
                 *traded],
            )
        )
    for plant in ("0.02", "0.05", "0.10"):
        out.append(
            (
                f"continuity 15m, planted {plant}",
                ["--target", "continuity", "--frame", "15m", "--arms", "real", "--plant", plant, *traded],
            )
        )

    for kind in ("origin", "no_approach", "no_pivot"):
        out.append(
            (
                f"pull 1h, traded, {kind}",
                ["--target", "pull", "--frame", "1h", "--kind", kind, "--arms", "real,shuffled", *traded,
                 "--deciles", PULL_FEATURES],
            )
        )
    out.append(
        (
            "pull 1h, traded, origin, de-overlapped",
            ["--target", "pull", "--frame", "1h", "--arms", "real", "--thin", *traded],
        )
    )
    for kind in ("origin", "no_pivot"):
        out.append(
            (
                f"pull 1h, synthetics, {kind}",
                ["--target", "pull", "--frame", "1h", "--kind", kind, "--arms", "real,shuffled", *synth,
                 "--deciles", PULL_FEATURES],
            )
        )
    for plant in ("0.02", "0.05", "0.10"):
        out.append(
            (
                f"pull 1h, traded, planted {plant}",
                ["--target", "pull", "--frame", "1h", "--arms", "real", "--plant", plant, *traded],
            )
        )
    # The operator's clock is 15m as well as hourly, and a shorter clock makes
    # the same spread 19x dearer in R - so the hourly answer does not carry to
    # it and it is a cell, not a footnote.
    out.append(
        (
            "pull 15m, traded, origin",
            ["--target", "pull", "--frame", "15m", "--arms", "real,shuffled", *traded],
        )
    )
    return out


def main() -> None:
    for title, argv in cells():
        print("\n" + "=" * 78)
        print(f"### {title}")
        print("=" * 78, flush=True)
        sys.argv = ["persistence.py", *argv]
        try:
            persistence.main()
        except Exception:
            traceback.print_exc()
        sys.stdout.flush()


if __name__ == "__main__":
    main()
