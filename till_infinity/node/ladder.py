"""The promotion loop, running inside the live node.

`pipeline.py` is the loop - discover, gate, small capital, full capital, and
back out again - with its state persisted, a ceiling no amount of passing can
lift, and every decision written with its evidence. **Its only importer was
`tests/test_pipeline.py`.** `node/live.py` never mentioned it, so the basket
was whatever `TRADING_STRATEGIES` named, for ever: nothing promoted, nothing
retired, and a discovery run had nowhere to deliver a candidate to. This is the
caller it was written for.

## Why an actor and a handler, rather than one of either

`pipeline.step` decides and does not act, and the docstring says why: "the node
holds the `Trader`, so this decides and the caller acts. A function that both
decides and places orders cannot be tested without a kernel, and this is the
function that must never be wrong."

An `Actor` cannot act either, and that is the part that shapes this file.
Nautilus gives an actor the bus, the cache, the clock and the portfolio.
Stopping a strategy is `Trader.stop_strategy`, and an actor has no trader; the
notional cap is `RiskEngine.set_max_notional_per_order`, and an actor has no
risk engine. So the work splits where the framework splits it: the actor
decides, records, persists and **publishes**, and `node/live` subscribes a
handler closed over the trader and the risk engine. One hop, and the capital
change happens where the engine is rather than behind a second copy of the
arithmetic.

## What it will not do

**It does not invent candidates.** A fresh deploy has an empty ladder and the
loop does nothing, which is the safe state and also the honest one: a strategy
the node is running was put there by configuration, and seeding it onto the
ladder at a rung it never passed a gate for would hand it an allocation the
gates did not grant. Candidates arrive by being written to the ladder file - by
a discovery run, or by a person - and an empty ladder is reported rather than
passed over, because a loop that logs nothing is indistinguishable from one
that has stopped.

**It is off unless asked.** `TRADING_LADDER` is the switch and it is not set by
default. This is the one actor on the node that changes how much money a
strategy may use, and `TRADING_LIVE` is the precedent: the thing that can trade
is off until somebody says otherwise.

**It never retires on recent performance.** `strategy-rotation-is-not-timeable`
is measured here - every pause rule tested matched random pausing at the same
duty cycle - so this loop promotes on pre-registered gates and retires only on
the reasons `promotion.may_retire` accepts, each of which needs evidence. The
loop has no opinion about a leg having a bad week, and `promotion.book_evidence`
returns nothing at all on a sample under `promotion.live_episodes`.

## The episode count is the sample, and it comes from the cache

A rung's decision is fixed on a number of **episodes**, and an episode here is
a closed position. `Cache.positions_closed(strategy_id=...)` is the count, so
the candidate's name has to be the strategy id Nautilus assigned - which is
what `node/desks._tag` builds and what every order, fill and position already
carries. Counting fills instead would count a scale-out twice.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig
from nautilus_trader.model.identifiers import StrategyId

from till_infinity.utils import effects
from till_infinity.utils.topics import LADDER

from .pipeline import Ladder, report, step
from .promotion import Allocation, Candidate, Rung

#: **An enabled ladder that never decides anything looks exactly like a
#: disabled one.** Declared here, where the flag is read, so an operator can
#: tell "switched on and holding every candidate" from "switched off" - which
#: is the whole subject of `utils/effects.py`.
effects.declare("node.ladder", enabled=False)

#: How often the loop looks, in seconds. Fifteen minutes.
#:
#: A rung's decision needs tens of closed positions, and the fastest thing on
#: this desk closes in minutes - so a pass every fifteen minutes is far more
#: often than the state can change, which is the right side to err on: the cost
#: of a pass is a cache query and the cost of missing one is a leg trading at an
#: allocation the ladder has already revoked.
EVERY = 900.0

#: Where the ladder is kept between runs.
#:
#: Under `.data/`, which is the mounted volume - `docker-compose.yml` binds it,
#: and an unmounted path would start every deploy with an empty ladder and
#: silently lose every candidate's position and history.
PATH = ".data/ladder.json"


@dataclass(slots=True)
class Episodes:
    """Closed positions already counted, per candidate.

    **The arithmetic that must not be wrong, as a plain object.** The cache
    keeps every closed position for the life of the process, so a pass that
    read the total and added it would multiply the sample by the number of
    passes - a candidate needing ten episodes would promote on its second pass
    having traded once. The pairing of "what the cache says now" with "what was
    already counted" is where that goes wrong, so it lives here rather than
    inside a handler, and is testable without a kernel. Same argument as
    `pipeline.step` and `strategies/sizes.py`.
    """

    counted: dict[str, int] = field(default_factory=dict)

    def since(self, name: str, closed: int) -> int:
        """New closed positions since the last pass, and remember the total.

        Zero when the count has not moved, and zero rather than a negative
        when it has gone *down* - which it does on a restart, because the cache
        starts empty and this object does not.
        """
        seen = self.counted.get(name, 0)
        if closed <= seen:
            return 0
        self.counted[name] = closed
        return closed - seen


def named(name: str) -> StrategyId | None:
    """`name` as a strategy id, or `None` if it is not one.

    A ladder may hold a candidate this node is not running - a discovery that
    has not been deployed, or a name from another host. `None` rather than a
    raise: the gates will hold it for want of episodes, which is the correct
    outcome, and a loop that raised on somebody else's candidate would stop
    deciding about its own.
    """
    try:
        return StrategyId(name)
    except ValueError:
        return None


def allocation_message(name: str, candidate: Candidate) -> dict[str, object]:
    """What a promotion means for capital, as the node is told it.

    **The share, not a notional.** The handler in `node/live` holds the risk
    engine and the account, so it converts once, where the equity is. A
    notional computed here would be computed from a portfolio read at a
    different moment than the one the cap is applied at - and the engine
    denominates the cap in the instrument's quote currency, which only the
    side holding the instrument can see.
    """
    return {
        "candidate": name,
        "action": "allocate",
        "rung": candidate.rung.value,
        "share": float(candidate.allocation),
    }


class LadderConfig(ActorConfig, frozen=True):
    """Where the ladder lives and how often it is walked."""

    path: str = PATH
    every: float = EVERY
    #: The share of the account each rung may use. The defaults are
    #: `Allocation`'s: 5% at small, everything at full, bounded by
    #: `pipeline.CEILING` across the whole ladder.
    small: float = 0.05
    full: float = 1.0


class LadderActor(Actor):
    """Walks the ladder on a timer, and publishes what the node must do."""

    def __init__(self, config: LadderConfig) -> None:
        super().__init__(config)
        self._cfg = config
        self.ladder = Ladder()
        self._episodes = Episodes()
        self.passes = 0
        self.decisions = 0

    # ----------------------------------------------------------- the lifecycle

    def on_start(self) -> None:
        """Load the ladder, say what is on it, then start the timer.

        The report comes before the first pass on purpose. An operator reading
        the log after a deploy wants to know what the loop inherited, and a
        loop that only speaks when it changes something cannot answer that.
        """
        self.ladder = Ladder.load(Path(self._cfg.path))
        self._seed()
        for line in report(self.ladder):
            self.log.info(line)
        self.clock.set_timer(
            name="ladder",
            interval=self._interval(),
            callback=self._walk,
        )

    def _seed(self) -> None:
        """Put every strategy this node runs onto the ladder, at the bottom.

        **At `DISCOVERED`, which grants nothing.** `Allocation.of` is zero
        there, and `Candidate.blocking` refuses to climb with "no gate has been
        run" - so a seeded leg is on the ladder, visible, and held until
        something gates it. Seeding at a rung it had passed no gate for would
        hand it an allocation the gates did not grant, which is the one thing
        this loop must not do.

        Seeded rather than left empty because an empty ladder says nothing. A
        node with twelve legs and no candidates logs "0 candidates" and an
        operator learns only that the loop is idle; the same node seeded logs
        twelve legs each held for want of a gate, which is a true and useful
        statement about the desk - and it is the statement this whole exercise
        kept arriving at.

        It also only ever *tightens*. An unseeded strategy has no notional cap
        at all, so the first promotion a seeded one earns replaces "no limit"
        with five percent of the account.
        """
        known = set(self.ladder.candidates)
        for strategy_id in self.cache.strategy_ids():
            name = str(strategy_id)
            if name in known:
                continue
            self.ladder.candidates[name] = Candidate(name=name, origin="configured on this node")
            self.ladder.enter(name, self.clock.timestamp())
            self.log.info(f"ladder seeded {name} at {Rung.DISCOVERED.value}, allocating nothing")

    def on_stop(self) -> None:
        """Save, and say what the loop did.

        Saved on stop as well as on every pass, because the episode counts and
        the hold reasons move without a decision being taken - and a restart
        that forgot them would re-log every hold and re-count every episode.
        """
        self._save()
        self.log.info(
            f"ladder: {self.passes} pass(es), {self.decisions} decision(s), "
            f"{self.ladder.allocated():.0%} allocated"
        )

    def _interval(self):
        from datetime import timedelta

        return timedelta(seconds=max(1.0, self._cfg.every))

    # ----------------------------------------------------------------- the loop

    def _walk(self, event: Any = None) -> None:  # noqa: ARG002 - the timer passes one
        """One pass: count the episodes, decide, record, publish.

        Failures are swallowed and counted rather than raised. This runs on a
        timer inside the node that is trading, and a loop that cannot read its
        own file must not take the desk down with it - the allocation already in
        force stays in force, which is the safe direction.
        """
        try:
            self.passes += 1
            self._count()
            decided = step(self.ladder, allocation=self._allocation())
            for decision in decided:
                self.decisions += 1
                self.log.info(decision.line())
                self._journal(decision)
                if decision.action == "promoted":
                    self._publish(decision.candidate)
            if decided:
                effects.fired("node.ladder", len(decided))
            self._save()
        except Exception as exc:  # a loop that cannot decide is not a halt
            self.log.error(f"ladder pass failed: {exc}")

    def _count(self) -> None:
        """Closed positions since the last pass, per candidate.

        **The delta, not the total.** `Cache.positions_closed` returns every
        closed position the process has seen, so adding it each pass would
        multiply the sample by the number of passes and promote a candidate on
        a sample it has not traded.
        """
        for name in self.ladder.candidates:
            found = named(name)
            if found is None:
                continue
            closed = len(self.cache.positions_closed(strategy_id=found))
            fresh = self._episodes.since(name, closed)
            if fresh:
                self.ladder.note_episodes(name, fresh)

    def _allocation(self) -> Allocation:
        return Allocation(small=self._cfg.small, full=self._cfg.full)

    def _publish(self, name: str) -> None:
        """Tell the node what a promotion means for capital.

        The share, not a notional: the handler in `node/live` holds the risk
        engine and the account, so it converts once, where the equity is. A
        notional computed here would be computed from a portfolio read at a
        different moment than the one the cap is applied at.
        """
        candidate = self.ladder.candidates.get(name)
        if candidate is None:
            return
        self.msgbus.publish(LADDER, allocation_message(name, candidate))

    def _journal(self, decision: Any) -> None:
        """Every decision in the record, not only in a log.

        An unattended loop's log rotates and its decisions are the thing a
        person reviews when the same candidate comes back round - which
        `pipeline.py`'s own docstring gives as the reason the evidence is
        written at all. Swallowed on failure for the same reason the desk's is:
        a record that cannot be written must not stop the loop.
        """
        from till_infinity.journal.actor import publish
        from till_infinity.journal.models import Entry, Kind

        try:
            publish(
                self,
                Entry(
                    title=f"{decision.action} {decision.candidate}",
                    kind=Kind.DECISION,
                    actor=str(self.id),
                    rationale=decision.reason,
                    context={
                        "candidate": decision.candidate,
                        "action": decision.action,
                        "evidence": decision.evidence,
                        "allocated": f"{self.ladder.allocated():.4f}",
                    },
                    tags=("ladder", decision.action),
                ),
            )
        except Exception as exc:
            self.log.debug(f"ladder journal refused {decision.action}: {exc}")

    def _save(self) -> None:
        try:
            self.ladder.save(Path(self._cfg.path))
        except Exception as exc:
            self.log.error(f"ladder could not be saved to {self._cfg.path}: {exc}")

    # -------------------------------------------------------------- retirement

    def retire(self, name: str, reason: Any, *, evidence: str = "") -> str:
        """Take a candidate off, and publish what the node must do about it.

        Not called on a timer, and that is the design rather than an omission.
        A retirement needs a reason `may_retire` accepts and evidence that can
        be rerun; nothing on a fifteen-minute clock produces either. What
        produces them is a null test failing on newer data, a cost measurement,
        a breached limit, or a replacement passing its own gate - and each of
        those arrives from somewhere other than the passage of time.

        Returns the action the node is to take: `REDUCING` for a wind-down,
        `HALTED` for a breached limit, `none` if the retirement was refused.
        """
        from .pipeline import take_off

        decision, action = take_off(self.ladder, name, reason, evidence=evidence)
        self.decisions += 1
        self.log.warning(decision.line())
        self._journal(decision)
        if action != "none":
            self.msgbus.publish(
                LADDER,
                {"candidate": name, "action": action, "rung": "retired", "share": 0.0},
            )
        self._save()
        return action


def wanted() -> bool:
    """Whether this node runs the ladder. `TRADING_LADDER`, off.

    Off by default because this is the actor that changes how much of the
    account a strategy may use. `TRADING_LIVE` is the precedent and the same
    argument: the thing that can move money is off until somebody says
    otherwise, and a default that promotes would mean the next deploy of a node
    with a seeded ladder reallocated capital without anybody asking.
    """
    from till_infinity.utils.env import flag

    return flag("TRADING_LADDER")


def configured() -> LadderConfig:
    """The config from the environment, so a deploy can move the file."""
    return LadderConfig(
        path=os.environ.get("TRADING_LADDER_PATH") or PATH,
        every=float(os.environ.get("TRADING_LADDER_SECONDS", str(EVERY))),
    )
