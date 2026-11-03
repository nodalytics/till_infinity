"""Bjorgum key levels, every style and every asymmetry, through the engine.

`strategies/zones.py` gives `indicators/levels.BjorgumLevels` its first caller.
This is what decides whether it should keep one.

## The grid

* **Four styles**, two reversal and two continuation, because nothing on this
  desk has pinned the sign of a level: `reject` (the zone held), `break` (it
  failed), `retest` (broken, revisited, leaving again on the break side) and
  `flip` (the bar its role changes).
* **Two presets.** `script` is the published indicator's own defaults - 20/15
  pivots, ATR 30, four zones a side, Heikin-Ashi bodies. `measured` is what
  `bjorgum.md` was run on - symmetric 5/5, ATR 14, ten zones, raw high/low.
  Mixing them gives numbers belonging to neither configuration.
* **Three pivot sources.** The wick (`high_low`), the body
  (`high_low_body`) and Heikin-Ashi (`ha`). The wick is where price reached
  and includes every stop-run; the body is where the auction settled. On an
  instrument whose round trip is a whole bar range - the exotics measured at
  **0.40 to 0.97** of one - the wick is partly spread.
* **Two asymmetries, both `Sided`** so the geometric mean is fixed and a tilt
  of 1 is exactly neutral: the zone width (`mult_tilt`) and the stop
  (`stop_tilt`). `refit-the-parameter-a-lever-multiplies` is why that matters -
  a multiplier whose mean was not 1 reversed a +1192 result to -24 by moving
  the average rather than the asymmetry.

## What is reported, and the bar it is read against

**The payoff ratio against its own break-even**, not the win rate. A rule
winning a minority of its trades needs `(1 - w) / w`: at 0.25 that is 3.00, at
0.43 it is 1.33. `band_asymmetry.py` measured the same quantity over 2,304
cells and **112 cleared**, with break-even hurting it in 92% of paired cells
and trailing in 76% - so the exit policy is held fixed here and the sweep is
over the level's own geometry.

And the deeper null is `1/(1+N)`: reward-to-risk alone has expected value zero,
so a payoff ratio earned by moving a target out is the same zero reshaped.
There is no target column for that reason; the stop sets the cost, since cost
in R is `cost_px / risk`.

## What this cannot settle

`node/corpus.py` holds about 76 days of 15-minute bars for six feeds, with
modelled quotes at the measured median spread per feed and venue. Cells run 74
to 122 positions on the better styles, which is near the ~100 where a per-trade
mean stops being noise and not past it.

**576 cells** - four styles x two presets x three sources x two width tilts x
two stop tilts x six feeds - and at a 5% threshold that is **29 positive cells
from chance alone**, so no single cell is a result. What the grid can show is
whether a *column* moves the payoff consistently across styles and feeds: a
source or a tilt that helps 12 of 12 paired cells is a different claim from the
best of 576, and only the first is reportable.

The entry side of levels is already closed here: `magnet.md` measured a level
reached 44.9% of the time against **49.5% for an arbitrary price the same
distance away**, and `level-shield.md` found real below its hardest null in 188
of 210 cells. A positive cell in this grid is a candidate for a measurement,
not a finding.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
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


@dataclass(frozen=True, slots=True)
class Cell:
    mode: str
    preset: str
    pivots: str
    mult_tilt: float
    stop_tilt: float
    stop_vol: float
    feed: str
    positions: int
    orders: int
    pnl: float
    win_rate: float
    expectancy: float
    avg_win: float
    avg_loss: float
    seconds: float
    note: str = ""

    @property
    def payoff(self) -> float:
        return self.avg_win / abs(self.avg_loss) if self.avg_loss else float("nan")

    @property
    def needed(self) -> float:
        """`(1 - w) / w`, the ratio this win rate has to clear."""
        w = self.win_rate
        return (1.0 - w) / w if 0.0 < w < 1.0 else float("nan")

    @property
    def clears(self) -> bool:
        p, n = self.payoff, self.needed
        return not math.isnan(p) and not math.isnan(n) and p >= n


def one(
    *,
    mode: str,
    preset: str,
    pivots: str,
    mult_tilt: float,
    stop_tilt: float,
    stop_vol: float,
    feed: str,
    spec: str,
) -> Cell:
    """One cell. The environment is set per cell because `desks.build` and
    `zones.Tuning.read` both read it at construction - a sweep setting it once
    would run every cell as the first one."""
    from nautilus_trader.backtest.node import BacktestNode

    os.environ["TRADING_STRATEGIES"] = "zones"
    os.environ["TRADING_ENTRIES"] = "edge"
    os.environ["TRADING_EXITS"] = "managed"
    os.environ["TRADING_SYMBOLS"] = feed.rsplit(".", 1)[0]
    os.environ["TRADING_ZONE_MODE"] = mode
    os.environ["TRADING_ZONE_PRESET"] = preset
    os.environ["TRADING_ZONE_PIVOTS"] = pivots
    os.environ["TRADING_ZONE_MULT_TILT"] = str(mult_tilt)
    os.environ["TRADING_ZONE_STOP_TILT"] = str(stop_tilt)
    os.environ["TRADING_ZONE_STOP_VOL"] = str(stop_vol)
    # Held fixed: `band_asymmetry.py` measured both hurting the payoff ratio -
    # break-even in 92% of paired cells, the trail in 76% - so sweeping them
    # again here would spend cells re-measuring a known column.
    os.environ["TRADING_BREAK_EVEN_AT"] = "0"
    os.environ["TRADING_TRAIL_VOL"] = "0"

    from till_infinity.node.backtest import desk_config

    blank = {
        "mode": mode,
        "preset": preset,
        "pivots": pivots,
        "mult_tilt": mult_tilt,
        "stop_tilt": stop_tilt,
        "stop_vol": stop_vol,
        "feed": feed,
    }
    started = time.perf_counter()

    def empty(note: str) -> Cell:
        return Cell(
            **blank,
            positions=0,
            orders=0,
            pnl=0.0,
            win_rate=float("nan"),
            expectancy=float("nan"),
            avg_win=0.0,
            avg_loss=0.0,
            seconds=time.perf_counter() - started,
            note=note,
        )

    try:
        found = BacktestNode(configs=[desk_config(feed, spec)]).run()
    except Exception as exc:
        return empty(f"{type(exc).__name__}: {exc}"[:200])
    if not found:
        return empty("the engine returned no result")

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
        seconds=time.perf_counter() - started,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=".data/out/zone_asymmetry")
    parser.add_argument("--spec", default="15-MINUTE-LAST-EXTERNAL")
    parser.add_argument("--modes", default="")
    parser.add_argument("--presets", default="script,measured")
    parser.add_argument("--pivots", default="ha,high_low,high_low_body")
    parser.add_argument("--mult-tilts", default="1.0,2.0")
    parser.add_argument("--stop-tilts", default="1.0,2.0")
    parser.add_argument("--stop-vols", default="3.0")
    parser.add_argument("--feeds", default="")
    args = parser.parse_args()

    from till_infinity.node.backtest import described
    from till_infinity.strategies.zones import MODES

    modes = tuple(args.modes.split(",")) if args.modes else MODES
    presets = tuple(args.presets.split(","))
    pivots = tuple(args.pivots.split(","))
    mults = tuple(float(v) for v in args.mult_tilts.split(","))
    stops = tuple(float(v) for v in args.stop_tilts.split(","))
    vols = tuple(float(v) for v in args.stop_vols.split(","))
    feeds = tuple(args.feeds.split(",")) if args.feeds else FEEDS

    import pathlib

    where = pathlib.Path(args.out)
    where.mkdir(parents=True, exist_ok=True)
    sink = where / "cells.jsonl"

    grid = list(itertools.product(modes, presets, pivots, mults, stops, vols, feeds))
    print(f"venue: {described()}", file=sys.stderr)
    print(
        f"{len(grid)} cells = {len(modes)} modes x {len(presets)} presets x "
        f"{len(pivots)} sources x {len(mults)} width tilts x "
        f"{len(stops)} stop tilts x {len(vols)} stops x {len(feeds)} feeds",
        file=sys.stderr,
    )
    done = 0
    with sink.open("w") as handle:
        for mode, preset, source, mult, stop, vol, feed in grid:
            cell = one(
                mode=mode,
                preset=preset,
                pivots=source,
                mult_tilt=mult,
                stop_tilt=stop,
                stop_vol=vol,
                feed=feed,
                spec=args.spec,
            )
            handle.write(json.dumps(asdict(cell)) + "\n")
            handle.flush()
            done += 1
            print(
                f"[{done}/{len(grid)}] {mode:7s} {preset:8s} {source:14s} "
                f"w{mult:<4} s{stop:<4} v{vol:<4} {feed:19s} "
                f"pos {cell.positions:4d} pnl {cell.pnl:+9.2f} "
                f"w {cell.win_rate:.2f} pay {cell.payoff:5.2f}/{cell.needed:5.2f} "
                f"{'CLEARS' if cell.clears else ''} {cell.seconds:4.1f}s {cell.note}",
                file=sys.stderr,
                flush=True,
            )
    print(f"wrote {sink}")


if __name__ == "__main__":
    main()
