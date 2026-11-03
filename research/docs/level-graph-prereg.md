# Is a level's position in the transition graph worth anything its distance is not?

**Pre-registered 2026-11-03, before any result was read.** The claim, the
statistics, the nulls, the pass rule and the direction of every effect below
were written and frozen first.

## Why this is not a repeat

Levels have been measured six ways on this desk and every one is null. The
table is in the `finding-edges` skill; the short version is that **a level does
not attract price** ([magnet.md](magnet.md): 44.9% reached against 49.5% for an
arbitrary price the same distance away), **does not block it**
([level-shield.md](level-shield.md): 1 of 210 cells beats its hardest null,
with real below the null in 188), **is not graded by its own prior behaviour**
([gap-levels.md](gap-levels.md)), and **is not better found by topology**
([topology.md](topology.md)).

So the question is why to ask anything about levels again, and the answer is
not optimism. **Price is the summary of the information**: whatever this desk
trades, it trades the geometry of price, so "the geometry is null" cannot be a
finding - it would be a statement that no observable exists. What those six
studies closed is narrower than the family they were in, and one row of that
table is the pattern this study copies: a level's own **record** predicts
nothing (AUC 0.5005) while `abs(record - 0.5)` reads **0.6006**. Nobody found
that by asking whether levels work. They found it by asking which *function* of
the level is the observable.

**The function this study proposes is centrality, and the claim is agreement
rather than attraction.** `a-magnet-is-a-shared-reference` states the
reformulation: liquidity rests where many participants compute the same price.
That is a claim about how many independent paths reference a price, not about a
force pulling price toward it, and **nothing in the six studies tests it**.

It is also a different object from `topology.md`. Persistent homology measured
the *shape of the price cloud* and concluded the levels it found were ones a
ruler already had - that is about **finding** levels. A transition graph does
not find levels; it **ranks** levels a ruler already found. Static point cloud
against a Markov structure over time.

## The graph, stated so it cannot be adjusted later

**Nodes** are the levels `research/ideas/level_shield.book_path` already
produces at each bar, clustered by `indicators.grouping.cluster` at the
study's tolerance. The level book is taken unchanged from the refuted study, so
a difference in result cannot be a difference in how levels were drawn.

**An edge** `i -> j` is recorded when price leaves the neighbourhood of node
`i` and the **next** node neighbourhood it enters is `j`. A neighbourhood is
`tol` volatility units either side of the node price, `tol` being swept.
Re-entering the same node is not an edge; it is a dwell and is counted
separately, because a self-loop would let a single oscillation dominate the
degree of one node.

**Weights** are transition counts. A second weighting by `1 / time taken` is
computed and reported beside it, because
`a-magnet-is-a-shared-reference` says to use the **time exponent** rather than
the return rate - a rate is geometry, and `a-return-rate-is-geometry` records
the origin's 82% being matched by a distance-matched placebo on every class.

**Causality.** The graph at bar `t` is built from bars strictly before `t`, and
every outcome is read strictly after `t`. `open-gap-filters-are-lookahead` is
the standing cost of getting this wrong: `drawing.gaps` emits only *unfilled*
gaps, so using it as a bias read +0.50R a trade out of nothing.

## The four centralities

Computed per node on the causal graph, all four reported, no composite:

1. **degree** - how many distinct nodes connect to it.
2. **weighted degree** - total transition count on its edges.
3. **betweenness** - the share of shortest paths through it, which is the one
   that matches "many participants compute this price" most directly.
4. **PageRank** - the stationary share of a random walk on the graph, damping
   0.85, which is degree with the neighbours' importance folded in.

**No composite and no fitted weights.**
`only-the-sign-survives-into-a-weighted-sum` holds that activation, scale and
per-term offset are rank identities within a weighted sum, and
`fit-on-the-edge-not-the-raw-score` measured fitted weights beating hand-tuned
ones on AUC 0.604 against 0.556 while **losing on edge, +0.002 against
+0.019**. Four columns, four verdicts.

## The outcome

At each causal anchor, for the nearest node on each side: **does price travel a
fixed distance `d` before returning to the node**, the same outcome
`level-shield.py` measured, so the two studies' numbers are comparable. `d` is
swept in volatility units.

The claim is **not** that a central node is reached more often. It is that the
outcome differs between a high-centrality node and a **distance-matched,
stratum-matched** low-centrality one. Matching on distance is not optional:
that single control is what turned the magnet claim from 44.9% into nothing.

## Stratification

**Within volatility strata, always.** `topology-restates-volatility` is the
single most likely explanation of any positive result here - levels, ranges
and shapes were all null once stratified - and `auc-is-free-on-volatility-
targets` measured AUC 0.805 on a *constant-volatility* process collapsing to
0.525 within strata. Strata are quintiles of the trailing volatility unit,
swept, and no pooled number is reported without its per-stratum twin.

## The nulls, and what each is for

Taken from `level_shield.py` unchanged, which is the point:
`null-structure-claims-on-the-same-detector` requires the null to walk through
the same detector with the same bar geometry.

| arm | what it holds fixed | what it destroys |
|---|---|---|
| `bar_shuffle` | the real bar distribution, including its skew | the order, so any graph structure |
| `walk_geometry` | the volatility and the calendar | the return distribution's shape |
| `garch_bars` | clustering, fitted per feed | everything else |
| `duty-twin` | the firing rate | which anchors fire |
| **distance-matched placebo** | the distance and the stratum | that the price is a node at all |

`bar_shuffle` is the arm that matters most here. A transition graph on a
shuffled series still has nodes and still has edges, because clustering a
price series always produces clusters - so the shuffled arm names what is
**mechanical** about centrality, which is exactly what
`shuffled-twin-names-the-mechanical-observables` says to use it for. The
hardest of the arms is the bar, and it is the **highest-powered** shuffled arm
rather than each arm's own, per that same note.

**The placebo instrument pair** is two Deriv volatility indices, carried in
every cell. `carry-an-independent-placebo-pair` caught two leaks in one run,
and `the-placebo-arm-selects-the-null` is the rule that kills this study if a
placebo instrument beats its own hardest null.

## Power, before any null is reported

`show-power-before-reporting-a-null` is not optional, and the anchored-states
study run earlier today is the reason it is stated twice here: its plant did
not register at **any** strength up to 3.20, because the outcome's denominator
was a trailing EWMA that had already absorbed the previous window's plant. A
null from a test that cannot see a planted effect is not a null.

So the power sweep comes **first**, and it plants into the graph rather than
into the price: a chosen node is given extra transitions, strength swept, and
the sweep reports the strength at which centrality stops distinguishing it.
The plant must not touch the trailing volatility unit, and a zero-strength
control must read nothing.

**The positive control is `Range_Break`**, which is a range by construction, so
its graph must show two dominant nodes with a heavy edge between them. A
harness that does not find that is broken rather than reporting a null -
`range-break-is-the-level-positive-control`. `Drift_Switch` is the regime
control and must **not** show it.

## The pass rule, frozen

All five, or the claim fails:

1. Beats the hardest null arm within strata on **3 or more** non-placebo
   instruments, in **both halves** of the history.
2. Survives Benjamini-Hochberg at q=0.10 over every cell attempted.
3. **No placebo instrument** passes, and no distance-matched placebo cell does.
4. The duty-cycle twin does not pass.
5. The power sweep shows the test could have seen an effect this size.

Passing all five is "worth a fresh-data test", not an edge. DSR >= 0.95 over
the true trial count is still required before that word is used.

## And the ways a pass would still be uninteresting

* **If it is volatility.** Centrality correlates with how long price spent
  near a price, which correlates with low volatility. If the per-stratum
  effect is a fraction of the pooled one, the finding is
  `topology-restates-volatility` again and belongs in that file.
* **If it is unreachable.** A dispersion reading has to move a stop of 3.0
  volatility units by more than 0.16 of the risk, so the bar is **0.48 units**.
  A centrality difference that cannot move a stop that far is not tradable
  whatever its z.
* **If it is dwell time renamed.** Dwell is counted separately for this
  reason; a centrality measure that tracks dwell at r > 0.9 is dwell.

## Data

The 1d FX history, 4,477-6,008 bars over 6.3-19.9 years, which is the only
window with enough de-overlapped anchors to build a graph from. **15-minute is
explicitly not the primary**: ~70 de-overlapped anchors per feed gives a graph
too sparse for betweenness to mean anything, and it is reported as a secondary
with that caveat attached rather than omitted.

## What is deliberately not done

**No trading rule.** This study measures a reading, and
`publish-then-measure-then-gate` is the order: every refuted gate on this desk
was built before it was scored. If centrality survives, it becomes a published
feature on every decision and is scored on the record before anything gates on
it.
