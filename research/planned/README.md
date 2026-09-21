# Planned

Documents describing work that **does not exist in the code**.

They were in `docs/` beside the documentation of things that do, which is the
one place a reader cannot tell the difference - and the difference is the whole
point. `docs/score.md` opened "Status: designed, not built. Nothing in this
document exists in the code yet", and it was filed next to `docs/prices.md`,
which describes a service you can run.

The rule for this folder is narrow: **a design nobody has built, or a
measurement nobody has taken.** Once either happens the document moves - to
`research/` if what it produced is a finding, to `docs/` if it produced code
somebody has to operate.

Nothing here is a promise. A plan that turns out to be wrong is deleted rather
than migrated, and saying so here is cheaper than discovering it from a stale
document later.

| | |
|---|---|
| [score.md](score.md) | designed, not built - one number per instrument in [−1, +1], and the decisions that are easy to get wrong quietly |
| [calibration.md](calibration.md) | not measured on this system - does 80% mean 80%, and what sizing needs from a probability before it can read one |
| [countering-the-anchor.md](countering-the-anchor.md) | not built - scalping the pullback to a daily call's own entry, on the opposite side to the call |
| [meta-labelling.md](meta-labelling.md) | measured - no edge (AUC 0.506); the level calls carry no direction at 5 minutes, and the old label would have taught "always invert" |
| [directional-edge.md](directional-edge.md) | not built - where a directional edge could live now the broker is readable, and why the horizon comes before the signal |
| [local-models.md](local-models.md) | not built - the host exists (64 cores, 125GB) and has no GPU, which is fine for `agents` and rules out `council` |
| [ensembles.md](ensembles.md) | not built - individual signals are weak; when combining them helps, when it cannot, and why the power audit makes this the best experiment left |
| [carried-ideas.md](carried-ideas.md) | a triage - research directions from earlier work elsewhere, graded against what has since been measured here |
| [more-mathematics.md](more-mathematics.md) | a triage - Catalan numbers, quantum mechanics with algebraic topology, and why a new formalism on the same close prices cannot add information |
| [cross-spreads.md](cross-spreads.md) | not measured - the only positive directional result here is an arbitrage residual the account cannot hold; whether the holdable kind carries any of it, and what two legs cost |
