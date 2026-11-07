"""Do displacement legs pay 1:2, and does the walk say 0.333?

A 1:2 race has a breakeven hit rate of exactly **1/3** on a driftless walk -
`P(+2R before -1R) = 1/3` by the optional stopping theorem - so the walk arm
is not a comparison here, it is the **acceptance test**. If it does not read
0.333 the harness is broken and nothing else in the output means anything.

This repository has the specific way it breaks on record: *settling on the
fill bar won 0.470 of 2R races against a required 0.333*. So the outcome is
resolved from the bar **after** entry, never the entry bar.

Run:
  ./.secrets/lab.sh run research/harness/legs.py \
      SEQLAB=$HOME/till_infinity/data/seqlab OMP_NUM_THREADS=1

## The trade

`indicators.levels.chains` finds displacement legs. At the bar a leg first
becomes visible - streaming, so that is its knowable time - enter in the leg's
direction at the next bar's open. Stop `STOP_VOL` volatility units away,
target twice that. Whichever is touched first inside `HOLD` bars decides it;
the stop is taken where both fall in one bar, because which came first is
unknowable at this resolution.

**Continuation, not retracement.** The retracement version - fading back to the
leg's origin - is already measured and null: a distance-matched placebo
reproduces the hold rate and the origin contributes +0.006. See
`revisiting.md`. So this asks the other question.

## The arms

* **real** - the instrument.
* **walk** - its own returns block-shuffled at 96 bars, same bar geometry, same
  machinery. **Must read 0.333.** Printed first, with a verdict, because the
  rest of the table is only readable if it does.
* **anytime** - the same geometry entered at uniformly drawn bars rather than
  at a leg. This is what says whether the *leg* matters or only the stop and
  target do.

## What would count as a result

A leg class whose hit rate clears 1/3 by more than the `anytime` arm does, net
of two spreads, with the sign holding across instruments. Note the prior: this
is a direction bet, and direction is measured closed on this book - the drift
gate finds a planted drift at z+2.90 and earns 2% of a spread. So the expected
answer is no, and the value is in how precisely no.
"""

from __future__ import annotations

import glob
import os
import sys
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from till_infinity.indicators.levels import SPAN, Candle, chains  # noqa: E402

SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
#: Stop distance in volatility units; the target is twice it.
STOP_VOLS = (0.5, 1.0, 2.0)
REWARD = 2.0
#: Bars a trade may run before it is marked out at the close.
HOLD = 96
UNIT_SPAN = 14
BLOCK = 96
MIN_BARS = 20_000
BARS = 120_000
#: Leg size buckets, in volatility units, for the conditioning question.
SIZE_EDGES = (2.0, 4.0, 8.0)


def unit_series(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    rng = high - low
    out = np.empty_like(rng)
    acc = 0.0
    alpha = 2.0 / (UNIT_SPAN + 1.0)
    for i, v in enumerate(rng):
        acc = v if i == 0 else acc + alpha * (v - acc)
        out[i] = acc
    return out


def stream_legs(high, low, op, cl) -> list[dict]:
    """Every leg with the bar it first became visible at.

    A `deque(maxlen=SPAN)`, so nothing after `t` is reachable. A leg is keyed
    on its own origin bar and side; `chains` re-reads an extending leg rather
    than updating it, so the **first** sighting is the knowable one and later
    extensions of the same leg are ignored.
    """
    window: deque[Candle] = deque(maxlen=SPAN)
    seen: set[tuple] = set()
    out: list[dict] = []
    for t in range(len(cl)):
        window.append(
            Candle(high=float(high[t]), low=float(low[t]), open=float(op[t]),
                   close=float(cl[t]), when=float(t))
        )
        if len(window) < SPAN:
            continue
        bars = list(window)
        base = t - len(bars) + 1
        for leg in chains(bars):
            key = (base + leg.origin, leg.side)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {"side": leg.side, "knowable": t, "origin": base + leg.origin,
                 "move": abs(float(leg.move)), "bars": int(leg.bars),
                 "pauses": len(leg.pauses)}
            )
    return out


def race(high, low, cl, op, i: int, side: int, stop_px: float, target: float) -> float | None:
    """R from an entry at bar `i`'s open, resolved from bar `i` onward.

    Entry is the open of the bar after the signal, so the signal bar's own
    range is never used - and the race starts at that same bar, which is
    legitimate because the entry price is its open rather than something
    chosen from inside it.
    """
    risk = abs(float(op[i]) - stop_px)
    if risk <= 0:
        return None
    for j in range(i, min(i + HOLD, len(high))):
        if side > 0:
            if low[j] <= stop_px:
                return -1.0
            if high[j] >= target:
                return REWARD
        else:
            if high[j] >= stop_px:
                return -1.0
            if low[j] <= target:
                return REWARD
    last = float(cl[min(i + HOLD, len(high)) - 1])
    return ((last - float(op[i])) if side > 0 else (float(op[i]) - last)) / risk


def bucket(move_units: float) -> int:
    return int(np.digitize(move_units, SIZE_EDGES))


def one_feed(path: str) -> list[tuple]:
    z = np.load(path)
    name = os.path.basename(path).split(".")[0]
    if len(z["close"]) < MIN_BARS:
        return []
    cl, hi_, lo_, op_ = (z[k].astype(np.float64)[-BARS:]
                         for k in ("close", "high", "low", "open"))
    point = float(np.min(np.abs(np.diff(np.unique(cl)))[np.abs(np.diff(np.unique(cl))) > 0]))
    spread = float(np.median(z["spread"])) * point if "spread" in z else 0.0
    rng = np.random.default_rng(13)
    rows: list[tuple] = []

    for arm in ("real", "walk", "anytime"):
        if arm == "walk":
            ret = np.diff(np.log(np.maximum(cl, 1e-12)))
            n = len(ret) // BLOCK
            blocks = ret[: n * BLOCK].reshape(n, BLOCK)
            rng.shuffle(blocks)
            w = float(cl[0]) * np.exp(np.cumsum(np.concatenate([[0.0], blocks.reshape(-1)])))
            close = w
            op = np.concatenate([[w[0]], w[:-1]])
            reach = (hi_ - lo_)[: len(w)]
            bh, bl = np.maximum(op, close), np.minimum(op, close)
            wick = np.maximum(reach - (bh - bl), 0.0) / 2.0
            high, low = bh + wick, bl - wick
        else:
            high, low, op, close = hi_, lo_, op_, cl
        unit = unit_series(high, low)
        legs = stream_legs(high, low, op, close)
        if arm == "anytime":
            #: The same count and the same side mix, at uniformly drawn bars.
            top = max(SPAN + 2, len(close) - HOLD - 2)
            legs = [
                {**leg, "knowable": int(rng.integers(SPAN + 1, top)), "move": leg["move"]}
                for leg in legs
            ]
        for stop_vol in STOP_VOLS:
            #: **(gross, net) per trade.** Storing only the net and then
            #: counting wins as `>= REWARD` made every win uncountable the
            #: moment a spread was charged: the net of a winner is
            #: `REWARD - cost`, which is never `>= REWARD`. The acceptance
            #: test read 0.0000 and refused to report, which is what it is for.
            got: dict[int, list[tuple[float, float]]] = {}
            for leg in legs:
                i = leg["knowable"] + 1
                if i >= len(high) - 1:
                    continue
                u = unit[leg["knowable"]]
                if u <= 0:
                    continue
                entry = float(op[i])
                dist = stop_vol * u
                stop_px = entry - dist if leg["side"] > 0 else entry + dist
                target = entry + REWARD * dist if leg["side"] > 0 else entry - REWARD * dist
                r = race(high, low, close, op, i, leg["side"], stop_px, target)
                if r is None:
                    continue
                #: Two spreads, as a fraction of the risk.
                got.setdefault(bucket(leg["move"] / u), []).append(
                    (r, r - 2.0 * spread / dist)
                )
            for size, values in sorted(got.items()):
                if len(values) < 50:
                    continue
                #: A win is the target being reached, which is a fact about
                #: the race. The cost belongs in the expectancy, not the
                #: hit rate - the breakeven 1/3 is a pre-cost number.
                wins = sum(gross >= REWARD - 1e-9 for gross, _net in values)
                rows.append((name, arm, stop_vol, size, len(values),
                             wins / len(values),
                             float(np.mean([net for _g, net in values]))))
    return rows


def main() -> int:
    paths = sorted(glob.glob(os.path.join(SEQLAB, "*.npz")))
    if not paths:
        print(f"no npz under {SEQLAB}")
        return 1
    print(f"{len(paths)} feeds, {BARS} bars, stops {STOP_VOLS}u, reward {REWARD}:1, "
          f"hold {HOLD} bars")
    print(f"leg size buckets at {SIZE_EDGES} units\n")
    rows: list[tuple] = []
    with ProcessPoolExecutor(max_workers=min(12, os.cpu_count() or 4)) as pool:
        for got in pool.map(one_feed, paths):
            rows.extend(got)
            if got:
                print(f"  {got[0][0]:28s} {len(got):3d} rows")
    if not rows:
        print("no rows")
        return 1

    def pooled(sel) -> tuple[int, float, float]:
        got = [r for r in rows if sel(r)]
        n = sum(g[4] for g in got)
        if not n:
            return 0, float("nan"), float("nan")
        return (n,
                sum(g[4] * g[5] for g in got) / n,
                sum(g[4] * g[6] for g in got) / n)

    # ---- the acceptance test, first and alone
    print("=== acceptance test: a 1:2 race on a walk must hit 1/3 ===")
    ok = True
    for stop_vol in STOP_VOLS:
        n, hit, mean = pooled(lambda r, s=stop_vol: r[1] == "walk" and r[2] == s)
        if not n:
            continue
        off = abs(hit - 1.0 / 3.0)
        flag = "ok" if off < 0.02 else "FAIL - the harness is wrong, not the market"
        ok = ok and off < 0.02
        print(f"  stop {stop_vol}u: {n:7d} races  hit {hit:.4f}  (1/3 = 0.3333, "
              f"off {off:+.4f})  meanR {mean:+.3f}  {flag}")
    if not ok:
        print("\nStopping on the acceptance test. Nothing below would mean anything.")
        return 1

    print("\n=== legs against anytime entries, by stop and leg size ===")
    print(f"{'stop':>5s} {'size':>5s} {'arm':>8s} {'races':>8s} {'hit':>7s} "
          f"{'vs 1/3':>7s} {'meanR':>8s}")
    for stop_vol in STOP_VOLS:
        for size in range(len(SIZE_EDGES) + 1):
            for arm in ("real", "anytime"):
                n, hit, mean = pooled(
                    lambda r, s=stop_vol, z=size, a=arm:
                    r[1] == a and r[2] == s and r[3] == z
                )
                if not n:
                    continue
                print(f"{stop_vol:5.1f} {size:5d} {arm:>8s} {n:8d} {hit:7.4f} "
                      f"{hit - 1.0 / 3.0:+7.4f} {mean:+8.3f}")

    print("\n=== does the leg add anything over the same geometry anywhere? ===")
    for stop_vol in STOP_VOLS:
        nr, hr, mr = pooled(lambda r, s=stop_vol: r[1] == "real" and r[2] == s)
        na, ha, ma = pooled(lambda r, s=stop_vol: r[1] == "anytime" and r[2] == s)
        if not nr or not na:
            continue
        print(f"  stop {stop_vol}u: leg {hr:.4f} ({mr:+.3f}R)  anytime {ha:.4f} "
              f"({ma:+.3f}R)  leg adds {hr - ha:+.4f} hit, {mr - ma:+.3f}R")
    print("\nNet of two spreads. A 1:2 race needs 0.3333 to break even before cost.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
