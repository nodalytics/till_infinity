"""What a member's eigenvalues say, in hours.

Members answer `transition(dt)` and `observation()` because the smoother needs
`F` and `C`. Those two matrices contain more than the smoother uses, and none
of it is read anywhere:

* **the eigenvalues of `F` are the member's rates**, and this package measures
  everything in time - so `ln 2 / |log lambda|` is a **half-life in hours**,
  which says directly what horizons the member can represent. A member whose
  slowest mode is an hour cannot carry a weekly level however it is fitted;
  that is arithmetic, not a fitting problem, and it is checkable before any
  data arrives.
* **whether the state can be seen at all.** The observability matrix
  `[C; CF; CF^2; ...]` has full rank exactly when the whole state can be
  recovered from the output. A member with an unobservable mode is carrying a
  quantity the data can never pin down - its covariance in that direction
  never shrinks, its likelihood never improves, and it looks like a member
  that just needs more data. Nothing here has ever checked it.
* **how close `F` is to defective.** A near-singular eigenvector matrix means
  the modes are nearly parallel, so the decomposition into them is numerically
  meaningless even when the filter itself is fine. `linear.Gaussian` is a
  triple integrator whose three eigenvalues are *identical*, which is the
  defective case exactly - and worth knowing before reading anything modal
  into its states.

## Marginal stability is a choice here, not an accident

A discrete eigenvalue on the unit circle is a random walk: it neither decays
nor explodes. `linear` is three of them, which is deliberate - a level that
mean-reverts to something would need that something, and this package's
position is that there is nothing to revert to. `reverting` makes the opposite
choice for the rate and measured **+0.96 nats per point** for it.

So `stability` is reported rather than enforced. An unstable member - any
eigenvalue outside the unit circle - is a different matter: it is a model
whose state grows without bound, and no member here should have one.

## A time-varying `C` makes the observability test a lower bound

The observability matrix assumes `C` is constant. `relating.Relating`'s is
not - its row is `[1, x_t]`, carrying the other leg - so the static test
reports **one hidden state out of two**, and that is both an artifact and a
true statement.

The artifact: with `F = I` and a frozen `C`, `[C; C]` has rank one, so the
test cannot distinguish the intercept from the hedge ratio. The truth: that
is exactly right *if the other leg does not move*. A pair whose independent
leg is constant has no information to separate a level from a slope, and no
filter can invent it. `Relating` is observable **because `x` varies**, which
is a real condition on the data rather than a property of the model, and it
is worth knowing that the identifiability of a hedge ratio rests on it.

For a time-varying system the correct test is the observability Gramian
accumulated over the actual `C_t` sequence. That is not written here; the
static rank is reported with this caveat, which is more useful than silence
and less misleading than a number without it.

## numpy, lazily

Imported inside the functions, like `structures/cycles.py` does, because it is
transitive through `river` and `yfinance` rather than declared. Everything here
is a diagnostic rather than a filtering path, so a missing numpy costs a
diagnostic and not a desk.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

HOUR = 3600.0

#: A discrete eigenvalue within this of the unit circle counts as marginal
#: rather than stable or unstable. Floating point puts a true unit root at
#: `1 +/- 1e-16`, and calling that unstable would be reporting arithmetic.
EDGE = 1e-9


@dataclass(frozen=True, slots=True)
class Spectrum:
    """A member's modes, as durations and as a verdict."""

    #: Discrete eigenvalues of `F(dt)`, as moduli. Complex pairs appear twice.
    moduli: tuple[float, ...]
    #: Each mode's half-life in **hours**. `inf` for a unit root, which is a
    #: random walk and has no half-life rather than a very long one.
    half_lives: tuple[float, ...]
    #: `stable`, `marginal` or `unstable`.
    stability: str
    #: Rank of the observability matrix, and the state dimension.
    observable: int
    states: int
    #: Condition number of the eigenvector matrix. Large means the modes are
    #: nearly parallel and the modal decomposition should not be read.
    conditioning: float

    @property
    def fully_observable(self) -> bool:
        return self.observable >= self.states

    def __str__(self) -> str:
        lives = "/".join("inf" if math.isinf(h) else f"{h:.3g}h" for h in self.half_lives)
        seen = (
            "observable"
            if self.fully_observable
            else (f"**{self.states - self.observable} HIDDEN**")
        )
        return f"{self.stability:<8} half-lives {lives}  {seen}  cond {self.conditioning:.3g}"


def spectrum(member: object, dt_hours: float = 1.0) -> Spectrum | None:
    """The modes of `member` at a step of `dt_hours`. `None` if it cannot say.

    A member that does not answer `transition` and `observation` declines to
    be analysed, which is the same contract `smooth` uses and the same true
    statement: a member that cannot state its own `F` has not been written
    down as a state-space model, whatever it does internally.
    """
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy is transitively present
        return None
    transition = getattr(member, "transition", None)
    observation = getattr(member, "observation", None)
    if transition is None or observation is None:
        return None

    f = np.asarray(transition(dt_hours), dtype=float)
    c = np.asarray(observation(), dtype=float)
    if f.ndim != 2 or f.shape[0] != f.shape[1] or f.shape[0] == 0:
        return None
    states = int(f.shape[0])

    values, vectors = np.linalg.eig(f)
    moduli = tuple(float(abs(v)) for v in values)

    # A discrete eigenvalue `lambda` over `dt` hours decays by `|lambda|` each
    # step, so its half-life is `dt * ln(1/2) / ln|lambda|`.
    lives = []
    for modulus in moduli:
        if modulus >= 1.0 - EDGE:
            lives.append(math.inf)
        elif modulus <= 0.0:
            lives.append(0.0)
        else:
            lives.append(dt_hours * math.log(0.5) / math.log(modulus))

    widest = max(moduli) if moduli else 0.0
    if widest > 1.0 + EDGE:
        stability = "unstable"
    elif widest >= 1.0 - EDGE:
        stability = "marginal"
    else:
        stability = "stable"

    # Observability: stack `C F^k` and take the rank. Rank is the whole
    # question - a deficient one names how many directions of the state the
    # output can never distinguish.
    rows = []
    power = np.eye(states)
    for _ in range(states):
        rows.append(c @ power)
        power = power @ f
    observable = int(np.linalg.matrix_rank(np.vstack(rows)))

    try:
        conditioning = float(np.linalg.cond(vectors))
    except np.linalg.LinAlgError:  # pragma: no cover - defective to machine eps
        conditioning = math.inf

    return Spectrum(
        moduli=moduli,
        half_lives=tuple(lives),
        stability=stability,
        observable=observable,
        states=states,
        conditioning=conditioning,
    )


def reachable(member: object, dt_hours: float = 1.0) -> tuple[float, float]:
    """`(shortest, longest)` half-life the member can represent, in hours.

    The practical reading of the spectrum, and the one that connects to the
    rest of the package: `inputs.LADDER` runs from ten seconds to four weeks,
    and a member can only answer about horizons its own modes span. A member
    whose longest finite half-life is an hour will track a weekly level by
    lagging it, not by representing it - and that is visible here rather than
    only in a disappointing likelihood.

    A unit root is reported as `inf`: a random walk represents every horizon,
    which is exactly why it is so hard to beat.
    """
    got = spectrum(member, dt_hours)
    if got is None or not got.half_lives:
        return (math.nan, math.nan)
    finite = [h for h in got.half_lives if math.isfinite(h) and h > 0]
    if not finite:
        return (math.inf, math.inf)
    return (min(finite), max(got.half_lives))
