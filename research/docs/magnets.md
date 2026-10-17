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

## The most-watched references, powered

The first pass starved exactly the rows where the reflexive thesis makes its
strongest prediction, so they were re-run on 2026-10-16 with 40 instruments a
class and a 120-bar stride, the heavy already-settled emitters dropped to buy
the windows, and - the fix that mattered most - **every pattern instance
emitted once** instead of only the most recent one per window. A pattern was
previously reported only if it was the last of its kind in the window, which
discarded almost all of them; reporting all of them would have counted each
three times over, because the windows overlap. Keeping those that formed in
the last `STRIDE` bars gives every occurrence exactly once, and it moved
`pin_tip` from 451 levels to 19,802.

| level | n (fx_major) | slope | `b-when` | vs b |
| --- | ---: | ---: | ---: | ---: |
| pin tip | 19,802 | 0.91 | 0.91 | **+0.00** |
| apex | 8,532 | 0.91 | 0.91 | **+0.00** |
| apex body | 8,808 | 0.89 | 0.95 | −0.06 |
| engulf edge | 7,326 | 0.91 | 0.91 | **+0.00** |
| last bar H/L | 4,194 | 0.85 | 0.81 | +0.04 |
| ema20 | 2,191 | 1.01 | 1.07 | −0.06 |
| double bottom neck | 2,130 | 0.93 | 0.92 | +0.01 |
| double top neck | 2,000 | 0.94 | 0.94 | −0.00 |
| double top | 1,993 | 0.91 | 1.05 | −0.14 |
| double bottom | 1,959 | 0.95 | 0.89 | +0.05 |
| ema100 | 1,814 | 0.95 | 0.93 | +0.02 |
| ema200 | 1,390 | 0.88 | 0.93 | −0.05 |
| sma200 | 1,239 | 1.15 | 1.29 | −0.14 |
| vwap | 684 | 1.27 | 0.88 | +0.39 |

**Read it against the control, not against zero.** `last_bar` - the previous
bar's high and low, with no story attached to it at all - scatters +0.04,
−0.14, +0.07, +0.07 across the four classes. That ±0.14 is this measurement's
noise floor at these sample sizes, and **every candidate sits inside it**:

| level | vs b, by class |
| --- | --- |
| vwap | +0.39 (n=684), +0.13 (2,975), −0.08 (2,757) |
| ema200 | −0.05 (1,390), −0.03 (3,230), −0.08 (834), −0.37 (1,019) |
| sma200 | −0.14, −0.01, −0.64, +0.17 |
| double top | −0.14, +0.14, +0.05, −0.05 |
| double bottom | +0.05, +0.06, −0.06, −0.02 |
| ema20 | −0.06, −0.03, +0.12, −0.04 |

Every one of them **changes sign between classes**, which is noise and not a
weak effect, and the two largest readings - `sma200` at −0.64 and `ema200` at
−0.37 - both carry unstable null fits (`b-when` of 1.65 and 1.85) on the
smallest samples in the table. VWAP's one large positive is the wrong sign for
a magnet anyway: it says VWAP is reached in *less* linear time than an
arbitrary price the same distance out.

The calibration rows settle the earlier table too. `ema20` read **+0.17** at 14
instruments and **−0.06** at 40, and `last_bar` moved −0.05 to +0.04 - so the
±0.17 scatter in the first panel was sampling noise, as it was read at the
time rather than afterwards.

**So the reflexive thesis gets no support.** It makes a specific, falsifiable
prediction - that a level's pull scales with how widely it is watched - and the
most-watched prices in existence (the 200-period averages, VWAP, the necklines
everybody's stops sit behind) are indistinguishable from the previous bar's
high.

### The one row still genuinely unmeasured

`equal` - the shipped equal-highs-and-lows rule - never reached a fittable
slope on any class: 144, 496, 107 and 191 levels. That is the rule's own
rarity rather than a sampling choice, and loosening its tolerance would be
measuring a different rule. It needs roughly ten times the instruments, and
its median-time differences are scattered (−4.0, −1.0, −2.5, +14.5 bars) with
no sign to them.

## The conditional version, which had not been tried

**2026-10-17. `research/ideas/liquidity_direction.py`.**

Everything above is unconditional. Asked the same day: *"if we know that a
volatile move is about to happen, how does sweep aware or liquidity aware find
areas of liquidity, we can use it to estimate the likely direction"* - and that
is a different question from the one this document answered, because **none of
the twenty-one rows above conditioned on volatility state.** Every one used
volatility as the *unit* - distances in volatility units - and never as a
regime filter. If liquidity only matters when a move is actually coming, an
unconditional panel averages the moments that matter with the many that do not,
and dilutes a real conditional effect to nothing. That is exactly how a
conditional effect hides.

It was also newly askable. `dispersion-forecast.md` and `dispersion_class.py`
identify those moments at **AUC 0.906, 0.897 within strata, lift 6.7x**, where
the incumbent reading collapses from 0.755 to 0.596 - so "a volatile move is
about to happen" is now a statement this desk can make, which it could not when
the panel above ran.

### The null, which is the whole difficulty

The nearer pool is reached first more often **by geometry alone**: for a
driftless walk the chance of touching the upper of two barriers first is
`d_down / (d_up + d_down)`. A harness comparing "price went to the pool"
against a coin would report an effect on a random walk. So the arm that decides
it is the **matched control** - the same two distances with no story attached -
and the comparison is pool against control, not pool against a half.

### Measured: the same answer, conditional or not

The gate takes the top 25% of predicted 40-bar dispersion as `loud`, the rest
as `quiet`, with the threshold fitted on each series' training half. `excess`
is the realised share where the upper level was touched first, less the
geometric expectation at those exact distances.

| cell | pool | control | pool - control |
| --- | ---: | ---: | ---: |
| fx_major, loud | -0.2002 | -0.1855 | -0.015 |
| fx_cross, loud | -0.2261 | -0.2138 | -0.012 |
| metal, loud | -0.1618 | -0.1558 | -0.006 |
| fx_major, quiet | -0.1522 | -0.1496 | -0.003 |
| fx_cross, quiet | -0.1542 | -0.1640 | **+0.010** |
| metal, quiet | -0.1051 | -0.0922 | -0.013 |

**Pool minus control runs -0.015 to +0.010 across six cells and changes sign**,
which is the same reading the unconditional panel gave: production's own
liquidity levels are indistinguishable from an arbitrary price the same
distance away. The effect is not hiding in the volatile moments.

### One column that is not usable, and why

Both arms sit far **below** the geometric expectation - `excess` of -0.09 to
-0.23 - and that is this harness's tie rule rather than a finding. A bar that
reaches both levels cannot be ordered from bar data, and it is charged to the
losing side on purpose, because assuming the favourable order is how a
backtest invents edge. With 1h bars and levels a few volatility units apart,
many bars straddle both, so `down` wins disproportionately and every absolute
excess is pulled negative. It is also why the `loud` rows are more negative
than the `quiet` ones: bigger bars straddle more often.

That bias is identical for the pool and for the control, so **pool minus
control is unaffected** and is the column to read. The geometric column is kept
because deleting a number that turned out to be unusable is worse than
printing it with the reason.
