"""Deriv variants of the production tools: an exact-law envelope, and an exact spike hazard.

Deriv is a real market here (memory: deriv-is-a-real-market). It publishes each index's generator
law, and `generators.md` found most of it true. Every exact-law variant below is still a *model
tested against the feed*, never assumed. Walks we generate from each law are the control: they show
what "the feed matches its law" reads like.

## Part 1: the envelope (PART=envelope FAMILY=vol|jump|boomcrash|other)

P10 / P50 / P90 of the N-bar log move, N = 5, 20, 50, at 3m, 15m and 1h (seqlab bars). Methods:

  prod       production's own `structures.vol.envelope.Envelope` (the empirical history corrected
             by AgACI, with the single-corrector handover), fed each bar's close and the
             production unit (`Ranges.ewma_tr_bps`), exactly as the engine feeds it. It runs from
             the series' start, so it is warm by the scored block.
  prod cold  the same, started empty at the scored block: what a newly followed index quotes over
             its first 1,000 bars
  law        the published law, where one is published:
             Volatility  GBM at the named sigma, Ito drift (`projection.py`, measured `ito`)
             Jump        Gaussian at the named sigma x 1.32 (`stated.JUMP_MULTIPLE`)
             Step        a fair +-0.1 coin at one tick a second, in price, so read in log per bar
             Boom/Crash  none published beyond the spike rate; see `iid`
  iid        the N-fold convolution of the bar's own one-bar log return, fitted on the first 60%
             (Monte Carlo). If the generator is memoryless, as published, this is exact at the bar
             resolution for every family - and a fitted one-bar law, not a fitted N-bar one
  hybrid     the law (or iid where none is published) with its levels corrected online by AgACI,
             started empty at the scored block

Scored on the last 40% by time: coverage, pinball and width (log-return bps), P90 over twenty
slices of time (worst), and P90 by volatility third. The first 1,000 scored bars are reported on
their own for the cold starts. Realised sigma over the named sigma, and one-bar kurtosis, say
whether the feed matches the law.

## Part 2: the spike hazard (PART=hazard)

Boom and Crash spikes, and Jump jumps, on 1m bars (research.db, 60 days) and seqlab 3m (100 days).
A spike bar is Boom: high - open, Crash: open - low, Jump: |close - open|, above 10x the median
absolute bar move (5x for Jump, whose jumps a bar's diffusion partly hides; 5x/10x/20x counts are
reported, and should not move for Boom and Crash). For each bar,
P(a spike within the next N bars), N = 1, 5, 20:

  published  1 - exp(-rate x N x bar minutes), rate from the name: Boom/Crash N one per N ticks at
             about one tick a second, Jump three an hour
  constant   the same form at the training period's own rate
  model      gradient boosting on time since the last spike, the gap before it, spikes in the last
             50 and 200 bars, the grind's volatility against its norm, the last 5 bars' grind,
             and the hour - trained on the first 60%

Memorylessness: the gap's CV, and the next-bar hazard by time since the last spike, which is flat
if the feed is memoryless. Pre-registered: a model AUC above 0.55 with its interval above 0.5, in
both halves, is evidence the feed departs from its published memorylessness.

Run on the lab:
  PART=envelope FAMILY=vol SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/derivvariants.py
  PART=hazard RESEARCH_DB=$HOME/till_infinity/data/research.db ...
"""
from __future__ import annotations

import math
import os
import sqlite3
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

from till_infinity.structures.vol import envelope as ev
from till_infinity.structures.vol import projection as pj
from till_infinity.structures.vol.ranges import Ranges

PART = os.environ.get("PART", "envelope")
FAMILY = os.environ.get("FAMILY", "vol")
INTERVALS = tuple(os.environ.get("INTERVALS", "3m,15m,1h").split(","))
HORIZONS = (5, 20, 50)
TARGETS = (0.1, 0.5, 0.9)
MINUTES = {"1m": 1, "3m": 3, "15m": 15, "1h": 60}
FAMILIES = {
    "vol": [f"Volatility_{v}_Index" for v in (10, 25, 50, 75, 100)],
    "jump": [f"Jump_{v}_Index" for v in (10, 25, 50, 75, 100)],
    "boomcrash": [f"{k}_{v}_Index" for k in ("Boom", "Crash") for v in (300, 500, 1000)],
    "other": ["Step_Index", "Range_Break_100_Index", "DEX_900_UP_Index", "Drift_Switch_Index_10"],
}
GAMMAS = tuple(np.geomspace(0.0005, 0.1, 12))
SIMS = 40_000
LEVEL_GRID = np.linspace(0.001, 0.999, 999)
SECONDS_PER_YEAR = 365 * 24 * 3600
rng = np.random.default_rng(0)


# ---------------------------------------------------------------------------------- the laws

def law_published(sym: str, interval: str, n: int):
    """A function level -> log-return quantile for the next n bars, and whether it scales by price
    (Step's law is in price). None where nothing is published."""
    feed = sym.lower()
    seconds = MINUTES[interval] * 60 * n
    sigma = pj.sigma_for(feed, seconds)
    if sigma is not None:
        drift = pj.drift_for(feed, seconds, "ito")
        return lambda level, price=None: drift + sigma * _z(level)
    if feed == "step_index":
        sd = 0.1 * math.sqrt(seconds)  # one +-0.1 fair flip a second (generators.md: 5.2M flips / 60 days)
        return lambda level, price=1.0: math.log1p(sd * _z(level) / price)
    return None


_ZCACHE: dict[float, float] = {}


def _z(level: float) -> float:
    level = float(min(max(level, 1e-6), 1 - 1e-6))
    got = _ZCACHE.get(level)
    if got is None:
        from statistics import NormalDist

        got = _ZCACHE[level] = NormalDist().inv_cdf(level)
    return got


def law_iid(returns: np.ndarray, n: int):
    """The n-fold convolution of the one-bar law, by Monte Carlo from the training returns."""
    r = returns[np.isfinite(returns)]
    draws = rng.choice(r, size=(SIMS, n)).sum(axis=1)
    table = np.quantile(draws, LEVEL_GRID)
    return lambda level, price=None: float(np.interp(level, LEVEL_GRID, table))


class Hybrid:
    """AgACI over a law's levels: twelve correctors, BOA per bound, P50 their median."""

    def __init__(self, law, n: int):
        from conformal import BOA  # the harness's own implementation

        self.law, self.n = law, n
        self.experts = {q: np.full(len(GAMMAS), q) for q in TARGETS}
        self.boa = {q: BOA(len(GAMMAS)) for q in TARGETS}
        self.pending = deque()

    def quote(self, price: float) -> dict[float, float]:
        out, each = {}, {}
        for q in TARGETS:
            eq = np.array([self.law(float(a), price) for a in self.experts[q]])
            each[q] = eq
            out[q] = float(np.median(eq)) if q == 0.5 else float(self.boa[q].weights() @ eq)
        self.pending.append((out, each))
        return out

    def settle(self, y: float) -> None:
        out, each = self.pending.popleft()
        for q in TARGETS:
            eq = each[q]
            self.experts[q] = np.clip(self.experts[q] + np.array(GAMMAS) * (q - (y <= eq)), 0.002, 0.998)
            self.boa[q].update(eq, out[q], y, q)


# ---------------------------------------------------------------------------------- scoring

def score(name: str, y: np.ndarray, Q: dict, lvol: np.ndarray) -> None:
    ok = np.isfinite(y) & np.all([np.isfinite(Q[q]) for q in TARGETS], axis=0)
    y, lvol = y[ok], lvol[ok]
    Q = {q: Q[q][ok] for q in TARGETS}
    if len(y) < 100:
        print(f"      {name:<12} too few ({len(y)})")
        return
    cov = {q: np.mean(y <= Q[q]) for q in TARGETS}
    pin = {q: 1e4 * np.mean(np.maximum(q * (y - Q[q]), (q - 1) * (y - Q[q]))) for q in TARGETS}
    width = 1e4 * np.mean(Q[0.9] - Q[0.1])
    chunks = np.array_split(np.arange(len(y)), 20)
    c90 = np.array([np.mean(y[c] <= Q[0.9][c]) for c in chunks])
    fin = np.isfinite(lvol)
    terc = np.quantile(lvol[fin], [1 / 3, 2 / 3]) if fin.sum() > 30 else (np.nan, np.nan)
    reg = [np.mean(y[m] <= Q[0.9][m]) if m.sum() else np.nan
           for m in (fin & (lvol <= terc[0]), fin & (lvol > terc[0]) & (lvol <= terc[1]), fin & (lvol > terc[1]))]
    half = len(y) // 2
    h90 = (np.mean(y[:half] <= Q[0.9][:half]), np.mean(y[half:] <= Q[0.9][half:]))
    print(f"      {name:<12} cover {cov[0.1]:5.1%}/{cov[0.5]:5.1%}/{cov[0.9]:5.1%} | pinball bps "
          f"{pin[0.1]:7.2f}/{pin[0.5]:7.2f}/{pin[0.9]:7.2f} | width {width:8.1f} bps | P90 worst slice "
          f"{c90.min():5.1%} | P90 by vol third {reg[0]:5.1%}/{reg[1]:5.1%}/{reg[2]:5.1%} | P90 halves "
          f"{h90[0]:5.1%}/{h90[1]:5.1%}", flush=True)


# ---------------------------------------------------------------------------------- the envelope

def prod_quotes(c: np.ndarray, sig: np.ndarray, n: int, start: int, stop: int) -> dict:
    """Production's Envelope, fed from `start`, quotes recorded (in log return) for [start, stop)."""
    env = ev.Envelope(horizon=n)
    Q = {q: np.full(len(c), np.nan) for q in TARGETS}
    for t in range(start, stop):
        env.observe(float(c[t]), float(sig[t]))
        if env.warm:  # production publishes nothing until it is
            for i, q in enumerate(TARGETS):
                Q[q][t] = env.quote[i] * env.sigma
    return Q


def envelope_series(sym: str, interval: str, df: pd.DataFrame) -> None:
    o, h, lo, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    ranges = Ranges()
    sig = np.empty(len(c))
    for t in range(len(c)):
        ranges.observe(o[t], h[t], lo[t], c[t])
        sig[t] = ranges.ewma_tr_bps / 10_000
    logc = np.log(c)
    r1 = np.diff(logc, prepend=np.nan)
    tr_mean = pd.Series(sig).rolling(500, min_periods=250).mean().to_numpy()
    lvol = np.log(sig / tr_mean)
    split = int(0.6 * len(c))
    seconds = MINUTES[interval] * 60
    realised = np.nanstd(r1[split:]) * math.sqrt(SECONDS_PER_YEAR / seconds) * 100
    named = pj.stated.nominal(sym.lower())
    kurt = pd.Series(r1[split:]).kurt() + 3
    print(f"\n  {sym} {interval}: {len(c):,} bars, scored from bar {split:,} | realised sigma "
          f"{realised:.2f}% against named {named:.2f}% (ratio {realised / named if named else float('nan'):.4f})"
          f" | one-bar kurtosis {kurt:.2f}", flush=True)
    for n in HORIZONS:
        y = np.r_[logc[n:] - logc[:-n], np.full(n, np.nan)]
        idx = np.arange(split, len(c) - n)
        print(f"    N = {n}: sd(y) / named {np.nanstd(y[idx]) / (pj.sigma_for(sym.lower(), seconds * n) or np.nan):.4f}")
        warm = prod_quotes(c, sig, n, 0, len(c) - n)
        cold = prod_quotes(c, sig, n, split, min(split + 1000 + n, len(c) - n))
        pub = law_published(sym, interval, n)
        iid = law_iid(r1[1:split], n)
        base = pub or iid
        hyb = Hybrid(base, n)
        Qh = {q: np.full(len(c), np.nan) for q in TARGETS}
        for k, t in enumerate(idx):
            got = hyb.quote(float(c[t]))
            for q in TARGETS:
                Qh[q][t] = got[q]
            if k >= n:
                hyb.settle(float(y[idx[k - n]]))
        methods = {"prod": warm}
        if pub is not None:
            methods["law"] = {q: np.array([pub(q, float(c[t])) if split <= t < len(c) - n else np.nan
                                           for t in range(len(c))]) for q in TARGETS}
        methods["iid"] = {q: np.full(len(c), iid(q)) for q in TARGETS}
        methods["hybrid"] = Qh
        for name, Q in methods.items():
            score(name, y[idx], {q: Q[q][idx] for q in TARGETS}, lvol[idx])
        first = idx[:1000]
        quoted = np.isfinite(cold[0.9][first]).mean()
        print(f"      -- first 1,000 scored bars, cold starts (production quotes on {quoted:.0%} of them;"
              " the rest of this block is silent on the card):")
        score("prod cold", y[first], {q: cold[q][first] for q in TARGETS}, lvol[first])
        if pub is not None:
            score("law", y[first], {q: methods["law"][q][first] for q in TARGETS}, lvol[first])
        score("iid", y[first], {q: methods["iid"][q][first] for q in TARGETS}, lvol[first])
        score("hybrid", y[first], {q: Qh[q][first] for q in TARGETS}, lvol[first])


# ---------------------------------------------------------------------------------- controls

def simulate(kind: str, interval: str, bars: int, ref: pd.DataFrame | None, sym: str) -> pd.DataFrame:
    """OHLC bars from a published law, with 60 steps inside each bar for the high and low."""
    steps = 60
    dt = MINUTES[interval] * 60 / steps  # seconds per step
    total = bars * steps
    if kind == "gbm":
        sigma = pj.stated.nominal(sym.lower()) / 100 * math.sqrt(dt / SECONDS_PER_YEAR)
        inc = rng.normal(-0.5 * sigma * sigma, sigma, total)
        path = 100.0 * np.exp(np.cumsum(inc))
    elif kind == "step":
        inc = 0.1 * rng.normal(0.0, math.sqrt(dt), total)
        path = 8000.0 + np.cumsum(inc)
    elif kind == "jump":
        named = float(sym.split("_")[1])
        sd = named / 100 * math.sqrt(dt / SECONDS_PER_YEAR)
        lam = 3 / 3600 * dt  # three jumps an hour
        # the jump variance that makes the total 1.32^2 x the diffusive
        jump_sd = math.sqrt(max(1.32**2 - 1, 0) * sd * sd / lam)
        inc = rng.normal(0.0, sd, total) + rng.normal(0.0, jump_sd, total) * (rng.random(total) < lam)
        path = 100.0 * np.exp(np.cumsum(inc))
    elif kind in ("boom", "crash"):
        n_name = float(sym.split("_")[1])
        lam = dt / n_name  # one spike per n_name ticks at one tick a second
        # grind and spike size from the real series' training bars, so the scale is the feed's
        r = np.diff(np.log(ref["close"].to_numpy(dtype=float)))
        r = r[np.isfinite(r)][: int(0.6 * len(r))]
        med = np.median(np.abs(r))
        sign = 1 if kind == "boom" else -1
        spikes = r[sign * r > 10 * med]
        size = np.mean(np.abs(spikes)) if len(spikes) else 20 * med
        grind = -sign * lam * size / dt  # the arithmetic closes (generators.md): drift pays the spike
        # spike sizes resampled from the feed's own spikes: exponential sizes make small spikes the
        # real feed does not have, and the count then moves with the detection threshold
        sizes = np.abs(spikes) if len(spikes) else np.array([size])
        inc = (grind * dt + rng.normal(0.0, 0.3 * abs(grind) * dt + 1e-12, total)
               + sign * rng.choice(sizes, total) * (rng.random(total) < lam))
        path = 100.0 * np.exp(np.cumsum(inc))
    else:
        raise ValueError(kind)
    p = path.reshape(bars, steps)
    opens = np.r_[100.0 if kind != "step" else 8000.0, p[:-1, -1]]
    return pd.DataFrame({"open": opens, "high": np.maximum(p.max(axis=1), opens),
                         "low": np.minimum(p.min(axis=1), opens), "close": p[:, -1]})


def envelope() -> None:
    print(f"DERIV VARIANTS - envelope, family {FAMILY}; y = log move over N bars; scored on the last 40%",
          flush=True)
    for interval in INTERVALS:
        print(f"\n{'=' * 110}\n{interval}", flush=True)
        for sym in FAMILIES[FAMILY]:
            try:
                df = spikerisk.load(None, sym, "SEQLAB", interval)
            except (ValueError, FileNotFoundError) as exc:
                print(f"  skip {sym}: {str(exc)[:60]}")
                continue
            envelope_series(sym, interval, df.reset_index(drop=True))
        # the control: walks we generate from the published law, same length as the feed
        sym = FAMILIES[FAMILY][min(3, len(FAMILIES[FAMILY]) - 1)]
        kind = {"vol": "gbm", "jump": "jump", "boomcrash": "boom", "other": "step"}[FAMILY]
        if FAMILY == "other":
            sym = "Step_Index"
        try:
            ref = spikerisk.load(None, sym, "SEQLAB", interval)
        except (ValueError, FileNotFoundError):
            continue
        sim = simulate(kind, interval, min(len(ref), 30_000), ref, sym)
        print(f"\n  CONTROL: {kind} walk we generate from the published law of {sym}", flush=True)
        envelope_series(sym, interval, sim)


# ---------------------------------------------------------------------------------- the hazard

def spikes_of(kind: str, o, h, lo, c, mult: float) -> np.ndarray:
    move = {"boom": h - o, "crash": o - lo, "jump": np.abs(c - o)}[kind] / o
    base = np.median(np.abs(c - o) / o)
    return move > mult * base


#: The detection threshold, in multiples of the median absolute bar move. A Jump index's jump (about
#: 30x the tick sigma) is partly hidden in a bar's diffusion, so it is detected at 5x.
MULT = {"boom": 10.0, "crash": 10.0, "jump": 5.0}


def published_rate(sym: str) -> float:
    """Spikes a minute, from the name."""
    low = sym.lower()
    if low.startswith(("boom", "crash")):
        return 60.0 / float(low.split("_")[1])
    return 3 / 60.0  # Jump: three an hour


def hazard_series(sym: str, kind: str, interval: str, df: pd.DataFrame) -> None:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score

    o, h, lo, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy()
    counts = {m: int(spikes_of(kind, o, h, lo, c, m).sum()) for m in (5, 10, 20)}
    s = spikes_of(kind, o, h, lo, c, MULT[kind])
    minutes = MINUTES[interval]
    span_min = len(c) * minutes
    rate = s.sum() / span_min
    pub = published_rate(sym)
    gaps = np.diff(np.flatnonzero(s))
    cv = gaps.std() / gaps.mean() if len(gaps) > 2 else float("nan")
    print(f"\n  {sym} {interval}: {len(c):,} bars | spike bars at 5x/10x/20x {counts[5]}/{counts[10]}/{counts[20]}"
          f" | rate {rate:.4f}/min against published {pub:.4f} (ratio {rate / pub:.3f}) | gap CV {cv:.3f}"
          f" (1 memoryless; a spike every {1 / rate:.1f} min)", flush=True)
    # hazard by time since the last spike, in units of the mean gap
    since = np.full(len(c), np.nan)
    last = -1
    for t in range(len(c)):
        since[t] = (t - last) if last >= 0 else np.nan
        if s[t]:
            last = t
    nxt = np.r_[s[1:], False].astype(float)
    mean_gap = gaps.mean() if len(gaps) else np.nan
    cells = []
    for a, b in ((0, 0.25), (0.25, 0.5), (0.5, 1), (1, 2), (2, np.inf)):
        m = (since / mean_gap >= a) & (since / mean_gap < b)
        cells.append(f"[{a},{b}) {nxt[m].mean() if m.sum() else float('nan'):.3f} (n {int(m.sum())})")
    print(f"    next-bar hazard by time since the last spike / mean gap: " + " | ".join(cells))
    # features, all known at the bar's close
    prev_gap = np.full(len(c), np.nan)
    g_last = np.nan
    last = -1
    for t in range(len(c)):
        prev_gap[t] = g_last
        if s[t]:
            if last >= 0:
                g_last = t - last
            last = t
    grind = np.where(s, 0.0, np.diff(np.log(c), prepend=np.nan))
    gvol = pd.Series(np.abs(grind)).ewm(span=14).mean()
    feats = pd.DataFrame({
        "since": since, "prev_gap": prev_gap,
        "n50": pd.Series(s.astype(float)).rolling(50, min_periods=1).sum(),
        "n200": pd.Series(s.astype(float)).rolling(200, min_periods=1).sum(),
        "gvol": gvol / gvol.rolling(500, min_periods=100).mean(),
        "g5": pd.Series(grind).rolling(5).sum() / (gvol + 1e-12),
        "hour_sin": np.sin(2 * np.pi * (ts % 86400) / 86400), "hour_cos": np.cos(2 * np.pi * (ts % 86400) / 86400),
    }).fillna(-1.0)
    split = int(0.6 * len(c))
    days = (ts // 86400).astype(int)
    for n in (1, 5, 20):
        y = np.array([s[t + 1:t + 1 + n].any() for t in range(len(c) - n)] + [np.nan] * n)
        ok = np.isfinite(y)
        tr, te = ok & (np.arange(len(c)) < split), ok & (np.arange(len(c)) >= split)
        p_train = s[:split].mean()
        const = 1 - (1 - p_train) ** n
        published = 1 - math.exp(-pub * n * minutes)
        yte = y[te]
        model = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05, min_samples_leaf=200)
        model.fit(feats[tr], y[tr].astype(int))
        p = model.predict_proba(feats[te])[:, 1]
        auc = roc_auc_score(yte, p) if 0 < yte.mean() < 1 else float("nan")
        # bootstrap over days, and halves
        dte = days[te]
        uniq = np.unique(dte)
        aucs = []
        for _ in range(300):
            pick = rng.choice(uniq, len(uniq))
            m = np.concatenate([np.flatnonzero(dte == d) for d in pick])
            if 0 < yte[m].mean() < 1:
                aucs.append(roc_auc_score(yte[m], p[m]))
        lo_ci, hi_ci = (np.quantile(aucs, [0.025, 0.975]) if aucs else (np.nan, np.nan))
        half = len(yte) // 2
        halves = [roc_auc_score(yte[a:b], p[a:b]) if 0 < yte[a:b].mean() < 1 else float("nan")
                  for a, b in ((0, half), (half, len(yte)))]
        brier_c = np.mean((const - yte) ** 2)
        brier_m = np.mean((p - yte) ** 2)
        print(f"    within {n:2d} bars: realised {yte.mean():.3f} | published {published:.3f} | constant {const:.3f}"
              f" | model AUC {auc:.3f} [{lo_ci:.3f}, {hi_ci:.3f}] halves {halves[0]:.3f}/{halves[1]:.3f}"
              f" | Brier skill vs constant {1 - brier_m / brier_c:+.4f}", flush=True)


def hazard() -> None:
    db = os.path.expanduser(os.environ.get("RESEARCH_DB", "~/till_infinity/data/research.db"))
    print("DERIV VARIANTS - spike hazard; spike = 10x the median absolute bar move; trained on the first 60%")
    syms = [f"{k}_{v}_Index" for k in ("Boom", "Crash") for v in (300, 500, 1000)] + \
           [f"Jump_{v}_Index" for v in (10, 50, 100)]
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    for sym in syms:
        kind = sym.split("_")[0].lower()
        rows = conn.execute("SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval='1m' ORDER BY ts",
                            (sym.lower(),)).fetchall()
        if len(rows) > 5000:
            df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
            df["ts"] = df["ts"] // 1000
            hazard_series(sym, kind, "1m", df)
        try:
            df3 = spikerisk.load(None, sym, "SEQLAB", "3m")
            hazard_series(sym, kind, "3m", df3.reset_index(drop=True))
        except (ValueError, FileNotFoundError):
            pass
        if sym in ("Boom_1000_Index", "Crash_500_Index", "Jump_50_Index") and len(rows) > 5000:
            ref = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
            sim = simulate(kind, "1m", 60_000, ref, sym)
            sim["ts"] = 1_700_000_000 + 60 * np.arange(len(sim))
            print(f"\n  CONTROL: {kind} walk we generate from the published law of {sym}")
            hazard_series(sym, kind, "1m", sim)


if __name__ == "__main__":
    hazard() if PART == "hazard" else envelope()
