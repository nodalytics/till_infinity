"""Fractal memory and historical twins, tested.

The claim, from a product description: "markets do not repeat linearly, but they rhyme fractally.
The engine embeds millions of historical multi-asset candles into a 1536-dimensional vector space.
When current price action forms, it retrieves the statistically dominant historical twins to
calculate empirical win rates, volatility bands and quantile trajectories", with regime-shift
alerts (compression to expansion), 15m market probabilities, and quantile fan charts.

Every part is tested here, on 20 real instruments and four exact random walks (Deriv
synthetics - the control, where twins must find nothing), fit or remembered on each series' first
60% by time and scored on the last 40%.

Embeddings (each moment's recent candles as a vector; cosine similarity; the 50 nearest twins
retrieved from the training memory, all instruments pooled):
  shape    the last 64 bars of the base timeframe: return, range and close location, each over
           the trailing baseline move
  fractal  the same, 32 bars on each of three timeframes (base, 4x, 16x) - "rhymes across scales";
           higher timeframes come from their last completed bar only
  learned  a 1D convolutional encoder trained on the training block to predict the forward path
           quantiles; its penultimate layer is the embedding (the "vector space", learned)

What the twins produce, each scored against a baseline:
  win rate    share of twins whose forward move over H is up -> AUC, and a trade (long above the
              training 80th percentile, short below the 20th), net of spread, non-overlapping,
              both halves, a common-offset null
  vol band    twins' median |forward move| against the trailing baseline x sqrt(H), by correlation
              with the realised |move| and by QLIKE
  fan         twins' 10/50/90% quantiles of the forward move (in baseline units, rescaled to now)
              against a Gaussian fan from the EWMA sigma: coverage and pinball loss
  alert       from a compressed state (14-bar true-range percentile <= 0.2 of its last 1,500), does
              an expansion (percentile >= 0.8 within H) follow? Twins' frequency against the
              compression base rate: precision and lift in the top 10%

ML and DL on the same windows and the same targets: gradient boosting on the flattened fractal
vector, and the same 1D CNN, for direction, the fan and the alert. `PART=rnn` adds the recurrent
architectures on the same 96-step multi-timeframe sequence: LSTM, a two-layer stacked LSTM, GRU
and a vanilla RNN, each trained for the same three targets. `PART=seq` adds a transformer encoder
and a TCN (dilated causal convolutions with residual connections) on the same sequences, and
`PART=hybrid` an LSTM with self-attention over its outputs and attention pooling, and `PART=more`
a bidirectional LSTM and the same attention hybrid built on a GRU, and `PART=tcnattn` the attention
hybrid built on the TCN, `PART=cnnlstm` a CNN front end feeding an LSTM, `PART=trlstm` a transformer encoder feeding an
LSTM, and `PART=grucnn` a GRU feeding convolutions.

Fractal memory itself: the DFA Hurst exponent of returns (memory of direction) and of |returns|
(memory of volatility) per instrument - 0.5 is no memory.

Run on the lab:
  ./.secrets/lab.sh run research/harness/fractal_twins.py BASE=15m SEQLAB=$HOME/till_infinity/data/seqlab OMP_NUM_THREADS=16
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "8")))
RNG = np.random.default_rng(29)
BASE = os.environ.get("BASE", "15m")
LADDER = {"15m": ("15m", "1h", "4h"), "1h": ("1h", "4h", "1d")}[BASE]
SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
MINUTES = {k: v // 60 for k, v in SECONDS.items()}
H = 16
K = 50
FAMILIES = {
    "fx": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "GBPJPY",
           "EURGBP", "AUDJPY", "EURAUD", "CHFJPY", "EURCHF", "USDCNH"],
    "metal": ["XAUUSD", "XAGUSD"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD"],
    "control": ["Volatility_25_Index", "Volatility_75_Index", "Volatility_100_Index", "Step_Index"],
}
COST_V = {"fx": 0.8, "metal": 0.16, "crypto": 0.5, "control": 0.15}


def bars(sym, interval):
    df = spikerisk.load(None, sym, "SEQLAB", interval)
    lc, hi, lo = np.log(df.close), np.log(df.high), np.log(df.low)
    r = lc.diff()
    long = 250 if interval == "1d" else 500
    base = r.abs().rolling(long, min_periods=long // 2).mean()
    rng = (hi - lo).replace(0, np.nan)
    per = pd.DataFrame({
        "r": r / base, "range": (hi - lo) / base, "clv": (((lc - lo) - (hi - lc)) / rng).fillna(0.0),
    }).clip(-10, 10).fillna(0.0)
    return df.ts.to_numpy() + SECONDS[interval], per.to_numpy(np.float32), lc.to_numpy(), base.to_numpy(), df


def windows(per, idx, n):
    return np.stack([per[idx - n + 1 + k] for k in range(n)], axis=1)  # (m, n, 3)


def build():
    rows = []
    for family, syms in FAMILIES.items():
        for s in syms:
            try:
                close_t, per, lc, base, df = bars(s, LADDER[0])
                higher = [bars(s, tf) for tf in LADDER[1:]]
            except (ValueError, FileNotFoundError) as exc:
                print(f"  skip {s}: {str(exc)[:80]}")
                continue
            n = len(lc)
            idx = np.arange(max(64, 600), n - H - 1)
            shape = windows(per, idx, 64)
            parts = [windows(per, idx, 32)]
            ok = np.ones(len(idx), bool)
            for ct, p_, _, _, _ in higher:
                j = np.searchsorted(ct, close_t[idx], side="right") - 1  # last completed bar
                ok &= j >= 32
                jj = np.clip(j, 32, None)
                parts.append(windows(p_, jj, 32))
            fractal = np.concatenate(parts, axis=1)  # (m, 96, 3)
            fwd = np.column_stack([lc[idx + 1 + k] - lc[idx + 1] for k in range(1, H + 1)]) / base[idx][:, None]
            # true-range percentile for the compression/expansion alert
            hi_, lo_, cl = (np.log(df[c].to_numpy()) for c in ("high", "low", "close"))
            prev = np.concatenate([[cl[0]], cl[:-1]])
            tr = np.maximum(hi_ - lo_, np.maximum(np.abs(hi_ - prev), np.abs(lo_ - prev)))
            pct = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().rolling(1500, min_periods=200).rank(pct=True).to_numpy()
            future_max = np.column_stack([pct[idx + k] for k in range(1, H + 1)]).max(axis=1)
            sigma = pd.Series(np.diff(lc, prepend=np.nan)).pow(2).ewm(alpha=1 / 30, adjust=False).mean().pow(0.5).to_numpy()
            keep = ok & np.isfinite(fwd).all(axis=1) & np.isfinite(base[idx]) & np.isfinite(pct[idx])
            m = int(keep.sum())
            rows.append(dict(
                family=family, sym=s, t=idx[keep], shape=shape[keep], fractal=fractal[keep], fwd=fwd[keep],
                compressed=(pct[idx] <= 0.2)[keep], expanded=(future_max >= 0.8)[keep],
                sig_ratio=(sigma[idx] / base[idx])[keep],
                test=(idx >= n * 0.6)[keep], half=(idx >= n * 0.8)[keep], cost=np.full(m, COST_V[family] / np.sqrt(MINUTES[LADDER[0]] / 5)),
            ))
    cat = {k: np.concatenate([r[k] if isinstance(r[k], np.ndarray) else np.full(len(r["t"]), r[k]) for r in rows])
           for k in rows[0]}
    return cat


def normalise(v):
    v = v.reshape(len(v), -1).astype(np.float32)
    v = v - v.mean(axis=1, keepdims=True)
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)


def twins(memory, queries, k=K, chunk=512):
    """Indices of the k most cosine-similar memory rows for each query."""
    out = np.empty((len(queries), k), np.int64)
    mt = torch.tensor(memory)
    for i in range(0, len(queries), chunk):
        sim = torch.tensor(queries[i:i + chunk]) @ mt.T
        out[i:i + chunk] = torch.topk(sim, k, dim=1).indices.numpy()
    return out


class CNN(torch.nn.Module):
    def __init__(self, length, outputs):
        super().__init__()
        self.body = torch.nn.Sequential(
            torch.nn.Conv1d(3, 32, 5, padding=2), torch.nn.ReLU(), torch.nn.MaxPool1d(2),
            torch.nn.Conv1d(32, 64, 5, padding=2), torch.nn.ReLU(), torch.nn.AdaptiveAvgPool1d(4),
            torch.nn.Flatten(), torch.nn.Linear(256, 64), torch.nn.ReLU())
        self.head = torch.nn.Linear(64, outputs)

    def forward(self, x):
        return self.head(self.body(x))


def fit_cnn(X, Y, loss, epochs=4, outputs=None):
    model = CNN(X.shape[1], outputs or Y.shape[1])
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    Xt, Yt = torch.tensor(X.transpose(0, 2, 1).copy()), torch.tensor(Y.astype(np.float32))
    for _ in range(epochs):
        perm = torch.randperm(len(Yt))
        for i in range(0, len(Yt), 1024):
            b = perm[i:i + 1024]
            opt.zero_grad()
            loss(model(Xt[b]), Yt[b]).backward()
            opt.step()
    return model


def predict_cnn(model, X, embed=False):
    out = []
    with torch.no_grad():
        for i in range(0, len(X), 8192):
            x = torch.tensor(X[i:i + 8192].transpose(0, 2, 1).copy())
            out.append((model.body(x) if embed else model(x)).numpy())
    return np.concatenate(out)


class Recurrent(torch.nn.Module):
    def __init__(self, kind, outputs, hidden=48, layers=1):
        super().__init__()
        cell = {"lstm": torch.nn.LSTM, "gru": torch.nn.GRU, "rnn": torch.nn.RNN}[kind]
        self.rnn = cell(3, hidden, num_layers=layers, batch_first=True)
        self.head = torch.nn.Linear(hidden, outputs)

    def forward(self, x):
        out, _ = self.rnn(x)
        return self.head(out[:, -1])


def fit_rnn(kind, layers, X, Y, loss, outputs, epochs=3):
    model = Recurrent(kind, outputs, layers=layers)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    Xt, Yt = torch.tensor(X.copy()), torch.tensor(Y.astype(np.float32))
    for _ in range(epochs):
        perm = torch.randperm(len(Yt))
        for i in range(0, len(Yt), 1024):
            b = perm[i:i + 1024]
            opt.zero_grad()
            loss(model(Xt[b]), Yt[b]).backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(X), 8192):
            out.append(model(torch.tensor(X[i:i + 8192].copy())).numpy())
    return np.concatenate(out)


class Transformer(torch.nn.Module):
    def __init__(self, outputs, length=96, width=32):
        super().__init__()
        self.embed = torch.nn.Linear(3, width)
        self.pos = torch.nn.Parameter(torch.zeros(1, length, width))
        layer = torch.nn.TransformerEncoderLayer(width, 4, 64, dropout=0.1, batch_first=True)
        self.encoder = torch.nn.TransformerEncoder(layer, 2)
        self.head = torch.nn.Linear(width, outputs)

    def forward(self, x):
        return self.head(self.encoder(self.embed(x) + self.pos[:, : x.shape[1]]).mean(dim=1))


class TCN(torch.nn.Module):
    """Dilated causal convolutions, residual, receptive field over the whole 96-step sequence."""

    def __init__(self, outputs, width=32, dilations=(1, 2, 4, 8, 16, 32)):
        super().__init__()
        self.inp = torch.nn.Conv1d(3, width, 1)
        self.blocks = torch.nn.ModuleList(torch.nn.Conv1d(width, width, 3, dilation=d) for d in dilations)
        self.dilations = dilations
        self.head = torch.nn.Linear(width, outputs)

    def forward(self, x):
        h = self.inp(x.transpose(1, 2))
        for conv, d in zip(self.blocks, self.dilations):
            h = h + torch.relu(conv(torch.nn.functional.pad(h, (2 * d, 0))))  # causal padding
        return self.head(h[:, :, -1])


class LSTMAttention(torch.nn.Module):
    """LSTM, then multi-head self-attention over its outputs, then attention pooling with a learned
    query - the recurrent model decides what each step means, attention decides which steps count."""

    def __init__(self, outputs, hidden=48, heads=4, cell="lstm"):
        super().__init__()
        self.lstm = {"lstm": torch.nn.LSTM, "gru": torch.nn.GRU}[cell](3, hidden, batch_first=True)
        self.attn = torch.nn.MultiheadAttention(hidden, heads, batch_first=True)
        self.norm = torch.nn.LayerNorm(hidden)
        self.query = torch.nn.Parameter(torch.randn(1, 1, hidden) * 0.1)
        self.pool = torch.nn.MultiheadAttention(hidden, heads, batch_first=True)
        self.head = torch.nn.Linear(hidden, outputs)

    def forward(self, x):
        h, _ = self.lstm(x)
        a, _ = self.attn(h, h, h)
        h = self.norm(h + a)
        pooled, _ = self.pool(self.query.expand(len(h), -1, -1), h, h)
        return self.head(pooled[:, 0])


class TCNAttention(torch.nn.Module):
    """TCN features at every step, then self-attention over them and attention pooling with a
    learned query - convolutions for local shape, attention for which steps count."""

    def __init__(self, outputs, width=32, heads=4, dilations=(1, 2, 4, 8, 16, 32)):
        super().__init__()
        self.inp = torch.nn.Conv1d(3, width, 1)
        self.blocks = torch.nn.ModuleList(torch.nn.Conv1d(width, width, 3, dilation=d) for d in dilations)
        self.dilations = dilations
        self.attn = torch.nn.MultiheadAttention(width, heads, batch_first=True)
        self.norm = torch.nn.LayerNorm(width)
        self.query = torch.nn.Parameter(torch.randn(1, 1, width) * 0.1)
        self.pool = torch.nn.MultiheadAttention(width, heads, batch_first=True)
        self.head = torch.nn.Linear(width, outputs)

    def forward(self, x):
        h = self.inp(x.transpose(1, 2))
        for conv, d in zip(self.blocks, self.dilations):
            h = h + torch.relu(conv(torch.nn.functional.pad(h, (2 * d, 0))))
        h = h.transpose(1, 2)
        a, _ = self.attn(h, h, h)
        h = self.norm(h + a)
        pooled, _ = self.pool(self.query.expand(len(h), -1, -1), h, h)
        return self.head(pooled[:, 0])


class CNNLSTM(torch.nn.Module):
    """Convolutions extract local candle shapes, an LSTM reads them in order."""

    def __init__(self, outputs, width=32, hidden=48):
        super().__init__()
        self.conv = torch.nn.Sequential(
            torch.nn.Conv1d(3, width, 5, padding=2), torch.nn.ReLU(),
            torch.nn.Conv1d(width, width, 5, padding=2), torch.nn.ReLU(), torch.nn.MaxPool1d(2))
        self.lstm = torch.nn.LSTM(width, hidden, batch_first=True)
        self.head = torch.nn.Linear(hidden, outputs)

    def forward(self, x):
        h = self.conv(x.transpose(1, 2)).transpose(1, 2)
        out, _ = self.lstm(h)
        return self.head(out[:, -1])


class TransformerLSTM(torch.nn.Module):
    """A transformer encoder relates every step to every other, then an LSTM reads the result in
    order - the reverse of `LSTMAttention`."""

    def __init__(self, outputs, width=32, hidden=48, length=96):
        super().__init__()
        self.embed = torch.nn.Linear(3, width)
        self.pos = torch.nn.Parameter(torch.zeros(1, length, width))
        layer = torch.nn.TransformerEncoderLayer(width, 4, 64, dropout=0.1, batch_first=True)
        self.encoder = torch.nn.TransformerEncoder(layer, 2)
        self.lstm = torch.nn.LSTM(width, hidden, batch_first=True)
        self.head = torch.nn.Linear(hidden, outputs)

    def forward(self, x):
        h = self.encoder(self.embed(x) + self.pos[:, : x.shape[1]])
        out, _ = self.lstm(h)
        return self.head(out[:, -1])


class GRUCNN(torch.nn.Module):
    """A GRU reads the sequence in order, then convolutions scan its hidden states for local
    patterns - the reverse of `CNNLSTM`."""

    def __init__(self, outputs, hidden=48, width=32):
        super().__init__()
        self.gru = torch.nn.GRU(3, hidden, batch_first=True)
        self.conv = torch.nn.Sequential(
            torch.nn.Conv1d(hidden, width, 5, padding=2), torch.nn.ReLU(),
            torch.nn.Conv1d(width, width, 5, padding=2), torch.nn.ReLU(), torch.nn.AdaptiveMaxPool1d(1))
        self.head = torch.nn.Linear(width, outputs)

    def forward(self, x):
        h, _ = self.gru(x)
        return self.head(self.conv(h.transpose(1, 2))[:, :, 0])


class BiLSTM(torch.nn.Module):
    """Reads each window forwards and backwards. Legitimate here: the whole window is already
    in the past when the decision is made, so the backward pass sees nothing the forward one could
    not."""

    def __init__(self, outputs, hidden=48):
        super().__init__()
        self.rnn = torch.nn.LSTM(3, hidden, batch_first=True, bidirectional=True)
        self.hidden = hidden
        self.head = torch.nn.Linear(2 * hidden, outputs)

    def forward(self, x):
        out, _ = self.rnn(x)
        return self.head(torch.cat([out[:, -1, : self.hidden], out[:, 0, self.hidden:]], dim=1))


def rnn_part(archs=None):
    """The recurrent (or other sequence) architectures, on the fractal sequence, for the three targets."""
    archs = archs or [(f"{name}", (lambda o, k=kind, l=layers: Recurrent(k, o, layers=l)))
                      for kind, layers, name in (("lstm", 1, "LSTM"), ("lstm", 2, "LSTM x2 (stacked)"),
                                                 ("gru", 1, "GRU"), ("rnn", 1, "vanilla RNN"))]
    c = build()
    tr = ~c["test"]
    real = c["family"] != "control"
    y_fwd = c["fwd"][:, -1]
    y_up = (y_fwd > 0).astype(float)
    ex_all = c["expanded"].astype(float)
    q = np.flatnonzero(c["test"] & ((c["t"] % 4) == 0))
    sub = RNG.choice(np.flatnonzero(tr), min(150_000, tr.sum()), replace=False)
    Xf = c["fractal"]
    taus = torch.tensor([0.1, 0.5, 0.9])

    def qloss(p, y):
        e = y[:, :1] - p
        return torch.mean(torch.maximum(taus * e, (taus - 1) * e))

    bce = torch.nn.BCEWithLogitsLoss()
    print(f"\n{'=' * 110}\nSEQUENCE MODELS BASE {BASE} (ladder {', '.join(LADDER)}), H={H}, sequence 96 x 3, "
          f"train sample {len(sub):,}")
    comp = c["compressed"][q]
    for name, factory in archs:
        # train on the sample, predict everything
        def run(target, loss, outputs):
            model = factory(outputs)
            opt = torch.optim.Adam(model.parameters(), lr=1e-3)
            Xt, Yt = torch.tensor(Xf[sub].copy()), torch.tensor(target[sub].astype(np.float32))
            for _ in range(3):
                perm = torch.randperm(len(Yt))
                for i in range(0, len(Yt), 1024):
                    b = perm[i:i + 1024]
                    opt.zero_grad()
                    loss(model(Xt[b]), Yt[b]).backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    opt.step()
            model.eval()
            out = []
            with torch.no_grad():
                for i in range(0, len(Xf), 8192):
                    out.append(model(torch.tensor(Xf[i:i + 8192].copy())).numpy())
            return np.concatenate(out)

        p_up = 1 / (1 + np.exp(-run(y_up[:, None], bce, 1)[:, 0]))
        p_q = np.sort(run(y_fwd[:, None], qloss, 3), axis=1)
        p_ex = 1 / (1 + np.exp(-run(ex_all[:, None], bce, 1)[:, 0]))
        auc = [f"{lab} {roc_auc_score(y_up[q][fm[q]], p_up[q][fm[q]]):.3f}" for lab, fm in (("real", real), ("control", ~real))]
        yq = y_fwd[q]
        fan = []
        for lab, fm in (("real", real[q]), ("control", ~real[q])):
            cov = np.mean((yq[fm] >= p_q[q][fm, 0]) & (yq[fm] <= p_q[q][fm, 2]))
            fan.append(f"{lab} cov {cov:.1%} pinball {pinball(p_q[q][fm], yq[fm]):.3f}")
        al = []
        for lab, fm in (("real", real[q]), ("control", ~real[q])):
            k = comp & fm
            ex = c["expanded"][q][k].astype(float)
            top = p_ex[q][k] >= np.quantile(p_ex[q][k], 0.9)
            al.append(f"{lab} AUC {roc_auc_score(ex, p_ex[q][k]):.3f} lift {ex[top].mean() / ex.mean():.2f}x")
        print(f"  {name:<18} direction AUC {' | '.join(auc)}")
        print(f"  {'':<18} fan {' | '.join(fan)}")
        print(f"  {'':<18} alert from compression {' | '.join(al)}")
        trade(c, p_up, tr, f"trade {name}")


def pinball(q, y, taus=(0.1, 0.5, 0.9)):
    return np.mean([np.mean(np.maximum(t * (y - q[:, i]), (t - 1) * (y - q[:, i]))) for i, t in enumerate(taus)])


def trade(c, score, tr, label, h=H):
    hi, lo = np.quantile(score[tr], 0.8), np.quantile(score[tr], 0.2)
    side = np.where(score >= hi, 1.0, np.where(score <= lo, -1.0, 0.0))
    fwd = c["fwd"][:, -1]
    real = c["family"] != "control"
    out = []
    for name, fm in (("real", real), ("control", ~real)):
        k = c["test"] & fm & (side != 0) & ((c["t"] % h) == 0)
        if k.sum() < 30:
            continue
        net = side[k] * fwd[k] - c["cost"][k]
        null = []
        sy = c["sym"]
        for _ in range(150):
            f = RNG.uniform(0.1, 0.9)
            tot, n = 0.0, 0
            for s in np.unique(sy[fm]):
                m = c["test"] & (sy == s) & ((c["t"] % h) == 0)
                p = np.roll(side[m], int(f * m.sum()))
                tot += (p[p != 0] * fwd[m][p != 0] - c["cost"][m][p != 0]).sum()
                n += (p != 0).sum()
            null.append(tot / max(n, 1))
        null = np.array(null)
        half = c["half"][k]
        out.append(f"{name} n={k.sum()} net {net.mean():+.3f}+-{net.std() / np.sqrt(k.sum()):.3f} "
                   f"({net[~half].mean():+.3f}/{net[half].mean():+.3f}) z {(net.mean() - null.mean()) / max(null.std(), 1e-12):+.1f}")
    print(f"    {label:<34} " + " | ".join(out))


def dfa(x, scales=(16, 32, 64, 128, 256, 512)):
    y = np.cumsum(x - np.nanmean(x))
    F = []
    for s in scales:
        n = len(y) // s
        segs = y[: n * s].reshape(n, s)
        t = np.arange(s)
        res = [np.sqrt(np.mean((seg - np.polyval(np.polyfit(t, seg, 1), t)) ** 2)) for seg in segs[:2000]]
        F.append(np.mean(res))
    return np.polyfit(np.log(scales), np.log(F), 1)[0]


def main():
    c = build()
    tr, te = ~c["test"], c["test"]
    real = c["family"] != "control"
    y_fwd = c["fwd"][:, -1]
    y_up = (y_fwd > 0).astype(float)
    print(f"\n{'=' * 110}\nBASE {BASE} (ladder {', '.join(LADDER)}), H={H} bars, {len(np.unique(c['sym']))} series, "
          f"{len(y_fwd):,} moments; memory = training block")
    # the memory: a subsample of training moments, to keep retrieval tractable
    mem = RNG.choice(np.flatnonzero(tr), min(300_000, tr.sum()), replace=False)
    q = np.flatnonzero(te & ((c["t"] % 4) == 0))  # queries: every 4th test moment
    q_tr = RNG.choice(np.flatnonzero(tr), min(60_000, tr.sum()), replace=False)  # to set thresholds

    # learned embedding + DL heads
    Xf = c["fractal"]
    taus = torch.tensor([0.1, 0.5, 0.9])

    def qloss(p, y):
        e = y[:, :1] - p
        return torch.mean(torch.maximum(taus * e, (taus - 1) * e))

    sub = RNG.choice(np.flatnonzero(tr), min(250_000, tr.sum()), replace=False)
    cnn_q = fit_cnn(Xf[sub], np.column_stack([y_fwd[sub]]), qloss, outputs=3)
    cnn_up = fit_cnn(Xf[sub], y_up[sub][:, None], torch.nn.BCEWithLogitsLoss())
    cnn_ex = fit_cnn(Xf[sub], c["expanded"][sub].astype(float)[:, None], torch.nn.BCEWithLogitsLoss())

    embeds = {"shape": normalise(c["shape"]), "fractal": normalise(Xf)}
    emb_learned = predict_cnn(cnn_q, Xf, embed=True)
    embeds["learned"] = normalise(emb_learned)

    est = {}
    for name, E in embeds.items():
        for label, rows in (("test", q), ("train", q_tr)):
            nn = twins(E[mem], E[rows])
            f = y_fwd[mem][nn]
            est[(name, label)] = dict(
                win=(f > 0).mean(axis=1), band=np.median(np.abs(f), axis=1),
                q=np.quantile(f, [0.1, 0.5, 0.9], axis=1).T,
                expand=c["expanded"][mem][nn].mean(axis=1))
    # ML: gradient boosting on the flattened fractal vector
    flat = Xf.reshape(len(Xf), -1)
    gb_up = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05).fit(flat[sub], y_up[sub])
    gb_ex = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05).fit(flat[sub], c["expanded"][sub])
    gb_q = [HistGradientBoostingRegressor(loss="quantile", quantile=t, max_depth=4, max_iter=200).fit(flat[sub], y_fwd[sub])
            for t in (0.1, 0.5, 0.9)]
    cnn_up_p = 1 / (1 + np.exp(-predict_cnn(cnn_up, Xf)[:, 0]))
    cnn_ex_p = 1 / (1 + np.exp(-predict_cnn(cnn_ex, Xf)[:, 0]))
    cnn_q_p = predict_cnn(cnn_q, Xf)

    # ---- 15m market probabilities: direction
    print("\n  DIRECTION - P(up over H): AUC on the test block (real / control), then traded")
    full_up = {"twins " + n: None for n in embeds}
    for n in embeds:
        for rows, lab in ((q, "test"),):
            sc = np.full(len(y_fwd), np.nan)
            sc[q] = est[(n, "test")]["win"]
            sc[q_tr] = est[(n, "train")]["win"]
            full_up["twins " + n] = sc
    full_up["gradient boosting"] = gb_up.predict_proba(flat)[:, 1]
    full_up["CNN"] = cnn_up_p
    for name, sc in full_up.items():
        a = [f"{lab} AUC {roc_auc_score(y_up[q][fm[q]], sc[q][fm[q]]):.3f}" for lab, fm in (("real", real), ("control", ~real))]
        print(f"    {name:<34} " + " | ".join(a))
    for name, sc in full_up.items():
        s2 = np.where(np.isfinite(sc), sc, np.nan)
        trmask = tr & np.isfinite(s2)
        s2 = np.nan_to_num(s2, nan=np.nanmedian(s2))
        trade(c, s2, trmask, f"trade {name}")

    # ---- vol band
    print("\n  VOLATILITY BAND - predicted |move| over H vs realised: Spearman (real / control), QLIKE (real)")
    realised = np.abs(y_fwd[q]) + 1e-6
    base_pred = np.full(len(q), np.sqrt(H) * 0.8)  # baseline units: a random walk's E|move| ~ 0.8 sqrt(H)
    ewma_pred = c["sig_ratio"][q] * np.sqrt(H) * 0.8
    preds = {"trailing baseline x sqrt(H)": base_pred, "EWMA sigma x sqrt(H)": ewma_pred}
    for n in embeds:
        preds["twins " + n] = est[(n, "test")]["band"]
    for name, p in preds.items():
        p = np.maximum(p, 1e-3)
        rs = [f"{lab} rho {stats.spearmanr(p[fm[q]], realised[fm[q]]).statistic:+.3f}" if np.std(p[fm[q]]) > 0 else f"{lab} rho n/a"
              for lab, fm in (("real", real), ("control", ~real))]
        ql = np.mean((realised[real[q]] ** 2) / p[real[q]] ** 2 - np.log((realised[real[q]] ** 2) / p[real[q]] ** 2) - 1)
        print(f"    {name:<34} " + " | ".join(rs) + f" | QLIKE {ql:.3f}")

    # ---- quantile fans
    print("\n  QUANTILE FAN - 10/50/90% of the move over H: coverage of the 10-90 band (target 80%) and pinball loss (real)")
    z = stats.norm.ppf([0.1, 0.5, 0.9])
    fans = {"Gaussian from EWMA sigma": (c["sig_ratio"][q] * np.sqrt(H) * np.sqrt(np.pi / 2))[:, None] * z[None, :]}
    for n in embeds:
        fans["twins " + n] = est[(n, "test")]["q"]
    fans["gradient boosting (quantile)"] = np.column_stack([g.predict(flat[q]) for g in gb_q])
    fans["CNN (quantile)"] = cnn_q_p[q]
    yq = y_fwd[q]
    for name, fq in fans.items():
        fq = np.sort(fq, axis=1)
        out = []
        for lab, fm in (("real", real[q]), ("control", ~real[q])):
            cov = np.mean((yq[fm] >= fq[fm, 0]) & (yq[fm] <= fq[fm, 2]))
            out.append(f"{lab} coverage {cov:.1%} pinball {pinball(fq[fm], yq[fm]):.3f}")
        print(f"    {name:<34} " + " | ".join(out))

    # ---- regime-shift alert
    print("\n  REGIME SHIFT - from compression (TR percentile <= 0.2), does expansion (>= 0.8) follow within H?")
    comp = c["compressed"][q]
    ex = c["expanded"][q].astype(float)
    alerts = {f"twins {n}": est[(n, "test")]["expand"] for n in embeds}
    alerts["gradient boosting"] = gb_ex.predict_proba(flat[q])[:, 1]
    alerts["CNN"] = cnn_ex_p[q]
    for lab, fm in (("real", real[q]), ("control", ~real[q])):
        k = comp & fm
        print(f"    {lab}: base rate of expansion from compression {ex[k].mean():.1%} (n={k.sum():,}); "
              f"from any state {ex[fm].mean():.1%}")
        for name, p in alerts.items():
            if ex[k].min() == ex[k].max():
                continue
            top = p[k] >= np.quantile(p[k], 0.9)
            print(f"      {name:<32} AUC {roc_auc_score(ex[k], p[k]):.3f} | top-10% alert precision {ex[k][top].mean():.1%} "
                  f"(lift {ex[k][top].mean() / ex[k].mean():.2f}x)")
    # after an expansion alert, can anyone call the side?
    k = comp & real[q] & (ex == 1)
    if k.sum() > 100:
        print(f"    side of the expansion, real, n={k.sum():,}: twins-fractal AUC "
              f"{roc_auc_score(y_up[q][k], est[('fractal', 'test')]['win'][k]):.3f}, CNN AUC {roc_auc_score(y_up[q][k], cnn_up_p[q][k]):.3f}")

    # ---- fractal memory
    print("\n  FRACTAL MEMORY - DFA Hurst exponent per family (0.5 = no memory): returns | |returns|")
    for fam in FAMILIES:
        hs, hv = [], []
        for s in FAMILIES[fam]:
            try:
                _, per, _, _, _ = bars(s, LADDER[0])
            except (ValueError, FileNotFoundError):
                continue
            r = per[:, 0]
            hs.append(dfa(r))
            hv.append(dfa(np.abs(r)))
        if hs:
            print(f"    {fam:<8} returns {np.mean(hs):.3f} ({min(hs):.3f}-{max(hs):.3f}) | |returns| {np.mean(hv):.3f} "
                  f"({min(hv):.3f}-{max(hv):.3f})")


if __name__ == "__main__":
    part = os.environ.get("PART", "")
    if part == "rnn":
        rnn_part()
    elif part == "grucnn":
        rnn_part([("GRU-CNN", lambda o: GRUCNN(o))])
    elif part == "trlstm":
        rnn_part([("transformer-LSTM", lambda o: TransformerLSTM(o))])
    elif part == "cnnlstm":
        rnn_part([("CNN-LSTM", lambda o: CNNLSTM(o))])
    elif part == "tcnattn":
        rnn_part([("TCN + attention", lambda o: TCNAttention(o))])
    elif part == "more":
        rnn_part([("bidirectional LSTM", lambda o: BiLSTM(o)),
                  ("GRU + attention", lambda o: LSTMAttention(o, cell="gru"))])
    elif part == "hybrid":
        rnn_part([("LSTM + attention", lambda o: LSTMAttention(o))])
    elif part == "seq":
        rnn_part([("transformer", lambda o: Transformer(o)), ("TCN", lambda o: TCN(o))])
    else:
        main()
