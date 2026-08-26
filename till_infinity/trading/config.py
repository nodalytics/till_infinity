"""Which instruments, on which terminal, with how much risk.

Env vars are read with a ``TRADING_`` prefix, matching the other services.

Two decisions in here are worth more than the numbers around them.

**Paper is the default, and arming is explicit.** `TRADING_LIVE=1` is the only
thing that sends an order to a real account. Every other setting can be wrong
and cost a backtest; this one can be wrong and cost money, so it does not
default to on, is not implied by configuring a terminal, and is printed at
start-up whichever way it is set.

**Gold and BTC are the default instruments; the rest are opt-in.** Not because
the others cannot be scalped, but because the broker has to actually quote
them. A retail MT5 account that carries XAUUSD and BTCUSD very often does not
carry SOLUSD or US100 under any name, and a scalper that discovers this at the
moment of firing has already decided to trade. Availability is resolved once,
at start-up, against the terminal — see `symbols.py`.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..structures import confluence

#: Broker names for each instrument the price side tracks, best first.
#:
#: MT5 symbol naming is a broker-by-broker affair — spot gold is `XAUUSD` at
#: most, `GOLD` at some, and either of those plus a suffix (`.raw`, `.r`, `m`,
#: `.pro`) on the raw-spread account types. The suffixes are handled separately
#: in `symbols.py` because they cross-multiply with every name here; this table
#: only carries the genuinely different *names*.
#:
#: Keys are the price side's feed names, so an instrument is one word from the
#: signal to the order. Anything absent from this table cannot be traded even
#: if the broker quotes it, which is deliberate: the scalper acts on `LEVEL`
#: signals, and those only exist for feeds `prices` collects.
INSTRUMENTS: dict[str, tuple[str, ...]] = {
    "gold": ("XAUUSD", "GOLD", "XAUUSD.spot"),
    "btc": ("BTCUSD", "BTCUSDT", "BITCOIN"),
    "eth": ("ETHUSD", "ETHUSDT", "ETHEREUM"),
    "sol": ("SOLUSD", "SOLUSDT", "SOLANA"),
    "eurusd": ("EURUSD",),
    "gbpusd": ("GBPUSD",),
    "usdjpy": ("USDJPY",),
    "audusd": ("AUDUSD",),
    "usdcad": ("USDCAD",),
    "usdchf": ("USDCHF",),
    "nzdusd": ("NZDUSD",),
    "usdcnh": ("USDCNH",),
    # The indices are where broker naming diverges most. The compact forms
    # are the CFD convention; the spaced ones are Deriv's, and were found by
    # scanning its 798 symbols after the compact names matched nothing at all.
    # Names are matched upper-cased, so they are written that way.
    "us100": ("US100", "NAS100", "USTEC", "NDX100", "USATECH", "US TECH 100"),
    "spx500": ("US500", "SPX500", "SP500", "USA500", "US SP 500"),
}

#: Account-type suffixes, tried against every name above. Empty string first,
#: so a broker with plain symbols never pays for the others, then roughly in
#: order of how often they turn up: Pepperstone razor accounts use `.r`,
#: Eightcap `.raw`, Exness `m`/`c`/`z` for mini, cent and zero, Vantage `+`,
#: spread-betting books `_SB`, and a good number of white labels use `.s` for
#: "standard" or `.i`/`.ecn` for the institutional book.
#:
#: **This list is a fallback, not the mechanism.** It cannot be complete —
#: brokers invent suffixes and nobody publishes the set — so a backend that can
#: enumerate its symbols is asked to instead, and the scan finds whatever this
#: list would have missed. See `Broker.catalogue` and `symbols.resolve`. The
#: list is what remains for backends that can only be asked about one symbol at
#: a time, which is the HTTP bridge as it stands.
SUFFIXES: tuple[str, ...] = (
    "",
    ".raw",
    ".r",
    ".s",
    "m",
    ".pro",
    ".ecn",
    ".i",
    ".a",
    ".c",
    ".z",
    ".std",
    ".stp",
    ".prime",
    ".p",
    ".e",
    "+",
    "#",
    "_SB",
    "_i",
    ".mini",
    ".micro",
    ".cent",
)

#: What is traded unless something else is named. The two the desk asked for.
DEFAULT_SYMBOLS: tuple[str, ...] = ("gold", "btc")

#: Available to name, not traded by default. Kept as its own constant so
#: `trading symbols` can report what could be turned on rather than leaving it
#: to be discovered by reading this file.
OPTIONAL_SYMBOLS: tuple[str, ...] = tuple(k for k in INSTRUMENTS if k not in DEFAULT_SYMBOLS)

#: Backends, in the order `auto` tries them. See `broker.choose`.
PAPER = "paper"
NATIVE = "mt5"
RPYC = "mt5-rpyc"
HTTP = "mt5-http"
#: In the order `auto` prefers them: in-process, then the module proxy, then
#: the HTTP wrapper, then no terminal at all. See `broker.choose`.
BACKENDS: tuple[str, ...] = (NATIVE, RPYC, HTTP, PAPER)

#: Every timeframe `structures` forms levels on. Imported rather than copied:
#: a second list would go stale the first time a timeframe was added, and the
#: symptom would be calls silently ignored.
TIMEFRAMES: tuple[str, ...] = confluence.TIMEFRAMES

DEFAULT_API_PATH = "/api/v1"

#: Stamped on every position this system opens, so `positions` and the panic
#: close can be filtered to *ours*. Any stable non-zero number would do; what
#: matters is that a hand-placed trade on the same terminal is never touched by
#: something here. Zero would mean "everything on the account", which is the
#: one value that must not be the default.
DEFAULT_MAGIC = 777_701


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _flag(name: str, default: str = "0") -> bool:
    raw = (os.environ.get(name, default) or "").strip().lower()
    return raw not in ("", "0", "false", "no", "off")


def _float(name: str, fallback: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return fallback


def _int(name: str, fallback: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return fallback


def _names(raw: str) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


@dataclass(slots=True)
class Settings:
    """Everything tunable, resolved once and threaded through the service."""

    # ------------------------------------------------------------- the venue
    #: "auto", or one of BACKENDS. Auto is resolved in `broker.choose`.
    backend: str = "auto"
    #: The HTTP bridge, for hosts where the MetaTrader5 package cannot run.
    url: str = ""
    api_key: str = ""
    api_path: str = DEFAULT_API_PATH
    timeout: float = 15.0
    retries: int = 3

    #: An RPyC server exposing the MetaTrader5 module from inside a Wine
    #: prefix — the `mt5linux` arrangement. Faster than the bridge and with the
    #: whole API surface rather than the wrapped subset.
    #:
    #: An RPyC server with `allow_all_attrs` runs whatever it is asked to, so
    #: this must never point at one listening on a public interface. Localhost,
    #: a private network, or an SSH tunnel.
    rpyc_host: str = ""
    rpyc_port: int = 18812

    #: Native terminal credentials. Blank means "whatever terminal is already
    #: logged in", which is the normal case on a desktop.
    login: int = 0
    password: str = ""
    server: str = ""
    terminal: str = ""
    #: Equity to size from when the venue cannot be asked. Required by the
    #: bridge backend, which exposes no account endpoint — see `mt5_http`. A
    #: wrong number here sizes every trade wrongly, so it is never guessed
    #: from a default that looks plausible; the fallback is logged when used.
    account_equity: float = 0.0

    # ------------------------------------------------------------ the switch
    #: The only setting that sends a real order. See the module docstring.
    live: bool = False
    magic: int = DEFAULT_MAGIC
    deviation: int = 20
    filling: str = "IOC"

    # ------------------------------------------------------- what to scalp
    #: Strategies to run, by registered name. Several may run together; the
    #: per-instrument position limit is what stops two of them doubling a
    #: position rather than any coordination between them.
    strategies: tuple[str, ...] = ("level-scalp",)
    #: The named risk plan. Individual limits set in the environment win over
    #: it — see `plans`.
    risk_plan: str = "standard"
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    #: Timeframes the service will *accept*. Every one a level forms on, by
    #: default — the restriction belongs to the strategy, not to the module.
    #:
    #: This started as `1m,5m` on the false grounds that "structures only
    #: builds levels on those two"; `structures.config.INTERVALS` is the
    #: anomaly detector's fast-data set, while levels form on all of
    #: `confluence.TIMEFRAMES`. Six of eight were discarded in silence, and the
    #: first live call to arrive was a 3m EURUSD one that the trader ignored
    #: while the same call was delivered to Telegram.
    #:
    #: Narrowing this narrows every strategy at once, which is a blunt
    #: instrument and rarely what is wanted. A strategy that only makes sense
    #: on fast data says so itself, in `Strategy.timeframes`, and the effective
    #: set is the intersection — so this can restrict a strategy but never
    #: widen one past what it claims to handle.
    intervals: tuple[str, ...] = TIMEFRAMES

    # ------------------------------------------------------------ the gates
    #: Fraction of equity risked per trade. 0.25% is a scalping number: the
    #: strategy's edge per trade is small and its trade count is large, so the
    #: per-trade risk that survives a losing streak is well under the 1-2% a
    #: swing book would use.
    risk_fraction: float = 0.0025
    #: Never risk more than this, whatever the equity says. A safety rail for
    #: the case where the account query returns something absurd.
    max_risk_money: float = 0.0
    #: Open positions across everything, and per instrument. One per instrument
    #: is not conservatism — the same level firing three times is one idea, and
    #: stacking it turns a single wrong read into three losses.
    max_positions: int = 4
    max_per_symbol: int = 1
    #: Stop for the day after losing this fraction of the day's opening equity.
    daily_loss_fraction: float = 0.03
    #: Minimum reward-to-risk from the *quoted* entry, spread included. Below
    #: this the trade is paying more to get in than it expects to make.
    min_reward_to_risk: float = 1.2
    #: A scalp whose spread eats this much of its own target is not a trade.
    max_spread_fraction: float = 0.25
    #: The signal's own confidence, and its separation from the base rate.
    #: `structures` already gates on `actionable`, but that threshold exists to
    #: decide whether to *tell someone*. Deciding whether to put money on it is
    #: a different question and gets its own number.
    min_probability: float = 0.58

    #: The floor on |edge|, and it has to sit **above** `reactions.MIN_EDGE`
    #: or it is configuration that can never fire — every signal reaching the
    #: bus has already cleared that gate. The first version of this module set
    #: it to 0.08, which is below the 0.10 upstream and therefore did nothing.
    #:
    #: 0.15 rather than 0.10 because [edge.md](../../docs/edge.md) puts the
    #: step at 0.0968 over ten deciles of 10,483 calls and finds direction
    #: keeps improving above it — its 0.20+ band calls 74.2% and 91.4% correct
    #: across the two halves against 63.3% and 88.0% at 0.11-0.14. Alerting on
    #: a call and staking money on it can reasonably want different margins
    #: over the same step, and this is the margin.
    #:
    #: What it is *not* is a rolling quantile of recent edges. That was
    #: measured and lost; see `speeds` for the record.
    min_edge: float = 0.15
    #: Seconds before the same instrument may be traded again after a loss.
    #: A level that just took money is the level most likely to take it again.
    loss_cooldown: float = 900.0
    #: Seconds a scalp may stay open before it is closed regardless. A scalp
    #: that has been open an hour has become a swing trade nobody planned.
    #: A strategy may ask for longer — see `Strategy.hold_seconds` — because
    #: this default is a property of the trade being taken, not of the module.
    max_hold: float = 1_800.0

    # ------------------------------------------------- standing aside
    #: **Seconds** either side of a high-impact release to stop entering, like
    #: every other duration here. The first version of this said "minutes" and
    #: held seconds, which made the blackout two minutes wide instead of ten.
    #:
    #: Asymmetric, and wider *after* the print. Before it the only job is to
    #: not be holding when the number lands, which needs about as long as a
    #: scalp takes to reach its target. After it the spread is at its widest,
    #: the first move frequently reverses, and a stop is least likely to fill
    #: where it says — so the reason to stay out outlasts the release itself.
    news_before: float = 600.0
    news_after: float = 900.0
    #: Basis points our broker may sit from the venue median before its quote
    #: is treated as unusable, and the multiple of the group's spread it may
    #: charge. Both fail open when fewer than three venues have reported.
    max_dislocation_bps: float = 8.0
    max_spread_ratio: float = 2.5
    #: Seconds to stop entering an instrument after a drift signal. Every level
    #: on it learned its behaviour in the regime that just ended.
    drift_pause: float = 900.0

    # ----------------------------------------------------- net exposure
    #: Money at risk on any one currency, as a fraction of equity, counting
    #: both legs of every open position. `max_positions` counts tickets; this
    #: counts the trade they add up to. Zero switches it off.
    #:
    #: 2x the per-trade risk, so three same-direction dollar trades are refused
    #: at the third — which is the case the limit exists for.
    max_currency_exposure: float = 0.005

    # ------------------------------------------------------- the council
    #: Agents that reason their own way to a trade. Off unless `council` is in
    #: TRADING_STRATEGIES, and it needs a model credential like `agents` does.
    #:
    #: Voices agreeing before anything is traded. Two of four is a majority of
    #: those who spoke in the common case where two abstain.
    council_quorum: int = 2
    #: Mean conviction across the agreeing voices, below which the panel is not
    #: confident enough to be worth the spread.
    council_min_conviction: float = 0.55
    #: Whether the voices see each other's answers and may revise, once. Off
    #: makes each signal cost half as many model calls.
    council_discuss: bool = True
    council_timeout: float = 25.0
    #: Model calls a day, across every voice and round. A cost ceiling, not a
    #: quality setting: four voices over two rounds is eight calls per signal
    #: considered. Zero removes the ceiling, which is rarely what anybody wants.
    council_daily_calls: int = 400

    # -------------------------------------------- managing an open trade
    #: R multiple at which the stop moves to break even. Zero is off, which is
    #: the default — see `manage` for why this is an experiment rather than a
    #: setting somebody should assume.
    break_even_at: float = 0.0
    #: Ticks past the entry the break-even stop sits, to cover the spread.
    break_even_ticks: int = 2
    #: Volatility units to trail behind the best price seen. Zero is off.
    trail_vol: float = 0.0

    # ------------------------------------------- trading toward a level
    #: Nearest and furthest a target level may be, in volatility units. Closer
    #: than the minimum and it is the same structure we are standing on;
    #: further than the maximum and first-passage time makes it unreachable
    #: inside any hold a scalper would accept.
    approach_min_vol: float = 0.8
    approach_max_vol: float = 6.0
    #: Stop this far short of the target level, in volatility units. See
    #: `ApproachScalp` — this is what keeps the strategy off the one claim the
    #: repository has already measured and rejected.
    approach_buffer_vol: float = 0.25
    #: Least acceptable chance of covering the distance within the hold, from
    #: the first-passage model in `structures.timing`.
    #:
    #: **A floor against the absurd, not a forecast.** Diffusion is a null
    #: model and markets depart from it — magnet.md measured exactly that — so
    #: this is not the strategy's estimate of anything. It is here to refuse a
    #: level that a driftless walk would rarely reach inside the hold, which is
    #: the case where the target is simply too far away for the time allowed.
    #:
    #: 0.20 rather than something higher because of where the two gates meet.
    #: On 5m with a 45-minute hold there are nine bars, and a 35% floor caps
    #: the distance at about 3.5v — below `approach_max_vol`, which would make
    #: that ceiling dead configuration that never fires. At 0.20 the reach gate
    #: binds on the slower timeframes and the distance ceiling binds on the
    #: faster ones, and both do something.
    approach_min_reach: float = 0.20

    # ------------------------------------------------------------- plumbing
    #: Refuse to keep trading if the terminal stops answering.
    heartbeat: float = 60.0
    # ------------------------------------------------------- announcements
    #: The master gate. Off means this service publishes nothing to `alerts`,
    #: whatever the three below say.
    #:
    #: Gated three ways on purpose, because the three messages have completely
    #: different volumes. A fill is rare and always worth seeing. A decline is
    #: the most informative and the easiest to drown in — every gate doing its
    #: job produces one, and a halted day produces one per signal until the
    #: clock rolls over — so it is off unless asked for.
    #:
    #: All of this is still subject to the notification layer's own filter: if
    #: `NOTIFY_SHAPES` has been narrowed, `trade` has to be in it or none of
    #: these arrive however they are set here.
    notify: bool = True
    notify_fills: bool = True
    notify_closes: bool = True
    notify_declines: bool = False
    journal_context: bool = True
    #: Starting balance for the paper book, when there is no account to ask.
    paper_equity: float = 10_000.0
    #: Spread assumed by the paper book when no quote has arrived yet, in bps.
    paper_spread_bps: float = 2.0

    #: Filled in by `symbols.resolve`: feed name -> broker symbol.
    resolved: dict[str, str] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        """Whether a real terminal has been pointed at, by any route."""
        return (
            bool(self.url)
            or bool(self.rpyc_host)
            or self.backend in (NATIVE, RPYC)
            or bool(self.login)
        )

    @property
    def mode(self) -> str:
        return "live" if self.live else "paper"

    def base_url(self) -> str:
        return f"{self.url.rstrip('/')}{self.api_path}" if self.url else ""

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            backend=(_env("TRADING_BACKEND") or "auto").lower(),
            url=_env("TRADING_MT5_URL"),
            api_key=_env("TRADING_MT5_API_KEY"),
            api_path=_env("TRADING_MT5_API_PATH") or DEFAULT_API_PATH,
            rpyc_host=_env("TRADING_RPYC_HOST"),
            rpyc_port=_int("TRADING_RPYC_PORT", 18812),
            timeout=_float("TRADING_TIMEOUT", 15.0),
            retries=_int("TRADING_RETRIES", 3),
            login=_int("TRADING_MT5_LOGIN", 0),
            password=_env("TRADING_MT5_PASSWORD"),
            server=_env("TRADING_MT5_SERVER"),
            terminal=_env("TRADING_MT5_TERMINAL"),
            account_equity=_float("TRADING_ACCOUNT_EQUITY", 0.0),
            live=_flag("TRADING_LIVE"),
            magic=_int("TRADING_MAGIC", DEFAULT_MAGIC),
            deviation=_int("TRADING_DEVIATION", 20),
            filling=(_env("TRADING_FILLING") or "IOC").upper(),
            strategies=_names(_env("TRADING_STRATEGIES")) or ("level-scalp",),
            risk_plan=(_env("TRADING_RISK_PLAN") or "standard").lower(),
            symbols=_names(_env("TRADING_SYMBOLS")) or DEFAULT_SYMBOLS,
            intervals=_names(_env("TRADING_INTERVALS")) or TIMEFRAMES,
            risk_fraction=_float("TRADING_RISK_FRACTION", 0.0025),
            max_risk_money=_float("TRADING_MAX_RISK_MONEY", 0.0),
            max_positions=_int("TRADING_MAX_POSITIONS", 4),
            max_per_symbol=_int("TRADING_MAX_PER_SYMBOL", 1),
            daily_loss_fraction=_float("TRADING_DAILY_LOSS_FRACTION", 0.03),
            min_reward_to_risk=_float("TRADING_MIN_RR", 1.2),
            max_spread_fraction=_float("TRADING_MAX_SPREAD_FRACTION", 0.25),
            min_probability=_float("TRADING_MIN_PROBABILITY", 0.58),
            min_edge=_float("TRADING_MIN_EDGE", 0.15),
            loss_cooldown=_float("TRADING_LOSS_COOLDOWN_S", 900.0),
            max_hold=_float("TRADING_MAX_HOLD_S", 1_800.0),
            news_before=_float("TRADING_NEWS_BEFORE_S", 600.0),
            news_after=_float("TRADING_NEWS_AFTER_S", 900.0),
            max_dislocation_bps=_float("TRADING_MAX_DISLOCATION_BPS", 8.0),
            max_spread_ratio=_float("TRADING_MAX_SPREAD_RATIO", 2.5),
            drift_pause=_float("TRADING_DRIFT_PAUSE_S", 900.0),
            max_currency_exposure=_float("TRADING_MAX_CURRENCY_EXPOSURE", 0.005),
            council_quorum=_int("TRADING_COUNCIL_QUORUM", 2),
            council_min_conviction=_float("TRADING_COUNCIL_MIN_CONVICTION", 0.55),
            council_discuss=_flag("TRADING_COUNCIL_DISCUSS", "1"),
            council_timeout=_float("TRADING_COUNCIL_TIMEOUT_S", 25.0),
            council_daily_calls=_int("TRADING_COUNCIL_DAILY_CALLS", 400),
            break_even_at=_float("TRADING_BREAK_EVEN_AT", 0.0),
            break_even_ticks=_int("TRADING_BREAK_EVEN_TICKS", 2),
            trail_vol=_float("TRADING_TRAIL_VOL", 0.0),
            approach_min_vol=_float("TRADING_APPROACH_MIN_VOL", 0.8),
            approach_max_vol=_float("TRADING_APPROACH_MAX_VOL", 6.0),
            approach_buffer_vol=_float("TRADING_APPROACH_BUFFER_VOL", 0.25),
            approach_min_reach=_float("TRADING_APPROACH_MIN_REACH", 0.20),
            heartbeat=_float("TRADING_HEARTBEAT_S", 60.0),
            notify=_flag("TRADING_NOTIFY", "1"),
            notify_fills=_flag("TRADING_NOTIFY_FILLS", "1"),
            notify_closes=_flag("TRADING_NOTIFY_CLOSES", "1"),
            notify_declines=_flag("TRADING_NOTIFY_DECLINES", "0"),
            paper_equity=_float("TRADING_PAPER_EQUITY", 10_000.0),
            paper_spread_bps=_float("TRADING_PAPER_SPREAD_BPS", 2.0),
        )


def feed_for(symbol: str) -> str:
    """Which instrument a broker symbol belongs to, by its name alone.

    The reverse of `INSTRUMENTS`, and it has to work *without* a resolved
    symbol map because the map is built by asking a broker for specs, and a
    broker being asked for a spec may need to know which instrument it is
    answering about. Consulting `Settings.resolved` there is circular, and the
    paper book did exactly that: while resolution was still running the map was
    empty, gold fell through to the currency-pair default, and a 100-ounce
    contract was priced as 100,000 units — a stop that should cost $440 a lot
    priced at $440,000, so every trade refused itself as too large to size.

    Exact matches win over prefixes, and the longest prefix wins among the
    rest, so `BTCUSDT` does not resolve against a shorter name from another
    instrument.
    """
    upper = symbol.upper()
    for feed, names in INSTRUMENTS.items():
        if any(upper == name for name in names):
            return feed
    best, found = 0, ""
    for feed, names in INSTRUMENTS.items():
        for name in names:
            if upper.startswith(name) and len(name) > best:
                best, found = len(name), feed
    return found


def resolve_symbols(
    names: Sequence[str] | None, settings: Settings | None = None
) -> tuple[str, ...]:
    """Turn what the caller typed into feed names this module can trade.

    Unknown names raise rather than being skipped. A typo in `TRADING_SYMBOLS`
    that silently trades two instruments instead of three is the kind of
    failure that is only noticed when the missing one would have made money.
    """
    wanted = tuple(n.strip().lower() for n in names if n.strip()) if names else ()
    if not wanted:
        return settings.symbols if settings else DEFAULT_SYMBOLS
    unknown = [n for n in wanted if n not in INSTRUMENTS]
    if unknown:
        raise ValueError(f"cannot trade: {', '.join(unknown)} (have: {', '.join(INSTRUMENTS)})")
    return wanted
