# Does this desk have an edge, and what sign is it

The question everything else waits on. A strategy with an unknown sign cannot be
sized, and sizing is what turns an edge into money - so this is measured before
any of the sizing machinery in `trading/scaling.py` is switched on.

## Why it had never been answered properly

Three reasons, and each of them was found on 2026-09-11:

**The pooled figure was a composition.** `research/choosing.md` reports every
strategy negative at **-0.216R** over 536 counterfactuals. That number mixes
strategies since removed with strategies still running, and
`research/instruments.md` records what happens when this project pools across
strategies: an entire instrument investigation ran on what turned out to be one
strategy wearing an instrument's name. Fourth Simpson reversal of the day.

**43% of closes were missing.** They were journalled as `unattributed`
observations rather than outcomes, carrying profit and seconds and nothing else,
because the position outlived the `_refs` entry linking it to its decision. And
the loss is **not random**: unattributed closes were held a median **1,683
seconds against 493**. Every R-based figure was computed on the short half.

**Money and R disagree.** `research/instruments.md`: the book's best-looking
instrument was a **single +622.63 trade** whose mean R was -0.028. Any answer has
to survive removing its own best trade.

## The measurement

All 688 closes on record - 398 outcomes plus 290 `unattributed` observations,
over 16 days - keyed by strategy. Money is available for every close; R only for
the attributed ones, and that limitation is stated rather than worked around.

| strategy | n | $ total | mean R | live |
| --- | ---: | ---: | ---: | --- |
| **sweep-aware** | 161 | **+133.31** | **+0.154** | yes |
| opportunity | 9 | -64.89 | -0.209 | was |
| level-scalp | 5 | -84.44 | -0.754 | no |
| thesis-only | 360 | -88.29 | -0.136 | no |
| confluence-scalp | 30 | **-191.12** | **-0.357** | was |
| snap | 29 | -210.38 | - | no |
| runner | 47 | -250.90 | -0.127 | no |
| fade-to-value | 30 | -343.54 | -0.573 | no |

**The live book was net -208.32 over 206 closes.**

## The answer, bootstrapped

4,000 resamples, 95% intervals, split by time, and each reported without its own
best trade:

| | n | mean | 95% CI | first half | second half | less its best trade |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| **sweep-aware** $ | 161 | +0.828 | **[-1.45, +3.21]** | +0.72 | +0.93 | **+0.382** |
| **sweep-aware** R | 77 | +0.154 | **[-0.022, +0.346]** | | | |
| **confluence-scalp** $ | 30 | -6.371 | **[-12.21, -0.04]** | -8.57 | -4.17 | **-7.684** |
| **confluence-scalp** R | 10 | -0.357 | **[-0.696, -0.018]** | | | |

**`sweep-aware` is probably positive and not yet proven.** The right sign,
positive in *both* halves, and it survives removing a +72.12 trade - the mean
halves to +0.382 and stays positive. But the interval touches zero on both money
and R. **That is not enough to lever.**

**`confluence-scalp` is confidently negative.** The interval excludes zero on
both measures, both halves are negative, and it is worse without its best trade.
It was switched **on** the same morning on the argument that its mean peak of
+1.401R was the regime `ride`'s exit was built for. That argument was about the
exit and this measurement is about the whole strategy, and the measurement wins.

## What was done about it

`TRADING_STRATEGIES` went from six to four: `origin-swing, sweep-aware,
approach-scalp, momentum-scalp`.

`confluence-scalp` was removed **on the evidence above**. `opportunity` was
removed on **n=9**, which is not evidence - it is precaution, and it is recorded
as precaution so nobody later mistakes it for a finding. The three that remain
beside `sweep-aware` have almost no record between them, which makes the next
few days a clean read on the one strategy that might have a sign.

## When this gets settled

At the measured spread of R (sigma 0.824) and mean +0.154, the interval excludes
zero at **110 R-carrying closes**. There are 77. So **33 more**, and since
2026-09-11 the arithmetic is recorded on unattributed closes too, which roughly
doubles the rate at which they accumulate.

Days, not weeks. And until then the honest description of this desk is: **one
strategy with a plausible edge that has not been demonstrated, and no basis for
increasing size.**

## What this does not say

* **Not that `sweep-aware` works.** A positive point estimate whose interval
  includes zero is a reason to keep measuring, not a reason to believe.
* **Not that the removed strategies are bad.** `opportunity` at n=9 is unjudged,
  and several of the others were removed for reasons recorded elsewhere.
* **Not that money and R agree.** `sweep-aware` is +133.31 and +0.154R, which
  point the same way here - but `research/instruments.md` has a case where they
  pointed opposite ways and money was the misleading one.
* **Nothing about size.** `research/compounding.md` is where the ruin arithmetic
  belongs, and an edge this marginal has ruin properties that a mean alone does
  not describe - especially one living in a tail, which
  `research/exiting.md` says this one does.
