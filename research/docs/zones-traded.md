# Bjorgum key levels as a trading rule: the geometry columns are coin flips

**Measured 2026-11-03.** Harness:
[`research/ideas/zone_asymmetry.py`](../ideas/zone_asymmetry.py), rule
[`till_infinity/strategies/zones.py`](../../till_infinity/strategies/zones.py).

[bjorgum.md](bjorgum.md) measured the indicator's features and says in its own
words that nothing there is in production. This is the first time the zones
have been **traded**, through the production engine with the real entry, exit
and sizing path.

| column, paired on the same cell | payoff better | PnL better |
|---|---|---|
| `high_low` vs `ha` | **95/192 (49.5%)** | 96/192 |
| `high_low_body` vs `ha` | **80/160 (50.0%)** | 86/160 |
| `high_low_body` vs `high_low` | 86/160 (53.8%) | 94/160 |
| zone-width tilt 2.0 vs 1.0 | 156/272 (57.4%) | 148/272 |
| stop tilt 2.0 vs 1.0 | 162/272 (59.6%) | **108/272 (39.7%)** |
| `measured` vs `script` preset | 99/272 (36.4%) | 88/272 |

**The pivot source does nothing and neither asymmetry does anything.** Every
instrument is negative in aggregate. The one consistent column - the preset -
is confounded with trade count and is not separable here.

## The grid

576 cells: four styles x two presets x three pivot sources x two zone-width
tilts x two stop tilts x six instruments. **544 traded, 32 placed nothing, 0
refused.** 150 of 544 clear their own break-even payoff and 151 have positive
PnL.

Four styles, because a key level offers two reversal readings and two
continuation ones and nothing here had pinned the sign:

| style | reading | cells | median payoff | median needed | clear | sum PnL |
|---|---|---|---|---|---|---|
| `break` | the zone failed — continuation | 136 | 4.65 | 6.75 | 28 | -83,153 |
| `flip` | the bar its role changes — continuation | 136 | 2.71 | 3.00 | 48 | -2,347 |
| `reject` | the zone held — reversal | 136 | 1.33 | 1.71 | 28 | -50,685 |
| `retest` | broken, revisited, leaving again | 136 | 2.13 | 2.50 | 46 | -20,600 |

The figure read against is the **payoff ratio against its own break-even**:
at a win rate `w` a rule winning a minority of its trades needs
`(1 - w) / w`. Every style's median payoff sits below its median requirement.

## The columns, read properly

A column is only reportable **paired** - the same cell with one knob moved -
because the styles differ enormously in trade count and a pooled median would
read the mix rather than the knob.

**The pivot source is null.** 49.5% and 50.0% against Heikin-Ashi is as close
to a coin as this desk measures, so the High/Low against High/Low-Body question
has the same answer here that it has elsewhere.

**Both asymmetries are noise, and the stop tilt shows how to tell.** It reads
59.6% better on payoff and **39.7% better on PnL** - a column that improves one
while worsening the other on the same cells is not an effect. The zone-width
tilt is 57.4% / 54.4%, inside what a coin gives on 272 pairs.

**The preset is the one consistent column and it is confounded.** `script`
beats `measured` on 64% of pairs, with clear counts 99 against 51 and aggregate
-6,242 against -150,542. But `script` trades **half as much** - median 88
positions against 165 - which is the duty-cycle confound named in the
`finding-edges` skill: on a net-negative book any rule that trades less shows a
profit improvement. The payoff ratio is per-trade and so less exposed, but the
effect is not separable from trade count without a twin that trades less at
random at the same rate, and that twin was not run. **Unresolved, not a
finding.**

## Per instrument, and why the best cells are not a result

| instrument | cells | median payoff | clear | sum PnL |
|---|---|---|---|---|
| GOLD.DERIV | 96 | 2.48 | 44 | -5,272 |
| BTC.DERIV | 96 | 1.97 | 29 | -14,573 |
| US100.FOREXCOM | 64 | 2.28 | 23 | -17,536 |
| GBP/USD.DERIV | 96 | 2.03 | 23 | -29,159 |
| SPX500.PEPPERSTONE | 96 | 2.82 | 21 | -32,266 |
| EUR/USD.DERIV | 96 | 2.28 | 10 | -57,979 |

The ten widest payoff margins are **all BTC**, `retest` and `flip` on the
`script` preset, at payoffs of 14.9 to 19.8 against requirements of 2.1 to 3.4.
That is best-of-576 on one instrument, and **BTC's own aggregate is -14,573**,
so the winners are specific cells rather than a property of the feed.
`discovery.gate_from` exists to refuse exactly this reading.

576 cells at a 5% threshold gives 29 positive cells from chance alone.

## Two defects in the rule, both silent

**Two of four styles were accepted, validated, and ran as a third.** `MODES`
declared `reject`, `break`, `retest` and `flip`, and `_side` branched on
`reject` then let everything else fall through to the `break` arm - so
`retest` and `flip` passed validation, ran, and reported cells under their own
names for a rule that was `break`. Every mode is now dispatched by name and an
unhandled one raises. The check that was missing is that all four behave
differently on the same feed, which they now do.

**The exit was declared and never read.** `on_opposite` existed on the config
and nothing consulted it, so with no target and no hold clock the only exit was
the stop and the win rate was **0.00 by construction** on all 15 positions of
the first `break` run. `bands.py` had the identical defect. An opposing signal
now closes through `ExitMechanism._close`, the one latched path.

Both are the same shape as the six other defects found the same day: a
configuration that is accepted, runs, and reports numbers for something that
never happened.

## What this cannot settle

`node/corpus.py` holds about 76 days of 15-minute bars for six feeds with
modelled quotes at the measured median spread per feed and venue. Cells run 74
to 122 positions on the better styles, which is near the ~100 where a per-trade
mean stops being noise and not past it. PnL is in the catalogue's own instrument
conventions rather than the broker's, so **signs and counts are interpretable
and totals are not**.

The entry side of levels is already closed here - [magnet.md](magnet.md)
measured a level reached 44.9% of the time against **49.5% for an arbitrary
price the same distance away** - so a positive cell in this grid is a candidate
for a measurement rather than a finding.

## What is worth doing next

The duty-cycle twin for the preset column, which is the only question this run
leaves genuinely open. Everything else in the grid is a coin flip and does not
need more cells.
