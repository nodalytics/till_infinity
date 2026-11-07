"""Do origins hold when price comes back - measured causally, against controls.

`revisits.py` asked this and cannot be run or trusted. It scans from
`int(origin.when) + 1`, the volatility turn, where the origin does not exist
until the impulse that followed broke structure - the `Origin.settled`
docstring in the retired package states it in terms: "**Not the same as
`when`, and the difference is a look-ahead bug.**" Between the two, price is
*by construction* travelling away from the zone in the impulse direction,
which is that harness's own definition of a bounce. It scores the definitional
impulse as a hold.

It also imports `till_infinity.structures`, retired with `till_platform`, so
it has not run since. Fixing the index in a file that cannot import would be a
fix nobody can check, so this measures the same question against the live
implementation instead.

Run:
  ./.secrets/lab.sh run research/harness/revisiting.py \
      SEQLAB=$HOME/till_infinity/data/seqlab OMP_NUM_THREADS=1

## Why this one is causal by construction rather than by a fixed index

`indicators.levels.Origins` is streaming: `handle_bar` keeps a 40-bar window
and recomputes `chains()` over it, so what it holds at bar `t` used only bars
up to `t`. An origin's knowable time is therefore **the bar it first appears
at**, and no `settled` field is needed.

**The full-series shortcut was checked and refused.** `chains()` documents that
"a leg that extends is re-read rather than updated in place", so a leg's `end`
grows as later bars arrive and the origins derived from it move with it.
Computing legs once over the whole series and taking each leg's end as its
knowable time is the same hindsight-replacement the look-ahead audit found in
`zigzag` and `displacements.nodes`. So this streams, at 40 comparisons a bar.

## The controls, because a return rate is geometry

A hold rate on its own measures the distance the band sits at, not the band.
The origin's 82% return rate is matched by a distance-matched placebo on every
class, and a random walk reads 0.825. So two arms beside the real one:

* **placebo** - a band of the same width, the same side, at the same distance
  from the price it was knowable at, placed at a time with no origin. This is
  the one that matters: it holds distance fixed and removes only the origin.
* **walk** - the instrument's own returns block-shuffled at 96 bars, through
  the same machinery. Volatility clustering preserved, since shuffling bar by
  bar would make the control easier than the thing.

A hold rate that the placebo matches says the band is a distance, not a level.
"""

from __future__ import annotations

import glob
import os
import sys
from collections import deque
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from till_infinity.indicators.levels import (  # noqa: E402
    ORIGIN_KEEP,
    SPAN,
    Candle,
    chains,
    origins_of,
)

SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
#: How far price must travel away from the zone to have bounced, and how far
#: through the far side to have broken. `revisits.py`'s own constants.
BOUNCE_VOL = 1.0
BREAK_VOL = 0.5
#: How long a visit is given to resolve, in bars.
RESOLVE = 48
#: How long an origin stays eligible for a first visit.
LIFE = 480
#: Visits past this are pooled.
VISITS = 4
BLOCK = 96
UNIT_SPAN = 14
MIN_BARS = 20_000
#: Cap per feed: the streaming recompute is the cost and this keeps a sweep
#: inside a few minutes a feed.
BARS = 120_000


def unit_series(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """An EWMA of the bar range: the unit `Origins` uses by default."""
    rng = high - low
    out = np.empty_like(rng)
    acc = 0.0
    alpha = 2.0 / (UNIT_SPAN + 1.0)
    for i, v in enumerate(rng):
        acc = v if i == 0 else acc + alpha * (v - acc)
        out[i] = acc
    return out


def stream(high: np.ndarray, low: np.ndarray, op: np.ndarray, cl: np.ndarray) -> list[dict]:
    """Every origin with the bar index it first became visible at.

    The window is a `deque(maxlen=SPAN)`, so nothing after `t` is reachable.
    """
    window: deque[Candle] = deque(maxlen=SPAN)
    seen: set[tuple] = set()
    found: list[dict] = []
    for t in range(len(cl)):
        window.append(
            Candle(high=float(high[t]), low=float(low[t]), open=float(op[t]),
                   close=float(cl[t]), when=float(t))
        )
        if len(window) < SPAN:
            continue
        bars = list(window)
        for leg in chains(bars):
            for origin in origins_of(bars, leg, keep=ORIGIN_KEEP):
                key = (origin.side, round(origin.low, 10), round(origin.high, 10),
                       round(origin.when, 6))
                if key in seen:
                    continue
                seen.add(key)
                #: `when` was stuffed with the bar index, so this is the
                #: origin candle's own bar - always at or before `t`.
                at = int(round(origin.when))
                assert at <= t, "an origin cannot precede its own window"
                found.append(
                    {"side": origin.side, "low": origin.low, "high": origin.high,
                     "at": at, "knowable": t}
                )
    return found


def resolve(
    high: np.ndarray, low: np.ndarray, zone: dict, unit: np.ndarray, *, legacy: bool = False
) -> list[str]:
    """Each visit to the band, as `hold`, `break` or `open`.

    The scan starts at the **knowable** bar, never at `at`: between the two the
    impulse is leaving the zone by construction, and counting that as a bounce
    is the bug this file exists to avoid.
    """
    side, lo, hi = zone["side"], zone["low"], zone["high"]
    #: `legacy` reproduces `revisits.py`'s index - the origin's own bar - so
    #: the bug can be priced instead of described. Measured on a walk, no
    #: origin is knowable on its own bar: the delay runs 1 to 29 bars, median
    #: 2, and those are the bars the impulse spends leaving the zone.
    start = (zone["at"] if legacy else zone["knowable"]) + 1
    out: list[str] = []
    i = start
    stop = min(start + LIFE, len(high))
    while i < stop and len(out) < VISITS + 2:
        inside = low[i] <= hi and high[i] >= lo
        if not inside:
            i += 1
            continue
        u = unit[i]
        if u <= 0:
            break
        #: Demand (+1) holds by leaving upward; supply (-1) by leaving down.
        away = (hi + BOUNCE_VOL * u) if side > 0 else (lo - BOUNCE_VOL * u)
        through = (lo - BREAK_VOL * u) if side > 0 else (hi + BREAK_VOL * u)
        verdict = "open"
        j = i
        while j < min(i + RESOLVE, len(high)):
            broke = low[j] <= through if side > 0 else high[j] >= through
            held = high[j] >= away if side > 0 else low[j] <= away
            #: Break first, for the same reason a stop is taken first: both
            #: inside one bar is unknowable at this resolution.
            if broke:
                verdict = "break"
                break
            if held:
                verdict = "hold"
                break
            j += 1
        out.append(verdict)
        if verdict == "break":
            break
        i = j + 1
        stop = min(i + LIFE, len(high))
    return out


def placebo(zones: list[dict], cl: np.ndarray, rng: np.random.Generator) -> list[dict]:
    """Same width, same side, same distance from price - no origin.

    The distance is what a return rate measures, so holding it fixed is the
    only control that isolates the level.
    """
    out = []
    n = len(cl)
    for z in zones:
        width = z["high"] - z["low"]
        here = float(cl[z["knowable"]])
        gap = (here - z["high"]) if z["side"] > 0 else (z["low"] - here)
        at = int(rng.integers(SPAN + 1, max(SPAN + 2, n - LIFE - RESOLVE - 2)))
        price = float(cl[at])
        if z["side"] > 0:
            hi = price - gap
            lo = hi - width
        else:
            lo = price + gap
            hi = lo + width
        out.append({"side": z["side"], "low": lo, "high": hi, "at": at, "knowable": at})
    return out


def walk_of(cl: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    ret = np.diff(np.log(np.maximum(cl, 1e-12)))
    n = len(ret) // BLOCK
    blocks = ret[: n * BLOCK].reshape(n, BLOCK)
    rng.shuffle(blocks)
    return float(cl[0]) * np.exp(np.cumsum(np.concatenate([[0.0], blocks.reshape(-1)])))


def one_feed(path: str) -> list[tuple]:
    z = np.load(path)
    name = os.path.basename(path).split(".")[0]
    cl = z["close"].astype(np.float64)
    if len(cl) < MIN_BARS:
        return []
    cl, hi_, lo_, op_ = (a.astype(np.float64)[-BARS:] for a in
                         (z["close"], z["high"], z["low"], z["open"]))
    rng = np.random.default_rng(13)
    rows: list[tuple] = []
    for arm in ("real", "legacy", "placebo", "walk"):
        if arm == "walk":
            w = walk_of(cl, rng)
            #: **The walk needs real candle bodies or it has no displacements
            #: at all.** `PUSH_BODY` is 0.70, so a candle whose open equals its
            #: close can never be impulsive: an arm built with `op = close`
            #: finds zero origins and reports nothing, which reads identically
            #: to a control that ran and agreed. Open is the previous close, and
            #: the wick straddles both, so the geometry matches the real series.
            close = w
            op = np.concatenate([[w[0]], w[:-1]])
            reach = (hi_ - lo_)[: len(w)]
            body_hi = np.maximum(op, close)
            body_lo = np.minimum(op, close)
            wick = np.maximum(reach - (body_hi - body_lo), 0.0) / 2.0
            high, low = body_hi + wick, body_lo - wick
        else:
            #: `legacy` and `placebo` both run on the real series; only the
            #: index and the placement differ.
            high, low, op, close = hi_, lo_, op_, cl
        unit = unit_series(high, low)
        zones = stream(high, low, op, close)
        if arm == "placebo":
            zones = placebo(zones, close, rng)
        if len(zones) < 30:
            print(f"  !! {name} {arm}: only {len(zones)} origins - arm did not run")
            continue
        if arm == "real":
            delays = [z["knowable"] - z["at"] for z in zones]
            rows.append((name, "delay", 0, len(delays), sum(d == 0 for d in delays),
                         float(np.median(delays))))
        tally: dict[int, list[str]] = {}
        for zone in zones:
            got_v = resolve(high, low, zone, unit, legacy=arm == "legacy")
            for k, verdict in enumerate(got_v, start=1):
                tally.setdefault(min(k, VISITS), []).append(verdict)
        for visit, got in sorted(tally.items()):
            decided = [v for v in got if v != "open"]
            if len(decided) < 20:
                continue
            rows.append((name, arm, visit, len(got), len(decided),
                         sum(v == "hold" for v in decided) / len(decided)))
    return rows


def main() -> int:
    paths = sorted(glob.glob(os.path.join(SEQLAB, "*.npz")))
    if not paths:
        print(f"no npz under {SEQLAB}")
        return 1
    print(f"{len(paths)} feeds, {BARS} bars each, span {SPAN}, keep {ORIGIN_KEEP}")
    print(f"bounce {BOUNCE_VOL}u, break {BREAK_VOL}u, resolve {RESOLVE} bars\n")
    from concurrent.futures import ProcessPoolExecutor

    rows: list[tuple] = []
    with ProcessPoolExecutor(max_workers=min(12, os.cpu_count() or 4)) as pool:
        for got in pool.map(one_feed, paths):
            rows.extend(got)
            if got:
                print(f"  {got[0][0]:28s} {len(got):3d} rows")
    if not rows:
        print("no rows")
        return 1

    print(f"\n{'arm':>8s} {'visit':>6s} {'visits':>8s} {'decided':>8s} {'hold rate':>10s}"
          f"  {'feeds':>5s}")
    agg: dict[tuple, list[tuple]] = {}
    for r in rows:
        agg.setdefault((r[1], r[2]), []).append(r)
    held: dict[tuple, float] = {}
    for key in sorted(agg, key=lambda k: (k[0], k[1])):
        got = agg[key]
        seen = sum(g[3] for g in got)
        decided = sum(g[4] for g in got)
        rate = sum(g[4] * g[5] for g in got) / decided if decided else float("nan")
        held[key] = rate
        print(f"{key[0]:>8s} {key[1]:>6d} {seen:8d} {decided:8d} {rate:10.3f}  {len(got):5d}")

    print("\n=== what the look-ahead was worth ===")
    for visit in range(1, VISITS + 1):
        r = held.get(("real", visit))
        g = held.get(("legacy", visit))
        if r is None or g is None:
            continue
        print(f"  visit {visit}: correct index {r:.3f}  "
              f"`revisits.py`'s index {g:.3f}  inflation {g - r:+.3f}")
    delay = [r for r in rows if r[1] == "delay"]
    if delay:
        zero = sum(r[4] for r in delay)
        total = sum(r[3] for r in delay)
        med = sum(r[3] * r[5] for r in delay) / total
        print(f"  origins knowable on their own bar: {zero} of {total}; "
              f"median delay {med:.1f} bars")

    print("\n=== the real question: does the origin beat its own distance? ===")
    for visit in range(1, VISITS + 1):
        r = held.get(("real", visit))
        p = held.get(("placebo", visit))
        w = held.get(("walk", visit))
        if r is None or p is None:
            continue
        if w is None:
            print(f"  visit {visit}: WALK ARM MISSING - a control that did not "
                  f"run reads the same as one that agreed")
        verdict = "origin adds nothing" if abs(r - p) < 0.02 else (
            "origin above its distance" if r > p else "origin BELOW its distance")
        print(f"  visit {visit}: real {r:.3f}  placebo {p:.3f}  walk "
              f"{'n/a' if w is None else f'{w:.3f}'}  -> {verdict}")
    print("\nA hold rate the placebo matches is a distance, not a level.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
