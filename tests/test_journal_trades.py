"""What the desk writes, read back by the things that read it.

**The third time this shape has been found here, and the most expensive.**
`desk._journal` records that `JournalActor` once "subscribed to a topic with no
producer"; `exits._announce` records that `alerts` "had one publisher and it was
not a trade". Both are the same fault: a publisher and a subscriber that cannot
see each other, and from either side the silence looks like a quiet market.

This is that fault between the desk and `strategies/report.py`. The legacy
`strategies/service.py` wrote two kinds of entry - an `OBSERVATION` per refused
gate and an `OUTCOME` per closed trade, both under `actor="trading"` - and it
was retired on 2026-10-31 with the rest of the legacy desk. The Nautilus desk
never took the job on. So `report.trades()` reads `actor="trading"` and
`kind="outcome"`, finds nothing, and returns an empty list; `report.declines()`
returns an empty dict; and `journal.ledger.outcomes()`, which adds closed trades
up against the level that produced them, yields nothing at all.

Every one of those is unit-tested against entries the test itself wrote, which
is why none of them failed. So these tests are deliberately built the other way
round: a real engine opens and closes a real position, the entries the desk
publishes are captured off the bus and written to a journal **unedited**, and
the readers are asked what they see. Nothing here hand-writes an `Entry`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig, BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType, QuoteTick
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from till_infinity.journal import Entry, Journal, Kind
from till_infinity.strategies.entries import EdgeEntryConfig
from till_infinity.strategies.surprise import SurpriseEdge
from till_infinity.utils.topics import JOURNAL, PROPOSALS

VENUE = Venue("SIM")
EURUSD = TestInstrumentProvider.default_fx_ccy("EUR/USD", VENUE)
BAR_TYPE = BarType.from_str(f"{EURUSD.id}-1-HOUR-LAST-EXTERNAL")
SECOND = 1_000_000_000
WARM = 3


# ------------------------------------------------------------------ the harness


class PitchConfig(ActorConfig, frozen=True):
    instrument_id: InstrumentId
    surprise: float = 4.2
    direction: int = 1
    after: int = WARM


class Pitcher(Actor):
    """One statespace proposal on the real topic, through the real bus."""

    def __init__(self, config: PitchConfig) -> None:
        super().__init__(config)
        self._seen = 0

    def on_start(self) -> None:
        self.subscribe_quote_ticks(self.config.instrument_id)

    def on_quote_tick(self, tick: QuoteTick) -> None:
        self._seen += 1
        if self._seen != self.config.after:
            return
        self.msgbus.publish(
            PROPOSALS,
            {
                "feed": "eurusd",
                "shape": "statespace",
                "interval": "5m",
                "direction": self.config.direction,
                "features": {
                    "surprise": self.config.surprise,
                    "vol_bps": 10.0,
                    "stop_vol": 2.0,
                    "target_r": 2.0,
                },
            },
        )


class ScribeConfig(ActorConfig, frozen=True):
    pass


class Scribe(Actor):
    """Everything published on the journal topic, kept in order.

    `JournalActor` itself is not used: it buffers on a timer and writes on an
    executor, and a test that waited on both would be asserting the actor's
    scheduling rather than the desk's record. What is under test is **what the
    desk publishes**, so this keeps the payloads and the writing is done below.
    """

    def __init__(self, config: ScribeConfig) -> None:
        super().__init__(config)
        self.seen: list[dict[str, Any]] = []

    def on_start(self) -> None:
        self.msgbus.subscribe(JOURNAL, self.seen.append)


def quotes(count: int = 20, step: float = 1e-05) -> list[QuoteTick]:
    rows = []
    mid = 1.10000
    for i in range(count):
        mid += step
        rows.append(
            QuoteTick(
                instrument_id=EURUSD.id,
                bid_price=Price(mid - 2.5e-05, 5),
                ask_price=Price(mid + 2.5e-05, 5),
                bid_size=Quantity(1_000_000, 0),
                ask_size=Quantity(1_000_000, 0),
                ts_event=i * SECOND,
                ts_init=i * SECOND,
            )
        )
    return rows


def desk(feed=None) -> tuple[SurpriseEdge, Scribe]:
    """One backtest that opens a position, with the journal topic recorded."""
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="TESTER-001",
            logging=LoggingConfig(bypass_logging=True),
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(100_000.0, USD)],
    )
    engine.add_instrument(EURUSD)
    engine.add_data(feed if feed is not None else quotes())
    strategy = SurpriseEdge(EdgeEntryConfig(instrument_id=EURUSD.id, bar_type=BAR_TYPE))
    engine.add_strategy(strategy)
    scribe = Scribe(ScribeConfig())
    engine.add_actor(scribe)
    engine.add_actor(Pitcher(PitchConfig(instrument_id=EURUSD.id)))
    engine.run()
    return strategy, scribe


def close(strategy: SurpriseEdge, position, pnl: str = "41.00", seconds: float = 900.0) -> None:
    """The `PositionClosed` event, in the shape Nautilus hands the strategy."""
    strategy.on_position_closed(
        type(
            "Closed",
            (),
            {
                "position_id": position.id,
                "instrument_id": position.instrument_id,
                "realized_pnl": pnl,
                "duration_ns": int(seconds * 1e9),
            },
        )()
    )


def written(scribe: Scribe, path) -> Journal:
    """Every captured payload, into a journal, **unedited**."""
    journal = Journal(path)
    journal.connect()
    journal.append([Entry.from_message(p) for p in scribe.seen if Entry.from_message(p)])
    return journal


def kinds(scribe: Scribe, kind: Kind) -> list[dict[str, Any]]:
    return [p for p in scribe.seen if str(p.get("kind")) == str(kind)]


# ------------------------------------------------- the decision a trade is on


def test_opening_a_position_records_the_decision_it_was_opened_on():
    """**There was no record that the desk had ever opened anything.**

    `report.trades()` pairs an outcome to its parent "because the outcome
    carries what happened and the decision carries what was intended - the
    strategy that opened it, and the risk it was sized for, which is the
    denominator of every number worth reporting". That parent was not being
    written. The only `DECISION` the live desk published was a *refusal*.
    """
    strategy, scribe = desk()
    assert strategy.cache.positions_open(strategy_id=strategy.id), "no position to record"

    found = kinds(scribe, Kind.DECISION)

    assert len(found) == 1, f"the opening decision was not recorded: {scribe.seen}"
    entry = found[0]
    assert entry["actor"] == "trading", "report.trades reads actor='trading' and nothing else"
    context = entry["context"]
    assert context["feed"] == "eurusd"
    assert context["side"] == "long"
    assert context["strategy"] == str(strategy.id)
    assert context["risk_money"] > 0.0, "the denominator of every R in the report"
    assert context["mode"] in ("live", "paper")


def test_closing_a_position_records_an_outcome_pointing_at_that_decision():
    """An outcome with no parent is dropped by the actor, by design.

    `JournalActor.on_entry` refuses one: "it could never be paired with the
    decision it judges, so it is not a training example - just noise". So the
    link is the whole point of the pair, and asserting the outcome exists
    without asserting its parent would pass over an entry that never lands.
    """
    strategy, scribe = desk()
    position = strategy.cache.positions_open(strategy_id=strategy.id)[0]
    opened = kinds(scribe, Kind.DECISION)[0]

    close(strategy, position, pnl="41.00", seconds=900.0)

    found = kinds(scribe, Kind.OUTCOME)
    assert len(found) == 1, f"the close was not recorded: {scribe.seen}"
    entry = found[0]
    assert entry["parent"] == opened["id"], "the outcome names a decision that is not the opening"
    assert entry["actor"] == "trading"
    assert entry["context"]["profit"] == 41.0
    assert entry["context"]["seconds"] == 900.0
    assert entry["context"]["feed"] == "eurusd"


def test_an_outcome_is_not_written_for_a_position_this_process_did_not_open():
    """The control, and the reason it is not just tidiness.

    A position adopted on start-up has no decision here to point at, so an
    outcome for it would be refused by the actor and counted as dropped - a
    number that then reads as a journal fault rather than as a restart.
    """
    strategy, scribe = desk()
    scribe.seen.clear()

    close(strategy, type("Gone", (), {"id": "SIM-UNKNOWN", "instrument_id": EURUSD.id})())

    assert kinds(scribe, Kind.OUTCOME) == [], "an unpairable outcome was published anyway"


# ------------------------------------------------------- read back by the report


def test_a_closed_trade_reaches_the_report(tmp_path):
    """**The whole point, and the thing that was returning an empty list.**

    Nothing here writes an `Entry`: the engine runs, the desk publishes, the
    payloads are written unedited, and `report.build` is asked what it sees.
    That is the assertion no existing test made - both halves were tested
    against entries their own test had written, and both passed while the
    chain between them was cut.
    """
    from till_infinity.strategies import report

    strategy, scribe = desk()
    position = strategy.cache.positions_open(strategy_id=strategy.id)[0]
    close(strategy, position, pnl="41.00", seconds=900.0)
    path = tmp_path / "journal.db"
    written(scribe, path)

    trades = report.trades(path)

    assert len(trades) == 1, "the report saw no trade at all"
    trade = trades[0]
    assert trade.profit == 41.0
    assert trade.seconds == 900.0
    assert trade.feed == "eurusd"
    assert trade.side == "long"
    assert trade.risk_money > 0.0
    assert trade.strategy == str(strategy.id)

    built = report.build(path)
    assert built.overall.count == 1, f"a trade that scores to nothing: {built}"
    assert built.by_strategy[str(strategy.id)].count == 1
    assert built.by_feed["eurusd"].count == 1


def test_a_refusal_is_an_observation_so_the_decline_tally_counts_it(tmp_path):
    """`declines()` reads `OBSERVATION`, and the desk wrote `DECISION`.

    `Kind.OBSERVATION` is documented as "we noticed something and did not act",
    which is what a refused gate is; a `DECISION` is the thing the desk chose to
    do. The gate tally reads the first and the desk published the second, so
    every refusal the desk recorded was invisible to the only thing that counts
    them - and `trades()` would have mixed them into its pool of parents.
    """
    from till_infinity.domain.models import Refusal
    from till_infinity.strategies import report

    strategy, scribe = desk()
    scribe.seen.clear()
    strategy._journal(Refusal(gate="spread", detail="30bps against 0.3", feed="eurusd"), {})

    found = kinds(scribe, Kind.OBSERVATION)
    assert len(found) == 1, f"the refusal was not recorded as an observation: {scribe.seen}"
    assert found[0]["actor"] == "trading"
    assert found[0]["context"]["strategy"] == str(strategy.id)

    path = tmp_path / "journal.db"
    written(scribe, path)
    assert report.declines(path) == {"spread": 1}


def test_the_level_ledger_adds_a_closed_trade_up_against_its_level(tmp_path):
    """`journal.ledger` is the other reader, and it was yielding nothing.

    It exists so a closed trade can be added up against the level that produced
    it - `Intent.level_id` is carried for exactly this - and its query is
    `actor = 'trading' AND kind = 'outcome'`, which had no rows at all.
    """
    from till_infinity.journal import ledger as book

    strategy, scribe = desk()
    position = strategy.cache.positions_open(strategy_id=strategy.id)[0]
    close(strategy, position, pnl="41.00")
    path = tmp_path / "journal.db"
    written(scribe, path)

    records = book.ledger(book.outcomes(path))

    assert len(records) == 1, "the ledger saw no closed trade"
    assert records[0].net == 41.0
    assert records[0].trades == 1
    assert str(strategy.id) in records[0].strategies


def test_the_writer_cannot_take_the_exit_path_down(monkeypatch):
    """The journal is not allowed to be the thing that breaks a close.

    This runs inside a Nautilus event handler, and the bus calls handlers
    inline, so a raise here is a raise inside the strategy's own
    `on_position_closed` - which is the one place the desk must not fail.
    """
    from till_infinity.strategies import exits

    strategy, scribe = desk()
    position = strategy.cache.positions_open(strategy_id=strategy.id)[0]

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("the journal is down")

    scribe.seen.clear()
    monkeypatch.setattr(exits, "publish", boom)
    close(strategy, position)  # must not raise

    assert strategy.cache.position(position.id) is not None
    assert kinds(scribe, Kind.OUTCOME) == [], "the raise was swallowed and the entry still went"


def test_the_journal_is_written_on_a_real_run_without_a_hand_written_entry(tmp_path):
    """The control for every test above: the capture has to be the desk's own.

    If `Scribe` were picking up something a test published, each assertion here
    would hold over an entry nothing in production writes - which is precisely
    the failure these tests exist to catch.
    """
    strategy, scribe = desk()

    assert scribe.seen, "nothing was published on the journal topic at all"
    assert all(p.get("actor") == "trading" for p in scribe.seen), (
        f"an entry the readers cannot see: {[p.get('actor') for p in scribe.seen]}"
    )
    assert all(p["context"].get("strategy") == str(strategy.id) for p in scribe.seen), (
        "the actor moved to a constant and took the strategy's name with it"
    )
    assert asyncio.run(_rows(written(scribe, tmp_path / "j.db"))) >= 1


async def _rows(journal: Journal) -> int:
    from till_infinity.journal import read

    return len(read(journal.path, limit=50))
