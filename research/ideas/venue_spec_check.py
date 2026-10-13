"""Do the generated instruments match their advertised process, and do they drift.

This desk trades Deriv's synthetic indices with real money, and the venue
*generates* the price process rather than quoting someone else's. That makes one
question a matter of verification rather than suspicion: **does the delivered
process match the published specification, and is it stable over time?**

It is answerable because the specification is unusually explicit. A
`Volatility_N_Index` is advertised as geometric Brownian motion at `N` percent
annualised volatility, which pins four things that are all measurable:

* **the level** - realised annualised volatility should be about `N`;
* **the shape** - Brownian returns are Gaussian, so kurtosis should sit near 3;
* **the independence** - no autocorrelation in returns;
* **the constancy** - and, the sharpest one, **no volatility clustering.** A
  real market's log-volatility is strongly autocorrelated; constant-volatility
  GBM has none at all. This single number separates "a market" from "the
  advertised process" more cleanly than anything else here.

## What the relationship work already settled

Volatilities across the generated instruments are **mutually uncorrelated** -
median `-0.0133` over 12 pairs, none beating the rotation null - and equally
uncorrelated with every real class. So there is no *common* modulation: nothing
is widening or narrowing volatility across the whole generated book at once,
which is the form a venue-wide intervention would take.

That leaves what a pooled correlation cannot see, and this harness looks at it:
a **single instrument** drifting from its own specification, and **time-local**
deviation that a full-sample statistic dilutes away.

## The drift test is the one that matters

Each instrument's history is cut into windows and the four statistics are
measured in each. A specification is a constant, so **the spread of a statistic
across windows is the evidence**: a process delivered to spec has realised
volatility wandering only as sampling noise allows, and a process being
adjusted does not.

The sampling noise is known rather than assumed. For `n` returns,
`sd(log realised vol)` is about `1/sqrt(2n)`, so each window's deviation can be
expressed in its **own** standard errors and the question becomes whether the
windows scatter more than that. The synthetics are also each other's control
here: whatever the estimator does to one, it does to all.

## And a scan for the unnatural

The last arm asks whether the windows in which instruments deviate **coincide**.
Independent generators drifting for independent reasons deviate at independent
times. A venue-level event - an outage, a feed fault, a change to the engine -
deviates everywhere at once, and that is a different signature from drift.

Reported as the share of instruments simultaneously past two standard errors in
the same window, against what independence would give.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics

import relationship_screen as screen

#: Bars per window. 720 at 1h is a month.
WINDOW = int(os.environ.get("WINDOW", "720"))
#: Hours in a trading year, for annualising. The synthetics quote continuously.
YEAR = float(os.environ.get("YEAR", str(365.0 * 24.0)))
#: Lags of log-volatility autocorrelation to report.
CLUSTER_LAG = int(os.environ.get("CLUSTER_LAG", "1"))
#: Bars per volatility observation inside a window, for the clustering measure.
SPAN = int(os.environ.get("SPAN", "24"))


def advertised(name: str) -> float | None:
    """The annualised volatility a `Volatility_N_Index` name promises, as a fraction."""
    if not name.startswith("Volatility_"):
        return None
    rest = name[len("Volatility_") :].split("_")
    if not rest or not rest[0].isdigit():
        return None
    return float(rest[0]) / 100.0


def statistics_for(values, *, per_year: float):
    """Realised annualised volatility, kurtosis, return and log-vol autocorrelation."""
    import numpy as np

    steps = np.diff(values)
    steps = steps[np.isfinite(steps)]
    if len(steps) < 100:
        return None
    sd = float(steps.std())
    if sd <= 0:
        return None
    out = {
        "realised": sd * math.sqrt(per_year),
        "kurtosis": float((((steps - steps.mean()) / sd) ** 4).mean()),
        "return_acf": float(np.corrcoef(steps[:-1], steps[1:])[0, 1])
        if len(steps) > 3
        else float("nan"),
        "count": len(steps),
    }
    # Volatility clustering: the autocorrelation of log realised volatility
    # over sub-spans. Zero for constant-volatility GBM, large for a market.
    blocks = len(steps) // SPAN
    if blocks >= 8:
        local = steps[: blocks * SPAN].reshape(blocks, SPAN).std(axis=1)
        local = local[local > 0]
        if len(local) >= 8:
            logged = np.log(local)
            out["vol_acf"] = float(
                np.corrcoef(logged[:-CLUSTER_LAG], logged[CLUSTER_LAG:])[0, 1]
            )
    return out


def windowed(series, *, per_year: float):
    """The same statistics per window, so drift is visible as scatter."""
    _, values, _ = series
    out = []
    for start in range(0, len(values) - WINDOW, WINDOW):
        got = statistics_for(values[start : start + WINDOW], per_year=per_year)
        if got is not None:
            got["start"] = start // WINDOW
            out.append(got)
    return out


def main() -> None:
    print(
        f"windows of {WINDOW} bars, annualising on {YEAR:,.0f} hours,\n"
        f"volatility clustering from {SPAN}-bar sub-spans at lag {CLUSTER_LAG}\n"
    )
    names = [n for n in screen.universe(screen.FRAME) if screen.load(n) is not None]
    traded = [n for n in screen.TRADED if screen.load(n) is not None][:6]
    print(f"{len(names)} generated instruments, {len(traded)} traded for comparison\n")

    print("=" * 104)
    print("ARM 1  the advertised level, where it is advertised")
    print("=" * 104)
    print(
        f"{'instrument':<28}{'advertised':>11}{'realised':>10}"
        f"{'ratio':>8}{'windows':>9}{'window sd':>11}{'noise sd':>10}"
    )
    for name in names:
        want = advertised(name)
        if want is None:
            continue
        series = screen.load(name)
        whole = statistics_for(series[1], per_year=YEAR)
        parts = windowed(series, per_year=YEAR)
        if whole is None or len(parts) < 3:
            continue
        logs = [math.log(p["realised"]) for p in parts if p["realised"] > 0]
        # What sampling noise alone would give: sd(log vol) ~ 1/sqrt(2n).
        noise = 1.0 / math.sqrt(2.0 * statistics.mean(p["count"] for p in parts))
        print(
            f"{name:<28}{want:>11.3f}{whole['realised']:>10.3f}"
            f"{whole['realised'] / want:>8.3f}{len(parts):>9}"
            f"{statistics.stdev(logs) if len(logs) > 1 else float('nan'):>11.4f}"
            f"{noise:>10.4f}"
        )
    print(
        "\n`window sd` is the scatter of log realised volatility across windows\n"
        "and `noise sd` is what sampling alone permits. A specification is a\n"
        "constant, so the first materially exceeding the second is drift."
    )

    print("\n" + "=" * 104)
    print("ARM 2  the shape, the independence and the clustering")
    print("=" * 104)
    print(
        "GBM promises kurtosis 3, return autocorrelation 0 and **no volatility\n"
        "clustering at all**. The traded rows are there to show what a market\n"
        "looks like on the same estimator.\n"
    )
    print(
        f"{'instrument':<28}{'kurtosis':>10}{'return acf':>12}"
        f"{'vol acf':>10}{'class':>12}"
    )
    rows = []
    for name in names:
        got = statistics_for(screen.load(name)[1], per_year=YEAR)
        if got is not None:
            rows.append((name, got, "generated"))
    for name in traded:
        got = statistics_for(screen.load(name)[1], per_year=YEAR)
        if got is not None:
            rows.append((name, got, "traded"))
    for name, got, label in rows:
        print(
            f"{name:<28}{got['kurtosis']:>10.3f}{got['return_acf']:>+12.4f}"
            f"{got.get('vol_acf', float('nan')):>+10.4f}{label:>12}"
        )
    for label in ("generated", "traded"):
        here = [g for _, g, k in rows if k == label and math.isfinite(g.get("vol_acf", float("nan")))]
        if here:
            print(
                f"\n{label:<12}median kurtosis "
                f"{statistics.median(g['kurtosis'] for g in here):>7.3f}   "
                f"median vol acf {statistics.median(g['vol_acf'] for g in here):>+7.4f}"
            )

    print("\n" + "=" * 104)
    print("ARM 3  do the deviations coincide, which drift does not and an event does")
    print("=" * 104)
    per_window: dict[int, list[float]] = {}
    for name in names:
        series = screen.load(name)
        parts = windowed(series, per_year=YEAR)
        if len(parts) < 4:
            continue
        logs = [math.log(p["realised"]) for p in parts if p["realised"] > 0]
        if len(logs) < 4:
            continue
        middle = statistics.median(logs)
        for part in parts:
            if part["realised"] <= 0:
                continue
            noise = 1.0 / math.sqrt(2.0 * part["count"])
            per_window.setdefault(part["start"], []).append(
                (math.log(part["realised"]) - middle) / noise
            )
    if not per_window:
        print("  not enough windows")
        return
    print(f"{'window':>8}{'instruments':>13}{'share past 2 se':>18}{'median z':>11}")
    shares = []
    for start in sorted(per_window):
        here = per_window[start]
        if len(here) < 4:
            continue
        share = sum(1 for v in here if abs(v) > 2.0) / len(here)
        shares.append(share)
        print(
            f"{start:>8}{len(here):>13}{share:>18.3f}"
            f"{statistics.median(here):>+11.3f}"
        )
    if shares:
        print(
            f"\nmedian share past 2 se across windows: {statistics.median(shares):.3f}"
        )
        print(
            "Under independence the share is roughly constant from window to\n"
            "window. A window where nearly every instrument deviates at once is\n"
            "the signature of something done to all of them, not of drift."
        )


if __name__ == "__main__":
    main()
