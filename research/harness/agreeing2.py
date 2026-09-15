"""Is a turn both detectors find different from one only one of them finds?

The usual question is *which detector is better*, and it has a dull answer: a
zigzag confirms a turn in about one bar, a changepoint detector in ten to
twenty-two, and they agree on well under half of each other's turns. That
disagreement is normally treated as a nuisance to be settled by picking a winner.

**It is a free conditioning variable**, and this desk already runs both -
`_note_change` is live and the swing detector feeds every level.
`research/families.md` is the reason to take that seriously: Range Break came in
at direction AUC **0.6627** while being invisible to lag-1 autocorrelation
(+0.0008) and to a phase surrogate (0.4956), because the structure was
conditional on position in a band. The conditioning variable was the whole
finding.

## The trap, which is most of the design

**A detector that confirms in twenty-two bars has seen twenty-two bars the other
has not.** Score the two at their own confirmation times and the slower one wins
on every forward-looking statistic, for a reason that has nothing to do with
turns: it is being asked the question later, with more information. That is not a
detector comparison, it is a head start.

So everything here is scored **at a common clock**: the later of the two
confirmations, for every turn, whether one detector found it or both. An
agreement and a disagreement are then judged from the same bar with the same
information, and the only difference between them is what the detectors said.

Turns are matched when their extremes fall within `NEAR` bars of each other and
point the same way. Anything else is two different events.

## The arms

* **both** - a turn each detector found independently.
* **zigzag only** and **cusum only** - found by one.
* and every arm on a matched Brownian null, because a detector run on a random
  walk still produces turns and still agrees with itself sometimes, and the
  agreement rate of two detectors on noise is not zero.

The outcome is the same one `refining.py` uses - does price reject the level -
so the two pages are comparable and neither invents its own definition of a
rejection.

    ./.secrets/lab.sh run research/harness/agreeing2.py
"""

from __future__ import annotations

import math
import sys

import numpy as np

from research.harness import seqlab
from research.harness.refining import REJECT_BY, TOLERANCE, rejected
from research.harness.reversing import turns_with_confirmation

#: Zigzag threshold, in per-bar sigma.
THETA = 2.0

#: Bars within which two extremes are the same event.
NEAR = 3

#: CUSUM threshold in sigma units, and its drift allowance.
CUSUM_H = 5.0
CUSUM_K = 0.5

GRID = ("15m", "1h", "4h")
FEWEST = 40


def cusum_turns(prices: np.ndarray, sigma: float) -> list[tuple[int, int]]:
    """Page's CUSUM on the increments, as `(extreme index, confirmation index)`.

    A genuinely different instrument from the zigzag rather than the same idea
    at another threshold: the zigzag waits for a **price reversal** of a fixed
    size, this waits for the **cumulative drift** of the increments to exceed a
    bound. One is about distance travelled back, the other about evidence
    accumulated - which is why they disagree on most turns and why the
    disagreement might carry something.
    """
    steps = np.diff(prices)
    if len(steps) < 10 or sigma <= 0:
        return []
    k = CUSUM_K * sigma
    h = CUSUM_H * sigma
    up = down = 0.0
    anchor = 0
    out: list[tuple[int, int]] = []
    for i, s in enumerate(steps, start=1):
        up = max(0.0, up + s - k)
        down = min(0.0, down + s + k)
        if up > h:
            # The extreme is the lowest point since the run began.
            lo = int(np.argmin(prices[anchor : i + 1])) + anchor
            out.append((lo, i))
            up = down = 0.0
            anchor = i
        elif down < -h:
            hi = int(np.argmax(prices[anchor : i + 1])) + anchor
            out.append((hi, i))
            up = down = 0.0
            anchor = i
    return out


def classify(prices: np.ndarray, sigma: float) -> list[tuple[int, int, str]]:
    """Every turn as `(extreme, common confirmation bar, arm)`.

    The common bar is the **later** of the two confirmations when both found it,
    and simply the finder's own when only one did. That is what removes the head
    start described in the module note.
    """
    zig = turns_with_confirmation(prices, THETA * sigma)
    cus = cusum_turns(prices, sigma)
    used: set[int] = set()
    out: list[tuple[int, int, str]] = []
    for z_at, z_conf in zig:
        match = None
        for j, (c_at, c_conf) in enumerate(cus):
            if j in used or abs(c_at - z_at) > NEAR:
                continue
            match = (j, c_conf)
            break
        if match is None:
            out.append((z_at, z_conf, "zigzag_only"))
        else:
            j, c_conf = match
            used.add(j)
            out.append((z_at, max(z_conf, c_conf), "both"))
    for j, (c_at, c_conf) in enumerate(cus):
        if j not in used:
            out.append((c_at, c_conf, "cusum_only"))
    return out


def score(prices: np.ndarray, sigma: float) -> dict[str, tuple[int, int]]:
    """Retests and rejections per arm, all judged from the common bar."""
    tally: dict[str, list[int]] = {k: [0, 0] for k in ("both", "zigzag_only", "cusum_only")}
    tolerance = TOLERANCE * sigma
    for at, confirmed, arm in classify(prices, sigma):
        level = float(prices[at])
        for j in range(confirmed + 1, len(prices)):
            if abs(prices[j] - level) <= tolerance:
                got = rejected(prices, j, level, sigma)
                if got is not None:
                    tally[arm][0] += 1
                    tally[arm][1] += int(got)
                break
    return {k: (v[0], v[1]) for k, v in tally.items()}


def run(symbols: list[str], arm_source: str, rng) -> dict:
    totals: dict[str, list[int]] = {k: [0, 0] for k in ("both", "zigzag_only", "cusum_only")}
    cells = 0
    for broker in symbols:
        for interval in GRID:
            try:
                bars = seqlab.load(broker, interval)
            except Exception:  # noqa: BLE001
                continue
            closes = np.asarray(bars["close"], dtype=float)
            logs = np.log(np.maximum(closes, 1e-12))
            sigma = float(np.std(np.diff(logs), ddof=1))
            if sigma <= 0:
                continue
            series = logs
            if arm_source == "gbm":
                series = logs[0] + np.cumsum(rng.normal(0.0, sigma, len(logs)))
            got = score(series, sigma)
            if sum(v[0] for v in got.values()) >= FEWEST:
                cells += 1
                for k, (t, r) in got.items():
                    totals[k][0] += t
                    totals[k][1] += r
    if not cells:
        return {}
    out = {"cells": cells}
    for k, (t, r) in totals.items():
        out[k] = {
            "tested": t,
            "rate": r / t if t else float("nan"),
            "se": math.sqrt(max(r * (t - r), 1)) / t**1.5 if t else float("nan"),
        }
    return out


def main() -> int:
    print("Is a turn both detectors find different from one only one of them finds?\n")
    print("Everything is judged from the LATER of the two confirmations, so a slow")
    print("detector gets no head start. Rejection is `refining.py`'s definition.\n")
    print(
        f"{'group':12} {'source':8} {'cells':>6}  "
        f"{'both n':>8} {'both':>7}  {'zig n':>8} {'zigzag':>7}  "
        f"{'cus n':>8} {'cusum':>7}"
    )
    for name, symbols in (
        ("real", list(seqlab.REAL)),
        ("volatility", list(seqlab.VOLATILITY)[:12]),
    ):
        for source in ("feed", "gbm"):
            got = run(symbols, source, np.random.default_rng(41))
            if not got:
                print(f"{name:12} {source:8}  nothing scored")
                continue
            b, z, c = got["both"], got["zigzag_only"], got["cusum_only"]
            print(
                f"{name:12} {source:8} {got['cells']:>6}  "
                f"{b['tested']:>8,} {b['rate']:>7.4f}  "
                f"{z['tested']:>8,} {z['rate']:>7.4f}  "
                f"{c['tested']:>8,} {c['rate']:>7.4f}"
            )
        print()

    print("Reading it: `both` above the single-detector arms, on the feed and not on")
    print("gbm, is agreement carrying something. Equal rates mean the disagreement is")
    print("noise and the ensemble-of-detectors idea can be retired.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
