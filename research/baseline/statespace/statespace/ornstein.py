"""A **value** that reverts to a level. The member the family did not have.

Asked for on 2026-10-17, after two separate measurements had to work around its
absence on the same day.

`reverting.Reverting` reverts the **rate** to zero and leaves the value as its
integral, so a level still drifts and the drift dies out. That is the right
model for a price, and it is the wrong model for a magnitude: a quantity that
mean-reverts *in level* - log-variance, a swing depth, a spread's dispersion -
is not an integrated process, and a filter that treats it as one tracks it like
a random walk and loses to its own running mean.

Both of the day's dispersion harnesses hit that and had to write the missing
model themselves:

* `research/docs/dispersion-forecast.md` added an `ou` arm because
  "`reverting`'s mean reversion" - which README item 6 offers as a reason the
  family should work on log-variance - reverts the wrong thing. The pool and
  `s4d` read **negative** R2 there, worse than predicting the mean, while a
  two-parameter AR(1) read positive on every class.
* `statespace/depths.py` added `AR1` for the same reason on turn depth, and
  `subjects.TURN_DEPTH`'s provenance says so in as many words.

A gap that two independent harnesses route around on the same day is a gap in
the family, not in the harnesses. This closes it.

## The model

An Ornstein-Uhlenbeck process on the observed quantity itself:

    d(value) = theta * (level - value) dt + sigma dW

One state. `theta` is the pull per hour, so `ln 2 / theta` is the half-life in
hours - the number a desk can argue with - and `sigma2` is the process
variance per hour. Discretised exactly over a gap, with `a = exp(-theta * dt)`:

    value <- level + a * (value - level)
    P     <- a^2 * P + sigma2 / (2 theta) * (1 - a^2)

and the update is the ordinary scalar Kalman step. The process variance has the
right limit: as `theta -> 0` it becomes `sigma2 * dt`, so the member degenerates
to a local-level random walk rather than to nonsense.

**That degeneracy is this member's own null**, and it is nested. `theta = 0` is
a one-state Kalman on the same series, so comparing the fitted `theta` against
zero on held-out likelihood is a direct test of *does this quantity revert at
all* - no second model, no matched control, just one parameter at the boundary.
Few members here come with a null that cheap.

## The level is **not** a state, and that is the one decision to get right

The obvious design is a second state for `level`, letting the data find it. It
is also the design this package has already measured as a failure:
`definitions-cannot-be-states` records that a mixture centre given as a free
state **collapses onto the data** and three members needed anchors instead.
The same thing happens here and for the same reason - if the level is free, the
filter explains every reading by moving the level, `value - level` stays near
zero, the reversion never fires, and the member silently becomes the random
walk it was written to replace.

So the level is an **anchored slow mean**: an exponentially weighted average of
the readings, kept outside the filter, with its own half-life. The anchor is
the timescale separation, and `__post_init__` enforces it: the level's
half-life must be at least `SEPARATION` times the reversion's. A level that
adapts as fast as the reversion is not a level, it is the value again.

`level_half_life` defaults to a week against a reversion default of a day,
which is a separation of seven. Neither is measured - they are placeholders
that say so, like every other subject parameter here - and the fit is the
ordinary one: `theta` and `sigma2` from a likelihood grid, the level's
half-life from how far the quantity's own mean moves over a sample much longer
than the reversion.

## What it answers that the integrated member cannot

`at_time` far ahead returns the **level**. `reverting`'s returns the value plus
a decaying drift, which for a mean-reverting magnitude is a forecast that never
comes home. That is the whole difference, and it is why the band from this
member narrows to a stationary width over a long gap instead of growing without
bound.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .linear import EXISTENCE_HALF_LIFE_HOURS, HOUR

#: Below this `theta * dt` the exact process variance cancels to nothing in
#: floating point, and the series expansion `sigma2 * dt * (1 - theta * dt)` is
#: used instead. The same guard `reverting._process` needs and for the same
#: reason.
SMALL = 1e-9

#: Reversion half-life, in hours, if a caller names none. A day - a placeholder
#: that says so, chosen because it is the scale at which log-variance is
#: usually described rather than because it was fitted.
HALF_LIFE = 24.0

#: The level's half-life, in hours. A week.
LEVEL_HALF_LIFE = 168.0

#: How much slower the level has to be than the reversion. **The anchor**, and
#: the reason this member does not collapse into a random walk: a level that
#: moves as fast as the value is the value. Seven is the default pair above -
#: a day against a week - and is a floor rather than a target.
SEPARATION = 3.0

#: The grid `theta` is fitted over, as half-lives in hours, plus the two ends
#: that matter. **This is the same likelihood grid everything else in this
#: package fits on, made streaming**: a running residual sum is kept per
#: candidate and the minimiser is taken, which handles irregular sampling
#: exactly because each candidate is evaluated at each step's own `dt`.
#:
#: The ends are the point. `inf` is `theta = 0`, a random walk - the member's
#: own nested null. `0.0` is instant reversion, `theta -> inf`, where the
#: forecast *is* the level and nothing of the current deviation is carried. A
#: quantity with no persistence wants that end, and a fixed `theta` cannot
#: reach it: `dispersion-forecast.md` measured the cost at **-0.73** on
#: shuffled and constant-sigma series where every fitted arm read about zero.
HALF_LIVES: tuple[float, ...] = (
    0.0,
    0.5,
    1.0,
    2.0,
    4.0,
    8.0,
    16.0,
    32.0,
    64.0,
    128.0,
    256.0,
    512.0,
    float("inf"),
)

#: Readings before a fitted `theta` is used. Below this the residual sums are a
#: handful of numbers and the minimiser is noise with a half-life printed on it.
LEARN_LEAST = 60

#: How fast the fit forgets, per reading. The residual sums are exponentially
#: weighted so `theta` can move when the quantity's own persistence does -
#: which is the whole reason to fit it online rather than once.
FORGET = 0.999


def _theta_for(half_life: float) -> float:
    """`ln 2 / half_life`, the pull per hour that gives that half-life.

    Zero gives infinite pull - the forecast is the level - and infinity gives
    no pull at all, a random walk. Both ends are in `HALF_LIVES` on purpose.
    """
    if half_life < 0.0:
        raise ValueError("a half-life cannot be negative")
    if half_life == 0.0:
        return math.inf
    if math.isinf(half_life):
        return 0.0
    return math.log(2.0) / half_life


#: The grid as pulls per hour, built once.
PULLS: tuple[float, ...] = tuple(_theta_for(h) for h in HALF_LIVES)


def _decay(theta: float, dt: float) -> float:
    """`exp(-theta * dt)`, with both ends of the grid handled exactly."""
    if theta <= 0.0:
        return 1.0
    if math.isinf(theta):
        return 0.0
    return math.exp(-theta * dt)


@dataclass(slots=True)
class Ornstein:
    """One state, reverting to an anchored level. Satisfies `family.Filter`."""

    #: Pull per hour. `ln 2 / theta` is the half-life.
    theta: float = _theta_for(HALF_LIFE)
    #: Process variance per hour, in the subject's units squared.
    sigma2: float = 1e-2
    #: The level's half-life in hours. Not a state - see the module note.
    level_half_life: float = LEVEL_HALF_LIFE

    #: The reversion level. Carried as state for persistence, but **learnt by
    #: an anchored slow mean rather than by the filter**, which is the whole
    #: point of this member not collapsing.
    level: float = 0.0
    #: Whether `level` has seen anything yet. Before it has, the first reading
    #: sets it - rather than reverting toward a zero nobody chose.
    anchored: bool = False

    value: float = 0.0
    p00: float = 1.0
    at: float | None = None
    seen: int = 0
    loglike: float = 0.0
    last_standardised: float = 0.0
    existence: float = 1.0
    #: One, not three: there is one state and it is observed directly, so only
    #: the reading that initialises it is excluded from the score.
    burn: int = 1
    #: Whether `theta` is fitted from the readings. **On by default**, because
    #: a fixed `theta` is the member's one measured defect: it carries a share
    #: of the current deviation into every forecast whether the quantity
    #: reverts at that rate or not, and on shuffled and constant-sigma series
    #: that cost **-0.73** of R2 at twenty bars where every fitted arm read
    #: about zero. `False` keeps whatever `theta` was constructed with, which
    #: is what a harness wants when it is measuring the fit itself.
    learn: bool = True
    #: Exponentially weighted **log predictive density**, one per candidate in
    #: `PULLS`, and the shadow state each candidate needs to produce one.
    #:
    #: A density and not a residual sum, and that distinction is the fix for
    #: the one thing a residual sum got wrong. `(d_t - phi d_{t-1})**2` is a
    #: method-of-moments fit on the **filtered** deviations - which the Kalman
    #: gain has already shrunk toward the level - so the implied `phi` is
    #: attenuated and `theta` comes out too slow. It read a 32-hour half-life
    #: on a series whose true one was 9.6. Scoring each candidate by the
    #: density it actually assigns the next reading is the ordinary maximum
    #: likelihood, it accounts for the measurement noise and the posterior
    #: variance that the residual form ignores, and it is the same likelihood
    #: grid every other parameter in this package is fitted on.
    scores: tuple[float, ...] = ()
    _shadow_value: tuple[float, ...] = ()
    _shadow_p00: tuple[float, ...] = ()
    #: Readings the fit has seen. Separate from `seen` because the fit needs a
    #: *pair* of readings and so starts one later.
    learned: int = 0

    #: Unix seconds of the last **reading**, which is not `at`: `predict` moves
    #: `at` without one. The level's half-life is in hours, so it needs the
    #: elapsed time between readings and not a count of them - the same
    #: distinction `selective.read_at` exists for, and getting it wrong makes a
    #: weekly level mean "a week of bars" on one feed and "a week of ticks" on
    #: another.
    read_at: float | None = None

    def __post_init__(self) -> None:
        if math.isnan(self.theta) or self.theta < 0.0:
            raise ValueError("theta cannot be negative")
        if self.sigma2 < 0.0:
            raise ValueError("sigma2 cannot be negative")
        if self.level_half_life <= 0.0:
            raise ValueError("the level's half-life has to be positive")
        if self.theta > 0.0 and not math.isinf(self.theta):
            reversion = math.log(2.0) / self.theta
            if self.level_half_life < SEPARATION * reversion:
                raise ValueError(
                    f"the level's half-life is {self.level_half_life:.1f}h against a "
                    f"reversion half-life of {reversion:.1f}h, a separation of "
                    f"{self.level_half_life / reversion:.1f} where {SEPARATION} is the "
                    "floor. A level that adapts as fast as the value is the value, and "
                    "this member then collapses into the random walk it replaces."
                )

    # ------------------------------------------------------------------ predict

    def predict(self, when: float) -> None:
        """Advance to `when`. The value decays **toward the level**, not to zero."""
        if self.at is None:
            self.at = float(when)
            return
        dt = (float(when) - self.at) / HOUR
        self.at = float(when)
        if dt <= 0.0:
            return

        theta = max(self.theta, 0.0)
        step = theta * dt
        decay = _decay(theta, dt)
        self.value = self.level + decay * (self.value - self.level)

        if math.isinf(theta):
            # Instant reversion: the value *is* the level, so there is no
            # carried uncertainty and nothing accumulates either - `decay` is
            # zero, so the line below leaves `p00` at zero.
            grown = 0.0
        elif step > SMALL:
            # sigma2 / (2 theta) * (1 - e^{-2 theta dt}), with expm1 for the
            # small end of the range this branch still covers.
            grown = -math.expm1(-2.0 * step) * max(self.sigma2, 0.0) / (2.0 * theta)
        else:
            # The limit as theta -> 0, to first order. A random walk's variance.
            grown = max(self.sigma2, 0.0) * dt * (1.0 - step)
        self.p00 = decay * decay * self.p00 + grown

        if self.existence > 0.0:
            self.existence *= 0.5 ** (dt / EXISTENCE_HALF_LIFE_HOURS)

    # ------------------------------------------------------------------- update

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold in one noisy reading. Returns the innovation."""
        if not math.isfinite(measured) or not math.isfinite(noise) or noise < 0.0:
            return 0.0
        if when is not None:
            self.predict(when)

        if not self.anchored:
            # The first reading sets the level, which is the honest start: a
            # level of zero would make the member revert toward a number
            # nobody chose, and on log-variance near -18 that is catastrophic
            # rather than merely wrong.
            self.level = float(measured)
            self.anchored = True

        if not self.seen:
            self.value = float(measured)
            self.p00 = float(noise)
            self.seen = 1
            self.existence = 1.0
            self.read_at = self.at
            return 0.0

        innovation = float(measured) - self.value
        s = self.p00 + float(noise)
        if s <= 0.0:
            return innovation

        self.last_standardised = innovation / math.sqrt(s)
        if self.seen >= self.burn:
            self.loglike += -0.5 * (math.log(2.0 * math.pi * s) + innovation * innovation / s)

        gain = self.p00 / s
        self.value += gain * innovation
        self.p00 -= gain * self.p00

        self.seen += 1
        self.existence = min(1.0, self.existence + (1.0 - self.existence) * 0.5)
        # **After the score, never before.** The level is a slow mean of the
        # readings, and folding this reading in before scoring it would let the
        # level see the answer.
        hours = 0.0
        if self.read_at is not None and self.at is not None:
            hours = max((self.at - self.read_at) / HOUR, 0.0)
        self._settle(measured, hours)
        # **After the level has settled**, so each shadow filter reverts toward
        # the level that was in force, and before `read_at` moves, so the fit
        # sees the gap it is fitting over.
        self._fit(measured, noise, hours)
        self.read_at = self.at
        return innovation

    def _fit(self, measured: float, noise: float, hours: float) -> None:
        """Score every candidate `theta` by the density it gave this reading.

        **Maximum likelihood, not a residual sum.** Each candidate runs its own
        one-state shadow filter - a predict to this reading's time at that
        candidate's pull, a log density for the reading, then an update - and
        the running sum of those densities is what the grid is ranked on. That
        is the ordinary MLE for this model and it is the same likelihood grid
        every other parameter in this package is fitted on.

        The residual form it replaces was a method-of-moments fit on the
        **filtered** deviations, which the Kalman gain has already pulled
        toward the level, so the implied decay was attenuated and the half-life
        came out slow - 32 hours where the truth was 9.6. A density also sees
        the measurement noise and the posterior variance, which a residual
        cannot.

        The grid is evaluated at **this step's own gap**, so irregular sampling
        is exact rather than approximated by a nominal bar length, and the two
        ends of the grid are what let it say *no reversion* and *instant
        reversion* - neither of which a fixed `theta` can reach.

        One `theta`, and **no horizon in the signature**. If the model is right
        its one-step dynamics determine every horizon, so an h-step forecast
        needs no separate fit; where an h-step score disagrees the model is
        misspecified, and `research/docs/dispersion-forecast.md` measures which
        parameter is actually responsible - the level, not the pull.
        """
        if not self.scores:
            self.scores = (0.0,) * len(PULLS)
            self._shadow_value = (float(measured),) * len(PULLS)
            self._shadow_p00 = (max(float(noise), SMALL),) * len(PULLS)
            self.learned += 1
            return

        fresh, values, spreads = [], [], []
        for theta, carried, value, p00 in zip(
            PULLS, self.scores, self._shadow_value, self._shadow_p00, strict=True
        ):
            decay = _decay(theta, hours) if hours > 0.0 else 1.0
            moved = self.level + decay * (value - self.level)
            if math.isinf(theta):
                grown = 0.0
            else:
                step = theta * hours
                if step > SMALL:
                    grown = -math.expm1(-2.0 * step) * max(self.sigma2, 0.0) / (2.0 * theta)
                else:
                    grown = max(self.sigma2, 0.0) * hours
            prior = decay * decay * p00 + grown
            s = prior + max(float(noise), 0.0)
            if s <= 0.0:
                s = SMALL
            err = float(measured) - moved
            fresh.append(FORGET * carried - 0.5 * (math.log(2.0 * math.pi * s) + err * err / s))
            gain = prior / s
            values.append(moved + gain * err)
            spreads.append(prior - gain * prior)

        self.scores = tuple(fresh)
        self._shadow_value = tuple(values)
        self._shadow_p00 = tuple(spreads)
        if self.learn and self.learned >= LEARN_LEAST:
            best = max(range(len(PULLS)), key=lambda i: self.scores[i])
            # Floored so the anchor survives: the reversion has to stay at
            # least `SEPARATION` times faster than the level, or the level is
            # the value again and the member collapses.
            floor = SEPARATION * math.log(2.0) / self.level_half_life
            self.theta = max(PULLS[best], floor)
        self.learned += 1

    @property
    def fitted_half_life(self) -> float:
        """The half-life the fit currently prefers, or `nan` before it is warm."""
        if not self.scores or self.learned < LEARN_LEAST:
            return float("nan")
        best = max(range(len(PULLS)), key=lambda i: self.scores[i])
        return HALF_LIVES[best]

    def _settle(self, measured: float, hours: float) -> None:
        """Move the level toward the reading, on its own half-life in hours.

        **In hours, not per reading.** The share is
        `1 - 0.5 ** (hours / half_life)`, so a gap moves the level further than
        a dense stretch does and a weekly level means a week on every feed.
        A zero-length step moves it not at all, which is the right answer: two
        venues printing the same instant are one observation of the level.
        """
        if hours <= 0.0:
            return
        share = 1.0 - 0.5 ** (hours / self.level_half_life)
        self.level += share * (float(measured) - self.level)

    # ------------------------------------------------------- the four quantities

    @property
    def rate(self) -> float:
        """Per hour, from the dynamics: `theta * (level - value)`.

        Read off the model rather than kept in a slot, because an OU has no
        rate state - its drift is wholly determined by where the value sits
        relative to the level, which is the content of the model.
        """
        return self.theta * (self.level - self.value)

    @property
    def sd(self) -> float:
        return math.sqrt(max(self.p00, 0.0))

    @property
    def half_life_hours(self) -> float:
        """`ln 2 / theta`, or infinity where the pull is zero - a random walk."""
        return math.log(2.0) / self.theta if self.theta > 0.0 else float("inf")

    @property
    def stationary_sd(self) -> float:
        """The spread this member settles at over a long gap: `sqrt(sigma2 / 2 theta)`.

        The quantity an integrated member cannot have. `reverting`'s variance
        grows without bound as the gap grows; this one converges, which is what
        makes a far-ahead band from it finite and worth reading.
        """
        if self.theta <= 0.0:
            return float("inf")
        if math.isinf(self.theta):
            return 0.0
        return math.sqrt(max(self.sigma2, 0.0) / (2.0 * self.theta))

    def at_time(self, when: float) -> float:
        """The value at a future time, which **converges to the level**."""
        if self.at is None:
            return self.value
        dt = (float(when) - self.at) / HOUR
        if dt <= 0.0 or self.theta <= 0.0:
            return self.value
        return self.level + _decay(self.theta, dt) * (self.value - self.level)

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        """A band at a future time, which **stops widening**.

        It approaches `level +/- sigmas * stationary_sd` rather than growing
        without bound, and that difference is the reason this member exists.
        """
        middle = self.at_time(when)
        dt = 0.0 if self.at is None else max((float(when) - self.at) / HOUR, 0.0)
        theta = max(self.theta, 0.0)
        step = theta * dt
        decay = _decay(theta, dt)
        if math.isinf(theta):
            grown = 0.0
        elif step > SMALL:
            grown = -math.expm1(-2.0 * step) * max(self.sigma2, 0.0) / (2.0 * theta)
        else:
            grown = max(self.sigma2, 0.0) * dt
        spread = math.sqrt(max(decay * decay * self.p00 + grown, 0.0))
        return middle - sigmas * spread, middle + sigmas * spread

    def predictive(self, measured: float, noise: float = 0.0) -> float:
        """Log density of a reading under the current one-step predictive."""
        s = self.p00 + max(float(noise), 0.0)
        if s <= 0.0:
            return 0.0
        err = float(measured) - self.value
        return -0.5 * (math.log(2.0 * math.pi * s) + err * err / s)

    # ------------------------------------------------- what a smoother needs

    NAMES: tuple[str, ...] = ("value",)
    OUTPUTS: tuple[str, ...] = ("value",)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        """`C`: the one state is the observed quantity."""
        return ((1.0,),)

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    def state(self) -> tuple[float, ...]:
        return (self.value,)

    def covariance(self) -> tuple[tuple[float, ...], ...]:
        """One state, so one number - and it exists, so this member smooths."""
        return ((self.p00,),)

    def transition(self, dt: float) -> tuple[tuple[float, ...], ...]:
        """`F(dt) = exp(-theta * dt)`, a single stable pole inside the unit circle.

        `spectrum.py` reads this, and what it will say is the point: the pole
        is strictly inside the circle for any positive `theta`, where
        `linear`'s all sit **on** it and `reverting`'s value pole does too. A
        member whose slowest mode is an hour cannot carry a weekly level, and
        here that is visible from one number.
        """
        theta = max(self.theta, 0.0)
        return ((_decay(theta, max(float(dt), 0.0)),),)
