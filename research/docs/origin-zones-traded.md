# The origin zone as a rule: two nominators, one zone, and the trade that is left

**Built 2026-11-10.** Code: [`strategies/origins.py`](../../till_infinity/strategies/origins.py),
[`strategies/crossing.py`](../../till_infinity/strategies/crossing.py).
Tests: `tests/test_origin_zones.py`, `tests/test_zone_rules.py`.

**No measurement here.** This file records what was built, what the existing
measurements already say about it, and the one question that is still open. It
is the counterpart to [`zone-rules.md`](zone-rules.md), which stated the zone
rule as the desk gave it before any numbers were taken.

## The zone is one object with four names

[`delivering.md`](delivering.md) puts them in a table: a ZigZag pivot, a FOCuS
change point, a perceptually important point, a change in state of delivery, an
**order block origin** and this desk's `Level` are all "the last price at which
the market changed its mind". `indicators/levels.Origin` says the same in one
line — an order block, a displacement origin and a supply/demand zone are the
same candle under three names.

**That is one hypothesis with several detectors, not several hypotheses.** So
the scoring now lives in one place, `crossing.side_of`, and
`strategies/zones.py` (Bjorgum key levels) and `strategies/origins.py` read
their crossings through it. A reading taken by one rule is therefore comparable
with a reading taken by another, which it was not when each rule carried its
own copy of the four modes.

## The two rules differ in the nominator and nowhere else

| rule | a candle counts when |
| --- | --- |
| `displacement-zones` | an impulsive chain left from it — `PUSH_MIN` candles each with a body `PUSH_BODY` of its range, stepping over at most `CHAIN_GAP` ordinary candles |
| `smc-zones` | the same, **and** structure broke in that direction, read from `structure.Fold` |

`Fold` is the causal structure detector `smc-bos-causal` already trades, reused
rather than restated: a second derivation of "the trend is up" would make these
results incomparable with that rule's, and
[`smc-conjunctions.md`](smc-conjunctions.md) is a study whose whole finding was
that two named primitives can be one event. A range engulf already takes out
the prior bar's high, so Candle Range Theory is satisfied on **0.706** of
engulfing bars by construction. Two rules whose zones are the same object and
whose nominators are the same test would be that again, and running both side
by side is how it would be found.

A trend of 0 — neither direction established yet — is a **refusal** and not a
pass. The claim both SLK and EMS make is that the higher-level bias is what
makes the conjunction worth taking, so "no bias yet" cannot be allowed to read
as "bias satisfied".

## What the existing measurements already settled

**The fade to this zone is dead, and it is the trade this rule is not.**

- [`displacement-origin.md`](displacement-origin.md): the 82% return rate is a
  statement about **distance**. A price-matched placebo the same distance away
  is reached just as often, on every class.
- CLAUDE.md's Kills section: fade-to-value as a displacement thesis had **0 of
  105 cells** with a positive lower bound across four entry rules, five stop
  pads and four body thresholds; as a filter on origins it read +0.120R on 477
  trades at 1d, +0.017R on 985 at 4h and **−0.007R on 2,786 at 1h** — shrinking
  as the sample grew and reversing on the largest.
- [`order-block-zones.md`](order-block-zones.md): "an 82% return rate and a
  losing read" on the same object at 4h and 1d.
- Killed by the stop: **89–91%** of fades were stopped before the target
  arrived. Price does return 77–81% of the time, but that is measured with no
  stop and 300 bars, and the trade has a stop and sixty.

## So what is actually open

`zones.py` names it, and it has not been asked of origins: **whether a zone's
own geometry — its width, its side, the leg that left it — places a better stop
than a flat volatility distance.** `stop-anchor.md` asked exactly that of
clusters and answered no.

What is traded here is therefore a **crossing**, not a fade: price leaving the
zone (`reject`, reversal) or closing through it from outside (`break`,
continuation). Both ship, because they are exact opposites and a rule offering
one would be asserting the sign of the family. There is **no target** — a
target invented here would be the dead fade with better arithmetic, which is
what `a-martingale-cannot-pay` is about.

`retest` and `flip` are **refused rather than approximated**. They need a zone
that remembers having been broken; `Origin` does not carry that. A `flipped`
field defaulting to False would make `retest` return zero on every bar — a rule
that validates, runs, and reports a cell nothing computed, which is the defect
`zones.py` has on record from the version where `retest` and `flip` silently
ran as `break`. Inventing a second derivation of "broken" would be worse: the
`retest` cell from this rule would no longer be comparable with the one `zones`
reports under the same name.

## Both are registered and neither is enabled

Neither name appears in any `TRADING_STRATEGIES` or in `Settings.strategies`. A
test asserts that, because the measurement that would license trading these
crossings does not exist. Registering them is what makes
`TRADING_STRATEGIES=displacement-zones` runnable at all — `desks.build` refuses
an unregistered name — which is the footing `vol-impulse` was registered on and
for the same reason.

`OriginProfile.interval` is **4h**, the clock the origin population was measured
on in `displacement-origin.md` and `order-block-zones.md`. A desk fanned out
over several clocks reports the one it trades through `Desk.interval`, and
`Desk._say_clock` says so out loud when it differs from the measured one.

## What would license enabling either

A sweep over `reject` and `break`, both nominators, against the three nulls this
desk's method requires:

1. **The same detector on a walk**, same bar geometry, both sides, reach swept.
   `null-structure-claims-on-the-same-detector` is why.
2. **A distance-matched placebo zone** — an ordinary prior extreme at a similar
   distance with no displacement behind it. Without it this measures mean
   reversion and reports it as structure, which is the failure
   `the-placebo-arm-selects-the-null` catches.
3. **The duty-cycle control**, `TRADING_ORIGIN_DUTY`, keeping the same share at
   random. On a net-negative book any rule that trades less shows a profit
   improvement, so the headline carries no information without it. Every pause
   rule ever proposed here beat its baseline and none beat its own random twin.

And power first: plant the effect, sweep its strength, say where the test goes
blind. `show-power-before-reporting-a-null`.
