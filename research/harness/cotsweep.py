"""The two things the COT fade's primary cell cannot answer about itself:
whether it sits on a plateau or a spike, and whether carry pays for it.

    ./.secrets/lab.sh run research/harness/cotsweep.py

**Imports the measured code path rather than copying it.** Every function
here comes from `cotfade`, which was just verified to reproduce its own
baseline after the parameters became arguments - so a cell in this grid and
the pre-registered cell are built by the same lines.

## Why the grid is read on the mean and not on a t

A z or t grid manufactures a ridge wherever n is small, and this repository
has already been fooled by one: a threshold sweep faked a peak at exactly the
chosen threshold while the same grid read on the mean was monotone. So this
prints the mean and the count, and the question asked of the grid is a shape
question - is the primary's neighbourhood positive - not a significance one.
The primary cell was declared in advance, so multiplicity does not threaten
the claim; what the grid can still show is that the claim rests on an
accident of three parameters.

## Why carry is bounded rather than reconstructed

Historical swap is not obtainable - the terminal states today's rates and
nothing else - and applying 2026 carry to 2013 would be wrong by the entire
history of rate differentials. But a bound is enough to decide whether the
question matters: if the rule's own sides pay only a small fraction of an R
at *today's* differentials, then carry cannot erase +0.243R even if the
historical differential were several times wider. If it pays a large
fraction, the result is unsafe until the real series is found.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request as request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cotfade as cf  # noqa: E402

GRID_T = [1.0, 1.25, 1.5, 1.75, 2.0]
GRID_C = [2, 4, 8, 13]
GRID_H = [2, 4, 8, 13]
GRID_L = [104, 156, 208]

PRIMARY = (1.5, 4, 4, 156)

BASE = os.environ.get("BRIDGE", "http://localhost:8000") + "/api/v1"

#: Nights of swap in a 28-day hold. Four Wednesdays each carry a triple
#: rollover, so 28 calendar nights bill as 28 + 4 x 2.
NIGHTS = 36


def bridge(path: str) -> object:
    key = (Path.home() / ".mt5key").read_text().strip()
    req = request.Request(BASE + path, headers={"X-API-Key": key})  # noqa: S310
    with request.urlopen(req, timeout=60) as response:  # noqa: S310
        return json.loads(response.read().decode())


def carry_bound(real: dict[str, list[dict]]) -> None:
    """What the rule's own sides pay in swap, at today's rates."""
    print("\n=== carry, at today's rates (a bound, not a history) ===")
    print(f"{'feed':7s} {'mode':>5s} {'swapL':>9s} {'swapS':>9s} {'meanR':>9s} {'n':>5s}")
    total, count = 0.0, 0
    for feed, symbol in cf.PAIRS.items():
        rows = real.get(feed) or []
        try:
            info = bridge(f"/symbols/info/{symbol}")
        except Exception as exc:  # noqa: BLE001
            print(f"{feed:7s} unreachable: {type(exc).__name__}")
            continue
        if not isinstance(info, dict):
            print(f"{feed:7s} no info")
            continue
        mode = int(info.get("swap_mode") or -1)
        swap_long = float(info.get("swap_long") or 0.0)
        swap_short = float(info.get("swap_short") or 0.0)
        point = float(info.get("point") or 0.0)
        if mode != 1 or point <= 0.0:
            # Mode 1 is swap stated in points. Any other mode is a different
            # unit and converting it on a guess is the error this repository
            # has already paid for on the spread column.
            print(f"{feed:7s} {mode:5d} {swap_long:9.3f} {swap_short:9.3f}   mode not points")
            continue
        per_night = {1.0: swap_long, -1.0: swap_short}
        carried = [
            (per_night[row["side"]] * point * NIGHTS) / row["risk_px"]
            for row in rows
            if row["risk_px"] > 0.0
        ]
        mean = float(np.mean(carried)) if carried else float("nan")
        print(
            f"{feed:7s} {mode:5d} {swap_long:9.3f} {swap_short:9.3f} {mean:9.4f} {len(carried):5d}"
        )
        if carried:
            total += mean * len(carried)
            count += len(carried)
    if count:
        print(f"\nswap over the rule's own sides: {total / count:+.4f} R per trade")
        print("positive is a credit; negative is what the gross figure overstates by")


def main() -> int:
    print("loading")
    bars = {feed: cf.load_bars(symbol) for feed, symbol in cf.PAIRS.items()}
    risk = {feed: 2.0 * cf.atr(bars[feed]) for feed in cf.PAIRS}
    drift: dict[tuple[str, int], float] = {}
    for feed in cf.PAIRS:
        for hold in GRID_H:
            drift[(feed, hold)] = cf.unconditional(bars[feed], hold, risk[feed])

    cells: dict[tuple[float, int, int, int], tuple[int, float]] = {}
    real_primary: dict[str, list[dict]] = {}
    for change in GRID_C:
        for trailing in GRID_L:
            scored = {feed: cf.scores(feed, change, trailing) for feed in cf.PAIRS}
            for threshold in GRID_T:
                for hold in GRID_H:
                    pooled: list[float] = []
                    for feed in cf.PAIRS:
                        usable, score = scored[feed]
                        rows = cf.trades(
                            feed,
                            bars[feed],
                            usable,
                            score,
                            hold_weeks=hold,
                            threshold=threshold,
                            risk=risk[feed],
                        )
                        shift = drift[(feed, hold)]
                        pooled.extend(row["r"] - row["side"] * shift for row in rows)
                        if (threshold, change, hold, trailing) == PRIMARY:
                            real_primary[feed] = rows
                    cells[(threshold, change, hold, trailing)] = (
                        len(pooled),
                        float(np.mean(pooled)) if pooled else float("nan"),
                    )

    n, mean = cells[PRIMARY]
    print(f"\nprimary cell {PRIMARY}: n {n}  de-drifted meanR {mean:+.3f}")

    usable_cells = {k: v for k, v in cells.items() if v[0] >= 30}
    positive = sum(1 for _, (_, m) in usable_cells.items() if m > 0)
    print(
        f"cells with n >= 30: {len(usable_cells)} of {len(cells)}; "
        f"{positive} positive ({positive / max(len(usable_cells), 1):.1%})"
    )

    print("\n=== slices through the primary, read on the mean ===")
    t0, c0, h0, l0 = PRIMARY
    for label, axis, fixed in (
        ("threshold", GRID_T, lambda v: (v, c0, h0, l0)),
        ("change_w", GRID_C, lambda v: (t0, v, h0, l0)),
        ("hold_w", GRID_H, lambda v: (t0, c0, v, l0)),
        ("trailing", GRID_L, lambda v: (t0, c0, h0, v)),
    ):
        parts = []
        for value in axis:
            cn, cm = cells[fixed(value)]
            parts.append(f"{value}: {cm:+.3f} (n{cn})")
        print(f"  {label:10s} " + "  ".join(parts))

    best = sorted(usable_cells.items(), key=lambda kv: -kv[1][1])[:6]
    print("\n=== strongest cells (n >= 30) ===")
    for (threshold, change, hold, trailing), (cn, cm) in best:
        print(f"  T{threshold} C{change} H{hold} L{trailing}: {cm:+.3f} (n{cn})")

    carry_bound(real_primary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
