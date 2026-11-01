# Do the eight sizing multipliers earn their place?

**Measured 2026-11-01** with [`sizing_multipliers.py`](../ideas/sizing_multipliers.py)
(the replay) and [`sizing_multipliers_engine.py`](../ideas/sizing_multipliers_engine.py)
(the engine run). The question is the one `SIZING_MULTIPLIERS` was built to
ask: of the nine reductions in `risk/scaling.py`, which should be switched on?

**The answer is none of them, and the reason is not the measurement.**
`SIZING_MULTIPLIERS` cannot change a position size in the package as it
stands, so there is nothing yet to compare. Of the nine, **two can move a size
at all** at the shipped settings, **three read a feature no live producer
emits**, **one is unmeasurable on every local record**, and on the only trade
population this desk has ever had, **none of the eight survives the
multiplicity of nine comparisons** - the best is `slippage` at p = 0.022
against a Holm bar of 0.0056.

## The switch is wired to nothing, and the engine says so

`Profile.risk_scale` and `Profile.multipliers` have **no caller in
`till_infinity/`**. Every call site is in `research/retire/` - the retired
`structures` strategies, which is where the method was written. The three
live references to `scaling` are all inside `strategies/profile.py`, calling
each other.

Run the engine and nothing contradicts that. 5,136 EURUSD 15m bars out of
`.data/prices/prices.db`, the shipped `StatespaceActor` and the shipped
`SurpriseEdge`, four arms:

| `SIZING_MULTIPLIERS` | `Profile.multipliers` calls | intents | orders | positions | equity |
| --- | ---: | ---: | ---: | ---: | ---: |
| unset | **0** | 25 | 0 | 0 | 10,000.00 |
| `all` | **0** | 25 | 0 | 0 | 10,000.00 |
| `spike` | **0** | 25 | 0 | 0 | 10,000.00 |
| `interval` | **0** | 25 | 0 | 0 | 10,000.00 |

Bit-identical. 5,133 readings published, 56 proposals reaching a desk, 31
declined on surprise, 25 accepted - and all 25 refused at
`(desk):zero-volume`, because `Intent.volume` is `_number(features.get(
"volume"))` and no producer sets `volume`. `Intent` is frozen, so nothing
downstream can fill it in. **The sizing path is not merely un-multiplied, it is
absent**: `risk.sizing.lots` is called only by `risk/affordable.py`, which is a
catalogue rather than a sizer.

So the nine arms a backtest can run today are nine copies of the baseline. Nine
comparisons of a difference that is identically zero is not a measurement, and
a DSR over them would be a deflation against a search that tried one thing.

## At the shipped settings, seven of the nine are the constant 1.0

Not because they are disabled - because their own threshold defaults to zero
and every function reads zero as off. `.env` sets none of them and
`.env.example` has all of them commented out, so these are the deployed values:

| multiplier | shipped setting | value it can take |
| --- | --- | --- |
| `crowding` | `crowding_share=0.0` | **1.0 always** (`share <= 0`) |
| `volatility` | `volatility_target_bps=0.0` | **1.0 always** (`target <= 0`) |
| `regime` | `regime_band=0.0` | **1.0 always** (`width <= 0`) |
| `spike` | `spike_above=0.0` | **1.0 always** (`above <= 0`) |
| `edge` | `edge_full_at=0.0` | **1.0 always** (`full_at <= 0`) |
| `drawdown` | `drawdown_halt_at=0.0` | **1.0 always** (`halt_at <= 0`) |
| `slippage` | `DEFAULT_STOP_OVERSHOOT` | 0.5 on six `boom`/`crash` spike sides |
| `interval` | `INTERVAL_WEIGHT` | 0.8 at 1m/3m/5m, 0.95 at 15m |
| `share` | `risk_share=0.0`, `style="scalp"` | 1.0 for a scalp, 0.85 swing, 0.7 position |

The brief named `by_regime` as the one needing a band chosen and stated. It is
six, not one. `SIZING_MULTIPLIERS=all` on the shipped settings would multiply
every trade by `slippage x interval x share` and nothing else.

## Three of them read a feature that no longer exists

`statespace/proposing.py` is the only proposal producer the node runs -
`statespace/service.py` still declares `PROPOSES` and is imported by the actor
for topic parity only, with an `F401` on it - and the features it emits are `vol_bps`, `surprise`, `stop_vol`, `target_r`,
`probability`, `base_rate_up`, `log_variance`, `spread`, `band_coverage` and
`stretch`. Against what the nine read:

* `spike` reads `tr_percentile` - **not emitted**, so `by_spike` returns 1.0.
* `regime` reads `forecast_ratio` - **not emitted**, so `by_regime` returns 1.0.
* `edge` reads `net_edge_vol` - **not emitted**, so `by_edge` returns 1.0.
* `volatility` reads `ewma_tr_bps` and falls back to `vol_bps`, which **is**
  emitted - so this one survives the producer change.
* `crowding` reads `p.feed` off each open position. A Nautilus `Position` has
  no `feed`, so the comprehension in `Profile.multipliers` filters the whole
  book out and the count is zero whatever the share is.

Those five readings were produced by the retired `structures` engine. Switching
the names on would not bring them back.

The side leaves being added in `statespace/deciding.py` are further from the
path, not nearer: `SideProfile` is a plain class of `ClassVar`s and **not a
`Profile`**, because `statespace` may not import `strategies`, so neither
`risk_scale` nor `multipliers` exists on it at all. Its own `risk_share` is
1.0 and its docstring says it plainly - "carried, not applied, and nothing
reads it yet" - and the copy on `Intent.features` is for the journal.

## The baseline, and the fact that it does not reproduce

The only trade population this desk has is the journal export at
`.data/live/journal_full.csv`: 2,891 decisions and 1,626 outcomes,
**2026-08-30 to 2026-10-08**. The window is chosen because it is the only one
that exists locally, not because it is the right length.

1,613 closes after dropping 13 records - 10 with no `r_multiple` and 3 whose
`risk_price` rounded to a couple of ticks, one of which reads **2,390 R** on a
5.38 profit. [`losing-faster.md`](losing-faster.md) already scores in broker
money for that reason, so the exclusion is the desk's own.

| | |
| --- | --- |
| closes | 1,613 |
| expectancy | **-0.0618 R** |
| sd | 0.9330 |
| win rate | 0.4634 |
| payoff | 0.9760 |
| profit factor | 0.8429 |
| per-trade Sharpe | -0.06625 |
| money | -1,543.63 (mean -0.957) |
| broker cross-check, `deals.json` | 4,215 deals, net **-1,031.81** |

**It does not reproduce the table the interval weights were fitted on.**
`trading-scaling.md` publishes a per-close record as of 2026-09-03; the same
cut of this window beside it:

| interval | published n | per close | here n | per close |
| --- | ---: | ---: | ---: | ---: |
| 1m | 47 | -7.75 | 27 | -3.22 |
| 3m | 34 | -4.80 | 14 | **+5.24** |
| 5m | 48 | -6.13 | 59 | -6.82 |
| 15m | 15 | -2.46 | 17 | -0.34 |
| 30m | 2 | +3.71 | 8 | +0.09 |
| 1h | 3 | +18.67 | 5 | +7.32 |

The sign and ordering hold at 1m, 5m, 15m and 1h; 3m flips; no count matches.
The cause is the window and not the extraction: the published table was
computed over the account's history to 2026-09-03 and the export begins
2026-08-30, so the two are different sets of trades. Per
`reproduce-the-baseline-before-an-increment` that is a reason to read the
`interval` arm below as an **out-of-sample** test of weights fitted on a
population this machine does not hold - which is the useful direction - and
not as a reproduction.

The exact pairing is also gone. [`loss_anatomy.py`](../ideas/loss_anatomy.py)
joined 1,562 closes to their decisions on the journal DB's `parent` column; the
CSV export drops that column, and no local DB has the trading decisions
(`.data/journal/journal.db` holds 167 `structures` outcomes,
`.data/tmp/journal.db` 398 trading outcomes and no decisions,
`.data/journal/fresh.db` is a `structures` signal record). So the join here is
`(feed, side, volume, entry)` with the last decision before the close, which
matches 745 of 1,626 and biases towards the first three weeks.

## One arm at a time

A sizing multiplier scales *risk*, so in R-multiples trade `i` risks `m_i` and
returns `m_i r_i`, and "are the trades it shrinks the ones that lost" is
whether the risk-weighted mean `sum(m r) / sum(m)` beats the unweighted
`mean(r)`. The denominator is invariant under permuting `m` against `r`, so
that permutation is an **exact** null for the statistic and it is centred on
zero; 20,000 draws, two-sided, seed 20261101. Win rate is unchanged by
construction and is the harness check.

Every arm that was run, including the losers and the two reported variants:

| arm | n | moved | mean m | baseline | arm | delta | z | p | setting, stated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `slippage` | 1,613 | 91 (6%) | 0.972 | -0.0618 | -0.0555 | **+0.0063** | +2.31 | 0.0224 | `DEFAULT_STOP_OVERSHOOT` (shipped) |
| `regime` | 562 | 380 (68%) | 0.721 | -0.0613 | -0.0404 | **+0.0209** | +2.07 | 0.0384 | `band=log 1.21=0.1906`, `floor=0.5` |
| `share` | 1,613 | 100 (6%) | 0.991 | -0.0618 | -0.0603 | +0.0015 | +1.75 | 0.0790 | `style -> RISK_SHARE_BY_STYLE` (shipped) |
| `edge` | 1,613 | 601 (37%) | 0.774 | -0.0618 | -0.0793 | -0.0174 | -1.66 | 0.0984 | `full_at=1.0`, net edge from `paying.md` |
| `volatility` | 562 | 279 (50%) | 0.824 | -0.0613 | -0.0753 | -0.0139 | -1.57 | 0.1162 | `target_bps=8.357` (the sample's median) |
| `drawdown` | 1,613 | 1,607 (100%) | 0.079 | -0.0618 | -0.1096 | -0.0478 | -1.20 | 0.2241 | `halt_at=0.03` (the standard plan's day) |
| `crowding` | 1,613 | 563 (35%) | 0.775 | -0.0618 | -0.0652 | -0.0034 | -0.35 | 0.7288 | `share=0.5` |
| `interval` | 1,613 | 1,533 (95%) | 0.828 | -0.0618 | -0.0617 | **+0.0002** | +0.09 | 0.9300 | `INTERVAL_WEIGHT` (shipped) |
| `spike` | **1** | - | - | - | - | - | - | - | `above=0.8`, `floor=0.5` - **not measurable** |
| `drawdown@0.30` | 1,613 | 1,607 (100%) | 0.747 | -0.0618 | -0.0668 | -0.0050 | -1.24 | 0.2119 | reported variant, not a sweep |
| `all-but-spike` | 562 | 562 (100%) | 0.054 | -0.0613 | -0.0716 | -0.0102 | -0.67 | 0.4998 | the eight measurable arms at once |

Where each stated setting comes from: `crowding_share=0.5` is
`trading-scaling.md`'s own worked example; `regime_band=log(1.21)` is the
measured plateau in the same doc (86.4% held between 1.00 and 1.21 against
81.3/81.4% outside); `spike_above=0.8` is "the measured setting" verbatim;
`edge_full_at=1.0` is the round number above the best row in
[`paying.md`](paying.md) (spx500 +0.938); `drawdown_halt_at=0.03` is the
standard plan's `daily_loss_fraction`; `volatility_target_bps` is the median
reading over the arm's own sample, so the lever cuts the loud half and leaves
the quiet half alone. None was moved after seeing a result.

Four things in that table are worth saying out loud.

**`by_drawdown` at the desk's own halt is a kill switch, not a taper.** The
taper is from the high-water mark and does not reset daily, so a 3% fall puts
every subsequent trade at `FLOOR` - 1,607 of 1,613 trades, mean multiplier
0.079. It is a near-uniform 20x shrink, and a uniform shrink cannot select: it
moves total P&L and leaves the per-unit-of-risk result alone (and here it reads
*worse*, because the trades after the first drawdown were better than
average). `drawdown@0.30` is listed so that is visible as a property of the
function rather than of the chosen number.

**`by_interval` is the one lever with a shipped non-trivial setting and it is
the flattest arm on the board.** It moves 95% of trades and buys +0.0002 R,
z +0.09. The weights were fitted on the per-interval money table above, and
out of sample on this window the selection is worth nothing.

**`by_slippage` is the only arm with a positive reading on the full sample**,
and it earns it on 91 trades of 1,613 - the Boom/Crash spike sides. It is also
the arm whose overshoot number was measured on this same book
(`trading-scaling.md`, 2026-09-02 and the 2026-09-11 revision), so a positive
in-sample reading was the expected outcome and is not evidence.

**`regime` has the largest delta and the smallest sample.** +0.0209 R on 562
trades at p = 0.0384 - the arm nearest to interesting, on the subsample whose
outcomes happened to carry their own features, i.e. the first three weeks. The
honest reading is that it is a candidate for a measurement, not a result.

## The multiplicity of nine

Eight of the nine moved a multiplier below 1 on at least one trade. Holm at
k = 9:

| arm | p | Holm bar | survives |
| --- | ---: | ---: | --- |
| `slippage` | 0.0224 | 0.00556 | no |
| `regime` | 0.0384 | 0.00625 | no |
| `share` | 0.0790 | 0.00714 | no |
| `edge` | 0.0984 | 0.00833 | no |
| `volatility` | 0.1162 | 0.01000 | no |
| `drawdown` | 0.2241 | 0.01250 | no |
| `crowding` | 0.7288 | 0.01667 | no |
| `interval` | 0.9300 | 0.02500 | no |

**Nothing survives.** The first comparison would have needed p <= 0.0056 and
the best is four times that.

And the deflation, over every arm that was run plus the baseline - eleven
trials, Sharpes from -0.0962 to -0.0506, variance 1.608e-04, SR\* +0.0206:

**every arm's Sharpe is below zero**, so the best arm has nothing to deflate.
`regime` at -0.0506 returns DSR 0.0493, which is the probability that an arm
whose point estimate is negative has a true Sharpe above an expected-maximum
bar of +0.0206. It is reported because the brief asks for every arm, not
because 0.049 is a near miss.

## Where this goes blind

The one thing worth knowing before accepting a null: what size of effect this
test would have found. The planted lever has the geometry of the real ones -
it reduces 55% of trades to 0.8 - and picks which ones with probability
`skill` of drawing from the losing half. 0.50 is the null; 60 draws per point,
alpha 0.0056 (Bonferroni at nine):

| skill | median delta | detected |
| ---: | ---: | ---: |
| 0.50 | +0.00007 | 3% |
| 0.52 | +0.00378 | 7% |
| 0.54 | +0.00654 | 37% |
| 0.56 | +0.01080 | 82% |
| 0.58 | +0.01387 | 97% |
| 0.60 | +0.01791 | 100% |
| 0.70 | +0.03587 | 100% |
| 0.85 | +0.06244 | 100% |
| 1.00 | +0.07301 | 100% |

**At 1,613 trades this is not an underpowered test.** It finds a lever that
reduces 55% of trades and gets 58% of them from the losing half, every time. It
goes blind below about 54% skill - a gain under roughly **+0.007 R a trade** -
and that is the honest boundary of the null: a sizing lever worth less than a
hundredth of an R per trade is not visible here, and a lever worth more than
+0.018 R would have been unmissable. For scale, `what-loses.md` puts the
spread at +0.089 R a trade, so the blind region is well under a tenth of the
cost the desk already pays.

Two caveats the power table does not cover. `regime` and `volatility` run on
562 trades rather than 1,613, where the blind boundary is roughly twice as far
out; and `spike` has a sample of one, where there is no boundary at all.

## Recommendation

**Enable none of the eight.** Specifically:

* **`interval`, `crowding`, `edge`, `volatility`, `drawdown`** - leave off.
  Each reads a negative or flat delta on the record and none is close to the
  corrected bar. `interval` is the clearest: the one with a shipped setting,
  moving 95% of trades, worth +0.0002 R.
* **`slippage`** - leave off, *and not because it failed*. Its +0.0063 R is
  the best on the board and it is in-sample on the book its overshoot was
  measured from. It is the first candidate for a pre-registered test on
  unseen Boom/Crash closes, where the mechanism (`deriving.md` puts the spike
  side's stop slippage at +13.96 R, with a formula) is the strongest on this
  desk. 91 trades is not enough to decide it.
* **`regime`** - leave off, and measure it properly. Largest delta,
  p = 0.0384, 562 trades, and a stated band taken from a doc rather than from
  this data. It needs `forecast_ratio` back on the proposal and a fresh
  population.
* **`share`** - leave off. It is not a reading of the bar, it is a constant
  per strategy, so it cannot select at all: its +0.0015 R is entirely which
  strategies happened to be labelled `swing`. Treat it as what it is - a
  per-strategy risk budget, decided by an argument about capital allocation
  rather than measured against outcomes - and keep it out of a comparison
  with eight bar-readings. It is the one of the nine whose value does not
  depend on the measurement at all.
* **`spike`** - **could not be measured.** `tr_percentile` first appears in the
  journal on 2026-09-26, the outcome records never carry it, and the lossy
  CSV join leaves **one** closed trade with the reading. The decisions have it
  on 1,544 rows; recovering it needs the production journal DB's `parent`
  column, which is not available locally. It is also the arm with the best
  prior evidence (`crash-timing.md`: a 4x bar is 2.2-2.5x as likely in the top
  fifth, and halving there moved a worst case from -38.3 to -19.2), so it
  should be the first one re-run when the record is reachable.

**And before any of that, the switch has to reach a trade.** Three things, in
order, none of them a sizing question:

1. Something has to set `Intent.volume`. `risk.sizing.lots` exists and has no
   caller on the entry path - it is reached only through `risk/affordable.py`,
   which is a catalogue of instruments this account cannot trade rather than a
   sizer, and no test calls it directly.
2. `Profile.risk_scale` or `Profile.multipliers` has to be called by whatever
   does. Today the switch is unreachable from the entry path.
3. `crowding` needs the book as `(feed, sign)` pairs; a Nautilus `Position`
   does not carry a feed, so the caller has to supply it, which is what
   `scaling.crowding`'s own docstring asks for.

Until then `SIZING_MULTIPLIERS=all` is a configuration change with no effect,
which is the safest thing it could be and the least useful.

## What this does not establish

**The population is the retired desk's.** These 1,613 closes were taken by
`cycle-scalp`, `sweep-aware`, `thesis-only`, `inverse` and nine others, all
retired to `research/retire/`. The multipliers now live above a statespace
surprise rule that has taken no trades. A lever that does not select on the
level desk's trades is not thereby refuted on a desk that does not exist yet -
but it is the only evidence available, and every one of the nine was designed
against exactly this population.

**Two arms are in-sample.** `interval`'s weights and `slippage`'s overshoot
were both measured on this book. For `interval` the window differs enough that
the test is effectively out of sample; for `slippage` it is not, and its
positive reading should be discounted accordingly.

**The engine run is one instrument over eleven weeks.** It establishes that the
switch changes nothing, which needs no statistical power - the arms are
bit-identical - and it establishes nothing about returns.

**The quotes in the engine run are synthesised** from each bar's close at a
one-point spread. They exist so the `no-quote` gate is not what stops the run,
and no number here depends on them.
