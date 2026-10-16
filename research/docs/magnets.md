# Magnets: where price is drawn back to, and why it would be

The desk's working theory of liquidity, written down on 2026-10-16 so the
harnesses have something to be wrong against.

## The thesis

**A magnet is not a prediction, it is a place where orders are resting.**

Institutions do not get filled by forecasting the next move. They get filled by
going to where the other side already is, because size cannot be worked into a
market that is not offering it. So the question "will price come back here" is
really the question "is there a reason for business to be transacted at this
price", and the answer has nothing to do with the shape of the candle that drew
the line.

What makes a price a place where orders rest is that **many participants can
compute it independently and arrive at the same number**. That is the single
property tying together everything in the panel below - a 200 EMA, a round
number, yesterday's high, a Fibonacci retracement. None of them is special
geometry. Each of them is a *shared reference*, and a shared reference is where
resting orders collect without anybody coordinating.

This has a sharp consequence worth stating because it cuts against most of
what is written about these patterns: **the mechanism is reflexive, not
structural.** A 200 EMA does not describe anything about supply. It works, if
it works, because enough screens draw the same line that orders accumulate on
it. That means a level's power should scale with **how widely watched it is**,
not with how well it fits a theory of order flow - and that is a testable
distinction, because the most-watched references are not the most
theoretically motivated ones.

## Why each candidate would be a magnet, in market terms

| level | why price would be drawn there |
| --- | --- |
| **displacement origin** | the small bar before a one-sided push is where a position was built without moving price; the push is what happened when the absorbing side stopped offering. The claim is the remainder of that order is still there. Already measured - see below |
| **origin** | the same claim stated by distance rather than by candle shape: a move that travelled `MOVE_VOL` in `MOVE_BARS` left from somewhere |
| **fair-value gap** | a price range that printed with no two-way trade at all. Nobody was filled there, so the business is unfinished by construction - the purest version of the thesis |
| **equal highs / lows** | two attempts stopped at the same price means a resting offer held twice. Everybody can see it, so everybody's stops go just beyond it, which makes it worth running |
| **volume profile (POC)** | the price the most business was actually done at. Not a story about intent - a measurement of where the market agreed value was |
| **VWAP** | the benchmark institutional fills are *judged against*. A desk filled worse than VWAP has a bad day on paper, so there is a real, mechanical reason for size to transact there |
| **round numbers** | no mechanism beyond the shared one, which is why it is the cleanest test of reflexivity. Humans place orders at round numbers because other humans do |
| **EMA 20 / 50 / 100 / 200, SMA 50 / 200** | the most-drawn lines in existence. Pure reflexivity: there is no supply-and-demand argument for an average of the last 200 closes |
| **Fibonacci retracements** | reflexive with no structural story at all, which makes it the control for the reflexive hypothesis itself. If fibs work and nothing else does, the mechanism is agreement; if nothing works, the mechanism is nothing |
| **prior day high / low / close** | a session boundary every participant has without agreeing to it, and the reference most risk is measured from overnight |
| **double top / bottom (M and W)** | two swings at one price, and the neckline between them is where the stops of everyone who traded the pattern are resting. The magnet is the stops, not the shape |
| **A / V apex** | a single-bar rejection so sharp that whoever wanted size at the extreme did not get it |
| **engulfing body edge, pin tip** | "where the rejection happened" - the candle-pattern version of the same claim |
| **most-touched price** | the bluntest statement of the thesis with no pattern at all: a level is a price people keep dealing at |
| **last bar's high / low** | no story whatsoever. The floor every other row has to clear |

## How it is measured

`research/ideas/magnet_levels.py`. Every rule draws on a rolling window at that
window's own volatility, and each level it emits is followed forward.

* **the return rate** - does price touch the level within the horizon;
* **the whole time distribution** - min, p25, median, p75, max, in bars,
  because a median alone hides whether "how long until price comes back" has a
  reliable answer or merely a typical one;
* **the scaling exponent** `b` in `log t = a + b log d`. This is the one that
  separates the explanations. A driftless walk covers a distance `d` in a time
  growing like `d**2`; anything genuinely *pulling* arrives in time
  proportional to `d`. **b near 2 is a line drawn on a walk. b near 1 is a
  magnet.**

The exponent exists because the return *rate* cannot answer the question. At a
100-bar horizon it reads 0.85 for a displacement origin and 0.85 for a random
level the same distance away, and planting a real magnet of 0.1 volatility
units a bar barely moves it - the statistic is against its own ceiling, and a
saturated statistic cannot report an absence.

## The nulls, and why there may not be a good one

The desk's objection is on the record and it is the right one: a walk and a
placebo may behave like the real thing, so they may not be the correct nulls,
or there may be no correct null. Three arms, none sufficient alone:

* **`~when`** - the same distance in volatility units, same side, from a
  *different bar*. This asks the only question a magnet claim actually makes:
  does the **identity** of this price matter beyond how far away it is? A rule
  whose levels are reached no sooner than an arbitrary price the same distance
  out is naming distances, not prices.
* **`~where`** - a price *this same rule* drew at another window, tested here.
  It holds "a price this rule likes" fixed and breaks "a price this rule likes
  **now**".
* **each other** - every rule in one table on the same bars. A ranking needs no
  synthetic null at all, and it is the arm that survives the objection: if the
  200 EMA, a displacement origin and the last bar's high all read alike, none
  of them is a magnet whatever the absolute numbers say.

**The confound that is stated rather than controlled:** a drawn level is
usually a price the path has already *visited*, and returning to a visited
price requires no participant and no intent. `~where` bites hardest on this,
because those are visited prices too.

### A null that was worse than none

The first version of this harness placed its placebo at the same distance, on
the same side, measured from the same bar - which reconstructs the level price
**exactly**. Every arm read `+0.00`, and the random-walk check that was
supposed to validate the method could not have failed. It was caught by the
result being too clean rather than by reading the code. A null that is
algebraically the thing it nulls does not fail to help, it actively reports
success.

The replacement is checked the other way round: on a generated random walk the
`origin` rule now recovers a slope of **1.99**, which is the diffusive 2 the
theory demands, so the instrument can produce the answer that means "nothing
here".

## What is already known, before this panel

The displacement origin is magnet number one and it is the one with a history:

* price returns to it **77-82%** of the time, and a distance-matched placebo
  matches that on every class - a plain walk reads 0.825
  (`origin-return-rates.md`);
* the trade built on it fails from all three directions, and it fails on
  **ordering** rather than on probability - price does come back, having gone
  further against you first, and 89-91% of fades were stopped before the target
  arrived (`fade-to-origin.md`);
* loosening it to a **one-candle** push multiplies the supply by five to ten
  (54-261 levels per 1,000 bars against 6-71) without diluting the measured
  edge, which is evidence *against* the accumulation story: if a bigger
  participant were doing the work, admitting every news tick should have made
  it worse.

That last point is the one to keep. The mechanism predicted `n=2` beats `n=1`
and the measurement says otherwise, which points at the mechanical explanation
- price returns to a price it recently traded through - rather than at anybody
resting an order.

## What the panel found

Measured 2026-10-16 on 1h bars, 600-bar windows every 200, 14 instruments a
class, levels given 1,000 bars to be reached. Twenty-one level types against
their own `~when` and `~where` arms.

**No level in the panel pulls price.** On fx_major, with samples from 737 to
61,550:

| level | n | slope | `b-when` | vs b | median bars |
| --- | ---: | ---: | ---: | ---: | ---: |
| run | 61,550 | 1.01 | 1.01 | **+0.00** | 14 |
| profile | 39,046 | 1.02 | 1.02 | **+0.00** | 13 |
| origin | 9,901 | 1.01 | 1.03 | −0.03 | 15 |
| fib | 4,735 | 0.98 | 0.96 | +0.01 | 8 |
| swing | 3,803 | 1.08 | 1.01 | +0.06 | 16 |
| prior day H/L/C | 3,139 | 1.05 | 0.96 | +0.09 | 10 |
| last bar H/L | 2,552 | 0.97 | 1.02 | −0.05 | 2 |
| apex body | 1,903 | 1.10 | 0.95 | +0.16 | 11 |
| touched | 1,408 | 1.00 | 1.01 | −0.01 | 11 |
| ema20 | 1,307 | 1.11 | 0.94 | +0.17 | 4 |
| pin tip | 1,254 | 1.00 | 0.89 | +0.11 | 5 |
| ema50 | 1,233 | 0.96 | 0.87 | +0.09 | 8 |
| sma50 | 1,187 | 0.98 | 1.08 | −0.10 | 10 |
| ema100 | 1,064 | 0.94 | 1.02 | −0.07 | 12 |
| engulf edge | 1,046 | 0.93 | 0.97 | −0.04 | 7 |
| sma200 | 737 | 1.30 | 1.13 | +0.16 | 15 |

Every row sits within **±0.17** of its own null and the two largest samples sit
at **±0.00**. On medians, `vs~when` runs −2 to +2 bars against medians of 2 to
18. Pooling every class, the largest |vs b| on any sample over 700 is 0.62 and
the next is 0.27 - and **the same rule changes sign between classes** (ema20
reads +0.17 on one and −0.16 on another), which is what noise looks like and
not what a weak effect looks like.

`last_bar`, the row with no story attached, reads −0.05. It behaves exactly
like everything with a story attached.

### The finding that is not a null

**`b-when` is about 1.0 on real markets where a random walk gives 2.0.** Price
genuinely travels in near-linear time at these distances - 0.1 to 8 volatility
units - rather than diffusively. Trends, volatility clustering and fat tails
all carry price further per unit of time than independent steps would.

So "price returns to the level in linear time" is **true and is not evidence
of anything**. Every arm shows it, including an arbitrary price the same
distance away and the previous bar's high. The ballistic exponent belongs to
the market, and every level inherits it. Any future claim of the form "price
is drawn to X" has to beat `b-when` on the same bars, not beat 2.

### Still under-powered, which is not the same as null

`ema200` could not be fitted on fx_major even at this sample (829 levels, the
null fitted at 1.65 and the real arm did not), and `vwap` fitted on only one
class (n=1,591, vs b **+0.16**, i.e. marginally *slower* than its null). The
double tops and bottoms, their necklines, and equal highs and lows all stayed
under the bucket threshold. These are reported as unmeasured rather than as
measured-and-null, and the slow references are the ones to re-run first if
this is picked up again - they are also the most-watched, which is exactly
where the reflexive thesis makes its strongest prediction.
