"""`winning.md`'s feature scan, run where no feature can possibly work.

`research/calibrating.md`. `calibfpr.py` calibrates the bootstrap this desk puts
intervals on; this file calibrates the other method it uses - the tercile scan
over decision-time features, judged against a permutation control - by running
it on books from `calibnull.py`'s world, where `deriving.md`'s theorem fixes
`E[R | anything knowable at entry] = -(cost)` and no entry feature can separate
winners from losers by more than noise.

## What is and is not null here, which matters

The theorem covers the **mean of R**. It does not cover `P(stop)` or `P(R>0)`,
and those are the other two targets `winning.md` scans. In a world with no edge
whatever, a trade whose stop sits closer in volatility units is genuinely more
likely to be stopped, and a trade whose target sits further away is genuinely
less likely to reach it - both are arithmetic, not information. So:

* **target R** is a true null and is where the false-positive rate is measured;
* **targets `P(stop)` and `P(R>0)` are not null**, and a feature clearing the
  control on them is exactly what a world with no edge in it produces. That is
  not a criticism of the scan, it is a reading instruction for its output, and
  `[6]` measures how strong the mechanical effect is so that `winning.md`'s one
  surviving feature can be read against it.

## Two cost models, because one of them is the whole question

`calibnull.py` charges a round trip as a fixed share of the risk, which makes
`E[R]` the same constant for every trade and gives the cleanest possible null.
The desk's spread is not like that: it is a price, so `spread / risk_price`
varies between trades and `E[R]` varies mechanically with it. `exiting.md`
pre-registered exactly that quantity, and `winning.md` found it is the one
feature that clears its noise floor on `P(stop)`.

Both arms are built. The **flat** arm (cost proportional to risk) is where the
false-positive rate is measured. The **priced** arm (cost a fixed price, so
`spread_over_risk` varies) is where the mechanical effect is measured.

## What would have killed this, declared before any number was read

1. **The permutation control must reject at 5% on null books.** It is an exact
   test under exchangeability and the rows here are independent draws, so
   anything outside 3 standard errors of 0.0500 is an implementation fault in
   this harness or in `winning.py`, and is chased before anything is reported.
2. **The same must hold on pure Gaussian toy data** - 43 independent normal
   features against an independent normal target, which has no market in it at
   all. If the scan machinery cannot recover 5% there it cannot measure
   anything here.
3. **The scan must find an edge that is really there.** A feature with a known
   relationship to R is injected at several sizes; if the scan never finds it,
   a 5% false-positive rate means only that the method never fires.
4. **The pool must be the null the theorem describes**: pooled mean R within 3
   standard errors of the charged cost, on the flat arm, checked before the
   scan runs.
5. **A rate landing on exactly 0.0500** to four decimals is a bug until proved
   otherwise, per `research/README.md`.
6. **If the uncontrolled read fires rarely**, then `winning.md`'s control is
   not doing any work and should not be claimed as the thing that saved it.

Run on the lab, after `calibnull.py`:

    ./.secrets/lab.sh run research/harness/calibscan.py BOOKS=400
"""

from __future__ import annotations

import math
import multiprocessing as mp
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.environ.get("REPO", os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

import research.harness.calibnull as N  # noqa: E402
import research.harness.rebuildgen as G  # noqa: E402
import research.harness.winning as W  # noqa: E402
from till_infinity.shared.replay import walk  # noqa: E402

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/results"))
#: `winning.md`: 397 attributed closes carrying R, split 60/40 by time.
BOOK_N = int(os.environ.get("BOOK_N", "397"))
BOOKS = int(os.environ.get("BOOKS", "400"))
#: Closes in the feature pool. Books are disjoint blocks of a permutation of it.
CLOSES = int(os.environ.get("CLOSES", "220000"))
PERMUTATIONS = int(os.environ.get("PERMUTATIONS", "300"))
#: Trials for the Gaussian toy in [1]. Its whole job is to recover 0.0500, so
#: it wants enough trials that the standard error is under half a point.
TOY_TRIALS = int(os.environ.get("TOY_TRIALS", "600"))
SEED = int(os.environ.get("SEED", "4242"))
WORKERS = int(os.environ.get("WORKERS", str(min(60, os.cpu_count() or 8))))
COST_R = N.COST_R
#: The priced arm's spread, as a share of the *close*, per family. The live
#: `spread_over_risk` has a median near 0.05 and a long right tail; a fixed
#: price spread against a varying risk distance reproduces that shape.
SPREAD_BPS = float(os.environ.get("SPREAD_BPS", "1.2"))
CTX = mp.get_context("fork")

_W: dict[str, object] = {}


def se_rate(p: float, n: int) -> float:
    return math.sqrt(max(p * (1 - p), 1e-12) / max(n, 1))


def fmt_rate(p: float, n: int) -> str:
    return f"{p * 100:5.2f}% +-{se_rate(p, n) * 100:4.2f}"


# ------------------------------------------------------------- the features --
#: Everything knowable at the close of the entry bar. Deliberately the same
#: *kinds* of quantity the live decision carries - trend, stretch, efficiency,
#: position in a range, wick shape, clock - at the same count, because the
#: statistic that matters is the largest gap over the whole set and that depends
#: on how many there are and how correlated they are.
WINDOWS = (5, 10, 20, 50, 100)
#: Computed from the bars alone, by `block_features`.
BAR_FEATS = (
    [f"vol_{w}" for w in WINDOWS]
    + [f"mom_{w}" for w in WINDOWS]
    + [f"eff_{w}" for w in WINDOWS]
    + [f"pos_{w}" for w in WINDOWS]
    + [f"up_share_{w}" for w in WINDOWS]
    + ["vol_stretch", "vol_stretch_fast", "range_bps", "range_stretch", "gap_vol",
       "wick_above_vol", "wick_below_vol", "run_len", "absret_vol", "touches_50",
       "dist_high_50", "dist_low_50", "hour_n", "minute_n"]
)
#: Known at entry but a property of the order rather than of the chart. The two
#: wicks are re-expressed relative to the side the trade took, the way
#: `winning.features_of` does it, because a tercile of a raw wick is a tercile
#: of `side`.
TRADE_FEATS = ["wick_ahead", "wick_behind", "reward_to_risk", "risk_vol", "stop_vol",
               "target_vol", "expected_hold", "spread_over_risk"]
FEAT_NAMES = BAR_FEATS + TRADE_FEATS


def _rolling(x: np.ndarray, w: int):
    """(mean, sd) of `x` over a trailing window, aligned so index i is closed."""
    c1 = np.concatenate([[0.0], np.cumsum(x)])
    c2 = np.concatenate([[0.0], np.cumsum(x * x)])
    n = x.size
    mean = np.zeros(n)
    sd = np.zeros(n)
    s1 = c1[w:] - c1[:-w]
    s2 = c2[w:] - c2[:-w]
    mean[w - 1:] = s1 / w
    sd[w - 1:] = np.sqrt(np.maximum((s2 - s1 * s1 / w) / (w - 1), 0.0))
    return mean, sd


def block_features(bars: dict) -> dict[str, np.ndarray]:
    """Everything the scan will tercile, computed once per block of bars."""
    o, h, low, c = bars["open"], bars["high"], bars["low"], bars["close"]
    n = c.size
    lr = np.zeros(n)
    lr[1:] = np.diff(c) / c[:-1]
    out: dict[str, np.ndarray] = {}
    for w in WINDOWS:
        mean, sd = _rolling(lr, w)
        out[f"vol_{w}"] = sd * 1e4
        out[f"mom_{w}"] = mean * w / np.maximum(sd * math.sqrt(w), 1e-12)
        net = np.zeros(n)
        net[w:] = np.abs(c[w:] - c[:-w])
        gross = np.zeros(n)
        acc = np.concatenate([[0.0], np.cumsum(np.abs(np.diff(c, prepend=c[0])))])
        gross[w:] = acc[w + 1:] - acc[1:n - w + 1]
        out[f"eff_{w}"] = net / np.maximum(gross, 1e-12)
        hi = np.zeros(n)
        lo = np.zeros(n)
        # A trailing max/min by strides is O(n w); w is at most 100 and this runs
        # once per block of 200,000 bars, so it is cheaper than it looks.
        for k in range(w):
            shifted = np.concatenate([np.full(k, np.nan), h[:n - k]])
            hi = np.fmax(hi, np.nan_to_num(shifted, nan=-np.inf)) if k else h.copy()
            shifted = np.concatenate([np.full(k, np.nan), low[:n - k]])
            lo = np.fmin(lo, np.nan_to_num(shifted, nan=np.inf)) if k else low.copy()
        out[f"pos_{w}"] = (c - lo) / np.maximum(hi - lo, 1e-12)
        out[f"__hi_{w}"] = hi
        out[f"__lo_{w}"] = lo
        up = (lr > 0).astype(float)
        m2, _ = _rolling(up, w)
        out[f"up_share_{w}"] = m2
    out["vol_stretch"] = out["vol_20"] / np.maximum(out["vol_100"], 1e-12)
    out["vol_stretch_fast"] = out["vol_5"] / np.maximum(out["vol_20"], 1e-12)
    rng = (h - low) / c * 1e4
    out["range_bps"] = rng
    mr, _ = _rolling(rng, 20)
    out["range_stretch"] = rng / np.maximum(mr, 1e-12)
    gap = np.zeros(n)
    gap[1:] = (o[1:] - c[:-1]) / c[:-1] * 1e4
    out["gap_vol"] = gap / np.maximum(out["vol_20"], 1e-12)
    body_hi = np.maximum(o, c)
    body_lo = np.minimum(o, c)
    out["wick_above_vol"] = (h - body_hi) / c * 1e4 / np.maximum(out["vol_20"], 1e-12)
    out["wick_below_vol"] = (body_lo - low) / c * 1e4 / np.maximum(out["vol_20"], 1e-12)
    sign = np.sign(lr)
    run = np.zeros(n)
    for i in range(1, n):
        run[i] = run[i - 1] + sign[i] if sign[i] == sign[i - 1] and sign[i] != 0 else sign[i]
    out["run_len"] = run
    out["absret_vol"] = np.abs(lr) * 1e4 / np.maximum(out["vol_20"], 1e-12)
    near = np.zeros(n)
    tol = out["vol_20"] / 1e4 * c * 0.25
    for k in range(1, 51):
        shifted_h = np.concatenate([np.full(k, np.inf), h[:n - k]])
        shifted_l = np.concatenate([np.full(k, -np.inf), low[:n - k]])
        near += ((shifted_l - tol <= c) & (c <= shifted_h + tol)).astype(float)
    out["touches_50"] = near
    unit_price = np.maximum(out["vol_20"] / 1e4 * c, 1e-12)
    out["dist_high_50"] = (out["__hi_50"] - c) / unit_price
    out["dist_low_50"] = (c - out["__lo_50"]) / unit_price
    idx = np.arange(n)
    out["hour_n"] = (idx // 60) % 24
    out["minute_n"] = idx % 60
    for w in WINDOWS:
        del out[f"__hi_{w}"], out[f"__lo_{w}"]
    return out


# -------------------------------------------------------------- the closes --
def one_family(args):
    """Replay non-overlapping trades on fresh bars, recording entry features."""
    name, kind, sigma, tick_s, n_trades, seed, priced, live_rr, live_rv = args
    rng = np.random.default_rng([seed, abs(hash(name)) % (2 ** 31)])
    rows_f: list[list[float]] = []
    out_r, out_exit, out_strat = [], [], []
    made = 0
    t0 = time.time()
    while made < n_trades:
        bars_d = N.bars_for(name, kind, sigma, tick_s, 200_000, rng)
        n = bars_d["n"]
        if n < 400:
            break
        cl = bars_d["close"]
        feats = block_features(bars_d)
        bars = list(zip(bars_d["ts"].tolist(), bars_d["open"].tolist(),
                        bars_d["high"].tolist(), bars_d["low"].tolist(), cl.tolist(),
                        strict=True))
        lr = np.zeros(n)
        lr[1:] = np.diff(cl) / cl[:-1]
        _, sd20 = _rolling(lr, 20)
        unit_all = sd20 * cl
        i = 120
        while i < n - 300 and made < n_trades:
            si = int(rng.integers(0, len(N.STRATEGY_NAMES)))
            sname = N.STRATEGY_NAMES[si]
            shape = N.SHAPES[sname]
            u = unit_all[i] * N.UNIT_MULT
            if u <= 0:
                i += 25
                continue
            rv = float(live_rv[rng.integers(0, live_rv.size)])
            rr = float(live_rr[rng.integers(0, live_rr.size)])
            push = rr * rv * shape["stop"] / shape["target"]
            risk_price = rv * shape["stop"] * u
            if risk_price <= 0 or push <= 0:
                i += 25
                continue
            cost = SPREAD_BPS / 1e4 * cl[i] if priced else COST_R * risk_price
            trade = {"up": bool(rng.integers(0, 2)), "unit": u, "push_vol": push,
                     "level": cl[i], "risk_vol": rv, "context": {}}
            policy = {"stop_mult": shape["stop"], "target_mult": shape["target"],
                      "trail_vol": shape["trail"], "protect_r": shape["protect"],
                      "trail_after_r": shape["protect"]}
            hold_bars = max(1, int(round(shape["hold"] * N.HOLD_MULT)))
            got = walk(bars, i + 1, trade, cost=cost, hold=hold_bars, policy=policy)
            if got is None:
                i += 25
                continue
            r, kind_exit = got
            row = {k: float(feats[k][i]) for k in BAR_FEATS}
            up = trade["up"]
            row["wick_ahead"] = row["wick_above_vol"] if up else row["wick_below_vol"]
            row["wick_behind"] = row["wick_below_vol"] if up else row["wick_above_vol"]
            row["reward_to_risk"] = rr
            row["risk_vol"] = rv
            row["stop_vol"] = risk_price / cl[i] * 1e4
            row["target_vol"] = push * shape["target"] * u / cl[i] * 1e4
            row["expected_hold"] = float(hold_bars)
            row["spread_over_risk"] = cost / risk_price
            rows_f.append([row[k] for k in FEAT_NAMES])
            out_r.append(r)
            out_exit.append({"stop": 0, "target": 1, "hold": 2}[kind_exit])
            out_strat.append(si)
            made += 1
            i += hold_bars + 25
        if time.time() - t0 > 3600:
            break
    return (name, np.array(rows_f, dtype=np.float32), np.array(out_r),
            np.array(out_exit, dtype=np.int8), np.array(out_strat, dtype=np.int8))


def build_pool(n_closes: int, priced: bool, seed: int) -> dict:
    rr, rv, _rm, src = N.live_draws()
    fams = list(N.FAMILIES)
    shards = max(1, WORKERS // len(fams)) if WORKERS > len(fams) else 1
    per = max(200, n_closes // (len(fams) * shards) + 1)
    jobs = [(nm, k, sg, t, per, seed + 1000 * j + 7 * sh, priced, rr, rv)
            for j, (nm, k, sg, t) in enumerate(fams) for sh in range(shards)]
    print(f"  {len(fams)} families x {shards} shards x {per} closes,"
          f" {'priced' if priced else 'flat'} cost, geometry from {src}", flush=True)
    with CTX.Pool(WORKERS) as pool:
        got = pool.map(one_family, jobs)
    names: list[str] = []
    feed_idx = []
    for nm, f, _r, _e, _s in got:
        if nm not in names:
            names.append(nm)
        feed_idx.append(np.full(f.shape[0], names.index(nm), dtype=np.int16))
    return {"f": np.concatenate([g[1] for g in got]),
            "r": np.concatenate([g[2] for g in got]),
            "exit": np.concatenate([g[3] for g in got]),
            "strategy": np.concatenate([g[4] for g in got]),
            "feed": np.concatenate(feed_idx), "feed_names": names}


# ------------------------------------------------------------ the scan, run --
def rows_for(idx: np.ndarray, pool: dict, target_r: np.ndarray | None = None):
    """`winning.py`'s row shape: a target, a label set, and a feature dict."""
    f = pool["f"][idx]
    r = pool["r"][idx] if target_r is None else target_r
    ex = pool["exit"][idx]
    strat = pool["strategy"][idx]
    feed = pool["feed"][idx]
    names = pool["feed_names"]
    out = []
    for k in range(idx.size):
        out.append({
            "R": float(r[k]),
            "won": 1.0 if r[k] > 0 else 0.0,
            "stopped": 1.0 if ex[k] == 0 else 0.0,
            "strategy": N.STRATEGY_NAMES[int(strat[k])],
            "interval": "1m",
            "feed": names[int(feed[k])],
            "f": {nm: float(v) for nm, v in zip(FEAT_NAMES, f[k], strict=True)},
        })
    return out


def naive_t(rows: list[dict], target: str, split: int, z: dict) -> float:
    """The t statistic a reader computes by eye: best tercile against worst.

    No control, no correction, no verify half - the comparison the top row of a
    scan invites. It is here to measure what `winning.md`'s permutation control
    is actually buying.
    """
    vals: dict[str, list[float]] = {"low": [], "mid": [], "high": []}
    for r in rows[:split]:
        got = r["f"].get(z["feat"])
        if got is not None:
            vals[W.bucket_of(got, z["low"], z["high"])].append(r[target])
    a, b = np.array(vals[z["best"]]), np.array(vals[z["worst"]])
    if a.size < 2 or b.size < 2:
        return 0.0
    den = math.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size)
    return abs(float(a.mean() - b.mean()) / den) if den > 0 else 0.0


def scan_once(rows: list[dict], target: str, seed: int):
    """`winning.scan` and `winning.control`, unchanged, on one book."""
    split = int(len(rows) * W.SPLIT)
    feats = sorted(FEAT_NAMES)
    W.SEED = seed
    W.PERMUTATIONS = PERMUTATIONS
    found = W.scan(rows, target, split, feats)
    if not found:
        return None
    gaps, survivors = W.control(rows, target, split, feats)
    best = found[0]
    ceiling = W.quantile(gaps, 0.95)
    held = [z for z in found if z["verify_gap"] is not None and z["verify_gap"] > 0]
    clears = [z for z in found if z["gap"] > ceiling]
    gate = [z for z in clears if z["verify_gap"] is not None and z["verify_gap"] > 0]
    ts = [naive_t(rows, target, split, z) for z in found]
    return {"max_gap": best["gap"], "best": best["feat"], "n_feats": len(found),
            "ceiling": ceiling, "control_median": W.quantile(gaps, 0.5),
            "clears": [z["feat"] for z in clears], "gate": [z["feat"] for z in gate],
            "held": len(held), "survivors_p95": W.quantile(survivors, 0.95),
            "survivors_median": W.quantile(survivors, 0.5),
            "naive_any": sum(1 for t in ts if t > 1.96), "naive_top": ts[0] if ts else 0.0}


def _scan_job(args):
    offset, k, seed, targets, lift = args
    pool = _W["pool"]
    order = np.asarray(_W["order"])
    out = []
    for b in range(k):
        idx = order[(offset + b) * BOOK_N: (offset + b + 1) * BOOK_N]
        base = None
        if lift:
            # A known edge, carried by one feature: the top tercile of
            # `mom_20` is paid `lift` of risk more than the bottom. Injected on
            # R only, and the feature is one the scan already sees.
            f = pool["f"][idx][:, FEAT_NAMES.index("mom_20")]
            base = pool["r"][idx] + lift * (f > np.median(f)).astype(float)
        rows = rows_for(idx, pool, base)
        for t in targets:
            got = scan_once(rows, t, seed + 13 * b)
            if got:
                out.append((t, got))
    return out


def run_books(books: int, targets, lift: float = 0.0, seed: int = SEED):
    total = int(np.asarray(_W["order"]).size) // BOOK_N
    take = min(books, total)
    per = max(1, math.ceil(take / WORKERS))
    jobs = []
    at = 0
    while at < take:
        k = min(per, take - at)
        jobs.append((at, k, seed + 7717 * at, tuple(targets), lift))
        at += k
    with CTX.Pool(WORKERS) as pool:
        got = pool.map(_scan_job, jobs)
    acc: dict[str, list[dict]] = {t: [] for t in targets}
    for chunk in got:
        for t, row in chunk:
            acc[t].append(row)
    return acc


def report(label: str, rows: list[dict], real=None) -> dict:
    n = len(rows)
    if not n:
        print(f"  {label}: no books scanned")
        return {}
    clears = float(np.mean([bool(z["clears"]) for z in rows]))
    gate = float(np.mean([bool(z["gate"]) for z in rows]))
    gaps = np.array([z["max_gap"] for z in rows])
    ceil = np.array([z["ceiling"] for z in rows])
    held = np.array([z["held"] for z in rows], dtype=float)
    print(f"  {label:26} books {n:5d}   biggest gap clears its own control "
          f"{fmt_rate(clears, n)}   full gate {fmt_rate(gate, n)}")
    print(f"  {'':26} biggest gap: median {np.median(gaps):.3f}, p95 "
          f"{np.percentile(gaps, 95):.3f}, max {gaps.max():.3f};  control p95: median "
          f"{np.median(ceil):.3f}")
    print(f"  {'':26} features holding their sign into verify: median {np.median(held):.0f}"
          f", p95 {np.percentile(held, 95):.0f} of {int(np.median([z['n_feats'] for z in rows]))}")
    if real is not None:
        print(f"  {'':26} winning.md read {real} on the live book")
    return {"clears": clears, "gate": gate, "n": n, "gaps": gaps}


# -------------------------------------------------------------- section one --
def _toy_job(args):
    seed, trials = args
    rng = np.random.default_rng(seed)
    names = [f"x{i}" for i in range(43)]
    fired = 0
    for t in range(trials):
        f = rng.standard_normal((BOOK_N, 43))
        y = rng.standard_normal(BOOK_N)
        rows = [{"R": float(y[k]), "f": {nm: float(v) for nm, v in zip(names, f[k],
                                                                      strict=True)}}
                for k in range(BOOK_N)]
        W.SEED = seed + t
        W.PERMUTATIONS = PERMUTATIONS
        found = W.scan(rows, "R", int(BOOK_N * W.SPLIT), names)
        gaps, _ = W.control(rows, "R", int(BOOK_N * W.SPLIT), names)
        if found and found[0]["gap"] > W.quantile(gaps, 0.95):
            fired += 1
    return trials, fired


def toy_control(trials: int = TOY_TRIALS) -> list[dict]:
    """43 Gaussian features against an independent Gaussian target."""
    print("\n[1] THE INSTRUMENT: THE SCAN AGAINST DATA WITH NOTHING IN IT\n")
    per = max(1, math.ceil(trials / WORKERS))
    jobs = [(SEED + 101 * j, min(per, trials - j * per))
            for j in range(math.ceil(trials / per))]
    with CTX.Pool(WORKERS) as pool:
        got = pool.map(_toy_job, jobs)
    trials = sum(g[0] for g in got)
    fired = sum(g[1] for g in got)
    rate = fired / trials
    print(f"  Gaussian features, Gaussian target, n={BOOK_N}, {trials} trials:"
          f"  the scan's own control is cleared {fmt_rate(rate, trials)}   nominal 5.00%")
    led = [{"test": "the permutation control rejects at 5% on Gaussian toy data",
            "value": rate - 0.05, "fired": abs(rate - 0.05) > 3 * se_rate(0.05, trials)}]
    if G.exactly_null(rate, 0.05, places=4):
        led.append({"test": "the toy rate is not exactly 0.0500", "value": rate - 0.05,
                    "fired": True})
    return led


def check_pool(pool: dict, priced: bool) -> list[dict]:
    r = pool["r"]
    se = r.std(ddof=1) / math.sqrt(r.size)
    charged = -COST_R if not priced else None
    print(f"\n  pool: {r.size} closes, mean R {r.mean():+.5f} +-{se:.5f}, "
          f"sd {r.std(ddof=1):.4f}, stops {(pool['exit'] == 0).mean() * 100:.1f}%")
    led = []
    if charged is not None:
        z = (r.mean() - charged) / se
        print(f"  the theorem says {charged:+.5f}; z = {z:+.2f}")
        led.append({"test": "flat-arm pool mean R equals minus the cost within 3 SE",
                    "value": z, "fired": abs(z) > 3})
    else:
        # On the priced arm the theorem says E[R_i] = -spread_i / risk_i exactly,
        # so the pool's mean R is minus the mean of the feature itself.
        sor = pool["f"][:, FEAT_NAMES.index("spread_over_risk")].astype(np.float64)
        z = (r.mean() + sor.mean()) / se
        print(f"  the theorem says {-sor.mean():+.5f} - minus the mean of"
              f" spread_over_risk itself; z = {z:+.2f}")
        led.append({"test": "priced-arm pool mean R equals minus mean spread_over_risk",
                    "value": z, "fired": abs(z) > 3})
    return led


def main() -> None:
    t0 = time.time()
    print("CALIBRATING THE FEATURE SCAN AGAINST A WORLD WITH NO EDGE IN IT")
    print(f"machine: {G.machine()}   books {BOOKS} x {BOOK_N} closes   "
          f"{PERMUTATIONS} permutations   seed {SEED}")
    led = toy_control()

    print("\n[2] THE FLAT ARM - cost proportional to risk, so E[R] is one constant\n")
    pool = build_pool(CLOSES, priced=False, seed=SEED)
    led += check_pool(pool, priced=False)
    _W["pool"] = pool
    _W["order"] = np.random.default_rng(SEED + 5).permutation(pool["r"].size)
    got = run_books(BOOKS, ("R", "stopped", "won"))
    print()
    flat = {}
    for target, real in (("R", "0.433 for break_probability, clearing nothing"),
                         ("stopped", "0.358 for spread_over_risk, which cleared"),
                         ("won", "0.302 for confluence_n, clearing nothing")):
        flat[target] = report(f"target {target}", got[target], real)
        print()
    led.append({"test": "the permutation control rejects at 5% on null books, target R",
                "value": flat["R"]["clears"] - 0.05,
                "fired": abs(flat["R"]["clears"] - 0.05) > 3 * se_rate(0.05, flat["R"]["n"])})

    print("\n[3] WHAT THE SAME BOOKS LOOK LIKE WITHOUT THE CONTROL\n")
    rows = got["R"]
    n = len(rows)
    naive = float(np.mean([z["naive_any"] > 0 for z in rows]))
    top = float(np.mean([z["naive_top"] > 1.96 for z in rows]))
    howmany = float(np.mean([z["naive_any"] for z in rows]))
    big = float(np.mean([z["max_gap"] >= 0.433 for z in rows]))
    print(f"  at least one feature separates its terciles at an uncorrected p<0.05:"
          f"  {fmt_rate(naive, n)} of {n} books")
    print(f"  the *biggest* feature does:                                        "
          f"  {fmt_rate(top, n)}")
    print(f"  and a null book carries {howmany:.1f} such features on average, of"
          f" {int(np.median([z['n_feats'] for z in rows]))} scanned.")
    print(f"  the biggest gap reaches winning.md's live 0.433 in {fmt_rate(big, n)}"
          f" of books.")

    print("\n[4] POWER - an edge the scan should find\n")
    print("  half the book, chosen by a feature the scan already sees, is paid `lift`")
    print("  more of its risk. How often does the scan report it?\n")
    for lift in (0.05, 0.10, 0.20, 0.40):
        acc = run_books(max(60, BOOKS // 4), ("R",), lift=lift, seed=SEED + 99)
        rows = acc["R"]
        k = len(rows)
        clears = float(np.mean([bool(z["clears"]) for z in rows]))
        right = float(np.mean([("mom_20" in z["clears"]) for z in rows]))
        print(f"    lift {lift * 100:4.0f}% of risk   scan clears its control "
              f"{fmt_rate(clears, k)}   and names mom_20 {fmt_rate(right, k)}")
        if lift == 0.40:
            led.append({"test": "the scan finds a 40%-of-risk edge at better than 80%",
                        "value": clears - 0.80, "fired": clears < 0.80})

    print("\n[5] THE PRICED ARM - the spread is a price, so spread_over_risk varies\n")
    pool2 = build_pool(max(CLOSES // 3, BOOK_N * 200), priced=True, seed=SEED + 11)
    led += check_pool(pool2, priced=True)
    sor = pool2["f"][:, FEAT_NAMES.index("spread_over_risk")]
    print(f"  spread_over_risk: median {np.median(sor):.4f}, "
          f"p95 {np.percentile(sor, 95):.4f} (live: the gate sits at 0.16)")
    _W["pool"] = pool2
    _W["order"] = np.random.default_rng(SEED + 6).permutation(pool2["r"].size)
    got2 = run_books(min(BOOKS, 300), ("R", "stopped"))
    print()
    for target in ("R", "stopped"):
        rows = got2[target]
        k = len(rows)
        named = float(np.mean([("spread_over_risk" in z["clears"]) for z in rows]))
        report(f"priced, target {target}", rows)
        print(f"  {'':26} and the feature it names is spread_over_risk in"
              f" {fmt_rate(named, k)} of books")
        print()

    print("\n[LEDGER] the conditions written down before the numbers\n")
    for row in led:
        print(f"  {'FIRED ' if row['fired'] else 'held  '} {row['test']:64} "
              f"{row['value']:+.4f}")
    print(f"\n  {sum(1 for x in led if x['fired'])} of {len(led)} fired"
          f"   ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
