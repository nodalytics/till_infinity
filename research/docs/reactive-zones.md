# The sequence rule, multi-timeframe, measured gross on two years

**Measured 2026-11-15.** Five instruments, 2024-11-12 to 2026-11-12, the
broker's own 5-minute bars folded to 4h / 1h / 15m. Everything below is
**before costs**, which is the right way round for a first pass: a rule with no
edge gross cannot have one net.

The rule, as specified by the operator:

> Bjorgum nominates levels. Price comes to a **fresh** one and bounces - or
> wicks through it without closing beyond, which is a liquidity grab. Wait for
> a pull-back, then a pin bar, hammer, shooting star or rejection pattern.
> Enter. Volatility should be low. The frames should agree.

Run as `uv run python research/ideas/reactive_zones.py --years 2`.

## A decoding defect, found first

Gold read **+2.92 units a trade** at the bounce stage against −0.15 to −0.85
everywhere else, with its two best trades at **+204** and **+129** units. A
number that size is a defect before it is an edge, and it was: the loader read
Nautilus's **128-bit** fixed-point price as two `int64`s and kept the low word.
That is correct only below `2**63 / 1e16 = 922.3`. EURUSD, GBPUSD and AUDUSD
are under one and USDJPY is about 150, so four of five instruments were fine
and gold at 1,313 wrapped to **-531.28**.

**`research/ideas/confluence_figures.py` had the same loader**, so every gold
row in the multi-structural confluence spec was computed on negative prices and
is withdrawn pending a re-run. The other four instruments there are unaffected.

Fixed in both: the low word is read unsigned and the high word carries its
`2**64`.

## The sequence, stage by stage

Each stage is its own entry at that bar's close, scored as the move over the
next 16 execution bars in ATR of the execution frame. Not a stop-and-target
race: `dual-thrust.md` measured an OHLC trigger fill at **+0.03 to +0.06 units
a trade on a direction-free series**, so a close-to-close score removes the one
artefact that reliably manufactures an edge.

| stage | n | pooled | EURUSD | GBPUSD | GOLD | USDJPY | AUDUSD |
|---|---:|---:|---:|---:|---:|---:|---:|
| bounce | 771 | **-0.311** ± 0.161 | -0.148 | -0.852 | +0.402 | -0.559 | -0.310 |
| pull-back | 396 | **-0.112** ± 0.207 | | | | | |
| pattern | 271 | **-0.144** ± 0.206 | +0.051 | -0.619 | +0.897 | -0.901 | -0.706 |

Standard errors are block-bootstrapped over **whole days**, because trades
cluster in days and the frames' states persist for hours.

**Every pooled stage is negative, and four of five instruments are negative at
every stage.** Waiting for the pattern does not rescue it: -0.311 at the
bounce, -0.144 after the full sequence, which is inside one standard error of
both zero and of each other.

## What armed it matters more than anything that followed

| pattern entry armed by | n | gross |
|---|---:|---:|
| the level **held** - traded in, closed back out | 64 | **+0.335** ± 0.268 |
| the level was **swept** - wick beyond, close back inside | 207 | **-0.292** ± 0.245 |

Pooled, those are -0.144 and the disagreement is invisible. This is
`pooled-medians-invert-subgroups` on a two-way split, and
`two detectors with the same name are usually two detectors` - except these two
do not even share a name. The liquidity-grab shape is the one `v6` carries as
its CRT trigger, and here it is the **negative** half.

At 1.25 standard errors the hold is not established. It is the one thing in
this run worth a dedicated harness with its own discovery/confirmation split.

## The TSI filter fails its control, and its sign is not stable

Bjorgum's TSI at the slow speed (25/13), on the structure frame, agreeing with
the trade's side. Each filtered arm is reported against a **twin that drops the
same share of signals at random**, seeded per cell - the control `finding-edges`
makes mandatory, because on a net-negative book any rule that trades less shows
an improvement.

| pull-back depth | TSI arm | n | gross | twin | edge over twin |
|---|---|---:|---:|---:|---:|
| 0.25 | tsi slow | 42 | +0.185 | -0.107 | **+0.292** |
| 0.33 | tsi slow | 24 | -0.798 | +0.151 | **-0.949** |
| 0.50 | tsi slow | 24 | -0.643 | +0.152 | **-0.795** |

**The filter's edge over its own twin changes sign with a parameter it has
nothing to do with.** Its standard errors are 0.5 to 0.8 on means of ±0.2 to
0.8 at n 24 to 42. The honest reading is not "the TSI is bad": it is that at
this sample size the filter is **unmeasurable**, and a sign that moves with the
pull-back depth is what noise looks like when it is sliced.

So it is not gated on. It can be published as a feature on every decision and
scored when there is a record; that ordering - publish, measure, then gate - is
the standing one here and every refuted gate on this desk was built before it
was scored.

## Volatility does not fall into the setup. It rises.

The premise was that the sequence forms in quiet conditions. Measured, as the
execution ATR over the instrument's own trailing 200-bar median, so 1.00 is
normal for that instrument at that time:

| where | mean | median |
|---|---:|---:|
| 6 bars before the trigger | 1.00 | 0.96 |
| at the trigger | **1.10** | 1.03 |
| 3 bars after the trigger | **1.13** | 1.03 |
| the 3 bars before entry | **1.12** | 1.02 |

**Volatility is ~10-13% above normal at the trigger and stays there into the
entry.** On reflection that is what it should be: it takes a move to reach a
level, and a sweep is a move by definition. The setup is a disturbance, not a
lull.

And it does not separate the outcome. Winners against losers at each point:
1.01/0.99 before, 1.12/1.07 at the trigger, 1.14/1.11 after, 1.13/1.11 into
the entry - differences of 0.02 to 0.05 on a spread of about 0.5.

## Low volatility is not a filter either

"Volatility is currently low" as the execution ATR in the lower 40th percentile
of its own trailing 200 bars - a quantile rather than a level, because gold's
ATR triples over this window and a fixed threshold would read as a filter on
the calendar.

| arm | n | share | gross | twin | edge over twin |
|---|---:|---:|---:|---:|---:|
| quiet, depth 0.25 | 106 | 39.1% | -0.141 | -0.241 | +0.100 |
| quiet, depth 0.33 | 67 | 37.2% | -0.770 | -0.218 | -0.553 |
| quiet, depth 0.50 | 72 | 37.9% | -0.309 | -0.028 | -0.281 |

Same shape as the TSI: positive against its twin at one depth, negative at the
other two, every one of them inside its own error.

## Multi-timeframe confluence has no sample

The ladder, each rung adding one frame's agreement, on the pattern entry at
depth 0.25:

| rung | n | share of entries |
|---|---:|---:|
| pattern | 271 | 100% |
| + quiet | 106 | 39.1% |
| + TSI slow | 17 | 6.3% |
| + TSI both frames | 1 | 0.4% |
| + a rejection candle on the middle frame | **0** | 0% |

**Three frames agreeing happens once in two years across five instruments, and
four conditions agreeing happens never.** That is the same wall the
multi-structural confluence blueprint hit, measured again on a different rule:
a conjunction of independent-ish gates multiplies its way out of existence long
before it runs out of edge. The `+ TSI both` cell reads **+3.15** on its single
trade, which is what a slice to n=1 always produces and is reported here only
so that nobody quotes it.

## The microscope: 271 pattern entries, every cut

A pooled mean hides its parts, so every cut that could invert it:

| cut | bucket | n | gross |
|---|---|---:|---:|
| instrument | EURUSD | 49 | **+0.708** ± 0.374 |
| | GOLD | 50 | +0.153 ± 0.472 |
| | USDJPY | 58 | -0.402 ± 0.438 |
| | GBPUSD | 42 | -0.505 ± 0.458 |
| | AUDUSD | 72 | -0.511 ± 0.424 |
| what armed it | the level held | 64 | **+0.335** ± 0.268 |
| | the level was swept | 207 | **-0.292** ± 0.245 |
| side | long / short | 126 / 145 | -0.132 / -0.154 |
| pattern shape | engulf | 195 | -0.095 ± 0.238 |
| | rejection (pin, hammer, star) | 76 | -0.271 ± 0.428 |
| session, UTC | 04-07h | 35 | +0.601 ± 0.550 |
| | 08-11h | 44 | -0.876 ± 0.560 |
| **bars waited** | 0-3 | 34 | **-0.855** ± 0.573 |
| | 4-11 | 180 | -0.195 ± 0.258 |
| | 12+ | 57 | **+0.442** ± 0.357 |
| pull-back depth | shallow < 0.4 | 213 | -0.229 ± 0.241 |
| | 0.4 - 0.7 | 52 | +0.335 ± 0.391 |
| | deep > 0.7 | 6 | thin |
| ATR at entry | low < 0.9 | 64 | +0.167 ± 0.491 |
| | mid 0.9 - 1.2 | 129 | -0.384 ± 0.282 |
| | high > 1.2 | 78 | -0.002 ± 0.340 |

**Side and role are the same cut.** Long is support and short is resistance by
construction, and they read -0.132 and -0.154: no asymmetry worth a word.

**The rejection family is the worse half.** The operator's rule names pin bar,
hammer and shooting star; those are -0.271 against the engulf's -0.095, on
fewer than half the entries.

**Three things look like structure, and two of them are one thing.**

1. *What armed it* - a level that held reads +0.335 and a level that was swept
   reads -0.292, and pooled they are -0.144.
2. *Bars waited* is **monotone**: -0.855, -0.195, +0.442. A monotone cut is
   harder to produce by chance than a single cell, which is why
   `sweep-thresholds-on-the-mean` asks for the grid rather than the best point.
3. *Pull-back depth* has its middle bucket at +0.335 - and waiting longer is
   how a pull-back gets deeper, so (2) and (3) are very likely the same
   observation counted twice.

**None of it survives being counted.** Nine cuts of three to six buckets on 271
trades is about 35 cells; Benjamini-Hochberg over that many would leave
nothing, and the best cell - EURUSD at +0.708, 1.9 standard errors - is exactly
what picking the best of five instruments produces. On this desk 18 of 43
instruments were once nominally profitable where chance gives 22, and not one
survived BH.

The honest statement is that the wait-time gradient and the hold-versus-sweep
split are the two **hypotheses worth a dedicated run**, with their own
discovery/confirmation split and their own nulls, and that nothing here is a
result yet.

## The adaptive band is a better instrument, and it reads zero

Replacing the preset's `ATR(30) * 0.015` with the **25th percentile of the
structure frame's own trailing ranges** - a width chosen by quantile rather
than by a constant - takes the sample from 271 pattern entries to **963**, and
with it the pooled reading to:

    +0.0045 +/- 0.1376

That is zero, measured with enough n to say so rather than enough to shrug.
Every stage agrees: +0.032 at the bounce (n 1,227), +0.055 at the pull-back,
+0.004 at the pattern.

**And it exposes the hold-versus-sweep split as a property of the band.** At
the narrow fixed band, 207 of 271 entries were "sweeps"; at the adaptive band,
**10 of 963**. A wick only goes beyond a band that is narrow enough to be
jumped, so the trigger classification was measuring the width, not the market.
The +0.335 against -0.292 from the fixed run should be read as a statement
about 0.015 ATR, not about liquidity grabs.

## Four differentiators, and one of them confirms

Asked of 963 entries: what about a level, other than volatility, separates one
that pays from one that does not?

| cut | bucket | n | gross |
|---|---|---:|---:|
| **how hard price arrived**, ATR travelled over the 12 bars before the trigger | **drift < 1** | 328 | **+0.456** ± 0.182 |
| | 1 - 2 | 255 | -0.306 ± 0.257 |
| | hard 2+ | 380 | -0.177 ± 0.233 |
| distance to a round number | on it < 0.1 ATR | 118 | **-0.420** ± 0.317 |
| | 0.1 - 0.4 | 298 | +0.191 ± 0.222 |
| | away 0.4+ | 547 | -0.006 ± 0.196 |
| level age, structure bars | new < 5 | 478 | +0.144 ± 0.167 |
| | 5 - 20 | 275 | -0.194 ± 0.307 |
| | old 20+ | 210 | -0.052 ± 0.282 |
| where it perches in the range | low / middle / high | 317/216/430 | +0.087 / -0.145 / +0.019 |

**Approach speed is not volatility.** ATR rises into every one of these setups;
*displacement* into the level is a different quantity, and a market can be loud
and go nowhere. What this says is that a level reached by **drifting** pays and
a level reached by a **thrust** does not.

### The confirmation split, which killed the previous two candidates

Split at the median trading day, five cuts:

| cut | first half | second half |
|---|---:|---:|
| **arrived on a drift** | **+0.308** ± 0.266 (n 159) | **+0.596** ± 0.249 (n 169) |
| arrived hard 2+ | -0.236 ± 0.245 | -0.110 ± 0.448 |
| **on a round number** | **-0.363** ± 0.298 | **-0.465** ± 0.498 |
| fresh level < 5 | +0.323 ± 0.232 | **-0.061** ± 0.258 |
| waited 12+ bars | -0.003 ± 0.245 | **-0.200** ± 0.400 |
| armed by a hold | -0.011 ± 0.152 | +0.046 ± 0.221 |

**The drift arm is positive in both halves and stronger in the second**, with
its complement negative in both. Round numbers are negative in both halves -
which is a watchedness reading with the **opposite sign to the naive prior**:
`magnet.md` closed attraction, and this says the prices everybody computes are
where this rule does worst.

The two candidates from the fixed-band run - the hold trigger and the wait-time
gradient - do not confirm. That is what the split is for.

### It is not a cost problem

The catalogue's own median spread, in ATR of the execution frame:

| | EURUSD | GBPUSD | GOLD | USDJPY | AUDUSD |
|---|---:|---:|---:|---:|---:|
| spread / ATR(15m) | 0.032 | 0.040 | 0.011 | 0.029 | 0.041 |

A round trip is **2 to 9 percent** of the drift arm's +0.456. Whatever is wrong
with this family, the spread is not it - which is unusual here and worth saying
plainly.

### The three arms, and what each one moved

The approach effect, swept on the mean, against a **placebo level** - the same
distance the other way, with no pivot behind it - and a **day-block shuffle** -
the same bars with their days reordered and re-based, so every wick, range and
ATR is exactly as the market made it and only the relationship between a level
drawn earlier and price arriving later is destroyed.

| drift threshold, ATR over 12 bars | real | placebo | day-shuffled |
|---|---:|---:|---:|
| < 0.50 | **+0.764** (n 168) | +0.303 (162) | **-0.114** (142) |
| < 0.75 | **+0.519** (249) | +0.311 (232) | -0.072 (230) |
| < 1.00 | **+0.456** (328) | +0.209 (300) | +0.066 (305) |
| < 1.50 | +0.242 (458) | +0.080 (455) | +0.082 (451) |
| < 2.00 | +0.123 (583) | +0.083 (573) | +0.177 (575) |

**The real arm is monotone in the threshold.** +0.764, +0.519, +0.456, +0.242,
+0.123: the tighter the drift, the larger the reading, with no ridge at any
particular value. That is the grid `sweep-thresholds-on-the-mean` asks for, and
it is the shape a z-grid fakes and a mean-grid does not.

**The shuffle is flat to negative where the real arm is strongest.** At the
0.50 threshold the real arm reads +0.764 and the shuffled arm **-0.114**. So
this is *not* the mechanical statistics of selecting quiet windows: that
selection is applied identically to both, and only the shuffled series has had
the level relationship removed. The difference, +0.878, is what the level is
worth here.

**The placebo takes about 40% of it.** +0.303 against +0.764 at the tightest
threshold, +0.209 against +0.456 at 1.00. A price the same distance away with
no pivot behind it collects a real share of the effect - so part of what is
being measured is the geometry of approaching *any* price slowly - and the
pivot roughly doubles what the geometry alone gives.

Per instrument, at the tightest threshold, **all five are positive**:

| | AUDUSD | EURUSD | GBPUSD | GOLD | USDJPY |
|---|---:|---:|---:|---:|---:|
| < 0.50 | +0.109 (39) | +0.898 (44) | +0.458 (22) | +0.619 (33) | +1.803 (30) |
| < 1.00 | -0.101 (80) | +0.820 (77) | -0.205 (44) | +0.544 (68) | +1.129 (59) |

Five of five positive at 0.50 and three of five at 1.00, on 22 to 44 trades
each. USDJPY carries more than its share at both.

**This is the first thing in this study that survived its own nulls.** It is
also still one measure, chosen after looking, on 168 trades at the threshold
where it is strongest, with the confirmation split run at the 1.00 threshold
(+0.308 then +0.596) rather than at 0.50.

### What would actually establish it

Everything above is still one cut of about forty-five, and the split was run
*after* the cut was chosen. The standing method asks for more than that:

1. **Pre-register the drift threshold and sweep it on the mean**, not on a z -
   `sweep-thresholds-on-the-mean` records a z grid faking a ridge at the chosen
   threshold where the mean grid was monotone. Here the buckets are not
   monotone (drift +0.46, middle -0.31, hard -0.18), which is the first thing
   to explain.
2. **Null it against the same detector on a walk**, with the same bar geometry
   and the same approach measure. A slow arrival is a low-displacement window,
   and low-displacement windows have their own forward statistics on any
   series.
3. **A placebo level** at the same distance with no pivot behind it, which is
   what separates "this level" from "this approach".
4. **Per instrument**, which 328 trades over five instruments cannot yet carry.

## The synthetics, and what they actually control for

**Not participants - news.** The operator's correction: people trade the Deriv
synthetics with the same tools and draw the same levels, so these feeds are not
a control for watchedness. What they have is **no scheduled releases and no
fundamentals**, which makes them the control for whether a structure needs news
to exist.

Six years of hourly bars, the same three-frame shape one step slower - 1d
structure, 4h middle, 1h execution - and the same three arms. 24 bars to the
day, because these feeds never close.

| drift threshold | | < 0.50 | < 0.75 | < 1.00 | < 1.50 | < 2.00 |
|---|---|---:|---:|---:|---:|---:|
| **Volatility 75** | real | **+0.670** (22) | **+0.531** (28) | **+0.622** (33) | +0.284 (48) | +0.233 (61) |
| | placebo | - | +0.219 (21) | **-0.175** (23) | -0.474 (40) | -0.628 (56) |
| **Step** | real | - | +0.289 (21) | +0.169 (26) | -0.270 (37) | +0.071 (49) |
| **Boom 1000** | real | - | **-0.363** (21) | **-0.589** (29) | **-0.609** (38) | -0.351 (47) |
| | placebo | - | - | +0.614 (22) | +0.295 (30) | +0.156 (44) |
| pooled | real | +0.155 (46) | +0.190 (70) | +0.089 (88) | -0.158 (123) | +0.007 (157) |
| | shuffled | -0.090 (47) | +0.006 (69) | +0.035 (100) | +0.026 (151) | -0.045 (196) |

**Volatility 75 replicates the majors.** +0.62 at the 1.00 threshold against
+0.46 pooled on the real markets, positive at every threshold, with its own
**placebo negative** at the same thresholds and its shuffle flat. On a feed
with no news at all. Whatever the approach effect is, it does not need a
calendar.

**Boom 1000 inverts it**, -0.36 to -0.61, with its placebo *positive*. That is
the generator showing through rather than a contradiction: Boom spikes upward
rarely and drifts down in between, so a slow approach to a level is the drift
phase and what follows it is more drift, not a reversal. `CLAUDE.md` already
records Boom/Crash spikes as flat across every bucket; this is the same
asymmetry seen from the entry side.

**Step Index says nothing, which is the expected answer.** Its step size is
constant by construction, so "price travelled less than 1 ATR" barely varies
and the selection is close to a no-op. A strong reading there would have been
the thing to worry about.

Per-cell n is 21 to 61. These are three feeds, not a sample.

## The family check, which is where it falls over

Volatility 75 was one feed. Run its own family - the same generator at another
volatility parameter, and the same generator ticking once a second - and only
one member shows anything:

| real arm | < 0.75 | < 1.00 | < 1.50 | < 2.00 |
|---|---:|---:|---:|---:|
| Volatility 75 | **+0.582** (28) | **+0.518** (33) | +0.558 (43) | +0.169 (70) |
| Volatility 75 (1s) | **-0.683** (25) | **-0.375** (31) | -0.483 (49) | -0.260 (60) |
| Volatility 100 | +0.028 (26) | -0.145 (33) | -0.174 (49) | -0.213 (60) |
| Volatility 100 (1s) | -0.419 (26) | -0.282 (31) | -0.082 (50) | -0.018 (68) |
| Crash 1000 | - | -0.211 (20) | -0.381 (31) | +0.015 (38) |
| **pooled** | **-0.069** (122) | **-0.083** (148) | -0.109 (222) | -0.058 (296) |

**The same generator at a different parameter fails. The same generator
ticking faster fails with the opposite sign.** That is what a cell picked out
of many looks like when the family is asked.

Crash 1000 reads negative like Boom 1000 rather than mirroring it, which does
*not* support the drift-phase story told above for Boom - on Crash the drift
phase is upward and the mirror would have been positive. Both are negative, so
whatever they share is not the direction of the spike.

Step Index is noise (+0.29, +0.17, -0.27, +0.07) and Step 200 produces fewer
than twenty entries per bucket on its 2.5 years of hourly data. Step 300, 400
and 500 are held no finer than 4h locally, and 97 weekly structure bars cannot
carry a 20-bar pivot window plus a 200-bar adaptive band, so the detector
finds nothing at all there. That is a data limit, not a result.

### "Account for the extra volatility" - measured

The proposal was that the faster feeds need a wider threshold: if Volatility 75
reads at 0.5, take Volatility 75 (1s) at 1.0 or 1.5. It is the right question
and it has an answer in the data:

| feed | median bar range / price | x V75 | ATR / price |
|---|---:|---:|---:|
| Volatility 75 | 0.01190 | 1.00 | 0.01259 |
| Volatility 75 (1s) | 0.01197 | **1.01** | 0.01258 |
| Volatility 100 | 0.01589 | 1.33 | 0.01684 |
| Volatility 100 (1s) | 0.01597 | 1.34 | 0.01677 |
| Crash 1000 | 0.00281 | 0.24 | 0.00313 |

**The 1s variant carries the same price action per hourly bar as the standard
one - 1.01x, not 2x.** The "1s" names the tick generation rate; the hourly
bar's realised range is unchanged by it. So between those two there is nothing
extra to account for, and they still disagree in sign at the same threshold.
Volatility 100 does carry 1.33x, and shifting its thresholds by that still
leaves it flat.

The threshold is already in ATR units, which is why: it was scale-free before
the rescaling was proposed.

### The denominator is not the cause

`gross` divides by the ATR of the entry bar, and the drift arm selects quiet
windows - so a smaller denominator could have manufactured the whole effect.
The same move over a **fixed** unit, the instrument's trailing median ATR,
which this selection cannot move:

| threshold | over the entry bar's ATR | over a fixed unit |
|---|---:|---:|
| < 0.50 | +0.764 | +0.800 |
| < 0.75 | +0.519 | +0.534 |
| < 1.00 | +0.456 | +0.456 |
| < 1.50 | +0.242 | +0.226 |
| < 2.00 | +0.123 | +0.094 |

Identical to two decimal places where it matters. One mechanical cause ruled
out; the effect is in the price, not in the unit.

### Where that leaves it

On the five real markets the approach effect has a monotone sweep, a flat
shuffle, a placebo worth about 40% of it, a confirmation split that holds, a
denominator that is not the cause, and a spread that is 2 to 9% of its size.
On the synthetic family it is one feed in five.

Both can be true: the real-market result is pooled over five instruments and
the synthetic result is five separate cells of 20 to 70 trades each, which is
not enough to refute it and not enough to support it. What it does mean is
that **Volatility 75 matching EURUSD was a coincidence of two cells**, and the
honest next step is the one the real-market section already names - a
pre-registered threshold, per instrument, with enough trades to carry it -
rather than another family.

## The held-out test, registered before it was run

**This section was written and committed while the run was still going.** The
git history carries the ordering, which is the only thing that makes a
pre-registration worth anything.

Everything above was found on **2024-11-12 to 2026-11-12**. The deep catalogue
holds bars back to 2018, so there are **six years the detector has never
touched**. The parameters are fixed at what the discovery window used, with no
tuning of any kind:

| | |
|---|---|
| window | 2018-11 to 2024-11, the two recent years held out |
| frames | 4h structure, 1h middle, 15m execution |
| band | 25th percentile of the structure frame's trailing ranges |
| pull-back | 0.25 of the move away from the level |
| horizon | 16 execution bars |
| **threshold** | **1.00 ATR** - a round number, and the one the earlier confirmation split was run at, chosen *not* to be the strongest cell (0.50 was) |
| arms | real, and the day-block shuffle |

**What the discovery window said**, at that threshold: pooled **+0.456**, and
per instrument EURUSD +0.820, USDJPY +1.129, GOLD +0.544, AUDUSD -0.101,
GBPUSD -0.205 - three of five positive.

**The predictions:**

1. The pooled held-out mean at 1.00 is **positive**. If the effect is real this
   is the minimum it must do.
2. The shuffle arm is **not** positive. If both move together the effect is in
   the selection, not the level.
3. **More than three of five instruments are positive.** Three of five in
   discovery is what chance gives on a coin, so a repeat of exactly three is
   not evidence; the claim is that the method travels rather than that those
   three instruments do.
4. The sweep stays **monotone** - tighter drift, larger reading.

Anything else - a positive pooled mean carried by one instrument, or a sweep
that peaks in the middle - is a failure to confirm, and will be written here as
one.

### The result: it does not confirm

**2,675 entries over the six held-out years, against 963 in discovery.** Three
of the four predictions fail, and the fourth passes only trivially.

| threshold | real, pooled | shuffled, pooled |
|---|---:|---:|
| < 0.50 | **-0.405** (476) | -0.108 (447) |
| < 0.75 | **-0.220** (719) | -0.039 (697) |
| < 1.00 | **-0.115** (958) | -0.042 (867) |
| < 1.50 | -0.210 (1,366) | -0.037 (1,269) |
| < 2.00 | -0.197 (1,711) | +0.017 (1,601) |

| prediction | outcome |
|---|---|
| 1. pooled mean at 1.00 is positive | **-0.115. Failed.** |
| 2. the shuffle is not positive | -0.042. Passes, but both arms are negative, so it carries no information |
| 3. more than three of five instruments positive | **two of five - GOLD +0.045, USDJPY +0.137. Failed.** |
| 4. the sweep stays monotone | **-0.405, -0.220, -0.115, -0.210, -0.197. Failed,** and the tightest threshold is now the *worst* where it was the best |

Per instrument at 1.00, held out against discovery:

| | held out | discovery |
|---|---:|---:|
| EURUSD | **-0.680** (177) | +0.820 (77) |
| USDJPY | +0.137 (217) | +1.129 (59) |
| GOLD | +0.045 (190) | +0.544 (68) |
| GBPUSD | -0.051 (189) | -0.205 (44) |
| AUDUSD | -0.102 (185) | -0.101 (80) |

**EURUSD, which carried the discovery result at +0.820, reads -0.680 on three
times the sample.** The sign of the sweep inverts: in discovery the tighter the
drift the better, out of sample the tighter the drift the worse.

### So the approach effect is closed

It had a monotone sweep, a flat shuffle, a placebo worth 40%, a confirmation
split that held, a denominator that was not the cause, and a spread at 2 to 9%
of its size. Every one of those was computed on the window it was found in.
Given six years it had never seen, it reversed.

That is the whole lesson of the section above it, arriving on schedule: **nine
cuts of three to six buckets on 271 trades is about thirty-five cells**, and
the best of them was EURUSD. The split that "held" was a split of the same
discovery window, which is why `finding-edges` asks for a fixed date and
untouched data rather than two halves of what you already looked at.

The synthetic family said the same thing a different way an hour earlier, and
was right.

## ATR's shape is stable and its level is not

Measured on the five majors, 15m ATR(30) over price, by year. Reusable past
this study, which is why it is here rather than in the run log.

| | 2019 | 2020 | 2022 | 2024 | 2026 |
|---|---:|---:|---:|---:|---:|
| EURUSD median | 4.13bp | 6.03 | 8.38 | 4.49 | 4.64 |
| GOLD median | 8.65bp | 15.00 | 12.26 | 11.64 | **20.36** |
| USDJPY median | 4.50bp | 5.05 | 8.03 | 7.18 | 5.34 |
| **p75 / p25**, any instrument, any year | **1.42 - 1.94** | | | | |

**The level swings by a factor of two and the dispersion does not move at
all.** Within any year, for any of these instruments, the 75th percentile of
ATR is 1.4 to 1.9 times the 25th - 2019 and 2022 and 2026 all look the same in
that ratio, while the median between them doubles.

The vivid version: **gold's quietest decile of 2026, at 15.65bp, is louder
than its loudest decile of 2019, at 15.19bp.** A threshold set in 2019 gold
would, in 2026, admit everything.

Two consequences, and they are why the adaptive band is not a preference:

1. **A threshold in ATR units is comparable across years; a threshold in price
   units is not.** That much was already assumed here. What is new is the
   second half:
2. **A quantile of trailing ATR is comparable and a multiple of its mean is
   less so.** Because the shape holds, the 25th percentile means the same
   thing about a market in every year measured - which is exactly the property
   a fixed multiple of a 30-bar mean does not have, since that mean inherits
   whichever few bars made it.

This is also why the regime shift does *not* explain the held-out reversal
above. The measure was ATR-normalised and the trailing window adapts inside
two days at 15m; the fixed-denominator arm read the same numbers. The reversal
is noise, not a regime.

## ATR across frames, and the thing that looks like trending

The same measurement on 15m, 1h, 4h and 1d. Growth is against the 15m median;
a random walk gives the square root of the bar ratio.

| | 15m | 1h | 4h | 1d | H |
|---|---:|---:|---:|---:|---:|
| EURUSD, ATR/price | 5.34bp | 11.19 | 23.43 | 62.77 | 0.533 - 0.540 |
| GOLD | 11.94bp | 24.73 | 52.27 | 139.49 | 0.525 - 0.539 |
| USDJPY | 5.95bp | 12.45 | 26.25 | 71.68 | 0.532 - 0.545 |
| a random walk would give | | 2.00x | 4.00x | 9.80x | 0.500 |

Daily ATR is **11.4 to 12.0 times** the 15m where a walk gives 9.80, and `H`
lands at **0.523 to 0.545** on every instrument and every frame pair. That
reads as trending. It is not.

**Close-to-close volatility scales at exactly a half.** The standard deviation
of log returns on the same bars gives `H` of **0.482 to 0.502**, a random walk
to three decimals, with a gap to the range measure of +0.034 to +0.055 that is
identical across instruments.

**The gap is the return distribution changing shape, not the market trending.**

| | kurtosis 15m -> 1d | mean\|r\|/sd 15m -> 1d |
|---|---|---|
| EURUSD | 29.1 -> 5.2 | 0.637 -> 0.747 |
| GOLD | 55.8 -> 8.7 | 0.612 -> 0.698 |
| USDJPY | **105.1** -> 8.9 | 0.606 -> 0.695 |

Gaussian is 0.798. Intraday returns are violently fat-tailed and daily ones
much less so, so a **mean-absolute** dispersion grows faster under aggregation
than a **second-moment** one. ATR is the first kind and the standard deviation
is the second, and they diverge by exactly as much as the shape moves: the
measured shape change implies an extra exponent of **0.029 to 0.035** against
an observed gap of **0.041 to 0.055**. About seventy percent of the gap is
aggregational Gaussianity; the remainder is plausibly the range estimator,
since a 15m bar's high-low misses more of its own path than a daily bar's does.

Neither reading is trending. Both are a random walk whose steps are fat-tailed
at short horizons - which is `how-markets-differ-from-every-simple-process`
measured from the other side.

### ATR is twice the mean close-to-close move, everywhere

| | 15m | 1h | 4h | 1d |
|---|---:|---:|---:|---:|
| mean \|close-to-close\| / ATR, EURUSD | 0.504 | 0.488 | 0.486 | 0.487 |
| GOLD | 0.493 | 0.486 | 0.491 | 0.510 |
| USDJPY | 0.501 | 0.490 | 0.487 | 0.504 |
| wick share of the range | ~0.50 | ~0.51 | ~0.51 | ~0.50 |

**0.486 to 0.510 in every cell**, and the body is the same share, so half of
every bar's range is wick on every frame of every instrument measured.

The practical consequence is that **ATR and a close-based scale are
interchangeable as normalisers up to a factor of two**. Every threshold in
this document would be halved and nothing else would move. What is *not*
interchangeable is using one to scale the other across frames, which is where
the 0.04 of exponent above comes from.

### A cumulative mean cannot follow a regime

The third normaliser: an **expanding** mean of true range, against the rolling
ATR(30), by year.

| ATR30 / cumulative mean | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| EURUSD | 0.80 | 1.14 | 0.86 | 1.36 | 0.91 | 0.73 | 1.02 | 0.80 |
| GOLD | 1.11 | 1.62 | 1.01 | 1.07 | 0.96 | 1.34 | 2.04 | **2.82** |

**It works where volatility oscillates and fails where volatility trends.**
EURUSD's ATR swings around a level, so an expanding mean stays within about
thirty percent of the rolling one for eight years. Gold's has risen and kept
rising, so by 2026 the rolling ATR is **2.82 times** the cumulative mean and
anything normalised that way reads nearly three times too large.

That is not a tuning problem. An expanding mean weights every bar it has ever
seen equally, so its lag behind a persistent shift grows without bound - by
construction, and worst exactly when the market has changed most.

So, of the three:

| normaliser | across years | across frames | in a trending regime |
|---|---|---|---|
| rolling ATR(30) | fine, adapts in ~2 days at 15m | mind the 0.04 of exponent above | fine |
| trailing quantile of range | fine, and the shape is stable so a percentile means one thing | same caveat | fine |
| cumulative mean | **no** | no | **wrong by 2.8x on gold** |

## The retail lens: where do the stops rest?

Every course teaches the same stop: **just beyond the swing**. If that is what
most people do, the distance past a level where stops rest is predictable, and
excursions beyond a level should *end* there more often than anywhere else.

There is no DOM here and `real_volume` is zero, so positioning cannot be seen
directly. What can be seen is where excursions terminate. Measured as a
**hazard** - the chance an excursion that got this far turns here - rather than
as a histogram, because the raw distribution falls away for the trivial reason
that fewer excursions travel further.

Eight years, five instruments, 15m execution against 4h levels:

| beyond the level, in ATR | real | day-shuffled |
|---|---:|---:|
| 0.00 - 0.25 | 7.1% | 7.3% |
| 0.25 - 0.50 | 13.3% | 12.8% |
| **0.50 - 0.75** | **13.9%** | **13.5%** |
| 0.75 - 1.00 | 12.8% | 13.3% |
| 1.00 - 1.25 | 12.3% | 11.8% |
| 1.25 - 1.50 | 11.1% | 10.9% |
| 1.50 - 1.75 | 10.3% | 10.1% |
| 1.75 - 2.00 | 9.4% | 9.1% |
| 2.00 - 2.25 | 8.2% | 8.6% |
| 2.50 - 2.75 | 7.5% | 7.0% |
| 3.00 - 3.25 | 6.1% | 6.3% |
| 3.75 - 4.00 | 5.3% | 5.3% |
| **excursions** | **73,871** | 76,187 |
| **came back at all** | **96.3%** | 96.5% |

**No bump anywhere.** The hazard rises to about 14% at half an ATR beyond the
level and decays monotonically after it, and the shuffled series - where the
level is a price nothing was drawn at - does the same thing to within half a
percentage point, with no systematic sign across sixteen buckets of 17,000 to
74,000 observations each.

So the shape is what a walk does on crossing a boundary, and **the level
contributes nothing to where an excursion ends**. The same goes for the 96.3%
that come back, which `a-return-rate-is-geometry` already recorded from the
other side: the shuffled arm returns 96.5%.

**What this does and does not close.** It is a measurement about *these*
levels - Bjorgum pivots on a 4h frame with a quantile band. Retail does not
draw those. It draws the raw swing high and low, the previous day's extremes,
the round number, the session open. If stops cluster, they cluster beyond
*those*, and the one such proxy already in this harness - distance to a round
number - is the single cut that was negative in both halves of the discovery
window, at -0.363 and -0.465. That is where the retail lens has something and
it is the next thing to measure, not this.

## Does a quantile of ATR give regimes?

Yes, at a **daily** horizon and not below it. Terciles of where ATR(30) sits in
its own trailing 200 bars, and the chance of still being in the loud tercile
`h` bars later:

| | base rate | h = 1 | h = 16 (4h) | **h = 96 (1 day)** | median dwell |
|---|---:|---:|---:|---:|---:|
| EURUSD, real | 0.323 | 0.961 | 0.583 | **0.553** | 23 bars |
| EURUSD, day-shuffled | 0.345 | 0.970 | 0.679 | **0.388** | 28 |
| GOLD, real | 0.323 | 0.957 | 0.581 | **0.482** | 18 |
| GOLD, day-shuffled | 0.354 | 0.978 | 0.777 | **0.306** | 29 |

**At h = 1 the 0.96 is mechanical** - ATR(30) shares twenty-nine of its thirty
bars with itself - and the shuffle matches it. **At four hours the shuffle is
*more* persistent than the real series**, because shuffling whole days leaves
each day internally intact, so a loud day stays loud for its own 96 bars.
Only at a full day does the real series separate: 0.55 and 0.48 against a
shuffle that has fallen to 0.39 and 0.31, over a base rate of 0.32.

So the state is real and the horizon to act on it is **a day**, not a bar.

### The clustering, against what is mechanical

Autocorrelation of log ATR, real against the day shuffle:

| lag | 1 | 16 (4h) | 96 (1d) | 480 (5d) |
|---|---:|---:|---:|---:|
| real, across five majors | 0.998 - 1.000 | 0.851 - 0.969 | **0.798 - 0.943** | **0.679 - 0.876** |
| day-shuffled | 0.998 - 0.999 | 0.798 - 0.915 | 0.204 - 0.310 | **-0.030 - +0.119** |

**Volatility clustering runs at least five days** and the shuffle prices the
mechanical part of it exactly: identical at lag 1, close at four hours, and
gone by a day. There is no ambiguity in this one - it is the largest
real-against-control gap measured anywhere in this document.

### PCA, and the correlation that was not there

On the five majors, log ATR: **PC1 is 57.5%** and loads EURUSD +0.56, GBPUSD
+0.51, AUDUSD +0.53, USDJPY +0.38 and **GOLD +0.01**. It is a *currency*
volatility factor with gold sitting out; PC2 at 23.6% is gold against the
dollar bloc. Interpretable loadings are what separate this from "PCA always
returns a PC1".

Then the three key instruments - one major, one metal, one synthetic - on a
common hourly clock, 43,248 aligned changes:

| correlation of **changes** in log ATR | EURUSD | GOLD | V75 |
|---|---:|---:|---:|
| EURUSD | 1.000 | **+0.512** | +0.006 |
| GOLD | +0.512 | 1.000 | +0.005 |
| V75 | +0.006 | +0.005 | 1.000 |

PC1 at 50.4% is EURUSD -0.71, GOLD -0.71, V75 -0.01 - a real-market
volatility factor - and PC2 at 33.3% is V75 +1.00, entirely its own axis.

**This is the news thesis, measured.** EURUSD and gold share sessions and
releases and their volatilities move together at +0.51. Volatility 75 has no
news and sits at **zero** against both. That is also what makes it a usable
control rather than a correlated echo.

### And the spurious correlation it nearly became

The same three instruments, correlated on **levels** instead of changes:

| levels | EURUSD | GOLD | V75 |
|---|---:|---:|---:|
| GOLD | +0.255 | 1.000 | **-0.612** |

**-0.612 against a true +0.005.** Gold's ATR/price has risen from 8.65bp to
20.36bp over this window while V75's is engineered near-constant, and two
series trending oppositely correlate strongly without co-moving at all. Read
off the levels it is a finding - synthetic volatility rises when gold's falls -
and it is nothing. `difference-before-aligning` is the rule that catches it,
and the differences here are taken in each series' own order with any step
that is not a true one-hour gap dropped, so a session break cannot become a
fake change.

### Orthogonal is an argument for trading it, not against

To be explicit, because the previous section reads as if it demoted
Volatility 75 to a measuring instrument: **it is traded here**, and the
operator's position on 2026-11-15 is that it stays traded. It went onto the
live desk on 2026-11-14 alongside Boom 1000.

Nothing measured above argues otherwise, and the orthogonality argues *for* it:

* **Independence is a portfolio property.** A return stream whose risk moves
  with nothing else in the book is worth more per unit of it than one that
  moves with everything, which is the whole of why the correlation was worth
  measuring. `swap-does-not-cancel-in-a-long-short-basket` is the standing
  caution about what independence does *not* buy, and it is about carry rather
  than about risk.
* **A control and a traded instrument are not exclusive.** What makes V75 a
  control is what it isolates - no news - not an absence of structure. The
  same feed can answer "does this rule need a calendar" and carry a position.
* **It never closes.** On a Saturday or a Sunday it and the Boom/Crash family
  are the only things on the account that quote at all, which is a real
  property of the book rather than a statistical one.

What the measurements *do* say is narrower: the sequence rule read +0.52 to
+0.62 on V75 at tight drift thresholds and **its own family did not replicate
it** - Volatility 75 (1s), Volatility 100 and Volatility 100 (1s) are flat to
negative at the same thresholds. That is a verdict on the rule, not on the
instrument. No rule measured in this document has an edge on V75; no
measurement here says one cannot.

## Six kinds of level, ordered by how many people compute the price

The retail lens asked where stops rest and the hazard said nowhere, on
Bjorgum pivots. But retail does not draw Bjorgum pivots. So: the same
measurement on six level kinds, band width held identical across all of them
so the comparison is about *which price* and never about how wide a zone is.

| kind | who computes it | excursions | came back | hazard at 0.50 ATR, real / shuffled |
|---|---|---:|---:|---|
| `bjorgum` | whoever runs that script | 34,199 | 96.4% | 14.2 / 13.4 |
| `swing` | the obvious line on any chart | 32,247 | 96.2% | 13.8 / 13.6 |
| `prior_day` | the platform draws it | 37,995 | 96.5% | 14.2 / 13.3 |
| `round` | everyone who looks | 2,881 | **70.7%** | 10.4 / 8.8 |
| `bollinger` | every default chart | 76,190 | **100%** | 21.9 / 21.4 |
| `twap` | every default chart | 104,190 | **100%** | 18.4 / 18.4 |

**The three static levels are their own shuffles, within 0.9 points of
hazard at every distance.** That spans the entire ladder from a price almost
nobody computes to one the platform draws unbidden, which is the comparison
`a-magnet-is-a-shared-reference` proposes - and it does not separate.

### The two readings that are not what they look like

**`round` returns 70.7% where every other static kind returns 96%**, and that
is geometry rather than a property of round numbers. A pivot and a prior-day
extreme sit near recent price by construction; a round-number grid has members
everywhere, including far above and below, and an excursion past a distant one
simply keeps going. `a-return-rate-is-geometry` is the same finding from the
other side, and it is why the 96% figure should never have been read as "price
comes back to levels".

**`bollinger` and `twap` return 100% of the time by construction.** Their
boundary follows price, so it is always re-crossed - these are not levels in
the sense the other four are, and their higher hazards (18-24% against 8-14%)
say only that price re-crosses its own moving average constantly. Bollinger's
real-against-shuffled gap of +1.4 and +1.5 at the far distances, on 76,190
excursions, is the one number here that would repay a second look - but the
quantity is "how far price gets from its own mean", which is the trailing
z-score family, and `trailing-zscores-fake-reversion` records a shuffled twin
taking +0.111 of a +0.137 effect there. One shuffle draw cannot separate
those; several would be needed, and that is the follow-up rather than a
finding.

### So the levels study closes

Across this document a level has now been asked six questions - does trading
it pay, does an excursion past it end anywhere special, does it matter who
computes it, does it matter how the approach looked, does a pattern at it
help, do the frames agree - and the answer to each is no, with the control
matching the real arm every time. Taken with `magnet.md` on attraction,
`level-shield.md` on blocking and `gap-levels.md` on grading, the geometry of
levels is measured out on this data.

What is **not** closed is what a level *is for*: `levels.py` and the zones
rule use them to nominate prices, and nominating is not predicting. A rule
that uses a level to decide *where* to act, having decided *whether* on other
grounds, is untouched by any of this.

## What this does not settle

* **Costs.** Gross by instruction. `a-shorter-clock-multiplies-cost-in-r` puts
  the same spread at 19x the cost in R at 15m against 1d, so the cost question
  is answered per clock and after a side exists to pay for it.
* **Exits.** The horizon is fixed at 16 bars. Break-even and trailing are not
  modelled, and the exit stack is separately measured at about **0.2R a trade**
  on these instruments, which is larger than anything above.
* **The hold-versus-sweep split**, which is the one result worth its own run.
* **Barrier outcomes.** Deliberately: see the fill artefact above.
