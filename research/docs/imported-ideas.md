# The imported ideas, re-tested on the broker: crypto momentum ignition survives, the rest does not

Measured 2026-10-02. The desk's earlier projects (the sage service, its api, and the research lab)
had built and tested a large number of trading ideas. Five catalogues copy every one of them into
[`../ideas/`](../ideas/):
- [`catalogue-sage-docs.md`](../ideas/catalogue-sage-docs.md), [`catalogue-sage-code.md`](../ideas/catalogue-sage-code.md);
- [`catalogue-api.md`](../ideas/catalogue-api.md);
- [`catalogue-lab-docs.md`](../ideas/catalogue-lab-docs.md), [`catalogue-lab-code.md`](../ideas/catalogue-lab-code.md),
  [`catalogue-lab-scripts.md`](../ideas/catalogue-lab-scripts.md).

Every idea that can be traded on broker bars was re-implemented and re-tested from scratch,
whatever its earlier verdict, because the earlier tests had flaws (below).

## How they were traded

The harness is [`../ideas/`](../ideas/README.md): `setups.py` (the rules), `run.py` (the
backtest), `score.py`, `validate.py`, `portfolio.py`.

- **Data:** the broker's own bars to 2026-10-02 (FX, gold, silver, 7 indices, 2 oils, BTC/ETH/SOL,
  8 Deriv indices; 15m, 1h, 4h, 1d), fetched for this.
- **Engine:** [mt5bt](../mt5bt/README.md), with resting limit orders added for this work. A limit
  fills only once price trades a spread through it.
- **Geometry, a trader's:** enter at the structure the idea names (at market on the confirming
  close, or a resting limit at the zone). The stop goes just beyond what would prove the idea
  wrong (0.1 ATR past it), and never inside two spreads. Where a source fixed its own geometry
  (zma's stop at one sigma with the mean as target, the lab's 2.5/4 ATR sweep fade, the box
  breakout's box-width stop), that version ran too.
- **Exits:**
  - `trail`: the market decides, via a 2-ATR trailing stop and no target;
  - `t4` and `t10`: targets at 4R and 10R;
  - `focus`: out at the first FOCuS changepoint against the trade;
  - `src`: the source's own exit.
- **Costs:** the broker's spread, swap, and its lot grid. MT5 bars carry each bar's *lowest*
  spread, which is 0 on most of this broker's bars. So the floor is the median tick spread, or
  the broker's quoted spread (11 points on EURUSD, 16 on gold, 36 on the S&P). A first pass
  without it showed every tight-stop setup trading for free.
- **Controls:**
  - a **coin twin** of every cell: the same fills replayed with a random side and the same exit;
  - six **GARCH walks** we generate ourselves.
- **Pass rule, per cell** (setup × tag × exit × family × timeframe), all of these:
  - n ≥ 30;
  - net R > 0 in both halves;
  - beats its coin twin, day-bootstrap q < 0.05 after Benjamini-Hochberg across every cell;
  - the walks earn under half of it.
- **Deriv's jump instruments** (Boom, Crash, Jump, Range Break) are scored as their own family and
  cannot pass. Bar fills miss their jumps: one cell earned +5.6R a trade, and its random-side twin
  +3.4R, almost all on Range Break.
- **Then a one-shot validation.** The passing cells were frozen in
  [`candidates.json`](../ideas/candidates.json) before any fresh data was scored, then re-run
  unchanged on instruments they had never seen:
  - the broker's 32 other crypto CFDs;
  - platinum, palladium and copper;
  - seven smooth Deriv indices.

## What was flawed in the original tests

| Source | Flaw | Effect |
|---|---|---|
| sage | The outcome walk starts one bar late, so a stop hit in the bar after the signal is never counted | Win rates overstated: the "grade A, 61%, +0.92R" claim was measured this way |
| sage | Entry at the signal bar's close; production fills a collection cycle later. Calibration feeds back into the grades it is then measured by | Optimistic, and circular |
| lab | `MaxwellCurl` reads the next bar; `Omori` reads up to 47 future bars | Every "verified" row built on them is void (rebuilt causally here: `physics`) |
| lab | Box and compression breakouts fill at the box edge on a *close* beyond it | Entries flattered (rebuilt at the close: `box_breakout`) |
| lab | The level lab divides a price-fraction cost by a price-unit stop | Gold, JPY pairs and crypto undercharged |
| lab | Bounce-fade studies drop touches unresolved within 24 bars | Selection bias |
| lab | Per-instrument "verified" signals: 6-bar hit rates with no costs, overlapping walk-forward windows, many cells | Multiple testing on overlapping data |
| lab | HTF slope interpolated by timestamp in the coherence study; HMM Viterbi over the full series; full-sample quantiles inside rules | Lookahead |
| lab | Deriv used as the random-walk control | Deriv is a market (`generators.md`) |
| api | The Mongo fallback returns the *oldest* bars, so the dollar and commodity confluence ran on data 12-630 days old | Live signals were stale |
| api | AME ships its sweep direction inverted; ATR=0 from a swallowed import makes the composer SKIP every setup | The live system did not do what it says (both tested here) |
| all | No bid/ask; flat bp costs; the last bar is often still forming | Optimistic |

## Results

Three runs over 56 rule families:
- **Run 1** (the sage ideas and FOCuS): 1,872 cells, 2 pass.
- **Run 2** (the api and lab ideas): 1,784 cells, 7 pass.
- **Run 3** (every family with the FOCuS exit): 1,186 cells, 2 pass.

After deflation, nothing passes in FX, indices, energy, smooth Deriv or metals that also holds on
fresh instruments. That includes every SMC/ICT pattern, every level reaction, every
mean-reversion rule, every candle rule, every sweep fade, the sage composer's components, and
the lab's "verified" physics signals.

**The one-shot validation on 32 fresh crypto CFDs** (pre-registered; q across the candidates):

| Candidate (crypto, daily) | Trades | Net R | Halves | Coin twin | Coins positive | P(≥4R) | Survives |
|---|---|---|---|---|---|---|---|
| `cusum_follow`, 10R target | 297 | **+0.47** | +0.49 / +0.46 | −0.21 | 58% | 13% | **yes** |
| `cusum_follow`, FOCuS exit | 333 | **+0.27** | +0.23 / +0.31 | +0.02 | 55% | 8% | **yes** |
| `anomaly`, 10R target | 197 | **+0.62** | +1.00 / +0.25 | +0.14 | 63% | 14% | **yes** |
| `donchian_trend`, trail / 4R | 1,231 / 893 | −0.07 / −0.19 | | | | | no |
| `box_breakout`, trail | 2,298 | −0.02 | | | | | no |
| `triangle_cook`, 10R | 278 | −0.01 | | | | | no |
| `focus_size`, trail | 1,503 | −0.05 | | | | | no |

The two rules that survive:
- **`cusum_follow`:** the first bar a CUSUM of log returns (drift 0.5σ, line 5σ, σ from the 60
  returns before the last 30) crosses up is bought. The stop is 2 ATR.
- **`anomaly`:** a daily return beyond 5 robust sigmas of the previous 60, closing in its top
  third, is followed. The stop goes just under that bar.

Both are **momentum ignition**: a move that breaks out of noise, held for the fat right tail.
About 1 trade in 7 reaches 4R. They do not pay with a 2-ATR trail. They pay with a 10R target
or the FOCuS exit, which hold through the noise.

**Metals and Deriv candidates fail on their fresh instruments:**
- `tf_coherent_breakout` on platinum, palladium and copper: −0.34R;
- `cusum_follow` on metals at 15m: −0.52R;
- `asc_triangle` on the smooth Deriv indices: −0.12R.

## Portfolios ([`portfolio.py`](../ideas/portfolio.py), daily, the broker's spread on turnover)

| Book | Sharpe | Halves | Beats random books | Fresh check |
|---|---|---|---|---|
| **Time-series momentum** (7/14/30/60-day sign ensemble, vol-scaled), 26 instruments | **0.66** | 0.61 / 0.72 | 100% | **0.42 on the 32 fresh coins (0.97 / 0.34), passes** |
| Cross-sectional momentum, 30 days, weekly | 0.70 | 0.87 / 0.50 | 100% | −0.09 on fresh coins, fails |
| Cross-sectional momentum, 15 days | 0.80 | 1.60 / −0.19 | | fails in-sample |
| Gold momentum alone | 0.35 | 0.09 / 0.56 | 96% | −0.17 platinum, −0.22 palladium: a gold result, not a metals one |
| Gold real-rate switch (FRED DFII10, a day late) | 0.27 | 0.00 / 0.48 | | fails |
| Currency strength, momentum and reversal | −1.83 to +0.06 | | | fails |
| Early acceleration | −0.30 | | | fails |
| Every Deriv book | −0.43 to +0.08 | | | fails |

## FOCuS, as entries and as an exit

- **As entries, nothing validates.**
  - Follow, fade, zone retest and multi-timeframe agreement fail everywhere.
  - Changes in move *size* (`focus_size`) passed on BTC/ETH/SOL daily but failed on the fresh
    coins.
- **As an exit**, compared with the 2-ATR trail on the very same entries across 1,021 cells: worse
  overall.
  - It is better in only 38% of cells, by −0.11R on average.
  - By family: crypto +0.14R, metals +0.04, FX and indices −0.04 to −0.06, energy −0.76.
- **So it is an exit for trending markets.** Its one validated use is on crypto ignition
  (`cusum_follow` with the FOCuS exit, +0.27R on fresh coins).

## Cross-pollination (exploratory: the parts were chosen on these coins)

All 35 crypto CFDs, daily, q < 0.05, both halves positive:

| Combination | 10R target | FOCuS exit | Its part alone (10R) |
|---|---|---|---|
| `anomaly` taken only with the momentum ensemble on its side | **+0.99R** (1.24 / 0.73) | +0.26 | +0.82 |
| `cusum_follow` with the momentum ensemble | +0.68 | **+0.37** | +0.66 |
| Donchian or box breakout confirmed by CUSUM within 3 bars | **+0.75** | +0.33 | breakouts alone fail fresh |
| CUSUM confirmed by a 5-sigma bar | +0.80 (1.49 / 0.12) | +0.19 | |

What adds:
- **The momentum gate** helps the 5-sigma bar most.
- **CUSUM confirmation** turns failing breakouts into paying ones.

At 4h the same combinations earn +0.25 to +0.53R with the FOCuS exit or a 10R target.
These are paper-trading candidates, not validated results: no instrument here is unseen.

## What it means

- **The broad finding stands.** Hundreds of ideas built on levels, structure, patterns and
  reversion do not earn their spread on these markets. That matches [`findings.md`](findings.md).
- **What does earn, consistently, is momentum where trends persist.** In crypto, ignition
  (CUSUM, 5-sigma bars) holds on 32 coins it never saw, as does a time-series momentum book. That
  agrees with the battery's crypto 4h CCI survivor ([`battery.md`](battery.md)).
- **The payoff is the fat right tail.** These trades win 20-35% of the time, and are paid by the
  13-16% that reach 4R. The 4-10R picture holds here, and only here.
- **Next:**
  1. Paper-trade `cusum_follow` and `anomaly` (crypto daily, 10R target and FOCuS exit) beside
     the crypto 4h CCI.
  2. Paper-trade the momentum-gated `anomaly` and the CUSUM-confirmed breakout as the
     exploratory arm.
  3. Paper-trade the time-series momentum book.
  4. Each with a coin twin and kill checkpoints, as in [`battery.md`](battery.md).

## Not testable on MT5 bars (listed in the catalogues)

- **Crypto exchange data:** funding and open-interest rules, liquidation clusters, flow and tape,
  and fresh-listing fades. They need exchange data ([`../freqtrade/`](../freqtrade/README.md)).
- **Other data sources:** options IV and volatility risk premium, COT, DeFi TVL/FDV, sector caps,
  on-chain flows, and retail positioning snapshots.
- **Deriv binary contracts and the RDBULL/RDBEAR resets:** these are payoffs, not prices.
- **Tick-level Deriv scalpers:** they need ticks.
- **Anything needing a historical news calendar.**
