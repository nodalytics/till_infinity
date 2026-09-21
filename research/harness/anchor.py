"""Does agreeing with a higher timeframe decide whether a trade wins?

Run from the repository root:  python research/harness/anchor.py

The operator's claim is that **4h is the king of timeframes**: a signal on a
timeframe above or below it that disagrees with 4h is likely to lose. This measures
it, four different ways, against nine other timeframes.

## Why this sweeps everything instead of testing 4h

Testing only 4h cannot answer the question. Alignment with *any* slower timeframe
helps if trends persist at all, so finding that 4h alignment helps would establish
nothing about 4h - it would establish that trend agreement helps, which nobody
doubts. The claim is that **4h is special**, and that only survives if 4h beats its
neighbours on the same rows. 2h and 6h sit either side of it deliberately: if 4h
rules, 2h and 6h should be visibly worse, and if the three are indistinguishable
then the number four is not doing any work.

**Four readings across ten anchors is forty cells, so the best is the best of
forty.** That is why the summary prints the spread and the per-symbol win count
rather than just the winner - the best of twenty instruments looked convincing here
until the best of twenty *shuffles* beat it 93% of the time.

## Four ways to read a timeframe, because "aligns with 4h" is ambiguous

| reading    | the question it asks                                          |
|------------|---------------------------------------------------------------|
| `trend`    | is this timeframe's close above its previous close             |
| `pivot`    | is price above the last closed bar's `(H+L+C)/3`               |
| `zma`      | is the desk's own `Zma` sloping up on this timeframe           |
| `momentum` | which way did the desk's own `Cusum` last break on it          |

They disagree often - price sits above a pivot while the timeframe falls - so these
are different claims, and the operator's rule is usually stated as the second.

`zma` and `momentum` use the **real classes the desk runs**, not reimplementations,
so a result here is a statement about this desk rather than about an indicator that
merely shares a name. `zma` carries a prior worth stating up front:
`structures/zma.py` records AUC 0.485-0.515 on this desk's outright prices and
37.6-46.1% hit on Boom and Crash - *reliably wrong* - paying only on constructed
spreads. Using it as a slower-timeframe anchor is a different question, which is why
it is here, but a null is the expected result rather than a surprise.

## What is measured, and why it needs no signal model

Testing a *rule* conditional on the anchor would confound the rule with the anchor.
Instead the anchor does the whole job:

    at every bar, what happens to a long, and to a short,
    when the anchor says up, and when the anchor says down?

The outcome is first passage of a symmetric barrier at `BAND` true ranges, which is
what a stop and a target resolve against. If an anchor carries direction, longs must
resolve better when it points up. The gap between the two is its edge, in units of
the trade the desk takes - and **cost cancels in that gap**, being subtracted from
both sides, so the comparison does not rest on the cost assumption.

**Both barriers inside one bar resolve as the stop**, because a bar does not record
which extreme arrived first. That biases every number downward, which is the
direction an honest bias points.

## The anchor cannot be built from the signal's own bars

An anchor finer than the signal timeframe **cannot be computed from it**. Folding
daily bars into 4h buckets puts one daily bar per bucket, so the "4h" anchor comes
back identical to the 1d anchor - exactly what happened on the first run here: with
a daily signal, 4h, 8h, 12h and 1d all reported +0.0090R and 7/7 symbols, to four
decimals. Four columns, one series, reading as robust agreement across timeframes
rather than as one number printed four times.

So anchors are folded from `--anchor-from`, a separate finer series, and any anchor
shorter than that series' own bar period is skipped rather than faked.

## What it cannot say

Nothing about entries. A real signal fires on a fraction of bars and may be
concentrated where the anchor is useless, or useful. This measures whether the
anchor carries direction at all - necessary for the claim, not sufficient. The
anchor is read **causally**: only bars already closed at the moment of decision.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))
sys.path.insert(0, str(HERE.parent.parent))

import candles  # noqa: E402

#: Barrier half-width, in true ranges. One is the desk's own scale.
BAND = 1.0

#: Bars ahead the barrier may be reached in, per signal timeframe. Roughly one
#: trading day of that timeframe, so horizons are comparable in wall time.
HORIZON = {"1h": 24, "4h": 12, "1d": 5}

#: Anchors to compare. The hourly ladder is dense around 4h on purpose: if four
#: hours is the special number, 2h and 6h either side of it must be worse.
ANCHORS = (
    ("1h", 3600),
    ("2h", 2 * 3600),
    ("3h", 3 * 3600),
    ("4h", 4 * 3600),
    ("6h", 6 * 3600),
    ("8h", 8 * 3600),
    ("12h", 12 * 3600),
    ("1d", 24 * 3600),
    ("3d", 3 * 24 * 3600),
    ("1w", 7 * 24 * 3600),
)


def resample(bars: np.ndarray, every: int) -> np.ndarray:
    """Fold bars into buckets of `every` seconds, on clock boundaries.

    Clock boundaries rather than bar counts, because an anchor must mean the same
    thing across instruments trading different hours - and because a 4h bar
    starting wherever the data happens to start is not the 4h bar on a chart.
    """
    if not len(bars):
        return bars
    keys = (bars[:, 0] // every).astype(np.int64)
    out = []
    start = 0
    for i in range(1, len(keys) + 1):
        if i == len(keys) or keys[i] != keys[start]:
            chunk = bars[start:i]
            out.append(
                (
                    float(keys[start] * every),
                    chunk[0, 1],
                    chunk[:, 2].max(),
                    chunk[:, 3].min(),
                    chunk[-1, 4],
                )
            )
            start = i
    return np.array(out, dtype=float)


def read_trend(anchor: np.ndarray) -> np.ndarray:
    """+1 where this anchor bar closed above the previous one.

    The plainest reading of a timeframe's direction, needing no parameter chosen
    after seeing the answer.
    """
    out = np.zeros(len(anchor), dtype=np.int64)
    if len(anchor) < 2:
        return out
    out[1:] = np.sign(anchor[1:, 4] - anchor[:-1, 4]).astype(np.int64)
    return out


def read_pivot(anchor: np.ndarray) -> np.ndarray:
    """+1 where this anchor bar closed above the *previous* bar's pivot.

    `P = (high + low + close) / 3` of the bar before - the pivot every chart draws
    for the session that follows it. A level rather than a slope, which is how the
    operator's rule is usually stated.
    """
    out = np.zeros(len(anchor), dtype=np.int64)
    if len(anchor) < 2:
        return out
    pivot = (anchor[:-1, 2] + anchor[:-1, 3] + anchor[:-1, 4]) / 3.0
    out[1:] = np.sign(anchor[1:, 4] - pivot).astype(np.int64)
    return out


def read_zma(anchor: np.ndarray) -> np.ndarray:
    """+1 where the desk's own `Zma` slopes up on this timeframe.

    The real class, fed this timeframe's closes in order. Its slope after observing
    bar `i` uses only bars `<= i`, so the reading is causal by construction.
    """
    from till_infinity.structures.zma import Zma

    out = np.zeros(len(anchor), dtype=np.int64)
    running = Zma()
    for i, price in enumerate(anchor[:, 4]):
        running.observe(float(price))
        out[i] = 1 if running.slope > 0 else (-1 if running.slope < 0 else 0)
    return out


def read_momentum(anchor: np.ndarray) -> np.ndarray:
    """Which way the desk's own `Cusum` last broke on this timeframe.

    `Cusum` is the filter the basket risk plan already reads to decide whether the
    heat on the book is reversing, and `events[-1].side` is the exact value it
    consults - so this asks the live momentum reading the question directly.

    It needs a volatility unit per bar, which is the same EWMA true range every
    other part of this file sizes with.
    """
    from till_infinity.structures.context.cusum import Cusum

    out = np.zeros(len(anchor), dtype=np.int64)
    if len(anchor) < 2:
        return out
    tr = candles.true_range(anchor)
    running = Cusum()
    side = 0
    for i, price in enumerate(anchor[:, 4]):
        unit = max(float(tr[i]) * float(price), 1e-12)
        event = running.push(float(price), unit, when=float(anchor[i, 0]), index=i)
        if event is not None:
            side = 1 if str(event.side).lower().startswith(("up", "b", "+")) else -1
        out[i] = side
    return out


READINGS = {"trend": read_trend, "pivot": read_pivot, "zma": read_zma, "momentum": read_momentum}


def settle(anchor: np.ndarray, reading: np.ndarray, when: np.ndarray) -> np.ndarray:
    """Map a per-anchor-bar reading onto signal-bar times, causally.

    `searchsorted(..., "right") - 1` finds the anchor bar containing the decision;
    that bar is still forming, so the reading comes from the one **before** it.
    Reading the forming bar would use a close that has not happened yet - the
    easiest way to manufacture a result here.
    """
    out = np.zeros(len(when), dtype=np.int64)
    if not len(anchor):
        return out
    idx = np.searchsorted(anchor[:, 0], when, side="right") - 1
    settled = idx - 1
    good = settled >= 0
    out[good] = reading[settled[good]]
    return out


def outcomes(bars: np.ndarray, tr: np.ndarray, horizon: int) -> np.ndarray:
    """+1 if a long reaches target first, -1 if stopped, 0 if neither in horizon.

    A short is the exact mirror, so one array serves both sides.
    """
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    out = np.zeros(len(close), dtype=np.int64)
    for at in range(len(close) - horizon):
        here = close[at]
        if here <= 0:
            continue
        reach = BAND * tr[at] * here
        up, down = here + reach, here - reach
        for step in range(1, horizon + 1):
            hit_up = high[at + step] >= up
            hit_down = low[at + step] <= down
            if hit_up and hit_down:
                out[at] = -1  # adverse first, by convention
                break
            if hit_up:
                out[at] = 1
                break
            if hit_down:
                out[at] = -1
                break
    return out


def mean_r(taken: np.ndarray, cost_r: float) -> tuple[float, int]:
    """Mean R and count over the trades that actually resolved.

    Unresolved bars are dropped rather than scored flat: the desk exits on
    barriers, so a bar reaching neither is a different question, and scoring it
    zero would pull every number towards zero by the same amount and make a real
    gap look smaller than it is.
    """
    resolved = taken != 0
    count = int(resolved.sum())
    if not count:
        return 0.0, 0
    return float(taken[resolved].astype(float).mean() - cost_r), count


def load(where: str, symbol: str, interval: str) -> tuple[np.ndarray, int] | None:
    found = sorted(Path(where).glob(f"{symbol}_{interval}_*.csv.gz"))
    return candles.read(found[0]) if found else None


def measure(symbol: str, args: argparse.Namespace, horizon: int, gathered: dict) -> None:
    """Report one symbol across every reading and anchor, and bank the gaps."""
    got = load(args.where, symbol, args.signal)
    if got is None:
        print(f"{symbol:<10} no {args.signal} file in {args.where}")
        return
    bars, repaired = got
    if len(bars) < candles.WARMUP + horizon + 10:
        print(f"{symbol:<10} only {len(bars)} bars")
        return
    tr = candles.true_range(bars)
    result = outcomes(bars, tr, horizon)

    source = load(args.where, symbol, args.anchor_from) or (bars, 0)
    fine = source[0]
    spacing = float(np.median(np.diff(fine[:, 0]))) if len(fine) > 2 else 0.0

    first = dt.datetime.fromtimestamp(bars[0, 0], dt.UTC).date()
    last = dt.datetime.fromtimestamp(bars[-1, 0], dt.UTC).date()
    base, base_n = mean_r(result, args.cost)
    print(
        f"{symbol:<10} {len(bars):>7} bars  {first} to {last}  {repaired} repaired   "
        f"unconditional long {base:+.4f}R on {base_n:,}"
    )
    print(
        f"           {'anchor':<7}"
        + "".join(f"{name:>11}" for name in READINGS)
        + "     gap = aligned minus opposed"
    )

    for label, seconds in ANCHORS:
        if spacing and seconds < spacing:
            print(f"           {label:<7} skipped - finer than the {args.anchor_from} source")
            continue
        folded = resample(fine, seconds)
        cells = []
        for name, reader in READINGS.items():
            side = settle(folded, reader(folded), bars[:, 0])
            up, down = side == 1, side == -1
            aligned = np.concatenate([result[up], -result[down]])
            aligned_r, aligned_n = mean_r(aligned, args.cost)
            opposed_r, _ = mean_r(-aligned, args.cost)
            gap = aligned_r - opposed_r
            gathered.setdefault((name, label), []).append((gap, aligned_n))
            cells.append(f"{gap:>+11.4f}")
        print(f"           {label:<7}" + "".join(cells))
    print()


def summarise(gathered: dict) -> None:
    rows = []
    for (name, label), seen in gathered.items():
        gaps = [g for g, _n in seen]
        if gaps:
            rows.append(
                (
                    float(np.mean(gaps)),
                    name,
                    label,
                    sum(1 for g in gaps if g > 0),
                    len(gaps),
                    sum(n for _g, n in seen),
                )
            )
    if not rows:
        return

    print(f"=== all {len(rows)} cells, ranked. The winner is the best of {len(rows)}.")
    print(f"  {'reading':<9} {'anchor':<7} {'mean gap':>10} {'+ve':>8} {'n':>12}")
    for mean, name, label, wins, count, total in sorted(rows, reverse=True):
        print(f"  {name:<9} {label:<7} {mean:>+10.4f} {wins:>4}/{count:<3} {total:>12,}")

    best = max(rows)
    spread = best[0] - min(r[0] for r in rows)
    print(f"\n  best is {best[1]}/{best[2]} at {best[0]:+.4f}R on {best[3]}/{best[4]} symbols.")
    print(f"  spread across all cells is {spread:.4f}R.")
    print(
        "  For one timeframe to rule, its cell must stand clear of the rest AND win\n"
        "  on most symbols. Winning narrowly on half is what the best of "
        f"{len(rows)} looks\n  like when nothing is there."
    )

    # 4h against the neighbours that would have to be worse if it were special.
    print("\n  4h against its neighbours, per reading:")
    print(f"    {'reading':<9}" + "".join(f"{lab:>10}" for lab in ("2h", "3h", "4h", "6h", "8h")))
    for name in READINGS:
        cells = []
        for lab in ("2h", "3h", "4h", "6h", "8h"):
            hit = [r for r in rows if r[1] == name and r[2] == lab]
            cells.append(f"{hit[0][0]:>+10.4f}" if hit else f"{'-':>10}")
        print(f"    {name:<9}" + "".join(cells))
    print(
        "    If 4h is not visibly better than 2h, 3h, 6h and 8h in this block, then\n"
        "    the number four is doing no work and the rule is about slower context."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "gbpusd", "usdjpy"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--signal", default="1h", choices=sorted(HORIZON))
    ap.add_argument(
        "--anchor-from",
        default="1h",
        help="interval the anchors are folded from; must be finer than the anchors",
    )
    ap.add_argument(
        "--cost",
        type=float,
        default=0.03,
        help="round-trip cost as a fraction of R; it cancels in every gap",
    )
    args = ap.parse_args()

    horizon = HORIZON[args.signal]
    print(
        f"signal {args.signal}, anchors folded from {args.anchor_from}, "
        f"barrier +/-{BAND} TR, horizon {horizon} bars, cost {args.cost:.3f}R\n"
    )
    gathered: dict[tuple[str, str], list[tuple[float, int]]] = {}
    for symbol in args.symbols:
        measure(symbol, args, horizon, gathered)
    summarise(gathered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
