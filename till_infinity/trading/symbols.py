"""Which of the instruments we watch can actually be traded here.

The price side names an instrument once — `gold`, `btc` — and six venues quote
it. A broker names it whatever it likes: `XAUUSD`, `GOLD`, `XAUUSD.raw`,
`BTCUSD` or nothing at all, because plenty of retail MT5 accounts that carry
gold and bitcoin carry neither Solana nor the Nasdaq under any name.

So availability is *discovered*, once, at start-up, and the result is a plain
mapping from feed name to broker symbol that everything downstream uses. Doing
it at start-up rather than at the moment of firing is the whole point: an
instrument that cannot be traded should be reported while nobody is waiting on
it, not turned into a rejected order three days later when a level finally
fires.

**The suffix is learned rather than enumerated.** Account types add a suffix to
every symbol — `.raw`, `.r`, `m`, `.pro` — and it is the same suffix across the
account. Probing ten of them against five candidate names for fourteen feeds is
seven hundred round trips over the bridge; noticing that `XAUUSD.raw` worked
and trying `.raw` first for everything after it is a handful. The full list is
still there as a fallback, so a broker that is inconsistent is found anyway,
just more slowly.
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

    A symbol that exists but is not fully tradable — close-only, or quotes with
    no execution, which is what a broker shows for an instrument outside its
    session — is recorded as missing *with that reason*, because "the broker
    does not have it" and "the broker will not let you open one right now" lead
    to different fixes.
    """
    resolution = Resolution()
    for feed in feeds:
        if feed not in INSTRUMENTS:
            resolution.missing[feed] = "not a tradable instrument in this module"
            continue

        spec, tried = await _probe(broker, feed, resolution.suffix)
        if spec is None:
            resolution.missing[feed] = f"no symbol found (tried {tried} name(s))"
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


async def _probe(broker: Broker, feed: str, learned: str) -> tuple[SymbolSpec | None, int]:
    tried = 0
    for name in candidates(feed, learned):
        tried += 1
        try:
            spec = await broker.spec(name)
        except Exception as exc:
            # One unreachable probe must not decide that an instrument is
            # unavailable — that would silently stop trading it for the run.
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
