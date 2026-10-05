# Environment variables

Every setting Till Infinity reads from the environment, grouped by the service that reads it. The
list was taken from the code, not from memory: every `os.environ` read, every `_env` / `_flag` /
`_float` / `_int` / `truthy` / `number` helper call, and every module-level switch. It was then
checked against [`.env.example`](../.env.example). 275 variables in all.

Defaults are **what the code actually resolves** when the variable is unset, which is
`Settings.from_env()` for the config classes. Two variables resolve differently from their dataclass
default, and both are flagged below.

## How settings are read

- **Real environment first.** `.env` is loaded with `load_dotenv(override=False)`, so a variable
  already set in the process environment always wins over the file. A stray `.env` can't override a
  deployment.
- **Read once, at start.** Config classes are built when a service starts, and module-level switches
  (`STRUCTURES_ZMA`, `STRUCTURES_VOL_CLOCK`, …) are read when their module is imported. **Every change
  needs a restart.** Nothing here is re-read live.
- **Booleans.** Anything but `0`, `false` or `no` is on, for the `not in ("0", "false", "no")`
  switches. The `_flag` / `truthy` helpers take `1`, `true` and `yes`.
- **Durations** are seconds unless the name says otherwise. Volatility distances (`*_VOL`) are in the
  production volatility unit, and money is in the account's currency.

### In production

The instance's environment file is `/home/ubuntu/till.env`, written once and passed to the container
with `--env-file` by `deploy.sh`. See [deployment.md](deployment.md), "Moving to another instance".
To change a setting:

1. edit `/home/ubuntu/till.env` on the instance;
2. restart the container (`docker restart till-infinity`, or redeploy);
3. check the start-up log. Most services log the settings they resolved.

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

## Core: which services run, the bus, logging

| Variable | Default | What it does | Change |
|---|---|---|---|
| `PRICES_ENABLED` | `1` | Whether `till-infinity run` starts the price collector. | restart |
| `NEWS_ENABLED` | `1` | Whether `run` starts the news collector. | restart |
| `STRUCTURES_ENABLED` | `1` | Whether `run` starts the levels / structures service. | restart |
| `NOTIFICATIONS_ENABLED` | `1` | Whether `run` starts notification delivery. It exits quietly with no channel configured. | restart |
| `JOURNAL` | `1` | Whether `run` starts the journal writer. | restart |
| `AGENTS_ENABLED` | `0` | Whether `run` starts the agents. Off because they are the only part needing a paid credential. | restart |
| `TRADING_ENABLED` | `0` | Whether `run` starts the trading service at all. Orders also need `TRADING_LIVE`. | trades |
| `MCFL_ENABLED` | `0` | Whether `run` starts the MCFL pattern alerts (alert-only; see [Pattern alerts](#pattern-alerts-mcfl)). | restart |
| `BACKFILL_ON_START` | `1` | Pull history at start when the store holds too little for levels to form, rather than collecting for days first. | restart |
| `SYMBOLS` | *(all)* | Narrow collection to these instruments (comma-separated feed names). Unset collects the whole catalogue. `STRUCTURES_FEEDS` falls back to it. | restart |
| `INTERVALS` | *(all)* | Narrow collection to these intervals, e.g. `1m,5m,15m,1h`. | restart |
| `TILL_REDIS_URL` | *(unset: in-process bus)* | Redis URL for the bus. Unset is an in-process bus, which is fine for one `run` and useless across processes (compose sets it). | restart |
| `STACK_HEARTBEAT` | `60` | Seconds between the stack's heartbeat writes. | restart |
| `STACK_STATUS_FILE` | `.data/stack.json` | Where `run` writes its status, read by `till-infinity health`. | restart |
| `TILL_LOG_LEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING` or `ERROR`. | restart |
| `TILL_LOG_FILE` | *(unset)* | Also write JSON-lines logs to this file. | restart |
| `TILL_LOG_JSON` | *(unset)* | `1` writes JSON lines to the console instead of rich text. | restart |

## Prices

| Variable | Default | What it does | Change |
|---|---|---|---|
| `PRICES_DIR` | `.data/prices` | Directory of the price store. | state |
| `PRICES_DB` | `$PRICES_DIR/prices.db` | The SQLite price store itself. Structures and trading read it too. | state |
| `PRICES_SOURCES` | *(all bar sources)* | Bar providers to poll, comma-separated. | restart |
| `PRICES_QUOTE_SOURCES` | *(all quote sources)* | Quote providers to poll. | restart |
| `PRICES_BROKER_SYMBOLS` | *(empty)* | Broker-only instruments (e.g. `Volatility 75 Index,Step Index`) to collect through the MT5 bridge. Empty by default, because it needs a bridge. See research/catalogue.md on which to carry. | restart |
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
| `NEWS_DB` | `.data/news/news.db` | The news store. Structures reads it for the monetary-policy series. | state |
| `NEWS_SOURCES` | `rss,forexfactory,tradingview,headlines,imf` | Providers to poll. | restart |
| `NEWS_POLL` | `300` | Seconds between headline passes. | restart |
| `NEWS_CAL_POLL` | `900` | Seconds between calendar passes. | restart |
| `NEWS_CAL_BACK_DAYS` / `NEWS_CAL_FORWARD_DAYS` | `3` / `14` | Calendar window around now, in days. | restart |
| `NEWS_CONCURRENCY` | `6` | Parallel requests. | restart |
| `NEWS_RETRIES` | `3` | Retries per failed request. | restart |
| `NEWS_USER_AGENT` | *(browser UA)* | HTTP user agent. | restart |
| `FRED_API_KEY` | *(empty)* | Needed for the `fred` source, which refuses to poll without it. | **secret** |
| `FRED_SERIES` | *(all thirty)* | FRED series to fetch. | restart |

## Structures

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
| `TI_MODELS_DIR` | `.data/models` | Where frozen offline models are read from and promoted into: the shock forecaster, the boosted FX envelope, the touch models. The engine prefers a model here over the one shipped in `till_infinity/models/`, and re-reads a changed file within five minutes. | state |

### Rollover mask

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

Trading is off unless `TRADING_ENABLED=1`, and sends a real order only with `TRADING_LIVE=1` as
well. Most sizing and gate values are justified in `research/docs/settings.md` unless another doc is
named. The named plan `TRADING_RISK_PLAN` sets a bundle of limits, and any limit set individually
wins over it.

### Switches, strategies, universe

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADING_LIVE` | `0` | **The only setting that sends a real order.** Without it, the paper book. | trades |
| `TRADING_STRATEGIES` | `level-scalp` ⚠ | Strategies to run, by registered name, comma-separated. **Inconsistent default:** the `Settings` dataclass says `cycle-turn,cycle-turn-scalp,cycle-scalp`, but `from_env`, which production uses, falls back to `level-scalp`. Set it explicitly. [triage.md](../research/docs/triage.md) found no strategy with an edge. | trades |
| `TRADING_STYLE` | `both` | `scalp`, `swing`, `both` or `none`. | trades |
| `TRADING_SYMBOLS` | `gold,btc` | What to trade. The rest are opt-in and only trade if the broker quotes them. | trades |
| `TRADING_INTERVALS` | every level interval | Timeframes the service accepts. | trades |
| `TRADING_PARALLEL` | `0` | Let every strategy that wants a signal take it, not just the first in order. | trades |
| `TRADING_EVALUATE_ALL` | `0` | Ask every strategy about every signal and record what each would have done. One still trades. | restart |
| `TRADING_CONSENSUS_MIN` | `2` | Strategies that must want the same side before the trade is rebuilt from their joint ask; 0 or 1 disables it. | trades |
| `TRADING_DIR` | `.data/trading` | Where open positions' high-water marks and the day's state live between restarts. | state |
| `TRADING_MAGIC` | `777701` | The base of the magic-number band that marks our positions at the broker; each strategy stamps base+n. Don't change with positions open. | state |

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
| `TRADING_INTERVAL_WEIGHT` | `()` ⚠ | Risk multiplier per entry timeframe, `interval=weight` pairs. **Inconsistent default:** the dataclass carries `1m=0.8,3m=0.8,5m=0.8,15m=0.95` (from `scaling.by_interval`), but `from_env` resolves an unset variable to *no weights*, so production sizes every timeframe at full. Set it explicitly if the weights are wanted. | trades |
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
| `TRADING_MIN_EDGE` | `0.15` | Floor on \|edge\|; must sit above `reactions.MIN_EDGE` to ever fire. | trades |
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

### Council (agents that trade)

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADING_COUNCIL_QUORUM` | `2` | Voices that must agree. Only used if `council` is in `TRADING_STRATEGIES`. | trades |
| `TRADING_COUNCIL_MIN_CONVICTION` | `0.55` | Mean conviction needed across agreeing voices. | trades |
| `TRADING_COUNCIL_DISCUSS` | `1` | Voices see each other and may revise once; 0 halves the calls. | restart |
| `TRADING_COUNCIL_TIMEOUT_S` | `25` | Per-call timeout. | restart |
| `TRADING_COUNCIL_DAILY_CALLS` | `400` | Daily model-call ceiling, for cost. | restart |

### Execution and the MT5 bridge

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADING_BACKEND` | `auto` | `auto`, `mt5`, `mt5-rpyc`, `mt5-http` or `paper`. | trades |
| `TRADING_MT5_URL` | *(empty)* | The HTTP bridge, for hosts where MetaTrader5 can't run. In production, `http://host.docker.internal:8000`, a tunnel from the terminal host. The retraining workflow also uses it. | restart |
| `TRADING_MT5_API_KEY` | *(empty)* | The bridge's key. Also a GitHub secret for the retrain workflow. | **secret** |
| `TRADING_MT5_API_PATH` | `/api/v1` | The bridge's API prefix. | restart |
| `TRADING_MT5_LOGIN` / `_PASSWORD` / `_SERVER` / `_TERMINAL` | *(blank)* | Native-terminal credentials. Blank means whatever terminal is logged in. | **secret** (password) |
| `TRADING_RPYC_HOST` / `TRADING_RPYC_PORT` | *(empty)* / `18812` | An RPyC server exposing MetaTrader5 from a Wine prefix. | restart |
| `TRADING_FOLLOWERS` | *(empty)* | Extra terminals that copy every decision, `name=url[\|api_key]`. | trades · **secret** |
| `TRADING_DEVIATION` | `20` | Maximum price deviation for market orders, in points. | trades |
| `TRADING_FILLING` | `IOC` | Order filling mode. | trades |
| `TRADING_TIMEOUT` / `TRADING_RETRIES` | `15` / `3` | Venue request timeout and retries. | restart |
| `TRADING_HEARTBEAT_S` | `60` | Seconds between trading heartbeats. | restart |
| `TRADING_PAPER_EQUITY` / `TRADING_PAPER_SPREAD_BPS` | `10000` / `2` | The paper book's starting balance and assumed spread. | restart |

### Trading notifications

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TRADING_NOTIFY` | `1` | Master switch for anything trading publishes to `alerts`. | restart |
| `TRADING_NOTIFY_FILLS` / `_CLOSES` / `_RESTS` / `_DECLINES` | `1` / `1` / `1` / `0` | Which trading events are carded. Declines are the loudest. | restart |

## Agents

| Variable | Default | What it does | Change |
|---|---|---|---|
| `AGENTS_MODEL` | `claude-opus-5` | `provider:model`; a bare name is Anthropic's. `till-infinity agents providers` lists them. | restart |
| `AGENTS_FALLBACK_MODELS` | *(empty)* | Models to fall back to, comma-separated. | restart |
| `AGENTS_WINDOW_S` | `60` | Seconds of bus traffic per judgement. Widen on free tiers. | restart |
| `AGENTS_SPREAD_BPS` | `8` | Spread that wakes the model. | restart |
| `AGENTS_IMPORTANCE` | `3` | Least news importance considered. | restart |
| `AGENTS_MAX_TOKENS` / `AGENTS_TOOL_CALLS` / `AGENTS_TIMEOUT_S` / `AGENTS_THINKING` | `2048` / `48` / `120` / `1` | Per-run model limits. | restart |
| `ANTHROPIC_API_KEY` | — | Anthropic (Claude). | **secret** |
| `OPENAI_API_KEY` | — | OpenAI. | **secret** |
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
| `NOTIFY_FEEDS` | *(all)* | Instruments to deliver. | restart |
| `NOTIFY_MIN_INTERVAL` | *(all)* | The fastest timeframe worth sending; sub-15m is where the noise and the losses live. | restart |
| `NOTIFY_COOLDOWN_S` | `900` | The same finding at most once per this many seconds. | restart |
| `NOTIFY_MAX_PER_HOUR` | `20` | Hourly ceiling on messages. | restart |

## Pattern alerts (mcfl)

Alert-only: publishes cards to `alerts`, never reaches `trading`. Off unless `MCFL_ENABLED=1`.
Example cards: `docs/img/mcfl/`.

| Variable | Default | What it does | Change |
|---|---|---|---|
| `MCFL_PAUSE_FILE` | `.data/mcfl.off` | While this file exists nothing is fetched or sent. Removing it resumes without replaying what was missed. | live |
| `MCFL_PATTERNS` | `DISPLACE_C_LOW12,M1,B` | Patterns that alert. Opt-in: `DISPLACE_C_LOW12_X`, `DISPLACE_C`, `BREACH_REVERT`, `DELIVERY_SHIFT`, `BOS`, `CLOSE_REVERT`, `SWEEP_SHIFT`, `INDUCEMENT`, `BREAKER`, `PROTECTED`. `till-infinity mcfl patterns` lists them with their evidence. | restart |
| `MCFL_TIMEFRAMES` | `15m,1h,4h,1d` | Timeframes alerted on. | restart |
| `MCFL_ALT_COINS` | *(the 344 validated coins)* | The alt universe fetched for the DISPLACE_C trade and the market mirror. | restart |
| `MCFL_ALT_TIMEFRAMES` | `4h,1d` | Timeframes the alt universe is fetched on (2,408 kline requests a day by default). | restart |
| `MCFL_MAJOR_PIVOT` | `10` | Bars either side of a 15m major swing for a BOS alert. | restart |
| `MCFL_MAJOR_MOVE_ATR` | `3.0` | ATR away from the major swing before its break counts. | restart |
| `MCFL_CHARTS` | `1` | Attach a chart image to each card (needs the `chart` extra). | restart |
| `MCFL_BINANCE_URL` | `https://data-api.binance.vision/api/v3` | Binance spot's API host for the alt universe. | restart |
| `MCFL_DIR` | `.data/mcfl` | Where the service keeps its state (sent alerts, open paper trades). | state |
| `MCFL_DERIVE_1D` | *(auto)* | Build 1d from stored 1h/4h bars; on by default only when `INTERVALS` is set without `1d`. | restart |

## Journal

| Variable | Default | What it does | Change |
|---|---|---|---|
| `JOURNAL_DB` | `.data/journal/journal.db` | The journal store, read by structures and the CLI. | state |

## Models and retraining

| Variable | Default | What it does | Change |
|---|---|---|---|
| `TI_MODELS_DIR` | `.data/models` | See the envelope table above. | state |
| `MODELS_SYMBOLS` | `$PRICES_BROKER_SYMBOLS` | Instruments `till-infinity models retrain` trains on. In GitHub Actions, a repository variable. | restart |
| `TRADING_MT5_URL`, `TRADING_MT5_API_KEY` | — | The bridge the retrain fetches bars through (secrets in the workflow). | **secret** |

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

## Known issues found while writing this

- **`TRADING_INTERVAL_WEIGHT` is silently empty in production.** `Settings.from_env()` turns an unset
  variable into no weights, dropping the dataclass's measured `1m/3m/5m=0.8, 15m=0.95`. Either set it
  in `till.env` or make `from_env` fall back to the dataclass default.
- **`TRADING_STRATEGIES` disagrees with itself.** It is `cycle-*` in the dataclass and `level-scalp`
  from the environment. Set it explicitly.
- **126 variables the code reads were missing from `.env.example`.** They are now listed there,
  commented, under "less-used settings", with this page as the reference.
