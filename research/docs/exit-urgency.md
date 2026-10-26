# Exit urgency that rises with progress toward the target

The proposal: rather than waiting for momentum to *reduce* before pulling out,
let readiness to exit grow as price approaches the take-profit, so that close to
the target the first adverse momentum candle is enough to leave.

With entry `E`, stop `S`, target `T`, side `s` and progress
`p = (close - E) * s / ((T - E) * s)` clamped to `[0, 1]`, the trade leaves at
the close of the first adverse bar whose body is at least `theta0 * (1 - p)`
units of its own risk. `theta0 = 0` is carried deliberately: it always exits on
the first adverse bar, so if the sloped members do not beat it then the slope is
decoration and only twitchiness is working.

This refines something already measured to pay -
`fade-to-value-loses-on-the-entry-not-the-target` found 62% of those trades
stopping out within 7 minutes at -10.81 while targets paid +28.16, and recorded
that managed exits pay.

## The result: refuted, with a monotone gradient pointing the other way

5-sigma anomaly-bar entries, 15 feeds at 1h, 905 trades, 2R target, paired
against `hold` on identical trades. Gross of costs.

| rule | mean R | vs hold | t | win % | bars held |
| --- | ---: | ---: | ---: | ---: | ---: |
| **hold** | **+0.1436** | 0 | - | 38.1 | 10.4 |
| trail 1R | +0.1462 | +0.0026 | 0.08 | 43.5 | 3.8 |
| urgency t0=0.0 | +0.1006 | **-0.0430** | -1.23 | 39.2 | 1.8 |
| urgency t0=0.25 | +0.1127 | -0.0310 | -0.94 | 41.7 | 2.7 |
| urgency t0=0.5 | +0.1293 | -0.0144 | -0.52 | 42.8 | 4.8 |
| urgency t0=1.0 | +0.1658 | +0.0222 | 1.62 | 40.4 | 9.1 |
| **random matched** | +0.1462 | +0.0025 | 0.08 | 44.4 | 4.8 |
| shuffled path | -0.0291 | -0.1727 | -2.93 | 37.6 | 9.6 |

**The rule improves monotonically as it fires less**, from -0.0430 at the most
twitchy setting to +0.0222 at the least, and the limit of that trend is `hold`.
The best member holds 9.1 bars against hold's 10.4 and is not significant.

The control settles it: **`random matched` exits at the same 4.8 bars as
`urgency t0=0.5` and beats it by 0.017R.** At matched holding time an arbitrary
exit does better than the rule's timing, which is what
`strategy-rotation-is-not-timeable` demands be checked - every pause rule there
matched random pausing at the same duty cycle.

Win rate rises as the rule fires more (39.2% to 44.4%) while mean R falls. That
is the trap: the rule *feels* better because it wins more often.

The mechanism is the entry. After a 5-sigma bar price **continues** - that is
the edge - so the first adverse candle is noise rather than a turn, and exiting
on it forfeits the continuation. `shuffled path` at -0.1727 confirms the real
post-entry sequence is what the trade is being paid for, not the exit rule.

Costs make this worse, not better: each managed row pays one market exit the
touch rows do not.

## The walk arm found two bugs before real data was touched

`a-martingale-cannot-pay` says any positive expectancy on a walk is a bug. The
sharper form is **optional stopping**: for a martingale and a bounded stopping
time every rule must read 0, so a large negative is a bug exactly as much as a
large positive. Both halves caught something.

* `hold` now wins **33.2%** of 2R races against the required 33.3%. The memory
  records the bug at 0.470 from settling on the fill bar, so settlement starts
  the bar *after* entry and this row is the assertion that it worked.
* `trail 1R` first read **-0.4900R +/- 0.0554**. Cause: the trail moved the
  stop into profit and settlement still returned a fixed -1R, booking every
  trailed exit as a full loss. On real data that would have read as a
  legitimate finding about trailing stops.

On real bars with random entries - a better-matched martingale than the walk,
since it carries the real bar geometry - every rule sits within |t| 1.75 of
hold and `hold` itself reads +0.0022 +/- 0.0183 at a 33.4% win rate.

## Scope, and the obvious next run

This is one entry family at one frame with a fixed 2R target. The intuition may
come from fade-to-value trades, where the measured picture is different: those
stop out early and their targets pay. Pointing the harness at those entries is
a constant change, and it is the run that would make this a general result
rather than a statement about anomaly-bar continuation.

Costs are **not applied**. The cache's spread column is in points, not price,
and `spread-column-is-in-points` records EURUSD reading a 476% round trip from
exactly that conversion, so costing it needs a per-feed tick size this harness
does not carry.
