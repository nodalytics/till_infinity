"""How long and how far an expansion runs - against walks matched to each market - and whether
that forecast makes better hold times and stop widths.

precursors.py / signature.py found an expansion's duration, magnitude and velocity predictable at
its onset (rank correlation 0.70 / 0.48 / 0.53), with a caveat: a bigger onset bar takes longer
to decay out of the percentile on any process. This settles the caveat, then uses the forecast.

Pre-registered (2026-10-01), before any run. Universe as expansion_build.py, 15m and 1h; each
series' first 60% by time trains, the rest scores, both halves.

Part A - market information, or GARCH persistence?
  episode   onset: the range percentile crosses into the top fifth; duration D: bars until it
            falls below 0.5 (capped at 200); magnitude M: largest |log move| from the pre-onset
            close during the episode, in pre-onset sigma
  features  read on the bar *before* the onset (what a trade knows when its breakout fills): that
            bar's range in sigma, the compression depth over the 16 bars before, the previous
            episode's duration; the market also has its calendar and tick-volume z
  walks     per series, GARCH(1,1) fitted on its own training 60% (normal QMLE), simulated at the
            same length with t(5) innovations: the same persistence, no market information
  judged    held-out Spearman of predicted against realised log D and log M: the market with the
            shared features, the market with all of them, and the matched walk with the shared
            ones. The forecast carries market information if the market (all features) beats the
            walk by >= 0.05 in both halves; it is usable for risk if its held-out Spearman is
            >= 0.3 in both halves, whatever the walks say.

Part B - hold times and stop widths
  entries   the trailing bracket (energy.py), armed on any compressed bar (A) and on the alert (B),
            15m and 1h, real markets, held-out predictions
  exits     fixed: trail 2 sigma, 96 bars at most (as tested)
            hold:  hold = predicted D, clipped to 4..96 bars
            trail: trail = 2 sigma x predicted M / its median, clipped to 1..4 sigma
            both
            placebo: both, with the predictions shuffled within each series
            The forecast is read at the bar before the order's fill bar.
  counts if a variant beats fixed by >= 0.01R in both halves and beats the placebo
"""
from __future__ import annotations

import json
import os
import sys
import zlib
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.signal import lfilter
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "harness"))
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT))

import energy as en  # noqa: E402
import expansion_build as eb  # noqa: E402
import precursors as pc  # noqa: E402
from mt5bt import Book, Costs, load_bars, load_specs, run  # noqa: E402
from mt5bt.engine import _frame, _sides, resolve, spreads  # noqa: E402
from mt5bt.nulls import garch_walk  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/duration"))
PRED = Path(os.environ.get("PRED", ".data/expansion_all"))
RNG = np.random.default_rng(53)
COMMON = ["pre_range", "depth", "prev"]
FULL = COMMON + ["clock", "vol_z"]


def garch_fit(r: np.ndarray) -> tuple[float, float, float]:
    r = r[np.isfinite(r)]
    r = r - r.mean()
    v0 = r.var()

    def nll(p):
        w, a, b = p
        if w <= 0 or a < 0 or b < 0 or a + b >= 0.999:
            return 1e12
        # var_k = w + a r_{k-1}^2 + b var_{k-1}, as a linear filter
        drive = w + a * np.r_[v0, r[:-1] ** 2]
        var = lfilter([1.0], [1.0, -b], drive, zi=[b * v0])[0]
        return 0.5 * np.sum(np.log(var) + r * r / var)

    best = minimize(nll, [v0 * 0.05, 0.05, 0.9], method="Nelder-Mead",
                    options={"maxiter": 400, "xatol": 1e-8, "fatol": 1e-3})
    w, a, b = best.x
    return float(w), float(a), float(b)


def frame_of(df: pd.DataFrame, iv: str) -> pd.DataFrame:
    f = pc.per_series(df, iv)
    f["lc"] = np.log(df["close"].to_numpy())
    return f


def episodes(f: pd.DataFrame) -> pd.DataFrame:
    pct, slow, tr, lc = (f[k].to_numpy() for k in ("pct", "slow", "tr", "lc"))
    n = len(pct)
    rows, prev = [], np.nan
    for o in np.flatnonzero((pct[1:] >= 0.8) & (pct[:-1] < 0.8)) + 1:
        if o < 20:
            continue
        end = o
        while end < n and end - o < 200 and not (pct[end] < 0.5):
            end += 1
        if end >= n:
            break
        pre = slow[o - 1]
        if not pre > 0:
            continue
        rows.append(dict(onset=o, D=end - o, M=float(np.max(np.abs(lc[o:end + 1] - lc[o - 1])) / pre),
                         pre_range=tr[o - 1] / slow[o - 2] if slow[o - 2] > 0 else np.nan,
                         depth=float(np.nanmin(pct[o - 17:o - 1])), prev=prev,
                         clock=f["clock"].iat[o - 1] if "clock" in f else np.nan,
                         vol_z=f["vol_z"].iat[o - 1] if "vol_z" in f else np.nan,
                         train=bool(f["train"].iat[o]) if "train" in f else o < 0.6 * n))
        prev = end - o
    return pd.DataFrame(rows)


def per_bar(f: pd.DataFrame, ep: pd.DataFrame) -> pd.DataFrame:
    """The features read at every bar, as if an onset followed it (for Part B)."""
    pct, slow, tr = (f[k].to_numpy() for k in ("pct", "slow", "tr"))
    n = len(pct)
    prev = np.full(n, np.nan)
    if len(ep):
        ends = (ep["onset"] + ep["D"]).to_numpy()
        for e, d in zip(ends, ep["D"].to_numpy(), strict=True):
            prev[int(e):] = d
    return pd.DataFrame({
        "pre_range": tr / np.r_[np.nan, slow[:-1]],
        "depth": pd.Series(pct).rolling(16, min_periods=1).min().to_numpy(),
        "prev": prev, "clock": f["clock"].to_numpy(), "vol_z": f["vol_z"].to_numpy()})


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, cols: list[str], target: str):
    from sklearn.ensemble import HistGradientBoostingRegressor
    y = np.log(train[target].to_numpy(float) + 1e-6)
    m = HistGradientBoostingRegressor(max_depth=3, max_iter=200, learning_rate=0.05,
                                      min_samples_leaf=100).fit(train[cols].to_numpy(float), y)
    return m, m.predict(test[cols].to_numpy(float))


def rho(pred, actual) -> float:
    return round(float(spearmanr(pred, np.log(actual + 1e-6)).statistic), 4)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    real, walk, frames = [], [], {}
    for sym, fam in eb.FAMILY.items():
        if fam == "deriv":
            continue
        for iv in ("15m", "1h"):
            df = pc.frame(sym, iv)
            if df is None or len(df) < 3_000:
                continue
            f = frame_of(df, iv)
            frames[f"{sym}|{iv}"] = (df, f)
            ep = episodes(f).assign(key=f"{sym}|{iv}", family=fam)
            real.append(ep)
            n = len(df)
            r = np.diff(f["lc"].to_numpy()[: int(0.6 * n)])
            w, a, b = garch_fit(r[-20_000:])
            wb = garch_walk(n, interval=iv, bar_vol=float(np.sqrt(w / max(1 - a - b, 1e-6))),
                            alpha=a, beta=b, df=5.0, spread_points=0.0, seed=zlib.crc32(sym.encode()) % 10_000, sub=64)
            wf = frame_of(wb.rename(columns={"ts": "time"}).assign(volume=0.0, spread=np.nan), iv)
            walk.append(episodes(wf).assign(key=f"{sym}|{iv}", family=fam, alpha=a, beta=b))
            print(f"  {sym} {iv}: garch a={a:.3f} b={b:.3f}, {len(ep)} episodes", flush=True)
    R, W = pd.concat(real, ignore_index=True), pd.concat(walk, ignore_index=True)
    # a few lab bars carry non-positive prices, which leave an episode without a magnitude
    R = R[np.isfinite(R["M"]) & np.isfinite(R["D"])].reset_index(drop=True)
    W = W[np.isfinite(W["M"]) & np.isfinite(W["D"])].reset_index(drop=True)
    res = {"episodes_real": len(R), "episodes_walk": len(W)}
    for target in ("D", "M"):
        cell = {}
        for name, data, cols in (("market_all", R, FULL), ("market_shared", R, COMMON), ("walk_shared", W, COMMON)):
            tr, te = data[data["train"]], data[~data["train"]]
            _, p = fit_predict(tr, te, cols, target)
            mid = te.groupby("key")["onset"].transform("median").to_numpy()
            s2 = te["onset"].to_numpy() >= mid
            cell[name] = dict(all=rho(p, te[target].to_numpy()),
                              halves=[rho(p[~s2], te[target].to_numpy()[~s2]), rho(p[s2], te[target].to_numpy()[s2])])
        cell["information"] = bool(min(cell["market_all"]["halves"][i] - cell["walk_shared"]["halves"][i]
                                       for i in (0, 1)) >= 0.05)
        cell["usable"] = bool(min(cell["market_all"]["halves"]) >= 0.3)
        res[target] = cell
    res["median_D"] = {f: [float(R.loc[R.family == f, "D"].median()), float(W.loc[W.family == f, "D"].median())]
                       for f in R["family"].unique()}
    print(json.dumps(res, indent=1), flush=True)

    # ------------------------------------------------------------------ part B
    pred = pd.read_csv(PRED / "test_predictions.csv")
    pred = pred[pred["test"] & (pred["kind"] == "real") & pred["key"].str.endswith(("|15m", "|1h"))]
    specs = load_specs(os.environ.get("MT5BT_DB"))
    trD, _ = fit_predict(R[R["train"]], R[R["train"]].head(1), FULL, "D")
    trM, _ = fit_predict(R[R["train"]], R[R["train"]].head(1), FULL, "M")
    med_M = float(np.exp(np.median(trM.predict(R.loc[R["train"], FULL].to_numpy(float)))))
    results = {k: [] for k in ("fixed", "hold", "trail", "both", "placebo")}
    for key, g in pred.groupby("key"):
        if key not in frames:
            continue
        sym, iv = key.split("|")
        spec = en.spec_for(specs, sym)
        if spec is None:
            continue
        df, f = frames[key]
        bars = load_bars(sym, iv, "seqlab", en.SEQLAB)
        book = Book(key, bars, spec, iv, feed=sym.lower())
        st = en.state(book.bars)
        ts = book.bars["ts"].to_numpy()
        idx = np.searchsorted(ts, (g["when"].to_numpy() - en.SECONDS[iv]).astype(np.int64))
        ok = (idx < len(ts)) & (ts[np.minimum(idx, len(ts) - 1)] == g["when"].to_numpy() - en.SECONDS[iv])
        idx, lift = idx[ok], g["lift"].to_numpy()[ok]
        ep = R[R["key"] == key]
        X = per_bar(f, ep)
        # align the feature frame (lab bar file) with the backtest's bars by open time
        X.index = df["time"].astype(np.int64).to_numpy()
        X = X.reindex(ts)
        Dh = np.exp(trD.predict(X[FULL].to_numpy(float)))
        Mh = np.exp(trM.predict(X[FULL].to_numpy(float))) / med_M
        perm = RNG.permutation(len(ts))
        mid = np.median(idx)
        for gate, arms in (("A", idx), ("B", idx[lift >= 2.5])):
            base = en.orders(book.bars, st, arms, two_sided=True, buffer=0.0, trail_k=2.0, confirm=False)
            if base.empty:
                continue
            # the bar each order fills in, from the engine's own resolver
            sp = spreads(book, Costs())
            fills = resolve(_frame(base), book, _sides(book, sp), Costs(fill="bars"))
            jmap = {(int(r.i), int(r.side)): int(r.j) for r in fills.itertuples()}
            jj = np.array([jmap.get((int(i), int(s)), int(i) + 1) for i, s in zip(base["i"], base["side"], strict=True)])
            at = np.clip(jj - 1, 0, len(ts) - 1)
            sig_px = base["trail"].to_numpy() / 2.0  # the trail was 2 sigma in price
            variants = {
                "fixed": base,
                "hold": base.assign(hold=np.clip(np.round(Dh[at]), 4, 96).astype(int)),
                "trail": base.assign(trail=2 * sig_px * np.clip(Mh[at], 0.5, 2.0)),
                "both": base.assign(hold=np.clip(np.round(Dh[at]), 4, 96).astype(int),
                                    trail=2 * sig_px * np.clip(Mh[at], 0.5, 2.0)),
                "placebo": base.assign(hold=np.clip(np.round(Dh[perm[at]]), 4, 96).astype(int),
                                       trail=2 * sig_px * np.clip(Mh[perm[at]], 0.5, 2.0)),
            }
            for name, sig in variants.items():
                sig = sig.assign(hold=sig["hold"].fillna(96).astype(int),
                                 trail=sig["trail"].fillna(pd.Series(2 * sig_px)))
                t, _ = run(book, None, Costs(), equity=1e7, risk=0.001, one_per_symbol=False,
                           signals={key: sig})
                if len(t):
                    results[name].append(t.assign(gate=gate, second=t["signal_bar"] >= mid))
        print(f"  {key} traded", flush=True)
    partB = {}
    for name, parts in results.items():
        t = pd.concat(parts, ignore_index=True)
        for gate, x in t.groupby("gate"):
            partB[f"{gate}/{name}"] = dict(n=len(x), R=round(x["R"].mean(), 4),
                                          halves=[round(x.loc[~x["second"], "R"].mean(), 4),
                                                  round(x.loc[x["second"], "R"].mean(), 4)])
    for gate in ("A", "B"):
        fx = partB.get(f"{gate}/fixed")
        pl = partB.get(f"{gate}/placebo")
        for name in ("hold", "trail", "both"):
            v = partB.get(f"{gate}/{name}")
            if v and fx and pl:
                v["counts"] = bool(min(v["halves"][i] - fx["halves"][i] for i in (0, 1)) >= 0.01
                                   and v["R"] > pl["R"])
    res["partB"] = partB
    print(json.dumps(partB, indent=1), flush=True)
    (OUT / "duration.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
