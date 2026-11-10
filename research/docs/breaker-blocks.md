# The breaker block: 92.6% of order blocks flip, and the flip is a distance-matched placebo

> **Withdrawn and then reinstated, both on 2026-11-10, and the round trip is
> worth more than either reading.** This document led with a "leak in
> `node/surrogates.walk_with_bar_geometry`": the surrogate places each bar's
> open inside that bar's own range, independently of the previous close, and a
> long-entry arm paid **+0.1012R** a trade on it.
>
> The claim was withdrawn after the coordinator measured the **mean** gap and
> found the market carrying the same one - negative on 28 of 28 of the broker's
> 1h FX stores at -0.0126 of a bar range, which `MODE=gap` reproduces here. The
> identity `close[i] - close[i-1] = (open[i] - close[i-1]) + (close[i] -
> open[i])` forces that for any series whose bars close above their opens with
> near-nil drift.
>
> **The mean is the one statistic that cannot see this defect, and the claim is
> reinstated on the distribution** (`till_infinity/node/surrogates.py`, and
> `#384`). As a share of the bar range, on the broker's 15m and 1h stores:
>
> | | median `|gap|` | bars with no gap | p90 `|gap|` |
> | --- | ---: | ---: | ---: |
> | real | **0.0000** | **71 - 79%** | 0.012 - 0.040 |
> | the surrogate | **0.60 - 0.64** | 0.01 - 0.16% | 1.64 - 1.88 |
>
> The market is contiguous on three quarters of its bars and reaches its mean
> through a minority of session-boundary gaps; the surrogate gaps 0.6 of a
> range on **every** bar. So the arm does plant a collectable edge for anything
> that fills on a gap, and the +0.1012R is it.
>
> **Both failures were the same failure.** The first version diagnosed a
> mechanism on a hand-built source with zero gap and never measured the
> market's; the withdrawal measured the market with a statistic that averages
> the defect away. A mechanism is not a defect until the thing it should be
> absent from has been checked, **and not with a statistic that cannot tell
> them apart**.
>
> A second limit stands on its own and is below under
> [a resting-limit arm is not measurable on bar data](#a-resting-limit-arm-is-not-measurable-on-bar-data):
> OHLC does not order the high and the low, so any fill inside a bar is the
> harness choosing an intrabar path. **The refutation never rested on that arm
> and does not now.**

**Measured 2026-11-10**, pre-registered as shortlist item 1 of
[`tradingview-survey.md`](tradingview-survey.md) and run to the specification
there without alteration. Code: [`breaker_blocks.py`](../ideas/breaker_blocks.py)
(detector, trades, nulls, cost, power, sweep, detector overlap, the gap
measurement), [`breaker_report.py`](../ideas/breaker_report.py) (every table
below), tests in [`test_breaker_blocks.py`](../ideas/test_breaker_blocks.py).

**The headline is a rate, not a mean.** The published breaker reaches a 2R
target before a 1R stop on **0.2980 of 23,751 trades** where the arithmetic rate
is **0.3333** and every matched walk through the same detector reads
0.2695-0.3187. Mean R is **-0.0263** [-0.0468, -0.0032] day-blocked, against a
**measured round trip of 0.0536R**. The flip beats a distance-matched prior
swing with no order block behind it by **+0.0023R** [-0.0228, +0.0292].

**And the refuted arm was kept in the run, which is what the design was for: it
does not beat its null either.** The fade to the un-flipped zone reads -0.0478
[-0.0677, -0.0264] against walks at -0.0291 to -0.0614 on the three arms that
are usable for it. Neither arm clears its null, so there is no gap to assign to
either claim.

**Every number in this document that carries a confidence interval is read off
the real bars**; the surrogates appear only in the `walk` columns, and where
they disagree with each other the disagreement is reported rather than resolved.

## Verdict

| question | answer |
|---|---|
| Does the **published breaker** pay at 2R? | **No.** 23,751 trades on 30 traded instruments at 1h, 4h and 1d: `P(>= 2R)` **0.2980** against an arithmetic 0.3333; mean **-0.0263R** [-0.0468, -0.0032] gross, **-0.0800R** net of a 0.0536R round trip |
| Does it beat the **placebo** - a breaker declared at a prior swing with no order block behind it, matched on zone height and drawn one per real trade? | **No. +0.0023R** [-0.0228, +0.0292], paired on days. The zone heights match to three decimals (median 1.197 against 1.201 units), so this is the same geometry with and without an order block, and the order block adds nothing. **This is the load-bearing control**: it runs on the real bars through the identical construction, so the harness's own intrabar assumption cancels, which no walk arm can do |
| Does the **refuted fade** also beat the null? | **No**, and that is the single most important column. Fade -0.0478 [-0.0677, -0.0264] against iid -0.0614, GARCH -0.0291 and `contopen` -0.0464. Neither the flip nor the fade clears a null, so there is no finding to assign to either claim |
| Does **EmreKb's confirmation** - a fresh swing inside the broken band - help? | **No.** -0.0330R [-0.0766, +0.0108] on 4,515 trades, worse than the unconfirmed arm, and it applies to only **0.2591 of flips** because the zone is usually deleted first |
| Does the prior study's **+0.337R at 1d / +0.506R at 4h** reproduce? | **Not on either zone population, and the 1d cell cannot settle it.** On the published blocks: 1d -0.0096R [-0.1220, +0.1129] on 567 trades, 4h -0.0290R [-0.0719, +0.0144] on 4,574. On **the desk's own blocks** with the published flip lifecycle: 4h -0.1189R [-0.2668, +0.0335] on 328, which excludes +0.506R; 1d **-0.0667R [-0.4667, +0.3636] on 45 trades**, which excludes nothing and is reported as unmeasurable |
| Is the published order block the **same object** as this repo's? | **No, and this is why neither null transfers.** Jaccard **0.0027** over 219,000 bars on eight instruments: LuxAlgo cuts **20,133** blocks where `zones.ob_zones` cuts **1,316**, and finds 4.4% of them. Two detectors with the same name are usually two detectors |
| Is "flipped" a **selection** at all? | **Barely. 0.9264 of order blocks flip** (0.9297 on the desk's), and 0.94-0.96 of flipped zones are retested before deletion. The published polarity flip is the default outcome of an order block, not a rare event, which is the mechanical reason it carries so little information |
| Does **cost** kill it first? | **No, and the survey priced it at the wrong stop.** The breaker's own stop is the zone plus a pad - **1.14 to 1.87 ATR**, not the 3.46-3.55 ATR of a 20-bar swing - so the real cost is about **2.6x** the survey's figure: median 0.0416R at 1h, 0.0204R at 4h, 0.0085R at 1d, outside the desk's 0.16 ceiling on 2 of 27 at 1h (XAGUSD 0.2500, XCUUSD 0.3113) and 0 of 27 at 4h |
| Does **any** parameter cell pay? | **No. 0 of 432.** Twelve configurations, one parameter moved at a time, three clocks, three arms, four targets: not one cell has a lower bound above zero. The best is +0.0339 +- 0.1037 |
| Does any **instrument** pay? | **No. 0 of 68 traded cells** have a lower bound above zero and **0 of 98 survive Benjamini-Hochberg**. The only two cells with a positive lower bound are **Boom 1000 Index** and **Boom 500 Index** - the arm that must be empty |
| Where does the test go **blind**? | Below about **0.2R of planted edge** pooled (z +1.88), and it sees 0.4R at z +6.25. In realised terms 2 sigma needs 0.019R at 1h, 0.040R at 4h and **0.11R at 1d**. About a fifth of each plant is what the estimator resolves, because the median trade closes in 5 bars of a 60-bar window |
| What does the study **not** settle, and why? | **Whether a resting-limit arm has any edge against a surrogate.** OHLC does not order the high and the low, so filling at a limit inside a bar and marking the race from that bar is the harness choosing an intrabar path. The market itself carries a negative mean `open[i] - close[i-1]` and arithmetic says it must, so the shipped surrogate having one is correct - but it does not match its size away from the hourly FX cells, where it is the same sign on 5 of 5 within a factor of 4.4, growing to 2.4-9.0x at 1d and reaching -0.1393 to +0.1280 on the Deriv synthetics. The same trade therefore reads **+0.0019R** over one geometry arm and **+0.0693R** over the other. That is why the verdict rests on the arithmetic rate, the placebo and the per-cell counts, none of which need a surrogate |

## A resting-limit arm is not measurable on bar data

This replaces a section that claimed a defect in
`node/surrogates.walk_with_bar_geometry`. The claim was wrong and the banner at
the top says so; what follows is what the same measurement actually supports,
and it is a harder constraint than the one it replaces.

**Start with the arithmetic, because it settles the sign for free.** For any
series,

    close[i] - close[i-1] = (open[i] - close[i-1]) + (close[i] - open[i])

so a series whose bars close above their opens on average and whose
close-to-close drift is about nil **must** carry a negative mean gap. That is
not a property of surrogates; it is a property of bookkeeping, and the market
obeys it. `MODE=gap`, on the broker's own 1h stores as stored:

| | |
|---|---:|
| stores with a negative mean `open[i] - close[i-1]` | **28 of 28** |
| mean gap, as a share of the mean bar range | **-0.0126** |
| median | -0.0120 |

with the mean body positive and the mean step near zero on every one. **So a
sawtooth in a surrogate is not an artefact and this document does not call it
one.**

Two store sets, two counts, and they agree. The coordinator's measurement is
over **12 hourly stores** and reads the real gap as negative on **10 of 12**,
with the surrogate understating it as often as it overstates; the two stores
where the real gap is about zero are BTCUSD and XCUUSD. Mine is over the **28
FX** 1h stores, which is why it is 28 of 28: the FX legs all carry it, and my own
folded table reads about **zero** on BTC (+0.0001) and the Deriv synthetics
(-0.0001). Same phenomenon, different denominators.

**Where the two arms stand against it depends on the clock, and the honest
summary leads with the hourly FX cells** - the ones the coordinator measured -
rather than with the extremes:

| cells | market's gap/span | `shipped` | same sign | `shipped` nearer zero than the market |
|---|---|---|---:|---:|
| the 5 deep FX legs, 1h | -0.0051 to -0.0031 | -0.0139 to -0.0015 | 5 of 5 | 1 of 5 |
| the same legs, 4h | -0.0047 to -0.0026 | -0.0235 to +0.0037 | 4 of 5 | 0 of 5 |
| the same legs, 1d | -0.0106 to -0.0057 | -0.0607 to -0.0181 | 5 of 5 | 0 of 5 |
| all 30 traded cells | -0.0106 to +0.0042 | -0.0607 to +0.0037 | | |
| all 24 Deriv cells | -0.0025 to +0.0028 | **-0.1393 to +0.1280** | | |
| all 54 | | | 28 of 54 | 2 of 54 |

At the hourly FX clock the surrogate is the **same sign on 5 of 5** and within a
factor of 0.46 to 4.43, under- as often as over-stating, which is the
coordinator's reading reproduced. The disagreement grows with the clock - 1.44
to 7.03x at 4h, 2.42 to 8.96x at 1d - and on the Deriv synthetics, where the
market's gap is about zero, the surrogate reaches **+0.1280** on Boom 1000 and
**-0.1393** on Crash 1000. `contopen_bars`, which opens every bar at the
previous close, pins it at exactly zero on all 54. **Neither arm is the market's
value, and the package's is the better of the two where it was measured**;
`contopen` is carried to size the sensitivity, not offered as a fix - the
package's docstring and its test say why one must not be applied.

**A resting-limit arm reads exactly that quantity**, because OHLC does not order
the high and the low inside a bar. Filling at a limit price inside bar `j` and
then marking the barrier race from bar `j` is the harness choosing an intrabar
path, and the choice is worth:

| arm, at 2R | real bars | `shipped` | `contopen` | the two arms' disagreement |
|---|---:|---:|---:|---:|
| `flip` (short entry) | **-0.0263** | -0.0956 | -0.0283 | 0.067 |
| `fade` (long entry) | **-0.0478** | **+0.0706** | -0.0464 | 0.117 |
| `placebo` (short entry) | **-0.0286** | -0.0784 | -0.0303 | 0.048 |

The shipped arm's long-entry reading, **+0.0706R on the traded book and +0.1012R
pooled with the synthetics**, is a positive expectancy on a series whose closes
are a resampled walk - and its short-entry readings are depressed by about as
much, which is the signature of a systematic intrabar path rather than of
structure. **The same thing happens on the real series for the same reason**,
which is the coordinator's point and the reason this is a method limit rather
than a surrogate defect. It also cuts a different population: 47,547 breaker
trades against `contopen`'s 101,901, so the two are not even a like-for-like
contrast.

Three consequences, and they are the reason this section exists:

1. **`flip - walk` is not a usable statistic for this trade.** It reads +0.0019
   +- 0.0103 against `contopen` and +0.0693 +- 0.0129 against `shipped`. A
   verdict resting on the second would be a verdict about bar assembly.
2. **The placebo is the control that works.** It runs on the **real** bars
   through the identical entry, stop, side and settlement, so the intrabar
   assumption appears in both arms and cancels. It reads +0.0023R
   [-0.0228, +0.0292].
3. **The arithmetic rate needs no surrogate at all**, and 0.2980 against 0.3333
   is the number this study leads with for that reason.

**And the two arms fail in different places, which is why both are reported.**
The shipped arm draws `span` and the shape pair independently, so a bar's body
share survives as a marginal - it is a function of the pair alone, and the pair
travels - while its dependence on the bar's size and on the bar's own move does
not. `contopen_bars` makes the body exactly the close-to-close step, so that
dependence is exact, and the wicks are resampled independently of it, so **body
share is rebuilt from marginals rather than carried**. Two readings here are
graded on body share and are therefore mis-nulled by `contopen` and better
served by `shipped`: `zones.ob_zones` (the `ZONES=desk` population) requires
`PUSH_BODY` 0.70 and `ORIGIN_BODY` 0.45 as body-to-range fractions, and the
`BAND=body` sweep cell measures the band off `max(open, close)`. The
pre-registered `BAND=range` detector reads no body share, but its flip condition
`min(close, open) < btm` does read where a body sits inside its bar. None of
that is worked around; it is stated, and
`test_the_contopen_arm_breaks_the_body_to_wick_joint` pins it.

**What I got wrong, recorded rather than deleted.** Three things, all of them
mine.

1. I read the surrogate's sawtooth as a defect **without measuring the
   market's**, having diagnosed the mechanism on a hand-built source that had
   **zero** gap by construction - a mechanism found in a surrogate and never
   nulled against the thing it was supposed to be absent from.
2. My first "vectorised" copy of the package function drew `span` and the shape
   pair with **one** index, preserving a link the package breaks with two
   independent `r.choice` calls, so the arm labelled as the shipped one was not
   it. `test_the_shipped_arm_draws_span_and_shape_independently` now pins the
   difference, and fixing it moved the long-entry reading from +0.1241R to
   +0.1012R - the size of the first error's own evidence, which is
   `expect-the-correction-to-be-the-size-of-the-effect` cutting both ways.
3. The first draft of this correction then **overclaimed in the other
   direction**, saying the shipped arm's gap was "an order of magnitude wider"
   and "the wrong sign on gold, silver, BTC and Boom". That is the Deriv
   synthetics and the daily clock; at the hourly FX cells the arm is the same
   sign on 5 of 5 and within a factor of 4.4, which is what the coordinator
   measured. Generalising from the extremes is the same mistake as generalising
   from the zero-gap fixture, made twice in one document.

## The rules, as frozen before the run

Nothing below was tuned. `SWING`, `PAD`, `EXPIRE` and `HOLD` were fixed before
the first cell and the full sweep over them is reported.

| part | rule | source |
|---|---|---|
| **swing** | `pivothigh(10, 10)` / `pivotlow(10, 10)`, known 10 bars after it prints | LuxAlgo's `swing lookback 10` |
| **order block** | on `ta.crossover(close, top)` against the last known swing high, the block is the **lowest-low bar** between the swing and the crossing bar; one block per swing. The band is that bar's whole range (`body` is a sweep variant) | LuxAlgo *Order Blocks & Breaker Blocks* |
| **breaker** | the first bar after the block is known whose `min(close, open)` closes through the far edge | LuxAlgo |
| **deleted** | the first bar after the flip whose `close` clears the near edge - the top, for a flipped demand zone | LuxAlgo |
| **confirmed** | the first fresh pivot after the flip whose price lands inside the broken band, taken at the bar it is **known**, so the confirmation is charged its 10 bars of delay | EmreKb *Market Structure Break & Order Block* |
| **the trade** | **against** the zone's original direction, a resting limit at the near edge of the breaker, live from the flip until deletion or `EXPIRE` 300 bars | the survey's shortlist entry |
| **stop** | `PAD` 0.1 ATR(14) beyond the far edge; realised median **1.30-1.36 ATR** | `origin-zones.md`, `zones.py` |
| **target** | 1R, 2R, 3R, 4R; the headline is 2R | the desk's own brief |
| **hold** | 60 bars, **the same for every arm** | `CLAUDE.md`, "a stop and sixty" |
| **cost** | one round trip from the terminal's live ask minus bid, charged as `trip / stop`, never the per-bar `spread` column, which is in points | `research/harness/venue.quoted` |

Short setups are the same rules on the mirrored frame, which is the idiom
`zones.py` uses and whose absence once cost that study its entire supply side.
**Every parameter is a bar count**, so the same rule is ten hours at 1h and ten
days at 1d; the three clocks are three horizons and are never pooled.

### Settlement, and the three conservative conventions

Entries are resting limits and the fill bar is settled as
`research/mt5bt/engine.walk` settles one: the **stop counts** on the fill bar,
the **target counts only if that bar closes beyond it**, and when both legs are
reachable in one bar the **stop wins**. All three are conservative, so a
surrogate whose closes are a martingale should read at or below zero and at or
below `1/(1+N)`. Four of the five arms do:

| null series | `flip` | `fade` | `placebo` | n, `flip` |
|---|---:|---:|---:|---:|
| `iid`, Student-t(3) sub-steps | -0.0400 | -0.0653 | -0.0431 | 108,574 |
| `garch`, GARCH(1,1)-t(5) | -0.0337 | -0.0308 | -0.0376 | 107,719 |
| `contopen`, bar geometry, continuous | -0.0278 | -0.0339 | -0.0306 | 101,901 |
| `contdrift`, the same with the drift left in | -0.0313 | -0.0463 | -0.0342 | 101,272 |
| `shipped`, `walk_with_bar_geometry` | -0.1001 | **+0.1012** | -0.0860 | 47,547 |

The fifth is the subject of the section above: a positive long-entry expectancy
on a resampled walk, which is the intrabar path the harness is forced to assume
rather than a property of the series. `contdrift` reading within 0.002R of
`contopen` on every arm is the measurement behind "the market's unconditional
drift reaches none of these arms".

A fourth convention is new here and drops trades: **a resting limit must sit on
the far side of the market when it is placed**. LuxAlgo's `min(close, open) <
btm` can be satisfied by an up-closing bar's open alone, which would leave the
sell limit at or below the market and make the entry a market order wearing a
limit's settlement rules. 2,028 trades at 1h were refused for it.

## The data

Fifteen-minute stores folded to 1h, 4h and 1d by **UTC timestamp bucket**, never
by index - index folding puts Friday's close in the same bar as Monday's open.
The daily bar is therefore a UTC day and not the broker's 21:00 session, which is
a different clock from the prior study's.

| store | instruments | from | to | bars at 1h / 4h / 1d |
|---|---:|---|---|---|
| deep | 8 (5 FX legs, gold, silver, BTC) | 2015-01-07 | 2026-11-05 | 572,185 / 149,193 / 28,510 |
| wide | 22 (10 indices, 2 oils, 2 metals, 2 coins, 6 FX) | 2024-06-12 | 2026-11-07 | 222,194 / 58,944 / below the floor |
| synthetic | 13 Deriv families | 2019-01-05 | 2026-11-08 | 364,918 / 91,245 / 10,520 |

Cells under 1,200 bars are not reported, which is why the wide store carries no
daily row. **Duplicate timestamps are dropped unconditionally and counted**: 44
bars at 1h and 4h, 0 at 1d. The `spx500`/`us100` daily duplication found on
2026-11-10 is in the prices store, which this study does not read; the guard is
here because a duplicate bar doubles a detector's firing rate in silence.

The Deriv synthetics are **real markets with a published generator**, and the
property they control for is narrow and named: no participant in them leaves
unfilled interest, so there is no order block to flip, while they do have levels
(`Range Break` is the level positive control) and a switching drift
(`Drift Switch`). They are never pooled with the traded book and they are not a
tail control.

## Result

### The arms, pooled over the traded book

"`P` given resolved" is `P(>= 2R)` among the trades that reached a barrier at
all; a finite hold makes `1/(1+N)` an upper bound rather than the rate, and the
conditional rate is the quantity a walk must put on 0.3333.

| arm | n | `P(>= 2R)` | `P` given resolved | mean R, day-blocked | cost | net |
|---|---:|---:|---:|---|---:|---:|
| **breaker (`flip`)** | 23,751 | **0.2980** | 0.3164 | **-0.0263** [-0.0468, -0.0032] | 0.0536 | -0.0800 |
| breaker, confirmed | 4,515 | 0.2726 | 0.3060 | -0.0330 [-0.0766, +0.0108] | 0.0464 | -0.0794 |
| **the refuted fade** | 21,995 | 0.2901 | 0.3081 | -0.0478 [-0.0677, -0.0264] | 0.0535 | -0.1013 |
| **the placebo** | 22,167 | 0.2966 | 0.3152 | -0.0286 [-0.0535, -0.0035] | 0.0497 | -0.0783 |
| arithmetic null | | **0.3333** | 0.3333 | 0.0000 | | |
| `iid` walk | 74,728 | 0.3166 | 0.3187 | -0.0406 | | |
| `garch` walk | 74,217 | 0.3187 | 0.3207 | -0.0343 | | |
| `contopen` walk | 68,894 | 0.2891 | 0.3120 | -0.0283 | | |
| `shipped` walk | 32,409 | 0.2695 | 0.2989 | -0.0956 | | |

Every mean has its median beside it, because one row has ended a study here
before: the flip arm's median R is **-1.00**, its range is [-5.60, +11.43], and
winsorising to [-1.5, 2.5] or dropping the 235 gap exits moves the mean by
**0.0001R**. Record consistency over all 420,856 rows: 0 rows claim a target
they did not reach, 0 reach one without claiming it, 0 are unresolved without
having timed out, and 0 stops paid anything but -1R.

### The gaps, which are the finding

Paired on days, so the two arms see the same market conditions:

| | pooled | 1h | 4h | 1d |
|---|---|---|---|---|
| **flip - placebo**, paired | **+0.0023** [-0.0228, +0.0292] | -0.0026 [-0.0315, +0.0269] | +0.0130 [-0.0433, +0.0646] | +0.0756 [-0.0842, +0.2353] |
| flip - fade, paired | +0.0215 [-0.0106, +0.0534] | +0.0213 [-0.0133, +0.0547] | +0.0176 [-0.0459, +0.0784] | +0.0545 [-0.1132, +0.2159] |
| flip - `iid` walk | +0.0143 +- 0.0103 | +0.0099 +- 0.0116 | +0.0254 +- 0.0235 | +0.0650 +- 0.0665 |
| flip - `contopen` walk | +0.0019 +- 0.0103 | +0.0032 +- 0.0117 | -0.0030 +- 0.0236 | -0.0032 +- 0.0674 |
| flip - `shipped` walk | +0.0693 +- 0.0129 | +0.0715 +- 0.0147 | +0.0556 +- 0.0292 | +0.0379 +- 0.0844 |
| **the round trip it must clear** | **0.0536** | 0.0600 | 0.0325 | 0.0166 |

Read the placebo row, not the walk rows. The two geometry arms disagree by
0.067R on this trade for the reason the section above gives, so `flip - walk`
is a statement about bar assembly; the placebo runs on the same bars through the
same construction and reads **+0.0023R**. The largest gap over a *generated*
walk is **+0.0143R** (iid, pooled) with a standard error of 0.0103, against a
round trip of 0.0536R - so even read at face value and ignoring that it does not
clear two standard errors, it is **27% of a spread**. That is the same shape
[`statespace-directional-edge.md`](statespace-directional-edge.md) reports for
every directional gate measured here, which earns about 2% of a spread against
the 1.0 it needs.

### Per clock, and per instrument

| clock | n | `P(>= 2R)` | mean R | fade | placebo | `contopen` | net |
|---|---:|---:|---|---:|---:|---:|---:|
| 1h | 18,610 | 0.2977 | -0.0262 [-0.0504, -0.0030] | -0.0475 | -0.0236 | -0.0294 | -0.0861 |
| 4h | 4,574 | 0.2973 | -0.0290 [-0.0719, +0.0144] | -0.0466 | -0.0420 | -0.0260 | -0.0615 |
| 1d | 567 | 0.3122 | -0.0096 [-0.1220, +0.1129] | -0.0641 | -0.0852 | -0.0064 | -0.0263 |
| Deriv, all clocks | 11,027 | 0.3243 | -0.0167 [-0.0440, +0.0123] | -0.0350 | -0.0351 | -0.0272 | -0.0447 |

By family, weighted by n: index -0.0627, fx -0.0378, deriv -0.0167, metal
-0.0008, crypto +0.0170 (n 2,475), energy +0.0440 (n 746). **Net of cost every
family is negative except energy at +0.0059 on 746 trades**, which is four cells.

Per (instrument, clock), 98 cells:

| | count |
|---|---:|
| traded cells with a nominally positive mean | 29 of 68 |
| traded cells with a day-blocked lower bound above zero | **0 of 68** |
| Deriv cells with a lower bound above zero | 2 of 30 - **Boom 1000 Index** 4h (n 50) and **Boom 500 Index** 1h (n 294) |
| cells beating **zero** at a day-blocked p < 0.05 | 3 of 98 |
| cells surviving Benjamini-Hochberg at q 0.05 | **0 of 98** |

The per-cell test is against zero rather than against a walk, because the two
geometry arms disagree by 0.067R on this trade and a per-cell test against one
of them would rest on an assembly choice. Zero is also the harder floor: every
walk arm reads negative.

**The only cells that pass are in the arm that must be empty.** Boom and Crash
spike one way by construction, so a short arm on them is a different trade; this
is `a-control-is-only-for-a-named-property` and
`the-placebo-arm-selects-the-null` arriving together, and the right reading is
that the test's positives at this sample size are noise.

### Overlap, non-overlap, halves and legs

* **Non-overlapping subsample**, one live trade at a time per instrument, clock
  and arm: flip -0.0231 [-0.0478, -0.0002] on 19,764, placebo -0.0310, fade
  -0.0448. The ranking and the magnitudes survive, so the dense overlap that
  `HOLD` and `EXPIRE` create is not carrying the reading.
* **Split halves**, reported as information and not a verdict: 1h flip -0.0245
  then -0.0279, 4h -0.0337 then -0.0243, 1d +0.0538 then -0.0728. Both halves
  negative on both intraday clocks; the 1d halves straddle zero on 283 trades
  each, which is below the floor.
* **Legs.** 1h flip long -0.0077 (n 9,148), short -0.0441 (n 9,462). The
  population is 49/51, so nothing here is a standing short - the defect that
  took the first version of `order-block-zones.md` apart.
* **Deep against wide.** -0.0257 [-0.0508, -0.0020] on the eight instruments
  with 11.8 years, -0.0281 [-0.0776, +0.0204] on the twenty-two with 2.4. Adding
  22 instruments did not reverse the sign, which is the test
  `widening-the-universe` exists for.

### The sweep, in full

One parameter moved at a time from the pre-registered default - never the full
cross - over three clocks, three arms and four targets. **432 cells, 0 with a
lower bound above zero.** The flip arm at 2R:

| config | 1h | 4h | 1d |
|---|---:|---:|---:|
| pre-registered default | -0.0258 | -0.0277 | -0.0096 |
| `pad` 0.25 | -0.0157 | -0.0084 | -0.0331 |
| `pad` 0.5 | -0.0130 | -0.0129 | -0.0644 |
| `band` body | -0.0378 | -0.0435 | +0.0145 |
| `swing` 5 | -0.0307 | -0.0062 | -0.0531 |
| `swing` 20 | -0.0065 | -0.0099 | +0.0225 |
| `expire` 50 | -0.0277 | -0.0235 | -0.0022 |
| `expire` 1000 | -0.0259 | -0.0315 | -0.0146 |
| `hold` 5 | -0.0197 | +0.0004 | -0.0167 |
| `hold` 30 | -0.0217 | -0.0132 | -0.0142 |
| `hold` 120 | -0.0256 | -0.0330 | -0.0239 |
| `hold` 300 | -0.0251 | -0.0337 | -0.0225 |

The best cell anywhere is `swing` 20 at 1d and a 3R target, **+0.0339 +-
0.1037** on 269 trades. `P(>= NR)` is below `1/(1+N)` in **every** cell at every
N: the default at 1h reads 0.4621 / 0.2982 / 0.2062 / 0.1464 against 0.5000 /
0.3333 / 0.2500 / 0.2000.

## The prior study's arms, and why its number is not contradicted

[`order-block-zones.md`](order-block-zones.md)'s open positive is **+0.337R at
1d and +0.506R at 4h**. This study does not reproduce it and does not refute it
in the same object, for two reasons that have to be stated separately.

**First, the zone is a different zone.** `MODE=overlap` runs LuxAlgo's
construction and `zones.ob_zones` over the same 219,000 bars on eight
instruments:

| | LuxAlgo | the desk's rule | both |
|---|---:|---:|---:|
| order blocks cut | **20,133** | **1,316** | 58 |
| Jaccard of the block bars | | | **0.0027** |
| share of the desk's blocks LuxAlgo finds | | | **0.0441** |

Fifteen times the firing rate and almost no agreement. The desk's rule wants two
impulsive candles at a 70% body floor, an imbalance, and a break of structure
that holds three bars and travels an ATR; LuxAlgo wants a swing high, a close
through it, and the lowest low in between. `displace` and `DISPLACE_C` agreed on
a quarter of their union and were correctly kept apart; these two agree on 0.3%.

**So the desk's own blocks were run too**, with the published flip lifecycle
applied to them - which is the mechanical definition that study lacked and the
whole reason this one exists (`ZONES=desk`):

| arm, the desk's blocks | n | `P(>= 2R)` | mean R, day-blocked | cost |
|---|---:|---:|---|---:|
| **breaker (`flip`)** | 1,535 | 0.3094 | **-0.0641** [-0.1340, +0.0063] | 0.0680 |
| the refuted fade | 1,389 | 0.3276 | -0.0097 [-0.0859, +0.0654] | 0.0703 |
| the placebo | 1,417 | 0.3253 | -0.0168 [-0.0916, +0.0578] | 0.0607 |
| flip - placebo, paired | | | **-0.0472** [-0.1499, +0.0541] | |
| 1h | 1,162 | 0.3141 | -0.0485 [-0.1284, +0.0307] | 0.0749 |
| **4h** | 328 | 0.2927 | **-0.1189** [-0.2668, +0.0335] | 0.0486 |
| **1d** | **45** | 0.3111 | **-0.0667 [-0.4667, +0.3636]** | 0.0286 |

On the desk's own population the flip is **worse** than both its controls, and
0.9297 of its blocks flip too. At 4h the interval excludes +0.506R. **At 1d it
excludes nothing**: 45 trades give a half-width of 0.4R, so the 1d claim is not
refuted here - it is unmeasurable on this data, and saying so is the result. One
cell of 96 survives Benjamini-Hochberg on this population: **XAGUSD at 1d on n =
4**, which is what BH cannot protect against and what the sample floor is for.

**Second, the prior study's arms did not hold for the same number of bars.** Its
`real` arm ran at `HOLD_DAYS = 5` while `flip`, `straight` and `coin` ran at
`MAXHOLD = 300`, so at 1d the comparison moved the side, the entry style *and* a
sixty-fold holding period at once. Measured here on one rule with only the hold
changed, at 1d:

| hold | `P(>= 2R)` | `P(>= 4R)` | mean R at 2R |
|---|---:|---:|---:|
| 5 bars | 0.1129 | 0.0159 | -0.0167 |
| 60 bars | 0.3122 | 0.1411 | -0.0096 |
| 300 bars | 0.3245 | 0.1764 | -0.0225 |

The hit rate moves by **2.9x at 2R and 11.1x at 4R**; the mean moves by at most
0.065R across every clock and target. So the asymmetry is a real defect in that
study's arm construction and is **not large enough on its own** to produce
+0.337R. Every arm here holds 60 bars.

## Power, and where it goes blind

A drift of `g` R spread over the holding window is added to the forward path
**from the fill bar on**, so the detector and the fill are untouched and `g` is
exactly "the edge this trade would have to carry". Pooled over the real series,
the flip arm:

| planted edge | 0 | 0.05R | 0.1R | 0.2R | 0.4R | 0.8R |
|---|---:|---:|---:|---:|---:|---:|
| measured mean R | -0.0215 | -0.0131 | -0.0046 | +0.0154 | +0.0518 | +0.1220 |
| z | -2.64 | -1.61 | -0.56 | **+1.88** | +6.25 | +14.53 |
| `P(>= 2R)` | 0.3078 | 0.3100 | 0.3123 | 0.3184 | 0.3288 | 0.3501 |

The placebo arm's curve tracks it to within 0.004R at every strength, which is
the control working. **The test is blind below about 0.2R of planted edge** and
sees 0.4R comfortably. About **a fifth of each plant** is what the estimator
resolves, because a drift spread over 60 bars mostly has not arrived when the
median trade closes in 5 - so the blind spot in realised terms is 2 sigma, which
is 0.019R at 1h, 0.040R at 4h and **0.11R at 1d**.

Two consequences, and they point opposite ways:

* at 1h and 4h the blind spot is **below the round trip** (0.0593R and 0.0324R),
  so the test can see any edge large enough to matter, and it sees none;
* at 1d on the published blocks the half-width is 0.117R, which **does** exclude
  +0.337R - but at 1d on the desk's blocks it is 0.4R, which does not. The
  unsettled positive therefore remains unsettled in the one place it was found,
  and the reason is sample, not method.

## Cost, re-derived

`./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=cost`, the
terminal's own ask minus bid through `research/harness/venue.quoted`, 2026-11-10.
Two columns because they answer different questions: `swing20` is the survey's
geometry and reproducing it checks that this harness reads the same book;
`breaker` is **this rule's own realised stop**, the median over the trades it
actually takes.

| clock | breaker stop, ATR | `swing20` stop, ATR | breaker cost, median | range | inside 0.16 of risk |
|---|---:|---:|---:|---|---:|
| 1h | 1.27-1.87 | 3.53 | **0.0416** | 0.0082-0.3113 | 25 of 27 |
| 4h | 1.14-1.85 | 3.55 | **0.0204** | 0.0039-0.1354 | 27 of 27 |
| 1d | 1.19-1.42 | 3.46 | **0.0085** | 0.0065-0.0624 | 8 of 8 |

**The survey priced this idea at a stop 2.6x wider than the rule uses.** It
quoted `swing20` at 0.006-0.074 of risk at 15m, median 0.017, and concluded the
idea "is affordable at every clock the venue serves". That conclusion survives at
4h and 1d and fails on two instruments at 1h - XAGUSD at 0.2500 and XCUUSD at
0.3113 - because a breaker's stop is the zone plus a pad and not a 20-bar swing.
Three of the thirty traded instruments are **unpriced** (the bridge did not
answer for AUDCAD, EURCAD or BNBUSD); they are reported as geometry and carry no
cost column, never a zero.

Both numbers carry the width the survey recorded: a **single live snapshot**, and
two snapshots of the same book two days apart disagreed by 3.7x on gold. A cost
screen wants a week of quotes and does not yet have one.

## What is refuted, what is not, and what is merely unmeasurable

**Refuted.**

* The **published breaker block** as a trade, at 1h, 4h and 1d, on 30 traded
  instruments and 23,751 trades: it reaches 2R less often than the arithmetic
  rate (0.2980 against 0.3333), and it is within **+0.0023R** [-0.0228, +0.0292]
  of a distance-matched prior swing with no order block behind it. Neither of
  those two statements needs a surrogate, which is why they carry the verdict.
* **The polarity flip as a source of information.** 92.6% of order blocks flip,
  so "flipped" selects almost nothing, and EmreKb's confirmation - which does
  select, applying to a quarter of flips - reads worse than no confirmation.
* **The reframing.** The rule for reopening a refuted claim is that the new
  statistic beats its null where the old one does not. Here **neither** beats
  it, so there is nothing to assign to the flip and the fade's refutation stands
  unchanged.
* On **the desk's own blocks** with the published lifecycle, the **4h** half of
  the prior study's open positive: -0.1189R [-0.2668, +0.0335] on 328 trades
  excludes +0.506R.

**Not refuted, and not supported.**

* The **1d** half of the prior study's open positive **on the desk's own
  blocks**. 45 trades, [-0.4667, +0.3636]. The sample is 3.4 times too small and
  the daily clock is a UTC day rather than the broker's session. This is the one
  cell in the study where the honest answer is *unmeasurable*, and the way to
  settle it is the frozen forward test that document already asked for - not
  another pass over the same bars.

**Unmeasurable on the data available.**

* Anything at 1d on the wide store: 2.4 years of 15m folds to about 520 daily
  bars, under the 1,200-bar floor, so the daily clock rests on eight instruments.
* The maker side. Every entry here is a resting limit charged a full round trip,
  which is what crossing from ask to bid costs; `polymarket-taker-fee` aside,
  this desk has no measured maker rebate to credit.
* **Whether a resting-limit arm has any edge against a surrogate at all.** The
  two geometry arms put this trade 0.067R apart and neither matches the market's
  intrabar assembly, so the question is not answerable on bar data and no
  `flip - walk` number here should be read as one. Settling it needs ticks,
  which `research/mt5bt` can use (`Book.ticks`, `walk_ticks`) and this study's
  stores do not carry.
* Whether the same sensitivity has moved a published number in
  [`level-shield.md`](level-shield.md) or the studies downstream of
  `walk_with_bar_geometry`. Their statistic is a two-sided first-passage rate
  rather than a limit-order trade and may well absorb it; **this study did not
  measure that** and the question is left open rather than asserted either way.

## Caveats

* **Three clocks are three detectors.** `SWING`, `EXPIRE` and `HOLD` are bar
  counts, so the 1d rule looks back ten days where the 1h rule looks back ten
  hours. That is what the published script says and it is why no number is
  compared across clocks except by naming the horizon.
* **The placebo matches height, not staleness.** Zone heights match to 1.197
  against 1.201 units at the median with the same quartiles, but the median wait
  from the zone being known to its flip is 86 bars for the breaker and 60 for
  the placebo. A level that has stood longer is a different object, and that
  difference is unmatched.
* **Neither geometry arm preserves everything, and they fail differently.**
  `shipped` draws `span` and the shape pair independently, so a bar's body share
  survives as a marginal but its joint with the bar's size and with the bar's own
  move does not. `contopen` makes the body the step, so that joint is exact, and
  rebuilds body share from marginals instead. Two readings here grade on body
  share - `zones.ob_zones` at `PUSH_BODY` 0.70 and `ORIGIN_BODY` 0.45, and the
  `BAND=body` sweep cell - and are mis-nulled by `contopen`; the pre-registered
  `BAND=range` detector reads no body share but its flip condition does read
  where a body sits inside its bar. Both arms are reported for that reason and
  the iid and GARCH arms are read beside both.
* **No ticks.** Every both-barriers-in-one-bar race is given to the stop, which
  is conservative and identical across arms, and is why the walks read 0.31
  rather than 0.3333 conditional on resolving.
* **One snapshot of cost**, as above.
* **The multiplicity count.** 98 instrument-clock cells, 432 sweep cells, 4
  arms, 5 null series, 2 zone populations. Nothing was selected on; the full grid
  is printed; and 0 cells survive BH on the published population.
* **One claim in this document was withdrawn and then reinstated**, and the
  banner at the top says which and why. The numbers involved are the `walk`
  columns and nothing else; the verdict rests on `P(>= 2R)` against its
  arithmetic rate, on a placebo running through the identical construction, and
  on per-cell counts, none of which touches a surrogate.

## Re-running

    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=cost    OUT=.data/breaker
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=run     OUT=.data/breaker WORKERS=28
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=run     OUT=.data/breakerdesk ZONES=desk WORKERS=28
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=sweep   OUT=.data/breaker WORKERS=28
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=power   OUT=.data/breaker
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=overlap OUT=.data/breaker
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=gap     OUT=.data/breaker
    ./.secrets/lab.sh exec 'cd ~/till_infinity && PYTHONPATH=$HOME/till_infinity/repo \
        OUT=.data/breaker .venv/bin/python -u repo/research/ideas/breaker_report.py'

Set `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1` on any pooled
mode. `MODE=smoke` runs on generated bars in seconds and prints every stage's
count, which exists because a detector that finds nothing and a detector that is
out of scope read identically.

Outputs under `$OUT`, none committed: `trades.csv.gz` (one row per real trade
per target), `cells.csv` (every arm and every null series summarised),
`zones.csv` (firing rates and drops), `cost.csv`, `sweep.csv`, `power.csv`,
`overlap.csv`, `gap.csv`, `per_instrument.csv`.
