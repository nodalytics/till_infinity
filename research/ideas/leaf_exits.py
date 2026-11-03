"""Every valid leaf, on both exits, over every catalogue instrument.

The sweep `leaf_sweep.py` could not run. It reported `+0.00 over 0 positions`
for nine of its twelve leaves, and that was not a measurement: three defects
sat between a configured desk and an order, and each alone was enough to zero
a cell.

* `BacktestNode` disposes the engine before `get_result()` reads
  `cache.orders_total_count()`, so **every** run reported 0 orders and 0
  positions whatever it did, while `stats_pnls` - computed off the portfolio
  analyzer - carried the real figure next to it.
* `StatespaceActor` folded only `('1m', '5m')` while the catalogue holds
  nothing but 15-minute bars, so `observe_bar` returned `None` on all 5,135
  bars of a run. That return also covers "unwarmed" and "no variance", so
  there was no log line to find.
* The actor restored its fold progress on start, and `observe_bar` refuses a
  bar at or before the last one folded. The first cell of a sweep saved
  progress at the window's end and every later cell was rejected bar for bar.

All three are fixed and pinned. This harness is the measurement they were
blocking, with the exit added as a dimension.

## What a cell is

One `(rule, entry)` leaf from `strategies/leaves.LEAVES` - the **valid**
pairings only, which is ten and not twelve - on one of the two exits in
`leaves.EXITS`, on one catalogue instrument. Ten leaves, two exits, six
instruments: **120 cells.**

`leaf_sweep.py` swept the cross product instead and spent twelve of its
seventy-two cells raising `there is no 'smc-bos-causal' desk on the 'arrival'
entry`. A refusal is not a result and is not counted as one here.

## What this settles, and what it cannot

**Mechanics, firing rates and cost sensitivity. Not an edge.**
`node/corpus.py` fills the catalogue with about 76 days of 15-minute bars for
six feeds, and the quotes are modelled - one per bar at the measured median
spread for that feed on that venue. So a cell is 4 to 18 positions, which is
far below the ~100 where a per-trade mean stops being noise.

120 cells at a 5% threshold gives six positive cells from chance alone. The
figure to read here is **whether a leaf places orders at all, how many, and on
which side of zero**, not which cell won. `discovery.gate_from` exists because
reporting the best of a sweep as though it were the only one is the error.

The one rule in this set reconciled against its specification reads
**-0.533R a trade** over 75 trades with a day-block interval of
[-0.830, -0.237]; see `research/docs/smc-bos-reconcile.md`.

## PnL units

Account currency, in the catalogue's own instrument conventions rather than
the broker's - see `node/corpus.py`. A sign and a trade count survive that; a
money total is not comparable to the live desk's. `venue()` reports the terms
every cell ran under, and they are printed once at the top.
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
    """One leaf, on one exit, on one instrument."""

    rule: str
    entry: str
    exit: str
    feed: str
    positions: int
    orders: int
    events: int
    pnl: float
    win_rate: float
    expectancy: float
    seconds: float
    note: str = ""


def one(rule: str, entry: str, exit_: str, feed: str, spec: str) -> Cell:
    """Run a single cell.

    The environment is set per cell rather than once, because `desks.build`
    reads it at construction: a sweep that set it once would run every cell as
    the first one.
    """
    from nautilus_trader.backtest.node import BacktestNode

    # `TRADING_STRATEGIES`, not `TRADING_RULES`. `desks.rules` reads the former
    # and falls back to `("statespace-surprise",)`, so a sweep setting the
    # latter silently built one leaf for every cell and reported it as a result
    # for four rules.
    os.environ["TRADING_STRATEGIES"] = rule
    os.environ["TRADING_ENTRIES"] = entry
    os.environ["TRADING_EXITS"] = exit_
    os.environ["TRADING_SYMBOLS"] = feed.rsplit(".", 1)[0]

    from till_infinity.node.backtest import desk_config

    started = time.perf_counter()
    try:
        results = BacktestNode(configs=[desk_config(feed, spec)]).run()
    except Exception as exc:  # a cell that cannot run is a cell, not a stop
        return Cell(
            rule=rule,
            entry=entry,
            exit=exit_,
            feed=feed,
            positions=0,
            orders=0,
            events=0,
            pnl=0.0,
            win_rate=float("nan"),
            expectancy=float("nan"),
            seconds=time.perf_counter() - started,
            note=f"{type(exc).__name__}: {exc}"[:200],
        )

    found = results[0]
    # Summed over currencies: a venue with two would otherwise report whichever
    # `dict` order happened to put first.
    byccy = getattr(found, "stats_pnls", None) or {}
    total = 0.0
    wins: list[float] = []
    expect: list[float] = []
    for stats in byccy.values():
        if not isinstance(stats, dict):
            continue
        total += float(stats.get("PnL (total)", 0.0) or 0.0)
        if stats.get("Win Rate") is not None:
            wins.append(float(stats["Win Rate"]))
        if stats.get("Expectancy") is not None:
            expect.append(float(stats["Expectancy"]))

    return Cell(
        rule=rule,
        entry=entry,
        exit=exit_,
        feed=feed,
        positions=int(getattr(found, "total_positions", 0) or 0),
        orders=int(getattr(found, "total_orders", 0) or 0),
        events=int(getattr(found, "total_events", 0) or 0),
        pnl=total,
        win_rate=sum(wins) / len(wins) if wins else float("nan"),
        expectancy=sum(expect) / len(expect) if expect else float("nan"),
        seconds=time.perf_counter() - started,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=".data/out/leaf_exits")
    parser.add_argument("--spec", default="15-MINUTE-LAST-EXTERNAL")
    parser.add_argument("--leaves", default="", help="rule:entry pairs, comma separated")
    parser.add_argument("--exits", default="", help="default every name in leaves.EXITS")
    parser.add_argument("--feeds", default="")
    args = parser.parse_args()

    from till_infinity.node.backtest import described
    from till_infinity.strategies.leaves import EXITS, LEAVES

    # **The valid pairings, not the cross product.** `smc-bos-causal` exists
    # only on `edge`, so a cross product spends a sixth of its cells raising.
    if args.leaves:
        pairs = tuple(tuple(p.split(":", 1)) for p in args.leaves.split(","))  # type: ignore[misc]
    else:
        pairs = tuple(sorted(LEAVES))
    exits = tuple(args.exits.split(",")) if args.exits else tuple(EXITS)
    feeds = tuple(args.feeds.split(",")) if args.feeds else FEEDS

    import pathlib

    where = pathlib.Path(args.out)
    where.mkdir(parents=True, exist_ok=True)
    sink = where / "cells.jsonl"

    total = len(pairs) * len(exits) * len(feeds)
    print(f"venue: {described()}", file=sys.stderr)
    print(
        f"{total} cells = {len(pairs)} valid leaves x {len(exits)} exits x {len(feeds)} feeds",
        file=sys.stderr,
    )
    done = 0
    with sink.open("w") as handle:
        for rule, entry in pairs:
            for exit_ in exits:
                for feed in feeds:
                    cell = one(rule, entry, exit_, feed, args.spec)
                    handle.write(json.dumps(asdict(cell)) + "\n")
                    handle.flush()
                    done += 1
                    print(
                        f"[{done}/{total}] {rule:20s} {entry:8s} {exit_:8s} {feed:19s} "
                        f"pos {cell.positions:3d} ord {cell.orders:3d} "
                        f"pnl {cell.pnl:+10.2f} {cell.seconds:5.1f}s {cell.note}",
                        file=sys.stderr,
                        flush=True,
                    )
    print(f"wrote {sink}")


if __name__ == "__main__":
    main()
