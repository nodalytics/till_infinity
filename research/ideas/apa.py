"""APA - Advanced Price Action: Analysis, Point of Interest, Action - traded.

The published outline (a retail course; no exact rules are public): analyse the higher timeframe's
trend and structure, mark a high-probability reaction zone, and act only on confirmation inside it -
aggressively on the first rejection, conservatively on a lower-timeframe change of character and its
retest. Higher timeframe first; never against it. Made into rules here, pre-registered 2026-10-03:

  analysis   on the higher timeframe (HTF): the direction of its last break of structure
             (`zones.bias_4h`, any timeframe) must be the trade's; and the entry in the discount half
             of its last swing range for a buy (premium for a sell)
  POI        an HTF reaction zone: the origin of a move that broke structure and left an imbalance
             (`zones.long_zones` - a swing low whose 3-ATR leg broke the last swing high within 10
             bars, held, and left a 0.2-ATR gap; the origin bar from its low to its body top - an
             order block in all but name). First return only
  action     on the lower timeframe (LTF), from its first bar in the POI, within the HTF's 12-bar
             reaction window:
               aggressive    the first rejection bar in the POI (a pin bar or a bullish engulfing),
                             in at the next open, stop 0.1 HTF-ATR past the POI
               conservative  the first LTF change of character (a close over the last 2-bar swing
                             high since the touch), then a limit at that broken high - the retest -
                             resting 12 LTF bars, stop 0.1 LTF-ATR under the reaction's low;
                             cancelled by a close under that low
  targets    opp: the HTF's last swing high (sell: low) above the entry - the liquidity; t4, t10,
             a 2-ATR trail. 5-day hold at most
  pairs      4h -> 1h, 4h -> 15m, 1d -> 1h, 1h -> 15m (15m from 2024-07). Both sides
  filters    none (POI and action only), bias (+ HTF trend), apa (+ discount/premium: the method)
  nulls      coin twin and random-time trades, day bootstrap (zones.run)

  OUT=... MT5BT_DB=... MODE=run|plot python research/ideas/apa.py
"""
from __future__ import annotations

import os
import sys
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import prims as P  # noqa: E402
import zones as Z  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/apa"))
PAIRS = os.environ.get("INTERVALS", "4h>1h,4h>15m,1d>1h,1h>15m")
SEC = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
RETEST_BARS = 12


def htf_zones(dh, ah):
    zs = Z.long_zones(dh, ah)
    short = Z.long_zones(Z.flip(dh), ah, -1)
    for z in short:
        z.lo, z.hi, z.bos_level, z.leg_extreme = -z.lo, -z.hi, -z.bos_level, -z.leg_extreme
    return zs + short


def setups(dh, ah, d1, a1, htf, ltf):
    """APA setups for one market: HTF POIs acted on in the LTF, in this chart's prices."""
    th, t1 = dh["ts"].to_numpy(), d1["ts"].to_numpy()
    sec_h = SEC[htf]
    bias = Z.bias_4h(dh)
    ph, pl = P.pivots(dh["high"].to_numpy(), dh["low"].to_numpy(), Z.LR, Z.LR)
    hi_k, lo_k = P.last_known(ph, len(dh)), P.last_known(pl, len(dh))
    fl1 = Z.flip(d1)
    ex1 = (Z.extras(d1), Z.extras(fl1))
    rows = []
    for z in htf_zones(dh, ah):
        if z.ret < 0:
            continue
        frame, ex = (d1, ex1[0]) if z.side > 0 else (fl1, ex1[1])
        o, h, l, c = (frame[k].to_numpy() for k in ("open", "high", "low", "close"))
        lo, hi = (z.lo, z.hi) if z.side > 0 else (-z.lo, -z.hi)
        A = ah[z.p]
        j0 = int(np.searchsorted(t1, th[z.ret], side="left"))
        j1 = int(np.searchsorted(t1, th[min(z.ret + Z.WINDOW, len(th) - 1)] + sec_h, side="left"))
        touch, low_since, got = -1, np.inf, set()
        for j in range(j0, min(j1, len(d1) - 2)):
            if touch < 0:
                if l[j] > hi:
                    continue
                touch = j
            low_since = min(low_since, l[j])
            if c[j] < lo - Z.BUF * A:
                break
            rng_ = max(h[j] - l[j], 1e-12)
            pin = (min(o[j], c[j]) - l[j] >= 0.6 * rng_ and abs(c[j] - o[j]) <= rng_ / 3
                   and c[j] >= l[j] + 0.5 * rng_)
            engulf = (j >= 1 and c[j] > o[j] and c[j - 1] < o[j - 1] and c[j] >= o[j - 1] and o[j] <= c[j - 1])
            if "aggr" not in got and (pin or engulf) and l[j] <= hi + Z.NEAR * a1[j]:
                got.add("aggr")
                rows.append(dict(i=j, side=z.side, trigger="apa_aggr", entry=np.nan, limit=0, expires=1,
                                 stop_px=(lo - Z.BUF * A) * z.side, zone=z, touch=touch, choch_px=np.nan))
            if "cons" not in got and j > touch and Z._choch(ex, c, touch, j):
                got.add("cons")
                k = np.searchsorted(ex["ph_known"], j, side="right") - 1
                level = ex["ph_px"][k]
                stop = low_since - Z.BUF * a1[j]
                # cancelled by a close under the reaction low: count the bars it may rest
                end = j + RETEST_BARS
                for m in range(j + 1, min(len(d1) - 1, j + RETEST_BARS) + 1):
                    if c[m] < low_since:
                        end = m
                        break
                if level > stop and end > j:
                    rows.append(dict(i=j, side=z.side, trigger="apa_cons", entry=level * z.side, limit=1,
                                     expires=end - j, stop_px=stop * z.side, zone=z, touch=touch,
                                     choch_px=level * z.side))
            if len(got) == 2:
                break
    if not rows:
        return pd.DataFrame()
    st = pd.DataFrame(rows)
    c1 = d1["close"].to_numpy()
    kh = np.searchsorted(th + sec_h, t1[st["i"].to_numpy()] + SEC[ltf], side="right") - 1  # HTF bar closed by then
    ref = np.where(np.isfinite(st["entry"]), st["entry"], c1[st["i"].to_numpy()])
    tgt, disc, bia = [], [], []
    for k, s_, r_ in zip(kh, st["side"], ref, strict=True):
        k = max(int(k), 0)
        H = hi_k[k][-1][1] if hi_k[k] else np.nan
        L_ = lo_k[k][-1][1] if lo_k[k] else np.nan
        liq = H if s_ > 0 else L_
        tgt.append(liq if np.isfinite(liq) and s_ * (liq - r_) > 0 else np.nan)
        mid = (H + L_) / 2
        disc.append(bool(np.isfinite(mid) and (r_ < mid if s_ > 0 else r_ > mid)))
        bia.append(bias[k] == s_)
    st["target_px"], st["discount"], st["bias"] = tgt, disc, bia
    st["none"] = True
    st["apa"] = st["bias"] & st["discount"]
    return st


def run_one(job):
    import run as R
    import survivors
    sym, pair = job
    htf, ltf = pair.split(">")
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")
    dh = R.load(sym, htf)
    got = Z.ltf_book(sym, ltf)
    if dh is None or got is None:
        return []
    book, costs, min_stop = got
    dh = dh.reset_index(drop=True)
    d1 = book.bars.reset_index(drop=True)
    ah, a1 = P.atr(dh, 14), P.atr(d1, 14)
    st = setups(dh, ah, d1, a1, htf, ltf)
    if st.empty:
        return []
    st = st.drop(columns=["zone"])
    st["sid"] = [f"{sym}|{pair}|{k}" for k in range(len(st))]
    out = Z._trade_all(sym, pair, book, costs, min_stop, d1, a1, st, ["none", "bias", "apa"],
                       ["apa_aggr", "apa_cons"], SEC[ltf])
    print(f"  {sym} {pair}: {len(st)} setups, {int(st['apa'].sum())} pass the whole method", flush=True)
    return out + [st.assign(sym=sym, iv=pair, kind="setup")]


def run():
    Z.OUT = OUT
    Z.run(run_one, primary=("apa_cons", "apa", "opp"), show="apa")


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    OUT.mkdir(parents=True, exist_ok=True)
    for sym, pair in (("EURUSD", "4h>1h"), ("XAUUSD", "4h>1h"), ("US Tech 100", "4h>1h"), ("GBPJPY", "1d>1h"),
                      ("BTCUSD", "4h>1h"), ("Germany 40", "1h>15m"), ("GBPUSD", "4h>15m")):
        htf, ltf = pair.split(">")
        dh, d1 = R.load(sym, htf), R.load(sym, ltf)
        if dh is None or d1 is None:
            continue
        dh, d1 = dh.reset_index(drop=True), d1.reset_index(drop=True)
        ah, a1 = P.atr(dh, 14), P.atr(d1, 14)
        st = setups(dh, ah, d1, a1, htf, ltf)
        if st.empty:
            continue
        st = st[st["apa"]]
        if st.empty:
            continue
        rng = np.random.default_rng(zlib.crc32((sym + pair).encode()))
        pick = st.iloc[np.sort(rng.choice(len(st), min(4, len(st)), replace=False))]
        t1, th = d1["ts"].to_numpy(), dh["ts"].to_numpy()
        fig, axes = plt.subplots(2, 2, figsize=(18, 11))
        for ax, (_, s_) in zip(axes.flat, pick.iterrows(), strict=False):
            z, i = s_.zone, int(s_.i)
            z0 = int(np.searchsorted(t1, th[z.p]))
            i0, i1 = max(0, min(z0, int(s_.touch)) - 20), min(len(d1) - 1, i + 60)
            if i1 - i0 > 400:
                i0 = max(0, int(s_.touch) - 120)
            w = d1.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.5)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            lo, hi = min(z.lo, z.hi), max(z.lo, z.hi)
            ax.add_patch(Rectangle((max(i0, z0), lo), i - max(i0, z0), hi - lo, color="#457b9d", alpha=0.3))
            ax.axvline(int(s_.touch), color="#999", lw=0.8, ls=":")
            if np.isfinite(s_.choch_px):
                ax.hlines(s_.choch_px, int(s_.touch), i + RETEST_BARS, colors="purple", linestyles="--", lw=1)
                ax.annotate("LTF CHoCH - retest here", (i, s_.choch_px), fontsize=8, color="purple")
            ent = s_.entry if np.isfinite(s_.entry) else d1["open"].iat[i + 1]
            ax.scatter([i + (0 if s_.limit else 1)], [ent], marker="^" if s_.side > 0 else "v", s=120,
                       color="green" if s_.side > 0 else "red", zorder=5)
            ax.hlines(s_.stop_px, i, i1, colors="red", lw=1)
            if np.isfinite(s_.target_px):
                ax.hlines(s_.target_px, i, i1, colors="green", lw=1)
            ys = [w["low"].min(), w["high"].max(), s_.stop_px] + ([s_.target_px] if np.isfinite(s_.target_px) else [])
            ax.set_ylim(min(ys) * 0.999, max(ys) * 1.001)
            ax.set_title(f"{sym} {pair} {'buy' if s_.side > 0 else 'sell'}  {s_.trigger.replace('apa_', '')} entry  "
                         f"{pd.Timestamp(t1[i], unit='s'):%Y-%m-%d %H:%M}", fontsize=10)
        fig.suptitle(f"APA: blue = {htf} POI (origin of a structure-breaking, imbalanced move), with the {htf} trend and in "
                     f"its discount/premium | {ltf} chart: dotted = first touch, purple = CHoCH level (conservative retest), "
                     "triangle = entry | red stop, green = HTF liquidity target", fontsize=10)
        fig.tight_layout()
        fig.savefig(OUT / f"apa_{sym.replace(' ', '_')}_{pair.replace('>', '-')}.png", dpi=80)
        plt.close(fig)
        print(f"  {sym} {pair}: {len(st)} setups pass the method", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    {"run": run, "plot": plot}[os.environ.get("MODE", "plot")]()


if __name__ == "__main__":
    main()
