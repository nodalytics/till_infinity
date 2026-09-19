# Structures Drawing Profile

Rationale moved out of `till_infinity/structures/drawing/profile.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `_visits`

    The bar of each occasion that came closest to the band's centre, so a turn
    is stamped at the price the band actually claims rather than at whichever
    end of the visit happened to be last.

    An occasion ends only after `gap` bars away. One bar of noise stepping out
    does not end a visit and start another - that would turn a single camp into
    a dozen turns and manufacture a level out of one occasion.


## `points`

    A fourth formation beside `pips`, `runs` and `origin_points`, on the same
    terms - the same `Point`, so nothing downstream can tell which pass found a
    level.

    **A band has no side**, which is the honest difference from the other
    three. A swing high is where price turned down and a swing low is where it
    turned up; a band where a lot of supply changed hands is neither, and price
    can arrive from either direction. `Swing.HIGH` and `Swing.LOW` are the only
    turns `form` accepts, so a band is emitted as whichever it is *not*
    currently on - one above the last price behaves like resistance and one
    below like support, which is the reading a cost-basis shelf gets.

    One point per **visit**, not one per band. `form` needs three turns within
    a volatility unit, so a formation emitting one point per band could never
    make a cluster; and a band price came to once is not a level whatever its
    density says, so this is the right test rather than a way around one.


