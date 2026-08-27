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
at start-up, against the terminal - see `symbols.py`.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..structures import confluence

#: Broker names for each instrument the price side tracks, best first.
#:
#: MT5 symbol naming is a broker-by-broker affair - spot gold is `XAUUSD` at
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
    "silver": ("XAGUSD", "SILVER"),
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
    "ger40": ("GER40", "DE40", "DE30", "DAX40", "GERMANY40", "GERMANY 40"),
    "uk100": ("UK100", "FTSE100", "UKX", "UK 100"),
    "us30": ("US30", "DJ30", "DOW30", "WALL STREET 30", "WALLSTREET30"),
    "us2000": ("US2000", "RUSSELL2000", "RUT", "US SMALL CAP 2000"),
    "jp225": ("JP225", "JPN225", "NIKKEI225", "JAPAN 225"),
    "fra40": ("FRA40", "FR40", "CAC40", "FRANCE 40"),
    "eu50": ("EU50", "EUSTX50", "STOXX50", "EUROPE 50"),
    "aus200": ("AUS200", "AU200", "ASX200", "AUSTRALIA 200"),
    "hk50": ("HK50", "HK33", "HSI", "HONG KONG 50"),
    "wti": ("WTI", "USOIL", "CRUDE", "XTIUSD", "US OIL"),
    "brent": ("BRENT", "UKOIL", "XBRUSD", "UK BRENT OIL"),
    # The crosses. No dollar leg - see `exposure.LEGS`.
    "eurgbp": ("EURGBP",),
    "eurjpy": ("EURJPY",),
    "gbpjpy": ("GBPJPY",),
    "eurchf": ("EURCHF",),
    "audjpy": ("AUDJPY",),
    "chfjpy": ("CHFJPY",),
    "euraud": ("EURAUD",),
}

#: Account-type suffixes, tried against every name above. Empty string first,
#: so a broker with plain symbols never pays for the others, then roughly in
#: order of how often they turn up: Pepperstone razor accounts use `.r`,
#: Eightcap `.raw`, Exness `m`/`c`/`z` for mini, cent and zero, Vantage `+`,
#: spread-betting books `_SB`, and a good number of white labels use `.s` for
#: "standard" or `.i`/`.ecn` for the institutional book.
#:
#: **This list is a fallback, not the mechanism.** It cannot be complete -
#: brokers invent suffixes and nobody publishes the set - so a backend that can
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
#:
#: This is the *base* of a band rather than a single number - see `MAGIC_BAND`.
DEFAULT_MAGIC = 777_701

#: How many magics one deployment occupies, starting at `Settings.magic`.
#:
#: The base itself means "ours, but we cannot say which strategy" - what a
#: position opened before per-strategy magics existed carries, and what the
#: panic close and reconciliation still have to recognise. Offsets 1 and above
#: name the strategy that asked for the trade, which is the only way to tell,
#: after a restart or from the terminal itself, which of several strategies
#: running side by side opened a given position. The order comment carries the
#: same name, but comments are advisory: brokers truncate and rewrite them,
#: and MT5 caps them at 31 characters. Magic survives.
MAGIC_BAND = 1_000

#: Strategy name to offset within the band. **Append-only.** These numbers end
#: up on positions held at a broker and in journal entries that outlive any one
#: release, so reordering this tuple would silently reattribute history: a
#: position opened by one strategy would start reading as another's. Add new
#: names at the end and never move an existing one.
#:
#: Deriving the offset from the *configured* strategy list instead would be the
#: same bug in a worse form - editing TRADING_STRATEGIES would renumber every
#: open position, and a restart mid-trade could not say who owned what.
MAGIC_ORDER: tuple[str, ...] = (
    "level-scalp",
    "confluence-scalp",
    "momentum-scalp",
    "approach-scalp",
    "swing-level",
    "sweep-aware",
    "fade-to-value",
    "council",
    # Appended, never inserted. A strategy added without a slot here still
    # trades - it stamps a hashed magic from the tail of the band - but that
    # hash has no inverse, so every position it opens reads as
    # "unattributed" on close and the strategy cannot be scored at all.
    # Both of these ran live for an hour before the missing entries were
    # noticed, and their two trades are unattributable in the record.
    "snap",
    "thesis-only",
    "runner",
    "inverse",
    "high-timeframe",
)


def magic_for(base: int, strategy: str) -> int:
    """The magic one strategy stamps on its orders.

    Names in `MAGIC_ORDER` get their fixed slot. Anything else - a strategy
    registered by something outside this package - is hashed into the rest of
    the band, deterministically, because Python's own `hash` is salted per
    process and would hand the same strategy a different magic on every
    restart. Collisions are possible in that tail and are reported at start-up
    rather than left to be discovered in a report that quietly merges two
    strategies' results.
    """
    if not strategy:
        return base
    if strategy in MAGIC_ORDER:
        return base + 1 + MAGIC_ORDER.index(strategy)
    fixed = len(MAGIC_ORDER)
    digest = hashlib.blake2s(strategy.encode(), digest_size=4).digest()
    span = MAGIC_BAND - 1 - fixed
    return base + 1 + fixed + int.from_bytes(digest, "big") % span


def strategy_for(base: int, magic: int) -> str:
    """The strategy a magic names, or "" when it does not name one.

    The inverse of `magic_for` for the fixed table only. A hashed offset has no
    inverse, so a plugin strategy's positions read as ours-but-unattributed,
    which is the honest answer rather than a guessed one.
    """
    offset = magic - base
    if 1 <= offset <= len(MAGIC_ORDER):
        return MAGIC_ORDER[offset - 1]
    return ""


def ours(base: int, magic: int) -> bool:
    """Whether a position at the broker belongs to this system.

    The band, not the base, because every strategy now stamps its own number.
    A comparison against the base alone - which is what this replaced - would
    make every position opened by a named strategy look like somebody else's,
    so the trader would neither manage nor close its own trades.
    """
    return base <= magic < base + MAGIC_BAND


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
    #: prefix - the `mt5linux` arrangement. Faster than the bridge and with the
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
    #: bridge backend, which exposes no account endpoint - see `mt5_http`. A
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
    #: it - see `plans`.
    risk_plan: str = "standard"
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    #: Timeframes the service will *accept*. Every one a level forms on, by
    #: default - the restriction belongs to the strategy, not to the module.
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
    #: set is the intersection - so this can restrict a strategy but never
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
    #: is not conservatism - the same level firing three times is one idea, and
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
    #: How often the level must hold in the claimed direction, unconditionally.
    #:
    #: Separate from `min_probability`, which is the *conditional* - what the
    #: model thinks about this touch. This is the baseline it is measured
    #: against, and the two are not the same question: a level that holds 45%
    #: of the time and is claimed at 80% is a bigger departure than one that
    #: holds 65% and is claimed at 85%, and the first is the worse trade.
    #:
    #: Zero disables. Measured over the first nineteen closed trades: the eight
    #: with a directional base under 0.55 produced one winner and -6.74R.
    min_base_rate: float = 0.0
    #: Where to sit in each direction's *own* distribution of claimed
    #: probability, in [0, 1]. Zero uses `min_probability` alone.
    #:
    #: One absolute number produced a one-sided book: over 7,498 calls the two
    #: directions are offered almost evenly - 48% up, 52% down - but down
    #: arrives more confident, median 0.880 against 0.824, so a single floor at
    #: 0.75 passed 96% of sells and 80% of buys and the book came out 21 sells
    #: to 4 buys with no rule saying it should.
    #:
    #: Off by default, and the reason is worth stating: this repository has
    #: measured dynamic thresholds losing to matched constants three times. The
    #: fixed-pair version is in `floors.by_direction` and is what the evidence
    #: favours; this exists for when the distributions drift far enough that a
    #: fixed pair stops meaning what it meant.
    probability_percentile: float = 0.0
    #: Ask every strategy about every signal, and record what each would have
    #: done. One of them still trades.
    #:
    #: The running order decides who trades and also who is ever *asked*, so
    #: the strategies never see the same signals and their records are not
    #: comparable - one scored +1.01R over two trades and another -0.75R over
    #: ten, on two different streams. Trading them in parallel would fix the
    #: comparison and multiply the risk, since two strategies on one signal is
    #: one idea found twice. Evaluating in parallel fixes it for free.
    evaluate_all: bool = False
    #: How many strategies must want the same side before the trade is rebuilt
    #: from what they collectively asked for. Zero or one disables it.
    #:
    #: Agreement does **not** size the trade up. Two strategies on one signal
    #: is one idea found twice, so betting more on it doubles a position on a
    #: single thesis. What agreement buys instead is a better-built trade: the
    #: furthest stop any of them wanted, because being stopped before the move
    #: arrived is the failure measured most this session, and the nearest
    #: target, because unreached targets are what a wide stop costs. Money at
    #: risk is unchanged - a wider stop is re-sized into fewer lots.
    consensus_min: int = 2
    #: Where `thesis-only` puts its stop, in volatility units.
    #:
    #: Far enough that it is a circuit breaker rather than a trade decision.
    #: Over 49,338 resolutions the 90th percentile of excursion past a level is
    #: 3.68v on 1m, so 4 sits just beyond the range where a stop decides
    #: anything while still firing before a loss becomes interesting.
    #:
    #: **Bounded by the account, not only by the argument.** At 8v the minimum
    #: lot risks more than the risk budget allows on a ten-thousand-unit
    #: account - the refusal reads "25.00 does not cover the minimum 0.01 lot,
    #: which risks 35.70" - so the experiment would simply not have traded. A
    #: wider stop is available on a larger account and is the honest place to
    #: run the full version.
    #:
    #: The trade is correspondingly small either way: the same money at risk
    #: spread over a stop four times wider buys a quarter of the lots, which is
    #: the price of giving a trade room.
    thesis_stop_vol: float = 4.0

    #: The floor on |edge|, and it has to sit **above** `reactions.MIN_EDGE`
    #: or it is configuration that can never fire - every signal reaching the
    #: bus has already cleared that gate. The first version of this module set
    #: it to 0.08, which is below the 0.10 upstream and therefore did nothing.
    #:
    #: 0.15 rather than 0.10 because [edge.md](../../docs/edge.md) puts the
    #: step at 0.0968 over ten deciles of 10,483 calls and finds direction
    #: keeps improving above it - its 0.20+ band calls 74.2% and 91.4% correct
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
    #: A strategy may ask for longer - see `Strategy.hold_seconds` - because
    #: this default is a property of the trade being taken, not of the module.
    max_hold: float = 1_800.0

    #: R in front at which the hold stops applying. Zero keeps the old rule:
    #: the clock closes everything, whatever it is doing.
    #:
    #: The hold exists to release capital from a thesis that is not playing
    #: out. It was closing trades that were, which is a different thing: a
    #: position a point in front at the thirty minute mark is closed at market
    #: and the rest of the move happens without us. Observed on gold - out at
    #: 4623 on a fall that carried to 4592.
    #:
    #: A trade allowed to outlive its hold is **first moved to break even**, so
    #: the extension cannot turn a winner into a loser. That is what makes this
    #: safe to run without the trailing rules in `manage.py` being on.
    hold_extends_at: float = 0.0
    #: Total age cap, as a multiple of the strategy's own hold. Extending has
    #: to end somewhere: a position held indefinitely accrues swap, crosses
    #: sessions it was never measured in, and eventually sits over a weekend.
    max_hold_multiple: float = 4.0

    # ------------------------------------------------- standing aside
    #: **Seconds** either side of a high-impact release to stop entering, like
    #: every other duration here. The first version of this said "minutes" and
    #: held seconds, which made the blackout two minutes wide instead of ten.
    #:
    #: Asymmetric, and wider *after* the print. Before it the only job is to
    #: not be holding when the number lands, which needs about as long as a
    #: scalp takes to reach its target. After it the spread is at its widest,
    #: the first move frequently reverses, and a stop is least likely to fill
    #: where it says - so the reason to stay out outlasts the release itself.
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
    #: at the third - which is the case the limit exists for.
    max_currency_exposure: float = 0.005

    #: How far past the level a fill may land before the trade is refused.
    #:
    #: Entry is a market order, so it lands wherever price is when the call
    #: arrives, and nothing looked at that. The call was measured *at* the
    #: level and the push it predicts is measured from there, so a fill well
    #: past it has already spent part of the move - and the stop, anchored to
    #: the level, ends up sitting close underneath the fill. Both halves of
    #: "stopped out before the move came" meet here.
    #:
    #: Only counted when the fill is past the level in the trade's own
    #: direction. Arriving before it is the setup behaving as described.
    #: Zero disables.
    max_chase_vol: float = 1.0

    #: How far toward the stop's price the entry is moved, as a fraction.
    #:
    #: Zero enters at market, which is what every order here has always done.
    #: One waits for the price the stop was going to defend - the far edge of
    #: the level's sweep zone - which is the best fill the setup can offer and
    #: the one it offers least often. A half meets it in the middle.
    #:
    #: The trade that gets stopped out today is the one that gets *filled*
    #: tomorrow, and the reward-to-risk improves because the target does not
    #: move with the entry. The cost is the setups that never come back, and it
    #: is a real cost: a strategy that only fills on retracements is a
    #: different strategy, not a cheaper version of this one.
    pullback_fraction: float = 0.0
    #: Bars of the **entry interval** a parked signal may wait. Replaces the
    #: fraction above wherever the interval is known: a fraction of the hold
    #: makes the wait a property of the strategy rather than of the market, so
    #: a 1m call and a 1h call would wait the same wall clock for retracements
    #: that happen on completely different clocks.
    pullback_bars: float = 10.0
    #: How much of the wick's own spread to add to its mean when choosing where
    #: to wait. Half of all wicks are deeper than the mean by definition, so
    #: waiting at the mean is waiting at a depth exceeded as often as not.
    pullback_sigmas: float = 0.5
    #: Wicks a level must have behind it before waiting for one is worth doing.
    #: Parking asks price to return somewhere it has been; a level with no such
    #: place offers nothing to wait for, and the signal expires unfilled - which
    #: is not a trade avoided but a trade the strategy wanted and did not get.
    pullback_min_wicks: float = 2.0
    #: The least a parked fill must improve on the one in hand, in volatility
    #: units, before the trade is put at risk of not happening. Parking trades
    #: a fill you have for one you may not get; when the offer is already near
    #: the level there is little to win and the whole spread of outcomes is
    #: downside.
    #: The deepest a parked entry may wait, in volatility units past the level.
    #:
    #: A bound in the level's own units rather than at the sweep edge. Clamping
    #: at the edge discarded exactly the fills worth waiting for - a pullback
    #: deeper than the zone *is* the sweep - and the edge was never a safe
    #: stopping point anyway: the stop sits beyond it, and the fill floor keeps
    #: the stop clear of wherever the entry lands.
    pullback_max_vol: float = 4.0
    pullback_min_gain: float = 0.25
    #: How often the level must have been swept before waiting for a sweep is
    #: worth doing. `sweep_rate` is the level's own record of being run through
    #: and recovering - the thing the wait is betting on. An unmeasured rate
    #: passes, because unknown is not the same as low.
    pullback_min_sweep_rate: float = 0.10

    #: How long a stopped trade is watched to see if its target arrived, as a
    #: multiple of the hold it would have had. Zero switches the watch off.
    #:
    #: The one question the account cannot answer on its own: a stop hit at
    #: full size looks identical whether the level failed or the stop sat
    #: inside the noise. Recorded, never traded.
    shadow_window: float = 1.0

    #: How much of the square-root-of-time scaling to apply to the stop floor.
    #:
    #: `vol_bps` is the volatility of **one bar** of the entry interval, so a
    #: stop at `min_stop_vol` units is sized for one bar - while the trade is
    #: held for many. Volatility grows with the square root of time, which was
    #: measured on our own instruments rather than assumed: observed growth
    #: over sqrt(t) came to 1.04, 1.12 and 0.89 on gold at 5m, 15m and 60m, and
    #: 0.99 and 0.98 on the Dow. Thirty one-minute bars therefore carry about
    #: 5.5 units of wandering, against an expected push near 1.3.
    #:
    #: 1.0 applies the scaling in full, 0.0 restores the one-bar stop, and
    #: values between are the honest position while `shadow_window` collects
    #: the evidence: a wider stop cannot create edge - for a driftless walk it
    #: buys win rate and pays for it in R - so what it fixes is paying spread
    #: to be stopped by noise, not the direction being wrong.
    #:
    #: Off by default, like every other rule here that changes what gets
    #: traded. A wider stop cannot create edge - it buys win rate and pays for
    #: it in R - so this is enabled to stop paying spread to be taken out by
    #: noise, and `shadow_window` is what says whether that was the problem.
    stop_hold_scaling: float = 0.0
    #: Ceiling on that multiplier. Uncapped, a thirty-bar hold asks for a stop
    #: 5.5 times wider and a position 5.5 times smaller, and `reward_to_risk`
    #: then refuses nearly everything - which may be the honest answer but is
    #: not one to arrive at by accident.
    max_stop_scale: float = 3.0

    #: The least a stop may sit from the level, in volatility units.
    #:
    #: Fair value is a distribution and volatility is its width, so a stop
    #: closer than one unit is *inside the estimate's own noise* and will be
    #: taken by ordinary movement rather than by the thesis being wrong. The
    #: README says exactly this about distance - one unit is noise, three is a
    #: statement - and it applies to the stop before it applies to the entry.
    #:
    #: Measured on the first two live trades, both gold, both sells: risk_vol
    #: of 0.53 and 0.61 against volatility units of 0.99 and 1.72. The second
    #: was stopped at 4626.09 on a 1.05-point stop and price then fell to 4615,
    #: which is the direction being right and the stop being inside the noise.
    #:
    #: `risk_vol` comes from the level model's own geometry and is frequently
    #: under a unit on young levels, where the zone has no wicks recorded to
    #: widen it either. Flooring here rather than there is deliberate: the model
    #: is describing where the level is invalidated, and this is a statement
    #: about what a *tradable* stop costs.
    #:
    #: The size shrinks to keep the risk budget, and a trade that then cannot
    #: make the minimum lot is refused - which is the correct outcome. A stop
    #: inside the noise is not a cheaper trade, it is a worse one.
    min_stop_vol: float = 1.0

    # ------------------------------------------- standing in front of a sweep
    #: A level run this often, from this side, is refused by `sweep-aware`.
    #: `TRAP` is the recorded outcome: through and back.
    sweep_max_rate: float = 0.35
    #: Decisive interactions before that rate is believed at all. Below it the
    #: level has not said anything about itself yet.
    sweep_min_history: float = 6.0
    #: How far a stop may reach toward the liquidity resting beyond, as a share
    #: of the distance to it. At 1.0 the stop sits exactly on the pool; the
    #: default keeps it well short of one.
    sweep_max_exposure: float = 0.8

    # ------------------------------------------------ pricing the distance
    #: Decisive interactions a level needs before `fade-to-value` will treat it
    #: as an estimate of fair value rather than a place price once went.
    fade_min_touches: float = 4.0
    #: How far out to look for fair value. Beyond this the level is not what
    #: the current move is priced against.
    fade_max_distance_vol: float = 8.0
    #: How far from fair value a price has to be before the distance is a
    #: statement rather than the noise of the estimate itself. Fair value is a
    #: distribution and volatility is its width; inside one unit there is
    #: nothing to say.
    fade_min_distance_vol: float = 1.5
    #: Stop this far short of fair value, for the reason `approach-scalp` does:
    #: price is not drawn to a level, so the last stretch into the zone is the
    #: part that was measured and did not survive.
    fade_buffer_vol: float = 0.25

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
    #: the default - see `manage` for why this is an experiment rather than a
    #: setting somebody should assume.
    break_even_at: float = 0.0
    #: Ticks past the entry the break-even stop sits, to cover the spread.
    break_even_ticks: int = 2
    #: Volatility units to trail behind the best price seen. Zero is off.
    trail_vol: float = 0.0
    #: How much of the level's own wick spread the trail must clear, on top of
    #: its mean. A trail inside the retracement this level routinely makes is
    #: taken by ordinary movement while the trade is still working, which is
    #: being stopped by noise in profit. `trail_vol` acts as the floor.
    trail_sigmas: float = 0.5
    #: How much further than the placed stop a stopped trade actually costs,
    #: as a fraction of the risk distance. Zero sizes as before.
    #:
    #: **Measured, not assumed.** Across the stopped trades in the journal the
    #: realised loss is 1.09R against the 1.00R they were sized for, and the
    #: decomposition puts most of it on the way out: entry slippage averages
    #: +0.025R, exit slippage +0.062R. A broker stop is a market order once
    #: triggered, so it fills through the spread and any gap - that half is a
    #: property of stops, not a defect to remove.
    #:
    #: What *is* a defect is sizing against the stop we place rather than the
    #: stop we get, which quietly breaches the risk budget on every loss. This
    #: inflates the distance used for sizing so the money lost matches the
    #: money budgeted.
    #:
    #: It does not improve returns. Positions get about 8% smaller and losses
    #: land where they were supposed to. The gain is that the risk limits mean
    #: what they say.
    stop_slippage: float = 0.0

    #: The largest expected push a call may claim, in volatility units. Beyond
    #: this the number is not a forecast, it is a fault.
    #:
    #: **Found live.** A brent call arrived with `expected_push_vol` of
    #: **10,229.7**. Measured over 54,547 resolutions the push distribution has
    #: a median of 2.24v and a p99 of 9.55v, so this was four orders of
    #: magnitude past anything the market does. Trading multiplied it into a
    #: target of 3850.308 on an entry of 88.374 - 43 times the price of the
    #: instrument - and the broker refused the order.
    #:
    #: The refusal is what made it visible, and that is the uncomfortable part:
    #: had the target been merely large rather than absurd, the order would
    #: have been accepted and the trade would have run to its stop or its clock
    #: with a target it could never reach. Nothing on this side checked.
    #:
    #: Set well above p99 rather than close to it. The job is to catch a broken
    #: number, not to second-guess a large one - a genuine 12v push is rare and
    #: real, and refusing it would be this gate exceeding its remit.
    max_push_vol: float = 25.0

    #: Defer the hold-clock close while the spread is this multiple of the
    #: trade's own risk distance or wider. Zero closes on the clock regardless.
    #:
    #: **Found live.** An aus200 position was quoted `bid 8998 / ask 9051` out
    #: of ASX hours - a 53-point spread against a normal 1 to 2, and against
    #: the trade's own 8.89-point risk. A long is marked at the bid, so it
    #: showed -61 on a 19 budget while its true mid had not even reached the
    #: stop. The hold clock was minutes from closing it at market and turning
    #: that arithmetic into a realised loss.
    #:
    #: `max_spread_fraction` already refuses to *enter* on a wide spread.
    #: Nothing protected a position already open when liquidity went away,
    #: which is the harder half - entry can always wait, an open position
    #: cannot.
    #:
    #: Measured against the trade's own risk rather than a baseline spread,
    #: because that is self-calibrating: it asks whether crossing the spread
    #: costs a meaningful share of what the trade was willing to lose, which is
    #: the question that matters and needs no history to answer.
    #:
    #: Bounded by `max_hold_multiple` like every other extension here, so a
    #: permanently wide instrument cannot hold a position open forever.
    hold_max_spread: float = 0.0

    #: Stop distance, in volatility units, for an entry that waited for the
    #: level. Zero keeps the ordinary stop. Only ever tightens, never widens.
    #:
    #: **The replay's best cell and this repository's own counter-argument are
    #: both right, and they reconcile here.** Scored over resolved touches, a
    #: 0.5v stop with a 1.5v target returns +1.785R against +0.630R for the
    #: 1.05v/2.53v pair production actually places. But `min_stop_vol` exists
    #: because a stop inside one volatility unit sits inside the width of the
    #: estimate it protects and is taken by ordinary movement - with two live
    #: trades cited for it.
    #:
    #: They measure from different places. **The replay measures from the
    #: level, and a market entry is not at the level.** A 0.5v stop from the
    #: level is a real stop; the same stop from a fill already 0.3v past it is
    #: 0.2v of room and dies to noise. So the tighter stop is worth exactly
    #: what the entry is worth.
    #:
    #: A parked entry is the case where the fill *is* at the level - that is
    #: what waiting for it buys - so the grid's number applies there and
    #: nowhere else. Applied to any other entry it would be the mistake
    #: `min_stop_vol` was written to prevent.
    parked_stop_vol: float = 0.0

    #: Refuse a trade when the market around this level is choppier than this.
    #: Zero is off. See `structures.trend`.
    #:
    #: Measured 2026-08-27: levels in the most trending decile break 1.4% of
    #: the time and return 1.149R, against 11.3% and 0.807R in the chop. A
    #: trend does *not* run levels over - it makes them hold harder and pay
    #: more, so this is a pullback-in-trend effect and the obvious reading of
    #: "trade the trend" has the sign backwards.
    min_efficiency: float = 0.0

    #: How far either side of 1 the trend context may move position size.
    #: Zero is off. 0.3 gives 0.7x in flat chop and 1.3x in a clean trend.
    #:
    #: Preferred to the floor above, and shipped alongside it so the two can be
    #: compared. The relationship is continuous and monotonic across the top
    #: deciles, so a threshold throws away the middle; and a gate that turns
    #: out to be wrong shows up as nothing happening, which is the failure this
    #: repository keeps finding late. Bounded because 0.34R between extreme
    #: deciles justifies leaning, not doubling.
    trend_sizing: float = 0.0

    #: Volatility units the move must have turned back **in the trade's
    #: favour**, after a pullback, before the entry is taken. Zero is off.
    #:
    #: The stricter half of the momentum filter. `max_against_vol` refuses an
    #: entry while a run is still going against it; this requires the turn to
    #: have actually started. One removes the worst entries, the other insists
    #: on the better ones.
    #:
    #: **Only applied after a pullback, and that is not a detail.** Momentum at
    #: a level is adverse by construction - price arriving at support is
    #: falling, which is what arriving means - so requiring favourable momentum
    #: on arrival would refuse every support buy this system exists to take.
    #: After the pullback the same measurement means something else entirely:
    #: that the fall has not finished. The pullback is what separates the two
    #: readings, so the requirement rides on it.
    require_turn_vol: float = 0.0

    #: Require a candlestick rejection at the level before entering. Off by
    #: default.
    #:
    #: The record this answers to: an `inverse` buy on gold took its stop at
    #: 4591 and then ran to its target at 4604, and it was not alone - 23 of
    #: the first 32 trades were stopped, several of which later reached the
    #: price they were aiming at. The direction was not the thing that was
    #: wrong. The trade was entered because price was *near* a level, while
    #: the level had not finished being tested.
    #:
    #: A pattern is a claim about that: the auction reached a price, was
    #: rejected, and closed away from it inside one bar. It is confirmation of
    #: timing, and it costs the entries that never get confirmed - which is a
    #: real cost, not a free filter, and is what running it as a setting rather
    #: than a rewrite is meant to measure.
    require_candle: bool = False
    #: How close to the level the bar must come, in volatility units, to count
    #: as having tested it.
    candle_tolerance_vol: float = 0.25

    #: Multiple of the broker's own `stops_level` a stop must clear.
    #:
    #: The broker's minimum is not checked when the order is built, it is
    #: checked against the price at the moment the order lands - so a stop that
    #: satisfies it exactly at decision time is refused if the market moves a
    #: point in between. This was 1.1 hard-coded, and a eurgbp buy was refused
    #: with a stop of 0.00022 against a minimum of 0.00020: the margin was
    #: doing its job and 10% of a 20-point floor is two points, which a quiet
    #: cross covers between deciding and sending.
    #:
    #: The cost of raising it is a wider stop, which for the same money at
    #: risk buys a smaller position. That is the trade: a slightly smaller
    #: trade against no trade at all.
    stops_level_margin: float = 1.25
    #: R multiple at which part of the position comes off. Zero is off.
    #:
    #: The push distribution is wide - median 2.24v, p90 4.93v - and a single
    #: exit has to choose which half of it to serve. Taking part off at the
    #: modelled push and letting the rest run serves both: the common case is
    #: banked before it can be given back, and the tail is still owned. It is
    #: the honest version of `runner`, which bets the whole position on the
    #: tail and will pay for that in win rate.
    scale_out_at: float = 0.0
    #: How much of the position comes off there. Half by default.
    #:
    #: Bounded to (0, 1): at 1.0 this is a target, not a scale-out, and the
    #: remainder that makes the idea work would not exist.
    scale_out_fraction: float = 0.5
    #: Seconds after which a trade that has gone nowhere is closed flat. Zero
    #: is off.
    #:
    #: The median touch resolves in **eighteen seconds** and 84% inside five
    #: minutes, so a position still sitting at its entry well past that is not
    #: the event it was opened for. Holding it does not wait for the thesis; it
    #: waits for noise to reach the stop, which is a losing trade arrived at
    #: slowly. Closing flat costs the spread and keeps the rest.
    stale_after: float = 0.0
    #: How far the trade must have travelled by `stale_after` to count as
    #: having started, in R. Deliberately generous - this is meant to catch
    #: trades that did nothing at all, not trades that are merely behind.
    stale_move: float = 0.25
    #: How many times one stopped-out setup may be taken again. Zero is off.
    #:
    #: Six of twelve stopped trades later reached the target they were aiming
    #: at, by between 3.7R and 25.7R. That says the level survived being
    #: crossed, which is what a sweep looks like from the outside, and that the
    #: only thing the stop settled was that *this fill* was too early.
    #:
    #: What re-arms is the **signal**, not the intent, parked at the level and
    #: put back through every gate on arrival - so a setup that stopped being
    #: worth taking is refused like any other. Bounded because a level that
    #: keeps taking money is not a level worth arguing with.
    reentry_max: int = 0

    # ------------------------------------------- trading toward a level
    #: Nearest and furthest a target level may be, in volatility units. Closer
    #: than the minimum and it is the same structure we are standing on;
    #: further than the maximum and first-passage time makes it unreachable
    #: inside any hold a scalper would accept.
    approach_min_vol: float = 0.8
    approach_max_vol: float = 6.0
    #: Stop this far short of the target level, in volatility units. See
    #: `ApproachScalp` - this is what keeps the strategy off the one claim the
    #: repository has already measured and rejected.
    approach_buffer_vol: float = 0.25
    #: Least acceptable chance of covering the distance within the hold, from
    #: the first-passage model in `structures.timing`.
    #:
    #: **A floor against the absurd, not a forecast.** Diffusion is a null
    #: model and markets depart from it - magnet.md measured exactly that - so
    #: this is not the strategy's estimate of anything. It is here to refuse a
    #: level that a driftless walk would rarely reach inside the hold, which is
    #: the case where the target is simply too far away for the time allowed.
    #:
    #: 0.20 rather than something higher because of where the two gates meet.
    #: On 5m with a 45-minute hold there are nine bars, and a 35% floor caps
    #: the distance at about 3.5v - below `approach_max_vol`, which would make
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
    #: the most informative and the easiest to drown in - every gate doing its
    #: job produces one, and a halted day produces one per signal until the
    #: clock rolls over - so it is off unless asked for.
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
            min_base_rate=_float("TRADING_MIN_BASE_RATE", 0.0),
            probability_percentile=_float("TRADING_PROBABILITY_PERCENTILE", 0.0),
            evaluate_all=_flag("TRADING_EVALUATE_ALL", "0"),
            consensus_min=_int("TRADING_CONSENSUS_MIN", 2),
            thesis_stop_vol=_float("TRADING_THESIS_STOP_VOL", 4.0),
            min_edge=_float("TRADING_MIN_EDGE", 0.15),
            loss_cooldown=_float("TRADING_LOSS_COOLDOWN_S", 900.0),
            max_hold=_float("TRADING_MAX_HOLD_S", 1_800.0),
            hold_extends_at=_float("TRADING_HOLD_EXTENDS_AT", 0.0),
            max_hold_multiple=_float("TRADING_MAX_HOLD_MULTIPLE", 4.0),
            news_before=_float("TRADING_NEWS_BEFORE_S", 600.0),
            news_after=_float("TRADING_NEWS_AFTER_S", 900.0),
            max_dislocation_bps=_float("TRADING_MAX_DISLOCATION_BPS", 8.0),
            max_spread_ratio=_float("TRADING_MAX_SPREAD_RATIO", 2.5),
            drift_pause=_float("TRADING_DRIFT_PAUSE_S", 900.0),
            max_currency_exposure=_float("TRADING_MAX_CURRENCY_EXPOSURE", 0.005),
            min_stop_vol=_float("TRADING_MIN_STOP_VOL", 1.0),
            max_chase_vol=_float("TRADING_MAX_CHASE_VOL", 1.0),
            shadow_window=_float("TRADING_SHADOW_WINDOW", 1.0),
            stop_hold_scaling=_float("TRADING_STOP_HOLD_SCALING", 0.0),
            max_stop_scale=_float("TRADING_MAX_STOP_SCALE", 3.0),
            pullback_fraction=_float("TRADING_PULLBACK_FRACTION", 0.0),
            pullback_bars=_float("TRADING_PULLBACK_BARS", 10.0),
            pullback_sigmas=_float("TRADING_PULLBACK_SIGMAS", 0.5),
            pullback_min_wicks=_float("TRADING_PULLBACK_MIN_WICKS", 2.0),
            pullback_max_vol=_float("TRADING_PULLBACK_MAX_VOL", 4.0),
            pullback_min_gain=_float("TRADING_PULLBACK_MIN_GAIN", 0.25),
            pullback_min_sweep_rate=_float("TRADING_PULLBACK_MIN_SWEEP_RATE", 0.10),
            sweep_max_rate=_float("TRADING_SWEEP_MAX_RATE", 0.35),
            sweep_min_history=_float("TRADING_SWEEP_MIN_HISTORY", 6.0),
            sweep_max_exposure=_float("TRADING_SWEEP_MAX_EXPOSURE", 0.8),
            fade_min_touches=_float("TRADING_FADE_MIN_TOUCHES", 4.0),
            fade_max_distance_vol=_float("TRADING_FADE_MAX_DISTANCE_VOL", 8.0),
            fade_min_distance_vol=_float("TRADING_FADE_MIN_DISTANCE_VOL", 1.5),
            fade_buffer_vol=_float("TRADING_FADE_BUFFER_VOL", 0.25),
            council_quorum=_int("TRADING_COUNCIL_QUORUM", 2),
            council_min_conviction=_float("TRADING_COUNCIL_MIN_CONVICTION", 0.55),
            council_discuss=_flag("TRADING_COUNCIL_DISCUSS", "1"),
            council_timeout=_float("TRADING_COUNCIL_TIMEOUT_S", 25.0),
            council_daily_calls=_int("TRADING_COUNCIL_DAILY_CALLS", 400),
            break_even_at=_float("TRADING_BREAK_EVEN_AT", 0.0),
            break_even_ticks=_int("TRADING_BREAK_EVEN_TICKS", 2),
            trail_vol=_float("TRADING_TRAIL_VOL", 0.0),
            trail_sigmas=_float("TRADING_TRAIL_SIGMAS", 0.5),
            stop_slippage=_float("TRADING_STOP_SLIPPAGE", 0.0),
            max_push_vol=_float("TRADING_MAX_PUSH_VOL", 25.0),
            hold_max_spread=_float("TRADING_HOLD_MAX_SPREAD", 0.0),
            parked_stop_vol=_float("TRADING_PARKED_STOP_VOL", 0.0),
            min_efficiency=_float("TRADING_MIN_EFFICIENCY", 0.0),
            trend_sizing=_float("TRADING_TREND_SIZING", 0.0),
            require_turn_vol=_float("TRADING_REQUIRE_TURN_VOL", 0.0),
            require_candle=_flag("TRADING_REQUIRE_CANDLE", "0"),
            candle_tolerance_vol=_float("TRADING_CANDLE_TOLERANCE_VOL", 0.25),
            stops_level_margin=_float("TRADING_STOPS_LEVEL_MARGIN", 1.25),
            scale_out_at=_float("TRADING_SCALE_OUT_AT", 0.0),
            scale_out_fraction=_float("TRADING_SCALE_OUT_FRACTION", 0.5),
            stale_after=_float("TRADING_STALE_AFTER_S", 0.0),
            stale_move=_float("TRADING_STALE_MOVE", 0.25),
            reentry_max=_int("TRADING_REENTRY_MAX", 0),
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
    contract was priced as 100,000 units - a stop that should cost $440 a lot
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
