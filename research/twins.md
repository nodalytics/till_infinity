# The twins are two draws from one law, not one path seen twice - and the law is exactly what it says on the tin

Deriv publishes `volatility_75_index` and `volatility_75_1s_index`. Same
headline parameter, different tick rate: the standard series prints every two
seconds, the `1s` series every second. If those were one path sampled at two
rates, the fast quote would be a higher-resolution view of the slow one and you
could see where the slow one is going before it prints. That is not an edge, it
is a free lunch, and the prior against it is enormous - which is exactly why it
was worth six seconds of a 64-core machine to kill.

It is dead. **916,248 comparisons** across tick and bar data. Two twin cells out
of everything measured clear the control built from mismatched pairs of the same
instruments, and neither survives a split by time - one reverses sign, the other
is contradicted by the rank statistic on its own sample.

What came back instead is better than a null. These are the cleanest geometric
Brownian motions this desk has measured: the stated annualised volatility is
true to within two standard errors on all twelve series, one-minute log returns
are indistinguishable from iid normal on every test applied, and the two members
of a twin pair carry **identical volatility per second** with per-tick variance
differing by exactly the tick-rate ratio. They are the same law, drawn
independently, twice as often.

## What was already known, and what was left open

[generated.md](generated.md) killed the minute-bar version of this in a 325-pair
study: twins at |corr| 0.0085 against strangers reaching 0.0129, seven lags.
A wall-clock-identical path would have shown there as a correlation near one, so
that hypothesis was already gone. Four openings remained, and they are what this
page tests:

* a **lead of seconds**, which a one-minute bar averages into nothing;
* a **tail** relationship - shared jumps without a correlated body;
* a shared **volatility clock** - independent innovations, one variance process;
* a shared **draw stream** consumed at two rates, which lines up in tick
  *index* rather than in wall-clock time.

Plus two questions that are about the generator rather than the pair: whether
the stated law is true, and whether a PRNG period or a reused seed leaves exact
repeats.

## What was run

`research/harness/twinpath.py` on the tick table and
`research/harness/twinclock.py` on the bars, both against `research.db` on the
lab. (`prices.db` there is corrupt and was not touched.)

* **ticks** - 1,123,472 across 16 feeds over one 24-hour window, the whole depth
  the table has.
* **bars** - 84,919 one-minute bars per feed common to all 16, over 59 days.

Sixteen feeds: the five twin pairs, the two orphan `1s` series (150, 250), and
Boom 500, Crash 500, Jump 25, Step as strangers. Every statistic is computed
identically on three kinds of pair:

| kind | pairs | what it is |
| --- | --- | --- |
| **twin** | 5 | `volatility_75_index` / `volatility_75_1s_index` |
| **mismatch** | 61 | `volatility_75_index` / `volatility_100_1s_index` - the like-for-like control: same generator family, same mixture of tick rates, no claimed relationship |
| **stranger** | 54 | a volatility index against Boom, Crash, Jump, Step |

**The bar was set before the numbers were seen**, and it is a line of code in
`report_pairs` rather than a sentence written afterwards: a twin counts only if
its statistic **exceeds every control's**, and does so in **both halves** of a
split sample. Maximising over 1,201 lags is a search over 1,201 chances, so the
controls are maximised over the identical 1,201 lags.

### The estimator had to pass first

Two failures on this project were tables that turned out to be arithmetic
([forecasting.md](forecasting.md)) and one was a statistic sitting on exactly
its null because the column under it was dead ([giveback.md](giveback.md)). So
before any pair was measured the estimator was handed a planted relationship:

    planted lag +37 rho 0.25  ->  recovered lag +37 rho +0.2496 (lag0 -0.0003)
    independent pair over 1201 lags  ->  max |corr| 0.0106   (1/sqrt(n) = 0.0034)

Both halves of that matter. It finds a lead when there is one. And **the search
over lags inflates the apparent correlation threefold** - 0.0106 where the
textbook noise floor is 0.0034 - which is the entire reason nothing below is
read on its own.

## 1. Not the same path, at any lag from -600s to +600s

Log returns on a common 2-second grid, 43,197 steps, every lag from -600s to
+600s:

| kind | pairs | mean \|r\| | max \|r\| | largest |
| --- | --- | --- | --- | --- |
| twin | 5 | 0.0161 | **0.0176** | v75 / v75(1s) = -0.0176 @ -401s |
| mismatch | 61 | 0.0166 | 0.0225 | v100 / v10(1s) = -0.0225 @ -508s |
| stranger | 54 | 0.0182 | **0.0493** | boom_500 / crash_500 = -0.0493 @ -346s |

Twins run from z **-0.78 to +0.05** against the control, and **0 of 5** exceed
the largest control value. Contemporaneous correlation is at most 0.0089 in
absolute value. The largest number in the whole table belongs to two
*unrelated* instruments, which is the same shape [generated.md](generated.md)
found and the reason the control is not optional. It does not reproduce either:
boom/crash is the largest control value in the first twelve hours at -0.0575 and
is displaced in the second, where crash/jump takes the top slot at +0.0944.

Same answer in both halves of the day (twin max 0.0260 and 0.0251, control max
0.0575 and 0.0944), on a 1-second grid, and on 59 days of one-minute bars at
lags -10 to +10 minutes:

| | twin max | mismatch max | stranger max | twin z range |
| --- | --- | --- | --- | --- |
| 1m bars, 59 days | 0.0088 | 0.0114 | 0.0129 | -1.47 to +0.79 |
| 1m bars, first half | 0.0123 | 0.0166 | 0.0167 | -1.54 to +0.64 |
| 1m bars, second half | **0.0167** | 0.0155 | 0.0156 | -0.33 to **+2.94** |

**One cell clears its control**: v75 against v75(1s) at lag -1 minute in the
second half, +0.0167, z +2.94. In the first half the same pair reads +0.0070
at a different lag, z -1.54, and pooled over 59 days it is +0.0074, z -0.05.
That is the split sample doing its job: on 5 twins x 3 samples x 21 lags a
+2.94 is what the largest cell looks like when there is nothing there.

### The shared draw stream, in index space

If the fast series is the slow one's generator run at twice the rate, the two
need not align in wall-clock time at all - but the n-th draw of one would align
with the n-th or the 2n-th of the other. Per-tick returns, z-scored so the
instruments' different scales cannot matter, offsets -60 to +60:

| index map | twin max \|r\| | control mean | control max | twin z range |
| --- | --- | --- | --- | --- |
| 1:1 | 0.0147 | 0.0118 | 0.0174 | -0.13 to +1.28 |
| 1:2 (fast draws paired) | 0.0177 | 0.0147 | 0.0342 | -1.00 to +0.87 |

Nothing.

## 2. The tails are not shared either

A shared generator might show only at the extremes. Two ways of asking, because
the obvious one has no power.

**Co-jumps.** Events above each feed's own 99.5th and 99.9th percentile of
|return|, counted when one lands within 1, 2 or 5 seconds of the other, against
a null built by rotating the second feed's event times around the day 200 times.
At the 99.9th percentile that is 44 events on a slow feed and an expectation of
**0.1 coincidences** - so the zeros the twins return are not evidence of
anything. At 99.5 the expectations run 2 to 11 and the twins z -1.08 to +2.41,
against a control reaching +3.77. **Say plainly what this test is worth:
very little.** It is reported because it was run, not because it decides
anything.

**Conditional exceedance**, which does have power: take each feed's 500 largest
moves of the day and measure how large the other feed is around those moments,
against the same rotation null.

| window | twin z range | control max | mismatch-only max |
| --- | --- | --- | --- |
| +/-2s | -1.42 to +1.88 | +3.21 | +2.43 |
| +/-10s | +0.03 to +0.94 | +4.14 | +2.80 |

Nothing. And the deeper reason there is nothing to find is section 4: these
series have **no tails to share**.

## 3. No shared volatility clock

The weakest shared-driver hypothesis and much the most plausible - one
scheduler, one variance state, two output streams. Realised variance, correlated
in logs, at four resolutions:

| sample | buckets | twin max | mismatch max | stranger max |
| --- | --- | --- | --- | --- |
| per minute, from ticks, 24h | 1,440 | 0.0705 | 0.0948 | 0.0862 |
| 5m, from 1m bars, 59 days | 16,983 | 0.0191 | 0.0278 | 0.0273 |
| 15m, from 1m bars, 59 days | 5,661 | **0.0476** | 0.0423 | 0.0396 |

**The 15m row is the one cell in this study that cleared its control**, so it
gets its own paragraph. It is `volatility_100_index` against
`volatility_100_1s_index`, +0.0476 at lag -1 bucket, z +3.40. Split by time:

    first half   -0.0405 @ +3   z +0.91     (opposite sign, different lag)
    second half  +0.0553 @ -1   z +2.28
    Spearman, full sample  rho +0.0079  z -0.32

The sign reverses across the split, the lag moves, and the rank correlation on
the same data is *below* the control mean. The same pair at 5m reads z +1.38
and at tick resolution z +0.82. Across the clock test there are 5 twins x 2
bucket sizes x 3 samples x 2 statistics = **60 twin cells**, and one of them at
+3.40 is unremarkable. It is a null.

## 4. The stated law is true, to four significant figures

`Volatility 75 Index` is sold as a geometric Brownian motion with 75% annualised
volatility. Measured on 84,918 one-minute returns per feed, annualising at
365 x 24 x 60 minutes because these run continuously. One standard error on the
ratio is 0.0024.

| feed | stated | measured | ratio | (ratio-1)/se |
| --- | --- | --- | --- | --- |
| volatility_10_index | 10% | 10.04% | 1.0038 | +1.56 |
| volatility_25_index | 25% | 25.00% | 0.9999 | -0.05 |
| volatility_50_index | 50% | 49.93% | 0.9986 | -0.60 |
| volatility_75_index | 75% | 75.01% | 1.0001 | +0.05 |
| volatility_100_index | 100% | 100.00% | 1.0000 | -0.01 |
| volatility_10_1s_index | 10% | 9.99% | 0.9988 | -0.50 |
| volatility_25_1s_index | 25% | 25.06% | 1.0023 | +0.96 |
| volatility_50_1s_index | 50% | 50.11% | 1.0023 | +0.93 |
| volatility_75_1s_index | 75% | 75.01% | 1.0002 | +0.07 |
| volatility_100_1s_index | 100% | 100.50% | 1.0050 | **+2.05** |
| volatility_150_1s_index | 150% | 150.68% | 1.0045 | +1.87 |
| volatility_250_1s_index | 250% | 250.71% | 1.0029 | +1.18 |

**Twelve for twelve inside two standard errors.** This also fixes the
annualisation convention as a measured fact rather than an assumption: 24/7,
365 days. It is not a free parameter being fitted - annualising on 252 trading
days of 1,440 minutes instead would put every one of these ratios at 0.831, and
on 252 sessions of 390 minutes at 0.432.

And the rest of the claim - iid normal increments - holds as well:

| feed | LB(30) p | kurtosis | JB p | VR(2) | Hill | RV cv | shuffled | chi2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| volatility_10_index | 0.872 | +0.018 | 0.40 | 1.0042 | 10.5 | 0.636 | 0.638 | 0.632 |
| volatility_25_index | 0.545 | +0.004 | 0.61 | 0.9982 | 10.0 | 0.633 | 0.634 | 0.632 |
| volatility_50_index | **0.045** | +0.004 | 0.56 | 0.9968 | 9.5 | 0.636 | 0.631 | 0.632 |
| volatility_75_index | 0.876 | -0.020 | 0.50 | 1.0001 | 11.1 | 0.630 | 0.626 | 0.632 |
| volatility_100_index | 0.666 | +0.012 | 0.73 | 1.0032 | 10.0 | 0.637 | 0.636 | 0.632 |
| volatility_75_1s_index | 0.166 | -0.011 | 0.80 | 1.0057 | 9.9 | 0.634 | 0.631 | 0.632 |
| *boom_500_index* | 0.078 | **+19.86** | **0** | 0.9998 | 6.1 | **2.093** | 2.086 | 0.632 |
| *crash_500_index* | 0.745 | **+20.83** | **0** | 1.0008 | 5.7 | **2.121** | 2.145 | 0.632 |
| *jump_25_index* | 0.059 | **+9.70** | **0** | 1.0043 | 4.9 | **1.536** | 1.534 | 0.632 |

Autocorrelation of returns sits inside +/-0.0069 - the two-standard-error band
at this sample size - at every one of the seven lags measured from 1 to 60, on
all twelve volatility feeds, and Ljung-Box over the first thirty lags jointly
rejects nowhere (one p-value of sixteen falls below 0.05, at 0.045, which is one
more than none and exactly what sixteen tests produce). Autocorrelation of
|returns| does the same: 35 of the 36 values measured sit inside the band, the
exception being `volatility_100_index` at lag 30 on -0.0091, and Ljung-Box on
squared returns has no p-value below 0.057. There is **no volatility clustering
at all**. Variance ratios at 2, 5, 15 and 60 minutes
are within two standard errors of 1 everywhere except the damaged feed in
section 6. `RV cv` is the coefficient of variation of five-minute realised
variance: theory for iid normal is sqrt(2/5) = 0.632, measured is 0.628 to
0.637, and shuffling the same returns - which destroys any clustering while
keeping the marginal distribution - moves it by less than 0.01.

**This is the place to be suspicious of a number landing on its null**, because
that is a mistake this repository has published before. Three things say the
columns are alive. The null here *is* the vendor's claim, so hitting it is the
alternative hypothesis rather than the absence of one. The same harness on the
same day and the same code path gives Boom and Crash a kurtosis of 20 and an
RV cv of 2.1, so the estimators do move when the data moves. And the shuffle
control reproduces the RV cv to three decimals, which a constant column could
not do.

## 5. The twins are one law at two sampling rates

From the tick table, with each feed's per-tick volatility divided by the square
root of its own median tick interval:

| pair | sd per tick, 2s feed | sd per tick, 1s feed | ratio | sd per sqrt(s), 2s | sd per sqrt(s), 1s |
| --- | --- | --- | --- | --- | --- |
| V10 | 2.515e-05 | 1.800e-05 | 1.397 | 1.779e-05 | 1.799e-05 |
| V25 | 6.305e-05 | 4.456e-05 | 1.415 | 4.459e-05 | 4.456e-05 |
| V50 | 1.256e-04 | 8.896e-05 | 1.412 | 8.882e-05 | 8.896e-05 |
| V75 | 1.896e-04 | 1.340e-04 | **1.415** | 1.340e-04 | 1.340e-04 |
| V100 | 2.561e-04 | 1.809e-04 | 1.416 | 1.810e-04 | 1.808e-04 |

The per-tick standard deviations differ by 1.397 to 1.416 against
sqrt(2) = 1.4142, and the per-second figures agree to within 0.16% on four of
the five pairs - exactly, to the printed four figures, on V75. The outlier is
V10, 1.1% apart, and its `1s` feed is missing 2% of its ticks in this window.
**Same law, twice the sampling rate, independent draws.** That is the whole relationship between a
twin pair, and it is worth stating positively because it is what everything
above rules the alternatives out in favour of.

It also has a practical edge to it that is not a trading edge: for any strategy
whose risk is set per unit time rather than per tick, the twins are
interchangeable, and the `1s` variant gives twice the observations for the same
volatility. [instruments.md](instruments.md) has V75 at -0.028R over 11 closes
and V75(1s) at -0.071R over 10; those are two samples of one process and can be
pooled.

## 6. No exact repeats - and one feed that is quoted too coarsely to measure

Windows of consecutive mid-price differences, quantised to each feed's own
quote resolution and hashed for exact equality. The longest window any clean
volatility feed prints twice in 24 hours is **2 to 6 steps**, which is what the
expected-collision column beside it predicts from discretisation alone. No
period, no reused seed, nothing.

The first version of this test quantised every feed to two decimals and reported
a single-step collision probability of **exactly 1.00** for
`volatility_250_1s_index`, which trades at 0.2728 and moves in the fifth
decimal. Every step rounded to the same integer. That is the dead-column failure
mode, caught by the fact that 1.00 is not a number data produces, and the fix is
`quote_decimals` measuring the grid from the quotes.

Which then found a real one. **`volatility_150_1s_index` is unusable at tick
level in this store.** Its quote step is 0.01 against a per-tick move whose sd
is 0.014 - a ratio of 1.40, where every other volatility feed runs 12 to 3,676 -
leaving **11 distinct step values** in the whole day. That rounding produces a
first-order tick autocorrelation of **-0.0705** (-0.0984 on evenly spaced
ticks), against a +/-0.0084 band, and inflates its tick-implied annual
volatility to 196.5% where its one-minute bars read 150.7%. The feed is also
missing ticks: 7.85% of its gaps exceed three seconds where the others run
0.00% to 2.94%. Both are facts about the quote and the collector, not about the
generator, and the one-minute bars for the same feed pass every test in section
4. **Do not compute tick statistics on volatility_150_1s.**

## What did turn up: one clock, sixteen streams

Every feed prints on the same timetable. Median distance from each tick of one
feed to the nearest tick of another is **8 to 9 milliseconds**, where
independent clocks at these rates would give 250 to 500. All five standard
volatility indices print at 229ms into each two-second slot - the same
millisecond, to the resolution stored.

That is a shared *timetable*, not a shared driver, and the distinction is worth
the paragraph because the timetable can imitate the driver. Correlating
|return| on a one-second grid gives `volatility_25_index` against
`volatility_75_index` **+0.3997 at lag zero** - by far the largest number in
this study, and it survives at +0.1913 on a two-second grid. It is an artefact.
Both are two-second feeds, so on a one-second grid both contribute a zero on
every other step, and because they print on the same clock **their zeros line
up**. The correlation is between two sampling patterns. The grid-free version of the same question - realised variance per
minute from each feed's own ticks, section 3 - puts the same pair on the noise
floor.

The harness prints `READ SECTION 0c FIRST` above that table. A reader who takes
+0.3997 at face value has found a shared driver between V25 and V75.

## If something had survived, it would still not have been a trade yet

Nothing did, so the sizing question is moot - but the shape of the answer should
be on the page rather than discovered later. A twin lead would have had to clear
its control in both halves before anything else was asked, and then the next
question is not sizing, **it is Deriv's terms**.

The synthetics are the broker's own product, quoted by the broker, settled by
the broker. A relationship between two of them that lets one predict the other
is by construction a defect in that product, and a broker's terms generally
reserve the right to void trades judged to exploit an error in its pricing.
An edge that gets voided on withdrawal is not an edge; it is unpaid QA. So the
order of operations on a generator artefact is: measure it, read the contract,
*then* size it - and the contract question belongs inside the finding, because
a finding that cannot be settled is not a finding.

That also bounds how much this page is worth being wrong about in the other
direction. A false positive here would have been sized into and would have cost
real money, which is why the bar was a line of code before it was a sentence.

## How many comparisons

**916,248**, and none of them is read on its own.

| | tick harness | bar harness |
| --- | --- | --- |
| return cross-correlation | 576,480 | 7,560 |
| \|return\| cross-correlation | 288,240 | - |
| volatility clock | 7,560 | 5,760 |
| tick-index alignment | 29,040 | - |
| co-jumps and exceedance | 960 | - |
| autocorrelation and normality | 128 | 240 |
| repeats, publication clock, other | 184 | 96 |
| **total** | **902,592** | **13,656** |

Every twin figure quoted above is a z-score against controls computed with the
identical statistic over the identical lag set, and the tick harness prints
`twins exceeding the largest control` directly: **0 of 5**, on both grids, in
the full day and in both twelve-hour halves. On the bars two cells did clear
their control - v75 returns in the second half at +2.94, v100 fifteen-minute
realised variance pooled at +3.40 - which is the count you get from taking a
maximum this many times, and neither holds across the split.

## What this does not say

* **The ticks are one day.** A PRNG period longer than 86,400 draws is invisible
  here, and a seed reused across days is invisible entirely. Only the bar tests
  reach 59 days, and one-minute bars cannot see a seconds-scale lead. **The
  whole seconds-scale claim rests on 24 hours**, and the way to strengthen it is
  to keep the tick collector running, not to re-analyse this window.
* **One publication slot is the floor.** Everything prints on a shared clock at
  1s and 2s, so a lead shorter than a slot cannot be observed from stored
  quotes at all. Testing that needs the websocket stream timestamped on arrival.
* **Uncorrelated is not independent.** What is excluded is linear dependence in
  returns, in |returns| and in log realised variance, plus co-exceedance of the
  extremes and exact equality of subsequences. A dependence structure orthogonal
  to all of those - some copula in the middle of the distribution - is not
  excluded by anything here.
* **Only the volatility family has twins.** Boom, Crash, Jump and Step appear
  here as controls. Their mirror relationships were tested at one minute in
  [generated.md](generated.md) and are not retested at tick level, though
  section 4 confirms in passing that they are the fat-tailed processes the
  volatility indices are not: kurtosis 9.7 to 20.8 against 0.02.
* **`volatility_150_1s_index` fails section 6 for reasons that are about the
  quote and the collector.** Its inclusion elsewhere as a control is harmless -
  a damaged control makes the bar harder, not easier - but nothing on this page
  is a claim about that feed's generator.
* **The law being true is a statement about 59 days.** Generators get changed.
  It is cheap to re-run and worth re-running after any long gap.

## What follows from it

Three things, none of them a trade.

**The synthetic null in other documents is sound.** [paying.md](paying.md) and
[shelves.md](shelves.md) both use a synthetic series as a no-signal control.
Section 4 says that control is exactly right: no autocorrelation at any lag, no
volatility clustering, no fat tail, variance ratio 1. A pattern that scores on
a volatility index is measuring the method, not the market.

**The twins can be pooled.** Section 5 makes V75 and V75(1s) two samples of one
law, so any per-time-unit statistic estimated on one applies to the other, and
the `1s` series is the better instrument to estimate on.

**There is nothing in these series to forecast.** That is worth saying flatly,
because 72% of this book is generated instruments
([generated.md](generated.md)). On a volatility index the only things that can
pay are the ones that do not need a forecast - the spread, the fee, the exit
policy, the sizing. Every result in this repository that came from a volatility
index and looked like prediction should be read against this page first.
