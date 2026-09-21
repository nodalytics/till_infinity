"""Linear regression channels: revert, follow, or break out?

Run from the repository root:  python research/harness/regression_channel.py

A regression channel is an ordinary least squares line through the last `N` closes with
bands at some multiple of the residual spread. It is one of the few chart tools that is
completely specified - there is no "roughly" anywhere in it - so it can be tested exactly
as written rather than as interpreted.

## Three readings, all of them taught, and they contradict each other

The same drawing is used to justify opposite trades, which is the first thing worth
testing:

* **revert** - price at the lower band is cheap, buy it back towards the line;
* **follow** - the slope is the trend, trade in its direction regardless of position;
* **break** - a close beyond the band has left the channel, trade the escape.

Two of these must be wrong about any given bar, and possibly all three.

## The variants

| band | definition |
|------|------------|
| `sigma` | k times the standard deviation of the residuals - the common one |
| `raff` | the largest absolute residual, so the channel contains every bar |
| `error` | k times the standard error of the regression, which narrows as the fit improves |

And the filter everyone adds: **only trade a well-formed channel**, meaning `R^2` above
some threshold. That is tested as its own dimension rather than assumed to help.

## Why reward-to-risk is fixed at one

`premium_discount.py` measured the 50%-of-range rule and found it tracked `a / (a + b)`
across ten deciles without departing from it - because a rule that places the stop and
target at the edges of a range has its hit rate *determined* by where price sits.

The same trap is waiting here: a revert trade from the lower band to the line has a near
target and a far stop, so it will look accurate whatever happens. So every trade here
uses **stop and target the same distance from entry**, fixed at one true range. Fair odds
is then 50% for every row, geometry cannot explain any result, and the only thing being
measured is direction.

Both barriers inside one bar counts as a stop, as everywhere here, which biases every
number slightly below 50% before anything else happens.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Channel lengths, in bars.
LENGTHS = (50, 100, 200)

#: Band multiples, for the `sigma` and `error` variants.
MULTIPLES = (1.0, 2.0)

#: `R^2` thresholds. 0.0 means unfiltered, so the filter's value is visible as a
#: comparison rather than assumed.
FITS = (0.0, 0.5, 0.8)

#: Risk and reward, in true ranges. Equal, so fair odds is exactly one half.
BARRIER = 1.0

#: Bars allowed to resolve.
HORIZON = 96


def channel(close: np.ndarray) -> tuple[float, float, float, float]:
    """Slope per bar, residual at the last point, residual sigma, and `R^2`.

    The fit uses only the window handed to it, and the window always ends at the
    decision bar - a regression channel drawn through future bars is the single
    easiest way to make this look profitable.
    """
    n = len(close)
    x = np.arange(n, dtype=float)
    x = x - x.mean()
    y = close - close.mean()
    denom = float(x @ x)
    if denom <= 0:
        return 0.0, 0.0, 0.0, 0.0
    slope = float(x @ y) / denom
    resid = y - slope * x
    sigma = float(resid.std(ddof=2)) if n > 2 else 0.0
    total = float(y @ y)
    r2 = 1.0 - float(resid @ resid) / total if total > 0 else 0.0
    return slope, float(resid[-1]), sigma, r2


def resolve(bars: np.ndarray, at: int, side: int, unit: float, horizon: int) -> int:
    high, low, close = bars[:, 2], bars[:, 3], bars[:, 4]
    here = close[at]
    target = here + side * BARRIER * unit
    stop = here - side * BARRIER * unit
    for step in range(1, horizon + 1):
        i = at + step
        if i >= len(bars):
            return 0
        if side > 0:
            hit_t, hit_s = high[i] >= target, low[i] <= stop
        else:
            hit_t, hit_s = low[i] <= target, high[i] >= stop
        if hit_t and hit_s:
            return -1
        if hit_t:
            return 1
        if hit_s:
            return -1
    return 0


def walk(bars: np.ndarray, tr: np.ndarray, horizon: int, every: int, tally: dict) -> int:
    close = bars[:, 4]
    counted = 0
    longest = max(LENGTHS)
    for at in range(longest, len(bars) - horizon, every):
        unit = tr[at] * max(close[at], 1e-12)
        if unit <= 0:
            continue
        for length in LENGTHS:
            window = close[at - length + 1 : at + 1]
            slope, resid, sigma, r2 = channel(window)
            if sigma <= 0:
                continue
            # Band widths, in residual units. `raff` uses the widest residual so the
            # channel contains every bar; `error` narrows as the fit tightens.
            x = np.arange(length, dtype=float)
            x = x - x.mean()
            fitted = slope * x
            residuals = (window - window.mean()) - fitted
            raff = float(np.max(np.abs(residuals)))
            stderr = sigma / np.sqrt(max(length - 2, 1))

            for band, width in (("sigma", sigma), ("raff", raff), ("error", stderr)):
                for mult in MULTIPLES:
                    edge = mult * width
                    if edge <= 0:
                        continue
                    where = resid / edge
                    # Three readings of the same picture.
                    calls = {}
                    if where <= -1.0:
                        calls["revert"] = 1
                        calls["break"] = -1
                    elif where >= 1.0:
                        calls["revert"] = -1
                        calls["break"] = 1
                    calls["follow"] = 1 if slope > 0 else -1

                    for reading, side in calls.items():
                        got = resolve(bars, at, side, unit, horizon)
                        if got == 0:
                            continue
                        for fit in FITS:
                            if r2 >= fit:
                                key = (reading, band, length, mult, fit)
                                tally[key].append(got > 0)
                        counted += 1
    return counted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "gbpusd", "usdjpy"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--horizon", type=int, default=HORIZON)
    ap.add_argument("--every", type=int, default=6)
    args = ap.parse_args()

    tally: dict[tuple, list] = defaultdict(list)
    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<22} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < max(LENGTHS) + args.horizon + 200:
            continue
        tr = candles.true_range(bars)
        n = walk(bars, tr, args.horizon, args.every, tally)
        print(f"{symbol:<22} {n:>9,} scored trades")

    print(
        "\nrisk and reward both one true range, so fair odds is 50.0% everywhere\n"
        f"\n  {'reading':<9}{'band':<7}{'len':>5}{'x':>5}{'R2>=':>6}"
        f"{'n':>10}{'hit':>8}{'excess':>9}{'+/-':>7}"
    )
    rows = []
    for (reading, band, length, mult, fit), got in tally.items():
        if len(got) < 500:
            continue
        won = np.array(got, dtype=float)
        hit = float(won.mean())
        se = float(np.sqrt(hit * (1 - hit) / len(won)))
        rows.append((hit - 0.5, reading, band, length, mult, fit, len(won), hit, 2 * se))

    for excess, reading, band, length, mult, fit, n, hit, w in sorted(rows, reverse=True)[:14]:
        mark = "  <-" if abs(excess) > w else ""
        print(
            f"  {reading:<9}{band:<7}{length:>5}{mult:>5.1f}{fit:>6.1f}"
            f"{n:>10,}{hit:>8.1%}{excess:>+9.2%}{w:>7.2%}{mark}"
        )

    print("\n  worst cells, which matter as much:")
    for excess, reading, band, length, mult, fit, n, hit, w in sorted(rows)[:5]:
        mark = "  <-" if abs(excess) > w else ""
        print(
            f"  {reading:<9}{band:<7}{length:>5}{mult:>5.1f}{fit:>6.1f}"
            f"{n:>10,}{hit:>8.1%}{excess:>+9.2%}{w:>7.2%}{mark}"
        )

    by_reading: dict[str, list] = defaultdict(list)
    for excess, reading, *_rest in rows:
        by_reading[reading].append(excess)
    print()
    for reading, gaps in sorted(by_reading.items()):
        print(f"  {reading:<9} mean excess {np.mean(gaps):>+7.2%} over {len(gaps)} configurations")
    print(
        f"\n  {len(rows)} cells were scored, so about {0.05 * len(rows):.0f} clear a\n"
        "  two-standard-error bar by chance. Read the per-reading means and the\n"
        "  worst cells: a tool whose opposite readings both look positive is being\n"
        "  fitted, and one whose best and worst are symmetric around zero is noise."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
