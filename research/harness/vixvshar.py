"""VIX against HAR - the comparison `implied.md` never made.

## Why this is the question

`implied.md` measured VIX against `hist`, a **trailing** realised estimate, and
beat it by 12 to 20 points of R-squared. That is this book's `ew` member, and
`ew` is not its best one.

`vixseed.py` then scored all five members as raw point forecasts over 20 years
and found **`har` wins every series** while `vix` is last on half of them. But
that comparison was unfair to VIX in a specific way: the ensemble scores raw
numbers, and VIX systematically exceeds realised volatility - the variance risk
premium - so it is informative and *biased*. A regression removes the bias;
scoring a raw point forecast keeps it.

So neither measurement answers the question that decides whether to build
anything: **does VIX, once its scale is fitted, beat HAR - the incumbent that
actually won?**

## What is compared

All strictly walk-forward: every coefficient is fitted on bars strictly before
the one being predicted, so nothing sees its own answer.

* `har` - this project's own `Har`, the incumbent. Its native task.
* `vix` - the raw converted quote. Known to lose; included as the baseline the
  fit has to improve on.
* `vix_fit` - `a + b * vix`, fitted online. **The proposed member.**
* `har_vix` - `a + b * har + c * vix`. Does VIX add to a forecast, rather than
  to a trailing estimate?
* `mean` - the running mean of realised volatility, so R-squared has a floor
  that is not zero.

Scored two ways, because the two disagreed last time and the disagreement was
the finding:

* **relative error**, symmetric, exactly as `consensus_vol.Score` does it. This
  is what decides ensemble membership.
* **R-squared** against the running mean, which is what `implied.md` reported.

## What would count as a result

`vix_fit` beating `har` on relative error says build the fitted member.
`har_vix` beating `har` says VIX carries information HAR does not, even if it
cannot stand alone. Neither beating `har` ends this line of work for this book.
"""

from __future__ import annotations

import math
import os
import statistics as st

from till_infinity.structures.vol.garch import Garch
from till_infinity.structures.vol.har import Har
from till_infinity.structures.vol.implied import bps_for
from till_infinity.structures.vol.ranges import Ranges
from till_infinity.structures.vol.volatility import Volatility

TICKERS = {"spx500": "^GSPC", "us100": "^NDX", "us30": "^DJI", "us2000": "^RUT"}
CODES = {"1d": "1d", "1w": "1wk"}
INTERVALS = tuple(os.environ.get("INTERVALS", "1d,1w").split(","))
YEARS = os.environ.get("YEARS", "20y")
#: Bars before anything is scored, so every model has a fit worth judging.
WARMUP = int(os.environ.get("WARMUP", "250"))


class Online:
    """Walk-forward least squares. Coefficients from what came before, only."""

    def __init__(self, width: int) -> None:
        self.width = width + 1  # intercept
        self.xtx = [[0.0] * self.width for _ in range(self.width)]
        self.xty = [0.0] * self.width
        self.n = 0

    def observe(self, xs: list[float], y: float) -> None:
        v = [1.0, *xs]
        for i in range(self.width):
            self.xty[i] += v[i] * y
            for j in range(self.width):
                self.xtx[i][j] += v[i] * v[j]
        self.n += 1

    def predict(self, xs: list[float]) -> float | None:
        if self.n < 30:
            return None
        # Ridge-stabilised so a near-singular normal matrix returns a number
        # rather than an exception; the penalty is tiny against the scale here.
        size = self.width
        a = [[self.xtx[i][j] + (1e-6 if i == j else 0.0) for j in range(size)] for i in range(size)]
        b = list(self.xty)
        for i in range(size):
            pivot = max(range(i, size), key=lambda r: abs(a[r][i]))
            if abs(a[pivot][i]) < 1e-12:
                return None
            a[i], a[pivot] = a[pivot], a[i]
            b[i], b[pivot] = b[pivot], b[i]
            d = a[i][i]
            a[i] = [x / d for x in a[i]]
            b[i] /= d
            for r in range(size):
                if r == i:
                    continue
                f = a[r][i]
                if f:
                    a[r] = [x - f * y for x, y in zip(a[r], a[i], strict=True)]
                    b[r] -= f * b[i]
        v = [1.0, *xs]
        return sum(c * x for c, x in zip(b, v, strict=True))


def bars_for(ticker: str, interval: str):
    import yfinance as yf

    got = yf.Ticker(ticker).history(period=YEARS, interval=CODES[interval], auto_adjust=False)
    rows = []
    for when, row in got.iterrows():
        values = [row.get(k) for k in ("Open", "High", "Low", "Close")]
        if any(v is None or math.isnan(v) or v <= 0 for v in values):
            continue
        rows.append((when.timestamp(), *(float(v) for v in values)))
    return rows


def vix_by_day() -> dict[str, float]:
    import yfinance as yf

    got = yf.Ticker("^VIX").history(period=YEARS, interval="1d", auto_adjust=False)
    return {
        str(when.date()): float(row["Close"])
        for when, row in got.iterrows()
        if row.get("Close") and not math.isnan(row["Close"]) and row["Close"] > 0
    }


def relative(predicted: float, actual: float) -> float:
    """`consensus_vol.Score`'s own measure, so this decides membership."""
    return abs(predicted - actual) / (predicted + actual)


def one(feed: str, interval: str, vix: dict[str, float]) -> dict | None:
    import datetime as dt

    rows = bars_for(TICKERS[feed], interval)
    if len(rows) < WARMUP + 100:
        return None

    vol = Volatility(_garch=Garch(), _ranges=Ranges(), _har=Har())
    fit_vix, fit_both = Online(1), Online(2)
    seen = 0
    total = 0.0
    errors: dict[str, list[float]] = {k: [] for k in ("har", "vix", "vix_fit", "har_vix", "mean")}
    truth: list[float] = []
    said: dict[str, list[float]] = {k: [] for k in errors}

    for ts, opened, high, low, close in rows:
        day = dt.datetime.fromtimestamp(ts, dt.UTC).date().isoformat()
        quote = vix.get(day)
        implied = bps_for(quote, interval) if quote else None

        # Everything said *before* this bar is folded in.
        guess = {
            "har": vol._har.predict(),
            "vix": implied,
            "mean": (total / seen) if seen else None,
        }
        if implied is not None:
            guess["vix_fit"] = fit_vix.predict([implied])
            if guess["har"] and guess["har"] > 0:
                guess["har_vix"] = fit_both.predict([guess["har"], implied])

        vol.update(close)
        realised = vol.observe_bar(opened, high, low, close)
        seen += 1
        total += realised

        if seen > WARMUP and realised > 0:
            usable = {k: v for k, v in guess.items() if v is not None and v > 0}
            # Only bars every model could answer, so the comparison is paired.
            if len(usable) == len(errors):
                truth.append(realised)
                for name, value in usable.items():
                    errors[name].append(relative(value, realised))
                    said[name].append(value)

        if implied is not None:
            fit_vix.observe([implied], realised)
            har_now = vol._har.predict()
            if har_now and har_now > 0:
                fit_both.observe([har_now, implied], realised)

    if len(truth) < 100:
        return None
    mean = st.fmean(truth)
    ss = math.fsum((t - mean) ** 2 for t in truth)
    return {
        "n": len(truth),
        "accuracy": {k: 1 - st.fmean(v) for k, v in errors.items()},
        "r2": {
            k: 1 - math.fsum((p - t) ** 2 for p, t in zip(said[k], truth, strict=True)) / ss
            for k in said
        },
    }


def run() -> None:
    vix = vix_by_day()
    print(f"^VIX {len(vix)} closes, {YEARS}, warmup {WARMUP} bars\n")
    names = ("har", "vix", "vix_fit", "har_vix", "mean")
    print(f"  {'feed':>8s} {'iv':>3s} {'n':>5s}  " + "  ".join(f"{n:>8s}" for n in names))

    wins = {n: 0 for n in names}
    for feed in sorted(TICKERS):
        for interval in INTERVALS:
            got = one(feed, interval, vix)
            if got is None:
                continue
            acc = got["accuracy"]
            best = max(acc, key=acc.get)
            wins[best] += 1
            cells = "  ".join(
                f"{acc[n]:8.3f}" + ("*" if n == best else " ") for n in names
            )
            print(f"  {feed:>8s} {interval:>3s} {got['n']:5d}  {cells}")
            r2 = got["r2"]
            print(f"  {'':>8s} {'':>3s} {'R2':>5s}  "
                  + "  ".join(f"{r2[n]:8.3f} " for n in names))

    print("\naccuracy = 1 - symmetric relative error, which is what decides")
    print("ensemble membership. R2 is against predicting the running mean,")
    print("which is what implied.md reported. * marks the best by accuracy.\n")
    print("  wins by accuracy: " + ", ".join(f"{k} {v}" for k, v in wins.items() if v))
    print("\n`vix_fit` beating `har` says build the fitted member. `har_vix`")
    print("beating `har` says VIX carries something HAR does not. Neither")
    print("beating `har` ends this line of work for this book.")


if __name__ == "__main__":
    run()
