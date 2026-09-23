# What else improves the break model: three from inside, four nulls from outside

Run: `python research/harness/break_features.py`

**Measured 2026-09-23.** The desk asked what other features could improve the break and levels
models. Seven candidates were tested. **The three that worked were already in the feature set and
being ignored; all four that would have needed something new are null.**

| candidate | AUC on break | verdict |
| --- | ---: | --- |
| `experience` | **0.6272** | **added** - was excluded on a band-conditioned reading |
| `conviction` = \|`up_rate` − 0.5\| | **0.6006** | **added** - resolves a two-document contradiction |
| `strength` | **0.6076** | **added** - same band artefact as `experience` |
| `chi` (Ising susceptibility) | 0.5259 | null - +1.4% lift inside experience quintiles |
| dollar factor return | 0.5075 | null |
| trailing semivariance asymmetry | 0.5103 | null |
| release proximity | no ordering | null |

## The three that were already there

`Breaks` fitted six inputs: `approach_vol`, `depth_vol`, `slowing`, `slope`, `prior_slope`,
`interval_log`. It now fits nine.

**`experience` and `strength`** were excluded because `force.md` measured them inside the
300-1,800s horizon band, where they lean the *wrong* way - stronger and better-tested levels
breaking more, at AUC 0.54, recorded there as "likely a confound rather than a finding".

On the unconditional population the sign reverses and they are the two best single features in the
set. The band keeps only resolutions lasting five minutes or more and the median 1m touch resolves
in **120 seconds**, so it discards most of the population and discards it non-randomly - the slow
touches are the ones that break. **The features were never the confound; the conditioning was.**

`experience` is monotone across all five quintiles - 15.0%, 12.1%, 11.3%, 8.8%, **2.9%** - a
fivefold spread over 320,811 touches.

### `conviction`, and the shape a linear model cannot see

`up_rate` is the level's record of which way its same-side touches went. `breaking.py` excluded it
on a measured **AUC 0.4892** - nothing - and that measurement is correct. Re-run on 293,252 journal
touches it comes out at **0.5005**, which confirms the exclusion exactly.

But `|up_rate − 0.5|` scores **0.6006**.

The record's *direction* says nothing about breaking. Its **conviction** says a great deal, and a
linear model cannot represent `|x − 0.5|` from `x` - so the feature was dropped for a property of
the model rather than a property of the feature. This is the same failure mode `breaking.py`
already documents for the slope sign, *"the one shape it cannot represent"*, arriving a second time.

Hold rate rises monotonically with conviction: **83.8%, 88.2%, 92.0%, 92.8%**.

**And it is not a restatement of `experience`**, despite correlating +0.573 with it:

| | conv q1 | conv q2 | conv q3 |
| --- | ---: | ---: | ---: |
| exp q1 | 15.5% | 18.0% | 11.2% |
| exp q2 | 18.4% | 15.1% | 10.2% |
| exp q3 | 17.2% | 13.1% | 7.5% |
| exp q4 | 17.9% | 8.9% | **3.1%** |

Conviction separates inside every experience quartile, the effect **strengthens** with experience -
4.3 points at the bottom, 14.8 at the top - and the joint span is **3.1% against 18.4%**, sixfold,
which neither reaches alone.

### It also settles a standing contradiction

`strength.md` measured the same-side record separating hold from break by **+32.8 points**.
`breaking.py` had the same quantity at AUC 0.4892 and excluded it. Both are right: the record
separates, its direction does not, and the disagreement was about **which reading of one feature
was being scored**.

A second correction came out of the same check. `signal-registry.md` originally excluded
`strength.md`'s +32.8 as "measured with a broken denominator". That was backwards - **+32.8 is the
corrected figure** and +15.6 was the pre-fix one. What the denominator fix *weakens* is everything
else on that page: `Level.strength` from +12.2 to +6.1, `experience` from +14.9 to +5.8, the
instrument spread from 19.0 points to 7.0, and the origin ordering inverts.

## The four nulls

Joined to 28,675 touches carrying a feed with local hourly bars, 9.5% of them breaks, each taken
from the bar **at or before** the touch - the whole feature set is frozen when a touch opens, so a
candidate needing a later bar is not a candidate.

| feature | AUC | best read | lift in experience quintiles |
| --- | ---: | ---: | ---: |
| `chi` | 0.5259 | 0.5259 | +1.4% |
| trailing asymmetry | 0.4897 | 0.5103 | +0.4% |
| trailing return | 0.5007 | 0.5007 | +0.7% |
| dollar factor | 0.5075 | 0.5075 | +0.8% |
| `experience` (reference) | 0.4134 | **0.5866** | — |

The lift column is the bar, not the AUC: with nine inputs already fitted, a candidate has to
separate *inside* quintiles of the strongest incumbent to be adding anything. None does.

`chi` is the only one showing a pulse at all, and `susceptibility.md` already says what it is - a
forecast that **volatility will fall**, not a statement about levels. A +1.4% lift does not earn a
tenth input.

### The calendar says nothing about breaks

Break rate by minutes to the nearest important release, on 23,391 touches within reach:

| minutes away | n | break rate |
| --- | ---: | ---: |
| 0-15 | 1,982 | 7.9% |
| 15-30 | 1,739 | 9.4% |
| 30-60 | 3,003 | 9.3% |
| 60-120 | 5,570 | 8.5% |
| 120-240 | 11,097 | 8.4% |
| all | 23,391 | **8.6%** |

No ordering, and the closest bucket is the *lowest*. So the calendar moves **volatility** - 0.79x
before a print and 2.42x on it, `news-volatility.md` - and does not move the probability that a
level gives way. Those are different questions and this is the evidence that they are, which is
the same lesson `breaking.py` opens with about direction and breaking.

## The clock, and where it is used

The largest effect measured this session is `P(break | still open at t)`, running 14.4% to 77.8%
and crossing even money at four to seven bars of the level's own timeframe. **It is not in
`Breaks` and cannot be**: the model's inputs come from `Features`, built once when the touch opens
and never mutated - deliberately, because a feature that changes under a model is how look-ahead
gets in.

Two ways of using it were written. **Only the second is in the production path**, and the reason
is in the fix section below.

`registry.aged()` combines the clock with a fitted probability in log-odds:

    logit(out) = logit(model) + logit(clock at t) − logit(clock at 0)

The final subtraction does the work - a fresh touch gets its model probability back unchanged, and
the clock only contributes what it has learned *since*. From a 20% prior it reads 0.28 at one bar,
0.42 at two, 0.70 at five, 0.95 at twenty. It is implemented and tested, and it is **not** what the
gate uses: adding log-odds assumes the two estimates are conditionally independent, and they are not.

`registry.clock_odds()` is the hazard on its own, and that is what the fix applies - as a floor.

**Two consumers exist and both are load-bearing:**

* the engine's per-quote carry loop sees every open touch and its age, but runs on every quote for
  every level - a probability recomputed there is a hot path, and the measured rule is a single
  threshold crossing rather than a continuous number, so the right form there is one event per
  touch and not one per quote;
* `max_break_risk` gates orders on `break_probability`, and the live instance has it set at
  **0.35**. But that number is computed when the touch opens and carried on the signal, so a
  **parked signal is gated on a stale probability** - and the clock says staleness is exactly when
  it is most wrong.

The first is still open. **The second is fixed** - below.

## The parked-signal fix

`Trader._age_break_risk`, called from `_arrived`, which is the one place a signal's age is known at
decision time. `Settings.age_break_risk`, on by default, `TRADING_AGE_BREAK_RISK=0` to disable.

`_arrived` already had the precedent and states the principle: it sets `after_pullback = 1.0` on
wake because *"the same momentum reading means 'arriving at the level' before the wait and 'the
fall has not finished' after it."* A stale break probability is the same thing with money on it.

### A floor, not a compounded estimate

The first version added the clock to the model in log-odds. **That was wrong**: log-odds addition
assumes the two estimates are conditionally independent, and they are not - both describe the same
touch. It took a 20% prior to **87%** after ten bars, and since `pullback_bars` is 10.0 it would
have refused essentially every parked entry.

The clock is applied as a **lower bound** instead. The gate may not see a break risk below what
elapsed time alone implies, and nothing is multiplied by anything:

| wait, in bars of the level's own timeframe | at open | after | against a 0.35 ceiling |
| ---: | ---: | ---: | --- |
| 0 | 0.20 | 0.200 | passes |
| 1 | 0.20 | 0.200 | passes |
| 2 | 0.20 | 0.279 | passes |
| 3 | 0.20 | **0.385** | **refused** |
| 5 | 0.20 | 0.560 | refused |
| 10 | 0.20 | 0.787 | refused |

A model already more worried than the clock keeps its own number, and the correction is
one-directional by construction - a gate that loosens while a setup ages is the failure this exists
to prevent.

### The effect is large, and that is the finding rather than a side effect

Against the live 0.35 ceiling this refuses a parked entry once the wait passes about **three** bars,
and the window is ten. **So the ceiling itself now wants re-tuning**, because 0.35 was chosen while
the input was stale - the gate was calibrated against a number that understated the risk it was
gating on.

It only bites where `max_break_risk` is set, since nothing else reads the value.

### One extrapolation, stated

The hazard was measured over **all** touches by elapsed time. A parked signal is a *selected*
subpopulation - price came back to a trigger - and that conditioning is not what the table measured.
The floor is the conservative reading of an estimate that does not strictly apply.

Which is why the original is kept as `break_probability_at_open`, beside `break_age_bars`: the
journal now carries both, so whether the correction was right becomes a query over live fills
rather than an argument.
