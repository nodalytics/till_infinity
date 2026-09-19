# The null for the post-stop replay

**Taken 2026-09-02. It refuted the claim it was built to test.**

## What was measured, and what it cannot say on its own

Walking `quotes.db` forward from each of 55 stopped trades on 2026-09-02 found
that price went on to reach the trade's target **82% of the time within 24
hours** — 25% within 30 minutes, 56% within two hours, 69% within four. That
reads as "the stops are early", and it was reported that way.

The comparison inside it is sound: the recovery rate is **flat across the
model's confidence bands** — 90%, 87%, 88% for the 0.7-0.8, 0.8-0.9 and 0.9+
bands. Every band shares one horizon, so whatever inflates the absolute figure
inflates all three equally, and the model's stated probability adds nothing to
whether a stopped trade was going the right way.

The **absolute** figure is the problem. A target sits roughly one risk unit
from entry. A driftless process will touch a level that close given a day, so a
large fraction of that 82% may be arithmetic about random walks rather than
anything about these calls. Nothing in the measurement separates the two,
because there is no null to subtract.

## The result

55 stopped trades against 684 signal-free entries drawn on the same feeds, same
side, same target *distance*, same horizons, measured through the same code
path so any bias in the method cancels in the difference.

| within | stopped trades | random entries | gap |
| --- | ---: | ---: | ---: |
| 30m | 14/55 — 25% | 307/684 — **45%** | **−19.4%** |
| 2h | 31/55 — 56% | 422/684 — 62% | −5.3% |
| 4h | 38/55 — 69% | 470/684 — 69% | +0.4% |
| 24h | 45/55 — 82% | 572/684 — 84% | −1.8% |

**The 82% was arithmetic about random walks.** The null reaches 84%. Given a
day, price touches a level one risk-unit away whether or not anything was
predicted, and the original figure carried no information about these calls.

**And the short horizon is worse than uninformative.** At 30 minutes a
signal-free entry reaches the target 45% of the time; a stopped trade manages
25%. That is the third row of the table this document was written with — *random
above the trades* — and it needs explaining rather than acting on.

The explanation that fits is mechanical: a stop fires when price is moving
decisively against the trade. Immediately after one, price is inside a
directional move away from the target, so near-term recovery is *less* likely
than from an arbitrary moment. Stops do not interrupt trades that were about to
work; they mark trades that were going wrong, and the market keeps going that
way for a while.

## What this changes

* **"Widen the stops" is dead** as a conclusion from this evidence. It rested
  on the 82%, and the 82% is the baseline.
* **The flat-across-confidence-bands comparison survives**, because it holds
  the horizon fixed and compares three bands against each other: 90%, 87%, 88%
  recovery for 0.7-0.8, 0.8-0.9 and 0.9+. The stated probability still says
  nothing about whether a stopped trade was going the right way. That is a
  claim about the model, and the null does not touch it.
* **The per-instrument readings are unqualified too.** Gold recovering 9 of 9
  and Boom 500 only 2 of 5 were reported against each other, which is the
  better comparison, but neither has its own null and the two feeds have very
  different processes. Gold's stops may still be too tight — the older finding
  that 62% of its stopped trades reached target afterwards against 26%
  book-wide is a *within-book* comparison and stands on its own — but this
  replay is not the second witness it was presented as.

## What it cost, and what it was worth

About 34 minutes of query time and one bug: a `print` outside its `if n:` guard
crashed the first run on a feed with no quotes. The rerun also excludes such
feeds from the *treatment* arm, so both arms cover the same instruments.

The measurement changed the answer. That is the argument for running the null
before acting rather than after: the reported 82% would have justified widening
every stop on the book, and the true reading is that being stopped predicts
continuation, not reversal.

## Related

* [failing.md](failing.md) — the measurement this retracts, kept as written.
* [planned/excursion.md](planned/excursion.md) — the other route to stop width,
  and now the only one left. It asks how much heat a *winning* trade takes,
  which needs no horizon and no null. `adverse_r` reads 0.0 and must be fixed
  first.
* [horizon.md](horizon.md) — the same class of error caught earlier.
