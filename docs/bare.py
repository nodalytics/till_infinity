"""Does a bare Nautilus engine crash on this data, with none of our code?"""
import os
os.environ.setdefault("LOG_LEVEL", "ERROR")
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

VENUE = Venue("SIM")
EURUSD = TestInstrumentProvider.default_fx_ccy("EUR/USD", VENUE)
BT = BarType.from_str(f"{EURUSD.id}-1-MINUTE-BID-EXTERNAL")
M = 60_000_000_000

engine = BacktestEngine(config=BacktestEngineConfig(trader_id="BARE-001",
    logging=LoggingConfig(log_level="ERROR")))
engine.add_venue(venue=VENUE, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
                 base_currency=USD, starting_balances=[Money(1_000_000, USD)])
engine.add_instrument(EURUSD)

bars, quotes, p, ts = [], [], 1.10000, 0
for _ in range(120):
    p += 0.0002
    bars.append(Bar(BT, Price(p,5), Price(p+0.0003,5), Price(p-0.0003,5), Price(p,5),
                    Quantity(1_000_000,0), ts_event=ts, ts_init=ts))
    quotes.append(QuoteTick(instrument_id=EURUSD.id, bid_price=Price(p-0.00005,5),
                  ask_price=Price(p+0.00005,5), bid_size=Quantity(1_000_000,0),
                  ask_size=Quantity(1_000_000,0), ts_event=ts, ts_init=ts))
    ts += M
engine.add_data(quotes)
engine.add_data(bars)
print("running bare...", flush=True)
engine.run()
print("bare ran clean", flush=True)
engine.dispose()
print("disposed clean", flush=True)
