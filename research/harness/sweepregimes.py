"""Which regimes does `sweep-aware` actually earn in, and which is it blind in?

`sweep-aware` is the best live performer on this book, and it takes every call
`level-scalp` takes except those whose stop sits in front of resting liquidity.
That filter is a statement about **geometry**. It says nothing about whether the
market is trending or ranging, whether volatility is rising or falling, which
session it is, or how far price has already travelled - so the strategy is, in
the plainest sense, trading the same way in every condition.

This asks whether it should be. Not "does it work" - that is already measured -
but **where the work comes from**, so the answer is a gate with a reason rather
than a number that looked good once.

## Why a replay rather than the live record

Its own closes number in the dozens, which cannot separate five regimes at any
confidence worth acting on. The published call stream is 27.7 days and ~197,000
level calls, and `research/harness/exits.py` established the machinery: apply
the strategy's own `accept` rule to each call, walk 1m bars forward under its
own exit, charge the spread. That gives tens of thousands of trades whose R is
computed the same way for every regime.

What it costs is realism. A replay assumes a resting entry is filled when price
touches the level, models no queue position and no slippage beyond the spread,
and `never filled` was 3.9% of live attempts. Those errors are the **same in
every bucket**, which is what makes a comparison between buckets meaningful even
where the absolute R is optimistic. Nothing here should be read as the R this
strategy would have made.

## The discipline, which is most of the work

This project has three recorded occasions where a clean table was mistaken for
a finding, and one where the largest correlation in a 325-pair study was between
two entirely unrelated instruments. So:

* **Split-sample.** The first 60% of the window proposes; the last 40%
  disposes. A regime effect that does not survive the split is not reported as
  one, however large it looks pooled.
* **A control.** The same table computed on shuffled labels, which is what a
  spread of R across buckets looks like when there is nothing to find. A gap
  smaller than the control's is noise with a name.
* **Within-stratum checks.** Simpson's paradox has reversed a pooled figure on
  this project three times - most recently the HTF-alignment result, which was
  worth 2.5-4.1 points at 3m and 5m and nothing pooled. Every headline
  dimension is therefore also cut within `interval`.
* **The count is stated.** Dimensions times buckets is the number of chances
  this had to produce something, and it is printed with the results rather than
  left for the reader to reconstruct.

Usage:
    JOURNAL=~/till_infinity/data/journal.db BARS=~/till_infinity/data/research.db \\
    python3 -m research.harness.sweepregimes
"""

from __future__ import annotations

import bisect
import json
import math
import os
import random
import sqlite3
import statistics as st
from collections import defaultdict

JOURNAL = os.path.expanduser(os.environ.get("JOURNAL", "~/till_infinity/data/journal.db"))
BARS = os.path.expanduser(os.environ.get("BARS", "~/till_infinity/data/research.db"))
#: How long a trade may run, in 1m bars. A day, which is past this desk's holds.
HOLD = int(os.environ.get("HOLD", "1440"))
#: `sweep-aware.entries`.
ENTRIES = ("1m", "3m", "5m", "15m", "30m")
#: Its exit, from the class: target at 6x the modelled push, half a volatility
#: unit of trail, break even once the trade has paid for its own risk.
TARGET_MULT, TRAIL_VOL, PROTECT_R = 6.0, 0.5, 1.0
#: Below this a bucket is not reported. Three hundred R multiples is enough to
#: separate a tenth of an R from nothing; thirty is not.
MIN_BUCKET = int(os.environ.get("MIN_BUCKET", "300"))
#: The discovery/verification split, by time.
SPLIT = float(os.environ.get("SPLIT", "0.6"))
SEED = int(os.environ.get("SEED", "20260911"))


# ------------------------------------------------------------------ loading


def spreads(conn):
    """Median observed spread per feed, in basis points. From `exits.py`."""
    book = defaultdict(list)
    for (ctx,) in conn.execute(
        "SELECT context FROM entries WHERE actor='structures' AND kind='decision'"
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if (
            isinstance(d, dict)
            and isinstance(d.get("spread_bps"), int | float)
            and d["spread_bps"] > 0
        ):
            book[str(d.get("feed") or "")].append(float(d["spread_bps"]))
    return {f: st.median(xs) for f, xs in book.items() if len(xs) >= 5}


def num(d, key, default=0.0):
    got = d.get(key)
    return float(got) if isinstance(got, int | float) else default


def candidates(conn, settings, gate: bool = True):
    """Every published call `sweep-aware.accept` would take, with its context.

    The rule is transcribed from `scalper.SweepAware.accept` rather than
    imported, because `accept` wants a live `Settings` and a payload shaped by
    the service. Any drift between the two makes this harness measure a
    strategy that does not exist, so the three refusal branches are kept in the
    same order and counted - a refusal tally that stops matching the live one is
    the signal that this has gone stale.
    """
    out = []
    refused = defaultdict(int)
    seen = 0
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries WHERE actor='structures' "
        "AND kind='decision' ORDER BY time"
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if not isinstance(d, dict) or not d.get("level"):
            continue
        seen += 1
        if str(d.get("interval")) not in ENTRIES:
            refused["interval"] += 1
            continue
        # `gate=False` takes every published level call instead of the subset
        # `sweep-aware` would accept, for questions about an *instrument* rather
        # than about that strategy.
        swept, swept_n = (num(d, "sweep_rate"), num(d, "sweep_n")) if gate else (0.0, 0.0)
        if swept_n >= settings.sweep_min_history and swept >= settings.sweep_max_rate:
            refused["swept_often"] += 1
            continue
        risk_vol = abs(num(d, "risk_vol"))
        beyond = num(d, "liquidity_beyond_vol") if gate else 0.0
        if beyond > 0 and (risk_vol * 1.0) / beyond >= settings.sweep_max_exposure:
            refused["in_front"] += 1
            continue
        direction = str(d.get("direction") or "")
        if direction not in ("up", "down"):
            refused["no_direction"] += 1
            continue
        level = float(d["level"])
        out.append(
            {
                "when": float(when),
                "feed": str(d.get("feed") or ""),
                "interval": str(d.get("interval")),
                "up": direction == "up",
                "level": level,
                "unit": level * num(d, "vol_bps") / 10_000.0,
                "risk_vol": max(risk_vol, settings.min_stop_vol),
                "push_vol": abs(num(d, "expected_push_vol")),
                "context": d,
            }
        )
    return out, seen, dict(refused)


def bars_for(conn, feed):
    """1m bars for one feed. `research.db` stamps in **milliseconds**.

    The open is carried because a stop is not always filled *at* the stop. If a
    bar opens already through it, the fill is the open - and a replay that books
    the stop price instead is quietly paying itself a price the market never
    offered. That error is invisible in a policy whose stop trails behind price
    and enormous in one that lets the stop move while forbidding it to fire.
    """
    rows = conn.execute(
        "SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval='1m' ORDER BY ts",
        (feed,),
    ).fetchall()
    return (
        [(r[0] / 1000.0, r[1], r[2], r[3], r[4]) for r in rows],
        [r[0] / 1000.0 for r in rows],
    )


# **One `walk`, because two of them diverged and one was wrong.**
#
# This module and `sweepstops` each had their own copy. When `sweepstops` was
# corrected for two look-aheads - a trail raised on a bar's own high and then
# filled on that same bar, and a stop booked at its own price on a bar that
# opened straight through it - this copy kept both. It had also silently started
# reading the *low* as the closing price when the bar tuple grew an open, so
# every hold-expiry exit was priced at the worst tick of the last bar.
#
# The results published from the broken copy - `vol_bps` and `risk_vol` as
# surviving regime dimensions - were withdrawn and re-measured with this one.
#
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
    target_mult = policy.get("target_mult", 6.0)
    target = entry + trade["push_vol"] * target_mult * unit * (1 if up else -1)
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


#: `sweep-aware`'s own exit, as a policy for the shared `walk`.
ITS_OWN_EXIT: dict = {}

#: **Two switches that decompose a regime into a mechanism.**
#
# The two largest surviving dimensions are both suspect as *regimes* and
# obvious as *arithmetic*:
#
# * `risk_vol` high scores better because the trail is a fixed 0.5 volatility
#   units. Against a 1v stop that gives back 0.5R; against a 2v stop, 0.25R.
#   Set `TRAIL_RISK=1` to trail at half the *risk* instead. If the gradient
#   flattens, it was the trail and not the market.
# * `vol_bps` low scores worse because the spread is charged in basis points
#   and R is normalised by risk, so the cost in R is
#   `spread / (risk_vol * vol_bps)` - it grows without bound as volatility
#   falls. Set `NOCOST=1` to charge nothing. If the gradient flattens, this is
#   a *cost* gate ("the spread eats this setup") rather than a regime one
#   ("do not trade quiet markets"), and those want different thresholds.
#
# Both would still be worth acting on. They would just be different actions,
# and naming a cost effect a regime is how a threshold ends up somewhere no
# measurement put it.
NOCOST = os.environ.get("NOCOST") == "1"
TRAIL_RISK = os.environ.get("TRAIL_RISK") == "1"
EXIT_POLICY: dict = {"trail_vol": 0.0, "trail_risk": 0.5} if TRAIL_RISK else ITS_OWN_EXIT


# --------------------------------------------------------------- dimensions


#: Each dimension is `name -> (kind, reader)`. `cut` is split into terciles on
#: the discovery half and those edges are reused on the verification half, which
#: is what makes the second table a test rather than a second fit. `tag` is
#: categorical and buckets itself.
def hour_of(trade):
    import datetime as dt

    return dt.datetime.fromtimestamp(trade["when"], dt.UTC).hour


DIMENSIONS = {
    # What the volatility models see: the current level, and the expected change.
    # `research/forecasting.md` measures these two as near-independent (+0.033),
    # so they are two dimensions rather than one said twice.
    "vol_stretch": ("cut", lambda t: num(t["context"], "vol_stretch")),
    "forecast_ratio": ("cut", lambda t: num(t["context"], "forecast_ratio")),
    "vol_bps": ("cut", lambda t: num(t["context"], "vol_bps")),
    # What the level model thinks of this particular level.
    "edge": ("cut", lambda t: num(t["context"], "edge")),
    "strength": ("cut", lambda t: num(t["context"], "strength")),
    "probability_up": ("cut", lambda t: num(t["context"], "probability_up")),
    # The strategy's own filter dimensions, below the threshold it refuses at.
    # If R rises steadily across these, the threshold is in the wrong place -
    # which is a different and more useful finding than "it works".
    "sweep_rate": ("cut", lambda t: num(t["context"], "sweep_rate")),
    "liquidity_beyond_vol": ("cut", lambda t: num(t["context"], "liquidity_beyond_vol")),
    "risk_vol": ("cut", lambda t: abs(num(t["context"], "risk_vol"))),
    "expected_push_vol": ("cut", lambda t: t["push_vol"]),
    # Where price sits in the structure it is trading inside.
    "range_position": ("cut", lambda t: num(t["context"], "range_position")),
    "range_width_vol": ("cut", lambda t: num(t["context"], "range_width_vol")),
    "origin_distance_vol": ("cut", lambda t: num(t["context"], "origin_distance_vol")),
    "origin_size_vol": ("cut", lambda t: num(t["context"], "origin_size_vol")),
    # Conditions rather than geometry.
    "interval": ("tag", lambda t: t["interval"]),
    "market": ("tag", lambda t: str(t["context"].get("market") or "?")),
    "direction": ("tag", lambda t: "up" if t["up"] else "down"),
    "in_origin": ("tag", lambda t: str(bool(num(t["context"], "in_origin")))),
    "origin_confirmed": ("tag", lambda t: str(bool(num(t["context"], "origin_confirmed")))),
    "confluence": ("tag", lambda t: (str(t["context"].get("confluence") or "none") or "none")[:18]),
    "hour_utc": ("tag", lambda t: f"{hour_of(t):02d}h"),
}


def terciles(values):
    """Two edges, or None when the values do not separate."""
    got = sorted(v for v in values if not math.isnan(v))
    if len(got) < 3 * MIN_BUCKET:
        return None
    lo, hi = got[len(got) // 3], got[2 * len(got) // 3]
    return None if lo >= hi else (lo, hi)


def bucket_of(kind, value, edges):
    if kind == "tag":
        return str(value)
    if edges is None:
        return None
    lo, hi = edges
    return "low" if value < lo else ("high" if value >= hi else "mid")


def table(rows):
    """n, mean R, median, win rate - per bucket."""
    out = {}
    for name, rs in rows.items():
        if len(rs) < MIN_BUCKET:
            continue
        out[name] = (
            len(rs),
            st.fmean(rs),
            st.median(rs),
            sum(1 for r in rs if r > 0) / len(rs),
        )
    return out


def spread_of(got):
    """Best bucket minus worst, in mean R. The size of the claim."""
    if len(got) < 2:
        return 0.0, None, None
    ranked = sorted(got.items(), key=lambda kv: kv[1][1])
    return ranked[-1][1][1] - ranked[0][1][1], ranked[-1][0], ranked[0][0]


# --------------------------------------------------------------------- run


def replay(trades, bars_db, spread):
    """R for every candidate, keeping the context so it can be cut later."""
    conn = sqlite3.connect(f"file:{bars_db}?mode=ro", uri=True, timeout=180.0)
    by_feed = defaultdict(list)
    for t in trades:
        by_feed[t["feed"]].append(t)

    done, missing = [], 0
    for feed, part in sorted(by_feed.items(), key=lambda kv: -len(kv[1])):
        rows, stamps = bars_for(conn, feed)
        if len(rows) < 500:
            missing += len(part)
            continue
        bps = spread.get(feed, 0.0)
        for t in part:
            start = bisect.bisect_left(stamps, t["when"])
            if start >= len(rows) - 10:
                continue
            cost = 0.0 if NOCOST else t["level"] * bps / 10_000.0
            got = walk(rows, start, t, cost, EXIT_POLICY)
            r = got[0] if got is not None else None
            if r is not None:
                t["r"] = r
                done.append(t)
    conn.close()
    return done, missing


def cut_by(trades, kind, read, edges=None):
    """Bucket `trades`, deriving tercile edges when none are supplied."""
    if kind == "cut" and edges is None:
        edges = terciles([read(t) for t in trades])
        if edges is None:
            return None, None
    rows = defaultdict(list)
    for t in trades:
        got = bucket_of(kind, read(t), edges)
        if got is not None:
            rows[got].append(t["r"])
    return table(rows), edges


def show(title, got, order=None):
    print(f"  {title}")
    print(f"    {'bucket':>20s} {'n':>7s} {'mean R':>9s} {'median':>9s} {'win':>7s}")
    for name in order or sorted(got, key=lambda k: -got[k][1]):
        if name not in got:
            continue
        n, mean, med, win = got[name]
        print(f"    {name:>20s} {n:7d} {mean:+9.3f} {med:+9.3f} {win:6.1%}")


def run():  # noqa: PLR0915 - one linear report, splitting it would hide the order
    from till_infinity.trading.config import Settings

    settings = Settings.from_env()
    print(f"journal: {JOURNAL}\nbars:    {BARS}")
    print(f"cost charged: {not NOCOST}   trail scaled to risk: {TRAIL_RISK}\n")
    jn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=300.0)

    spread = spreads(jn)
    trades, seen, refused = candidates(jn, settings)
    jn.close()
    print(f"{seen} published level calls over the journal's span")
    print(f"  {len(trades)} pass sweep-aware's rule; refused {refused}")
    print(f"  spread known for {len(spread)} feeds\n")

    done, missing = replay(trades, BARS, spread)
    if len(done) < 3 * MIN_BUCKET:
        print(f"only {len(done)} replayed - not enough to cut")
        return
    done.sort(key=lambda t: t["when"])
    overall = [t["r"] for t in done]
    print(f"{len(done)} replayed, {missing} skipped for want of bars")
    print(
        f"  pooled: mean {st.fmean(overall):+.3f}R  median {st.median(overall):+.3f}  "
        f"win {sum(1 for r in overall if r > 0) / len(overall):.1%}\n"
    )

    edge = int(len(done) * SPLIT)
    early, late = done[:edge], done[edge:]
    import datetime as dt

    def fmt(when):
        return dt.datetime.fromtimestamp(when, dt.UTC).strftime("%m-%d %H:%M")

    print(f"  discovery {len(early)} trades {fmt(early[0]['when'])}..{fmt(early[-1]['when'])}")
    print(f"  verify    {len(late)} trades {fmt(late[0]['when'])}..{fmt(late[-1]['when'])}\n")

    # The control: what a spread across buckets looks like with nothing to find.
    random.seed(SEED)
    shuffled = [t["r"] for t in done]
    random.shuffle(shuffled)
    fake = defaultdict(list)
    for i, r in enumerate(shuffled):
        fake[f"fake{i % 3}"].append(r)
    control, _, _ = spread_of(table(fake))
    print(
        f"control: three random buckets of the same trades differ by "
        f"{control:.3f}R\n  anything below that is noise with a name.\n"
    )

    print("=" * 78)
    survived, checked = [], 0
    for name, (kind, read) in DIMENSIONS.items():
        got_e, edges = cut_by(early, kind, read)
        if not got_e or len(got_e) < 2:
            continue
        got_l, _ = cut_by(late, kind, read, edges)
        if not got_l or len(got_l) < 2:
            continue
        checked += len(got_e)
        gap_e, best_e, worst_e = spread_of(got_e)
        gap_l, best_l, worst_l = spread_of(got_l)
        # The ordering has to survive, not merely the size. A dimension whose
        # best bucket becomes its worst is the shape of an overfit split.
        held = best_e == best_l and worst_e == worst_l
        print(f"\n{name}  (edges {edges})")
        order = sorted(got_e, key=lambda k: -got_e[k][1])
        show("discovery", got_e, order)
        show("verify", got_l, order)
        if held and gap_l > control:
            mark = "HELD"
        else:
            mark = "ordering held, gap small" if held else "did not hold"
        print(f"    gap {gap_e:.3f}R -> {gap_l:.3f}R   best={best_e}  worst={worst_e}   [{mark}]")
        if held and gap_l > control:
            survived.append((name, gap_l, best_e, worst_e))

    print("\n" + "=" * 78)
    print(f"\n{checked} bucket-comparisons over {len(DIMENSIONS)} dimensions.")
    print(f"Control gap {control:.3f}R.\n")
    if not survived:
        print("Nothing survived the split with a gap above the control.")
        print("That is the honest answer to 'which regimes work': on this")
        print("evidence, none separates - the strategy is not blind, it is flat.")
        return
    print("Survived the split with an ordering that held and a gap above control:\n")
    print(f"  {'dimension':>22s} {'gap R':>8s} {'best':>16s} {'worst':>16s}")
    for name, gap, best, worst in sorted(survived, key=lambda s: -s[1]):
        print(f"  {name:>22s} {gap:8.3f} {best:>16s} {worst:>16s}")
    print("\nSimpson's check: the same dimensions cut within each interval.")
    print("A pooled effect that vanishes here is a mix of feeds, not a regime.\n")
    for name, _gap, _b, _w in sorted(survived, key=lambda s: -s[1])[:4]:
        kind, read = DIMENSIONS[name]
        print(f"\n{name} within interval:")
        for interval in ENTRIES:
            part = [t for t in done if t["interval"] == interval]
            if len(part) < 3 * MIN_BUCKET:
                continue
            got, _ = cut_by(part, kind, read)
            if not got or len(got) < 2:
                continue
            gap, best, worst = spread_of(got)
            n = sum(v[0] for v in got.values())
            print(f"  {interval:>4s} {n:7d} trades   gap {gap:6.3f}R   best={best} worst={worst}")


if __name__ == "__main__":
    run()
