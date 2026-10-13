# A relationship that holds for a while and then breaks

[The relationship screen](statespace-relationship-screen.md) fits one hedge
ratio and takes **one** Dickey-Fuller `t` over the whole out-of-sample half. Its
answer was that 0 of 190 traded pairs clear a null built from block-shuffled
real markets.

**That answers a narrower question than it appears to.** A pair that tracks
tightly for three months and then diverges contributes a reverting stretch and a
trending stretch to the same regression, and they cancel. The statistic is an
average over regimes, so a relationship present in only some of them averages
toward nothing - and the more cleanly it breaks, the more completely it cancels.

So the screen's result is "no traded pair has a **time-invariant**
cointegration", which is not the same claim as "no relationship".

It is also the one shape the desk's own machinery contradicts.
`relating.Relating` carries the hedge ratio as a **state** rather than a
constant, and `switching.py`, `changepoint.py` and `hmm.py` exist because the
regime is expected to change. A single global `t` assumes the opposite.

The harness is `research/ideas/episodic_relationships.py`.

## How much of a relationship has to survive before the screen sees it

Measured rather than argued. Each row is a planted pair whose two legs differ by
bounded noise for that share of the out-of-sample half and by a free walk
afterwards - a relationship that is **real and strong while it lasts** - over 12
seeds, with the screen's own `-4.07` bar:

| tied share | single `t` | passes -4.07 | windowed share | windowed median `t` | longest run |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1.0 | **-63.60** | 12/12 | 1.000 | -15.85 | 16 |
| 0.8 | -3.79 | 5/12 | 0.844 | -15.45 | 13 |
| **0.6** | **-2.29** | **0/12** | 0.688 | **-14.74** | 9 |
| 0.5 | -1.68 | 0/12 | 0.656 | -8.64 | 8 |
| 0.4 | -1.34 | 0/12 | 0.562 | -2.28 | 6 |
| 0.3 | -1.29 | 0/12 | 0.500 | -1.86 | 5 |

**At 60% tied the screen reads -2.29 and never once clears its bar, while the
same data read in windows gives a median `t` of -14.74 and nine consecutive
reverting windows.** The cliff is between 1.0 and 0.8.

A relationship does not have to be weak to be missed, only finite. The windowed
statistics degrade smoothly; the single `t` falls off a cliff and reports the
pair as unrelated.

## What replaces the single `t`

Non-overlapping 250-bar windows of the out-of-sample half - about five weeks at
1h, forty of them - and three statistics per pair:

* **share** - the fraction of windows reverting at `t < -2`. A pair reverting a
  third of the time has a relationship the global `t` would not report.
* **persistence** - `P(next window reverts | this one did) - P(next reverts)`.
  **This is the statistic that decides whether any of it is tradeable**, because
  the position is taken *after* the window is observed. An episodic relationship
  whose episodes cannot be seen coming is a description, not an edge.
* **breaks** - `P(next window trends | this one reverted)`, less the
  unconditional rate. Elevated, a reverting pair is one about to diverge, which
  is how a stat-arb book fails rather than underperforms.

Two ratio arms, neither allowed to peek: **fixed**, the first-half ratio held
throughout, and **rolling**, the ratio fitted on window `k-1` and applied to
window `k`. The rolling arm is `Relating`'s premise without the absorption
defect that made the screen's live arm read `-29`.

### The null is the same detector, and the comparison is between distributions

Run lengths and rolling minima in noise are longer than intuition allows, so
every statistic is also computed on the **two-real-leg block-shuffled null** - a
traded instrument against another traded instrument's returns in day-long
blocks, scrambled, which preserves both legs' tails exactly.

And the comparison is of *medians*, not extremes. The screen took the minimum
`t` over 553 null pairs, a severe multiplicity correction that asks whether the
best pair is extraordinary. The episodic question is whether traded pairs spend
*more* of their time reverting than unrelated ones - a shift in the middle of
the distribution, which a comparison of extremes has almost no power to detect.

## The answer is a null, and this time the test has demonstrated power

| | pairs | share | persistence | breaks | longest | median `t` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| traded, fixed ratio | 190 | 0.3250 | -0.0467 | 0.0000 | 3 | -1.6829 |
| block-shuffled null, fixed | 570 | 0.3117 | -0.0304 | 0.0000 | 3 | -1.6070 |
| traded, rolling ratio | 190 | **0.3077** | -0.0435 | 0.0000 | 3 | -1.6418 |
| block-shuffled null, rolling | 570 | **0.3077** | -0.0176 | 0.0000 | 3 | -1.5907 |

**Traded pairs spend 30.8% of their windows reverting and unrelated shuffled
pairs spend 30.8%.** On the rolling arm the two medians agree to four decimal
places. The fixed arm's 0.3250 against 0.3117 is a difference of 1.3 percentage
points, about half a window in forty.

**Persistence is negative in every arm**, and *more* negative for traded pairs
than for the null. Reversion does not predict reversion; it very slightly
anti-predicts, which is what a mean-reverting statistic measured on adjacent
independent windows does when there is no episode structure to find.

The tail counts agree, against 9.5 expected at a 95th-percentile bar:

| arm | statistic | null 95th pct | above it |
| --- | --- | ---: | ---: |
| fixed | share | +0.4359 | 12 of 190 |
| fixed | persistence | +0.1693 | 4 of 190 |
| fixed | breaks | +0.1029 | 9 of 190 |
| rolling | share | +0.4286 | 13 of 190 |
| rolling | persistence | +0.1778 | 6 of 190 |
| rolling | breaks | +0.1029 | 15 of 190 |

Every count is inside Poisson noise of 9.5 (sd 3.1). **Nothing is elevated in
either direction** - traded pairs are not more reverting than noise, and their
reverting episodes are not unusually prone to breaking.

### And no pair clears both gates

The pairs that spend the most time reverting are the dollar-bloc and CNH
crosses, at `share` 0.43 to 0.475:

| pair | windows | share | persistence | breaks | longest | median `t` | beats |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| USDCAD/AUDUSD | 40 | 0.475 | +0.1174 | -0.0243 | 4 | -1.69 | share |
| NZDUSD/AUDUSD | 40 | 0.475 | -0.0726 | -0.0256 | 3 | -1.82 | share |
| EURUSD/USDCNH | 39 | 0.462 | -0.0585 | +0.0292 | 4 | -1.82 | share |
| USDCHF/AUDUSD | 40 | 0.450 | +0.0085 | +0.0299 | 7 | -1.89 | share |
| GBPUSD/AUDUSD | 39 | 0.436 | +0.1084 | +0.0325 | 4 | -1.93 | share |

**Not one clears `share` and `persistence` together**, and the best persistence
among them (+0.1174) is short of the null's 95th percentile (+0.1778). This is
the case the harness was written to distinguish: a pair that reverts often but
unpredictably cannot be traded, because the episode is only visible once it is
over.

## What to use

The screen's conclusion stands, and now stands on a test that would have found
the thing it was accused of missing: **no traded pair in this universe has a
relationship worth trading, episodic or constant.**

Report it with its scope. The single-`t` screen answers *time-invariant
cointegration* and has no power past 80% tied - say so rather than letting
"0 of 190" carry a claim it cannot support. The windowed form is the one to
reach for whenever a relationship is expected to come and go, which is the only
assumption consistent with carrying the ratio as a state.

**And keep the planted arm.** It is what turns "this test might be blind" from
an objection into a number, and it cost one function.

## Related

* [The relationship screen](statespace-relationship-screen.md) - the single-`t`
  form, the live-ratio defect, and the block-shuffled null this reuses
* [The hierarchical prior](statespace-hierarchical-prior.md) - the other half of
  the stat-arb import, also a null
