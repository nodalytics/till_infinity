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
