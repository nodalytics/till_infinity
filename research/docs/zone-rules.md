# The zone rule, as the desk gave it

**Specified 2026-10-07**, over an afternoon, in pieces. This is the standing
statement of the rule - what is being tested, in the desk's own words, with the
parameter that encodes each part and the value it is set to. Results live in
[`order-block-zones.md`](order-block-zones.md); this file is the rule itself, so
that a later result can be read against what it was measuring.

Code: [`zones.py`](../ideas/zones.py) (`ZONES=ob`),
[`test_zone_push.py`](../ideas/test_zone_push.py),
[`zone_sweep.py`](../ideas/zone_sweep.py),
[`zone_push_plot.py`](../ideas/zone_push_plot.py).

## The order the scan runs in

The desk gave the search order explicitly - **"look for impulsive candles, then
candle before this impulsive candle"**, and of that candle, **"that is your
supply/demand zone"**. So the impulse is the anchor and the zone is read
backwards from it, not the other way round.

### 1. The impulsive candles

> "then the impulsive move must have at least 2 momentum candles"
> "for the impulsive candles make the body at least 70% of the total candle range"
> "for the displacement candles, let's use the strong one instead of the weak ones"

`PUSH_N` consecutive candles, all one colour, **each** with a body of at least
`PUSH_BODY` of its own range, and **each closing past the whole range of the one
before it** - the strong form. The weak form, closing past the previous *close*,
is `PUSH_STRONG=0` and is kept only for comparison.

| | |
|---|---|
| `PUSH_N` | **2** |
| `PUSH_BODY` | **0.70** |
| `PUSH_STRONG` | **1** (strong) |

Every adjacent pair must clear, not only the first: a run that stalls in the
middle is a push and then a pause.

### 1b. The chain: the leg may skip a weak candle, and each pause is a zone

> "we will not use that approach but rather after finding 2 impulsive candles
> like that we look at the candle before that, it is zone 1, then we also look
> back for more impulsive candles, we stop when after looking back N candles we
> could not find impulsive candles anymore, so sometimes we might have 2
> impulsive then a candle that is not too strong then another impulsive"

`PUSH_N` **consecutive** candles cannot see that shape: one ordinary candle in
the middle of a leg ends the displacement and the whole setup is dropped, however
obvious the move looks on the chart. The chain fixes that, and it changes what a
zone *is*:

| | |
|---|---|
| **seed** | `PUSH_MIN` (**2**) consecutive impulsive candles start a chain |
| **extend** | from the last impulsive candle, look forward up to `CHAIN_GAP` (**1**) ordinary candles for the next one. Found, the leg continues; not found, it has ended |
| **zones** | **every pause inside the chain**, plus the candle before the chain - each one tested exactly as section 2 tests a single origin |
| **rank** | counted back from the end of the leg: **zone 1 is the pause nearest the end**, which is the one a reader marks first. `CHAIN_ZONES` keeps only the first few; 0 keeps all |

Chains do not overlap - once one has consumed its bars the scan resumes after it -
so an impulsive candle is never part of two legs.

This is `ZONES=chain`. The consecutive rule stays as `ZONES=ob` and is still the
one every number in this file was measured on, because a builder that replaces
the measured one without being measured itself would quietly invalidate the whole
study. The sweep runs both.

### 2. The candle before them - the zone

> "demand zone is the last candle before the impulsive move, vice versa for supply"
> "for the zone the colour of the candle does not matter"
> "it is normally a small candle"
> "so let's say for a demand we mark the full candle range from high to low, then
> the support is the open price if the candle was a green candle and the close if
> the candle was a red candle"

The bar immediately before the impulse. **Colour is not part of the rule** - the
desk said so after seeing the marked charts, superseding the order-block reading
it gave earlier the same day ("the last candle before the opposite move"). That
earlier reading is kept as `ORIGIN_COLOUR=1` so the two populations can be
compared, not so one can be chosen after the fact.

| | |
|---|---|
| **band** | the candle's **whole range, high to low** (`OB_BAND=range`) |
| **line** | the **near edge of its body**: the open if it closed green, the close if it closed red - `min(open, close)` for demand, mirrored for supply |
| **size** | "normally a small candle": its range at most `ORIGIN_MAX` x the first impulse candle's range. `ORIGIN_MAX` = **1.0** |
| **body** | at least `ORIGIN_BODY` of its range. **0.45** - a real candle rather than a doji |
| **distance** | `OB_BACK` = **0**: the impulse begins on the very next bar |

`OB_BACK` is the **lookback** the desk asked for directly: "sometimes the candle
before the impulsive candles might not be it, and we might need to still check
backward too for more info". With it at `d`, the scan will walk back up to `d`
bars from the impulse until it finds a bar that passes the zone tests - the size
cap, the body floor, and (if it is on) the colour. The nearest qualifying bar
wins, so raising `OB_BACK` only ever *adds* setups the adjacent-bar rule had
dropped; it never moves one that already qualified. Swept at 1, 2, 3 and 5.

### 2b. The zone must be fresh - untested before it is traded

> "and also the zone should be fresh"
> "what I mean by fresh is that it does not have to have been tested before"
> "the zone I mean"

| reading | where it lives |
|---|---|
| untested between going live and the entry | `Zone.ret` is the **first** bar back in the band |
| traded once | one entry per zone |
| **untested between the displacement and the setup being known** | **`FRESH`** - this was missing |

The third one was a real gap, not a filter. `live` is the bar by which the push,
the break of structure and the imbalance are all known - and the break has to
hold three bars and reach an ATR past the level, which takes time. The return
search began *after* `live`, so price could come back into the band while the
break was still being confirmed and the "first return" the study traded would be
the zone's **second** test. Nothing in the first build looked.

`FRESH` is **on**, because it corrects the rule rather than tightening it.
`FRESH=0` restores the old behaviour so the difference can be measured, and it
is small: 328 trades against 334 at 4h, 144 against 148 at 1d. The hole was real
and rarely fell through.

A separate parameter, `QUIET`, asks a different question - whether the band sits
where price had lately been *working*, measured as bars before the zone candle in
which something closed inside it. It is **off**, and its first run is a caution
about turning a word into a test: at 10 bars it left **twelve** trades on 1d and
three at 4h, because the leg that creates a demand zone arrives from above and
its last bar closes inside the band almost by definition. `QUIET_SKIP` ignores
that delivery.

### 3. The imbalance

> "in the momentum candles there must be at least 1 imbalance/fvg"

A fair-value gap of `FVG_MIN` (0.2) ATR or more on the leg. The first one
possible is the hole the displacement leaves over the zone itself.

### 4. The break of structure

> "it must break a previous high"
> "the demand zone must break a previous high"
> "without swing high or swing low"

A close above the highest high of the last `OB_LOOKBACK` (**20**) bars - **no
pivots anywhere**, which the desk asked for directly. It must hold: no close back
through the level for 3 bars, and 1 ATR beyond it within 5.

The answer to **"does a BOS always follow after the movement of the
displacement?"** is **no** - about one displacement in six, and it is the
biggest filter in the chain.

### 5. The return

> "also, the play might not happen immediately it might happen later even days ahead"

The first bar back inside the band, up to `EXPIRE` (**300**) bars later - 50 days
at 4h.

### 6. The confirmation

> "after it returns to the zone let's wait for a candlestick pattern as
> confirmation, looking at pinbars/hammers or candle with medium to long lower
> wick if it was a demand zone or support level"

Three readings are run side by side, which is how the confirmation itself gets
priced rather than assumed:

| trigger | rule |
|---|---|
| `touch` | **no confirmation**: a resting limit at the zone's near edge |
| `pin` | the strict pinbar: 60%+ of the range below the body, a body of a third or less, closing in the upper half |
| `wick` | **the desk's "medium to long"**: a lower wick of `WICK_MIN` (**0.40**) or more of the range, longer than the body, closing in the upper half |

`pin` is a subset of `wick`, so the pair measures what the strictness is worth.
Neither requires the candle to close green: a hammer that closes red still
rejected the low, and the close-in-the-upper-half test is the rejection claim.

All of it mirrors for supply: upper wicks, a bearish impulse, a close below the
20-bar low.

### 7. Open question: does the approach decide whether it holds?

> "the momentum candles with which it comes back to the zone matters before the
> candlestick pattern - if the candles start becoming choppy as it is getting
> closer back to the zone ... if it does not slow when getting closer to the
> zone, the zone might get voided"

Not part of the rule yet - a prediction about it, with a sign, which is what
makes it testable. Four readings of the approach, all from bars **strictly
before** the bar that re-enters the band, because the touch entry is a limit
resting through that bar:

| | |
|---|---|
| `app_decel` | the near half's speed over the far half's. Below 1 is slowing into the zone |
| `app_speed` | ATR a bar over the whole approach |
| `app_body` | mean body as a share of range: momentum against chop |
| `app_run` | consecutive bars closing the zone's way at the end |

Scored against the **hold rate** - no close beyond the band's far edge within the
reaction window, a property of the zone rather than of any trade - and against
the R actually earned, so a feature that sorts holds but not money shows up as
that. [`zone_approach.py`](../ideas/zone_approach.py), with a within-symbol
shuffle of the feature as the null and Benjamini-Hochberg across the lot.
**Answered in [`zone-approach.md`](zone-approach.md): no, and at 1d the sign is
the other way round.**

## What is given and what is fitted

This matters more than any single number. **Given** by the desk and therefore not
chosen by any result: `PUSH_N` 2, `PUSH_BODY` 0.70, the strong push form, the
colour-agnostic zone candle, the full-range band, the body-edge line, the
imbalance requirement, the break of a previous high without pivots, the late
return, and the wick confirmation.

**Not given, and so carrying a degree of freedom each**: `OB_LOOKBACK` 20,
`OB_MINLEG` 1.5, `ORIGIN_BODY` 0.45 (set after a first run at 0.50 - one value
tried with the first's result visible), `ORIGIN_MAX` 1.0, `WICK_MIN` 0.40,
`WINDOW` 36, `HOLD_DAYS` 15, `EXPIRE` 300.

[`zone_sweep.py`](../ideas/zone_sweep.py) runs each of these one at a time around
the given setting. It is read for **shape, not for a maximum**: a result that
survives a parameter's whole range is a property of the market, one that lives at
a single value is a property of this sample. The sweep selects nothing - whatever
the desk keeps is confirmed once, on instruments the rule never saw.

## Seeing it

[`zone_push_plot.py`](../ideas/zone_push_plot.py) draws what the scan marked, in
the terms the rule is written in: the impulsive candles boxed in gold, the candle
before them boxed in black, that candle's whole range carried forward as the
band, the body-edge line through it, the break of structure, the first return,
and the confirming wick. Asked for on 2026-10-07 - "can you give me a chart of
what you marked as an impulsive candles" - and it is the cheapest check there is
that the code is finding what the desk means.

    OUT=.data/zoneob_marked WANT=ob SYMBOLS=EURUSD,XAUUSD,BTCUSD INTERVALS=4h,1d \
      MT5BT_DB=... python research/ideas/zone_push_plot.py

# What the sweep found

**Measured 2026-10-07.** Twenty-four arms, 135 cells, `.data/zsweep4/sweep.csv`,
on the sixteen instruments the rule was developed on - twelve FX pairs, gold,
silver, BTC and ETH - at 4h and 1d.

**This is a development-set sweep and it selects nothing.** At a 90% interval
about fourteen of 135 cells clear zero by chance; twenty-four do, and **twenty-three
of those twenty-four are negative**.

> Run twice: once before the freshness correction and once after. The correction
> removes six trades of 334 and no figure moves by more than 0.01R, so the two
> runs agree and the numbers below are the corrected one.

## The base rule, in full

| iv | trigger | n | long | win | R | 90% interval | coin | at market | flipped |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|
| 1d | touch | 144 | 51% | 29% | -0.104 | [-0.397, +0.231] | +0.055 | -0.778 | +0.735 |
| 1d | pin | 41 | 49% | 54% | **+0.211** | [-0.157, +0.634] | +0.022 | -0.073 | -0.186 |
| 1d | wick | 75 | 52% | 48% | +0.087 | [-0.192, +0.400] | +0.030 | -0.064 | +0.071 |
| 4h | touch | 328 | 59% | 30% | -0.005 | [-0.176, +0.167] | +0.100 | -0.779 | +1.145 |
| 4h | pin | 86 | 62% | 33% | **-0.368** | [-0.558, -0.168] | -0.266 | -0.415 | +0.173 |
| 4h | wick | 153 | 58% | 36% | -0.149 | [-0.337, +0.050] | -0.028 | -0.197 | -0.033 |

**Exactly one cell of 135 is positive with its interval clear of zero**:
`origin_small` at 1d `pin`, +0.567 [+0.033, +1.220], on **23 trades**. One cell,
the smallest population in its column, from looking 135 times.

## The strong displacement is a no-op

The desk asked for the strong form - the second candle closing past the first's
whole range - in place of the weak one. It changes almost nothing:

| | n | R | win |
|---|---:|---:|---:|
| strong (`PUSH_STRONG=1`), 4h touch | 328 | -0.005 | 29.6% |
| weak (`PUSH_STRONG=0`), 4h touch | 329 | -0.003 | 29.6% |

**One trade in 329.** At a 70% body floor a candle that closes past the previous
*close* has nearly always closed past its *high* too, so the two forms select the
same population. The distinction only had room to matter at a looser body floor,
where the first build measured it - as a *filter*, on the 84%-long population -
so that earlier reading ("the strong form is worse than the weak one") should be
discarded rather than reversed.

## The lookback breaks the one positive cell

`OB_BACK` - the desk's "check backward too for more info" - lets the scan walk
back from the impulse until it finds a bar that passes the zone tests. It can
only **add** setups; it cannot remove one that already qualified.

| | 4h touch n | 4h touch R | 4h pin R | 1d pin n | **1d pin R** |
|---|---:|---:|---:|---:|---:|
| `OB_BACK` 0 | 328 | -0.005 | -0.368 | 41 | **+0.211** |
| `OB_BACK` 1 | 429 | +0.001 | -0.341 | 58 | -0.006 |
| `OB_BACK` 3 | 534 | -0.006 | -0.249 | 91 | -0.075 |
| `OB_BACK` 5 | 603 | +0.034 | -0.196 | 101 | **-0.089** |

The 4h figures do not move - and 4h `pin`, the worst cell in the table, improves
steadily as the population grows, which is what a sampling artefact does when you
dilute it. The **1d `pin` result goes from +0.211 to -0.089 as its population
goes 41 to 101**.

That is the cheapest available test of a small positive cell: widen the
population along an axis that cannot remove the trades you already have. It
failed. Those 41 trades were a favourable subset of a rule that is flat.

## Every parameter is a plateau

Across all twenty-four arms, with no confirmation:

| | min | median | max |
|---|---:|---:|---:|
| 4h touch | -0.550 | **-0.005** | +0.862 |
| 1d touch | -0.672 | -0.133 | +0.154 |

Both extremes are the smallest populations in the sweep (`push_n3` n=37,
`push_n4` n=2). Nothing in the middle moves the result: `OB_LOOKBACK` 10 against
40, `OB_MINLEG` 0 against 3, the band body-high against wick-high, the clip on or
off, the window 12 bars or 36, the hold 5 days or 15 - each lands within 0.1R of
the base.

That is the useful finding. **The zone rule's parameters are not where its result
lives.** A rule whose answer is the same from `OB_LOOKBACK` 10 to 40 is not being
tuned - and a sweep that cannot move it cannot have found its result by tuning
either.

Two arms look like exceptions and are not. `push_body_80` is +0.168 at 4h and
**-0.475** at 1d; `origin_colour` is +0.334 at 4h and **-0.425** at 1d. Opposite
signs across timeframes on 104 and 74 trades is what noise looks like when it is
given two chances.

## The confirmation splits clean across timeframes

The one consistent structure in the table, and it points both ways:

| | pin minus touch | positive in |
|---|---:|---:|
| **4h** | **-0.341** | **0 of 22 arms** |
| **1d** | **+0.271** | **20 of 22 arms** |

`wick`, the looser reading, sits between them both times (-0.107 and +0.164), as
a superset of `pin` should.

Waiting for a candlestick confirmation **costs about a third of an R at 4h and
pays about a quarter at 1d**, in essentially every parameter arm. Arms share most
of their trades, so this is two observations rather than forty-four - but two
that survive every change made to the rule around them.

The win rates say what it is doing: at 1d, `pin` wins 53.7% against `touch`'s
28.5%. The confirmation is not finding better trades, it is **refusing the ones
price went straight through** - worth more on a daily bar, where the next bar is
the whole day, than on a 4h bar, where waiting gives up a quarter of the move.

**But the lookback arms break the 1d half of it** (above), so what is left is the
4h half: confirmation at 4h is reliably expensive. That is a real and usable
negative.

## Freshness, and the reading that was not meant

`FRESH` - the zone untested between the displacement and the setup being known -
costs six trades of 334 and moves nothing. The hole it closes was real and rarely
fell through.

`QUIET` - the band sitting where price had not lately been working - is a
different claim and a dead end at these settings: 328 trades become **71** at 20
bars and the result gets worse (-0.005 to -0.162). A filter that removes 78% of a
flat population and makes it worse is removing signal or nothing; either way it
is not what "fresh" meant.

## The thing that does move, and why it is probably not an edge

`flip` - the same fills and stops, entered at market, on the **opposite** side -
is positive in every arm and both timeframes, median **+1.05R** at 4h and
**+0.74R** at 1d, intervals clear of zero in every `touch` cell.

The column beside it explains most of that. `straight`, the *same* side at
market, is **-0.78R** across the board while the real limit entry is -0.005R.
Entering at market once price has reached the zone is three-quarters of an R
worse than resting a limit at its edge, and `flip` is `straight` reflected.

What survives the reflection is small and points where everything else this week
has pointed: **price that reaches a zone tends to keep going through it**. The
band is not holding - which matches the measured hold rate of ~50% at 1d and ~46%
at 4h in [`zone-approach.md`](zone-approach.md), and
[`magnet.md`](../../docs/magnet.md) on levels not being magnets.

## 1h: with five times the sample, the rule is reliably negative

Asked for 2026-10-07 along with weekly. 1h is the only interval where this study
has real power - 721 trades at the desk's setting against 328 at 4h and 144 at
1d, and 1,624 at the loosest arm - and it is the clearest answer in the file.

| arm | trigger | n | long | win | R | 90% interval |
|---|---|---:|---:|---:|---:|---|
| base | touch | 721 | 49% | 18% | -0.147 | [-0.335, +0.058] |
| base | pin | 220 | 52% | 21% | -0.249 | [-0.510, +0.025] |
| base | wick | 366 | 52% | 24% | **-0.241** | **[-0.427, -0.037]** |
| `PUSH_BODY` 0.60 | touch | 1394 | 49% | 20% | **-0.175** | **[-0.294, -0.040]** |
| `PUSH_BODY` 0.60 | pin | 448 | 53% | 27% | **-0.182** | **[-0.339, -0.019]** |
| no body floor | touch | 1624 | 47% | 18% | **-0.241** | **[-0.342, -0.137]** |
| no body floor | pin | 513 | 50% | 21% | **-0.364** | **[-0.513, -0.209]** |
| `OB_BACK` 5 | touch | 1441 | 49% | 20% | **-0.128** | **[-0.248, -0.005]** |
| `OB_BACK` 5 | pin | 521 | 52% | 26% | **-0.183** | **[-0.330, -0.029]** |

**Every arm and every trigger is negative, and ten cells of fifteen have their
whole interval below zero.** Not one is positive. The long share is 47-52%, so
there is no skew doing it, and the strong-versus-weak push is a no-op here too -
721 trades against 723.

This is what the 4h and 1d tables look like when they are given enough trades to
say something. The pattern across the four intervals is the one a zero-or-worse
edge produces:

| | n | R |
|---|---:|---:|
| 1h | 721 | **-0.147** |
| 4h | 328 | -0.005 |
| 1d | 144 | -0.104 (`pin` +0.211) |
| 1w | 33 | -0.036 |

The more trades an interval has, the more clearly negative it reads. The one
positive cell in the study sits on the interval with the fewest trades, and
[the lookback already broke it](#the-lookback-breaks-the-one-positive-cell).

The confirmation agrees with 4h and not with 1d: `pin` minus `touch` is **-0.102**
at 1h on the base arm and negative in four arms of five. Two intervals now say
waiting for a candlestick costs money and one says it pays, and the one that says
it pays has 41 trades.

## Weekly: the rule is too selective to measure there

Asked for 2026-10-07, "let's run it on more time, like 1h and weekly". There are
**no weekly bars in `mt5bt.db`** - 15m, 1h, 4h and 1d only - so the weekly study
resamples the daily series, Monday to Monday (`weekly()` in
[`zones.py`](../ideas/zones.py); flooring by 604800 would cut the week on a
Thursday, because the epoch was one, and split every weekend across two bars).

| | n | long | win | R | 90% interval | at market | flipped |
|---|---:|---:|---:|---:|---|---:|---:|
| 1w `touch`, 16 instruments | 33 | 79% | 55% | -0.036 | [-0.279, +0.195] | -0.658 | +0.492 |
| 1w `touch`, **all 76** | 36 | 78% | 56% | -0.020 | [-0.241, +0.206] | -0.693 | +0.532 |
| 1w `pin` | 5 | 100% | 80% | +0.301 | - | +0.846 | -0.144 |
| 1w `wick` | 12 | 67% | 83% | +0.100 | - | +0.174 | -0.232 |

**Sixty extra instruments buy three extra trades.** That is the whole result:
weekly bars need a long daily history and only the majors have one, so the
population is set by the calendar and not by the instrument list. Loosening the
rule does not rescue it either - dropping the zone-candle body floor takes it to
68 trades and `OB_BACK` 5 to 69, both still flat (-0.052 and +0.010).

Two things worth recording anyway:

* the weekly zones are **33 long against 13 short** - 72% long at the *zone*
  level, not only at the trade level, so it is not the dataclass skew returning.
  On 46 zones that is about three standard errors, and the likely cause is
  mechanical: the break of structure wants a close above the 20-bar high, which
  a twenty-four-year window hands to anything with a secular uptrend
* the `pin` and `wick` cells are **5 and 12 trades**. They are in the table so
  that nobody reads their absence as a result, and for no other reason

Weekly is not a timeframe this rule can be tested on. It would need either a
much looser rule - which the sweep says costs nothing and gains nothing - or
decades more data.

## What is left

* **4h: confirmation is expensive**, reliably, across every arm. Negative, usable.
* **1d: nothing survives the lookback.** The only positive cell in the table is
  one of 135 at n=23.
* The held-out instruments produced about a hundred zones in total and no cell
  reached thirty trades, so they cannot confirm anything at these settings. What
  this needs is **more time, not more instruments**.
* Nothing here should be traded.
