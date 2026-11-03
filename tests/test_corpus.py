"""Filling the backtest catalogue, and the silent zero that hid behind it.

`node/backtest.catalogue()` has pointed at a `ParquetDataCatalog` since the
port and **nothing ever wrote one**, so `BacktestNode` and `desk_config()` -
the path whose whole argument is that a measurement and a deployment are the
same desks - could not run. Two agents hit that wall on one afternoon and both
invented a feed to get past it.

Writing one exposed a second defect that would have spoiled every run through
this module even with data present. `BacktestDataConfig` **appends the
aggregation source itself**, so a `bar_spec` that already carries one resolves
to `...-EXTERNAL-EXTERNAL`, a bar type that exists nowhere. The query returns
nothing, the engine runs to completion, and the result prints
`PnL (total): 0.0` with every other statistic `nan`. No exception, no warning,
`total_orders` zero. `run_config`'s own default was `1-MINUTE-LAST-EXTERNAL`,
so the defect was in the default, and it survived precisely because the
catalogue was empty: a run that found no bars looked exactly like a run with
no data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from till_infinity.node import backtest, corpus


def store(path: Path, bars: int = 300, feed: str = "eurusd", venue: str = "DERIV") -> Path:
    """A price store in the shape the retired collector wrote, with `ts` in
    whole seconds - which is what the real one uses and is easy to get wrong,
    because the `quotes` table in the same file is in milliseconds."""
    db = path / "prices.db"
    con = sqlite3.connect(db)
    con.execute(
        "create table bars (source text, feed text, venue text, ticker text, interval text, "
        "ts integer, open real, high real, low real, close real, volume real, closed integer)"
    )
    con.execute(
        "create table quotes (source text, feed text, venue text, ticker text, ts integer, "
        "bid real, ask real, last real)"
    )
    start = 1_780_000_000
    for i in range(bars):
        price = 1.10 + i * 1e-05
        con.execute(
            "insert into bars values ('tv',?,?,'x','15m',?,?,?,?,?,100.0,1)",
            (feed, venue, start + i * 900, price, price + 2e-05, price - 2e-05, price),
        )
    for i in range(40):
        con.execute(
            "insert into quotes values ('tv',?,?,'x',?,?,?,0.0)",
            (feed, venue, (start + i * 900) * 1000, 1.10 - 0.00005, 1.10 + 0.00005),
        )
    con.commit()
    con.close()
    return db


# ------------------------------------------------------- the duplicated source


@pytest.mark.parametrize(
    ("given", "wanted"),
    [
        ("15-MINUTE-LAST-EXTERNAL", "15-MINUTE-LAST"),
        ("1-MINUTE-LAST-EXTERNAL", "1-MINUTE-LAST"),
        ("15-MINUTE-MID-INTERNAL", "15-MINUTE-MID"),
        ("15-MINUTE-LAST", "15-MINUTE-LAST"),
    ],
)
def test_the_aggregation_source_is_stripped_before_the_query(given, wanted):
    """**Nautilus appends it, so passing one duplicates it.** Callers keep
    handing over a full bar type, because that is what a desk subscribes to and
    `node/desks.bar_type` builds one; the stripping happens once, here."""
    assert backtest.specification(given) == wanted


def test_the_query_names_a_bar_type_that_could_exist(monkeypatch, tmp_path):
    """The assertion the unit test above cannot make: what the data config
    actually asks the catalogue for. `...-EXTERNAL-EXTERNAL` is not a bar type
    any catalogue can hold, and asking for it is silent."""
    monkeypatch.setenv("CORPUS_DIR", str(tmp_path))
    found = backtest.data("EUR/USD.DERIV", "15-MINUTE-LAST-EXTERNAL")
    bars = found[0].query["identifiers"]
    assert bars == ["EUR/USD.DERIV-15-MINUTE-LAST-EXTERNAL"]
    assert not any(name.count("EXTERNAL") > 1 for name in bars)


# ------------------------------------------------------------- what is written


def test_the_catalogue_is_written_and_reads_back(monkeypatch, tmp_path):
    """End to end over a store in the real shape. A catalogue that writes and
    cannot be read back is the failure mode a round trip catches and a write
    alone does not."""
    db = store(tmp_path)
    monkeypatch.setenv("CORPUS_DIR", str(tmp_path / "catalog"))
    done = corpus.write(("eurusd",), store=db)

    assert len(done) == 1
    assert done[0].instrument_id == "EUR/USD.DERIV"
    assert done[0].bars == 300
    assert done[0].quotes == 300, "one quote a bar, since the store's own are too sparse"
    assert done[0].spread_bps == pytest.approx(0.909, abs=0.01)

    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    book = ParquetDataCatalog(str(tmp_path / "catalog"))
    assert [str(i.id) for i in book.instruments()] == ["EUR/USD.DERIV"]
    assert len(book.bars(bar_types=["EUR/USD.DERIV-15-MINUTE-LAST-EXTERNAL"])) == 300


def test_the_quote_sits_a_nanosecond_before_its_bar(monkeypatch, tmp_path):
    """**Before, not after.** Nautilus delivers in timestamp order, so a quote
    stamped after the bar leaves the cache holding the *previous* bar's quote
    when `on_bar` fires - a decision priced off a quote fifteen minutes stale,
    and `Desk._undealable` would refuse the first signal of every run at
    `no-quote`."""
    db = store(tmp_path, bars=10)
    monkeypatch.setenv("CORPUS_DIR", str(tmp_path / "catalog"))
    corpus.write(("eurusd",), store=db)

    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    book = ParquetDataCatalog(str(tmp_path / "catalog"))
    bars = book.bars(bar_types=["EUR/USD.DERIV-15-MINUTE-LAST-EXTERNAL"])
    quotes = book.query(QuoteTick, identifiers=["EUR/USD.DERIV"])
    assert quotes[0].ts_event == bars[0].ts_event - 1
    # And the quote straddles that bar's own close, which is known when the bar
    # closes - so it is modelled, not forward-looking.
    middle = (float(quotes[0].bid_price) + float(quotes[0].ask_price)) / 2
    assert middle == pytest.approx(float(bars[0].close), abs=1e-06)


def test_a_second_write_is_refused_rather_than_doubling_the_bars(monkeypatch, tmp_path):
    """`write_data` appends. A backtest over duplicated bars does not fail, it
    reports a different answer - which is the one shape of bug nobody can see."""
    db = store(tmp_path, bars=20)
    monkeypatch.setenv("CORPUS_DIR", str(tmp_path / "catalog"))
    corpus.write(("eurusd",), store=db)
    with pytest.raises(FileExistsError, match="would double"):
        corpus.write(("eurusd",), store=db)


def test_a_feed_with_no_recorded_spread_is_skipped_rather_than_guessed(monkeypatch, tmp_path):
    """A backtest priced off an invented spread is the one result that would
    look like a measurement and not be one. The cost gate is the gate that
    decides these rules, so the spread is not a detail."""
    db = store(tmp_path, bars=20, feed="gbpusd")
    monkeypatch.setenv("CORPUS_DIR", str(tmp_path / "catalog"))
    assert corpus.write(("eurusd",), store=db) == []
    assert corpus.write(("gbpusd",), store=db, spread=1.0)[0].bars == 20


def test_the_spread_is_measured_per_venue_and_never_pooled(tmp_path):
    """The same instrument's recorded spread runs from 0.17 bps at one venue to
    3.30 at another, a nineteenfold range, so a pooled median describes none of
    them - and which venue a rule runs on decides whether its cost gate binds
    at all."""
    db = store(tmp_path, bars=5)
    con = sqlite3.connect(db)
    con.execute(
        "insert into quotes values ('tv','eurusd','OANDA','x',1780000000000,1.0997,1.1003,0.0)"
    )
    con.commit()
    assert corpus.spread_bps(con, "eurusd", "DERIV") == pytest.approx(0.909, abs=0.01)
    assert corpus.spread_bps(con, "eurusd", "OANDA") == pytest.approx(5.45, abs=0.05)
    assert corpus.spread_bps(con, "eurusd", "SAXO") == 0.0
    con.close()


def test_the_sizes_carry_the_instruments_own_precision(tmp_path, monkeypatch):
    """Nautilus refuses a mismatch outright - `invalid tick.bid_size
    .precision=0 did not match instrument.size_precision=2` - and it refuses it
    at the first quote, so the whole run aborts rather than degrading."""
    db = store(tmp_path, bars=10, feed="gold")
    monkeypatch.setenv("CORPUS_DIR", str(tmp_path / "catalog"))
    corpus.write(("gold",), store=db, spread=1.0)

    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    book = ParquetDataCatalog(str(tmp_path / "catalog"))
    instrument = book.instruments()[0]
    quotes = book.query(QuoteTick, identifiers=["GOLD.DERIV"])
    assert quotes[0].bid_size.precision == instrument.size_precision
    assert book.bars(bar_types=["GOLD.DERIV-15-MINUTE-LAST-EXTERNAL"])[0].volume.precision == (
        instrument.size_precision
    )


# ------------------------------------------------- the counts the result reports


def test_the_run_keeps_the_state_its_trade_counts_are_computed_from():
    """**A disposed engine reports zero trades on a run that traded.**

    `BacktestNode._run` calls `engine.dispose()` - "drop data and all state" -
    and *then* `engine.get_result()`, whose `total_orders` is
    `cache.orders_total_count()` and whose `total_positions` counts
    `cache.positions()`. Both read the cache that was just emptied, so the
    result says 0 and 0 however much the run did.

    `stats_pnls` is computed off the portfolio analyzer instead of the cache,
    so it survives - which is what made this expensive to find. One run
    reported `PnL (total): -62.32` at a 0.25 win rate beside `total_orders =
    0`, and a sweep reading the counts called it a cell that never traded.
    That is how `research/ideas/leaf_sweep.py` reported 0 of 72 cells, and it
    was first mis-diagnosed as a `BacktestDataConfig` bar-type fault - the
    data config was resolving and loading correctly the whole time.

    Nautilus's default is `True`, so this has to be set on every config this
    module builds rather than relied on.
    """
    config = backtest.run_config("EUR/USD.DERIV", "15-MINUTE-LAST-EXTERNAL")
    assert config.dispose_on_completion is False


def test_a_desk_run_reports_counts_as_well_as_a_pnl(monkeypatch):
    """The control for the test above: that the flag is wired to a config a
    desk actually runs, not just to `run_config`'s own default. Without it the
    counts here are 0 while the PnL is unchanged, which is the exact pairing
    that reads as "nothing traded"."""
    monkeypatch.setenv("TRADING_SYMBOLS", "EUR/USD")
    config = backtest.desk_config("EUR/USD.DERIV", "15-MINUTE-LAST-EXTERNAL")
    assert config.dispose_on_completion is False
