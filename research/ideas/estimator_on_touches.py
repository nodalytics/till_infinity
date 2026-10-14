"""Step two: does `Pooled` beat `levels.Kalman` on **touch-spaced** observations?

`docs/specs/2026-10-14-statespace-as-the-structures-library.md` makes this step
two rather than step five, because the estimator is what every later step hangs
off: the band, the barrier probabilities and the activity channel all improve a
thing that is only as good as the level it is attached to.

And it has to be measured on touches rather than on closes. `Pooled` was scored
at **5.6x** on CRPS and then **2.7x** again from `Adapting`, but both were on a
close every bar. The production filter sees something else entirely: a level is
observed only when price **comes to it**, which is irregular, bursty, and
separated by gaps of hours or days. A filter that is excellent on a dense series
can be poor on a sparse one, because the thing that carries it across a gap is
the process noise - and `statespace-activity-on-production-q.md` measured the
production filter wanting a process noise **16,384 times** its constant, which
is the symptom of exactly that.

## In log prices, because the first run was a scale comparison

CRPS is in the units of the thing forecast, so a run on raw prices compares
EURUSD at 1.1 with gold at 2,000 and the synthetics at 5,000 - and the median
over levels is then dominated by whichever instrument is quoted largest. The
first version did exactly that and read a CRPS of **170** on the generated
feeds against **0.0012** on traded, which is a statement about quote
conventions and nothing else.

Everything here is therefore in **log price**, which makes a CRPS a relative
error and comparable across instruments and groups. It is the same correction
`statespace-conditional-quantiles.md` needed, for the same reason: the units
decide whether a comparison means anything.

## Touches, reconstructed rather than replayed

The journal's `closes` extract carries `level` and `zone_high`/`zone_low`, but
it is 1,202 rows of **closed trades** - a selected sample far too thin to fit a
filter on. So touches are reconstructed from bars, which is faithful to what the
production filter sees and uses the whole cache:

* a **level** is a rolling extreme - the highest high or lowest low of the
  previous `LOOKBACK` bars, taken once and then held, which is what a pivot is
  and avoids rebuilding `drawing`'s 3,554 lines to ask a question about the
  estimator;
* a **touch** is a bar whose `[low, high]` contains that level;
* the **observation** is the touch's close, and the **state** is where the level
  has drifted to.

Levels that are never touched are dropped, and a level needs `LEAST_TOUCHES`
before it is scored, because a filter judged on three observations is judged on
its prior.

## The comparison is deliberately generous to the incumbent

`levels.Kalman` takes its process noise per call, so it gets a **grid refit** -
its best case over a wide sweep, the same treatment that revealed the 16,384x.
`Pooled` gets no such sweep: `Adapting` is supposed to find its own, and if it
cannot then that is the result rather than an unfairness.

Both are scored on the predictive density of the **next touch**: `p00 + R` for
the Kalman and `variance + R` for the pool, so each is asked about an
observation rather than about its own state - the omission that
`statespace-river-against-members.md` records as making every filter look
over-confident by exactly that term.

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
from till_infinity.structures.statespace.diagnostics import crps, pit_flatness  # noqa: E402
from till_infinity.structures.statespace.distance import _normal_quantile  # noqa: E402
from till_infinity.structures.statespace.pooling import Pooled  # noqa: E402

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "40000"))
#: Bars a rolling extreme looks back over. A pivot, not a fitted level.
LOOKBACK = int(os.environ.get("LOOKBACK", "100"))
#: Levels taken per instrument, evenly spaced through its history.
PER_FEED = int(os.environ.get("PER_FEED", "40"))
#: Touches a level needs before it is scored at all.
LEAST_TOUCHES = int(os.environ.get("LEAST_TOUCHES", "40"))
#: The production constant, in volatility units per hour.
DRIFT_VOL_PER_HOUR = 0.02
GRID = tuple(float(x) for x in os.environ.get("GRID", "1,8,64,512,4096,16384").split(","))
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
    keep = (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 8000:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    # **Log price**, so a CRPS is a relative error rather than a quote
    # convention. The touch test - does this bar's range contain the level -
    # is unchanged by a monotone transform, so the touches are the same ones.
    for k in ("high", "low", "close"):
        got[k] = np.log(got[k])
    return got


def touch_series(bars):
    """`[(times, prices)]`, one per level that was touched often enough.

    Each level is a rolling extreme taken at one bar and then held fixed, and
    its series is the closes of every later bar whose range contained it. That
    is what a level filter is fed: irregular, bursty, and gappy.
    """
    import numpy as np

    times, highs, lows, closes = (bars[k] for k in ("time", "high", "low", "close"))
    out = []
    starts = np.linspace(LOOKBACK, len(closes) - 1, PER_FEED, dtype=int)
    for i, at in enumerate(starts):
        window = slice(max(at - LOOKBACK, 0), at)
        level = float(highs[window].max() if i % 2 == 0 else lows[window].min())
        # A log price may be negative; only non-finite is disqualifying.
        if not math.isfinite(level):
            continue
        hit = (lows[at:] <= level) & (highs[at:] >= level)
        if hit.sum() < LEAST_TOUCHES:
            continue
        out.append((times[at:][hit], closes[at:][hit]))
    return out


def score_kalman(times, prices, drift: float):
    """Held-out `(loglike/touch, pit, crps)` for the production filter."""
    steps = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    noise = statistics.pstdev(steps) or 1e-9
    one = Kalman(mean=float(prices[0]), variance=noise * noise, updated=float(times[0]))
    start = len(times) // 2
    total, scores, pits = 0.0, [], []
    for i, (when, price) in enumerate(zip(times, prices, strict=True)):
        one.predict(float(when), drift)
        spread = float(one.variance) + noise * noise
        if i >= start and spread > 0:
            mu, sd = float(one.mean), math.sqrt(spread)
            z = (float(price) - mu) / sd
            total += -0.5 * (z * z + math.log(2.0 * math.pi * spread))
            pits.append(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
            scores.append(
                crps([(q, mu + sd * _normal_quantile(q)) for q in QUANTILES], float(price))
            )
        one.update(float(price), noise * noise, float(when))
    if len(scores) < 10:
        return None
    return total / len(scores), pit_flatness(pits), statistics.mean(scores)


def score_pool(times, prices, adapt: bool):
    """The same three, for `Pooled`. No grid: `Adapting` is meant to find it."""
    steps = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    noise = statistics.pstdev(steps) or 1e-9
    one = Pooled(adapt=adapt)
    start = len(times) // 2
    total, scores, pits = 0.0, [], []
    for i, (when, price) in enumerate(zip(times, prices, strict=True)):
        one.predict(float(when))
        spread = float(one.variance) + noise * noise
        if i >= start and spread > 0:
            mu, sd = float(one.value), math.sqrt(spread)
            z = (float(price) - mu) / sd
            total += -0.5 * (z * z + math.log(2.0 * math.pi * spread))
            pits.append(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
            scores.append(
                crps([(q, mu + sd * _normal_quantile(q)) for q in QUANTILES], float(price))
            )
        one.update(float(price), noise * noise, float(when))
    if len(scores) < 10:
        return None
    return total / len(scores), pit_flatness(pits), statistics.mean(scores)


def main() -> None:
    import numpy as np

    print(
        f"frame {FRAME}  lookback {LOOKBACK}  up to {PER_FEED} levels per feed, "
        f"each needing {LEAST_TOUCHES} touches\n"
    )
    print(
        "The Kalman gets a grid refit of its process noise - its best case. The\n"
        "pool gets none: `Adapting` is supposed to find its own, and if it\n"
        "cannot that is the result. Both are scored on the predictive density\n"
        "of the next touch, `p00 + R`, not on their own state's spread.\n"
    )
    print(
        f"{'group':<12}{'levels':>7}{'touches':>9}{'arm':<24}"
        f"{'loglike/touch':>15}{'pit':>9}{'crps':>12}{'pit n':>7}"
    )
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        series = []
        for name in names:
            bars = load(name)
            if bars is None:
                continue
            series.extend(touch_series(bars))
        if not series:
            continue
        counts = [len(p) for _, p in series]
        rows: dict[str, list[tuple[float, float, float]]] = {}
        for times, prices in series:
            # The incumbent at its best over the grid, by held-out loglike.
            best = None
            spread = statistics.pstdev(
                [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
            ) or 1e-9
            for multiple in GRID:
                got = score_kalman(times, prices, spread * DRIFT_VOL_PER_HOUR * multiple)
                if got and (best is None or got[0] > best[0]):
                    best = got
            if best:
                rows.setdefault("levels.Kalman, best grid", []).append(best)
            for label, adapt in (("Pooled(adapt=False)", False), ("Pooled(adapt=True)", True)):
                got = score_pool(times, prices, adapt)
                if got:
                    rows.setdefault(label, []).append(got)
        first = True
        for label in ("levels.Kalman, best grid", "Pooled(adapt=False)", "Pooled(adapt=True)"):
            cells = rows.get(label)
            if not cells:
                continue
            head = (
                f"{group:<12}{len(series):>7}{int(np.median(counts)):>9}"
                if first
                else f"{'':<12}{'':>7}{'':>9}"
            )
            first = False
            pits = [c[1] for c in cells if math.isfinite(c[1])]
            print(
                f"{head}{label:<24}"
                f"{statistics.median(c[0] for c in cells):>15.4f}"
                f"{(statistics.median(pits) if pits else float('nan')):>9.2f}"
                f"{statistics.median(c[2] for c in cells):>12.6f}"
                f"{len(pits):>7}"
            )
        print()
    print(
        "**`Pooled(adapt=False)` is the arm that says where any gain comes\n"
        "from.** If the adapting pool wins and the plain one does not, the gain\n"
        "is the process noise being fitted rather than the members being\n"
        "pooled - which is what every measurement on dense series has said, and\n"
        "which would mean the cheaper change is to fit the incumbent's noise\n"
        "rather than to replace it.\n\n"
        "And the generated block is the control. A level on a driftless walk\n"
        "does not drift, so a filter that wins there by adapting is adapting to\n"
        "noise."
    )


if __name__ == "__main__":
    main()
