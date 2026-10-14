# Every published pivot formula is one object: a weighted centre plus a multiple of the prior range

Asked on 2026-10-14: *checkout the formulas for calculating supports and
resistance levels online as well as pivots too, so we can review them and see
how we can create statespace versions of them.*

`structures/drawing/pivots.py` publishes **Classic** pivots only, on daily and
weekly sessions. Woodie, Camarilla, DeMark and Fibonacci are absent. The
formulas are below as the sources give them, with the disagreements marked,
followed by the thing worth noticing about all of them.

## The formulas, as published

Prior session's high `H`, low `L`, close `C`, open `O`; `Range = H - L`.

| family | centre | levels |
| --- | --- | --- |
| **Classic** (in production) | `(H+L+C)/3` | `R1 = 2PP-L`, `R2 = PP+Range`, `R3 = H+2(PP-L)`; S mirrored |
| **Woodie** | `(H+L+2C)/4` | `R1 = 2PP-L`, `R2 = PP+Range`; S mirrored |
| **Fibonacci** | `(H+L+C)/3` | `PP ± 0.382·Range`, `± 0.618·Range`, `± 1.000·Range` |
| **Camarilla** | `C` | `C ± Range·1.1/12`, `·1.1/6`, `·1.1/4`, `·1.1/2` |
| **DeMark** | `X/4` | `R1 = X/2 - L`, `S1 = X/2 - H` |

DeMark's `X` is the only asymmetric one: `X = H + 2L + C` when `C < O`,
`2H + L + C` when `C > O`, and `H + L + 2C` when they are equal. The branch is
the point - it leans the level toward the side the session closed away from.

Camarilla's `1.1/n` notation causes trouble and is widely misread. It resolves
to multipliers of **0.0917, 0.1833, 0.2750 and 0.5500**.

**Where the sources disagree, and it matters:**

- **Woodie's input.** Most sources give `(H+L+2C)/4`; others give
  `(H+L+2·today's open)/4`. These are different objects - the second needs the
  session to have opened, so it is not knowable in advance, which breaks the
  one property `pivots.py` values pivots for.
- **Camarilla's fifth rung.** `H5 = H/L` in one source, `(H/L)·C` in another.
  The first is dimensionally wrong - a ratio is not a price.
- **DeMark.** One guide gives `(H+L+2C)/4`, which is Woodie's formula, not
  DeMark's. Treat it as unreliable.

## What they all are

Written out, every family is the same expression:

    level = w·[H, L, C, O] ± k·(H - L)

a weighted centre plus a multiple of the prior range. The families differ only
in `w` and `k`:

| | centre weights | spread multipliers |
| --- | --- | --- |
| Classic | `(1,1,1,0)/3` | `k` implied by `2PP-L`, then `1.0`, then `~2` |
| Woodie | `(1,1,2,0)/4` | `1.0` |
| Fibonacci | `(1,1,1,0)/3` | `0.382, 0.618, 1.000` |
| Camarilla | `(0,0,1,0)` | `0.0917, 0.1833, 0.2750, 0.5500` |
| DeMark | branch on `C` vs `O` | `0.5` on the branched sum |

That is **a point estimate of value plus a scaled uncertainty band**, which is
what `facade.Desk.read()` already publishes. So there is no new formula to
write - the families are special cases of something statespace emits natively,
with two parts worth separating.

## The spread they chose is the one this desk just measured as better

Every family uses `H - L` for its spread. That is the **Parkinson** estimator,
and `candle-screen.md` measured the range-based family against close-to-close
on the question of what volatility does next: AUC **0.6484** within strata of
current volatility on twenty FX feeds at 100% sign agreement, and **0.6671** on
equities with **371 of 392** instruments agreeing - rising as the window
shortens, which is the regime a filter's `Q(dt)` update lives in.

Statespace currently drives `Q` from close-to-close returns. The pivot
families have used the better proxy since the 1930s floor. That is one point
to them and a concrete change here, already written up in #226.

## The multipliers are the part to replace

`0.382`, `0.618`, `0.55`, `1.1/12` are constants standing in for quantiles of a
predictive distribution. They cannot adapt to an instrument, a session, or a
volatility regime, and nothing in their provenance is a measurement.

A state space has the distribution. `no-gaussian-band-is-calibrated` says
nothing beats the walk on CRPS, so its quantiles are the best-calibrated band
available here - which makes the statespace version of this whole family:

    centre  = the filtered state, as `Readout.mean`
    level_q = centre ± quantile(q) of the predictive distribution

with `q` chosen to match what each published multiplier was reaching for -
0.382 of a range is roughly a 30th-to-70th percentile band, 1.1/2 is roughly
the 90th. The result is calibrated by construction, adapts per instrument, and
unlike a constant it can be **wrong in a measurable way**.

## The test, which decides whether any of it earns its place

The question is not whether a statespace pivot is prettier. It is whether a
calibrated quantile beats a hand-chosen constant at the only thing a level has
to do. The harness exists:

1. **Nominate** both - the published families and the quantile versions - as
   prices, from the same prior session.
2. **Race each against a distance-matched placebo** through the identical
   detector, which is what `level_signatures.py` does, with anchors spaced a
   full horizon apart so no two decisions share a bar of outcome.
3. **Gate on `Range_Break_100/200`**, whose generator has a boundary by
   construction. A nomination that cannot find the boundary of a process built
   to have one does not get read on FX.
4. **Report the trap and backcheck rates per nomination**, which
   `outcome-prediction.md` found are the two outcomes that are predictable at
   all - `strength` and `experience` for a break, `confluence_n` for a
   backcheck at 0.6140.

The expected answer is that none of them beats a placebo, because seventeen
level constructions already have not and neither did topological prominence.
**Pivots are the interesting exception to try anyway**, for the reason
`pivots.py` already states in its docstring: their power is partly
self-fulfilling. Enough people watch `R1` that it does not need the formula to
mean anything - and that is a hypothesis about **which** nominations are
watched, not about which arithmetic is right, so Classic and Camarilla being
popular is the prediction, not Fibonacci being principled.

## Measured: no family beats a matched placebo

Every variant above, including the disputed ones, nominated from the prior
session and raced over the next - one decision a session, so no two share a bar
- against a placebo at the same distance from the session open:

| family | touched | hold rate | placebo | diff |
| --- | ---: | ---: | ---: | ---: |
| camarilla | 104,897 | 0.5109 | 0.5108 | +0.0001 |
| demark | 33,819 | 0.5123 | 0.5119 | +0.0004 |
| woodie_close | 39,428 | 0.5079 | 0.5070 | +0.0009 |
| classic | 41,187 | 0.5070 | 0.5082 | -0.0012 |
| woodie_open | 39,479 | 0.5073 | 0.5081 | -0.0008 |
| fibonacci | 58,066 | 0.5073 | 0.5096 | -0.0023 |
| demark_mistranscribed | 32,941 | 0.5092 | 0.5118 | -0.0026 |
| camarilla_h5_scaled | 6,355 | 0.5057 | 0.5158 | -0.0100 |

Nothing clears its placebo by more than a tenth of a percentage point, in
either direction. The self-fulfilling argument - that `R1` works because people
watch it - predicts Classic and Camarilla outperforming, and they do not.

`camarilla_h5_ratio` is **absent from the table**, which is the result for it:
`H5 = H/L` is about 1.0013 on EURUSD while price is near 1.09, so it is never
reached. A dimensionally wrong level shows up as never touched.

**And the control did not work as built.** `demark_mistranscribed` is Woodie's
formula and should have scored identically to `woodie_close`. It did not -
0.5092 against 0.5079 - because the first nominates three levels and the second
five, so the aggregates cover different level sets. The shared levels agree; the
check has to be per-level-name to mean anything. Worth fixing before the next
run leans on it.

## Wyckoff and Elliott, as the one falsifiable piece each

Neither is arithmetic on a session, so neither reviews the way pivots do. Both
are models, and each maps onto a module that already exists.

**Wyckoff is a hidden Markov model.** Four phases with transitions, observed
through price and volume jointly, which is `hmm.py` and `switching.py`. Its
mechanic - effort against result - is a two-channel observation model, and the
activity clock here already absorbs 76% of the Q clock into volume time.

Tested as a conditional: at the end of a zigzag leg, does effort-to-result
predict whether the next leg is **bigger**? AUC **0.5693** on twelve traded
feeds at 100% sign agreement - and **0.5791 on the same bars block-shuffled**,
also at 100%. Unanimity in both arms is the tell. The cause is in the
construction: `effort` divides volume by distance travelled, so a small leg
inflates effort **and** makes "next leg bigger" more likely. Leg-size mean
reversion, built in.

**Elliott is a constrained changepoint segmentation**, which is
`changepoint.py` with rules attached. Its real problem is identifiability - the
rule set can label almost any path - so "does the count work" has no answer.
One component is falsifiable without any counter: **the Fibonacci ratios
between consecutive legs**.

68,796 legs across twelve feeds, three zigzag thresholds, density within 5% of
each named ratio against the same bars shuffled:

| ratio | real | shuffled | lift | feeds agreeing |
| ---: | ---: | ---: | ---: | --- |
| 0.382 | 0.0245 | 0.0242 | +0.0003 | 58% |
| 0.618 | 0.0391 | 0.0372 | +0.0019 | 75% |
| 1.000 | 0.0489 | 0.0479 | +0.0010 | 67% |
| 1.618 | 0.0388 | 0.0377 | +0.0010 | 67% |
| 2.618 | 0.0252 | 0.0264 | -0.0012 | 17% |

No clustering. A 5% window around 0.618 covers about 6% of the plausible ratio
range and catches 3.9% of ratios, which is roughly uniform. The largest lift
anywhere is at ratio **1.000** (+0.0045 at the widest threshold), and that is a
property of the detector: a fixed-threshold zigzag bounds leg size from below,
so equal legs are over-represented by construction.

The zigzag itself is worth a note. Its first version initialised direction to
zero, which left both tracking branches live, set the running extreme to the
current price on every bar, and made the turn condition unreachable - zero legs
from forty thousand bars at every threshold. A silent zero is the good kind of
failure.

## Benner, and why it is not testable here

Samuel Benner's 1875 chart is a **fixed-period calendar cycle** - 7, 9 and 11
years - with no data input at all. In these terms it is the degenerate case of
`spectrum.py`: a periodogram with the period pinned instead of estimated.

The longest history in the cache is daily EURUSD and USDJPY, **1971 to 2026**.
Fifty-five years is about **six repetitions** of a nine-year cycle, so a "was
this a turning year" test has roughly six events, and a spectral estimate at
that frequency carries a standard error about equal to its own value. To reject
at the five percent level on six events the cycle would have to be very nearly
deterministic.

So the honest answer is that this desk cannot test Benner **as a frequency**,
and the number that says so is six.

### But the logic is derivable, and then it is testable

That framing was too narrow. Benner's structure is not a sinusoid - it is a
**repeating sequence of intervals**:

    pig iron lows  : 11, 9, 7, 11, 9, 7, ...   (summing to 27)
    pig iron peaks : 8, 9, 10, 8, 9, 10, ...   (summing to 27)
    corn peaks     : 5, 6, 5, 6, ...           (summing to 11)

a deterministic renewal process whose inter-arrival times cycle through a fixed
list. The general object containing it is already in this package's vocabulary.
A standard hidden Markov model has **geometric** dwell times - memoryless, a
constant hazard of leaving a state - while Benner's durations are **patterned**,
the extreme opposite. The model spanning both is a hidden **semi**-Markov model
with an explicit duration distribution per state, and Benner is the degenerate
case where that distribution is a point mass cycling 11, 9, 7.

A nine-year cycle needs decades. **Duration dependence needs transitions**, and
intraday data has tens of thousands. Regimes defined crudely on purpose -
20-bar volatility against its own 500-bar median, because the claim is about
durations rather than about a clever state definition:

| arm | runs | mean | CV | h(1) | h(2) | h(3) | h(5) | h(8) | h(13) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| traded, real | 25,918 | 18.3 | **1.332** | 0.144 | 0.100 | 0.087 | 0.063 | 0.038 | 0.032 |
| traded, shuffled | 21,474 | 22.0 | 1.225 | 0.132 | 0.093 | 0.076 | 0.055 | 0.033 | 0.027 |
| control, real | 5,051 | 15.6 | 1.102 | 0.137 | 0.102 | 0.086 | 0.071 | 0.044 | 0.037 |
| generated, real | 8,155 | 12.2 | 1.253 | 0.209 | 0.151 | 0.117 | 0.087 | 0.061 | 0.041 |
| generated, shuffled | 8,256 | 12.1 | 1.254 | 0.215 | 0.147 | 0.116 | 0.087 | 0.065 | 0.037 |

**Dwell times are not memoryless.** The hazard falls more than fourfold from
h(1) to h(13), so duration dependence is real and the geometric assumption in a
plain HMM is wrong here.

**The direction is the opposite of Benner's.** Patterned durations need a CV
well below one and a hazard that **peaks** at the patterned interval. Measured:
CV **1.332** and a monotonically **falling** hazard - the longer a regime has
lasted the less likely it is to end. That is persistence and long memory, not
periodicity. A cycle needs a hump; this is a decay.

**And most of it is mechanical.** The shuffled arm reproduces the falling
hazard, and on the generated feeds real and shuffled agree to three decimals -
1.253 against 1.254 - which is the negative control working exactly: no regime
structure, so destroying the ordering changes nothing. The part that needs the
real ordering is the traded gap, CV 1.332 against 1.225, consistent across all
eight hazard steps but small.

So the usable form of Benner is: **give `switching.py` an explicit duration
distribution instead of geometric dwell times, and fit it decreasing.** His
insight - that durations carry information - survives. His periodicity does not,
and the sign is measured.

## The ideas behind the cycle theories, taken the way Benner was

Benner's surface claim - a nine-year period - was untestable on six
repetitions. Its **idea** - that durations carry information - was testable on
25,918 transitions. The rest of the list, treated the same way:

| framework | the mechanism | general form | where it is tested |
| --- | --- | --- | --- |
| Benner | durations carry information | duration distribution | `dwell.py` |
| Kitchin, Juglar | lagged negative feedback | damped oscillator | `mechanisms.py`, arm one |
| Kondratiev, 17.6y | rare structural shifts | over-dispersed dwell | `dwell.py`, the CV |
| Gann | price and time commensurable | scaling exponent | `mechanisms.py`, arm two |
| BTC halving | scheduled known shock | exogenous `Q` input | `statespace-seasonal.md`, +197 nats |
| M2 liquidity | slow exogenous state | `inputs.py` channel | data absent |

Three of those need no new data at all, and one of them already passed.

### Kitchin and Juglar are one mechanism, and it is absent

Forty months and seven-to-eleven years are the same thing at different lags: a
stock adjusted with a delay overshoots and the overshoot corrects. That
mechanism is **scale-free**, which is what makes it testable where the period is
not - delayed negative feedback produces **negative autocorrelation at a
characteristic lag**, and pure persistence produces none at any lag.

| series | arm | 2 | 8 | 32 | 64 | 128 | 512 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| returns | real | -0.001 | 0.003 | -0.002 | 0.004 | -0.005 | 0.002 |
| returns | shuffled | -0.001 | 0.001 | 0.001 | 0.000 | -0.002 | 0.000 |
| log volatility | real | **0.947** | 0.784 | 0.470 | 0.413 | 0.376 | 0.287 |
| log volatility | shuffled | 0.942 | 0.732 | 0.194 | 0.010 | 0.002 | 0.002 |

Returns carry nothing at any of nine lags from 2 to 512, and the shuffled arm
matches them. **There is no lag at which price reliably reverses.**

What is there is **long memory in volatility** - never negative, decaying
slowly, and real: 0.413 against a shuffled 0.010 at lag 64. That is the same
conclusion the dwell-time hazard reached from an independent direction.
Persistence, not periodicity.

### Gann's premise rests on one number, and it is 0.56

Squaring price against time presumes a stable exchange rate between them, a
move of one unit per bar being a meaningful constant. That requires

    |price move| ~ horizon ** H     with H near 1

and **diffusion gives H = 0.5**, at which the ratio of move to time decays as
`1 / sqrt(horizon)` so no fixed angle holds at two horizons at once.

Measured: **H = 0.5577**, standard deviation 0.0119 across twelve feeds, with
the **block-shuffled arm at 0.5788** - so even the small excess over a half is
not market structure. At 0.5577 an angle calibrated over ten bars is wrong by a
factor of about 2.7 over a hundred.

The density tests agree and are worth reading carefully, because two of them
produce unanimous-looking lifts that are artefacts:

| arm | reading |
| --- | --- |
| angles, slope ratios | lifts -0.0006 to +0.0024, 33% to 75% of feeds. Null. |
| squaring, raw slope | `0.25` and `0.33` lift **+0.0135** and **+0.0140** at **100% of 12** - and `1.0`, `2.0`, `3.0`, `4.0` are **negative at 0%** |
| time counts | `30` lifts +0.0085 at 92%, `45` at +0.0048, and `60`, `90`, `180`, `360` are null or negative |

The squaring row is the Hurst result restated: slope is `move / N`, which at
H = 0.56 goes as `N ** -0.44`, so longer legs have smaller slopes and the
typical slope sits well below one. Real legs are longer than shuffled ones -
shuffling destroys the trends that extend a leg - so real carries more mass at a
quarter and a third. **Diffusive scaling, and it points away from the 1x1
rather than toward it.**

The time-count row fails on harmonics. A genuine thirty-bar count has to appear
at sixty and ninety; these are null or negative there. What the lift measures is
the leg-duration distribution differing between real and shuffled bars.

### The halving idea already works here, as a variance

A scheduled, publicly known supply shock is an exogenous input on a known
future date. That is exactly what the session clock is, and it is the one item
on this list that **measured positive**: a time-of-day profile on innovation
size worth **+197 nats** at the median, FX and metals moving three to four
times as far per hour at 14:00-15:00 UTC as at 03:00, nothing on markets with a
known generator and no session, and **-443 with the clock deliberately
misaligned**.

So the generalised halving mechanism - scheduled events move variance - is
confirmed on this desk's own data. What fails is reading it directionally.

### And the CV discriminates between the two families

`dwell.py` measured a coefficient of variation of **1.332**, which is **above**
one: durations are over-dispersed, a mixture of short regimes and rare long
ones. Fixed-interval recurrence needs a CV well **below** one. So the same
measurement that refutes Benner, Kitchin and Juglar is **consistent** with
Kondratiev's and the 17.6-year model's structural-shift form - occasional very
long regimes.

### And the period itself, which a CV does not give

A coefficient of variation says "over-dispersed" and puts no number on the
regime. Fitting four duration families by maximum likelihood does, and the
answer **changing with the frame** is the whole result:

| frame | best fit | period | Weibull shape |
| --- | --- | --- | ---: |
| 15m | Weibull | 19.7 bars = **296 min**, 4.9 h | 0.840 |
| 1h | lognormal | 8.5 bars = **508 min**, 8.5 h | 0.827 |
| 4h | **Pareto, alpha 0.485** | **none - infinite mean** | 0.782 |
| 1d | **Pareto, alpha 0.501** | **none - infinite mean** | 0.686 |

A characteristic regime length does exist intraday, around **five to eight and
a half hours** - but it is not one number. 296 minutes at 15m against 508 at 1h
means it drifts with the measuring frame, which is partial self-similarity
rather than a clean period.

**At four hours and above it is gone.** Pareto wins, and an alpha below one has
an **infinite mean** - there is no characteristic length to quote in any unit,
which is a definite answer rather than an absence of one. The discriminator is
the 4h shuffled arm: real fits Pareto while shuffled fits a lognormal at 9.4
bars, so the scale-freeness **needs the real ordering** and is not something the
estimator invented.

The Weibull shape falls monotonically as the frame lengthens - 0.840, 0.827,
0.782, 0.686 - the hazard decaying ever more steeply, converging on scale-free.
On that trend there is no reason for a period to reappear at decadal scale,
which is as close as this data comes to addressing Kondratiev and should be read
as an extrapolation rather than a test of his claim.

One reporting defect was fixed on the way and is worth naming: Pareto's
parameter is a **tail exponent**, not a duration, and the first version printed
it through the same bars-to-minutes conversion as the others - "scale 0.5 bars
= 721 min". A number with no meaning, in the column that mattered most.

### Every one of those three claims fails its own stress test

The three readings above were each put against their own specific flaw, and
none survived intact.

**The drift is the detector, and no windowing is neutral.** "Partial
self-similarity" assumed the detector measured the same object at every frame.
It does not - a 20-bar volatility window is five hours at 15m and twenty at 1h
- so the window was held constant in **real time** instead, at 1200 minutes
against a 30,000-minute median:

| frame | window | best fit | period |
| --- | ---: | --- | --- |
| 15m | 80 bars | lognormal | 17.7 bars = **266 min** |
| 1h | 20 bars | lognormal | 8.5 bars = **508 min** |
| 4h | 5 bars | **geometric** | 6.2 bars = **1483 min** |

It drifts **further**, not less. And at 4h a real-time window of 1200 minutes is
only five bars, which turns the detector into a noise-flipper: 72,512 runs
against 24,387, a geometric best fit, and a Weibull shape of **1.193** - a
hazard that *rises*. There is no windowing that measures one object across
frames, so **the period is not identifiable independently of the detector**, and
the self-similarity reading was a reading of the parameter.

**The Pareto win at 4h was the mass at one and two bars.** A continuous Pareto
MLE on discrete run lengths floored at one bar is driven by exactly that mass,
so the floor was swept:

| floor | 4h | 1d |
| --- | --- | --- |
| >= 1 | pareto, alpha 0.485 | pareto, alpha 0.501 |
| >= 3 | **lognormal, 14.3 bars** | pareto, alpha 0.620 |
| >= 5 | **lognormal, 19.0 bars** | pareto, alpha 0.685 |
| >= 10 | pareto, alpha 1.004 | pareto, alpha 0.871 |

At 4h the scale reappears as soon as the shortest runs leave. At 1d Pareto
survives every cut but its alpha climbs monotonically with the floor, 0.501 to
0.871, which is what a mis-specified tail does rather than what a real exponent
does - so **"infinite mean" is not established**.

**And the discriminator was sample composition.** The arms had 24,387 and
19,985 runs and different mean lengths, so each was subsampled to the smaller
count before refitting:

| frame | real | shuffled |
| --- | --- | --- |
| 4h, 20,111 each | **lognormal**, 7.9 bars | **lognormal**, 9.3 bars |
| 1d, 5,346 each | **pareto**, 0.500 | **pareto**, 0.467 |

The same family on both arms at both frames. The scale-freeness does **not**
need the real ordering, and the one line that made it look like a finding was
the run counts differing.

**What survives.** Over-dispersion at a CV of 1.332 and a hazard falling more
than fourfold from h(1) to h(13). Those hold at every frame, every floor and
both arms, and they are the part `switching.py` can use: durations are not
memoryless and the hazard decreases. The **period** does not survive, in any
unit, and neither does the scale-free reading.

## Sources

- [Pivot points, CrossTrade](https://crosstrade.io/learn/technical-indicators/pivot-points) - Classic and Woodie
- [The Camarilla Equation Explained, PivotBoss](https://pivotboss.com/2010/05/31/the-camarilla-equation-explained/) - the `1.1/n` rungs
- [Camarilla, LuxAlgo](https://www.luxalgo.com/library/concept/camarilla/)
- [DeMark Pivots, LuxAlgo](https://www.luxalgo.com/library/concept/demark-pivots/) - the `C` against `O` branch
- [Standard Pivot Point formulas, ActionForex](https://www.actionforex.com/?p=629083)
- [Pivot Points: Definition, Formula & Calculation, Strike](https://www.strike.money/technical-analysis/pivot-points) - Fibonacci ratios
