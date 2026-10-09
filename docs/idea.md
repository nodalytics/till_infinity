# The idea

> **The thesis, in one line.** We price the market and take a stance relative
> to where that price lands: fair value above the market is a long, below it is
> a short, and the distance between them is what the trade is worth. No
> direction is forecast - the side is arithmetic once the valuation exists. The
> README's opening is the short version; this document is the reasoning behind
> each choice.

## First, what a valuation is not

The clearest illustration is not one of ours. VWAP - the price at which the
day's volume actually changed hands - is as good an estimate of fair value as
this market produces, and it is the one large institutions are measured
against. They use it for two things: to know what the day's price was, and to
place a large order without moving the market against themselves. Both are
uses of a **measurement**.

Turn the same number into a rule - buy below it, sell above it, no volume
confirmation, no risk management - and it draws down heavily. Nothing about the
estimate got worse. What changed is that a statement about where value is was
asked to answer a different question: whether to take this trade, at this size,
right now, and where to be wrong. Those are not properties of the valuation,
and no amount of improving the valuation supplies them.

That gap is why this project is shaped the way it is, and why the shape looks
slow from outside. A level is published before anything is allowed to trade it.
Features are published and read by nothing until the record says whether they
predict. Every model scores itself against the control that would beat it - the
base rate, the constant, the coin - so the question "is this better than nothing"
is answered in the same breath as "what does this say". A number that has not
been through that is an opinion, however well it is computed.

**So the valuation is the input and never the trade.** What makes it a trade is
everything that comes after: whether the distance is worth the cost of crossing
the spread, whether the stop has structure to lean on, how big the position is
against a loss limit that resets on a clock rather than on a feeling, and what
happens when the thesis is right and slow. Those are the parts that fail
quietly, so those are the parts kept in the record.

The corollary is the uncomfortable half. It means most of what is built here
will earn nothing, and that has to be discoverable rather than argued about -
which is what [research/inert.md](../research/docs/inert.md) is: a list of things
computed correctly and read by nothing, kept because a fix that ships and
changes no number is the failure mode this desk is most prone to.

Which leaves the question that has to be answered before any of that machinery
means anything: **what is the valuation?**

## The valuation, and why the turn is a consequence of it rather than a definition

Price does not stop at a level because the line is special. It stops because
enough of the market agrees, for now, that the instrument is worth about that
much. Reading it the other way round - a level is "where price turned" - makes
it a shape that either repeats or does not, and there is nothing to be wrong
about. Reading it as a claim about **value** makes it falsifiable: the level is
an estimate, each touch is an observation of it, and it can be revised or
abandoned.

That is why the origin is a **latent state in a state-space model** rather than
a line. The model is not decoration; it is what it means to hold an estimate of
a quantity you cannot observe directly and keep updating it from noisy
evidence.

**State space is the thesis; a Kalman filter is one way to do it.** The family
is larger, and which member fits depends on what the state has to express:

| | what it buys |
| --- | --- |
| **Kalman filter** | linear, Gaussian, exact and cheap |
| **particle filter** | arbitrary distributions, non-linear dynamics |
| **hidden Markov model** | a state that is a regime rather than a number |
| **random finite set** (PHD/CPHD) | an unknown and changing *number* of states |
| **Dirichlet-process mixture** | the same, posed as clustering |

**Listed as a family rather than a verdict.** Some of these have been tried
here on one particular state and the results are in `research/docs/`; none of
that settles what a different member would do on a different state, and a table
that reads as a scoreboard would close off the thinking this is meant to open.
Which member fits is a question asked per state, not once.

**What the model outputs is a level, and a level is not necessarily a price.**
It is an estimate with a width: sometimes a point, when the filter is confident
enough that the band is narrower than the tick grid, and more often a **range**
- what this desk calls a *zone*. The point and the zone are the same object at
different confidences, which is why they come out of one model rather than two:
the mean says where, the variance says how wide, and the zone is what a
consumer actually trades against.

**Only where the level sits is held that way, and that is an incomplete
reading of this paragraph rather than a decision.** Whether a level is there at
all, and how many there are, are quantities nobody can observe directly either;
today they are settled geometrically before the filter sees anything. See
[`levels.md`](levels.md) §3 and the design that states the correction,
[`2026-10-09-levels-in-one-state-space-design.md`](specs/2026-10-09-levels-in-one-state-space-design.md).

**The kinship is volume profile**, and the difference is the input. A point of
control is fair value derived from *where volume traded*. This is fair value
derived from **where volatility turned** - the leg in and the leg out meeting
at a price - which needs nothing but bars, works on any instrument, and does
not depend on a venue willing to sell its tape. Where both can be computed they
are asking the same question with different evidence.

### And *when the slope turned*, which is the same event seen in time

"Where volatility turned" locates the level on the price axis. It is only half
of what the turn is, because a turn is also an event in **time**: the level was
drifting one way, and from some moment it was not.

That second half is a state in its own right and the model holds it. The level's
drift is `slope`, in price units per hour, and the moment it reverses is
`crossed`; the moment it begins decaying against its own direction is
`turning`. A level that trended up for a week and has started to flatten is a
different object from one that has been flat throughout, and the price axis
alone cannot tell them apart - both are "a price where volatility turned".

**And the slope has its own volatility.** Price has a volatility because price
is noisy; so is the drift, and for the same reason. The filter carries it as
`var_slope`, grows it with elapsed time, and gates every use of the slope on
it - `trending` asks whether the slope is large against *its own* dispersion
rather than against zero, which is what stops three scattered touches being
read as a trend.

So the valuation is two estimates with two dispersions, not one price with one
band:

| | estimate | its own volatility |
| --- | --- | --- |
| **where** the level is | `mean` | `variance` - and this is the zone |
| **which way** it is going | `slope` | `var_slope` - and this is what `trending` tests against |

The symmetry is not decoration. Every argument this document makes for holding
a price as a latent state with a width applies unchanged to holding its drift
that way, and the second one was the part left implicit.

One honesty note, because this is the half that is still assumed rather than
measured: the slope's volatility is currently set as a fixed share of the
price's - a tenth, in `SLOPE_DRIFT_SHARE` - on the judgement that a level's
direction should wander more slowly than its position. That ratio is chosen,
not fitted, and the observation noise beside it was chosen too until it was
measured at 0.40 and found 25% too wide. See **I10** in
[`2026-10-09-levels-in-one-state-space-design.md`](specs/2026-10-09-levels-in-one-state-space-design.md).

## What "fair value" means here, and what it rests on

The phrase is doing a lot of work, so it is worth saying exactly what is being
claimed and what is not.

**Fair value here is a price at which the marginal buyer and the marginal
seller both decline to act.** Not a valuation in the accounting sense, not an
estimate of what the thing is worth to hold forever. It is the price where
disagreement runs out. Above it, someone would rather sell than own; below it,
someone would rather own than sell; at it, neither has a reason to move, and
price stops for a while.

### Which means it is found at the start of a move, not at the end of one

That definition is a description. The thing that makes it usable is knowing
where to look, and the answer is the part worth stating plainly, because
everything else here is downstream of it:

> **A sustained move is evidence that agreement broke. The price it broke from
> was the last one anybody agreed on. That price is the estimate.**

Price rising for eight hours is not eight hours of information about where value
is - it is eight hours of demand exceeding supply, which is a statement that the
market had the price wrong when the move began. The run is the *proof* of
mispricing, and the interesting quantity is not how far it went but what it left
from. Everything above the start was the market discovering that the start was
too cheap.

So the estimate is not extracted from the move. It is the point the move
**departed from**, and the move is only the evidence that the point mattered.
This is why an origin is the last extreme *before* an impulse rather than the
extreme the impulse reached: the far end is where the imbalance exhausted
itself, which is a different event with different people behind it.

It also explains what a retest is, which otherwise has to be asserted. Price
coming back to an origin is the market putting the old agreement to the
question a second time - with the difference that the participants now know
what happened last time. That is why statistics are kept **per approach side**:
arriving from the direction the move went is a different question from arriving
from the direction it left, and averaging them describes nobody.

And it is why an untouched origin is worth more than a worked-over one. The
disagreement that stopped price there has never been spent; each retest eats
into it. A level's state is tracked for exactly that reason, and "fresh" is a
claim about how much of the original imbalance is still sitting there.

### Which makes it a sequence rather than a number

The awkward consequence, and it is better faced than smoothed over: if every
sustained move creates an origin, a trending instrument is manufacturing new
fair values continuously, each further along than the last. There is no single
number to converge on.

That is not a flaw in the definition - it is what a market in one direction
actually looks like, and any definition producing a single stable value would
be describing something else. What it forces is a hierarchy: an origin left by
a move that ran for a day is a wider agreement than one left by a move that ran
for twenty minutes, because more participants had to change their minds to
produce it.

Which is where the timeframes come from. They are not a resolution setting;
they are **how large a disagreement had to be before it counted**. A level
several timeframes agree on is one where the small and the large repricing
happened to stop in the same place, and the higher timeframe carries the
significance while the lower one carries the placement - the coarse view knows
which agreements were big, the fine view knows exactly where they were.

Read that way, fair value is **a fact about the participants, not about the
instrument.** It is the current state of a disagreement, which is why it moves,
why it can be wrong, and why it has to be re-estimated from every touch rather
than solved once.

### And leaves open whether anything sits underneath it

For a share there is something: the cash it will produce. For a currency pair
there is less but not nothing - rate differentials, trade flows, a central bank
with an opinion. For a **synthetic index there is nothing at all.** It is a
generated process. No earnings, no underlying, no supply, no story. The number
is produced by a definition, and the definition does not care what anyone
thinks of it.

And levels form on it anyway. They hold, they break, they get retested, and the
per-side statistics behave the way they behave on gold. That is the awkward
fact this project is built on top of, and it points one way: **whatever fair
value is, it cannot require the instrument to be worth something.** If it did,
half the book would produce noise, and it does not.

So the honest position is that there is no floor under the estimate. Fair value
is not discovered, it is *agreed* - and the agreement is made out of nothing
firmer than what the participants did last time they were here. On an
instrument with cash flows the agreement has something to be about; on a
synthetic it has only itself. The machinery cannot tell the two apart and does
not try to, which is a claim rather than an oversight: whatever anchors a price,
its only observable trace is where volatility turned.

That leaves the estimate resting on something circular, and the circularity is
not a defect in the reasoning - it is the mechanism. The level holds because
enough people expect it to hold, and their expectation is legible in the record
of what happened there before. A self-fulfilling belief is still a belief you
can measure, and a measurable belief is tradeable whether or not it is *about*
anything.

### Two measurements keep this from being a story

A claim this loose could absorb any evidence, so it is worth naming what the
data has already said, both ways.

**It is not a magnet.** Across 22,219 bars a level was reached within twenty
bars 44.9% of the time, against 49.5% for an arbitrary price the same distance
away. If fair value were a centre that price was pulled toward, that number
would have come back the other way round. It did not, so it is not - the
distance to a level is an *opportunity*, not a force.

That result is exactly what the definition above predicts, which is worth
noticing because it could have gone the other way. If fair value is the last
price anybody agreed on before a repricing, there is nothing to pull price
back to it: the agreement was *abandoned*, and the market has been operating on
a different one since. What survives is only the record of who was willing to
act there. So an origin should be a place where something informative happens
**if** price returns, and should not make returning any more likely. Which is
what the two numbers say.

**It does have memory.** A level's own record predicts the next turn: the hold
rate on the side price is arriving from separates 59% to 92% across four bands,
an AUC of 0.648. So the thing being estimated is real enough to be estimated
badly or well.

Those two together are the whole position, and they are more restrictive than
they look. Fair value is not somewhere price wants to be. It is somewhere
opinions have changed before, and are more likely to change again. Everything
downstream - the per-side statistics, the base rates, the refusal to forecast -
follows from taking that seriously rather than from preferring it.

### And one would overturn it

If levels on synthetics behaved measurably worse than levels on instruments
with an underlying, once cost and volatility were accounted for, the argument
above would be wrong and fair value would need something real beneath it after
all. That is checkable with what is already stored, and it has not been checked
- `research/catalogue.md` compares what they cost to trade, not what their
levels are worth. It is the most load-bearing untested claim in this document.

## Once there is a valuation the side is arithmetic, which is why nothing here forecasts a direction

That is the estimate. Everything from here is what follows from having one.

The system never answers "which way will price go". It answers "what is this
worth, and where is it trading" - and the side follows arithmetically. That is
a valuation, not a prediction, and it is the constraint the rest of the
architecture exists to protect.

> **Sharpened 2026-09-23.** This section used to say "nothing here forecasts",
> and that has become too strong. Two things now do, and both were reached by
> the discipline described here rather than in spite of it: **whether a level
> gives way**, and **how volatile the next stretch is**. Neither is a direction.
> The constraint was never "forecast nothing" - it was "forecast no direction",
> and the difference is the whole of [what is now forecast](#what-is-now-forecast-and-why-these-two).

The distinction is not word-play. A forecast is scored on whether the future
matched it, and can only be improved by forecasting better. A valuation is
scored on whether the estimate was right about *value*, which is checkable
against what the market subsequently paid, and can be improved by measuring
better. The second is a question this project can actually answer with its own
data; the first is not.

It is also the reason a great deal of received technical wisdom evaporates
under test. Break of structure, liquidity sweeps, premium/discount context -
measured as *direction predictors* they land at a coin flip, in this project
and in others. That is not a failure of the observations. It is a failure of
the question being asked of them. The same observations, read as evidence about
where fair value sits and how firmly it is held, have somewhere to go.

## What is now forecast, and why these two

The valuation fixes the side. Two questions sit on top of it that the valuation
does not answer and the data turns out to support, and it is worth being precise
about why *these* two and not others.

### Whether the level gives way

A level can be perfectly valid and still fail. That is a different question from
which way price goes, and `learning/breaking.py` now fits nine inputs online to
answer it, reaching **AUC 0.658**. The live desk refuses a call whose break risk
exceeds 35%.

The evidence that it is genuinely a separate question rather than direction in
disguise is the level's own record. `up_rate` - which way this side's previous
touches went - is the **strongest direction feature** the project has, at weight
+2.29 against nothing else above 0.22. Asked about breaking it scores **0.5005**
over 293,252 live resolutions: nothing at all. But its *conviction*,
`|up_rate - 0.5|`, scores **0.6006**. One feature, two readings, two different
questions - and only the magnitude answers this one, because a linear model
cannot represent `|x - 0.5|` from `x`.

The largest single effect here costs nothing to observe. `P(break | the touch is
still open at t)` runs from **14.4% at open to 77.8% at ten bars**, and crosses
even money at **four to seven bars of the level's own timeframe** on every
timeframe from 1m to 30m. A thirtyfold span with one parameter: *a level that has
not resolved within about five of its own bars is more likely to break than to
hold.* "Resolution took at least t" and "still open at t" are the same event, so
a table built on finished touches is one a live clock can act on - which is what
separates it from every other conditional in the research folder, all of which
need to know how the touch ended.

### How volatile the next stretch is

This is the half the width already needed, and it has a baseline that is very
hard to beat: a trailing standard deviation. Measured against it, a three-state
Gaussian HMM loses by 3% to 72%, a fifty-neighbour analogue loses on **0 of 20**
window-by-horizon cells, an Ising susceptibility loses by a factor of two to
five, and persistence landscapes lose. The honest summary is that a hundred bars
of arithmetic is the state of the art here.

What does add to it is the one input that needs no model of the future at all:
**a scheduled release time is published days ahead.** Net of the hour of the day
- and that control is the whole study, because 61 of 161 high-importance events
land in the 12:30 UTC hour, which is also the London/New York overlap -
volatility runs **0.79x in the two hours before a print and 2.42x on the print
itself**, decaying through 1.35x at an hour to **0.92x at four hours**, which is
*below* normal. Every interval excludes 1.0 and both halves of the sample agree
at every horizon.

The lull is the part worth having: least obvious, knowable furthest ahead, and a
21% change in a volatility-scaled sizing input.

### And why direction still is not

Not for want of trying, and the failures are specific. Momentum trajectory -
velocity and acceleration of a normalised momentum - prices at **-0.00006** on
the step that adds velocity, out of sample, across four instruments and three
horizons. Similarity twins land at 50.0-50.6%. Sequence models on the synthetics
are provably null. Trend exhaustion does not survive a change of clock, and the
daily result it came from now looks like a volatility proxy.

The pattern across all of them is the same: hit rates between 49% and 51%
against a round trip that costs 4bp. **The two families above work because they
answer a magnitude and a conditional probability rather than a sign**, and those
are the questions this data can answer.

### All of it is scored live against its own claim

Every one of these arrives with the number its backtest promised and is then
scored on **live** resolutions, with ensemble weight coming from the live
separation rather than the claim
([`structures/context/registry.py`](../till_infinity/structures/context/registry.py)).
The reason is this folder's own record: point estimates from backtests decay
here, repeatedly, and nothing was previously arranged to notice. A signal that
stops separating now loses its vote without anyone editing a table.

## Why the width is the part worth modelling at all

There is a reason this section exists before the ones about direction, and it
is the single most useful fact anyone has established about markets.

**Direction is close to unforecastable.** The sign of the next move is
dominated by noise in every liquid market, and whatever edge exists there is
small, unstable and mostly gone once costs are paid.

**Volatility is not.** It clusters - large moves follow large moves, quiet
follows quiet - reliably enough to model, everywhere anyone has looked. That is
a structural property rather than a pattern someone found, which is why the
econometrics for it is textbook material and about sixty lines of code.

So the question a desk asks is not "will it go up" but **"will the next move be
large or small"**, because sizing correctly inside a regime is worth more than
being right about direction. A trader right 48% of the time who sizes with the
regime beats one right 62% of the time who sizes blindly, over any sample long
enough to matter - which is arithmetic about position size, not a claim about
skill.

This system takes that seriously in both directions. The predictable half is
the width, so the width is modelled - GARCH, HAR, range estimators and an
ensemble over them, in `structures/vol/`. The unpredictable half is the sign,
so **nothing here forecasts it**; the sign falls out of where price sits against
structure, which is the argument the rest of this document makes.

And the sizing is not a separate rule bolted on. A stop is expressed in
volatility units, converted to a price distance through `vol_bps`, and the lot
count is that distance inverted against the risk budget - so a wider regime
gives a wider stop and fewer lots automatically. There is no path through this
code that sizes a trade without dividing by a volatility estimate.

`research/clustering.md` sets out what that framing does and does not license,
including the thing it is most often used to excuse: knowing the regime tells
you how big to be, never whether there is anything worth being big about.

## An estimate needs a width, and volatility is the width

*How firmly* is the other half of the estimate, and it is the half that gets
mistaken for a formatting choice.

Everything here is measured in volatility units, and it is easy to read that as
a normalisation convenience. It is not. Fair value is an estimate of a quantity
that cannot be observed directly, and an estimate without a width is not one -
so fair value is a **distribution**, and volatility is its width.

That is what turns a distance into a mispricing. Price five dollars from the
level is not a fact about anything until five dollars has a scale attached; one
volatility unit away is inside the noise of the estimate and says nothing,
three units away is a statement about value. The same five dollars is both,
on different days.

It then does the work three more times:

- **whether to trade at all** - the distance has to clear the noise, and it has
  to clear the spread, which is also quoted against it;
- **where being wrong starts** - the stop sits outside the estimate's width
  rather than at a round number, which is why the zone is the filter's variance
  and not a fixed band;
- **how large the position is** - risk is distance times size, and only one of
  those is a choice.

Get volatility wrong and all three are wrong together, in the same direction,
silently. Which is why it is estimated per instrument *and* per timeframe, and
why the most expensive bug this project has had was a denominator: the estimate
folded the same bar in once per reporting venue, so every distance read two to
four times larger than it was, by a factor that differed per instrument. It
changed which levels existed, which arrivals counted as touches, and which
touches resolved as what - the labels, not just the covariates.

### And because the width is the modellable part, it is the part with models on it

Direction is close to unforecastable and volatility is not - a large move is
followed by large moves, a quiet session by quiet ones - which is why the
argument above puts the whole weight of the system on the width rather than on
the sign. That is also the one quantity here where *forecasting* is the honest
word for what is being attempted, so it has accumulated several attempts at it:

* an exponentially weighted mean absolute return, which is what everything
  divides by;
* a **GARCH** estimate, which adds a long-run level to revert toward;
* **range** estimators - Parkinson, Garman-Klass, Yang-Zhang - which read the
  whole bar rather than its last price;
* a **HAR** regression, which forecasts the next bar from three horizons of its
  own history and is the source of `forecast_ratio`;
* a **learned** model - one online tree over twenty dimensionless features
  shared across the whole book, including the two leading inputs this system
  has (the hour's own volatility share, and quote arrival rate);
* and an **ensemble** scoring all of them against what each bar actually did.

Only the first is used. The rest are published beside it and read by nothing,
which is deliberate: every threshold in the system divides by that one number,
and `research/forecasting.md` records what happened each of the three times a
replacement looked justified. Two of those three were defects that made the
data look clean.

The part of that comparison which has held under every re-run is **the
horizon**: persistence's advantage shrinks monotonically as the horizon
lengthens, so the case for a forecast is strongest exactly where this system
holds trades longest and weakest at the scalp horizon where most of them are.

Whether any model *beats* persistence outright is currently being
re-measured - the comparison was made while two volatility conventions were
mixed asymmetrically, which flattered one competitor and penalised another.
`research/forecasting.md` has it. Either way it is a finding about the *width*
rather than the sign, and it changes how much to size rather than which way to
face.

## What the record supports, and what it has already refused

So much for the argument. The thesis has two halves and they have not fared
equally, and the half that failed is the one most systems are built on.

**Supported.** A level's own record predicts its next turn. Bucketed by hold
rate on the arriving side, resolutions separate 59.4% to 92.2% across four
bands with an AUC of 0.648 - the strongest single signal a level carries, and
the only one that *strengthened* when a volatility-denominator bug was fixed.
See [strength.md](../research/docs/strength.md).

**Not supported.** Price is not drawn to a level. Across 22,219 evaluation bars
a level was reached within twenty bars 44.9% of the time against 49.5% for an
arbitrary price the same distance away; holding the day fixed the gap is
nine-tenths of a point and indistinguishable from zero. See
[magnet.md](magnet.md).

Those two are consistent, and together they say what the edge is and is not.
The evidence lives in **what a level has done at the turn**. The distance is
what that evidence is worth in money - a target chosen because the level is a
place with statistics attached, not because price is pulled toward it. A design
that assumed attraction would be betting on the one part that was tested and
failed.

## Which leaves two ways to trade one estimate

- **React at fair value.** Price arrives, the level's record says what usually
  happens next, and the trade is taken there with the stop beyond it. This is
  `level-scalp` and its variants.
- **Trade the distance to fair value.** Price is somewhere else, and the trade
  is the journey back - sell down to it from above, buy up to it from below.
  This is `approach-scalp`, and it is the one that has to be careful about
  magnet.md: it targets *short* of the level and checks the distance against a
  first-passage model, precisely because attraction is the part that was
  measured and did not survive.

See [trading.md](trading.md) for how each is implemented.

## One estimate, but two bounds - because a trade needs a price to be wrong at

Both ways of trading need the same two things: a price that says the reading
was wrong, and a price that says it was right. Those are not risk-management
settings bolted on afterwards. They are **statements about structure** - where
the wall is below, where the wall is above - and the model that estimates
levels is the thing that should produce them.

So the valuation's output is not a price. It is a pair:

```
barrier_down = (price, sigma)      the wall below, with its own uncertainty
barrier_up   = (price, sigma)      the wall above
p_up_first                          which one gives way first
```

Each bound is a level in its own right - the same latent state, the same mean
and variance - widened on the side a stop must clear by how far wicks actually
run past it there. The asymmetry is the point: how far price overshoots a floor
and how far it undershoots a ceiling are different quantities, measured
separately, and a single symmetric band averages them into something neither
side ever does.

**This does not make them a stop and a target, and the distinction is the same
one this document opened with.** Two bounds with uncertainties are a
measurement. A stop is a decision, and it needs what the measurement cannot
supply: the cost of crossing the spread, the size against a loss limit, whether
the distance is worth taking at all. The model says where the structure is and
which side gives way first; the trading layer turns that into orders, or
declines to.

The practical difference is modest and real. Today a consumer assembles those
bounds from three separate places - the range the price sits in, the race
between its walls, and the band a stop has to clear - and only the last of them
carries an uncertainty derived from evidence. One model emitting both bounds
means a stop is placed against **one** estimate that states how sure it is,
rather than three that do not.

`2026-10-09-levels-in-one-state-space-design.md` records this as **I7** with
what already exists, and with the reason it is sequenced late: it is the only
improvement on that list with a visible path to P&L, which makes it the easiest
to talk oneself into, and it is only as good as the per-side statistics
underneath it - most of which are still outside the state vector.

## An instrument against its own kind, and whether the gap says anything

Every reading so far is about an instrument on its own: where *its* volatility
turned, how *its* drift is moving, how busy *it* is. There is a second axis.
Gold sits in a family with silver, platinum and copper; BTC sits with the
majors. Most of what any of them does on a given day is what the family did.
What is left over - the part that is **this** instrument and not its peers - is
a different quantity, and the question is whether it carries information the
instrument's own history does not.

It is a fair question and it has a name: factor out the common movement, and
what remains is the residual. The attraction is that the residual is cleaner
than the price - the family's shared move is exactly the part no single-name
reading can explain.

**It has been measured here, twice, and both results are discouraging.**

[`pca-residuals.md`](../research/docs/pca-residuals.md) is this idea executed
properly: PCA over a trailing window, each name regressed on the
eigenportfolios, the residual fitted as an Ornstein-Uhlenbeck process and
traded when stretched. Frozen rule, discovery and confirmation split, 12 coins
then 131 more never seen in discovery. The result:

| book | gross Sharpe | **net Sharpe** |
| --- | ---: | ---: |
| fresh coins, real | +0.27 | **-0.97** [-1.59, -0.30] |
| fresh coins, **OU control** | +11.94 | **+10.47** |
| fresh coins, iid null | -0.49 | -1.94 |

The control is the line that settles it. On a simulated panel whose residuals
*do* revert, the same machinery returns a Sharpe over ten - so the method works
and is implemented correctly. On the real panel the gross edge is +0.27 and
fees take 20% a year. **The residuals do not revert enough to pay for the
hedge.** [`peering.md`](../research/docs/peering.md) reached the same place
from another direction: cross-asset agreement vanished against its control, and
the *synthetic* control showed a larger effect than the real assets did.

### What is still open, and it is not a small remainder

Two things those studies did not test, and the distinction matters:

**A different family.** Both ran on crypto perpetuals, where the cost structure
is brutal - 20.2% a year in fees plus funding, against a gross edge of 5.3%.
Metals are a different proposition: fewer names, a genuinely shared physical
driver, and a CFD cost structure with no funding leg. A result on BTC against
the majors is not a result on gold against silver and platinum.

**A different use.** Both tested the residual as a **trade** - a market-neutral
book that must clear its own hedging costs. That is the expensive way to ask
the question. The cheap way is to use the deviation as a **reading**: an
instrument-level state that conditions what the rest of the model already does,
the way volatility and regime do. A deviation that cannot carry a hedged book
can still be worth knowing when deciding whether *this* level, on *this*
instrument, is likely to hold - and it costs nothing to publish and score,
because the desk already scores every published feature against its own base
rate before anything is allowed to read it.

And the deviation belongs in the state space like everything else, which is
the second thing those studies did differently. A rolling PCA re-fits from
scratch every bar over a chosen window; a **dynamic factor model** holds the
common factors as latent states that persist, lets each instrument's loading
drift, and gives the leftover its own posterior rather than a point estimate
handed to a second-stage fit. The same filter covers one peer or a whole
panel - a pair is the degenerate case - so "pair or family" stops being an
architectural choice.

That gives three layers rather than two, each parameterising the one below:
the **panel** carries the common factors, the **instrument** carries its
volatility and its deviation from them, and the **level** carries its position
and drift.

**And the panel should not be split by sector.** The instinct is to compare
gold with silver and BTC with the majors, but imposing those groups is a
judgement made before the measurement, and it forecloses the most interesting
thing a panel can show. Money leaving crypto and arriving in metals is a
*cross-sector* move; a model fitted per sector cannot see it, because inside
each sector it looks like everything falling together and then everything
rising together, which is exactly what a common factor absorbs.

One universe - metals, indices, equities, crypto, FX - and let the factor model
say what the groups are. If the sectors are real, the loadings will find them;
if what actually moves is **liquidity rotating between** them, only a model
that held them together could have seen it. The grouping becomes an output
rather than an assumption, and the assumption was never measured.

### Which leg, and when

A panel of deviations is a list of candidates, not a trade. Two things decide
which one is worth anything, and a factor model gives both with their own
uncertainty:

* **how well the relationship is holding right now** - the instrument's
  loading on the factors, and how much of its variance they explain. A large
  deviation from a relationship that has stopped holding is not a deviation,
  it is a name that has left the group.
* **how far it has gone** - the deviation against its own dispersion, not in
  price. The same gap means different things on a quiet name and a violent one.

And a third that is easy to leave out: **how fast it comes back**. A deviation
with a long half-life is a position held through cost and funding until the
thesis is forgotten. The reversion speed is a parameter of the deviation's own
state equation, so it is estimated alongside the gap rather than assumed - and
a wide, slow deviation should rank below a narrower, faster one.

The three together are the ranking. None of them is new machinery: a dynamic
factor model produces the loading, the standardised deviation and the
reversion speed as part of the same fit.

That second framing is the one worth taking, and it is specified as **I11** in
[`2026-10-09-levels-in-one-state-space-design.md`](specs/2026-10-09-levels-in-one-state-space-design.md).

## And two kinds of evidence, which is where the five parts come from

A directional call is only worth making when the price structure and the
fundamentals point the same way. Most setups see one or the other. This one is
built to see both at once, and to write down why it thought so at the time.

They are not two votes on the same question. They answer **different**
questions, and the division of labour is the whole reason for carrying both:

> **Technicals give the direction, and let you stand in front of it. News gives
> the instrument the move.**

A level says *where* and *which way*: here is a price that has turned this
market before, here is the side to be on, here is a stop that says when the
reading was wrong. What it cannot say is whether anything is going to happen at
all. A level is a place to be positioned; it is not a reason for the market to
go anywhere.

The catalyst is what supplies that. It decides which instrument moves today and
how far, and it does so without reference to where the lines are drawn. Two
instruments can carry the same structure and only one of them has a reason to
travel.

**Neither half is worth much alone.** Structure without a catalyst is a correct
position in a market that does not move - which is not a small loss, it is the
most expensive kind, because the trade holds risk for nothing and the stop is
still live. A catalyst without structure is a move you have no defined place to
meet, so the entry is arbitrary and the stop is a guess.

That is a claim with a measurable fingerprint, and this repository has one.
**Half of a strategy's trades expiring is what a missing catalyst looks like**:
of 159 closed `thesis-only` trades, 58 timed out and 20 went stale - 49% never
reached either the stop or the target. They were not wrong about direction so
much as positioned in front of nothing. `research/catalysing.md` sets out how
to test that against the news the system already collects, and whether the
timeout rate falls when a catalyst was present.

Five things follow from that, and they are the five parts of the project.

### 1. Structure needs more than one view of the price

The same instrument is quoted by six brokers at once, so the *differences* carry
information a single feed cannot: which venue leads, where quotes diverge, when
liquidity thins ahead of a move. That is why `prices` collects one instrument
from many venues rather than many instruments from one.

It also makes a whole class of error detectable. A feed that stops moving while
five others keep going is a fault, not a market opinion, and no amount of
cleverness applied to that feed alone would reveal it - the only evidence is the
disagreement. Every anomaly feature is therefore a comparison against the median
of the *other* venues, never against a constant, and never against a group the
venue is itself part of.

### 2. Finding the structure is arithmetic, not judgement

`structures` measures every venue against the others and learns, online, what
normal looks like for each - "unusual" only means anything relative to
something, and a constant threshold is the wrong something. It runs
continuously, independently of any model provider, and does not stop when one
is down or unpaid.

The larger half is **key levels**: the prices price keeps turning at, and which
way it goes from what happened last time it arrived *from that side*. Three
ideas carry most of the weight.

**A level is where volatility turns, not where price poked.** The leg coming in
and the leg going out meet at the **origin**, and that is the level. The wick
beyond it is not a second level - it is how far past the first one price was
pushed, which makes it the *width* of the zone rather than its position. Feed
the extreme to the filter instead and every level drifts outward by whatever the
last wick happened to be.

**And an origin spans periods, not bars.** The legs are runs of volatility, and
a run can be six bars on the 3m or most of a session on the daily. The origin is
where those two runs meet - which is why the same price keeps appearing across
`1d`, `5m` and `3m` in the confluence view: one intersection, measured at three
resolutions. The implementation currently approximates this at a bar boundary;
[levels.md](levels.md) sets out what locating it per run would take, and why it
should make the timeframes agree more sharply rather than less.

**A level does different things from each side.** The same price met from below
and met from above are two different objects - one is a ceiling being tested,
the other a floor - so every statistic is kept per approach side. That
asymmetry is what turns "will it hold" into an answer worth having: *given price
arrived from this side, P(pushed up) is p, the expected push is n volatility
units, against a base rate of q*.

Everything is measured in **volatility units**, where `1v` is one typical move
for that instrument on that timeframe. It is what lets gold and EURUSD, 3m and
1w, be compared without per-instrument tuning - and what makes a six-pip move in
a dead session read as the large move it is.

### 3. Fundamentals separate a structure from a coincidence

A move with a release behind it is a different animal from the same move on a
quiet calendar. `news` keeps the economic calendar, the headlines and central
bank reserves alongside the prices, on the same clock.

### 4. Judgement has to happen where both are visible

`agents` puts a model over the stored data with read-only tools, and tells it
plainly that "nothing is happening" is a correct answer. Most windows are.

Judgement is deliberately the *last* layer and the only optional one. The
collectors, the levels model and the notifications all run without a credential,
because a system whose always-on half inherits the availability of its
occasionally-absent half is not always-on.

### 5. Every call gets written down with its reasoning

`journal` records what was decided, *why at that moment*, the state it was
decided from, and what happened afterwards. Prices can be recomputed forever;
the reasoning cannot be reconstructed at all once it is lost - which is what
makes it the one thing worth capturing from day one.

It is also what makes the system able to learn from itself. A resolved level
call plus the features it was made from is a labelled example, and
[`facto.py`](structures.md) fits interactions between those features once enough
have accumulated. That is only possible because the reasoning was written down
before the outcome was known.

## What is not claimed

Which brings it back to where this started. No performance figures. Enough outcomes have to resolve first, and the honest
number of them is small - the counter deliberately restarts whenever a
measurement bug is fixed, because examples recorded under a broken ruler
describe a model that no longer exists.

The system is built to be wrong in ways that can be seen: every conditional is
reported next to its base rate, every claim carries the count behind it, and a
call that merely restates the base rate is not sent at all.
