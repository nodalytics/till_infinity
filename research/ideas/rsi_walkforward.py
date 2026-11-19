"""Does last week's best combination pay next week.

[`rsi-ma-momentum.md`](../docs/rsi-ma-momentum.md) ranked 414 RSI-and-average
times momentum cells on seven days and found the leaders lost over the
preceding month, with a day-shuffled market's best-of-grid beating the real
one. That is one week looked at twice. **This is the same question asked of
every week there is**, which is the control the original request really wants:

    rank the grid on week w-1, take the top k, and score those k on week w.

Three things to compare it against, and the second is the one that matters:

* **every cell's mean in week `w`** - what picking at random from the same grid
  pays. If the top-k does not beat this, selection carries nothing, and
  `duty-cycle` is the standing version of the same argument: on a losing book
  any rule that trades less looks better, so the baseline has to be a twin that
  selects as often.
* **the bottom k of week `w-1`**, scored on week `w`. If last week's *worst*
  cells do as well as last week's best, the ranking is noise with a sign on it.
  This arm is cheap and it is the sharpest of the three.
* **the best cell of week `w` itself** - the hindsight ceiling, which says how
  much was there to be had if selection were perfect.

One continuous race per cell over the whole history, bucketed into weeks
afterwards. **Not a race restarted at each week edge**: restarting lets every
week open with a free entry that the previous week's open position would have
blocked, which is a small look-ahead that favours whichever arm trades most.

Run as:

    uv run python research/ideas/rsi_walkforward.py --frames 15m --years 2
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reactive_zones import CATALOGUE, atr, fold, load, shuffled, window  # noqa: E402
from rsi_momentum import SPREADS, SYMBOLS, Cell, Readings, cells, race, sided  # noqa: E402

DAY = 86_400_000_000_000


@dataclass(slots=True)
class Ledger:
    """Every trade a cell made, with the entry timestamp.

    Bucketed by the caller rather than here, so one race serves every window
    length in a sweep - a 3-day bucketing and a 14-day one are the same trades
    counted differently, and re-racing them per window would be three times
    the work for identical outcomes.
    """

    ts: np.ndarray
    net: np.ndarray


def ledger(symbol: str, frame: str, arm: str, args: argparse.Namespace) -> dict[int, Ledger]:
    """One continuous race per cell, over the whole window, bucketed by week."""
    base = load(Path(args.catalogue), symbol)
    series = shuffled(base, seed=23) if arm == "shuffled" else base
    if args.years > 0 or args.before > 0:
        series = window(series, args.years, args.before)
    bars = series if frame == args.unit else fold(series, frame, unit=args.unit)
    band = atr(bars)
    every = cells(args)
    cache = Readings.of(bars, band, every)
    points, tick = SPREADS[symbol]
    cost = points * tick
    out: dict[int, Ledger] = {}
    for index, cell in enumerate(every):
        side = sided(bars, band, cell, args, cache)
        got = race(bars, band, side, args.stop, cell.reward, args.patience, cost)
        if got.trades == 0:
            continue
        out[index] = Ledger(ts=bars.ts[got.at].astype(np.int64), net=got.values)
    return out


def bucketed(book: dict[int, Ledger], days: float) -> dict[int, dict[int, tuple[int, float]]]:
    """`{window: {cell: (trades, mean net)}}` at a window of `days`."""
    width = int(days * DAY)
    out: dict[int, dict[int, tuple[int, float]]] = {}
    for index, rows in book.items():
        keys = rows.ts // width
        for w in np.unique(keys):
            pick = keys == w
            out.setdefault(int(w), {})[index] = (int(pick.sum()), float(rows.net[pick].mean()))
    return out


def walk(
    table: dict[int, dict[int, tuple[int, float]]], top: int, least: int
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Scored on the next week: the top k, the bottom k, every cell, the best."""
    weeks = sorted(table)
    chosen, worst, average, ceiling = [], [], [], []
    for previous, current in zip(weeks, weeks[1:], strict=False):
        if current - previous != 1:
            # A gap means a week with no trades anywhere, so there is no
            # ranking to carry forward across it.
            continue
        ranked = [(net, i) for i, (n, net) in table[previous].items() if n >= least]
        if len(ranked) < top * 2:
            continue
        ranked.sort(reverse=True)
        here = table[current]
        live = [net for n, net in here.values() if n >= 1]
        if not live:
            continue
        best = [here[i][1] for _, i in ranked[:top] if i in here]
        tail = [here[i][1] for _, i in ranked[-top:] if i in here]
        if not best or not tail:
            continue
        chosen.append(float(np.mean(best)))
        worst.append(float(np.mean(tail)))
        average.append(float(np.mean(live)))
        ceiling.append(float(np.max(live)))
    return chosen, worst, average, ceiling


def report(name: str, chosen: list[float], worst: list[float], average: list[float], ceiling: list[float]) -> None:
    if len(chosen) < 8:
        print(f"  {name}: {len(chosen)} usable window pairs, too few")
        return
    picked, tail, mean, top = (np.asarray(v) for v in (chosen, worst, average, ceiling))
    lift = picked - mean
    spread = lift.std(ddof=1) / np.sqrt(lift.size)
    print(
        f"  {name}: {picked.size} window pairs\n"
        f"    the window's top k, the next     {picked.mean():+.4f}R\n"
        f"    the window's bottom k, the next  {tail.mean():+.4f}R\n"
        f"    every cell, the next window      {mean.mean():+.4f}R\n"
        f"    the best cell of the next        {top.mean():+.4f}R   (hindsight ceiling)\n"
        f"    top k minus every cell           {lift.mean():+.4f}R +/- {1.96 * spread:.4f}, "
        f"beat it in {int((lift > 0).sum())} of {lift.size} windows\n"
        f"    top k minus bottom k             {(picked - tail).mean():+.4f}R{_against(picked - tail)}"
    )


def _against(gap: np.ndarray, draws: int = 2000, seed: int = 61) -> str:
    """A bootstrap, a median and a sign count on the top-minus-bottom arm.

    **The unbiased arm needs all three**, because its mean can be carried by a
    handful of windows: the top-k and the grid average are different
    populations (selection picks particular geometry, which a shuffled market
    reproduces), while the top-k and the bottom-k are the same grid sorted two
    ways. Resampling whole window pairs is the block here - a window's trades
    are one block and the pairs are the independent unit.
    """
    if gap.size < 20:
        return ""
    rng = np.random.default_rng(seed)
    draw = gap[rng.integers(0, gap.size, (draws, gap.size))].mean(axis=1)
    return (
        f", 90% [{np.percentile(draw, 5):+.4f}, {np.percentile(draw, 95):+.4f}]"
        f", median {float(np.median(gap)):+.4f}"
        f", positive in {int((gap > 0).sum())} of {gap.size}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--frames", default="15m")
    parser.add_argument("--unit", default="5m")
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument(
        "--before",
        type=float,
        default=0.0,
        help="end the window this many years ago, for a disjoint confirmation half",
    )
    parser.add_argument("--arms", default="real,shuffled")
    parser.add_argument("--top", default="1,3,10")
    parser.add_argument(
        "--windows",
        default="14,7,3",
        help="ranking window lengths in days; the same races are bucketed at each",
    )
    parser.add_argument(
        "--least",
        type=int,
        default=8,
        help="trades a cell needs to be ranked, scaled down with the window",
    )
    parser.add_argument("--families", default="rsi,ma")
    parser.add_argument("--rsi", default="7,14,21")
    parser.add_argument("--ma", default="20,50,100")
    parser.add_argument("--reach", default="5,10,20")
    parser.add_argument("--thresholds", default="20,25,30,35")
    parser.add_argument("--stretch", default="1.0,1.5,2.0,2.5")
    parser.add_argument("--reward", default="1,2")
    parser.add_argument("--stop", type=float, default=1.0)
    parser.add_argument("--patience", type=int, default=48)
    parser.add_argument("--fresh", type=int, default=3)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()

    names = [s for s in args.symbols.split(",") if s]
    frames = [f.strip() for f in args.frames.split(",") if f.strip()]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    tail = f" ending {args.before:g}y ago" if args.before > 0 else ""
    print(
        f"{len(cells(args))} cells  {args.years:g}y{tail}  frames {','.join(frames)}  "
        f"top {args.top}  windows {args.windows}d  symbols {args.symbols}"
    )

    jobs = [(s, f, a) for f in frames for a in arms for s in names]
    if args.workers > 1:
        import multiprocessing as mp

        # One thread per worker: `one-thread-per-pool-worker` measured sklearn
        # driving the lab's load to 658 on 64 cores without it. Nothing here
        # uses BLAS, but the pool is the same shape and the habit is cheap.
        with mp.Pool(min(args.workers, len(jobs))) as pool:
            books = pool.starmap(ledger, [(s, f, a, args) for s, f, a in jobs])
    else:
        books = [ledger(s, f, a, args) for s, f, a in jobs]

    for frame in frames:
        for arm in arms:
            for days in (float(v) for v in args.windows.split(",")):
                print(f"\n=== {frame} {arm}, {days:g}-day windows")
                merged: dict[int, dict[int, tuple[int, float]]] = {}
                for (s, f, a), book in zip(jobs, books, strict=False):
                    if f != frame or a != arm:
                        continue
                    for w, row in bucketed(book, days).items():
                        into = merged.setdefault(w, {})
                        for index, (n, net) in row.items():
                            had_n, had_net = into.get(index, (0, 0.0))
                            total = had_n + n
                            into[index] = (total, (had_net * had_n + net * n) / total)
                # **The trade floor scales with the window.** Eight trades is
                # a reasonable bar over a fortnight and an impossible one over
                # three days, so holding it fixed would silently rank only the
                # most frequent cells at the short end and compare a different
                # grid at each window length.
                floor = max(int(round(args.least * days / 7.0)), 3)
                for top in (int(v) for v in args.top.split(",")):
                    report(f"top {top} (min {floor} trades)", *walk(merged, top, floor))


if __name__ == "__main__":
    main()
