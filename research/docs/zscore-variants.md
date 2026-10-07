# Four variants of the z-score, and whether a model beats them

**Measured 2026-10-07**, after [`zscore-window.md`](zscore-window.md) showed that
a z-score's reach is decided by its window. Five questions: the four variants
proposed off that result, and "can ML predict the numbers".

Code: [`zscore_variants.py`](../ideas/zscore_variants.py),
[`zscore_ml.py`](../ideas/zscore_ml.py). 218,440-220,029 4h bars, sixteen
development instruments.

## Summary

| | verdict |
|---|---|
| 1. normalise by the ceiling | **the normalisation does not do what I claimed** - but it is how the best cells in the whole z study were found |
| 2. term structure across windows | **the one that works.** Alignment matters more than any single window's level |
| 3. volatility z | **nothing.** The ATR already knows it |
| 4. cross-sectional z | **IC zero**, and the decile effect looks like composition, not signal |
| 5. gradient boosting | **finds something real and small**, and loses to a two-condition hand filter |

## 1. Normalising by the ceiling does not make a threshold comparable

The proposal was that dividing by `(N-1)/sqrt(N)` would make a threshold the same
event at every window. **It does not.** The share of bars past each fraction of
the attainable maximum:

| N | > 0.4 | > 0.6 | > 0.8 | > 0.9 |
|---:|---:|---:|---:|---:|
| 4 | 70.5% | 50.6% | 29.2% | 17.1% |
| 8 | 49.4% | 21.7% | 5.6% | 1.6% |
| 12 | 36.2% | 10.7% | 1.7% | 0.4% |
| 20 | 20.1% | 3.1% | 0.26% | 0.04% |
| 36 | 6.4% | 0.39% | **0.01%** | 0.00% |

Normalising fixes **reachability** - every window can now reach 1.0 - and leaves
**rarity** exactly as window-dependent as before, in the opposite direction. A
raw `z >= 2` goes from 0.57% of bars at N = 6 to 12.7% at N = 36; a normalised
`>= 0.8` goes from 29.2% at N = 4 to 0.01% at N = 36. Neither is a constant
event. My own recommendation was wrong on this point.

What the normalised form is good for is **dialling rarity deliberately**, and
that is where the largest separations in the whole z study live. Forward move at
h = 3, in ATR:

| N | cut | n (high side) | high | low | spread |
|---:|---:|---:|---|---|---:|
| 8 | 0.8 | 6,187 | +0.089 [+0.053, +0.126] | -0.064 [-0.102, -0.028] | **0.153** |
| 12 | 0.8 | 1,787 | +0.139 [+0.073, +0.209] | -0.111 [-0.175, -0.046] | **0.250** |
| 20 | 0.6 | 3,406 | +0.137 [+0.077, +0.196] | -0.087 [-0.143, -0.030] | **0.224** |
| 36 | 0.4 | 7,249 | +0.098 [+0.053, +0.144] | -0.061 [-0.112, -0.012] | **0.160** |

Four cells with **both tails clear of zero** - the raw-threshold tables never
produced that. The spread rises monotonically with both the cut and the window.
So the lesson is not the normalisation; it is that **rarity is the variable**,
and the normalised form is the convenient handle on it.

## 2. The term structure is the one that works

The same fast reading inside different slow ones. 8-bar against 36-bar, both
ceiling-normalised, forward move at h = 3 in ATR:

| fast \\ slow | slow high | slow mid | slow low |
|---|---:|---:|---:|
| **fast high** | **+0.128** (5,836) | +0.022 (33,387) | - (0) |
| fast mid | -0.024 (1,413) | +0.018 (141,291) | -0.081 (1,322) |
| **fast low** | - (0) | -0.009 (30,937) | **-0.057** (5,507) |

**A high fast reading is worth +0.128 inside an extended slow window and +0.022
inside a flat one** - nearly six times the difference, from the same fast number.
The level at any one window cannot say which of those it is, which is the whole
point of the question.

The 4/36 pair says the same more weakly (+0.058 aligned against +0.013 not), and
the disagreeing corners are **empty by construction**: the 8-bar window sits
inside the 36-bar one, so a high 8-bar reading cannot coexist with a low 36-bar
reading at these cuts. Alignment is not a filter that can be inverted.

## 3. Volatility z says nothing the ATR has not already said

The same statistic on the bar's log range, scored against the **forward realised
range over the current ATR** - a sizing number, not a direction.

| N | IC vs forward range | top quintile | bottom quintile | ratio |
|---:|---:|---:|---:|---:|
| 4 | +0.040 | 1.860 [1.844, 1.877] | 1.735 [1.721, 1.749] | 1.07 |
| 6 | -0.039 | 1.769 | 1.812 | 0.98 |
| 12 | -0.008 | 1.807 | 1.786 | 1.01 |
| 36 | -0.006 | 1.808 | 1.780 | 1.02 |

A ratio of 1.0 means the top and bottom quintiles of the volatility z-score are
followed by **the same forward range**. The ATR in the denominator has already
absorbed the information, and the sign of the IC is not even stable across
windows. This was the variant with the best story - the desk's loss is stops
inside the instrument's own noise, so a vol-state reading would feed sizing - and
it is the emptiest of the four.

## 4. Cross-sectional z: the IC is zero and the tail looks like composition

Each instrument standardised against the other fifteen at the same bar.

| lookback | n | IC | IC shuffled | top decile | bottom decile | spread |
|---:|---:|---:|---:|---|---|---:|
| 1 | 220,029 | -0.0040 | +0.0005 | +0.057 [+0.034, +0.080] | +0.009 [-0.013, +0.030] | 0.048 |
| 4 | 202,681 | -0.0035 | -0.0061 | +0.048 [+0.021, +0.075] | +0.000 [-0.025, +0.028] | 0.048 |
| 12 | 156,599 | +0.0003 | -0.0028 | +0.054 [+0.020, +0.087] | +0.006 [-0.029, +0.037] | 0.048 |

The IC is zero against a null that is also zero. The top decile does clear zero -
but the bottom decile sits at **zero rather than negative**, which is not what a
signal looks like, and the spread is **0.048 to three decimals at every
lookback**, from one bar to twelve. A statistic that gives an identical answer
whether it looks back one bar or twelve is not reading the lookback; it is
reading something constant about which instruments sit in the tail. Crypto moves
several times as far as FX in ATR terms, so "top cross-sectional z" is partly
"this is a crypto bar". **Not believable without a per-family control**, which is
the next thing to run if this is pursued.

## 5. Can a model predict it?

Gradient boosting (sklearn `HistGradientBoosting`) on twenty features - the
ceiling-normalised z at six windows, three speeds, the term structure, body,
body in ATR, range in ATR, relative ATR, wicks, direction. Target: the 3-bar
forward move in ATR. **Split by date**, train to 2024-04-25, test on the
remainder, with the boundary purged by the horizon; a random split would put the
same overlapping move on both sides of it.

| | IC | spread, top/bottom 10% | 5% | 1% |
|---|---:|---:|---:|---:|
| always the mean | - | 0.000 | 0.000 | 0.000 |
| best single feature | +0.0063 | -0.005 | -0.005 | -0.005 |
| **gradient boosting** | **+0.0045** | **+0.056** | **+0.063** | **+0.128** |
| same model, y shuffled | -0.0004 | -0.003 | +0.007 | +0.006 |

**It finds something.** The shuffled-target control - the same model, the same
capacity, the same features, `y` permuted within symbol - is flat at every
sharpness, so the +0.056 is not what this much capacity extracts from noise. And
it sharpens the right way: 0.056 at the decile, 0.128 at the top and bottom 1%.

**Three reasons it is not an edge.**

1. **No interval clears zero.** The top 1% is +0.060 [-0.060, +0.183] on 655
   bars.
2. **The walk-forward IC is zero while the spread is not.** Refitting each
   calendar year: IC positive in **1 of 6 years** (mean -0.0008), spread positive
   in **6 of 6** (+0.022 to +0.102, mean +0.050). Both are true and they say the
   model's ordering is wrong through the middle and right at the edges - the same
   non-monotonicity the single-feature study found, now inside the model.
3. **It loses to a hand filter.** The best model cell is a 0.128 spread on the
   extreme 1%. `|z| >= 2` **and** a 70% body - two conditions, no fitting -
   reached 0.21, and normalised `z >= 0.8` at N = 12 reached **0.250 with both
   tails clear of zero**. Twenty features and 300 boosting rounds did not beat
   two inequalities.

That last point is the useful one. On this problem the model is not finding
structure a person could not state; it is finding a blurrier version of it,
because it optimises squared error over every bar while the hand condition goes
straight to the rare corner where the effect lives.

## Followed up in

[`zscore-ml.md`](zscore-ml.md), which changes the model's objective as this file
suggested. Training on the rare corner does sharpen it to the best cell in the
study (+0.257, the only interval here that clears zero) - and then the same
features put through **the question a trade asks**, "did price reach +1 ATR
before -1 ATR", find **nothing at all**: 48.7% against a base rate of 48.6%.

## What to do with this

* **Keep the term structure.** It is the only variant that adds something the
  level does not have, and the mechanism is legible.
* **Keep rarity as the dial**, through the normalised form, and stop reading raw
  thresholds across windows.
* **Drop the volatility z** - the ATR has it.
* **Do not pursue cross-sectional z** without a per-family control first.
* **A model is the wrong tool here** until there is something to combine that is
  bigger than the noise. It cost nothing to find that out and it is worth
  recording, because "we should try ML on it" is the default suggestion for any
  table like these.

And the standing caveat: every number here is a conditional mean of a forward
move, with **no entry, stop, spread or slippage anywhere in it**. The best cell
in this file is 0.25 ATR over three 4h bars. The zone study is the measured
demonstration of how little of that survives a stop.
