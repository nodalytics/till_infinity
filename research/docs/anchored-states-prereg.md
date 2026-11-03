# Anchored states and the next move's size: pre-registration

**Written 2026-11-03, before any cell of this study was computed.** Not to be
edited after it is committed; any departure goes in a "Deviations" section of
the results document with the reason.

## Why this replaces the geometric framing

The user's reframing, and it names a defect rather than a preference:

> we need to reframe our geometric approach now we are using something that
> can't see into the future, what we want to be able to do is to
> probabilistically react to some high probability market states, that might
> move in a certain or probabilistic direction

**A geometric pattern is only identifiable once it completes**, so the shape
exists only after the move it describes. `trend.pivots` is honest about this -
it confirms a pivot `reach` bars later, which is why `L50` means "confirmed 51
bars on" - and a Fibonacci level needs both ends of a leg that has therefore
already finished. The measurement side found the same thing from the other
direction: `a-return-rate-is-geometry` and
`the-origin-picks-a-distance-not-a-probability` both say the 82% was a target
hit rate rather than an entry signal.

So the question changes from *what shape is this* to **what state is this, and
what is the distribution of the next move given it**. A state is a reading of
what has already printed, so it is causal by construction.

## What is being claimed, and what is not

**Primary claim.** The conditional distribution of the next move's
**magnitude** differs across anchored states by more than the null arms
produce, within volatility strata, on more than one instrument.

**Secondary claim, and expected to fail.** Direction differs within a state -
tested only as an *interaction* with the state, never as a standalone gate.

The asymmetry between the two is measured, not assumed.
`relationships-are-contemporaneous`: volatility and tails are huge and every
lagged measure is null. `direction-is-closed-not-just-null`: the direction
gate finds a **planted** drift at z +2.90 and earns 2% of a spread. So a
direction result has to clear the interaction null, not merely zero, and will
be reported as a failure of the secondary claim unless it does.

**What this study does not claim.** That any of it is tradable. Magnitude is
what sizing and stop placement consume, and a conditional dispersion finding
is an input to those rather than a signal. No gate ships from this document.

## The anchoring rule, which is the design and the main risk

**A state must be pinned to something external, never fitted.**
`definitions-cannot-be-states` is the recorded failure: a mixture centre left
as a free state **collapses onto the data**, and three members needed anchors
to stay distinct. A freely-fitted "high probability state" will find itself in
any series, including every null arm, and the study would then be measuring
its own fitting procedure.

So every state below is defined by a quantity this desk already publishes, with
its parameters frozen here:

| anchor | definition | why it is external |
|---|---|---|
| `session` | `pivots.session_of` - sydney / tokyo / london / newyork | a clock, conventional boundaries, no fit |
| `through` | `Pivots.through` in thirds: early / middle / late in the period | derived from the session cut, no fit |
| `compression` | quintiles of a causal EWMA of bar range (`drive-q-from-the-range`) | the strata this desk already conditions on |
| `pivot_room` | `Pivots.room` in thirds: near a level, mid, far | `Pivots` has no parameters at all |
| `mood_vol` | `FearGreed.volatile` in thirds | a bars-only reading, equal weights, not fitted |
| `mood_dir` | `FearGreed.directional` in thirds | the same, and the half measured closed |

`mood_dir` is included **so the secondary claim has a state built from the
quantity most likely to carry it**, not because it is expected to work.

**Every state must be computable from bars closed at or before the decision
bar.** Where more than one interval is involved, `strategies.timeframes
.Frames.ready` is the mechanism: it drops any frame whose last close is after
the decision moment, so a forming higher bar cannot be read. A state that
cannot be produced that way is excluded from this study rather than
approximated.

## The outcome

**`size`**: the absolute log move from the decision bar's close to the close
`H` bars later, in volatility units of the decision bar.

**`signed`**: the same with its sign, for the secondary claim only.

`H` is **20 bars at 1d and 48 at 15m and 1h**, matching `level-bounce.md` so
the two are comparable. Fixed here; not swept.

**Outcome windows are de-overlapped**: one outcome per non-overlapping block
of `H` bars per instrument. `overlapping-outcome-windows-leak` is the
refutation - a short skip rule with a long forward window gave a direction AUC
of **0.79 that collapsed to 0.51**, and the tell was the placebo and shuffled
arms tracking it.

## The nulls

Four arms, every one through the same state detector over the same bar
geometry, reusing `level_shield`'s machinery rather than new code:

| arm | keeps | removes |
|---|---|---|
| `garch-bars` | volatility clustering, fat tails, bar wickiness | path structure |
| `walk-geometry` | bar wickiness, the step distribution | path structure and clustering |
| `bar-shuffle` | each bar's own shape, the marginal step distribution | all memory |
| `duty-twin` | the state's firing rate and times, by construction | any association between state and outcome |

`garch-bars` is required because `walk-geometry` resamples steps i.i.d. and so
has none of this market's clustering - and clustering is the mechanical route
by which a state defined on recent range predicts a forward excursion.

**Sixteen draws per arm, minimum.** Measured this session: four draws an arm
makes a hardest-of-N test **anti-conservative**, because the maximum of four
understates the arm's own tail and the bias runs towards passing. `audusd`'s
speed gap read **+0.093** over its hardest-of-20 and **-0.037** over its
hardest-of-80, and that was the one substantive path finding in that study.

**Seeds are `crc32` or `blake2b` over the arm's parts, never `hash()`.** Three
separate harnesses carried the same bug this session: the builtin hash of a
tuple containing a string is salted per process, so surrogate draws did not
reproduce between runs. In every case the real arm was unaffected and
verifiably bit-identical, and in one the tell was a hardest-of-N *falling* as
draws rose, which cannot otherwise happen.

**An independent placebo pair.** Two instruments excluded from every state
construction, carried in every table. `carry-an-independent-placebo-pair`
caught two leaks in one run, and this session it caught the fear-greed study
reading each instrument's own recent direction back to itself through a basket
index - a circularity that one flat placebo diagnosed and no amount of
surrogate arms would have.

## Stratification, and the trap it exists for

Every reading is reported **within quintiles of trailing compression** as well
as pooled, and the stratified figure is the one that decides.

**`AUC-is-free-on-volatility-targets` is why this is not optional**: an AUC of
**0.805** was measured on a constant-volatility process where the true answer
is 0.5, falling to **0.525 within strata**, and incumbent features alone read
0.74-0.78. A dispersion target is exactly that kind of target. **An
unstratified AUC on `size` is not a result and will not be reported as one.**

The quintile edges are full-sample. That makes them a conditioning variable
rather than a predictor, which is acceptable and is declared here rather than
discovered later.

## Pass rule, fixed before the run

The primary claim passes only if **all** of:

1. The state's effect on `size` exceeds its **hardest** null arm, within
   strata, on at least **3 of the instruments carried**, and on **both** of two
   non-overlapping halves of the history.
2. The effect survives Benjamini-Hochberg across every cell in the study.
3. The **placebo pair does not pass** under the same rule.
4. The **duty-cycle twin does not pass** - otherwise the finding is the firing
   rate rather than the state.
5. The power sweep shows the test could have seen an effect of the measured
   size. A null without this is not reported as a null.

Anything else is a fail. Passing all five is "worth a fresh-data test", not an
edge: DSR >= 0.95 over the true trial count is still required before that word
is used.

The secondary claim passes only if the interaction clears the same five **and**
the state's own direction effect is larger than the same state's effect on a
`signed` outcome with the state's sign randomised.

## Trial count, stated now

6 anchors x 3-4 state levels x 3 intervals x 14 instruments, plus the
secondary claim's cells, is of order **1,500 cells**. The deflation carries
that number plus the prior searching this desk has already done on direction
and on levels, which is substantial and is why `discovery.gate_from` takes
`prior_trials` at all. A gate counting only this sweep understates the search
that produced any candidate.

## What would refute it, and what would make it uninteresting

**Refuted** if the stratified effect sits inside the hardest null on most
instruments - which is the outcome the three studies merged in #286 all
reached, and the honest prior here.

**Uninteresting even if it passes** in two specific ways, both of which must
be checked and reported:

- If the effect is monotone in the compression quintile itself, the state is
  restating the volatility estimate and `topology-restates-volatility` already
  covers it: levels, ranges and shapes all read null once volatility is
  stratified.
- If the magnitude of the effect is smaller than the cost of acting on it. The
  desk's own measured limit is `costs.MAX_SPREAD_RISK_FRACTION` at **0.16 of
  risk**, and a dispersion edge that moves a stop distance by less than that is
  not reachable. The `stop-anchor` study is the cautionary case: its anchor
  could only move a 2-unit stop by **1.4 to 5.3%**, which settled it before any
  null was consulted.

## Costs and data

**Primary reading is gross and labelled so.** Only `eurusd`, `gbpusd`, `gold`,
`btc` (DERIV), `us100` (FOREXCOM) and `spx500` (PEPPERSTONE) have enough
recorded quotes to measure a median spread per venue; the other feeds in the
store carry two or fewer. **No spread is invented for any feed**, and
`us100`/`spx500` are not the venue the live desk trades, which is stated
wherever they appear.

1d gives 4,980-5,009 bars over **19.2-19.9 years** on eight FX feeds and gold,
which is where the power is. 15m gives 5,135 bars over 76 days. 1h gives
0.8-0.9 years on FX and gold, and 2.87 on the two indices - so 1h is reported
separately rather than pooled, and a result at one interval is **a different
rule** from the same logic at another, named separately.

**Any synthetic cross is excluded.** Measured this session: a constructed
cross's range over |close change| reads **4.03 against a 2.300-2.439 band on
every real instrument**, about 1.7x too wide, because the legs sit on opposite
sides of the dollar and their highs never co-occurred. `levels.chains` finds
**four displacement legs in nineteen years instead of eighty-three**. So the
range-based volatility unit this study's strata depend on is invalid there.

## Metrics

Mean and dispersion of `size` with a **day-block bootstrap** CI, block at least
`max(H, bars per day)`. Where anything is expressed as a trade: mean R with a
day-block CI, profit factor, and DSR over the trial count - **win rate is
descriptive and labelled so**, per the standing correction that a poor win rate
with a larger payoff is not a failure. Each arm's per-trade sd and the sample
its own CI implies are reported beside its mean, because a low-win-rate arm has
higher variance and therefore needs *more* evidence for the same confidence,
not the same.

**Nothing is judged against an analytic `1/(1+N)`.** A barrier race read off
bar extremes departs from the closed form by -0.25 to +0.12R, monotone in
(stop - target), and every surrogate does it three to seven times harder. Any
race in this study is compared to the same race on matched surrogates.

## Compute

One invocation, output directory configurable, worker count a flag. **Run on
the 64-core box, not locally.** This session's lesson, and it was expensive:
three studies competed on an 8-core machine at load 25-31, one of them never
completed its panel at all, and a 406 s/leg timing turned out to be a
measurement of contention rather than of the job. The same panels ran in **91
and 96 seconds** on the lab.
