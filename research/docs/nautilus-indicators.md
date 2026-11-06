# Nautilus's indicators, their parameters, and the desk's money management

**Pre-registered 2026-11-05.** The grid below was frozen in
[`research/ideas/nautilus_grid_rule.json`](../ideas/nautilus_grid_rule.json)
and committed before any cell ran. Results are appended under
[Results](#results) in a later commit, so the ordering is in the history rather
than asserted here.

## Verdict

| | |
| --- | --- |
| **Primary** | *pending* |
| **Secondary** | *pending* |
| **Cells** | 288 hypothesis cells; 14.4 positive from chance alone at 5% |
| **Controls** | 288 matched-walk runs, 288 synthetic-market runs, 72 duty-cycle twins |

## The question, and why it is not one of the two dozen already closed

This desk has measured indicators five ways and the honest summary is that the
*entry* question is shut:

| what was closed | where | the number |
| --- | --- | --- |
| textbook indicators at default parameters, as standalone entries | [battery.md](battery.md) | 15 of 323 cells; FX and metals zero; only crypto 4h CCI survives, at +0.059R |
| a lagging indicator timing an entry at a structure zone | [indicators.md](indicators.md) | 0 of ~170 cells; waiting for a reclaim *costs* 0.07-0.13 vol on FX 15m |
| indicators as confirmation gates on level signals | [confirm.md](confirm.md) | 17 of 8,366; a learned confirmer reads AUC 0.537 on markets and 0.537 on walks |
| published multi-indicator EAs with their own geometry | [geraked-eas.md](geraked-eas.md) | 12 of 13 lose 0.02-0.09R; P(+N R) equals 1/(1+N) on all of them |
| three TradingView indicators traded as strategies | [tv-indicators.md](tv-indicators.md) | every primary fails; -0.11R to -1.34R |

**So the entry axis of this grid is a re-measurement and is labelled one.** It
is the carrier, not the question. The two things it adds over battery.md are
that the **parameters are swept** - battery ran every rule at its default, and
its own note says a parameter change is a new trial it did not spend - and that
it runs through `BacktestNode` and a production catalogue, which no indicator
study on this desk has done.

**The question is the money-management axis**, and it is open for a specific,
checkable reason. [sizing-multipliers.md](sizing-multipliers.md) set out to
measure the desk's eight sizing levers and found that **not one of them could
change a position size**: `Profile.multipliers` had no caller in
`till_infinity/`, no producer set `Intent.volume`, all 25 intents died at
`(desk):zero-volume`, and the four engine arms came back bit-identical at
equity 10,000.00. `strategies/sizes.py` has since wired that path. This is the
first run in which the desk's sizing arithmetic reaches an order, and
`Strategy.reward_floor` - which [hold-clock.md](hold-clock.md) names as the
lever and which **no document has ever measured** - gets a number.

### What is deliberately not in the grid

Each of these would be a closed claim wearing a new name, and each is dropped:

- **a wider or narrower stop at constant money risk.** [widestop.md](widestop.md):
  mean R scales as exactly `1/m` (+0.180, +0.180, +0.178, +0.177 for `R x m`).
  The stop multiple is fixed at 2.0 ATR here and is not swept.
- **a trailing stop, a breakeven trigger, a grid or a martingale.**
  [geraked-eas.md](geraked-eas.md) Mode R: every factor's shift in mean R
  matched the walks' to within 0.007R, and trail-25%'s apparent +0.040R gain was
  +0.036/+0.039 on the walks.
- **a stop anchored to a level.** [stop-anchor.md](stop-anchor.md): 0 of 14
  instruments beat a distance-matched placebo.
- **a reward-to-risk gate.** 0.908R ungated against 0.868R at 1.2, refusing
  40,421 of 47,676 calls. `reward_floor` is in the grid *because it is not that*:
  it moves a target out and refuses nothing.
- **a rolling quantile of anything.** Worse than the constant passing the same
  volume over 10,483 pairs.
- **pausing on recent P&L.** No better than pausing at random.
- **Kelly or fractional-Kelly.** [compounding.md](compounding.md): growth-optimal
  `f` is exactly 0 in 100% of 2,000 bootstraps, so it is meaningless until an
  edge exists.

## The prediction, written before the run

[deriving.md](deriving.md) is a theorem rather than a measurement: a predictable
position on a martingale has zero gross expectancy, so
`E[net] = -(c/2) x turnover` for every stop, target, trail, breakeven,
scale-out and position-sizing scheme including Kelly. Mode R measured exactly
that on thirteen EAs across three arms.

**The pre-registered expectation is therefore a null on every money-management
arm.** The result that would be worth something is a clean null with its power
shown, and the result that would be worth a great deal is a money-management
variant that beats base, beats its own duty-cycle twin, and does neither on the
walk.

## The data

`node/corpus.py` fills the catalogue from `.data/prices/prices.db`: about 76
days of 15-minute bars for six feeds. Its own docstring is blunt about what
that is worth - *"A catalogue this size answers mechanics, not edge."* At the
firing rates measured in the smoke run (83 to 148 signals per feed over 5,135
bars) a cell there holds about 120 trades, which is the sd-of-1.6R regime where
a mean is noise.

So [`nautilus_grid_corpus.py`](../ideas/nautilus_grid_corpus.py) writes a second
catalogue from the lab's `data/seqlab` cache, at the same interval over seven to
twelve years, in the same `ParquetDataCatalog` through the same
`node/corpus.instrument_for`, `_bar` and `_quote`.

| arm | instruments | bars each | span | spread |
| --- | --- | ---: | --- | --- |
| `real` | EUR/USD, GBP/USD, GOLD, BTC on DERIV | 259,486-294,524 | 7.4-11.8 years | 1.0414 / 0.8897 / 0.4081 / 2.9017 bps, **measured** from the store's own DERIV quotes |
| `walk` | the same four on a WALK venue | identical | identical | identical |
| `synth` | VOL25, VOL75, JUMP75, STEP on DERIV | 198,530-275,053 | 5.7-7.8 years | set to a 0.063R round trip |

**The per-bar `spread` column in the cache is not used and must not be.**
Measured against the recorded quotes it is 3.3 to 8.3x too narrow on FX and
6.5x too wide on `Volatility 75 Index`, and 421 of 4,830 direction cells in
another study changed sign on the cost line alone.

**No Deriv synthetic has a recorded quote anywhere in the store**, so the
`synth` arm is costed to the *median of the four real legs' cost in R* (0.063R
at a 2-ATR stop) rather than priced off a guessed spread. That is a decision
about what a control pays, not a claim that a synthetic is tradable at that
price, and no money figure from that arm is quoted.

**The `walk` arm is built in log space**, which is a deliberate departure from
`node/surrogates.walk_with_bar_geometry`. That helper resamples the *additive*
close-to-close step and each bar's shape as proportions of its own range, which
is right at the lengths it was written for. BTCUSD's 259,486 steps have a
standard deviation near 60 dollars, so an additive walk of them wanders about
`60 * sqrt(259486) = 30,500` from a start near 8,000 and spends part of the run
at a negative price, which Nautilus refuses outright. The resampling here is of
log returns and of each bar's range as a fraction of its close: the same two
quantities, the same removal of path structure, and a price that cannot go
negative.

## The grid as frozen

Six rules, three parameters each, four money-management variants, four traded
instruments. Every cell is **two** Nautilus indicators - the signal one and
`AverageTrueRange(14)`, which sets the stop and therefore the unit every number
here is reported in.

| rule | Nautilus class | parameters | the signal |
| --- | --- | --- | --- |
| `ema_cross` | `ExponentialMovingAverage` | 5, 10, 20 | EMA(n) crossing EMA(3n) |
| `donchian_break` | `DonchianChannel` | 20, 55, 100 | close beyond the **previous** bar's channel |
| `rsi_revert` | `RelativeStrengthIndex` | 7, 14, 28 | crossing back up through 0.30 or down through 0.70 |
| `macd_signal` | `MovingAverageConvergenceDivergence` | 6, 12, 24 | MACD(n, 2n) crossing zero |
| `bb_revert` | `BollingerBands` | 10, 20, 40 | close re-entering the band from outside |
| `keltner_break` | `KeltnerChannel` | 10, 20, 40 | close beyond the previous channel |

**Previous, not current.** Nautilus updates a registered indicator *before*
`on_bar`, so `donchian.upper` at the time a rule reads it is already this bar's
high and `close > upper` can never be true. A breakout rule that fires zero
times reads as a market with no breakouts, which is why the smoke run checks
that all six fire.

| variant | what changes | why it is in the grid |
| --- | --- | --- |
| `base` | stop 2.0 x ATR(14), target 2.0R, risk 0.25% of equity | the reference |
| `floor` | `Profile.floored_target` at `reward_floor = 1.7` | moves a target out and refuses nothing. Never measured by any doc |
| `volsize` | risk fraction x `median(ATR, 96) / ATR`, clipped to [0.5, 2.0] | `sizing-multipliers.md`'s volatility arm on a fresh population, judged on a scale-free statistic |
| `gate` | trade only where ATR(14) is below its own 96-bar median | an on/off rule, which is the shape that has fooled this desk most |
| `twin` | keeps signals **at random** at exactly its gate cell's own keep rate | the only comparison that carries information on a net-negative book |

Fixed and not swept: the hold cap at 200 bars (battery.md's, so the two are
comparable), the regime window at 96 bars (one day of 15-minute bars), the stop
at 2.0 ATR (widestop.md closed the sweep), the account at 100,000 USD at 30x.

### The cells, counted

```
6 rules x 3 parameters x 4 money-management variants x 4 instruments = 288
```

**288 hypothesis cells.** At a 5% threshold that is **14.4 positive cells from
chance alone**, which is why the only number worth reading is the one after
Benjamini-Hochberg over all 288 - never over the survivors. This desk's own
record is the reason: 18 of 43 instruments were nominally profitable where
chance gives 22, and **not one survived BH as profitable while five survived as
losers.**

The 288 walk runs, 288 synthetic runs and 72 twins are **controls, not
hypotheses**, and are not in the BH family.

### Discovery and confirmation

**Split at 2022-01-01, fixed before the run.** Discovery is every trade opened
before that date, confirmation every trade opened on or after it. Both halves
are reported for every cell that is highlighted, and selection happens on
discovery only.

### What is measured

- **mean net R per trade**, which is net per unit traded. `R = (exit_fill -
  entry_fill) * side / |entry_ref - stop|`, from the engine's own fills, with
  the denominator set by the **stop and never the target**.
- the standard error from a **day-block bootstrap**, 2,000 draws over whole UTC
  days, because trades cluster in days and an ordinary standard error is far too
  narrow.
- `P(reach 2R before the stop)` against the walk's `1/(1+2) = 0.3333`.
- `sum(pnl) / sum(risk_money)` for the sizing arm, which is scale-free, so a
  multiplier whose mean is not one cannot move it on its own.
- stop-out share, time-exit share, trades per year, and the duty cycle.

### The bars to clear, set in advance

- **positive:** mean net R > 0, BH `q < 0.05` over 288, positive in **both**
  halves, and beating the matched walk cell.
- **a money-management variant:** beats `base` on net R per trade, and where it
  gates, beats **its own twin at the same keep rate**.
- **a null is the valued result**, and is only reported alongside the power to
  have seen the effect.

## A harness defect this run found before it ran

`BacktestVenueConfig.bar_execution=True` is what makes a bar-only catalogue
tradable, and it fills a **market order from the bar's own one-tick book, not
from the catalogue's modelled quote.** Measured on EUR/USD, same feed, same
rule, the catalogue written twice:

| modelled spread | modelled half-spread | median entry slip | mean R on stop exits |
| ---: | ---: | ---: | ---: |
| 1.0414 bps | 0.0000597 | **0.0000100** | -1.223 |
| 100 bps | 0.0057377 | **0.0000097** | -6.750 |

A ninety-sixfold change in the spread moved the entry slip by three ten-
millionths of a pip - it is one price increment both times - while the stop
exits moved from -1.223R to -6.750R. So the quotes *do* reach the matching
engine and *do* price a stop exit, and an entry is filled off the bar. The
entry half-spread is therefore **not charged by the engine** and is charged
analytically instead: `max(0, half_spread_px - tick_size) / risk`, which is
0.056R on EUR/USD, 0.045R on GBP/USD, 0.011R on GOLD and 0.024R on BTC at the
median 2-ATR stop. Stop and target exits are priced off the quote and are left
alone.

This is the shape of defect the catalogue's own docstring warns about from the
other direction - it worries that a stop fills *at* the stop with no overshoot
- and the measured mean of -1.223R on stop exits says that is not happening
either.

## Results

*Pending. Appended in a later commit, with the grid above unchanged.*
