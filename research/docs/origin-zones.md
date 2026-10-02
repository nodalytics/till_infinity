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
