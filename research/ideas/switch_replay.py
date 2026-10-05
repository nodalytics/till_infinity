"""Long return streams for production's level strategies, replayed through production's own code.

For `strategy-switching.md`. The approach is `lrc_fade.py`'s (R4b), widened from one strategy to every
registered `LevelStrategy` that enters on 15m or 30m calls: each series' 15m bars (30m, 1h, 2h, 4h
resampled from them) stream through production's `structures.engine.Engine` in the order they close;
every actionable call becomes `Call.to_signal(...).to_dict()`, the message `trading` reads, with its
`confluence` set the way `structures/service.py` sets it (the call's level grouped with the other
timeframes' levels by `drawing.confluence.combine`; no zone, no confluence). Every payload goes to every
strategy's `observe`; payloads on 15m and 30m go to `consider` with a tick at the bar's close and the
broker's spread. Each Intent is traded on the 15m bars from the next bar's open: stop, target, or out at
the close when its hold runs out; R net of the spread, 0.05 ATR slippage on stops; one open position per
strategy per series. Production code is imported read-only and never modified.

Not replayed (they live in the service or need live services): one-zone-one-message deduplication, the
regime classifier's label, the break model's reading, macro / release features, the race model, the
momentum ensemble (absent, so its gates are silent by design), candle witnesses that need the service's
bar store, break-even and trailing protection, sizing and account limits.

Also logged per trade, from bars up to the decision bar only (the regime gate's inputs):
  vol_ratio  ATR(14) at the bar before entry over its median across the previous 30 days of 15m bars
  eff        24-hour efficiency ratio |c[k-1] - c[k-97]| / sum |dc| over the same 96 bars
  trend_with sign(c[k-1] - c[k-97]) * side: +1 trading with the last 24 hours' move

  LRC_DIR=... OUT=... MT5BT_DB=... MODE=run|agg python research/ideas/switch_replay.py
"""
from __future__ import annotations

import os
import sys
import time as _time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LRC_DIR = Path(os.environ.get("LRC_DIR", str(HERE)))
for p in (str(HERE.parents[1]), str(HERE.parent), str(HERE), str(LRC_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import lrc_fade as F  # noqa: E402
import lrc_retest as L  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/switch_replay"))
ENTRY_IVS = ("15m", "30m")
#: Not replayed: `council` asks a language model; `cycle-turn`/`cycle-turn-scalp` need the zma
#: and cycles permissions of a live service, which the zero-skill work shows are coin flips anyway.
SKIP = {"council"}
MAX_BARS = int(os.environ.get("MAX_BARS", "0"))  # smoke tests only


def patch_clock():
    F.patch_clock()
    import till_infinity.trading.strategies.scalper as sc
    import till_infinity.trading.strategies.strategy as stg
    for mod in (sc, stg):
        if hasattr(mod, "time"):
            mod.time = F.Clock()


def strategies():
    from till_infinity import trading as td
    from till_infinity.trading.strategies import strategy as stg
    stg.build(("fade-to-value",), td.Settings(symbols=("x",)))  # registers everything
    made = td.Settings(symbols=("x",), account_equity=1e9, paper_equity=1e9)
    made.max_spread_risk_fraction = 0.0
    out = {}
    for name, cls in sorted(stg.STRATEGIES.items()):
        if name in SKIP:
            continue
        try:
            st = cls(made)
        except Exception:  # noqa: BLE001 - a strategy that cannot be built here is reported as absent
            continue
        if not any(iv in getattr(st, "intervals", ()) for iv in ENTRY_IVS):
            continue
        out[name] = st
    return out


def regime(df15):
    """Per 15m bar k: (vol_ratio, eff, move sign) from bars before k only."""
    h, l, c = (df15[k].to_numpy(float) for k in ("high", "low", "close"))
    a = L.atr(h, l, c)
    med = pd.Series(a).rolling(2880, min_periods=500).median().to_numpy()
    vr = np.full(len(c), np.nan)
    vr[1:] = a[:-1] / med[:-1]
    dc = np.abs(np.diff(c, prepend=c[0]))
    path = pd.Series(dc).rolling(96).sum().to_numpy()
    move = np.full(len(c), np.nan)
    move[97:] = c[96:-1] - c[:-97]
    eff = np.full(len(c), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        eff[97:] = np.abs(move[97:]) / path[96:-1]
    return vr, eff, np.sign(move)


def replay(feed, df15, spread_px):
    from till_infinity.structures import zma as zm
    from till_infinity.structures.drawing import confluence as cf
    from till_infinity.structures.engine import Engine
    from till_infinity.trading.models import Intent, Side, Tick
    patch_clock()
    frames = {"15m": df15}
    for iv in F.IVS[1:]:
        frames[iv] = L.resample(df15, F.SEC[iv])
    engine = Engine(intervals=F.IVS)
    engine.consensus.single_source = frozenset({feed})
    strats = strategies()
    spec = F.SPEC(feed)
    out, refusals, errors, calls_n = [], {}, {}, 0
    for (_key, bar) in F.stream(feed, frames):
        F.Clock.now = bar["time"] + F.SEC[bar["interval"]]
        zones = None
        for call in engine.observe_bar(bar):
            if not call.inference.actionable:
                continue
            calls_n += 1
            sig = call.to_signal(engine.vol.of(call.feed, call.interval), engine.zma.of(call.feed, call.interval),
                                 engine.cycles.of(call.feed), None, engine.levels(call.feed, call.interval), 1.0, "",
                                 venue="replay", anchor=engine.zma.of(call.feed, zm.ANCHOR),
                                 broke=engine.break_of(call.feed, call.interval))
            payload = sig.to_dict()
            payload["time"] = F.Clock.now
            if zones is None:  # once per bar, as the service groups once per batch
                zones = cf.combine(engine.levels(feed), engine.reference(feed),
                                   volatility=lambda level: engine.vol.of(feed, level.interval))
            zone = next((z for z in zones if len(z.members) > 1 and any(m is call.level for m in z.members)), None)
            payload["confluence"] = list(zone.timeframes) if zone is not None else []
            close = bar["close"]
            tick = Tick(feed, bid=close - spread_px / 2, ask=close + spread_px / 2, time=F.Clock.now)
            for name, st in strats.items():
                try:
                    st.observe(payload)
                    if payload["interval"] not in ENTRY_IVS:
                        continue
                    v = st.consider(payload, spec=spec, tick=tick, equity=1e9)
                except Exception as exc:  # noqa: BLE001 - counted, never silent
                    k = (name, type(exc).__name__)
                    errors[k] = errors.get(k, 0) + 1
                    continue
                if isinstance(v, Intent):
                    out.append(dict(variant=name, t=F.Clock.now, iv=payload["interval"],
                                    side=1 if v.side is Side.BUY else -1, entry=v.entry, mid=close, stop=v.stop,
                                    target=v.target, hold=float(v.hold or 0.0) or 4 * 3600.0))
                else:
                    k = (name, str(getattr(v, "gate", "") or type(v).__name__))
                    refusals[k] = refusals.get(k, 0) + 1
    return out, refusals, errors, calls_n


def simulate(df15, intents, spread_px):
    """As `lrc_fade.simulate`, keeping each trade's exit bar and time and the regime inputs."""
    ts = df15["ts"].to_numpy(np.int64)
    up = {k: df15[k].to_numpy(float) for k in ("open", "high", "low", "close")}
    dn = {"open": -up["open"], "close": -up["close"], "high": -up["low"], "low": -up["high"]}
    a = L.atr(up["high"], up["low"], up["close"])
    vr, eff, mv = regime(df15)
    rows, busy = [], {}
    for it in sorted(intents, key=lambda x: x["t"]):
        k = int(np.searchsorted(ts, it["t"]))
        if k >= len(ts) - 1 or busy.get(it["variant"], -1) >= k:
            continue
        s = it["side"]
        risk = abs(it["entry"] - it["stop"])
        if not risk > 0 or not risk >= 0.25 * a[k - 1]:  # the desk's minimum risk, 0.25 ATR
            continue
        reward = abs(it["target"] - it["entry"])
        n_hold = max(1, int(round(it["hold"] / 900)))
        arr = up if s > 0 else dn
        e = s * it["mid"]
        r, xb, mfe = F.trade(arr, k, e, e - risk, e + reward, n_hold, a[k - 1], risk)
        busy[it["variant"]] = xb
        rows.append(dict(it, f=k, ts=int(ts[k]), xb=int(xb), exit_ts=int(ts[xb]) + 900, risk_atr=risk / a[k - 1],
                         rr=reward / risk, R=r - spread_px / risk, mfe=mfe, vol_ratio=vr[k], eff=eff[k],
                         trend_with=float(mv[k] * s)))
    return rows


def one(job):
    import logging
    logging.disable(logging.WARNING)
    venue, sym, source = job
    tag = f"{venue}_{sym}_{source}".replace(" ", "-")
    part = OUT / "parts" / f"{tag}.pkl"
    if part.exists():
        return tag, "cached"
    df, spread = F.load15(venue, sym)
    if df is None or len(df) < 2000:
        return tag, "no data"
    if MAX_BARS:
        df = df.iloc[:MAX_BARS].reset_index(drop=True)
    a = L.atr(*(df[k].to_numpy(float) for k in ("high", "low", "close")))
    if venue in ("binance", "fresh"):
        spread = L.FEE * float(np.median(df["close"]))
    cost_atr = spread / float(np.median(a[50:]))
    if not cost_atr <= L.MAX_COST_ATR:
        pd.to_pickle(dict(dropped=True, cost_atr=cost_atr), part)
        return tag, f"dropped: cost {cost_atr:.2f} ATR"
    if source != "real":  # the same walk seeds as R4b, so these are R4b's walks
        df = F.walk15(df, source, zlib.crc32(f"{venue}_{sym}_{source}".replace(" ", "-").encode() + b"fade") % 100000)
        spread = cost_atr * float(np.median(L.atr(*(df[k].to_numpy(float) for k in ("high", "low", "close")))[50:]))
    t0 = _time.time()
    feed = sym.lower().replace(" ", "_")
    intents, refusals, errors, ncalls = replay(feed, df, spread)
    d = pd.DataFrame(simulate(df, intents, spread))
    if len(d):
        d["venue"], d["sym"], d["src"], d["cls"] = venue, sym, source, L.klass(venue, sym, "15m")
    pd.to_pickle(dict(trades=d, refusals=refusals, errors=errors, calls=ncalls, bars=len(df), cost_atr=cost_atr), part)
    per = d.groupby("variant").size().to_dict() if len(d) else {}
    return tag, f"{ncalls} calls, {len(intents)} intents, {len(d)} trades {per}, errors {errors}, {_time.time() - t0:.0f}s"


def jobs():
    return F.jobs()


def run():
    (OUT / "parts").mkdir(parents=True, exist_ok=True)
    js = jobs()
    if os.environ.get("ONLY"):
        js = [j for j in js if os.environ["ONLY"] in "_".join(j)]
    if os.environ.get("SRC"):
        js = [j for j in js if j[2] in os.environ["SRC"].split(",")]
    js.sort(key=lambda j: j[0] != "binance")
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 12))) as pool:
        for tag, msg in pool.map(one, js, chunksize=1):
            print(f"  {tag}: {msg}", flush=True)
    print("run done", flush=True)


def agg():
    T, ref, err = [], {}, {}
    for p in sorted((OUT / "parts").glob("*.pkl")):
        d = pd.read_pickle(p)  # our own parts
        if d.get("dropped") or not len(d["trades"]):
            continue
        T.append(d["trades"])
        for (var, why), k in d["refusals"].items():
            ref[(d["trades"]["src"].iloc[0], var, str(why)[:40])] = ref.get((d["trades"]["src"].iloc[0], var, str(why)[:40]), 0) + k
        for (var, why), k in d["errors"].items():
            err[(var, why)] = err.get((var, why), 0) + k
    t = pd.concat(T, ignore_index=True)
    t.to_pickle(OUT / "prod_trades.pkl.gz")
    pd.DataFrame([dict(src=k[0], variant=k[1], reason=k[2], n=v) for k, v in ref.items()]).to_csv(
        OUT / "prod_refusals.csv", index=False)
    print(t.groupby(["variant", "src"]).agg(n=("R", "size"), R=("R", "mean")).round(3).to_string())
    print("errors", err)


def main():
    {"run": run, "agg": agg}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
