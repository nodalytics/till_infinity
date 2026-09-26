"""Zone fill with every modern tool: all inputs, learned weights, multi-layer, stacking, attention.

`zonefill.py` fitted the method's weights with a plain logistic regression on five inputs, and
they added at most 0.003 AUC over a distance-only physics formula. The method's author suggests
the limit is the manual weighting, and proposes the fixes a modern modeller would reach for:
- use **every input available**, and trim the fat afterwards;
- let the weights be **learned**, not hand-tuned;
- go **multi-layer**;
- **stack** several models under a meta-model;
- use an **attention** mechanism, as in LLMs.

All five are tried here, on two targets:
  fill    the zone is touched by a wick within H bars - the method's own target
  profit  the trade toward the zone (target at the zone, stop at the same distance) wins net of
          spread - the target that decides whether any of it pays

`barrier-geometry-is-irrelevant.md` bounds the first: however well fill is predicted, a trade
toward a near zone earns the drift and nothing else. So the second target is the one that could
change the conclusion, and it is scored by trading it.

Inputs: the five zone inputs of `zonefill.py`, the zone's side, and the 54 bar features of
`crashlab.features` (technical, bar shape, borrowed fields, calendar). The attention model also
sees the last 32 bars as a sequence (return, range, close location, gap, all over the baseline and
oriented toward the zone) through a small transformer encoder.

Models: logistic regression (all inputs), gradient boosting, an MLP (64-32), a stack of the three
under a logistic meta-model, and the transformer. Fit on each series' first 60% by time (a 200k-row
sample), scored on the last 40%. Trading: per bar the side with the higher predicted probability,
entries above the training block's 80th percentile of that model, non-overlapping, net of spread,
both halves reported. The four random walks are the control. Permutation importance on the
gradient-boosted models names the inputs worth keeping.

Run on the lab:
  ./.secrets/lab.sh run research/harness/zonefill2.py SEQLAB=$HOME/till_infinity/data/seqlab OMP_NUM_THREADS=16
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import HistGradientBoostingClassifier, StackingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
import zonefill as zf
from crashlab import features

torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "8")))
RNG = np.random.default_rng(23)
SEQ = 32
SETUP = {"15m": (900, 500, True), "1h": (3600, 500, True)}


def build(interval):
    rows, seqs = [], []
    seconds, long, season = SETUP[interval]
    for family, syms in zf.FAMILIES.items():
        for s in syms:
            try:
                df = spikerisk.load(None, s, "SEQLAB", interval)
            except (ValueError, FileNotFoundError) as exc:
                print(f"  skip {s}: {str(exc)[:80]}")
                continue
            df = df.rename(columns={"ts": "time"}).reset_index(drop=True)
            z = zf.label_and_trade(df, zf.zones(df), interval, family)
            feats = features(df.rename(columns={"time": "ts"}), seconds, long, season)
            fcols = [c for c in feats.columns if not c.startswith("_") and c != "ts"]
            z = z.join(feats[fcols], on="t")
            # the sequence: last SEQ bars, oriented toward the zone later
            lc, lo, hi, op = (np.log(df[c].to_numpy()) for c in ("close", "low", "high", "open"))
            base = pd.Series(np.abs(np.diff(lc, prepend=np.nan))).rolling(long, min_periods=long // 2).mean().to_numpy()
            r = np.diff(lc, prepend=np.nan) / base
            rng_ = (hi - lo) / base
            clv = np.where(hi > lo, ((lc - lo) - (hi - lc)) / np.where(hi > lo, hi - lo, 1), 0.0)
            gap = (op - np.concatenate([[np.nan], lc[:-1]])) / base
            per_bar = np.nan_to_num(np.column_stack([r, rng_, clv, gap]), nan=0.0, posinf=0.0, neginf=0.0)
            z["family"], z["sym"] = family, s
            z["test"] = z.t >= z.t.quantile(0.6)
            z["half"] = z.t >= z.t.quantile(0.8)
            z = z.dropna(subset=zf.INPUTS + ["filled", "R1"])
            z = z[z.t >= SEQ]
            idx = z.t.to_numpy()
            win = np.stack([per_bar[idx - SEQ + 1 + k] for k in range(SEQ)], axis=1)  # (n, SEQ, 4)
            win[:, :, [0, 3]] *= z.side.to_numpy()[:, None, None]  # returns point toward the zone
            win[:, :, 2] *= z.side.to_numpy()[:, None]
            rows.append(z.reset_index(drop=True))
            seqs.append(win.astype(np.float32))
    d = pd.concat(rows, ignore_index=True)
    return d, np.concatenate(seqs), fcols


class Attention(torch.nn.Module):
    def __init__(self, n_static):
        super().__init__()
        self.embed = torch.nn.Linear(4, 32)
        layer = torch.nn.TransformerEncoderLayer(32, 4, 64, dropout=0.1, batch_first=True)
        self.encoder = torch.nn.TransformerEncoder(layer, 2)
        self.pos = torch.nn.Parameter(torch.zeros(1, SEQ, 32))
        self.head = torch.nn.Sequential(torch.nn.Linear(32 + n_static, 64), torch.nn.ReLU(), torch.nn.Linear(64, 1))

    def forward(self, seq, static):
        h = self.encoder(self.embed(seq) + self.pos).mean(dim=1)
        return self.head(torch.cat([h, static], dim=1)).squeeze(1)


def fit_attention(seq_tr, st_tr, y_tr, seq_all, st_all, epochs=4):
    model = Attention(st_tr.shape[1])
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    lossf = torch.nn.BCEWithLogitsLoss()
    S, T, Y = map(torch.tensor, (seq_tr, st_tr.astype(np.float32), y_tr.astype(np.float32)))
    for _ in range(epochs):
        perm = torch.randperm(len(Y))
        model.train()
        for i in range(0, len(Y), 1024):
            b = perm[i:i + 1024]
            opt.zero_grad()
            lossf(model(S[b], T[b]), Y[b]).backward()
            opt.step()
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(seq_all), 8192):
            out.append(torch.sigmoid(model(torch.tensor(seq_all[i:i + 8192]),
                                           torch.tensor(st_all[i:i + 8192].astype(np.float32)))).numpy())
    return np.concatenate(out)


def trade(d, p, tr, label, interval):
    d = d.assign(p=p)
    best = d.loc[d.groupby(["sym", "t"]).p.idxmax()].sort_values(["sym", "t"])
    cut = np.quantile(p[tr], 0.8)
    keep, last = [], {}
    for i, s, t, pv, te in zip(best.index, best.sym, best.t, best.p, best.test):
        if te and pv >= cut and t - last.get(s, -10**9) >= zf.H:
            keep.append(i)
            last[s] = t
    b = best.loc[keep]
    if len(b) < 30:
        print(f"      {label:<30} n={len(b)}")
        return
    net = b.R1 - b.cost1
    fams = " ".join(f"{f[:3]}{net[b.family == f].mean():+.3f}" for f in zf.FAMILIES if (b.family == f).sum() >= 20)
    print(f"      {label:<30} n={len(b):>6,} win {np.mean(b.R1 > 0):5.1%} gross {b.R1.mean():+.3f} "
          f"net {net.mean():+.3f} +- {net.std() / np.sqrt(len(b)):.3f} | halves {net[~b.half].mean():+.3f} "
          f"{net[b.half].mean():+.3f} | {fams}")


def study(interval):
    d, seq, fcols = build(interval)
    static = zf.INPUTS + ["side"] + fcols
    X = d[static].to_numpy(float)
    X[:, 0] = np.log(np.maximum(X[:, 0], 1e-6))
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    tr_all = ~d.test.to_numpy()
    sample = np.flatnonzero(tr_all)
    sample = RNG.choice(sample, min(200_000, len(sample)), replace=False)
    te = d.test.to_numpy()
    y_fill = d.filled.to_numpy()
    y_profit = ((d.R1 - d.cost1) > 0).to_numpy().astype(float)
    scaler = StandardScaler().fit(X[sample])
    Xs = scaler.transform(X)
    print(f"\n{'=' * 110}\n{interval}: {d.sym.nunique()} series, {len(d):,} zone-bars, {X.shape[1]} inputs "
          f"(+{SEQ}-bar sequence for attention); test fill {y_fill[te].mean():.1%}, test profitable "
          f"{y_profit[te].mean():.1%}")
    for target, y in (("fill", y_fill), ("profit", y_profit)):
        models = {
            "logistic, all inputs": LogisticRegression(max_iter=2000, C=0.1),
            "gradient boosting": HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=300,
                                                                min_samples_leaf=200),
            "MLP 64-32": MLPClassifier((64, 32), early_stopping=True, max_iter=60, random_state=1),
            "stack (LR+GBM+MLP -> LR)": StackingClassifier(
                [("lr", LogisticRegression(max_iter=2000, C=0.1)),
                 ("gb", HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=200,
                                                       min_samples_leaf=200)),
                 ("mlp", MLPClassifier((64, 32), early_stopping=True, max_iter=40, random_state=1))],
                final_estimator=LogisticRegression(), cv=3),
        }
        print(f"\n  target: {target}")
        preds = {"physics (distance only, no fit)": d.physics.to_numpy()} if target == "fill" else {}
        for name, m in models.items():
            m.fit(Xs[sample], y[sample])
            preds[name] = m.predict_proba(Xs)[:, 1]
            if name == "gradient boosting":
                gb = m
        preds["attention (transformer, 32 bars)"] = fit_attention(seq[sample], Xs[sample], y[sample], seq, Xs)
        for name, p in preds.items():
            line = []
            for fam in ["real", "control"]:
                fm = (d.family != "synthetic").to_numpy() if fam == "real" else (d.family == "synthetic").to_numpy()
                k = te & fm
                line.append(f"{fam} AUC {roc_auc_score(y[k], p[k]):.3f} Brier {brier_score_loss(y[k], p[k]):.3f}")
            print(f"    {name:<34} " + " | ".join(line))
        print("    trading toward the zone the model favours, top 20% (target at the zone, stop at the same distance):")
        for name, p in preds.items():
            trade(d, p, tr_all, name, interval)
        sub = RNG.choice(np.flatnonzero(te), min(40_000, te.sum()), replace=False)
        imp = permutation_importance(gb, Xs[sub], y[sub], n_repeats=3, random_state=0, scoring="roc_auc", n_jobs=1)
        order = np.argsort(-imp.importances_mean)[:10]
        print("    inputs that matter (permutation importance, AUC drop): "
              + ", ".join(f"{static[i]} {imp.importances_mean[i]:.3f}" for i in order))


if __name__ == "__main__":
    for iv in os.environ.get("INTERVALS", "15m,1h").split(","):
        study(iv)
