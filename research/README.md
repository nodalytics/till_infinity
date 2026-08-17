# Research

Experiments and their results. Each document is a question, what was run to
answer it, and what the answer turned out to be — including when the answer was
"do not build this", which it often is.

Design documents live in [docs/](../docs). This folder is for things that were
*measured*, with the harness that measured them, so a result can be re-run
rather than believed.

| | |
|---|---|
| [models.md](models.md) | **measured** — would trees, forests, cosine similarity or an MLP help; a 1KB logistic regression beats all of them, and five times the data did not change that |
| [features.md](features.md) | **measured** — `side` alone matches all nine features together, generated features make it worse, and the trivial "level holds" rule still beats our directional call everywhere but the top decile |
| [volatility.md](volatility.md) | **measured** — the estimate is well calibrated and its half-life is well past the optimum; a flat 20-bar mean beats it at every interval |
| [prior.md](prior.md) | **measured** — what `edge` is actually measuring; subtract a side-aware baseline and the level's record plus its neighbours predict at 51.8%, AUC 0.520 |
| [turns.md](turns.md) | **measured** — can a major turn be seen coming; yes, weakly. AUC 0.595 purged over 310 turns, and `vol` alone carries it |
| [cycles.md](cycles.md) | **measured** — does a level's place in the larger move matter; one cell separates by nothing at all, and the AUC gain's interval includes zero |
| [bandits.md](bandits.md) | design note — where a bandit fits (attention budgets, not the alert gate) and why gymnasium is not the reason to reach for one |

Findings that changed the code, or that belong next to it, are written up in
`docs/` instead — [edge.md](../docs/edge.md), [strength.md](../docs/strength.md),
[absorption.md](../docs/absorption.md), [magnet.md](../docs/magnet.md),
[news-dedup.md](../docs/news-dedup.md).

## Running the harness

From the repository root, with the stored prices database in place:

```bash
python research/harness/touches.py    # replay once, cache resolved touches
python research/harness/models.py     # model and similarity comparison
python research/harness/edge_gate.py  # the |edge| gate, thresholds and quantiles
python research/harness/similarity.py # does feature distance predict agreement
python research/harness/features.py   # feature importance, and generated features
python research/harness/holds.py      # the edge against "assume the level holds"
python research/harness/vol.py        # does the volatility estimate predict the next move
python research/harness/cycles.py     # does cyclical context change what a touch means
python research/harness/turns.py      # can a major turn be seen before it happens
python research/harness/prior.py      # what edge measures, and whether the kNN earns its place
```

`touches.py` writes `touches.pkl` beside itself and the others read it, so the
replay runs once rather than four times.

## Which data these were measured on

Everything dated **2026-08-16** was re-run on 10,484 touches across fourteen
instruments, after the backfill in [todo.md](../docs/todo.md) §0d took the
store from 455k bars to 1.56M. The earlier readings used 1,995 touches across
six instruments over days rather than months, and are in git.

Two of the six documents changed their answer. [turns.md](turns.md) went from
"does not separate from chance" to AUC 0.595; [cycles.md](cycles.md) went from
"nothing separates anywhere" to one marginal cell. The other four reproduced,
with absolute accuracies about five points lower on the harder sample and the
rankings intact.

**Re-run the harness after any backfill.** Every document here reads
`touches.pkl`, which regenerates from whatever is in the store, so a collection
run silently invalidates all of them.

## What every result here shares, and its limits

**Walk-forward.** Nothing is predicted from its own outcome or from anything
that resolved after it.

**Bars only.** Production drives touches from quotes as well, and on
2026-08-14 that difference twice overturned a replay result: the
instant-resolution fix looked complete on a replay and was still 42.9% wrong
live. Treat every number here as the level machinery rather than the system.

**One replay, six instruments, ~2,000 touches.** Enough to rank things, not
enough to pin a constant. Where a number is quoted as transportable, the
document says so and shows the split that establishes it.

**Measured after 2026-08-14.** Everything before that date was counted on data
where roughly half of all outcomes were artefacts — touches resolving at the
instant they opened — so earlier measurements in this project are not
comparable, and several were withdrawn.
