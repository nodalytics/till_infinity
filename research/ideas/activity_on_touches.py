"""Step four: does activity drive `Q` on **touch-spaced** observations too?

`statespace-activity-on-production-q.md` measured activity on the production
filter's process noise at **+0.0513 per observation on 7 of 8 instruments**, at
exponent **1** rather than the 2 the price members prefer, and concluded the
wiring was a one-line multiply at `levels.py:1244` - the single call site that
supplies `drift_per_hour`.

**That was measured on a close every bar, and step two just showed what that can
cost.** `statespace-estimator-on-touches.md` took `Pooled`, which beat the best
single member by 5.6x on dense closes, and found it **18 times worse** on
touch-spaced observations - a reversal larger than the win. The production
filter's observations are touches, so an activity result on closes is not an
activity result for `levels.py`.

So this re-asks the same question on the same touch series the estimator study
used, before anything is wired.

## What changes on touches, and why it might go either way

**Against the channel:** a level is observed irregularly, so the activity of the
bar carrying the touch may say nothing about the gap that preceded it - and the
gap is where the process noise does its work.

**For it:** the touches themselves cluster, and
`statespace-conformal-filter-band.md` measured how strongly - **65% of the
filter's PIT mass sits in the two central bins** because consecutive bars both
contain the level, so a third of observations are near-duplicates. A busy bar is
exactly when that clustering happens, so activity may be the signal that says
"this touch is one of a burst" - which is a statement about `Q`.

The two readings disagree, which is the reason to measure rather than to assume.

## The arms

The incumbent gets a grid refit of its base process noise first, so the
activity channel is judged on top of a filter that is not mis-set - and then
each exponent is tried on that base. Exponent 1 is the measured one; 0.5 and 2
bracket it, and 2 is what the price members wanted, so its failure here would
be the same split the close-based study found.

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

from till_infinity.structures.levels import Kalman  # noqa: E402
from till_infinity.statespace.behaving import drives_q  # noqa: E402
from till_infinity.statespace.diagnostics import crps  # noqa: E402
from till_infinity.statespace.distance import _normal_quantile  # noqa: E402
from till_infinity.statespace.pacing import Pace  # noqa: E402

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "40000"))
LOOKBACK = int(os.environ.get("LOOKBACK", "100"))
PER_FEED = int(os.environ.get("PER_FEED", "40"))
LEAST_TOUCHES = int(os.environ.get("LEAST_TOUCHES", "60"))
DRIFT_VOL_PER_HOUR = 0.02
GRID = tuple(float(x) for x in os.environ.get("GRID", "1,8,64,512,4096,16384").split(","))
EXPONENTS = tuple(float(x) for x in os.environ.get("EXPONENTS", "0.5,1,2").split(","))
QUANTILES = tuple(i / 20.0 for i in range(1, 20))
TRADED = tuple(os.environ.get("TRADED", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD").split(","))
GENERATED = tuple(os.environ.get("GENERATED", "Volatility_75_Index,Step_Index_200").split(","))


def load(name: str):
    import numpy as np

    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "high", "low", "close"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
        got["volume"] = (
            np.asarray(bundle["volume"], dtype=float)[order]
            if "volume" in bundle
            else np.ones(len(order))
        )
    keep = (got["high"] >= got["low"]) & (got["low"] > 0) & (got["volume"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 8000:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    for k in ("high", "low", "close"):
        got[k] = np.log(got[k])
    return got


def touch_series(bars):
    """`[(times, prices, volumes)]` per level, as the estimator study built them."""
    import numpy as np

    times, highs, lows = bars["time"], bars["high"], bars["low"]
    closes, volumes = bars["close"], bars["volume"]
    out = []
    starts = np.linspace(LOOKBACK, len(closes) - 1, PER_FEED, dtype=int)
    for i, at in enumerate(starts):
        window = slice(max(at - LOOKBACK, 0), at)
        level = float(highs[window].max() if i % 2 == 0 else lows[window].min())
        if not math.isfinite(level):
            continue
        hit = (lows[at:] <= level) & (highs[at:] >= level)
        if hit.sum() < LEAST_TOUCHES:
            continue
        out.append((times[at:][hit], closes[at:][hit], volumes[at:][hit]))
    return out


def score(times, prices, volumes, *, drift: float, exponent: float | None, paced: bool):
    """Held-out `(loglike/touch, crps, mean factor)`."""
    steps = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    noise = statistics.pstdev(steps) or 1e-9
    one = Kalman(mean=float(prices[0]), variance=noise * noise, updated=float(times[0]))
    pace = Pace(exponent=exponent) if (exponent is not None and paced) else None
    start = len(times) // 2
    total, scores, factors = 0.0, [], []
    for i, (when, price, volume) in enumerate(zip(times, prices, volumes, strict=True)):
        scale = 1.0
        if pace is not None and volume > 0:
            pace.update(float(volume))
            scale = pace.factor(float(volume))
            factors.append(scale)
        # A **variance** ratio on a quantity that is a spread, so it enters as
        # a square root - the exponent trap `Profile.factor` documents, in the
        # other direction.
        one.predict(float(when), drift * math.sqrt(scale))
        spread = float(one.variance) + noise * noise
        if i >= start and spread > 0:
            mu, sd = float(one.mean), math.sqrt(spread)
            z = (float(price) - mu) / sd
            total += -0.5 * (z * z + math.log(2.0 * math.pi * spread))
            scores.append(
                crps([(q, mu + sd * _normal_quantile(q)) for q in QUANTILES], float(price))
            )
        one.update(float(price), noise * noise, float(when))
    if len(scores) < 20:
        return None
    return (
        total / len(scores),
        statistics.mean(scores),
        statistics.fmean(factors) if factors else 1.0,
    )


def main() -> None:
    import numpy as np

    print(
        f"frame {FRAME}  {LOOKBACK}-bar extremes, {LEAST_TOUCHES}+ touches, log price\n"
        f"exponents {EXPONENTS}; the base noise is refitted on the undriven arm first\n"
    )
    print(
        "The close-based study measured +0.0513 per observation on 7 of 8 at\n"
        "exponent 1. Step two showed a close-based result can reverse on touch\n"
        "spacing by more than it won by, so this re-asks it where it would be\n"
        "wired.\n"
    )
    labels = ["flat"] + [f"pace {e:g}" for e in EXPONENTS]
    print(
        f"{'group':<12}{'levels':>7}{'gated':>7}"
        + "".join(f"{one:>12}" for one in labels)
        + f"{'mean factor':>13}"
    )
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        rows: dict[str, list[float]] = {}
        crpses: dict[str, list[float]] = {}
        factor, levels, gated = 1.0, 0, 0
        for name in names:
            bars = load(name)
            if bars is None:
                continue
            on = drives_q(name)
            for times, prices, volumes in touch_series(bars):
                levels += 1
                gated += on
                spread = statistics.pstdev(
                    [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
                ) or 1e-9
                best, chosen = None, spread * DRIFT_VOL_PER_HOUR
                for multiple in GRID:
                    drift = spread * DRIFT_VOL_PER_HOUR * multiple
                    got = score(times, prices, volumes, drift=drift, exponent=None, paced=False)
                    if got and (best is None or got[0] > best):
                        best, chosen = got[0], drift
                flat = score(times, prices, volumes, drift=chosen, exponent=None, paced=False)
                if flat is None:
                    continue
                rows.setdefault("flat", []).append(flat[0])
                crpses.setdefault("flat", []).append(flat[1])
                for exponent in EXPONENTS:
                    got = score(
                        times, prices, volumes, drift=chosen, exponent=exponent, paced=on
                    )
                    if got:
                        rows.setdefault(f"pace {exponent:g}", []).append(got[0] - flat[0])
                        crpses.setdefault(f"pace {exponent:g}", []).append(got[1])
                        factor = got[2]
        if not rows:
            continue
        print(
            f"{group:<12}{levels:>7}{gated:>7}"
            + "".join(
                f"{statistics.median(rows[one]):>12.4f}" if one in rows else f"{'-':>12}"
                for one in labels
            )
            + f"{factor:>13.3f}"
        )
        print(
            f"{'':<12}{'':>7}{'crps':>7}"
            + "".join(
                f"{statistics.median(crpses[one]):>12.6f}" if one in crpses else f"{'-':>12}"
                for one in labels
            )
        )
    print(
        "\n**The `flat` column is a level, the `pace` columns are differences\n"
        "from it**, so a positive pace figure is a gain. `crps` is absolute for\n"
        "every arm and is the one that decides: it penalises width and\n"
        "miscalibration together, which is why it survived a diagnostic that\n"
        "PIT did not in `statespace-conformal-filter-band.md`.\n\n"
        "`gated` counts the levels whose feed `behaving.drives_q` allows an\n"
        "activity channel on. On the generated feeds that is zero, so their\n"
        "pace columns must read exactly the flat arm - the control needs no\n"
        "flag and gets none."
    )
    _ = np


if __name__ == "__main__":
    main()
