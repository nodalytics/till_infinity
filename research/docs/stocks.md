# Mean reversion on the broker's share CFDs: nothing passes, and the test is too short to tell

Harness: [`research/harness/stocks.py`](../harness/stocks.py). Lab run 2026-09-30.

## The question

The MT5 terminal serves share CFDs. Does any classic stock mean-reversion strategy survive our
costs, our walks and a correction for how many variants were tried?

## The data, and its limits

| | |
|---|---|
| Share CFDs served | 448: 222 NYSE (`.N`), 217 NASDAQ (`.OQ`), 9 European. No sector labels |
| Used | 431 US names (the European 9 trade another calendar) |
| History | **13 months**: daily bars from 2025-09-02, 218 regular-session days; most names serve regular-session 1h bars only (~1,880 a year), a few the 22-hour CFD day |
| Spread | median round trip **1.2 bps** of price (p10 0.5, p90 3.5), from the recorded 1h-bar spread in regular hours. MT5's bar spread is a floor, so real costs are likely higher |
| Financing | `swap_mode` 5 (annual % of price): US longs **-7.4% a year**, shorts 0; charged on long exposure per calendar day |
| Split | fit on 2025-09-02 -> 2026-04-23 (60%), scored on 2026-04-24 -> 2026-09-28 (87 days, split into two halves of about 43) |

**Survivorship.** The terminal serves only names listed today. Delisted losers are missing, which
flatters buying losers. Over 13 months the effect is small, but it biases towards a pass.

## Method

Pre-registered, all in the harness docstring:

- **(a) Cross-sectional reversal** (Lehmann 1990; Lo & MacKinlay 1990): dollar-neutral, minus the
  demeaned 1/2/3/5-day return, held 1 or 5 days. Also cluster-neutral, with correlation clusters of
  about 15 names standing in for industries (Da, Liu & Schaumburg 2014).
- **(b) Connors RSI(2):** long below 10 above the 100-day mean (not the rule's 200-day, which
  doesn't fit in 218 days), out above the 5-day mean or after 10 days. Also long-short.
- **(c) z-score reversion:** in at |z| > 2 of the 20-day band, out inside 0.5. With and without
  Chan's variance-ratio filter (VR(5) < 0.9, [`chan.md`](chan.md)).
- **(d) Pairs:** distance pairs (Gatev, Goetzmann & Rouwenhorst 2006) and Engle-Granger pairs,
  formed on the fit block, traded net of both legs.
- **(e) Overnight vs intraday:** from the 1h open and close proxies, and the overnight-intraday
  reversal.

Every rule is scored net of spread (1x, 2x, 3x) and financing. The controls:

- **factor walks we generate** (one market factor, betas and idiosyncratic volatility matched per
  stock), run through the same code;
- **a random-rank placebo** for (a);
- **BH** over the 23 trials;
- **the Deflated Sharpe Ratio** over them.

The pass bar: test Sharpe ≥ 0.5 in the scored block and both halves, DSR > 0.95, positive at 2x
costs, and above the walks' 95th percentile.

## Results

| Rule | Test Sharpe | Halves | Fit Sharpe | 2x costs | Walks p95 | DSR | Verdict |
|---|---|---|---|---|---|---|---|
| xs L5 H1 | +3.06 | +0.29 / +5.80 | -2.03 | +2.96 | +1.08 | 0.468 | fail |
| xs L1 H5 | +2.90 | +0.05 / +5.92 | -1.25 | +2.80 | +1.25 | 0.428 | fail |
| **rsi2 long** | **+2.38** | **+2.18 / +2.54** | -2.38 | +2.31 | +1.99 | 0.308 | **fail on DSR only** |
| xs L2 H5 | +2.33 | -0.38 / +5.97 | -1.20 | +2.24 | +1.51 | 0.308 | fail |
| rsi2 long-short | +1.91 | +1.88 / +1.92 | -2.01 | +1.81 | +2.30 | 0.217 | fail (below walks) |
| xs L3 H5 | +1.85 | +0.37 / +4.12 | -1.60 | +1.77 | +1.14 | 0.217 | fail |
| zscore | +1.01 | +0.84 / +1.18 | -0.47 | +0.96 | +1.99 | 0.097 | fail (below walks) |
| zscore +VR<0.9 | +0.76 | +0.54 / +1.02 | -1.30 | +0.72 | +1.86 | 0.075 | fail |
| xs-cluster (best, L5 H1) | +1.37 | -1.69 / +4.57 | -1.87 | +1.22 | +0.79 | 0.143 | fail |
| pairs distance | -1.92 | -3.54 / -0.05 | +8.58 | -1.94 | +0.05 | 0.001 | fail |
| pairs coint | -3.73 | -4.81 / -2.40 | +10.67 | -3.74 | +1.89 | 0.000 | fail |
| overnight-intraday reversal | -1.15 | -0.07 / -2.32 | | -1.46 | | 0.002 | fail |

The random-rank placebo on the xs family reads a test Sharpe of +0.59 at its 95th percentile. The
overnight session carried the drift: equal-weight overnight returned +7.6% annualised (Sharpe
+0.60), and intraday -2.8%.

## What this means

- **Nothing passes.** The best rules fail the Deflated Sharpe Ratio. With 23 trials and 87 test
  days, a Sharpe of about +3 is what the best of 23 noisy tries can reach, which is exactly what
  DSR 0.3-0.47 says.
- **Every rule's fit period was negative and its test period positive.** Almost all the gain sits
  in the test block's second half, about 43 days from mid-July to late September 2026 (xs +4 to +6
  there). That is the market changing regime over the two periods, not a rule being learned: the
  fit block chose nothing, because everything lost in it. One regime is not evidence.
- **RSI(2) long is the one to watch.** It is positive in both halves (+2.18 / +2.54), beats the
  walks' 95th percentile (+1.99), and survives 3x costs (+2.25). It fails only on deflation, and it
  lost in the fit block (-2.38). That is Connors' rule behaving as it is known to: it pays in some
  regimes and not others.
- **Pairs fail badly out of sample.** The in-sample Sharpes of +8.6 and +10.7 are formation-period
  overfitting; the out-of-sample spreads did not revert.
- **Costs are not the problem here.** The recorded spread is about 1.2 bps round trip, and every
  rule's ranking holds at 3x. The problem is 13 months of history and one regime.

## For production

- **Nothing to trade live.** At most, **paper-trade RSI(2) long** to accumulate an out-of-sample
  record across regimes. It needs about a year more of data before a DSR > 0.95 is even reachable.
- **What trading share CFDs would need:**
  - symbol handling for the `.N` / `.OQ` suffixes and the broker's exchange sessions (regular hours
    for most names);
  - financing through the new swap gate (`trading/swap.py` already reads `swap_mode` 5; US longs
    cost 7.4% a year, shorts nothing);
  - an earnings-date blackout (the terminal carries no calendar; it needs an external source);
  - the confirmation that MT5's bar spread understates fills. Measure live fills before trusting
    1.2 bps.
- **For the fund study** ([`fund.md`](fund.md), running): 431 share CFDs with 13 months of daily
  bars are now cached on the lab (`data/seqlab/*.OQ.1d.npz`, `*.N.1d.npz`). That is too short for a
  volatility-managed equity sleeve's track record, but usable for a cross-sectional check.
