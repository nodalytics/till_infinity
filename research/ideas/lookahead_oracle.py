"""Give the models a glimpse of the future on purpose. Does the machinery work?

Asked on 2026-10-11, and it is the right diagnostic after a session of null
results. Every negative finding so far has two possible explanations and the
measurements cannot tell them apart:

* **there is no signal in the data** - the series is a martingale and nothing
  could have found direction in it
* **the models cannot use the signal** - something is there and this machinery
  is the wrong shape to see it

**Deliberate lookahead separates them.** A model handed the future should do
well. If it does, the machinery is sound and the problem is the information, so
the work belongs in finding better information. If it *still* does badly, the
model is misspecified and no amount of data will rescue it.

This is a ceiling, not a strategy. Nothing here is tradeable by construction -
that is the point of it.

## Four levels of cheating

1. **The smoother**, which is honest hindsight and already in the library.
   `smoothing.smooth` conditions on *every* measurement, so its estimate at bar
   `k` uses bars after `k`. Filter against smoother at the same point is the
   cheapest glimpse test there is, and it needs no new code - only the
   discipline to label it as cheating.
2. **A `k`-bar leak.** Feed the member bars `k+1 ... k+leak` before asking it to
   predict `k+h`. Sweeping `leak` from 0 upward is a dial on how much future is
   needed before the forecast improves, which is the quantity that answers the
   question.
3. **A direction oracle.** Trade on `sign(value[k+h] - value[k])`, known in
   advance. This is the ceiling on any directional strategy at that horizon -
   and the sharp version of the cost question: **at 3m, does even perfect
   direction clear the spread?** If it does not, the timeframe is untradeable
   however good the model, and no further modelling work on it is justified.
4. **A volatility oracle.** Rank by the realised `|move|` over the next `h`
   bars, known in advance, against ranking by recent speed - which scored a
   3.12x spread between extreme quintiles. The gap between the two is how much
   of the forecastable volatility is already being captured.

Runs on the lab. Production has two cores and a 2.6GB container limit, and
research on it OOM-killed the live desk three times - see `research/starving.md`.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.structures.statespace.linear import Gaussian
from till_infinity.structures.statespace.reverting import Reverting
from till_infinity.structures.statespace.smoothing import smooth
from till_infinity.structures.statespace.swarm import Swarm

SYMBOLS = (("eurusd", "EURUSD"), ("xauusd", "XAUUSD"), ("v75", "Volatility_75_Index"))
FRAMES = ("15m", "1h", "1d")
HORIZONS = (1, 5, 20)
LEAKS = (0, 1, 2, 5, 20)

LIMIT = int(os.environ.get("LIMIT", "4000"))
NOISE = float(os.environ.get("NOISE", "0.16"))


def tick_size(closes: list[float]) -> float:
    positive = [
        abs(closes[i] - closes[i - 1])
        for i in range(1, len(closes))
        if closes[i] != closes[i - 1]
    ]
    return min(positive) if positive else 0.0


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = bundle["time"][order].tolist()
        closes = bundle["close"][order].tolist()
        spreads = (
            bundle["spread"][order].tolist() if "spread" in bundle else [0.0] * len(closes)
        )
    if len(closes) > LIMIT:
        times, closes, spreads = times[-LIMIT:], closes[-LIMIT:], spreads[-LIMIT:]
    return times, closes, spreads


def normalise(closes: list[float]) -> tuple[list[float], float]:
    alpha = 1.0 - 0.5 ** (1.0 / 60.0)
    average = 0.0
    for i in range(1, len(closes)):
        move = abs(closes[i] - closes[i - 1]) / closes[i - 1] * 10_000
        average = move if i == 1 else average + alpha * (move - average)
    bps = max(average, 0.25)
    return [(c / closes[0] - 1.0) * 10_000 / bps for c in closes], bps * closes[0] / 10_000


def members():
    return {
        "linear": lambda: Gaussian(jerk=1e-4),
        "reverting": lambda: Reverting(theta=0.5, sigma2=0.5),
        "swarm": lambda: Swarm(drift=0.5413, wander=0.1, noise=1.0),
    }


def leaked(build, times, values, horizon: int, leak: int) -> tuple[float, float]:
    """`(rmse, coverage)` when the member is fed `leak` bars past the decision.

    At `leak = 0` this is the honest causal forecast. Above it, the member has
    seen bars it could not have seen, which is the whole point: the improvement
    is the value of information rather than the value of the model.
    """
    engine = build()
    errors: list[float] = []
    inside: list[float] = []
    for k in range(len(values) - horizon - leak - 1):
        engine.predict(times[k])
        engine.update(values[k], NOISE, times[k])
        if k < 30:
            continue
        # The cheat: a *copy* would be cleaner, but the members have no copy and
        # a fresh run per bar is quadratic. Instead the leak is applied to a
        # throwaway rebuild over the recent window, which sees the leaked bars
        # and nothing else beyond them.
        if leak > 0:
            peek = build()
            lo = max(0, k - 200)
            for j in range(lo, k + leak + 1):
                peek.predict(times[j])
                peek.update(values[j], NOISE, times[j])
            guess = peek.at_time(times[k + horizon])
            low, high = peek.band(times[k + horizon])
        else:
            guess = engine.at_time(times[k + horizon])
            low, high = engine.band(times[k + horizon])
        truth = values[k + horizon]
        errors.append((truth - guess) ** 2)
        inside.append(1.0 if low <= truth <= high else 0.0)
    if not errors:
        return float("nan"), float("nan")
    return math.sqrt(statistics.fmean(errors)), statistics.fmean(inside)


def main() -> None:
    print("Deliberate lookahead: a ceiling, not a strategy.")
    print(f"noise={NOISE} (a variance, per the Filter contract), {LIMIT} bars a series\n")

    for label, stem in SYMBOLS:
        for frame in FRAMES:
            loaded = load(stem, frame)
            if loaded is None:
                continue
            times, closes, spreads = loaded
            if len(closes) < 600:
                continue
            values, unit = normalise(closes)
            tick = tick_size(closes)
            points = [s for s in spreads if s > 0]
            spread_vol = (
                statistics.median(points) * tick / unit if points and tick > 0 else 0.0
            )
            moves = [0.0] + [values[k] - values[k - 1] for k in range(1, len(values))]

            print(f"=== {label} {frame}: {len(values)} bars, spread {spread_vol:.3f} vol units ===")

            # 1. the smoother, which is hindsight already in the library.
            #
            # **This arm measures the wrong target and is kept only as a
            # warning.** It compares each estimate to the *measurement*, and a
            # smoother's job is to sit further from a noisy reading than the
            # filter does - so a good smoother scores *worse* here, which is
            # why ratios below 1.0 come out of it. A member that merely copies
            # the reading wins it outright. The only meaningful version
            # compares against the latent truth, which is unobservable on real
            # data: `paths.simulate` generates a path with known states and is
            # where this belongs.
            print("  1. filter against smoother - WRONG TARGET, see the comment")
            for name, build in members().items():
                got = smooth(build, tuple(times), tuple(values), noise=NOISE)
                if got is None:
                    print(f"     {name:<12} not smoothable")
                    continue
                filtered = [abs(f - v) for f, v in zip(got.filtered, values, strict=True)]
                smoothed = [row[0] for row in got.states]
                hind = [abs(sm - v) for sm, v in zip(smoothed, values, strict=True)]
                print(f"     {name:<12} filtered |error| {statistics.fmean(filtered):7.3f}"
                      f"   with hindsight {statistics.fmean(hind):7.3f}"
                      f"   -> {statistics.fmean(filtered) / max(statistics.fmean(hind), 1e-9):5.2f}x better")

            # 2. the leak dial
            print("  2. a leak of k bars before forecasting h ahead (rmse, coverage)")
            for horizon in HORIZONS:
                row = []
                for leak in LEAKS:
                    rmse, cover = leaked(members()["reverting"], times, values, horizon, leak)
                    row.append(f"{rmse:6.2f}/{cover:4.0%}")
                print(f"     h={horizon:<3} " + "  ".join(
                    f"leak={leak}: {cell}" for leak, cell in zip(LEAKS, row, strict=True)
                ))

            # 3. the direction oracle, and whether it clears the spread
            print("  3. a PERFECT direction oracle - the ceiling, against the spread")
            for horizon in HORIZONS:
                got = []
                for k in range(len(values) - horizon):
                    move = values[k + horizon] - values[k]
                    got.append(abs(move))  # perfect direction earns the whole move
                mean = statistics.fmean(got)
                print(f"     h={horizon:<3} perfect direction earns {mean:7.3f} vol units"
                      f"   = {mean / max(spread_vol, 1e-9):8.1f} spreads"
                      f"   {'TRADEABLE' if mean > spread_vol else 'BELOW COST'}")

            # 4. the volatility oracle against recent speed
            print("  4. ranking by realised future vol, against ranking by recent speed")
            for horizon in HORIZONS:
                rows = []
                for k in range(21, len(values) - horizon):
                    speed = statistics.fmean(abs(v) for v in moves[k - 19 : k + 1])
                    future = abs(values[k + horizon] - values[k])
                    rows.append((speed, future))
                n = len(rows)
                by_speed = sorted(rows, key=lambda r: r[0])
                by_truth = sorted(rows, key=lambda r: r[1])
                def ratio(ordered):
                    lo = statistics.fmean(r[1] for r in ordered[: n // 5])
                    hi = statistics.fmean(r[1] for r in ordered[4 * n // 5 :])
                    return hi / max(lo, 1e-9)
                got_speed, got_oracle = ratio(by_speed), ratio(by_truth)
                share = (got_speed - 1.0) / max(got_oracle - 1.0, 1e-9)
                print(f"     h={horizon:<3} recent speed {got_speed:5.2f}x"
                      f"   perfect foresight {got_oracle:6.2f}x"
                      f"   -> speed captures {share:5.1%} of the ceiling")
            print()


if __name__ == "__main__":
    main()
