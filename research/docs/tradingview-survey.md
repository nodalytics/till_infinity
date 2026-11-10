# The published TradingView catalogue, screened for what this desk could deploy

**Surveyed 2026-11-10. Of 387 of the catalogue's most-boosted scripts, 42 do not publish their rule,
100 of the remaining 345 read a `volume` series this venue does not send, 15 specify a trade at all
and 6 mention a cost. Nothing in the catalogue is a new object in the one place this desk has an edge:
every volatility script it offers is a configuration of something already shipped, and the most
boosted of them is a thresholded version of a statistic already measured here.** One idea survives
the three filters with a positive, unsettled reading behind it and is worth a pre-registered run; two
more are listed with the arithmetic that says why they are not first.

The three filters, in the order that ends things cheapest:

| filter | what it is | what it killed |
|---|---|---|
| **expressible** | the venue sends OHLC bars at M1-D1, quote ticks, and `tick_volume`, which is a count of quote updates | every size-weighted statistic: volume profile, VWAP, OBV, money flow, CVD, delta, absorption, liquidity heatmaps - **100 of 345** open scripts read it, and **36 of 38** in the volume family |
| **affordable** | the round trip as a share of the stop the script's own defaults imply | a 1xATR stop at 5m on 8 of 19 instruments, and the whole bar-range geometry on 8; **not** the catalogue's wide default stops, which are affordable and are priced below |
| **not already refuted** | `research/docs/` | the rest of it: oscillators, trend systems, bands, levels, pivots, patterns, candles, SMC, divergence, cycles, ML-on-indicators and the squeeze, each with a file name in the table below |

Scripts: [`ideas/tv_survey.py`](../ideas/tv_survey.py) (frame, source, audit),
[`ideas/tv_survey_cost.py`](../ideas/tv_survey_cost.py) (the cost screen) and
[`ideas/tv_squeeze.py`](../ideas/tv_squeeze.py) (the one measurement). Every number below names one of
them. This follows [tv-indicators.md](tv-indicators.md), which traded three named indicators and found
every primary negative; that study asked whether three scripts pay, and this one asks what the
catalogue contains.

## The frame: how the catalogue was sampled

`MODE=frame python research/ideas/tv_survey.py`, 2026-11-10. TradingView's own
`pubscripts-suggest-json` answers a search with 50 published scripts ordered by boosts, so **50
frozen keywords** - written before any source was read, and listed in the script - give a frame that
re-runs to the same shape and that nobody chose after seeing the answers.

- **2,445 result rows, 2,259 distinct scripts.** 1,942 publish their source, 251 are protected and 66
  are invite-only.
- The audit set is the **top 8 by boosts within each keyword**, deduplicated: **387 scripts**, of which
  42 are closed and 345 were fetched from `pine-facade` and read.
- Per keyword rather than overall, so a thin family is still represented: `gamma exposure` returns 12
  scripts in all and `chart patterns` 33, against 50 for everything else.

**It is not a census.** A family with no keyword is absent, boosts measure popularity and not quality,
and the top 8 of a keyword is the catalogue's shop window rather than its contents. The families this
frame does not reach are named under *What this survey did not cover*.

The eight most boosted scripts in the frame, which is a fair picture of what the catalogue is for:

| boosts | script | author |
|---:|---|---|
| 180,328 | Smart Money Concepts (SMC) | LuxAlgo |
| 118,116 | Squeeze Momentum Indicator | LazyBear |
| 85,331 | SuperTrend | KivancOzbilgic |
| 82,829 | MacD Custom Indicator - Multiple Time Frame | ChrisMoody |
| 67,693 | Support and Resistance Levels with Breaks | LuxAlgo |
| 65,011 | Market Structure Break & Order Block | EmreKb |
| 60,219 | ICT Killzones + Pivots | tradeforopp |
| 49,345 | Bollinger + RSI, Double Strategy | ChartArt |

## What the venue cannot express, said once

Measured from the code rather than assumed, and already measured from the terminal in
[scalping.md](scalping.md) (`real_volume` 0 on 80,000 of 80,000 M1 bars; Step Index's `tick_volume`
median 60, min 17, **max 62** a minute, which is a publication clock and not activity):

- `adapters/mt5/data.py:648` fills a bar's volume with
  `float(row.get("tick_volume") or row.get("real_volume") or 0.0)`. The venue sends `real_volume = 0`,
  so **every bar's volume is a count of quote updates.**
- `node/desks.py:359-377` refuses `VOLUME` and `VALUE` bars outright, because "an MT5 tick's trade
  fields read 0 or a constant 5000, which is why it publishes a `QuoteTick` with a placeholder size
  and never a `TradeTick`". `<N>tick` bars **are** allowed (`node/desks.py:354`), which is the one
  honest use of a quote count.
- `adapters/mt5/data.py:4` and `adapters/mt5/__init__.py:30`: "MT5 has no order book - `market_book_add`
  fails outright". `ticks_bookdepth` reads 0 on every symbol asked.

So **VWAP, volume profile, OBV, money-flow, CVD, volume delta, accumulation/distribution, footprint,
absorption, liquidity heatmaps and every volume-confirmation rule are not buildable here.** Not hard:
the input does not exist. The audit counts **100 of 345** open scripts reading a volume series, led by
the catalogue's 5th most boosted script. The six highest:

| boosts | script | author |
|---:|---|---|
| 67,693 | Support and Resistance Levels with Breaks | LuxAlgo |
| 45,919 | Support and Resistance (High Volume Boxes) | ChartPrime |
| 44,278 | Sessions | LuxAlgo |
| 41,221 | Order Block Detector | LuxAlgo |
| 31,713 | ICT Concepts | LuxAlgo |
| 30,693 | Divergence for Many Indicators v4 | LonesomeTheBlue |

**The count is an upper bound on signal dependence**, because the regex finds any read of the series
including a plot nobody trades off. Read by hand, the top one is not: its break signal is gated on
`osc = 100 * (ema(volume,5) - ema(volume,10)) / ema(volume,10) > 20`, so on this venue the levels draw
and the signal never fires for the stated reason. Where tick volume is used as an **activity** measure
there is a measured basis for it - `shockvolume.md` ships `volume_z` and `volume_z_hour` in the shock
forecaster, and `statespace-volume-clock.md` has volume time absorbing 76% of the clock effect - but
that is a quote count doing a quote count's job, and it is not a VWAP.

**External data is not the blocker people expect.** `request.financial`, `request.economic`,
`request.dividends`, `request.splits` and `request.earnings` appear in **0 of 345** scripts. The
catalogue is built on price alone, which is also why nothing in it tells this desk anything it does
not already have on the same bars.

## Four mechanical facts about the catalogue

`MODE=audit`, over the 345 open sources, with comments and string literals stripped so a script is not
counted volume-dependent on its prose:

| column | count | what it means here |
|---|---:|---|
| **closed** | 42 of 387 (10.9%) | the rule is unknowable, so it is undeployable at any cost. Led by *Swing high low support & resistance* (Patternsmart, 46,185) and *Market Structure BOS/CHOCH/MSB/FVG/OB/BB* (nephew_sam_, 30,931) |
| **volume** | 100 of 345 (29.0%) | no input on this venue |
| **lookahead** | 28 of 345 (8.1%), of which **21 naked** | `barmerge.lookahead_on`. The documented *safe* idiom pairs it with `close[1]`, so 28 is the upper bound and 21 is the count with no offset in front of it - a higher-timeframe bar read before it closed, which draws history the live chart cannot reproduce |
| **cost** | 6 of 345 (1.7%) | mentions commission, slippage or spread anywhere |
| **strategy()** | 15 of 345 (4.3%) | specifies an entry and an exit at all |

**Those last two numbers are the survey's finding.** 95.7% of the catalogue's most boosted scripts
name no trade, and 98.3% never mention what one costs - and two of the six that do are position-size
calculators. That is not a criticism of the authors: TradingView's feed carries no bid-ask, so a Pine
author has nothing to price with. It is the structural reason the catalogue fails here, where
`triage.md` found that every strategy's loss is its spread and
`a-shorter-clock-multiplies-cost-in-r` measured the same spread as 19x dearer at 15m than at 1d. A
published script is a **detector**, and this desk has already measured that detectors are the part
that is not missing.

Per family (`families.csv`), with the top boost in each:

| family | scripts | closed | volume | naked lookahead | cost | strategy() | top boost |
|---|---:|---:|---:|---:|---:|---:|---:|
| smc | 51 | 6 | 16 | 6 | 0 | 0 | 180,328 |
| pattern | 56 | 6 | 8 | 4 | 0 | 0 | 35,039 |
| oscillator | 52 | 4 | 14 | 2 | 2 | 6 | 82,829 |
| trend | 47 | 6 | 3 | 1 | 1 | 4 | 85,331 |
| level | 41 | 8 | 12 | 3 | 0 | 0 | 67,693 |
| volume | 41 | 3 | 36 | 1 | 1 | 0 | 26,770 |
| volatility | 37 | 2 | 6 | 5 | 0 | 2 | 118,116 |
| model | 35 | 4 | 11 | 0 | 1 | 1 | 37,577 |
| band | 26 | 1 | 2 | 0 | 1 | 2 | 33,025 |
| clock | 26 | 1 | 7 | 7 | 0 | 1 | 44,278 |
| risk | 16 | 3 | 1 | 0 | 2 | 2 | 7,542 |
| cross | 16 | 3 | 4 | 3 | 0 | 1 | 5,988 |

## The cost screen, and the one correction it makes

`./.secrets/lab.sh run research/ideas/tv_survey_cost.py CLOCKS=5,15`, 2026-11-10, 19 instruments from
the lab's M1 stores, against the terminal's own live ask minus bid. **0 of 19 unscreened** - the bridge
answered for every symbol.

Cost in R is `round_trip / stop` and is set by the stop, so each family is priced at **its own
published geometry** measured off the bars, not at a flat 1 ATR. The ceilings are the desk's own:
0.16 of the risk (`domain/costs.MAX_SPREAD_RISK_FRACTION`) and 0.10 of a 2R target
(`strategies/surprise.SurpriseProfile.cost_share`).

| geometry | its source | stop, in ATR(14) at 15m | inside 0.16 of risk at 5m | at 15m |
|---|---|---:|---:|---:|
| `atr1` | the desk's own reference | 1.00 | 11 of 19 | 16 of 19 |
| `bar_range` | one whole bar, the unit `exotic-spreads-are-a-whole-bar-range` uses | 0.88-1.00 | 11 of 19 | 14 of 19 |
| `keltner_1p5x20` | the Squeeze's Keltner channel, 1.5 x ATR(20) | 1.49-1.58 | 14 of 19 | 19 of 19 |
| `atr2` | the desk's own reference | 2.00 | 17 of 19 | 19 of 19 |
| `bollinger_2sd20` | Bollinger(20, 2), a reversion stop past the band | 1.67-2.22 | 18 of 19 | 19 of 19 |
| `supertrend_3x10` | SuperTrend's defaults, 3.0 x ATR(10) | 2.91-3.01 | 19 of 19 | 19 of 19 |
| `chandelier_3x22` | Chandelier Exit, 3.0 x ATR(22) | 2.98-3.19 | 19 of 19 | 19 of 19 |
| `donchian20_width` | a Donchian-20 breakout stopped at the far edge | 4.31-4.97 | 19 of 19 | 19 of 19 |
| `swing20` | a structural stop at the 20-bar swing - a zone, a sweep, a breaker | 3.03-3.80 | 19 of 19 | 19 of 19 |

**What the screen kills before measurement.** A 1xATR stop at 5m is outside the gate on AUDUSD
(0.297), BTCUSD (0.208), ETHUSD (0.417), EURUSD (0.261), GBPUSD (0.277), USDCAD (0.338), USDCHF
(0.206) and USDJPY (0.185) - every FX pair and both coins. At 15m three remain outside: AUDUSD 0.164,
ETHUSD 0.226, USDCAD 0.185. So any catalogue rule whose stop is one bar's range or tighter is
arithmetically finished on FX at 5 minutes, which is where most of the catalogue's signal density is.

**And the catalogue's own default stops are affordable, which is not the escape it looks like.**
SuperTrend at 3 x ATR(10) costs 0.007-0.076 of its risk at 15m on all 19. That is arithmetic, not
relief: `widestop.md` measured mean R at m times the stop as the 1x mean divided by m, to within a few
thousandths (+0.180 / +0.120 / +0.089 / +0.059). Cost in R and edge in R both scale as 1/m, so
widening a stop moves every number in the table above and **cannot change a sign**. The screen says
whether a geometry is affordable at the edge size that geometry can produce; it never says a wide stop
fixes a losing rule.

### The weekday re-screen that `scalping.md` asked for

`scalping.md` ends with an open item: "the screen must be re-run on a **weekday** before anything is
built on it", because the first run held Friday's last FX quote. This run is a Tuesday and closes it.

| | `scalping.md`, Friday close | here, Tuesday | ATR(14) |
|---|---:|---:|---:|
| EURUSD round trip | 0.00011 | **0.00008** | identical: 5m 0.00030643, 15m 0.00055393 |
| EURUSD cost at 1xATR, 5m | 0.359 | **0.261** | |
| EURUSD cost at 1xATR, 15m | 0.199 | **0.144** | |
| XAUUSD round trip | 0.59 | **0.16** | |

The ATRs reproduce `scalping.md` to every digit, so the two screens differ **only** in the quote, which
is the point. Two things follow. FX is about 27% cheaper than that document records, and gold is
**3.7x** cheaper - so the claim there that "only FX is affected" by the weekend quote understates it,
and a metal moved more than any FX pair. And the broader lesson: both runs are a **single live
snapshot**, and two snapshots of the same book disagree by a factor of 3.7 on one instrument. A cost
screen wants a distribution of quotes over a week, not one read; until it has one, every cost number in
this document and in `scalping.md` carries that width.

## Family by family

Cost columns are the 15m figure for the geometry the script implies, from the table above. "Rule" is
what the published source says; **"unspecified" means the script names no entry, stop or target**,
which is true of 95.7% of them and is why so many rows are priced at the desk's reference geometry
instead of the author's.

### Dead on arrival: the input does not exist

| family | the claim | rule | verdict |
|---|---|---|---|
| Volume profile, fixed-range and visible-range (LonesomeTheBlue 26,770; LuxAlgo *Supply and Demand Visible Range* 26,682) | volume at price marks value and the levels that matter | bins volume by price over a window; POC, value area | **unbuildable.** `real_volume` is 0. [orderflow.md](orderflow.md) also measured POC/HVN/LVN levels bouncing like random prices on a venue that *does* have volume |
| VWAP, anchored VWAP, VWAP bands | the volume-weighted average price is where institutions trade | `ta.vwap`, session or event anchored | **unbuildable.** A VWAP weighted by a quote count is a time-weighted average wearing another name ([scalping.md](scalping.md)) |
| OBV, money flow, CMF, MFI, Williams A/D | volume confirms or diverges from price | cumulative signed volume against its average | **unbuildable** as published. Volume-free, the family's core collapses to close location in range, which **is** measured - see the shortlist |
| Cumulative volume delta, volume delta, footprint, absorption | the buy/sell split inside the bar | `ta.requestVolumeDelta`, lower-timeframe up/down volume | **unbuildable.** No `TradeTick`, no aggressor side ([scalping.md](scalping.md), [orderflow.md](orderflow.md) null on real Binance footprints) |
| Liquidity heatmaps, *Liquidity Depth Walls* (JOAT) | resting liquidity sits at visible prices | volume or estimated depth binned by price | **unbuildable.** `ticks_bookdepth` is 0 on every symbol |
| Gamma exposure, options flow (12 scripts in all) | dealer hedging pins or amplifies price | needs open interest by strike | **unbuildable** from this feed. The desk records option surfaces separately ([implied.md](implied.md)) and that is a different study |

### Already refuted here

| family | the claim | exact rule, where published | cost at 15m, median of 19 | refuted in | verdict |
|---|---|---|---|---|---|
| SuperTrend and ATR trend bands (85,331 + a dozen variants) | an ATR band flips with the trend | ATR(10), multiplier 3.0, on `hl2`; band ratchets, flip on close through it. Stop = the band | 0.020 | [battery.md](battery.md) (15 of 323 cells, crypto only); [indicators.md](indicators.md) | **already refuted** |
| MACD, RSI, stochastic, CCI, Williams %R, ADX/DI, Ichimoku, Parabolic SAR, Donchian, Keltner, Heikin-Ashi | a lagging oscillator or trend system times entries | textbook defaults; entry on the cross, exit unspecified | 0.013-0.059 | [battery.md](battery.md); [indicators.md](indicators.md) 0 of ~170 cells; [mean-reversion.md](mean-reversion.md) | **already refuted.** One survivor on fresh instruments in the whole program: crypto 4h CCI(20) at +0.06R |
| Bollinger reversion and breakout, %B, BandWidth, *Fibonacci Bollinger Bands* (33,025) | price returns to, or escapes, a volatility band | BB(20, 2); entry on re-entry or on the break | 0.029 | [mean-reversion.md](mean-reversion.md); [indicators.md](indicators.md); [trailing-zscore-fakes-reversion] (the shuffled twin took +0.111 of a +0.137 effect) | **already refuted** |
| Squeeze: *Squeeze Momentum* (118,116), *TTM Squeeze* (10,230), *TTM Squeeze Pro* (6,922) | compression precedes expansion; the histogram gives the side | BB(20) inside KC(20, 1.5); momentum = `linreg(close - avg(avg(hh,ll), sma), 20)`. Entry unspecified | 0.039 | [expansion.md](expansion.md) (shipped as a **risk** reading, AUC 0.781 held out; the breakout straddle nets -0.024R against a -0.030R null); [vol-impulse-trade.md](vol-impulse-trade.md) (-0.135R on 5,708 trades, and the 4h squeeze contributes nothing) | **already refuted, and measured again below** |
| Order blocks, supply/demand zones | the candle before a displacement holds unfilled interest | *Order Blocks & Breaker Blocks* (LuxAlgo, 30,718): swing lookback 10; on `close > top.y`, the OB is the lowest-low bar between the swing and its break. Entry unspecified | 0.017 (`swing20`) | [order-block-zones.md](order-block-zones.md) (returns 82%, direction a coin, -0.259R traded at 1d); [origin-zones.md](origin-zones.md) (0 passes in 3,697 cells) | **already refuted** as a fade. The *flip* is not - see the shortlist |
| Fair value gaps, imbalances, FVG magnets | an unfilled gap attracts price | a 3-bar gap; target the consequent encroachment | 0.017 | [imbalance.md](imbalance.md) (50.2% against a 49.2% placebo, breakeven 51.5%); [zone-fill.md](zone-fill.md) (fill probability **is** distance, AUC 0.881 with no fitted parameter); [tv-indicators.md](tv-indicators.md) (-0.278R) | **already refuted** |
| Market structure: BOS, CHoCH, MSB, CISD, auto structure maps (LuxAlgo SMC 180,328) | a break of structure calls the next move | pivot swings, label the break, draw the zone | 0.017 | [bos-predict.md](bos-predict.md) (side AUC 0.75 real, **0.755-0.757 on walks**); [lrc-retest.md](lrc-retest.md) (-0.291R over 167,501 trades); [smc-bos-reconcile.md](smc-bos-reconcile.md) | **already refuted** |
| Liquidity sweeps, stop hunts, SFP, turtle soup, inducement | price takes out liquidity, then reverses | poke past a prior extreme, close back inside | 0.017 | [sweeps.md](sweeps.md) (**0 of 2,629 cells** survive BH; primary -0.021R over 65,104 trades); [stophunt.md](stophunt.md) (0 of 180); [trap-levels.md](trap-levels.md) | **already refuted** |
| Auto support/resistance, pivot points, clustered swings, round numbers (67,693; 48,627) | repeated prices hold | *S&R Levels with Breaks*: `pivothigh(15,15)`, break confirmed by a volume oscillator > 20 | 0.017 | [pivot-families.md](pivot-families.md) (Classic, Woodie, Camarilla, DeMark, Fibonacci all within ±0.003 of a distance-matched placebo); [magnet.md](../../docs/magnet.md) (44.9% against 49.5%); [level-shield.md](level-shield.md) (1 of 210 cells); [focal-points.md](focal-points.md); [tv-indicators.md](tv-indicators.md) Part B (clustering adds nothing; real levels hold 58-59% against 56.5% on walks, too small to pay a stop) | **already refuted**, and the break gate is also **unbuildable** |
| Fibonacci retracement, extension, confluence, golden pocket | price turns at 0.382/0.5/0.618 and projects to 1.618 | levels off the last swing; entry at the level | 0.017 | [indicators.md](indicators.md) (the fib filter adds nothing at t>=3 anywhere); [pivot-families.md](pivot-families.md) (leg-ratio clustering -0.0012 to +0.0019 against shuffled bars, largest at 1.000 and a detector artefact); [structural-target.md](structural-target.md) for the projected target | **already refuted** |
| Harmonic patterns: Gartley, bat, butterfly, crab, PRZ | five-leg ratio patterns mark reversal zones | zigzag legs matched to ratio windows; entry in the PRZ | 0.017 | no study by name. Its **precondition** is refuted: [pivot-families.md](pivot-families.md) finds no clustering at the ratios the patterns use, and [chart-patterns.md](chart-patterns.md) uses the same zigzag machinery | **already refuted at the precondition.** Measuring the patterns adds a trial for a claim whose input is flat |
| Classical patterns: head and shoulders, triangles, flags, wedges, double tops, cup and handle | a shape predicts the break direction and the measured move | detectors on confirmed pivots; the measure rule as target | 0.017 | [chart-patterns.md](chart-patterns.md) (**18 of 18** break rates reproduced by a random walk; H&S breaks down 73.2% real, **74.5%** on an iid shuffle); [patterns.md](patterns.md); [eve-and-adam.md](eve-and-adam.md) | **already refuted** |
| Candlestick patterns (35,039) | a bar's shape signals rejection or continuation | engulfing, pin bar, doji, hammer, three soldiers, by body and wick fractions | 0.017 | [letter-shapes.md](letter-shapes.md) (**0 of 384** cells survive BH); [fuzzy-logic.md](fuzzy-logic.md) (-0.110R over 210,048 trades, crisp twin -0.100R); [fractal-twins.md](fractal-twins.md) (shapes call volatility, not direction) | **already refuted** |
| Elliott Wave (incl. the frame's top new script, *Elliott Wave Impulse 12345*) | impulse and corrective counts with Fibonacci targets | a labelled count plus ratio targets | 0.017 | [pivot-families.md](pivot-families.md): the falsifiable piece - Fibonacci leg-ratio clustering - is null, and the count itself is unidentifiable because the rule set can label almost any path | **already refuted** on its testable claim; the schema is not falsifiable |
| Wyckoff (8,280) | effort versus result, phases, spring and UTAD | volume against range at the end of a leg | 0.017 | [pivot-families.md](pivot-families.md): effort-vs-result AUC **0.5693** against **0.5791 on block-shuffled bars** - it reads *worse* than its own null. Also volume-dependent as published | **already refuted** |
| Gann: angles, squares, fans | price and time move on fixed ratios | angles from a pivot at a chosen scale | 0.017 | [pivot-families.md](pivot-families.md): the move-vs-horizon exponent is **0.5577** against 0.5788 block-shuffled; a calibrated angle is off by about 2.7x over a 10x horizon | **already refuted** |
| RSI/MACD divergence detectors (30,693; *VuManChu Cipher B* 24,951) | momentum diverging from price precedes a turn | pivots on the oscillator against pivots on price | 0.017 | [confirm.md](confirm.md) (divergence is among the 45 gates: **17 of 8,366** cells, 4 of 5 survivors fail deflation); [origin-zones.md](origin-zones.md) (RSI and SMT divergence as triggers, all negative) | **already refuted.** *Cipher B* also carries a naked `lookahead_on` |
| ZigZag, swing projection, *CIT ZigZag Projection* | the next leg repeats the last | alternating confirmed pivots, projected forward | 0.017 | [turning-points.md](turning-points.md) (swing structure does not persist beyond chance); [pivot-families.md](pivot-families.md) | **already refuted** |
| ICT sessions, killzones, HTF candles (60,219; 44,278) | moves originate in named windows | time windows, session ranges, prior-session levels | 0.017 | [calendar-returns.md](calendar-returns.md) (**volatility has a clock, drift does not**: FX ANOVA F 511.8 on absolute return, Deriv and walks 0.90-1.12); [origin-zones.md](origin-zones.md) (the killzone filter reads -0.19R); [rollover.md](rollover.md); [fxtod.md](fxtod.md) | **already refuted** as direction; the volatility clock is **shipped** |
| Seasonality, day-of-week, *Quarterly Cycles* | the calendar carries drift | per-period averages | 0.017 | [calendar-returns.md](calendar-returns.md); and `calendar-claims-need-the-weekday-control` - a z of -4.99 where placebo and shuffle both passed | **already refuted** |
| ML indicators: *Lorentzian Classification* (37,577), *Machine Learning Moving Average*, *Market Memory AI*, kNN strategies | a classifier over indicators calls the next few bars | k=8 nearest neighbours over 5 of {RSI(14), WT(10,11), CCI(20,1), ADX(20,2)}, distance `sum log(1+abs(df))`, label = the sign 4 bars on; volatility, regime (-0.1) and ADX filters; default exits exactly 4 bars after entry | 0.017 | [battery.md](battery.md) `ta_meta` (lifts markets +0.07R and **walks +0.28R**: fails its control); [lopez-de-prado.md](lopez-de-prado.md) (meta-labelling AUC 0.541 on markets and 0.541 on walks); [similarity.md](similarity.md) (0.4921 and 0.5120 against a 0.500 control); [fractal-twins.md](fractal-twins.md) | **already refuted.** Its `Use Worst Case Estimates` input defaults to **false**, so the trade stats it displays assume mid-bar entries, which the author's own tooltip says |
| Cycles: Ehlers-style filters, Schaff Trend Cycle, Fourier projections | a dominant cycle can be extrapolated | DFT or filter bank, projected forward | 0.017 | [fourier.md](fourier.md) (7 of 66 cells, AUC 0.511-0.533 against walks 0.498-0.506; in 6 of 7 the cycle part alone reads 0.488-0.501 and the straight line carries it; best cell grosses +1.65 bps against a 2.39 bps spread); [cycles.md](cycles.md) | **already refuted** |
| Kalman and adaptive moving averages, ZMA-likes | a filter tracks the state better than an average | Kalman gain on price, or a variable-period MA | 0.017 | [zma.md](zma.md); [zma-ml.md](zma-ml.md) (ML learns the z-score back and nothing more); [state-space-ml.md](state-space-ml.md); [state-space-filters.md](state-space-filters.md) | **already refuted.** `only-the-sign-survives-into-a-weighted-sum`: activation, scale and per-term offset are rank identities |
| Hurst, fractal dimension, variance ratio | persistence can be measured and traded | rolling R/S or DFA exponent | 0.017 | [fractal-twins.md](fractal-twins.md) (DFA on abs(returns) 0.67-0.84 against walks 0.53; on returns 0.513-0.535 against 0.508); [fractal-rules.md](fractal-rules.md) (direction AUC **0.500** on every reading and arm); [chan.md](chan.md) | **already refuted.** `VarianceRatio` is already in `till_infinity/indicators/trend.py` |
| ATR trailing stops, Chandelier Exit, *Saty ATR Levels*, *Market Structure Trailing Stop* | an adaptive stop keeps you in the move | 3 x ATR(22) from the running extreme | 0.020 | [stop-width.md](stop-width.md) (402 rules; no volatility-state-dependent rule beats a uniform one); [widestop.md](widestop.md); [stop-coverage.md](stop-coverage.md) (a fixed multiplier is not horizon-calibrated; a t-quantile scaled by sqrt(H) calibrates 12 of 30); [stop-anchor.md](stop-anchor.md) | **already refuted** as a state rule. The calibrated stop is **shipped** (`risk/quantiles.student_stop`), and `the-walk-is-the-best-calibrated-band` |
| Position-size and lot calculators | size to a fixed risk | risk % over stop distance | n/a | the desk sizes to a volatility forecast already, and `volatility-estimators.md` calls that the one use that survived | **already built** |
| Renko, range bars, Kagi, Point & Figure, *Renko-based strategy* | a travel-based clock removes noise | fixed or ATR box | 0.017 | [statespace-reference-frames.md](statespace-reference-frames.md): range time **manufactures** clustering - lag-one squared autocorrelation +0.0721 against -0.0071 on iid generated data, clustering 5.32x on a generated feed that has none. Imbalance time refuted outright | **already refuted.** Kagi and P&F are unmeasured by name and share the mechanism |
| Confluence dashboards, signal scoring, multi-indicator tables | agreement between indicators is information | a weighted count of sub-signals | 0.017 | [confirm.md](confirm.md) (17 of 8,366); [directional-questions.md](directional-questions.md) (no combination of 57-92 signals beats the better of always-long and always-short); [fuzzy-logic.md](fuzzy-logic.md) | **already refuted** |
| Currency strength, correlation matrices | relative strength leads | rolling correlation or a basket re-basis | - | [chan.md](chan.md); `relationships-are-contemporaneous` (vol and tails are huge, every lagged measure is null); and the FX store holds 8 USD legs with no crosses, so a strength meter is a re-basis | **already refuted**, and partly unbuildable from the local store |

### The detector is already in the package

`till_infinity/indicators/__init__.py` carries an audit of what Nautilus ships and what this desk
added. A catalogue script whose detector is listed there is a **configuration**, which is cheap and
worth saying:

- Moving averages, ATR, RSI, stochastics, MACD, Bollinger, Donchian, Keltner, linear regression,
  Aroon, OBV, VWAP: `FRAMEWORK` in `indicators/__init__.py`, taken from Nautilus. Two of Nautilus's are
  arithmetically wrong and are deliberately absent - `momentum.EfficiencyRatio` takes its numerator
  over one fewer step and reads `(period-1)/period` on a straight line, and `SpreadAnalyzer.average`
  stops updating once its window fills. Both are replaced here and pinned by tests.
- Pivots, trendlines, zigzag, swings: `indicators/trend.py` (`pivots`, `Trendlines`),
  `indicators/zigzag.py`, `indicators/pivots.py`.
- Changepoint and CUSUM: `indicators/changepoint.py` (`Changepoint`, `Focus`), `indicators/momentum.py`
  (`Cusum`). Nothing comparable in Nautilus.
- Fair value gaps, displacement, origins, levels, Kalman and particle level filters:
  `indicators/levels.py`.
- Fuzzy candlesticks: `indicators/fuzzy.py`, wrapping Nautilus's grader and adding the level question.
- Variance ratio: `indicators/trend.py`. Fear and greed: `indicators/sentiment.py`. Spread:
  `indicators/spread.py`.

## The one measurement: what the catalogue's most boosted volatility script is

`./.secrets/lab.sh run research/ideas/tv_squeeze.py CLOCKS=15,60`, seed 20261110.

*Squeeze Momentum Indicator [LazyBear]* is the second most boosted script in the whole community
library. Read off `pine-facade`, its source computes

    length = 20   mult = 2.0   lengthKC = 20   multKC = 1.5
    basis   = sma(close, 20)
    dev     = multKC * stdev(close, 20)
    rangema = sma(tr, 20)
    sqzOn   = (basis - dev > basis - rangema*multKC) and (basis + dev < basis + rangema*multKC)

**`mult`, the input labelled "BB MultFactor" with a default of 2.0, is declared and never used.** `dev`
is scaled by `multKC`. With both lengths at 20 the two centres are the same `sma(close, 20)` and the
multiplier cancels on both sides, so the published squeeze is exactly

    sqzOn  <=>  stdev(close, 20) < sma(tr, 20)

a close-to-close volatility estimator against a range estimator - the statistic `drive-q-from-the-range`
measured here (range-vs-close estimator ratio: 0.648 within strata on FX, 0.667 on 371 of 392
equities), thresholded at 1 and thrown away as a bit.

**The identity holds exactly.** Evaluating LazyBear's expressions as written and comparing them with
the reduction, bar by bar:

| clock | instruments | agreement | squeeze share |
|---|---:|---:|---|
| 15m | **19 of 19** | **1.000000**, min 1.000000 | 0.516 [0.445, 0.671] |
| 60m | 10 of 10 | 1.000000, min 1.000000 | 0.500 [0.458, 0.530] |

So a condition sold as finding compression **is on for half of all bars**, and it is on for 0.671 of
them on ETHUSD and 0.445 on USDCAD. The threshold is not a compression threshold; it sits near the
median because that is where the geometry of a near-random path puts the two estimators relative to
each other.

### What binarising costs

Three readings against the forward volatility: the published bit, the continuous ratio behind it, and
the desk's shipped incumbent (`tr_percentile`, the 14-bar mean relative true range ranked in its own
last 1,500 bars). Target = the mean relative true range over the next 20 bars, which shares **no bar**
with any feature. Non-overlapping rows only (every 20th bar, 998 a cell at 15m), Spearman, per
instrument because the deep-store set is 3 index CFDs and 7 Deriv synthetics and a median over the ten
is not a market reading.

**15m, real, |rho| against the forward volatility level:**

| instrument | `sqz_bit` | its block shuffle | `ratio` | its shuffle | `tr_pct` | `tr_pct` within strata |
|---|---:|---:|---:|---:|---:|---:|
| US SP 500 | 0.0495 | 0.0155 | 0.0164 | 0.0120 | **0.4720** | 0.1736 |
| US Tech 100 | 0.0160 | 0.0244 | 0.0082 | 0.0224 | **0.4622** | 0.1300 |
| Wall Street 30 | 0.0649 | 0.0224 | 0.0787 | 0.0470 | **0.4213** | 0.1242 |
| Volatility 25 Index | 0.0341 | 0.0392 | 0.0396 | 0.0192 | 0.0473 | 0.0509 |
| Volatility 75 Index | 0.0072 | 0.0131 | 0.0301 | 0.0099 | 0.0170 | 0.0246 |
| the other five synthetics | 0.0095-0.0397 | 0.0111-0.0653 | 0.0036-0.0476 | 0.0146-0.0556 | 0.0139-0.0410 | 0.0039-0.0544 |

- **The incumbent reads 0.42-0.47 on the three real markets and 0.014-0.047 on the seven synthetics**,
  whose volatility is constant by construction ([deriv-variants.md](deriv-variants.md): they realise
  0.99-1.01 of their named sigma). That is a control which **must** come back empty, and it does.
- **The squeeze bit reads 0.016-0.065 on the same three real markets, against 0.016-0.024 for its own
  block-shuffled twin.** It is at its shuffle. One eighth of the incumbent's rank correlation, and
  nothing that separates from a null which keeps its serial structure and breaks only its alignment.
- The continuous ratio is no better here (0.008-0.079 against shuffles of 0.012-0.047). On this
  target, at this horizon, on these ten instruments, the whole family is flat; what
  `drive-q-from-the-range` found is a *within-strata* effect on FX and equities, which these three
  index CFDs and seven synthetics are not.
- **The iid-walk arm reads |rho| <= 0.026 on every reading**, as it must.
- **Power.** On a target built to depend on the ratio and nothing else, the harness recovers
  |rho| **0.7460** [0.7148, 0.7765] for the ratio and **0.5499** [0.5245, 0.5988] for the bit. So the
  test is not blind, and binarising a statistic costs about **26%** of its rank correlation even when
  the dependence is entirely in the statistic.

### Two defects this harness found in itself, and one warning they carry

Both were caught by the arm that has to read zero, and both were in the *measurement* rather than the
model - which is the failure mode `costs.md` and `calibrating.md` warn about.

1. **A feature/target window overlap.** The first version averaged the *smoothed* true range over the
   forward window. `smooth_tr[i+1]` is a 14-bar mean ending at `i+1`, so it shares 13 of its 14 bars
   with the feature `smooth_tr[i]`. The incumbent then read |rho| **0.425 on a constant-volatility iid
   walk**. Fixed by averaging the raw range over `i+1 .. i+20`; the walk arm fell to 0.020.
2. **True range in price units.** A walk's level wanders over 20,000 bars and a price-unit range
   inherits the level on both sides of the comparison - the defect
   [volatility-estimators.md](volatility-estimators.md) records at rho 0.57 against a true 0.21. Fixed
   by dividing by the close, feature and target alike. The bit and the ratio were immune, being a
   comparison and a quotient.

**And the warning, which is the more useful result.** The natural way to write a
compression-to-expansion target - the forward window **over the trailing one** - puts the feature's own
quantity in its denominator. On that target the incumbent reads **0.718-0.773 on the seven
constant-volatility synthetics** and 0.474-0.520 on the three real markets: the arm that must be empty
is the *strongest* arm in the table. Any study whose target is a forward/trailing volatility ratio
should check a constant-volatility feed before quoting a number from it.
[expansion.md](expansion.md)'s own controls read 0.548 (iid) and 0.564 (GARCH), so the shipped model's
target does not carry this artefact; this is a caution for the next study, not a retraction of that one.

## Shortlist: three ideas, one of them worth running now

Ranked by expected value, with the honest reason each is where it is. Every one is **volatility- or
geometry-flavoured or carries a named open positive**; a new *directional* indicator starts from
[statespace-directional-edge.md](statespace-directional-edge.md), where a gate finds a planted drift at
z +2.90 and earns **+0.019 spread units, about 2% of a spread**, against the 1.0 it needs.

### 1. The breaker block: trading the zone that failed, not the zone that held

**The idea.** *Order Blocks & Breaker Blocks* (LuxAlgo, 30,718) and *Market Structure Break & Order
Block* (EmreKb, 65,011) publish a mechanical polarity flip that this desk's own version lacked: an
order block becomes a **breaker** when `min(close, open)` closes through its far edge, it is **deleted**
when `close` clears its near edge, and the flip is **confirmed** when a fresh swing lands inside the
broken zone's range. The trade is against the original zone's direction on a retest of the breaker.

**Why it is not already refuted.** [order-block-zones.md](order-block-zones.md) refuted the fade *to*
the zone (price returns 82% of the time, direction a coin, **-0.259R** [-0.408, -0.100] at 1d) and
[origin-zones.md](origin-zones.md) found **0 passes in 3,697 cells**. The *flip* is that document's one
unsettled positive: **+0.337R at 1d and +0.506R at 4h**, found only after two bugs were fixed, with the
doc itself saying "Unsettled" and the 4h confirmation half failing. This is a claim the old study could
not have tested, because it had no mechanical definition of when a zone has flipped; the script
supplies one.

**Cost.** Priced, not assumed: a structural stop at the 20-bar swing costs **0.006-0.074 of risk at
15m on 19 of 19 instruments** and 0.011-0.128 at 5m, median 0.017. It is affordable at every clock the venue serves.

| | |
|---|---|
| **the null it must beat** | 1/(1+N) at the target used, and the same trade through the same detector on matched iid and GARCH walks. `P(>= N R)` led with, not mean R |
| **the placebo arm** | a breaker declared at a **distance-matched prior swing with no order block behind it**, at the same duty cycle. This is the arm whose absence once turned a gap study into a measurement of mean reversion |
| **the control** | the **refuted arm kept in the run** - the fade to the un-flipped zone. If the flip beats its null and the fade does not, the reframing is real; if both beat it, the finding belongs to the old claim and the harness is wrong. Plus a discovery/confirmation split by instrument and by half, reported as a gating condition rather than a verdict, since the 4h half already disagrees |
| **what would kill it** | the 1d/4h disagreement surviving a wider universe, as 16 instruments to 29 once killed the only positive cell in a sixty-cell sweep |

### 2. The money-flow family with its volume removed, at a longer horizon

**The idea.** Strip the volume the venue does not send from OBV, CMF, MFI, Williams A/D and the
intraday-intensity family and what is left is **close location in range** - the statistic
[statespace-orderflow-from-bars.md](statespace-orderflow-from-bars.md) already measured. Real markets
close **nearer mid-range than a matched walk on 8 of 8** traded instruments while generators do the
reverse on **5 of 5**, and 21 of 24 traded directional cells beat a block-shuffled null against 2 of 15
generated - both of those being the one synthetic with a planted drift. That document names its own
next arm: the same features against the sign of the return over **2, 4, 8 and 24 bars**, looking for
where `edge x room` clears twice the spread.

**Why it is second and not first.** It is a directional claim, and the existing reading earns about a
**quarter of a spread**. It needs roughly a factor of eight, and the mechanism is one-bar absorption
that may not survive aggregation - which is exactly what the arm tests.

**What this survey changes about it.** Its cost arithmetic. That document priced EURUSD at an assumed
**1.9 bp** round trip because the cached `spread` column read 0.00; the terminal's weekday quote here is
**0.00008**, about **0.69 bp**. Part of the gap is a convention difference - `scalp_cost.py` charges one
spread per round trip, which is what crossing from ask to bid costs - and the rest is the weekend-quote
defect. **That is a factor of 2.75 on the only number standing between that arm and a pass, and it
should be resolved before the arm is run rather than inside it.**

| | |
|---|---|
| **the null it must beat** | the block-shuffled feature (the arm the original used), matched iid walks built from each instrument's own tick counts, and `edge x room >= 2x the measured round trip` as a pre-registered pass written before the run |
| **the placebo arm** | the same statistic on the matched walk, which has the same bar geometry and no book - and the generated feeds, which must keep reading the **opposite sign** |
| **the control** | the **one-bar horizon kept in the run**, because the claim is that a one-bar mechanism survives aggregation; and the AUC decay across 2, 4, 8 and 24 bars reported whatever it does |
| **what would kill it** | AUC decaying faster than room grows, which is the expected outcome |

### 3. Candle Range Theory out of sample - listed, and not recommended first

**The idea.** CRT is a TradingView-popular name for a bar that takes out the prior bar's range and
closes back inside it. [smc-conjunctions.md](smc-conjunctions.md) names it as the single corner worth a
pre-registered out-of-sample test: 1h context with a 15m entry on FX crosses, n 2,531, gap over its walk
**+0.105R** at a 2R target, **z +3.75**.

**Why it is third.** Three reasons, all in that document. The largest |z| expected under the null over
its 516 rows is about **3.2**, so 3.75 is at the edge of what multiplicity produces by itself. The three
CRT rows are one cell at three targets rather than three confirmations. And **none is positive in
absolute terms**: the 2R row grosses **-0.008R** before costs, so it beats its walk and still does not
pay. A fourth reason is practical: the finding is on **FX crosses**, and the local FX store holds eight
USD legs with no crosses, so confirming it needs data this machine does not have.

| | |
|---|---|
| **the null it must beat** | its own matched walk through the same detector, and absolute R above zero after the measured round trip - the second clause is the one it currently fails |
| **the placebo arm** | the same bar geometry at a random prior bar at a matched range percentile, since a CRT bar is selected for being wide |
| **the control** | the overlapping primitives kept in the run: a range engulf already takes out the prior bar's high on **0.706** of engulfing bars, so CRT and engulf are largely one event (Jaccard 0.552) and must be scored together or the trial count is wrong |

### And nothing else

No fourth candidate. The catalogue's volatility shelf - squeeze variants, BandWidth, ATR percentile,
volatility bands, ATR trailing stops, realised-volatility scripts, volatility seasonality - maps
one-to-one onto work that is already shipped here (`models/expansion.json`, `models/shocks.json`,
`structures/vol/envelope.py` with AgACI, `structures/vol/har.py`, `risk/quantiles.student_stop`, the
volatility clock), and where it was measured against the incumbent above it read an eighth of it. The
catalogue's directional shelf is the subject of
[battery.md](battery.md), [indicators.md](indicators.md), [confirm.md](confirm.md),
[chart-patterns.md](chart-patterns.md), [sweeps.md](sweeps.md),
[order-block-zones.md](order-block-zones.md), [pivot-families.md](pivot-families.md) and
[fourier.md](fourier.md), which between them cover more cells than this survey could add.

## What this survey did not cover

- **Families with no keyword in the frame.** Among them: Market Profile and TPO, Ichimoku variants
  beyond the base keyword, options-expiry and GEX tools beyond the 12 `gamma exposure` returns,
  statistical-arbitrage and pairs scripts, and anything whose name uses none of the 50 words.
- **The 42 closed scripts**, by definition. Their rules were not read and are not guessed at. Two of
  them sit in the frame's top thirty.
- **Scripts below the top 8 of their keyword.** 2,259 scripts were framed and 387 audited.
- **No script was executed.** Pine cannot be run from here, which is the same limit
  `research/tradingview/README.md` records for this desk's own indicator. Rules are read off the source,
  and the one re-implementation - LazyBear's squeeze - is pinned by an identity measured on 19
  instruments rather than asserted.
- **Nothing was traded.** The cost screen prices geometries and the squeeze harness scores a
  volatility reading; no R was measured for any catalogue family in this document. The R figures quoted
  are from the documents cited beside them.

## Caveats

- **The cost screen is one snapshot.** Two snapshots of the same book, taken two days apart, disagree
  by 3.7x on gold. Every cost figure here carries that width until a week of quotes replaces it.
- **The squeeze measurement reaches 10 instruments, of which 7 are Deriv synthetics.** The deep M1
  stores hold 300,000 bars for three index CFDs and 50,000 for seven synthetics; FX, gold and the two
  coins have 20,000 M1 bars, which is 1,314 bars at 15m and not enough for the incumbent's 1,500-bar
  rank history. **The identity covers all 19**; the skill comparison does not cover FX, metals or
  crypto at all, and `drive-q-from-the-range`'s effect was found on FX and equities.
- **The audit's flags are regex over stripped source, not a parser.** `volume` counts any read of the
  series, including a plot; `lookahead_naked` is a 200-character window heuristic. Both are reported as
  bounds with the hand-read cases beside them.
- **Boosts are popularity.** They say what is read, not what works, and the frame is ordered by them.
- **Three families are unmeasured here and predicted, not demonstrated, to fail**: Kagi and Point &
  Figure (sharing range time's mechanism), full Elliott and Wyckoff schemas (unidentifiable and
  volume-dependent respectively), and harmonic patterns (whose ratio precondition is flat). A prediction
  is not a result and they are listed that way.

## Re-running

    MODE=frame  OUT=.data/tvsurvey python research/ideas/tv_survey.py        # 50 keywords -> frame.csv
    MODE=source OUT=.data/tvsurvey TOP=8 python research/ideas/tv_survey.py  # Pine source, not committed
    MODE=audit  OUT=.data/tvsurvey TOP=8 python research/ideas/tv_survey.py  # audit.csv, families.csv
    MODE=rules  OUT=.data/tvsurvey python research/ideas/tv_survey.py PUB_175

    ./.secrets/lab.sh run research/ideas/tv_survey_cost.py CLOCKS=5,15 OUT=.data/tvsurvey
    ./.secrets/lab.sh run research/ideas/tv_squeeze.py CLOCKS=15,60 OUT=.data/tvsurvey

The frame and the audit need the network and no market data, so they run anywhere. The cost screen and
the squeeze harness read the lab's M1 stores, and the cost screen also reads the terminal's live
bid-ask through `research/harness/venue.quoted`, so both belong on the lab.

Outputs, all under `$OUT` and none committed: `frame.csv` (2,259 scripts), `keywords.csv`, `audit.csv`
(387 rows), `families.csv`, `cost.csv` (342 rows), `squeeze_cells.csv` (440 rows),
`squeeze_identity.csv`, and `src/*.pine` - **fetched source is other people's code and this repository
is public, so it stays in `.data/`.**
