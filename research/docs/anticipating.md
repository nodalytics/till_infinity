# What a look-back can anticipate about a look-ahead

Run 2026-11-07 over **12 instruments and 3.3M 15m bars** — FX majors, metals and
BTC from 2015, Deriv synthetics from 2019 — with the broker's own per-bar
spread. **Nothing anticipates it.** No look-back feature separates a take-profit
from a stop-loss once volatility is conditioned on, at any look-back span, any
forward horizon or any target geometry, and the largest deviations from 0.5
anywhere in the study are in the **control arm**.

| question | answer |
| --- | --- |
| Is the label tradeable before features? | No. Expectancy is negative at every geometry; the best is **−0.056R** |
| Does RSI, ADX-like efficiency or momentum separate TP from SL? | No. Pooled and within-strata AUC both **0.495–0.509** |
| Does anything have a pooled reading? | Relative volatility, **0.520** — which collapses to **0.501** within strata |
| Does the real market beat its shuffled self? | **No, the reverse.** The walk deviates further from 0.5 than the market does |
| Does overlapping the forward windows inflate it? | **No**, ≤0.005 at a 4h horizon |

Two stages, kept apart on purpose: the label is a **counting** problem and the
features are an **explanation** problem, and mixing them is how both go wrong.

## Stage one: the label, and it is a cost problem first

A hypothetical BUY at each eligible bar, entered at **ask**, taken out against
**bid** — the spread paid twice, on the executable side. TP-first, SL-first, or
the window expires. Targets in ATR units rather than fixed pips, because +20
pips at 03:00 and at 14:00 are different trades when FX volatility runs 3x.
Where both barriers fall inside one bar the **stop** is taken: which came first
is unknowable at this resolution, and assuming the good one is how a backtest
invents money.

Real arm, trade-weighted across 12 instruments:

| target | 1:1, TP rate | 1:1, mean R | 2:1, TP rate | 2:1, mean R |
| --- | --- | --- | --- | --- |
| 0.5 x ATR14 | 0.399 | −0.203 | 0.277 | −0.165 |
| 1.0 x ATR14 | 0.453 | −0.094 | 0.306 | −0.083 |
| 2.0 x ATR14 | 0.471 | **−0.056** | 0.304 | −0.073 |

205,896 trades at a 4h horizon, 51,470 at 16h, 34,312 at 24h.

**Every TP rate is below its breakeven** — 0.399 against 0.50 at 1:1, 0.277
against 0.333 at 2:1. That is the spread, and it is why the *widest* target is
least bad: a fixed cost is a smaller share of a wider R. The same arithmetic in
reverse is why a shorter clock multiplies cost in
R.

**This bounds everything downstream.** A feature does not have to beat zero, it
has to beat −0.056R — and on 1:1 at a half-ATR target it has to find 10
percentage points of hit rate before a desk sees a cent.

## Stage two: the features, scored twice

Everything knowable at the entry bar's close and nothing after it: RSI, trend
efficiency (standing in for ADX, with no smoothing constants to get wrong),
ATR-normalised momentum, relative volatility, and the range-vs-close estimator
ratio — each at spans 14 and 50.

Scored **pooled and within volatility quintiles**, because AUC is free on a
volatility target: 0.805 on a
*constant-volatility* process, 0.525 within strata. The gap between the two
columns is the result. Neither column alone means anything.

Real arm:

| feature | pooled | within strata | gap |
| --- | --- | --- | --- |
| rsi14 / rsi50 | 0.495–0.508 | 0.496–0.509 | ~0.000 |
| eff14 / eff50 | 0.495–0.508 | 0.495–0.507 | +0.002 |
| mom14 / mom50 | 0.495–0.507 | 0.496–0.508 | +0.001 |
| rngratio14 / rngratio50 | 0.505–0.515 | 0.503–0.511 | +0.003 |
| **relvol14 / relvol50** | **0.517–0.520** | **0.501–0.507** | **+0.015 to +0.019** |

Only the volatility features read above noise pooled, and they are the ones
that collapse. **The free AUC on this label is worth about 0.02**, and it is
the whole of the apparent signal. The indicators the question was actually
about — RSI, ADX, momentum — are flat in both columns at every span and every
horizon.

## The control arm deviates further than the market

This was not the expected result and it is the strongest thing here.

The control is each instrument's own returns **block-shuffled** at 96 bars —
same step distribution, same bar geometry, same label machinery, volatility
clustering preserved. Shuffling bar by bar would destroy the clustering every
barrier label lives on and make the control easier than the thing.

Every one of the ten largest within-strata deviations from 0.5 is a **walk**
row:

| feature | arm | horizon | within | the other arm |
| --- | --- | --- | --- | --- |
| rngratio14 | walk | 4h | **0.438** | real 0.503 |
| rngratio50 | walk | 4h | **0.448** | real 0.503 |
| rngratio14 | walk | 16h | 0.458 | real 0.505 |
| relvol50 | walk | 4h | 0.463 | real 0.509 |
| relvol14 | walk | 4h | 0.470 | real 0.499 |

1,235,124 trades at the 4h horizon.

So on a shuffled walk the volatility features are **negatively** predictive of
TP-first, at 0.438–0.479, while on the real market they sit at 0.50. The market
is not showing a signal the walk lacks; the walk is showing a **geometric
artefact the market does not have**.

**Either arm alone gives a wrong answer, with opposite signs.** The real arm
alone reads as a clean null. The walk arm alone reads as a strong effect. This
is a sharper requirement than nulling an idea against a
walk usually implies: a control that
*tracks* the real arm says "geometry", and a control that deviates *further*
says the real series has actively less structure than its own shuffled returns.
Both are refutations. They are not the same refutation.

## Overlapping the windows costs nothing here

Overlapping outcome windows leak, and a
short skip rule with a long forward window once gave direction AUC 0.79 that
collapsed to 0.51. Measured rather than assumed, at a 4h horizon with entries
every bar against entries spaced by the horizon, 72 cells each side:

Spaced and overlapped differ by **≤0.005 on every feature and both arms**, and
usually by 0.000–0.001.

So the trap is real and it is not biting here. The difference from the case that
burned is the *ratio*: 96 overlapping entries per window there, 16 here, against
features that are flat to begin with. A flat feature cannot be inflated.

## What none of this establishes

* **One direction.** BUY only. The source brief is explicit that BUY and SELL
  must be analysed separately and this run does not, so a long/short asymmetry
  is untested.
* **Single features, no combinations.** Each column is one feature against the
  label. A pair that works where neither member does is not excluded — though
  only the sign survives into a weighted
  sum bounds how much a linear
  blend can add.
* **ATR targets only.** The fixed-pip arm the brief describes was designed in
  and not run. The comparison between the two *is* part of the dynamics and is
  still owed.
* **One stratifier.** Volatility quintiles. Session and spread quintiles are
  built into the harness and unreported.
* **The stratifier is a whole-sample quantile**, which is the one place that is
  legitimate: it cuts both arms of a lift measurement rather than feeding a
  per-bar prediction, and events and non-events share the bands. The same
  reading the look-ahead audit gave `searching.strata`.

## Six bugs, and why they are in the write-up

`focusparams.py` and `lookbacks.py` together produced six of mine in one
morning, four of them look-ahead, each with a confident number attached:

| symptom | cause |
| --- | --- |
| −1.19R, and the reward column changed nothing | zone edges inverted, stop inside the zone |
| +2.28R at 82% won | entry searched inside the anchor bar that defined the zone |
| +1.46R at 69% won | outcome resolved from the entry bar's own range |
| +1.46R at 66% won, walk arm correctly null | zone knowable at the changepoint, not at the firing bar |
| IndexError, on one feed of twelve | entry loop bounded by the real series' length, not the arm's |
| overlap table unreadable against its own report | kept the last cell written instead of weighting |

**The detector was correct from the first run** — validated against the shipped
`indicators.changepoint.Focus`, identical changepoint starts at three
thresholds. Everything that was wrong was the scaffolding that decides what a
number *means*: the trade loop, the knowability time, the array bounds, the
aggregation.

What caught them was never plausibility. It was an impossible invariant (a
reward that cannot change the outcome), a win rate far above breakeven, a
control arm that read correctly while the real one did not, and a crash. The
numbers were all plausible on the way past.

So both harnesses now carry their guards inline, and `focusparams.py` runs
**prefix invariance** before it sweeps anything — rebuild on `bars[:t]`, demand
every zone knowable by `t` be identical. The look-ahead audit found that no
harness in this repository had that check.
