"""ZMA + conformal inference: an anytime-valid gate, calibrated probabilities, and a Mondrian envelope.

`zeroskill.md` found the ZMA record's old bar (200 calls above 52%) passing coins on about one feed in
five; PR #19 replaced it with a single-look significance line, `Settings.zma_line` =
0.5 + 3.29 * sqrt(0.25 / calls). But the record is re-read on every bar, which is a repeated look,
and a single-look line is not valid under continuous monitoring. Three questions, pre-registered:

PART=gate  **Anytime-valid earning.** An e-process on the edge record's right/wrong sequence against
           p = 0.5: a mixture of betting martingales K_t = mean over lambda of
           prod(1 + lambda * (x_i - 0.5)), lambda in LAMBDAS. By Ville's inequality P(ever K >= 1/a)
           <= a under a coin, whenever it is looked at; across F feeds, Bonferroni: pass when
           K >= F / 0.05. Compared with the current line under continuous monitoring (checked at every
           call from 200 on):
             - book-wide ever-false-pass over 30/90/180 days, F = 100 coin feeds, at each interval's
               edge-call rate (measured by driving the production `Zma` on walks we generate);
             - days to earn for a feed with real skill p = 0.53 / 0.55 / 0.60;
             - the real feeds' records (seqlab), with walks and Deriv as markets.
           Pass: the e-process's book-wide ever-false-pass <= 5% over 180 days, and a skilled feed
           earns in time comparable to the line's (median within 2x).

PART=prob  **Calibrated probability of the edge call.** Every edge call (production `Zma.stretched`),
           its next-bar outcome as the record scores it, and a 5-bar outcome. Score: |z| / strong and
           whether the slope agrees. Inductive Venn-Abers on isotonic regression, refit every 250
           calls on the previous 3,000, scored on each series' last 40%: Brier skill over the running
           base rate, calibration by decile, both halves, day-bootstrap CIs; walks as control.
           Pass: skill over the base rate > 0 with the CI above 0 in both halves on a market family,
           and not on the walks.

PART=envelope  **Mondrian conformal by ZMA state.** The envelope's AgACI run separately for each
           z bucket (stretched down / inside / stretched up, from production `Zma.stretched`), each
           reading its own bucket's history ("mondrian"), against production's single AgACI
           ("agaci"). Empirical base everywhere; on FX a quantile-boosted base fitted on the first
           60% stands in for production's boosted FX base ("gbm agaci" vs "gbm mondrian"). N = 5, 20,
           50 at 15m. Scored as conformal.py, plus P90/P10 coverage by z bucket.
           Pass: mondrian beats agaci on pinball in a family and horizon and does not worsen the
           worst slice by more than 1 point; and the z-bucket coverage gap it closes is > 2 points.

Deriv is a market (its own rows), and the controls are walks we generate.

Run on the lab:
  PART=gate SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/zmaconformal.py
  PART=prob ...    PART=envelope HORIZONS=5 ... (one process per horizon)
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

from till_infinity.structures import zma as zm

PART = os.environ.get("PART", "gate")
ALPHA = 0.05
FEEDS = 100
LAMBDAS = np.array([0.02, 0.05, 0.1, 0.2, 0.4])
DAYS = (30, 90, 180)
BARS_PER_DAY = {"15m": 96, "1h": 24, "4h": 6}  # 24/7; FX trades about 5/7 of it
FAMS = {
    "fx": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "GBPJPY",
           "EURGBP", "AUDJPY", "EURAUD", "CHFJPY", "EURCHF"],
    "metals": ["XAUUSD", "XAGUSD"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD"],
    "deriv": ["Volatility_25_Index", "Volatility_75_Index", "Boom_1000_Index", "Crash_1000_Index",
              "Jump_50_Index", "Step_Index"],
}
RNG = np.random.default_rng(0)


def say(*a):
    print(*a, flush=True)


def walk(n, rng, kind="t3"):
    if kind == "t3":
        r = rng.standard_t(3, n) * 0.001
    else:  # GARCH(1,1): persistent volatility, no direction
        r, v = np.empty(n), 1e-6
        z = rng.standard_normal(n)
        for i in range(n):
            v = 2e-8 + 0.08 * (r[i - 1] ** 2 if i else 0.0) + 0.9 * v
            r[i] = math.sqrt(v) * z[i]
    return 100.0 * np.exp(np.cumsum(r))


def load(sym, interval):
    try:
        df = spikerisk.load(None, sym, "SEQLAB", interval)
    except (ValueError, FileNotFoundError):
        return None
    return df.reset_index(drop=True)


def drive(closes, times):
    """Production `Zma` over a close series. Per bar: z, strong, slope, stretched (the edge call).
    The edge record's outcomes: the next bar's sign against the call, nonzero moves only."""
    z = zm.Zma()
    n = len(closes)
    zz, strong, slope, edge = (np.zeros(n) for _ in range(4))
    for i, p in enumerate(closes):
        z.observe(float(p))
        zz[i], strong[i], slope[i], edge[i] = z.z_score, z.strong, z.slope, z.stretched
    return pd.DataFrame({"t": times, "close": closes, "z": zz, "strong": strong, "slope": slope,
                         "edge": edge})


def calls_of(frame, ahead=1):
    """The edge calls and their outcomes, as the record scores them (next bar, flat bars skipped),
    and over `ahead` bars."""
    c = frame["close"].to_numpy()
    e = frame["edge"].to_numpy()
    nxt = np.r_[c[1:], np.nan] - c
    far = np.r_[c[ahead:], np.full(ahead, np.nan)] - c
    m = (e != 0) & np.isfinite(nxt) & (nxt != 0)
    out = frame[m].copy()
    out["right"] = (np.sign(nxt[m]) == e[m]).astype(float)
    out["right5"] = np.where(np.isfinite(far[m]) & (far[m] != 0), (np.sign(far[m]) == e[m]), np.nan)
    return out


# ------------------------------------------------------------------------------------ gates

def line(n):
    """The production single-look line (`Settings.zma_line`)."""
    return np.maximum(0.52, 0.5 + 3.29 * np.sqrt(0.25 / np.maximum(n, 1)))


def ever_line(x):
    """Ever passed the line, checked at every call from 200 on. x: (books, calls) of 0/1."""
    s = np.cumsum(x, axis=1)
    n = np.arange(1, x.shape[1] + 1)
    ok = (s / n > line(n)) & (n >= 200)
    return ok.any(axis=1), np.where(ok.any(axis=1), ok.argmax(axis=1) + 1, -1)


def log_k(x):
    """log of the mixture e-process at every call. x: (books, calls)."""
    s = np.cumsum(x, axis=1)
    n = np.arange(1, x.shape[1] + 1)
    f = n - s
    acc = None
    for lam in LAMBDAS:  # log of the mean over lambda, accumulated to keep memory to two arrays
        term = s * math.log1p(lam / 2) + f * math.log1p(-lam / 2)
        acc = term if acc is None else np.logaddexp(acc, term)
    return acc - math.log(len(LAMBDAS))


def ever_e(x, feeds=FEEDS):
    lk = log_k(x)
    ok = lk >= math.log(feeds / ALPHA)
    return ok.any(axis=1), np.where(ok.any(axis=1), ok.argmax(axis=1) + 1, -1)


def call_rates():
    """Edge calls per bar from the production Zma on walks we generate, per walk kind."""
    rates = {}
    for kind in ("t3", "garch"):
        fr = drive(walk(20_000, np.random.default_rng(1), kind), np.arange(20_000))
        rates[kind] = len(calls_of(fr)) / 20_000
    return rates


def gate():
    rates = call_rates()
    say(f"GATE: edge calls per bar from production Zma on walks: t3 {rates['t3']:.3f}, garch "
        f"{rates['garch']:.3f}. e-process: mixture over lambda {list(LAMBDAS)}, pass at K >= "
        f"{FEEDS}/{ALPHA} = {FEEDS / ALPHA:.0f} (Ville + Bonferroni). Line: max(0.52, 0.5 + 3.29 sqrt(0.25/n)) "
        f"from 200 calls, checked at every call.")
    rate = rates["t3"]
    say("\n  coins: book of %d feeds, share of books with ANY feed ever passing, and share of feeds ever passing" % FEEDS)
    books = 100
    for interval, per_day in BARS_PER_DAY.items():
        for days in DAYS:
            n = max(1, int(rate * per_day * days * 5 / 7))
            x = RNG.random((books * FEEDS, n)) < 0.5
            ln, _ = ever_line(x)
            ee, _ = ever_e(x)
            ln_b, ee_b = ln.reshape(books, FEEDS).any(axis=1), ee.reshape(books, FEEDS).any(axis=1)
            say(f"    {interval:4s} {days:3d}d ({n:6,} calls): line  book {ln_b.mean():6.1%} feed {ln.mean():6.2%}"
                f" | e-process book {ee_b.mean():6.1%} feed {ee.mean():6.3%}")
    say("\n  days to earn for one skilled feed (median [25%, 75%] of 400 runs, 'never' within 3 years)")
    for interval, per_day in BARS_PER_DAY.items():
        per_call_days = 1 / (rate * per_day * 5 / 7)
        n = int(3 * 365 / per_call_days)
        for p in (0.53, 0.55, 0.60):
            x = RNG.random((400, n)) < p
            for name, fn in (("line", ever_line), ("e-process", ever_e)):
                hit, first = fn(x)
                d = np.where(first > 0, first * per_call_days, np.inf)
                q = np.quantile(d, [0.25, 0.5, 0.75])
                fmt = ["never" if not np.isfinite(v) else f"{v:.0f}" for v in q]
                say(f"    {interval:4s} p {p:.2f} {name:9s}: earns within 3y {hit.mean():6.1%} | days "
                    f"{fmt[1]} [{fmt[0]}, {fmt[2]}]")
    say("\n  walks through the production Zma (8 seeds x 60,000 bars): ever passing")
    for kind in ("t3", "garch"):
        ln_n = ee_n = 0
        for s in range(8):
            fr = drive(walk(60_000, np.random.default_rng(100 + s), kind), np.arange(60_000))
            x = calls_of(fr)["right"].to_numpy()[None, :]
            ln_n += ever_line(x)[0][0]
            ee_n += ever_e(x)[0][0]
        say(f"    {kind:5s}: line {ln_n}/8 | e-process {ee_n}/8")
    say("\n  real feeds (seqlab), whole history, the production Zma's edge record")
    for interval in BARS_PER_DAY:
        for fam, syms in FAMS.items():
            for sym in syms:
                df = load(sym, interval)
                if df is None or len(df) < 3000:
                    continue
                fr = drive(df["close"].to_numpy(), df["ts"].to_numpy())
                x = calls_of(fr)["right"].to_numpy()[None, :]
                if x.shape[1] < 200:
                    continue
                ln, lf = ever_line(x)
                ee, ef = ever_e(x)
                end_ok = x.mean() > line(x.shape[1])
                say(f"    {interval:4s} {fam:6s} {sym:22s} calls {x.shape[1]:7,} right {x.mean():.4f} | line: ends "
                    f"{'pass' if end_ok else '----'} ever {'yes' if ln[0] else 'no '} | e-process: max log K "
                    f"{log_k(x).max():7.2f} (pass at {math.log(FEEDS / ALPHA):.2f}) ever {'yes' if ee[0] else 'no'}")


# ------------------------------------------------------------------------------------ probability

def ivap(train_s, train_y, test_s):
    """Inductive Venn-Abers: isotonic fits with the test point labelled 0 and 1, merged as p1/(1-p0+p1)."""
    from sklearn.isotonic import IsotonicRegression

    out = np.empty(len(test_s))
    for j, s in enumerate(test_s):
        ps = []
        for lab in (0.0, 1.0):
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(np.r_[train_s, s], np.r_[train_y, lab])
            ps.append(float(iso.predict([s])[0]))
        p0, p1 = ps
        out[j] = p1 / (1 - p0 + p1) if (1 - p0 + p1) > 0 else 0.5
    return out


def prob_series(calls, target):
    """Walk-forward IVAP over one series' calls; returns test rows with p and base."""
    calls = calls.dropna(subset=[target]).reset_index(drop=True)
    if len(calls) < 4000:
        return None
    score = (np.abs(calls["z"]) / np.maximum(calls["strong"], 1e-9)).to_numpy()
    agree = (np.sign(calls["slope"]) == calls["edge"]).to_numpy()
    s = score + 10.0 * agree  # two strata on one axis: isotonic within each since the gap is large
    y = calls[target].to_numpy().astype(float)
    start = int(0.6 * len(calls))
    p, base = np.full(len(calls), np.nan), np.full(len(calls), np.nan)
    for a in range(start, len(calls), 250):
        lo = max(0, a - 3000)
        b = min(a + 250, len(calls))
        # IVAP per point is O(train); thin the calibration set to 1,500 for speed
        idx = np.arange(lo, a)
        if len(idx) > 1500:
            idx = np.sort(RNG.choice(idx, 1500, replace=False))
        p[a:b] = ivap(s[idx], y[idx], s[a:b])
        base[a:b] = y[lo:a].mean()
    out = calls.iloc[start:].copy()
    out["p"], out["base"] = p[start:], base[start:]
    out["half"] = np.where(np.arange(len(out)) < len(out) / 2, 1, 2)
    return out


def brier_skill(rows, seed=0):
    y, p, b = rows["y"].to_numpy(), rows["p"].to_numpy(), rows["base"].to_numpy()
    sk = 1 - np.mean((p - y) ** 2) / np.mean((b - y) ** 2)
    days = (rows["t"].to_numpy() // 86_400).astype(np.int64)
    uniq = np.unique(days)
    by = {d: np.flatnonzero(days == d) for d in uniq}
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(300):
        idx = np.concatenate([by[d] for d in rng.choice(uniq, len(uniq))])
        draws.append(1 - np.mean((p[idx] - y[idx]) ** 2) / np.mean((b[idx] - y[idx]) ** 2))
    return sk, np.quantile(draws, [0.025, 0.975])


def prob():
    say("PROB: inductive Venn-Abers on the edge call's |z|/strong and slope agreement; walk-forward, "
        "last 40% of each series; Brier skill over the running base rate, day-bootstrap 95% CI")
    for interval in ("15m", "1h"):
        for target in ("right", "right5"):
            say(f"\n  {interval} · target {'next bar (the record)' if target == 'right' else '5 bars'}")
            groups = dict(FAMS)
            groups["walks t3"] = ["walk_t3_%d" % i for i in range(4)]
            groups["walks garch"] = ["walk_garch_%d" % i for i in range(4)]
            for fam, syms in groups.items():
                rows = []
                for sym in syms:
                    if sym.startswith("walk_"):
                        kind, seed = sym.split("_")[1], int(sym.split("_")[2])
                        closes = walk(60_000, np.random.default_rng(500 + seed), kind)
                        times = 1_700_000_000 + np.arange(60_000) * (900 if interval == "15m" else 3600)
                    else:
                        df = load(sym, interval)
                        if df is None or len(df) < 5000:
                            continue
                        closes, times = df["close"].to_numpy(), df["ts"].to_numpy()
                    got = prob_series(calls_of(drive(closes, times), 5), target)
                    if got is not None:
                        got["y"] = got[target].astype(float)
                        rows.append(got)
                if not rows:
                    continue
                r = pd.concat(rows, ignore_index=True)
                sk, ci = brier_skill(r)
                halves = [brier_skill(r[r["half"] == h])[0] for h in (1, 2)]
                dec = pd.qcut(r["p"], 10, duplicates="drop")
                cal = r.groupby(dec, observed=True).agg(pred=("p", "mean"), real=("y", "mean"))
                worst = float((cal["real"] - cal["pred"]).abs().max())
                strong = float((r["p"] > 0.55).mean())
                say(f"    {fam:12s} n {len(r):8,} base {r['y'].mean():.4f} | skill over base {sk:+.5f} "
                    f"[{ci[0]:+.5f}, {ci[1]:+.5f}] halves {halves[0]:+.5f} / {halves[1]:+.5f} | worst decile gap "
                    f"{worst:.4f} | p range {r['p'].quantile(0.05):.3f}-{r['p'].quantile(0.95):.3f} | share p > 0.55 "
                    f"{strong:.1%}")


# ------------------------------------------------------------------------------------ envelope

def envelope():
    import envelope as env
    from conformal import GROUPS
    from conformal2 import Series, clip
    from sklearn.ensemble import HistGradientBoostingRegressor

    H = int(os.environ.get("HORIZONS", "5"))
    env.H = H
    targets = (0.1, 0.5, 0.9)
    feats = ["lvol", "r1", "r5", "r20", "rng", "hour"]
    say(f"ENVELOPE, next {H} bars at 15m, test = last 40%: production AgACI against Mondrian AgACI by ZMA bucket")

    def frame(sym):
        f = env.frame(sym, "15m")  # y, lvol, sig, features, test
        df = load(sym, "15m")
        fr = drive(df["close"].to_numpy(), df["ts"].to_numpy())
        # env.frame drops its first rows; align on the trailing rows, which it keeps in order
        f["zb"] = fr["edge"].to_numpy()[-len(f):] if len(fr) >= len(f) else 0.0
        return f

    def run(g, mondrian, pred=None):
        y, sig = g["y"].to_numpy(), g["sig"].to_numpy()
        zb = g["zb"].to_numpy().astype(int)
        idx = np.flatnonzero(g["test"].to_numpy() & np.isfinite(y))
        quotes = {q: np.full(len(idx), np.nan) for q in targets}
        if not len(idx):
            return idx, quotes
        keys = (-1, 0, 1) if mondrian else (0,)
        states = {k: Series("agaci", H) for k in keys}
        hist = {k: [] for k in keys}
        for k in keys:
            m = (np.arange(len(y)) < idx[0] - H) & np.isfinite(y)
            if mondrian:
                m &= zb == k
            hist[k] = list(y[m][-2000:])
        pending = []
        sorted_y = {k: np.sort(hist[k]) for k in keys}
        for n_, i in enumerate(idx):
            k = int(zb[i]) if mondrian else 0
            if n_ % 10 == 0:
                sorted_y = {kk: np.sort(np.asarray(hist[kk][-2000:])) for kk in keys}
            s = sorted_y[k] if len(sorted_y[k]) >= 200 else np.sort(np.concatenate([sorted_y[kk] for kk in keys]))
            if pred is not None:
                row = pred[i]

                def read(level, row=row):
                    return float(np.interp(level, env.LEVELS, row))
            else:
                def read(level, s=s):
                    return float(s[int(round(np.clip(level, 0, 1) * (len(s) - 1)))])
            Q, memo = states[k].quote({"read": read, "read_raw": read, "sig": sig[i]})
            for q in targets:
                quotes[q][n_] = Q[q]
            pending.append((i, k, Q, memo))
            if len(pending) > H:
                j, kj, Qj, mj = pending.pop(0)
                states[kj].settle(float(y[j]), Qj, mj)
                hist[kj].append(y[j])
        return idx, quotes

    groups = {k: v for k, v in GROUPS.items()}
    for name, syms in groups.items():
        frames = []
        for s in syms:
            try:
                frames.append(frame(s))
            except (ValueError, FileNotFoundError, TypeError):
                continue
        if not frames:
            continue
        bases = [("", None)]
        if name == "fx":
            allf = pd.concat(frames, ignore_index=True)
            tr = allf[~allf["test"] & allf["y"].notna()]
            fit = tr.sample(min(150_000, len(tr)), random_state=0)
            gbm = {q: HistGradientBoostingRegressor(loss="quantile", quantile=q, max_depth=4, max_iter=60,
                                                    learning_rate=0.05, min_samples_leaf=500).fit(fit[feats], fit["y"])
                   for q in env.LEVELS}
            bases.append(("gbm ", gbm))
        say(f"\n  {name}: {sum(len(f) for f in frames):,} bars")
        for label, model in bases:
            for mondrian in (False, True):
                res = []
                for g in frames:
                    g = g.reset_index(drop=True)
                    pred = None
                    if model is not None:
                        pred = np.sort(np.column_stack([model[q].predict(g[feats].fillna(0.0)) for q in env.LEVELS]), axis=1)
                    idx, quotes = run(g, mondrian, pred)
                    res.append({"y": g["y"].to_numpy()[idx], "lvol": g["lvol"].to_numpy()[idx], "Q": quotes,
                                "zb": g["zb"].to_numpy()[idx]})
                method = f"{label}{'mondrian' if mondrian else 'agaci'}"
                env.evaluate(method, res)
                y = np.concatenate([r["y"] for r in res])
                zb = np.concatenate([r["zb"] for r in res])
                q90 = np.concatenate([r["Q"][0.9] for r in res])
                q10 = np.concatenate([r["Q"][0.1] for r in res])
                by = " | ".join(f"z {int(k):+d}: P10 {np.mean(y[zb == k] <= q10[zb == k]):5.1%} P90 "
                                f"{np.mean(y[zb == k] <= q90[zb == k]):5.1%} (n {int((zb == k).sum()):,})"
                                for k in (-1, 0, 1) if (zb == k).any())
                say(f"      {'':16s} by ZMA bucket: {by}")


if __name__ == "__main__":
    {"gate": gate, "prob": prob, "envelope": envelope}[PART]()
