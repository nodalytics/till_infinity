"""Measure the market classes `behaving.TRAITS` has no row for.

`behaving.TRAITS` holds absorption, activity extent and the `Q` exponent for
six classes, and returns `None` for the rest - equities, crypto, the FX
crosses, the softs, the baskets and the volatility synthetics - because they
were not in the study that produced it. `None` is the honest answer to an
unmeasured class, and the fix is to measure them rather than to guess a row.

## What is being measured and why each one is in the table

* **absorption**, `|imbalance|` over a **matched walk's** own `|imbalance|`,
  minus one. The walk is built from the instrument's own per-bar tick counts
  and volatility, so the comparison removes path geometry - most OHLC flow
  proxies take ordinary values on a random path and a figure without the walk
  beside it says nothing. Negative absorbs, zero is a walk, positive runs;
* **activity extent**, the ninetieth over the tenth percentile of
  `pacing.shares`. One means a fixed tick count and so an inert activity
  channel, whatever else is true of the market;
* **tail alpha**, Hill's estimator on raw returns, which says which moments
  exist. Below two there is no variance and a sample kurtosis is an artefact of
  the largest observation.

The `Q` exponent is **not** measured here. It needs the filter sweep in
`activity_clock.py`, which is far more expensive per instrument, and a class
whose activity extent comes back near one cannot have one at all.

## The classes are populated from the cache, not from a list

`behaving.classify` already names every family, so the instruments are gathered
by asking it rather than by naming them - which means a class cannot be
silently misassigned between this harness and the library it feeds.

Medians over instruments within a class, with the count reported, because a
class represented by two names is a different claim from one represented by
forty.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (str(ROOT), str(Path(__file__).resolve().parent)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import orderflow_from_bars as flow  # noqa: E402

from till_infinity.statespace.behaving import classify  # noqa: E402
from till_infinity.statespace.pacing import extent  # noqa: E402

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
#: Instruments per class, so one crowded class cannot dominate the runtime.
PER_CLASS = int(os.environ.get("PER_CLASS", "12"))
WALKS = int(os.environ.get("WALKS", "4"))
SEED = 20261013


def hill(values, share: float = 0.05) -> float:
    """Hill's tail index on `|values|`, over the top `share` of observations."""
    import numpy as np

    got = np.sort(np.abs(np.asarray(values, dtype=float)))
    got = got[got > 0]
    k = int(len(got) * share)
    if k < 50:
        return float("nan")
    tail = got[-k:]
    cut = got[-k]
    if cut <= 0:
        return float("nan")
    logs = np.log(tail / cut)
    total = float(logs.sum())
    return k / total if total > 0 else float("nan")


def main() -> None:
    import numpy as np

    print(f"frame {FRAME}  up to {PER_CLASS} instruments per class  {WALKS} walks each\n")
    names: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob(f"*.{FRAME}.npz")):
        name = path.name[: -len(f".{FRAME}.npz")]
        names.setdefault(classify(name), []).append(name)
    print("what the cache holds, by the library's own classifier:")
    for label in sorted(names):
        print(f"  {label:<16}{len(names[label]):>5}")

    print("\n" + "=" * 112)
    print("per class, against each instrument's own matched walk")
    print("=" * 112)
    print(
        f"{'class':<16}{'names':>6}{'absorption':>12}{'state':>10}"
        f"{'extent':>9}{'tail alpha':>12}{'bars, median':>14}"
    )
    rng = np.random.default_rng(SEED)
    out = {}
    for label in sorted(names):
        picked, cells = [], []
        for name in names[label]:
            if len(picked) >= PER_CLASS:
                break
            bars = flow.load(name)
            if bars is None:
                continue
            opens, highs, lows, closes, ticks = bars[:5]
            real = flow.statistics_for(bars)
            if not real or not math.isfinite(real.get("|imbalance|", float("nan"))):
                continue
            steps = np.diff(np.log(closes))
            sigma_bar = float(np.std(steps)) or 1e-9
            sigma_tick = sigma_bar / math.sqrt(max(float(np.mean(ticks)), 1.0))
            drawn = []
            for _ in range(WALKS):
                walk = flow.matched_walk(ticks, sigma_tick, rng)
                got = flow.statistics_for(walk)
                if got and math.isfinite(got.get("|imbalance|", float("nan"))):
                    drawn.append(got["|imbalance|"])
            if not drawn:
                continue
            picked.append(name)
            cells.append(
                {
                    "absorption": real["|imbalance|"] / statistics.median(drawn) - 1.0,
                    "extent": extent(ticks.tolist()),
                    "alpha": hill(steps),
                    "bars": len(closes),
                }
            )
        if not cells:
            print(f"{label:<16}{0:>6}   nothing usable")
            continue
        absorption = statistics.median(c["absorption"] for c in cells)
        state = "absorbs" if absorption < -0.01 else "runs" if absorption > 0.01 else "neutral"
        alphas = [c["alpha"] for c in cells if math.isfinite(c["alpha"])]
        print(
            f"{label:<16}{len(cells):>6}{absorption:>+12.4f}{state:>10}"
            f"{statistics.median(c['extent'] for c in cells):>9.3f}"
            f"{statistics.median(alphas) if alphas else float('nan'):>12.2f}"
            f"{statistics.median(c['bars'] for c in cells):>14,.0f}"
        )
        out[label] = (absorption, state, cells)

    print(
        "\n**`state` is the claim and `absorption` is only its size.** The\n"
        "departures are a few per cent, so what separates a real book from a\n"
        "generator is the **sign**, and a class whose sign disagrees with the\n"
        "classes around it is the interesting row rather than the largest one."
    )

    real_like = [k for k, v in out.items() if v[1] == "absorbs"]
    made_like = [k for k, v in out.items() if v[1] == "runs"]
    flat = [k for k, v in out.items() if v[1] == "neutral"]
    print(f"\nabsorbs : {', '.join(sorted(real_like)) or '-'}")
    print(f"runs    : {', '.join(sorted(made_like)) or '-'}")
    print(f"neutral : {', '.join(sorted(flat)) or '-'}")
    print(
        "\nThe prediction this tests is that **every traded class absorbs and\n"
        "every generated one does not**, since absorption is what a passive\n"
        "order book does and a generator has no book. A traded class that\n"
        "comes back neutral is either thinly quoted or not really traded."
    )


if __name__ == "__main__":
    main()
