# TA indicators as strategies: crypto trend-following survives on fresh coins, thinly; nothing else does

Measured 2026-10-02 on the lab with [`ta_battery.py`](../harness/ta_battery.py),
[`ta_validate.py`](../harness/ta_validate.py) and [`ta_meta.py`](../harness/ta_meta.py), with the
[`mt5bt`](../mt5bt/README.md) backtester.

Earlier work used indicators as entry timing ([`indicators.md`](indicators.md): 0 of about 170
cells) and as confirmation gates ([`confirm.md`](confirm.md): 17 of 8,366 cells, most failing
deflation). This is the first time they were traded as strategies in their own right, across the
whole book.

## The battery

**Rules:** 19 textbook rules at default parameters, entering at the next open after a signal at
the close:

- moving-average crosses: SMA 20/50, SMA 50/200;
- oscillators: MACD (12/26/9), RSI(14) and RSI(2), stochastic, Williams %R, CCI;
- bands and channels: Bollinger reversion and breakout, Donchian 20 and 55, Keltner;
- trend systems: ADX with a DI cross, Ichimoku, Parabolic SAR, Supertrend;
- OBV against its average, and Heikin-Ashi colour flips.

**Exits, the same for all:** stop at 2 ATR, trailing stop at 3 ATR, out on the opposite signal,
200 bars at most. No take-profit.

**Universe:** the broker's own bars for FX (15 pairs), metals (2), crypto (3), US stocks (20, 1h
and 1d) and Deriv (8), at 15m, 1h, 4h and 1d. Costs are each bar's spread plus swap.

**Nulls:** each cell has a coin twin (the same entries and exits, a random side), and each rule
also runs on GARCH walks.

**The bar:** beat the coin after Benjamini-Hochberg across all 323 cells, positive in both halves,
positive net, and not positive on walks.

**15 of 323 cells passed:**

| Group | Cells | Note |
|---|---|---|
| Crypto, 4h and 1d trend rules | 12 | Donchian 20 and 55, Bollinger and Keltner breakouts, CCI, Supertrend, MACD, OBV; daily Donchian 55 at +0.54R a trade (coin +0.11) |
| Stocks 1h SMA 20/50 | 1 | +0.12R (coin −0.04) |
| Deriv 15m, Bollinger breakout and Parabolic SAR | 2 | Mostly Range Break and Crash fill artefacts: their coin twins earn as much. Drift Switch 10 is the exception (+0.15R against a +0.05 coin), consistent with its measured autocorrelation |

FX and metals have no survivors; their trend rules lose net. Every crypto survivor decays: first
half +0.7 to +1.0R, second half +0.1R.

## The payoff profile: winners average 1.3-2.0R, not 2-4R

Across the 323 cells the median shape is the same everywhere: a 35% win rate, winners of about
1.4R, losers of about −0.8R, roughly break-even before costs. Only 5 cells average a 2R winner,
all crypto daily trend rules.

| Survivor | Win rate | Avg winner | Avg loser | Trades ≥ 1R / 2R / 4R | Best | Expectancy |
|---|---|---|---|---|---|---|
| Crypto 1d Donchian 55 | 49% | 1.94R | −0.79R | 30% / 20% / 5% | 9.9R | +0.54R |
| Crypto 1d Donchian 20 | 43% | 2.01R | −0.79R | 28% / 17% / 5% | 9.9R | +0.42R |
| Crypto 4h Keltner | 39% | 1.74R | −0.80R | 22% / 13% / 5% | 9.8R | +0.20R |
| Stocks 1h SMA 20/50 | 39% | 1.47R | −0.74R | 19% / 10% / 3% | 10.4R | +0.12R |

## The validation on fresh instruments ([`ta_validate.py`](../harness/ta_validate.py))

Picking 15 of 323 cells is itself a selection, so each survivor was re-run unchanged on
instruments that played no part in picking it:

- **crypto:** the 12 crypto rules on Binance USD-M perps, 2021-2026, with taker fees and the
  archive's own funding. The **9 coins** outside BTC, ETH and SOL are the test;
- **stocks:** the stock rule on **100 other stocks**.

| Fresh test | Trades | Net R | Coin | Difference (q) | Halves | Passes |
|---|---|---|---|---|---|---|
| **Crypto 4h CCI(20) ±100** | 5,372 | **+0.059** | −0.018 | +0.077 (0.013) | +0.053 / +0.065 | **yes** |
| Crypto 1d Bollinger breakout | 611 | +0.115 | −0.044 | +0.159 (0.10) | +0.12 / +0.11 | no (deflation) |
| Crypto 1d Donchian 20 | 602 | +0.107 | −0.008 | +0.116 (0.10) | +0.11 / +0.10 | no |
| Crypto 4h Keltner | 2,454 | +0.053 | −0.007 | +0.059 (0.10) | +0.05 / +0.05 | no |
| Crypto 1d Donchian 55, the original best | 337 | −0.005 | +0.078 | −0.083 | | no |
| Stocks 1h SMA 20/50 | 4,121 | −0.122 | −0.088 | −0.035 | | no |

- **10 of the 12 crypto rules beat their coin on the fresh coins.** Crypto has a consistent trend
  tendency that survives instruments it was not found on. It is the first directional effect in
  this program to do that.
- **It is far smaller than the selection sample showed.** +0.0 to +0.11R a trade on fresh coins,
  not +0.2 to +0.5.
- **One cell passes every pre-registered test:** crypto 4h CCI(20) ±100, at +0.06R a trade.
- **The stock rule fails;** it was a fluke of one sample.

**A caveat on absolute R:** bar backtests can flatter stops filled at their level. A check on
zero-cost walks read +0.03 ± 0.01 in one run and was not reproduced in three others (+0.005,
+0.037, +0.011, each ±0.02-0.05), so no reliable bias was found. Comparisons against coin twins
are immune either way, since the twin shares the exits.

## Does ML raise the winners? ([`ta_meta.py`](../harness/ta_meta.py))

**The setup:** one gradient-boosted model over every rule, family and timeframe (4.4 million
trades), predicting each trade's R from what is known at entry. Inputs: volatility and compression
percentiles, trend efficiency, distance from the mean, RSI, the 16-bar return, range and volume z,
the hour and weekday, the side, and the rule, family and timeframe. It was trained on each
instrument's first half and picked the top 30% of the second half.

| | All trades | ML's top 30% | Lift |
|---|---|---|---|
| Markets | −0.043R, win 35%, avg winner 1.09R | +0.027R, win 36%, avg winner 1.26R | +0.07R |
| GARCH walks | −0.165R | +0.111R | +0.28R |

**It fails the pre-registered test.** The lift on walks is four times the lift on markets, so what
the model learns is not market information. The walk trades come from only 16 walk paths, so
their numbers are dominated by each path's luck, plus a real asymmetry: the example contract
charges longs swap and credits shorts, so "short" looks good on long holds. Meta-labelling fails
here as it did before ([`lopez-de-prado.md`](lopez-de-prado.md)).

## Verdict

- **The one tradeable directional result in this program** is crypto trend-following at 4h and
  1d. It is real on fresh coins but thin: about +0.06R a trade net for the rule that passes
  everything, +0.0 to +0.11R across the family.
- **It is a candidate for a paper or shadow account, not production.** It needs a forward record
  on fresh data before money.
- **FX, metals and stocks:** no indicator strategy has an edge.
- **Deriv:** the apparent edges are fill artefacts, except Drift Switch, which is being checked on
  real ticks ([`ta_ticks.py`](../harness/ta_ticks.py), [`deriv_ticks.py`](../harness/deriv_ticks.py)).

## On real ticks ([`ta_ticks.py`](../harness/ta_ticks.py), [`deriv_ticks.py`](../harness/deriv_ticks.py))

**The tick battery:** 21 rules (the 19 plus EMA 9/21 and 20/50) on 1m, 5m and 15m candles built
from real bid/ask ticks, with every fill on the ticks themselves. Each rule ran plain and aligned
with the next timeframe up (1m → 15m, 5m → 1h, 15m → 4h, as of its last closed candle).

- **Instruments:** Drift Switch 10 and Jump 50 (2026-02-13 → 10-02, about 20 million ticks each);
  EURUSD, XAUUSD and BTCUSD (the last 30 days).
- **Missing:** US 500 returned no ticks under that name.
- **Scale:** 592 cells.

**7 cells pass deflation, and only one group looks real:**

| Cell | Trades | Net R | Coin twin | Halves |
|---|---|---|---|---|
| Drift Switch 10, 15m MACD, aligned | 715 | +0.093 | −0.092 | +0.10 / +0.08 |
| Drift Switch 10, 5m EMA 20/50, aligned | 601 | +0.055 | −0.244 | +0.03 / +0.08 |
| Drift Switch 10, 15m CCI, aligned | 577 | +0.027 | −0.196 | +0.01 / +0.04 |
| Drift Switch 10, 15m Keltner | 786 | +0.024 | −0.128 | +0.02 / +0.03 |
| Jump 50, 5m Supertrend | 2,140 | +0.026 | −0.069 | +0.01 / +0.04 |
| BTCUSD 5m RSI(14), aligned | 65 | +0.279 | −0.300 | |
| EURUSD 15m CCI, aligned | 37 | +0.122 | −0.327 | |

- **Drift Switch trend-following holds up on ticks** with indicator exits. That fits the index's
  published design (drift regimes that switch, an autocorrelation of +0.15, [`families.md`](families.md)).
  **Re-tested on the sister indices, Drift Switch 20 and 30** (never used in choosing,
  [`drift_validate.py`](../harness/drift_validate.py), 20 million ticks each):
  - **The trend effect replicates:** all 8 cells beat their coin by +0.09 to +0.28R, 6 of them
    significant after deflation. It is a genuine property of how these indices are generated.
  - **It does not pay the spread:** on DSI 20 every cell is net negative (−0.01 to −0.15R). On
    DSI 30 the positive cells (+0.02 to +0.08R) all turn negative in their second half.
  - **None passes.** A real directional property, too small to trade after Deriv's costs.
- **The BTCUSD and EURUSD cells are noise** (37 and 65 trades from 30 days); Jump 50's +0.026R is
  negligible.
- **Timeframe alignment does not help on average:** the aligned version beats the plain one in only
  45% of cells.
- **1m candles are worst** (median −0.09R; costs dominate).

**The Deriv candidates' brackets, settled on ticks.**

- **Drift Switch 10's brackets** made +0.05 to +0.11R on bars. On ticks they make +0.008 (any
  compression), −0.030 (the alert) and −0.490 (the hedged pair). The bar-level profit was fill
  optimism.
- **Jump 50's brackets** stay positive on ticks (+0.07 to +0.12R, both halves), so they pass the
  letter of the pre-registered rule. But at about 230-480 trades that is about 1.3 standard errors.
  Jump 50 is published as a jump-diffusion martingale, and its fresh three weeks are negative on
  every arm. **Not established.**
- **A lesson for future pre-registrations:** "positive in both halves" without a significance test
  is too weak a bar.

## Next: paper trade crypto 4h CCI (decided 2026-10-02)

The one indicator strategy that passed every pre-registered test on fresh instruments goes to a
**paper (dry-run) account, not production.** Its edge is thin, so it must earn a forward record
before any money.

**The rule, frozen exactly as validated:**

- **Signal:** CCI(20) on 4h candles, computed at the candle's close. Long when CCI crosses up
  through +100; short when it crosses down through −100.
- **Entry:** at the next 4h candle's open.
- **Stop:** 2 ATR(14) from entry; then a trailing stop 3 ATR behind the best price.
- **Exit:** the opposite signal, the stop, or 200 candles. **No take-profit.**
- **One position per coin.** Risk a fixed fraction per trade (paper: 0.5% of the paper equity).

**Where:** USD-margined perpetuals, the 12 coins of the validation (BTC ETH SOL BNB XRP DOGE ADA
AVAX LINK LTC DOT TRX), in freqtrade dry-run on Bybit. Bybit is reachable through `bytick.com`
([`../freqtrade/README.md`](../freqtrade/README.md)); Binance's API is blocked from the desk.
Taker fees and funding are charged as freqtrade does. **No live keys.** The paper run must not
touch the production hosts.

**A shadow twin:** the same signals with a coin-flip side, run alongside. The edge is measured as
the strategy minus its twin, exactly as validated.

**What to expect:** +0.06R a trade net on the fresh coins (5,372 trades, halves +0.053 / +0.065;
the coin twin was −0.018). In the original sample (BTC, ETH, SOL) its win rate was 37%, winners
averaged 1.59R and losers −0.73R; the fresh-coin run did not record these. The standard deviation
of R is estimated at about 1.4 from that payoff shape, and the first checkpoint should replace it
with the measured value. Expect long losing streaks: at a 37% win rate,
runs of 10 or more losses are normal.

**How long it takes to know:**

- 12 coins at 4h give about 1,250 trades a year.
- Confirming +0.06R at two standard errors (1.4R / √n) needs about 2,200 trades, **about two
  years.**
- A shorter record can only show that the edge is broken, not that it is real.

**Pre-registered checkpoints:**

| After | Check | Action |
|---|---|---|
| 300 trades (about 3 months) | Mean R minus the twin's below −0.15R | **Kill**: that is about 2 standard errors below the expected edge |
| 600 trades | Mean R minus the twin's ≤ 0 | **Kill**: the edge is not showing |
| 1,200 trades | Below +0.02R | Review; likely kill |
| 2,200 trades (about 2 years) | Above 0 with the 95% interval above 0, in both halves of the forward record | Eligible to be proposed for a small real allocation, as a separate decision |
| Any time | Fills or fees differ from the backtest's by more than 0.02R a trade | Stop and reconcile before continuing |

**What it is not:**

- It is not a production strategy, and it does not touch the desk's MT5 account.
- Its parameters are not tuned. Any change resets the record, because a changed rule is a new
  trial.
- It is not to be judged on its first weeks.
