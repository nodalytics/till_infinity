# Prices Config

Rationale moved out of `till_infinity/prices/config.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `broker_feeds`

    The point of these is the instruments no consensus venue quotes -
    synthetics above all, which have no underlying and so no other source by
    construction. Without a feed they cannot be traded here at all, because
    `structures` builds levels out of quotes and there are none.

    The broker's own name is the symbol, verbatim: `Volatility 75 Index`, not a
    guess at what it might be called elsewhere. The feed name is a slug of it,
    because feed names travel through journal keys and log lines where spaces
    are a nuisance. Nothing is resolved or probed here - a name the broker does
    not carry simply never quotes, and `_note_unavailable` says so once.


## `register_broker_feeds`

    Called at start-up from `PRICES_BROKER_SYMBOLS`, so a synthetic named there
    becomes an ordinary feed that everything downstream - quotes, storage,
    levels, signals - handles without knowing it came from anywhere unusual.

    Mutating the module catalogue is deliberate. `FEEDS` is what `resolve_feeds`
    and every alias lookup read, and a parallel registry would be a second
    place for a feed to exist and a second place to forget to look.


## `ccxt_feeds`

    Takes pair -> the exchanges carrying it, so a pair listed on three of them
    becomes **one feed with three symbols** - exactly the shape a TradingView
    instrument has, and for the same reason: the consensus layer downstream
    compares venues against each other and cannot do that with one.

    The venue on each symbol is the exchange name, which is what
    `CcxtSource.fetch` reads to know who to ask. The ccxt pair is kept verbatim
    - `BTC/USDT:USDT` is what `fetch_ohlcv` answers to - and the slug
    (`btc_usdt_usdt`) is what journal keys and log lines carry, where slashes
    and colons are a nuisance.

    A bare sequence of pairs is still accepted and means "one exchange, the
    configured one".


## `bar_source_names`

    `PRICES_SOURCES` if set, otherwise the default - plus `broker` whenever
    broker-only feeds are registered, for the same reason the quote list gets
    it: nothing else carries them.

    Quotes alone are not enough. `structures` builds levels from **bars**, so a
    synthetic with a live price and no candles produces no level, no signal and
    no trade. Nine of them collected 1,271 quotes each and zero bars, which
    reads as a slow warm-up and is not one.


## `resolve_symbols`

    Three forms are accepted, and they mix freely:

    * a tracked instrument - ``gold``, ``xauusd``, ``btc``, ``eurusd`` - which
      brings along every broker configured for it;
    * ``VENUE:TICKER`` (``OANDA:XAUUSD``, ``YAHOO:GC=F``) for one exact series;
    * a bare ticker (``AAPL``, ``BTC-USD``), which goes to Yahoo - TradingView
      needs the venue to resolve a symbol.

    With nothing passed, every feed in `DEFAULT_SYMBOLS` is tracked.


