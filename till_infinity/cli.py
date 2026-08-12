"""Command line entry point."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import click
from rich.markup import escape
from rich.table import Table

from . import news as nw
from . import notifications as nt
from . import prices as px
from .bus import Bus
from .logging import console, get_logger, setup_logging

log = get_logger(__name__)
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


publish_option = click.option(
    "--publish",
    metavar="REDIS_URL",
    is_flag=False,
    flag_value="",
    default=None,
    help=(
        "Publish to the message bus so other services can consume. "
        "Give a redis:// URL to reach another process; bare --publish uses "
        "TILL_REDIS_URL, or an in-process bus when that is unset."
    ),
)


def _bus(publish: str | None) -> Bus | None:
    """Build the bus a collector announces on, or None if nobody asked for one.

    An in-process bus with no subscriber is a no-op, which is why this returns
    None unless `--publish` was given: the seam should cost nothing by default.
    """
    if publish is None:
        return None
    url = publish or os.environ.get("TILL_REDIS_URL") or None
    bus = Bus(redis_url=url)
    log.info("publishing to the %s bus", bus.backend)
    return bus


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
@publish_option
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
    publish,
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
        bus = _bus(publish)
        try:
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
                    bus=bus,
                )
        finally:
            if bus is not None:
                await bus.close()

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
@publish_option
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
    publish,
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
        bus = _bus(publish)
        try:
            async with store:
                await px.stream(
                    settings=settings,
                    feeds=feeds,
                    sink=store.write_quote,
                    sources=source or None,
                    ticks=1 if once else None,
                    on_tick=show,
                    bus=bus,
                )
        finally:
            if bus is not None:
                await bus.close()

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


def _clock() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S")


class _Ticker:
    """One line per tick: the tightest quote per instrument, and which way it moved.

    Deliberately not one line per broker per update — that is thousands of lines
    an hour and nobody reads it. This is a glance, and the database has the rest.
    """

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def line(self, tick: px.QuoteTick) -> str:
        parts: list[str] = []
        for feed in dict.fromkeys(key.feed for key in tick.quotes):
            best = next((q for _, q in tick.by_feed(feed) if q.mid is not None), None)
            if best is None or best.mid is None:
                continue
            previous = self._last.get(feed)
            self._last[feed] = best.mid
            if previous is None or best.mid == previous:
                mark, colour = "·", "dim"
            elif best.mid > previous:
                mark, colour = "▲", "green"
            else:
                mark, colour = "▼", "red"
            parts.append(f"{feed} [{colour}]{_price(best.mid)} {mark}[/]")
        return "   ".join(parts)


@prices.command("collect")
@_common()
@publish_option
@click.option("--bars", type=int, help="Bars to request per sweep. Default: PRICES_LIVE_BARS.")
@click.option("--cycle", type=float, help="Seconds between bar sweeps. Default: PRICES_CYCLE_S.")
@click.option(
    "--poll", type=float, help="Seconds between ticker lines. Default: PRICES_QUOTE_POLL."
)
@click.option("--all-ticks", is_flag=True, help="Store every quote update, not just changes.")
@click.option("--once", is_flag=True, help="One bar sweep and one quote snapshot, then exit.")
def collect_command(
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
    poll,
    all_ticks,
    once,
    publish,
):
    """Run bars and quotes together — the everyday collector.

    Candles are swept on the slower clock while quotes stream continuously.
    `--source` selects candle providers; quotes use the default socket transport.
    """
    setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)
    settings = _settings(db, data_dir, include_partial)
    if cycle is not None:
        settings.cycle_seconds = cycle
    if poll is not None:
        settings.quote_poll_seconds = poll
    feeds = px.resolve_symbols(symbol or None)
    intervals = px.resolve_intervals(interval or None)
    ticker = _Ticker()

    def on_bars(_index: int, summary: px.Summary) -> None:
        console.print(f"[dim]{_clock()}[/] [bold]bars[/]  {summary}")

    def on_quotes(_index: int, tick: px.QuoteTick) -> None:
        line = ticker.line(tick)
        if line:
            console.print(f"[dim]{_clock()}[/] {line}")

    async def go() -> None:
        store = px.open_store(
            store_kind,
            database=settings.database,
            data_dir=settings.data_dir,
            dedupe_quotes=not all_ticks,
        )
        bus = _bus(publish)
        try:
            async with store, asyncio.TaskGroup() as group:
                group.create_task(
                    px.collect(
                        settings=settings,
                        store=store,
                        feeds=feeds,
                        intervals=intervals,
                        sources=source or None,
                        bars=bars,
                        cycles=1 if once else None,
                        on_cycle=on_bars,
                        bus=bus,
                    )
                )
                group.create_task(
                    px.stream(
                        settings=settings,
                        feeds=feeds,
                        sink=store.write_quote,
                        ticks=1 if once else None,
                        on_tick=on_quotes,
                        bus=bus,
                    )
                )
        finally:
            if bus is not None:
                await bus.close()

    try:
        run(go())
    except KeyboardInterrupt:
        console.print("stopped")


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


@main.group()
def news() -> None:
    """Headlines and the economic calendar around them."""


def _news_settings(db: Path | None, data_dir: Path | None) -> nw.Settings:
    settings = nw.Settings.from_env()
    if data_dir is not None:
        settings.data_dir = Path(data_dir)
        if db is None:
            settings.database = settings.data_dir / "news.db"
    if db is not None:
        settings.database = Path(db)
    return settings


def _news_common(func):
    options = [
        click.option(
            "--source",
            "-S",
            multiple=True,
            type=click.Choice(sorted(nw.SOURCES)),
            help="Source; repeatable. Default: all.",
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
        click.option("-v", "--verbose", is_flag=True, help="Debug logging."),
        click.option("-q", "--quiet", is_flag=True, help="Warnings and errors only."),
        click.option(
            "--log-file",
            type=click.Path(path_type=Path),
            help="Also write JSON-lines logs here (rotated).",
        ),
    ]
    for option in reversed(options):
        func = option(func)
    return func


@news.command()
@_news_common
@publish_option
@click.option("--poll", type=float, help="Seconds between passes. Default: NEWS_POLL (300).")
@click.option("--once", is_flag=True, help="Run a single pass and exit.")
def collect(source, store_kind, db, data_dir, verbose, quiet, log_file, publish, poll, once):
    """Poll headlines and calendars, forever."""
    setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)
    settings = _news_settings(db, data_dir)
    if poll is not None:
        settings.news_poll_seconds = poll

    def cycle_done(index: int, summary: nw.Summary) -> None:
        console.print(f"[bold]pass {index}:[/] {summary}")

    async def go() -> None:
        store = nw.open_store(store_kind, database=settings.database, data_dir=settings.data_dir)
        bus = _bus(publish)
        try:
            async with store:
                await nw.collect(
                    settings=settings,
                    store=store,
                    sources=source or None,
                    cycles=1 if once else None,
                    on_cycle=cycle_done,
                    bus=bus,
                )
        finally:
            if bus is not None:
                await bus.close()

    try:
        run(go())
    except KeyboardInterrupt:
        console.print("stopped")


@news.command("info")
@click.option(
    "--store",
    "store_kind",
    default="sqlite",
    type=click.Choice(["sqlite", "jsonl"]),
    show_default=True,
)
@click.option("--db", type=click.Path(path_type=Path))
@click.option("--dir", "data_dir", type=click.Path(path_type=Path))
def news_info(store_kind, db, data_dir):
    """Show what is stored: headlines and events per source."""
    settings = _news_settings(db, data_dir)

    async def go() -> list[nw.FeedInfo]:
        store = nw.open_store(store_kind, database=settings.database, data_dir=settings.data_dir)
        async with store:
            return await store.feeds()

    rows = run(go())
    if not rows:
        console.print("nothing stored yet")
        return
    table = Table(title=str(settings.database if store_kind == "sqlite" else settings.data_dir))
    for column in ("kind", "source", "rows", "from", "to"):
        table.add_column(column, justify="right" if column == "rows" else "left")
    for row in rows:
        table.add_row(
            row.kind, row.source, f"{row.rows:,}", _stamp(row.first_time), _stamp(row.last_time)
        )
    console.print(table)


@news.command()
@click.option("--limit", "-n", default=15, show_default=True)
@click.option("--source", "-S", help="Only this source.")
@click.option("--db", type=click.Path(path_type=Path))
def latest(limit, source, db):
    """Most recent headlines."""
    settings = _news_settings(db, None)

    async def go() -> list[nw.Article]:
        async with nw.SqliteStore(settings.database) as store:
            return await store.latest_articles(limit=limit, source=source)

    rows = run(go())
    if not rows:
        console.print("no headlines stored yet — run `till-infinity news collect --once`")
        return
    table = Table(show_lines=False)
    for column in ("when", "source", "headline"):
        table.add_column(column, overflow="fold" if column == "headline" else "ellipsis")
    for article in rows:
        table.add_row(_stamp(article.published), article.provider or article.source, article.title)
    console.print(table)


@news.command()
@click.option("--limit", "-n", default=15, show_default=True)
@click.option("--high", is_flag=True, help="High-impact releases only.")
@click.option("--db", type=click.Path(path_type=Path))
def upcoming(limit, high, db):
    """The next scheduled releases."""
    settings = _news_settings(db, None)

    async def go() -> list[nw.Event]:
        async with nw.SqliteStore(settings.database) as store:
            return await store.upcoming(limit=limit, min_importance=nw.HIGH if high else nw.LOW)

    rows = run(go())
    if not rows:
        console.print("no events stored yet — run `till-infinity news collect --once`")
        return
    table = Table()
    for column in ("when", "country", "impact", "event", "forecast", "previous"):
        table.add_column(column)
    impact = {nw.LOW: "low", nw.MEDIUM: "med", nw.HIGH: "[bold]HIGH[/]"}
    for event in rows:
        table.add_row(
            _stamp(event.time),
            event.country,
            impact.get(event.importance, "?"),
            event.title,
            event.forecast or "-",
            event.previous or "-",
        )
    console.print(table)


@news.command("sources")
def news_sources():
    """List the configured feeds."""
    table = Table()
    for column in ("kind", "name", "detail"):
        table.add_column(column)
    for name, url in nw.RSS_FEEDS.items():
        table.add_row("rss", name, url)
    table.add_row("calendar", "forexfactory", "this week + next, by currency")
    table.add_row("calendar", "tradingview", ", ".join(nw.CALENDAR_COUNTRIES))
    table.add_row("headlines", "tradingview", ", ".join(nw.HEADLINE_SYMBOLS))
    console.print(table)


@main.group()
def notify() -> None:
    """Send alerts to Telegram and Discord."""


@notify.command("send")
@click.argument("message")
@click.option("--title", "-t", default="", help="Headline. Defaults to the message itself.")
@click.option(
    "--level",
    "-l",
    default="info",
    type=click.Choice(["info", "warning", "critical"]),
    show_default=True,
)
@click.option(
    "--target",
    "-T",
    multiple=True,
    type=click.Choice(sorted(nt.NOTIFIERS)),
    help="Destination; repeatable. Default: every configured one.",
)
@click.option("--url", default="", help="Link to attach.")
@click.option("--field", "-f", multiple=True, metavar="KEY=VALUE", help="Extra field; repeatable.")
@click.option("-v", "--verbose", is_flag=True)
def notify_send(message, title, level, target, url, field, verbose):
    """Send MESSAGE to the configured destinations."""
    setup_logging(verbose=verbose)
    fields: dict[str, str] = {}
    for pair in field:
        key, sep, value = pair.partition("=")
        if not sep:
            raise click.BadParameter(f"expected KEY=VALUE, got {pair!r}", param_hint="--field")
        fields[key.strip()] = value.strip()

    notification = nt.Notification(
        title=title or message,
        body="" if title == "" else message,
        level=nt.Level.parse(level),
        url=url,
        fields=fields,
        source="till-infinity",
    )
    results = run(nt.notify(notification, targets=target or None))
    if not results:
        console.print(
            "[yellow]no target configured[/] — set TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID, or DISCORD_WEBHOOK_URL"
        )
        raise SystemExit(1)
    for delivery in results:
        mark = "[green]✓[/]" if delivery.ok else "[red]✗[/]"
        console.print(f"  {mark} {escape(str(delivery))}")
    if not all(d.ok for d in results):
        raise SystemExit(1)


@notify.command("targets")
def notify_targets():
    """List the configured channels. Webhook URLs are masked."""
    settings = nt.Settings.from_env()
    table = Table()
    for column in ("target", "label", "address", "min level"):
        table.add_column(column)
    rows = 0
    for target in sorted(nt.NOTIFIERS):
        for channel in settings.channels(target):
            table.add_row(
                target,
                escape(channel.label),
                escape(channel.masked),
                channel.min_level.name.lower(),
            )
            rows += 1
    if rows:
        console.print(table)
    if settings.telegram_auto_chats and not settings.telegram_chats:
        console.print("[dim]telegram: auto-discovering chats (TELEGRAM_AUTO_CHATS)[/]")
    elif not rows:
        console.print("[yellow]no channel configured[/]")
    missing = [t for t in sorted(nt.NOTIFIERS) if t not in settings.configured()]
    needs = {
        "telegram": "TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_IDS",
        "discord": "DISCORD_WEBHOOK_URLS",
    }
    for target in missing:
        console.print(f"[dim]{target}: needs {needs[target]}[/]")


@notify.command("chats")
@click.option("--verbose", "-v", is_flag=True)
def notify_chats(verbose):
    """Discover Telegram chat ids the bot can post to."""
    setup_logging(verbose=verbose)
    settings = nt.Settings.from_env()
    if not settings.telegram_token:
        console.print("[yellow]set TELEGRAM_BOT_TOKEN first[/]")
        raise SystemExit(1)

    try:
        chats = run(nt.discover_telegram_chats(settings))
    except Exception as exc:
        console.print(f"[red]discovery failed:[/] {exc}")
        raise SystemExit(1) from exc

    if not chats:
        console.print(
            "no chats seen. Telegram's getUpdates only covers the last 24 hours — "
            "send the bot a message, or post in the group, then try again."
        )
        return
    table = Table()
    for column in ("chat id", "name"):
        table.add_column(column)
    for chat in chats:
        table.add_row(chat.address, escape(chat.label))
    console.print(table)
    console.print("\n[dim]add them with:[/]")
    console.print("  export TELEGRAM_CHAT_IDS=" + ",".join(f"{c.label}={c.address}" for c in chats))


@notify.command("test")
@click.option(
    "--target",
    "-T",
    multiple=True,
    type=click.Choice(sorted(nt.NOTIFIERS)),
)
def notify_test(target):
    """Send a test notification to prove the wiring."""
    setup_logging()
    notification = nt.Notification(
        title="Till Infinity is wired up",
        body="If you can read this, alerts will reach you.",
        level=nt.Level.INFO,
        fields={"sent": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")},
        source="till-infinity",
    )
    results = run(nt.notify(notification, targets=target or None))
    if not results:
        console.print("[yellow]no target configured[/] — see `till-infinity notify targets`")
        raise SystemExit(1)
    for delivery in results:
        mark = "[green]✓[/]" if delivery.ok else "[red]✗[/]"
        console.print(f"  {mark} {escape(str(delivery))}")
    if not all(d.ok for d in results):
        raise SystemExit(1)


@notify.command("listen")
@click.option(
    "--target",
    "-T",
    multiple=True,
    type=click.Choice(sorted(nt.NOTIFIERS)),
    help="Target; repeatable. Default: all configured.",
)
@click.option(
    "--redis",
    "redis_url",
    metavar="URL",
    help="Redis to subscribe on. Default: TILL_REDIS_URL.",
)
@click.option("--group", default="notifications", show_default=True, help="Consumer group name.")
@click.option("-v", "--verbose", is_flag=True, help="Debug logging.")
@click.option("-q", "--quiet", is_flag=True, help="Warnings and errors only.")
@click.option("--log-file", type=click.Path(path_type=Path), help="Also write JSON-lines logs.")
def notify_listen(target, redis_url, group, verbose, quiet, log_file):
    """Deliver alerts published to the bus, forever.

    This is the consumer end of `--publish`: an agent puts an alert on the
    `alerts` topic and this turns it into Telegram and Discord messages. It
    needs Redis to hear another process — an in-process bus only reaches
    publishers in this one.
    """
    setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)
    url = redis_url or os.environ.get("TILL_REDIS_URL") or None
    bus = Bus(redis_url=url)
    if url is None:
        console.print(
            "[yellow]no redis configured[/] — listening on an in-process bus, "
            "which only hears publishers inside this command. "
            "Set TILL_REDIS_URL or pass --redis to consume from a collector."
        )
    console.print(f"listening on [bold]{bus.backend}[/] for alerts, Ctrl-C to stop")

    async def go() -> None:
        try:
            await nt.listen(bus, targets=target or None, group=group)
        finally:
            await bus.close()

    try:
        run(go())
    except KeyboardInterrupt:
        console.print("stopped")


if __name__ == "__main__":  # pragma: no cover
    main()
