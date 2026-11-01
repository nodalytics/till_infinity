"""Which Nautilus instrument an MT5 symbol becomes, and why it matters.

Everything used to be a `CurrencyPair`, and the provider's docstring called
that a deliberate simplification. It was not harmless: a `CurrencyPair`
asserts a base and a quote currency, so `US500` - an index, priced in dollars,
with nothing underneath it to be a base - got `USD` by fallback and became a
pair against itself. Nothing raised. It just classified, margined and reported
an index as FX.

So these tests are mostly about **what the type is and where the type came
from**: the terminal's `trade_calc_mode`, not the symbol's name. A name is a
broker's marketing - Deriv calls a synthetic "Volatility 75 Index" and a
broker may file gold anywhere - and a rule keyed on names needs a new case per
broker, discovered in production.

The fixtures are the real field shapes the bridge returns for five symbols the
desk actually trades.
"""

from __future__ import annotations

import asyncio

import pytest
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Cfd, CurrencyPair

from till_infinity.adapters.mt5.providers import (
    CFDINDEX,
    MT5InstrumentProvider,
    asset_class,
    is_forex,
)

VENUE = Venue("MT5")

#: `trade_calc_mode` is MQL5's `ENUM_SYMBOL_CALC_MODE`: 0 forex, 2 cfd,
#: 3 cfdindex, 4 cfdleverage.
SYMBOLS: dict[str, dict] = {
    "EURUSD": {
        "digits": 5,
        "volume_step": 0.01,
        "volume_min": 0.01,
        "volume_max": 500.0,
        "currency_base": "EUR",
        "currency_profit": "USD",
        "trade_calc_mode": 0,
        "path": "Forex\\Majors\\EURUSD",
        "trade_contract_size": 100_000,
    },
    "XAUUSD": {
        "digits": 2,
        "volume_step": 0.01,
        "currency_base": "XAU",
        "currency_profit": "USD",
        "trade_calc_mode": 2,
        "path": "CFD\\Metals\\XAUUSD",
        "trade_contract_size": 100,
    },
    "US500": {
        "digits": 1,
        "volume_step": 0.1,
        "currency_base": "USD",
        "currency_profit": "USD",
        "trade_calc_mode": 3,
        "path": "CFD\\Indices\\US500",
        "trade_contract_size": 1,
    },
    "Volatility 75 Index": {
        "digits": 4,
        "volume_step": 0.001,
        "currency_base": "USD",
        "currency_profit": "USD",
        "trade_calc_mode": 4,
        "path": "Synthetic Indices\\Volatility 75 Index",
        "trade_contract_size": 1,
    },
    "BTCUSD": {
        "digits": 2,
        "volume_step": 0.01,
        "currency_base": "BTC",
        "currency_profit": "USD",
        "trade_calc_mode": 2,
        "path": "Crypto\\BTCUSD",
        "trade_contract_size": 1,
    },
}


class FakeTransport:
    """The transport surface the provider uses, and nothing else.

    `open` is here because it is the method the provider was *not* calling:
    the factory built one transport for the provider and each client built its
    own, and only the client opened the one it built - so the provider's first
    call raised `BridgeError("the bridge session is not open")` at the moment
    a node starts.
    """

    def __init__(self, rows: dict[str, dict] | None = None) -> None:
        self.rows = SYMBOLS if rows is None else rows
        self.opened = 0

    async def open(self) -> None:
        self.opened += 1

    async def symbols(self) -> list[str]:
        return list(self.rows)

    async def symbol_info(self, symbol: str) -> dict:
        return self.rows.get(symbol, {})


def loaded(rows: dict[str, dict] | None = None) -> MT5InstrumentProvider:
    provider = MT5InstrumentProvider(FakeTransport(rows), VENUE)
    asyncio.run(provider.load_all_async())
    return provider


def one(symbol: str):
    provider = MT5InstrumentProvider(FakeTransport(), VENUE)
    asyncio.run(provider.load_async(InstrumentId(Symbol(symbol), VENUE)))
    return provider.find(InstrumentId(Symbol(symbol), VENUE))


# ---------------------------------------------------------------- the open bug


def test_the_provider_opens_its_transport_before_using_it():
    """The factory's provider transport was never opened, so the first
    `_connect` of a node raised `BridgeError`. A data client would have loaded
    no instruments and every reconciliation report would have skipped every
    row as an unknown instrument - not a crash, a node that comes up and
    reconciles nothing."""
    transport = FakeTransport()
    provider = MT5InstrumentProvider(transport, VENUE)
    asyncio.run(provider.load_all_async())
    assert transport.opened >= 1
    assert provider.list_all(), "and it actually loaded something"


# ------------------------------------------------------------------- the split


def test_a_currency_pair_is_a_currency_pair():
    instrument = one("EURUSD")
    assert isinstance(instrument, CurrencyPair)
    assert str(instrument.base_currency) == "EUR"
    assert str(instrument.quote_currency) == "USD"


@pytest.mark.parametrize("symbol", ["XAUUSD", "US500", "Volatility 75 Index", "BTCUSD"])
def test_everything_that_is_not_forex_is_a_cfd(symbol):
    """On this venue the non-forex symbols *are* CFDs - there is no underlying
    being delivered. `Deriv synthetics are real markets`, which changes how
    they are researched and not how they are modelled."""
    assert isinstance(one(symbol), Cfd)


def test_an_index_has_no_base_currency():
    """**The bug this split exists for.** `US500` reports
    `currency_base="USD"` and `currency_profit="USD"`, so the old fallback
    produced a currency pair of USD against USD - an index classified and
    margined as FX, with nothing raising."""
    instrument = one("US500")
    assert instrument.base_currency is None
    assert str(instrument.quote_currency) == "USD"


def test_a_synthetic_index_is_an_index_and_not_a_pair():
    """Deriv's synthetics quote in USD with no base, exactly like a cash
    index, and their names are the least reliable thing about them."""
    instrument = one("Volatility 75 Index")
    assert isinstance(instrument, Cfd)
    assert instrument.base_currency is None
    assert instrument.asset_class == AssetClass.INDEX


def test_a_cfd_on_a_pair_keeps_its_base_currency():
    """Gold against the dollar has a real base - the absence is a property of
    an index, not of being a CFD, so the test for it cannot be the type."""
    instrument = one("XAUUSD")
    assert str(instrument.base_currency) == "XAU"
    assert instrument.asset_class == AssetClass.COMMODITY


def test_crypto_is_classified_from_the_path():
    assert one("BTCUSD").asset_class == AssetClass.CRYPTOCURRENCY


# ------------------------------------------------------- what decides the type


def test_the_mode_decides_and_not_the_name():
    """A broker that files gold under a name this code has never seen still
    gets a CFD, because the mode is what MT5 computes profit and margin
    from - and that is the one field certain to be right about an
    instrument's type."""
    assert is_forex({"trade_calc_mode": 0}) is True
    assert is_forex({"trade_calc_mode": 5}) is True, "forex without leverage is still forex"
    assert is_forex({"trade_calc_mode": 2}) is False
    assert is_forex({"trade_calc_mode": CFDINDEX}) is False


def test_a_bridge_that_does_not_report_the_mode_falls_back_to_the_currencies():
    """`mt5-api` narrows its symbol response and may not carry the mode at
    all, and a narrowed body is a 200 rather than an error - so the absence
    cannot be treated as "not forex" or every symbol on that bridge becomes a
    CFD."""
    assert is_forex({"currency_base": "EUR", "currency_profit": "USD"}) is True
    assert is_forex({"currency_base": "USD", "currency_profit": "USD"}) is False
    assert is_forex({"currency_profit": "USD"}) is False


def test_an_unparseable_mode_does_not_decide_the_type():
    """A string where an int was expected is a bridge change, not a forex
    pair, and `int("")` raising inside a type decision would take out the
    whole symbol load."""
    assert is_forex({"trade_calc_mode": "", "currency_base": "EUR", "currency_profit": "USD"})
    assert not is_forex({"trade_calc_mode": "nonsense", "currency_profit": "USD"})


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("CFD\\Metals\\XAUUSD", AssetClass.COMMODITY),
        ("CFD\\Energies\\XTIUSD", AssetClass.COMMODITY),
        ("Crypto\\ETHUSD", AssetClass.CRYPTOCURRENCY),
        ("CFD\\Indices\\GER40", AssetClass.INDEX),
        ("Stocks\\US\\AAPL", AssetClass.EQUITY),
        ("Forex\\Exotics\\USDTRY", AssetClass.FX),
    ],
)
def test_the_asset_class_comes_from_the_brokers_own_filing(path, expected):
    """The path is the only description of an instrument MT5 offers beyond its
    name, and it is the broker's own - so it is evidence rather than a guess."""
    assert asset_class({"path": path}) == expected


def test_metals_filed_under_indices_are_still_metals():
    """A broker filing gold under `CFD\\Indices\\Metals` means metal. The
    ordering of the path table is what makes the more specific fragment win,
    which is a property worth a test because reordering the table silently
    changes the answer."""
    assert asset_class({"path": "CFD\\Indices\\Metals\\XAUUSD"}) == AssetClass.COMMODITY


def test_an_index_mode_with_no_path_is_still_an_index():
    """A bridge that narrows the response to drop `path` should not downgrade
    an index to FX when the mode already said what it is."""
    assert asset_class({"trade_calc_mode": CFDINDEX}) == AssetClass.INDEX


def test_a_leveraged_currency_cfd_falls_to_fx():
    """Which is what it is: a CFD on a currency pair, with no path saying
    otherwise."""
    assert asset_class({}) == AssetClass.FX


# ------------------------------------------------------------ what rides in info


@pytest.mark.parametrize(("symbol", "size"), [("EURUSD", 100_000), ("XAUUSD", 100), ("US500", 1)])
def test_the_contract_size_survives_on_the_instrument(symbol, size):
    """Nautilus fixes a CFD's multiplier at 1, so `trade_contract_size` - 100
    ounces for gold, 1 for an index - cannot ride on the instrument and has to
    stay readable. Sizing needs it, and losing it silently would size gold as
    though a lot were one ounce."""
    assert one(symbol).info["trade_contract_size"] == size


def test_precision_comes_from_the_terminal():
    """`Price` is fixed-precision, so declaring it wrong truncates the feed.
    Measured on the dispersion fold: btc at 2 decimals moves a 1m reading by
    3e-5 relative while 15m stays at float noise."""
    assert one("EURUSD").price_precision == 5
    assert one("US500").price_precision == 1
    assert one("Volatility 75 Index").price_precision == 4


def test_a_symbol_the_bridge_does_not_know_is_skipped_rather_than_invented():
    """An empty body is what `/symbols/info/{symbol}` returns for a name the
    account does not carry, and a half-filled instrument would resolve with
    invented precision."""
    provider = MT5InstrumentProvider(FakeTransport({"NOPE": {}}), VENUE)
    asyncio.run(provider.load_all_async())
    assert provider.list_all() == []


def test_every_listed_symbol_loads():
    """A provider that silently drops one symbol is a desk that cannot trade
    one feed, and `pool-events-before-a-per-feed-guard` is the recorded
    version of that: a guard once dropped 141 of 146 feeds."""
    assert len(loaded().list_all()) == len(SYMBOLS)
