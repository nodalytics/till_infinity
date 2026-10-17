"""Sequence models (fxml_add_rule.json section 3): LSTM, GRU and a TCN on windows of OHLC-derived bars.

Five heads (sign1, tup05, tdn05, log rvk, ret1), trained on discovery fit rows with early stopping on a
purged, later validation slice, identically on both walks. Writes OUT/seq/<tf>_<src>_<arch>_w<W>_s<seed>.pkl
with every row's head outputs and the learning curve.

  OUT=... WORKERS=6 python research/ideas/fxml_seq.py
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fxml_data as D  # noqa: E402
import fxml_models as M  # noqa: E402

OUT = D.OUT
SEQ = OUT / "seq"
NF = 11
HIDDEN = 32
EPOCH = 100_000
MAX_EPOCHS = 15
PATIENCE = 3
BATCH = 512
LR = 1e-3
HEADS = ("sign1", "tup05", "tdn05", "lrv", "ret1")
WEIGHTS = (1.0, 1.0, 1.0, 0.5, 0.5)


def bar_inputs(b):
    o, h, l, c = (b[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = b["atr"].to_numpy(float)
    cp = np.r_[c[0], c[:-1]]
    ap = np.r_[a[0], a[:-1]]
    rng = np.where(h - l > 0, h - l, np.nan)
    hr = (b["ts"].to_numpy(np.int64) // 3600) % 24
    with np.errstate(divide="ignore", invalid="ignore"):
        F = np.c_[(o - cp) / ap, (h - cp) / ap, (l - cp) / ap, (c - cp) / ap, np.log(rng / ap),
                  (c - o) / rng, (h - np.maximum(o, c)) / rng, (np.minimum(o, c) - l) / rng,
                  np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24), np.log(a / ap)]
    return np.clip(np.nan_to_num(F, nan=0.0, posinf=0.0, neginf=0.0), -10, 10).astype(np.float32)


def build(tf, src):
    """Concatenated per-bar inputs, the rows' window end index into them, and the targets."""
    d = pd.read_pickle(OUT / f"ds_{tf}_{src}.pkl")  # our own pickle
    rows = d["rows"].reset_index(drop=True)
    bars = pd.read_pickle(OUT / f"bars_{tf}_{src}.pkl")  # our own pickle
    feats, off, base = [], {}, 0
    for sym, b in bars.items():
        f = bar_inputs(b.reset_index(drop=True))
        feats.append(f)
        off[sym] = base
        base += len(f)
    Fall = np.concatenate(feats)
    end = rows["bar"].to_numpy(np.int64) + rows["sym"].map(off).to_numpy(np.int64)
    c = rows["close"].to_numpy(float)
    # ret1 from the rows (the next row of the same series is the next bar)
    ret1 = np.full(len(rows), np.nan)
    for sym, ix in rows.groupby("sym", sort=False).indices.items():
        ix = np.sort(ix)
        cc = c[ix]
        ret1[ix[:-1]] = (cc[1:] - cc[:-1]) / rows["atr"].to_numpy(float)[ix[:-1]]
    Y = np.c_[rows["sign1"], rows["tup05"], rows["tdn05"], np.log(np.maximum(rows["rvk"], M.EPS)),
              np.clip(ret1, -5, 5)].astype(np.float32)
    return rows, Fall, end, Y, d["horizons"]


def make_model(arch):
    import torch
    from torch import nn

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.arch = arch
            if arch == "lstm":
                self.rnn = nn.LSTM(NF, HIDDEN, batch_first=True)
            elif arch == "gru":
                self.rnn = nn.GRU(NF, HIDDEN, batch_first=True)
            else:
                layers = []
                ch = NF
                for dil in (1, 2, 4):
                    layers += [nn.ConstantPad1d((2 * dil, 0), 0.0), nn.Conv1d(ch, HIDDEN, 3, dilation=dil), nn.ReLU()]
                    ch = HIDDEN
                self.tcn = nn.Sequential(*layers)
            self.shared = nn.Sequential(nn.Linear(HIDDEN, 32), nn.ReLU())
            self.heads = nn.Linear(32, len(HEADS))

        def forward(self, x):
            if self.arch in ("lstm", "gru"):
                hseq, _ = self.rnn(x)
                h = hseq[:, -1]
            else:
                h = self.tcn(x.transpose(1, 2))[:, :, -1]
            return self.heads(self.shared(h))

    return Net()


def loss_fn(out, y):
    import torch
    import torch.nn.functional as F
    total = 0.0
    for k, w in enumerate(WEIGHTS):
        m = torch.isfinite(y[:, k])
        if m.sum() == 0:
            continue
        if k < 3:
            l_ = F.binary_cross_entropy_with_logits(out[m, k], y[m, k])
        else:
            l_ = F.mse_loss(out[m, k], y[m, k])
        total = total + w * l_
    return total


def job(spec):
    tf, src, arch, W, seed = spec
    name = f"{tf}_{src}_{arch}_w{W}_s{seed}"
    path = SEQ / f"{name}.pkl"
    if path.exists():
        return name, "cached"
    import torch
    torch.set_num_threads(int(os.environ.get("TORCH_THREADS", 2)))
    torch.manual_seed(seed)
    t0 = time.time()
    rows, Fall, end, Y, hz = build(tf, src)
    # windows need W bars of the same series: the row's bar index must be >= W - 1
    ok_w = rows["bar"].to_numpy() >= W - 1
    from fxml_models import splits
    # purge by the longest label horizon (rvk's k)
    ts = rows["ts"].to_numpy(np.int64)
    k = D.K[tf]
    res_t = np.full(len(rows), np.iinfo(np.int64).max, np.int64)
    for sym, ix in rows.groupby("sym", sort=False).indices.items():
        ix = np.sort(ix)
        j = np.arange(len(ix)) + k
        okj = j < len(ix)
        res_t[ix[okj]] = ts[ix[j[okj]]]
    sp = splits(rows, res_t, Y[:, 0].astype(float))
    fit = sp["fit"] & ok_w
    fit_ix = np.flatnonzero(fit)
    t_fit = ts[fit_ix]
    v_start = np.quantile(t_fit, 0.85)
    tr_ix = fit_ix[res_t[fit_ix] < v_start]
    va_ix = fit_ix[t_fit >= v_start + k * D.SEC[tf]]
    rng = np.random.default_rng(seed)
    Ft = torch.from_numpy(Fall)
    Yt = torch.from_numpy(Y)
    offs = torch.arange(-W + 1, 1)

    def batch_x(ix):
        e = torch.from_numpy(end[ix])
        return Ft[e[:, None] + offs]

    model = make_model(arch)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    curve, best, best_state, bad = [], np.inf, None, 0
    va_sub = va_ix if len(va_ix) <= 40000 else np.sort(rng.choice(va_ix, 40000, replace=False))
    for ep in range(MAX_EPOCHS):
        model.train()
        draw = rng.choice(tr_ix, EPOCH, replace=len(tr_ix) < EPOCH)
        tl = []
        for s0 in range(0, EPOCH, BATCH):
            ix = draw[s0:s0 + BATCH]
            opt.zero_grad()
            l_ = loss_fn(model(batch_x(ix)), Yt[ix])
            l_.backward()
            opt.step()
            tl.append(l_.item())
        model.eval()
        with torch.no_grad():
            vl = [float(loss_fn(model(batch_x(va_sub[s0:s0 + 4096])), Yt[va_sub[s0:s0 + 4096]]))
                  for s0 in range(0, len(va_sub), 4096)]
        v = float(np.mean(vl))
        curve.append(dict(epoch=ep + 1, train=float(np.mean(tl)), val=v))
        if v < best - 1e-5:
            best, bad = v, 0
            best_state = {kk: vv.clone() for kk, vv in model.state_dict().items()}
        else:
            bad += 1
            if bad >= PATIENCE:
                break
    model.load_state_dict(best_state)
    model.eval()
    pred = np.full((len(rows), len(HEADS)), np.nan, np.float32)
    allv = np.flatnonzero(ok_w)
    with torch.no_grad():
        for s0 in range(0, len(allv), 8192):
            ix = allv[s0:s0 + 8192]
            pred[ix] = model(batch_x(ix)).numpy()
    out = dict(tf=tf, source=src, arch=arch, window=W, seed=seed, curve=curve, heads=HEADS,
               pred=pred, n_train=len(tr_ix), n_val=len(va_ix), seconds=time.time() - t0)
    SEQ.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(out, path)
    return name, f"done in {time.time() - t0:.0f}s, {len(curve)} epochs, best val {best:.4f}"


def all_jobs():
    js = []
    for tf in ("4h", "1d", "1h"):
        if tf not in D.TFS:
            continue
        for src in D.SOURCES:
            for seed in (1, 2, 3):
                for arch in ("lstm", "gru", "tcn"):
                    js.append((tf, src, arch, 64, seed))
                if tf == "4h" and os.environ.get("WINDOWS", "1") == "1":
                    for W in (32, 128):
                        js.append((tf, src, "lstm", W, seed))
    return js


def main():
    SEQ.mkdir(parents=True, exist_ok=True)
    js = all_jobs()
    if os.environ.get("ONLY"):
        js = [j for j in js if os.environ["ONLY"] in "_".join(map(str, j))]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 6))) as pool:
        for name, msg in pool.map(job, js, chunksize=1):
            print(f"  {name}: {msg}", flush=True)
    print("seq done", flush=True)


if __name__ == "__main__":
    main()
