"""Second-scale windows, now that tick stores make them reachable.

Asked on 2026-10-12: the ladder supports minutes, hours, days and weeks, and
with quote data it should support **seconds** - an EMA over thirty seconds
beside one over three minutes, and the pairs that follow.

## What was already there, and what was not

`inputs.LADDER` has carried `10s` and `30s` rungs for a long time and **no
feed could ever reach them**. The finest series this desk stored was 1m, and
`resolvable` correctly refused a 10s window on it: two bars is the floor and
ten seconds is a sixth of a 1m bar. The rungs were aspiration.

Tick stores change that. Added here: `1s` and `5s`, because ticks arrive every
tenth of a second on the traded pairs and every second or two on the
synthetics. The bound still does its work at the fine end - a 1s feed reaches
`5s` and is refused `1s`, exactly as a 1d feed is refused `30m`.

## The reading that decides the scale

A rung being **reachable** is not a rung being **useful**, and at this scale
the question is not information but cost. A round trip pays the spread; a
thirty-second move may be smaller than the spread. So the first table is the
**median move over each rung, in spreads**, and a rung whose ratio is below
about three cannot support a round trip at any hit rate - there is no edge
large enough to clear a cost that is a third of the move.

That number is cheap and it bounds everything else, so it comes first and the
signal arms come after. The desk has learnt this the expensive way once
already: the up/down edge measured good fills and -98%.

## The pair arm

The user's example: an EMA over thirty seconds against one over three
minutes. For each ordered pair of resolvable rungs the fast EMA less the slow
is a signal, and the forward return over the slow rung's own horizon is the
outcome, with:

* the **rotated control** at three offsets, since a smooth difference of two
  EMAs is autocorrelated and will correlate with anything smooth;
* the **cost gate** in that instrument's own median spread;
* and cell counting, because the pairs of fifteen rungs are many.

Runs on the lab.
"""

from __future__ import annotations

import itertools
import math
import os
import statistics
from pathlib import Path

HOUR = 3600.0

TRADED = ("XAUUSD", "BTCUSD")
GENERATED = ("Volatility_75_Index", "Step_Index", "Boom_500_Index")

#: Bar length in seconds for the series built from ticks. One second, so the
#: ladder reaches `5s` upward.
BAR_SECONDS = int(os.environ.get("BAR_SECONDS", "1"))

#: Round-trip cost in spreads, the desk's own gate.
COST_SPREADS = 1.5

#: The rungs to pair, by label. Only the second and low-minute end: pairing a
#: 1s EMA with a 1d one on five hours of data is not a measurement.
PAIRS = ("5s", "10s", "30s", "1m", "3m", "5m", "15m")

TICKS = Path.home() / "till_infinity" / "data" / "seqlab" / "ticks"


def load(name: str):
    import numpy as np

    path = TICKS / f"{name}.tick.npz"
    if not path.exists():
        return None
    try:
        with np.load(path) as bundle:
            if not {"time", "bid", "ask"} <= set(bundle.keys()):
                return None
            order = np.argsort(bundle["time"])
            times = np.asarray(bundle["time"], dtype=float)[order]
            bids = np.asarray(bundle["bid"], dtype=float)[order]
            asks = np.asarray(bundle["ask"], dtype=float)[order]
    except Exception:
        return None
    keep = (bids > 0) & (asks >= bids)
    return times[keep], bids[keep], asks[keep]


def bars_from_ticks(times, bids, asks, seconds: int):
    """Second bars from ticks: time, high, low, close of the mid, and spread."""
    import numpy as np

    mids = (bids + asks) / 2.0
    spreads = asks - bids
    edges = (times // seconds).astype(np.int64)
    out = {"time": [], "high": [], "low": [], "close": [], "spread": []}
    start = 0
    for i in range(1, len(edges) + 1):
        if i < len(edges) and edges[i] == edges[start]:
            continue
        chunk = mids[start:i]
        out["time"].append(float(edges[start] * seconds + seconds))
        out["high"].append(float(chunk.max()))
        out["low"].append(float(chunk.min()))
        out["close"].append(float(chunk[-1]))
        out["spread"].append(float(np.median(spreads[start:i])))
        start = i
    return out


def move_per_rung(data: dict, rungs) -> list[tuple[str, float, float, float]]:
    """Median absolute move over each rung, in spreads and in basis points.

    **The table that bounds the scale.** A rung whose move is smaller than a
    few spreads cannot support a round trip however good the signal.
    """
    closes = data["close"]
    spread = statistics.median(data["spread"]) or 1e-12
    middle = statistics.median(closes) or 1.0
    out = []
    for window in rungs:
        span = window.bars(BAR_SECONDS / HOUR, 1.0)
        if span < 2 or span >= len(closes) // 4:
            continue
        moves = [
            abs(closes[i + span] - closes[i]) for i in range(0, len(closes) - span, max(span, 1))
        ]
        if len(moves) < 30:
            continue
        got = statistics.median(moves)
        out.append((window.label(), got / spread, got / middle * 1e4, float(len(moves))))
    return out


def ema(values: list[float], span: int) -> list[float]:
    """Exponential mean with a span in bars, as `inputs` does it."""
    if span < 1:
        return list(values)
    weight = 2.0 / (span + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(out[-1] + weight * (value - out[-1]))
    return out


def spearman(xs: list[float], ys: list[float], shift: int = 0) -> float:
    n = min(len(xs), len(ys))
    if n < 30:
        return float("nan")
    xs, ys = xs[:n], ys[:n]
    if shift:
        xs = [xs[(i + shift) % n] for i in range(n)]

    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        for rank, i in enumerate(order):
            out[i] = float(rank)
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den > 0 else float("nan")


def pair_arm(data: dict, rungs) -> list[dict]:
    """Fast EMA less slow EMA against the forward move over the slow horizon."""
    closes = data["close"]
    spread = statistics.median(data["spread"]) or 1e-12
    spans = {}
    for window in rungs:
        if window.label() not in PAIRS:
            continue
        span = window.bars(BAR_SECONDS / HOUR, 1.0)
        if 2 <= span < len(closes) // 8:
            spans[window.label()] = span
    if len(spans) < 2:
        return []

    means = {label: ema(closes, span) for label, span in spans.items()}
    rows = []
    for fast, slow in itertools.combinations(spans, 2):
        if spans[fast] >= spans[slow]:
            continue
        ahead = spans[slow]
        signal: list[float] = []
        outcome: list[float] = []
        # Strided by the horizon, so the windows do not overlap and the `t`
        # is not inflated by the same move counted many times.
        for i in range(spans[slow], len(closes) - ahead, ahead):
            signal.append(means[fast][i] - means[slow][i])
            outcome.append(closes[i + ahead] - closes[i])
        if len(signal) < 40:
            continue
        raw = spearman(signal, outcome)
        control = statistics.fmean(
            [
                v
                for v in (
                    spearman(signal, outcome, shift=max(int(len(signal) * f), 1))
                    for f in (0.25, 0.5, 0.75)
                )
                if not math.isnan(v)
            ]
            or [float("nan")]
        )
        # What a perfectly-signed trade would have made, per round trip, in
        # spreads - against the cost of one.
        edge = statistics.fmean([abs(v) for v in outcome]) / spread
        rows.append(
            {
                "fast": fast,
                "slow": slow,
                "n": len(signal),
                "raw": raw,
                "control": control,
                "edge": edge,
            }
        )
    return rows


def main() -> None:
    from till_infinity.structures.statespace.inputs import resolvable

    print(
        f"bars built at {BAR_SECONDS}s from ticks  cost {COST_SPREADS} spreads\n"
        "move/spread is the median absolute move over the rung divided by the\n"
        "instrument's median spread. Below about 3 a round trip cannot pay at\n"
        "any hit rate, because the cost is a third of the whole move.\n"
    )

    rungs_cache = {}
    print(f"{'instrument':<24}{'rung':>6}{'move/spread':>13}{'move bp':>9}{'n':>7}")
    for name in TRADED + GENERATED:
        found = load(name)
        if found is None:
            print(f"{name:<24}unreadable")
            continue
        data = bars_from_ticks(*found, BAR_SECONDS)
        if len(data["close"]) < 1000:
            continue
        rungs = resolvable(BAR_SECONDS / HOUR, len(data["close"]))
        rungs_cache[name] = (data, rungs)
        label = f"*{name}" if name in GENERATED else name
        for rung, ratio, basis, count in move_per_rung(data, rungs):
            if rung not in PAIRS:
                continue
            print(f"{label:<24}{rung:>6}{ratio:>13.2f}{basis:>9.2f}{count:>7.0f}")

    print("\n== the pair arm: fast EMA less slow EMA, strided by the slow horizon")
    print(
        f"{'instrument':<24}{'fast':>6}{'slow':>6}{'n':>6}{'raw':>8}{'rotated':>9}{'move/sprd':>11}"
    )
    best = []
    for name, (data, rungs) in rungs_cache.items():
        label = f"*{name}" if name in GENERATED else name
        for row in pair_arm(data, rungs):
            print(
                f"{label:<24}{row['fast']:>6}{row['slow']:>6}{row['n']:>6}"
                f"{row['raw']:>8.3f}{row['control']:>9.3f}{row['edge']:>11.2f}"
            )
            if not name.startswith(GENERATED[:1]):
                best.append(row)
    traded = [
        r
        for name, (_d, _r) in rungs_cache.items()
        if name in TRADED
        for r in pair_arm(*rungs_cache[name])
    ]
    if traded:
        strong = [r for r in traded if abs(r["raw"]) > abs(r["control"]) + 0.1]
        payable = [r for r in traded if r["edge"] > COST_SPREADS * 2.0]
        print(
            f"\n   {len(traded)} traded pairs. {len(strong)} beat their rotated"
            f" control by 0.1.\n   {len(payable)} have a move worth more than"
            f" twice the round-trip cost."
        )


if __name__ == "__main__":
    main()
