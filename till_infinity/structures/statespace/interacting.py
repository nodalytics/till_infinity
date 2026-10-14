"""What a level has done to price, as posteriors rather than as ratios.

`structures/levels.py` already keeps, per level and per **side**, the richest
record on this desk: a hold rate, a trap rate, a sweep-depth spread, a push
distribution, and a symmetric-race hold rate. Asked for on 2026-10-14: the
statespace versions of these, inside statespace.

The versions are not copies, and the difference is the reason they are worth
having. `SideStats` keeps **ratios** - `rejects / decisive` - which is the right
thing for a display and the wrong thing for everything else: a ratio cannot say
how sure it is, so it cannot be pooled, cannot be shrunk toward a prior, and
cannot be compared between a level with four touches and one with four hundred.
Every object here carries its own uncertainty.

## And the measurement that makes this the interesting half of levels

`statespace-ranging.md` tested **seventeen** ways of picking a price that should
act as support - volume profile, value area, rejection and acceptance profiles,
hour-of-day profiles, two published wick-to-body thresholds, and momentum and
acceleration turns - against a distance-matched placebo. Every one came back
inside the noise.

That refutes **level constructions**: ways of nominating a price in advance.
It says nothing about the question these objects answer, which is conditional
on a level's own history: *has **this** level, from **this** side, turned price
before, and by how much?* A construction has no history; a level does. That is
why `sym_hold_rate` is the most interesting unused number in `levels.py` - it
is the conditional version of exactly the claim the seventeen refuted, it has a
noise floor of 0.5 written into its own docstring, production has been
accumulating it since `engine.py:2759` was written, and **nothing reads it**.

## Three objects

**`Rate`** - a Beta posterior over a hold, trap or symmetric rate. The mean is
the shrunk estimate, `sd` is how sure it is, and `beats(level)` asks whether it
clears a floor by its own uncertainty rather than by its point value. A level
with 3 of 4 holds and one with 300 of 400 have the same ratio and are not the
same evidence, which is the whole reason this is not a division.

**`Depth`** - the sweep-depth distribution, as quantiles rather than as mean
plus spread. `levels.wick_deep_vol` returns `mean + sigmas * sd`, which assumes
a shape for a quantity this desk has measured as having none: no Gaussian band
here has ever been calibrated. The empirical quantiles make no such assumption
and cost nothing extra to keep.

**`Attention`** - the `strength` analogue. `levels.Level.strength` combines four
terms with **chosen** weights - `0.4 * evidence + 0.25 * agreement +
0.2 * recency + 0.15 * breadth` - and is the most-read number in that file, with
seventeen consumers. This keeps the same four terms and makes the weights an
argument, so they can be fitted against an outcome instead of picked. It
defaults to the production weights exactly, so swapping it in changes nothing
until someone measures a better set.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

#: Prior strength on a rate, in pseudo-observations. Two, so a level with no
#: history reads 0.5 with a wide posterior rather than 0.0 with a certain one -
#: the mistake `Kalman.var_slope` documents, where zero variance reads as *no
#: information* and not as certainty.
PRIOR = 2.0

#: Sweep depths kept per side. Enough for a tail quantile to have observations
#: behind it, few enough to describe the level as it is now.
DEPTHS = 200

#: The production weights for `Attention`, unchanged. See the module docstring:
#: they are an argument here so they can be fitted, not because a better set is
#: known.
WEIGHTS = (0.4, 0.25, 0.2, 0.15)


@dataclass(slots=True)
class Rate:
    """A Beta posterior over a rate in [0, 1], with its own uncertainty.

    `hits` and `misses` are counts; the posterior is `Beta(hits + prior,
    misses + prior)`, so the mean is shrunk toward 0.5 by an amount that
    decays as evidence arrives.
    """

    hits: float = 0.0
    misses: float = 0.0
    prior: float = PRIOR

    def observe(self, hit: bool, weight: float = 1.0) -> None:
        if hit:
            self.hits += float(weight)
        else:
            self.misses += float(weight)

    @property
    def seen(self) -> float:
        return self.hits + self.misses

    @property
    def alpha(self) -> float:
        return self.hits + self.prior

    @property
    def beta(self) -> float:
        return self.misses + self.prior

    @property
    def mean(self) -> float:
        """The shrunk rate. 0.5 with no evidence, by construction."""
        return self.alpha / (self.alpha + self.beta)

    @property
    def sd(self) -> float:
        """Posterior standard deviation. The thing a bare ratio cannot report."""
        a, b = self.alpha, self.beta
        total = a + b
        return math.sqrt(a * b / (total * total * (total + 1.0)))

    @property
    def raw(self) -> float:
        """The unshrunk ratio, for comparison with `levels.SideStats`."""
        return self.hits / self.seen if self.seen > 0 else 0.0

    def beats(self, level: float = 0.5, sigmas: float = 2.0) -> bool:
        """Whether the rate clears `level` by `sigmas` of its own uncertainty.

        **This is what the object is for.** Three holds out of four is a ratio
        of 0.75 and no evidence at all; three hundred out of four hundred is
        the same ratio and a fact. `beats` separates them and a division
        cannot.
        """
        return self.mean - sigmas * self.sd > level


@dataclass(slots=True)
class Depth:
    """How far sweeps past a level reach, as a distribution.

    The statespace version of `levels.SideStats.wick_deep_vol`, which returns
    `mean + sigmas * sd` and so assumes a shape. This keeps the observations and
    reads quantiles off them, which assumes none - and
    `no-gaussian-band-is-calibrated` is why that matters here: nothing on this
    desk has found a calibrated Gaussian band, and a sweep depth is a tail
    quantity where the assumption costs most.
    """

    kept: deque[float] = field(default_factory=lambda: deque(maxlen=DEPTHS))

    def observe(self, depth: float) -> None:
        value = float(depth)
        if math.isfinite(value) and value >= 0:
            self.kept.append(value)

    @property
    def seen(self) -> int:
        return len(self.kept)

    def quantile(self, share: float) -> float:
        """The depth `share` of sweeps stay inside. 0.0 while empty."""
        if not self.kept:
            return 0.0
        got = sorted(self.kept)
        at = min(int(float(share) * len(got)), len(got) - 1)
        return got[max(at, 0)]

    @property
    def typical(self) -> float:
        return self.quantile(0.5)

    def unusual(self, share: float = 0.9) -> float:
        """How far past the origin a sweep reaches before it is unusual.

        `levels.wick_deep_vol`'s question, answered empirically. A caller that
        wants the Gaussian answer can still have it from `typical` and the
        spread, but it should want this one.
        """
        return self.quantile(share)


@dataclass(frozen=True, slots=True)
class Attention:
    """`levels.Level.strength`, with the weights as an argument.

    The four terms are production's, unchanged and in the same order:
    **evidence** from touches, **agreement** from a tight zone, **recency**, and
    **breadth** from swings. `WEIGHTS` reproduces `strength` exactly.

    It is separated out because that number has **seventeen** consumers and its
    weights were chosen rather than fitted - which makes it the highest-leverage
    constant in `levels.py` and the one most worth measuring. Nothing here
    claims a better set; this makes measuring one possible.
    """

    weights: tuple[float, float, float, float] = WEIGHTS

    def of(
        self,
        *,
        touches: float,
        spread: float,
        unit: float,
        since: float,
        swings: float,
        half_life_days: float = 14.0,
    ) -> float:
        """The score in [0, 1]. `since` is seconds since the last touch."""
        evidence = min(float(touches), 10.0) / 10.0
        agreement = 1.0 - min(1.0, float(spread) / max(float(unit), 1e-9))
        recency = math.exp(-max(0.0, float(since)) / (half_life_days * 86_400.0))
        breadth = min(float(swings), 5.0) / 5.0
        terms = (evidence, max(0.0, agreement), recency, breadth)
        return round(sum(w * t for w, t in zip(self.weights, terms, strict=True)), 4)

    def terms(
        self,
        *,
        touches: float,
        spread: float,
        unit: float,
        since: float,
        swings: float,
        half_life_days: float = 14.0,
    ) -> tuple[float, float, float, float]:
        """The four terms unweighted, which is what a fit needs."""
        return (
            min(float(touches), 10.0) / 10.0,
            max(0.0, 1.0 - min(1.0, float(spread) / max(float(unit), 1e-9))),
            math.exp(-max(0.0, float(since)) / (half_life_days * 86_400.0)),
            min(float(swings), 5.0) / 5.0,
        )


@dataclass(slots=True)
class Interactions:
    """Everything one level's one side has done, as posteriors.

    The statespace counterpart of `levels.SideStats`, keeping the three rates
    that `levels.py` computes and the sweep depths, each with its uncertainty.
    """

    held: Rate = field(default_factory=Rate)
    trapped: Rate = field(default_factory=Rate)
    symmetric: Rate = field(default_factory=Rate)
    depth: Depth = field(default_factory=Depth)

    def observe_touch(self, *, rejected: bool, trapped: bool | None = None) -> None:
        """One resolved interaction. `trapped` is only meaningful on a break."""
        self.held.observe(rejected)
        if not rejected and trapped is not None:
            self.trapped.observe(bool(trapped))

    def observe_symmetric(self, held: bool) -> None:
        """One symmetric race, the comparison `sym_hold_rate` was built for."""
        self.symmetric.observe(bool(held))

    def observe_sweep(self, depth: float) -> None:
        self.depth.observe(depth)

    @property
    def decisive(self) -> float:
        return self.held.seen

    def reading(self) -> dict[str, float]:
        """Everything a caller publishes, with the uncertainties beside it."""
        return {
            "hold_rate": round(self.held.mean, 4),
            "hold_sd": round(self.held.sd, 4),
            "hold_beats_coin": float(self.held.beats()),
            "trap_rate": round(self.trapped.mean, 4),
            "trap_sd": round(self.trapped.sd, 4),
            "symmetric_rate": round(self.symmetric.mean, 4),
            "symmetric_sd": round(self.symmetric.sd, 4),
            "symmetric_beats_coin": float(self.symmetric.beats()),
            "sweep_typical": round(self.depth.typical, 4),
            "sweep_unusual": round(self.depth.unusual(), 4),
            "decisive": round(self.decisive, 2),
        }
