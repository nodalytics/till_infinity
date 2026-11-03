"""What would make a band rule pay: the payoff ratio, not the entry.

Twelve estimators over six instruments, crossed with the exit policy and the
per-side stop asymmetry. The question is **not** whether a moving average
predicts direction - `direction-is-closed-not-just-null` records the direction
gate finding a planted drift at z +2.90 while earning 2% of a spread - but
whether the payoff shape a trend rule produces can clear its own break-even.

## The null, written first

A trend rule wins a minority of its trades and needs a right tail to pay for
them. At a win rate `w` the break-even payoff ratio is `(1 - w) / w`: at 0.26
it is **2.85**, at 0.33 it is 2.03, at 0.40 it is 1.50. So the statistic this
file reports is `Avg Winner / |Avg Loser|` **against that bar**, per cell,
beside the win rate that sets it.

And the deeper null is `1/(1+N)`: on a driftless walk the chance of reaching
`+N R` before `-1R` is exactly `1/(N+1)`, so **reward-to-risk alone has
expected value zero** and a payoff ratio of 2.85 earned by moving a target out
to 2.85R is not an edge - it is the same zero reshaped. A payoff ratio only
means something when the trade count holds up as the ratio rises, which is
what the policy columns here are for: break-even and trailing change the
*shape* of the exit without moving a target.

## The three asymmetries, each from something measured here

* **The exit.** `exit_turn='both'` closes winners **and** losers on the
  opposite cross, which caps every winner at the next cross - the symmetric
  exit, and the opposite of the asymmetry a trend rule needs.
  `fade-to-value-loses-on-the-entry-not-the-target` measured entries bleeding
  -10.81 while targets paid +28.16 on the same setups, so the arm that lets
  winners run to a trail while losers exit on the turn is the one with a prior.
* **The side.** `fear-greed.md` measured down swings **33% faster** (-0.285, z
  -3.68) and up swings **21% longer**, with the speed gap negative in 6 of 6
  eras against 3 of 6 on the placebo. That says a short wants a tighter stop
  than a long, which is what `stop_tilt` carries - and the tilt preserves the
  geometric mean, so a tilted cell and a neutral one have the same average
  stop and differ only in asymmetry. `refit-the-parameter-a-lever-multiplies`
  is why that matters: a multiplier whose mean is not 1 reversed a +1192
  result to -24 by moving the average rather than the asymmetry.
* **The horizon.** `stop-coverage.md`, measured today: a flat 3.0-unit stop is
  reached **0.477** of the time over a 20-bar hold against a 0.100 target, and
  0.750 over 96 bars. A trend trade whose stop does not scale with its
  intended hold is stopped out before the trend it is waiting for develops.
  `stop_vol` is swept here for that reason rather than for tuning.

## What this cannot settle

`node/corpus.py` holds about 76 days of 15-minute bars for six feeds and the
quotes are modelled - one per bar at the measured median spread for that feed
on that venue. A cell is 20 to 231 positions, so the better cells are near the
~100 where a per-trade mean stops being noise and none is past it.

576 cells at a 5% threshold gives **29 positive cells from chance alone**, so
no individual cell is a result. What the grid can show is whether a *column*
moves the payoff ratio consistently across estimators and feeds - a policy
that helps 12 of 12 estimators is a different claim from the best of 576
cells, and only the first is reportable.

Costs are set by the stop and not the target: cost in R is `cost_px / risk`,
so the `stop_vol` column moves the cost per trade and the `target` column
would not. That is why there is no target column.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from dataclasses import asdict, dataclass

FEEDS: tuple[str, ...] = (
    "EUR/USD.DERIV",
    "GBP/USD.DERIV",
    "GOLD.DERIV",
    "BTC.DERIV",
    "US100.FOREXCOM",
    "SPX500.PEPPERSTONE",
)

#: FX and crypto specifically, which is where the claim being tested was made.
MAJORS: tuple[str, ...] = ("EUR/USD.DERIV", "GBP/USD.DERIV", "BTC.DERIV")


@dataclass(frozen=True, slots=True)
class Cell:
    kind: str
    feed: str
    stop_vol: float
    stop_tilt: float
    break_even: float
    trail: float
    exit_turn: str
    positions: int
    orders: int
    pnl: float
    win_rate: float
    expectancy: float
    avg_win: float
    avg_loss: float
    max_win: float
    max_loss: float
    seconds: float
    note: str = ""

    @property
    def payoff(self) -> float:
        """`Avg Winner / |Avg Loser|`, the ratio the win rate sets a bar for."""
        return self.avg_win / abs(self.avg_loss) if self.avg_loss else float("nan")

    @property
    def needed(self) -> float:
        """`(1 - w) / w`: the payoff ratio this win rate has to clear."""
        w = self.win_rate
        return (1.0 - w) / w if 0.0 < w < 1.0 else float("nan")


def one(
    kind: str,
    feed: str,
    *,
    stop_vol: float,
    stop_tilt: float,
    break_even: float,
    trail: float,
    exit_turn: str,
    spec: str,
) -> Cell:
    """One cell. The environment is set per cell because `desks.build` and
    `bands.Tuning.read` both read it at construction - a sweep that set it once
    would run all 576 cells as the first one."""
    from nautilus_trader.backtest.node import BacktestNode

    os.environ["TRADING_STRATEGIES"] = "bands"
    os.environ["TRADING_ENTRIES"] = "edge"
    os.environ["TRADING_EXITS"] = "managed"
    os.environ["TRADING_SYMBOLS"] = feed.rsplit(".", 1)[0]
    os.environ["TRADING_BAND_KIND"] = kind
    os.environ["TRADING_BAND_STOP_VOL"] = str(stop_vol)
    os.environ["TRADING_BAND_STOP_TILT"] = str(stop_tilt)
    os.environ["TRADING_BAND_EXIT_TURN"] = exit_turn
    os.environ["TRADING_BREAK_EVEN_AT"] = str(break_even)
    os.environ["TRADING_TRAIL_VOL"] = str(trail)

    from till_infinity.node.backtest import desk_config

    started = time.perf_counter()
    blank = {
        "kind": kind,
        "feed": feed,
        "stop_vol": stop_vol,
        "stop_tilt": stop_tilt,
        "break_even": break_even,
        "trail": trail,
        "exit_turn": exit_turn,
    }
    try:
        found = BacktestNode(configs=[desk_config(feed, spec)]).run()
    except Exception as exc:
        return Cell(
            **blank,
            positions=0,
            orders=0,
            pnl=0.0,
            win_rate=float("nan"),
            expectancy=float("nan"),
            avg_win=0.0,
            avg_loss=0.0,
            max_win=0.0,
            max_loss=0.0,
            seconds=time.perf_counter() - started,
            note=f"{type(exc).__name__}: {exc}"[:200],
        )
    if not found:
        return Cell(
            **blank,
            positions=0,
            orders=0,
            pnl=0.0,
            win_rate=float("nan"),
            expectancy=float("nan"),
            avg_win=0.0,
            avg_loss=0.0,
            max_win=0.0,
            max_loss=0.0,
            seconds=time.perf_counter() - started,
            note="the engine returned no result",
        )

    result = found[0]
    stats: dict = {}
    for byccy in (getattr(result, "stats_pnls", None) or {}).values():
        if isinstance(byccy, dict):
            stats = byccy
            break

    def num(name: str) -> float:
        value = stats.get(name)
        return float(value) if value is not None else 0.0

    return Cell(
        **blank,
        positions=int(getattr(result, "total_positions", 0) or 0),
        orders=int(getattr(result, "total_orders", 0) or 0),
        pnl=num("PnL (total)"),
        win_rate=num("Win Rate"),
        expectancy=num("Expectancy"),
        avg_win=num("Avg Winner"),
        avg_loss=num("Avg Loser"),
        max_win=num("Max Winner"),
        max_loss=num("Max Loser"),
        seconds=time.perf_counter() - started,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=".data/out/band_asymmetry")
    parser.add_argument("--spec", default="15-MINUTE-LAST-EXTERNAL")
    parser.add_argument("--kinds", default="")
    parser.add_argument("--feeds", default="", help="'majors' for FX and crypto only")
    parser.add_argument("--stop-vols", default="1.5,3.0")
    parser.add_argument("--stop-tilts", default="1.0,2.0")
    parser.add_argument("--break-evens", default="0,1.0")
    parser.add_argument("--trails", default="0,2.0")
    parser.add_argument(
        "--turn-exits",
        default="both,losers,never",
        help="what the opposite cross closes. `both` is the conventional "
        "crossover rule; `losers` cuts the left tail and leaves the right one "
        "to the stop and the trail, which is the asymmetric arm with a prior; "
        "`never` is the control that shows what the turn exit is worth (6 "
        "positions over 5,135 bars, since only a stop ends a trade).",
    )
    args = parser.parse_args()

    from till_infinity.node.backtest import described
    from till_infinity.strategies.bands import KINDS

    kinds = tuple(args.kinds.split(",")) if args.kinds else KINDS
    if args.feeds == "majors":
        feeds = MAJORS
    elif args.feeds:
        feeds = tuple(args.feeds.split(","))
    else:
        feeds = FEEDS
    stop_vols = tuple(float(v) for v in args.stop_vols.split(","))
    stop_tilts = tuple(float(v) for v in args.stop_tilts.split(","))
    break_evens = tuple(float(v) for v in args.break_evens.split(","))
    trails = tuple(float(v) for v in args.trails.split(","))
    turn_exits = tuple(v.strip() for v in args.turn_exits.split(","))

    import pathlib

    where = pathlib.Path(args.out)
    where.mkdir(parents=True, exist_ok=True)
    sink = where / "cells.jsonl"

    grid = list(
        itertools.product(kinds, feeds, stop_vols, stop_tilts, break_evens, trails, turn_exits)
    )
    print(f"venue: {described()}", file=sys.stderr)
    print(
        f"{len(grid)} cells = {len(kinds)} kinds x {len(feeds)} feeds x "
        f"{len(stop_vols)} stops x {len(stop_tilts)} tilts x "
        f"{len(break_evens)} break-evens x {len(trails)} trails x "
        f"{len(turn_exits)} turn-exits",
        file=sys.stderr,
    )
    done = 0
    with sink.open("w") as handle:
        for kind, feed, stop_vol, tilt, even, trail, turn in grid:
            cell = one(
                kind,
                feed,
                stop_vol=stop_vol,
                stop_tilt=tilt,
                break_even=even,
                trail=trail,
                exit_turn=turn,
                spec=args.spec,
            )
            handle.write(json.dumps(asdict(cell)) + "\n")
            handle.flush()
            done += 1
            print(
                f"[{done}/{len(grid)}] {kind:9s} {feed:19s} sv{stop_vol:<4} t{tilt:<4} "
                f"be{even:<4} tr{trail:<4} {turn:6s} "
                f"pos {cell.positions:4d} pnl {cell.pnl:+9.2f} "
                f"w {cell.win_rate:.2f} pay {cell.payoff:5.2f}/{cell.needed:5.2f} "
                f"{cell.seconds:4.1f}s {cell.note}",
                file=sys.stderr,
                flush=True,
            )
    print(f"wrote {sink}")


if __name__ == "__main__":
    main()
