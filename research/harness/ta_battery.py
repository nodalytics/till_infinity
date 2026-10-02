"""Classic TA indicator strategies, each traded on its own, on every market family and timeframe.

Earlier work used indicators as entry timing (indicators.md: 0 of ~170 cells) and as confirmation
gates (confirm.md: 17 of 8,366 cells, four of five survivors failing deflation). Never as the
strategies themselves, across the whole book. This does, once, with every cell counted.

Pre-registered (2026-10-02), before any run.

  rules     19 textbook rules, default parameters, signals at a bar's close, entry at the next open:
            sma_20_50 and sma_50_200 crosses (ema_9_21 and ema_20_50 crosses were added on
            2026-10-02 for ta_ticks.py, after this battery had started, and are not in its count); macd (12, 26, 9) signal cross; rsi14 (cross back
            up through 30 / down through 70); rsi2 (below 10 long / above 90 short); bb_revert
            (close back inside the 20, 2 band); bb_break (close outside it); donchian20 and
            donchian55 breakouts; keltner (20, 2 ATR) breakout; stoch (14, 3) cross out of 20/80;
            willr (14) cross out of -80/-20; adx (14) > 25 with a DI cross; ichimoku (tenkan/kijun
            cross on the cloud's side); psar flip; cci (20) cross of +-100; obv against its 20 SMA;
            supertrend (10, 3) flip; heikin-ashi colour flip after two of a colour
  exits     the same for all: stop 2 ATR(14), trailing 3 ATR, out on the opposite signal, 200 bars
            at most. No take-profit.
  universe  the lab's broker bars: FX (15), metals (2), crypto (3), stocks (20, 1h and 1d), Deriv
            (8); 15m, 1h, 4h, 1d; the whole history (nothing is fitted), halves by time
  costs     each bar's own MT5 spread, swap from the broker's specs (mt5bt)
  nulls     a coin twin of every cell (the same entries and exits, a seeded random side); and each
            rule on 4 GARCH walks per timeframe with the EURUSD contract
  survives  a cell (rule x family x timeframe) whose net R beats its coin with a day-bootstrap
            p < 0.05 after Benjamini-Hochberg across every cell, positive in both halves, net R
            > 0, and not positive on the walks
"""
from __future__ import annotations

import json
import os
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "harness"))
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT))

OUT = Path(os.environ.get("OUT", ".data/ta_battery"))
SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
INTERVALS = ("15m", "1h", "4h", "1d")
MAXHOLD = 200


# ------------------------------------------------------------------ indicators


def ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def cross_up(a, b):
    return (a > b) & (a.shift() <= b.shift())


def cross_dn(a, b):
    return (a < b) & (a.shift() >= b.shift())


def signals(df: pd.DataFrame) -> dict[str, pd.Series]:
    """+1 long, -1 short, 0 nothing, per rule, at each bar's close."""
    c, h, l = df["close"], df["high"], df["low"]
    a = atr(df)
    out = {}

    def sig(long, short):
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=df.index)

    s20, s50, s200 = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    out["sma_20_50"] = sig(cross_up(s20, s50), cross_dn(s20, s50))
    out["sma_50_200"] = sig(cross_up(s50, s200), cross_dn(s50, s200))
    for f, sl_ in ((9, 21), (20, 50)):
        ef, es = ema(c, f), ema(c, sl_)
        out[f"ema_{f}_{sl_}"] = sig(cross_up(ef, es), cross_dn(ef, es))
    macd = ema(c, 12) - ema(c, 26)
    sl = ema(macd, 9)
    out["macd"] = sig(cross_up(macd, sl), cross_dn(macd, sl))
    r14 = rsi(c, 14)
    out["rsi14"] = sig(cross_up(r14, pd.Series(30.0, index=c.index)), cross_dn(r14, pd.Series(70.0, index=c.index)))
    r2 = rsi(c, 2)
    out["rsi2"] = sig((r2 < 10) & (r2.shift() >= 10), (r2 > 90) & (r2.shift() <= 90))
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    up, lo = mid + 2 * sd, mid - 2 * sd
    out["bb_revert"] = sig(cross_up(c, lo), cross_dn(c, up))
    out["bb_break"] = sig(cross_up(c, up), cross_dn(c, lo))
    for n in (20, 55):
        hh, ll = h.rolling(n).max().shift(), l.rolling(n).min().shift()
        out[f"donchian{n}"] = sig(cross_up(c, hh), cross_dn(c, ll))
    kmid = ema(c, 20)
    out["keltner"] = sig(cross_up(c, kmid + 2 * a), cross_dn(c, kmid - 2 * a))
    k = 100 * (c - l.rolling(14).min()) / (h.rolling(14).max() - l.rolling(14).min()).replace(0, np.nan)
    d = k.rolling(3).mean()
    out["stoch"] = sig(cross_up(d, pd.Series(20.0, index=c.index)), cross_dn(d, pd.Series(80.0, index=c.index)))
    wr = -100 * (h.rolling(14).max() - c) / (h.rolling(14).max() - l.rolling(14).min()).replace(0, np.nan)
    out["willr"] = sig(cross_up(wr, pd.Series(-80.0, index=c.index)), cross_dn(wr, pd.Series(-20.0, index=c.index)))
    upm, dnm = h.diff(), -l.diff()
    pdm = np.where((upm > dnm) & (upm > 0), upm, 0.0)
    ndm = np.where((dnm > upm) & (dnm > 0), dnm, 0.0)
    pdi = 100 * pd.Series(pdm, index=c.index).ewm(alpha=1 / 14, adjust=False).mean() / a
    ndi = 100 * pd.Series(ndm, index=c.index).ewm(alpha=1 / 14, adjust=False).mean() / a
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / 14, adjust=False).mean()
    out["adx"] = sig(cross_up(pdi, ndi) & (adx > 25), cross_dn(pdi, ndi) & (adx > 25))
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    top, bot = np.maximum(span_a, span_b), np.minimum(span_a, span_b)
    out["ichimoku"] = sig(cross_up(tenkan, kijun) & (c > top), cross_dn(tenkan, kijun) & (c < bot))
    out["psar"] = sig(*psar_flips(df))
    tp = (h + l + c) / 3
    cci = (tp - tp.rolling(20).mean()) / (0.015 * tp.rolling(20).apply(lambda w: np.mean(np.abs(w - w.mean())), raw=True))
    out["cci"] = sig(cross_up(cci, pd.Series(100.0, index=c.index)), cross_dn(cci, pd.Series(-100.0, index=c.index)))
    obv = (np.sign(c.diff()).fillna(0) * df["volume"]).cumsum()
    out["obv"] = sig(cross_up(obv, obv.rolling(20).mean()), cross_dn(obv, obv.rolling(20).mean()))
    out["supertrend"] = sig(*supertrend_flips(df, a))
    ha_c = (df["open"] + h + l + c) / 4
    ha_o = ha_c.copy()
    ha_o.iloc[0] = (df["open"].iloc[0] + c.iloc[0]) / 2
    hv, cv = ha_o.to_numpy(), ha_c.to_numpy()
    for i in range(1, len(hv)):
        hv[i] = (hv[i - 1] + cv[i - 1]) / 2
    green = pd.Series(cv > hv, index=c.index)
    red1, red2 = ~green.shift(1, fill_value=True), ~green.shift(2, fill_value=True)
    grn1, grn2 = green.shift(1, fill_value=False), green.shift(2, fill_value=False)
    out["heikin_ashi"] = sig(green & red1 & red2, ~green & grn1 & grn2)
    return out


def psar_flips(df, step=0.02, top=0.2):
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(h)
    up = np.zeros(n, bool)
    sar, ep, af, rising = l[0], h[0], step, True
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if rising:
            if l[i] < sar:
                rising, sar, ep, af = False, ep, l[i], step
            else:
                if h[i] > ep:
                    ep, af = h[i], min(af + step, top)
                sar = min(sar, l[i - 1])
        else:
            if h[i] > sar:
                rising, sar, ep, af = True, ep, h[i], step
            else:
                if l[i] < ep:
                    ep, af = l[i], min(af + step, top)
                sar = max(sar, h[i - 1])
        up[i] = rising
    s = pd.Series(up, index=df.index)
    return s & ~s.shift(1, fill_value=True), ~s & s.shift(1, fill_value=False)


def supertrend_flips(df, a, mult=3.0):
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    mid = (h + l) / 2
    av = a.to_numpy()
    upper, lower = mid + mult * av, mid - mult * av
    n = len(c)
    trend = np.ones(n, bool)
    fu, fl = upper.copy(), lower.copy()
    for i in range(1, n):
        fu[i] = upper[i] if (upper[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower[i] if (lower[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        trend[i] = True if c[i] > fu[i - 1] else (False if c[i] < fl[i - 1] else trend[i - 1])
    s = pd.Series(trend, index=df.index)
    return s & ~s.shift(1, fill_value=True), ~s & s.shift(1, fill_value=False)


# ------------------------------------------------------------------ trading


def orders(df: pd.DataFrame, sig: pd.Series, coin: bool, seed: int) -> pd.DataFrame:
    a = atr(df).to_numpy()
    s = sig.to_numpy()
    idx = np.flatnonzero(s != 0)
    if len(idx) == 0:
        return pd.DataFrame()
    side = s[idx].copy()
    # exit on the opposite signal: the bars until the next signal of the other side
    nxt_hold = np.full(len(idx), MAXHOLD)
    for k in range(len(idx)):
        later = idx[k + 1:][s[idx[k + 1:]] == -side[k]]
        if len(later):
            nxt_hold[k] = min(MAXHOLD, int(later[0] - idx[k]))
    if coin:
        rng = np.random.default_rng(seed)
        side = np.where(rng.random(len(idx)) < 0.5, 1, -1)
    ok = a[idx] > 0
    return pd.DataFrame({"i": idx[ok], "side": side[ok], "stop": 2 * a[idx][ok], "trail": 3 * a[idx][ok],
                         "hold": np.maximum(nxt_hold[ok], 1)})


def one(job: tuple) -> list[dict]:
    from mt5bt import Book, Costs, load_bars, load_specs, run
    from mt5bt.data import EXAMPLE_SPECS
    from mt5bt.nulls import garch_walk
    import energy as en

    kind, sym, fam, iv = job
    if kind == "walk":
        bars = garch_walk(20_000, interval=iv, spread_points=8.0, seed=int(sym))
        spec = EXAMPLE_SPECS["EURUSD"]
        name = f"walk{sym}"
    else:
        try:
            bars = load_bars(sym, iv, "seqlab", SEQLAB)
        except (OSError, ValueError):
            return []
        spec = en.spec_for(load_specs(os.environ.get("MT5BT_DB")), sym)
        if spec is None or len(bars) < 500:
            return []
        name = sym
    book = Book(name, bars, spec, iv, feed=sym.replace("_", " ").lower() if kind != "walk" else "eurusd")
    sigs = signals(book.bars)
    mid = book.bars["ts"].iat[len(book.bars) // 2]
    rows = []
    for rule, sg in sigs.items():
        for coin in (False, True):
            od = orders(book.bars, sg, coin, zlib.crc32(f"{name}{iv}{rule}".encode()))
            if od.empty:
                continue
            t, _ = run(book, None, Costs(), equity=1e7, risk=0.001, one_per_symbol=True, signals={name: od})
            if t.empty:
                continue
            rows.append(pd.DataFrame({"kind": kind, "sym": name, "family": fam, "interval": iv, "rule": rule,
                                      "coin": coin, "R": t["R"].to_numpy(), "gross": (t["gross"] / t["risk_money"]).to_numpy(),
                                      "day": (t["entry_ts"] // 86400).to_numpy(),
                                      "second": (t["entry_ts"] >= mid).to_numpy()}))
    print(f"  {kind} {name} {iv} done", flush=True)
    return rows


def main() -> None:
    import expansion_build as eb

    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("market", sym, fam, iv) for sym, fam in eb.FAMILY.items() for iv in INTERVALS]
    jobs += [("walk", str(900 + k), "walk", iv) for k in range(4) for iv in INTERVALS]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", "48"))) as pool:
        parts = [r for rows in pool.map(one, jobs) for r in rows]
    df = pd.concat(parts, ignore_index=True)
    df.to_pickle(OUT / "trades.pkl.gz")  # our own output, read back only by us
    cells = []
    rng = np.random.default_rng(71)
    for (fam, iv, rule), g in df[df["kind"] == "market"].groupby(["family", "interval", "rule"]):
        s, c = g[~g["coin"]], g[g["coin"]]
        if len(s) < 30 or len(c) < 30:
            continue
        # day bootstrap of (strategy mean - coin mean)
        sd = {d: x["R"].to_numpy() for d, x in s.groupby("day")}
        cd = {d: x["R"].to_numpy() for d, x in c.groupby("day")}
        days = np.array(sorted(set(sd) | set(cd)))
        diffs = []
        for _ in range(1000):
            pick = rng.choice(days, len(days))
            a = np.concatenate([sd[d] for d in pick if d in sd] or [np.array([0.0])])
            b = np.concatenate([cd[d] for d in pick if d in cd] or [np.array([0.0])])
            diffs.append(a.mean() - b.mean())
        diffs = np.array(diffs)
        cells.append(dict(family=fam, interval=iv, rule=rule, n=len(s), R=s["R"].mean(), coin_R=c["R"].mean(),
                          diff=s["R"].mean() - c["R"].mean(), p=float((diffs <= 0).mean()),
                          first=s.loc[~s["second"], "R"].mean(), second=s.loc[s["second"], "R"].mean(),
                          gross=s["gross"].mean()))
    cells = pd.DataFrame(cells)
    m = len(cells)
    order = np.argsort(cells["p"].to_numpy())
    q = np.empty(m)
    q[order] = np.minimum.accumulate((cells["p"].to_numpy()[order] * m / np.arange(1, m + 1))[::-1])[::-1]
    cells["q"] = np.minimum(q, 1.0)
    walks = df[(df["kind"] == "walk") & ~df["coin"]].groupby(["interval", "rule"])["R"].mean().rename("walk_R").reset_index()
    cells = cells.merge(walks, on=["interval", "rule"], how="left")
    cells["survives"] = (cells["q"] < 0.05) & (cells["first"] > 0) & (cells["second"] > 0) & (cells["R"] > 0) & ~(cells["walk_R"] > 0)
    cells.to_csv(OUT / "cells.csv", index=False)
    summary = {
        "cells": m, "survivors": int(cells["survives"].sum()),
        "positive_net": int((cells["R"] > 0).sum()), "beat_coin_raw_p05": int((cells["p"] < 0.05).sum()),
        "by_rule_mean_R": cells.groupby("rule")["R"].mean().round(4).sort_values(ascending=False).to_dict(),
        "by_rule_diff": cells.groupby("rule")["diff"].mean().round(4).sort_values(ascending=False).to_dict(),
        "by_family_mean_R": cells.groupby("family")["R"].mean().round(4).to_dict(),
        "best_cells": cells.sort_values("q").head(15).round(4).to_dict(orient="records"),
    }
    print(json.dumps(summary, indent=1, default=str), flush=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
