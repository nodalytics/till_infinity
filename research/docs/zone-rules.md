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
the given setting, and [`zone-sweep.md`](zone-sweep.md) is what it found. It is read for **shape, not for a maximum**: a result that
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
