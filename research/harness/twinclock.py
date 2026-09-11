"""Do the twins share a volatility clock, and is the stated law even true?

Two things `twinpath.py` cannot answer from one day of ticks.

**The clock.** Two series can be driven by completely independent innovations
and still share a *variance* process - one generator, one stochastic volatility
state, two draws from it. That leaks nothing into the correlation of returns
and everything into the correlation of realised volatility. It is the weakest
of the shared-driver hypotheses and by some distance the most likely, because
it is what a single scheduler feeding two streams would look like.

**The law.** `Volatility 75 Index` is sold as a geometric Brownian motion with
75% annualised volatility. That is a statement about a generator, and a fact
about a generator is worth more than a pattern in a real market, because there
is nobody on the other side to arbitrage it away. So: measure the annualised
volatility, and then test the rest of the claim - that log returns are iid
normal. Autocorrelation at every lag the data can see, Ljung-Box on returns and
on squared returns, excess kurtosis, a tail index, and variance ratios.

60 days of one-minute bars, 86,411 per feed, which is 60x the tick table's
reach. Split in half by time, because a result that only holds in one half is
not a result.

Controls, as everywhere on this page: a twin is read against the mismatched
volatility pairs and against strangers from other generator families, all
measured with the identical statistic over the identical lag set.
"""

from __future__ import annotations

import math
import os
import sqlite3
import time
from collections import Counter
from itertools import combinations

import numpy as np
from scipy import signal, stats

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
DAYS = float(os.environ.get("DAYS", "60"))
MAXLAG = int(os.environ.get("MAXLAG", "10"))     # minutes each way
SEED = int(os.environ.get("SEED", "20260911"))

PARAMS = ("10", "25", "50", "75", "100")
SLOW = [f"volatility_{p}_index" for p in PARAMS]
FAST = [f"volatility_{p}_1s_index" for p in PARAMS]
EXTRA = ["volatility_150_1s_index", "volatility_250_1s_index"]
STRANGERS = ["boom_500_index", "crash_500_index", "jump_25_index", "step_index"]
FEEDS = SLOW + FAST + EXTRA + STRANGERS

MINUTES_PER_YEAR = 365.0 * 24.0 * 60.0
COMPARISONS = Counter()


def bump(name: str, n: int = 1) -> None:
    COMPARISONS[name] += n


def kind(a: str, b: str) -> str:
    va, vb = a.startswith("volatility"), b.startswith("volatility")
    if not (va and vb):
        return "stranger"
    pa = a.replace("_1s_", "_").replace("volatility_", "").replace("_index", "")
    pb = b.replace("_1s_", "_").replace("volatility_", "").replace("_index", "")
    if pa == pb and ("_1s_" in a) != ("_1s_" in b):
        return "twin"
    return "mismatch"


def load(conn, feed: str, since_ms: int) -> tuple[np.ndarray, np.ndarray]:
    rows = conn.execute(
        "SELECT ts, close FROM bars WHERE feed=? AND interval='1m' AND ts>=? "
        "ORDER BY ts ASC", (feed, since_ms),
    ).fetchall()
    if not rows:
        return np.empty(0, dtype=np.int64), np.empty(0)
    a = np.asarray(rows, dtype=np.float64)
    ts, close = a[:, 0].astype(np.int64), a[:, 1]
    ok = np.isfinite(close) & (close > 0)
    return ts[ok], close[ok]


def align(series: dict) -> tuple[np.ndarray, dict]:
    """One common minute grid, so every pair is the same sample."""
    common = None
    for ts, _c in series.values():
        s = set(ts.tolist())
        common = s if common is None else (common & s)
    grid = np.array(sorted(common), dtype=np.int64)
    out = {}
    for feed, (ts, close) in series.items():
        idx = np.searchsorted(ts, grid)
        out[feed] = close[idx]
    return grid, out


def xcorr(x, y, maxlag):
    x = x - x.mean()
    y = y - y.mean()
    nx, ny = float(np.sqrt((x * x).sum())), float(np.sqrt((y * y).sum()))
    if nx <= 0 or ny <= 0:
        return np.full(2 * maxlag + 1, np.nan)
    full = signal.correlate(y, x, mode="full", method="fft")
    z = len(x) - 1
    return full[z - maxlag: z + maxlag + 1] / (nx * ny)


def peak(c, maxlag):
    k = int(np.nanargmax(np.abs(c)))
    return float(c[k]), k - maxlag, float(c[maxlag])


def acf(r: np.ndarray, lags) -> list[float]:
    r = r - r.mean()
    den = float((r * r).sum())
    return [float((r[:-L] * r[L:]).sum()) / den if den > 0 else float("nan")
            for L in lags]


def ljung_box(r: np.ndarray, h: int) -> tuple[float, float]:
    n = len(r)
    a = acf(r, range(1, h + 1))
    q = n * (n + 2) * sum((v * v) / (n - k) for k, v in enumerate(a, start=1))
    return q, float(stats.chi2.sf(q, h))


def hill(x: np.ndarray, frac: float = 0.005) -> float:
    x = np.sort(np.abs(x))[::-1]
    k = max(30, int(len(x) * frac))
    top, thr = x[:k], x[k]
    if thr <= 0:
        return float("nan")
    return float(1.0 / np.mean(np.log(top / thr)))


def variance_ratio(r: np.ndarray, q: int) -> tuple[float, float]:
    n = len(r)
    mu = r.mean()
    v1 = float(((r - mu) ** 2).sum()) / (n - 1)
    agg = np.convolve(r, np.ones(q), mode="valid")
    vq = float(((agg - q * mu) ** 2).sum()) / (n - q + 1)
    vr = vq / (q * v1) if v1 > 0 else float("nan")
    se = math.sqrt(2.0 * (2 * q - 1) * (q - 1) / (3.0 * q * n))
    return vr, (vr - 1.0) / se if se > 0 else float("nan")


# ------------------------------------------------------------------ tests


def section_returns(rets: dict, label: str) -> None:
    print(f"\n=== 1. one-minute return cross-correlation, {label}, "
          f"lags {-MAXLAG}..{MAXLAG}m ===")
    rows = []
    for a, b in combinations([f for f in FEEDS if f in rets], 2):
        c = xcorr(rets[a], rets[b], MAXLAG)
        bump("bar_xcorr", 2 * MAXLAG + 1)
        best, lag, at0 = peak(c, MAXLAG)
        rows.append((kind(a, b), a, b, at0, best, lag))
    summarise(rows, f"1m returns, {label}", len(next(iter(rets.values()))))


def section_clock(rets: dict, label: str) -> None:
    """The volatility clock. Realised variance per 5m and per 15m bucket,
    correlated in logs across pairs. Spearman as well as Pearson, because a
    shared clock need not be linear in logs."""
    for bucket in (5, 15):
        lv = {}
        for feed, r in rets.items():
            m = (len(r) // bucket) * bucket
            rv = (r[:m].reshape(-1, bucket) ** 2).sum(axis=1)
            rv = np.maximum(rv, 1e-300)
            lv[feed] = np.log(rv)
        n = len(next(iter(lv.values())))
        rows = []
        for a, b in combinations([f for f in FEEDS if f in lv], 2):
            c = xcorr(lv[a], lv[b], 3)
            bump("clock_xcorr", 7)
            best, lag, at0 = peak(c, 3)
            sp = float(stats.spearmanr(lv[a], lv[b]).statistic)
            bump("clock_spearman", 1)
            rows.append((kind(a, b), a, b, at0, best, lag, sp))
        print(f"\n=== 2. volatility clock, {bucket}m realised variance, "
              f"{label} ({n} buckets) ===")
        summarise([r[:6] for r in rows], f"log RV {bucket}m, {label}", n)
        ctrl = [abs(r[6]) for r in rows if r[0] != "twin"]
        mu, sd = float(np.mean(ctrl)), float(np.std(ctrl))
        print(f"  spearman: control mean |rho| {mu:.4f} sd {sd:.4f} "
              f"max {max(ctrl):.4f}")
        for k, a, b, _a0, _bs, _lg, sp in rows:
            if k == "twin":
                zz = (abs(sp) - mu) / sd if sd > 0 else float("nan")
                print(f"  {a + ' / ' + b:>46s} rho {sp:+.4f}  z {zz:+.2f}")


def summarise(rows: list, label: str, n: int) -> None:
    print(f"  --- {label}: |corr| at the best of {2*MAXLAG+1 if 'returns' in label else 7} lags, "
          f"n={n}, noise floor 1/sqrt(n)={1/math.sqrt(n):.4f} ---")
    order = {"twin": 0, "mismatch": 1, "stranger": 2}
    for k in sorted({r[0] for r in rows}, key=lambda k: order.get(k, 9)):
        got = [r for r in rows if r[0] == k]
        mags = [abs(r[4]) for r in got]
        w = max(got, key=lambda r: abs(r[4]))
        print(f"  {k:>9s} {len(got):5d} pairs  mean {np.mean(mags):.4f}  "
              f"max {max(mags):.4f}   {w[1]} / {w[2]} = {w[4]:+.4f} @ {w[5]:+d}")
    ctrl = [abs(r[4]) for r in rows if r[0] != "twin"]
    mu, sd = float(np.mean(ctrl)), float(np.std(ctrl))
    print(f"  control max|r| mean {mu:.4f} sd {sd:.4f} max {max(ctrl):.4f}")
    for k, a, b, at0, best, lag in rows:
        if k != "twin":
            continue
        z = (abs(best) - mu) / sd if sd > 0 else float("nan")
        flag = "  <- exceeds every control" if abs(best) > max(ctrl) else ""
        print(f"  {a + ' / ' + b:>46s} lag0 {at0:+.4f} best {best:+.4f} "
              f"@ {lag:+d} z {z:+.2f}{flag}")


def section_law(rets: dict, grid: np.ndarray) -> None:
    print("\n=== 3. is the stated law true? annualised volatility ===")
    n_all = len(next(iter(rets.values())))
    se = 1.0 / math.sqrt(2 * n_all)
    print(f"  annualised at 365*24*60 minutes, 24/7. One standard error on the"
          f" ratio is {se:.4f}, so anything inside 1.000 +/- {2*se:.3f} is the"
          f" stated law.")
    print(f"  {'feed':26s} {'stated':>7s} {'measured':>9s} {'ratio':>7s} "
          f"{'(ratio-1)/se':>13s} {'half A':>8s} {'half B':>8s}")
    half = len(grid) // 2
    for feed in FEEDS:
        if feed not in rets:
            continue
        r = rets[feed]
        ann = float(r.std(ddof=1)) * math.sqrt(MINUTES_PER_YEAR)
        a = float(r[:half].std(ddof=1)) * math.sqrt(MINUTES_PER_YEAR)
        b = float(r[half:].std(ddof=1)) * math.sqrt(MINUTES_PER_YEAR)
        bump("annual_vol", 1)
        stated, ratio, zcell = "", "", ""
        if feed.startswith("volatility"):
            p = float(feed.replace("_1s_", "_").replace("volatility_", "")
                      .replace("_index", ""))
            rr = ann / (p / 100.0)
            stated = f"{p:.0f}%"
            ratio = f"{rr:7.4f}"
            zcell = f"{(rr - 1.0) / se:+13.2f}"
        print(f"  {feed:26s} {stated:>7s} {100*ann:8.2f}% {ratio:>7s} "
              f"{zcell:>13s} {100*a:7.2f}% {100*b:7.2f}%")

    print("\n=== 4. are one-minute log returns iid normal? ===")
    LAGS = (1, 2, 3, 5, 10, 30, 60)
    n = len(next(iter(rets.values())))
    print(f"  n={n} per feed, 2/sqrt(n) = {2/math.sqrt(n):.4f}")
    print(f"  {'feed':26s} " + "".join(f"{'r%d' % L:>8s}" for L in LAGS)
          + f"{'LB(30)p':>10s}{'kurt':>8s}{'JB p':>9s}{'hill':>7s}")
    for feed in FEEDS:
        if feed not in rets:
            continue
        r = rets[feed]
        a = acf(r, LAGS)
        bump("bar_acf", len(LAGS))
        q, p = ljung_box(r, 30)
        bump("ljung_box", 1)
        k = float(stats.kurtosis(r))
        jb = float(stats.jarque_bera(r).pvalue)
        bump("normality", 2)
        h = hill(r)
        bump("hill", 1)
        print(f"  {feed:26s} " + "".join(f"{v:+8.4f}" for v in a)
              + f"{p:10.3g}{k:+8.3f}{jb:9.2g}{h:7.2f}")

    print("\n=== 5. volatility clustering: |r| autocorrelation and Ljung-Box "
          "on squares ===")
    print(f"  {'feed':26s} " + "".join(f"{'|r|%d' % L:>9s}" for L in (1, 5, 30))
          + f"{'LB2(30)p':>11s}{'RV cv':>8s}{'shuf cv':>9s}{'chi2 cv':>9s}")
    rng = np.random.default_rng(SEED)
    for feed in FEEDS:
        if feed not in rets:
            continue
        r = rets[feed]
        aa = acf(np.abs(r), (1, 5, 30))
        bump("abs_acf", 3)
        q2, p2 = ljung_box(r * r, 30)
        bump("ljung_box", 1)
        m = (len(r) // 5) * 5
        rv = (r[:m].reshape(-1, 5) ** 2).sum(axis=1)
        cv = float(rv.std() / rv.mean()) if rv.mean() > 0 else float("nan")
        sh = r.copy()
        rng.shuffle(sh)
        rvs = (sh[:m].reshape(-1, 5) ** 2).sum(axis=1)
        cvs = float(rvs.std() / rvs.mean()) if rvs.mean() > 0 else float("nan")
        bump("rv_dispersion", 1)
        print(f"  {feed:26s} " + "".join(f"{v:+9.4f}" for v in aa)
              + f"{p2:11.3g}{cv:8.3f}{cvs:9.3f}{math.sqrt(2/5):9.3f}")

    print("\n=== 6. variance ratios (1 = random walk) ===")
    QS = (2, 5, 15, 60)
    print(f"  {'feed':26s} " + "".join(f"{'VR%d' % q:>9s}{'z':>8s}" for q in QS))
    for feed in FEEDS:
        if feed not in rets:
            continue
        cells = ""
        for q in QS:
            vr, z = variance_ratio(rets[feed], q)
            bump("variance_ratio", 1)
            cells += f"{vr:9.4f}{z:+8.2f}"
        print(f"  {feed:26s}" + cells)


def run() -> None:
    t_start = time.time()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=900.0)
    since = int((time.time() - DAYS * 86400) * 1000)
    series = {}
    for feed in FEEDS:
        ts, close = load(conn, feed, since)
        if len(ts) < 10_000:
            print(f"  SKIP {feed}: {len(ts)} bars")
            continue
        series[feed] = (ts, close)
    grid, closes = align(series)
    print(f"loaded {len(series)} feeds, {len(grid)} common 1m bars "
          f"({(grid[-1]-grid[0])/86400000:.1f} days)")

    rets = {}
    for feed, c in closes.items():
        r = np.diff(np.log(c))
        rets[feed] = r
        if r.std() <= 0 or np.mean(r != 0) < 0.5:
            print(f"  DEAD COLUMN {feed}: sd {r.std():.3g} nonzero "
                  f"{np.mean(r != 0):.3f}")
    gridr = grid[1:]

    section_returns(rets, "all 60 days")
    section_clock(rets, "all 60 days")

    half = len(gridr) // 2
    for name, sl in (("first half", slice(0, half)), ("second half", slice(half, None))):
        sub = {f: r[sl] for f, r in rets.items()}
        section_returns(sub, name)
        section_clock(sub, name)

    section_law(rets, gridr)

    print("\n=== comparisons made ===")
    for k, v in sorted(COMPARISONS.items()):
        print(f"  {k:18s} {v:9d}")
    print(f"  {'TOTAL':18s} {sum(COMPARISONS.values()):9d}")
    print(f"\nelapsed {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    run()
