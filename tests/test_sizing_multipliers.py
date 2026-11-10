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
    assert len(MULTIPLIERS) == 9, "eight reductions plus the structural share"


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
