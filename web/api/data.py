"""What the dashboard is allowed to know, read from the desk's own files.

**Nothing here recomputes a trade statistic.** `strategies.report` is what
pairs an outcome to the decision it judges - including the `risk_money`
fallback that, missing, hid 839 of 1,486 closed trades - and it is what every
R, win rate and verdict on the dashboard comes from. `journal.ledger` adds
levels up. `journal.store` reads entries. This module selects, windows and
shapes; a second implementation of the pairing is the bug class this repository
has paid for most often.

Two places that would otherwise look like duplication, both deliberate:

- `groups` repeats the three lines `report.build` uses to bucket trades,
  because `build` takes no time window and the dashboard's whole point is a
  selectable one. It buckets with `report.Group`, so every number is still
  that class's property. `test_web_api.py` pins it against `report.build` at
  the full window.
- `declines` delegates to `report.declines` when no window is asked for, and
  counts the same `context["gate"]` key when one is, for the same reason.

Read-only by construction: every sqlite connection here is opened `mode=ro`
(`journal.store.read_only` does it for the journal, and the bar store is
opened the same way), the parquet catalogues are only queried, and the import
graph reaches no `adapters/` or `node/` module - see `main.py`.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import math
import os
import sqlite3
import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from till_infinity.journal import DEFAULT_DB, Entry, Kind, ledger, read_only, summary
from till_infinity.journal import read as _read_entries
from till_infinity.strategies import report

#: Repository root, so a relative `TILL_JOURNAL_DB` resolves the same whether
#: uvicorn was started from here or from the repository root.
ROOT = Path(__file__).resolve().parents[2]

#: How many entries the journal reads reach for. `report` defaults to the same
#: figure; a window narrows what is *scored*, not what is read, because an
#: outcome's parent decision can sit well outside the window it closed in.
LIMIT = 100_000


#: How long a journal read is reused before the file is touched again.
#:
#: **This is not a latency optimisation, it is what keeps the dashboard off the
#: desk's back.** The production journal is a single unindexed table of about
#: 3.8GB, and `read` issues `WHERE actor = ? AND kind = ?` with an
#: `ORDER BY time DESC LIMIT n`. With no index that is a full scan and a sort
#: of the whole table, per call - and `journal-extraction-on-tis` records that
#: a `WHERE` there un-bounds the rowid limit, which is the same finding from
#: the other direction. The trading host has **two cores** and runs the live
#: desk on them; `tis-research-jobs-starve-the-service` is a measured outage
#: from exactly this shape of work.
#:
#: So every panel refresh must not re-scan. Thirty seconds is shorter than the
#: journal actor's own flush interval, so nothing is served staler than it
#: could have been written, and it turns a per-request scan into at most two a
#: minute however many people are looking.
READ_TTL_S = float(os.environ.get("TILL_WEB_READ_TTL", "30"))

#: Keyed by the exact query, holding `(monotonic_deadline, entries)`.
_READS: dict[tuple[Any, ...], tuple[float, list[Entry]]] = {}


def read(path: Any = DEFAULT_DB, **kwargs: Any) -> list[Entry]:
    """`journal.read`, memoised for `READ_TTL_S`.

    Same signature and same answer; the only difference is that a second
    identical question inside the window does not touch a 3.8GB file again.
    The returned list is shared, so **callers must not mutate it** - nothing
    here does, and the alternative is copying a hundred thousand entries to
    defend against a bug that does not exist yet.
    """
    key = (str(path), tuple(sorted((k, str(v)) for k, v in kwargs.items())))
    now = time.monotonic()
    found = _READS.get(key)
    if found is not None and found[0] > now:
        return found[1]
    entries = _read_entries(path, **kwargs)
    _READS[key] = (now + READ_TTL_S, entries)
    return entries


def forget() -> None:
    """Drop every memoised read. For tests, and for a manual refresh."""
    _READS.clear()


#: Interval names the bar stores use, in seconds. Markers are snapped to the
#: bar they fall in, because a marker whose time is not a bar's time is drawn
#: at whichever bar the chart library picks and reads as the wrong candle.
SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
}

#: Nautilus bar specifications, as the catalogue spells them in a directory
#: name, against the interval names the rest of the desk uses.
SPECS: dict[str, str] = {
    "1-MINUTE": "1m",
    "5-MINUTE": "5m",
    "15-MINUTE": "15m",
    "30-MINUTE": "30m",
    "1-HOUR": "1h",
    "4-HOUR": "4h",
    "1-DAY": "1d",
}

NANOS = 1_000_000_000


def journal_path() -> Path:
    """The journal to read. `TILL_JOURNAL_DB`, else `journal.DEFAULT_DB`."""
    return _resolve(os.environ.get("TILL_JOURNAL_DB") or DEFAULT_DB)


def prices_path() -> Path:
    """The sqlite bar store. `TILL_PRICES_DB`, else the collector's own path."""
    return _resolve(os.environ.get("TILL_PRICES_DB") or ".data/prices/prices.db")


def catalogues() -> dict[str, Path]:
    """Nautilus parquet catalogues to chart from, by the name the UI shows.

    `CORPUS_DIR` is the variable `node.backtest.catalogue()` reads, and is
    repeated rather than imported: importing that module would pull the
    backtest engine into a read-only web service for the sake of one path.
    """
    home = Path.home() / "till-data"
    return {
        "mt5": _resolve(os.environ.get("TILL_MT5_CATALOG") or str(home / "mt5")),
        "catalog": _resolve(os.environ.get("CORPUS_DIR") or str(home / "catalog")),
    }


def _resolve(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (ROOT / path)


# ------------------------------------------------------------------- shapes


@dataclass(frozen=True)
class Window:
    """The span asked for, and the span the trades in it actually cover."""

    since: float | None = None
    until: float | None = None
    days: int | None = None
    first: float | None = None
    last: float | None = None


@dataclass(frozen=True)
class GroupView:
    """One `report.Group`, flattened. Every field is that class's property."""

    name: str
    count: int
    wins: int
    win_rate: float
    mean_r: float
    total_r: float
    profit: float
    median_seconds: float
    enough: bool
    verdict: str
    #: Standard error of `mean_r`. `report.Group` does not carry one, and the
    #: house rule is that a mean without its standard error and its count is a
    #: number nobody can judge. `None` under two trades, where there is no
    #: spread to estimate.
    se_r: float | None = None


@dataclass(frozen=True)
class TradeView:
    """One closed trade: what it scored, and where it sat on a chart.

    `r`, `won`, `profit` and `risk_money` are `report.Trade`'s. The prices are
    read off the journal entries afterwards and are `None` when the record does
    not carry them - never zero, which on a price axis is a point at the bottom
    of the chart rather than a missing one.
    """

    key: str
    strategy: str
    feed: str
    side: str
    mode: str
    profit: float
    risk_money: float
    r: float
    won: bool
    seconds: float
    reason: str
    exit_source: str
    reward_to_risk: float
    opened: float
    closed: float | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    level_price: float | None = None
    interval: str = ""
    exit_kind: str = ""
    symbol: str = ""
    #: The desk-level label the profile gave this trade. Absent from every
    #: entry in the journals read so far - `context["rule"]` is simply not
    #: written yet - so it shows as the strategy's own name rather than blank.
    rule: str = ""
    #: The intent's own reason string, from the decision entry. The closest
    #: thing the record has to "why this trade".
    why: str = ""
    #: The close record's reason string.
    exit_why: str = ""
    level_id: str = ""
    scaled: bool = False
    stop_vol: float | None = None
    #: The spread at entry, in the units the journal recorded it - points for
    #: an MT5 feed, which is not price. Compared against nothing here; the
    #: comparison lives in `costs`.
    spread_at_entry: float | None = None
    slippage: float | None = None


@dataclass(frozen=True)
class EquityPoint:
    """Cumulative realised R and money after each closed trade, in close order."""

    index: int
    time: float
    r: float
    profit: float
    cumulative_r: float
    cumulative_profit: float


@dataclass(frozen=True)
class DeclineView:
    """One gate, and how many trades it refused."""

    gate: str
    count: int
    share: float


@dataclass(frozen=True)
class TurnView:
    """The turn model's exit against the one the trades took.

    `gained_r` is `None` rather than `nan` until something has been scored:
    `nan` is not JSON, and a zero here would read as "the model agreed".
    """

    scored: int
    reached: int
    took_r: float
    suggested_r: float
    gained_r: float | None
    summary: str


@dataclass(frozen=True)
class Overview:
    """Everything the header, the curve and the breakdowns need, in one read."""

    window: Window
    overall: GroupView
    by_strategy: list[GroupView]
    by_feed: list[GroupView]
    #: The desk-level label, where one was recorded. Grouped separately from
    #: the strategy because they are different names for different things and
    #: a rule that is quietly losing hides inside a strategy that is not.
    by_rule: list[GroupView]
    #: Count and mean R per close reason, and per `exit_source`. Which rule is
    #: doing the closing, and whether it beats letting the stop run.
    by_exit: list[GroupView]
    by_exit_source: list[GroupView]
    declines: list[DeclineView]
    turn_exit: TurnView
    equity: list[EquityPoint]
    trades: list[TradeView]
    modes: list[str]
    strategies: list[str]
    feeds: list[str]
    enough: int
    measured: list[Measured] = field(default_factory=list)
    costs: list[CostView] = field(default_factory=list)


@dataclass(frozen=True)
class Measured:
    """A research figure to put beside a live one, if the operator has any.

    Read from `TILL_MEASURED_JSON`, a file the operator writes: a map of
    strategy name to `{trades, win_rate, mean_r, se_r, hold_seconds}`. There is
    no such file by default and nothing in this repository produces one, so the
    column is blank rather than zero - a zero would read as "the backtest said
    nothing works", which is a different claim from "nobody has measured this".
    """

    strategy: str
    trades: int | None = None
    win_rate: float | None = None
    mean_r: float | None = None
    se_r: float | None = None
    hold_seconds: float | None = None
    source: str = ""


@dataclass(frozen=True)
class CostView:
    """What a feed actually paid to get in, from the decision records.

    `spread_at_entry` as the journal recorded it, which for an MT5 feed is in
    **points, not price** - a unit confusion here once read a 476% round trip
    on EURUSD and reordered every instrument by cost. Stated per feed and never
    pooled, and compared against nothing: the modelled median lives in
    `node/corpus.py`, and `node/` is deliberately outside this service's import
    graph.
    """

    feed: str
    trades: int
    median_spread: float | None
    mean_spread: float | None
    median_slippage: float | None
    worst_spread: float | None


@dataclass(frozen=True)
class LevelView:
    """One level's trading record, from `journal.ledger`."""

    level_id: str
    named: bool
    feed: str
    interval: str
    price: float
    trades: int
    wins: int
    hit_rate: float
    net: float
    strategies: list[str]
    endings: dict[str, int]


@dataclass(frozen=True)
class Levels:
    totals: dict[str, float]
    records: list[LevelView]
    message: str = ""


@dataclass(frozen=True)
class SeriesView:
    """One chartable (feed, interval), and what covers it."""

    feed: str
    interval: str
    source: str
    venue: str
    bars: int | None
    first: float | None
    last: float | None


@dataclass(frozen=True)
class BarView:
    """One candle. `time` is unix seconds, which is what the chart takes."""

    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class MarkerView:
    """An entry or an exit, snapped to the bar it falls in."""

    time: int
    price: float
    kind: str
    side: str
    strategy: str
    r: float
    label: str


@dataclass(frozen=True)
class RefusalMark:
    """Where the desk wanted a trade and a gate said no.

    The only record there is. Nautilus persists orders and fills; a trade that
    was never placed leaves nothing behind but the observation a gate wrote,
    which is why `why` carries the entry's own rationale rather than a
    reconstruction of it.
    """

    time: int
    price: float | None
    level: float | None
    gate: str
    strategy: str
    side: str
    feed: str
    why: str


@dataclass(frozen=True)
class LevelLine:
    """A level the desk actually traded or was refused at.

    Drawn from `context["level"]` on the entries for this feed, deduplicated to
    a tick. **A level's price is not its name** - the filter moves it whenever
    it learns something - so two prices a few ticks apart may be one level, and
    this does not pretend to know which.
    """

    price: float
    label: str
    traded: int
    refused: int


@dataclass(frozen=True)
class Chart:
    feed: str
    interval: str
    source: str
    venue: str
    bars: list[BarView]
    markers: list[MarkerView]
    refusals: list[RefusalMark] = field(default_factory=list)
    levels: list[LevelLine] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True)
class SourceState:
    """One file or directory the dashboard reads, and whether it is there."""

    name: str
    kind: str
    path: str
    present: bool
    detail: str = ""


@dataclass(frozen=True)
class Health:
    """What is readable on this machine, and what the journal actually holds.

    `entries` is `journal.summary` - actor, kind, count, first, last - because
    an empty dashboard over a journal that is full of `structures` rows is a
    different problem from an empty dashboard over a missing file, and the
    reader should not have to guess which.

    **It is populated only when `trades` is zero**, which is the case it was
    written for. `summary` scans the entire journal, and `health` is what the
    container healthcheck polls; see the note in `health` itself.
    """

    sources: list[SourceState]
    entries: list[dict[str, Any]] = field(default_factory=list)
    trades: int = 0
    message: str = ""


@dataclass(frozen=True)
class Event:
    """One journal entry, as the activity feed shows it."""

    time: float
    kind: str
    strategy: str
    feed: str
    gate: str
    title: str
    why: str


@dataclass(frozen=True)
class Pulse:
    """What one strategy has been doing lately, and when it last did anything."""

    strategy: str
    taken: int
    refused: int
    last_seen: float | None
    feeds: list[str]
    gates: list[DeclineView]


@dataclass(frozen=True)
class Activity:
    """The desk right now, from the journal.

    **Freshness is a field, not a vibe.** `age` is seconds since the newest
    trading entry, and the page says it out loud: four health signals once read
    green over a desk that could not trade, and a panel that looks live while
    the file underneath it stopped moving is the same failure.
    """

    hours: float
    now: float
    age: float | None
    taken: int
    refused: int
    strategies: list[Pulse]
    gates: list[DeclineView]
    recent: list[Event]


# ------------------------------------------------------------------ reading


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _price(context: dict[str, Any], name: str) -> float | None:
    value = context.get(name)
    return _finite(value) if isinstance(value, int | float) else None


def geometry(path: Path | str) -> dict[int, dict[str, Any]]:
    """Prices and close times for closed trades, keyed by the decision's time.

    **Drawing only.** Which outcomes count, and what each one risked, is
    `report.trades`' judgement and is not repeated here; this attaches the
    prices to trades that function has already accepted. The key is
    `Trade.opened`, which is the parent decision's `time`, in microseconds so
    two floats that print the same also match.

    A decision with no outcome, or an outcome carrying no price, simply has no
    entry here and its trade is drawn without markers.
    """
    outcomes = read(path, actor="trading", kind=Kind.OUTCOME, limit=LIMIT)
    by_parent: dict[str, Entry] = {}
    for entry in outcomes:
        if entry.parent:
            by_parent.setdefault(entry.parent, entry)

    found: dict[int, dict[str, Any]] = {}
    for decision in read(path, actor="trading", kind=Kind.DECISION, limit=LIMIT):
        outcome = by_parent.get(decision.id)
        if outcome is None:
            continue
        context = {**decision.context, **outcome.context}
        found[_key(decision.time)] = {
            "closed": outcome.time,
            "rule": str(decision.context.get("rule") or ""),
            "why": decision.rationale,
            "exit_why": outcome.rationale,
            "level_id": str(context.get("level_id") or ""),
            "scaled": bool(context.get("scaled") or False),
            "stop_vol": _price(decision.context, "stop_vol"),
            "spread_at_entry": _price(decision.context, "spread_at_entry"),
            "slippage": _price(outcome.context, "slippage"),
            "entry_price": _price(context, "entry_filled") or _price(context, "entry"),
            "exit_price": _price(context, "exit"),
            "stop_price": _price(context, "stop"),
            "target_price": _price(context, "target"),
            "level_price": _price(context, "level"),
            "interval": str(context.get("interval") or ""),
            "exit_kind": str(context.get("exit_kind") or ""),
            "symbol": str(context.get("symbol") or ""),
        }
    return found


def _key(when: float) -> int:
    return round(when * 1_000_000)


def views(found: Sequence[report.Trade], places: dict[int, dict[str, Any]]) -> list[TradeView]:
    """`report.Trade` plus whatever geometry the journal had for it."""
    out: list[TradeView] = []
    for index, trade in enumerate(found):
        extra = places.get(_key(trade.opened), {})
        out.append(
            TradeView(
                key=f"{_key(trade.opened)}-{index}",
                strategy=trade.strategy,
                feed=trade.feed,
                side=trade.side,
                mode=trade.mode,
                profit=trade.profit,
                risk_money=trade.risk_money,
                r=trade.r,
                won=trade.won,
                seconds=trade.seconds,
                reason=trade.reason,
                exit_source=trade.exit_source,
                reward_to_risk=trade.reward_to_risk,
                opened=trade.opened,
                closed=extra.get("closed") or (trade.opened + trade.seconds),
                entry_price=extra.get("entry_price"),
                exit_price=extra.get("exit_price"),
                stop_price=extra.get("stop_price"),
                target_price=extra.get("target_price"),
                level_price=extra.get("level_price"),
                interval=str(extra.get("interval") or ""),
                exit_kind=str(extra.get("exit_kind") or ""),
                symbol=str(extra.get("symbol") or ""),
                rule=str(extra.get("rule") or ""),
                why=str(extra.get("why") or ""),
                exit_why=str(extra.get("exit_why") or ""),
                level_id=str(extra.get("level_id") or ""),
                scaled=bool(extra.get("scaled") or False),
                stop_vol=extra.get("stop_vol"),
                spread_at_entry=extra.get("spread_at_entry"),
                slippage=extra.get("slippage"),
            )
        )
    return out


def groups(
    found: Sequence[report.Trade],
) -> tuple[report.Group, dict[str, report.Group], dict[str, report.Group]]:
    """Bucket trades the way `report.build` does, over a window it cannot take.

    Same class, same keys, same order of appearance. Pinned against `build` by
    `test_web_api.test_grouping_matches_the_report_at_the_full_window`, which
    is the only thing stopping this drifting into a second scoring rule.
    """
    by_strategy: dict[str, report.Group] = {}
    by_feed: dict[str, report.Group] = {}
    for trade in found:
        by_strategy.setdefault(trade.strategy, report.Group(trade.strategy)).trades.append(trade)
        by_feed.setdefault(trade.feed, report.Group(trade.feed)).trades.append(trade)
    return report.Group("overall", list(found)), by_strategy, by_feed


#: What an unrecorded field is called on screen. `exit_source` and `reason`
#: only started being written recently, and labelling an older trade with a
#: default would make the exit mix wrong in a way nobody could see.
UNRECORDED = "unrecorded"


def _keyed(
    found: Sequence[report.Trade],
    key: Callable[[report.Trade], str],
) -> dict[str, report.Group]:
    """Bucket by any label, with `report.Group` doing every statistic."""
    out: dict[str, report.Group] = {}
    for trade in found:
        out.setdefault(key(trade), report.Group(key(trade))).trades.append(trade)
    return out


def declines(
    path: Path | str,
    *,
    since: float | None = None,
    until: float | None = None,
) -> dict[str, int]:
    """Gate refusals by gate name.

    Delegates to `report.declines` for the whole record. A window counts the
    same `context["gate"]` key over the same entries, because `report.declines`
    takes none; `test_web_api.test_windowed_declines_match_the_report` pins the
    two together when the window is the whole record.
    """
    if since is None and until is None:
        return report.declines(path, limit=LIMIT)
    counted: dict[str, int] = defaultdict(int)
    for entry in read(path, actor="trading", kind=Kind.OBSERVATION, since=since, limit=LIMIT):
        if until is not None and entry.time > until:
            continue
        gate = str(entry.context.get("gate") or "")
        if gate:
            counted[gate] += 1
    return dict(counted)


def _se(group: report.Group) -> float | None:
    if group.count < 2:
        return None
    spread = statistics.stdev(trade.r for trade in group.trades)
    return _finite(spread / math.sqrt(group.count))


def _group_view(group: report.Group, against: float | None = None) -> GroupView:
    return GroupView(
        se_r=_se(group),
        name=group.name,
        count=group.count,
        wins=group.wins,
        win_rate=group.win_rate,
        mean_r=_finite(group.mean_r) or 0.0,
        total_r=_finite(group.total_r) or 0.0,
        profit=group.profit,
        median_seconds=group.median_seconds,
        enough=group.enough,
        verdict=group.verdict(against),
    )


def _turn_view(turn: report.TurnComparison) -> TurnView:
    return TurnView(
        scored=turn.scored,
        reached=turn.reached,
        took_r=turn.took_r,
        suggested_r=turn.suggested_r,
        gained_r=_finite(turn.gained_r),
        summary=turn.summary(),
    )


def overview(
    path: Path | str | None = None,
    *,
    mode: str = "",
    strategy: str = "",
    feed: str = "",
    since: float | None = None,
    until: float | None = None,
    days: int | None = None,
) -> Overview:
    """Score the journal over a window, and shape it for one page load."""
    where = Path(path) if path is not None else journal_path()
    found = report.trades(where, limit=LIMIT)
    modes = sorted({trade.mode for trade in found if trade.mode})
    names = sorted({trade.strategy for trade in found if trade.strategy})
    feeds = sorted({trade.feed for trade in found if trade.feed})

    if mode:
        found = [trade for trade in found if trade.mode == mode]
    if strategy:
        found = [trade for trade in found if trade.strategy == strategy]
    if feed:
        found = [trade for trade in found if trade.feed == feed]
    if since is not None:
        found = [trade for trade in found if trade.opened >= since]
    if until is not None:
        found = [trade for trade in found if trade.opened <= until]

    overall, by_strategy, by_feed = groups(found)
    places = geometry(where)
    shown = views(found, places)
    labels = {
        _key(trade.opened): str(places.get(_key(trade.opened), {}).get("rule") or "")
        for trade in found
    }
    by_rule = _keyed(found, lambda t: labels.get(_key(t.opened)) or t.strategy or UNRECORDED)
    by_exit = _keyed(found, lambda t: t.reason or UNRECORDED)
    by_source = _keyed(found, lambda t: t.exit_source or UNRECORDED)
    refused = declines(where, since=since, until=until)
    total = sum(refused.values())

    return Overview(
        window=Window(
            since=since,
            until=until,
            days=days,
            first=min((t.opened for t in found), default=None),
            last=max((t.opened for t in found), default=None),
        ),
        overall=_group_view(overall),
        by_strategy=[_group_view(g, overall.win_rate) for g in by_strategy.values()],
        by_feed=[_group_view(g, overall.win_rate) for g in by_feed.values()],
        by_rule=[_group_view(g, overall.win_rate) for g in by_rule.values()],
        by_exit=[_group_view(g, overall.win_rate) for g in by_exit.values()],
        by_exit_source=[_group_view(g, overall.win_rate) for g in by_source.values()],
        declines=[
            DeclineView(gate=gate, count=count, share=count / total if total else 0.0)
            for gate, count in sorted(refused.items(), key=lambda pair: -pair[1])
        ],
        turn_exit=_turn_view(report.compare_turn_exits(found)),
        equity=_equity(shown),
        trades=shown,
        modes=modes,
        strategies=names,
        feeds=feeds,
        enough=report.ENOUGH,
        measured=measured(sorted(by_strategy)),
        costs=costs(shown),
    )


def measured(names: Sequence[str]) -> list[Measured]:
    """Research figures for these strategies, if a file names any.

    Missing is the normal case and is reported as missing. A strategy the file
    does not mention gets a row of `None`s, so the panel can say "no measured
    figure" in the place a number would have gone.
    """
    raw = os.environ.get("TILL_MEASURED_JSON", "").strip()
    found: dict[str, Any] = {}
    source = ""
    if raw:
        path = _resolve(raw)
        if path.exists():
            try:
                loaded = json.loads(path.read_text())
            except (OSError, ValueError):
                loaded = None
            if isinstance(loaded, dict):
                found = loaded
                source = path.name

    def number(row: Any, key: str) -> float | None:
        if not isinstance(row, dict):
            return None
        value = row.get(key)
        return _finite(value) if isinstance(value, int | float) else None

    out: list[Measured] = []
    for name in names:
        row = found.get(name)
        count = number(row, "trades")
        out.append(
            Measured(
                strategy=name,
                trades=int(count) if count is not None else None,
                win_rate=number(row, "win_rate"),
                mean_r=number(row, "mean_r"),
                se_r=number(row, "se_r"),
                hold_seconds=number(row, "hold_seconds"),
                source=source,
            )
        )
    return out


def costs(shown: Sequence[TradeView]) -> list[CostView]:
    """Realised entry cost per feed, from what the decisions recorded."""
    buckets: dict[str, list[TradeView]] = defaultdict(list)
    for trade in shown:
        if trade.spread_at_entry is not None:
            buckets[trade.feed].append(trade)

    out: list[CostView] = []
    for feed, rows in sorted(buckets.items()):
        spreads = [row.spread_at_entry for row in rows if row.spread_at_entry is not None]
        slips = [row.slippage for row in rows if row.slippage is not None]
        out.append(
            CostView(
                feed=feed,
                trades=len(rows),
                median_spread=statistics.median(spreads) if spreads else None,
                mean_spread=statistics.fmean(spreads) if spreads else None,
                median_slippage=statistics.median(slips) if slips else None,
                worst_spread=max(spreads) if spreads else None,
            )
        )
    out.sort(key=lambda row: -(row.median_spread or 0.0))
    return out


def _equity(shown: Sequence[TradeView]) -> list[EquityPoint]:
    """Cumulative realised R and money, in close order.

    Ordered by close rather than by open, because a curve is what the account
    had realised at a moment and a trade contributes nothing until it closes.
    """
    ordered = sorted(shown, key=lambda t: t.closed or t.opened)
    points: list[EquityPoint] = []
    running_r = 0.0
    running_profit = 0.0
    for index, trade in enumerate(ordered, start=1):
        running_r += trade.r
        running_profit += trade.profit
        points.append(
            EquityPoint(
                index=index,
                time=trade.closed or trade.opened,
                r=trade.r,
                profit=trade.profit,
                cumulative_r=running_r,
                cumulative_profit=running_profit,
            )
        )
    return points


def levels(path: Path | str | None = None) -> Levels:
    """What each level made or lost, from `journal.ledger`."""
    where = Path(path) if path is not None else journal_path()
    if not where.exists():
        return Levels(totals={}, records=[], message=f"no journal at {where}")
    records = ledger.ledger(ledger.outcomes(where))
    if not records:
        return Levels(totals={}, records=[], message="no closed trades recorded")
    return Levels(
        totals=ledger.totals(records),
        records=[
            LevelView(
                level_id=record.level_id,
                named=record.named,
                feed=record.feed,
                interval=record.interval,
                price=record.price,
                trades=record.trades,
                wins=record.wins,
                hit_rate=record.hit_rate,
                net=record.net,
                strategies=sorted(record.strategies),
                endings=dict(record.endings),
            )
            for record in records
        ],
    )


# --------------------------------------------------------------------- bars


def _catalogue_series(root: Path) -> list[tuple[str, str, str, float | None, float | None]]:
    """(feed, interval, venue, first, last) for each bar directory under `root`.

    Coverage comes off the parquet file names, which carry the span Nautilus
    wrote, so listing what is chartable does not open a single parquet file.
    """
    folder = root / "data" / "bar"
    if not folder.is_dir():
        return []
    out: list[tuple[str, str, str, float | None, float | None]] = []
    for entry in sorted(folder.iterdir()):
        if not entry.is_dir() or "-" not in entry.name:
            continue
        instrument, _, rest = entry.name.partition("-")
        symbol, _, venue = instrument.partition(".")
        spec = rest.removesuffix("-LAST-EXTERNAL")
        interval = SPECS.get(spec)
        if not interval or not symbol:
            continue
        stamps = [t for file in entry.glob("*.parquet") for t in _span(file.stem)]
        out.append(
            (
                symbol.lower(),
                interval,
                venue,
                min(stamps, default=None),
                max(stamps, default=None),
            )
        )
    return out


def _span(stem: str) -> list[float]:
    """Unix seconds parsed out of a Nautilus parquet file name.

    `2026-06-24T17-15-00-000000000Z_2026-08-26T07-30-00-000000000Z`: date and
    time are hyphen-separated, so this reads the digits positionally rather
    than handing a malformed name to `datetime`.
    """
    found: list[float] = []
    for half in stem.split("_"):
        digits = [part for part in half.replace("T", "-").rstrip("Z").split("-") if part.isdigit()]
        if len(digits) < 6:
            continue
        year, month, day, hour, minute, second = (int(part) for part in digits[:6])
        try:
            moment = dt.datetime(year, month, day, hour, minute, second, tzinfo=dt.UTC)
        except ValueError:
            continue
        found.append(moment.timestamp())
    return found


#: Filled on first use and never invalidated - see `_price_series`.
_CACHE: dict[str, list[SeriesView]] = {}


def _price_series() -> list[SeriesView]:
    """(feed, interval, venue) in the sqlite bar store, best-covered venue first.

    Cached for the life of the process: the store is a 300MB file written by a
    collector that is retired, so the grouping is a full scan of a table that
    does not change under us.
    """
    if "series" in _CACHE:
        return _CACHE["series"]
    path = prices_path()
    if not path.exists():
        return _CACHE.setdefault("series", [])
    with contextlib.closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        rows = conn.execute(
            "SELECT feed, interval, venue, COUNT(*), MIN(ts), MAX(ts) FROM bars"
            " GROUP BY feed, interval, venue ORDER BY COUNT(*) DESC"
        ).fetchall()
    found = [
        SeriesView(
            feed=feed,
            interval=interval,
            source="prices",
            venue=venue,
            bars=count,
            first=float(first),
            last=float(last),
        )
        for feed, interval, venue, count, first, last in rows
    ]
    return _CACHE.setdefault("series", found)


def series() -> list[SeriesView]:
    """Every chartable (source, feed, interval), richest coverage first.

    One row per source and venue rather than a merged "gold at 5m", because
    the same instrument's recorded spread runs 0.17 to 3.30 bps across venues
    and a chart that does not say whose candles it is drawing is a chart about
    an unnamed venue.
    """
    out: list[SeriesView] = []
    for name, root in catalogues().items():
        for feed, interval, venue, first, last in _catalogue_series(root):
            out.append(
                SeriesView(
                    feed=feed,
                    interval=interval,
                    source=name,
                    venue=venue,
                    bars=None,
                    first=first,
                    last=last,
                )
            )
    best: dict[tuple[str, str], SeriesView] = {}
    for found in _price_series():
        best.setdefault((found.feed, found.interval), found)
    out.extend(best.values())
    out.sort(key=lambda s: (s.feed, SECONDS.get(s.interval, 0), s.source))
    return out


def _catalogue_bars(
    root: Path, feed: str, interval: str, start: float, end: float
) -> list[BarView]:
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    spec = next((k for k, v in SPECS.items() if v == interval), "")
    venue = next(
        (v for f, i, v, _, _ in _catalogue_series(root) if f == feed and i == interval),
        "",
    )
    if not spec or not venue:
        return []
    bar_type = f"{feed.upper()}.{venue}-{spec}-LAST-EXTERNAL"
    bars = ParquetDataCatalog(str(root)).bars(
        bar_types=[bar_type],
        start=int(start * NANOS),
        end=int(end * NANOS),
    )
    return [
        BarView(
            time=bar.ts_event // NANOS,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )
        for bar in bars
    ]


def _store_bars(feed: str, interval: str, venue: str, start: float, end: float) -> list[BarView]:
    path = prices_path()
    if not path.exists():
        return []
    with contextlib.closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        rows = conn.execute(
            "SELECT ts, open, high, low, close, volume FROM bars"
            " WHERE feed = ? AND interval = ? AND venue = ? AND ts >= ? AND ts <= ?"
            " ORDER BY ts",
            (feed, interval, venue, int(start), int(end)),
        ).fetchall()
    return [
        BarView(
            time=int(ts),
            open=float(o),
            high=float(h),
            low=float(low),
            close=float(c),
            volume=float(v or 0.0),
        )
        for ts, o, h, low, c, v in rows
    ]


def markers(shown: Iterable[TradeView], feed: str, interval: str) -> list[MarkerView]:
    """Entries and exits for one feed, snapped to the bar they fall in."""
    step = SECONDS.get(interval, 900)
    out: list[MarkerView] = []
    for trade in shown:
        if trade.feed != feed:
            continue
        if trade.entry_price is not None:
            out.append(
                MarkerView(
                    time=int(trade.opened // step * step),
                    price=trade.entry_price,
                    kind="entry",
                    side=trade.side,
                    strategy=trade.strategy,
                    r=trade.r,
                    label=f"{trade.side} {trade.strategy}",
                )
            )
        if trade.exit_price is not None and trade.closed is not None:
            out.append(
                MarkerView(
                    time=int(trade.closed // step * step),
                    price=trade.exit_price,
                    kind="exit",
                    side=trade.side,
                    strategy=trade.strategy,
                    r=trade.r,
                    label=f"{trade.r:+.2f}R {trade.exit_kind or trade.reason}".strip(),
                )
            )
    out.sort(key=lambda m: m.time)
    return out


def chart(
    feed: str,
    interval: str,
    *,
    source: str = "",
    venue: str = "",
    start: float | None = None,
    end: float | None = None,
    shown: Sequence[TradeView] = (),
    path: Path | str | None = None,
) -> Chart:
    """Candles for one feed, with the markers for the trades taken on it.

    With no window asked for, the window is **where the trades are**, padded
    by sixty bars either side, because a chart of the most recent candles on a
    feed whose trades are three months old shows no trades at all.

    Markers outside the candles are dropped and counted in `message` rather
    than left in. The catalogue's coverage and the journal's are different
    spans - us100 bars stop eight days before the us100 trades - and a marker
    the chart cannot place is drawn against whichever candle is nearest, which
    reads as a trade that did not happen there.
    """
    choices = [s for s in series() if s.feed == feed and s.interval == interval]
    if source:
        choices = [s for s in choices if s.source == source]
    if venue:
        choices = [s for s in choices if s.venue == venue]
    if not choices:
        return Chart(
            feed=feed,
            interval=interval,
            source=source,
            venue=venue,
            bars=[],
            markers=[],
            message=f"no bars for {feed} at {interval} in any catalogue on this machine",
        )

    chosen = max(choices, key=lambda s: s.last or 0.0)
    step = SECONDS.get(interval, 900)
    found = markers(shown, feed, interval)
    if start is None and end is None and found:
        start = min(mark.time for mark in found) - 60 * step
        end = max(mark.time for mark in found) + 60 * step
    first = start if start is not None else (chosen.last or 0.0) - 400 * step
    final = end if end is not None else (chosen.last or 0.0) + step

    if chosen.source == "prices":
        bars = _store_bars(chosen.feed, chosen.interval, chosen.venue, first, final)
    else:
        root = catalogues()[chosen.source]
        bars = _catalogue_bars(root, chosen.feed, chosen.interval, first, final)

    note = ""
    if not bars:
        note = f"{chosen.source} holds {feed} at {interval}, but nothing in this window"
        found = []
    elif found:
        inside = [mark for mark in found if bars[0].time <= mark.time <= bars[-1].time]
        if len(inside) < len(found):
            note = (
                f"{len(found) - len(inside)} of {len(found)} markers fall outside the candles "
                f"{chosen.source} holds for {feed}"
            )
        found = inside

    declined = _refusal_marks(path, feed, step, bars)
    return Chart(
        feed=chosen.feed,
        interval=chosen.interval,
        source=chosen.source,
        venue=chosen.venue,
        bars=bars,
        markers=found,
        refusals=declined,
        levels=_level_lines(shown, declined, feed, bars),
        message=note,
    )


def _refusal_marks(
    path: Path | str | None,
    feed: str,
    step: int,
    bars: Sequence[BarView],
) -> list[RefusalMark]:
    """Where a gate said no on this feed, snapped to the bar and clipped to it."""
    if not bars:
        return []
    where = Path(path) if path is not None else journal_path()
    if not where.exists():
        return []
    first, last = bars[0].time, bars[-1].time
    out: list[RefusalMark] = []
    for entry in _refusals(where, since=first):
        if str(entry.context.get("feed") or "") != feed:
            continue
        when = int(entry.time // step * step)
        if when < first or when > last:
            continue
        out.append(
            RefusalMark(
                time=when,
                price=_price(entry.context, "entry") or _price(entry.context, "level"),
                level=_price(entry.context, "level"),
                gate=str(entry.context["gate"]),
                strategy=str(entry.context.get("strategy") or ""),
                side=str(entry.context.get("side") or ""),
                feed=feed,
                why=entry.rationale,
            )
        )
    out.sort(key=lambda mark: mark.time)
    return out


def _level_lines(
    shown: Sequence[TradeView],
    declined: Sequence[RefusalMark],
    feed: str,
    bars: Sequence[BarView],
) -> list[LevelLine]:
    """Levels this feed was traded or refused at, inside the candles' range.

    Rounded to six significant figures before grouping, which is a display
    tolerance and not a claim that two prices are one level: the Kalman filter
    moves a level whenever it learns something, so grouping by price is exactly
    the mistake `journal/ledger.py` exists to avoid. Nothing is added up here -
    these are lines to look at, and the counts say how many records landed on
    each.
    """
    if not bars:
        return []
    low = min(bar.low for bar in bars)
    high = max(bar.high for bar in bars)
    traded: dict[float, int] = defaultdict(int)
    refused: dict[float, int] = defaultdict(int)

    for trade in shown:
        if trade.feed == feed and trade.level_price is not None:
            traded[float(f"{trade.level_price:.6g}")] += 1
    for mark in declined:
        if mark.level is not None:
            refused[float(f"{mark.level:.6g}")] += 1

    prices = sorted({*traded, *refused})
    return [
        LevelLine(
            price=price,
            label=f"{price:.6g}",
            traded=traded.get(price, 0),
            refused=refused.get(price, 0),
        )
        for price in prices
        if low <= price <= high
    ]


# ----------------------------------------------------------------- activity


def _refusals(path: Path | str, *, since: float | None = None) -> list[Entry]:
    """Observations carrying a gate. The only record of a trade not taken."""
    found = read(path, actor="trading", kind=Kind.OBSERVATION, since=since, limit=LIMIT)
    return [entry for entry in found if entry.context.get("gate")]


def activity(path: Path | str | None = None, *, hours: float = 6.0) -> Activity:
    """What each strategy has taken and been refused over a recent window.

    Reads the journal and nothing else. The broker knows what filled; only
    this knows what was wanted and declined, and by which gate - which is the
    question "why did nothing trade" actually asks.
    """
    where = Path(path) if path is not None else journal_path()
    now = time.time()
    if not where.exists():
        return Activity(
            hours=hours,
            now=now,
            age=None,
            taken=0,
            refused=0,
            strategies=[],
            gates=[],
            recent=[],
        )

    since = now - hours * 3600
    declined = _refusals(where, since=since)
    decisions = read(where, actor="trading", kind=Kind.DECISION, since=since, limit=LIMIT)
    outcomes = read(where, actor="trading", kind=Kind.OUTCOME, since=since, limit=LIMIT)

    newest = max(
        (entry.time for entry in (*declined, *decisions, *outcomes)),
        default=None,
    )
    # Age is measured against the newest entry in the whole journal, not the
    # newest inside the window: an empty window with a fresh journal and an
    # empty window with a dead one look identical otherwise.
    if newest is None:
        latest = read(where, actor="trading", limit=1)
        newest = latest[0].time if latest else None

    taken: dict[str, int] = defaultdict(int)
    refused: dict[str, int] = defaultdict(int)
    feeds: dict[str, set[str]] = defaultdict(set)
    gates: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    seen: dict[str, float] = {}
    pooled: dict[str, int] = defaultdict(int)

    def note(entry: Entry, name: str) -> None:
        seen[name] = max(seen.get(name, 0.0), entry.time)
        feed = str(entry.context.get("feed") or "")
        if feed:
            feeds[name].add(feed)

    for entry in decisions:
        name = str(entry.context.get("strategy") or "unknown")
        taken[name] += 1
        note(entry, name)
    for entry in declined:
        name = str(entry.context.get("strategy") or "unknown")
        gate = str(entry.context["gate"])
        refused[name] += 1
        gates[name][gate] += 1
        pooled[gate] += 1
        note(entry, name)

    names = sorted(set(taken) | set(refused), key=lambda n: -(taken[n] + refused[n]))
    total_refused = sum(pooled.values())
    return Activity(
        hours=hours,
        now=now,
        age=None if newest is None else max(0.0, now - newest),
        taken=sum(taken.values()),
        refused=total_refused,
        strategies=[
            Pulse(
                strategy=name,
                taken=taken[name],
                refused=refused[name],
                last_seen=seen.get(name),
                feeds=sorted(feeds[name]),
                gates=[
                    DeclineView(gate=gate, count=count, share=count / refused[name])
                    for gate, count in sorted(gates[name].items(), key=lambda pair: -pair[1])
                ],
            )
            for name in names
        ],
        gates=[
            DeclineView(
                gate=gate,
                count=count,
                share=count / total_refused if total_refused else 0.0,
            )
            for gate, count in sorted(pooled.items(), key=lambda pair: -pair[1])
        ],
        recent=_recent(decisions, outcomes, declined),
    )


def _recent(
    decisions: Sequence[Entry],
    outcomes: Sequence[Entry],
    declined: Sequence[Entry],
    *,
    limit: int = 120,
) -> list[Event]:
    """The newest entries of all three kinds, interleaved, newest first."""
    rows = [
        Event(
            time=entry.time,
            kind=str(entry.kind),
            strategy=str(entry.context.get("strategy") or ""),
            feed=str(entry.context.get("feed") or ""),
            gate=str(entry.context.get("gate") or ""),
            title=entry.title,
            why=entry.rationale,
        )
        for entry in (*decisions, *outcomes, *declined)
    ]
    rows.sort(key=lambda event: -event.time)
    return rows[:limit]


# ------------------------------------------------------------------- health


def _trading_entries(db: Path) -> int:
    """How many entries the trading actor has written, off the actor index.

    `entries_actor` is `(actor, time DESC)`, so this is a range scan over one
    actor's rows and never a table lookup: about a second on a 3.87GB journal
    against minutes for the `GROUP BY` it replaces in `health`.
    """
    try:
        with read_only(db) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE actor = ?", ("trading",)
            ).fetchone()
    except (FileNotFoundError, sqlite3.Error):
        return 0
    return int(row[0]) if row else 0


def health() -> Health:
    """Which of the four sources this machine has, and what the journal holds."""
    db = journal_path()
    sources = [
        SourceState(
            name="journal",
            kind="sqlite",
            path=str(db),
            present=db.exists(),
            detail="decisions, outcomes and gate refusals" if db.exists() else "missing",
        ),
        SourceState(
            name="prices",
            kind="sqlite",
            path=str(prices_path()),
            present=prices_path().exists(),
            detail="recorded bars, many venues per feed",
        ),
    ]
    for name, root in catalogues().items():
        found = _catalogue_series(root)
        sources.append(
            SourceState(
                name=name,
                kind="parquet",
                path=str(root),
                present=bool(found),
                detail=", ".join(sorted({f"{f} {i}" for f, i, _, _, _ in found})) or "no bar data",
            )
        )

    if not db.exists():
        return Health(
            sources=sources,
            message=f"No journal at {db}. Set TILL_JOURNAL_DB to the desk's journal.",
        )

    # **The count comes off an index. The breakdown is only for the empty
    # case, because it reads the whole file.**
    #
    # `summary` is `GROUP BY actor, kind` with no window, and on the live
    # journal sqlite plans it as `SCAN entries USING INDEX entries_actor` plus
    # a temp B-tree - 945,007 pages, 3.87GB, every page of it. This endpoint is
    # what the container healthcheck probes **every 60 seconds**, so that scan
    # ran on a loop beside the desk, on the same disk the desk writes to, and
    # `tis-research-jobs-starve-the-service` is a measured outage from exactly
    # that. The probe timed out at 15s each time and the container was marked
    # unhealthy while the query it had abandoned kept reading.
    #
    # The one thing the page needs from it is whether there are trading
    # entries at all, and `entries_actor` answers that in about a second
    # without touching the table. The full breakdown exists to diagnose a
    # journal pointed at the wrong file - which is precisely the case where
    # `trading` is zero - so it is read **only then**, and on a journal that
    # has trades in it the scan never happens.
    trading = _trading_entries(db)
    entries = summary(db) if not trading else []
    note = ""
    if not trading:
        actors = ", ".join(sorted({str(row["actor"]) for row in entries})) or "nothing"
        note = (
            f"This journal holds entries from {actors} and none from trading, "
            "so there are no trades to score. Set TILL_JOURNAL_DB to the desk's journal."
        )
    return Health(sources=sources, entries=entries, trades=trading, message=note)
