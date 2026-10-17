"""Do the counted-event features carry anything? Each one, against the nulls.

`inputs.py` gained 48 features on 2026-10-11: rates per hour of **spiking
bodies**, **long wicks** and **confirmed pivots** over every resolvable window,
the EMA of each, and hours since the last of each. They were asked for; none
of them was measured.

A feature that is computed and never scored is the shape this repository keeps
finding - `finding-bugs` #4, computed, published and read by nothing - and the
cost of 48 of them is not zero: every one widens the multiple-comparison
surface for everything built on `Features`.

## The three nulls, which are the ones everything here faces

* **A rotated control.** The same feature circularly shifted by a quarter, a
  half and three quarters of the sample: same distribution, same
  autocorrelation, no alignment. A reading its control matches is a marginal.
* **The trailing standard deviation**, for magnitude. It has beaten a
  three-state HMM, a fifty-neighbour analogue on 0 of 20 cells, an Ising
  susceptibility, a panel of stale forecasts and a rank-then-map model. Every
  magnitude claim is reported **net of it**.
* **The cell count.** 48 features times horizons times series is thousands of
  cells, so the honest reading is the *pattern* - a feature that works should
  work on neighbouring windows and neighbouring instruments, not in one square.

Direction is scored too, and expected to be dead: `informatory-pairs.md` found
at most 6 of 45 bin pairs orderable by their mean signed outcome. It is here
so the expectation is tested rather than assumed.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.statespace.inputs import Features, bar_hours, coverage
from till_infinity.statespace.nulls import control, spearman, trailing

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
    ("btcusd", "BTCUSD"),
)
FRAMES = ("15m", "1h")
HORIZONS = (4.0, 24.0)

SINCE = float(os.environ.get("SINCE", "1262304000"))
LIMIT = int(os.environ.get("LIMIT", "12000"))

#: Prefixes of the features under test. Everything else in `Features` has been
#: measured before.
UNDER_TEST = ("spikes_", "wicks_", "pivots_", "ema_spikes_", "ema_wicks_", "ema_pivots_")


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "open", "high", "low", "close"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: bundle[k][order].tolist() for k in sorted(need)}
    first = 0
    while first < len(got["time"]) and got["time"][first] < SINCE:
        first += 1
    got = {k: v[first:] for k, v in got.items()}
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def logs(prices: list[float]) -> list[float]:
    out, running = [0.0], 0.0
    for i in range(1, len(prices)):
        if prices[i] > 0 and prices[i - 1] > 0:
            running += math.log(prices[i] / prices[i - 1]) * 10_000
        out.append(running)
    return out


def main() -> None:
    print("Do the counted-event features carry anything?")
    print("Each feature scored against a rotated control, and - for magnitude -")
    print("net of a trailing standard deviation. Direction is expected dead.")
    print("A feature that works should work on neighbouring windows and")
    print("neighbouring instruments, not in one square.\n")

    tally: dict[str, list[tuple[float, float, float]]] = {}
    cells = 0
    for _label, stem in SYMBOLS:
        for frame in FRAMES:
            bars = load(stem, frame)
            if bars is None or len(bars["close"]) < 3000:
                continue
            times = bars["time"]
            bar = bar_hours(times)
            if bar <= 0:
                continue
            cover = coverage(times, bar)
            values = logs(bars["close"])
            built = Features(
                times=times,
                closes=bars["close"],
                highs=bars["high"],
                lows=bars["low"],
                opens=bars["open"],
            )
            names = [n for n in built.names() if n.startswith(UNDER_TEST)]
            if not names:
                continue

            for horizon in HORIZONS:
                ahead = max(round(horizon * cover / bar), 1)
                stride = ahead
                start = max(len(values) // 5, 200)
                rows = list(range(start, len(values) - ahead, stride))
                if len(rows) < 300:
                    continue
                sd = trailing(values, max(round(horizon * cover / bar), 2))
                signed = [values[i + ahead] - values[i] for i in rows]
                size = [abs(v) for v in signed]
                vol = [sd[i] for i in rows]
                base = spearman(vol, size)

                for name in names:
                    got = [built.at(i).of(name) for i in rows]
                    if max(got) - min(got) <= 0:
                        continue
                    cells += 1
                    raw = spearman(got, size)
                    null = control(got, size)
                    # Net of the trailing sd: rank-residualise the feature on
                    # it, then correlate. Anything that survives is something
                    # the simplest estimator does not already have.
                    net = partial(got, size, vol)
                    tally.setdefault(name.rsplit("_", 1)[0], []).append((raw - null, net, base))

    print(f"{cells} cells over {len(tally)} feature families.\n")
    print(f"  {'family':<14}{'cells':>7}{'raw-control':>13}{'net of sd':>11}{'|net|>0.05':>12}")
    for family, got in sorted(tally.items()):
        edge = statistics.fmean(v[0] for v in got)
        net = statistics.fmean(v[1] for v in got)
        strong = sum(1 for v in got if abs(v[1]) > 0.05)
        print(f"  {family:<14}{len(got):>7}{edge:>+13.3f}{net:>+11.3f}{strong:>8}/{len(got)}")

    print()
    print("Reading it: 'raw-control' is the feature's rank correlation with")
    print("|move| minus its own rotated control, so zero means a marginal.")
    print("'net of sd' is what survives taking the trailing standard deviation")
    print("out, which is the only column that can justify a new feature.")


def ranked(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    for rank, i in enumerate(order):
        out[i] = float(rank)
    return out


def partial(feature: list[float], target: list[float], given: list[float]) -> float:
    """Spearman of `feature` on `target` with `given` removed from the feature."""
    if len(feature) < 30:
        return float("nan")
    rf, rt, rg = ranked(feature), ranked(target), ranked(given)
    mg, mf = statistics.fmean(rg), statistics.fmean(rf)
    sgg = sum((g - mg) ** 2 for g in rg)
    if sgg <= 0:
        return float("nan")
    beta = sum((f - mf) * (g - mg) for f, g in zip(rf, rg, strict=True)) / sgg
    resid = [f - beta * (g - mg) for f, g in zip(rf, rg, strict=True)]
    mr, mt = statistics.fmean(resid), statistics.fmean(rt)
    num = sum((r - mr) * (t - mt) for r, t in zip(resid, rt, strict=True))
    den = math.sqrt(sum((r - mr) ** 2 for r in resid) * sum((t - mt) ** 2 for t in rt))
    return num / den if den > 0 else float("nan")


if __name__ == "__main__":
    main()
