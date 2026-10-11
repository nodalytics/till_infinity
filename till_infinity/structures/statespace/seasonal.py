"""A seasonal in state space: phase-locked to the clock, not to the bar.

Nothing in this package was seasonal before this. `oscillator.py` cycles, but
a **stochastic cycle is not a seasonal** and the difference is the whole point
of this module:

* the oscillator's phase is a free state. It drifts, and fitted on real series
  it came back at `zeta = 67` - overdamped, no oscillation left at all;
* a seasonal is **locked to wall-clock time**. Noon UTC is noon UTC every day,
  and the component has to be at the same point in its cycle then, whatever
  the market did in between.

That lock is also what makes it portable. The standard textbook seasonal
carries one state per period *step* - eleven states for monthly data, twenty-
three for hourly - which is a bar count in disguise, and a twenty-four-bar
seasonal means a day at 1h and four days at 4h. Here the rotation angle is
`2 pi j dt / period` with `dt` in **hours**, so a 24-hour seasonal is a day at
every timeframe and the same fitted shape survives a change of frame.

## The trigonometric form, and why not dummies

Two ways to write a seasonal as states. **Dummy** form keeps one state per
step of the period, constrained to sum to zero; **trigonometric** form keeps a
rotating pair per harmonic. They span the same space when the harmonics are
complete, and the trigonometric form is the one that works here for three
reasons:

* it takes `dt` continuously, so irregular bars and weekend gaps need no
  special case - a gap of 63 hours rotates by 63 hours;
* it is **truncatable**. Three harmonics of a daily period give a smooth
  six-parameter shape rather than a 24-parameter one, which is the difference
  between a fitted profile and a memorised one;
* each harmonic is a plane rotation, so the transition is exactly orthogonal
  and the component neither grows nor decays. A seasonal that decays is not a
  seasonal.

## The seasonal is allowed to change, slowly

`wander` gives each harmonic's pair a small process noise, which makes this a
**stochastic** seasonal: the daily shape can evolve over months without being
re-fitted. Set it to zero and the shape is fixed forever, which is the right
choice only if the claim is that a session profile never changes - and the
desk's own evidence is against that, since the up/down edge died.

## What it has to be scored against

Three nulls, and the third is the one that matters:

* **level only** - the same member with the seasonal harmonics' noise at zero
  and their states pinned, which is a random walk. The usual comparison.
* **a rotated phase** - the identical member fitted to the same series with
  every timestamp shifted by half a period. If a shifted phase fits as well,
  the member is reading a smooth function of something else and the lock to
  the clock is doing no work.
* **a generated market** - the Deriv synthetics have no sessions, so a
  seasonal amplitude that appears on `Volatility_75_Index` is the member
  fitting noise with six spare parameters.

The second is specific to seasonals and is easy to forget. A flexible periodic
component will always explain *some* variance; the question is whether it
needs to be aligned with the clock to do it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

HOUR = 3600.0
TAU = 2.0 * math.pi

#: Periods in hours. A day and a week, because those are the two the sessions
#: and the weekend impose, and because a weekly period at 168 hours is a
#: different question from a daily one at 24.
PERIODS = (24.0, 168.0)

#: Harmonics per period. Three gives a smooth shape with two bumps, which is
#: what a session profile looks like; the fourth and beyond start fitting
#: single hours.
HARMONICS = 3

#: Per-hour process noise on the level, and on each harmonic's pair.
#:
#: The seasonal wander is three orders smaller than the level's on purpose: a
#: session profile that can move as fast as the price is not a profile, it is
#: a second copy of the level wearing a sine wave.
LEVEL_WANDER = 1e-3
WANDER = 1e-6


@dataclass(slots=True)
class Seasonal:
    """A level plus phase-locked harmonics, as one linear filter.

    The state is `[level, a_1, b_1, a_2, b_2, ...]` with one `(a, b)` pair per
    harmonic per period. The observation is `level + sum(a_j)`, because each
    pair's `a` is its contribution at the current phase and `b` is the
    quadrature term that carries it forward.
    """

    periods: tuple[float, ...] = PERIODS
    harmonics: int = HARMONICS
    level_wander: float = LEVEL_WANDER
    wander: float = WANDER

    #: Off makes this **the matched null for itself**: the same level filter,
    #: the same level noise, the same anchor, the harmonics simply not
    #: observed. Comparing against `Walk` instead would compare two models
    #: with different level noise, and the gain would be calibration rather
    #: than seasonality - the trap `jpy-silver-pair.md` records costing a
    #: +99,444 false positive.
    #:
    #: With the matched null the member is honest about having spare
    #: parameters. On three thousand hours of a level walk:
    #:
    #: | series | gain over level-only | amplitude |
    #: | --- | --- | --- |
    #: | a real 24h seasonal | +38,873 | 1.139 (true 1.077) |
    #: | a weak one, a fifth the size | +1,528 | 0.281 |
    #: | none at all | **-39** | 0.080 |
    #:
    #: The negative gain on a flat series is the point: six extra states cost
    #: likelihood when they have nothing to explain, so the comparison cannot
    #: be won by flexibility alone.
    seasonal_on: bool = True

    #: The whole state and its covariance.
    values: list[float] = field(default_factory=list)
    covariance: list[list[float]] = field(default_factory=list)

    #: Where the level starts, fixed at the first reading rather than at zero.
    #: An uncentred level has to travel the price's whole magnitude before the
    #: seasonal sees anything but the gap, and the harmonics absorb that
    #: journey - which is the same anchor defect `relating` and `panel` have.
    anchor: float | None = None

    at: float | None = None
    seen: int = 0
    loglike: float = 0.0
    burn: int = 20
    existence: float = 1.0
    last_standardised: float = 0.0

    def __post_init__(self) -> None:
        if self.harmonics < 1:
            raise ValueError("a seasonal needs at least one harmonic")
        if any(p <= 0 for p in self.periods):
            raise ValueError("periods are in hours and must be positive")
        size = self.width
        if not self.values:
            self.values = [0.0] * size
        if not self.covariance:
            # The level starts uncertain and the harmonics start near zero
            # with a prior that says "probably no seasonal", so the member has
            # to earn the amplitude rather than beginning with one.
            self.covariance = [
                [1.0 if i == j and i == 0 else (0.01 if i == j else 0.0) for j in range(size)]
                for i in range(size)
            ]

    # ------------------------------------------------------------------ shape

    @property
    def width(self) -> int:
        return 1 + 2 * self.harmonics * len(self.periods)

    @property
    def level(self) -> float:
        base = self.anchor or 0.0
        return base + self.values[0]

    @property
    def season(self) -> float:
        """The seasonal contribution at the current phase."""
        if not self.seasonal_on:
            return 0.0
        return sum(self.values[1 + 2 * k] for k in range(self.harmonics * len(self.periods)))

    @property
    def amplitude(self) -> float:
        """Root-sum-square of the harmonics: how big the seasonal is at all.

        **The number to compare against the nulls.** A member fitting noise
        with spare parameters still produces an amplitude, so this means
        nothing until a generated market's amplitude is beside it.
        """
        total = 0.0
        for k in range(self.harmonics * len(self.periods)):
            a = self.values[1 + 2 * k]
            b = self.values[2 + 2 * k]
            total += a * a + b * b
        return math.sqrt(total)

    @property
    def value(self) -> float:
        return self.level + self.season

    @property
    def rate(self) -> float:
        return 0.0

    @property
    def sd(self) -> float:
        row = self._row()
        total = 0.0
        for i, left in enumerate(row):
            if left == 0.0:
                continue
            for j, right in enumerate(row):
                if right != 0.0:
                    total += left * self.covariance[i][j] * right
        return math.sqrt(max(total, 0.0))

    def state(self) -> tuple[float, ...]:
        return tuple(self.values)

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        return (tuple(self._row()),)

    def _row(self) -> list[float]:
        """`H`: the level, plus every harmonic's in-phase term when on."""
        row = [0.0] * self.width
        row[0] = 1.0
        if self.seasonal_on:
            for k in range(self.harmonics * len(self.periods)):
                row[1 + 2 * k] = 1.0
        return row

    # ------------------------------------------------------------- the clock

    def _angles(self, hours: float) -> list[float]:
        """Rotation per harmonic over `hours`. One angle per `(a, b)` pair."""
        return [
            TAU * j * hours / period
            for period in self.periods
            for j in range(1, self.harmonics + 1)
        ]

    def profile(self, when: float, period: float | None = None) -> float:
        """The fitted seasonal at an arbitrary time, for plotting the shape.

        Reads the component forward to `when` without touching the state, so a
        caller can walk 24 hours and get the daily profile the member has
        learnt. `period` restricts the reading to one period's harmonics,
        which is how the daily and weekly parts are told apart.
        """
        if self.at is None or not self.seasonal_on:
            return 0.0
        hours = (float(when) - self.at) / HOUR
        total = 0.0
        index = 0
        for this in self.periods:
            for j in range(1, self.harmonics + 1):
                if period is None or this == period:
                    angle = TAU * j * hours / this
                    a = self.values[1 + 2 * index]
                    b = self.values[2 + 2 * index]
                    total += a * math.cos(angle) + b * math.sin(angle)
                index += 1
        return total

    def at_time(self, when: float) -> float:
        """The level, plus the seasonal rotated forward to `when`.

        **This is the forecast a seasonal exists to make.** Every other member
        here projects a level and a rate; this one also knows that in six
        hours it will be a different time of day, and says so.
        """
        return self.level + self.profile(when)

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        middle = self.at_time(when)
        width = sigmas * self.sd
        return (middle - width, middle + width)

    # ---------------------------------------------------------- the machinery

    def predict(self, when: float, control: float = 0.0) -> None:  # noqa: ARG002
        """Rotate every harmonic by the elapsed time, then inflate.

        The level is a random walk and each harmonic is an exact plane
        rotation, so the transition is block diagonal with one 1x1 and one 2x2
        block per harmonic. Written out as blocks rather than as a full matrix
        multiply because the full `F` is almost all zeros - at the default
        settings it is 13x13 with 25 non-zero entries - and because the
        rotation has to stay exactly orthogonal. Accumulating it through a
        general matrix product loses that to rounding and a seasonal that
        slowly gains energy is worse than none.
        """
        if self.at is None:
            self.at = float(when)
            return
        hours = (float(when) - self.at) / HOUR
        if hours <= 0:
            return
        angles = self._angles(hours)
        size = self.width

        # The state: level held, each pair rotated.
        for k, angle in enumerate(angles):
            cos, sin = math.cos(angle), math.sin(angle)
            a = self.values[1 + 2 * k]
            b = self.values[2 + 2 * k]
            self.values[1 + 2 * k] = cos * a + sin * b
            self.values[2 + 2 * k] = -sin * a + cos * b

        # The covariance: `F P F'`, applied as rotations on rows then columns.
        for k, angle in enumerate(angles):
            cos, sin = math.cos(angle), math.sin(angle)
            one, two = 1 + 2 * k, 2 + 2 * k
            for j in range(size):
                a, b = self.covariance[one][j], self.covariance[two][j]
                self.covariance[one][j] = cos * a + sin * b
                self.covariance[two][j] = -sin * a + cos * b
            for i in range(size):
                a, b = self.covariance[i][one], self.covariance[i][two]
                self.covariance[i][one] = cos * a + sin * b
                self.covariance[i][two] = -sin * a + cos * b

        self.covariance[0][0] += self.level_wander * hours
        for k in range(len(angles)):
            self.covariance[1 + 2 * k][1 + 2 * k] += self.wander * hours
            self.covariance[2 + 2 * k][2 + 2 * k] += self.wander * hours

        self.at = float(when)

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        """Fold in one reading of `level + season`.

        The observation is scalar, so the gain is a vector and no matrix needs
        inverting - which is why this member can carry thirteen states and
        still cost what `linear` costs.
        """
        if when is not None and self.at is None:
            self.at = float(when)
        if not math.isfinite(measured):
            return 0.0
        if self.anchor is None:
            # Anchored at the first reading, so the level does not have to
            # travel the price's magnitude with the harmonics absorbing the
            # journey. Third member to need this; see `relating` and `panel`.
            self.anchor = float(measured)

        size = self.width
        row = self._row()
        residual = float(measured) - self.value

        # `P H'`, then `H P H' + R`.
        gain_raw = [sum(self.covariance[i][j] * row[j] for j in range(size)) for i in range(size)]
        spread = sum(row[i] * gain_raw[i] for i in range(size)) + max(noise, 1e-12) ** 2
        if spread <= 0:
            return 0.0
        gain = [g / spread for g in gain_raw]

        self.seen += 1
        if self.seen > self.burn:
            self.loglike += -0.5 * (math.log(TAU * spread) + residual * residual / spread)
        self.last_standardised = residual / math.sqrt(spread)

        for i in range(size):
            self.values[i] += gain[i] * residual

        # `(I - K H) P`, in the symmetric Joseph-free form. Symmetrised at the
        # end because the asymmetry this accumulates is what eventually makes
        # a covariance indefinite, and a seasonal runs for thousands of steps.
        for i in range(size):
            for j in range(size):
                self.covariance[i][j] -= gain[i] * gain_raw[j]
        for i in range(size):
            for j in range(i + 1, size):
                shared = 0.5 * (self.covariance[i][j] + self.covariance[j][i])
                self.covariance[i][j] = self.covariance[j][i] = shared
            self.covariance[i][i] = max(self.covariance[i][i], 0.0)

        return self.last_standardised


#: Harmonics for a clock profile. Three, for the same reason the member uses
#: three: a session shape has two or three bumps, and the fourth starts
#: fitting single hours.
PROFILE_HARMONICS = 3


@dataclass(slots=True)
class Profile:
    """A time-of-day profile on the **spread**, for driving `Q`.

    This is where the seasonal actually lives, and the measurement says so.
    Scored against its own matched null over ten traded instruments at 1h:

    | the profile multiplies | median gain | clock broken | generated markets |
    | --- | --- | --- | --- |
    | `Q`, the level's own wander | **+219** | -482 | -1.6 |
    | `R`, the measurement spread | +43, signs mixed | - | - |
    | nothing - the level's harmonics | **-585** | -583 | -460 |

    The three rows are the whole finding. A **phase-locked seasonal on the
    level earns nothing** - it lost to its own matched null in all 26 cells
    tested, by 368 to 779 nats - because a daily pattern in how far the market
    moves says nothing about which way it moves, and the level observes the
    way. Put the same profile on **how far**, and every traded instrument
    gains while every generated market does not.

    `R` is the wrong door and it is worth saying why: scaling the measurement
    spread tells the filter to *distrust* the readings during the busy hours,
    which is close to the opposite of the truth. Scaling `Q` says price
    genuinely travels further then, which is what an intraday volatility
    profile is.

    ## What it finds

    Fitted on FX and metals at 1h the profile has a peak-to-trough ratio of
    **2.7 to 3.7** and peaks at **14:00-15:00 UTC** on every one of them - the
    London and New York overlap. Crypto is flatter at 1.7 to 1.8, which is
    what a market without a session close should look like. The Deriv
    synthetics come in at 1.04 to 1.08: no profile, as a specified
    constant-sigma process should have none, and that is the control.

    ## How many harmonics a timeframe can carry

    **A daily profile cannot be fitted from four-hourly bars at three
    harmonics**, and this is a sampling limit rather than a convention. Bars
    four hours apart visit only six hours of the day, so the design matrix
    has rank at most six and seven coefficients are not identifiable - the
    normal equations are singular and `fit` refuses. At the Nyquist point the
    highest harmonic is degenerate as well: with six samples a day the third
    harmonic's sine term is identically zero at every sample.

    So `fit` reads the data's own spacing and caps the harmonics at what the
    spacing can carry, `(distinct - 1) // 2`. At 1h that is three, which is
    the default; at 4h it is two; at 1d a daily profile is not a question.
    `harmonics` on the returned profile says what was actually used, which is
    not always what was asked for.

    This is the one place in this package where a **bar count is the right
    unit**: the question is how many times a day the series is sampled, and
    that is a count of samples, not a duration.

    ## Fit it on one stretch and use it on another

    `fit` takes the half of the history a caller is willing to spend. A
    profile fitted on everything and then scored on everything is a profile
    scored on its training data, and with seven free coefficients that is not
    a small difference. The numbers above are all out of sample.
    """

    #: `[mean, cos_1, sin_1, cos_2, sin_2, ...]` on the **log** scale, so the
    #: profile multiplies a spread rather than adding to it. The right scale
    #: for a quantity that cannot go negative, and it makes the output a
    #: ratio.
    weights: tuple[float, ...] = ()
    harmonics: int = PROFILE_HARMONICS

    #: The period the profile repeats over, in hours. A day by default; a week
    #: is the other one worth trying, and the weekend gap makes it harder.
    period: float = 24.0

    @property
    def fitted(self) -> bool:
        return len(self.weights) == 1 + 2 * self.harmonics

    def _basis(self, when: float) -> list[float]:
        hours = (float(when) % (self.period * HOUR)) / HOUR
        row = [1.0]
        for j in range(1, self.harmonics + 1):
            angle = TAU * j * hours / self.period
            row.extend((math.cos(angle), math.sin(angle)))
        return row

    def at(self, when: float) -> float:
        """The profile at `when`, as a multiple averaging one over the cycle."""
        if not self.fitted:
            return 1.0
        row = self._basis(when)
        fitted = sum(a * b for a, b in zip(row, self.weights, strict=True))
        return math.exp(fitted - self.weights[0])

    def wander(self, base: float, when: float) -> float:
        """A per-hour **variance** for `Q` at `when`, from a base variance.

        Squared, because the profile was fitted to a standard deviation: a
        threefold profile in size is a ninefold one in variance. Getting this
        exponent wrong is the difference between a profile that helps and one
        that overshoots every busy hour.
        """
        factor = self.at(when)
        return base * factor * factor

    def shape(self) -> list[float]:
        """The profile hour by hour over one period, for reading or plotting."""
        steps = max(round(self.period), 1)
        return [self.at(h * HOUR) for h in range(steps)]

    def extent(self) -> float:
        """Peak over trough. One means no profile; FX at 1h gives 2.7 to 3.7."""
        shape = self.shape()
        low = min(shape)
        return max(shape) / low if low > 0 else math.inf

    @classmethod
    def fit(
        cls,
        times: Sequence[float],
        values: Sequence[float],
        *,
        harmonics: int = PROFILE_HARMONICS,
        period: float = 24.0,
    ) -> Profile | None:
        """Least squares of `log|step|` on the harmonics of the clock.

        `values` are levels - log prices, normally - and the steps between
        them are the sizes the profile describes. Returns `None` rather than a
        flat profile when there is too little to fit or the normal equations
        are singular, because a silently flat profile would be indistinguishable
        from a real one that happens to be flat.
        """
        pairs = [
            (float(times[i]), abs(float(values[i]) - float(values[i - 1])))
            for i in range(1, min(len(times), len(values)))
        ]
        pairs = [(t, v) for t, v in pairs if v > 0]
        if len(pairs) < 50:
            return None

        # How many distinct phases the sampling actually visits, and so how
        # many harmonics are identifiable. Counted from the data rather than
        # taken on trust, because a series with gaps visits fewer phases than
        # its nominal spacing suggests.
        seen_phases = {round((t % (period * HOUR)) / HOUR, 3) for t, _ in pairs}
        allowed = max((len(seen_phases) - 1) // 2, 0)
        harmonics = min(harmonics, allowed)
        if harmonics < 1:
            return None

        width = 1 + 2 * harmonics
        if len(pairs) < 50 * width:
            return None

        empty = cls(weights=(), harmonics=harmonics, period=period)
        normal = [[0.0] * width for _ in range(width)]
        target = [0.0] * width
        for when, size in pairs:
            row = empty._basis(when)
            value = math.log(size)
            for i in range(width):
                target[i] += row[i] * value
                for j in range(width):
                    normal[i][j] += row[i] * row[j]

        # Gauss-Jordan with partial pivoting. Seven unknowns, so an explicit
        # solve is cheaper than a dependency and keeps this importable on a
        # machine with nothing installed - which is the whole point of the
        # package having no hard numeric dependency.
        for col in range(width):
            pivot = max(range(col, width), key=lambda r: abs(normal[r][col]))
            if abs(normal[pivot][col]) < 1e-12:
                return None
            normal[col], normal[pivot] = normal[pivot], normal[col]
            target[col], target[pivot] = target[pivot], target[col]
            scale = normal[col][col]
            normal[col] = [v / scale for v in normal[col]]
            target[col] /= scale
            for index in range(width):
                if index == col:
                    continue
                factor = normal[index][col]
                if factor == 0.0:
                    continue
                normal[index] = [
                    a - factor * b for a, b in zip(normal[index], normal[col], strict=True)
                ]
                target[index] -= factor * target[col]

        return cls(weights=tuple(target), harmonics=harmonics, period=period)
