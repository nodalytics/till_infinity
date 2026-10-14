# EMAs and slopes as signals, and why tick data is out of reach

Two questions: do EMA and slope signals carry direction, and what is their AUC.
Plus the answer to a third - whether tick data can be fetched at all - because
it decides the resolution everything else here runs at.

## Tick data is not reachable without touching the live path

The HTTP bridge exposes **no tick history**. Its routes are quotes
(`/symbols/ticks/{symbol}`, which returns the *current* bid and ask), bars
(`/symbols/rates/pos`), positions, orders, account and terminal info. There is
no `copy_ticks` equivalent.

There is a second path that would work. `trading/venues/mt5_rpyc.py` proxies
**the MetaTrader5 module itself** out of the Wine prefix over RPyC, so
`conn.modules.MetaTrader5` answers with the real module and `copy_ticks_range`
is reachable without any bridge change. **It is not running** - nothing is
listening on 18812, and no `TRADING_RPYC_HOST` is configured.

So tick history costs one of two changes, and both touch the live trading path:

- **start the RPyC server inside the Wine prefix** on the lab, which is the
  host that also runs the live terminal;
- **add a tick-history route to the bridge**, which is the component whose
  rebuild is already known to break MT5 IPC - an unpinned `mt5setup` against a
  pinned `MetaTrader5==5.0.5640` is how that failed before, and build 6204 does
  not work where 6140 does.

Neither is a change to make as a side effect of a measurement. A third option
costs nothing and gives nothing now: polling the live tick route accumulates
history going forward.

So this runs at **3m**, the finest bars in the cache, and 15m.

## The signals, and what was missing

`reversion_clock.py` used a rolling least-squares line as a **centre** and never
scored the **slope**. Those are different claims - a centre asks how far from
fair, a slope asks which way it is going - and the second is what a regression
channel or an EMA crossover actually trades.

- **slope t** - the slope over its own standard error. A raw slope is in price
  units a bar and cannot be compared across instruments or windows; its
  t-statistic can.
- **ema gap** - distance from a slow EMA in deviation units.
- **ema cross** - fast EMA minus slow, in deviation units, as a continuous
  score rather than a binary event.
- **ema slope** - the EMA's own change, in deviation units.

Scored for momentum: above 0.5 means the signal's direction is where price then
goes.

## The result: a properly powered null

3m, a 24-hour span, held 3 bars:

| class | kind | n | auc | twin | edge | +0.02σ | +0.05σ | +0.1σ |
|---|---|---|---|---|---|---|---|---|
| fx majors | slope t | 92,211 | 0.4950 | 0.4952 | -0.0002 | 0.5106 | 0.5363 | 0.5699 |
| fx majors | ema cross | 92,211 | 0.4938 | 0.4952 | -0.0014 | 0.5091 | 0.5345 | 0.5668 |
| fx crosses | slope t | 92,211 | 0.5005 | 0.5013 | -0.0008 | 0.5173 | 0.5428 | 0.5776 |
| fx crosses | ema gap | 92,211 | 0.4939 | 0.4986 | -0.0047 | 0.5102 | 0.5349 | 0.5680 |
| metals | slope t | 26,346 | 0.4976 | 0.5055 | -0.0078 | 0.5112 | 0.5336 | 0.5683 |
| synth volatility | slope t | 52,692 | 0.5019 | 0.5033 | -0.0014 | 0.5330 | 0.5789 | 0.6478 |
| synth step | slope t | 52,692 | 0.5051 | 0.4981 | +0.0070 | 0.5170 | 0.5204 | 0.5471 |
| synth dex | slope t | 52,692 | 0.5194 | 0.5216 | -0.0022 | 0.5310 | 0.5480 | 0.5761 |

**Every edge is inside +-0.008, and the power line is why that means
something**: a planted drift of **0.02 standard deviations** already lifts the
AUC from 0.495 to 0.511, and 0.05 to 0.536. The test could comfortably see a
drift far smaller than anything these ideas claim, and it sees nothing.

`synth dex` is worth a note: its raw AUC is 0.519, the highest in the table,
and its **twin reads 0.522**. Genuine autocorrelation in a synthetic that the
surrogate reproduces, which is what a surrogate is for.

## The one coherent thread: metals trend

Across spans at 15m the edges are flat for FX and **growing for metals**:

| class | kind | 24h | 2d | 1w |
|---|---|---|---|---|
| metals | slope t | +0.0031 | +0.0123 | **+0.0159** |
| metals | ema cross | +0.0025 | +0.0105 | **+0.0178** |
| metals | ema slope | +0.0006 | +0.0074 | +0.0161 |
| metals | ema gap | -0.0027 | +0.0032 | +0.0119 |
| fx crosses | slope t | -0.0065 | -0.0076 | -0.0008 |
| fx crosses | ema gap | -0.0066 | -0.0071 | -0.0052 |
| fx majors | slope t | -0.0023 | +0.0001 | +0.0025 |

Four things make this the one reading worth naming. It is **positive for
metals** where FX crosses are negative; it **grows monotonically with the
span**; it is **consistent across all four signals**, which are different
constructions of the same idea; and it **agrees with the reversion measurement**
in `mean-reversion-signals.md`, where metals were the one class with a
*negative* reversion edge - at -0.0065 at 100 bars and -0.0159 at 500. Two
independent harnesses saying metals trend while FX crosses revert.

It is still **not established**. The largest figure is +0.018 of AUC, metals is
two instruments, and this exploration has now spent well over a hundred cells.
What it is good for is a prior: if anything in this family is worth another run,
it is trend on metals at a weekly window, not reversion on FX at a daily one.
