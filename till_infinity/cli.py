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

from . import agents as ag
from . import journal as jr
from . import news as nw
from . import notifications as nt
from . import prices as px
from . import structures as sx
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


@main.group()
def agents() -> None:
    """Ask an analyst about the collected data, or leave one watching."""


def _agent_settings(prices_db, news_db, model, role_name):
    settings = ag.Settings.from_env()
    if prices_db is not None:
        settings.prices_db = Path(prices_db)
    if news_db is not None:
        settings.news_db = Path(news_db)
    if model:
        settings.model = model
    if not settings.ready:
        console.print(f"[red]{escape(ag.providers.missing(settings.model))}[/]")
        raise SystemExit(1)
    return settings, ag.resolve(role_name)


agent_options = [
    click.option(
        "--role",
        "-r",
        "role_name",
        type=click.Choice(sorted(ag.ROLES)),
        default=ag.DEFAULT_ROLE,
        show_default=True,
        help="Which analyst. Each sees a different set of tools.",
    ),
    click.option(
        "--model",
        "-m",
        help=(
            "provider:model — openai:gpt-5, google:gemini-2.5-pro, xai:grok-4. "
            f"A bare name is Anthropic's. Default: {ag.DEFAULT_MODEL}."
        ),
    ),
    click.option("--prices-db", type=click.Path(path_type=Path), help="Prices SQLite file."),
    click.option("--news-db", type=click.Path(path_type=Path), help="News SQLite file."),
    click.option("-v", "--verbose", is_flag=True, help="Debug logging."),
    click.option("-q", "--quiet", is_flag=True, help="Warnings and errors only."),
    click.option("--log-file", type=click.Path(path_type=Path), help="Also write JSON-lines logs."),
]


def _agent_common(func):
    for option in reversed(agent_options):
        func = option(func)
    return func


def _show(run: ag.Run) -> None:
    console.print(f"[bold]{escape(run.analysis.summary)}[/]")
    if not run.analysis.findings:
        console.print("[dim]no findings — the data does not support an alert[/]")
    for finding in run.analysis.findings:
        colour = {"critical": "red", "warning": "yellow"}.get(finding.level, "cyan")
        console.print(
            f"\n[{colour}]{finding.level}[/] [bold]{escape(finding.title)}[/] "
            f"[dim]({finding.confidence:.0%}"
            f"{', ' + escape(finding.instrument) if finding.instrument else ''})[/]"
        )
        if finding.detail:
            console.print(f"  {escape(finding.detail)}")
        for line in finding.evidence:
            console.print(f"  [dim]· {escape(line)}[/]")
    console.print(f"\n[dim]{run.role} via {run.model}: {run}[/]")


@agents.command("ask")
@click.argument("question", nargs=-1, required=True)
@_agent_common
def agents_ask(question, role_name, model, prices_db, news_db, verbose, quiet, log_file):
    """Ask a question about the stored data.

    The analyst answers only from tool calls against the databases — it has no
    prices of its own, and every store it reads is opened read-only.
    """
    setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)
    settings, role = _agent_settings(prices_db, news_db, model, role_name)
    try:
        outcome = run(ag.analyse(" ".join(question), role=role, settings=settings))
    except (ag.NotConfiguredError, ag.ProviderUnavailableError) as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
        raise SystemExit(1) from None
    _show(outcome)


@agents.command("watch")
@_agent_common
@click.option(
    "--redis",
    "redis_url",
    metavar="URL",
    help="Redis to consume from. Default: TILL_REDIS_URL.",
)
@click.option("--window", type=float, help="Seconds of bus traffic per judgement. Default: 60.")
@click.option("--spread-bps", type=float, help="Spread that wakes the model. Default: 8.")
@click.option("--group", default="agents", show_default=True, help="Consumer group name.")
@click.option("--journal-db", type=click.Path(path_type=Path), help="Journal SQLite file.")
@click.option("--no-journal", is_flag=True, help="Do not record decisions.")
@click.option("--once", is_flag=True, help="Judge a single window and exit.")
def agents_watch(
    role_name,
    model,
    prices_db,
    news_db,
    verbose,
    quiet,
    log_file,
    redis_url,
    window,
    spread_bps,
    group,
    journal_db,
    no_journal,
    once,
):
    """Watch the bus and alert when something is worth a human's attention.

    Consumes what the collectors publish, judges each window without a model
    first, and only then asks one. Findings go to the `alerts` topic, which
    `notify listen` delivers.
    """
    setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)
    settings, role = _agent_settings(prices_db, news_db, model, role_name)
    if window is not None:
        settings.window_seconds = window
    if spread_bps is not None:
        settings.spread_bps = spread_bps
    if journal_db is not None:
        settings.journal_db = Path(journal_db)
    if no_journal:
        settings.journalling = False

    url = redis_url or os.environ.get("TILL_REDIS_URL") or None
    bus = Bus(redis_url=url)
    if url is None:
        console.print(
            "[yellow]no redis configured[/] — an in-process bus only hears "
            "publishers inside this command. Set TILL_REDIS_URL or pass --redis."
        )
    console.print(
        f"[bold]{role.name}[/] watching {bus.backend} in "
        f"{settings.window_seconds:.0f}s windows, Ctrl-C to stop"
    )

    def window_done(index, messages, outcome):
        console.print(
            f"[dim]{_clock()}[/] window {index}: {len(messages)} message(s)"
            + ("" if outcome is None else f" -> {outcome}")
        )
        if outcome is not None:
            _show(outcome)

    async def go() -> None:
        book = jr.Journal(settings.journal_db) if settings.journalling else None
        try:
            if book is not None:
                await book.open()
            await ag.watch(
                bus,
                settings=settings,
                role=role,
                group=group,
                windows=1 if once else None,
                on_window=window_done,
                journal=book,
            )
        finally:
            if book is not None:
                await book.close()
            await bus.close()

    try:
        run(go())
    except KeyboardInterrupt:
        console.print("stopped")


@agents.command("providers")
def agents_providers():
    """Show which model providers are usable from here."""
    setup_logging()
    table = Table(title="model providers")
    for column in ("prefix", "models", "environment", "ready", "installs with"):
        table.add_column(column)
    for name in sorted({p.name for p in ag.providers.PROVIDERS.values()}):
        known = ag.providers.PROVIDERS[name]
        ready = ag.providers.ready(f"{name}:x")
        table.add_row(
            f"[bold]{name}[/]" + (" [dim](default)[/]" if name == "anthropic" else ""),
            escape(known.label),
            escape(known.env_names or "—"),
            "[green]yes[/]" if ready else "[dim]no[/]",
            escape(known.install or "—"),
        )
    console.print(table)
    console.print("[dim]Use as[/] --model openai:gpt-5 [dim]· a bare name is Anthropic's[/]")


@agents.command("roles")
def agents_roles():
    """Show the analysts and what each one can read."""
    table = Table(title="analysts")
    for column in ("role", "goal", "tools"):
        table.add_column(column)
    for name in sorted(ag.ROLES):
        role = ag.ROLES[name]
        table.add_row(
            f"[bold]{name}[/]" + (" [dim](default)[/]" if name == ag.DEFAULT_ROLE else ""),
            escape(role.goal),
            escape(", ".join(role.tools)),
        )
    console.print(table)


@main.group()
def structures() -> None:
    """Online models over the price data — what is unusual, what has changed."""


@structures.command("watch")
@click.option("--redis", "redis_url", metavar="URL", help="Redis. Default: TILL_REDIS_URL.")
@click.option("--dir", "state_dir", type=click.Path(path_type=Path), help="Where models persist.")
@click.option("--warmup", type=int, help="Readings before a score means anything. Default: 60.")
@click.option("--quantile", type=float, help="Joint-model cutoff. Default: 0.999.")
@click.option("--sigma", type=float, help="Per-venue cutoff, in sigma. Default: 4.")
@click.option("--group", default="structures", show_default=True, help="Consumer group name.")
@click.option("--no-alerts", is_flag=True, help="Publish signals only; never alert directly.")
@click.option("--no-journal", is_flag=True, help="Do not record detections.")
@click.option("--messages", type=int, help="Stop after this many bus messages.")
@click.option("-v", "--verbose", is_flag=True, help="Debug logging.")
@click.option("-q", "--quiet", is_flag=True, help="Warnings and errors only.")
@click.option("--log-file", type=click.Path(path_type=Path), help="Also write JSON-lines logs.")
def structures_watch(
    redis_url,
    state_dir,
    warmup,
    quantile,
    sigma,
    group,
    no_alerts,
    no_journal,
    messages,
    verbose,
    quiet,
    log_file,
):
    """Learn what is normal across venues, and say when something is not.

    Consumes quotes and fast bars, measuring every venue against the median of
    the others. Findings go to `structures.signals` for an agent to weigh
    against the calendar; the unambiguous ones — a feed that has stopped —
    go straight to `alerts`.
    """
    setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)
    settings = sx.Settings.from_env()
    if state_dir is not None:
        settings.state_dir = Path(state_dir)
    if warmup is not None:
        settings.warmup = warmup
    if quantile is not None:
        settings.quantile = quantile
    if sigma is not None:
        settings.sigma = sigma
    if no_alerts:
        settings.alert_direct = False
    if no_journal:
        settings.journalling = False

    url = redis_url or os.environ.get("TILL_REDIS_URL") or None
    bus = Bus(redis_url=url)
    if url is None:
        console.print(
            "[yellow]no redis configured[/] — an in-process bus only hears "
            "publishers inside this command. Set TILL_REDIS_URL or pass --redis."
        )

    def show(signal) -> None:
        colour = {"stale": "red", "drift": "magenta", "spread": "yellow"}.get(
            str(signal.shape), "cyan"
        )
        console.print(
            f"[dim]{_clock()}[/] [{colour}]{signal.shape}[/] "
            f"[bold]{escape(signal.venue)}[/] {escape(signal.feed)} "
            f"[dim]{signal.score:.3f}[/] {escape(signal.detail)}"
        )

    async def go() -> None:
        book = jr.Journal(settings.journal_db) if settings.journalling else None
        watcher = sx.Watcher(bus, settings=settings, group=group, journal=book)
        try:
            if book is not None:
                await book.open()
            console.print(
                f"[bold]{'warm' if watcher.load() else 'cold'}[/] start on "
                f"{bus.backend}, models in {escape(str(settings.state_dir))}, Ctrl-C to stop"
            )
            await watcher.run(messages=messages, on_signal=show)
        finally:
            console.print(f"{watcher.published} signal(s), {watcher.alerted} direct alert(s)")
            if book is not None:
                await book.close()
            await bus.close()

    try:
        run(go())
    except KeyboardInterrupt:
        console.print("stopped")


@structures.command("info")
@click.option("--dir", "state_dir", type=click.Path(path_type=Path), help="Where models persist.")
def structures_info(state_dir):
    """What the models have learned so far."""
    setup_logging()
    settings = sx.Settings.from_env()
    if state_dir is not None:
        settings.state_dir = Path(state_dir)
    state = sx.load(settings.state_dir)
    if not state:
        console.print(
            f"[yellow]no model state in {escape(str(settings.state_dir))}[/] — "
            "nothing learned yet, or it was written by another river/python version"
        )
        return
    table = Table(title=f"models: {settings.state_dir}")
    for column in ("model", "instrument", "readings", "warm"):
        table.add_column(column, justify="right" if column == "readings" else "left")
    detector = state.get("detector")
    for feed, count in sorted(getattr(detector, "seen", dict)().items()):
        table.add_row("anomaly", feed, f"{count:,}", "yes" if count >= detector.warmup else "no")
    for feed, count in sorted(getattr(state.get("drift"), "seen", dict)().items()):
        table.add_row("drift", feed, f"{count:,}", "—")
    console.print(table)


def _load_engine(state_dir):
    """The engine as `structures watch` last saved it, or None."""
    settings = sx.Settings.from_env()
    if state_dir is not None:
        settings.state_dir = Path(state_dir)
    state = sx.load(settings.state_dir)
    engine = (state or {}).get("engine")
    if engine is None:
        console.print(
            f"[yellow]no levels in {escape(str(settings.state_dir))}[/] — run "
            "`till-infinity structures watch` first, or the state was written "
            "by another river/python version"
        )
    return engine


def _state_colour(state: str) -> str:
    return {"broken": "red", "flipped": "magenta", "tested": "green"}.get(state, "dim")


@structures.command("levels")
@click.option("--dir", "state_dir", type=click.Path(path_type=Path), help="Where models persist.")
@click.option("--feed", "-s", help="Instrument. Default: all.")
@click.option("--interval", "-i", help="Interval or pivot session (5m, 1h, daily).")
@click.option(
    "--min-touches",
    type=float,
    default=0.0,
    show_default=True,
    help="Hide levels with less evidence than this.",
)
@click.option("--pivots/--no-pivots", default=True, show_default=True, help="Include pivots.")
@click.option(
    "--at",
    "price",
    type=float,
    help="Price to judge from — shows the directional call at the nearest levels.",
)
def structures_levels(state_dir, feed, interval, min_touches, pivots, price):
    """Show the key levels found, and what they do when price arrives.

    Touch counts are *effective* counts: evidence decays with age, so a level
    tested ten times last quarter reads lower than one tested ten times this
    week. That is the point — a level is only as good as its recent behaviour.

    With `--at`, the nearest levels are judged from that price: which way the
    history says it goes, against the base rate, and whether that clears the
    bar for being worth acting on.
    """
    setup_logging()
    engine = _load_engine(state_dir)
    if engine is None:
        raise SystemExit(1)

    rows = [row for row in engine.summary() if row["touches"] >= min_touches]
    if feed:
        rows = [row for row in rows if row["feed"] == feed]
    if interval:
        rows = [row for row in rows if row["interval"] == interval]
    if not pivots:
        rows = [row for row in rows if not row["origin"].startswith("pivot")]
    if not rows:
        console.print("no levels match")
        return

    table = Table(title="key levels")
    for column in ("feed", "tf", "price", "zone", "state", "from above", "from below", "str"):
        table.add_column(column, justify="right" if column in ("price", "str") else "left")
    for row in sorted(rows, key=lambda r: (r["feed"], r["interval"], r["price"])):
        sides = row["sides"]
        table.add_row(
            escape(row["feed"]),
            escape(row["interval"]),
            f"{row['price']:.5g}",
            f"[dim]{row['low']:.5g}-{row['high']:.5g}[/]",
            f"[{_state_colour(row['state'])}]{row['state']}[/]"
            + (
                f" [dim]{escape(row['origin'].partition(':')[2])}[/]"
                if row["origin"].startswith("pivot")
                else ""
            ),
            _side_cell(sides.get("above")),
            _side_cell(sides.get("below")),
            f"{row['strength']:.2f}",
        )
    console.print(table)
    console.print(f"{len(rows)} level(s) [dim]· touches are effective counts, decayed by age[/]")

    if price is not None:
        _judge_at(engine, feed, price)


def _side_cell(stats) -> str:
    """Touches and mean push for one side, or a dash."""
    if not stats or not stats["touches"]:
        return "[dim]—[/]"
    push = stats["mean_push_vol"]
    colour = "green" if push > 0 else "red" if push < 0 else "dim"
    return f"{stats['touches']:.1f}x [{colour}]{push:+.2f}v[/]"


def _judge_at(engine, feed: str | None, price: float) -> None:
    """What the history says about arriving at `price` right now."""
    from till_infinity.structures import reactions

    feeds = [feed] if feed else sorted({row["feed"] for row in engine.summary()})
    for name in feeds:
        vol = engine.vol.of(name)
        near = sx.levels_near(engine, name, price)
        if not near:
            continue
        console.print(
            f"\n[bold]{escape(name)}[/] arriving at {price:.5g} "
            f"[dim](volatility {vol.bps:.2f}bps)[/]"
        )
        for level in near:
            side = level.side_of(price)
            features = reactions.features_for(level, side, price, vol)
            found = reactions.infer(level, side, features, engine.tracker.memory)
            mark = "[bold green]![/]" if found.actionable else "[dim]·[/]"
            arrow = "↑" if found.direction == "up" else "↓"
            console.print(
                f"  {mark} {level.price:.5g} [dim]({level.distance_vol(price, vol):+.2f}v away, "
                f"from {side})[/] {arrow} {found.probability_up:.0%} "
                f"[dim]vs {found.base_rate_up:.0%} base[/] "
                f"push {found.expected_push:+.2f}v [dim]{escape(found.detail)}[/]"
            )


@main.group()
def journal() -> None:
    """The decision journal: what was decided, and why at that moment."""


def _journal_db(path):
    return Path(path) if path is not None else Path(os.environ.get("JOURNAL_DB") or jr.DEFAULT_DB)


db_option = click.option("--db", type=click.Path(path_type=Path), help="Journal SQLite file.")


def _entries_table(entries, title):
    table = Table(title=title)
    for column in ("when", "kind", "actor", "entry", "id"):
        table.add_column(column, overflow="fold")
    for entry in entries:
        colour = {"decision": "cyan", "outcome": "green", "observation": "dim"}.get(
            str(entry.kind), "white"
        )
        label = escape(entry.title)
        if entry.confidence is not None:
            label += f" [dim]({entry.confidence:.0%})[/]"
        table.add_row(
            _stamp(int(entry.time)),
            f"[{colour}]{entry.kind}[/]",
            escape(entry.actor),
            label,
            f"[dim]{entry.id}[/]",
        )
    console.print(table)


@journal.command("add")
@click.argument("title", nargs=-1, required=True)
@db_option
@click.option("--why", "-w", default="", help="Why, at this moment. The point of the entry.")
@click.option(
    "--kind",
    "-k",
    type=click.Choice([str(k) for k in jr.Kind]),
    default=str(jr.Kind.NOTE),
    show_default=True,
)
@click.option("--actor", "-a", default="human", show_default=True)
@click.option("--tag", "-t", multiple=True, help="Instrument or venue; repeatable.")
@click.option("--parent", "-p", default="", help="Entry this is an outcome of.")
def journal_add(title, db, why, kind, actor, tag, parent):
    """Record a decision, an observation or a note.

    The `--why` is the part that matters. A title says what happened; the
    reasoning at the time is the thing nobody can reconstruct later.
    """
    setup_logging()
    entry = jr.Entry(
        title=" ".join(title),
        kind=jr.Kind.parse(kind),
        actor=actor,
        rationale=why,
        tags=tuple(tag),
        parent=parent,
    )
    if entry.kind is jr.Kind.DECISION and not why:
        console.print("[yellow]a decision without a --why is only a log line[/]")

    async def go():
        async with jr.Journal(_journal_db(db)) as book:
            return await book.write(entry)

    written = run(go())
    console.print(f"{'recorded' if written else 'already recorded'} [dim]{entry.id}[/]")


@journal.command("list")
@db_option
@click.option("--kind", "-k", type=click.Choice([str(k) for k in jr.Kind]))
@click.option("--actor", "-a", default="", help="Exact actor, e.g. agents/risk.")
@click.option("--tag", "-t", default="", help="Instrument or venue.")
@click.option("--hours", type=float, help="Only entries this recent.")
@click.option("--limit", "-n", type=int, default=25, show_default=True)
def journal_list(db, kind, actor, tag, hours, limit):
    """Show recent entries, newest first."""
    setup_logging()
    try:
        entries = jr.read(
            _journal_db(db), kind=kind, actor=actor, tag=tag, hours=hours, limit=limit
        )
    except FileNotFoundError as exc:
        console.print(f"[yellow]{escape(str(exc))}[/]")
        return
    if not entries:
        console.print("nothing matches")
        return
    _entries_table(entries, f"journal: {_journal_db(db)}")


@journal.command("show")
@click.argument("entry_id")
@db_option
def journal_show(entry_id, db):
    """Show one entry in full, with anything that followed from it."""
    setup_logging()
    path = _journal_db(db)
    try:
        entry = jr.get(path, entry_id)
    except FileNotFoundError as exc:
        console.print(f"[yellow]{escape(str(exc))}[/]")
        return
    if entry is None:
        console.print(f"no entry {escape(entry_id)}")
        raise SystemExit(1)

    console.print(f"[bold]{escape(entry.title)}[/] [dim]({entry.kind})[/]")
    console.print(f"[dim]{_stamp(int(entry.time))} · {escape(entry.actor)}[/]")
    if entry.rationale:
        console.print(f"\n[bold]why[/]  {escape(entry.rationale)}")
    if entry.confidence is not None:
        console.print(f"[bold]confidence[/]  {entry.confidence:.0%}")
    if entry.tags:
        console.print(f"[bold]tags[/]  {escape(', '.join(entry.tags))}")
    if entry.context:
        console.print("\n[bold]state at the time[/]")
        for key, value in entry.context.items():
            console.print(f"  [dim]{escape(str(key))}[/] {escape(str(value))}")
    followed = jr.read(path, parent=entry.id, limit=20)
    if followed:
        console.print()
        _entries_table(followed, "what followed")


@journal.command("listen")
@db_option
@click.option("--redis", "redis_url", metavar="URL", help="Redis. Default: TILL_REDIS_URL.")
@click.option("--group", default="journal", show_default=True, help="Consumer group name.")
@click.option("-v", "--verbose", is_flag=True, help="Debug logging.")
@click.option("-q", "--quiet", is_flag=True, help="Warnings and errors only.")
@click.option("--log-file", type=click.Path(path_type=Path), help="Also write JSON-lines logs.")
def journal_listen(db, redis_url, group, verbose, quiet, log_file):
    """Write down what the other services publish to the `journal` topic.

    The journal is a service like the rest: agents and structures publish their
    decisions and this records them, so there is one writer rather than one per
    process — and a service on another machine can record a decision at all.
    """
    setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)
    url = redis_url or os.environ.get("TILL_REDIS_URL") or None
    bus = Bus(redis_url=url)
    path = _journal_db(db)
    if url is None:
        console.print(
            "[yellow]no redis configured[/] — an in-process bus only hears "
            "publishers inside this command. Set TILL_REDIS_URL or pass --redis."
        )
    console.print(f"recording to [bold]{escape(str(path))}[/] from {bus.backend}, Ctrl-C to stop")

    def show(entry, fresh: bool) -> None:
        mark = "[green]+[/]" if fresh else "[dim]=[/]"
        console.print(
            f"  {mark} [dim]{entry.kind}[/] {escape(entry.title)} [dim]{escape(entry.actor)}[/]"
        )

    async def go() -> None:
        written = 0
        try:
            async with jr.Journal(path) as book:
                written = await jr.listen(bus, book, group=group, on_entry=show)
        finally:
            console.print(f"{written} entr(y/ies) recorded")
            await bus.close()

    try:
        run(go())
    except KeyboardInterrupt:
        console.print("stopped")


@journal.command("info")
@db_option
def journal_info(db):
    """What is in the journal, by actor and kind."""
    setup_logging()
    try:
        rows = jr.summary(_journal_db(db))
    except FileNotFoundError as exc:
        console.print(f"[yellow]{escape(str(exc))}[/]")
        return
    table = Table(title=f"journal: {_journal_db(db)}")
    for column in ("actor", "kind", "entries", "first", "last"):
        table.add_column(column, justify="right" if column == "entries" else "left")
    for row in rows:
        table.add_row(
            escape(row["actor"] or "—"),
            escape(row["kind"]),
            f"{row['entries']:,}",
            _stamp(int(row["first"])),
            _stamp(int(row["last"])),
        )
    console.print(table)
    console.print(f"{sum(r['entries'] for r in rows):,} entries")


@journal.command("export")
@db_option
@click.option("--out", "-o", type=click.Path(path_type=Path), help="Write here; default stdout.")
@click.option("--kind", "-k", type=click.Choice([str(k) for k in jr.Kind]))
@click.option("--hours", type=float, help="Only entries this recent.")
@click.option("--limit", "-n", type=int, default=jr.MAX_ROWS, show_default=True)
def journal_export(db, out, kind, hours, limit):
    """Write the journal out as JSON lines, oldest first — training-set shaped."""
    setup_logging(quiet=out is None)
    try:
        written = jr.export(_journal_db(db), target=out, kind=kind, hours=hours, limit=limit)
    except FileNotFoundError as exc:
        console.print(f"[yellow]{escape(str(exc))}[/]")
        raise SystemExit(1) from None
    if out is not None:
        console.print(f"{written:,} entries -> {escape(str(out))}")


if __name__ == "__main__":  # pragma: no cover
    main()
