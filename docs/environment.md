# Environment variables

Every setting Till Infinity reads from the environment, grouped by what reads it. The list was taken
from the code, not from memory: every `os.environ` read, every `utils/env.py` and
`strategies/config.py` helper call, and every module-level switch.

**206 variables are read by literal name, plus four families whose name is built at runtime.** This
document names 256, so about ninety of the rows below belong to code that retired with the Nautilus
port and are kept under their own headings rather than deleted - an old `.env` has them in it and a
reader needs to be able to find out that they do nothing. Where a section is dead it says so in its
first line. Re-audited 2026-11-01.

Defaults are **what the code actually resolves** when the variable is unset.

## How settings are read

- **Real environment first**, but no longer by a mechanism of ours: nothing loads `.env` in Python
  any more. Docker does it - `env_file` in `docker-compose.yml`, resolved before the `environment:`
  block, and `--env-file` in `deploy.sh`. So a variable set in the process environment still wins
  over the file, and a stray `.env` still cannot override a deployment, because Docker orders them
  that way rather than because `load_dotenv` was asked to.
- **Read once, at start.** Config classes are built when the node starts. Two switches are read at
  *import* time instead - `STRUCTURES_ROLLOVER_MASK` in `domain/rollover.py` and `TILL_STATUS_PATH`
  in `node/status.py` - which makes them unsettable from inside a running process. **Every change
  needs a restart.** Nothing here is re-read live.
- **Booleans.** One helper, `utils/env.py`'s `flag`. Off is an empty value, `0`, `false`, `no` or
  `off`; **anything else that is set is on**, including `yes`, `maybe` and a typo. That is
  deliberate - the module docstring argues it - and it means a misspelled value enables rather than
  disables.
- **Durations** are seconds unless the name says otherwise. Volatility distances (`*_VOL`) are in the
  production volatility unit, and money is in the account's currency.

### Two variables where the node and `Settings` disagree

`node/desks.py` decides what the node runs and `strategies/config.py`'s `Settings` carries the
trading knobs, and three variables are read by both with **different defaults**. The node's is the
one that takes effect on what gets built:

| | `node/desks.py` | `strategies/config.py` |
|---|---|---|
| `TRADING_STRATEGIES` | `statespace-surprise` | `level-scalp` |
| `TRADING_SYMBOLS` | *(none - unset builds nothing)* | `gold,btc` |
| `TRADING_DESKS_PER_CORE` | `8` | Desks a core may carry; the rest are clipped with a warning. Two cores at two rules a symbol is eight symbols. | restart |
| `TRADING_INTERVALS` | `15m` | every timeframe |

`TRADING_SYMBOLS` unset means the node raises rather than starting empty, which is deliberate: a
node that connects, reconciles, reports up and trades nothing is a failure this desk has had three
times.

### In production

The instance's environment file is `/home/ubuntu/till.env`, written once and passed to the container
with `--env-file` by `deploy.sh`. See [deployment.md](deployment.md), "Moving to another instance".
To change a setting:

1. edit `/home/ubuntu/till.env` on the instance;
2. restart the container (`docker restart till-infinity`, or redeploy) - a `docker restart` keeps
   the old value and still looks healthy if the file was not passed again, so a recreate is the
   safer move;
3. check the start-up log. `utils/env.py` warns on a value it cannot parse, and the node logs what
   it resolved for the venues and the desks.

`deploy.sh` never rewrites the file, so an edit survives deploys.

### Reading the "Change" column

| Mark | Meaning |
|---|---|
| **restart** | Safe to change; takes effect on restart. |
| **trades** | Changes what the desk trades, or how. Read the linked research first. |
| **state** | Points at stored state or data. Changing it starts that component from empty or strands the old files. |
| **secret** | A credential. Never commit it, paste it, or put it in a card. |
| **live** | Read while running; no restart needed. |

---

## Core: the node, its actors, logging

`node/live.py` builds the node from these. The four `*_OFF` switches are the shape worth noticing:
the journal, the status heartbeat and the notifier are **added by default and switched off by
name**, because a node that trades without a record is the state this desk was actually in after
the port - both actors written, neither registered - and an opt-in record is a record nobody turns
on. Statespace is the opposite: it is added only when `STATESPACE_BARS` names something, because an
actor subscribed to nothing is a fold that never runs pretending to be a model that does.

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADER_ID` | `TILL-001` | The Nautilus trader id, stamped on everything the node emits. | restart |
| `TRADING_VENUES` | `mt5` | Which venues the node registers clients for. A name other than `mt5` is resolved against Nautilus's own adapters by shape. | restart |
| `TRADING_LIVE` | *(unset)* | **The arming switch, and the only one.** Unset, the risk engine sits in `HALTED`: the node connects, reconciles, subscribes and computes, and every order is denied inside the engine, below the strategies and above the client. No paper book is substituted. | trades |
| `RISK_ORDER_RATE` | `10/00:00:01` | Nautilus's order submit rate cap, as `count/HH:MM:SS`. | trades |
| `JOURNAL_OFF` | *(unset: on)* | Set to stop registering the journal actor. | restart |
| `JOURNAL_DB` | `.data/journal/journal.db` | Where the journal actor writes. | state |
| `JOURNAL_FLUSH_SECONDS` | `5.0` | How often the journal actor flushes. | restart |
| `STATUS_OFF` | *(unset: on)* | Set to stop registering the status heartbeat. The container's `HEALTHCHECK` then has no source and can only prove a process is alive, which Docker already knew. | restart |
| `TILL_STATUS_PATH` | `/app/.data/status.json` | Where the heartbeat writes and `python -m till_infinity.node.status` reads. Read at import time. Set by `docker-compose.yml`. | state |
| `ALERTS_OFF` | *(unset: on)* | Set to stop registering the notifier. | restart |
| `ALERTS_MINIMUM_LEVEL` | `WARNING` | The lowest level the notifier delivers. | restart |
| `STATESPACE_BARS` | *(unset: no statespace)* | Bar types the statespace actor folds, space- or comma-separated. Unset means the actor is **not added at all**. | restart |
| `STATESPACE_INDICATORS` | *(empty)* | Indicators the statespace actor registers. | restart |
| `NODE_CONNECT_TIMEOUT` | `240` | Seconds to wait for the clients to connect. **Miss it and the node starts no strategy at all** - Nautilus returns from its start sequence before `trader.start()` - so this is sized against the measured 78-85s this venue takes to load 728 instruments, not against the usual case. | restart |
| `NODE_START_DEADLINE` | `420` | Seconds before a node that never started its trader leaves the process, so the restart policy replaces it. `0` disables. | restart |
| `NODE_RECONCILE_TIMEOUT` | `30` | Seconds to wait for execution reconciliation. | restart |
| `NODE_PORTFOLIO_TIMEOUT` | `30` | Seconds to wait for the portfolio to initialise. | restart |
| `NODE_DISCONNECT_TIMEOUT` | `30` | Seconds to wait on a clean stop. | restart |
| `NODE_POST_STOP_TIMEOUT` | `10` | Seconds after the stop. Positions are **left alone** - flattening is never implicit, because a restart for a code change must not close a book. | restart |
| `LOG_LEVEL` | `INFO` | Nautilus's own log level, passed to `LoggingConfig`. Separate from `TILL_LOG_LEVEL`, which only reaches this project's own loggers. | restart |
| `TILL_LOG_LEVEL` | `INFO` | Level for `utils/logging.py`: `DEBUG`, `INFO`, `WARNING` or `ERROR`. Nothing in the package calls `setup_logging`, so this is read only by a script or a test that does. | restart |
| `TILL_LOG_FILE` | *(unset)* | Also write JSON-lines logs to this file. Same caveat. | restart |
| `TILL_LOG_JSON` | *(unset)* | `1` writes JSON lines to the console instead of rich text. Same caveat. | restart |
| `ALLOW_BACKTEST_HERE` | *(unset)* | Lets a backtest build on a host named in `node/backtest.py`'s `TRADING_HOSTS`. The refusal exists because a backtest is a burst of exactly the work the live node needs cores for, and a research job has already silently starved the desk on a two-core box. | restart |
| `CORPUS_DIR` | `~/till-data/catalog` | Where `node/backtest.py` looks for a bar catalogue. | state |

### Per-venue overrides

Four separate schemes build a variable name at runtime, so none of them can be listed above:

| Pattern | Read by | Example |
|---|---|---|
| `<NAME>_<VENUE>`, tried before the bare `<NAME>` | `node/live.py` | `TRADING_MT5_URL_DERIV` beats `TRADING_MT5_URL` |
| `TRADING_SYMBOLS_<VENUE>` | `node/desks.py` | `TRADING_SYMBOLS_BINANCE` |
| `TRADING_VENUE_KIND_<VENUE>` | `node/venues.py` | `TRADING_VENUE_KIND_DERIV=mt5` |
| `TRADING_<VENUE>_API_KEY`, `_API_SECRET`, `_API_PASSPHRASE`, `_ACCOUNT_TYPE` | `node/venues.py` | `BINANCE_API_KEY` is Nautilus's own name and is read by its adapter, not by this |

A second venue is added by naming what differs rather than by re-stating everything. The venue is
upper-cased into the name, so a mixed-case variable is missed silently - which, for a credential,
means connecting to the wrong account.

### Retired: which services ran, and the bus

**Nothing reads any of these.** They chose which of the six services `till-infinity run` started,
and the CLI, the services and the Redis bus retired together on 2026-11-01. Listed so that an
inherited `.env` can be read; six of them are uncommented in `.env.example` and are inert.

| Variable | What it did |
|---|---|
| `PRICES_ENABLED`, `NEWS_ENABLED`, `NOTIFICATIONS_ENABLED`, `JOURNAL`, `TRADING_ENABLED` | Whether `run` started each service. `TRADING_ENABLED` in particular: the arming switch is now `TRADING_LIVE` alone. |
| `BACKFILL_ON_START` | Pulled history at start when the store held too little for levels to form. |
| `SYMBOLS`, `INTERVALS` | Narrowed collection. The node's equivalents are `TRADING_SYMBOLS` and `TRADING_INTERVALS`. |
| `TILL_REDIS_URL` | The Redis URL for the bus. Nothing imports Redis now; Nautilus's bus is in-process, with its own optional Redis backing. Compose never set this, despite what this document used to say. |
| `STACK_HEARTBEAT`, `STACK_STATUS_FILE` | The stack's heartbeat interval and status file. `TILL_STATUS_PATH` replaced the second; the interval is no longer configurable. |

## Retired: Prices

**Nothing reads any of these.** The `prices` package retired to
`research/retire/prices/` with the CLI on 2026-11-01 and the node subscribes to the venue instead,
keeping bars in the Nautilus cache rather than a SQLite store. The one exception is
`PRICES_BROKER_SYMBOLS`, which is live and is under
[Switches, strategies, universe](#switches-strategies-universe) where it belongs - it never
configured a collector, it says which broker-only instruments are registered as tradable.

| Variable | Default | What it did | Change |
|---|---|---|---|
| `PRICES_DIR` | `.data/prices` | Directory of the price store. | state |
| `PRICES_DB` | `$PRICES_DIR/prices.db` | The SQLite price store itself. Structures and trading read it too. | state |
| `PRICES_SOURCES` | *(all bar sources)* | Bar providers to poll, comma-separated. | restart |
| `PRICES_QUOTE_SOURCES` | *(all quote sources)* | Quote providers to poll. | restart |
| `PRICES_BROKER_SYMBOLS` | *(empty)* | **Live, and the only variable left in this section.** Broker-only instruments (e.g. `Volatility 75 Index,Step Index`) registered as tradable. It never configured a collector, whatever its prefix suggests: `Settings.from_env` passes it to `register_broker_instruments`. Empty by default, because it needs a bridge. See [research/docs/catalogue.md](../research/docs/catalogue.md) on which to carry. | restart |
| `PRICES_BROKER_LABEL` | `broker` | Source label the broker's bars are stored under. | state |
| `PRICES_CYCLE_S` | `60` | Seconds between bar sweeps. | restart |
| `PRICES_LIVE_BARS` | `300` | Bars requested per sweep. | restart |
| `PRICES_BACKFILL_BARS` | `5000` | Bars requested per series by a backfill. | restart |
| `PRICES_QUOTE_POLL` | `15` | Seconds between quote snapshots. | restart |
| `PRICES_QUOTE_CONCURRENCY` | `8` | Parallel quote requests. | restart |
| `PRICES_YAHOO_CONCURRENCY` | `4` | Parallel Yahoo requests. | restart |
| `PRICES_TV_CONCURRENCY` | `6` | Parallel TradingView requests. | restart |
| `PRICES_RETRIES` | `3` | Retries per failed request. | restart |
| `PRICES_RETAIN_QUOTE_DAYS` | `14` | Days of quotes the collector keeps as it runs. Quotes only, and no VACUUM. | restart |
| `PRICES_RETAIN_EVERY_S` | `3600` | How often that trim runs. | restart |
| `PRICES_USER_AGENT` | *(browser UA)* | HTTP user agent for providers. | restart |
| `PRICES_TV_WS_URL` | TradingView socket URL | TradingView websocket endpoint. | restart |
| `PRICES_TV_ORIGIN` | `https://data.tradingview.com` | Origin header for TradingView. | restart |
| `PRICES_TV_TOKEN` | `unauthorized_user_token` | TradingView auth token; the default is the anonymous one. | **secret** |
| `PRICES_CCXT_EXCHANGE` | `binance` | Exchange the crypto source talks to, by ccxt's name. | restart |
| `PRICES_CCXT_EXCHANGES` | *(empty)* | Several exchanges, ranked against each other. | restart |
| `PRICES_CCXT_MARKET_TYPE` | `swap` | `swap` for perpetuals, `spot` for spot. | restart |
| `PRICES_CCXT_SWAPS_ONLY` | `1` | Only perpetual swaps. | restart |
| `PRICES_CCXT_TOP` | `0` (off) | Pairs to carry after ranking by 24h quote volume. This sets the size of the crypto book. | restart |
| `PRICES_CCXT_MIN_VOLUME` / `_MIN_DAYS` / `_MAX_SPREAD` / `_MIN_PRICE` / `_MIN_RANGE` | `0` (off) | Floors under the ranking. All off at zero, deliberately. | restart |
| `PRICES_CCXT_QUOTES` | *(any)* | Quote currencies to consider. | restart |
| `PRICES_SPREADS` | `0` | Build constructed spread series each cycle. It can add hundreds of derived feeds. | restart |
| `PRICES_SPREAD_KINDS` | `cross` | Which kinds of spread to construct. | restart |
| `PRICES_SPREAD_BASE` | `1m` | Interval spreads are computed at before bucketing. | restart |
| `PRICES_SPREAD_MIN_SHARED` | `1000` | Stored bars each leg needs before a pair is built. | restart |
| `PRICES_SPREAD_CROSS_SOURCE` | `0` | Allow legs from two providers. Off: two clocks skew the spread. | restart |
| `PRICES_SPREAD_PAIRS` | *(empty)* | Exact spreads to build, `name=feed@VENUE-feed@VENUE`, the same syntax as `STRUCTURES_SPREAD_QUOTES`. | restart |

## News

| Variable | Default | What it does | Change |
|---|---|---|---|
| `NEWS_DIR` | `.data/news` | Directory of the news store. | state |
| `NEWS_DB` | `.data/news/news.db` | The news store, read by `adapters/news/`. `structures` read it for the monetary-policy series and is retired; no node registers the news adapter yet, so nothing writes this today. | state |
| `NEWS_SOURCES` | `rss,forexfactory,tradingview,headlines,imf` | Providers to poll. | restart |
| `NEWS_POLL` | `300` | Seconds between headline passes. | restart |
| `NEWS_CAL_POLL` | `900` | Seconds between calendar passes. | restart |
| `NEWS_CAL_BACK_DAYS` / `NEWS_CAL_FORWARD_DAYS` | `3` / `14` | Calendar window around now, in days. | restart |
| `NEWS_CONCURRENCY` | `6` | Parallel requests. | restart |
| `NEWS_RETRIES` | `3` | Retries per failed request. | restart |
| `NEWS_USER_AGENT` | *(browser UA)* | HTTP user agent. | restart |
| `FRED_API_KEY` | *(empty)* | Needed for the `fred` source, which refuses to poll without it. | **secret** |
| `FRED_SERIES` | *(all thirty)* | FRED series to fetch. | restart |

## Retired: Structures

**Nothing reads any of these except `STRUCTURES_ROLLOVER_MASK`**, which survives in
`till_infinity/domain/rollover.py` and has its own subsection below. `structures` retired on
2026-10-29 to `research/retire/structures/`, with the eight level-scalper strategies that read it;
`statespace/` is the successor and its own variables are under
[Core](#core-the-node-its-actors-logging) and in `statespace/config.py`.

### Service and levels

| Variable | Default | What it does | Change |
|---|---|---|---|
| `STRUCTURES_DIR` | `.data/structures` | Where the engine's state is saved between runs. | state |
| `STRUCTURES_FEEDS` | `$SYMBOLS` | Feeds the engine keeps state for. Empty admits whatever arrives. | restart |
| `STRUCTURES_WARM` | `1` | Seed levels from stored price history on a cold start. | restart |
| `STRUCTURES_WARMUP` | `60` | Readings before an anomaly score means anything. | restart |
| `STRUCTURES_WINDOW` | `1000` | Bars kept per series, and bars replayed on a warm start. The first number to raise if the instance grows. | restart |
| `STRUCTURES_FINE_WINDOW` | `1500` | 1m bars kept for refining origins (about a day). | restart |
| `STRUCTURES_FORGET_FEED` | `604800` (7 days) | Seconds of silence before a feed's state is dropped. | restart |
| `STRUCTURES_SAVE_S` | `300` | Seconds between state saves. | restart |
| `STRUCTURES_FORMATION` | `pip,run,origin,profile,wick,vwap,gap,round` | How swings are found, as a list of drawing passes. | trades |
| `STRUCTURES_SIGMA` | `4` | Per-venue anomaly cutoff, in sigma. | restart |
| `STRUCTURES_QUANTILE` | `0.999` | Joint-model anomaly cutoff. | restart |
| `STRUCTURES_COOLDOWN_S` | `900` | Seconds before the same finding is announced again. | restart |
| `STRUCTURES_ALERT_LEVELS` | `1` | Actionable level calls reach a person without an agent in between. Off, with agents off, publishes to nobody. | restart |
| `STRUCTURES_DIRECT` | `1` | Alert directly on venue faults. | restart |
| `STRUCTURES_DIRECT_DEV_BPS` | `100` | Deviation, in bps, at which a venue fault alerts directly. | restart |
| `STRUCTURES_CHARGE_SPREAD` | `1` | Charge the measured spread against every level call before judging it. | trades |
| `STRUCTURES_MACRO` | `1` | Fold monetary policy onto level calls and emit it as its own shape. | restart |
| `STRUCTURES_VOL_LEARNER` | `0` | The learned volatility forecaster. Off until measured live. | restart |
| `STRUCTURES_SPREAD_QUOTES` | *(off)* | Constructed spreads to price from quotes, same syntax as `PRICES_SPREAD_PAIRS`. | restart |
| `STRUCTURES_SPREAD_SKEW_S` | `2.0` | How far apart two legs' quotes may be and still count as simultaneous. | restart |

### Volatility, the envelope and forecasts

| Variable | Default | What it does | Change |
|---|---|---|---|
| `STRUCTURES_IMPLIED` | `1` | Fold implied volatility (VIX) into the volatility estimate; measured to win. | restart |
| `STRUCTURES_IMPLIED_TICKER` | `^VIX` | The implied-volatility ticker. | restart |
| `STRUCTURES_IMPLIED_POLL` | `3600` | Seconds between implied-vol fetches. | restart |
| `STRUCTURES_IMPLIED_TIMEOUT` | `10` | Fetch timeout, in seconds. | restart |
| `STRUCTURES_STATED` | `0` | The name-stated volatility member for Deriv indices. Off until measured live. | restart |
| `STRUCTURES_PROJECTION` | `0` | The exact-law forward cone for Deriv synthetics, published and calibrated. Off until measured live. The envelope's own law path (Volatility/Jump/Step) does not need it. | restart |
| `STRUCTURES_VOL_CLOCK` | `1` | Scale the envelope's unit by the hour of the week: FX on New York's clock (outside the boosted 15m), and crypto. It also drives the "this hour is historically N× average volatility" card line (FX, metals, crypto). [calendar-returns.md](../research/docs/calendar-returns.md) | restart |
| `STRUCTURES_ENVELOPE_MONDRIAN` | `0` | Key the envelope's AgACI correction by the ZMA stretched state, once a bucket has 200 outcomes of its own. It closes 1-2 points of coverage gap when price is stretched, at equal or better pinball ([zma-conformal.md](../research/docs/zma-conformal.md)). **Off by default: it roughly triples each series' envelope state (about 65 KB to 189 KB).** **Switching Mondrian on is one setting once memory headroom is confirmed**: `STRUCTURES_ENVELOPE_MONDRIAN=1` and a restart. See [deployment.md](deployment.md), "Features that wait on memory headroom". | restart |
| `TI_MODELS_DIR` | `.data/models` | **Read by nothing.** It pointed at the frozen offline models - the shock forecaster, the boosted FX envelope, the touch models - which the engine preferred over the copy shipped in `till_infinity/models/`. Neither the directory nor the reader exists now; see [Retired: models and retraining](#retired-models-and-retraining). | state |

### Rollover mask - live

The one variable in this section the node still reads, at **import** time in
`domain/rollover.py`, which means it cannot be changed from inside a running process.

| Variable | Default | What it does | Change |
|---|---|---|---|
| `STRUCTURES_ROLLOVER_MASK` | `1` | For FX only, in 16:55-17:10 New York: no touch opens or resolves, the bar's wick is cut to its body, and records learned before the mask are faded once. [rollover.md](../research/docs/rollover.md) | trades |

### ZMA (the z-score around a moving average)

| Variable | Default | What it does | Change |
|---|---|---|---|
| `STRUCTURES_ZMA` | `1` | Record and publish the z-score. It costs one array pass a bar. | restart |
| `STRUCTURES_ZMA_ACTS` | `0` | Let the z-score influence decisions in structures. Off until its record justifies it. | trades |
| `STRUCTURES_ZMA_RECORD` | `.data/structures/zma.pkl` | The z-score's scored record, kept in its own file so deploys don't reset it. | state |

### Cycles

| Variable | Default | What it does | Change |
|---|---|---|---|
| `STRUCTURES_CYCLES` | `1` | Record and surface the cycle model. | restart |
| `STRUCTURES_CYCLES_ACT` | `0` | Let the cycle depth head cap anything. Keep off. Its skill is now judged against the same head on walks ([zeroskill.md](../research/docs/zeroskill.md)). | trades |
| `STRUCTURES_CYCLES_ATTENTION` | `1` | Attention weighting across cycle arms, at the measured temperature. | restart |
| `STRUCTURES_CYCLES_WEIGHTS` | `.data/structures/cycles.pkl` | Where the cycle weights live. | state |

## Trading

Trading sends a real order only with `TRADING_LIVE=1`. There is no second switch: `TRADING_ENABLED`
gated whether `till-infinity run` started the trading service at all, and retired with it, so
`TRADING_LIVE` is now the whole arming decision. Most sizing and gate values are justified in
[research/docs/settings.md](../research/docs/settings.md) unless another doc is named. The named plan
`TRADING_RISK_PLAN` sets a bundle of limits, and any limit set individually wins over it; it is
applied in `Settings.from_env` rather than by the node, because `from_env` runs in several live
places and a node applying a plan to its own instance would leave the others on the defaults.

### Switches, strategies, universe

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADING_LIVE` | *(unset)* | **The only setting that sends a real order.** Without it the Nautilus risk engine sits in `HALTED` and every order is denied inside it. There is no paper book to fall back to - that went with `service.py` - so unarmed means computing and not trading, not trading pretend. Also read by the health probe, which reports it as `armed`. | trades |
| `TRADING_STRATEGIES` | `statespace-surprise` ⚠ | Decision rules to run, by registered name, comma-separated. **Two defaults:** `node/desks.py` resolves `statespace-surprise` and is what builds the node; `strategies/config.py` resolves `level-scalp`. An unknown name now raises rather than running nothing. Set it explicitly. [triage.md](../research/docs/triage.md) found no strategy with an edge. | trades |
| `TRADING_STYLE` | `both` | `scalp`, `swing`, `both` or `none`. | trades |
| `TRADING_SYMBOLS` | *(none)* ⚠ | What to trade. **Two defaults:** `node/desks.py` has none, so unset builds no desks and the node refuses to start; `strategies/config.py` resolves `gold,btc`. Separate names with commas - a space-separated `Volatility 75 Index` is torn apart, and `desks.py` raises on a bare number rather than quoting an instrument that does not exist. Per venue with `TRADING_SYMBOLS_<VENUE>`. | trades |
| `TRADING_INTERVALS` | `15m` ⚠ | Timeframes to trade. **Two defaults:** `node/desks.py` resolves `15m` and takes the first entry as the bar type; `strategies/config.py` resolves every timeframe. | trades |
| `TRADING_PARALLEL` | `0` | Let every strategy that wants a signal take it, not just the first in order. | trades |
| `TRADING_EVALUATE_ALL` | `0` | Ask every strategy about every signal and record what each would have done. One still trades. | restart |
| `TRADING_CONSENSUS_MIN` | `2` | Strategies that must want the same side before the trade is rebuilt from their joint ask; 0 or 1 disables it. | trades |
| `TRADING_DIR` | `.data/trading` | Where open positions' high-water marks and the day's state live between restarts. | state |
| `TRADING_MAGIC` | `777701` ⚠ | One number the bridge stamps to tell this desk's orders from a human's. It is **no longer how a strategy is identified** - that is Nautilus's `strategy_id`, assigned by the framework and carried on every order, fill and position, which is why being off by one no longer relabels every strategy as its neighbour. Per venue as `TRADING_MAGIC_<VENUE>`. It reached nothing until 2026-11-01: `node/live.py` passed the constant's name, `DEFAULT_MAGIC`, where the variable name belongs, so the documented knob was inert and the live one was undocumented. Don't change with positions open. | state |

### Risk and sizing

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADING_RISK_PLAN` | `standard` | Named plan: `conservative`, `standard` or `aggressive`. | trades |
| `TRADING_RISK_FRACTION` | `0.0025` | Fraction of equity risked per trade. | trades |
| `TRADING_MAX_RISK_MONEY` | `0` (off) | Hard cap on money risked per trade, whatever equity says. | trades |
| `TRADING_ACCOUNT_EQUITY` | `0` | Equity to size from when the venue can't be asked. The HTTP bridge requires it. **A wrong number mis-sizes every trade.** | trades |
| `TRADING_DAILY_LOSS_FRACTION` | `0.03` | Stop for the day after losing this share of opening equity. | trades |
| `TRADING_DRAWDOWN_HALT_AT` | `0` (off) | Drawdown from peak at which size ramps to its floor. | trades |
| `TRADING_MAX_POSITIONS` | `4` | Open positions across everything. | trades |
| `TRADING_MAX_PER_SYMBOL` | `1` | Open positions per instrument. | trades |
| `TRADING_MAX_CURRENCY_EXPOSURE` | `0.005` | Money at risk on one currency across both legs of every position, as a share of equity; 0 off. | trades |
| `TRADING_CROWDING_SHARE` | `0` (off) | Size kept per open position sharing a currency leg the same way. | trades |
| `TRADING_VOLATILITY_TARGET_BPS` | `0` (off) | Volatility the book is sized for; above it, size scales down. | trades |
| `TRADING_INTERVAL_WEIGHT` | `1m=0.8,3m=0.8,5m=0.8,15m=0.95` | Risk multiplier per entry timeframe, `interval=weight` pairs. The measured weights from `scaling.by_interval`. This used to resolve to *no weights* when unset, so production sized every timeframe at full; `from_env` falls back to the dataclass now. | trades |
| `TRADING_REGIME_BAND` / `TRADING_REGIME_FLOOR` | `0` (off) / `0.5` | Size by regime edge, and the most it may reduce. | trades |
| `TRADING_SPIKE_ABOVE` / `TRADING_SPIKE_FLOOR` | `0` (off) / `0.5` | Cut size to the floor when the true-range percentile is at or above this. Off: [session-switch.md](../research/docs/session-switch.md). | trades |
| `TRADING_EDGE_FULL_AT` | `0` (off) | Net edge, in vol units, that earns full size. | trades |
| `TRADING_TREND_SIZING` | `0` (off) | How far trend context may move size either side of 1. | trades |
| `TRADING_UNCONFIRMED_SIZE` | `1.0` (off) | Size share when momentum isn't confirming. | trades |
| `TRADING_STOP_SLIPPAGE` | `0` | Extra cost of a stopped trade beyond the stop, as a share of risk, for sizing. | trades |
| `TRADING_STOP_OVERSHOOT` | measured per-feed table | What a stop really costs per instrument, in R, `feed[.side]=multiple`. | trades |

### Entry gates and vetoes

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADING_MIN_PROBABILITY` | `0.58` | Floor on the signal's own probability. | trades |
| `TRADING_PROBABILITY_PERCENTILE` | `0` (off) | Gate on the signal's place in its own direction's probability distribution. | trades |
| `TRADING_MIN_EDGE` | `0.15` | Floor on \|edge\|. It had to sit above `reactions.MIN_EDGE` to ever fire; `reactions` retired with `structures/` and the pairing cannot be checked against live code any more. | trades |
| `TRADING_MIN_BASE_RATE` | `0` (off) | How often the level must hold unconditionally. | trades |
| `TRADING_MIN_RR` | `0` (off) | Minimum reward-to-risk from the quoted entry, spread included. | trades |
| `TRADING_MIN_EFFICIENCY` | `0` (off) | Refuse when the market around the level is choppier than this. | trades |
| `TRADING_MAX_SPREAD_FRACTION` | `0.25` | Refuse a trade whose spread eats this much of its target. | trades |
| `TRADING_MAX_SPREAD_RISK_FRACTION` | `0.16` | The same against the risk. It buys only cost, and its setting is right: [vetoes.md](../research/docs/vetoes.md). | trades |
| `TRADING_MAX_SPREAD_RATIO` | `2.5` | How much more than the venue group's spread we may pay. | trades |
| `TRADING_MAX_DISLOCATION_BPS` | `8` | How far our broker's quote may sit from the venue median. | trades |
| `TRADING_MAX_SWAP_FRACTION` | `0.25` | Refuse a hold whose expected overnight swap, over the 17:00 New York rollovers it crosses (triple on the broker's triple day), exceeds this share of its target; 0 off. [carry.md](../research/docs/carry.md) | trades |
| `TRADING_QUIET_HOURS` | *(empty)* | UTC hours in which nothing opens, e.g. `20,21,22,23`. Global. Prefer the FX-only vetoes below. | trades |
| `TRADING_FX_QUIET_NY` | `16-19` | FX only, on New York's clock: no entries in these hours (end exclusive), the close and the rollover. Empty turns it off. [vetoes.md](../research/docs/vetoes.md) | trades |
| `TRADING_FX_SUNDAY_OPEN_MIN` | `60` | FX only: no entries this many minutes after the Sunday 17:00 New York open; 0 off. | trades |
| `TRADING_NEWS_BEFORE_S` / `TRADING_NEWS_AFTER_S` | `600` / `900` | Seconds either side of a high-impact release to stop entering. Wider doesn't help: [vetoes.md](../research/docs/vetoes.md). | trades |
| `TRADING_RELEASE_IN_HOLD` | `0` | Also refuse when a high-importance release lands inside the planned hold. | trades |
| `TRADING_RELEASE_HOLD_CAP_S` | `14400` | How far ahead that check looks. | trades |
| `TRADING_DRIFT_PAUSE_S` | `900` | Seconds to stand aside after a regime-change signal. | trades |
| `TRADING_LOSS_COOLDOWN_S` | `900` | Seconds before an instrument may be traded again after a loss. | trades |
| `TRADING_MAX_BREAK_RISK` | `0` (off) | Refuse when the calibrated break probability is above this. | trades |
| `TRADING_AGE_BREAK_RISK` | `1` | Bring `break_probability` up to date on a signal that waited, before the gate reads it. | trades |
| `TRADING_MAX_PUSH_VOL` | `25` | Largest expected push a call may claim before it's treated as a fault. | trades |
| `TRADING_MAX_CHASE_VOL` | `1.0` | How far past the level a fill may land. | trades |
| `TRADING_REQUIRE_CANDLE` | `0` | Require a candlestick rejection at the level. Leave off: [stophunt.md](../research/docs/stophunt.md). | trades |
| `TRADING_CANDLE_TOLERANCE_VOL` | `0.25` | How close the bar must come to count as a test of the level. | trades |
| `TRADING_MAX_AGAINST_VOL` / `TRADING_REQUIRE_TURN_VOL` | `0` / `0` (off) | Momentum filters: how far the run may go against, and how far the turn must run. | trades |
| `TRADING_SESSION_MARGIN_S` | `60` | Refuse a hold that doesn't fit before its market closes, plus this margin. | trades |
| `TRADING_SESSION_BARS` | `1400` | 15m bars read per instrument to learn session hours at start. | restart |
| `TRADING_STALE_QUOTE_AFTER_S` | `300` | Seconds without a quote before a feed counts as a shut market. | trades |
| `TRADING_REENTRY_MAX` | `0` (off) | Times one stopped-out setup may be retaken. | trades |

### The ZMA gate

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADING_ZMA_GATE` | `1` | Let `cycle-scalp` veto a call the z-score leans against, only where the feed has earned it. | trades |
| `TRADING_ZMA_MIN_CALLS` | `200` | Scored calls a feed needs before its record counts at all. | trades |
| `TRADING_ZMA_MIN_ACCURACY` | `0.52` | A floor on the record's hit rate. It isn't the bar on its own. | trades |
| `TRADING_ZMA_FEEDS` / `TRADING_ZMA_ALPHA` | `100` / `0.05` | The anytime-valid e-process a feed must clear: evidence of at least feeds / alpha = 2,000, valid however often the record is re-read ([zma-conformal.md](../research/docs/zma-conformal.md)). These replaced the old `TRADING_ZMA_Z`. | trades |

### Shadow confirmation gates

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADING_SHADOW_GATES` | `1` | Record the five confirmation gates from [confirm.md](../research/docs/confirm.md) on matching signals. They never act; they only write journal observations. | restart |
| `TRADING_SHADOW_WINDOW` | `1.0` | How long a stopped trade is watched for its target afterwards, as a multiple of its hold; 0 off. | restart |

### Entries, stops, exits, holds

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADING_MIN_STOP_VOL` | `1.0` | Least distance a stop may sit from the level. | trades |
| `TRADING_STOP_HOLD_SCALING` / `TRADING_MAX_STOP_SCALE` | `0` / `3.0` | Square-root-of-time widening of the stop floor, and its cap. | trades |
| `TRADING_STOPS_LEVEL_MARGIN` | `1.25` | Multiple of the broker's `stops_level` a stop must clear. | trades |
| `TRADING_THESIS_STOP_VOL` | `4.0` | Where `thesis-only` puts its stop. | trades |
| `TRADING_TARGET_BUFFER_VOL` | `0` | Pull the target short of where it was aimed. | trades |
| `TRADING_ENTRY_EDGE_VOL` / `TRADING_ENTRY_PENDING` | `0` / `0` | Rest the entry this far better than the quote, as a pending order. | trades |
| `TRADING_PULLBACK_FRACTION` | `0` (off) | Move the entry toward the stop by this fraction. | trades |
| `TRADING_PULLBACK_BARS` | `10` | How long a parked entry waits. It looks long, and parking has no edge: shorten it to 1-3 if it's kept ([limitfills.md](../research/docs/limitfills.md)). | trades |
| `TRADING_PULLBACK_SIGMAS` / `_MIN_WICKS` / `_MAX_VOL` / `_MIN_GAIN` / `_MIN_SWEEP_RATE` | `0.5` / `2` / `4.0` / `0.25` / `0.10` | Where and when to park for a sweep. | trades |
| `TRADING_PARKED_STOP_VOL` | `0` | Stop distance for an entry that waited for the level (holds under 300 s). | trades |
| `TRADING_SWEEP_MAX_RATE` / `_MIN_HISTORY` / `_MAX_EXPOSURE` | `0.35` / `6` / `0.8` | `sweep-aware`'s gate, and how far a stop may reach toward resting liquidity. | trades |
| `TRADING_APPROACH_MIN_VOL` / `_MAX_VOL` / `_BUFFER_VOL` / `_MIN_REACH` | `0.8` / `6.0` / `0.25` / `0.2` | `approach-scalp`'s target range, buffer and reachability floor. | trades |
| `TRADING_FADE_MIN_TOUCHES` / `_MIN_DISTANCE_VOL` / `_MAX_DISTANCE_VOL` / `_BUFFER_VOL` | `4` / `1.5` / `8.0` / `0.25` | `fade-to-value`'s fair-value rules. | trades |
| `TRADING_BREAK_EVEN_AT` / `TRADING_BREAK_EVEN_TICKS` | `0` (off) / `2` | Move the stop to entry at this R, and ticks past entry. | trades |
| `TRADING_TRAIL_VOL` / `TRADING_TRAIL_SIGMAS` | `0` (off) / `0.5` | Trailing stop distance, and the wick spread it must clear. | trades |
| `TRADING_SCALE_OUT_AT` / `TRADING_SCALE_OUT_FRACTION` | `0` (off) / `0.5` | Take part off at this R, and how much. | trades |
| `TRADING_MAX_HOLD_S` | `1800` | Scalp hold cap; a strategy may ask for longer. | trades |
| `TRADING_MIN_HOLD_S` | `0` | Least time a position is held. | trades |
| `TRADING_MAX_HOLD_SWING_S` | `21600` | Swing hold cap. | trades |
| `TRADING_MAX_HOLD_POSITION_S` | `345600` | Absolute position hold cap (four days). | trades |
| `TRADING_HOLD_EXTENDS_AT` / `TRADING_MAX_HOLD_MULTIPLE` | `0` / `4.0` | R in front at which the hold stops applying, and the total age cap as a multiple of the hold. | trades |
| `TRADING_HOLD_MAX_SPREAD` | `0` (off) | Defer the hold-clock close while the spread is this multiple of risk or wider. | trades |
| `TRADING_STALE_AFTER_S` / `TRADING_STALE_MOVE` | `0` (off) / `0.25` | Cut a trade that went nowhere after this long, unless it reached this R. | trades |
| `TRADING_BASKET_GIVE_BACK` / `_STOP_FRACTION` / `_TAKE_FRACTION` / `_SPARE_PROGRESS` / `_MOMENTUM` | all `0` (off) | Whole-book exits. | trades |

### Execution and the MT5 bridge

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADING_BACKEND` | `auto` | `auto`, `mt5`, `mt5-rpyc`, `mt5-http` or `paper`. | trades |
| `TRADING_MT5_URL` | *(empty)* | The HTTP bridge, for hosts where MetaTrader5 can't run. In production, `http://host.docker.internal:8000`, a tunnel from the terminal host. The retraining workflow also uses it. | restart |
| `TRADING_MT5_API_KEY` | *(empty)* | The bridge's key. Also a GitHub secret for the retrain workflow. | **secret** |
| `TRADING_MT5_QUOTE_SOURCE` | `poll` | Quote transport: `poll` (a sample, one request per symbol per `MT5_POLL_SECONDS`), `ticks` (complete, up to one interval late) or `push` (one WebSocket for every symbol). | restart |
| `TRADING_MT5_API_PATH` | `/api/v1` | The bridge's API prefix. | restart |
| `TRADING_MT5_LOGIN` / `_PASSWORD` / `_SERVER` / `_TERMINAL` | *(blank)* | Native-terminal credentials. Blank means whatever terminal is logged in. | **secret** (password) |
| `TRADING_RPYC_HOST` / `TRADING_RPYC_PORT` | *(empty)* / `18812` | An RPyC server exposing MetaTrader5 from a Wine prefix. **A non-loopback host is refused** unless `TRADING_RPYC_TUNNELLED` is also set, which will stop a deploy dead if it is missed: rpyc with `allow_all_attrs` over an open network is a remote execution surface, so the tunnel has to be asserted rather than assumed. | restart |
| `TRADING_FOLLOWERS` | *(empty)* | Extra terminals that copy every decision, `name=url[\|api_key]`. | trades · **secret** |
| `TRADING_DEVIATION` | `20` | Maximum price deviation for market orders, in points. | trades |
| `TRADING_FILLING` | `IOC` | Order filling mode. | trades |
| `TRADING_TIMEOUT` / `TRADING_RETRIES` | `15` / `3` | Venue request timeout and retries. | restart |
| `TRADING_HEARTBEAT_S` | `60` | Seconds between trading heartbeats. **Read into `Settings.heartbeat`, which nothing reads** - the heartbeat is the status actor now, at a fixed 30 seconds. Setting this does nothing. | restart |
| `TRADING_PAPER_EQUITY` / `TRADING_PAPER_SPREAD_BPS` | `10000` / `2` | The paper book's starting balance and assumed spread. **Inert:** the paper backend retired with `service.py` and nothing reads the fields these resolve into. | restart |

### Trading notifications

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADING_NOTIFY` | `1` | Master switch for anything trading publishes to `alerts`. | restart |
| `TRADING_NOTIFY_FILLS` / `_CLOSES` / `_RESTS` / `_DECLINES` | `1` / `1` / `1` / `0` | Which trading events are carded. Declines are the loudest. | restart |

## Retired: Agents

**Nothing reads any of these.** The agents retired to `research/retire/agents/`, which is the only
place `pydantic_ai` and `anthropic` are still named, and they left the dependency manifest with the
Nautilus port. A key set here reaches nothing.

| Variable | Default | What it did | Change |
|---|---|---|---|
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | — | Gemini (either name). | **secret** |
| `GROQ_API_KEY` | — | Groq. | **secret** |
| `XAI_API_KEY` | — | xAI Grok (OpenAI wire format). | **secret** |
| `DEEPSEEK_API_KEY` | — | DeepSeek. | **secret** |
| `OPENROUTER_API_KEY` | — | OpenRouter. | **secret** |

## Notifications

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | *(empty)* | The bot's token. | **secret** |
| `TELEGRAM_CHAT_IDS` | *(empty)* | Chats or channels to post to. A public channel can be `@username`. | restart |
| `TELEGRAM_AUTO_CHATS` | `0` | Ask Telegram which chats the bot can see, instead of listing them. | restart |
| `DISCORD_WEBHOOK_URLS` | *(empty)* | Discord webhooks, comma-separated. | **secret** |
| `NOTIFY_SHAPES` | *(all)* | Shapes to deliver: `level`, `stale`, `spread`, `dislocation`, `drift`, … | restart |
| `NOTIFY_MIN_INTERVAL` | *(all)* | The fastest timeframe worth sending; sub-15m is where the noise and the losses live. | restart |
| `NOTIFY_COOLDOWN_S` | `900` | The same finding at most once per this many seconds. | restart |
| `NOTIFY_MAX_PER_HOUR` | `20` | Hourly ceiling on messages. | restart |

## Retired: pattern alerts (mcfl)

The `mcfl` service was retired on 2026-10-11 and moved to
`research/retire/mcfl/`, superseded by `statespace/`. Its
`MCFL_*` settings are **gone, not merely ignored** - nothing reads them, so
a deployment that still sets them is setting nothing. The settings they
were, and what they did, are in that directory's own history.

## Journal

| Variable | Default | What it does | Change |
|---|---|---|---|
| `JOURNAL_DB` | `.data/journal/journal.db` | The journal store. Written by the journal actor and read from Python; the two readers this used to name, `structures` and the CLI, are both retired. | state |

## Retired: models and retraining

**`TI_MODELS_DIR` is read by nothing**, and the image ships no models. The retraining pipeline went
to `research/retire/models/` on 2026-10-28 with its workflow; the artefacts went to
`research/retire/models/artefacts/`; the reader, `till-platform`'s `frozen.py`, went to
`research/retire/packages/`; and every loader was in `structures/`, which retired the next day.
`till_infinity/models/` does not exist. See [deployment.md](deployment.md).

`TRADING_MT5_URL` and `TRADING_MT5_API_KEY` are live and are under
[Execution and the MT5 bridge](#execution-and-the-mt5-bridge). They were also GitHub secrets for
the retrain workflow, which is the part that is gone.

## Research-only (not read by production)

The harnesses under `research/harness/` take their own variables, set per run on the lab, and
nothing in `till_infinity/` reads them:

- `SEQLAB`: the lab's bar store;
- `OUT`: the output directory;
- `PART`: which phase to run (`run`, `report`, `contest`, …);
- `START` / `END`: the date range;
- `HORIZONS`, `INTERVAL`, `INTERVALS`, `UNIVERSE`, `ONLY`, `TRIM`, `GAMMA`;
- `JOURNAL` / `BARS`: paths to snapshot databases.

Each harness's docstring gives its own run line. `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and
`MKL_NUM_THREADS` cap threads on the shared lab.

## Known issues

Re-checked 2026-11-01. The first of the three originally listed here is fixed; the other two
changed shape.

- **Fixed: `TRADING_INTERVAL_WEIGHT` was silently empty in production.** `from_env` now falls back
  to the dataclass's measured weights.
- **`TRADING_STRATEGIES`, `TRADING_SYMBOLS` and `TRADING_INTERVALS` each have two defaults**, one in
  `node/desks.py` and one in `strategies/config.py`. The node's is what gets built. Set all three
  explicitly; the table at the top of this page gives both.
- ~~**`TRADING_MAGIC` does not reach the execution client.**~~ Fixed on 2026-11-01. `node/live.py`
  passed `DEFAULT_MAGIC` - the constant's name - where the variable name belongs, so the documented
  knob was inert and the live one had never been written down. It reads `TRADING_MAGIC` now, like
  every sibling beside it, and the old spelling is not kept: it was a bug rather than an interface.
- **`.env.example` is out by 125 names in both directions**: 39 variables the code reads are missing
  from it, and 86 of its entries name something nothing reads - six of those uncommented, so a
  copied `.env` sets them and they do nothing. Two entries are corrupted, carrying Python source
  where a value belongs.
