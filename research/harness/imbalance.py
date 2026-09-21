"""When price comes back to a gap, does it react - and does freshness matter?

Run from the repository root:  python research/harness/imbalance.py

The operator's account of it: an imbalance is left behind by a displacement, price
may return to that edge later, and **a fresh imbalance is what gives a level a
fresh perspective** - the first touch is the informative one. So three questions,
in order:

1. what happened *before* the gap - does the displacement that opened it predict
   whether the level holds?
2. what happened *after* price returned - is it a reaction, or does price walk
   straight through?
3. does **freshness** matter - is the first touch different from the third?

## The control, which is the only reason any of this is answerable

Price touching some earlier level and bouncing is ordinary mean reversion. Any
level would do that, and a study of gap edges alone would measure reversion and
report it as a property of gaps.

So every gap touch is matched against a **placebo level**: an ordinary prior low
(for a bullish gap) picked at a similar distance and a similar age, with no
imbalance behind it. The number that means anything is the *difference* between
them. If gap edges and placebo levels react alike, a gap is a way of drawing
attention to a level rather than a reason for one.

## What counts as a touch, and as a reaction

A bullish gap at bar `j` spans `high[j-span]` to `low[j]`. Price has **touched** it
when a later bar's low reaches `low[j]` - the wick edge, which is what the operator
watches, not the body. From the close of that touch bar, the outcome is first
passage of a symmetric `BAND` true-range barrier: up first is a reaction, down
first is a failure. Bearish gaps are the mirror.

**Both barriers inside one bar counts as a failure**, because a bar does not record
which extreme came first. That biases every reaction rate here downward.

## What it cannot say

Nothing about size. A reaction rate above half is not an edge until it clears the
cost of trading it, and the barrier here is symmetric so the breakeven rate is
`0.5 + cost/(2*band)`. The rate is printed against that line rather than against
50%, because 50% is not the line anyone trades against.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Barrier half-width from the touch, in true ranges.
BAND = 1.0

#: Bars the barrier may be reached in, after the touch.
HORIZON = 24

#: Span for the gap, in bars back. 2 is the classic three-candle imbalance.
SPAN = 2

#: How long a gap stays eligible to be touched, in bars. Past this it is stale by
#: assumption rather than by measurement, which is a limitation worth naming.
ALIVE = 500

#: Same-coloured candles before the gap that count as a consistent run. The
#: operator's rule says a minimum of two or three, with at least one long one.
RUN_STRONG = 3

#: Round-trip cost as a fraction of R, for the breakeven line only.
COST = 0.03

#: Timeframes to compare, as (label, seconds per bar). The question is whether a
#: gap found on a slower timeframe is a stronger level than one on a faster one, so
#: the ladder has to span enough of them to show a trend rather than a pair.
LADDER = (
    ("15m", 15 * 60),
    ("30m", 30 * 60),
    ("1h", 3600),
    ("2h", 2 * 3600),
    ("4h", 4 * 3600),
    ("8h", 8 * 3600),
    ("1d", 24 * 3600),
)


def fold(bars: np.ndarray, every: int) -> np.ndarray:
    """Fold bars into clock buckets of `every` seconds.

    Clock boundaries, not bar counts, so a 4h bar here is the 4h bar on a chart.
    """
    if not len(bars):
        return bars
    keys = (bars[:, 0] // every).astype(np.int64)
    out, start = [], 0
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


def gaps(
    bars: np.ndarray, tr: np.ndarray, span: int = SPAN
) -> list[tuple[int, int, float, float, float]]:
    """Every gap, as `(index, side, edge, displacement, origin_wick)`.

    `side` is +1 bullish, -1 bearish. `edge` is the wick price price must return
    to. `displacement` is the opening candle's body in true ranges - "what happened
    before" - and `origin_wick` is the wick that forms the edge, both of which the
    operator says should matter.
    """
    high, low, close, opens = bars[:, 2], bars[:, 3], bars[:, 4], bars[:, 1]
    out = []
    for j in range(span, len(bars)):
        unit = max(tr[j] * close[j], 1e-12)
        body = (close[j - 1] - opens[j - 1]) / unit  # the displacement candle
        if high[j - span] < low[j]:
            out.append(
                (j, 1, float(low[j]), float(body), float((min(opens[j], close[j]) - low[j]) / unit))
            )
        elif low[j - span] > high[j]:
            out.append(
                (
                    j,
                    -1,
                    float(high[j]),
                    float(body),
                    float((high[j] - max(opens[j], close[j])) / unit),
                )
            )
    return out


def resolve(bars: np.ndarray, tr: np.ndarray, at: int, side: int) -> int:
    """From the close of bar `at`, did a `side` trade reach target or stop first?

    +1 reached the target, -1 stopped, 0 neither inside `HORIZON`.
    """
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    here = close[at]
    if here <= 0 or at + HORIZON >= len(bars):
        return 0
    reach = BAND * tr[at] * here
    up, down = here + reach, here - reach
    for step in range(1, HORIZON + 1):
        hit_up = high[at + step] >= up
        hit_down = low[at + step] <= down
        if hit_up and hit_down:
            return -side if side > 0 else side  # adverse first, by convention
        if hit_up:
            return 1 if side > 0 else -1
        if hit_down:
            return -1 if side > 0 else 1
    return 0


def touches(bars: np.ndarray, gap: tuple, tr: np.ndarray, limit: int = ALIVE) -> list[int]:
    """Visits to this gap's edge, oldest first.

    A **visit**, not a bar. A hundred consecutive bars resting on a level are one
    touch, and counting each separately both swamped the tally with the quietest
    levels and made this study too slow to finish. Price has to leave the edge by
    half a true range before a return counts again.

    Every visit is recorded, not only the first, because the question is whether the
    *first* is different - and that cannot be answered without the others.
    """
    j, side, edge, _disp, _wick = gap
    high, low, close = bars[:, 2], bars[:, 3], bars[:, 4]

    seen: list[int] = []
    away = True
    for at in range(j + 1, min(j + 1 + limit, len(bars))):
        reached = low[at] <= edge if side > 0 else high[at] >= edge
        if reached:
            if away:
                seen.append(at)
                away = False
            continue
        room = 0.5 * tr[at] * max(close[at], 1e-12)
        if (side > 0 and low[at] > edge + room) or (side < 0 and high[at] < edge - room):
            away = True
    return seen


def placebo_edge(bars: np.ndarray, j: int, side: int, distance: float) -> float | None:
    """An ordinary prior extreme at a similar distance, with no imbalance behind it.

    The matched control. Picked from bars before the gap so nothing about the gap
    itself informs it, and chosen for closeness of *distance* so the comparison is
    not confounded by how far price had to travel.
    """
    lows, highs = bars[:, 3], bars[:, 2]
    close = bars[j, 4]
    best, best_off = None, np.inf
    for k in range(max(j - ALIVE, 1), j - SPAN):
        level = lows[k] if side > 0 else highs[k]
        off = abs(abs(close - level) - distance)
        if off < best_off:
            best, best_off = float(level), off
    return best


def fill_state(bars: np.ndarray, gap: tuple, at: int, span: int = SPAN) -> str:
    """How much of the band price had already taken back before this touch.

    A bullish gap spans `high[j-span]` (the far edge) to `low[j]` (the near edge,
    which is the wick price returns to). Three states, and the middle one is what
    "a gap that has not been closed" actually means:

    * `untouched`  - nothing since has reached the near edge at all
    * `not closed` - price entered the band but never crossed the far edge, so the
                     imbalance is still partly there
    * `closed`     - price crossed the far edge and the imbalance is spent

    This is deliberately separate from freshness. The first *touch* of an edge and
    the first *entry* into a band are different events, and a level can be touched
    repeatedly while the band behind it stays unclosed.
    """
    j, side, edge, _disp, _wick = gap
    far = bars[j - span, 2] if side > 0 else bars[j - span, 3]
    if at <= j + 1:
        return "untouched"
    window = bars[j + 1 : at]
    if not len(window):
        return "untouched"
    if side > 0:
        reached = window[:, 3].min()
        if reached > edge:
            return "untouched"
        return "not closed" if reached > far else "closed"
    reached = window[:, 2].max()
    if reached < edge:
        return "untouched"
    return "not closed" if reached < far else "closed"


def _opening(run: float, strong: float, side: int) -> str:
    """How the imbalance was opened, in the operator's own terms.

    Three states, and the distinction that matters is the middle one: a run of
    same-coloured candles *with* a long one in it is intent, a run without one is
    drift, and a single candle is a spike. All three leave a gap.

    The run must also point the same way as the gap. A bullish imbalance opened by
    a run of red candles is not the pattern being claimed, and lumping it in would
    dilute exactly the cell under test.
    """
    aligned = (run > 0 and side > 0) or (run < 0 and side < 0)
    if not aligned:
        return "run against the gap"
    if abs(run) >= RUN_STRONG and strong > 0:
        return "consistent run, with intent"
    if abs(run) >= RUN_STRONG:
        return "consistent run, no long candle"
    return "single candle"


def study(symbol: str, bars: np.ndarray, tally: dict, where: str = "") -> None:
    """Measure every gap on one instrument and bank the outcomes.

    `where` names the timeframe the bars are on, so the same routine serves every
    rung of the ladder. **Everything scales with the bars it is given** - the true
    range, the barrier and the horizon are all in that timeframe's own units - which
    is the only way the rungs are comparable. A fixed barrier in price would simply
    report that 4h gaps are further apart than 15m gaps.
    """
    tr = candles.true_range(bars)
    found = gaps(bars, tr)
    if not found:
        print(f"{symbol:<22} no gaps found")
        return

    disp = np.array([g[3] for g in found])
    wick = np.array([g[4] for g in found])
    big_disp = np.nanquantile(np.abs(disp), 0.67) if len(disp) else 0.0
    big_wick = np.nanquantile(wick, 0.67) if len(wick) else 0.0

    # The operator's consistency rule, as a qualifier on the gap rather than as a
    # signal of its own: was the imbalance opened by a *run* of same-coloured
    # candles containing at least one long one, and did that run point the same way
    # as the gap? A single spike and a three-candle march both leave a gap, and the
    # claim is that they are not the same level.
    run, strong = candles.consistency(bars, tr)

    counted = 0
    for gap in found:
        j, side, edge, displacement, origin = gap
        seen = touches(bars, gap, tr)
        if not seen:
            continue
        distance = abs(bars[j, 4] - edge)
        fake = placebo_edge(bars, j, side, distance)
        for order, at in enumerate(seen, start=1):
            got = resolve(bars, tr, at, side)
            if got == 0:
                continue
            counted += 1
            rank = "first" if order == 1 else ("second" if order == 2 else "later")
            tally[("freshness", rank)][got > 0] += 1
            tally[("displacement", "big" if abs(displacement) >= big_disp else "small")][
                got > 0
            ] += 1
            tally[("origin wick", "big" if origin >= big_wick else "small")][got > 0] += 1
            tally[("band state before the touch", fill_state(bars, gap, at))][got > 0] += 1
            tally[("what opened it", _opening(run[j], strong[j], side))][got > 0] += 1
            if where and order == 1:
                tally.setdefault(("timeframe, first touch", where), Counter())[got > 0] += 1
            if order == 1:
                tally[("what it is", "gap edge, first touch")][got > 0] += 1
        # The placebo gets exactly one shot, matched to the gap's first touch.
        if fake is not None:
            for at in range(j + 1, min(j + 1 + ALIVE, len(bars))):
                reached = bars[at, 3] <= fake if side > 0 else bars[at, 2] >= fake
                if reached:
                    got = resolve(bars, tr, at, side)
                    if got != 0:
                        tally[("what it is", "placebo level, first touch")][got > 0] += 1
                    break
    print(f"{symbol:<22} {len(found):>6} gaps  {counted:>7} resolved touches")


def report(tally: dict) -> None:
    breakeven = 0.5 + COST / (2.0 * BAND)
    print(f"\nreaction rate at the edge, against a breakeven of {breakeven:.1%}")
    groups: dict[str, list[tuple[str, Counter]]] = {}
    for (group, name), counter in tally.items():
        groups.setdefault(group, []).append((name, counter))
    for group, rows in groups.items():
        print(f"\n  {group}")
        for name, counter in sorted(rows):
            total = counter[True] + counter[False]
            if not total:
                continue
            rate = counter[True] / total
            # Standard error of a proportion, which is the least this needs.
            se = (rate * (1 - rate) / total) ** 0.5
            flag = "  <- clears breakeven" if rate - 2 * se > breakeven else ""
            print(f"    {name:<28} {rate:>7.1%} +/- {2 * se:.1%}  on {total:>7,}{flag}")

    edge = tally.get(("what it is", "gap edge, first touch"), Counter())
    fake = tally.get(("what it is", "placebo level, first touch"), Counter())
    et, ft = edge[True] + edge[False], fake[True] + fake[False]
    if et and ft:
        er, fr = edge[True] / et, fake[True] / ft
        se = (er * (1 - er) / et + fr * (1 - fr) / ft) ** 0.5
        print(
            f"\n  gap edge minus placebo: {er - fr:+.1%} +/- {2 * se:.1%}\n"
            "  This is the only number that says a gap is a reason for a level rather\n"
            "  than a way of noticing one. Zero means any old level would have done."
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "gbpusd", "usdjpy"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument(
        "--ladder",
        action="store_true",
        help="also fold the bars up the timeframe ladder and compare rungs",
    )
    args = ap.parse_args()

    tally: dict[tuple[str, str], Counter] = {}
    for key in (
        ("freshness", "first"),
        ("freshness", "second"),
        ("freshness", "later"),
        ("displacement", "big"),
        ("displacement", "small"),
        ("origin wick", "big"),
        ("origin wick", "small"),
        ("band state before the touch", "untouched"),
        ("band state before the touch", "not closed"),
        ("band state before the touch", "closed"),
        ("what opened it", "consistent run, with intent"),
        ("what opened it", "consistent run, no long candle"),
        ("what opened it", "single candle"),
        ("what opened it", "run against the gap"),
        ("what it is", "gap edge, first touch"),
        ("what it is", "placebo level, first touch"),
    ):
        tally[key] = Counter()

    print(f"span {SPAN}, barrier +/-{BAND} TR, {HORIZON} bars to resolve, alive {ALIVE} bars\n")
    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<22} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if args.ladder:
            spacing = float(np.median(np.diff(bars[:, 0]))) if len(bars) > 2 else 0.0
            for label, seconds in LADDER:
                if spacing and seconds < spacing:
                    continue
                folded = fold(bars, seconds)
                if len(folded) < 200:
                    continue
                study(f"{symbol} {label}", folded, tally, where=label)
        else:
            study(symbol, bars, tally)
    report(tally)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
