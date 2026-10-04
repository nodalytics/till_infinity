"""Paper log of the FX 1h gap fade at every reopen, from the lab's MT5 bridge (read-only).

The fade was picked and confirmed by `mean_reversion.py` (`mr_selected.json`: gap|H>=0.45, FX, 1h, own exit)
and is under suspicion of being the bid bars' wide reopening spread (`gapfade_replay_rule.json`). This
logs each reopen as it happens, with the frozen rule applied exactly, and the quotes a trader would
actually have faced, so the fade can be judged on reopens that did not exist when it was found.

The frozen rule (mr_rule.json "gap", mr_selected.json): on the 1h bars, the first bar after a hole in the
clock; gap = its open - the last close before the hole (Friday's); a long when gap <= -0.5 ATR(14) of the
last bar before the hole, a short when gap >= +0.5 ATR (the same rule on the chart negated); only when
the trailing 100-bar Hurst exponent at that last bar is >= 0.45. Entry at the reopen bar's open; target
Friday's close; stop |gap| + 0.1 ATR beyond the open; out at the close of the 8th bar from the reopen bar.

  MODE=loop   poll the bridge (every 30 s from Friday 20:00 to Monday 01:00 UTC, every 15 min otherwise);
              log every reopen of the 12 pairs (signal or not) to gapfade_reopens.csv, and an hour later
              the measured reopen spreads to gapfade_spreads.csv
  MODE=once   one poll
  MODE=smoke  apply the rule to the most recent reopen in the bridge's bars and print it, without logging
  MODE=score  grade logged signals: the frozen R on the bridge's bid bars, and the tick replay at the first
              executable price (ask for longs, bid for shorts)

  OUT=out/paper_gapfade MR_OUT=out/mr python research/ideas/paper_gapfade.py   (with the bridge's env set)
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import mean_reversion as M  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/paper_gapfade"))
MR_OUT = Path(os.environ.get("MR_OUT", os.path.expanduser("~/till_infinity/out/mr")))
LOG = OUT / "gapfade_reopens.csv"
SPREADS = OUT / "gapfade_spreads.csv"
PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP",
         "AUDJPY", "USDCNH")
HISTORY = 600  # 1h bars for ATR(14) and the 100-bar Hurst; Wilder's ATR forgets its seed long before this
H = max(1, int(M.GAP_HOURS * 3600 / M.SEC["1h"]))
HOT, COLD, SPACING = 30, 900, 0.5


def client():
    import httpx
    key = os.environ.get("TRADING_MT5_API_KEY", "")
    return httpx.Client(headers={"Accept": "application/json", **({"X-API-Key": key} if key else {})}, timeout=90)


BASE = os.environ.get("TRADING_MT5_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1"


def _ms(v):
    if v is None:
        return None
    if isinstance(v, int | float):
        return int(v) if v > 1e11 else int(v * 1000)
    try:
        return int(datetime.fromisoformat(str(v)).replace(tzinfo=UTC).timestamp() * 1000)  # the bridge's naive UTC
    except ValueError:
        return None


def _rows(payload):
    if isinstance(payload, list):
        return payload
    for k in ("data", "rates", "ticks", "result", "items"):
        if isinstance(payload, dict) and isinstance(payload.get(k), list):
            return payload[k]
    return []


def stamp(s):
    return datetime.fromtimestamp(s, UTC).strftime("%Y-%m-%d %H:%M:%S")


def rates(cl, sym, n=HISTORY):
    """The last n 1h bid bars, the forming one included, oldest first."""
    r = cl.get(f"{BASE}/symbols/rates/pos", params={"symbol": sym, "timeframe": "H1", "num_bars": n})
    if r.status_code != 200:
        return None
    rows = [x for x in _rows(r.json()) if isinstance(x, dict)]
    if not rows:
        return None
    d = pd.DataFrame({"ts": [(_ms(x.get("time")) or 0) // 1000 for x in rows],
                      **{k: [float(x.get(k, np.nan)) for x in rows] for k in ("open", "high", "low", "close")},
                      "spread": [float(x.get("spread", np.nan)) for x in rows]})
    return d[d["ts"] > 0].drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def ticks(cl, sym, a, b):
    r = cl.get(f"{BASE}/symbols/ticks/{sym}/range", params={"date_from": stamp(a), "date_to": stamp(b)})
    if r.status_code != 200:
        return pd.DataFrame(columns=["ts_ms", "bid", "ask"])
    rows = _rows(r.json())
    d = pd.DataFrame({"ts_ms": [_ms(x.get("time_msc")) or _ms(x.get("time")) for x in rows],
                      "bid": [x.get("bid") for x in rows], "ask": [x.get("ask") for x in rows]}).dropna()
    return d[(d["bid"] > 0) & (d["ask"] > 0)].sort_values("ts_ms").reset_index(drop=True)


def evaluate(d, s):
    """The frozen rule at reopen bar s of bars d (s must open after a hole)."""
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    t = s - 1
    a = M.atr(h[:s], l[:s], c[:s])  # bars up to Friday's last only
    _, hu, _ = M.regimes(c[:s])
    gap = o[s] - c[t]
    side = 1 if gap <= -M.GAP_ATR * a[t] else (-1 if gap >= M.GAP_ATR * a[t] else 0)
    risk = abs(gap) + M.PAD * a[t]
    sig = bool(side != 0 and np.isfinite(hu[t]) and hu[t] >= M.HU_T and risk <= M.MAX_RISK * a[t])
    return dict(reopen_ts=int(d["ts"].iat[s]), fri_bar_ts=int(d["ts"].iat[t]), hole_h=(d["ts"].iat[s] - d["ts"].iat[t]) / 3600,
                fri_close=c[t], open_bid=o[s], atr=float(a[t]), hurst=float(hu[t]), gap=gap, gap_atr=gap / a[t],
                side=side, signal=sig, stop=(o[s] - side * risk) if side else np.nan, target=c[t] if side else np.nan,
                risk=risk if side else np.nan, bar_spread_field=float(d["spread"].iat[s]))


def reopen_bars(d, last=3):
    """Indices of the last few bars that open after a hole in the clock (mcfl.synth.gaps' rule)."""
    ts = d["ts"].to_numpy(np.int64)
    g = np.r_[False, np.diff(ts) > 3600]
    return [s for s in range(max(1, len(d) - last), len(d)) if g[s] and s >= 200]


def _seen():
    if not LOG.exists():
        return set()
    old = pd.read_csv(LOG)
    return set(zip(old["sym"], old["reopen_ts"]))


def once(cl):
    OUT.mkdir(parents=True, exist_ok=True)
    seen = _seen()
    new = []
    for sym in PAIRS:
        try:
            probe = rates(cl, sym, 3)
            time.sleep(SPACING)
            if probe is None or len(probe) < 2:
                continue
            pts = probe["ts"].to_numpy(np.int64)
            fresh = [int(pts[i + 1]) for i in np.flatnonzero(np.diff(pts) > 3600) if (sym, int(pts[i + 1])) not in seen]
            if not fresh:
                continue
            d = rates(cl, sym)
            time.sleep(SPACING)
            if d is None:
                continue
            for s in reopen_bars(d):
                if (sym, int(d["ts"].iat[s])) in seen:
                    continue
                e = evaluate(d, s)
                tk = ticks(cl, sym, e["reopen_ts"], time.time() + 60)
                time.sleep(SPACING)
                first = tk.iloc[0] if len(tk) else None
                new.append(dict(logged_at=int(time.time()), sym=sym, **e,
                                first_tick_ms=int(first["ts_ms"]) if first is not None else None,
                                first_bid=float(first["bid"]) if first is not None else np.nan,
                                first_ask=float(first["ask"]) if first is not None else np.nan,
                                first_spread=float(first["ask"] - first["bid"]) if first is not None else np.nan,
                                ticks_so_far=len(tk),
                                med_spread_so_far=float((tk["ask"] - tk["bid"]).median()) if len(tk) else np.nan,
                                lag_s=int(time.time() - (first["ts_ms"] / 1000 if first is not None else e["reopen_ts"]))))
                print(f"{stamp(time.time())} {sym} reopen {stamp(e['reopen_ts'])}: gap {e['gap_atr']:+.2f} ATR, "
                      f"Hurst {e['hurst']:.3f}, side {e['side']:+d}, signal {e['signal']}, first spread "
                      f"{new[-1]['first_spread']}", flush=True)
        except Exception as exc:  # noqa: BLE001 - keep logging through a bad request
            print(f"{stamp(time.time())} {sym}: {exc!r}", flush=True)
    if new:
        pd.DataFrame(new).to_csv(LOG, mode="a", header=not LOG.exists(), index=False)
    spreads(cl)


def spreads(cl):
    """An hour after each logged reopen: the spread over the first 1, 5, 15 and 60 minutes, from ticks."""
    if not LOG.exists():
        return
    log = pd.read_csv(LOG)
    done = set(pd.read_csv(SPREADS)[["sym", "reopen_ts"]].itertuples(index=False, name=None)) if SPREADS.exists() else set()
    rows = []
    for _, r in log.iterrows():
        key = (r["sym"], int(r["reopen_ts"]))
        if key in done or time.time() < r["reopen_ts"] + 3900:
            continue
        tk = ticks(cl, r["sym"], int(r["reopen_ts"]), int(r["reopen_ts"]) + 3900)
        time.sleep(SPACING)
        if not len(tk):
            continue
        sp = (tk["ask"] - tk["bid"]).to_numpy()
        el = (tk["ts_ms"].to_numpy() - tk["ts_ms"].iat[0]) / 60000.0
        rows.append(dict(sym=r["sym"], reopen_ts=int(r["reopen_ts"]), first=sp[0],
                         **{f"med{m}": float(np.median(sp[el < m])) for m in (1, 5, 15, 60)},
                         at60=float(sp[el >= 60][0]) if (el >= 60).any() else np.nan, atr=r["atr"]))
    if rows:
        pd.DataFrame(rows).to_csv(SPREADS, mode="a", header=not SPREADS.exists(), index=False)


def hot(now):
    """Friday 20:00 UTC to Monday 01:00 UTC: the weekend reopen window, polled every 30 s."""
    t = pd.Timestamp(now, unit="s", tz="UTC")
    wd, hr = t.dayofweek, t.hour
    return (wd == 4 and hr >= 20) or wd in (5, 6) or (wd == 0 and hr < 1)


def loop():
    with client() as cl:
        while True:
            try:
                once(cl)
            except Exception as exc:  # noqa: BLE001
                print(f"cycle failed: {exc!r}", flush=True)
            time.sleep(HOT if hot(time.time()) else COLD)


def smoke():
    """The most recent reopen in the bridge's bars, evaluated and printed; nothing logged."""
    with client() as cl:
        rows = []
        for sym in PAIRS:
            d = rates(cl, sym)
            time.sleep(SPACING)
            if d is None:
                print(f"{sym}: no bars", flush=True)
                continue
            ts = d["ts"].to_numpy(np.int64)
            g = np.flatnonzero(np.diff(ts) > 3600) + 1
            g = g[g >= 200]
            if not len(g):
                print(f"{sym}: no reopen in the last {len(d)} bars", flush=True)
                continue
            e = evaluate(d, int(g[-1]))
            tk = ticks(cl, sym, e["reopen_ts"], e["reopen_ts"] + 1800)
            time.sleep(SPACING)
            e["first_spread"] = float(tk["ask"].iat[0] - tk["bid"].iat[0]) if len(tk) else np.nan
            e["first_tick"] = stamp(tk["ts_ms"].iat[0] / 1000) if len(tk) else None
            rows.append(dict(sym=sym, **e))
        x = pd.DataFrame(rows)
        x["reopen"] = pd.to_datetime(x["reopen_ts"], unit="s")
        pd.set_option("display.width", 250)
        print(x[["sym", "reopen", "first_tick", "hole_h", "fri_close", "open_bid", "gap_atr", "atr", "hurst", "side",
                 "signal", "stop", "target", "first_spread", "bar_spread_field"]].round(5).to_string(index=False))
        OUT.mkdir(parents=True, exist_ok=True)
        x.to_csv(OUT / "smoke_last_reopen.csv", index=False)


def score():
    """Each logged signal, once its 8 hours are over: the frozen R on bid bars (cost: the weekday spread
    floor) and the tick replay entering at the first executable price."""
    log = pd.read_csv(LOG)
    log = log[log["signal"].astype(bool)]
    costs = json.loads((MR_OUT / "costs.json").read_text())
    rows = []
    with client() as cl:
        for _, r in log.iterrows():
            sym, s_ts, side = r["sym"], int(r["reopen_ts"]), int(r["side"])
            done = time.time() >= s_ts + (H + 1) * 3600
            d = rates(cl, sym)
            time.sleep(SPACING)
            if d is None or s_ts not in set(d["ts"]):
                continue
            s = int(np.flatnonzero(d["ts"].to_numpy() == s_ts)[0])
            f = d if side > 0 else M.flip(d)
            o, h, l, c = (f[k].to_numpy(float) for k in ("open", "high", "low", "close"))
            a = M.atr(h[:s], l[:s], c[:s])
            t = s - 1
            risk = c[t] - o[s] + M.PAD * a[t]
            e = np.array([s])
            own, *_ = M.sim(o, h, l, c, e, o[e], np.array([risk]), np.array([M.SLIP * a[t]]), np.zeros(len(c), bool),
                            H, np.array([c[t]]))
            frozen = float(own[0] - float(costs[sym][0]) / risk)
            tk = ticks(cl, sym, s_ts, s_ts + 3 * 3600)
            time.sleep(SPACING)
            t0 = np.nan
            if len(tk):
                bid, ask = tk["bid"].to_numpy(), tk["ask"].to_numpy()
                target, stop = r["target"], r["stop"]
                entry = ask[0] if side > 0 else bid[0]
                px = None
                for k in range(1, len(tk)):
                    if side > 0 and (bid[k] <= stop or bid[k] >= target):
                        px = bid[k] if bid[k] <= stop else target
                        break
                    if side < 0 and (ask[k] >= stop or ask[k] <= target):
                        px = ask[k] if ask[k] >= stop else target
                        break
                if px is None and s + H - 1 < len(d):
                    # after the tick window: the bid bars, a short's ask as bid + the weekday floor, as the replay
                    spr = float(costs[sym][0])
                    bo, bh, bl, bc = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
                    slip = M.SLIP * float(r["atr"])
                    j0 = int(np.searchsorted(d["ts"].to_numpy(), s_ts + 3 * 3600))
                    for j in range(j0, s + H):
                        if side > 0 and bl[j] <= stop:
                            px = min(bo[j], stop) - slip
                        elif side > 0 and bh[j] >= target:
                            px = max(bo[j], target)
                        elif side < 0 and bh[j] + spr >= stop:
                            px = max(bo[j] + spr, stop) + slip
                        elif side < 0 and bl[j] + spr <= target:
                            px = min(bo[j] + spr, target)
                        if px is not None:
                            break
                    if px is None:
                        px = bc[s + H - 1] + (spr if side < 0 else 0.0)
                if px is not None:
                    t0 = side * (px - entry) / r["risk"]
            rows.append(dict(sym=sym, reopen=stamp(s_ts), side=side, gap_atr=r["gap_atr"], frozen_R=frozen, T0_R=t0,
                             complete=done))
    x = pd.DataFrame(rows)
    x.to_csv(OUT / "gapfade_scored.csv", index=False)
    if len(x):
        cpl = x[x["complete"]]
        print(x.round(3).to_string(index=False))
        print(f"\n{len(log)} signals logged, {len(cpl)} complete: frozen R {cpl['frozen_R'].mean():+.3f}, "
              f"first executable price {cpl['T0_R'].mean():+.3f}")


def main():
    mode = os.environ.get("MODE", "once")
    if mode == "once":
        with client() as cl:
            once(cl)
    else:
        {"loop": loop, "smoke": smoke, "score": score}[mode]()


if __name__ == "__main__":
    main()
