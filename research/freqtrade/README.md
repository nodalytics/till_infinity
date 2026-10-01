# Freqtrade: a crypto perpetuals backtester for research

Set up 2026-10-01. [Freqtrade](https://www.freqtrade.io) backtests crypto spot and perpetual
futures. We use it **for research backtests only**: no API keys, never live, never on the
production hosts.

## Why it is here

For **bid/ask and tick research**, use MT5. The broker bridge serves every tick (`copy_ticks_range`),
bars and market depth, as deep as the broker's server keeps it. [`../harness/mt5fill.py`](../harness/mt5fill.py)
pulls them, and that includes the broker's crypto CFDs. Freqtrade is for what a broker does not
carry. Crypto exchanges publish:

| Information | Where from | In freqtrade's backtest? |
|---|---|---|
| Perpetual OHLCV, mark price | exchange API | Yes |
| Funding rate history, charged per stamp | exchange API | Yes, charged on open positions |
| Leverage tiers, liquidation price | exchange API | Yes (isolated margin) |
| Open interest, long/short ratios, taker buy/sell volume | Bybit v5 API; Binance archive `metrics` (5m) | No: merge it in the strategy (below) |
| Trades (taker side) and order-book depth | Binance archive `aggTrades`, `bookDepth`; Bybit archive | No: aggregate it ourselves first |
| Options implied volatility | Deribit (`till_infinity/prices/options.py`) | No |

Production already **collects** funding, open interest and the Deribit book live
(`till_infinity/prices/funding.py`, `positioning.py`, `options.py`). Those collectors started
recently, so they give little history. The exchanges' own histories and archives fill that gap.

Several agenda items need exactly this data: lensing, tomography, fault lines, failure mechanics,
percolation and crowding ([`../docs/agenda.md`](../docs/agenda.md)). Ideas ready to backtest
here are marked **FT** in [`../docs/ideas.md`](../docs/ideas.md).

## Network: what is reachable from the desk

Measured 2026-10-01 from the desk's own network, both inside and outside the sandbox:

| Host | Reachable |
|---|---|
| `api.binance.com`, `fapi.binance.com` | **No** (times out) |
| `api.bybit.com` | **No** (times out) |
| `api.bytick.com` (Bybit's own alternate domain) | Yes |
| `data.binance.vision` (Binance's public bulk archive) | Yes |

So:

- **Bybit works here.** `config.bybit.json` points ccxt at `bytick.com`.
- **Binance does not.** Freqtrade must load markets from the API, so `config.json` (Binance) runs only
  on a host that can reach it, such as the lab. It must never run on the production EC2 hosts.
- Binance history is still reachable through the bulk archive, read by our own harness instead.

## Layout

    research/freqtrade/
      config.json                 Binance USDT-M perps (needs a host that can reach the Binance API)
      config.bybit.json           Bybit linear perps through bytick.com
      user_data/strategies/       strategies (committed)
      user_data/data/             downloaded candles (ignored by git)
      .venv/                      freqtrade's own environment (ignored by git)

Freqtrade lives in its **own venv**, not in `pyproject.toml`: it pins its own ccxt, pandas and
numpy, which would fight the project's.

## Setup and use

    cd research/freqtrade
    uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python freqtrade

    # candles, mark and funding for BTC, ETH and SOL perps since 2024
    .venv/bin/freqtrade download-data -c config.bybit.json --timeframes 15m 1h --timerange 20240101-

    # a backtest
    .venv/bin/freqtrade backtesting -c config.bybit.json --strategy RandomBaseline --timerange 20240101-

Run downloads and backtests at `nice -n 10` so the live MT5 tunnel isn't starved. The installed
version is freqtrade 2026.9 with ccxt 4.5.84.

## The null comes first: `RandomBaseline`

Random entries on 2% of candles, a random side, a 2% stop and a 16-candle time exit. It is seeded
with a CRC of the pair, not `hash()`, which Python salts per process and so made two runs disagree.

**Smoke result** (Bybit, BTC/ETH/SOL perps, 15m, 2024-01-01 to 2026-10-01): 4,564 trades and
−467.9 USDT on 10,000. That is about **−0.11% a trade**, the round-trip taker fee (2 × 0.055%), so the
null pays its costs and nothing else, as it should. Every crypto strategy tested here must beat
this baseline on the same pairs, period, fees and funding.

## The discipline still applies

Freqtrade's own reports are not the evaluation. Ideas tested here follow
[`../docs/agenda.md`](../docs/agenda.md) ("How a program is judged"):

- **Walk forward by time and report both halves.** Do not trust `hyperopt` in-sample: every
  hyperopt epoch is a trial, and counts towards deflation.
- **Beat `RandomBaseline`** and a version run on walks we generate ourselves. Write a GARCH or
  t(3) walk as feather candles under a fake pair name.
- **Fees, plus funding at the stamps.** Freqtrade charges both. Add slippage for anything that is
  not a large-cap perp.
- **External data merges at knowledge time.** Merge open interest, long/short ratios or taker flow
  with `merge_asof` on the time each value became *known*, not the time it describes. Exchange
  metrics are often stamped at the start of their window.
- **Fills.** Freqtrade fills at the next candle's open, and its stops fill at the stop price. On
  gappy moves, model stops on wicks and with slippage ([`../docs/crash-timing.md`](../docs/crash-timing.md)).

## Backtests, 2026-10-01 ([`user_data/strategies/edges.py`](user_data/strategies/edges.py), [`report.py`](report.py))

Three pre-registered strategies on 12 Bybit perps (BTC ETH SOL BNB XRP DOGE ADA AVAX LINK LTC DOT
TRX), 15m, 2024-01 to 2026-10. Taker fee 0.055% a side; funding charged at each stamp; no
take-profit. Each strategy has a coin twin with the same bars and exits but a random side.

| Strategy | Trades | Net per trade [95% CI, days resampled] | Coin twin | Strategy − coin (2024 / 2025+) |
|---|---|---|---|---|
| **FundingFade:** after an extreme funding stamp (top or bottom 5% of 90 days), take the receiving side; stop 3 ATR; exit 24h | 2,330 | −0.178% [−0.382, +0.036] | −0.064% | **−0.114%** (−0.128 / −0.102) |
| **CoilBreakout:** compressed (range percentile ≤ 0.2), then a close beyond the 16-bar box; stop at the opposite edge, trailing 2σ; 24h at most | 19,420 | −0.247% [−0.259, −0.236] | −0.241% | −0.007% (−0.021 / +0.001) |
| **FundingStamp:** an hour either side of the stamp, on the receiving side after an extreme stamp | 3,197 | −0.089% [−0.198, +0.027] | −0.053% | −0.035% (−0.089 / +0.021) |
| *RandomBaseline* | 4,564 | −0.11% (the round-trip fee) | | |

**None beats its coin in both halves.**

- **CoilBreakout is its coin.** Taking the side of the breakout is worth nothing, which matches the
  escape study ([`../docs/expansion.md`](../docs/expansion.md)): a breakout out of compression
  commits no more than a random walk's. It loses about 0.25% a trade because 1.3-hour trades with
  tight trailing stops mostly pay two fees.
- **FundingFade collects funding and loses on price.** It received +27.5 USDT of funding over the
  trades, yet did 0.11% a trade worse than a coin in both halves: the crowd that pays extreme
  funding was, if anything, right over the next day. "Trade *with* extreme funding" is a new
  hypothesis, not a finding. It needs fresh data (the Binance archive's 2023, or 2026 onward)
  before it counts.
- **FundingStamp** also collects funding (+45.7 USDT) and loses more on price.

Run them again with:

    .venv/bin/freqtrade backtesting -c config.bybit.json --strategy CoilBreakout --timerange 20240101- --export trades
    .venv/bin/python report.py FundingFade CoilBreakout FundingStamp

## Trading *with* extreme funding: the one-shot test, 2026-10-01 ([`../harness/funding_with.py`](../harness/funding_with.py))

FundingFade's loss suggested the crowd paying extreme funding was right. That was a hypothesis
made by looking, so it got one pre-registered test on data neither venue nor year had touched:
**Binance USD-M, 12 perps, 2023.** The rule: after a stamp in the top or bottom 5% of its 90 days,
trade *with* the side that pays. Stop 3 ATR, exit after 24h, fees 0.05% a side, funding at every
stamp held.

| Rule | Trades | Net per trade [95% CI] | 2023 H1 / H2 |
|---|---|---|---|
| **With the crowd** | 1,312 | **−0.437%** [−0.769, −0.027] | −0.85 / −0.19 |
| Coin | 1,312 | −0.052% | −0.09 / −0.03 |
| Fade (the Bybit rule) | 1,312 | +0.082% [−0.152, +0.334] | +0.46 / −0.14 |
| With minus coin | | −0.385% [−0.719, −0.038] | −0.76 / −0.16 |

**Rejected.** Trading with the crowd lost in both halves and on all 12 symbols. The fade won in
early 2023, lost in late 2023, and lost on Bybit in 2024–26. **The funding effect's sign flips
from period to period, so neither side is an edge.** Funding-based direction is closed.
