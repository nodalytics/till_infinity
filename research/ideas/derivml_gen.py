"""Deriv synthetics: measure each generator from its ticks and bars, and fit the nulls (derivml_rule.json,
generator_measurement). Runs before any model; its output is committed before any model run.

  OUT=... WORKERS=4 python research/ideas/derivml_gen.py

Writes OUT/gen_params.json (per series: tick interval, spread, generator kind and parameters, and the
measurement report) and OUT/gen/bc_<slug>.npz, OUT/gen/jump_<slug>.npz (resampling pools).
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import derivml_data as D  # noqa: E402

OUT = D.OUT
TICK0 = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp())
BC_SPLIT_DAY = 20410                        # boomcrash-trend's split: 2025-11-18 (its discovery ends 11-17)
JUMP_FIT_END = BC_SPLIT_DAY * 86400          # Jump: the first half of the fetched ticks, the same date
DT_GRID = (0.25, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0)
JUMP_K = 6.0
SEED = 20261006


def wilson(k, n, z=1.645):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (float(c - h), float(c + h))


def boot_days(vals_by_day, stat, B=1000, seed=SEED):
    """Day bootstrap (90%) of stat over a list of per-day arrays."""
    rng = np.random.default_rng(seed)
    n = len(vals_by_day)
    if n < 3:
        return (np.nan, np.nan)
    out = []
    for _ in range(B):
        ix = rng.integers(0, n, n)
        out.append(stat([vals_by_day[i] for i in ix]))
    return (float(np.nanquantile(out, 0.05)), float(np.nanquantile(out, 0.95)))


def tick_basics(days, split):
    """Tick interval (median within-day gap), share at the mode, spread median (discovery days if any)."""
    gaps = np.concatenate([np.diff(ms) for _, ms, _, _ in days if len(ms) > 2])
    med = float(np.median(gaps)) / 1000
    dt = min(DT_GRID, key=lambda g: abs(g - med))
    mode_share = float(np.mean(np.abs(gaps / 1000 - dt) < 0.25 * dt))
    disc = [d for d in days if d[0] * 86400 < split]
    use = disc if disc else days
    spread = float(np.median(np.concatenate([a - b for _, _, b, a in use])))
    per_day = float(np.mean([len(ms) for _, ms, _, _ in days]))
    return dict(dt_s=dt, dt_median_s=med, dt_mode_share=mode_share, spread=spread,
                spread_days="discovery" if disc else "all", ticks_per_day=per_day, tick_days=len(days),
                first_tick_day=str(np.datetime64(days[0][0], "D")), last_tick_day=str(np.datetime64(days[-1][0], "D")))


def bars_1h(sym):
    df = D.load_bars(sym, "1h")
    return df


def vol_measure(sym, b, split):
    """Realised sigma (annualised, calendar time) from 1h log close changes, against the name."""
    r = D.REG[sym]
    ts = b["ts"].to_numpy(np.int64)
    lc = np.log(b["close"].to_numpy(float))
    d = np.diff(lc)
    gap_ok = np.diff(ts) == 3600
    d, t = d[gap_ok], ts[1:][gap_ok]
    disc = t < split
    by_day = pd.Series(d[disc] ** 2).groupby(t[disc] // 86400).apply(np.array).tolist()

    def sig(days):
        x = np.concatenate(days)
        return float(np.sqrt(np.mean(x) * 24 * 365))

    s_disc = sig(by_day) if by_day else np.nan
    allday = pd.Series(d ** 2).groupby(t // 86400).apply(np.array).tolist()
    s_all = sig(allday)
    yr = pd.Series(d ** 2).groupby(pd.to_datetime(t, unit="s").year).mean()
    rep = dict(sigma_name=r.get("sigma"), sigma_disc=s_disc, sigma_all=s_all,
               ratio_disc=s_disc / r["sigma"] if r.get("sigma") else np.nan,
               ratio_disc_ci=[x / r["sigma"] for x in boot_days(by_day, sig, 300)] if r.get("sigma") and by_day else None,
               ratio_by_year={int(k): float(np.sqrt(v * 24 * 365) / r["sigma"]) for k, v in yr.items()} if r.get("sigma") else None,
               kurt_1h=float(pd.Series(d[disc] if disc.sum() > 100 else d).kurt() + 3),
               n_1h=int(len(d)))
    h, l, o, c = (b[k].to_numpy(float) for k in ("high", "low", "open", "close"))
    park = np.sqrt(np.mean(np.log(h / l) ** 2) / (4 * np.log(2)))
    rep["parkinson_over_cc"] = float(park / np.std(np.diff(np.log(c))))
    return rep


def step_measure(sym, days, split, b):
    """Step family: the increment distribution, up share, drift, run lengths, variance ratio."""
    info = D.REG[sym]
    point = 0.01 if "Multi" in sym else 0.1
    fit_days = [x for x in days if x[0] * 86400 < split]
    basis = "discovery"
    if len(fit_days) < 10:
        fit_days = days[:len(days) // 2]
        basis = "first half of the fetched tick days"
    fit_set = {x[0] for x in fit_days}
    inc_by_day, fit_inc = [], []
    for day, ms, bid, _ in days:
        g = np.diff(ms) / 1000
        dd = np.round(np.diff(bid) / point) * point
        dd = dd[g <= 3 * np.median(g)]
        inc_by_day.append(dd)
        if day in fit_set:
            fit_inc.append(dd)
    fit_inc = np.concatenate(fit_inc)
    vals, cnt = np.unique(np.round(fit_inc, 6), return_counts=True)
    probs = cnt / cnt.sum()
    allinc = np.concatenate(inc_by_day)
    nz = allinc[allinc != 0]
    up = int((nz > 0).sum())
    rep = dict(fit_basis=basis, fit_days=len(fit_days), n_inc=int(len(allinc)),
               support=[float(v) for v in vals], probs=[float(p) for p in probs],
               zero_share=float(np.mean(allinc == 0)), up_share=float(up / max(len(nz), 1)),
               up_share_ci90=wilson(up, len(nz)), up_share_z=float((up - 0.5 * len(nz)) / np.sqrt(0.25 * max(len(nz), 1))),
               mean_inc=float(np.mean(allinc)), mean_inc_ci90=boot_days(inc_by_day, lambda L: float(np.mean(np.concatenate(L))), 300),
               step=float(np.median(np.abs(nz))) if len(nz) else np.nan)
    # run lengths of same-sign steps against the geometric law of the measured up share
    s = np.sign(nz)
    ch = np.flatnonzero(np.r_[True, s[1:] != s[:-1], True])
    runs = np.diff(ch)
    rs = s[ch[:-1]]
    pu = rep["up_share"]
    for nm, sel, p in (("up", rs > 0, pu), ("down", rs < 0, 1 - pu)):
        rl = runs[sel]
        rep[f"run_{nm}_mean"] = float(rl.mean()) if len(rl) else np.nan
        rep[f"run_{nm}_geom"] = float(1 / (1 - p)) if p < 1 else np.nan
        rep[f"run_{nm}_pmf"] = [float(np.mean(rl == k)) for k in range(1, 11)]
        rep[f"run_{nm}_pmf_geom"] = [float((1 - p) * p ** (k - 1)) for k in range(1, 11)]
    vr = {}
    for m in (1, 10, 60, 600, 3600):
        tot = [x[: len(x) // m * m].reshape(-1, m).sum(1) for x in inc_by_day if len(x) >= 2 * m]
        if tot:
            v = np.var(np.concatenate(tot)) / (m * np.var(allinc))
            vr[m] = float(v)
    rep["variance_ratio"] = vr
    # stability from bars: median 1h range in step units by year
    rng_steps = (b["high"] - b["low"]).to_numpy(float) / rep["step"]
    rep["range1h_steps_by_year"] = {int(k): float(v) for k, v in
                                   pd.Series(rng_steps).groupby(pd.to_datetime(b["ts"], unit="s").dt.year).median().items()}
    # the generator: a +/-step Bernoulli at the measured up share where the support is +/-step; otherwise the
    # measured increment distribution
    prm = dict(kind="step", values=[float(v) for v in vals], probs=[float(p) for p in probs], step=rep["step"])
    return prm, rep


def jump_measure(sym, days):
    """Jump family: Gaussian diffusion + Bernoulli jumps per tick, fitted on the first half of the ticks."""
    fit = [x for x in days if x[0] * 86400 < JUMP_FIT_END]
    d_all = [np.diff(np.log(bid)) for _, ms, bid, _ in fit]
    d = np.concatenate(d_all)
    sd_rob = 1.4826 * np.median(np.abs(d - np.median(d)))
    jmask = np.abs(d) > JUMP_K * sd_rob
    sd = float(np.std(d[~jmask]))
    J = d[jmask]
    p = float(jmask.mean())
    rep = dict(fit_days=len(fit), sd_rob=float(sd_rob), sd_diff=sd, p_jump=p, n_jumps=int(jmask.sum()),
               jump_up_share=float((J > 0).mean()) if len(J) else np.nan,
               jump_abs_mean_over_sd=float(np.mean(np.abs(J)) / sd) if len(J) else np.nan,
               var_share_jumps=float(p * np.mean(J ** 2) / (sd ** 2 + p * np.mean(J ** 2))) if len(J) else np.nan)
    OUTG = OUT / "gen"
    OUTG.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUTG / f"jump_{D.slug(sym)}.npz", J=J.astype(np.float64))
    return dict(kind="jump", p=p, sd=sd), rep


def bc_measure(sym):
    """boomcrash-trend's fitted null, re-fitted with its own code on its own tick store."""
    import boomcrash_trend as bc
    bc.DATA = D.BCDATA
    sl = bc.slug(sym)
    ms, bid, ask = bc.load_ticks(sl)
    k = (ms >= 20089 * 86400000) & (ms < (20730 + 1) * 86400000)
    ms, bid, ask = ms[k], bid[k], ask[k]
    s = bc.side(sl)
    disc_end = BC_SPLIT_DAY * 86400000
    theta = bc.theta_of(bid, ms, s, disc_end)
    first, last, J, ex, sub, outage = bc.detect(ms, bid, s, theta)
    par = bc.fit_null(ms, bid, s, first, last, J, outage, disc_end, np.random.default_rng(1))
    OUTG = OUT / "gen"
    OUTG.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUTG / f"bc_{D.slug(sym)}.npz", grind=par["grind"].astype(np.float64), J=par["J"].astype(np.float64))
    nd = int(np.searchsorted(ms, disc_end))
    gaps = np.diff(ms[:nd])
    med = float(np.median(gaps)) / 1000
    dt = min(DT_GRID, key=lambda g: abs(g - med))
    spread = float(np.median((ask - bid)[:nd]))
    rep = dict(theta=float(theta), p=float(par["p"]), ticks_per_spike=float(1 / par["p"]), n_spikes_disc=int((first < nd).sum()),
               grind_mean=float(np.mean(par["grind"])), J_mean=float(np.mean(par["J"])),
               closure=float(par["p"] * np.mean(par["J"]) + (1 - par["p"]) * np.mean(par["grind"]) * s))
    return dict(kind="bc", p=float(par["p"]), dt_s=dt, dt_median_s=med, spread=spread, spread_days="discovery (boomcrash split)",
                tick_days=int(len(np.unique(ms // 86400000)))), rep


def rb_measure(sym):
    prm = json.loads((HERE / "rb_sim_params.json").read_text())
    key = "RB100" if "100" in sym else "RB200"
    days = D.load_ticks(sym, days=None)
    sp = float(np.median(np.concatenate([a - b for _, _, b, a in days[:60]])))
    return dict(kind="rb", rbsim=prm[key], dt_s=1.0, spread=sp, spread_days="first 60 tick days",
                tick_days=len(days)), dict(p=prm[key]["p"], mean_absJ=prm[key]["mean_absJ"],
                                           martingale_drift=prm[key]["martingale_drift"])


def one(sym):
    r = D.REG[sym]
    try:
        b = bars_1h(sym)
    except Exception as e:  # noqa: BLE001
        return sym, None, f"no bars: {e!r}"
    if len(b) < D.MIN_BARS:
        return sym, None, f"{len(b)} 1h bars"
    split = D.split_ts(b["ts"].to_numpy(np.int64))
    rep = dict(group=r["group"], cls=r["cls"], split=str(pd.Timestamp(split, unit="s").date()), bars_1h=len(b),
               first_1h=str(pd.Timestamp(int(b["ts"].iloc[0]), unit="s")))
    if r["cls"] == "BC":
        prm, rr = bc_measure(sym)
        rep.update(rr)
        rep.update(vol_measure(sym, b, split))
        return sym, dict(prm, report=rep), "ok"
    if r["group"] == "RB":
        prm, rr = rb_measure(sym)
        rep.update(rr)
        return sym, dict(prm, report=rep), "ok"
    days = D.load_ticks(sym)
    if not days:
        return sym, None, "no ticks"
    tb = tick_basics(days, split)
    rep.update({k: v for k, v in tb.items()})
    if r["group"] == "DIFF":
        vm = vol_measure(sym, b, split)
        rep.update(vm)
        prm = dict(kind="gbm", sigma=float(vm["sigma_disc"]) if np.isfinite(vm["sigma_disc"]) else float(vm["sigma_all"]))
    elif r["group"] == "STEP":
        prm, sr = step_measure(sym, days, split, b)
        rep.update(sr)
    else:
        prm, jr = jump_measure(sym, days)
        rep.update(jr)
        rep.update(vol_measure(sym, b, split))
    prm.update(dt_s=tb["dt_s"], spread=tb["spread"])
    return sym, dict(prm, report=rep), "ok"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    syms = list(D.REG)
    if os.environ.get("ONLY"):
        syms = [s for s in syms if s in os.environ["ONLY"].split(",")]
    res = {}
    p = OUT / "gen_params.json"
    if p.exists():
        res = json.loads(p.read_text())["series"]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 4))) as pool:
        for sym, prm, msg in pool.map(one, syms, chunksize=1):
            print(f"  {sym}: {msg}", flush=True)
            if prm is not None:
                res[sym] = prm
    p.write_text(json.dumps(dict(series=res), indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print("gen done", flush=True)


if __name__ == "__main__":
    main()
