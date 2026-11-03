"""Filling the backtest catalogue from the price store.

`node/backtest.catalogue()` points at a `ParquetDataCatalog` and **nothing has
ever written one**. So `BacktestNode` and `desk_config()` - the path whose whole
argument is that a measurement and a deployment are the same desks - could not
run at all, and every backtest on this desk has been a `BacktestEngine` driven
by hand over a generated feed. Two separate agents reached that wall on the
same afternoon and both had to invent a feed to get past it.

## What is real here and what is not

**The bars are real.** `.data/prices/prices.db` is what the retired `prices`
collector wrote: 485,046 bars at 15m across its feeds, recorded per venue, and
`ts` in whole seconds. Nothing is interpolated and nothing is filled.

**The quotes are modelled, and this is the part to be careful about.** The
store's `quotes` table is too sparse to replay - 866 Deriv eurusd quotes across
37 days, one every hour - so one quote is derived per bar: the bar's own close,
straddled by half the **measured median spread for that feed on that venue**.
The spread is a measurement; its constancy is not. Real spreads widen into news
and into the close, and this desk has already costed that: `Envelope
.quiet_hours` exists because the widest hours carried 45% of a loss. A run over
these quotes therefore understates cost in exactly the hours that matter most.

**The instrument conventions are Nautilus's standard ones, not the broker's.**
Without the terminal's `symbol_info` there is no tick value to be had, so an FX
pair is quantity in units of the base currency and everything else is a `Cfd`
at **one unit of the underlying, not a broker lot**. R is scale-free and money
is not: a trade count, a win rate, an R distribution and a stop-out share are
unaffected, and any figure in account currency is this catalogue's.

**R was not scale-free while a contract size was asserted.** Nautilus's `Cfd`
takes no `multiplier`, so stating gold's 100 ounces to the sizer and not to the
engine made every gold R a hundredth of its size - see `CONTRACTS`. And both
fee fields are zero here: the FX test provider's 0.00002 is a 2 bp commission
worth 0.019R a trade at the `N20` stop, which gold never paid, so the feeds'
R were not comparable with each other either.

## What the local store can and cannot support

Per venue, for `eurusd` on `DERIV`: 5,135 bars at 15m spanning **76 days**, and
3,979 at 1m spanning **5.8 days**. So a 15m rule gets about two and a half
months and a rule needing minute bars gets under a week.

That is enough to settle a firing rate and not enough to settle a return. At
`smc_bos_c_L50`'s measured 8.5 breaks per instrument-month, 76 days is about
21 trades per instrument - which answers the one question that run left open,
whether "the latest unbroken swing" means one live slot per side (8.5 a month)
or a stack of every unbroken swing (21.2 a month), a factor of 2.5 in trade
count. It is nowhere near the 230 trades a per-trade sd of 2.35R needs for
+0.31R to be two sigma. **A catalogue this size answers mechanics, not edge.**
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Cfd, CurrencyPair, Instrument
from nautilus_trader.model.objects import Currency, Money, Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog

#: Where the retired collector's store sits, relative to the repository.
STORE = Path(".data/prices/prices.db")

#: The desk's feed names as the pair a `CurrencyPair` needs. Only the ones the
#: store actually carries at a tradable interval; a name absent here is built
#: as a CFD, which is what the MT5 provider does for the same reason - see
#: `adapters/mt5/providers.py` on why `trade_calc_mode` and not the symbol.
PAIRS: dict[str, str] = {
    "eurusd": "EUR/USD",
    "gbpusd": "GBP/USD",
    "audusd": "AUD/USD",
    "nzdusd": "NZD/USD",
    "usdjpy": "USD/JPY",
    "usdcad": "USD/CAD",
    "usdchf": "USD/CHF",
    "eurgbp": "EUR/GBP",
    "eurjpy": "EUR/JPY",
    "gbpjpy": "GBP/JPY",
}

#: Price precision for the non-FX instruments, by feed.
#:
#: **The broker's contract size is deliberately not carried here**, and that is
#: a correction. `adapters/mt5/providers.py` names gold at 100 ounces a lot, and
#: this module used to state that as `info={"trade_contract_size": 100.0}` -
#: which `sizes.spec_of` reads and sizes against. Nautilus's `Cfd` takes no
#: `multiplier`, so the engine computed P&L at one unit of quantity per price
#: unit while the sizer had budgeted for a hundred: **every gold R in the
#: catalogue was a hundredth of its true size**, a stop-out reading -0.013R
#: instead of -0.85R, on the one instrument the standing result says carries
#: half the R. Quantity here is therefore one unit of the underlying - ounces
#: for gold - so the sizer and the engine use the same number. It also stops a
#: $25 budget quantising to a 0.02 lot, a 15% rounding error on the risk.
CONTRACTS: dict[str, int] = {
    "gold": 2,
    "silver": 3,
    "btc": 2,
    "eth": 2,
    "spx500": 2,
    "us100": 2,
}

#: Nautilus bar specifications by the store's interval name.
SPECS: dict[str, str] = {
    "1m": "1-MINUTE",
    "5m": "5-MINUTE",
    "15m": "15-MINUTE",
    "1h": "1-HOUR",
    "4h": "4-HOUR",
    "1d": "1-DAY",
}

NANOS = 1_000_000_000

#: The venue whose recorded quotes support a measured spread, per feed.
#:
#: Six feeds and only six have both 15m bars and enough recorded quotes to
#: measure one: gold 2,670, btc 2,682, gbpusd 1,120, eurusd 866, us100 791,
#: spx500 345. `audusd, nzdusd, usdcad, usdchf, usdjpy, eurgbp, eurjpy,
#: gbpjpy, silver, eth, sol` each have about 5,000 15m bars and **two or fewer
#: recorded quotes at any venue**, so `write` skips them rather than invent a
#: spread.
#:
#: **us100 and spx500 are not the venue the live desk trades.** Their best
#: quote coverage is at FOREXCOM and PEPPERSTONE, and the same instrument's
#: recorded spread runs 0.17 to 3.30 bps across venues - a nineteenfold range -
#: so a result on either is a result about that venue's cost and must be
#: reported saying so.
VENUES: dict[str, str] = {
    "eurusd": "DERIV",
    "gbpusd": "DERIV",
    "gold": "DERIV",
    "btc": "DERIV",
    "us100": "FOREXCOM",
    "spx500": "PEPPERSTONE",
}


@dataclass(frozen=True, slots=True)
class Written:
    """What one feed contributed, so a caller can report it rather than guess."""

    instrument_id: str
    bars: int
    quotes: int
    spread_bps: float
    first: int
    last: int

    @property
    def days(self) -> float:
        return (self.last - self.first) / 86_400.0

    def __str__(self) -> str:
        return (
            f"{self.instrument_id}: {self.bars} bars over {self.days:.1f} days, "
            f"{self.quotes} quotes at a modelled {self.spread_bps:.3f} bps"
        )


def spread_bps(con: sqlite3.Connection, feed: str, venue: str) -> float:
    """The median recorded spread for this feed on this venue, in basis points.

    **Per venue, never pooled.** The same instrument's recorded spread runs
    from 0.17 bps at one venue to 3.30 at another, a nineteenfold range, and a
    pooled median is a number that describes none of them.
    `pooled-medians-invert-subgroups` is the recorded lesson and this is a
    textbook instance of it.
    """
    rows = con.execute(
        "select bid, ask from quotes where feed=? and venue=? and bid>0 and ask>bid",
        (feed, venue),
    ).fetchall()
    if not rows:
        return 0.0
    return statistics.median((ask - bid) / ((ask + bid) / 2) * 1e4 for bid, ask in rows)


def instrument_for(feed: str, venue: str) -> Instrument:
    """The instrument a backtest trades this feed as.

    Standard conventions, not the broker's - see the module docstring. A pair
    is Nautilus's FX convention with quantity in base-currency units;
    everything else is a `Cfd`, the split `adapters/mt5/providers.py` makes.

    **Zero fees, and not the test provider's.**
    `TestInstrumentProvider.default_fx_ccy` sets `maker_fee` and `taker_fee` to
    0.00002, a 2 bp commission on notional that no rule measured here charges
    and the Deriv account does not pay. At the `N20` stop it is 0.019R a trade
    - measured at 5.72 USD over 12 eurusd trades and 10.47 over 19 gbpusd -
    charged to the account and **invisible in the R**, because
    `Position.realized_pnl` is read net of nothing. Gold, built below with
    explicit zeros, paid none of it, so the three feeds' R were not comparable.
    """
    where = Venue(venue)
    pair = PAIRS.get(feed)
    if pair is not None:
        base, _, quote = pair.partition("/")
        digits = 3 if quote == "JPY" else 5
        return CurrencyPair(
            instrument_id=InstrumentId(Symbol(pair), where),
            raw_symbol=Symbol(pair),
            base_currency=Currency.from_str(base),
            quote_currency=Currency.from_str(quote),
            price_precision=digits,
            size_precision=0,
            price_increment=Price(10.0**-digits, digits),
            size_increment=Quantity(1, 0),
            lot_size=Quantity(1_000, 0),
            max_quantity=Quantity(10_000_000, 0),
            min_quantity=Quantity(1_000, 0),
            max_notional=Money(50_000_000.0, USD),
            min_notional=Money(1_000.0, USD),
            max_price=None,
            min_price=None,
            margin_init=Decimal("0.03"),
            margin_maint=Decimal("0.03"),
            maker_fee=Decimal("0"),
            taker_fee=Decimal("0"),
            ts_event=0,
            ts_init=0,
        )

    digits = CONTRACTS.get(feed, 2)
    symbol = feed.upper()
    return Cfd(
        instrument_id=InstrumentId(Symbol(symbol), where),
        raw_symbol=Symbol(symbol),
        asset_class=AssetClass.COMMODITY if feed in ("gold", "silver") else AssetClass.INDEX,
        base_currency=None,
        quote_currency=USD,
        price_precision=digits,
        size_precision=2,
        price_increment=Price(10.0**-digits, digits),
        size_increment=Quantity(0.01, 2),
        lot_size=None,
        max_quantity=Quantity(10_000.0, 2),
        min_quantity=Quantity(0.01, 2),
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
        # No `trade_contract_size`: see `CONTRACTS`. `sizes.spec_of` falls back
        # to `instrument.multiplier`, which is the 1 the engine prices with.
        info=None,
    )


def _bar(bar_type: BarType, instrument: Instrument, row: tuple) -> Bar:
    ts, open_, high, low, close, volume = row
    digits = instrument.price_precision
    stamp = int(ts) * NANOS
    return Bar(
        bar_type,
        Price(open_, digits),
        Price(high, digits),
        Price(low, digits),
        Price(close, digits),
        # **The instrument's own size precision, not zero.** Nautilus refuses a
        # bar or a quote whose size precision does not match the instrument's,
        # with `invalid tick.bid_size.precision=0 did not match
        # instrument.size_precision=2` - at the first quote, so a mismatch
        # aborts the whole run rather than degrading it.
        Quantity(volume or 0.0, instrument.size_precision),
        ts_event=stamp,
        ts_init=stamp,
    )


def _quote(instrument: Instrument, close: float, stamp: int, half: float) -> QuoteTick:
    """One quote at the bar's own close, a nanosecond before it.

    **Before, not after, and the choice is not arbitrary.** Nautilus delivers
    in timestamp order, so a quote stamped after the bar would leave the cache
    holding the *previous* bar's quote when `on_bar` fires - a decision priced
    off a quote fifteen minutes stale. A nanosecond earlier means the quote at
    the signal's own moment.

    It is still causal. A bar's close is known when the bar closes, so a quote
    derived from it is not a reading of the future; what it is not is a
    separate observation, and a rule whose entry is specified as the *next*
    bar's open gets this bar's close plus the spread instead.
    """
    digits = instrument.price_precision
    return QuoteTick(
        instrument_id=instrument.id,
        bid_price=Price(close - half, digits),
        ask_price=Price(close + half, digits),
        # One, because the store records no size - at the instrument's own
        # precision, because Nautilus refuses a mismatch outright and aborts
        # the run at the first quote. A backtest's fills are capped by this, so
        # it is a one-unit book at the quoted price, which is pessimistic for a
        # position of any size; the MT5 adapter makes the same placeholder
        # choice live, because an MT5 tick carries no size either.
        bid_size=Quantity(1, instrument.size_precision),
        ask_size=Quantity(1, instrument.size_precision),
        ts_event=stamp - 1,
        ts_init=stamp - 1,
    )


def write(
    feeds: tuple[str, ...],
    *,
    interval: str = "15m",
    venue: str = "DERIV",
    path: Path | None = None,
    store: Path | None = None,
    spread: float | None = None,
    replace: bool = False,
) -> list[Written]:
    """Write the catalogue, and return what went into it.

    `replace` permits writing over a catalogue that already holds these bars;
    without it that is refused, because the write appends.

    `spread` overrides the measured median, in basis points. A feed with no
    recorded quotes and no override is **skipped rather than guessed**: a
    backtest priced off an invented spread is the one result that would look
    like a measurement and not be one.
    """
    from .backtest import catalogue

    spec = SPECS.get(interval)
    if spec is None:
        raise ValueError(
            f"{interval!r} is not an interval the store keeps. Known: {', '.join(SPECS)}."
        )

    where = Path(path) if path is not None else catalogue()
    where.mkdir(parents=True, exist_ok=True)
    book = ParquetDataCatalog(str(where))
    source = Path(store) if store is not None else STORE
    con = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    done: list[Written] = []

    try:
        for feed in feeds:
            bps = spread if spread is not None else spread_bps(con, feed, venue)
            if bps <= 0.0:
                continue
            instrument = instrument_for(feed, venue)
            bar_type = BarType.from_str(f"{instrument.id}-{spec}-LAST-EXTERNAL")
            rows = con.execute(
                "select ts, open, high, low, close, volume from bars "
                "where feed=? and venue=? and interval=? and closed=1 order by ts",
                (feed, venue, interval),
            ).fetchall()
            if not rows:
                continue

            # **A second run would double the bars and say nothing.**
            # `write_data` appends, so re-running this module over a catalogue
            # it has already filled leaves every bar twice - and a backtest
            # over duplicated bars does not fail, it reports a different
            # answer. Refused by default, with the count, because the shape of
            # that bug is a measurement nobody can tell is wrong.
            already = len(book.bars(bar_types=[str(bar_type)]))
            if already and not replace:
                raise FileExistsError(
                    f"{where} already holds {already} bars for {bar_type}. "
                    f"`write_data` appends, so writing again would double them. "
                    f"Pass replace=True, or remove {where} and start again."
                )

            bars = [_bar(bar_type, instrument, row) for row in rows]
            quotes = [
                _quote(instrument, row[4], int(row[0]) * NANOS, row[4] * bps / 1e4 / 2.0)
                for row in rows
            ]
            book.write_data([instrument])
            book.write_data(bars)
            book.write_data(quotes)
            done.append(
                Written(
                    instrument_id=str(instrument.id),
                    bars=len(bars),
                    quotes=len(quotes),
                    spread_bps=bps,
                    first=int(rows[0][0]),
                    last=int(rows[-1][0]),
                )
            )
    finally:
        con.close()
    return done


def main() -> None:
    """Fill the catalogue with what the store has, and say what that was.

    Run as `python -m till_infinity.node.corpus`. Deliberately not a console
    script - `pyproject.toml` declares none, and `tests/test_entrypoints.py`
    holds it that way, because a second way to run the desk is a second thing
    to go stale.
    """
    import os

    feeds = tuple(
        part
        for part in (os.environ.get("CORPUS_FEEDS") or " ".join(VENUES)).replace(",", " ").split()
        if part
    )
    interval = os.environ.get("CORPUS_INTERVAL", "15m")
    forced = os.environ.get("CORPUS_VENUE", "")
    # Grouped by venue, because `VENUES` gives a different one per feed and
    # `write` takes one: a single call at one venue would skip the three feeds
    # whose quotes are recorded elsewhere, and skipping is silent.
    done = []
    for venue in dict.fromkeys(forced or VENUES.get(feed, "DERIV") for feed in feeds):
        chosen = tuple(f for f in feeds if forced or VENUES.get(f, "DERIV") == venue)
        done.extend(write(chosen, interval=interval, venue=venue))
    if not done:
        print(
            f"nothing written: the store has no {interval} bars with recorded quotes "
            f"for {', '.join(feeds)}"
        )
        return
    for row in done:
        print(row)
    print(
        "\nthe bars are recorded; the quotes are one per bar at a measured median "
        "spread, so cost is understated in the hours a spread widens"
    )


if __name__ == "__main__":
    main()
