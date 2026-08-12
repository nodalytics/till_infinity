"""Interaction effects — deliberately not built yet.

River's factorisation machines (`FMRegressor`, `FFMRegressor`) model how
features *combine*: venue x instrument x session x calendar-proximity, learning
that OANDA's gold spread behaves one way in the Tokyo session and another in
the hour before a payrolls print. That is genuinely the next thing worth having
and it is genuinely not buildable yet, for one reason.

A factorisation machine is supervised. It needs a target, and the honest
targets here are things like "what happened to the price in the next five
minutes" or "was this signal worth acting on" — which is to say, labels. Those
are exactly what `journal` has just started collecting: every signal is written
down with the features it was found from, and every outcome links back to the
decision it judges.

So the order is forced. Collect first, fit second. Writing an FM now would mean
inventing a target, and a model fitted to an invented target learns to predict
the invention.

What it needs before it is worth writing:

- a few weeks of journalled `(features, signal, outcome)` triples, which
  `journal export` already produces in the right shape;
- a decision about the target — forward return over a fixed horizon is the
  obvious candidate and has the obvious flaw that it labels a correct call
  wrong whenever the market disagrees for longer than the horizon;
- a walk-forward evaluation, because an online model tested on shuffled data
  reports a score it will never reproduce live.

Until then this module is empty on purpose, and that is a better state than a
plausible model nobody can check.
"""

from __future__ import annotations

__all__: list[str] = []
