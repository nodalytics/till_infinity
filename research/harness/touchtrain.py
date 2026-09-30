"""Train the initial band-touch models (`structures/learning/touches.py`) from the lab's FX 15m bars.

The production trainer (`models/touches_train.py`) does the replay, the fit and the scoring; this
feeds it the lab's history and reports twice:

  bandrace's split  the first 60% by time trains, the last 40% scores - the design
                    `research/docs/bandrace.md` measured +0.087 / +0.059 skill over geometry on
  retrain's split   everything but the last 14 days trains, the 14 days score - the model that
                    ships, judged the way `models/retrain.py` will judge its successors

and writes the shipped specs to OUT (default .data/touch_models/).

Run on the lab:
  SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/touchtrain.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from fractal_twins import FAMILIES

from till_infinity.models import touches_train as tt
from till_infinity.prices.models import Bar
from till_infinity.shared import frozen
from till_infinity.structures.learning import touches as tc

OUT = Path(os.environ.get("OUT", ".data/touch_models"))
HOLDOUT_DAYS = 14


def bars(sym: str) -> list[Bar]:
    df = spikerisk.load(None, sym, "SEQLAB", "15m")
    return [Bar(int(t), float(o), float(h), float(lo), float(c))
            for t, o, h, lo, c in zip(df["ts"], df["open"], df["high"], df["low"], df["close"],
                                      strict=True)]


def contest(x, y, when, train, held, label):
    spec = tt.train(x[train], y[train])
    model = spec.pop("_sklearn")
    trees = frozen.Trees(spec)
    p = np.array([trees.predict(list(r)) for r in x[held]])
    exact = float(np.max(np.abs(p[:5000] - model.predict_proba(x[held][:5000])[:, 1])))
    geo = tt.geometry(x[train], y[train])(x[held])
    got = tt.score(p, geo, y[held], when[held])
    print(f"    {label:22s} skill over geometry {got['skill']:+.4f} (se {got['skill_se']:.4f}) | "
          f"calibration worst decile {got['calibration']:.1%} | rate {got['rate']:.3f} | "
          f"n {got['n']:,} | exact {exact:.1e}", flush=True)
    return spec, got, exact


def contests() -> None:
    """PART=contest: the production retrain contests themselves on seqlab FX 15m, writing only
    what they promote - so what ships is exactly what the pipeline would ship."""
    from till_infinity.models import retrain as rt

    names = list(FAMILIES["fx"])
    cache: dict[str, list] = {}

    def fetch(symbol: str, interval: str) -> list:
        if interval != "15m":
            return []
        if symbol not in cache:
            try:
                cache[symbol] = bars(symbol)
            except (ValueError, FileNotFoundError):
                cache[symbol] = []
        return cache[symbol]

    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("touch90_fx15m", "touch10_fx15m"):
        spec, report = rt.REGISTRY[name](fetch, names)
        c = report.get("challenger", {})
        print(f"{name}: promoted {report['promoted']} | skill over rate {c.get('skill_rate')} "
              f"(se {c.get('skill_rate_se')}) | over geometry {c.get('skill')} | calibration fails "
              f"{c.get('calibration_fails')} | 14d worst decile {c.get('calibration')} | reasons "
              f"{report['reasons']}", flush=True)
        for d in c.get("calibration_table", []):
            print(f"    {d}", flush=True)
        if spec is not None:
            (OUT / f"{name}.json").write_text(json.dumps(spec, separators=(",", ":")))


def main() -> None:
    series = {}
    for sym in FAMILIES["fx"]:
        try:
            series[(sym, "15m")] = bars(sym)
        except (ValueError, FileNotFoundError) as exc:
            print(f"  skip {sym}: {str(exc)[:60]}", flush=True)
    print(f"{len(series)} FX 15m series", flush=True)
    rows = tt.dataset(series)
    when, x, y90, y10 = rows.arrays()
    print(f"{len(when):,} rows · touch90 rate {y90.mean():.3f} · touch10 rate {y10.mean():.3f}", flush=True)
    split = np.quantile(when, 0.6)
    cut = when.max() - HOLDOUT_DAYS * 86_400
    OUT.mkdir(parents=True, exist_ok=True)
    for band, y in (("touch90", y90), ("touch10", y10)):
        print(f"\n  {band}", flush=True)
        contest(x, y, when, when < split, when >= split, "60/40 (bandrace's)")
        spec, got, exact = contest(x, y, when, when < cut, when >= cut, "last 14 days (ships)")
        spec["test"] = got
        spec["evaluator_max_diff"] = exact
        (OUT / f"{tc.MODELS[band]}.json").write_text(json.dumps(spec, separators=(",", ":")))
    print(f"\nwrote {', '.join(tc.MODELS.values())} to {OUT}", flush=True)


if __name__ == "__main__":
    contests() if os.environ.get("PART") == "contest" else main()
