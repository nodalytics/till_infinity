# Four books, read for things this desk can measure

Notes from `calv.info/bookshelf` on *The Laws of Trading*, *Thinking in
Systems*, *A Thousand Brains* and *Radical Markets*, kept only where they turn
into an experiment or a rule this desk can apply to its own record.

Each item below is scored against **what has already been measured here**,
because an idea that agrees with the record retrospectively is worth more than
one that merely sounds right. Three of them agree with results that are already
in `research/docs/`, which is the reason to take the rest seriously.

## 1. Stocks against flows, and why the desk's whole result set has one shape

*Thinking in Systems*: a **stock** is a quantity you can observe, a **flow** is
what changes it, and **people notice stocks far more readily than flows** - it
is easier to say "find more oil wells" than "use less oil".

This is the single best description of this desk's accumulated results.

| quantity | kind | measured here |
| --- | --- | --- |
| price level, spreads, cointegration | **stock** | 0 of 190 pairs, 0 of 1,625 baskets, 0 of 18 commodity claims |
| volatility correlation | **flow** | median **+0.5170**, 104 of 107 beat null |
| tail co-movement | **flow** | **+0.1275** lift, 177 of 190 |
| activity on `Q` | **flow** | **+2197** nats, 8 of 8 |
| the clock on `Q` | **flow** | +675 nats |

**Everything the desk has found is a flow and everything it has failed to find
is a stock.** That is not a coincidence to be admired, it is an explanation:
the crowded quantity is the one people notice, and price level is the stock
everybody watches. It also gives a cheap prior for triaging the next idea -
**ask whether the candidate is a stock or a flow before measuring it** - and the
record says a stock-shaped idea starts at long odds.

## 2. The absorption fingerprint is a loop-type classifier

*Thinking in Systems* again: **balancing** loops push a system back toward a
target; **reinforcing** loops amplify their own input.

`statespace-orderflow-from-bars.md` split markets three ways by comparing
intra-bar geometry against a matched walk, and the three states are exactly the
three loop types:

| measured state | loop | what produces it |
| --- | --- | --- |
| absorbing, 0.94 to 0.97 | **balancing** | passive liquidity pushing price back |
| neutral, 1.00 | **no loop** | a generator with no jump, `Step_Index_200` |
| running, 1.13 to 1.23 | **reinforcing** | a generator with a jump |

That reframe earns its place because it says **what to measure next**. A
balancing loop has exactly two parameters - a **gain**, how much of a
displacement is pushed back, and a **delay**, over what time - and this desk has
measured only the one-bar slice of it (AUC 0.484, real but worth a quarter of a
spread). The loop framing says sweep the delay.

`statespace-orderflow-from-bars.md` arrived at the same next experiment from the
cost side: edge scales with available room, room grows with horizon, the spread
does not. **Two independent routes to the same arm** is the strongest argument
for running it.

*Thinking in Systems* also warns that **delay causes overcorrection** - the
shower that is always too hot or too cold. That is a live risk for the
adaptive conformal corrector in `conformal_band.py`, which is a feedback loop
with a delay in it, and it is worth checking whether its `gamma` sweep is
really a stability sweep.

## 3. "Why would they trade with me?" - the question the desk has not asked

*The Laws of Trading*: the other side usually knows more than you; ask what
their edge is, and **"if their edge is really so good, why would they trade with
me?"**

This desk measures whether an effect is real and whether it clears a cost. It
has never asked who is on the other side. Applied to the absorption finding the
question is immediately sharp:

Absorption means price travels its range and comes back. To be paid for that,
the desk has to be **the one absorbing** - posting resting orders and being
filled by the flow that pushes price out. That is a **market-making** position,
not a taking one. So:

* the relevant cost is the **maker** fee, not the taker fee;
* and `polymarket-taker-fee-is-about-3pt5-percent` already records that the
  **maker fee is unknown and is the thing that decides whether making works**.

So the adverse-selection question converts a vague "0.3 bp against a 1.9 bp
spread" into a specific blocker: **measure the maker fee**. It also reframes
the edge, because a maker is not paying the spread, it is **earning** it - and
the absorption signal is then a filter on which quotes to leave up rather than
a reason to cross.

## 4. The length of an edge's explanation, tested on the desk's own record

*The Laws of Trading*: **"the more words it takes to explain your edge, the
worse it probably is."** A real edge is something others miss, that you can act
on, and that is **simple to state**.

That is a falsifiable claim about this repository, so it was checked against the
record:

| edge | words to state | verdict here |
| --- | --- | --- |
| the ladder belongs on log-volatility | ~8 | **+191 to +547 on 7 of 7** |
| activity drives how far price goes | ~7 | **+2197, 8 of 8** |
| volatility has a time-of-day shape | ~7 | **+675** |
| the walk is the best-calibrated band | ~7 | **nothing beats it on CRPS** |
| rolling-quantile edge gates | many | **refuted** |
| the level magnet effect | many | **refuted** |
| strategy rotation is timeable | many | **refuted, matched random pausing** |

The rule holds on seven for seven. It is kept as a **triage prior and not a
decision**: it would have rejected the optional-stopping identity, which needs
a paragraph and is correct. But a candidate that needs three clauses and a
conditional should be measured last rather than first.

Same source, the related one that matters more: prefer a **generative** model -
"the gears approach" - over a phenomenological one. Every member in
`statespace` is generative, and every refuted item in the table above was
phenomenological. The absorption finding has gears: passive liquidity. The
commodity-currency finding has gears: an exporter's terms of trade.

## 5. Quadratic voting against measured over-confidence

*Radical Markets*: under **quadratic voting** a voter's influence is the
**square root** of the credits they spend, so expressing a strong preference
costs disproportionately more and a minority can be heard without a fringe
dominating.

That is a weighting scheme, and this desk has a measured problem it fits.
`prod-probability-up-needs-halving` records that `probability_up` reaches AUC
**0.6365** while being roughly **twice as confident as it should be** - its
distance from 0.5 needs shrinking by 0.47.

Standard inverse-variance pooling weights a member by its **precision**, which
rewards exactly the member that has understated its own uncertainty.
Square-root-of-precision weighting caps how far one over-confident member can
dominate a vote, and - unlike the measured 0.47 shrink - it is a **mechanism
rather than a fitted constant**, so it has somewhere to generalise to.

**The arm**: pool the members by `sqrt(precision)` against the usual
`precision`, scored on held-out likelihood and on PIT flatness, with the
measured 0.47 shrink as a third arm. If the mechanism matches the fitted
constant, the constant stops being a magic number.

## 6. Reference frames, which this desk has already confirmed twice

*A Thousand Brains*: the cortex builds many models in parallel, each in its own
**reference frame**, and they **vote** to produce one percept. The author's gloss
is the useful part: *"being an expert is mostly about finding a good reference
frame that you can use to frame and connect various facts."*

This desk has twice found that the reference frame mattered more than the model:

* `statespace-volume-clock.md` - **volume time** absorbs three-quarters of the
  time-of-day profile. The structure was not in the clock, it was in activity;
* `the-ladder-belongs-on-log-volatility` - the same ladder earns +191 to +547
  on 7 of 7 markets once it is put in log-volatility space and loses on 5 of 5
  controls in price space.

So the transferable instruction is **search over frames, not only over models**,
and the frames this desk has not tried are the obvious next list: **range
time** (a bar per unit of travel), **tick time**, and **imbalance time** (a bar
per unit of signed flow, which `orderflow_from_bars.py` now makes measurable).

The **voting** half is separate and untested here. `swarm.py`, `ranking.py` and
`selective.py` exist, and the illusion evidence Hawkins uses - a vase or a
face, never both - suggests **winner-take-all** rather than blending. This desk
has a near-miss on that question already: a blend-against-unblended comparison
here turned out to be a **smoothing artefact**, with the rotation null scoring
+104.4 against the real +35.6. So the arm is worth running, with that null
built in from the start.

## 7. Blue oceans, and the axis this desk is already on

*Blue Ocean Strategy*: a red ocean is a contested market where everyone competes
on the same axes; a blue ocean comes from competing on a **different axis**. The
distinction the notes draw is between **substitutes** - same market, same axes -
and **alternatives**, which serve the same goal from another category.

The red ocean here is **direction**, and the desk has the measurements to say
so: `direction-is-closed-not-just-null` finds a planted drift at `z + 2.90` and
earns 2% of a spread, and the new absorption signal is real on 8 of 8 and earns
a quarter of one. Meanwhile every uncrowded axis has paid: how far, the band,
the clock, activity, tails.

Read strictly, that is an argument about **instruments** rather than signals. An
edge in "how far" expressed as a spot position has to be converted into
direction to be paid, which is the crowded axis. The instruments that pay for
"how far" directly are **barrier and digital payoffs** - which is what
`bounding.py` and the barrier work already address, and which is where the
desk's convexity line is pointed.

The "alternatives" idea has one concrete arm: *can a related activity be used
to boost the main goal?* The desk has the two halves sitting next to each
other - cross-instrument volatility correlation at a median **+0.5170**, and
activity driving `Q` at **+2197** - and has never crossed them. **Drive one
instrument's `Q` from a peer's activity.** If relationships are contemporaneous
and large in volatility space, a peer's activity should carry information about
this instrument's variance, and that is a flow-shaped, one-sentence,
generatively-motivated candidate which is exactly what every rule above says to
measure first.

## The order to run them in

1. **the delay sweep on the absorption loop** - two independent arguments, and
   it decides whether the one real directional signal here is tradeable;
2. **a peer's activity driving this instrument's `Q`** - crosses the desk's two
   largest measured effects and nothing has been tried there;
3. **measure the maker fee** - converts the absorption edge from "a quarter of
   a spread" to a different arithmetic problem entirely;
4. **`sqrt(precision)` pooling** - a mechanism for a defect currently patched
   with a fitted constant;
5. **new reference frames: range time, imbalance time**;
6. **winner-take-all against blending**, with the smoothing null built in.
