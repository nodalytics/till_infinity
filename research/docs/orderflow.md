# Order flow explains the bar it happens in, absorption does no better than any spike, and volume-profile levels hold like random prices

Measured 2026-09-28 on the lab with [`orderflow.py`](../harness/orderflow.py) and
[`volumeprofile.py`](../harness/volumeprofile.py).

**Order flow data:** every trade on Binance USDT-M futures for BTC, ETH and SOL from September 2025
to August 2026. That is 12 months, and each trade carries its aggressor side (`is_buyer_maker`).
The trades are streamed into 1-minute bars of taker-buy volume, taker-sell volume, trade counts,
and large-trade flow (at least $100k / $50k / $25k per trade), then into 105,120 5m bars per
symbol. Spot FX has no central tape, so this is the only real footprint free data allows. BTC, ETH
and SOL are what the desk trades through Deriv, whose quote follows the exchange consensus
([`lagging.md`](lagging.md)).

**Volume profile** is tested on those crypto bars (real volume) and on the lab's broker 15m bars
for 15 FX pairs, XAU and XAG (tick volume), with four random walks as the control.

Train is each series' first 60% by time and test the last 40%. Every threshold was fixed before
any result was seen. Costs are round trip: Deriv's crypto spread (2.4bp) and a Binance taker (10bp).

## The claims

From Trader Dale, "ORDER FLOW: How to Trade The Absorption Setup" (notes in
`.secrets/videos/notes.md`):
- At a strong support level from volume profile (a heavy-volume node formed inside a rejection),
  after a sudden sell-off, a 5-minute footprint shows **unusually heavy volume on both the bid and
  the ask while price does not move**. Buyers are "buying everything the sellers have to sell";
  the sellers exhaust, and price turns up.
- "If you see huge volumes on bid and on ask somewhere random on the chart, that doesn't really
  mean anything." Absorption counts only at a level. That is a built-in placebo.

And the broader ideas:
- **order flow** (signed aggressive volume) says where price goes next;
- **volume profile** levels (POC, high- and low-volume nodes, value-area edges) are where price
  turns.

## 1. Absorption

Pre-registered, long case (mirrored for short):
- **the move in:** the prior 30 minutes fell at least 2 sigma (sigma is the trailing one-day mean
  |5m return|);
- **heavy on both sides:** this 5m bar's taker-buy and taker-sell volume are each at least 2x their
  trailing one-day median;
- **the stall:** the bar's net move is within ±0.5 sigma;
- **at a level:** within 1 sigma of a one-day swing high or low, or of a high-volume node of the
  last three days' profile.

The trade is taken against the move in, one minute after the bar closes, and is non-overlapping per
symbol. Three twins isolate the ingredients:
- **absorption away from levels:** Dale's placebo;
- **stall only:** the same spike and stall with no volume condition;
- **one-sided:** heavy flow on the aggressor side only, with price continuing.

**Every spike** is the base rate of fading the move.

Mean forward move aligned with the trade, in sigma, then gross bps:

| | train n | train 1h / 4h | test n | test 1h / 4h | test 4h gross, net of Deriv / taker | bracket (stop past the bar, 2R target), test |
| --- | ---: | --- | ---: | --- | --- | --- |
| **absorption at a level** | 1,106 | -0.43 / -0.54 | 802 | -0.08 / **+0.27** | +4.7bp, +2.3 / -5.3 | -0.75R |
| absorption away from levels | 928 | -0.61 / -1.17 | 622 | -0.54 / -0.41 | +1.6bp, -0.8 / -8.4 | -0.77R |
| stall only, at a level | 2,897 | -0.06 / +0.20 | 1,972 | -0.02 / +0.04 | -0.2bp | -1.10R |
| one-sided heavy flow | 1,744 | -0.10 / +0.05 | 1,240 | +0.06 / +0.01 | +2.5bp | -1.37R |
| **every spike (base rate)** | 3,679 | -0.02 / -0.22 | 2,460 | +0.25 / **+0.50** | +4.5bp, +2.1 / -5.5 | -0.81R |

- **The location condition is real in direction, but weak in size.** Absorption at a level beats
  absorption away from levels in both periods, by 0.6-0.7 sigma at 4h. Away from levels,
  heavy two-sided volume that stalls is followed by *more* of the move in, which fits Dale's warning
  that it "doesn't really mean anything" there.
- **At a level, absorption adds nothing to fading any spike.**
  - In test, the base rate of every spike is +0.50 sigma at 4h against absorption's +0.27.
  - In train, absorption at a level is -0.54 against the base rate's -0.22.
  - Absorption's own sign flips between train and test, and the test positive is just what the whole
    period did after spikes.
- **Nothing pays.**
  - The best cell grosses 4.7bp over 4 hours. That is +2.3bp after Deriv's spread, and it is negative
    in train.
  - Every bracket version loses 0.58-1.37R. A stop placed past the absorption bar's extreme sits
    within reach of ordinary noise.

## 2. Order flow: the present, not the future

Test block, pooled, sampled hourly (n = 10,500, standard error of a correlation about 0.01).
Imbalance is (taker buy - taker sell) / volume over the last k:

| k -> next | imbalance vs same-window return | imbalance -> future | past return -> future | **imbalance beyond past return** | large-trade imbalance -> future |
| --- | ---: | ---: | ---: | ---: | ---: |
| 5m -> 15m | +0.654 | -0.012 | -0.013 | **-0.005** | -0.009 |
| 5m -> 1h | +0.654 | -0.010 | +0.001 | **-0.014** | -0.017 |
| 15m -> 15m | +0.615 | -0.019 | -0.018 | **-0.010** | -0.018 |
| 15m -> 1h | +0.615 | -0.006 | -0.018 | **+0.007** | -0.010 |
| 60m -> 15m | +0.513 | -0.030 | -0.042 | **-0.009** | -0.035 |
| 60m -> 1h | +0.513 | -0.025 | -0.057 | **+0.004** | -0.032 |

- **Signed flow *is* the price move:** +0.51 to +0.65 with the same window's return. That is Kyle's
  price impact: aggressive buying moves price as it happens.
- **It says nothing about what comes next.** Once past return is accounted for, imbalance predicts
  the next 15m or 1h at -0.014 to +0.007, within about one standard error of zero.
- **What little there is comes from price.** The one visible regularity is short-term *reversal*
  of the past hour's return (-0.042 and -0.057). Raw imbalance and large-trade imbalance only
  echo it, because they are correlated with that return.
- **Large trades** ("whales") add nothing beyond that echo.

## 3. Volume profile: its levels hold like random prices

Each UTC day, a profile is built from the prior three days (volume at typical price, bins of half a
baseline move), giving the POC, high-volume nodes, low-volume nodes and the value-area edges. The
next day's first touch of each level is followed, and so are **placebo levels**: random prices in
the same range, at least half a move from any real level, followed identically.

The race: from the touch, does price travel one baseline move back the way it came (a bounce)
before one move through, within an hour? A bar reaching both counts as a break. Test block:

| bounce rate (n) | POC | HVN | LVN | VAH / VAL | **placebo** |
| --- | --- | --- | --- | --- | --- |
| crypto, real volume, 5m | 49.3% (205) | 48.8% (3,414) | 45.4% (3,555) | 46.6% (365) | **44.9%** (1,152) |
| FX, tick volume, 15m | 46.3% (1,495) | 46.7% (11,690) | 46.8% (13,913) | 47.6% (2,755) | **46.8%** (8,286) |
| metals, tick volume, 15m | 43.7% (191) | 45.5% (1,576) | 42.8% (1,883) | 43.1% (344) | **42.3%** (1,037) |
| random walks, 15m | 51.0% (351) | 46.4% (2,519) | 46.8% (2,674) | 44.6% (694) | **45.0%** (2,005) |

- **FX:** every kind of level is within 1.2 points of a random price.
- **Crypto:** high-volume nodes beat the placebo by 3.9 points (about 2 standard errors). The
  halves are 49.1% / 48.6% against 47.6% / 42.4%, so the gap is mostly one half.
- **The random walks**, which have no memory by construction, show a gap just as large: the POC is
  6.0 points over the placebo. Across 16 level-by-market comparisons, a 4-point gap is what
  noise produces.
- **Stickiness does not separate either.** Price spends 10-20% of the next hour within half a move
  of the level, whether the level is a POC, an HVN or a random price.
- **Even the crypto HVN gap would not pay.** A symmetric ±1 race that wins 48.8% instead of 44.9%
  is worth about 0.08 of a baseline move before costs
  ([`barrier-geometry-is-irrelevant.md`](barrier-geometry-is-irrelevant.md)). On BTC's 5m moves
  that is of the order of a basis point, against Deriv's 2.4bp spread.

## What this settles

- **Absorption as an entry confirmation has no edge on real footprints.** Where it is supposed to
  work, at a level, it does no better than fading any spike, and its sign flips between periods.
  The at-level versus away difference Dale describes does show up in direction, but it separates a
  bad signal from a worse one.
- **Order flow is how price moves, not where it goes next.** The imbalance of aggressive volume
  moves with the price at +0.5 to +0.65 and predicts nothing beyond past returns. This is the same
  answer as every price-based direction test on this desk
  ([`fractal-twins.md`](fractal-twins.md), [`state-and-memory.md`](state-and-memory.md)), now from
  non-price data.
- **Volume-profile levels are random prices** as far as a bounce is concerned: FX within 1.2
  points, crypto within the range the random walks produce.
- **For production:** nothing to build. A footprint feed would add infrastructure and a Binance
  dependency to the desk and buy nothing measurable.
