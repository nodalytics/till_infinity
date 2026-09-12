"""Recurrent nets on the Volatility family: a null calibration and one real question.

**The direction arm on this page is a calibration, not a hunt, and it is written
that way on purpose.** `research/deriving.md` proves `E[net] = -(c/2) x turnover`
for any predictable position on a martingale, `research/rebuilding.md` confirmed
it empirically on these feeds - boosted models on tick windows, k-tuples and bar
OHLC, `n*` infinite on every arm - and a Volatility index is geometric Brownian
motion at a published constant sigma, whose increments are independent by
construction. There is no direction edge here to find. If an LSTM on this page
reports one, **the first hypothesis is a leak in this file**, and the second is
a defect in the feed worth chasing for what it says about the generator. It is
not a trade. That ordering is the whole reason the controls below outnumber the
models.

The open question is **magnitude**. `seqlab.main()` already put the sharp
version of it on the table: on `Volatility 75 Index` 1h, the naive forecaster
(last realised) scores srel 0.8802 against the unconditional mean's 0.6691 - and
a *simulated* GBM at the same sigma scores 0.8809 / 0.6642. The two are the same
number to three decimals. On a market with volatility clustering the naive
forecaster wins; here it loses to a constant, exactly as it loses on a series
with no clustering in it at all. **That is a generator-identification statistic,
not a forecasting result**, and this arm's job is to find out whether a
recurrent net - which can express state that a rolling window cannot - sees
anything the constant does not.

The prediction, written before the run: **it cannot, on the twenty constant-sigma
members.** The two interesting symbols are `seqlab.SPOT_UP`, whose names say the
variance moves.

## Kill conditions, stated before any number was read

1. **The harness is wrong** if the window alignment test fails. A window ending
   at row `t` must contain feature row `t` as its last element and nothing
   later. This is asserted on every single call to `windows()`, not in a test
   file, because an off-by-one here puts bar `t+1` inside the window and the
   target is a function of bar `t+1`. Every "recurrent nets beat everything"
   result this desk has ever seen elsewhere is that off-by-one.

2. **The harness is wrong** if the injected-leak probe does not fire. `probe`
   deliberately appends the target as a 29th feature and requires AUC > 0.95 and
   logvol R^2 > 0.95. A null result from a pipeline that cannot detect a signal
   handed to it directly is a statement about the pipeline. This is the positive
   control for the machinery, and it runs before any real number.

3. **The result is not reportable** if the `gbm` control scores differently from
   the real series by more than the spread between folds. `gbm` is a simulated
   Volatility index at the symbol's own sigma - the known null, where the true
   answer is exactly 0.50 and R^2 exactly 0. If the net separates the feed from
   its own simulated null, either the sigma is wrong or the feed is not what its
   name says, and both of those are findings that outrank any score.

4. **A direction AUC is not an edge** unless it survives `max_of_k` across the
   whole family. 22 symbols x 8 timeframes x 3 architectures is 528 chances to
   see 0.53, and the best of 528 fair coins clears 0.53 routinely. A per-test
   p-value on this grid is how a research folder fills with findings that do not
   replicate. The family-wise number is computed two ways - parametric, from
   each cell's own null standard error, and empirical, by resampling the control
   cells - and both are reported.

5. **A net that loses to a straight line is the finding**, and it is reported as
   one rather than dropped. Three baselines run on **identical rows** in every
   fold: the unconditional mean of the training block, the naive last-realised
   value, and a HAR regression on `rv1`/`rv5`/`rv22`. `research/forecasting.md`
   already found that a learned model beat HAR in all eight cells and both lost
   to naive in eleven of twelve; a recurrent net that cannot clear those three
   has not earned the sentence "sequence models find nothing here", it has
   earned "this sequence model finds less than a line".

6. **A score at 1d means nothing and is labelled so in the output.** 1h holds
   50,000 bars; 1d holds under three thousand. An LSTM at hidden 64 has 24,000
   parameters against roughly 1,800 training windows. Every record on this page
   carries `params` and `n_train`, and `overparam` is true wherever the first
   exceeds the second. A table that prints a 1d LSTM's R^2 beside a 1h one
   without that flag is comparing a fit to a memorisation.

   **This condition fired against the study's own selection rule and the rule
   lost.** The sweep's validation-selected geometry - hidden 64, sequence length
   32 - is overparameterised at *every* cell, not only at 1d, because
   `MAX_TRAIN` caps a fold's training block at 12,000 windows and the densest
   cell in the grid trains on 10,927. `grid_config` therefore runs the grid at
   hidden 32, sequence length 16, records the override on every record, and
   leaves the validation-selected geometry's answer where the sweep measured
   it. A capacity rule written down before any number was read is allowed to
   override a selection rule written down before any number was read; a score
   is not.

## What would falsify the negative result

Not "we ran a net and it scored zero". The claim this page makes is *the feed has
no forecastable volatility structure at these timeframes*, and the thing that
would falsify it is the positive control: `seqlab.REAL` - gold, the majors,
bitcoin - run through exactly this code, exactly these folds, exactly this
architecture. Volatility clustering on XAUUSD is a fact. If this harness cannot
find it there, then "we found nothing on the synthetics" is a statement about
the harness and is withdrawn. The `real` stage exists for that and for nothing
else, and it is not optional.

## The four variants every headline number carries

* **`real`** - the feed.
* **`shuffle`** - `seqlab.shuffle_target`. Targets permuted. Catches a model
  reading the answer back through the feature matrix.
* **`surrogate`** - `seqlab.surrogate_bars`, phase-randomised returns rebuilt
  into bars through a Brownian bridge. Keeps the return spectrum and the full
  linear autocorrelation exactly, destroys every nonlinear dependence.
* **`gbm`** - `seqlab.gbm_bars` at `seqlab.NAMED_SIGMA` where the name publishes
  one and `seqlab.measured_sigma` where it does not. The exact null.

## The split, and why validation is carved from the end

Folds are `seqlab.walk_forward`: expanding, never shuffled, with a purge of
`horizon` bars between train and test. Early stopping needs a validation slice
and **it is taken from the end of the training block, never at random**. A random
validation slice on a time series lets the net stop on rows it is interleaved
with, which reports the training loss twice and calls the second one validation.
The same `horizon` purge is applied between the sub-train and the validation
slice for the same reason it is applied before the test block.

Feature scaling is fit on the training rows alone and applied forward. Values are
clipped at +-8 sigma after scaling: a tanh RNN fed an unclipped `z22` outlier
saturates for the rest of the sequence, which is a numerical failure that looks
like a modelling result.

## Threads

`torch.set_num_threads(8)` at module scope, as commissioned - five other agents
share this box. The fan-out below is `WORKERS` processes each pinned to **one**
torch thread, so the total is eight cores either way; a recurrent net on a
(256, 32, 28) batch does not scale past one thread, and eight one-thread
processes finish this grid roughly six times faster than one eight-thread
process does. The cap is on cores, and the cap is respected.

    ./.secrets/lab.sh run research/harness/seqnets.py MODE=probe
    ./.secrets/lab.sh run research/harness/seqnets.py MODE=sweep
    ./.secrets/lab.sh run research/harness/seqnets.py MODE=grid
    ./.secrets/lab.sh run research/harness/seqnets.py MODE=real
"""

from __future__ import annotations

import json
import math
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import torch
from numpy.lib.stride_tricks import sliding_window_view
from torch import nn

from research.harness import seqlab

torch.set_num_threads(8)

#: Where records land. One JSON per stage, so the page can be rebuilt from disk
#: without re-running anything.
OUT = Path.home() / "till_infinity" / "data" / "seqnets"

#: Eight processes, one torch thread each. See the docstring's Threads section.
WORKERS = int(os.environ.get("WORKERS", "8"))

ARCHS = ("lstm", "gru", "rnn")
HIDDEN = (8, 16, 32, 64)
SEQLENS = (8, 16, 32, 64)

#: Training budget. Sixty epochs with patience six is generous for a 28-feature
#: sequence and is never the binding constraint - on a null target the net stops
#: between epoch two and epoch eight, which is itself a readable signal.
EPOCHS = 60
PATIENCE = 6
BATCH = 256
LR = 1e-3
VAL_FRAC = 0.2
CLIP = 8.0

#: Cap on training windows per fold, stride-subsampled across the block rather
#: than truncated to the tail - an expanding-window fold that silently becomes a
#: rolling one is a different experiment. Both the cap and the number available
#: are recorded on every row so the subsampling is never invisible.
MAX_TRAIN = 12_000

#: Five folds everywhere, which the probe's timing made affordable: with
#: `MAX_TRAIN` capping the training block, an expanding fold costs the same as
#: the one before it rather than more, so the bill is linear in folds and not
#: quadratic. Five is what `seqlab.walk_forward` defaults to and what
#: `seqlab.main()` reported its naive-vs-mean numbers on, so the folds on this
#: page and the folds under that number are the same folds.
FOLDS_GRID = 5
FOLDS_SWEEP = 5

HORIZON = 1
VARIANTS = ("real", "shuffle", "surrogate", "gbm")

#: The cells the architecture sweep runs on, chosen to span the sample cliff
#: rather than to be representative: 1h is 50,000 bars, 1d is under 3,000, and
#: the two are not expected to want the same architecture.
ANCHORS = (
    ("Volatility 75 Index", "1h"),
    ("Volatility 75 Index", "1d"),
    ("Volatility 10 Index", "1h"),
    ("Spot Up - Volatility Up Index", "1h"),
)


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------


def windows(x: np.ndarray, seqlen: int) -> np.ndarray:
    """Sliding windows as a view: `w[i]` covers rows `i .. i+seqlen-1`.

    Position `t` in the feature block maps to window `t - (seqlen - 1)`, so the
    window **ends** at `t` and contains nothing after it. The assertion below is
    kill condition 1 and it runs on every call rather than in a test file,
    because it costs microseconds and the bug it catches invalidates the page.
    """
    if seqlen < 1 or len(x) < seqlen:
        raise seqlab.Thin(f"windows: {len(x)} rows < seqlen {seqlen}")
    w = sliding_window_view(x, seqlen, axis=0).transpose(0, 2, 1)
    probe = min(len(w) - 1, 7)
    assert np.array_equal(w[probe][-1], x[probe + seqlen - 1]), "window ends past its row"
    assert np.array_equal(w[probe][0], x[probe]), "window starts before its span"
    return w


def longest_run(mask: np.ndarray) -> tuple[int, int]:
    """The longest contiguous stretch of usable rows, as `[lo, hi)`.

    `seqlab.usable` returns a boolean mask, and a sequence model cannot step over
    a hole in it: a window spanning a dropped row silently concatenates two
    non-adjacent bars. In practice the mask is the warm-up prefix and the
    horizon tail and nothing else - 22 rows of 50,000 on the anchor - but taking
    the longest run and **recording how many rows that cost** is the difference
    between knowing that and assuming it.
    """
    m = np.asarray(mask, dtype=bool)
    best_lo = best_hi = lo = 0
    inside = False
    for i, v in enumerate(m):
        if v and not inside:
            lo, inside = i, True
        elif not v and inside:
            inside = False
            if i - lo > best_hi - best_lo:
                best_lo, best_hi = lo, i
    if inside and len(m) - lo > best_hi - best_lo:
        best_lo, best_hi = lo, len(m)
    return best_lo, best_hi


def prepare(bars: dict[str, np.ndarray], horizon: int = HORIZON) -> dict:
    """Features, targets and one common usable block.

    **One mask for every target, deliberately.** `direction` and `logvol` are
    scored on identical rows so the null calibration and the real question are
    never answered on different samples - a direction AUC that moves because its
    sample moved is unreadable beside a volatility R^2 that did not.
    """
    x, names = seqlab.build(bars)
    tg = seqlab.targets(bars, horizon)
    ok = np.isfinite(x).all(axis=1)
    for key in ("direction", "logvol", "realised"):
        ok &= np.isfinite(tg[key])
    lo, hi = longest_run(ok)
    n = hi - lo
    if n < seqlab.FEWEST:
        raise seqlab.Thin(f"usable block {n} < {seqlab.FEWEST}")
    return {
        "x": np.ascontiguousarray(x[lo:hi], dtype=np.float64),
        "t": {k: np.asarray(v[lo:hi], dtype=np.float64) for k, v in tg.items()},
        "names": names,
        "n": n,
        "rows_total": len(x),
        "rows_dropped": int(len(x) - n),
    }


# --------------------------------------------------------------------------
# The nets
# --------------------------------------------------------------------------


class Rec(nn.Module):
    """One recurrent layer and a linear head on the last hidden state.

    Small on purpose. These are 28-feature sequences of at most 32 steps, not
    language; a stacked net here would be more parameters chasing the same
    nothing, and kill condition 6 already has trouble with the parameter count
    at the top of the timeframe grid.
    """

    def __init__(self, kind: str, n_in: int, hidden: int) -> None:
        super().__init__()
        if kind == "lstm":
            self.rnn = nn.LSTM(n_in, hidden, batch_first=True)
        elif kind == "gru":
            self.rnn = nn.GRU(n_in, hidden, batch_first=True)
        elif kind == "rnn":
            self.rnn = nn.RNN(n_in, hidden, batch_first=True, nonlinearity="tanh")
        else:
            raise ValueError(f"unknown arch {kind}")
        self.head = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.rnn(x)
        return self.head(out[:, -1, :]).squeeze(-1)


def _batches(idx: np.ndarray, size: int):
    for i in range(0, len(idx), size):
        yield idx[i : i + size]


def fit_predict(
    win: np.ndarray,
    y: np.ndarray,
    train_pos: np.ndarray,
    val_pos: np.ndarray,
    test_pos: np.ndarray,
    *,
    kind: str,
    hidden: int,
    seqlen: int,
    task: str,
    seed: int,
) -> dict:
    """Train with early stopping on the tail-of-train validation slice, then predict.

    Gradients are norm-clipped at 1.0. That is not a tuning choice: a tanh RNN
    over 32 steps of a heavy-tailed feature produces gradients that are finite
    and enormous, and the resulting run has a loss curve, a validation score and
    no information in it. Clipping makes the vanilla RNN comparable to the gated
    architectures instead of being a study of exploding gradients.
    """
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = Rec(kind, win.shape[2], hidden)
    params = int(sum(p.numel() for p in model.parameters()))
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    lossfn = nn.BCEWithLogitsLoss() if task == "direction" else nn.MSELoss()

    off = seqlen - 1
    ytr = torch.from_numpy(y[train_pos].astype(np.float32))
    yva = torch.from_numpy(y[val_pos].astype(np.float32))

    def gather(pos: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(np.ascontiguousarray(win[pos - off], dtype=np.float32))

    xva = gather(val_pos)
    best_loss, best_state, bad, ran = float("inf"), None, 0, 0
    for epoch in range(EPOCHS):
        model.train()
        order = rng.permutation(len(train_pos))
        for chunk in _batches(order, BATCH):
            opt.zero_grad()
            out = model(gather(train_pos[chunk]))
            loss = lossfn(out, ytr[chunk])
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        model.eval()
        with torch.no_grad():
            vloss = float(lossfn(model(xva), yva))
        ran = epoch + 1
        if not math.isfinite(vloss):
            break
        if vloss < best_loss - 1e-6:
            best_loss = vloss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            bad = 0
        else:
            bad += 1
            if bad >= PATIENCE:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    preds = []
    with torch.no_grad():
        for chunk in _batches(np.arange(len(test_pos)), 4096):
            preds.append(model(gather(test_pos[chunk])).numpy())
        vpred = []
        for chunk in _batches(np.arange(len(val_pos)), 4096):
            vpred.append(model(gather(val_pos[chunk])).numpy())
    return {
        "test": np.concatenate(preds) if preds else np.zeros(0),
        "val": np.concatenate(vpred) if vpred else np.zeros(0),
        "params": params,
        "epochs": ran,
        "val_loss": best_loss,
    }


# --------------------------------------------------------------------------
# Baselines - fit on the same rows the net trains on
# --------------------------------------------------------------------------


def har_fit(rv1: np.ndarray, rv5: np.ndarray, rv22: np.ndarray, y: np.ndarray) -> np.ndarray:
    a = np.column_stack([
        np.ones(len(rv1)),
        np.log(np.maximum(rv1, 1e-12)),
        np.log(np.maximum(rv5, 1e-12)),
        np.log(np.maximum(rv22, 1e-12)),
    ])
    ok = np.isfinite(a).all(axis=1) & np.isfinite(y)
    if ok.sum() < 10:
        return np.array([np.nanmean(y), 0.0, 0.0, 0.0])
    beta, *_ = np.linalg.lstsq(a[ok], y[ok], rcond=None)
    return beta


def har_apply(beta: np.ndarray, rv1: np.ndarray, rv5: np.ndarray, rv22: np.ndarray) -> np.ndarray:
    a = np.column_stack([
        np.ones(len(rv1)),
        np.log(np.maximum(rv1, 1e-12)),
        np.log(np.maximum(rv5, 1e-12)),
        np.log(np.maximum(rv22, 1e-12)),
    ])
    return a @ beta


def r2(pred: np.ndarray, truth: np.ndarray, ref: np.ndarray) -> float:
    """Out-of-sample R^2 against a reference forecaster, not against zero.

    `ref` is the training-block unconditional mean, so a negative number means
    exactly one thing: **this model loses to a constant**. That is the statistic
    the magnitude question is asking for, and srel on a log-scale quantity is
    not - srel on `logvol` is dominated by the size of `log(1e-4)` and would
    report two useless forecasters as nearly identical. srel is carried too, on
    `realised` rather than on its log, because that is the object
    `research/forecasting.md`'s table scores and this page has to join it.
    """
    p, t, r = np.asarray(pred, float), np.asarray(truth, float), np.asarray(ref, float)
    ok = np.isfinite(p) & np.isfinite(t) & np.isfinite(r)
    if ok.sum() < 5:
        return float("nan")
    sse = float(np.sum((t[ok] - p[ok]) ** 2))
    sst = float(np.sum((t[ok] - r[ok]) ** 2))
    return float("nan") if sst <= 0 else 1.0 - sse / sst


def auc_se(n1: float, n0: float) -> float:
    """Standard error of a rank AUC under the null. Feeds the parametric family-wise draw."""
    if n1 < 2 or n0 < 2:
        return float("nan")
    n = n1 + n0
    return float(math.sqrt((n + 1.0) / (12.0 * n1 * n0)))


# --------------------------------------------------------------------------
# One cell
# --------------------------------------------------------------------------


def variant_bars(symbol: str, interval: str, variant: str,
                 bars: dict[str, np.ndarray], rng: np.random.Generator) -> dict[str, np.ndarray]:
    if variant in ("real", "shuffle"):
        return bars
    if variant == "surrogate":
        return seqlab.surrogate_bars(bars, rng)
    if variant == "gbm":
        sigma = seqlab.NAMED_SIGMA.get(symbol)
        if sigma is None or not math.isfinite(sigma):
            sigma = seqlab.measured_sigma(bars, interval)
        return seqlab.gbm_bars(sigma, len(bars["close"]), interval, rng)
    raise ValueError(variant)


def run_cell(job: dict) -> dict:
    """One (symbol, timeframe, variant, architecture, target) cell, all folds.

    Returns fold-weighted metrics plus every number needed to read them: rows,
    parameters, epochs actually run, and the three baselines scored on the
    identical test rows the net was scored on.
    """
    symbol, interval, variant = job["symbol"], job["interval"], job["variant"]
    kind, hidden, seqlen = job["arch"], job["hidden"], job["seqlen"]
    task, folds_n, seed = job["target"], job["folds"], job["seed"]
    rng = np.random.default_rng(seed)

    bars = seqlab.load(symbol, interval)
    bars = variant_bars(symbol, interval, variant, bars, rng)
    prep = prepare(bars)
    x, tg, names = prep["x"], prep["t"], prep["names"]
    n = prep["n"]

    y = tg[task].copy()
    if variant == "shuffle":
        y = seqlab.shuffle_target(y, rng)
    truth_rv = tg["realised"]
    truth_lv = tg["logvol"]
    if variant == "shuffle" and task == "logvol":
        truth_lv = y
        truth_rv = np.exp(y)

    i1, i5, i22 = (names.index(k) for k in ("rv1", "rv5", "rv22"))
    folds = seqlab.walk_forward(n, folds=folds_n, horizon=HORIZON)
    if not folds:
        raise seqlab.Thin(f"no folds at n={n}")

    rows = []
    for fold_i, (tr, te) in enumerate(folds):
        off = seqlen - 1
        tr = tr[tr >= off]
        te = te[te >= off]
        if len(tr) < 200 or len(te) < 30:
            continue
        cut = int(len(tr) * (1.0 - VAL_FRAC))
        sub = tr[: max(cut - HORIZON, 0)]
        val = tr[cut:]
        if len(sub) < 100 or len(val) < 30:
            continue
        avail = len(sub)
        if avail > MAX_TRAIN:
            sub = sub[np.linspace(0, avail - 1, MAX_TRAIN).astype(int)]

        hi = int(sub[-1]) + 1
        mu = np.nanmean(x[:hi], axis=0)
        sd = np.nanstd(x[:hi], axis=0)
        sd = np.where(np.isfinite(sd) & (sd > 1e-12), sd, 1.0)
        xs = np.clip((x - mu) / sd, -CLIP, CLIP).astype(np.float32)
        win = windows(xs, seqlen)

        fit = fit_predict(win, y, sub, val, te, kind=kind, hidden=hidden,
                          seqlen=seqlen, task=task, seed=seed + fold_i)
        pred = fit["test"]
        row = {
            "fold": fold_i, "n_train": int(len(sub)), "n_train_avail": int(avail),
            "n_val": int(len(val)), "n_test": int(len(te)),
            "params": fit["params"], "epochs": fit["epochs"],
            "overparam": bool(fit["params"] > len(sub)),
        }

        if task == "direction":
            lab = y[te].astype(int)
            row["auc_net"] = seqlab.auc(pred, lab)
            row["auc_val"] = seqlab.auc(fit["val"], y[val].astype(int))
            row["auc_momentum"] = seqlab.auc(x[te][:, names.index("ret")], lab)
            row["rate"] = float(lab.mean())
            row["n1"] = int((lab == 1).sum())
            row["n0"] = int((lab == 0).sum())
        else:
            lv_tr, lv_te = truth_lv[sub], truth_lv[te]
            ref = np.full(len(te), float(np.nanmean(lv_tr)))
            beta = har_fit(x[sub][:, i1], x[sub][:, i5], x[sub][:, i22], lv_tr)
            har_te = har_apply(beta, x[te][:, i1], x[te][:, i5], x[te][:, i22])
            naive_lv = np.log(np.maximum(x[te][:, i1], 1e-12))
            rv_te = truth_rv[te]
            mean_rv = np.full(len(te), float(np.nanmean(truth_rv[sub])))

            row["r2_net"] = r2(pred, lv_te, ref)
            row["r2_val"] = r2(fit["val"], truth_lv[val],
                               np.full(len(val), float(np.nanmean(lv_tr))))
            row["r2_har"] = r2(har_te, lv_te, ref)
            row["r2_naive"] = r2(naive_lv, lv_te, ref)
            row["srel_net"] = seqlab.srel(np.exp(pred), rv_te)
            row["srel_har"] = seqlab.srel(np.exp(har_te), rv_te)
            row["srel_naive"] = seqlab.srel(x[te][:, i1], rv_te)
            row["srel_mean"] = seqlab.srel(mean_rv, rv_te)
            row["srel_meanlog"] = seqlab.srel(np.exp(ref), rv_te)
        rows.append(row)

    if not rows:
        raise seqlab.Thin("no usable folds")

    w = np.array([r["n_test"] for r in rows], dtype=float)
    out = {
        "symbol": symbol, "interval": interval, "variant": variant,
        "arch": kind, "hidden": hidden, "seqlen": seqlen, "target": task,
        "bars": int(prep["rows_total"]), "usable": int(n),
        "dropped": int(prep["rows_dropped"]),
        "folds": len(rows), "n_test": int(w.sum()),
        "n_train": int(np.mean([r["n_train"] for r in rows])),
        "n_train_avail": int(np.mean([r["n_train_avail"] for r in rows])),
        "params": rows[0]["params"],
        "epochs": float(np.mean([r["epochs"] for r in rows])),
        "overparam": bool(any(r["overparam"] for r in rows)),
        "per_fold": rows,
    }
    keys = [k for k in rows[0] if k.startswith(("auc_", "r2_", "srel_"))]
    for k in keys:
        v = np.array([r[k] for r in rows], dtype=float)
        ok = np.isfinite(v)
        out[k] = float(np.sum(v[ok] * w[ok]) / w[ok].sum()) if ok.any() else float("nan")
        out[k + "_sd"] = float(np.std(v[ok])) if ok.sum() > 1 else float("nan")
    if task == "direction":
        n1 = float(sum(r["n1"] for r in rows))
        n0 = float(sum(r["n0"] for r in rows))
        out["auc_se"] = auc_se(n1, n0)
        out["nstar"] = seqlab.nstar(out["auc_net"], 0.5, out["n_test"])
    return out


def safe_cell(job: dict) -> dict:
    try:
        return run_cell(job)
    except seqlab.Thin as exc:
        return {**{k: job[k] for k in ("symbol", "interval", "variant", "arch",
                                       "hidden", "seqlen", "target")},
                "skipped": f"thin: {exc}"}
    except Exception as exc:  # noqa: BLE001 - one bad cell must not stop a grid
        return {**{k: job[k] for k in ("symbol", "interval", "variant", "arch",
                                       "hidden", "seqlen", "target")},
                "failed": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc()[-600:]}


# --------------------------------------------------------------------------
# Fan-out
# --------------------------------------------------------------------------


def _init_worker() -> None:
    torch.set_num_threads(1)


def fan_out(jobs: list[dict], label: str) -> list[dict]:
    began = time.time()
    got: list[dict] = []
    print(f"{label}: {len(jobs):,} cells on {WORKERS} workers", flush=True)
    with ProcessPoolExecutor(max_workers=WORKERS, initializer=_init_worker) as pool:
        futures = [pool.submit(safe_cell, j) for j in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            got.append(fut.result())
            if i % max(1, len(jobs) // 40) == 0 or i == len(jobs):
                rate = i / max(time.time() - began, 1e-9)
                left = (len(jobs) - i) / max(rate, 1e-9) / 60.0
                bad = sum(1 for r in got if "failed" in r or "skipped" in r)
                print(f"  {i:,}/{len(jobs):,}  {bad} skipped/failed  "
                      f"~{left:.1f}m left", flush=True)
    print(f"{label}: {(time.time() - began) / 60:.1f}m\n", flush=True)
    return got


def save(stage: str, payload: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{stage}.json"
    path.write_text(json.dumps(payload, indent=1, default=float))
    print(f"wrote {path}", flush=True)
    return path


def warm(pairs: list[tuple[str, str]]) -> tuple[dict[str, int], set[tuple[str, str]]]:
    """Pull anything the cache is missing, one at a time, and name what is unusable.

    Eight workers each discovering a cache miss is eight concurrent
    fifty-thousand-bar transfers against the terminal the live desk trades
    through, which is the failure `research/starving.md` is about. Serial here,
    parallel after.

    **It also returns the dead pairs, and the caller must use them.** The first
    run of this grid did not: `Spot Up - Volatility Down Index` 404s on every
    timeframe, nothing ever lands in the cache for it, and each of its 128 cells
    therefore re-ran `seqlab.fetch`'s four retries - about five hundred requests
    to a route that was never going to answer, against the terminal the desk
    trades through. The arithmetic was unaffected and the cells were correctly
    reported as failures; the cost was borne entirely by a shared resource,
    which is the kind of defect that does not show up in a result table.
    """
    sizes: dict[str, int] = {}
    dead: set[tuple[str, str]] = set()
    for symbol, interval in pairs:
        key = f"{symbol}|{interval}"
        try:
            sizes[key] = int(len(seqlab.load(symbol, interval)["close"]))
        except Exception as exc:  # noqa: BLE001
            sizes[key] = 0
            dead.add((symbol, interval))
            print(f"  ! {symbol} {interval}: {str(exc)[:80]}", flush=True)
    return sizes, dead


# --------------------------------------------------------------------------
# Family-wise
# --------------------------------------------------------------------------


def family_auc_p(observed: float, ses: list[float], rng: np.random.Generator,
                 reps: int = 20_000) -> dict:
    """Parametric family-wise p: draw one null AUC per cell, take the best, repeat.

    `seqlab.max_of_k` then answers the only question worth asking on a grid this
    wide - *how often does the best of this many fair coins beat what we saw* -
    rather than the per-test question, which on 528 cells is answered "often"
    by construction.
    """
    s = np.array([v for v in ses if np.isfinite(v)], dtype=float)
    if not len(s) or not np.isfinite(observed):
        return {"p": float("nan"), "k": int(len(s))}
    draws = (0.5 + rng.normal(size=(reps, len(s))) * s).max(axis=1)
    return {"p": seqlab.max_of_k(observed, draws), "k": int(len(s)),
            "null_best_median": float(np.median(draws)),
            "null_best_p95": float(np.quantile(draws, 0.95))}


def family_empirical_p(observed: float, control: list[float], k: int,
                       rng: np.random.Generator, reps: int = 20_000) -> dict:
    """Family-wise p from the control cells themselves, no distributional assumption.

    The `gbm` and `surrogate` cells are draws from a true null - not a modelled
    one - so resampling `k` of them and taking the best reproduces the grid's own
    multiple-testing exposure using the grid's own noise, including whatever the
    fold structure does to it that a normal approximation misses.

    **Read `best_control` before the p-value.** When `k` approaches the size of
    the control pool, a bootstrap maximum is the pool maximum almost every time
    and the p-value collapses to a coarse 0 or 1 - the resampling has no room
    left to vary. The honest statement in that regime is the direct comparison
    the field is actually asking for, *is the best real cell better than the best
    control cell*, so both are returned and the direct one is the one to quote.
    """
    c = np.array([v for v in control if np.isfinite(v)], dtype=float)
    if len(c) < 10 or not np.isfinite(observed):
        return {"p": float("nan"), "pool": int(len(c))}
    draws = rng.choice(c, size=(reps, k), replace=True).max(axis=1)
    return {"p": seqlab.max_of_k(observed, draws), "pool": int(len(c)), "k": k,
            "best_control": float(c.max()),
            "observed_minus_best_control": float(observed - c.max()),
            "control_q99": float(np.quantile(c, 0.99)),
            "null_best_median": float(np.median(draws)),
            "null_best_p95": float(np.quantile(draws, 0.95))}


# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------


def stage_probe() -> dict:
    """Kill conditions 1 and 2, a timing measurement, and nothing else.

    Nothing on this page is readable until the injected-leak probe fires. A
    pipeline that cannot see the target when the target is handed to it as a
    feature column returns zero for reasons that have nothing to do with the
    data.
    """
    sym, tf = "Volatility 75 Index", "1h"
    rng = np.random.default_rng(11)
    bars = seqlab.load(sym, tf)
    verdict = seqlab.check_causality(bars)
    print(f"causality: {'CLEAN' if verdict['clean'] else 'LEAKING ' + str(verdict['leaking'])}"
          f"  ({verdict['rows_checked']:,} rows)", flush=True)

    prep = prepare(bars)
    print(f"{sym} {tf}: {prep['rows_total']:,} bars, {prep['n']:,} usable, "
          f"{prep['rows_dropped']} dropped", flush=True)
    w = windows(np.arange(40 * 3, dtype=np.float64).reshape(40, 3), 8)
    print(f"window alignment: OK  shape {w.shape} (assertions live in windows())", flush=True)

    # Kill condition 2: hand the model the answer and require that it takes it.
    leak = {}
    x, tg = prep["x"], prep["t"]
    n = prep["n"]
    folds = seqlab.walk_forward(n, folds=2, horizon=HORIZON)
    tr, te = folds[-1]
    off = 15
    tr, te = tr[tr >= off], te[te >= off]
    cut = int(len(tr) * 0.8)
    sub, val = tr[: cut - 1], tr[cut:]
    sub = sub[np.linspace(0, len(sub) - 1, min(len(sub), 4000)).astype(int)]
    for task in ("direction", "logvol"):
        y = tg[task]
        planted = np.column_stack([x, np.nan_to_num(y)])
        mu, sd = planted.mean(axis=0), np.maximum(planted.std(axis=0), 1e-12)
        xs = np.clip((planted - mu) / sd, -CLIP, CLIP).astype(np.float32)
        fit = fit_predict(windows(xs, 16), y, sub, val, te, kind="gru", hidden=16,
                          seqlen=16, task=task, seed=3)
        if task == "direction":
            leak["auc"] = seqlab.auc(fit["test"], y[te].astype(int))
        else:
            ref = np.full(len(te), float(np.nanmean(y[sub])))
            leak["r2"] = r2(fit["test"], y[te], ref)
    print(f"injected leak: direction AUC {leak['auc']:.4f}  logvol R2 {leak['r2']:.4f}"
          f"   {'FIRED' if leak['auc'] > 0.95 and leak['r2'] > 0.95 else 'DID NOT FIRE'}",
          flush=True)

    timing = []
    for kind in ARCHS:
        for hidden in (16, 64):
            t0 = time.time()
            safe_cell({"symbol": sym, "interval": tf, "variant": "real", "arch": kind,
                       "hidden": hidden, "seqlen": 32, "target": "logvol",
                       "folds": FOLDS_GRID, "seed": 5})
            dt = time.time() - t0
            timing.append({"arch": kind, "hidden": hidden, "seconds": dt})
            print(f"  timing {kind} h{hidden} seqlen32 {FOLDS_GRID} folds: {dt:.1f}s",
                  flush=True)
    return {"causality": verdict, "prep": {k: prep[k] for k in
                                           ("n", "rows_total", "rows_dropped")},
            "injected_leak": leak, "timing": timing,
            "sigma_named": seqlab.NAMED_SIGMA[sym],
            "sigma_measured": seqlab.measured_sigma(bars, tf)}


def stage_sweep() -> dict:
    jobs = []
    for symbol, interval in ANCHORS:
        for kind in ARCHS:
            for hidden in HIDDEN:
                for seqlen in SEQLENS:
                    for task in ("logvol", "direction"):
                        jobs.append({"symbol": symbol, "interval": interval,
                                     "variant": "real", "arch": kind, "hidden": hidden,
                                     "seqlen": seqlen, "target": task,
                                     "folds": FOLDS_SWEEP, "seed": 17})
    _, dead = warm(list(ANCHORS))
    jobs = [j for j in jobs if (j["symbol"], j["interval"]) not in dead]
    got = fan_out(jobs, "sweep")
    return {"stage": "sweep", "anchors": [list(a) for a in ANCHORS], "cells": got}


def pick_config(sweep: dict) -> dict:
    """Choose the grid architecture on **validation**, never on test.

    Selecting on the test fold is the quiet version of the leak this page is
    built to avoid: with 36 configs and a null target, the best test score is
    guaranteed to look like an edge. The validation slice is the tail of the
    training block and was never scored against, so it is the only honest place
    to make this choice - and if the choice turns out not to matter, that is a
    result about recurrent nets on this data rather than an inconvenience.
    """
    best, bestv = None, -float("inf")
    per: dict[str, list] = {}
    for c in sweep["cells"]:
        if c.get("target") != "logvol" or "r2_val" not in c:
            continue
        key = f"{c['arch']}|{c['hidden']}|{c['seqlen']}"
        per.setdefault(key, []).append(c["r2_val"])
    ranked = sorted(((float(np.nanmean(v)), k) for k, v in per.items()), reverse=True)
    for score, key in ranked:
        if np.isfinite(score):
            best, bestv = key, score
            break
    if best is None:
        best, bestv = "gru|16|16", float("nan")
    arch, hidden, seqlen = best.split("|")
    return {"arch": arch, "hidden": int(hidden), "seqlen": int(seqlen),
            "val_r2": bestv, "ranking": [{"config": k, "val_r2": s} for s, k in ranked[:10]]}


def _grid_jobs(symbols: tuple[str, ...], config: dict, *,
               archs: tuple[str, ...] = ARCHS,
               multi: tuple[str, ...] = ("real", "gbm"),
               single: tuple[str, ...] = ("shuffle", "surrogate"),
               seed: int = 23) -> list[dict]:
    """All three architectures where the comparison needs them, one where it does not.

    **`real` and `gbm` run on every architecture and the other two controls run
    on one.** That is a deliberate asymmetry, not a saving. The family-wise
    question is "how often does the best of 22 symbols x 8 timeframes x 3
    architectures beat this", so the architecture axis has to be inside the
    family or the multiplicity is understated by a factor of three - and `gbm`
    has to carry it too, because a null that was only ever run at one
    architecture cannot say what three architectures' worth of searching does to
    the best score. `shuffle` and `surrogate` are the *mechanism* controls -
    they answer "is the pipeline reading the answer" and "is it reading the
    spectrum", and neither question is architecture-specific.

    The hidden size and sequence length are fixed at what the sweep chose on
    validation, so the architecture is the only free axis here and the selection
    that produced the rest of the configuration never saw a test row.
    """
    jobs = []
    for symbol in symbols:
        for interval in seqlab.GRID:
            for task in ("logvol", "direction"):
                for arch in archs:
                    for variant in multi:
                        jobs.append({"symbol": symbol, "interval": interval,
                                     "variant": variant, "arch": arch,
                                     "hidden": config["hidden"],
                                     "seqlen": config["seqlen"],
                                     "target": task, "folds": FOLDS_GRID,
                                     "seed": seed})
                for variant in single:
                    jobs.append({"symbol": symbol, "interval": interval,
                                 "variant": variant, "arch": config["arch"],
                                 "hidden": config["hidden"], "seqlen": config["seqlen"],
                                 "target": task, "folds": FOLDS_GRID, "seed": seed})
    return jobs


def _family(cells: list[dict], rng: np.random.Generator) -> dict:
    good = [c for c in cells if "failed" not in c and "skipped" not in c]
    real = [c for c in good if c["variant"] == "real"]
    # **`shuffle` is deliberately not in the null pool, and the reason is a bug
    # this function had.** Under `shuffle` the target itself is destroyed, so a
    # logvol R^2 there is measured against a reference the model could not have
    # matched and comes back at minus several hundred. Pooling those with the
    # `gbm` and `surrogate` R^2 values drags the null's *maximum* down, which
    # makes the family-wise p-value smaller - it would manufacture significance
    # out of a control. `gbm` and `surrogate` are the right pool: real-shaped
    # data with a real target and no forecastable structure. `shuffle` is a
    # mechanism check - "is the pipeline reading the answer" - and is reported
    # on its own line rather than mixed into an arithmetic it does not belong in.
    ctrl = [c for c in good if c["variant"] in ("surrogate", "gbm")]
    d_real = [c for c in real if c["target"] == "direction"]
    d_ctrl = [c for c in ctrl if c["target"] == "direction"]
    v_real = [c for c in real if c["target"] == "logvol"]
    v_ctrl = [c for c in ctrl if c["target"] == "logvol"]

    def by_variant(task: str, key: str) -> dict:
        return {
            v: float(np.nanmean([c[key] for c in good
                                 if c["variant"] == v and c["target"] == task]))
            for v in VARIANTS
            if any(c["variant"] == v and c["target"] == task for c in good)
        }

    out: dict = {"archs": sorted({c["arch"] for c in real})}
    for task_name, key, cells_t in (("direction", "auc_net", d_real),
                                    ("logvol", "r2_net", v_real)):
        out.setdefault("by_arch", {})[task_name] = {
            a: float(np.nanmean([c[key] for c in cells_t if c["arch"] == a]))
            for a in out["archs"]
            if any(c["arch"] == a for c in cells_t)
        }
    if d_real:
        best = max(d_real, key=lambda c: c.get("auc_net", -1))
        out["direction"] = {
            "best_cell": {k: best[k] for k in ("symbol", "interval", "arch",
                                               "auc_net", "n_test", "nstar",
                                               "auc_se", "overparam")},
            "mean_auc": float(np.nanmean([c["auc_net"] for c in d_real])),
            "sd_auc": float(np.nanstd([c["auc_net"] for c in d_real])),
            "cells": len(d_real),
            "parametric": family_auc_p(best["auc_net"],
                                       [c.get("auc_se", np.nan) for c in d_real], rng),
            "empirical": family_empirical_p(best["auc_net"],
                                            [c["auc_net"] for c in d_ctrl],
                                            len(d_real), rng),
            "by_variant": by_variant("direction", "auc_net"),
        }
    if v_real:
        best = max(v_real, key=lambda c: c.get("r2_net", -np.inf))
        out["logvol"] = {
            "best_cell": {k: best[k] for k in ("symbol", "interval", "arch",
                                               "r2_net", "r2_har", "r2_naive",
                                               "n_test", "overparam")},
            "mean_r2": float(np.nanmean([c["r2_net"] for c in v_real])),
            "sd_r2": float(np.nanstd([c["r2_net"] for c in v_real])),
            "beat_mean": int(sum(1 for c in v_real if c["r2_net"] > 0)),
            "beat_har": int(sum(1 for c in v_real
                                if c["r2_net"] > c.get("r2_har", np.inf))),
            "beat_naive": int(sum(1 for c in v_real
                                  if c["r2_net"] > c.get("r2_naive", np.inf))),
            "cells": len(v_real),
            "empirical": family_empirical_p(best["r2_net"],
                                            [c["r2_net"] for c in v_ctrl],
                                            len(v_real), rng),
            "by_variant": by_variant("logvol", "r2_net"),
            "by_variant_srel_net": by_variant("logvol", "srel_net"),
            "by_variant_srel_naive": by_variant("logvol", "srel_naive"),
            "by_variant_srel_mean": by_variant("logvol", "srel_mean"),
        }
    return out


def grid_config() -> dict:
    """The geometry the grid runs at, and the one place this study overrode its own rule.

    The pre-registered rule was *select on validation, never on test*, and the
    sweep's answer was **GRU hidden 64, sequence length 32** - 18,113 parameters
    for a GRU and 24,129 for an LSTM. Then kill condition 6 was checked against
    it and it fails, not at 1d where it was expected to, but **everywhere**:
    `MAX_TRAIN` caps a fold's training block at 12,000 windows, and the densest
    cell in the study trains on 10,927. A full grid at that geometry would be a
    grid of cells the harness's own rules say are memorisations, and the sweep
    already showed what such cells do - 17 of the 18 positive R^2 values in it
    have more parameters than training windows.

    So the grid runs at the **largest geometry whose parameter count stays below
    the training windows at the dense timeframes**: hidden 32, sequence length
    16, which is 5,985 parameters for a GRU and 7,969 for an LSTM against 10,927
    windows. The override is recorded on every record rather than applied
    silently, and the reason for it is a capacity rule written down before any
    number was read - not a score. The validation-selected geometry is not
    abandoned: the sweep ran it at five folds on four anchors and its answer,
    test R^2 **-0.0026**, is reported beside this grid's.

    `HIDDEN`, `SEQLEN` and `ARCH` in the environment override all of this, so
    the grid can be re-run at the validation-selected geometry by anyone who
    wants to spend the four hours it costs.
    """
    path = OUT / "sweep.json"
    chosen = (pick_config(json.loads(path.read_text())) if path.exists()
              else {"arch": "gru", "hidden": 64, "seqlen": 32,
                    "val_r2": float("nan"), "ranking": []})
    config = dict(chosen)
    config["selected_on_validation"] = {k: chosen[k] for k in
                                        ("arch", "hidden", "seqlen", "val_r2")}
    config["hidden"] = int(os.environ.get("HIDDEN", 32))
    config["seqlen"] = int(os.environ.get("SEQLEN", 16))
    config["arch"] = os.environ.get("ARCH", chosen["arch"])
    config["capacity_override"] = (
        config["hidden"] != chosen["hidden"] or config["seqlen"] != chosen["seqlen"]
    )
    return config


def stage_grid() -> dict:
    config = grid_config()
    sel = config["selected_on_validation"]
    print(f"config: {config['arch']} h{config['hidden']} L{config['seqlen']}"
          f"  (validation chose {sel['arch']} h{sel['hidden']} L{sel['seqlen']}"
          f" at val R2 {sel['val_r2']:.5f};"
          f" capacity override {config['capacity_override']})", flush=True)

    symbols = tuple(seqlab.VOLATILITY) + tuple(seqlab.SPOT_UP)
    sizes, dead = warm([(s, tf) for s in symbols for tf in seqlab.GRID])
    jobs = [j for j in _grid_jobs(symbols, config)
            if (j["symbol"], j["interval"]) not in dead]
    got = fan_out(jobs, "grid")
    rng = np.random.default_rng(101)
    return {"stage": "grid", "config": config, "cells": got, "bars": sizes,
            "unavailable": sorted(f"{a}|{b}" for a, b in dead),
            "family": _family(got, rng)}


def stage_real() -> dict:
    """The positive control, and the only thing that makes the negative falsifiable."""
    config = grid_config()
    sizes, dead = warm([(s, tf) for s in seqlab.REAL for tf in seqlab.GRID])
    jobs = [j for j in _grid_jobs(tuple(seqlab.REAL), config, single=())
            if (j["symbol"], j["interval"]) not in dead]
    got = fan_out(jobs, "real")
    rng = np.random.default_rng(202)
    return {"stage": "real", "config": config, "cells": got, "bars": sizes,
            "unavailable": sorted(f"{a}|{b}" for a, b in dead),
            "family": _family(got, rng)}


def summarise(payload: dict) -> None:
    cells = [c for c in payload.get("cells", [])
             if "failed" not in c and "skipped" not in c]
    if not cells:
        return
    print("\n--- logvol: net vs the three baselines, real variant ---", flush=True)
    print(f"{'symbol':30s} {'tf':4s} {'arch':5s} {'n_test':>8s} {'R2 net':>9s} {'R2 har':>9s} "
          f"{'R2 naive':>9s} {'srel net':>9s} {'srel mean':>9s} over", flush=True)
    for c in sorted([c for c in cells if c["target"] == "logvol"
                     and c["variant"] == "real"],
                    key=lambda c: (c["symbol"], seqlab.GRID.index(c["interval"]),
                                   c["arch"])):
        print(f"{c['symbol'][:30]:30s} {c['interval']:4s} {c['arch']:5s} {c['n_test']:8,d} "
              f"{c['r2_net']:9.4f} {c['r2_har']:9.4f} {c['r2_naive']:9.4f} "
              f"{c['srel_net']:9.4f} {c['srel_mean']:9.4f} "
              f"{'Y' if c['overparam'] else '.'}", flush=True)
    print("\n--- direction: null calibration, real variant ---", flush=True)
    for c in sorted([c for c in cells if c["target"] == "direction"
                     and c["variant"] == "real"],
                    key=lambda c: (c["symbol"], seqlab.GRID.index(c["interval"]),
                                   c["arch"])):
        print(f"{c['symbol'][:30]:30s} {c['interval']:4s} {c['arch']:5s} {c['n_test']:8,d} "
              f"AUC {c['auc_net']:.4f}  n* {c['nstar']:.3g}  "
              f"{'Y' if c['overparam'] else '.'}", flush=True)
    fam = payload.get("family", {})
    if fam:
        print("\n--- family-wise ---", flush=True)
        print(json.dumps(fam, indent=1, default=float), flush=True)


def main() -> None:
    mode = os.environ.get("MODE", "probe")
    print(f"seqnets - recurrent arm, MODE={mode}, workers={WORKERS}\n", flush=True)
    began = time.time()
    if mode == "probe":
        payload = stage_probe()
    elif mode == "sweep":
        payload = stage_sweep()
    elif mode == "grid":
        payload = stage_grid()
    elif mode == "real":
        payload = stage_real()
    elif mode == "all":
        # The grid and its positive control in one process. Two launches would
        # race for the same log name and the same flag file, and a negative
        # result whose positive control ran from a different sync of the repo
        # is not a control.
        for sub in ("grid", "real"):
            part = stage_grid() if sub == "grid" else stage_real()
            part["minutes"] = (time.time() - began) / 60.0
            save(sub, part)
            summarise(part)
        payload = {"stage": "all", "ran": ["grid", "real"]}
    else:
        raise SystemExit(f"unknown MODE {mode}")
    payload["minutes"] = (time.time() - began) / 60.0
    save(mode, payload)
    if mode != "all":
        summarise(payload)
    print(f"\n{mode} finished in {payload['minutes']:.1f}m", flush=True)


if __name__ == "__main__":
    main()
