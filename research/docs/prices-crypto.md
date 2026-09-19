# Prices Crypto

Rationale moved out of `till_infinity/prices/crypto.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `CcxtSource._top_of_book`

        **`fetch_tickers` does not carry them here.** Binance answers it from
        the 24h statistics endpoint, which has no top of book: all 762 swap
        rows came back `bid=0, ask=0`, and since `spread_share` reports 0.0
        when it cannot be computed, `max_spread` could not reject a single
        pair at any threshold - 1e-9 dropped none of them. The filter was
        decorative. `fetch_bids_asks` is the bookTicker endpoint and returns
        all 762 populated.

        Best-effort: an exchange without it keeps the old behaviour, where an
        unknown spread costs a pair nothing.


## `CcxtSource._markets`

        Two fields from one call. `created` fills `listed_days`, which was
        never assigned anywhere in this module - the field existed, defaulted
        to 0.0, and `min_days` was written to skip a zero reading, so a
        10,000-day threshold rejected nothing.

        `contractSize` is here because **okx reports no `quoteVolume` at all**
        - None on all 470 of its swaps - so `min_volume` rejected every pair it
        listed and one of the largest perpetual venues contributed nothing to
        the board, silently. Its `baseVolume` is in *contracts*, and a contract
        is not a coin: BTC-USDT-SWAP is 0.01 BTC, so multiplying the raw count
        by the price overstates the notional a hundredfold. This is the same
        unit trap `positioning.py` documents for open interest, on a different
        field.


## `discover_ccxt`

    **Ranked across the exchanges, not within them.** One venue's board is one
    venue's opinion of what is liquid; the desk wants the pairs that are liquid
    *in the market*, which is the same reason gold is quoted from six venues
    and not from whichever one answered first. So the quality filters run per
    exchange - a pair that is wide or dead or newly listed *there* is dropped
    from *there* - and the volume ranking is then taken over the summed volume
    of what survives.

    The cut is applied last, once, globally. Applying `top` per exchange and
    then merging would give the union of several top-250s, which is neither 250
    pairs nor the 250 largest.

    Returns pair -> the exchanges carrying it, busiest first, so a feed's
    symbols are ordered the way the TradingView feeds are.


