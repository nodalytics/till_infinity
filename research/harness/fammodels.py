"""Can a sequence model find what section one says is there - and is it worth anything?

`seqfamilies.py` characterises the generators. This file asks the question that
characterisation raises and cannot answer: **given that a family has internal
structure, does a model reading the sequence recover it, and does recovering it
survive the costs.** Those are two questions and `research/deriving.md`'s theorem
bears on the second only.

## The three targets, and why the third is the one worth having

* **`direction`** - the null calibration, exactly as it is on the Volatility
  arm. It should come back at 0.50 everywhere and anything else is a leak here
  before it is a finding. One caveat this family forces: **on Boom and Crash the
  base rate is not one half.** 99.8% of Boom 500's ticks are down moves; on a
  bar the sign is nearly a statement about whether a spike landed. An accuracy
  of 0.95 on that is a statement about the base rate, so this file reports AUC
  and never accuracy.
* **`logvol`** - and the interesting quantity is not the model score but the
  **naive-versus-mean gap**, which `seqlab.py`'s docstring names as a
  generator-identification statistic. On a process whose conditional variance is
  constant, the unconditional mean beats the last realised value; where variance
  clusters, the last value wins. That gap separates a compound Poisson from a
  regime-switching diffusion without fitting anything, and it is reported for
  every family beside the model scores.
* **`spike_next`** - **the family-specific target, and the only one of the three
  that could not have been asked on a Volatility index.** Did a spike land in
  the next bar. It is the tradeable form of section one's hazard question and it
  has an exact analytic floor, which is what makes it readable.

## The analytic floor on `spike_next`, which is the whole design

If the spike hazard is memoryless at per-tick probability `p`, then for a bar of
exactly `m` ticks

    P(spike in the next bar | anything at all) = 1 - (1 - p)^m

- a **constant**, independent of the entire history. A constant score has rank
  AUC exactly 0.500. So on a memoryless generator the Bayes-optimal classifier
  scores 0.500 and **any AUC above it is either non-memorylessness or a leak**,
  with no third option and no baseline to argue about.

That clean statement only holds on a bar of *exactly* `m` ticks, which is why
this file runs `spike_next` on tick bars and not on the wall clock.

## The confound the wall clock introduces, stated because it would otherwise be the result

On a three-minute bar the tick count varies. A bar with more ticks in it is more
likely to contain a spike **for a reason that has nothing to do with the hazard**,
and `logvolume` is in `seqlab.NAMES`, so a classifier on wall-clock bars can
score above 0.500 by reading the clock. That is real structure and it is not the
structure anyone is asking about. Tick bars remove it by construction - every
bar has the same `m` - and this file reports the wall-clock number beside the
tick-bar number precisely so the size of the confound is on the page rather than
in the headline.

## Where the timeframe destroys the object

Boom 500 spikes once per five hundred ticks on a one-second feed. A one-day bar
holds 86,400 ticks and therefore 173 spikes; "will a spike happen in the next
bar" has the answer yes, every time, and a classifier on it is scoring a
constant label. `census()` prints the expected spikes per bar at every timeframe
in `seqlab.GRID` and every cell outside roughly [0.05, 1.0] is reported as
destroyed rather than as a number.

## The controls, four deep on every cell

`shuffle` and `surrogate` from `seqlab`, plus a **family-appropriate simulated
null**: `compound_poisson_ticks` for Boom, Crash, DEX and Jump, `step_ticks` for
the Step family, `switch_bars` for Drift Switch. `seqlab.gbm_bars` is **not**
used anywhere in this file and that is deliberate - it is the right null for a
Volatility index and the wrong null for every symbol here, and a model that
separates Boom from a Brownian motion has identified the simulator.

    ./.secrets/lab.sh run research/harness/fammodels.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import numpy as np  # noqa: E402

from research.harness import seqfamilies as sf  # noqa: E402
from research.harness import seqlab  # noqa: E402

WORKERS = 4
OUT = Path.home() / "till_infinity" / "data" / "families"

#: Sequence length for the recurrent net, in bars. Thirty-two is long enough to
#: span several mean waits on a tick bar sized to a third of the nominal rate,
#: which is the window inside which a hazard would have to be visible.
SEQ = 32

#: Hidden width. Small on purpose: at 1d a Volatility-arm LSTM has more
#: parameters than samples, and the same is true here on the thin timeframes.
HID = 24

#: The recurrent budget, and it is a budget rather than a preference.
#:
#: The first smoke run was left to time itself and a single Boom cell - five
#: walk-forward folds at forty epochs over 15,789 tick bars, then four null
#: replicates of the same - had not finished in twenty minutes. Twenty-nine
#: spike symbols at that rate is two days on a box five other arms are sharing.
#:
#: So: at most `GRU_ROWS` training windows, drawn as a contiguous *tail* of the
#: training block rather than a random sample, because a walk-forward fold's
#: recent rows are the ones a real user would have and a random subsample would
#: quietly turn this into a non-causal design; `GRU_FOLDS` folds rather than
#: five, taken as the **last** folds, which are the ones with the most training
#: history; and `EPOCHS` sweeps. Everything the net is compared against - the
#: logistic baseline, the base rate, the null arm - runs on the identical rows,
#: so the budget costs power and not fairness.
GRU_ROWS = 6_000
GRU_FOLDS = 2
EPOCHS = 15

#: Wall-clock timeframes the model arm runs on. Not all eight - `seqlab.GRID`'s
#: low end is where the sample lives and its high end is where a Drift Switch
#: dwell time is a handful of bars. Each arm states which it uses and why.
DIR_TF = ("15m", "1h", "4h", "1d")


def _torch():
    import torch
    torch.set_num_threads(2)
    return torch


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------


def ridge_fit(x: np.ndarray, y: np.ndarray, lam: float = 1.0) -> np.ndarray:
    """Ridge by normal equations. The cheap baseline that has to be beaten.

    `research/models.md` found a linear model beating trees, forests, cosine
    similarity and an MLP on this project's other classification problem, so
    this is the baseline with a record rather than the baseline that was easy.
    """
    xm, xs = x.mean(axis=0), x.std(axis=0)
    xs = np.where(xs > 1e-12, xs, 1.0)
    z = np.column_stack([(x - xm) / xs, np.ones(len(x))])
    a = z.T @ z + lam * np.eye(z.shape[1])
    a[-1, -1] -= lam
    w = np.linalg.solve(a, z.T @ y)
    return np.concatenate([w, xm, xs])


def ridge_apply(p: np.ndarray, x: np.ndarray) -> np.ndarray:
    k = x.shape[1]
    w, xm, xs = p[: k + 1], p[k + 1 : 2 * k + 1], p[2 * k + 1 :]
    return np.column_stack([(x - xm) / xs, np.ones(len(x))]) @ w


def logistic_fit(x: np.ndarray, y: np.ndarray, *, lam: float = 1.0,
                 iters: int = 250, lr: float = 0.35) -> np.ndarray:
    xm, xs = x.mean(axis=0), x.std(axis=0)
    xs = np.where(xs > 1e-12, xs, 1.0)
    z = np.column_stack([(x - xm) / xs, np.ones(len(x))])
    w = np.zeros(z.shape[1])
    n = len(z)
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(z @ w, -30, 30)))
        g = z.T @ (p - y) / n + lam * np.concatenate([w[:-1], [0.0]]) / n
        w -= lr * g
    return np.concatenate([w, xm, xs])


def logistic_apply(p: np.ndarray, x: np.ndarray) -> np.ndarray:
    return ridge_apply(p, x)


def windows(x: np.ndarray, seq: int) -> np.ndarray:
    """`(n - seq + 1, seq, features)` - row `i` ends at `i + seq - 1`, never past it."""
    n, k = x.shape
    if n < seq:
        return np.zeros((0, seq, k), dtype=np.float32)
    stride = x.strides
    return np.lib.stride_tricks.as_strided(
        x, shape=(n - seq + 1, seq, k), strides=(stride[0], stride[0], stride[1])
    ).astype(np.float32)


def gru_budget(tr: np.ndarray, folds: list) -> np.ndarray:
    """The tail of a training block, capped at `GRU_ROWS`. Contiguous and causal."""
    return tr[-GRU_ROWS:] if len(tr) > GRU_ROWS else tr


def gru_folds(folds: list) -> list:
    """The last `GRU_FOLDS` walk-forward folds - the ones with the most history."""
    return folds[-GRU_FOLDS:] if len(folds) > GRU_FOLDS else folds


def gru_score(xtr: np.ndarray, ytr: np.ndarray, xte: np.ndarray, *,
              task: str = "binary", seed: int = 5) -> np.ndarray:
    """A small GRU on the raw sequence. Torch, CPU, two threads.

    `groundgru.py` hand-wrote its own because the lab had no torch. It has
    torch 2.14.0+cpu now, so this uses `nn.GRU` and the hand-written one stays
    where it is - two implementations of one object in one study is how the two
    volatility conventions got mixed in `research/forecasting.md`.
    """
    torch = _torch()
    torch.manual_seed(seed)
    mu, sd = xtr.reshape(-1, xtr.shape[-1]).mean(0), xtr.reshape(-1, xtr.shape[-1]).std(0)
    sd = np.where(sd > 1e-9, sd, 1.0)
    a = torch.from_numpy(((xtr - mu) / sd).astype(np.float32))
    b = torch.from_numpy(((xte - mu) / sd).astype(np.float32))
    t = torch.from_numpy(ytr.astype(np.float32))

    gru = torch.nn.GRU(xtr.shape[-1], HID, batch_first=True)
    head = torch.nn.Linear(HID, 1)
    params = list(gru.parameters()) + list(head.parameters())
    opt = torch.optim.Adam(params, lr=6e-3)
    loss_fn = torch.nn.BCEWithLogitsLoss() if task == "binary" else torch.nn.MSELoss()
    n = len(a)
    batch = min(512, max(32, n // 8))
    for _ in range(EPOCHS):
        perm = torch.randperm(n)
        for i in range(0, n, batch):
            idx = perm[i : i + batch]
            opt.zero_grad()
            out, _ = gru(a[idx])
            pred = head(out[:, -1, :]).squeeze(-1)
            loss = loss_fn(pred, t[idx])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 2.0)
            opt.step()
    with torch.no_grad():
        chunks = []
        for i in range(0, len(b), 4096):
            out, _ = gru(b[i : i + 4096])
            chunks.append(head(out[:, -1, :]).squeeze(-1).numpy())
    return np.concatenate(chunks) if chunks else np.zeros(0)


# --------------------------------------------------------------------------
# The spike arm - tick bars, the family target, and an analytic floor
# --------------------------------------------------------------------------


def census(symbol: str, per_spike: float) -> dict[str, float]:
    """Expected spikes per bar at every timeframe in `seqlab.GRID`.

    Kill condition 6 lives here: outside roughly [0.05, 1.0] the next-bar spike
    question has stopped being a question, and a number taken from such a cell
    is withdrawn rather than reported.
    """
    secs = {"3m": 180, "15m": 900, "1h": 3600, "4h": 14400, "6h": 21600,
            "8h": 28800, "12h": 43200, "1d": 86400}
    return {tf: float(n / max(per_spike, 1e-9)) for tf, n in secs.items()}


def _spike_bars(price: np.ndarray, idx: np.ndarray, per: int) -> dict:
    """Tick bars of `per` ticks, with the spike label and the hazard feature.

    `elapsed` is ticks since the last spike **as of the end of the bar**, which
    is a function of bars <= t; the label is whether a spike lands in bar t+1,
    which is a function of bars > t. The two never touch.
    """
    n = len(price) // per
    if n < 200:
        return {}
    bars = seqlab.bars_from_ticks(np.arange(len(price), dtype=float), price, per)
    hit = np.zeros(len(price), dtype=bool)
    hit[np.minimum(idx + 1, len(price) - 1)] = True   # idx indexes moves, not ticks
    per_bar = hit[: n * per].reshape(n, per).sum(axis=1)
    label = np.full(n, np.nan)
    label[: n - 1] = (per_bar[1:] > 0).astype(float)

    elapsed = np.empty(len(price))
    last = -1
    for i in range(len(price)):
        if hit[i]:
            last = i
        elapsed[i] = i - last if last >= 0 else i
    end = elapsed[: n * per].reshape(n, per)[:, -1]
    return {"bars": bars, "label": label, "count": per_bar.astype(float),
            "elapsed": end, "n": n}


def _spike_cell(price: np.ndarray, per: int, rng, *, tag: str, do_gru: bool) -> dict:
    """One (series, bar size) cell: build, split walk-forward, score every model."""
    moves = np.diff(price)
    det = seqlab.spikes(moves, 10.0)
    if det["n_spikes"] < 40:
        return {"tag": tag, "skip": f"{det['n_spikes']} spikes"}
    built = _spike_bars(price, det["idx"], per)
    if not built:
        return {"tag": tag, "skip": "too few bars"}

    x, names = seqlab.build(built["bars"])
    # The hazard feature, which is the whole point on this target: if the wait
    # is memoryless it carries nothing, and that is the measurement.
    extra = np.column_stack([
        built["elapsed"] / max(det["per_spike"], 1e-9),
        np.log1p(built["elapsed"]),
        built["count"],
    ])
    x = np.column_stack([x, extra])
    y = built["label"]
    ok = seqlab.usable(x, y)
    if ok.sum() < 400:
        return {"tag": tag, "skip": f"{int(ok.sum())} usable rows"}
    xo, yo = x[ok], y[ok]
    base = float(yo.mean())
    if base < 0.01 or base > 0.99:
        return {"tag": tag, "skip": f"base rate {base:.3f}"}

    # The recurrent net reads the sequence, not the engineered row.
    seq_src = np.column_stack([
        np.nan_to_num(xo[:, names.index("ret")]),
        np.abs(np.nan_to_num(xo[:, names.index("ret")])),
        np.nan_to_num(xo[:, names.index("logrange")]),
        xo[:, len(names)],           # elapsed / nominal
    ])

    folds = seqlab.walk_forward(len(xo), folds=5, horizon=1)
    keep = {id(f) for f in gru_folds(folds)}
    wtr = windows(seq_src, SEQ) if do_gru else None
    got = {"logistic": [], "logistic_nohaz": [], "gru": []}
    for fold in folds:
        tr, te = fold
        if yo[tr].std() < 1e-9 or yo[te].std() < 1e-9:
            continue
        w = logistic_fit(xo[tr], yo[tr])
        got["logistic"].append(seqlab.auc(logistic_apply(w, xo[te]), yo[te]))
        # The same model with the hazard columns removed - so a score can be
        # attributed to the hazard rather than to the feature set at large.
        cut = xo[:, : len(names)]
        w2 = logistic_fit(cut[tr], yo[tr])
        got["logistic_nohaz"].append(seqlab.auc(logistic_apply(w2, cut[te]), yo[te]))
        if do_gru and id(fold) in keep:
            off = SEQ - 1
            tr2 = gru_budget(tr[tr >= off] - off, folds)
            te2 = te[te >= off] - off
            if len(tr2) > 200 and len(te2) > 60 and yo[tr2 + off].std() > 1e-9:
                s = gru_score(wtr[tr2], yo[tr2 + off], wtr[te2], task="binary")
                got["gru"].append(seqlab.auc(s, yo[te2 + off]))

    out = {"tag": tag, "per": per, "rows": int(ok.sum()), "base_rate": base,
           "n_spikes": det["n_spikes"], "per_spike": det["per_spike"],
           "folds": len(folds)}
    for k, v in got.items():
        v = [q for q in v if np.isfinite(q)]
        out[k] = float(np.mean(v)) if v else float("nan")
        out[f"{k}_n"] = len(v)
    return out


def spike_arm(symbol: str, seed: int = 23, replicates: int = 24) -> dict:
    """`spike_next` on tick bars, with the memoryless null as the floor.

    The null arm is the load-bearing row. It is the identical pipeline on a
    series whose hazard is memoryless by construction and whose marginals match
    the feed exactly, so whatever it scores is what this harness reads when
    there is nothing to read - and `research/grounding.md`'s arm B was voided by
    exactly this check, its own floor at 0.5210 being wider than the effect it
    was testing for.
    """
    rng = np.random.default_rng(seed)
    ticks = seqlab.tick_cache(symbol)
    if len(ticks.get("time", ())) < 20_000:
        return {"symbol": symbol, "skip": f"{len(ticks.get('time', ()))} ticks"}
    price = sf._bid(ticks)
    moves = np.diff(price)
    det = seqlab.spikes(moves, 10.0)
    if det["n_spikes"] < 40:
        return {"symbol": symbol, "skip": f"{det['n_spikes']} spikes"}

    row: dict = {"symbol": symbol, "family": seqlab.FAMILY_OF.get(symbol, "?"),
                 "n_ticks": len(price), "n_spikes": det["n_spikes"],
                 "per_spike": det["per_spike"], "nominal": sf.nominal(symbol),
                 "census": census(symbol, det["per_spike"])}

    # A bar of a third of the mean wait, so the label lands near 0.28 and the
    # question is well posed on every member of a family whose members differ
    # by a factor of twenty in rate - **but not if that leaves no bars.** Boom
    # 1000 waits eleven hundred ticks, so a third of it is a 367-tick bar and
    # 300,000 ticks is 817 of them, at which an AUC has a standard error of
    # 0.03 and the arm cannot see anything it is looking for. Where the two
    # constraints collide the bar count wins and the base rate is reported, so
    # a thin cell reads as thin rather than as null.
    per = max(int(round(det["per_spike"] / 3.0)), 4)
    per = max(min(per, len(price) // 4_000), 4)
    row["ticks_per_bar"] = per
    row["real"] = _spike_cell(price, per, rng, tag="real", do_gru=True)

    # Control 1: the target permuted. Catches a model reading the answer.
    built = _spike_bars(price, det["idx"], per)
    row["shuffle"] = {}
    if built:
        x, names = seqlab.build(built["bars"])
        y = seqlab.shuffle_target(built["label"], rng)
        ok = seqlab.usable(x, y)
        if ok.sum() > 400:
            xo, yo = x[ok], y[ok]
            sc = []
            for tr, te in seqlab.walk_forward(len(xo), folds=5, horizon=1):
                if yo[tr].std() < 1e-9 or yo[te].std() < 1e-9:
                    continue
                w = logistic_fit(xo[tr], yo[tr])
                sc.append(seqlab.auc(logistic_apply(w, xo[te]), yo[te]))
            row["shuffle"] = {"logistic": float(np.nanmean(sc)) if sc else float("nan"),
                              "n": len(sc)}

    # Control 2: phase surrogate of the increments. Keeps the spectrum, kills
    # the nonlinear dependence - and on a spike process it also destroys the
    # spike, which is the point: there is nothing left to find.
    surr = 1000.0 + np.cumsum(seqlab.phase_surrogate(moves, rng))
    row["surrogate"] = _spike_cell(surr, per, rng, tag="surrogate", do_gru=False)

    # Control 3: the family null. Memoryless by construction, marginals exact.
    p_hat = det["n_spikes"] / det["n_moves"]
    draws = {"logistic": [], "logistic_nohaz": [], "gru": []}
    for i in range(replicates):
        sim = seqlab.compound_poisson_ticks(det["grind"], det["spike"], p_hat,
                                            min(len(price), 300_000), rng)
        cell = _spike_cell(sim, per, rng, tag="null", do_gru=(i < 3))
        for k in draws:
            v = cell.get(k, float("nan"))
            if np.isfinite(v):
                draws[k].append(v)
    row["null"] = {}
    for k, v in draws.items():
        if len(v) < 4:
            row["null"][k] = {"mean": float("nan"), "sd": float("nan"), "n": len(v)}
            continue
        arr = np.asarray(v, float)
        obs = row["real"].get(k, float("nan"))
        row["null"][k] = {
            "mean": float(arr.mean()), "sd": float(arr.std(ddof=1)), "n": len(arr),
            "max": float(arr.max()),
            "z": float((obs - arr.mean()) / max(arr.std(ddof=1), 1e-12)) if np.isfinite(obs) else float("nan"),
            "p_max_of_k": seqlab.max_of_k(obs, arr) if np.isfinite(obs) else float("nan"),
        }
    return row


# --------------------------------------------------------------------------
# The direction and volatility arm, on wall-clock bars
# --------------------------------------------------------------------------


def bar_arm(symbol: str, interval: str, seed: int = 29) -> dict:
    """`direction` and `logvol` on the shared bar layer, with the naive-mean gap.

    The Drift Switch members get one extra model here - the causal HMM filter -
    because it is the one family in the book whose name says a hidden state
    exists, and a filter is the instrument built for that shape. Everywhere else
    it would be a model looking for a state that is not there, which is exactly
    what kill condition 5 is written to catch.
    """
    rng = np.random.default_rng(seed)
    try:
        bars = seqlab.load(symbol, interval)
    except Exception as exc:  # noqa: BLE001
        return {"symbol": symbol, "interval": interval, "skip": str(exc)[:70]}
    fam = seqlab.FAMILY_OF.get(symbol, "?")
    x, names = seqlab.build(bars)
    y = seqlab.targets(bars, horizon=1)
    row: dict = {"symbol": symbol, "family": fam, "interval": interval,
                 "n_bars": len(bars["close"])}

    # --- logvol, and the generator-identification statistic -----------------
    okv = seqlab.usable(x, y["logvol"])
    if okv.sum() > 400:
        rv = y["realised"][okv]
        prev = x[okv][:, names.index("rv1")]
        row["vol"] = {
            "rows": int(okv.sum()),
            "naive_srel": seqlab.srel(prev, rv),
            "mean_srel": seqlab.srel(np.full(len(rv), float(rv.mean())), rv),
        }
        row["vol"]["naive_minus_mean"] = row["vol"]["naive_srel"] - row["vol"]["mean_srel"]
        xv, yv = x[okv], y["logvol"][okv]
        har_i = [names.index(k) for k in ("rv1", "rv5", "rv22")]
        sc_har, sc_ridge, sc_naive = [], [], []
        for tr, te in seqlab.walk_forward(len(xv), folds=5, horizon=1):
            with np.errstate(divide="ignore", invalid="ignore"):
                h = np.log(np.maximum(xv[:, har_i], 1e-12))
            good_tr = np.isfinite(h[tr]).all(axis=1)
            if good_tr.sum() < 100:
                continue
            p = ridge_fit(h[tr][good_tr], yv[tr][good_tr], lam=1.0)
            sc_har.append(seqlab.srel(np.exp(ridge_apply(p, h[te])), y["realised"][okv][te]))
            p2 = ridge_fit(xv[tr], yv[tr], lam=10.0)
            sc_ridge.append(seqlab.srel(np.exp(ridge_apply(p2, xv[te])), y["realised"][okv][te]))
            sc_naive.append(seqlab.srel(xv[te][:, names.index("rv1")], y["realised"][okv][te]))
        for k, v in (("har_srel", sc_har), ("ridge_srel", sc_ridge), ("naive_wf_srel", sc_naive)):
            v = [q for q in v if np.isfinite(q)]
            row["vol"][k] = float(np.mean(v)) if v else float("nan")

    # --- direction -----------------------------------------------------------
    okd = seqlab.usable(x, y["direction"])
    if okd.sum() > 400:
        xd, yd = x[okd], y["direction"][okd]
        r = np.diff(np.log(bars["close"]))
        row["dir"] = {"rows": int(okd.sum()), "base_rate": float(yd.mean())}
        arms: dict[str, list] = {"logistic": [], "momentum": [], "hmm": []}
        ctrl: dict[str, list] = {"shuffle": [], "surrogate": []}
        ysh = seqlab.shuffle_target(yd, rng)
        for tr, te in seqlab.walk_forward(len(xd), folds=5, horizon=1):
            if yd[tr].std() < 1e-9 or yd[te].std() < 1e-9:
                continue
            w = logistic_fit(xd[tr], yd[tr])
            arms["logistic"].append(seqlab.auc(logistic_apply(w, xd[te]), yd[te]))
            arms["momentum"].append(seqlab.auc(xd[te][:, names.index("runlen")], yd[te]))
            w3 = logistic_fit(xd[tr], ysh[tr])
            ctrl["shuffle"].append(seqlab.auc(logistic_apply(w3, xd[te]), ysh[te]))
            if fam == "drift_switch":
                ret_tr = np.nan_to_num(xd[tr][:, names.index("ret")])
                fit = sf.fit_hmm(ret_tr, 2, seed=seed)
                if fit["ok"]:
                    filt = sf.hmm_filter(np.nan_to_num(xd[te][:, names.index("ret")]), fit)
                    arms["hmm"].append(seqlab.auc(filt, yd[te]))
        # The surrogate arm is a whole rebuild of the series, not a re-score.
        sur = 1000.0 * np.exp(np.cumsum(seqlab.phase_surrogate(r, rng)))
        sb = seqlab.bars_from_ticks(np.arange(len(sur), dtype=float), sur, 1)
        if len(sb.get("close", ())) > 500:
            xs, _ = seqlab.build(sb)
            ys = seqlab.targets(sb, horizon=1)["direction"]
            oks = seqlab.usable(xs, ys)
            if oks.sum() > 400:
                xs, ys = xs[oks], ys[oks]
                for tr, te in seqlab.walk_forward(len(xs), folds=5, horizon=1):
                    if ys[tr].std() < 1e-9 or ys[te].std() < 1e-9:
                        continue
                    w = logistic_fit(xs[tr], ys[tr])
                    ctrl["surrogate"].append(seqlab.auc(logistic_apply(w, xs[te]), ys[te]))
        for d, dest in ((arms, "dir"), (ctrl, "dir")):
            for k, v in d.items():
                v = [q for q in v if np.isfinite(q)]
                row[dest][k] = float(np.mean(v)) if v else float("nan")
                row[dest][f"{k}_n"] = len(v)
    return row


def drift_model_arm(symbol: str, interval: str, seed: int = 31) -> dict:
    """Drift Switch at full depth: HMM filter, GRU and momentum on one split.

    This family gets the recurrent net because it is the one family here where a
    recurrent net has a legitimate job - inferring a hidden regime is exactly
    what a hidden state is for. Everywhere else in this book the net is looking
    for a state the generator does not have.
    """
    rng = np.random.default_rng(seed)
    try:
        bars = seqlab.load(symbol, interval)
    except Exception as exc:  # noqa: BLE001
        return {"symbol": symbol, "interval": interval, "skip": str(exc)[:70]}
    x, names = seqlab.build(bars)
    y = seqlab.targets(bars, horizon=1)
    ok = seqlab.usable(x, y["direction"])
    if ok.sum() < 600:
        return {"symbol": symbol, "interval": interval, "skip": f"{int(ok.sum())} rows"}
    xo, yo = x[ok], y["direction"][ok]
    r = np.nan_to_num(xo[:, names.index("ret")])
    row = {"symbol": symbol, "interval": interval, "family": "drift_switch",
           "rows": int(ok.sum()), "base_rate": float(yo.mean())}

    def run(series_r: np.ndarray, labels: np.ndarray, tag: str, do_gru: bool) -> dict:
        src = np.column_stack([series_r, np.abs(series_r),
                               np.nan_to_num(seqlab._roll_mean(series_r, 22)),
                               np.nan_to_num(seqlab._roll_std(series_r, 22))])
        out = {"hmm": [], "gru": [], "mom22": []}
        all_folds = seqlab.walk_forward(len(labels), folds=5, horizon=1)
        keep = {id(f) for f in gru_folds(all_folds)}
        for fold in all_folds:
            tr, te = fold
            if labels[tr].std() < 1e-9 or labels[te].std() < 1e-9:
                continue
            fit = sf.fit_hmm(series_r[tr], 2, seed=seed)
            if fit["ok"]:
                out["hmm"].append(seqlab.auc(sf.hmm_filter(series_r[te], fit), labels[te]))
            m = np.nan_to_num(seqlab._roll_mean(series_r, 22))
            out["mom22"].append(seqlab.auc(m[te], labels[te]))
            if do_gru and id(fold) in keep:
                w = windows(np.nan_to_num(src), SEQ)
                off = SEQ - 1
                tr2 = gru_budget(tr[tr >= off] - off, all_folds)
                te2 = te[te >= off] - off
                if len(tr2) > 200 and len(te2) > 60 and labels[tr2 + off].std() > 1e-9:
                    s = gru_score(w[tr2], labels[tr2 + off], w[te2], task="binary")
                    out["gru"].append(seqlab.auc(s, labels[te2 + off]))
        res = {"tag": tag}
        for k, v in out.items():
            v = [q for q in v if np.isfinite(q)]
            res[k] = float(np.mean(v)) if v else float("nan")
            res[f"{k}_n"] = len(v)
        return res

    row["real"] = run(r, yo, "real", True)
    row["shuffle"] = run(r, seqlab.shuffle_target(yo, rng), "shuffle", True)
    sur = seqlab.phase_surrogate(r, rng)
    row["surrogate"] = run(sur, (np.concatenate([sur[1:], [0.0]]) > 0).astype(float),
                           "surrogate", True)

    # The family null, with the state path known - so this is both the floor and
    # the positive control. If the filter cannot read a regime it was handed,
    # a null result on the feed is a statement about the filter.
    fit = sf.fit_hmm(r, 2, seed=seed)
    if fit["ok"]:
        sim = seqlab.switch_bars(np.asarray(fit["mu"]), np.asarray(fit["sigma"]),
                                 np.asarray(fit["trans"]), len(r), rng)
        lab = np.concatenate([(sim["ret"][1:] > 0).astype(float), [np.nan]])
        good = np.isfinite(lab)
        row["null_switch"] = run(sim["ret"][good], lab[good], "null_switch", True)
        row["null_switch"]["true_dwell"] = fit["dwell"]
        row["null_switch"]["true_persist"] = fit["persist"]
        row["null_switch"]["fitted_sep"] = fit["sep"]
        # And the same generator with the drift removed - two states that differ
        # only in sigma. A filter that still scores 0.5 there has correctly
        # refused to call direction off a variance regime.
        flat = seqlab.switch_bars(np.zeros(2), np.asarray(fit["sigma"]),
                                  np.asarray(fit["trans"]), len(r), rng)
        lab2 = np.concatenate([(flat["ret"][1:] > 0).astype(float), [np.nan]])
        g2 = np.isfinite(lab2)
        row["null_volonly"] = run(flat["ret"][g2], lab2[g2], "null_volonly", False)
    return row


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def _job(spec) -> dict:
    kind, symbol, interval = spec
    began = time.time()
    try:
        if kind == "spike":
            out = spike_arm(symbol)
        elif kind == "bar":
            out = bar_arm(symbol, interval)
        else:
            out = drift_model_arm(symbol, interval)
    except Exception as exc:  # noqa: BLE001
        out = {"symbol": symbol, "interval": interval,
               "error": f"{type(exc).__name__}: {exc}"[:200]}
    out["kind"] = kind
    out["secs"] = round(time.time() - began, 1)
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    for fam in ("boom", "crash", "dex", "jump"):
        jobs += [("spike", s, "tick") for s in seqlab.SYNTHETIC[fam]]
    for fam, syms in sorted(seqlab.SYNTHETIC.items()):
        for s in syms:
            for tf in DIR_TF:
                jobs.append(("bar", s, tf))
    for s in seqlab.SYNTHETIC["drift_switch"]:
        for tf in ("15m", "1h", "4h"):
            jobs.append(("drift", s, tf))

    print(f"fammodels - {len(jobs)} cells, {WORKERS} workers at 2 threads each")
    print(f"  spike arm: {sum(j[0]=='spike' for j in jobs)}   "
          f"bar arm: {sum(j[0]=='bar' for j in jobs)}   "
          f"drift arm: {sum(j[0]=='drift' for j in jobs)}\n", flush=True)

    began = time.time()
    rows = []
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_job, j): j for j in jobs}
        for i, future in enumerate(as_completed(futures), 1):
            row = future.result()
            rows.append(row)
            tag = row.get("error") or row.get("skip") or ""
            extra = ""
            if row["kind"] == "spike" and "real" in row and "logistic" in row["real"]:
                rl, nl = row["real"], row.get("null", {})
                extra = (f"per={row['ticks_per_bar']} base {rl['base_rate']:.3f}  "
                         f"logit {rl['logistic']:.4f} (null {nl.get('logistic',{}).get('mean',float('nan')):.4f}"
                         f"+-{nl.get('logistic',{}).get('sd',float('nan')):.4f}, "
                         f"z{nl.get('logistic',{}).get('z',float('nan')):+.1f})  "
                         f"nohaz {rl['logistic_nohaz']:.4f}  gru {rl['gru']:.4f}")
            elif row["kind"] == "bar" and "dir" in row:
                d, v = row["dir"], row.get("vol", {})
                extra = (f"{row['interval']:>3s} dir {d.get('logistic',float('nan')):.4f} "
                         f"(sh {d.get('shuffle',float('nan')):.4f} su {d.get('surrogate',float('nan')):.4f})"
                         f"  vol naive-mean {v.get('naive_minus_mean',float('nan')):+.4f}")
            elif row["kind"] == "drift" and "real" in row:
                r_, n_ = row["real"], row.get("null_switch", {})
                extra = (f"{row['interval']:>3s} hmm {r_.get('hmm',float('nan')):.4f} "
                         f"gru {r_.get('gru',float('nan')):.4f} mom {r_.get('mom22',float('nan')):.4f} "
                         f"| null-switch hmm {n_.get('hmm',float('nan')):.4f}")
            print(f"  {i:3d}/{len(jobs)} {row['symbol']:24s} {extra} {tag}", flush=True)

    path = OUT / "models.json"
    path.write_text(json.dumps(sf._clean(rows), indent=1))
    print(f"\ndone in {(time.time()-began)/60:.1f}m -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
