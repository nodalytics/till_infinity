"""A stop at a measured quantile of the adverse excursion, scored on coverage.

A stop distance is a claim about a tail: *price will not go this far against
me before the trade resolves, with probability `tau`*. Nothing on this desk
measured whether its stops deliver that, so this does - and reports the answer
whether or not it is flattering.

## Why a quantile and not a forecast

This is the one use of a conditional distribution the measurements here
support. `direction-is-closed-not-just-null` has the direction gate finding a
*planted* drift at z +2.90 and earning 2% of a spread, and
`fit-on-the-edge-not-the-raw-score` measured fitted weights beating
hand-tuned ones on AUC 0.604 against 0.556 while **losing on edge, +0.002
against +0.019** - so fitting to a direction or a classification target has
been tried and cost money.

A quantile of the adverse excursion asks nothing about direction. It asks how
far the losing side runs, which is a property of the return distribution, and
the return distribution is where this desk's large measured effects live
(`relationships-are-contemporaneous`).

## Coverage is the statistic, and it can refuse the estimator

A stop at the 90th percentile should be hit about 10% of the time. If it is
hit 25% of the time the quantile is wrong, and no amount of it being
"adaptive" helps. So every estimator here reports its realised coverage
against its target, scored **one step ahead and out of sample** - the stop is
fixed before the excursion is seen, exactly as it is in a trade.

That is the same discipline as `indicators.zigzag.Forecast.skill`, and for the
same reason: an estimator that cannot report itself failing will be trusted
when it is failing.

## The parametric baseline is strong and must be beaten, not assumed past

`no-gaussian-band-is-calibrated` is the measured result: the one-bar Gaussian
band is miscalibrated and **a Student-t with dof 3 to 5 fixes it, 64 of 64 out
of sample**. So a t-quantile at the desk's own measured shape is the baseline,
it is already known to be well calibrated, and an empirical estimator has to
beat its coverage error to earn the extra state. `beats_parametric` is that
comparison and is expected to be close.

`the-walk-is-the-best-calibrated-band` points the same way from the other
side: the walk is what to use for stops, and members lose exactly the spread
on direction.

## What a tight stop costs, which is why `affordable` is here

A quantile stop can come out tighter than the spread justifies, and that is
not a hypothetical. `stop-anchor.md` measured a level-anchored stop running
**0.169 to 0.198 of risk** in cost against this desk's own limit of 0.16
(`domain.costs.MAX_SPREAD_RISK_FRACTION`), putting it outside the envelope on
3 of 6 feeds before any edge was tested. So a stop distance is reported with
whether it clears that limit, and the caller is told rather than left to
divide.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field

from till_infinity.domain.costs import MAX_SPREAD_RISK_FRACTION

#: The share of trades a stop is meant to survive. 0.90, so one in ten is
#: expected to stop out on the excursion alone - chosen, and the point of
#: `Coverage` is that a caller can see whether it is delivered.
TAU = 0.90

#: Degrees of freedom for the parametric baseline. **Measured, not chosen.**
#: `no-gaussian-band-is-calibrated` found a Student-t at dof 3 to 5 fixing the
#: one-bar band on 64 of 64 out-of-sample readings; 4 is the middle of that.
DOF = 4.0

#: How fast the empirical quantile moves on one observation. Small, because a
#: quantile estimated from a handful of excursions is mostly its own initial
#: value and a large gain makes the stop chase the last trade.
GAIN = 0.02


def student_stop(tau: float = TAU, dof: float = DOF) -> float:
    """The `tau` quantile of **|Student-t|** at unit variance, in vol units.

    The baseline an empirical estimator must beat. Computed from the
    distribution rather than tabulated so a caller may move `dof` within the
    measured 3-to-5 range and see the stop move with it.

    **One-sided, and getting that wrong makes every stop too tight.** An
    adverse excursion is a distance against the trade, so it is `|X|`, and the
    `tau` quantile of `|X|` is the `(1 + tau) / 2` quantile of `X` - the 90th
    percentile of the absolute value is the 95th of the signed variable. Using
    the two-sided quantile here put the baseline at 1.08 units where it
    belongs at 1.51, and a stop that tight read a realised coverage of
    **0.20 against a 0.100 target** on `|t(4)|` excursions - twice the
    intended stop-out rate. Measured while writing this, and the exact class
    of error this desk keeps finding: a
    quantity that looks right, is off by a factor, and only shows up when
    somebody checks the coverage.

    Scaled to unit variance so the result is in volatility units and a stop on
    gold and one on eurusd are the same quantity. A t with `dof <= 2` has no
    finite variance and cannot be scaled that way, so it is refused rather
    than returned unscaled.
    """
    if not 0.0 < tau < 1.0:
        raise ValueError(f"tau={tau} is not a quantile; it is a probability in (0, 1)")
    if dof <= 2.0:
        raise ValueError(
            f"dof={dof} has no finite variance, so a unit-scale quantile is not "
            f"defined. The measured range is 3 to 5."
        )
    return _cached(tau, dof)


@functools.lru_cache(maxsize=256)
def _cached(tau: float, dof: float) -> float:
    """`domain.tails.reach`, memoised.

    **Three fixes in one line, each forced by a test.**

    Not scipy: it is absent from `pyproject.toml` and resolves only because
    `river` pulls it in transitively, so
    `test_every_third_party_import_is_declared` turned red the moment this
    module imported it - the exact failure that test exists for. Four modules
    state the policy outright, `node/metrics.py` among them: "hand-rolled
    rather than taking scipy, which would be a dependency for one".

    Not `statespace.tails` either, though it holds the same arithmetic:
    **`risk` may import no layer at all**, which `test_service_boundaries.py`
    pins as `"risk": frozenset()`. Reaching into `statespace` turned two more
    tests red, so the function lives in `domain` - which `risk` may use, and
    which this module already imports `costs` from.

    **Memoised because the in-house version is three times slower per call** -
    about 1,700 us against scipy's 630 - so the swap uncached would have made
    the live path worse rather than better. It takes two floats and returns a
    constant, so there is nothing to invalidate.
    """
    from till_infinity.domain.tails import reach

    return reach(tau, dof)


@dataclass(frozen=True, slots=True)
class Coverage:
    """How often a stop was actually reached, against how often it should be."""

    target: float
    hits: int
    n: int

    @property
    def rate(self) -> float:
        """Realised share of excursions that reached the stop."""
        return self.hits / self.n if self.n else 0.0

    @property
    def excess(self) -> float:
        """Realised minus intended. **Positive means the stop is too tight.**

        Signed deliberately: "miscalibrated by 0.08" does not say whether the
        desk is being stopped out more often than it planned or less, and
        those call for opposite corrections.
        """
        return self.rate - (1.0 - self.target)

    @property
    def enough(self) -> bool:
        """Whether there are enough observations to read the rate at all.

        At a target of one stop-out in ten, thirty trades expect three, and a
        rate read off three events is not a rate. Below this the coverage is
        reported and should not be acted on.
        """
        return self.n >= 30


@dataclass(slots=True)
class Quantile:
    """An online quantile of the adverse excursion, per side, in vol units.

    The update is the standard stochastic approximation on the check loss: the
    estimate rises by `gain * tau` when an excursion exceeds it and falls by
    `gain * (1 - tau)` when it does not, so it settles where the two happen in
    the ratio `tau` to `1 - tau`. Nothing is fitted.

    **Per side**, because the adverse tail is not symmetric: `fear-greed.md`
    measured down moves faster and deeper than up moves, stable across 6 of 6
    eras on audusd at z -4.56 - and that it is a property of the return
    distribution rather than of path structure, which is exactly the kind of
    fact a stop can use and a signal cannot.
    """

    tau: float = TAU
    gain: float = GAIN
    dof: float = DOF
    #: Per side: the estimate, its hit count, and the parametric baseline's.
    state: dict[int, dict[str, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 < self.tau < 1.0:
            raise ValueError(f"tau={self.tau} is not a quantile")
        if not 0.0 < self.gain <= 1.0:
            raise ValueError(
                f"gain={self.gain} is not a step. It multiplies one observation, "
                f"so 0 never moves and above 1 overshoots every time."
            )

    def _side(self, side: int) -> dict[str, float]:
        """This side's state, created on first use.

        **Not `setdefault`.** Python builds a `setdefault` default *eagerly*,
        on every call rather than only when the key is absent, so the
        quantile was being computed twice per observation for a constant -
        measured at 1,499 us an `observe` against `student_stop`'s own 630.
        On a live path that is milliseconds per decision for a number that
        never changes.
        """
        held = self.state.get(side)
        if held is None:
            held = {"q": student_stop(self.tau, self.dof), "hits": 0.0, "flat": 0.0, "n": 0.0}
            self.state[side] = held
        return held

    def observe(self, side: int, excursion: float) -> None:
        """Score the stop this excursion tested, then move the estimate.

        `excursion` is how far price ran against the trade before it resolved,
        in volatility units. **Scored before the update**, which is what makes
        the coverage one-step-ahead: the stop was fixed when the trade opened.

        A negative excursion is refused rather than clamped. Price not moving
        against a trade at all is a real outcome and belongs in the count as a
        zero; a negative one is a sign error in the caller and should surface.
        """
        if excursion < 0.0:
            raise ValueError(
                f"excursion={excursion} is negative. An adverse excursion is a "
                f"distance against the trade, so it is zero or more - a negative "
                f"one means the sign was taken from the wrong side."
            )
        held = self._side(side)
        if excursion >= held["q"]:
            held["hits"] += 1.0
        if excursion >= student_stop(self.tau, self.dof):
            held["flat"] += 1.0
        held["n"] += 1.0
        # The check-loss step, applied after scoring.
        held["q"] += self.gain * (self.tau - (0.0 if excursion >= held["q"] else 1.0))
        held["q"] = max(0.0, held["q"])

    def stop(self, side: int) -> float:
        """The stop distance for `side`, in volatility units.

        The parametric baseline until this side has been seen, because that is
        a measured, well-calibrated starting point rather than a guess - and
        starting an empirical estimator from zero would place the first stops
        at the entry.
        """
        held = self.state.get(side)
        return held["q"] if held else student_stop(self.tau, self.dof)

    def coverage(self, side: int) -> Coverage | None:
        """Realised against intended coverage, or `None` before any trade."""
        held = self.state.get(side)
        if held is None or held["n"] < 1.0:
            return None
        return Coverage(target=self.tau, hits=int(held["hits"]), n=int(held["n"]))

    def parametric(self, side: int) -> Coverage | None:
        """The same, for the fixed Student-t stop, on the same excursions."""
        held = self.state.get(side)
        if held is None or held["n"] < 1.0:
            return None
        return Coverage(target=self.tau, hits=int(held["flat"]), n=int(held["n"]))

    def beats_parametric(self, side: int) -> bool | None:
        """Whether the online estimate is better calibrated than the t.

        **The statistic that decides whether this object is worth its state.**
        `no-gaussian-band-is-calibrated` found a Student-t at dof 3 to 5
        fixing the one-bar band on 64 of 64 out-of-sample readings, so the
        baseline is already good and the honest expectation is that this reads
        false or close to it. `None` until the coverage can be read at all.
        """
        mine, theirs = self.coverage(side), self.parametric(side)
        if mine is None or theirs is None or not mine.enough:
            return None
        return abs(mine.excess) < abs(theirs.excess)


def affordable(
    stop_vol: float,
    spread_vol: float,
    limit: float = MAX_SPREAD_RISK_FRACTION,
) -> str:
    """Empty if a stop this tight can carry its own spread, else why not.

    A quantile stop can come out tighter than the cost justifies, and
    `stop-anchor.md` measured exactly that: a level-anchored stop ran 0.169 to
    0.198 of risk against this desk's limit of 0.16, outside the envelope on 3
    of 6 feeds before any edge was tested.

    A reason string rather than a bool, in the same shape as
    `domain.costs.too_expensive`, because a caller that has to compose the
    sentence will compose a different one.
    """
    if limit <= 0.0 or stop_vol <= 0.0 or spread_vol <= 0.0:
        return ""
    share = spread_vol / stop_vol
    if share <= limit:
        return ""
    return (
        f"a stop at {stop_vol:.2f} volatility units pays {share:.0%} of its risk "
        f"in spread, limit is {limit:.0%}"
    )
