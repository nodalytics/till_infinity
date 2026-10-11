"""Peaks, troughs, and the distance sequence between like nodes.

Asked on 2026-10-11, right after the displacement work: can we have peaks and
troughs as such, and their distance sequencing?

The displacement sequence that already existed keeps only the **unsigned**
swing size, `|level(b) - level(a)|` between opposite nodes. That is how far
price travelled, and it has the direction already removed - so a clean uptrend
and a flat range with the same swing sizes are *identical* in it. Which is
very likely why `statespace-displacement-sequences.md` came back null on all
seven claims: the ratios were computed on a quantity that cannot tell a trend
from a range.

A like-node step is the other quantity. Peak to peak, trough to trough,
**signed**, and its sign is the structural reading everyone actually uses:
higher highs and higher lows are an uptrend. So the question here is sharp -
does the signed sequence carry what the unsigned one did not?

## Four readings

* **the period.** Consecutive peaks are two swings apart, so a peak-to-peak
  duration is a full cycle. If the market has a characteristic cycle length
  the distribution of those durations is **tight**; if turning points are a
  renewal process it is exponential, whose coefficient of variation is
  exactly 1. That single number decides whether "cycle" means anything here,
  and it is the same shape of test that killed the rotation counting.
* **agreement against drift.** Higher highs *with* higher lows is the textbook
  trend. But any upward drift produces both simply because everything is
  rising, so agreement has to be read against `p^2 + (1-p)^2`, which is what
  two independent sequences at the same up-share would give. The gap is the
  only part that is structure.
* **does a step predict the next step.** Signed rise against the next signed
  rise, with the rotated control, which is the direct test of whether the
  sequence is a sequence.
* **does a step predict the next return.** The tradeable version, over
  horizons in hours, gated on cost.

## The honest prior

Unkind, and from this desk's own measurements. Counted pivots were null over
1,020 cells. The displacement ratios were null on all seven published claims.
The nearest positive thing anywhere near this is
`fade-to-value-targets-the-displacement-origin`, and even there the 82% is a
**target hit rate** rather than an entry signal.

What is genuinely new is only that the sign is kept. That is a real difference
rather than a re-encoding, which is why it is worth one measurement.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from pathlib import Path

from till_infinity.structures.statespace.displacements import (
    PEAK,
    nodes,
    steps,
    structure,
)
from till_infinity.structures.statespace.nulls import control, spearman, trailing

HOUR = 3600.0

TRADED = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "XAUUSD",
    "XAGUSD",
    "BTCUSD",
    "ETHUSD",
    "SPX500",
)
GENERATED = (
    "Volatility_75_Index",
    "Volatility_100_Index",
    "Step_Index",
    "Boom_500_Index",
)

FRAMES = tuple(os.environ.get("FRAMES", "1h,4h,1d").split(","))
SPAN = int(os.environ.get("SPAN", "5"))
HORIZONS = (6, 24, 72, 168)
COST_SPREADS = 1.5
SINCE = float(os.environ.get("SINCE", "1262304000"))
LIMIT = int(os.environ.get("LIMIT", "40000"))
SEED = 20261011
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str):
    import numpy as np

    for path in (CACHE / f"{name}.{frame}.npz", Path(f"data/seqlab/{name}.{frame}.npz")):
        if not path.exists():
            continue
        with np.load(path) as bundle:
            keys = set(bundle.keys())
            if not {"time", "close", "high", "low"} <= keys:
                continue
            order = np.argsort(bundle["time"])
            out = {k: bundle[k][order].tolist() for k in ("time", "close", "high", "low")}
        first = 0
        while first < len(out["time"]) and out["time"][first] < SINCE:
            first += 1
        for key, series in list(out.items()):
            trimmed = series[first:]
            out[key] = trimmed[-LIMIT:] if len(trimmed) > LIMIT else trimmed
        return out if len(out["time"]) > 1000 else None
    return None


def unit(closes: list[float]) -> float:
    moves = [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i] > 0 and closes[i - 1] > 0
    ]
    return statistics.pstdev(moves) if len(moves) > 2 else 0.0


def walk_like(closes: list[float], seed: int) -> list[float]:
    rng = random.Random(seed)
    step = unit(closes) or 1e-6
    out = [closes[0]]
    for _ in range(len(closes) - 1):
        out.append(out[-1] * math.exp(rng.gauss(0.0, step)))
    return out


def spread_of(hours: list[float]) -> float:
    """Coefficient of variation. Exactly 1 for an exponential, so for a
    renewal process - and well below 1 for anything with a period."""
    if len(hours) < 10:
        return float("nan")
    middle = statistics.fmean(hours)
    return statistics.pstdev(hours) / middle if middle > 0 else float("nan")


def period_arm(found, unit_value: float) -> dict[str, float]:
    """Is the peak-to-peak duration a period, or a renewal interval?"""
    moves = steps(found, unit=unit_value, kind=PEAK)
    hours = [m.hours for m in moves]
    if len(hours) < 20:
        return {}
    return {
        "periods": float(len(hours)),
        "median": statistics.median(hours),
        # The decisive number. A renewal process gives exactly 1.
        "spread": spread_of(hours),
    }


def sequence_arm(found, unit_value: float) -> dict[str, float]:
    """Does one signed step say anything about the next?

    Peaks and troughs are kept apart. Interleaving them would put a
    peak-to-peak step next to a trough-to-trough step and call that a lag of
    one, which is two different quantities in one series.
    """
    out: dict[str, float] = {}
    for want, tag in ((PEAK, "peak"), (-PEAK, "trough")):
        moves = steps(found, unit=unit_value, kind=want)
        rises = [m.rise for m in moves]
        if len(rises) < 40:
            continue
        out[f"{tag}_lag1"] = spearman(rises[:-1], rises[1:])
        out[f"{tag}_rotated"] = control(rises[:-1], rises[1:])
        # Against the trailing spread of the same series, to see whether a
        # step is only reporting how volatile the last stretch was.
        out[f"{tag}_vs_sd"] = spearman(rises, trailing(rises, 20))
    return out


def forward_arm(data: dict, found, unit_value: float, bar_hours: float):
    """Does a confirmed step say anything about the next few hours of price?

    Entry is at the bar **after** the step was confirmed, which is the first
    bar a live feature could act on. Using the node's own bar would be reading
    the pivot before the market knew it was one.
    """
    times = data["time"]
    closes = data["close"]
    index = {float(t): i for i, t in enumerate(times)}
    moves = steps(found, unit=unit_value)

    cost = COST_SPREADS * (unit_value or 1e-9)
    rows = []
    for horizon in HORIZONS:
        ahead = max(round(horizon / bar_hours), 1)
        if ahead >= len(closes) // 10:
            continue
        for label, want in (("higher", True), ("lower", False)):
            got: list[float] = []
            for move in moves:
                start = index.get(move.confirmed)
                if start is None or (move.rise > 0) is not want:
                    continue
                here, later = start + 1, start + 1 + ahead
                if later >= len(closes) or closes[here] <= 0 or closes[later] <= 0:
                    continue
                got.append(math.log(closes[later] / closes[here]))
            if len(got) < 30:
                continue
            middle = statistics.fmean(got)
            spread = statistics.pstdev(got) or 1e-12
            # Overlapping windows inflate the t by about the root of the
            # overlap; divided out rather than quoted at face value.
            t = middle / (spread / math.sqrt(len(got))) / math.sqrt(ahead)
            rows.append((label, horizon, len(got), middle, t, cost))
    return rows


def _cell(data: dict, label: str, frame: str, seed: int):
    scale = unit(data["close"])
    if scale <= 0:
        return None
    found = nodes(data["time"], data["close"], data["high"], data["low"], span=SPAN)
    if len(found) < 60:
        return None

    gaps = [data["time"][i] - data["time"][i - 1] for i in range(1, min(len(data["time"]), 500))]
    bar = statistics.median(gaps) / HOUR if gaps else 1.0

    fake = walk_like(data["close"], seed)
    walked = nodes(data["time"], fake, fake, fake, span=SPAN)

    return {
        "label": label,
        "frame": frame,
        "structure": structure(found, unit=scale),
        "walk_structure": structure(walked, unit=unit(fake)),
        "period": period_arm(found, scale),
        "walk_period": period_arm(walked, unit(fake)),
        "sequence": sequence_arm(found, scale),
        "forward": forward_arm(data, found, scale, bar),
    }


def measure() -> list[dict]:
    out = []
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            data = load(name, frame)
            if data is None:
                continue
            shown = f"*{name}" if name in GENERATED else name
            found = _cell(data, shown, frame, SEED + len(out))
            if found:
                out.append(found)
    return out


def report(found: list[dict]) -> None:
    print(f"cells {len(found)}  frames {FRAMES}  span {SPAN} bars\n")

    print("== is the peak-to-peak duration a period? a renewal process gives spread 1.00")
    print(f"{'instrument':<22}{'frame':<6}{'n':>6}{'median h':>10}{'spread':>8}{'walk':>8}")
    for cell in found:
        one, two = cell["period"], cell["walk_period"]
        if not one:
            continue
        print(
            f"{cell['label']:<22}{cell['frame']:<6}{one['periods']:>6.0f}"
            f"{one['median']:>10.1f}{one['spread']:>8.2f}"
            f"{two.get('spread', float('nan')):>8.2f}"
        )

    print("\n== higher highs with higher lows, against what the drift alone gives")
    print(
        f"{'instrument':<22}{'frame':<6}{'HH':>7}{'HL':>7}"
        f"{'agree':>8}{'drift':>8}{'gain':>8}{'walk gain':>11}"
    )
    gains, walk_gains = [], []
    for cell in found:
        one, two = cell["structure"], cell["walk_structure"]
        if not one or math.isnan(one.get("agreement", float("nan"))):
            continue
        gain = one["agreement"] - one["drift"]
        gains.append(gain)
        walk = (
            two["agreement"] - two["drift"]
            if two and not math.isnan(two.get("agreement", float("nan")))
            else float("nan")
        )
        if not math.isnan(walk):
            walk_gains.append(walk)
        print(
            f"{cell['label']:<22}{cell['frame']:<6}{one['higher_highs']:>7.3f}"
            f"{one['higher_lows']:>7.3f}{one['agreement']:>8.3f}"
            f"{one['drift']:>8.3f}{gain:>8.3f}{walk:>11.3f}"
        )
    if gains:
        print(
            f"median gain over drift {statistics.median(gains):+.3f}   "
            f"a walk's own gain {statistics.median(walk_gains):+.3f}"
        )

    print("\n== does one signed step say anything about the next?")
    print(
        f"{'instrument':<22}{'frame':<6}{'peak lag1':>11}{'rotated':>9}"
        f"{'trough lag1':>13}{'rotated':>9}{'vs sd':>8}"
    )
    for cell in found:
        one = cell["sequence"]
        if "peak_lag1" not in one:
            continue
        print(
            f"{cell['label']:<22}{cell['frame']:<6}{one['peak_lag1']:>11.3f}"
            f"{one['peak_rotated']:>9.3f}{one.get('trough_lag1', float('nan')):>13.3f}"
            f"{one.get('trough_rotated', float('nan')):>9.3f}"
            f"{one.get('peak_vs_sd', float('nan')):>8.3f}"
        )

    print("\n== after a confirmed step, what does price do? cost-gated")
    print(
        f"{'instrument':<22}{'frame':<6}{'step':<8}{'h':>5}{'n':>6}"
        f"{'mean':>10}{'t':>7}{'cost':>10}{'':>12}"
    )
    best = 0.0
    shown = 0
    for cell in found:
        for label, horizon, count, middle, t, cost in cell["forward"]:
            if abs(middle) < cost:
                best = max(best, 0.0)
                continue
            shown += 1
            best = max(best, abs(t))
            print(
                f"{cell['label']:<22}{cell['frame']:<6}{label:<8}{horizon:>5}{count:>6}"
                f"{middle:>10.5f}{t:>7.2f}{cost:>10.5f}{'over cost':>12}"
            )
    total = sum(len(cell["forward"]) for cell in found)
    print(f"\n{shown} of {total} cells clear the cost gate; largest |t| among them {best:.2f}")


if __name__ == "__main__":
    report(measure())
