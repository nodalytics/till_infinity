"""The positive control: run the identical pipeline on a market where the answer is known.

**This is the arm that makes the other five falsifiable.** Five arms - recurrent
nets, echo state networks, Kronos, a reinforcement learner, the non-Volatility
synthetics - are all expected to come back negative on the Volatility family, and
`research/rebuilding.md` and `research/deriving.md` between them give strong
reasons why they should. But a folder of negative results is worth nothing on its
own. "We found nothing" and "this instrument cannot find anything" produce the
same table, and only one of them is a finding about the market.

So: the same loader, the same features, the same folds, the same metric, on
XAUUSD, EURUSD, GBPUSD, USDJPY and BTCUSD, where **volatility clustering is one
of the most replicated facts in empirical finance**. If this pipeline cannot see
it there, every negative on the synthetic side is a statement about
`seqlab.py` and the whole study is void.

## The specific claim being audited

`seqlab.main()` prints, on `Volatility 75 Index` at 1h:

    vol: naive srel 0.8802   mean srel 0.6691
    gbm: naive srel 0.8809   mean srel 0.6642

and the reading offered is that the unconditional mean beats the last realised
value because sigma on a Volatility index is genuinely constant, with the
simulated GBM agreeing to three decimals as confirmation. **That reading is only
established if the same measurement inverts on a real market**, and nobody has
checked. This file checks, and it does not assume the inversion will happen.

## Why the statistic is run four ways rather than once

At `horizon = 1` the target `realised` is `|r_{t+1}|` - a single squared return,
the noisiest possible estimate of a variance. Under `srel` (a symmetric relative
error) a forecaster is charged for *its own* noise as well as for its bias, and
`|r_t|` carries a full half-normal of noise where a constant carries none. That
means the h=1 comparison can fail to inverta on gold **for a reason that has
nothing to do with whether gold's volatility clusters**, and reading a
non-inversion there as "the harness is broken" would be as wrong as reading the
inversion on V75 as "sigma is constant".

The design therefore separates the two:

* **The published statistic, replicated exactly** - `rv1` against the sample
  mean at h=1. Whatever it does, it is reported.
* **The matched-window statistic** - at horizon `h` the naive forecast is the
  realised volatility over the *last* `h` bars, so `rv1`/`rv5`/`rv22` against
  targets at h=1/5/22. This is the comparison HAR is built on and the one where
  the estimator noise falls as `1/sqrt(2h)`.
* **A model** - the HAR ridge on `log rv1, log rv5, log rv22`, and a ridge on
  the entire 28-column `seqlab` feature matrix. An instrument that cannot fit a
  known signal cannot be trusted to report its absence.
* **The clustering statistic that cannot be confounded by any of this** - the
  rank autocorrelation of `|r|`. It has no forecaster, no loss function and no
  metric convention inside it. If gold's is positive and the Volatility family's
  is zero, clustering is present and detected, whatever `srel` does.

Three columns throughout: the real market, the Volatility family, and a
**simulated GBM at each symbol's own sigma** through `seqlab.gbm_bars` - the
known null, on the same folds, with the same feature code.

## What would count as failure, written before any number was read

1. **The study is void** if `check_causality` reports a leaking feature on a real
   symbol. A look-ahead is the one bug that makes every arm succeed.
2. **The harness is broken** if the rank autocorrelation of `|r|` on XAUUSD is
   not clearly positive at the timeframes where five years of history exist. That
   is not a subtle effect; it is the reason GARCH exists.
3. **The harness is broken** if the HAR ridge cannot beat the unconditional mean
   out of sample on real markets in log-volatility R-squared.
4. **The published reading of the srel gap is wrong** if the gap fails to invert
   on real markets at *every* horizon while condition 2 passes - because then the
   gap is measuring target noise rather than the constancy of sigma, and every
   page that reads its sign as generator identification needs the correction.
5. **The measurement has no power** and must be reported as such if the
   discriminator `n*` between a Volatility index and gold exceeds the bars
   actually available at that timeframe.

Threads are capped at eight in total - eight worker processes with one BLAS
thread each - because five sibling arms share the box.

    ./.secrets/lab.sh run research/harness/seqcontrol.py
"""

from __future__ import annotations

import os

# Before numpy: the BLAS thread pool is sized at import and cannot be shrunk
# afterwards, and eight arms each grabbing 64 threads is how the lab stalls.
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_var] = "1"

import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402

import numpy as np  # noqa: E402

from research.harness import seqlab  # noqa: E402

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/seqcontrol.json"))
SEED = int(os.environ.get("SEED", "20260912"))
WORKERS = int(os.environ.get("WORKERS", "8"))

#: The three horizons, and the reason they are these three. `seqlab.HAR` is
#: `(1, 5, 22)`, so at each horizon there is already a feature that is exactly
#: the trailing realised volatility over the matching window - the naive
#: forecast is then a like-for-like comparison rather than a mismatch of scales.
HORIZONS = (1, 5, 22)

#: The Volatility symbols carried into the comparison. All twenty would triple
#: the runtime to say the same thing twice: the family is one process at ten
#: parameters, and `research/twins.md` verified the stated sigma on twelve of
#: twelve. Five standard members spanning 10% to 100% plus one `1s` variant is
#: enough to show the column is flat, and the cross-sectional arm
#: (`seqcross.py`) reads all twenty-two anyway.
VOL_SAMPLE = (
    "Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index",
    "Volatility 75 Index", "Volatility 100 Index", "Volatility 75 (1s) Index",
)


# --------------------------------------------------------------------------
# Metrics that are not in seqlab, because they are specific to this question
# --------------------------------------------------------------------------


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Rank correlation. Used on `|r|` because the tails and the zeros both bite.

    Pearson on `|r|` is dominated by the largest handful of moves - on BTCUSD at
    3m, four bars out of forty thousand - and Pearson on `log |r|` is dominated
    by the *smallest*, because a quantised feed prints exact zeros and `log 0`
    has to be floored. Ranks are immune to both and the statistic still answers
    the only question being asked: does a big bar follow a big bar.
    """
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 30:
        return float("nan")
    ra, rb = _rank(a), _rank(b)
    ra, rb = ra - ra.mean(), rb - rb.mean()
    den = math.sqrt(float((ra * ra).sum()) * float((rb * rb).sum()))
    return float((ra * rb).sum() / den) if den > 0 else float("nan")


def _rank(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), float)
    ranks[order] = np.arange(len(x), dtype=float)
    return ranks


def ljung_box(x: np.ndarray, lags: int = 10) -> float:
    """Ljung-Box Q on `|r|`. Chi-square with `lags` df; 18.31 is the 95% point at 10.

    Reported rather than a p-value so this file keeps no dependency beyond numpy,
    and because the number that matters here is how many orders of magnitude past
    the critical value a real market lands.
    """
    x = np.asarray(x, float)
    x = x[np.isfinite(x)] - np.mean(x[np.isfinite(x)])
    n = len(x)
    if n < 50 * lags:
        return float("nan")
    den = float((x * x).sum())
    q = 0.0
    for k in range(1, lags + 1):
        r = float((x[k:] * x[:-k]).sum()) / den
        q += r * r / (n - k)
    return float(n * (n + 2) * q)


def log_r2(pred: np.ndarray, truth: np.ndarray, baseline_log: float) -> float:
    """Out-of-sample R-squared of log realised volatility against the train mean.

    The scale-free score for a volatility forecast, and the one that is
    comparable across a 10% index and BTCUSD. `baseline_log` is the *training*
    mean of `log realised` - using the test mean would be the quiet leak that
    makes every fold look better than it is.
    """
    p, t = np.asarray(pred, float), np.asarray(truth, float)
    ok = np.isfinite(p) & np.isfinite(t) & (p > 0) & (t > 0)
    if ok.sum() < 30:
        return float("nan")
    lp, lt = np.log(p[ok]), np.log(t[ok])
    ss_res = float(((lt - lp) ** 2).sum())
    ss_tot = float(((lt - baseline_log) ** 2).sum())
    return float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")


def gap_se(pred_naive: np.ndarray, pred_mean: np.ndarray, truth: np.ndarray,
           rng: np.random.Generator, *, draws: int = 300) -> float:
    """Moving-block bootstrap standard error of `srel(mean) - srel(naive)`.

    `seqlab.nstar` takes a standard error and defaults it to 0.01, which is a
    placeholder. Every quantity here is computed on overlapping windows of an
    autocorrelated series where the iid formula understates the error, and an
    `n*` built on an understated error says the question needs less data than it
    does - the direction that gets a null declared early.
    """
    n = len(truth)
    if n < 200:
        return float("nan")
    out = np.empty(draws)
    for i in range(draws):
        idx = seqlab.moving_block(n, rng)
        out[i] = seqlab.srel(pred_mean[idx], truth[idx]) - seqlab.srel(pred_naive[idx], truth[idx])
    return float(np.std(out, ddof=1))


# --------------------------------------------------------------------------
# One (kind, symbol, timeframe) cell
# --------------------------------------------------------------------------


def measure(bars: dict[str, np.ndarray], tag: str) -> dict:
    """Every number this page reports, for one series. Folds and metric shared with every arm."""
    rng = np.random.default_rng(SEED)
    x, names = seqlab.build(bars)
    rv_at = {1: names.index("rv1"), 5: names.index("rv5"), 22: names.index("rv22")}
    ret = np.concatenate(([np.nan], np.diff(np.log(bars["close"]))))
    absret = np.abs(ret[1:])

    # Clustering, measured with no forecaster and no loss function in the way.
    out: dict = {
        "tag": tag,
        "n_bars": int(len(bars["close"])),
        "frac_zero_ret": float(np.mean(absret == 0.0)),
        "ac1_absret_spearman": spearman(absret[:-1], absret[1:]),
        "ac1_absret_pearson": float(np.corrcoef(absret[:-1], absret[1:])[0, 1])
        if len(absret) > 100 else float("nan"),
        "ljung_box_10": ljung_box(absret, 10),
        "sigma_ann": float(np.nanstd(ret) * math.sqrt(seqlab.PER_YEAR[tag.split("|")[-1]])),
        "horizons": {},
    }

    for h in HORIZONS:
        y = seqlab.targets(bars, horizon=h)
        ok = seqlab.usable(x, y["logvol"])
        if ok.sum() < seqlab.FEWEST:
            out["horizons"][h] = {"skipped": f"{int(ok.sum())} usable rows"}
            continue
        xs, rv_true = x[ok], y["realised"][ok]
        folds = seqlab.walk_forward(int(ok.sum()), folds=5, horizon=h)
        if not folds:
            out["horizons"][h] = {"skipped": "no folds"}
            continue

        har_cols = [rv_at[k] for k in seqlab.HAR]
        keep: dict[str, list[np.ndarray]] = {k: [] for k in
                                             ("truth", "mean", "naive1", "naive_h", "har", "full")}
        base_logs: list[np.ndarray] = []
        for tr, te in folds:
            ytr, yte = rv_true[tr], rv_true[te]
            ltr = np.log(np.maximum(ytr, 1e-12))
            keep["truth"].append(yte)
            keep["mean"].append(np.full(len(te), float(ytr.mean())))
            keep["naive1"].append(xs[te, rv_at[1]])
            keep["naive_h"].append(xs[te, rv_at[h]])
            with np.errstate(divide="ignore", invalid="ignore"):
                lh_tr = np.log(np.maximum(xs[tr][:, har_cols], 1e-12))
                lh_te = np.log(np.maximum(xs[te][:, har_cols], 1e-12))
            keep["har"].append(np.exp(np.clip(
                seqlab.ridge(lh_tr, ltr, lh_te, lam=1.0), -40.0, 5.0)))
            keep["full"].append(np.exp(np.clip(
                seqlab.ridge(xs[tr], ltr, xs[te], lam=10.0), -40.0, 5.0)))
            base_logs.append(np.full(len(te), float(ltr.mean())))

        pooled = {k: np.concatenate(v) for k, v in keep.items()}
        base = float(np.concatenate(base_logs).mean())
        truth = pooled["truth"]
        row = {
            "n_test": int(len(truth)),
            "n_eff": float(len(truth) / h),
            "folds": len(folds),
            "srel": {k: seqlab.srel(pooled[k], truth)
                     for k in ("mean", "naive1", "naive_h", "har", "full")},
            "log_r2": {k: log_r2(pooled[k], truth, base)
                       for k in ("mean", "naive1", "naive_h", "har", "full")},
        }
        row["gap_published"] = row["srel"]["mean"] - row["srel"]["naive1"]
        row["gap_matched"] = row["srel"]["mean"] - row["srel"]["naive_h"]
        row["gap_published_se"] = gap_se(pooled["naive1"], pooled["mean"], truth, rng)
        row["gap_matched_se"] = gap_se(pooled["naive_h"], pooled["mean"], truth, rng)
        out["horizons"][h] = row
    return out


def job(spec: tuple[str, str, str]) -> dict:
    """One cell, in its own process. `kind` is real, vol or gbm."""
    kind, symbol, interval = spec
    try:
        if kind == "gbm":
            rng = np.random.default_rng(abs(hash((symbol, interval, SEED))) % (2**31))
            real = seqlab.load(symbol, interval)
            ret = np.diff(np.log(real["close"]))
            sigma = float(np.nanstd(ret) * math.sqrt(seqlab.PER_YEAR[interval]))
            sigma = seqlab.NAMED_SIGMA.get(symbol, sigma)
            bars = seqlab.gbm_bars(sigma, len(real["close"]), interval, rng)
        else:
            bars = seqlab.load(symbol, interval)
        got = measure(bars, f"{symbol}|{interval}")
        got.update(kind=kind, symbol=symbol, interval=interval, ok=True)
    except Exception as exc:  # noqa: BLE001 - one absent feed must not end the study
        return {"kind": kind, "symbol": symbol, "interval": interval,
                "ok": False, "why": f"{type(exc).__name__}: {str(exc)[:110]}"}
    return got


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def _fmt(v: float, w: int = 7, p: int = 4) -> str:
    return f"{'':>{w}}" if v is None or not np.isfinite(v) else f"{v:{w}.{p}f}"


def causality_gate() -> dict:
    """Condition 1, on a real symbol and on a synthetic, before any score is printed."""
    print("=== Condition 1: the leak boundary, on both sides of the comparison ===\n")
    got = {}
    for symbol in ("XAUUSD", "Volatility 75 Index"):
        for interval in ("1h",):
            try:
                verdict = seqlab.check_causality(seqlab.load(symbol, interval))
                got[f"{symbol}|{interval}"] = verdict
                state = "CLEAN" if verdict["clean"] else "LEAKING " + str(verdict["leaking"])
                print(f"    {symbol:24s} {interval:4s} {state}  "
                      f"({verdict['rows_checked']:,} rows checked)")
            except Exception as exc:  # noqa: BLE001
                got[f"{symbol}|{interval}"] = {"clean": None, "why": str(exc)[:100]}
                print(f"    {symbol:24s} {interval:4s} unavailable: {str(exc)[:70]}")
    return got


def main() -> None:
    began = time.time()
    print("=" * 108)
    print("seqcontrol.py - the positive control: the same pipeline on a market with a known answer")
    print("=" * 108 + "\n")

    res: dict = {"seed": SEED, "horizons": list(HORIZONS), "grid": list(seqlab.GRID)}
    res["causality"] = causality_gate()

    specs: list[tuple[str, str, str]] = []
    for interval in seqlab.GRID:
        for symbol in seqlab.REAL:
            specs.append(("real", symbol, interval))
            specs.append(("gbm", symbol, interval))
        for symbol in VOL_SAMPLE:
            specs.append(("vol", symbol, interval))
            specs.append(("gbm_vol", symbol, interval))
    print(f"\n{len(specs)} cells: {len(seqlab.REAL)} real, {len(VOL_SAMPLE)} volatility, "
          f"and a simulated GBM for each, across {len(seqlab.GRID)} timeframes\n", flush=True)

    cells: list[dict] = []
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(job, ("gbm" if s[0].startswith("gbm") else s[0], s[1], s[2])): s
                   for s in specs}
        for i, fut in enumerate(as_completed(futures), 1):
            spec = futures[fut]
            got = fut.result()
            got["kind"] = spec[0]
            cells.append(got)
            if not got.get("ok"):
                print(f"  ! {spec[1]} {spec[2]} [{spec[0]}] {got.get('why')}", flush=True)
            if i % 25 == 0 or i == len(specs):
                print(f"  {i}/{len(specs)}  {(time.time() - began) / 60:.1f}m", flush=True)
    res["cells"] = cells
    good = [c for c in cells if c.get("ok")]

    def pick(kind: str, interval: str, h: int) -> list[dict]:
        out = []
        for c in good:
            if c["kind"] != kind or c["interval"] != interval:
                continue
            row = c.get("horizons", {}).get(h) or c.get("horizons", {}).get(str(h))
            if row and "srel" in row:
                out.append({"symbol": c["symbol"], **row, "ac1": c["ac1_absret_spearman"]})
        return out

    # ---- Section 2: the published statistic, replicated ------------------
    print("\n\n=== Section 2: the published statistic (rv1 vs the sample mean, horizon 1) ===")
    print("    gap = srel(mean) - srel(naive).  gap < 0 is what V75 1h showed: the mean wins.")
    print("    The claim under audit is that this sign inverts on a real market.\n")
    print(f"    {'timeframe':10s} {'group':10s} {'n_sym':>5s} {'naive':>8s} {'mean':>8s} "
          f"{'gap':>9s} {'+-se':>7s} {'n_test':>9s}")
    table2: dict = {}
    for interval in seqlab.GRID:
        for kind, label in (("real", "real"), ("vol", "volatility"),
                            ("gbm", "gbm@realsig"), ("gbm_vol", "gbm@volsig")):
            rows = pick(kind, interval, 1)
            if not rows:
                continue
            gaps = np.array([r["gap_published"] for r in rows])
            ses = np.array([r["gap_published_se"] for r in rows])
            table2.setdefault(interval, {})[label] = {
                "n_symbols": len(rows),
                "naive": float(np.mean([r["srel"]["naive1"] for r in rows])),
                "mean": float(np.mean([r["srel"]["mean"] for r in rows])),
                "gap": float(np.mean(gaps)),
                "gap_sd_across_symbols": float(np.std(gaps, ddof=1)) if len(gaps) > 1 else float("nan"),
                "se_within_symbol": float(np.nanmean(ses)),
                "n_test_median": float(np.median([r["n_test"] for r in rows])),
                "per_symbol": {r["symbol"]: r["gap_published"] for r in rows},
            }
            t = table2[interval][label]
            print(f"    {interval:10s} {label:10s} {t['n_symbols']:5d} {_fmt(t['naive'],8)} "
                  f"{_fmt(t['mean'],8)} {_fmt(t['gap'],9)} {_fmt(t['se_within_symbol'],7,3)} "
                  f"{t['n_test_median']:9,.0f}")
    res["published_statistic"] = table2

    # ---- Section 3: matched window ---------------------------------------
    print("\n\n=== Section 3: the matched-window statistic (rv_h vs the mean, horizon h) ===")
    print("    At h the naive forecast is the realised volatility of the last h bars, so the")
    print("    forecaster's own estimator noise falls as 1/sqrt(2h) and the comparison is the")
    print("    one HAR is built on.\n")
    print(f"    {'timeframe':10s} {'h':>3s} {'group':10s} {'naive_h':>8s} {'mean':>8s} "
          f"{'gap':>9s} {'har R2':>8s} {'full R2':>8s} {'n_eff':>9s}")
    table3: dict = {}
    for interval in seqlab.GRID:
        for h in HORIZONS:
            for kind, label in (("real", "real"), ("vol", "volatility"),
                                ("gbm", "gbm@realsig"), ("gbm_vol", "gbm@volsig")):
                rows = pick(kind, interval, h)
                if not rows:
                    continue
                cell = {
                    "n_symbols": len(rows),
                    "naive_h": float(np.mean([r["srel"]["naive_h"] for r in rows])),
                    "mean": float(np.mean([r["srel"]["mean"] for r in rows])),
                    "gap": float(np.mean([r["gap_matched"] for r in rows])),
                    "se_within_symbol": float(np.nanmean([r["gap_matched_se"] for r in rows])),
                    "har_log_r2": float(np.mean([r["log_r2"]["har"] for r in rows])),
                    "full_log_r2": float(np.mean([r["log_r2"]["full"] for r in rows])),
                    "naive_log_r2": float(np.mean([r["log_r2"]["naive_h"] for r in rows])),
                    "n_eff_median": float(np.median([r["n_eff"] for r in rows])),
                    "per_symbol_gap": {r["symbol"]: r["gap_matched"] for r in rows},
                    "per_symbol_har_r2": {r["symbol"]: r["log_r2"]["har"] for r in rows},
                }
                table3.setdefault(interval, {}).setdefault(str(h), {})[label] = cell
                print(f"    {interval:10s} {h:3d} {label:10s} {_fmt(cell['naive_h'],8)} "
                      f"{_fmt(cell['mean'],8)} {_fmt(cell['gap'],9)} "
                      f"{_fmt(cell['har_log_r2'],8)} {_fmt(cell['full_log_r2'],8)} "
                      f"{cell['n_eff_median']:9,.0f}")
    res["matched_window"] = table3

    # ---- Section 4: clustering, with nothing in the way -------------------
    print("\n\n=== Section 4: rank autocorrelation of |r| - clustering with no forecaster in the way ===")
    print("    Condition 2 fires if this is not clearly positive on real markets.\n")
    print(f"    {'timeframe':10s} {'group':10s} {'ac1':>8s} {'range':>20s} {'LB(10)':>12s} "
          f"{'n_bars':>9s}   (chi2 95% = 18.31)")
    table4: dict = {}
    for interval in seqlab.GRID:
        for kind, label in (("real", "real"), ("vol", "volatility"),
                            ("gbm", "gbm@realsig"), ("gbm_vol", "gbm@volsig")):
            rows = [c for c in good if c["kind"] == kind and c["interval"] == interval]
            if not rows:
                continue
            ac = np.array([r["ac1_absret_spearman"] for r in rows], float)
            lb = np.array([r["ljung_box_10"] for r in rows], float)
            n = np.array([r["n_bars"] for r in rows], float)
            cell = {"n_symbols": len(rows), "ac1_mean": float(np.nanmean(ac)),
                    "ac1_min": float(np.nanmin(ac)), "ac1_max": float(np.nanmax(ac)),
                    "ljung_box_median": float(np.nanmedian(lb)),
                    "n_bars_median": float(np.median(n)),
                    "per_symbol": {r["symbol"]: r["ac1_absret_spearman"] for r in rows}}
            table4.setdefault(interval, {})[label] = cell
            print(f"    {interval:10s} {label:10s} {_fmt(cell['ac1_mean'],8)} "
                  f"{_fmt(cell['ac1_min'],9)} to{_fmt(cell['ac1_max'],9)} "
                  f"{cell['ljung_box_median']:12,.1f} {cell['n_bars_median']:9,.0f}")
    res["clustering"] = table4

    # ---- Section 5: the discriminator -------------------------------------
    print("\n\n=== Section 5: how many bars to tell a Volatility index from a real market ===")
    print("    n* from seqlab.nstar, with the standard error measured by a moving-block")
    print("    bootstrap rather than assumed. 'available' is the median bars actually held.\n")
    print(f"    {'timeframe':10s} {'statistic':22s} {'real':>9s} {'vol':>9s} {'se':>8s} "
          f"{'n at':>9s} {'n*':>12s} {'available':>10s}")
    table5: dict = {}
    for interval in seqlab.GRID:
        real4 = table4.get(interval, {}).get("real")
        vol4 = table4.get(interval, {}).get("volatility")
        if real4 and vol4:
            n = real4["n_bars_median"]
            se = 1.0 / math.sqrt(max(n, 2.0))  # rank AC se under the null is 1/sqrt(n)
            ns = seqlab.nstar(real4["ac1_mean"], vol4["ac1_mean"], n, se)
            table5.setdefault(interval, {})["ac1_absret"] = {
                "real": real4["ac1_mean"], "vol": vol4["ac1_mean"], "se": se,
                "n_at": n, "nstar": ns, "available": n}
            print(f"    {interval:10s} {'rank ac1 of |r|':22s} {_fmt(real4['ac1_mean'],9)} "
                  f"{_fmt(vol4['ac1_mean'],9)} {_fmt(se,8,5)} {n:9,.0f} "
                  f"{('inf' if not np.isfinite(ns) else f'{ns:,.0f}'):>12s} {n:10,.0f}")
        for h in HORIZONS:
            r3 = table3.get(interval, {}).get(str(h), {})
            if "real" not in r3 or "volatility" not in r3 or not real4:
                continue
            n = r3["real"]["n_eff_median"]
            se = float(np.nanmean([r3["real"]["se_within_symbol"],
                                   r3["volatility"]["se_within_symbol"]]))
            ns = seqlab.nstar(r3["real"]["gap"], r3["volatility"]["gap"], n, se)
            table5.setdefault(interval, {})[f"gap_h{h}"] = {
                "real": r3["real"]["gap"], "vol": r3["volatility"]["gap"], "se": se,
                "n_at": n, "nstar": ns, "available": table4[interval]["real"]["n_bars_median"]}
            print(f"    {interval:10s} {f'srel gap, h={h}':22s} {_fmt(r3['real']['gap'],9)} "
                  f"{_fmt(r3['volatility']['gap'],9)} {_fmt(se,8,5)} {n:9,.0f} "
                  f"{('inf' if not np.isfinite(ns) else f'{ns:,.0f}'):>12s} "
                  f"{table4[interval]['real']['n_bars_median']:10,.0f}")
    res["discriminator"] = table5

    # ---- The verdict -------------------------------------------------------
    print("\n\n=== The verdict on the four kill conditions ===\n")
    leaks = [k for k, v in res["causality"].items() if v.get("clean") is False]
    real_ac = [table4[i]["real"]["ac1_mean"] for i in table4 if "real" in table4[i]]
    vol_ac = [table4[i]["volatility"]["ac1_mean"] for i in table4 if "volatility" in table4[i]]
    har_beats = []
    for interval in table3:
        for h in table3[interval]:
            cell = table3[interval][h].get("real")
            if cell and np.isfinite(cell["har_log_r2"]):
                har_beats.append(cell["har_log_r2"] > 0.0)
    inverts = []
    for interval in table3:
        for h in table3[interval]:
            cell = table3[interval][h].get("real")
            if cell and np.isfinite(cell["gap"]):
                inverts.append(cell["gap"] > 0.0)
    verdict = {
        "condition_1_leak": {"fired": bool(leaks), "where": leaks},
        "condition_2_clustering": {
            "fired": bool(real_ac) and float(np.nanmax(real_ac)) < 0.02,
            "real_ac1_range": [float(np.nanmin(real_ac)), float(np.nanmax(real_ac))] if real_ac else [],
            "vol_ac1_range": [float(np.nanmin(vol_ac)), float(np.nanmax(vol_ac))] if vol_ac else []},
        "condition_3_har": {"fired": bool(har_beats) and not any(har_beats),
                            "cells_with_positive_oos_r2": int(sum(har_beats)),
                            "cells": len(har_beats)},
        "condition_4_gap_reading": {"fired": bool(inverts) and not any(inverts),
                                    "cells_inverting_on_real": int(sum(inverts)),
                                    "cells": len(inverts)},
    }
    res["verdict"] = verdict
    for name, got in verdict.items():
        print(f"    {name:28s} fired: {str(got['fired']):5s}   {json.dumps({k: v for k, v in got.items() if k != 'fired'})}")

    passed = (not verdict["condition_1_leak"]["fired"]
              and not verdict["condition_2_clustering"]["fired"]
              and not verdict["condition_3_har"]["fired"])
    res["positive_control_passes"] = bool(passed)
    print(f"\n    POSITIVE CONTROL: {'PASSES' if passed else 'FAILS'}")
    print("    (conditions 1-3. Condition 4 is a correction to how the srel gap is read,")
    print("     not a defect in the pipeline - see research/controls.md.)")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    print(f"\nwrote {OUT} in {(time.time() - began) / 60:.1f}m")


if __name__ == "__main__":
    sys.exit(main() or 0)
