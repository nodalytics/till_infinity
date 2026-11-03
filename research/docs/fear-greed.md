# Fear and greed in FX as risk-on / risk-off: the carry crosses, the shapes, the trade

**Measured 2026-11-03, pre-registered.** The well-known Fear & Greed Index is
CNN's, for US stocks, and there is a crypto version. **Neither is computable
here.** They need put/call ratios, market breadth, junk-bond demand, safe-haven
flows and social volume; this desk has OHLCV. Nothing in this document is a
reimplementation of one and no number here should be compared to one.

What *is* computable is the thing those indices proxy for, and in FX it has a
name and a literature. Fear is risk-off: money runs to JPY, CHF and gold and
out of AUD, NZD and CAD, so the carry crosses fall fast; greed is risk-on and
rebuilds the carry trade slowly. **Brunnermeier, Nagel and Pedersen, *Carry
Trades and Currency Crashes* (2008)** is the published description of exactly
that asymmetry, and the 2008 episode they describe is inside this store's
window, so it is available as a positive control rather than as an anecdote.

There is no sentiment feed, so **the proxy is shape**: a level formed at a
down-crash is a fear level, one formed at an up-spike is a greed level, one
formed along a trend run is neither. The label is a property of the bar shape
that produced the level, not of any sentiment source.

## Verdict

| question | answer |
|---|---|
| **Does the fear reading fire on the 2008 carry crash?** | **Yes, on 2 of 3 pre-registered criteria, and the third was a bad criterion.** The 2008-08-01..2009-03-31 window is the **most risk-off of the 28 non-overlapping windows** of its length in 19.25 years (+0.1276) and its peak clears the sample's 99th percentile (+0.3308 against +0.3060). It is **not** the global maximum: that is **2020-03-08**, COVID. The index's top two episodes are 2008-08-03..2009-03-31 (+0.1276) and **2024-07-17..2025-03-18 (+0.1126)** - the two largest yen-carry unwinds in the window, which nothing told it to find |
| Is the synthetic cross trustworthy? | **The close path yes, exactly; the bar extremes no, and not marginally.** The triangle holds to 8.9e-16 in log price and collapses to r2 0.003 at a one-bar calendar shift. But the synthesised **range is about 1.7x too wide on AUDJPY and NZDJPY**, which takes median body-over-range from 0.463 to 0.268 and `levels.chains` from **83 displacement legs in 19 years to 4** |
| **Are up moves longer and slower, down faster and deeper?** | **Yes, and it is stable across all 19 years rather than carried by 2008.** AUDJPY down swings are 33% faster per bar (speed gap **-0.285**, z -3.68), up swings 21% longer (+0.213, z +2.60); NZDJPY -0.252 / +0.219. **Dropping 2008 entirely changes it by 0.005 on AUDUSD and 0.003 on USDCHF**, and the speed gap is negative in **6 of 6 eras** on both against **3 of 6** on the placebo |
| Is it the path, or the return distribution? | **On the crosses, the distribution. On two legs, about a quarter is not.** No carry cross exceeds its hardest null arm on any statistic - NZDJPY's -0.252 is matched by a memory-free `bar-shuffle` at **-0.252**. But **AUDUSD (+0.066) and USDCHF (+0.077) exceed every arm**, 22% and 29% of the raw effect, and they are exactly the high-yield leg and the safe-haven leg the framing names. Gaussian GARCH reads **-0.093 to +0.081 on all fourteen instruments**, so clustering contributes nothing and the mechanism is return skewness |
| So is the asymmetry tradeable as a sequence rule? | **Not on this evidence, and the order is untested rather than null.** The power sweep drives the duration gap from -0.033 to **+0.557** by changing the up-bar share alone with the shuffle tracking it to +0.530, so the statistic is close to a marginal statistic by arithmetic; its zero cell reads **-0.002 +- 0.018**, correctly empty. But the **pure-order plant failed its own zero control** - excess **-0.180 at z -4.76 where nothing is planted** - so it was rejected and there is no calibrated test here for a path effect. 5 of 42 cells exceed the hardest arm against 2 expected, and **none at both swing scales**, so the pre-registered consistency rule fails |
| Does a fear/greed label on a level's formation carry anything? | **Nothing survives, and three of the four books cannot answer** - but this is the one section with **no power statement**, so read it as a sample-size verdict rather than a null. `Levels` and `BjorgumLevels` publish 2-6 crash-labelled levels with a touch per instrument over 19 years; only `Pivots`, the **no-parameter control**, has a usable sample (164-209). Its fear-minus-greed hold gap is +0.061/+0.128 pooled, +0.055/+0.063 within strata, and **-0.203/-0.008 de-overlapped** - the sign flips when the overlap is removed |
| Does the basket index predict a level's hold? | **No.** AUC 0.436-0.557 pooled and 0.433-0.525 within strata for `volatile_off`; 0.441-0.553 and 0.433-0.527 for `directional_off`. Both halves sit on 0.5 |
| **Does the short-the-cross trade pay?** | **No. The short arm is the flat one and the long arm is the carry trade.** AUDJPY short reads **-0.0002R** ungated and **-0.0862R** on the volatility gate; long reads **+0.2030R** and **+0.2301R**. And the placebo EURGBP reads **+0.1073R short**, so a positive mean R here is the race geometry, not carry |
| Is direction inside a volatility state the open question it was said to be? | **Measured, null, and one apparent signal in it is circular.** The volatility half carries no direction even conditioned (down-share 0.542 to 0.465 across its whole range on AUDJPY). The direction half *looks* strong - down-share **0.622 against 0.357** - until the placebo: EURGBP's legs are the two excluded from the index, and its conditioning is **0.468 against 0.507**, flat. The index was reading each instrument's own direction back to itself. The 4-cell interaction's **largest readings are the placebo's** (+0.245 to -0.270 against AUDJPY's -0.006 to -0.151) |
| So is the interaction closed? | **No - open, and this sample cannot close it.** The trade arm's version (`volatile_off` **and** `directional_off` both in their top fifth) reads -0.0010R short on AUDJPY on 65 trades against +0.1970R long, and at sd 1.33 its 95% interval is +-0.31R. The bound that *is* firm: **a conditional drift above a tenth of a stop over the 20-bar hold would have been seen** |
| What would it have found? | **A conditional drift of 0.10 volatility units over the 20-bar hold reads +0.43R**, monotone and steep from there. The real gated short arm reads -0.09 to +0.03R, so the conditional drift is bounded **well under 0.10 units** - under a tenth of a stop. Run on the placebo at 2 draws, so transferring the bound assumes the slope in drift carries across instruments at the same stop and horizon |
| Does `Mood`'s +-0.5 ever fire? | **Not on anything market-like, and nothing keys on it.** The basket index's 90th percentile is **+0.152 to +0.189** over 19.25 years. A single instrument needs a noiseless **75% up-rate** to reach +0.5 - 67% reads +0.499, just under. Every gate here uses a **trailing** quantile and reports the absolute boundary it lands on: **+0.10 at the 80th percentile, +0.15 at the 90th** |

**Nothing in this document is priced.** The primary result is gross and says so
in every table. See [Costs](#costs-and-what-this-store-cannot-supply).

## What has actually been run, and what has not

**This matters for how much weight each section carries, so it is stated before
the results rather than in a footnote.**

| section | coverage | arms |
|---|---|---|
| **1. the 2008 control and the triangle** | **complete** - all 6 crosses, all 4 calendar shifts, the full basket | the planted-crash sweep at **3 draws a depth** |
| **3. the asymmetry** | **complete** - 14 series x 2 swing scales x both pivot kinds, 1,012 rows | **all 5 null arms x 4 draws + 2 diagnostics** |
| **6. the conditioning** | 3 series (audjpy, audusd, eurgbp) x 2 swing scales | real arm only |
| 4. the level labels | **2 of 8 legs** (audusd, usdjpy) x 4 books | **real arm only - no surrogate arms yet** |
| 5. the trade | **3 of 14 series** x 5 gates x the 2:1 race x both sides | **real arm only - no surrogate arms, no duty-cycle twin yet** |
| the power sweeps | asymmetry on 2 feeds at `reach` 10, **8 plants a strength with matched twins**; the trade on eurgbp; the planted crash at 3 draws a depth; the level plant on audusd/`pivots` at 2 draws | **the level plant was rejected** - it fails its own zero control and has no dose response even at a hard wall. Section 4 therefore has no power statement |

Sections 1 and 3 are panel results. **Sections 4 and 5 are single-box
reconnaissance on a subset and their nulls have not been run** - the harness
runs all of it in one invocation and the command is below, but what is written
here for those two sections is the real arm alone. Section 5's conclusion rests
on the **EURGBP placebo** rather than on surrogates for exactly that reason,
and the surrogate comparison is the thing to read first when the panel lands.
The two other `RACES` rows (1:1 and 1:2) and the 15m rule are in the harness
and are not reported here. One of the asymmetry run's 1,012 lines was torn by
an overlapping launch and is skipped by the report, which now counts and prints
what it skipped rather than failing on it.

## The rules, as frozen before the run

* **Instruments.** Eight real legs (`audusd`, `nzdusd`, `usdcad`, `usdjpy`,
  `usdchf`, `eurusd`, `gbpusd`, `gold`) and six synthetic crosses, laid out as
  a 2x2 in the two legs the carry story needs:

  | cross | built as | kind |
  |---|---|---|
  | `audjpy` | AUDUSD x USDJPY | carry + haven |
  | `nzdjpy` | NZDUSD x USDJPY | carry + haven |
  | `cadjpy` | USDJPY / USDCAD | carry + haven |
  | `audchf` | AUDUSD / USDCHF | carry + haven |
  | `eurchf` | EURUSD / USDCHF | haven only |
  | `eurgbp` | EURUSD / GBPUSD | placebo - neither |

* **Venue: OANDA, every interval.** It is the only venue in the store whose
  gold and FX daily bars share a timestamp - SAXO stamps gold at 22:00 and FX
  at 21:00, so their daily intersection is empty - and a cross built from two
  venues' legs is two clocks multiplied together. 4,980 bars common to all
  eight feeds, 2007-05-16 to 2026-08-13, **19.25 years**. FX_IDC and SAXO carry
  4,999 for the five cross legs alone and no usable gold.
* **Interval: 1d is primary**, and 15m is a **separate rule** (4,760 bars,
  about 50 days) never pooled with it, because the swing length, the volatility
  unit and the hold all scale with the bar.
* **The reading is `FearGreed`** (`till_infinity/indicators/sentiment.py`) at
  its module defaults, `span` 60 and `warmup` 20, **not tuned**. Every result
  is reported as `volatile` and `directional` separately, never as the
  composite alone.
* **The index is a basket of the six real legs**, each component oriented to
  risk-off by `RISK_OFF_SIGN`, positive meaning risk-off. `expansion` is
  oriented **without** the quote flip because ranges widen in a panic whichever
  way a pair is quoted; flipping it would make audusd's and gold's
  contributions equal and opposite and the index would read a range explosion
  as zero.
* **Shape labels.** `CRASH` / `SPIKE` where a confirmed `levels.chains`
  displacement leg ran down or up and **ended within 5 bars**; `RUN` where no
  leg ended in reach and `trend.ratio` over the trailing 12 closes is at least
  0.50; `NEITHER` otherwise. Every displacement parameter is the module default
  (`push_min` 2, `push_body` 0.70, `chain_gap` 1).
* **Level books**: `Levels`, `BjorgumLevels.measured()`, `Pips`, `Pivots`, all
  at module defaults. `Pivots` is the **no-parameter control** - arithmetic on
  the prior period's range, nothing to fit.
* **Gates are causal.** A trailing quantile over the prior 500 bars at the 80th
  percentile. No whole-sample quantile anywhere, and no gate reads `Mood`.
* **Null arms**, four draws each, every one through the same detector over the
  same bar geometry: `garch-bars` (clustering, no skew), `walk-geometry` and
  `bar-shuffle` (absolute step distribution and wickiness, no memory), and -
  **added mid-study, see deviation 5** - `log-walk` and `log-shuffle`, the same
  two on log returns with the range carried as a share of price. Plus two
  deterministic **diagnostics** that are not nulls: `sign-flip` and
  `drift-free`. A finding is scored against the **extreme of all twenty
  surrogate draws**, not against the mean of one arm.
* **Direction pre-stated for the asymmetry and one-sided**: `bars` positive,
  `size` negative, `speed` negative. **Two-sided for the level label**, because
  unlike a barrier claim the framing does not fix a sign and pretending to have
  pre-stated one would be choosing it afterwards.
* **A finding needs** the real value outside the hardest null arm's range over
  its draws, the sign consistent across a majority of instruments, presence
  **within strata** of trailing compression, and survival of Benjamini-Hochberg
  over every cell.

### Deviations from the pre-registration

Four, all recorded rather than quietly fixed.

1. **`eurchf` was pre-registered as the placebo and is not one.** The grounds
   were that EUR and CHF were both low-yield across this window, which is true
   about yields and wrong about havens: CHF *is* a haven, and EURCHF duly fell
   **31.6%** in the same 2008 window where the carry crosses fell 32.6-44.5%.
   It is relabelled "haven only", which isolates the haven leg and is the more
   useful control, and **`eurgbp` was added** as the placebo that was missing.
   It falls 10.5% in the same window.
2. **The third criterion of the 2008 control was wrong as written.** "The
   single most risk-off day of the 19.25 years falls inside the window" assumed
   2008 was the largest risk-off event in the sample, which is a claim about
   the world rather than about the reading. It is not: March 2020 is larger on
   a 60-bar reading, because 2008 was deeper but slower. Reported as failed.
3. **The label was redefined from "the bar is inside a leg" to "a leg ended
   within 5 bars".** The strict version gave **zero** crash-formed levels with
   a touch on audusd, and the cause was not rarity but anti-correlation: a
   level forms at a *pivot* and a displacement is a *run*, so the two shapes
   avoid each other. "A level formed at a crash" means the crash left the level
   behind. 0, 3 and 10 are reported as a sensitivity below.
4. **A second swing scale was added.** `trend.REACH` 3 gives a median swing of
   4 bars, and the 2008 AUDJPY unwind ran 60 bars peak to trough - which a
   reach-3 detector chops into roughly fifteen swings. Reporting only the
   repo's default would have tested the claim at the wrong scale and called it
   a null. `reach` 10 is carried beside it as a second **named rule**, not a
   sweep.
5. **Two null arms were added mid-study**, `log-walk` and `log-shuffle`,
   because the three pre-registered arms were **wrong for this window**.
   `bar-shuffle` and `walk-geometry` permute *absolute* close-to-close steps -
   which is `level-shield.md`'s construction, sound over 76 days of 15-minute
   bars - and this study's level moves by a factor of 2.06 on audjpy and
   **8.45 on gold**, so the arms were pasting 2026 steps onto 2007 prices. The
   two kinds of shuffle disagree on audjpy's duration gap by **+0.142 against
   +0.236**, more than the effect being measured. Adding arms after seeing
   results is a hole in a pre-registration; it is recorded here, the old arms
   are retained and reported, and the hardest-arm test now takes the extreme
   over all five. The defect was found by the power sweep rather than by
   review - see the end of section 3.

## 1. The 2008 carry crash, and the triangle

### The triangle is an alignment test, not a discovery

For a cross built by multiplying its legs the identity is exact in logs, so the
regression `currency-triangles-are-the-positive-control` asks for is degenerate
by construction: weights 1.0 to machine precision and t statistics at 1e15,
which is a statement about float arithmetic. The number worth quoting is the
**log-price deviation**, and the arm worth having is the one that makes the
check falsifiable:

| leg calendar shift | audjpy weights | r2 | max log-price deviation |
|---|---|---|---|
| **0** | **+1.0000, +1.0000** | **1.000000** | **8.9e-16** |
| 1 | -0.0162, -0.0898 | 0.003333 | 1.2e-01 |
| 2 | +0.0044, -0.0065 | 0.000030 | 1.6e-01 |
| 5 | -0.0461, -0.0280 | 0.001615 | 2.5e-01 |

**A one-bar calendar disagreement takes r2 from 1.000 to 0.003.** Without this
row "weights 1.0, t 1e15" would read the same if the whole study were
multiplying the wrong days together.

The synthesis also reproduces the world, which the triangle cannot check.
Synthetic AUDJPY peaks at **107.84 in 2007** and troughs at **55.79 on
2008-10-26**; synthetic NZDJPY reads 97.57 and 45.07, CADJPY 124.65 and 70.84.

**This store holds no real JPY cross, so that comparison is against published
history and not against a measurement here** - the widely quoted figures are
an AUDJPY peak near 108 in late 2007 and a trough near 55 in the last week of
October 2008. It is a sanity check on the magnitude and the date, not a
reconciliation, and it is the one check in this study that cannot be reproduced
from `.data/prices/prices.db`. It is worth having anyway: an exact triangle
says the arithmetic is right, and only an outside reference says the *legs* are
the pairs their names claim.

### The control

| reading | window mean | rank | window max | sample q99 | peak pct | global argmax |
|---|---|---|---|---|---|---|
| `risk_off` | **+0.1276** | **1 / 28** | **+0.3308** | +0.3060 | 0.9938 | 2020-03-08 (out) |
| `volatile_off` | +0.1162 | 2 / 28 | **+0.5125** | +0.4476 | 0.9956 | 2020-03-08 (out) |
| `directional_off` | **+0.1352** | **1 / 28** | +0.3247 | +0.3353 | 0.9873 | 2008-01-20 (out) |

**Breadth at the index's peak: 6 of 6 legs.** The most risk-off day of 19.25
years has every basket leg reading risk-off at once, which is the one thing a
published fear index has that a single instrument cannot.

Criterion 1 (peak clears q99) passes on `risk_off` and `volatile_off` and fails
narrowly on `directional_off` (98.73rd percentile against the 99th). Criterion
2 (largest of the non-overlapping windows) passes on `risk_off` and
`directional_off` and reads 2nd on `volatile_off`. Criterion 3 fails on all
three, and deviation 2 above says why it was a bad criterion.

**The direction half is the stronger of the two in this window** - window mean
+0.1352 against +0.1162, rank 1 against rank 2 - which is worth recording
against the standing expectation that the volatility half would carry it. The
volatility half has the larger *peak* (+0.5125 against +0.3247); the direction
half has the more sustained reading.

The crosses over the same window:

| cross | kind | peak | trough | drawdown | bars |
|---|---|---|---|---|---|
| audjpy | carry + haven | 100.62 | 55.79 | **-44.5%** | 60 |
| nzdjpy | carry + haven | 78.99 | 45.07 | -42.9% | 129 |
| cadjpy | carry + haven | 105.12 | 70.84 | -32.6% | 108 |
| audchf | carry + haven | 0.89 | 0.50 | -43.7% | 78 |
| eurchf | **haven only** | 1.49 | 1.02 | **-31.6%** | 78 |
| eurgbp | **placebo** | 0.98 | 0.87 | **-10.5%** | 29 |

**Most of the 2008 move is the haven leg.** EURCHF, which has a haven and no
carry leg, falls 31.6% where the carry crosses fall 32.6-44.5%; the placebo
with neither falls 10.5%. The carry leg adds 1 to 13 points on top of the haven
leg's 32. That is a decomposition the framing does not make and it matters for
anything built on this: the tradeable part of a risk-off event here is mostly
long-haven, not short-carry.

### The six most risk-off windows in 19.25 years

| window | mean `risk_off` |
|---|---|
| **2008-08-03 .. 2009-03-31** | **+0.1276** |
| **2024-07-17 .. 2025-03-18** | **+0.1126** |
| 2019-03-19 .. 2019-11-14 | +0.0915 |
| 2014-07-20 .. 2015-03-18 | +0.0895 |
| 2011-03-27 .. 2011-11-21 | +0.0860 |
| 2022-07-18 .. 2023-03-16 | +0.0636 |

The top two are the **two largest yen-carry unwinds in the window** - the 2008
crash and the August 2024 unwind. Nothing in the construction told the index to
find either; the second is not in the pre-registration and is the strongest
single piece of evidence here that the reading is measuring the thing it is
named after.

### Power for the control, which a control expected to pass still needs

Every basket leg replaced by a `walk-geometry` surrogate - no 2008 - and a
crash of known depth spread over 68 bars at a random start, with each leg's own
risk-off sign. Three draws per depth. Chance is 0.0137.

| planted depth | index argmax in window | `volatile_off` | `directional_off` |
|---|---|---|---|
| **0.00** | **0 / 3** | 0 / 3 | 0 / 3 |
| 0.05 | 0 / 3 | 0 / 3 | 1 / 3 |
| 0.10 | 1 / 3 | 0 / 3 | 2 / 3 |
| **0.20** | **3 / 3** | 0 / 3 | 2 / 3 |
| 0.30 | 3 / 3 | 2 / 3 | 3 / 3 |
| 0.45 | 2 / 3 | 2 / 3 | 3 / 3 |

**The control sees a 20% crash and goes blind between 0.05 and 0.10.** At
strength 0 it correctly reads nothing, which is the arm that must come back
empty.

One caveat on the volatility half, and it is the plant's limitation rather than
the index's: **the planted crash is a smooth drift, so it does not widen
ranges**, and `expansion` is a range statistic. The direction half sees the
plant from 0.05 where the volatility half needs 0.30. On a real crash
volatility explodes, which is why `volatile_off` has the larger peak in 2008
than the planted sweep would suggest. The plant understates the volatility
half.

**And the power arm caught its own sign error.** The first version used
`log1p(-depth)`, which is negative, and so planted a *rally*: the index's
argmax missed the planted window at every depth and the window's peak
percentile *fell* from 0.98 to 0.08 as the crash got deeper. A planted effect
with one sign backwards reads exactly like a test with no power, and this is
what the arm is for.

## 2. The synthetic cross's range is a bound, and it is not a small one

The product of two daily highs is the daily high of the product only if both
legs printed their high in the same instant. Measured rather than assumed:
median bar range over median absolute close-to-close move, 1d, 4,980 bars.

| instrument | range / \|dclose\| | implied range inflation |
|---|---|---|
| nzdusd | 2.300 | - |
| eurusd | 2.319 | - |
| gbpusd | 2.322 | - |
| usdcad | 2.336 | - |
| audusd | 2.344 | - |
| usdchf | 2.356 | - |
| gold | 2.412 | - |
| usdjpy | 2.439 | - |
| **audjpy** | **4.027** | **1.72x** |
| **nzdjpy** | **4.096** | **1.75x** |
| cadjpy | 3.589 | 1.53x |
| audchf | 2.785 | 1.19x |
| eurchf | 2.447 | 1.05x |

**All eight real instruments cluster in a band 0.139 wide** - 2.300 to 2.439 -
which is what makes the cross's excess over it readable as bound inflation
rather than as a property of the instrument. The inflation column is against
the real band's **median of 2.340**.

`RANGE_OVER_STEP`, which converts a cross's close-step volatility unit onto the
same scale as a leg's range unit, is **2.39** - fixed from the first six
instruments measured and 2% above the eight-instrument median. It is kept
rather than re-centred: it scales every distance on a cross by 2%, two orders
of magnitude below anything measured here, and re-centring would invalidate
every number already taken on it.

The direction follows from the quote convention and is why EURCHF escapes:
AUDUSD and USDJPY sit on **opposite sides of the dollar**, so AUDUSD's high and
USDJPY's high are two moves that never co-occurred. EURUSD and USDCHF move
together against the dollar, so a *quotient* takes EURUSD's high over USDCHF's
low - nearly the same instant - and the bound is tight.

What it costs, audjpy against audusd over the same 4,980 days:

| | audusd | audjpy |
|---|---|---|
| median body / range | **0.463** | **0.268** |
| share of bars with body >= 0.70 of range | **0.211** | **0.045** |
| `levels.chains` displacement legs in 19 years | **83** | **4** |

So a displacement, a candle shape, a level book and an EWMA-of-range volatility
unit are all unusable on a JPY cross. The study is split accordingly:

* **close-exact on a cross** - `open`, `close`, every return, a swing
  decomposition on closes, a barrier race on closes, and `FearGreed`'s
  `pressure` and `skew`, both of which read returns only;
* **range-dependent, so real legs only** - the level books, `Displacement`,
  `Candles`, and `FearGreed`'s `position`, `conviction` and `expansion`.

That split is why the fear reading is a **basket of real legs** rather than a
cross's own `FearGreed`, and why the level study runs on the eight legs while
the crosses carry the trade and the swing asymmetry.

## 3. The asymmetry: real, stable across 19 years, and mostly the return distribution

`reach` 10 close pivots, 1d, log-mean gaps of up swings against down swings.
Pre-stated direction: `bars` positive, `size` negative, `speed` negative. z is
on a day-block bootstrap standard error over whole days. Five null arms, four
draws each, shown as the mean with the range over draws; `sign-flip` and
`drift-free` are diagnostics, not nulls.

### The speed gap: down swings are faster

| instrument | kind | real | z | `garch-bars` | `bar-shuffle` | `log-shuffle` | `log-walk` | `sign-flip` | `drift-free` |
|---|---|---|---|---|---|---|---|---|---|
| audjpy | carry+haven | **-0.285** | -3.68 | +0.049 | -0.172 [-0.22,-0.11] | -0.258 [-0.28,-0.24] | -0.220 [-0.34,-0.09] | +0.308 | -0.272 |
| nzdjpy | carry+haven | **-0.252** | -3.49 | +0.003 | **-0.252** [-0.40,-0.12] | -0.060 | -0.178 | +0.278 | -0.245 |
| cadjpy | carry+haven | -0.167 | -2.13 | +0.066 | -0.175 [-0.27,-0.08] | -0.072 | -0.192 | +0.186 | -0.160 |
| audchf | carry+haven | -0.016 | -0.22 | -0.021 | -0.041 | +0.069 | +0.030 | +0.053 | -0.065 |
| eurchf | haven | +0.120 | +1.50 | -0.074 | +0.025 | +0.065 | +0.137 | -0.086 | +0.130 |
| **eurgbp** | **placebo** | **-0.032** | -0.46 | -0.037 | +0.068 | +0.084 | +0.096 | +0.046 | -0.016 |
| **audusd** | leg (carry) | **-0.297** | **-4.56** | +0.004 | -0.101 [-0.23,+0.02] | -0.106 [-0.14,-0.02] | -0.029 | +0.325 | -0.302 |
| nzdusd | leg (carry) | -0.120 | -1.88 | +0.029 | -0.058 | -0.006 | -0.022 | +0.152 | -0.120 |
| usdjpy | leg (haven) | -0.119 | -1.58 | -0.037 | -0.126 | -0.046 | -0.024 | +0.140 | -0.080 |
| **usdchf** | leg (haven) | **-0.261** | **-3.08** | -0.093 | -0.070 [-0.18,+0.05] | -0.097 [-0.14,-0.06] | -0.033 | +0.285 | -0.277 |
| usdcad | leg (carry) | +0.077 | +1.06 | +0.025 | -0.027 | +0.079 | +0.026 | -0.059 | +0.054 |
| gold | leg (haven) | -0.185 | -2.79 | +0.081 | -0.085 [-0.18,+0.02] | +0.009 | -0.045 | +0.226 | -0.164 |
| eurusd | leg | -0.038 | -0.65 | -0.020 | -0.100 | -0.012 | -0.001 | +0.059 | -0.015 |
| gbpusd | leg | -0.013 | -0.21 | -0.043 | -0.081 | -0.049 | -0.028 | +0.034 | -0.014 |

A speed gap of -0.285 means **down swings are 33% faster per bar**. The
duration gap is positive on the same instruments - audjpy **+0.213** (z +2.60),
nzdjpy +0.219 (+2.60), gold +0.233 (+2.93), audusd +0.186 (+2.30) - so **up
swings are 20-26% longer**. At `reach` 3 the same signs appear about 40%
smaller (audjpy +0.194 / -0.165, audusd +0.156 / -0.119, eurgbp -0.038 /
+0.027).

### What the arms say

**Five of 42 cells at `reach` 10 exceed the hardest null arm; 1 of 42 at
`reach` 3.** The hardest-arm test asks the real value to beat the extreme of 20
surrogate draws, so under the null each cell passes with probability about
1/21 and 42 cells give **about 2 by chance**. Two of the five are substantial
and three are not:

| cell | real | hardest null | excess |
|---|---|---|---|
| **usdchf speed** | -0.261 | -0.184 | **+0.077** |
| **audusd speed** | -0.297 | -0.231 | **+0.066** |
| nzdusd speed | -0.120 | -0.104 | +0.017 |
| usdjpy size | -0.042 | -0.037 | +0.005 |
| gold speed | -0.185 | -0.182 | +0.003 |

Four things fall out.

**On the synthetic crosses the effect is fully reproduced by a memory-free
surrogate.** NZDJPY real -0.252 against a `bar-shuffle` at **-0.252**
[-0.40,-0.12]; AUDJPY real -0.285 against `log-shuffle` -0.258 [-0.28,-0.24]
and `log-walk` -0.220 [-0.34,-0.09]; CADJPY -0.167 against -0.175 and -0.192.
A surrogate with **no memory whatsoever** gives the same answer, and
`let-the-shuffled-twin-name-the-mechanical-observables` said it would name the
mechanical part immediately. **None of the four carry crosses exceeds its
hardest arm on any statistic.**

**The two cells that do exceed are the two legs the framing names** - AUDUSD,
the high-yield leg that is sold in a risk-off event, and USDCHF, whose *fall*
is the safe haven being bought. Their excesses are +0.066 and +0.077, which is
22% and 29% of the raw effect. So whatever path component exists lives in the
**legs** and does not survive multiplying two of them into a cross. That is a
coherent reading - two legs' independent asymmetries combine into a cross whose
asymmetry is only the distributional part - and it is the opposite of what the
framing expected, which was that the cross would be where the effect
concentrates.

**Volatility clustering contributes nothing.** `garch-bars` is Gaussian, so it
has clustering and no skewness, and it reads **-0.093 to +0.081 across all
fourteen instruments** - zero everywhere. That rules out clustering as the
mechanism and leaves return skewness, which every shuffle arm keeps exactly.

**`sign-flip` is an exact mirror, which validates the statistic.** The
duration gap flips to the digit on every instrument (audjpy +0.213 to -0.213,
nzdjpy +0.219 to -0.219, gold +0.233 to -0.233) and the speed gap flips in
sign with its magnitude within 10%. An asymmetry that survived a return-sign
flip with its own sign would have been a defect in the measurement.

**`drift-free` separates the trend out, and only gold is a trend.** Gold's
duration gap falls from +0.233 to **+0.054**, a 77% reduction; audjpy's from
+0.213 to +0.180 (15%); audusd's does not fall at all (+0.186 to +0.216).
19 years of gold is not drift-free and a trending series has longer up swings
for an arithmetic reason.

**Benjamini-Hochberg over the 14 speed cells leaves 5 survivors** - audjpy,
nzdjpy, audusd, usdchf and gold - but that is BH on the **raw** day-block z,
which asks "is the asymmetry real" and not "does it exceed a surrogate". The
raw effect surviving is expected; the excess over the arms is the number that
decides, and it survives on two cells.

**It fails the pre-registered consistency requirement.** The sign has to hold
across both swing scales for the same cell, and the exceedances do not: usdchf
exceeds on `bars` at `reach` 3 and on `speed` at `reach` 10, and audusd
exceeds at `reach` 10 only. 5 of 42 against 2 expected, with no cell exceeding
at both scales.

### Eras: the asymmetry is not 2008

The question the framing rests on, and the answer is clear. Speed gap, `reach`
10, with 2008-01-01..2009-06-30 dropped and taken alone:

| instrument | pooled | 2008 dropped | 2008 only | eras negative |
|---|---|---|---|---|
| audjpy | -0.285 | **-0.257** | -0.593 | 5 of 6 |
| nzdjpy | -0.252 | **-0.198** | -0.877 | 5 of 6 |
| **audusd** | -0.297 | **-0.302** | -0.234 | **6 of 6** |
| **usdchf** | -0.261 | **-0.258** | -0.309 | **6 of 6** |
| gold | -0.185 | -0.175 | -0.299 | 5 of 6 |
| **eurgbp** (placebo) | -0.032 | -0.015 | -0.191 | **3 of 6** |

**Dropping 2008 changes almost nothing.** AUDUSD reads -0.302 without it
against -0.297 with it, USDCHF -0.258 against -0.261. The episode is *more*
extreme when taken alone - audjpy -0.593, nzdjpy -0.877 against pooled -0.285
and -0.252, on 20-22 swings - which is exactly the Brunnermeier-Nagel-Pedersen
description and is **not** what the pooled result rests on.

Per era, the speed gap is negative in **6 of 6 eras on AUDUSD** (-0.236,
-0.149, -0.358, -0.102, -0.517, -0.524) and **6 of 6 on USDCHF** (-0.205,
-0.130, -0.217, -0.179, -0.795, -0.112). The JPY crosses are negative in 5 of 6,
the exception being 2013-2015 for audjpy (+0.146) and 2010-2012 for nzdjpy
(+0.109). **The placebo is 3 of 6 - a coin flip** - which is what a null era
profile looks like and is the control that makes the 6-of-6 readings
meaningful.

So: **up slower and longer, down faster and deeper is a stable 19-year property
of these instruments and not one event.** What the nulls then say is that on the
crosses it is a property of the return distribution, and on two of the legs
about a quarter of it is not.

### Power: what the statistic sees, and the arm that failed its own control

Three plants on the same series, **eight independent plants per strength**,
each with the shuffle arm **matched to how it builds its path** - an
absolute-step plant gets `bar-shuffle`, a log-return plant gets `log-shuffle` -
so the paired excess is not contaminated by the arithmetic-against-log confound
at the end of this section.

| plant | what it changes | matched twin |
|---|---|---|
| `plant_up_share` | P(up) = 0.5 + k, i.i.d. | `bar-shuffle` |
| `plant_skew` | share `k` of large steps forced negative, variance held | `bar-shuffle` |
| `plant_sign_clustering` | the **exact multiset** of signed returns, reordered by a two-state Markov chain of persistence `p` | `log-shuffle` |

#### What it sees: the up-bar share, and the shuffle sees it too

audjpy, `reach` 10, duration gap, excess is real minus its own twin:

| strength | real | twin | excess | z |
|---|---|---|---|---|
| **k = 0.00** | -0.033 | -0.032 | **-0.002 +- 0.018** | **-0.08** |
| k = 0.02 | +0.179 | +0.115 | +0.063 | +1.58 |
| k = 0.05 | +0.274 | +0.280 | -0.005 | -0.27 |
| **k = 0.10** | **+0.557** | **+0.530** | +0.027 | +0.88 |

**The zero-strength cell reads -0.002 +- 0.018, which is the arm that must come
back empty coming back empty.** From there the duration gap runs to **+0.557**
at a 60% up-rate on audjpy and +0.552 on audusd, **and the twin tracks it to
+0.530 and +0.582** with the excess at zero throughout. The skew plant behaves
the same way: its zero cell is +0.044 +- 0.043, and real and twin then move
together (+0.034 to +0.112 against -0.010 to +0.107).

So the statistic is strongly sensitive to the **marginal** - the up-bar share
and the return skewness - and a memory-free shuffle reproduces that sensitivity
exactly. That is close to arithmetic rather than empirical: with a fixed
multiset of signed returns and alternating runs, the run-length ratio is pinned
by the up/down bar-count ratio, so "up moves longer" **is** "more up bars than
down bars".

#### What it cannot see, because the arm is not calibrated

`plant_sign_clustering` was built to be the pure **order** effect: same
multiset, only the sequence changed. It fails its own zero control.

| persistence | real | twin | excess | z |
|---|---|---|---|---|
| **p = 0.50 (i.i.d., no effect planted)** | **+0.020** | **+0.200** | **-0.180 +- 0.038** | **-4.76** |
| p = 0.55 | -0.019 | +0.160 | -0.179 | -5.37 |
| p = 0.60 | -0.052 | +0.209 | -0.261 | -8.93 |
| p = 0.70 | -0.011 | +0.167 | -0.178 | -8.66 |
| p = 0.80 | +0.035 | +0.195 | -0.160 | -3.89 |

**At p = 0.50 the plant is an i.i.d. sign sequence and nothing is planted, and
the excess is -0.180 at z -4.76.** The sweep is also flat above it: -0.180,
-0.179, -0.261, -0.178, -0.160, with no dose response in `p`. So the whole
column is the plant's own construction and not the planted effect - the
Markov chain draws signs at 50/50 while consuming from fixed up and down pools,
which is not the same object as a permutation of the real sign sequence, and
`log-shuffle` of the same returns reads +0.200 where the plant reads +0.020.

`finding-edges` is explicit about what to do with this: *a control that **must**
come back empty catches what a control that should come back smaller does not*.
This one did not come back empty, so **the arm is rejected and this study has
no calibrated test for a pure path effect.**

**The consequence for the verdict.** "A bar shuffle reproduces the asymmetry"
is established and is the right reading of section 3's tables. What is **not**
established is the stronger claim that there is therefore nothing in the order:
this study could not build an arm with a working zero control for that
question, so the order is **untested**, not null. A test for it needs a
statistic a shuffle changes - a run-length distribution conditioned on
something exogenous, or a conditional forecast - rather than a pooled
up-against-down contrast, and it needs a plant whose zero cell reads zero.

### A measurement defect, and the arm that caught it

**The absolute-step shuffle arms are wrong for a 19-year window and the log
arms were added after the fact.** `bar-shuffle` and `walk-geometry` permute and
resample *absolute* close-to-close steps, which is what
`research/docs/level-shield.md` does and is sound there - 76 days of 15-minute
bars move a few percent. Over this window the level moves by a factor of
**2.06 on audjpy, 2.19 on nzdjpy and 8.45 on gold**, so permuting absolute
steps puts a 2026 gold step on a 2007 gold price.

Measured consequence on audjpy's duration gap: **+0.142 on the absolute-step
shuffle against +0.236 on the log-return shuffle**, with the real value at
+0.213 between them. The two arms disagree by more than the effect, so no
verdict can rest on the absolute-step arm alone. `log-shuffle` and `log-walk`
preserve the log-return marginal exactly and carry the range as a share of
price; both are now in `NULL_ARMS` and the hardest-arm test takes the extreme
over all five.

This was found by the power sweep rather than by review: the sign-clustering
plant is built from log returns and its own `bar-shuffle` twin was built from
absolute steps, and the two disagreed at strength 0.5 where they should have
agreed exactly.

### A discreteness defect this study walked into

At `reach` 3 the median swing is **4 bars on 8 of 9 instruments**, so the
original statistic - the log of the ratio of medians - read **exactly 0.000**
on every one of them, and its day-block standard error read 0.000 too. A
statistic quantised at the point it is evaluated reports a clean null it has no
power to refute. The statistic is now the **mean of logs**, which is smooth,
and that is why the tables above exist at all. This is the discreteness version
of `sweep-thresholds-on-the-mean-not-z`.

## 4. The level formation label: null, and three books cannot answer

Real legs only. `horizon` 20 bars, touch tolerance `TOUCH_NOISE_VOL` 0.40
units, hold = the close 20 bars after the first touch is still on the approach
side. **Two of the eight legs and the real arm only** - the surrogate arms for
this section are unrun, so what follows is a sample-size verdict and a sign
check, not a null-tested one.

| feed | book | levels | touched | crash hold | spike hold | f-g pooled | within strata | de-overlapped |
|---|---|---|---|---|---|---|---|---|
| audusd | `levels` | 295 | 196 | 0.500 (n 4) | 0.556 (n 9) | -0.056 | - | - |
| audusd | `bjorgum` | 141 | 81 | 0.500 (n 2) | 0.667 (n 3) | -0.167 | - | - |
| audusd | `pips` | 4,406 | 747 | 0.714 (n 42) | 0.625 (n 32) | +0.089 | +0.043 | - |
| **audusd** | **`pivots`** | 4,590 | 3,246 | **0.593 (n 209)** | **0.533 (n 199)** | **+0.061** | **+0.055** | **-0.203** |
| usdjpy | `levels` | 316 | 218 | 0.667 (n 6) | 0.455 (n 11) | +0.212 | - | - |
| usdjpy | `bjorgum` | 156 | 102 | 0.500 (n 2) | 1.000 (n 3) | -0.500 | - | - |
| usdjpy | `pips` | 4,550 | 796 | 0.444 (n 27) | 0.541 (n 61) | -0.097 | - | - |
| **usdjpy** | **`pivots`** | 5,073 | 3,579 | **0.591 (n 164)** | **0.463 (n 326)** | **+0.128** | **+0.063** | **-0.008** |

**Three of the four books cannot answer the question.** `Levels` keeps 24
levels and forgets after 500 bars, so it publishes about 300 distinct levels
over 4,980 days; crossed with a crash class that is 3-5% of bars that leaves
**2 to 6 crash-labelled levels with a touch**. `BjorgumLevels` is worse.
Reporting a gap of -0.500 on n 2 against n 3 as a result would be the
`pool-events-before-a-per-feed-guard` failure, where a min-events guard dropped
141 of 146 feeds and made 0.9 sigma look like 4.8.

**Only `Pivots` has a usable sample, and `Pivots` is the no-parameter
control** - arithmetic on the prior period's range, nothing to fit. Its gap is
+0.061 and +0.128 pooled, falls to +0.055 and +0.063 within compression
quintiles, and **changes sign to -0.203 and -0.008 when the outcome windows are
de-overlapped**. A sign that flips on de-overlapping is the
`overlapping-windows-inflate-permutation-nulls` signature, which turned a level
finding at p 0.015 into anchor overlap.

And the mechanism is visible in the counts. `Pivots`' 4,590 "levels" are not
4,590 independent levels: they are a **new daily set of up to nine correlated
prices**, about one new price a day over 4,980 days, and 3,246 of them get a
touch inside 20 bars. Nine prices computed from the same prior day's range,
tested in the same week, share almost everything. So the dense number is the
one with 3,246 rows behind it and the de-overlapped one is the one with
independent rows behind it, and they disagree in sign. That is the whole
finding for this section.

The pre-registered prediction was that the raw gap would be non-zero and would
be the volatility term, going away within strata. **It half holds**: the gap
shrinks within strata (+0.128 to +0.063) but does not vanish, and then inverts
on de-overlapping - so the residual is overlap rather than a volatility
residual. Either way nothing survives.

### Neither half of the index predicts a hold

AUC for the hold, pooled and within compression quintiles:

| feed | book | `volatile_off` | `directional_off` |
|---|---|---|---|
| audusd | `levels` | 0.557 / 0.525 | 0.450 / 0.433 |
| audusd | `pips` | 0.436 / 0.472 | 0.484 / 0.492 |
| audusd | `pivots` | 0.483 / 0.490 | 0.495 / 0.495 |
| usdjpy | `levels` | 0.446 / 0.435 | 0.466 / 0.451 |
| usdjpy | `pips` | 0.459 / 0.466 | 0.517 / 0.522 |
| usdjpy | `pivots` | 0.489 / 0.513 | 0.526 / 0.527 |

Every cell is on 0.5. Worth noting against
`auc-is-free-on-volatility-targets`, which records 0.805 on a
constant-volatility process and 0.525 within strata: here the **pooled** AUC is
already 0.44-0.56, so the hold outcome is not a volatility target in disguise
and the strata control has little left to remove.

### Power for this section: the arm was built, run, and rejected

`plant_label_hold` takes a `walk-geometry` surrogate, reads its **own** causal
`Pivots` book and shape labels off it, and then reflects every step that would
cross a **crash-labelled** level about that level with probability `strength`.
Spike-labelled and unlabelled levels are left alone, so what is planted is the
**label gap** rather than a general barrier. audusd, `pivots`, 2 plants a
strength.

| planted strength | recovered fear-minus-greed gap | crash levels |
|---|---|---|
| **0.00 (nothing planted)** | **+0.0971** | 175.5 |
| 0.10 | -0.0652 | 175.0 |
| 0.25 | -0.0482 | 169.5 |
| 0.50 | +0.0845 | 174.5 |
| 0.75 | -0.0475 | 151.0 |
| **1.00 (hard walls at the fear levels)** | **-0.0008** | 235.5 |

**It fails on both counts.** The zero cell reads +0.0971 where it must read 0,
and there is no dose response at all - a book of **hard walls at every crash
level** recovers -0.0008, when it should recover a large positive gap. At two
draws the per-cell standard error is about 0.039 on its own binomial
arithmetic (175 crash levels at a hold rate near 0.55, differenced against the
spike class), so the whole column is inside noise. The arm is rejected.

**And the reason it cannot be fixed by adding draws is the useful part.** The
plant reflects price about crash-labelled levels, which **changes the path** -
and the measurement then recomputes the book and the shape labels *on the
planted series*, where different bars are crash bars and different prices are
levels. **The act of planting destroys the association being planted.**
`research/docs/level-shield.md`'s barrier plant does not hit this because it
reflects at *every* level in the book, so there is no label to be reassigned;
a label-conditional plant has no such escape.

So a power statement for a label-conditional level claim needs a different
construction - planting the label on an exogenous variable the reflection
cannot move, or generating the path and the labels jointly - and this study
does not have one. **Section 4's "nothing survives" is a sample-size verdict,
not a measured null**, and that is the largest remaining gap here.

### The label definition sensitivity

Share of bars in each class, by how many bars back a leg may have ended:

| reach | audusd crash / spike | usdjpy crash / spike | gold crash / spike | both |
|---|---|---|---|---|
| 0 | 0.0102 / 0.0096 | 0.0064 / 0.0155 | 0.0046 / 0.0157 | 0.0000 |
| 3 | 0.0371 / 0.0345 | 0.0235 / 0.0512 | 0.0175 / 0.0534 | 0.0002 |
| **5** | **0.0544 / 0.0506** | **0.0343 / 0.0723** | **0.0259 / 0.0765** | **0.0012** |
| 10 | 0.0940 / 0.0902 | 0.0610 / 0.1209 | 0.0468 / 0.1323 | 0.0044 |

**Spike levels outnumber crash levels 2 to 3 to one on usdjpy and gold** at
every reach, which is a fact about the instruments rather than about the label:
`levels.chains` needs two consecutive 70%-body candles of the same sign, and
those are more common upward on a haven that grinds up and gaps down.

## 5. The trade: the short arm is flat and the long arm is the carry trade

1d, target 2.0 units and stop 1.0 unit, race on **closes**, horizon 20 bars,
one position at a time, **gross**. Gate = trailing 80th percentile of the named
reading over the prior 500 bars. **Three series and the real arm only**; the
1:1 and 1:2 races, the other eleven series and every surrogate arm are in the
harness and unrun.

| feed | gate | side | n | duty | mean R | sd | 95% day-block CI | PF | win | trades for 95% |
|---|---|---|---|---|---|---|---|---|---|---|
| audjpy | all | **short** | 471 | 0.90 | **-0.0002** | 1.31 | [-0.120, +0.117] | 1.000 | 0.363 | inf |
| audjpy | all | long | 454 | 0.90 | **+0.2030** | 1.37 | [+0.071, +0.311] | 1.378 | 0.436 | 117 |
| audjpy | `volatile_off` | **short** | 164 | 0.31 | **-0.0862** | 1.29 | [-0.276, +0.139] | 0.863 | 0.323 | inf |
| audjpy | `volatile_off` | long | 148 | 0.31 | +0.2301 | 1.39 | [+0.017, +0.410] | 1.428 | 0.453 | 93 |
| audjpy | `directional_off` | short | 157 | 0.29 | +0.0317 | 1.36 | [-0.144, +0.241] | 1.052 | 0.357 | 4836 |
| audjpy | `directional_off` | long | 158 | 0.31 | +0.1708 | 1.36 | [-0.009, +0.396] | 1.311 | 0.424 | 163 |
| audjpy | **`both`** | short | 65 | 0.12 | **-0.0010** | 1.33 | [-0.303, +0.331] | 0.998 | 0.338 | inf |
| audjpy | `both` | long | 68 | 0.14 | +0.1970 | 1.38 | [-0.068, +0.565] | 1.359 | 0.441 | 125 |
| nzdjpy | `volatile_off` | short | 159 | 0.30 | -0.0683 | 1.30 | [-0.266, +0.139] | 0.892 | 0.340 | inf |
| nzdjpy | `volatile_off` | long | 158 | 0.31 | **+0.2946** | 1.37 | [+0.097, +0.471] | 1.589 | 0.487 | 56 |
| **eurgbp** | all | **short** | 444 | 0.90 | **+0.1073** | 1.35 | [-0.002, +0.239] | 1.188 | 0.403 | 411 |
| **eurgbp** | all | long | 433 | 0.90 | +0.0710 | 1.35 | [-0.055, +0.179] | 1.124 | 0.393 | 915 |

**The framing's trade is the one that does not work.** Short the carry cross on
a risk-off reading: -0.0002R ungated, **-0.0862R on the volatility gate**,
-0.0010R on the interaction gate. The long arm pays +0.17 to +0.29R throughout.

**And the placebo is the reason not to celebrate the long arm.** EURGBP, with
neither a carry nor a haven leg, reads **+0.1073R short and +0.0710R long** -
both positive. A positive mean R in this race is therefore not a carry
property; it is the race geometry, which is exactly what
`research/docs/level-shield.md` measured when it found a bar-level barrier race
departing from the analytic 1/(1+N) by -0.25 to +0.12R. **No arm here is
compared against the closed form**. The surrogate arms are the comparison that
counts and **have not been run** - see "What has actually been run" above - so
this section's conclusion rests on the placebo, which is a weaker control.

**On the win rate, as the coordinator's correction asks.** The short arm's win
rate is 0.32-0.37 and that is not why it is rejected - the carry-crash shape
predicts a low win rate, and the long arm's 0.44-0.49 is not why it is
accepted. It is rejected on mean R with its own interval straddling zero, and
on `minimum_track_record`: at a mean of -0.09R and an sd of 1.29 the arm's own
arithmetic returns **inf** trades needed for a 95% probabilistic Sharpe, which
is the honest statement that it is not a small edge measured badly but no edge.
The `directional_off` short arm at +0.0317R needs **4,836 trades**; it produced
157 in 19.25 years, so at this firing rate it is unmeasurable for the next six
centuries. That is a different and cheaper decision than "it failed".

**The variances are comparable and the samples are not.** Every arm's sd sits
in 1.24-1.39, so comparing means across arms is fair here - which is not
something to assume, and is why the sd is in the table. What differs is n: the
interaction gate produces 65-71 trades, so its 95% interval is +-0.31R and
**anything smaller than a third of a stop is invisible to it.**

### Power for the trade

A `walk-geometry` path whose gated 20-bar windows are given a downward drift of
known size, scored by the same short arm. The **gate is computed on the real
basket index**, so the planted effect sits exactly where the test looks for
one. Run on **eurgbp** at 2 draws a drift.

| planted drift (units per horizon) | mean R |
|---|---|
| 0.00 | +0.0485 |
| **0.10** | **+0.4321** |
| 0.25 | +0.8768 |
| 0.50 | +1.4641 |
| 1.00 | +1.7610 |

**A conditional drift of a tenth of a stop over the hold would read +0.43R**,
and the response is monotone and steep from there. The real gated short arm
reads -0.09 to +0.03R, so the conditional downward drift inside the fear state
is bounded well below 0.10 volatility units over 20 bars.

Two caveats on reading it across instruments. The drift-0 row reads **+0.0485
rather than 0.000** - the race geometry again, and the baseline every other row
should be read against rather than zero. And the plant was run on **eurgbp**,
not on the carry crosses the bound is then applied to; the ungated real arms of
the two sit at +0.107 (eurgbp short) and -0.000 (audjpy short), so the geometry
baseline is close but not identical, and transferring the bound assumes the
*slope* in drift carries across instruments with the same stop distance and
horizon. At 2 draws there is no standard error on these rows.

### The measured boundary

`Mood`'s +-0.5 is conventional and unmeasured and nothing here keys on it. The
trailing quantiles of the basket index, as absolute readings:

| reading | q60 | q70 | **q80** | q90 |
|---|---|---|---|---|
| `risk_off` | +0.0507 | +0.0760 | **+0.1045** | +0.1520 |
| `volatile_off` | +0.0651 | +0.0907 | **+0.1271** | +0.1890 |
| `directional_off` | +0.0474 | +0.0789 | **+0.1268** | +0.1816 |

**The 90th percentile of the index is +0.15 to +0.19**, so a gate at +-0.5
refuses everything. If a boundary is wanted, **+0.10 is the 80th percentile and
+0.15 the 90th** on this basket.

Two things are being distinguished here and the distinction matters. The
**basket index** is a mean over six legs, so it is far tighter than any single
leg's own reading and never approaches +-0.5 over 19.25 years. A **single
instrument's** `FearGreed` can reach it, and
`test_the_conventional_threshold_needs_three_bars_in_four_going_one_way` pins
where: a noiseless series reads +0.391 at a 55% up-rate, **+0.499 at 67% -
still `CALM`, just under** - and +0.537 at 75%, the first `GREED`. Three bars
in four going one way for sixty bars is not a market. So the threshold is not
unreachable in principle, it is unreachable in practice, and a later reader who
finds `mood()` always `CALM` finds a test that already knew.

## 6. Direction conditioned on volatility, which was the open question

`direction-is-closed-not-just-null` is a result about direction as a
**standalone** gate - the detector finds a planted drift at z +2.90 and the real
thing earns 2% of a spread - and it is not a result about direction inside a
volatility state. This desk's volatility-space results do pay
(`the-clock-and-the-loop-compose` reads +1567 together against +848 and +518
apart), and the framing's claim is precisely a conditional one: not "JPY crosses
fall" but "JPY crosses fall **fast when fear is rising**". So the conditioning
was measured rather than assumed closed.

Swings at `reach` 3 (859, 838 and 857 of them), split at the top and bottom
tercile of each reading at the swing's **start** bar. `down_share` is the share
of swings that went down; `speed` is the up-against-down log gap within that
cell.

| instrument | conditioned on | low tercile | high tercile |
|---|---|---|---|
| audjpy | `volatile_off` | down 0.542, speed -0.079 | down 0.465, speed -0.117 |
| audjpy | `directional_off` | **down 0.622**, speed -0.098 | **down 0.357**, speed -0.094 |
| audusd | `volatile_off` | down 0.504, speed -0.082 | down 0.484, speed -0.064 |
| audusd | `directional_off` | **down 0.586**, speed -0.050 | **down 0.401**, speed -0.166 |
| **eurgbp** | `volatile_off` | down 0.489, speed -0.063 | down 0.514, speed +0.087 |
| **eurgbp** | `directional_off` | **down 0.468**, speed -0.064 | **down 0.507**, speed +0.153 |

**The volatility half carries no direction, even conditioned.** The down-share
moves from 0.542 to 0.465 on audjpy and 0.504 to 0.484 on audusd across the
whole range of the volatility reading - nothing, on 278-286 swings a cell.

**The direction half appears to carry a lot, and it is circular.** Down-share
0.622 against 0.357 on audjpy and 0.586 against 0.401 on audusd looks like a
strong conditional direction signal. **The placebo says it is not.** EURGBP's
legs - `eurusd` and `gbpusd` - are the two deliberately **excluded** from the
basket index, so for EURGBP the index is not a trailing reading of its own
direction. Its down-share conditioning on `directional_off` is **0.468 against
0.507**: flat. For audjpy and audusd, whose legs *are* in the index, it is
0.62 against 0.36.

So the mechanism is the index reading the instrument's own recent direction
back to itself, which a swing's direction is then determined by: a swing that
goes up starts at a pivot low, and at a pivot low a trailing direction reading
is already negative. That is the definitional trap
`let-the-shuffled-twin-name-the-mechanical-observables` describes - "overshoot
at an extreme is definitional" - and here the control that caught it was the
one placebo whose legs are outside the index. Carrying it was the only reason
this is a diagnosis and not a finding.

### The interaction, and the placebo that refuses it

Direction terciles **within** each volatility tercile, `reach` 3, n 93-96 a cell:

| cell | audjpy speed | audusd speed | **eurgbp speed** |
|---|---|---|---|
| low vol, low dir | -0.151 | -0.019 | **-0.154** |
| low vol, high dir | -0.058 | -0.109 | **+0.194** |
| high vol, low dir | -0.095 | -0.026 | **-0.270** |
| high vol, high dir | -0.006 | -0.064 | **+0.245** |

**The largest readings in the table are the placebo's.** EURGBP spans +0.245 to
-0.270 where audjpy spans -0.006 to -0.151 and audusd -0.019 to -0.109, and
the cross and the leg order their four cells **oppositely** to each other -
audjpy's strongest cell is low-vol/low-dir and audusd's is low-vol/high-dir. At
n 95 a cell this is sampling noise, and `the-placebo-arm-selects-the-null` is
explicit: reject any null whose placebo finds structure. This one finds more
than the instruments the claim is about.

**Verdict on the conditioning: measured, and null.** It is not refuted in the
way a standalone direction gate is - the test here is a 4-cell split at n 95,
not a fitted gate - but the conditioning this study could run reads nothing,
the one apparent signal is circular, and the placebo is noisier than the
signal. The trade arm's own version of the same question (the `both` gate in
section 5) reads -0.0010R on 65 trades with a +-0.31R interval. **The honest
statement is that the interaction remains open and this sample cannot close
it**, with the bound from section 5's power sweep: a conditional drift above a
tenth of a stop over 20 bars would have been seen.

## Costs, and what this store cannot supply

**Everything above is gross.** Of the fourteen series here only `eurusd`,
`gbpusd` and `gold` have enough recorded quotes for a median spread;
`audusd`, `nzdusd`, `usdcad`, `usdchf` and `usdjpy` have two or fewer, so
`node/corpus.py` skips them rather than guess.

A synthetic cross is worse than unpriced. **A cross's spread is not the product
of its legs' spreads - it is wider**, because a dealer quoting AUDJPY carries
both legs' risk plus their correlation, and there is **no recorded AUDJPY,
NZDJPY or CADJPY quote anywhere in this store** to measure it against. No cost
is charged and none is invented, which is the one rule [CLAUDE.md](../../CLAUDE.md)'s
"The data ceiling" is absolute about: a result priced off a guessed spread is
the one result that looks like a measurement and is not.

For scale only, and explicitly not applied: audjpy's 1d unit is about 44 bp of
close-to-close move, so a 3-4 bp round trip would be roughly 0.1R at the
1.0-unit stop - the same size as the entire effect being looked for. **A costed
read needs one thing: recorded quotes for the cross from the venue that would
trade it.**

## What was not done, and why

* **No 15m rule at all was run**, on any section. The harness takes
  `--intervals 1d,15m` and the 15m window is 4,760 bars common to all eight
  feeds, about 50 days. For the **level** study that is not worth running: the
  books publish a few hundred levels over 19 years at 1d, so at 50 days the
  crash class would hold single digits. For the asymmetry and the trade it is
  worth running and is a **different rule**, never pooled with 1d.
* **The level and trade panels were not run** - two of eight legs and three of
  fourteen series, real arm only. See "What has actually been run" above. The
  surrogate arms and the duty-cycle twin are in the harness and are the first
  thing to read when the panel lands, because section 5's verdict currently
  leans on one placebo instead of on three null arms.
* **No `reach`, `keep` or shield-band sweep on the books.** With the crash
  class at 2-6 levels on two of the four books, a parameter sweep buys cells
  rather than evidence.
* **Section 4 has no power statement, and the arm built for it does not
  work.** `plant_label_hold` was run and rejected - see "Power for this
  section" in section 4. The plant changes the path, so the recomputed shape
  labels no longer mark the bars the reflection was placed at, and the act of
  planting destroys the association being planted.
* **`indicators.Candles` was available and is not used.** Its question is
  level-relative - `confirms(level, want_up)` asks whether the auction reached
  a price, was rejected and closed away from it - and the labels here are about
  the bar that **formed** the level, not about a bar arriving at one. The
  rejection-shape-at-a-level question is `research/docs/level-bounce.md`'s, and
  running it here would have measured that study again under a different name.
  `levels.chains` (the displacement leg) and `trend.ratio` (Kaufman's
  efficiency) are the primitives the three shapes actually need, and
  `smc-primitives-overlap-and-are-closed` is the reason to use the fewest that
  answer the question rather than all of them.
* **No cost, anywhere.** See above.
* **No synthetic-generator placebo.** `carry-an-independent-placebo-pair` asks
  for two Deriv volatility indices in every relationship harness and there are
  none in this store at 1d - the synthetics present are 15m-only or absent.
  `eurgbp` is the placebo instead: real FX, same synthesis arithmetic, neither
  leg a haven nor high-yield. It is a weaker control than a known generator and
  is the best this store supports.
* **The JPY crosses are not three independent cells.** `audjpy`, `nzdjpy` and
  `cadjpy` all share the `usdjpy` leg, so the three strong asymmetry readings
  are substantially one leg's property seen three times. `usdjpy` alone reads
  -0.119 (z -1.55), and `audusd` alone reads -0.297 (z -4.91), so the carry leg
  is carrying more of it than the haven leg. Counted as one cell for
  Benjamini-Hochberg would be the stricter choice and was not made; the cells
  are reported individually and the dependence is stated here.
* **No intrabar reconstruction of a cross's true range.** It is possible from
  the 1h and 15m legs over their shorter windows and would turn the 1.7x bound
  inflation from an inference into a direct measurement. It would not change
  any result here, because every cross-based reading in this document already
  avoids the range.

## The code

| file | what it is |
|---|---|
| `research/ideas/fear_greed.py` | the store, the venue rule, the cross synthesis, the null arms, the basket index, the shape labels |
| `research/ideas/fear_greed_control.py` | the triangle screen with its misalignment arm, the 2008 control, the planted crash |
| `research/ideas/fear_greed_asym.py` | the swing decomposition, the three log gaps, the eras, the conditioning |
| `research/ideas/fear_greed_levels.py` | the four books replayed causally, the formation labels, the hold outcomes, the AUCs |
| `research/ideas/fear_greed_trade.py` | the race on closes, the causal gate, the day-block CI, the duty-cycle twin |
| `research/ideas/fear_greed_power.py` | every planted effect and its strength sweep |
| `research/ideas/fear_greed_run.py` | the single entry point |
| `research/ideas/fear_greed_report.py` | the tables above |
| `till_infinity/indicators/sentiment.py` | `FearGreed`, with the halves exposed |
| `tests/test_sentiment.py` | 27 cases from 25 functions - the 20 already committed with `sentiment.py` (one parametrised three ways, so 22 cases) plus **5 added** for the facts this study rests on |

### How to run it

```sh
uv run python -m research.ideas.fear_greed_run --out <dir> --jobs 16
uv run python -m research.ideas.fear_greed_report <dir>
```

`--jobs` defaults to **1** and is the only thing to raise; nothing else needs
changing. Measured per job on an 8-core shared box, at 1d:

| section | jobs | measured | at `--draws` 4 |
|---|---|---|---|
| asymmetry | 14 | 1,012 rows in **609 s at `--jobs 3`** | as measured |
| levels | 8 | **406 s** for one leg at `--draws` 1 | about **1,300 s** a leg |
| trade | 14 | **31 s** for one series at `--draws` 1 | about 120 s a series |
| power | 4 | **140 s** for one feed at `--draws` 1 | about 500 s a feed |

So roughly **17,000 core-seconds**, which is about **3 hours single-process**.
At `--jobs 16` the wall clock is set by the longest single job - a `levels` leg
at about 22 minutes - so **25 to 35 minutes**, and raising `--jobs` past 16
buys nothing because there are only 8 `levels` jobs. The level books dominate:
on 4,980 daily bars `Levels` takes 5-50 s, `Pips` 12-51 s, `BjorgumLevels`
0.5-11 s and `Pivots` 0.1-6 s, and the study replays them over 8 legs x 23
arm-draws.

`--intervals 1d,15m` adds the 15m rule as a separate rule - do not pool it.
`--sections` runs a subset in the pre-registered order; `--draws` sets the
surrogate draws per arm (4 in everything reported here).

### Three properties of the indicator a careless fixture gets wrong

Found while writing the added tests, and recorded because each one produces a
*plausible* number rather than an error. The committed fixtures already avoid
all three; a new one will not unless its author knows.

1. **`_skew` returns 0.0 when either side of the window is empty.** A monotone
   fixture therefore leaves the volatility half unreadable and every assertion
   about it passes for the wrong reason. It also makes a 100%-up series read
   **+0.574** where a 90%-up series reads **+0.621** - the reading goes *down*
   as the trend gets cleaner, because `skew` drops out.
2. **A constant *relative* wick on a falling price gives a range that
   shrinks**, so a "crash" built that way read `expansion` at **+0.70** - the
   greed side - while every direction component read fear correctly. A fear
   fixture has to widen the range in absolute terms, in the last fifth of the
   window, which is the slice `_expansion` averages.
3. **`position` reads 1.0 on an alternating series**, because it is scale-free
   within the window and the close sits at the window's extreme. A "flat"
   fixture that ends on one tick of an alternation reads **+0.30** overall, not
   0.

And one property worth knowing at a call site: **`conviction`'s sign is the
trailing window's net move**, so on a market that went nowhere it reads
whichever phase the window ends in - about -0.5 on a closed oscillation. A
caller reading `conviction` on a range is reading a phase, and
`test_convictions_sign_is_the_windows_net_move_not_the_recent_direction` pins
it.

### A mistake in the making of this study

**`tests/test_sentiment.py` was overwritten and restored.** 20 test functions
had already been committed alongside `sentiment.py`; this study's
tests were written without reading that file first and replaced it wholesale.
The file was recovered from git, every one restored verbatim, and the 5 genuinely
new tests appended - so the diff is now additive, with nothing removed. The
recovered tests are the better half of the file: they carry the look-ahead
check, the deque-bound check and the identity check that the replacement did
not have.

Nothing measured in this document depended on the lost file, because the
harness drives `update_raw` directly. The cost was a full 18-minute suite run
against the wrong version of it.
