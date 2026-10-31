# retiring `prices/`

The adapters replace this package, module for module, and when the last row
below is done the directory goes. It is here as a baseline copy because it is
what the replacements have to reproduce - the same reason `statespace` is.

**It cannot go first.** `prices` is what feeds the fold today, so removing it
before its replacements exist stops the desk rather than simplifying it.

| module | what replaces it | state |
| --- | --- | --- |
| `broker.py` | `adapters/mt5` - the bridge over HTTP | **done** |
| `quotes.py` | `adapters/mt5` for the live stream | **done** for MT5 feeds |
| `crypto.py` | native Nautilus adapters: Binance, Bybit, OKX, Kraken, Coinbase, Deribit, dYdX, Hyperliquid. **None need API keys for public data** - verified, `api_key=None` constructs. ccxt stays for *discovery* across the long tail of venues, where Nautilus covers ten and ccxt covers a hundred. | to do |
| `yahoo.py` | nothing, deliberately. Databento is not free - $125 of one-time credit, then per uncompressed GB. For FX, which is what we trade, `copy_ticks_range` through the bridge is **more** complete than Yahoo and already ours. Yahoo only ever carried daily equity bars for research, and it is where the 1,187 malformed bars came from, so it stays in research behind the validity filter. | keep, in research |
| `options.py` | the Deribit adapter, marked Stable, and we already have our own Deribit recordings to check it against | to do |
| `funding.py` | native: `_subscribe_funding_rates` is on the data-client interface for perp venues | to do |
| `tradingview.py` | a data client publishing a custom *signal* type. TradingView has no redistributable market data, so it cannot be a price feed - what it offers is alerts and webhooks, and Nautilus has no equivalent for that. | to do |
| `positioning.py` | nothing. COT-style positioning has no Nautilus adapter; it moves to a data client of its own or into research. | to do |
| `spreads.py` | `actors/spread.py` for the rolling measure. The rest - per-instrument cost tables - has no equivalent and needs a home. | partly |
| `store.py` | Nautilus's `ParquetDataCatalog`, which is also what `services/ticks` should write into | to do |
| `symbols.py` | `adapters/mt5/providers.py` - an `InstrumentProvider` built from the terminal's own `digits` and `volume_step` | **done** for MT5 |
| `models.py` | Nautilus `Bar`, `QuoteTick`, `Instrument` | to do |
| `service.py`, `config.py`, `source.py` | the node's config and the clients' own lifecycles | to do |

## The bar validity filter is transitional

`Bar.defects()` and `drop_unsound()` exist because the legacy loaders accept
bars that contradict themselves. **Nautilus already refuses such a bar** -
that is how the 1,187 were found, by a `ValueError: low was > open` during the
statespace spike. So the filter protects the *old* path, and when `models.py`
goes it goes with it.

What should not be lost with it is the finding: a close outside `[low, high]`
on 0.3 to 0.8% of daily bars per FX feed, none intraday, from an adjusted
close carried against unadjusted highs and lows. `drive-q-from-the-range` is a
range-versus-close estimator ratio reported on FX dailies, and that is exactly
the quantity those bars break.
