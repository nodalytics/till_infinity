# "Every cycle must close" — where that comes from, and the step that does not hold

The system set out below is **Ramin Rostami's**. It is worth writing up
properly because three of its five pieces are sound, one of them is already
built here on the strength of it, and the load-bearing one is wrong in a way
that is easy to miss.

The measurements and the objections are this folder's, and nothing here is a
claim about what he would say to them.

## The argument, in the order it is made

**1. The market is zero-sum.** Futures and foreign exchange, where no wealth is
created — so every move has to be paid for by somebody.

**2. Therefore every cycle must close itself.** Stated directly: *"In a
zero-sum game market, every cycle must close itself"* and *"you will never see
that the market always remains in trend."* A move up has to be paid back.

**3. Structure is fractal.** *"Small cycles are inside larger cycles"*, and
*"smaller cycles are fractally building larger cycles and vice versa."* The same
shape at every scale, which is why the proposal calls for **20 to 30 timeframes
per instrument** — around two hundred zigzags computed in parallel.

**4. The zigzag is the measuring instrument, not the signal.** Explicitly:
*"We will not be using zigzag directly in our model — I want to use it to
understand geometry market."* It is how the cycles are *seen*.

**5. Cycles close at 86% of the previous leg.** *"Statistically, in the
backtest, the cycles close themselves in the area of 86% of the previous leg."*
Operationally a rectangle with the retracement set to 86%: enter as a cycle
begins to close, exit at the 86% area, stop beyond. Hedged by its author —
*"the cycle does not always end at 86"*, and *"for the first guess, we predict
that the curve should reach 86, but it may not."*

**6. The path is a cubic plus an exponential, fitted by least squares and
corrected by its own error.** *"polynomial degree three least square for fit and
feedback error to train model"*, and *"the model is better and more accurate
after the frequent updates of the errors in the points and entry/exit."* The
first derivative going to zero locates the turn; the second says which kind.

## What is right, and one piece already built on it

**Point 6 is the strongest part of the proposal and it is what
[`streaming.md`](streaming.md) builds** — the depth head there exists because of
this argument. `structures/cycles.py` is an online
learner with stochastic gradient descent and drift detection whose depth head
answers exactly the question a fitted curve is being asked: *how much further
does this leg run before it turns*, corrected by every turn it gets wrong. That
page measured it beating the running mean on 8 of 8 constructed spreads and on
none of the simulated arms — the one component of that work carrying anything.

**Point 4 is a discipline this folder arrived at independently**, which is a
point in its favour.
[`delivering.md`](delivering.md) treats ZigZag, FOCuS, perceptually important
points, a change in state of delivery and this desk's own levels as **one object
under several names**, and scores the claim rather than the detector.

**Point 3's infrastructure is now cheap**, which it was not when proposed. Every
part of the reading has an exact O(1) recursion — attention-weighted moments as
three decaying accumulators, the slope by exponentially weighted least squares,
the thresholds by a streaming quantile — so a stream per timeframe costs a
handful of floats a bar instead of a recomputed window. Two hundred of them is
arithmetic rather than a cluster.

## The step that does not hold

**Zero-sum does not imply mean reversion.** This is the hinge the whole argument
turns on and it is not valid.

A random walk *is* a fair game — a martingale, zero-sum by construction — and it
does not revert. It has no level to come back to. Zero-sum constrains the
**expectation** of a bet, not the **path** of the price. The two are different
statements and only the first follows from the accounting.

[`deriving.md`](deriving.md) has the sharp version for this desk's own
instruments: because a predictable position on a martingale has zero gross
expectancy, `E[net] = -(c/2) x turnover` for **every** stop, target, trail, grid
and filter. That is what zero-sum actually buys you. It guarantees you cannot
win on average; it says nothing about price returning to where it was.

So "every cycle must close" needs a mechanism, and the accounting identity is
not one.

## And the 86% figure does not survive measurement

[`delivering.md`](delivering.md) tested it — between consecutive confirmed
ZigZag extremes, at three thresholds, against a random walk:

| series | theta | n | median retracement | share in 0.80-0.92 |
| --- | --- | --- | --- | --- |
| **GBM (null)** | 2.0 | 3,965 | **1.020** | **0.0666** |
| OU theta=0.05 | 2.0 | 4,340 | 1.008 | 0.0906 |
| gold 15m | 2.0 | 409 | 0.991 | **0.0709** |
| gold 15m | 4.0 | 145 | 0.981 | 0.0690 |
| spx500 1h | 2.0 | 379 | 0.993 | **0.0739** |

The median retracement is **1.00 on every arm including Brownian motion**, about
half of all legs exceed the one before them everywhere, and the share landing in
a band around 86% is **the same on gold as on a random walk**. The ratio of
consecutive leg lengths is a quantity whose median sits near one; 86% is inside
its natural spread and is not a property of markets.

**Two caveats owed to the claim.** A "leg" here is consecutive confirmed ZigZag
extremes at a volatility-scaled threshold; the proposal uses a specific
parameter-free implementation, and a different leg definition could give a
different distribution. And the figure is offered as a *first guess to be
corrected by error feedback* rather than as a law — testing whether 86 is the
mode is the right test of the stated statistic, but not of the adaptive version,
which is really point 6 and is the part that works.

## Where closure is real

**The instinct that closure needs a reason is right**, and it is the part worth
keeping. The reason is just not conservation of money.

Where a series genuinely must return, it is because **a participant is paid to
return it**. A cross-venue spread cannot stay open, because the same asset at
two venues is an arbitrage somebody closes for a profit.
[`constructing.md`](constructing.md) measured the z-score at **AUC 0.6985
against 0.5031** on the same days and bars for exactly that reason, and it is
the only positive directional result in this folder.

That is the same conclusion [`diverging.md`](diverging.md) reaches from the
other direction: an edge needs a mechanism and a counterparty. **The synthetics
have neither** — `generators.md` verified they are the published generators, so
there is no interpretation diverging from formation and nobody to be wrong.
A constructed spread has both, and that is why it is the one thing here that
measures.

## What to take

* **Build point 6, not point 5.** The fitted-and-corrected path is the idea
  worth having; the 86% constant is what that model should *learn*, per
  instrument, rather than be told.
* **Keep point 4's discipline.** The detector is a measuring instrument. Score
  the claim, not the indicator.
* **Point 3 is affordable now** and worth widening — `Cycles` runs three
  timeframes because that is what was measured, not because more is expensive.
* **Drop point 2.** Replace "the market is zero-sum, so it must return" with
  "who is on the other side of this, and what pays them to close it". The first
  is true of everything and predicts nothing; the second is the question that
  picked out the only series here that works.
