"""The zone-crossing rule: which way each mode reads, and on which bar.

**Written because `strategies/zones.py` had no tests.** It is a registered
trading rule, 476 lines, and the only thing standing behind its four modes was
the docstring saying they must not share a branch - which is exactly the defect
its own comment records: `retest` and `flip` were once accepted, validated, and
ran as `break` while reporting cells under their own names.

`_side` is the whole decision and it is pure in `(zone, was, now, close)`, so it
is called directly on a stub rather than through a Nautilus strategy. The stub
carries only what the method reads: the mode, and the per-zone flip history.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from till_infinity.strategies.zones import MODES, Zones


@dataclass
class Fake:
    """One zone, carrying only what `_side` reads off it."""

    at: int = 1
    bottom: float = 100.0
    top: float = 110.0
    resistance: bool = True
    flipped: bool = False


def read(mode: str, zone: Fake, *, was: bool, now: bool, close: float, seen: bool = False) -> int:
    """`Zones._side` on a stub. `seen` is whether the flip was already reported."""
    stub = SimpleNamespace(
        tuning=SimpleNamespace(mode=mode),
        flipped={zone.at: seen} if seen else {},
    )
    return Zones._side(stub, zone, was=was, now=now, close=close)


# ------------------------------------------------------------------ the signs


def test_a_rejection_and_a_break_of_one_zone_are_opposite_trades():
    """**The two signs, and the reason the rule ships both.** `reject` trades
    price turning at a zone and `break` trades price leaving it; a rule that
    shipped one would be asserting the sign of the whole family."""
    zone = Fake(resistance=True)
    # Left a resistance zone downward: it held, so this is a sell.
    assert read("reject", zone, was=True, now=False, close=99.0) == -1
    # Closed through a resistance zone from outside: it failed, so this is a buy.
    assert read("break", zone, was=False, now=False, close=111.0) == +1


def test_a_support_zone_reads_the_mirror_of_a_resistance_zone():
    """`with_role` is the side a zone's own role points to - a resistance that
    breaks, breaks upward - so support must invert both readings and not just
    one. A sign error here is a rule that trades the correct setups backwards."""
    zone = Fake(resistance=False)
    assert read("reject", zone, was=True, now=False, close=111.0) == +1
    assert read("break", zone, was=False, now=False, close=99.0) == -1


# ------------------------------------------------------- what does *not* fire


def test_price_still_inside_the_zone_is_not_a_crossing():
    """A crossing is an edge, not a state. Firing on the state re-proposes on
    every bar price spends in the zone, and the desk refuses each one as already
    held - which reads as a gate count rather than as the design error it is."""
    zone = Fake()
    for mode in MODES:
        assert read(mode, zone, was=True, now=True, close=105.0) == 0, mode


def test_leaving_a_zone_the_way_it_broke_is_not_a_rejection():
    """A rejection is price leaving **back the way it came**. Leaving the other
    way is the zone failing, which is the opposite trade, so admitting it here
    would make `reject` and `break` fire together on one bar."""
    zone = Fake(resistance=True)
    assert read("reject", zone, was=True, now=False, close=111.0) == 0


def test_a_break_is_only_read_from_outside_the_zone():
    """`outside` is both bars out. A bar that left the zone this instant is a
    rejection's shape, and counting it as a break too would double-count the
    one crossing under two modes."""
    zone = Fake(resistance=True)
    assert read("break", zone, was=True, now=False, close=111.0) == 0


# ------------------------------------------- the two modes that need history


def test_a_retest_needs_the_zone_to_have_broken_first():
    """`retest` is a continuation of a break that already happened, so an
    unbroken zone cannot produce one. Without the guard it is `reject`'s
    geometry under a continuation sign."""
    assert read("retest", Fake(flipped=False), was=True, now=False, close=111.0) == 0
    assert read("retest", Fake(flipped=True), was=True, now=False, close=111.0) == +1


def test_a_retest_that_fails_is_a_different_trade_and_not_this_one():
    """Leaving a broken zone on the side it came from is the retest *failing*.
    It is tradeable and it is not this rule, so it reads zero rather than being
    folded into the same cell."""
    assert read("retest", Fake(flipped=True), was=True, now=False, close=99.0) == 0


def test_a_flip_fires_on_the_bar_the_role_changes_and_not_after():
    """**`Zone.flipped` is a state that stays true once set**, so firing on the
    state would re-propose every bar for the rest of the zone's life. The edge
    is the state against what was already reported."""
    zone = Fake(flipped=True)
    assert read("flip", zone, was=False, now=False, close=105.0, seen=False) == +1
    assert read("flip", zone, was=False, now=False, close=105.0, seen=True) == 0


def test_an_unflipped_zone_never_reads_as_a_flip():
    assert read("flip", Fake(flipped=False), was=False, now=False, close=105.0) == 0


# ------------------------------------------------------------- the dispatcher


def test_every_mode_has_its_own_branch_rather_than_falling_through():
    """**The defect this file exists for.** The first version branched on
    `reject` and let everything else fall to the `break` arm, so `retest` and
    `flip` were accepted, validated, and ran as `break` while reporting cells
    under their own names - numbers for a rule that never ran.

    Asserted by asking each mode for a reading on the one geometry that is
    unambiguously a `break`: if a mode is silently aliased to it, it answers
    like it. `break` itself is excluded, being the thing compared against.
    """
    zone = Fake(resistance=True, flipped=False)
    broke = {"was": False, "now": False, "close": 111.0}
    assert read("break", zone, **broke) == +1
    for mode in (m for m in MODES if m != "break"):
        assert read(mode, zone, **broke) == 0, f"{mode} reads like a break"


def test_a_mode_in_the_table_with_no_branch_raises():
    """A mode that validates and then does nothing is the same failure as one
    that validates and runs a different rule: it produces a cell under a name
    nothing computed. So the dispatcher's fallthrough raises."""
    with pytest.raises(ValueError, match="is in MODES and has no branch"):
        read("sideways", Fake(), was=True, now=False, close=99.0)
