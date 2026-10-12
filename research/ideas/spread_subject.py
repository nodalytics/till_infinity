"""The spread as a filtered subject, against a trailing average.

`subjects.SPREAD` has existed since the package began, with `member="reverting"`
and both its parameters marked placeholder, and nothing has ever measured it.
Meanwhile every cost gate in the repository uses a **constant** spread - 1.5 of
them, multiplied by one number per instrument - and the SEC order-flow paper's
whole finding is that the number moves with the composition of the flow.

Tick stores make this measurable for the first time: the broker's own bid and
ask, rather than a spread field averaged into a bar.

## What the subject's own provenance asks for

> `noise` is about how well a bar's recorded spread represents the spread that
> would have been paid, which is a question about the feed rather than about
> the market. **Roll's implied spread** from the serial covariance of price
> changes is the independent estimate, and the disagreement between the two is
> itself a measurement: the broker's number is the one the desk is charged.

So three things, in that order: the spread's own dynamics, a filter against
the trailing average, and Roll's estimate beside the quoted one.

## Why the logarithm

A spread cannot be negative and it moves multiplicatively - a quiet hour and a
news minute differ by a factor, not by an amount. So the subject is filtered
on `log(spread)`, which makes the member's Gaussian assumption defensible and
its band a ratio. Filtering the spread directly would put mass below zero and
make the band meaningless at the tight end, which is exactly the end a cost
gate cares about.

## The null is hard and it is the right one

**A trailing average of the spread.** Spreads are strongly persistent, so this
is not a straw man: the honest question is whether a filter's extra machinery
buys anything over "it is about what it was". `nulls.py` calls the trailing
standard deviation "the one nothing here has beaten" for magnitudes, and a
trailing *mean* for the spread is the same shape of null.

Scored two ways, because they answer different questions:

* **held-out likelihood**, which says whether the filter is a better model;
* **mean absolute error in spread units**, which says whether a cost gate set
  from it would be more accurate - and that is the number the desk would feel.

Runs on the lab.
"""

from __future__ import annotations

import itertools
import math
import os
import statistics
from pathlib import Path

HOUR = 3600.0

TRADED = ("XAUUSD", "BTCUSD")
GENERATED = (
    "Volatility_75_Index",
    "Volatility_100_Index",
    "Step_Index",
    "Boom_500_Index",
)

#: Interval over which one spread observation is formed, in seconds.
WINDOW = int(os.environ.get("WINDOW", "60"))

#: Trailing windows to try for the null, in observations.
TRAILS = (5, 10, 20, 60, 240)

LEAST_TICKS = 5
TICKS = Path.home() / "till_infinity" / "data" / "seqlab" / "ticks"


def load(name: str):
    import numpy as np

    path = TICKS / f"{name}.tick.npz"
    if not path.exists():
        return None
    try:
        with np.load(path) as bundle:
            if not {"time", "bid", "ask"} <= set(bundle.keys()):
                return None
            order = np.argsort(bundle["time"])
            times = np.asarray(bundle["time"], dtype=float)[order]
            bids = np.asarray(bundle["bid"], dtype=float)[order]
            asks = np.asarray(bundle["ask"], dtype=float)[order]
    except Exception:
        return None
    keep = (bids > 0) & (asks >= bids)
    return times[keep], bids[keep], asks[keep]


def observations(times, bids, asks, seconds: int):
    """One spread observation per interval, with the mid path beside it.

    The spread is the **median** quoted spread inside the interval rather than
    the mean, because a single crossed or stale quote moves a mean and a desk
    pays the typical one. The mid closes come along so Roll's estimator can be
    computed on the same intervals.
    """
    import numpy as np

    mids = (bids + asks) / 2.0
    spreads = asks - bids
    edges = (times // seconds).astype(np.int64)
    out = {"at": [], "spread": [], "mid": [], "ticks": []}
    start = 0
    for i in range(1, len(edges) + 1):
        if i < len(edges) and edges[i] == edges[start]:
            continue
        if i - start >= LEAST_TICKS:
            out["at"].append(float(edges[start] * seconds + seconds))
            out["spread"].append(float(np.median(spreads[start:i])))
            out["mid"].append(float(mids[i - 1]))
            out["ticks"].append(i - start)
        start = i
    return out


def roll_spread(mids: list[float]) -> float:
    """Roll's implied spread: `2 * sqrt(-cov(dp(t), dp(t-1)))`.

    The independent estimate the subject's provenance asks for. Bid-ask bounce
    makes consecutive price changes negatively covariant, and the size of that
    covariance implies the spread without ever seeing a quote.

    **It is undefined when the covariance is positive**, which happens whenever
    the price has any trend or momentum at the sampling interval - and
    returning a nan there rather than a number is the honest answer. A version
    that clamps to zero would report a tight spread exactly where the
    estimator has broken.
    """
    if len(mids) < 100:
        return float("nan")
    moves = [b - a for a, b in itertools.pairwise(mids)]
    if len(moves) < 50:
        return float("nan")
    first = moves[:-1]
    second = moves[1:]
    mf, ms = statistics.fmean(first), statistics.fmean(second)
    cov = statistics.fmean([(a - mf) * (b - ms) for a, b in zip(first, second, strict=True)])
    return 2.0 * math.sqrt(-cov) if cov < 0 else float("nan")


def fit_and_score(logs: list[float], stamps: list[float]) -> dict:
    """`reverting` on the log spread against the trailing mean and a constant.

    Every arm forecasts the **next** observation from what it has seen, and is
    scored on the second half only. The filter's two parameters are swept on
    the first half, which is the comparison `statespace-clock-levers.md`
    records three instances of getting wrong.
    """
    from till_infinity.structures.statespace.reverting import Reverting

    half = len(logs) // 2
    spread = statistics.pstdev([b - a for a, b in itertools.pairwise(logs)]) or 1e-9
    variance = spread * spread

    # Both grids are wide, because the first attempt used `sigma2` from 1e-6
    # to 1e1 and `theta` from 0.02 to 2.0 and **every instrument pinned
    # `theta` at the top**, with XAUUSD pinning `sigma2` too. A parameter at a
    # grid edge is not a fitted parameter - the defect
    # `statespace-clock-levers.md` records three instances of - and for a
    # near-constant spread the fit wants very fast reversion, so the grid has
    # to reach there.
    best = (float("-inf"), 0.0, 0.0)
    for sigma_power in range(-8, 5):
        for theta in (0.002, 0.02, 0.2, 2.0, 20.0, 200.0, 2000.0):
            member = Reverting(sigma2=10.0**sigma_power, theta=theta)
            for when, value in zip(stamps[:half], logs[:half], strict=True):
                member.predict(when)
                member.update(value, variance, when)
            if math.isfinite(member.loglike) and member.loglike > best[0]:
                best = (member.loglike, 10.0**sigma_power, theta)
    _, sigma2, theta = best
    edges = []
    if sigma2 in (1e-8, 1e4):
        edges.append("sigma2")
    if theta in (0.002, 2000.0):
        edges.append("theta")

    member = Reverting(sigma2=sigma2, theta=theta)
    rows: dict[str, list[float]] = {"filter": [], "constant": []}
    rows.update({f"trail{t}": [] for t in TRAILS})
    loglike = 0.0

    for i, (when, value) in enumerate(zip(stamps, logs, strict=True)):
        if i >= half:
            # Each arm's forecast of this observation, before it is folded in.
            rows["filter"].append(member.at_time(when))
            rows["constant"].append(statistics.fmean(logs[:half]))
            for trail in TRAILS:
                window = logs[max(i - trail, 0) : i]
                rows[f"trail{trail}"].append(statistics.fmean(window) if window else logs[0])
        member.predict(when)
        member.update(value, variance, when)
        if i == half:
            loglike = member.loglike
    held = member.loglike - loglike

    actual = logs[half:]
    out = {
        "sigma2": sigma2,
        "theta": theta,
        "loglike": held,
        "n": len(actual),
        "pinned": ",".join(edges) or "-",
    }
    for name, guesses in rows.items():
        if len(guesses) != len(actual):
            continue
        # Error in **spread units**, not in logs: a cost gate is set in the
        # quantity it charges, so the error that matters is the ratio by which
        # the forecast missed, expressed as a fraction of the spread.
        out[name] = statistics.fmean(
            [abs(math.exp(g - a) - 1.0) for g, a in zip(guesses, actual, strict=True)]
        )
    return out


def profile(stamps: list[float], logs: list[float]) -> tuple[float, int]:
    """Peak-to-trough of the spread's own hour-of-day profile, and its peak.

    The volatility profile measured 2.7 to 3.7 in `statespace-seasonal.md`. If
    the spread has one of comparable size, a constant cost gate is wrong in
    both directions over the day - too lenient when quotes are wide and too
    strict when they are tight - and that is the cheapest actionable thing
    here.
    """
    import datetime as dt

    buckets: dict[int, list[float]] = {}
    for when, value in zip(stamps, logs, strict=True):
        hour = dt.datetime.fromtimestamp(when, tz=dt.UTC).hour
        buckets.setdefault(hour, []).append(value)
    usable = {h: statistics.fmean(v) for h, v in buckets.items() if len(v) >= 20}
    if len(usable) < 6:
        return float("nan"), -1
    low = min(usable.values())
    peak = max(usable, key=lambda h: usable[h])
    return math.exp(max(usable.values()) - low), peak


def main() -> None:
    print(
        f"spread observed as the median quoted spread per {WINDOW}s interval,\n"
        "filtered on its logarithm. Errors are mean |forecast/actual - 1|, so\n"
        "0.10 means the forecast missed by a tenth of the spread on average.\n"
        "Scored on the second half; the filter's parameters swept on the first.\n"
    )
    print(
        f"{'instrument':<24}{'n':>6}{'median bp':>10}{'profile':>9}{'peak h':>7}"
        f"{'quoted':>9}{'Roll':>9}{'Roll/quoted':>12}"
    )

    rows = []
    for name in TRADED + GENERATED:
        found = load(name)
        if found is None:
            print(f"{name:<24}unreadable")
            continue
        data = observations(*found, WINDOW)
        if len(data["spread"]) < 400:
            continue
        logs = [math.log(v) for v in data["spread"] if v > 0]
        if len(logs) != len(data["spread"]):
            continue
        stamps = data["at"]
        mid = statistics.median(data["mid"]) or 1.0
        quoted = statistics.median(data["spread"])
        rolled = roll_spread(data["mid"])
        extent, peak = profile(stamps, logs)
        label = f"*{name}" if name in GENERATED else name
        print(
            f"{label:<24}{len(logs):>6}{quoted / mid * 1e4:>10.2f}"
            f"{extent:>9.2f}{peak:>7}"
            f"{quoted / mid * 1e4:>9.2f}"
            + (f"{rolled / mid * 1e4:>9.2f}" if not math.isnan(rolled) else f"{'-':>9}")
            + (
                f"{rolled / quoted:>12.2f}"
                if not math.isnan(rolled) and quoted > 0
                else f"{'-':>12}"
            )
        )
        got = fit_and_score(logs, stamps)
        rows.append({"label": label, "profile": extent, **got})

    print("\n== the filter against the trailing average, on the held-out half")
    print(
        f"{'instrument':<24}{'sigma2':>9}{'theta':>9}  {'pinned':<14}{'filter':>9}"
        + "".join(f"{'trail' + str(t):>9}" for t in TRAILS)
        + f"{'constant':>10}{'best':>10}"
    )
    for row in rows:
        names = ["filter", *[f"trail{t}" for t in TRAILS], "constant"]
        have = {n: row[n] for n in names if n in row}
        if not have:
            continue
        best = min(have, key=lambda n: have[n])
        print(
            f"{row['label']:<24}{row['sigma2']:>9.0e}{row['theta']:>8.3f}"
            f"{row['pinned']:>8}"
            + "".join(f"{have[n]:>9.3f}" if n in have else f"{'-':>9}" for n in names[:-1])
            + (f"{have['constant']:>10.3f}" if "constant" in have else f"{'-':>10}")
            + f"{best:>10}"
        )

    traded = [r for r in rows if not r["label"].startswith("*")]
    if traded:
        print("\n== medians over traded instruments")
        for name in ["filter", *[f"trail{t}" for t in TRAILS], "constant"]:
            got = [r[name] for r in traded if name in r]
            if got:
                print(f"{name:<12}{statistics.median(got):>9.3f}")
        shapes = [r["profile"] for r in traded if not math.isnan(r["profile"])]
        if shapes:
            print(
                f"\n   spread profile over the day: {statistics.median(shapes):.2f}x"
                " peak to trough, against the volatility profile's 2.7 to 3.7."
            )


if __name__ == "__main__":
    main()
