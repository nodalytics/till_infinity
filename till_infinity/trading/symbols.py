"""Which of the instruments we watch can actually be traded here.

The price side names an instrument once - `gold`, `btc` - and six venues quote
it. A broker names it whatever it likes: `XAUUSD`, `GOLD`, `XAUUSD.raw`,
`BTCUSD` or nothing at all, because plenty of retail MT5 accounts that carry
gold and bitcoin carry neither Solana nor the Nasdaq under any name.

So availability is *discovered*, once, at start-up, and the result is a plain
mapping from feed name to broker symbol that everything downstream uses. Doing
it at start-up rather than at the moment of firing is the whole point: an
instrument that cannot be traded should be reported while nobody is waiting on
it, not turned into a rejected order three days later when a level finally
fires.

There are two ways to find out, and the better one is used when it is
available.

**Scan, if the broker can list its symbols.** The native terminal can -
`symbols_get()` returns the whole tree - and then the account's suffix does not
have to be guessed at all: `XAUUSD.s` is found by looking, whatever `.s` means
at that broker. This matters because the suffix is not a standard. `.raw`,
`.r`, `.s`, `m`, `+`, `_SB`, `.ecn`, `.z` are all in use, brokers invent more,
and no list of them can be complete. A scan has no list to be incomplete.

**Probe, when it cannot.** The HTTP bridge's only symbol route takes one name,
so there the candidates are tried in turn - and the suffix is *learned* rather
than enumerated. The full cross-product is twenty-odd suffixes against several
names for fourteen instruments, which is hundreds of round trips; noticing that
`XAUUSD.raw` worked and trying `.raw` first for everything after it makes each
of the remaining thirteen a single probe. The list is still walked in full for
the first instrument, and for any later one the learned suffix does not fit, so
an inconsistent broker is still found - just more slowly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..logging import get_logger
from .broker import Broker
from .config import INSTRUMENTS, SUFFIXES, Settings
from .models import SymbolSpec

log = get_logger(__name__)


@dataclass(slots=True)
class Resolution:
    """What the broker turned out to offer, and what it did not."""

    found: dict[str, SymbolSpec] = field(default_factory=dict)
    #: feed -> why it cannot be traded here.
    missing: dict[str, str] = field(default_factory=dict)
    #: The account suffix, once one has been seen. "" is a real answer.
    suffix: str = ""

    @property
    def symbols(self) -> dict[str, str]:
        """feed -> broker symbol, which is all the rest of the module needs."""
        return {feed: spec.symbol for feed, spec in self.found.items()}

    def __str__(self) -> str:
        have = ", ".join(f"{feed}={spec.symbol}" for feed, spec in sorted(self.found.items()))
        if not self.missing:
            return have or "nothing"
        return f"{have or 'nothing'} · unavailable: {', '.join(sorted(self.missing))}"


def candidates(feed: str, learned: str = "") -> list[str]:
    """Broker symbols to try for one feed, best first."""
    names = INSTRUMENTS.get(feed, ())
    suffixes = [learned, *[s for s in SUFFIXES if s != learned]] if learned else list(SUFFIXES)
    return [f"{name}{suffix}" for name in names for suffix in suffixes]


async def resolve(
    broker: Broker,
    feeds: Sequence[str],
    settings: Settings | None = None,
) -> Resolution:
    """Probe the broker for each feed. Never raises: a miss is a result.

    A symbol that exists but is not fully tradable - close-only, or quotes with
    no execution, which is what a broker shows for an instrument outside its
    session - is recorded as missing *with that reason*, because "the broker
    does not have it" and "the broker will not let you open one right now" lead
    to different fixes.
    """
    resolution = Resolution()
    listing = await _catalogue(broker)
    for feed in feeds:
        if feed not in INSTRUMENTS:
            resolution.missing[feed] = "not a tradable instrument in this module"
            continue

        if listing is not None:
            spec, tried = await _scan(broker, feed, listing)
            how = f"scanned {tried} of {len(listing)} symbol(s)"
        else:
            spec, tried = await _probe(broker, feed, resolution.suffix)
            how = f"tried {tried} name(s)"
        if spec is None:
            resolution.missing[feed] = f"no symbol found ({how})"
            continue
        if not spec.tradable:
            resolution.missing[feed] = f"{spec.symbol} is quoted but not open for trading"
            continue

        resolution.found[feed] = spec
        if not resolution.suffix:
            resolution.suffix = _suffix_of(feed, spec.symbol)

    if settings is not None:
        settings.resolved = resolution.symbols
    log.info("trading: %s", resolution)
    return resolution


async def _catalogue(broker: Broker) -> list[str] | None:
    """The broker's symbol list, if it has one. Never raises."""
    try:
        listing = await broker.catalogue()
    except Exception as exc:
        log.debug("trading: could not list symbols: %s", exc)
        return None
    if listing:
        log.info("trading: scanning %d broker symbols", len(listing))
    return listing or None


def matches(feed: str, listing: Sequence[str]) -> list[str]:
    """Symbols in `listing` that look like this instrument, best first.

    A match is one of the instrument's names plus **anything**, which is what
    makes an unguessed suffix findable. Ranked by how much was appended, so an
    exact `XAUUSD` beats `XAUUSD.s` beats `XAUUSD.raw.cfd` - the shortest
    addition is the plain instrument and the longer ones are variants of it.

    Case-insensitive, because a handful of brokers list in lower case and the
    comparison is about identity rather than presentation.
    """
    names = INSTRUMENTS.get(feed, ())
    found: list[tuple[int, int, str]] = []
    for symbol in listing:
        upper = symbol.upper()
        for rank, name in enumerate(names):
            if upper.startswith(name):
                found.append((len(upper) - len(name), rank, symbol))
                break
    found.sort()
    return [symbol for _, _, symbol in found]


async def _scan(broker: Broker, feed: str, listing: Sequence[str]) -> tuple[SymbolSpec | None, int]:
    """Find this instrument in the broker's own symbol list.

    Still asks for the spec of each candidate rather than trusting the name:
    a broker may carry `XAUUSD` as a CFD it will not let this account open, and
    only the spec says so.
    """
    tried = 0
    for symbol in matches(feed, listing):
        tried += 1
        try:
            spec = await broker.spec(symbol)
        except Exception as exc:
            log.debug("trading: reading %s failed: %s", symbol, exc)
            continue
        if spec is not None and spec.tradable:
            return spec, tried
        if spec is not None and tried == 1:
            # Keep the first match even if it is not tradable, so the caller
            # can report *why* rather than "no symbol found" - which would be
            # wrong, and would send somebody looking for a naming problem.
            return spec, tried
    return None, tried


async def _probe(broker: Broker, feed: str, learned: str) -> tuple[SymbolSpec | None, int]:
    tried = 0
    for name in candidates(feed, learned):
        tried += 1
        try:
            spec = await broker.spec(name)
        except Exception as exc:
            # One unreachable probe must not decide that an instrument is
            # unavailable - that would silently stop trading it for the run.
            log.debug("trading: probing %s failed: %s", name, exc)
            continue
        if spec is not None:
            return spec, tried
    return None, tried


def _suffix_of(feed: str, symbol: str) -> str:
    for name in INSTRUMENTS.get(feed, ()):
        if symbol.startswith(name):
            return symbol[len(name) :]
    return ""
