"""The sizing-multiplier path, and the fact that it has never run.

`Profile.risk_scale` and `profile.spike_scale` both imported `scaling` as
`from ...risk import scaling` - **three dots**, which raises `ImportError:
attempted relative import beyond top-level package`. So every call raised, the
eight sizing reductions behind them never applied, and the only coverage was a
`hasattr` check, which a broken method passes just as well as a working one.

The import is fixed and the multipliers are **off**, because switching eight
reductions on with a one-character fix would change every position size on the
next deploy with no measurement of their joint effect and no baseline to
compare against. `refit-the-parameter-a-lever-multiplies` is what that costs:
a multiplier whose mean is not one changes the average too, and it once
reversed a +1192 result to -24.

So these tests pin two things: that the shipped answer is `1.0`, which is what
the desk has actually been trading, and that the import resolves when the
switch is on - the second being the part a `hasattr` could never check.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from till_infinity.strategies.profile import (
    MULTIPLIERS,
    MULTIPLIERS_ON,
    Profile,
    multipliers_on,
    spike_scale,
)


class Bare(Profile):
    """A profile with nothing on it, so only the gate can be under test."""

    name = "bare"


@pytest.fixture(autouse=True)
def _off(monkeypatch):
    monkeypatch.delenv(MULTIPLIERS_ON, raising=False)


def test_the_multipliers_are_off_as_shipped():
    """Which is not a default chosen here - it is what the desk has traded,
    because the path raised on every call until 2026-11-01."""
    assert multipliers_on() == frozenset()
    assert Bare.__new__(Bare).risk_scale({}, "eurusd") == 1.0
    assert spike_scale({}, object()) == 1.0


def test_an_unset_switch_is_not_an_error():
    """A gate that raised when unset would be the same bug in a new place: a
    sizing path that cannot be called is a sizing path nobody is using."""
    assert Bare.__new__(Bare).risk_scale({"tr_percentile": 0.99}, "eurusd") == 1.0


def test_an_empty_setting_leaves_everything_off(monkeypatch):
    """A blank value is what a hand-edited env file looks like, and it has to
    mean off rather than all."""
    monkeypatch.setenv(MULTIPLIERS_ON, "")
    assert multipliers_on() == frozenset()
    monkeypatch.setenv(MULTIPLIERS_ON, " , ")
    assert multipliers_on() == frozenset()


def test_all_turns_on_every_one(monkeypatch):
    monkeypatch.setenv(MULTIPLIERS_ON, "all")
    assert multipliers_on() == set(MULTIPLIERS)
    assert len(MULTIPLIERS) == 10, (
        "nine reductions plus the structural share - `agreement` was added "
        "2026-11-10 and prices how many *rules* point the same way, where "
        "`crowding` prices how many *positions* sit on one currency leg"
    )


def test_the_import_actually_resolves_now(monkeypatch):
    """**The assertion a `hasattr` cannot make.** `risk_scale` existed and
    raised `ImportError` for as long as the path was dead, so the only test
    that distinguishes fixed from broken is one that reaches the import.

    `spike_scale` is the one of the two that needs nothing but its arguments,
    so it is the one that can be driven to the import without constructing a
    whole profile.
    """
    monkeypatch.setenv(MULTIPLIERS_ON, "spike")

    class Settings:
        spike_above = 0.0
        spike_floor = 0.5

    # Reaches `scaling.by_spike` and returns a real number rather than raising.
    assert spike_scale({"tr_percentile": 0.5}, Settings()) == pytest.approx(1.0)


def test_each_multiplier_can_be_switched_on_by_itself(monkeypatch):
    """**Eight at once is one trial with eight confounded parameters**, and at
    a target Sharpe of 1.5 a month of data supports about one trial. So they
    are named individually: `SIZING_MULTIPLIERS=spike` enables one."""
    monkeypatch.setenv(MULTIPLIERS_ON, "spike")
    assert multipliers_on() == {"spike"}
    monkeypatch.setenv(MULTIPLIERS_ON, "spike,crowding")
    assert multipliers_on() == {"spike", "crowding"}
    monkeypatch.setenv(MULTIPLIERS_ON, "all")
    assert multipliers_on() == set(MULTIPLIERS)


def test_a_typo_refuses_rather_than_silently_disabling_one(monkeypatch):
    """A name that matched nothing would leave a multiplier off while the
    config said it was on, and the failure is a position sized **larger** than
    intended - the wrong direction to be quiet about."""
    monkeypatch.setenv(MULTIPLIERS_ON, "spike,crowdding")
    with pytest.raises(ValueError, match="not a sizing multiplier"):
        multipliers_on()


def test_the_values_come_back_by_name(monkeypatch):
    """A product says a trade was made smaller; nine named numbers say which
    readings did it and by how much. The journal's whole value is the `why`,
    and a product discards exactly that.

    The keys are present whether or not a multiplier is enabled, so a reader
    comparing two decisions is not comparing two different shapes.
    """
    found = Bare.__new__(Bare).multipliers({}, "eurusd")
    assert set(found) == set(MULTIPLIERS)
    assert all(value == 1.0 for value in found.values())


def test_the_module_imports_scaling_from_one_level_up():
    """The literal regression. `strategies` and `risk` are siblings under
    `till_infinity`, so `..risk` is correct and `...risk` reaches past the
    top-level package - which is an `ImportError` at call time rather than at
    import time, and so invisible to anything that only imports the module.
    """
    from pathlib import Path

    import till_infinity.strategies.profile as module

    source = Path(module.__file__).read_text()
    # Import *statements* only - the prose above `MULTIPLIERS_ON` quotes the
    # broken form on purpose, and a substring search would match itself.
    statements = [
        line.strip() for line in source.splitlines() if line.strip().startswith("from ..")
    ]
    assert not [line for line in statements if line.startswith("from ...risk")]
    # Three: `spike_scale`, `risk_scale`'s product and `multipliers`' terms.
    assert statements.count("from ..risk import scaling") == 3


# ------------------------------------- a correlated book, and the side of it


def test_a_sell_is_scored_on_the_legs_it_actually_holds():
    """**The defect this exists for, measured on the live desk.**

    `crowding` assumed every proposal was a buy, so a short of EURUSD was read
    as long EUR when it is long **USD** - and it therefore found no crowding
    against a book that was long the dollar seven other ways. On 2026-11-10
    `statespace-surprise` opened eight positions on one bar close, every one of
    them long USD (two by buying USDxxx, six by selling xxxUSD), and this
    multiplier scored the eighth at 1.000 against the seven before it.
    """
    from till_infinity.risk.scaling import crowding

    # Long USD seven ways: two by buying USDxxx, five by selling xxxUSD.
    book = [
        ("usdcad", 1),
        ("usdjpy", 1),
        ("gbpusd", -1),
        ("audusd", -1),
        ("eurusd", -1),
        ("xauusd", -1),
        ("btcusd", -1),
    ]
    # An eighth trade that is also long USD must be reduced.
    crowded = crowding("ethusd", book, 0.9, "sell")
    assert crowded < 1.0, "a sell that is long USD read as uncrowded"
    assert crowded == pytest.approx(0.9**7, rel=1e-9), "every one of the seven shares the leg"

    # And the unsided call is the bug: it scores the same trade as a buy.
    assert crowding("ethusd", book, 0.9) > crowded


def test_a_hedge_is_not_penalised():
    """`trading-scaling.md` states it: two positions can share a leg and point
    opposite ways on it, which is not crowding. Buying EURUSD against a book
    that is long USD is **short** the dollar, so it reduces concentration and
    must keep its full size."""
    from till_infinity.risk.scaling import crowding

    book = [("usdcad", 1), ("usdjpy", 1), ("gbpusd", -1), ("audusd", -1)]
    assert crowding("eurusd", book, 0.9, "buy") == 1.0


def test_an_instrument_that_diversifies_the_quote_currency_is_barely_touched():
    """A DAX CFD settles in euros, so against a dollar-long book it loads EUR
    rather than USD. It is reduced only for the EUR legs it genuinely shares -
    here the one short-EUR position - and not for the dollar at all."""
    from till_infinity.risk.scaling import crowding

    dollars = [("usdcad", 1), ("usdjpy", 1), ("audusd", -1), ("gbpusd", -1)]
    assert crowding("germany 40", dollars, 0.9, "buy") == 1.0, "no EUR leg in that book"

    with_euro = [*dollars, ("eurusd", -1)]  # selling EURUSD is short EUR
    assert crowding("germany 40", with_euro, 0.9, "buy") == pytest.approx(0.9)


def test_the_reduction_is_geometric_and_lenient_at_a_high_share():
    """Geometric because the risk of a shared leg compounds - three positions
    all long the dollar are closer to three of one trade than to one and a
    half. The numbers are stated so a deploy can see what it is choosing:
    at 0.9 an eighth correlated trade still keeps about half its size."""
    from till_infinity.risk.scaling import crowding

    book = [(f"{leg}usd", -1) for leg in ("gbp", "aud", "eur", "nzd")]
    assert crowding("xauusd", book, 0.9, "sell") == pytest.approx(0.9**4)
    assert crowding("xauusd", book, 0.9, "sell") > 0.65, "four deep is still two thirds"
    first = crowding("xauusd", book[:1], 0.9, "sell")
    assert first == pytest.approx(0.9), "the first shared leg costs a tenth"


def test_a_share_of_zero_leaves_every_size_alone():
    """The switch. Off is the default and off must be exactly 1.0, so a deploy
    that has not opted in is bit-identical to one before this existed."""
    from till_infinity.risk.scaling import crowding

    book = [("gbpusd", -1), ("audusd", -1), ("eurusd", -1)]
    assert crowding("xauusd", book, 0.0, "sell") == 1.0
    assert crowding("xauusd", book, 0.0) == 1.0


def test_every_deployed_symbol_decomposes_into_currency_legs():
    """**The guard that would have caught this at the migration.**

    `LEGS` was keyed on the retired service's feed names - `gold`, `btc`,
    `us100` - and the live desk calls those `xauusd`, `btcusd`,
    `us tech 100`. So `legs()` returned `("", "")` for **22 of the 30 deployed
    symbols** and `crowding` returned 1.0 for each: a concentration limit that
    could only see the eight USD majors, with nothing anywhere saying so.

    Asserted over the deployed list rather than over `LEGS` itself, because the
    failure is a symbol with no entry and not an entry with no symbol.
    """
    from till_infinity.risk import exposure
    from till_infinity.strategies.sizes import feed_of_symbol

    deployed = (
        "EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF XAUUSD XAGUSD XPTUSD XCUUSD",
        "US Oil|UK Brent Oil|Wall Street 30|US SP 500|US Tech 100|Germany 40",
        "UK 100|Japan 225|Australia 200|France 40|Europe 50|Hong Kong 50",
        "BTCUSD ETHUSD BNBUSD NZDUSD AUDCAD EURAUD AUDNZD EURCAD",
    )
    symbols = [s for row in deployed for s in (row.split("|") if "|" in row else row.split())]
    blind = [s for s in symbols if exposure.legs(feed_of_symbol(s)) == ("", "")]
    assert not blind, (
        f"{len(blind)} of {len(symbols)} deployed symbols have no currency legs, so a "
        f"concentration limit cannot see them: {blind}"
    )


def test_a_dollar_pegged_quote_is_carried_with_its_own_code():
    """`Hong Kong 50` settles in HKD, which is pegged to the dollar - so it
    diversifies the currency *code* and not the risk. Carried with its own code
    because that is what the broker settles in, and asserted here so a reader
    counting distinct quote currencies knows it is not diversification."""
    from till_infinity.risk import exposure

    assert exposure.legs("hong kong 50") == ("HK50", "HKD")


# ------------------------------------- rules that agree are not rules apart


def test_rules_all_pointing_one_way_are_sized_as_fewer_rules():
    """**The gap between the two guards this desk already had.**

    `_already_held` refuses two rules wanting the *same* trade, and `crowding`
    prices two rules both long USD on *different* instruments. Neither notices
    five rules whose whole books point one way, so a book that is one bet five
    times prices as five independent ones. `ideas.md` logs it as E6 and
    `node/selection.effective_trials` already deflates a Sharpe by exactly this
    quantity - it had simply never reached a sizing decision.
    """
    from till_infinity.risk.scaling import by_agreement

    # Three rules, each long USD a different way.
    others = {
        "a": [("gbpusd", -1), ("audusd", -1)],
        "b": [("eurusd", -1), ("usdcad", 1)],
        "c": [("usdjpy", 1), ("xauusd", -1)],
    }
    mine = [("ethusd", -1)]  # also long USD
    assert by_agreement(mine, others, 0.9) == pytest.approx(0.9**3)


def test_a_hedging_rule_keeps_its_whole_size():
    """A rule that is short the dollar against a book that is long it reduces
    concentration. Penalising it would push the book further one way, which is
    the opposite of what the multiplier is for."""
    from till_infinity.risk.scaling import by_agreement

    others = {"a": [("gbpusd", -1), ("audusd", -1)], "b": [("eurusd", -1), ("usdcad", 1)]}
    hedge = [("eurusd", 1), ("gbpusd", 1)]  # long EUR and GBP, short USD
    assert by_agreement(hedge, others, 0.9) == 1.0


def test_the_threshold_separates_the_live_case_from_a_hedge_with_margin():
    """**`AGREE_AT` is derived from the book, not chosen round.** Cosine over
    full leg vectors dilutes a shared dollar leg, because each pair contributes
    its own counter-currency and those read as disagreement even though they
    are diversification. So the cases this exists for sit well below 1.0 and a
    threshold picked by intuition would have missed all of them."""
    from till_infinity.risk.exposure import agreement, leg_vector
    from till_infinity.risk.scaling import AGREE_AT

    one = leg_vector([("ethusd", -1)])
    pair = leg_vector([("gbpusd", -1), ("audusd", -1)])
    live = leg_vector(
        [
            ("gbpusd", -1),
            ("audusd", -1),
            ("eurusd", -1),
            ("usdcad", 1),
            ("usdjpy", 1),
            ("xauusd", -1),
            ("btcusd", -1),
        ]
    )
    hedge = leg_vector([("eurusd", 1), ("gbpusd", 1)])

    assert agreement(one, pair) == pytest.approx(0.5774, abs=5e-4)
    assert agreement(one, live) == pytest.approx(0.6614, abs=5e-4)
    assert agreement(hedge, pair) == pytest.approx(-0.8333, abs=5e-4)
    # The threshold sits between them, with room on both sides.
    assert agreement(hedge, pair) < AGREE_AT < agreement(one, pair)


def test_a_share_of_zero_and_an_empty_book_both_leave_the_size_alone():
    """The two off switches. A gate that silently admits everything reads the
    same as one that works, so off must be exactly 1.0."""
    from till_infinity.risk.scaling import by_agreement

    others = {"a": [("gbpusd", -1)]}
    assert by_agreement([("ethusd", -1)], others, 0.0) == 1.0
    assert by_agreement([("ethusd", -1)], {}, 0.9) == 1.0
    assert by_agreement([], others, 0.9) == 1.0


def test_a_position_is_attributed_to_the_rule_that_opened_it():
    """Nautilus derives `strategy_id` as `ClassName-tag` and `desks._tag`
    guarantees no hyphen inside the tag, so the class names the leaf and
    `LEAVES` names the rule. The class and not the tag's checksum: inverting a
    checksum fails silently on a collision."""
    from till_infinity.strategies.sizes import rule_of

    assert rule_of("SurpriseEdge-EURUSD_E270") == "statespace-surprise"
    assert rule_of("ZonesEdge-AUDCAD_E327_5m") == "zones"
    assert rule_of("StructureEdge-eurcad_E580") == "smc-bos-causal"
    assert rule_of("Nonsense-X") == "", "an unknown class names no rule"


def test_an_unattributable_position_is_dropped_and_not_pooled():
    """Pooling them under a blank key would make every unrecognised position
    one synthetic rule that agrees with everything - the failure direction that
    silently shrinks a size."""

    from till_infinity.strategies.sizes import books_by_rule

    def position(qty, sid, symbol):
        return SimpleNamespace(
            signed_qty=qty,
            strategy_id=sid,
            instrument_id=SimpleNamespace(symbol=SimpleNamespace(value=symbol)),
        )

    got = books_by_rule(
        [
            position(1.0, "SurpriseEdge-EURUSD_E270", "EURUSD"),
            position(-1.0, "ZonesEdge-GBPUSD_E327", "GBPUSD"),
            position(1.0, "Nonsense-X", "XAUUSD"),
            position(0.0, "ZonesEdge-X_E327", "XAUUSD"),
        ]
    )
    assert set(got) == {"statespace-surprise", "zones"}
    assert "" not in got
    assert got["zones"] == (("gbpusd", -1),), "the flat position was counted"


def test_a_profile_built_the_way_production_builds_one_sizes_with_a_multiplier_on(monkeypatch):
    """**This took the node down 13 times in seven hours.**

    Every rule profile in production is built with `__new__` - `ZoneProfile`'s
    own docstring says so, because configuration is shared between instances
    on two instruments - so `Profile.__init__` never runs and `self.settings`
    does not exist. The *off* path returns before reading it and carries a
    comment saying it must; the *on* path read it anyway.

    The first night `SIZING_MULTIPLIERS=crowding` was set, every sized intent
    from `zones` and `structure` raised
    `AttributeError('ZoneProfile' object has no attribute 'settings')` inside
    `on_bar`. The node exited cleanly and `restart: unless-stopped` brought it
    back, 13 times, each restart dropping the bracket legs that protect open
    positions.

    The existing `__new__` test passes because the multipliers are off in it.
    This is the same construction with one switched on, which is the case the
    deployment actually ran.
    """
    monkeypatch.setenv(MULTIPLIERS_ON, "crowding")
    # The real `Settings`, because a stub would only prove that a stub has
    # whatever fields the test gave it - and the production failure was a
    # *missing* field.
    from till_infinity.strategies.config import Settings

    settings = Settings()

    found = Bare.__new__(Bare).multipliers({}, "eurusd", book=(("eurusd", 1),), settings=settings)

    assert set(found) == set(MULTIPLIERS)
    assert all(value > 0.0 for value in found.values())


def test_without_settings_it_names_the_problem_rather_than_raising_an_attribute_error(
    monkeypatch,
):
    """**Named, and refused rather than sized.** A multiplier that quietly
    returned 1.0 would be a position larger than intended, which is the wrong
    direction to be quiet about - and an `AttributeError` from a line that
    reads like an attribute access is the hardest kind of failure to place.
    """
    monkeypatch.setenv(MULTIPLIERS_ON, "crowding")
    with pytest.raises(ValueError, match="no settings"):
        Bare.__new__(Bare).multipliers({}, "eurusd")


# ----------------------------------------------------- aggressive sizing


def test_the_ceiling_is_one_by_default_and_that_is_reduction_only():
    """**Off is a true no-op.** Every deployment before this setting existed
    ran a reduction-only book, so the default has to reproduce it exactly -
    a flag that quietly changes size on a redeploy is the one shape of change
    nobody can audit after the fact."""
    from till_infinity.risk import scaling
    from till_infinity.strategies.config import Settings

    assert Settings().size_ceiling == 1.0
    # An instrument at half the target: the ratio is 2.0 and is cut to 1.0.
    assert scaling.by_volatility(50.0, 100.0) == 1.0
    assert scaling.combined(1.5, 0.8) == pytest.approx(0.8)


def test_the_ceiling_lets_the_quiet_half_of_the_same_ratio_through():
    """`target / vol` is **one formula**. Clamping it at 1.0 keeps the cut
    when an instrument is loud and discards the increase when it is quiet,
    which is an asymmetric estimator and not conservatism: a desk that halves
    at twice the target and never doubles at half of it runs a lower average
    risk than `TRADING_RISK_FRACTION` says, by an amount no setting records.
    """
    from till_infinity.risk import scaling

    # Twice as quiet as the target earns twice the size, up to the ceiling.
    assert scaling.by_volatility(50.0, 100.0, 2.0) == pytest.approx(2.0)
    # Four times as quiet still earns only the ceiling. The bound is required
    # rather than optional: the ratio goes to infinity on a dead instrument.
    assert scaling.by_volatility(25.0, 100.0, 1.5) == pytest.approx(1.5)
    # And the loud half is untouched by the ceiling, which is the half that
    # was never in question.
    assert scaling.by_volatility(200.0, 100.0, 2.0) == pytest.approx(0.5)


def test_the_ceiling_bounds_the_product_and_the_floor_still_holds():
    from till_infinity.risk import scaling

    assert scaling.combined(1.5, 0.8, ceiling=1.5) == pytest.approx(1.2)
    assert scaling.combined(1.5, 1.5, ceiling=1.5) == pytest.approx(1.5), "the ceiling was passed"
    assert scaling.combined(0.01, 0.01, ceiling=2.0) == pytest.approx(scaling.FLOOR)


def test_a_ceiling_below_one_cannot_shrink_the_book():
    """A ceiling is the *top* of the range and never a cut. Read as a scale,
    `TRADING_SIZE_CEILING=0.5` would halve every position on the desk; read as
    a ceiling it is simply not raising anything, which is what the name says.
    """
    from till_infinity.risk import scaling

    assert scaling.by_volatility(200.0, 100.0, 0.5) == pytest.approx(0.5)
    assert scaling.combined(0.8, ceiling=0.0) == pytest.approx(0.8)
    assert scaling.combined(1.0, ceiling=0.5) == pytest.approx(1.0)


def test_no_other_scaler_is_allowed_above_one():
    """**What keeps the lever to one measured quantity.** Every other scaler's
    upper half would be a new claim nothing here measured - more edge earns
    more size, above the high-water mark earns more size - and the second of
    those is a martingale. `refit-the-parameter-a-lever-multiplies` is why
    eight levers at once cannot be read at all.
    """
    from till_infinity.risk import scaling

    assert scaling.by_edge(10.0, 1.0) == 1.0, "edge sized up"
    assert scaling.by_drawdown(100.0, 200.0, 0.2) == 1.0, "equity above the peak sized up"
    assert scaling.by_regime(1.0, 0.1) == 1.0
    assert scaling.by_spike(0.99, 0.9, 2.0) == 1.0
    assert scaling.by_slippage(0.5) == 1.0, "an undershooting stop sized up"
    assert scaling.by_interval("15m", (("15m", 3.0),)) == 1.0
    assert scaling.crowding("eurusd", (), 2.0) == 1.0
