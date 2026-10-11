# Counting the informatory pairs: which conditions can the data actually see?

The pre-test from Kretschmer et al. (Nature Methods, 2026), run on 2026-10-11.
It was the first item in `statespace-from-papers.md`'s "what to build
first", on the grounds that it needs no model and decides whether several open
ideas can work at all. It took one harness and it answered five questions.

Harness: `research/ideas/informatory_pairs.py`.

## The question

Predicting retention times across laboratories, the paper asks before building
anything: for each **pair** of compounds, does their retention *order* ever
change between systems? 93.8% of pairs never change order, so only 6.16% can
carry any information about the system - and on the rest, a condition-aware
model cannot beat a condition-agnostic one. That is knowable without training
either.

Every idea here that conditions on something - regime gating, per-instrument
models, session thresholds, volatility splits - is a bet that orderings change
between conditions. This measures the bet directly.

An "item" is a **decile bin of a feature** (the cumsum `z` over the window),
because our features are continuous and no observation recurs under two
conditions. Bins come from the pooled distribution so a bin means the same thing
everywhere. The "retention time" is the mean outcome in that bin. Ten bins, 45
pairs, six window/horizon combinations, five condition types.

Two guards, and the measurement is worthless without them:

* a pair counts as **resolved** in a condition only when its two bin means
  differ by more than **two standard errors** of the difference - the paper's
  ten-second rule, which exists so the comparison is not of estimation error;
* the **noise floor** is the same count with conditions replaced by *random
  splits of one pool*, which have no condition difference by construction, and
  with the same number of splits as the condition has levels.

The noise floor came back at **0.0% in every cell**, so the control behaves and
the shares below are not a flip rate manufactured by noise.

## Answer one: direction cannot be ordered at all

| window / horizon | signed pairs orderable | size pairs orderable |
|---|---|---|
| 1h / 4h | **0/45** | 33/45 |
| 1h / 24h | **0/45** | 20/45 |
| 4h / 4h | **1/45** | 34/45 |
| 4h / 24h | **6/45** | 20/45 |
| 24h / 4h | **1/45** | 20/45 |
| 24h / 24h | **5/45** | 15/45 |

Before any condition is involved, the feature's bins **cannot be put in order by
their mean signed outcome**. At most six of forty-five pairs are separable at
two standard errors, and in two cells not one of them is.

This is the strongest form the direction result has taken here, because it needs
no model, no horizon tuning and no cost line. There is no ordering for a model
to learn. Every directional candidate this desk has refuted was refuted after
fitting something; this says the map does not exist to be fitted.

Magnitude, by contrast, orders fine: 15 to 34 pairs of 45.

## Answer two: which conditions change the magnitude ordering

Readable cells only - a share computed off fewer than eight resolved pairs is
not a share, and the first run of this harness duly printed "100.0%
informatory" off a single comparison before that gate existed.

| condition | cells | informatory | range | excess over noise |
|---|---|---|---|---|
| **volatility** | 6 | **47.1%** | 22-70% | +47.1% |
| **session** | 2 | **23.4%** | 19-28% | +23.4% |
| instrument | 6 | 5.1% | 0-13% | +5.1% |
| timeframe | 2 | **0.0%** | 0-0% | +0.0% |
| era | 2 | **0.0%** | 0-0% | +0.0% |

**The level count works against this conclusion, which makes it stronger.** More
levels means more chances for some pair of them to disagree, so a five-level
condition should show a *higher* informatory share than a three-level one for
purely mechanical reasons. Instrument has five levels and reads 5.1%;
volatility has three and reads 47.1%. The mechanical bias runs the wrong way for
the result it would have to explain.

## What this answers, without building anything

**The rank-then-map architecture's premise holds.** Its whole bet is that a
model can be fitted across instruments and resolutions because the *ordering*
transfers even where the values do not. Instrument reads 5.1% informatory and
timeframe reads 0.0% in every readable cell - so the orderings do transfer, and
one model spanning all five instruments and both resolutions is viable. The
corollary is sharper: **per-instrument and per-timeframe models buy almost
nothing**, and this desk has several.

**Volatility is the condition worth gating on**, at 22-70% across every cell -
the only one that is strongly informatory everywhere. That supports the
regime-gated idea from JRFM 19:801 specifically where it conditions on
volatility, and it is also the condition this desk already has the best handle
on, since magnitude is the one quantity measured as forecastable here.

**Session carries real information too**, at 19-28%, which is consistent with
the calendar result already measured (volatility runs 2.42x on a scheduled
print and 0.79x in the two hours before).

**Non-stationarity is not the obstacle for this map.** Era - first against
second half of the sample - reads 0.0% in every readable cell. The feature's
ordering of magnitudes is the same in 2010-2018 as in 2018-2026. That is worth
knowing before reaching for walk-forward refitting, which is the usual response
to a non-stationarity worry and which this says would buy nothing here.

## What it does not say

* **One feature.** This is the cumsum `z`; another feature could order
  differently, and the harness takes a feature as a parameter for that reason.
* **Era is two halves of a 2010-onwards window**, not a long-run claim. The
  files reach back to 1971 but most of that is vendor reconstruction - see
  `slope-fade-in-time.md`, where it manufactured a result.
* **Informatory is not profitable.** A pair whose order changes between
  volatility regimes says a conditional model *can* differ from an unconditional
  one, not that the difference earns anything after costs. It removes ideas
  rather than confirming them, which is what a pre-test is for.
