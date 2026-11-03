"""A detector's parameters may differ by side, and by default they do not.

Long and short are not the same trade, and this desk already has the
measurement that makes that concrete rather than plausible:
`risk/scaling.overshoot_for` prefers `boom_500_index.sell` over
`boom_500_index`, because on a jump instrument a stop on the spike side can
only be gapped over. Until now that asymmetry stopped at sizing - the entry
leaves are one per side and `SideProfile` holds a per-side geometry, but every
*detector* read one parameter for both sides.

`momentum.Cusum` is the one where that was arithmetic rather than style: one
`threshold` governed both accumulators, so a filter could not be made to speak
earlier on the side that gaps and later on the side that does not.

## The shape of the addition, and why it is this shape

A second parameter, declared through the syntax that already existed.
`cusum:typical` and `rsi:7` are one syntax on purpose, "because a strategy
using both should not have to say which is which", and both reach
`build_detector` as the whole tail after the colon - so the grammar grew there
and neither `Desk._register` nor `StatespaceActor._register` changed:

    cusum:typical,threshold.buy=1.2,threshold.sell=2.4

`.buy` and `.sell` are the spelling `scaling.overshoot_for` and
`strategies/exits.geometry_for` already read, because two spellings for one
idea inside one configuration file is the second syntax this one exists not to
be.

## Why it is off by default, which is the expensive part

`Cusum.restart` zeroes **both** accumulators, so raising one side's threshold
changes which events the other side fires: a sweep over k thresholds per side
is k**2 cells, not 2k. At k = 6 that is 30 new trials where a month of data at
a target Sharpe of 1.5 supports about one.

So `threshold_up` and `threshold_down` are zero, meaning "use `threshold`", and
`research/ideas/sided_thresholds.py` measured whether they earn more than that:
on 5,135 recorded 15m eurusd bars the best asymmetric pair beat the best
symmetric threshold by +0.0960 volatility units of forward move, against a
block-shuffled twin that beat it by +0.0731 on average and exceeded it in 9 of
40 draws - p = 0.244, which is the selection a 36-cell grid hands out for free.
The same harness finds a *planted* one-sided effect of 0.25v at +0.1050 and is
blind to one of 0.10v, so the null has a resolution attached to it.

An asymmetric default would therefore be eight confounded parameters wearing
one name.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, OrderStatus
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from till_infinity.domain.models import Intent, Refusal, Side
from till_infinity.indicators import Cusum, Reading, build_detector, declaration
from till_infinity.statespace.actor import StatespaceActor, StatespaceConfig
from till_infinity.strategies.entries import EdgeEntry, EdgeEntryConfig
from till_infinity.strategies.exits import ManagedExit
from till_infinity.strategies.leaves import StatespaceLong, StatespaceShort

VENUE = Venue("SIM")
EURUSD = TestInstrumentProvider.default_fx_ccy("EUR/USD", VENUE)
BAR_TYPE = BarType.from_str(f"{EURUSD.id}-15-MINUTE-LAST-EXTERNAL")
QUARTER = 15 * 60 * 1_000_000_000

#: A declaration with the two sides apart, and the same one with them together.
APART = "cusum:typical,threshold.buy=0.5,threshold.sell=1.8"
TOGETHER = "cusum:typical,threshold.buy=1.0,threshold.sell=1.0"


# ----------------------------------------------------------- the declaration


def test_the_declarations_that_existed_parse_as_they_did():
    """The syntax is extended, not forked. A tail with no `=` in it is the
    source it always was, and a config that never heard of a side is read by
    the same function as one that has."""
    assert declaration("typical") == ("typical", {})
    assert declaration("7") == ("7", {})
    assert declaration(None) == (None, {})
    assert declaration(Reading.CLOSE) == ("close", {})


def test_a_side_keyed_parameter_reaches_the_detector():
    """Both halves: the grammar resolves `.buy` to the field the detector holds
    the pair under, and the detector reports the pair it was given."""
    assert declaration("typical,threshold.buy=1.2,threshold.sell=2.4") == (
        "typical",
        {"threshold_up": 1.2, "threshold_down": 2.4},
    )
    detector = build_detector("cusum", "typical,threshold.buy=1.2,threshold.sell=2.4")
    assert detector.thresholds == (1.2, 2.4)
    assert detector.sided


def test_the_side_words_are_the_ones_the_rest_of_the_desk_writes():
    """`scaling.overshoot_for` reads `boom_500_index.sell` and
    `exits.geometry_for` reads the same spelling, so a detector that demanded
    `.down` would make one configuration file carry two vocabularies for one
    idea - and the one a reader guesses wrong is silently ignored."""
    for word in ("buy", "long", "up"):
        assert declaration(f"typical,threshold.{word}=1.5")[1] == {"threshold_up": 1.5}
    for word in ("sell", "short", "down"):
        assert declaration(f"typical,threshold.{word}=1.5")[1] == {"threshold_down": 1.5}


def test_a_source_may_be_left_out_and_a_parameter_may_have_no_side():
    """A per-side parameter is a second parameter and nothing more, so the
    grammar does not make one a special case of the other."""
    assert declaration(",threshold.sell=2.4") == (None, {"threshold_down": 2.4})
    assert declaration("typical,unit_span=5") == ("typical", {"unit_span": 5})


def test_a_count_declared_as_one_stays_an_integer():
    """`unit_span` is a half-life in bars. A float that reads as an integer
    everywhere it is printed is a field whose type nobody can check."""
    assert isinstance(declaration("typical,unit_span=5")[1]["unit_span"], int)
    assert isinstance(declaration("typical,threshold.buy=1")[1]["threshold_up"], int)
    assert isinstance(declaration("typical,threshold.buy=1.5")[1]["threshold_up"], float)


@pytest.mark.parametrize(
    ("tail", "complaint"),
    [
        ("typical,threshold.middle=1", "not a side"),
        ("typical,threshold.buy=x", "no number in it"),
        ("typical,close", "parameter was expected"),
        ("typical,=3", "no parameter name"),
    ],
)
def test_a_declaration_that_cannot_be_read_is_refused(tail, complaint):
    """Refused at build time rather than dropped. A detector the config asked
    for and the strategy quietly did not build is a sweep reporting a null for
    a question it never asked, which is why `Desk._register` raises on an
    unknown name too."""
    with pytest.raises(ValueError, match=complaint):
        build_detector("cusum", tail)


def test_a_parameter_the_detector_holds_no_pair_for_is_refused():
    """And the message says what growing one would cost, because the reason a
    detector does not have a per-side pair is that nobody measured the two
    sides differing - not that the plumbing is missing."""
    with pytest.raises(ValueError, match="one unit_span for both sides"):
        build_detector("cusum", "typical,unit_span.buy=5")
    with pytest.raises(ValueError, match="takes no"):
        build_detector("cusum", "typical,nonsense.buy=5")


def test_one_of_nautiluss_own_indicators_cannot_be_given_sides():
    """`FRAMEWORK` is the framework's parameters, and adding a side to one
    would mean subclassing a Cython indicator to hold it. A config that tries
    should be told so rather than get a symmetric indicator back under a name
    that claims two sides."""
    with pytest.raises(ValueError, match="takes a period and nothing else"):
        build_detector("rsi", ",threshold.buy=1.0")


def test_a_negative_per_side_threshold_is_refused():
    """A negative threshold is crossed by the first observation on that side,
    so the filter fires every bar and reports a run length rather than an
    event - a plausible-looking number from a detector that has stopped being
    one."""
    with pytest.raises(ValueError, match="negative threshold"):
        Cusum(threshold_down=-1.0)


# -------------------------------------------------------------- the detector


def push_all(detector: Cusum, steps: list[float]) -> list[tuple[int, str]]:
    """Feed a path of unit steps, returning `(index, side)` per event."""
    out = []
    price = 100.0
    for i, step in enumerate(steps):
        price += step
        got = detector.push(price, 1.0, index=i)
        if got is not None:
            out.append((i, got.side))
    return out


def test_a_detector_with_no_side_declared_is_the_one_that_existed_before():
    """The default has to be bit-identical, not merely similar. A second
    parameter that moved the symmetric reading would make every number measured
    on the old detector a number about a detector that no longer exists."""
    steps = [0.4, -0.9, 1.3, 0.8, -2.6, 1.1, 1.4, -0.3, 0.9]
    assert push_all(Cusum(threshold=2.0, unit=1.0, unit_from=None), steps) == push_all(
        build_detector("cusum", "close"), steps
    )
    assert build_detector("cusum", "close").sided is False


#: A path with a run of +1.0 and then a run of -1.5, after a priming step.
#: The first push only records the starting price - there is no change yet - so
#: a path whose first element carried a move would be measuring one step fewer
#: than it reads as.
BOTH_WAYS = [0.0, 0.5, 0.5, -0.5, -0.5, -0.5]

#: A path where the up accumulator is still positive when the down side fires:
#: +2.0, then -1.2 in two steps, then four of +1.0. Only such a path shows the
#: coupling, because a negative step large enough to fire the down side also
#: drives the up accumulator down by the same amount - so up survives a down
#: event only where it had run further than the down threshold.
COUPLED = [0.0, 2.0, -0.6, -0.6, 1.0, 1.0, 1.0, 1.0]


def test_each_side_fires_at_its_own_threshold():
    """The point of the pair. One path, two detectors: only the side whose
    threshold the path actually reaches may speak, and which side that is comes
    from the declaration rather than from the data."""
    up_only = build_detector("cusum", "close,threshold.buy=0.75,threshold.sell=3.0")
    assert push_all(up_only, BOTH_WAYS) == [(2, "up")]

    down_only = build_detector("cusum", "close,threshold.buy=3.0,threshold.sell=0.75")
    assert push_all(down_only, BOTH_WAYS) == [(4, "down")]


def test_raising_one_sides_threshold_moves_the_other_sides_events():
    """Why a per-side sweep costs a grid and not two sweeps.

    `restart` zeroes both accumulators, because the statistic is progress since
    the last event - so an event on the down side wipes what the up side had
    accumulated. Silencing the down side therefore lets the up side run
    further and fire a bar earlier, which is the whole reason the two
    parameters are not separable: a sweep that treated them as independent
    would be offering k + k cells of evidence for a k * k search.
    """
    both = push_all(build_detector("cusum", "close,threshold.buy=3.5,threshold.sell=1.1"), COUPLED)
    quiet = push_all(build_detector("cusum", "close,threshold.buy=3.5,threshold.sell=9.0"), COUPLED)
    assert both == [(3, "down"), (7, "up")]
    assert quiet == [(6, "up")], "the up event moved, on an unchanged up threshold"


def test_a_reset_keeps_the_declared_pair():
    """Nautilus's `reset` means *this has never seen anything*, and it is called
    when the engine rewinds. A rewind that dropped the declared thresholds
    would restart the detector symmetric, which is a different detector
    answering under the same name."""
    detector = build_detector("cusum", "close,threshold.buy=0.5,threshold.sell=1.8")
    push_all(detector, [0.6, 0.6])
    detector.reset()
    assert detector.thresholds == (0.5, 1.8)
    assert detector.up == 0.0
    assert not detector.has_inputs


def test_a_state_written_before_the_pair_existed_restores_symmetric():
    """A saved detector predating the two fields comes back as the detector it
    was, at **its own** threshold.

    `utils/codec.py` writes a dataclass field by field, so a state written
    before the pair existed simply has two keys fewer - which is simulated here
    by dropping them. The default they fall back to is the sentinel meaning
    "use `threshold`", so the restored filter is the one that was saved. A
    default of a real number instead would restore every stored detector at
    that number under the name of the one that was running, and the aliases in
    `codec.ALIASES` exist because the quiet version of that failure "reads as a
    quiet market rather than as a failure".
    """
    from till_infinity import indicators
    from till_infinity.utils import codec

    known = codec.registry(indicators)
    written = codec.pack(Cusum(threshold=1.5, unit=1.0, unit_from=None))
    before = {k: v for k, v in written["f"].items() if not k.startswith("threshold_")}

    restored = codec.unpack({**written, "f": before}, known)
    assert restored.thresholds == (1.5, 1.5)
    assert not restored.sided

    declared = codec.unpack(
        codec.pack(Cusum(threshold_up=0.5, threshold_down=1.8, unit=1.0, unit_from=None)), known
    )
    assert declared.thresholds == (0.5, 1.8), "a declared pair has to survive a restart too"


# ------------------------------------------------------- and through a desk


class Recording(EdgeEntry):
    """`EdgeEntry` that keeps what it saw, so a run can be counted."""

    def __init__(self, config: EdgeEntryConfig) -> None:
        super().__init__(config)
        self.bars_seen = 0
        self.proposals = 0
        self.readings: list[tuple[str, str]] = []

    def on_bar(self, bar: Bar) -> None:
        self.bars_seen += 1

    def on_data(self, data: Any) -> None:
        if isinstance(data, dict):
            self.proposals += 1
        super().on_data(data)


class CusumGate:
    """A decision that reads a registered detector before accepting an intent.

    **The reason a detector is registered at all.** `DeskConfig.indicators` and
    `StatespaceConfig.indicators` both build detectors the engine then warms,
    and nothing in `till_infinity/` reads one - which is the "configured,
    correct and inert" shape `utils/effects.py` exists for. This is the
    consumer, so the run below is not a fold nobody reads.

    It takes the **side of the last event**, not the accumulator: a CUSUM
    restarts when it fires, so the strongest case it can report reads a
    pressure of exactly zero and would be indistinguishable from a flat market.
    `momentum.Ensemble._opinion` falls back the same way and says why. The
    per-side threshold therefore acts through the event stream - it decides
    when each side speaks at all.
    """

    declaration: ClassVar[str] = ""

    def decide(self, payload: dict[str, Any]) -> Intent | Refusal | None:
        verdict = super().decide(payload)  # type: ignore[misc]
        if not isinstance(verdict, Intent):
            return verdict
        events = self.detectors[self.declaration].events  # type: ignore[attr-defined]
        latest = events[-1].side if events else ""
        wanted = "up" if verdict.side is Side.BUY else "down"
        self.readings.append((verdict.side.value, latest))  # type: ignore[attr-defined]
        if latest != wanted:
            return Refusal(
                gate="cusum",
                detail=f"last event was {latest or 'none'}, wanted {wanted}",
                feed=verdict.feed,
            )
        return verdict


class TogetherLong(CusumGate, StatespaceLong, ManagedExit, Recording):
    declaration: ClassVar[str] = TOGETHER


class TogetherShort(CusumGate, StatespaceShort, ManagedExit, Recording):
    declaration: ClassVar[str] = TOGETHER


class ApartLong(CusumGate, StatespaceLong, ManagedExit, Recording):
    declaration: ClassVar[str] = APART


class ApartShort(CusumGate, StatespaceShort, ManagedExit, Recording):
    declaration: ClassVar[str] = APART


def feed(count: int = 400, seed: int = 11) -> list[Any]:
    """Bars, and one quote a nanosecond before each bar's close.

    **Generated, and the shape of the generator is the point rather than its
    numbers**: this holds the wiring, and the measurement that asked whether a
    per-side threshold pays ran on recorded bars in
    `research/ideas/sided_thresholds.py`.

    The quote comes first because the desk decides inside the handler the bar
    triggers, and `_undealable` refuses on a missing quote - a run whose result
    depended on which of two equal timestamps the engine sorted first would not
    be a measurement of anything. The epoch is a real one because
    `Engine.observe_bar` reads a falsy `time` as the wall clock, and a series
    starting at zero therefore folds one bar and refuses every bar after it.
    """
    import math
    import random

    rng = random.Random(seed)
    base, price = 1_780_000_000, 1.1000
    out: list[Any] = []
    for i in range(count):
        close = price * math.exp(rng.gauss(0.0, 0.0004))
        high = max(price, close) * (1.0 + abs(rng.gauss(0.0, 0.0002)))
        low = min(price, close) * (1.0 - abs(rng.gauss(0.0, 0.0002)))
        closed_at = (base + (i + 1) * 900) * 1_000_000_000
        out.append(
            QuoteTick(
                instrument_id=EURUSD.id,
                bid_price=Price(close - 0.00001, 5),
                ask_price=Price(close + 0.00001, 5),
                bid_size=Quantity(1_000_000, 0),
                ask_size=Quantity(1_000_000, 0),
                ts_event=closed_at - 1,
                ts_init=closed_at - 1,
            )
        )
        out.append(
            Bar(
                BAR_TYPE,
                Price(price, 5),
                Price(high, 5),
                Price(low, 5),
                Price(close, 5),
                Quantity(1000, 0),
                ts_event=closed_at,
                ts_init=closed_at,
            )
        )
        price = close
    return out


def run(long_cls: type, short_cls: type, tmp_path) -> tuple[Any, list[Any]]:
    """One backtest: the real statespace actor, two side leaves, one venue.

    The state directory is this test's own, for two reasons that both bite.
    `Engine.restore` reads the last folded bar time out of it and `observe_bar`
    refuses a bar that is not strictly after it, so a second run over one
    series folds nothing - which looks exactly like a quiet market. And a run
    that wrote into `.data/statespace` would leave the box's own progress file
    holding a backtest's timestamps.
    """
    import os

    os.environ["STATESPACE_INTERVALS"] = "15m"
    os.environ["STATESPACE_STATE_DIR"] = str(tmp_path)

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="TESTER-001", logging=LoggingConfig(bypass_logging=True)
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(100_000, USD)],
    )
    engine.add_instrument(EURUSD)
    engine.add_data(feed())
    # **The actor gets the same declaration the desks do**, and not a symmetric
    # one. `StatespaceActor._register` is a second registrar - it checks the
    # bare name against `BAR_DETECTORS` itself before handing `build_detector`
    # the whole tail - so a grammar that reached only `Desk._register` would
    # work on a strategy and raise on an actor. Its copy is read by nothing,
    # which is what `StatespaceConfig.indicators` being empty by default is
    # for; it is here to be the thing that proves the second registrar, rather
    # than a fold nobody consults.
    actor = StatespaceActor(
        StatespaceConfig(
            bar_types=(str(BAR_TYPE),),
            feeds={"EUR/USD": "eurusd"},
            indicators=(long_cls.declaration,),
        )
    )
    engine.add_actor(actor)
    desks = []
    for tag, cls in enumerate((long_cls, short_cls)):
        desk = cls(
            EdgeEntryConfig(
                instrument_id=EURUSD.id,
                bar_type=BAR_TYPE,
                indicators=(cls.declaration,),
                order_id_tag=f"{tag:03d}",
            )
        )
        engine.add_strategy(desk)
        desks.append(desk)
    engine.run()
    return actor, desks


def test_a_registered_detector_reaches_a_decision_and_a_detector_gated_trade(tmp_path):
    """The chain this file is for, end to end and nothing driven by hand.

    A quote and bar feed into a `BacktestEngine`, the real `StatespaceActor`
    folding them and publishing proposals, two real side leaves consuming them,
    a CUSUM registered through the config and **read** by the decision, and a
    venue at the far end.

    The assertions are the zeros as much as the counts. A registered detector
    that is never read is the failure mode the registration itself invites, and
    a run reporting a result computed from no trades is the one this desk has
    on record more than any other - so both the readings and the orders are
    asserted non-empty, and the bars the actor registered its own detector on
    are asserted to have arrived.
    """
    actor, desks = run(TogetherLong, TogetherShort, tmp_path)

    folded = list(actor.detectors.values())
    assert len(folded) == 1, "the actor's own registrar built nothing"
    assert folded[0].thresholds == (1.0, 1.0), "the declaration reached the second registrar"
    assert sum(d.bars_seen for d in desks) == 800, "400 bars to each of the two desks"
    assert all(d.proposals > 0 for d in desks), "the producer published nothing"
    assert all(len(d.detectors) == 1 for d in desks)
    assert sum(len(d.readings) for d in desks) > 0, "a detector registered and read by nothing"

    taken = sum(d.taken for d in desks)
    orders = [o for d in desks for o in d.cache.orders(strategy_id=d.id)]
    assert taken > 0, "every proposal was refused, so nothing reached the venue"
    assert len(orders) == 3 * taken, "a bracket is the entry and its two exits"
    entries = [o for o in orders if o.order_type.name == "MARKET"]
    assert all(o.status == OrderStatus.FILLED for o in entries)
    assert {o.side for o in entries} <= {OrderSide.BUY, OrderSide.SELL}
    assert any("cusum" in gate for d in desks for gate in d.passed_over), (
        "the detector gate never fired, so this run would pass with it removed"
    )


def test_the_per_side_threshold_changes_which_side_is_refused(tmp_path):
    """The control for the test above, and the assertion that the declaration
    is not decoration.

    Same feed, same decisions, same engine; one arm with the thresholds
    together and one with them apart. The proposals must be identical - they
    come from the actor, which neither arm touches - and the detector gate's
    tally must not be, or the per-side parameter reached the detector and
    changed nothing a decision could see.
    """
    _, together = run(TogetherLong, TogetherShort, tmp_path / "together")
    _, apart = run(ApartLong, ApartShort, tmp_path / "apart")

    assert [d.proposals for d in together] == [d.proposals for d in apart]
    assert [d.detectors[TOGETHER].thresholds for d in together] == [(1.0, 1.0), (1.0, 1.0)]
    assert [d.detectors[APART].thresholds for d in apart] == [(0.5, 1.8), (0.5, 1.8)]

    def events(desks):
        return sorted({e.side for d in desks for e in d.detectors[d.declaration].events})

    assert events(together) == ["down", "up"]
    assert events(apart) == ["down", "up"], "a side silenced entirely is not the test"

    def gated(desks):
        return sum(count for d in desks for gate, count in d.passed_over.items() if "cusum" in gate)

    assert gated(apart) != gated(together), "the declared pair changed no decision"
