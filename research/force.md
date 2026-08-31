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

## Break rate across each feature, weakest fifth to strongest

| feature | 1st | 2nd | 3rd | 4th | 5th | spread | AUC |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **approach_vol** | 49.8% | 51.1% | 54.6% | 58.6% | **63.8%** | **+14.0%** | 0.5600 |
| **depth_vol** | 64.6% | 60.6% | 58.6% | 55.8% | **38.3%** | **−26.3%** | **0.4010** |
| strength | 51.5% | 53.9% | 55.6% | 54.1% | 62.9% | +11.3% | 0.5404 |
| experience | 51.2% | 54.7% | 55.2% | 55.9% | 60.8% | +9.6% | 0.5368 |
| run_vol | 55.0% | 50.7% | 52.2% | 59.0% | 61.1% | +6.1% | 0.5000 |
| up_rate | | | | | | | 0.4892 |

At n=10,871 the standard error of an AUC is about 0.006, so 0.560 is eleven
standard errors from nothing and 0.401 is eighteen. Both are real.

## The claim holds

**Arrival speed predicts breaks, monotonically.** Fast arrivals break 59.8% of
the time against 51.4% for slow ones, and the quintile ladder rises without a
kink: 49.8, 51.1, 54.6, 58.6, 63.8. AUC 0.5600.

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
barely enters the zone breaks 64.6% of the time; one that pushes deep into it
breaks 38.3%. AUC 0.4010, which read the right way round is 0.599 - stronger
than arrival speed.

The reading that fits: a touch that pushes deep into a level and still resolves
inside thirty minutes has been *absorbed* - that is what a long rejection wick
is. One that clips the edge and keeps going was never stopped at all. Depth is
evidence the level did something.

Stated as a mechanism that is a guess; stated as a number it is the strongest
single separator found so far, and it was sitting in the feature set unused.

## What does not predict a break

**`up_rate`, at AUC 0.4892 - nothing.** The level's own record of which way its
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
