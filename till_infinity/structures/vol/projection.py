"""Where a synthetic goes next, as a distribution rather than a number.

Everything else in this package returns a **scale**. `volatility.py` says how
big a move is now, `har.py` says how big the next one will be, `stated.py` says
the name already told us. None of them says *where price can be in twenty
minutes, and with what probability* - and on this book that question has an
exact answer, which is unusual enough to be worth a module.

## Why an exact answer exists here and nowhere else

On a real market a forward distribution is a guess stacked on an estimate: you
do not know sigma, you do not know the law, and the law changes. On a Deriv
Volatility index all three are known. `stated.py` collects the evidence -
twelve of twelve realising the name within **0.49%**, `H = 0.50`, kurtosis 2.98
to 3.02, Jarque-Bera `p` from 0.40 to 0.95, largest `|acf|` of absolute return
**0.017** against 0.219-0.453 on real controls. The process is geometric
Brownian motion at a published constant, so the forward law is not fitted, it
is **derived**:

    log(S_T / S_0) ~ Normal(mu * T, sigma^2 * T)

and every band below is that normal read off at a quantile. There is no
estimator here to be wrong, which is exactly why the calibration section
matters: when the only free parameter is a constant Deriv publishes, **a band
that misses is evidence about the generator rather than about the model.**

## What `mu` is, and why this module refuses to assume it

This is the open question the module is built around, and it is a question
about **the middle of Deriv's pipeline**.

A generator of this kind is a chain: a cryptographic source emits uniforms, an
inverse-normal turns them into standard normals, a recursion turns those into a
path, and a quantiser puts the result on the quote grid. The source is
unattackable and `research/harness/rebuildpredict.py` says so at length. The
quantiser is visible and `frac_zero` and `n_distinct` have already read it
twice. **The recursion in between has never been identified**, and it has a
free convention:

* **`ito`** - the path is `S * exp((-sigma^2/2) dt + sigma dW)`, whose
  **price** is a martingale and whose median drifts down.
* **`plain`** - the path is `S * exp(sigma dW)`, whose **log price** is a
  martingale and whose median is flat, but whose price drifts up.

Both are standard, both are used in production systems, and they differ by
`sigma^2 T / 2`. Nothing in this repository knows which one Deriv runs.

So this module **carries both and scores both**, the way `consensus_vol` scores
its members rather than picking one.

**Answered, 2026-09-12: it is `ito`.** Deriv applies the drift correction, so
**price is the martingale and log price is not.** Measured by
`research/harness/convention.py` over **2,997,653 closed bars** across twenty
Volatility feeds and eight timeframes - from history rather than by live
accumulation, because a closed bar's open and close are exactly the `(t, t+T)`
pair this calibration settles, so every bar ever printed was an observation it
could have had.

| timeframe | bars | `ito` bias | `plain` bias | separation |
| --- | --- | --- | --- | --- |
| 1h | 635,437 | **+0.27** | -2.46 | 4.4 SE |
| 4h | 190,006 | **+0.10** | -2.79 | 4.8 SE |
| 6h | 126,677 | **-0.14** | -3.03 | 4.8 SE |
| 8h | 94,997 | **-0.04** | -2.93 | 4.8 SE |
| 12h | 61,032 | **-0.21** | -3.12 | 4.7 SE |
| 1d | 28,743 | **-0.00** | -2.87 | 4.6 SE |

Six independent timeframes, `ito` at zero bias on every one and `plain` two and
a half to three standard errors low on every one. 3m and 15m report **cannot
resolve** rather than a verdict, which is `convention.py`'s power calculation
refusing a cell whose separation is 1.2 SE - the sample is largest there and
the question is least answerable, because the conventions separate as
`sigma sqrt(T) / 2` while the error does not care what `T` is. The test recovers
a known convention from simulated paths in both directions before it is shown
any Deriv data.

**What that changes here.** `ito` was already the default and is now the
measured one. The live calibration therefore stops being an identification and
becomes a **monitor**: the question is no longer "which recursion is this" but
"is it still that one", and an alarm needs `WARM`, not `RESOLVES_AT`. A mean PIT
walking away from 0.5 on a feed whose sigma has not moved is the generator
changing under the desk - the cheap venue check `research/generators.md` asks
for, reached by another route.

**What it would have cost to wait.** At 1h the two conventions differ by 0.4% of
one standard deviation, so a single bar cannot distinguish them; against the
`1/sqrt(12 N)` standard error of a mean PIT, live accumulation needed of order
**50,000 settled bars** before the answer meant anything. `RESOLVES_AT` keeps
that number because re-identification from live data alone is still what it
measures, and knowing how far a claim is from being supportable is worth having
even once the claim has arrived another way.

## The error rate is a PIT, not a hit rate

The obvious way to score a band is to count how often price landed inside it.
That throws away almost everything: it reduces a whole distribution to one bit
and cannot tell a band that is slightly too wide from one that is wildly too
wide with a fat middle.

The probability integral transform keeps all of it. Push each realised outcome
through the forecast's own CDF:

    u = Phi( (log(S_T/S_0) - mu T) / (sigma sqrt(T)) )

**If the forecast law is right, `u` is uniform on (0, 1)** - whatever the law
was. So mean `u` should be 0.5, its variance 1/12, and the deviation from
uniform is a complete statement of what is wrong: a mean above 0.5 means the
forecast drifts low, a variance below 1/12 means the bands are too wide, and a
crowded middle with thin tails means the tails are underweighted. Coverage is
kept alongside it because it is what a human reads, but the PIT is what decides.

## What this is not

It is **not** a direction call and cannot become one. `research/deriving.md`
proves `E[net] = -(c/2) x turnover` for any predictable position on a
martingale, and a symmetric band around the current price is the formal
statement that there is no direction to call. What it buys is the *shape* of
the next move, which is what sizing, stop distance and target distance are
actually made of - `research/spending.md`'s conclusion is that the desk's
weakness is its conditional estimates, not its direction calls.

First-passage - the probability of **touching** a level rather than finishing
beyond it - is a different integral and it already has a home in
`till_infinity/trading/barriers.py`, with the Broome-Glasserman-Kou continuity
correction that a naive Brownian form gets wrong. This module does not
duplicate it; `touch` defers to it.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from ..state import Restorable
from . import stated

#: Off until measured live, like every other new member on this book.
ENABLED = os.environ.get("STRUCTURES_PROJECTION", "0") not in ("0", "false", "no")

#: Seconds in a 365-day year. No session, no weekend - see `stated.py`.
SECONDS_PER_YEAR = 365 * 24 * 60 * 60

#: The two conventions for `mu`, scored against each other. See the docstring.
CONVENTIONS = ("ito", "plain")

#: Central bands, by the z that bounds them. Hardcoded rather than inverted from
#: a rational approximation nobody in this repository would audit: these four
#: numbers are exact to the digits shown and the forward CDF is `math.erf`,
#: which is exact, so no approximation enters this module at all.
BANDS: dict[int, float] = {
    50: 0.6744897501960817,
    80: 1.2815515655446004,
    95: 1.9599639845400545,
    99: 2.5758293035489004,
}

#: How many settled observations before a PIT statistic is worth reading. Below
#: this the mean of a uniform is mostly its own standard error.
WARM = 200

#: Accumulated `sigma^2 T` needed before the two conventions can be told apart.
#:
#: **Not a bar count, and the difference is a defect this carried until
#: 2026-09-12.** It was `50_000` observations, which is wrong because the
#: information about a drift is **calendar span, not sample size**: the sum of
#: the log returns telescopes to `log(S_end / S_start)`, so a year of 1m bars and
#: a year of 1d bars carry identically much. Separation between the conventions
#: goes as `sqrt(sum sigma^2 T) / 2`, and `research/pipeline.md` validated the
#: estimator unbiased and correct on 38-39 of 40 simulated venues at 56.
#:
#: At daily spacing the two criteria happen to agree, which is why the error was
#: invisible in `convention.py`'s headline. At **hourly** spacing a bar count
#: raises the flag at about **a fifth** of the separation it promises.
RESOLVES_AT = 37.7

#: Kept only so a stored `Calibration` written before the fix still restores.
#: `Restorable` defaults a missing field; it cannot undo a field that meant
#: something else.
LEGACY_RESOLVES_AT_COUNT = 50_000


def _cdf(z: float) -> float:
    """Standard normal CDF, exactly, via `math.erf`."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def sigma_for(feed: str, seconds: float) -> float | None:
    """The standard deviation of `log(S_T/S_0)` over `seconds`, from the name.

    `None` for every instrument whose name claims nothing - the real book, and
    the Boom, Crash, Step and Range Break families, which have documented
    mechanics but no published volatility. `stated.nominal` is the single place
    that decision is made and this defers to it rather than re-deciding.
    """
    claimed = stated.nominal(feed)
    if claimed <= 0 or seconds <= 0:
        return None
    return claimed / 100.0 * math.sqrt(seconds / SECONDS_PER_YEAR)


def drift_for(feed: str, seconds: float, convention: str = "ito") -> float:
    """`mu * T` under one of the two conventions. Zero when the name says nothing."""
    sigma = sigma_for(feed, seconds)
    if sigma is None:
        return 0.0
    return -0.5 * sigma * sigma if convention == "ito" else 0.0


@dataclass(slots=True)
class Cone(Restorable):
    """The projected distribution of price at one horizon.

    `Restorable` although a cone is computed fresh on every call and never
    saved. The invariant this package enforces is that **every slotted
    dataclass under `structures` restores a snapshot written before one of its
    fields existed**, and it is enforced blanket rather than per-class because
    the alternative is deciding, per class, whether something might one day be
    held inside something that is persisted - which is exactly the judgement
    that gets made wrong. `ranges.Bar` carries it for the same reason.
    """

    feed: str
    seconds: float
    price: float
    sigma: float
    drift: float
    convention: str
    bands: dict[int, tuple[float, float]] = field(default_factory=dict)

    @property
    def median(self) -> float:
        return self.price * math.exp(self.drift)

    def quantile(self, p: float) -> float:
        """Price at probability `p`, for any `p` - the bands are the common cases."""
        if not 0.0 < p < 1.0:
            raise ValueError(f"p must be in (0, 1), got {p}")
        # Bisection on the exact CDF. Twelve iterations of a monotone function
        # on a bracketed root is cheaper than carrying an inverse-normal
        # approximation whose error nobody here would ever check.
        lo, hi = -10.0, 10.0
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if _cdf(mid) < p:
                lo = mid
            else:
                hi = mid
        return self.price * math.exp(self.drift + self.sigma * (lo + hi) / 2.0)

    def contains(self, actual: float, level: int = 95) -> bool:
        low, high = self.bands[level]
        return low <= actual <= high

    def pit(self, actual: float) -> float:
        """Where `actual` fell in this forecast's own CDF. Uniform if the forecast is right."""
        if actual <= 0 or self.price <= 0 or self.sigma <= 0:
            return float("nan")
        z = (math.log(actual / self.price) - self.drift) / self.sigma
        return _cdf(z)

    def to_dict(self) -> dict:
        return {
            "feed": self.feed,
            "seconds": self.seconds,
            "price": self.price,
            "median": self.median,
            "sigma": self.sigma,
            "convention": self.convention,
            "bands": {str(k): list(v) for k, v in self.bands.items()},
        }


def project(feed: str, price: float, seconds: float, *, convention: str = "ito") -> Cone | None:
    """The forward distribution of `feed` at `seconds` ahead, or None if unnamed.

    Exact, not fitted. The only input beyond the current price is the number in
    the instrument's own name.
    """
    sigma = sigma_for(feed, seconds)
    if sigma is None or price <= 0:
        return None
    drift = drift_for(feed, seconds, convention)
    cone = Cone(
        feed=feed, seconds=seconds, price=price, sigma=sigma, drift=drift, convention=convention
    )
    for level, z in BANDS.items():
        centre = price * math.exp(drift)
        cone.bands[level] = (centre * math.exp(-z * sigma), centre * math.exp(z * sigma))
    return cone


def path(
    feed: str, price: float, seconds: float, steps: int = 12, *, convention: str = "ito"
) -> list[Cone]:
    """The whole cone out to `seconds`, in `steps` slices.

    The widening is `sqrt(t)`, which is the part a chart makes obvious and a
    single number does not: at four times the horizon the band is twice as wide,
    not four times. Stops placed on a linear intuition are systematically too
    tight at short horizons and too loose at long ones.
    """
    if steps < 1:
        raise ValueError("steps must be at least 1")
    out = []
    for i in range(1, steps + 1):
        cone = project(feed, price, seconds * i / steps, convention=convention)
        if cone is None:
            return []
        out.append(cone)
    return out


def touch(target_units: float, stop_units: float) -> float:
    """Probability of reaching the target before the stop.

    Deferred to `trading.barriers`, which carries the Broadie-Glasserman-Kou
    continuity correction. A naive Brownian first-passage form is wrong on
    discretely-monitored barriers and this module is not going to hold a second,
    worse copy of an integral that already has a correct home.
    """
    from ...trading import barriers

    return barriers.probability(target_units, stop_units)


@dataclass(slots=True)
class Calibration(Restorable):
    """Whether the cone is the right shape, by the PIT, for one convention.

    Streaming: the mean and the variance of `u` are accumulated rather than the
    values kept, because this runs per feed per horizon on a live desk and a
    growing list is a leak with a schedule.
    """

    convention: str = "ito"
    n: int = 0
    _sum: float = 0.0
    _sumsq: float = 0.0
    #: Accumulated `sigma^2 T`, which is what actually decides the convention.
    _info: float = 0.0
    _inside: dict[int, int] = field(default_factory=dict)

    def record(self, cone: Cone, actual: float) -> None:
        u = cone.pit(actual)
        if not math.isfinite(u):
            return
        self.n += 1
        self._sum += u
        self._sumsq += u * u
        # `cone.sigma` is already `sigma * sqrt(T)`, so its square is the
        # `sigma^2 T` this observation contributes. See `RESOLVES_AT`.
        self._info += cone.sigma * cone.sigma
        for level in BANDS:
            if cone.contains(actual, level):
                self._inside[level] = self._inside.get(level, 0) + 1

    @property
    def warm(self) -> bool:
        return self.n >= WARM

    @property
    def resolved(self) -> bool:
        """Whether there is enough **information** to tell the two conventions apart.

        Accumulated `sigma^2 T`, not a count of bars. A drift is a statement
        about calendar span: the log returns telescope, so a million one-minute
        bars say no more about it than the same span of daily ones. Counting
        rows instead raises this flag at a fifth of the separation it promises
        at hourly spacing - see `RESOLVES_AT`, and `research/pipeline.md` for
        the estimator that measured it.

        Reported rather than enforced, because a caller is entitled to read an
        unresolved number as long as it is labelled as one. The alternative -
        returning a winner at `n = 300` - is how a convention gets adopted on
        noise and stays adopted.
        """
        return self._info >= RESOLVES_AT

    @property
    def information(self) -> float:
        """Accumulated `sigma^2 T`. `sqrt(information) / 2` is the separation."""
        return self._info

    @property
    def separation(self) -> float:
        """How far apart the two conventions are here, in standard deviations."""
        return math.sqrt(max(self._info, 0.0)) / 2.0

    @property
    def mean(self) -> float:
        """Mean PIT. 0.5 when the forecast is centred; above it when it forecasts low."""
        return self._sum / self.n if self.n else float("nan")

    @property
    def variance(self) -> float:
        """Variance of the PIT. 1/12 = 0.0833 when the bands are the right width."""
        if self.n < 2:
            return float("nan")
        m = self.mean
        return max(self._sumsq / self.n - m * m, 0.0)

    @property
    def dispersion(self) -> float:
        """Band width as a multiple of correct. Above 1 is too wide, below is too tight."""
        var = self.variance
        if not math.isfinite(var) or var <= 0:
            return float("nan")
        return math.sqrt((1.0 / 12.0) / var)

    def coverage(self, level: int = 95) -> float:
        """Fraction that landed inside the band. Should equal `level / 100`."""
        return self._inside.get(level, 0) / self.n if self.n else float("nan")

    def bias_sigma(self) -> float:
        """Mean PIT's distance from 0.5, in standard errors of its own null.

        The null is uniform, whose mean has variance `1/(12 n)`. This is the
        number that decides whether a drift convention is wrong or merely
        unlucky, and it is the one to read before `mean`.
        """
        if self.n < 2:
            return float("nan")
        return (self.mean - 0.5) / math.sqrt(1.0 / (12.0 * self.n))

    def to_dict(self) -> dict:
        return {
            "convention": self.convention,
            "n": self.n,
            "warm": self.warm,
            "resolved": self.resolved,
            "information": round(self._info, 4),
            "separation": round(self.separation, 4),
            "pit_mean": round(self.mean, 6) if self.n else None,
            "pit_var": round(self.variance, 6) if self.n > 1 else None,
            "dispersion": round(self.dispersion, 4) if self.n > 1 else None,
            "bias_sigma": round(self.bias_sigma(), 3) if self.n > 1 else None,
            "coverage": {str(k): round(self.coverage(k), 4) for k in sorted(BANDS)},
        }


@dataclass(slots=True)
class Projector(Restorable):
    """One feed's cone, and a scored calibration for each convention.

    Holding both is the whole point: `standings` is what identifies the
    generator's drift convention, and it can only do that if neither was
    assumed at the start.
    """

    feed: str = ""
    _cal: dict[str, Calibration] = field(default_factory=dict)

    def _for(self, convention: str) -> Calibration:
        found = self._cal.get(convention)
        if found is None:
            found = self._cal[convention] = Calibration(convention=convention)
        return found

    def cone(self, price: float, seconds: float, *, convention: str = "ito") -> Cone | None:
        return project(self.feed, price, seconds, convention=convention)

    def settle(self, price_then: float, seconds: float, price_now: float) -> None:
        """Score both conventions against one realised outcome."""
        for convention in CONVENTIONS:
            cone = project(self.feed, price_then, seconds, convention=convention)
            if cone is not None:
                self._for(convention).record(cone, price_now)

    def standings(self) -> list[tuple[str, float]]:
        """Conventions by how close their mean PIT sits to 0.5, best first.

        The score is `|bias_sigma|`, so a convention is not rewarded for a large
        sample - it is a distance in standard errors and both members have seen
        exactly the same observations.
        """
        out = []
        for convention in CONVENTIONS:
            cal = self._cal.get(convention)
            if cal is not None and cal.warm:
                out.append((convention, abs(cal.bias_sigma())))
        return sorted(out, key=lambda kv: kv[1])

    def to_dict(self) -> dict:
        return {
            "feed": self.feed,
            "enabled": ENABLED,
            "standings": [[k, round(v, 3)] for k, v in self.standings()],
            "calibration": {k: v.to_dict() for k, v in sorted(self._cal.items())},
        }


@dataclass(slots=True)
class Book(Restorable):
    """One projector per instrument, keyed the way `volatility.Book` keys its own.

    Per feed rather than per feed and timeframe, which is the one place this
    deliberately differs from `volatility.Book`. A cone is parameterised by a
    horizon in **seconds** and its width scales as `sqrt(t)` from a single
    published constant, so one projector answers every timeframe exactly. The
    volatility estimates need a key per timeframe because they are *estimates*
    and a 4h estimate of a 5m move is wrong; this needs none because it is a
    derivation and the horizon is an argument.
    """

    _by_feed: dict[str, Projector] = field(default_factory=dict)

    def of(self, feed: str) -> Projector:
        found = self._by_feed.get(feed)
        if found is None:
            found = self._by_feed[feed] = Projector(feed=feed)
        return found

    def cone(
        self, feed: str, price: float, seconds: float, *, convention: str = "ito"
    ) -> Cone | None:
        return self.of(feed).cone(price, seconds, convention=convention)

    def settle(self, feed: str, price_then: float, seconds: float, price_now: float) -> None:
        """Score a closed bar, and **create nothing for a feed that cannot be scored.**

        The check is here rather than inside `Projector.settle` because `of`
        creates on access: without it, every real instrument on the book gets a
        permanently empty projector the first time a bar arrives, and `forget`
        cannot reclaim them because those feeds are live. On this desk that is
        33 of 53 entries that will never hold an observation.
        """
        if sigma_for(feed, seconds) is None:
            return
        self.of(feed).settle(price_then, seconds, price_now)

    def forget(self, keep: set[str]) -> int:
        """Drop instruments the desk no longer trades. Mirrors `volatility.Book.forget`."""
        gone = [feed for feed in self._by_feed if feed not in keep]
        for feed in gone:
            del self._by_feed[feed]
        return len(gone)

    def feeds(self) -> list[str]:
        return sorted(self._by_feed)

    def standings(self) -> list[tuple[str, float]]:
        """The drift convention, pooled across every feed that is warm.

        Pooled because the per-feed samples are small and the convention is a
        property of the **generator**, not of an instrument - if Deriv runs one
        recursion for the family, one answer covers all of them. Reported as a
        mean of each feed's `|bias_sigma|`, so a single long-lived feed cannot
        carry the verdict alone.
        """
        totals: dict[str, list[float]] = {}
        for projector in self._by_feed.values():
            for convention, score in projector.standings():
                totals.setdefault(convention, []).append(score)
        return sorted(
            ((k, sum(v) / len(v)) for k, v in totals.items() if v),
            key=lambda kv: kv[1],
        )

    def to_dict(self) -> dict:
        return {
            "enabled": ENABLED,
            "feeds": len(self._by_feed),
            "standings": [[k, round(v, 3)] for k, v in self.standings()],
        }
