# A range-based volatility estimator beats close-to-close on 371 of 392 equities, and an AUC of 0.805 is worth nothing

Asked on 2026-10-14: *go through the different markets and their candles
yourself and see if you can find things too, some help improve statespace by a
lot, hope for an auc above 0.80, and i know we can do it* - then *we can achieve
auc of >0.80 in direction*, *we have done it in volatility*, *we might just be
thinking about the whole directional thing the wrong way or something's
missing*, and *directional values might also lie in the tails*.

Twenty-four scale-free window features against thirteen targets across six
market families, including the **four hundred and seventy-two equities** in the
cache that nothing in this desk's research had ever loaded.

## An AUC of 0.805 that means nothing, which is the first result

| arm | `gk_cc` raw AUC | within strata of current volatility | feeds agreeing |
| --- | ---: | ---: | --- |
| **deriv vol** - constant volatility by construction | **0.8052** | **0.5250** | 100% of 12 |
| fx | 0.7077 | **0.6484** | 100% of 20 |
| equity | 0.7379 | **0.6671** | **98% of 371** |
| fx, block-shuffled | 0.6732 | 0.5448 | 100% of 20 |

Deriv's volatility indices hold their volatility **constant by construction**.
`gk_cc` - the Garman-Klass estimator over the close-to-close one - reads 0.8052
there, and 0.5250 once current volatility is held fixed. The mechanism is in the
target: `vol_up` asks whether forward volatility exceeds current volatility, and
`gk_cc` carries current volatility in its denominator, so on a constant-volatility
process the feature is reading the target's own definition back.

It is not only the features. The **incumbent** - plain current realised
volatility, no new idea in it - reads an AUC of **0.7763** on fx for "is forward
volatility in the top tercile", and plain range width reads **0.7409** for
containment. High AUCs are free on volatility-shaped targets.

**So every table in this file reports the AUC inside strata of the predictor
already available, and that column is the only one that carries a claim.**

## What survives: drive `Q` from the range, not from closes

| fx, `vol_up` (base 0.488, 499 windows a feed) | AUC | within strata | sign |
| --- | ---: | ---: | --- |
| `gk_cc` Garman-Klass / close-to-close | **0.7077** | **0.6484** | 100% of 20 |
| `park_cc` Parkinson / close-to-close | 0.7067 | 0.6481 | 100% of 20 |
| `rs_cc` Rogers-Satchell / close-to-close | 0.7056 | 0.6471 | 100% of 20 |
| `vol_ratio` this window over the last | 0.3177 | 0.3780 | 100% of 20 |
| `vol_of_vol` | 0.3633 | 0.4101 | 100% of 20 |

On equities, 392 feeds and 371 scored: `gk_cc` **0.7379** raw, **0.6671**
within strata, **98% of 371 instruments agreeing in sign**. Three hundred and
seventy-one independent markets is the strongest replication this cache can
offer, and the three estimators agree with each other to three decimal places
because they measure the same thing - how much of the variance happened inside
the bar rather than between closes.

**It strengthens as the window shortens**, which is the part that matters for
production: within-strata 0.6232 at a hundred-bar window, **0.6484** at forty.
A range estimator earns most where observations are few, and few observations is
exactly the regime a filter's `Q(dt)` update lives in.

The surrogate behaves as it should. Block-shuffling keeps each bar's own geometry
and destroys the ordering, so an estimator that is simply **more efficient**
should keep part of its edge there - and it does, 0.5448 against 0.6484. The gap
between those two is the part that needs the real series.

## Direction: the framings that were wrong, and the one that was missing

Everything this desk had closed about direction was measured on **terminal sign
over a hundred-bar forward window, unconditionally, on fx and synthetics**. That
is a narrow piece of evidence, so four more framings were added:

- `dir_1`, `dir_5`, `dir_20`, `dir_100` - terminal sign at four horizons.
- `first_up` - **which barrier arrives first**, plus or minus one sigma. Path
  dependent, clock free, and what a position actually experiences.
- `mfe_gt_mae` - did the favourable excursion beat the adverse one. A magnitude
  statement, not a sign one, and an AUC on sign is blind to it.
- `big_up_1/2/3` - direction **given** the move reached one, two or three sigma.
- A **cross-section** of 147 equities over 360 dates: which names outrun the
  others, which needs no view on the market at all.

| framing | best reading anywhere |
| --- | --- |
| terminal sign, four horizons | 0.5267 |
| barrier first | 0.5325 |
| excursion asymmetry | 0.5541 |
| tail direction, pooled | `kurtosis` 0.565 at two sigma |
| cross-section, 360 dates | **0.5072**, t 1.60; best decile spread t -2.36 of 24 features |

Nothing is near 0.80. `drift after`-shaped readings are null in every arm of
every run.

## The tails: a real test, and a null - plus a correction

The first version of this was underpowered in a way that produced a false
positive, and the story is worth keeping. Scored per feed, a tail target needs
eight up **and** eight down events before that feed counts. A 1,900-bar equity
holds a handful of two-sigma moves, so **141 of 146 names were discarded** and
the reported equity base rate came from five feeds and 110 events. Read as 146
feeds and 3,200 events it looked like 4.8 sigma. It was 0.9.

Pooling every feed's tail events into one pot is what makes the question
answerable:

| arm | 1 sigma | 2 sigma | 3 sigma |
| --- | --- | --- | --- |
| fx | 0.5055, z 0.61, n 3100 | 0.4827, z -0.95, n 750 | 0.4500, z -1.34, n 180 |
| metal | 0.5312, z 1.14 | **0.6220, z 2.21**, n 82 | too few |
| equity | 0.5101, z 1.39, n 4742 | 0.5061, z 0.41, n 1152 | **0.5481**, z 1.70, n 312 |
| deriv vol | z -0.96 | z -1.10 | too few |
| deriv jump | z -0.13 | z -0.23 | too few |
| deriv structured | z -0.63 | z -0.99 | too few |

Eighteen readings and one at `z` 2.21 on eighty-two events, which is what chance
gives. The signs **contradict**: fx leans down at three sigma, equities lean up.
The earlier "monotone downward in every arm" was the broken per-feed guard, not
the market.

And the predictors of **which** tail settle it. The best fx three-sigma reading
is `spread_level` at **0.599** - and the block-shuffled surrogate of the same
series gives `spread_level` at **0.601**. Same feature, same value, with no
market structure left in the bars.

## What should change in `statespace`

One thing, and it is measured: **`Q` should be driven by a range-based
volatility estimator rather than by close-to-close returns.** Garman-Klass,
Parkinson and Rogers-Satchell are equivalent for this purpose; the effect is
0.648 within strata on twenty fx feeds and 0.667 on three hundred and
seventy-one equities, it grows as the window shortens, and the surrogate places
roughly a third of it beyond mere estimator efficiency.

What should **not** happen is chasing the raw number. The arm that crossed 0.80
is the one whose generator holds volatility constant.

## What is not done

- The incremental edge is measured against a six-bin dial, **not against
  `statespace`'s own `Q(dt)`**. That is the bar this has to clear before it goes
  into the filter, and it is harder than the one cleared here.
- Equity windows are forty bars because most names carry about 1,900 hourly
  bars. The hundred-bar read exists for fx and is weaker, so the window length
  is a live parameter rather than a settled one.
- The cross-section is one five-bar horizon on 147 names. Longer horizons and a
  wider panel are cheap and untried.
- Features are read one at a time. Nothing here combines them, and the Mapper
  work in `mapper.md` is the other half of that question.
