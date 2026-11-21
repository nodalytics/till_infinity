# Roles: the thing this desk already does twice, named once

**Asked for on 2026-11-21.** The operator, arriving at it from zones: *"there
should be a story from the higher timeframe to the lower timeframe... we can add
more roles... same thing for our rules, and even models, we should have the
concept of roles even in statespace too."*

## It already exists, under two vocabularies

**In `strategies/`.** A concrete desk is three things composed, and `exits.py`
says so in as many words: *"a mixin with no base, composed in front of an
entry, exactly the way a decision mixin is composed in front of one."*

    class SurpriseEdge(Surprise, ManagedExit, EdgeEntry): ...
                       \______/  \_________/  \________/
                       decision     exit        entry

`surprise.py` draws the same line from the other side: *"it answers one
question - is this proposal worth trading, and where do the stop and target go
- and nothing else."* The decision does not know how it will be placed; the
entry does not know what it is placing.

**In `statespace/`.** The architecture rule is a role split too: *every member
and component forecasts dispersion, only the Monte Carlo emits a price, and
that price is paired with the signal rather than merged into it.*

So the idea is not new here. What is new is **naming it once and extending it**,
because two of the roles the operator describes do not exist in either package.

## The roles that exist

| role | where | what it answers |
|---|---|---|
| **decision** | a rule mixin - `Surprise`, `Structure`, `Zones`, `Identity`, `VolImpulse` | is this worth trading, and where do the stop and target go |
| **entry** | `entries.py` - `EdgeEntry`, `RestingEntry`, `ArrivalEntry` | how the order reaches the venue |
| **exit** | `exits.py` - `ManagedExit` and its leaves | what happens after the trade is on |
| **dispersion** | every statespace member | how far can price get, how often, how soon |
| **price** | `projecting.py` alone | the distribution over forward paths |

A sixth is half-built: `projecting.py` can already answer *how far, how
often, how soon*, which is what a **gauge** needs. See below.

## The roles that do not

**`context` - where, and what is happening there.** This is the operator's
story: *"on 4h it could be in a bos, choch, or zone or any key level or area,
then in 1h, it could be reacting there by slowing momentum or increasing it."*
A decision mixin today sees **its own feed at its own interval** and nothing
else. There is no way for a rule to say "I act only where a slower frame says
something, and only when a middle frame reacts to it".

Two sub-roles, because they are different questions and the evidence for them
differs:

* **location**, from the slowest frame: a zone, a break of structure, a change
  of character, a key level. Any of them, not all of them.
* **reaction**, from the middle frame: momentum slowing or accelerating at that
  location.

**`gauge` - how strong a signal is, in units that mean something.** The
operator: *"projecting can also be used for deviation rate... know gauge how
strong a signal is."*

A `Signal.strength` today is a scalar in -1..+1 and **nothing says what it is
worth**. `projecting.py` can answer that, because it already measures the
quantity a strength should be compared against: *how far can price get, how
often, and how soon*. The accessors exist - `Projection.above(level)`,
`touches(level)`, `when(level, coverage)`, `worth(cost, multiple)` - and `Trade`
already prints the comparison that matters: `win_rate` beside `geometric`, the
`1 / (1 + reward)` a driftless market owes, *"their difference is the only
quantity that can be an edge"*.

So a gauge role would express a signal's claim as **a position in the projected
distribution**: a target inside the projected band is claiming nothing beyond
diffusion, and one far outside is claiming a great deal and is correspondingly
unlikely. The deviation rate is exactly the denominator for that.

**What this can and cannot buy, stated before anyone builds it.** It cannot
improve ranking: `only-the-sign-survives-into-a-weighted-sum` records that
activation, scale and per-term offset are all rank identities and that 0..1
against -1..+1 is empty, so a monotone re-expression of strength reorders
nothing and no AUC will move.

What it buys is **a portable threshold**. A strength of 0.6 means nothing across
instruments; "the target sits at the 0.93 coverage edge of the projection"
means the same thing on EURUSD at 15m and on gold at 4h, which is what lets one
number be set once instead of per desk. And the coverage is calibrated to say
it: `band-coverage.md` measured the composition holding **1.02 to 1.10** across
0.95 to 0.999 where a Gaussian band of the same nominal width degrades to
**14.80**.

The one trap is the horizon. A projection read at one day on a 2R target
forecasts the **stop** rather than the trade -
[`race-calibration.md`](../../research/docs/race-calibration.md) measured it:
7.5% at one day climbing to 33.3% at seven, where the geometry owes 33.3%. So a
gauge has to state its horizon, and `projecting.PERIODS` already insists a
horizon is a duration and never a count of bars.

**`forget` - how fast to discount.** `research/docs/edge-life.md` measures log
volatility at rho 0.9963 to 0.9995, half-lives of 185 to 1,253 hours and 7x
apart across five feeds, while the edge's own half-life cannot be told from
infinity. So "how fast to forget" is estimable per feed and is nobody's job
today.

**`regime` - which description is in force.** statespace members all compete at
the same job: describe the series, scored against a random-walk null in
`statespace-measured.md`. None of them is a specialist. `reverting` is the only
member that beats the walk, which under a role framing is a finding about *one
role* rather than a verdict on the bench.

## The two hazards, both already measured here

**A role must not become a veto.** `reactive-zones.md` measured confluence as a
vote and it died of arithmetic:

| rung | n | share |
|---|---:|---:|
| pattern | 271 | 100% |
| + quiet | 106 | 39.1% |
| + TSI slow | 17 | 6.3% |
| + TSI both frames | **1** | 0.4% |
| + a rejection candle | **0** | 0% |

*"A conjunction of independent-ish gates multiplies its way out of existence
long before it runs out of edge."* The operator's own clarification is the fix -
*"it does not need to agree exactly"* - which turns an agreement into a
**distance**, and a distance has a tolerance that can be swept. Every role that
conditions another must be a distance, a band or a strength, never a boolean
that has to line up.

**A role must earn its place marginally.**
`the-book-is-composable-judge-rules-marginally`: a rule must add to the book,
and composition buys variance and conditioning, **never expectancy**. So the
test for a new role is not "does the composed rule make money" - it is "does
the composed rule beat the same rule without this role, on the same entries".
`reproduce-the-baseline-before-an-increment` is the procedure.

## What the evidence already says about the 4h-to-15m story

`bjorgum.md` measured the same zones at three frames and they are **not
interchangeable**:

| | 15m | 1h | 4h |
|---|---:|---:|---:|
| never-flipped effect | **+23.6** | +12.3 | +5.0 |
| *its control* | *+0.9* | ***+5.6*** | *0.0* |

15m is clean. **4h is clean on 481 visits.** 1h is the frame where half the
effect sits in the control - which is an argument for giving 1h the
**reaction** role rather than the location one, since the location evidence
there is the weak evidence. It also found the best cell on the book at 4h: a
zone with three to five prior visits breaks 25.3% against a 37.3% base.

## The fourth formulation in this family, and what the first three already cost

**This is not the first multi-structural design here.**
[`2026-11-13-multi-structural-confluence-blueprint.md`](2026-11-13-multi-structural-confluence-blueprint.md)
is the third, and it opens by closing the first two in
[`dual-engine-confluence.md`](../../research/docs/dual-engine-confluence.md):

* **v1** - volatility z-score exhaustion plus a choppy-cluster breakout:
  **-0.210R on n 906**, against its own flip at -0.219R, a gap of **+0.009**.
* **v2** - the same geometry with a softmax price z-score: **+0.162R on n 48**
  over 464 days, then **-0.127R on n 356** over 3,111 days. The expectancy went
  positive to negative on 7.4 times the span.

So the structural half of this family has been measured three times and has
never cleared its own flip. A role framing does not change that and must not be
read as changing it.

### And the exit stack is a measured tax of 0.2R a trade

The finding that matters most to the zones question is not about structure at
all. `dual-engine-confluence.md`, on break-even at 1R, half off after it, an
ATR trail and a time stop:

> A direction-free entry with a symmetric stop and target should read about
> minus the cost. It reads **twenty-five times** the cost, and both arms read
> it. The break-even stop and the partial cut the right tail while the full stop
> stays on the left... **Any entry with no directional information, run through
> this exit stack, loses roughly 0.2R a trade** on these instruments - and that
> is a number to check the next management proposal against rather than a story
> about one algorithm.

**The live desk is running that stack.** `TRADING_BREAK_EVEN_AT=1.0`,
`TRADING_SCALE_OUT_AT=1.0` at a 0.5 fraction, `TRADING_TRAIL_VOL=2.0`, and
until 2026-11-21 a twenty-minute stale clock in the time stop's role.

And the shape it predicts is the shape zones has. Over 14 days, 80 positions:
**median win +1.96 against a median loss -4.62** - the right tail cut and the
left intact, which is what "break-even plus a partial" does to a distribution
by construction. Zones' deficit excluding the stale exits is about **0.32R a
position**, and the exit stack's measured tax is **0.2R**. They are the same
order of magnitude.

**So the first thing to try on zones is not a new role.** It is the four-way
break-even x trail comparison `manage.py` has been asking for since it was
written - two environment variables, no code, now possible for the first time
because managed exits only started completing on 2026-11-20. A conditioning
role that bought 0.1R would be undone by an exit stack that costs 0.2R, and
`reproduce-the-baseline-before-an-increment` says which order those go in.

## The order to do it in

0. **The exit stack first**, per the section above: the four-way comparison
   costs two environment variables and the prior measurement says it is worth
   more than anything below it.
1. **The retention measurement, before any code.** What share of 15m entries
   sit within a tolerance of a 4h location? `research/ideas/zone_story.py`
   sweeps it at 0, 0.25, 0.5, 1, 2 and 4 ATR with a shuffled and a
   distance-matched placebo arm. A tolerance that retains 6% is the vote again
   under a different name, and the answer is no.
2. **`location` as a published reading, not a gate.** The slow frame publishes
   *distance to the nearest location* and the decision reads it as a number. A
   number can be swept, conditioned on and refuted; a boolean can only be
   obeyed.
3. **`reaction` as the second reading**, from the middle frame, once location
   retains a sample worth measuring.
4. **Roles in statespace last**, because it is the biggest change and the
   cheapest version is a relabelling: say which role each member is competing
   for in `family.PENDING`, and let the dispersion and regime roles be scored
   separately rather than against one pooled null.

## Roles can change, and that is where this gets hard

The operator, same day: *"roles can change."* So the assignment is not a wiring
diagram - 4h is not permanently the location and 1h not permanently the
reaction. A frame, a rule or a member can play a different role at a different
time, which is the same premise the statespace work runs on: *"we are not using
statespace to trade these signals long term, that is why it is adapting."*

**That turns role assignment into a decision, and a decision can be scored.**
It also drags in the one problem this desk has the most evidence about, so the
evidence has to come first.

### What is not estimable: switching on performance

* `strategy-rotation-is-not-timeable` - **every pause rule tested matched
  random pausing at the same duty cycle.** A role assignment that reads "this
  frame has been the better location lately, promote it" is a rotation rule,
  and rotation rules on this desk have never beaten the coin that switches at
  the same rate.
* `research/docs/edge-life.md` - the decay estimator is **blind**: planted
  half-lives of 10, 50, 200, 1,000 and **infinity** all come back as 3.5 to 4.6
  trades. So *when* a role has stopped working is precisely the quantity that
  cannot be measured, and a switching rule needs exactly that quantity.

Put together: **a role assignment driven by recent performance is
unmeasurable**, and would be indistinguishable from switching at random.

### What is estimable: switching on an observable state

* Log volatility has `rho` **0.9963 to 0.9995** with half-lives of **185 to
  1,253 hours**, 7x apart across five feeds. That is a state that can be read
  now and will still be true in an hour.
* `seasonality-belongs-on-q`, `relationships-are-contemporaneous` and
  `drive-q-from-the-range` all put the structure in volatility rather than in
  return, contemporaneously rather than at a lag.

So a role assignment conditioned on **a volatility regime** is a measurable
proposition, and one conditioned on **which role made money last week** is not.
That is the whole of the design guidance here.

### The ordering is free too, and that has a size

The operator, pressing it further: *"4h can be or structure today and entry
tomorrow and 1h same etc."* So the frame-to-role mapping is itself free - a slow
frame can supply the entry and a fast one the location. Coherent: a 4h entry is
what a swing desk does.

**Which frames can hold which roles is arithmetic, and it is not symmetric.**
EURUSD, two years of 5m folded, with Bjorgum's pivot rate near 2.5% and three
visits a zone:

| frame | bars | zones | visits | **pooled, 5 symbols** |
|---|---:|---:|---:|---:|
| 15m | 49,677 | 1,242 | 3,726 | **18,629** |
| 1h | 12,419 | 310 | 931 | **4,657** |
| **4h** | 3,104 | 78 | 233 | **1,164** |
| 1d | 517 | 13 | 39 | **194** |

* **4h can be the entry frame and still be measured** - 1,164 pooled against
  the 350 to 800 `Trade.trials` requires.
* **1d cannot.** 194 pooled is under the floor, so a daily entry role is
  unfalsifiable on the history that exists and must not be built.
* 4h clears **pooled only**. Per symbol it is 233, and
  `pooled-medians-invert-subgroups` records a pooled answer disagreeing with
  every subgroup - so a 4h entry role is judgeable across the book and never
  for one instrument. `pool-events-before-a-per-feed-guard` is the other side
  of that: a min-events guard once dropped 141 of 146 feeds and made 0.9 sigma
  read as 4.8.

**And a free ordering is a grid.** Four frames into three distinct roles is
**24 assignments**. That is small next to the one this desk has a scar from -
`rsi-ma-momentum.md` ran **414 cells** whose seven-day leaders had **0 of the
top 10 positive in the following month**, and a day-shuffled market's best cell
beat the real market's best. 24 is defensible where 414 was not, but it carries
the same requirement: **the real best is compared to the shuffled best, never
to zero.**

If the assignment then rotates, the space multiplies by the switching schedule
and the 414-cell failure returns with a time dimension on it. Which is the same
conclusion as the section above, arrived at from the size rather than from the
estimator: rotate on a state, not on a score.

### Detect-and-redeploy, and the arithmetic that stops it

The operator states the goal plainly: *"the edge that works now might not be
the edge that work in the next window, so our system can detect when edge is
not working and deploy another one."*

**The intent is right and the detection step is the one thing measured here as
unmeasurable.** Two findings, independent of each other:

* `research/docs/edge-life.md` - the decay estimator is **blind**. Planted
  half-lives of 10, 50, 200, 1,000 and **infinity** all come back as **3.5 to
  4.6 trades**, with half the draws reading "static" regardless. A hundred-fold
  change in the truth moves the answer by one trade.
* `strategy-rotation-is-not-timeable` - **every pause rule tested matched
  random pausing at the same duty cycle.**

And the operator's own window definition prices it. Telling a win rate from its
geometric baseline needs **350 to 800 trades** (`Trade.trials`). Telling win
rate A from win rate B - which is what *detecting a change* means - needs
roughly two to four times that: **1,500 to 3,000**. At about a dozen trades a
day that is **18 to 36 weeks**.

> **An edge cannot be detected as stopping inside the window in which it
> stopped.** By the time the sample exists the window is four to eight months
> gone, and a detector built on the edge's own P&L fires on noise.

### Three ways to keep the intent without the detector

1. **Condition on a state, not a score.** Volatility regime is readable now and
   persists - `rho` 0.9963 to 0.9995, half-life 185 to 1,253 hours. If rules
   suit regimes, read the regime. Same adaptation, estimable input, no
   detection latency.
2. **Run them all and let the state set the sizes.** Instead of
   detect-then-switch, hold every rule and have the regime weight them. This is
   the continuous version of the same idea, it needs no switching decision, and
   it sidesteps the 24-assignment grid entirely. `sizing-is-reduction-only`
   already makes every scaler a reduction, so a weighting cannot enlarge a
   position by accident.
3. **Detect breaks, not fades.** "The edge faded" needs a thousand trades;
   "something is broken" is **one event** - a venue fault, a desk that cannot
   fill, a gate refusing everything.
   `venue-faults-hide-below-the-strategy` exists because a rule that never
   fires and a rule that *cannot* fire read identically, and
   `half-the-desks-can-never-trade` is what that cost. That detector is worth
   building and is a different object from a decay detector.

### The chosen shape: regimes plus the Monte Carlo

The operator: *"we can still make it work, detect breaks too and regimes too,
regimes can be how we would handle it, regimes + monte carlo."*

**This replaces the question rather than answering it.** The unanswerable
question is *"has this edge stopped working"*, which needs 1,500 to 3,000
trades. The answerable one is *"what is this geometry worth in the regime that
is in force now"* - and `projecting.py` already computes it.

The loop, with every input estimable:

1. **Read the regime.** Log volatility, `rho` 0.9963 to 0.9995, half-life 185
   to 1,253 hours. Readable now, still true in an hour, 7x apart across feeds
   so it is per-instrument for free.
2. **Feed it to the projection.** `project(..., scales=...)` is already the
   per-step dispersion arm, and its docstring says so: *"this is the arm the
   members are being pointed at dispersion to feed."*
3. **Read what each rule's geometry is worth there.** `Trade` already prints
   `win_rate` beside `geometric`, plus `edge_needed`, `cover` and `trials`. A
   geometry whose `cover` is under the gate has no trade in this regime
   whatever its signal says.
4. **Size by that, not by recent P&L.** No detector, no switching decision, no
   latency - the regime changes, the projection changes, the implied value of
   each geometry changes, the sizes follow. `sizing-is-reduction-only` means a
   weighting can only ever reduce.

**What it can and cannot tell you, which is the whole discipline of it.** The
projection is **driftless by default** - *"that default is the measurement and
not a placeholder"* - so its win rate sits on the geometric. It therefore
answers **"is this geometry tradeable in this regime"**: the cost in R, the time
to the target, the share of paths that resolve at all. It does **not** answer
"does this rule have direction here", and reading it as though it did is the
mistake `a-martingale-cannot-pay` records.

Given `direction-is-closed-not-just-null` - the gate earns 2% of a spread
against a planted drift - geometry and cost are what is left to optimise, so
this is the right target rather than a consolation.

**And there is one directional quantity it does yield.**
[`race-calibration.md`](../../research/docs/race-calibration.md) establishes
that `projected - realised` **is realised drift**, because the simulator
assumes none. So *per regime*, that gap is a measurable directional residual
with its control built in - and it tracked the long/short bias cell by cell on
the first sample it was run on.

**The sample arithmetic works, for the first time in this document.** Regimes
partition rather than intersect, so three regimes over the operator's one-year
maximum - about 4,000 trades - give roughly **1,300 each**, which clears the
350 to 800 floor. Over 7 days it gives 28 a regime and clears nothing, which is
the same conclusion as everywhere else here: **act on a week, judge on a
quarter, bound at a year.**

### The control a rotating assignment must beat

`a-control-is-only-for-a-named-property`: the control has to rotate the same
way. The named property is **the switching**, so the arm to beat is a
**placebo assignment that switches at the same duty cycle** - the protocol
`strategy-rotation-is-not-timeable` was written from. An adaptive assignment
that beats a static one but not a random one at the same rate has measured its
own switching frequency and nothing else.

**And the horizon has to be stated before the run**, because a rotating
assignment has a free parameter - how often - that can be fitted after the
fact. `research/docs/edge-life.md` puts the sample a win rate needs at 350 to
800 trades; a rule that switches weekly over a fortnight has made two choices
and cannot be judged at all.

## What this is not

It is not a new rule, and it must not become one. Every role above is a way of
**conditioning** a decision that already exists and is already measured. The
desk has 89 registered strategies, three of which traded last week, and the
record of adding primitives is `smc-primitives-overlap-and-are-closed` and
`topology-restates-volatility` - levels, ranges and shapes all null
individually. The claim here is about composition, which is the one thing those
studies did not test.
