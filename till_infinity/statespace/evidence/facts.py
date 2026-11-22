"""Does a member, simulated forward, produce something that looks like a market?

Taken from TradeFM (arXiv:2602.23784), which judges a generative model of order
flow on whether its **rollouts reproduce stylized facts** - near-zero return
autocorrelation, slowly decaying autocorrelation of *absolute* returns, and
kurtosis declining toward Gaussian as the interval grows - alongside
distributional distances to real data.

This package has scored every member on held-out likelihood and **never on
whether simulating it forward produces a series that looks like a market**. The
two are different questions. A member can be the best one-step density in the
family and still generate, when run forward, a series with no volatility
clustering at all - which would mean it is a good local approximation and a
false description, and nothing here would have said so.

## How a member is rolled out

`paths.simulate` generates from *the* model - a triple integrator driven by
white jerk - so it tests that model rather than a member. Any member can be
rolled out through the `Filter` protocol instead: ask for its predictive mean
and spread at the next time, **draw from that**, feed the draw back as the
reading, repeat. That is a posterior-predictive sample, and it is exactly what
the member claims the world does.

A member whose rollout has no clustering is not being judged on a technicality:
clustering is the most robust stylized fact in finance, and this package's own
measurements say volatility is the one forecastable quantity here.

## What is measured, and what each one is worth

* **`drift`** - the lag-1 autocorrelation of returns. Markets sit near zero;
  this desk measured 49.5% sign agreement over 70,000 points and `|t|` below 2
  on every directional test it has run. A member that generates strong return
  autocorrelation is generating a market that could be traded, which is the
  loudest possible sign that it is wrong.
* **`clustering`** - the autocorrelation of **absolute** returns, summed over
  the first lags. Positive and slowly decaying in every real series.
  `research/docs/statespace-measured.md` measured +0.381 over five lags on
  eurusd 4h against -0.047 for the signed rate.
* **`tails`** - excess kurtosis at one step, and at aggregations of it. Real
  series are leptokurtic at short intervals and approach Gaussian as the
  interval grows; a member that keeps the same kurtosis at every aggregation is
  generating iid draws from a fat-tailed law rather than a market.

None of these is a likelihood, and that is the point: they are checkable against
the real series with no model fitted to either.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

#: Lags over which absolute-return autocorrelation is summed. Five, matching
#: the measurement in `statespace-measured.md` so the numbers compare.
LAGS = 5

#: Aggregations at which kurtosis is reported. The claim is that it falls.
STEPS = (1, 5, 20)


def autocorrelation(values: Sequence[float], lag: int) -> float:
    """Sample autocorrelation at one lag. Hand-written, so it has a reference.

    `tests/test_statespace.py` checks it against `numpy.corrcoef` on the lagged
    pair, which is the module rule: anything hand-written arrives with an
    independent check.
    """
    n = len(values)
    if n <= lag + 2 or not all(math.isfinite(v) for v in values):
        return float("nan")
    mean = statistics.fmean(values)
    # **Scaled before squaring.** A correlation is invariant to scale, and a
    # rollout from a mis-specified member can run to 1e200 - where squaring
    # overflows and the estimator raises instead of reporting. Dividing by the
    # largest deviation costs one pass and makes the arithmetic safe for any
    # series the caller can hold, which matters because this is the check meant
    # to catch exactly that runaway.
    widest = max((abs(v - mean) for v in values), default=0.0)
    if widest <= 0 or not math.isfinite(widest):
        return float("nan")
    scaled = [(v - mean) / widest for v in values]
    numerator = sum(scaled[i] * scaled[i + lag] for i in range(n - lag))
    denominator = sum(v * v for v in scaled)
    return numerator / denominator if denominator > 0 else float("nan")


def kurtosis(values: Sequence[float]) -> float:
    """Excess kurtosis. Zero for a Gaussian."""
    n = len(values)
    if n < 8 or not all(math.isfinite(v) for v in values):
        return float("nan")
    mean = statistics.fmean(values)
    widest = max((abs(v - mean) for v in values), default=0.0)
    if widest <= 0 or not math.isfinite(widest):
        return float("nan")
    # Scaled for the same reason as `autocorrelation`: kurtosis is a ratio of
    # moments and therefore scale-free, and the fourth power is where a wide
    # series overflows.
    scaled = [(v - mean) / widest for v in values]
    second = statistics.fmean([v * v for v in scaled])
    if second <= 0:
        return float("nan")
    fourth = statistics.fmean([v**4 for v in scaled])
    return fourth / (second * second) - 3.0


@dataclass(frozen=True, slots=True)
class Facts:
    """The three stylized facts, as numbers that can be compared."""

    #: Lag-1 autocorrelation of returns. Near zero in a market.
    drift: float
    #: Summed autocorrelation of |returns| over `LAGS`. Positive in a market.
    clustering: float
    #: Excess kurtosis at each aggregation in `STEPS`. Falls in a market.
    tails: tuple[float, ...]
    #: How many returns these were measured on.
    seen: int

    @property
    def tails_fall(self) -> bool:
        """Does kurtosis decline with aggregation? The shape, not the level."""
        usable = [t for t in self.tails if not math.isnan(t)]
        return len(usable) >= 2 and usable[0] > usable[-1]

    def __str__(self) -> str:
        tails = "/".join(f"{t:+.2f}" for t in self.tails)
        return (
            f"drift {self.drift:+.3f}  clustering {self.clustering:+.3f}  "
            f"kurtosis {tails}  n={self.seen}"
        )


def measure(values: Sequence[float]) -> Facts:
    """The three facts of one series of **levels** (not returns)."""
    steps = [values[i] - values[i - 1] for i in range(1, len(values))]
    if len(steps) < 50:
        return Facts(float("nan"), float("nan"), (), len(steps))
    sizes = [abs(s) for s in steps]
    clustering = sum(
        got for lag in range(1, LAGS + 1) if not math.isnan(got := autocorrelation(sizes, lag))
    )
    tails = []
    for step in STEPS:
        if step == 1:
            tails.append(kurtosis(steps))
            continue
        # Aggregate non-overlapping, because overlapping sums share terms and
        # would smooth the kurtosis for a reason that is arithmetic.
        lumped = [sum(steps[i : i + step]) for i in range(0, len(steps) - step + 1, step)]
        tails.append(kurtosis(lumped) if len(lumped) >= 8 else float("nan"))
    return Facts(autocorrelation(steps, 1), clustering, tuple(tails), len(steps))


def rollout(
    build: Callable[[], object],
    times: Sequence[float],
    *,
    noise: float,
    start: float = 0.0,
    seed: int = 0,
    warmup: Sequence[tuple[float, float]] = (),
) -> list[float]:
    """Run a member forward, drawing each reading from its own forecast.

    The member is optionally shown `warmup` readings first - real ones, so it
    starts from a state it would actually be in - and then generates: predict,
    draw from the predictive distribution, feed the draw back as the reading.

    **The draw uses the predictive spread, not the state spread.** A reading
    carries measurement noise as well as state uncertainty, so sampling from the
    state band alone would generate a series smoother than the member claims -
    which is the same conflation that made one harness report 50.3% coverage for
    `linear` against 98.0% for `selective`.
    """
    rng = random.Random(seed)
    engine = build()
    for when, value in warmup:
        engine.predict(when)  # type: ignore[attr-defined]
        engine.update(value, noise, when)  # type: ignore[attr-defined]

    out: list[float] = []
    last = float(warmup[-1][1]) if warmup else float(start)
    for when in times:
        engine.predict(when)  # type: ignore[attr-defined]
        centre = float(engine.at_time(when))  # type: ignore[attr-defined]
        spread = math.sqrt(float(engine.sd) ** 2 + max(noise, 0.0))  # type: ignore[attr-defined]
        if not math.isfinite(centre) or not math.isfinite(spread) or spread <= 0:
            centre, spread = last, math.sqrt(max(noise, 1e-12))
        drawn = rng.gauss(centre, spread)
        engine.update(drawn, noise, when)  # type: ignore[attr-defined]
        out.append(drawn)
        last = drawn
    return out


def verdict(real: Facts, made: Facts) -> str:
    """Which of the real series' facts the rollout reproduced.

    Deliberately a **shape** comparison, not a distance. The question is whether
    the member generates a market, not whether it generates *this* market: a
    rollout matching eurusd's kurtosis to two places would be a coincidence,
    and reproducing the sign and direction of each fact is the claim worth
    making.

    Each fact is scored against what the real series did, so a member is not
    penalised for failing to cluster on a series that does not cluster - which
    matters, because the Deriv synthetics barely do.
    """
    notes, agreed = [], 0
    if abs(real.drift) < 0.1:
        ok = abs(made.drift) < 0.1
        notes.append("drift~0" if ok else f"drift {made.drift:+.2f}")
        agreed += ok
    else:
        ok = (made.drift > 0) == (real.drift > 0)
        notes.append(f"drift {made.drift:+.2f} vs {real.drift:+.2f}")
        agreed += ok

    wanted = real.clustering > 0.1
    got = made.clustering > 0.1
    notes.append(
        ("clusters" if got else "NO clustering") + ("" if wanted == got else " (real disagrees)")
    )
    agreed += wanted == got

    notes.append("tails fall" if made.tails_fall else "tails flat")
    agreed += made.tails_fall == real.tails_fall

    head = "MARKET-LIKE  " if agreed == 3 else f"{agreed}/3 facts  "
    return head + ", ".join(notes)
