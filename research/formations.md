# Seven ways to find a level, and why they run together

A level is a price. Which prices count is a separate question from what happens
at them, and until this year the answer was one method: `pips` took bar extremes
by prominence, and every level in production was drawn that way. All 969
recorded touch outcomes say `pip` and nothing else.

They now run together, merged rather than chosen. The argument for that is
narrow and worth stating precisely: **merging is additive**. `lv.merge` folds a
candidate into an existing level only when it falls inside that level's own
zone, so a pass that draws nothing costs a little work and removes no level, and
a pass that draws a price another pass already found adds a name to it rather
than a second level. Nothing can get worse by adding a formation; the only cost
is compute.

## The seven

| pass | what it claims | defined by |
| --- | --- | --- |
| `pip` | price turned here, significantly | prominence of a bar extreme |
| `run` | one run of volatility ended and the next began | retracement past a threshold |
| `origin` | an impulse started here and set a new extremum | what price did *next* |
| `profile` | a lot of activity happened at this band | density over price |
| `equal` | price stopped at *this same price* more than once | equality, within a quarter unit |
| `gap` | trade did **not** happen across this range | absence |
| `round` | people place orders at numbers they can say | nothing at all |

`pivot` is an eighth, from completed sessions, and predates this.

The table is ordered by how much history each needs, and the last row is the
point: `round` reads no history whatever, which makes it either a free level or
a superstition. It is in the default set to be measured, not because it is
believed.

## Why these three were added rather than three others

Because they fail differently from what already existed, and from each other.
That is the only property that makes agreement between passes worth anything: if
two methods make the same mistakes, both finding a price says no more than one
finding it twice.

* **`equal`** is the tight version of a question `form` already asks loosely.
  `form` clusters turns within a whole volatility unit, which on most
  instruments is most of a range; this asks whether the extremes are equal, at
  a quarter unit. `pip` ranks by prominence and cannot express "at the same
  price" at all - a double top is not two significant highs, it is two highs at
  one price, and the second is evidence about the first.
* **`gap`** is defined by absence. Everything else here is defined by presence:
  a turn that happened, an impulse that happened, activity that was there. An
  untraded range is the one object in the set whose evidence is that nothing
  occurred, so its errors have no reason to correlate with anything else's.
* **`round`** shares no mechanism with any of them. Its step comes from the
  instrument's own volatility rather than a table - the smallest power of ten
  at least `STEP_VOL` units wide - because a table is what this repository
  keeps finding bugs in: an instrument arrives, nobody adds a row, and the
  formation silently draws nothing for it.

## Agreement, and the thing that was never counted

`Level.origin` has always carried the passes that drew a level - `pip+run+origin`
- and `agree()` has always maintained it through a merge. **Nothing ever
counted it.** So "does a level two independent methods found behave better than
one a single method found" could not be asked, of any of the 969 outcomes or of
anything else.

`drawn_by_n` now publishes the count on every level call. It decides nothing and
it is not a gate; it lands in the journal beside the outcome, which is the
arrangement that lets the record settle it in a few thousand touches instead of
an argument.

### What it looks like so far

1,808 levels held across 42 instruments, first measurement after all four
original passes were made to run:

| passes agreeing | levels | share |
| --- | --- | --- |
| 1 | 771 | 42.6% |
| 2 | 794 | 43.9% |
| 3 | 241 | 13.3% |
| 4 | 2 | 0.1% |

| pass | contributed to | share |
| --- | --- | --- |
| `run` | 1,318 | 72.9% |
| `pip` | 1,257 | 69.5% |
| `origin` | 361 | 20.0% |
| `pivot` | 151 | 8.4% |
| `profile` | 3 | 0.2% |

**57% of levels now have more than one method behind them**, where before every
one was `pip` alone. `run` overtook `pip` as the most productive pass, and 347
levels are `run`-only - prices `pip` never drew, which had existed nowhere in
production.

`profile`'s three are explained in [shelves.md](shelves.md) and were the reason
it was rewritten.

## The setting was inert for its whole life

Worth recording as a failure mode rather than as history, because it is the one
this repository keeps repeating.

`STRUCTURES_FORMATION` was set to `pip,run,origin` in production. `Watcher.load`
replaces the freshly-configured engine with the pickled one, and a pickle
carries the settings it was **first** built with - so the engine drew with `pip`
alone from the day a state file existed, and kept doing so across every restart
and every deploy.

The symptom was that `run` and `origin` never drew anything. That reads exactly
like two formations that do not work, which is the worst kind of silent failure:
it produces evidence, and the evidence is wrong.

Configuration is now re-applied over the restore - what was *learned* is kept,
what was *chosen* comes from the deployment - and a test asserts the handover
rather than the setting, because the setting existing was never the problem.

## What none of this establishes

That any of these prices is respected. Seven ways of finding a level is seven
ways of proposing one, and the outcome machinery is the only thing that can say
whether a proposal was worth making. The reachability harness has already
refuted `profile` as a *source* (see [shelves.md](shelves.md)); the other six
are unmeasured against each other, and `drawn_by_n` is what makes that
measurable rather than arguable.
