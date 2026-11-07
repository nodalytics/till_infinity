"""The carry-neutral version: rank the eight markets, trade the extremes.

    ./.secrets/lab.sh run research/harness/cotcross.py

## What this fixes about the fade

`cotfade.py` measured the rule as specified: +0.243R de-drifted on 290 trades,
and **-0.126R of carry at today's rates on 8 of 8 instruments**, which shifts
the interval to straddle zero. The drag is mechanical - fading crowded
positioning means shorting the currency everyone is long, and what everyone is
long is what pays to hold, so the signal and the carry are the same crowd.

Two defects fall out together here:

* **Carry.** A long leg and a short leg financed against the same dollar
  offset much of each other's swap, so the basket pays a fraction of what
  eight one-sided bets pay. Reported rather than assumed - the broker takes a
  spread on both sides of the swap (gbp pays -5.43 long **and** -4.13 short),
  so cancellation is partial and has to be measured.
* **Independence.** `linear-algebra.md` finds one factor in this book carrying
  45.6% of variance and its eigenvector is the dollar, so eight simultaneous
  one-sided positions are nowhere near eight bets. A long/short basket is
  dollar-neutral by construction, which is what makes the baskets countable.

## Why the baskets do not overlap

Entries step by the hold, so no basket shares a week with another. The
overlapping version would roughly quadruple the row count and none of the
extra rows would be new information - the defect that turned a direction AUC
of 0.79 into 0.51 elsewhere in this repository.

## The arm that decides it

`shuffled-across` permutes the scores **between instruments inside the same
week**, which destroys the cross-sectional ranking while keeping the week, the
dates, the holds and the market conditions identical. If the real basket does
not beat that, the reading is the weeks and not the ranking.
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

HOLD_WEEKS = int(os.environ.get("HOLD_WEEKS", "4"))
KS = [1, 2, 3]
DRAWS = 2000
SEED = 20261107
NIGHTS = 36
BASE = os.environ.get("BRIDGE", "http://localhost:8000") + "/api/v1"


def swaps() -> dict[str, tuple[float, float, float]]:
    """(swap_long, swap_short, point) per feed, mode 1 only."""
    key = (Path.home() / ".mt5key").read_text().strip()
    out: dict[str, tuple[float, float, float]] = {}
    for feed, symbol in cf.PAIRS.items():
        try:
            req = request.Request(  # noqa: S310
                f"{BASE}/symbols/info/{symbol}", headers={"X-API-Key": key}
            )
            with request.urlopen(req, timeout=60) as response:  # noqa: S310
                info = json.loads(response.read().decode())
        except Exception:  # noqa: BLE001
            continue
        if isinstance(info, dict) and int(info.get("swap_mode") or -1) == 1:
            out[feed] = (
                float(info.get("swap_long") or 0.0),
                float(info.get("swap_short") or 0.0),
                float(info.get("point") or 0.0),
            )
    return out


def main() -> int:
    rng = np.random.default_rng(SEED)
    bars = {f: cf.load_bars(s) for f, s in cf.PAIRS.items()}
    risk = {f: 2.0 * cf.atr(bars[f]) for f in cf.PAIRS}
    swap = swaps()
    hold = HOLD_WEEKS * 7 * 86400.0

    # date -> {feed: score}. Dates differ per feed only in how far back they
    # reach, so the key is the usable timestamp itself.
    board: dict[float, dict[str, float]] = {}
    for feed in cf.PAIRS:
        usable, score = cf.scores(feed)
        for ts, value in zip(usable, score, strict=True):
            if np.isfinite(value):
                board.setdefault(float(ts), {})[feed] = float(value)

    dates = sorted(ts for ts, row in board.items() if len(row) >= 6)
    print(f"{len(dates)} weeks with at least 6 markets scored\n")

    def leg_r(feed: str, ts: float, side: float) -> tuple[float, float] | None:
        """(R, swap in R) for one leg, or None where it cannot be priced."""
        time, close = bars[feed]["time"], bars[feed]["close"]
        i = int(np.searchsorted(time, ts, side="left"))
        j = int(np.searchsorted(time, ts + hold, side="left"))
        if i >= len(time) or j >= len(time) or not np.isfinite(risk[feed][i]):
            return None
        unit = risk[feed][i]
        if unit <= 0.0:
            return None
        r = side * (close[j] - close[i]) / unit
        carried = 0.0
        if feed in swap:
            swap_long, swap_short, point = swap[feed]
            carried = ((swap_long if side > 0 else swap_short) * point * NIGHTS) / unit
        return float(r), float(carried)

    def basket(ts: float, ranked: list[tuple[str, float]], k: int) -> tuple[float, float] | None:
        """Mean leg R and mean leg swap for one basket."""
        if len(ranked) < 2 * k:
            return None
        legs = [(feed, 1.0) for feed, _ in ranked[:k]] + [
            (feed, -1.0) for feed, _ in ranked[-k:]
        ]
        got = [leg_r(feed, ts, side) for feed, side in legs]
        kept = [g for g in got if g is not None]
        if len(kept) < 2 * k:
            return None
        return float(np.mean([g[0] for g in kept])), float(np.mean([g[1] for g in kept]))

    step = HOLD_WEEKS
    head = f"{'arm':18s} {'K':>2s} {'baskets':>8s} {'meanR':>8s} {'lo':>8s} {'hi':>8s} {'swapR':>8s} {'net':>8s}"
    print(head)
    print("-" * len(head))

    for k in KS:
        results: dict[str, list[float]] = {name: [] for name in
                                           ("real", "reversed", "shuffled-across", "stale-8w", "random-pick")}
        carries: list[float] = []
        for d in range(0, len(dates) - 1, step):
            ts = dates[d]
            row = board[ts]
            feeds = sorted(row)
            # Lowest score first: the fade LONGS the markets speculators left
            # and SHORTS the ones they piled into.
            ranked = sorted(((f, row[f]) for f in feeds), key=lambda kv: kv[1])

            got = basket(ts, ranked, k)
            if got is None:
                continue
            results["real"].append(got[0])
            carries.append(got[1])

            rev = basket(ts, list(reversed(ranked)), k)
            if rev is not None:
                results["reversed"].append(rev[0])

            values = [row[f] for f in feeds]
            rng.shuffle(values)
            shuffled = sorted(zip(feeds, values, strict=True), key=lambda kv: kv[1])
            got = basket(ts, shuffled, k)
            if got is not None:
                results["shuffled-across"].append(got[0])

            stale_ts = dates[d - 8] if d >= 8 else None
            if stale_ts is not None:
                stale_row = board[stale_ts]
                shared = [f for f in feeds if f in stale_row]
                if len(shared) >= 2 * k:
                    stale_ranked = sorted(
                        ((f, stale_row[f]) for f in shared), key=lambda kv: kv[1]
                    )
                    got = basket(ts, stale_ranked, k)
                    if got is not None:
                        results["stale-8w"].append(got[0])

            picked = list(feeds)
            rng.shuffle(picked)
            got = basket(ts, [(f, 0.0) for f in picked], k)
            if got is not None:
                results["random-pick"].append(got[0])

        swap_mean = float(np.mean(carries)) if carries else float("nan")
        for name, values in results.items():
            if not values:
                continue
            mean = float(np.mean(values))
            boots = [
                float(np.mean([values[i] for i in rng.integers(0, len(values), len(values))]))
                for _ in range(DRAWS)
            ]
            lo, hi = float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))
            shown_swap = swap_mean if name == "real" else float("nan")
            net = mean + swap_mean if name == "real" else float("nan")
            print(
                f"{name:18s} {k:2d} {len(values):8d} {mean:8.3f} {lo:8.3f} {hi:8.3f} "
                f"{shown_swap:8.3f} {net:8.3f}"
            )
        print()

    print(
        "The baskets do not overlap, so each row is an independent observation, and the\n"
        "basket is dollar-neutral so the one factor in this book is not being bet on.\n"
        "`real` must beat `shuffled-across` - same weeks, same dates, ranking destroyed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
