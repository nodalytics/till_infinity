# Peaks, troughs, and the distance between like nodes

Asked on 2026-10-11, straight after the displacement work: can we have peaks
and troughs as such, and their distance sequencing?

Yes, and the object is a better-specified one than what came before - which is
exactly why it is worth saying that it carries nothing either.

## What was missing, and the hypothesis it suggested

The displacement sequence keeps `|level(b) - level(a)|` between **opposite**
nodes. That is how far price travelled, and it has the direction already
removed, so **a clean uptrend and a flat range with the same swing sizes are
identical in it.** There is a test asserting exactly that now, because it is
the sort of claim that should not survive on assertion.

That suggested a reason the earlier work came back null on all seven published
claims: the ratios were computed on a quantity that cannot tell a trend from a
range. So the natural fix is the **like-node step** - peak to peak, trough to
trough, **signed** - whose sign is the structural reading everybody actually
uses. Higher highs with higher lows is an uptrend.

`nodes()` returns the typed reversals, `steps()` the like-node distances, and
`structure()` the whole-series reading. `sequence()` is now built on `nodes()`
so there is one detector rather than two copies of the same loop.

**The hypothesis was wrong.** Keeping the sign does not help. Every reading
below matches its own null, for a different mechanism than the α case but an
equally mechanical one.

39 cells: ten traded instruments and four generated markets, at 1h, 4h and 1d,
span 5, run in the lab.

## 1. The peak-to-peak duration is not a period

Consecutive peaks are two swings apart, so their separation is a full cycle.
If the market has a characteristic cycle length that distribution is **tight**;
if turning points are a renewal process it is exponential, whose coefficient
of variation is exactly 1.

| | median separation | spread | a random walk's spread |
| --- | --- | --- | --- |
| EURUSD 1h | 22.0 h | 0.77 | **0.83** |
| EURUSD 4h | 100.0 h | 0.55 | **0.55** |
| EURUSD 1d | 480.0 h | 0.50 | **0.54** |
| XAUUSD 1h | 22.0 h | 0.79 | **0.82** |
| BTCUSD 1h | 17.0 h | 0.49 | **0.50** |
| `Volatility_75_Index` 1h | 18.0 h | 0.52 | **0.52** |

The spread is below 1 everywhere, which looks like structure until the walk
column is read: **a Gaussian random walk gives the same number.** A span-5
detector cannot place two peaks closer than about five bars apart, so the
short end of the distribution is truncated by construction and the
coefficient of variation falls below 1 mechanically. Nothing about the market
is involved.

### And the separation is a bar count, not a duration

The sharpest portability demonstration this desk has produced:

| frame | median separation | in bars |
| --- | --- | --- |
| 1h | 22 h | **22** |
| 4h | 100 h | **25** |
| 1d | 480 h | **20** |

The "cycle length" is twenty-odd bars at every timeframe. It is set by the
detector's reach relative to the bar, not by any clock the market keeps. A
feature built on it would mean a day at 1h and three weeks at 1d while
appearing to be the same feature - which is the defect `statespace-method.md`
exists to prevent, caught here in its purest form.

## 2. Higher highs with higher lows is the detector's alternation

The textbook trend is both sequences rising together. But any upward drift
produces both, simply because everything is rising, so agreement has to be
read against `p^2 + (1-p)^2` - what two independent sequences at the same
up-share would give.

| | agreement | drift | gain | a walk's own gain |
| --- | --- | --- | --- | --- |
| EURUSD 1h | 0.642 | 0.500 | +0.142 | +0.178 |
| GBPUSD 4h | 0.676 | 0.500 | +0.176 | +0.166 |
| AUDUSD 1d | 0.674 | 0.502 | +0.173 | +0.124 |
| `Volatility_75_Index` 1h | 0.662 | 0.500 | +0.161 | +0.154 |
| **median over 39 cells** | | | **+0.151** | **+0.158** |

Real markets gain 0.151 over the drift; a random walk gains 0.158; the
generated markets gain 0.148 to 0.161. Three populations, one number.

The mechanism is a **shared node**. A peak step and the trough step beside it
are computed from overlapping nodes: to reach a higher high, price had to rise
through the preceding trough, which makes that trough likely higher too. The
two signs are correlated by the geometry of the path and not by any trend.

This is the same family of defect as the correction factor's famous serial
correlation, which turned out to be a shared *denominator* worth exactly
-1/2. Here it is a shared node worth about +0.15. **Both are the arithmetic
of how the quantity is written down.**

## 3. One step says nothing about the next

Signed rise against the next signed rise, peaks and troughs kept apart
because interleaving them would put two different quantities in one series:

* peak lag-1 from **-0.092 to +0.044**, trough lag-1 from **-0.149 to
  +0.025**, with every rotated control inside ±0.04;
* against the trailing spread of the same series, ±0.08.

Weakly negative on balance, which is the shared-node arithmetic again and an
order of magnitude smaller than the α case because a step shares one node
rather than a whole divided term.

## 4. Nothing follows from a confirmed step

Entry at the bar **after** confirmation - the first bar a live feature could
act on - over horizons of 6, 24, 72 and 168 hours, both step directions,
gated at 1.5 spreads round trip:

**3 of 312 cells clear the cost gate, and the largest |t| among them is
0.64.** One of the three is a generated market, with the sign inverted. At
312 cells, three survivors at |t| below one is fewer than chance would supply.

## What this is worth

The code, which is better than what it replaced:

* **`nodes()`** gives typed, alternating reversals with their levels, and
  keeps the more extreme of two same-kind firings rather than dropping one
  arbitrarily;
* **`steps()`** gives the signed like-node distance, in volatility units and
  hours, with the four structural labels;
* **`structure()`** never reports `agreement` without `drift` beside it,
  because the measurement above is what happens when it is read alone;
* **one detector** feeds both views, so the swing sequence and the node
  sequence cannot drift apart.

And one reusable lesson, which is the real output. The displacement sequence's
null had an obvious candidate explanation - the unsigned size throws the
direction away - and that explanation was **testable and wrong**. Keeping the
sign produced a differently-mechanical null rather than a signal. The thing
these quantities have in common is not that they discard information; it is
that they are **arithmetic rearrangements of an alternating sequence**, and an
alternating sequence produced by a thresholded detector has strong structure
that has nothing to do with the market.

So the next pivot-derived idea should be measured against a random walk
**before** it is reasoned about, not after. Every one of the four readings
here cost nothing to null and all four came back level with the walk.

The harness is `research/ideas/peaks_and_troughs.py`.
