"""How far a leg stretches before price comes back to where it started.

The operator, 2026-11-20: *"can you measure the full stretch leg the price got
to before it turn back and came back to the points again or even more, our
objective is we want to measure leg lengths and see if we can find fractals in
them, across timeframes too"*.

So the object is the **round-trip excursion**: from a turn point, the furthest
price travelled before returning to that same price. Not the leg between two
turn points - that is [`leg_sequence.py`](leg_sequence.py) - but the stretch a
single turn point eventually gives back.

## What is already settled, so this does not re-measure it

* [`excursion-scaling.md`](../docs/excursion-scaling.md) fitted the **adverse**
  excursion against the horizon over 3,216 fits: median exponent **0.5196**,
  and **every real deviation from 0.5 is smaller than its own hardest surrogate
  deviation on all 14 cells** - shuffled bars manufacture two to a hundred
  times the apparent departure any real feed shows. So "is the exponent 0.5" is
  answered, and answered as yes.
* [`fractal-twins.md`](../docs/fractal-twins.md) measured DFA Hurst at **0.67
  to 0.84 on |returns|** and **0.51 to 0.54 on returns**, against 0.51 for
  random walks. **Volatility is fractal here and direction is not.**

Those two together give this study its prior, and it is a strong one: with
returns at H = 0.5 and lengths divided by the frame's own ATR, the
distributions *should* coincide across frames. **So invariance is the null, not
the finding.** What is worth measuring is where it breaks, and by how much -
and a result that merely confirms self-similarity has found the arithmetic of
ATR normalisation rather than a property of markets.

## The measurement

For every turn point, walk forward until price trades back through the turn
price, and record:

    stretch   the furthest it got, in ATR of the turn's bar
    bars      how long that took
    overshoot how far past the turn price it went when it came back
    gave      stretch minus overshoot: what the round trip handed back

Across five frames - 5m, 15m, 1h, 4h, 1d - on four indices whose cost is
already screened, and against a **day-shuffled twin at every frame**: a
distribution that is invariant across frames on real bars *and* on shuffled
ones is invariant because of the normaliser.

The fractal reading is the quantile ladder. If `stretch` in ATR has the same
quantiles at 5m and at 1d, the object is scale-free over that range; the frame
where the ladder bends is the scale at which it stops being.

Run as:

    uv run python research/ideas/leg_lengths.py --frames M5,M15,H1,H4,D1
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from index_pullback import Feed, point_of, read, shuffle_days  # noqa: E402
from reactive_zones import atr  # noqa: E402

DEEP = Path(".secrets/indices/deepidx.csv.gz")

#: ATR the stretch must clear before the fade is entered - "once that is an
#: impulse". Swept on the command line; this is only the default.
IMPULSE = 2.0
CHEAP = ("US Tech 100", "Wall Street 30", "US SP 500", "Japan 225")
#: Bars one frame holds of the next one down, for reporting a stretch in time
#: as well as in ATR.
MINUTES = {"M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}


@dataclass(slots=True)
class Stretch:
    atr_units: np.ndarray
    bars: np.ndarray
    overshoot: np.ndarray
    side: np.ndarray
    resolved: np.ndarray


def pivots(feed: Feed, left: int, right: int) -> tuple[np.ndarray, np.ndarray]:
    """Swing pivots and their side, known `right` bars after the fact.

    The simplest turn definition of the four in `leg_sequence.turns_of`, chosen
    because this study is about the **stretch** and not about the detector: a
    richer definition would make the length distribution partly a property of
    the detector's own selectivity, which is the confound
    `turn-points.md` found running through its whole selectivity ladder.
    """
    bars = feed.bars
    n = len(bars)
    at, side = [], []
    for i in range(left, n - right):
        low, high = float(bars.low[i]), float(bars.high[i])
        if low < bars.low[i - left : i].min() and low <= bars.low[i + 1 : i + 1 + right].min():
            at.append(i)
            side.append(1)
        elif high > bars.high[i - left : i].max() and high >= bars.high[i + 1 : i + 1 + right].max():
            at.append(i)
            side.append(-1)
    return np.asarray(at, dtype=np.int64), np.asarray(side, dtype=np.int8)


def stretches(feed: Feed, left: int, right: int, patience: int) -> Stretch:
    """From each turn, the furthest price got before trading back through it.

    **Measured from the turn's own price, and the walk starts at `right + 1`.**
    The pivot is not knowable until `right` bars after it, so a stretch counted
    from the pivot bar itself would include bars a person could not have acted
    on - and on a quantity that is a maximum over a window, those few bars are
    exactly the ones most likely to hold the maximum.
    """
    bars = feed.bars
    band = atr(bars)
    at, side = pivots(feed, left, right)
    n = len(bars)
    units, took, over, sides, done = [], [], [], [], []
    for k in range(at.size):
        i = int(at[k])
        unit = band[i]
        if not np.isfinite(unit) or unit <= 0:
            continue
        up = side[k] == 1
        origin = float(bars.low[i]) if up else float(bars.high[i])
        best = 0.0
        resolved, back, bars_taken = False, 0.0, 0
        for j in range(i + right + 1, min(n, i + right + 1 + patience)):
            reach = (float(bars.high[j]) - origin) if up else (origin - float(bars.low[j]))
            best = max(best, reach)
            through = (float(bars.low[j]) <= origin) if up else (float(bars.high[j]) >= origin)
            if through:
                resolved = True
                bars_taken = j - i
                back = (origin - float(bars.low[j])) if up else (float(bars.high[j]) - origin)
                break
        if best <= 0:
            continue
        units.append(best / unit)
        took.append(float(bars_taken if resolved else patience))
        over.append(max(back, 0.0) / unit)
        sides.append(1 if up else -1)
        done.append(resolved)
    return Stretch(
        atr_units=np.asarray(units),
        bars=np.asarray(took),
        overshoot=np.asarray(over),
        side=np.asarray(sides, dtype=np.int8),
        resolved=np.asarray(done, dtype=bool),
    )


def ladder(name: str, values: np.ndarray, extra: str = "") -> None:
    """The quantile ladder, which is where self-similarity is read off."""
    ok = np.isfinite(values)
    if ok.sum() < 60:
        print(f"    {name:<22} {ok.sum()} turns, too few")
        return
    v = values[ok]
    marks = (10, 25, 50, 75, 90, 99)
    shown = "  ".join(f"p{q}{np.percentile(v, q):7.2f}" for q in marks)
    print(f"    {name:<22} n{ok.sum():>6}  {shown}  mean{v.mean():6.2f}{extra}")


def tail_exponent(values: np.ndarray, floor: float = 1.0) -> float:
    """Hill's estimator on the upper tail, which says whether a tail is heavy.

    The quantile ladder says whether two distributions coincide; this says what
    shape the far end has. A power-law tail is the signature a self-similar
    process leaves, and a sharply different exponent across frames is the
    clearest way the ladder can agree while the object is not scale-free.
    """
    v = values[np.isfinite(values) & (values > floor)]
    if v.size < 50:
        return float("nan")
    return float(1.0 / np.mean(np.log(v / floor)))


def fade(feed: Feed, left: int, right: int, hours: float, stop_atr: float, cost_r: float) -> dict:
    """Bet the stretch comes back, inside `hours`, with a stop. What it pays.

    The operator's question, 2026-11-20: *"once that is an impulse i can bet
    that is will come back in the next 3 hours"*. The unconditional table says
    price returns to a turn point **90%** of the time - and that figure is
    measured with 500 bars of patience and no stop. This is the same claim
    asked as a trade, which is a different question.

    **It is the shape that killed `fade-to-value`**, which also found an 81%
    return rate and then lost: price does return 77-81% of the time, *"but that
    is measured with no stop and 300 bars, and the trade has a stop and
    sixty"*, with **89-91% of fades stopped before the target arrived**. So the
    two numbers that matter are the hit rate inside the clock and the R after
    the stop, and the second is not implied by the first.

    Entry is the close of the first bar whose stretch clears `IMPULSE` ATR, on
    the side that fades it; the target is the turn's own price; the stop is
    `stop_atr` ATR beyond the entry. `fair` is `1/(1+reward/risk)` for the
    geometry each trade actually had, so a high hit rate at a poor ratio reads
    as what it is.
    """
    bars = feed.bars
    band = atr(bars)
    at, side = pivots(feed, left, right)
    n = len(bars)
    span = max(int(round(hours * 60 / MINUTES.get(bars.frame, 15))), 1)
    taken: list[float] = []
    ratios: list[float] = []
    wins = 0
    for k in range(at.size):
        i = int(at[k])
        unit = band[i]
        if not np.isfinite(unit) or unit <= 0:
            continue
        up = side[k] == 1
        origin = float(bars.low[i]) if up else float(bars.high[i])
        entry_at = -1
        for j in range(i + right + 1, min(n, i + right + 1 + 500)):
            reach = (float(bars.high[j]) - origin) if up else (origin - float(bars.low[j]))
            if reach >= IMPULSE * unit:
                entry_at = j
                break
        if entry_at < 0 or entry_at >= n - 1:
            continue
        entry = float(bars.close[entry_at])
        reward = abs(entry - origin)
        risk = stop_atr * unit
        if reward <= 0 or risk <= 0:
            continue
        guard = entry + risk if up else entry - risk
        ratio = reward / risk
        got = None
        for j in range(entry_at + 1, min(n, entry_at + 1 + span)):
            hit_stop = float(bars.high[j]) >= guard if up else float(bars.low[j]) <= guard
            hit_back = float(bars.low[j]) <= origin if up else float(bars.high[j]) >= origin
            if hit_stop:
                got = -1.0
                break
            if hit_back:
                got = ratio
                wins += 1
                break
        if got is None:
            last = min(n, entry_at + 1 + span) - 1
            got = (entry - float(bars.close[last])) * (1.0 if up else -1.0) / risk
        taken.append(got - cost_r)
        ratios.append(ratio)
    if not taken:
        return {}
    out = np.asarray(taken)
    rr = np.asarray(ratios)
    return {
        "n": out.size,
        "hit": wins / out.size,
        "fair": float(np.mean(1.0 / (1.0 + rr))),
        "ratio": float(rr.mean()),
        "net": float(out.mean()),
    }


def main() -> None:  # noqa: PLR0912
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(CHEAP))
    parser.add_argument("--frames", default="M5,M15,H1,H4,D1")
    parser.add_argument("--left", type=int, default=5)
    parser.add_argument("--right", type=int, default=3)
    parser.add_argument("--patience", type=int, default=500)
    parser.add_argument("--arms", default="real,shuffled")
    parser.add_argument("--fade", action="store_true", help="trade the return, with a stop and a clock")
    parser.add_argument("--hours", default="1,3,8,24")
    parser.add_argument("--stops", default="0.5,1.0,2.0")
    parser.add_argument("--impulse", type=float, default=2.0)
    parser.add_argument("--cost", type=float, default=0.02, help="cost in R; index M15 measured 0.018-0.055")
    args = parser.parse_args()

    names = [s.strip() for s in args.symbols.split(",") if s.strip()]

    def feeds(frame: str):
        for symbol in names:
            probe = read(symbol, frame, 0.0, DEEP)
            if probe is None:
                continue
            feed = read(symbol, frame, point_of(symbol, float(probe.bars.close[-1])), DEEP)
            if feed is not None and len(feed.bars) >= 400:
                yield feed

    if args.fade:
        global IMPULSE
        IMPULSE = args.impulse
        print(
            f"betting the return: enter when the stretch clears {args.impulse:g} ATR, "
            f"target the turn's own price, stop beyond the entry, {args.cost:g}R charged."
        )
        print("'fair' is 1/(1+reward/risk) for the geometry each trade actually had.")
        for frame in (f.strip() for f in args.frames.split(",") if f.strip()):
            print(f"\n  {frame}")
            print("    hours  stop      n     hit    fair   hit-fair    R:R      net R")
            for hours in (float(h) for h in args.hours.split(",")):
                for stop in (float(s) for s in args.stops.split(",")):
                    pooled = [
                        got
                        for feed in feeds(frame)
                        if (got := fade(feed, args.left, args.right, hours, stop, args.cost))
                    ]
                    if not pooled:
                        continue
                    n = sum(p["n"] for p in pooled)
                    hit = sum(p["hit"] * p["n"] for p in pooled) / n
                    fair = sum(p["fair"] * p["n"] for p in pooled) / n
                    ratio = sum(p["ratio"] * p["n"] for p in pooled) / n
                    net = sum(p["net"] * p["n"] for p in pooled) / n
                    print(
                        f"    {hours:5g}  {stop:4.1f}  {n:>6,}  {hit:.3f}  {fair:.3f}   "
                        f"{hit - fair:+.3f}    {ratio:5.2f}  {net:+.4f}"
                    )
        return

    print(
        f"round-trip stretch, {args.left}/{args.right} pivots, {len(names)} indices, "
        f"patience {args.patience} bars"
    )
    print(
        "the stretch is in ATR of the turn's own bar, and the walk starts "
        f"{args.right + 1} bars after the pivot because that is when it is knowable"
    )
    for arm in (a.strip() for a in args.arms.split(",") if a.strip()):
        print(f"\n=== {arm}")
        for frame in (f.strip() for f in args.frames.split(",") if f.strip()):
            pooled = []
            for feed in feeds(frame):
                source = shuffle_days(feed, 23) if arm == "shuffled" else feed
                pooled.append(stretches(source, args.left, args.right, args.patience))
            if not pooled:
                continue
            every = Stretch(
                atr_units=np.concatenate([s.atr_units for s in pooled]),
                bars=np.concatenate([s.bars for s in pooled]),
                overshoot=np.concatenate([s.overshoot for s in pooled]),
                side=np.concatenate([s.side for s in pooled]),
                resolved=np.concatenate([s.resolved for s in pooled]),
            )
            hill = tail_exponent(every.atr_units)
            minutes = MINUTES.get(frame, 0)
            ladder(
                f"{frame} stretch ATR",
                every.atr_units,
                f"  tail {hill:.2f}  returned {float(every.resolved.mean()):.3f}",
            )
            ladder(f"{frame} bars to return", every.bars[every.resolved])
            if minutes:
                ladder(f"{frame} hours to return", every.bars[every.resolved] * minutes / 60.0)
            ladder(f"{frame} overshoot ATR", every.overshoot[every.resolved])


if __name__ == "__main__":
    main()
