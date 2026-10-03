"""The DAX mentorship's SMC checklist, traded: sweep -> major break -> structural liquidity -> POI ->
context. Copied into this repo from the desk's notes on an outside course (an 8-video SMC
mentorship): the method is described here in full and nothing here refers back to them.

Pre-registered (2026-10-02), before any run. One chart per timeframe (1h, 4h, 1d), context one
timeframe up (4h, 1d, weekly). For a buy (a sell is the same on the flipped chart):

  1 sweep        a swing low (3/3 pivot) that trades below the last swing low of the 40 bars before
                 it - one nothing had broken - and closes back above it within two bars. That low is
                 PROTECTED. A low that was not swept is not
  2 break        the first close above the last swing high known before the sweep, within 60 bars,
                 with the protected low holding. MAJOR when that high was a lower high (below the
                 swing high before it) - the previous lower high, not any local high
  3 structural   the last swing low between the protected low and the break, above the protected
    liquidity    low. None: the protected low is INDUCEMENT and the source stands down (the veto).
                 Valid when at or below the 50% of the leg (protected low -> the break's high) and
                 an obvious V: price at least 0.5 ATR above it on both sides within three bars
  4 POI          the QMR - the last order block (a bearish bar followed within 3 bars by a 1-ATR
                 rise) formed in the 30 bars before the sweep and traded through by the drop into
                 it - when it sits above the structural liquidity, inside the discount half and
                 untouched since the break; else the order block at the structural liquidity (the
                 last bearish bar of the 5 up to it); else, without structural liquidity, the order
                 block at the protected low (what the source says everyone else buys)
  5 context      the entry in the discount half of the timeframe above's last swing range
  entries        risk     a limit at the POI's top. The source's default
                 sl_take  a limit at the structural liquidity: "buy as it takes it"
                 Live from the bar everything above is known, for 50 bars; cancelled by a close
                 below the protected low or price reaching the target unfilled
  stop, target   0.1 ATR past the protected low; 3R fixed (the source's) - and 4R, 10R, 2-ATR trail
  hold           5 days at most (the desk's)
  filters        all (no veto), veto (structural liquidity present), veto50 (+ the 50% test),
                 vshape (+ the V), major (+ the major break), full (+ context), no_sl (exactly the
                 setups the veto skips - what standing down avoided)
  combined       (asked for later) the POI on a live zone of ours, not closed through since:
                 zr_all  any setup whose POI is on a research origin zone; zr the same with the
                 veto; zp on one of production's origins; zf on a fair-value gap; z_full every
                 step of the checklist and on any of them. zb: the POI on a Bjorgum zone shown
                 at that bar (veto too); zb_full every step and on one; zrb on a Bjorgum zone and
                 on one of ours. zz: ZMA stretched the setup's way when it is known (veto
                 too); zz_full every step and that; zzb that and on a Bjorgum zone. The other half - our origin zones
                 asked the DAX tests - is in `zones.py` (filters dax, dax_major)
  nulls          coin twin, random-time trades; day bootstrap, Benjamini-Hochberg (zones.run)

  OUT=... MT5BT_DB=... MODE=plot|run|direction python research/ideas/dax_smc.py
"""
from __future__ import annotations

import os
import sys
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
import zones as Z  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/dax_smc"))
L, SWEEP_BACK, BREAK_BARS, QMR_BACK, LIVE_BARS, BUF, TARGET_R = 3, 40, 60, 30, 50, 0.1, 3.0
UP = {"1h": "4h", "4h": "1d", "1d": "1w"}
SEC = {"1h": 3600, "4h": 14400, "1d": 86400, "1w": 7 * 86400}
FILTERS = ("all", "veto", "veto50", "vshape", "major", "full", "no_sl",
           "zr_all", "zr", "zp", "zf", "z_full", "zb", "zb_full", "zrb", "zz", "zz_full", "zzb")
TRIGGERS = ("risk", "sl_take")


def _ob_before(o, c, k_hi, k_lo):
    """The last bearish bar in [k_lo, k_hi], or -1."""
    for k in range(k_hi, max(k_lo, 0) - 1, -1):
        if c[k] < o[k]:
            return k
    return -1


def long_setups(df: pd.DataFrame, a: np.ndarray) -> list[dict]:
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(df)
    ph, pl = P.pivots(h, l, L, L)
    ph_known = np.array([x[0] for x in ph])
    pl_at = np.array([x[1] for x in pl])
    out = []
    for known_s, s, low_s in pl:
        if not a[s] > 0:
            continue
        A = a[s]
        # 1 the sweep: the last swing low before it, unbroken until s, taken and closed back above
        prior = [x for x in pl if s - SWEEP_BACK <= x[1] < s and x[0] <= s]
        if not prior:
            continue
        _, q, q_px = prior[-1]
        if not (low_s < q_px and l[q + 1:s].min(initial=np.inf) >= q_px and c[s:s + 2].max() > q_px):
            continue
        # 2 the break: the last swing high known before the sweep, closed above, protected low holding
        j = np.searchsorted(ph_known, s, side="right") - 1
        if j < 0:
            continue
        hi_px = ph[j][2]
        major = j >= 1 and hi_px < ph[j - 1][2]
        b = -1
        for k in range(s + 1, min(n, s + BREAK_BARS)):
            if l[k] < low_s:
                break
            if c[k] > hi_px:
                b = k
                break
        if b < 0:
            continue
        leg_hi = h[s:b + 1].max()
        level50 = low_s + 0.5 * (leg_hi - low_s)
        # 3 structural liquidity: the last swing low strictly between, above the protected low
        inner = [x for x in pl if s < x[1] < b and x[2] > low_s]
        sl = inner[-1] if inner else None
        live = max(b, known_s)
        sl_px = np.nan
        valid50 = vshape = False
        if sl is not None:
            known_m, m, sl_px = sl
            live = max(live, known_m)
            valid50 = sl_px <= level50
            left, right = h[max(0, m - 3):m].max(initial=sl_px), h[m + 1:m + 4].max(initial=sl_px)
            vshape = min(left, right) - sl_px >= 0.5 * a[m]
        # 4 the POI
        poi, kind = None, ""
        # the QMR: an order block before the sweep, traded through by the drop into it
        for k in range(s - 1, max(0, s - QMR_BACK) - 1, -1):
            if c[k] < o[k] and h[k + 1:k + 4].max(initial=-np.inf) - c[k] >= A and l[k] > low_s:
                if l[k + 1:s + 1].min() < l[k]:  # price took it out on the way down: it failed
                    zlo, zhi = l[k], h[k]
                    above_sl = sl is not None and zlo > sl_px
                    untouched = l[b + 1:live + 1].min(initial=np.inf) > zhi
                    if above_sl and zhi <= level50 and untouched:
                        poi, kind = (zlo, zhi), "qmr"
                break
        if poi is None and sl is not None:
            k = _ob_before(o, c, sl[1], sl[1] - 5)
            if k >= 0:
                poi, kind = (l[k], h[k]), "ob_sl"
        if poi is None and sl is None:
            k = _ob_before(o, c, s, s - 5)
            if k >= 0:
                poi, kind = (l[k], h[k]), "ob_protected"
        if poi is None or live + 1 >= n:
            continue
        stop_px = low_s - BUF * A
        rows = [("risk", poi[1])]
        if sl is not None:
            rows.append(("sl_take", sl_px))
        for trig, entry in rows:
            if not entry > stop_px:
                continue
            target = entry + TARGET_R * (entry - stop_px)
            # live for LIVE_BARS, cancelled by a close below the protected low or the target unfilled
            end = min(n - 1, live + LIVE_BARS)
            for k in range(live + 1, end + 1):
                if c[k] < low_s or h[k] >= target:
                    end = k
                    break
            if end <= live:
                continue
            out.append(dict(i=live, side=1, trigger=trig, entry=entry, limit=1, expires=end - live,
                            stop_px=stop_px, target_px=target, protected=s, protected_px=low_s, swept=q,
                            swept_px=q_px, break_bar=b, break_px=hi_px, major=bool(major), sl_at=sl[1] if sl else -1,
                            sl_px=sl_px, level50=level50, valid50=bool(valid50), vshape=bool(vshape),
                            poi_lo=poi[0], poi_hi=poi[1], poi=kind, has_sl=sl is not None))
    return out


def setups(df: pd.DataFrame, a: np.ndarray) -> pd.DataFrame:
    """Both sides, in this chart's prices."""
    rows = long_setups(df, a)
    for r in long_setups(Z.flip(df), a):
        r["side"] = -1
        for k in ("entry", "stop_px", "target_px", "protected_px", "swept_px", "break_px", "sl_px", "level50"):
            r[k] = -r[k]
        r["poi_lo"], r["poi_hi"] = -r["poi_hi"], -r["poi_lo"]
        rows.append(r)
    return pd.DataFrame(rows)


def weekly(d1: pd.DataFrame) -> pd.DataFrame:
    wk = (d1["ts"] - 4 * 86400) // (7 * 86400)  # weeks starting Monday (epoch day 0 was a Thursday)
    w = d1.groupby(wk).agg(ts=("ts", "first"), open=("open", "first"), high=("high", "max"),
                           low=("low", "min"), close=("close", "last"))
    return w.reset_index(drop=True)


def context(df, iv, st, load):
    """Whether each setup's entry is in the discount half (a sell: premium) of the timeframe
    above's last known swing range."""
    up = UP[iv]
    dh = weekly(load("1d")) if up == "1w" else load(up)
    if dh is None or st.empty:
        return np.zeros(len(st), bool)
    dh = dh.reset_index(drop=True)
    k = P.htf_index(df["ts"].to_numpy()[st["i"].to_numpy()], SEC[iv], dh["ts"].to_numpy(), SEC[up])
    ph, pl = P.pivots(dh["high"].to_numpy(), dh["low"].to_numpy(), L, L)
    hi, lo = P.last_known(ph, len(dh)), P.last_known(pl, len(dh))
    mid = np.array([(hi[x][-1][1] + lo[x][-1][1]) / 2 if x >= 0 and hi[x] and lo[x] else np.nan for x in k])
    e = st["entry"].to_numpy()
    return np.where(st["side"] > 0, e < mid, e > mid)


def confluence(df, a, st, zs) -> np.ndarray:
    """Whether each setup's POI overlaps (0.1 ATR) a zone of the same side that is live by the
    setup's bar and has not been closed through since."""
    c = df["close"].to_numpy()
    out = np.zeros(len(st), bool)
    for n_, s in enumerate(st.itertuples()):
        plo, phi = min(s.poi_lo, s.poi_hi), max(s.poi_lo, s.poi_hi)
        pad = 0.1 * a[int(s.i)]
        for z in zs:
            if z.side != s.side or z.live > s.i:
                continue
            lo, hi = min(z.lo, z.hi), max(z.lo, z.hi)
            if hi < plo - pad or lo > phi + pad:
                continue
            span = c[z.live:int(s.i) + 1]
            A = a[z.p]
            broken = (span < z.lo - Z.BUF * A).any() if z.side > 0 else (span > z.lo + Z.BUF * A).any()
            if not broken:
                out[n_] = True
                break
    return out


def flags(st: pd.DataFrame) -> pd.DataFrame:
    st["all"] = True
    st["veto"] = st["has_sl"]
    st["veto50"] = st["veto"] & st["valid50"]
    st["vshape"] = st["veto50"] & st["vshape"]
    st["major"] = st["vshape"] & st["major"]
    st["full"] = st["major"] & st["context"]
    st["no_sl"] = ~st["has_sl"]
    # the combination with our zone marking (asked for later): the POI sits on a live zone of ours
    if "conf_research" in st:
        st["zr_all"] = st["conf_research"]
        st["zr"] = st["veto"] & st["conf_research"]
        st["zp"] = st["veto"] & st["conf_prod"]
        st["zf"] = st["veto"] & st["conf_fvg"]
        st["z_full"] = st["full"] & (st["conf_research"] | st["conf_prod"] | st["conf_fvg"])
        st["zb"] = st["veto"] & st["conf_bjorgum"]
        st["zb_full"] = st["full"] & st["conf_bjorgum"]
        st["zrb"] = st["veto"] & st["conf_bjorgum"] & (st["conf_research"] | st["conf_prod"] | st["conf_fvg"])
        st["zz"] = st["veto"] & st["zma_st"]
        st["zz_full"] = st["full"] & st["zma_st"]
        st["zzb"] = st["veto"] & st["zma_st"] & st["conf_bjorgum"]
    return st


def run_one(job):
    import run as R
    import survivors
    sym, iv = job
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")
    got = survivors.book_for(sym, iv)
    if got is None:
        return []
    book, costs, min_stop = got
    df = book.bars.reset_index(drop=True)
    a = P.atr(df, 14)
    st = setups(df, a)
    if st.empty:
        return []
    st["context"] = context(df, iv, st, lambda x: R.load(sym, x))
    st["conf_research"] = confluence(df, a, st, Z.long_zones(df, a) + _flipped(df, a))
    st["conf_prod"] = confluence(df, a, st, Z.zones_prod(df, a))
    st["conf_fvg"] = confluence(df, a, st, Z.zones_fvg(df, a))
    piv = Z.bjorgum_pivots(df)
    st["conf_bjorgum"] = [Z.bjorgum_overlap(piv, int(r.i), min(r.poi_lo, r.poi_hi), max(r.poi_lo, r.poi_hi))
                          for r in st.itertuples()]
    zm = Z.zma_series(df)  # stretched the setup's way when it is known (the bar before the limit rests)
    st["zma_st"] = zm["stretched"].to_numpy()[st["i"].to_numpy()] == st["side"].to_numpy()
    st = flags(st)
    st["sid"] = [f"{sym}|{iv}|{k}" for k in range(len(st))]
    out = Z._trade_all(sym, iv, book, costs, min_stop, df, a, st, list(FILTERS), list(TRIGGERS), SEC[iv])
    print(f"  {sym} {iv}: {len(st)} setups, {int(st['veto'].sum())} with structural liquidity, "
          f"{int(st['full'].sum())} pass every step", flush=True)
    return out + [st.assign(sym=sym, iv=iv, kind="setup", ts=df["ts"].to_numpy()[st["i"].to_numpy()])]


def _flipped(df, a):
    """The research origin zones' short side, in this chart's prices (as `zones.zones` builds it)."""
    zs = Z.long_zones(Z.flip(df), a, -1)
    for z in zs:
        z.lo, z.hi, z.bos_level, z.leg_extreme = -z.lo, -z.hi, -z.bos_level, -z.leg_extreme
    return zs


def run():
    Z.OUT = OUT
    Z.run(run_one, primary=("risk", "full", "opp"), show="full")


# ------------------------------------------------------------------------------------- direction

def direction_one(job):
    """With the stop aside: from the fill, does price go the setup's way (Z._paths), against the
    same side at random bars of the same market."""
    import run as R
    sym, iv = job
    R.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, iv)
    if df is None:
        return None
    df = df.reset_index(drop=True)
    a = P.atr(df, 14)
    st = setups(df, a)
    if st.empty:
        return None
    st["context"] = context(df, iv, st, lambda x: R.load(sym, x))
    st = flags(st)
    l, h, o = df["low"].to_numpy(), df["high"].to_numpy(), df["open"].to_numpy()
    rng = np.random.default_rng(zlib.crc32(f"dax{sym}{iv}".encode()))
    ok = np.flatnonzero(a > 0)
    ok = ok[(ok > 100) & (ok < len(df) - 2)]
    cols = [f"mv{H}" for H in Z.HORIZONS] + [f"first{k}" for k in Z.LEVELS]
    rows = []
    for s in st[st["trigger"] == "risk"].itertuples():
        end = int(s.i + s.expires)
        span = np.arange(int(s.i) + 1, min(end, len(df) - 1) + 1)
        hit = span[(l[span] <= s.entry) if s.side > 0 else (h[span] >= s.entry)]
        if not len(hit):
            continue
        f = int(hit[0])
        base = {k: getattr(s, k) for k in FILTERS}
        rows.append(dict(kind="setup", side=s.side, **base,
                         **dict(zip(cols, Z._paths(df, a, f, s.side, s.entry, SEC[iv]), strict=True))))
        for j in rng.choice(ok, 3):
            rows.append(dict(kind="random", side=s.side, **base,
                             **dict(zip(cols, Z._paths(df, a, int(j), s.side, o[j + 1], SEC[iv]), strict=True))))
    print(f"  direction {sym} {iv}", flush=True)
    return pd.DataFrame(rows).assign(sym=sym, iv=iv, family=R.FAMILY.get(sym, "?")) if rows else None


def direction():
    import run as R
    from score import JUMPY
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    jobs = [(s, iv) for iv in os.environ.get("INTERVALS", "1h,4h,1d").split(",") for s in syms]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 20))) as pool:
        got = [g for g in pool.map(direction_one, jobs) if g is not None]
    d = pd.concat(got, ignore_index=True)
    d.loc[(d["family"] == "deriv") & d["sym"].str.startswith(JUMPY), "family"] = "deriv_jump"
    d["scope"] = np.where(d["family"].str.startswith("deriv"), d["family"], "real markets")
    d.to_pickle(OUT / "direction.pkl.gz")
    rows = []
    for (scope, iv, kind), g in d.groupby(["scope", "iv", "kind"]):
        for flt in FILTERS:
            x = g[g[flt]]
            if len(x) < 30:
                continue
            r = dict(scope=scope, iv=iv, filter=flt, kind=kind, n=len(x))
            for H in Z.HORIZONS:
                r[f"up{H}d"] = (x[f"mv{H}"].dropna() > 0).mean()
            for k in Z.LEVELS:
                f = x[f"first{k}"]
                r[f"{k}ATR first"] = (f == 1).sum() / max((f != 0).sum(), 1)
            rows.append(r)
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "direction.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 300)
    print(t.round(3).to_string(index=False))


# ------------------------------------------------------------------------------------------ plot

def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    OUT.mkdir(parents=True, exist_ok=True)
    for sym, iv in (("EURUSD", "1h"), ("GBPUSD", "1h"), ("XAUUSD", "4h"), ("Germany 40", "1h"),
                    ("US Tech 100", "4h"), ("AUDUSD", "4h"), ("BTCUSD", "1d"), ("GBPJPY", "4h")):
        df = R.load(sym, iv)
        if df is None:
            continue
        df = df.reset_index(drop=True)
        a = P.atr(df, 14)
        st = setups(df, a)
        if st.empty:
            continue
        st["context"] = context(df, iv, st, lambda x, s=sym: R.load(s, x))
        st = flags(st)
        piv = Z.bjorgum_pivots(df)
        pick = st[(st["trigger"] == "risk") & st["veto50"]]
        if pick.empty:
            continue
        rng = np.random.default_rng(zlib.crc32(sym.encode()))
        pick = pick.iloc[np.sort(rng.choice(len(pick), min(4, len(pick)), replace=False))]
        fig, axes = plt.subplots(2, 2, figsize=(18, 11))
        for ax, (_, s) in zip(axes.flat, pick.iterrows(), strict=False):
            i0, i1 = max(0, int(s.swept) - 15), min(len(df) - 1, int(s.i + s.expires) + 25)
            w = df.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            bj = False
            for b_lo, b_hi, _ in Z.bjorgum_live(piv, int(s.i)):
                ax.axhspan(b_lo, b_hi, color="purple", alpha=0.08)
                bj |= b_hi >= min(s.poi_lo, s.poi_hi) and b_lo <= max(s.poi_lo, s.poi_hi)
            ax.hlines(s.swept_px, s.swept, s.protected, colors="#666", linestyles=":", lw=1)
            ax.annotate("swept low" if s.side > 0 else "swept high", (s.swept, s.swept_px), fontsize=8)
            ax.scatter([s.protected], [s.protected_px], marker="o", s=80, facecolors="none", edgecolors="k", zorder=5)
            ax.annotate("PROTECTED", (s.protected, s.protected_px), fontsize=8, xytext=(3, -10), textcoords="offset points")
            ax.hlines(s.break_px, s.protected, s.break_bar, colors="k", linestyles="--", lw=1)
            ax.annotate("major BOS" if s.major else "BOS (minor)", (s.break_bar, s.break_px), fontsize=8)
            if s.has_sl:
                ax.scatter([s.sl_at], [s.sl_px], marker="x", s=80, color="purple", zorder=5)
                ax.annotate("structural liq.", (s.sl_at, s.sl_px), fontsize=8, color="purple",
                            xytext=(3, -10), textcoords="offset points")
            ax.hlines(s.level50, s.protected, i1, colors="#999", linestyles="-.", lw=0.8)
            ax.annotate("50%", (i1, s.level50), fontsize=8, color="#666")
            ax.add_patch(Rectangle((s.i, s.poi_lo), s.expires, s.poi_hi - s.poi_lo, color="#457b9d", alpha=0.3))
            ax.hlines(s.stop_px, s.i, i1, colors="red", lw=1)
            ax.hlines(s.target_px, s.i, i1, colors="green", lw=1)
            ax.axvline(s.i, color="#bbb", lw=0.6, ls=":")
            ax.set_title(f"{sym} {iv} {'buy' if s.side > 0 else 'sell'}  POI={s.poi}  "
                         f"50%:{'ok' if s.valid50 else 'fail'}  V:{'ok' if s.vshape else 'fail'}  "
                         f"context:{'ok' if s.context else 'fail'}  bjorgum:{'on' if bj else 'off'}  "
                         f"{pd.Timestamp(df['ts'].iat[int(s.i)], unit='s'):%Y-%m-%d %H:%M}", fontsize=9)
        fig.suptitle("swept low -> PROTECTED low -> BOS (dashed) -> structural liquidity (x) -> POI (blue, live "
                     "window) | red stop past the protected low, green 3R | purple: Bjorgum zones shown then", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"dax_{sym.replace(' ', '_')}_{iv}.png", dpi=80)
        plt.close(fig)
        print(f"  {sym} {iv}: {len(st)} setups", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    {"plot": plot, "run": run, "direction": direction}[os.environ.get("MODE", "plot")]()


if __name__ == "__main__":
    main()
