"""Which feeds can clear the surprise trigger at all, measured rather than assumed.

`SurpriseProfile.feeds` admits eight instruments and the comment beside it is
explicit about why the list is a measurement and not a preference: crypto is in
because the production fold fires on **2.11%** of BTCUSD bars against **1.80%**
on the majors, and the Deriv synthetics are out because over 4,725 readouts
`|surprise|` never reached 2.5 against a trigger of 3.0 - "admitting them would
add desks that cannot fire, which is the state 26 of 32 desks were in before
this comment existed."

So the live situation is not a bug. Of 163 desk slots the node builds, 76
decline to register and the largest group declines on this allowlist. That is
the allowlist working.

**What was never measured is everything else in `TRADING_SYMBOLS`.** Silver,
the Swiss and antipodean majors and five crosses sit in the live book and have
never been put through the fold, so they are excluded by *omission* rather than
by measurement. This file measures them, beside the eight that are already in
as a reference group and the synthetics as a negative control whose answer is
known in advance.

## What it measures

For each feed, the production fold (`statespace.facade.Desk.read`, the same
object the live node uses) is run bar by bar over 15-minute bars, and the
`|surprise|` series is kept. Reported per feed:

* **rate** - the share of bars at or above `TRIGGER`. This is the number the
  allowlist turns on: a feed that cannot reach the trigger produces a desk that
  cannot fire.
* **max** and **q99** - how far the distribution reaches. The synthetics'
  failure is visible here as a max *below* the trigger rather than as a low
  rate, and the two are different diagnoses.
* **noise swept** at 0.5, 1.0 and 2.0 times a quarter of each bar's log range,
  because the standardised innovation is a ratio and the measurement noise is
  its denominator. A rate quoted at one noise level says nothing about another,
  and the production path's noise is not a constant.

## What would justify an addition

A candidate's rate landing inside the reference group's range at the same
noise. Not "above zero": a feed firing on 0.1% of bars gives a desk that
fires nine times a year and cannot be judged. `pool-events-before-a-per-feed-guard`
is the standing warning about per-feed thresholds on thin counts.

**This does not open the synthetics.** Their exclusion stands on its own
measurement, and the route for them is a per-family trigger on the residual
deque's empirical quantile at a target rate - the rate-matched conversion being
1.446 on the synthetics is 3.0 on a real market - which needs a planted-effect
power check and a placebo arm. That is a separate piece of work.

Run as:

    uv run python research/ideas/surprise_reach.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_layer import load

from till_infinity.statespace.facade import Desk
from till_infinity.statespace.proposing import TRIGGER

FRAME = "15m"
BARS = 40_000
NOISES = (0.5, 1.0, 2.0)

#: Already admitted, as the reference. `ethusd` has no cached series here.
REFERENCE = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "XAUUSD", "BTCUSD")

#: In `TRADING_SYMBOLS`, never measured through the fold.
CANDIDATES = ("XAGUSD", "USDCHF", "NZDUSD", "AUDCAD", "EURAUD", "AUDNZD", "EURCAD")

#: The negative control. Known to fail; here so a run that reported every feed
#: as admissible would be visibly wrong rather than quietly believed.
CONTROL = ("Volatility 75 Index", "Volatility 25 Index", "Step Index", "Jump 75 Index")


def reach(bars: dict, feed: str, noise: float) -> np.ndarray:
    """`|surprise|` for every bar, through the production fold."""
    price = np.log(np.maximum(bars["close"], 1e-12))
    high = np.log(np.maximum(bars["high"], 1e-12))
    low = np.log(np.maximum(bars["low"], 1e-12))
    span = np.maximum(high - low, 1e-9)
    desk = Desk()
    out = np.full(price.size, np.nan)
    for i in range(price.size):
        got = desk.read(
            feed,
            FRAME,
            float(bars["time"][i]),
            float(price[i]),
            float((noise * span[i] / 4.0) ** 2),
            volume=float(bars["volume"][i]) if "volume" in bars else 0.0,
        )
        value = getattr(got, "surprise", None)
        if value is not None and np.isfinite(value):
            out[i] = abs(float(value))
    return out[np.isfinite(out)]


def main() -> None:
    print(
        f"Can a feed reach the trigger at all? {FRAME} bars, up to {BARS:,} each,\n"
        f"through statespace.facade.Desk - the production fold. TRIGGER = {TRIGGER}.\n"
        "A desk on a feed whose distribution stops below the trigger can never fire."
    )
    groups = (("already in", REFERENCE), ("candidate", CANDIDATES), ("control", CONTROL))
    series = {}
    for _, names in groups:
        for name in names:
            got = load(name, FRAME)
            if got is not None:
                series[name] = {k: np.asarray(v, dtype=float)[-BARS:] for k, v in got.items()}
    print(f"  {len(series)} of {sum(len(n) for _, n in groups)} feeds cached\n")

    for noise in NOISES:
        print("=" * 86)
        print(f"noise {noise} x range/4")
        print("=" * 86)
        print(
            f"  {'group':<11}{'feed':<22}{'bars':>8}{'rate':>9}{'q99':>8}{'max':>8}{'verdict':>12}"
        )
        rates: dict[str, list[float]] = {}
        for group, names in groups:
            for name in names:
                bars = series.get(name)
                if bars is None:
                    continue
                values = reach(bars, name, noise)
                if values.size < 500:
                    continue
                rate = float(np.mean(values >= TRIGGER))
                top = float(values.max())
                q99 = float(np.quantile(values, 0.99))
                rates.setdefault(group, []).append(rate)
                verdict = "cannot fire" if top < TRIGGER else ""
                print(
                    f"  {group:<11}{name:<22}{values.size:>8,}{100 * rate:>8.2f}%"
                    f"{q99:>8.2f}{top:>8.2f}{verdict:>12}"
                )
        inside = rates.get("already in") or [0.0]
        low, high = min(inside), max(inside)
        print(
            f"  reference band {100 * low:.2f}% to {100 * high:.2f}%; "
            f"a candidate inside it is admissible on this measurement"
        )
        print()


if __name__ == "__main__":
    main()
