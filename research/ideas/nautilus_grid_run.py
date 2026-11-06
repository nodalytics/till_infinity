"""Run the pre-registered grid. The grid is `nautilus_grid_rule.json`.

Two passes, because the duty-cycle twin cannot be specified before the gate it
twins has been measured. Pass one runs `base`, `floor`, `volsize` and `gate` on
all three arms; pass two runs `twin` at exactly the keep rate the matching
`gate` cell turned out to have, on the traded arm. Any rule that trades less
improves the headline on a net-negative book, so the twin is the only
comparison that carries information.

Cells are run in a process pool, one engine each, and the pool is forked so
`nautilus_grid` - imported here as a top-level module because `research/` is
not a package - is already in every worker's `sys.modules`.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

RULE = Path(__file__).with_name("nautilus_grid_rule.json")


def cells(grid: dict, arms: tuple[str, ...]) -> list[tuple]:
    """Every pass-one cell, as the tuple `run_cell` takes."""
    out = []
    seed = int(grid["seed"])
    for arm in arms:
        for instrument in grid["arms"][arm]:
            for rule, params in grid["rules"].items():
                for param in params:
                    for mm, spec in grid["money"].items():
                        if mm == "twin":
                            continue
                        name = f"{arm}|{instrument}|{rule}|{param}|{mm}".replace("/", "")
                        out.append(
                            (
                                instrument,
                                rule,
                                int(param),
                                mm,
                                str(Path(grid["out"]).expanduser() / f"{name}.json"),
                                1.0,
                                seed,
                                float(spec.get("reward_floor", 0.0)),
                            )
                        )
    return out


def twins(grid: dict, done: list[dict]) -> list[tuple]:
    """One twin per `gate` cell on the traded arm, at that cell's own keep rate.

    The keep rate is `signals kept / signals seen`, read off the gate cell's
    own counters rather than assumed from the rule - a median split on ATR does
    not keep half the *signals*, because signals are not uniform in the
    volatility they arrive at.
    """
    out = []
    seed = int(grid["seed"])
    for row in done:
        if row.get("mm") != "gate" or "real|" not in Path(row["out"]).name:
            continue
        counts = row.get("counts") or {}
        seen = counts.get("signals", 0)
        if not seen:
            continue
        keep = (seen - counts.get("gated", 0)) / seen
        name = Path(row["out"]).name.replace("|gate.json", "|twin.json")
        out.append(
            (
                row["instrument_id"],
                row["rule"],
                int(row["param"]),
                "twin",
                str(Path(row["out"]).parent / name),
                keep,
                seed,
                0.0,
            )
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=int(os.environ.get("GRID_WORKERS", 16)))
    parser.add_argument("--arms", default="real,walk,synth")
    parser.add_argument("--limit", type=int, default=0, help="first N cells, for timing")
    parser.add_argument("--pass-two", action="store_true", help="twins only, from pass one")
    args = parser.parse_args()

    grid = json.loads(RULE.read_text())
    os.environ.setdefault("CORPUS_DIR", str(Path(grid["catalogue"]).expanduser()))
    os.environ.setdefault("BACKTEST_BALANCE", str(grid["balance"]))
    Path(grid["out"]).expanduser().mkdir(parents=True, exist_ok=True)
    sink = Path(grid["cells"]).expanduser()
    sink.parent.mkdir(parents=True, exist_ok=True)

    import multiprocessing as mp

    from nautilus_grid import run_cell
    from till_infinity.node.backtest import described

    arms = tuple(a for a in args.arms.split(",") if a)
    if args.pass_two:
        done = [json.loads(line) for line in sink.read_text().splitlines() if line.strip()]
        work = twins(grid, done)
        mode = "a"
    else:
        work = cells(grid, arms)
        mode = "w"
    if args.limit:
        work = work[: args.limit]

    print(f"venue: {described()}", file=sys.stderr)
    print(f"catalogue: {os.environ['CORPUS_DIR']}", file=sys.stderr)
    print(f"{len(work)} runs on {args.workers} workers", file=sys.stderr)

    context = mp.get_context("fork")
    done_n = 0
    with sink.open(mode) as handle, context.Pool(args.workers) as pool:
        for row in pool.imap_unordered(run_cell, work, chunksize=1):
            handle.write(json.dumps(row) + "\n")
            handle.flush()
            done_n += 1
            counts = row.get("counts") or {}
            print(
                f"[{done_n}/{len(work)}] {Path(row['out']).stem:52s} "
                f"bars {counts.get('bars', 0):7d} sig {counts.get('signals', 0):6d} "
                f"gate {counts.get('gated', 0):6d} unsized {counts.get('unsized', 0):5d} "
                f"trades {row.get('trades', 0):6d} {row.get('seconds', 0):6.1f}s "
                f"{row.get('error', '')}",
                file=sys.stderr,
                flush=True,
            )
    print(f"wrote {sink}")


if __name__ == "__main__":
    main()
