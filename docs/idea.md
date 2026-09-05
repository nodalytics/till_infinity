# The idea

> **The thesis, in one line.** We price the market and take a stance relative
> to where that price lands: fair value above the market is a long, below it is
> a short, and the distance between them is what the trade is worth. No
> direction is forecast - the side is arithmetic once the valuation exists. The
> README's opening is the short version; this document is the reasoning behind
> each choice.

## Fair value, and why the turn is a consequence rather than a definition

Price does not stop at a level because the line is special. It stops because
enough of the market agrees, for now, that the instrument is worth about that
much. Reading it the other way round - a level is "where price turned" - makes
it a shape that either repeats or does not, and there is nothing to be wrong
about. Reading it as a claim about **value** makes it falsifiable: the level is
an estimate, each touch is an observation of it, and it can be revised or
abandoned.

That is why the origin is a Kalman state rather than a line. The filter is not
decoration; it is what it means to hold an estimate of a quantity you cannot
observe directly and keep updating it from noisy evidence.

**The kinship is volume profile**, and the difference is the input. A point of
control is fair value derived from *where volume traded*. This is fair value
derived from **where volatility turned** - the leg in and the leg out meeting
at a price - which needs nothing but bars, works on any instrument, and does
not depend on a venue willing to sell its tape. Where both can be computed they
are asking the same question with different evidence.

## What "fair value" means here, and what it rests on

The phrase is doing a lot of work, so it is worth saying exactly what is being
claimed and what is not.

**Fair value here is a price at which the marginal buyer and the marginal
seller both decline to act.** Not a valuation in the accounting sense, not an
estimate of what the thing is worth to hold forever. It is the price where
disagreement runs out. Above it, someone would rather sell than own; below it,
someone would rather own than sell; at it, neither has a reason to move, and
price stops for a while. That is all a level is.

Read that way, fair value is **a fact about the participants, not about the
instrument.** It is the current state of a disagreement, which is why it moves,
why it can be wrong, and why it has to be re-estimated from every touch rather
than solved once.

### Whether anything sits underneath it

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

### The two measurements that keep this from being a story

A claim this loose could absorb any evidence, so it is worth naming what the
data has already said, both ways.

**It is not a magnet.** Across 22,219 bars a level was reached within twenty
bars 44.9% of the time, against 49.5% for an arbitrary price the same distance
away. If fair value were a centre that price was pulled toward, that number
would have come back the other way round. It did not, so it is not - the
distance to a level is an *opportunity*, not a force.

**It does have memory.** A level's own record predicts the next turn: the hold
rate on the side price is arriving from separates 59% to 92% across four bands,
an AUC of 0.648. So the thing being estimated is real enough to be estimated
badly or well.

Those two together are the whole position, and they are more restrictive than
they look. Fair value is not somewhere price wants to be. It is somewhere
opinions have changed before, and are more likely to change again. Everything
downstream - the per-side statistics, the base rates, the refusal to forecast -
follows from taking that seriously rather than from preferring it.

### What would overturn it

If levels on synthetics behaved measurably worse than levels on instruments
with an underlying, once cost and volatility were accounted for, the argument
above would be wrong and fair value would need something real beneath it after
all. That is checkable with what is already stored, and it has not been checked
- `research/catalogue.md` compares what they cost to trade, not what their
levels are worth. It is the most load-bearing untested claim in this document.

## Not forecasting is a design constraint, not modesty

The system never answers "which way will price go". It answers "what is this
worth, and where is it trading" - and the side follows arithmetically. That is
a valuation, not a prediction, and it is the constraint the rest of the
architecture exists to protect.

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

## Volatility is half the valuation, not the unit it is quoted in

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

## What is measured and what is assumed

The thesis has two halves and they have not fared equally.

**Supported.** A level's own record predicts its next turn. Bucketed by hold
rate on the arriving side, resolutions separate 59.4% to 92.2% across four
bands with an AUC of 0.648 - the strongest single signal a level carries, and
the only one that *strengthened* when a volatility-denominator bug was fixed.
See [strength.md](../research/strength.md).

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

## Which is also two ways to trade the same estimate

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

A directional call is only worth making when the price structure and the
fundamentals point the same way. Most setups see one or the other. This one is
built to see both at once, and to write down why it thought so at the time.

Five things follow from that, and they are the five parts of the project.

## 1. Structure needs more than one view of the price

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

## 2. Finding the structure is arithmetic, not judgement

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

## 3. Fundamentals separate a structure from a coincidence

A move with a release behind it is a different animal from the same move on a
quiet calendar. `news` keeps the economic calendar, the headlines and central
bank reserves alongside the prices, on the same clock.

## 4. Judgement has to happen where both are visible

`agents` puts a model over the stored data with read-only tools, and tells it
plainly that "nothing is happening" is a correct answer. Most windows are.

Judgement is deliberately the *last* layer and the only optional one. The
collectors, the levels model and the notifications all run without a credential,
because a system whose always-on half inherits the availability of its
occasionally-absent half is not always-on.

## 5. Every call gets written down with its reasoning

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

No performance figures. Enough outcomes have to resolve first, and the honest
number of them is small - the counter deliberately restarts whenever a
measurement bug is fixed, because examples recorded under a broken ruler
describe a model that no longer exists.

The system is built to be wrong in ways that can be seen: every conditional is
reported next to its base rate, every claim carries the count behind it, and a
call that merely restates the base rate is not sent at all.
