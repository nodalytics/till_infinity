"""Allan variance: a clock metrologist's estimator, and what it finds here.

Asked whether chronometry and horology have anything for this package. Most of
the field does not - there is no mechanism by which relativistic or quantum
time affects a price series, and this desk's record with physics metaphors is
six nulls from six. But **one piece fits exactly**: a clock's state is
`(phase, frequency)` and this package's is `(value, rate)`. Same state space,
so clock metrology's noise-identification tool applies without analogy.

The overlapping Allan variance of a phase series `x` at averaging interval `m`
is

    sigma2_y(m) = mean (x[k+2m] - 2 x[k+m] + x[k])^2 / (2 m^2)

and its log-log slope **names the noise type**: `-2` white phase, `-1` white
frequency - which is a random walk in the phase - `0` flicker or `1/f`, `+1`
random-walk frequency, `+2` drift. It was designed precisely because the
sample variance does not converge for `1/f` noise, which is the regime this
desk's volatility turns out to be in.

## Two series, and only the second one has anything in it

**On log price** the answer is `-1` everywhere and nothing else, which is the
walk and is already known.

**On log volatility** it separates traded feeds from constant-volatility ones
at both ends of the interval range, and - the useful part - **dips at the
averaging interval equal to a periodic component's period.** That is a
standard Allan-variance feature: averaging over exactly one period cancels the
periodic part, so the variance falls there. It makes the estimator a
**model-free period finder**, which is what `seasonal.PERIODS` currently has to
be told.

The planted arm is what makes that claim readable rather than suggestive:
inject a known volatility cycle into a Brownian series and the dip has to land
on the period injected, and move when it moves.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

HOUR = 3600.0
SEED = 20261012

TRADED = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "XAUUSD",
    "XAGUSD",
    "BTCUSD",
    "ETHUSD",
)
#: Constant volatility by construction - the calibration for "no cycle".
GENERATED = ("Volatility_75_Index", "Volatility_25_Index", "Volatility_100_Index", "Step_Index")
FRAME = os.environ.get("FRAME", "1h")
#: Averaging intervals in bars. Dense around 24 so the dip is resolved rather
#: than inferred from two rungs either side of it.
TAUS = (
    1,
    2,
    3,
    4,
    6,
    8,
    10,
    12,
    14,
    16,
    18,
    20,
    22,
    24,
    26,
    28,
    32,
    36,
    40,
    48,
    60,
    72,
    96,
    120,
    168,
    240,
    336,
)
#: Bars to smooth `|return|` over before taking its log. One absolute return is
#: a one-observation variance estimate, and its own noise would dominate every
#: short interval if it were used raw.
SMOOTH = int(os.environ.get("SMOOTH", "6"))
SINCE = float(os.environ.get("SINCE", "99792000"))
LIMIT = int(os.environ.get("LIMIT", "40000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def phase(name: str, frame: str = FRAME):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        order = np.argsort(bundle["time"])
        times = np.asarray(bundle["time"], dtype=float)[order]
        closes = np.asarray(bundle["close"], dtype=float)[order]
    keep = (closes > 0) & (times >= SINCE)
    closes = closes[keep]
    if len(closes) < 5000:
        return None
    return np.log(closes[-LIMIT:])


def volatility_phase(x, span: int = SMOOTH):
    """The log-volatility integrated into a phase, as log price is for returns.

    Allan variance measures the noise of a **rate**, so the series it is given
    has to be the integral of the quantity of interest. Log price is the
    integral of returns; this is the integral of log volatility.
    """
    import numpy as np

    moves = np.abs(np.diff(x))
    moves = moves[moves > 0]
    if len(moves) < 8 * span:
        return None
    smooth = np.convolve(moves, np.ones(span) / span, mode="valid")
    return np.cumsum(np.log(smooth))


def allan(x, m: int) -> float:
    import numpy as np

    n = len(x)
    if n < 3 * m + 2:
        return float("nan")
    step = x[2 * m :] - 2.0 * x[m : n - m] + x[: n - 2 * m]
    return float(np.mean(step * step)) / (2.0 * m * m)


def slope(taus, values) -> float:
    import numpy as np

    xs, ys = np.log(np.asarray(taus, dtype=float)), np.log(np.asarray(values, dtype=float))
    good = np.isfinite(xs) & np.isfinite(ys)
    if good.sum() < 3:
        return float("nan")
    return float(np.polyfit(xs[good], ys[good], 1)[0])


def curve(x):
    got = {m: allan(x, m) for m in TAUS}
    return {m: v for m, v in got.items() if math.isfinite(v) and v > 0}


def band(usable, low, high) -> float:
    pick = {m: v for m, v in usable.items() if low <= m <= high}
    return slope(list(pick), list(pick.values())) if len(pick) >= 3 else float("nan")


def dip(usable, period: int, reach: int = 3) -> float:
    """Local value against the geometric trend of its neighbours.

    **Below 1.0 is a dip**, which is the periodic signature: averaging over
    exactly one period cancels the periodic component. `reach` rungs either
    side are used as the trend rather than one, so a single noisy rung cannot
    manufacture or hide the feature.
    """
    keys = sorted(usable)
    if period not in keys:
        return float("nan")
    at = keys.index(period)
    if at < reach or at + reach >= len(keys):
        return float("nan")
    left = [usable[k] for k in keys[at - reach : at]]
    right = [usable[k] for k in keys[at + 1 : at + 1 + reach]]
    trend = math.exp(statistics.fmean(math.log(v) for v in left + right))
    return usable[period] / trend if trend > 0 else float("nan")


def planted(period: int, n: int = 30000, seed: int = SEED):
    """Brownian increments whose **scale** cycles with a known period.

    The arm that makes the claim readable. If the dip is a period finder it has
    to land on the period injected, and move when that moves - and the
    amplitude is deliberately modest so this is not a trivially easy target.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    clock = 1.0 + 0.45 * np.sin(2.0 * math.pi * np.arange(n) / period)
    return np.cumsum(rng.normal(0.0, 1.0, n) * clock)


def main() -> None:
    print(
        f"frame {FRAME}, smoothing {SMOOTH} bars, intervals {TAUS[0]}-{TAUS[-1]}\n"
        "Allan slope names the noise: -1 white frequency (a random walk in the\n"
        "phase), 0 flicker/1-over-f, +1 random-walk frequency. A 'dip' below\n"
        "1.0 at interval m is the signature of a period-m component.\n"
    )

    print("=" * 100)
    print("ARM 1  planted: does the dip land on the period that was injected?")
    print("=" * 100)
    print(f"{'planted period':>16}" + "".join(f"{f'dip@{m}':>10}" for m in (12, 24, 48, 72)))
    for period in (12, 24, 48, 72):
        usable = curve(volatility_phase(planted(period)))
        print(f"{period:>16}" + "".join(f"{dip(usable, m):>10.3f}" for m in (12, 24, 48, 72)))
    print(
        "\nThe diagonal should be the lowest entry in each row. If it is, the\n"
        "dip locates a period without being told one."
    )

    print("\n" + "=" * 100)
    print("ARM 2  on log price: the walk, and nothing else")
    print("=" * 100)
    print(f"{'instrument':<22}{'slope 1-8':>11}{'slope 8-48':>12}{'slope 48-336':>14}{'dip@24':>9}")
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        print(f"--- {group} ---")
        for name in names:
            x = phase(name)
            if x is None:
                continue
            usable = curve(x)
            if len(usable) < 12:
                continue
            print(
                f"{name:<22}{band(usable, 1, 8):>11.2f}{band(usable, 8, 48):>12.2f}"
                f"{band(usable, 48, 336):>14.2f}{dip(usable, 24):>9.3f}"
            )

    print("\n" + "=" * 100)
    print("ARM 3  on log volatility: where the structure is")
    print("=" * 100)
    print(f"{'instrument':<22}{'slope 1-8':>11}{'slope 8-48':>12}{'slope 48-336':>14}{'dip@24':>9}")
    rows: dict[str, list] = {}
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        print(f"--- {group} ---")
        for name in names:
            x = phase(name)
            if x is None:
                continue
            v = volatility_phase(x)
            if v is None:
                continue
            usable = curve(v)
            if len(usable) < 12:
                continue
            got = {
                "short": band(usable, 1, 8),
                "long": band(usable, 48, 336),
                "dip": dip(usable, 24),
            }
            rows.setdefault(group, []).append(got)
            print(
                f"{name:<22}{got['short']:>11.2f}{band(usable, 8, 48):>12.2f}"
                f"{got['long']:>14.2f}{got['dip']:>9.3f}"
            )

    print("\n" + "=" * 100)
    print("ARM 4  the separation")
    print("=" * 100)
    print(
        f"{'group':<12}{'cells':>7}{'med slope 1-8':>15}{'med slope 48-336':>18}"
        f"{'med dip@24':>12}{'share dip<1':>13}"
    )
    for group in ("traded", "generated"):
        cells = rows.get(group, [])
        if not cells:
            continue
        dips = [c["dip"] for c in cells if math.isfinite(c["dip"])]
        print(
            f"{group:<12}{len(cells):>7}"
            f"{statistics.median(c['short'] for c in cells):>+15.2f}"
            f"{statistics.median(c['long'] for c in cells):>+18.2f}"
            + (
                f"{statistics.median(dips):>12.3f}{sum(1 for d in dips if d < 1) / len(dips):>13.2f}"
                if dips
                else f"{'-':>12}{'-':>13}"
            )
        )
    print("\nDONE")


if __name__ == "__main__":
    main()
