"""Backtest every imported idea on the broker's bars with mt5bt, against a coin twin and walks.

Pre-registered (2026-10-02), before any run.

  data      broker bars to today (fetch: harness/ideas_fetch.sh): 12 FX pairs, gold, silver, BTC,
            ETH, SOL, 7 indices, 2 oils, 8 Deriv indices; 15m, 1h, 4h, 1d
  setups    setups.py: each idea's entry and structural invalidation, both sides by mirroring
  exits     trail   no target; a trailing stop 2 ATR behind the best price ("the market decides")
            t4      a target at 4R, no trail
            t10     a target at 10R, no trail
            src     the source's own geometry where it fixed one (zma: target the mean)
            all exits hold 300 bars at most; one position per symbol per setup
  costs     the broker's per-bar spread x 1.3 (MT5 stores a bar's lowest), swap, the lot grid;
            a resting limit fills only when price trades one spread through it
  controls  coin   the same fills, replayed at market with a random side, same stop and exit
            walk   the same rule on GARCH(1,1) t walks with EURUSD's contract, 6 per timeframe
  measures  per (setup, tag, exit, family, interval): n, net R a trade with a day-bootstrap CI,
            both halves of the period, hit rate, P(R >= 4), P(R >= 10), the coin's and the walk's
  passes    net R > 0 in both halves; beats its coin twin with day-bootstrap p < 0.05 after
            Benjamini-Hochberg across every cell; the walk's net R below half of it; n >= 30.
            Deriv cells with jumps (Boom, Crash, Jump) are flagged: bar fills miss the jump

  OUT=... MT5BT_DB=... python research/ideas/run.py
"""
from __future__ import annotations

import warnings
import os
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import prims as P  # noqa: E402
import setups as S  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/ideas"))
warnings.filterwarnings("ignore", category=FutureWarning)
DB = os.environ.get("MT5BT_DB")
SEC = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}
UP = {"5m": ("15m", "1h"), "15m": ("1h", "4h", "1d"), "1h": ("4h", "1d"), "4h": ("1d",), "1d": ()}
INTERVALS = tuple(os.environ.get("INTERVALS", "15m,1h,4h,1d").split(","))
ONLY = [s for s in os.environ.get("SETUPS", "").split(",") if s]
TRAIL_ATR, MAXHOLD, SPREAD_MULT = 2.0, 300, 1.3
EXITS = tuple(os.environ.get("EXITS", "trail,t4,t10,src").split(","))
FAMILY = {
    **{s: "fx" for s in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
                         "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "USDCNH")},
    "XAUUSD": "metal", "XAGUSD": "metal", "BTCUSD": "crypto", "ETHUSD": "crypto", "SOLUSD": "crypto",
    **{s: "index" for s in ("US SP 500", "US Tech 100", "Wall Street 30", "Germany 40", "UK 100",
                            "Japan 225", "Australia 200")},
    "US Oil": "energy", "UK Brent Oil": "energy",
    **{s: "deriv" for s in ("Volatility 75 Index", "Volatility 25 Index", "Jump 50 Index",
                            "Boom 1000 Index", "Crash 1000 Index", "Step Index",
                            "Range Break 100 Index", "Drift Switch Index 10")},
}
#: The broker's other crypto CFDs: coins no idea here was built or scored on - the validation set.
FRESH = ("AAVUSD,ADAUSD,ALGUSD,APEUSD,APTUSD,AVAUSD,BATUSD,BCHUSD,BNBUSD,COMUSD,DOGUSD,DOTUSD,DSHUSD,"
         "ETCUSD,FILUSD,IMXUSD,IOTUSD,LNKUSD,LTCUSD,MLNUSD,NEOUSD,NERUSD,SANUSD,SHBUSD,TRUUSD,TRXUSD,"
         "UNIUSD,XLMUSD,XMRUSD,XRPUSD,XTZUSD,ZECUSD").split(",")
FAMILY.update({s: "crypto" for s in FRESH})
FAMILY.update({"XPTUSD": "metal", "XPDUSD": "metal", "XCUUSD": "metal",
               **{s: "deriv" for s in ("Volatility 10 Index", "Volatility 50 Index", "Volatility 100 Index",
                                       "Step Index 200", "Step Index 500", "Drift Switch Index 20",
                                       "Drift Switch Index 30")}})
PEERS = ("BTCUSD", "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD")


def spread_floor(sym, spec) -> float:
    """The spread a trade actually pays, in points. MT5 bars carry the bar's *lowest* spread, which
    is 0 on most of this broker's bars, so the floor is the median spread of the symbol's ticks
    where we hold them, else the broker's quoted spread from its symbol info."""
    import json
    import sqlite3
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT ask - bid FROM ticks WHERE symbol = ? ORDER BY ts_ms DESC LIMIT 200000",
                            (sym,)).fetchall()
        if len(rows) > 1000:
            return float(np.median([r[0] for r in rows]) / spec.point)
        raw = conn.execute("SELECT raw FROM specs WHERE symbol = ?", (sym,)).fetchone()
        quoted = (json.loads(raw[0]) or {}).get("spread") if raw and raw[0] else None
        return float(quoted) if quoted else 0.0
    finally:
        conn.close()


def load(sym, iv):
    from mt5bt import load_bars
    try:
        df = load_bars(sym, iv, "sqlite", DB)
    except (ValueError, OSError):
        return None
    return df if len(df) >= 400 else None


def focus_hold(sig: pd.DataFrame, fired_up: np.ndarray, fired_dn: np.ndarray) -> np.ndarray:
    """Bars from each signal to the first FOCuS changepoint against it: the market's own say on when
    the move is over (a long ends at the first downward change in mean, a short at the first upward)."""
    up, dn = np.flatnonzero(fired_up), np.flatnonzero(fired_dn)
    out = np.full(len(sig), MAXHOLD)
    for k, (i, side) in enumerate(zip(sig["i"].to_numpy(int), sig["side"].to_numpy(int))):
        against = dn if side > 0 else up
        j = np.searchsorted(against, i, side="right")
        if j < len(against):
            out[k] = min(MAXHOLD, max(1, int(against[j] - i)))
    return out


def to_mt5(sig: pd.DataFrame, df: pd.DataFrame, a: np.ndarray, exit_: str, min_stop: float = 0.0,
           focus=None) -> pd.DataFrame:
    """Setup rows -> mt5bt signals: stop distance from the entry reference, the exit attached."""
    if sig.empty:
        return sig
    c = df["close"].to_numpy()
    i = sig["i"].to_numpy(int)
    ok = (i >= 0) & (i < len(df) - 1)
    sig = sig[ok].copy()
    i = sig["i"].to_numpy(int)
    entry = sig["entry"].to_numpy(float) if "entry" in sig else np.full(len(sig), np.nan)
    ref = np.where(np.isnan(entry), c[i], entry)
    side = sig["side"].to_numpy(int)
    stop = side * (ref - sig["stop_px"].to_numpy(float))
    # No stop inside the spread: a trader puts it at least two spreads away, so tighter ones widen.
    stop = np.where(stop > 0, np.maximum(stop, min_stop), stop)
    good = (stop > 0) & np.isfinite(stop) & (a[i] > 0) & (stop <= 15 * a[i])
    sig, stop, ref, i, side = sig[good].copy(), stop[good], ref[good], i[good], side[good]
    sig["stop"] = stop
    hold = sig["hold"].to_numpy(float) if "hold" in sig else np.full(len(sig), np.nan)
    sig["hold"] = np.where(np.isfinite(hold), hold, MAXHOLD).astype(int)
    sig["target"], sig["trail"] = 0.0, 0.0
    if exit_ == "trail":
        sig["trail"] = TRAIL_ATR * a[i]
    elif exit_ == "t4":
        sig["target"] = 4 * stop
    elif exit_ == "t10":
        sig["target"] = 10 * stop
    elif exit_ == "focus":
        if focus is None:
            return sig.iloc[0:0]
        sig["hold"] = focus_hold(sig, *focus)
    elif exit_ == "src":
        if "target_px" not in sig:
            return sig.iloc[0:0]
        tp = side * (sig["target_px"].to_numpy(float) - ref)
        keep = tp > 0
        sig = sig[keep].copy()
        sig["target"] = tp[keep]
    if "limit" not in sig:
        sig["limit"] = 0
    sig["expires"] = sig["expires"].fillna(1).astype(int)
    return sig[["i", "side", "stop", "target", "hold", "trail", "entry", "limit", "expires", "tag"]]


def trade(book, sig, costs):
    from mt5bt import run
    if sig.empty:
        return pd.DataFrame()
    t, _ = run(book, None, costs, equity=1e9, risk=0.001, one_per_symbol=True,
               signals={book.symbol: sig.drop(columns=["tag"])})
    if t.empty:
        return t
    # tags back by signal bar: one position per symbol keeps them in order
    tags = sig.set_index("i")["tag"]
    t["tag"] = tags.reindex(t["i"]).to_numpy() if "i" in t else ""
    return t


def coin(book, t, a, seed):
    """The fills replayed at market with a random side, the same stop distance and exit."""
    ts = book.bars["ts"].to_numpy()
    j = np.searchsorted(ts, t["entry_ts"].to_numpy(), side="right") - 1
    rng = np.random.default_rng(seed)
    sig = pd.DataFrame({"i": np.maximum(j - 1, 0), "side": np.where(rng.random(len(t)) < 0.5, 1, -1),
                        "stop": t["stop_d"].to_numpy(), "target": t.get("target_d", 0.0),
                        "hold": MAXHOLD, "trail": t.get("trail_d", 0.0), "entry": np.nan,
                        "limit": 0, "expires": 1, "tag": t["tag"].to_numpy()})
    return sig


def context(sym, iv, df, frames):
    ctx = S.Ctx(sym, FAMILY.get(sym, "walk"), iv, SEC[iv], df)
    ts = df["ts"].to_numpy()
    for up in UP.get(iv, ()):
        d = frames.get(up)
        if d is not None:
            ctx.htf[up] = (d, P.htf_index(ts, SEC[iv], d["ts"].to_numpy(), SEC[up]))
    return ctx


def one(job) -> list[pd.DataFrame]:
    from mt5bt import Book, Costs, load_specs
    from mt5bt.data import EXAMPLE_SPECS
    kind, sym, seed = job
    t0 = time.time()
    specs = load_specs(DB)
    out = []
    if kind == "real":
        spec = specs.get(sym)
        frames = {iv: load(sym, iv) for iv in ("15m", "1h", "4h", "1d")}
    else:
        spec = EXAMPLE_SPECS["EURUSD"]
        frames = walk_frames(seed)
    if spec is None:
        print(f"  {sym}: no spec", flush=True)
        return []
    floor = spread_floor(sym, spec) if kind == "real" else 11.0  # walks: EURUSD's quoted spread
    costs = Costs(spread_mult=SPREAD_MULT, limit_through_points=0.0, spread_points=floor,
                  spread_floor_points=floor)
    for iv in INTERVALS:
        df = frames.get(iv)
        if df is None:
            continue
        book = Book(sym if kind == "real" else f"walk{seed}", df, spec, iv,
                    feed=sym.lower() if kind == "real" else "eurusd")
        bars = book.bars
        costs.limit_through_points = floor  # a resting limit fills only once traded a spread through
        min_stop = 2 * floor * spec.point
        ctx = context(sym, iv, bars, frames)
        if kind == "real":
            for p in PEERS:
                if p != sym:
                    pdf = load(p, iv)
                    if pdf is not None:
                        ctx.peers[p] = pd.Series(pdf["close"].to_numpy(), index=pdf["ts"]) \
                            .reindex(bars["ts"]).ffill().to_numpy()
        a = ctx.a
        for name, fn in S.SETUPS.items():
            if ONLY and name not in ONLY:
                continue
            try:
                raw = fn(ctx)
            except Exception as exc:  # one broken rule must not cost the rest
                print(f"  {sym} {iv} {name}: {type(exc).__name__}: {exc}", flush=True)
                continue
            if raw is None or raw.empty:
                continue
            for exit_ in EXITS:
                fz = None
                if exit_ == "focus":
                    fz = (ctx.get(("fu", id(bars)), lambda: S._focus(ctx, bars, True))[0],
                          ctx.get(("fd", id(bars)), lambda: S._focus(ctx, bars, False))[0])
                sig = to_mt5(raw, bars, a, exit_, min_stop, fz)
                if sig.empty:
                    continue
                t = trade(book, sig, costs)
                if t.empty:
                    continue
                rows = [("real" if kind == "real" else "walk", t)]
                if kind == "real":
                    t = t.assign(stop_d=t["stop_d"])
                    cs = coin(book, t.assign(trail_d=(TRAIL_ATR * a[np.clip(np.searchsorted(bars["ts"].to_numpy(), t["entry_ts"].to_numpy(), side="right") - 2, 0, None)]) if exit_ == "trail" else 0.0,
                                             target_d=t["stop_d"] * {"t4": 4, "t10": 10}.get(exit_, 0)),
                              a, zlib.crc32(f"{sym}{iv}{name}{exit_}".encode()))
                    if exit_ == "focus":
                        # the coin's exit is the FOCuS change against *its own* side
                        cs["hold"] = focus_hold(cs, *fz)
                    ct = trade(book, cs, costs)
                    if not ct.empty:
                        rows.append(("coin", ct))
                for k, x in rows:
                    out.append(pd.DataFrame({
                        "kind": k, "sym": sym, "family": FAMILY.get(sym, "walk"), "interval": iv,
                        "setup": name, "tag": x["tag"].astype(str).to_numpy(), "exit": exit_,
                        "R": x["R"].to_numpy(), "entry_ts": x["entry_ts"].to_numpy(),
                        "reason": x["reason"].astype(str).to_numpy(),
                        "fill": x["fill"].astype(str).to_numpy() if "fill" in x else "bars"}))
    print(f"  {kind} {sym}: {sum(len(o) for o in out):,} trades in {time.time() - t0:.0f}s", flush=True)
    return out


def walk_frames(seed):
    """A GARCH t walk at 15m with 1h/4h/1d aggregates, long enough for daily setups to warm."""
    from mt5bt.nulls import garch_walk
    w = garch_walk(140_000, interval="15m", spread_points=8.0, seed=1000 + seed)
    out = {"15m": w.tail(60_000).reset_index(drop=True)}
    for iv, k in (("1h", 4), ("4h", 16), ("1d", 96)):
        g = np.arange(len(w)) // k
        agg = w.groupby(g).agg(ts=("ts", "first"), open=("open", "first"), high=("high", "max"),
                               low=("low", "min"), close=("close", "last"), spread=("spread", "mean"))
        if "tick_volume" in w:
            agg["tick_volume"] = w.groupby(g)["tick_volume"].sum()
        out[iv] = agg.reset_index(drop=True)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    syms = [s for s in os.environ.get("SYMBOLS", ",".join(FAMILY)).split(",") if s]
    jobs = [("real", s, 0) for s in syms] + [("walk", f"walk{k}", k) for k in range(int(os.environ.get("WALKS", 6)))]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 24))) as pool:
        parts = [p for got in pool.map(one, jobs) for p in got]
    df = pd.concat(parts, ignore_index=True)
    df.to_pickle(OUT / "trades.pkl.gz")
    print(f"{len(df):,} trades", flush=True)


if __name__ == "__main__":
    main()
