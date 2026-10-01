"""The simulation: signals in, trades out, charged what the broker would charge.

## A strategy is a function from bars to signals

    def strategy(bars: pd.DataFrame, book: Book) -> pd.DataFrame:
        # one row per signal:
        #   i       the bar at whose close the signal is known (it fills at bar i + 1's open)
        #   side    +1 long, -1 short
        #   stop    stop distance in price units (> 0)
        #   target  target distance in price units (0 or NaN: none)
        #   hold    bars to hold at most (0 or NaN: until stop, target or the data ends)
        #   risk    optional: fraction of equity to risk, overriding `run(risk=...)`

The function sees the whole frame, so it *could* look ahead. `audit.lookahead` re-runs it on
truncated history and fails any strategy whose past signals change when the future is removed.

## Fills (bar mode)

MT5 bars are bid. The ask is rebuilt from the bar's spread.

  entry       long at the next open's ask, short at its bid, plus `slippage_points`
  long exit   on the bid: stop if low <= stop, target if high >= target
  short exit  on the ask: stop if high + spread >= stop, target if low + spread <= target
  gap         a bar opening beyond a level fills at that open, not at the level
  both        a bar touching both is the stop, unless ticks say the target came first
  time        at the close of the last held bar, on the exit side
  stop slip   `slippage_points` plus `stop_slip_frac` of the stop distance (spike sides)

A CFD round trip pays the spread once: a long at entry (buys the ask), a short at exit.

## Money

Sizing is production's own `trading.sizing.lots`: risk a fraction of equity, snapped *down* to
the broker's lot grid, refused below the minimum lot (counted, not hidden). P&L converts price
to money with the spec's tick value, as the terminal does. Swap is production's
`trading.swap.expected` (charges only; credits are ignored, which is conservative). R is net
money over the money the stop was sized to lose.

The tick value is today's; a JPY- or CHF-quoted symbol's money P&L therefore uses today's
conversion rate. R is free of that, and R is the unit this desk judges in.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from till_infinity.trading import swap as swap_rules
from till_infinity.trading.models import Side
from till_infinity.trading.sizing import lots

from .data import Book

SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400,
           "1d": 86400}


@dataclass
class Signal:
    """One signal, for strategies that would rather build a list than a frame."""

    i: int
    side: int
    stop: float
    target: float = 0.0
    hold: int = 0
    risk: float = 0.0


@dataclass
class Costs:
    #: Used where a bar carries no spread (SEQLAB bars, CSV without one).
    spread_points: float = 0.0
    #: Scale the recorded spread: MT5 stores a bar's lowest spread on most servers.
    spread_mult: float = 1.0
    spread_floor_points: float = 0.0
    #: Account money per lot per side.
    commission_per_lot: float = 0.0
    slippage_points: float = 0.0
    #: Extra stop slippage as a share of the stop distance (Boom/Crash spike sides: 10-19R).
    stop_slip_frac: float = 0.0
    swap: bool = True
    #: "auto": a trade's fills come from ticks when the book's ticks cover it, else bars.
    #: "ticks": ticks or nothing (uncovered signals are refused). "bars": bars only.
    fill: str = "auto"


def _frame(signals) -> pd.DataFrame:
    if isinstance(signals, pd.DataFrame):
        df = signals.copy()
    else:
        df = pd.DataFrame([s.__dict__ for s in signals or []])
    for col, default in (("target", 0.0), ("hold", 0), ("risk", 0.0), ("entry", np.nan),
                         ("expires", 1), ("oco", -1), ("trail", 0.0)):
        if col not in df:
            df[col] = default
    if df.empty:
        return pd.DataFrame(columns=["i", "side", "stop", "target", "hold", "risk", "entry",
                                     "expires", "oco", "trail"])
    df = df.fillna({"target": 0.0, "hold": 0, "risk": 0.0, "expires": 1, "oco": -1,
                    "trail": 0.0})
    df["i"] = df["i"].astype(int)
    df["side"] = np.sign(df["side"]).astype(int)
    bad = (df["side"] == 0) | ~(df["stop"] > 0)
    if bad.any():
        raise ValueError(f"{int(bad.sum())} signals have no side or a stop <= 0")
    return df.sort_values("i").reset_index(drop=True)


def spreads(book: Book, costs: Costs) -> np.ndarray:
    pts = book.bars["spread"].to_numpy(float)
    pts = np.where(np.isnan(pts), costs.spread_points, pts) * costs.spread_mult
    return np.maximum(pts, costs.spread_floor_points) * book.spec.point


def _first_tick(book: Book, t0: float, t1: float, side: int, stop: float, target: float) -> str:
    """Which level a bar's ticks reached first; "stop" when ticks cannot say."""
    if book.ticks is None or book.ticks.empty:
        return "stop"
    tk = book.ticks
    a, b = np.searchsorted(tk["ts_ms"].to_numpy(), [t0 * 1000, t1 * 1000])
    if b <= a:
        return "stop"
    px = (tk["bid"] if side > 0 else tk["ask"]).to_numpy()[a:b]
    hit_s = np.nonzero(px <= stop if side > 0 else px >= stop)[0]
    hit_t = np.nonzero(px >= target if side > 0 else px <= target)[0]
    if len(hit_t) and (not len(hit_s) or hit_t[0] < hit_s[0]):
        return "target"
    return "stop"


def _sides(book: Book, sp: np.ndarray):
    """Bid and ask OHLC arrays. The ask is the bar's own (exact when built from ticks) moved by
    whatever `Costs` adds to the recorded spread (fallback, multiple, floor)."""
    b = book.bars
    bid = [b[k].to_numpy(float) for k in ("open", "high", "low", "close")]
    raw = np.nan_to_num(b["spread_price"].to_numpy(float))
    extra = sp - raw
    ask = []
    for k, x in zip(("open", "high", "low", "close"), bid, strict=True):
        col = b[f"ask_{k}"].to_numpy(float)
        ask.append(np.where(np.isnan(col), x + sp, col + extra))
    return bid, ask


def walk(book: Book, j: int, side: int, stop_d: float, target_d: float, hold: int,
         sp: np.ndarray, costs: Costs, sides=None, fill: float | None = None,
         trail: float = 0.0) -> dict | None:
    """One trade from bar j's open (or a resting order's `fill` inside bar j) to its exit, on
    bars. None when there is no bar j. On a resting order's fill bar, a stop inside that bar's
    range counts: the bar cannot say whether the low came before the fill, so it is assumed to.

    `trail` > 0 trails the stop that far behind the best exit-side price of the bars already
    *completed* (never the bar being checked: its high may have come after its low). The stop only
    ever tightens; a trailed stop that is hit exits as "trail"."""
    b = book.bars
    n = len(b)
    if j >= n:
        return None
    (o, h, l, c), (ao, ah, al, ac) = sides or _sides(book, sp)
    pt = book.spec.point
    slip = costs.slippage_points * pt
    if fill is not None and not np.isnan(fill):
        entry = fill
    else:
        entry = ao[j] + slip if side > 0 else o[j] - slip
    stop = entry - side * stop_d
    target = entry + side * target_d if target_d > 0 else np.nan
    stop_slip = slip + costs.stop_slip_frac * stop_d
    last = n - 1 if not hold else min(n - 1, j + int(hold) - 1)
    step = SECONDS.get(book.interval, 0)
    # the exit side: a long sells the bid, a short buys the ask
    xo, xh, xl, xc = (o, h, l, c) if side > 0 else (ao, ah, al, ac)
    base = dict(entry=entry, sp_entry=ao[j] - o[j], fill="bars")
    first_stop, best = stop, entry
    for k in range(j, last + 1):
        if trail > 0 and k > j:
            stop = max(stop, best - trail) if side > 0 else min(stop, best + trail)
        why = "stop" if stop == first_stop else "trail"
        if k > j:
            if (side > 0 and xo[k] <= stop) or (side < 0 and xo[k] >= stop):
                return base | dict(exit_bar=k, exit=xo[k] - side * stop_slip, reason=why + "_gap",
                                   sp_exit=ao[k] - o[k])
            if target_d > 0 and ((side > 0 and xo[k] >= target) or (side < 0 and xo[k] <= target)):
                return base | dict(exit_bar=k, exit=xo[k], reason="target_gap", sp_exit=ao[k] - o[k])
        hit_s = xl[k] <= stop if side > 0 else xh[k] >= stop
        hit_t = target_d > 0 and (xh[k] >= target if side > 0 else xl[k] <= target)
        if hit_s and hit_t:
            first = _first_tick(book, b["ts"].iat[k], b["ts"].iat[k] + step, side, stop, target)
            hit_s, hit_t = first == "stop", first == "target"
        if hit_s:
            return base | dict(exit_bar=k, exit=stop - side * stop_slip, reason=why,
                               sp_exit=ac[k] - c[k])
        if hit_t:
            return base | dict(exit_bar=k, exit=target, reason="target", sp_exit=ac[k] - c[k])
        best = max(best, xh[k]) if side > 0 else min(best, xl[k])
    reason = "time" if hold and last == j + hold - 1 else "end"
    return base | dict(exit_bar=last, exit=xc[last], reason=reason, sp_exit=ac[last] - c[last])


def _covered(book: Book, t0: float, t1: float) -> tuple[int, int] | None:
    """Tick indices [a, z) spanning epoch seconds [t0, t1), or None if the ticks don't cover it."""
    tk = book.ticks
    if tk is None or tk.empty:
        return None
    ms = tk["ts_ms"].to_numpy()
    if ms[0] > t0 * 1000 + 60_000 or ms[-1] < t1 * 1000 - 60_000:
        return None
    a, z = np.searchsorted(ms, [t0 * 1000, t1 * 1000])
    return (int(a), int(z)) if z > a else None


def walk_ticks(book: Book, j: int, side: int, stop_d: float, target_d: float, hold: int,
               costs: Costs, trail: float = 0.0, start_ms: float | None = None,
               entry: float | None = None) -> dict | None:
    """One trade on real ticks: in at the first tick of bar j (the ask for a long), or at a resting
    order's fill tick (`start_ms`, `entry`); out on the first tick whose exit side (the bid for a
    long, the ask for a short) reaches a level - at that tick's price, so a jump through a stop
    costs what it cost. `trail` trails the stop behind the best exit-side price of the ticks
    already seen. None if ticks don't cover it."""
    b = book.bars
    step = SECONDS.get(book.interval, 0)
    n = len(b)
    if j >= n:
        return None
    last = n - 1 if not hold else min(n - 1, j + int(hold) - 1)
    t0 = b["ts"].iat[j] if start_ms is None else start_ms / 1000
    span = _covered(book, t0, b["ts"].iat[last] + step)
    if span is None:
        return None
    a, z = span
    tk = book.ticks
    ms = tk["ts_ms"].to_numpy()
    bid, ask = tk["bid"].to_numpy()[a:z], tk["ask"].to_numpy()[a:z]
    slip = costs.slippage_points * book.spec.point
    if entry is None:
        entry = (ask[0] + slip) if side > 0 else (bid[0] - slip)
    stop = entry - side * stop_d
    px = bid if side > 0 else ask
    if trail > 0:
        if side > 0:
            best = np.r_[entry, np.maximum.accumulate(np.maximum(px, entry))[:-1]]
            path = np.maximum(stop, best - trail)
        else:
            best = np.r_[entry, np.minimum.accumulate(np.minimum(px, entry))[:-1]]
            path = np.minimum(stop, best + trail)
    else:
        path = np.full(len(px), stop)
    hit_s = np.nonzero(px <= path if side > 0 else px >= path)[0]
    hit_t = (np.nonzero(px >= entry + target_d if side > 0 else px <= entry - target_d)[0]
             if target_d > 0 else np.array([], int))
    s0 = hit_s[0] if len(hit_s) else len(px)
    g0 = hit_t[0] if len(hit_t) else len(px)
    k = min(s0, g0, len(px) - 1)
    if s0 <= g0 and s0 < len(px):
        price = px[s0] - side * costs.stop_slip_frac * stop_d - side * slip
        reason = "stop" if path[s0] == stop else "trail"
    elif g0 < len(px):
        price, reason = px[g0], "target"
    else:
        price, reason = px[-1], ("time" if hold and last == j + hold - 1 else "end")
    at = ms[a + k] // 1000
    exit_bar = int(min(max(np.searchsorted(b["ts"].to_numpy(), at, side="right") - 1, j), last))
    return dict(entry=entry, sp_entry=ask[0] - bid[0], exit_bar=exit_bar, exit=price,
                reason=reason, sp_exit=ask[k] - bid[k], fill="ticks")


def _tick_fill(book: Book, i: int, expires: int, side: int, level: float, costs: Costs):
    """A resting stop order on ticks: the first tick after bar i whose entry side reaches the level,
    at that tick's price. (fill_ms, price) or None if ticks don't cover the window or it never
    fills."""
    b = book.bars
    n = len(b)
    if i + 1 >= n:
        return None
    step = SECONDS.get(book.interval, 0)
    end = min(n - 1, i + int(expires))
    span = _covered(book, b["ts"].iat[i + 1], b["ts"].iat[end] + step)
    if span is None:
        return None
    a, z = span
    tk = book.ticks
    px = (tk["ask"] if side > 0 else tk["bid"]).to_numpy()[a:z]
    hit = np.nonzero(px >= level if side > 0 else px <= level)[0]
    if not len(hit):
        return (np.nan, np.nan)  # covered and never reached: no fill
    slip = costs.slippage_points * book.spec.point
    return float(tk["ts_ms"].to_numpy()[a + hit[0]]), float(px[hit[0]] + side * slip)


def resolve(sig: pd.DataFrame, book: Book, sides, costs: Costs) -> pd.DataFrame:
    """Market signals fill at bar i + 1's open. Resting stop orders (`entry` a price level) fill
    on the first bar within `expires` whose *entry*-side price reaches the level: a buy stop when the ask's high reaches it, a sell stop when the bid's low does; at
    the level, or at the open when the bar gaps through it. Orders sharing an `oco` id cancel each
    other: the first to fill wins. When both legs fill in the same bar, the bar cannot say which
    came first, and the leg against the bar's close is taken - the whipsaw, the worse case.

    Returns one row per order that fills: the signal's columns plus `j` (fill bar) and `fill`."""
    (o, h, l, c), (ao, ah, al, ac) = sides
    n = len(o)
    b_ts = book.bars["ts"].to_numpy()
    slip = costs.slippage_points * book.spec.point
    out = []
    for row in sig.itertuples(index=False):
        r = row._asdict()
        if np.isnan(row.entry):
            r.update(j=row.i + 1, fill=np.nan, fill_ms=np.nan)
            out.append(r)
            continue
        a, z = row.i + 1, min(n, row.i + 1 + int(row.expires))
        if a >= n:
            continue
        L = row.entry
        if costs.fill in ("auto", "ticks") and book.ticks is not None:
            got = _tick_fill(book, row.i, int(row.expires), int(row.side), L, costs)
            if got is not None:
                if np.isnan(got[0]):
                    continue  # the ticks say it never filled
                k_ms = int(np.searchsorted(b_ts, got[0] / 1000, side="right") - 1)
                r.update(j=k_ms, fill=got[1], fill_ms=got[0])
                out.append(r)
                continue
        if row.side > 0:
            hit = np.nonzero(ah[a:z] >= L)[0]
            if not len(hit):
                continue
            k = a + hit[0]
            px = max(L, ao[k]) + slip
        else:
            hit = np.nonzero(l[a:z] <= L)[0]
            if not len(hit):
                continue
            k = a + hit[0]
            px = min(L, o[k]) - slip
        r.update(j=k, fill=px, fill_ms=np.nan)
        out.append(r)
    df = pd.DataFrame(out)
    if df.empty:
        return df
    grouped = df[df["oco"] >= 0]
    keep = df[df["oco"] < 0]
    winners = []
    for _, g in grouped.groupby("oco"):
        if g["fill_ms"].notna().all():  # ticks say which filled first
            winners.append(g.sort_values("fill_ms").head(1))
            continue
        g = g.sort_values("j")
        first = g[g["j"] == g["j"].iloc[0]]
        if len(first) > 1:  # both legs in one bar: the whipsaw
            k = int(first["j"].iloc[0])
            against = -1 if c[k] >= o[k] else 1
            first = first[first["side"] == against].head(1)
        winners.append(first.head(1))
    df = pd.concat([keep, *winners], ignore_index=True) if winners else keep
    return df.sort_values(["j", "i"]).reset_index(drop=True)


def run(books: list[Book] | Book, strategy, costs: Costs | None = None, *, equity: float = 10_000.0,
        risk: float = 0.005, max_open: int = 0, one_per_symbol: bool = True, allow=None,
        signals: dict[str, pd.DataFrame] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run `strategy` over `books`. Returns (trades, refused).

    `allow(ts, book) -> bool` vetoes entries (quiet hours, the rollover, news). `signals` skips
    calling the strategy and uses these frames instead, keyed by symbol (the nulls use it).
    """
    books = [books] if isinstance(books, Book) else list(books)
    costs = costs or Costs()
    candidates, refused = [], []
    for book in books:
        sig = _frame(signals[book.symbol] if signals else strategy(book.bars.copy(), book))
        sp = spreads(book, costs)
        sides = _sides(book, sp)
        ts = book.bars["ts"].to_numpy()
        busy_until = -1
        sig = resolve(sig, book, sides, costs)
        for row in sig.itertuples(index=False):
            j = int(row.j)
            if j >= len(ts):
                continue
            if one_per_symbol and j <= busy_until:
                refused.append(dict(symbol=book.symbol, ts=ts[j], why="position open"))
                continue
            if allow is not None and not allow(int(ts[j]), book):
                refused.append(dict(symbol=book.symbol, ts=ts[j], why="vetoed"))
                continue
            got = None
            resting = not np.isnan(row.fill)
            trail = float(getattr(row, "trail", 0.0) or 0.0)
            fill_ms = getattr(row, "fill_ms", np.nan)
            if costs.fill in ("auto", "ticks") and (not resting or not np.isnan(fill_ms)):
                got = walk_ticks(book, j, row.side, row.stop, row.target, int(row.hold), costs,
                                 trail=trail,
                                 start_ms=None if np.isnan(fill_ms) else fill_ms,
                                 entry=row.fill if resting else None)
                if got is None and costs.fill == "ticks":
                    refused.append(dict(symbol=book.symbol, ts=ts[j], why="no ticks"))
                    continue
            if got is None:
                got = walk(book, j, row.side, row.stop, row.target, int(row.hold), sp, costs,
                           sides, fill=row.fill if resting else None, trail=trail)
            if got is None:
                continue
            busy_until = got["exit_bar"]
            step = SECONDS.get(book.interval, 0)
            candidates.append(dict(symbol=book.symbol, book=book, side=row.side, signal_bar=row.i,
                                   entry_bar=j, entry_ts=int(ts[j]),
                                   exit_ts=int(ts[got["exit_bar"]]) + step,
                                   stop_d=row.stop, target_d=row.target, hold=int(row.hold),
                                   risk=row.risk or risk, **got))
    # the portfolio: in time order, sized on the equity realised so far
    candidates.sort(key=lambda t: (t["entry_ts"], t["symbol"]))
    trades, open_, cash = [], [], equity
    for t in candidates:
        still = []
        for x in open_:
            if x["exit_ts"] <= t["entry_ts"]:
                cash += x["net"]
            else:
                still.append(x)
        open_ = still
        if max_open and len(open_) >= max_open:
            refused.append(dict(symbol=t["symbol"], ts=t["entry_ts"], why="max open"))
            continue
        book = t.pop("book")
        spec = book.spec
        slip_frac = costs.stop_slip_frac + (costs.slippage_points * spec.point / t["stop_d"])
        size = lots(spec, equity=cash, risk_fraction=t["risk"], stop_distance=t["stop_d"],
                    slippage=slip_frac)
        if not size.ok:
            refused.append(dict(symbol=t["symbol"], ts=t["entry_ts"], why=size.reason[:60]))
            continue
        per_price = spec.tick_value / spec.tick_size * size.volume  # money per 1.0 of price
        side, entry = t["side"], t["entry"]
        gross_px = side * (t["exit"] - entry)
        swap_px = 0.0
        if costs.swap:
            swap_px = swap_rules.expected(spec, book.feed, Side.BUY if side > 0 else Side.SELL,
                                          entry, t["entry_ts"], t["exit_ts"] - t["entry_ts"])
        commission = 2 * costs.commission_per_lot * size.volume
        net = gross_px * per_price - swap_px * per_price - commission
        spread_px = t["sp_entry"] if side > 0 else t["sp_exit"]
        t.update(volume=size.volume, entry=entry, risk_money=size.risk_money,
                 gross=(gross_px + spread_px) * per_price, spread_cost=spread_px * per_price,
                 swap_cost=swap_px * per_price, commission=commission, net=net,
                 R=net / size.risk_money, equity_before=cash)
        trades.append(t)
        open_.append(t)
    out = pd.DataFrame(trades)
    if not out.empty:
        out["entry_time"] = pd.to_datetime(out["entry_ts"], unit="s", utc=True)
        out["exit_time"] = pd.to_datetime(out["exit_ts"], unit="s", utc=True)
    return out, pd.DataFrame(refused)
