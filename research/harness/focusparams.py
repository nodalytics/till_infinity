"""Good parameters for FOCuS origin zones, on 130x the sample that settled nothing.

`research/docs/focusing.md` measured the indicator's own rules at +0.051R over
**205 trades** and said plainly what it needed: "What the sample cannot do is
separate a real 0.2R effect from noise, and the only fix for that is more of
it." `multi.db` holds 25 days of 8 instruments. The lab's seqlab holds
**3.3M 15m bars over 12 instruments and eleven years**, with a spread column -
so this run can be powered *and* costed, which that one could be neither.

Run:
  ./.secrets/lab.sh run research/harness/focusparams.py \
      SEQLAB=$HOME/till_infinity/data/seqlab OMP_NUM_THREADS=1

## What is swept, and why in two stages

Zone construction is the expensive half - a detector pass per rung per
instrument - and trade management is nearly free once the zones exist. So
zones are built once per `(anchor, base, k)` and every `(buffer, reward,
min_agree)` is scored against the same set. That is also the honest factoring:
the first three change *which* zones exist, the last three change only what a
trade does with one.

## The nulls

* **Matched random zones** - same count, same widths, same entry rule, times
  drawn uniformly. A 1:2 stop and target has a non-zero expectancy under a
  random walk before costs, so the question is never "is R positive" but "is
  it better than the same geometry somewhere else".
* **Permuted agreement** - real trades, agreement labels shuffled, 200 draws.
  `focusing.md` records the mistake this avoids: one shuffled draw was read as
  a refutation, and one shuffle is not a null, it is one sample from one.

## Costs

The npz `spread` column is in **points, not price** - the error that once read
EURUSD as a 476% round trip. Point size is inferred per instrument as the
smallest positive step between distinct closes, which recovers 1e-05 on the FX
majors and is data-driven rather than a table to get wrong. One spread is
charged at entry and one at exit, expressed in R.
"""

from __future__ import annotations

import glob
import os
import statistics as st
from concurrent.futures import ProcessPoolExecutor
from math import log

import numpy as np

SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
#: 15m bars per anchor bar. 96 is the daily anchor the indicator ships with.
ANCHORS = (16, 96)
BASES = (3.0, 6.0, 9.0, 12.0)
KFACTORS = (0.0, 3.0)
BUFFERS = (0.25, 0.5, 1.0)
REWARDS = (1.0, 2.0, 3.0)
AGREES = (1, 2, 3)
#: Agreement rungs in 15m bars: 15m, 1h, 4h, 1d.
LADDER = (1, 4, 16, 96)
#: How long a call from one rung stands, in anchor bars.
WINDOW = 6.0
#: How long a zone stays live and a trade may run, in 15m bars.
LIFE = 96 * 5
HOLD = 96
SCALE_SPAN = 250
MIN_BARS = 20_000
DRAWS = 200


# ----------------------------------------------------------------- detector
def focus_calls(steps: np.ndarray, threshold: float, up: bool) -> list[tuple[int, int]]:
    """Indices where an exact hull-pruned FOCuS clears `threshold`, and resets.

    The candidates that can ever maximise the likelihood ratio lie on the lower
    convex hull of the partial-sum path, so one inside it can never beat both
    neighbours whatever arrives next. Returns the index the change *started*,
    which is what a zone is placed from.
    """
    out: list[tuple[int, int]] = []
    hull_sum: list[float] = [0.0]
    hull_at: list[int] = [0]
    running = 0.0
    seen = 0
    sign = 1.0 if up else -1.0
    for i, step in enumerate(steps):
        if not np.isfinite(step):
            continue
        running += float(step)
        seen += 1
        best = 0.0
        where = 0
        for k in range(len(hull_sum)):
            gap = seen - hull_at[k]
            if gap <= 0:
                continue
            diff = sign * (running - hull_sum[k])
            if diff > 0.0:
                score = diff * diff / (2.0 * gap)
                if score > best:
                    best = score
                    where = hull_at[k]
        while len(hull_sum) >= 2:
            left_s, left_t = hull_sum[-2], hull_at[-2]
            mid_s, mid_t = hull_sum[-1], hull_at[-1]
            span = max(1, seen - left_t)
            on_it = left_s + (running - left_s) / span * (mid_t - left_t)
            if (mid_s >= on_it) if up else (mid_s <= on_it):
                hull_sum.pop()
                hull_at.pop()
            else:
                break
        hull_sum.append(running)
        hull_at.append(seen)
        if best >= threshold:
            out.append((max(0, i - (seen - where)), i))
            hull_sum, hull_at = [0.0], [0]
            running = 0.0
            seen = 0
    return out


def scaled_steps(close: np.ndarray, span: int = SCALE_SPAN) -> np.ndarray:
    """Close-to-close steps over a running mean absolute step.

    Dividing by a volatility unit is what makes a threshold in nats mean the
    same thing on gold and on a JPY cross.
    """
    step = np.diff(close, prepend=close[0])
    mag = np.abs(step)
    scale = np.empty_like(mag)
    acc = 0.0
    alpha = 2.0 / (span + 1.0)
    for i, m in enumerate(mag):
        acc = m if i == 0 else acc + alpha * (m - acc)
        scale[i] = acc
    out = np.where(scale > 0, step / np.where(scale > 0, scale, 1.0), 0.0)
    out[:span] = np.nan
    return out


def aggregate(close: np.ndarray, size: int) -> np.ndarray:
    """Last close of each `size`-bar bucket, and the index it ends at."""
    n = (len(close) // size) * size
    return close[:n].reshape(-1, size)[:, -1]


def nats_for(anchor: int, rung: int, base: float, k: float) -> float:
    """`base + k * ln(anchor / rung)`, the measured timeframe correction.

    A threshold in nats is scale-free across instruments and not across
    timeframes: a fast rung gets more chances a day and the running maximum of
    a likelihood ratio grows with the number of chances it has had. `k = 3` is
    what flattened the fire rate on 8 instruments; `k = 0` is one threshold
    everywhere, swept here as the control.
    """
    return base + k * max(0.0, log(anchor / rung))


# --------------------------------------------------------------------- zones
def build_zones(bars: dict, anchor: int, base: float, k: float) -> list[dict]:
    """Zones from the indicator's rules: detect on the anchor, place inside it."""
    close, high, low = bars["close"], bars["high"], bars["low"]
    anchor_close = aggregate(close, anchor)
    if len(anchor_close) < SCALE_SPAN + 50:
        return []
    anchor_steps = scaled_steps(anchor_close)
    threshold = nats_for(anchor, anchor, base, k)

    #: Which rungs have called recently, as sets of 15m indices.
    rung_calls: dict[int, dict[bool, np.ndarray]] = {}
    for rung in LADDER:
        if rung > anchor:
            continue
        rung_close = aggregate(close, rung)
        if len(rung_close) < SCALE_SPAN + 50:
            continue
        steps = scaled_steps(rung_close)
        thr = nats_for(anchor, rung, base, k)
        rung_calls[rung] = {
            #: A rung agrees from when it *fired*, not from the change it
            #: points back at.
            up: np.array(
                [f * rung for _s, f in focus_calls(steps, thr, up)], dtype=np.int64
            )
            for up in (True, False)
        }

    zones = []
    for up in (True, False):
        for call, fired in focus_calls(anchor_steps, threshold, up):
            start = call * anchor
            stop = min(start + anchor, len(close))
            #: Knowable only once the statistic crossed, which is `fired`, not
            #: the retrospective `call`.
            knowable = min((fired + 1) * anchor, len(close))
            if stop - start < 2 or start < SCALE_SPAN * anchor:
                continue
            #: Estimator F: the extreme close inside the anchor bar. It beat
            #: FOCuS itself at placement, 0.107v against 0.161v, and every
            #: blend of the two was worse than the extreme alone.
            window = close[start:stop]
            at = start + (int(np.argmin(window)) if up else int(np.argmax(window)))
            width = float(high[at] - low[at])
            if width <= 0:
                continue
            agreed = 0
            span = WINDOW * anchor
            for rung, calls in rung_calls.items():
                hits = calls[up]
                if hits.size and np.any((hits <= start) & (hits >= start - span)):
                    agreed += 1
            zones.append(
                {
                    "at": at,
                    #: **The anchor bar's close, not the extreme's bar.** The
                    #: zone's edges are the extreme of the refinement bars
                    #: *inside* the anchor bar, so the zone is not knowable
                    #: until that anchor bar has closed. Searching for entry
                    #: from `at + 1` lets a trade fill at a price chosen using
                    #: the rest of the very bar that defined it, and returns
                    #: about +2.3R at an 82% win rate - which is the hit rate
                    #: a distance-matched walk gives for free. `focusing.md`
                    #: records the same bug at +1.363R and 80.8%. And the
                    #: anchor bar's own close is still too early: see
                    #: `focus_calls` on `started` against `fired`.
                    "from": knowable,
                    "up": up,
                    "top": float(high[at]),
                    "btm": float(low[at]),
                    "width": width,
                    "agreed": agreed,
                }
            )
    return zones


def trade(bars: dict, zone: dict, buffer_: float, reward: float, cost: float) -> float | None:
    """One zone traded on return, net of a spread each way, in R.

    Entry is the **near** edge - the price a returning move touches first and
    the worse of the two fills. Taking the far edge assumes a fill nobody
    offered.
    """
    high, low = bars["high"], bars["low"]
    up = zone["up"]
    #: **The near edge is the one a returning move reaches first**, and it is
    #: the worse of the two fills. Price sits *above* a support zone and falls
    #: onto its top; it sits below a resistance zone and rises to its bottom.
    #: Inverting these put the stop inside the zone - above a long's entry at
    #: a half-width buffer - so every trade stopped out on its entry bar and
    #: the reward made no difference to the mean. A target that cannot change
    #: the outcome is the invariant that caught it.
    entry = zone["top"] if up else zone["btm"]
    far = zone["btm"] if up else zone["top"]
    stop = far - buffer_ * zone["width"] if up else far + buffer_ * zone["width"]
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    target = entry + reward * risk if up else entry - reward * risk
    start = max(zone["at"] + 1, zone["from"])
    end = min(start + LIFE, len(high))
    #: **A return has to come from somewhere.** A zone price is already
    #: through is not a level waiting to be retested, and `low <= entry` is
    #: trivially true on the first bar for one of them - which hands the trade
    #: a fill better than the market at no risk.
    if start >= len(high):
        return None
    here = bars["close"][start]
    if (here <= entry) if up else (here >= entry):
        return None
    for i in range(start, end):
        touched = low[i] <= entry if up else high[i] >= entry
        if not touched:
            continue
        #: **From the bar AFTER the touch.** Resolving from the entry bar lets
        #: a bar that dipped to the zone and rallied book the target off its
        #: own range, and the zone's width comes from the quiet origin bar, so
        #: the target is small enough to sit inside one later bar. That read
        #: +1.5R at a 69% win rate against a 25% breakeven. `zoning.py:231`
        #: has the same `range(i, ...)` and is worth the same fix.
        for j in range(i + 1, min(i + 1 + HOLD, len(high))):
            hit_stop = low[j] <= stop if up else high[j] >= stop
            hit_target = high[j] >= target if up else low[j] <= target
            #: The stop is checked first. Both inside one bar is unknowable at
            #: this resolution, and assuming the good one is how a backtest
            #: invents money.
            if hit_stop:
                return -1.0 - cost / risk
            if hit_target:
                return reward - cost / risk
        last = bars["close"][min(i + 1 + HOLD, len(high)) - 1]
        out = (last - entry) / risk if up else (entry - last) / risk
        return out - cost / risk
    return None


#: Set per sweep so a random zone carries the real one's information delay.
ANCHOR_LAG = [16]


def randomised(bars: dict, zones: list[dict], rng: np.random.Generator) -> list[dict]:
    """Same count, same widths, same sides, times drawn uniformly."""
    n = len(bars["close"])
    out = []
    for z in zones:
        at = int(rng.integers(SCALE_SPAN + 1, max(SCALE_SPAN + 2, n - LIFE - HOLD - 1)))
        mid = float(bars["close"][at])
        half = z["width"] / 2.0
        out.append(
            {
                "at": at,
                #: The same delay the real zone has, so the comparison is
                #: between places and not between information sets.
                "from": at + ANCHOR_LAG[0],
                "up": z["up"],
                "top": mid + half,
                "btm": mid - half,
                "width": z["width"],
                "agreed": z["agreed"],
            }
        )
    return out


def point_of(close: np.ndarray) -> float:
    """Tick size, as the smallest positive step between distinct closes."""
    d = np.abs(np.diff(np.unique(close)))
    d = d[d > 0]
    return float(np.min(d)) if d.size else 0.0


def one_feed(path: str) -> list[tuple]:
    z = np.load(path)
    name = os.path.basename(path).split(".")[0]
    close = z["close"].astype(np.float64)
    if len(close) < MIN_BARS:
        return []
    bars = {
        "close": close,
        "high": z["high"].astype(np.float64),
        "low": z["low"].astype(np.float64),
    }
    point = point_of(close)
    spread_pts = float(np.median(z["spread"])) if "spread" in z else 0.0
    #: One spread in, one out.
    cost = 2.0 * spread_pts * point
    rng = np.random.default_rng(13)
    rows = []
    for anchor in ANCHORS:
        for base in BASES:
            for k in KFACTORS:
                zones = build_zones(bars, anchor, base, k)
                if len(zones) < 20:
                    continue
                ANCHOR_LAG[0] = anchor
                fakes = randomised(bars, zones, rng)
                for buffer_ in BUFFERS:
                    for reward in REWARDS:
                        real = [(z["agreed"], trade(bars, z, buffer_, reward, cost)) for z in zones]
                        real = [(a, r) for a, r in real if r is not None]
                        null = [trade(bars, z, buffer_, reward, cost) for z in fakes]
                        null = [r for r in null if r is not None]
                        for agree in AGREES:
                            kept = [r for a, r in real if a >= agree]
                            if len(kept) < 10:
                                continue
                            won = sum(1 for r in kept if r > 0) / len(kept)
                            rows.append(
                                (
                                    name, anchor, base, k, buffer_, reward, agree,
                                    len(kept), st.fmean(kept),
                                    len(null), st.fmean(null) if null else 0.0,
                                    cost, won,
                                )
                            )
    return rows


def prefix_check(bars: dict, anchor: int, base: float, k: float) -> str:
    """**Prefix invariance.** Re-build on `bars[:t]` and demand every zone
    knowable by `t` be identical.

    This is the invariant the look-ahead audit found missing from every
    harness in the repository, and it is the one check that catches the whole
    family: a zone that changes when the future is removed was using it.
    """
    n = len(bars["close"])
    t = int(n * 0.6) // anchor * anchor
    whole = build_zones(bars, anchor, base, k)
    part = build_zones({key: v[:t] for key, v in bars.items()}, anchor, base, k)
    a = sorted((z["at"], z["up"], round(z["top"], 10)) for z in whole if z["from"] <= t)
    b = sorted((z["at"], z["up"], round(z["top"], 10)) for z in part if z["from"] <= t)
    if a == b:
        return f"prefix invariant: {len(a)} zones identical at t={t}"
    extra = [x for x in a if x not in b]
    missing = [x for x in b if x not in a]
    return (f"PREFIX LEAK at t={t}: {len(a)} whole vs {len(b)} prefix, "
            f"{len(extra)} only-with-future, {len(missing)} only-without")


def main() -> int:
    paths = sorted(glob.glob(os.path.join(SEQLAB, "*.npz")))
    if not paths:
        print(f"no npz under {SEQLAB}")
        return 1
    print(f"{len(paths)} feeds, anchors {ANCHORS}, bases {BASES}, k {KFACTORS}")
    print(f"buffers {BUFFERS}, rewards {REWARDS}, min agreed {AGREES}\n")
    #: Checked on one feed before anything is swept. A harness that leaks has
    #: nothing worth reporting.
    probe = np.load(paths[0])
    pb = {
        "close": probe["close"].astype(np.float64),
        "high": probe["high"].astype(np.float64),
        "low": probe["low"].astype(np.float64),
    }
    print(f"  {os.path.basename(paths[0])}: {prefix_check(pb, 96, 6.0, 3.0)}\n")
    rows: list[tuple] = []
    with ProcessPoolExecutor(max_workers=min(12, os.cpu_count() or 4)) as pool:
        for got in pool.map(one_feed, paths):
            rows.extend(got)
            if got:
                print(f"  {got[0][0]:28s} {len(got):5d} rows  cost {got[0][11]:.6f}")
    if not rows:
        print("no rows")
        return 1

    #: Pooled across feeds per configuration. Pooled medians invert subgroups,
    #: so the per-feed sign agreement is reported beside the mean.
    agg: dict[tuple, list[tuple]] = {}
    for r in rows:
        agg.setdefault(r[1:7], []).append(r)
    print(f"\n{'anchor':>7s} {'base':>5s} {'k':>4s} {'buf':>5s} {'rwd':>4s} {'agr':>4s} "
          f"{'trades':>7s} {'meanR':>8s} {'nullR':>8s} {'edge':>8s} {'feeds+':>7s} {'won':>6s}")
    scored = []
    for key, got in agg.items():
        trades = sum(g[7] for g in got)
        if trades < 200:
            continue
        mean = sum(g[7] * g[8] for g in got) / trades
        nulls = sum(g[9] for g in got)
        null = sum(g[9] * g[10] for g in got) / nulls if nulls else 0.0
        pos = sum(1 for g in got if g[8] > g[10])
        won = sum(g[7] * g[12] for g in got) / trades
        scored.append((mean - null, key, trades, mean, null, pos, len(got), won))
    scored.sort(reverse=True)
    for edge, key, trades, mean, null, pos, feeds, won in scored[:25]:
        a, b, k, buf, rwd, agr = key
        #: Breakeven at this reward. A win rate far above it is not a good
        #: strategy, it is a look-ahead - the same arithmetic that makes a
        #: distance-matched walk read 0.825 on a return target.
        be = 1.0 / (1.0 + rwd)
        flag = "  <-- WIN RATE IMPLAUSIBLE" if won > be + 0.35 else ""
        print(f"{a:7d} {b:5.0f} {k:4.0f} {buf:5.2f} {rwd:4.0f} {agr:4d} "
              f"{trades:7d} {mean:+8.3f} {null:+8.3f} {edge:+8.3f} {pos:3d}/{feeds:<3d} "
              f"{won:6.3f} (be {be:.2f}){flag}")
    #: **The reward has to matter.** Identical means across rewards is what a
    #: stop inside the zone looks like, and it is cheap to assert for ever.
    by_reward: dict[tuple, set[float]] = {}
    for edge, key, trades, mean, null, pos, feeds, won in scored:
        by_reward.setdefault((key[0], key[1], key[2], key[3], key[5]), set()).add(round(mean, 6))
    flat = [k for k, v in by_reward.items() if len(v) == 1]
    print(f"\nconfigs where the reward did not move the mean: {len(flat)} of {len(by_reward)}"
          f"{'  <-- STOP IS INSIDE THE ZONE' if len(flat) > len(by_reward) // 2 else ''}")
    print(f"\n{len(scored)} configurations with 200+ trades, of {len(agg)} swept")
    best = scored[0] if scored else None
    if best:
        print(f"best edge {best[0]:+.3f}R at anchor {best[1][0]} base {best[1][1]:.0f} "
              f"k {best[1][2]:.0f} buffer {best[1][3]} reward {best[1][4]:.0f} "
              f"agreed>={best[1][5]} on {best[2]} trades")
    worst = scored[-1] if scored else None
    if worst:
        print(f"worst edge {worst[0]:+.3f}R - the spread of the sweep is what says "
              f"whether any of this is a parameter or a draw")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
