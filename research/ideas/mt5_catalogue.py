"""Build a Nautilus catalogue from bars pulled off the live MT5 terminal.

`node/corpus.py` fills a catalogue from the retired collector's store, which
holds **6.5 days** of 5-minute bars for three of the five feeds this rule
trades. That is not a sample, and it is why `dual_engine_timeframes.py` had to
report "execution below 15m is not testable here" as an absence rather than a
result.

The terminal itself holds far more. Pulled through the bridge's
`/symbols/rates/pos` with `MT5_MAX_BARS=1000000`, 90,000 M5 bars per symbol is
**442 days** on all five - EURUSD, GBPUSD, XAUUSD, USDJPY and AUDUSD - against
321 days of hourly bars and 76-86 days of 15-minute ones from the store.

## Where the numbers come from, and what they are not

* **The bars are the broker's own**, from the account this desk trades, rather
  than a third-party mirror. They are also the broker's *bid* series, which is
  what MT5 serves: the ask side is modelled from the recorded spread below, and
  is not a second observation.
* **The spread is each bar's own recorded spread, in points**, taken as a
  median per feed and converted to price through the instrument's price
  increment. `spread-column-is-in-points` is a measured error here - reading
  that column as a price gave EURUSD a 476% round trip and reordered every
  instrument by cost - so the conversion is explicit and the bps figure is
  printed for each feed to be sanity-checked against the store's own.
* **One quote per bar**, straddling the bar's own close by half the median
  spread, stamped a nanosecond before the bar. That is `corpus._quote`, reused
  rather than re-derived, including its one-unit book - which is pessimistic
  for a position of any size and is the reason a market order larger than one
  unit fills across the bar rather than at the quote.
* **It is still a modelled cost.** A median spread is a measurement; its
  constancy is not. Real spreads widen into news and at the session roll, and
  nothing here reproduces that, so cost is understated exactly where it is
  worst.

Written into a catalogue of its own rather than beside the store's, because the
venue differs - these are the live broker's bars and the store's are DERIV's -
and a backtest that silently mixed two venues' prices for one feed would be
measuring the join.

Run it as `uv run python research/ideas/mt5_catalogue.py`.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import statistics
from pathlib import Path

from nautilus_trader.model.data import BarType
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from till_infinity.node.corpus import SPECS, _bar, _quote, instrument_for

#: Where the pull leaves its files. Gitignored: candle history from the desk's
#: own broker stays out of a public repository.
BARS = Path(".secrets/broker/mt5-bars")

#: Where the catalogue goes.
INTO = Path.home() / "till-data" / "mt5"

#: The terminal's symbol against this repository's feed name. `gold` rather
#: than `xauusd` because `corpus.CONTRACTS` and every study already say gold,
#: and a second name for one instrument is how two results stop comparing.
FEEDS: dict[str, str] = {
    "EURUSD": "eurusd",
    "GBPUSD": "gbpusd",
    "XAUUSD": "gold",
    "USDJPY": "usdjpy",
    "AUDUSD": "audusd",
}

#: The venue these came from. **Not DERIV**: the store's bars are DERIV's and
#: these are the live broker's, and one feed with two venues' prices in one
#: catalogue would make a backtest a measurement of the join.
VENUE = "MT5"

NANOS = 1_000_000_000


def rows(path: Path) -> list[tuple[int, float, float, float, float, float, float]]:
    """One file's bars as `(ts, open, high, low, close, volume, spread_points)`."""
    out = []
    with gzip.open(path, "rt") as handle:
        for row in csv.DictReader(handle):
            stamp = dt.datetime.fromisoformat(row["time"])
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=dt.UTC)
            out.append(
                (
                    int(stamp.timestamp()),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row.get("tick_volume") or 0.0),
                    float(row.get("spread") or 0.0),
                )
            )
    out.sort(key=lambda r: r[0])
    return out


def build(bars: Path, into: Path, interval: str = "5m") -> None:
    spec = SPECS[interval]
    book = ParquetDataCatalog(str(into))
    for symbol, feed in FEEDS.items():
        path = bars / f"{symbol}_M5.csv.gz"
        if not path.exists():
            print(f"  {symbol}: no file at {path} - skipped")
            continue
        found = rows(path)
        if not found:
            print(f"  {symbol}: empty - skipped")
            continue
        instrument = instrument_for(feed, VENUE)
        bar_type = BarType.from_str(f"{instrument.id}-{spec}-LAST-EXTERNAL")

        # **Points to price, through the instrument's own increment.** Reading
        # the column as a price is a measured error in this repository.
        points = [r[6] for r in found if r[6] > 0]
        median_points = statistics.median(points) if points else 0.0
        increment = float(instrument.price_increment)
        spread = median_points * increment
        if spread <= 0:
            print(f"  {symbol}: no recorded spread - skipped rather than guessed")
            continue
        half = spread / 2.0
        mid = statistics.median([r[4] for r in found])

        built_bars = [_bar(bar_type, instrument, r[:6]) for r in found]
        built_quotes = [_quote(instrument, r[4], r[0] * NANOS, half) for r in found]
        book.write_data([instrument])
        book.write_data(built_bars)
        book.write_data(built_quotes)
        span = (found[-1][0] - found[0][0]) / 86_400.0
        print(
            f"  {instrument.id}: {len(built_bars)} bars over {span:.1f} days, "
            f"{len(built_quotes)} quotes at a modelled {spread / mid * 10_000:.3f} bps "
            f"({median_points:.1f} points)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", default=str(BARS))
    parser.add_argument("--into", default=str(INTO))
    parser.add_argument("--interval", default="5m")
    args = parser.parse_args()
    print(f"from {args.bars} -> {args.into}")
    build(Path(args.bars), Path(args.into), args.interval)
    print(
        "\nthe bars are the broker's own bid series; the ask is modelled from the "
        "recorded spread, so cost is understated in the hours a spread widens"
    )


if __name__ == "__main__":
    main()
