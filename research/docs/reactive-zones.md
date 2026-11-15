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

## What this does not settle

* **Costs.** Gross by instruction. `a-shorter-clock-multiplies-cost-in-r` puts
  the same spread at 19x the cost in R at 15m against 1d, so the cost question
  is answered per clock and after a side exists to pay for it.
* **Exits.** The horizon is fixed at 16 bars. Break-even and trailing are not
  modelled, and the exit stack is separately measured at about **0.2R a trade**
  on these instruments, which is larger than anything above.
* **The hold-versus-sweep split**, which is the one result worth its own run.
* **Barrier outcomes.** Deliberately: see the fill artefact above.
