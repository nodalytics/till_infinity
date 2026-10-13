# Does a panel-denoised volatility move the clock or the ladder

[The panel estimator](statespace-panel-volatility.md) removed **4.3%** of
out-of-sample log-volatility forecast error on equities at a pooled `t` of
`+4.85`, and **3.1%** on the FX crosses. It said plainly that whether this moves
the clock, the ladder or sizing was not measured. This measures two of them.

**The answer is no, and a rotation null is the only reason that is known.**

The harness is `research/ideas/panel_clock_ladder.py`.

## Both scorers are reused, not reimplemented

* the **clock** is `Driven(build, lever, clock=factor)` from
  `clock_levers.py`, scored by the member's own log-likelihood on the second
  half;
* the **ladder** is `Fractional(modes=5)` against a single `Reverting`, from
  `rough_volatility.py`, scored the same way.

A result on a fresh scorer would not be a result about the clock.

## Two configuration mistakes, both caught before the result

**The lever was wrong.** A volatility clock belongs on `level_wander`, whose
variance grows like `q * dt`, not on `jerk`, which grows like `q * dt^5`.
Checked against a planted clock on a series whose volatility quadruples half
way through, base swept on the null in every case:

| lever | null | the true clock | the same clock reversed |
| --- | ---: | ---: | ---: |
| **level** | +3830.45 | **+33.06** | **-1298.40** |
| reverting | +3713.40 | -93.13 | -28.96 |
| jerk | +3313.00 | -31.19 | -15.44 |

Only `level` rewards a correct clock. The first version used `jerk` and would
have reported a null from the lever alone. The asymmetry is worth keeping: a
correct clock is worth `+33` and a reversed one costs `-1298`, so this scorer is
far more sensitive to a misleading clock than a helpful one.

**And the window was wrong.** `rough_volatility.WINDOW` is **6**, so the
published ladder result is six-bar realised volatility with a declared variance
of `1/12`. A first run at 24 improved a ladder that was itself *losing* to a
single OU by `-27.6` nats, which is not the ladder this is about.

## The blend is nested, and it still was not enough

The denoised series is `(1-w) * own + w * (a + b * factor)` with `w` swept on
the training half. `w = 0` **is** the own-only arm, so a null result should be
exactly zero rather than a small negative needing interpretation.

| | rows | median nats | best | helped | baseline's own value |
| --- | ---: | ---: | ---: | ---: | ---: |
| traded, ladder | 20 | +35.6 | +75.6 | 20/20 | -16.1 vs one OU |
| traded, clock vs **profile** | 20 | **-22.1** | +19.4 | 3/20 | **+98.6** vs no clock |
| equities, ladder | 21 | +24.5 | +39.3 | 21/21 | -7.2 |
| **traded, rotated, ladder** | 20 | **+104.4** | +179.2 | 20/20 | -46.3 |
| **equities, rotated, ladder** | 21 | **+40.1** | +91.7 | 21/21 | -10.2 |
| **generated, ladder** | 36 | **+13.4** | +65.2 | 36/36 | -5.9 |

**The rotation null gains more than the real data**, and `w > 0` was chosen on
every instrument even when the factor is pure noise - including on the
synthetics, which have no factor to borrow at all.

### What the artefact is

Blending own log-volatility toward *any* smooth series **reduces the observed
series' variance**, and the declared measurement variance is fixed at
`1/(2 * WINDOW)`. A smoother series fits a fixed-variance filter better, so the
likelihood rises wherever the second series came from.

The nested `w = 0` design did not protect against it because the smoothing helps
**in sample too** - it is not overfitting, it is a real change to the series -
so the training sweep always prefers a blend.

### Read against the right baseline, the factor is worse than noise

A rotated factor carries the identical smoothing artefact, so the difference
between the two isolates the information:

* **ladder**: real `+35.6` against rotated `+104.4` - the real factor is **69
  nats worse than noise**;
* **clock**: the established profile clock earns `+98.6` nats on its own, and
  adding the panel term costs `-22.1` where a rotated factor costs only `-5.4`.

So the panel's information does not reach either scorer, and on the clock it
actively interferes with a clock that works.

## What this does and does not say about the panel estimator

It does **not** retract it. That measurement used the factor as a **regressor**
against a HAR baseline on out-of-sample forecast MSE, and its rotation null came
back properly negative at `-3.19` against the real `+4.85`. That design was
sound and this one is a different question with a different failure.

What it says is that **a 3% to 4% better volatility forecast does not transfer
to the two places this desk earns from volatility.** The clock is driven by
time-of-day profile and the ladder by long memory in log-volatility; neither is
short of a point estimate of current volatility, which is what the panel
improves.

## What to use

* **Judge a blend against a rotated blend, never against the unblended
  series.** Smoothing is worth more to a fixed-variance filter than information
  is, and the comparison that does not control for it reads `+104` on noise.
* **Put a volatility clock on `level_wander`.** The lever decides whether the
  measurement can see anything.
* **Match a published harness's window before claiming to have moved it.** At
  `WINDOW=24` the ladder loses to a single OU, so there is nothing to move.

## Related

* [The panel estimator](statespace-panel-volatility.md) - the forecasting
  result this tried and failed to spend
* [Clock levers](statespace-clock-levers.md) - the `+98.6` profile clock this
  measures against
