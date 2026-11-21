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
