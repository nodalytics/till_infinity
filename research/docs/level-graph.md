# A level's centrality in the transition graph is null, and the harness cannot prove it

**Measured 2026-11-03, pre-registered in
[level-graph-prereg.md](level-graph-prereg.md).** Harness:
[`research/ideas/level_graph.py`](../ideas/level_graph.py), reporter
[`level_graph_report.py`](../ideas/level_graph_report.py).

| criterion, frozen before the run | result |
|---|---|
| 1. beats the hardest null on 3+ instruments **and** both halves | **NOT MET** — 2 instruments, and **1 of 221** cells in both halves |
| 2. survives Benjamini-Hochberg | not computed — needs a per-cell p |
| 3. no placebo instrument passes | **MET** — 0 |
| 4. the duty-cycle twin does not pass | not in this run's arms |
| 5. the power sweep shows the test could see it | **FAILS** — see the control |

**The claim fails. It is also not reportable as a market null**, because the
harness cannot distinguish a range it was handed by construction from a drift.
What follows is therefore a statement about the statistic.

## Why the question was asked again

Levels have been measured six ways here and every one is null -
[magnet.md](magnet.md), [level-shield.md](level-shield.md),
[gap-levels.md](gap-levels.md), [topology.md](topology.md),
[trap-levels.md](trap-levels.md) and `level-signatures.md`. The
pre-registration opens by saying which **claims** those closed, because the
table is a list of claims and not a list of forbidden subjects: price is the
summary of the information, so "the geometry is null" would be a statement that
no observable exists.

The reformulation tested here is **agreement rather than attraction** -
`a-magnet-is-a-shared-reference`: liquidity rests where many participants
compute the same price. Nothing in the six studies tests that, and it is a
different object from `topology.md`, which measured the shape of the price
cloud and found levels a ruler already had. A transition graph does not *find*
levels; it **ranks** levels a ruler already found.

## What was built

Nodes are `level_shield.book_path`'s levels unchanged, binned at
`round(price / (tol * unit))` fixed at first appearance so a drifting level
stays one node. An edge is price leaving one node's neighbourhood and next
entering a **different** one; re-entry is a dwell and never a self-loop. Four
centralities - degree, weighted degree, Brandes betweenness, PageRank - each
reported separately, no composite.

16 feeds at 1d including two generated controls, both price sources
(`extreme` and `body`), 77 null draws a cell from `level_shield`'s three arms.
**70,802 rows, zero error rows, every requested feed present.**

## The result

| | |
|---|---|
| cells on traded instruments | 231, 77 null draws each |
| beating the hardest null draw | **5 against 3.0 by chance** |
| instruments with a beating cell | 2 (gold, spx500) — rule needs 3 |
| **beating in both halves** | **1 of 221** (half A alone 2, half B alone 5) |
| real **below** its hardest arm | **226 of 231** |
| reachable at 0.48 volatility units | **0 of 231** |

| centrality | cells | mean gap | mean hardest | beats | reachable |
|---|---|---|---|---|---|
| betweenness | 59 | -0.0031 | +0.1901 | 2 | 0 |
| degree | 56 | +0.0056 | +0.2006 | 1 | 0 |
| pagerank | 60 | +0.0115 | +0.2012 | 2 | 0 |
| weighted | 56 | +0.0075 | +0.2003 | 0 | 0 |

The null arms produce about **27 times** the real effect. And **reachability
closes it independently of any significance question**: the bar for moving a
3.0-unit stop by more than 0.16 of the risk is 0.48 volatility units, the
widest gap anywhere is 0.26, and nothing comes within half of it. Even a
confirmed effect would not be tradeable.

## The half-split is what closed criterion 1

The pre-registration requires 3+ instruments **and** both halves. The first
version of the reporter checked only the instrument count and printed `[MET]`
on half the definition. With the split implemented, **1 of 221 cells** beats
its hardest null in both halves against 2 in A and 5 in B - which is the same
pattern that killed the anchored-states magnitude claim on the same data window
the same day, where 4 instruments met the count and 0 of 90 beat in both.

## `topology-restates-volatility`, again where predicted

| stratum | cells | mean gap | beats |
|---|---|---|---|
| 0 | 34 | -0.0014 | 0 |
| 1 | 41 | +0.0296 | 3 |
| 2 | 48 | +0.0035 | 1 |
| 3 | 56 | **-0.0262** | 0 |
| 4 | 52 | +0.0265 | 1 |

No monotone structure: the beats sit in 1, 2 and 4 while stratum 3 has none and
the most negative mean gap. The pre-registration named this as the most likely
explanation of anything positive and it is what the strata show.

## Why this is not a market null

**The positive control cannot be run from this store, and the generated one
fails.**

`Range Break` and `Drift Switch` are absent from `prices.db` at every interval
and venue, and the seqlab npz cache that would hold them exists on neither
machine. `seqlab.fetch` pulls from the MT5 terminal the live desk trades
through, so `research/starving.md`'s rule applies and they were generated
instead.

Three constructions were measured and **none separates from the drift arm**:

| construction | reading |
|---|---|
| Ornstein-Uhlenbeck to a centre | 6.01 edges a node against the drift arm's 5.28 |
| a walk reflecting off two walls | 6.01 again; `top_edge` **0.0096 against 0.0099** |
| two attractors with noise | **no cells** - zero volatility inside a state, so the unit collapses and `bins_of` refuses a zero-width bin |

The reason the first two fail is the mechanism the study rests on: **a bounded
walk visits every price in its range**, so its transition graph is a chain of
prices seen about once each. The range lives in the marginal distribution and
never reaches the graph. The third shows the alternative is not constructible -
a process that only visits two prices has no volatility to measure a range in.

So "two dominant nodes with a heavy edge between them" is not what a range
produces, and `range-break-is-the-level-positive-control` is satisfied in the
only way that matters: by reporting that the harness cannot find a range it was
given. **The generated range even appears in the top ten gaps at -0.208 and
-0.204** - in the wrong direction, the control failing in the same table as the
result.

## What did survive

**Centrality is not dwell renamed**, which the pre-registration named in
advance as one of three ways a pass would be uninteresting. Rank correlation
against dwell time: betweenness median **+0.062**, PageRank **-0.007**, degree
+0.458, weighted degree +0.489, against the 0.9 line. Worth noting weighted
degree reached +0.779 on its worst feed, so it is the one closest to being
dwell with extra steps.

## Defects found on the way

* **The reporter said "every job returned cells" while 10 of 16 feeds were
  absent.** It looked for `kind == "error"` rows, and a job killed outright -
  the lab rebooted mid-panel - takes its error row with it. Absence is now
  computed from the request.
* **`Row.kind` held the centrality name and overwrote the row-type marker**, so
  every cell was written as `kind="degree"` and a reporter filtering on
  `"cell"` would have found none of them. Renamed to `centrality`.
* **The harness rebuilt the graph four times per anchor** - the anchor loop sat
  inside the centrality loop - and `build(upto)` re-walked from bar zero each
  time. Brandes betweenness on the whole-history graph reached 393 nodes and
  1,493 edges, about 136M operations a series, which projected to 2.7 hours a
  feed and wrote nothing in six minutes. One graph per anchor and a trailing
  2,000-bar window took the same smoke from 88s to 33s - and the window is the
  better model anyway, since a level's watchedness now should not depend on
  transitions from nineteen years ago.

## Gross throughout

No spread is applied; this measures a reading, not a trade. Eight of the
fourteen carried feeds have two or fewer recorded quotes and no spread is
invented.
