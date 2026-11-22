"""Activity as the second door onto `Q`: how far, driven by how busy.

`seasonal.Profile` drives `Q` from the **clock** and earns +1055 nats median on
traded instruments at 1h. `statespace-volume-clock.md` then asked whether the
clock is really about time, and answered no: resampling into **volume time**
absorbs about three-quarters of the profile - `extent` falls from 2.99 to 1.72
against a 1.31 noise floor - which is the subordination result of Clark 1973
and Ane-Geman 2000. 14:00 UTC is not special; it is busy.

That makes activity the more fundamental variable and the clock a proxy for it,
and it predicts something the clock cannot do: a **quiet 14:00 should be
quiet**. A time-of-day profile raises `Q` every day at 14:00 whatever the
market is actually doing, and on a holiday it is simply wrong. Activity is
observed per bar, so it is right on the days the profile is wrong.

## Why this is `Q` and not `B u`

The same reason `driven.py` gives for the clock, and it is worth repeating
because activity is the input most likely to be mistaken for a direction: a
busy bar says price travelled **further**, not which way. Volume is unsigned.
Putting it in `B u` would assert that heavy trading pushes price up, which is
a claim this desk has refuted in every form it has tested.

## The exponent is a real question, not a copy of the clock's

`Profile.factor` squares, because the profile was fitted to a **standard
deviation** and a variance is its square. Activity is not a fitted size, so
the exponent is open, and the two candidate answers differ by a lot:

* **`1.0`** - subordination. Variance is proportional to the number of price
  changes, because the bar is a sum of that many increments. This is what
  Clark's mixture-of-distributions hypothesis says and it is the default here;
* **`2.0`** - if share were standing in for a size the way the clock's profile
  does, it would need squaring like the clock's.

A twofold busy bar gets `2x` the variance under the first and `4x` under the
second, so getting it wrong overshoots every busy bar by its own square. It is
`exponent` rather than a constant because the harness sweeps it.

## The generated feeds are the control, with nothing special done for them

Deriv's synthetics post **exactly constant** tick volume - `Volatility_75`
gives 1800 ticks an hour, interquartile range zero. So `share` is identically
one on them, the factor is identically one, and the mechanism is off on the
markets whose generator says it should be off. The control arm needs no flag,
which is the strongest form a control can take: the member cannot tell whether
it is in the control group and neither can the caller.

## It averages one, which is the whole reason there is a mean to divide by

A lever whose multiplier does not average one changes the member's *average*
process noise as well as its variation, and the two effects are then not
separable: a gain that looks like it helped may only have raised `Q` overall,
which a refit of the base would have done without any input at all. That
mistake reversed a +1192 result to -24 on this desk once already.

So `share` is volume over its own exponential mean, which averages one by
construction, and `control` returns `share ** exponent - 1` so that
`driven.Driven`'s `1 + gain * u` is exactly `share ** exponent` at unit gain
and exactly `1.0` on an average bar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Bars to forget over, matching `context.activity` and the volatility
#: estimator. Activity clusters the way volatility does and for the same
#: reasons, so it should forget at the same rate.
HALF_LIFE = 60.0

#: Bars before `share` is anything but one. An exponential mean over a handful
#: of bars is mostly the first bar, and a ratio to it is noise with a
#: multiplier's authority.
WARMUP = 30

#: Variance per unit of activity. See the module docstring: `1.0` is
#: subordination, `2.0` would be the clock's own exponent.
EXPONENT = 1.0

#: A share beyond this is a venue resetting a counter or a session gap counted
#: as one bar, not a real burst. Letting it through would hand `Q` a
#: twentyfold variance on a data artefact, and `Driven` has no ceiling of its
#: own - only a floor.
MAX_SHARE = 20.0


def _alpha(half_life: float) -> float:
    return 1.0 - 0.5 ** (1.0 / max(half_life, 1e-9))


@dataclass(slots=True)
class Pace:
    """One instrument-and-timeframe's typical bar, as a `Q` multiplier.

    Not `Restorable` and not persisted: see `CODEC_UNPERSISTED` in this
    package's `__init__`. Nothing here is saved, which is deliberate.
    """

    half_life: float = HALF_LIFE
    warmup: int = WARMUP
    exponent: float = EXPONENT
    mean: float = 0.0
    #: An exponential mean of `share ** exponent`, which is what `factor`
    #: divides by. See `factor` for why this field has to exist.
    power: float = 0.0
    seen: int = 0

    def update(self, volume: float) -> float:
        """Fold a bar in and return its share. One while warming or absent.

        Folds in before reading, so the current bar is in its own mean. The
        alternative - score against the mean of everything before it - makes
        the first busy bar of a session score against a sleepy mean and come
        back at the clamp.
        """
        if volume is None or volume <= 0:
            return 1.0
        self.seen += 1
        if not self.mean:
            self.mean = float(volume)
        else:
            self.mean += _alpha(self.half_life) * (float(volume) - self.mean)
        got = self.share(volume)
        raised = got**self.exponent
        if not self.power:
            self.power = raised
        else:
            self.power += _alpha(self.half_life) * (raised - self.power)
        return got

    def share(self, volume: float) -> float:
        """This bar's activity as a multiple of the typical bar."""
        if not volume or volume <= 0 or self.seen < self.warmup or self.mean <= 0:
            return 1.0
        return min(float(volume) / self.mean, MAX_SHARE)

    def factor(self, volume: float) -> float:
        """The **variance** multiplier for this bar, normalised to average one.

        The counterpart of `seasonal.Profile.factor`, and the same contract -
        a variance factor, not a size factor - so the two can be multiplied.

        **`share` averages one and `share ** 2` does not**, and the first
        version of this class returned the raised share directly. For a share
        with any spread, `E[share ** 2] = 1 + Var(share)`, which on real FX
        volume at 1h measures **2.23**: the squared arm was multiplying the
        member's average process noise by more than two as well as varying it.

        That is not a subtlety, it is the difference between a result and an
        artefact. Scored that way the squared arm beat the linear one by +2365
        to +1734 nats, and a sweep of the base process noise on the flat arm -
        the usual guard - cannot remove it, because the guard refits the arm
        that is *not* being driven. The exponent comparison was measuring
        "more `Q`" and reporting it as "the right shape for `Q`".

        Dividing by an exponential mean of the same raised share makes every
        exponent average one, so what is compared is the **shape** of the
        multiplier and nothing else. `Profile.at` does the same thing by
        subtracting `weights[0]` on the log scale.
        """
        raised = self.share(volume) ** self.exponent
        if self.seen < self.warmup or self.power <= 0:
            return 1.0
        return raised / self.power

    def control(self, volume: float) -> float:
        """The input for `driven.Driven.predict(when, control=...)`.

        `Driven` applies `1 + gain * u`, so this returns `factor - 1` and a
        unit gain reproduces `factor` exactly. An average bar returns `0.0`
        and leaves the member alone, which is what makes a gain sweep
        interpretable: `gain=0` is the control arm and nothing else changes.
        """
        return self.factor(volume) - 1.0

    def wander(self, base: float, volume: float) -> float:
        """A per-bar variance for `Q` from a base variance. Mirrors `Profile`."""
        return base * self.factor(volume)

    @property
    def warm(self) -> bool:
        return self.seen >= self.warmup


@dataclass(slots=True)
class Levelled:
    """Any variance factor, renormalised to an **arithmetic** mean of one.

    This exists because the lesson had to be learnt three times in one study.
    A multiplier on `Q` whose average is not one hands the member more process
    noise as well as varying it, and sweeping the base noise on the undriven
    arm cannot remove that - the sweep refits the arm that is not being driven.
    Three cases, all measured on FX at 1h:

    * `share ** 2` runs at a mean of **2.23**, because `E[x^2]` exceeds
      `E[x]^2`. Fixed inside `Pace.factor`;
    * the **product** of two factors that each average one runs at **1.36**,
      because activity is high exactly when the clock is high and
      `E[XY] = E[X]E[Y] + Cov(X, Y)`. Fixed inside `Both`;
    * **`seasonal.Profile.factor` itself runs at 1.21**, worst 1.58.
      `Profile.at` normalises by subtracting `weights[0]` on the *log* scale,
      which makes its **geometric** mean one, and `factor` then squares it. A
      log-normalised quantity squared does not have an arithmetic mean of one.

    The third is a statement about an existing measured result rather than
    about this module, which is why this wrapper is separate and takes any
    callable: it lets the clock be scored with and without the subsidy instead
    of changing what `Profile` does.
    """

    inner: object
    half_life: float = HALF_LIFE
    mean: float = 0.0

    def factor(self, *args) -> float:
        raw = float(self.inner(*args))  # type: ignore[operator]
        if not math.isfinite(raw) or raw <= 0:
            return 1.0
        if not self.mean:
            self.mean = raw
        else:
            self.mean += _alpha(self.half_life) * (raw - self.mean)
        return raw / self.mean if self.mean > 0 else 1.0

    def __call__(self, *args) -> float:
        return self.factor(*args)


@dataclass(slots=True)
class Both:
    """The clock and activity on one lever, as the product of two factors.

    Both are ratios on a variance, so they compose by multiplication: a busy
    hour and a busy bar should reinforce rather than one overwriting the other.
    This exists because the composition is the measurement that matters -
    `statespace-volume-clock.md` found activity absorbs three-quarters of the
    clock, so the open question is whether the quarter it leaves is worth
    carrying, and that question needs an arm that runs both.

    `clock` is any `(when) -> variance factor`, normally `Profile.factor`.
    """

    pace: Pace
    clock: object | None = None
    #: An exponential mean of the **product**, which the product is divided by.
    #:
    #: Two factors that each average one do not multiply to one when they are
    #: correlated, and these two are: a busy hour is busy because the bars in
    #: it are busy. Measured, the uncorrected product runs at **1.36** on
    #: average and **1.99** at worst, so an arm scored with it is handed a
    #: third more process noise than the arms it is being compared with.
    mean: float = 0.0
    half_life: float = HALF_LIFE

    def factor(self, when: float, volume: float) -> float:
        timed = 1.0
        if self.clock is not None:
            timed = float(self.clock(when))  # type: ignore[operator]
        raw = timed * self.pace.factor(volume)
        if not math.isfinite(raw) or raw <= 0:
            return 1.0
        if not self.mean:
            self.mean = raw
        else:
            self.mean += _alpha(self.half_life) * (raw - self.mean)
        return raw / self.mean if self.mean > 0 else 1.0

    def control(self, when: float, volume: float) -> float:
        """The combined input for `Driven`, on the same `1 + gain * u` form."""
        return self.factor(when, volume) - 1.0

    def update(self, volume: float) -> float:
        return self.pace.update(volume)


def factors(
    volumes,
    exponent: float = EXPONENT,
    half_life: float = HALF_LIFE,
    warmup: int = WARMUP,
) -> list[float]:
    """Every bar's variance multiplier, computed causally. Averages one."""
    pace = Pace(exponent=exponent, half_life=half_life, warmup=warmup)
    out = []
    for v in volumes:
        pace.update(v)
        out.append(pace.factor(v))
    return out


def shares(volumes, half_life: float = HALF_LIFE, warmup: int = WARMUP) -> list[float]:
    """Every bar's share, computed causally. For harnesses and plotting.

    Causal because the alternative is a share against the whole sample's mean,
    which uses the future and would make any gain measured with it unearnable.
    """
    pace = Pace(half_life=half_life, warmup=warmup)
    return [pace.update(v) for v in volumes]


def extent(volumes, half_life: float = HALF_LIFE) -> float:
    """Ninetieth over tenth percentile of the shares: how uneven activity is.

    One means activity is constant, which is what the generated feeds give and
    what makes them the control. Reported as a percentile ratio rather than
    peak over trough because the clamp truncates the peak by design.
    """
    got = sorted(s for s in shares(volumes, half_life=half_life) if s > 0)
    if len(got) < 20:
        return 1.0
    low = got[len(got) // 10]
    high = got[(len(got) * 9) // 10]
    return high / low if low > 0 else math.inf
