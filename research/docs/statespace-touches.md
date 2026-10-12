# The band on touches: the debt is real, modest at two sigma, large at one

Asked on 2026-10-12 as the largest unaddressed debt in the package. Every
measurement here had been on **bar closes**, which `__init__.py`'s fourth
principle warns about, and this is the first one that is not.

## What was at stake

`statespace-backtest.md` ended with a recommendation: use the random walk's
band for stops, because its two-sigma coverage is 0.953 against a nominal
0.954. **That was measured on closes, and a stop is not hit on a close** - it
is hit the moment price touches it, at any instant inside the interval. The
interval's extremes are invisible to a close, so the two numbers can differ
by a lot.

It was my own recommendation, made a day earlier, so it is the first thing
these ticks were pointed at.

## What a stop actually touches

Not the mid. A long's stop is reached by the **bid** and a short's by the
**ask**, so the honest test is asymmetric and the spread enters it directly.
Tick data makes that measurable and a finer bar series could not.

Three coverages, one pass, so they cannot differ by sample:

* **close** - the next mid close inside the band. What every earlier
  measurement tested.
* **touch, mid** - the mid's whole path inside.
* **touch, quoted** - the lowest **bid** above the lower edge and the highest
  **ask** below the upper.

## The answer

XAUUSD and BTCUSD, at ten-second and one-minute intervals, the walk's step
fitted on the first half and everything scored on the second:

| arm | 1 sigma | 2 sigma | 3 sigma |
| --- | --- | --- | --- |
| nominal | 0.683 | 0.954 | 0.9973 |
| close | 0.868 | **0.969** | 0.988 |
| touch, mid | 0.780 | 0.949 | 0.983 |
| **touch, quoted** | **0.753** | **0.944** | 0.983 |

**At two sigma the debt is 0.025 and it changes the recommendation without
overturning it.** The band contains the next close 0.969 of the time - it
*over*-covers against the nominal 0.954 - and holds a quoted path 0.944 of
the time, which *under*-covers. The two bracket the nominal, so a two-sigma
stop is breached about one time in eighteen rather than one in twenty-two.
Usable, with that correction.

**At one sigma the debt is 0.115 and the recommendation does not survive.**
0.868 of closes against 0.753 of quoted paths. A one-sigma band read off
closes would suggest being stopped out about one interval in eight; the real
rate is one in four. Anything sized on a tight band from close-based coverage
is wrong by that much.

## The gap scales with the spread, which is why it varies so much

| | spread | 2 sigma close | 2 sigma quoted | gap |
| --- | --- | --- | --- | --- |
| XAUUSD 10s | 0.34 bp | 0.944 | 0.900 | 0.044 |
| BTCUSD 10s | 0.31 bp | 0.994 | 0.991 | 0.003 |
| `Volatility_75_Index` 10s | 3.51 bp | 0.956 | 0.861 | 0.095 |
| `Volatility_100_Index` 10s | 4.31 bp | 0.969 | 0.903 | 0.066 |
| `Step_Index` 10s | 0.13 bp | 0.977 | 0.952 | 0.025 |

The quoted test fails when the spread is large relative to the interval's own
movement, because the band has to contain the *quote* and the quote is half a
spread wider than the mid on each side. BTCUSD shows almost no gap - its
ten-second moves are large against its 0.31 bp spread - while the volatility
indices at three to four basis points show the largest. **So the closes
versus touches correction is not a constant: it is a function of the spread
in units of the interval's volatility**, and an instrument with a wide spread
and a quiet interval needs much more of it.

On the generated markets the one-sigma gap reaches **0.34** - 0.705 of closes
against 0.365 of quoted paths - which is the same mechanism at its extreme.

## What this changes

* **A two-sigma walk band is still the thing to use for stops**, now with a
  measured breach rate of 0.056 per interval rather than the 0.047 a
  close-based reading implies.
* **Do not size on a one-sigma band from close-based coverage.** The error is
  0.115 on the instruments measured here and 0.34 on the widest-spread ones.
* **Quote the spread in volatility units beside any touch-based number**,
  because that ratio is what sets the correction.
* **Every other result in this package is still on closes.** This measured
  the one that carried an actionable recommendation. The directional P&L, the
  displacement sequences and the fractal arms are all close-based and the
  correction above does not transfer to them automatically - it is specific
  to a band, which is a question about paths.

## The limits, stated plainly

* **EURUSD's tick store is corrupt** - a bad CRC on its time array - so the
  pair this desk trades most is absent, and the two traded instruments here
  carry 994 and 1,888 ten-second intervals.
* **The spans are hours, not years**: about five for XAUUSD and ten for
  BTCUSD. The synthetics reach three and a half days.
* Intervals with fewer than five ticks are dropped, because an interval with
  two ticks has no interior to test.

The harness is `research/ideas/touches.py`.
