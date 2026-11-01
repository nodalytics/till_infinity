"""The whole book, as one opinion. An Actor, because no strategy owns it.

**The account does not hold seventeen opinions, it holds one balance**, and
nothing in the per-trade machinery reads that. Each strategy's gates decide
whether to *open*, each position's stop decides its own leg, and a daily-loss
rule halts opening on realised loss - none of them can act on the floating
total across positions, which with several strategies running is the same
direction on the same instrument many times over.

## Why this is the one exit that is not a strategy's

Every other exit in `exits.py` is a component the opening strategy owns,
because an exit rule that could close another strategy's position is the magic
number bug wearing a new hat. This one is the exception that proves it: its
whole subject is *other strategies' positions*, so it cannot be any one
strategy's and must be an Actor with the book in view.

The split is the one the rest of the desk already follows: `guard.basket` holds
the policy and this holds the action.

## Order matters when a close can fail part way through

The reason is logged **before** anything is closed, because a close that fails
half way leaves a book that no longer matches the reason it was judged on - and
the log is then the only record of what the whole book looked like.

And one leg refusing must not strand the rest: an index in its daily break
cannot be closed while the others still can, and leaving them open because of
it is the opposite of what was asked for. So each close is attempted
independently and a failure is counted rather than raised.
"""

from __future__ import annotations

from collections.abc import Callable

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig
from nautilus_trader.model.enums import PriceType

from ..utils import topics
from .config import Settings
from .guard import Guard


class BasketConfig(ActorConfig, frozen=True):
    """How often to look at the book, and which venue's account to read."""

    venue: str
    #: Seconds between looks. The book's floating total moves with every
    #: quote, so this is a sampling choice: often enough to act, rarely
    #: enough that it is not re-deciding on noise.
    every_seconds: int = 10


class BasketExit(Actor):
    """Close every open position when the book as a whole says so."""

    def __init__(self, config: BasketConfig) -> None:
        super().__init__(config)
        self._cfg = config
        self.settings = Settings.from_env()
        self.guard = Guard(settings=self.settings)
        self.closed = 0
        self.failed = 0
        self.looks = 0
        #: Positions skipped on the last look for never having quoted. State
        #: and not only a log line, because a log line cannot be asserted on -
        #: `Logger.warning` is read-only, the same constraint as `cache`.
        self.unpriced = 0

    def on_start(self) -> None:
        self.clock.set_timer(
            name="basket",
            interval=self._interval(),
            callback=self._look,
        )
        self.log.info(f"watching the book every {self._cfg.every_seconds}s")

    def _interval(self):
        from datetime import timedelta

        return timedelta(seconds=self._cfg.every_seconds)

    def _look(self, event: object = None) -> None:  # noqa: ARG002
        """One look at the whole book, from the cache.

        `event` is the timer's, and unused: this reads the book rather than the
        tick that woke it. Kept in the signature because that is what Nautilus
        calls the callback with.
        """
        self.judge(self.cache.positions_open(), self._last_price)

    def _last_price(self, instrument_id: object) -> object | None:
        """The last quoted mid for an instrument, or None if it has not quoted."""
        quote = self.cache.quote_tick(instrument_id)
        return None if quote is None else quote.extract_price(PriceType.MID)

    def judge(self, positions: list, price_of: Callable[[object], object | None]) -> None:
        """Decide on a book and act. **Takes the positions, does not read them.**

        `Actor.cache` is read-only - the same constraint that made the news
        adapter's `read_rows` a module function and had `_sweep` take the time
        rather than read `self._clock`. So the decision is a method over a list
        and a pricer, which makes it testable without a kernel, and `_look` is
        the two lines that fetch.

        **`price_of` is required and is not `avg_px_open`.** The first version
        of this priced every position at its own opening price, which makes
        `unrealized_pnl` zero by definition and the basket stop unreachable - a
        rule that is configured, correct and inert, which is the exact shape
        `research/inert.md` catalogues. A position that has not quoted yet is
        skipped rather than counted at zero, because zero is a number and
        "unknown" is not.
        """
        self.looks += 1
        if not positions:
            return
        net = 0.0
        self.unpriced = 0
        for position in positions:
            price = price_of(position.instrument_id)
            if price is None:
                self.unpriced += 1
                continue
            net += float(position.unrealized_pnl(price) or 0.0)
        if self.unpriced:
            # Said out loud: a book judged on part of itself is a book judged
            # on the wrong number, and the share that is missing is the thing
            # a reader needs to know.
            self.log.warning(
                f"{self.unpriced} of {len(positions)} position(s) have not quoted - "
                f"judging the book on the rest"
            )
        why = self.guard.basket(net, self._equity(), None, 0.0)
        if not why:
            return
        # Named before anything is closed. See the module docstring.
        self.log.warning(f"closing all {len(positions)} position(s) - {why}")
        for position in positions:
            try:
                self._close(position)
            except Exception as exc:
                self.failed += 1
                self.log.warning(f"could not close {position.id} for the basket: {exc}")
                continue
            self.closed += 1

    def _close(self, position: object) -> None:
        """Ask the position's own strategy to close it.

        **Published rather than submitted.** An Actor has no order factory and
        should not have one: it would be submitting under its own identity, and
        the position's `strategy_id` would then no longer name what opened and
        closed it - which is the whole property this carve-up was for. So the
        request goes on the message bus and the owning strategy acts on it.

        Through `utils.topics.publish`, which is `msgbus.publish` - the first
        version of this called `self.publish_data_dict`, **which is not a
        Nautilus method**. It would have raised the first time a node ran, and
        the test passed because it stubbed the name rather than checking one
        existed.
        """
        topics.publish(
            self,
            topics.ALERTS,
            {
                "shape": "basket.close",
                "position_id": str(position.id),
                "strategy_id": str(position.strategy_id),
                "instrument_id": str(position.instrument_id),
            },
        )

    def _equity(self) -> float:
        """The one balance the book has, or 0.0 when there is no account yet."""
        from nautilus_trader.model.identifiers import Venue

        account = self.portfolio.account(Venue(self._cfg.venue))
        if account is None:
            return 0.0
        balance = account.balance_total()
        return float(balance.as_double()) if balance is not None else 0.0
