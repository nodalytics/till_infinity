# An online ZMA can say "there is nothing here". The fixed rule cannot.

[`zma.md`](zma.md) left the indicator in an awkward place: a **working**
mean-reversion detector - AUC 0.62 on an Ornstein-Uhlenbeck control, scaling
with the reversion speed - pointed at processes that do not revert, where it
scores 0.49 to 0.52 and, on Boom and Crash, 0.376 to 0.461. And it fires
anyway, on roughly 15% of bars everywhere, because its thresholds are
percentiles of its own history and a percentile always has something above it.

That last sentence is the defect, and it is not a defect of the detector. **It
is a defect of a fixed rule**: the rule has no way to represent "there is
nothing here". This asks whether an online learner does.

[`harness/zmaonline.py`](harness/zmaonline.py) is the study.

## How it is scored, which is most of the work

**Prequential.** Every prediction is made from a model that has not seen the bar
it is predicting; the bar updates the model only afterwards. Test, then train,
one bar at a time. Any other order scores a model on its own training data, and
an online learner is *especially* easy to flatter this way because it never has
a train/test split that somebody could forget to make.

**Against saying nothing, not against 0.5.** The baseline is the running base
rate of the series itself, which on a drifting instrument is not a coin. The
headline number is therefore **information gain**: the mean log-loss of the
always-base-rate predictor minus the model's own, in milli-nats a bar. Zero is
"added nothing". **Negative is worse than silence** - which the Boom and Crash
arms produce, and which is the evidence that this harness can return a no.

## The four arms

| arm | what it is | what it is for |
| --- | --- | --- |
| `fixed` | the shipped rule: `agrees` as a direction | the thing to beat |
| `logistic` | online logistic regression on ZMA's own readings, one SGD step a bar | the minimal conversion - same inputs, learned mapping |
| `hedge` | exponential weights over ZMA at periods 20/50/100/200 **plus a null expert that always predicts the base rate** | the null expert's weight *is* the answer |
| `abstain` | the logistic model, betting only when it is more than 0.02 from the base rate | does shrinkage do the abstaining by itself? |

The null expert is the design. It is not a control bolted on beside the
mixture - it is *in* the mixture, competing for weight, so "how much signal is
here" becomes a number the algorithm reports rather than a judgement somebody
makes about its output.

## What it measured

40,000 bars an arm, 60,000 for the switching series.

| arm | z AUC | flag hit | top-z hit | fixed | logistic | hedge | **null wt** | lift |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OU theta=0.02 | 0.523 | 0.504 | 0.562 | -0.04 | -3.91 | +0.28 | **0.952** | +0.003 |
| OU theta=0.05 | 0.550 | 0.578 | 0.603 | +0.19 | -1.56 | +1.68 | **0.844** | +0.020 |
| **OU theta=0.15** | **0.613** | 0.646 | **0.724** | +0.62 | +14.48 | **+18.69** | **0.092** | **+0.082** |
| its own shuffle | 0.498 | 0.487 | 0.489 | -0.05 | -4.07 | -0.22 | **0.960** | +0.001 |
| switch OU/GBM/OU | 0.567 | 0.593 | 0.588 | +0.29 | +6.14 | +9.57 | 0.007 | +0.057 |
| volatility 25 | 0.497 | 0.484 | 0.482 | -0.06 | -4.14 | -0.29 | **0.880** | +0.005 |
| volatility 75 | 0.501 | 0.437 | 0.477 | -0.16 | -4.72 | -0.27 | **0.969** | -0.003 |
| step index | 0.499 | 0.533 | 0.484 | +0.02 | -4.61 | -0.28 | **0.913** | -0.002 |
| **boom 500** | 0.468 | **0.119** | 0.985 | -4.98 | -5.32 | -0.58 | **0.998** | -0.997 |
| **crash 500** | 0.429 | **0.164** | 1.000 | -4.55 | -5.79 | -0.47 | **0.998** | -0.993 |
| jump 25 | 0.499 | 0.513 | 0.547 | -0.01 | -4.68 | -0.33 | **0.856** | +0.001 |

Gains are milli-nats a bar. `lift` is the bet hit rate minus always guessing the
common direction on the same bars, because a raw hit rate on Boom and Crash
measures the drift - the first run of this harness reported 0.003 there, which
reads as a catastrophic detector and is mostly a base rate.

### The null weight is the result

Read the `null wt` column down the OU arms: **0.952, 0.844, 0.092**. The
mixture's weight on the expert that says nothing falls monotonically as the
reversion speed rises. On a shuffle of the best OU arm it returns to 0.960. On
every instrument family this desk trades it sits between 0.856 and 0.998.

That is the property the fixed rule cannot have. The rule fires at the same rate
on all eleven arms; the mixture puts 91% of its weight on "no opinion" where
there is nothing and 91% on the detector where there is something, **and it did
not have to be told which was which.**

### Mixtures degrade gracefully. Gradient descent does not.

The worst the mixture does on any null arm is **-0.58** milli-nats. The worst
the logistic learner does is **-5.79**, ten times as bad, and it is negative on
every single null arm. Both are online learners on the same features; the
difference is that a mixture's worst case is bounded by its best expert - here,
by an expert that predicts the base rate - and SGD's is not bounded by anything.

**This is the practical argument for the mixture over the obvious answer.** The
obvious conversion of a rule into a learner is to regress on its features, and
it is the wrong one: it pays for its wins on the OU control (+14.48) with a
uniform loss everywhere else.

### Online learning did not create signal anywhere, which is the point

Every null arm is at or below zero for every learner. Neither the regression nor
the mixture found anything in geometric Brownian motion, in a Step lattice, or
in a shuffle. A harness that cannot come back empty proves nothing when it comes
back full, and this one comes back empty eight times out of eleven.

## The arm that decides it: reversion that stops and starts

A fixed rule adapts to *scale* - that is what the percentiles buy - but it
cannot adapt to whether reversion exists at all. So the series that settles this
is OU at `theta = 0.15` for 20,000 bars, geometric Brownian motion for 20,000,
then OU again. One series, one model, read by segment:

| segment | bets | null weight |
| --- | --- | --- |
| reverting | 84.7% | 0.127 |
| **random walk** | 63.8% | **0.922** |
| reverting again | 84.5% | **0.138** |

It goes quiet when reversion stops and **it comes back when reversion returns**.
The recovery is the harder half and it is not free: see below.

## Plain exponential weights are a one-way door

The first run of this study ended the switching series at `null = 1.000` while
sitting in a *reverting* segment. Not a coding error - the algorithm working as
specified. Multiplicative weights underflow to exactly zero, and an expert at
zero can never be revived by multiplication however well it would now do. The
detector experts were killed during the random walk in the middle and there was
no arithmetic that could bring them back.

The fix is **fixed share** (Herbster-Warmuth): mix `alpha = 0.001` of the weight
back toward uniform every bar, flooring every expert at `alpha/N`. That buys a
regret bound against the best *sequence* of experts rather than the best single
one, which is the right guarantee when the question is explicitly about a
process that stops and starts. The 0.138 in the table above is what it bought.

**This generalises past ZMA.** Any online component on this desk that weights
alternatives multiplicatively has the same trapdoor, and the same one-line fix.

## The threshold throws away about eight points

`agrees` is a flag, and a flag's AUC is not comparable with a continuous score's
- it is zero on most bars, so the ranking is mostly ties and the AUC is pinned
near 0.5 by construction whatever the flag knows. The fair question is: on the
bars it fires, is it right more often than the raw z-score is on **the same
number** of its own most extreme bars?

| control | flag hit | continuous z, same bet count |
| --- | --- | --- |
| OU theta=0.02 | 0.504 | **0.562** |
| OU theta=0.05 | 0.578 | **0.603** |
| OU theta=0.15 | 0.646 | **0.724** |

Same series, same number of bets, and the continuous reading wins every time by
2.5 to 7.8 points. **The percentile threshold is a loss, not a filter.** If the
z-score is ever allowed to influence a decision it should be as a number and not
as a state.

## On Boom and Crash the flag is an anti-signal, and there is a mechanism

`flag hit` on boom is **0.119** and on crash **0.164** - not noise, an
inversion. `zma.md` measured the same thing (0.376 to 0.461) and called it
reliably wrong; this says why.

Boom drifts slowly down and spikes up. The long drift leaves the z-score
persistently low - `oversold`. The spike is what finally turns the slope
positive. So `agrees` - oversold *and* rising - fires precisely on the bar after
the one up-move, and calls for more up, at the moment the drift resumes. **The
agreement condition is a detector of the spike having already happened.**

The `top-z hit` of 0.985 and 1.000 in those rows is the mirror of it and is not
a signal either: it is the drift, since betting against an extreme z on a series
that goes one way 499 bars in 500 is betting the drift. That is why `lift` is
the column to read there, and `lift` is -0.997.

**This has a direct consequence for the desk.** `trading.strategies.scalper`'s
`zma_gate` refuses a call the flag leans against. On the spike families the flag
leans the wrong way, so the gate would veto the *correct* side. See below.

## The shipped period is not the best period

The mixture's final weights on the OU control, by ZMA period:

    20: 0.024    50: 0.039    100: 0.217    200: 0.628    null: 0.092

Production runs **50**, which the mixture gives 0.039. It wants 200.

This is on an OU process and not on any instrument this desk trades, where
nothing works at any period, so it is not an instruction to change the constant.
It is an argument for the mixture being the shipped object rather than one
period being the shipped object: the best period is a property of the process,
and the desk does not know which process it is looking at.

### A bug this found, which could not have been found any other way

The first mixture run produced four experts with **exactly identical
predictions** and therefore an exactly uniform weight vector, which is not a
result a mixture can reach by accident. `Zma.period` and `Zma.lookback` were
decorative: a `dataclasses.field(default_factory=lambda: deque(maxlen=PERIOD))`
is evaluated with no access to the instance, so it captured the module constant
and every `Zma` kept fifty prices however it was constructed. `Zma(period=200)`
built, reported `period == 200`, and behaved like the default.

Nothing shipped was wrong - production only ever builds the default - but no
study of whether some other window is better could have been run. Fixed in
`__post_init__`, with tests.

## What to do with this

**1. If the z-score is ever given a vote, give it the number and not the
state.** The threshold costs 2.5 to 7.8 points at equal bet count. `zma_z` and
`zma_strong` are both published on every call; `zma_agrees` is the lossy one.

**2. Gate the veto on the feed's own scored record, not on a family list.**
`Zma.accuracy` already scores every call this desk makes, per feed and
timeframe, and `till-infinity structures zma` reports it worst-first. A veto
that fires only where that record is above a coin is self-limiting on exactly
the instruments where the flag is an anti-signal, and it needs nobody to
maintain a list of which families spike.

**3. The mixture is the shipped shape, if any of this ships.** It bounds its own
worst case, it reports its own confidence as the null weight, and it recovers
from a regime that kills a plain weighting. What it does *not* do is find
anything in a random walk - and this desk's synthetics are random walks, with
`H = 0.50` measured in [`generators.md`](generators.md).

**4. The place to point it is still a spread.** `zma.md` measured AUC 0.67 to
0.73 on constructed cross-venue spreads. Everything here says the machinery is
sound and the input is wrong, which is the same conclusion arrived at twice by
different routes.

## What this is and is not

**Simulated.** These are each family's documented mechanics - `grounding.md`'s
`p = 0.499734` for Step, `families.md`'s memoryless spike hazard for Boom and
Crash, the 1.322x diffusive multiple for Jump - and not the feeds. A generator
that differs from its documentation in a way nobody has checked would not appear
here. The harness runs unchanged on cached bars; that is the version to believe.

**One seed.** The OU ladder is monotone in `theta` across three arms and the
null arms agree with each other and with `zma.md`'s independent run, which is
the reason to believe the ordering. The individual figures are not tight.

**Nothing here is a profit measurement.** Information gain in nats is not money,
and `asking.md` lists the gap between the two as outstanding. A learner that
adds 18.69 milli-nats a bar on a process this desk cannot trade has demonstrated
a mechanism and not an edge.
