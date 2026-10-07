# Take the sign away and the model works: magnitude, not direction

**Measured 2026-10-07.** Asked as "for the z-score ML, can we remove the sign +
or - and see if it still sees something". It does - thirty-three times better -
and the answer reframes everything in
[`zscore-window.md`](zscore-window.md), [`zscore-variants.md`](zscore-variants.md)
and [`zscore-ml.md`](zscore-ml.md).

Code: [`zscore_sign.py`](../ideas/zscore_sign.py). Same features, same date split
(train to 2024-04, boundary purged), same 218,440 4h bars over sixteen
instruments. The target is the 3-bar forward move **over the ATR at the bar**, so
everything below is already net of the ATR.

## The result

| model | IC | decile spread | top 1% spread |
|---|---:|---:|---:|
| signed move (baseline) | +0.0024 | +0.043 | +0.173 |
| **\\|move\\|** | **+0.0782** | **+0.258** | **+0.393** |
| **\\|move\\| from \\|features\\|** | **+0.0792** | **+0.261** | +0.320 |
| \\|move\\|, shuffled target | +0.0087 | +0.033 | +0.071 |

**Stripping the sign from the *features* as well costs nothing** - +0.0792
against +0.0782. Whatever the model is using, none of it encodes direction. That
is not a small detail: it means every signed result in the other three files was
being read off a model that was not predicting the thing it was scored on.

The deciles are monotone from end to end:

| decile | n | mean \\|move\\|, in ATR |
|---:|---:|---|
| 1 | 6,553 | 0.756 [0.730, 0.783] |
| 2 | 6,553 | 0.806 [0.782, 0.830] |
| 4 | 6,553 | 0.854 [0.828, 0.881] |
| 6 | 6,553 | 0.896 [0.873, 0.921] |
| 8 | 6,552 | 0.928 [0.903, 0.955] |
| 10 | 6,553 | **1.013** [0.976, 1.054] |

Ten deciles, no inversion, and the ends nowhere near each other - a **34%
difference in expected absolute move**, against a shuffled control whose own
spread is 0.033.

## It is not one feature wearing a heavier coat

The signed problem was lost to two inequalities, so the same question has to be
asked here before any credit is given:

| | IC | decile spread |
|---|---:|---:|
| **model** | **+0.0782** | **+0.258** |
| `z36` alone | +0.0212 | +0.085 |
| `range_atr` alone | +0.0148 | +0.076 |
| `body_atr` alone | +0.0146 | +0.007 |
| `z8` alone | -0.0066 | -0.004 |
| `atr_rel` alone | **-0.0441** | -0.078 |
| shuffled control | +0.0087 | +0.033 |

**The model beats the best single feature by roughly four times on IC and three
on spread.** That is the opposite of the signed problem, and it is the first
result in this line of work where a model earns its keep.

## The single most informative feature points the wrong way round

`atr_rel` - the 14-bar ATR over its own 100-bar mean - carries the **largest
single-feature |IC| in the table, and it is negative**. When ATR is high against
its own recent average, the **ATR-normalised** forward move is *smaller*.

Volatility mean-reverts, so a trailing ATR **over-estimates** forward magnitude
exactly when it is already elevated, and under-estimates it when it is
depressed. A stop set at a fixed multiple of ATR is therefore systematically too
wide in fast conditions and too tight in quiet ones - the opposite of what it
feels like it is doing.

That is one number, it is mechanical, and it is a direct correction to stop width
and position size. It needs no edge to be worth having.

## Why this makes sense of everything before it

The diagnostic, run on the *signed* model's own output:

| | IC |
|---|---:|
| its prediction against the signed move | +0.0024 |
| **its \\|prediction\\| against \\|move\\|** | **+0.0097** |

The signed model was tracking magnitude better than direction all along. Which
explains the result that killed the line in [`zscore-ml.md`](zscore-ml.md):
knowing **how far** price will travel but not **which way** is worth exactly
nothing on a symmetric +-1 ATR barrier bet, and the barrier classifier duly
returned 48.7% against a 48.6% base rate.

It also explains why the conditional means looked real while the trades did not.
A rule that selects bars with a large forthcoming move raises `E[|move|]`, and
`E[move]` with it if the sample happens to lean one way - but it does not move
the odds of touching one barrier before the other. Every table in
`zscore-window.md` is measuring the first thing.

## What to do with it

* **This is a sizing model, not a signal.** It belongs where stop width,
  target distance and position size are decided, not where direction is.
* It is **incremental to ATR by construction**, since the ATR is already in the
  denominator of its target. That is what makes it worth having at all - the
  desk's loss has been traced four independent ways to stops sitting inside the
  instrument's own noise, and this predicts the part of that noise the ATR is
  missing.
* **Before anything is built on it**: it has been fitted and scored once, on the
  development instruments, on one horizon, at 4h. The next steps are a
  walk-forward refit, the held-out instruments, and the 1h and 1d horizons -
  none of which have been run.
* **`atr_rel` on its own is usable now** and needs no model.

## What this does not say

Nothing here predicts direction. The signed IC is +0.0024 and the barrier test
found nothing, and both remain true. A magnitude model does not make a losing
rule profitable; it makes the stop on an existing rule better placed.
