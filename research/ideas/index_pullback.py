"""`ma_pullback` on indices at 1m to 15m, costed at each bar's own spread.

The operator, 2026-11-20: *"ma pullback, use timeframes 1m to 15min, you can
even use microstructure info, test on indices like spy, Dow, etc, test on the
last 14 days to 7 days. Also need to know the market conditions that worked for
them."*

`ma_pullback` is the reading that led the 15m leaderboard in
[`rsi-ma-momentum.md`](../docs/rsi-ma-momentum.md) at **+0.3171R** over seven
days - and whose leaders were **0 of 10 positive in the prior thirty**, with a
day-shuffled market's best cell beating the real market's. So this is not a
fresh hypothesis; it is the same one asked at a finer clock, on a different
asset class, with two things the earlier run did not have.

**What is new here, and it is the reason to run it at all:**

* **The spread is measured per bar, not assumed.** The broker's rate rows carry
  a `spread` field in **points** alongside the OHLC, so every trade is charged
  the spread *that bar actually quoted* rather than a median for the feed.
  `spread-column-is-in-points` is the error that makes this worth saying twice:
  read as price it gave EURUSD a 476% round trip.
* **`tick_volume` as the only order-flow proxy there is.** `real_volume` is
  **0** on every row - `no-order-flow-and-no-real-volume` records why: no DOM,
  and `tick_volume` is a count of quotes, not of contracts. So it is a measure
  of *quoting activity*, and it is used as that and never as volume.
* **The conditions are the question, not a footnote.** Every trade is labelled
  with its volatility band, session, spread quantile and quoting-activity
  quantile, and the result is cut by each. A pooled mean on this desk has
  inverted in its subgroups before.

The cost warning that applies hardest at 1m, measured in
[`edge_life.py`](edge_life.py): cost in R is `spread / stop`, so it rises as
the clock shortens **and** as the stop tightens, and the second lever is much
the stronger. A 1 ATR stop at 5m is cheaper than a 0.25 ATR stop at 1h.

Run as:

    uv run python research/ideas/index_pullback.py --frames M1,M5,M15 --windows 14,7
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reactive_zones import Candles, atr  # noqa: E402

#: One gzipped CSV of every feed and frame, packed on the instance and pulled
#: whole. **Outside the repository**: candle history from the desk's own feed
#: stays out of a public tree, and `.secrets/` is gitignored.
#:
#: Packed there rather than read here because the bridge's key never leaves
#: that host, and converted from the rate rows' JSON because 156,541 bars of
#: it is 2.07 MB gzipped against about ten times that as JSON.
CACHE = Path(".secrets/indices/indices.csv.gz")

#: Every index the broker lists, at M15 with H4 and D1 beside it for the trend
#: filter. Separate from `CACHE` because the fast frames were pulled for six
#: symbols and this for fifteen, and merging them would make a missing feed
#: look like a quiet one.
WIDE = Path(".secrets/indices/allidx.csv.gz")

SYMBOLS = ("US SP 500", "Wall Street 30", "US Tech 100", "Germany 40", "UK 100", "Japan 225")
MINUTES = {"M1": 1, "M5": 5, "M15": 15}


@dataclass(slots=True)
class Feed:
    """Bars plus the two microstructure columns the venue does send."""

    bars: Candles
    spread_points: np.ndarray
    quotes: np.ndarray
    point: float


def _packed(where: Path = CACHE) -> dict[tuple[str, str], dict[str, np.ndarray]]:
    """Every feed in a CSV, keyed by `(symbol, frame)`. Read once per file."""
    if where in _CACHED:
        return _CACHED[where]
    import csv
    import gzip

    held: dict[tuple[str, str], list[list[float]]] = {}
    with gzip.open(where, "rt") as handle:
        for row in csv.DictReader(handle):
            key = (row["symbol"], row["frame"])
            held.setdefault(key, []).append(
                [
                    float(row["ts"]),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["spread"]),
                    float(row["quotes"]),
                ]
            )
    out: dict[tuple[str, str], dict[str, np.ndarray]] = {}
    for key, rows in held.items():
        block = np.asarray(rows)
        block = block[np.argsort(block[:, 0], kind="stable")]
        out[key] = {
            "ts": block[:, 0],
            "open": block[:, 1],
            "high": block[:, 2],
            "low": block[:, 3],
            "close": block[:, 4],
            "spread": block[:, 5],
            "quotes": block[:, 6],
        }
    _CACHED[where] = out
    return out


_CACHED: dict[Path, dict[tuple[str, str], dict[str, np.ndarray]]] = {}


def read(symbol: str, frame: str, point: float, where: Path = CACHE) -> Feed | None:
    """One feed out of a packed CSV, or `None` where it is not there."""
    block = _packed(where).get((symbol, frame))
    if block is None or block["ts"].size < 200:
        return None
    return Feed(
        bars=Candles(
            symbol=symbol,
            frame=frame,
            ts=(block["ts"] * 1e9).astype(np.int64),
            open=block["open"],
            high=block["high"],
            low=block["low"],
            close=block["close"],
        ),
        spread_points=block["spread"],
        quotes=block["quotes"],
        point=point,
    )


def moving(values: np.ndarray, length: int) -> np.ndarray:
    out = np.full(values.size, np.nan)
    if values.size >= length:
        out[length - 1 :] = np.lib.stride_tricks.sliding_window_view(values, length).mean(axis=1)
    return out


def point_of(symbol: str, close: float) -> float:
    """Price per point, inferred from the quote's own magnitude.

    The broker states `spread` in points and the spec that converts them is
    behind the symbol endpoint; these indices quote to two decimals at four to
    five figures, so a point is 0.01. Inferred rather than hard-coded per
    symbol, and asserted against the quote so a feed that is not shaped this
    way is skipped instead of silently mispriced by a factor of a hundred.
    """
    _ = symbol
    return 0.01 if close > 100.0 else 0.0001


@dataclass(slots=True)
class Trades:
    net: np.ndarray
    gross: np.ndarray
    cost: np.ndarray
    at: np.ndarray
    side: np.ndarray


def pullback(feed: Feed, length: int, reach: int, stop_atr: float, reward: float, patience: int) -> Trades:
    """`ma_pullback`: close above the average, momentum negative - a dip while above.

    The rule verbatim from `rsi_momentum.ma_signals`, so the two studies cannot
    drift: long when `close > MA` and the `reach`-bar change is negative, short
    on the mirror. Entry at the signal bar's close, one position at a time.

    **Charged this bar's own spread, twice** - in and out. `spread` is in
    points, so the money is `points * point`, and the cost in R is that over
    the stop distance.
    """
    bars, band = feed.bars, atr(feed.bars)
    slow = moving(bars.close, length)
    push = np.full(bars.close.size, np.nan)
    push[reach:] = bars.close[reach:] - bars.close[:-reach]
    side = np.zeros(bars.close.size, dtype=np.int8)
    alive = np.isfinite(slow) & np.isfinite(push) & np.isfinite(band) & (band > 0)
    side[alive & (bars.close > slow) & (push < 0)] = 1
    side[alive & (bars.close < slow) & (push > 0)] = -1

    n = bars.close.size
    nets, grosses, costs, ats, sides = [], [], [], [], []
    firing = np.flatnonzero(side != 0)
    at = 0
    while at < firing.size:
        i = int(firing[at])
        if i >= n - 1:
            break
        up = side[i] == 1
        entry = float(bars.close[i])
        risk = stop_atr * float(band[i])
        guard = entry - risk if up else entry + risk
        target = entry + reward * risk if up else entry - reward * risk
        done, j = None, i
        for j in range(i + 1, min(n, i + 1 + patience)):
            if (bars.low[j] <= guard) if up else (bars.high[j] >= guard):
                done = -1.0
                break
            if (bars.high[j] >= target) if up else (bars.low[j] <= target):
                done = reward
                break
        if done is None:
            j = min(n, i + 1 + patience) - 1
            done = (float(bars.close[j]) - entry) * (1.0 if up else -1.0) / risk
        # Two spreads: the entry bar's and the exit bar's, each as quoted.
        paid = (feed.spread_points[i] + feed.spread_points[j]) * feed.point / risk
        nets.append(done - paid)
        grosses.append(done)
        costs.append(paid)
        ats.append(i)
        sides.append(1 if up else -1)
        at = int(np.searchsorted(firing, j + 1))
    return Trades(
        net=np.asarray(nets),
        gross=np.asarray(grosses),
        cost=np.asarray(costs),
        at=np.asarray(ats, dtype=np.int64),
        side=np.asarray(sides, dtype=np.int8),
    )


def trend_of(symbol: str, frame: str, length: int, where: Path = WIDE) -> tuple[np.ndarray, np.ndarray]:
    """`(close times, +1 / -1 / 0)` for one higher frame, from **closed** bars.

    **The stamp returned is the bar's close, not its open**, and that is the
    whole of the look-ahead question. The broker stamps a rate row with the
    bar's **opening** time, so an H4 row stamped 12:00 is not knowable until
    16:00 - using it at 12:05 would read four hours of the future, and on a
    trend filter that is exactly the four hours the filter is supposed to be
    agnostic about. `open-gap-filters-are-lookahead` is the same error on this
    desk costed at +0.50R a trade.

    Trend is `close > SMA(length)` against `close < SMA(length)`, and 0 where
    the average is not yet full - not a guess either way.
    """
    block = _packed(where).get((symbol, frame))
    if block is None or block["close"].size < length + 2:
        return np.asarray([]), np.asarray([])
    close = block["close"]
    slow = moving(close, length)
    side = np.where(np.isfinite(slow), np.sign(close - slow), 0.0)
    width = {"H4": 4 * 3600.0, "D1": 24 * 3600.0}.get(frame, 0.0)
    return block["ts"] + width, side.astype(np.int8)


def agrees(took: Trades, stamps: np.ndarray, filters: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    """Which trades had every higher frame already pointing their way.

    `searchsorted(..., "right") - 1` is the last higher-frame bar whose **close**
    is at or before the entry, so a trade taken at 12:05 reads the H4 that
    closed at 12:00 and never the one still forming.
    """
    keep = np.ones(took.net.size, dtype=bool)
    for closes, side in filters:
        if closes.size == 0:
            return np.zeros(took.net.size, dtype=bool)
        where = np.searchsorted(closes, stamps, side="right") - 1
        ok = where >= 0
        found = np.zeros(took.net.size, dtype=np.int8)
        found[ok] = side[where[ok]]
        keep &= found == took.side
    return keep


def conditions(feed: Feed, took: Trades) -> dict[str, np.ndarray]:
    """The market state at each entry: the cut the operator asked for.

    Four readings, each known at the entry bar's close:

    * **volatility** - ATR over its own trailing 480-bar median, so "loud or
      quiet for this feed lately" rather than an absolute that drifts.
    * **session** - the UTC hour, because an index's day has an auction in it
      and `seasonality-belongs-on-q` measures the intraday pattern as a
      volatility effect three times its quiet level on FX.
    * **spread** - the bar's own quoted spread over its trailing median. The
      only direct read on how dear the venue is at that moment.
    * **quoting** - `tick_volume` over its trailing median. Activity, not
      volume: `real_volume` is 0 on every row.
    """
    bars = feed.bars
    band = atr(bars)
    window = 480

    def relative(values: np.ndarray) -> np.ndarray:
        out = np.full(values.size, np.nan)
        if values.size > window:
            stack = np.lib.stride_tricks.sliding_window_view(values[:-1], window)
            with np.errstate(invalid="ignore", divide="ignore"):
                middle = np.nanmedian(stack, axis=1)
                out[window:] = values[window:] / np.where(middle > 0, middle, np.nan)
        return out

    hour = ((bars.ts // 3_600_000_000_000) % 24).astype(float)
    return {
        "volatility": relative(band)[took.at],
        "session": hour[took.at],
        "spread": relative(feed.spread_points)[took.at],
        "quoting": relative(feed.quotes)[took.at],
    }


def cut(name: str, values: np.ndarray, net: np.ndarray, cells: int = 4) -> None:
    """One condition, by quantile, with the mean net R each band was followed by."""
    ok = np.isfinite(values) & np.isfinite(net)
    if ok.sum() < 40:
        return
    v, y = values[ok], net[ok]
    edges = np.percentile(v, np.linspace(0, 100, cells + 1))
    parts = []
    for c in range(cells):
        lo, hi = edges[c], edges[c + 1]
        pick = (v >= lo) & (v < hi) if c < cells - 1 else (v >= lo)
        if pick.sum() < 10:
            continue
        spread = y[pick].std(ddof=1) / np.sqrt(pick.sum()) if pick.sum() > 1 else np.nan
        parts.append(f"{lo:5.2f}+ n{pick.sum():<4} {y[pick].mean():+.4f}+-{1.96 * spread:.3f}")
    print(f"      {name:<11} " + "   ".join(parts))


def session_cut(values: np.ndarray, net: np.ndarray) -> None:
    """Net R by six-hour block, which is where an index's auction shows up."""
    ok = np.isfinite(values) & np.isfinite(net)
    if ok.sum() < 40:
        return
    v, y = values[ok], net[ok]
    parts = []
    for lo in (0, 6, 12, 18):
        pick = (v >= lo) & (v < lo + 6)
        if pick.sum() < 10:
            continue
        parts.append(f"{lo:02d}-{lo + 6:02d}h n{pick.sum():<4} {y[pick].mean():+.4f}")
    print("      session     " + "   ".join(parts))


def trim(feed: Feed, days: float) -> Feed:
    """The last `days` of a feed, keeping the microstructure columns aligned."""
    cutoff = int(feed.bars.ts[-1]) - int(days * 86_400_000_000_000)
    keep = feed.bars.ts >= cutoff
    bars = feed.bars
    return Feed(
        bars=Candles(
            symbol=bars.symbol,
            frame=bars.frame,
            ts=bars.ts[keep],
            open=bars.open[keep],
            high=bars.high[keep],
            low=bars.low[keep],
            close=bars.close[keep],
        ),
        spread_points=feed.spread_points[keep],
        quotes=feed.quotes[keep],
        point=feed.point,
    )


def shuffle_days(feed: Feed, seed: int) -> Feed:
    """Whole days reordered, re-based to join up, with their spreads carried.

    The twin that matters: every bar's shape and **its own quoted spread** stay
    attached, so a result that survives is not a cost artefact. Days rather
    than bars, because `re-hung-bar-shapes-break-bar-derived-nulls` invalidates
    a null built by re-hanging shapes for anything read off a wick - and a
    pullback reads an average and a stop off them.
    """
    bars = feed.bars
    day = bars.ts // 86_400_000_000_000
    edges = np.flatnonzero(np.diff(day)) + 1
    blocks = np.split(np.arange(bars.ts.size), edges)
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(blocks))
    opens, highs, lows, closes, spreads, quotes = [], [], [], [], [], []
    carry = float(bars.close[0])
    for index in order:
        block = blocks[index]
        shift = carry - float(bars.open[block[0]])
        opens.append(bars.open[block] + shift)
        highs.append(bars.high[block] + shift)
        lows.append(bars.low[block] + shift)
        closes.append(bars.close[block] + shift)
        spreads.append(feed.spread_points[block])
        quotes.append(feed.quotes[block])
        carry = float(closes[-1][-1])
    return Feed(
        bars=Candles(
            symbol=bars.symbol + "~shuffled",
            frame=bars.frame,
            ts=bars.ts,
            open=np.concatenate(opens),
            high=np.concatenate(highs),
            low=np.concatenate(lows),
            close=np.concatenate(closes),
        ),
        spread_points=np.concatenate(spreads),
        quotes=np.concatenate(quotes),
        point=feed.point,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--frames", default="M1,M5,M15")
    parser.add_argument("--windows", default="14,7")
    parser.add_argument("--ma", default="20,50")
    parser.add_argument("--reach", default="5,10")
    parser.add_argument("--stop", type=float, default=1.0)
    parser.add_argument("--reward", default="1,2")
    parser.add_argument("--patience", type=int, default=96)
    parser.add_argument("--least", type=int, default=30)
    args = parser.parse_args()

    names = [s.strip() for s in args.symbols.split(",") if s.strip()]
    print(
        f"ma_pullback on {len(names)} indices  frames {args.frames}  windows {args.windows}d  "
        f"stop {args.stop} ATR  each trade charged its own two quoted spreads"
    )
    for frame in (f.strip() for f in args.frames.split(",") if f.strip()):
        for days in (float(d) for d in args.windows.split(",") if d.strip()):
            pooled: dict[str, list[np.ndarray]] = {"real": [], "shuffled": []}
            states: dict[str, list[np.ndarray]] = {}
            costs: list[np.ndarray] = []
            per_symbol = []
            for symbol in names:
                whole = read(symbol, frame, 0.0)
                if whole is None:
                    continue
                feed = read(symbol, frame, point_of(symbol, float(whole.bars.close[-1])))
                if feed is None:
                    continue
                window = trim(feed, days)
                if len(window.bars) < 600:
                    continue
                for arm, source in (("real", window), ("shuffled", shuffle_days(window, 23))):
                    best = None
                    for length in (int(v) for v in args.ma.split(",")):
                        for reach in (int(v) for v in args.reach.split(",")):
                            for reward in (float(v) for v in args.reward.split(",")):
                                took = pullback(
                                    source, length, reach, args.stop, reward, args.patience
                                )
                                if took.net.size < args.least:
                                    continue
                                pooled[arm].append(took.net)
                                if arm == "real":
                                    costs.append(took.cost)
                                    for key, value in conditions(source, took).items():
                                        states.setdefault(key, []).append(value)
                                if best is None or took.net.mean() > best[0]:
                                    best = (float(took.net.mean()), length, reach, reward, took.net.size)
                    if arm == "real" and best is not None:
                        per_symbol.append((symbol, *best))
            if not pooled["real"]:
                print(f"\n  {frame}, {days:g}d: nothing reached {args.least} trades")
                continue
            real = np.concatenate(pooled["real"])
            twin = np.concatenate(pooled["shuffled"]) if pooled["shuffled"] else np.asarray([])
            paid = np.concatenate(costs)
            spread = real.std(ddof=1) / np.sqrt(real.size)
            print(
                f"\n  {frame}, last {days:g} days - {real.size:,} trades over every cell\n"
                f"    net {real.mean():+.4f} +/- {1.96 * spread:.4f}   "
                f"gross {real.mean() + paid.mean():+.4f}   cost {paid.mean():.4f}R   "
                f"shuffled twin {twin.mean():+.4f}" + ("" if twin.size else " (none)")
            )
            for symbol, mean, length, reach, reward, n in sorted(per_symbol, key=lambda r: -r[1]):
                print(f"      best on {symbol:<16} ma{length} mom{reach} R{reward:g}  n{n:<5} {mean:+.4f}")
            print("    the conditions, by quantile of each reading at entry")
            for key in ("volatility", "spread", "quoting"):
                if key in states:
                    cut(key, np.concatenate(states[key]), real)
            if "session" in states:
                session_cut(np.concatenate(states["session"]), real)


if __name__ == "__main__":
    main()
