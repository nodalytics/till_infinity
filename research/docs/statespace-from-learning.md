# What `structures/learning` already solved, and statespace has not

Asked on 2026-10-11, while building `ranking.py`. The answer is embarrassing in
a useful way: the second step of the architecture I had just written **already
exists in this repository**, solved for a different target, with a self-check
mine did not have.

`structures/learning` is 4,798 lines of online models over level outcomes.
`structures/statespace` is a filter family over price. They do different things
and have barely looked at each other. Five things transfer, roughly in order of
how much they would change.

## 1. `calibration.Platt` is the mapping step, with a self-check

Built on 2026-09-05 for exactly the split `ranking.py` assumes: `breaking.Breaks`
scores **AUC 0.658** - a claim about *ranking* - and a log loss of **0.3624**
against **0.2493** for quoting the base rate. It ranks well and is calibrated
badly, and those are separate claims nothing had checked.

Three things to copy:

* **Monotone by construction, so it cannot change the ranking or the AUC.**
  `Mapping` needed the same property and got it late, as a fallback that
  straightens a degree-two fit whose turning point lands inside the anchor
  range. Platt has it for free because it is two parameters on the log-odds.
* **It publishes `improvement`, and it can be negative.** The calibrator scores
  *both* streams on the same observations - its own output and the raw one it
  was given - so the record can say whether calibrating helped. `Mapping` has
  no such number, and should: the comparison is against predicting the anchors'
  mean, which is one line and would have caught a dead mapping immediately.
* **Platt rather than isotonic, because isotonic wants more data per bin.**
  Thirty anchors cannot support a flexible map either, which is the same
  argument the paper makes for degree two and arrived at independently.

> Nothing consumes the calibrated number yet. It is published beside the raw one
> so the record can say which is better before either decides anything.

That is the house rule, and `ranking.py` follows it by not being in `members()`.

## 2. `online.py` has the discipline `Ranker` is missing

**Predict-then-update, enforced rather than requested.** `observe` returns the
prediction it made *before* learning, and the running score is built from those.
The filter family already does this - `drive()` reads `output()` before folding
the reading in - but `Ranker.fit` is batch, so a live version needs it. The
docstring's own summary is the reason:

> Every number this package has ever had to withdraw came from getting that
> wrong in one form or another, so it is enforced here rather than left to each
> caller.

**Welford standardisation inside the model.** Gradient descent on raw inputs
lets whichever feature is largest dominate the step. `Ranker` currently *assumes*
its features are `z`-like, which is true in the harness and a trap for anyone
else; it should standardise internally so it cannot be fed raw inputs.

And a leakage judgement worth importing verbatim: the standardiser updates from
observations it has **not** been given an answer for, because knowing the
distribution of the inputs is not knowing the outcome.

## 3. `decay.py` watches a model's error stream, which statespace cannot

`Paired` runs FOCuS over a member's **standardised innovations**, which is the
same idea restricted to models that have innovations. `decay.py` runs DDM and
EDDM over a stream of **wrong/right**, which works for any model at all -
including `ranking.py`, which has no innovation and currently has no way to say
it has stopped working.

Two refinements statespace should take:

* **Both detectors, because they fail at opposite things.** DDM is sharp on a
  step - a model that breaks. EDDM watches the *distance between* errors, which
  catches a gradual slide, and gradual is what decay looks like here: a model
  whose edge erodes over a month never has a bad enough day to trip DDM.
* **The warning zone before the alarm**, which arrives earlier and costs nothing
  to observe.

**And the finding that should embarrass `focus.py`:** run against a
**stationary** error stream, where the right number of alarms is zero, both
detectors fire. `focus.py` says of its own threshold that it is *"not
calibrated, and the right way to set it is the realised false-alarm rate on a
series known to have no changes, which the Deriv synthetics are the closest
thing to"* - and then does not do it. `decay.py` did the equivalent and found
the answer was not zero. That measurement is a few hours and it is the
difference between a detector and a decoration.

## 4. `baseline.Bench` scores against controls continuously, including no model

Every touch goes to all three models *and* to `up_rate` - **no model at all**,
the level's own record read straight off the feature, as the floor everything
must clear. The scoring is continuous rather than a study somebody ran once.

statespace has neither half. Members accumulate `loglike`, but nothing scores
them side by side against the random walk on every reading - `RandomWalk` lives
in a research harness rather than the library, which is backwards given it is
the null the whole family is judged against. And the magnitude work has a
no-model floor that has beaten everything tried against it, the trailing
standard deviation, which for the same reason belongs in the library as a named
arm rather than re-implemented in four harnesses.

## 5. `regimes.py` on asserted boundaries, which statespace is full of

> An asserted boundary is a free parameter that never gets measured.

statespace currently asserts `FRESH_HOURS = 6.0`, `THRESHOLD = 10.0`,
`LIVES = 3.0`, `WARMUP = 20` and `margin = 0.1`. Each is defended in a comment
and none is fitted. `regimes.py` makes the same complaint about named sessions
and hand-cut volatility thresholds, and its answer - put the boundary where the
data separates, online, so it moves when the market does - applies to at least
the first two.

Two more rules from it:

* **Ordered labels, not cluster ids.** "A k-means cluster id is a memory
  address, not a meaning": the cluster called 2 today may be 0 after a restart,
  so a per-regime scoreboard needs labels ordered by something physical. The
  harness here uses volatility terciles, which are ordered by construction; any
  clustering added later must earn that.
* **Size the effect before conditioning on it.** Regime separated real outcomes
  over 49,338 touches and was still **an order of magnitude smaller than the
  stop and the entry**. The informatory-pairs result says volatility regime is
  the condition worth having; this says to find out how much it is worth before
  building around it.

## What to do first

1. **The stationary-stream false-alarm rate for `Paired`** (§3). `focus.py`
   names the measurement and skips it, `decay.py` ran the equivalent and found
   the answer was not zero, and the Deriv synthetics are sitting there.
2. **`improvement` on `Mapping`** (§1). One line, and it is the difference
   between a calibration step and an assumption.
3. **`RandomWalk` and the trailing standard deviation into the library** (§4),
   so the nulls are code the family is scored against rather than something each
   harness rebuilds.
