"""Does Deriv's crypto quote follow the exchanges, and is the lag worth the spread?

Deriv quotes `btc`, `eth` and `sol` as CFDs. If its quote is a delayed copy of
where the exchanges already are, the delay is in principle tradeable: buy the
broker's stale ask while the market is already higher, sell it back when the
broker catches up. That is the hypothesis. It is also, stated plainly, latency
arbitrage against a broker's own price - the thing brokers surveil for - so the
bar for believing it has to be higher than usual, not lower.

`structures` already measures cross-venue lateness: `features.Book` gives every
venue a `staleness` in seconds against the group, and the `stale` shape fires
when one venue stops while the others carry on. That machinery compares
exchanges **to each other** at a scale of tens of seconds - it is a dead-feed
detector. It has never been pointed at Deriv as a *price*, and the lag that
would matter here is one to two orders of magnitude smaller than what it fires
on.

## The measurement that decides this is not the lead-lag, it is the clock

A lead measured across sources is a lead in *arrival*, not in *price*, unless
you know what each timestamp means. So the first section of this harness asks
what our timestamps are, and everything after it is read in that light:

* **Every quote row in `prices.db` is stamped by us.** `prices/quotes.py` calls
  `parse_quote(merged, now=time.time())` in the websocket handler and
  `store.py` writes `int(quote.time * 1000)`. There is no venue-side timestamp
  in the store at all - `lp_time` is *requested* from TradingView in
  `QUOTE_FIELDS` and then dropped on the floor by `parse_quote`.
* That is good and bad. Good: all six venues share one clock, so there is no
  clock-offset term between them and a difference in arrival is a real
  difference in arrival. Bad: the quantity measured is
  `venue move + TradingView ingest + TradingView fan-out + our socket handler`,
  and only the first term is tradeable.

Three controls separate those:

1. **The transport floor.** Exchange against exchange. Binance and Bybit track
   each other to within milliseconds in reality, so whatever lead this data
   reports between *them* is what the pipe manufactures. A Deriv lead inside
   that band is a pipe measurement wearing a market's clothes.
2. **The same venue down two pipes.** `research.db`'s `ticks` table is Deriv's
   own MT5 feed - the one the desk actually trades through - for `btc` and
   `eth`. Deriv-via-TradingView against Deriv-via-MT5 is one venue, two
   transports, so any lag between them is entirely transport (plus whatever
   offset MT5's server clock carries, which is exactly the term this cannot
   separate and must therefore report rather than assume away).
3. **A placebo.** The dislocation machinery run against a consensus index
   shifted twelve hours. It preserves the selection rule, the volatility
   clustering and Deriv's own mean reversion, and destroys only the thing being
   claimed. `research/generated.md` is the standing reminder: the largest
   correlation in a 325-pair study was between two unrelated instruments.

## What would count as failure, written before the run

* The cross-correlation peak for Deriv sitting inside the exchange-against-
  exchange band. Then there is no Deriv-specific lateness, only a pipe.
* The peak not reproducing in both halves of the window.
* The catch-up after a dislocation being no larger than after a placebo
  dislocation. Then what is being measured is Deriv's own microstructure.
* The catch-up, net of placebo, being smaller than Deriv's spread.
  `research/reacting.md` killed a seconds-scale edge on the broker's book for
  exactly this reason - a median spread of 0.159 volatility units against an
  excursion of 0.015 - and the same arithmetic applies here.

## Why the dislocation is demeaned before it is used

Two of the five exchange venues quote USDT pairs (`BINANCE:BTCUSDT`,
`BYBIT:BTCUSDT`) and three quote USD. The USDT basis is a real, persistent,
drifting offset of a few basis points, and a CFD broker is entitled to carry a
markup on top of it. A raw gap between Deriv and a consensus is therefore
mostly basis and not lateness. Every level here is expressed against its own
**trailing** hour, so a constant or slowly-drifting offset contributes nothing
and only the fresh part of a gap is called a dislocation. Trailing, not
centred: a centred window would be reading the future.

## Resolution, honestly

TradingView pushes on its own cadence, not on the exchange's. Over the dense
part of the window a venue writes on the order of one row a second, so this
data cannot resolve a lead finer than roughly a second no matter how the
arithmetic is arranged. Deriv's MT5 feed arrives on a 100ms poll. Both numbers
are printed in section 1 so the resolution floor is visible next to every lag
claimed below it.
"""

from __future__ import annotations

import os
import random
import sqlite3
import statistics as st
import sys
import time

import numpy as np

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
PRICES = os.environ.get("PRICES", os.path.join(DATA, "prices.db"))
RESEARCH = os.environ.get("RESEARCH", os.path.join(DATA, "research.db"))

#: `prices.db` reads clean through the table's own primary key and dies on a
#: full scan. See `_connect` - this is a property of the file, not a setting.
BROKER = "DERIV"

FEEDS: dict[str, list[tuple[str, str]]] = {
    "btc": [("BINANCE", "BTCUSDT"), ("BYBIT", "BTCUSDT"), ("COINBASE", "BTCUSD"),
            ("BITSTAMP", "BTCUSD"), ("KRAKEN", "BTCUSD"), ("DERIV", "BTCUSD")],
    "eth": [("BINANCE", "ETHUSDT"), ("BYBIT", "ETHUSDT"), ("COINBASE", "ETHUSD"),
            ("BITSTAMP", "ETHUSD"), ("KRAKEN", "ETHUSD"), ("DERIV", "ETHUSD")],
    "sol": [("BINANCE", "SOLUSDT"), ("BYBIT", "SOLUSDT"), ("COINBASE", "SOLUSD"),
            ("BITSTAMP", "SOLUSD"), ("KRAKEN", "SOLUSD"), ("DERIV", "SOLUSD")],
}

#: End of the dense collection window, and how far back to go. The quote
#: collector wrote 15-87k rows a venue a day through 2026-09-06 and then
#: thinned to a few hundred, so the window stops at the end of the 6th rather
#: than pretending the tail is data. Nothing here reaches the last three days.
END = int(os.environ.get("END", "1788825600000"))       # 2026-09-07 00:00 UTC
DAYS = float(os.environ.get("DAYS", "21"))
START = int(os.environ.get("START", str(END - int(DAYS * 86_400_000))))

GRID_MS = int(os.environ.get("GRID_MS", "250"))
#: Widest lead worth scanning, in seconds, either way.
LAG_S = float(os.environ.get("LAG_S", "15"))
#: A quote older than this is not evidence about the present, so a grid point
#: where any venue is staler than this is excluded rather than carried forward.
#: Same number and same reason as `structures.features.MAX_AGE`, scaled down:
#: this is a sub-minute question and a five-minute-old quote is not an answer.
MAX_AGE_MS = int(os.environ.get("MAX_AGE_MS", "60000"))
#: Trailing window the basis and the dislocation are measured against.
BASE_S = float(os.environ.get("BASE_S", "3600"))
#: How long a dislocation event stands, so overlapping windows are not counted
#: as independent observations.
COOLDOWN_S = float(os.environ.get("COOLDOWN_S", "60"))
#: Hours the placebo consensus is rotated by.
PLACEBO_H = float(os.environ.get("PLACEBO_H", "12"))
MAX_EVENTS = int(os.environ.get("MAX_EVENTS", "400000"))
HORIZONS_S = (0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 300.0)
#: Thresholds, in multiples of Deriv's own median spread. Stated this way on
#: purpose: a dislocation smaller than the cost of taking it is not an
#: opportunity, so the smallest interesting threshold is one spread.
SPREADS = (1.0, 2.0, 4.0)

SEED = int(os.environ.get("SEED", "20260911"))


def _connect(path: str) -> sqlite3.Connection:
    """Read-only, with a cache big enough that the walk is not seek-bound.

    `prices.db` has been treated as unusable on this project because
    `SELECT count(*)` raises `database disk image is malformed`. It is the
    **secondary index** that is malformed, not the table: `integrity_check`
    names tree 6 - `quotes_feed_ts` - holding page numbers past the end of a
    5,365,199-page file. Every query here gives equality on all four leading
    primary key columns, so the planner walks the table's own btree and never
    touches the broken index. That is why nothing below filters on `feed` and
    `ts` alone, and it must stay that way.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-400000")
    return conn


QUERY = (
    "SELECT ts, bid, ask, mid, spread_bps FROM quotes "
    "WHERE source='tradingview' AND feed=? AND venue=? AND ticker=? "
    "AND ts>=? AND ts<=? ORDER BY ts"
)


def read_quotes(conn, feed, venue, ticker, start, end):
    rows = conn.execute(QUERY, (feed, venue, ticker, start, end)).fetchall()
    rows = [r for r in rows if r[3] and r[3] > 0]
    if not rows:
        return np.empty(0, np.int64), np.empty(0), np.empty(0)
    ts = np.fromiter((r[0] for r in rows), np.int64, len(rows))
    mid = np.fromiter((r[3] for r in rows), np.float64, len(rows))
    spread = np.fromiter((r[4] if r[4] is not None else np.nan for r in rows),
                         np.float64, len(rows))
    return ts, mid, spread


def gridify(ts, val, start, n, step):
    """Last observation carried forward onto a fixed grid, plus its age.

    The age is the point. Carrying a price forward across a collector outage
    manufactures one enormous return at the far end of it, which is exactly the
    shape every statistic here is looking for - so the age is returned
    alongside and used to refuse those points rather than to smooth them.
    """
    raw = np.full(n, np.nan)
    if len(ts):
        idx = ((ts - start) // step).astype(np.int64)
        keep = (idx >= 0) & (idx < n)
        raw[idx[keep]] = val[keep]          # ascending, so the last write wins
    seen = ~np.isnan(raw)
    pos = np.where(seen, np.arange(n), -1)
    np.maximum.accumulate(pos, out=pos)
    live = pos >= 0
    out = np.full(n, np.nan)
    out[live] = raw[pos[live]]
    age = np.full(n, 1 << 30, np.int64)
    age[live] = (np.arange(n)[live] - pos[live]) * step
    return out, age


def trailing_mean(x, w):
    """Causal rolling mean over `w` grid steps, short windows at the start."""
    c = np.concatenate(([0.0], np.cumsum(x)))
    i = np.arange(len(x))
    lo = np.maximum(0, i - w + 1)
    return (c[i + 1] - c[lo]) / (i + 1 - lo)


def lagged_corr(x, y, lags):
    """corr(x[t], y[t+k]) for each k. Positive k means y moves *after* x.

    Returns are zeroed outside the usable region rather than dropped. Zeroing
    both series adds mass at the origin of the joint distribution, which
    attenuates every lag by the same factor and so cannot move the argmax -
    and the argmax is the whole claim.
    """
    n = len(x)
    xs = x - x.mean()
    ys = y - y.mean()
    denom = np.sqrt((xs * xs).sum() * (ys * ys).sum())
    if denom <= 0:
        return np.zeros(len(lags))
    out = np.empty(len(lags))
    for j, k in enumerate(lags):
        if k >= 0:
            a, b = xs[: n - k], ys[k:]
        else:
            a, b = xs[-k:], ys[: n + k]
        out[j] = float(np.dot(a, b)) / denom
    return out


def peak(lags, corrs, step_ms):
    """Where the profile peaks, how high, what it is at zero, and whether the
    peak is real.

    A correlation profile that rises all the way to the edge of the scan has no
    peak inside it, and reporting its argmax as a lead would be reporting the
    width of the scan. Those are marked, not silently used. `r@0` is printed
    beside every peak for the same reason: a peak of 0.11 against 0.105 at zero
    lag is a flat profile with a rounding error on top.
    """
    j = int(np.argmax(corrs))
    zero = int(np.argmin(np.abs(lags)))
    edge = j in (0, len(lags) - 1)
    return lags[j] * step_ms / 1000.0, float(corrs[j]), float(corrs[zero]), edge


def cooled(idx, cooldown_steps):
    """Keep the first of every cluster, so windows do not overlap."""
    keep = []
    last = -(1 << 60)
    for i in idx:
        if i - last >= cooldown_steps:
            keep.append(i)
            last = i
    return np.asarray(keep, np.int64)


def build(feed, start, end, step_ms):
    """Every venue for one feed on one grid, plus the usable mask."""
    n = int((end - start) // step_ms)
    conn = _connect(PRICES)
    grids, ages, spreads, counts = {}, {}, {}, {}
    for venue, ticker in FEEDS[feed]:
        ts, mid, spread = read_quotes(conn, feed, venue, ticker, start, end)
        counts[venue] = len(ts)
        g, age = gridify(ts, mid, start, n, step_ms)
        grids[venue] = g
        ages[venue] = age
        good = spread[~np.isnan(spread)]
        spreads[venue] = float(np.median(good)) if len(good) else float("nan")
    conn.close()
    usable = np.ones(n, bool)
    for venue in grids:
        usable &= ages[venue] <= MAX_AGE_MS
        usable &= ~np.isnan(grids[venue])
    return n, grids, ages, spreads, counts, usable


def consensus(grids, usable):
    """A consensus log-price index, with each venue's basis taken out.

    Two of the five exchanges quote USDT and three quote USD, so the raw levels
    are not comparable and their median is not a price. Each venue is expressed
    against the cross-venue mean over its own trailing hour before the median
    is taken; a constant or slowly-drifting basis therefore contributes nothing.
    """
    venues = [v for v in grids if v != BROKER]
    logs = np.vstack([np.log(np.where(np.isnan(grids[v]), 1.0, grids[v])) for v in venues])
    middle = logs.mean(axis=0)
    w = int(BASE_S * 1000 / GRID_MS)
    aligned = np.vstack([row - trailing_mean(row - middle, w) for row in logs])
    return np.median(aligned, axis=0), venues


def dislocation(index, broker_log):
    """Consensus minus broker, in bps, against its own trailing hour."""
    gap = index - broker_log
    w = int(BASE_S * 1000 / GRID_MS)
    return 1e4 * (gap - trailing_mean(gap, w))


def study(label, e, broker_log, index, usable, threshold, horizons_steps, rng, start):
    """Signed forward move after a dislocation, for the broker and the market.

    Every horizon keeps its own surviving index, because a point near the end
    of the window survives one second ahead and not five, and quietly reusing
    one mask across horizons is how a forward return gets attached to the wrong
    event.
    """
    cand = np.flatnonzero(usable & (np.abs(e) >= threshold))
    if len(cand) == 0:
        return None
    if len(cand) > 8 * MAX_EVENTS:
        cand = cand[:: max(1, len(cand) // (8 * MAX_EVENTS))]
    idx = cooled(cand, int(COOLDOWN_S * 1000 / GRID_MS))
    if len(idx) > MAX_EVENTS:
        idx = np.sort(rng.choice(idx, MAX_EVENTS, replace=False))
    if len(idx) == 0:
        return None
    sign = np.sign(e[idx])
    n = len(usable)
    out = {"label": label, "n": len(idx), "at": {}}
    for name, k in horizons_steps:
        ahead = idx + k
        ok = ahead < n
        ok[ok] &= usable[ahead[ok]]
        if int(ok.sum()) < 30:
            continue
        a, b, s = idx[ok], ahead[ok], sign[ok]
        out["at"][name] = {
            "idx": a,
            "broker": 1e4 * (broker_log[b] - broker_log[a]) * s,
            "market": 1e4 * (index[b] - index[a]) * s,
            "size": np.abs(e[a]),
            "hour": ((start + a.astype(np.int64) * GRID_MS) // 3_600_000) % 24,
        }
    return out if out["at"] else None


def section_clocks():
    print("=== 1. what the timestamps are, and how fine they can resolve ===")
    print("  Every prices.db row is stamped by our own collector at receive:")
    print("    quotes.py   parse_quote(merged, now=time.time())")
    print("    store.py    int(quote.time * 1000)")
    print("  TradingView's own `lp_time` is requested in QUOTE_FIELDS and never read,")
    print("  so no venue-side timestamp exists in the store. One clock for all six")
    print("  venues - no offset term between them - but it is a clock of arrival.")
    print()
    conn = _connect(PRICES)
    print(f"  {'feed':>5s} {'venue':>9s} {'rows':>9s} {'p25':>7s} {'p50':>7s} "
          f"{'p75':>7s}   deciles of ts % 1000")
    for feed in FEEDS:
        for venue, ticker in FEEDS[feed]:
            ts, _, _ = read_quotes(conn, feed, venue, ticker, START, END)
            if len(ts) < 100:
                print(f"  {feed:>5s} {venue:>9s} {len(ts):9d}   too few rows")
                continue
            gaps = np.diff(ts)
            bins = np.bincount((ts % 1000) // 100, minlength=10) / len(ts)
            q = np.percentile(gaps, [25, 50, 75])
            print(f"  {feed:>5s} {venue:>9s} {len(ts):9d} {q[0]:7.0f} {q[1]:7.0f} "
                  f"{q[2]:7.0f}   " + " ".join(f"{b:.2f}" for b in bins))
    conn.close()
    print()
    print("  Gaps are milliseconds between consecutive stored rows, and a row is")
    print("  stored only when the top of book actually changed. A median of one to")
    print("  four seconds is TradingView's push cadence, not the exchange's - which")
    print("  is the resolution floor for everything below.")
    print()
    print("  The deciles are where inside the second each row lands on our clock. A")
    print("  receive time from a continuously pushing source is flat at 0.10. Any")
    print("  venue that is not flat is arriving on somebody's schedule, and a")
    print("  schedule is a fixed offset that will read as a lead.")
    print()


def broker_ticks(feed):
    """Deriv's own MT5 stream: the price the desk actually trades."""
    conn = _connect(RESEARCH)
    rows = conn.execute(
        "SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts", (feed,)
    ).fetchall()
    conn.close()
    rows = [r for r in rows if r[1] and r[2] and r[2] > r[1] > 0]
    if not rows:
        return None
    ts = np.fromiter((r[0] for r in rows), np.int64, len(rows))
    mid = np.fromiter(((r[1] + r[2]) / 2 for r in rows), np.float64, len(rows))
    spread = np.fromiter((1e4 * (r[2] - r[1]) / ((r[1] + r[2]) / 2) for r in rows),
                         np.float64, len(rows))
    return ts, mid, spread


def section_two_pipes():
    """Is the Deriv we can measure the Deriv we can trade?

    This is the control the whole page turns on and it is not the one that was
    planned. The plan was to align Deriv-via-TradingView against Deriv-via-MT5
    and read the transport delay off the peak. The two pulls do not overlap
    where they need to: the dense quote window ends on the 6th and the MT5 tick
    pull covers the 9th to the 10th, by which time the quote collector was
    writing a few hundred rows a day. So the lag cannot be measured that way,
    and what can be measured instead turns out to matter more - whether the two
    series are the same instrument at all.
    """
    print("=== 2. the same venue down two pipes ===")
    print("  research.db `ticks` is the MT5 bridge - the broker the desk places")
    print("  orders through, on the broker's own server clock. prices.db's DERIV")
    print("  rows are TradingView's copy of Deriv, on our clock. If a lag is to be")
    print("  traded it has to exist in the first of those, and it can only be")
    print("  measured in the second.")
    print()
    found = {}
    conn = _connect(PRICES)
    for feed in FEEDS:
        got = broker_ticks(feed)
        if got is None:
            print(f"  {feed}: no MT5 ticks in research.db - nothing to check against")
            continue
        mts, mmid, mspread = got
        lo, hi = int(mts[0]), int(mts[-1])
        found[feed] = float(np.median(mspread))
        ticker = dict(FEEDS[feed])[BROKER]
        ts, mid, spread = read_quotes(conn, feed, BROKER, ticker, lo, hi)
        print(f"  {feed}: MT5 {len(mts):,} ticks over {(hi - lo) / 3.6e6:.1f}h, "
              f"median gap {np.median(np.diff(mts)):.0f}ms")
        print(f"        MT5 spread   {np.percentile(mspread, [25, 50, 75]).round(3)} bps "
              f"(p25/p50/p75)")
        tv_spread = spread[~np.isnan(spread)]
        if len(tv_spread):
            print(f"        TV DERIV spread {np.percentile(tv_spread, [25, 50, 75]).round(3)} "
                  f"bps over the same window, on {len(ts):,} rows")
        for venue, vt in FEEDS[feed]:
            if venue == BROKER:
                continue
            ets, _, _ = read_quotes(conn, feed, venue, vt, lo, hi)
            print(f"        {venue} rows inside the MT5 window: {len(ets):,}")
            break
        if len(ts) >= 50:
            j = np.searchsorted(mts, ts)
            ok = (j > 0) & (j < len(mts))
            dev = 1e4 * np.log(mid[ok] / mmid[j[ok]])
            print(f"        TV DERIV mid against MT5 mid, matched to the nearest tick:")
            print(f"          {np.percentile(dev, [5, 25, 50, 75, 95]).round(2)} bps "
                  f"(p5..p95) on {len(dev):,} points")
    conn.close()
    print()
    print("  Read the last two lines together. The two Deriv quotes disagree by more")
    print("  basis points than the MT5 spread is wide, and they disagree in a way")
    print("  that wanders. They are related series, not one series down two pipes -")
    print("  so a lead measured on the TradingView copy is a fact about the")
    print("  TradingView copy until somebody shows it survives the crossing.")
    print()
    return found


def section_leadlag(feed, grids, usable, label=""):
    step = GRID_MS
    span = int(LAG_S * 1000 / step)
    lags = np.arange(-span, span + 1)
    rets = {}
    for venue, g in grids.items():
        s = np.log(np.where(np.isnan(g), 1.0, g))
        r = np.diff(s)
        r *= usable[1:] & usable[:-1]
        rets[venue] = r
    exch = [v for v in grids if v != BROKER]

    def line(a, b):
        at, value, zero, edge = peak(lags, lagged_corr(rets[a], rets[b], lags), step)
        mark = "  *edge" if edge else ""
        print(f"      {a:>9s} -> {b:<9s} peak {at:+6.2f}s  r={value:.3f}  "
              f"r@0={zero:.3f}{mark}")
        return at, edge

    print(f"  {label}{feed}: exchange against exchange - the transport floor")
    floor = []
    for i, a in enumerate(exch):
        for b in exch[i + 1:]:
            at, edge = line(a, b)
            if not edge:
                floor.append(abs(at))
    print(f"  {label}{feed}: exchange against {BROKER}")
    deriv = []
    for a in exch:
        at, edge = line(a, BROKER)
        if not edge:
            deriv.append(at)
    if floor and deriv:
        print(f"      floor: |peak| between two exchanges reaches "
              f"{max(floor):.2f}s. Deriv peaks span "
              f"{min(deriv):+.2f}s to {max(deriv):+.2f}s. A Deriv lead inside "
              f"the floor is the pipe, not the market.")
    print("      *edge marks a profile still rising at the edge of the scan,")
    print("       which has no peak in it and is not a lead.")
    print()
    return rets


def section_events(feed, grids, usable, spreads, rng, start, floor=None, label=""):
    index, _ = consensus(grids, usable)
    broker_log = np.log(np.where(np.isnan(grids[BROKER]), 1.0, grids[BROKER]))
    e = dislocation(index, broker_log)
    shift = int(PLACEBO_H * 3600 * 1000 / GRID_MS)
    placebo_index = np.roll(index, shift)
    ep = dislocation(placebo_index, broker_log)

    spread = spreads[BROKER]
    #: The optimistic cost: Deriv's spread on the MT5 account the desk actually
    #: trades, which is far tighter than the quote TradingView publishes for the
    #: same venue. If an edge fails against this it fails against anything.
    cheap = floor if floor else spread
    others = [v for k, v in spreads.items() if k != BROKER]
    horizons = [(s, int(s * 1000 / GRID_MS)) for s in HORIZONS_S]
    print(f"  {label}{feed}: Deriv spread {spread:.3f}bps on TradingView, "
          f"{cheap:.3f}bps on MT5; exchanges {min(others):.3f}-{max(others):.3f}bps")
    share = float(np.mean(np.abs(e[usable]) >= spread)) if usable.any() else 0.0
    print(f"  {label}{feed}: |dislocation| >= one Deriv spread "
          f"{share:.1%} of usable time")
    rows = []
    for mult in SPREADS:
        theta = mult * spread
        real = study("event", e, broker_log, index, usable, theta, horizons, rng, start)
        fake = study("placebo", ep, broker_log, placebo_index, usable, theta,
                     horizons, rng, start)
        if real is None or fake is None:
            print(f"      {mult:.0f}x spread ({theta:.2f}bps): too few to report")
            continue
        print(f"      threshold {mult:.0f}x spread = {theta:6.2f}bps   "
              f"events {real['n']:6d}   placebo {fake['n']:6d}")
        print(f"        {'ahead':>7s} {'n':>7s} {'deriv':>9s} {'placebo':>9s} "
              f"{'edge':>9s} {'market':>9s} {'net (TV)':>10s} {'net (MT5)':>10s}")
        for name, _ in horizons:
            if name not in real["at"] or name not in fake["at"]:
                continue
            r, f = real["at"][name], fake["at"][name]
            d, p = float(np.mean(r["broker"])), float(np.mean(f["broker"]))
            m = float(np.mean(r["market"]))
            print(f"        {name:7.2f} {len(r['broker']):7d} {d:+9.3f} {p:+9.3f} "
                  f"{d - p:+9.3f} {m:+9.3f} {d - p - spread:+10.3f} "
                  f"{d - p - cheap:+10.3f}")
        # Rows for the conditioned cut, at two seconds - the soonest horizon a
        # real round trip through the bus and the broker could plausibly reach.
        for kind, got in (("event", real), ("placebo", fake)):
            block = got["at"].get(2.0)
            if block is None:
                continue
            for j in range(len(block["broker"])):
                rows.append({
                    "kind": kind,
                    "feed": feed,
                    "hour": f"{int(block['hour'][j]) // 6 * 6:02d}h",
                    "size": ("1-2x" if block["size"][j] < 2 * spread else
                             "2-4x" if block["size"][j] < 4 * spread else "4x+"),
                    "threshold": f"{mult:.0f}x",
                    "net": float(block["broker"][j]) - cheap,
                })
    print()
    return rows


def run():
    rng = np.random.default_rng(SEED)
    random.seed(SEED)
    began = time.time()
    print(f"window {START} -> {END}  ({(END - START) / 86.4e6:.1f} days), "
          f"grid {GRID_MS}ms, max age {MAX_AGE_MS}ms")
    print()
    section_clocks()
    mt5_spread = section_two_pipes()

    print("=== 3. lead-lag by cross-correlation of returns ===")
    print("  positive peak: the second venue moves after the first.")
    print()
    built = {}
    for feed in FEEDS:
        n, grids, ages, spreads, counts, usable = build(feed, START, END, GRID_MS)
        built[feed] = (grids, spreads, usable)
        print(f"  {feed}: {n:,} grid points, {usable.mean():.1%} usable "
              f"({', '.join(f'{v}={c:,}' for v, c in counts.items())})")
        section_leadlag(feed, grids, usable)

    print("=== 4. dislocation events: does Deriv catch up, and is it worth crossing ===")
    print("  deriv   = mean signed move of Deriv's own mid, bps")
    print("  placebo = the same after a dislocation against a 12h-rotated consensus")
    print("  edge    = deriv - placebo, which is what the lateness is worth")
    print("  market  = the consensus's own signed move, so convergence that is the")
    print("            market coming back rather than Deriv catching up is visible")
    print()
    rows = []
    for feed in FEEDS:
        grids, spreads, usable = built[feed]
        rows += section_events(feed, grids, usable, spreads, rng, START,
                               floor=mt5_spread.get(feed))

    print("=== 5. conditioned, so the pooled number is not a composition ===")
    try:
        from till_infinity.shared.strata import compare
        got = compare(rows, value="net", bucket="kind",
                      within=("feed", "hour", "size", "threshold"), min_n=200)
        print(got.render())
    except Exception as exc:      # noqa: BLE001 - a research harness, not a service
        print(f"  strata unavailable ({exc!r}); pooled only")
        for kind in ("event", "placebo"):
            xs = [r["net"] for r in rows if r["kind"] == kind]
            if xs:
                print(f"  {kind:>8s} n={len(xs):7d} mean {st.fmean(xs):+.4f}")
    print()

    print("=== 6. split sample: the same thing on each half of the window ===")
    mid = START + (END - START) // 2
    for name, (lo, hi) in (("first half", (START, mid)), ("second half", (mid, END))):
        for feed in FEEDS:
            n, grids, ages, spreads, counts, usable = build(feed, lo, hi, GRID_MS)
            if usable.mean() < 0.2:
                print(f"  {name} {feed}: {usable.mean():.1%} usable, skipped")
                continue
            section_leadlag(feed, grids, usable, label=f"{name} ")
            section_events(feed, grids, usable, spreads, rng, lo,
                           floor=mt5_spread.get(feed), label=f"{name} ")

    print(f"done in {time.time() - began:.0f}s")


if __name__ == "__main__":
    sys.exit(run())
