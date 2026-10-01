# mt5bt: a backtester for MT5 CFDs

Built 2026-10-01. It backtests strategies on the broker's own history (FX, metals, indices,
stocks, crypto CFDs and the Deriv markets) and charges what the broker charges. It is the
MT5 counterpart of [`../freqtrade/`](../freqtrade/README.md), which covers crypto exchange data.
Research only: it never places an order.

## What it models

| | How |
|---|---|
| **Bid and ask** | MT5 bars are bid. Every bar also carries `ask_open..ask_close`, `mid_*`, `spread` (points) and `spread_price`. Bars built from ticks keep the true ask; MT5 bars rebuild it from the bar's spread |
| **Tick volume** | `tick_volume` (MT5's tick count; the only volume a CFD has) on every bar |
| **Ticks** | `fetch.py ticks` stores every bid/ask tick. `bars_from_ticks` builds bars with bid and ask OHLC, the spread's min, mean and max, and the tick count. With ticks loaded, fills walk the real ticks (`Costs.fill`) |
| **Fills** | A long buys the ask and sells the bid; a short sells the bid and buys the ask. Stops are hit by wicks on the exit side. A bar that opens beyond a level fills at the open. A bar touching both levels counts as the stop, unless ticks show the target came first |
| **Costs** | The spread (once a round trip), commission per lot per side, entry and stop slippage, extra stop slippage as a share of the stop (spike sides), and swap at the New York rollover with the triple day (production's `trading.swap`) |
| **Contract** | The broker's own symbol info, parsed as production parses it: tick size and value, contract size, minimum lot and lot step, swap terms |
| **Sizing** | Production's `trading.sizing.lots`: risk a fraction of equity, snap *down* to the lot grid, and refuse below the minimum lot. Refusals are counted, never rounded up |
| **Portfolio** | Several symbols on one clock, compounding on realised equity, `max_open`, one position per symbol, and an `allow(ts, book)` veto hook (quiet hours, rollover, news) |
| **Results** | R net of every cost, gross, the cost split, a day-bootstrap 95% CI, both halves, hit rate, money, max drawdown, exit reasons, and how many fills came from ticks |
| **Discipline** | A look-ahead audit, a random-entry null with the strategy's own geometry, and walks we generate ourselves (iid t, GARCH) with the real contract |

## Use

    # 1. data, on the lab (the bridge is shared with the live desk: spaced requests, niced)
    python research/mt5bt/fetch.py specs --symbols EURUSD,XAUUSD,"US 500"
    python research/mt5bt/fetch.py bars  --symbols EURUSD,XAUUSD --intervals 15m,1h --days 730
    python research/mt5bt/fetch.py ticks --symbols EURUSD --start 2026-09-01 --end 2026-09-08

    # 2. a backtest, audited, against 200 random-entry replays
    python research/mt5bt/bt.py --strategy research/mt5bt/strategies/donchian.py:strategy \
        --symbols EURUSD,XAUUSD --interval 15m --start 2025-01-01 --audit --null 200

    # with ticks: fills on real bid/ask ticks wherever they cover a trade
    python research/mt5bt/bt.py ... --ticks
    # or bars built from ticks (true bid/ask OHLC and tick counts)
    python research/mt5bt/bt.py ... --from-ticks --start 2026-09-01 --end 2026-09-08

    # 3. the walk control: the same strategy on 20 GARCH walks with the real contract
    python research/mt5bt/bt.py --strategy ...:strategy --walk garch --walks 20 --symbols EURUSD

    # tests
    .venv/bin/python -m pytest research/mt5bt/test_mt5bt.py -q

Data lives in `~/till_infinity/data/mt5bt.db` (`MT5BT_DB`). The bridge is `TRADING_MT5_URL`, with
`TRADING_MT5_API_KEY`. `--source seqlab` reads the lab's `$SEQLAB` bars, which have no spread, so
pass `--spread-points`. `--source csv` reads any export with the same columns. How deep the history
goes depends on what the broker's server keeps.

## A strategy

A strategy is a function from bars to signals. It sees bid, ask, mid, spread and tick volume:

    def strategy(bars, book):
        # columns: ts open high low close ask_open ask_high ask_low ask_close mid_*
        #          spread spread_price tick_volume (volume)
        return pd.DataFrame({"i": ..., "side": ..., "stop": ..., "target": ..., "hold": ...})

- `i` is the bar at whose close the signal is known; it fills at bar `i + 1`.
- `stop` and `target` are distances in price units; a target of 0 means none.
- `hold` is the most bars to hold; 0 means no limit.
- An optional `risk` column overrides the risk fraction per signal.

[`strategies/`](strategies/) has the random null and a Donchian example. The example is not a
recommendation.

## What building it taught, which applies to every backtest here

1. **A walk generator can hand out free edge.** The first walks drew each bar's return, then drew
   a path inside the bar pinned to end there. Inside the bar, price then drifted predictably
   toward the close, so a stop taken mid-bar dodged a move already coming. Random entries
   earned **+0.07R a trade on a walk**. The walks are now built forward from independent
   sub-steps, a martingale at every scale. Anyone writing a walk with intrabar paths should
   check this.
2. **Bar backtests are optimistic about stops by the overshoot.** When price jumps through a stop
   between observations, bars can only fill at the level. On walks with t(3) sub-steps,
   stop-and-time-exit trades showed **+0.09R at 16 sub-steps a bar, +0.03 at 64 and none at 256**.
   It is the discrete-monitoring constant from [`../docs/deriving.md`](../docs/deriving.md), in
   another guise. On real data:
   - use `--ticks` where ticks exist; tick fills take the price of the tick that crossed;
   - otherwise charge `--slippage-points`, and `--stop-slip-frac` on jumpy instruments (Boom/Crash
     stops fill 10-19R past the level; [`../docs/generators.md`](../docs/generators.md)).
3. **One walk is not a control.** A single 20,000-bar walk's mean R swings about ±0.07. The
   Donchian example earned +0.063R (CI excluding zero) on one GARCH walk and +0.013 ± 0.021
   across twelve. Run `--walks 20` or more.
4. **A random null on the same path doesn't control for the path.** All its draws share the
   walk's luck, so "beats 94% of random entries" on one path means little. Read
   `beats_null_share` on real data together with the walk control.
5. **The audit catches more than peeking.** The first random-entry strategy drew its sides after
   drawing one number per bar. Its sides then depended on how many bars existed, so cutting
   history changed past signals, and the audit failed it. It was right to.

## Limits

- **Tick value is today's.** Money P&L on a JPY- or CHF-quoted symbol uses today's conversion
  rate. R does not depend on it, and R is the unit this desk judges in.
- **Swap counts charges only.** A credited side is treated as free, which is conservative.
- **MT5 stores one spread per bar** (the lowest, on most servers). In bar mode, raise
  `--spread-mult` or use ticks.
- **Stops and targets are measured from the actual fill,** not from the signal bar's close.
- **One position per symbol is decided before sizing.** A signal refused for lot size or
  `max_open` can still have blocked a later signal on that symbol.
- **Market orders only.** Resting limit and stop entries are not modelled yet. Limit fills carry
  the winner's curse ([`../docs/limitfills.md`](../docs/limitfills.md)), so model them with care.
