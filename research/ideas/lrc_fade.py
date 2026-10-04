"""R4b: production's own `fade-to-value`, replayed on history through production's own code.

Addendum to `lrc_rule.json` (frozen before its run, after R1-R5 had run). R4 is the 'fade to value'
the desk lost on, written from the desk's description; R4b is the strategy the desk actually runs
under that name: `till_infinity/trading/strategies/swing.py` `FadeToValue`, imported read-only.

The replay: each series' 15m bars (and 30m, 1h, 2h, 4h resampled from them) are streamed through
production's `structures.engine.Engine` in the order they close; every actionable call becomes a
signal through `Call.to_signal` and its `to_dict` payload, exactly the message `trading` reads.
Every payload goes to `FadeToValue.observe` (the valuation book); payloads on 15m and 30m go to
`FadeToValue.consider` with a tick at the bar's close and the broker's spread. Its Intent is the
trade: entry, stop, target and hold as production computes them. Two copies run side by side:

  GATED  production's `consider`, its `quality()` gates included
  CORE   the same with `quality()` switched off (value, distance, side, stop, target, hold)

Not replayed (they live in the service, not the strategy, or need live services): the confluence
zone grouping and the context-anchoring requirement, the 4h rejection candle, the break model's
`break_probability`, origins / level-range extras, momentum (absent, so its gate is skipped by
design), break-even and trailing protection, sizing limits, one-position-per-symbol across
strategies (one position per series per variant is kept here).

  OUT=... MT5BT_DB=... MODE=run|agg python research/ideas/lrc_fade.py
"""
from __future__ import annotations

import heapq
import os
import sys
import time as _time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import lrc_retest as L  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/lrc_fade"))
START = pd.Timestamp(os.environ.get("START", "2019-01-01"), tz="UTC").timestamp()  # all the 15m history there is
IVS = ("15m", "30m", "1h", "2h", "4h")
SEC = {"15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400}
ENTRY_IVS = ("15m", "30m")
SNAP_VOL = 12.0  # book levels kept around each entry-timeframe call, in vol units (fade looks within 8)
CALL_KEYS = ("vol_bps", "probability", "probability_up", "strength", "record_n", "own_touches", "risk_vol",
             "edge", "base_rate_up", "zone_low", "zone_high")
NS = L.NS
STEPS = 64


class Clock:
    """Simulated wall clock: production's book forgets levels by `time.time()`."""
    now = 0.0

    @classmethod
    def time(cls):
        return cls.now

    def __getattr__(self, name):  # anything else from the time module
        return getattr(_time, name)


def patch_clock():
    import till_infinity.trading.book as book
    import till_infinity.trading.strategies.swing as swing
    fake = Clock()
    book.time = fake
    swing.time = fake


def strategies():
    from till_infinity import trading as td
    from till_infinity.trading.strategies.swing import FadeToValue

    class Core(FadeToValue):
        def quality(self, feed, features, side, interval=""):  # noqa: ARG002
            return None

    made = td.Settings(symbols=("x",), account_equity=1e9, paper_equity=1e9)
    made.max_spread_risk_fraction = 0.0
    return {"GATED": FadeToValue(made), "CORE": Core(made)}


def stream(feed, frames):
    """Bars in the order they close; at one instant the slower timeframe first."""
    def gen(iv, df):
        for t, o, h, lo, c in zip(df["ts"].to_numpy(), df["open"].to_numpy(), df["high"].to_numpy(),
                                  df["low"].to_numpy(), df["close"].to_numpy(), strict=True):
            yield (int(t) + SEC[iv], -SEC[iv]), {"feed": feed, "venue": "replay", "interval": iv, "time": int(t),
                                                 "open": float(o), "high": float(h), "low": float(lo),
                                                 "close": float(c)}
    return heapq.merge(*(gen(iv, df) for iv, df in frames.items()), key=lambda x: x[0])


def replay(feed, df15, spread_px):
    """Every Intent each variant produces: (variant, call time, interval, side, entry, stop, target, hold)."""
    from till_infinity.structures import zma as zm
    from till_infinity.structures.engine import Engine
    from till_infinity.trading.models import Intent, Side, SymbolSpec, Tick
    patch_clock()
    frames = {"15m": df15}
    for iv in IVS[1:]:
        frames[iv] = L.resample(df15, SEC[iv])
    engine = Engine(intervals=IVS)
    engine.consensus.single_source = frozenset({feed})
    strats = strategies()
    spec = SymbolSpec(symbol=feed, digits=10, point=1e-10, tick_size=1e-10, tick_value=1.0, volume_min=1e-6,
                      volume_max=1e12, volume_step=1e-6, contract_size=1.0)
    out, refusals, calls_n = [], {}, 0
    calls, snaps = [], []
    for (_key, bar) in stream(feed, frames):
        Clock.now = bar["time"] + SEC[bar["interval"]]
        for call in engine.observe_bar(bar):
            if not call.inference.actionable:
                continue
            calls_n += 1
            sig = call.to_signal(engine.vol.of(call.feed, call.interval), engine.zma.of(call.feed, call.interval),
                                 engine.cycles.of(call.feed), None, engine.levels(call.feed, call.interval), 1.0, "",
                                 venue="replay", anchor=engine.zma.of(call.feed, zm.ANCHOR),
                                 broke=engine.break_of(call.feed, call.interval))
            payload = sig.to_dict()
            payload["time"] = Clock.now
            close = bar["close"]
            ft = payload["features"]
            calls.append(dict(t=Clock.now, iv=payload["interval"], level=ft.get("level", np.nan),
                              above=float(call.inference.side.name == "ABOVE"),
                              up=float(payload.get("direction") == "up"), spot=close,
                              **{k: ft.get(k, np.nan) for k in CALL_KEYS}))
            if payload["interval"] in ENTRY_IVS:
                unit = close * ft.get("vol_bps", 0.0) / 10_000
                book = [(x.price, x.interval, x.probability, x.strength, x.touches, x.when)
                        for x in strats["GATED"].book.levels(feed)
                        if unit > 0 and abs(x.price - close) <= SNAP_VOL * unit]
                snaps.append(dict(t=Clock.now, iv=payload["interval"], spot=close, book=book,
                                  **{k: v for k, v in ft.items() if isinstance(v, int | float)}))
            tick = Tick(feed, bid=close - spread_px / 2, ask=close + spread_px / 2, time=Clock.now)
            for name, st in strats.items():
                st.observe(payload)
                if payload["interval"] not in ENTRY_IVS:
                    continue
                v = st.consider(payload, spec=spec, tick=tick, equity=1e9)
                if isinstance(v, Intent):
                    out.append(dict(variant=name, t=Clock.now, iv=payload["interval"],
                                    side=1 if v.side is Side.BUY else -1, entry=v.entry, mid=close, stop=v.stop,
                                    target=v.target, hold=float(v.hold or 0.0) or 4 * 3600.0,
                                    distance_vol=float(v.features.get("distance_vol", np.nan))))
                else:
                    k = (name, str(getattr(v, "gate", "") or type(v).__name__))
                    refusals[k] = refusals.get(k, 0) + 1
    return out, refusals, calls_n, calls, snaps


def simulate(df15, intents, spread_px, seed=None):
    """Each intent traded on the 15m bars from the next bar's open, one position per variant at a time:
    stop, target, or out at the close when the hold runs out. R against |entry - stop|, net of the
    spread; 0.05 ATR(15m) slippage on stop fills. Also the coin twin (random side, same distances)."""
    ts = df15["ts"].to_numpy(np.int64)
    up = {k: df15[k].to_numpy(float) for k in ("open", "high", "low", "close")}
    dn = {"open": -up["open"], "close": -up["close"], "high": -up["low"], "low": -up["high"]}
    a = L.atr(up["high"], up["low"], up["close"])
    rng = np.random.default_rng(seed)
    rows, busy = [], {}
    for it in sorted(intents, key=lambda x: x["t"]):
        k = int(np.searchsorted(ts, it["t"]))  # the first 15m bar opening at or after the call's close
        if k >= len(ts) - 1 or busy.get(it["variant"], -1) >= k:
            continue
        s = it["side"]
        risk = abs(it["entry"] - it["stop"])
        if not risk > 0:
            continue
        reward = abs(it["target"] - it["entry"])
        n_hold = max(1, int(round(it["hold"] / 900)))
        res = {}
        for tag, side in (("", s), ("tw_", s if rng.random() < 0.5 else -s), ("rev_", -s)):
            arr = up if side > 0 else dn
            e = side * it["mid"]  # mid; the spread is charged as cost
            stop, tgt = e - risk, e + reward
            r, xb, mfe = trade(arr, k, e, stop, tgt, n_hold, a[k - 1], risk)
            res[f"{tag}R"] = r - spread_px / risk
            res[f"{tag}mfe"] = mfe
            if tag == "":
                busy[it["variant"]] = xb
        rows.append(dict(it, f=k, ts=int(ts[k]), risk_atr=risk / a[k - 1], rr=reward / risk, **res))
    return rows


def trade(arr, k, e, stop, tgt, n_hold, a_t, risk):
    o, h, l, c = arr["open"], arr["high"], arr["low"], arr["close"]
    end = min(len(c) - 1, k + n_hold - 1)
    hh, ll, oo = h[k:end + 1], l[k:end + 1], o[k:end + 1]
    js = np.flatnonzero(ll <= stop)
    jt = np.flatnonzero(hh >= tgt)
    js = js[0] if len(js) else None
    jt = jt[0] if len(jt) else None
    if js is not None and (jt is None or js <= jt):
        r, xb = (min(oo[js], stop) - L.SLIP * a_t - e) / risk, k + js
    elif jt is not None:
        r, xb = (max(oo[jt], tgt) - e) / risk, k + jt
    else:
        r, xb = (c[end] - e) / risk, end
    mfe = L.reach(h, l, k, e, stop, risk, None if l[k] <= stop else h[k])
    return r, xb, mfe


def load15(venue, sym):
    df, cost = L.load(venue, sym, "15m")
    if df is None:
        return None, None
    df = df[df["ts"] >= START].reset_index(drop=True)
    return df, (float(np.median(cost)) if len(df) else None)


def walk15(df, source, seed):
    """An iid or GARCH walk in log price at the series' own level and volatility, 64 sub-steps a bar."""
    from mcfl import synth
    c = df["close"].to_numpy(float)
    lr = np.diff(np.log(c))
    sig = float(np.std(lr))
    gen = synth.walk if source == "walk" else synth.garch
    w = gen(len(df), sigma=sig, seed=seed, steps=STEPS).iloc[:len(df)]
    shift = np.log(c[0]) - synth.START
    out = pd.DataFrame({k: np.exp(w[k].to_numpy(float) + shift) for k in ("open", "high", "low", "close")})
    out["ts"] = df["ts"].to_numpy()[:len(out)]
    out["volume"] = 0.0
    return out


def one(job):
    venue, sym, source = job
    tag = f"{venue}_{sym}_{source}".replace(" ", "-")
    part = OUT / "parts" / f"{tag}.pkl"
    if part.exists():
        return tag, "cached"
    df, spread = load15(venue, sym)
    if df is None or len(df) < 2000:
        return tag, "no data"
    a = L.atr(*(df[k].to_numpy(float) for k in ("high", "low", "close")))
    if venue in ("binance", "fresh"):
        spread = L.FEE * float(np.median(df["close"]))
    cost_atr = spread / float(np.median(a[50:]))
    if not cost_atr <= L.MAX_COST_ATR:
        pd.to_pickle(dict(dropped=True, cost_atr=cost_atr), part)
        return tag, f"dropped: cost {cost_atr:.2f} ATR"
    if source != "real":
        df = walk15(df, source, zlib.crc32(f"{tag}fade".encode()) % 100000)
        spread = cost_atr * float(np.median(L.atr(*(df[k].to_numpy(float) for k in ("high", "low", "close")))[50:]))
    t0 = _time.time()
    feed = sym.lower().replace(" ", "_")
    intents, refusals, ncalls, calls, snaps = replay(feed, df, spread)
    rows = simulate(df, intents, spread, zlib.crc32(f"{tag}twin".encode()) % 100000)
    d = pd.DataFrame(rows)
    if len(d):
        d["venue"], d["sym"], d["src"], d["cls"] = venue, sym, source, L.klass(venue, sym, "15m")
    pd.to_pickle(dict(trades=d, refusals=refusals, calls=ncalls, bars=len(df), cost_atr=cost_atr), part)
    # everything a later tuning study needs without replaying the engine again: the bars it ran on,
    # every actionable call, and each entry-timeframe call with the valuation book around it
    pd.to_pickle(dict(bars=df, spread=spread, calls=pd.DataFrame(calls), snaps=pd.DataFrame(snaps)),
                 OUT / "logs" / f"{tag}.pkl")
    return tag, f"{ncalls} calls, {len(intents)} intents, {len(d)} trades, {_time.time() - t0:.0f}s"


def jobs():
    mt5 = L.FX + L.METAL + L.INDEX + L.ENERGY + L.CRYPTO_MAJOR + L.DERIV_DIFFUSIVE + L.DERIV_JUMPY + L.RANGE_BREAK
    js = [("mt5", s) for s in mt5] + [("binance", c) for c in L.COINS] + [("deriv1s", s) for s in L.DERIV_1S]
    return [(v, s, src) for src in ("real", "walk", "garch") for v, s in js]


def run():
    (OUT / "parts").mkdir(parents=True, exist_ok=True)
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    js = jobs()
    if os.environ.get("ONLY"):
        js = [j for j in js if os.environ["ONLY"] in "_".join(j)]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 12))) as pool:
        for tag, msg in pool.map(one, js, chunksize=1):
            print(f"  {tag}: {msg}", flush=True)
    print("run done", flush=True)


def agg():
    rng = np.random.default_rng(44)
    T, refusals = [], {}
    for p in sorted((OUT / "parts").glob("*.pkl")):
        d = pd.read_pickle(p)  # our own parts
        if d.get("dropped") or not len(d["trades"]):
            continue
        T.append(d["trades"])
        src = p.stem.rsplit("_", 1)[1]
        for (var, why), k in d["refusals"].items():
            key = (src, var, str(why).split(" ")[0][:40])
            refusals[key] = refusals.get(key, 0) + k
    t = pd.concat(T, ignore_index=True)
    t.to_pickle(OUT / "fade_trades.pkl.gz")
    rows = []
    groups = [("ALL_NONDERIV", t["cls"].isin(L.NONDERIV)), ("ALL", t["cls"].notna())] + \
             [(c, t["cls"] == c) for c in L.CLASS_ORDER] + [("V10_1S", t["sym"] == "volatility_10_1s_index")]
    for var in ("GATED", "CORE"):
        for cls, m in groups:
            for iv in ("15m", "30m", "ALL"):
                x = t[m & (t["variant"] == var) & ((t["iv"] == iv) if iv != "ALL" else True)]
                for src in ("real", "walk", "garch", "twin", "reversed"):
                    if src in ("twin", "reversed"):
                        y = x[x["src"] == "real"]
                        col, mcol = ("tw_R", "tw_mfe") if src == "twin" else ("rev_R", "rev_mfe")
                    else:
                        y = x[x["src"] == src]
                        col, mcol = "R", "mfe"
                    if not len(y):
                        continue
                    R = y[col].to_numpy(float)
                    lo, hi, p = L.boot(y["ts"].to_numpy(np.int64), R, rng) if len(R) > 30 else (np.nan,) * 3
                    rows.append(dict(variant=var, cls=cls, iv=iv, src=src, n=len(R), R=R.mean(), lo=lo, hi=hi, p=p,
                                     win=(R > 0).mean(), rr=y["rr"].median(), risk_atr=y["risk_atr"].median(),
                                     **{f"P{N}": (y[mcol] >= N).mean() for N in NS}))
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "fade_table.csv", index=False)
    pd.DataFrame([dict(src=k[0], variant=k[1], reason=k[2], n=v) for k, v in refusals.items()]).sort_values(
        ["src", "variant", "n"], ascending=[True, True, False]).to_csv(OUT / "fade_refusals.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 400)
    print(tab[tab["iv"] == "ALL"].round(3).to_string(index=False))


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    tab = pd.read_csv(OUT / "fade_table.csv")
    classes = [c for c in ("ALL_NONDERIV",) + L.CLASS_ORDER + ("V10_1S",) if len(tab[tab["cls"] == c])]
    fig, axes = plt.subplots(2, len(classes), figsize=(3.3 * len(classes), 7), sharey=True, squeeze=False)
    for i, var in enumerate(("GATED", "CORE")):
        for j, cls in enumerate(classes):
            ax = axes[i, j]
            for src, st, col in (("real", "-o", "#1d3557"), ("walk", "--s", "#e76f51"), ("garch", ":^", "#2a9d8f"),
                                 ("twin", "-.d", "#9b5de5"), ("reversed", "-x", "#999999")):
                r = tab[(tab["variant"] == var) & (tab["cls"] == cls) & (tab["iv"] == "ALL") & (tab["src"] == src)]
                if len(r):
                    r = r.iloc[0]
                    ax.plot(NS, [r[f"P{N}"] for N in NS], st, color=col, ms=3, label=f"{src} {r['R']:+.3f} n{int(r['n'])}")
            ax.plot(NS, [1 / (N + 1) for N in NS], color="grey", lw=0.8, label="1/(N+1)")
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.set_ylim(0.005, 1)
            ax.set_title(f"{var} {cls}", fontsize=8)
            ax.legend(fontsize=5.5, loc="lower left")
    fig.suptitle("R4b, production's fade-to-value replayed: P(+N R before -1R), 15m+30m entries; legend: mean R after costs")
    fig.tight_layout()
    fig.savefig(OUT / "lrc_fade_pnr.png", dpi=70)
    plt.close(fig)


def main():
    {"run": run, "agg": agg, "plot": plot}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
