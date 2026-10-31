"""What would have happened to the trades the desk did not take.

Two instruments, both recorded and neither traded, and **nothing in Nautilus
does either**. The framework records what happened; this records what would
have.

* **`Untaken`** - a trade a strategy wanted and did not get, followed to its
  own barriers. A signal refused by a gate, or an entry that never filled.
* **`Shadow`** - a trade that *was* stopped, watched to see whether the target
  arrived anyway.

## Why this is not optional bookkeeping

**The deflated Sharpe needs the losers.** `Var(SR_trials)` in the DSR is a
variance over the whole search, so a trial count that quietly drops what was
declined makes every deflated Sharpe on this desk optimistic - the correction
shrinks as the recorded search looks smaller and more uniformly good. A
counterfactual that is allowed to lapse is a DSR that flatters itself, and the
failure is silent in both directions: the number still prints.

So the discipline is the same one `node/selection.py` applies to a sweep, one
level down: keep the losers, because the losers are what the correction is
computed from.

## The shadow answers the one question the account cannot

**A stop hit at full size looks the same whether the level failed or the stop
sat inside the noise.** Until this existed the argument about stop width had
nothing but reasoning to settle it. `best_r` is how far the trade got in units
of the risk it was stopped for, so **above 1 means the stop cost a winner** -
and a distribution of those is the evidence a width argument needs.

## The fill is never assumed

`Untaken` waits for a price that actually traded before it starts the barrier
race. Crediting a rested entry with a price it never traded at would rank it
above strategies that paid the spread to be certain - which is the comparison
the whole record exists to make, so getting it wrong inverts the answer.

Both sides are paid as a real trade would pay them: the entry side coming in,
the exit side going out. A counterfactual filled at the mid and exited at the
mid is a strategy that never paid a spread, and it will beat every real one.

## `regime` is carried, which fixes a recorded gap

`research/choosing.md` measured 536 untaken trades and found the three
strategies with real samples at **-0.172, -0.179 and -0.190R** -
indistinguishable, so a selector has nothing to select on. Its own note on what
it could not ask:

> The interesting version of that question is conditional: strategies could be
> alike pooled and separate cleanly within a state. It could not be asked,
> because `regime` is on every level call and was dropped here.

So `regime` and `market` are fields rather than an afterthought, and
`by_market` splits the record by them. The conditional question is the one
worth asking and it was unanswerable for want of one column.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..domain.models import Intent, Side

#: How long an unfilled intent waits before it is recorded as never filled, as
#: a multiple of the hold it would have had. Beyond this the signal it came
#: from is stale and a fill would be a different trade.
FILL_WINDOW = 1.0

#: How long a stopped trade is watched, as a multiple of the hold it would have
#: had. The trade's own horizon, because that is the window in which its target
#: was a claim.
SHADOW_WINDOW = 1.0


@dataclass(slots=True)
class Untaken:
    """A trade a strategy wanted and did not get, followed to its barriers."""

    feed: str
    by: str
    side: Side
    entry: float
    stop: float
    target: float
    interval: str
    #: When to give up waiting for the fill.
    fill_by: float
    #: How long the trade may run once filled.
    hold: float
    placed_at: float = 0.0
    #: Zero until it fills, then the time it did.
    filled_at: float = 0.0
    #: When the barrier race ends. Set at fill.
    until: float = 0.0
    #: Last exit-side price seen since the fill, for a timeout's mark.
    last: float = 0.0
    #: What the market was doing when the signal was found. **Carried so the
    #: counterfactual can be split by it** - see the module docstring.
    regime: float = 0.0
    market: str = ""

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)


@dataclass(slots=True)
class Shadow:
    """A trade that was stopped, watched to see whether it was right anyway."""

    feed: str
    side: Side
    entry: float
    stop: float
    target: float
    by: str
    #: When the watch gives up, which is the hold the trade would have had.
    until: float
    #: Furthest exit-side price reached in the trade's favour since the stop.
    best: float = 0.0
    stopped_at: float = 0.0

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)


@dataclass(frozen=True, slots=True)
class Resolved:
    """One counterfactual that has finished, ready to be journalled.

    Returned rather than written, so the resolution is testable without a
    journal - the same split `Exits` uses and the same reason `read_rows` is a
    module function.
    """

    #: "untaken" or "shadow".
    shape: str
    feed: str
    by: str
    #: How it ended: never filled, target, stop, timeout - or for a shadow,
    #: reached or never reached.
    how: str
    #: The outcome in units of the risk it was sized for. For an untaken
    #: trade: +R at target, -1 at stop, the mark on a timeout, 0 unfilled. For
    #: a shadow: how far it got, where **above 1 means the stop cost a
    #: winner**.
    reward: float
    when: float
    regime: float = 0.0
    market: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Counterfactual:
    """The untaken and shadow records for one strategy.

    Held by the strategy, like `Exits`, so it can only ever follow trades that
    strategy wanted. `observe` folds in a quote and returns whatever finished;
    the caller journals.
    """

    fill_window: float = FILL_WINDOW
    shadow_window: float = SHADOW_WINDOW
    _untaken: dict[str, list[Untaken]] = field(default_factory=lambda: defaultdict(list))
    _shadows: dict[Any, Shadow] = field(default_factory=dict)

    # ------------------------------------------------------------ the recording

    def wanted(
        self,
        intent: Intent,
        *,
        by: str,
        now: float,
        hold: float,
        regime: float = 0.0,
        market: str = "",
    ) -> Untaken | None:
        """Follow a trade a gate refused, or an entry that never filled.

        None when there is no risk to measure against: a stop at the entry
        gives a zero denominator, and an R with a zero denominator is not a
        small number, it is not a number.
        """
        if abs(intent.entry - intent.stop) <= 0.0:
            return None
        shade = Untaken(
            feed=intent.feed,
            by=by,
            side=intent.side,
            entry=intent.entry,
            stop=intent.stop,
            target=intent.target,
            interval=intent.interval,
            fill_by=now + hold * self.fill_window,
            hold=hold,
            placed_at=now,
            regime=regime,
            market=market,
        )
        self._untaken[intent.feed].append(shade)
        return shade

    def stopped(
        self, position_id: Any, intent: Intent, *, by: str, now: float, hold: float
    ) -> Shadow | None:
        """Watch a stopped trade to see whether its target arrived anyway."""
        if abs(intent.entry - intent.stop) <= 0.0:
            return None
        shade = Shadow(
            feed=intent.feed,
            side=intent.side,
            entry=intent.entry,
            stop=intent.stop,
            target=intent.target,
            by=by,
            until=now + hold * self.shadow_window,
            best=intent.entry,
            stopped_at=now,
        )
        self._shadows[position_id] = shade
        return shade

    # ----------------------------------------------------------- the resolution

    def observe(self, feed: str, bid: float, ask: float, now: float) -> list[Resolved]:
        """Walk every unresolved record on this feed one quote forward."""
        return self._step_untaken(feed, bid, ask, now) + self._step_shadows(feed, bid, ask, now)

    def _step_untaken(self, feed: str, bid: float, ask: float, now: float) -> list[Resolved]:
        kept = self._untaken.get(feed)
        if not kept:
            return []
        done: list[Resolved] = []
        alive: list[Untaken] = []
        for shade in kept:
            got = self._one_untaken(shade, bid, ask, now)
            if got is None:
                alive.append(shade)
            else:
                done.append(got)
        if alive:
            self._untaken[feed] = alive
        else:
            self._untaken.pop(feed, None)
        return done

    def _one_untaken(self, shade: Untaken, bid: float, ask: float, now: float) -> Resolved | None:
        """One quote against one intent. A `Resolved` when it is finished with.

        Fill first, then the barrier race - and both sides paid as a real trade
        would pay them.
        """
        sign = shade.side.sign
        # Coming in: a buy pays the ask. Going out: a buy is closed at the bid.
        coming = ask if shade.side is Side.BUY else bid
        going = bid if shade.side is Side.BUY else ask

        if not shade.filled_at:
            if (coming - shade.entry) * sign <= 0:
                shade.filled_at = now
                shade.until = now + shade.hold
                shade.last = going
                return None
            if now >= shade.fill_by:
                return self._resolve(shade, "never filled", 0.0, now)
            return None

        shade.last = going
        risk = shade.risk
        if risk <= 0.0:
            return self._resolve(shade, "no risk", 0.0, now)
        if (going - shade.target) * sign >= 0:
            return self._resolve(shade, "target", abs(shade.target - shade.entry) / risk, now)
        if (going - shade.stop) * sign <= 0:
            return self._resolve(shade, "stop", -1.0, now)
        if now >= shade.until:
            return self._resolve(shade, "timeout", ((going - shade.entry) * sign) / risk, now)
        return None

    def _resolve(self, shade: Untaken, how: str, reward: float, when: float) -> Resolved:
        return Resolved(
            shape="untaken",
            feed=shade.feed,
            by=shade.by,
            how=how,
            reward=round(reward, 4),
            when=when,
            regime=shade.regime,
            market=shade.market,
            extra={
                "interval": shade.interval,
                "entry": round(shade.entry, 8),
                "stop": round(shade.stop, 8),
                "target": round(shade.target, 8),
                "filled": bool(shade.filled_at),
                "waited": round(when - shade.placed_at, 1),
            },
        )

    def _step_shadows(self, feed: str, bid: float, ask: float, now: float) -> list[Resolved]:
        done: list[Resolved] = []
        for position_id, shade in list(self._shadows.items()):
            if shade.feed != feed:
                continue
            price = bid if shade.side is Side.BUY else ask
            sign = shade.side.sign
            if (price - shade.best) * sign > 0:
                shade.best = price
            hit = (price - shade.target) * sign >= 0
            if not (hit or now >= shade.until):
                continue
            self._shadows.pop(position_id, None)
            went = (shade.best - shade.entry) * sign
            risk = shade.risk
            # Clamped at zero: a trade that never got in front of its entry
            # did not get part of the way to its target, it got nowhere, and a
            # negative "how far it reached" would average as progress.
            reach = (abs(shade.best - shade.entry) / risk) if risk and went > 0 else 0.0
            done.append(
                Resolved(
                    shape="shadow",
                    feed=shade.feed,
                    by=shade.by,
                    how="reached" if hit else "never reached",
                    reward=round(reach, 4),
                    when=now,
                    extra={
                        "position_id": str(position_id),
                        "best": round(shade.best, 8),
                        "target": round(shade.target, 8),
                        "stopped_at": round(shade.stopped_at, 8),
                        # Above 1 means the stop cost a winner.
                        "cost_a_winner": reach >= 1.0,
                    },
                )
            )
        return done

    def forget(self, position_id: Any) -> None:
        """Drop a shadow early - the position re-opened, so it is not stopped."""
        self._shadows.pop(position_id, None)

    # -------------------------------------------------------------- the reading

    @property
    def following(self) -> int:
        """How many records are still unresolved. **The number that must not
        quietly go to zero**: a counterfactual that lapses is a DSR that
        flatters itself."""
        return sum(len(v) for v in self._untaken.values()) + len(self._shadows)

    @staticmethod
    def by_market(resolved: list[Resolved]) -> dict[str, list[float]]:
        """Rewards grouped by the market state the signal was found in.

        The split `research/choosing.md` could not make. Pooled, the three
        strategies with real samples were indistinguishable at -0.172, -0.179
        and -0.190R; whether they separate *within* a state is the question
        that was left open for want of this column.
        """
        out: dict[str, list[float]] = defaultdict(list)
        for row in resolved:
            out[row.market or "(unknown)"].append(row.reward)
        return dict(out)

    @staticmethod
    def by_strategy(resolved: list[Resolved]) -> dict[str, list[float]]:
        """Rewards grouped by which strategy wanted the trade."""
        out: dict[str, list[float]] = defaultdict(list)
        for row in resolved:
            out[row.by or "(unattributed)"].append(row.reward)
        return dict(out)
