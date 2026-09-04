"""Levels defined by trade that did **not** happen.

Every other formation here is defined by presence. A pip is where price turned,
a run boundary is where volatility changed hands, an origin is the impulse that
set an extremum, a mode is where a lot happened. This one is the complement:
three bars where the first bar's high sits below the third bar's low leave a
range that price passed through in one direction and **never traded back into**.

The desk name is an imbalance or a fair-value gap. The mechanism claimed for it
is that the move was one-sided - buyers lifted every offer without sellers
getting a chance to transact - so the range is unfinished business and price
tends to come back and finish it.

That claim is testable and this makes no attempt to argue it. What is emitted
is the midpoint of the untraded range, as a turning point like any other, so
the outcome machinery gets to say whether price respects it.

## Why the middle, and why it is one point per gap

The **middle** because the gap is a range and the claim is about the range;
picking an edge would be picking which end of a band to believe, which is the
question `levels` answers with a zone rather than with a choice.

**One point** because a gap happens once. That is the honest shape of the
object and it is also the reason this pass rarely draws a level alone -
`form` needs three turns within a volatility unit, so a gap becomes a level
only where three of them have opened at nearly the same price, which does
happen in a repeatedly-traversed area and is exactly where the claim is
strongest. Everywhere else it merges into a level another pass drew, and
`agree` records that this one found it too.

## Size matters, and is measured in the usual currency

A gap smaller than the noise is not an imbalance, it is two bars. `MIN_GAP_VOL`
is in volatility units for the same reason everything else here is: a fixed
price width would give btc four gaps and eurusd four thousand.

## Filled gaps are not emitted

A gap price has already traded back through is finished business by its own
definition, and emitting it would be claiming the opposite of what the idea
says. The scan therefore looks forward from each gap and drops the ones later
bars covered - which costs a pass over the window and removes the only way this
formation could quietly become a list of every three-bar pattern in history.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..vol.volatility import Volatility
from .pips import Point, Swing

#: How large an untraded range must be to be an imbalance rather than two bars,
#: in volatility units.
MIN_GAP_VOL = 0.5

#: How much of the range must still be untraded for the gap to count as open.
#: Not "any part of it": a gap price has come back through nine tenths of is
#: finished in every sense that matters, and holding it open would keep a level
#: alive on the strength of a tenth of a bar.
OPEN_SHARE = 0.5


def gaps(
    highs: Sequence[float],
    lows: Sequence[float],
    vol: Volatility,
    *,
    minimum_vol: float = MIN_GAP_VOL,
    open_share: float = OPEN_SHARE,
) -> list[tuple[int, float, float, float]]:
    """`(index, low, high, size in volatility units)` for each open gap.

    `index` is the middle bar of the three - the one the move happened on, and
    the one whose time stamps the point. Oldest first.
    """
    if len(highs) != len(lows) or len(highs) < 3:
        return []

    found: list[tuple[int, float, float, float]] = []
    for i in range(1, len(highs) - 1):
        before_high, before_low = highs[i - 1], lows[i - 1]
        after_high, after_low = highs[i + 1], lows[i + 1]
        if after_low > before_high:
            low, high = before_high, after_low  # a gap left by a move up
        elif before_low > after_high:
            low, high = after_high, before_low  # and one left by a move down
        else:
            continue
        middle = (low + high) / 2.0
        if middle <= 0:
            continue
        size = vol.units((high - low) / middle * 10_000)
        if size < minimum_vol:
            continue

        # Filled? Anything after the third bar that traded into the range eats
        # it from whichever side it arrived on.
        top, bottom = high, low
        for j in range(i + 2, len(highs)):
            if lows[j] < top and highs[j] > bottom:
                top = min(top, max(bottom, lows[j]))
                bottom = max(bottom, min(top, highs[j])) if highs[j] < top else bottom
            if top - bottom < (high - low) * open_share:
                break
        if top - bottom < (high - low) * open_share:
            continue
        found.append((i, low, high, size))
    return found


def points(
    times: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    vol: Volatility,
) -> list[Point]:
    """Open imbalances as turning points, so levels can form at them.

    **A gap has no side**, like a mode and unlike a swing: price can arrive at
    it from either direction, and which side it is on depends only on where
    price is now. `Swing.HIGH` and `Swing.LOW` are the only turns `form`
    accepts, so a gap above the last price is emitted as resistance and one
    below as support.

    `confirmed` is the time of the **third** bar, not the middle one. The gap
    does not exist until the third bar has printed - that is what makes it a
    gap - so anything asking when this became usable must not be told the
    middle bar's time, which is a bar earlier than the evidence.
    """
    if not closes or len(times) != len(closes) or len(highs) != len(closes):
        return []
    spot = closes[-1]
    out: list[Point] = []
    for index, low, high, size in gaps(highs, lows, vol):
        middle = (low + high) / 2.0
        after = min(index + 1, len(times) - 1)
        out.append(
            Point(
                index=index,
                time=int(times[index]),
                price=middle,
                swing=Swing.HIGH if middle > spot else Swing.LOW,
                # How big the imbalance is, in basis points of volatility unit,
                # so it ranks the way prominence does for the other formations.
                prominence_bps=size * 10_000,
                confirmed=float(times[after]),
            )
        )
    return out
