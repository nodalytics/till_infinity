"""I7: two barriers from one model instead of three.

The desk sets a target, a stop and a time limit as **three independent
numbers**. They are not independent, and this module is the statement of how
many of them are actually free.

## The algebra, which is the whole item

First passage of a driftless walk between two barriers, with the discrete-
monitoring correction `SHIFT` added to each wall, gives the probability of the
upper barrier first and the expected bars to either as

    P = (down + B) / (up + down + 2B)        T = (up + B) * (down + B)

Substitute `u = up + B` and `d = down + B` and the two laws collapse into
something much plainer:

    P = d / (u + d)                          T = u * d

**Four quantities, two degrees of freedom.** `up`, `down`, `probability` and
`horizon` are one surface, and fixing any two fixes the other two exactly:

| given | the rest |
| --- | --- |
| `up`, `down` | `P = d/(u+d)`, `T = u*d` |
| `up`, `probability` | `d = u*P/(1-P)` |
| `up`, `horizon` | `d = T/u` |
| `down`, `probability` | `u = d*(1-P)/P` |
| `down`, `horizon` | `u = T/d` |
| `probability`, `horizon` | `d = sqrt(T*P/(1-P))`, `u = sqrt(T*(1-P)/P)` |

So a desk choosing three numbers has **over-specified the problem**, and the
third choice is either redundant or contradictory. There is no third case.

## What the over-specification costs, and it is not symmetric

A time limit set longer than `T` never binds: the trade ends at a barrier and
the limit is decoration. Set shorter, the barriers never bind: the geometry is
decoration and the trade is a fixed-horizon bet wearing a target. `slack`
returns the ratio, so which of the two is happening is a number rather than an
impression.

The failure is quiet in both directions, which is why it survives: a time limit
that never fires looks like a time limit, and a target that is never reached
looks like a target.

## Not every pair is reachable

`u >= SHIFT` and `d >= SHIFT` are forced - a barrier cannot sit at a negative
distance - so a *probability* and a *horizon* cannot be chosen freely either:

    T >= SHIFT**2 * max((1-P)/P, P/(1-P))

**A three-number view cannot express that constraint**, because it has no
relation between the numbers to violate. `feasible` is the check, and an
infeasible request is a genuine finding about the trade rather than an input
error: it says the desired win rate and the desired holding time cannot both be
had from a geometry.

## The correction this deliberately does not apply

`T` is the Brownian expectation and real feeds run **25% to 96% longer**, by a
volatility-reversion mechanism measured elsewhere on 19 feeds out of 19. That
multiple belongs to the feed, not to the algebra, so it is a caller's argument
here (`slower`) rather than a constant: passing it scales `horizon` and leaves
`probability` alone, which is the right shape because the label is invariant to
volatility and the duration is not.

`SHIFT` is restated rather than imported. This package does not import from
`trading`, deliberately, and one duplicated constant is a smaller cost than a
dependency that makes the members untestable without a broker.

## One shift is wrong for a one-sided feed, and the formulas are not

A published spec that spikes one way - `Boom`, `Crash`, `DEX_UP`, `DEX_DOWN` -
breaks the symmetric correction without touching the algebra, and getting that
distinction the right way round decides how much changes.

`P = d/(u+d)` is optional stopping on a mean-zero martingale and `T = u*d` is
Wald's second identity. **Neither derivation mentions symmetry, Gaussianity or
any higher moment**, so a skewed martingale has the same laws. What it does not
have is the same **overshoot**: `SHIFT` exists because a barrier watched once a
bar can be crossed and recrossed inside it, which is an overshoot correction,
and a Boom index reaches its upper barrier *in a spike* and overshoots badly
while reaching its lower barrier in small drifting steps.

So optional stopping still applies - to the stopped value **including its
overshoot** - and the same `P = d/(u+d)` holds with `u = up + shift_up` and
`d = down + shift_down`. On a planted skewed martingale that prediction lands
within three decimals of the measured crossing share at every reach: predicted
0.4538 against measured 0.4534, and 0.4718 against 0.4715.

**The single defect was that `SHIFT` was one number where it needs two**, and
`SHIFTS` carries the measured pairs. The practical size of it: a `Boom` index on
a symmetric `+/-2` sigma geometry wins **0.4861** of the time, not half.
"""

from __future__ import annotations

import math

#: Broadie-Glasserman-Kou discrete-monitoring shift, `-zeta(1/2)/sqrt(2*pi)`.
#:
#: A barrier watched once a bar is effectively this much further away than one
#: watched continuously, because the walk can cross and return inside a bar.
SHIFT = 0.5826

#: The quantities on the surface. Exactly two are free.
QUANTITIES = ("up", "down", "probability", "horizon")

#: Measured directional shifts, as `(up, down)`, for feeds whose published
#: process spikes one way.
#:
#: **One constant is wrong for a one-sided process, and the formulas are not.**
#: `SHIFT` corrects for a barrier being watched once a bar rather than
#: continuously, so it is an *overshoot* correction - and the overshoot is
#: exactly where a spiking feed differs by direction. A `Boom` index reaches its
#: upper barrier **in a spike** and overshoots it badly; it reaches its lower
#: barrier in small drifting steps and barely overshoots at all.
#:
#: Measured by `research/ideas/barrier_overshoot.py` as the mean excess beyond
#: the barrier at first crossing, in units of one bar's standard deviation, on
#: non-overlapping windows at reaches of 2, 4 and 8 sigma. The
#: `Volatility_*` family is the control and recovers `0.5745` to `0.6002` up
#: and `0.5773` to `0.6058` down - a ratio of 0.948 to 1.024 - so an estimator
#: that reproduces the constant it replaces is what produced the rest.
#:
#: The mirror families mirror each other, which is the internal check: Boom
#: reads `0.65 / 0.51` where Crash reads `0.51 / 0.60`, and `DEX_UP` reads
#: `0.72 / 0.45` where `DEX_DOWN` reads `0.47 / 0.72`.
#: The step families are listed as symmetric **because they were measured and
#: came out symmetric**, which is worth recording so nobody derives it twice.
#: `Step_Index`, `Multi_Step_*` and `Skew_Step_*` read ratios of 0.881 to 1.047
#: across reaches, and `Skew_Step` is symmetric too despite its name.
#:
#: They are also a genuine **lattice** - 149 distinct bar-return magnitudes on
#: `Step_Index` against 14,000 for a diffusion, on a price grid of exactly
#: `0.1` - which raises the question of whether a grid-aligned barrier removes
#: the correction entirely, since a walk lands on such a barrier rather than
#: crossing it. **It does not, and the reason is a number:** the grid spacing is
#: `0.0166` of one bar's standard deviation, so alignment can remove at most 2.8%
#: of a `0.5826` shift. The monitoring correction comes from within-bar path
#: behaviour, not from grid granularity, and at this resolution the grid is far
#: too fine to touch it.
SHIFTS: dict[str, tuple[float, float]] = {
    "volatility": (SHIFT, SHIFT),
    "boom": (0.6535, 0.5100),
    "crash": (0.5080, 0.6027),
    "dex_up": (0.7183, 0.4500),
    "dex_down": (0.4683, 0.7169),
    "step": (SHIFT, SHIFT),
    "multi_step": (SHIFT, SHIFT),
    "skew_step": (SHIFT, SHIFT),
}


def shifts_for(feed: str) -> tuple[float, float]:
    """The `(up, down)` shift for a feed name, symmetric when it is not listed.

    Falls back to `(SHIFT, SHIFT)` rather than guessing: an unlisted feed has
    not been measured, and a symmetric correction is the honest default for a
    process whose asymmetry is unknown.
    """
    from .behaving import classify

    return SHIFTS.get(classify(feed), (SHIFT, SHIFT))


def _walls(
    shift: float,
    shift_up: float | None,
    shift_down: float | None,
    feed: str | None = None,
):
    """Resolve the two walls, with `shift` as the symmetric shorthand.

    `feed` names an instrument and resolves the measured pair through
    `shifts_for`, which is what makes `SHIFTS` reachable without a caller
    knowing that walls exist. An explicit `shift_up` or `shift_down` still
    wins, because a caller who has measured their own should not be overridden
    by a table.
    """
    if feed is not None:
        measured_up, measured_down = shifts_for(feed)
    else:
        measured_up = measured_down = shift
    return (
        measured_up if shift_up is None else float(shift_up),
        measured_down if shift_down is None else float(shift_down),
    )


def feasible(
    probability: float,
    horizon: float,
    *,
    shift: float = SHIFT,
    shift_up: float | None = None,
    shift_down: float | None = None,
    feed: str | None = None,
) -> bool:
    """Whether a `(probability, horizon)` pair admits non-negative barriers."""
    p = float(probability)
    if not 0.0 < p < 1.0:
        return False
    return float(horizon) >= least_horizon(
        p, shift=shift, shift_up=shift_up, shift_down=shift_down, feed=feed
    )


def least_horizon(
    probability: float,
    *,
    shift: float = SHIFT,
    shift_up: float | None = None,
    shift_down: float | None = None,
    feed: str | None = None,
) -> float:
    """The smallest `horizon` compatible with `probability`.

    Each wall contributes its own bound, because `u >= shift_up` and
    `d >= shift_down` are separate constraints once the two differ.
    """
    p = float(probability)
    if not 0.0 < p < 1.0:
        return math.inf
    up, down = _walls(shift, shift_up, shift_down, feed)
    return max(up * up * p / (1.0 - p), down * down * (1.0 - p) / p)


def solve(
    *,
    up: float | None = None,
    down: float | None = None,
    probability: float | None = None,
    horizon: float | None = None,
    shift: float = SHIFT,
    shift_up: float | None = None,
    shift_down: float | None = None,
    feed: str | None = None,
    slower: float = 1.0,
) -> dict[str, float]:
    """All four quantities from exactly two of them.

    Distances are in volatility units of one bar, `horizon` in bars. `slower`
    multiplies the duration for a feed whose volatility reverts, and does not
    touch the probability.

    `shift` sets both walls; `shift_up` and `shift_down` override them
    separately, which is what a one-sided feed needs - see `SHIFTS`. The
    algebra is unchanged by the asymmetry, because optional stopping applies to
    the stopped value **including its overshoot**: with different overshoots the
    same `P = d/(u+d)` holds with `u = up + shift_up` and
    `d = down + shift_down`. Measured against a planted skewed martingale that
    prediction holds to three decimals.

    Raises `ValueError` on anything but two, because the point of the item is
    that three is not a valid input.
    """
    given = {
        "up": up,
        "down": down,
        "probability": probability,
        "horizon": horizon,
    }
    named = {key: float(value) for key, value in given.items() if value is not None}
    if len(named) != 2:
        raise ValueError(
            f"exactly two of {QUANTITIES} are free, got {len(named)}: "
            f"{sorted(named)} - a third is determined, not chosen"
        )
    if slower <= 0:
        raise ValueError(f"slower must be positive, got {slower}")

    wall_up, wall_down = _walls(shift, shift_up, shift_down, feed)
    # Work in shifted units, where the two laws are P = d/(u+d) and T = u*d.
    u = named["up"] + wall_up if "up" in named else None
    d = named["down"] + wall_down if "down" in named else None
    p = named.get("probability")
    # The caller's horizon is on the feed's clock; the algebra is Brownian.
    t = named["horizon"] / slower if "horizon" in named else None

    if p is not None and not 0.0 < p < 1.0:
        raise ValueError(f"probability must lie strictly inside (0, 1), got {p}")
    if t is not None and t <= 0:
        raise ValueError(f"horizon must be positive, got {named['horizon']}")
    if u is not None and u <= 0:
        raise ValueError(f"up must exceed -{wall_up}, got {named['up']}")
    if d is not None and d <= 0:
        raise ValueError(f"down must exceed -{wall_down}, got {named['down']}")

    if u is not None and d is not None:
        pass
    elif u is not None and p is not None:
        d = u * p / (1.0 - p)
    elif u is not None and t is not None:
        d = t / u
    elif d is not None and p is not None:
        u = d * (1.0 - p) / p
    elif d is not None and t is not None:
        u = t / d
    else:
        # probability and horizon: the only pair that can be infeasible.
        if not feasible(p, t, shift_up=wall_up, shift_down=wall_down):
            raise ValueError(
                f"probability {p:.4f} and horizon {t:.4f} bars need a barrier "
                f"closer than zero; the least horizon for that probability is "
                f"{least_horizon(p, shift_up=wall_up, shift_down=wall_down):.4f} bars"
            )
        d = math.sqrt(t * p / (1.0 - p))
        u = math.sqrt(t * (1.0 - p) / p)

    return {
        "up": u - wall_up,
        "down": d - wall_down,
        "probability": d / (u + d),
        "horizon": u * d * slower,
    }


def slack(
    up: float,
    down: float,
    horizon: float,
    *,
    shift: float = SHIFT,
    shift_up: float | None = None,
    shift_down: float | None = None,
    feed: str | None = None,
    slower: float = 1.0,
) -> float:
    """The desk's time limit over the one its geometry implies.

    Above 1 the limit is decoration and the trade ends at a barrier; below 1 the
    barriers are decoration and the trade is a fixed-horizon bet. **1 is not a
    target** - it is the point at which the two mechanisms are equally
    responsible, which is usually not what a desk wants either.
    """
    implied = solve(
        up=up,
        down=down,
        shift=shift,
        shift_up=shift_up,
        shift_down=shift_down,
        feed=feed,
        slower=slower,
    )["horizon"]
    return math.inf if implied <= 0 else float(horizon) / implied


def binding(
    up: float,
    down: float,
    horizon: float,
    *,
    shift: float = SHIFT,
    shift_up: float | None = None,
    shift_down: float | None = None,
    feed: str | None = None,
    slower: float = 1.0,
) -> str:
    """Which of the three numbers is actually deciding the exit."""
    ratio = slack(
        up,
        down,
        horizon,
        shift=shift,
        shift_up=shift_up,
        shift_down=shift_down,
        feed=feed,
        slower=slower,
    )
    if ratio > 2.0:
        return "barriers"
    if ratio < 0.5:
        return "time"
    return "both"
