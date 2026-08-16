# Does it matter where a level sits in the larger move

Run: `python research/harness/cycles.py`

Every feature the model has is local to the touch — `approach_vol`,
`depth_vol`, `run_vol`, `pivot`, `backcheck`, and the six candidates
[features.md](features.md) §4 tested all describe the last few bars before
price arrived. None says whether the instrument has been climbing for a
quarter, falling for one, or oscillating; nor, if oscillating, whether this
level is near the floor or the ceiling. [todo.md](../docs/todo.md) §6c asks
whether that missing context carries anything.

**Still no, but it is now a close no rather than an empty one.**

> **Re-measured on 2026-08-15** after the backfill in [todo.md](../docs/todo.md)
> §0d took the sample from 1,862 touches over 26 cycles to **10,483 touches
> over 73 cycles across all 14 instruments**. The first reading of this document
> said "nothing separates at any threshold". That is no longer true, and the
> sections below are the second reading. The original numbers are kept in git
> rather than here, because a stale number that looks current is worse than no
> number.

One cell now separates, the direction is consistent, and it still fails the
test that matters: adding cycle state to the model is worth **+0.0041 AUC with
a 95% interval of −0.0008 to +0.0085**, which includes zero.

## 1. The label is a rule, because otherwise it is hindsight

"We were in an uptrend" is trivially true afterwards and worthless in advance.
The label here is computed from daily closes **strictly before the touch
began**, by Kaufman's efficiency ratio over a 60-day window:

    ER = |last - first| / sum of |day-to-day moves|

One if price went straight there, near zero if it wandered back over itself.
The threshold was fixed before looking, against a stated null: a random walk of
N steps has an expected ER of about 1/sqrt(N), which is **0.129** at N=60, so
`TREND = 0.30` means "more than twice as directional as a coin".

That null is also the check that the measure works. Across twelve years of
daily closes the observed median ER is **0.131** against the predicted 0.129.

## 2. Two ways to get this wrong, both found by running it

### A cross-venue median destroys the measure

The first version took the median close across venues, on the reasoning that
`structures` takes a cross-venue consensus everywhere else. It was wrong here,
and the failure is instructive.

Venues within a feed sit at slightly different levels — spx500 quotes between
7,780 and 7,805 across eight of them, a third of a percent — and they do not
all report every day. So the median switches between price levels as coverage
changes, and **every switch adds a step to the path the instrument never
took**. ER is a ratio *to* that path, so inflating it crushes the ratio:

| | median across venues | one venue's own series |
|---|---|---|
| spx500 ER, same window | 0.081 | 0.121 |
| median over all touches | 0.049 | 0.131 |

Consensus earns its keep at tick level, where one broker's spike is a false
touch. It buys nothing across a quarter, where the venues disagree about the
third decimal and agree about the direction.

### A fixed threshold cannot label a downtrend

Under `TREND = 0.30` the first reading of this document found **no downtrend
days at all**. Over the full daily history, downtrends are 0.0% of us100 days
and 0.1% of spx500 days against 12.5% and 9.0% uptrend.

Markets fall faster and messier than they rise, so a decline rarely sustains a
high efficiency ratio over a quarter. **A symmetric threshold on an asymmetric
process labels one tail and never the other**, which leaves half the question
unasked rather than answered.

**The backfill confirmed this rather than fixing it.** With fourteen
instruments over 200–300 days each, `TREND = 0.30` still calls only **1.6%** of
touches a downtrend against 3.7% an uptrend — better than zero and nowhere near
balanced. More data does not repair a measure that is asymmetric by
construction.

The fix is the one this project reaches for everywhere else: stop using a
constant. Terciles of *the feed's own* prior ratio distribution are symmetric
by construction and self-calibrating, since btc's ordinary directionality is
not eurusd's. That gives a usable split — **43.5% range, 34.6% downtrend, 21.9%
uptrend** — and it is the labeller the real test runs under.

## 3. The falsification, and what it says now

The question is not "does cycle state predict direction". Position-in-range
alone will correlate with `side` — near a range floor most touches come from
above — and would score as a discovery while adding nothing `side` did not
already say. The question is whether cycle state **changes what `side`
means**: within each state, does the up-rate for a given side differ from that
side's pooled rate by more than the interval on the cell?

Under the self-calibrating labeller, which now has enough downtrends to be
worth reading — 34.6% of touches against 0.0% before the backfill:

| side | cycle | n | up-rate | 95% interval | vs pooled |
|---|---|---|---|---|---|
| above | *(pooled)* | 5,290 | 73.4% | 72.2% – 74.5% | |
| | **uptrend** | 1,188 | **76.8%** | **74.3% – 79.1%** | **+3.4pp** |
| | range | 2,360 | 72.1% | 70.2% – 73.8% | −1.3pp |
| | downtrend | 1,742 | 72.8% | 70.7% – 74.8% | −0.6pp |
| below | *(pooled)* | 5,193 | 27.3% | 26.1% – 28.5% | |
| | uptrend | 1,103 | 29.6% | 26.9% – 32.3% | +2.3pp |
| | range | 2,205 | 25.9% | 24.1% – 27.8% | −1.4pp |
| | downtrend | 1,885 | 27.5% | 25.6% – 29.6% | +0.3pp |

**One cell separates**, and the direction is coherent: in an uptrend a touch
resolves upward more often *whichever side it arrived from*, +3.4pp from above
and +2.3pp from below. That is a main effect of trend on direction rather than
the interaction that was predicted, but it is not nothing.

### It survives correcting for six tests, by nothing at all

Six cells are being tested at 95%, so about one separation in three is expected
from chance alone. Holding the family-wise error at 5% needs a per-cell
interval of 99.15% (Šidák), which is z = 2.631 rather than 1.96:

| cell | 95% | corrected | pooled | separates |
|---|---|---|---|---|
| above / uptrend | 74.3% – 79.1% | **73.4% – 79.8%** | **73.4%** | *exactly on the line* |

The corrected lower bound and the pooled rate agree to the decimal shown. This
is the weakest form a positive result can take while still being one.

### And the threshold sweep is not consistent

Sweeping the fixed threshold, which the tercile labeller replaced:

| TREND | up | range | down | cells that separate |
|---|---|---|---|---|
| 0.100 | 24.0% | 51.6% | 24.4% | above/uptrend |
| 0.129 | 19.3% | 60.1% | 20.6% | none |
| 0.150 | 15.8% | 66.0% | 18.2% | none |
| 0.200 | 9.4% | 79.1% | 11.5% | below/uptrend |
| 0.250 | 6.6% | 88.6% | 4.8% | none |
| 0.300 | 3.7% | 94.7% | 1.6% | none |

A real effect should not appear at 0.10, vanish at 0.129 and 0.15, reappear on
the *other side* at 0.20, and vanish again. That pattern is what a marginal
effect looks like when the labelling moves under it.

## 4. It buys nothing a model can use

Walk-forward over 10,333 touches:

| features | accuracy | AUC |
|---|---|---|
| assume the level holds *(no model)* | 73.0% | — |
| side only | 73.0% | 0.736 |
| all nine features | 73.0% | 0.735 |
| all nine + cycle | 73.0% | **0.742** |
| side + cycle | 73.0% | 0.742 |

The AUC gain is real-looking and the accuracy gain is exactly zero — every
configuration ties the trivial rule to the tenth of a point. A model that ranks
slightly better while deciding identically has not changed any decision.

**And the gain does not survive being resampled by instrument.** Measured
directly, +0.0041 with a 95% interval of **−0.0008 to +0.0085**. It includes
zero.

| | AUC |
|---|---|
| side + eight features | 0.7352 |
| plus cycle | 0.7393 |
| gain | **+0.0041** (95%: −0.0008 to +0.0085) |

## 5. Where it helps and where it hurts

| feed | base | + cycle | gain | | feed | base | + cycle | gain |
|---|---|---|---|---|---|---|---|---|
| audusd | 0.747 | 0.764 | +0.017 | | nzdusd | 0.734 | 0.738 | +0.003 |
| eth | 0.749 | 0.763 | +0.014 | | eurusd | 0.718 | 0.722 | +0.003 |
| gbpusd | 0.742 | 0.753 | +0.012 | | btc | 0.753 | 0.755 | +0.002 |
| usdcad | 0.741 | 0.752 | +0.012 | | sol | 0.763 | 0.764 | +0.001 |
| usdjpy | 0.725 | 0.734 | +0.009 | | gold | 0.713 | 0.713 | −0.000 |
| usdchf | 0.732 | 0.735 | +0.003 | | us100 | 0.697 | 0.691 | −0.006 |
| | | | | | usdcnh | 0.715 | 0.707 | −0.008 |
| | | | | | **spx500** | 0.743 | 0.726 | **−0.017** |

Ten of fourteen improve, which is more consistent than chance would give. But
**the largest loss is spx500, and spx500 and us100 have the most cycles of any
instrument** — 9 and 11 against a median of 5. The two feeds with the most
opportunity to show the effect are the two it hurts most, and that is the
wrong way round for a real one.

## 6. What the sample actually is

The number that sizes every claim above is not 10,483.

| feed | touches | cycles | span | | feed | touches | cycles | span |
|---|---|---|---|---|---|---|---|---|
| gbpusd | 1,030 | 1 | 291d | | audusd | 733 | 7 | 290d |
| btc | 980 | 5 | 205d | | usdchf | 698 | 1 | 291d |
| spx500 | 894 | 9 | 308d | | nzdusd | 693 | 7 | 291d |
| us100 | 894 | 11 | 309d | | eth | 648 | 9 | 205d |
| eurusd | 864 | 3 | 290d | | sol | 626 | 3 | 206d |
| gold | 839 | 4 | 303d | | usdjpy | 559 | 3 | 291d |
| | | | | | usdcad | 532 | 5 | 290d |
| | | | | | usdcnh | 493 | 5 | 290d |
| **total** | **10,483** | **73** | | | | | | |

Better than the 26 this started with, and still the binding constraint. Two
feeds have a *single* cycle across 290 days — gbpusd and usdchf simply did not
change state — so they contribute a thousand touches and no information about
whether state matters.

**Count cycles, not touches.** 10,483 is the number that makes a 3.4-point
effect look decisive; 73 is the number that makes it marginal.

## Recommendations, in order

1. **Do not add cycle state to `Features` yet.** The deciding number is the
   AUC gain's interval, −0.0008 to +0.0085, which includes zero. Accuracy is
   flat to the tenth of a point across every configuration, so nothing decides
   differently even if the effect is real. Adding a feature on this would be
   adding noise with a plausible story attached.
2. **It is worth re-testing, which it was not before.** The honest change
   between the two readings of this document: one cell separates, both uptrend
   cells move the same way, ten of fourteen instruments improve. That is a
   direction rather than a result, and the thing that would settle it is more
   cycles — 73 is what makes a 3.4-point effect marginal.
3. **Keep the labeller.** Point-in-time, self-calibrating, cheap, and checked
   against a stated null. [turns.md](turns.md) reuses the same machinery.
4. **Do not reach for a shorter window to manufacture cycles.** Shortening it
   until the data shows variety is fitting the measure to the sample, which is
   the failure mode §6c was written to avoid — and the threshold sweep in §3
   shows how quickly that manufactures a separating cell.
5. **Two findings to carry elsewhere.** Cross-venue consensus is wrong at
   cycle scale, for a reason that will recur in any path-dependent measure. And
   a symmetric threshold cannot label a market's downside — which the backfill
   confirmed rather than fixed: downtrends went from 0.0% of touches to 1.6% at
   `TREND = 0.30`, still far below the 34.6% the tercile labeller finds.
