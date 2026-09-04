"""Being wrong and being swept are different events that look identical.

A stop is hit two ways. Either the level failed - fair value was somewhere else
and the trade was wrong - or price ran through, took the stops resting beyond
it, and carried on in the original direction without you. The account cannot
tell those apart. This module is the attempt to, before the fact.

## The claim, reduced to something we already measure

The folk version says a level is "protected" when there is another extreme
between it and the last structural break, giving price something to come back
and take; without that intervening extreme the level is *inducement* - bait,
and it will be run before the real move.

Stated that way it needs a swing-labelling apparatus and a definition of
"structural break", and each of those is a construct with free parameters. But
the operative content survives a much simpler statement:

    a level with liquidity resting close beyond it is a level price has a
    reason to run through

which is answerable directly from the level set this package already maintains.
The "liquidity" is the next level out - a price where stops accumulate because
it is a price everybody else can see too.

## Two numbers, both derived rather than declared

**How often this level has been swept.** `Outcome.TRAP` is already recorded per
side: price went through and came back. Its decayed share of decisive
interactions is the level's own sweep rate, and it is the direct evidence - a
level that has been run four times out of ten is telling you something about
itself that no geometry needs to be inferred.

**What is resting beyond it.** The distance to the next level out, in
volatility units. Close liquidity beyond is a reason to expect a run; nothing
within reach means a stop placed outside this level's zone is not sitting in
front of an obvious target.

## What this is not

It is not a direction predictor, and that matters because every direction claim
in this family has been measured to a coin flip - sweep direction at 50.7%
accuracy and negative net of costs, in a study of 73,000 ranges. This asks a
different question: *given a setup already selected on other grounds, is the
stop about to be placed somewhere price has a reason to reach*. A filter on an
entry, not a forecast.

Nothing here gates anything on its own. Both numbers go onto the signal and
into the journal beside the outcome, so the question "does close liquidity
beyond predict a sweep" becomes answerable from our own resolutions - which is
the only way it should ever be answered. The prior from elsewhere is not
encouraging; that is a reason to measure it rather than to skip it.
"""

from __future__ import annotations

from ..levels import Level, Side
from ..vol.volatility import Volatility

#: How far out to look for the next level. Beyond this the "liquidity" is not
#: a target for the current move - it is a different trade on a different day,
#: and counting it would make every level look surrounded.
REACH_VOL = 6.0

#: Below this a neighbouring level is not *beyond* this one, it is the same
#: structure seen twice. The level model merges within its own tolerance; this
#: is the equivalent guard for a set that has not been merged.
SAME_LEVEL_VOL = 0.5


def sweep_rate(level: Level, side: Side) -> tuple[float, float]:
    """(share of decisive interactions that were sweeps, count behind it).

    A sweep is `Outcome.TRAP`: price went through the level and came back. It
    is recorded per side already, because the same level met from above and
    from below are two different objects - and a level that traps arrivals from
    one side and rejects them cleanly from the other is exactly the case a
    pooled number would hide.
    """
    stats = level.sides.get(side)
    if stats is None:
        return 0.0, 0.0
    decisive = stats.decisive
    return (stats.traps / decisive if decisive > 0 else 0.0), decisive


def liquidity_beyond(
    level: Level,
    levels: list[Level],
    side: Side,
    vol: Volatility,
    reach: float = REACH_VOL,
) -> tuple[float, int]:
    """(distance to the nearest level beyond this one, how many are within reach).

    "Beyond" is away from where price is arriving from: an arrival from above
    is heading down, so what is beyond is *below*. That is the direction a
    sweep of this level would travel, and therefore the only side whose resting
    orders are a reason to run it.

    Returns a distance of 0.0 when there is nothing within reach, which is the
    interesting case rather than a missing value - it says a stop placed beyond
    this level is not sitting in front of an obvious target.
    """
    if not level.price:
        return 0.0, 0
    unit = vol.price_units(level.price, 1.0)
    if unit <= 0:
        return 0.0, 0

    # Arriving from above means the trade is long and a sweep runs down.
    downward = side is Side.ABOVE
    found: list[float] = []
    for other in levels:
        if other is level or not other.price:
            continue
        gap = (level.price - other.price) if downward else (other.price - level.price)
        if gap <= 0:
            continue
        distance = gap / unit
        if distance < SAME_LEVEL_VOL or distance > reach:
            continue
        found.append(distance)

    if not found:
        return 0.0, 0
    return min(found), len(found)


def exposure(
    level: Level,
    levels: list[Level],
    side: Side,
    vol: Volatility,
    stop_vol: float,
) -> float:
    """How much of the way to the next level a stop at `stop_vol` reaches.

    The number a strategy actually wants. Above 1.0 the stop sits *past* the
    liquidity resting beyond, so a run that takes those orders takes this one
    on the way - the worst place to stand. Near zero the stop is nowhere near
    it. Zero exactly means there is nothing within reach to be run toward.

    Deliberately a ratio rather than a verdict. Where the line falls is a
    question for the journal, and hard-coding one here would be inventing the
    answer this module exists to make measurable.
    """
    distance, _ = liquidity_beyond(level, levels, side, vol)
    if distance <= 0:
        return 0.0
    return abs(stop_vol) / distance
