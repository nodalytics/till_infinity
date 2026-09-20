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
from .models import Intent, Position, Refusal, Tick, money

log = get_logger(__name__)


def _day(when: float) -> str:
    return datetime.fromtimestamp(when, UTC).strftime("%Y-%m-%d")


@dataclass(frozen=True, slots=True)
class Limits:
    """One strategy's own gate values. Zero on a field means the deployment's.

    **Only the gates that are about a single trade.** `max_positions`,
    `max_per_symbol`, `daily_loss_fraction` and `max_currency_exposure` are
    deliberately absent, because they are properties of the *account*: give
    seventeen strategies a daily loss budget each and the account can lose
    seventeen times the limit it was configured with. Those stay global, and
    there is no field here through which one could be overridden.

    The two spread gates are absent for a different reason - they need no
    tailoring. `max_spread_fraction` is `spread / reward` and
    `max_spread_risk_fraction` is `spread / risk`, so both are already
    normalised by the strategy's own geometry: a distant target already buys the
    right to pay more, without anybody setting a number per strategy.
    """

    by: str = ""
    #: Seconds to wait after a loss on a feed. Zero means `loss_cooldown`.
    loss_cooldown: float = 0.0
    #: Reward-to-risk floor. Zero means `min_reward_to_risk`.
    min_reward_to_risk: float = 0.0

    def cooldown(self, settings: Settings) -> float:
        return self.loss_cooldown or settings.loss_cooldown

    def reward_floor(self, settings: Settings) -> float:
        return self.min_reward_to_risk or settings.min_reward_to_risk


#: Every field a strategy may govern for itself, as a set, so a test can assert
#: that no account-level limit has quietly joined them.
PER_STRATEGY: frozenset[str] = frozenset({"loss_cooldown", "min_reward_to_risk"})

#: What stays the account's, whatever a strategy says.
ACCOUNT_LEVEL: frozenset[str] = frozenset(
    {"max_positions", "max_per_symbol", "daily_loss_fraction", "max_currency_exposure"}
)


@dataclass(slots=True)
class Guard:
    """The day's state, and the decision to take another trade or not."""

    settings: Settings
    #: What the rest of the system knows. Optional, so a Guard can be tested
    #: and used without one - every check it drives fails open.
    context: Context | None = None
    #: The account's currency, for the running total. Empty prints a bare
    #: number, which is what an account that never reported one deserves.
    currency: str = ""
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
    #: The best net floating profit the open book has shown today, in money.
    #:
    #: Kept here rather than in the service because it is day state and has to
    #: survive a deploy: a peak that resets on restart makes the give-back rule
    #: measure from wherever the desk happened to reboot.
    basket_peak: float = 0.0

    def state(self) -> dict[str, object]:
        """The day's running total, for keeping across a restart.

        Only what the *day* accumulated. `settings` and `context` are rebuilt
        from configuration and must not come from a file, or a change to either
        would be silently ignored until somebody deleted one.
        """
        return {
            "day": self.day,
            "opening_equity": self.opening_equity,
            "realised": self.realised,
            "trades": self.trades,
            "wins": self.wins,
            "halted": self.halted,
            "basket_peak": self.basket_peak,
            "last_loss": dict(self.last_loss),
        }

    def restore(self, saved: object, now: float | None = None) -> bool:
        """Take the day's total back, if it is still the same day.

        See `trading-risk.md` in research/docs.
        """
        if not isinstance(saved, dict):
            return False
        day = str(saved.get("day") or "")
        if not day or day != _day(now if now is not None else time.time()):
            return False
        self.day = day
        self.opening_equity = float(saved.get("opening_equity") or 0.0)
        self.realised = float(saved.get("realised") or 0.0)
        self.trades = int(saved.get("trades") or 0)
        self.wins = int(saved.get("wins") or 0)
        self.halted = str(saved.get("halted") or "")
        self.basket_peak = float(saved.get("basket_peak") or 0.0)
        got = saved.get("last_loss")
        if isinstance(got, dict):
            self.last_loss = {
                str(k): float(v) for k, v in got.items() if isinstance(v, int | float)
            }
        if self.halted:
            log.info("trading: the halt from earlier today is still in force - %s", self.halted)
        return True

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
        self.basket_peak = 0.0
        return True

    @property
    def daily_loss_limit(self) -> float:
        return self.opening_equity * self.settings.daily_loss_fraction

    def basket(
        self,
        net: float,
        equity: float,
        progress: float | None = None,
        against: float = 0.0,
    ) -> str:
        """Why the whole book should be closed now, or "" to leave it open.

        **The gap this fills.** `daily_loss_fraction` halts *opening* on realised
        loss and leaves what is already open alone, so nothing in the desk acts on
        the floating total across positions. With `parallel` on, seventeen
        strategies can hold the same direction on the same instrument at once, and
        that is a single position seventeen times over as far as the account is
        concerned.

        Three rules, each off at zero, checked worst-first so a book that trips
        two is reported by the one that matters:

        * **give-back** - having shown a peak profit, close if the book hands back
          that share of it. A trailing stop on the basket rather than on a trade.
        * **stop** - close if the net loss reaches this share of the day's opening
          equity.
        * **take** - close if the net profit reaches this share of it.

        **This does not create edge and is not meant to.** With direction absent -
        see `research/docs/exits.md` - every exit rule has the same expectation
        before costs, and closing a book pays the spread on every leg. What it buys
        is a bounded tail: the desk stops being able to hold a losing basket open
        indefinitely, which is a risk decision rather than a profit one.
        """
        opening = self.opening_equity or equity
        if opening <= 0:
            return ""
        self.basket_peak = max(self.basket_peak, net)
        loss = self.settings.basket_stop_fraction
        if loss > 0 and net <= -loss * opening:
            return (
                f"the open book is {money(net, self.currency)}, past the "
                f"{loss:.1%} basket stop on {money(opening, self.currency, signed=False)}"
            )
        # **Momentum before give-back, because it is the same reversal seen sooner.**
        # Give-back waits for profit to be handed back; `cusum` measures net
        # directional progress without a window, so a book the market has turned
        # against is readable before the money is gone.
        heat = self.settings.basket_momentum
        if heat > 0 and against >= heat:
            return (
                f"momentum has run {against:.2f}v against the open book, past the "
                f"{heat:.2f}v it tolerates, with the book at {money(net, self.currency)}"
            )
        give = self.settings.basket_give_back
        # Only once there was a profit worth protecting. A peak of nothing would
        # make this fire on the first tick a book went red, which is the stop's
        # job and at the stop's threshold, not this one's.
        if give > 0 and self.basket_peak > 0 and net <= self.basket_peak * (1.0 - give):
            spare = self.settings.basket_spare_progress
            # Nearly home is a reason to wait, not to close. The dip may be the
            # last pullback before the targets, and closing pays the spread on
            # every leg to avoid it. Only the give-back is spared: the stop is a
            # loss limit and answers to nothing else.
            if spare > 0 and progress is not None and progress >= spare:
                return ""
            return (
                f"the open book peaked at {money(self.basket_peak, self.currency)} "
                f"and is {money(net, self.currency)}, having given back {give:.0%}"
            )
        take = self.settings.basket_take_fraction
        if take > 0 and net >= take * opening:
            return f"the open book is {money(net, self.currency)}, at the {take:.1%} basket target"
        return ""

    def allows(  # noqa: PLR0912 - one gate per branch, in the order they are
        # applied. Splitting them across helpers would hide that order, and the
        # order is the design: cheap refusals about the signal come before the
        # arithmetic, and the arithmetic before anything touching the book.
        self,
        intent: Intent,
        *,
        positions: list[Position],
        tick: Tick | None = None,
        now: float | None = None,
        risk_of: dict[int, float] | None = None,
        feed_of: dict[str, str] | None = None,
        limits: Limits | None = None,
    ) -> Refusal | None:
        """None if this trade may go ahead, else the gate that stopped it.

        Ordered cheapest-first and most-decisive-first, which happen to agree:
        a halted day and a blackout are facts that need no arithmetic, and
        checking them before sizing anything keeps the log honest about what
        actually stopped a trade. A refusal names one gate, so the order
        decides which one gets named when several apply.
        """
        when = now if now is not None else time.time()
        # The strategy's own values where it names any, the deployment's where it
        # does not. Never the account's - see `Limits` on what is absent and why.
        mine = limits or Limits()

        if self.halted:
            return self._no("halted", intent.feed, self.halted)

        # **Before anything else about the signal, because it is about the clock.**
        # The broker's quotes widen around the daily rollover - 15.4x the median
        # spread at 21:00 UTC - and 14% of closed trades were opened in that window
        # for 45% of the loss. `max_spread_fraction` cannot catch it, since it
        # compares the spread to the reward and a distant target passes however
        # wide the quote is. See `Settings.quiet_hours`.
        quiet = self.settings.quiet_hours
        if quiet:
            hour = datetime.fromtimestamp(when, UTC).hour
            if hour in quiet:
                return self._no(
                    "quiet_hour",
                    intent.feed,
                    f"{hour:02d}:00 UTC is a quiet hour - the spread is widest around "
                    f"the rollover and nothing opens here",
                )

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
        cooldown = mine.cooldown(self.settings)
        if lost and when - lost < cooldown:
            left = cooldown - (when - lost)
            return self._no("cooldown", intent.feed, f"{left:.0f}s left after a loss")

        # Zero is off, explicitly, like every other floor here. Relying on
        # "nothing is below zero" would leave the gate looking enforced in a
        # reading of the code while doing nothing, and this repository has
        # spent a day finding checks that were quietly inert.
        #
        # Re-verified 2026-08-27 over 47,676 production touches joined to the
        # signals that produced them: 0.908R ungated against 0.868R at the 1.2
        # floor that was live, monotonically worse as the floor rises. The
        # quality difference is 0.047R and the volume difference is everything
        # - it refused 40,421 of 47,676 calls to gain nothing. See
        # research/replay.md and todo 0f, whose original figures were computed
        # on realised push rather than R and overstated this fivefold.
        floor = mine.reward_floor(self.settings)
        if floor > 0 and intent.reward_to_risk < floor:
            return self._no(
                "reward_to_risk",
                intent.feed,
                f"{intent.reward_to_risk:.2f} against a {floor:.2f} floor",
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
        # **And against the risk**, which is the denominator the damage was
        # measured in. Scaling the permitted spread with the target lets a
        # distant target buy the right to pay more; a spread that is half the
        # stop distance is half the stop distance wherever the target sits. 49
        # trades passed the reward test while expensive against risk, at -0.471R
        # and 53% stopped, for -502.70. See `Settings.max_spread_risk_fraction`.
        limit = self.settings.max_spread_risk_fraction
        if tick is not None and limit > 0 and intent.risk > 0:
            share = tick.spread / intent.risk
            if share > limit:
                return self._no(
                    "spread_risk",
                    intent.feed,
                    f"spread is {share:.0%} of the risk, limit is {limit:.0%}",
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
        """The day in one line.

        Worded "won 0 of 1" rather than "0/1 won", because the second put the
        word *won* immediately after the count in an alert announcing a loss -
        "0/1 won, -$18.07 realised" - and it read as a win at a glance. The
        numbers were right and the sentence was not, which is worse than being
        wrong in a way people notice.
        """
        rate = f"won {self.wins} of {self.trades}" if self.trades else "no trades"
        state = f" · HALTED ({self.halted})" if self.halted else ""
        return f"{self.day or '-'}: {rate}, {money(self.realised, self.currency)} realised{state}"
