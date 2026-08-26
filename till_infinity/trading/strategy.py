"""The contract a strategy implements, and the register of the ones we have.

A strategy answers one question: *given this signal, this instrument's trading
rules and this quote, is there a trade here?* It does not place orders, size
against the account's history, or know whether the day has already hit its loss
limit — those belong to `risk` and `service`, and keeping them out is what lets
two strategies run side by side without either one deciding the other's limits.

The split is worth stating plainly because it is easy to blur:

| | decides |
|---|---|
| `strategy` | is this signal worth trading, and where do the stop and target go |
| `plans` | how much may be lost, per trade and per day |
| `risk` | may *this account, right now* take another one |
| `service` | send it, record it, and reconcile what came back |

**A strategy claims no edge of its own.** Every one registered here reads the
same measured signal `structures` publishes; they differ in which of those
calls they will act on and how they place the stop and target around it. None
of them adds an indicator, and that is deliberate — the edge has been measured
upstream, and a rule invented here would be an unmeasured one riding on a
measured one's reputation. Adding a strategy is a claim that a *subset* of
those calls behaves differently, which is a claim the journal can settle.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, ClassVar

from ..logging import get_logger
from .config import Settings
from .models import SymbolSpec, Tick, Verdict

log = get_logger(__name__)


class Strategy(ABC):
    """One way of turning signals into intents."""

    name: ClassVar[str]
    description: ClassVar[str] = ""
    #: The shape of signal this strategy reads. Everything else is skipped
    #: before any of its logic runs.
    shape: ClassVar[str] = "level"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.seen = 0
        self.wanted = 0

    #: Seconds a trade from this strategy may stay open. Zero takes the
    #: configured `max_hold`. A strategy whose thesis needs time to play out
    #: says so here rather than being cut off by a default chosen for a
    #: different kind of trade.
    hold_seconds: ClassVar[float] = 0.0

    #: Where a trade may be **triggered**. The lower timeframes: the entry is
    #: what decides the stop, and a tighter stop on faster data is the whole
    #: reason to drop down to it.
    #:
    #: Empty means "whatever the operator allows". A strategy whose thesis only
    #: holds on fast data says so here rather than relying on the deployment to
    #: be configured for it — the module accepts every timeframe a level forms
    #: on, because restricting the service restricts every strategy at once.
    entries: ClassVar[tuple[str, ...]] = ()

    #: Where the **bias** comes from. The higher timeframes, which do not
    #: trigger anything: they say whether a trigger is worth taking.
    #:
    #: The pair is the point. A scalper anchored on 1h and entering on 3m is
    #: taking a fast trade in a slow structure's direction; the same scalper
    #: with no anchor is taking a fast trade in no direction at all. And a
    #: swing anchored on 1d does not have to enter on 1d — dropping to 1h, or
    #: lower, buys a tighter stop for the same idea, which is risk reduction
    #: rather than a different trade.
    #:
    #: Context reaches a strategy through the signal's `confluence`, which is
    #: the timeframes `structures` found agreeing on that price.
    context: ClassVar[tuple[str, ...]] = ()

    #: Whether an entry is refused when no context timeframe agrees.
    needs_context: ClassVar[bool] = False

    @property
    def intervals(self) -> tuple[str, ...]:
        """Timeframes this strategy will trigger on.

        The intersection of what it claims and what the operator allows, so
        configuration can narrow a strategy and never widen one past the data
        its reasoning was built for.
        """
        allowed = self.settings.intervals
        if not self.entries:
            return allowed
        return tuple(t for t in self.entries if t in allowed)

    @property
    def anchors(self) -> tuple[str, ...]:
        """Timeframes whose agreement counts as context for this strategy."""
        if not self.context:
            return ()
        return tuple(t for t in self.context if t in self.settings.intervals)

    def anchored(self, payload: dict[str, Any]) -> tuple[str, ...]:
        """Which of this strategy's context timeframes agree with this call.

        Read from the signal rather than fetched: `structures` has already
        grouped a price into a zone across timeframes, and asking again here
        would be a second, differently-wrong answer to a question already
        settled upstream.
        """
        raw = payload.get("confluence")
        if not isinstance(raw, list):
            return ()
        wanted = set(self.anchors)
        interval = str(payload.get("interval") or "")
        return tuple(str(t) for t in raw if str(t) in wanted and str(t) != interval)

    def wants(self, payload: dict[str, Any]) -> bool:
        """A cheap pre-filter, so a firehose of signals costs almost nothing."""
        return str(payload.get("shape") or "") == self.shape

    def observe(self, payload: dict[str, Any]) -> None:
        """Learn from a signal whatever the verdict on it turns out to be.

        Called for every matching signal before any of them is considered, and
        called on every strategy rather than only the one that ends up acting.
        A strategy that accumulated state only from the signals it was asked
        about would be learning from a sample it had already filtered — the
        rolling-quantile gate would measure the distribution of what it already
        accepts, and the level book would only know about levels that produced
        a trade.
        """

    async def consider_async(
        self,
        payload: dict[str, Any],
        *,
        spec: SymbolSpec,
        tick: Tick,
        equity: float,
    ) -> Verdict:
        """The async door, for a strategy that genuinely blocks on the network.

        Defaults to the synchronous one, so the four arithmetic strategies are
        unchanged and `service` has a single call site. Only `council`
        overrides it — making every strategy async would be a lie about what
        the others cost.
        """
        return self.consider(payload, spec=spec, tick=tick, equity=equity)

    @abstractmethod
    def consider(
        self,
        payload: dict[str, Any],
        *,
        spec: SymbolSpec,
        tick: Tick,
        equity: float,
    ) -> Verdict:
        """A trade, or the reason there is not one. Never raises for a bad signal."""

    def __str__(self) -> str:
        return f"{self.name} ({self.wanted}/{self.seen} taken)"


#: Every strategy that can be named in `TRADING_STRATEGIES`. Populated at the
#: bottom of `scalper`, which is imported for its side effect by `__init__`.
STRATEGIES: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    """Add a strategy to the register. Used as a decorator."""
    STRATEGIES[cls.name] = cls
    return cls


def build(names: Sequence[str] | None, settings: Settings) -> list[Strategy]:
    """Instantiate the named strategies, or the configured default.

    An unknown name raises rather than being skipped, for the same reason an
    unknown instrument does: a typo that silently runs one strategy instead of
    two is only noticed by the trades that never happened.
    """
    from . import council as _council  # noqa: F401 — registers `council`
    from . import scalper as _  # noqa: F401 — registers the built-ins

    chosen = tuple(names) if names else settings.strategies
    unknown = [n for n in chosen if n not in STRATEGIES]
    if unknown:
        raise ValueError(
            f"unknown strategy: {', '.join(unknown)} (have: {', '.join(sorted(STRATEGIES))})"
        )
    return [STRATEGIES[name](settings) for name in chosen]


def catalogue() -> dict[str, str]:
    """name -> what it does, for `trading strategies`."""
    from . import council as _council  # noqa: F401
    from . import scalper as _  # noqa: F401

    return {name: cls.description for name, cls in sorted(STRATEGIES.items())}
