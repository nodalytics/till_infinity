"""Four clocks, and whether any makes increments more nearly i.i.d. than time.

*A Thousand Brains* gives the instruction: the cortex builds its models in
**reference frames**, and the author's gloss is the transferable part - "being
an expert is mostly about finding a good reference frame". This desk has twice
found the frame mattered more than the model:

* `statespace-volume-clock.md` - **volume time** absorbs three-quarters of the
  time-of-day volatility profile. The structure was not in the clock, it was in
  activity;
* `the-ladder-belongs-on-log-volatility` - the same ladder earns +191 to +547
  on 7 of 7 markets in log-volatility space and loses on 5 of 5 controls in
  price space.

So the frames that have not been tried are worth trying. **Range time** closes
a bar each time price has travelled a fixed distance; **imbalance time** closes
one each time the signed intra-bar pressure that `orderflow_from_bars.py`
measures has accumulated to a threshold.

## The measurement has to avoid two traps, and they are different

**A clock cannot be scored on the thing it fixes by construction.** Range time
holds each bar's travel constant, so any range-based volatility measure is
flat in it **tautologically** - the same trap as a conformal PIT, where the rank
of a residual among exchangeable residuals is uniform by definition. Reporting
that range time flattens a range-based volatility profile would be reporting the
definition of range time.

So the score is **close-to-close** return behaviour, which no clock here fixes:

* **kurtosis** of standardised returns. Subordination's claim is that returns
  are closer to i.i.d. Gaussian in the right frame, and a kurtosis of 3 is what
  that would look like;
* **clustering**, the lag-one autocorrelation of squared returns. An i.i.d.
  frame has none, and this is the quantity volatility clustering *is*.

**And likelihoods cannot be compared across clocks at all.** Resampling changes
the observation set, so a density over range bars and one over calendar bars are
different quantities. Everything here is a **ratio or a moment**, which is
scale-free, and the bar counts are matched across clocks so that a kurtosis is
not being compared on 40,000 observations against 4,000.

## The controls

The generated feeds, whose increments are specified. A clock that improves
kurtosis on `Volatility_75_Index` - already a geometric Brownian motion with no
clustering to remove - is improving an artefact, and says the method is wrong
before its answer is read.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
#: The fine frame the clocks are built from. A clock's bar boundary is only as
#: precise as the bars it aggregates, which is the limit `volume_clock.py`
#: records.
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "40000"))
#: Target bars per clock, so every clock is scored on the same count.
TARGET = int(os.environ.get("TARGET", "4000"))
TRADED = tuple(
    os.environ.get("TRADED", "EURUSD,GBPUSD,USDJPY,USDCAD,AUDUSD,XAUUSD,XAGUSD,US_Oil").split(",")
)
GENERATED = tuple(
    os.environ.get(
        "GENERATED", "Volatility_75_Index,Step_Index_200,Boom_500_Index,DEX_900_UP_Index"
    ).split(",")
)


def load(name: str):
    import numpy as np

    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "open", "high", "low", "close", "volume"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
    keep = (got["high"] > got["low"]) & (got["low"] > 0) & (got["volume"] > 0)
    if keep.sum() < 8000:
        return None
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def closes_on(bars, driver, target: int):
    """Closing prices of bars formed by accumulating `driver` to a threshold.

    The threshold is set from the driver's own total and `target`, so every
    clock returns about the same number of bars - which is what makes a
    kurtosis comparable between them.
    """
    import numpy as np

    total = float(np.sum(np.abs(driver)))
    if total <= 0:
        return None
    step = total / max(target, 1)
    out, carried = [], 0.0
    for i, amount in enumerate(driver):
        carried += abs(float(amount))
        if carried >= step:
            out.append(float(bars["close"][i]))
            carried = 0.0
    return np.asarray(out, dtype=float) if len(out) > 500 else None


def shape(closes) -> dict[str, float]:
    """Kurtosis of standardised returns, and clustering of their squares."""
    import numpy as np

    steps = np.diff(np.log(closes))
    steps = steps[np.isfinite(steps)]
    if len(steps) < 500 or steps.std() == 0:
        return {}
    z = (steps - steps.mean()) / steps.std()
    squares = z * z
    centred = squares - squares.mean()
    denominator = float(np.sum(centred * centred))
    return {
        "kurtosis": float(np.mean(z**4)),
        "clustering": (
            float(np.sum(centred[1:] * centred[:-1]) / denominator) if denominator > 0 else 0.0
        ),
        "bars": float(len(closes)),
    }


def main() -> None:
    import numpy as np

    print(f"built from {FRAME}, every clock cut to about {TARGET} bars\n")
    print(
        "Scored on **close-to-close** returns, which no clock here fixes. A\n"
        "clock cannot be judged on the thing it holds constant: range time\n"
        "flattens a range-based volatility measure by construction, the same\n"
        "way a conformal PIT is uniform by definition.\n"
        "\n"
        "kurtosis 3 and clustering 0 are what i.i.d. Gaussian increments give,\n"
        "which is what subordination says the right frame should produce.\n"
    )
    print(
        f"{'instrument':<22}{'clock':<12}{'bars':>7}{'kurtosis':>10}"
        f"{'vs calendar':>13}{'clustering':>12}{'vs calendar':>13}"
    )
    rows = []
    for name in TRADED + GENERATED:
        bars = load(name)
        if bars is None:
            print(f"{name:<22}  no usable bars")
            continue
        logs = np.log(bars["close"])
        steps = np.diff(logs, prepend=logs[0])
        drivers = {
            # One unit of calendar per bar: the baseline, and it reproduces the
            # source series thinned to `TARGET`.
            "calendar": np.ones(len(logs)),
            "volume": bars["volume"],
            # Price travelled, as the bar's own high-low range.
            "range": bars["high"] - bars["low"],
            # Signed intra-bar pressure, unsigned for the accumulation: a bar
            # that closed far from the middle of its range carries more of it.
            "imbalance": np.abs(
                (bars["close"] - bars["open"]) / (bars["high"] - bars["low"])
            ),
            # The plain absolute return, as the control on `range`: if range
            # time only works because range is a volatility proxy, this does
            # the same job and the two agree.
            "absreturn": np.abs(steps),
        }
        base = None
        for label, driver in drivers.items():
            closes = closes_on(bars, driver, TARGET)
            if closes is None:
                continue
            got = shape(closes)
            if not got:
                continue
            if label == "calendar":
                base = got
            made = name in GENERATED
            print(
                f"{('*' + name if made else name):<22}{label:<12}{got['bars']:>7.0f}"
                f"{got['kurtosis']:>10.2f}"
                f"{(got['kurtosis'] / base['kurtosis'] if base else float('nan')):>13.2f}"
                f"{got['clustering']:>12.4f}"
                f"{(got['clustering'] / base['clustering'] if base and base['clustering'] else float('nan')):>13.2f}"
            )
            rows.append({"name": name, "made": made, "clock": label, **got})
        print()

    if not rows:
        return
    print("=" * 110)
    print("medians, as a ratio to the calendar clock on the same instrument")
    print("=" * 110)
    print(f"{'group':<12}{'clock':<12}{'kurtosis':>10}{'ratio':>8}{'clustering':>12}{'ratio':>8}{'cells':>7}")
    for group, made in (("traded", False), ("generated", True)):
        here = [r for r in rows if r["made"] == made]
        if not here:
            continue
        bases = {
            r["name"]: r for r in here if r["clock"] == "calendar"
        }
        for label in ("calendar", "volume", "range", "imbalance", "absreturn"):
            cells = [r for r in here if r["clock"] == label and r["name"] in bases]
            if not cells:
                continue
            print(
                f"{group:<12}{label:<12}"
                f"{statistics.median(c['kurtosis'] for c in cells):>10.2f}"
                f"{statistics.median(c['kurtosis'] / bases[c['name']]['kurtosis'] for c in cells):>8.2f}"
                f"{statistics.median(c['clustering'] for c in cells):>12.4f}"
                f"{statistics.median(abs(c['clustering']) / abs(bases[c['name']]['clustering']) for c in cells if bases[c['name']]['clustering']):>8.2f}"
                f"{len(cells):>7}"
            )
        print()
    print(
        "**The generated rows are the method's own test.** Their increments are\n"
        "specified and already close to i.i.d., so a clock that lowers their\n"
        "kurtosis is improving an artefact rather than removing structure, and\n"
        "nothing in the traded rows can be read until they say the method is\n"
        "sound.\n\n"
        "And `absreturn` is the control on `range`. If range time works only\n"
        "because a bar's range is a volatility proxy, then the plain absolute\n"
        "return does the same job and the two clocks agree - in which case the\n"
        "finding is subordination to volatility and not anything about range."
    )


if __name__ == "__main__":
    main()
