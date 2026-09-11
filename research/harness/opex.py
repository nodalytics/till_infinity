"""Do option expiries move the equity indices, with no news to explain it?

The idea under test: **dealer positioning is a force on price that is not
information**. Market makers who are short options hedge with the move and
amplify it; makers who are long options hedge against it and suppress it. Near a
strike with large open interest, and near expiry when gamma is largest, that
hedging is supposed to pin price - and none of it is news, so a model that
watches the tape and the calendar would see the move and never see the cause.

That is a genuine gap in this desk's inputs. `forecasting.md` records that every
volatility model here is a function of the past, and `implied.md` found the one
input that is not - VIX - by going outside the price series. This is the same
move applied to positioning rather than to expectations.

## What can be tested now, and what cannot

**Open interest is a snapshot.** Yahoo serves the *current* option chain and no
history, so "where was the gamma on 14 March 2019" is not answerable from any
free source. The positioning version of this idea needs a collector running
forward for months before it can be measured at all.

**The calendar is free.** Monthly expiry is the third Friday, quarterly expiry -
triple witching, when index futures, index options and stock options all expire
together - is the third Friday of March, June, September and December. Those
dates are computable back to 1928 and need no data.

So this measures the half that can be measured today, and it is the half that
decides whether the other half is worth building. If expiry weeks are
indistinguishable from ordinary weeks in realised volatility and drift, then the
positioning effect is either absent or too small to survive at this desk's
horizon, and a months-long collection project is not justified by anything.

## The controls, because a calendar is the easiest thing in finance to fool
yourself with

There are twelve months, five weekdays, four weeks in a month and two expiry
kinds, and slicing those produces a great many ways to find a p < 0.05. So:

* **A placebo expiry.** The same test run on the **second** Friday of each
  month, which shares the day of week and roughly the month position and has no
  expiry attached to it. Any effect that shows up equally on the placebo is a
  day-of-month effect, not an expiry effect.
* **A split sample.** Pre-2018 proposes, post-2018 disposes. Index option
  volume roughly tripled over the period, so if the mechanism is real the recent
  half should show it at least as strongly - a finding that only exists in the
  older half is the wrong sign for a positioning story.
* **Four indices.** ^GSPC, ^NDX, ^DJI and ^RUT share the mechanism and do not
  share their constituents, so an effect on one and not the others is noise.

## What would count as a finding

Realised volatility on expiry day, or over expiry week, that differs from the
matched non-expiry baseline by enough to survive the placebo and the split. And
the direction matters: **pinning predicts lower** realised volatility into
expiry and **higher** just after, as the hedges come off.

Anything about *drift* is a weaker claim and treated as such here - the measured
shape of this book is that direction is close to unforecastable and width is the
modellable part (`clustering.md`), so a volatility result is the one that could
change sizing and a drift result would need to be very large to change anything.

Usage:  YEARS=25y python3 -m research.harness.opex
"""

from __future__ import annotations

import calendar
import datetime as dt
import math
import os
import statistics as st

import yfinance as yf

INDICES = ("^GSPC", "^NDX", "^DJI", "^RUT")
YEARS = os.environ.get("YEARS", "25y")
#: The split. Index option volume roughly tripled over the window, so the
#: recent half is the one a positioning story has to survive.
SPLIT = os.environ.get("SPLIT", "2018-01-01")


def nth_friday(year: int, month: int, n: int) -> dt.date:
    """The nth Friday of a month. Expiry is the third; the placebo is the second."""
    first = dt.date(year, month, 1)
    ahead = (calendar.FRIDAY - first.weekday()) % 7
    return first + dt.timedelta(days=ahead + 7 * (n - 1))


def series(ticker: str) -> dict[dt.date, float]:
    got = yf.Ticker(ticker).history(period=YEARS, interval="1d", auto_adjust=False)
    out = {}
    for when, row in got.iterrows():
        close = row.get("Close")
        if close is None or math.isnan(close) or close <= 0:
            continue
        out[when.date()] = float(close)
    return out


def marks(days: list[dt.date]) -> tuple[set, set, set]:
    """Expiry Fridays, placebo Fridays, and which expiries are quarterly."""
    expiry, placebo, quarterly = set(), set(), set()
    for year in {d.year for d in days}:
        for month in range(1, 13):
            third = nth_friday(year, month, 3)
            expiry.add(third)
            placebo.add(nth_friday(year, month, 2))
            if month in (3, 6, 9, 12):
                quarterly.add(third)
    return expiry, placebo, quarterly


def around(days, index, rets, mark, offset, since=None, until=None):
    """|return| in basis points, `offset` sessions from each mark."""
    out = []
    for d in days:
        if d not in mark or (since and d < since) or (until and d >= until):
            continue
        j = index[d] + offset
        if 0 <= j < len(days) and days[j] in rets:
            out.append(abs(rets[days[j]]) * 10_000)
    return out


def line(days, index, rets, label, mark, since=None, until=None):
    cells = []
    for offset in (-3, -1, 0, 1, 3):
        got = around(days, index, rets, mark, offset, since, until)
        cells.append(f"{st.median(got):7.1f}" if len(got) > 20 else "      -")
    everything = [
        abs(r) * 10_000
        for d, r in rets.items()
        if (not since or d >= since) and (not until or d < until)
    ]
    base = st.median(everything) if everything else float("nan")
    n = len(around(days, index, rets, mark, 0, since, until))
    print(f"    {label:<22s} {n:>5d} " + " ".join(cells) + f"  {base:7.1f}")


def one(ticker: str, cut: dt.date) -> None:
    prices = series(ticker)
    days = sorted(prices)
    if len(days) < 500:
        print(f"{ticker}: only {len(days)} days\n")
        return
    rets = {}
    for i in range(1, len(days)):
        a, b = prices[days[i - 1]], prices[days[i]]
        if a > 0 and b > 0:
            rets[days[i]] = math.log(b / a)
    expiry, placebo, quarterly = marks(days)
    index = {d: i for i, d in enumerate(days)}

    print(f"{ticker}: {len(days)} sessions, {len(rets)} returns")
    print(
        f"    {'window':<22s} {'n':>5s} {'  -3d':>7s} {'  -1d':>7s} "
        f"{'   0':>7s} {'  +1d':>7s} {'  +3d':>7s}  {'  base':>7s}"
    )
    line(days, index, rets, "monthly expiry", expiry)
    line(days, index, rets, "  quarterly only", quarterly)
    line(days, index, rets, "PLACEBO 2nd Friday", placebo)
    print()
    line(days, index, rets, "monthly, pre-split", expiry, until=cut)
    line(days, index, rets, "monthly, post-split", expiry, since=cut)
    line(days, index, rets, "placebo, post-split", placebo, since=cut)
    print()


def run() -> None:
    print(f"period {YEARS}, split at {SPLIT}\n")
    cut = dt.date.fromisoformat(SPLIT)
    for ticker in INDICES:
        one(ticker, cut)

    print("Median |return| in basis points, by sessions from the mark.")
    print("`base` is the median absolute return over the same window, every day.")
    print("\nPinning predicts **below base** into expiry and **above** after it.")
    print("The placebo row shares the weekday and the month position and has no")
    print("expiry, so anything appearing on both rows is a calendar artefact.")
    print("A result that exists only pre-split is the wrong sign for a story")
    print("about positioning, because option volume grew across the window.")


if __name__ == "__main__":
    run()
