"""Directional edge from a state-space member: the drift's own uncertainty.

Seven directional claims have been measured on this desk and all seven are
null against a matched control - the direction chain, the Landau cubic, Point
Z on both sides, the Hawkes cascade, five regime gates, the displacement
family. **Every one of them used a point estimate of direction.**

A state-space member carries something none of them had: a **calibrated
uncertainty on the drift**. `rate_confident` is `|rate| > 2 * sd_rate` and has
existed on every member since the package began without ever being used as a
gate. If the drift is mostly noise but *occasionally* identified, the edge
lives in the small subset where the filter says it knows - and nothing tested
so far could have found it.

That is arm 2, and it is the reason to run this at all.

## The arms, and which are new

1. **The planted arm.** `Drift_Switch_Index_10/20/30` is a real market whose
   drift genuinely switches between discrete values. If the members cannot
   find direction there, they cannot anywhere; if they can, the machinery
   works and real markets simply have no drift to find. Nothing else makes a
   null here readable.
2. **Confidence as the gate** - buckets of `|rate| / sd_rate`. New.
3. **The horizon where cost is payable.** The record says sub-three-minute
   nulls mean *cannot pay* - a cost threshold of 0.188 against a detection of
   0.08 - rather than *cannot find*. At 1h a spread is paid about 24 times a
   day; over a month it is amortised some 700 times. **The members have never
   been scored at week-to-month horizons**, which is the only regime where a
   five-basis-point edge clears costs. New.
4. **Cross-member sign agreement** - do `kalman`, `reverting` and `landau`
   agree, and does agreement beat any one of them? Differently misspecified
   models agreeing is classic ensemble logic and is untested here. New.

## What every arm is scored against

* **A matched random control at the same duty cycle.** A confidence gate fires
  rarely, and a rule that trades rarely changes the average without knowing
  anything - the control that disposed of every pause rule here.
* **`Volatility_*`**, whose drift is **zero by construction**. A non-zero
  reading there is measurement artefact, not an edge.
* **Cost, in spread units**, from the feed's own spread column. Break-even
  needs 1.0 and a round trip 2.0. Every directional result on this desk so far
  has lost exactly the spread, so this column decides it.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from pathlib import Path

from till_infinity.structures.statespace.landau import Landau
from till_infinity.structures.statespace.linear import Gaussian
from till_infinity.structures.statespace.reverting import Reverting

HOUR = 3600.0
SEED = 20261012

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD")
#: Drift is zero by construction: the null that must read null.
FLAT = ("Volatility_75_Index", "Volatility_25_Index", "Step_Index")
#: Drift genuinely switches: the planted arm that makes a null readable.
PLANTED = ("Drift_Switch_Index_10", "Drift_Switch_Index_20", "Drift_Switch_Index_30")

FRAME = os.environ.get("FRAME", "1h")
#: Out to a month at 1h, because that is where a spread stops dominating.
#: 168 is a week, 720 a month.
HORIZONS = tuple(int(h) for h in os.environ.get("HORIZONS", "1,24,168,720").split(","))
JERKS = tuple(10.0**k for k in range(-9, 2))
BUCKETS = 5
DRAWS = int(os.environ.get("DRAWS", "200"))
SINCE = float(os.environ.get("SINCE", "99792000"))
LIMIT = int(os.environ.get("LIMIT", "30000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str = FRAME):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = np.asarray(bundle["time"], dtype=float)[order]
        closes = np.asarray(bundle["close"], dtype=float)[order]
        spread = (
            np.asarray(bundle["spread"], dtype=float)[order]
            if "spread" in bundle
            else np.zeros_like(closes)
        )
    keep = (closes > 0) & (times >= SINCE)
    times, closes, spread = times[keep], closes[keep], spread[keep]
    if len(times) > LIMIT:
        times, closes, spread = times[-LIMIT:], closes[-LIMIT:], spread[-LIMIT:]
    if len(times) < 3 * max(HORIZONS):
        return None
    return times.tolist(), np.log(closes).tolist(), (spread / closes).tolist()


def build(kind: str, jerk: float):
    if kind == "kalman":
        return Gaussian(jerk=jerk, p00=1.0)
    if kind == "reverting":
        return Reverting(sigma2=jerk, theta=0.5)
    if kind == "landau":
        return Landau(sigma2=jerk, theta=0.5, kappa=0.5)
    raise ValueError(kind)


def walk(times, levels, costs, kind: str, jerk: float):
    """One pass, recording the drift, its own uncertainty, and what followed.

    `confidence` is `|rate| / sd_rate` - the filter's own statement about
    whether it has identified a drift at all, which is the quantity no
    indicator can supply and which no earlier harness used.
    """
    member = build(kind, jerk)
    noise = (
        0.25
        * statistics.pstdev([levels[i] - levels[i - 1] for i in range(1, min(len(levels), 3000))])
        ** 2
    )
    start = len(levels) // 2
    rows = []
    for i, (when, level) in enumerate(zip(times, levels, strict=True)):
        member.update(level, noise, when)
        if i < start or i + max(HORIZONS) >= len(levels):
            continue
        spread_rate = member.sd_rate if hasattr(member, "sd_rate") else float("nan")
        rate = float(member.rate)
        if not (math.isfinite(rate) and math.isfinite(spread_rate) and spread_rate > 0):
            continue
        side = 1.0 if rate > 0 else (-1.0 if rate < 0 else 0.0)
        if side == 0.0:
            continue
        rows.append(
            {
                "side": side,
                "confidence": abs(rate) / spread_rate,
                "ahead": {h: 100.0 * side * (levels[i + h] - levels[i]) for h in HORIZONS},
                "cost": 100.0 * float(costs[i]) if costs[i] > 0 else float("nan"),
            }
        )
    return rows


def against_random(rows, picked, horizon: int):
    """Edge of a subset against the right null, and the gap in spread units.

    **Two different nulls, because the question differs.**

    For a *subset* - a confidence bucket - the null is random bars of the same
    count, which controls the duty cycle: a gate that fires rarely changes the
    average without knowing anything.

    For the **whole** set the subset null is degenerate: every draw of
    `len(rows)` from `rows` is the same set, the spread is zero and the
    z-score comes back `nan`. That is what the first run of this arm reported.
    The right null there is **sign randomisation** - keep the moves and flip
    the drift's sign at random - which asks whether the drift's *direction*
    carries information rather than whether a subset differs from its parent.

    The standard error uses the **non-overlapping** count, `len / horizon`,
    not the raw count. At `horizon = 720` on 12,602 rows that is 17
    independent observations rather than 12,602, and quoting the raw figure
    would inflate every long-horizon t-statistic by a factor of 27.
    """
    if len(picked) < 50 or len(rows) < 400:
        return None
    rng = random.Random(SEED)
    real = statistics.fmean(r["ahead"][horizon] for r in picked)
    if len(picked) == len(rows):
        draws = [
            statistics.fmean(
                r["ahead"][horizon] * (1.0 if rng.random() < 0.5 else -1.0) for r in picked
            )
            for _ in range(DRAWS)
        ]
    else:
        draws = [
            statistics.fmean(r["ahead"][horizon] for r in rng.sample(rows, len(picked)))
            for _ in range(DRAWS)
        ]
    middle = statistics.fmean(draws)
    # Inflate the control's spread to the overlapping sample's real precision:
    # the draws are over `len(picked)` values but only `len(picked)/horizon`
    # of them are independent.
    independent = max(len(picked) / max(horizon, 1), 2.0)
    noise = statistics.stdev(draws) * math.sqrt(len(picked) / independent)
    costs = [r["cost"] for r in picked if math.isfinite(r["cost"]) and r["cost"] > 0]
    gate = statistics.fmean(costs) if costs else float("nan")
    return {
        "n": len(picked),
        "independent": independent,
        "edge": real,
        "random": middle,
        "z": (real - middle) / noise if noise > 0 else float("nan"),
        "in_spreads": (real - middle) / gate if gate and gate > 0 else float("nan"),
    }


def best_jerk(times, levels, costs, kind: str):
    """Pick the jerk by the shortest horizon's hit rate, then report all of them.

    Selected on one horizon so the long ones are not chosen on what they are
    then judged by, and reported with the grid edge flagged.
    """
    top = None
    for jerk in JERKS:
        rows = walk(times, levels, costs, kind, jerk)
        if len(rows) < 400:
            continue
        got = against_random(rows, rows, HORIZONS[0])
        if got is None:
            continue
        if top is None or got["edge"] > top[0]:
            top = (got["edge"], jerk, rows)
    if top is None:
        return None, None, False
    return top[1], top[2], top[1] in (JERKS[0], JERKS[-1])


def main() -> None:
    print(
        f"frame {FRAME}, horizons {HORIZONS} bars (168 = a week, 720 = a month)\n"
        "'edge' is the mean forward move in the drift's own direction, percent.\n"
        "'random' is the same over bars drawn at the same count. 'in sprd' is\n"
        "the gap between them in spread units - **break-even is 1.0 and a round\n"
        "trip 2.0**, and that column decides everything.\n"
    )

    print("=" * 112)
    print("ARM 1  the planted arm: can a member find a drift that is really there?")
    print("=" * 112)
    print(
        f"{'instrument':<24}{'member':<11}{'jerk':>8}{'h':>5}{'indep':>7}"
        f"{'edge %':>10}{'random':>10}{'z':>8}{'in sprd':>9}{'edge':>6}"
    )
    for group, names in (("planted", PLANTED), ("flat", FLAT)):
        print(f"--- {group} ---")
        for name in names:
            found = load(name)
            if found is None:
                continue
            times, levels, costs = found
            for kind in ("kalman", "reverting"):
                jerk, rows, on_edge = best_jerk(times, levels, costs, kind)
                if rows is None:
                    continue
                for h in HORIZONS:
                    got = against_random(rows, rows, h)
                    if got is None:
                        continue
                    print(
                        f"{name:<24}{kind:<11}{jerk:>8.0e}{h:>5}{got['independent']:>7.0f}"
                        f"{got['edge']:>+10.4f}{got['random']:>+10.4f}{got['z']:>+8.2f}"
                        f"{got['in_spreads']:>+9.3f}{'*' if on_edge else '':>6}"
                    )

    print("\n" + "=" * 112)
    print("ARM 2  confidence as the gate: is direction findable where the filter says it knows?")
    print("=" * 112)
    print(
        "Buckets of `|rate| / sd_rate`, lowest first. The filter's own statement\n"
        "about whether it has identified a drift - the quantity no indicator can\n"
        "supply and which no earlier harness here used.\n"
    )
    print(
        f"{'instrument':<24}{'member':<11}{'h':>5}"
        + "".join(f"{f'q{i + 1} sprd':>10}" for i in range(BUCKETS))
        + f"{'top z':>8}"
    )
    collected: dict[str, list] = {}
    for group, names in (("traded", TRADED), ("flat", FLAT), ("planted", PLANTED)):
        print(f"--- {group} ---")
        for name in names:
            found = load(name)
            if found is None:
                continue
            times, levels, costs = found
            for kind in ("kalman", "reverting"):
                jerk, rows, _edge = best_jerk(times, levels, costs, kind)
                if rows is None:
                    continue
                order = sorted(rows, key=lambda r: r["confidence"])
                size = len(order) // BUCKETS
                bands = [order[i * size : (i + 1) * size] for i in range(BUCKETS)]
                for h in HORIZONS:
                    parts = [against_random(rows, b, h) for b in bands]
                    if any(p is None for p in parts):
                        continue
                    collected.setdefault(f"{group}:{kind}:{h}", []).append(parts)
                    print(
                        f"{name:<24}{kind:<11}{h:>5}"
                        + "".join(f"{p['in_spreads']:>+10.3f}" for p in parts)
                        + f"{parts[-1]['z']:>+8.2f}"
                    )

    print("\n" + "=" * 112)
    print("ARM 3  the verdict: does the most confident bucket pay, at any horizon?")
    print("=" * 112)
    print(
        f"{'group:member:horizon':<30}{'cells':>7}{'lowest conf':>13}"
        f"{'highest conf':>14}{'top z':>8}{'share z>2':>11}{'share pays':>12}"
    )
    for key in sorted(collected):
        cells = collected[key]
        lows = [c[0]["in_spreads"] for c in cells if math.isfinite(c[0]["in_spreads"])]
        highs = [c[-1]["in_spreads"] for c in cells if math.isfinite(c[-1]["in_spreads"])]
        zs = [c[-1]["z"] for c in cells if math.isfinite(c[-1]["z"])]
        if not highs:
            continue
        print(
            f"{key:<30}{len(cells):>7}"
            + (f"{statistics.median(lows):>+13.3f}" if lows else f"{'-':>13}")
            + f"{statistics.median(highs):>+14.3f}"
            + (
                f"{statistics.median(zs):>+8.2f}{sum(1 for z in zs if z > 2) / len(zs):>11.2f}"
                if zs
                else f"{'-':>8}{'-':>11}"
            )
            + f"{sum(1 for v in highs if v > 1.0) / len(highs):>12.2f}"
        )
    print(
        "\n'share pays' is the fraction of cells whose most-confident bucket\n"
        "clears one spread. The flat rows are the calibration - their drift is\n"
        "zero by construction, so anything they report is artefact."
    )
    print("\nDONE")


if __name__ == "__main__":
    main()
