"""Structural edges between venues, between instruments, and against a definition.

`research/structure.py` is the level set's shape and is unrelated; this is the
*cross* study - cross-venue, cross-rate, cross-instrument - so it is named for
the thing all three have in common, which is that every one of them ends at a
spread that has to be crossed.

## What is asked, and what would count as failure

Four questions, each with the number that kills it stated before the run.

**1. Does a venue's deviation from consensus revert, and can that be traded?**
`structures` publishes `dev_bps` - one venue's mid against the median of the
others, leaving itself out. Failure: the reversion is no larger than a
permutation of the same sample; or the reverted amount is smaller than the
deviating venue's own spread; or - the one that kills it whatever the numbers
say - the deviating venue is one the desk cannot trade, since a relative
quantity needs both legs.

**2. Does the triangular residual in FX ever exceed all three spreads?**
`eurjpy` and `eurusd x usdjpy` are the same thing. Failure: the executable
residual - synthetic bid against direct ask and the reverse, built from real
bid/ask - is never positive, or is positive only when a leg is stale.

**3. Do related instruments lead each other on a seconds scale?**
Failure: the cross-correlation peak away from lag zero is no larger on related
pairs than on unrelated ones, or the move it implies is below the spread.

**4. Do the Volatility indices realise the volatility they are named for?**
Failure: they do, to within the split-sample spread of the estimate.

## The clock, established first because everything else depends on it

Two clocks in this repository, and they are not the same clock.

* **`research.db.ticks`** carries MT5's `time_msc` - the broker's own tick
  time, read from the bridge by `mt5fill.py`. Every one of the 53 feeds is
  stamped by the **same** server, so a lead-lag measured inside this table is a
  lead-lag between instruments and not between collectors. Questions 2, 3 and 4
  live here.

* **`journal.db`** carries `dev_bps` computed by `structures/features.py`, whose
  `now` is the `time` field of a `prices.quotes` message. For every TradingView
  venue that field is set by `parse_quote(..., now=time.time())` - **our receive
  time**, not the venue's. `lp_time` is requested in `QUOTE_FIELDS` and then
  never read by `parse_quote`. So for the consensus venues:

      staleness  = seconds since *we* last saw that venue's price change
      dev_bps    = this venue's mid against others' mids as *we* last had them

  A lead-lag across venues is therefore not measurable from what is stored - it
  would be the websocket's delivery order. Question 1 is asked only as a level
  comparison, and its horizons start at 5s so that an unknown sub-second offset
  between the two clocks cannot carry the answer.

Only the broker source keeps a venue's own stamp (`quotes.py` line 595 keeps
the bridge's tick time deliberately), which is the other half of why questions
2-4 are asked of the tick table and question 1 is not.
"""

from __future__ import annotations

import math
import os
import random
import sqlite3
import statistics
import time
from collections import Counter, defaultdict

import numpy as np

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
RESEARCH = os.environ.get("RESEARCH_DB", os.path.join(DATA, "research.db"))
JOURNAL = os.environ.get("JOURNAL_DB", os.path.join(DATA, "journal.db"))
SEED = int(os.environ.get("SEED", "20260911"))
PARTS = os.environ.get("PARTS", "1234")

COMPARISONS: Counter[str] = Counter()


def bump(name: str, n: int = 1) -> None:
    COMPARISONS[name] += n


def head(text: str) -> None:
    print(f"\n\n{'=' * 78}\n{text}\n{'=' * 78}", flush=True)


def sub(text: str) -> None:
    print(f"\n--- {text} ---", flush=True)


def q(values, *fractions):
    """Quantiles without importing a stats package for it."""
    if not len(values):
        return [float("nan")] * len(fractions)
    a = np.sort(np.asarray(values, dtype=float))
    return [float(a[min(len(a) - 1, int(len(a) * f))]) for f in fractions]


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

FX = [
    "eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "usdchf", "nzdusd",
    "eurgbp", "eurjpy", "gbpjpy", "eurchf", "audjpy", "chfjpy", "euraud",
    "cadjpy",
]


def load_ticks(feeds: list[str]) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """(ts_ms, bid, ask) per feed, sorted, bid<ask enforced."""
    conn = sqlite3.connect(f"file:{RESEARCH}?mode=ro", uri=True)
    out = {}
    for feed in feeds:
        rows = conn.execute(
            "SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts", (feed,)
        ).fetchall()
        if not rows:
            continue
        a = np.array(rows, dtype=float)
        ts, bid, ask = a[:, 0].astype(np.int64), a[:, 1], a[:, 2]
        ok = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask >= bid)
        out[feed] = (ts[ok], bid[ok], ask[ok])
    conn.close()
    return out


def last_at(ts: np.ndarray, when: np.ndarray) -> np.ndarray:
    """Index of the last tick at or before each `when`; -1 where none."""
    return np.searchsorted(ts, when, side="right") - 1


# --------------------------------------------------------------------------
# 0. The clock, measured rather than asserted
# --------------------------------------------------------------------------


def part_clock(ticks) -> None:
    head("0. WHAT EACH TIMESTAMP MEANS")
    print(
        "research.db.ticks = MT5 time_msc, the broker's own tick clock, one\n"
        "server for all feeds. journal.db dev_bps = our receive clock (see the\n"
        "module docstring; parse_quote discards lp_time).\n"
    )
    print(f"{'feed':10s} {'ticks':>8s} {'median gap ms':>14s} {'p95 gap ms':>11s} "
          f"{'median spread bps':>18s} {'ms-resolution?':>15s}")
    for feed in sorted(ticks):
        ts, bid, ask = ticks[feed]
        gaps = np.diff(ts)
        mid = (bid + ask) / 2.0
        spread_bps = (ask - bid) / mid * 10_000.0
        # A clock that is really milliseconds has ts % 1000 spread out; one that
        # is seconds rounded up has every tick on a round second.
        sub_ms = float(np.mean((ts % 1000) != 0))
        print(f"{feed:10s} {len(ts):8d} {np.median(gaps):14.0f} "
              f"{np.quantile(gaps, 0.95):11.0f} {np.median(spread_bps):18.3f} "
              f"{sub_ms:14.1%}")


# --------------------------------------------------------------------------
# 1. Consensus deviation
# --------------------------------------------------------------------------

HORIZONS = [(0, 5), (5, 15), (15, 60), (60, 300), (300, 900)]


def journal_devs() -> list[dict]:
    import json

    conn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True)
    rows = []
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries "
        "WHERE kind='decision' AND context LIKE '%dev_bps%' ORDER BY time"
    ):
        d = json.loads(ctx)
        if not d.get("venue") or not d.get("feed"):
            continue
        rows.append(
            {
                "t": float(when),
                "feed": d["feed"],
                "venue": d["venue"],
                "shape": d.get("shape", ""),
                "dev": float(d.get("dev_bps", 0.0)),
                "spread_bps": float(d.get("spread_bps", 0.0)),
                "staleness": float(d.get("staleness", 0.0)),
                "venues": float(d.get("venues", 0.0)),
            }
        )
    conn.close()
    return rows


def winsorise(x, y, p=0.01):
    """Clip both series to their central 98%.

    `dev_bps` has a tail that reaches thousands of basis points - a venue
    quoting a different contract, or a decimal - and an OLS slope on that is
    one observation's slope. The first run of this harness reported
    `beta=-0.000 +- 0.000` with a permutation interval of zero width, which is
    the dead-column signature `research/README.md` warns about. It was this.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    lo, hi = np.quantile(x, p), np.quantile(x, 1 - p)
    keep = (x >= lo) & (x <= hi)
    lo2, hi2 = np.quantile(y, p), np.quantile(y, 1 - p)
    keep &= (y >= lo2) & (y <= hi2)
    return x[keep], y[keep], keep


def slope(x, y) -> tuple[float, float]:
    """OLS slope and its standard error."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if len(x) < 8 or x.std() == 0:
        return float("nan"), float("nan")
    b = float(np.cov(x, y, bias=True)[0, 1] / x.var())
    a = float(y.mean() - b * x.mean())
    resid = y - (a + b * x)
    se = float(math.sqrt(resid.var(ddof=2) / (len(x) * x.var())))
    return b, se


def part_deviation(rng: random.Random) -> None:
    head("1. DOES A VENUE'S DEVIATION FROM CONSENSUS REVERT?")
    rows = journal_devs()
    print(f"{len(rows):,} decisions carrying dev_bps and a venue, "
          f"{len({(r['feed'], r['venue']) for r in rows})} (feed, venue) pairs")
    print("Timestamps are our receive clock. Horizons start at 5s for that reason.\n")

    by_pair: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by_pair[(r["feed"], r["venue"])].append(r)

    # Pair each observation with the next observation of the SAME (feed, venue).
    pairs = []
    for key, seq in by_pair.items():
        seq.sort(key=lambda r: r["t"])
        for a, b in zip(seq, seq[1:]):
            gap = b["t"] - a["t"]
            if gap <= 0 or gap > 900:
                continue
            pairs.append((a, b, gap))
    print(f"{len(pairs):,} consecutive same-pair observations within 900s\n")

    sub("The sample is anomaly-triggered, so a permutation control is mandatory")
    print(
        "Both endpoints are anomalies. Regression to the mean is guaranteed by\n"
        "that alone. The control shuffles the *second* element within each\n"
        "(feed, venue), which keeps every marginal and destroys the time order.\n"
    )

    def table(subset, label):
        if len(subset) < 30:
            print(f"{label:28s} n={len(subset):5d}  (too few)")
            return
        x0 = np.array([a["dev"] for a, _, _ in subset])
        y0 = np.array([b["dev"] for _, b, _ in subset])
        x, y, keep = winsorise(x0, y0)
        if len(x) < 30:
            print(f"{label:28s} n={len(x):5d}  (too few after winsorising)")
            return
        b_obs, se = slope(x, y - x)
        # Permutation control, within (feed, venue).
        groups: dict[tuple[str, str], list[int]] = defaultdict(list)
        for i, (a, _, _) in enumerate([s for s, k in zip(subset, keep) if k]):
            groups[(a["feed"], a["venue"])].append(i)
        perms = []
        for _ in range(200):
            yp = y.copy()
            for idx in groups.values():
                if len(idx) > 1:
                    shuffled = idx[:]
                    rng.shuffle(shuffled)
                    yp[idx] = y[shuffled]
            perms.append(slope(x, yp - x)[0])
        bump("deviation-cells")
        lo, hi = float(np.quantile(perms, 0.025)), float(np.quantile(perms, 0.975))
        closed = float(np.median(np.abs(x) - np.abs(y)))
        spread = float(np.median([a["spread_bps"] for s, k in zip(subset, keep) if k
                                  for a in (s[0],)]))
        verdict = "inside control" if lo <= b_obs <= hi else (
            "MORE reversion" if b_obs < lo else "LESS reversion")
        print(f"{label:28s} n={len(x):5d}  beta={b_obs:+.3f}+-{se:.3f}  "
              f"perm[{lo:+.3f},{hi:+.3f}]  {verdict:14s} "
              f"closed={closed:+.3f}bps  spread={spread:.3f}bps")

    sub("beta of (dev_next - dev_now) on dev_now: -1 is full reversion, 0 a random walk")
    for lo, hi in HORIZONS:
        cut = [p for p in pairs if lo < p[2] <= hi]
        table(cut, f"all, {lo}-{hi}s")

    sub("By shape at the first observation")
    for shape in ("stale", "dislocation", "spread"):
        for lo, hi in ((5, 60), (60, 300)):
            cut = [p for p in pairs if p[0]["shape"] == shape and lo < p[2] <= hi]
            table(cut, f"{shape}, {lo}-{hi}s")

    sub("Stale against fresh: a stale venue's deviation should revert mechanically")
    for lo, hi in ((5, 60), (60, 300)):
        for name, keep in (
            ("staleness < 5s", lambda r: r["staleness"] < 5),
            ("staleness 5-20s", lambda r: 5 <= r["staleness"] < 20),
            ("staleness >= 20s", lambda r: r["staleness"] >= 20),
        ):
            cut = [p for p in pairs if keep(p[0]) and lo < p[2] <= hi]
            table(cut, f"{name}, {lo}-{hi}s")

    sub("Which venue is deviating, and can the desk trade it")
    counts = Counter(r["venue"] for r in rows)
    total = sum(counts.values())
    for venue, n in counts.most_common():
        tradeable = "yes - this is our broker" if venue == "DERIV" else "no"
        print(f"{venue:14s} {n:7d}  {n / total:6.1%}   tradeable: {tradeable}")

    sub("DERIV alone, which is the only leg of this the desk could hold")
    for lo, hi in HORIZONS:
        cut = [p for p in pairs if p[0]["venue"] == "DERIV" and lo < p[2] <= hi]
        table(cut, f"DERIV, {lo}-{hi}s")

    return rows


# --------------------------------------------------------------------------
# 1b. Does the *broker's own price* move when DERIV deviates?
# --------------------------------------------------------------------------


def part_broker_reaction(rows, ticks, rng: random.Random) -> None:
    head("1b. WHEN A VENUE DEVIATES, DOES THE PRICE WE CAN TRADE MOVE BACK?")
    print(
        "Part 1 measures a relative quantity. Trading it needs both legs, and\n"
        "the desk holds one. So: take the deviation as a signal and ask what the\n"
        "broker's own mid - the only price we can fill against - did next.\n"
        "Control is reacting.md's: the same feed, the same sign, a random moment\n"
        "in the same window.\n"
    )
    horizons = (5, 15, 60, 300)
    lo_ms = min(int(ts[0]) for ts, _, _ in ticks.values())
    hi_ms = max(int(ts[-1]) for ts, _, _ in ticks.values())

    def move_bps(feed, t0_ms, secs):
        ts, bid, ask = ticks[feed]
        i = last_at(ts, np.array([t0_ms]))[0]
        j = last_at(ts, np.array([t0_ms + secs * 1000]))[0]
        if i < 0 or j < 0 or j <= i:
            return None
        m0 = (bid[i] + ask[i]) / 2.0
        m1 = (bid[j] + ask[j]) / 2.0
        return (m1 / m0 - 1.0) * 10_000.0

    for venue in ("DERIV", "OANDA", "FOREXCOM", "PEPPERSTONE", "SAXO", "CAPITALCOM"):
        cut = [
            r for r in rows
            if r["venue"] == venue and r["feed"] in ticks
            and lo_ms <= r["t"] * 1000 <= hi_ms - 900_000
            and abs(r["dev"]) > 0.0
        ]
        if len(cut) < 40:
            print(f"{venue:12s} n={len(cut)}  (too few inside the tick window)")
            continue
        # Sign convention differs by who is deviating, and getting it wrong
        # would answer the opposite question. DERIV *is* our broker, so its
        # deviation is a reversion signal: dev<0 means our price is below the
        # others and the trade is long. Any other venue deviating is a
        # follow-the-leader signal: dev>0 means somebody else is high and the
        # trade is long.
        follow = venue != "DERIV"
        print(f"\n{venue:12s} n={len(cut)}  "
              f"median |dev| {statistics.median(abs(r['dev']) for r in cut):.3f}bps  "
              f"({'follow the deviating venue' if follow else 'revert to consensus'})")
        print(f"  {'horizon':>8s} {'signal bps':>11s} {'control bps':>12s} "
              f"{'edge':>8s} {'spread':>8s} {'net':>8s}")
        for secs in horizons:
            got, ctl = [], []
            for r in cut:
                lean = 1.0 if r["dev"] > 0 else -1.0
                direction = lean if follow else -lean
                m = move_bps(r["feed"], int(r["t"] * 1000), secs)
                if m is not None:
                    got.append(direction * m)
                for _ in range(3):
                    t = rng.uniform(lo_ms, hi_ms - secs * 1000)
                    mc = move_bps(r["feed"], int(t), secs)
                    if mc is not None:
                        ctl.append(direction * mc)
            if len(got) < 30:
                continue
            ts_, bid_, ask_ = ticks[cut[0]["feed"]]
            spreads = []
            for r in cut:
                t_, b_, a_ = ticks[r["feed"]]
                i = last_at(t_, np.array([int(r["t"] * 1000)]))[0]
                if i >= 0:
                    spreads.append((a_[i] - b_[i]) / ((a_[i] + b_[i]) / 2) * 10_000)
            sp = float(np.median(spreads)) if spreads else float("nan")
            e = float(np.mean(got)) - float(np.mean(ctl))
            bump("broker-reaction-cells")
            print(f"  {secs:7d}s {np.mean(got):11.3f} {np.mean(ctl):12.3f} "
                  f"{e:8.3f} {sp:8.3f} {e - sp:8.3f}")


# --------------------------------------------------------------------------
# 2. Triangular residual
# --------------------------------------------------------------------------

#: (direct, leg A, leg B, how) where how is 'mul' for direct = A*B and
#: 'div' for direct = A/B.  ask_direct_synth = ask_A*ask_B  |  ask_A/bid_B.
TRIANGLES = [
    ("eurjpy", "eurusd", "usdjpy", "mul"),
    ("gbpjpy", "gbpusd", "usdjpy", "mul"),
    ("audjpy", "audusd", "usdjpy", "mul"),
    ("eurchf", "eurusd", "usdchf", "mul"),
    ("cadjpy", "usdjpy", "usdcad", "div"),
    ("chfjpy", "usdjpy", "usdchf", "div"),
    ("eurgbp", "eurusd", "gbpusd", "div"),
    ("euraud", "eurusd", "audusd", "div"),
]

STALE_BUCKETS = [(0, 100), (0, 250), (0, 1000), (0, 5000), (0, 10**12)]


def triangle_frame(ticks, direct, a, b, how, shift_ms=0):
    """Executable residuals at every tick of any of the three legs."""
    if direct not in ticks or a not in ticks or b not in ticks:
        return None
    td, bd, ad = ticks[direct]
    ta, ba, aa = ticks[a]
    tb, bb, ab = ticks[b]
    if shift_ms:
        tb = tb + shift_ms
    when = np.unique(np.concatenate([td, ta, tb]))
    id_, ia, ib = last_at(td, when), last_at(ta, when), last_at(tb, when)
    ok = (id_ >= 0) & (ia >= 0) & (ib >= 0)
    when, id_, ia, ib = when[ok], id_[ok], ia[ok], ib[ok]
    if not len(when):
        return None
    stale = np.maximum.reduce([when - td[id_], when - ta[ia], when - tb[ib]])

    if how == "mul":
        synth_bid = ba[ia] * bb[ib]
        synth_ask = aa[ia] * ab[ib]
    else:
        synth_bid = ba[ia] / ab[ib]
        synth_ask = aa[ia] / bb[ib]

    dir_bid, dir_ask = bd[id_], ad[id_]
    dir_mid = (dir_bid + dir_ask) / 2.0
    synth_mid = (synth_bid + synth_ask) / 2.0

    resid_bps = (dir_mid / synth_mid - 1.0) * 10_000.0
    # Both directions, in bps of the direct mid. Positive is a free lunch.
    sell_direct = (dir_bid - synth_ask) / dir_mid * 10_000.0
    buy_direct = (synth_bid - dir_ask) / dir_mid * 10_000.0
    cost = (
        (dir_ask - dir_bid) / dir_mid
        + (aa[ia] - ba[ia]) / ((aa[ia] + ba[ia]) / 2)
        + (ab[ib] - bb[ib]) / ((ab[ib] + bb[ib]) / 2)
    ) * 10_000.0
    return when, stale, resid_bps, sell_direct, buy_direct, cost


def part_triangles(ticks) -> None:
    head("2. THE TRIANGULAR RESIDUAL IN FX")
    print(
        "All three legs come from one broker on one clock, so the only\n"
        "synchrony problem left is that legs tick at different times - which is\n"
        "why every row is also cut by the staleness of the *stalest* leg.\n"
        "'free lunch' means the executable residual is positive after paying\n"
        "bid/ask on all three legs: it is an arbitrage, not a tendency.\n"
    )
    for direct, a, b, how in TRIANGLES:
        frame = triangle_frame(ticks, direct, a, b, how)
        if frame is None:
            print(f"{direct}: missing a leg")
            continue
        when, stale, resid, sell, buy, cost = frame
        sign = "x" if how == "mul" else "/"
        sub(f"{direct}  =  {a} {sign} {b}     ({len(when):,} observation points)")
        print(f"  {'max leg stale':>14s} {'n':>9s} {'|resid| p50':>12s} "
              f"{'p99':>8s} {'p99.9':>8s} {'max':>9s} {'3-leg cost p50':>15s} "
              f"{'free lunches':>13s}")
        for lo, hi in STALE_BUCKETS:
            m = (stale >= lo) & (stale < hi)
            n = int(m.sum())
            if n < 100:
                print(f"  {f'<{hi}ms':>14s} {n:>9d}   (too few)")
                continue
            best = np.maximum(sell[m], buy[m])
            wins = int((best > 0).sum())
            bump("triangle-cells")
            p50, p99, p999 = q(np.abs(resid[m]), 0.5, 0.99, 0.999)
            label = "any" if hi > 10**11 else f"<{hi}ms"
            print(f"  {label:>14s} {n:>9d} {p50:12.3f} {p99:8.3f} {p999:8.3f} "
                  f"{np.abs(resid[m]).max():9.3f} {np.median(cost[m]):15.3f} "
                  f"{wins:6d} {wins / n:6.3%}")

        # Signed, because the sign is the whole diagnosis. A residual that
        # changes sign is a dislocation; one that does not is the broker
        # quoting this cross off its own cross, and the two want opposite
        # write-ups.
        fresh = stale < 250
        if fresh.sum() > 500:
            r = resid[fresh]
            locked = np.maximum(sell[fresh], buy[fresh])
            half = cost[fresh] / 2.0
            bump("triangle-sign-checks")
            print(f"  signed: mean {r.mean():+.3f}  median {np.median(r):+.3f}  "
                  f"frac>0 {float((r > 0).mean()):.1%}  "
                  f"|mean|/p50|resid| {abs(r.mean()) / max(np.median(np.abs(r)), 1e-9):.2f}")
            print(f"  locked arb (hold both legs, cross once): p50 {np.median(locked):+.4f}bps  "
                  f"p99 {q(locked, 0.99)[0]:+.4f}  frac>0 {float((locked > 0).mean()):.2%}")
            print(f"  round trip (cross twice, unwind at zero): p50 "
                  f"{np.median(np.abs(r) - cost[fresh]):+.4f}bps  "
                  f"frac>0 {float((np.abs(r) - cost[fresh] > 0).mean()):.2%}")
            # Hour by hour: a constant offset is a convention, an episodic one
            # is an event.
            # Carry is a level, so take it out and ask what is left. The day's
            # own median residual is subtracted; what remains is the part that
            # is a dislocation rather than a value date.
            day_med = np.median(resid[fresh])
            flat = resid[fresh] - day_med
            locked_flat = np.abs(flat) - half
            bump("carry-removed-checks")
            print(f"  carry removed (minus the window median {day_med:+.3f}bps): "
                  f"|resid| p50 {np.median(np.abs(flat)):.4f}  p99 "
                  f"{q(np.abs(flat), 0.99)[0]:.4f}  vs half-cost "
                  f"{np.median(half):.4f}  locked>0 "
                  f"{float((locked_flat > 0).mean()):.3%}")
            hours = ((when[fresh] // 3_600_000) % 24).astype(int)
            line = []
            for h in range(24):
                m = hours == h
                line.append(f"{np.median(r[m]):+.2f}" if m.sum() > 200 else "  . ")
            print("  by UTC hour (the window straddles two dates, so this dial\n        folds them together - see 2b for the day-by-day form):\n    " + " ".join(line))

        # Control: one leg taken from a minute later. Keeps every marginal,
        # destroys the synchrony. If the true residual is not much smaller than
        # this, the triangle is not actually tight and the measurement is noise.
        ctl = triangle_frame(ticks, direct, a, b, how, shift_ms=60_000)
        if ctl is not None:
            _, cstale, cresid, csell, cbuy, _ = ctl
            m = cstale < 1000
            t = stale < 1000
            if m.sum() > 100 and t.sum() > 100:
                bump("triangle-controls")
                cbest = np.maximum(csell[m], cbuy[m])
                print(f"  control (one leg +60s, <1000ms): |resid| p50 "
                      f"{q(np.abs(cresid[m]), 0.5)[0]:.3f}bps against "
                      f"{q(np.abs(resid[t]), 0.5)[0]:.3f} true, free lunches "
                      f"{float((cbest > 0).mean()):.3%}")

        # Offset scan. If the residual is smallest at a non-zero shift of the
        # direct leg, the two series are not on the same clock after all and
        # the whole triangle is a latency measurement wearing an arbitrage.
        scan = []
        for shift in (-2000, -1000, -500, -250, 0, 250, 500, 1000, 2000):
            f2 = triangle_frame(ticks, direct, a, b, how, shift_ms=-shift)
            if f2 is None:
                continue
            _, s2, r2, _, _, _ = f2
            m2 = s2 < 250
            if m2.sum() > 500:
                scan.append((shift, float(np.median(np.abs(r2[m2])))))
                bump("triangle-offset-scans")
        if scan:
            best = min(scan, key=lambda p: p[1])
            print("  offset scan (direct leg shifted, median |resid| bps): "
                  + "  ".join(f"{s:+5d}ms {v:.3f}" for s, v in scan))
            print(f"  minimum at {best[0]:+d}ms"
                  + ("  <- aligned" if best[0] == 0 else "  <- NOT aligned"))


# --------------------------------------------------------------------------
# 2b. The same residual over sixty days of bars
# --------------------------------------------------------------------------


def part_triangles_long(ticks) -> None:
    head("2b. THE SAME RESIDUAL OVER SIXTY DAYS, FROM 1m BARS")
    print(
        "The tick table is one day. A one-signed residual on one day is a\n"
        "Tuesday; the question is whether it is a fact about the instrument.\n"
        "1m closes have no bid/ask, so this is mid against mid and says nothing\n"
        "about cost - it is only asked to find out whether the sign holds.\n"
    )
    conn = sqlite3.connect(f"file:{RESEARCH}?mode=ro", uri=True)
    series = {}
    for feed in sorted({f for tri in TRIANGLES for f in tri[:3]}):
        rows = conn.execute(
            "SELECT ts, close FROM bars WHERE feed=? AND interval='1m' ORDER BY ts", (feed,)
        ).fetchall()
        if rows:
            a = np.array(rows, dtype=float)
            series[feed] = (a[:, 0].astype(np.int64), a[:, 1])
    conn.close()

    # MT5 bars are built from the **bid**, and the tick table says what each
    # leg's spread is. A bid-built residual therefore has an arithmetic offset
    # from a mid-built one that involves nobody's opinion about anything:
    #
    #   direct = A x B :  resid_bid - resid_mid = (sA + sB - sD) / 2
    #   direct = A / B :  resid_bid - resid_mid = (sA - sB - sD) / 2
    #
    # That is a prediction, made from a different table, with no free
    # parameters. If the sixty-day offsets match it, the whole column is a
    # quoting convention and there is nothing here. Whatever does *not* match
    # is the only thing in this section worth reading.
    spread_bps = {}
    for feed, (_, bid, ask) in ticks.items():
        spread_bps[feed] = float(np.median((ask - bid) / ((ask + bid) / 2) * 10_000))

    print(f"  {'triangle':30s} {'bars':>8s} {'median bps':>11s} {'predicted':>10s} "
          f"{'residual':>9s} {'frac>0':>8s} {'days>0':>10s} {'p5':>8s} {'p95':>8s}")
    for direct, a, b, how in TRIANGLES:
        if not all(f in series for f in (direct, a, b)):
            continue
        td, cd = series[direct]
        ta, ca = series[a]
        tb, cb = series[b]
        when = np.intersect1d(np.intersect1d(td, ta), tb)
        if len(when) < 1000:
            continue
        d = cd[np.searchsorted(td, when)]
        x = ca[np.searchsorted(ta, when)]
        y = cb[np.searchsorted(tb, when)]
        synth = x * y if how == "mul" else x / y
        r = (d / synth - 1.0) * 10_000.0
        r = r[np.isfinite(r)]
        days = when // 86_400_000
        per_day = []
        for day in np.unique(days):
            m = days == day
            if m.sum() > 100:
                per_day.append(float(np.median((cd[np.searchsorted(td, when)][m]
                                                / synth[m] - 1.0) * 10_000.0)))
        bump("long-triangles")
        up = sum(1 for v in per_day if v > 0)
        p5, p95 = q(r, 0.05, 0.95)
        sign = "x" if how == "mul" else "/"
        sa, sb, sd = spread_bps.get(a), spread_bps.get(b), spread_bps.get(direct)
        if None in (sa, sb, sd):
            pred = float("nan")
        else:
            pred = ((sa + sb - sd) if how == "mul" else (sa - sb - sd)) / 2.0
        print(f"  {f'{direct} = {a} {sign} {b}':30s} {len(r):8d} {np.median(r):11.3f} "
              f"{pred:10.3f} {np.median(r) - pred:9.3f} {float((r > 0).mean()):8.1%} "
              f"{f'{up}/{len(per_day)}':>10s} {p5:8.3f} {p95:8.3f}")

    sub("By weekday. A spot cross settles T+2, so rolling Wed->Thu moves the "
        "value\n    date three days instead of one. If the residual is carry, "
        "Thursday is where\n    it shows, and it shows on every triangle at once")
    print(f"  {'triangle':30s} " + " ".join(f"{d:>8s}" for d in
          ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")) + "   Thu/other")
    for direct, a, b, how in TRIANGLES:
        if not all(f in series for f in (direct, a, b)):
            continue
        td, cd = series[direct]
        ta, ca = series[a]
        tb, cb = series[b]
        when = np.intersect1d(np.intersect1d(td, ta), tb)
        d = cd[np.searchsorted(td, when)]
        x = ca[np.searchsorted(ta, when)]
        y = cb[np.searchsorted(tb, when)]
        synth = x * y if how == "mul" else x / y
        r = (d / synth - 1.0) * 10_000.0
        # 1970-01-01 was a Thursday. Indexing Monday as 0 puts Thursday at 3,
        # so epoch day 0 must map to 3.
        dow = ((when // 86_400_000) + 3) % 7
        cells, other = [], []
        for k in range(7):
            m = (dow == k) & np.isfinite(r)
            v = float(np.median(r[m])) if m.sum() > 200 else float("nan")
            cells.append(v)
            if k != 3 and m.sum() > 200:
                other.append(v)
        ratio = (cells[3] / statistics.median(other)) if other and statistics.median(other) else float("nan")
        bump("weekday-triangles")
        print(f"  {direct:30s} " + " ".join(
            "     .  " if v != v else f"{v:+8.3f}" for v in cells) + f"   {ratio:7.2f}x")

    sub("cadjpy day by day - is the offset a level or an event")
    direct, a, b, how = "cadjpy", "usdjpy", "usdcad", "div"
    if all(f in series for f in (direct, a, b)):
        td, cd = series[direct]
        ta, ca = series[a]
        tb, cb = series[b]
        when = np.intersect1d(np.intersect1d(td, ta), tb)
        d = cd[np.searchsorted(td, when)]
        synth = ca[np.searchsorted(ta, when)] / cb[np.searchsorted(tb, when)]
        r = (d / synth - 1.0) * 10_000.0
        days = when // 86_400_000
        rows = []
        for day in np.unique(days):
            m = (days == day) & np.isfinite(r)
            if m.sum() > 100:
                rows.append((time.strftime("%m-%d", time.gmtime(day * 86_400)),
                             int(m.sum()), float(np.median(r[m])),
                             float(np.median(np.abs(r[m]))), float((r[m] > 0).mean())))
        print("   date    bars   median bps   |median|   frac>0")
        for date, n, med, amed, frac in rows:
            print(f"  {date}  {n:5d}   {med:+9.3f}   {amed:8.3f}   {frac:6.1%}")


# --------------------------------------------------------------------------
# 3. Lead-lag between related instruments
# --------------------------------------------------------------------------

RELATED = [
    ("us100", "us30"),
    ("ger40", "fra40"),
    ("ger40", "uk100"),
    ("fra40", "uk100"),
    ("gold", "silver"),
    ("btc", "eth"),
    ("eurusd", "gbpusd"),
    ("usdjpy", "eurjpy"),
]
UNRELATED = [
    ("us100", "gold"),
    ("us30", "btc"),
    ("ger40", "gold"),
    ("us100", "volatility_75_index"),
    ("btc", "gbpusd"),
    ("gold", "uk100"),
    ("eurusd", "step_index"),
    ("silver", "boom_500_index"),
]


def second_grid(ticks, feed, lo_s, hi_s):
    ts, bid, ask = ticks[feed]
    grid = np.arange(lo_s, hi_s, dtype=np.int64)
    idx = last_at(ts, grid * 1000)
    mid = np.where(idx >= 0, (bid[np.maximum(idx, 0)] + ask[np.maximum(idx, 0)]) / 2.0, np.nan)
    fresh = np.where(idx >= 0, grid * 1000 - ts[np.maximum(idx, 0)], 10**9)
    return mid, fresh


def part_leadlag(ticks, maxlag=10) -> None:
    head("3. DOES ONE INSTRUMENT LEAD ANOTHER AT SECONDS SCALE?")
    print(
        "One broker, one clock, so a lead here is between instruments rather\n"
        "than between collectors. 1s log returns, a quote required within 5s on\n"
        "both sides, lags +-10s. generated.md is the reason the unrelated pairs\n"
        "are run with the identical statistic: the largest correlation in a\n"
        "325-pair study there was between two instruments with nothing in\n"
        "common.\n"
    )
    lo_s = max(int(ts[0]) for ts, _, _ in ticks.values()) // 1000 + 1
    hi_s = min(int(ts[-1]) for ts, _, _ in ticks.values()) // 1000
    print(f"grid {hi_s - lo_s:,} seconds\n")

    cache = {}

    def series(feed):
        if feed not in cache:
            cache[feed] = second_grid(ticks, feed, lo_s, hi_s)
        return cache[feed]

    def run(pairs, label):
        sub(label)
        print(f"  {'pair':>28s} {'n':>8s} {'rho(0)':>8s} {'best rho':>9s} "
              f"{'at lag':>7s} {'implied bps':>12s} {'spread bps':>11s} {'net':>8s}")
        for x, y in pairs:
            if x not in ticks or y not in ticks:
                print(f"  {x + ' vs ' + y:>28s}   missing")
                continue
            mx, fx = series(x)
            my, fy = series(y)
            ok = (fx < 5000) & (fy < 5000) & np.isfinite(mx) & np.isfinite(my)
            rx = np.where(ok, np.log(np.where(np.isfinite(mx), mx, 1.0)), np.nan)
            ry = np.where(ok, np.log(np.where(np.isfinite(my), my, 1.0)), np.nan)
            dx, dy = np.diff(rx), np.diff(ry)
            good = np.isfinite(dx) & np.isfinite(dy)
            dx, dy = np.where(good, dx, 0.0), np.where(good, dy, 0.0)
            n = int(good.sum())
            if n < 5000:
                print(f"  {x + ' vs ' + y:>28s} {n:8d}   (too few)")
                continue
            best, best_lag, at0 = 0.0, 0, 0.0
            for lag in range(-maxlag, maxlag + 1):
                if lag >= 0:
                    u, v = dx[: len(dx) - lag], dy[lag:]
                else:
                    u, v = dx[-lag:], dy[: len(dy) + lag]
                if u.std() == 0 or v.std() == 0:
                    continue
                r = float(np.corrcoef(u, v)[0, 1])
                bump("leadlag-lags")
                if lag == 0:
                    at0 = r
                elif abs(r) > abs(best):
                    best, best_lag = r, lag
            # What that correlation would be worth: rho * sigma of the target.
            sigma_bps = float(np.std(dy[good]) * 10_000.0)
            implied = abs(best) * sigma_bps
            ts_, b_, a_ = ticks[y]
            spread = float(np.median((a_ - b_) / ((a_ + b_) / 2) * 10_000))
            print(f"  {x + ' vs ' + y:>28s} {n:8d} {at0:8.4f} {best:9.4f} "
                  f"{best_lag:7d} {implied:12.4f} {spread:11.4f} "
                  f"{implied - spread:8.4f}")

    run(RELATED, f"related pairs ({len(RELATED)})")
    run(UNRELATED, f"unrelated controls ({len(UNRELATED)})")


# --------------------------------------------------------------------------
# 4. The Volatility indices against their own names
# --------------------------------------------------------------------------


def part_definition() -> None:
    head("4. DO THE VOLATILITY INDICES REALISE WHAT THEY ARE NAMED FOR?")
    print(
        "Named annualised volatility against measured. 1m closes, 60 days, split\n"
        "in half by time because a number that only holds in one half is not a\n"
        "number. The generator study is another agent's; this is only the level\n"
        "check that the desk's own volatility estimate would inherit.\n"
    )
    conn = sqlite3.connect(f"file:{RESEARCH}?mode=ro", uri=True)
    names = [("volatility_%s_index" % p, float(p)) for p in ("10", "25", "50", "75", "100")]
    names += [("volatility_%s_1s_index" % p, float(p)) for p in ("10", "25", "50", "75", "100", "150", "250")]
    mins = 365.0 * 24.0 * 60.0
    print(f"  {'feed':26s} {'named':>7s} {'measured':>9s} {'ratio':>7s} "
          f"{'1st half':>9s} {'2nd half':>9s} {'bars':>8s}")
    for feed, named in names:
        rows = conn.execute(
            "SELECT close FROM bars WHERE feed=? AND interval='1m' ORDER BY ts", (feed,)
        ).fetchall()
        c = np.array([r[0] for r in rows], dtype=float)
        c = c[np.isfinite(c) & (c > 0)]
        if len(c) < 1000:
            continue
        r = np.diff(np.log(c))
        half = len(r) // 2
        ann = lambda x: float(np.std(x) * math.sqrt(mins) * 100.0)  # noqa: E731
        bump("definition-feeds")
        print(f"  {feed:26s} {named:7.0f} {ann(r):9.2f} {ann(r) / named:7.3f} "
              f"{ann(r[:half]):9.2f} {ann(r[half:]):9.2f} {len(c):8d}")
    conn.close()


# --------------------------------------------------------------------------


def main() -> None:
    started = time.time()
    rng = random.Random(SEED)
    print(f"crossing.py  seed={SEED}  parts={PARTS}", flush=True)
    ticks = load_ticks(sorted({f for tri in TRIANGLES for f in tri[:3]}
                              | {f for p in RELATED + UNRELATED for f in p}))
    print(f"loaded ticks for {len(ticks)} feeds", flush=True)
    part_clock(ticks)
    rows = None
    if "1" in PARTS:
        rows = part_deviation(rng)
        part_broker_reaction(rows, ticks, rng)
    if "2" in PARTS:
        part_triangles(ticks)
        part_triangles_long(ticks)
    if "3" in PARTS:
        part_leadlag(ticks)
    if "4" in PARTS:
        part_definition()
    head("COMPARISONS MADE")
    for name, n in sorted(COMPARISONS.items()):
        print(f"  {name:28s} {n}")
    print(f"  {'TOTAL':28s} {sum(COMPARISONS.values())}")
    print(f"\nelapsed {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
