"""Scoring what the trader actually did, from the journal.

Every trade writes two entries: a `decision` carrying the numbers it was sized
from, and an `outcome` pointing back at it with what happened. Pairing them is
the whole evaluation, and this module does only that — reads the pairs, groups
them, and reports.

**It computes no claim the data cannot carry.** Three disciplines, all of them
taken from how the rest of the project measures itself:

*Report R, not money.* A win of 40 on a trade risking 20 and a win of 40 on one
risking 200 are not the same result, and averaging currency hides it. R is
profit over the risk the trade was sized for, which is the only unit in which
trades of different sizes are comparable.

*Say the count, always, next to the number.* A 70% win rate over ten trades is
a coin that came up heads seven times. `verdict` refuses to characterise a
sample under `ENOUGH`, and the CLI prints that refusal rather than hiding it in
a footnote.

*Compare against the base rate.* A strategy's win rate means nothing without
what the account did overall, so every row carries the pooled figure beside it.
This is the same discipline `structures` applies when it quotes P(up) against
the unconditional rate, for the same reason: a number with nothing to be
compared against reads as a finding when it is a summary.

The declines are counted too, per gate. A gate that never fires is doing
nothing and a gate that fires constantly is mis-set, and neither is visible
without the tally — which is why `Refusal` carries a machine-readable `gate` in
the first place.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..journal import DEFAULT_DB, Entry, Kind, read

#: Closed trades below which no rate is characterised. Not a significance
#: threshold — it is the point below which quoting a percentage misleads more
#: than it informs, and the honest output is the count itself.
ENOUGH = 30


@dataclass(frozen=True, slots=True)
class Trade:
    """One closed trade, rebuilt from its decision and its outcome."""

    strategy: str
    feed: str
    side: str
    mode: str
    profit: float
    risk_money: float
    seconds: float
    reason: str
    exit_source: str
    reward_to_risk: float
    opened: float

    @property
    def r(self) -> float:
        """Profit in units of the risk it was sized for."""
        return self.profit / self.risk_money if self.risk_money > 0 else 0.0

    @property
    def won(self) -> bool:
        return self.profit > 0


@dataclass(slots=True)
class Group:
    """What a set of trades did. Named rather than a tuple, because six
    numbers positionally is how a win rate ends up printed as a mean R."""

    name: str
    trades: list[Trade] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for trade in self.trades if trade.won)

    @property
    def win_rate(self) -> float:
        return self.wins / self.count if self.count else 0.0

    @property
    def mean_r(self) -> float:
        return statistics.fmean(t.r for t in self.trades) if self.trades else 0.0

    @property
    def total_r(self) -> float:
        return sum(t.r for t in self.trades)

    @property
    def profit(self) -> float:
        return sum(t.profit for t in self.trades)

    @property
    def median_seconds(self) -> float:
        return statistics.median(t.seconds for t in self.trades) if self.trades else 0.0

    @property
    def enough(self) -> bool:
        return self.count >= ENOUGH

    def verdict(self, against: float | None = None) -> str:
        """A sentence, or a refusal to give one.

        The refusal is the point. Everything here is being collected precisely
        because the question cannot be answered yet, and a report that produced
        a confident line anyway would be the thing this project keeps finding
        in its own history.
        """
        if not self.count:
            return "no closed trades"
        if not self.enough:
            return f"{self.count} trades — too few to characterise (need {ENOUGH})"
        edge = ""
        if against is not None:
            edge = f", {self.win_rate - against:+.1%} against the pooled rate"
        return (
            f"{self.count} trades, {self.win_rate:.0%} won{edge}, "
            f"{self.mean_r:+.2f}R mean, {self.total_r:+.1f}R total"
        )


@dataclass(slots=True)
class Report:
    """Everything the journal can say about the trader so far."""

    overall: Group
    by_strategy: dict[str, Group] = field(default_factory=dict)
    by_feed: dict[str, Group] = field(default_factory=dict)
    #: gate -> how many trades it refused. Strategy-level refusals are not
    #: journalled (there are hundreds a day and they are the filter working),
    #: so this is the account saying no to something a strategy wanted.
    declines: dict[str, int] = field(default_factory=dict)
    #: Resolutions seen for instruments we trade, whether or not we traded them.
    open_trades: int = 0

    @property
    def enough(self) -> bool:
        return self.overall.enough

    def __str__(self) -> str:
        return self.overall.verdict()


def _number(context: dict[str, Any], name: str, default: float = 0.0) -> float:
    value = context.get(name, default)
    return float(value) if isinstance(value, int | float) else default


def _text(context: dict[str, Any], name: str) -> str:
    value = context.get(name)
    return str(value) if value is not None else ""


def trades(path: Path | str = DEFAULT_DB, *, limit: int = 100_000) -> list[Trade]:
    """Every closed trade in the journal, oldest first.

    Built by pairing outcomes to their parents rather than by reading outcomes
    alone, because the outcome carries what happened and the decision carries
    what was intended — the strategy that opened it, and the risk it was sized
    for, which is the denominator of every number worth reporting.
    """
    outcomes = read(path, actor="trading", kind=Kind.OUTCOME, limit=limit)
    if not outcomes:
        return []
    decisions: dict[str, Entry] = {
        entry.id: entry for entry in read(path, actor="trading", kind=Kind.DECISION, limit=limit)
    }

    found: list[Trade] = []
    for outcome in outcomes:
        parent = decisions.get(outcome.parent)
        if parent is None:
            # An outcome whose decision has aged out of the window, or a
            # position adopted on start-up that nothing here decided. Skipped
            # rather than counted with a zero risk, which would land as an
            # infinite R or a silent zero.
            continue
        context = {**parent.context, **outcome.context}
        risk = _number(context, "risk_money")
        if risk <= 0:
            continue
        found.append(
            Trade(
                strategy=_text(context, "strategy") or "unknown",
                feed=_text(context, "feed"),
                side=_text(context, "side"),
                mode=_text(context, "mode") or "paper",
                profit=_number(context, "profit"),
                risk_money=risk,
                seconds=_number(context, "seconds"),
                reason=_text(context, "reason"),
                exit_source=_text(context, "exit_source"),
                reward_to_risk=_number(context, "reward_to_risk"),
                opened=parent.time,
            )
        )
    found.sort(key=lambda t: t.opened)
    return found


def declines(path: Path | str = DEFAULT_DB, *, limit: int = 100_000) -> dict[str, int]:
    """How many trades each gate refused, by gate name."""
    counted: dict[str, int] = defaultdict(int)
    for entry in read(path, actor="trading", kind=Kind.OBSERVATION, limit=limit):
        gate = _text(entry.context, "gate")
        if gate:
            counted[gate] += 1
    return dict(counted)


def build(
    path: Path | str = DEFAULT_DB,
    *,
    mode: str = "",
    strategy: str = "",
    limit: int = 100_000,
) -> Report:
    """Read the journal and score it.

    `mode` filters to paper or live, and defaults to **both together**, which
    is wrong for judging a strategy and right for seeing everything. The CLI
    defaults to splitting them, because paper fills are simulated and live ones
    are not, and averaging the two produces a number describing neither.
    """
    found = trades(path, limit=limit)
    if mode:
        found = [t for t in found if t.mode == mode]
    if strategy:
        found = [t for t in found if t.strategy == strategy]

    report = Report(overall=Group("overall", found))
    for trade in found:
        report.by_strategy.setdefault(trade.strategy, Group(trade.strategy)).trades.append(trade)
        report.by_feed.setdefault(trade.feed, Group(trade.feed)).trades.append(trade)
    report.declines = declines(path, limit=limit)
    return report
