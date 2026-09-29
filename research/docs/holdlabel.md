# The hold label is biased by five points, not twenty-five, and the ratchet is all of it

Run: `python research/harness/holdlabel.py --touches 200000`

**Measured 2026-09-30.** 200,000 touches on a pure random walk, every rule over the
**same paths** so a difference is the rule and not the sample.

| rule | hold% | reject | break | trap | chop |
| --- | ---: | ---: | ---: | ---: | ---: |
| symmetric *(control)* | **49.9** | 99,767 | 100,233 | 0 | 0 |
| **production** | **55.0** | 108,893 | 70,032 | 18,999 | 2,076 |
| fixed origin | **49.9** | 95,833 | 75,579 | 20,601 | 7,987 |
| chop included | 54.4 | 108,893 | 70,032 | 18,999 | 2,076 |
| traps as holds *(not production)* | **64.6** | 108,893 | 70,032 | 18,999 | 2,076 |

## What is true

**There is a real definitional bias, and it is the ratcheting origin.** Production reads
**55.0%** on noise where a symmetric rule reads 49.9%. Replace the ratchet with a fixed
reference and it returns to **49.9%** — so the ratchet is **+5.1 points and the entire
effect**.

The mechanism is in `reactions.py:1154`, and the code says it plainly:

> *"a deeper print re-extends it and moves the origin with it"*

`touch.origin = price` on every deeper print while the leg is still running. So a hold
needs `resolve_vol` retraced from a **moving** extreme that keeps resetting, while a
break needs `resolve_vol` through the **fixed** level and then six bars of survival. On
a random walk the first is simply easier to satisfy.

**So the null for a hold rate is 55%, not 50%.** Any argument that treated 50% as the
baseline was wrong by five points, and that correction should be applied wherever it was.

## What is not true

A report attributed 67–76% on noise to two asymmetries, the first being that *failed
breaks count as holds*. That is not what production does. `Stats.hold_rate` is

    rejects / (rejects + breaks + traps)

so a trap sits in the **denominator** and *lowers* the rate. `learning/breaking.py` never
references `Outcome.TRAP` at all. Trap-as-holding exists in exactly one place —
`levels.py:769`, the state machine — where it decides `FLIPPED`/`TESTED` and whether to
decay the level's history. That affects level state and future weighting, not the
statistic.

And the arithmetic identifies where 67% came from. Move traps from the denominator into
the numerator and this harness reads **64.6%**, against production's 55.0%. That single
change is the difference, so the reported figure measures a reimplementation rather than
the desk.

**A third asymmetry runs the other way and is worth knowing before anyone "fixes" it.**
`resolve_vol` is 1.5 and `trap_vol` is **0.5**: confirming a break demands 1.5 units
through *and* six bars, while voiding it demands only 0.5 units back. A break is three
times easier to lose than to win, so on noise 19,000 attempts become traps — and because
traps are in the denominator, that pushes the hold rate **down**. It is not part of the
inflation.

**Chop exclusion is negligible at the correct volatility unit** — 55.0% against 54.4%,
worth +0.6 points. It matters only when the unit is badly wrong: understate volatility by
half and 55,632 touches end undecided, at which point including them moves the rate from
58.3% to 42.1%. That is a reason to keep the volatility unit honest, not a reason to
change the denominator.

## Measuring in volatility units cannot manufacture holds

The control settles the question the original report raised first. The symmetric rule
reads **49.9%, 49.9%, 49.9%** at volatility units of half, correct, and double. A rule
whose reading moves with the unit is reading volatility; this one does not. What the unit
changes is the **mix** — too small and touches end undecided, too large and they resolve
early — which is the one part of the original report that holds without qualification.

## What this does and does not invalidate

**Invalidated: absolute readings against a 50% null.** A replayed 87% hold rate is 87%
against a **55%** baseline, not against 50%. Still a large effect — 32 points of it is
the market — but the headline number should carry its null.

**Not invalidated: the differential results**, which is where every trading claim in this
folder actually lives. A bias that applies to all touches roughly equally cancels in a
comparison:

* `experience` quintile 1 breaks **15.0%** against quintile 5 at **2.9%** — fivefold,
  monotone across all five;
* `trend.py`'s top efficiency decile breaks **1.4%** against chop's **11.3%**.

Neither is a statement about the level of the hold rate. The conclusion that "the hold
rate, and the skill built on it, measure the label" is too strong: it holds for the
level and not for the spread.

## What to do about it, in order

1. **State the null.** Wherever a hold rate is quoted as evidence, quote 55% beside it.
   This costs nothing and fixes the actual error.
2. **Add a symmetric label in parallel**, not as a replacement. Swapping the outcome rule
   would silently redefine every statistic already recorded and break comparability with
   everything in this folder. Measured alongside on the same touches, the two can be
   differenced — which is the only way to get the real number rather than assert it.
   [`trap-levels.md`](trap-levels.md) is the working precedent: it scores level placements
   on a symmetric ±1 sigma race precisely so the +5.1 here cannot leak into the comparison,
   and its control confirms the property this harness asserts — across seven placements and
   twenty random-walk series it reads **48.8–50.1%**, flat to 1.2 points.
3. **Leave `trap_vol` alone** until someone measures it deliberately. It biases the rate
   downward, so "fixing" it in the same pass as the ratchet would move the null in two
   directions at once and the result would be uninterpretable.

## What is not established

* **This is a random walk, not a market.** It bounds what the *label* does on noise. It
  says nothing about how much of a real 87% is structure, beyond moving the baseline.
* **The horizon is 12 bars and the trap window 6**, production's defaults. A desk running
  other values has a different null and should re-run this rather than quote it.
* **Bar geometry is ignored.** Production sets the extreme from the wick and the origin
  from the close (`reactions.py:1145`); this harness has one price per bar, so it cannot
  see wick-versus-close effects. That is the most likely reason a replay would read
  differently from this, and it is the next thing to model.
* **A flat control is not a free pass for the level of anything.** The +5.1 measured here
  cancels in a differential and nowhere else, so a study needing an absolute rate still
  needs its own null. [`trap-levels.md`](trap-levels.md) shows the cost of getting that
  null wrong from the other direction: its first control was five series carrying a 4.7
  point spread of their own, and both the positive and the negative reading were available
  from that table.
