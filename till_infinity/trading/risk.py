"""The gates between a good-looking signal and an order.

These are portfolio questions, not signal questions. Whether the level is worth
trading is decided in `scalper`; whether *this account, right now* should take
another one is decided here, and the distinction matters because the answers
move independently. The best signal of the day still gets refused if it is the
fifth open position or the third loss in an hour.

Three of the gates deserve their reasoning stated, because each exists to stop
a specific way an automated scalper loses money faster than it can be watched.

**One position per instrument.** The same level fires repeatedly - that is what
a level *is* - and `structures` re-arms it after each resolution. Without this
gate a level that is quietly wrong is not one loss, it is one loss per re-arm,
all in the same direction, all for the same reason.

**A daily loss stop that halts rather than shrinks.** Reducing size after
losses sounds prudent and keeps trading a system that is currently wrong. The
day's opening equity is the reference rather than a rolling window, so the
limit is a fact about today and cannot be walked forward by a recovery.

**Spread as a fraction of the target, not an absolute.** A two-pip spread is
nothing on a target of forty and fatal on a target of five, and a scalper's
targets are small by construction. Everything else in this project is measured
against what it is trying to earn; so is this.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..logging import get_logger
from . import exposure as ex
from .config import Settings
from .context import Context
from .models import Intent, Position, Refusal, Tick

log = get_logger(__name__)


def _day(when: float) -> str:
    return datetime.fromtimestamp(when, UTC).strftime("%Y-%m-%d")


@dataclass(slots=True)
class Guard:
    """The day's state, and the decision to take another trade or not."""

    settings: Settings
    #: What the rest of the system knows. Optional, so a Guard can be tested
    #: and used without one - every check it drives fails open.
    context: Context | None = None
    #: Equity as the day opened. The daily stop measures against this.
    opening_equity: float = 0.0
    day: str = ""
    realised: float = 0.0
    trades: int = 0
    wins: int = 0
    #: feed -> when it last lost. Read by the cooldown gate.
    last_loss: dict[str, float] = field(default_factory=dict)
    #: gate -> how many times it refused. See `Refusal` on why this is counted.
    refusals: dict[str, int] = field(default_factory=dict)
    halted: str = ""

    def roll(self, equity: float, now: float | None = None) -> bool:
        """Start a new day if the clock has. True when it did.

        A halt lasts the day and no longer. The alternative - carrying it until
        someone restarts the process - makes the size of the loss decide how
        long trading stops, which is not a rule anybody chose.
        """
        today = _day(now if now is not None else time.time())
        if today == self.day:
            return False
        if self.day and self.halted:
            log.info("trading: new day, the halt from %s is lifted", self.day)
        self.day, self.opening_equity = today, equity
        self.realised, self.trades, self.wins, self.halted = 0.0, 0, 0, ""
        return True

    @property
    def daily_loss_limit(self) -> float:
        return self.opening_equity * self.settings.daily_loss_fraction

    def allows(
        self,
        intent: Intent,
        *,
        positions: list[Position],
        tick: Tick | None = None,
        now: float | None = None,
        risk_of: dict[int, float] | None = None,
        feed_of: dict[str, str] | None = None,
    ) -> Refusal | None:
        """None if this trade may go ahead, else the gate that stopped it.

        Ordered cheapest-first and most-decisive-first, which happen to agree:
        a halted day and a blackout are facts that need no arithmetic, and
        checking them before sizing anything keeps the log honest about what
        actually stopped a trade. A refusal names one gate, so the order
        decides which one gets named when several apply.
        """
        when = now if now is not None else time.time()

        if self.halted:
            return self._no("halted", intent.feed, self.halted)

        if self.context is not None:
            release = self.context.blackout(intent.feed, when)
            if release is not None:
                minutes = (release.when - when) / 60.0
                due = f"in {minutes:.0f}m" if minutes >= 0 else f"{-minutes:.0f}m ago"
                return self._no(
                    "news",
                    intent.feed,
                    f"{release.currency} {release.title or 'high-impact release'} {due}",
                )

            paused = self.context.drifting(intent.feed, when)
            if paused > 0:
                return self._no(
                    "drift",
                    intent.feed,
                    f"the regime changed; {paused:.0f}s of stand-aside left",
                )

            wide = self.context.widened(intent.feed, when)
            if wide:
                return self._no(
                    "wide",
                    intent.feed,
                    f"{wide} venues are quoting it wide at once; there is no "
                    f"good fill to be had from anyone",
                )

            if tick is not None:
                off = self.context.dislocation(intent.feed, tick, when)
                if off:
                    return self._no("dislocated", intent.feed, off)

        if len(positions) >= self.settings.max_positions:
            return self._no(
                "max_positions",
                intent.feed,
                f"{len(positions)} open, limit is {self.settings.max_positions}",
            )

        same = [p for p in positions if p.symbol == intent.symbol]
        if len(same) >= self.settings.max_per_symbol:
            return self._no(
                "already_open",
                intent.feed,
                f"{len(same)} already open on {intent.symbol}",
            )

        lost = self.last_loss.get(intent.feed)
        if lost and when - lost < self.settings.loss_cooldown:
            left = self.settings.loss_cooldown - (when - lost)
            return self._no("cooldown", intent.feed, f"{left:.0f}s left after a loss")

        if intent.reward_to_risk < self.settings.min_reward_to_risk:
            return self._no(
                "reward_to_risk",
                intent.feed,
                f"{intent.reward_to_risk:.2f} against a "
                f"{self.settings.min_reward_to_risk:.2f} floor",
            )

        if tick is not None and intent.reward > 0:
            share = tick.spread / intent.reward
            if share > self.settings.max_spread_fraction:
                return self._no(
                    "spread",
                    intent.feed,
                    f"spread is {share:.0%} of the target, limit is "
                    f"{self.settings.max_spread_fraction:.0%}",
                )

        if intent.volume <= 0:
            return self._no("size", intent.feed, "sized to nothing")

        crowded = self._exposure(intent, positions, risk_of or {}, feed_of or {})
        if crowded is not None:
            return crowded

        return None

    def _exposure(
        self,
        intent: Intent,
        positions: list[Position],
        risk_of: dict[int, float],
        feed_of: dict[str, str],
    ) -> Refusal | None:
        """Refuse a trade that would pile too much onto one currency.

        Checked last because it is the only gate that needs the trade to have
        been sized - the limit is in money at risk, and until the volume is
        known there is no number to add to the book.
        """
        limit = self.settings.max_currency_exposure * self.opening_equity
        if limit <= 0:
            return None

        after = ex.would_be(ex.measure(positions, risk_of, feed_of), intent)
        currency, amount = after.worst()
        if abs(amount) <= limit:
            return None
        return self._no(
            "exposure",
            intent.feed,
            f"would put {abs(amount):.2f} on {currency} "
            f"({'long' if amount > 0 else 'short'}), limit is {limit:.2f}",
        )

    def record(self, feed: str, profit: float, equity: float, now: float | None = None) -> None:
        """Fold a closed trade in, and halt for the day if it took us past the limit."""
        when = now if now is not None else time.time()
        self.roll(equity, when)
        self.realised += profit
        self.trades += 1
        if profit > 0:
            self.wins += 1
        else:
            self.last_loss[feed] = when

        limit = self.daily_loss_limit
        if limit > 0 and self.realised <= -limit and not self.halted:
            self.halted = (
                f"down {abs(self.realised):.2f} today, past the "
                f"{self.settings.daily_loss_fraction:.1%} limit of {limit:.2f}"
            )
            log.warning("trading: halted for %s - %s", self.day, self.halted)

    def _no(self, gate: str, feed: str, detail: str) -> Refusal:
        self.refusals[gate] = self.refusals.get(gate, 0) + 1
        return Refusal(gate=gate, detail=detail, feed=feed)

    def summary(self) -> str:
        rate = f"{self.wins}/{self.trades}" if self.trades else "0/0"
        state = f" · HALTED ({self.halted})" if self.halted else ""
        return f"{self.day or '-'}: {rate} won, {self.realised:+.2f} realised{state}"
