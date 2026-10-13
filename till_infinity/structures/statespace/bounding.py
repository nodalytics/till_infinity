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


def feasible(probability: float, horizon: float, *, shift: float = SHIFT) -> bool:
    """Whether a `(probability, horizon)` pair admits non-negative barriers."""
    p = float(probability)
    if not 0.0 < p < 1.0:
        return False
    need = shift * shift * max((1.0 - p) / p, p / (1.0 - p))
    return float(horizon) >= need


def least_horizon(probability: float, *, shift: float = SHIFT) -> float:
    """The smallest `horizon` compatible with `probability`."""
    p = float(probability)
    if not 0.0 < p < 1.0:
        return math.inf
    return shift * shift * max((1.0 - p) / p, p / (1.0 - p))


def solve(
    *,
    up: float | None = None,
    down: float | None = None,
    probability: float | None = None,
    horizon: float | None = None,
    shift: float = SHIFT,
    slower: float = 1.0,
) -> dict[str, float]:
    """All four quantities from exactly two of them.

    Distances are in volatility units of one bar, `horizon` in bars. `slower`
    multiplies the duration for a feed whose volatility reverts, and does not
    touch the probability.

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

    # Work in shifted units, where the two laws are P = d/(u+d) and T = u*d.
    u = named["up"] + shift if "up" in named else None
    d = named["down"] + shift if "down" in named else None
    p = named.get("probability")
    # The caller's horizon is on the feed's clock; the algebra is Brownian.
    t = named["horizon"] / slower if "horizon" in named else None

    if p is not None and not 0.0 < p < 1.0:
        raise ValueError(f"probability must lie strictly inside (0, 1), got {p}")
    if t is not None and t <= 0:
        raise ValueError(f"horizon must be positive, got {named['horizon']}")
    if u is not None and u <= 0:
        raise ValueError(f"up must exceed -{shift}, got {named['up']}")
    if d is not None and d <= 0:
        raise ValueError(f"down must exceed -{shift}, got {named['down']}")

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
        if not feasible(p, t, shift=shift):
            raise ValueError(
                f"probability {p:.4f} and horizon {t:.4f} bars need a barrier "
                f"closer than zero; the least horizon for that probability is "
                f"{least_horizon(p, shift=shift):.4f} bars"
            )
        d = math.sqrt(t * p / (1.0 - p))
        u = math.sqrt(t * (1.0 - p) / p)

    return {
        "up": u - shift,
        "down": d - shift,
        "probability": d / (u + d),
        "horizon": u * d * slower,
    }


def slack(
    up: float,
    down: float,
    horizon: float,
    *,
    shift: float = SHIFT,
    slower: float = 1.0,
) -> float:
    """The desk's time limit over the one its geometry implies.

    Above 1 the limit is decoration and the trade ends at a barrier; below 1 the
    barriers are decoration and the trade is a fixed-horizon bet. **1 is not a
    target** - it is the point at which the two mechanisms are equally
    responsible, which is usually not what a desk wants either.
    """
    implied = solve(up=up, down=down, shift=shift, slower=slower)["horizon"]
    return math.inf if implied <= 0 else float(horizon) / implied


def binding(
    up: float,
    down: float,
    horizon: float,
    *,
    shift: float = SHIFT,
    slower: float = 1.0,
) -> str:
    """Which of the three numbers is actually deciding the exit."""
    ratio = slack(up, down, horizon, shift=shift, slower=slower)
    if ratio > 2.0:
        return "barriers"
    if ratio < 0.5:
        return "time"
    return "both"
