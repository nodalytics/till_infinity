"""Which way a zone reads on one bar, for every rule that trades a zone.

**One hypothesis, several ways of nominating the level.** `delivering.md` puts
it in a table: a ZigZag pivot, a change in state of delivery, an **order block
origin**, a **displacement origin**, a supply/demand zone and this desk's
`Level` are all "the last price at which the market changed its mind", and the
claim attached to every one of them is the same - price comes back to that
point and is rejected there. `indicators/levels.Origin` says the same thing in
one line: an order block, a displacement origin and a supply/demand zone are
the same candle under three names.

So the *scoring* belongs in one place and the *nomination* belongs with each
rule. This module is the scoring: given a zone, a mode and where the last two
closes sat, which way does it read. `strategies/zones.py` nominates with
Bjorgum key levels and `strategies/origins.py` with displacement origins and
breaks of structure; all three read their crossings here, so a result from one
is comparable with a result from another.

**Extracted from `zones.py` without a change in behaviour**, and that claim is
what `tests/test_zone_rules.py` is for - it was written against the original
and passes against this unchanged, having first been checked to fail on a
mutation of the dispatcher.
"""

from __future__ import annotations

from typing import Any, Protocol

#: The four readings a zone offers, and they are not variations - two are
#: **reversal** trades and two are **continuation** trades, so a rule that
#: ships one is asserting the sign of the whole family.
#:
#: * `reject` - price enters the zone and leaves back the way it came.
#:   **Reversal.** The zone held.
#: * `break` - price closes through the zone from outside. **Continuation.**
#:   The zone failed.
#: * `retest` - price broke the zone earlier, has returned to it, and leaves
#:   again on the break side. **Continuation.**
#: * `flip` - the bar on which a zone's role changes. **Continuation** of
#:   whatever broke it.
MODES: tuple[str, ...] = ("reject", "break", "retest", "flip")

#: The two that need a zone to remember having been broken. A nominator whose
#: zones carry no break history can offer `reject` and `break` - which are
#: already exact opposites, so both signs are on the table - and must refuse
#: these rather than run them as something else.
NEEDS_HISTORY: frozenset[str] = frozenset({"retest", "flip"})


class Zone(Protocol):
    """What `side_of` reads off a nominated zone, whoever nominated it."""

    #: A stable identity for this zone, for the caller's own bookkeeping.
    at: int
    bottom: float
    top: float
    #: True when the zone sits above price as supply, False for demand.
    resistance: bool
    #: Whether this zone's role has ever changed. False where the nominator
    #: does not track it, in which case `MODES` must be narrowed - see
    #: `NEEDS_HISTORY`.
    flipped: bool


def side_of(zone: Any, mode: str, *, was: bool, now: bool, close: float, seen: bool) -> int:
    """Which way this zone reads on this bar: +1, -1 or 0.

    `was` and `now` are whether price was inside the zone on the previous bar
    and this one, so **a crossing is an edge and never a state**: firing on the
    state re-proposes on every bar price spends in the zone, and the desk
    refuses each one as already held - which reads as a gate count rather than
    as the design error it is.

    `seen` is whether a flip has already been reported for this zone, which the
    caller keeps. `flipped` is a state that stays true once set, so `flip`
    without it would re-propose every bar for the rest of the zone's life.

    **Every mode is dispatched by name and an unhandled one raises.** The first
    version of this branched on `reject` and let everything else fall through
    to the `break` arm, so `retest` and `flip` were accepted, validated, and
    ran as `break` while reporting cells under their own names - a configuration
    that produces numbers for a rule that never ran.
    """
    left = was and not now
    outside = not was and not now
    up = close > zone.top
    down = close < zone.bottom
    # The side a zone's own role points to: a resistance that breaks, breaks
    # upward.
    with_role = +1 if zone.resistance else -1

    if mode == "reject":
        # Left the zone back the way it came. The zone held: reversal.
        return -with_role if left and (down if zone.resistance else up) else 0
    if mode == "break":
        # Closed through from outside. The zone failed: continuation.
        return with_role if outside and (up if zone.resistance else down) else 0
    if mode == "retest":
        # Already broken, price back inside, now leaving on the break side.
        # Continuation. Leaving the other way is the retest *failing*, which is
        # a different trade and not this one.
        if not (zone.flipped and left):
            return 0
        return with_role if (up if zone.resistance else down) else 0
    if mode == "flip":
        # The bar the role changes on. Read against `seen`, because a role
        # change is an **edge** and `flipped` is a state that stays true.
        return 0 if (not zone.flipped or seen) else with_role
    raise ValueError(f"{mode!r} is in MODES and has no branch here")


__all__ = ["MODES", "NEEDS_HISTORY", "Zone", "side_of"]
