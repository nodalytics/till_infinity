# FOCuS, end to end

The index for everything this repository has measured about the exact CUSUM
likelihood-ratio test, and the two results that were produced for the
TradingView indicator: how a threshold should change with the timeframe, and
whether the zones the indicator draws are tradeable.

| question | answer | where |
| --- | --- | --- |
| Is it a good change detector? | Quiet enough to be an alarm - at most 5 false alarms across five stationary runs of 3,000, where EDDM fires every 270 | [detecting.md](detecting.md) |
| Should it locate origins? | Best of six change-point methods, and **loses to taking the extreme** | [localising.md](localising.md) |
| Should it *confirm* the extreme? | Yes - 0.101v against 0.152v, with a control that only the two resolving estimators move | [localising.md](localising.md) |
| Across timeframes? | Three or more agreeing is followed by **+7.92v** a day out; one alone by **-1.24v** | [agreeing.md](agreeing.md) |
| Across instruments? | No - fails its synthetic control | [peering.md](peering.md) |
| What threshold per timeframe? | `base + 3 * ln(anchor / tf)`, measured below |  |
| Are the zones tradeable? | Marginally, and the agreement filter does **not** transfer |  |

## The threshold has to change with the timeframe

A threshold in nats is scale-free across *instruments* - that is what dividing
by a volatility unit buys - and it is **not** scale-free across *timeframes*. A
5m series gets 288 chances a day where a daily gets one, and the running
maximum of a likelihood ratio grows with the number of chances it has had.

Measured on 8 instruments, fires per calendar day at a fixed 3 nats:

| tf | 5m | 15m | 30m | 1h | 2h | 4h | spread |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fires/day | 16.96 | 5.57 | 2.53 | 1.38 | 0.63 | 0.20 | **83.7x** |

**At a fixed threshold the fast rungs are always on**, which makes the
agreement count meaningless: a rung that fires seventeen times a day is not
casting a vote, it is a constant. Every rung has to be a comparable event or
counting them measures nothing.

The theory says the correction is `ln n` - a threshold rising one nat per
e-fold of bar count - if the statistic's tail falls like `exp(-h)`. Swept:

| k in `base + k * ln(anchor/tf)` | 5m | 15m | 30m | 1h | 2h | 4h | spread |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 16.96 | 5.57 | 2.53 | 1.38 | 0.63 | 0.20 | 83.7x |
| 1 | 3.00 | 1.30 | 0.83 | 0.47 | 0.24 | 0.12 | 25.2x |
| 2 | 1.07 | 0.59 | 0.40 | 0.24 | 0.12 | 0.08 | 13.4x |
| **3** | **0.55** | **0.32** | **0.32** | **0.20** | **0.08** | **0.08** | **7.0x** |
| 4 | 0.40 | 0.20 | 0.24 | 0.12 | 0.08 | 0.04 | 9.8x |

**k = 3, not the k = 1 the theory gives.** Measured, a nat buys only about a
third of a log-unit of firing rate rather than a whole one, so the correction
has to be three times as strong. k = 4 over-corrects.

That is the same lesson `CHANGE_THRESHOLD` learned in
[localising.md](localising.md): a constant chosen for one question is wrong for
another, and sweeping it is cheap.

**And it is arithmetic, not market structure.** The same sweep on a step-shuffled
copy of every series - same marginal distribution, same length, no ordering -
behaves identically: 29.8x at k = 0 falling to 12.3x at k = 1. A correction
about *how many chances the detector had* must work on a series with no
structure at all, and it does.

At `base = 3` with a 1d anchor this gives 3 nats at 1d, 8.4 at 4h, 12.5 at 1h
and 20.0 at 5m. That 12.5 at 1h is a useful check: it lands beside the 12 the
`structures` service already ships, which runs on intraday timeframes.

## Are the zones tradeable?

The rules are the indicator's, not a tuned variant: FOCuS on the anchor finds
the change, the origin is refined to the extreme close inside that anchor bar,
the zone is that finer bar's own high and low, and **the zone is traded on
return** - resistance sold into, support bought. Entry at the *near* edge,
which is the price a returning move touches first and the worse of the two
fills. Stop beyond the far edge by a quarter of the zone width, target at 2R.

### The look-ahead that had to be removed first

The first run returned **+1.363R at an 80.8% win rate** on btc against a null
of +0.046R. It was wrong, and it was wrong in a way worth recording.

The zone's edges are the extreme of the refinement bars *inside* the anchor
bar. Entry was being looked for from that anchor bar's **open** - so a trade
could fill at a price chosen using the rest of that same bar. A zone is not
knowable until the bar carrying it has closed, and entry now starts there.

A number good enough to be obviously wrong is the cheapest kind of bug to
catch. The expensive kind is the one that looks plausible.

### Scalp: 1h anchor, 5m refinement, 205 trades

| | trades | mean | won |
| --- | --- | --- | --- |
| **real zones** | 205 | **+0.051R** | 37.6% |
| random zones, same geometry | 230 | -0.143R | 30.9% |

The zone beats a matched random-zone null by about **0.19R a trade**. That is
real and it is small, and it is *before costs*: no spread, no slippage, no
commission. At 2R the breakeven win rate is 33.3% and this is 37.6%, so the
margin is four percentage points of win rate.

### The agreement filter does not transfer

By how many timeframes agreed, against the same trades with the labels
shuffled:

| agreed | trades | real | shuffled |
| --- | --- | --- | --- |
| 1 | 85 | -0.072R | -0.017R |
| 2 | 36 | -0.097R | -0.347R |
| 3 | 26 | +0.174R | **+0.444R** |
| 4 | 58 | +0.268R | +0.222R |

The real pattern looks right - negative at one and two, positive at three and
four. A single shuffled draw produced the same pattern and a larger effect at
three, which read as a refutation.

**That reading was wrong, and the mistake is worth naming: one shuffle is not
a null, it is one sample from one.** Swept properly - across five stop widths,
with a 500-draw permutation test at each - the split is positive at **every**
geometry:

| stop, in zone widths | edge over null | 1-2 tf | 3+ tf | split | p (permutation) |
| --- | --- | --- | --- | --- | --- |
| 0.25 | +0.195R | -0.079R | +0.239R | **+0.318R** | 0.048 |
| 0.50 | +0.265R | +0.059R | +0.270R | +0.211R | 0.142 |
| 1.00 | +0.107R | +0.016R | +0.150R | +0.134R | 0.248 |
| 2.00 | +0.176R | +0.020R | +0.190R | +0.170R | 0.152 |
| 4.00 | -0.191R | -0.094R | +0.127R | +0.221R | 0.050 |

**Consistent in sign, and not significant.** Two of five reach p < 0.05 and
three do not, and the five rows are the *same 205 trades* re-managed, so they
are five looks at one sample rather than five samples. After any allowance for
that, nothing here clears a bar.

The honest statement is therefore neither "the filter works" nor "the filter
does not transfer" - it is that **205 trades cannot tell**. The sign being
positive at every geometry is worth something; it is not worth a gate.

**And the same caution applies to the edge itself.** The null column is one
random draw per row and moves over a 0.38R range across the sweep - comparable
to the 0.18R edge it is being subtracted from. The zone's advantage over random
placement is *also* unestablished on this sample, which the first version of
this document stated more confidently than it should have.

What the sweep does settle: **the stop was not the explanation.** Loosening it
from a quarter of a zone width to two does not change the picture, and four
destroys the edge outright.

**This is the interesting result, because agreement passed its control
convincingly for *location*.** In [agreeing.md](agreeing.md), three-or-more
agreement was followed by +7.92v a day out against -1.24v, with a shuffled null
of -0.66v - a factor of fourteen. Here it is inside the noise.

The likeliest reason, and it is a hypothesis: **that measurement had no stop.**
It measured where price went. This measures what a trade with a stop a quarter
of a zone-width beyond the far edge collects, and a stop that tight is hit by
exactly the move-and-return that leaves the forward number intact. The edge may
be real and the geometry may be spending it.

That hypothesis has now been tested and is **not** the explanation - the split
is much the same at every stop width. What the sample cannot do is separate a
real 0.2R effect from noise, and the only fix for that is more of it.

### Swing: 4h anchor, 15m refinement - not measurable here

22 trades across eight instruments. The database holds 25 days of one-minute
bars, which is about 150 four-hour bars per feed, and a detector needs most of
them to warm. -0.008R against a null of -0.423R on 22 trades is not a number.

The daily anchor the indicator ships with cannot be tested here at all.

## What none of this establishes

* **No costs.** Everything is in R before spread, slippage and commission. On
  the venue this repository trades the taker fee alone is about 3.5%.
* **25 days**, one regime, eight instruments.
* **One geometry.** A quarter-width buffer and a 2R target were chosen, not
  swept, and the section above argues they are the most likely thing to be
  wrong.
* **The indicator has still never been executed.** Everything here is the
  harness reproducing its rules in Python. See
  [tradingview/README.md](tradingview/README.md).
