"""What the look-ahead would have been worth, measured rather than asserted.

`kronos.py` claims its Kronos readout is causal: the tokenizer is causal by
architecture and every normalisation constant is computed inside a window that
ends at the row being scored. A claim like that is cheap. **This file prices
it** - it runs the same model, on the same rows, with the normalisation
deliberately contaminated in the two ways this class of study actually gets
contaminated, and reports the AUC each one manufactures.

The two contaminations:

* **`future`** - the normalisation mean and standard deviation are taken over
  `[t-ctx+1 .. t+1]` instead of `[t-ctx+1 .. t]`. The model still sees only bars
  up to `t`; only the *constants* that scale them carry the bar being predicted.
  This is the classic off-by-one: it survives a code review, it survives a
  feature-level causality assertion that only inspects the features, and it is
  invisible in a loss curve.
* **`global`** - mean and standard deviation over the whole series, computed once
  before the split. This is what "fit the scaler, then split" does, and it is the
  form the brief names as the single most likely way this arm produces a false
  positive.

Both are run against **`causal`**, which is exactly what `kronos.py` reports, on
identical rows with identical folds and an identical sample stream.

If `future` scores at the null, the off-by-one is harmless here and the study's
care was insurance. If it scores well above the null, then the number on this
page is the size of the false positive that this arm avoided, and it is the most
useful thing on it.

    ./.secrets/lab.sh run research/harness/kronosleak.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

from research.harness import kronos as kz
from research.harness import kronoslib, seqlab

RESULTS = Path.home() / "till_infinity" / "results"

CTX = int(os.environ.get("CTX", 128))
SAMPLES = int(os.environ.get("SAMPLES", 64))
CAP = int(os.environ.get("CAP", 1500))
#: Four cells: two constant-sigma synthetics where the truth is 0.50 by
#: construction, and two real markets where it is not quite.
CELLS = tuple(os.environ.get("CELLS",
              "Volatility_75_Index,Volatility_100_Index,XAUUSD,EURUSD").split(","))
TF = os.environ.get("TF", "1h")


def stats_for(chan: np.ndarray, ctx: int, mode: str):
    """The normalisation constants each arm uses, as a function of the scored rows."""
    if mode == "global":
        m = chan.mean(axis=0)[None, None, :]
        s = chan.std(axis=0)[None, None, :]
        return lambda ends: (np.repeat(m, len(ends), axis=0), np.repeat(s, len(ends), axis=0))
    if mode == "future":
        def fn(ends):
            take = np.asarray(ends)[:, None] - np.arange(ctx - 1, -1, -1)[None, :] + 1
            w = chan[np.clip(take, 0, len(chan) - 1)]
            return w.mean(axis=1, keepdims=True), w.std(axis=1, keepdims=True)
        return fn
    raise ValueError(mode)


def run(symbol: str, interval: str, reader: kronoslib.Reader, log=print) -> list[dict]:
    bars = seqlab.load(symbol, interval)
    x, names, y, idx = kz.prepare(bars, reader.ctx)
    folds = seqlab.walk_forward(len(idx), folds=5, horizon=1)
    chan, stamp = kronoslib.frame(bars)
    total = sum(len(te) for _, te in folds)
    stride = max(1, int(np.ceil(total / CAP)))

    rows_te = np.concatenate([idx[te[::stride]] for _, te in folds])
    rows_te = rows_te[rows_te < len(chan) - 1]
    lab = y["direction"][rows_te]
    rv = y["realised"][rows_te]

    out = []
    for mode in ("causal", "future", "global"):
        fn = None if mode == "causal" else stats_for(chan, reader.ctx, mode)
        began = time.time()
        got = reader.readout(chan, stamp, rows_te, batch=32, stats_fn=fn)
        a = np.median(rv) / np.median(got["mean_absr"])
        row = {
            "symbol": symbol, "interval": interval, "normalisation": mode,
            "n": int(len(rows_te)),
            "auc_dir": round(seqlab.auc(got["mean_r"], lab), 4),
            "auc_se": round(kronoslib.boot_auc(got["mean_r"], lab), 4),
            "auc_dir_raw": round(seqlab.auc(got["mean_raw"], lab), 4),
            "srel_vol": round(seqlab.srel(a * got["mean_absr"], rv), 4),
            "entropy": round(float(np.mean(got["entropy"])), 3),
            "seconds": round(time.time() - began, 1),
        }
        log("  " + json.dumps(row, default=float))
        out.append(row)
    return out


def main() -> int:
    kronoslib.threads()
    RESULTS.mkdir(parents=True, exist_ok=True)
    model, tok = kronoslib.load_pair("mini")
    v = kronoslib.verify(model, tok)
    print("verify: " + json.dumps(v, default=float), flush=True)
    if not v["clean"]:
        return 1
    reader = kronoslib.Reader(model, tok, ctx=CTX, samples=SAMPLES)

    rows = []
    for token in CELLS:
        symbol = token.replace("_", " ")
        print(f"\n{symbol} {TF}", flush=True)
        try:
            rows += run(symbol, TF, reader)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {type(exc).__name__}: {str(exc)[:120]}", flush=True)
    (RESULTS / "kronos_leak.json").write_text(json.dumps(rows, indent=2, default=float))
    print(f"\nwrote {RESULTS / 'kronos_leak.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
