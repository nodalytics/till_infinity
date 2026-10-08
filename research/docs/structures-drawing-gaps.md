# Structures Drawing Gaps

Rationale moved out of `till_infinity/structures/drawing/gaps.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `points`

    **A gap has no side**, like a mode and unlike a swing: price can arrive at
    it from either direction, and which side it is on depends only on where
    price is now. `Swing.HIGH` and `Swing.LOW` are the only turns `form`
    accepts, so a gap above the last price is emitted as resistance and one
    below as support.

    `confirmed` is the time of the **third** bar, not the middle one. The gap
    does not exist until the third bar has printed - that is what makes it a
    gap - so anything asking when this became usable must not be told the
    middle bar's time, which is a bar earlier than the evidence.



## The family, added 2026-10-08

`gaps` drew one shape - the three-bar fair-value gap - and the desk reads five
more. They are all the same claim, *price passed here without transacting
properly*, differing only in what counts as evidence, so they live in one
module rather than six.

| kind | the evidence | emitted |
|------|--------------|---------|
| `fvg` | three bars, the first's high below the third's low | midpoint |
| `vi` | two bars whose **bodies** gap while their wicks still overlap | midpoint |
| `og` | two bars that do not overlap **at all**, wicks included | midpoint |
| `void` | one bar that is nearly all body - traversed, not auctioned | midpoint |
| `ifvg` | an `fvg` price has *closed* through, read the other way up | midpoint |
| `bpr` | where an up `fvg` and a down `fvg` overlap | midpoint |

### What each one is for

`vi` and `og` are the two halves of a distinction the three-bar form cannot
make. A body gap whose wicks overlap says price **was** quoted across the band
and barely traded there; a true gap says it was never quoted at all. The
three-bar shape collapses those into one object and this is the only place that
separates them.

`void` is where the desk's displacement rule lands as a formation. A bar whose
body is `VOID_BODY` of its range and whose range reaches `VOID_VOL` units is a
bar price travelled rather than auctioned, and its **body** is the band - the
wicks are where price was rejected. It is the one kind here defined by a single
bar, and `VOID_BODY` is imported from `learning.touches` rather than restated,
because two copies of the desk's number would drift apart the first time it
moved. It has moved once already, 0.70 to 0.65 on 2026-10-08.

`ifvg` is the only kind that **needs** a filled gap. `gaps` throws those away
by its own definition - a gap price has traded back through is finished
business - and `ifvg` keeps exactly what it discards, so the fill scan earns
its keep twice. The test is a **close** beyond the far edge rather than a wick,
because a wick through a band is the band holding.

`bpr` is the narrowest object of the six: two imbalances in opposite directions
covering one band, which means price left it unfinished going both ways. It is
stamped at the later of the two, since that is when the overlap existed.

### One fill scan, extracted rather than rewritten

`_remaining` is the erosion rule lifted out of `gaps` **unchanged**. The `gap`
pass draws levels in production, so a tidier rule would have been a silent
change to the live book dressed up as a refactor. Every kind that can be filled
now asks the same function.

### `opens`, and why two kinds are skipped without them

`vi` and `void` are both claims about where a bar's **body** sits, which highs
and lows cannot express. `points` skips them rather than approximating when it
is not given opens: a body inferred from the range is a different object
wearing the same name. The engine passes `series.opens`, so they draw in
production; a caller that does not gets the other four and no warning, which is
the one sharp edge in this interface.

### What is already measured, and it is not encouraging

`imbalance.md` took gap **edges** at first touch and found **50.2%** against a
**51.5%** breakeven and a 49.6% placebo - a loss, not a small edge. Two things
keep that from settling this. It measured the wick edge and this module emits
the **midpoint**, so it is not the same price; and none of the five kinds added
here were in it at all.

So none of this is a claim that they work. Each is emitted as a turning point
and the outcome machinery is left to say whether price respects it. The placebo
in that study is the bar to clear: a kind that reacts like an ordinary prior
extreme at the same distance is a way of *noticing* a level rather than a
reason for one.
