"""How accurate is the forward cone, and does counting ticks beat counting seconds?

`till_infinity/structures/vol/projection.py` returns an *exact* forward law: the
sigma is printed in the instrument's name and `stated.py` verified twelve of
twelve realise it within 0.49%. Exact does not mean accurate, and nothing has
ever measured the gap.

The probability integral transform measures it completely. Push each realised
outcome through the forecast's own CDF and a correct law gives a **uniform**:

* **mean 0.5** - anything else is a drift error;
* **variance 1/12** - anything else is a width error, and `dispersion` reports
  it as a multiple of correct;
* **coverage `level/100`** in each band, which is what a human reads.

Three parameterisations are scored on identical rows, which is the whole point:
a comparison on different bars is not a comparison.

1. **`calendar`** - what the module does today. `sigma * sqrt(T)` with `T` the
   bar's nominal span in seconds.
2. **`ticks`** - `sigma * sqrt(n / N)`, where `n` is the bar's own tick count and
   `N` the ticks a year holds at this feed's publication interval.
   `research/pipeline.md` measured `dt` at **exactly 2000 ms** on the 2s family
   and found **122 missing publications** in 302,421 slots, so a bar does not
   always carry the ticks its span implies - and variance accrues per draw, not
   per second. This is the refinement that finding makes available.
3. **`measured`** - calendar, but with sigma estimated from the training half of
   the series rather than read off the name. The control that says whether the
   published constant is the limiting factor at all.

**Every fit is on the first half and every score on the second.** `measured`
would otherwise be scored against data it was fitted on, and would win by
construction against two parameterisations that fit nothing.

    ./.secrets/lab.sh run research/harness/calibproj.py
"""

from __future__ import annotations

import math
import sys

import numpy as np

from research.harness import seqlab
from research.harness.convention import SECONDS, production_name
from till_infinity.structures.vol import projection as pj


#: Publication interval in seconds, by family. `pipeline.md` measured 2000ms
#: exactly on the standard feeds; the `(1s)` variants publish twice as often.
def tick_seconds(broker: str) -> float:
    return 1.0 if "(1s)" in broker else 2.0


def cells(bars: dict[str, np.ndarray], feed: str, seconds: float, dt: float) -> dict:
    """Score the three parameterisations on one series, train/test split in half."""
    o, c, v = bars["open"], bars["close"], bars["volume"]
    ok = (o > 0) & (c > 0) & np.isfinite(o) & np.isfinite(c)
    o, c, v = o[ok], c[ok], v[ok]
    if len(c) < 400:
        return {}
    half = len(c) // 2
    ret = np.log(c / o)

    named = pj.sigma_for(feed, seconds)
    if named is None:
        return {}
    # Fitted on the first half only.
    fitted = float(np.std(ret[:half], ddof=1))

    # Ticks a year at this publication interval, and the nominal count per bar.
    per_year = pj.SECONDS_PER_YEAR / dt
    nominal = seconds / dt

    out: dict[str, pj.Calibration] = {
        k: pj.Calibration(convention="ito") for k in ("calendar", "ticks", "measured")
    }
    drift = pj.drift_for(feed, seconds, "ito")
    ann = named / math.sqrt(seconds / pj.SECONDS_PER_YEAR)  # back out annual sigma

    for i in range(half, len(c)):
        actual = c[i] / o[i]
        # 1. calendar - the module as it stands today
        out["calendar"].record(pj.cone_at(feed, 1.0, seconds, named, drift), actual)

        # 2. ticks - variance per published draw rather than per second. The bar's
        #    own `volume` is its tick count, and `research/pipeline.md` measured
        #    122 missing publications in 302,421 slots, so a bar does not always
        #    carry the draws its span implies.
        n = float(v[i]) if v[i] > 0 else nominal
        sig_t = ann * math.sqrt(n / per_year)
        out["ticks"].record(pj.cone_at(feed, 1.0, seconds, sig_t, -0.5 * sig_t * sig_t), actual)

        # 3. measured - the same geometry at a sigma fitted on the first half
        out["measured"].record(
            pj.cone_at(feed, 1.0, seconds, fitted, -0.5 * fitted * fitted), actual
        )

    return {
        "n": out["calendar"].n,
        "named_over_fitted": named / fitted if fitted else float("nan"),
        **{
            k: {"pit": v2.mean, "disp": v2.dispersion, "bias": v2.bias_sigma()}
            for k, v2 in out.items()
        },
    }


def main() -> int:
    print("How accurate is the cone, and does counting ticks beat counting seconds?\n")
    print(
        f"{'timeframe':10} {'feeds':>5} {'n':>9}  "
        f"{'calendar disp':>13} {'ticks disp':>11} {'measured disp':>13}  "
        f"{'cal |bias|':>10} {'tick |bias|':>11}"
    )

    grand: dict[str, list] = {}
    for interval in seqlab.GRID:
        seconds = SECONDS[interval]
        rows = []
        for broker in seqlab.VOLATILITY:
            try:
                bars = seqlab.load(broker, interval)
            except Exception:
                continue
            got = cells(bars, production_name(broker), seconds, tick_seconds(broker))
            if got:
                rows.append(got)
        if not rows:
            continue
        n = sum(r["n"] for r in rows)

        def pooled(key: str, stat: str) -> float:
            vals = [r[key][stat] for r in rows if math.isfinite(r[key][stat])]
            return float(np.mean(vals)) if vals else float("nan")

        print(
            f"{interval:10} {len(rows):>5} {n:>9,}  "
            f"{pooled('calendar', 'disp'):>13.4f} {pooled('ticks', 'disp'):>11.4f} "
            f"{pooled('measured', 'disp'):>13.4f}  "
            f"{abs(pooled('calendar', 'bias')):>10.2f} {abs(pooled('ticks', 'bias')):>11.2f}"
        )
        grand[interval] = rows

    print(
        "\ndispersion is band width as a multiple of correct: 1.0000 is right, "
        "below 1 too tight, above 1 too wide."
    )
    print("bias is the mean PIT's distance from 0.5 in standard errors of its own null.\n")

    # Which parameterisation is closest to a uniform, counted over every cell.
    wins = {k: 0 for k in ("calendar", "ticks", "measured")}
    total = 0
    for rows in grand.values():
        for r in rows:
            total += 1
            best = min(wins, key=lambda k: abs(r[k]["disp"] - 1.0))
            wins[best] += 1
    print(f"closest dispersion to 1.0, over {total} cells:")
    for k, n in sorted(wins.items(), key=lambda kv: -kv[1]):
        print(f"  {k:10} {n:>4}  ({n / max(total, 1):.1%})")

    ratios = [
        r["named_over_fitted"]
        for rows in grand.values()
        for r in rows
        if math.isfinite(r["named_over_fitted"])
    ]
    if ratios:
        arr = np.array(ratios)
        print(
            f"\nnamed sigma / fitted sigma: median {np.median(arr):.4f}, "
            f"IQR {np.percentile(arr, 25):.4f}-{np.percentile(arr, 75):.4f}, "
            f"over {len(arr)} cells"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
