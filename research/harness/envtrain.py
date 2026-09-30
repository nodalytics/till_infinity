"""Train the initial boosted-envelope models (`structures/vol/envelope.py`, FX 15m) from the lab.

The production trainer (`models/envelope_train.py`) does the replay, the fit and the scoring; this
feeds it the lab's FX 15m history and reports three ways per horizon:

  block    the first 60% by time trains, the last 40% scores: one fit, against gbm-envelope.md's
           fortnightly refits (FX pinball -3.4 / -4.2 / -6.6% at N = 5 / 20 / 50)
  ships    everything but the last 14 days trains, the 14 days score - the model that ships,
           judged by `models/retrain.py`'s gates, the 90-day slice gate included
  cost     the spec's size and the per-bar cost of reading it

and writes the shipped spec to OUT (default .data/envelope_models/).

Run on the lab, one process per horizon:
  HORIZON=20 SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/envtrain.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from fractal_twins import FAMILIES

from till_infinity.models import envelope_train as et
from till_infinity.models import retrain as rt
from till_infinity.prices.models import Bar
from till_infinity.shared import frozen
from till_infinity.structures.vol import envelope as ev

OUT = Path(os.environ.get("OUT", ".data/envelope_models"))
HORIZON = int(os.environ.get("HORIZON", "20"))
DOC = {5: -0.034, 20: -0.042, 50: -0.066}


def bars(sym: str) -> list[Bar]:
    df = spikerisk.load(None, sym, "SEQLAB", "15m")
    return [
        Bar(int(t), float(o), float(h), float(lo), float(c))
        for t, o, h, lo, c in zip(
            df["ts"], df["open"], df["high"], df["low"], df["close"], strict=True
        )
    ]


def show(label: str, mine: dict, theirs: dict, vs: dict) -> None:
    m, t = et.summary(mine), et.summary(theirs)
    print(
        f"    {label}: pinball {vs['relative']:+.2%} [{vs['low']:+.2%}, {vs['high']:+.2%}] vs history | "
        f"cover {m['p10']:.1%}/{m['p50']:.1%}/{m['p90']:.1%} (history {t['p10']:.1%}/{t['p50']:.1%}/"
        f"{t['p90']:.1%}) | P90 by vol third {'/'.join(f'{v:.1%}' for v in m['p90_thirds'])} (history "
        f"{'/'.join(f'{v:.1%}' for v in t['p90_thirds'])}) | width {m['width']:.2f} vs {t['width']:.2f} | "
        f"n {m['n']:,}",
        flush=True,
    )


def main() -> None:
    t0 = time.time()
    series = {}
    for sym in FAMILIES["fx"]:
        try:
            series[(sym, "15m")] = bars(sym)
        except (ValueError, FileNotFoundError) as exc:
            print(f"  skip {sym}: {str(exc)[:60]}", flush=True)
    found = et.tracks(series)
    when, x, y = et.rows(found, HORIZON)
    print(
        f"N = {HORIZON}: {len(found)} FX 15m series, {len(y):,} rows ({time.time() - t0:.0f}s)",
        flush=True,
    )

    split = float(np.quantile(when, 0.6))
    spec = et.train(when[when < split], x[when < split], y[when < split], HORIZON)
    spec.pop("_sklearn")
    model, history = et.scored(found, HORIZON, [spec, None], split)
    show(f"block (last 40%, doc {DOC[HORIZON]:+.1%})", model, history, et.compare(model, history))
    print(
        f"      worst 14-day P90 {et.worst_window(model, split):.1%} (history "
        f"{et.worst_window(history, split):.1%}) ({time.time() - t0:.0f}s)",
        flush=True,
    )

    cut = when.max() - rt.HOLDOUT_DAYS * 86_400
    spec = et.train(when[when < cut], x[when < cut], y[when < cut], HORIZON)
    fitted = spec.pop("_sklearn")
    exact = et.exactness(spec, fitted, x[when >= cut][:2_000])
    model, history = et.scored(found, HORIZON, [spec, None], cut)
    challenger = et.summary(model)
    challenger["vs_empirical"] = et.compare(model, history)
    show("ships (last 14 days)", model, history, challenger["vs_empirical"])
    early = when.max() - et.SLICE_DAYS * 86_400
    judge = et.train(when[when < early], x[when < early], y[when < early], HORIZON)
    judge.pop("_sklearn")
    sm, sh = et.scored(found, HORIZON, [judge, None], early)
    challenger["vs_empirical_slice"] = et.compare(sm, sh)
    challenger["worst_window"] = round(et.worst_window(sm, early), 4)
    challenger["empirical_worst_window"] = round(et.worst_window(sh, early), 4)
    show("slice block (last 90 days, judge)", sm, sh, et.compare(sm, sh))
    reasons = rt.envelope_gate(challenger)
    print(
        f"      worst 14-day P90 over 90 days {challenger['worst_window']:.1%} (history "
        f"{challenger['empirical_worst_window']:.1%}) | exact {exact:.1e} | gates: "
        f"{'pass' if not reasons else '; '.join(reasons)} ({time.time() - t0:.0f}s)",
        flush=True,
    )

    spec["test"] = challenger
    spec["evaluator_max_diff"] = exact
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{ev.MODELS[HORIZON]}.json"
    path.write_text(json.dumps(spec, separators=(",", ":")))
    q = frozen.Quantiles(spec)
    sample = [list(r) for r in x[:2_000]]
    t1 = time.perf_counter()
    for r in sample:
        q.predict(r)
    per = (time.perf_counter() - t1) / len(sample) * 1e6
    print(
        f"    cost: {path.stat().st_size / 1e6:.2f} MB, {per:.0f} us per bar; wrote {path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
