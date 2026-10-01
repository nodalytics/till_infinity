"""Part G (research/docs/ideas.md, `energy.py`): magnitude without direction, the whipsaw, and SL-only trades.

The expansion alert predicts a range expansion (AUC 0.78); a box straddle armed by it still lost,
and gross it made the same as unarmed (expansion.md). Before more trades: does the alert predict
two-sided *excursion*, does it carry any sign, when does the move come, and is the whipsaw what
kills the bracket?

Pre-registered (2026-10-01), before any run. Held-out rows only (the walk-forward model's 40%).

  groups    N = not compressed (pct > 0.2), Q = compressed with lift < 1, M = 1 <= lift < 2.5,
            A = the alert, lift >= 2.5; and lift deciles among compressed rows
  horizon   H = 16 bars; sigma = the 14-bar smoothed true range (log) at the arming bar
  G1        Y = max(MFE up, MFE down) over H, in sigma: P(Y > 2, 4, 6 sigma) by group
  G2        bits of mutual information of lift decile with |R_H| above its median, and with
            sign(R_H); each against 200 shuffles. P(up) by group
  G3        hazard of the first 3-sigma excursion, bar by bar, by group
  G4        P(Y > 4 sigma) and the bracket's EV by lift decile: monotone or not (Spearman)
  G5        the whipsaw: both box edges (16-bar high and low) touched within H; and after a first
            breakout, the share that comes back to the other edge
  trades    SL-only. Initial stop at the opposite box edge (box height + spread); then a trailing
            stop k sigma behind the best price of completed bars; no take-profit; 96 bars at most.
              A  any compressed bar, two-sided OCO bracket
              B  the alert, two-sided OCO bracket
              C  any compressed bar, one stop order in the box's drift (close against box middle)
              D  the alert, the same
            primary: entry buffer d = 0, trail k = 2. Anti-whipsaw variants on A and B:
            d = 0.5 sigma, d = 1 sigma, close-confirmed (enter at the next open after a close
            beyond the edge, within 16 bars), and k = 3. 20 trades configurations in all, plus the
            10 decile cells, which are descriptive. Judged in R net of spread and swap, both halves,
            and B's primary against 12 GARCH walks.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from mt5bt import Book, Costs, load_bars, load_specs, run  # noqa: E402
from mt5bt.data import EXAMPLE_SPECS  # noqa: E402
from mt5bt.nulls import garch_walk  # noqa: E402
from mt5bt.report import day_bootstrap  # noqa: E402
from till_infinity.shared import frozen  # noqa: E402
from till_infinity.structures.learning import expansion as ex  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/expansion"))
SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
SECONDS = {"15m": 900, "1h": 3600}
H, BOX, MAXHOLD = 16, 16, 96
RNG = np.random.default_rng(17)


def state(bars: pd.DataFrame) -> pd.DataFrame:
    """sigma (smoothed log true range), its percentile, the box, and the forward path stats."""
    h, l, c = (np.log(bars[k].to_numpy()) for k in ("high", "low", "close"))
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    sig = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean()
    pct = sig.rolling(1500, min_periods=300).rank(pct=True).to_numpy()
    hi = pd.Series(h).rolling(BOX).max().to_numpy()
    lo = pd.Series(l).rolling(BOX).min().to_numpy()
    n = len(c)
    fh = pd.Series(h[::-1]).rolling(H, min_periods=1).max().to_numpy()[::-1]  # max h[t..t+H-1]
    fl = pd.Series(l[::-1]).rolling(H, min_periods=1).min().to_numpy()[::-1]
    up = np.r_[fh[1:], np.nan] - c  # max over t+1..t+H
    dn = c - np.r_[fl[1:], np.nan]
    up[n - H:] = np.nan
    dn[n - H:] = np.nan
    r = np.r_[c[H:] - c[:-H], [np.nan] * H]
    s = sig.to_numpy()
    out = pd.DataFrame({"sig": s, "pct": pct, "R": r / s, "up": up / s, "dn": dn / s,
                        "box_hi": hi - c, "box_lo": c - lo})
    # touches of the box edges within H, and the bar of the first 3-sigma excursion
    touch_hi = np.r_[fh[1:], np.nan] >= hi
    touch_lo = np.r_[fl[1:], np.nan] <= lo
    out["whipsaw"] = touch_hi & touch_lo
    out["one_edge"] = touch_hi ^ touch_lo
    first = np.full(n, np.nan)
    for t in range(n - H):
        lim = 3 * s[t]
        path = np.maximum(h[t + 1:t + 1 + H] - c[t], c[t] - l[t + 1:t + 1 + H])
        hit = np.nonzero(path >= lim)[0]
        if len(hit):
            first[t] = hit[0] + 1
    out["first3"] = first
    return out


def bits(x: np.ndarray, y: np.ndarray) -> float:
    joint = pd.crosstab(x, y).to_numpy().astype(float)
    p = joint / joint.sum()
    px, py = p.sum(axis=1, keepdims=True), p.sum(axis=0, keepdims=True)
    nz = p > 0
    return float((p[nz] * np.log2(p[nz] / (px @ py)[nz])).sum())


def mi_test(x, y, draws=200):
    real = bits(x, y)
    null = [bits(x, RNG.permutation(y)) for _ in range(draws)]
    return dict(bits=round(real, 5), null_p95=round(float(np.percentile(null, 95)), 5),
                p=round(float(np.mean(np.array(null) >= real)), 3))


def orders(bars: pd.DataFrame, st: pd.DataFrame, arms: np.ndarray, *, two_sided: bool,
           buffer: float, trail_k: float, confirm: bool) -> pd.DataFrame:
    """The pre-registered orders for every arming bar (one per BOX bars)."""
    hi = bars["high"].rolling(BOX).max().to_numpy()
    lo = bars["low"].rolling(BOX).min().to_numpy()
    cl = bars["close"].to_numpy()
    sp = bars["spread_price"].to_numpy()
    sig = st["sig"].to_numpy()
    rows, last = [], -BOX
    for n, i in enumerate(np.sort(arms)):
        if i - last < BOX or np.isnan(hi[i]) or np.isnan(sp[i]) or np.isnan(sig[i]):
            continue
        height = hi[i] - lo[i]
        if height < 3 * sp[i]:
            continue
        last = i
        px_sig = sig[i] * cl[i]
        d = buffer * px_sig
        stop = height + sp[i] + 2 * d
        trail = trail_k * px_sig
        sides = [1, -1] if two_sided else [1 if cl[i] >= (hi[i] + lo[i]) / 2 else -1]
        if confirm:  # market entry at the next open after a close beyond the edge, within BOX bars
            j_end = min(len(cl) - 1, i + BOX)
            for k in range(i + 1, j_end + 1):
                side = 1 if cl[k] > hi[i] + d else (-1 if cl[k] < lo[i] - d else 0)
                if side and side in sides:
                    rows.append(dict(i=k, side=side, stop=stop, trail=trail, hold=MAXHOLD))
                    break
            continue
        for side in sides:
            level = hi[i] + sp[i] + d if side > 0 else lo[i] - d
            rows.append(dict(i=i, side=side, entry=level, expires=BOX, stop=stop, trail=trail,
                             hold=MAXHOLD, oco=n if two_sided else -1))
    return pd.DataFrame(rows)


def judge(t: pd.DataFrame) -> dict:
    if t.empty:
        return dict(n=0)
    t = t.sort_values("entry_ts")
    half = len(t) // 2
    lo, hi = day_bootstrap(t)
    risk = t["risk_money"]
    return dict(n=len(t), mean_R=round(t["R"].mean(), 4), ci=[round(lo, 4), round(hi, 4)],
                halves=[round(t["R"].iloc[:half].mean(), 4), round(t["R"].iloc[half:].mean(), 4)],
                gross_R=round((t["gross"] / risk).mean(), 4),
                spread_R=round((t["spread_cost"] / risk).mean(), 4),
                hit=round(float((t["net"] > 0).mean()), 3),
                p90_R=round(float(t["R"].quantile(0.9)), 3),
                exits=t["reason"].value_counts().to_dict())


def main() -> None:
    pred = pd.read_csv(OUT / "test_predictions.csv")
    pred = pred[pred["test"] & (pred["kind"] == "real")]
    wf = json.loads((OUT / "expansion_wf.json").read_text())
    base = wf["base_rate"]
    pred["lift"] = pred["p"] / base
    specs = load_specs(os.environ.get("MT5BT_DB"))
    deciles = np.quantile(pred["lift"], np.linspace(0, 1, 11))

    stats, books = [], {}
    for key, g in pred.groupby("key"):
        sym, iv = key.split("|")
        spec = specs.get(sym) or next((v for k, v in specs.items() if k.split(".")[0] == sym), None)
        if spec is None:
            continue
        bars = load_bars(sym, iv, "seqlab", SEQLAB)
        book = Book(key, bars, spec, iv, feed=sym.lower(), meta={"family": g["family"].iloc[0]})
        st = state(book.bars)
        ts = book.bars["ts"].to_numpy()
        idx = np.searchsorted(ts, (g["when"].to_numpy() - SECONDS[iv]).astype(np.int64))
        ok = (idx < len(ts)) & (ts[np.minimum(idx, len(ts) - 1)] == g["when"].to_numpy() - SECONDS[iv])
        g, idx = g[ok], idx[ok]
        lift = g["lift"].to_numpy()
        test_from = idx.min()
        # C = 0: held-out bars that are not compressed, sampled to the compressed count
        loose = np.flatnonzero((np.arange(len(ts)) >= test_from) & (st["pct"].to_numpy() > 0.2))
        loose = RNG.choice(loose, min(len(loose), len(idx)), replace=False)
        rows = st.iloc[np.r_[idx, loose]].copy()
        rows["bar"] = np.r_[idx, loose]
        rows["lift"] = np.r_[lift, np.full(len(loose), np.nan)]
        rows["group"] = np.r_[np.where(lift >= 2.5, "A", np.where(lift >= 1, "M", "Q")),
                              np.full(len(loose), "N")]
        rows["key"] = key
        rows["family"] = g["family"].iloc[0]
        stats.append(rows)
        books[key] = (book, st, idx, lift)
    df = pd.concat(stats, ignore_index=True).dropna(subset=["R", "up", "dn"])
    df["Y"] = np.maximum(df["up"], df["dn"])
    df["second"] = df.groupby("key")["bar"].transform(lambda b: b >= b.median())
    res: dict = {"rows": int(len(df))}

    g1 = {}
    for name, g in df.groupby("group"):
        g1[name] = dict(n=len(g), **{f"P(Y>{k})": round(float((g["Y"] > k).mean()), 4) for k in (2, 4, 6)},
                        mean_Y=round(float(g["Y"].mean()), 3), P_up=round(float((g["R"] > 0).mean()), 4),
                        whipsaw=round(float(g["whipsaw"].mean()), 4),
                        one_edge=round(float(g["one_edge"].mean()), 4),
                        first3_median=float(g["first3"].median()),
                        halves_P4=[round(float((g[~g["second"]]["Y"] > 4).mean()), 4),
                                   round(float((g[g["second"]]["Y"] > 4).mean()), 4)])
    res["G1_G5_by_group"] = g1
    comp = df[df["group"] != "N"].copy()
    comp["decile"] = np.clip(np.searchsorted(deciles, comp["lift"], side="right") - 1, 0, 9)
    big = (comp["R"].abs() > comp["R"].abs().median()).to_numpy()
    res["G2_bits"] = {"magnitude": mi_test(comp["decile"].to_numpy(), big),
                      "sign": mi_test(comp["decile"].to_numpy(), (comp["R"] > 0).to_numpy())}
    haz = {}
    for name, g in df.groupby("group"):
        f = g["first3"].to_numpy()
        at_risk = len(f)
        h = []
        for k in range(1, H + 1):
            events = int(np.sum(f == k))
            h.append(round(events / at_risk, 4) if at_risk else None)
            at_risk -= events
        haz[name] = h
    res["G3_hazard_3sigma"] = haz
    dec = comp.groupby("decile").agg(n=("Y", "size"), P4=("Y", lambda y: float((y > 4).mean())),
                                     whipsaw=("whipsaw", "mean"), P_up=("R", lambda r: float((r > 0).mean())))
    res["G4_by_decile"] = dec.round(4).reset_index().to_dict(orient="records")
    print(json.dumps(res, indent=1), flush=True)

    # ---------------------------------------------------------------- the trades
    configs = {
        "A_primary": dict(gate="any", two_sided=True, buffer=0.0, trail_k=2.0, confirm=False),
        "B_primary": dict(gate="alert", two_sided=True, buffer=0.0, trail_k=2.0, confirm=False),
        "C_primary": dict(gate="any", two_sided=False, buffer=0.0, trail_k=2.0, confirm=False),
        "D_primary": dict(gate="alert", two_sided=False, buffer=0.0, trail_k=2.0, confirm=False),
    }
    for gate in ("any", "alert"):
        tag = "A" if gate == "any" else "B"
        configs[f"{tag}_buffer0.5"] = dict(gate=gate, two_sided=True, buffer=0.5, trail_k=2.0, confirm=False)
        configs[f"{tag}_buffer1"] = dict(gate=gate, two_sided=True, buffer=1.0, trail_k=2.0, confirm=False)
        configs[f"{tag}_confirm"] = dict(gate=gate, two_sided=True, buffer=0.0, trail_k=2.0, confirm=True)
        configs[f"{tag}_trail3"] = dict(gate=gate, two_sided=True, buffer=0.0, trail_k=3.0, confirm=False)
        for kk in ("buffer0.5", "buffer1", "trail3"):
            configs[f"{'C' if gate == 'any' else 'D'}_{kk}"] = dict(
                gate=gate, two_sided=False, buffer=configs[f"{tag}_{kk}"]["buffer"],
                trail_k=configs[f"{tag}_{kk}"]["trail_k"], confirm=False)
    trades = {}
    for name, cfg in configs.items():
        parts = []
        for key, (book, st, idx, lift) in books.items():
            arms = idx[lift >= 2.5] if cfg["gate"] == "alert" else idx
            sig = orders(book.bars, st, arms, two_sided=cfg["two_sided"], buffer=cfg["buffer"],
                         trail_k=cfg["trail_k"], confirm=cfg["confirm"])
            if len(sig):
                t, _ = run(book, None, Costs(), equity=1e7, risk=0.001, one_per_symbol=False,
                           signals={key: sig})
                if len(t):
                    parts.append(t.assign(family=book.meta["family"]))
        t = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        trades[name] = t
        out = judge(t)
        if len(t):
            out["by_family"] = {f: round(x["R"].mean(), 4) for f, x in t.groupby("family")}
        res[f"trade/{name}"] = out
        print(f"  {name:14s} {json.dumps(out)}", flush=True)

    # G4 economics: the primary bracket by lift decile (descriptive)
    dec_ev = []
    for d in range(10):
        lo_, hi_ = deciles[d], deciles[d + 1]
        parts = []
        for key, (book, st, idx, lift) in books.items():
            sig = orders(book.bars, st, idx[(lift >= lo_) & (lift <= hi_)], two_sided=True,
                         buffer=0.0, trail_k=2.0, confirm=False)
            if len(sig):
                t, _ = run(book, None, Costs(), equity=1e7, risk=0.001, one_per_symbol=False,
                           signals={key: sig})
                parts.append(t)
        t = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        dec_ev.append(dict(decile=d, lift=[round(lo_, 2), round(hi_, 2)], n=len(t),
                           mean_R=round(t["R"].mean(), 4) if len(t) else None,
                           gross_R=round((t["gross"] / t["risk_money"]).mean(), 4) if len(t) else None))
    res["G4_bracket_by_decile"] = dec_ev
    print(json.dumps(dec_ev), flush=True)

    # walks: B's primary on 12 GARCH walks
    spec = frozen.Trees(wf)
    walk = []
    for w in range(12):
        bars = garch_walk(30_000, interval="15m", spread_points=8.0, seed=900 + w)
        book = Book("EURUSD", bars, EXAMPLE_SPECS["EURUSD"], "15m")
        st = state(book.bars)
        model, armed = ex.Expansion(), []
        for k, r in enumerate(book.bars.itertuples(index=False)):
            model.observe("w", "15m", 900, r.ts + 900, r.high, r.low, r.close)
            s = model.series.get("w|15m")
            if k > 18_000 and s is not None and s.compressed and s.latest:
                if spec.predict(s.latest) / base >= 2.5:
                    armed.append(k)
        sig = orders(book.bars, st, np.array(armed, int), two_sided=True, buffer=0.0, trail_k=2.0,
                     confirm=False)
        if len(sig):
            t, _ = run(book, None, Costs(), equity=1e7, risk=0.001, one_per_symbol=False,
                       signals={"EURUSD": sig})
            walk.append(t["R"].mean())
    res["walks_B_primary"] = dict(per_walk=[round(x, 4) for x in walk],
                                  mean=round(float(np.mean(walk)), 4),
                                  se=round(float(np.std(walk, ddof=1) / np.sqrt(len(walk))), 4))
    print(json.dumps(res["walks_B_primary"]), flush=True)
    (OUT / "energy.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
