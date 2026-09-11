"""sweep-aware's own entries, under its exit and under ride's, with spread.

sweep-aware is the best live performer on this book (+104 in a day) and runs
the **third-worst exit policy** in the table `Ride` was built from - target at
1x the modelled push, no trail, measured at -0.041R against ride's +0.404R over
31,820 replayed touches.

So its edge looks like the entry filter, not the exit. The obvious change is to
give it ride's exit. The obvious change is also exactly what `Ride`'s docstring
warns against: *"the replay models no spread, which is precisely what sinks
fast entries live"* - and sweep-aware trades from 1m.

Its own 30 closes cannot settle it; only 14 carry a stop and a target. So this
replays **its entry rule** over the published call stream, which is 52,376
calls in 7 days, and walks 1m bars forward under both exits **with the spread
charged**.

## What is modelled and what is not

* **Entry** at the level, which is where it rests. Crossed at half the spread.
* **Exit** crossed at half the spread again, so a round trip pays one spread.
* **No slippage beyond the spread**, no commission, no overnight funding.
* **No queue position.** A resting entry is assumed filled when price touches
  the level, which flatters both policies equally and flatters the resting one
  more - `never filled` was 3.9% of its live attempts.
"""
# ---------------------------------------------------------------------------
#
# ## 2026-09-11: this harness was wrong, and its result is in production
#
# The comparison above is **why `SweepAware` carries `target_multiple=6.0`,
# `trail_vol=0.5` and `break_even_at=1.0` today**. The walk that produced it has
# two look-aheads, found on 2026-09-11 in two sibling harnesses:
#
# * the trail was raised on a bar's own high and then allowed to fill on that
#   same bar, protecting the trade with information it did not have;
# * a stop was booked at its own price even on a bar that gapped straight
#   through it, paying a price the market never offered.
#
# **A trailing policy benefits from both. The fixed-target policy it was
# compared against barely does.** So the comparison that chose the shipping exit
# was biased in the direction of the answer it gave, and the size of that bias
# has never been measured.
#
# This rewrite measures it. The walk now comes from `till_infinity.shared.replay`
# - linted, tested, one implementation - and `_legacy_walk` below reproduces the
# old arithmetic **deliberately**, so both can be run over the *same* trades and
# the difference attributed to the bug rather than to the data.
#
# The data has changed, which is why that matters: `multi.db` is not reachable
# from the research machine, so this runs on `research.db` - 60 days of MT5 bars
# across 53 feeds rather than 7 days. Running one walk here and comparing it to
# a number produced on different bars would confound the two.

from __future__ import annotations

import bisect
import os
import sqlite3
import statistics as st
from collections import defaultdict

from research.harness.sweepregimes import (
    BARS,
    JOURNAL,
    bars_for,
    candidates,
    spreads,
)
from till_infinity.shared.replay import walk

#: How long a trade may run, in 1m bars. The original used 1,440 - a full day -
#: while the live desk holds `sweep-aware` for 1,800 seconds, thirty bars. Kept
#: at 1,440 by default so this reproduces the original question, and overridable
#: so the live answer can be asked separately.
HOLD = int(os.environ.get("HOLD", "1440"))
SPLIT = float(os.environ.get("SPLIT", "0.6"))

#: The two policies the original compared.
OLD_EXIT = {"target_mult": 1.0, "trail_vol": 0.0, "protect_r": 0.0}
RIDE_EXIT = {"target_mult": 6.0, "trail_vol": 0.5, "protect_r": 1.0}


def _legacy_walk(rows, start, trade, cost, policy):
    """**The old arithmetic, reproduced on purpose. Do not copy this.**

    Two deliberate faults, kept so the bias they caused can be measured:

    1. `best` and the trail are updated from *this* bar before the stop is
       tested on the same bar.
    2. A stop is filled at its own price even when the bar opened through it.

    Nothing else differs from the kernel.
    """
    up, unit = trade["up"], trade["unit"]
    if unit <= 0 or trade["push_vol"] <= 0:
        return None
    risk = trade["risk_vol"] * unit
    if risk <= 0:
        return None
    half = cost / 2 if up else -cost / 2
    entry = trade["level"] + half
    stop = entry - risk if up else entry + risk
    target = entry + trade["push_vol"] * policy["target_mult"] * unit * (1 if up else -1)
    trail_vol, protect = policy["trail_vol"], policy["protect_r"]
    best = entry

    last_bar = min(start + HOLD, len(rows))
    for i in range(start, last_bar):
        _ts, _opened, high, low, close = rows[i]
        if None in (high, low, close):
            continue
        # Fault 1: this bar's extreme moves the stop before the stop is tested.
        best = max(best, high) if up else min(best, low)
        gained = ((best - entry) if up else (entry - best)) / risk
        if protect and gained >= protect:
            stop = max(stop, entry) if up else min(stop, entry)
        if trail_vol:
            pull = best - trail_vol * unit if up else best + trail_vol * unit
            stop = max(stop, pull) if up else min(stop, pull)

        hit_stop = low <= stop if up else high >= stop
        hit_target = high >= target if up else low <= target
        if hit_stop:
            # Fault 2: no gap handling - the stop's own price, always.
            left = stop - half
            return ((left - entry) if up else (entry - left)) / risk, "stop"
        if hit_target:
            left = target - half
            return ((left - entry) if up else (entry - left)) / risk, "target"

    if start >= last_bar:
        return None
    left = rows[last_bar - 1][4] - half
    return ((left - entry) if up else (entry - left)) / risk, "hold"


def report(label, rows, keys):
    if len(rows) < 100:
        print(f"  {label}: only {len(rows)} trades")
        return
    print(f"\n  {label}  ({len(rows)} trades)")
    print(f"    {'walk':>10s} {'policy':>12s} {'mean R':>9s} {'median':>9s} "
          f"{'win':>7s} {'stopped':>8s}")
    for key in keys:
        rs = [r[key][0] for r in rows]
        kinds = [r[key][1] for r in rows]
        walk_name, policy_name = key
        print(f"    {walk_name:>10s} {policy_name:>12s} {st.fmean(rs):+9.3f} "
              f"{st.median(rs):+9.3f} {sum(1 for x in rs if x > 0) / len(rs):6.1%} "
              f"{kinds.count('stop') / len(kinds):7.1%}")

    for walk_name in ("legacy", "kernel"):
        old = [r[(walk_name, "old")][0] for r in rows]
        ride = [r[(walk_name, "ride")][0] for r in rows]
        paired = [b - a for a, b in zip(old, ride, strict=True)]
        print(f"    {walk_name}: ride minus its own = {st.fmean(paired):+.3f}R, "
              f"better on {sum(1 for d in paired if d > 0) / len(paired):.1%}")


def run():
    from till_infinity.trading.config import Settings

    settings = Settings.from_env()
    jn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=300.0)
    spread = spreads(jn)
    trades, seen, refused = candidates(jn, settings)
    jn.close()
    print(f"{seen} published level calls; {len(trades)} pass sweep-aware's rule")
    print(f"  refused {refused}\n  hold {HOLD} bars\n")

    conn = sqlite3.connect(f"file:{BARS}?mode=ro", uri=True, timeout=300.0)
    by_feed = defaultdict(list)
    for t in trades:
        by_feed[t["feed"]].append(t)

    keys = [(w, p) for w in ("legacy", "kernel") for p in ("old", "ride")]
    policies = {"old": OLD_EXIT, "ride": RIDE_EXIT}
    done = []
    for feed, part in by_feed.items():
        rows, stamps = bars_for(conn, feed)
        if len(rows) < 500:
            continue
        bps = spread.get(feed, 0.0)
        for t in part:
            start = bisect.bisect_left(stamps, t["when"])
            if start >= len(rows) - 10:
                continue
            cost = t["level"] * bps / 10_000.0
            got = {"when": t["when"]}
            for policy_name, policy in policies.items():
                a = _legacy_walk(rows, start, t, cost, policy)
                b = walk(rows, start, t, cost=cost, hold=HOLD, policy=policy)
                if a is None or b is None:
                    break
                got[("legacy", policy_name)] = a
                got[("kernel", policy_name)] = b
            if len(got) == len(keys) + 1:
                done.append(got)
    conn.close()
    done.sort(key=lambda r: r["when"])
    print(f"{len(done)} replayed under both walks and both policies")

    report("pooled", done, keys)
    edge = int(len(done) * SPLIT)
    report("discovery", done[:edge], keys)
    report("verify", done[edge:], keys)

    print("\nThe `legacy` rows carry two look-aheads on purpose. The question is")
    print("whether ride's exit still wins under `kernel`, because the original")
    print("+0.655R against +0.099R is why sweep-aware ships that exit today.")


if __name__ == "__main__":
    run()
