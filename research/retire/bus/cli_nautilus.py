"""The command line, for the Nautilus era.

**The previous one was 2,852 lines and is in `research/retire/bus/cli.py`.**
It grew around the services it drove - `prices collect`, `structures watch`,
`journal listen`, `notify listen` - and every one of those is retired: the
collectors are adapters, the listeners are actors, and the supervisor is a
`TradingNode`. A command group for a package that no longer exists is not a
command group.

What a person still needs from a terminal:

    till-infinity live              run the trading node
    till-infinity backtest NAME     run a backtest config
    till-infinity ladder            what the pipeline has decided
    till-infinity sizing            what this machine will allow
    till-infinity contracts         which bus contracts are declared
    till-infinity doctor            can this box reach what it needs

Deliberately small. A CLI that can do everything the node can do is a second
way to run the desk, and the lesson from `till.env needs a container
recreate` is that two ways to change the same thing means one of them is
silently stale.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="till-infinity")
def main() -> None:
    """Till Infinity: a Nautilus trading node and the pipeline that feeds it."""


@main.command()
@click.option("--dry-run", is_flag=True, help="Build the node and report, without running.")
def live(dry_run: bool) -> None:
    """Run the live trading node."""
    from .node.live import build, settings

    config = settings()
    console.print(f"trader [bold]{config.trader_id}[/]")
    console.print(f"  data clients: {', '.join(config.data_clients) or 'none'}")
    console.print(f"  exec clients: {', '.join(config.exec_clients) or 'none'}")
    console.print(f"  reconciliation: {config.exec_engine.reconciliation}")
    if dry_run:
        console.print("[yellow]dry run[/] - built, not started")
        return
    node = build()
    try:
        node.run()
    finally:
        node.dispose()


@main.command()
@click.argument("instrument")
@click.option("--spec", default="1-MINUTE-LAST-EXTERNAL", show_default=True)
@click.option("--start", default=None, help="ISO date, inclusive.")
@click.option("--end", default=None, help="ISO date, inclusive.")
def backtest(instrument: str, spec: str, start: str | None, end: str | None) -> None:
    """Run a backtest over one instrument.

    Refuses on the trading host: a sweep is a burst of exactly the work the
    live node needs cores for, and a research job has already starved the desk
    on a two-core box.
    """
    from .node.backtest import WrongHostError, run_config, where

    try:
        host = where()
    except WrongHostError as exc:
        console.print(f"[red]{exc}[/]")
        raise SystemExit(2) from exc
    console.print(f"backtesting {instrument} {spec} on {host}")
    config = run_config(instrument, spec, start=start, end=end)
    console.print(f"  venue: {config.venues[0].name}, data: {len(config.data)} source(s)")
    console.print("[yellow]configured[/] - add actors and strategies to run it")


@main.command()
@click.option(
    "--path",
    type=click.Path(path_type=Path),
    default=lambda: Path(os.environ.get("LADDER_PATH", ".data/ladder.json")),
    show_default="$LADDER_PATH or .data/ladder.json",
)
def ladder(path: Path) -> None:
    """What the pipeline has decided, and why anything is held."""
    from .node.pipeline import Ladder, pending, report

    state = Ladder.load(path)
    if not state.candidates:
        console.print(f"[yellow]no ladder at {path}[/] - nothing has been discovered yet")
        return
    for line in report(state):
        console.print(line)
    held = pending(state)
    if held:
        console.print()
        console.print("[bold]waiting on[/]")
        for name, reasons in held:
            console.print(f"  {name}: {'; '.join(reasons)}")


@main.command()
def sizing() -> None:
    """What this machine will allow a sweep to do."""
    from .node.sizing import describe

    console.print(describe())


@main.command()
def contracts() -> None:
    """Which bus contracts are declared, and whether they can be found."""
    from till_platform import contracts as reader

    why = reader.missing()
    if why:
        console.print(f"[red]{why}[/]")
        raise SystemExit(1)
    declared = reader.declared()
    console.print(f"{len(declared)} declared at [dim]{reader.HOME}[/]")
    for topic in declared:
        console.print(f"  {topic}")


@main.command()
def doctor() -> None:
    """Can this box reach what the node needs?

    Checks the things that have actually broken: the bridge, the contracts and
    the machine's own capacity. Each line says what it asked and what
    answered, because "unhealthy" is not an answer anybody can act on.
    """
    import httpx

    ok = True
    bridge = os.environ.get("TRADING_MT5_URL", "http://localhost:8000")
    try:
        response = httpx.get(f"{bridge}/api/v1/terminal/ping", timeout=10.0)
        console.print(f"bridge {bridge}: [green]{response.status_code}[/]")
    except Exception as exc:
        console.print(f"bridge {bridge}: [red]{type(exc).__name__}: {exc}[/]")
        ok = False

    from till_platform import contracts as reader

    why = reader.missing()
    console.print(
        f"contracts: [red]{why}[/]" if why else f"contracts: [green]{len(reader.declared())}[/]"
    )
    ok = ok and not why

    from .node.sizing import describe

    console.print(f"sizing: {describe()}")

    try:
        import nautilus_trader

        console.print(f"nautilus: [green]{nautilus_trader.__version__}[/]")
    except ImportError:
        console.print("nautilus: [red]not installed[/]")
        ok = False
    raise SystemExit(0 if ok else 1)


@main.command()
@click.argument("claim")
def closed(claim: str) -> None:
    """Has this desk already answered this question?"""
    from .node.closed import summary, warn

    note = warn(claim)
    console.print(note if note else f"[green]open[/] - {claim}")
    console.print(f"[dim]{summary()}[/]")


@main.command("partition")
@click.argument("operator")
@click.option("--operators", required=True, help="Comma-separated, including this one.")
def partition_command(operator: str, operators: str) -> None:
    """Which slice of the search space this operator should explore."""
    from .node.partition import assign

    names = [n.strip() for n in operators.split(",") if n.strip()]
    feeds = json.loads(os.environ.get("PARTITION_FEEDS", "[]")) or [
        "eurusd",
        "gbpusd",
        "usdjpy",
        "audusd",
        "usdcad",
        "usdchf",
        "nzdusd",
        "eurgbp",
        "eurjpy",
        "gold",
        "btc",
        "spx500",
    ]
    got = assign(
        operator,
        feeds=feeds,
        intervals=["1m", "5m", "15m", "1h"],
        questions=["dispersion", "participation", "regime", "context"],
        operators=names,
    )
    console.print(f"[bold]{operator}[/] of {len(names)} operators")
    console.print(f"  feeds:     {', '.join(got.feeds)}")
    console.print(f"  intervals: {', '.join(got.intervals)}")
    console.print(f"  questions: {', '.join(got.questions)}")


if __name__ == "__main__":
    main()
