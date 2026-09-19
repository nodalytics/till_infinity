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
from pathlib import Path

from ..prices.models import slugify
from ..shared.env import env as _env
from ..shared.env import flag as _flag
from ..shared.env import number as _float
from ..shared.env import whole as _int
from ..structures.drawing import confluence

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
#: Broker-only instruments, by their exact name on the account.
#:
#: Synthetics have no underlying, so no venue outside the broker quotes them
#: and no alias guessing is possible or wanted: `Volatility 75 Index` is the
#: only name that resolves. The feed slug is derived the same way
#: `prices.broker_feeds` derives it, so one instrument has one name on both
#: sides of the bus.
#:
#: They also never close - measured quoting normally on a Saturday with every
#: real market on the account hours stale - which makes them the only thing
#: here a weekend session gate has nothing to say about.
SYNTHETICS: tuple[str, ...] = (
    "Volatility 10 Index",
    "Volatility 25 Index",
    "Volatility 50 Index",
    "Volatility 75 Index",
    "Volatility 100 Index",
    "Step Index",
    "Boom 500 Index",
    "Boom 1000 Index",
    "Crash 1000 Index",
    # Added 2026-08-30 on the cost screen in research/catalogue.md. Every one
    # of these costs the same or less to cross than the nine above - 0.116v to
    # 0.199v against their 0.075v to 0.244v - measured in volatility units,
    # which is the only currency that compares across instruments. In points
    # the synthetics look ten times dearer than FX and the ordering inverts.
    "Range Break 100 Index",
    "Range Break 200 Index",
    "Jump 10 Index",
    "Jump 25 Index",
    "Crash 300 Index",
    "Crash 500 Index",
    # The one-second variants. Same generated processes, ticking every second
    # rather than every two, so they carry roughly twice the quote rate for the
    # same structure - the cost worth watching here is bus traffic, not spread.
    "Volatility 10 (1s) Index",
    "Volatility 25 (1s) Index",
    "Volatility 50 (1s) Index",
    "Volatility 75 (1s) Index",
    "Volatility 100 (1s) Index",
)


def broker_slug(name: str) -> str:
    """`Volatility 75 Index` -> `volatility_75_index`.

    The one place a broker symbol becomes a feed name. Every table that has to
    agree - instruments, exposure legs, price feeds - derives its key from
    here, so they cannot drift apart the way a second hand-written list does.
    """
    return slugify(name).lower()


def register_broker_instruments(names: Sequence[str]) -> tuple[str, ...]:
    """Make broker symbols tradable. Returns the feed names added.

    An instrument needs four things to be traded here: a name the broker
    answers to, an exposure leg, a price feed, and a place in the symbol list.
    All four were written by hand for nine synthetics, in three files, keyed on
    a slug each computed for itself - which is three chances to disagree and no
    way to notice.

    This is the generated form. The broker's own name is the only alias,
    because for an instrument nothing else quotes there is nothing to guess at.

    **Not the whole catalogue.** The account lists 798 symbols and level
    building scales with feeds times timeframes, so what is registered is what
    is asked for. Naming them is the operator's decision; keeping the four
    tables in step is not.
    """
    from .exposure import register_broker_legs

    added: list[str] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        slug = broker_slug(name)
        if not slug or slug in INSTRUMENTS:
            continue
        INSTRUMENTS[slug] = (name,)
        added.append(slug)
    register_broker_legs(added)
    return tuple(added)


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

DEFAULT_TRADING_DIR = ".data/trading"
DEFAULT_API_PATH = "/api/v1"

#: Stop overshoot that applies with no configuration at all - see the
#: `Settings.stop_overshoot` note for the measurement and for why 2.0 is a floor
#: rather than the answer. Boom spikes up, so its gapped stop is a sell's; Crash
#: spikes down, so it is a buy's.
DEFAULT_STOP_OVERSHOOT: tuple[tuple[str, float], ...] = tuple(
    (f"{family}_{size}_index.{side}", 2.0)
    for family, side in (("boom", "sell"), ("crash", "buy"))
    for size in (300, 500, 1000)
)

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
    # Removed 2026-08-28 as a near-duplicate of `swing-level`, which shares its
    # entries, context and higher-timeframe requirement; its resting entry and
    # horizon-scaled protection moved there. The slot stays reserved because
    # this table is append-only - a magic that has been on live orders has to
    # keep resolving to the name that placed them.
    "high-timeframe",
    "origin-swing",
    # 2026-09-02. The nine above are points in one parameter space and this is
    # the space itself; see `trading/opportunity.py`. Appended like every other
    # slot, because a magic that has been on a live order has to keep resolving
    # to the name that placed it.
    "opportunity",
    # 2026-09-03. `opportunity` with the target moved out of reach so the trail
    # decides - the measured best exit policy of six tested. See `Ride`.
    "ride",
    # 2026-09-14. Unified scalp thesis: trend context from 4h/1h and the
    # fast pullback entry from 15m/1m, with sweep-aware geometry guarding the
    # stop. Appended to preserve the strategy attribution table's append-only
    # contract.
    "cycle-scalp",
    # 2026-09-15. The cycle reading as an entry rather than a veto, gated on
    # that feed's own scored record - see `strategies/turning.py`. Appended,
    # never inserted: a magic that has been on a live order has to keep
    # resolving to the name that placed it.
    #
    # It shipped for one commit without this line, and the test below caught
    # it. Two earlier strategies did not get caught and ran live for an hour
    # each; their trades are unattributable in the record for ever.
    "cycle-turn",
    # 2026-09-16. `cycle-turn` one tier down and one condition looser: a 1h
    # mother cycle over 15m/30m, entries from 1m to 15m, gated on the
    # z-score's *displacement* rather than on displacement-plus-momentum -
    # which fires on 1.5% of calls and is why `cycle-turn` has never traded.
    # Agreement sizes the trade instead of gating it. See
    # `strategies/stretching.py`. Appended, never inserted.
    "cycle-turn-scalp",
)


#: The synthetics carried by default. A list rather than the whole catalogue
#: for the reason `register_broker_instruments` gives, and here rather than in
#: the environment so a deployment that says nothing still gets the instruments
#: this repository has measured.
register_broker_instruments(SYNTHETICS)


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


def _overshoot(raw: str) -> tuple[tuple[str, float], ...]:
    """`feed=multiple` pairs, optionally keyed by side: `boom_500_index.sell=12`.

    **The side matters and a per-feed number is wrong on a jump instrument.**
    On `boom_500_index`, 84,506 of 84,701 tick moves are down and 162 are up, of
    which 160 are spikes - so a stop above price can never be *walked* to, only
    jumped over, while a stop below behaves normally. Measured in
    `research/generators.md`: the spike side overshoots by **+9.9R to +19.1R**
    and the grind side by **+0.02R**. One number for the feed would either leave
    the tail unsized or shrink the side that works.

    A bare `feed=` still applies to both sides, so existing settings are
    unchanged.

    A malformed pair is dropped rather than raised on: this is a sizing
    reduction, and a typo in it should cost the correction, not the desk.

    `none` turns the correction off entirely, and exists so that "unset" and
    "deliberately empty" are different instructions. Without it an unset
    variable would have to mean no scaling, which would silently discard
    `DEFAULT_STOP_OVERSHOOT` - the exact drift `DEFAULT_FORMATION` was named to
    stop, where a field default and its environment fallback disagreed and the
    deployment got whichever one `from_env` happened to say.
    """
    if raw.strip().lower() in ("none", "off"):
        return (("", 0.0),)
    out: list[tuple[str, float]] = []
    for part in raw.split(","):
        name, _, value = part.partition("=")
        try:
            out.append((name.strip().lower(), float(value)))
        except ValueError:
            continue
    return tuple(out)


def _names(raw: str) -> tuple[str, ...]:
    """A comma list from a raw **value**, lower-cased.

    Deliberately not `shared.env.names`, which takes a variable *name* and
    does not lower-case. Symbols and strategy names are matched case-blind
    here and the shared reader is used where the caller has the variable
    rather than its value.
    """
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
    #: The two the desk actually runs. `cycle-scalp` is the unified scalp
    #: thesis - 4h bias, 1h structure, fast pullback entry - and `cycle-turn`
    #: is the slower reversion trade that the 4h cycle has to agree with, on a
    #: feed whose 4h record earns a say.
    #: Measured; see `research/docs/settings.md`.
    strategies: tuple[str, ...] = ("cycle-turn", "cycle-turn-scalp", "cycle-scalp")
    #: The named risk plan. Individual limits set in the environment win over
    #: it - see `plans`.
    risk_plan: str = "standard"
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    #: Timeframes the service will *accept*. Every one a level forms on, by
    #: default - the restriction belongs to the strategy, not to the module.
    #: Measured; see `research/docs/settings.md`.
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
    #: Minimum reward-to-risk from the *quoted* entry, spread included.
    #: Measured; see `research/docs/settings.md`.
    min_reward_to_risk: float = 0.0
    #: A scalp whose spread eats this much of its own target is not a trade.
    max_spread_fraction: float = 0.25
    #: And the same question against the **risk**, which is the denominator the
    #: damage was measured in.
    #: Measured; see `research/docs/settings.md`.
    max_spread_risk_fraction: float = 0.16
    #: The signal's own confidence, and its separation from the base rate.
    #: `structures` already gates on `actionable`, but that threshold exists to
    #: decide whether to *tell someone*. Deciding whether to put money on it is
    #: a different question and gets its own number.
    min_probability: float = 0.58
    #: How often the level must hold in the claimed direction, unconditionally.
    #: Measured; see `research/docs/settings.md`.
    min_base_rate: float = 0.0
    #: Where to sit in each direction's *own* distribution of claimed
    #: probability, in [0, 1]. Zero uses `min_probability` alone.
    #: Measured; see `research/docs/settings.md`.
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
    #: Let **every** strategy that wants a signal take it, rather than the
    #: first one in the running order.
    #: Measured; see `research/docs/settings.md`.
    parallel: bool = False
    #: How many strategies must want the same side before the trade is rebuilt
    #: from what they collectively asked for. Zero or one disables it.
    #: Measured; see `research/docs/settings.md`.
    consensus_min: int = 2
    #: Where `thesis-only` puts its stop, in volatility units.
    #: Measured; see `research/docs/settings.md`.
    thesis_stop_vol: float = 4.0

    #: The floor on |edge|, and it has to sit **above** `reactions.MIN_EDGE`
    #: or it is configuration that can never fire - every signal reaching the
    #: bus has already cleared that gate. The first version of this module set
    #: it to 0.08, which is below the 0.10 upstream and therefore did nothing.
    #: Measured; see `research/docs/settings.md`.
    min_edge: float = 0.15
    #: Seconds before the same instrument may be traded again after a loss.
    #: A level that just took money is the level most likely to take it again.
    loss_cooldown: float = 900.0
    #: Seconds a scalp may stay open before it is closed regardless. A scalp
    #: that has been open an hour has become a swing trade nobody planned.
    #: A strategy may ask for longer - see `Strategy.hold_seconds` - because
    #: this default is a property of the trade being taken, not of the module.
    #: The longest a **scalp** may be held, in seconds.
    #: Measured; see `research/docs/settings.md`.
    max_hold: float = 1_800.0

    #: The longest a **swing** may be held, in seconds. Six hours.
    #: Measured; see `research/docs/settings.md`.
    max_hold_swing: float = 21_600.0

    #: The longest a **position** may be held, in seconds. Four days.
    #:
    #: A third ceiling, because two did not cover the thesis `cycle-turn`
    #: trades. Its entry is 15m to 1h and its context is 4h and 1d, so the move
    #: it is betting on takes days rather than hours - and capped by the swing
    #: ceiling it would have been closed by the clock at six hours, which
    #: `research/spending.md` already measured as how `snap` loses: ended by
    #: the timer rather than by being right or wrong, which teaches the journal
    #: nothing.
    #:
    #: Four days rather than three so a Friday entry can survive a weekend gap
    #: on instruments that have one; the strategy asks for 72 hours and this is
    #: the ceiling over it.
    max_hold_position: float = 4 * 24 * 3_600.0

    min_hold: float = 0.0

    #: How much of its size a position keeps for each open position sharing a
    #: currency leg the same way round. Zero is off, 0.5 halves the second on a
    #: leg and quarters the third.
    #: Measured; see `research/docs/settings.md`.
    crowding_share: float = 0.0

    #: The instrument volatility this book is sized for, in basis points. Zero
    #: is off. Above it a trade is scaled by the ratio, so twice the volatility
    #: is half the size.
    #:
    #: **Only ever reduces.** A quiet instrument does not get a larger
    #: position: the stop already widens with volatility so the money at risk
    #: is constant either way, and what this adds is a cap on how much of the
    #: portfolio one violent instrument can represent. Sizing *up* into calm is
    #: how a book discovers that the calm was the beginning of something.
    volatility_target_bps: float = 0.0

    #: The net edge, in volatility units, that earns full size. Zero is off.
    #: Measured; see `research/docs/settings.md`.
    regime_band: float = 0.0
    #: The most `by_regime` may reduce by. A scaler that can reach zero is a
    #: gate wearing a multiplier's clothes, and seven points of held rate does
    #: not justify a veto.
    regime_floor: float = 0.5

    edge_full_at: float = 0.0

    #: What a stop actually costs on an instrument, in R, as `feed=multiple`
    #: pairs. Anything unlisted is 1.0 and unscaled.
    #: Measured; see `research/docs/settings.md`.
    stop_overshoot: tuple[tuple[str, float], ...] = DEFAULT_STOP_OVERSHOOT

    #: Risk multiplier per entry timeframe, as `interval=weight` pairs.
    #: Anything unlisted sizes at full. See `scaling.by_interval` for the
    #: measured table this comes from - sub-15m is -821.75 over 129 closes
    #: against +35.03 over 21 at 15m and above.
    interval_weight: tuple[tuple[str, float], ...] = ()

    #: Drawdown from the equity peak at which size reaches its floor. Zero is
    #: off.
    #:
    #: `daily_loss_limit` is a cliff - full size until it fires, then nothing.
    #: This is the ramp to it. Square-root rather than linear so the first
    #: losses barely register: a book that tapers hard on a 2% dip cannot
    #: recover, because it is trading a quarter size exactly when the edge it
    #: was sized for is still there.
    drawdown_halt_at: float = 0.0

    #: R in front at which the hold stops applying. Zero keeps the old rule:
    #: the clock closes everything, whatever it is doing.
    #: Measured; see `research/docs/settings.md`.
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
    #: Measured; see `research/docs/settings.md`.
    max_chase_vol: float = 1.0

    #: How far toward the stop's price the entry is moved, as a fraction.
    #: Measured; see `research/docs/settings.md`.
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
    #: Measured; see `research/docs/settings.md`.
    stop_hold_scaling: float = 0.0
    #: Ceiling on that multiplier. Uncapped, a thirty-bar hold asks for a stop
    #: 5.5 times wider and a position 5.5 times smaller, and `reward_to_risk`
    #: then refuses nearly everything - which may be the honest answer but is
    #: not one to arrive at by accident.
    max_stop_scale: float = 3.0

    #: The least a stop may sit from the level, in volatility units.
    #: Measured; see `research/docs/settings.md`.
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

    # ------------------------------------------------ the z-score's directional veto
    #: Whether `cycle-scalp` may refuse a call the attention-weighted z-score is
    #: leaning against. Off, and it should stay off until the scored record in
    #: `structures.zma.Book.standings` says the agreement call beats a coin on
    #: the instruments this desk actually trades. It is the trading-side twin of
    #: `STRUCTURES_ZMA_ACTS` and deliberately a separate switch: `structures`
    #: recording a signal and `trading` obeying one are different decisions, and
    #: the package boundary here is that `trading` reads signals off the bus and
    #: never touches the level engine.
    zma_gate: bool = False
    #: Scored continuous calls a feed needs before the gate believes its record
    #: at all. `structures.zma.WARM` is 200 and this matches it: the agreement
    #: condition is strict enough that a series makes one call every forty-odd
    #: bars, so 200 is months on a slow timeframe and hours on a fast one.
    zma_min_calls: float = 200.0
    #: And how far above a coin that record has to be. At 0.50 the gate would
    #: fire on feeds where the reading is worthless; the margin is what keeps a
    #: hundred coin flips from reading as evidence.
    zma_min_accuracy: float = 0.52

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
    #: Measured; see `research/docs/settings.md`.
    stop_slippage: float = 0.0

    #: How much of normal size a trade takes when momentum is not confirming
    #: it. One is off - every trade takes full size regardless.
    #: Measured; see `research/docs/settings.md`.
    unconfirmed_size: float = 1.0

    #: Seconds without a quote before a feed is treated as a shut market
    #: rather than a refusing broker. Zero is off.
    #: Measured; see `research/docs/settings.md`.
    stale_quote_after: float = 300.0

    #: How many 15-minute bars to read per instrument when learning session
    #: hours at start-up. 1,400 covers about three weeks for an index, which is
    #: enough to see every weekday several times and let a holiday be outvoted.
    #: Zero disables the learning, and with it the closing gate.
    session_bars: int = 1400

    #: Pull the target this many volatility units short of where it was aimed.
    #: Measured; see `research/docs/settings.md`.
    target_buffer_vol: float = 0.0

    #: Rest the entry this many volatility units better than the quote.
    #: Measured; see `research/docs/settings.md`.
    entry_pending: bool = False

    #: Distinct from `pullback_fraction`, which waits for the **sweep edge** -
    #: a retracement that measured 189 signals of 813 reaching the wait and
    #: none of them parking, because by then the fill was already past it. This
    #: rests at a measured depth instead of at a computed edge.
    #: Measured; see `research/docs/settings.md`.
    entry_edge_vol: float = 0.0

    #: Extra terminals that copy every decision, as
    #: `name=url[|api_key]` entries. Empty means one terminal, as before.
    #:
    #: **Copy mode.** The strategy decides once and each account re-sizes the
    #: trade against its own equity - risk is replicated, lots never are. See
    #: `replicate.py`, and `docs/todo.md` 6i for why the other mode inverts
    #: several of these answers.
    followers: tuple[str, ...] = ()

    #: Broker-only instruments to carry, by their exact names.
    #:
    #: The **same** variable `prices` reads, deliberately. An instrument needs
    #: a price feed and a tradable entry and an exposure leg, and two lists
    #: would let a deployment have one without the others - a feed that quotes
    #: and cannot be traded, or an instrument that resolves and has no prices.
    broker_symbols: tuple[str, ...] = ()

    #: Which kind of trading to run: `scalp`, `swing`, `both` or `none`.
    #: Measured; see `research/docs/settings.md`.
    style: str = "both"

    #: Refuse a trade whose hold does not fit before its market closes, plus
    #: this much margin, in seconds.
    #: Measured; see `research/docs/settings.md`.
    session_margin: float = 60.0

    #: The largest expected push a call may claim, in volatility units. Beyond
    #: this the number is not a forecast, it is a fault.
    #: Measured; see `research/docs/settings.md`.
    max_push_vol: float = 25.0

    #: Defer the hold-clock close while the spread is this multiple of the
    #: trade's own risk distance or wider. Zero closes on the clock regardless.
    #: Measured; see `research/docs/settings.md`.
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
    #:
    #: **What it does, measured rather than argued** (gold at 4400, one unit
    #: $4.40, `snap`, entry parked below its support):
    #:
    #:     fill past the level    off      at 0.5v
    #:     0.0v                   1.11v    0.61v risk, R:R 1.26 -> 2.28
    #:     0.3v                   1.00v    0.50v risk, R:R 1.40 -> 2.80
    #:     0.6v                   1.00v    0.50v risk, R:R 1.40 -> 2.80
    #:     1.0v                   1.00v    refused, "through"
    #:
    #: Half the risk for the same target doubles the ratio and doubles the
    #: size for the same money at stake - 0.05 lots to 0.11.
    #:
    #: **The refusal at 1.0v is the cost and it is not a bug.** A long filling
    #: a full volatility unit below its support has a fill past the price the
    #: stop is anchored to; with the wide stop that trade is taken and with the
    #: tight one it is not. That is what a tight stop means. It matters because
    #: `entry_edge_vol` parked 1.5v better than the market against a median
    #: entry 0.91v from its level, so a typical rest filled ~0.6v past it -
    #: safe - while the quartile already close to its level filled past 1.0v
    #: and was refused: roughly a quarter of resting fills, declined rather
    #: than taken with a stop already behind price. At the 0.5v it was lowered
    #: to on 2026-09-01 that arithmetic reverses - a typical rest now fills
    #: ~0.4v *short* of the level rather than past it - so this refusal should
    #: become rare. Predicted, not measured; the parked sample is 13 trades.
    #:
    #: Bounded to holds under `Scalper.PARKED_STOP_HOLD` (300s) whatever this
    #: says, which is what keeps a short-hold grid's number off a swing.
    #:
    #: **Turned off in production on 2026-08-31, and the reason is worth
    #: keeping.** Gold is nearly half the account's loss, its median hold is 95
    #: seconds - so it qualifies for this - and 62% of its stopped trades
    #: reached target *after* being stopped, against 26% across the book. Its
    #: stops are already too tight, and this halves them again. The arithmetic
    #: above is correct and was measured on the pooled record; gold is the
    #: instrument it is wrong for. See research/stops.md.
    #: Refuse a level call whose chance of giving way is above this. Zero is
    #: off.
    #:
    #: `structures/breaking.py` publishes `break_probability` from the arrival
    #: speed and the depth of the touch - a different question from the
    #: direction every other gate reads, and demonstrably so: `up_rate`, which
    #: carries almost all of direction, predicts a break at AUC 0.4928.
    #:
    #: **0.42 is the measured top fifth.** Over 10,977 resolved touches at five
    #: to thirty minutes, the highest fifth by this estimate breaks 43.2% of
    #: the time against the lowest fifth's 16.9% - so the level's call is right
    #: 56.8% there against 83.1% at the other end.
    #:
    #: **Refusing, not inverting.** Flipping the trade in that fifth was
    #: measured and loses: the call is still right more often than not even
    #: where it is weakest, so an inversion turns 56.8% into 43.2%. That was
    #: worth testing and the answer was no.
    #:
    #: Off by default because a gate that refuses trades should be turned on
    #: deliberately, and because the numbers behind it were wrong once already
    #: - `trap` was grouped with `break`, which put the break rate at 55.6%
    #: instead of 32.3%. See research/force.md.
    max_break_risk: float = 0.0

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
    #: Measured; see `research/docs/settings.md`.
    max_against_vol: float = 0.0

    #: The stricter half of the momentum filter. `max_against_vol` refuses an
    #: entry while a run is still going against it; this requires the turn to
    #: have actually started. One removes the worst entries, the other insists
    #: on the better ones.
    #: Measured; see `research/docs/settings.md`.
    require_turn_vol: float = 0.0

    #: Require a candlestick rejection at the level before entering. Off by
    #: default.
    #: Measured; see `research/docs/settings.md`.
    require_candle: bool = False
    #: How close to the level the bar must come, in volatility units, to count
    #: as having tested it.
    candle_tolerance_vol: float = 0.25

    #: Multiple of the broker's own `stops_level` a stop must clear.
    #: Measured; see `research/docs/settings.md`.
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
    #: Measured; see `research/docs/settings.md`.
    stale_after: float = 0.0
    #: How far the trade must have travelled by `stale_after` to count as
    #: having started, in R. Deliberately generous - this is meant to catch
    #: trades that did nothing at all, not trades that are merely behind.
    stale_move: float = 0.25
    #: How many times one stopped-out setup may be taken again. Zero is off.
    #: Measured; see `research/docs/settings.md`.
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
    #: Measured; see `research/docs/settings.md`.
    approach_min_reach: float = 0.20

    # ------------------------------------------------------------- plumbing
    #: Refuse to keep trading if the terminal stops answering.
    #: Where the open positions' high-water marks are kept between restarts.
    #: The only thing this service needs to survive one - see `Trader._marks`.
    state_dir: Path = field(default_factory=lambda: Path(DEFAULT_TRADING_DIR))
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
    #: Whether a resting entry is announced when it is placed and when it is
    #: taken back.
    #:
    #: On by default, unlike declines, because an order left with the broker is
    #: money committed while nobody is looking: it can fill on the terminal's
    #: own tick with this process asleep, so the one thing a person needs is to
    #: know it is out there and to know when it is not.
    notify_rests: bool = True
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
        # Registered before the settings exist, so the instrument, its exposure
        # leg and its price feed are all in place before anything resolves it.
        # One list drives all three; two would let a deployment have a feed
        # that quotes and cannot be traded.
        # Split but not lowered: a broker symbol is `Volatility 75 Index` and
        # that exact string is what the terminal answers to. The slug derived
        # from it is what everything here keys on.
        carried = tuple(
            n.strip() for n in (_env("PRICES_BROKER_SYMBOLS") or "").split(",") if n.strip()
        )
        if carried:
            register_broker_instruments(carried)
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
            min_reward_to_risk=_float("TRADING_MIN_RR", 0.0),
            max_spread_fraction=_float("TRADING_MAX_SPREAD_FRACTION", 0.25),
            max_spread_risk_fraction=_float("TRADING_MAX_SPREAD_RISK_FRACTION", 0.16),
            min_probability=_float("TRADING_MIN_PROBABILITY", 0.58),
            min_base_rate=_float("TRADING_MIN_BASE_RATE", 0.0),
            probability_percentile=_float("TRADING_PROBABILITY_PERCENTILE", 0.0),
            evaluate_all=_flag("TRADING_EVALUATE_ALL", False),
            parallel=_flag("TRADING_PARALLEL", False),
            consensus_min=_int("TRADING_CONSENSUS_MIN", 2),
            thesis_stop_vol=_float("TRADING_THESIS_STOP_VOL", 4.0),
            min_edge=_float("TRADING_MIN_EDGE", 0.15),
            loss_cooldown=_float("TRADING_LOSS_COOLDOWN_S", 900.0),
            max_hold=_float("TRADING_MAX_HOLD_S", 1_800.0),
            min_hold=_float("TRADING_MIN_HOLD_S", 0.0),
            max_hold_swing=_float("TRADING_MAX_HOLD_SWING_S", 21_600.0),
            max_hold_position=_float("TRADING_MAX_HOLD_POSITION_S", 4 * 24 * 3_600.0),
            crowding_share=_float("TRADING_CROWDING_SHARE", 0.0),
            volatility_target_bps=_float("TRADING_VOLATILITY_TARGET_BPS", 0.0),
            regime_band=_float("TRADING_REGIME_BAND", 0.0),
            regime_floor=_float("TRADING_REGIME_FLOOR", 0.5),
            edge_full_at=_float("TRADING_EDGE_FULL_AT", 0.0),
            drawdown_halt_at=_float("TRADING_DRAWDOWN_HALT_AT", 0.0),
            # `or` the default, like `formation` above: an unset variable means
            # "whatever was measured", not "no correction". `none` is how a
            # deployment says no correction and get an empty table.
            stop_overshoot=_overshoot(_env("TRADING_STOP_OVERSHOOT")) or DEFAULT_STOP_OVERSHOOT,
            interval_weight=_overshoot(_env("TRADING_INTERVAL_WEIGHT")),
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
            zma_gate=_flag("TRADING_ZMA_GATE", False),
            zma_min_calls=_float("TRADING_ZMA_MIN_CALLS", 200.0),
            zma_min_accuracy=_float("TRADING_ZMA_MIN_ACCURACY", 0.52),
            fade_min_touches=_float("TRADING_FADE_MIN_TOUCHES", 4.0),
            fade_max_distance_vol=_float("TRADING_FADE_MAX_DISTANCE_VOL", 8.0),
            fade_min_distance_vol=_float("TRADING_FADE_MIN_DISTANCE_VOL", 1.5),
            fade_buffer_vol=_float("TRADING_FADE_BUFFER_VOL", 0.25),
            council_quorum=_int("TRADING_COUNCIL_QUORUM", 2),
            council_min_conviction=_float("TRADING_COUNCIL_MIN_CONVICTION", 0.55),
            council_discuss=_flag("TRADING_COUNCIL_DISCUSS", True),
            council_timeout=_float("TRADING_COUNCIL_TIMEOUT_S", 25.0),
            council_daily_calls=_int("TRADING_COUNCIL_DAILY_CALLS", 400),
            break_even_at=_float("TRADING_BREAK_EVEN_AT", 0.0),
            break_even_ticks=_int("TRADING_BREAK_EVEN_TICKS", 2),
            trail_vol=_float("TRADING_TRAIL_VOL", 0.0),
            trail_sigmas=_float("TRADING_TRAIL_SIGMAS", 0.5),
            stop_slippage=_float("TRADING_STOP_SLIPPAGE", 0.0),
            unconfirmed_size=_float("TRADING_UNCONFIRMED_SIZE", 1.0),
            stale_quote_after=_float("TRADING_STALE_QUOTE_AFTER_S", 300.0),
            session_bars=_int("TRADING_SESSION_BARS", 1400),
            broker_symbols=carried,
            target_buffer_vol=_float("TRADING_TARGET_BUFFER_VOL", 0.0),
            entry_edge_vol=_float("TRADING_ENTRY_EDGE_VOL", 0.0),
            entry_pending=_flag("TRADING_ENTRY_PENDING"),
            followers=_names(_env("TRADING_FOLLOWERS")),
            style=_env("TRADING_STYLE") or "both",
            session_margin=_float("TRADING_SESSION_MARGIN_S", 60.0),
            max_push_vol=_float("TRADING_MAX_PUSH_VOL", 25.0),
            hold_max_spread=_float("TRADING_HOLD_MAX_SPREAD", 0.0),
            parked_stop_vol=_float("TRADING_PARKED_STOP_VOL", 0.0),
            max_break_risk=_float("TRADING_MAX_BREAK_RISK", 0.0),
            min_efficiency=_float("TRADING_MIN_EFFICIENCY", 0.0),
            trend_sizing=_float("TRADING_TREND_SIZING", 0.0),
            max_against_vol=_float("TRADING_MAX_AGAINST_VOL", 0.0),
            require_turn_vol=_float("TRADING_REQUIRE_TURN_VOL", 0.0),
            require_candle=_flag("TRADING_REQUIRE_CANDLE", False),
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
            state_dir=Path(os.environ.get("TRADING_DIR") or DEFAULT_TRADING_DIR),
            heartbeat=_float("TRADING_HEARTBEAT_S", 60.0),
            notify=_flag("TRADING_NOTIFY", True),
            notify_fills=_flag("TRADING_NOTIFY_FILLS", True),
            notify_closes=_flag("TRADING_NOTIFY_CLOSES", True),
            notify_rests=_flag("TRADING_NOTIFY_RESTS", True),
            notify_declines=_flag("TRADING_NOTIFY_DECLINES", False),
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
