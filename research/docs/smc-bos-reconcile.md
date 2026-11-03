# Reconciling `smc_bos_c_L50|M15|N20|time` against its specification

**measured 2026-11-03** on the recorded catalogue. Harness:
[`research/ideas/smc_bos_c_catalogue.py`](../ideas/smc_bos_c_catalogue.py). The
rule is [`strategies/structure.py`](../../till_infinity/strategies/structure.py);
the catalogue is written by
[`node/corpus.py`](../../till_infinity/node/corpus.py).

**This does not measure an edge and must not be quoted as one.** Six feeds over
62-86 days give 75 trades at this rule's firing rate, and the per-trade sd is
2.4R, so the standard error on any mean here is 0.20-0.95R. What it settles is
whether the implementation is the rule, what each divergence is worth, and
where the rule's loss comes from.

## Verdict

| question | answer | kind |
|---|---|---|
| does the port match the frozen rule? | **no, in four places.** Three were worth +0.004 to -0.032R a trade and one, the hold clock, was worth **-0.146R on eurusd** | mechanic |
| is the earlier 43-trade reading reproducible? | **the trade counts exactly, the R not at all.** Same 43 trades, same code: **-0.258R** pooled, not -0.040R; eurusd -0.348 not -0.056, gbpusd -0.355 not -0.055, gold **-0.013** not -0.001 | mechanic |
| was gold's R ever readable? | **no. It was a hundredth of its size**, because the catalogue stated a 100-ounce contract to the sizer and Nautilus's `Cfd` carries no multiplier | artefact |
| are the six feeds comparable? | **they were not.** The FX test instrument charged a 2 bp commission - 0.019R a trade - that gold never paid | artefact |
| are the stop fills optimistic, as assumed? | **no, pessimistic, and by much more than a tick correction.** Median overshoot past the stop: **+0.363R spx500, +0.173R us100, +0.081R gold**, -0.017R on FX | artefact |
| what does the corrected rule read? | **-0.533R a trade**, n 75, day-block [-0.830, -0.237] | reading, se 0.196 |
| does the break's side carry anything? | **no, and the sign is wrong.** The reversed twin reads **-0.134R** against the rule's -0.533, better on 5 of 6 instruments | reading |
| does the break itself carry anything? | **no.** Taking the same signals **8 bars late** reads -0.519R against -0.533: a difference of 0.014R | reading |
| does a swing reach **per side** beat the symmetric one? | **null, and on the right side of the line.** The mirror arm extracts a *larger* asymmetric gain than the rule on 5 of 6 instruments and pooled | null |

## The rule as frozen

Causal BOS from a 50-bar swing structure on M15; direction is the break side;
market entry on the first M1 after the M15 close; stop is the wider of one M15
ATR(14) **from the signal close** and 20 spreads **from the fill**; no target;
exit at the close **1,440 M1 bars after the fill - a bar count, not 24 hours**;
one position per instrument, both directions pooled; later variants take **no
fill in 19:00-23:59 UTC**, judged on the fill.

## The data, and the ceiling

| feed | venue | bars (15m) | days | modelled spread |
|---|---|---|---|---|
| eurusd | DERIV | 5,135 | 75.6 | 1.041 bps |
| gbpusd | DERIV | 5,135 | 75.6 | 0.890 bps |
| gold | DERIV | 5,427 | 86.2 | 0.408 bps |
| btc | DERIV | 5,538 | 62.6 | 2.902 bps |
| us100 | **FOREXCOM** | 5,128 | 78.0 | 1.008 bps |
| spx500 | **PEPPERSTONE** | 5,128 | 78.1 | 0.516 bps |

**us100 and spx500 are not the venue the live desk trades.** Their quote
coverage is best at those two venues and the same instrument's recorded spread
runs 0.17 to 3.30 bps across venues, so both rows are statements about that
venue's cost. The eleven other feeds in the store have two or fewer recorded
quotes at any venue and are skipped rather than priced off a guess.

One quote per bar at the bar's own close, so **the entry fills at the signal
bar's close plus half a spread**: there is no M1 here and no close-to-fill
travel. Three consequences, all stated where they bite below.

## The four divergences, each measured alone

Cumulative, so each row's difference from the one above is that correction. All
six feeds, 2026-06 to 2026-08.

| correction | pooled R/trade | n | moved | the instruments it moved |
|---|---|---|---|---|
| as committed | -0.556 | 83 | | |
| **+bars** - 96 M15 bars, not 86,400 s | -0.588 | 83 | **-0.032** | eurusd **-0.146**, gbpusd -0.040, us100 -0.023, btc +0.008 |
| **+anchor** - ATR leg from the signal close | -0.584 | 83 | +0.004 | spx500 +0.024, gold +0.009, rest ~0 |
| **+cut** - no fill 19:00-23:59 UTC | -0.527 | 74 | **+0.057** | eurusd **+0.163**, gold +0.104, gbpusd +0.036, btc/spx500 +0.029 |
| **+tie** - a tie is a swing | -0.533 | 75 | -0.006 | spx500 +0.061 and one extra trade; every other feed 0.000 |

**The hold clock is the one that mattered and it was not a rounding.**
`Intent.hold` is seconds and `Exits._expired` compares elapsed time, so an
86,400-second deadline falling inside a weekend closed the position at the
**first quote after the gap** - the Sunday reopen. Three FX trades had exits at
49.0 and 56.8 hours of clock for that reason. A reopen quote is exactly where a
survivorship confound lives, so this was not only -0.146R on eurusd, it was
-0.146R taken from the most suspect bar on the feed. The clock is now a bar
count (`StructureProfile.hold_signal_bars`, 96) run by `Structure._clock`.

**The anchor cannot be measured here and the +0.004 is not evidence.** The
frozen rule takes the ATR distance from the signal bar's close and the spread
floor from the fill. In this catalogue the modelled quote *is* the bar's close,
so the two anchors differ by half a spread. On a real M1 feed the gap is the
fill's own travel, which is what the correction is for; the test for it is
`test_the_atr_leg_is_measured_from_the_signal_close_and_binds_when_it_is_wider`,
not this table.

**Ties matter only where prices are coarse.** The rule reads
`high[j] == max(window)`, which admits a tie; this port required strictly
beyond. With one live slot per side the last bar of a flat run wins either way,
so the two differ only on exact equality - once in 94 breaks, on the
two-decimal spx500, and never on five-decimal FX. Both readings are kept
(`tie_is_a_swing`) because which is right is a fact about the feed's price
precision.

## Two artefacts in the catalogue, not in the rule

Neither is switchable, so both were measured by running the same code against a
catalogue written before the fix.

| | before | after | moved |
|---|---|---|---|
| eurusd | -0.348 (n 12) | -0.328 (n 12) | +0.020 |
| gbpusd | -0.355 (n 19) | -0.333 (n 19) | +0.022 |
| gold | **-0.013** (n 12) | **-1.309** (n 12) | **-1.296** |

**Gold's R was a hundredth of its size.** `corpus.instrument_for` stated
`info={"trade_contract_size": 100.0}`, which `sizes.spec_of` sizes against, and
Nautilus's `Cfd` takes no `multiplier`, so the engine priced one unit of
quantity at one price unit. A stop-out read **-0.013R instead of -0.85R**, on
the one instrument the standing result says carries half the R. It also
quantised a $25 budget to a 0.02 lot, a 15% rounding error on the risk.
Quantity is now one unit of the underlying and `info` is empty.

**The FX instruments charged a commission nothing measured.**
`TestInstrumentProvider.default_fx_ccy` sets `maker_fee` and `taker_fee` to
0.00002, which is 0.019-0.022R a trade at the `N20` stop - 5.72 USD over 12
eurusd trades, 10.47 over 19 gbpusd. Gold, built with explicit zeros, paid
none, so the three feeds' R were not comparable with each other. Both fields
are now zero.

**The earlier -0.040R pooled does not reproduce.** The trade counts do, exactly
- 43 trades, eurusd 12, gbpusd 19, gold 12, and the firing rate reconciles - so
the signal path is the same code. The R does not: the same 43 trades read
-0.258R pooled and -0.348 / -0.355 / -0.013 per instrument, against
-0.040 and -0.056 / -0.055 / -0.001. The per-instrument *pattern* is the same
(the two FX pairs near-equal, gold near zero) at about 6.3x the magnitude on
FX, which is the shape of an R computed against a risk denominator 6x too
large. Gold's near-zero is explained; the FX factor is not, and the earlier
figures should be treated as superseded rather than reconciled.

## Where the loss comes from: which stop leg binds

The dominant fact in the per-instrument spread, and it is a mechanic rather
than a reading.

| feed | median stop | binding leg | stop in ATRs | stopped | clocked | win |
|---|---|---|---|---|---|---|
| eurusd | 0.0024 | **20 spreads, every trade** | 3-4 | 3 | 5 | 25% |
| gbpusd | 0.0024 | **20 spreads, every trade** | 3-4 | 10 | 8 | 28% |
| gold | 10.09 | 1 ATR | 1 | **11 of 11** | 0 | **0%** |
| spx500 | 13.13 | 1 ATR | 1 | **9 of 9** | 0 | **0%** |

On tight-spread FX, 20 spreads is 24 pips against an M15 ATR of 5-8, so the
floor binds on **every** trade, the cost in R is exactly 1/20 = 0.0500 **by
construction**, and 40-44% of trades reach the clock. On gold and spx500 the
ATR leg binds, the stop is about one M15 bar's range, and holding 96 bars with
a stop that close is near-certain to be stopped - 20 of 20 were, at a 0% win
rate.

So `N20` is not a floor on these two instruments, it is inert, and the pooled
figure averages two rules with stop widths differing 3-4x. The 0.0500R the
earlier run compared against is a tautology on FX and does not describe gold,
spx500 or us100 at all.

## The stop fill runs the opposite way to the assumption

The earlier run's stated worry was that filling a stop off a bar path gives
zero overshoot and is therefore optimistic by at least 0.035R. Measured off the
realised R (a stop filled at the stop is -1R, so anything past that is the gap):

| feed | median overshoot past the stop |
|---|---|
| spx500 | **+0.363R** |
| us100 | +0.173R |
| gold | +0.081R |
| eurusd / gbpusd | -0.017R |

The catalogue's only quotes are one per 15m bar, so a stop **cannot** fill at
the stop when price jumps over it between closes; the fill is the next bar's
close. The fills here are pessimistic by four to ten times what a tick
correction would charge, on the three instruments where the ATR leg binds.
Debiting a further 0.035R would double-count, so `--overshoot` exists and was
not used in the headline figure.

## The nulls

Same bars, same detector, same stop geometry, same spread paid.

| arm | pooled | n | per instrument |
|---|---|---|---|
| **rule** | **-0.533** +/-0.196 | 75 | btc -0.207, eurusd -0.311, gbpusd -0.336, gold -1.196, spx500 -1.475, us100 -0.126 |
| **flip** - every break's side reversed | **-0.134** +/-0.275 | 72 | btc -0.348, eurusd **+0.116**, gbpusd -0.146, gold -0.740, spx500 +0.004, us100 **+0.453** |
| **late** - the same signals 8 bars stale | **-0.519** +/-0.212 | 74 | btc -0.152, eurusd +0.029, gbpusd -0.333, gold -2.025, spx500 -0.573, us100 -0.233 |

The reversed twin beats the rule pooled and on 5 of 6 instruments. On 75 trades
the difference (0.40R, se about 0.34) is not significant and must not be read as
an anti-edge - but the **sign is the wrong way round**, and three of the
mirror's six instruments read positive. A reversed-side rule earning positive R
says the reading is the stop-against-a-clock geometry and not the side.

The late arm is the stronger statement: holding the clock, the stop, the
instrument and the firing times fixed and letting the break go **eight bars
stale** changes the result by 0.014R. Whatever this rule selects, it is not
"the bar that broke the swing".

## Does a reach per side help? No, and the mirror says why

`indicators/trend.pivots` and `strategies/structure.Fold` now take
`reach_up`/`reach_down`, zero meaning the shared `reach`, and zero on both is
asserted bit-identical to the version without them. 3x3 grid over
`reach in {25, 50, 100}`: three symmetric cells, six asymmetric.

**Pre-registered null, written before the run:** a per-side reach is two free
parameters where there was one, so the best of six asymmetric cells beats the
best of three symmetric ones by construction. The arm that decides it is the
**mirror** - the same grid with every break's side reversed, which has no
genuine side asymmetry in it. If up and down legs really want different
windows, the real grid gains more than the mirror.

| asymmetric gain (best asym - best sym) | rule | mirror |
|---|---|---|
| POOLED | **-0.285** | -0.144 |
| btc | +0.158 | +0.630 |
| eurusd | +0.111 | +0.514 |
| gbpusd | +0.031 | +0.117 |
| gold | -0.984 | -1.008 |
| spx500 | -0.253 | +0.283 |
| us100 | +0.102 | +0.692 |

**The mirror gains more than the rule pooled and on 5 of 6 instruments.** The
asymmetric gain is the max of six noisy cells and nothing else.

**Where the test goes blind, measured rather than assumed.** The mirror's own
gains run +0.117 to +0.692R with no asymmetry present, so this grid
manufactures per-side gains of that size out of noise: it is blind to anything
below about **0.7R a trade**, which is larger than the entire standing claim
for the rule. The capability is built and tested; the question is open and this
catalogue cannot answer it.

**A larger confound in the same table.** The reading is driven by `reach`, not
by the side: pooled, reach 25 reads +0.034 on 134 trades, reach 50 reads -0.533
on 75, reach 100 reads +0.218 on 33. The mirror shows the same U (+0.232,
-0.134, +0.411), so it is not direction - but `L50` is itself a free parameter
nobody measured, n falls 4x across the sweep, and 50 is the worst of the three
on both arms. Any future reading of this rule has to carry the reach as a
choice rather than as part of the name.

## What the harness caught on the way

- **An internally aggregated bar type back-fills a session gap.** A 48.5-hour
  hole in the minute stream becomes 194 empty M15 bars - 120 become 314 - so a
  bar-count hold silently behaves like a seconds hold and anything measuring a
  session effect on a composite bar type is measuring a feed with no sessions
  in it. The catalogue writes **external** bars, where a gap is an absence;
  `test_an_internally_aggregated_bar_type_back_fills_a_session_gap` pins it.
- **`Position.realized_pnl` is read net of nothing**, so the FX commission was
  charged to the account and invisible in `Closed.reward`. Fixed by removing
  the fee, not by changing the read.
- **A top-1% share of total R is unreadable when the total is negative** - it
  came out at -103%. Reported as the mean with the best trade removed instead:
  pooled -0.670 against -0.533, and us100's single +9.56R trade carries its
  whole reading (-0.126 with it, -1.007 without).
- **The store's `ts` is probably the bar's open**, not its close: the last
  Friday bar is stamped 20:40 against a 20:55 session end, and the first Sunday
  bar 21:10 against a ~21:05 reopen. `corpus._bar` passes it through as
  `ts_event`, which Nautilus reads as the close, so every bar may be labelled
  15 minutes early. Bars and quotes shift together, so only the UTC hour cut is
  affected, and a cut trade within 15 minutes of 19:00 or 00:00 is the
  uncertain case. Not changed, because the evidence is circumstantial and
  changing it would move every timestamped result at once.

## What would settle any of it

Not more cells on this catalogue. The reading needs about 230 trades for the
standing +0.31R to be two sigma and this gives 75. The two things worth doing
with what is here are both mechanics: cost the rule per instrument with the
binding stop leg stated, and decide `reach` on its own before any per-side
question is asked again.
