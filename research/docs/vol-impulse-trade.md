# A 15-minute impulse out of a four-hour squeeze, traded: gross zero, net its spread

Measured 2026-11-08 on the lab with
[`vol_impulse.py`](../harness/vol_impulse.py), over the production detector in
[`strategies/volimpulse.py`](../../till_infinity/strategies/volimpulse.py): the
five markets the rule names at a 15-minute base, 276,423 to 294,524 bars each
(11.8 years, 2015-01-02 to 2026-11-05), 5,708 non-overlapping trades.

The rule, `VI_M15_imp_H4sq`, as the operator specified it: a four-hour squeeze
(the range of the last 24 four-hour bins, over the four-hour ATR, in the bottom
20% of the last 750 bins), then a 15-minute bar moving at least 3x a **frozen**
HAR forecast, entered in the impulse's own direction at the next minute's open
at a real bid/ask, no entries 19:00-23:00 UTC, closed 16 bars later on the
clock with no stop and no target, scored in R where 1R is the 3x trigger.

| question | verdict |
|---|---|
| Does the rule make money? | **No. -0.1347R a trade** pooled over 5,708 trades and 2,076 days, day-block interval **[-0.2015, -0.0709]**, and negative on **5 of 5** markets. |
| Is the loss the signal or the spread? | **The spread.** Gross is **-0.0498R** and the quoted round trip is **0.0849R**. Gross is indistinguishable from zero at this sample: the interval's half-width is 0.065R. |
| Does it beat a coin on the same dates and geometry? | **No, it loses to one.** The coin arm's own 200-draw null is -0.0819 +- 0.0384 and the real arm sits at -0.1347, **beaten by 91.0% of the draws**. The sign-flip surrogate agrees: -0.0828 +- 0.0368, beaten by 89.5%. |
| **Does the squeeze contribute anything?** | **No, and this is the rule's central claim.** The impulses the squeeze *refused* read **-0.1197** [-0.1523, -0.0866] over 20,934 trades against the squeeze's **-0.1347**. The squeeze stratum is 0.015R *worse*, inside the noise of either arm. The squeeze also carries almost no information about *when* an impulse happens: **19.9% to 22.6%** of impulses land in it, against the 20% a quantile admits by construction. |
| Is the signal specific to the moment? | **No.** The same signal filled **8 bars late** reads **-0.1293** against -0.1347 - the same number. |
| Is it being in the market at those times? | Partly. An hour-matched random-entry arm reads **-0.0890**, which is *better* than the rule. |
| Does the verdict depend on the specification's ambiguity? | **No.** Ranking the unadjusted four-day range instead of the ATR-adjusted one reads **-0.1328**. |
| Does the frozen date's look-ahead matter? | **No.** A HAR frozen before 2019 and scored on 2019-2026 only reads **-0.1150** [-0.1924, -0.0369] over 3,853 trades. |
| Is the live +1.87R reproducible? | **A single draw, and not one this rule would have taken.** The 03:00 UTC bar on 2026-11-06 moved **down** 6.71bp against a 2.432bp forecast - a ratio of **2.76**, below the 3.00 trigger, on the **sell** side while the desk bought. The direction was right: a long held the rule's 16 bars paid +1.35R at the quoted spread. But this rule's trades have sd **2.81** and **16.6%** of them reach +2R, so +1.87R is a **0.7-sigma** draw. And the spread at that fill was **71 points against the 10 quoted**, which turns +1.35R into +0.75R. See *The one live trade*. |
| Should it be enabled? | **No.** Nothing here licenses it. The leaf is registered and in no default. |

## Which part of `impulse-vol.md` already answered this, and which part did not

[`impulse-vol.md`](impulse-vol.md) measured this conditioning over the same
panel three days earlier and is the reason this was not a hunt. Keeping the two
apart matters, because the sentence most likely to be quoted is about the wrong
channel.

**Already answered, and this run only confirms it:**

* **That the slow leg adds nothing.** *"A 4-hour squeeze with a 15-minute
  impulse reads `d_rv` 0.225 against 0.226 for the single-timeframe squeeze and
  0.226 for no condition at all."* That is the **volatility** channel - how much
  price will move - and it is the channel this desk can forecast. This run finds
  the same thing on the **direction and money** channel, which is a different
  measurement of the same conclusion rather than a new one.
* **That the direction reading does not pay.** At the headline cell USDCAD read
  **-0.228** of a forecast unit at trigger 3 over 12 bars, a *reversion*, with
  its interval containing its own round trip; and
  [`trigger-expectancy.md`](trigger-expectancy.md) read the signed continuation
  at trigger 3.0 over 12 bars at **-0.069** pooled with 0 of 6 instruments
  clearing cost at any threshold. This rule takes the **continuation** side at
  trigger 3 over 16 bars, so its sign was already known to be the wrong one.
* **That the mechanical part of that is real.** Selecting on `|r| / vol` tilts
  to a small denominator, which is why the constant-volatility synthetics read
  -0.033 and -0.044 in `trigger-expectancy.md`. Part of this run's -0.05R gross
  is that, and nothing here separates the two.

**Not answered by it, which is why this exists:**

1. **The trade.** Both impulse studies end on the same sentence - *"there is no
   stop, no target and no fill model"* - and neither computes an R. Four things
   change when it becomes one, and each can move a number on its own: the fill
   is the **next bar's open** and not the signal bar's close; **one position at
   a time**, which removes 28.6-36.3% of the events; the cost is charged in R
   against a risk unit that is the **trigger** rather than a forecast unit; and
   the **hour cut** removes another 7.0-12.6%.
2. **A frozen HAR as the denominator.** Every impulse reading on this desk used
   `EWMA(|r|, 60).shift(1)` or the statespace fold's surprise. A HAR appears as
   a *forecaster* arm in [`vol-gate.md`](vol-gate.md) and has never been the
   thing that defines the event set. It changes the event set materially: the
   HAR carries no intraday seasonal, so firings concentrate at 12-15 UTC (280
   of 2,332 EURUSD firings in the 13:00 hour alone against 15 in the 03:00
   hour), which is why the random arm here is hour-matched.
3. **1R as the trigger size.** No study on this desk sets R from the trigger.
   The consequence is the number this run leads with: **cost in R is 0.065 to
   0.095**, which is a quarter to a third of what the same spread costs against
   a one-ATR stop and is why the rule is affordable at all at 15 minutes.
4. **Whether the squeeze stratum differs from its complement as a traded
   book.** `impulse-vol.md` compared the squeeze band's *level* of forward
   volatility; nothing compared squeeze impulses against not-squeeze impulses
   as two books with the same fills.

Nothing in this run reopens the direction claim. `findings.md`'s standing
position - *this desk can forecast risk and cannot forecast direction* - is
what it reads.

## The rules, as frozen before the run

| | |
|---|---|
| base | 15-minute bars, UTC, from `data/seqlab` |
| squeeze | the range of the last **24 finished** four-hour calendar bins, divided by the four-hour **ATR(14)**, in the bottom **20%** of a **trailing 750-bin** window including the current one. 750 bins is 125 calendar days |
| slow leg | four-hour **calendar bins**, never a difference of aligned closes: aligning first and differencing after turns every session gap into a fabricated one-bar return |
| impulse | `abs(r) >= 3.0 * sigma`, `r` close-to-close, `sigma` the frozen HAR's forecast for that bar |
| HAR | OLS of `log|r|` on the logs of the lagged mean `|r|` over **4, 96 and 480 bars** - one hour, one day, one week, the components `vol_gate.py` already uses - fitted on bars before **2026-02-01** and frozen, with a **smearing** factor `mean(exp(y - pred))` so a fit in logs is not left biased in levels. Strictly lagged: a forecast never sees its own bar |
| side | the impulse's own, continuation |
| entry | the **open of the next bar**, at the ask on a buy and the bid on a sell |
| hour cut | no entry when the signal bar closes in **19, 20, 21 or 22 UTC** - `[19:00, 23:00)`, four hours |
| exit | the open **16 bars** after the entry bar. No stop, no target |
| 1R | `3.0 * sigma`, the trigger distance |
| cost | **one quoted spread** per round trip, from the terminal's quote on 2026-11-05, never the per-bar `spread` column |
| cost gate | a round trip may not exceed **0.16** of 1R - `domain/costs.MAX_SPREAD_RISK_FRACTION`, the desk's one measured limit, used unchanged |
| non-overlap | one position at a time per instrument; the slot frees on the bar the clock closes the trade, which is what production's `_clock` does before it judges that bar's event |
| discovery / confirmation | **2021-01-01**, fixed before the grid was read |
| uncertainty | day-block bootstrap, 2,000 draws, 90% interval. A day is 96 bars and the hold is 16, so no block is shorter than a trade |

### The ambiguity in the specification, named rather than resolved

*"the range of the last 24 four-hour bars is in the bottom 20% of the past 750
bars, after adjusting for normal ATR"* admits at least three denominators and
they are not the same gate. An ATR over the same 24 bins cancels the thing being
measured; an ATR over the whole 750-bin window is constant inside it and changes
no rank at all. The reading taken is the textbook **ATR(14)** on the four-hour
clock, and the unadjusted range is carried as an arm. They rank differently -
`tests/test_vol_impulse.py` pins that they do - and they give the same verdict.

### The controls

| arm | what it changes | what it answers |
|---|---|---|
| `coin` | the side, drawn at random, 200 draws | does the side carry anything beyond the dates and the cost |
| `stale8` | the fill is 8 bars late | is the information specific to the moment |
| `random` | the entry bar, at the same count and the same **hour histogram** | is it being in the market at those times |
| `nosqueeze` | `Fold(require_squeeze=False)` | the impulse alone |
| `expansion` | the impulses the squeeze **refused** | the duty-cycle-free half of the same question. `nosqueeze` trades 4.6x as often as the rule, and on a losing book any rule that trades less looks better, so the comparison that carries information is squeeze against not-squeeze |
| `rawrange` | the squeeze ranks the unadjusted range | the specification's ambiguity |
| `flip` | every return's sign randomised, the magnitude path kept exactly | the calibrated direction null `impulse-vol.md` uses |
| `har_early` | the HAR frozen before 2019, scored on 2019+ | the rule freezes the model *after* most of the sample, so the denominator that picks the events has seen the future |

`nosqueeze` and `expansion` run through the **production fold** with one field
changed, not through a copy of the rule in a harness. That is the point of
`Fold.require_squeeze` being a field: the arm that decides the rule's central
claim and the rule itself are the same object.

## The data, the fit and the firing rate

| instrument | bars | from | HAR rows | R2 on `log|r|` | smearing | quoted spread |
|---|---|---|---|---|---|---|
| EURUSD | 294,499 | 2015-01-02 | 270,969 | 0.143 | 1.592 | 9 points |
| USDJPY | 294,522 | 2015-01-02 | 271,528 | 0.138 | 1.595 | 9 points |
| GBPUSD | 294,524 | 2015-01-02 | 271,717 | 0.132 | 1.692 | 11 points |
| USDCAD | 294,517 | 2015-01-02 | 271,246 | 0.119 | 1.619 | 10 points |
| XAUUSD | 276,423 | 2015-01-02 | 256,279 | 0.109 | 1.640 | 16 points |

A smearing factor of 1.59 to 1.69 is not cosmetic: without it the forecast is
the geometric mean of `|r|` and the trigger fires about 60% too often.

| instrument | judged bars | impulses | % of bars | in a squeeze | % of impulses | % of bars |
|---|---|---|---|---|---|---|
| EURUSD | 282,555 | 10,327 | 3.655 | 2,332 | **22.6** | 0.825 |
| USDJPY | 282,578 | 10,195 | 3.608 | 2,033 | **19.9** | 0.719 |
| GBPUSD | 282,579 | 9,379 | 3.319 | 2,036 | **21.7** | 0.721 |
| USDCAD | 282,570 | 9,606 | 3.400 | 2,081 | **21.7** | 0.736 |
| XAUUSD | 265,012 | 10,586 | 3.995 | 2,124 | **20.1** | 0.801 |

**The squeeze admits its own quantile and nothing more.** A gate that keeps the
bottom 20% of a trailing window keeps 20% of anything independent of it, and
19.9-22.6% is what it keeps of impulses. So before any outcome is read, the
four-hour squeeze is already known to carry almost no information about *when* a
15-minute impulse happens - the 1.7-2.6 points of excess being the only
dependence there is.

The rule fires on 0.72-0.83% of judged bars: about **175 to 200 events a year**
per instrument, and 92 to 103 trades a year after the gates.

**Firings concentrate at the volatility peak**, because a HAR has no intraday
seasonal in it. EURUSD by UTC hour:

```
00 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23
60 53 41 15 18 35 71 127 145 78 69 77 218 280 240 210 112 92 110 97 44 38 58 44
```

`seasonality-belongs-on-q` is the standing note: intraday pattern is in
volatility, FX peaks 14-15 UTC at 3x. A rule whose denominator ignores that
fires where the pattern is, which is why the random arm is drawn from the same
hour histogram rather than uniformly.

## What each gate refused

| instrument | events | cut 19-22 UTC | over the cost limit | one at a time | taken |
|---|---|---|---|---|---|
| EURUSD | 2,332 | 237 (10.2%) | 162 (**6.9%**) | 718 (30.8%) | 1,215 |
| USDJPY | 2,033 | 231 (11.4%) | 104 (**5.1%**) | 581 (28.6%) | 1,116 |
| GBPUSD | 2,036 | 209 (10.3%) | 75 (**3.7%**) | 616 (30.3%) | 1,136 |
| USDCAD | 2,081 | 262 (12.6%) | 129 (**6.2%**) | 604 (29.0%) | 1,085 |
| XAUUSD | 2,124 | 149 (7.0%) | 49 (**2.3%**) | 770 (36.3%) | 1,156 |

The cost gate refuses **2.3% to 6.9%** of firings, and turning it off changes
nothing worth the name: EURUSD -0.1264 ungated against -0.1407 gated, USDCAD
-0.1048 against -0.1219. The gate is not what the rule's result rests on.

The **hour cut helps**, slightly and consistently: with 19-22 UTC admitted the
pooled readings per instrument are -0.1297 to -0.1745 against -0.1219 to
-0.1412 with the cut - between 0.01 and 0.03R a trade, on 5 of 5 markets, which
is the same direction `intraday.md` found for 20:00-23:00 and about a tenth of
its size.

**One position at a time removes a third of the events.** Without it a four-hour
hold on a 15-minute trigger counts one outcome up to sixteen times, and the
interval would be about four times too narrow.

## The result, per instrument

Mean R net of one quoted round trip, with the day-block interval. Never only
pooled:

| instrument | n | net R | se | 90% interval | gross R | cost R | sd | win | P(>=1R) | first half | second half |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EURUSD | 1,215 | **-0.1407** | 0.0860 | [-0.2860, +0.0017] | -0.0461 | 0.0946 | 3.00 | 0.460 | 0.290 | -0.1054 | -0.1790 |
| USDJPY | 1,116 | **-0.1373** | 0.0794 | [-0.2626, -0.0143] | -0.0524 | 0.0849 | 2.65 | 0.470 | 0.283 | -0.1161 | -0.1561 |
| GBPUSD | 1,136 | **-0.1412** | 0.0806 | [-0.2694, -0.0039] | -0.0557 | 0.0855 | 2.72 | 0.460 | 0.291 | -0.1869 | -0.0915 |
| USDCAD | 1,085 | **-0.1219** | 0.0856 | [-0.2621, +0.0113] | -0.0272 | 0.0948 | 2.82 | 0.470 | 0.295 | -0.0772 | -0.1704 |
| XAUUSD | 1,156 | **-0.1313** | 0.0836 | [-0.2695, +0.0090] | -0.0667 | 0.0646 | 2.84 | 0.452 | 0.285 | -0.1616 | -0.1034 |

**5 of 5 negative, 2 of 5 with an interval excluding zero, and the same sign in
both halves on 5 of 5.** The discovery / confirmation split agrees with the
whole: there is no half in which this rule pays.

Gross is -0.027 to -0.067 and cost is 0.065 to 0.095, so **the loss is about
two thirds spread and one third a small negative gross** - and the gross part is
not separable from zero at this sample, nor from the known mechanical reversion
of selecting on `|r| / sigma`.

## The nulls, pooled, with the day block shared across instruments

The block is a **calendar day across all five markets**, not a day per market: a
squeeze on four dollar legs is one condition seen four times, and resampling the
instruments independently would count it as four observations.

| arm | n | days | net R | 90% interval | gross R | cost R | win | P(>=1R) | P(>=2R) |
|---|---|---|---|---|---|---|---|---|---|
| **real** | 5,708 | 2,076 | **-0.1347** | [-0.2015, -0.0709] | -0.0498 | 0.0849 | 0.462 | 0.289 | 0.166 |
| `coin` | 5,708 | 2,076 | -0.1039 | [-0.1635, -0.0429] | -0.0190 | 0.0849 | 0.487 | 0.300 | 0.169 |
| `stale8` | 5,064 | 2,070 | **-0.1293** | [-0.1881, -0.0717] | -0.0444 | 0.0849 | 0.461 | 0.258 | 0.136 |
| `random` | 8,042 | 2,866 | -0.0890 | [-0.1304, -0.0490] | -0.0157 | 0.0732 | 0.474 | 0.243 | 0.114 |
| `nosqueeze` | 26,185 | 3,177 | -0.1250 | [-0.1560, -0.0928] | -0.0394 | 0.0856 | 0.467 | 0.289 | 0.165 |
| **`expansion`** | 20,934 | 3,138 | **-0.1197** | [-0.1523, -0.0866] | -0.0342 | 0.0856 | 0.469 | 0.289 | 0.165 |
| `rawrange` | 6,119 | 2,008 | -0.1328 | [-0.1963, -0.0655] | -0.0376 | 0.0952 | 0.463 | 0.291 | 0.172 |
| `flip` | 5,644 | 2,076 | -0.0566 | [-0.1141, +0.0041] | +0.0282 | 0.0848 | 0.484 | 0.315 | 0.179 |
| `har_early` | 3,853 | 1,400 | -0.1150 | [-0.1924, -0.0369] | -0.0318 | 0.0832 | 0.465 | 0.289 | 0.171 |

And the two surrogates against their own 200-draw distributions:

| surrogate | its own null | the real arm | share of draws beating the real arm |
|---|---|---|---|
| `coin` | -0.0819 +- 0.0384 | -0.1347 | **91.0%** |
| `flip` | -0.0828 +- 0.0368 | -0.1347 | **89.5%** |

Four readings decide it:

* **The rule does not beat its coin.** Nine draws in ten of a random side on the
  same dates, paying the same spread, do better. It is not significantly worse
  either - 91% is p 0.09 one-sided on a single pre-named comparison - so the
  honest statement is *the side carries nothing*, not *the side is backwards*.
* **The squeeze contributes nothing.** The impulses it refused read -0.1197
  against its own -0.1347 over four times the sample. This is the rule's central
  claim and it is answered in the direction `impulse-vol.md` predicted.
* **The signal is not about the moment.** Eight bars late is the same number.
* **The tail is the coin's tail.** P(>=1R) is 0.289 for the rule and 0.300 for
  the coin; P(>=2R) 0.166 against 0.169. There is no stop here, so `1/(1+N)`
  has no role - but the shape of the distribution is the shape a random side on
  the same bars produces, which is what matters.

`random` reading better than the rule (-0.0890 against -0.1347) is mostly its
cheaper cost (0.0732 against 0.0849, because the rule fires where volatility is
high and the HAR forecast is *not* proportionally high) and its smaller sd (2.16
against 2.81). It is reported because the brief asked for it and because it
rules out "being in the market at 13:00 UTC" as the explanation; it is not a
better strategy.

## Power, and the defect in how it was first measured

**The planted-drift sweep in the harness is not a power curve, and this is the
defect `impulse-vol.md` already named**: *"a plant swept on a series that
already has an effect is not power."* Adding a drift `d` to a book whose mean is
-0.1347 and asking when the lower bound clears zero measures whether
`-0.1347 + d > 0`, not whether `d` is detectable. The sweep is left in the
harness output and must not be quoted as power: it reports `blind` at every
plant up to 0.20R for exactly that reason.

**The power statement that is available is the interval width**, which needs no
plant:

* **pooled**: the 90% interval is [-0.2015, -0.0709], a half-width of
  **0.065R** on 5,708 trades. An effect of 0.07R or larger would have been seen.
* **per instrument**: half-widths of 0.14R on about 1,100 trades each. An
  instrument-level effect smaller than 0.14R would not have been seen, which is
  **larger than the cost** - so the per-instrument rows cannot resolve a rule
  that merely covers its spread, and only the pooled row can.
* **per bar**: the pooled bound divided by the 16-bar hold is **0.004R a bar**,
  which is the resolution a longer hold would improve at constant cost. That is
  the one honest route to more power on this family and it is listed as a
  candidate below rather than run here.

The surrogate arms are calibrated: the coin's own 200-draw sd is 0.0384 pooled
against the real arm's naive se of 0.0372, which is what a correctly built
surrogate should give.

## The one live trade: a single draw, and the spread nobody charged

The rule's only live evidence is one trade: **bought USDCAD at 03:00 UTC on
2026-11-06, exited 07:00, +1.87R**. The `seqlab` cache ends 2026-11-05 15:30, so
the fast minute cache was folded to 15 minutes and spliced on - the squeeze needs
125 days of history and the fast cache holds two weeks, so neither half can
answer this alone.

**The rule as specified does not fire there, in two independent ways.**

| | |
|---|---|
| the 03:00 bar | open 1.40014, close 1.40084, **down 6.71bp** |
| the frozen HAR's forecast for it | **2.432bp** |
| the ratio | **2.76**, against a trigger of **3.00** |
| the side it would have taken | **SELL**. The desk bought |
| the squeeze rank | 0.037, so the squeeze itself was satisfied |
| the nearest firing | **06:45 UTC the same day**, ratio 4.07, rank 0.065 - refused on **cost**, the round trip reading **0.17R** against the 0.16 limit because the forecast had decayed to 1.366bp through the quiet Asian session |

So the bar is a 2.8-sigma move, below the trigger, on the opposite side to the
trade, and the one bar that day that *did* clear the trigger was refused by the
cost gate by a hundredth of an R. Either the live desk ran a different
denominator, a different multiple, or a fade rather than a continuation.
**Unknown: what produced the live signal.** What is not unknown is that the rule
written here would not have taken that trade.

**The direction was right and the size is ordinary.** A long entered at the
03:15 open and held the rule's 16 bars to the 07:15 open:

| 1R | gross | net at the quoted 10 points | net at the 71 points the minute cache shows at that fill |
|---|---|---|---|
| 1 x sigma (34.1 points) | +4.34R | +4.05R | **+2.26R** |
| 2 x sigma (68.1 points) | +2.17R | +2.03R | **+1.13R** |
| **3 x sigma (102.2 points)** | **+1.45R** | **+1.35R** | **+0.75R** |

So +1.87R is reachable on that move - it sits between the 2-sigma and 3-sigma
readings at the quoted spread - and it is **one draw**. This rule's own trade
distribution has mean -0.1347R and sd **2.81**, so +1.87R is a **0.7-sigma**
draw and **16.6%** of its trades reach +2R or better. One trade at +1.87R is
what this rule does roughly one time in six while losing 0.13R on average. It is
not evidence of anything, and the brief's question - *is the +1.87R reproducible
or a single draw* - answers **single draw**.

**What the minute cache says about that moment is worth more than the trade.**

```
02:59  open 1.40184  close 1.40178  spread    5 points
03:00 - 03:04  MISSING from the broker's own minute history
03:05  open 1.40014  close 1.40065  spread  151 points
03:10  open 1.40071  close 1.40071  spread  129 points
03:15  (the rule's entry bar)       spread   71 points
07:00  (the operator's exit)        spread    3 points
```

The minutes 03:00-03:04 are absent, price gapped 16 pips down across the hole,
and the quoted spread at the first print afterwards was **151 points against the
10 points this study charges - 15 times**, still 71 at the entry bar and back to
3 by the exit. On this rule's unit 1R was 102 points there, so the round trip at
the spread actually quoted was **0.70R at 03:15 and 1.48R at 03:05**, against the
0.085R the study charges and the 0.16R gate that would have refused it outright.

Two consequences, and the second is a finding about every impulse study on this
desk:

1. **The live trade's net depends entirely on which spread it was computed at.**
   +1.35R at the quote, +0.75R at the fill's real spread, on the same move and
   the same R. Whether the operator's +1.87R is gross, at the fill, or from the
   broker's own realised P&L cannot be settled from here, and it is the
   difference between a good trade and a scratch.
2. **A constant quoted spread is the wrong cost model for an impulse, and the
   error has a known direction.** Every impulse reading on this desk, this one
   included, charges one number taken on one day. The one event with a minute
   record attached arrived inside a 15x blowout. If impulses systematically
   arrive when the book is wide, every cost line in this family is optimistic -
   and the per-bar `spread` column cannot answer it, being zero on 35% of
   USDCAD's 15-minute bars. The fast minute cache **can**: its spread column on
   the same instrument reads a median of 3 points and a maximum of 151. That is
   the candidate this study would run next.

## Bugs and measurement defects this run caught

1. **A fifteen-minute bin with fewer than fifteen minutes was being dropped, and
   the one bin it dropped was the live trade's.** The minute-to-15-minute fold
   first required all fifteen rows. A minute with no tick produces no M1 bar, so
   a short bin is an absence of *trading*, not of data - and 03:00 on 2026-11-06
   is short *because* of the event that made it interesting. 14 of 1,339 bins on
   USDCAD are short. The filter now drops only the final bin, which is
   incomplete by the clock rather than by the market. **Without this fix the
   study would have reported "the rule does not fire near the live trade" with
   the reason being its own data handling.**
2. **The planted-drift sweep is not power.** Reported above rather than quoted:
   the baseline is -0.1347, so the sweep measures the total and not the
   increment. `impulse-vol.md` had already written this defect down and the
   harness reproduced it anyway.
3. **`Intent.stop` of zero is refused as unsized, so "no stop" was not
   expressible.** `sizes.size` divides a budget by `intent.risk`, so a rule whose
   exit is a clock could only be deployed with a stop it does not have - and a
   stop at 1R both changes the hit rate and improves the number.
   `Profile.protective_stop` makes `Intent.stop` a **sizing distance** with
   nothing sent to defend it, and `Desk._protects` is read by both paths that
   put a stop at a venue - `EdgeEntry` and `ExitMechanism._attach` - because a
   flag honoured by one of them is a rule that trades differently depending on
   which fired first.
4. **A HAR fitted on `log|r|` and exponentiated without a smearing factor
   forecasts the geometric mean.** The factor is 1.59-1.69 here, so the
   uncorrected version fires about 60% too often - a silent change to the rule's
   event rate with nothing in the diff that looks like one.
5. **The rule's warm-up is 12,000 bars and the production catalogue holds about
   7,300.** 750 four-hour bins is 125 calendar days. A backtest over
   `node/corpus.py`'s catalogue produces **zero** signals by construction, and
   that zero is not a null. Said in the module docstring and in the profile's
   `warm_bars_request`.
6. **The squeeze's ATR denominator is ambiguous in the specification and two of
   the three readings are degenerate** - an ATR over the same 24 bins cancels
   the measurement, an ATR over the whole ranking window changes no rank. Named
   in `SQUEEZE_ATR` rather than chosen silently, with the surviving alternative
   carried as an arm.

## What this does not close

* **The maker side.** Every number here is a taker paying a full quoted round
  trip. Gross is -0.05R and cost is 0.085R, so a fill that *collects* even half
  the spread changes the sign of the net - and nothing here measures whether such
  a fill is reachable on an impulse. `stop-free.md` found that posting a limit on
  the side an instrument jumps towards buys you the jump, on Boom and Crash, and
  never on FX.
* **The conditional spread.** The cost is one number from one day. The one event
  with minute data attached arrived at 15x it, and the distribution of the spread
  *at an impulse* is unmeasured on this panel.
* **Holds other than 16 bars.** One hold, because the rule names one. The pooled
  bound is 0.004R a bar, so a longer hold resolves a smaller per-bar drift at
  the same cost in R, and that sweep was not run.
* **Triggers other than 3.0, and squeeze shares other than 0.20.** No sweep:
  `trigger-expectancy.md` already swept the trigger on the conditional mean and
  found *lowering the trigger multiplies the events and not the edge*, so a
  sweep here would be a grid over a family whose centre reads zero.
* **Slippage, commission and swap.** None is charged. Every net number here is
  optimistic by all three, and a four-hour hold crossing 22:00 UTC pays a swap
  this study ignores.
* **What produced the live +1.87R.** Stated above as unknown.
* **Instruments beyond the five.** The rule names five. A cheaper instrument
  cannot rescue this rule in any case: gross is zero, so a smaller spread gives
  a smaller loss and not a profit. That is the difference between an idea about
  costs and an idea about a signal, and this one is neither - it is an idea about
  nothing.

## Candidates this run points at, none of them built

Each is written as a sentence the existing studies could not have tested, with
the row it is distinct from.

1. **The maker side of an impulse.** *"A limit resting at the pre-impulse price,
   filled by the impulse's own overshoot, collects the spread rather than paying
   it, and a book that does so is positive where the taker book is negative by
   exactly its cost."* Distinct from `vol-gate.md`, whose own open question is
   *"whether the same trade can be taken for under 5 basis points of R - a
   maker-side or a cheaper instrument"* and whose entries are at the close with a
   full round trip; distinct from `limitfills.md`, which measured a pullback
   entry's winner's curse rather than a fill *into* a trigger. The strongest
   candidate, because this study's own gross is zero and its net is its spread.
2. **The spread at the moment of the impulse.** *"The quoted spread conditional
   on an impulse is several times its unconditional median, so every impulse
   study's cost line is optimistic by a knowable factor."* Distinct from every
   row in the corpus: the per-bar `spread` column is refuted as a *level*
   (zero on 7-35% of bars, 3-8x below the quote) and nothing has asked whether
   it is informative as a *conditional* reading. The fast minute cache can
   answer it on two weeks of five instruments, and the one observation that
   exists reads 151 points against 10.
3. **The impulse as a risk switch over the rest of the book.** *"Halving every
   other desk's size for 48 bars after an impulse out of a squeeze cuts the
   book's 1% tail without cutting its mean."* Uses what `impulse-vol.md` *found*
   rather than what it refuted - forward volatility 1.49x the pre-event forecast
   48 bars after a squeeze impulse against 0.95x after a high-volatility one, on
   8 of 8 markets - and is distinct from `crash-timing.md`, which did the
   equivalent for a different detector and found the top score quintile carries
   a 34% chance of a 4x bar with halving cutting the 1% tail 14-26% at neutral
   Sharpe. It is a risk claim, which is the channel this desk can forecast.
4. **The hold as a power instrument rather than as a parameter.** *"1R is fixed
   by the trigger and the cost in R is therefore independent of the hold, so a
   96-bar hold resolves a per-bar drift six times smaller than a 16-bar hold at
   the same cost."* Distinct from `hold-clock.md`, which swept 1-40 bars on level
   trades still carrying a stop and a target, and from `impulse-vol.md`'s four
   horizons, which carry no cost. Worth running precisely because it does not
   assume an edge: it widens the window the test can see through.
5. **Volatility-of-volatility as the conditioner, instead of the level.** *"The
   dispersion of the recent volatility forecast, not its level, separates
   impulses whose forward move is signed."* Distinct from `impulse-vol.md`, which
   conditioned on the level's trailing rank on both clocks, and from
   `letter-shapes.md`, which conditioned on shape. Carried at a **low prior**:
   `findings.md` records direction as closed rather than merely null, and
   `noise-argument-is-a-variance` is the only reason this is not simply the same
   claim again.

And one missing control in an existing study, which is cheaper than any of the
above: `vol-gate.md` names it itself - *"the coin is not a bar-matched surrogate
for `donch` ... a bar-matched sign-flip arm is the first thing a re-opening
should add"*. Its one non-null cell has never been tested against its own
surrogate.

## Where the code is

| | |
|---|---|
| the rule | [`till_infinity/strategies/volimpulse.py`](../../till_infinity/strategies/volimpulse.py), registered in `leaves.py` as `("vol-impulse", "edge")` and **in no default** |
| the tests | [`tests/test_vol_impulse.py`](../../tests/test_vol_impulse.py), 24 of them |
| the harness | [`research/harness/vol_impulse.py`](../harness/vol_impulse.py) |
| the output | `vol_impulse.csv`, `-trades.csv`, `-pooled.csv` on the lab |

`TRADING_STRATEGIES=vol-impulse` resolves and the desk would trade. **It is not
enabled anywhere and nothing in this document licenses enabling it.**
