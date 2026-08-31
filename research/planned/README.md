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
