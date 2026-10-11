---
name: finding-bugs
description: Use when hunting for defects in this repo, reviewing a change, or when a measurement looks surprisingly good - the bug shapes this codebase actually produces, each with a mechanical check, drawn from defects found here rather than from a generic checklist
---

# Finding the bugs this codebase actually makes

Generic review checklists find generic bugs. This repository has a house style
of defect, and it is **not** null-dereferences and off-by-ones. It is
**silent corruption of a measurement**: code that runs, tests that pass,
dashboards that look reasonable, and a number that means something other than
what it says.

Every shape below was found here, most of them in one day. Each has a check you
can run rather than a principle to remember.

## The governing question

> **Is this number a measurement, or does it only look like one?**

Nearly every defect below is a case of that going unanswered.

---

## 1. A record that contradicts itself

**Shape.** Two fields on the same row that cannot both be true.

**Found here.** `best_r` - the furthest a trade ran in its favour - read
exactly **0.0** on 45% of closes, and **34.6% of those closed positive**. A
trade cannot finish in front without having been in front.

**The check.** For every pair of fields with an arithmetic relation, assert it
over the live record:

```python
assert (d.best_r >= d.r_multiple.clip(lower=0)).all()  # it failed
```

Write these as *data* tests, not unit tests. The unit tests all passed.

---

## 2. A cleaning filter that selects on the outcome

**The most dangerous shape in this list**, because the fix for #1 creates it.

**Found here.** Dropping rows whose `best_r` was below their own result looked
like obvious hygiene. It can only ever drop a **winner** - for a loser,
`max(0, r_multiple)` is zero and `best_r` is never below zero. It dropped
**51.9% of winners and 0% of losers**, and the win rate of what survived fell
from 46.1% to 29.2%.

**The check.** Any time you drop rows, print the drop rate **by outcome**:

```python
d.groupby(d.r_multiple > 0).dropped.mean()  # must be flat
```

If it is not flat, the filter is part of the result.

**The tell beforehand.** A filter written against a field that is *itself* the
thing under suspicion. Prefer a flag set **before the outcome exists** -
`excursion_partial` is set at adopt time precisely so that filtering on it
cannot select on the result.

---

## 3. An aggregation that merges some fields and not others

**Shape.** A function that copies state field by field, and a type that grew a
field after it was written.

**Found here.** `dedupe()` merged **7 of 15** `SideStats` fields, silently
dropping `backchecks`, `traps`, four wick statistics and both symmetric-race
counts. Worse than loss: `touches` **was** merged while the outcomes it should
account for were not, so `traps / touches` came out biased **downward** by
exactly the touches merged in - and the wick fields size stops.

**The check.** Compare the fields a function touches against the fields the
type has:

```python
import dataclasses

a, b = T(), T()
for f in dataclasses.fields(T):
    setattr(a, f.name, 2.0)
    setattr(b, f.name, 3.0)
a.merge(b)
assert [f.name for f in dataclasses.fields(T) if getattr(a, f.name) == 2.0] == []
```

Write it against `dataclasses.fields`, never a hand-written list, so a field
added next year is covered on the day it is added.

---

## 4. Computed, published, and read by nothing

**Shape.** A value the code goes to trouble to produce that no decision
consumes. It is not a bug in itself; it is where bugs live undisturbed, because
nothing would notice if it were wrong.

**Found here.** `activity` and `vol_stretch`: **zero** references in trading.
`ensemble_bps`, `forecast_bps`, `garch_bps`: one reference each, **all in
comments**. `Touch.energy`: computed since it was written, read by nothing.
`vol_bps` is used 96 times and every one is as a *unit of measure*, never as a
gate - the desk sizes by volatility and decides by nothing.

**The check.**

```bash
grep -rn "\bthe_name\b" till_infinity/ --include=*.py | grep -v "def \|#:"
```

Two hits means its definition and its serialisation. That is a value nobody
reads.

**And the subtler version.** A value can be published on an object and still
never reach the journal, because the journal context is **hand-assembled**
elsewhere. `Touch.to_dict()` is not what gets written. Check the writer, not
the type.

---

## 5. Two definitions of one concept

**Shape.** The same idea implemented twice, drifting apart, with nothing
comparing them.

**Found here.** `efficiency` existed in `context/trend.py` while a second copy
was being added to `touches.py` - identical formula. `ifvg` in `gaps.py` and
`INVERTED` in MCFL's VOID lifecycle are one object computed in two languages.
**Four** definitions of "displacement" coexist.

**The check.** Before adding a named quantity, grep for the name *and the
formula*:

```bash
grep -rn "sum(abs(" till_infinity/structures/ --include=*.py
```

**And when you find two, measure them before merging them.** `displace` and
MCFL's `DISPLACE_C` both claim "two consecutive one-sided bars" and agree on
**a quarter** of their union over 2.0M bars. Collapsing them would have been
the bug, not the fix.

---

## 6. Constants that must move together, and don't

**Shape.** A threshold in one place, a value chosen relative to it somewhere
else, and nothing linking them.

**Found here.** `VOID_BODY` was 0.70; a test fixture padded with 66.7%-body
bars, safely under it. `PUSH_BODY` then moved to 0.65, `VOID_BODY` follows it
by design, and the padding became a void. **Both branches were green; main
broke on the merge.**

**The check.** Import the constant rather than restating it - `VOID_BODY =
PUSH_BODY`. And in tests, never pick a fixture value that sits *near* a
threshold; pick one that is obviously on one side of any threshold anyone might
choose next.

**The shape to fear:** two PRs, each green, that interact. CI cannot see it.

---

## 7. In-memory state that no restart survives

**Shape.** A dict or deque built in `__init__`, never restored, read as though
it were history.

**Found here.** `_best`, `_worst`, `_best_at`, `_worst_at` on the trading
service - and `_reach` returns `0.0` for a ticket it cannot find, which its own
docstring admits "is how every close in the book's history once recorded
`best_r` of exactly 0.000". Separately, a capped `deque` came back from a
restore **unbounded**, and `risk_money` came back `0.0` on 839 of 1,486
positions.

**The check.** For every `self._x = {}` or `deque(maxlen=...)`, ask what reads
it after a restart and what that read returns. If the answer is a plausible
number rather than an error, it is this bug.

**Production deploys on every merge to main**, so "across a restart" is not a
rare path - it is most days.

---

## 8. A docstring that makes a claim no test pins

**Shape.** Prose asserting a property that was never measured.

**Found here.** The zone said "price inside this band is touching the level in
any sense the data can distinguish". That is a **coverage claim** made without
a coverage measurement - two sigmas is 95.4% of a Gaussian, and nothing had
checked that touches are Gaussian. Measured later: the band covers **97.6-98.6%**
where 90% was asked.

**The check.** Read docstrings as assertions. Any sentence with a number, a
rate, or "is enough to" either has a test or is a hypothesis wearing prose.

---

## 9. An arithmetic ceiling nobody noticed

**Shape.** A statistic whose range is bounded by its own construction, swept
over values it cannot reach.

**Found here.** A rolling z-score over `N` points cannot exceed
`(N-1)/sqrt(N)`, so `z > 2` is **impossible** below `N = 6` - and a sweep of
thresholds 1 to 4 over windows 2 to 36 spent most of its cells measuring
nothing.

**The check.** Before sweeping a parameter, derive its attainable range. If
cells are empty or identical, that is the ceiling, not the data.

---

## 10. The result that is too good

**Shape.** Uniformity. Every cell positive, every arm agreeing, a clean
monotone across a grid.

**Found here.** The regret model reported a positive correction for **every
strategy at every reward** - 26 of 40 cells. That uniformity was the bias in
#2, and it is what gave it away. Separately, `cycle-scalp` showed a mean R of
**+3.35** against a median of -0.27, driven by a single row with
`r_multiple = 2390`.

**The check.** When a result is uniformly favourable, look for the mechanism
that could only produce favourable results. And always print a **median beside
every mean** - they disagreed by a factor of twelve above.

---

## 11. A test that asserts nothing

**Shape.** A loop over a possibly-empty collection, or an assertion that holds
vacuously.

**Found here.** `for one in found: assert ...` with no `assert found` above it
passes perfectly when the fixture produces nothing.

**The check.** Every loop-assertion needs `assert found` first. Every new test
should be seen to **fail** once before it is trusted.

---

## 12. A correction derived from the thing it corrects

**Shape.** A statistic is contaminated, so a correction is subtracted. The
correction is computed from the same quantity it is meant to clean, so it
cannot be smaller than the contamination it is estimating, and subtracting it
leaves nothing **by construction**.

**Found here.** Measuring the Hurst exponent of realised variance needs the
estimation noise removed from the second moment of log-volatility increments.
The noise was estimated by splitting each window in half and comparing the
halves - but adjacent non-overlapping windows are *exactly what the lag-1
moment is taken over*, so the "noise" was the lag-1 moment plus the volatility's
own variation. Every cell returned `nan` at "noise 100%". It read as a numerical
problem and was a logical one.

**The check.** Write down what the correction is a function of. If it shares a
term with the statistic, it is not independent of it. The fix is a handle that
varies the nuisance while **holding the signal fixed** - here, interleaving
alternate bars so two estimates cover the same window of the same time, which
makes their spread pure estimation error. And give the correction a
**prediction** it can fail: the density exponent came out 0.66-1.35 against
sampling theory's 1, which is the only reason the floor is believable.

---

## 13. A bar count inside a time-portable measurement

**Shape.** A window, span, decay or threshold stated in bars, in code that is
run across timeframes. It then means a different thing on every one, and
comparisons across them are comparing different estimators.

**Found here.** Three times. `volatility_ceiling.py` compared `har (5/22/110)`
across 15m and 1d, where it is 1.25h/5.5h/27h on one and 5d/22d/110d on the
other, and reported that HAR-Parkinson wins intraday and loses daily - a result
that vanished on conversion. A noise floor was derived as `4/n` from
`Var(log RV) ~ 2/n`, which claims the same four hours of the same market is five
times noisier when sampled at 1h than at 15m. And a 5-day trading week was
hardcoded where crypto has 7.

**The check.** Grep the module for integer windows and ask what each is in
**hours**. `statespace/__init__.py` carries the rule and `inputs.py` the
conversion - `bar_hours` and `coverage` infer both from the series' own
timestamps, so nothing needs a per-instrument constant. A span that cannot be
stated as a duration is a span that cannot be compared across timeframes.

---

## What has actually caught things here

Ranked by what they found, not by how they sound:

1. **`test_no_published_feature_is_near_constant`** - caught **two unrelated
   defects on the same feature, hours apart**: a formation biasing the level
   book, and a filter widening every zone. Neither looked like what it was;
   both surfaced as a published statistic collapsing. **A test that asserts a
   distribution has not collapsed catches the failures that do not announce
   themselves.**
2. **Widening the sample.** Sixteen instruments to twenty-nine killed the only
   positive cell in a sixty-cell sweep, and cost one rerun.
3. **A matched control.** The duty-cycle control has killed every pause rule
   proposed here. The Huberised arm is what made a particle-filter null
   interpretable rather than ambiguous.
4. **Reading the code instead of the name.** `CONFIDENT_TOUCHES` sounds like
   the shrinkage parameter and affects no number at all; the shrinkage is
   `PRIOR_WEIGHT`. `fade-to-value` turned out to already trade origins, which
   changed the question before any measurement ran.
5. **Giving the fix a number it can fail.** Both noise floors above produced
   plausible-looking output; the one that was wrong failed its own stability
   criterion and the one that works predicted `p = 1` and measured it. A
   correction with no falsifiable consequence is a parameter.
6. **Printing the number.** A filter reported `slope = 0.0000` forever and
   looked entirely healthy, because the covariance it needed to learn from was
   gated out of existence. The tests passed. Printing it took one line.

## The one habit worth more than the list

**When a measurement surprises you, suspect the measurement first.** Every
entry above was found that way, and the time between "this looks great" and
"this is a filter artifact" is usually one `groupby`.
