# The 3-sigma trigger fires at 0.9 to 1.9 per cent, not the "genuinely rare" its own comment claims

**Measured 2026-11-05** on the lab with
[`research/harness/surprise_rate.py`](../harness/surprise_rate.py): the
production `statespace.Engine`, default settings, over 60,000 15-minute bars
per instrument from the broker cache - four traded markets and two Deriv
synthetics, about 59,940 readouts each.

| question | verdict |
|---|---|
| How often does `\|surprise\| >= 3` actually fire? | **0.91% to 1.86%** on traded markets - between **3.4x and 6.9x** the Gaussian rate of 0.27%, and well under a Student-t(4)'s 3.99% |
| Is the constant's stated justification right? | **No.** `DEFAULT_SIGNAL_SURPRISE` says a 3-sigma reading is "genuinely rare here"; it is roughly one bar in 54 to one in 110 |
| Is the *premise* behind it right? | **Yes, and both can be true.** The standardised innovation has sd **0.67 to 0.76**, so the bulk is narrower than Gaussian - conservative bands, as `band-coverage.md` found - while the tail past 3 is still four to seven times too heavy |
| Does the control come back empty? | **Yes.** The two constant-generator synthetics read **0.000%** at 3 sigma and 0.15-0.20% at 2, against 6.2-7.9% at 2 on traded markets |
| Does this explain the live desk's 9.1%? | **No.** Offline the same engine fires at 0.9-1.9%; the live reading was 5 to 10 times that, so the excess is environmental and not the threshold |

## Why this was measured

`statespace/config.py` sets the trigger and justifies it in the same breath:

> `DEFAULT_SIGNAL_SURPRISE = 3.0`
>
> 3.0 rather than 2.0 because `band-coverage.md` measured the 0.99 interval
> breaching at 0.0006 to 0.0018 - a 3-sigma reading is genuinely rare here,
> where on a Gaussian assumption it would not be.

On 2026-11-05 the live desk reported `readouts=441 proposals=40` over five
hours - **9.1%**, where a Gaussian 3-sigma is 0.27% and the comment's own
evidence argues for rarer still. A trigger meant to fire about once in 370
readouts had fired once in eleven. Two things could be true: the live
`surprise` is not distributed the way the comment assumes, or the live model
was under-dispersed. This separates them by running the production engine over
long contiguous histories, where neither restarts nor gaps can contribute.

## The reading

| instrument | readouts | >= 2 | >= 3 | >= 4 | sd |
|---|---|---|---|---|---|
| EURUSD | 59,940 | 6.73% | **1.40%** | 0.36% | 0.71 |
| GBPUSD | 59,939 | 6.49% | **1.26%** | 0.36% | 0.70 |
| USDJPY | 59,940 | 7.90% | **1.86%** | 0.63% | 0.76 |
| XAUUSD | 59,941 | 6.20% | **0.91%** | 0.19% | 0.67 |
| Volatility 75 Index | 59,941 | 0.20% | **0.000%** | 0.000% | 0.39 |
| Step Index | 59,941 | 0.15% | **0.000%** | 0.000% | 0.38 |

References at 3.0: Gaussian **0.270%**, Student-t(4) **3.994%**.

**The synthetics are the result that makes the rest believable.** They are
real markets with a known, constant-volatility generator, and the statistic
reads *exactly* zero past 3 sigma on both - 0 of about 120,000 readouts. An
estimator manufacturing surprise out of estimation error would have given them
the same answer it gives EURUSD. It does not, so the 0.91-1.86% on traded
markets is a property of those markets and not of the measurement.

## Two things that are both true

The comment's **premise** is sound and its **inference** is not.

The standardised innovation's sd is 0.67 to 0.76 rather than 1. The bulk of
the distribution is narrower than a Gaussian of the same name, which is
exactly what a 0.99 interval breaching at 0.0006-0.0018 describes: the bands
are conservative and almost nothing ordinary escapes them.

And the tail past 3 is four to seven times heavier than Gaussian anyway. A
distribution can be tight in the middle and fat at the edge - that is what a
mixture of volatility states looks like, and this desk already holds the
finding that `no-gaussian-band-is-calibrated`: a Student-t with 3 to 5 degrees
of freedom fixes the one-bar band on 64 of 64 out of sample.

So "the 0.99 interval rarely breaches" does not license "3 sigma is rare".
They are statements about different parts of one distribution, and the second
was inferred from the first rather than measured.

## What this does not settle

**It is a firing rate, not an edge.** Nothing here says whether 3.0 is the
right threshold to *trade*; it says what the threshold costs in events. The
question of whether a proposal at 3 sigma pays is
[`impulse-vol.md`](impulse-vol.md)'s, and its answer for direction is no.

**The live excess is still unexplained.** Offline this engine fires at
0.9-1.9% on contiguous history. The live desk read 9.1%. The gap is not the
threshold, and the candidates are the ones a live process has and a replay
does not: partially warmed members, feed gaps across restarts, and bars
arriving out of order. The 9.1% was also read *before* the cold-start fix
landed, so part of it may already be gone - the post-fix live rate has not
been measured, because the desk is inside its warm-up window.

**One interval, six instruments.** 15m only, and 60,000 bars per instrument
rather than the 198,000-294,000 the cache now holds. A rate this stable across
four traded markets is unlikely to move much, but it has not been checked at
1h or 1d, where the bar count per unit of time and the overnight gap both
change.

## What is worth doing next

Read the live rate again once the desk is warm, on the same statistic. If it
has fallen to 1-2% the cold-start fix explains the whole gap and nothing
further is needed. If it has not, the next candidate is bar ordering: the
engine refuses a bar at or before the last one folded, and a feed that
delivers out of order would both inflate `already_folded` and leave the member
folding a sparser series than it believes.
