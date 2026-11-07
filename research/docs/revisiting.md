# Do origins hold when price comes back?

Run 2026-11-07 over **12 instruments and 1.44M 15m bars**, 37,542 origins and
34,713 decided first visits. **No.** The hold rate is a property of the
distance the band sits at, not of the origin: a placebo matched on width, side
and distance-from-price reproduces it exactly. And the finding the original
harness produced — that holds weaken with each revisit — is an artefact of a
two-bar index error worth **+0.254 of hold rate**.

| | visit 1 | visit 2 | visit 3 | visit 4 |
| --- | --- | --- | --- | --- |
| `revisits.py`'s index | **0.931** | 0.694 | 0.622 | 0.645 |
| the correct index | 0.677 | 0.631 | 0.647 | 0.645 |
| distance-matched placebo | 0.671 | 0.644 | 0.662 | 0.684 |
| block-shuffled walk | 0.613 | 0.615 | 0.642 | 0.662 |

## What the look-ahead was worth

`revisits.py` scans from `int(origin.when) + 1` — the volatility turn. An
origin does not exist until the impulse that followed broke structure, which is
later, and the retired `Origin.settled` docstring states it in terms: "**Not
the same as `when`, and the difference is a look-ahead bug.**"

Measured rather than argued: **0 of 37,542 origins were knowable on their own
bar.** The delay runs 1 to 29 bars with a median of 2. Those are precisely the
bars the impulse spends travelling away from the zone — which is `revisits.py`'s
own definition of a bounce. It scores the definitional impulse as a hold.

**+0.254 on the first visit**, 0.931 against 0.677 on 37,472 decided visits.

**And the inflation is confined to visit 1** — +0.254, +0.063, −0.024, −0.000 —
which is the mechanism's own signature, since only the first visit overlaps the
impulse. That detail is what destroys the headline. The harness exists to test
whether holds weaken as a zone is revisited, because each visit is interest
being filled. Its contaminated numbers decay convincingly, 0.931 to 0.694 to
0.622. The correct numbers are **0.677, 0.631, 0.647, 0.645** — flat after the
first visit. The decay was the look-ahead washing out, nothing more.

## Does the origin beat its own distance?

A hold rate on its own measures the distance the band sits at. So the control
that matters is not a walk, it is a **placebo matched on distance**: the same
width, the same side, the same gap from the price it was knowable at, placed at
a time with no origin.

Real beats the walk at the first visit, 0.677 against 0.613. **The placebo also
beats the walk, at 0.671.** The origin's own contribution is **+0.006**, and it
is negative at every later visit — −0.013, −0.015, −0.039.

So the ordering is `real ≈ placebo > walk`, and the whole excess over a walk is
geometry. This is the same shape as the 82% return rate being matched by a
distance-matched placebo on every class: an origin picks a distance, not a
probability.

## How this one is causal by construction

`indicators.levels.Origins` is streaming — `handle_bar` keeps a 40-bar window
and recomputes `chains()` over it — so what it holds at bar `t` used only bars
up to `t`. An origin's knowable time is **the bar it first appears at**, and no
`settled` field is needed. A fixed index can be got wrong; first appearance
cannot.

**The full-series shortcut was checked and refused.** `chains()` documents that
"a leg that extends is re-read rather than updated in place", so a leg's `end`
grows as later bars arrive and the origins derived from it move with it.
Computing legs once over the whole series and taking each leg's end as its
knowable time is the same hindsight replacement the look-ahead audit found in
`zigzag` and `displacements.nodes`. Streaming costs 40 comparisons a bar, so
there was nothing to buy by being clever.

## Why `revisits.py` was not simply corrected

It imports `till_infinity.structures`, retired alongside `till_platform`, so it
has not been able to import since that move. Changing one index in a file that
cannot run is a fix nobody can check and is indistinguishable from doing
nothing. `revisiting.py` measures the same question against the live
implementation instead, which is why there is a number here at all.

## What none of this establishes

* **One definition of a hold.** `BOUNCE_VOL` 1.0 units away before
  `BREAK_VOL` 0.5 through the far side, resolved within 48 bars. Not swept.
* **No trade.** This reads price, not P&L. A hold rate is not an edge, and the
  spread is not charged anywhere in it.
* **`keep=4` origins per leg**, the shipped default. A rank-1 origin nearest
  the leg's end may behave differently from rank 4; pooled here.
* **The walk arm needed a fix to exist at all.** Built with `open == close` it
  has no candle bodies, `PUSH_BODY` of 0.70 can never match, and it silently
  found zero origins — a control that did not run reads exactly like one that
  ran and agreed. It now carries real bodies, and an arm with too few origins
  says so loudly.
