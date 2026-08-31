"""Monetary policy: as features on a signal, and as a model of its own.

The failure this file is written against is not a wrong number. It is a number
that is computed correctly and read by nothing - which is what FRED was for
2,174 rows, and what several settings in this repository have been. So the
tests that matter here are the **handover** tests: is the topic subscribed to,
does the reading reach a signal, does a float dictionary survive the contract
`Signal` enforces on it.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from till_infinity.bus import MACRO, Bus, Message
from till_infinity.structures import macro as mc
from till_infinity.structures.config import Settings
from till_infinity.structures.models import Shape, Signal
from till_infinity.structures.service import TOPICS, Watcher

DAY = 86_400.0


def series(macro: mc.Macro, name: str, points: list[tuple[float, float]]) -> None:
    """Feed one series, times given as days before now."""
    now = time.time()
    for ago, value in points:
        macro.observe(name, now - ago * DAY, value)


def steady(
    name: str, start: float, drift: float = 0.0, days: int = 400
) -> list[tuple[float, float]]:
    """A monthly series moving `drift` percentage points per quarter."""
    return [(day, start + drift * (days - day) / 90.0) for day in range(days, 0, -30)]


def ramp(start: float, creep: float, jump: float, days: int = 400) -> list[tuple[float, float]]:
    """Gentle for most of its history, then `jump` in the final quarter.

    A constant drift cannot test the score: the typical move it is standardised
    against *is* the drift, so every quarter scores exactly 1.0. Something has
    to be unusual for unusualness to be measurable.
    """
    out = [(day, start + creep * (days - day) / (days - 90.0)) for day in range(days, 90, -30)]
    return out + [(day, start + creep + jump * (90.0 - day) / 90.0) for day in (90, 60, 30, 1)]


# ------------------------------------------------------------- what a feed is


def test_a_six_letter_pair_is_split_without_a_table():
    assert mc.currencies("eurusd") == ("EUR", "USD")
    assert mc.currencies("gbpjpy") == ("GBP", "JPY")


def test_an_instrument_that_is_not_a_pair_has_no_base():
    """Gold has no policy rate, and saying it has one at zero is the mistake."""
    assert mc.currencies("gold") == ("", "USD")
    assert mc.currencies("btc") == ("", "USD")
    assert mc.currencies("volatility_75_index") == ("", "USD")


def test_a_european_index_is_not_quoted_in_dollars():
    assert mc.currencies("ger40") == ("", "EUR")
    assert mc.currencies("uk100") == ("", "GBP")


def test_the_quote_table_agrees_with_the_one_trading_uses():
    """Two tables for the same fact, and this is what stops them drifting.

    `structures` cannot import `trading` - trading imports structures and the
    cycle would close - so the currency an instrument is quoted in is written
    twice. Written twice and checked once.
    """
    from till_infinity.trading import exposure as ex

    for feed, (_, quote) in ex.LEGS.items():
        base, mine = mc.currencies(feed)
        if base:
            assert (base, mine) == ex.legs(feed), feed
        else:
            assert mine == quote, feed


# --------------------------------------------------------------- the readings


def test_a_missing_leg_produces_no_gap_rather_than_a_gap_against_zero():
    """The yen has no daily policy rate. Read as zero it is the largest carry
    trade in the book, in whichever direction the present leg points."""
    macro = mc.Macro()
    series(macro, mc.OVERNIGHT["USD"], steady("us", 3.6))
    found = macro.features("usdjpy")
    assert "macro_carry_gap" not in found


def test_a_gap_is_the_difference_between_two_legs():
    macro = mc.Macro()
    series(macro, mc.OVERNIGHT["USD"], steady("us", 3.6))
    series(macro, mc.OVERNIGHT["JPY"], steady("jp", 0.8))
    found = macro.features("usdjpy")
    assert found["macro_carry_gap"] == pytest.approx(2.8)


def test_the_daily_policy_rate_wins_the_level_and_the_monthly_one_the_trend():
    """Both are carried on purpose: the level wants to be current and the trend
    wants both legs measured the same way. No single series does both."""
    macro = mc.Macro()
    series(macro, mc.OVERNIGHT["USD"], steady("us", 3.0, drift=0.5))
    series(macro, mc.POLICY["USD"], [(0.0, 3.63)])
    reading = macro.reading("USD")
    assert reading.carry == pytest.approx(3.63)  # the daily one
    assert reading.trend == pytest.approx(0.5)  # the monthly one


def test_a_balance_sheet_is_read_relatively_and_a_rate_absolutely():
    """A trillion dollars means nothing without the level it is a trillion out
    of; a rate moving a point means a point wherever it started."""
    macro = mc.Macro()
    now = time.time()
    macro.observe("WALCL", now - 120 * DAY, 8_000.0)
    macro.observe("WALCL", now, 7_600.0)
    assert macro.relative("WALCL") == pytest.approx(-0.05)
    assert macro.change("WALCL") == pytest.approx(-400.0)


def test_a_series_that_stops_before_the_window_has_no_trend():
    macro = mc.Macro()
    macro.observe(mc.OVERNIGHT["USD"], time.time(), 3.6)
    assert macro.change(mc.OVERNIGHT["USD"]) is None


def test_a_revision_replaces_the_value_at_that_date():
    macro = mc.Macro()
    when = time.time()
    assert macro.observe("WALCL", when, 8_000.0)
    assert macro.observe("WALCL", when, 8_100.0)
    assert not macro.observe("WALCL", when, 8_100.0)
    assert macro.latest("WALCL") == 8_100.0


def test_observations_out_of_order_stay_sorted():
    """FRED answers newest-first and a revision restates an old date."""
    macro = mc.Macro()
    now = time.time()
    for ago in (10, 400, 90, 200):
        macro.observe("DFF", now - ago * DAY, float(ago))
    assert macro.latest("DFF") == 10.0


# ------------------------------------------------ the features on a signal


def test_every_feature_is_a_float_the_signal_contract_accepts():
    """A string in `features` raised on the first signal and stopped the
    structures consumer for four minutes while the container reported healthy."""
    macro = mc.Macro()
    series(macro, mc.OVERNIGHT["USD"], steady("us", 3.6, drift=-0.2))
    series(macro, mc.OVERNIGHT["EUR"], steady("eu", 2.0, drift=0.1))
    series(macro, mc.LONG["USD"], steady("usl", 4.4))
    series(macro, mc.LONG["EUR"], steady("eul", 2.9))
    series(macro, mc.REAL_YIELD, steady("real", 1.9, drift=-0.1))
    found = macro.features("eurusd")
    assert found
    assert all(isinstance(v, float) for v in found.values()), found
    assert all(k.startswith("macro_") for k in found), found
    # The contract itself: `to_dict` rounds every value.
    Signal(shape=Shape.LEVEL, feed="eurusd", venue="x", score=1.0, features=found).to_dict()


def test_a_cold_macro_publishes_nothing():
    assert mc.Macro().features("eurusd") == {}


def test_the_dollar_block_reaches_an_instrument_with_no_carry():
    """Gold has no rate differential and is still a macro trade: it is priced
    against the dollar's real yield like everything else here."""
    macro = mc.Macro()
    series(macro, mc.REAL_YIELD, steady("real", 1.9, drift=-0.3))
    series(macro, mc.BREAKEVEN, steady("be", 2.3))
    found = macro.features("gold")
    assert found["macro_us_real_yield"] == pytest.approx(steady("real", 1.9, drift=-0.3)[-1][1])
    assert found["macro_us_real_yield_change"] < 0
    assert "macro_carry_gap" not in found


# ------------------------------------------------------------- the model


def test_the_model_needs_the_level_and_the_change_to_agree():
    """A wide gap on its own is priced. What is not priced is the change."""
    macro = mc.Macro()
    # The dollar pays more and the gap is *narrowing*: no call.
    series(macro, mc.OVERNIGHT["USD"], steady("us", 4.0, drift=-0.4))
    series(macro, mc.OVERNIGHT["EUR"], steady("eu", 2.0, drift=0.0))
    side, _score, _why = macro.stance("eurusd")
    assert side == 0


def test_the_model_speaks_when_a_widening_gap_favours_the_base():
    macro = mc.Macro()
    series(macro, mc.OVERNIGHT["EUR"], ramp(4.0, creep=0.1, jump=1.0))
    series(macro, mc.OVERNIGHT["USD"], steady("us", 2.0))
    side, score, why = macro.stance("eurusd")
    assert side == 1
    assert score > mc.MOVE_SCORE
    assert "EUR" in why


def test_a_constant_drift_scores_exactly_one_because_it_is_the_typical_move():
    """Not a curiosity - it is what the score means. A quarter that moved the
    gap by exactly its own median quarter is not news, and the threshold sits
    there deliberately."""
    macro = mc.Macro()
    series(macro, mc.OVERNIGHT["EUR"], steady("eu", 4.0, drift=0.5))
    series(macro, mc.OVERNIGHT["USD"], steady("us", 2.0))
    assert macro.stance("eurusd")[1] == pytest.approx(1.0)


def test_a_stance_is_announced_once_and_not_on_every_poll():
    """A gap that has been wide all year is priced; repeating it every poll
    publishes a constant wearing a timestamp."""
    macro = mc.Macro()
    series(macro, mc.OVERNIGHT["EUR"], ramp(4.0, creep=0.1, jump=1.0))
    series(macro, mc.OVERNIGHT["USD"], steady("us", 2.0))
    first = macro.calls(["eurusd"])
    assert len(first) == 1
    assert first[0].shape is Shape.MACRO
    assert first[0].direction == "up"
    assert macro.calls(["eurusd"]) == []


def test_a_macro_signal_carries_the_features_it_was_read_from():
    macro = mc.Macro()
    series(macro, mc.OVERNIGHT["EUR"], ramp(4.0, creep=0.1, jump=1.0))
    series(macro, mc.OVERNIGHT["USD"], steady("us", 2.0))
    call = macro.calls(["eurusd"])[0]
    assert call.features["macro_carry_gap"] == pytest.approx(ramp(4.0, 0.1, 1.0)[-1][1] - 2.0)


def test_an_unknown_instrument_produces_no_call():
    macro = mc.Macro()
    series(macro, mc.OVERNIGHT["USD"], ramp(3.0, creep=0.1, jump=1.0))
    assert macro.calls(["", "not_a_thing"]) == []


# ------------------------------------------------------------- the handover


def test_the_macro_topic_is_actually_subscribed_to():
    """The defect this whole file exists for: a correct model on a topic
    nothing reads is the same as no model."""
    assert MACRO in TOPICS


def observations(path, rows) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE observations (source TEXT, series TEXT, time REAL, value REAL,"
        " scale INTEGER, country TEXT, indicator TEXT, frequency TEXT, period TEXT,"
        " updated REAL)"
    )
    conn.executemany(
        "INSERT INTO observations (source, series, time, value) VALUES (?, ?, ?, ?)", rows
    )
    conn.commit()
    conn.close()


def test_the_store_is_read_and_the_series_arrive(tmp_path):
    path = tmp_path / "news.db"
    now = time.time()
    observations(
        path,
        [("fred", mc.OVERNIGHT["USD"], now - d * DAY, 3.0) for d in range(400, 0, -30)],
    )
    rows = mc.stored(path)
    assert rows
    macro = mc.Macro()
    assert macro.take(rows) == len(rows)
    assert macro.latest(mc.OVERNIGHT["USD"]) == 3.0


def test_a_missing_store_is_silence_rather_than_a_fault(tmp_path):
    """Macro features are an enrichment. The level calls they attach to are
    correct without them, so a deployment with no news service must not stop."""
    assert mc.stored(tmp_path / "absent.db") == []


@pytest.mark.asyncio
async def test_a_macro_notice_makes_the_watcher_read_the_store(tmp_path):
    """End to end, and the only test that would have caught the original bug:
    the bus notice carries a count, so the reading has to come from the store."""
    path = tmp_path / "news.db"
    now = time.time()
    rows = [("fred", mc.OVERNIGHT["USD"], now - d * DAY, 3.0) for d in range(400, 0, -30)]
    rows += [("fred", mc.OVERNIGHT["EUR"], now - d * DAY, 2.0) for d in range(400, 0, -30)]
    observations(path, rows)

    watcher = Watcher(Bus(), settings=Settings(news_db=path, warm=False, journalling=False))
    assert not watcher.macro.warm
    await watcher.handle(Message(topic=MACRO, payload={"source": "fred", "rows": len(rows)}))
    assert watcher.macro.warm
    assert watcher.macro.features("eurusd")["macro_carry_gap"] == pytest.approx(-1.0)


@pytest.mark.asyncio
async def test_the_reading_can_be_turned_off(tmp_path):
    path = tmp_path / "news.db"
    observations(path, [("fred", mc.OVERNIGHT["USD"], time.time(), 3.0)])
    watcher = Watcher(
        Bus(), settings=Settings(news_db=path, macro=False, warm=False, journalling=False)
    )
    await watcher.handle(Message(topic=MACRO, payload={"source": "fred"}))
    assert not watcher.macro.warm


# ------------------------------------------- configuration across a restore


def test_a_restore_takes_this_deployment_s_formation_not_the_pickled_one(tmp_path):
    """The bug this catches ran in production for the whole life of the setting.

    `load` replaces the configured engine with the pickled one, and the pickle
    carries the formation it was **first** saved with. A deployment asking for
    three passes therefore drew levels with whichever one existed when the
    state file was created, and the only symptom was that `run` and `origin`
    never drew anything - which reads exactly like two formations that do not
    work rather than like two that never ran.
    """
    from till_infinity.structures import store as sxstore

    stale = Watcher(Bus(), settings=Settings(state_dir=tmp_path, formation="pip", warm=False))
    assert stale.engine.passes == ("pip",)
    sxstore.save(
        {
            "detector": stale.detector,
            "drift": stale.drift,
            "engine": stale.engine,
            "clock": stale.clock,
            "activity": stale.activity,
        },
        tmp_path,
    )

    fresh = Watcher(
        Bus(), settings=Settings(state_dir=tmp_path, formation="pip,run,origin", warm=False)
    )
    assert fresh.load()
    assert fresh.engine.passes == ("pip", "run", "origin")
    assert fresh.engine.formation == "pip,run,origin"


def test_an_unknown_formation_is_still_refused_after_a_restore():
    from till_infinity.structures.engine import Engine

    engine = Engine()
    with pytest.raises(ValueError, match="unknown formation"):
        engine.draw_with("candles")
    # And the engine is left drawing what it was, not left with nothing.
    assert engine.passes


def test_how_many_passes_agree_is_published_as_a_number():
    """`Level.origin` has always recorded which formations drew a level and
    nothing ever counted it, so "do two methods agreeing behave better" could
    not be asked of a single one of 969 recorded outcomes."""
    from till_infinity.structures.service import _passes

    class Level:
        origin = "pip+run+origin"

    assert _passes(Level()) == ["origin", "pip", "run"]

    class Pivot:
        origin = "pivot:PC+pivot:PP"

    # One formation however many pivots merged into it.
    assert _passes(Pivot()) == ["pivot"]


@pytest.mark.asyncio
async def test_the_store_is_read_before_the_first_notice(tmp_path):
    """FRED is a slow source. Waiting for its next poll would publish level
    calls with no policy on them for hours, with four hundred days of it
    already in the store."""
    path = tmp_path / "news.db"
    now = time.time()
    observations(
        path,
        [("fred", mc.OVERNIGHT["USD"], now - d * DAY, 3.0) for d in range(400, 0, -30)],
    )
    bus = Bus()
    watcher = Watcher(bus, settings=Settings(news_db=path, warm=False, journalling=False))
    await bus.close()
    await watcher.run(messages=0)
    assert watcher.macro.warm


def test_a_pair_with_a_leg_not_yet_collected_is_not_treated_as_gold():
    """`macro_liquidity` is the reading for an instrument with no base leg.
    Keyed off whether the *readings* were known rather than off whether there
    is a base, it appeared on `eurusd` for as long as the euro rate had not
    arrived - the same key meaning two different things."""
    macro = mc.Macro()
    now = time.time()
    macro.observe("WALCL", now - 120 * DAY, 8_000.0)
    macro.observe("WALCL", now, 8_100.0)
    assert "macro_liquidity" not in macro.features("eurusd")
    assert "macro_liquidity" in macro.features("gold")


@pytest.mark.asyncio
async def test_the_opening_read_emits_what_it_finds(tmp_path):
    """Discarding the return was worse than not reading at all: `calls` records
    the stance it announces, so a startup read computed seven stance changes,
    marked them as published, and dropped them - and those feeds then stayed
    silent until they flipped again."""
    import inspect

    from till_infinity.structures import service

    source = inspect.getsource(service.Watcher.run)
    assert "opening = await self._read_macro()" in source
    assert "await self.emit(opening)" in source


def test_a_stance_is_only_remembered_once_it_is_returned():
    """The property that made the dropped signals permanent: `calls` is the
    only place the stance is written, so anything that takes its output and
    discards it has suppressed a signal rather than delayed one."""
    macro = mc.Macro()
    series(macro, mc.OVERNIGHT["EUR"], ramp(4.0, creep=0.1, jump=1.0))
    series(macro, mc.OVERNIGHT["USD"], steady("us", 2.0))
    assert "eurusd" not in macro._stance
    found = macro.calls(["eurusd"])
    assert found
    assert macro._stance["eurusd"] != 0
