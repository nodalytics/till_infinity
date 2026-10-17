"""Deriv ML addendum D: LSTM and GRU sequence models on OHLC-derived bar sequences, multi-task heads
(derivml_addendum.json, D_sequence_models). CPU only, torch threads capped.

One job is (timeframe, group, source); it reads the main dataset (rows, splits, main targets), the bars and the
addendum targets (OUT/add, derivml_add.py) and writes OUT/seq/<tf>_<group>_<source>.pkl (our own pickles).

  OUT=... DGROUPS=... TFS=1d,4h WORKERS=4 python research/ideas/derivml_seq.py
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import derivml_data as D  # noqa: E402
import derivml_models as M  # noqa: E402

OUT = D.OUT
SEQ = OUT / "seq"
WINDOWS = (32, 64, 128)
HID = 32
EPOCHS, PATIENCE, PER_EPOCH, BATCH, LR = 15, 3, 100000, 512, 1e-3
THREADS = int(os.environ.get("TORCH_THREADS", 2))
BIN_HEADS = ("sign1", "signk", "tup10", "tdn10", "tr_sgn20", "bup5", "bdn5", "rup50_5", "rdn50_5", "spk")
REG_HEADS = ("z1", "zk", "lrvk", "lrange1", "tr_slope20")


def channels(b, side):
    o, h, l, c = (b[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = b["atr"].to_numpy(float)
    pa = np.r_[a[0], a[:-1]]
    pc = np.r_[c[0], c[:-1]]
    rg = np.maximum(h - l, 1e-12)
    ch = np.c_[(o - pc) / pa, (h - pc) / pa, (l - pc) / pa, (c - pc) / pa, (h - l) / pa, (c - o) / rg,
               (h - np.maximum(o, c)) / rg, (np.minimum(o, c) - l) / rg, np.log(a / pa),
               (D.excursion(b, side) / pa) if side is not None else np.zeros(len(c)),
               np.zeros(len(c)), np.zeros(len(c))]
    ch[:, 10] = np.log(np.maximum((h - l) / pa, 1e-6))
    ch[:, 11] = np.sign(c - pc)
    return np.nan_to_num(np.clip(ch, -50, 50)).astype(np.float32)


def heads(rows, add):
    """The head targets per row: main-rule targets from rows, addendum targets from OUT/add."""
    k = {"1h": 24, "4h": 6, "1d": 5}
    Y = {}
    for t in ("sign1", "signk", "tup10", "tdn10", "spk"):
        if t in rows:
            Y[t] = rows[t].to_numpy(float)
    Y["lrvk"] = np.log(np.maximum(rows["rvk"].to_numpy(float), M.EPS))
    Y["lrange1"] = np.log(np.maximum(rows["range1"].to_numpy(float) ** 2, M.EPS))
    T = add["targets"]
    for src, dst in (("lr1", "z1"), ("ck", "zk"), ("tr_sgn20", "tr_sgn20"), ("tr_slope20", "tr_slope20"),
                     ("bup5", "bup5"), ("bdn5", "bdn5"), ("rup50_5", "rup50_5"), ("rdn50_5", "rdn50_5")):
        if src in T:
            Y[dst] = T[src]["y"].astype(float)
    del k
    names = [h for h in BIN_HEADS + REG_HEADS if h in Y]
    return names, np.stack([Y[h] for h in names], 1).astype(np.float32)


def run_one(spec):
    tf, grp, src = spec
    import torch
    torch.set_num_threads(THREADS)
    path = SEQ / f"{tf}_{grp}_{src}.pkl"
    if path.exists():
        return f"{tf}_{grp}_{src}: cached"
    t0 = time.time()
    d = pd.read_pickle(OUT / f"ds_{tf}_{grp}_{src}.pkl")  # our own pickle
    rows = d["rows"].reset_index(drop=True)
    bars = pd.read_pickle(OUT / f"bars_{tf}_{grp}_{src}.pkl")  # our own pickle
    add = pd.read_pickle(OUT / "add" / f"{tf}_{grp}_{src}.pkl")  # our own pickle
    names, Y = heads(rows, add)
    isbin = np.array([h in BIN_HEADS for h in names])
    # the stacked channel array and each row's position in it
    offs, chans, pos = {}, [], np.zeros(len(rows), np.int64)
    o = 0
    for sym, b in bars.items():
        side = D.REG[sym].get("side", 0) if D.REG[sym]["group"] in ("JUMPY", "RB") else None
        ch = channels(b.reset_index(drop=True), side)
        offs[sym] = o
        chans.append(ch)
        o += len(ch)
    C = np.concatenate(chans)
    sym_arr = rows["sym"].to_numpy()
    bar = rows["bar"].to_numpy(np.int64)
    for sym, ix in rows.groupby("sym", sort=False).indices.items():
        pos[ix] = offs[sym] + bar[ix]
    ts = rows["ts"].to_numpy(np.int64)
    # splits: the main rule's fit rows (labels resolve before the per-series 80% point), with the head horizon
    hmax = max(D.K[tf], 20, int(round(5 * 86400 / D.SEC[tf])))
    ysig = rows["sign1"].to_numpy(float)
    res_t = ts + hmax * D.SEC[tf]
    sp = M.splits(rows, res_t, np.where(np.isfinite(ysig), 0.0, 0.0))
    fit = sp["fit"]
    t_val = np.quantile(ts[fit], 0.85)
    emb = (128 + hmax) * D.SEC[tf]
    # the gap (purge + embargo) sits on the training side, so the validation block keeps its 15%
    tr_rows = np.flatnonzero(fit & (res_t < t_val - emb) & (bar >= max(WINDOWS)))
    va_rows = np.flatnonzero(fit & (ts >= t_val) & (bar >= max(WINDOWS)))
    # standardise the regression heads on the training rows
    mu = np.nanmean(Y[tr_rows], 0)
    sd = np.nanstd(Y[tr_rows], 0)
    mu[isbin], sd[isbin] = 0.0, 1.0
    sd = np.where(sd > 0, sd, 1.0)
    Ys = (Y - mu) / sd
    Ct = torch.from_numpy(C)

    def batch(ix, W):
        g = pos[ix][:, None] - (W - 1) + np.arange(W)[None, :]
        return Ct[torch.from_numpy(g)]

    def loss_fn(out, yb):
        m = ~torch.isnan(yb)
        yz = torch.nan_to_num(yb)
        bce = torch.nn.functional.binary_cross_entropy_with_logits(out, yz, reduction="none")
        mse = (out - yz) ** 2
        ib = torch.from_numpy(isbin)[None, :].expand_as(out)
        l_ = torch.where(ib, bce, mse) * m
        return l_.sum() / torch.clamp(m.sum(), min=1)

    class Net(torch.nn.Module):
        def __init__(self, kind):
            super().__init__()
            rnn = torch.nn.LSTM if kind == "lstm" else torch.nn.GRU
            self.rnn = rnn(C.shape[1], HID, batch_first=True)
            self.head = torch.nn.Linear(HID, len(names))

        def forward(self, x):
            hseq, _ = self.rnn(x)
            return self.head(hseq[:, -1])

    def train(kind, W, seed):
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        net = Net(kind)
        opt = torch.optim.Adam(net.parameters(), lr=LR)
        best, best_state, bad = np.inf, None, 0
        va = va_rows if len(va_rows) <= 50000 else np.sort(rng.choice(va_rows, 50000, replace=False))
        hist = []
        for ep in range(EPOCHS):
            net.train()
            ix = rng.choice(tr_rows, min(PER_EPOCH, len(tr_rows)), replace=False)
            for s_ in range(0, len(ix), BATCH):
                bi = ix[s_:s_ + BATCH]
                opt.zero_grad()
                lval = loss_fn(net(batch(bi, W)), torch.from_numpy(Ys[bi]))
                lval.backward()
                opt.step()
            net.eval()
            with torch.no_grad():
                vl = float(np.mean([loss_fn(net(batch(va[s_:s_ + 4096], W)), torch.from_numpy(Ys[va[s_:s_ + 4096]])).item()
                                    for s_ in range(0, len(va), 4096)]))
            hist.append(vl)
            if vl < best - 1e-5:
                best, bad = vl, 0
                best_state = {k_: v_.clone() for k_, v_ in net.state_dict().items()}
            else:
                bad += 1
                if bad >= PATIENCE:
                    break
        net.load_state_dict(best_state)
        return net, best, hist

    def predict(net, W):
        ok = np.flatnonzero(bar >= W - 1)
        P = np.full((len(rows), len(names)), np.nan, np.float32)
        net.eval()
        with torch.no_grad():
            for s_ in range(0, len(ok), 8192):
                bi = ok[s_:s_ + 8192]
                out = net(batch(bi, W)).numpy()
                P[bi] = out
        P[:, isbin] = 1 / (1 + np.exp(-P[:, isbin]))
        P[:, ~isbin] = P[:, ~isbin] * sd[~isbin] + mu[~isbin]
        return P

    if len(tr_rows) < 1000 or len(va_rows) < 200:
        return f"{tf}_{grp}_{src}: too few rows ({len(tr_rows)}, {len(va_rows)})"
    search = {}
    nets = {}
    for W in WINDOWS:
        net, vl, hist = train("lstm", W, 0)
        search[W] = dict(val=vl, hist=hist)
        nets[W] = net
    Wb = min(search, key=lambda w: search[w]["val"])
    preds, seeds = {}, {}
    for kind in ("lstm", "gru"):
        ps = []
        for seed in (0, 1, 2):
            if kind == "lstm" and seed == 0:
                net = nets[Wb]
            else:
                net, _, _ = train(kind, Wb, seed)
            ps.append(predict(net, Wb))
        preds[kind] = np.mean(ps, 0).astype(np.float32)
        seeds[kind] = np.stack([p[:, [names.index(h) for h in ("sign1", "z1") if h in names]] for p in ps], 0)
    SEQ.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(dict(tf=tf, group=grp, source=src, heads=names, window=Wb, search=search, pred=preds,
                      seeds=seeds, seed_heads=[h for h in ("sign1", "z1") if h in names], n_train=len(tr_rows),
                      n_val=len(va_rows)), path)
    return f"{tf}_{grp}_{src}: window {Wb}, {time.time() - t0:.0f}s"


def main():
    groups_ = os.environ.get("DGROUPS", ",".join(D.GROUPS)).split(",")
    tfs = os.environ.get("TFS", "1d,4h").split(",")
    js = [(tf, g, s) for tf in tfs for g in groups_ for s in D.SOURCES[g]
          if (OUT / "add" / f"{tf}_{g}_{s}.pkl").exists()]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 4))) as pool:
        for msg in pool.map(run_one, js, chunksize=1):
            print("  " + msg, flush=True)
    print("seq done", flush=True)


if __name__ == "__main__":
    main()
