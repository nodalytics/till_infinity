"""Would a deliberately convex exit beat the one that ships, and is the tail cut off?

`research/convexity.md`. The desk owner's framing: *stop paying for accuracy*.
Every strategy on this book is built to be right often, `clustering.md` and
`horizon.md` both measured direction as close to unforecastable at the horizon
traded, and the book is net negative. So the question is whether the money is
in the **shape** of the trade rather than in the call - lose small and often,
win large and rarely - and whether the current exit is destroying that shape.

Two claims in the folder say the shape is already there and already being cut:

* `exiting.md` - ride's exit earns **+0.046R while being worse on 64% of the
  same trades.** It wins only through a thin right tail.
* `giveback.md` - the desk keeps **27%** of its high-water mark, and 38 of 47
  `sweep-aware` closes end on the **hold timeout** rather than on any rule.

A convex policy that times out its winners has inverted itself, so the first
thing measured here is the hold cap and nothing else.

## The three questions, in the order they are answered

1. **Is the tail being cut off by the clock?** The same trades, the same
   shipping exit, walked under eight hold caps from the live 30 bars out to
   2,880. If the mean and the 95th percentile keep climbing past 30, the clock
   is the binding constraint and nothing about the exit *rules* matters yet.
2. **Would a deliberately convex policy do better?** Tiny stop, no target,
   wide trail, long hold - against what ships and against a deliberately
   **concave** control (wide stop, near target) that should do the opposite.
3. **Does the convex side of a one-sided generator pay?** Boom spikes up and
   grinds down; Crash spikes down and grinds up. A position held in the spike
   direction has a bounded downside and an unbounded upside, which is the
   structurally convex bet on this book. `instruments.md` measured the desk on
   the wrong side of it and then **withdrew** the finding - the replay's
   buy-minus-sell gap had the *same* sign on both families, which is a long
   bias and not a spike effect. So this run carries a long-bias control.

## Why R is the unit and why that is not a dodge

Every policy here is scored in multiples of its own initial risk. That is fair
**only because the desk sizes to risk** - the live record carries `risk_money`
against `risk_price` and `volume`, so halving the stop halves the position for
the same dollars. A tiny stop is therefore not leverage; it is the same money
cut finer. What it *is* is more expensive: the spread is charged in price and
divided by a smaller risk, so `stop_mult=0.5` pays **twice** the cost in R.
That is charged here and it is a real part of the answer.

## What would count as failure, declared before the run

The convex policy fails if any of these holds:

* its mean R does not beat what ships **in the verify half**;
* it beats on the mean but its 95th percentile does not move - which would say
  the gain is a broad shift and the convexity framing is decoration;
* the advantage disappears when the single best replayed trade is removed;
* `no_trail` and `concave` score the same as `convex`, which would say the
  exit rules do nothing on this population and only the clock matters.

**A null is a real result**, and the most likely one: `sweepstops.py` put
eighteen exit policies against this same population on the corrected walk and
**none beat what ships by more than noise.** This asks a different question of
the same data - not "which exit is better on average" but "which exit has a
tail" - and the honest prior is that it comes back flat too.

## What is not modelled

Inherited from `exits.py` and unchanged: no queue position (a resting entry is
assumed filled the moment price touches, and `never filled` was 3.9% of live
attempts), spread only on the 33 feeds that have a record, no commission, no
funding, no slippage beyond the spread, and no opportunity cost - a policy
holding 24 hours against `max_positions=10` occupies a slot this cannot see.
Those errors are the **same in every policy**, which is what makes the paired
comparison meaningful where the absolute R is not.

The last one matters more here than anywhere else in the folder, because the
whole point of a convex policy is to hold longer. **A 48-fold hold difference
cannot be free**, and this replay prices none of it.

Usage:
    JOURNAL=~/till_infinity/data/journal.db BARS=~/till_infinity/data/research.db \\
    WORKERS=16 python3 -m research.harness.convexity
"""

from __future__ import annotations

import bisect
import math
import multiprocessing as mp
import os
import random
import sqlite3
import statistics as st
from collections import defaultdict

from research.harness.sweepregimes import (
    BARS,
    JOURNAL,
    bars_for,
    candidates,
    num,
    spreads,
)
from till_infinity.shared.replay import walk
from till_infinity.shared.strata import compare

SPLIT = float(os.environ.get("SPLIT", "0.6"))
MIN_N = int(os.environ.get("MIN_N", "300"))
WORKERS = int(os.environ.get("WORKERS", "16"))
#: How many trades one worker takes at a time. Small enough that one enormous
#: feed does not become the critical path, large enough that reloading that
#: feed's bars per chunk stays a rounding error.
CHUNK = int(os.environ.get("CHUNK", "1200"))
#: Random deciles drawn for the tail-feature control.
CONTROLS = int(os.environ.get("CONTROLS", "500"))
#: Cap the candidate set. Zero means all of it; a small number is for checking
#: that the thing runs before committing an hour of a 64-core box to it.
LIMIT = int(os.environ.get("LIMIT", "0"))
SEED = int(os.environ.get("SEED", "20260911"))

#: The live desk's hold, in 1m bars. `giveback.md`: a 30-minute clock, and four
#: in five `sweep-aware` closes end on it.
LIVE_HOLD = 30
#: "No cap at all", for a desk that holds for half an hour. A day.
LONG_HOLD = 1440
#: The ladder. Every trade in this study has room for the longest of these, so
#: the rungs are the same trades under a different clock and nothing else.
LADDER = (15, 30, 60, 120, 240, 480, 960, 1440, 2880)
RUNWAY = max(LADDER)

#: Tiny stop, no target, wide trail, long hold - the shape the question asks
#: for. `target_mult` is not zero but absurd: `walk` always places a target, so
#: "no target" is one the trade cannot reach.
CONVEX = {"stop_mult": 0.5, "target_mult": 1000.0, "trail_risk": 3.0, "protect_r": 0.0}

#: Each entry is `(policy, hold)`. Everything but the exit is held constant -
#: entry, direction, level and the risk the position is sized against - so a row
#: is the same trade under a different rule rather than a different trade.
GRID: dict[str, tuple[dict, int]] = {
    # What ships, on the clock it ships with. This is the row every other row is
    # paired against.
    "shipping_30": ({}, LIVE_HOLD),
    # The same rules with the clock removed. The gap between these two rows is
    # the entire cost of the hold cap, with no policy change mixed in.
    "shipping_long": ({}, LONG_HOLD),
    # **What the desk actually applies, which is not what the class asks for.**
    # `manage.stop_for` widens the trail to clear each level's own wicks and the
    # rule has no ceiling: over 47,233 level calls the computed trail is the
    # 0.5v floor only 59% of the time and its maximum is 2,239v. That is why the
    # live desk exits 81% by timeout while this replay's `shipping` row exits
    # ~99% by stop, and it is the row the hold-cap question has to be asked of -
    # a clock only binds on a trade that would otherwise still be open.
    "live_wick_30": ({"wick_trail": True}, LIVE_HOLD),
    "live_wick_long": ({"wick_trail": True}, LONG_HOLD),
    # The clock removed *and* the target removed: now only a stop or a trail can
    # end the trade, which is what "let it run until stopped" means.
    "let_it_run": ({"target_mult": 1000.0}, LONG_HOLD),
    # The asked-for policy and three decompositions of it, so that if it wins it
    # is known *which* of the four changes won.
    "convex": (CONVEX, LONG_HOLD),
    "convex_tighter": ({**CONVEX, "stop_mult": 0.33}, LONG_HOLD),
    "convex_full_stop": ({**CONVEX, "stop_mult": 1.0}, LONG_HOLD),
    "convex_no_trail": ({**CONVEX, "trail_risk": None, "trail_vol": 0.0}, LONG_HOLD),
    "convex_trail_late": ({**CONVEX, "trail_after_r": 3.0}, LONG_HOLD),
    # Break-even is the most anti-convex rule on the book: it converts a trade
    # that has started to work into one that cannot pay. This isolates it.
    "convex_break_even": ({**CONVEX, "protect_r": 1.0}, LONG_HOLD),
    # **The control, and it is the important row.** Deliberately concave: wide
    # stop, target at half the modelled push, nothing trailing. It should win
    # far more often and earn less, and its 95th percentile should be flat. If
    # it scores the same as `convex` then the exit rules are doing nothing on
    # this population and only the clock is real.
    "concave": (
        {"stop_mult": 2.0, "target_mult": 0.5, "trail_vol": 0.0, "protect_r": 0.0},
        LONG_HOLD,
    ),
}

#: What is knowable at the moment the level is published, kept so the tail can
#: be cut by it later. Everything else in the decision context is dropped before
#: the row leaves the worker: 30,000 full contexts is a gigabyte of pickling for
#: fields nothing reads.
#:
#: `edge`, `expected_push_vol` and `probability_up` are **up-positive**, so a
#: tercile of the raw field is a tercile of `side`. They are re-expressed
#: relative to the trade's own direction, as `winning.py` does, and the raw
#: fields are kept beside them so the difference is visible rather than assumed.
FEATURES = (
    "vol_stretch", "forecast_ratio", "vol_bps", "edge", "strength",
    "probability_up", "sweep_rate", "sweep_n", "liquidity_beyond_vol",
    "risk_vol", "expected_push_vol", "range_position", "range_width_vol",
    "origin_distance_vol", "origin_size_vol", "origin_revisits", "in_origin",
    "origin_confirmed", "own_touches", "neighbours", "wick_n",
    "wick_above_vol", "wick_below_vol", "spread_bps", "base_rate_up",
)

#: Dimensions times policies is the number of chances this had to find
#: something, printed with the results rather than left to be reconstructed.
COMPARISONS = len(GRID) - 1 + len(LADDER) * 3 + len(FEATURES) + 3


SYNTHETIC = ("boom_", "crash_", "jump_", "volatility_", "step_", "range_break_")


def klass(feed: str) -> str:
    return "synthetic" if str(feed).startswith(SYNTHETIC) else "real"


def features_of(trade) -> dict:
    """The decision-time numbers, direction-corrected where the field is signed."""
    ctx = trade["context"]
    sign = 1.0 if trade["up"] else -1.0
    got = {k: num(ctx, k) for k in FEATURES if isinstance(ctx.get(k), int | float)}
    for key, name in (("edge", "edge_with"), ("expected_push_vol", "push_with")):
        if isinstance(ctx.get(key), int | float):
            got[name] = float(ctx[key]) * sign
    if isinstance(ctx.get("probability_up"), int | float):
        up = float(ctx["probability_up"])
        got["prob_with"] = up if sign > 0 else 1.0 - up
    below, above = ctx.get("wick_below_vol"), ctx.get("wick_above_vol")
    if isinstance(below, int | float) and isinstance(above, int | float):
        got["wick_ahead"] = float(above if sign > 0 else below)
        got["wick_behind"] = float(below if sign > 0 else above)
    risk, vol = num(ctx, "risk_vol"), num(ctx, "vol_bps")
    if risk and vol:
        # The one contrast this project wrote down *before* measuring it:
        # `exiting.md` derives the cost in R as spread / (risk_vol * vol_bps).
        got["spread_over_risk"] = num(ctx, "spread_bps") / (abs(risk) * vol)
    return got


# ------------------------------------------------------------------ workers


_STATE: dict = {}


def _init(bars_db: str) -> None:
    _STATE["conn"] = sqlite3.connect(f"file:{bars_db}?mode=ro", uri=True, timeout=300.0)
    _STATE["bars"] = {}


def _bars(feed: str):
    got = _STATE["bars"].get(feed)
    if got is None:
        got = bars_for(_STATE["conn"], feed)
        # One feed at a time. Holding all 53 would be ~4M bars in every worker.
        _STATE["bars"] = {feed: got}
    return got


def _run_chunk(task):
    """Every policy and every ladder rung on one block of one feed's trades."""
    feed, cost_bps, trades = task
    rows, stamps = _bars(feed)
    if len(rows) < 500:
        return []
    out = []
    for t in trades:
        start = bisect.bisect_left(stamps, t["when"])
        # **The runway rule.** `walk` silently ends at the last bar it has, and
        # labels that exit `hold`. A trade without room for the longest rung
        # would therefore be scored as having timed out when it merely ran out
        # of data, which biases exactly the policies this study is about.
        if start >= len(rows) - RUNWAY:
            continue
        cost = t["level"] * cost_bps / 10_000.0
        by = {}
        broke = False
        for name, (policy, hold) in GRID.items():
            got = walk(rows, start, t, cost=cost, hold=hold, policy=policy)
            if got is None:
                broke = True
                break
            by[name] = got
        if broke:
            continue
        ladder = {}
        for hold in LADDER:
            for label, policy in (
                ("shipping", {}),
                ("live_wick", {"wick_trail": True}),
                ("convex", CONVEX),
            ):
                got = walk(rows, start, t, cost=cost, hold=hold, policy=policy)
                if got is None:
                    broke = True
                    break
                ladder[(label, hold)] = got
            if broke:
                break
        if broke:
            continue
        out.append(
            {
                "when": t["when"],
                "feed": feed,
                "interval": t["interval"],
                "up": t["up"],
                "klass": klass(feed),
                "by": by,
                "ladder": ladder,
                "f": features_of(t),
            }
        )
    return out


# ------------------------------------------------------------------ reporting


def quantile(values, q: float) -> float:
    got = sorted(values)
    if not got:
        return float("nan")
    return got[min(len(got) - 1, int(q * len(got)))]


def stats(rs: list[float]) -> dict:
    return {
        "n": len(rs),
        "mean": st.fmean(rs),
        "median": st.median(rs),
        "win": sum(1 for r in rs if r > 0) / len(rs),
        "p95": quantile(rs, 0.95),
        "p99": quantile(rs, 0.99),
        "max": max(rs),
    }


def ladder_table(title: str, rows: list[dict]) -> None:
    """The hold cap, and nothing else, moved."""
    if len(rows) < MIN_N:
        print(f"  {title}: only {len(rows)} trades")
        return
    print(f"\n  {title}  ({len(rows)} trades)")
    for label in ("shipping", "live_wick", "convex"):
        print(f"    {label}'s exit under each hold cap:")
        print(
            f"      {'hold':>7s} {'mean R':>9s} {'median':>9s} {'win':>7s} "
            f"{'p95':>9s} {'max':>9s} {'timed out':>10s} {'stopped':>8s}"
        )
        for hold in LADDER:
            rs = [r["ladder"][(label, hold)][0] for r in rows]
            kinds = [r["ladder"][(label, hold)][1] for r in rows]
            got = stats(rs)
            mark = "  <- ships" if label == "shipping" and hold == LIVE_HOLD else ""
            print(
                f"      {hold:7d} {got['mean']:+9.3f} {got['median']:+9.3f} "
                f"{got['win']:6.1%} {got['p95']:+9.3f} {got['max']:+9.2f} "
                f"{kinds.count('hold') / len(kinds):9.1%} "
                f"{kinds.count('stop') / len(kinds):7.1%}{mark}"
            )


def grid_table(title: str, rows: list[dict], base: str = "shipping_30") -> None:
    """Every policy on the same trades, paired against what ships."""
    if len(rows) < MIN_N:
        print(f"  {title}: only {len(rows)} trades")
        return
    anchor = [r["by"][base][0] for r in rows]
    print(f"\n  {title}  ({len(rows)} trades, paired)")
    print(
        f"    {'policy':>19s} {'mean R':>9s} {'median':>9s} {'win':>7s} "
        f"{'p95':>9s} {'p99':>9s} {'max':>8s} {'vs ships':>9s} {'better':>7s} "
        f"{'-best':>9s}"
    )
    ranked = []
    for name in GRID:
        rs = [r["by"][name][0] for r in rows]
        got = stats(rs)
        paired = st.fmean([a - b for a, b in zip(rs, anchor, strict=True)])
        better = sum(1 for a, b in zip(rs, anchor, strict=True) if a > b) / len(rs)
        # `instruments.md` records a whole instrument ranking that was one
        # +622.63 trade. Every mean here is reported again without its own
        # single largest member.
        cut = sorted(rs)[:-1]
        ranked.append((got, name, paired, better, st.fmean(cut)))
    for got, name, paired, better, without in sorted(ranked, key=lambda z: -z[0]["mean"]):
        mark = " <- ships" if name == base else ""
        print(
            f"    {name:>19s} {got['mean']:+9.3f} {got['median']:+9.3f} "
            f"{got['win']:6.1%} {got['p95']:+9.3f} {got['p99']:+9.3f} "
            f"{got['max']:+8.2f} {paired:+9.3f} {better:6.1%} {without:+9.3f}{mark}"
        )


def concentration(title: str, rows: list[dict], name: str) -> None:
    """Where a policy's money comes from, in its own R.

    The whole premise is that the top few trades carry the book. A policy is
    convex in the sense meant here if its **gross profit is concentrated** and
    its losses are not - so both sides are printed, because a number with no
    mirror is not a shape.
    """
    rs = sorted((r["by"][name][0] for r in rows), reverse=True)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    if not wins or not losses:
        return
    gross, bled = sum(wins), sum(losses)
    top5 = sum(rs[: max(1, len(rs) // 20)])
    worst5 = sum(sorted(rs)[: max(1, len(rs) // 20)])
    print(
        f"    {name:>19s} {title}: top 5% = {top5 / gross:6.1%} of gross profit, "
        f"worst 5% = {worst5 / bled:6.1%} of gross loss, "
        f"best {rs[0]:+.2f}R vs worst {rs[-1]:+.2f}R"
    )


def sides(title: str, rows: list[dict], policies: tuple[str, ...]) -> None:
    """Boom and Crash by side, under each policy, with a long-bias control."""
    families = {
        "boom": ("boom_300_index", "boom_500_index", "boom_1000_index"),
        "crash": ("crash_300_index", "crash_500_index", "crash_1000_index"),
    }
    member = {f: k for k, fs in families.items() for f in fs}
    print(f"\n  {title}")
    for name in policies:
        by = defaultdict(list)
        for r in rows:
            fam = member.get(r["feed"], "other")
            by[(fam, "buy" if r["up"] else "sell")].append(r["by"][name][0])
        if not by:
            continue
        print(f"    under {name}:")
        print(f"      {'family':<8s} {'side':<5s} {'n':>7s} {'mean R':>9s} {'p95':>9s} {'win':>7s}")
        for (fam, side), rs in sorted(by.items()):
            if len(rs) < MIN_N:
                continue
            got = stats(rs)
            # The spike runs *with* a boom buy and *with* a crash sell. That is
            # the convex side: bounded grind against, unbounded spike for.
            convexly = (fam == "boom" and side == "buy") or (fam == "crash" and side == "sell")
            mark = "  <- spike with" if convexly else ""
            print(
                f"      {fam:<8s} {side:<5s} {len(rs):7d} {got['mean']:+9.3f} "
                f"{got['p95']:+9.3f} {got['win']:6.1%}{mark}"
            )
        gaps = {}
        for fam in ("boom", "crash", "other"):
            buys, sells = by.get((fam, "buy"), []), by.get((fam, "sell"), [])
            if len(buys) >= MIN_N and len(sells) >= MIN_N:
                gaps[fam] = st.fmean(buys) - st.fmean(sells)
                print(f"      {fam}: buy - sell = {gaps[fam]:+.3f}R")
        if "boom" in gaps and "crash" in gaps:
            # The hypothesis needs boom's gap positive and crash's negative. The
            # same sign on both is the replay's own long bias, which `other`
            # measures directly.
            drift = gaps.get("other", 0.0)
            print(
                f"      net of the long bias on everything else ({drift:+.3f}R): "
                f"boom {gaps['boom'] - drift:+.3f}  crash {gaps['crash'] - drift:+.3f}"
                f"   {'OPPOSITE signs - a spike effect' if (gaps['boom'] - drift) * (gaps['crash'] - drift) < 0 else 'SAME sign - not a spike effect'}"
            )


def tail_features(rows: list[dict], policy: str, split: int) -> None:
    """What the tail winners have in common - if anything.

    **The tail is defined by the replay's R under a convex policy**, because
    that is the closest thing the walk can produce to `best_r`: a policy with no
    target and a three-R trail exits near its own high-water mark, so its top
    decile is the set of trades that went furthest in front. `walk` returns R
    and an exit kind and nothing else, and the excursion is not recoverable from
    it without changing package code.

    The cut is made on the **discovery** half and the threshold carried into
    verify, which is what makes the second column a test rather than a second
    fit. Every feature is then compared tail-against-rest through
    `shared.strata.compare`, which cuts within interval and feed class and
    warns when the pooled ordering flips - four Simpson reversals in this
    repository say do not skip that.

    The control is the part that decides the answer. A decile of 30,000 trades
    has a mean for every feature, and 28 features give 28 chances for one of
    them to look separated. So the same statistic is computed on **a random
    decile of the same trades**, 500 times, and what is reported is the largest
    standardised gap over all features against the largest the random deciles
    produce. `generated.md` is the precedent: the biggest correlation in a
    325-pair study was between two unrelated instruments.
    """
    rng = random.Random(SEED)
    discovery, verify = rows[:split], rows[split:]
    got = sorted((r["by"][policy][0] for r in discovery), reverse=True)
    cut = got[max(1, len(got) // 10) - 1]
    for r in rows:
        r["_tail"] = "tail" if r["by"][policy][0] >= cut else "rest"
    d_tail = sum(1 for r in discovery if r["_tail"] == "tail")
    v_tail = sum(1 for r in verify if r["_tail"] == "tail")
    print(f"\n  tail = top decile of {policy} R, threshold {cut:+.3f}R set on discovery")
    print(f"    discovery {d_tail}/{len(discovery)} tail;  verify {v_tail}/{len(verify)} tail")
    if d_tail < MIN_N or v_tail < 50:
        print("    too thin to cut")
        return

    names = sorted({k for r in rows for k in r["f"]})
    scored = []
    for name in names:
        seen = [r for r in discovery if name in r["f"]]
        tail = [r["f"][name] for r in seen if r["_tail"] == "tail"]
        rest = [r["f"][name] for r in seen if r["_tail"] == "rest"]
        if len(tail) < 100 or len(rest) < 100:
            continue
        pooled = st.pstdev([r["f"][name] for r in seen])
        if pooled <= 0:
            continue
        gap = (st.fmean(tail) - st.fmean(rest)) / pooled
        vt = [r["f"][name] for r in verify if name in r["f"] and r["_tail"] == "tail"]
        vr = [r["f"][name] for r in verify if name in r["f"] and r["_tail"] == "rest"]
        vgap = None
        if len(vt) >= 25 and len(vr) >= 100:
            vpool = st.pstdev(vt + vr)
            vgap = (st.fmean(vt) - st.fmean(vr)) / vpool if vpool > 0 else None
        scored.append((abs(gap), gap, vgap, name, len(tail)))

    # The control: a random decile of the same trades, over and over, keeping
    # only the largest standardised gap each time - which is what an eye picks
    # out of a table of 28.
    columns = {}
    for _, _, _, name, _ in scored:
        values = [r["f"][name] for r in discovery if name in r["f"]]
        pooled = st.pstdev(values)
        if pooled > 0:
            columns[name] = (values, math.fsum(values), pooled, max(1, len(values) // 10))
    nulls = []
    for _ in range(CONTROLS):
        biggest = 0.0
        for values, total, pooled, k in columns.values():
            picked = math.fsum(rng.sample(values, k))
            rest_mean = (total - picked) / (len(values) - k)
            biggest = max(biggest, abs(picked / k - rest_mean) / pooled)
        nulls.append(biggest)
    nulls.sort()
    floor = nulls[int(0.95 * len(nulls))]
    print(f"    control: a random decile's largest standardised gap over {len(columns)} features")
    print(f"      median {st.median(nulls):.3f}, 95th percentile {floor:.3f}  ({CONTROLS} draws)")
    print(f"\n    {'feature':>22s} {'tail-rest sd':>13s} {'verify':>9s} {'n tail':>7s}  survives")
    for _, gap, vgap, name, n in sorted(scored, reverse=True)[:12]:
        survives = abs(gap) > floor and vgap is not None and gap * vgap > 0 and abs(vgap) > floor
        print(
            f"    {name:>22s} {gap:+13.3f} "
            f"{('%+9.3f' % vgap) if vgap is not None else '        -'} {n:7d}  "
            f"{'YES' if survives else 'no'}"
        )

    print("\n    the strata check on the three largest, within interval and feed class:")
    for _, _, _, name, _ in sorted(scored, reverse=True)[:3]:
        usable = [
            {
                name: r["f"][name],
                "tail": r["_tail"],
                "interval": r["interval"],
                "klass": r["klass"],
            }
            for r in rows
            if name in r["f"]
        ]
        try:
            got = compare(
                usable,
                value=name,
                bucket="tail",
                within=("interval", "klass"),
                min_n=MIN_N,
            )
        except ValueError as exc:
            print(f"    {name}: {exc}")
            continue
        print(f"\n    {name}")
        print(got.render())


# --------------------------------------------------------------------- run


def main() -> None:
    from till_infinity.trading.config import Settings

    settings = Settings.from_env()
    jn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=300.0)
    spread = spreads(jn)
    trades, seen, refused = candidates(jn, settings, gate=True)
    jn.close()
    print("=" * 78)
    print("CONVEXITY: the hold cap, the exit shape, and the one-sided generators")
    print("=" * 78)
    print(f"{seen} published level calls; {len(trades)} pass sweep-aware's rule")
    print(f"  refused {refused}")
    print(f"  {len(GRID)} policies, {len(LADDER)} hold rungs x 3 exits = {COMPARISONS} comparisons")
    print(f"  runway required: {RUNWAY} bars after entry, so every rung is the same trades")

    if LIMIT:
        trades = trades[:: max(1, len(trades) // LIMIT)]
        print(f"  LIMIT set: thinned to {len(trades)} candidates - a smoke test, not a result")
    by_feed = defaultdict(list)
    for t in trades:
        by_feed[t["feed"]].append(t)
    tasks = []
    for feed, part in by_feed.items():
        bps = spread.get(feed, 0.0)
        for i in range(0, len(part), CHUNK):
            tasks.append((feed, bps, part[i : i + CHUNK]))
    tasks.sort(key=lambda z: -len(z[2]))
    print(f"  {len(tasks)} chunks over {len(by_feed)} feeds on {WORKERS} workers\n")

    rows: list[dict] = []
    with mp.Pool(WORKERS, initializer=_init, initargs=(BARS,)) as pool:
        for got in pool.imap_unordered(_run_chunk, tasks, chunksize=1):
            rows.extend(got)
    rows.sort(key=lambda r: r["when"])
    print(f"{len(rows)} trades replayed under every policy and every rung")
    if len(rows) < 4 * MIN_N:
        print("too few to split - stopping rather than reporting an unsplit table")
        return

    edge = int(len(rows) * SPLIT)
    discovery, verify = rows[:edge], rows[edge:]

    print("\n" + "=" * 78)
    print("1. IS THE TAIL BEING CUT OFF BY THE CLOCK")
    print("=" * 78)
    print("  Same trades, same exit rules, only the hold cap moved.")
    ladder_table("pooled", rows)
    ladder_table("verify half", verify)

    print("\n" + "=" * 78)
    print("2. WOULD A DELIBERATELY CONVEX POLICY DO BETTER")
    print("=" * 78)
    grid_table("discovery", discovery)
    grid_table("verify", verify)
    grid_table("pooled", rows)

    print("\n  where each policy's money comes from:")
    for name in GRID:
        concentration("pooled", rows, name)

    print("\n  by entry timeframe, verify half - the Simpson check:")
    for interval in sorted({r["interval"] for r in rows}):
        part = [r for r in verify if r["interval"] == interval]
        if len(part) >= MIN_N:
            grid_table(f"verify {interval}", part)

    print("\n" + "=" * 78)
    print("3. THE CONVEX SIDE OF A ONE-SIDED GENERATOR")
    print("=" * 78)
    print("  Boom grinds down and spikes up; Crash grinds up and spikes down.")
    print("  `other` is every non-synthetic feed and measures the replay's own")
    print("  long bias, which `instruments.md` mistook for a spike effect once.")
    sides("pooled", rows, ("shipping_30", "live_wick_30", "convex", "let_it_run"))
    sides("verify", verify, ("shipping_30", "convex"))

    print("\n" + "=" * 78)
    print("4. WHAT THE TAIL WINNERS HAVE IN COMMON")
    print("=" * 78)
    for policy in ("convex", "shipping_30"):
        tail_features(rows, policy, edge)

    print("\n" + "=" * 78)
    print("Failure conditions declared in the docstring: no verify-half win over")
    print("what ships; a mean that moves without the p95 moving; an advantage that")
    print("dies with the single best trade removed; or `concave` scoring the same,")
    print("which would say only the clock is real.")


if __name__ == "__main__":
    mp.set_start_method("fork", force=True)
    main()
