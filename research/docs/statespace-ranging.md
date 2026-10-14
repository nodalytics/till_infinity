# A range statespace can build, and seventeen levels that do not hold

Asked for on 2026-10-14, across four messages that are one piece of work:
statespace should pick **levels** and a **range** with the current price inside
it; the range's edges should act as **support and resistance**; the levels
should be **liquidity aware**; they should be **candlestick order-flow aware**
since there is no order book; and **seasonal and volume profiles should combine
into something more powerful**.

The range is built and it works. **None of the levels hold.**

## Why a range was buildable where "find the levels" was not

`docs/specs/2026-10-14-statespace-as-the-structures-library.md` recorded level
discovery as the one migration item blocked on **design**, and the obstacle is
measured: `definitions-cannot-be-states` found that a mixture whose centres are
**free states collapses onto the data**.

A range edge is not a free position. It is defined by a **share** - of volume,
or of observations - so it is anchored by construction and the only thing left
to estimate is how far out that share sits. `statespace/ranging.py` is built on
that, and its thin edges bracket the current price **by construction** rather
than by luck, which is asserted on five seeds.

Three profiles, from OHLCV alone:

| profile | a price counts when | what it means |
| --- | --- | --- |
| **volume** | any bar covered it | where trade happened |
| **acceptance** | a bar's **body** covered it | price traded through and closed past |
| **rejection** | a bar's **wick** covered it | price went there and came back |

The third is the candlestick order-flow channel, and
`statespace-orderflow-from-bars.md` is why it is more than a convention: the
sign of exactly this separates a real order book from a generated one with no
exceptions across nineteen classes - traded markets close **nearer the middle
of their range** than a matched walk on 8 of 8, and every jump generator does
the reverse. Rejection is what a book does.

## Then the test, against the standard that refuted this family before

`research/docs/game-theory.md` ran "levels hold" and its verdict was blunt:
round numbers *"turn price no more than placebo levels"*, there is no hunt at
yesterday's high or low in FX (**66.2%** against a placebo's **67.7%**), and *"a
trap's new extreme holds worse than a random price"*.

So each candidate is paired with a placebo **the same distance away on the same
side** - a nearer price is touched sooner and in calmer conditions, so comparing
against any random price compares distances. From the first touch: does price
travel one typical bar **back** before one bar **through**, within 24 bars?

| level, traded | holds | placebo | lift | races |
| --- | ---: | ---: | ---: | ---: |
| thin low | 49.0% | 48.8% | +0.2% | 1,999 |
| thin high | 48.2% | 47.9% | +0.4% | 2,075 |
| value low | 47.9% | 49.3% | -1.3% | 1,271 |
| value high | 48.9% | 47.3% | +1.6% | 1,395 |
| centre, the point of control | 47.5% | 46.8% | +0.7% | 1,443 |
| rejection centre | 47.3% | 47.4% | -0.1% | 1,459 |
| rejection low | 49.7% | 48.9% | +0.8% | 2,165 |
| rejection high | 47.0% | 46.5% | +0.5% | 2,248 |
| acceptance centre | 48.4% | 48.2% | +0.2% | 1,415 |
| **hourly centre** | 45.0% | 45.5% | **-0.5%** | 795 |
| **hourly low** | 45.7% | 44.3% | **+1.4%** | 560 |
| **hourly high** | 42.9% | 43.4% | **-0.5%** | 791 |
| **wick 2:1** | 48.1% | 46.9% | **+1.2%** | 2,201 |
| **wick 3:1** | 47.8% | 48.2% | **-0.3%** | 2,193 |

Every lift is inside `+/-1.6%` and every hold rate is a coin.

## Momentum turns are not levels either, and the gate says so

Asked for on 2026-10-14: *"price points that had at least 1 momentum or
acceleration turn could be a level"*. These are the only candidates here built
from **dynamics** rather than from volume or candle geometry, and they are
native to a state-space filter in a way a profile cannot be - `levels.Kalman`
carries `(price, slope, acceleration)`, so the price where momentum reversed is
something it already knows.

| level | holds | placebo | lift | races |
| --- | ---: | ---: | ---: | ---: |
| turn, slope sign change | 49.0% | 48.7% | +0.4% | 1,905 |
| accel turn | 46.2% | 47.0% | -0.8% | 1,352 |
| **gated turn** | 49.0% | 49.1% | **-0.2%** | 1,838 |

**The gated row is the informative one.** `Kalman.turning` means *"earned a
trend, and is now decaying toward or through zero"* rather than "the slope is
near zero" - the slope has to clear **two of its own standard deviations**
before a turn counts. That is the sharper hypothesis, and if a momentum turn
marked a level the gated version should mark it **better**. It is marginally
worse.

That is the same internal inconsistency the published wick thresholds showed,
where tightening 2:1 to 3:1 moved the lift from `+1.2%` to `-0.3%`. A real
effect does not weaken when its filter is tightened; twice now, in two
unrelated families, the tighter filter has been the worse one.

## Three independent reasons that is a null and not a small effect

**The generated feeds set the noise floor and it is wider than every lift.**
`Volatility_75` and `Step_Index_200` have no levels by construction, and their
lifts span **-3.5% to +3.6%** on the same design. Nothing in the traded table
leaves that band.

**The stricter wick threshold is worse than the looser one.** The published
construction calls 2:1 "significant rejection" and 3:1 a source of
"high-probability setups". Measured, 2:1 gives **+1.2%** and 3:1 gives
**-0.3%**. A real effect does not weaken when its filter is tightened; noise
does exactly that.

**And re-running moves each lift by more than the lift.** Across runs on the
same data, differing only in the placebo draws, `value low` went from `+0.6%`
to `-1.3%`, `hourly low` from `-0.5%` to `+1.4%`, `centre` from `+0.7%` to
`+2.3%` and `value high` from `-0.1%` to `-2.2%`. A run-to-run spread of about
`+/-2%` is wider than every lift in the table, which is the plainest possible
statement that none of them is an effect.

## So the seasonal combination makes it worse, not more powerful

The three hourly rows are the **weakest in the study** - the lowest absolute
hold rates at 42.9% to 45.7%, and two of three lifts negative. A profile built
from one hour-of-day bucket uses a sixth of the bars and buys nothing for it.

That is worth separating from the seasonal result it was reasoned from.
`seasonal.Profile` earns **+1192 nats** on `Q` from exactly this conditioning,
and it still does - but `Q` is **how far** price goes, and this is **which
prices matter**. `seasonality-belongs-on-q` is the recorded form of that
distinction, and this is a second instance: the hour of day is strongly
informative about volatility and says nothing about level location.

## What survives, and it is not nothing

**The range.** `Range` gives a bracket containing the current price with
liquidity-aware edges, a point of control, a value area with an explicit
`inside` check, and `position` for where price sits across the range. That is a
**calibrated interval**, which is what a stop and a size are set from - and
`statespace-conformal-filter-band.md` measured this desk's intervals at
**95.7%** coverage against a 95.0% nominal, so intervals here are trustworthy
in a way levels are not.

**What does not survive is the extra claim** - that the edges turn price. They
do not, by any of the seventeen constructions, which now includes the
liquidity-aware, the candlestick-aware, the seasonal and the two published
wick thresholds.

## Two defects found on the way, both by a check rather than by review

**The tally never looked at the race.** `sum(1 for r, _, _ in cells)` yields one
per row whatever `r` is, so both arms read exactly **100.0%** on every line. A
`DEGENERATE` guard added for the first symptom caught it on the second run, and
an instrumented trace showed the race itself had been correct all along. Two
earlier attempts to explain the 100% - the baseline move being too small, then
the race direction - were both wrong, and the guard plus the trace found in
minutes what reasoning did not.

**And acceptance leaked into rejection.** Volume is assigned to bins by **index**
while body and wick were classified by the bin's **centre**, so an edge bin
whose centre fell outside the bar still received its share and was labelled
wick. A bar given no open and close is all body, so its rejection profile must
be empty - a test asserted that, and it failed. Classified by **overlap**
instead, `rejection low`'s lift fell from `+1.5%` to `+0.6%`: part of the
largest apparent effect in the study was that leak.
