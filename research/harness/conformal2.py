"""Okita's adaptive-conformal methods on the envelope: Conformal PID, BiTrend, Multi-Strategy.

Okita, "Adaptive Conformal Prediction with Foundation Models" (SSRN 7457798) ranks 21 online
conformal methods and finds that the forecaster's quality decides how much the choice matters:
conditional-coverage spread 0.335 with GBDT, 0.150 with Chronos. Three of its methods target the two
faults `conformal.md` left in the envelope:

  cpid         Conformal PID (Angelopoulos, Candes & Tibshirani 2023), the paper's best with tree
               predictors. It tracks the quantile *value* rather than its level (P) and adds a
               saturating integrator on the recent coverage error (I). The D term is a forecast of
               the next score, which is SPCI's idea, and SPCI added nothing here (`conformal.md`),
               so it is left out. The paper's case for PID is autocorrelated residuals, and
               overlapping N-bar moves are exactly that: neighbours share N - 1 bars.
  bitrend      the paper's proactive correction: shift the level *before* coverage breaks, by the
               trend of recent absolute scores. Delta = lambda * (r2 - r1) / r1 * alpha, W = 20,
               lambda = 0.3, clipped to +-0.05 (the paper's values), widening when scores rise and
               narrowing when they fall. The scores are outcomes H bars apart, so overlapping moves
               cannot manufacture a trend. On ACI, and on AgACI's correctors.
  ms           Multi-Strategy: raw-move quantiles and volatility-normalised quantiles side by side,
               each with its own ACI, quoting whichever covered the P10-P90 band better over the
               last L = 50 outcomes, with under-coverage penalised twice. The paper's case is
               normalised scores collapsing when the scale does (Solar, 70.2% -> 89.4%); ours is the
               calm third's 82.8% P90 at 50 bars.

and the combination `conformal.md` left as the next test:

  gbm agaci    AgACI's correctors reading the quantile-boosted model's quantiles instead of the
               empirical history: regime-flat coverage from the features, drift fixed by AgACI.

Diagnosis: the paper's **calibration ratio**, realised |move| over the unit's prediction per bin of
the prediction, here mean |y| in each volatility quintile over the overall mean |y| (y is already in
units of the volatility). Near 1 in every bin means normalising by the volatility is right; well
above 1 in the calmest bin is the paper's "confidently wrong", where normalised conformal fails.

Everything else as `conformal.py`: y = log(close[t+N] / close[t]) in production volatility units,
feedback N bars late, the last 40% of each series scored, N = 5, 20, 50 at 15m, FX, metals, crypto
and Deriv's indices (a market, not a control). The baselines `aci` and `agaci` are re-run here so
every row shares one pass.

Run on the lab, one process per horizon:
  HORIZONS=5 SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/conformal2.py
"""
from __future__ import annotations

import os
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).parent))
import envelope as env

from conformal import BOA, GAMMAS, GROUPS, TARGETS, WINDOW

STEADY = 0.005
LR, KI, L_I = 0.01, 0.1, 200  # cpid: step as a share of the P10-P90 spread, integrator gain, window
W, LAMBDA, CLIP = 20, 0.3, 0.05  # bitrend
L_MS = 50  # ms
METHODS = ("aci", "agaci", "cpid", "bitrend", "agaci bitrend", "ms", "gbm", "gbm agaci")


def clip(level):
    return float(min(max(level, 0.002), 0.998))


def side(q):
    return 1.0 if q > 0.5 else -1.0 if q < 0.5 else 0.0


class Series:
    """One series' online state for one method."""

    def __init__(self, method, H):
        self.method, self.H = method, H
        self.a = {q: q for q in TARGETS}  # ACI, and ms's normalised branch
        self.a_raw = {q: q for q in TARGETS}  # ms's raw branch
        self.experts = {q: np.full(len(GAMMAS), q) for q in TARGETS}
        self.boa = {q: BOA(len(GAMMAS)) for q in TARGETS}
        self.offset = {q: 0.0 for q in TARGETS}  # cpid's P
        self.errors = {q: deque(maxlen=L_I) for q in TARGETS}  # cpid's I
        self.cover = {"norm": deque(maxlen=L_MS), "raw": deque(maxlen=L_MS)}
        self.scores = []  # |y| of settled outcomes, in order

    def trend(self):
        """BiTrend's (r2 - r1) / r1 over the last W outcomes spaced H apart."""
        spaced = self.scores[::-1][:: self.H][:W][::-1]
        if len(spaced) < W:
            return 0.0
        r1, r2 = np.mean(spaced[: W // 2]), np.mean(spaced[W // 2 :])
        return float((r2 - r1) / r1) if r1 > 0 else 0.0

    def quote(self, ctx):
        """{target: quote} plus whatever `settle` needs to learn from it."""
        m, read = self.method, ctx["read"]
        memo = {}
        if m == "aci":
            Q = {q: read(self.a[q]) for q in TARGETS}
        elif m in ("agaci", "gbm agaci", "agaci bitrend"):
            shift = 0.0
            if m == "agaci bitrend":
                shift = float(np.clip(LAMBDA * self.trend(), -1, 1))
            Q, memo["each"] = {}, {}
            for q in TARGETS:
                d = float(np.clip(side(q) * shift * min(q, 1 - q), -CLIP, CLIP))
                eq = np.array([read(clip(lv + d)) for lv in self.experts[q]])
                memo["each"][q] = eq
                Q[q] = float(np.median(eq)) if q == 0.5 else float(self.boa[q].weights() @ eq)
        elif m == "bitrend":
            t = LAMBDA * self.trend()
            Q = {q: read(clip(self.a[q] + float(np.clip(side(q) * t * min(q, 1 - q), -CLIP, CLIP))))
                 for q in TARGETS}
        elif m == "cpid":
            spread = read(0.9) - read(0.1)
            Q = {}
            for q in TARGETS:
                e = self.errors[q]
                z = sum(e) / np.sqrt(max(len(e), 1) * q * (1 - q)) if e else 0.0
                Q[q] = read(q) + self.offset[q] + KI * spread * np.tanh(z / 3)
            memo["spread"] = spread
        elif m == "ms":
            norm = {q: read(self.a[q]) for q in TARGETS}
            raw = {q: ctx["read_raw"](self.a_raw[q]) / ctx["sig"] for q in TARGETS}
            memo["norm"], memo["raw"] = norm, raw

            def loss(c):
                if not c:
                    return 0.0
                got = np.mean(c)
                return 2 * max(0.8 - got, 0) + max(got - 0.8, 0)

            Q = raw if loss(self.cover["raw"]) < loss(self.cover["norm"]) else norm
        elif m == "gbm":
            Q = {q: read(q) for q in TARGETS}
        return Q, memo

    def settle(self, y, Q, memo):
        self.scores.append(abs(y))
        m = self.method
        for q in TARGETS:
            hit = float(y <= Q[q])
            if m in ("aci", "bitrend"):
                self.a[q] = clip(self.a[q] + STEADY * (q - hit))
            elif m in ("agaci", "gbm agaci", "agaci bitrend"):
                eq = memo["each"][q]
                self.experts[q] = np.clip(self.experts[q] + np.array(GAMMAS) * (q - (y <= eq)), 0.002, 0.998)
                self.boa[q].update(eq, Q[q], y, q)
            elif m == "cpid":
                self.offset[q] += LR * memo["spread"] * (q - hit)
                self.errors[q].append(q - hit)
        if m == "ms":
            for name, a in (("norm", self.a), ("raw", self.a_raw)):
                quotes = memo[name]
                for q in TARGETS:
                    a[q] = clip(a[q] + STEADY * (q - float(y <= quotes[q])))
                self.cover[name].append(float(quotes[0.1] < y <= quotes[0.9]))


def run(g, method, H, pred=None):
    y, sig, lv = g["y"].to_numpy(), g["sig"].to_numpy(), g["lvol"].to_numpy()
    idx = np.flatnonzero(g["test"].to_numpy() & np.isfinite(y))
    quotes = {q: np.full(len(idx), np.nan) for q in TARGETS}
    if not len(idx):
        return idx, quotes
    start = max(0, idx[0] - WINDOW - H)
    hist = list(y[start : idx[0] - H])
    hist_raw = list(y[start : idx[0] - H] * sig[start : idx[0] - H])
    state = Series(method, H)
    pending = deque()
    sorted_y = sorted_raw = None
    for k, i in enumerate(idx):
        if sorted_y is None or k % 10 == 0:
            a = np.asarray(hist[-WINDOW:])
            sorted_y = np.sort(a[np.isfinite(a)])
            b = np.asarray(hist_raw[-WINDOW:])
            sorted_raw = np.sort(b[np.isfinite(b)])
        n, nr = len(sorted_y), len(sorted_raw)

        if pred is not None:
            row = pred[i]

            def read(level, row=row):
                return float(np.interp(level, env.LEVELS, row))
        else:
            def read(level, s=sorted_y, n=n):
                return float(s[int(round(np.clip(level, 0, 1) * (n - 1)))])

        def read_raw(level, s=sorted_raw, n=nr):
            return float(s[int(round(np.clip(level, 0, 1) * (n - 1)))])

        Q, memo = state.quote({"read": read, "read_raw": read_raw, "sig": sig[i]})
        for q in TARGETS:
            quotes[q][k] = Q[q]
        pending.append((i, Q, memo))
        if len(pending) > H:
            j, Qj, mj = pending.popleft()
            state.settle(float(y[j]), Qj, mj)
            hist.append(y[j])
            hist_raw.append(y[j] * sig[j])
    return idx, quotes


def calibration(frames):
    """The paper's calibration ratio: mean |y| per volatility quintile over the overall mean |y|.
    Quintiles of the unit itself (sig, ranked within each series) and of the regime (lvol)."""
    t = pd.concat([f[f["test"] & f["y"].notna()] for f in frames], ignore_index=True)
    out = []
    for name, key in (("unit", "sig"), ("regime", "lvol")):
        rank = t.groupby("sym")[key].rank(pct=True)
        bins = np.minimum((rank * 5).astype(int), 4)
        base = t["y"].abs().mean()
        ratio = [t["y"].abs()[bins == b].mean() / base for b in range(5)]
        out.append(f"{name} " + " / ".join(f"{r:.2f}" for r in ratio))
    return " | ".join(out)


def main():
    horizons = tuple(int(x) for x in os.environ.get("HORIZONS", "5,20,50").split(","))
    interval = os.environ.get("INTERVAL", "15m")
    feats = ["lvol", "r1", "r5", "r20", "rng", "hour"]
    for H in horizons:
        env.H = H
        print(f"\n{'=' * 120}\nCONFORMAL-2 {interval}, next {H} bars; test = last 40%", flush=True)
        for name, syms in GROUPS.items():
            frames = []
            for s in syms:
                try:
                    frames.append(env.frame(s, interval))
                except (ValueError, FileNotFoundError):
                    continue
            if not frames:
                continue
            allf = pd.concat(frames, ignore_index=True)
            tr = allf[~allf["test"] & allf["y"].notna()]
            fit = tr.sample(min(150_000, len(tr)), random_state=0)
            gbm = {q: HistGradientBoostingRegressor(loss="quantile", quantile=q, max_depth=4, max_iter=150,
                                                    learning_rate=0.05, min_samples_leaf=500).fit(fit[feats], fit["y"])
                   for q in env.LEVELS}
            print(f"\n  {name}: {len(allf):,} bars · calibration ratio, calm -> volatile quintile: "
                  f"{calibration(frames)}", flush=True)
            for method in METHODS:
                res = []
                for g in frames:
                    g = g.reset_index(drop=True)
                    pred = None
                    if method.startswith("gbm"):
                        pred = np.sort(np.column_stack([gbm[q].predict(g[feats].fillna(0.0)) for q in env.LEVELS]),
                                       axis=1)
                    idx, quotes = run(g, method, H, pred)
                    res.append({"y": g["y"].to_numpy()[idx], "lvol": g["lvol"].to_numpy()[idx], "Q": quotes})
                env.evaluate(method, res)
                sys.stdout.flush()


if __name__ == "__main__":
    main()
