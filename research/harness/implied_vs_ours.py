"""Do this desk's volatility forecasts beat Deribit's implied volatility?

    python research/harness/implied_vs_ours.py --surface ~/options-data

**This is the gate for the options programme.** Everything the research folder has
found that works predicts *size*: `crash-timing.md`'s big-move score at AUC
0.65-0.81, `news-volatility.md`'s 2.4x release bar, `implied.md`'s VIX result. None
of it has ever been scored against an option market's own forecast, because there
were no option prices here to score against.

`implied.md` is also the warning. There, the market's volatility index **beat**
our trailing estimates by 12 to 20 points of R-squared. The opponent in this file
is the same kind of object, and the prior should be that it wins.

## The comparison

For each recorded quote, take the option's remaining life as the forecast horizon,
compute what volatility the underlying **actually** realised over that window from
bars, and score two forecasts against it by QLIKE:

* **Deribit's** `mark_iv`;
* **ours** - a trailing estimate over the same horizon, which is the baseline that
  has already beaten a three-state HMM, a 50-neighbour analogue and persistence
  landscapes elsewhere in this folder.

QLIKE rather than squared error because variance loss is asymmetric and squared
error on a variance rewards under-forecasting. It is the loss
`similarity_grid.py`, `regimes.py` and `susceptibility.py` all use.

**On units, corrected 2026-09-24 after review.** Those harnesses pass
**variances** to `qlike`. An earlier version of this docstring claimed they pass
standard deviations, on a misreading of `susceptibility.py:176` - that line is a
`np.sqrt` intermediate which line 197 squares back (`base = x_trail**2 * horizon`)
before anything reaches the loss. `regimes.py:340` and `similarity_grid.py:207` pass
variances too.

The correction matters because **the convention can flip the ranking, not just the
scale**. With an actual sigma of 0.010, a forecast 50% high and one 30% low:

    on standard deviations:  high 0.07213   low 0.07190   -> low wins
    on variances:            high 0.25537   low 0.32747   -> high wins

If those are `mark_iv` and ours, the phase-0 verdict depends on the convention
alone. And `realised_vol` returns a **sigma**, so the natural composition lands on
the wrong side of it. `score` exists so the bar join cannot make that mistake:
it takes sigmas, squares them, and calls `qlike`. Use `score`, not `qlike`.

**Walk-forward, and the floor first.** `implied_floor.floor` is printed before any
score, and a win smaller than it is reported as a null.

## What this cannot establish

Deribit lists BTC and ETH. This desk's best-validated volatility work is on indices
and gold through VIX, so a positive result here is on the underlyings where our
forecasts are **least** proven, and a negative one does not transfer to the
instruments IBKR would reach. That asymmetry belongs in the write-up.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.deribit_recorder import read_surface_safe
from research.harness.implied_floor import floor

#: Seconds in a year, calendar. Crypto trades continuously, so a 252-day trading
#: year would overstate annualised sigma by about 1.9x and make every comparison
#: wrong in the same direction.
YEAR_SECONDS = 365.0 * 24.0 * 3600.0

#: Said on every run until the bar join exists, and the exit status says it too.
#:
#: An earlier version printed this only when under five days were recorded, so after
#: the week the plan gates on it printed a floor and exited 0 - a clean
#: successful-looking run with no score, at exactly the moment somebody comes back
#: to read one. A script that has not done the thing it is named after should be
#: impossible to mistake for one that has.
JOIN_IS_UNWRITTEN = "the bar join is not implemented yet, so nothing has been scored"

#: Fewest paired observations before a QLIKE is reported. The same 200 the other
#: harnesses use, so a thin cell reads as thin rather than as a result.
MIN_PAIRS = 200


def annualise(sigma_per_bar: float, bar_seconds: float) -> float:
    """A per-bar standard deviation as an annualised fraction."""
    if sigma_per_bar <= 0.0 or bar_seconds <= 0.0:
        return float("nan")
    return sigma_per_bar * math.sqrt(YEAR_SECONDS / bar_seconds)


def horizon_bars(expiry: float, at: float, bar_seconds: float) -> int | None:
    """Bars from the quote to the option's expiry, or `None` if that is not forward.

    `None` for anything at or before `at`. Deribit's `expired=false` is a request
    rather than a guarantee, and a negative window does not raise - it scores the
    forecast against a window running backwards. `None` too for a window shorter
    than one bar, which rounds to zero and would score nothing at all.
    """
    if bar_seconds <= 0.0:
        return None
    seconds = expiry - at
    if seconds <= 0.0:
        return None
    bars = int(seconds // bar_seconds)
    return bars if bars >= 1 else None


def realised_vol(closes: np.ndarray, bars: int) -> np.ndarray:
    """Forward realised per-bar sigma over `bars`, aligned to the window's **start**.

    `out[i]` describes the window beginning at `closes[i]`, which is what a quote
    taken at `i` has to be scored against. Aligning to the window's *end* instead
    would be a look-ahead: the forecast would be graded on volatility that had
    already happened when the quote was taken.
    """
    out = np.full(len(closes), np.nan)
    if bars < 2 or len(closes) <= bars:
        return out
    returns = np.diff(np.log(closes))
    squared = returns**2
    # A rolling sum by cumulative difference rather than a loop: the surface is
    # hundreds of thousands of rows and this runs once per distinct horizon.
    cumulative = np.concatenate([[0.0], np.cumsum(squared)])
    window = cumulative[bars:] - cumulative[:-bars]
    out[: len(window)] = np.sqrt(window / bars)
    return out


def qlike(actual: np.ndarray, forecast: np.ndarray) -> float:
    """Variance loss: `a/f - log(a/f) - 1`. Lower is better, zero is perfect.

    Both arguments are **variances**, which is what the other harnesses in this
    folder pass and what the loss is defined on. Prefer `score` below, which takes
    the sigmas everything here actually computes and squares them for you - see the
    module docstring on how getting this backwards flips the ranking.
    """
    ok = (actual > 0) & (forecast > 0) & np.isfinite(actual) & np.isfinite(forecast)
    if ok.sum() < MIN_PAIRS:
        return float("nan")
    ratio = actual[ok] / forecast[ok]
    return float(np.mean(ratio - np.log(ratio) - 1.0))


def score(actual_sigma: np.ndarray, forecast_sigma: np.ndarray) -> float:
    """QLIKE on two **standard deviations**, squared to variances first.

    The one function the bar join should call. `realised_vol` returns a sigma and
    `mark_iv` is quoted as one, so every input here is a sigma while the loss is
    defined on variances - and passing sigmas straight through does not merely
    rescale the answer, it can reverse which forecast wins.
    """
    return qlike(np.asarray(actual_sigma) ** 2, np.asarray(forecast_sigma) ** 2)


def read_surface(directory: Path) -> tuple[list[dict], list[Path]]:
    """Every recorded sweep, oldest file first, plus any archive that would not read.

    Delegates to the recorder's `read_surface_safe` rather than reimplementing the
    read: a truncated gzip member raises `EOFError` naming no file, and one
    interrupted write should not make a month of recording unreadable.
    """
    return read_surface_safe(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", required=True, help="where the recorder wrote")
    args = parser.parse_args(argv)

    rows, broken = read_surface(Path(args.surface).expanduser())
    if broken:
        print(f"skipped {len(broken)} unreadable archive(s):", file=sys.stderr)
        for path in broken:
            print(f"  {path}", file=sys.stderr)
    if not rows:
        print("no recorded surface - run the recorder first", file=sys.stderr)
        return 1

    print(f"{len(rows):,} recorded quotes")
    bar = floor(rows)
    print("\n=== the floor, before any score")
    print(f"  {bar['n']:,} quotes with a usable book")
    print(f"  median round-trip cost: {bar['cost_percent_of_premium']:.2f}% of premium")
    print(f"  mean {100 * bar['mean_cost']:.2f}%, 90th percentile {100 * bar['p90_cost']:.2f}%")
    # Two units, two numbers. They differ by roughly the median mark_iv, and an
    # earlier version printed the same digits under both labels.
    points = bar["iv_points_needed"]
    if not math.isnan(points):
        print(f"  in the units mark_iv is quoted in: {points:.2f} volatility points")
    else:
        print("  volatility points: unavailable, no row carried a mark_iv")
    print("  a win smaller than this is a null, whatever its sign")

    expiries = sorted({float(row["expiry"]) for row in rows})
    stamps = sorted({float(row["at"]) for row in rows})
    print("\n=== what is recorded so far")
    print(f"  {len(expiries)} distinct expiries, {len(stamps)} distinct sweep instants")
    span = (stamps[-1] - stamps[0]) / 86400.0 if len(stamps) > 1 else 0.0
    print(f"  spanning {span:.2f} days")

    print(f"\n  {JOIN_IS_UNWRITTEN}.")
    print(
        "  It needs the underlying's bars over each option's remaining life, joined to"
        "\n  these quotes, and scored with `score` - not `qlike` - because the loss takes"
        "\n  variances and everything here is a sigma."
    )
    if span < 5.0:
        print(
            f"  Under five days recorded ({span:.2f}), so most option windows are still"
            "\n  open and there would be little realised volatility to score against yet."
        )
    # Non-zero, because no score is not a success. See JOIN_IS_UNWRITTEN.
    return 2


if __name__ == "__main__":
    sys.exit(main())
