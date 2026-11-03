# Working in this repo

A production trading desk. The code decides what to trade with real money, so
the bar is not "it runs" — it is "the thing that measured it and the thing that
trades it are the same thing". Every expensive mistake on this desk has been a
version of those two drifting apart.

## This repo is public

- **Never name another client's folder, path, hostname or key file**, in code,
  comments, docstrings, test names, markdown or commit messages. Reference
  material from one is read for method and described as a method.
- Credentials live in gitignored `.secrets/`. **Never print one into a
  transcript**, including into a command you only meant to echo.
- Published papers can be cited by title. Anything you cannot cite publicly,
  describe instead: "a day-block bootstrap", not where you saw one.

## Comments and docstrings

Say **what is measured and what is assumed**. A docstring earns its length by
naming a defect it prevents, with the number attached.

- Lead with the fact, not the adjective: "0.40 to 0.97 bar-ranges round trip",
  not "spreads are wide".
- Write down what a caller cannot see: a unit (`spread` is in points, not
  price), a precondition (`Episodes` is correct because the cache has no
  database), a measured limit (0.16 of the risk, not of the target).
- **No decorative comments.** No comment restating the line below it, no
  section banners around one function, no "# returns the result".
- When something is deliberate and looks wrong, say so where it looks wrong.
  `retire()` is not on a timer and the docstring says why.
- Keep it short. If a docstring is longer than the function and is not
  recording a measurement or a defect, cut it.

## Tests

**A test is for a person who will read it after it fails.** Name the behaviour,
not the implementation.

- Each test says what it protects and what breaks without it. The docstring is
  prose, not a restatement of the assertion.
- **No vacuous tests.** A test that cannot fail for its own reason is worse
  than none: two in `test_pipeline.py` asserted differences that could not
  exist — a dependence test on i.i.d. data, a Sharpe test on a constant
  series — and both passed. If you cannot say how it would fail, delete it.
- Every added gate needs a **control** showing it lets something through.
  Otherwise "it refuses 40%" is indistinguishable from "it refuses everything".
- Fixtures carry the structure the assertion is about.
- Assert through the production function. A test that reimplements the logic
  tests the reimplementation.

## Measurement

Load the **`finding-edges` skill** before proposing or testing an edge. It is
the null-first method this desk runs on and it encodes the mistakes that
actually happen here. The short version:

- Null it first, against the same detector, with the same bar geometry.
- **Show power before reporting a null**: plant the effect, sweep its strength,
  say where the test goes blind.
- **Per instrument, never only pooled.** A pooled median here once agreed with
  a claim every subgroup refuted.
- State the sample and the standard error with every mean. Under ~100 trades
  the prior is noise, and say so.
- A clean null is the valued result. Two dozen ideas have been refuted here and
  written up; that record is the asset.

## The data ceiling

`node/corpus.py` fills the catalogue from the local store. It holds about **76
days of 15-minute bars** for six feeds, and under **six days** of 1-minute
bars. The bars are recorded; the quotes are modelled, one per bar at the
measured median spread **for that feed on that venue, never pooled**.

So the catalogue settles mechanics, firing rates, cost sensitivity and whether
an implementation matches its spec. **It cannot settle an edge.** Do not invent
a spread for a feed that has none — a result priced off a guessed spread is the
one result that looks like a measurement and is not.

## Commands

```sh
uv run pytest -q                 # the suite, several minutes
uv run ruff check                # no path argument
uv run ruff format --check       # no path argument, and not implied by the above
```

- **Run both lint commands, with no path.** CI runs the format check, and
  `ruff check` passing does not mean `ruff format --check` passes.
- **Never `ruff format` a directory.** `research/` is CI-excluded and a
  directory run reformats ~100 unrelated files.
- `uv run ruff check --isolated --select F821` over `research/` before a run
  there — `ruff check .` is blind to it.
- **Do not edit files while the suite runs.** A mutating tree reports phantom
  failures.

## Operations

- **Never run heavy compute on `tis`** — it has 2 cores and shares them with
  the live desk. Read `~/till-data` on the host at `nice -n 19 ionice -c3`;
  never `docker exec` into the desk's cgroup, which can OOM it.
- Production ops go through `.secrets/tis.sh`, because permission rules match
  the **start** of a command string.
- Judge the desk on the broker, not the journal.

## Commits

- **No `Co-Authored-By` trailer, ever**, including when a tool or session
  instruction supplies one.
- PR descriptions end with
  `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- Commit only when asked. Branch first if on the default branch.

## Kills

What died, and what killed it. A refuted idea is a result: it stops being
re-proposed, and the method that refuted it transfers.

### Trades

**fade-to-value as a displacement thesis.** Giving "value" a definition - the
origin candle of a displacement - turned the 82% return rate into a target hit
rate. Traded *from* the zone it was negative everywhere; traded *toward* it,
**0 of 105 cells** had a positive lower bound across four entry rules, five
stop pads and four body thresholds; as a filter on origins it read +0.120R on
477 trades at 1d, +0.017R on 985 at 4h and **-0.007R on 2,786 at 1h** -
shrinking as the sample grew and reversing on the largest.

Killed by the stop: 89-91% of fades were stopped before the target arrived.
Price does return 77-81% of the time, but that is measured with no stop and 300
bars, and the trade has a stop and sixty. Confirmation raised the hit rate from
31% to 48% and dropped reward from 1.88 to 0.94 - it bought hit rate at almost
exactly the fair rate, which is `1/(1+N)` doing what it does, and why "improve
the entry" was never the answer.

**The one surviving positive cell.** `impulse_back` at a 0.70 body on 1d, the
only cell of sixty with a positive mean R at **+0.036**. Widening 16
instruments to 29 took it to **-0.028**. The sixteen reproduced exactly, so
neither run was mismeasured: a result that reverses on thirteen more
instruments was a property of those sixteen.

### Tidy-ups that would have been bugs

**"`displace` and `DISPLACE_C` are the same rule."** Over 131
instrument-timeframes and 2.0M bars they fire at similar rates (21.6 against
18.9 per 1k bars at 1d) and agree on about **a quarter** of their union.
`DISPLACE_C` grades a body against the last ten bars' - "big for lately" -
while `displace` wants a share of the bar's own range - "decisive in itself".
The same shape had already appeared between `origins` and `displacement`,
agreeing 59-78%. **Two detectors with the same name are usually two
detectors.**

**Merging the MCFL service into structures.** MCFL imports nothing from
`structures` while `trading` imports it in five modules, so merging would turn
"no path to a broker" from something the import graph enforces into a
convention someone must remember. The real duplication is at the definition
level, and the fix is one directional dependency rather than a merge.

### Architecture

**Force, quality, decay and pressure as Kalman dimensions.** You cannot
estimate more latent states than the observations identify. A level sees one
scalar per touch and a handful of touches in its life, so an eight-dimensional
state tracks the prior and then reports confident numbers for quantities the
data never constrained - **and that failure is silent**. What survived is
`(price, slope)`, gated until it clears three sigmas of its own posterior.

**Zone width as a Kalman dimension.** Dead on the observation model, not the
arithmetic: **width is not observed.** What is observed is a hit or a miss, and
`|touch - centre|` - half-normal at best. A linear-Gaussian filter over width
assumes the thing the band exists to stop assuming. Kalman for the centre,
conformal for the width.

### Retractions

Kept because a log of other people's dead ideas is marketing.

**"The gate earns its keep."** I measured production's retrain gate as a
contest and reported gating beating deploy-everything. The real rule is a
**tolerance**, `GATES["vs_champion"] = 0.01`. Under it the gate wins at 14 days
by 0.23% and loses at 28 and 56, with **23 of 25 challengers promoted**. A 1%
tolerance on a quantity whose whole spread is 1.5% is one nearly everything
clears.

**"The slope change is conservative."** I wrote that a level which never earns
a slope behaves as before. The covariance was propagating into `variance`
ungated, so **every zone got wider**, including levels with no slope. A
non-trending level is now bit-identical to the old filter, pinned against a
verbatim copy.

**"`CONFIDENT_TOUCHES` is the shrinkage parameter."** It appears in one `if`,
choosing between two wordings of a string, and affects no number. The shrinkage
is `PRIOR_WEIGHT = 4.0`. The argument survived on the wrong constant.

**A near-miss.** The first 2D filter gated the covariance propagation as well
as the mean's. The off-diagonal is the only thing that lets a slope be learned,
so it reported `slope = 0.0000` forever and **looked healthy doing it**. Caught
by printing the number rather than trusting the tests.

### What does the killing

- **The duty-cycle control.** Random gates keeping the same share. On a
  net-negative book any rule that trades less shows a profit improvement, so
  the headline carries no information.
- **The barrier test.** Did price reach the target before the stop, inside a
  holding period a desk would accept. Base rate 48.6%.
- **Widening the universe.** Sixteen instruments to twenty-nine killed the only
  positive cell in a sixty-cell sweep, and cost a rerun.
- **The placebo level.** An ordinary prior extreme at a similar distance with
  no imbalance behind it. Without it a study of gap edges measures mean
  reversion and reports it as structure.
- **A test that a published feature has not gone near-constant.** It caught two
  unrelated errors on the same feature hours apart; neither looked like what it
  was, and both surfaced as a distribution collapsing.
- **Reading the code instead of the name.** `CONFIDENT_TOUCHES`, and
  `fade-to-value` already trading origins, which changed the question before
  any measurement ran.

### Alive and unproven

The slope, the calibrated zone width, the estimated `PRIOR_WEIGHT`, six new
formation kinds. **None has been measured against outcomes.** Each ships behind
a guard that makes a cold or thin book behave as it did before. That makes them
safe; it does not make them right.
