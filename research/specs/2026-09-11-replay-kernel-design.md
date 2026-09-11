# The replay kernel

**Status:** design, approved 2026-09-11. Implementation plan to follow.

## The problem

On 2026-09-11 a replay harness reported that ignoring the stop for ten bars was
worth **+1.335R against the shipping policy's +0.344R**, better on 63.5% of the
same trades, holding in both halves of a split sample. It passed the split, it
passed a shuffled-label control, and it passed a within-interval Simpson check.

It was a look-ahead. During the grace window the trailing stop kept tightening
while exits were forbidden, so the exit at bar ten booked a price the market had
already passed through and left. Fixing that exposed a second one: the trail was
being raised on a bar's own high and then allowed to fill on that same bar,
which protects a trade with information it did not have.

Corrected, the policy scores **+0.014R**. It was never a policy.

### Why the guards did not catch it

Every statistical guard this project uses was applied and every one passed.
**None of them can see a replay that is cheating** - a look-ahead produces a
clean, stable, reproducible result, which is exactly what the guards test for.

### Why it survived in the code

`pyproject.toml` excludes `research` from ruff (`extend-exclude`), and pytest's
`testpaths` is `tests` alone. **The code that produces this project's
conclusions is the only code in the repository with no lint gate and no test
gate.**

The stated rationale is sound and is true of about 100 of the 103 harnesses:
they are written to be read beside their results and thrown away when the
question is answered. But a forward walk is not a scratch script. It is the
function that decides what ships.

### What it has already cost

`research/harness/exits.py` scored `sweep-aware`'s old exit at **+0.099R against
ride's +0.655R** over 30,875 replayed calls, and that measurement is why
`SweepAware` carries `target_multiple=6.0`, `trail_vol=0.5` and
`break_even_at=1.0` **in production today**.

That harness has both bugs. A trailing policy benefits from both; the
fixed-target policy it was compared against barely does. **The comparison that
chose the shipping exit was biased in the direction of the answer it gave.**

## Scope

**In:** one forward-walk implementation inside the package, used by the three
harnesses that walk bars forward, and a re-run of the `exits.py` comparison on
it.

**Out, deliberately:**

* The other 100 harnesses. They do not walk trades forward and this changes
  nothing for them.
* Conditioning-by-default reporting, the live-journal cross-check, and the
  field-liveness audit. Each catches a distinct failure from the same day and
  each deserves its own design; bundling them here would make one spec that
  does four things.
* Any change to what `sweep-aware` ships. This produces the number; acting on
  it is a separate decision with its own evidence.

## Design

### Where it lives, and why that is the whole point

`till_infinity/shared/replay.py`.

Inside the package, so CI lints it and the existing suite covers it. The
harnesses stay in `research/`, stay excluded, stay scratch - they import the
walk instead of writing one.

The boundary being drawn: **a forward walk is library code that happens to be
used by research.** `research/` keeps its exclusion for the scratch scripts the
exclusion was written for.

### The surface

Three things, and no more.

```python
Bar = tuple[float, float, float, float, float]  # ts, open, high, low, close

def walk(
    bars: Sequence[Bar],
    start: int,
    trade: Trade,
    cost: float,
    policy: Mapping[str, Any],
) -> tuple[float, str] | None:
    """R and how it ended - "stop", "target" or "hold" - or None."""
```

`Trade` is a **`Mapping`, not a new dataclass** - the shape the three harnesses
already build, carrying `up`, `level`, `unit`, `risk_vol`, `push_vol` and the
originating `context`. Introducing a type here would make every harness
construct it, which is churn in the scratch layer to no benefit; the kernel
reads the keys it needs and ignores the rest.

**The bar tuple carries `open`, and that is load-bearing.** Its absence is why
gap fills were impossible; its late addition is why `rows[...][3]` silently
turned from close into low in one harness, pricing every hold-expiry exit at the
worst tick of the last bar.

**`cost` is required, not defaulted.** Four of 103 harnesses charge a spread
today. Measured on 2026-09-11, charging zero moves a replayed population from
**-0.015R to +0.348R** - the spread is larger than every regime effect in that
study combined. A zero default is how that omission stays invisible; an argument
with no default is how it stays a decision.

### The fill semantics, stated exactly

These are the rules the two bugs broke, and they are the reason this exists.

1. **Exits are tested against the levels that were resting when the bar
   opened.** The order of prices within a bar is not knowable from OHLC, so the
   only honest sequence is: test the stop and target as they stood entering the
   bar, then let that bar's extreme move them for the next one. Raising the
   trail on a bar's own high and filling on the same bar is a look-ahead wearing
   a trailing stop's clothes.

2. **A bar that opens through a level fills at the open.** For a long, if the
   stop is breached and `open <= stop`, the fill is `open`. Filling at the stop
   pays the trade a price the market never offered - invisible when the stop
   trails just behind price, enormous when a rule lets the stop move while
   forbidding it to fire.

3. **A stop and a target both touched in one bar resolve as the stop.** The
   worse order within the bar, as `exits.py` already assumed.

4. **The spread is charged on both legs**, half on entry and half on exit, so a
   round trip pays one spread.

5. **A policy that suspends the stop must suspend its movement too.** While a
   stop cannot fire, it does not trail. This is rule 1 restated for the case
   that broke it.

### Migration

Three call sites.

* `research/harness/sweepregimes.py` and `research/harness/sweepstops.py`
  already share the corrected walk as of 2026-09-11; this is an import change.
* `research/harness/exits.py` is the real work. It loads bars from a different
  database with a different schema (`multi.db`, `(feed, venue, ts)`) than the
  other two (`research.db`, `(feed, interval, ts)` in **milliseconds**), so the
  loader differences are part of the migration rather than incidental to it.

Bar loading is **not** in the kernel. Sources differ per question and a loader
that tried to cover them would grow a schema registry; what must not differ is
what happens to the bars once loaded.

## Validation

**The re-check is the validation.** Re-run the `exits.py` comparison on the
kernel, split by time as the original was not.

* If ride's exit still wins, the shipped configuration is vindicated, and the
  kernel has been demonstrated on the most consequential result in the folder.
* If it does not, a live misconfiguration has been found - which is worth more
  than the kernel.

Either outcome validates the kernel, which is what makes this the right first
customer rather than the most convenient one.

The result is written into `research/exiting.md` beside the finding it revises,
and `SweepAware`'s docstring - which quotes `+0.655R` and `+0.099R` as the
reason for its exit - is corrected to whatever the re-run says.

## Testing

In `tests/`, covered by the main suite. Each pins a specific failure rather than
a behaviour in general:

1. **The grace look-ahead.** A trade that peaks during a suspended-stop window
   and retraces before the window ends must not return the peak's R. This is the
   +1.335R result as an assertion.
2. **The gap fill.** A bar opening through the stop returns the open's R, not
   the stop's. Constructed so the two differ by a wide margin, since a fixture
   where they nearly agree would pass while broken.
3. **Intra-bar ordering.** A bar whose high would raise the trail above its own
   low must not exit at the raised level.
4. **Cost is not optional.** `inspect.signature(walk)` shows no default for
   `cost` - asserted directly, because the guarantee is about the signature and
   a future edit adding `cost: float = 0.0` would silently restore the very
   omission this exists to stop. Paired with a behavioural check that the same
   trade walked with and without a spread returns different R.
5. **Characterisation.** A fixed fixture of bars and trades, with the expected R
   and exit kind recorded, so a later edit that changes the arithmetic has to
   change the test and say so.

## Risks

* **Making `cost` required breaks every harness that omits it.** Intended:
  those harnesses are reporting gross numbers as if they were net. But it is
  breakage, it lands all at once, and only three call sites are being migrated
  here - the rest do not call `walk` at all, so the blast radius is bounded to
  those three.
* **The re-check may overturn a shipped config.** That is a finding, not a
  failure of this work, and it is handled by writing it up rather than by
  changing the strategy inside this piece of work.
* **The kernel could still be wrong in a way nobody has thought of.** It is one
  implementation rather than a correct one; what it buys is that a fix lands
  once. The characterisation test makes drift visible, not correctness certain.

## What this does not fix

A shared, tested, linted forward walk removes one **class** of error. It does
nothing about pooled figures that reverse when conditioned (four occurrences),
dead fields that quietly carry no data (`run_vol` and `pivot` are identically
zero across 20,000 production outcomes today), or replays that disagree with the
live record and win by default (98% stop against 81% timeout on the same
strategy). Those are the rest of the measurement work and they are named here so
that finishing this is not mistaken for finishing that.
