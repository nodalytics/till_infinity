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

### The operator's standing instructions, 2026-11-15

- **Measure gross first.** "We are looking at before costs." A rule with no
  edge before costs cannot have one after, and costing a rule that has no side
  wastes the run. Price it once a side exists to pay for it.
- **Break everything down. "We want to look at things from a microscopic
  view."** A pooled mean hides its parts: cut by instrument, by what triggered
  it, by shape, by session, by how long it took. On this desk a pooled median
  once agreed with a claim every subgroup refuted, and a two-way split of one
  rule read +0.335 and -0.292 where the pooled number was -0.144.
- **Ask what *differentiates*, not only whether the rule works.** Volatility is
  one lens and usually the wrong one - measured around a level sequence, ATR
  *rises* into the setup and separates winners from losers by 0.02. The
  approach, the age, the watchedness proxies and the position in the range are
  different questions and one of them confirmed where the rule itself did not.
- **A null's job is attribution, not permission.** The operator's position is
  that a result on shuffled or placebo data should not by itself veto a
  decision, "cause the data and movements are different" - and that is right
  about what a null *cannot* do. What it does do is say **which part of the
  machine produced the number**: run the same detector with only the level
  relationship removed, and whatever survives belonged to the selection rather
  than to the level. Every branch changes what gets built, which is why the arm
  is worth its compute.
- **The Deriv synthetics are a different lens, not more instruments - and the
  thing they control for is news.** The operator's correction, 2026-11-15:
  *"people trade deriv synthetics, so part of our test is to see if levels work
  there as well like they do for the real markets; the great separator is just
  news, everything else is mostly the same."* They are traded by humans drawing
  the same levels with the same tools, so they are **not** a control for
  watchedness or for participants. They have no scheduled releases and no
  fundamentals, so what they isolate is whether a structure needs news to
  exist. A rule that works on a real market and on `Volatility 75` is not
  news-driven; one that works only on the real market is.
- **And they are traded, so being a control does not demote them.** Measured
  2026-11-15: changes in `Volatility 75`'s hourly ATR correlate **+0.006 with
  EURUSD's and +0.005 with gold's**, where EURUSD and gold correlate +0.512
  with each other. That independence is an argument *for* carrying it - a
  return stream whose risk moves with nothing else in the book is worth more
  per unit of it - and it never closes, so on a weekend it and the Boom/Crash
  family are the only things on the account that quote. A control and a
  position are not exclusive.

### The operator's standing instructions, 2026-11-21

- **Edge life means 7 days, 3 months, 1 year.** The operator: *"remember that
  edge life to us means short last 7 days, to last 3 months, max last 1 year."*
  So default a research window to one of those three and say which one a number
  came from. A study pooling four years answers a question nobody is asking,
  because the premise is an adapting process rather than a durable rule.

  **State the arithmetic with any 7-day claim.** At about a dozen trades a day
  the desk makes **~84 in a week**, against the **350 to 800**
  `projecting.Trade.trials` needs before a win rate can be told from its
  geometric baseline. So **a 7-day edge can be acted on and never verified**,
  and 3 months - near a thousand trades - is the shortest window that can be.
  Saying "it worked last week" is a statement about 84 trades and has to be
  labelled as one.
- **Roles are a first-class idea, and two packages already use them.**
  [`docs/specs/2026-11-21-roles-design.md`](docs/specs/2026-11-21-roles-design.md)
  is the record. `SurpriseEdge(Surprise, ManagedExit, EdgeEntry)` is decision,
  exit and entry composed; statespace splits dispersion from price. What is new
  is `location` and `reaction` from slower frames, a `gauge` from
  `projecting.py`, and that **the assignment can change** - including which
  frame holds which role.

  Three constraints came with it and all three are measured. A role must be a
  **distance and not a veto**: confluence as a vote went 271 entries to 1 to 0.
  A rotating assignment must beat **a placebo switching at the same duty
  cycle**, because `strategy-rotation-is-not-timeable`. And a role driven by
  **recent performance is unmeasurable** where one driven by a **volatility
  state** is, since the decay estimator cannot tell a half-life of 10 trades
  from infinity while log volatility reads rho 0.9963 to 0.9995.
- **An edge cannot be detected as stopping inside the window in which it
  stopped.** The operator wants a system that *"can detect when edge is not
  working and deploy another one"*, and the arithmetic refuses the detection
  half: telling one win rate from another needs **1,500 to 3,000 trades**,
  which at a dozen a day is **18 to 36 weeks**. A detector on the edge's own
  P&L fires on noise, and `strategy-rotation-is-not-timeable` has every pause
  rule matching a coin at the same duty cycle.

  Keep the intent three other ways: **condition on a volatility state** rather
  than a score; **run every rule and let the state set the sizes**, which needs
  no switching decision at all; and **detect breaks rather than fades** - a
  venue fault or a gate refusing everything is one event, not a thousand.

### The operator's standing instructions, 2026-11-17

- **Leg analysis is in scope, and it is the subject of the data.** The
  operator, 2026-11-17: *"anything that concerns leg(s) analysis, we are in,
  the data we are using has to do with legs, so turn points, etc are important
  to us."* So a null on a leg statistic is attribution and not a reason to stop
  measuring legs. What the turn studies closed is narrow -
  [`turns-fast.md`](research/docs/turns-fast.md) closed *a fixed-drop turn
  label on an hourly clock, carried by `vol` alone* - and the leg objects
  themselves (the origin, the push, the pull, the extreme) are the vocabulary
  the desk thinks in. Keep building them; keep nulling the claims made about
  them.
- **A pull origin has a supplied definition, and it is a labeller, not a
  signal.** Clauses 1 and 2 - a 15-bar pivot with a 1.5 ATR fall into it - hold
  at the candle's close. Clauses 3 and 4 - a 3 ATR directional rise that never
  revisits the low - are the forward confirmation, about 5-6 candles later. Any
  study that treats the whole definition as a signal has used the future;
  [`persistence.md`](research/docs/persistence.md) is the split version.

#### Put the label's own arithmetic in the incumbent

The biggest single measurement error of 2026-11-17, and it is not a bug - every
line was correct and the design was wrong.

A label of the form "price reaches `k` ATR from the origin" is **already
partly satisfied at the decision bar**, because price has travelled from the
origin to that bar's close. Call that distance the cushion: `remaining = k -
cushion` is computable at decision time with no information about the future at
all. Anything correlated with it then reads as skill - the bar's size, its
wick, where in its range it closed.

Measured: candle geometry read a **+0.15 AUC lift** over a volatility-only
incumbent, which is a large and publishable-looking number. With `cushion` and
`remaining` moved into the incumbent, the incumbent went from 0.5391 to
**0.7467** and the full model's lift turned **negative**, day-block 90%
`[-0.0381, -0.0057]`. `cushion` alone reads **0.7648**.

So the rule: **before fitting anything, write down the arithmetic that maps
what is known at the decision bar onto the label, and put every term of it in
the baseline.** If the baseline then explains the result, the finding was the
definition. This is the same defect as `the-origin-picks-a-distance-not-a-
probability` and `a-return-rate-is-geometry`, arriving through a model instead
of through a rate.

And the corollary that matters for trading: **the quantity that predicts the
outcome is the quantity you pay for it.** The cushion is the risk - the stop
sits beyond the origin - so a high-cushion entry buys its hit rate at exactly
the fair price. Measured gross on 4,656 hourly EURUSD candidates: hit 0.2446
against a fair 0.2394, **+0.0309R** a trade, day-block 90% `[-0.0325,
+0.0933]`.

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
