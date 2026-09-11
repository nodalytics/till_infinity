"""What stop policy stops `sweep-aware` being stopped out so often?

Its own docstring records the problem: **nine of its twelve trades were
stopped**, more than any other strategy on the book. And the irony is in the
name - a strategy built to notice that price runs through a level to take the
stops behind it, being taken out by exactly that.

`research/harness/sweepregimes.py` found the first clue without looking for it.
Of six dimensions that survived a split-sample, `risk_vol` was the only one whose
ordering held in **every** interval, and it strengthened as the timeframe grew:
wider initial stops score better, by 0.135R at 1m rising to 0.548R at 15m. That
is suspicious as a regime and obvious as a mechanism - the trail is a **fixed**
0.5 volatility units, so against a 1-vol stop it gives back 0.5R and against a
2-vol stop only 0.25R. The gradient may be the trail, not the market.

So this measures policies rather than conditions, on the same replayed trades,
and reports the number the question is actually about: **how often each one is
stopped**.

## The policies, and what each is a theory about

* `current` - what ships. Stop at the modelled risk, trail half a volatility
  unit from the extreme, break even at 1R, target at 6x the push.
* `no_trail` - the trail is what converts a winner into a scratch. Removing it
  says the target and the stop are enough.
* `trail_late` - trail only once the trade is 1R up, so the first push is not
  policed by a stop that tightens on noise.
* `trail_scaled` - trail at half the *risk* rather than half a volatility unit.
  This is the direct test of the mechanism above: if the `risk_vol` gradient is
  the fixed trail, scaling it should flatten the gradient.
* `be_never` / `be_late` - break-even at 1R is a classic source of stop-outs,
  because it puts the stop exactly where price is most likely to retest. These
  ask whether protecting the trade costs more than it saves.
* `close_only` - **the sweep-aware policy.** Stop on a bar's *close* beyond the
  level, not on its wick. A sweep is a wick; a strategy that models sweeps and
  then stops on them is arguing with itself.
* `grace_10` - ignore the stop for ten bars. The blunt version of `close_only`:
  survive the entry noise, then behave normally.
* `wide_15` / `wide_20` - simply a wider initial stop. R is normalised by risk,
  so this is a fair comparison in R and a smaller position for the same dollars.
* `beyond_pool` - put the stop past the resting liquidity the strategy currently
  *refuses* to trade in front of. If that works, a filter becomes a stop rule,
  and the 12,617 calls refused as `in_front` come back.

## What is being held constant

Entry, direction, level, size in R, and the 6x target - everything but the exit.
Changing more than one thing makes this a different trade rather than the same
trade under a different rule, which is the mistake `thesis-only` made in reverse.

The spread is charged on both legs, as in `exits.py`. Paired: every policy sees
exactly the same trades, so `better on N%` is a like-for-like count rather than
two distributions with different members.

Usage:
    JOURNAL=~/till_infinity/data/journal.db BARS=~/till_infinity/data/research.db \\
    python3 -m research.harness.sweepstops
"""

from __future__ import annotations

import bisect
import os
import sqlite3
import statistics as st
from collections import defaultdict

from research.harness.sweepregimes import (
    BARS,
    ENTRIES,
    HOLD,
    JOURNAL,
    bars_for,
    candidates,
    spreads,
)
from till_infinity.shared.replay import walk

SPLIT = float(os.environ.get("SPLIT", "0.6"))
MIN_N = int(os.environ.get("MIN_N", "300"))


POLICIES = {
    # `current` is the class's own numbers. `live_wick` is what the service
    # actually applies to them, which is not the same policy - and the gap
    # between these two rows is the cost of an uncapped widening rule.
    "current": {},
    # **The policy `ride` replaced, re-tested on a corrected walk.**
    #
    # `exits.py` scored this at +0.099R against ride's +0.655R over 30,875
    # replayed calls and that is why `sweep-aware` carries ride's exit today.
    # That harness raises the trail on a bar's own high and then fills on the
    # same bar, and books the stop at its own price on a bar that opened
    # straight through it - the two look-aheads found here. A trailing policy
    # benefits from both and a fixed-target one barely does, so the comparison
    # that chose the shipping exit was biased in exactly the direction of the
    # answer it gave. This row is what re-runs that decision.
    "old_exit": {"target_mult": 1.0, "trail_vol": 0.0, "protect_r": 0.0},
    "live_wick": {"wick_trail": True},
    "wick_cap_2v": {"wick_trail": True, "cap_vol": 2.0},
    "wick_cap_1v": {"wick_trail": True, "cap_vol": 1.0},
    "wick_cap_risk": {"wick_trail": True, "cap_risk": 1.0},
    "wick_cap_half_risk": {"wick_trail": True, "cap_risk": 0.5},
    "no_trail": {"trail_vol": 0.0},
    "trail_late": {"trail_after_r": 1.0},
    "trail_scaled": {"trail_vol": 0.0, "trail_risk": 0.5},
    "be_never": {"protect_r": 0.0},
    "be_late": {"protect_r": 2.0},
    "close_only": {"close_only": True},
    "grace_10": {"grace": 10},
    "wide_15": {"stop_mult": 1.5},
    "wide_20": {"stop_mult": 2.0},
    "beyond_pool": {"beyond_pool": True},
    # The two most promising ideas together, because a policy is a package.
    "close_be_late": {"close_only": True, "protect_r": 2.0},
    "wide_trail_scaled": {"stop_mult": 1.5, "trail_vol": 0.0, "trail_risk": 0.5},
}


def replay(trades, bars_db, spread):
    """Every policy on every trade, kept together so the comparison is paired."""
    conn = sqlite3.connect(f"file:{bars_db}?mode=ro", uri=True, timeout=300.0)
    by_feed = defaultdict(list)
    for t in trades:
        by_feed[t["feed"]].append(t)

    got = []
    for feed, part in sorted(by_feed.items(), key=lambda kv: -len(kv[1])):
        rows, stamps = bars_for(conn, feed)
        if len(rows) < 500:
            continue
        bps = spread.get(feed, 0.0)
        for t in part:
            start = bisect.bisect_left(stamps, t["when"])
            if start >= len(rows) - 10:
                continue
            cost = t["level"] * bps / 10_000.0
            out = {}
            for name, policy in POLICIES.items():
                answer = walk(rows, start, t, cost=cost, hold=HOLD, policy=policy)
                if answer is None:
                    break
                out[name] = answer
            if len(out) == len(POLICIES):
                got.append({"when": t["when"], "interval": t["interval"], "by": out})
    conn.close()
    return got


def report(title, rows):
    if len(rows) < MIN_N:
        print(f"  {title}: only {len(rows)} trades")
        return
    base = [r["by"]["current"][0] for r in rows]
    print(f"\n  {title}  ({len(rows)} trades)")
    print(
        f"    {'policy':>18s} {'mean R':>9s} {'median':>9s} {'win':>7s} "
        f"{'stopped':>8s} {'target':>7s} {'vs now':>9s} {'better':>7s}"
    )
    ranked = []
    for name in POLICIES:
        rs = [r["by"][name][0] for r in rows]
        kinds = [r["by"][name][1] for r in rows]
        stopped = kinds.count("stop") / len(kinds)
        hit = kinds.count("target") / len(kinds)
        paired = st.fmean([a - b for a, b in zip(rs, base, strict=True)])
        better = sum(1 for a, b in zip(rs, base, strict=True) if a > b) / len(rs)
        ranked.append((st.fmean(rs), name, st.median(rs), stopped, hit, paired, better))
    for mean, name, med, stopped, hit, paired, better in sorted(ranked, reverse=True):
        win = sum(1 for r in [x["by"][name][0] for x in rows] if r > 0) / len(rows)
        mark = " <- ships" if name == "current" else ""
        print(
            f"    {name:>18s} {mean:+9.3f} {med:+9.3f} {win:6.1%} "
            f"{stopped:7.1%} {hit:6.1%} {paired:+9.3f} {better:6.1%}{mark}"
        )


def run():
    from till_infinity.trading.config import Settings

    settings = Settings.from_env()
    jn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=300.0)
    spread = spreads(jn)
    trades, seen, refused = candidates(jn, settings)
    jn.close()
    print(f"{seen} published level calls; {len(trades)} pass sweep-aware's rule")
    print(f"  refused {refused}\n")

    rows = replay(trades, BARS, spread)
    rows.sort(key=lambda r: r["when"])
    print(f"{len(rows)} replayed under {len(POLICIES)} policies each")

    edge = int(len(rows) * SPLIT)
    report("discovery", rows[:edge])
    report("verify", rows[edge:])
    report("pooled", rows)

    print("\n  by entry timeframe, verify half only:")
    for interval in ENTRIES:
        part = [r for r in rows[edge:] if r["interval"] == interval]
        if len(part) >= MIN_N:
            report(f"verify {interval}", part)

    print("\n`stopped` is the column the question was about. A policy that lifts")
    print("mean R while stopping just as often has bought something else.")
    print("\nR is normalised by risk, so a wider stop is a fair comparison and a")
    print("smaller position for the same dollars - not free money.")


if __name__ == "__main__":
    run()
