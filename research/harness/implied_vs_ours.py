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
from research.harness.implied_floor import _as_float, floor

#: Seconds in a year, calendar. Crypto trades continuously, so a 252-day trading
#: year would overstate annualised sigma by about 1.9x and make every comparison
#: wrong in the same direction.
YEAR_SECONDS = 365.0 * 24.0 * 3600.0

#: Printed, with a non-zero exit, whenever the run could not produce a score.
#:
#: Kept as a constant and asserted in a test because of what it replaced: a version
#: that announced its own incompleteness only when under five days were recorded, so
#: after exactly the wait the plan prescribed it printed a floor and exited 0 - a
#: clean successful-looking run with no score, at the one moment somebody comes back
#: to read one. A run that has not scored must be impossible to mistake for one that
#: has, however much data is on disk.
NOTHING_SCORED = "nothing could be scored"

#: How far a strike may sit from spot and still be scored, as a fraction.
#:
#: **Measured, not chosen.** Selecting the options whose whole life closed inside a
#: short recording selects the shortest-dated ones, and a strike far from spot with
#: hours to run carries an enormous implied volatility that has nothing to do with
#: forecasting the index - it is the wing of the smile. On 34 hours of real surface
#: the unfiltered scored set had a median `mark_iv` of **173.6%** against realised of
#: **41.4%**, and comparing those two numbers is not a measurement of anything.
#:
#: 5% of spot keeps the strikes whose implied volatility is close to an at-the-money
#: one, which is the only thing a realised estimate is the counterpart of.
MONEYNESS_BAND = 0.05

#: Fewest bars of option life before a window is worth measuring. Twelve, an hour at
#: the recorder's five-minute cadence.
#:
#: **QLIKE is unbounded as realised variance goes to zero**: `a/f - log(a/f) - 1`
#: diverges through the logarithm however good the forecast is. Realised variance over
#: a handful of five-minute bars is frequently near zero, so a mean over such rows is
#: decided by its quietest few. On 34 hours of real surface the mean QLIKE for
#: `mark_iv` read **5,640** while its median implied volatility was 45.7% against
#: realised of 34.4% - two numbers far closer than that loss admits, which is how the
#: pathology announces itself.
MIN_HORIZON_BARS = 12

#: A QLIKE margin smaller than this fraction of the loss itself is a tie.
#:
#: Without it the script reports "ours is ahead by 0.0025" on a loss of 0.238 - a 1%
#: relative margin - in the same words it would use for a real win. A threshold is not
#: a significance test, and it is not offered as one; it is the smallest guard that
#: stops a rounding difference reading as a finding.
TIE_BAND = 0.05

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


def underlying_series(rows: list[dict], underlying: str) -> tuple[np.ndarray, np.ndarray]:
    """The index path for one currency, as `(instants, prices)` sorted by time.

    **Built from the recorded quotes themselves**, not from a bar endpoint, because
    every row carries `underlying_price` - Deribit's own index at that instant, which
    is the series the options actually settle on. Fetching bars from anywhere else
    would introduce a basis between the price the option is written on and the price
    the forecast is scored against, and that basis is not small on crypto.

    Every strike quoted in one sweep carries the same index price, so the path is one
    point per instant rather than one per row.

    The cost is resolution: the path is as fine as the sweep interval, five minutes,
    and no finer. A realised volatility measured on five-minute steps is not the same
    number as one measured on ticks, and the comparison is only fair because
    `mark_iv` is annualised and so is this.
    """
    seen: dict[float, float] = {}
    for row in rows:
        if str(row.get("underlying") or "") != underlying:
            continue
        at = _as_float(row.get("at"))
        price = _as_float(row.get("underlying_price"))
        if not math.isfinite(at) or not math.isfinite(price) or price <= 0.0:
            continue
        seen.setdefault(at, price)
    if not seen:
        return np.array([]), np.array([])
    order = sorted(seen)
    return np.array(order, dtype=float), np.array([seen[k] for k in order], dtype=float)


#: Why one quote could not be scored. `None` means it was.
Reject = str


def _median_loss(actual: np.ndarray, forecast: np.ndarray) -> float:
    """The median per-row QLIKE, on variances, robust to a near-zero realised window."""
    a, f = np.asarray(actual) ** 2, np.asarray(forecast) ** 2
    ok = (a > 0) & (f > 0) & np.isfinite(a) & np.isfinite(f)
    if ok.sum() < MIN_PAIRS:
        return float("nan")
    ratio = a[ok] / f[ok]
    return float(np.median(ratio - np.log(ratio) - 1.0))


def _one(
    row: dict,
    *,
    at: np.ndarray,
    squared: np.ndarray,
    step: float,
    last: float,
) -> tuple[float, float, float] | Reject:
    """One quote as `(realised, mark_iv, ours)` in annualised percent, or why not.

    Split out of `compare` because the rejection reasons are the substance: on a
    short recording almost every quote is rejected, and which reason dominates is
    what tells you whether to keep waiting or to change the method.
    """
    quote_at = _as_float(row.get("at"))
    expiry = _as_float(row.get("expiry"))
    mark_iv = _as_float(row.get("mark_iv"))
    strike = _as_float(row.get("strike"))
    spot = _as_float(row.get("underlying_price"))
    bars = horizon_bars(expiry, quote_at, step)
    if (
        not math.isfinite(quote_at)
        or not math.isfinite(expiry)
        or not math.isfinite(strike)
        or mark_iv <= 0.0
        or spot <= 0.0
        or bars is None
    ):
        return "unusable"

    # The wing of the smile is not a forecast of at-the-money realised volatility.
    # See `MONEYNESS_BAND`.
    if abs(strike / spot - 1.0) > MONEYNESS_BAND:
        return "off_the_money"
    if bars < MIN_HORIZON_BARS:
        return "too_short"
    if expiry > last:
        return "unresolved"

    start = int(np.searchsorted(at, quote_at))
    # A forward window for what happened, and a trailing one of the same length for
    # our estimate. Out of range, or a window with no movement in it at all, is no
    # path rather than a zero forecast.
    if start + bars >= len(squared) or start - bars < 0:
        return "no_path"
    forward = math.sqrt((squared[start + bars] - squared[start]) / bars)
    trailing = math.sqrt((squared[start] - squared[start - bars]) / bars)
    if forward <= 0.0 or trailing <= 0.0:
        return "no_path"
    return (
        annualise(forward, step) * 100.0,
        mark_iv,
        annualise(trailing, step) * 100.0,
    )


def compare(rows: list[dict]) -> dict[str, float]:
    """Score `mark_iv` and a trailing estimate against what the index actually did.

    One row per recorded quote that is near the money and whose whole life closed
    inside the recording. A quote whose option expires after the last sweep is
    **unresolved** and counted separately rather than scored on a half-open window -
    grading a forecast on less time than it forecast is the quiet way to get a wrong
    answer here.

    Both forecasts are annualised percentages, the units `mark_iv` is quoted in, and
    both go through `score` so the loss sees variances.

    **The trailing estimate is a weak opponent and knowingly so.** It is measured on
    the window immediately before the one it is scored against, on the same path, so
    it is correlated with the target in a way an implied volatility quoted days
    earlier is not. It is the folder's standard baseline and it is reported for
    continuity, not as a fair contest. Read `median_mark_iv` against
    `median_realised` first: if those two are not the same order of magnitude,
    nothing else here means anything.
    """
    out: dict[str, float] = {
        "scored": 0,
        "unresolved": 0,
        "no_path": 0,
        "off_the_money": 0,
        "too_short": 0,
        "unusable": 0,
        "qlike_mark": float("nan"),
        "qlike_ours": float("nan"),
        "qlike_mark_median": float("nan"),
        "qlike_ours_median": float("nan"),
        "median_mark_iv": float("nan"),
        "median_realised": float("nan"),
    }
    actual: list[float] = []
    marks: list[float] = []
    ours: list[float] = []

    for underlying in sorted({str(r.get("underlying") or "") for r in rows} - {""}):
        at, price = underlying_series(rows, underlying)
        if len(at) < 3:
            continue
        # The sweep interval from the data rather than from `SWEEP_SECONDS`, so a
        # recording made at another cadence still scores correctly.
        step = float(np.median(np.diff(at)))
        if step <= 0.0:
            continue
        squared = np.concatenate([[0.0], np.cumsum(np.diff(np.log(price)) ** 2)])
        last = float(at[-1])

        for row in rows:
            if str(row.get("underlying") or "") != underlying:
                continue
            got = _one(row, at=at, squared=squared, step=step, last=last)
            if isinstance(got, str):
                out[got] += 1
                continue
            realised, mark_iv, trailing = got
            actual.append(realised)
            marks.append(mark_iv)
            ours.append(trailing)
            out["scored"] += 1

    if actual:
        a = np.array(actual)
        m = np.array(marks)
        o = np.array(ours)
        out["qlike_mark"] = score(a, m)
        out["qlike_ours"] = score(a, o)
        # The median of the per-row loss, which one quiet window cannot move. Where
        # the mean and the median disagree by orders of magnitude, the median is the
        # one describing the population and the mean is describing its tail.
        out["qlike_mark_median"] = _median_loss(a, m)
        out["qlike_ours_median"] = _median_loss(a, o)
        # How you tell a result from a units error.
        out["median_mark_iv"] = float(np.median(m))
        out["median_realised"] = float(np.median(a))
    return out


def read_surface(directory: Path) -> tuple[list[dict], list[Path]]:
    """Every recorded sweep, oldest file first, plus any archive that would not read.

    Delegates to the recorder's `read_surface_safe` rather than reimplementing the
    read: a truncated gzip member raises `EOFError` naming no file, and one
    interrupted write should not make a month of recording unreadable.
    """
    return read_surface_safe(directory)


def _say_floor(bar: dict[str, float]) -> None:
    """Print the detection floor. Split out only to keep `main` legible."""
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
    _say_floor(bar)

    expiries = sorted({float(row["expiry"]) for row in rows})
    stamps = sorted({float(row["at"]) for row in rows})
    span = (stamps[-1] - stamps[0]) / 86400.0 if len(stamps) > 1 else 0.0
    print("\n=== what is recorded")
    print(f"  {len(expiries)} distinct expiries, {len(stamps)} distinct sweep instants")
    print(f"  spanning {span:.2f} days")

    got = compare(rows)
    print("\n=== the comparison")
    print(f"  {got['scored']:,} near-the-money quotes whose whole life closed in the recording")
    print(f"  {got['unresolved']:,} still open at the last sweep, so not scored")
    print(
        f"  {got['off_the_money']:,} more than {100 * MONEYNESS_BAND:.0f}% from spot, so not scored"
    )
    if got["no_path"]:
        print(f"  {got['no_path']:,} with no usable index path around them")
    # The first thing to read. If these two are not the same order of magnitude the
    # numbers below are a units error, not a finding.
    print(
        f"  median mark_iv {got['median_mark_iv']:.1f}%  vs  "
        f"median realised {got['median_realised']:.1f}%"
    )

    if got["scored"] < MIN_PAIRS:
        print(f"\n  {NOTHING_SCORED}: {got['scored']} usable pairs against a floor of {MIN_PAIRS}.")
        print(
            f"  With {span:.2f} days recorded, almost every option's window is still"
            "\n  open. Keep the recorder running - a week is what the plan gates on."
        )
        return 2

    mark, mine = got["qlike_mark_median"], got["qlike_ours_median"]
    print("\n  QLIKE, lower is better. Median per row, not mean:")
    print(f"    mark_iv {mark:.4f}    ours {mine:.4f}")
    print(f"    (means, for comparison: {got['qlike_mark']:.1f} and {got['qlike_ours']:.1f})")
    if got["qlike_mark"] > 10.0 * max(mark, 1e-9):
        print(
            "    The mean is far above the median, so it is describing the quietest few"
            "\n    windows rather than the population. Read the median."
        )
    edge = mark - mine
    scale = max(abs(mark), abs(mine), 1e-12)
    if abs(edge) < TIE_BAND * scale:
        print(
            f"  **A tie.** {edge:+.4f} on a loss of {scale:.4f} is {100 * abs(edge) / scale:.1f}%"
            "\n  relative, which is not a difference. Neither forecast is better here."
        )
        print(
            "  The prior was that implied volatility wins, and a tie is already more than"
            "\n  that predicted - but on this much data it is not evidence of anything."
        )
    elif edge > 0:
        print(f"  Ours is ahead by {edge:.4f}, {100 * edge / scale:.1f}% relative.")
        print(
            "  **That is not yet a result.** The floor above is a cost in premium terms"
            "\n  and this is a variance loss; the two are not in the same units, and"
            "\n  turning a QLIKE margin into an expected return needs the position sizing"
            "\n  this phase deliberately does not have. Treat it as grounds to continue."
        )
    else:
        print(f"  mark_iv is ahead by {-edge:.4f}, which is the prior and the likely answer.")
        print("  If it holds over a week, phase 2 should not be built.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
