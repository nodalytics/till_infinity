# The same anti-signal, found twice independently — and why flipping it is the trap

A separate body of work on a different codebase, different instruments and a
different detector reached a conclusion this folder reached today by another
route, and then drew the wrong lesson from it. Both halves are worth having: the
finding transfers, and so does the mistake.

## The finding, twice

**Over there.** A three-phase structural detector - a range, a sweep of it, then
the expansion that follows - emitted a direction on every confirmed sweep. Over
14 days and 1,838 published readings, its most-emitted state on its most natural
horizon measured **n = 410, 46.8% hit, -22.4 bps, t = -2.07**. Pooled across
states, **512 signals at 46.9% and -20.9 bps, t = -2.28**. Not noise: reliably
wrong.

The mechanism named for it is exactly right and is the transferable part:

> the peer is reporting the direction of the *exhausted move*, not the direction
> of the *next move*.

Price runs above a prior high, so the sweep signal is positive, so the label is
"up" - when a high-sweep is conventionally the exhaustion of the move that made
it.

**Over here.** [`zma.md`](zma.md) and [`adapting.md`](adapting.md) measured the
z-score's agreement condition on Boom and Crash at a **0.376 to 0.461 hit rate**,
and then at **0.119 and 0.164** once the flag was scored on its own terms.
[`adapting.md`](adapting.md) derived the mechanism independently:

> Boom drifts slowly down and spikes up. The long drift leaves the z-score
> persistently low - `oversold`. The spike is what finally turns the slope
> positive. So `agrees` - oversold *and* rising - fires precisely on the bar
> after the one up-move, and calls for more up, at the moment the drift resumes.

**These are the same defect.** Two unrelated detectors, on unrelated
instruments, both fire on a counter-trend excursion and both label it with the
direction of the excursion rather than of what follows. Neither was found by
reasoning about the indicator; both were found by scoring it against outcomes
and being surprised.

That is a defect *class*, and it is worth naming: **a detector built to find
exhaustion will label the exhausted move**, because the excursion is what
triggered it and the excursion has a direction. The label is the easy part to
get backwards and the hard part to notice, because the detector is working.

## Why flipping the sign is the trap

The conclusion drawn over there was to invert the direction, on this evidence:

| | n | hit% | bps | t |
| --- | --- | --- | --- | --- |
| as shipped | 512 | 46.9 | -20.9 | -2.28 |
| inverted | 512 | 52.3 | +20.9 | **+2.28** |

described as "perfect symmetry - the model's signal carries +2σ of edge".

**That symmetry is arithmetic, not evidence.** Inverting a binary direction
label negates the signed return of every row by construction, so the t-statistic
must flip sign exactly. The second row contains no information the first did not
and cannot confirm anything. It is the same shape as scoring a model on its own
training data: the number that comes back was determined before the test ran.

Two things in the same audit say so more clearly than the summary does.

**Every state was negative.** Raw forward return after each state, with no
direction applied: -50.3 bps, -31.2, -11.4, -166.6, across all four states
including "accumulating" and "expansion", which are supposed to mean opposite
things. A detector whose every state predicts a fall is not detecting; the
*sample* fell. Inverting the sign then buys a positive result in-sample that
reverses the first time the drift does.

**The one good cell contradicts the others.** The only positive surface -
`nyse 15m` at +10.1 bps - is the same state that reads -20.5 on `nasdaq 1h` and
-79.8 on `mexc 4h`. One global sign cannot be right for all three, which is
itself proof that the problem is not a global sign.

[`calibrating.md`](calibrating.md) measured what this costs here: one pass of
this desk's own analysis produces **at least one interval excluding zero 63.05%
of the time** on null data. Four states by three horizons by several venues and
timeframes is a far larger table than that, and a single t of 2.28 inside it is
unremarkable.

**The test that would settle it was not run**, and it is cheap: score the
direction against a drift-matched baseline, or on a window whose drift has the
opposite sign. Then "the label is backwards" and "the fortnight fell" stop being
the same number.

## What this desk did instead, and why

The same choice arose here and was resolved differently, before any of the above
was read. `agrees` is an anti-signal on Boom and Crash, a coin on the
synthetics, and a coin on real outrights. Inverting it globally would have
turned the coins into coins and the anti-signal into a signal **on one family**,
while breaking nothing visibly - which is exactly the failure that survives a
deploy.

So `trading.strategies.scalper.zma_gate` does not invert anything. It reads the
continuous z rather than the flag, and it refuses to act at all until **that
feed's own scored record** clears `TRADING_ZMA_MIN_CALLS` settled calls at
`TRADING_ZMA_MIN_ACCURACY`. On a family where the reading is an anti-signal the
record never clears and the gate stays silent. Nobody maintains a list of which
families spike, and no global sign has to be right everywhere at once.

## The four questions, and what they say about this book

The same body of work carries a framing worth more than the detector:

> find where human interpretation of probability systematically diverges from
> probability formation

with four questions a hypothesis has to answer before it becomes an experiment:
**how** the probability is formed in this market, **which** cognitive error
produces the divergence, **who** is on the other side, and **why** it persists.

Applied to this desk it explains a year of null results in one line.

**The synthetics have no participants.** `generators.md` verified they are
exactly the published generators - realised volatility equal to the name on 12
of 12 within 0.49%, Step Index a fair coin to `p = 0.499734 ± 0.000220` over
5.2M flips. There is no interpretation to diverge from formation, because
formation is a random number generator and nobody is interpreting anything.
`deriving.md`'s theorem is the formal version of the same statement:
`E[net] = -(c/2) × turnover` for every rule, because a predictable position on a
martingale has zero gross expectancy. **Question one has an answer for these
instruments and the answer is "there is nobody to be wrong".**

That is not a discouraging result, it is a *targeting* result. It says the
entire synthetic book - 43% of this desk's closes - cannot pay by construction,
and no detector, model, timeframe or exit will change that.

**The constructed spreads do have a mechanism.** A cross-venue spread reverts by
arbitrage: participants with latency, fees and inventory, whose interpretation
can and does lag formation. [`constructing.md`](constructing.md) measured the
z-score at **AUC 0.6985 against 0.5031 on the same days and bars**, which is the
only positive directional result in this folder. Question one has an answer
there too, and it is a different answer.

The gap the four questions expose, and which nothing here has closed: **who is
on the other side of a cross-venue spread, and why does the deviation persist
long enough to be traded?** Until that is answered the 0.70 AUC is a
measurement, not an edge - and this desk cannot hold the position anyway,
because two venues is two accounts.

## Ideas worth porting, in order of how cheaply they pay

**Provenance on every reading.** A range there carries `range_source` -
structural, statistical, both, or neither - and a matching strength. Not a
confidence score but a statement of *where the number came from*. This desk
started doing the same thing this week without naming it: `trading affordable`
prints whether each volatility came from the instrument's published name, from
bars, or from the engine state, and that column is what made "18 of 51 judged"
visible instead of silent.

**Per-instrument behaviour, measured and persisted.** Sweeps there are
classified per `(symbol, timeframe)` as messy or clean, written to a collection
and refreshed on a schedule, and the classification changes what downstream
believes. `Zma.standings()` and `Book.standings()` here are the same object -
what has this reading actually done *on this feed* - and the z gate already
defers to it. Worth extending to the other detectors that currently assume one
character for every instrument.

**A changepoint that relaxes a threshold rather than firing one.** A confirmed
low-volatility changepoint there does not emit anything; it lowers the bars a
range needs from 8 to 5. That is a better use of a changepoint than a gate, and
it is what [`zma.md`](zma.md)'s own FOCuS result pointed at from the other
direction - the gate that raised precision needed the changepoint to be
**active**, not quiet.

**A constant that encoded one regime.** A maximum range width hardcoded at 3%
was misclassifying genuine wider ranges - a week of BTC drifting 74k to 78k -
until it was raised to 8% and made configurable. Three of today's findings are
the same sentence: the softmax with no temperature, the minimum pull applied to
an unnormalised slope, and the weight sums taken from their infinite-series
closed forms. **A number needs a scale before a constant can be compared with
it**, and every one of those shipped and did nothing visible.

**Shadow-filter first.** Empirical rules there are attached to every setup with
a verdict and a reason and **no decision effect yet**. That is `Shadow` and
`TurnExit` here, and it is the only discipline that has ever settled an argument
in this folder.

## What is not worth porting

The three-phase lifecycle itself - range, sweep, expansion - is a richer state
machine than the two-state zigzag in `structures/cycles.py`, and the temptation
is to build it. The measurement above is the reason not to yet: that machine's
own audit found its most-emitted state anti-predictive at n = 410, and
[`delivering.md`](delivering.md) found this desk's four detectors of the same
object separated by **2 to 4 points** from matched-random on real instruments.
Building a fifth detector of a thing that has not been shown to pay is the
activity this folder exists to stop.

The part already worth having is the part `delivering.md` measured: the
**feature families** underneath all of them - the extreme, the derivatives, the
extremes behind, and volatility - which took the turn-depth head from 0.0451 to
0.1894 on an identical series.
