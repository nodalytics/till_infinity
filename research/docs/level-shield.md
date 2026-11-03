# Is a level a barrier in the path? Read for the stop, not the target

**Measured 2026-11-03, pre-registered.** The entry side of levels is closed on
this desk. This asks the exit question instead, which nothing here had asked:
not *does price reach the level*, but **given a fixed distance, does price
travel that distance less often when a level sits in the path than when the
path is clear**. If it does, the same number is a target rule and a stop rule
with opposite signs - put the take-profit in front of the nearest level, put
the protective stop beyond one so the level has to break first.

It does not. The direction was fixed before the run; **1 of 210 cells** beats
its own hardest null arm at z > +2, which is what 210 cells give by chance, and
real sits **below** the hardest null in **188 of them**.

## Verdict

| question | answer |
|---|---|
| Does a level in the path suppress the move, at matched distance, within the same anchor? | **No.** Of 210 mirror cells, 22 exceed their hardest null arm at all and **1** does so at z > +2 (btc 1d d=4, z +2.65), against about 2 expected by chance. Real is **below** the hardest null in **188 of 210** |
| Does the reach rate fall as more levels block the path? | **No.** **0 of 420** dose cells exceed the hardest null at z > +2; the slope's sign disagrees between the up and down side on the real arm and agrees on the nulls |
| So should a target go in front of a level, or a stop beyond one? | **Neither is supported.** No gate shipped. The one thing a level in the path predicts at 15m is the move being *more* likely, which reverses by 1h |
| Does a per-side (long/short) parameter help? | **Null.** Mean asymmetry +0.004 / -0.004 / -0.018 at 15m / 1h / 1d across 14 feeds, against a standard error of 0.0155; per-feed spread 0.035-0.058 against the nulls' 0.012-0.021, but a feed keeps its asymmetry's **sign** on only 5-7 of 14 crossings between intervals, where a **bar shuffle keeps 6-8**. There is nothing to fit |
| Does the harness reproduce a known number? | **Yes, at 1d and only there.** The presence gap is **+0.0528** against [`magnet.md`](../../docs/magnet.md)'s **+0.046 [+0.027, +0.073]**, from a different detector, a different venue policy and a stricter placebo. At 15m it is -0.039 and at 1h +0.007 |
| What *is* worth recording | **A bar-level barrier race departs from 1/(1+N) by -0.25 to +0.12R, monotone in (stop - target) distance, growing with the interval - and the surrogates do it harder.** At 1d a 4:1 reward:risk reads **-0.2529R** where the closed form says zero; a GARCH surrogate with the same bar geometry reads -0.7274R |

## The rules, as frozen before the run

* **Anchors are entry-agnostic**: every bar past warm-up, no signal, so nothing
  about an entry can leak. 14 feeds, one venue each, chosen by bar count at
  that interval and fixed before any result was seen.
* **Distances** 1.0, 1.5, 2.0, 3.0, 4.0 volatility units, the unit being a
  causal EWMA of the bar range (`drive-q-from-the-range`).
* **Shielded** = a level between 0.30 and 0.90 of the way to the target.
  **Clear** = no level anywhere from here to 1.20 of it. Same distance in both
  arms, so geometry is identical.
* **Horizon** 48 bars at 15m and 1h, 20 at 1d.
* **Direction pre-stated**: a barrier means a *positive* mirror gap and a
  *negative* dose slope, **on both sides**. One sign up and the other down is a
  drift or a book-geometry effect, not a barrier.
* **A finding needs** the real value outside the hardest null arm's draws, the
  sign consistent across intervals, and survival of Benjamini-Hochberg over
  every cell.

## The three estimators, weakest control to strongest

**Presence gap** - shielded against clear, within quintiles of trailing
compression. It leans on a clear arm that is only 7-9% of anchors, because at
`KEEP` 24 levels about 80% of anchors have something in the path. A clear path
is a regime of its own.

**Dose slope** - the reach rate against how many levels block the way, within
strata. Uses every anchor and asks for monotonicity, which one cell cannot
fake.

**Mirror gap** - the one that decides. Anchors where one side is blocked and
the other is clear, paired **within the anchor**: the day, the hour, the
volatility estimate and the forward window are the same bar's, so no property
of the regime can produce the difference. `magnet.md` §5 is why this is the
headline rather than the stratified version - a level exists on days price
subsequently travels 8-17% less far, which accounted for the whole of that
study's -4.6 point deficit, and its own day-fixed control took the level
effect to -0.009 [-0.062, +0.038]. The residual up/down excursion skew is
measured on the concordant anchors of the same series and subtracted.

## The nulls

Three arms, every one through the **same detector** over the same bar geometry,
four draws each:

| arm | keeps | removes |
|---|---|---|
| `garch-bars` | volatility clustering, fat tails, bar wickiness | path structure |
| `walk-geometry` | bar wickiness, the step distribution (`node/surrogates.walk_with_bar_geometry`) | path structure **and** clustering |
| `bar-shuffle` | each bar's own shape, the marginal step distribution | all memory |

`garch-bars` exists because `walk-geometry` resamples steps i.i.d. and so has
none of this market's clustering - and clustering is the mechanical route by
which "a level is nearby" predicts a smaller forward excursion, since a level
nearby means price has been turning nearby. An arm without it cannot judge the
claim.

**The shuffled twin named the mechanical observable immediately**, as
`let-the-shuffled-twin-name-the-mechanical-observables` says it would. On
`bar-shuffle` the mirror gap is already -0.03 to -0.045 at d = 2-3: a level
above price is a price price **has already reached**, so it is demonstrably
reachable from near here, while the clear side is a direction price has not
recently gone. The blocked side is reached more often on any series. Reading
the raw gap as a barrier effect without that arm would have produced a
confident finding with the sign backwards.

## Power, before the null

A null is only worth reporting with the strength at which the test stops seeing
one, so the alternative hypothesis was planted rather than approximated: a walk
with this market's bar geometry, its own `Levels` book maintained causally, and
every step that would carry price across a level in that book reflected about
it with probability `strength`. 0 is a plain walk, 1 is a book of hard walls.
EURUSD 15m, 5,136 bars, three draws per strength, ten cells each.

| planted strength | dose slope recovered | z | cells negative | cells monotone |
|---|---|---|---|---|
| 0.00 | +0.0086 | +0.71 | 0.37 | 0.03 |
| 0.10 | -0.0066 | -0.52 | 0.67 | 0.13 |
| 0.25 | -0.0124 | -1.01 | 0.70 | 0.10 |
| **0.50** | **-0.0355** | **-2.68** | **0.97** | **0.50** |
| 0.75 | -0.0387 | -2.84 | 0.97 | 0.43 |
| 1.00 | -0.0386 | -2.20 | 0.90 | 0.43 |

**The test sees a barrier that reflects price half the time or more, and goes
blind between 0.25 and 0.50.** At strength 0 it correctly reads nothing. So the
null below covers barriers that hold at least about half of their touches; one
that leaks more than three times in four would not be visible on a single
series at 15m, which is the reason for carrying 14 feeds.

The calibration is the useful part. **A book of hard walls produces a dose
slope of only -0.039.** The real down side reads about -0.034 - nearly a hard
wall - but `garch-bars` already supplies -0.027 of it from clustering and bar
geometry alone, leaving roughly -0.007 attributable to levels, about a sixth of
a hard wall. The real up side reads **+0.049**, the wrong sign outright. A
barrier that reflects one touch in six or seven sits below this test's blind
point, which is the honest upper bound on what levels could be doing here and
is not a quantity worth a parameter.

## What came back

### The mirror, which decides

210 cells (14 feeds x 3 intervals x 5 distances). **22 exceed their hardest
null arm at all, and 1 does so at z > +2** - which is what 210 cells give by
chance. Real sits **below** the hardest null in **188 of 210**. 21 cells are
nominally positive on their own day-block sd and 24 nominally negative, and 49
survive Benjamini-Hochberg - the survivors being overwhelmingly the *other*
sign, where the blocked side is reached more often than the clear side.

The per-instrument table is the point, and pooling it would have hidden the
answer. Instruments disagree in sign at the same interval and the same
distance:

| 1h, d = 3 | gap | own z | hardest null | excess |
|---|---|---|---|---|
| gold | **+0.2533** | +3.18 | +0.2397 | +0.0136 |
| spx500 | **-0.2595** | -2.81 | +0.2124 | -0.4719 |
| us100 | -0.1530 | -2.06 | +0.1933 | -0.3463 |
| eurusd | +0.0498 | +0.57 | +0.2301 | -0.1803 |
| audusd | -0.1660 | -1.71 | +0.1493 | -0.3153 |

Gold at 1h reads +0.2533 (z +3.18) and +0.3241 (z +3.66) at d = 4, which read
alone is the finding this study was looking for. Its own null arms produce
+0.2397 and +0.2701. The excess is +0.014 and +0.054. **The single most
impressive cell in the study is reproduced by a walk with the same bar
geometry.**

The only cell that beats its hardest null at z > +2 is **BTC at 1d, d = 4:
+0.2550 against a hardest null of +0.0705, an excess of +0.1845 at z +2.65** on
476 discordant anchors over 5,012 days. The next is usdcnh 1d d = 3 at z +1.97
and then nothing above +1.5.

It fails the consistency requirement fixed before the run: the same cell reads
**-0.2120 at 15m** and +0.1133 at 1h, so the sign is not stable across
intervals. It is 1 of 210 cells where chance gives about 2. And gold 1d is
positive at every distance while spx500 and us100 1d are negative at every
distance - three strong-uptrend instruments, two signs. Recorded, not built
on.

### The dose

420 cells (the mirror's, split by side). **0 exceed the hardest null at
z > +2**; 112 BH survivors, all the other way. The decisive feature is not the
significance but the **sign disagreement between sides on the real arm and the
agreement on the nulls**: at 15m the real up-side slope averages +0.049 and the
down side -0.034, while every null arm has both sides the same sign and the
same size. A barrier is a property of the path, so it cannot be present in one
direction and reversed in the other; a drift or a book-geometry effect can.

### The presence gap, and the baseline

Pooled and within strata, averaged over distance and side:

| arm | 15m | 1h | 1d |
|---|---|---|---|
| **real** | **-0.0389** | +0.0067 | **+0.0528** |
| garch-bars | -0.0040 | -0.0031 | +0.0261 |
| walk-geometry | -0.0011 | +0.0110 | +0.0117 |
| bar-shuffle | -0.0029 | +0.0076 | +0.0175 |
| feeds positive, real | 4 of 14 | 9 of 14 | **12 of 14** |
| sd across feeds, real | 0.0420 | 0.0566 | 0.0469 |

Stratifying moves these by under 0.002, which is itself a result: the quintile
control that `topology.md` would call for does almost nothing here, because the
mirror estimator had already removed the regime by pairing within the anchor.

**At 1d the harness reproduces `magnet.md`.** +0.0528 against that study's
+0.046 [+0.027, +0.073], from a different detector (this is
`indicators.Levels`, a Kalman book over `trend.pivots`; that was the retired
structures engine's `pips.as_of` book), a different venue policy (one venue per
feed here, a three-venue consensus median there) and a stricter placebo there
(empty of levels, swings **and** round numbers within 1.0v). Two independent
implementations landing inside each other's interval, on 12 of 14 feeds and
19.2 to 19.9 years of daily history for the FX pairs and gold, is the strongest
evidence in this document that the measurement is sound.

It also localises that number: **+0.046 is a 1d quantity.** At 15m the same
estimator reads -0.039 and at 1h +0.007. `reproduce-the-baseline-before-an-
increment` says the cause of a mismatch is usually the data window, and here it
is the *interval*: 10 of 14 feeds are negative at 15m and 9 of 14 positive at
1h. So the 15m and 1h numbers in this study are not a failed reproduction of
magnet.md, they are a different regime.

And **a quarter to a half of magnet.md's +0.046 is mechanical.** The null arms
supply +0.012 (bar geometry alone) to +0.026 (geometry plus clustering) of the
1d gap, which nothing had measured. magnet.md attributed the whole deficit to
the day mix and its own day-fixed control took it to -0.009; this says bar
wickiness and volatility clustering account for a quarter to a half of it
before the day mix is reached at all.

### Per-side asymmetry: the null the user's question needed

The asymmetry of the dose slope, up side minus down side, averaged over
distances, across 14 feeds:

| arm | 15m mean | 15m sd across feeds | 1h mean | 1h sd |
|---|---|---|---|---|
| **real** | **+0.0045** | **0.0580** | **-0.0045** | **0.0359** |
| garch-bars | +0.0034 | 0.0210 | +0.0113 | 0.0196 |
| walk-geometry | +0.0017 | 0.0197 | +0.0011 | 0.0185 |
| bar-shuffle | +0.0031 | 0.0120 | +0.0053 | 0.0201 |

The mean is zero. The per-feed spread is real - 0.058 at 15m against the nulls'
0.012-0.021, so instruments do differ by more than the nulls - and it carries
**no information at all across intervals**:

| arm | feeds keeping the sign from 15m to 1h | correlation |
|---|---|---|
| real | **6 of 14** | **+0.027** |
| garch-bars | 5 of 14 | -0.201 |
| walk-geometry | 5 of 14 | -0.305 |
| bar-shuffle | **8 of 14** | +0.225 |

**A bar shuffle replicates its own asymmetry better than the real market
does.** audusd reads +0.073 at 15m and -0.032 at 1h; gbpusd +0.099 and -0.007;
usdjpy +0.002 and +0.086. A per-side parameter fitted to the 15m number is a
parameter fitted to that sample's 15m noise. With 14 feeds and a per-feed sd of
0.058, the standard error on the mean asymmetry is 0.0155, so the mean is
0.3 sigma from zero: the test is not short of power to see a *common*
asymmetry, it is that there is not one.

### The one thing worth keeping: the race is not 1/(1+N), and nulls miss it harder

Entry-agnostic races, 110k-145k decided races per cell pooled over 28
series. Edge in R, so a walk is zero by construction.

| interval | target | stop | real | garch-bars | walk-geometry | bar-shuffle | ties |
|---|---|---|---|---|---|---|---|
| 15m | 1.0 | 4.0 | +0.0170 | +0.1253 | +0.0349 | +0.0351 | 0.11% |
| 15m | 2.0 | 4.0 | +0.0306 | +0.1544 | +0.0384 | +0.0378 | 0.11% |
| 15m | 4.0 | 1.0 | **-0.0732** | **-0.5381** | -0.1721 | -0.1612 | 0.11% |
| 15m | 4.0 | 2.0 | -0.0646 | -0.3340 | -0.0991 | -0.0890 | 0.11% |
| 1h | 2.0 | 4.0 | +0.0261 | +0.1583 | +0.0201 | +0.0265 | 0.06% |
| 1h | 4.0 | 1.0 | -0.0435 | -0.5348 | -0.0880 | -0.0835 | 0.08% |
| 1h | 4.0 | 2.0 | -0.0540 | -0.3418 | -0.0503 | -0.0638 | 0.06% |

The edge is monotone in (stop distance - target distance): a stop wider than
the target beats 1/(1+N) by 1-3% of R, a stop tighter than the target loses to
it by 4-7%. **Every null arm produces the same pattern three to seven times
larger.** Real is *closer* to 1/(1+N) than any surrogate, which is the recorded
`the-walk-is-the-best-calibrated-band` from the other direction.

It is not the tie rule: ties are 0.04-0.8% of decided races, an order of
magnitude too small, and the conservative rule biases against the target, which
is the wrong sign for the wide-stop half. The mechanism is that a first passage
read off bar highs and lows is an *excursion*, not a close path, so a near
barrier is crossed sooner than a diffusion calculation on closes implies - and
the nearer the barrier, the larger that effect in proportion.

**The consequence for this desk is a measurement caveat, not a strategy.** Any
backtest that races barriers off bar extremes and judges the result against an
analytic 1/(1+N) inherits a spurious "wide stops are better" tilt of 2-7% of R
on real bars, and up to 54% on a GARCH surrogate. Compare a rule against the
same race on matched surrogates, never against the closed form.

## What was not done, and why

* **No shield-band or `keep` sweep.** The band is fixed at 0.30-0.90 of the
  distance and the book at `KEEP` 24. With 0 of 175 and 0 of 280 cells in the
  predicted direction and real below the hardest null in 150 of 175, a band
  sweep buys cells rather than evidence. It is the obvious re-opening if the
  *claim* changes.
* **No cost anywhere.** Everything here is a hit rate or a distance. Six of the
  14 feeds have enough recorded quotes to measure a median spread per venue
  (eurusd, gbpusd, gold, btc, us100, spx500); the other eight have at most two
  quotes, so `corpus.write` skips them and no spread was invented for them.
  Geometry is sound on all 14 because nothing is priced.
* **No 4h interval**, where the store holds about 714 days on the indices.
* **The Bjorgum zone was not tested**, and it is the level primitive with the
  measurement behind it (real zones break 33.9/37.7/37.3% against a synthetic
  control's 81.3/85.0/80.5%). This study used `indicators.Levels` because that
  is the book a strategy here reads and the one the per-side parameters went
  into. A zone is a different object with a width, and "price stops inside a
  band" is not the claim tested here.

## The code

| file | what it is |
|---|---|
| `research/ideas/level_shield.py` | the data, the null arms, the causal book replay, the first-passage walk and the race |
| `research/ideas/level_shield_agg.py` | the three estimators as count tensors, with a day-block bootstrap |
| `research/ideas/level_shield_run.py` | the panel, one process per (feed, interval) |
| `research/ideas/level_shield_power.py` | the planted barrier and its strength sweep |
| `research/ideas/level_shield_report.py` | the tables above |

The first version of the aggregation resampled days as boolean masks and did
not finish one series in seven minutes; binning to a `(day, bucket, stratum)`
count tensor made a draw an array index. That also fixed a correctness problem
rather than only a speed one - a presence mask cannot represent a day drawn
twice, so the standard errors it produced were too narrow.
