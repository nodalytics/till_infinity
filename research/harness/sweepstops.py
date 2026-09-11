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
    num,
    spreads,
)

SPLIT = float(os.environ.get("SPLIT", "0.6"))
MIN_N = int(os.environ.get("MIN_N", "300"))


def walk(rows, start, trade, cost, policy):  # noqa: PLR0912, PLR0915 - one exit rule,
    # written as the linear sequence the broker applies rather than split across
    # helpers that would hide the order the checks happen in.
    """R and how the trade ended, under one exit policy.

    Returns `(r, kind)` where kind is "stop", "target" or "hold". The kind is
    the point: a policy that improves mean R by being stopped just as often has
    not answered the question that was asked.
    """
    up, unit = trade["up"], trade["unit"]
    if unit <= 0 or trade["push_vol"] <= 0:
        return None
    risk = trade["risk_vol"] * unit * policy.get("stop_mult", 1.0)
    if policy.get("beyond_pool"):
        beyond = num(trade["context"], "liquidity_beyond_vol")
        if beyond <= 0:
            return None
        # Past the pool, plus a tenth of a unit so a touch is not a stop.
        risk = (beyond + 0.1) * unit
    if risk <= 0:
        return None

    entry = trade["level"] + (cost / 2 if up else -cost / 2)
    stop = entry - risk if up else entry + risk
    target = entry + trade["push_vol"] * 6.0 * unit * (1 if up else -1)
    trail_vol = policy.get("trail_vol", 0.5)
    trail_risk = policy.get("trail_risk")
    # **What actually ships.** `manage.stop_for` widens the trail to clear this
    # level's own wicks - `room = max(trail_vol, wick + sd * trail_sigmas)` -
    # and that rule has no ceiling. Measured over 47,233 level calls, the
    # computed trail is the 0.5v floor only 59% of the time, exceeds 1v on
    # 30.2%, exceeds 3v on 9.4%, and its maximum is **2,239v**. On levels
    # selected for being swept, the wick distribution is exactly the fat-tailed
    # one that rule cannot survive.
    #
    # A trail wider than the trade's own risk protects nothing: it gives back
    # more than the stop it replaced would have lost, so `cap_risk` is the
    # natural ceiling and `cap_vol` an absolute one.
    if policy.get("wick_trail"):
        context = trade["context"]
        side = "below" if up else "above"
        seen = num(context, "wick_n")
        if seen >= 2:
            room = num(context, f"wick_{side}_vol") + num(context, f"wick_{side}_sd") * 0.5
            trail_vol = max(trail_vol, room)
        cap_vol = policy.get("cap_vol")
        if cap_vol:
            trail_vol = min(trail_vol, cap_vol)
        if policy.get("cap_risk"):
            trail_vol = min(trail_vol, trade["risk_vol"] * policy["cap_risk"])
    protect = policy.get("protect_r", 1.0)
    trail_after = policy.get("trail_after_r", 0.0)
    grace = policy.get("grace", 0)
    close_only = policy.get("close_only", False)
    best = entry

    stop_at = min(start + HOLD, len(rows))
    for i in range(start, stop_at):
        _ts, opened, high, low, close = rows[i]
        if high is None or low is None or close is None or opened is None:
            continue
        resting = i - start < grace

        # **Exits first, against the stop as it stood coming into this bar.**
        #
        # The order within a bar is not knowable from OHLC, so the only honest
        # sequence is to test the levels that were actually resting at the
        # broker when the bar opened, and only then let this bar's extreme move
        # them for the next one. Doing it the other way round - raising the
        # trail on this bar's high and then filling on the same bar - protects
        # the trade with information it did not have, which is a look-ahead
        # wearing the clothes of a trailing stop.
        #
        # Two of those were found here. This one, and a grace window that let
        # the trail tighten while forbidding it to fire, so the exit at bar ten
        # booked a price the market had already left. Before they were fixed
        # this harness reported `grace_10` at **+1.335R** against a shipping
        # policy at +0.344R, better on 63.5% of the same trades, holding in both
        # halves of a split sample. Every one of those guards passed. None of
        # them can see a replay that is cheating.
        if not resting:
            # The wick or the close, which is the whole of `close_only`.
            low_seen, high_seen = (close, close) if close_only else (low, high)
            if (low_seen <= stop) if up else (high_seen >= stop):
                # A bar that opens already through the stop fills at the open.
                # Anything else pays itself a price that was not on offer.
                through = (opened <= stop) if up else (opened >= stop)
                out = close if close_only else (opened if through else stop)
                out = out - (cost / 2 if up else -cost / 2)
                return ((out - entry) if up else (entry - out)) / risk, "stop"
            if (high >= target) if up else (low <= target):
                through = (opened >= target) if up else (opened <= target)
                out = (opened if through else target) - (cost / 2 if up else -cost / 2)
                return ((out - entry) if up else (entry - out)) / risk, "target"

        best = max(best, high) if up else min(best, low)
        gained = ((best - entry) if up else (entry - best)) / risk

        # The stop does not move while it cannot fire, for the reason above.
        if resting:
            continue
        if protect and gained >= protect:
            stop = max(stop, entry) if up else min(stop, entry)
        if gained >= trail_after:
            step = trail_risk * risk if trail_risk is not None else trail_vol * unit
            if step:
                pull = best - step if up else best + step
                stop = max(stop, pull) if up else min(stop, pull)

    if start < stop_at:
        last = rows[stop_at - 1][4]
        out = last - (cost / 2 if up else -cost / 2)
        return ((out - entry) if up else (entry - out)) / risk, "hold"
    return None


POLICIES = {
    # `current` is the class's own numbers. `live_wick` is what the service
    # actually applies to them, which is not the same policy - and the gap
    # between these two rows is the cost of an uncapped widening rule.
    "current": {},
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
                answer = walk(rows, start, t, cost, policy)
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
