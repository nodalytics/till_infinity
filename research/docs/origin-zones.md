# Origin zones: the level a violent move left from, traded on its first return - no edge

Code: [`research/ideas/zones.py`](../ideas/zones.py). Run on the lab, 2026-10-02, on the broker's
bars and spreads (MT5 CFDs: FX, metals, indices, energy, crypto) and Deriv's synthetics, 1h / 4h /
1d, 2020 on (1h), 2018 on (4h), 2002 on (1d). Trades are capped at 5 days, the desk's 3-5 day hold.

## The idea, as the desk drew it

A level that launched an aggressive move - the move broke structure and left an imbalance on the
way - is where the market defends again. On the first return price may bounce at once, stall, or
grind; a reaction there is traded to the nearest opposite zone of the same kind. 1h to 1d, aligned
with the 4h ("the mother cycle"). Plots were checked with the desk before the run, and the rules
were tightened after its review: a stricter leg, a strong break, strong candles.

| Part | Rule |
|---|---|
| origin | a swing low (3/3) whose up-leg, within 10 bars, closes above the last known swing high, travels 3+ ATR without trading below it, and leaves a fair-value gap of 0.2+ ATR |
| strong break | the 3 bars after the break close beyond it and price reaches 1 ATR past it within 5 bars; the zone is live only once that is known |
| zone | the origin bar from its low to its body top (0.2-1.5 ATR) |
| strong candles (filter) | the leg's bodies average 60%+ of their ranges, 70%+ of its bars point the move's way, one body of 1+ ATR |
| return | the first bar back in the zone; a 12-bar window for the reaction; the zone fails on a close 0.1 ATR through it |
| triggers | touch (a resting limit, no confirmation), pin bar, engulfing, morning/evening star, inside-bar break, reclaim (the stall or grind resolved), CISD; then sweep, double bottom, inverse FVG, CHoCH, RSI divergence, displacement, tweezer, outside bar, volume climax |
| lower-timeframe confirmation | a 4h or 1d zone confirmed by a CISD or CHoCH on the 1h, 30m or 15m (a 1h zone on the 30m or 15m), entered on that timeframe's next open; stop under the reaction's low, or past the zone |
| stop | 0.1 ATR past the zone or the lowest low since the return (also 0.3, 0.5 and 1 ATR, after a wick stopped a trade the desk liked) |
| exits | the opposite zone's near edge (the idea's own target), 4R, 10R, a 2-ATR trail |
| filters | 4h bias (the last 4h break of structure points the trade's way), nested in a live 4h zone (1h), strong candles; SMC: discount/premium of the 4h dealing range, inducement swept on the way in, London/New York killzones, all of them; the desk's NAS100 example (a zone 50+ bars old reached by a 3-ATR fall in 5 bars) |
| nulls | the coin twin (same fills, random side) and random-time trades (same side and geometry in ATR at a random bar); day-bootstrap p, Benjamini-Hochberg over every cell |

## How the zones are built

Four zone definitions went through the same harness. All are in [`zones.py`](../ideas/zones.py)
except the DAX checklist ([`dax_smc.py`](../ideas/dax_smc.py)). Every rule is written for a long;
a short is the same rule on the flipped chart (prices negated, highs and lows swapped), so both
sides are always traded. ATR is Wilder's 14-bar. Nothing is used before the bar it is known on.

### 1. Research origin zones (the desk's idea) - `long_zones`, `strong_leg`

The plots in `zones_*.png` and the `gallery/` folder. Built from the desk's description, then
tightened after its first review of the plots.

1. **Origin.** A swing low: lower than the 3 bars before it and no higher than the 3 after
   (`prims.pivots`, known 3 bars later).
2. **Break of structure.** Within 10 bars of the origin a bar *closes* above the last swing high
   that was known by the origin bar. Price may not trade below the origin's low before that close.
3. **A violent leg.** From the origin to the break, price travels at least 3 ATR (the highest high
   of the leg minus the origin low), and the leg leaves a fair-value gap: some bar whose low is
   above the high two bars before it by at least 0.2 ATR.
4. **A strong break, not a poke.** The 3 bars after the break all close above the broken level,
   and price reaches 1 ATR beyond it within 5 bars. A break that falls back or stalls at the line
   is not an origin.
5. **The zone.** The origin bar from its low (the far edge, where the stop goes) to the top of
   its body (the near edge, where a resting buy sits), forced to between 0.2 and 1.5 ATR tall.
6. **Live** from the latest of: the pivot confirmed, the strong break confirmed, the gap formed.
7. **The return.** The first bar after it is live whose low reaches the near edge; only the first
   return is traded, and a zone not revisited within 300 bars is dropped. From the return there
   is a 12-bar window for the reaction - price may bounce at once, stall or grind. The zone fails
   on a close 0.1 ATR below the far edge, and the window closes once price leaves the zone by
   more than 0.25 ATR.
8. **Strong candles** (`strong_leg`, the `strong` filter): the leg's bodies average 60% or more
   of their bar ranges, at least 70% of its bars close in the move's direction, and at least one
   body is 1 ATR or larger.
9. **The mother cycle** (`bias_4h`, the `bias` filter): on the 4h chart, the last close beyond
   a confirmed swing high (or low) sets the bias up (or down); a trade must agree with it.

The `gallery/` folder draws only setups that pass both 8 and 9, four per entry type, picked at
random from 12 markets on 1h and 4h.

### 2. Production's origins - `zones_prod`, `prod_unit` (`ZONES=prod`)

The plots in `zones/prod/`. Production's own detector, `till_infinity/structures/drawing/origins.py`,
called unchanged and replayed the way production runs it:

1. **The volatility unit.** An exponentially weighted mean of absolute close-to-close moves in
   basis points (half-life 60 bars, floor 0.25 bps), times the close.
2. **Replay.** Every 4 bars, `Origins.observe` on the last 1,000 bars at that bar's unit.
3. **What production calls an origin:** a close-to-close move of 4 units within 6 bars, run out
   to its full extent; the origin is the extreme inside that window (the turn); the move must
   close beyond the highest (lowest) close of the 20 bars before the turn by at least 0.5 units.
4. **The zone** is the turn bar's full high-low range, or its body when that bar is 2 units or
   wider.
5. **Live** from the first replay that finds it, never before its structure break. Production
   never invalidates an origin; here only the first return is traded, as for the others.

The differences from 1: a running 20-bar extreme instead of a pivot, no fair-value gap, a single
bar's full range, no strong-break test - and about 14 times as many zones.

### 3. Fair-value gaps - `zones_fvg` (`ZONES=fvg`)

The plots in `zones/fvg/`.

1. **The gap.** Bar k's low is above bar k-2's high by at least 0.2 ATR (a bearish gap: bar k's
   high below bar k-2's low).
2. **The zone** runs from bar k-2's high (the far edge) to bar k's low (the near edge).
3. **Live** when bar k closes; first return as in 1.
4. **Strong** when the middle bar, the one that left the gap, has a body of 1 ATR or more in the
   gap's direction.

### 4. The DAX mentorship's POI - `dax_smc.long_setups`

The plots in `.data/dax_smc/`. The course's checklist, in its order:

1. **Sweep.** A swing low (3/3 pivot) that trades below the last swing low of the 40 bars before
   it - one no bar had broken in between - and closes back above it within two bars. That low is
   *protected*.
2. **Break.** The first close above the last swing high known before the sweep, within 60 bars,
   with the protected low holding. *Major* when that high was lower than the swing high before it
   (the previous lower high), *minor* otherwise.
3. **Structural liquidity.** The last swing low strictly between the protected low and the break,
   above the protected low. If there is none, the protected low is *inducement* and the setup is
   vetoed (kept only as the `no_sl` comparison group). It passes the *50% test* when it sits at or
   below the midpoint of the leg from the protected low to the break's high, and the *V test* when
   price stood at least 0.5 ATR above it within 3 bars on both sides.
4. **POI.** The QMR first: the last order block (a bearish bar followed within 3 bars by a 1-ATR
   rise) in the 30 bars before the sweep, which the drop into the sweep traded through - used when
   it sits above the structural liquidity, inside the discount half and untouched since the break.
   Otherwise the order block at the structural liquidity (the last bearish bar among the 5 up to
   it). Without structural liquidity, the order block at the protected low. The zone is that bar's
   full range.
5. **Context.** The entry in the discount half of the timeframe above's last swing range (4h for
   a 1h setup, 1d for 4h, weekly for 1d).
6. **Entries.** A limit at the POI's top (the risk entry), or at the structural liquidity (the
   trigger entry). Live for 50 bars from when everything above is known; cancelled by a close
   below the protected low or by price reaching the target unfilled. Stop 0.1 ATR past the
   protected low; target 3R.

### What every plot shows

Candles; the zone as a blue box from where it formed to the entry; the gap in orange (research
zones only - for production's origins the orange box has no meaning, since they need no gap); the
broken level dashed; the first return dotted; the entry as a triangle; the stop in red; the target
(the near edge of the nearest live opposite zone, or 3R for the DAX checklist) in green.

## Result

**Nothing passes.** 3,697 cells (market family x timeframe x trigger x filter x exit). On real
markets the average cell is -0.16R a trade against -0.13R for both nulls; 24 of 863 cells beat both
nulls in both halves, fewer than chance would give. No trigger, filter or exit is positive on
average:

- **The confirmations do not help.** Every candle pattern and SMC confirmation loses about as much
  as the plain touch: pin -0.13R, engulfing -0.25R, CISD -0.16R, CHoCH -0.12R, sweep -0.16R. The
  one positive, the double bottom (+0.20R), rests on 143 setups.
- **Lower-timeframe entries are worse, not better.** They do enter earlier with tighter stops, but
  the tighter stop is hit more: CISD on the 15m/30m/1h -0.24 to -0.30R, CHoCH -0.22 to -0.34R.
- **Wider stops do not save the trades the wick took.** From 0.1 to 1 ATR past the zone the win
  rate rises from 22.5% to 25.8% and R stays at -0.18 to -0.20.
- **The 4h bias, the nested 4h zone, strong candles and the SMC filters change nothing** (bias
  -0.13R, nested -0.38R, strong -0.25R, discount -0.13R, inducement -0.15R, killzone -0.19R, all of
  them -0.17R).
- **Deriv** behaves the same: -0.09R (smooth indices), 0.00R (jump indices, whose bar fills are
  unreliable).

### Direction, with the stop set aside

Asked separately: whether or not the stop is hit first, does price go the zone's way? From the
entry, the move 6 hours and 1, 3 and 5 days on, and whether price reaches 1, 2 or 4 ATR in the
zone's favour before as much against - each against random bars of the same market and side:

| | right way at 1 day | at 5 days | 2 ATR in favour first | random bars |
|---|---|---|---|---|
| 1h zones | 51% | 49% | 50% | 50% |
| 4h zones | 50% | 48% | 47% | 50% |
| 1d zones | 47% | 48% | **43%** | 50% |

**The zones point the right way half the time.** On 4h and 1d they are slightly worse than a coin:
returns to a higher-timeframe zone go through it more often than they bounce. The 4h bias does not
change this. Only the double bottom (58% reach 2 ATR first, n 143) and the index family on the 1h
(55% right at a day, against 49%) lean the right way; neither survives as a trade.

### Does a volatility forecast pick better zones?

A walk-forward HAR forecast of the next 5 days' true range over ATR (refit every 500 bars on rows
whose 5 days are over; correlation with the realised range 0.57 on 1h, 0.23 on 4h, 0.18 on 1d),
with each setup placed in its market's causal tercile of the forecast:

- **Real markets: no.** The terciles run from -0.28 to +0.05R (the best, 1d's top tercile with
  the opposite-zone exit, is +0.05R on 610 trades) and none points the right way more than random
  bars of the same tercile. A forecast of how far price will move says nothing about
  which way.
- **Deriv: a lead, not a result.** The top tercile turns positive on the smooth indices (1h +0.04
  to +0.11R, n about 1,600; 4h +0.06 to +0.15R, n about 450), and 1h setups there reach 2 ATR in
  their favour first 54% of the time against 51% for random bars. Found by splitting after looking;
  it needs its own out-of-sample run before anything else.

## A backtester bug the study found

The one cell that first passed (index 1h, touch, 4h discount, 4R: +0.41R, p < 0.003 against both
nulls) was an artefact. On a resting limit's fill bar `mt5bt` credited the target whenever the
bar's high reached it - but a buy limit is filled from above, so that high most likely printed
before the fill. 35 of the cell's 128 winners were such fill-bar targets; without them it is
-0.09R. **Fixed** (`walk`: on a resting order's fill bar a target counts only if the bar closes
beyond it; two tests). Earlier results with limit entries (the sweep and retest families in
[`imported-ideas.md`](imported-ideas.md)) were flattered by the same thing, so their verdicts -
none passed - stand; the validated survivors enter at market and are unaffected.

## Where it leaves the idea

The pictures look right - the desk checked them - and some of the trades are excellent. But the
rule that finds the excellent ones finds as many that fail, and the same geometry at random bars
does as well. The hand-picked examples (XAUUSD 4h reclaim, NAS100 1h short reclaim, EURUSD 1h short
engulf) are what the rule finds on a good day. If the desk sees something in them the rules miss,
the next step is to say which feature it is and test that feature alone, as the NAS100 example was
here (`fast_old`: -0.19R).

## The same harness on production's zones, fair-value gaps and the DAX mentorship's checklist

Run after the desk asked whether the research zones were production's (they are not) and for two
more zone definitions. Same triggers, filters, exits, 5-day hold, nulls and direction measure.

- **Production's origins** (`ZONES=prod`): `structures/drawing/origins.py` replayed every 4 bars
  over the last 1,000 at production's volatility unit (an EWMA of absolute close-to-close moves,
  half-life 60), live from the first replay that finds them. They differ from the research zones:
  a 20-bar running extreme instead of a pivot, 4 units in 6 bars, no gap required, the turn bar's
  full range (its body when 2+ units wide), never invalidated - 14x as many (3,975 on EURUSD 1h).
- **Fair-value gaps** (`ZONES=fvg`): every 0.2+ ATR three-bar gap, far edge to near edge.
- **The DAX mentorship** ([`dax_smc.py`](../ideas/dax_smc.py)): the course's full checklist - a
  swept low becomes protected, a major break of the previous lower high, structural liquidity
  (the last higher low, at or below 50% of the leg, an obvious V) or the inducement veto, the QMR
  else the order block as the POI, discount on the timeframe above; a risk entry (limit at the
  POI) and a trigger entry (limit at the structural liquidity), stop past the protected low, the
  source's fixed 3R. Both sides.

| | cells | real-market R a trade | coin / random time | cells beating both nulls, both halves |
|---|---|---|---|---|
| production's origins | 8,304 | -0.13 | -0.14 / -0.12 | 59 of 1,412 |
| fair-value gaps | 9,885 | -0.13 | -0.13 / -0.11 | 22 of 1,488 |
| DAX checklist | 824 | -0.13 | -0.11 / -0.10 | 0 of 152 |

- **Nothing passes.** Production's one "pass" (1d engulfing, `fast_old`, 10R: 30 trades) is the
  floor of the scoring: its coin twin had too few trades to bootstrap and the remaining p was 0 of
  200 draws. Not counted.
- **The DAX checklist, every step passing,** makes -0.11R (1d), -0.11R (1h), -0.15R (4h) at the
  source's 3R. The trigger entry is worse (-0.17 to -0.29R). The inducement veto is the only rule
  that moves anything, and a little: setups with structural liquidity -0.06 to -0.10R against
  -0.12 to -0.18R for those it skips; on the 1h they reach 2 ATR first 51.6% of the time against
  47.2%.
- **Direction, stop aside:** every confirmed trigger on every zone type is 47-53%. Production's
  plain touch reads 33-36% - not a signal that the zones break: they are one bar wide, so the bar
  that arrives runs through the limit price, and a measure taken from the limit counts that move.

## Levels where fair-value gaps line up (2026-10-03)

The desk's next idea: fair-value gaps from different moves that sit at the same height make a level,
whether or not they were filled later. What does price do when it gets back there? Then two
variants: count only levels that have already bounced (0.5, 1 or 2 ATR), and rest the entries
deeper - below the level for a buy, above it for a sell. Code: `zones_fvglevel`, `_proof` and the
`touch_*` triggers in [`zones.py`](../ideas/zones.py) (`ZONES=fvglevel LEVELS=...`); plots in
`.data/zones/fvg_levels/`.

**How a level is built.**

1. Every fair-value gap of 0.2+ ATR, either direction (`_gaps`).
2. A new gap whose band overlaps (within 0.1 ATR) an earlier gap 10 to 300 bars older makes a
   level at the mean of their centres; more gaps there add to it. A new level within 0.25 ATR of
   one not yet returned to is merged into it.
3. The level's band is +-0.25 ATR. Once price has gone 1 ATR away, the side it went decides
   support (a long) or resistance (a short); the first return is traded.
4. *Proven* (`LEVEL_BOUNCE` = 0.5 / 1 / 2): from the level's first gap on, some touch after which
   price went that many ATR back the way it came before closing through the band; the trade is the
   next return after that bounce completed.
5. *Deeper entries*: besides the touch at the band's near edge, resting limits at the level itself,
   at the band's far edge, and half an ATR beyond the level - resting through the 12-bar window,
   the stop always 0.6 ATR past the entry so R means the same at every depth.

**Matched nulls**, built and arrived at the same way: levels from a single gap with no partner
(does alignment matter?), and levels at a random price as far from the close as each aligned
level, on a random side (do the gaps matter at all?) - each also with the same bounce proof.

**What price does at the level** (the stop aside; from the touch, 1h, real markets):

| | 1 ATR back before 1 ATR through | 2 ATR | n |
|---|---|---|---|
| aligned gaps | 52.0% | 51.1% | 60,977 |
| one gap alone | 53.1% | 51.6% | 19,945 |
| random price, same distance | 51.6% | 50.7% | 63,231 |
| proven 0.5 / 1 / 2 ATR | 52.0 / 52.0 / 52.0% | 51.1 / 51.1 / 51.0% | |
| proven random | 51.7 / 51.7 / 51.6% | 50.7 / 50.7 / 50.6% | |

- **Lining up does not make a level.** Every kind of level, random ones included, shows the same
  slight reversal on a first touch (about 52%); the gaps add at most half a point. The number of
  gaps (2, 3, 4-5, 6+) changes nothing (51.4-52.4%).
- **A past bounce proves nothing,** because nearly every level has one: requiring it removes under
  1% of levels.
- **The deeper entries look superb with the stop aside (82-85% reach 1 ATR first) and are an
  artefact of that measure:** a limit far below the level fills on the spike, often at the bar's
  low, and random levels score the same. With the stop, they lose like the rest.

**Trading it** (all triggers, filters and exits; real markets, R a trade):

| levels | R | coin | random time | touch | middle | far edge | 0.5 ATR past |
|---|---|---|---|---|---|---|---|
| aligned | -0.12 | -0.13 | -0.11 | | | | |
| proven 1 ATR | -0.12 | -0.09 | -0.12 | -0.13 | -0.13 | -0.12 | -0.13 |
| proven random 1 ATR | -0.13 | -0.08 | -0.12 | -0.14 | -0.16 | -0.14 | -0.15 |

The gaps are worth about +0.01 to +0.02R over a random level that also bounced - inside the noise
and far short of the cost. Win rates are 21-22% at every depth.

## A flaw in the significance test, and the re-test

`zones.run` judged cells by a 200-draw day bootstrap and Benjamini-Hochberg over all cells. Two
faults, both fixed: a bootstrap that found no draw above the real mean returned p = 0 rather than
"below 1/201", which let a handful of 30-trade cells through as "passes"; and a cell whose coin
twin was too thin to test was judged on the other null alone. Floored at 1/201 and with a missing
null failing, **no cell of any run passes - but 200 draws cannot resolve significance across
thousands of cells either way**, so every cell of 200+ trades that beat both nulls in both halves
(561 of them, across the origin, production, gap, DAX and level runs) was re-tested with 10,000
draws. The best p is 0.0027 among about 10,000 cells; Bonferroni would need about 0.000005. The
random-price levels, which can have no edge, produce p-values as small. The nulls stand.
