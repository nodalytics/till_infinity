"""Get Kronos onto the lab, prove the plumbing, and price the run before trusting a number.

**Nothing in this file is a finding.** It exists because a foundation model is a
large opaque object pulled off someone else's hub, and `research/rebuilding.md`'s
record on this project is that every confident false positive it caught came from
a pipeline defect rather than from a model: three inflation bugs, a pooled split
that scored 0.96 on feed identity alone, and a specification whose own published
moments miss their closure by 6-12%. A score from a model whose example has never
been reproduced on this machine is not a measurement, it is a hope.

So this script does four things and reports all four, and `kronos.py` refuses to
run until it has:

1. **Vendor the upstream repo outside the git tree.** `~/till_infinity/vendor/Kronos`,
   not `repo/`. `lab.sh sync` runs `rsync --delete` over `repo/`, so anything
   checked out in-tree is deleted on the next sync and the run dies half way with
   an import error that looks like a code bug.
2. **Pull the weights and print what they weigh**, because "did you get it running
   and what did it cost" is half the question this arm was commissioned to answer.
3. **Reproduce the upstream published example.** `examples/prediction_example.py`
   verbatim in structure - `KronosPredictor.predict` at lookback 400, pred_len 120,
   T=1.0, top_p=0.9 - on a K-line CSV that ships with the repo, for both the
   published `small`/`Tokenizer-base` pair and the `mini`/`Tokenizer-2k` pair this
   study fine-tunes. The check is not "is the forecast good"; it is that the
   forecast is finite, continuous with the last observed close, and carries a
   realised volatility inside a factor of three of the truth it was not shown.
   A tokenizer loaded against the wrong model fails all three loudly.
4. **Benchmark the CPU cost**, so the grid in `kronos.py` is sized against a
   measured rate rather than a guess. The lab has no GPU and five other agents on
   it; the thread cap is not advisory.

## The published identifiers, verified rather than remembered

Read off the upstream README and the hub configs on 2026-09-12, not from memory:

    NeoQuasar/Kronos-mini   4.1M   d_model 256, 4 layers, 4 heads, ff 512, s1/s2 10/10 bits
    NeoQuasar/Kronos-small  24.7M  d_model 512, 8 layers
    NeoQuasar/Kronos-Tokenizer-2k    d_in 6, d_model 256, 4 enc / 4 dec layers, group_size 5
    NeoQuasar/Kronos-Tokenizer-base  same but group_size 4

`mini` pairs with `Tokenizer-2k` and every other size with `Tokenizer-base`. Both
tokenizers emit a 20-bit code split into two 10-bit sub-tokens, so the model's
vocabulary is 1024 x 1024 and a full enumeration of the next-step distribution is
out of reach - which is why `kronoslib` samples and why it caches the decoder.

    ./.secrets/lab.sh run research/harness/kronosboot.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

#: Where upstream lives on the lab. **Outside `repo/`**, for the reason above.
VENDOR = Path.home() / "till_infinity" / "vendor"
KRONOS_DIR = VENDOR / "Kronos"
UPSTREAM = "https://github.com/shiyu-coder/Kronos.git"

#: The pairs, by the hub's own spelling. Order matters only for the report.
PAIRS = {
    "mini": ("NeoQuasar/Kronos-mini", "NeoQuasar/Kronos-Tokenizer-2k"),
    "small": ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base"),
}

#: The K-line file the upstream repo actually ships. `examples/prediction_example.py`
#: reads `./data/XSHG_5min_600977.csv`, which is **not in the repository** - the
#: example as published cannot run without a file its author did not commit. This
#: one is real 5-minute Hong Kong equity data from the `finetune_csv` demo and is
#: the same shape, so the example runs unmodified apart from the path.
DEMO_CSV = "finetune_csv/data/HK_ali_09988_kline_5min_all.csv"

THREADS = 8


def vendor(*, refresh: bool = False) -> Path:
    """Clone or update upstream. Returns the path that must go on `sys.path`."""
    VENDOR.mkdir(parents=True, exist_ok=True)
    if not (KRONOS_DIR / ".git").exists():
        subprocess.run(["git", "clone", "--depth", "1", UPSTREAM, str(KRONOS_DIR)],
                       check=True, capture_output=True)
    elif refresh:
        subprocess.run(["git", "-C", str(KRONOS_DIR), "pull", "--ff-only"],
                       check=True, capture_output=True)
    head = subprocess.run(["git", "-C", str(KRONOS_DIR), "log", "--oneline", "-1"],
                          check=True, capture_output=True, text=True).stdout.strip()
    print(f"upstream: {KRONOS_DIR}  @ {head}")
    return KRONOS_DIR


def load(which: str):
    """The model pair, on CPU, in eval mode. Weights land in the HF cache."""
    sys.path.insert(0, str(KRONOS_DIR))
    from model import Kronos, KronosTokenizer  # noqa: PLC0415 - path set above

    model_id, tok_id = PAIRS[which]
    began = time.time()
    tokenizer = KronosTokenizer.from_pretrained(tok_id)
    model = Kronos.from_pretrained(model_id)
    took = time.time() - began
    tokenizer.eval(), model.eval()
    n_m = sum(p.numel() for p in model.parameters())
    n_t = sum(p.numel() for p in tokenizer.parameters())
    print(f"{which}: {model_id} {n_m/1e6:.2f}M params, {tok_id} {n_t/1e6:.2f}M  "
          f"(loaded in {took:.1f}s)")
    return model, tokenizer, n_m, n_t


def demo_frame(rows: int):
    import pandas as pd  # noqa: PLC0415

    df = pd.read_csv(KRONOS_DIR / DEMO_CSV)
    df["timestamps"] = pd.to_datetime(df["timestamps"], format="mixed")
    return df.iloc[:rows].reset_index(drop=True)


def reproduce(which: str, *, lookback: int = 400, pred_len: int = 120) -> dict:
    """The upstream example, with the held-out truth scored rather than plotted.

    Upstream plots the forecast against the truth and calls that the check. A plot
    is not a check on a headless box, so the three properties a working pipeline
    must have are asserted instead:

    * **finite** - a tokenizer paired with the wrong model produces NaN here,
      because the codebook widths disagree and `indices_to_bits` silently wraps;
    * **continuous** - the first forecast bar within a few percent of the last
      observed close, which fails the moment the per-window normalisation is
      inverted with the wrong mean;
    * **scaled** - forecast realised volatility inside a factor of three of the
      truth's, which is the loosest band that still catches a dead sampler
      returning a flat line.
    """
    import pandas as pd  # noqa: PLC0415
    import torch  # noqa: PLC0415

    sys.path.insert(0, str(KRONOS_DIR))
    from model import KronosPredictor  # noqa: PLC0415

    model, tokenizer, n_m, n_t = load(which)
    predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)

    df = demo_frame(lookback + pred_len)
    cols = ["open", "high", "low", "close", "volume", "amount"]
    x_df = df.loc[: lookback - 1, cols]
    x_stamp = df.loc[: lookback - 1, "timestamps"]
    y_stamp = df.loc[lookback : lookback + pred_len - 1, "timestamps"]

    torch.manual_seed(7)
    began = time.time()
    pred = predictor.predict(df=x_df, x_timestamp=x_stamp, y_timestamp=y_stamp,
                             pred_len=pred_len, T=1.0, top_p=0.9, sample_count=1,
                             verbose=False)
    took = time.time() - began

    truth = df.loc[lookback : lookback + pred_len - 1, "close"].to_numpy()
    last = float(df.loc[lookback - 1, "close"])
    fc = pred["close"].to_numpy()
    rv_true = float(np.std(np.diff(np.log(truth))))
    rv_pred = float(np.std(np.diff(np.log(np.maximum(fc, 1e-9)))))
    jump = abs(fc[0] / last - 1.0)
    ratio = rv_pred / max(rv_true, 1e-12)

    out = {
        "pair": which, "params_model": n_m, "params_tokenizer": n_t,
        "seconds": round(took, 2), "lookback": lookback, "pred_len": pred_len,
        "finite": bool(np.isfinite(fc).all()),
        "first_step_jump": round(float(jump), 4),
        "rv_pred_over_true": round(ratio, 3),
        "mape_close": round(float(np.mean(np.abs(fc / truth - 1.0))), 4),
        "hit_rate_direction": round(float(np.mean(
            (np.diff(np.concatenate(([last], fc))) > 0)
            == (np.diff(np.concatenate(([last], truth))) > 0))), 4),
    }
    out["ok"] = bool(out["finite"] and jump < 0.05 and 1 / 3 < ratio < 3)
    print(json.dumps(out, default=float))
    return out


def benchmark(which: str = "mini") -> dict:
    """What one context window costs, so the grid can be sized rather than guessed."""
    import torch  # noqa: PLC0415

    model, tokenizer, _, _ = load(which)
    rates = {}
    for ctx in (64, 128, 256, 512):
        x = torch.randn(16, ctx, 6)
        stamp = torch.zeros(16, ctx, 5)
        with torch.no_grad():
            tokenizer.encode(x, half=True)  # warm
            began = time.time()
            for _ in range(3):
                s1, s2 = tokenizer.encode(x, half=True)
                logits, ctxt = model.decode_s1(s1, s2, stamp)
                model.decode_s2(ctxt[:, -1:, :], s1[:, -1:])
                tokenizer.decode([s1, s2], half=True)
            took = (time.time() - began) / 3
        rates[ctx] = round(16.0 / took, 1)
        print(f"  ctx {ctx:4d}: {took*1000:7.1f} ms / batch of 16 "
              f"-> {rates[ctx]:8.1f} windows/s on {THREADS} threads")
    return rates


def main() -> int:
    import torch  # noqa: PLC0415

    torch.set_num_threads(THREADS)
    os.environ.setdefault("OMP_NUM_THREADS", str(THREADS))
    print(f"kronosboot - torch {torch.__version__}, {THREADS} threads, "
          f"cuda {torch.cuda.is_available()}\n")

    vendor()
    results = {"upstream": str(KRONOS_DIR), "torch": torch.__version__}

    print("\n-- upstream published example, reproduced --")
    for which in ("mini", "small"):
        try:
            results[f"example_{which}"] = reproduce(which)
        except Exception as exc:  # noqa: BLE001 - the point is to report the failure
            print(f"  ! {which} failed: {type(exc).__name__}: {exc}")
            results[f"example_{which}"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    print("\n-- cost --")
    results["windows_per_second"] = benchmark("mini")

    out = Path.home() / "till_infinity" / "results" / "kronosboot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, default=float))
    print(f"\nwrote {out}")
    ok = all(results.get(f"example_{w}", {}).get("ok") for w in ("mini", "small"))
    print("PLUMBING OK" if ok else "PLUMBING NOT PROVEN - do not read any score from this model")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
