"""Kronos-mini on Deriv synthetics and on real markets: a null calibration with a strong prior.

**Written before any number was read, because the prior is unusually strong and
the arm is unusually easy to fool.**

`research/deriving.md` proves `E[net] = -(c/2) x turnover` for any predictable
position on a martingale. A Deriv Volatility index is geometric Brownian motion
at a published constant sigma, so its increments are independent *by
construction*, and `research/rebuilding.md` already found boosted models scoring
nothing on these feeds with `n*` infinite on every arm. A decoder-only
transformer pretrained on real equities and crypto has **no mechanism** by which
it could predict the sign of the next bar of a synthetic GBM. If it appears to,
the finding is a defect in this file.

So this page is not a hunt. It asks three questions that are worth asking
precisely because the answer to the first is known:

* **(a) The null calibration.** Given every advantage - a pretrained foundation
  model, the raw candles it was trained on rather than a feature matrix, its own
  sampler, its own tokenizer - does it still come back at AUC 0.50 on a process
  that is unpredictable by construction? Nobody in this folder has run that, and
  a measured null on a large pretrained model is worth more than another
  absence from a small one.
* **(b) The transfer question, which is the interesting one.** Kronos is
  pretrained on *real* markets. The zero-shot-to-fine-tuned gap **on synthetics
  against on real markets** measures how much of its pretraining is market
  structure that synthetics do not have. `seqlab.REAL` is therefore not a
  courtesy control here; the contrast is the result.
* **(c) Volatility rather than direction.** `seqlab.main()` found on Volatility
  75 1h that the unconditional mean (srel 0.6691) beats naive last-realised
  (0.8802), and that a simulated GBM behaves identically (0.6642 / 0.8809) -
  which is exactly what constant sigma predicts and is a generator-identification
  statistic in its own right. Can a foundation model beat the unconditional mean
  at forecasting realised volatility? On a constant-sigma member it must not.

## Kill conditions, before the numbers

1. **The run is void** if `kronoslib.verify` fails - if the cached decoder is not
   reproducing `tokenizer.decode`, or `_cond_s2` is not reproducing
   `Kronos.decode_s2`, then every score below is a score for a model nobody
   published.
2. **The run is void** if `kronoslib.check_causality` shows a single logit moving
   when a future bar is poked. That is the one bug that makes every arm succeed.
3. **The arm is void** if the `gbm` control does not land at AUC 0.50 within its
   own bootstrap band. The simulated null is the one place the true answer is
   known exactly; a harness that finds direction there is broken, not lucky.
4. **A direction result is a leak, not an edge**, if it survives on the feed and
   also survives on the phase surrogate. The surrogate keeps the return spectrum
   and destroys everything nonlinear, so a score that does not move is a score a
   straight line already had.
5. **A volatility result is a units artefact** if Kronos beats the unconditional
   mean on a constant-sigma Volatility member. The mean is optimal there by
   construction and anything that beats it has read the test block.
6. **A cell is not reportable** if it carries fewer than 400 scored rows. At 1d a
   Volatility symbol holds under 2,900 bars and a five-fold walk-forward leaves
   test blocks of a few hundred; those cells are printed with their `n` and not
   pooled into a headline.

## What is being scored, and against what

One bar ahead, `horizon=1`, on `seqlab` folds - expanding walk-forward with a
one-bar purge, never shuffled - so the rows are the rows every other arm in this
study uses.

* **direction** - `seqlab.auc` of Kronos's mean sampled log return against
  `targets['direction']`. Floor 0.50.
* **volatility** - `seqlab.srel` of Kronos's mean sampled absolute return against
  `targets['realised']`, which at `horizon=1` is exactly `|log(c_{t+1}/c_t)|`,
  against three baselines on **identical rows**: the unconditional mean of the
  fold's *train* realised volatility, naive last-realised (`rv1`, which is
  `|r_t|`), and log-HAR over the `seqlab.HAR` triple fitted on the fold's train
  rows. A foundation model that loses to a straight line is a finding.

Every headline carries three controls beside it: `shuffle` (targets permuted
inside the test block), `surrogate` (phase-randomised returns, spectrum kept),
and `gbm` (simulated geometric Brownian motion at the symbol's true
`seqlab.NAMED_SIGMA`, or at its measured sigma where the name does not publish
one).

## The budget, stated rather than implied

The lab has 64 cores, 125GB and **no GPU**, and five other agents share it, so
this runs on 8 threads. Measured by `kronosboot`: 195 windows/s at ctx=128,
84/s at 256, 29/s at 512. Kronos-mini's published context is 2048.

**ctx=128 bars and 64 samples per row** is the budget, and `--sweep` measures
what the choice costs by scoring one synthetic and one real cell at 64, 128, 256
and 512. Scored rows are capped per cell and decimated uniformly inside each
test fold; the baselines are scored on those same rows, never on the full block,
because a baseline scored on more rows than the model is not a baseline.

    ./.secrets/lab.sh run research/harness/kronos.py TFS=1h,4h
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

from research.harness import kronoslib, seqlab

RESULTS = Path.home() / "till_infinity" / "results"

#: Scored test rows per (symbol, timeframe, arm), decimated uniformly inside
#: each fold. 2,000 rows puts the AUC standard error near 0.013, which is small
#: against every effect this page could honestly claim to see.
CAP = int(os.environ.get("CAP", 2000))

#: Train rows per fold used to fit the single scale constant that puts Kronos's
#: volatility readout on the target's units. Train only, and decimated, because
#: it is one parameter and does not need 10,000 rows to find.
CAL = int(os.environ.get("CAL", 250))

CTX = int(os.environ.get("CTX", 128))
SAMPLES = int(os.environ.get("SAMPLES", 64))
FOLDS = int(os.environ.get("NFOLDS", 5))

#: Ordered so the two commissioned timeframes land first and the page is
#: readable from a partial run.
TFS = tuple(os.environ.get("TFS", "1h,4h,1d,15m,6h,12h,8h,3m").split(","))

ARMS = ("feed", "surrogate", "gbm")

#: Below this a cell's AUC band is wider than anything it could report.
FEWEST_SCORED = 400


def sigma_for(symbol: str, bars: dict, interval: str) -> tuple[float, str]:
    """The true sigma where the instrument's name publishes one, else the measured one.

    `research/grounding.md` tier 1 verified the named sigmas to within 0.49% on
    12 of 12, so on a Volatility member the simulated null can be built at the
    **true** parameter rather than a fitted one - which is what makes it a null
    and not a second fit.
    """
    if symbol in seqlab.NAMED_SIGMA:
        return seqlab.NAMED_SIGMA[symbol], "named"
    return kronoslib.measured_sigma(bars, interval), "measured"


def prepare(bars: dict, ctx: int):
    """Feature matrix, targets and the rows usable to both the baselines and Kronos."""
    x, names = seqlab.build(bars)
    y = seqlab.targets(bars, horizon=1)
    ok = seqlab.usable(x, y["logvol"]) & np.isfinite(y["direction"])
    ok &= np.arange(len(ok)) >= ctx - 1
    return x, names, y, np.flatnonzero(ok)


def cell(symbol: str, interval: str, arm: str, reader: kronoslib.Reader,
         *, cap: int = CAP, seed: int = 17, log=print) -> dict | None:
    """One (symbol, timeframe, arm). Returns pooled scores or None if too thin."""
    rng = np.random.default_rng(seed)
    bars = seqlab.load(symbol, interval)
    sigma, how = sigma_for(symbol, bars, interval)
    if arm == "surrogate":
        bars = kronoslib.surrogate_bars(bars, rng)
    elif arm == "gbm":
        bars = kronoslib.gbm_like(bars, sigma, interval, rng)

    ctx = reader.ctx
    x, names, y, idx = prepare(bars, ctx)
    folds = seqlab.walk_forward(len(idx), folds=FOLDS, horizon=1)
    if not folds:
        return None

    total = sum(len(te) for _, te in folds)
    stride = max(1, int(np.ceil(total / cap)))

    xk, stamp = kronoslib.frame(bars)
    pooled: dict[str, list[np.ndarray]] = {}

    def keep(k, v):
        pooled.setdefault(k, []).append(np.asarray(v, dtype=float))

    began = time.time()
    for tr, te in folds:
        te_s = te[::stride]
        if len(te_s) < 30:
            continue
        rows_te = idx[te_s]
        rows_tr = idx[tr]
        cal = rows_tr[:: max(1, len(rows_tr) // CAL)][:CAL]
        cal = cal[cal >= ctx - 1]

        got = reader.readout(xk, stamp, rows_te, batch=32)
        cal_got = reader.readout(xk, stamp, cal, batch=32) if len(cal) >= 40 else None

        rv_te = y["realised"][rows_te]
        rv_tr = y["realised"][rows_tr]
        lab = y["direction"][rows_te]

        keep("label", lab)
        keep("realised", rv_te)
        keep("k_dir", got["mean_r"])
        keep("k_dir_raw", got["mean_raw"])
        keep("entropy", got["entropy"])

        # One scale constant per readout per fold, fitted on train rows only.
        for src, name in (("mean_absr", "k_vol_absr"), ("sd_r", "k_vol_sd"),
                          ("mean_logrange", "k_vol_range")):
            if cal_got is None:
                keep(name, np.full(len(rows_te), np.nan))
                continue
            num = np.median(y["realised"][cal])
            den = np.median(cal_got[src])
            a = num / den if np.isfinite(den) and den > 0 else np.nan
            keep(name, a * got[src])

        keep("b_mean", np.full(len(rows_te), float(np.nanmean(rv_tr))))
        keep("b_naive", x[rows_te][:, names.index("rv1")])
        beta, smear = kronoslib.har_fit(x, names, y["realised"], rows_tr)
        keep("b_har", kronoslib.har_predict(x, names, rows_te, beta, smear))

    if not pooled:
        return None
    p = {k: np.concatenate(v) for k, v in pooled.items()}
    n = len(p["label"])
    took = time.time() - began

    rng2 = np.random.default_rng(seed + 1)
    shuffled = seqlab.shuffle_target(p["label"].copy(), rng2)
    shuffled_rv = seqlab.shuffle_target(p["realised"].copy(), rng2)

    out = {
        "symbol": symbol, "interval": interval, "arm": arm, "n": int(n),
        "ctx": ctx, "samples": reader.samples, "stride": int(stride),
        "folds": len(folds), "seconds": round(took, 1),
        "sigma": round(float(sigma), 4), "sigma_from": how,
        "up_rate": round(float(np.mean(p["label"])), 4),
        "entropy": round(float(np.mean(p["entropy"])), 3),
        "auc_dir": round(seqlab.auc(p["k_dir"], p["label"]), 4),
        "auc_dir_raw": round(seqlab.auc(p["k_dir_raw"], p["label"]), 4),
        "auc_dir_shuffled": round(seqlab.auc(p["k_dir"], shuffled), 4),
        "auc_se": round(kronoslib.boot_auc(p["k_dir"], p["label"]), 4),
    }
    for k in ("k_vol_absr", "k_vol_sd", "k_vol_range", "b_mean", "b_naive", "b_har"):
        out[f"srel_{k}"] = round(seqlab.srel(p[k], p["realised"]), 4)
    out["srel_k_vol_absr_shuffled"] = round(seqlab.srel(p["k_vol_absr"], shuffled_rv), 4)
    out["srel_b_naive_shuffled"] = round(seqlab.srel(p["b_naive"], shuffled_rv), 4)
    out["thin"] = bool(n < FEWEST_SCORED)
    log("  " + json.dumps(out, default=float))
    return out


def family(rows: list[dict], names: tuple[str, ...], interval: str, arm: str) -> dict:
    """Pool a family's cells. Per-symbol AUCs, not a pooled-row AUC.

    Pooling rows across symbols would let one long series carry the number and
    would mix instruments with different sigmas into one ranking, which is how
    `research/rebuilding.md`'s 0.96 on feed identity happened. The family
    statistic here is the **median over symbols** with the spread beside it, and
    `seqlab.max_of_k` on the best cell against the `gbm` draws, because with 25
    symbols the best of 25 fair coins clears 0.52 routinely.
    """
    take = [r for r in rows if r["interval"] == interval and r["arm"] == arm
            and r["symbol"] in names and not r["thin"]]
    if not take:
        return {}
    aucs = np.array([r["auc_dir"] for r in take])
    out = {"interval": interval, "arm": arm, "cells": len(take),
           "rows": int(sum(r["n"] for r in take)),
           "auc_median": round(float(np.median(aucs)), 4),
           "auc_min": round(float(aucs.min()), 4),
           "auc_max": round(float(aucs.max()), 4)}
    for k in ("k_vol_absr", "k_vol_sd", "k_vol_range", "b_mean", "b_naive", "b_har"):
        v = np.array([r[f"srel_{k}"] for r in take], dtype=float)
        out[f"srel_{k}"] = round(float(np.nanmedian(v)), 4)
    out["beats_mean"] = int(sum(r["srel_k_vol_absr"] < r["srel_b_mean"] for r in take))
    out["naive_beats_mean"] = int(sum(r["srel_b_naive"] < r["srel_b_mean"] for r in take))
    return out


def sweep(reader_for, symbol: str, interval: str, log=print) -> list[dict]:
    """What the context budget buys. One synthetic cell, one real cell, four lengths."""
    out = []
    for ctx in (64, 128, 256, 512):
        r = reader_for(ctx)
        began = time.time()
        got = cell(symbol, interval, "feed", r, cap=600, log=lambda s: None)
        if got:
            got["wallclock_per_1k_rows"] = round(
                (time.time() - began) / max(got["n"], 1) * 1000, 1)
            out.append(got)
            log(f"  ctx {ctx:4d}  n {got['n']:5d}  auc {got['auc_dir']:.4f}  "
                f"srel {got['srel_k_vol_absr']:.4f}  mean {got['srel_b_mean']:.4f}  "
                f"{got['wallclock_per_1k_rows']:.0f}s/1k rows")
    return out


def main() -> int:
    kronoslib.threads()
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS / "kronos_zero.jsonl"
    print(f"kronos - zero-shot, ctx {CTX}, {SAMPLES} samples, cap {CAP} rows/cell")
    print(f"timeframes: {', '.join(TFS)}\n", flush=True)

    model, tok = kronoslib.load_pair("mini")

    v = kronoslib.verify(model, tok)
    print("verify: " + json.dumps(v, default=float), flush=True)
    if not v["clean"]:
        print("VOID - the cached decoder is not upstream. No score below is readable.")
        return 1

    reader = kronoslib.Reader(model, tok, ctx=CTX, samples=SAMPLES)
    bars = seqlab.load("Volatility 75 Index", "1h")
    c = kronoslib.check_causality(reader, bars)
    print("causality: " + json.dumps(c, default=float), flush=True)
    if not c["clean"]:
        print("VOID - a future bar moved the model's logits.")
        return 1

    if os.environ.get("SWEEP", "1") == "1":
        print("\n-- context budget --", flush=True)
        swept = []
        for sym in ("Volatility 75 Index", "XAUUSD"):
            print(f" {sym} 1h", flush=True)
            swept += sweep(lambda k: kronoslib.Reader(model, tok, ctx=k, samples=SAMPLES),
                           sym, "1h")
        (RESULTS / "kronos_sweep.json").write_text(json.dumps(swept, indent=2, default=float))

    universe = list(seqlab.VOLATILITY) + list(seqlab.REAL)
    if os.environ.get("SYMS"):
        # Comma-separated, underscores for spaces: `lab.sh run` forwards env through `env $*`,
        # which splits a value containing a space into two arguments.
        want = {t.replace("_", " ") for t in os.environ["SYMS"].split(",")}
        universe = [s for s in universe if s in want]
    rows: list[dict] = []
    if out_path.exists():
        rows = [json.loads(ln) for ln in out_path.read_text().splitlines() if ln.strip()]
    seen = {(r["symbol"], r["interval"], r["arm"]) for r in rows}
    print(f"\n-- grid: {len(universe)} symbols x {len(TFS)} timeframes x {len(ARMS)} arms "
          f"({len(seen)} already done) --", flush=True)

    began = time.time()
    with out_path.open("a") as fh:
        for interval in TFS:
            for symbol in universe:
                for arm in ARMS:
                    if (symbol, interval, arm) in seen:
                        continue
                    try:
                        got = cell(symbol, interval, arm, reader)
                    except seqlab.Thin as exc:
                        print(f"  thin {symbol} {interval}: {exc}", flush=True)
                        continue
                    except Exception as exc:  # noqa: BLE001 - one bad cell must not stop the grid
                        print(f"  ! {symbol} {interval} {arm}: "
                              f"{type(exc).__name__}: {str(exc)[:120]}", flush=True)
                        continue
                    if got is None:
                        continue
                    rows.append(got)
                    fh.write(json.dumps(got, default=float) + "\n")
                    fh.flush()
            print(f"-- {interval} done, {(time.time()-began)/60:.1f}m elapsed --", flush=True)

            for names, tag in ((seqlab.VOLATILITY, "volatility"), (seqlab.REAL, "real")):
                for arm in ARMS:
                    f = family(rows, names, interval, arm)
                    if f:
                        print(f"   {tag:11s} {json.dumps(f, default=float)}", flush=True)

    print(f"\nwrote {out_path}  ({len(rows)} cells, {(time.time()-began)/60:.1f}m)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
