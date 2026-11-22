"""Is the filter right, and what should its parameters be - both from residuals.

**A member cannot grade itself, which is the whole reason this folder is
separate from `filters/`.** Every module here takes a fitted model as an input
and tries to break it: against its own residuals, against a null that should
beat it, against data generated from known parameters, or against the rest of
the panel.

## The entries

| module | how it tries to break a model |
| --- | --- |
| `diagnostics` | is the filter right, and what should its parameters be - from the residuals |
| `nulls` | the nulls as library code, rather than something each harness rebuilds |
| `facts` | does a member, simulated forward, produce something that looks like a market? |
| `distance` | Wasserstein: a second axis for judging a member, beside likelihood |
| `paths` | generate data from the model, so a parameter can be **recovered** rather than argued |
| `searching` | discovery: sweep the panel, keep the losers, make the controls structural |
| `dispersion` | do these units differ at all, once their own counting noise is removed? |

## The two rules this folder exists to enforce

**A null belongs to a named property.** `a-control-is-only-for-a-named-property`
is why `nulls` is library code: a harness that writes its own control writes one
for the property it was hoping to find, and `the-placebo-arm-selects-the-null`
records a block design finding structure in 27 of 36 placebo pools.

**Show power before reporting a null.** `paths` is here for that - plant the
effect, sweep its strength, and report where the test goes blind. A null from a
test whose power was never measured is an absence of evidence wearing the
clothes of evidence of absence.
"""

from __future__ import annotations
