"""Instruments, from what the terminal lists.

`InstrumentProvider` is Nautilus's local store of instrument definitions. The
bridge's `/symbols/info/{symbol}` carries everything needed to build one:
digits, point, volume step and limits, contract size.

**Precision comes from the terminal, not from a guess.** `digits` is what the
broker quotes to, and `Price` is fixed-precision, so declaring it wrong
truncates the feed. Measured in `research/baseline/README.md`: btc at its
tradable 2 decimals moves a 1m dispersion reading by 3e-5 while 15m stays at
noise, because truncation matters in proportion to how small a bar's range is
against its tick size.

## A CFD is a `Cfd`, and the terminal says which is which

Everything used to be modelled as a `CurrencyPair`, including the index CFDs
and the synthetics, and the docstring called that a deliberate simplification.
It is not harmless. A `CurrencyPair` asserts a base currency and a quote
currency, and **US500 has no base currency** - the thing being priced is an
index, not a unit of something. The invented base was `USD` by fallback, which
makes `USDUSD`-shaped nonsense out of an instrument that Nautilus would
otherwise classify, margin and report correctly.

**The discriminator is `trade_calc_mode`**, which is MT5's own answer to "how
is profit on this computed" - `SYMBOL_CALC_MODE_FOREX` against
`SYMBOL_CALC_MODE_CFD`, `_CFDINDEX` and `_CFDLEVERAGE`. Not the symbol name
and not the path: a name is a broker's marketing - Deriv calls a synthetic
"Volatility 75 Index" and ICMarkets calls gold "XAUUSD" - and keying on it
means every new broker needs a new rule. The path is used only to pick an
asset class once the mode has already decided the type.

**What a `Cfd` cannot carry is the contract size.** Nautilus fixes a CFD's
multiplier at 1, so `trade_contract_size` - 100 ounces for gold, 1 for an
index - stays in `info` and sizing reads it from there. That is the right
place for it anyway: `risk/` already converts a price distance to lots, and a
multiplier on the instrument would be a second place for the conversion to
live and so a second place for it to disagree.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Cfd, CurrencyPair, Instrument
from nautilus_trader.model.objects import Currency, Price, Quantity

from .transport import Transport

#: Ticks spanned when asking the broker what a move is worth.
#:
#: One tick is rounded to the cent on most instruments, so asking about a
#: single one returns zero or a figure quantised to uselessness. A thousand
#: ticks is a move every instrument on the book prices without rounding, and
#: the answer divides back down exactly because `order_calc_profit` is linear
#: in the distance.
CALC_SPAN = 1000


class MT5InstrumentProvider(InstrumentProvider):
    """Loads instruments from the bridge, as the type the terminal says.

    A forex pair becomes a `CurrencyPair` and everything else - the index
    CFDs, the metals, the synthetics - becomes a `Cfd`, decided by
    `trade_calc_mode`. See the module docstring for why that field and not the
    symbol name.

    `Deriv synthetics are real markets`: a known generator and no auction,
    which changes how they are *researched*, not how an order is sized. They
    are CFDs on this venue and are modelled as such.
    """

    def __init__(self, bridge: Transport, venue: Venue, symbols: tuple[str, ...] = ()) -> None:
        super().__init__()
        self._bridge = bridge
        self._venue = venue
        self._wanted = symbols
        # Deferred like `terminal.py` does it: `Logger` is Nautilus's and
        # wants the logging subsystem up, which it is by the time a node
        # builds its providers but not necessarily when a test imports this.
        from nautilus_trader.common.component import Logger

        self.log = Logger(type(self).__name__)

    async def _ready(self) -> None:
        """Open the transport before using it, every time.

        **This provider's transport was never opened.** The factory built one
        for the provider and each client built its own, and only the client
        opened the one it built - so the provider's first call raised
        `BridgeError("the bridge session is not open")` on the first
        `_connect`, which is the moment a node starts. A data client would
        have failed to load a single instrument, and every execution
        reconciliation report would have skipped every row as an unknown
        instrument: not a crash, a node that comes up and reconciles nothing.

        Nothing caught it because every test passes the provider a fake that
        needs no session. Opening here rather than demanding the caller do it
        is the fix that cannot be forgotten again: `open()` is idempotent on
        both transports, so the cost of calling it per load is a branch.
        """
        await self._bridge.open()

    async def load_all_async(self, filters: dict | None = None) -> None:
        await self._ready()
        names = list(self._wanted) or await self._bridge.symbols()
        for name in names:
            await self.load_async(InstrumentId(Symbol(name), self._venue))

    async def load_ids_async(
        self, instrument_ids: list[InstrumentId], filters: dict | None = None
    ) -> None:
        for instrument_id in instrument_ids:
            await self.load_async(instrument_id)

    async def load_async(self, instrument_id: InstrumentId, filters: dict | None = None) -> None:
        await self._ready()
        symbol = instrument_id.symbol.value
        info = await self._bridge.symbol_info(symbol)
        if not info:
            return
        calculated = await self._calculated_tick_value(symbol, info)
        if calculated > 0.0:
            # A copy: the transport's dict is not this provider's to edit, and
            # `Proxy.symbol_info` returns one it has already merged a quote into.
            info = {**info, "calc_tick_value": calculated}
        instrument = self._build(instrument_id, info)
        if instrument is not None:
            self.add(instrument)

    async def _calculated_tick_value(self, symbol: str, info: dict[str, Any]) -> float:
        """What the **broker** says one tick on one lot is worth, in the
        account's currency - or `0.0` where it would not say.

        `order_calc_profit` is the function the terminal computes P&L with, so
        this is the one reading that settles what `trade_tick_value`'s unit
        is. Two readings of that field were open, one of them sizes a
        yen-quoted CFD 158x larger than the other, and `sizes.spec_of` refused
        to guess between them - see `docs/venue.md`, which says it needs a
        realised P&L observation. This is that observation without the
        position.

        **Asked over a wide move and divided back down.** One tick is rounded
        to the cent on most instruments, so a one-tick question comes back
        quantised to uselessness or to zero.

        **`symbol_info`'s own quote is the right price here, stale as it is.**
        Everywhere else in this adapter that is a bug - the route is frozen,
        which is why `tick()` exists and why the quote poll moved to it - but
        a tick value is a property of the contract and the account's currency,
        not of where the price is this second. A price minutes old names the
        same region, and using it costs no extra round trip.

        Never raises. The question is asked once per instrument at startup and
        can fail for reasons that have nothing to do with this instrument: a
        name the terminal will not `symbol_select` is a 400, and a transport
        with no calculator at all is an `AttributeError`. Either leaves sizing
        on the stated value, which is how the desk already behaves - whereas
        letting it propagate would drop the instrument and read as a feed that
        went quiet for no recorded reason.
        """
        tick = float(info.get("trade_tick_size") or 0.0)
        price = float(info.get("ask") or info.get("bid") or 0.0)
        if tick <= 0.0 or price <= 0.0:
            return 0.0
        try:
            profit = await self._bridge.calc_profit(
                "BUY", symbol, 1.0, price, price + CALC_SPAN * tick
            )
        except Exception:
            return 0.0
        value = abs(float(profit or 0.0)) / CALC_SPAN

        # **The measurement, in the startup log.** `docs/venue.md` records the
        # seven CFDs whose stated value is a factor out and says the question
        # needs a realised P&L observation; this line is that observation, per
        # instrument, every time the desk starts. A ratio near 1 says the
        # stated figure was already in the account's currency; the ratio being
        # the instrument's FX rate says it was not.
        #
        # Only where they differ, because 23 lines that all read `1.00x` is a
        # startup log nobody reads twice.
        stated = float(info.get("trade_tick_value_loss") or info.get("trade_tick_value") or 0.0)
        if stated > 0.0 and value > 0.0 and not 0.99 <= value / stated <= 1.01:
            self.log.warning(
                f"{symbol}: the broker prices a tick at {value:.6g} "
                f"against a stated {stated:.6g} ({value / stated:.4g}x)"
            )
        return value

    def _build(self, instrument_id: InstrumentId, info: dict[str, Any]) -> Instrument | None:
        digits = int(info.get("digits") or 5)
        step = float(info.get("volume_step") or 0.01)
        size_precision = max(0, len(f"{step:.10f}".rstrip("0").split(".")[-1]))
        quote = _currency(info.get("currency_profit") or info.get("currency_margin") or "USD")
        # Every field below is shared, because MT5 reports all of these the
        # same way whatever the instrument is. Only the type and the two
        # currency arguments differ.
        shared: dict[str, Any] = {
            "instrument_id": instrument_id,
            "raw_symbol": Symbol(instrument_id.symbol.value),
            "quote_currency": quote,
            "price_precision": digits,
            "size_precision": size_precision,
            "price_increment": Price(10.0**-digits, digits),
            "size_increment": Quantity(step, size_precision),
            "lot_size": None,
            "max_quantity": _quantity(info.get("volume_max"), size_precision),
            "min_quantity": _quantity(info.get("volume_min"), size_precision),
            "max_notional": None,
            "min_notional": None,
            "max_price": None,
            "min_price": None,
            # **Measured, not assumed.** The taker fee on this venue is read
            # off the spread rather than a schedule, and `spread-column-is-in-
            # points` is why: the terminal reports spread in points, not
            # price, and reading it as price made EURUSD look like a 476%
            # round trip. Commission is left at zero because this broker
            # charges in the spread.
            "margin_init": Decimal("0"),
            "margin_maint": Decimal("0"),
            "maker_fee": Decimal("0"),
            "taker_fee": Decimal("0"),
            "ts_event": 0,
            "ts_init": 0,
            # `trade_contract_size`, `trade_tick_value` and `trade_tick_size`
            # ride here. A `Cfd`'s multiplier is fixed at 1 by Nautilus, so
            # this dict is where sizing reads the contract size from.
            "info": dict(info),
        }

        if is_forex(info):
            # A pair has two currencies and both are real. `currency_base` is
            # only trustworthy once the mode has said this is forex - on an
            # index CFD the field is whatever the broker left in it.
            return CurrencyPair(
                base_currency=_currency(info.get("currency_base") or "USD"),
                **shared,
            )
        return Cfd(
            asset_class=asset_class(info),
            # **`None`, not a fallback.** An index has no base currency, and
            # inventing `USD` is what made `US500` look like a currency pair
            # against itself. `Cfd` accepts the absence; a `CurrencyPair`
            # cannot, which is the whole reason for the split.
            base_currency=_base_currency(info),
            **shared,
        )


#: `trade_calc_mode`, by MQL5's own `ENUM_SYMBOL_CALC_MODE` names.
#:
#: Only the ones this venue serves are named. The rest - the exchange modes
#: from 32 up, which are MOEX stocks and bonds - are not wrong so much as
#: absent: no broker this desk trades quotes them, and a mapping that guessed
#: at them would be untested code in the one place where being wrong silently
#: changes how a position is margined.
FOREX = 0
FUTURES = 1
CFD = 2
CFDINDEX = 3
CFDLEVERAGE = 4
FOREX_NO_LEVERAGE = 5

#: The modes where `currency_base` means something and a pair is a pair.
FOREX_MODES = (FOREX, FOREX_NO_LEVERAGE)

#: What a path says about an asset class, matched against the lowercased
#: `path` the terminal reports - `Forex\\Majors\\EURUSD`,
#: `CFD\\Metals\\XAUUSD`, `Crypto\\BTCUSD`. Ordered, because a path can
#: match more than one and the first is the more specific: a broker filing
#: gold under `CFD\\Indices\\Metals` means metal, not index.
PATHS: tuple[tuple[str, AssetClass], ...] = (
    ("metal", AssetClass.COMMODITY),
    ("energ", AssetClass.COMMODITY),
    ("oil", AssetClass.COMMODITY),
    ("agric", AssetClass.COMMODITY),
    ("commodit", AssetClass.COMMODITY),
    ("crypto", AssetClass.CRYPTOCURRENCY),
    ("stock", AssetClass.EQUITY),
    ("share", AssetClass.EQUITY),
    ("equit", AssetClass.EQUITY),
    ("ind", AssetClass.INDEX),
    ("synthetic", AssetClass.INDEX),
    ("volatility", AssetClass.INDEX),
    ("forex", AssetClass.FX),
    ("fx", AssetClass.FX),
)


def is_forex(info: dict[str, Any]) -> bool:
    """Is this a currency pair, by the terminal's own reckoning?

    `trade_calc_mode` is the field, because it is what MT5 uses to compute
    profit and margin on the symbol - so it is the one thing that is certain
    to be right about an instrument's type, whatever the broker called it.

    Absent, it falls back to *both* currencies being real and different, which
    is the weaker test the old code made implicitly. An `mt5-api` bridge
    narrows its symbol response and may not carry the mode at all, and a
    narrowed body is a 200 rather than an error.
    """
    mode = info.get("trade_calc_mode")
    if mode is not None:
        try:
            return int(mode) in FOREX_MODES
        except (TypeError, ValueError):
            pass
    base = str(info.get("currency_base") or "").upper()
    profit = str(info.get("currency_profit") or "").upper()
    return bool(base) and bool(profit) and base != profit


def asset_class(info: dict[str, Any]) -> AssetClass:
    """What kind of thing this CFD is on, from the path the terminal reports.

    The path is the broker's own filing system - `CFD\\Metals\\XAUUSD` - and
    it is the only description of an instrument MT5 offers beyond its name.
    Where it says nothing, `_CFDINDEX` is taken at its word and everything
    else falls to `OTHER`-shaped `FX`, which is what a leveraged CFD on a
    currency actually is.
    """
    path = str(info.get("path") or "").lower()
    for fragment, kind in PATHS:
        if fragment in path:
            return kind
    try:
        if int(info.get("trade_calc_mode") or -1) == CFDINDEX:
            return AssetClass.INDEX
    except (TypeError, ValueError):
        pass
    return AssetClass.FX


def _base_currency(info: dict[str, Any]) -> Currency | None:
    """The base currency where there genuinely is one, and `None` otherwise.

    A CFD on a currency pair has one; a CFD on an index does not. The test is
    that the field holds something, that it parses as a currency, and that it
    is not simply the quote currency repeated - `US500` with
    `currency_base="USD"` and `currency_profit="USD"` is the shape that used
    to produce a pair against itself.
    """
    raw = str(info.get("currency_base") or "").strip().upper()
    if not raw:
        return None
    quote = str(info.get("currency_profit") or info.get("currency_margin") or "").strip().upper()
    if raw == quote:
        return None
    try:
        return Currency.from_str(raw)
    except Exception:
        return None


def _currency(code: str) -> Currency:
    try:
        return Currency.from_str(str(code).upper())
    except Exception:
        return USD


def _quantity(value: Any, precision: int) -> Quantity | None:
    try:
        return Quantity(float(value), precision) if value else None
    except Exception:
        return None


__all__ = ["AssetClass", "MT5InstrumentProvider"]
