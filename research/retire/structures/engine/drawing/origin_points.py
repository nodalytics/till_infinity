"""Levels drawn where volatility turned and the move that followed broke structure.

A third formation beside `pips` and `runs`, offered on the same terms: the same
`Point`, so `as_of`, `form` and the whole outcome machinery cannot tell which
pass found a level, and the journal decides which price gets respected rather
than an argument here.

**What makes this one different.** `pips` selects bar extremes by prominence
and `runs` takes the boundaries between volatility runs; both ask *was this a
turn*. This asks a harder question - was it a turn that **led somewhere**: an
impulse large enough to matter, which took out the structure that had been
holding. Most turns are not, so this produces far fewer points than either.

Measured before it was built: price returning to one of these zones is turned
away 63.5% of the time on the first return and 55.6% on the second, against a
driftless-walk null near 33%. See `research/origins.md`.

**Confirmation is the break, not the turn.** A `pips` swing is knowable once
enough bars have passed, a `runs` swing once price retraces. An origin does not
exist until its impulse breaks structure, which is several bars after the turn
it is drawn at - so `confirmed` reads `Origin.settled`. Using the turn time
would draw a level at a price nobody could yet have known was one, which is the
look-ahead bug this whole field exists to prevent.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..vol.volatility import Volatility
from . import origins
from .pips import Point, Swing


def points(
    times: Sequence[float],
    prices: Sequence[float],
    vol: Volatility,
    *,
    move_vol: float = origins.MOVE_VOL,
    bars: int = origins.MOVE_BARS,
) -> list[Point]:
    """Turning points drawn at origins, newest last."""
    if len(prices) < 2 or len(times) != len(prices):
        return []
    unit = vol.price_units(prices[-1], 1.0)
    if unit <= 0:
        return []

    at: dict[float, int] = {}
    for index, when in enumerate(times):
        at.setdefault(float(when), index)

    found: list[Point] = []
    for origin in origins.Origins().observe(
        list(times), list(prices), unit, move_vol=move_vol, bars=bars
    ):
        index = at.get(float(origin.when))
        if index is None:
            continue
        # A down-launched impulse turned at a high, and the reverse.
        swing = Swing.HIGH if origin.launched == "down" else Swing.LOW
        found.append(
            Point(
                index=index,
                time=int(origin.when),
                price=origin.price,
                swing=swing,
                # The impulse, in basis points - the same measure `runs` uses,
                # and the thing that makes an origin worth a level at all.
                prominence_bps=(
                    abs(origin.size_vol * unit / origin.price * 10_000) if origin.price else 0.0
                ),
                # Settled when the structure broke. See the module docstring.
                confirmed=float(origin.settled or origin.when),
            )
        )
    return found
