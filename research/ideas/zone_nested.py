"""A break on the higher timeframe, entered from a lower-timeframe zone close to it.

The desk's idea (2026-10-03): when a 4h or 1h break of structure happens, drop to 15m or 30m and
enter from a zone there that sits close to the break. Pre-registered before any run.

  HTF break    every break of structure on 4h and 1h from `zone_events` (a swing origin whose move
               closed beyond the last known swing within 20 bars), with its broken level, its leg
               (origin bar to break bar) and whether it was qualified (gap + 2 ATR)
  LTF zones    qualified zones on 15m and on 30m (built from the 15m), first return, near edge, body
               band, their 1R outcome net of the spread - as everywhere in `zone_events`
  relations    inside   the LTF zone's origin lies in an HTF break's leg of the same direction - it is
                        part of the move that broke structure up there
               near     and its band is within 0.5 HTF-ATR of the broken HTF level (the retest of
                        broken structure)
               against  an LTF zone of the other direction inside an HTF break's leg
               after    the LTF zone formed within 2 HTF bars after the HTF break, same direction
               none     no HTF break of either kind around it
  judged       R a trade by relation, LTF and HTF, against all LTF zones of the same period; each
               relation also for HTF-qualified breaks only. The broker's 15m starts 2024-07, so this
               is about 15 months; it is reported by month halves for stability

  stack        the frozen test in `nested_stack.json`: rare origin and trending return stacked on the
               nested effect, thresholds from the MT5 run, judged once on Binance (MODE=stack)

  OUT=... MT5BT_DB=... MODE=run|plot|stack python research/ideas/zone_nested.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import prims as P  # noqa: E402
import zone_events as E  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/zone_nested"))
#: SOURCE=binance: the confirmation on Binance USD-M perpetuals (12 coins, 15m from 2021, fees 0.07%
#: of price a trade) - pre-registered after the MT5 run: 15m/30m zones inside a 4h break's leg beat all
#: 15m/30m zones and those against a 4h break do worst, judged on 2021 to 2024-06 (time the MT5 run never
#: saw) and on 2024-07 on (its period, another venue)
SOURCE = os.environ.get("SOURCE", "mt5")
BIN = Path(os.environ.get("BINANCE", os.path.expanduser("~/till_infinity/data/binance")))
COINS = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "TRX")
FEE = 0.0007
LTFS = ("15m", "30m")
HTFS = ("1h", "4h")
SEC = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}
NEAR = 0.5


def _bin(sym, iv):
    z = np.load(BIN / f"{sym}USDT.klines.{iv}.npz")
    d = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close", "volume")})
    return d.rename(columns={"time": "ts"}).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def bars(sym, iv):
    import run as R
    if SOURCE == "binance":
        if iv == "30m":
            d = _bin(sym, "15m")
            d["k"] = d["ts"] // 1800 * 1800
            d = d.groupby("k").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                   close=("close", "last"), volume=("volume", "sum"))
            return d.reset_index().rename(columns={"k": "ts"})
        return _bin(sym, iv)
    if iv == "30m":
        d = R.load(sym, "15m")
        if d is None:
            return None
        d = d.copy()
        d["k"] = d["ts"] // 1800 * 1800
        d = d.groupby("k").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                               close=("close", "last"), volume=("volume", "sum"), spread=("spread", "min"))
        return d.reset_index().rename(columns={"k": "ts"})
    d = R.load(sym, iv)
    return None if d is None else d.reset_index(drop=True)


def evs(df, iv, spread):
    a = P.atr(df, 14)
    rows = []
    frac = FEE if SOURCE == "binance" else None
    for side, frame in ((1, df), (-1, E.flip(df))):
        rows += E.events(frame, a, side, spread, None, None, SEC[iv], spread_frac=frac)
    d = pd.DataFrame(rows)
    if d.empty:
        return d, a
    d["bos_level"] = d["bos_level"] * d["side"]  # back to this chart's prices
    return d, a


def one(sym):
    import run as R
    from mt5bt import load_specs
    R.DB = os.environ.get("MT5BT_DB")
    if SOURCE == "binance":
        spread = 0.0
        R.FAMILY.setdefault(sym, "crypto")
        l15 = bars(sym, "15m")
    else:
        spec = load_specs(R.DB).get(sym)
        spread = R.spread_floor(sym, spec) * spec.point if spec is not None else 0.0
        l15 = R.load(sym, "15m")
    if l15 is None or len(l15) < 2000:
        return None
    start = int(l15["ts"].iloc[0])
    breaks = []
    for htf in HTFS:
        dh = bars(sym, htf)
        if dh is None:
            continue
        dh = dh[dh["ts"] >= start - 200 * SEC[htf]].reset_index(drop=True)
        d, ah = evs(dh, htf, spread)
        if d.empty:
            continue
        b = d.drop_duplicates(["p", "side"])[["p", "side", "V", "ts", "bos_ts", "bos_level", "atr_p"]].copy()
        b["htf"] = htf
        b["end_ts"] = b["bos_ts"] + SEC[htf]  # the break is known at the break bar's close
        breaks.append(b)
    if not breaks:
        return None
    H = pd.concat(breaks, ignore_index=True)
    out = []
    for ltf in LTFS:
        dl = bars(sym, ltf)
        if dl is None:
            continue
        d, _ = evs(dl, ltf, spread)
        if d.empty:
            continue
        f = d[d["filled"] & (d["depth"] == "d0") & (d["bound"] == "body") & (d["ret"] == 1) & d["V"]].copy()
        if f.empty:
            continue
        o = dl.reset_index(drop=True)
        near_edge = np.where(f["side"] > 0, np.maximum(o["open"].to_numpy()[f["p"]], o["close"].to_numpy()[f["p"]]),
                             np.minimum(o["open"].to_numpy()[f["p"]], o["close"].to_numpy()[f["p"]]))
        far_edge = np.where(f["side"] > 0, o["low"].to_numpy()[f["p"]], o["high"].to_numpy()[f["p"]])
        for htf in HTFS:
            hh = H[H["htf"] == htf]
            for col in ("inside", "near", "against", "after", "inside_q", "near_q"):
                f[f"{col}_{htf}"] = False
            f[f"inside_known_{htf}"] = np.nan  # when the earliest matching HTF break became knowable
            for n_, r in enumerate(f.itertuples()):
                t0 = r.ts  # the LTF origin's time
                lo, hi = min(near_edge[n_], far_edge[n_]), max(near_edge[n_], far_edge[n_])
                legs = hh[(hh["ts"] <= t0) & (t0 <= hh["bos_ts"] + SEC[htf] - 1)]
                same = legs[legs["side"] == r.side]
                f.iat[n_, f.columns.get_loc(f"inside_{htf}")] = len(same) > 0
                if len(same):
                    f.iat[n_, f.columns.get_loc(f"inside_known_{htf}")] = float(same["end_ts"].min())
                f.iat[n_, f.columns.get_loc(f"against_{htf}")] = (legs["side"] != r.side).any()
                if len(same):
                    q = same[same["V"]]
                    f.iat[n_, f.columns.get_loc(f"inside_q_{htf}")] = len(q) > 0
                    close_ = (np.abs(same["bos_level"].to_numpy() - (lo + hi) / 2) <= NEAR * same["atr_p"].to_numpy()
                              + (hi - lo) / 2)
                    f.iat[n_, f.columns.get_loc(f"near_{htf}")] = bool(close_.any())
                    f.iat[n_, f.columns.get_loc(f"near_q_{htf}")] = bool((close_ & same["V"].to_numpy()).any())
                aft = hh[(hh["side"] == r.side) & (hh["end_ts"] <= t0) & (t0 <= hh["end_ts"] + 2 * SEC[htf])]
                f.iat[n_, f.columns.get_loc(f"after_{htf}")] = len(aft) > 0
        out.append(f.assign(sym=sym, ltf=ltf, family=R.FAMILY.get(sym, "?")))
    print(f"  {sym}", flush=True)
    return pd.concat(out, ignore_index=True) if out else None


def run():
    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    syms = list(COINS) if SOURCE == "binance" else [s for s in R.FAMILY if s not in R.FRESH]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 20))) as pool:
        got = [g for g in pool.map(one, syms) if g is not None]
    d = pd.concat(got, ignore_index=True)
    d.to_pickle(OUT / "nested.pkl.gz")
    d["scope"] = np.where(d["family"].str.startswith("deriv"), "deriv", "real")
    d["hit"] = (d["best"] >= 1).astype(float)
    mid = (pd.Timestamp("2024-07-01", tz="UTC").timestamp() if SOURCE == "binance" else d["ret_ts"].median())
    d["half"] = np.where(d["ret_ts"] < mid, "first", "second")  # binance: before / from the MT5 window
    pd.set_option("display.width", 250)
    rows = []
    for (scope, ltf), g in d.groupby(["scope", "ltf"]):
        for htf in HTFS:
            masks = {"all LTF zones": np.ones(len(g), bool),
                     "inside an HTF break leg": g[f"inside_{htf}"].to_numpy(),
                     "inside a qualified HTF break": g[f"inside_q_{htf}"].to_numpy(),
                     "inside + near the broken level": g[f"near_{htf}"].to_numpy(),
                     "inside + near, qualified HTF": g[f"near_q_{htf}"].to_numpy(),
                     "just after an HTF break": g[f"after_{htf}"].to_numpy(),
                     "against an HTF break": g[f"against_{htf}"].to_numpy(),
                     "no HTF break around": ~(g[f"inside_{htf}"] | g[f"against_{htf}"] | g[f"after_{htf}"]).to_numpy()}
            for name, m in masks.items():
                x = g[m]
                rows.append(dict(scope=scope, ltf=ltf, htf=htf, relation=name, n=len(x), P1R=x["hit"].mean(),
                                 R=x["R"].mean(), R_first=x.loc[x["half"] == "first", "R"].mean(),
                                 R_second=x.loc[x["half"] == "second", "R"].mean(), R_flip=x["flip_R"].mean()))
    t = pd.DataFrame(rows).round(3)
    t.to_csv(OUT / "nested.csv", index=False)
    print(t.to_string(index=False))


def plot():
    """LTF zones inside and near an HTF break, on the LTF chart: the HTF break's leg shaded, its
    broken level, the LTF zone and its first return with the R it reached."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    d = pd.read_pickle(OUT / "nested.pkl.gz")
    d = d[~d["family"].str.startswith("deriv")]
    rng = np.random.default_rng(9)
    for col, title in (("near_4h", "inside a 4h break's leg and near the broken 4h level"),
                       ("inside_4h", "inside a 4h break's leg"), ("against_4h", "against a 4h break")):
        pick = d[d[col] & (d["ltf"] == "15m")]
        if pick.empty:
            continue
        pick = pick.iloc[rng.choice(len(pick), min(4, len(pick)), replace=False)]
        fig, axes = plt.subplots(2, 2, figsize=(18, 10))
        for ax, (_, r) in zip(axes.flat, pick.iterrows(), strict=False):
            dl, dh = bars(r.sym, "15m"), bars(r.sym, "4h")
            dh = dh[dh["ts"] >= dl["ts"].iloc[0] - 200 * SEC["4h"]].reset_index(drop=True)
            hd, _ = evs(dh, "4h", 0.0)
            hb = hd.drop_duplicates(["p", "side"])
            leg = hb[(hb["ts"] <= r.ts) & (r.ts <= hb["bos_ts"] + SEC["4h"] - 1)]
            p, k = int(r.p), int(r.k_idx)
            t = dl["ts"].to_numpy()
            i0, i1 = max(0, p - 60), min(len(dl) - 1, k + 60)
            w = dl.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.4)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            for lg in leg.itertuples():
                a0, a1 = np.searchsorted(t, lg.ts), np.searchsorted(t, lg.bos_ts + SEC["4h"])
                ax.axvspan(max(a0, i0), min(a1, i1), color="#f4a261" if lg.side == r.side else "#999", alpha=0.15)
                ax.hlines(lg.bos_level, max(a0, i0), i1, colors="k", linestyles="--", lw=1)
            o = dl.reset_index(drop=True)
            far = o["low"].iat[p] if r.side > 0 else o["high"].iat[p]
            near = max(o["open"].iat[p], o["close"].iat[p]) if r.side > 0 else min(o["open"].iat[p], o["close"].iat[p])
            ax.add_patch(Rectangle((p, min(far, near)), k - p, abs(near - far), color="#457b9d", alpha=0.35))
            ax.scatter([k], [near], marker="^" if r.side > 0 else "v", s=100,
                       color="green" if r.best >= 1 else "red", zorder=5)
            ax.set_ylim(w["low"].min() * 0.9995, w["high"].max() * 1.0005)
            ax.set_title(f"{r.sym} 15m zone {'bull' if r.side > 0 else 'bear'}  -> {r.best:.1f}R"
                         + ("  stopped" if r.stopped else ""), fontsize=9)
        fig.suptitle(f"15m zones {title} | orange: the 4h break's leg (grey if the other way), dashed: the broken 4h "
                     "level, blue: the 15m zone, triangle: its first return (green made 1R)", fontsize=10)
        fig.tight_layout()
        fig.savefig(OUT / f"nested_{col}.png", dpi=80)
        plt.close(fig)
    print("plots written", flush=True)


def stack():
    """The frozen stacking test (`nested_stack.json`): thresholds from the MT5 run, judged on Binance."""
    import json
    rule = json.loads((HERE / "nested_stack.json").read_text())
    mt5 = pd.read_pickle(os.environ["MT5_NESTED"])
    binance = pd.read_pickle(os.environ["BINANCE_NESTED"])
    mt5 = mt5[~mt5["family"].str.startswith("deriv")]
    rng = np.random.default_rng(13)
    split = pd.Timestamp("2024-07-01", tz="UTC").timestamp()
    rows = []
    for ltf in LTFS:
        disc = mt5[mt5["ltf"] == ltf]
        cuts = {"er": float(np.nanquantile(disc["er_r"].astype(float), 0.6)),
                "stretch": float(np.nanquantile(disc["stretch"].astype(float), 0.8))}
        print(f"{ltf} thresholds from MT5 (frozen): er_r >= {cuts['er']:.4f}, stretch >= {cuts['stretch']:.4f}")
        for name, d in (("MT5 (discovery)", disc), ("Binance (judge)", binance[binance["ltf"] == ltf])):
            ins = d["inside_4h"].astype(bool)
            if os.environ.get("CAUSAL"):  # the HTF break must be known before the LTF entry (the return bar)
                ins = ins & (d["inside_known_4h"].astype(float) <= d["ret_ts"].astype(float))
                print(f"  {name} {ltf}: {int(d['inside_4h'].astype(bool).sum())} inside, "
                      f"{int(ins.sum())} with the 4h break known before the entry")
            er_ok = d["er_r"].astype(float) >= cuts["er"]
            st_ok = d["stretch"].astype(float) >= cuts["stretch"]
            for key, m in (("all LTF zones", np.ones(len(d), bool)), ("S0", ins), ("S1", ins & er_ok),
                           ("S2", ins & st_ok), ("S3", ins & er_ok & st_ok)):
                x = d[m].copy()
                if len(x) < 20:
                    rows.append(dict(ltf=ltf, data=name, rule=key, n=len(x)))
                    continue
                x["day"] = x["ret_ts"] // 86400
                days = x.groupby("day")["R"].agg(["sum", "count"])
                boots = [days["sum"].values[s_].sum() / days["count"].values[s_].sum()
                         for s_ in (rng.integers(0, len(days), len(days)) for _ in range(2000))]
                lo, hi = np.quantile(boots, [0.05, 0.95])
                rows.append(dict(ltf=ltf, data=name, rule=key, n=len(x), P1R=(x["best"] >= 1).mean(), R=x["R"].mean(),
                                 lo=lo, hi=hi, R_before=x.loc[x["ret_ts"] < split, "R"].mean(),
                                 R_after=x.loc[x["ret_ts"] >= split, "R"].mean()))
    t = pd.DataFrame(rows).round(3)
    pd.set_option("display.width", 250)
    print(t.to_string(index=False))
    t.to_csv(OUT / "stack.csv", index=False)
    b30 = t[(t["ltf"] == "30m") & (t["data"] == "Binance (judge)")].set_index("rule")
    for key in ("S1", "S2", "S3"):
        r = b30.loc[key] if key in b30.index else None
        ok = r is not None and r.get("R_before", -1) > 0 and r.get("R_after", -1) > 0 and r.get("lo", -1) > 0
        print(f"{key}: {'PASSES' if ok else 'fails'} ({rule['rules'][key]})")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    {"run": run, "plot": plot, "stack": stack}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
