# One input can disable a model without breaking it

A day's worth of chasing one number, kept because the failure is invisible by
construction and this repository has now produced it twice.

## What happened

`structures/breaking.py` predicts whether a level gives way, from
`approach_vol`, `depth_vol` and `slowing`, standardised by a running mean and
variance per input. On 2026-09-03 two slope features were added on a measured
lift (see [slopes.md](slopes.md)), and a watcher was armed to report when the
fitted weights moved.

Within an hour it reported `approach_vol` moving from **-0.313 to -0.034** —
for a feature that had been learning for weeks and whose meaning had not
changed.

The first hypothesis was collinearity: two new inputs stealing weight from a
feature they duplicate. It was measured and refuted. Over 2,531 resolved
touches every pairwise correlation among the five inputs is below 0.12, and
`slope` against `approach_vol` is **-0.026**. The features are near-orthogonal,
which is what they should be.

Then the standardiser's own state was read out:

```
approach_vol      1.3628
depth_vol         0.6170
slowing     141,380,329.7572      <--
slope             0.1755
prior_slope       0.1864
```

`slowing` is a ratio — the speed of the last few bars over the speed of the few
before them — and `_slowing` guarded only `before <= 0`. That catches exactly
zero and nothing near it, so a near-zero denominator sent the feature to
astronomical values. Its running mean had reached **141 million**.

## Why that disables a model rather than breaking it

Nothing raises. Nothing logs. Every prediction still returns a number in
[0, 1], the model still reports itself warm, and the gate downstream still
acts on it.

What happens instead is arithmetic. All five inputs share one standardiser, so
`slowing`'s variance sets the scale for its own column and its extremes arrive
often enough to keep moving the shared statistics. Standardised, `slowing`
collapses towards zero for every ordinary value — the feature is *present and
mute* — and every other weight rescales each time a new extreme lands, which is
what the watcher caught.

**The feature with the largest weight was contributing nothing, and its
neighbours could not settle.** Neither is observable from the model's output.

## The fix that was not a fix

`slowing` was capped at 10.0. A leg ten times faster than the one before it is
already an extreme reading, so nothing a linear model could use was discarded.

**It could never take effect.** `Scaler` is plain Welford with no decay:

```
mean += (value - mean) / n
```

With `n` at 5,256 and a mean of 141,380,329, one clamped observation moves the
mean by `(10 - 141M) / 5256`, about -26,900. Solving for the mean to reach a
sane figure needs on the order of **1e11** further observations. At the desk's
rate that is not a long time, it is never.

So the input was corrected and the statistics describing it were not. The
commit read as done, the tests passed, and the model was in exactly the state
it had been in. **This is the same defect the fix was addressing, produced
inside an hour by the person who had just written about it.**

## What actually fixed it

A `RECIPE` constant naming what the model was trained on. When it differs, the
model is thrown away on the next resolution rather than standardising new
inputs against statistics gathered under an old meaning.

Adding an input was already handled — `Logistic` and `Scaler` rebuild on a
length change. **Re-meaning one was not**, and that is the gap.

Confirmed from the saved state rather than from a log line, because the log
line fired inside a container that has since been recreated and `docker logs`
does not survive that:

| | before | after |
| --- | ---: | ---: |
| `slowing` running mean | 141,380,329 | **2.2996** |
| scaler n | 5,256 | 896 |
| logistic seen | 1,855 | 722 |
| saved recipe | absent | matches the build |

Every per-feature mean now sits in the same range — 1.44, 0.67, 2.30, 0.21,
0.27 — which is what a usable standardiser looks like, and is the first time
this model has had one. `slowing` is now the largest weight, which is the
point: before the cap it could neither contribute nor let anything else settle.

## Two traps found on the way, both specific to slotted dataclasses

* **`__setstate__` with a bare `super()`** raises `TypeError: super(type, obj)`
  **at unpickling time only**. A `slots=True` dataclass is a new class object
  built after the method bodies compile, so the `__class__` cell that bare
  `super()` needs points at a class that no longer exists. Name the base
  explicitly.
* **`Breaks.recipe` is the slot descriptor**, not the field default. Comparing
  an instance against it never matches, so the model restarted on *every*
  restore - a fix that fails in the opposite direction and just as quietly.
  `RECIPE` is a module constant for that reason.

The check ended up in `observe`, which runs once per resolved touch, rather
than in the pickle path.

## What to take from it

1. **Bound every ratio at the point it is computed.** A guard against a zero
   denominator is not a guard against a small one, and this codebase has
   `slowing`, `forecast_ratio`, `vol_stretch` and `reward_to_risk` in that
   shape. Only one has been checked.
2. **Read the standardiser, not just the weights.** The weights are the
   symptom; the running statistics are where a broken input is visible. Nothing
   was looking at them until an hour ago.
3. **Fixing an input means invalidating what was learned from it.** The two are
   one change. `RECIPE` makes that explicit for this model and no other model
   here has an equivalent.
4. **A watcher on the weights paid for itself in under an hour.** It was armed
   to see whether the new slope features earned their place and instead found a
   feature that had been mute for weeks.
