# A zone's fill probability is distance, "certainty" is a zone inside the spread, and trading it loses more the surer it looks

Measured 2026-09-26 on the lab with [`zonefill.py`](../harness/zonefill.py): 21 series (12 FX
pairs, XAU, XAG, BTC, ETH, SOL, and four exact random walks from the Deriv synthetics as a
control), at 15m and 1h, about two million zone-bars per interval.

## The method, restated

A trader's method, described in quantum terms: price is a particle whose position is known only
as a probability until the wave collapses, so trade the outcome with the highest probability.

Concretely:
- for every liquidity zone near the price, estimate the probability that price fills it;
- the inputs are how hard price is moving, how directional the motion is (directional
  efficiency), how large the zone is, and how far away it is;
- they combine through a hand-weighted function;
- trade toward the zone with the highest probability - originally only when it is 1.

Mathematically this is a classical **first-passage probability** - will price touch a level
before time runs out - and with the hand weights replaced by fitted ones it is a logistic
regression. That is what was tested:
- **zones:** the nearest untaken 50-bar swing high above and swing low below, the resting
  liquidity;
- **size:** how many recent highs or lows cluster within a quarter of a normal move of the level;
- **label:** a wick touches the zone within 8 bars;
- **split:** fit on each series' first 60% by time, scored on the last 40%.

## The probability is distance, and physics already knew it

| | 15m AUC / Brier | 1h AUC / Brier |
| --- | --- | --- |
| **physics - distance alone, no fitting** (reflection principle: 2(1 - Phi(d / sigma sqrt H))) | **0.881** / 0.101 | **0.889** / 0.099 |
| distance and speed, fitted | 0.885 / 0.100 | 0.890 / 0.099 |
| all five inputs, fitted - the method | 0.884 / 0.099 | 0.890 / 0.099 |
| the random-walk synthetics, all five inputs | 0.914 | 0.914 |

A fill probability of about 0.88 AUC sounds like skill. It is geometry. A formula with no fitted
parameter gets 0.881; speed, push velocity, directional efficiency and zone size together add at
most 0.003. The random walks, where no input can carry information, score *higher*. Fitted weights
(15m): distance -1.88, efficiency +0.56, speed +0.54, velocity +0.06, size -0.04 - efficiency and
speed shade the probability, and do not change the ranking.

## "Certainty" is a zone inside the spread

Calibration of the full model on the test block, 15m (1h is the same within a point):

| predicted | n | realised |
| --- | ---: | ---: |
| 0.06 | 566,761 | 0.060 |
| 0.49 | 54,316 | 0.509 |
| 0.88 | 25,281 | 0.803 |
| 0.97 | 9,214 | 0.905 |
| **0.996** | 5,383 | **0.968** |

The model is honest in the middle and **overconfident exactly where the method trades**. A
probability of 1 is not reached, and the zones that come closest are the ones that are almost
touching:

| trade toward the most probable zone | median distance | tie | gross R | cost R | **net R**, stop 1x / 2x |
| --- | ---: | ---: | ---: | ---: | --- |
| every bar | 3.6 baseline moves | 4% | -0.05 | 0.21 | **-0.26 / -0.14** (15m), -0.16 / -0.09 (1h) |
| P >= 0.80 | 0.55 | 34% | -0.39 | 1.25 | **-1.64 / -0.89** (15m), -1.05 / -0.58 (1h) |
| P >= 0.95 | 0.25 | 63% | -0.65 | 2.53 | **-3.17 / -1.77** (15m), -2.13 / -1.28 (1h) |
| P >= 0.99 | 0.10 | 83% | -0.79 | 5.08 | **-5.87 / -3.26** (15m), -3.85 / -2.28 (1h) |

(15m rows; gross, cost and tie are for the 1x stop. "Tie" is the share of trades whose first
touching bar reaches both the zone and a stop placed at the same distance on the other side -
scored as the stop, since a bar does not say which came first.)

**The surer the method is, the worse it trades**, in every family and both halves of the test.
Three reasons, all of them structural:
1. **A near zone fills for free.** High probability means small distance, which means a small
   win. The stop has to sit somewhere, and a stop at the same distance is hit as often.
   [`barrier-geometry-is-irrelevant.md`](barrier-geometry-is-irrelevant.md) is the theorem: a
   target-and-stop trade earns the drift over its hold and nothing else. Choosing the most probable
   target buys a win rate, not an expectancy.
2. **The spread is larger than the move.** At P >= 0.95 the zone is a quarter of a normal bar's
   move away, and a round-trip spread costs 2.5 times that distance.
3. **One bar does both.** 63-83% of "certain" trades have a first bar that reaches the zone *and*
   the stop. Whichever came first inside the bar decides the trade, and bars cannot tell - so even
   gross, and even ignoring every tie, there is no margin to find.

## Every modern tool: all inputs, learned weights, multi-layer, stacking, attention

The method's author suggested that the limit is the manual weighting, and proposed the fixes:
use every input and trim later, learn the weights, go multi-layer, stack models, and use an
attention mechanism. [`zonefill2.py`](../harness/zonefill2.py) does all of it:
- **inputs:** 46 - the five zone inputs, the zone's side, and every bar feature in
  `crashlab.features`;
- **models:** logistic regression, gradient boosting, an MLP (64-32), a stack of the three
  under a logistic meta-model, and a transformer encoder attending over the last 32 bars;
- **targets:** two - whether the zone fills, and whether the trade toward it wins *net of
  spread*, which is the one that decides.

**Fill** (test AUC, real markets / random-walk control):

| | 15m | 1h |
| --- | --- | --- |
| physics, distance only, no fit | 0.872 / 0.915 | 0.883 / 0.915 |
| logistic, all inputs | 0.882 / 0.912 | 0.892 / 0.910 |
| gradient boosting | **0.888** / 0.913 | **0.894** / 0.913 |
| MLP | 0.883 / 0.911 | 0.891 / 0.911 |
| stack | 0.887 / 0.912 | 0.892 / 0.912 |
| attention | 0.882 / 0.912 | 0.893 / 0.910 |

Every learner adds 0.01-0.016 AUC over the formula with no parameters, and none reaches the
random walks. Trading the zone each one favours (top 20%, stop at the zone's distance): **-0.48 to
-0.50R at 15m and -0.30 to -0.32R at 1h, for every model including the formula** - within 0.02R
of each other, because they rank the same zones. Permutation importance, "trim the fat":
distance carries an AUC drop of 0.36-0.38; the next input, the hour of day, 0.004-0.007;
everything else less.

**Profit** - the target that pays:

| | 15m AUC real / control | 15m net R, top 20% | 1h AUC real / control | 1h net R, top 20% |
| --- | --- | --- | --- | --- |
| logistic | 0.530 / 0.519 | -0.023 | 0.523 / 0.522 | -0.015 |
| gradient boosting | **0.548** / 0.522 | -0.050 | 0.527 / 0.523 | -0.019 |
| MLP | 0.535 / 0.519 | -0.072 | 0.525 / 0.524 | -0.037 |
| stack | 0.547 / 0.521 | -0.063 | 0.529 / 0.524 | -0.024 |
| attention | 0.537 / 0.523 | -0.043 | 0.529 / 0.521 | -0.022 |

Trained on the right target, every model learns the one thing available - choose *far* zones,
where the spread is a small part of the move - and the loss shrinks from -0.3/-0.5R to -0.02 to
-0.07R. It never crosses zero: gross is -0.002 to +0.017R against a spread of 0.013-0.075R. And
the random walks score AUC 0.519-0.524 on the same target, so most of what these models "see" is
the cost structure, which exists on a random walk too. The attention model does no better than the
logistic regression; neither does the stack.

**The weights were not the limit.** Learned, stacked, deep or attentive, the fill probability is
distance, and the profit probability is a coin that the spread tips against you.

## What it would take

The only term that pays is **drift** - a signed forecast of where price goes, not whether it
touches something near. Directional efficiency is the right kind of input for that, which is why
it was the one variable here that ever cleared an error bar
([`a-theory-from-ohlc.md`](a-theory-from-ohlc.md)); its pre-registered replication failed. A
zone-fill probability, however well tuned, answers a question whose answer is already priced by
geometry.

The physics-first version of this question - estimate the drift and diffusion of price as a
stochastic process directly, and trade only the drift - is the natural next test.
