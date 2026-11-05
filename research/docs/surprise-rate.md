# The 3-sigma trigger fires at 0.9 to 1.9 per cent, not the "genuinely rare" its own comment claims

**Measured 2026-11-05** on the lab with
[`research/harness/surprise_rate.py`](../harness/surprise_rate.py): the
production `statespace.Engine`, default settings, over 60,000 15-minute bars
per instrument from the broker cache - four traded markets and two Deriv
synthetics, about 59,940 readouts each.

| question | verdict |
|---|---|
| How often does `\|surprise\| >= 3` actually fire? | **0.91% to 1.86%** on traded markets - between **3.4x and 6.9x** the Gaussian rate of 0.27%, and well under a Student-t(4)'s 3.99% |
| And at the thresholds either side of it? | **1.5 sigma: 15.2-17.4%. 2.0: 6.2-7.9%. 2.5: 2.4-3.7%.** The excess over Gaussian *grows* with the threshold - 1.18x at 1.5, 1.48x at 2.0, 5.19x at 3.0, 60x at 4.0 - so below about 1.5 sigma the distribution is essentially Gaussian and the fat tail only bites past 2 |
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

| instrument | readouts | >=1.0 | >=1.5 | >=2.0 | >=2.5 | >=3.0 | >=3.5 | >=4.0 | sd |
|---|---|---|---|---|---|---|---|---|---|
| EURUSD | 59,940 | 33.94% | 15.83% | 6.73% | 2.91% | **1.40%** | 0.69% | 0.36% | 0.71 |
| GBPUSD | 59,939 | 33.28% | 15.22% | 6.49% | 2.78% | **1.26%** | 0.67% | 0.36% | 0.70 |
| USDJPY | 59,940 | 35.48% | 17.44% | 7.90% | 3.66% | **1.86%** | 1.05% | 0.63% | 0.76 |
| XAUUSD | 59,941 | 34.22% | 15.68% | 6.20% | 2.43% | **0.91%** | 0.36% | 0.19% | 0.67 |
| Volatility 75 Index | 59,941 | 12.41% | 1.94% | 0.20% | 0.010% | **0.000%** | 0.000% | 0.000% | 0.39 |
| Step Index | 59,941 | 11.67% | 1.64% | 0.15% | 0.015% | **0.000%** | 0.000% | 0.000% | 0.38 |

References:

| | >=1.0 | >=1.5 | >=2.0 | >=2.5 | >=3.0 | >=3.5 | >=4.0 |
|---|---|---|---|---|---|---|---|
| Gaussian | 31.73% | 13.36% | 4.55% | 1.24% | **0.270%** | 0.047% | 0.006% |
| Student-t(4) | 37.39% | 20.80% | 11.61% | 6.68% | **3.994%** | 2.49% | 1.61% |
| Student-t(3) | 39.10% | 23.06% | 13.93% | 8.77% | **5.767%** | 3.95% | 2.80% |

## The excess is not a constant, it grows with the threshold

EURUSD against a Gaussian of the same name:

| threshold | 1.0 | 1.5 | 2.0 | 2.5 | 3.0 | 3.5 | 4.0 |
|---|---|---|---|---|---|---|---|
| ratio to Gaussian | 1.07x | 1.18x | **1.48x** | 2.35x | **5.19x** | 14.8x | 60x |

**Below about 1.5 sigma the distribution is essentially Gaussian** - slightly
*thin*, in fact, which is what an sd of 0.7 means. The fat tail only begins to
bite past 2. So this is a Gaussian-ish core with a heavy tail attached, which
is what a mixture of volatility regimes produces and why no single named
distribution fits: every reading sits **between** Gaussian and Student-t(4),
nearer the Gaussian low down and drifting toward the t high up without ever
reaching it.

That shape is the reason the constant's comment could be half right. A
statement about the 0.99 interval is a statement about the core, where the
model is conservative and the data are close to Gaussian. It carries no
information about 3 sigma, which lives in the part of the distribution the
bands were never describing.

### What a different threshold would cost

Across 21 symbols at 96 bars a day, using the EURUSD-to-USDJPY range:

| threshold | share of readouts | proposals/day |
|---|---|---|
| 2.0 | 6.2-7.9% | 130-160 |
| 2.5 | 2.4-3.7% | 50-75 |
| 3.0 | 0.9-1.9% | 19-38 |
| 3.5 | 0.36-1.05% | 7-21 |

Moving from 3.0 to 2.0 multiplies candidates by about **five**, not the
seventeen a Gaussian table would predict. A threshold chosen from the Gaussian
column is wrong in both directions at once: too many events where it expected
few, and a smaller change in event count than expected when it is moved.

**The synthetics are the result that makes the rest believable.** They are
real markets with a known, constant-volatility generator, and the statistic
reads *exactly* zero past 3 sigma on both - 0 of about 120,000 readouts, and
flat at zero across 3.0, 3.5 and 4.0, so the control holds over the whole
grid rather than at one point. Their core is thin too (12.4% and 11.7% past 1
sigma against 31.7% Gaussian, sd 0.38-0.39): a constant generator is
predictable, the model fits it, and the surprise piles up near nothing. An
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
