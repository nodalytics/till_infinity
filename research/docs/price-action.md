# Four price-action patterns, and the entry mechanic that pays +0.22R on a driftless walk

**Measured 2026-11-10.** The rules as the sources state them are frozen in
[`price-action-rules.md`](price-action-rules.md), written before any of this
ran. Code: [`price_action.py`](../ideas/price_action.py),
[`price_action_run.py`](../ideas/price_action_run.py),
[`price_action_power.py`](../ideas/price_action_power.py),
[`price_action_report.py`](../ideas/price_action_report.py), tests in
[`test_price_action.py`](../ideas/test_price_action.py).

The headline is a defect, and it is the most valuable thing here.

## Verdict

| question | answer |
|---|---|
| Is the **inside bar** breakout, entered and stopped as the only page that states both says to, worth anything at 1d? | **No.** Both sides, 1,976 trades over 14 feeds and 19.2-19.9 years: **-0.0640R +- 0.0341** against the same mechanics at random bars, **4 of 14 feeds positive**. With the trend it is -0.0115 +- 0.0347. The best-reading variant anywhere - with the trend and the page's own 50% stop - is **+0.0503 +- 0.0351**, z +1.43, which does not survive 92 cells |
| Is the **pin bar** worth anything? | **No on the two entries the sources describe in prose**: at market on the close **-0.0103R +- 0.0311** on 2,066 trades, on stop beyond the nose **-0.0545 +- 0.0337**, 4 of 14 feeds positive. **The 50%-of-the-tail limit is the one strong reading in the study and its own calendar-shuffled twin reproduces it**: +0.1602 +- 0.0347 (z +4.61, 13 of 14 feeds) against the twin's +0.1479, so **+0.0123 over the hardest null** |
| Is the **fakey** worth anything? | **No.** +0.0222R +- 0.0407 on 1,210 trades, 7 of 14 feeds, and the whole `break_ref` x `close_back` x `fake_bars` sweep sits inside its nulls. A **GARCH twin makes 30% more fakeys than the market** (86.2 against 66.4 per 1,000 bars) |
| Is the **inside-pin combo** worth anything? | **No, and it is the only pattern the market makes more of than any surrogate** - 23.3 against 18.4-20.8 per 1,000 bars. Traded it reads **-0.0829R +- 0.0553** on 687 trades, and per feed that is 20-60 trades, below the floor |
| Does **confluence** help, as "at least two supporting factors"? | **No, and the placebo arm is what says so.** At three of the four codeable factors the real arm reads **+0.0219 +- 0.0240** on the inside bar and **-0.0132 +- 0.0298** on the pin bar, while the **same rule over levels displaced 1.5-3.0 units** reads **+0.0551 +- 0.0311** and **+0.1172 +- 0.0446** - the placebo is the only cell in the table past |z| 2. `the-placebo-arm-selects-the-null` rejects the null rather than passing the claim |
| Is **"the lower the timeframe the less effective"** true? | **Not as stated, and the data cannot contradict it either.** The sign is **not monotone in the clock on any of the six rules**, the inside bar's best cell is at **1h** (+0.1016, z +2.38) rather than 1d, and the largest |z| over 24 (rule, clock) cells is 2.42. What *is* monotone is the cost: **0.0023-0.0034R at 1d against 0.0494-0.0749R at 15m**, a 21x multiplier that turns three of six positive 15m gross readings negative. The signal half stays **unmeasurable** - the store holds ~5,000 bars per feed at *every* interval, so 1d is 19 years and 15m is seven weeks |
| Is **"the 50% retrace of the last major move"** the displacement origin? | **No.** It is within 0.25 units of the displacing body's midpoint on **0.1894** of 59,765 windows, against **0.1888 for a random prior bar's midpoint**. Different constructions, so [`displacement-origin.md`](displacement-origin.md) is not cited as covering it |
| Does **cost** kill it first, as it usually does here? | **No, and that is unusual.** These are wide-stop rules - risk 0.58-1.28 volatility units - so **0 of 42 costed cells at 1d, 4h and 1h exceed the desk's 0.16R ceiling**, against [`scalping.md`](scalping.md)'s 42 of 249 refused unmeasured |
| Where does the test go blind? | **Below about 0.20R of planted drift.** |z| > 2 arrives at a plant of 0.40R on the fakey and 0.80R on the other three, and about a quarter of each plant is what the estimator resolves. An edge the size of the 15m cost is inside the blind spot |
| Did the harness reproduce a known number? | **Yes, twice.** The inside-bar rate reads **0.159** against [`inside-bars.md`](inside-bars.md)'s 0.140-0.168, and the clock cost multiplier reads 21x against `a-shorter-clock-multiplies-cost-in-r`'s 19x |
| What is the most valuable thing here? | **The defect.** A stop-order entry settled from the next bar pays **+0.2234R +- 0.0541 on a driftless walk**, and the placebo the study started with turned that into a +0.2474R "edge" |

## The defect, first, because it decided the study

The sources' entries are resting **stop** orders - "place a buy stop or sell
stop at the high or low of the mother bar" - so a fill happens mid-bar at the
trigger price, and bar-level data cannot say where in the bar. The first
version of this harness did what [`level-bounce.md`](level-bounce.md) and
`smc_battery.py` both do and began the barrier race on the bar **after** the
fill. That is the fix for the leak
[`smc-conjunctions.md`](smc-conjunctions.md) paid for - settling *on* the fill
bar uses that bar's other extreme, which may have printed before the entry
touch - and on a stop-order entry it introduces the opposite one.

Conditional on a buy stop filling, that bar closed **above** the trigger on
average. Starting the race at the next bar therefore starts it nearer the
target and further from the stop, and the whole favourable displacement from
the trigger to the close is a gift. Measured on a driftless walk built at
sub-bar resolution, where the answer must be exactly zero:

`PA_WALK=1 uv run python research/ideas/price_action_power.py`, six walks of
4,000 bars, the inside-bar breakout at a 2R target and a 20-bar horizon:

| arm, on a driftless walk | mean R at 2R | n |
|---|---:|---:|
| **the rule, entering at the trigger** | **+0.2234 +- 0.0541** | 743 |
| a placebo entered at a random bar's **close** | -0.0240 +- 0.0162 | 7,515 |
| **the gap the first harness would have reported** | **+0.2474 +- 0.0565** | |
| a placebo entered through **the same mechanics** at random bars | +0.2114 +- 0.0161 | 8,403 |
| **the gap after the fix** | **+0.0121 +- 0.0565** | |
| the rule, entering at the fill bar's **close** | +0.0272 +- 0.0539 | 698 |
| its gap against the close-entry placebo | +0.0745 +- 0.0564 | |
| **its gap against the same mechanics** | **+0.0019 +- 0.0563** | |

A walk is a martingale, so +0.2234R is impossible and the number is the
mechanic, not the market. Two things were changed, and both are recorded as
deviations in [`price-action-rules.md`](price-action-rules.md):

* **the placebo runs through the same construction**, picking random bars and
  applying the identical entry, stop, side and expiry, so the mechanic appears
  in both arms and cancels to +0.0121 +- 0.0565;
* **a second settlement is carried**, `at-close`, entering at the fill bar's
  close, which is leak-free because the entry price and the first bar of the
  race are the same instant. It reads +0.0272 on the same walk, so most of the
  mechanic is gone before any placebo is subtracted, and the residual +0.0745
  against the wrong placebo is what the mechanic is worth once the entry price
  and the race start together.

**Both numbers matter and they say different things.** The `at-trigger` column
is the sources' rule and is only readable against a placebo that fills the same
way; the `at-close` column is a worse trade - a bar that ran a long way past
the trigger buys a wider stop and a worse R - and is the one a reading can be
taken off without trusting the placebo to cancel a quarter of an R.

`test_a_walk_pays_nothing_against_its_own_matched_placebo` pins both
settlements against their own standard error, so this cannot come back
silently.

## Half of two feeds' daily history is printed twice

Found by reading `n` as a claim about the world, which is the check
`slope_fade.py` paid for - there, `n = 3159` independent daily observations
needed 15,800 daily bars and the file duly began in 1971.

| feed, 1d | venue | rows | distinct timestamps | bars a year |
|---|---|---:|---:|---:|
| **spx500** | YAHOO | 6,005 | **3,006** | **502.9** |
| **us100** | YAHOO | 6,008 | **3,009** | **502.6** |
| gold | YAHOO | 5,009 | 5,009 | 251.5 |
| eurusd | FOREXCOM | 5,002 | 5,002 | 260.0 |
| btc | BITSTAMP | 5,012 | 5,012 | 365.1 |

503 bars a year on a daily series, for an index that trades about 252 days.
**2,999 bars of each appear twice in a row**, and at 1h the same two feeds
carry 6 duplicates each. Nothing else in the fourteen feeds at four intervals
is affected: FOREXCOM's FX reads 260 a year (a five-day week, 19.2 years from
2007) and the crypto venues read 365.

A duplicated bar is not a harmless repeat. The volatility unit is an EWMA over
bars, so a doubled series **halves its effective span**; a 20-bar horizon
covers ten real days; `Fold` confirms swings over doubled windows; and a
first-passage search can resolve on the copy. Every statistic downstream is
quoted in a unit that is not the one it names. The loader here collapses
duplicate timestamps and the share travels in the panel output as
`dup_share`.

**One accidental protection is worth recording.** `inside` refuses a pair with
the same high *and* the same low - which is priceaction.com's own clause,
"two bars with the same high and low, it's generally not considered an inside
bar by most traders" - so the inside-bar detector was the one thing the
duplicates could not fool. A rule written for traders' taste happened to be a
data guard.

**`level_shield.load` is not changed**, because it is the loader
[`level-shield.md`](level-shield.md), [`level-bounce.md`](level-bounce.md) and
[`stop-coverage.md`](stop-coverage.md) read, and changing it under them would
silently alter three published panels. That those three read the same
contaminated series on `spx500` and `us100` at 1d is **reported here rather
than fixed**: two of fourteen feeds, so it will not have decided any of them,
but on those two feeds at 1d every span stated in bars - the volatility unit,
the compression stratifier, the forward horizon - covers **half the time it
names**.

## The sources, and that there is one method rather than three

| tag | what it is | what it was worth |
|---|---|---|
| **PA** | `priceaction.com/price-action-university/`, nine pages | the only complete entry-and-stop statement, on the inside-bar page |
| **LTTM** | `learntotradethemarket.com`, six pages | **every number in the study**: the 2/3 tail share, the 1-pip stop, the 8/21 EMAs, the 50-61.8% band, "at least two supporting factors" |
| **VID** | a four-hour YouTube "Complete Price Action Course" | **nothing; dropped as a rule source** |

**PA and LTTM are one author and are not two sources.** Both are bylined Nial
Fuller; the PA start page's bio reads "He has a monthly readership of 250,000+
traders and has taught over 30,000+ students since 2008" and links to
`learntotradethemarket.com/forex-trading-course`, and "fakey" is his coined
term and appears on both. Counting them as two corroborating sources would
inflate confidence in exactly the way
[`smc-conjunctions.md`](smc-conjunctions.md) warns about, where two published
SMC frameworks turned out to be one shape under two names. What the second
presentation is worth is narrower and real: it states the numbers the first
leaves qualitative.

**The video is a different method and is recorded rather than used.** Its
captions transcribe cleanly, so this is not a transcription problem. Over 7,253
caption lines it says "pin bar" **0** times, "inside bar" **0**, "fakey" **0**,
"confluence" **0** and "key level" **0**, against "liquidity" 137, "supply" 146
and "demand" 162. It names no author, states no mechanical entry, stop or
target - its numbers are discretionary chart readings, "a 6.51 risk to reward"
at 02:45:22 on one example and "the stop loss under the low" at 02:34:04 - and
the material it does cover is already measured here in
[`order-block-zones.md`](order-block-zones.md),
[`smc-conjunctions.md`](smc-conjunctions.md) and `sweeps.md`.

**Nine of the fourteen pages specify nothing that the overview did not**, which
is itself a reading on a method described as mechanical. The full
clause-by-source table is in [`price-action-rules.md`](price-action-rules.md).

## Cost, first, and it does not kill this one - which is unusual here

Cost in R is `round_trip / risk` and is set by the **stop**, not the target
(`domain/costs.py`: a permitted spread scaled to the target lets a distant
target buy the right to pay more, and the desk's measured limit is 0.16 of the
risk). These rules place the stop at the far end of the mother bar or beyond a
pin bar's tail, so the risk runs **0.58 to 1.28 volatility units** - wide - and
that is what makes them affordable where [`scalping.md`](scalping.md)'s 1xATR
scalps were not.

The spread is the median recorded bid/ask **per feed per venue, never pooled**,
and a feed with no quotes on its chosen venue carries no costed number rather
than a guessed one.

| clock | feed | spread | risk | round trip over risk |
|---|---|---:|---:|---:|
| 1d | eurusd | 0.174 bps | 0.68-1.13 u | **0.0020-0.0034R** |
| 1d | gbpusd | 0.222 bps | 0.65-1.17 u | 0.0024-0.0043R |
| 4h | us100 | 0.370 bps | 0.69-1.12 u | 0.0053-0.0087R |
| 4h | spx500 | 0.516 bps | 0.58-1.28 u | 0.0089-0.0197R |
| 1h | eurusd | 0.174 bps | 0.64-1.04 u | 0.0175-0.0283R |
| 15m | eurusd | 0.174 bps | 0.68-1.01 u | 0.0388-0.0619R |
| 15m | gbpusd | 0.222 bps | 0.70-1.15 u | 0.0422-0.0691R |
| 15m | us100 | 0.605 bps | 0.66-1.05 u | 0.0313-0.0496R |
| 15m | spx500 | 0.774 bps | 0.62-1.01 u | 0.0749-0.1232R |
| 15m | gold | 1.929 bps | 0.67-1.16 u | **0.0828-0.1433R** |

**0 of 42 costed cells at 1d, 4h and 1h exceed the ceiling, and none at 15m
does either** - gold's 0.1433R at 15m on the tightest entry is the dearest cell
in the study and still inside 0.16. Against [`scalping.md`](scalping.md), where
a 1xATR stop refused 42 of 249 cells unmeasured, the difference is entirely the
stop: these rules place it at the far end of a mother bar instead of one ATR
away, and a wide stop is what makes a clock affordable.

The 1d to 15m ratio on eurusd is **0.0020 to 0.0416, a 21x multiplier**, which
reproduces `a-shorter-clock-multiplies-cost-in-r`'s measured 19x from a
different estimator and a different store.

**Three feeds carry no costed number at 1d at all** - gold, spx500 and us100 -
because the venue with the most daily bars is YAHOO and YAHOO has **zero**
recorded quotes. That is the rule working: no spread is invented for them, and
their 1d numbers are geometry.

**btc is excluded from the cost screen and the reason is worth recording.** Its
chosen venues are BITSTAMP at 1d and BINANCE below, whose median recorded
spread is **0.0016 bps** - about a cent on sixty thousand dollars. That is a
plausible *spot exchange top-of-book* and it is not a tradeable round trip for
this desk, which trades a CFD and pays commission and funding that this store
does not carry. A cost of 0.0000R is not a cheap instrument, it is the wrong
instrument.

## What decides, and what is only description

**No source states a target.** Not one of the fourteen pages fetched; the
strongest statement anywhere is "Inside bars typically offer good risk reward
ratios". That is the opposite of [`patterns.md`](patterns.md)'s situation,
where the books supplied a measured move, reward-to-risk was *determined by the
geometry*, and a pattern could be refused on its shape alone against
`need = (1 + cost) / (1 + R:R)`. Here there is no geometry to refuse.

So the target is `k` times the **realised risk**, measured from the fill and
not from the pattern (`risk-vol-is-not-the-stop-distance`), with `k` in
1/2/3. On a driftless walk such a target is reached with probability `1/(1+k)`
and the expected R is **exactly zero at every k**, so no reward-to-risk can
manufacture a result and the study measures the entry and the stop the sources
*do* specify. The headline is read at 2R, as in
[`level-bounce.md`](level-bounce.md), so the two studies' races are the same
object.

**The deciding statistic is `excess`, not mean R.** A bar-level barrier race
does not pay `1/(1+N)`: [`level-shield.md`](level-shield.md) measured it
departing by -0.25 to +0.12R, monotone in the stop-minus-target distance,
growing with the interval, **and the surrogates do it harder** - at 1d a 4:1
reward:risk read -0.2529R where the closed form says zero while a GARCH twin
read -0.7274R. A raw mean R is therefore not comparable between a market and
its own surrogate, and comparing them would make a finding out of a replay
bias. Every arm is quoted as its own mean minus **the same rule's mechanics
applied at random bars on the same series**, twenty draws a setup, which is
simultaneously `patterns.md`'s geometry placebo and the **duty-cycle control** -
the comparison is mean R per trade at a matched trade count, and on a
net-negative book any rule that trades less otherwise shows a profit
improvement.

**The arm to beat is the hardest null, not the average of them.**
`let-the-shuffled-twin-names-the-mechanical-observables`: the highest-reading
arm is the one naming how much of the observable is definitional.

**One live trade at a time per cell**, so two scored trades never share
outcome bars (`overlapping-outcome-windows-leak` is a direction AUC of 0.79
that collapsed to 0.51). That is a large selection and it is counted rather
than hidden: at 1d it refuses about **two thirds** of inside-bar signals, so a
nineteen-year daily series yields 130-170 trades a feed and the pooled cell is
1,700-2,400 over fourteen feeds. **Per feed that is 90-170 trades, at or just
above the noise floor**, and the combo cells are 20-60 a feed, below it.

**The one filter that could select on the outcome is checked rather than
argued.** A race where neither barrier is reached inside the horizon is
dropped, not scored a loss - which is `level_bounce.race`'s rule and
`Visit.broke_edge`'s argument, a vertical barrier that expires is not a
stop-out - but it is the only selection here applied *after* the outcome
exists, and a filter written against the outcome is the most dangerous shape
this repo records. So the **drop rate is printed by arm**: on eurusd 1d the
inside-bar breakout resolves 0.890 of its races and its placebo resolves
0.888, and the `dec=` column carries both for every cell. A gap there would
mean the two arms are not being scored on the same population.

**Every other selection is set before the outcome exists** - `no_fill` and
`thin_risk` at the fill, `overlapped` from the previous trade's fill bar - and
all four counts travel in the census.

## The nulls, and the one that had to be added

Every arm goes through **the same detector over the same bar geometry**.
`level_shield.ARMS` is imported whole so this harness and
[`level-shield.md`](level-shield.md) cannot drift apart on what an arm is:

| arm | keeps | removes |
|---|---|---|
| `garch-bars` | volatility clustering, fat tails, bar wickiness | path structure |
| `walk-geometry` | bar wickiness, the step distribution | path structure **and** clustering |
| `bar-shuffle` | each bar's own shape, the marginal step distribution | all memory, **including the daily cycle** |
| **`calendar-shuffle`** (added here) | each bar's own shape **and its hour of day** | the ordering only |

**The fourth arm is required, not optional.** The inside bar is a two-bar
statistic and the fakey a three-or-four-bar one, and
[`inside-bars.md`](inside-bars.md) measured what that costs: the ordering
*suppresses* the inside-bar rate by 0.046-0.072 on an absolute rate of 0.15,
and **between a third and a half of that is the deterministic hour-of-day
cycle**, which a generated series has none of. A generated walk is therefore
not a sufficient null for three of these four patterns, and
`bar-shuffle` - which permutes globally - destroys the cycle along with the
ordering. `calendar-shuffle` permutes bars **within their hour-of-day bucket**
at 15m, 1h and 4h and within their **weekday** bucket at 1d, which is the only
deterministic cycle a daily bar has.

Four draws of each surrogate, as in `level-shield.md` and `level-bounce.md`, so
"outside the hardest arm's draws" is a statement about a range and not about
one number.

**Does the harness reproduce a known number?** Yes, on the one quantity that
can be checked. The inside-bar firing table below reads **287 signals per
1,000 bars on eurusd at 1d** for the two-sided cell, and that cell emits two
signals per inside bar, so the detector's inside-bar rate is **0.143** against
[`inside-bars.md`](inside-bars.md)'s **0.150** for fx majors measured on a
different interval with a different loader. What is *not* comparable is the
suppression's size: `bar-shuffle` here permutes arithmetic close-to-close steps
and reassigns each bar's shape independently, where `inside-bars.md` chained
each bar's own geometry onto the previous close, so the two "shuffled" arms are
different constructions and only the real rate is a reproduction.


## The firing rate says the wickiness confound cannot appear here

Signals per 1,000 bars at 1d, pooled over 14 feeds. A one-bar pattern and a
multi-bar one behave completely differently, and the reason is the arms'
construction rather than anything about markets.

| pattern | real | garch-bars | walk-geometry | bar-shuffle | calendar-shuffle |
|---|---:|---:|---:|---:|---:|
| **pin**, the sources' 2/3 tail | 120.42 | 120.95 | 120.47 | 120.47 | 120.48 |
| **pin**, `candles.hammer` | 65.60 | 65.93 | 65.87 | 65.65 | 65.63 |
| **pin**, `fuzzy.pin` graded | 155.93 | 154.98 | 155.43 | 155.07 | 155.76 |
| **inside** (two signals a bar, so a rate of 0.159) | 317.68 | 319.94 | 320.45 | 311.59 | 314.00 |
| **fakey** | 66.41 | **86.23** | 67.15 | 65.32 | 65.87 |
| **combo** (inside bar that is a pin) | **23.26** | 20.83 | 18.43 | 19.39 | 19.77 |

**A pin bar fires at the same rate on a market and on every surrogate of it, to
three significant figures.** That is not a null about pin bars; it is what the
arms are *for*. Every arm keeps each bar's own wick-to-body proportions by
construction - `bar_shuffle` and `calendar_shuffle` carry each bar's shape
intact and `garch_bars` resamples the shapes from the real ones - so a
single-bar shape statistic has the same marginal in all five columns and
**cannot** discriminate. The practical consequence is the useful one:
`how-markets-differ-from-every-simple-process`'s wickiness confound is a
statement about a market against a *generated* process, and it cannot
manufacture a pin-bar result here, in either direction, because no arm in this
panel removes wickiness.

Two multi-bar rates do move and both are worth recording. **A GARCH twin
produces 30% more fakeys than the market** (86.23 against 66.41): volatility
clustering makes a break-and-close-back more common than the market does, and
any fakey count read against a clustering null is reading that. And **the
inside-pin combo is the one shape the market makes more of than any
surrogate** - 23.26 against 18.43-20.83, 12 to 26% more - which is a real
conjunction effect in the *rate*, and the combo's traded excess above is
-0.0829 +- 0.0553. Occurring more often than a walk and paying less than one is
exactly the shape `pattern-fingerprint.md` describes.

The inside-bar rate is a **reproduction check**: 317.68 signals per 1,000 bars
on a two-sided cell is a rate of **0.159**, against
[`inside-bars.md`](inside-bars.md)'s **0.140-0.168** across traded classes.

**At 15m the two-bar arms separate and the one-bar ones still do not**, which
is the sharpest evidence that the calendar arm earns its place:

| pattern, 15m | real | garch-bars | walk-geometry | bar-shuffle | calendar-shuffle |
|---|---:|---:|---:|---:|---:|
| **pin**, the sources' 2/3 tail | 115.44 | 115.01 | 115.03 | 115.43 | 115.43 |
| **inside** | 314.21 | 333.92 | 284.88 | 280.19 | **253.90** |
| **fakey** | 73.44 | **90.25** | 67.23 | 66.17 | 62.24 |
| **combo** | 22.04 | 22.35 | 16.20 | 18.92 | 17.52 |

The pin bar is identical to four significant figures again. The inside bar
spans **253.90 to 333.92** across the arms where at 1d it spanned 311.59 to
320.45 - a 31% spread against a 3% one. A two-bar statistic is arm-sensitive at
the clock where the intraday cycle exists and nearly arm-insensitive at the
clock where it does not, which is what [`inside-bars.md`](inside-bars.md)
predicts and is the reason a generated walk alone would not have been a
sufficient null below 1d.


## The four patterns at 1d, as the sources prescribe them

14 feeds, 19.2-19.9 years of daily bars on the FX majors and gold, a 2R target
against a stop the source places, pooled across feeds and weighted by trades.
`excess` is mean R minus the same rule's mechanics at random bars on the same
series; `null` is the **highest-reading** of the four surrogate arms; `up` is
how many of fourteen feeds read positive.

| pattern, as prescribed | settle | n | excess | se | z | up | hardest null | over null |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **inside**, buy/sell stop at the mother bar, stop at its far end, both sides | trigger | 1,976 | **-0.0640** | 0.0341 | -1.88 | 4/14 | walk-geometry -0.1279 | +0.0639 |
| | close | 1,879 | -0.0331 | 0.0336 | -0.98 | 3/14 | walk-geometry +0.0036 | -0.0367 |
| **inside**, with the trend | trigger | 1,742 | -0.0115 | 0.0347 | -0.33 | 8/14 | calendar-shuffle -0.1053 | +0.0938 |
| | close | 1,653 | +0.0166 | 0.0365 | +0.45 | 8/14 | bar-shuffle +0.0089 | +0.0076 |
| **inside**, with the trend, the **50% stop** the page offers | trigger | 1,879 | **+0.0503** | 0.0351 | +1.43 | 11/14 | bar-shuffle -0.1041 | +0.1544 |
| | close | 1,682 | +0.0609 | 0.0360 | +1.69 | 11/14 | walk-geometry +0.0226 | +0.0383 |
| **pin**, at market on the close, stop a pip beyond the tail | both | 2,066 | -0.0103 | 0.0311 | -0.33 | 7/14 | garch-bars +0.0022 | -0.0125 |
| **pin**, on stop beyond the nose | trigger | 1,840 | -0.0545 | 0.0337 | -1.61 | 4/14 | garch-bars +0.0850 | -0.1395 |
| | close | 1,674 | -0.0577 | 0.0344 | -1.68 | 2/14 | bar-shuffle +0.0281 | -0.0858 |
| **pin**, the 50%-of-the-tail limit | close | 1,535 | **+0.1602** | 0.0347 | **+4.61** | 13/14 | calendar-shuffle **+0.1479** | **+0.0123** |
| | trigger | 1,542 | +0.0872 | 0.0415 | +2.10 | 9/14 | garch-bars **+0.4822** | **-0.3950** |
| **fakey**, entry back through the inside bar, stop at the false break | trigger | 1,210 | +0.0222 | 0.0407 | +0.55 | 7/14 | calendar-shuffle -0.0555 | +0.0777 |
| | close | 1,102 | +0.0048 | 0.0431 | +0.11 | 4/14 | garch-bars +0.0010 | +0.0038 |
| **combo**, inside bar that is a pin, buy stop at the mother high | trigger | 687 | -0.0829 | 0.0553 | -1.50 | 5/14 | bar-shuffle -0.0184 | -0.0645 |
| | close | 631 | -0.0671 | 0.0555 | -1.21 | 5/14 | bar-shuffle +0.0732 | -0.1403 |

**Nothing the sources prescribe clears its own mechanics.** Over 92 cells at
1d, **3 survive Benjamini-Hochberg** and all three are the same pin-bar entry -
the 50%-of-the-tail limit, settled at the close - at `+0.1031` to `+0.1602`.
And on every one of them the **calendar-shuffled twin reads +0.1105 to
+0.1331**, so the excess over the hardest null is **-0.0085 to +0.0123**. The
one statistically strong effect in the study is reproduced by a surrogate that
keeps each bar's shape and its hour of the week and destroys the ordering,
which is `let-the-shuffled-twin-names-the-mechanical-observables` doing exactly
its job: a limit resting at the midpoint of a long tail is a statement about
bar shape, not about what price did before the bar.

**Settled at the trigger the same entry reads +0.0872 while its GARCH twin
reads +0.4822.** A surrogate beating the market by four tenths of an R is not a
finding about the market; it is the entry mechanic plus volatility clustering,
and it is the clearest single illustration of why `excess` is quoted against
the hardest arm rather than against zero.

**The best-reading cell the sources actually prescribe is the inside bar with
the trend and the 50% stop, at +0.0503 +- 0.0351 (z +1.43, 11 of 14 feeds
positive).** Its hardest null reads -0.1041, so the gap over the null is
+0.1544 - the largest in the study. It does not survive BH over 92 cells, its
own t is 1.43, and the power sweep below says a 0.05R effect is invisible here,
so this is **the one cell worth a pre-registered out-of-sample test** and is
not reported as an edge. Nothing is gated on it.

**Both sides were taken and they disagree.** An inside bar is sideless in the
sources, and the long-only and short-only cells read -0.0365 and -0.0065 at the
trigger: the two-sided cell at -0.0640 is not one side carrying the other.


## The parameters the sources leave unspecified, swept

32 cells at 1d, one parameter moved at a time off the base cell, the whole grid
reported with its mean rather than the best cell with its z
(`sweep-thresholds-on-the-mean-not-z`). **0 of 32 survive Benjamini-Hochberg.**

**The tail share.** priceaction.com gives none; LTTM gives 2/3 of the bar
length. The sweep bites - the firing count falls from 2,631 to 1,518 trades -
and nothing moves with it.

| tail / range | pin at market: n | excess | se | over null | pin on stop: n | excess | se | over null |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.50 (`candles.TAIL_SHARE`) | 2,631 | +0.0161 | 0.0283 | +0.0030 | 2,363 | -0.0362 | 0.0306 | -0.0807 |
| 0.60 | 2,347 | -0.0109 | 0.0309 | -0.0029 | 2,101 | -0.0679 | 0.0322 | -0.1431 |
| **0.667 (LTTM's own)** | 2,066 | **-0.0103** | 0.0311 | +0.0097 | 1,840 | **-0.0545** | 0.0337 | -0.1392 |
| 0.75 | 1,518 | +0.0051 | 0.0368 | +0.0007 | 1,362 | -0.0031 | 0.0397 | -0.1042 |

**The method's own value is not special and no value is.** Across eight cells
the excess spans -0.0679 to +0.0161 and every one is inside one standard error
of zero; on the on-stop entry all four are negative and all four are below
their own hardest null by 0.08 to 0.14R.

**The "1 pip" beyond the tail is worth 0.0016R.** The same cell with the pad at
zero reads -0.0529 against -0.0545 with it, which is the sources' only stated
stop distance measured and found to be below the resolution of the question.

**How long the pending order lives**, which neither source states: the strictest
reading is best and all three are negative. -0.0192 at one bar, -0.0314 at two,
-0.0640 at three (2,010, 1,917 and 1,976 trades). A longer-lived order is
monotonically worse, which is the opposite of what a breakout thesis predicts.

**The fakey's two "or"s and its bar count**, eight combinations of
`break_ref` x `close_back` x `fake_bars`: the excess spans **-0.0245 to
+0.0318** over 516 to 1,210 trades and the largest |z| is 0.58. The ambiguity
in the source does not matter because none of its readings does.

**`Fold`'s swing reach**, which LTTM leaves open by giving HH/HL with no swing
method: -0.0108 at reach 2, -0.0115 at 3, -0.0097 at 5. Flat to three decimals.

**The graded ordinals, and an arithmetic ceiling worth recording.** `fuzzy`
orders wicks `NONE, SMALL, MEDIUM, LARGE = 0, 1, 2, 3` and `pin`'s default tail
is `WICK_LARGE = 3`, so the tail grid's 1 and 2 admit **2,507 and 2,506**
trades - the same population to one trade - and only 3 separates, at 2,260.
Two of three swept values are one value, which is `finding-bugs`' attainable-
range check: a sweep's empty or identical cells are the ceiling and not the
data. The one graded knob that bites hard is the opposing-wick limit at
`stub = WICK_NONE`, which cuts the population to **478** and reads
**-0.1444 +- 0.0610** against a calendar-shuffled +0.0353 - the most negative
cell in the study, and a demand that the opposing wick be exactly zero.

## Confluence: the displaced level finds more than the real one, on 3 of 4 patterns

The one clause with a number behind it. LTTM's filter page: "a level that has
at least two supporting factors behind it", and the confluence page lists
exactly five factors. Four are codeable and are counted as a **mask, not a
partition** - the trend and the retrace band overlap by construction. The
fifth, "event areas", is **refused**: an event area is a level defined by a
past price-action signal at it, which makes it the same object as the pattern
under test, and measuring it would be the lookahead
[`level-bounce.md`](level-bounce.md) names.

The level factor is measured through `level_shield.book_path` - this repo's own
`Levels`, bar by bar, read as of the previous bar - so it is the detector
[`level-bounce.md`](level-bounce.md) used and not a fifth definition of a
level. And it carries the **distance-matched placebo**: every level displaced
by a random 1.5-3.0 volatility units, rejected if it lands within 0.70 units of
a real one.


| pattern, factors required | real: n | excess | se | z | placebo: n | excess | se | z |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **inside**, >=0 | 10,811 | +0.0014 | 0.0143 | +0.10 | 10,811 | +0.0014 | 0.0143 | +0.10 |
| >=1 | 10,478 | +0.0049 | 0.0145 | +0.33 | 9,994 | +0.0066 | 0.0148 | +0.45 |
| >=2 | 8,032 | +0.0103 | 0.0166 | +0.62 | 5,395 | +0.0286 | 0.0202 | +1.41 |
| **>=3** | 4,064 | **+0.0219** | 0.0240 | +0.91 | 2,207 | **+0.0551** | 0.0311 | **+1.77** |
| **pin**, >=0 | 7,646 | -0.0313 | 0.0163 | -1.93 | 7,646 | -0.0313 | 0.0163 | -1.93 |
| >=1 | 7,048 | -0.0297 | 0.0174 | -1.71 | 5,686 | -0.0160 | 0.0190 | -0.84 |
| >=2 | 4,755 | -0.0113 | 0.0212 | -0.53 | 3,367 | +0.0160 | 0.0249 | +0.64 |
| **>=3** | 2,594 | **-0.0132** | 0.0298 | -0.44 | 1,126 | **+0.1172** | 0.0446 | **+2.63** |
| **fakey**, >=0 | 2,312 | +0.0139 | 0.0296 | +0.47 | 2,312 | +0.0139 | 0.0296 | +0.47 |
| >=2 | 1,487 | +0.0338 | 0.0385 | +0.88 | 1,114 | +0.0345 | 0.0434 | +0.79 |
| **>=3** | 875 | **+0.0385** | 0.0514 | +0.75 | 437 | **+0.1049** | 0.0709 | +1.48 |
| **combo**, >=0 | 1,318 | -0.0753 | 0.0392 | -1.92 | 1,318 | -0.0753 | 0.0392 | -1.92 |
| **>=3** | 392 | **-0.0932** | 0.0716 | -1.30 | 177 | **-0.2100** | 0.0981 | -2.14 |

**On three of the four patterns the displaced level finds more than the real
one**, and the single largest reading in the whole confluence table is the
**placebo** arm of the pin bar at three factors: **+0.1172 +- 0.0446, z +2.63**,
the only cell past |z| 2 either way. `the-placebo-arm-selects-the-null` says
plainly what to do with that - the null is rejected, not the claim confirmed -
and this is a textbook instance rather than a borderline one.

**The mechanism is in the `n` column and it is the factor count selecting on
sample size.** Requiring three factors cuts the real pin-bar population from
7,646 to 2,594 and the placebo's from 7,646 to **1,126**, because a displaced
level is touched less often, so "three factors" on the placebo arm is a
*rarer and more extreme* selection of the same trades. A smaller, more extreme
selection of a trade population drifts, and both arms drift monotonically with
the factor count - the placebo more steeply. "The more confluent factors the
higher-probability it is considered" therefore reproduces on levels that are
not there, which means it is not a statement about levels.

The `>=0` rows are the internal check: with the level factor unable to bind,
the two arms are identical to four decimals on all four patterns, as they must
be.

## The 50% retrace is not the displacement origin, measured rather than assumed

LTTM offers "the 50% retrace of the last major move" as a confluence factor.
[`displacement-origin.md`](displacement-origin.md) defines the displacement
origin as the halfway mark of the **displacing body** and the fade to it is
closed - 0 of 105 cells with a positive lower bound, and the 82% return rate is
a statement about *distance*, matched by a price-matched placebo on every class.
A multi-bar swing midpoint and a one-bar body midpoint are different
constructions, so whether that result transfers is a measurement.

Share of windows where the two prices fall within a tolerance of each other,
14 feeds at 1d, 59,765 windows:

| tolerance | 50% retrace vs the displacing body's midpoint | vs the origin candle's **close** (production's `Origin.line`) | vs a **random prior bar's** body midpoint |
|---|---:|---:|---:|
| 0.10 units | 0.0768 | 0.0538 | **0.0765** |
| 0.25 units | 0.1894 | 0.1325 | **0.1888** |
| 0.50 units | 0.3536 | 0.2645 | **0.3603** |

**They are the same price exactly as often as two arbitrary prices off the same
series are.** The control column matches the claim column to within 0.0006 at
0.25 units and is *higher* at 0.50. So `displacement-origin.md`'s
result does not transfer and is not cited as covering this clause; the 50%
retrace is measured here on its own, as a confluence factor, below.

The third column is worth a line of its own: production's `Origin.line` is
where the origin candle **closed**, not its body's midpoint, and it agrees with
the retrace *less* often than the midpoint does. That is the same
"production's own definition is a different object" that
`displacement-origin.md` records about itself.

## The clock claim, and why only half of it is measurable here

The author's claim, from a reader reply on the LTTM overview rather than from
any article body: *"The lower the timeframe the less effective the signal is
because of noise"*, and a signal taking a day to form "has more weight behind
it". Every strategy page says the same in prose - daily best, 4h and 1h
acceptable, "I personally don't go below the 1 hour chart".

**The cost half is measurable and it is true.** The same rule's round trip is
0.0020R on eurusd at 1d and 0.0416R at 15m, a **21x** multiplier that
reproduces `a-shorter-clock-multiplies-cost-in-r`'s measured 19x from a
different estimator. On the geometry these rules use, that is still inside the
desk's 0.16R ceiling, so the cost does not refuse the fast clocks here - it
just makes them 21x dearer per unit of risk.

**The signal half is not measurable on this store, and that is a data
statement rather than a result.** The price store holds about **5,000 bars per
feed per interval at every interval**, so 1d spans 19-20 years while 15m spans
about seven weeks and 1h about ten months. A comparison across clocks is
therefore also a comparison across spans, regimes and sample sizes, and the
power sweep above says the 1h panel is blind below a plant of 0.80R where the
1d panel sees 0.40R. A claim that the same rule is *weaker* at 15m cannot be
separated from the fact that there are a fifteenth as many years of it.

What can be said is narrower and is said below: **the sign of the excess is not
monotone in the clock on any of the six rules**, the best inside-bar cell is at
1h rather than 1d, and the largest |z| over 24 (rule, clock) cells is 2.42 -
which is what 24 cells give by chance.


Excess at a 2R target, settled at the fill bar's close, with `net` subtracting
the median round trip in R over the feeds that carry recorded quotes at that
clock. 4h is **2 feeds and 44-152 trades** because the store's 4h coverage is
patchy, so nothing rests on that column.

| rule | 1d | 4h | 1h | 15m |
|---|---:|---:|---:|---:|
| **inside**, both sides | -0.0331 | +0.1101 | **+0.1016 (z +2.38)** | +0.0187 |
| net | -0.0355 | +0.0987 | +0.0834 | -0.0562 |
| **inside**, with the trend | +0.0166 | +0.1202 | +0.0474 | +0.0680 |
| net | +0.0142 | +0.1088 | +0.0292 | -0.0069 |
| **pin**, at market | -0.0103 | -0.2679 | +0.0106 | -0.0367 |
| net | -0.0137 | -0.2876 | -0.0177 | -0.1058 |
| **pin**, on stop | -0.0577 | -0.0429 | -0.0194 | -0.0463 |
| net | -0.0611 | -0.0626 | -0.0477 | -0.1154 |
| **fakey** | +0.0048 | +0.2827 | +0.0433 | +0.0458 |
| net | +0.0025 | +0.2719 | +0.0224 | -0.0036 |
| **combo** | -0.0671 | -0.2321 | -0.0393 | +0.0960 |
| net | -0.0695 | -0.2410 | -0.0581 | +0.0459 |
| feeds | 14 | **2** | 14 | 14 |
| cost charged | 0.0023-0.0034R | 0.0089-0.0197R | 0.0182-0.0283R | **0.0494-0.0749R** |

**The claim is not what the data shows, and the data is not strong enough to
contradict it either.** The inside bar's best cell is at **1h** (+0.1016,
z +2.38) and not at 1d; the pin bar's worst is at 4h on 152 trades from two
feeds; the combo's only positive cell is **15m**. The sign is not monotone in
the clock on any of the six rules, and across 24 (rule, clock) cells the
largest |z| is 2.42 - about what 24 cells give by chance. **An ordering that
reverses between neighbouring clocks on four of six rules is noise, not a
gradient.**

**What the net row does show is the cost half, cleanly.** The charge grows
from 0.0023-0.0034R at 1d to 0.0494-0.0749R at 15m, and it is the only thing
in the table that moves monotonically with the clock. It turns three of six
positive 15m gross readings negative - the inside bar's two-sided cell from
+0.0187 to **-0.0562**, the fakey's from +0.0458 to -0.0036 - which is
`a-shorter-clock-multiplies-cost-in-r` acting on readings that are themselves
inside their own noise.

So **"the lower the timeframe the less effective the signal"** comes out as:
the *signal* half is unmeasurable here and the *cost* half is true and sized.
A practitioner would see the same thing a desk sees - fast clocks pay worse -
and would attribute it to noise in the signal where this panel can only
attribute it to the spread.


## Per instrument, because a pooled mean is not the answer

The inside bar entered at the mother bar's extreme, both sides, settled at the
close, at 1d - the cell with the largest sample. `pooled-medians-invert-
subgroups` is the reason this column is not an appendix.

| feed | n | mean R | excess | se | win |
|---|---:|---:|---:|---:|---:|
| audusd | 157 | -0.0446 | -0.0353 | 0.1158 | 0.318 |
| btc | 151 | +0.2318 | +0.0140 | 0.1188 | 0.411 |
| eth | 126 | +0.0476 | -0.1353 | 0.1314 | 0.349 |
| eurusd | 147 | -0.1020 | -0.0505 | 0.1189 | 0.299 |
| gbpusd | 140 | -0.1857 | -0.1290 | 0.1102 | 0.271 |
| gold | 163 | +0.1595 | -0.0069 | 0.1147 | 0.387 |
| nzdusd | 150 | +0.1800 | **+0.2110** | 0.1324 | 0.393 |
| sol | 66 | +0.1364 | -0.0222 | 0.1782 | 0.379 |
| spx500 | 90 | +0.3333 | **+0.3369** | 0.1640 | 0.444 |
| us100 | 95 | +0.0737 | -0.0307 | 0.1491 | 0.358 |
| usdcad | 158 | -0.1076 | -0.1368 | 0.1170 | 0.297 |
| usdchf | 147 | +0.0204 | -0.0077 | 0.1165 | 0.340 |
| usdcnh | 134 | -0.2836 | -0.2383 | 0.1197 | 0.239 |
| usdjpy | 155 | -0.0710 | -0.1160 | 0.1180 | 0.310 |
| **3 of 14 positive** | **1,879** | | **-0.0331** | **0.0336** | |

**The per-feed column is where the mean R column is told apart from the excess
one.** Read as mean R, six of fourteen feeds are positive and gold reads
+0.1595 and btc +0.2318 - which is what a book of these trades would have
looked like. Read as excess over the same mechanics at random bars on the same
instrument, three are positive and gold is -0.0069. **Gold's +0.16 is the entry
mechanic on gold, not the inside bar on gold**, and that is the whole reason
the placebo runs per instrument rather than pooled.

**Per feed the sample is 66 to 163 trades, at or below the ~100-trade floor**,
so no single feed's number is evidence. The two positive outliers are spx500
(+0.3369 on 90 trades) and nzdusd (+0.2110 on 150), each about 1.6 standard
errors, which is what fourteen draws produce.

## Power, before the null: where the test goes blind

A directional drift of known strength is planted on the bars after every
detected setup, ramped so the total displacement over the forward window is
`strength` times that trade's own risk. Every bar keeps its own shape - open,
high, low and close all move by the same amount - so the detector never sees a
different kind of bar. Planting it in **R** is what makes the sweep readable:
the deciding statistic is mean R, so the strength at which the excess stops
clearing its own noise is a blind spot quoted in the same units as the result.

| planted, in R over the window | inside | pin | fakey | combo |
|---|---:|---:|---:|---:|
| 0.00 | -0.0633 (z -1.89) | -0.0272 (z -0.84) | +0.0179 (z +0.43) | -0.0609 (z -1.13) |
| 0.05 | -0.0614 | -0.0222 | +0.0180 | -0.0546 |
| 0.10 | -0.0437 | -0.0093 | +0.0351 | -0.0407 |
| 0.20 | -0.0298 | +0.0071 | +0.0652 (z +1.50) | -0.0036 |
| 0.40 | +0.0250 | +0.0450 (z +1.40) | **+0.1266 (z +2.88)** | +0.0649 (z +1.18) |
| 0.80 | **+0.1534 (z +4.43)** | **+0.1074 (z +3.24)** | **+0.2243 (z +5.09)** | **+0.1762 (z +3.11)** |
| feeds positive at 0.80 | **14 of 14** | 11 of 14 | 13 of 14 | 12 of 14 |

The numbers are the **excess**, so the unplanted row is the study's own result
and the lift is the difference from it.

Three readings:

* **The plant lands and is monotone on 4 of 4 patterns at 1d and 1h**, so the
  detector and the settlement see a directional effect when there is one, and
  the per-feed agreement rises with it - the inside bar goes from 4 of 14 feeds
  positive unplanted to **14 of 14** at 0.80R.
* **About a quarter of the plant arrives.** A 0.80R drift over the window lifts
  the excess by 0.13-0.24R, because most races resolve before the ramp has
  finished delivering. So the strengths below are the plant, and the effect the
  test is actually resolving is roughly a quarter of each one.
* **The test is blind below about 0.20R of plant and reliable from 0.40-0.80R.**
  Pooled over fourteen feeds it reaches |z| > 2 at 0.40 on the fakey and only at
  0.80 on the other three. At 1h, with a twentieth of the span, nothing reaches
  |z| > 2 below 0.80.

So a null here closes an effect of roughly **half an R per trade and larger**,
and says nothing about one of a tenth of an R - which matters, because the cost
at 15m is 0.03-0.14R and an edge the size of the cost is inside the blind spot.

## What is refuted, what is unmeasurable, and what was not re-run

### Not re-run, because it is already measured here

| clause | where | what this study did instead |
|---|---|---|
| how often an inside bar occurs, and against what null | [`inside-bars.md`](inside-bars.md) - rate 0.140-0.168 on traded classes, ordering suppresses it by 0.046-0.072, a third to a half of that the hour-of-day cycle | inherited the **null design**: a generated walk has `order` 0 by construction, so `calendar-shuffle` is a required arm. The rate is not re-measured |
| "at a key chart level": does price bounce at a level | [`level-bounce.md`](level-bounce.md) 168 cells null; [`level-shield.md`](level-shield.md) 1 of 210; [`magnet.md`](../../docs/magnet.md) 44.9% against a placebo's 49.5%; `level-signatures.md` 19 observables within 0.006 of AUC 0.5 over 6,902 touches | the level is a **conditioning factor on the pattern**, with the placebo arm, never re-tested as a claim of its own |
| the trend (HH/HL) as a direction predictor | [`structure.md`](structure.md) nothing beyond `side`; [`bos-predict.md`](bos-predict.md) AUC 0.75 on walks as well as markets | `Fold.trend` reused as a filter, with its reach swept, scored against its own duty-cycle twin |
| the 50% retrace as a fade target | [`displacement-origin.md`](displacement-origin.md) 0 of 105 cells | agreement rate measured instead - and it does **not** transfer, see above |
| a pattern's hit rate against its own geometry | [`patterns.md`](patterns.md) - the double bottom's 58% matched by a placebo at 57.6% | the matched-mechanics placebo is inherited as the deciding arm |
| engulfing bars, sweeps, order blocks, structure shifts | [`smc-conjunctions.md`](smc-conjunctions.md), [`order-block-zones.md`](order-block-zones.md), `sweeps.md` | not tested: none of the four patterns is one of those, and the third source is entirely about them |

### Refused as unspecified rather than reported as null

**The general false break-out.** priceaction.com's `/strategies/false-break-out/`
page gives it no bar count, no close-back requirement and no reference level,
and explicitly admits versions with no pattern in them at all - "More
experienced traders can also trade false breakouts that don't contain a price
action trigger like a pin bar". There is nothing to encode that would not be
this desk inventing a method and then reporting the result under the source's
name. Its one codeable clause - "wait for price to close outside of the range
for two days or more" - is carried as the fakey's `CLOSE_BACK` and `FAKE_BARS`
sweep.

**"Event areas" as a confluence factor.** A level defined by a past
price-action signal at it is the same object as the pattern under test.

## Two limitations of the encoding, stated rather than buried

**The EMA confluence factor is only interpretable at 1d.** LTTM says "I use the
8 and 21 **day** EMAs on the daily charts", so at 1d an 8-bar and a 21-bar EMA
are the thing he names and below 1d they are 2 hours and 5.25 hours - a
different object with the same code. That is the bar-count-in-a-portable-
measurement defect `volatility_ceiling.py` recorded, where comparing
`har (5/22/110)` across 15m and 1d compared 1.25h/5.5h/27h with 5d/22d/110d and
the finding vanished on conversion. The confluence arm is therefore **run at 1d
only**, which is where the source's own number means what it says.

**The horizon is in bars and is deliberately not converted.** 20 bars at 1d, 30
at 4h, 48 at 1h and 15m, which is `level_shield.SETTINGS` unchanged so the two
studies' races are the same object. In duration that is a month at 1d and two
days at 15m, and the clock comparison has to be read knowing it: what is held
fixed across clocks is the *stop and target in units of the trade's own risk*,
not the time the trade is allowed.

## Defects reported

Seven, two of which would have decided the study and two of which read as a
detector declining to fire.

1. **A stop-order entry settled from the next bar wins +0.2234R +- 0.0541 on a
   driftless walk**, because conditional on the stop filling the bar closed past
   the trigger. Fixed by driving the placebo through the same construction, and
   by carrying a second, leak-free settlement. Pinned by
   `test_a_walk_pays_nothing_against_its_own_matched_placebo`.
2. **The swept tail share never reached the detector.** The driver cached the
   pin masks on the encoding name alone, so all four values of the sweep read
   the mask built at 2/3 and the table printed **four identical rows at
   n = 2,256**. The only reason it was visible is that the whole grid is
   printed rather than summarised. Pinned by
   `test_the_tail_sweep_actually_reaches_the_detector`, which requires the
   firing count to fall monotonically and the four counts to be distinct.
3. **The graded pin-bar arm read zero signals on the research box**, because
   `indicators/fuzzy.py` was absent from the synced tree and the guarded import
   left the mask all-False. A silent zero is not a null: it read as
   *the detector declined to fire* on 24 cells. Caught because the census
   prints every arm's setup count whether or not it scores, which is
   `smc-conjunctions.md`'s own correction. Pinned by
   `test_the_graded_pin_fires_and_is_not_the_fixed_one`.
4. **The pin branch looped over every bar rather than over the firing ones.**
   With the placebo running twenty draws a cell that is 156 million iterations
   a job, and the panel produced no output at all after fifteen minutes on
   twenty-six cores. Not a correctness defect, but it is the reason the first
   version of this panel was unrunnable.
5. **Half of two feeds' daily history is printed twice** - `spx500` and
   `us100` at 1d on YAHOO, 2,999 duplicate timestamps each - which halves the
   effective span of every EWMA and every horizon stated in bars. Found by
   reading bars-a-year as a claim about the world: 503 on a daily series.
   Collapsed on load, counted as `dup_share`, and reported for the three
   published panels that read the same series. Its own section is above.
6. **btc's recorded spread is a spot exchange's top-of-book**, 0.0016 bps, and
   a cost of 0.0000R would have gone into the screen as the cheapest instrument
   in the study. Excluded with the reason, not with a fudge.
7. **A string patch no-opped after `ruff format` reflowed the lines it matched
   on**, so a call site kept fourteen arguments where the function had grown a
   fifteenth and **all 56 jobs died with 0 rows in 18 seconds**.
   `assert-every-string-patch` is the recorded form, and the only reason it was
   not mistaken for a null is that a job printing `0 rows` prints it next to a
   `TypeError` - the harness catches a dead job rather than letting the panel
   die, and `a count of zero beside a non-zero P&L is a reporting bug, never a
   null` generalises to this.

## What is not done

* **The target is this desk's, not the sources'.** No source states one, so
  `k x risk` is the construction that cannot contribute a result rather than
  the method's own exit. A rule whose author's exit is unknown has not been
  tested as that author trades it, and nothing here can say otherwise.
* **Discretion.** All three sources are discretionary. "Whether or not you
  should take a particular Fakey depends on not only its formation, but also
  where it forms in the market" is not codeable, and a mechanical encoding is a
  different object from the method. What the measurement can say is that the
  mechanical version has no edge over its own entry mechanics.
* **The 4h panel is thin.** The store's 4h coverage is patchy - two of fourteen
  feeds carry enough bars on their chosen venue to be costed - so the 4h column
  is carried for sign consistency and nothing rests on it.
* **No fill model.** A stop order is filled at its trigger, or at the open when
  the bar gapped past it. `range-break-100.md` measured a bar replay filling a
  jumped stop at -1R where the tick fill averaged -7.8R, so the `at-trigger`
  column is optimistic on gaps by an amount this store cannot size.
* **Weekly bars are untested.** LTTM says inside bars "are best played on daily
  and weekly charts" and the weekly series in this store is 2,100-12,100 bars
  pooled across venues, which is a few hundred per venue - below the floor.
* **The confluence factor count is a mask over four factors, not five**, and
  the fifth was refused rather than measured.

