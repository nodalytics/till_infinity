"""Retrain the offline models on fresh bars; promote a challenger only when it beats the champion.

Models moved from online learning to offline training (see `shared/frozen.py`) go stale unless
retrained, and a retrain shipped because it is newer rather than better is how a working model gets
replaced by a broken one. So each run is a contest, judged on data neither model was trained on:

  1. fetch     up to 50,000 bars per series from the terminal (`bridge.py`)
  2. hold out  the most recent `HOLDOUT_DAYS` of every series
  3. train     the challenger on everything before the hold-out
  4. score     challenger and champion - the model in service - on the hold-out
  5. promote   only if every gate in `GATES` passes: write `<models dir>/<name>.json`, which the
               engine re-reads within five minutes (`frozen.RECHECK`) with no restart; append the
               run to `<name>.report.jsonl` either way, and publish a card when a bus is given

The promoted model was trained without the hold-out, and that is deliberate: the model that ships is
exactly the one that was scored. The gates are fixed here, before any run.

Run as a service (`till-infinity models retrain --every-days 14`) or once (`--once`). Training needs
the `train` extra (scikit-learn); the engine that reads the result does not.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import numpy as np

from ..logging import get_logger
from ..shared import frozen

log = get_logger(__name__)

HOLDOUT_DAYS = 14

GATES: dict[str, Any] = {
    # on real markets and on Deriv alike: not worse than the model in service on the same fresh
    # weeks, by more than this or two standard errors, whichever is wider - two weeks of one
    # family is a small sample, and noise must not block every promotion
    "vs_champion": 0.01,
    # on our own memoryless walks, where the answer is known: no further from 0.5 than this
    "control_band": 0.03,
    # worth publishing at all
    "min_real_auc": 0.65,
    # top decile's realised over predicted rate: what a card's "3x normal" relies on
    "calibration": (0.7, 1.4),
    # the dependency-free evaluator must reproduce the training library
    "exact": 1e-9,
}


def symbols() -> list[str]:
    """The instruments to train on: `MODELS_SYMBOLS`, else the broker book."""
    raw = os.environ.get("MODELS_SYMBOLS") or os.environ.get("PRICES_BROKER_SYMBOLS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def gate(challenger: dict, champion: dict) -> list[str]:
    """Every reason not to promote; empty means promote."""
    reasons = []
    real = challenger.get("real", float("nan"))
    if not real >= GATES["min_real_auc"]:
        reasons.append(f"real-market AUC {real} below {GATES['min_real_auc']}")
    # Deriv is a market, not a control: what we score is the whole feed as served, and 1h
    # Volatility indices score 0.70 held out. So it is held to the same standard as the rest.
    for market in ("real", "deriv"):
        mine, theirs = challenger.get(market), champion.get(market)
        if mine is None or theirs is None or math.isnan(theirs):
            continue
        se = challenger.get(f"{market}_se", float("nan"))
        slack = max(GATES["vs_champion"], 2 * se) if not math.isnan(se) else GATES["vs_champion"]
        if math.isnan(mine) or mine < theirs - slack:
            reasons.append(
                f"{market} AUC {mine} against the champion's {theirs} (slack {slack:.3f})"
            )
    # The control is only the walks we generate ourselves, whose process we know.
    control = challenger.get("control")
    if control is not None and not abs(control - 0.5) <= GATES["control_band"]:
        reasons.append(
            f"control AUC {control} on memoryless walks, not 0.5 +- {GATES['control_band']}"
        )
    lo, hi = GATES["calibration"]
    cal = challenger.get("calibration", float("nan"))
    if not lo <= cal <= hi:
        reasons.append(f"top-decile calibration {cal} outside {lo}-{hi}")
    return reasons


def run_shocks(fetch: Callable[[str, str], list], names: list[str]) -> tuple[dict | None, dict]:
    """One contest for the shock forecaster. Returns (spec to promote or None, report)."""
    from ..structures.learning import shocks as sh
    from . import shocks_train as st

    series = {}
    for symbol in names:
        for interval in ("15m", "1h"):
            got = fetch(symbol, interval)
            if len(got) > 2 * sh.NORM:
                series[(symbol, interval)] = got
    rows = st.dataset(series)
    when, kinds, x, y = rows.arrays()
    if len(y) == 0:
        return None, {"series": len(series), "promoted": False, "reasons": ["no usable history"]}
    cut = when.max() - HOLDOUT_DAYS * 86_400
    train, held = when < cut, when >= cut
    spec = st.train(x[train], y[train])
    model = spec.pop("_sklearn")
    trees = frozen.Trees(spec)
    sample = x[held][:5_000]
    exact = (
        float(
            np.max(
                np.abs(
                    np.array([trees.predict(list(r)) for r in sample])
                    - model.predict_proba(sample)[:, 1]
                )
            )
        )
        if len(sample)
        else 0.0
    )
    _, ck, cx, cy = st.dataset(st.controls()).arrays()  # never trained on: all of it is held out
    xs, ys, ks = (
        np.vstack([x[held], cx]),
        np.concatenate([y[held], cy]),
        np.concatenate([kinds[held], ck]),
    )
    challenger = st.score(trees.predict, xs, ys, ks)
    current = frozen.load(sh.MODEL, recipe=sh.RECIPE, names=sh.NAMES)
    champion = st.score(frozen.Trees(current).predict, xs, ys, ks) if current else {}
    reasons = gate(challenger, champion)
    if exact > GATES["exact"]:
        reasons.append(f"evaluator differs from the training library by {exact:.2e}")
    spec["test"] = challenger
    spec["holdout_from"] = datetime.fromtimestamp(cut, UTC).isoformat(timespec="seconds")
    report = {
        "series": len(series),
        "challenger": challenger,
        "champion": champion,
        "promoted": not reasons,
        "reasons": reasons,
        "evaluator_max_diff": exact,
    }
    return (spec if not reasons else None), report


REGISTRY: dict[str, Callable[..., tuple[dict | None, dict]]] = {"shocks": run_shocks}


def run_once(name: str, fetch: Callable[[str, str], list], names: list[str]) -> dict:
    """Run one model's contest, write the promoted model and the report, and return the report."""
    out = frozen.models_dir()
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    spec, report = REGISTRY[name](fetch, names)
    report = {
        "model": name,
        "started": started,
        "finished": datetime.now(UTC).isoformat(timespec="seconds"),
        **report,
    }
    if spec is not None:
        tmp = out / f"{name}.json.tmp"
        tmp.write_text(json.dumps(spec, separators=(",", ":")))
        tmp.replace(out / f"{name}.json")  # atomic: the engine never reads half a file
        frozen.forget_cache()
    with (out / f"{name}.report.jsonl").open("a") as fh:
        fh.write(json.dumps(report) + "\n")
    log.info(
        "models: %s %s", name, "promoted" if report["promoted"] else f"kept: {report['reasons']}"
    )
    return report


def card(report: dict) -> dict:
    """A notification for one run: what was promoted, or why the champion stayed."""
    promoted = report.get("promoted")
    c, k = report.get("challenger", {}), report.get("champion", {})
    lines = [
        f"🧪 {report['model']} retrained on {report.get('series', 0)} series",
        f"challenger AUC real {c.get('real', 'n/a')}"
        f" · deriv {c.get('deriv', 'n/a')} · control {c.get('control', 'n/a')}"
        f" · top-decile calibration {c.get('calibration', 'n/a')}",
        f"champion AUC real {k.get('real', 'n/a')} · deriv {k.get('deriv', 'n/a')}",
        "✅ promoted - live within five minutes"
        if promoted
        else "↩️ kept the champion: " + "; ".join(report.get("reasons", [])),
    ]
    return {
        "title": f"models: {report['model']} {'promoted' if promoted else 'kept'}",
        "body": "\n".join(lines),
        "level": "info",
        "fields": {"shape": "models", "model": report["model"]},
    }


def watch(
    every_days: float,
    fetch: Callable[[str, str], list],
    names: list[str],
    publish: Callable[[dict], None] | None = None,
    *,
    once: bool = False,
    only: Sequence[str] | None = None,
) -> None:
    """Retrain every model (or `only` these) when due, then every `every_days`, forever.

    The time of the last run is kept on disk, so a restarted service waits out the rest of the
    fortnight rather than retraining on every deploy."""
    state = frozen.models_dir() / "retrain.last"
    while True:
        last = float(state.read_text()) if state.exists() else 0.0
        due = last + every_days * 86_400
        if once or time.time() >= due:
            for name in only or REGISTRY:
                try:
                    report = run_once(name, fetch, names)
                except Exception as exc:  # one model's failure must not stop the next run
                    log.exception("models: %s retrain failed", name)
                    report = {"model": name, "promoted": False, "reasons": [f"failed: {exc}"]}
                if publish is not None:
                    publish(card(report))
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(f"{time.time():.0f}")
            if once:
                return
        time.sleep(min(3600.0, max(60.0, due - time.time())))
