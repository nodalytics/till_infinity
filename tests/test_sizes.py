"""The arithmetic between an accepted signal and an order the venue will take.

**A 5,136-bar replay accepted 25 intents and placed none of them.** All 25 were
refused at `(desk):zero-volume`, because `Surprise.decide` read its volume off
the proposal's features with a comment saying the sizer had put it there, and
no sizer ran: `risk/sizing.lots` had no caller on the Nautilus path, nor did
`Profile.risk_scale`, nor did the crowding multiplier. Every gate worked and
nobody did the arithmetic.

Two of the three things that were missing would have been caught by any test
that sized a real instrument, and the suite had none - a `Strategy` cannot be
instantiated without a kernel around it, so the only cheap assertions anybody
wrote were about the gates, and the conversion underneath them was reachable
only through a node no test stood up. `strategies/sizes.py` exists so that
conversion is a plain function over an instrument, a book and an intent. This
file is the reason it is worth having as one.

The third thing is the one worth reading twice. `Desk._spec` left `tick_value`
on its dataclass default of **1.0**, and 1.0 is correct for a standard lot of
nearly every dollar-quoted instrument this desk trades: 100,000 units at a
0.00001 tick, or 100 ounces of gold at 0.01. So the sizing was right on the
majors by coincidence and wrong on a yen pair, wrong on a synthetic, and wrong
on anything priced in a currency the account is not held in - which is the
error that ships, because nothing about it looks broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from nautilus_trader.model.currencies import EUR, JPY, USD
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Currency, Price, Quantity

from till_infinity.domain.models import Intent, Refusal, Side
from till_infinity.strategies import sizes
from till_infinity.strategies.config import Settings
from till_infinity.strategies.surprise import SurpriseProfile

VENUE = Venue("MT5")


def pair(
    symbol: str = "EURUSD",
    *,
    digits: int = 5,
    step: float = 0.01,
    quote=USD,
    **info: object,
) -> CurrencyPair:
    """One instrument, in the shape the MT5 provider builds them.

    A `CurrencyPair` rather than a mock, because the fields being read are
    Nautilus's own types and a mock would let a test pass against an attribute
    the real class does not have. `info` is the terminal's `symbol_info` dict,
    which is where the contract size and the tick value ride - see
    `adapters/mt5/providers.py` on why a `Cfd` cannot carry them.
    """
    precision = max(0, len(f"{step:.10f}".rstrip("0").split(".")[-1]))
    return CurrencyPair(
        instrument_id=InstrumentId(Symbol(symbol), VENUE),
        raw_symbol=Symbol(symbol),
        base_currency=EUR,
        quote_currency=quote,
        price_precision=digits,
        size_precision=precision,
        price_increment=Price(10.0**-digits, digits),
        size_increment=Quantity(step, precision),
        lot_size=None,
        max_quantity=Quantity(100.0, precision),
        min_quantity=Quantity(step, precision),
        max_notional=None,
        min_notional=None,
        max_price=None,
        min_price=None,
        margin_init=Decimal("0"),
        margin_maint=Decimal("0"),
        maker_fee=Decimal("0"),
        taker_fee=Decimal("0"),
        ts_event=0,
        ts_init=0,
        info=dict(info),
    )


@dataclass(frozen=True, slots=True)
class Held:
    """An open position, as `book_of` reads one: an id and a signed quantity."""

    instrument_id: InstrumentId
    signed_qty: float


def held(symbol: str, quantity: float) -> Held:
    return Held(InstrumentId(Symbol(symbol), VENUE), quantity)


def buy(**fields: object) -> Intent:
    """A long EURUSD with a 22-point stop, which is 0.0022 of price.

    The numbers are arbitrary and chosen to be easy to divide: at a 0.00001
    tick and a tick value of 1.0 the stop costs 220 per lot, so a 25 budget
    buys 0.1136 lots and rounds down to 0.11.
    """
    chosen: dict[str, object] = {
        "feed": "eurusd",
        "symbol": "EURUSD",
        "side": Side.BUY,
        "volume": 0.0,
        "entry": 1.1000,
        "stop": 1.0978,
        "target": 1.1044,
        "features": {"vol_bps": 10.0},
        "interval": "5m",
    }
    chosen.update(fields)
    return Intent(**chosen)  # type: ignore[arg-type]


def sized(intent: Intent | None = None, *, instrument=None, **kwargs: object):
    """`sizes.size` over the defaults, so a test states only what it varies."""
    chosen = instrument if instrument is not None else pair(trade_contract_size=100_000)
    settings = kwargs.pop("settings", None) or Settings()
    return sizes.size(
        intent if intent is not None else buy(),
        spec=sizes.spec_of(chosen, rate=float(kwargs.pop("rate", 1.0))),
        settings=settings,
        equity=float(kwargs.pop("equity", 10_000.0)),
        **kwargs,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------- the spec


def test_the_tick_value_comes_from_the_venue_rather_than_a_default():
    """**The bug that was right on the majors.** A yen pair's tick is worth
    about 0.0067 of a dollar per unit, not 1.0, so a spec carrying the default
    sized a USDJPY position by a factor of 150 - and sized EURUSD correctly, so
    nothing in a run on the majors would have shown it."""
    instrument = pair("USDJPY", digits=3, quote=JPY, trade_tick_value_loss=0.67)
    assert sizes.spec_of(instrument).tick_value == pytest.approx(0.67)


def test_the_loss_tick_value_beats_the_profit_one():
    """MT5 states three: `trade_tick_value_profit`, `trade_tick_value_loss`,
    and `trade_tick_value`, which equals the profit figure. A risk budget is
    the cost of being **stopped**, so the loss one is what is being inverted.
    They agree on nearly every instrument; where a venue charges an asymmetric
    conversion they do not, and taking the profit value sizes the position
    slightly too large - the direction nobody notices."""
    instrument = pair(trade_tick_value=1.10, trade_tick_value_loss=0.90)
    assert sizes.spec_of(instrument).tick_value == pytest.approx(0.90)


def test_a_venue_that_states_no_tick_value_is_derived_from_the_contract_size():
    """Binance states no tick value and quantity is in base units, so one tick
    on one unit is the tick itself. The same expression covers a 100,000-unit
    forex lot, which is the point of deriving it rather than special-casing."""
    assert sizes.spec_of(pair(trade_contract_size=100_000)).tick_value == pytest.approx(1.0)
    assert sizes.spec_of(pair(trade_contract_size=1)).tick_value == pytest.approx(1e-05)


def test_a_derived_value_is_converted_and_a_stated_one_is_not():
    """MT5's three tick values are already in the deposit currency, so applying
    a rate to them would convert twice. The contract-size figure is in the
    quote currency by construction and is the only one that needs it."""
    assert sizes.spec_of(pair(trade_contract_size=100_000), rate=0.5).tick_value == pytest.approx(
        0.5
    )
    stated = pair(trade_contract_size=100_000, trade_tick_value_loss=1.0)
    assert sizes.spec_of(stated, rate=0.5).tick_value == pytest.approx(1.0)


def test_a_missing_conversion_refuses_the_trade_rather_than_guessing_one():
    """A rate of zero is how `Desk._rate` reports that it could not get one. It
    has to reach a refusal with a reason: a yen pair mis-converted is wrong by
    a factor of 150 and the direction depends on which way the mistake went, so
    there is no safe guess - only a refusal, or a number the venue supplied."""
    found = sized(rate=0.0, instrument=pair("USDJPY", digits=3, quote=JPY))
    assert isinstance(found, Refusal)
    assert found.gate == "unsized"
    assert "no tick value" in found.detail


def test_a_tick_value_its_own_contract_size_contradicts_is_refused():
    """**NGAS, measured 2026-11-06.** The terminal states `trade_tick_size`
    0.001 and `trade_contract_size` 10000, so one tick on one lot is 10.0 - and
    states `trade_tick_value_loss` as **0.001**. Its `currency_profit` is USD,
    so no conversion explains the gap: one of the two fields is wrong by a
    factor of 10,000.

    Every other instrument on the book satisfies the identity, XAGUSD being the
    clean demonstration - tick 0.001, contract 5000, value 5.0. Which NGAS field
    is the bad one decides whether a position is right or 10,000x too large, and
    `volume_max` of 5.0 is the only thing bounding it. There is no safe guess,
    so this refuses, exactly as a missing conversion does.
    """
    ngas = pair(
        "NGAS",
        digits=3,
        trade_tick_size=0.001,
        trade_contract_size=10_000,
        trade_tick_value_loss=0.001,
    )
    assert sizes.spec_of(ngas, account_currency=USD).tick_value == pytest.approx(0.0)
    found = sizes.size(
        buy(symbol="NGAS", feed="ngas", entry=3.283, stop=3.233, target=3.383),
        spec=sizes.spec_of(ngas, account_currency=USD),
        settings=Settings(),
        equity=10_000.0,
    )
    assert isinstance(found, Refusal)
    assert found.gate == "unsized"
    assert "no tick value" in found.detail

    # **Fails open where the account currency is unknown.** No account yet, or
    # a genuinely multi-currency one, must not start refusing instruments.
    assert sizes.spec_of(ngas).tick_value == pytest.approx(0.001)


def test_the_brokers_own_profit_calculation_beats_the_stated_tick_value():
    """**It ends the ambiguity this function's docstring describes, without a
    trade.** Two readings of `trade_tick_value` were open: that it is the quote
    currency unconverted, or that it is already the deposit currency. The doc
    said it "needs a realised P&L observation, not another read" -
    `order_calc_profit` is neither. It is the arithmetic the broker *settles*
    with, answered in the account currency, so it is the observation without
    the position.

    The value here is EUR-quoted: stated 0.01 against a true 0.01114, which
    oversizes by 1.11x. That is the direction that matters - an oversized
    instrument risks more than the budget said, while an undersized one merely
    reads as a dead rule.
    """
    instrument = pair("Germany 40", trade_tick_value_loss=0.01, calc_tick_value=0.01114)
    assert sizes.spec_of(instrument).tick_value == pytest.approx(0.01114)


def test_a_calculated_value_the_stated_one_contradicts_is_refused_not_adopted():
    """**Japan 225, the 158x case.** A yen-quoted CFD states 0.01 where the
    converted truth is 0.0000631, and position size is inversely proportional
    to the tick value - so adopting the calculated figure would size it 158x
    *larger* on one endpoint's word.

    A gap that wide means one of the two numbers means something nobody has
    confirmed, and only one of the two possible mistakes can empty an account.
    So this refuses, exactly as `_contradicts` refuses NGAS: the calculation is
    trusted to *correct* a value, never to multiply one by a factor no trade
    has yet shown. Leaving it refused also loses nothing real - at 1/158 of
    intent the instrument was never trading.
    """
    instrument = pair("Japan 225", trade_tick_value_loss=0.01, calc_tick_value=0.0000631)
    found = sized(instrument=instrument)
    assert isinstance(found, Refusal)
    assert found.gate == "unsized"


def test_without_a_calculation_the_stated_value_stands():
    """The venue is asked once per instrument at load and the answer can fail -
    a symbol the terminal will not select, a bridge restart mid-load. That has
    to leave sizing exactly as it was rather than refuse the whole book, which
    is why the calculated figure is an *addition* to `info` and not a
    replacement for the stated one."""
    assert sizes.spec_of(pair(trade_tick_value_loss=0.9)).tick_value == pytest.approx(0.9)


def test_a_stated_value_a_conversion_explains_is_kept():
    """USDJPY as the terminal really states it: tick 0.001 on a 100,000 contract
    is 100 JPY, and the stated 0.6308 is that figure converted at 158.53. The
    guard above must not fire on it - a stated value the contract size explains
    *through the rate* is the venue doing its job."""
    yen = pair(
        "USDJPY",
        digits=3,
        quote=JPY,
        trade_tick_size=0.001,
        trade_contract_size=100_000,
        trade_tick_value_loss=0.6308,
    )
    assert sizes.spec_of(yen, rate=1.0 / 158.53, account_currency=USD).tick_value == pytest.approx(
        0.6308
    )

    # **And at the rate this desk actually passes.** The account states no base
    # currency, so `Desk._rate` returns 1.0 - against which 0.6308 looks like a
    # hundredfold contradiction. The guard must not fire: JPY is not the
    # account's currency, so a conversion is exactly what explains the gap.
    assert sizes.spec_of(yen, rate=1.0, account_currency=USD).tick_value == pytest.approx(0.6308)


def test_a_stated_value_matching_the_contract_size_is_kept_whatever_the_rate():
    """Germany 40: tick 0.01, contract 1, stated 0.01, `currency_profit` EUR.

    The stated figure equals `tick x contract` exactly, which it does for all
    seven non-USD CFDs on this book while the three non-USD FX pairs come back
    at exactly their rate. That is strong evidence the CFD figures are in the
    quote currency and are being sized as though they were dollars.

    **It is not conclusive, and this deliberately does not act on it.** The
    other reading is that the broker settles these in the account currency and
    `currency_profit` names the underlying's currency, in which case 0.01 is
    already right. Converting on the wrong reading would size Japan 225 **158x
    larger**; not converting leaves it 158x smaller. Only one of those can
    blow up an account, so the stated value stands until a realised P&L
    observation settles it - see `docs/venue.md`.
    """
    dax = pair(
        "Germany 40",
        digits=2,
        quote=EUR,
        trade_tick_size=0.01,
        trade_contract_size=1,
        trade_tick_value_loss=0.01,
    )
    assert sizes.spec_of(dax, rate=1.1136, account_currency=USD).tick_value == pytest.approx(0.01)
    assert sizes.spec_of(dax, rate=1.0, account_currency=USD).tick_value == pytest.approx(0.01)


#: Every instrument the desk trades, as the terminal stated them on
#: 2026-11-06: `(symbol, digits, tick_size, contract_size, stated_loss_value,
#: currency_profit)`. Kept whole rather than sampled, because the guard in
#: `spec_of` must be shown to refuse exactly one of them.
LIVE_BOOK = [
    ("EURUSD", 5, 1e-05, 100_000, 1.0, "USD"),
    ("GBPUSD", 5, 1e-05, 100_000, 1.0, "USD"),
    ("AUDUSD", 5, 1e-05, 100_000, 1.0, "USD"),
    ("USDCAD", 5, 1e-05, 100_000, 0.7077241008365298, "CAD"),
    ("USDCHF", 5, 1e-05, 100_000, 1.2184423433083147, "CHF"),
    ("USDJPY", 3, 0.001, 100_000, 0.6307954330410648, "JPY"),
    ("XAUUSD", 2, 0.01, 100, 1.0, "USD"),
    ("XAGUSD", 3, 0.001, 5_000, 5.0, "USD"),
    ("XPTUSD", 2, 0.01, 100, 1.0, "USD"),
    ("XCUUSD", 2, 0.01, 1, 0.01, "USD"),
    ("NGAS", 3, 0.001, 10_000, 0.001, "USD"),
    ("US Oil", 3, 0.001, 1, 0.001, "USD"),
    ("UK Brent Oil", 3, 0.001, 1, 0.001, "USD"),
    ("Wall Street 30", 2, 0.01, 1, 0.01, "USD"),
    ("US SP 500", 2, 0.01, 1, 0.01, "USD"),
    ("US Tech 100", 2, 0.01, 1, 0.01, "USD"),
    ("Germany 40", 2, 0.01, 1, 0.01, "EUR"),
    ("France 40", 2, 0.01, 1, 0.01, "EUR"),
    ("Europe 50", 2, 0.01, 1, 0.01, "EUR"),
    ("UK 100", 2, 0.01, 1, 0.01, "GBP"),
    ("Japan 225", 2, 0.01, 1, 0.01, "JPY"),
    ("Australia 200", 2, 0.01, 1, 0.01, "AUD"),
    ("Hong Kong 50", 2, 0.01, 1, 0.01, "HKD"),
]


def test_the_guard_refuses_exactly_one_instrument_on_the_live_book():
    """**The check that stops this change being an outage.** A guard that
    refuses a stated tick value has to be shown against the whole book, not a
    sample: every instrument it refuses stops trading.

    Of the 23 live instruments, 16 are USD-profit and satisfy
    `stated == tick x contract` exactly, so the guard is silent on them. The
    six non-USD ones are skipped because a conversion can explain any gap -
    which is what keeps USDJPY, whose stated 0.6308 sits a hundredfold from its
    100 JPY, out of it. NGAS is the only contradiction, and it is a real one.
    """
    refused = []
    for symbol, digits, tick, contract, stated, profit in LIVE_BOOK:
        currency = Currency.from_str(profit)
        instrument = pair(
            symbol,
            digits=digits,
            quote=currency,
            trade_tick_size=tick,
            trade_contract_size=contract,
            trade_tick_value_loss=stated,
        )
        spec = sizes.spec_of(instrument, rate=1.0, account_currency=USD)
        if spec.tick_value == 0.0:
            refused.append(symbol)
    assert refused == ["NGAS"], refused


def test_every_other_instrument_keeps_the_tick_value_the_venue_stated():
    """The converse of the above: the guard must not quietly alter a value it
    accepts. Only NGAS is zeroed; the other 22 come through untouched."""
    for symbol, digits, tick, contract, stated, profit in LIVE_BOOK:
        if symbol == "NGAS":
            continue
        instrument = pair(
            symbol,
            digits=digits,
            quote=Currency.from_str(profit),
            trade_tick_size=tick,
            trade_contract_size=contract,
            trade_tick_value_loss=stated,
        )
        found = sizes.spec_of(instrument, rate=1.0, account_currency=USD).tick_value
        assert found == pytest.approx(stated), f"{symbol}: {found} != {stated}"


def test_the_venues_own_tick_beats_the_price_increment():
    """`price_increment` is set to `10**-digits` by the MT5 provider, and an
    instrument whose real tick is coarser pairs its tick value with the wrong
    tick. The money conversion divides by it, so a tenfold difference is a
    tenfold difference in position size."""
    coarse = sizes.spec_of(pair(trade_tick_size=0.0001, trade_tick_value_loss=1.0))
    assert coarse.tick_size == pytest.approx(0.0001)
    # `point` stays at the price increment, because that is what a broker's
    # `stops_level` is quoted in. The two fields are not the same question.
    assert coarse.point == pytest.approx(1e-05)


def test_a_close_only_instrument_is_not_tradable():
    """`Desk._undealable` has refused on `spec.tradable` since the port and the
    field was hardcoded `True`, so the gate could not fire. MT5 says
    `trade_mode` 0 for disabled and 3 for close-only; neither can open."""
    assert sizes.spec_of(pair(trade_mode=4)).tradable is True
    assert sizes.spec_of(pair(trade_mode=0)).tradable is False
    assert sizes.spec_of(pair(trade_mode=3)).tradable is False
    # A venue that says nothing is tradable, because the alternative is
    # refusing every instrument on every venue that is not MT5.
    assert sizes.spec_of(pair()).tradable is True


def test_the_brokers_minimum_stop_distance_reaches_the_spec():
    """`respects_stops_level` existed with no caller and `stops_level` was
    zero, which is the value that means "the broker did not say" and skips the
    check. Scalping lives inside that band, so the refusal it produces is a
    retcode turned into a record."""
    spec = sizes.spec_of(pair(trade_stops_level=20))
    assert spec.stops_level == 20.0
    assert spec.min_stop_distance == pytest.approx(0.0002)


# ------------------------------------------------------------------- the book


def test_the_open_book_is_feed_and_sign_pairs():
    """What `scaling.crowding` has always wanted. `Profile.multipliers` used to
    dig them out of position objects with `getattr(p, "feed", "")`, a contract
    only this desk's own `Position` satisfied - a Nautilus `Position` has an
    `instrument_id` and a signed quantity and no `feed` at all, so the
    comprehension discarded the whole book on every call."""
    book = sizes.book_of([held("EURUSD", 0.11), held("GBPUSD", -0.05)])
    assert book == (("eurusd", 1), ("gbpusd", -1))


def test_a_flat_position_does_not_crowd_a_leg():
    """The cache can hold a closed position briefly, and counting it would
    reduce the next trade for a leg nobody is on."""
    assert sizes.book_of([held("EURUSD", 0.0)]) == ()


def test_a_slash_in_the_symbol_is_the_same_feed():
    """Venues disagree about the separator and the currency legs are keyed one
    way. `EUR/USD` and `EURUSD` are one feed and one dollar leg."""
    assert sizes.feed_of(InstrumentId(Symbol("EUR/USD"), VENUE)) == "eurusd"


# ------------------------------------------------------------------ the sizing


def test_an_accepted_intent_leaves_with_a_volume():
    """**The regression.** Twenty-five accepted intents, no orders."""
    found = sized()
    assert isinstance(found, Intent)
    assert found.volume == pytest.approx(0.11)


def test_the_volume_risks_the_budget_and_not_more():
    """The one step in the chain that has to be right to the cent. Everything
    upstream is an estimate of what price will do; this is an arithmetic fact
    about what a loss costs. 0.25% of 10,000 is 25, and a 0.0022 stop at a
    0.00001 tick worth 1.0 costs 220 a lot."""
    found = sized()
    assert isinstance(found, Intent)
    assert found.risk_money == pytest.approx(0.11 * 220.0)
    assert found.risk_money <= 10_000.0 * Settings().risk_fraction


def test_the_lot_grid_is_rounded_down_and_never_up():
    """0.1136 lots is a good answer from the arithmetic and an instant
    rejection from the terminal. Rounding up is the one direction that takes a
    position over the risk it was sized for."""
    found = sized()
    assert isinstance(found, Intent)
    assert found.volume == pytest.approx(0.11)
    assert found.volume * 220.0 < 25.0


def test_a_minimum_lot_that_breaches_the_budget_is_refused_with_the_arithmetic():
    """Not rounded up to the minimum, which would convert "too small to take"
    into "take it anyway at a risk nobody authorised". The detail carries both
    figures because the decision it informs is whether to keep trading the
    instrument at all, not whether to re-refuse one signal."""
    found = sized(equity=100.0, instrument=pair(step=0.1, trade_contract_size=100_000))
    assert isinstance(found, Refusal)
    assert found.gate == "unsized"
    assert "does not cover the minimum" in found.detail
    assert "0.1 lot" in found.detail


def test_no_equity_is_a_refusal_rather_than_a_position():
    """`Desk._equity` returns 0.0 where there is no account yet, deliberately,
    rather than a guess - and a size computed from an invented equity is the
    one number nobody would catch."""
    found = sized(equity=0.0)
    assert isinstance(found, Refusal)
    assert "no equity" in found.detail


def test_a_stop_at_the_entry_cannot_be_sized():
    """Dividing by it would be an unbounded position. This is the refusal, not
    the exception."""
    found = sized(buy(stop=1.1000))
    assert isinstance(found, Refusal)
    assert "stop is at the entry" in found.detail


# -------------------------------------------------------------- the reductions


def test_the_reductions_do_nothing_until_they_are_named():
    """What the desk has actually been trading. `SIZING_MULTIPLIERS` is the
    deliberate switch and `1.0` is the baseline: turning eight levers on at
    once is one trial with eight confounded parameters."""
    assert isinstance(sized(profile=SurpriseProfile(Settings())), Intent)
    assert sized(profile=SurpriseProfile(Settings())).volume == sized().volume


def test_a_reduction_multiplies_the_budget_and_not_the_lots(monkeypatch):
    """**The order matters and it is not a free choice.** `lots` rounds down to
    the broker's volume step and then refuses a result below the minimum lot,
    so scaling after it would hand the venue a size off the grid. Scaling the
    fraction means one rounding, in the direction that cannot breach the
    budget.

    `share` is the reduction used here because it is the one that is constant
    per strategy rather than a reading of the current bar, so the expected
    number is arithmetic rather than a measurement: a scalp's share is 1.0 and
    a swing's is 0.85."""
    monkeypatch.setenv("SIZING_MULTIPLIERS", "share")

    class Swing(SurpriseProfile):
        style = "swing"

    found = sized(profile=Swing(Settings()))
    assert isinstance(found, Intent)
    # 25 x 0.85 / 220 is 0.0965 lots, which is 0.09 on a 0.01 grid.
    assert found.volume == pytest.approx(0.09)
    # Still on the grid, at the step's own precision. A float modulo is not the
    # check here: 0.09 % 0.01 is 0.00999... because a decimal step is not a
    # binary one, which is the reason `round_volume` rounds to the step's
    # decimal places rather than multiplying the steps back out.
    assert found.volume == round(found.volume, 2)


def test_the_reductions_that_fired_are_recorded_on_the_intent(monkeypatch):
    """A single number says a trade was made smaller; named numbers say which
    readings did it. That is the difference between enabling these and
    measuring them, and the journal copies the intent's features - so a product
    discards exactly the thing worth keeping."""
    monkeypatch.setenv("SIZING_MULTIPLIERS", "share")

    class Swing(SurpriseProfile):
        style = "swing"

    found = sized(profile=Swing(Settings()))
    assert isinstance(found, Intent)
    assert found.features["size_share"] == pytest.approx(0.85)
    assert found.features["size_scale"] == pytest.approx(0.85)
    # The ones that did not fire are not recorded. Nine columns of 1.0 on every
    # decision is noise rather than a record.
    assert "size_crowding" not in found.features


def test_crowding_reaches_the_sizer_with_a_real_book(monkeypatch):
    """**The third dead wire.** A long EURUSD and a long GBPUSD are one dollar
    trade in two tickets, and `crowding_share` is what sizes the second one
    down. It read 1.0 against a full book because the pairs never arrived.

    0.5 on one shared leg, so a quarter of the budget goes: 25 x 0.5 / 220 is
    0.0568 lots, which is 0.05 on a 0.01 grid."""
    monkeypatch.setenv("SIZING_MULTIPLIERS", "crowding")
    # **The share arrives with the caller, not on the profile.** Production
    # builds every profile with `__new__`, so `self.settings` does not exist
    # there at all - reading it took the node down 13 times on 2026-11-11 -
    # and `sizes.size` already receives the deployment's one `Settings`. There
    # is one configuration and this is where it comes from.
    found = sized(
        settings=Settings(crowding_share=0.5),
        profile=SurpriseProfile.__new__(SurpriseProfile),
        book=sizes.book_of([held("GBPUSD", 0.05)]),
    )
    assert isinstance(found, Intent)
    assert found.volume == pytest.approx(0.05)
    assert found.features["size_crowding"] == pytest.approx(0.5)


def test_a_position_the_other_way_round_does_not_crowd(monkeypatch):
    """A short GBPUSD is long dollars and a long EURUSD is short them, so they
    offset rather than compound. A crowding rule blind to the sign would halve
    a hedge."""
    monkeypatch.setenv("SIZING_MULTIPLIERS", "crowding")
    found = sized(
        profile=SurpriseProfile(Settings(crowding_share=0.5)),
        book=sizes.book_of([held("GBPUSD", -0.05)]),
    )
    assert isinstance(found, Intent)
    assert found.volume == pytest.approx(0.11)


def test_an_unknown_multiplier_name_raises_rather_than_disabling_one(monkeypatch):
    """A typo that silently switched a reduction off would be invisible in
    exactly the way the whole path was invisible while it raised `ImportError`
    - and the failure is a position larger than intended."""
    monkeypatch.setenv("SIZING_MULTIPLIERS", "crowdign")
    with pytest.raises(ValueError, match="crowdign"):
        sized(profile=SurpriseProfile(Settings()))


# -------------------------------------------------------- the argument order


def test_the_reductions_cannot_be_called_with_their_arguments_swapped():
    """`risk_scale` took `(feed, features)` and `multipliers` took the reverse
    until 2026-11-01, so a call written against either was wrong against the
    other - **and silently**: both arguments are consulted with `.get`, a
    string has none of the keys, and a swapped call sized every trade at 1.0
    rather than raising. `tests/test_sizing_multipliers.py` was written against
    the wrong order and passed.

    Keyword-only from the third argument on, for the reason `_reductions`
    exists: a positional list in that file has already put one argument in the
    wrong slot once."""
    profile = SurpriseProfile(Settings())
    with pytest.raises(TypeError):
        profile.multipliers({}, "eurusd", (), 10_000.0)  # type: ignore[misc]
    with pytest.raises(TypeError):
        profile.risk_scale({}, "eurusd", (), 10_000.0)  # type: ignore[misc]


def test_a_volume_already_on_the_intent_is_replaced_and_recorded():
    """Both decision rules read their volume as `features.get("volume")`, and
    the bar payload statespace publishes carries `volume` as the bar's own
    traded volume. Those are one careless move apart: a `features` dict that
    included it would put four digits where a lot size goes, and `make_qty`
    would take it. There is one authority for a size."""
    found = sized(buy(volume=1_337.0))
    assert isinstance(found, Intent)
    assert found.volume == pytest.approx(0.11)
    assert found.features["size_given"] == pytest.approx(1_337.0)


class _Money:
    def __init__(self, amount: float) -> None:
        self._amount = amount

    def as_double(self) -> float:
        return self._amount


class _SingleCurrencyAccount:
    """What Nautilus gives when `base_currency` was declared."""

    base_currency = "USD"

    def balance_total(self, currency=None):
        return _Money(10_000.0)

    def balances_total(self):
        return {"USD": _Money(10_000.0)}


class _MultiCurrencyAccount:
    """What the **MT5 client actually produces**: `base_currency=None`.

    `balance_total()` with no argument falls back to `self.base_currency` and
    raises when there is none, which is exactly what Nautilus does.
    """

    base_currency = None

    def balance_total(self, currency=None):
        if currency is None:
            raise TypeError("'currency' argument was `None`")
        return _Money(10_000.0)

    def balances_total(self):
        return {"USD": _Money(10_000.0)}


def test_equity_reads_an_account_that_declares_no_base_currency():
    """The live desk's shape, and the defect that stopped it trading.

    `MT5ExecutionClient` passes `base_currency=None` because an exec client is
    built before it has connected, so before the broker has said what the
    account is held in. `Desk._equity` then called `balance_total()` with no
    argument, which raises on such an account - **inside `Actor.on_bar`**, so
    every statespace proposal died on the way to being sized while quotes
    flowed and the terminal reported it would accept orders. The only symptom
    was a traceback per bar.
    """
    import pytest

    from till_infinity.strategies.sizes import equity_of

    account = _MultiCurrencyAccount()
    # The fixture is the failing shape, not a stand-in for one: the call the
    # old code made still raises on it.
    with pytest.raises(TypeError):
        account.balance_total()

    assert equity_of(account) == 10_000.0


def test_equity_still_reads_a_single_currency_account():
    """The control: the fix must not change the account shape that worked."""
    from till_infinity.strategies.sizes import equity_of

    assert equity_of(_SingleCurrencyAccount()) == 10_000.0


def test_equity_is_zero_without_an_account():
    """Zero rather than a guess - a size from an invented equity is the one
    number nobody would catch."""
    from till_infinity.strategies.sizes import equity_of

    assert equity_of(None) == 0.0


def test_equity_refuses_to_add_two_currencies():
    """A sum of unlike units is a wrong number that looks like a right one.

    MT5 holds one currency, so this cannot happen there; if a venue ever
    reports two, returning 0.0 stops sizing rather than sizing off a figure
    that is the addition of dollars and yen.
    """
    from till_infinity.strategies.sizes import equity_of

    class _Two(_MultiCurrencyAccount):
        def balances_total(self):
            return {"USD": _Money(10_000.0), "JPY": _Money(1_500_000.0)}

    assert equity_of(_Two()) == 0.0


# ------------------------------------------------------- aggressive sizing


def _aggressive(ceiling: float, monkeypatch) -> object:
    """A settings with volatility targeting on, which is the only reading the
    ceiling can act on. Without `SIZING_MULTIPLIERS` the whole path returns
    1.0 before it reads anything, so a test that forgot this would pass for
    the wrong reason."""
    monkeypatch.setenv("SIZING_MULTIPLIERS", "volatility")
    return Settings(volatility_target_bps=20.0, size_ceiling=ceiling)


def test_the_ceiling_raises_the_lot_on_a_quiet_instrument(monkeypatch):
    """**The end-to-end claim.** `buy()` carries `vol_bps` 10 against a target
    of 20, so the instrument is half as volatile as the target and the ratio
    is 2.0 - truncated to 1.0 today, and 1.5 under a ceiling of 1.5.

    Asserted on the volume and not on the multiplier, because the scale is
    applied to the *risk fraction* and `lots` then rounds down to the broker's
    volume step: a test on the scalar would pass over a path where the number
    never reached a size.
    """
    from till_infinity.strategies.profile import Profile

    # Built with `__new__`, the way production builds every rule profile -
    # which is the construction that took the node down 13 times when
    # `multipliers` read `self.settings`.
    bare = Profile.__new__(Profile)

    plain = sized(settings=_aggressive(1.0, monkeypatch), profile=bare)
    loud = sized(settings=_aggressive(1.5, monkeypatch), profile=bare)
    assert plain.volume > 0.0
    assert loud.volume > plain.volume, "the ceiling did not reach a size"
    # The exact lots, not a ratio. `buy()`'s own docstring sets the arithmetic:
    # the stop costs 220 per lot, so a 25 budget buys 0.1136 and a 1.5x budget
    # of 37.5 buys 0.1704 - and **both round down to the volume step**, which
    # is why 0.17 over 0.11 is 1.545 and not 1.5. A ratio assertion here would
    # be a test of the broker's step, not of the ceiling.
    assert plain.volume == pytest.approx(0.11)
    assert loud.volume == pytest.approx(0.17)
    assert loud.features["size_volatility"] == pytest.approx(1.5)


def test_the_money_cap_still_binds_above_the_ceiling(monkeypatch):
    """**It raises the fraction and not the stated cash loss.** A ceiling that
    could walk past `TRADING_MAX_RISK_MONEY` would make the one number a
    reader checks before a deploy stop meaning anything."""
    from till_infinity.strategies.profile import Profile

    # Built with `__new__`, the way production builds every rule profile -
    # which is the construction that took the node down 13 times when
    # `multipliers` read `self.settings`.
    bare = Profile.__new__(Profile)

    capped = Settings(volatility_target_bps=20.0, size_ceiling=3.0, max_risk_money=25.0)
    monkeypatch.setenv("SIZING_MULTIPLIERS", "volatility")
    found = sized(settings=capped, profile=bare)
    assert found.risk_money <= 25.0 + 1e-9, f"the cash cap was passed: {found.risk_money}"


def test_a_loud_instrument_is_still_cut_with_the_ceiling_up(monkeypatch):
    """The control. "The ceiling raises a quiet instrument" must be
    distinguishable from "the ceiling disables volatility targeting"."""
    from till_infinity.strategies.profile import Profile

    # Built with `__new__`, the way production builds every rule profile -
    # which is the construction that took the node down 13 times when
    # `multipliers` read `self.settings`.
    bare = Profile.__new__(Profile)

    quiet = sized(settings=_aggressive(2.0, monkeypatch), profile=bare)
    noisy = sized(
        buy(features={"vol_bps": 80.0}),
        settings=_aggressive(2.0, monkeypatch),
        profile=bare,
    )
    assert noisy.volume < quiet.volume
    assert noisy.features["size_volatility"] == pytest.approx(0.25)
