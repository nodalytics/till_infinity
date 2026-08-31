# Does the force arriving at a level decide whether it breaks?

The desk claim, and it is a good one: a level can be perfectly valid and still
fail, because what matters is not only its own record but **how hard price is
coming at it**. Arrive gently and it holds; arrive with a run behind you and it
goes.

Two features already carried that and neither had ever been asked this
question. `approach_vol` is how fast price was travelling into the level, in
volatility units per bar; `run_vol` is how far the leg had already travelled.

It had to wait for [horizon.md](horizon.md). Asked of the whole record the
answer would have been measured on a population where a touch resolving inside
a minute resolves in the direction its side implies **100.0%** of the time -
there is nothing to separate when nothing breaks. At 300-1,800s the side is
right about 68% of the time, so a third of touches are breaks and the question
has an answer.

Harness: [`harness/force.py`](harness/force.py), over 10,871 resolved touches in
that band, 55.6% of them breaks. Read off `outcome` - reject, backcheck, break,
trap - which labels this directly rather than inferring it from the push.


## Correction, 2026-08-31: a trap is not a break

Every number first published in this document was computed with `trap` grouped
with `break`. It is not one. A trap is a **failed** break - price gets through,
traps whoever followed it, and comes back - so the level ultimately held and the
final push lands in the *hold* direction. Measured over 10,977 touches, with no
ambiguity at all:

| side | outcome | pushed up |
| --- | --- | --- |
| above | reject | 100.0% |
| above | **trap** | **100.0%** |
| above | break | 0.0% |
| below | reject | 0.0% |
| below | **trap** | **0.0%** |
| below | break | 100.0% |

A trap pushes exactly like a reject. Grouping it with breaks inflated the break
rate from **32.3% to 55.6%**, and produced two conclusions that were wrong:

* that the level's directional call is right **44.7%** of the time - below a
  coin. It is right **67.6%**.
* that inverting the trade in the highest break-risk fifth would turn 29.5%
  into 70.5%. It would turn **56.8% into 43.2%** - inverting loses.

**There is no sign error.** `outcome` and `push_vol` agree perfectly; the
inconsistency was in this document's own labelling, and it was found by chasing
a contradiction between two of its own measurements - [similarity.md](similarity.md)
had side-above touches pushing up 68.9% of the time, which implies a 31% break
rate, against this document's 55.6%. Both could not be true.

The corrected figures are below. The direction of every finding survives; the
sizes are smaller.


## Break rate across each feature, weakest fifth to strongest

| feature | 1st | 2nd | 3rd | 4th | 5th | spread | AUC |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **approach_vol** | 27.7% | 29.4% | 31.1% | 33.9% | **37.9%** | **+10.2%** | 0.5429 |
| **depth_vol** | 41.6% | 36.7% | 33.8% | 30.1% | **19.7%** | **−21.9%** | **0.4180** |
| strength | 29.6% | 31.0% | 32.3% | 30.5% | 38.2% | +8.6% | 0.5325 |
| experience | 29.8% | 31.3% | 32.0% | 33.8% | 34.6% | +4.8% | 0.5230 |
| run_vol | 55.0% | 50.7% | 52.2% | 59.0% | 61.1% | +6.1% | 0.5000 |
| up_rate | | | | | | | 0.4928 |

At n=10,871 the standard error of an AUC is about 0.006, so 0.560 is eleven
standard errors from nothing and 0.401 is eighteen. Both are real.

## The claim holds

**Arrival speed predicts breaks, monotonically.** Fast arrivals break 35.1% of
the time against 29.5% for slow ones, and the quintile ladder rises without a
kink: 27.7, 29.4, 31.1, 33.9, 37.9. AUC 0.5429.

That is a modest effect and a real one, and it is the first thing in this
repository to separate hold from break at all. It is also, notably, a different
result from [absorption.md](absorption.md), which measured absorption and
compression at the level and found neither separates. Force *arriving* is not
the same quantity as volume *absorbed*, and only one of them works.

`run_vol` - how far the leg had already come - does nothing at all. AUC 0.5000,
which is as clean a null as this repository has produced. **Speed on arrival
matters and distance travelled does not**, which is worth knowing because they
are the same intuition and only half of it survives.

## And something larger, running the other way

**`depth_vol` separates harder than anything else here, inverted.** A touch that
barely enters the zone breaks 41.6% of the time; one that pushes deep into it
breaks 19.7%. AUC 0.4180, which read the right way round is 0.582 - stronger
than arrival speed.

The reading that fits: a touch that pushes deep into a level and still resolves
inside thirty minutes has been *absorbed* - that is what a long rejection wick
is. One that clips the edge and keeps going was never stopped at all. Depth is
evidence the level did something.

Stated as a mechanism that is a guess; stated as a number it is the strongest
single separator found so far, and it was sitting in the feature set unused.

## What does not predict a break

**`up_rate`, at AUC 0.4928 - nothing.** The level's own record of which way its
touches went is the single strongest feature for *direction*
([learning.md](learning.md) has it at weight +2.29, ten times the next) and it
is worthless for *hold versus break*.

Those are different questions and this is the evidence that they are. A model
built to answer one has been assumed to answer the other.

`strength` and `experience` both lean the wrong way - stronger and
better-tested levels break *more*, at AUC 0.54. That is likely a confound
rather than a finding: both correlate with busy instruments and slower
timeframes. It is recorded because it is the opposite of what the names imply,
and anything reading `strength` as "this will hold" has it backwards.

## Digging in: together, and how big

**They are complementary, not redundant.** Fitted jointly over 10,904 touches,
a walk-forward logistic on the two reaches **AUC 0.658** - materially better
than either alone, with weights `approach_vol +0.255` and `depth_vol -0.779`,
which is the model saying what the quintile ladders say.

Two weak separators that disagree are worth more than two that agree, and that
is what these are: speed is about the move, depth is about the level.

**A break is the more predictable move but not the larger one.**

| | median \|push\| | mean \|push\| |
| --- | --- | --- |
| broke | **2.82v** | 3.38v |
| held | 2.08v | **5.67v** |

Breaks are bigger at the median and much smaller at the mean, because holds
have a fat right tail: most rejections are modest and a few run a very long
way. A model that trades breaks is trading the consistent side of a skewed
distribution, which is a different proposition from trading the bigger one and
should not be confused with it.

Per instrument the joint AUC runs from 0.509 on jp225 to 0.671 on euraud, and
break rates from 38.5% on eurgbp to 59.4% on us2000 - so both the separability
and the base rate are instrument-specific, which is the same shape
[paying.md](paying.md) found for direction.

## Does price *slow down* into a level it respects?

`approach_vol` is one reading taken when the touch opens. The desk describes a
**sequence** - price comes in, slows, pushes back, rejects, comes back - and
only the first frame of that is stored. The second is reconstructable from
bars: speed over the three bars immediately before arrival, over the speed of
the three before those. Below one is decelerating.

[`harness/slowing.py`](harness/slowing.py), 4,078 touches with enough bars
either side.

| feature | slowest fifth → fastest | AUC |
| --- | --- | --- |
| **slowing** | 50.3, 50.4, 50.4, 56.1, 55.0% | **0.5237** |
| approach_vol | 45.3, 49.7, 51.0, 56.9, 59.3% | 0.5573 |

    decelerating   2040 touches, 50.3% break
    accelerating   2038 touches, 54.6% break

**The claim holds and is weak.** Price decelerating into a level breaks 50.3%
of the time against 54.6% when it is still accelerating - the right direction,
a 4.3 point gap, AUC 0.5237. At n=4,078 the standard error of an AUC is about
0.009, so that is under three standard errors: real, and much smaller than
arrival speed's six-and-a-half.

**And it is almost perfectly orthogonal to arrival speed - correlation
+0.008.** That is the finding. A weak separator that is uncorrelated with a
strong one is worth more than a second strong one that agrees, because it is
new information rather than a restatement. `approach_vol` and `slowing` are
measuring different things: how fast price is going, and whether it is easing
off.

It is **not** in `breaking.py`, and the reason is practical rather than
principled: it needs the speed of the *preceding* bars, which nothing currently
carries at the moment a touch opens. Adding it means the engine tracking a
short speed history per series - a genuine change, justified by an orthogonal
+0.02 of AUC, which is worth doing and worth doing deliberately.

## Applied, and deciding nothing

`structures/breaking.py`. A single online logistic on the two features, one
model across the book because they are scale-free, learning from every
resolution and publishing `break_probability` on every level call.

Silent until 200 resolutions are behind it, and **`None` rather than 0.5 while
cold** - "no opinion" and "an even chance" are different claims, and a consumer
that cannot tell them apart will act on the second when it was handed the
first.

`chop` is not counted as a hold. A touch that went nowhere is not evidence the
level did anything, which is the discipline the rest of the package already
applies to it.

## What follows

Nothing is gated on this yet, and nothing should be until it is scored the way
[paying.md](paying.md) scores direction - a break rate is not money.

What it does change is where to look. There are now two measured separators for
a question nothing addressed before, both in the existing feature set, both
ignored by a model fitted to predict direction instead. The obvious next step
is a second head: **predict the break, not the direction**, on `depth_vol` and
`approach_vol`, and score it per instrument against the cost of being wrong.
