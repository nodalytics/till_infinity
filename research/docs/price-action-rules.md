# The price-action rules as the sources state them

**Written 2026-11-10, before the measurement.** The result is
[`price-action.md`](price-action.md); this file is the standing statement of
what was measured, in the sources' own words, with the harness parameter that
encodes each clause and an explicit mark where the sources specify nothing.
[`zone-rules.md`](zone-rules.md) is the precedent and the reason: a rule that
moved while it was being measured produced a write-up nobody could read
against anything, and the fix is to freeze the rule in prose first.

**Every clause below carries the source it came from.** That column exists
because a rule the authors stated and a rule this desk had to invent are
different objects, and a later reader has to be able to tell them apart.

## The sources, and how many of them there are

| tag | what it is |
|---|---|
| **PA** | `priceaction.com/price-action-university/` - the start page plus the six `/strategies/` sub-pages and two `/beginners/` pages named in the brief |
| **LTTM** | `learntotradethemarket.com` - the `price-action-trading-forex` overview and five linked strategy pages |
| **VID** | a YouTube "Complete Price Action Course (4+ Hours)", auto-captions pulled with `yt-dlp` |

**PA and LTTM are one author, and they are not two sources.** Both are bylined
**Nial Fuller**; the PA start page's bio reads "He has a monthly readership of
250,000+ traders and has taught over 30,000+ students since 2008" and links to
`learntotradethemarket.com/forex-trading-course`, and "fakey" is his coined
term and appears on both. So this is **one method with two presentations**, and
counting them as two corroborating sources would inflate confidence in exactly
the way [`smc-conjunctions.md`](smc-conjunctions.md) warns about - two
published SMC frameworks turned out to be the same shape under two names. What
the second presentation is worth is narrower and real: **it states numbers the
first leaves qualitative**, and every such number is tagged LTTM below.

**VID is a different method and is dropped as a rule source.** Its captions
transcribe cleanly, so this is not a transcription problem. It is a
supply-and-demand / liquidity / market-structure course: over 7,253 caption
lines it says **"pin bar" 0 times, "inside bar" 0, "fakey" 0, "confluence" 0,
"key level" 0**, against "liquidity" 137, "supply" 146 and "demand" 162. It
names no author. It states no mechanical entry, stop or target - its numbers
are discretionary chart readings ("a 6.51 risk to reward" at 02:45:22 on one
example, "the stop loss under the low" at 02:34:04). It therefore cannot close
the gaps PA and LTTM leave, and the material it does cover is already measured
here in [`order-block-zones.md`](order-block-zones.md),
[`smc-conjunctions.md`](smc-conjunctions.md) and `sweeps.md`. Recorded, not
used.

### What each PA sub-page added

The brief required all six. Several added nothing, and that is itself a reading
on a method described as mechanical.

| page | what it added |
|---|---|
| `/strategies/inside-bar/` | **the only page with a complete entry and stop**: buy/sell stop at the mother bar's extreme, stop at the opposite end or the 50% level. No target |
| `/strategies/pin-bar/` | three entry *styles* named (at market, 50% retrace limit, on-stop) with no prices. No stop, no target, **no tail ratio** |
| `/strategies/fakey/` | the entry trigger ("breaks back past the inside bar or mother bar low or high"). No stop, no target |
| `/strategies/false-break-out/` | **nothing beyond the overview.** No definition past "a breakout that failed to continue beyond a level", no entry, no stop, no target, no bar count. Its one testable clause is a *range* rule: "wait for price to close outside of the range for two days or more" |
| `/strategies/pin-bar-inside-bar-combo/` | the combo's entry ("buy on stop entry just above the mother bar high") and a stop ("just above (or below) the inside bar") |
| `/strategies/support-resistance-levels/` | **nothing numeric.** "The article never defines key." Levels "connect price bar highs to other price bar highs or lows to lows", drawn as lines, "not an exact science". No touch count, no lookback, no tolerance |

**`fakey` and `false-break-out` are not the same construction, and only one is
codeable.** A fakey is anchored: it *requires* an inside bar and is a
three-or-four-bar pattern with a stated trigger price. A false break-out is
anchored to nothing - PA gives it no bar count, no close-back requirement and
no reference level, and explicitly admits versions with no pattern in them at
all ("More experienced traders can also trade false breakouts that don't
contain a price action trigger"). So the fakey is measured and the general
false break-out is **refused as unspecified**, not reported as null. The one
exception is its range clause, which is codeable and is carried as the fakey's
`CLOSE_BACK` sweep.

## The four patterns, as definitions

| clause | source | harness parameter |
|---|---|---|
| inside bar: "contained completely within the high to low range of the mother bar" | PA start | `inside()`: `high[i] <= high[i-1] and low[i] >= low[i-1]` |
| equal high **and** equal low is not an inside bar - "if you have two bars with the same high and low, it's generally not considered an inside bar" | PA inside-bar | the same predicate refuses the exact-equality pair |
| pin bar: "a long tail", "small real bodies in comparison to their long tails" | PA pin-bar | - **no ratio given** |
| pin bar: "you want to see the pin bar tail be two/thirds the total pin bar length or more", the rest "one/third the total pin bar length or less" | **LTTM** pin-bar | `TAIL_SHARES` - the method's own value is **2/3 of the range**, swept 0.50 / 0.60 / 0.667 / 0.75 |
| pin bar: "The open and close of the pin bar are near one end of the bar" | LTTM pin-bar | follows arithmetically from the tail clause and is not a second parameter |
| fakey: "a false breakout of an inside bar pattern ... closes back within the range of the mother bar or inside bar" | PA start, PA fakey | `BREAK_REF` and `CLOSE_BACK`, each swept over `inside` / `mother` because the source says "or" |
| fakey: one false-break bar or "a two-bar pattern" | PA fakey | `FAKE_BARS` swept 1 / 2 |
| inside-pin combo: "an inside bar with a pin bar for the inside bar" | PA start | `inside(i) and pin(i)` |

### What the sources do not pin down, and is therefore swept

* **the tail-to-range ratio.** PA gives none. LTTM gives 2/3. Swept, with 2/3
  inside the sweep and marked as the method's own.
* **the opposing-wick limit and the body's position.** Neither source states
  one. This repo's `indicators/candles.hammer` does - `TAIL_SHARE` 0.5,
  `STUB_SHARE` 1/7, a body in the far third - so the desk's own encoding is
  carried as a **separate arm** rather than substituted for the source's.
  `smc-primitives-overlap-and-are-closed` is the recorded reason: two
  detectors with the same name are usually two detectors.
* **how long a pending stop order lives.** Neither source says. `EXPIRY_BARS`
  swept 1 / 2 / 3.
* **the fakey's stop.** Neither source states one. Swept over the false-break
  extreme and the opposite end of the mother bar.
* **"key chart level".** Neither source defines it: no touch count, no
  lookback, no tolerance, no zone width. The harness reads the desk's own
  Kalman book (`indicators.levels.Levels`) and the parameter-free session
  pivots that [`level-bounce.md`](level-bounce.md) uses as its control, and
  **carries a distance-matched placebo level in every cell**.
* **the confluence factor count.** PA says only "the more confluent factors
  behind a signal the higher-probability it is considered". LTTM's filter page
  gives a working threshold - "see if two or more of them line up with the
  price action signal" - and its confluence page lists exactly five factors.
  `FACTORS` swept 0 / 1 / 2 / 3.
* **the trend.** LTTM: "an uptrend if it is making Higher Highs and Higher
  Lows (HH, HL)", "a downtrend is Lower Highs and Lower Lows (LH, LL)", with
  no swing method. Read with this repo's `strategies/structure.Fold`, whose
  `trend` label is that rule exactly, with `reach` swept - **not a third
  derivation**, because a second HH/HL rule would make these numbers
  incomparable with the one the desk trades.

## Entry and stop, which is where the two presentations earn their keep

| pattern | entry | source | stop | source |
|---|---|---|---|---|
| inside bar | "place a buy stop or sell stop at the high or low of the mother bar" | PA inside-bar | "typically at the opposite end of the mother bar", alternatively "near the mother bar halfway point (50% level)" | PA inside-bar |
| pin bar, at market | "enter the trade at the current market price", after "the pin bar pattern must be closed out" | PA pin-bar | **1 pip beyond the tail** ("1 pip below the low of the tail") | **LTTM** pin-bar |
| pin bar, on stop | "Buy on a break of the pin's high" / sell on a break of its low | **LTTM** pin-bar | 1 pip beyond the tail extreme | **LTTM** pin-bar |
| pin bar, 50% limit | "some pin bars will retrace to around 50% of the tail, so we can look to enter there with a limit order" | **LTTM** pin-bar | "just above or below the pin bar high or low" | **LTTM** pin-bar |
| fakey | "Enter as price breaks back past the inside bar or mother bar low or high, following the initial false-break" | PA fakey, LTTM setups | **not specified by either source** | - |
| inside-pin combo | "buy on stop entry just above the mother bar high" | PA combo | "just above (or below) the inside bar", or the inside-bar rule | PA combo |

**The 50% limit is ambiguous in the source itself** and the ambiguity is
recorded rather than resolved: LTTM says "50% of the tail" in one sentence and
"50% of the pin bar's length" in another. Both are encoded; the bar-midpoint
reading is the primary because it is the one PA's combo page also uses ("near
its 50% level").

## The target: absent from every source, and that decides the measurement

**No source states a target, a target method, or a numeric reward-to-risk.**
Not one of the fourteen pages fetched. The strongest statements are
qualitative - "Inside bars typically offer good risk reward ratios" (PA),
"a large potential risk reward" (LTTM) - and LTTM's pin-bar page says other
exits "are taught in the paid course".

This is the opposite of [`patterns.md`](patterns.md)'s situation, and it
changes what can be concluded. There, the books supplied a measured-move
target, so reward-to-risk was *determined by the geometry* and a pattern could
be ruled out on its shape alone against `need = (1 + cost) / (1 + R:R)`. Here
there is no geometry to rule out.

So the target is set as **`k` times the realised risk**, `k` in 1 / 2 / 3, and
risk is measured **from the entry, not from the pattern**
(`risk-vol-is-not-the-stop-distance`). On a driftless walk a target at `k`
times the risk is reached with probability `1/(1+k)` and the expected R is
**exactly zero at every `k`**, so no reward-to-risk can manufacture a result
and any departure from zero is the finding. That is the only honest way to
price a rule whose author did not state an exit, and it means **this study
measures the entry and the stop the sources do specify**, with the exit held at
a construction that cannot contribute.

## The clock

| clause | source |
|---|---|
| "Inside bars work best on the daily chart time frame" | PA inside-bar |
| "Inside bars are best played on daily and weekly charts" | LTTM setups |
| "stick to Fakey signals on the daily charts", later "4 hour and 1 hour" | PA fakey |
| "Pin bars work on all time frames but are especially powerful on the 1 hour, 4hour and daily chart time frames" | LTTM pin-bar |
| "Inside-pin bar setups are best on the daily chart time frame" | PA combo |
| "on lower timeframes there are just too many inside bars and many of them are meaningless" | PA inside-bar |
| "I personally don't go below the 1 hour chart" | LTTM setups, comment reply |
| "The lower the timeframe the less effective the signal is because of noise" | **LTTM overview, a reader reply by the author, not the article body** |

The last two are a **monotonicity claim across clocks** and it is measurable:
the same rule should read better at 1d than at 1h than at 15m. It carries a
confound this desk has already sized. `a-shorter-clock-multiplies-cost-in-r`
records that the same spread is **19x dearer at 15m than at 1d**, so a signal
that looks weaker on a fast clock may be entirely a cost effect. **Gross and
net are therefore reported side by side on every clock**, because "signals work
better on higher timeframes" and "costs eat signals on lower timeframes" are
different claims with one symptom and only the first is about price action.

Clocks measured: **1d primary**, with 4h, 1h and 15m for the monotonicity claim.

## Confluence, as the sources list it

PA: "at least a couple things line up with a price action entry signal". LTTM's
filter page: "a level that has at least two supporting factors behind it", and
"the more the merrier". LTTM's confluence page lists five and no more:

| factor | source wording | harness |
|---|---|---|
| trend | "a 'trend' is one factor of confluence in and of itself" | `Fold.trend` agrees with the trade's side |
| EMA layer | "I use the 8 and 21 day EMAs on the daily charts" | price inside or at the 8/21 EMA band, periods as stated |
| static horizontal S/R | "connect highs to highs or lows to lows" | the touch test from [`level-bounce.md`](level-bounce.md), with its placebo arm |
| event areas | "a price level or zone that saw a price action _event_" | **refused**: this is a level defined by a past signal at it, which makes it the same object as the pattern under test. Measuring it would be the lookahead `level-bounce.md` names |
| 50-61.8% retrace | "I personally watch the 50% to 61.8% retrace levels" | the retrace band of the last confirmed swing leg from `Fold` |

**The 50% retrace clause is probably a dead idea already, and the agreement is
measured rather than assumed.** [`displacement-origin.md`](displacement-origin.md)
defines the displacement origin as the halfway mark of the displacing body and
the fade to it is closed - 0 of 105 cells with a positive lower bound, and the
82% return rate is a statement about *distance*, matched by a price-matched
placebo on every class. "The 50% retrace of the last major move" is a
*multi-bar swing* midpoint where the origin is a *single-bar body* midpoint, so
they are not the same construction by definition. The harness therefore reports
their **agreement rate on real bars** - how often the two prices fall within
0.25 volatility units of each other - and if it is high the existing result is
cited rather than re-run.

## What is not re-run, because it is already measured here

| clause | where it is already answered | what this study does instead |
|---|---|---|
| how often an inside bar occurs, and against what null | [`inside-bars.md`](inside-bars.md): rate 0.140-0.168 on traded classes, ordering suppresses it by 0.046-0.072, a third to a half of that the hour-of-day cycle | inherits the **null design** - a generated walk has `order` 0 by construction, so a calendar-preserving shuffle is a required arm - and does not re-measure the rate |
| "at a key chart level": does price bounce at a level | [`level-bounce.md`](level-bounce.md) 168 cells null; [`level-shield.md`](level-shield.md) 1 of 210; [`magnet.md`](../../docs/magnet.md) 44.9% against a placebo's 49.5%; `level-signatures.md` 19 observables within 0.006 of AUC 0.5 over 6,902 touches | the level is a **conditioning factor on the pattern**, carried with the placebo arm, never re-tested as a claim of its own |
| the trend as a direction predictor | [`structure.md`](structure.md) nothing beyond `side`; [`bos-predict.md`](bos-predict.md) AUC 0.75 on walks as well as markets | `Fold.trend` is used as a **filter**, reusing the desk's own reading, and the filter is scored against its own duty-cycle twin |
| the 50% retrace as a fade target | [`displacement-origin.md`](displacement-origin.md), and `fade-to-value` in [CLAUDE.md](../../CLAUDE.md)'s kills | agreement rate only |
| a pattern's hit rate against its own geometry | [`patterns.md`](patterns.md): double bottom's 58% matched by a placebo at 57.6% | the matched-random-entry placebo is inherited as a required arm |

## The nulls and the controls, frozen

* **Every arm goes through the same detector over the same bar geometry.**
  `level_shield.ARMS` is imported whole: `garch-bars` (clustering and fat tails
  kept, path structure gone), `walk-geometry` (bar wickiness and the step
  distribution, no clustering), `bar-shuffle` (no memory).
* **A fifth arm is added for this study and is required, not optional.**
  `calendar-shuffle` permutes bars **within their hour-of-day bucket** at 15m,
  1h and 4h and within their weekday bucket at 1d, so the deterministic
  intraday cycle survives and the ordering does not. The inside bar is a
  two-bar statistic and the fakey a three-or-four-bar one, and
  `a-pair-of-bars-needs-the-hour-of-day-null` records that ordering suppresses
  two-bar statistics by 0.046-0.072 with about half of that the daily cycle -
  which a *generated* null has none of. A generated walk alone is therefore
  **not a sufficient null for these patterns**.
* **A matched random entry**, 20 draws per setup: the same side, the same stop
  *distance* and the same target *distance*, taken at a randomly chosen bar on
  the same instrument. This is simultaneously the geometry placebo
  [`patterns.md`](patterns.md) requires and the **duty-cycle control**, because
  the comparison is mean R per trade at a matched trade count.
* **A distance-matched placebo level** for the confluence arm: each level
  displaced by a random 1.5-3.0 volatility units and rejected if it lands
  within 0.70 units of a real one. `the-placebo-arm-selects-the-null` - any
  null whose placebo arm itself finds structure is rejected.
* **Both sides, always.** An inside bar is **sideless** - the source gives its
  direction from the trend or from a level, not from the pattern - so the long
  and the short are separate cells and a straddle arm takes whichever fires
  first. A pin bar and a fakey carry their own side.
* **The race starts on the bar after the fill.** `a-martingale-cannot-pay` and
  [`smc-conjunctions.md`](smc-conjunctions.md): settling on the fill bar won
  0.470 of 2R races against a required 0.333, because the fill bar's *other*
  extreme may have printed before the entry touch. A tie inside one bar goes
  to the stop.
* **Minimum risk 0.25 volatility units**, with refusals counted. A near-zero
  risk is the recorded fill artefact in [`walks-and-edge.md`](walks-and-edge.md).
* **Strata**: quintiles of trailing compression, of each arm's own
  distribution.
* **Block bootstrap by day**, blocks no shorter than the outcome window.
* **Per instrument, never only pooled** (`pooled-medians-invert-subgroups`),
  with Benjamini-Hochberg over every cell.
* **Cost first and in R**, `round_trip / risk`, against the desk's **0.16 of
  the risk** ceiling (`domain/costs.py`). The spread is the median recorded
  bid/ask per feed **per venue, never pooled**, and a feed with no quotes
  carries no costed number rather than a guessed one.
* **A power sweep before any null is reported.** A directional nudge of known
  strength is planted on the bars after each detected setup and swept, and the
  strength at which the test stops seeing it is reported.

## Deviations from this statement, with the number that caused each

Recorded here rather than folded into the text above, because a rule that
moved silently produces a write-up nobody can read against anything. None was
made after an outcome statistic had been seen on the quantity it changed.

**1. The entry is settled two ways, not one.** This file froze "a buy stop at
the mother bar's high" and said nothing about *where the race starts*, because
the sources' entry is a resting stop order and bar-level data cannot say where
inside a bar it filled. Settling from the bar after the fill - the choice
[`level-bounce.md`](level-bounce.md) and `smc_battery.py` both make - hands the
trade the whole favourable move from the trigger to that bar's close for free:
conditional on a buy stop filling, the bar closed *above* the trigger on
average, so the race begins nearer the target and further from the stop.
Measured on a driftless walk, where the answer must be zero, that read
**+0.2234R +- 0.0541 over 743 races**. So `fill_at` carries both: `trigger`,
the sources' rule as stated, and `close`, entry at the fill bar's close, which
is leak-free because the entry price and the first bar of the race are the same
instant and is a **different and worse trade** - a bar that ran a long way past
the trigger buys a wider stop and a worse R, as it would live.

**2. The placebo runs through the same construction, not beside it.** The first
version entered the placebo at a random bar's *close* while the real arm rested
a stop order at a breakout price, so it compared two entry mechanics rather
than two populations. On a walk that gap read **+0.2474R**; driven through the
identical construction at random anchors it reads **+0.0121R +- 0.0230**. The
placebo therefore picks random bars and applies the same entry, stop, side and
expiry to them.

**3. A third pin-bar encoding was added.** `indicators/fuzzy.py` (#358) grades a
bar's wicks and body **against its own rolling window**, which is the control
for a confound the fixed-fraction rule inherits:
`how-markets-differ-from-every-simple-process` measured real bars as *wickier*
than every simple process, so an absolute tail fraction fires more often on real
data than on a walk for mechanical reasons. All three encodings are run - the
sources' one clause, this repo's `candles.hammer`, and the graded one - and if
the fixed ones beat their walk where the graded one does not, the finding is the
confound.

## Every parameter, and where its value came from

The constant that encodes each clause, so a later result can be read against
what it was measuring. "swept" means no source states it.

| parameter | value(s) | from |
|---|---|---|
| `TARGETS` | 1.0 / 2.0 / 3.0 x the realised risk | **this desk**: no source states a target, and this is the construction that cannot contribute a result |
| `TAIL_SHARES` | 0.50 / 0.60 / **0.667** / 0.75 of the bar range | **LTTM** states 2/3; the rest is the sweep |
| `SHAPES` | `source` / `desk` / `graded` | the sources' one clause, `candles.hammer`, and `fuzzy.pin` |
| `GRADED_TAILS/STUBS/BODIES` | ordinals 1-3 / 0-2 / 1-3 | swept; `fuzzy.PIN_*` are the defaults |
| `EXPIRIES` | 1 / 2 / 3 bars | swept; neither source says how long a pending order lives |
| `PIP_PADS` | 0.0 / 0.02 volatility units | **LTTM** says "1 pip", which is 0.01-0.02 units at 1d on the majors |
| `BREAK_REF`, `CLOSE_BACK` | `inside` / `mother` each | **PA** says "or" in both places, so both are run |
| `FAKE_BARS` | 1 / 2 | **PA** allows a one-bar and "a two-bar pattern" |
| `REACHES` | 2 / 3 / 5 bars each side | swept; LTTM gives HH/HL with no swing method, so `Fold`'s reach is free |
| `FACTOR_COUNTS` | 0 / 1 / 2 / 3 | **LTTM** says "at least two"; swept around it |
| `EMA_FAST/SLOW` | 8 / 21 | **LTTM** verbatim, and **day** EMAs, so the factor is read at 1d only |
| `RETRACE_LO/HI` | 0.50 / 0.618 | **LTTM** verbatim |
| `TOUCH_VOL` | 0.10 units | `level_bounce.TOUCH_VOL`, unchanged |
| `PLACEBO_LO/HI/CLEAR` | 1.5 / 3.0 / 0.70 units | `level_bounce.placebo_books`, unchanged |
| `MIN_RISK_VOL` | 0.25 units | **this desk**: `walks-and-edge.md`'s minimum risk |
| `SETTINGS` horizon | 20 / 30 / 48 / 48 bars at 1d / 4h / 1h / 15m | `level_shield.SETTINGS`, unchanged, so the two studies' races are one object |
| `fill_at` | `trigger` / `close` | **this desk**, and the reason is the deviation below |
| arms | real + `garch-bars`, `walk-geometry`, `bar-shuffle`, `calendar-shuffle` | `level_shield.ARMS` plus the calendar arm this study adds |
| draws | 4 per surrogate, 20 per placebo | `level-shield.md` and `patterns.md` respectively |

## Harness

| script | what it runs |
|---|---|
[`price_action.py`](../ideas/price_action.py) | the detectors, the entry/stop/target construction, the barrier settlement, the arms |
[`price_action_run.py`](../ideas/price_action_run.py) | the panel: feeds x intervals x patterns x arms x sweeps, one JSONL row per cell |
[`price_action_power.py`](../ideas/price_action_power.py) | the planted-effect sweep |
[`price_action_report.py`](../ideas/price_action_report.py) | the cost screen and the tables in [`price-action.md`](price-action.md) |
