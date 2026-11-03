"""Every configured strategy over every catalogue instrument, through the engine.

Answers one question with the production path rather than from memory: **does
this desk have a profitable strategy?** Each cell is a real `BacktestNode` run
over the recorded catalogue, building the desks `node/desks.py` would deploy,
so a result here is a statement about what would trade.

## What a cell is, and what it is not

A cell is one `(rule, entry)` leaf on one instrument. `strategies/leaves.py`
registers four rules and three entries, so twelve leaves, over the six
catalogue instruments - 72 runs.

**The figure reported is account PnL and the position count, not R.** R needs
the risk denominator each `Intent` carried, which `BacktestResult` does not
hold; `research/ideas/smc_bos_c_catalogue.py` extracts it from fills and is
the place to go for an R reading. PnL here is in the catalogue's own
instrument conventions, which are Nautilus's standard ones rather than the
broker's, so **money is this catalogue's and not the desk's** - see
`node/corpus.py`. A sign and a trade count are what survive that.

## Why a positive cell here is not an edge

Twelve leaves over six instruments is 72 trials. At a 5% threshold that is
between three and four positive cells from noise alone, and the catalogue
gives this family 4-8 trades an instrument-month over 62-86 days - so a cell
is a handful of trades. `discovery.gate_from` exists because reporting the
best of a sweep as though it were the only one is the error; nothing here is
deflated, and a positive cell is a candidate for a measurement rather than a
result.

The measured context, so a reader does not have to guess: the one rule in
this set that has been reconciled against its specification reads **-0.533R a
trade** over 75 trades with a day-block interval of [-0.830, -0.237], its
reversed-side twin reads -0.134R, and taking its signals **eight bars stale**
changes the figure by 0.014R. See `research/docs/smc-bos-reconcile.md`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass

#: The catalogue's instruments. `us100` and `spx500` are **not the venue the
#: live desk trades** - their quote coverage is best elsewhere - so their rows
#: are statements about that venue's cost.
FEEDS: tuple[str, ...] = (
    "EUR/USD.DERIV",
    "GBP/USD.DERIV",
    "GOLD.DERIV",
    "BTC.DERIV",
    "US100.FOREXCOM",
    "SPX500.PEPPERSTONE",
)


@dataclass(frozen=True, slots=True)
class Cell:
    """One leaf on one instrument."""

    rule: str
    entry: str
    feed: str
    positions: int
    orders: int
    pnl: float
    seconds: float
    note: str = ""


def one(rule: str, entry: str, feed: str, spec: str) -> Cell:
    """Run a single leaf over a single instrument.

    The environment is set per cell rather than once, because `desks.build`
    reads it at construction and a sweep that set it once would run every cell
    as the first one.
    """
    from nautilus_trader.backtest.node import BacktestNode

    # **`TRADING_STRATEGIES`, not `TRADING_RULES`.** `desks.rules` reads the
    # former and falls back to `("statespace-surprise",)`, so a sweep setting
    # the latter silently built the same leaf 72 times and reported it as a
    # result for four rules.
    os.environ["TRADING_STRATEGIES"] = rule
    os.environ["TRADING_ENTRIES"] = entry
    os.environ["TRADING_SYMBOLS"] = feed.rsplit(".", 1)[0]

    from till_infinity.node.backtest import desk_config

    started = time.perf_counter()
    try:
        config = desk_config(feed, spec)
        results = BacktestNode(configs=[config]).run()
    except Exception as exc:  # a cell that cannot run is a cell, not a stop
        return Cell(
            rule=rule,
            entry=entry,
            feed=feed,
            positions=0,
            orders=0,
            pnl=0.0,
            seconds=time.perf_counter() - started,
            note=f"{type(exc).__name__}: {exc}"[:160],
        )

    found = results[0]
    pnls = getattr(found, "stats_pnls", None) or {}
    total = 0.0
    for byccy in pnls.values():
        if isinstance(byccy, dict):
            total += float(byccy.get("PnL (total)", 0.0) or 0.0)
    return Cell(
        rule=rule,
        entry=entry,
        feed=feed,
        positions=int(getattr(found, "total_positions", 0) or 0),
        orders=int(getattr(found, "total_orders", 0) or 0),
        pnl=total,
        seconds=time.perf_counter() - started,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=".data/out/leaf_sweep")
    parser.add_argument("--spec", default="15-MINUTE-LAST-EXTERNAL")
    parser.add_argument("--rules", default="")
    parser.add_argument("--entries", default="")
    parser.add_argument("--feeds", default="")
    args = parser.parse_args()

    from till_infinity.strategies.leaves import ENTRIES, RULES

    rules = tuple(args.rules.split(",")) if args.rules else tuple(RULES)
    entries = tuple(args.entries.split(",")) if args.entries else tuple(ENTRIES)
    feeds = tuple(args.feeds.split(",")) if args.feeds else FEEDS

    import pathlib

    where = pathlib.Path(args.out)
    where.mkdir(parents=True, exist_ok=True)
    sink = where / "cells.jsonl"

    total = len(rules) * len(entries) * len(feeds)
    done = 0
    with sink.open("w") as handle:
        for rule in rules:
            for entry in entries:
                for feed in feeds:
                    cell = one(rule, entry, feed, args.spec)
                    handle.write(json.dumps(asdict(cell)) + "\n")
                    handle.flush()
                    done += 1
                    print(
                        f"[{done}/{total}] {rule:20s} {entry:8s} {feed:20s} "
                        f"pos {cell.positions:4d} pnl {cell.pnl:+12.2f} "
                        f"{cell.seconds:5.1f}s {cell.note}",
                        file=sys.stderr,
                        flush=True,
                    )
    print(f"wrote {sink}")


if __name__ == "__main__":
    main()
