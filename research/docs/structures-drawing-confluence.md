# Structures Drawing Confluence

Rationale moved out of `till_infinity/structures/drawing/confluence.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Zone.strength`

        Averaging is still wrong for the reason it always was - it would let a
        weak 15m level drag down a strong 4h one it merely happens to sit
        beside - so the best member is what a zone is worth.

        What is gone is the multiplier that used to lift that by 15% per extra
        timeframe. Confluence breadth was measured against whether the level
        went on to hold, over four replays, and it does not separate: four runs
        produced four different orderings, AUC 0.45-0.51, and a bootstrap over
        levels put the spread at -2.2 points [-6.3, +1.7]. A 4-deep zone was
        being lifted 45% on that. See research/strength.md.

        This orders what the agents are shown (`agents/data.py`) and what the
        CLI prints, so it is a live decision rather than a display detail.
        `depth` and `timeframes` are still on the zone for anyone who wants to
        judge for themselves.


## `combine`

    Grouping is on **zone overlap**, not on a single tolerance, and that is the
    difference between this working and not. A shared tolerance is necessarily
    expressed in one timeframe's volatility, and the timeframes differ by more
    than an order of magnitude - measured on gold, one volatility unit is $0.74
    on 5m and $9.87 on 4h. With a 5m-scale tolerance a 4h level would have to
    sit within about fifty cents of a 5m level to be considered the same price,
    which almost never happens, so nothing ever combined.

    A level's zone already encodes how precisely its own timeframe can place
    it. Two levels describe one price when those zones overlap - which is the
    same test `dedupe` uses within a timeframe, applied across them.

    `volatility` resolves each level's estimate; without it every level is
    measured with `vol`, which is only correct when they share a timeframe.

    Levels outside `span` are ignored rather than merged. Combining a 1m level
    into a 4h zone would drag the fused price toward whichever minute-scale
    wiggle happened to be nearby, which is precision about the wrong thing.


