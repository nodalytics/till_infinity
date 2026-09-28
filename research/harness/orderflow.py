"""Order flow and absorption, on real aggressor-tagged trades.

Every trade on Binance USDT-M futures is published with its aggressor side (`is_buyer_maker`: true
means the seller hit the bid). Spot FX has no central tape, so this is the only free footprint the
desk can reach, and BTC, ETH and SOL are what it trades through Deriv, whose crypto quote follows
the exchange consensus (`research/docs/lagging.md`).

PART=fetch  download monthly aggTrades from data.binance.vision, one symbol at a time, and keep only
            1-minute bars: open/high/low/close, volume, taker-buy volume, trade counts, and
            large-trade buy/sell volume (notional above LARGE). The zip is deleted after.
PART=study  the questions (see the study section).

Run on the lab:
  PART=fetch SYMBOL=BTCUSDT OUT=$HOME/till_infinity/data/orderflow python research/harness/orderflow.py
"""
from __future__ import annotations

import os
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(os.environ.get("OUT", ".data/orderflow"))
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
MONTHS = [str(p) for p in pd.period_range("2025-09", "2026-08", freq="M")]
LARGE = {"BTCUSDT": 100_000.0, "ETHUSDT": 50_000.0, "SOLUSDT": 25_000.0}  # USD notional of one trade
URL = "https://data.binance.vision/data/futures/um/monthly/aggTrades/{s}/{s}-aggTrades-{m}.zip"
COLS = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "transact_time", "is_buyer_maker"]


def minute_bars(path, symbol):
    """Stream one month's trades into 1-minute bars without holding the month in memory."""
    parts = []
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            first = fh.readline().decode()
        header = 0 if first.startswith("agg_trade_id") else None
        with z.open(name) as fh:
            for ch in pd.read_csv(fh, header=header, names=None if header == 0 else COLS, chunksize=5_000_000,
                                  usecols=["price", "quantity", "transact_time", "is_buyer_maker"]):
                t = ch["transact_time"].to_numpy()
                t = np.where(t > 1e14, t // 1000, t)  # microseconds in some newer files
                ch = ch.assign(minute=(t // 60_000).astype(np.int64))
                seller = ch["is_buyer_maker"].astype(str).str.lower().eq("true")
                q = ch["quantity"].astype(float)
                notional = q * ch["price"]
                big = notional >= LARGE[symbol]
                ch = ch.assign(buy=np.where(seller, 0.0, q), sell=np.where(seller, q, 0.0), nb=(~seller).astype(int),
                               ns=seller.astype(int), bigbuy=np.where(big & ~seller, q, 0.0),
                               bigsell=np.where(big & seller, q, 0.0), pv=notional)
                g = ch.groupby("minute", sort=True)
                parts.append(pd.DataFrame({
                    "open": g["price"].first(), "high": g["price"].max(), "low": g["price"].min(),
                    "close": g["price"].last(), "buy": g["buy"].sum(), "sell": g["sell"].sum(),
                    "nb": g["nb"].sum(), "ns": g["ns"].sum(), "bigbuy": g["bigbuy"].sum(),
                    "bigsell": g["bigsell"].sum(), "pv": g["pv"].sum(),
                }))
    d = pd.concat(parts)
    # a minute split across two chunks is recombined
    d = d.groupby(level=0).agg({"open": "first", "high": "max", "low": "min", "close": "last", "buy": "sum",
                                "sell": "sum", "nb": "sum", "ns": "sum", "bigbuy": "sum", "bigsell": "sum", "pv": "sum"})
    return d


def fetch(symbol):
    OUT.mkdir(parents=True, exist_ok=True)
    for m in MONTHS:
        dest = OUT / f"{symbol}.{m}.npz"
        if dest.exists():
            continue
        tmp = OUT / f"{symbol}.{m}.zip"
        urllib.request.urlretrieve(URL.format(s=symbol, m=m), tmp)
        d = minute_bars(tmp, symbol)
        np.savez_compressed(dest, minute=d.index.to_numpy(), **{c: d[c].to_numpy() for c in d.columns})
        tmp.unlink()
        print(f"{symbol} {m}: {len(d):,} minutes, {d.buy.sum() + d.sell.sum():,.0f} traded", flush=True)


# ---------------------------------------------------------------------------------------------- study
#
# Pre-registered, before any result was seen. Units are sigma: the trailing one-day mean |5m return|.
#
# Absorption (Trader Dale, "How to Trade The Absorption Setup"), long case, mirrored for short:
#   a sharp move in       the last 6 bars (30m) fell by at least SPIKE sigma
#   heavy on both sides   this 5m bar's buy AND sell volume are each >= HEAVY x their trailing
#                         one-day median
#   price does not move   this bar's net move is within +-STALL sigma
#   at a level            within NEAR sigma of a one-day swing low/high or a volume-profile
#                         high-volume node of the last three days (the video's condition; the rest
#                         is its placebo: "somewhere random on the chart ... doesn't really mean anything")
# Traded in the direction against the move in, from the close of the next minute (one minute of
# latency), held 15m / 1h / 4h, non-overlapping per symbol; and as a bracket with the stop beyond the
# absorption bar's extreme and the target at twice that distance, resolved on 1m wicks, tie = stop.
#
# Twins that isolate each ingredient:
#   stall only      the same spike and stall, no volume condition - is it the volume or the stall?
#   one-sided       the same spike, heavy volume on the aggressor side only, price kept going
SPIKE, HEAVY, STALL, NEAR = 2.0, 2.0, 0.5, 1.0
HORIZONS = {"15m": 15, "1h": 60, "4h": 240}
COST_BPS = {"deriv": 2.4, "taker": 10.0}  # round trip; lagging.md for Deriv's crypto spread
RNG = np.random.default_rng(11)


def load(symbol):
    parts = [np.load(f) for f in sorted(OUT.glob(f"{symbol}.*.npz"))]
    d = pd.DataFrame({k: np.concatenate([p[k] for p in parts]) for k in parts[0].files}).set_index("minute")
    d = d[~d.index.duplicated()].sort_index()
    full = np.arange(d.index[0], d.index[-1] + 1)
    d = d.reindex(full)
    d["close"] = d["close"].ffill()
    for c in ("open", "high", "low"):
        d[c] = d[c].fillna(d["close"])
    return d.fillna(0.0)


def five(m):
    g = m.groupby(m.index // 5)
    b = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                      "close": g["close"].last(), "buy": g["buy"].sum(), "sell": g["sell"].sum(),
                      "bigbuy": g["bigbuy"].sum(), "bigsell": g["bigsell"].sum(), "pv": g["pv"].sum()})
    b.index = b.index * 5  # minute at which the bar opens
    return b


def levels(b, sig):
    """Distance, in sigma, to the nearest level: a one-day swing high/low, or a high-volume node of the
    last three days' volume profile (local maxima of volume at price). Causal: uses bars before t."""
    lc = np.log(b["close"].to_numpy())
    vol = (b["buy"] + b["sell"]).to_numpy()
    hi = pd.Series(np.log(b["high"].to_numpy())).shift(1).rolling(288).max().to_numpy()
    lo = pd.Series(np.log(b["low"].to_numpy())).shift(1).rolling(288).min().to_numpy()
    d_swing = np.minimum(np.abs(lc - hi), np.abs(lc - lo))
    d_hvn = np.full(len(b), np.nan)
    tp = np.log(((b["high"] + b["low"] + b["close"]) / 3).to_numpy())
    for i in range(864, len(b)):
        if not np.isfinite(sig[i]):
            continue
        w = slice(i - 864, i)
        width = 0.5 * sig[i]
        edges = np.arange(tp[w].min(), tp[w].max() + width, width)
        if len(edges) < 4:
            continue
        h, _ = np.histogram(tp[w], bins=edges, weights=vol[w])
        peak = (h[1:-1] > h[:-2]) & (h[1:-1] >= h[2:]) & (h[1:-1] > np.median(h[h > 0]) * 1.5)
        centres = 0.5 * (edges[1:-2] + edges[2:-1])[peak]  # centres of the inner bins h[1:-1]
        if len(centres):
            d_hvn[i] = np.abs(centres - lc[i]).min()
    return np.fmin(d_swing, d_hvn) / sig


def signals(b, m):
    lc = np.log(b["close"].to_numpy())
    r = np.diff(lc, prepend=np.nan)
    sig = pd.Series(np.abs(r)).shift(1).rolling(288, min_periods=144).mean().to_numpy()
    buy, sell = b["buy"].to_numpy(), b["sell"].to_numpy()
    mb = pd.Series(buy).shift(1).rolling(288, min_periods=144).median().to_numpy()
    ms = pd.Series(sell).shift(1).rolling(288, min_periods=144).median().to_numpy()
    prior = (lc - np.r_[np.full(6, np.nan), lc[:-6]]) - r  # the 30m before this bar, excluding it
    prior = prior / sig
    move = r / sig
    heavy_b, heavy_s = buy >= HEAVY * mb, sell >= HEAVY * ms
    stall = np.abs(move) <= STALL
    near = levels(b, sig) <= NEAR
    down, up = prior <= -SPIKE, prior >= SPIKE
    side = np.where(down, 1.0, np.where(up, -1.0, 0.0))  # against the move in
    absorb = (down | up) & heavy_b & heavy_s & stall
    stall_only = (down | up) & stall
    one_sided = (down & heavy_s & ~heavy_b & (move < -STALL)) | (up & heavy_b & ~heavy_s & (move > STALL))
    # entry one minute after the bar closes; forward paths from minute bars
    close_m = m["close"].to_numpy()
    idx0 = m.index[0]
    entry_min = b.index.to_numpy() + 5 + 1 - idx0
    ok = (entry_min + max(HORIZONS.values()) < len(close_m)) & np.isfinite(sig)
    entry_min = np.clip(entry_min, 0, len(close_m) - 1)
    entry = np.log(close_m[entry_min])
    fwd = {h: (np.log(close_m[np.clip(entry_min + n, 0, len(close_m) - 1)]) - entry) for h, n in HORIZONS.items()}
    # bracket: stop beyond the absorption bar's extreme, target 2x, up to 4h, on minute wicks
    lo_m, hi_m = np.log(m["low"].to_numpy()), np.log(m["high"].to_numpy())
    stop_d = np.where(side > 0, entry - np.log(b["low"].to_numpy()), np.log(b["high"].to_numpy()) - entry)
    stop_d = np.maximum(stop_d, 0.1 * sig)  # a stop inside a tenth of a normal bar is noise
    return dict(ts=b.index.to_numpy(), side=side, absorb=absorb, stall_only=stall_only, one_sided=one_sided,
                near=near, ok=ok, sig=sig, fwd=fwd, entry=entry, entry_min=entry_min, stop_d=stop_d,
                lo_m=lo_m, hi_m=hi_m, imb=(buy - sell) / np.maximum(buy + sell, 1e-12), r=r,
                bigimb=(b["bigbuy"] - b["bigsell"]).to_numpy() / np.maximum(buy + sell, 1e-12))


def bracket(s, i):
    """Net result in R of the bracket at bar i: +2 target, -1 stop (a minute touching both is the stop)."""
    side, e, d = s["side"][i], s["entry"][i], s["stop_d"][i]
    a = s["entry_min"][i]
    lo, hi = s["lo_m"][a + 1:a + 1 + 240], s["hi_m"][a + 1:a + 1 + 240]
    adverse = (e - lo) if side > 0 else (hi - e)
    favour = (hi - e) if side > 0 else (e - lo)
    stop_hit = adverse >= d
    take_hit = favour >= 2 * d
    first_stop = np.argmax(stop_hit) if stop_hit.any() else 10 ** 9
    first_take = np.argmax(take_hit) if take_hit.any() else 10 ** 9
    if first_stop == first_take == 10 ** 9:
        return np.nan, d  # neither within 4h: the caller scores it at the 4h close
    return (2.0 if first_take < first_stop else -1.0), d


def report(name, sel, S, test_from):
    """Pooled over symbols: n, mean forward return aligned with the signal (sigma), hit rate, both
    halves of the test period, and net bps per trade at each cost; plus the bracket in R."""
    out = []
    for per, lo_t, hi_t in (("train", -np.inf, test_from), ("test", test_from, np.inf)):
        rows = {h: [] for h in HORIZONS}
        bps = {h: [] for h in HORIZONS}
        br = []
        halves = []
        for sym, s in S.items():
            k = np.flatnonzero(sel[sym] & s["ok"] & (s["ts"] >= lo_t) & (s["ts"] < hi_t))
            # non-overlapping: at most one trade per 4h per symbol
            keep, last = [], -10 ** 12
            for i in k:
                if s["ts"][i] >= last + 240:
                    keep.append(i)
                    last = s["ts"][i]
            k = np.array(keep, dtype=int)
            if not len(k):
                continue
            for h in HORIZONS:
                aligned = s["side"][k] * s["fwd"][h][k]
                rows[h].append(aligned / s["sig"][k])
                bps[h].append(aligned * 1e4)
            for i in k:
                res, d = bracket(s, i)
                if np.isnan(res):
                    res = s["side"][i] * s["fwd"]["4h"][i] / d
                br.append(res - COST_BPS["deriv"] / 1e4 / d)
            halves.append(s["ts"][k])
        if not rows["1h"]:
            out.append(f"{per}: none")
            continue
        n = sum(len(x) for x in rows["1h"])
        cells = []
        for h in HORIZONS:
            x, b_ = np.concatenate(rows[h]), np.concatenate(bps[h])
            cells.append(f"{h} {x.mean():+.2f}s hit {np.mean(x > 0):.0%} gross {b_.mean():+.1f}bp "
                         f"net {b_.mean() - COST_BPS['deriv']:+.1f}/{b_.mean() - COST_BPS['taker']:+.1f}")
        br = np.array(br)
        out.append(f"{per} n={n}: " + " | ".join(cells) + f" | bracket {np.nanmean(br):+.2f}R")
    print(f"    {name:<34} " + "\n    " + " " * 35 + "".join(o + "\n    " + " " * 35 for o in out).rstrip())


def flow(S, test_from):
    """Does signed flow predict returns beyond past returns? 5m bars, test block, pooled."""
    print("\n  ORDER FLOW - imbalance (buy - sell) / volume over the last k bars, against the next h minutes")
    for k in (1, 3, 12):
        for h in ("15m", "1h"):
            xs, ys, rs, bs = [], [], [], []
            for s in S.values():
                imb = pd.Series(s["imb"]).rolling(k).mean().to_numpy()
                big = pd.Series(s["bigimb"]).rolling(k).mean().to_numpy()
                past = pd.Series(s["r"]).rolling(k).sum().to_numpy()
                m = s["ok"] & (s["ts"] >= test_from) & np.isfinite(imb) & np.isfinite(past) & (np.arange(len(imb)) % 12 == 0)
                xs.append(imb[m]); rs.append(past[m] / s["sig"][m]); bs.append(big[m])
                ys.append(s["fwd"][h][m] / s["sig"][m])
            x, y, r_, bg = map(np.concatenate, (xs, ys, rs, bs))
            from scipy import stats
            rho = stats.spearmanr(x, y).statistic
            rho_r = stats.spearmanr(r_, y).statistic
            # imbalance beyond past return: rank-residualise both on the past return
            rx = stats.rankdata(x) - np.polyval(np.polyfit(stats.rankdata(r_), stats.rankdata(x), 1), stats.rankdata(r_))
            ry = stats.rankdata(y) - np.polyval(np.polyfit(stats.rankdata(r_), stats.rankdata(y), 1), stats.rankdata(r_))
            partial = np.corrcoef(rx, ry)[0, 1]
            same = stats.spearmanr(x, r_).statistic
            rho_big = stats.spearmanr(bg, y).statistic
            print(f"    k={k * 5:>3}m -> {h:<4} imbalance {rho:+.4f} | past return {rho_r:+.4f} | imbalance beyond "
                  f"past return {partial:+.4f} | large-trade imbalance {rho_big:+.4f} | (imbalance vs same-window "
                  f"return {same:+.3f}), n={len(x):,}")


def study():
    S = {}
    for sym in SYMBOLS:
        m = load(sym)
        b = five(m)
        S[sym] = signals(b, m)
        print(f"  {sym}: {len(b):,} 5m bars, {m.index[0]} to {m.index[-1]} (minutes)", flush=True)
    t_all = np.concatenate([s["ts"] for s in S.values()])
    test_from = np.quantile(t_all, 0.6)
    print(f"\n{'=' * 110}\nORDER FLOW, Binance USDT-M futures {', '.join(SYMBOLS)}; train = first 60% by time, test = last 40%")
    print(f"  pre-registered: spike {SPIKE} sigma over 30m, heavy {HEAVY}x median on each side, stall +-{STALL} sigma, "
          f"level within {NEAR} sigma; costs round trip {COST_BPS}")
    print("\n  ABSORPTION - aligned against the move in; s = sigma units, net = after Deriv / taker cost, bracket after Deriv cost")
    for name, key, where in (("absorption AT a level", "absorb", True), ("absorption away from levels", "absorb", False),
                             ("stall only (no volume), at a level", "stall_only", True),
                             ("one-sided heavy flow, kept going", "one_sided", None)):
        sel = {sym: s[key] & ((s["near"] == where) if where is not None else True) for sym, s in S.items()}
        report(name, sel, S, test_from)
    # the whole spike universe, as the base rate of reversal
    report("every spike (base rate)", {sym: s["side"] != 0 for sym, s in S.items()}, S, test_from)
    flow(S, test_from)


if __name__ == "__main__":
    if os.environ.get("PART", "study") == "fetch":
        fetch(os.environ["SYMBOL"])
    else:
        study()
