"""The turning-point signature, traded: a forceful reversal bar at a 12-bar low.

Frozen in `turn_rule.json` before this ran (see `turns.py` for where the signature came from). Judged
on Binance perpetuals, reported on MT5 (where it was found) and against matched walks and against
entering at every 12-bar low.

  OUT=... MT5BT_DB=... MODE=run|plot python research/ideas/turn_trade.py
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

OUT = Path(os.environ.get("OUT", ".data/turn_trade"))
BIN = Path(os.environ.get("BINANCE", os.path.expanduser("~/till_infinity/data/binance")))
COINS = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "TRX")
MT5 = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US SP 500", "US Tech 100", "Germany 40", "US Oil", "BTCUSD", "ETHUSD")
SEC = {"1h": 3600, "4h": 14400}
SIGNALS = {"T1": ("DISPLACE_C",), "T2": ("BREACH_REVERT",), "T3": ("DELIVERY_SHIFT",),
           "T_any": ("DISPLACE_C", "BREACH_REVERT", "DELIVERY_SHIFT")}
TARGETS = (1, 2, 3)
FEE = 0.0007
SPLIT = pd.Timestamp("2024-01-01", tz="UTC").timestamp()


def _bin(coin, iv):
    z = np.load(BIN / f"{coin}USDT.klines.{iv}.npz")
    d = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close", "volume")})
    return d.rename(columns={"time": "ts"}).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def ups(df):
    """Bars where each production completed the up way (known_at), on this chart."""
    from mcfl.parse import parse
    n = len(df)
    out = {p: np.zeros(n, bool) for p in ("DISPLACE_C", "BREACH_REVERT", "DELIVERY_SHIFT")}
    for e in parse(df).entities:
        if e.type in out and 0 <= e.known_at < n:
            if getattr(e.dir, "name", str(e.dir)).upper() in ("UP", "U"):
                out[e.type][e.known_at] = True
    return out


def trades(df, side, cost_frac, spread, src, sym, iv):
    from mcfl import candles
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy()
    n = len(df)
    atr = np.asarray(candles.table(df)["atr"], float)
    low3 = pd.Series(l).rolling(3).min().to_numpy()
    prior = pd.Series(l).shift(3).rolling(9).min().to_numpy()
    at_low = low3 <= prior
    U = ups(df)
    H = max(1, int(5 * 86400 / SEC[iv]))
    rows = []
    for t in np.flatnonzero(at_low):
        if t + 1 >= n or not atr[t] > 0:
            continue
        fired = {k: any(U[p][t] for p in v) for k, v in SIGNALS.items()}
        entry = o[t + 1]
        stop = low3[t] - 0.1 * atr[t]
        risk = entry - stop
        if not risk > 0:
            continue
        cost = (cost_frac * abs(entry) if cost_frac else spread)
        res = {}
        for k in TARGETS:
            tgt = entry + k * risk
            R = None
            for j in range(t + 1, min(n, t + 1 + H)):
                if l[j] <= stop:
                    R = -1.0
                    break
                if h[j] >= tgt:
                    R = float(k)
                    break
            if R is None:
                R = (c[min(n - 1, t + H)] - entry) / risk
            res[f"R{k}"] = R - cost / risk
        rows.append(dict(src=src, sym=sym, iv=iv, side=side, t=t, ts=int(ts[t]), risk_atr=risk / atr[t], **fired, **res))
    return rows


def one(job):
    from mcfl import synth
    from mcfl.parse import flip
    venue, sym, iv, source = job
    if venue == "binance":
        try:
            df = _bin(sym, iv)
        except OSError:
            return None
        cost_frac, spread = FEE, 0.0
    else:
        import run as R
        from mt5bt import load_specs
        R.DB = os.environ.get("MT5BT_DB")
        df = R.load(sym, iv)
        if df is None:
            return None
        df = df.reset_index(drop=True)[["ts", "open", "high", "low", "close", "volume"]]
        spec = load_specs(R.DB).get(sym)
        cost_frac, spread = None, (R.spread_floor(sym, spec) * spec.point if spec is not None else 0.0)
    if source == "walk":
        ts = df["ts"].to_numpy()
        df = synth.matched_walk(df, seed=zlib.crc32(f"{venue}{sym}{iv}".encode()) % 100000).reset_index(drop=True)
        df["ts"] = ts[:len(df)]  # the walk keeps the real series' clock, for the halves and the day bootstrap
    rows = []
    for side, frame in ((1, df), (-1, flip(df))):
        rows += trades(frame, side, cost_frac, spread, f"{venue}:{source}", sym, iv)
    print(f"  {venue} {source} {sym} {iv}: {len(rows)} 12-bar lows", flush=True)
    return pd.DataFrame(rows)


def boot(x, rng, draws=2000):
    d = x.groupby(x["ts"] // 86400)["R"].agg(["sum", "count"])
    b = [d["sum"].values[s].sum() / d["count"].values[s].sum() for s in (rng.integers(0, len(d), len(d)) for _ in range(draws))]
    return np.quantile(b, [0.05, 0.95])


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("binance", c, iv, s) for s in ("real", "walk") for iv in ("1h", "4h") for c in COINS] + \
           [("mt5", m, iv, s) for s in ("real", "walk") for iv in ("1h", "4h") for m in MT5]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 20))) as pool:
        got = [g for g in pool.map(one, jobs) if g is not None and len(g)]
    d = pd.concat(got, ignore_index=True)
    d.to_pickle(OUT / "turn_trades.pkl.gz")
    rng = np.random.default_rng(21)
    rows = []
    for src, g in d.groupby("src"):
        for name in ("all 12-bar lows", *SIGNALS):
            x = g if name == "all 12-bar lows" else g[g[name]]
            for k in TARGETS:
                y = x.assign(R=x[f"R{k}"])
                lo, hi = boot(y, rng) if len(y) > 30 else (np.nan, np.nan)
                rows.append(dict(src=src, signal=name, target=f"{k}R", n=len(y), R=y["R"].mean(), lo=lo, hi=hi,
                                 win=(y["R"] > 0).mean(), R_before=y.loc[y["ts"] < SPLIT, "R"].mean(),
                                 R_after=y.loc[y["ts"] >= SPLIT, "R"].mean(),
                                 R_1h=y.loc[y["iv"] == "1h", "R"].mean(), R_4h=y.loc[y["iv"] == "4h", "R"].mean()))
    t = pd.DataFrame(rows).round(3)
    t.to_csv(OUT / "turn_trade.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    print(t.to_string(index=False))
    p = t[(t["src"] == "binance:real") & (t["signal"] == "T_any") & (t["target"] == "2R")].iloc[0]
    w = t[(t["src"] == "binance:walk") & (t["signal"] == "T_any") & (t["target"] == "2R")].iloc[0]
    a = t[(t["src"] == "binance:real") & (t["signal"] == "all 12-bar lows") & (t["target"] == "2R")].iloc[0]
    ok = p["R"] > 0 and p["lo"] > 0 and p["R_before"] > 0 and p["R_after"] > 0 and p["R"] > w["R"] and p["R"] > a["R"]
    print(f"\nPRIMARY (T_any, 2R, Binance): R {p['R']:+.3f} [{p['lo']:+.3f}, {p['hi']:+.3f}], before {p['R_before']:+.3f}, "
          f"after {p['R_after']:+.3f}; walk {w['R']:+.3f}; all lows {a['R']:+.3f} -> {'PASSES' if ok else 'fails'}")


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mcfl.parse import flip
    d = pd.read_pickle(OUT / "turn_trades.pkl.gz")
    d = d[(d["src"] == "binance:real") & d["T_any"] & (d["iv"] == "1h")]
    rng = np.random.default_rng(4)
    for tag, sub in (("winners", d[d["R2"] > 0]), ("losers", d[d["R2"] <= 0])):
        pick = sub.iloc[rng.choice(len(sub), min(6, len(sub)), replace=False)]
        fig, axes = plt.subplots(2, 3, figsize=(20, 10))
        for ax, (_, r) in zip(axes.flat, pick.iterrows(), strict=False):
            df = _bin(r.sym, r.iv)
            frame = df if r.side > 0 else flip(df)
            t = int(r.t)
            i0, i1 = max(0, t - 30), min(len(df) - 1, t + 40)
            w = df.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            from mcfl import candles
            atr = np.asarray(candles.table(frame)["atr"], float)
            low3 = frame["low"].iloc[t - 2:t + 1].min()
            entry = frame["open"].iat[t + 1]
            stop = low3 - 0.1 * atr[t]
            risk = entry - stop
            s = r.side
            for lvl, col, lab in ((stop, "red", "stop"), (entry, "k", "entry"), (entry + 2 * risk, "green", "2R")):
                ax.hlines(s * lvl, t + 1, i1, colors=col, lw=1)
            ax.axvline(t, color="purple", lw=1, ls=":")
            names = [k for k in ("T1", "T2", "T3") if r[k]]
            lab = {"T1": "DISPLACE_C", "T2": "BREACH_REVERT", "T3": "DELIVERY_SHIFT"}
            ax.set_title(f"{r.sym}USDT {r.iv} {'long' if s > 0 else 'short'}  "
                         f"{'+'.join(lab[k] for k in names)}  -> {r.R2:+.2f}R at 2R  "
                         f"{pd.Timestamp(r.ts, unit='s'):%Y-%m-%d %H:%M}", fontsize=9)
        fig.suptitle(f"turn signature trades ({tag}): purple dotted - the signal bar at a 12-bar low; entry next open (black), "
                     "stop under the low (red), 2R target (green)", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"turn_trades_{tag}.png", dpi=80)
        plt.close(fig)
    print("plots written", flush=True)


def main():
    {"run": run, "plot": plot}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
