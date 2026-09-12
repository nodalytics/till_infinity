"""Fine-tuning Kronos-mini per fold, on synthetics and on real markets, to measure the transfer gap.

**The gap is the measurement, not the level.** Kronos is pretrained on real
equities and crypto. If its pretraining carries market structure - volatility
clustering, the leverage effect, session shape, anything at all - then fine-tuning
should buy little on a real market, because the structure is already in the
weights, and should buy more on a Deriv synthetic, because a constant-sigma GBM
has none of that structure and the model has to be retuned to a process it has
never seen. If instead fine-tuning buys the *same* amount on both, the
pretraining was carrying general sequence machinery rather than market structure,
and "foundation model for finance" is a claim about the architecture.

That is the one question on this page that has an interesting answer either way,
which is why it is run at all: **the direction arm's outcome is known**
(`research/deriving.md`, and `kronos.py`'s null calibration) and the volatility
arm's outcome on a constant-sigma member is known too.

## The protocol, and the two places it could cheat

Per timeframe, per domain (`seqlab.VOLATILITY` or `seqlab.REAL`), per
`seqlab.walk_forward` fold:

* **Train windows are drawn from that fold's train block only**, pooled across
  the domain's symbols. The block ends at the fold's purge boundary, so the last
  training target is the last bar a train row is allowed to read - no window
  reaches into the test block.
* **Validation is the last tenth of the train block**, with a one-bar purge
  against the training part. It is strictly before the test block, so the early
  stop is not a test-set decision.
* **The tokenizer is never trained.** Not for economy: a quantiser refitted per
  fold is the single most likely way this arm manufactures a false positive, and
  freezing it turns "the codebook never saw a test row" from a promise into a
  property of the code. The tokenizer is also causal by architecture
  (`kronoslib` documents why), so its codes at row `t` are a function of bars
  `<= t` whatever it was fitted on.
* **Normalisation is per window on the lookback part**, which is upstream's own
  `finetune/dataset.py` convention and is causal by construction.
* **A fresh model per fold.** Carrying a model across folds would train it on a
  later fold's test block through the earlier fold's weights.

## The scratch arm, which is what makes "pretraining helped" falsifiable

`zero-shot -> fine-tuned` measures how much fine-tuning adds. It does not
measure whether the pretrained weights were worth anything: a 4.1M-parameter
transformer trained from random initialisation on the same rows, for the same
number of steps, might land in the same place. So `scratch` runs exactly that -
the published architecture, the published initialisation
(`Kronos._init_weights`), the same data, the same schedule - and the
`fine-tuned - scratch` gap is what pretraining actually bought.

## Reading the curves, and where fine-tuning is not defensible

Train and validation loss are both evaluated **in eval mode on fixed window
sets**, with the sampler reseeded identically at every evaluation point. That
matters more than it sounds: `Kronos.forward` samples `s1` to condition the `s2`
head when teacher forcing is off, and `DependencyAwareLayer` masks causally in
train mode and not in eval mode, so a training-mode loss and an eval-mode loss
are not the same number and their difference is not an overfitting measure.

At 1d a Volatility symbol holds under 2,900 bars. Twenty of them pooled is about
57,000 bars, but a 128-bar context slides one bar at a time, so those are
overlapping views of roughly 450 independent context-lengths of history against
4.1M parameters. **Fine-tuning at 1d is not defensible and this file runs it
anyway**, because the honest way to say so is to show the validation curve
turning up.

    ./.secrets/lab.sh run research/harness/kronosfine.py TFS=1h STEPS=1200
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch

from research.harness import kronos as kz
from research.harness import kronoslib, seqlab

RESULTS = Path.home() / "till_infinity" / "results"

CTX = int(os.environ.get("CTX", 128))
SAMPLES = int(os.environ.get("SAMPLES", 64))
STEPS = int(os.environ.get("STEPS", 1200))
BATCH = int(os.environ.get("BATCH", 16))
#: Upstream's `predictor_learning_rate`. Not tuned here - a learning rate chosen
#: by looking at a test score is a test-set decision wearing a hyperparameter's
#: clothes.
LR = float(os.environ.get("LR", 4e-5))
EVERY = int(os.environ.get("EVERY", 100))
CAP = int(os.environ.get("CAP", 1200))
CAL = int(os.environ.get("CAL", 200))
TFS = tuple(os.environ.get("TFS", "1h,1d").split(","))
ARMS = tuple(os.environ.get("ARMS", "zero,fine,scratch").split(","))
NFOLDS = int(os.environ.get("NFOLDS", 5))

DOMAINS = {"volatility": seqlab.VOLATILITY, "real": seqlab.REAL}


class Series:
    """One symbol, pre-built: channels, clock, features, targets, folds."""

    def __init__(self, symbol: str, interval: str, ctx: int):
        self.symbol, self.interval = symbol, interval
        bars = seqlab.load(symbol, interval)
        self.x, self.names, self.y, self.idx = kz.prepare(bars, ctx)
        self.chan, self.stamp = kronoslib.frame(bars)
        self.folds = seqlab.walk_forward(len(self.idx), folds=NFOLDS, horizon=1)
        self.n = len(self.idx)


def train_span(s: Series, fold: int) -> tuple[int, int]:
    """First and last **bar** index a training window may read for this fold.

    The upper edge is `idx[tr_end-1] + 1`: the last train row's own target. Going
    one bar further would hand the model a bar the purge exists to withhold.
    """
    tr, _ = s.folds[fold]
    return int(s.idx[0]), int(s.idx[tr[-1]]) + 1


def draw(series: list[Series], pairs: np.ndarray, ctx: int):
    """Windows of `ctx + 1` bars, z-scored on the first `ctx` - upstream's convention.

    `pairs` is an `(n, 2)` array of `(symbol index, start bar)`. It is an array
    and not a list of tuples because at 1h twenty symbols carry about 800,000
    legal starts per fold, and a Python list of that many tuples costs more
    memory than the bars themselves.
    """
    xs, ss = [], []
    for si, start in pairs:
        s = series[int(si)]
        w = s.chan[int(start) : int(start) + ctx + 1]
        past = w[:ctx]
        m, sd = past.mean(axis=0), past.std(axis=0)
        xs.append(np.clip((w - m) / (sd + 1e-5), -kronoslib.CLIP, kronoslib.CLIP))
        ss.append(s.stamp[int(start) : int(start) + ctx + 1])
    return (torch.from_numpy(np.stack(xs).astype(np.float32)),
            torch.from_numpy(np.stack(ss).astype(np.float32)))


def starts(series: list[Series], fold: int, ctx: int, *, val_share: float = 0.10):
    """Legal window starts, split into a train part and a validation tail.

    The validation tail is the last `val_share` of each symbol's train block with
    a one-bar purge, so a validation window's target is never a training
    window's input.
    """
    tr, va = [], []
    for si, s in enumerate(series):
        lo, hi = train_span(s, fold)
        last_start = hi - ctx
        if last_start <= lo:
            continue
        cut = int(lo + (1 - val_share) * (last_start - lo))
        a = np.arange(lo, max(cut - 1, lo))
        b = np.arange(cut, last_start + 1)
        if len(a):
            tr.append(np.column_stack([np.full(len(a), si), a]))
        if len(b):
            va.append(np.column_stack([np.full(len(b), si), b]))
    empty = np.zeros((0, 2), dtype=int)
    return (np.concatenate(tr) if tr else empty,
            np.concatenate(va) if va else empty)


@torch.no_grad()
def loss_on(model, tok, series, pool: np.ndarray, ctx: int, *, chunk: int = 16,
            seed: int = 1234) -> float:
    """Eval-mode loss on a fixed window set, with the sampler pinned.

    `Kronos.forward` draws `s1` to condition the `s2` head. Left unseeded that
    draw moves every evaluation point and the curve acquires a wobble that reads
    as structure. Reseeding identically makes successive points comparable.
    """
    was = model.training
    model.eval()
    torch.manual_seed(seed)
    total, seen = 0.0, 0
    for i in range(0, len(pool), chunk):
        xb, sb = draw(series, pool[i : i + chunk], ctx)
        t0, t1 = tok.encode(xb, half=True)
        lg = model(t0[:, :-1], t1[:, :-1], sb[:, :-1, :])
        loss, _, _ = model.head.compute_loss(lg[0], lg[1], t0[:, 1:], t1[:, 1:])
        total += float(loss) * len(xb)
        seen += len(xb)
    model.train(was)
    return total / max(seen, 1)


def fit(series: list[Series], fold: int, *, scratch: bool, ctx: int, steps: int,
        batch: int, lr: float, seed: int, log=print):
    """Fine-tune (or train from scratch) one predictor on one fold's train block."""
    model, tok = kronoslib.load_pair("mini")
    if scratch:
        model.apply(model._init_weights)  # noqa: SLF001 - the published initialiser
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)

    tr_pool, va_pool = starts(series, fold, ctx)
    if len(tr_pool) < batch * 20 or len(va_pool) < 32:
        return None, {"skipped": "too few windows", "train_windows": len(tr_pool),
                      "val_windows": len(va_pool)}

    #: Fixed sets, so every evaluation point is the same question.
    fixed_tr = tr_pool[rng.choice(len(tr_pool), min(256, len(tr_pool)), replace=False)]
    fixed_va = va_pool[rng.choice(len(va_pool), min(256, len(va_pool)), replace=False)]

    opt = torch.optim.AdamW(model.parameters(), lr=lr, betas=(0.9, 0.95),
                            weight_decay=0.1)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps,
                                                pct_start=0.03, div_factor=10)
    model.train()
    curve = []
    best = (float("inf"), None)
    began = time.time()
    for step in range(steps):
        xb, sb = draw(series, tr_pool[rng.integers(0, len(tr_pool), batch)], ctx)
        with torch.no_grad():
            t0, t1 = tok.encode(xb, half=True)
        lg = model(t0[:, :-1], t1[:, :-1], sb[:, :-1, :])
        loss, _, _ = model.head.compute_loss(lg[0], lg[1], t0[:, 1:], t1[:, 1:])
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=3.0)
        opt.step()
        sched.step()

        if step % EVERY == 0 or step == steps - 1:
            lt = loss_on(model, tok, series, fixed_tr, ctx)
            lv = loss_on(model, tok, series, fixed_va, ctx)
            curve.append({"step": step, "train": round(lt, 4), "val": round(lv, 4),
                          "gap": round(lv - lt, 4)})
            if lv < best[0]:
                best = (lv, {k: v.detach().clone() for k, v in model.state_dict().items()})
            log(f"    step {step:5d}  train {lt:.4f}  val {lv:.4f}  "
                f"gap {lv-lt:+.4f}  {time.time()-began:.0f}s")

    if best[1] is not None:
        model.load_state_dict(best[1])
    model.eval()
    meta = {"curve": curve, "best_val": round(best[0], 4),
            "train_windows": len(tr_pool), "val_windows": len(va_pool),
            "steps": steps, "batch": batch, "lr": lr, "scratch": scratch,
            "seconds": round(time.time() - began, 1),
            "final_gap": curve[-1]["gap"] if curve else None}
    return model, meta


def score(series: Series, fold: int, readers: dict, *, cap: int, log=print) -> list[dict]:
    """Every arm on **identical rows**, with the three baselines beside them."""
    tr, te = series.folds[fold]
    per_fold = max(1, cap // max(len(series.folds), 1))
    stride = max(1, int(np.ceil(len(te) / per_fold)))
    te_s = te[::stride]
    if len(te_s) < 30:
        return []
    rows_te, rows_tr = series.idx[te_s], series.idx[tr]
    cal = rows_tr[:: max(1, len(rows_tr) // CAL)][:CAL]
    cal = cal[cal >= CTX - 1]

    y, x, names = series.y, series.x, series.names
    lab = y["direction"][rows_te]
    rv = y["realised"][rows_te]
    beta, smear = kronoslib.har_fit(x, names, y["realised"], rows_tr)
    base = {
        "b_mean": np.full(len(rows_te), float(np.nanmean(y["realised"][rows_tr]))),
        "b_naive": x[rows_te][:, names.index("rv1")],
        "b_har": kronoslib.har_predict(x, names, rows_te, beta, smear),
    }

    out = []
    for arm, reader in readers.items():
        got = reader.readout(series.chan, series.stamp, rows_te, batch=32)
        cg = reader.readout(series.chan, series.stamp, cal, batch=32) if len(cal) >= 40 else None
        a = (np.median(y["realised"][cal]) / np.median(cg["mean_absr"])) if cg else np.nan
        row = {
            "symbol": series.symbol, "interval": series.interval, "fold": fold,
            "arm": arm, "n": int(len(rows_te)),
            "auc_dir": round(seqlab.auc(got["mean_r"], lab), 4),
            "auc_se": round(kronoslib.boot_auc(got["mean_r"], lab), 4),
            "srel_vol": round(seqlab.srel(a * got["mean_absr"], rv), 4),
            "entropy": round(float(np.mean(got["entropy"])), 3),
        }
        for k, v in base.items():
            row[f"srel_{k}"] = round(seqlab.srel(v, rv), 4)
        out.append(row)
        log("    " + json.dumps(row, default=float))
    return out


def main() -> int:
    kronoslib.threads()
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS / "kronos_fine.jsonl"
    meta_path = RESULTS / "kronos_curves.jsonl"
    print(f"kronosfine - ctx {CTX}, {STEPS} steps, batch {BATCH}, lr {LR}, "
          f"arms {','.join(ARMS)}")
    print(f"timeframes: {', '.join(TFS)}\n", flush=True)

    zero_model, tok = kronoslib.load_pair("mini")
    v = kronoslib.verify(zero_model, tok)
    print("verify: " + json.dumps(v, default=float), flush=True)
    if not v["clean"]:
        return 1

    began = time.time()
    with out_path.open("a") as fh, meta_path.open("a") as mh:
        for interval in TFS:
            for domain, names in DOMAINS.items():
                series = []
                for sym in list(names)[: int(os.environ.get("MAXSYM", 99))]:
                    try:
                        series.append(Series(sym, interval, CTX))
                    except Exception as exc:  # noqa: BLE001
                        print(f"  skip {sym} {interval}: {type(exc).__name__}: "
                              f"{str(exc)[:80]}", flush=True)
                series = [s for s in series if s.folds]
                if not series:
                    continue
                nf = min(len(s.folds) for s in series)
                print(f"\n== {domain} {interval}: {len(series)} symbols, {nf} folds, "
                      f"{sum(s.n for s in series):,} usable rows ==", flush=True)

                for fold in range(nf):
                    print(f"  fold {fold}", flush=True)
                    readers = {}
                    if "zero" in ARMS:
                        readers["zero"] = kronoslib.Reader(zero_model, tok, ctx=CTX,
                                                           samples=SAMPLES)
                    for arm, scratch in (("fine", False), ("scratch", True)):
                        if arm not in ARMS:
                            continue
                        m, meta = fit(series, fold, scratch=scratch, ctx=CTX, steps=STEPS,
                                      batch=BATCH, lr=LR, seed=100 + fold)
                        meta.update({"domain": domain, "interval": interval,
                                     "fold": fold, "arm": arm})
                        mh.write(json.dumps(meta, default=float) + "\n")
                        mh.flush()
                        if m is not None:
                            readers[arm] = kronoslib.Reader(m, tok, ctx=CTX, samples=SAMPLES)
                    for s in series:
                        for row in score(s, fold, readers, cap=CAP):
                            row["domain"] = domain
                            fh.write(json.dumps(row, default=float) + "\n")
                        fh.flush()
                    print(f"  -- fold {fold} done, {(time.time()-began)/60:.1f}m --",
                          flush=True)

    print(f"\nwrote {out_path} and {meta_path}  ({(time.time()-began)/60:.1f}m)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
