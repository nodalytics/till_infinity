# More mathematics — and why most of it cannot help

**Status: a triage, not a plan.** None of this exists in the code.

Three directions were proposed - Catalan numbers, combining quantum mechanics with algebraic
topology, and a swarm of specialist agents. One contains a genuinely useful result, one contains
one computable object and a lot of decoration, and the third turns out to be about something
other than mathematics. The section that matters most is the last one.

## Catalan numbers — one real contribution, and it is about power

`C_n = binom(2n, n) / (n + 1)` counts Dyck paths: lattice paths of `2n` steps of `+/-1` that
return to zero without ever going below it. That is a price path constrained by a barrier, so the
connection to everything in `barriers.md` and `first-passage.md` is exact rather than
metaphorical.

### What it does not add

The obvious application is already covered. For a symmetric `+/-1` walk the probability of
reaching `+a` before `-b` is exactly `b / (a + b)` - the discrete gambler's ruin - and that is the
**same** formula the continuum first-passage derivation gives and that
`premium_discount.py` confirmed across 314,794 rows. Discrete and continuous agree here, so
recomputing it combinatorially would produce the number already in use.

And the place they genuinely disagree has already been measured. The lattice walk cannot overshoot
a barrier; a real bar can and does. That gap **is** the slippage in `costs.md`, and the live
journal puts it at 0.063 of a stop. So the discretisation error is not an open question needing
combinatorics - it is a measured quantity.

### What it does add, and it is worth running

**Catalan numbers count how many hypotheses a market-structure rule is implicitly choosing
between.** A nested sequence of swings - higher highs inside higher highs, a pullback inside a
leg - is a balanced bracketing, and the number of distinct bracketings of `n` items is `C_{n-1}`:

| swings | distinct nestings | implied Bonferroni factor on the detection floor |
|---|---|---|
| 4 | 5 | 1.18x |
| 5 | 14 | 1.33x |
| 6 | 42 | 1.46x |
| 7 | 132 | 1.58x |
| 8 | **429** | 1.70x |
| 9 | **1,430** | 1.81x |

This is not decoration, it is the missing input to `power.py`. That harness had to be handed a
cell count per study, and for the structure-based ones - `smc.py`, `patterns.py`,
`displacement.py` - the honest count was never obvious: a rule phrased as "a break of structure
after a higher low" is selecting one configuration out of the Catalan set, not out of the handful
of cells the script happened to print.

**So a structure rule over eight swings is about 429 hypotheses**, and `power.py` should take its
comparison count from `C_{n-1}` rather than from how many rows a script chose to tabulate. That
reclassifies `smc.py` and `patterns.py` from "blind by a factor of six" to blind by rather more,
and it is a correction to the audit rather than a new signal.

Second, smaller use: the exact distribution of the **height of a Dyck path** is known in closed
form, so `breakout-runs.md`'s finding that excursion is exponential with mean equal to the
giveback can be checked against the exact lattice answer instead of against a continuum
approximation. Cheap, and it would either confirm the law or quantify where bar discreteness bends
it.

## Quantum mechanics with algebraic topology — one object, and a warning

The honest starting point: both halves have already failed here separately. The earlier work
tested a quantum superposition model and found **zero collapse events on any asset**, concluding
that classical statistical mechanics was the right frame. `topology.md` found persistence
landscapes losing to six trailing volatility ratios by 6.8 points, and `shapes` and `motifs` dying
on bootstrap. **Combining two formalisms that each measured nothing is not a reason to expect
something.**

There is nevertheless one well-defined, computable object worth naming, because it is the only
part of this pairing that is not analogy.

**Geometric phase - holonomy around a closed loop.** Take the analytic signal of a price series
(its Hilbert transform gives an amplitude and a phase), and consider a stretch where price returns
to where it started. The phase accumulated around that closed loop is **not** determined by the
endpoints; it depends on the loop. That is a real invariant, it is basis-independent, it is cheap
to compute, and it measures something none of the existing 34 features do: *how* a round trip was
made rather than that it was made.

It is also the honest version of "topological": a holonomy is a genuine topological quantity
because it is invariant under reparametrisation of the path. Persistent homology on a price window
is not - it depends on the embedding and the metric, which is exactly why `shapes.py` came out at
chance at two different embeddings.

**The prediction to record before running it**: it will fail, for the reason set out in the next
section. It is worth one run because it is a day's work, it is falsifiable, and a phase invariant
is the one class of feature this repository has never computed.

## The reason almost none of this can work

This is the most useful thing in this document, and it applies to every "try X" direction
including the ones above.

**Every transform proposed so far reads the same closed prices.** Candle features, gaps, anchors,
zma, persistence landscapes, regression channels, stretch measures, PIP windows, Catalan
bracketings, geometric phase - all are functions of one series. And the earlier work measured that
series' effective dimension: a participation ratio of **5.0 +/- 0.3**, meaning eleven features
compressed to about five independent factors.

If the information content of the input is fixed, a new formalism cannot add information. It can
only re-express what is there - possibly more legibly, which is worth something for a model, but
never more of it. That is consistent with every result in this repository: dozens of
transformations of one series, all landing within a point or two of fair odds, because they are all
reading the same five factors.

**What adds information is different data, not different mathematics.** And the specialist agents
in the other proposal are, read carefully, a list of exactly that - an order-book imbalance reader,
a cross-venue event matcher, filings and transcript classifiers, on-chain forensics, narrative
dispersion across sources. Not one of them is a transform of close prices; every one is a
different sensor.

So the ranking that follows from this is uncomfortable but clear:

1. **tick and level-2 data** - would settle the slippage bracket in `costs.md` and unblock
   order-flow absorption, the two things currently blocked for want of depth;
2. **cross-venue quotes** - a lead-lag edge is a claim about one venue pricing before another,
   which is information the single series cannot contain;
3. **event and text data** - the news and filings store already exists in this codebase, and no
   study here has used it;
4. **more mathematics on close prices** - last, and the two items above are worth one run each
   mainly because they are cheap and falsifiable.

## The part of the swarm proposal worth taking

Not the swarm. This is a two-core production instance and a research lab that also serves the live
desk's terminal; `starving.md` records what happened the last time research competed with the desk
for cores.

What is worth taking is the **adversarial pattern** - `devils_advocate`, `adversarial_reviewer`,
`veto`. The most expensive class of error here has not been a bad hypothesis, it has been a result
that looked real and was an artefact, and today produced four in one sitting: a stop-overshoot
figure four times too large because it came from bar extremes rather than fills, a claim that a
production setting was unset when it was not, three wrong guesses about exposure in a row, and
"refuted" applied to a study 82 times too small to refute anything.

Every one was caught by a check someone had to think to run. `power.py` is the first of those
written down instead of performed ad hoc, and the pattern generalises: a standing adversary whose
only job is to find the cost that was not charged, the look-ahead in the indexing, and the
comparison count that was not corrected is worth more here than another hypothesis.

That is a checklist, not a framework, and it should live next to `power.py`.
