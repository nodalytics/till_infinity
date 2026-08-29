"""The contract a strategy implements, and the register of the ones we have.

A strategy answers one question: *given this signal, this instrument's trading
rules and this quote, is there a trade here?* It does not place orders, size
against the account's history, or know whether the day has already hit its loss
limit - those belong to `risk` and `service`, and keeping them out is what lets
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
of them adds an indicator, and that is deliberate - the edge has been measured
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
from .floors import Floors
from .models import SymbolSpec, Tick, Verdict

log = get_logger(__name__)


class Strategy(ABC):
    """One way of turning signals into intents."""

    name: ClassVar[str]
    description: ClassVar[str] = ""
    #: The shape of signal this strategy reads. Everything else is skipped
    #: before any of its logic runs.
    shape: ClassVar[str] = "level"

    #: The strategy this one is a *stricter* version of, if it is one.
    #:
    #: `TRADING_STRATEGIES` is a priority list, not a set - the first taker
    #: wins - so a strategy that is another plus extra refusals can only ever
    #: see what the permissive one declined, and it declined those for reasons
    #: this one would decline too. Listed after what it refines, it never
    #: trades, and nothing about that looks wrong: it loads, it is enabled, and
    #: it books nothing forever.
    #:
    #: Declaring the relationship is what lets start-up say so. It cannot be
    #: inferred - "is a subset of" is not something one gate chain can work out
    #: about another - so the strategy that knows states it.
    refines: ClassVar[str] = ""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.seen = 0
        self.wanted = 0
        #: The bar each direction has to clear, kept per direction because the
        #: two do not have the same distribution. See `floors.py`.
        self.floors = Floors(percentile=settings.probability_percentile)

    #: Seconds a trade from this strategy may stay open. Zero takes the
    #: configured `max_hold`. A strategy whose thesis needs time to play out
    #: says so here rather than being cut off by a default chosen for a
    #: different kind of trade.
    hold_seconds: ClassVar[float] = 0.0

    #: Whether this is a scalp or a swing, so the two can be run together, one
    #: at a time, or not at all - see `TRADING_STYLE`.
    #:
    #: Declared per strategy rather than derived, because the names lie. Both
    #: `approach-scalp` and `fade-to-value` hold for forty-five minutes, longer
    #: than `max_hold`, and are swings wearing a scalp's name. What decides is
    #: how long the thesis needs and whether the trade is trying to catch a
    #: reaction or ride a move: a swing either holds an hour or more, or lets
    #: its target run past the modelled push.
    style: ClassVar[str] = "scalp"

    #: The same limit expressed in **bars of the entry interval**, which is the
    #: clock everything else about the trade is measured on.
    #:
    #: A fixed number of seconds cannot mean one thing across eight timeframes.
    #: Thirty minutes is thirty bars to a strategy triggering on 1m and two to
    #: one triggering on 15m, so the same setting asks a one-minute signal to
    #: survive a thirty-minute walk and a fifteen-minute signal to survive
    #: almost none of one. Zero keeps the seconds-only behaviour.
    #:
    #: `hold_seconds` remains as the ceiling: bars are the right unit and wall
    #: clock is the right cap, because a 4h strategy holding twenty bars is
    #: three days and that is not a scalp whatever the arithmetic says.
    hold_bars: ClassVar[float] = 0.0

    #: How quickly this strategy protects a trade, overriding the deployment's
    #: own settings. Zero on either means "use the configured value".
    #:
    #: These were global, and a global number cannot fit both a strategy that
    #: holds thirty minutes and one that holds two. A fast trade spends most of
    #: its life waiting for a 1R threshold it may never announce, and a trail
    #: wide enough for a half-hour thesis is most of the move for a
    #: twenty-second one - so the fast strategy is unprotected for exactly the
    #: window it exists to trade.
    break_even_at: ClassVar[float] = 0.0
    trail_vol: ClassVar[float] = 0.0

    #: Zero means take the deployment's `max_against_vol`, so the filter is a
    #: property of the book rather than of whichever strategies remembered to
    #: ask for it.
    #:
    #: How much accumulated momentum *against* this trade it will tolerate,
    #: in volatility units. Zero is off, which is every strategy that has not
    #: asked for it.
    #:
    #: A level call is a claim that price has arrived somewhere it will turn.
    #: It says nothing about whether the move that brought price here has
    #: finished, and taking the other side of a run that is still running is
    #: how a correct level becomes a stopped trade - the thing 23 of the first
    #: 32 trades did. `structures.cusum` measures that run without a window,
    #: and this is the number that decides how much of it is too much.
    max_against_vol: ClassVar[float] = 0.0

    #: This strategy's own `require_turn_vol`. Zero means use the configured
    #: value, so a strategy that wants the turn regardless of how the
    #: deployment is tuned says so here.
    min_with_vol: ClassVar[float] = 0.0

    #: How far this strategy insists price come back before it will fill,
    #: overriding the deployment's own `pullback_fraction`. Zero means use the
    #: configured value; a strategy that always wants a resting entry says so
    #: here rather than depending on how the deployment happens to be tuned.
    pullback_fraction: ClassVar[float] = 0.0

    def horizon(self, interval: str) -> float:
        """How far this strategy's hold stretches one bar of `interval`.

        The same square root of time the stop floor uses, and for the same
        reason: `vol_bps` and every threshold denominated in it describe **one
        bar**, while the trade is held for many. A number that is right for one
        bar is wrong for thirty by a factor of about 5.5.

        Three settings inherited that mistake and are corrected by this.

        * **the trail**, in volatility units of one bar - a session's pullback
          against a minute's.
        * **the momentum filter**, likewise: 1.5v is a real run on a 3m chart
          and ordinary noise on a 4h one.

        Each was previously a constant per strategy, which meant every new
        strategy had to rediscover the arithmetic and `high-timeframe` carried
        hand-picked doubles of the scalpers' numbers. This derives them.

        **Break-even is deliberately not one of them**, and that was a mistake
        caught by reading the numbers before shipping them. Break-even is in R,
        and R is already measured against the stop, which this same reasoning
        has already widened. Scaling it again counts the horizon twice and puts
        `level-scalp` on a 5.5R break-even, which is a threshold that never
        fires - protection removed by an excess of it.

        Capped at `max_stop_scale`, like the stop floor, because the square
        root of thirty bars is 5.5 and a trail five and a half times its
        stated width is not the same rule any more.

        Returns 1.0 when the hold is not knowable, which restores the constants
        rather than guessing at a scale for them.
        """
        import math

        from ..structures.levels import SECONDS

        bars = SECONDS.get(interval, 0.0)
        if bars <= 0:
            return 1.0
        held = self.hold_for(interval, self.settings.max_hold)
        if held <= 0:
            return 1.0
        grown = math.sqrt(max(held / bars, 1.0))
        return max(1.0, min(grown, max(self.settings.max_stop_scale, 1.0)))

    #: The most of the expected push a trail may sit behind the best price.
    #:
    #: A trail wider than the move it protects can never be better than the
    #: stop already in place, so `manage.advance` never applies it and the
    #: protection is silently absent. Half means that once price reaches the
    #: modelled push, the trail has locked in half of it.
    TRAIL_SHARE: ClassVar[float] = 0.5

    def protection(self, interval: str, push_vol: float = 0.0) -> tuple[float, float]:
        """Break-even and trail for this strategy on this interval.

        A strategy's own values win where it states them, and the trail is then
        stretched by `horizon` so the same declared intent means the same thing
        on a two-minute hold and a two-day one.

        **And then capped against the push, which the first version was not.**
        Scaling 2v by the horizon gives 6v, while the measured push
        distribution has a median of 2.24v and a p90 of 4.93v - so the trail
        sat further from price than the entire move on nine trades in ten,
        could never beat the stop already in place, and was never applied.
        Generalising the horizon idea removed the protection it was meant to
        improve, and silently, which is the worst way for a rule to fail.

        There is a floor downstream: `manage.advance` widens the trail to clear
        the level's own wick spread, so a tight cap here cannot produce a trail
        inside the noise. Between them the trail is bracketed rather than
        merely scaled.

        Break-even is deliberately unscaled - it is in R, and R is measured
        against a stop this same reasoning has already widened, so scaling it
        again counts the horizon twice.
        """
        even = self.break_even_at or self.settings.break_even_at
        trail = (self.trail_vol or self.settings.trail_vol) * self.horizon(interval)
        if push_vol > 0 and trail > 0:
            trail = min(trail, abs(push_vol) * self.TRAIL_SHARE)
        return even, trail

    def against_limit(self, interval: str) -> float:
        """How much momentum against the trade this strategy tolerates here."""
        base = self.max_against_vol or self.settings.max_against_vol
        return base * self.horizon(interval) if base > 0 else 0.0

    def hold_for(self, interval: str, ceiling: float) -> float:
        """Seconds this strategy may hold a trade triggered on `interval`."""
        from ..structures.levels import SECONDS

        seconds = SECONDS.get(interval, 0.0)
        want = self.hold_seconds or ceiling
        if self.hold_bars <= 0 or seconds <= 0:
            return want
        return min(self.hold_bars * seconds, want)

    def hold_bars_for(self, interval: str, ceiling: float) -> float:
        """How many bars of `interval` the hold above actually covers.

        The number the stop has to survive, which is why it is derived from the
        capped hold rather than from `hold_bars` directly - a hold cut short by
        the ceiling is fewer bars of noise, and pretending otherwise would size
        the stop for time the trade will not be given.
        """
        from ..structures.levels import SECONDS

        seconds = SECONDS.get(interval, 0.0)
        if seconds <= 0:
            return 1.0
        return max(self.hold_for(interval, ceiling) / seconds, 1.0)

    #: Where a trade may be **triggered**. The lower timeframes: the entry is
    #: what decides the stop, and a tighter stop on faster data is the whole
    #: reason to drop down to it.
    #:
    #: Empty means "whatever the operator allows". A strategy whose thesis only
    #: holds on fast data says so here rather than relying on the deployment to
    #: be configured for it - the module accepts every timeframe a level forms
    #: on, because restricting the service restricts every strategy at once.
    entries: ClassVar[tuple[str, ...]] = ()

    #: Where the **bias** comes from. The higher timeframes, which do not
    #: trigger anything: they say whether a trigger is worth taking.
    #:
    #: The pair is the point. A scalper anchored on 1h and entering on 3m is
    #: taking a fast trade in a slow structure's direction; the same scalper
    #: with no anchor is taking a fast trade in no direction at all. And a
    #: swing anchored on 1d does not have to enter on 1d - dropping to 1h, or
    #: lower, buys a tighter stop for the same idea, which is risk reduction
    #: rather than a different trade.
    #:
    #: Context reaches a strategy through the signal's `confluence`, which is
    #: the timeframes `structures` found agreeing on that price.
    context: ClassVar[tuple[str, ...]] = ()

    #: Whether an entry is refused when no context timeframe agrees.
    needs_context: ClassVar[bool] = False

    #: The timeframe whose last closed bar must show the rejection, when the
    #: candle witness is asked for. Empty means the entry interval, which is
    #: what a scalp wants: it is entering on that bar's evidence.
    #:
    #: A swing wants the opposite. It enters on 1h but the rejection that
    #: matters is the 4h one - a pin bar there is a claim several hours of
    #: auction failed at this price, where the same shape on 1h is one hour's
    #: worth. Naming the timeframe separately is what lets the entry be fast
    #: and the evidence slow.
    candle_interval: ClassVar[str] = ""

    #: Whether every witness asked for must confirm, rather than any one of
    #: them.
    #:
    #: The disjunction is right for a scalp: it cannot wait four hours for a 4h
    #: bar to close, so requiring both would refuse a clean fast turn for not
    #: yet having a candle to show for itself. A swing has the time, and the
    #: two witnesses answer different questions - the candle says the auction
    #: failed here, the momentum ensemble says it is failing now.
    needs_both_witnesses: ClassVar[bool] = False

    #: How much of the sub-hour momentum ensemble must point the way the trade
    #: does, from 0 (ask nothing) to 1 (every timeframe).
    #:
    #: Agreement is the reading a single filter cannot give: momentum on 1m and
    #: nowhere else is noise, the same move on 1m, 5m and 15m at once is the
    #: market doing one thing at several resolutions.
    #:
    #: **Silent when the ensemble is cold.** A gate that refuses because the
    #: reading is missing is a gate that stops all trading on a fresh
    #: container, which this repository has done once already.
    min_momentum_agree: ClassVar[float] = 0.0

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
        about would be learning from a sample it had already filtered - the
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
        overrides it - making every strategy async would be a lie about what
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
    from . import council as _council  # noqa: F401 - registers `council`
    from . import scalper as _  # noqa: F401 - registers the built-ins

    chosen = tuple(names) if names else settings.strategies
    unknown = [n for n in chosen if n not in STRATEGIES]
    if unknown:
        raise ValueError(
            f"unknown strategy: {', '.join(unknown)} (have: {', '.join(sorted(STRATEGIES))})"
        )
    return [STRATEGIES[name](settings) for name in chosen]


#: What `TRADING_STYLE` accepts. "both" is the default and preserves the
#: behaviour that existed before the switch did.
STYLES = ("scalp", "swing", "both", "none")


def by_style(engines: list[Strategy], style: str) -> tuple[list[Strategy], list[Strategy]]:
    """Split a strategy list into the ones this style runs and the rest.

    Returns `(kept, dropped)` so the caller can say what it turned off. An
    unrecognised style keeps everything: a typo in an environment variable
    should not silently stop the service trading, which is the failure a
    mis-set base-rate floor already caused once.
    """
    wanted = (style or "both").strip().lower()
    if wanted not in STYLES:
        log.warning(
            "trading: TRADING_STYLE=%r is not one of %s - running everything",
            style,
            ", ".join(STYLES),
        )
        return list(engines), []
    if wanted == "both":
        return list(engines), []
    if wanted == "none":
        return [], list(engines)
    kept = [e for e in engines if e.style == wanted]
    dropped = [e for e in engines if e.style != wanted]
    return kept, dropped


def catalogue() -> dict[str, str]:
    """name -> what it does, for `trading strategies`."""
    from . import council as _council  # noqa: F401
    from . import scalper as _  # noqa: F401

    return {name: cls.description for name, cls in sorted(STRATEGIES.items())}
