"""Command line entry point."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import click
from rich.table import Table

from . import prices as px
from .logging import console, setup_logging

T = TypeVar("T")


def run(coro: Coroutine[Any, Any, T]) -> T:
    """Run `coro`, preferring uvloop when it is installed."""
    try:
        import uvloop
    except ImportError:
        return asyncio.run(coro)
    with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
        return runner.run(coro)


def _stamp(value: int | None) -> str:
    if not value:
        return "-"
    return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%d %H:%M")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="till-infinity")
def main() -> None:
    """till-infinity."""


@main.group()
def prices() -> None:
    """Fetch and store OHLCV candles."""


def _common(quotes: bool = False):
    """Options shared by backfill, bars and quotes.

    `quotes` drops the two bar-only options: a quote has no interval, and there
    is no such thing as a partial one.
    """
    source_help = (
        f"Transport; repeatable. Default: {', '.join(px.DEFAULT_QUOTE_SOURCES)}."
        if quotes
        else "Provider; repeatable. Default: all."
    )
    bar_options = [
        click.option(
            "--interval", "-i", multiple=True, help="Interval name; repeatable. Default: all."
        ),
        click.option(
            "--include-partial",
            is_flag=True,
            help="Also store the still-forming bar (SQLite corrects it later; JSONL cannot).",
        ),
    ]
    options = [
        click.option(
            "--symbol",
            "-s",
            multiple=True,
            metavar="SYMBOL",
            help=(
                "Instrument (gold, btc, eurusd, gbpusd), VENUE:TICKER "
                "(OANDA:XAUUSD) or a bare Yahoo ticker (AAPL); repeatable. "
                "Default: eurusd, gbpusd, gold, btc."
            ),
        ),
        *([] if quotes else bar_options[:1]),
        click.option(
            "--source",
            "-S",
            multiple=True,
            type=click.Choice(sorted(px.QUOTE_SOURCES if quotes else px.SOURCES)),
            help=source_help,
        ),
        click.option(
            "--store",
            "store_kind",
            default="sqlite",
            type=click.Choice(["sqlite", "jsonl", "both"]),
            show_default=True,
        ),
        click.option("--db", type=click.Path(path_type=Path), help="SQLite file."),
        click.option("--dir", "data_dir", type=click.Path(path_type=Path), help="JSONL root."),
        *([] if quotes else bar_options[1:]),
        click.option("-v", "--verbose", is_flag=True, help="Debug logging."),
        click.option("-q", "--quiet", is_flag=True, help="Warnings and errors only."),
        click.option(
            "--log-file",
            type=click.Path(path_type=Path),
            help="Also write JSON-lines logs here (rotated).",
        ),
    ]

    def decorate(func):
        for option in reversed(options):
            func = option(func)
        return func

    return decorate


def _settings(db: Path | None, data_dir: Path | None, include_partial: bool) -> px.Settings:
    settings = px.Settings.from_env()
    if data_dir is not None:
        settings.data_dir = Path(data_dir)
        if db is None:
            settings.database = settings.data_dir / "prices.db"
    if db is not None:
        settings.database = Path(db)
    settings.include_partial = include_partial
    return settings


def _report(result: px.JobResult) -> None:
    if result.ok:
        console.print(
            f"  [green]✓[/] {result.job.source:12} {result.job.symbol.full:22}"
            f" +{result.result.inserted} new, {result.result.updated} updated"
        )
    else:
        console.print(
            f"  [red]✗[/] {result.job.source:12} {result.job.symbol.full:22} {result.error}"
        )


@prices.command()
@_common()
@click.option("--bars", type=int, help="Bars to pull per series. Default: PRICES_BACKFILL_BARS.")
def backfill(
    symbol,
    interval,
    source,
    store_kind,
    db,
    data_dir,
    include_partial,
    verbose,
    quiet,
    log_file,
    bars,
):
    """One-time deep history pull per source x symbol x interval."""
    setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)
    settings = _settings(db, data_dir, include_partial)
    feeds = px.resolve_symbols(symbol or None)
    intervals = px.resolve_intervals(interval or None)

    async def go() -> None:
        store = px.open_store(store_kind, database=settings.database, data_dir=settings.data_dir)
        async with store:
            summary = await px.backfill(
                settings=settings,
                store=store,
                feeds=feeds,
                intervals=intervals,
                sources=source or None,
                bars=bars,
                on_done=_report,
            )
        console.print(f"[bold]backfill:[/] {summary}")

    run(go())


@prices.command("bars")
@_common()
@click.option("--bars", type=int, help="Bars to request per pass. Default: PRICES_LIVE_BARS.")
@click.option("--cycle", type=float, help="Seconds between passes. Default: PRICES_CYCLE_S.")
@click.option("--once", is_flag=True, help="Run a single pass and exit.")
def bars_command(
    symbol,
    interval,
    source,
    store_kind,
    db,
    data_dir,
    include_partial,
    verbose,
    quiet,
    log_file,
    bars,
    cycle,
    once,
):
    """Keep candles current — sweep for newly closed bars, forever."""
    setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)
    settings = _settings(db, data_dir, include_partial)
    if cycle is not None:
        settings.cycle_seconds = cycle
    feeds = px.resolve_symbols(symbol or None)
    intervals = px.resolve_intervals(interval or None)

    def cycle_done(index: int, summary: px.Summary) -> None:
        console.print(f"[bold]cycle {index}:[/] {summary}")

    async def go() -> None:
        store = px.open_store(store_kind, database=settings.database, data_dir=settings.data_dir)
        async with store:
            await px.collect(
                settings=settings,
                store=store,
                feeds=feeds,
                intervals=intervals,
                sources=source or None,
                bars=bars,
                cycles=1 if once else None,
                on_cycle=cycle_done,
                on_done=_report if verbose else None,
            )

    try:
        run(go())
    except KeyboardInterrupt:
        console.print("stopped")


@prices.command()
@click.option(
    "--store",
    "store_kind",
    default="sqlite",
    type=click.Choice(["sqlite", "jsonl"]),
    show_default=True,
)
@click.option("--db", type=click.Path(path_type=Path))
@click.option("--dir", "data_dir", type=click.Path(path_type=Path))
def info(store_kind, db, data_dir):
    """Show what is stored: series, bar counts and coverage."""
    settings = _settings(db, data_dir, include_partial=False)

    async def go() -> list[px.SeriesInfo]:
        store = px.open_store(store_kind, database=settings.database, data_dir=settings.data_dir)
        async with store:
            return await store.series()

    rows = run(go())
    if not rows:
        console.print("no data stored yet")
        return

    target = settings.database if store_kind == "sqlite" else settings.data_dir
    table = Table(title=f"{store_kind}: {target}")
    for column in ("source", "feed", "symbol", "tf", "bars", "from", "to"):
        table.add_column(column, justify="right" if column == "bars" else "left")
    for row in rows:
        table.add_row(
            row.key.source,
            row.key.feed,
            row.key.symbol.full,
            row.key.interval,
            f"{row.bars:,}",
            _stamp(row.first_time),
            _stamp(row.last_time),
        )
    console.print(table)
    console.print(f"{len(rows)} series, {sum(r.bars for r in rows):,} bars")


@prices.command()
@_common(quotes=True)
@click.option(
    "--poll",
    type=float,
    help=(
        "Seconds between summary lines. The socket source streams — it writes on "
        "every update regardless; only the scanner and yahoo re-fetch on this "
        "interval. Default: PRICES_QUOTE_POLL (15)."
    ),
)
@click.option("--once", is_flag=True, help="Take one snapshot and exit.")
@click.option("--all-ticks", is_flag=True, help="Store every update, not just price changes.")
def quotes(
    symbol,
    source,
    store_kind,
    db,
    data_dir,
    verbose,
    quiet,
    log_file,
    poll,
    once,
    all_ticks,
):
    """Stream live bid/ask across brokers — cross-broker spread and lead-lag."""
    setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)
    settings = _settings(db, data_dir, include_partial=False)
    if poll is not None:
        settings.quote_poll_seconds = poll
    feeds = px.resolve_symbols(symbol or None)

    def show(index: int, tick: px.QuoteTick) -> None:
        if once:
            _quote_table(tick)
        else:
            console.print(f"[bold]tick {index}:[/] {tick}")

    async def go() -> None:
        store = px.open_store(
            store_kind,
            database=settings.database,
            data_dir=settings.data_dir,
            dedupe_quotes=not all_ticks,
        )
        async with store:
            await px.stream(
                settings=settings,
                feeds=feeds,
                sink=store.write_quote,
                sources=source or None,
                ticks=1 if once else None,
                on_tick=show,
            )

    try:
        run(go())
    except KeyboardInterrupt:
        console.print("stopped")


def _quote_table(tick: px.QuoteTick) -> None:
    table = Table(title="top of book, tightest spread first")
    for column in ("feed", "broker", "bid", "ask", "mid", "spread", "bps"):
        table.add_column(column, justify="left" if column in ("feed", "broker") else "right")
    for feed in dict.fromkeys(key.feed for key in tick.quotes):
        for key, quote in tick.by_feed(feed):
            table.add_row(
                feed,
                key.symbol.venue,
                _price(quote.bid),
                _price(quote.ask),
                _price(quote.mid),
                _price(quote.spread),
                "-" if quote.spread_bps is None else f"{quote.spread_bps:.2f}",
            )
    console.print(table)
    console.print(str(tick))


def _price(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.5f}" if abs(value) < 100 else f"{value:,.2f}"


@prices.command()
@click.argument("names", nargs=-1)
def symbols(names):
    """Show what -s resolves to. With no argument, show the tracked instruments."""
    table = Table()
    for column in ("instrument", "source", "symbols"):
        table.add_column(column)
    for feed in px.resolve_symbols(names or None):
        for source_name, syms in feed.symbols.items():
            if syms:
                table.add_row(feed.name, source_name, ", ".join(s.full for s in syms))
    console.print(table)
    if not names:
        console.print("defaults: " + ", ".join(px.DEFAULT_SYMBOLS))
        console.print("aliases: " + ", ".join(sorted(px.SYMBOL_ALIASES)))
        console.print("anything else works too: -s OANDA:XAUUSD, -s AAPL, -s YAHOO:GC=F")
    console.print("intervals: " + ", ".join(px.INTERVALS))


if __name__ == "__main__":  # pragma: no cover
    main()
