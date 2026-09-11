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
    """Mid, spread and both sides. The sides are the point: a round trip is
    bought at the ask and sold at the bid, and a claim about a mid is a claim
    about a price nobody trades."""
    rows = conn.execute(QUERY, (feed, venue, ticker, start, end)).fetchall()
    rows = [r for r in rows if r[3] and r[3] > 0 and r[1] and r[2] and r[2] >= r[1] > 0]
    if not rows:
        z = np.empty(0)
        return np.empty(0, np.int64), z, z, z, z
    ts = np.fromiter((r[0] for r in rows), np.int64, len(rows))
    bid = np.fromiter((r[1] for r in rows), np.float64, len(rows))
    ask = np.fromiter((r[2] for r in rows), np.float64, len(rows))
    mid = np.fromiter((r[3] for r in rows), np.float64, len(rows))
    spread = np.fromiter((r[4] if r[4] is not None else np.nan for r in rows),
                         np.float64, len(rows))
    return ts, mid, spread, bid, ask


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
    """Every venue for one feed on one grid, trimmed to where all of them are live.

    The trim is not tidiness. `gridify` has nothing to carry forward before a
    venue's first row, and a log price that begins at zero and steps to 11.3 is
    a **113,000 basis point return** sitting at the head of the window. It does
    not need to be common to matter: the first version of this harness left it
    in, and the mean forward move after a dislocation came back at +49bps
    against a consensus whose 250ms return had a standard deviation of 18.6bps
    - forty times the truth. The masks hid it from the event selection and not
    from the trailing means, which is the worst of both.

    So the window starts where the last venue starts, and the first `BASE_S` of
    it is marked unusable as well, because a trailing hour that is not yet an
    hour old is not a baseline.
    """
    n = int((end - start) // step_ms)
    conn = _connect(PRICES)
    grids, ages, spreads, counts, sides = {}, {}, {}, {}, {}
    for venue, ticker in FEEDS[feed]:
        ts, mid, spread, bid, ask = read_quotes(conn, feed, venue, ticker, start, end)
        counts[venue] = len(ts)
        g, age = gridify(ts, mid, start, n, step_ms)
        grids[venue] = g
        ages[venue] = age
        # Both sides for every venue, not only the broker: the control that
        # decides this page puts each exchange in the broker's chair, and it
        # has to pay that exchange's own spread when it does.
        sides[venue] = {
            "bid": gridify(ts, bid, start, n, step_ms)[0],
            "ask": gridify(ts, ask, start, n, step_ms)[0],
        }
        good = spread[~np.isnan(spread)]
        spreads[venue] = float(np.median(good)) if len(good) else float("nan")
    conn.close()

    live = [int(np.argmax(~np.isnan(grids[v]))) if np.isnan(grids[v]).any() else 0
            for v in grids]
    begin = max(live) + 1
    for store in (grids, ages):
        for key in store:
            store[key] = store[key][begin:]
    for key in sides:
        sides[key] = {k: v[begin:] for k, v in sides[key].items()}
    n -= begin
    usable = np.ones(n, bool)
    for venue in grids:
        usable &= ages[venue] <= MAX_AGE_MS
        usable &= ~np.isnan(grids[venue])
    warm = min(n, int(BASE_S * 1000 / GRID_MS))
    usable[:warm] = False
    return n, grids, sides, spreads, counts, usable, start + begin * step_ms


def consensus(grids, exclude=BROKER):
    """A consensus log-price index, with each venue's basis taken out.

    `exclude` is not optional in spirit, and the reason is
    `structures.features.Book.consensus`, which takes the same argument for the
    same reason: a venue must never be part of the number it is measured
    against. Deriv is never in it. When an exchange is put in Deriv's chair for
    the control, that exchange comes out of it too.

    Two of the five exchanges quote USDT and three quote USD, so the raw levels
    are not comparable and their median is not a price. Each venue is expressed
    against the cross-venue mean over its own trailing hour before the median
    is taken; a constant or slowly-drifting basis therefore contributes nothing
    and only the fresh part of a gap survives.
    """
    venues = [v for v in grids if v != BROKER and v != exclude]
    logs = np.vstack([np.log(grids[v]) for v in venues])
    middle = logs.mean(axis=0)
    w = int(BASE_S * 1000 / GRID_MS)
    aligned = np.vstack([row - trailing_mean(row - middle, w) for row in logs])
    return np.median(aligned, axis=0)


def dislocation(index, broker_log):
    """Consensus minus broker, in bps, against its own trailing hour.

    Trailing, never centred. A centred baseline would be reading the future,
    and the whole claim here is about what is knowable at the moment of the
    trade.
    """
    gap = index - broker_log
    w = int(BASE_S * 1000 / GRID_MS)
    return 1e4 * (gap - trailing_mean(gap, w))


#: How far back an event looks to decide who opened the gap.
CAUSE_S = float(os.environ.get("CAUSE_S", "5"))


def study(label, e, sides, broker_log, index, usable, threshold, horizons_steps,
          rng, start):
    """What a round trip after a dislocation is worth, and who opened the gap.

    Every horizon keeps its own surviving index, because a point near the end
    of the window survives one second ahead and not five, and quietly reusing
    one mask across horizons is how a forward return gets attached to the wrong
    event.

    `trip` is the whole answer to "is the lag bigger than the spread", and it
    answers it without an assumption: when Deriv looks cheap it buys at Deriv's
    **ask** and sells at Deriv's **bid** later, and when Deriv looks rich it
    does the reverse. The spread is not subtracted afterwards, it is paid.

    `cause` splits the events by who opened the gap in the previous `CAUSE_S`:
    the market moving away from Deriv, or Deriv moving away from the market.
    Only the first is the hypothesis. The second is Deriv's own quote wobbling
    and then coming back, which would produce exactly the same convergence and
    mean nothing about lateness.
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
    bid, ask = np.log(sides["bid"]), np.log(sides["ask"])

    back = int(CAUSE_S * 1000 / GRID_MS)
    prior = np.maximum(idx - back, 0)
    by_market = (index[idx] - index[prior]) * sign
    by_broker = -(broker_log[idx] - broker_log[prior]) * sign
    cause = np.where(by_market >= by_broker, "market", "broker")

    out = {"label": label, "n": len(idx), "at": {}}
    for name, k in horizons_steps:
        ahead = idx + k
        ok = ahead < n
        ok[ok] &= usable[ahead[ok]]
        if int(ok.sum()) < 30:
            continue
        a, b, g = idx[ok], ahead[ok], sign[ok]
        long = g > 0
        trip = np.where(long, bid[b] - ask[a], bid[a] - ask[b]) * 1e4
        out["at"][name] = {
            "idx": a,
            "broker": 1e4 * (broker_log[b] - broker_log[a]) * g,
            "market": 1e4 * (index[b] - index[a]) * g,
            "trip": trip,
            "size": np.abs(e[a]),
            "cause": cause[ok],
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
            ts = read_quotes(conn, feed, venue, ticker, START, END)[0]
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
        ts, mid, spread, _, _ = read_quotes(conn, feed, BROKER, ticker, lo, hi)
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
            ets = read_quotes(conn, feed, venue, vt, lo, hi)[0]
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


def section_events(feed, grids, sides, usable, spreads, rng, start, floor=None,
                   label=""):
    index = consensus(grids, exclude=BROKER)
    broker_log = np.log(grids[BROKER])
    e = dislocation(index, broker_log)
    shift = int(PLACEBO_H * 3600 * 1000 / GRID_MS)
    placebo_index = np.roll(index, shift)
    ep = dislocation(placebo_index, broker_log)

    spread = spreads[BROKER]
    #: The optimistic cost: Deriv's spread on the MT5 account the desk actually
    #: trades, which is far tighter than the quote TradingView publishes for the
    #: same venue. If an edge fails against this, it fails against anything.
    cheap = floor if floor else spread
    others = [v for k, v in spreads.items() if k != BROKER]
    horizons = [(x, int(x * 1000 / GRID_MS)) for x in HORIZONS_S]
    print(f"  {label}{feed}: Deriv spread {spread:.3f}bps on TradingView, "
          f"{cheap:.3f}bps on MT5; exchanges {min(others):.3f}-{max(others):.3f}bps")
    share = float(np.mean(np.abs(e[usable]) >= spread)) if usable.any() else 0.0
    print(f"  {label}{feed}: |dislocation| >= one Deriv spread "
          f"{share:.2%} of usable time")
    rows = []
    for mult in SPREADS:
        theta = mult * spread
        real = study("event", e, sides[BROKER], broker_log, index, usable, theta,
                     horizons, rng, start)
        fake = study("placebo", ep, sides[BROKER], broker_log, placebo_index,
                     usable, theta, horizons, rng, start)
        if real is None or fake is None:
            print(f"      {mult:.0f}x spread ({theta:.2f}bps): too few to report")
            continue
        print(f"      threshold {mult:.0f}x spread = {theta:6.2f}bps   "
              f"events {real['n']:6d}   placebo {fake['n']:6d}   "
              f"market-made {float(np.mean(real['at'][min(real['at'])]['cause'] == 'market')):.0%}")
        print(f"        {'ahead':>7s} {'n':>7s} {'deriv':>8s} {'median':>8s} "
              f"{'placebo':>8s} {'market':>9s} {'net MT5':>8s} {'ROUND TRIP':>11s} "
              f"{'median':>8s} {'win%':>6s}")
        for name, _ in horizons:
            if name not in real["at"] or name not in fake["at"]:
                continue
            r, f = real["at"][name], fake["at"][name]
            d = float(np.mean(r["broker"]))
            dm = float(np.median(r["broker"]))
            p = float(np.mean(f["broker"]))
            m = float(np.mean(r["market"]))
            t = float(np.mean(r["trip"]))
            tm = float(np.median(r["trip"]))
            win = float(np.mean(r["trip"] > 0))
            print(f"        {name:7.2f} {len(r['broker']):7d} {d:+8.3f} {dm:+8.3f} "
                  f"{p:+8.3f} {m:+9.3f} {d - p - cheap:+8.3f} {t:+11.3f} "
                  f"{tm:+8.3f} {win:6.1%}")
        # Rows for the conditioned cut, at two seconds - the soonest horizon a
        # real round trip through the bus and the broker could plausibly reach.
        for kind, got in (("event", real), ("placebo", fake)):
            block = got["at"].get(2.0)
            if block is None:
                continue
            for j in range(len(block["trip"])):
                rows.append({
                    "kind": kind,
                    "feed": feed,
                    "cause": str(block["cause"][j]),
                    "hour": f"{int(block['hour'][j]) // 6 * 6:02d}h",
                    "size": ("1-2x" if block["size"][j] < 2 * spread else
                             "2-4x" if block["size"][j] < 4 * spread else "4x+"),
                    "threshold": f"{mult:.0f}x",
                    "trip": float(block["trip"][j]),
                    "net": float(block["broker"][j]) - cheap,
                })
    # Who opened the gap decides whether any of this is about lateness at all.
    block = None
    for mult in SPREADS[:1]:
        real = study("event", e, sides[BROKER], broker_log, index, usable,
                     mult * spread, horizons, rng, start)
        block = real["at"].get(2.0) if real else None
    if block is not None:
        print(f"      by who opened the gap, at 2s, threshold 1x spread:")
        for which in ("market", "broker"):
            sel = block["cause"] == which
            if sel.sum() < 30:
                print(f"        {which:>7s}: {int(sel.sum())} - too few")
                continue
            print(f"        {which:>7s}: n={int(sel.sum()):6d}  "
                  f"deriv {float(np.mean(block['broker'][sel])):+7.3f}  "
                  f"round trip {float(np.mean(block['trip'][sel])):+7.3f}  "
                  f"win {float(np.mean(block['trip'][sel] > 0)):.1%}")
    print()
    return rows


def section_chairs(feed, grids, sides, usable, spreads, rng, start, label=""):
    """Put every exchange in Deriv's chair and ask the same question of it.

    This is the control the page turns on, and it is the one the rotated
    placebo cannot supply. Any venue measured against a median of the others
    will appear to revert to it, because top of book wanders and a median does
    not. That is a fact about quotes, not about brokers. If Bitstamp catches up
    the way Deriv does, then "Deriv is late" is a description of every venue on
    the board and there is nothing here about Deriv at all.

    Each venue is measured against a consensus that excludes it, at the **same
    absolute threshold** - Deriv's own spread on this feed - so the comparison
    is between equal dislocations rather than between equal quantiles. And each
    pays its own spread on the round trip, which is the part that decides
    whether a catch-up is worth anything: the exchanges catch up across a
    hundredth of a basis point and Deriv across two and a half.
    """
    theta = spreads[BROKER]
    horizons = [(2.0, int(2000 / GRID_MS))]
    print(f"  {label}{feed}: every venue in the broker's chair, dislocation "
          f">= {theta:.3f}bps, measured 2s later")
    print(f"      {'venue':>9s} {'spread':>8s} {'events':>8s} {'of time':>7s} "
          f"{'catch-up':>9s} {'round trip':>11s} {'win%':>6s} | "
          f"{'market-made':>11s} {'trip':>8s} {'win%':>6s} | "
          f"{'broker-made':>11s} {'trip':>8s}")
    for venue in grids:
        index = consensus(grids, exclude=venue)
        own = np.log(grids[venue])
        e = dislocation(index, own)
        got = study(venue, e, sides[venue], own, index, usable, theta,
                    horizons, rng, start)
        if got is None or 2.0 not in got["at"]:
            print(f"      {venue:>9s} {spreads[venue]:8.3f}   too few")
            continue
        at = got["at"][2.0]
        share = float(np.mean(np.abs(e[usable]) >= theta))
        made = at["cause"] == "market"
        cells = []
        for sel in (made, ~made):
            count = int(sel.sum())
            if count < 30:
                # Printed as a count and a dash rather than a number. A mean of
                # eleven observations rendered to three decimals is the shape a
                # table takes just before somebody quotes it.
                cells.append((f"{count:11d}", f"{'-':>8s}", f"{'-':>6s}"))
            else:
                cells.append((f"{count:11d}",
                              f"{float(np.mean(at['trip'][sel])):+8.3f}",
                              f"{float(np.mean(at['trip'][sel] > 0)):6.1%}"))
        print(f"      {venue:>9s} {spreads[venue]:8.3f} {len(at['broker']):8d} "
              f"{share:7.2%} {float(np.mean(at['broker'])):+9.3f} "
              f"{float(np.mean(at['trip'])):+11.3f} "
              f"{float(np.mean(at['trip'] > 0)):6.1%} | "
              f"{cells[0][0]} {cells[0][1]} {cells[0][2]} | "
              f"{cells[1][0]} {cells[1][1]}")
    print()


#: Entry delays to price the round trip at, in seconds. `research/reacting.md`
#: measured the same thing on the broker's own book and found the question never
#: got asked because the edge was zero before latency touched it. Here it is not
#: zero, so it has to be asked.
DELAYS_S = (0.0, 0.25, 0.5, 1.0, 2.0, 3.0)
HOLD_S = float(os.environ.get("HOLD_S", "5"))


def section_latency(feed, grids, sides, usable, spreads, rng, start, label=""):
    """The only subset that pays, priced at the delay a real round trip takes.

    Entry is not at the instant the dislocation is visible. It is visible to
    `structures` after a quote is written, then travels the bus, then `trading`
    decides, then the broker fills. Every one of those is measured in the
    hundreds of milliseconds on this desk, so an edge that exists at zero delay
    and not at one second is not an edge this desk has.
    """
    theta = spreads[BROKER]
    hold = int(HOLD_S * 1000 / GRID_MS)
    index = consensus(grids, exclude=BROKER)
    own = np.log(grids[BROKER])
    e = dislocation(index, own)
    bid, ask = np.log(sides[BROKER]["bid"]), np.log(sides[BROKER]["ask"])
    n = len(usable)

    cand = np.flatnonzero(usable & (np.abs(e) >= theta))
    idx = cooled(cand, int(COOLDOWN_S * 1000 / GRID_MS))
    if len(idx) < 50:
        print(f"  {label}{feed}: too few dislocations to price")
        return
    sign = np.sign(e[idx])
    back = int(CAUSE_S * 1000 / GRID_MS)
    prior = np.maximum(idx - back, 0)
    made = ((index[idx] - index[prior]) * sign) >= (-(own[idx] - own[prior]) * sign)

    print(f"  {label}{feed}: market-made dislocations >= {theta:.3f}bps, "
          f"held {HOLD_S:.0f}s, entered after a delay")
    print(f"      {'delay':>6s} {'n':>7s} {'round trip':>11s} {'median':>9s} "
          f"{'win%':>6s} {'still open':>11s}")
    for delay in DELAYS_S:
        k = int(delay * 1000 / GRID_MS)
        enter, exit_ = idx + k, idx + k + hold
        ok = made & (exit_ < n)
        ok[ok] &= usable[enter[ok]] & usable[exit_[ok]]
        if int(ok.sum()) < 30:
            print(f"      {delay:6.2f} {int(ok.sum()):7d}   too few")
            continue
        a, b, g = enter[ok], exit_[ok], sign[ok]
        trip = 1e4 * np.where(g > 0, bid[b] - ask[a], bid[a] - ask[b])
        # How much of the gap is still open at the moment of entry - if it has
        # already closed there is nothing left to take.
        left = e[a] * g
        print(f"      {delay:6.2f} {len(trip):7d} {float(np.mean(trip)):+11.3f} "
              f"{float(np.median(trip)):+9.3f} {float(np.mean(trip > 0)):6.1%} "
              f"{float(np.mean(left)):11.3f}")
    print()


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
        n, grids, sides, spreads, counts, usable, begin = build(feed, START, END, GRID_MS)
        built[feed] = (grids, sides, spreads, usable, begin)
        print(f"  {feed}: {n:,} grid points from {begin}, {usable.mean():.1%} usable "
              f"({', '.join(f'{v}={c:,}' for v, c in counts.items())})")
        section_leadlag(feed, grids, usable)

    print("=== 4. dislocation events: does Deriv catch up, and is it worth crossing ===")
    print("  deriv      mean signed move of Deriv's mid after the dislocation, bps")
    print("  median     the same, median - a mean carried by three prints is visible")
    print("  placebo    the same after a dislocation against a 12h-rotated consensus")
    print("  market     the consensus's own signed move, so convergence that is the")
    print("             market coming back rather than Deriv catching up is visible")
    print("  net MT5    deriv - placebo - the spread on the account the desk trades")
    print("  ROUND TRIP buy Deriv's ask and sell its bid (or the reverse), in bps.")
    print("             Nothing is subtracted from this: the spread is paid in it.")
    print()
    rows = []
    for feed in FEEDS:
        grids, sides, spreads, usable, begin = built[feed]
        rows += section_events(feed, grids, sides, usable, spreads, rng, begin,
                               floor=mt5_spread.get(feed))

    print("=== 4b. the control that decides it: every venue in the broker's chair ===")
    for feed in FEEDS:
        grids, sides, spreads, usable, begin = built[feed]
        section_chairs(feed, grids, sides, usable, spreads, rng, begin)

    print("=== 4c. what a delay does to the only subset that pays ===")
    for feed in FEEDS:
        grids, sides, spreads, usable, begin = built[feed]
        section_latency(feed, grids, sides, usable, spreads, rng, begin)

    print("=== 5. conditioned, so the pooled number is not a composition ===")
    try:
        from till_infinity.shared.strata import compare
        for value in ("trip", "net"):
            what = ("a real round trip through Deriv's own bid and ask"
                    if value == "trip" else
                    "the mid move, net of the MT5 spread")
            print(f"  --- {value}: {what} ---")
            got = compare(rows, value=value, bucket="kind",
                          within=("feed", "cause", "hour", "size", "threshold"),
                          min_n=200)
            print(got.render())
            print()
        print("  --- and the cut that carries the hypothesis: who opened the gap ---")
        only = [r for r in rows if r["kind"] == "event"]
        got = compare(only, value="trip", bucket="cause",
                      within=("feed", "hour", "size", "threshold"), min_n=200)
        print(got.render())
        print()
    except Exception as exc:      # noqa: BLE001 - a research harness, not a service
        print(f"  strata unavailable ({exc!r}); pooled only")
        for kind in ("event", "placebo"):
            xs = [r["trip"] for r in rows if r["kind"] == kind]
            if xs:
                print(f"  {kind:>8s} n={len(xs):7d} mean {st.fmean(xs):+.4f}")
    print()

    print("=== 6. split sample: the same thing on each half of the window ===")
    mid = START + (END - START) // 2
    for name, (lo, hi) in (("first half", (START, mid)), ("second half", (mid, END))):
        for feed in FEEDS:
            n, grids, sides, spreads, counts, usable, begin = build(feed, lo, hi, GRID_MS)
            if usable.mean() < 0.2:
                print(f"  {name} {feed}: {usable.mean():.1%} usable, skipped")
                continue
            section_leadlag(feed, grids, usable, label=f"{name} ")
            section_events(feed, grids, sides, usable, spreads, rng, begin,
                           floor=mt5_spread.get(feed), label=f"{name} ")
            section_chairs(feed, grids, sides, usable, spreads, rng, begin,
                           label=f"{name} ")

    print(f"done in {time.time() - began:.0f}s")


if __name__ == "__main__":
    sys.exit(run())
