# Research

Experiments and their results. Each document is a question, what was run to
answer it, and what the answer turned out to be — including when the answer was
"do not build this", which it often is.

Design documents live in [docs/](../docs). This folder is for things that were
*measured*, with the harness that measured them, so a result can be re-run
rather than believed.

| | |
|---|---|
| [models.md](models.md) | **measured** — would trees, forests, cosine similarity or an MLP help; a 1KB logistic regression beats all of them, and `side` carries most of the signal |
| [features.md](features.md) | **measured** — `side` alone beats all nine features together, generated features make it worse, and the trivial "level holds" rule beats our own directional call |
| [volatility.md](volatility.md) | **measured** — the estimate is well calibrated and its half-life is well past the optimum; a flat 20-bar mean beats it at every interval |
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
```

`touches.py` writes `touches.pkl` beside itself and the others read it, so the
replay runs once rather than four times.

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
