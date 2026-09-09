# Outstanding

Ordered by what would change the numbers most. Each entry says where the detail
lives, because the reasoning belongs next to the code it explains rather than
duplicated here.


## Residual time is the hold clock, and the hold clock is where the money went

Noted 2026-09-08 from Agudelo-España et al., *Bayesian Online Prediction of
Change Points* (UAI 2020) - see [research/reading.md](../research/reading.md).

Standard BOCPD infers **run length**: how long since the last regime change.
That paper extends it to **residual time**: how many steps until the *next*
one. That is not a refinement of a detector, it is a different output, and it
happens to be the quantity this desk loses most money not having.

**The measured case, which is already on file.** `thesis-only` closed 74 trades
at target or stop for a net **-7.10** and 75 on the clock for **-389.98**.
Ninety-eight per cent of the loss was the hold timeout. `runner` has the same
shape from the other side: it widens its target and then closes 16 of 26 trades
on a four-hour clock, so the mechanism it exists for never operates. Every
`hold_seconds` on this book is a constant somebody chose.

**What exists to build on.** `context/timing.py` answers the neighbouring
question - `probability_within(distance_vol, bars)`, first passage over a
distance - and `Cusum` and `learning/regimes.py` are already online models over
the same stream. What none of them says is how long the *current* regime has
left.

**Order, and the first step is not the model.**

1. ~~**Measure what the clock is actually costing now, per strategy.**~~ Done
   2026-09-08, and it **demotes this whole entry**. Over 309 closed trades the
   clock costs **-319.50** and the stop costs **-1,801.56**; per trade that is
   -2.68 against -24.35. `thesis-only` is -255.35 on the clock against -690.45
   on stops. A residual-time model would be aimed at the smaller of two
   problems. See [research/locking.md](../research/locking.md).
2. **Score a trivial residual-time baseline first**: the median observed
   regime duration per feed and interval, which is a lookup. A Bayesian
   posterior has to beat that before it has earned anything.
3. **Then BOCPD with residual time**, and ship it with the control the MQL5
   BOCPD article ran - a randomised intervention at matched frequency. Their
   overlay cut drawdown 856.50 to 755.60 by skipping 4 trades of 97, and the
   randomised version *made things worse*, which is the only reason the first
   number means anything.
4. Only then anything that changes a hold in production.

**What would kill it.** If regime duration turns out to be close to
memoryless - the hazard flat - then residual time is a constant and step 2 is
the whole answer. That is a cheap thing to check and it should be checked
before any of step 3.

## FOCuS, and a licence question that has to be settled first

Noted 2026-09-08 from [changepoint-online](https://pypi.org/project/changepoint-online/).

**It is the right shape for the gap.** `river.drift.ADWIN` tests a change in the
**mean** via a Hoeffding bound, which is why the entry below calls a change in
*scale* with no change in mean the gap on the signal side - the event this desk
is built around and the one a mean test cannot see. FOCuS is offered with a
**Gamma cost, which is change-in-scale**, and with the option to constrain
detection to increases only. That is a volatility-regime detector, parametric,
in the form the problem actually has.

Two further things that matter here:

* **It solves the CUSUM likelihood-ratio test exactly, in O(log n) per
  observation, with no window.** Our `context/cusum.py` accumulates deviations
  against a fixed threshold; FOCuS maximises the likelihood ratio over *every
  possible changepoint location* without one being chosen. Given that our own
  `Cusum` scored 0.205v against a fine-resolution transition's 0.124v in
  `research/localising.md`, "our CUSUM is the weak part" is a live hypothesis
  and this is the way to test it.
* **NPFocus is non-parametric**, which covers the same ground as KSWIN without
  a second window to size.

### The licence has to be settled before any of it

**`changepoint-online` is GPLv3. This repository is public and carries no
licence file, and its Docker image is published to `ghcr.io`.** Publishing an
image containing a GPLv3 dependency is distribution, and GPLv3's copyleft
reaches the combined work - which sits badly with a repository that currently
grants no rights at all.

That is not a reason to avoid it, but it is a decision to make deliberately
rather than acquire by running `uv add`:

1. **Decide what licence this repository is under.** It has none today, which
   means default copyright - all rights reserved - while being publicly
   readable. That is worth settling on its own account, independently of this.
2. If the answer is a GPL-compatible one, FOCuS is in.
3. If it is not, the options are to reimplement the algorithm from the papers
   (they are published, and the algorithm is short), or to keep it to offline
   research where nothing is distributed.

`river` is BSD-3 and `river.drift` is already a dependency, which is why ADWIN
raised none of this.

### Order

1. **Settle the licence question.** It is a decision, not work, and everything
   else here waits on it.
2. Then FOCuS with a Gamma cost against `ADWIN` on the same consensus series,
   counting where they disagree - the same shape as the KSWIN comparison below,
   and if neither fires where ADWIN does not, both are cheap to reject.
3. Then FOCuS against `Cusum` in the estimator harness in
   `research/localising.md`, which already has the baseline to beat.

## River's other drift detectors - one of the four is already here

Noted 2026-09-08. River is already a dependency and `river.drift.ADWIN` is
already in production, so the useful question is not "should we use River's
drift module" but **which of the four we are missing and what each would catch
that ADWIN does not**.

**ADWIN: done, and thoroughly.** `learning/drift.py` runs one per feed and
timeframe on the consensus mid, declares a change only when timeframes agree -
a slow one alone, or two fast ones together, because a single fast detector
fires on a busy hour - and grades the result by a scale-free severity,
`|log(after/before)|`, turned into a percentile by a running quantile. A
confirmed change then **discounts every level's accumulated history** in
proportion. It is a consumer, not a published feature, which puts it in a small
minority here.

**PageHinkley: we already have one, hand-rolled.** `context/cusum.py` is a
symmetric CUSUM over a price series in volatility units, and PageHinkley is the
same family with a different stopping rule. So this is a **replacement, not an
addition**, and the interesting form is a head-to-head. The harness for it
exists: the estimator comparison in `research/localising.md` already ranks
change-point estimators by stability under an arbitrary sampling grid, and
`Cusum` scored 0.205v there against the fine-resolution transition's 0.124v.
Dropping PageHinkley into the same table is an afternoon and would say whether
our own version is the weak part or the family is.

**KSWIN: the real gap on the signal side.** ADWIN tests for a change in the
**mean** via a Hoeffding bound. KSWIN applies a Kolmogorov-Smirnov test to two
windows and asks whether they came from the same **distribution** at all. The
difference matters here specifically: a volatility regime change with no change
in mean is exactly the event this desk is built around, and it is invisible to a
mean test. `research/volatility.md` found the estimator's half-life well past
its optimum and a flat 20-bar mean beating it at every interval - a
distribution-shape detector is a different route at the same failure.

**DDM and EDDM: the largest gap, and it is not about prices.** These watch a
*model's error rate* rather than a signal, and flag when it degrades. This
repository has models that decay and **nothing that raises an alarm about it**:

* `breaking.py` is measurably badly calibrated - log loss 0.3624 against 0.2493
  for a constant - and that was found by a person running a measurement.
* `Platt` was added to correct it, and publishes `improvement` so the record can
  say whether it helped. Also read by a person.
* `baseline.Bench` scores every model against its controls continuously, which
  is a **comparison, not an alarm**. It says which is better today; it does not
  say "this stopped working on Tuesday".

Every model-decay finding in `research/` was noticed by somebody looking. DDM on
`Logistic`'s running error, or EDDM on the distance between its mistakes, is the
first thing that would notice on its own - and EDDM specifically because model
decay here is gradual rather than a step.

**Order:**

1. **DDM or EDDM on one model's error stream**, published beside `Bench` and
   acting on nothing. The break model is the obvious first subject because its
   miscalibration is already established, so there is a known event to detect.
2. **KSWIN beside ADWIN on the same series**, counting where they disagree. If
   KSWIN never fires when ADWIN does not, it adds nothing here and that is worth
   knowing cheaply.
3. **PageHinkley against `Cusum`** in the existing estimator harness.

And the caution that applies to all three: `learning/drift.py`'s own docstring
records that a spurious drift **throws away real evidence**, which is why ADWIN
had to become more conservative once its output was consumed. Any second
detector inherits that cost, so each one ships reporting only until the record
says it agrees with something.

## The volatility indices: what else is in a process we know the rules of

Noted 2026-09-08. Prompted by the per-feed record, which has one line in it
that does not look like the others:

| feed | n | total | mean | win |
| --- | --- | --- | --- | --- |
| **volatility_75_index** | 11 | **+618.44** | **+56.22** | 64% |
| uk100 | 12 | +85.11 | +7.09 | 67% |
| volatility_100_index | 10 | -1.21 | -0.12 | 80% |
| volatility_25_index | 20 | -31.48 | -1.57 | 50% |
| volatility_50_index | 11 | -50.41 | -4.58 | 27% |
| whole book | 309 | **-781.44** | -2.53 | |

**The first question is whether v75 is real at all.** Eleven trades at +56 a
trade, on a book losing 781. One outsized winner would produce that line, and
nothing about eleven trades distinguishes a strategy from a coincidence. Before
any of the research below, pull those eleven and look at the distribution: if
the total is one trade, there is nothing here.

**What makes these instruments different, and it is a real difference.** A
Volatility N Index is a generated process with a **stated** annualised
volatility and a fixed tick interval. That means no news, no sessions, no
weekend gaps, no venue disagreement - and, uniquely on this book, **the
volatility is known rather than estimated**. Everything in `structures/vol/` is
machinery for inferring a number these instruments publish in their own name.

Properties worth extracting because they exist here and nowhere else:

* **The tick grid.** A generated series moves in discrete steps; the smallest
  non-zero change is the venue's tick, and `Volatility._tick` already measures
  it and counts distinct multiples. On a synthetic that grid is exact, which
  makes it a testbed for every distance threshold in the book -
  `MIN_TICKS_PER_ZONE` is already gated on it.
* **Known volatility against estimated.** v25, v50, v75 and v100 differ only in
  a published constant. Scoring `Volatility.bps` against the number in the
  instrument's name is a **direct calibration test** of the estimator, on four
  instruments where the truth is not in dispute. `research/volatility.md` found
  a flat 20-bar mean beat the estimator at every interval; this would say by how
  much and whether the error is a scale factor or a shape.
* **Stationarity.** These are the only instruments here where a regime label
  should be *constant*. `learning/regimes.py` producing regime changes on a
  process with none is a false positive with a known answer, which is a
  cleaner test than anything the real instruments can offer.

**On whether ML can predict them, the honest prior is no**, and the reason is
worth stating before anybody spends a week: if the generator is a
constant-volatility random walk then direction is unpredictable *by
construction*, and a model that appears to predict it is finding the
implementation rather than the process. `research/shelves.md` already treats
the synthetics as a **null** for exactly this reason - a model that cannot beat
them is refuted rather than under-trained.

Which makes this the sharper question: **if something does predict them, what
has it found?** Three candidates, all mechanical rather than market:

1. **Tick quantisation** - a discrete grid makes some prices unreachable, and a
   level sitting between two ticks behaves differently from one on the grid.
2. **The spread.** `research/catalogue.md` measured the synthetics at 0.170v to
   cross against FX's 2.267v. A cost that low changes which edges survive, and
   may be the whole of any apparent advantage.
3. **The generator's seed structure** - the Boom and Crash indices announce
   "one spike every N ticks" in their own subtitle, which is a *counting*
   property. Whether the volatility indices carry anything similar is
   checkable and nobody has looked.

**Order:**

1. The eleven v75 trades. One query, and it decides whether any of this is
   worth doing.
2. `Volatility.bps` against the published constant, on all four. A calibration
   test with a known answer.
3. Regime stability on a process with no regimes - a false-positive rate for
   `regimes.py` that no real instrument can give.
4. Only then anything predictive, and with `null.md`'s framing: the finding
   would be about the implementation, not the market, and should be written up
   that way.

## Self-play, which does not transfer - and the simulator, which now does

Noted 2026-09-08. The proposal is poker's: have models play versions of
themselves and let the improvement compound.

**Self-play needs an opponent whose improvement forces yours, and there is not
one.** [research/reading.md](../research/reading.md) already records this from
the AlphaGo Zero side - *"self-play has no analogue at all"* - and the reason is
structural rather than a matter of effort. In poker the opponent adapts, so a
better strategy makes the game harder and the pressure is what produces
improvement. The market does not respond to this desk: it trades fractions of a
lot on a demo account, and a strategy that gets better does not make the market
get better. Two of our models competing would be two models overfitting the
same history in parallel, which is slower than one doing it alone.

The 2026-09-08 adversarial test says the same thing from the evidence side:
asked whether this desk is worst where it is most confident - the signature of
being played against - the answer was no. There is no opponent in the record.

**But the half that was missing is now here.** reading.md names the real
obstacle: Go has a *perfect simulator* and markets do not, so rolling a strategy
forward re-reads one realised path rather than exploring alternatives. It also
names the exception:

> The nearest honest thing to self-play here is the **Deriv synthetics** - a
> generated process we can draw unlimited samples from, with no structure to
> find.

That was a hypothesis when it was written. [spiking.md](../research/spiking.md)
now measures the generator: on Boom 500 the spike arrival is **memoryless with a
coefficient of variation of 0.99** at one per 11.9 minutes, the grind sits
inside a 0.24 band, and the spike size distribution is in hand. **That is enough
to write a simulator that is faithful rather than assumed**, and a faithful
simulator is the thing every RL result in reading.md depends on and this
repository has never had.

So the version worth doing is not self-play. It is **strategies against
unlimited fresh paths from a generator we have verified**, which gives:

* **Sample size without leakage.** Every path is new, so there is no train/test
  split to get wrong and no purging to remember - the failure
  `research/similarity.md` and `horizon.md` both found by hand.
* **A known answer.** Expectancy on a synthetic is computable from the
  generator's parameters, so a strategy's result can be checked against the
  arithmetic rather than against a benchmark. A strategy that beats the
  arithmetic has found an implementation detail, and that is a finding about
  the venue.
* **A null that costs nothing.** The same generator with the spike removed, or
  with the drift zeroed, is the control - and `null.md` asks for exactly this
  and has to improvise it every time.

**What it does not give.** A strategy tuned against a simulated Boom is tuned
for Boom, which is 20% of this book's trades and 42% of its loss. Nothing
learned there transfers to gold or EURUSD, where the generator is unknown and
the whole difficulty lives. This is a **testbed for the machinery** - does the
sizing work, does the stop rule survive a fat tail, does a gate refuse what it
should - not a source of edge on the instruments that matter.

**Order:**

1. **Write the generator** from spiking.md's measured parameters and check it
   against the real series: same spike rate, same gap distribution, same grind
   band, same size quantiles. If a simulated Boom is distinguishable from the
   real one, stop - everything below rests on it not being.
2. **Run the existing strategies against it** and compare with the arithmetic
   expectancy. Any gap is either a bug in a strategy or a bug in the
   arithmetic, and both are worth finding.
3. **Then the controls**: spike removed, drift zeroed, spike direction flipped.
   A strategy whose result does not move when the spike is removed was never
   trading the spike.
4. Self-play stays out until there is an opponent, which there is not.

## Traps on the synthetics, where one of them is published - noted 2026-09-08

A sharper version of the entry below, because on these instruments the question
changes shape twice.

**On the volatility indices, manipulation cannot exist.** v10 through v100 are
generated by a documented algorithm at a stated annualised volatility. There is
no order book, no participants, no dealer and no stop hunt - a "trap" on
Volatility 75 is a random walk doing what a random walk does. That is not a
limitation, it is the most useful control on the book: **any trap or
manipulation detector that fires here is firing on noise, and its false-positive
rate is measurable against a truth known to be zero.** `research/null.md` makes
this argument for features; it applies with more force to a detector whose whole
claim is that it has spotted somebody doing something.

**On Boom and Crash the trap is published.** The instrument's own subtitle says
it: *"On average 1 spike occurs in the price series every 500 ticks."* Price
grinds one way and spikes violently the other, on a stated frequency. Anyone
positioned against the spike is trapped **by design, on a schedule** - which
makes this the one place on this book where a real-time trap predictor has a
ground truth to be scored against.

So the work is **counting, not detecting**. Ticks since the last spike is a
state variable, the hazard is published as a mean, and neither is currently
recorded. Three things follow:

* **It connects to residual time.** The BOCPD entry above wants "how long until
  the next change" and calls the hazard the thing that would kill it if flat.
  Here the hazard is *given*, so Boom and Crash are the test bed where a
  residual-time estimate can be checked against a number the venue publishes,
  before it is trusted anywhere the answer is unknown.
* **It has a live cost attached.** The spike indices are 20% of trades and 42%
  of the loss, at -5.33 a trade against -1.83 for the rest, and the
  against-the-spike hypothesis did **not** explain it - on crash_1000 the buy
  side is the only positive cell. Ticks-since-spike is the obvious next
  candidate and nothing has looked.
* **It is the honest form of "manipulation detection" here.** Everywhere else on
  this book the order flow is unobservable and any such claim would be invented.
  Here it is arithmetic.

**First step, and it is not modelling.** Can a spike be seen in what is already
stored? A query for it against the 19GB quote store timed out, so this is
genuinely unanswered: the `quotes` table is indexed on feed and carries mids,
but whether the sampling is fine enough to resolve a spike - and whether "tick"
in the venue's sense is what we record - has to be established before anything
counts them. If the stored resolution is too coarse, the collector needs a tick
subscription for three instruments before any of the above is possible.

**Order:**

1. Establish whether spikes are visible in stored quotes, and what a "tick"
   means in our record against the venue's.
2. If they are, count them: distribution of ticks between spikes, against the
   published mean. That alone says whether the venue's number is the one the
   feed actually delivers.
3. Then ticks-since-last-spike as a feature, published and read by nothing, and
   scored against the spike-index losses.
4. And use v75 as the control for every step - a detector that fires there is
   wrong, and by exactly how often.

## Spotting a trap while it is happening, not after - noted 2026-09-08

[research/trapping.md](../research/trapping.md) counts traps **after they
resolve**: price went through a level and came back, and the counter increments
once the return is in. That is the right way to measure them and it is useless
at the moment a trade has to be placed.

**The crux, stated before any design.** A trap is *defined* by what happens
next. At the instant of penetration a trap and a break are the same event -
price beyond the level - and they stay the same event until the return does or
does not arrive. So "real-time trap detection" is not detection at all; it is
**P(return | penetration, right now)**, which is the model trapping.md
measured, asked at a different moment. Calling it detection would be the
category error that makes the whole thing sound easier than it is.

**What that model already has.** Within a timeframe the level's own record
separates trap from break at **AUC 0.567**, with `depth_vol` adding at 0.5255
and a correlation of only +0.096. Both features exist at penetration time -
`strength` is on the level, `depth_vol` is how far past it price has gone - so
nothing new has to be collected to ask the question early. That is the cheap
first version and it should be built before anything more ambitious.

**What is genuinely real-time here already**, and is the reason this is worth
attempting at all: `context/cusum.py` is fed from the **quote stream**, not
from closed bars. That is why momentum is intrabar. A penetration that is going
to be a trap should, if the idea has anything in it, show a CUSUM turn against
the break within seconds - and `Cusum` is already stateful per feed and
threshold-adaptive.

**The obstacle that has to be respected.**
[research/resolution.md](../research/resolution.md) measured that **two thirds
of touch outcomes resolve within two seconds**. For a model that is either a
gift or a wall depending on which side of the two seconds the decision sits: a
trap that completes in a second is not something an order reacts to, it is
something a fill is on the wrong side of. So the first measurement is not the
model - it is **the distribution of time-to-return for traps specifically**,
because if the median is under a second there is nothing to trade and the
honest answer is a refusal gate rather than an entry.

**On "manipulation" more broadly, and what this desk cannot see.** Spoofing,
layering and wash trading are order-book phenomena. This book has a broker feed
with a spread and **no depth and no trade tape**, so they are not hard here -
they are unobservable, and any claim to detect them from OHLC would be
invented. Two things are in reach:

* **Cross-venue dislocation**, which already exists as a signal and is the one
  place a price can be shown to be wrong rather than merely unusual.
* **The spike indices**, where the "manipulation" is the generated process and
  is published in the instrument's own name - see the Boom/Crash entry above.
  Nothing has to be inferred; it has to be respected.

**And a prior worth carrying in.** The adversarial test on 2026-09-08 - is this
desk worst where it is most confident - came back **no**: `strength` predicts
traps monotonically, but that is `strength.md`'s finding seen from the other
side rather than evidence of anything selecting against us. So the expectation
going in should be that the record contains less manipulation than it feels
like it does.

**Order:**

1. Time-to-return for traps. One query, and it decides whether the rest is a
   trade or a refusal.
2. Ask the existing trap features at penetration time rather than resolution
   time, and score against the 57.6% base rate on log loss, not accuracy.
3. Only then the quote-stream version, and only on the instruments where step 1
   said there is time to act.

## Shorting a spike index has a stop-to-target ratio nothing refuses - found 2026-09-08

Spotted from a chart: two live sells on Boom 500, the worse one with its stop
**17.0 above entry and its target 9.6 below** - risking 1.78 to make 1. The
record says it is not a one-off and not a mis-adjustment:

| strategy | entry | stop | target | RR |
| --- | --- | --- | --- | --- |
| confluence-scalp | 4715.57 | +8.71 | -2.57 | **0.295** (declined) |
| thesis-only | 4711.74 | +14.61 | -2.57 | ~0.18 |
| sweep-aware | 4711.74 | +11.94 | -2.57 | ~0.22 |
| level-scalp | 4711.74 | +11.94 | -2.57 | ~0.22 |

**It is the instrument, and it is structural.** Boom spikes *up* every ~500
ticks by construction - the chart says so in the instrument's own subtitle. So:

* the **stop** comes from the level's zone, whose width is driven by wick
  depth, and on a spike index the wicks are the spikes. A stop that means
  anything has to sit beyond one.
* the **target** comes from `expected_push_vol`, which is the *ordinary* move
  and was **-0.72v** on these calls.

Wide stop, narrow target, every time, for a sell on Boom. The mirror applies to
a buy on Crash.

**The gate saw it and only one strategy listened.** `reward_to_risk` was
recorded at 0.295 and `confluence-scalp` declined at that number; three others
produced the same shape and took it. That is deliberate - `research/failing.md`
found the RR gate refuses 85% of calls to gain nothing, and RR 1.5+ is the
*worst* bucket by realised return - so RR is not a hard floor. The finding here
is that the one place RR is unambiguously informative is the one place it is
not applied.

**The realised record, which was step 2 and should have been step 1.**

| feed | side | n | total | mean |
| --- | --- | --- | --- | --- |
| boom_500 | **sell** | 15 | **-130.58** | -8.71 |
| boom_500 | buy | 9 | -32.40 | -3.60 |
| boom_1000 | **buy** | 15 | **-116.62** | -7.77 |
| boom_1000 | sell | 4 | -26.98 | -6.75 |
| crash_1000 | **buy** | 10 | **+14.62** | **+1.46** |
| crash_1000 | sell | 9 | -38.57 | -4.29 |

**The against-the-spike hypothesis is not supported.** boom_500 fits it - sells
are four times worse than buys - and the other two contradict it. On
boom_1000 the *buy* side is worse, and on crash_1000 buying is the only
positive cell of the six and one of a handful on the whole book.

So "refuse sells on Boom and buys on Crash", written above as the one fix here
that needs no measurement, is **wrong**, and it would have removed a profitable
line. Proposing a live trading change as needing no measurement was the error,
not the hypothesis - the hypothesis is a reasonable thing to have had and a
cheap thing to have checked first.

Cells are 4 to 15 trades, so none of this is conclusive either. What survives
is narrower and still worth acting on: **the spike indices are 20% of the
trades and 42% of the loss**, at -5.33 a trade against -1.83 for everything
else. That is a size and selection question rather than a side one.

**What to do now:**

1. **Nothing by side.** The record does not support it.
2. **Size them smaller, or refuse them, as a group.** -5.33 a trade over 62
   trades is the second-largest identifiable hole in the book.
3. A per-instrument RR floor remains the general version, and remains the one
   most likely to refuse 85% of calls to gain nothing.

## The round-number control - run 2026-09-07, and it could not answer

Osler's *Support for Resistance* (FRBNY Economic Policy Review, 2000; see
[research/reading.md](../research/reading.md)) tests the support and resistance
levels six FX firms published to their customers and finds they do predict
intraday trend interruptions. It also finds that **round numbers predict about
as well as most published levels**.

That is a control this desk has never run, and it is the most dangerous one
available. Levels here are Kalman states drawn from swing origins across eight
timeframes, grouped into confluence zones, scored by decayed touch counts. If
the whole apparatus does no better than *"round the price and use that"*, the
apparatus is decoration - and the failure would be invisible, because every
number it produces would still look reasonable.

It is the same shape as [magnet.md](magnet.md), which compared a level against
an arbitrary price the same distance away and found the level 44.9% against
49.5%. That measurement is the reason this one is worth running: the arbitrary
price already beat the level once.

**What to run.** Bucket resolved touches by distance to the nearest round
number for the instrument - the round grid is instrument-specific, so it has to
be derived from the price scale rather than fixed - and compare hold rate and
push against the level's own. Then the harder version: draw a level set from
round numbers alone and score it through the ordinary outcome machinery, so
the comparison is between two level *books* rather than between a level and a
number.

**What would make it conclusive.** If round numbers win, the drawing is
decoration. If they tie, confluence is worth exactly what agreement with a
round number is worth, and the zone code has a cheaper substitute. If the drawn
levels win, this is the first outside validation the level book has ever had.

**Run on 2026-09-07 and it answered none of those.**
[research/rounding.md](../research/rounding.md) has it in full. Drawn, round
and random books all hold price within one standard error of each other over
5,877 approaches - and the positive control fails with them: splitting the
drawn book by its own touch count separates the well-tested half from the
untested one by 2.34pp against a standard error of 2.03.

A counter that cannot tell a level touched forty times from one touched twice
is not entitled to an opinion about round numbers, so the null means nothing.
The reason was already on file: [resolution.md](../research/resolution.md)
measured that **two thirds of touch outcomes resolve within two seconds**, and
this audit ran at 5m.

**What is still outstanding is the same question, asked properly**: run the
round-number and random books through the *engine's own touch machinery* on the
quote stream, rather than through a second counter written for the audit. The
`quotes` table exists and is indexed on feed. Until that is done the level book
has never been compared against a trivial baseline at a resolution capable of
telling them apart.

## What is left of the origin-localization specification - 2026-09-07

Only what is outstanding. What was done or refused is recorded in
[research/localising.md](../research/localising.md) with the numbers, which is
where a finished thing belongs - a todo that lists its own completed items
stops being a list of what to do.

**The estimators the comparison never ran.** §5 names eight candidates and
`research/localising.md` reported "the estimators, paired on the same events"
having run **three** - A, D and F. That was an overstatement of what had been
measured. Still unrun:

* **B, candle boundary** - the legacy close-to-open representation. Cheap, and
  the only value is as a second control beside A.
* **C, body midpoint** - explicitly "include only as a benchmark". Same.
* **E, run intersection** - locate where the incoming and outgoing runs meet
  *without* assuming a single candle. This is the one with content: every
  estimator run so far assumes the turn is inside one bar, and E does not.
* **G, fine transition → Kalman** - F feeds the existing filter rather than
  replacing the price outright. F is measured; using it as `z_t` is not.

**H, change-point, is measured and loses.** Run 2026-09-07 on the repository's
own `Cusum` at four thresholds. Best is 0.205v against F's 0.124v - better than
the 0.237v baseline, decisively worse than F. The specification predicted this
in §18 and the measurement agrees with it. Not carried forward.

**§22.1, Bayesian online change-point detection.** Not attempted, and the
reason recorded here for not starting it was wrong. It said "H losing to F is
evidence about the *family*". It is not: H asked **where in price** the
transition sits, and BOCPD's value here is **how long the regime has left**,
which is a different question that test did not touch. See
[the residual-time entry below](#residual-time-is-the-hold-clock-and-the-hold-clock-is-where-the-money-went).

What does still apply is §22.2 - the origin as a posterior was refused because
the band is seven times the localization error - so BOCPD aimed at *locating*
an origin has that to argue past. Aimed at duration it does not.

**The rest, in order.**

1. **The intervals `refine` cannot serve.** 1d needs 24 hours of minutes
   against a window holding eight, so it will never capture. Either the 1m
   window grows for one series or coarse origins keep the coarse band. A
   measurement, not a preference.
2. **§10, asymmetry.** Every band here is symmetric about the transition while
   the rest of the package keeps per-side statistics everywhere. The
   specification asks whether localization changes the wick-depth distribution.
   It must - changing the origin changes the measured distance - and nobody has
   looked.
3. **§22.5, regime-conditional origins.** The grid test shows the answer varies
   enormously by instrument. Splitting by volatility regime rather than by
   ticker is the version with a chance of transferring.
4. **§22.6, liquidity-aware zone width.** Needs a spread series per instrument,
   which `prices` has and nothing has joined to the band.
5. **§22.7, §22.8, §22.9** - run persistence, event-based sampling, multi-scale
   persistence. All three are variations on "does the answer survive a change
   of sampling", which §22.12 already answered once in the affirmative. Lower
   priority for that reason rather than higher.
6. **§22.11, origin survival analysis.** How long an origin stays relevant.
   `revisits` already counts the wearing-out and nothing reads it.
7. **§22.3, microstructure-noise-aware detection.** Relevant only once
   something reads below 1m. Nothing does.

**Not applicable here, and worth saying so rather than leaving as "later".**
§22.4 order-flow confirmation and §22.10 liquidity around levels both need a
book. This desk has a broker feed with a spread and no depth, so they are not
outstanding work - they are unreachable without a different data source.

## Options flow, as positioning that is observed rather than inferred - noted 2026-09-07

Not started. Recorded now because it is the third entry on a list this desk
keeps rediscovering: `prices/positioning.py` collects open interest and the
long/short split, `prices/funding.py` collects funding, and **nothing consumes
any of them**. Options flow would be a fourth collector unless the order is
fixed first.

**Why it is worth wanting.** Everything this system draws is inferred from
price. Open interest is the one exception already collected, and
[research/crypto.md](../research/crypto.md) makes the argument for it: OI plus
price direction separates fresh money from closing, and the price path is
identical in both cases, so it is information a price-only model cannot
recover. Options flow is the same kind of claim with more structure - strikes
are prices somebody committed at, and expiries put a clock on the commitment.

The specific thing that would connect to what is already here is **gamma
positioning**: dealers hedging a short-gamma book amplify moves and a
long-gamma book damps them. That is a statement about whether a level holds,
which is exactly what `learning/breaking.py` already models from price alone at
AUC 0.658. A feature uncorrelated with `approach_vol` and `depth_vol` is worth
more than a better-correlated one, which is the test `slowing` had to pass.

**What would have to be true first, in order:**

1. **A source.** Deribit publishes an options book over the same ccxt path the
   perpetuals already use, which makes crypto the cheap case. Equity options
   flow is a paid feed and the broker here carries none, so `us100` and
   `spx500` would stay dark - and half a book is how a feature becomes a
   comparison between instruments rather than about them.
2. **Consume something already collected.** Open interest has been sitting in
   `positioning.py` unread since it was built. Wiring a fourth source before
   the first three feed anything is how [inert.md](../research/inert.md) got to
   nine cases.
3. **Then the ordinary discipline**: correlate against `approach_vol` and
   `depth_vol` before looking at AUC at all, and run it against the null in
   [research/null.md](../research/null.md), because a positioning series
   measured on a trending market will look predictive whether or not it is.

**The honest prior.** Deribit is one venue on two instruments. Whatever gamma
positioning says there is a statement about crypto options in one place, not
about the book this desk trades - and the seven FX majors, gold, silver and
the indices have no options data reachable from here at all.

## VWAP, as a second definition of fair value - noted 2026-09-07

[Volume Weighted Average Price (VWAP): The Holy Grail for Day Trading
Systems](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4631351), SSRN
4631351. Read for what it would add to `structures`, not adopted.

**Why it is interesting here.** [idea.md](idea.md) defines fair value as where
a demand or supply spree began - a price the market itself committed at. VWAP
is a different answer to the same question: the price at which the day's volume
actually changed hands. Two definitions that disagree is information; a level
that both agree on is a stronger claim than either alone, which is exactly the
argument `confluence` already makes across timeframes.

It is also the one anchor institutions are measured against, which is a
mechanical reason for price to return to it that has nothing to do with the
level being respected - a different *kind* of reason from anything currently
drawn here.

**The caveat, and it is the point.** Traded mechanically on its own - buy below
it, sell above it, no volume confirmation, no risk rule - it produces heavy
drawdowns. Institutions use it to gauge fair value and to minimise market
impact on an order they were going to place anyway, which is not the same as
using it to decide whether to place one. So the shape this would take here is
a **feature and a second opinion on fair value**, published beside the outcome
and read by nothing, in the order [features.md](../research/features.md)
argues for.

**What would block it.** VWAP needs volume, and volume is the field this book
is least sure of: the broker feed has a spread and no book behind it, and the
`bars` table's `volume` column is nullable and unevenly populated across
venues. The first question is not whether VWAP predicts anything - it is
whether there is volume to compute it from on the instruments that trade here.
That is a counting exercise and it comes first.


## Strategies on break risk, added 2026-08-31

`structures/learning/breaking.py` publishes `break_probability` on every level call and
nothing acts on it. These are the strategies it makes possible, and what each
needs before it can be trusted with money.

The evidence behind all of them: `approach_vol` and `depth_vol` together
separate hold from break at **AUC 0.658** over 10,904 touches
([research/force.md](../research/force.md)), on a question `up_rate` - which
carries almost all of *direction* - answers at 0.4892, i.e. not at all.

### 1. Refuse the trade the level is about to lose

The cheapest and the one to do first, because it only ever declines. Every
existing strategy trades a level *holding*; none of them asks how likely it is
to give way. A gate that refuses when `break_probability` is high is a filter on
what already exists rather than a new thing to size.

**Needs first**: the arithmetic in [paying.md](../research/paying.md), applied
to breaks. A refusal is only worth making if the trades it declines lose more
than the trades it wrongly declines would have won.

### 2. Trade the break itself

The level goes, price runs. This is the natural inverse of every level strategy
here and nothing implements it.

**Needs first, and this is the awkward part**: breaks are the *more
predictable* move but not the larger one. Median push 2.82v against a hold's
2.08v, but means of 3.38v and 5.67v - holds carry a fat right tail. A break
strategy trades the consistent side of a skewed distribution, which is a
different proposition from trading the bigger one and must not be sold as the
same.

**And**: break rates and separability are instrument-specific, 38.5% on eurgbp
against 59.4% on us2000, joint AUC 0.509 on jp225 against 0.671 on euraud. An
instrument list chosen on net, as paying.md argues for direction.

### 3. Size on the break estimate rather than gate on it

Between the two: take the trade either way and let `break_probability` scale
the position. Softer than a gate and it keeps the evidence flowing, because a
refused trade produces no outcome and a small one does.

**Needs first**: calibration. `Logistic` is not calibrated and nothing here has
checked whether a stated 70% happens seventy times in a hundred - which is what
[calibration.md](../research/planned/calibration.md) was written for and has
never been measured on this system.

### 4. The range around a level - `chop`, and why it is parked

Price does not only hold or break. It can settle into a **range around** the
level, oscillating either side and resolving neither way, and nothing here
models that: `approach_vol`, `depth_vol` and the momentum ensemble all describe
the *arrival* rather than what follows.

The code names it - `Outcome.CHOP` - and every model excludes it, correctly,
since it is neither a hold nor a break. What nothing does is predict it.

**Parked on the sample, not on the idea.** At five to thirty minutes chop is
2.5% of resolutions - 280 of 11,272 - which cannot support a third class. For
comparison `trap` is 22.6%, and a trap is the same shape of event ("went
through and came back") already handled on the right side of the hold/break
line.

Revisit when there are a few thousand chops, or if a cut of the record makes
them commoner - a slower timeframe, a quieter session, a wider zone. The
question to ask then is not "can we predict chop" but **"does a level about to
chop look different on arrival"**, which is the same shape as the break
question and would use the same two features.

### 5. Add deceleration to the estimate

`slowing` - the speed of the bars before arrival against the bars before those
- separates at AUC 0.5237 and is **orthogonal to `approach_vol`**, correlation
+0.008. A weak separator uncorrelated with a strong one adds where a second
strong one would not.

**Needs first**: the engine carrying a short speed history per series, so the
figure exists when a touch opens rather than only in a replay.

## ~~0r. Nothing can tell a shut market from a refused order~~ - fixed 2026-08-28

Three parts, and the third matters most.

`stale_quote_after` treats a feed that has not quoted in five minutes as a
shut market: the hold defers quietly instead of retrying and filling the log
with warnings that read as a fault.

The rejection message now carries whatever the bridge said. It looked only for
a `detail` key the bridge does not use, so every refusal arrived as a bare
"400" carrying nothing - which hid three distinct causes in one day and left
one of them permanently unidentified, because the container had recycled
before anyone looked.

The eurgbp and usdcad rejections were **not** the stops-level miss assumed
earlier: their stops clear the broker minimum by 2.65x and 1.95x and their
volumes are valid. What refused them is still unknown, and now recoverable
next time it happens.


Found 2026-08-27. A us30 position could not be closed for twenty minutes -
`POST /positions/close: 400`, retried on every pass. The cause was the index's
daily break, and the evidence was not the error, which carries no retcode: it
was that **the quote had not moved in thirty minutes**, bid and ask and
timestamp all identical to half an hour earlier.

**`spec.tradable` said `True` throughout.** That flag reports whether the
instrument is enabled, not whether it is currently trading, so nothing
upstream had any reason to hold back.

These are different situations and deserve different handling. A shut market
means wait - retrying is pointless, and the log fills with warnings that look
like a fault. A refused order means something about *this order* is wrong and
is worth surfacing loudly. Today they are indistinguishable, so the loud
handling is applied to both and the real refusals - the eurgbp stops-level
miss, the brent target - are harder to see for the noise.

A staleness check on the quote is cheap and reliable: this feed was thirty
minutes old against a normal sub-second. It would let `_stale` and `_expire`
defer quietly instead of retrying, and would let a genuine rejection stand out
again.

Two smaller things it would also fix. The bridge's bare 400 has now hidden
three distinct causes in one day - a stops-level miss, an impossible target,
and a shut market - and each took a separate investigation to identify. And
the wide-spread guard added the same evening keys off the spread, which a
frozen feed may not widen at all.

## 0s. A trade that spans a restart is never journalled on close

Found 2026-08-28, and it undermines every measurement taken from the trading
journal.

`_settle` guards its journal write on `if live.ref:`. `ref` is handed over
through `_pending`, which is only set for a position **opened in this run**, so
a position adopted during reconciliation after a restart carries `ref=""`. Its
close is logged, announced to Telegram, and never written down. `journal.outcome`
would refuse it anyway - an outcome without a parent cannot be paired - so
removing the guard alone changes nothing.

Two closes on the evening it was found went missing this way: an aus200
`runner` at -28.49 and a us30 `thesis-only` at -5.55, both having survived a
deploy. The service was deployed about fifteen times that day.

**The bias is not random, which is the damaging part.** What goes missing is
exactly the trades that lived longest - long enough to span a restart. Every
number computed from `kind='outcome'` that day inherits that: the per-strategy
table, the 1.09R stop cost, the win share. Short trades are over-represented in
all of them.

Two ways to fix it, and the second needs no new storage:

* persist a ticket-to-ref map in the data volume, written on fill and read at
  startup;
* or recover the ref at adoption by finding the newest `decision` for that
  symbol and side which is not yet the parent of any outcome. The journal
  already holds everything this needs.

Worth doing before any further conclusion is drawn from the trading journal.
Until then, treat trade counts as a floor and hold-length statistics as
understated - together with 0q, which independently makes `seconds` measure
from the last adoption rather than from the fill.

## ~~0q. Every deploy resets the hold clock on open positions~~ - fixed 2026-08-28

`Live.seen` is stamped from the broker's own `opened` when a position is
adopted, rather than from the moment of adoption. The honest timestamp was
already on the position and nothing had asked for it, so no storage was
needed. Hold statistics taken from `seconds` before this date still measure
from the last adoption and read shorter than the trades were.


Noticed 2026-08-27 while a us30 position retried a refused close: its age went
from 436s back to 311s across a container restart.

`Live.seen` is set when a position is adopted during reconciliation, so a
restart gives every open position a fresh clock. `max_hold`, `hold_seconds`
and `stale_after` all measure from it, and all of them therefore start again.

Mostly harmless, and not always: on the day this was found the service was
deployed about fifteen times, so anything open across that window had its hold
extended repeatedly. Two consequences worth knowing:

* **A position can evade its hold indefinitely** during a busy day of
  shipping, which is precisely when nobody is watching the holds.
* **The journal cannot be trusted on duration across a restart.** `seconds` on
  an outcome measures from the last adoption, not from the fill, so any
  analysis of how long trades are held is wrong by however many deploys
  intervened - and it will be wrong quietly, in the direction of looking
  shorter.

The fix is to persist the fill time per ticket rather than stamping it at
adoption; the broker already reports `opened` on a position, which is the
honest source and needs no storage at all. Small, and worth doing before any
question about hold length is asked of the data.

## ~~0p. `structures` published an expected push of 10,229 volatility units~~ - root cause found 2026-08-28

**It was a guard that existed and was never asked.** `WARMUP = 20` in
`volatility.py`, the `warmup` field, the `_seen` counter and a `warm` property
all existed, each documented - "below this the variance of the variance is
larger than anything it would be used to decide" - and **no code joined them to
a decision**. The estimator published `bps` from its first bar.

A cold estimate returns `floor_bps`. Every distance in the package is a price
divided by that, so at the old floor of 0.05 bps one volatility unit on brent
was 0.00044 in price and a four-and-a-half point move came out at 10,227
units - against the 10,229.7 that was published. That also explains the
concentration on 1m: those are the series that can genuinely be flat long
enough for the estimate to sit on its floor.

Fixed in two places. `Engine` declines to publish a call from an estimate that
is not warm, which is the root cause. And `MIN_VOL_BPS` goes from 0.05 to
0.25 - across live decisions the lowest volatility ever seen was 0.517 bps and
the median 2.47, so the old floor sat an order of magnitude below anything real
and did not bound what it was written to bound.

`max_push_vol` stays as the third line. It is a bandage, and a bandage over a
fixed wound is worth keeping: it is the only thing that made this visible.

### The original entry `structures` published an expected push of 10,229 volatility units

Found live 2026-08-27. A brent 1m call arrived with `expected_push_vol` of
**10,229.708407** against a measured distribution whose median is 2.24v and
whose p99 is 9.55v - four orders of magnitude past anything the market does.
`vol_bps` on the same call was 41.6, which is ordinary, so the fault is in the
push estimate itself rather than in the volatility it is denominated in.

Trading turned it into a target of 3850.308 on an entry of 88.374 - 43 times
the price of the instrument - and the broker refused the order. **The refusal
is the only reason it was seen**, which is the part worth sitting with: a push
of 30v rather than 10,229v would have produced a target that looked odd and
traded fine, and the position would have run to its stop or its clock aiming
at a price it could never reach. Nothing would have said anything.

The trading side now refuses a push past `max_push_vol`, which stops the money
leaving. **That is a bandage on the symptom.** The open question is upstream:
what produces a number like that, how often, and whether the same fault
distorts pushes that are wrong but plausible - because those are the expensive
ones and this gate cannot see them.

### Characterised the same evening, over 51,885 signals

**It is rare: 40 occurrences, 0.077%.** And it is concentrated on fast
intervals - 27 on 1m, 38 of 40 across 1m, 3m and 5m together. Only one 15m
call. That points at something in the fast path rather than at the estimator in
general.

**The distribution is bimodal, with a clean gap**, which is the useful part:

| band | n | what it looks like |
| --- | ---: | --- |
| up to 10.59v | - | legitimate, ordinary `risk_vol`, just past p99.9 (9.81v) |
| 10.59v - 45.82v | **0** | nothing at all |
| 45.8v to 20,682v | 40 | the fault |

So `max_push_vol` at 25v sits inside the gap. On this sample it refuses every
fault and no legitimate call, and there are **no wrong-but-plausible values
hiding under the ceiling** - which was the worry that made the ceiling feel
like a bandage. It is better placed than the guess deserved.

That does not close the item. Absence of intermediate values in one sample is
not proof the fault cannot produce them, and a ceiling still treats the
symptom. But the risk it was covering is now measured rather than feared.

Worth checking next: what is different about the 1m path, and whether
`expected_push_vol` has a divide-by-something that can approach zero there.
Two of the affected calls also carry `risk_vol` of exactly 0.0, which may be
the same fault seen from another angle.

## 0n. Trend context is the strongest thing measured here, and nothing uses it

Found 2026-08-27, written up in [replay.md](../research/replay.md), built by
`research/harness/trend.py`. **This is the highest-value unbuilt item on the
list.**

An efficiency ratio over the last twelve level prices on a feed - net
displacement over distance travelled, computed from strictly prior resolutions
- separates outcomes better than anything else tried:

| efficiency | break share | R with the level |
| --- | ---: | ---: |
| 0.017-0.096 (chop) | 11.3% | 0.807 |
| 0.985-1.000 (trend) | **1.4%** | **1.149** |

0.34R between the extremes, monotonic across the top three deciles, and it
holds inside every interval - which is what rules out composition - while
strengthening as the timeframe slows, +0.081 on 1m to +0.245 on 15m.

For scale: every direction gate measured the same day spread 0.09 to 0.15
across its entire range, and all three were switched off as a result. This is
more than twice that and points somewhere.

**The mechanism is not the obvious one, and building the obvious thing would
get it backwards.** A trend does not run levels over - breaks are *rarest* in
the most trending decile. What a trend does is make a level hold harder and
pay more, so this is a pullback-in-trend effect, not a breakout effect.

**Two shapes, and the second is probably better.** A gate refusing entries
below an efficiency floor is the obvious form. But the effect is continuous and
monotonic, so *sizing* risk with trend context uses the whole curve instead of
a cliff edge, and does not throw away the trades in the middle. Sizing has the
further advantage of being reversible in a way a gate is not: a gate that is
wrong shows up as nothing happening, which is the failure mode this repository
keeps finding late.

It also lands well for `high-timeframe`, which triggers at 15m and above -
exactly where the effect is largest.

Three things that stop this being a finished answer. The window of twelve is a
guess. The efficiency ratio is one trend measure among several, and picking it
first because it was easy to compute is not the same as picking it because it
was best - see 0m, which this partly pays down. And it is a fixed
stop-and-target rule over touch resolutions rather than the trades the book
actually took, which is the same caveat that applies to every replay result
here.

## 0m. Momentum has one detector, and levels have a whole discipline

Raised 2026-08-27, after `structures/context/cusum.py` went in and momentum became the
**primary** entry confirmation, with candlestick patterns demoted to a
fallback. The reasoning for that demotion is sound and is recorded in
`trading/candles.py`: candles are bar-quantised and single-broker, while the
accumulator reads the consensus quote stream across six venues. One measures
the market, the other measures a vendor.

But it leaves an imbalance nobody should be comfortable with. Levels are
served by `pips`, `runs`, `confluence`, `pivots`, `sweeps`, `facto` and a
documented argument about which of them price respects more often. Volatility
is served by five estimators and `consensus_vol` to ensemble them, precisely
because trusting one number was judged too fragile. **Momentum is now load-
bearing and is served by exactly one estimator, chosen on its first day, with
no measurement behind its threshold.**

`MOVE_VOL`, `THRESHOLD` and the `max_against_vol` values are all guesses. They
are stated as such in the code, which is honest and is not the same as being
right.

What the parallel would look like, roughly in order of what it would change:

* **An ensemble, as `consensus_vol` is for volatility.** The single most
  transferable idea, because the argument for it is already written down and
  already accepted for a different quantity.
* **An efficiency ratio** - net displacement over the sum of absolute moves.
  It separates a run from chop at the same net distance, which CUSUM alone
  cannot: twelve up-ticks and a hundred ticks of noise ending in the same
  place accumulate identically.
* **Run persistence**, measured rather than assumed. The gates ask whether a
  run is still going; nothing here has established how long runs *last*, which
  is the empirical question underneath that.
* **Cross-venue agreement**, the momentum analogue of level confluence. A run
  visible on one venue and absent on five is that venue, not the market - the
  same reasoning that produced the dislocation detector.
* **Velocity**, in volatility units per second rather than per bar, so a fast
  move and a slow one of equal size are distinguishable. `speeds.py` is close
  to this and is windowed, which is the thing CUSUM was adopted to avoid.

Not urgent while confirmation stays off, and it becomes urgent the moment it
is switched on for real, because at that point every refused entry is being
refused by a number nobody has checked.

## 0. The outcome rate - **answered on 2026-08-14**, and it was the consensus

*Read this before the rest of item 0, which is the trail that led here and is
kept because two of its hypotheses were wrong in instructive ways.*

The rate was not a level problem, a granularity problem or a re-arm problem. It
was that **the touch check ran once per venue row rather than once per bar.**

`Consensus.observe` answers again on every venue that reports a bar - by
design, so the median improves within a sweep instead of waiting for a venue
that may never arrive. `Engine.observe_bar` then ran the whole touch check on
each of those answers, and the consensus median *moves* as venues arrive. On
spx500, whose venues quote genuinely different absolute prices, it moves by
more than four volatility units inside a single bar. The tracker was handed
that jitter as though it were price, so a touch opened on one venue's row and
resolved on the next one's - at the same timestamp, having observed nothing
but the median rearranging itself.

Measured on a replay of the stored 5m bars, before and after:

| | resolutions | resolved at the instant they opened |
|---|---|---|
| before | 500 | 224 (44.8%) |
| checking once per bar | 255 | **0** |
| and resolving from the origin | 206 | 0 |

**49% of all resolutions were manufactured**, and spx500 alone fell from 263 to
39. The production journal agrees independently: 46% of its outcomes have
`seconds <= 0`, and 97% of those were already past `resolve_vol` when they
resolved, with a median `depth_vol` of 0.12 against 0.25 for touches that
lasted - they clipped the zone edge and were recorded as rejections.

It also explains why two runs of the same replay disagreed: venue arrival order
is not stable.

A second, independent cause survived that fix at 16.7% of touches, spread
evenly across all six instruments: a zone reaches `MAX_ZONE_VOL` from the level
while a rejection needs `resolve_vol`, which is half of it, so price clipping
the far edge arrived already past the threshold. Rejections are now measured
from the origin. Both in `ddc7aec`.

**What this does not do is unblock `fit`.** The rate should fall by about half
and the concentration by more, but neither has been re-measured on production -
the replay is not the live system. Re-measure before lifting the gate, and note
that three of the four counting bugs found this day were only visible *because*
someone measured rather than reasoned.

### The other three found the same day

- **Volatility was estimated once per venue row too** (`18e95c0`), so it came
  out divided by the venues past quorum - 4x on EURUSD and GBPUSD, 3x on
  XAUUSD, 2x on BTCUSD. Every distance in volatility units read that much too
  large. This invalidates measurements, not just numbers: see [levels.md](
  levels.md) §10b and the agreement section, and [strength.md](../research/strength.md).
- **`expire`'s return value was discarded** (`04d24c0`), so touches that
  resolved on the clock reached only the kNN memory - no `level.record`, no
  journal, no `facto`. Breaks went 11 to 61 and back checks 3 to 29.
- **The first-passage null was handed a MAD where it wanted a sigma**
  (`e5dec8d`), understating every reach probability by a quarter of a distance.

## ~~0y. What the weekend could not answer~~ - answered on Monday 2026-08-17

Everything in the original version of this item was measured on a Saturday with
FX and the indices shut, so any number involving the other eleven instruments
was describing a closed market rather than a quiet one. The recorder ran
without a gap through to Monday and settled most of it.

**The weekday multiplier is 6.5x.** Outcomes per hour, from 88 uninterrupted
windows:

| day | windows | outcomes | per hour |
|---|---|---|---|
| Sat 15 Aug | 24 | 377 | 31 |
| Sun 16 Aug | 48 | 1,025 | 43 |
| **Mon 17 Aug** | 16 | 1,602 | **200** |

So the weekend readings were not a quiet market, they were a shut one, and
every conclusion this item was protecting was right to wait.

**The outcome mix is stable across sessions**, which is the more interesting
half:

| day | reject | trap | break | backcheck |
|---|---|---|---|---|
| Sat | 54% | 31% | 9% | 6% |
| Sun | 61% | 24% | 6% | 10% |
| Mon | 62% | 14% | 9% | 16% |

Roughly **38% of resolutions are not a bounce** on every one of the three days.
The mix moves within that - Monday trades backcheck for trap - but the
headline share does not, so the pipeline is not degenerate and was not
degenerate on the weekend either.

**The decline gate corrected itself.** `audusd`, `eurusd`, `usdcad`, `usdchf`
and `nzdusd` at 1m were declined on `MIN_TICKS_PER_ZONE` using tick estimates
taken while those markets were shut. On Monday **only `sol/1m` is declined**,
and four of the five are resolving at 1m: eurusd 40, usdchf 21, usdcad 20,
nzdusd 13. Nothing had to be changed. The floor is not too high for FX; the
estimate it reads was simply meaningless on a closed market and became
meaningful when the market opened.

That also answers the tick-estimate question underneath it. The estimates were
not real on Saturday and are now - the gate is the thing that tells you.

### Still open: us100 is nearly silent and spx500 is not

The one thing Monday raised rather than settled. On the same windows,
**spx500 resolved 355 outcomes and us100 five**, for two instruments that move
together. Three explanations are ruled out by measurement:

- **Bar flow.** Both are collecting normally, newest bar 2 minutes old across
  every venue and interval.
- **Level count.** us100 holds 35 levels against spx500's 41.
- **Venue floor.** us100/3m has four fresh venues and us100/1m five, both above
  `MIN_VENUES = 3`. This was the leading hypothesis and it is wrong.

What has *not* been ruled out is the simplest thing: the recorder's Monday rows
stop at 07:00 UTC, which is before the US cash open, and 231 of spx500's 355
came from its 3m cell. This may be nothing more than two instruments being
looked at pre-market.

**Do not spend a day on this before the evidence is in.** The eth-versus-btc
investigation on 2026-08-15 ruled out three structural explanations, found
nothing, and the ratio flipped inside an hour - it was market, not structure,
and the 5x turned out to be 1.3x over six hours. This has the same shape. Read
the recorder across a full US session first.

### What a healthy rate looks like - still not established

The one question here with no answer. 200/hour on a weekday across fourteen
instruments is a number, not a baseline, because nothing says what it should
be. The closest thing to a control remains a per-cell rate: `spx500/3m` runs
1,750 per thousand bars where `nzdusd/1m` runs 148, and neither is known to be
right. This needs a definition before it needs a measurement.

## 0g. Two thirds of production outcomes resolve within two seconds

**Found on 2026-08-18** while asking which journalled outcomes resolved well.
Ahead of everything else: it may invalidate what the production journal says
about anything.

Over 26,495 resolved outcomes across 4.4 days:

| | share |
|---|---|
| resolved in **0 seconds** | **33.6%** |
| resolved in <= 2 seconds | **67.5%** |
| resolved in <= 60 seconds | 84.0% |

**It is the coarse timeframes, and 1m is the one that behaves.**

| interval | n | zero-duration | negative |
|---|---|---|---|
| 3m | 13,794 | **41.9%** | 1.7% |
| 15m | 3,017 | 35.1% | 1.2% |
| 5m | 5,152 | 35.0% | 1.4% |
| 1h | 946 | **22.7%** | 0.0% |
| **1m** | 3,559 | **1.0%** | **7.9%** |

A touch on a **1h** level opening and resolving inside two seconds means price
travelled `resolve_vol` - 1.5 volatility units of *something* - in two seconds.
For an hourly level that is not a market move; it is a threshold measured
against the wrong denominator.

The durations are **1, 2, 3 seconds**, not multiples of the bar, so this is the
**quote path** rather than a bar containing both events. That matters twice
over: it is where the resolution is happening, and it is why none of the
bars-only research shows it. [edge.md](edge.md) already warns that "the quote
path can overturn a bars-only result" - this is that, and it means the
production journal and the replay are not measuring the same system.

**Negative durations are back**, at 2.34% overall and worst at −1,347s. They
were fixed to 0% on 2026-08-14 and 1m is now the worst offender at 7.9%. A
resolution recorded before its own touch began is a timestamp bug, and a
separate one from the instant resolutions since it concentrates on the opposite
interval.

**Found and fixed on 2026-08-18 - and the first hypothesis was wrong.** The
suspicion recorded here was that the resolution threshold or its volatility
denominator came from the finest series rather than the level's own. It does
not: `check` reads `self.vol.of(feed, interval)`, the level's own.

The actual mechanism is the **bar wick**. `observe_bar` hands `low` and `high`
to `check`, which passes them to `Tracker.update` for whatever touch is open.
A quote opens a touch part way through a bar; the bar then arrives carrying a
range describing the *whole* period, including the seconds before that touch
existed. Applied to it, the touch resolves immediately on movement that
predates it.

The journal says exactly that. Across all 8,897 zero-duration outcomes,
`run_vol` is **0.00 at the median, at p90 and at the maximum** - not one of
them ever recorded a leg into the level - while `push_vol` reads a median of
2.88 volatility units. A large move, no approach, no time.

The fix is one condition: a touch that began at or after the bar opened sees
only the close, and picks the wick up on the next bar it genuinely lives
through. `check` takes a `since` argument for it, which is the bar's open.

Coarse intervals were worse because their bars cover more time, so more touches
open inside one. 1m was least affected and is the only interval whose numbers
looked sane, which is what made this legible at all.

**Not yet verified in production.** The fix is measured only by a unit test;
the journal has to be re-read after a day of running to confirm the zero
durations are gone. The negative durations are a *separate* bug - they
concentrate on 1m, the opposite interval - and are untouched by this.

**What it does not touch.** Every research document replays bars only, so the
findings in [prior.md](../research/prior.md),
[magnitude.md](../research/magnitude.md) and the rest describe the bar path and
are unaffected. What is now in doubt is whether production behaves like the
thing that was measured.

### It also means the journal cannot be trained on yet

Asked on 2026-08-18 whether it was time to fit `facto` on the journal. It is
not, and the way that was established is worth keeping: rather than pick one
plausibility cutoff and assert it, the fit was run at several, so the answer
could be read against how much the filter was doing.

| filter | kept | facto | logistic | holds |
|---|---|---|---|---|
| everything | 26,538 | 96.0% | 97.3% | 97.4% |
| positive duration only | 17,021 (64%) | 93.5% | 95.8% | 95.9% |
| at least a quarter of its bar | 5,588 (21%) | 79.4% | 87.3% | 87.3% |
| **at least one of its own bars** | **3,179 (12%)** | **60.7%** | **77.1%** | **77.3%** |
| at least two of its own bars | 2,116 (8%) | 52.0% | 67.0% | 67.8% |

**The filter is the whole result.** 96-97% on the raw journal is the same shape
as the 99.9% that [edge.md](edge.md) was written about: not skill, but
resolutions so fast the label predicts itself. Requiring a touch to outlive one
bar of its own timeframe drops 88% of the journal and takes accuracy to 77%.

Two things follow.

**Do not fit `facto` on this.** It loses at every filter level - to a 1KB
logistic regression and to the trivial rule alike - and at the honest filter it
scores **52.0%**, which is a coin flip. That agrees with
[models.md](../research/models.md), which measured it at 64.3% against 73.1% on
replayed touches.

**And the model is the trivial rule again, on production data this time.**
Logistic and holds are within 0.8 points of each other at every level: 97.3 vs
97.4, 77.1 vs 77.3, 67.0 vs 67.8. [prior.md](../research/prior.md) found that
on the replay; here it is in the journal.

The survival table is also the cleanest statement of the bug:

| interval | outcomes | survive one bar | median seconds of those |
|---|---|---|---|
| 3m | 13,805 | **6.2%** | 472 |
| 5m | 5,159 | 8.2% | 932 |
| 15m | 3,021 | 5.1% | 2,435 |
| 1h | 946 | **3.8%** | 7,048 |
| **1m** | 3,580 | **47.6%** | 198 |

1m keeps half and every coarse timeframe keeps almost nothing.

## 0h. Pivots are inert, and they are the control the project needs most

**Found on 2026-08-18** while asking what a model trained on pivots could do.
The answer is nothing, because pivot levels have never opened a single touch.

`vol.of(feed, "daily")` returns **warm=False, bps=0.0500**. The volatility book
holds series for `1m`, `3m`, `5m`, `15m`, `1h`, `4h`, `1d` and `1w` - the bar
intervals. Pivots live under their **session** name, `daily` and `weekly`, and
there is no series behind either. Three consequences, in order:

- 0.0500 is the documented **floor** from [levels.md](levels.md) §4, which
  exists so a quiet instrument does not get a near-zero denominator. Here it
  makes a series that has never been updated look like a real but tiny one
  rather than an obvious error.
- A zone built on it is **0.0bps wide**, so `dedupe` merges every pivot for an
  instrument into one level. Production holds twelve daily levels whose origin
  reads `pivot:PC+pivot:PH+pivot:PL+pivot:PP+pivot:R1+pivot:R2+pivot:R3+pivot:S1+pivot:S2+pivot:S3`
  - all ten prices collapsed into a single point.
- `check` returns early on `if not vol.warm`, so they are never tested against
  price at all. **Every pivot level in production has 0.0 touches.**

571 pip levels against 14 pivot levels, and 514 of the pip levels have been
touched. The comparison the module was written for has never been possible.

**Why this matters more than a dormant feature.** `pivots.py` states its own
purpose:

> **No look-ahead, at all.** A pivot for today is fully determined by
> yesterday... That makes them a clean control: **if PIP levels do not
> outperform pivots, the swing detection is not earning its complexity.**

That control has never run, and this week it would have been worth a great
deal. [prior.md](../research/prior.md) found the kNN prior contributes nothing
and `similarity.md` reportedly found the distance metric orders neighbours no
better than random - **but that document does not exist and never has**, so
treat the second half as unsupported. Measured live in
[learning.md](../research/learning.md), the kNN beats a one-feature floor by
3.1 points on 1,996 matched touches, so the cold-start mechanism is not dead. **A
pivot is on the chart before the first touch**, which is the same problem
solved without borrowing anything.

**The fix is small.** Either give the session names a volatility series, or have
a pivot read the volatility of the bar interval it is derived from - `1d` for
daily, `1w` for weekly, both of which exist and are warm (`btc/1d` reads 136.8
bps against the floor's 0.05).

**Then run the control**, and target magnitude rather than direction:
[magnitude.md](../research/magnitude.md) found `expected_push` is the only
component in this project to beat its null, ordering realised profit 7.5x from
bottom decile to top, while every directional claim reduces to `side`.

## 0e. `edge` is measuring `side`, and the honest version is a coin flip

**Measured on 2026-08-17, in [prior.md](../research/prior.md).** The most
consequential finding so far and the one that needs a decision rather than more
work.

`Memory.neighbours()` filters by side, so the kNN prior is side-conditioned.
`Memory.base_rate_for(feed, interval)` is not. So `edge` subtracts a side-blind
baseline from a side-aware estimate, and most of what survives is *which side
price arrived from* - which is why the published edge agrees with "assume the
level holds" **89.8%** of the time.

Give the baseline the same side conditioning and the remainder predicts
direction at **51.8%, AUC 0.520**. The level's own record and its twelve
nearest neighbours, together, are a coin flip.

Meanwhile a per-(feed, interval, side) base rate - counting, nothing else -
ranks **best of everything at AUC 0.741**, ahead of the composite that costs a
kNN scan over every stored touch.

**The decision this forces.** Redefining `edge` honestly is four lines and
would nearly silence the channel: at `MIN_EDGE = 0.10` the honest edge passes
43% of calls at 51.2% direction. A system that correctly says nothing is not
obviously better than one that says something slightly wrong, and which of
those this project wants is a judgement about the product rather than a
measurement. **Make it deliberately.**

What follows if the honest version is adopted:

- ~~`Memory`, `Features.distance` and the kNN can be deleted~~ - **withdrawn**,
  see [learning.md](../research/learning.md). The `similarity.md` this rested on
  does not exist in the tree or in git history, and the live bench has the kNN
  3.1 points of edge ahead of a one-feature floor over 1,996 matched touches.
- The published directional estimate becomes the side-conditioned base rate.
- **Magnitude and risk are untouched and untested.** `expected_push`,
  `risk_vol` and `reward_to_risk` are separate claims. The system may be useful
  for *how far* while having nothing to say about *which way*, and nobody has
  measured that. It is now the most valuable open question in the project.

## 0f. The `reward_to_risk` gate refuses 85% of calls to gain nothing

**Re-verified on 2026-08-27 against the live journal** - see
[replay.md](../research/replay.md), "Re-verifying the `reward_to_risk` gate".
The re-check confirmed the direction and substantially softened the claim
below, so read this first.

In R at a 0.5v stop, over 47,676 production touches joined to the signals that
produced them: 0.908 ungated, 0.868 at the live 1.2 threshold, 0.834 at 2.0.
The gate keeps 0.868R and rejects 0.915R, and gets monotonically worse as the
threshold rises.

So the direction holds and **the magnitude does not**: 0.047R, the same order
as the three direction gates removed the same day and called noise. The
original figures below were computed on realised *push* rather than R, and
push is distance, not profit - it scores a large move against the trade as a
good outcome.

**The case for removal is volume, not quality.** It refuses 40,421 of 47,676
calls to gain nothing and lose a twentieth of an R. A filter discarding six
trades in seven has to earn that.

**The mechanism below did not reproduce.** It predicts the top RR decile
excursing *less*, being built on a tighter stop. It excurses more - 0.960v
against 0.812v - and the ratio's distribution is badly behaved besides, the
bottom decile all zeros and the top reaching 12,772. The effect is real; this
explanation of it is not supported.

### The original 2026-08-17 measurement, kept for the record

**Measured in [magnitude.md](../research/magnitude.md).** Read with the
correction above: these are push figures, not R.

`actionable` requires `reward_to_risk >= MIN_REWARD_TO_RISK`. On 11,113 calls:

| | mean realised push |
|---|---|
| every call, no gate | **+0.496** |
| gated at RR >= 1.0 *(live)* | **−0.268** |
| gated at RR >= 2.0 | −0.614 |

And end to end: the 9.9% of calls that pass every gate return **−0.151**, while
everything the gate **rejects** returns **+0.569**. It selects a losing tenth
out of a winning population.

**The mechanism.** `reward_to_risk` is `|net_push| / risk_vol` and correlates
+0.571 with its numerator but **−0.359 with its denominator**. A high ratio is
substantially a *small* `risk_vol` - a tight zone, so a close stop. Top-decile
RR calls carry `risk_vol` 0.968 against 2.279 in the bottom decile and are
**stopped out 44.8% of the time against 29.1%**.

`Level.stop_for` already states the principle being violated: *"a stop inside
it is a stop inside the noise - it gets hit by the level working."* The ratio
rewards precisely that.

**Order of operations matters here.** `expected_push` is also miscalibrated -
it understates by **3x**, 1.023 against a realised 2.992 - so the ratio is
understated by the same factor. Fixing the calibration *first* would triple the
number of calls passing a gate that loses money. Remove the gate, then fix the
number.

**What to keep.** `expected_push` orders realised profit **7.5x** from bottom
decile to top and beats its null on rank correlation (+0.072 against +0.029) -
the first component in this project to beat the cheap alternative. It is
currently used mainly as an input to the ratio doing the damage.

**What to rebuild.** `risk_vol` has a measured correlation of **+0.006** with
realised adverse excursion. It is placed by zone geometry and that geometry
knows nothing about how far price goes against the trade. `excursion_vol` is
already recorded on every touch, so the data to derive a real stop exists.

## 0z. Two things found on 2026-08-14, both ahead of everything below

The two learning-path bugs from the same day are **fixed** - the silent
`journal.read` clamp that starved `facto.dataset`, and the unscaled features
that diverged the FM. Both accounted for in [handoff.md](../research/handoff.md). Neither
touches the two items below, and the first of them now matters *more*: a fit
can finally see the whole journal, so nothing but the warning below stops it
drawing 9,000 examples from one afternoon.

**The outcome rate needs explaining before any fit** - *the fourth route was
found; the rate itself still needs re-measuring.* The journal recorded 976
outcomes in one hour and 8,411 in six, against 76 the previous day, and the
guess was right: there was a fourth route to over-counting that the three touch
fixes did not close. It was `observe_bar` running the touch check at its own
interval during replay, which item 1 has now split out. On production
`own_touches` fell from 171 to 0.0.

**Re-measured on 2026-08-14 after the split, and it is not fixed.** 18,228
outcomes over 20.4 hours is **895/hour**, against the 976/hour that raised this
item; the three most recent full hours were 2,290, 2,257 and 2,285. Splitting
`observe_bar` fixed the *per-level* inflation - `own_touches` fell from 171 to
single figures - and did not touch the rate. Those were two problems wearing
one symptom.

The consequence this item exists for is therefore unchanged and now measured:
**200 consecutive outcomes accumulate in a median of 4.9 minutes**, fastest 1.1.
`MIN_EXAMPLES` is reached from five minutes of one afternoon, which is not a
spread of market conditions and not the dataset progressive validation assumes.

They are concentrated as well as fast. Of the last 5,000: `sol` alone accounts
for 2,430, and 3m and 5m for 4,305 between them, against 10 on 4h and none on
the daily or weekly. So a fit would learn one instrument on two fine
timeframes over one afternoon and report it as a model of everything.

**So `fit` stays gated, and the fourth route was not the last one.**

**Investigated, with one hypothesis refuted and one candidate measured.** The
re-arm hole is *not* it: `check` sets `waiting = contains(price)` after a
resolution, which looked like it bypassed `REARM_VOL`, but a reproduction
oscillating across a zone edge produced one resolution rather than dozens - a
small oscillation never resolves at all, it times out.

The candidate is **price granularity**. sol carries the same volatility as btc
and eth on one eight-hundredth of the price, so its smallest quotable step is
0.0726v against btc's 0.0083v - nine times larger as a fraction of a typical
move, and a fifth of a minimum-width zone. Price steps across a sol zone in
five ticks where btc needs forty. Numbers and the proposed remedy in
[levels.md](levels.md), "Price is not continuous, and the zone floor assumes it
is".

**Checked against a price gradient, and it is broader than sol.** Of eight
instruments, six have a tick worth more than a third of a minimum-width zone
and two - ADA and LTC - have a tick **larger than the whole zone**. The tidy
law is wrong though: tick-in-volatility against price fits a log-log slope of
−0.33, not the −1 that proportionality predicts, because exchanges set tick
sizes in decade steps. ADA at $0.18 is worse than SOL at $75.

So it cannot be predicted from price and has to be measured per instrument.
**Before adding any cheap instrument, measure its tick in volatility units** -
ADA today would be a sixth of the zone it is supposed to sit inside.

Still a candidate for the *rate* specifically: the granularity is measured, the
causal link to sol's 2,430 outcomes is not.

**The fix is shipped and unverified**, which is the open loop. `Level.zone` now
takes its floor as the larger of `MIN_ZONE_VOL` and six ticks, with the tick
read off a low quantile of observed changes - measured effect ADA 8.6x, LTC
6.9x, SOL 4.2x, btc and eth untouched. All of that measures *zone width*.
**None of it measures the outcome rate**, which is what the change was for.

So the next step is the same measurement that opened this item, run again after
the fix has been live long enough to matter:

```bash
sudo docker exec -i till-infinity python -c "..."   # outcomes per hour, by feed
```

What would confirm it: sol's share of outcomes falling from its half of the
total, and the per-hour rate dropping from ~895. What would refute it: the rate
unchanged, which would mean the zones were never the reason and the cause is
still unfound - the third time that has happened on this item, after the
re-arm hypothesis and the `observe_bar` split.

Do not treat wider zones as the answer until the rate says so. Widening a zone
also *reduces* touch counts mechanically, so a fall in the rate is necessary
evidence rather than sufficient - the question is whether the remaining touches
are better, and that needs the hold rate beside the count.

The older examples remain unusable regardless: recorded under the inflated
counts, and the pre-fix journal calls direction correctly 99.9% of the time
because a level's history and its next outcome were the same move counted
twice. `fit(since=)` exists for exactly this boundary. Do not fit across it.

**~~Agents have never woken~~** - done, and it was neither of the suspects. Not
the thresholds: left alone for thirty minutes the gate fired on its first
window, on 94,311 messages, naming usdcnh, nzdusd and usdchf. **It was the
window never closing.** `AGENTS_WINDOW_S` is 1800 in production and every
deploy restarts that timer, so on a day with deploys more often than every half
hour the gate never runs at all - which the "watch rather than act" note below
had predicted and nobody had connected to this item.

The analysis then died on `tool_calls_limit of 12 (tool_calls=14)`, a budget set
when six instruments were tracked and never revisited at fourteen. Raised to 32,
since the failure discards a whole judgement rather than truncating it. The
wake gate also now reports its closest approach at INFO rather than DEBUG, so a
gate that declines can be told from one that never ran.

Full account in [agents.md](agents.md), "Why agents appeared never to wake".
Still to confirm: that a window survives end to end now, which needs half an
hour without a deploy.

## ~~0a. Put 1m back on the level set~~ - done, and the detour is the lesson

1m was removed on 2026-08-14 to buy memory, and put back the same day once the
memory was actually measured. Keeping the whole shape because the mistake is a
better guide than the fix.

**The reasoning for removing it was wrong, and it was wrong in a way that
looked rigorous.** Two measured points - 42 series at ~232MB, 112 at ~400MB -
fitted a tidy 2.4MB per series, and that line predicted the failure. It was
still attribution by correlation: more instruments means more quotes per
second, which is what actually grew. Profiling the engine directly put its
retained structures at **0.15MB per series**, sixteen times smaller, so
dropping 1m from fourteen instruments saved about **2MB of a 400MB process**.
It changed no bus traffic at all, since `prices` collects 1m regardless.

**The memory was in the agents watcher.** It held every message of a
thirty-minute window - **101,297 messages, 199MB**, about half the resident
size at the moment of the kill - in order to derive fifteen triggers. The
window is bounded now at 20,000 messages (~40MB) and reports what it dropped.

Worth carrying forward: a curve fit through two points will happily predict the
thing you already saw while pointing at the wrong cause. The profiler took five
minutes and disagreed with it immediately.

**The window is streamed now**, not bounded: `Window` folds each message into
the running answer and keeps none, so the 101,297-message window that cost
199MB costs 464 bytes. `interesting()` folds a sequence into the same
accumulator, so there is one implementation rather than two that could drift.

**Still open:** swap does not exist, which is why an overshoot is a kill rather
than a slowdown - and that does not improve on a bigger box, it just gets
harder to reach.

## 0b. Three found on 2026-08-14 while tracing the silent channel

Ordered by what is holding back the most. All three are documented with their
measurements in [levels.md](levels.md).

**~~The spread cost charges zero on every call~~** - *resolved by item 1, watch
it.* `cost_of` reads a window filled by `observe_quote` only, and every recorded
call used to come off the bar path before any quote had landed, so the window
was empty and the charge a true zero - not a rounding artefact. Splitting
`observe_bar` moved when calls happen, and production now records a non-zero
`cost_vol`. Worth confirming over a longer run than the half hour it has had.

The measured charges are worth carrying in your head, because this gate is not
one threshold: 0.003v on btc against 2.5v on gbpusd 3m, so it is nearly free on
crypto and close to absolute on FX intraday. `STRUCTURES_CHARGE_SPREAD=0` turns
it off for comparison, and says so in the log while it is off.

**~~`risk_vol` is 0.0 on every recorded call~~** - done. `vol` was an optional
argument to `infer` with a zero fallback, so the risk geometry was something a
caller could forget, and all three callers did - each with `vol` right there in
scope. `reward_to_risk`, documented as the number that decides whether an edge
is worth taking, was therefore identically zero on every call ever journalled.
It stayed invisible because nothing gates on it and because zero reads as a
number rather than as an omission.

`vol` is now required rather than more carefully defaulted, so the next caller
cannot repeat the omission quietly. Both numbers are real: over a gold warm,
`risk_vol` on 16 of 16 calls and `reward_to_risk` spanning 0.45 to 3.12.

**And now gated.** `actionable` requires reward-to-risk ≥ 1.0 - a break-even
rather than a preference, since below it the predicted move is shorter than the
stop behind it. On the ratio and never on `risk_vol`, because risk is in each
timeframe's own units and 0.90 is $0.77 on 15m gold against $24.76 on the
daily; only the ratio travels. Measured cost: **13 of 35** otherwise-actionable
calls suppressed across gold, btc and eurusd, mostly large moves sitting behind
larger stops. Detail in [levels.md](levels.md), "The risk gate, and why it is a
ratio".

Raising it above 1.0 is the part that is a policy about capital rather than a
property of the model - the same argument as sizing in item 3 - and wants
outcomes behind it rather than a number that sounds professional.

**`0.08` was never derived from anything.** Not in the commit that introduced
it, not in the docs. It is the number currently separating signal from silence,
with the median call sitting five thousandths under it. It sits near the 97.7th
percentile of its own input - 2.3% of calls reach it - which is a defensible
place for a gate to be and not a chosen one.

Deriving it from the journal was **tried and does not work yet**: the pre-fix
data calls direction correctly 99.9% of the time at every level of `|edge|`,
against ~78% for independent series with those marginals, because inflated touch
counts made a level's history and its next outcome the same move counted twice.
Detail in [levels.md](levels.md), "The attempt to derive it, and why it failed".

So this waits on post-fix data. Then make it a rolling quantile of realised
edges rather than a constant - the same instinct as [score.md](../research/planned/score.md)'s
thresholds - rather than picking a new number by hand.

## 0c. Left open by the 2026-08-14 fixes, in the order they would bite

**~~Guard every pickled slots dataclass~~ - the important half is done, the
cheap half is not.** `_schema` now derives the fingerprint by walking the
package rather than from a hand-written list of seven, so a field added to any
of the twenty-seven persisted dataclasses invalidates the saved state and the
service starts cold instead of crashing on it (`98e45be`). That was the root
cause: the list existed, `Volatility` was not on it, and using it correctly
required knowing it was there. It fired correctly on its first real test -
`schema 25296b265b0805a0, this is c6229bdc019bc469 - starting cold`.

What is left is belt-and-braces: fourteen of those classes still have no
`__setstate__`, so if state is ever loaded that the schema did *not* catch, the
read still raises. The schema stops bad state being loaded; a `__setstate__`
stops a crash if it ever is. Lower priority now, and it wants one shared mixin
rather than a fourth hand-written method.

**Confirm the engine fixes on production - mostly done, one number left.**
Measured over 87 outcomes on 2026-08-14:

| | before | after |
|---|---|---|
| instant | 47.8% (n=18,709) | **9.2%** |
| back checks | 1, all history | **30** |
| breaks | 43, all history | 3 in two hours |
| bus drops | 372/min | 0 |

The back check number is the one to notice: it was not low because back checks
are rare, it was low because `expire`'s resolutions were discarded and
`broke_at` is what makes a retest detectable.

**Still unread: whether negatives went to zero.** They went the wrong way first
- 1.7% before the clock fix, 5.7% after it, because stamping a bar at its close
puts the *forming* bar in the future. `e02e7d7` clamps to now and has no sample
yet, because it deployed into the cold start above. Read it next sitting.
Until then item 4's gate stays shut.

**The box is re-learning from cold.** The schema change was correct and cost the
accumulated touch history and kNN memory. Levels re-form from stored bars, but
the per-level statistics that `quality_l` depends on start from nothing, so the
strength work below has no history behind it for a while.

**Replace `Level.strength`, do not merely stop multiplying it.** Removing
confluence breadth from `Zone.strength` was the cheap half.
[strength.md](../research/strength.md) finds the composite loses to its own best term in
every run - AUC 0.548 against 0.648 for the level's own same-side record - and
this number is not only reported: `reactions.py` passes it into the model as a
feature. Mixing one signal that works with three that do not is diluting the
feature the model is given. The proposed `quality_l` is unfitted and beats it on
all four runs. Prerequisite is touch counting being trustworthy, which is item 0.

**One horizon serves every timeframe.** `Tracker.horizon` is 3,600 seconds
whatever the interval, so 1,054 of 1,270 chops in the absorption replay are 4h,
1d and 1w touches labelled by the clock rather than by price. A daily level
cannot resolve at all inside an hour. Make it a multiple of the interval, the
same argument as evidence half-life in [levels.md](levels.md) §10b.

**`Touch.energy` divides by `approach_vol` with no floor** and reaches 4.6e10
in a replay. Nothing consumes it yet, which is the only reason it has not
already poisoned something - the same shape as the unbounded features that
diverged the FM.

**Record press depth on every touch.** [absorption.md](absorption.md) measures
it non-zero on 68.8% of real interactions against `excursion_vol`'s 25.2%; the
quantity [behaviours.md](behaviours.md) nominates is zero on 82.7% of touches,
so the thing being modelled is mostly absent. Cheap, and it is a measurement
input rather than a feature.

**~~`0.08` is now derivable~~ - derived. See [edge.md](edge.md).** The blocker
was inflated touch counts making a level's history and its next outcome the
same move twice, which showed as the direction being called correctly 99.9% of
the time at every level of |edge|. Fixed, and it now reads 71.1%, so the
measurement means something.

Two results, one of them against what this file used to say:

- **0.08 sits inside a flat region and should be 0.11.** Below roughly 0.11,
  direction runs 54-61% - a coin flip with a push near zero - and at 0.11 it
  steps to 75%. Six instruments out of six show the same step. The gate also
  is not where it was believed to be: on corrected data the median |edge| is
  0.1373, so 0.08 is *below* the median and passes 69.6% of calls, against the
  2.3% recorded in [levels.md](levels.md).
- **Keep it a constant. Do not build the rolling quantile this item used to
  ask for.** Against the constant that passes exactly the same number of
  calls, the rolling rule is four to ten points worse on direction at every
  selectivity tried, and 9 of 24 cells never reach the 50 calls it needs.
  `edge` is a difference of two probabilities and so already means the same
  thing on every instrument; normalising it per cell destroys that. The
  instinct is right for anything in volatility units and wrong here, which is
  the distinction worth keeping.

**Can it be computed rather than chosen? Yes, and it buys maintenance rather
than accuracy.** Accuracy-targeting - the lowest |edge| whose *realised*
accuracy clears a target, re-estimated from outcomes and kept global - looked
like a clear win over the whole replay, +3.6 to +5.1 points. Scored on the
second half alone at matched volume it is **equal to a constant three times out
of three**. The earlier margin was the rule riding the warm-up drift; its own
threshold fell from 0.26 to 0.06 across the replay.

So it is worth building, for a different reason than the one this item
originally gave. `0.08` was defensible when set - 97.7th percentile, passing
2.3% - and today passes 69.6% without anyone touching it. A constant is as good
as the adaptive rule *provided somebody keeps re-deriving it*, and nobody did.
The evidence-scaled form `z * sqrt(p(1-p)/n)` is the more principled shape and
has nothing to work with today - see the item below, which is its prerequisite.

Not yet done, and deliberately: the constant is unchanged in code. The
measurement is a bars-only replay, and today established twice that the quote
path behaves differently enough to overturn a replay result. Re-derive on
production once there are enough post-fix outcomes, then move it.

**~~Let `k` reflect how much similar history there actually is~~ - measured
first, and the radius must not be built.** The plan was a similarity cutoff so
the neighbour count would mean something. The cutoff was measured before being
built and the measurement killed it: **the nearest twelve neighbours predict no
better than twelve at random** (72.9% against 72.7%), and pairwise agreement
*rises* with distance across every control - within a cell, across cells, and
restricted to pairs more than a day apart. `Features.distance` does not order
neighbours by relevance. Full numbers in [edge.md](edge.md) §6.

The kNN prior still works - twelve neighbours call the direction correctly 73%
against a 51% base rate - but the similarity is not what does it. A pooled vote
of recent touches captures the market's prevailing direction, which is the same
dependence that makes any two touches agree 57-62% a day apart.

So the open item is the **metric**, not the cutoff: which features belong in
`Features.distance` and with what weights is an empirical question nobody has
asked, and until it is asked a radius would only restrict the pool to
neighbours carrying no advantage. Two smaller consequences stand on their own:
the `1/(1+d)` weighting in `prior` gains 0.9 points over unweighted and still
loses to the farthest twelve, and the alert's "+12 similar" is decorative
wording for a count that is always twelve.

Original reasoning, kept because the three consequences are still true:

- **`Inference.neighbours` is not an evidence count**, though it reads as one
  and is printed in the alert as "+12 similar".
- **The shrinkage cannot weaken when it should.** `prior` shrinks toward the
  base rate with `weight = len(found) / (len(found) + PRIOR_WEIGHT)`, so twelve
  distant strangers are trusted exactly as much as twelve close matches.
- **The evidence-scaled gate has nothing to bite on.** Measured over 2,003
  calls, the effective count runs 12.5 / 13.8 / 15.3 across the quartiles, and
  a rule of the form `|edge| >= z * sqrt(p(1-p)/n)` is therefore almost a
  constant in disguise. See [edge.md](edge.md) §4.

The change is a similarity radius: take neighbours within a distance cutoff, up
to `k`, rather than the nearest `k` unconditionally. `Features.distance` is
already scale-free, so a cutoff means the same thing on every instrument. Then
the count means "how much genuinely comparable history exists", the shrinkage
follows it honestly, and the evidence-scaled gate becomes testable.

Pick the cutoff by measuring, not by choosing: the distance distribution of
neighbours that did and did not predict correctly will say where similarity
stops carrying information.

**Make the agents service better: faster, more accurate, and pointed at
meaning rather than at numbers.** *Found on 2026-08-15 while reading the
alerts: **news can never wake the agent**, and the news specialist never runs.*

`Window.observe` dispatches on `SIGNALS`, `QUOTES` and `EVENTS`. `ARTICLES` is
in `TOPICS` and subscribed to, and there is no branch for it - so a headline is
readable once the agent is awake and is never the reason it wakes. `BARS` is
subscribed and unhandled too. Every trigger is therefore a price trigger: the
loudest structures signal per feed, the worst spread, and calendar releases
that printed.

And only one role runs, `DEFAULT_ROLE = RISK`. `MACRO` - the role whose whole
lens is the calendar and "several independent outlets converging on the same
story" - is never instantiated in production. That is why every alert in the
channel is a spread, a stale quote or a divergence.

**Wiring `ARTICLES` to a trigger on its own would produce noise**, and today's
research says why: [news-dedup.md](news-dedup.md) found the corpus contains no
observation of independent outlets converging - 94 of 105 duplicate groups are
one outlet counted twice by our own collection - so `MACRO`'s headline lens is
looking for something the data does not contain. And symbol normalisation is
unbuilt, so half the corpus cannot be routed to an instrument at all.

So the order is the one [news-models.md](../research/news-models.md) §2 already gives:
symbol normalisation, then keyword matching against TradingView's tagged rows,
then a headline trigger, then the join with price. Wiring the trigger first
inverts it. Today the roles read prices and structures
and describe what changed. The more valuable half is the news - what a headline
*means* and what intent sits behind it - with the technicals brought in as
corroboration rather than as the subject.

Concretely, in the order the groundwork exists:

- **Intent and meaning from the news, not keywords.** [news-models.md](
  ../research/news-models.md) ranks what fits on this box, and [news-dedup.md](news-dedup.md)
  settled the first question on it: deduplication is hygiene, not signal, so
  the restatement count is not the feature. Symbol normalisation (§2 there) is
  the real prerequisite, because nothing routes without it and half the corpus
  is untagged.
- **Then join the technicals to it.** A headline that means something about
  the dollar is worth more when EURUSD is sitting at a level with a record -
  which is exactly what `agents/data.py` already exposes. The join is the
  product; either half alone is what we have now.
- **Faster.** The window is the scarcest resource in the system. See
  [bandits.md](../research/bandits.md): choosing which instruments deserve the
  ten trigger slots is the one genuinely bandit-shaped problem here, and the
  incumbent policy is "first ten past the gate".
- **More accurate.** The spread finding on 2026-08-14 reported a reading "at
  the historical maximum" against a maximum computed over a window containing
  it. That class of error is a tool-framing problem, fixed in `05a0abf` for
  spreads; the other tools in `agents/tools.py` want the same read-through.

**The directional call does not beat "assume the level holds", and the feature
set is why.** Measured in [features.md](../research/features.md), and it is the
most serious finding of 2026-08-14 because it is about the premise rather than
the plumbing.

- **`side` alone predicts direction at 78.8%; all nine features together
  manage 77.8%.** Dropping side costs 26.6 points and drops the model to
  chance. Dropping any other feature costs nothing, and three of them are worth
  negative accuracy.
- **The trivial rule beats us at every gate.** A touch from above pushes back
  up: 77.7% against the edge sign's 71.1%, and still ahead at 0.08, 0.11, 0.14,
  0.20 and 0.30. The two converge as the gate tightens - 97.8% agreement above
  0.20 - so a high-edge call is nearly always just restating the trivial rule,
  and the disagreements are where it loses.
- **Generated features do not rescue it.** Pairwise products are 3.3 points
  worse, a random Fourier basis 1.3 worse, target encoding neutral.

This explains the kNN result above rather than sitting beside it:
`Features.distance` is a metric over eight features with no directional signal,
so of course it could not order neighbours by relevance.

What it does *not* say: the gate still selects larger moves - mean realised
push rises from 0.73 to 1.83 across the same thresholds - and magnitude and
risk are untested. So the gate earns its place and the direction does not.

The next step is not a model. It is **what to measure at a touch**, because
nothing currently collected predicts direction beyond the side, and no amount
of modelling fixes that. Until then, `facto.Report` should carry "assume the
level holds" as a baseline alongside the two it already compares against.

**~~Decline the instrument and timeframe pairs that cannot support a level~~
- built, `ef7fa71`, with one thing to re-check.** Asked whether more
instruments can be added, especially crypto and indices. Resources say yes;
the model says *it depends on the pair*, and that is measurable before adding
anything.

The number that decides it is **ticks per zone** - how many price steps fit
inside a level's band. Price is supposed to enter a band, react, and leave. If
the venue's tick is a large fraction of a typical move, price cannot enter it,
only jump across, and every crossing becomes a touch. Measured on the
instance:

| pair | ticks per zone | |
|---|---|---|
| sol 3m | 2.5 | unusable |
| sol 1m | 2.7 | unusable |
| **audusd 1m** | **2.7** | unusable |
| sol 5m | 3.5 | unusable |
| nzdusd 1m | 4.1 | marginal |
| eurusd 1m | 5.9 | marginal |
| spx500 3m | 6.7 | marginal |
| btc 5m | 170.2 | fine |
| gold 15m | 109.7 | fine |

**It is not a crypto problem.** `audusd 1m` is as bad as sol, and six FX pairs
are marginal at 1m - coarse pip quoting does what a cheap coin does. It is also
not fixed by the zone floor: `GRID_ZONE_VOL` stopped the zone being absurdly
*wide*, which was making everything a touch; what remains is a zone only two or
three ticks across, which is the opposite failure and the one
`MIN_ZONE_TICKS` was originally added for. Both ends are bad, and the honest
answer is that the pair cannot be modelled at that resolution.

So: **form no levels where ticks-per-zone falls below a floor**, log it once,
and let the coarser timeframes for that instrument carry it. sol is fine at
15m and up; it is noise at 1m and 3m. This is the same shape as `trading()` -
refusing to produce rather than producing something meaningless.

Then the answer to "can we add more" becomes mechanical:

- **Indices are safe.** spx500 and us100 sit between 6.7 and 36 ticks per zone.
  More of them should behave.
- **Cheap crypto is not**, at fine timeframes. ADA at about \$0.18 was already
  measured with a tick larger than the whole zone, which is worse than sol.
  With the gate they would simply carry fewer timeframes rather than poison
  the sample.
- **Measure before adding, not after.** `Engine.supports(feed, interval)` is
  the check and it now runs itself: `reform` forms nothing for a pair below
  `MIN_TICKS_PER_ZONE = 4`, drops whatever was already formed on that geometry,
  and logs it once.

**What it declines today, and the one thing to re-check.** Eight of fifteen
sampled pairs: sol at 1m, 3m and 5m, and audusd, nzdusd, eurusd, usdcad and
usdchf at 1m. sol keeps 15m and coarser, so the instrument is not lost, only
the resolutions it cannot carry.

More than the observed widths suggested, because `supports` judges the **floor**
zone rather than the widened one - wicks make an established level roomier, but
a new level gets the floor and the question is whether to form one at all.

**The FX pairs were assessed over a weekend, with those markets shut.** Their
measured rates say nothing - eurusd produced 4 outcomes in 24 hours, which is a
closed market rather than a quiet one. Re-check those five on a weekday: if
they behave, the floor is too high for FX and should come down. Erring toward
declining in the meantime, because losing a good pair costs alerts visibly
while keeping a bad one poisons the sample invisibly - sol alone was half of
every outcome in the journal.

Resource headroom, so the other half of the question is answered too: memory
257MB of a 2.6GB cap, disk 235GB free at about 461MB a day of quotes, no bus
drops. **CPU is the binding constraint**, at 76.4% of a 150% allowance -
doubling the instrument count would reach the `--cpus 1.5` ceiling before
anything else complained.

**Quotes have no retention, and they are three quarters of the prices file.**
`prices prune` covers bars only, and the reason written into `store.prune` was
wrong in both halves: quotes are not bounded by `dedupe_quotes`, and bars are
not what grows. Measured on the instance:

| object | size |
|---|---|
| quotes | 333.2 MB |
| quotes_series_ts | 212.3 MB *(index)* |
| quotes_feed_ts | 191.3 MB *(index)* |
| bars | 51.7 MB |
| bars_series_ts | 36.2 MB *(index)* |

Quotes are 76% of the file and their two indexes cost more than the rows.
`dedupe_quotes` skips a quote whose price is *unchanged* - it lowers the write
rate in a quiet market and deletes nothing. On the instance quotes spanned
39.3 hours, which was the **entire age of the database**: not one had ever been
removed, at roughly 64,000 rows an hour, about 450MB a day.

The first prune ever run dropped 27,004 bars and a VACUUM took the file from
787MB to 567MB, so the bar half is now handled. The quote half is not.

Two things to decide together, because they pull in opposite directions:

- **Retention** would cap the growth. 450MB a day is nothing against 242GB, so
  this is no longer urgent - but unbounded is still unbounded, and the indexes
  make each row cost triple.
- **The item below wants the opposite**: microstructure at a touch is
  unanswerable precisely because quote *history* does not survive. Cutting
  retention harder makes that worse.

The resolution is probably that they are not in tension at all. Snapshotting
what a touch needed - spread, dispersion, staleness - into the touch itself
makes the raw quotes disposable, which is what allows a short retention rather
than what argues against it. Do that one first.

**Snapshot the microstructure state into a touch when it opens.** The
question "what should we measure at a touch" is answered in
[research/features.md](../research/features.md) for everything derivable from
bars: nothing predicts direction beyond `side` except the level's own record,
now added as `up_rate`. The candidates that remain are microstructure, and they
cannot be tested - not because they were tried and failed, but because there is
no history to try them on.

`quotes` holds **8.6 hours** against years of bars. It is a rolling recent
window, so a quote-driven replay yields a handful of touches where the bar
replay yields two thousand. That is also the concrete reason every result in
`research/` is bars-only, and why a replay has twice disagreed with production.

Retaining every quote is the wrong fix - expensive, and mostly noise. Write the
state into the touch instead, at `Tracker.begin`, exactly as `up_rate` now
records the level's record:

- spread in volatility units at the moment of contact, not the windowed median
  `cost_of` already keeps
- cross-venue dispersion, which `features.Book` computes for the anomaly
  detector and never shares
- staleness of the freshest venue, and how old the quote driving the touch is

All three are already computed somewhere in the process and thrown away. Then
the question is answerable from the journal in a few weeks rather than never,
and the two weak candidates already measured - venue dispersion at +3.1pp
within cell over 11 of 13 cells, volume at +2.3pp over 9 of 13 - get a sample
large enough to settle them.

Order flow proper stays out of reach: there is no book, which is the same wall
[absorption.md](absorption.md) hit. That one is a data-source question, not a
retention question.

**Form levels at momentum turns, not only at price turns.** Asked directly:
are we already doing this? **No.** `momentum`, `velocity` and `acceleration`
appear nowhere in the package. The two formations that exist both segment on
*price*:

- `pips.points` picks bar extremes and waits `confirm` bars to call one a turn.
- `runs.points` ends a run when price has retraced from its extreme by
  `RUN_SWING_VOL` volatility units - displacement, not rate.

The nearest thing to momentum is `Engine._speed`, one bar's change over the
previous in volatility units per bar. It is computed only at the instant a
touch opens, becomes `Features.approach_vol`, and is used nowhere else.

The proposal is a third formation and it is well posed: segment the series by
where the **rate of change** turns rather than where price does, and take the
last bar before that turn as the *momentum origin* - the same role
`touch.origin` plays for a reaction, the point where the leg stopped
extending. Momentum turns lead price turns, so a level drawn there sits where
the move began losing its push rather than where it finally stopped, and those
are different prices.

It is cheap to test and the machinery is already built for exactly this
comparison. `Engine(formation=...)` takes `pip`, `run` or `both` and
`levels.form` consumes whatever `Point` objects it is handed, so a
`momentum.points` producing the same shape drops in beside the other two. Then
`research/harness/` replays all three over one history and the outcome
machinery says which set price respects - the same question
[levels.md](levels.md) leaves unresolved for pip against run, and which
[strength.md](../research/strength.md) showed was measured on a broken
volatility denominator anyway and needs redoing regardless.

One caution from what is already measured, and it cuts both ways.
[research/features.md](../research/features.md) found `approach_vol` predicts
nothing about direction once side is known - so momentum *at a touch* is not
informative. That is not evidence against momentum-derived *levels*: the claim
here is about where a level should be drawn, not about what predicts once
price arrives. But it is a reason to test the formation on outcomes rather than
assume the idea transfers.

**Two smaller ones.** `yahoo.to_bars` converts an entire frame and then keeps
only the last `bars` of it; slicing first is much faster but changes the count
when rows are dropped as NaN, so it needs a decision rather than a patch. And
the agents' spread finding reports a reading as being "at the historical
maximum" while computing that maximum over a window *containing* the reading -
true by construction, and it belongs in the tool's framing rather than the
prompt.

**A deploy is an outage.** Every push restarts the container, including
docs-only ones, and four this afternoon each cost a backfill. `e4b0f3f` stops a
backfill starving the consumer, which shortens it, but does not make a restart
free. Batching pushes is the cheap discipline; not rebuilding on a docs-only
change is the real fix.

## ~~0d. The backfill nobody had run~~ - done on 2026-08-15

Found while running §6a. `1d` bars existed for **six** feeds and for none of
the eight added during the instrument expansion on 2026-08-14. The deep pull
was simply never re-run after the config grew.

```bash
till-infinity prices backfill --interval 1d   # then --interval 1h, --interval 15m
```

**Done on 2026-08-15, and it changed an answer.** [turns.md](../research/turns.md)
went from 131 turns to 310 and from "does not separate from chance" to **AUC
0.595, interval 0.540-0.654**. The method did not change at all; only the
sample did.

**A correction, because the first version of this item was wrong.** It claimed
the daily backfill would also give [cycles.md](../research/cycles.md) the span
it lacked. It does not: cycles is limited by *fine-grained* history, because
the touch replay reads 1m/5m/15m/1h and never touches a daily bar. Daily bars
feed the cycle *label*, not the touches being labelled.

What actually helped cycles was noticing, while checking that claim, that
**spx500 and us100 had 632 days of hourly data where every other feed had
15-21**. Backfilling 1h and 15m across all fourteen took the touch sample from
1,862 to **10,483** and the cycle count from 26 to 73:

| interval | before | after |
|---|---|---|
| 1d | 6 feeds | 14 feeds, 6-20 years |
| 1h | 15-21 days, 632d for two indices | **208-1,045 days**, all 14 |
| 15m | 6-7 days | **52-273 days**, all 14 |

455k bars to **1.56M**. The lesson worth keeping is that the gap was invisible
because live collection was working perfectly at the intervals the pipeline
consumes - nothing was broken, so nothing complained.

Three things worth keeping:

- **Re-run the harness after any backfill.** Every research document was
  measured off `touches.pkl`, which regenerates from whatever is in the store.
  The numbers in [features.md](../research/features.md),
  [models.md](../research/models.md) and [edge.md](edge.md) all moved.
- **A gap in collection depth is invisible from the outside.** Nothing alerted,
  nothing failed, and the live pipeline was healthy throughout - because the
  intervals it consumes were being collected. Only a research question that
  needed *history* rather than *freshness* surfaced it. Worth a periodic check
  of span per feed per interval rather than waiting for the next one.
- **Do not take a cross-venue median at cycle scale.**
  [cycles.md](../research/cycles.md) §2 found it destroys a path-dependent
  measure: venues sit at different levels and do not all report every day, so
  the median adds steps the instrument never took.

## ~~1. Split `observe_bar`: form from own bars, touch from the finest~~ - done

Every bar forms levels for its own interval; only the finest interval touches,
against every interval at once - the replay equivalent of `observe_quote`.

The documented trap was the wrong one to worry about. What actually bit is that
**"finest available" is not the globally finest series, it is the finest one
available *at that moment*.** Venues keep years of 1w and days of 1m, so a few
hundred bars per interval covers hours at 1m and years at 1w; pinning the check
to 1m left every earlier era untouched, 1w and 4h opened *zero* touches across
20,159 replayed gold bars, and their levels were pruned for never having been
visited. Twenty-one levels became four. The touch source now hands over as finer
history begins.

Measured rather than argued, on the same history: levels 20 → 21, touches median
2.0 → 2.9, max 11.1 → 14.0, none at or above 100 in either. Coarse levels
register interactions they previously could not see - 1d median 1.5 → 3.3, 4h
1.8 → 5.5, 15m 1.3 → 9.1 - and the absence of inflation is what says the trap
was avoided.

**On production the effect is what it was meant to be:** `own_touches` fell from
171 to 0.0, and the spread cost started charging for the first time. Alerts are
still gated by `0.08` above.

One casualty worth remembering: adding `_touch_eras` to `Engine` took structures
down on deploy, because state is a pickle and unpickling never calls `__init__`.
See [structures.md](structures.md) on persistence.

Detail: [levels.md](levels.md), "The live path is already fine".

## ~~2. Split `RUN_VOL` into arrival and departure constants~~ - done

`ARRIVAL_RUN_VOL` and `DEPARTURE_RUN_VOL`, equal at 0.5 because nothing yet says
they should differ. They answer different questions: the arrival threshold
decides where the level *is*, and being wrong moves every statistic the level
owns; the departure threshold decides how much of what followed counts as this
reaction, and being wrong changes one feature.

Each leg is now sabotage-checkable alone - disabling the departure rule fails
only the departure test, and the arrival test still passes.

## ~~3. Wire the measured spread into `cost_vol`~~ - done

Quotes carry `spread_bps`; the engine keeps a window of them per instrument and
charges the **median**, in volatility units, to every level call. A median for
the reason the consensus is one - a mean is dragged by the outlier it exists to
ignore. An exponential average was tried first and failed its own test: at a 0.1
weight a single hundred-fold print moved the charged cost tenfold, which would
have silenced a whole instrument until it decayed.

Some signals will now stop qualifying. That is the point of it.

Three further steps stand between this and anything resembling a buy/sell
decision, and they are listed so nobody mistakes a good model for a decision:

- **Calibration.** MAE says predictions are close on average; it does not say
  that when the model claims 80% it is right 80% of the time. Confidence is
  what any sizing rule consumes, so it has to be checked directly - bucket the
  predictions, compare claimed against realised.
- **Sizing.** `risk_vol` and `reward_to_risk` describe how wrong a call can be.
  Turning that into a position is a policy about capital, not a property of the
  model, and it belongs to whoever owns the capital.
- **Out-of-sample evidence.** Progressive validation gives this honestly by
  construction; it needs the examples.

`facto` sits *after* all three. It sharpens an estimate that first has to be
measuring the right quantity.

## 4a. The concentration gating `fit` was geometry, and is fixed

`sol` was 4,940 of the last 24 hours' 9,863 outcomes - half of everything -
which is what item 4 means by a fit learning one instrument and reporting it as
a model of everything. Measured per bar, so "more bars means more outcomes" is
removed:

| cell | outcomes per 1,000 bars |
|---|---|
| **sol 3m** | **582.0** |
| sol 5m | 429.9 |
| eth 3m | 159.2 |
| btc 3m | 62.8 |

A resolution every 1.7 bars on sol against one every sixteen on btc. That is
not a sampling problem and no stratification fixes it; it is the zone.

`MIN_ZONE_TICKS = 6` is a sensible floor while a tick is a small part of a
typical move. **On sol a tick is 0.378 volatility units**, so six of them is
2.27 - wider than `resolve_vol`, the distance a touch must travel to resolve at
all. sol's zone measured 2.268v against btc's 0.484v, 4.7 times wider in the
only units that compare, so it caught 4.7 times the price action.

The floor added on 2026-08-14 to stop price crossing a zone in a few ticks
over-corrected: it made the zone enormous instead. `GRID_ZONE_VOL = 0.75`
bounds the grid-derived part at half of `resolve_vol`, so the ladder alone can
never open a zone wide enough to resolve a touch. The filter's own uncertainty
and observed wicks may still exceed it - those are evidence about this level,
where the grid is a fact about the venue.

**Prediction, so this one is falsifiable unlike the last zone change.** sol's
zone half falls from 2.268v to 0.75v, three times narrower, so sol 3m should
drop from 582 per thousand bars towards roughly 200 - closer to eth's 159 than
to btc's 63, because sol's grid is still coarse, just no longer unbounded. If
it does not move, the tick is not the cause and this document is wrong.

Not verified on the replay: the local prices database holds no `sol`, so the
instrument this is about cannot be measured there. It has to be read off
production.

## 4. `fit(since=)` once 200 post-fix outcomes exist

No code needed. The counter restarts from the **2026-08-14** fixes, not the
13th's: examples recorded under inflated touch counts and a pooled base rate
describe a model that no longer exists, and half of everything recorded before
the 14th was a touch resolving at the instant it opened. Detail:
[structures.md](structures.md), "Examples have an expiry".

The count therefore starts from zero again as of `ddc7aec`, and at the corrected
rate - roughly half the old one, with the concentration on `sol` 3m and 5m
unmeasured since - 200 outcomes is a longer wait than the 4.9 minutes item 0
recorded. That is the point of the gate rather than a problem with it.

## ~~5. Run-formed levels - built, run, and answered~~ - done

`runs.py` and `Engine(formation="run")` exist; the comparison has been run.
Detail and the numbers in [levels.md](levels.md), "Built and run, 2026-08-14".

**The resolution claim holds** - 26 of 27 coarse run boundaries appear in the
fine set against 5 of 7 bar extremes, and that is now a test. **The outcome
comparison did not settle anything**: run formation lost 83.3% to 59.7% on gold
alone and won 82.2% to 79.5% across three instruments. A 24-point gap that
looked decisive was sample noise.

Both flaws are fixed: resolutions are drained *during* the replay through the
progress callback, so nothing is censored, and four instruments at 400 bars
raised the decisive samples from 36 to between 624 and 1,133.

**On hold rate, PIP still wins narrowly** - 81.6% against 77.9% - but now on
samples that mean something. **The merge is what earned its place**, and not
for accuracy: it finds twice the levels at a hold rate two points lower, and
agreement between the formations turns out to predict holding. See 5a.

Left open: `both` is not the default, and the pip-versus-agreement ordering is
unresolved on 50 interactions. More history would settle it.

## ~~5a. Merge the two formations rather than picking one~~ - done

`Engine(formation="both")` forms each way and merges; `lv.agree` keeps every
formation that found a level, so `origin` reads `pip+run` where they concur.
Merging rather than pooling the swings, so a bar extreme and a run boundary a
hair apart cannot form a level *between* them and lose which pass found it.

**Agreement predicts holding**, which is what the merge was for: a level both
passes find holds 80-83% against 75-77% for run-only, at every threshold
tested, on samples in the hundreds. It does not clearly beat PIP alone - that
comparison is unresolved on 50 interactions. Numbers in
[levels.md](levels.md), "Agreement between the formations is a real strength
signal".

Left deliberately: `both` is not the default. It roughly doubles the level
count for a hold rate two points lower, which is a coverage-for-quality trade
somebody should choose knowingly rather than inherit.

## 5b. Weak and strong, as a first-class notion

Nothing in the model currently says a level is *weak* except `strength`, which
is a continuous score mixing touches, agreement, recency and breadth, and which
is consumed nowhere as a decision. There is no point at which the system says
"this one is worth less" and acts on it.

Three sources of evidence were proposed for that judgement. **All three have
now been measured** ([strength.md](../research/strength.md)), and only one of them earns
its place:

- **What it has done - yes, and by a wide margin.** A level's own same-side
  record separates holds from fails by +32.8 points on corrected code, and the
  separation *grows* with the gap since the last touch (+25.1 at 20 bars or
  more), which answers the obvious objection that it is just measuring a
  grind. Point-in-time safe, since `SideStats` at contact holds only resolved
  interactions - but only trustworthy while touch counting is, so item 0 is a
  prerequisite rather than a nicety.
- **How it was found - no, and the earlier evidence was an artefact.** The
  agreement result in [levels.md](levels.md) was measured on the broken
  volatility denominator, and it **inverts** on the corrected one. Origin came
  out of the design. Status is unresolved rather than reversed, and either way
  it is not a validated input.
- **How many timeframes see it - no.** Confluence breadth does not separate at
  all: four runs, four orderings, AUC 0.45-0.51, bootstrap -2.2 [-6.3, +1.7].
  The 15%-per-timeframe multiplier it used to earn has been removed from
  `Zone.strength`, since that ordering decides what the agents are shown.

A fourth finding matters more than any of them: **the existing `strength`
composite loses to its own best term** in every run (AUC 0.548 against 0.648
for the record alone). Mixing touches, agreement, recency and breadth into one
number dilutes the one part that works with three that do not.

[strength.md](../research/strength.md) proposes a concrete `quality_l` built from the
record and experience only, graded *within* `(feed, interval)` - the grading is
load-bearing, since chart identity alone reaches AUC 0.586-0.608. It is
unfitted and beats `Level.strength` on all four runs. The open risks are the
quantile window, which leaks unless it is causal, and the trap classification:
with 12 breaks against 933 traps, counting a trap as a hold makes everything
read 99.8% and nothing separates.

Two places it should show up:

**In levels**, as a grade rather than a hidden float. The zone width, the
`|edge|` gate and the reward-to-risk floor could all reasonably move with it: a
strong level deserves a tighter zone and a lower bar, a weak one the reverse.
Today every level is gated identically no matter what is behind it.

**In the [score](../research/planned/score.md)**, which is where it matters more. The score is one
number per instrument and a level call is its main input, so a call from a weak
level and one from a strong level currently contribute the same. They should
not. The score's own thresholds are already designed as rolling quantiles
rather than constants, and level strength wants the same treatment - graded
against what strength has looked like recently, not against a number somebody
picked.

**The trap, and it is the same one as everywhere else here.** Grading levels by
what they have done and then measuring how well the graded levels do is
circular. The grade has to be formed from evidence available *before* the
interaction being judged, which is exactly what `as_of` and the journal's
copied-in context already exist to enforce. Do not skip it because the
arithmetic looks harmless.

## 6. Build the score

Designed in [score.md](../research/planned/score.md), not built: one number per instrument in
[-1, +1], three EWMAs, thresholds as rolling quantiles, transitions only.

## 6b. Let the constants adjust themselves

The pattern this project keeps rediscovering is not that a particular number
was wrong. It is that **hand-set numbers go stale and nothing notices**:

| constant | set to | what measuring found |
|---|---|---|
| `0.08` edge gate | a judgement | passed 2.3% of calls when set, 69.6% by 2026-08-15 - below the median |
| `HALF_LIFE` | 60 bars | optimum is 7-10 at every interval ([volatility.md](../research/volatility.md)) |
| `MIN_ZONE_TICKS` | 6 | opened a 2.27v zone on sol, wider than `resolve_vol` |
| `MAX_ZONE_VOL` | 3.0 | twice `resolve_vol`, so a touch could be born resolved |
| `DEFAULT_K` | 12 | a fixed count, so the neighbour count carries no information |

Five for five, and each was found by measuring rather than by anything in the
system complaining. That is the argument for adaptation, and it is structural
rather than a list of numbers to re-pick.

### The mechanism is expert aggregation, not a bandit - mostly

The instinct to reach for a bandit is close but not quite right, and the
distinction is the same one [bandits.md](../research/bandits.md) draws for the
alert gate. A bandit exists to handle **partial feedback**: it sees the reward
of the arm it pulled and never the others. For a parameter like `HALF_LIFE`
there is no such limitation - several estimators can run side by side and every
one of them is scored against the same realised move, every bar. That is full
feedback, and with full feedback **expert aggregation beats a bandit**: run the
candidates, weight them by recent loss, and let the weights move. `river` has
`EWARegressor` and the `ensemble` module for exactly this shape.

So:

- **`HALF_LIFE`** - the obvious first candidate, and **measuring it produced
  the most important correction to this whole section.** Weighting several
  half-lives by realised *forecast* loss would optimise the wrong thing:
  [volatility.md](../research/volatility.md) found the forecast optimum at 7 to
  10 bars, and running the edge machinery at each half-life found the calls do
  not improve - h=7 and h=10 are worse on direction than the current 60, and
  the spread across all four is 3.1 points against a standard error of 1.1.

  So **whatever adapts must be scored on outcomes, not on the quantity it
  predicts.** That is harder: a forecast is scored every bar, an outcome takes
  hours, and the loop that closes in hours cannot use the per-bar aggregation
  that makes this cheap. Any scheme here has to confront that gap rather than
  quietly optimise the convenient metric - which is exactly the mistake the
  measurement caught before it was made.
- **`resolve_vol`, `MIN_ZONE_VOL`, `GRID_ZONE_VOL`** - harder, because their
  loss is not observable per bar. These feed touch outcomes, so the loop closes
  in hours rather than bars, and the honest form is periodic re-derivation
  against realised outcomes rather than online weighting.
- **The edge gate** - already designed in [edge.md](edge.md) §4 as accuracy
  targeting, and already measured: **equal to a well-chosen constant at matched
  volume, three times out of three.** Its value is maintenance, not accuracy,
  which is precisely the argument of this section rather than an exception to
  it.
- **The agents' attention budget** - genuinely a bandit, for the reason the
  others are not: analysing gold tells you nothing about what analysing btc
  would have found. See [bandits.md](../research/bandits.md).

### The trap to design against

Adaptation makes a system that *looks* responsive while being harder to reason
about, and this project has already been bitten by drift-following once:
edge.md §4's accuracy-targeting rule looked like a +3.6 to +5.1 point win until
it was scored on a homogeneous window, where the margin vanished entirely. It
had been riding the replay's warm-up trend.

So any adaptive rule here needs the same discipline the constants now get:
**scored against the fixed value it replaces, at matched selectivity, on a
window without a trend running through it.** An adaptive parameter that merely
tracks a drift is not better, it is only harder to audit.

## ~~6a. Model the next major turn, not just the next touch~~ - measured on 2026-08-15, and the answer is do not build it

**Built, run and written up in [turns.md](../research/turns.md).** The
falsification was written first, as this item asked, and it fails.

Four signals do separate turns from non-turns in sample, consistently and in
the same direction over twenty years: **old, extended, volatile trends turn**
(`since_low` 0.616, `vol` 0.606, `extension` 0.593, `vol_ratio` 0.583 AUC).
None survives a purged walk-forward - every interval contains 0.5, and
`since_low` falls from 0.616 to **0.503**. Leave-one-instrument-out is five of
six above chance with one below and intervals a quarter wide.

That is a different verdict from [cycles.md](../research/cycles.md), where
nothing pointed anywhere. Here something does and it is still not enough.

Four things worth keeping from it:

- **The sample was better than this item assumed** - 131 turns, not "tens",
  because the daily history runs 12-20 years rather than the six months the
  touch data covers. It is still too small: the interval needs *several
  hundred* out-of-sample turns against the 94 available, and it narrows more
  slowly than the square-root law because episodes are correlated.
- **Overlapping windows are the trap.** Two days a week apart share 53 of their
  60 forward days. Resampling days rather than episodes would have made every
  result above look significant. Any future work on this shape needs the same
  guard.
- **The sign is stable, the magnitude is not.** Across four eras every signal
  stays on the same side of 0.5, but swings by up to 0.27 - larger than the
  effect. And the base rate halved over twenty years, from 12.9% of days to
  5.4%.
- **Momentum deceleration measures at chance**, and so does the efficiency
  ratio. Those are the two things anyone picking this up would try first.

**The one cheap lever is a collection run.** Eight tracked feeds have no daily
bars at all - audusd, eth, nzdusd, sol, usdcad, usdchf, usdcnh, usdjpy - so the
cross-section is six instruments where it could be fourteen. That roughly
doubles the turns, and [cycles.md](../research/cycles.md) failed for want of
exactly the same span. It is not enough on its own.

The original statement of the question follows.

### Why it was worth asking

Everything built so far answers a question measured in minutes: price has
arrived at a level, which way does it go and how far. A **major turn** - the
end of a trend, the reversal that matters over weeks - is a different object,
and nothing here models it.

What exists to build on, and what each is not:

- **`drift.py`** already answers "has what counts as usual moved?" with ADWIN
  across timeframes, and a drift *invalidates* accumulated history rather than
  predicting anything. It says the regime changed; it does not say a turn is
  coming, and it says so after the fact.
- **BOCPD** (item 7) would *grade* a change rather than flag it. Closer, still
  retrospective.
- **`score.md`** (item 6) is one number per instrument in [-1, +1] with
  transitions. That is the shape a turn signal would have to take, and it is
  the natural home for this rather than a new subsystem.
- **The momentum-turn formation** in §0c is the same idea two scales down -
  where a leg loses its push rather than where a trend does. If it works at the
  swing scale it is evidence the framing transfers; if it does not, that is
  worth knowing before attempting the harder version.

### The problem that makes this hard, stated first

**Major turns are rare, and the sample is the whole difficulty.** Fourteen
instruments with a handful of genuine reversals each a year is *tens* of
examples, not thousands. Every guard this project has built assumes otherwise:
`MIN_EXAMPLES`, progressive validation, the kNN prior, the beta-binomial
shrinkage. None of them work on tens.

Three of today's research documents ran into exactly this shape and it is worth
reading them before starting rather than rediscovering it:

- [news-dedup.md](news-dedup.md) - the falsification could not be run because
  the cell was empty, and the honest answer was to say so.
- [magnet.md](magnet.md) - 45 point estimates, and the one positive had an
  interval five times its own width.
- [features.md](../research/features.md) - an effect that looked like +22.9
  points pooled collapsed to +3.1 within cells.

A turn model will produce a confident-looking number from a dozen observations
unless it is built to refuse. **Design the refusal first.**

### What would make it worth building

Write the falsification before the model, as [edge.md](edge.md) §3 did:

> Label the major turns in the stored history - by a rule, not by eye, or the
> labels encode hindsight. Then ask whether any signal available *before* each
> one separates it from the far more numerous moments that looked similar and
> continued. If the separation does not survive a walk-forward split by time
> **and** hold across instruments, there is no model here, only a fitted story.

The rule for labelling is itself the first piece of work and probably the
hardest: "a major turn" has no definition in this codebase, and one chosen
loosely will make everything downstream look excellent.

### What not to do

Do not start from the news. [news-dedup.md](news-dedup.md) established that
the corpus contains no observation of independent outlets converging on a
story, and [news-models.md](../research/news-models.md) §1 was demoted on the strength of
it. Sentiment or crowding as a turn signal is the same claim in a longer coat,
and the data to test it does not exist yet.

Do not start from levels either. [magnet.md](magnet.md) found levels do not
attract price, and a level is a price rather than a regime - the wrong object
at the wrong scale for this question.

## ~~6c. Cyclical context - where a level sits in the larger move~~ - measured on 2026-08-15, and the answer is no

**Built, run and written up in [cycles.md](../research/cycles.md).** Nothing
separates: under a self-calibrating labeller every cycle cell's interval
contains the pooled up-rate, no threshold from 0.10 to 0.40 changes that, and a
model given the cycle gains a thousandth of AUC while losing accuracy. The
trivial "assume the level holds" rule still beats everything at 75.2%.

The more useful half of the answer is that **the data cannot really be asked
yet**. 1,862 touches span 26 cycles, two index feeds carry 19 of them, and the
other four instruments have 14-18 days of fine-grained history each - less than
one 60-day window, so they cannot vary in cycle state at all and four of six
have zero uptrend touches. The cross-instrument gate could not be run. Re-test
when the 1m/5m history reaches a few months; the harness is written and cached.

Two findings worth carrying to §6a, which needs the same labelling:

- **Cross-venue consensus is wrong at cycle scale.** Venues sit at slightly
  different levels and do not all report every day, so a median switches
  between them and adds steps to the path the instrument never took. The
  efficiency ratio is a ratio *to* that path - it read 0.081 through the median
  against 0.121 through one venue's own series.
- **A symmetric threshold cannot label a downtrend.** Markets fall faster and
  messier than they rise, so a decline rarely sustains directionality over a
  quarter: 0.0% of us100 days and 0.1% of spx500 days over twelve years. The
  turns §6a cares about most are the ones down, and a fixed threshold will
  never see them. Terciles of the feed's own distribution do.

The labeller itself is worth keeping - point-in-time, self-calibrating, checked
against a stated null (observed median efficiency ratio 0.131 against a
random-walk prediction of 0.129). §6a named labelling as its hardest part and
this is most of it.

The original statement of the question follows.

### Why it was worth asking

Every feature the model has is **local to the touch**. `approach_vol`,
`depth_vol`, `run_vol`, `pivot`, `backcheck`, and the six candidates tested in
[features.md](../research/features.md) §4 all describe the last few bars before
price arrived. None of them describes *where that arrival sits in anything
larger* - whether the instrument has been climbing for a month, falling for a
month, or oscillating in a range, and if in a range, whether this level is near
its floor or near its ceiling.

That is a real gap and it is a different gap from the one already recorded.
features.md concluded "the missing information is probably not another function
of price" and named order flow as the absent class. Order flow is absent
*downward* - finer than a bar, and uncollected. This is absent **upward**: the
same stored bars, read at a scale nothing currently reads them at. The two are
not alternatives and the second is far cheaper to test, because the data is
already on disk.

The intuition: a support level in the third month of a downtrend and the same
support in the second week of a recovery are not the same object, and the model
cannot currently tell them apart. Nor can it tell the bottom of a range - where
the next move is up because there is nowhere else - from the top of one.

### Why this is not obviously a good idea

Three findings point the other way and should be read first:

- [magnet.md](magnet.md) found levels **do not attract price**. A cycle claim is
  a bigger version of the same kind of claim, and the smaller one failed.
- [features.md](../research/features.md) §1 found `side` carries essentially all
  of the signal and eight other features carry none. The prior on any tenth
  feature mattering should be low.
- The pooled-to-within-cell collapse: +22.9 points became +3.1. Anything
  measured across instruments and regimes without conditioning will look good.

And a fourth, structural: **regime labels are the easiest thing in this field to
fit backwards.** "We were in an uptrend" is trivially true in hindsight and
nearly useless in advance, which is the same trap §6a names for major turns.
The label must be computable from data strictly before the touch - a rule, not
an eye - or the whole thing is hindsight wearing a feature's clothes.

### The shape it would take

Two values, both point-in-time, both from bars already stored:

1. **Direction at scale** - up, down, or ranging, over a window much longer than
   the touch horizon. `drift.py` already tracks whether what counts as usual has
   moved, but a drift says the regime *changed*, not which way it is pointing;
   this is the missing sign. A slope with a band around it is the crude version
   and is the right first attempt.
2. **Position within the range** - where price sits between the range floor and
   ceiling, as a fraction, when direction is "ranging". Undefined, and correctly
   so, when it is trending: a trend has no ceiling to be near.

Both are one number per instrument per timeframe, recomputed as bars arrive, and
both fit `Features` without touching the touch pipeline.

### The falsification, written first

The interaction is the whole claim, so test the interaction and not the main
effect. Position-in-range on its own will correlate with `side` - near the range
floor most touches are from above - and would score as a discovery while adding
nothing to what `side` already says.

> Split resolved touches by cycle state. Within each state, does the up-rate for
> a given `side` differ from the pooled up-rate by more than the cell interval?
> If a support touch in an uptrend and a support touch in a downtrend resolve at
> the same rate, there is nothing here.

Then the standard gates: walk-forward by time, hold across instruments, AUC
beside accuracy, and scored against "assume the level holds" - which currently
beats the model at 74.8% against 71.1%, and is the baseline any new feature has
to move.

Sample is the binding constraint again. A month-scale cycle gives *tens* of
independent observations per instrument, not thousands, however many touches sit
inside them - the touches within one uptrend are not independent draws on the
question "does an uptrend matter". Count cycles, not touches, when sizing the
claim.

### Where it connects

- **§6a (major turns)** is the same question one scale up and asked as an event
  rather than a state. A cycle label is most of the labelling work that item
  says is its hardest part, so doing this first is the cheaper order.
- **§5b (weak and strong)** would gain the obvious conditioning: a level is
  probably strong or weak *relative to the prevailing direction*, not absolutely.
- **§6 (the score)** is where a cycle state belongs if it survives, as context
  on the number rather than a term in it.
- **`regime`** already exists in `Features` and is a **volatility** percentile,
  not a direction. Not the same thing, and the name collision will mislead
  someone - whatever this ends up called, it should not be called regime.

## 6d. Score the trading, and stop calling four rules a strategy set

**This is the largest gap the trading module has**, and it is the same gap the
level model had before `record_outcomes`: decisions with no labels attached.

Four strategies ship - `level-scalp`, `confluence-scalp`, `momentum-scalp`,
`approach-scalp` - and none has been evaluated against its own outcomes. Each
is a rule for acting on a measured signal; none is itself measured. The docs
say so, and that is the honest position rather than a satisfactory one.

The pieces are in place. `structures.resolutions` carries ground truth on the
bus, `trading` writes a `decide` per intent and an `outcome` per close with the
sizing copied in, and `trading report` pairs them and refuses to characterise a
sample under thirty. What is missing is closed trades.

**Order of work.**

1. **Run it on paper against real broker quotes** for long enough to accumulate
   trades. Unarmed runs fill against the terminal's actual bid/ask, so the
   spread is real and only the fill is simulated - which is the cheapest
   honest sample available.
2. **Score by strategy against the pooled rate**, in R rather than money, the
   way `trading report` already does. A win rate without the base rate beside
   it is the mistake §7 of levels.md exists to prevent.
3. **Then decide what to keep.** `confluence-scalp` is the one to watch:
   [strength.md](../research/strength.md) measures confluence depth at an AUC of 0.476 and
   0.452 - below the 0.5 that means no information - so the prior says it
   should not beat `level-scalp`. If it does, that is worth understanding
   rather than celebrating, because what strength.md measured is "did price get
   through the level" and not "did the trade make money".

**What would falsify the module as a whole:** every strategy indistinguishable
from the others and from a fixed-size entry at the same signals. That is the
null, it is cheap to compute from the same journal, and it should be run first
rather than last.

## 6e. The gates have never been costed

`Guard` counts refusals per gate - that is what the machine-readable `gate` on
every `Refusal` is for - and nothing reads the tally back. A gate that never
fires is doing nothing; one that fires constantly is mis-set. Both are
invisible without looking, and both are one query away.

`trading report` prints the tally today. What it cannot say is what the refused
trades *would* have done, which is the number that decides whether a limit is
protecting the account or just costing it. The refusals are journalled with the
full sizing context precisely so that question can be answered later; nothing
answers it yet.

The one to look at first is `news`, because it is the widest: a single US
release blacks out gold, BTC and all seven majors for ten minutes before and
fifteen after, and on a busy calendar that is a large fraction of the session.
It may well be worth it. Nobody has checked.

## 6f. Trading is unmeasured against slippage and rejection

Sizing assumes the fill is the quote. Against a real terminal it is not: the
order pays the ask, the deviation allows a requote, and a stop fills where the
market is rather than where it was placed. `OrderResult` carries the fill price
and the intent carries the quote it was sized from, so the difference is
already recorded on every trade - and nothing compares them.

A running estimate of realised slippage per instrument would feed straight back
into `min_reward_to_risk`, which is currently a constant nobody derived. It is
the same shape of question as the spread charge in §3, and the same answer: it
is measurable from what is already written down.

## ~~6g. Let the agents price the market too~~ - the primitive is built, the strategy is not

The thesis is that we price the market and take a stance on the distance. The
arithmetic side does that: `structures` estimates fair value from where
volatility turned, and `fade-to-value` trades the gap.

The agents do not. `agents` reports findings and the `council` strategy votes on
a side, which is the old shape - an opinion about direction rather than a
valuation. Fundamental analysis is a valuation exercise more naturally than a
directional one, and an analyst that has read the calendar, the reserves and the
headlines is being asked the wrong question when it is asked which way price
goes.

**What to build.** Have a role output a *price*, with a width, and a horizon:
"gold is worth about X, give or take Y, over the next Z hours". Then the same
arithmetic applies to it as to a level - distance from spot, scaled by the
width, is the stance - and the same journal pairing makes it scoreable against
what the market subsequently paid.

Two things fall out for free. A model quoting a number can be **scored on
calibration**, which is a far better question than whether it was directionally
right, and it is the question `calibration.md` already wants to ask. And an
agent valuation and a level valuation can be *compared*: where they agree the
distance is worth more, and where they disagree that is worth knowing on its
own.

The `council` should follow: a voice that answers "buy at 0.7 conviction" is
harder to score than one that answers "worth 4,415, give or take 30".

**Built on 2026-08-26**: `trading/valuation.py` asks exactly that question and
checks the answer against the market - a stance, a gap in volatility units, and
a gap in the analyst's *own* widths, which is what decides whether a distance
is a mispricing or the noise of its uncertainty. Widths are clamped in
volatility units because a model's stated precision is the least trustworthy
number it produces and the one that would size the position.

**Left to do**, and deliberately not done at once:

1. **A strategy that trades it.** The primitive returns a stance and a distance;
   turning that into an entry needs the same gates and sizing everything else
   uses, and there is no reason to write it before there is any evidence the
   valuations are worth trading.
2. **Score the calibration first.** Record valuations against what the market
   subsequently paid and ask whether an 80% interval contains the price 80% of
   the time. That is answerable long before any trade is taken on one, and it
   is the question that decides whether step 1 is worth doing.
3. **Compare the two estimates.** `structures` prices from where volatility
   turned; an analyst prices from the calendar and the flow. Plot one against
   the other and against what the market paid. Where they agree the distance
   should be worth more, and where they disagree that is worth knowing on its
   own - but "should" is doing a lot of work in that sentence and it is exactly
   what the data can settle.

## 6h. Structures: what would actually improve the estimate

The fair-value estimate comes from one input - where volatility turned - and
the honest question is what else would sharpen it. Roughly in order of expected
value against effort:

**Volume, if it can be had.** A point of control is fair value derived from
where volume traded, and it is the closest independent estimate of the same
quantity this project models. Two problems. Our bars carry `tick_volume` from
TradingView, which counts *price changes* rather than contracts - a proxy for
activity, not size, and one that varies by venue in ways that would leak into a
cross-venue median. Real volume exists on the crypto venues and on futures
(GC=F, SI=F, NQ=F, ES=F) and not on spot FX at all, so a volume term would be
available for some instruments and not others, which the level model currently
never has to deal with.

The measurable first step is small: record `tick_volume` on the touch features
alongside everything else, and ask whether touches on high-activity bars
resolve differently. If they do not, the expensive version is answered before
it is built.

**Where the estimate is thin.** `Level.filter.sigma` is the width of the
estimate and nothing consumes it as a *confidence*. A level whose variance has
not converged is a worse valuation than one that has, and the zone already uses
it geometrically without anything reading it as evidence.

**Time, now that it is instrumented.** `sessions.Clock` records how hours
behave; nothing weights by it yet. That is deliberate - it should earn a weight
from our own resolutions first - but the wiring is the cheap part and is done.

**Cross-instrument.** Gold and silver are the same trade most days, and
`exposure` already knows they share a dollar leg. A level on one is weak
evidence about the other, and the correlation is measurable from the bars we
already store rather than assumed.

**What not to add.** Anything that turns the estimate into a direction
predictor. Every entry in the price-geometry family has been measured to a coin
flip, here and elsewhere; the reason this project is not in that graveyard is
that it is estimating a *quantity*, and that is the property to protect.

## 6i. More than one terminal, in two modes

> **Copy mode is built** - `trading/replicate.py`, `TRADING_FOLLOWERS`, and
> [trading.md](trading.md). Split is still only reasoning.

`Broker` is one terminal, one account, and everything above it assumes that:
`symbols.resolve` scans one catalogue at start-up, sizing reads one equity, and
the risk plan's limits are a fraction of that one number.

There are two different reasons to want several, they are not variations of
each other, and several questions below have **opposite** correct answers
depending on which one is meant. Copy is the intended mode; split is recorded
so that the reasoning survives if scale ever makes it worth building.

| question | **copy** (the default) | **split** (later, if scale needs it) |
| --- | --- | --- |
| what is replicated | the decision | nothing - each position lives on one terminal |
| lot size | re-derived from each account's own equity | derived once, from the shared book |
| magic base | **the same** on every account | **must differ** per process |
| exposure | per-account | must aggregate across terminals |
| risk limits | each account's own plan | one plan spanning all of them |
| a rejected order | let the accounts diverge, record it | route the same order elsewhere |
| choosing a terminal | not a choice - all of them | a decision worth measuring |
| what equity means | each account's own | the sum, or a designated primary |

Running both at once is not a simple composition - it is a split book being
copied, and every exposure question then has to be asked twice at two different
scopes. Not a reason to rule it out, but a reason not to arrive at it by
accident.

### Copy: one decision, many accounts

The strategy decides once and the position is replicated across several
accounts. The parts that actually break, in the order they matter:

**Lots must not be copied. Risk must be.** This is the correctness point
everything else is downstream of. A 0.05-lot trade sized for a 10,000-unit
account is a quarter percent of it; replicated verbatim onto a 2,000-unit
account it is one and a quarter percent - five times the risk the plan
authorised, on the account least able to carry it. So a followed account
re-runs `sizing.lots` against **its own** equity and its own symbol spec, and
what travels is the decision and the price levels, never the volume. An account
whose minimum lot is larger than its risk budget allows should be refused
rather than rounded up, which is the same `min_stop_vol` argument in a
different variable.

**Partial failure is the normal case, not the edge.** Account A fills and
account B is refused - not enough margin, the instrument is not carried, a
different filling mode, AutoTrading switched off on that terminal. The state
afterwards is genuinely divergent and the policy has to be chosen rather than
discovered: unwinding A to stay symmetric turns one broker's problem into a
realised loss on an account that did nothing wrong, so the default is to let
them diverge and record it. What must not happen is a report presenting one
decision with three fills as though it were one trade. Closes fan out the same
way and fail the same way, and a half-completed close is the more dangerous
half of this.

**The magic base stays the same across accounts.** Magic distinguishes our
trades from a hand-placed one on that terminal, and every account should mark
them identically. The collision that matters is two processes against *one*
account, which is a separate problem and still real.

**Exposure stays per-account.** The same position on five accounts is five
accounts holding it against their own capital, not one position sized five
times. Aggregating here would refuse the replication that is the entire point.

**Risk limits stay per-account.** Each has its own equity, daily loss halt and
position count. A follower that hits its halt stops copying while the others
carry on, which is correct and needs to be visible rather than silent.

**Symbol resolution is already per-terminal and that part works.** Run it per
account and one that does not carry `Germany 40` simply does not receive those
trades. No new mechanism, just not sharing one resolved map.

### Split: one book across several terminals

Worth writing down because the answers invert, and because a note that
originally said these things was corrected as wrong when it was only wrong for
copy mode.

The reason to do this is capacity or execution quality rather than
replication - a size that moves one broker's book, or a second venue with
better index pricing. Then:

**The magic base must differ per process.** Two processes against the same
account and band reconcile positions the other opened. Magic separates our
trades from a hand-placed one; it does not separate us from ourselves, and
per-strategy magics did not change that - two processes running the same
strategy stamp the same number by construction, because the number derives from
the strategy name so that it survives a restart.

**Exposure must aggregate.** Two terminals both long the dollar are one dollar
trade, and a guard seeing only its own book would authorise it twice. That is
the argument `exposure.py` already makes about tickets, one level up.

**Which terminal fills it becomes a real decision** with an answer worth
measuring: the tighter spread at that instant, the account with room under its
limits, or simply the venue whose symbol resolved. `speeds.py` and the slippage
work in 6f are what would settle it, which is an argument for doing those
first.

### The step both modes need

`Broker` construction should take an explicit account identity instead of
reading one set of environment variables, and `Trader` should hold a set of
execution targets rather than one. That much leaves the single-account case
behaving exactly as it does now, which is the property that makes it safe to
build before either mode's policy is settled.

## 6j. Limit entries, so the fill is chosen rather than accepted

Every order this module sends is a market order. `Order` carries no type, and
none of the four backends or the HTTP bridge know about a pending one, so the
fill is wherever price happens to be when the call arrives.

That is worst for `approach-scalp`, whose geometry is deliberately entering
away from the level it measures. It buys up to a level above, and how good the
trade is depends entirely on how far below that level the fill lands - which is
currently not a decision at all. The stop now clears the fill by a volatility
unit, which stops the size inflating on a bad fill, but a better fill would
have been better than a safer bad one.

The idea worth trying: **rest the entry where the stop would otherwise have
been.** Instead of buying at market and stopping out a unit below, place the
buy at that lower price and put the stop beyond the zone's outer wick. The
trade that gets stopped out today is instead the trade that gets *filled*
today, the reward-to-risk improves because the target has not moved, and the
cost is the trades that never fill because price left without the pullback.
That cost is real and is the thing to measure: a strategy that only fills on
retracements is a different strategy, not a cheaper version of this one.

What it needs before it can be built:

* a type on `Order` - `BUY_LIMIT`/`SELL_LIMIT` in MT5 terms - and support in
  `paper`, `mt5_native`, `mt5_rpyc`, `mt5_http` and the bridge itself;
* an expiry, because a resting order with no deadline is a trade taken on
  information that has gone stale. The natural one is the strategy's own hold;
* pending orders in reconciliation. `positions` returns positions; a resting
  order is neither an open position nor a closed one, and `_settle` currently
  has no state for "asked for, not filled";
* a decision about what the journal records. One `decide` at rest and an
  `outcome` on fill or expiry keeps the pairing honest, but it means a decision
  entry that may never become a trade, which the scoring in 6d has to expect.

The cheaper half of this can be had first without touching the broker port: the
strategy holds the intent and fires a market order when the bus quote reaches
the price it wanted. That is a worse fill than a resting limit and it cannot be
hit while the process is down, but it needs no new order type and would answer
whether the pullback fills often enough to be worth the plumbing.

## 6k. What the terminal knows that we are not asking it

Measured against the live account rather than reasoned from the MT5 API, on
2026-08-26. What the broker actually serves decides most of this.

| | this account | usable |
| --- | --- | --- |
| depth of market | `market_book_add` fails, then `"No book data"` | **no** |
| tick stream | bid/ask, `time_msc`, `flags` | yes |
| traded volume / last | `last=0.0`, `volume=0`, `session_volume=0.0` | **no** |
| spread | `spread=16` points, `spread_float=True` | yes |
| broker stop limits | `trade_stops_level=20`, `freeze_level=3` | already used |

**No depth, so `liquidity_beyond` cannot be grounded.** `sweeps.py` infers
resting liquidity from where peer levels sit, which was the right design and is
now also the only one available here: this broker publishes no book at all.
Worth re-testing on any new broker before assuming it, but nothing should be
built that depends on it.

**No traded volume either.** The tick stream is quotes, not trades - `last` and
`volume` are zero on every tick and the session counters stay at zero. So MT5
cannot supply the real volume that 6h wants for a point-of-control estimate.
What it *can* supply is a quote-update rate from the venue we actually execute
on, which is a better activity proxy than TradingView `tick_volume` for exactly
one reason: it is the same book the order goes to. Same model as `activity.py`
already uses, better input.

**Spread is the one worth doing first.** `max_spread_fraction` is a fixed
fraction of the stop, and spread is not fixed - `spread_float=True`, and it
widens at rollover, before releases and at session edges. A per-`(symbol, hour)`
spread distribution would let the gate say "this is the 95th percentile for this
hour" instead of comparing against a constant, which is the same shrinkage
machinery `sessions.py` already uses for hold rates and the same scale-free
argument the rest of the project makes. It would also cost nothing at decision
time, because the quote is already in hand.

**Slippage is now recorded** - see the `entry_wanted`/`entry_filled`/`slippage`
fields on every close - so the question 6f asks can start being answered from
the journal rather than needing new plumbing. The thing to do with it once
there is enough: compare the round trip against the edge the gate required. The
edge gate currently does not know what trading costs, which is the largest
unmeasured assumption in the module.

## 6l. Three clocks, and the stop is on the fastest one

Measured on 2026-08-27 against 16 live trades and the journal behind them.
This is the most consequential thing found so far and nothing has been changed
for it, because it is a change to sizing on a live account.

**Every loss came in at between -0.90R and -1.18R**, which is the stop being
hit at full size, and they arrived in 23, 24, 41, 54, 55, 127, 272 and 307
seconds. The wins took 42, 86, 175, 254 and 266. Losses arrive in under a
minute; wins take four. A thesis about where fair value sits does not resolve
in 23 seconds, so what is being measured there is not the model being wrong.

**Every stop from 19:36 onward sits at exactly 1.00 volatility units** - pinned
to `min_stop_vol`, on every trade, because the sweep-zone widening added the
day before turns out to be inert: `wick_deep_vol` falls back to the mean
whenever a side has fewer than two recorded wicks, and these levels have
`own_touches` between 0 and 8. It fired on 2 of 17 decisions. Not wrong,
starved.

### The mismatch

Three quantities, on three different clocks:

| quantity | measured over |
| --- | --- |
| `vol_bps`, and therefore the stop | **one bar** of the entry interval |
| `expected_push_vol` | the resolution **horizon**, up to an hour |
| `max_hold` | a fixed **thirty minutes** of wall clock |

A stop at one unit of *one-minute* volatility, on a trade held for thirty
one-minute bars, faces the accumulated wandering of thirty bars. Volatility
grows with the square root of time, which was checked rather than assumed -
measured on our own instruments, the ratio of observed growth to sqrt(t) is
1.04, 1.12 and 0.89 on gold at 5m, 15m and 60m, and 0.99 and 0.98 on the Dow.
So thirty bars is about 5.5 units of noise against an expected push of about
1.3. Noise beats signal four to one over the holding period, and the stop is
not merely likely to be hit first - it is close to certain.

### The two halves of the fix

They are the same correction seen from either end and should be done together.

**Scale the stop to the hold** - `min_stop_vol * sqrt(hold_bars)` - which
widens the stop by that factor and shrinks position size by the same, holding
the money at risk constant while giving the trade room to be right.

**Express the hold in bars of the entry interval** rather than in fixed
seconds. A strategy triggering on 1m and holding thirty minutes is asking a
one-minute signal to survive a thirty-minute walk; on 15m the same setting is
two bars. One number cannot mean both.

Doing both also makes `reward_to_risk` honest for the first time. It currently
compares a horizon-scale push against a one-bar stop, which flatters every
trade that passes it - and `reward_to_risk` is already the largest single
refusal reason at 143, so the gate is both busy and measuring the wrong ratio.

## 6m. Trade crypto - spot and futures - on what ccxt now collects, added 2026-09-04

The collection half is built and wired: `prices/crypto.py` discovers a board
from any ccxt exchange, filters it freqtrade-style (rank by quote volume, then
reject), registers the survivors as ordinary feeds, and `bar_source_names()`
turns the source on once any exist. **Nothing trades them.** `trading` reaches
the market through `Broker`, and there is no ccxt implementation of it.

### What has to be decided before any of it is built

**Spot or futures, and they are not the same instrument.** `CcxtSource`
defaults to `defaultType: swap` on purpose: a perpetual has a position with a
size and a side, which is the model `trading` is built around, where spot has
balances and no such thing as a short. Trading spot would mean either a
long-only book or a second position model. Collecting one and trading the other
is worse than either - the basis is small but the liquidations that move a
perpetual do not exist on spot, so a level learned on one is not the level
being traded.

**Funding is a cost this desk does not model.** A perpetual charges funding
every eight hours, and it is paid by whoever holds through the stamp. It is
not spread and it is not commission - it is a carry that scales with *time in
the trade*, which is the one dimension `research/paying.md` does not price.
A trailing scalp-to-swing hold is exactly the shape that pays it most.

**24/7 breaks the session model.** `_warm_sessions`, `_undealable`'s shut-market
test and the weekend logic all assume an instrument that closes. Crypto never
does, so the "could not close a us30 position for twenty minutes" failure that
motivated that code cannot happen - but neither can the code's assumption that
a stale quote means a shut market. It would read a dead socket as a holiday.

### What freqtrade is worth taking from, beyond the pairlists

The filters are already borrowed and reimplemented. The rest of what it has
solved and this desk has not:

* **Leverage and margin mode as per-pair settings**, not a global. Isolated vs
  cross changes what a liquidation costs, and it is set per position at the
  exchange, so it belongs beside `SymbolSpec`.
* **A liquidation price that is tracked, not assumed.** The stop is not the
  worst case on a leveraged perpetual; the liquidation is, and it moves with
  funding and with unrealised P&L on cross margin.
* **Exchange-specific order behaviour.** freqtrade carries a per-exchange table
  of what actually works - which order types are honoured, what the minimum
  notional is, how `reduceOnly` behaves. ccxt unifies the call and not the
  semantics, and that table is most of its exchange support.
* **Precision and notional floors before sizing, not after.** A size that
  rounds to zero is a silent no-trade, which is the shape of failure this
  project keeps finding.

### Order to build it in

1. **Collect and learn only.** Feeds are registered now; let levels form on
   them and check the models say something before any money is involved. The
   null is cheap here - `research/null.md`'s argument applies unchanged.
2. **Paper against ccxt quotes.** `PaperBroker` already holds its own stops and
   needs a quote stream; there is no ccxt quote transport yet, which is the
   next concrete gap (`quote_source_names()` has no ccxt entry).
3. **A `CcxtBroker`**, testnet first, perpetuals only, one exchange.

**Not started, and deliberately behind the trading fixes.** The give-back bug
(`research/inert.md`) is worth more than a new venue.

## ~~7. BOCPD~~ - measured on 2026-09-08, and it loses to doing nothing

Documented in [structures.md](structures.md) as a way to *grade* a regime
change rather than flag it, and deferred for a year.

**Run.** Written from Adams & MacKay rather than taken from a package, and
scored as an origin locator against five other detectors on 6,300 paired
comparisons: **0.237v against the baseline's 0.226v** - worse than the estimate
you get by not running a detector at all, and beaten by a ten-line NEWMA. Four
times the window made it worse, not better. So did KCP and RuLSIF; only FOCuS
improved on the baseline, and it still lost to taking the extreme.

Full table and the reason - the localisation problem is an *extremum* problem
wearing change-point clothes - in [localising.md](../research/localising.md).

The run-length posterior is still the only one of the six that reports a
*distribution* over where the change was, so if a consumer ever wants a
confidence rather than a point, this is where to come back to. Nothing wants
one today.

## 7a. Change points into an HMM, across timeframes

Two shapes, and they are different experiments:

1. **Every detector into one model.** The six detectors of
   [localising.md](../research/localising.md) each produce a statistic per bar
   per timeframe; feed the vector to an HMM and let the hidden state be the
   regime. The attraction is that the detectors disagree in structured ways -
   FOCuS and the extreme agreeing is already measured to mean something
   (`Origin.confirmed`) - and an HMM is a principled way to read a
   disagreement rather than a hand-written rule.
2. **Only FOCuS, across timeframes.** The same statistic on 5m, 15m, 1h and 4h.
   Much smaller, and it asks the sharper question: is a change that shows on
   every timeframe a different object from one that shows on the fastest only?
   `confluence` already assumes something like this about *levels* and has
   never been asked about *changes*.

**Do 2 first.** It has one free parameter family instead of six, the streams
are already computed per timeframe, and if the cross-timeframe signal is not
there in the cleanest possible form it will not be there in a six-detector
soup either. This is the same order that made the `Cusum` ensemble readable.

**~~Done, 2026-09-08~~, and it is the largest result on this line.** A change
point on three or more timeframes is followed by **+7.92v** a day out; one on a
single timeframe by **-1.24v**, at a matched realised move. The shuffled-label
null returns -0.66v, and 3+tf is ahead on 6 of 6 instruments that produce
enough of both. They are not the same object at different strengths - they
point opposite ways. Full tables, the confound that had to be beaten and the
five things it does *not* establish are in
[agreeing.md](../research/agreeing.md).

What is still open on this item:

* **Option 1 - six detectors into one HMM.** Unchanged and still last. The
  single-statistic version has now returned a large effect, which raises rather
  than lowers the bar: a six-detector model has to beat +7.92v, not zero.
* ~~**Publish the agreement count as a feature**~~ - shipped, and journalling:
  412 rows in six hours spread 238/44/42/57/31 across 0-4 agreeing, with
  `change_watched_tf` mostly 3-4. It needs weeks before it can be scored.
* ~~**Block bootstrap the day-horizon gap.**~~ Done. **Only the day survives**:
  90% interval [0.644v, 14.876v] over 125 feed-days, 96.5% of resamples
  positive. The hour ([-0.549v, 1.502v]) and the four-hour ([-0.470v, 3.968v])
  straddle zero and were reported as results when they should not have been.
  The day's interval is wide, so what is established is the **sign**, not the
  nine volatility units.
* **The 4h arm was not run.** 24 days of 1m is 144 four-hour bars. 30m stood in
  for it.
* **spx500 and us100 produced zero three-way agreements in 24 days**, on
  hundreds of single-timeframe calls. That wants explaining before the feature
  is trusted on indices.

## ~~7e. KSWIN is silent, and the alpha is why~~ - removed 2026-09-09

`drift: adwin 27, kswin 0, both 0, kswin alone 0` in the first hours of the
tally logging. `kswin_alone` is the number the whole experiment exists to
produce and it is zero.

**That is a verdict on the configuration, not the detector.** `KS_ALPHA` is
0.0005 against River's default 0.005 - ten times stricter. A detector that
never fires at a tenth of the usual significance is telling you about the
significance.

Two ways to close it, and leaving it running-but-unanswerable was not one:

1. Run at 0.005 and see whether `kswin_alone` becomes non-zero. If it did, the
   question becomes whether those alarms are worth their false positives.
2. Or accept that a second detector silent at the significance this desk will
   act on is not earning its window, and remove it.

**Option 2, on 2026-09-09.** By then it was 0 against ADWIN's 136. The cost was
a hundred-sample window per instrument and timeframe, a KS test on every quote,
and a pickled detector per pair restored on every start - paid for a reading
that could not come back non-zero. `Drift.__setstate__` drops what old saves
carry so the memory goes with it.

What stays open is the blind spot itself: ADWIN cannot see a distribution that
widens with its mean unmoved, and that case is ordinary here. The way back is a
detector that *decides* something, measured against what discarding a level's
history costs - not a second opinion nobody reads.

## 7f. The stop was not the explanation, and 205 trades cannot tell

The agreement filter passed its control by a factor of fourteen for *location*
and did not show for *trade outcomes*. The named hypothesis was the stop.
Tested across five stop widths with a 500-draw permutation test at each: the
split is **positive at every geometry** (+0.318R to +0.134R) with p from 0.048
to 0.248, and the five rows are the same 205 trades re-managed rather than five
samples.

So the stop is not the explanation, and the honest conclusion is that the
sample cannot separate a 0.2R effect from noise. The same applies to the zone's
edge over random placement: the null is one draw per row and moves over 0.38R,
which is larger than the 0.18R edge.

**What this needs is more trades, not more cleverness.** 25 days and eight
instruments produced 205. The options are a longer history, more instruments,
or a faster anchor - and the first is the only one that does not change the
question being asked.

## ~~7g. Does a catalyst change the rate of going nowhere?~~ - not runnable yet

`research/catalysing.md`. Technicals say where and which way; news decides
which instrument has a reason to travel. The testable half is that **structure
without a catalyst is a trade that expires rather than one that loses**.

The number that makes it worth running first: **49% of `thesis-only`'s 159
trades reached neither stop nor target**, and those 78 cost 392 units. Every
other open question in the research folder is worth tenths of an R.

Three things the run has to get right, each of which has already cost a wrong
answer somewhere in this folder:

* The catalyst window must **end at the entry**, not span it. Counting one that
  lands afterwards is look-ahead.
* The control must be **matched on busyness**, not on the absence of a
  headline - trades and news both cluster when markets are active, so an
  unmatched comparison measures the session.
* **The synthetics are the built-in control.** They have no underlying and no
  news, so the effect cannot exist there. If it appears anyway, it is not news.

**Run 2026-09-09 and it cannot be answered on this book.** Of 203 closed trades
over 45 days, 146 are synthetics with no calendar; of the 57 real ones only 20
map to a calendar tag, splitting 6 with a catalyst against 14 without, and not
one instrument-hour cell carried both. `articles.symbols` turned out to be `[]`
on all 24,214 rows, so RSS cannot be linked to an instrument at all.

**And the placebo fired.** Synthetics given the US calendar flag - for events
that cannot reach a generated index - expired 58.5% against 49.4%. Nine points
on instruments the news cannot touch, because the flag is a proxy for the
session. An effect that size on the real arm would have been indistinguishable
from the clock, and would have been published as a result.

To run it properly the book has to trade instruments that have a calendar. That
is the binding constraint and it is not a data problem.

**What the run did settle is where the money goes.** Boom is 53% of all losses
- 44 trades, -410, losing in *both* directions - on an instrument
[spiking.md](../research/spiking.md) had already shown to be memoryless and
unpredictable. See [catalysing.md](../research/catalysing.md).

## 7h. Levels that tally across instruments - run, and it is about the dollar

`research/tallying.md`. If EURUSD has a level and GBPUSD has the corresponding
one, is the pair worth more than either alone? Designed, not run.

The trap is named in the design and it already killed the change-point version
in [peering.md](../research/peering.md): **two dollar pairs are not two
witnesses, they are one witness seen twice.** The controls are a no-shared-
currency pair, the synthetics, and a permutation test rather than one shuffle.

**Run 2026-09-09.** Within the hour of day, a level held **+5.6% more often**
on eurusd when gbpusd was simultaneously at one of its own (21 of 24 hours),
and +1.7% to +3.1% across the rest of the dollar bloc. Both honest controls are
clean: the synthetic pair -0.2%, eurusd/audjpy -1.5%.

**But it is probably the dollar, not the principle.** gold/silver - the one
pair that would separate "a shared factor at a level" from "the dollar at a
level" - returns +0.9% on 11 of 22 hours, a coin flip. A `gold/audjpy` control
fired at +2.6% and turned out not to be a control at all: AUD and gold co-move,
so the pair shares a factor while sharing no currency.

**The composite carries it, tested the same day.** Counting how many dollar
pairs are at a level at once gives a monotone rise - eurusd holds 78% with none
of the others at a level and 96% with four - and **conditioned on that count
the pairwise identity adds nothing**: eurusd/gbpusd runs +6.9%, +2.3%, +1.3%,
-0.0%, -1.1% across counts of one to five, none significant. The +5.6% was
GBPUSD standing in for "the dollar bloc is at a level".

What survives is broader than the question asked, and is **not yet a result**:
the more instruments are simultaneously at a level, the more likely any one
holds - and the metals show it too. The count was never conditioned on the
session the way the pairwise test was, so it could still be volatility wearing
a costume. Condition on the hour and on realised volatility, run longer than 14
days, and block bootstrap it.

## 7i. Is the regime forecast actually combined with direction?

`research/clustering.md`. Volatility clusters and direction does not, so the
sharpest statement of what this system does is: take the predictable part and
let structure supply the sign.

**That has never been tested directly.** `forecast_ratio` - how far the current
scale sits above its own long-run level - is published on every call and
nothing conditions on it. Whether a level held more often when the regime
forecast was rising, falling or flat is answerable from the journal today, and
would say whether the two halves are combined or merely both present.

Measured on the way in: the level book holds **1 to 15 levels per (feed,
interval)** across 3,451 sets - a near-price working set, not a historical map,
because `prune` drops untouched levels beyond 8 volatility units. Agreement is
therefore conditioned on both instruments being near their level at once, which
thins the population sharply. Count the pairs before promising a measurement.

## 7c. Cross-instrument agreement - run, and it failed its control

The same idea across eight instruments instead of across timeframes. Effects of
about a volatility unit with shuffled-label nulls of comparable size, mostly
gone once the instrument's own timeframes are conditioned on - and **Deriv's
synthetics, which share no macro factor, produced a larger effect than real
assets that share the dollar**. See [peering.md](../research/peering.md).

Nothing was published from it. What is left:

* **A cross-sectional volatility control.** The likeliest mechanism is that the
  peer count proxies for "everything is moving", which the realised-move
  conditioning does not touch. Any second attempt needs it.
* **The Volatility 1s series wants its own threshold.** Five indices produced
  62 events between them at 12 nats - a detector calibrated on FX and crypto is
  close to silent there.
* **Keep the synthetic group in every future cross-asset claim.** It cost one
  extra run and it is the only thing that settled anything.

## 7d. A TradingView indicator for the origin zones

Built: [research/tradingview/focus_zones.pine](../research/tradingview/focus_zones.pine).
A 4h anchor detects the change, a 5m refinement places the zone inside the
anchor bar, and the 3-of-4 timeframe agreement rule filters what gets drawn.

**It has never been executed.** Pine cannot be run from here, so the script is
reviewed rather than tested and the arithmetic in it - the hull pruning
especially - carries the risk any untested code does. First run on a chart
should compare its zones against the harness output on the same instrument and
period before it is trusted.

**The null it has to beat**, and it is not "does the HMM fit": an HMM will
always find states. The question is whether the state it infers predicts
anything the current priority ordering does not - which is the same bar
[choosing.md](../research/choosing.md) sets for HMM strategy selection, and the
two should share a harness rather than each grow one.

**A warning from the run above.** Every method that pooled more inputs did
*worse* than the one that pooled fewest - MD-FOCuS lost to univariate FOCuS by
feeding it two extra co-dependent streams. "More signals into one model" is the
shape that has already failed once here, so the cross-timeframe version needs
the single-timeframe baseline measured first and beaten, not assumed.

## 7b. The dual-stream trap test needs volume, which the research db has not got

Separating a **trend reversal** from a **liquidity spike** is the framing that
falls out of running two change detectors side by side: the range widening and
the volume spiking while the mean return does *not* shift is absorption or a
news print, not a turn. That is exactly the trap population
[trapping.md](../research/trapping.md) already has - 64% of attempts, 94.6% at
30m - so the hypothesis has somewhere to be tested.

Two things block it:

* **`bt1m.db` has no volume column.** Open, high, low, close and nothing else,
  so the liquidity stream cannot be built in the harness that measures
  everything else. The live `Series` *does* carry `volumes` now, so the data is
  being collected going forward; the history is not there.
* **On synthetics there is no volume to have.** Deriv's indices are generated,
  and the traps that matter most on this book are on Boom and Crash. The
  candle-spread stream works there and the volume one never will.

So the testable half is `log(high/low)` against the log return, and that is
worth running on the trap population as it stands.

## Watch rather than act

> **Migrated on 2026-08-15.** The three notes that follow describe the
> 908MB instance this ran on until then and are kept because the reasoning
> is still how to read a kill - but the numbers are not the current box, and
> several of them were the *reason* a diagnostic was deferred. Those reasons
> are gone.
>
> | | old | new |
> |---|---|---|
> | RAM | 908MB | 3,823MB |
> | swap | none | 2GB |
> | disk | 6.7GB, 79% used | 242GB, 3% used |
> | container cap | 640MB, pinned | 70% of host, derived |
> | architecture | amd64 | **arm64** - the image is now built for both |
>
> **So do the deferred work** - but read the correction below first.
> `prices prune` has never actually run, `VACUUM` was waiting on room for a
> second copy of the file, and the outcome-rate re-measure and `structures
> gaps` were both put off because a second process was enough to OOM the box.
> None of *that* is true now.
>
> **Corrected 2026-09-08: the binding constraint is CPU, not RAM, and this
> note caused an outage by saying otherwise.** The box has **2 cores**. A day
> of research harnesses run inside the live container - several minutes of CPU
> each, plus a 208-second full scan of `prices.db` writing an 841MB extract -
> took the service from ~3,500 journal entries an hour to **zero**. It stayed
> `healthy` at 68% CPU and produced nothing for hours, logging `bus:
> prices.bars full` 132,807 times, which rotated every diagnostic out of
> `docker logs`. A restart fixed it: CPU 68% to 9%, drops to zero.
>
> So: heavy work is fine on this box and **not inside that container**. Use a
> second container, or run it `nice`d on the host against a copy of the
> database. And when something looks stalled, `docker logs` may be useless -
> group the journal's `entries` by `actor`, which separates a structures stall
> from a trading one in one query. What has *not* changed
> is that a cold start is still the expensive moment - see item 0c - though it
> costs 36MB rather than 410MB since the warm was streamed.

- **~~Nothing heavier than a read can run on this box.~~** Established the hard
  way on 2026-08-14: `agents ask` and `prices prune` each OOM-killed the
  container, three restarts between them. Kills landed at ~260MB resident
  against 908MB total with ~148MB available, so *any* second process was
  enough. The database survived every one - `pragma quick_check` clean, no rows
  lost, which is SQLite's transactionality doing its job - but the agent window
  timer resets on each restart, so the diagnostics kept destroying the test they
  were run for.
- **Memory bit before disk did**, and the shape of the kill is worth keeping
  even on a bigger box. The container was capped at 640MB but the kill came
  from the *host* running out - `oomkilled=false` on the container with
  `global_oom` in `dmesg`, which is a confusing pair to read and reads as "not
  a memory problem" if taken at face value. Watch resident size against the
  host's total, not against the container's cap.
- **Disk** was next at 79% of 6.7GB, and is now 3% of 242GB. `prices` is 961MB
  and grows continuously; the instrument count went from six to fourteen on
  2026-08-14 and 1m joined the level set, so the growth *rate* is roughly 2.3x
  what the original note was written against. `till-infinity prices prune`
  exists for this and still nothing runs it - see [prices.md](prices.md),
  "Retention". A cron entry with `--yes` is the intended shape, and `--vacuum`
  is now affordable whenever, since a second copy of the file is 0.4% of the
  disk rather than most of it.
- **Agents** wake every 30 minutes, and every deploy restarts that timer. On a
  busy deploy day they may never reach a wake.
- **Confluence text** in a delivered alert should match `structures zones` for
  the same instrument. Both are logged; if they diverge, the per-batch grouping
  in `_level_calls` is where to look.
- **The MT5 tunnel** is a single point of failure that fails quietly in the
  right direction: `trading` cannot reach the terminal, refuses to start, and
  the rest of the stack carries on. `systemctl status mt5-bridge-tunnel` on the
  box, and `trading doctor` inside the container, are the two things to look
  at. A tunnel bound to loopback instead of the docker gateway is the failure
  that looks like everything working - it answers from a shell and is invisible
  to the container.
- **AutoTrading on the terminal** switches itself off whenever the account
  changes, and every order is then refused with a message naming the client
  rather than the terminal. The auto-login script now reads the state back
  rather than blind-toggling, but it is worth knowing what 10027 means.
- **Two traders, one magic.** Running a second `trading` anywhere against the
  same account and magic number makes both of them reconcile positions the
  other opened. The magic is what separates our trades from a hand-placed one;
  it does not separate us from ourselves.
