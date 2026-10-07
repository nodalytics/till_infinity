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


#: The band-touch forecaster's gates (`structures/learning/touches.py`, research/docs/bandrace.md).
TOUCH_GATES: dict[str, float] = {
    # Brier skill over the training base rate - the constant the card would otherwise print. It
    # was skill over geometry (the band distances alone) while the bands were the empirical
    # envelope's; the boosted FX envelope now carries the volatility state itself, so the touch
    # model adds little over geometry (+0.011 / +0.017) while still pricing the touch well. What
    # the card line needs is a calibrated probability that beats the flat rate.
    "min_skill": 0.03,
}

#: One replay serves both bands' contests in a run: (fetch, names, hour) -> (series count, rows).
_touch_rows: dict[tuple[int, tuple[str, ...], int], tuple[int, Any]] = {}


def touch_gate(challenger: dict, champion: dict) -> list[str]:
    """Every reason not to promote a band-touch model; empty means promote."""
    reasons = []
    skill = challenger.get("skill_rate", float("nan"))
    if not skill >= TOUCH_GATES["min_skill"]:
        reasons.append(f"skill over the base rate {skill} below {TOUCH_GATES['min_skill']}")
    # What "P90 touched 38%" relies on, judged over 90 days out of sample, where one regime
    # cannot pass for a bad model (`touches_train.CAL_*` says why each number is what it is).
    from .touches_train import CAL_DAYS, CAL_TOLERATED

    bad = challenger.get("calibration_fails", float("nan"))
    if not bad <= CAL_TOLERATED:  # a missing count (nan) fails too
        reasons.append(
            f"{bad} decile(s) miscalibrated over {CAL_DAYS} days, beyond 20% and two standard"
            f" errors (at most {CAL_TOLERATED} tolerated)"
        )
    theirs = champion.get("skill_rate")
    if theirs is not None and not math.isnan(theirs):
        se = challenger.get("skill_rate_se", float("nan"))
        slack = max(GATES["vs_champion"], 2 * se) if not math.isnan(se) else GATES["vs_champion"]
        if skill < theirs - slack:
            reasons.append(f"skill {skill} against the champion's {theirs} (slack {slack:.3f})")
    return reasons


def _touch_contest(band: str, fetch: Callable[[str, str], list], names: list[str]):
    """One contest for one band's touch model. Returns (spec to promote or None, report)."""
    from ..structures import rollover as ro
    from ..structures.learning import touches as tc
    from . import touches_train as tt

    # Keyed by the hour too: the service reuses one fetch across fortnights, and a replay must not
    # outlive the run it was made for.
    key = (id(fetch), tuple(names), int(time.time() // 3600))
    if key not in _touch_rows:
        _touch_rows.clear()
        series = {}
        for symbol in names:
            if ro.is_fx(symbol):
                got = fetch(symbol, tc.INTERVAL)
                if len(got) > 2 * tc.NORM:
                    series[(symbol, tc.INTERVAL)] = got
        _touch_rows[key] = (len(series), tt.dataset(series).arrays())
    count, (when, x, y90, y10) = _touch_rows[key]
    y = y90 if band == "touch90" else y10
    if len(y) == 0:
        return None, {"series": count, "promoted": False, "reasons": ["no usable FX 15m history"]}
    cut = when.max() - HOLDOUT_DAYS * 86_400
    train, held = when < cut, when >= cut
    if not held.any() or not train.any():
        return None, {"series": count, "promoted": False, "reasons": ["too little history"]}
    spec = tt.train(x[train], y[train])
    model = spec.pop("_sklearn")
    trees = frozen.Trees(spec)
    sample = x[held][:5_000]
    exact = float(
        np.max(
            np.abs(
                np.array([trees.predict(list(r)) for r in sample])
                - model.predict_proba(sample)[:, 1]
            )
        )
    )
    geo = tt.geometry(x[train], y[train])(x[held])
    p = np.array([trees.predict(list(r)) for r in x[held]])
    base = float(y[train].mean())
    challenger = tt.score(p, geo, y[held], when[held], base=base)
    # Calibration over a longer out-of-sample block, by a model trained before it.
    early = when < when.max() - tt.CAL_DAYS * 86_400
    if early.any() and (~early).any():
        judge = tt.train(x[early], y[early])
        judge.pop("_sklearn")
        jt = frozen.Trees(judge)
        pc = np.array([jt.predict(list(r)) for r in x[~early]])
        table = tt.deciles(y[~early], pc, when[~early])
        challenger["calibration_fails"] = len(tt.miscalibrated(table))
        challenger["calibration_table"] = table
    current = frozen.load(tc.MODELS[band], recipe=tc.RECIPE, names=tc.NAMES)
    champion = {}
    if current:
        old = frozen.Trees(current)
        champion = tt.score(
            np.array([old.predict(list(r)) for r in x[held]]), geo, y[held], when[held], base=base
        )
    reasons = touch_gate(challenger, champion)
    if exact > GATES["exact"]:
        reasons.append(f"evaluator differs from the training library by {exact:.2e}")
    spec["test"] = challenger
    spec["holdout_from"] = datetime.fromtimestamp(cut, UTC).isoformat(timespec="seconds")
    report = {
        "series": count,
        "challenger": challenger,
        "champion": champion,
        "promoted": not reasons,
        "reasons": reasons,
        "evaluator_max_diff": exact,
    }
    return (spec if not reasons else None), report


def run_touch90(fetch: Callable[[str, str], list], names: list[str]) -> tuple[dict | None, dict]:
    """The P90-touched model's contest."""
    return _touch_contest("touch90", fetch, names)


def run_touch10(fetch: Callable[[str, str], list], names: list[str]) -> tuple[dict | None, dict]:
    """The P10-touched model's contest."""
    return _touch_contest("touch10", fetch, names)


#: One replay serves the three horizons' contests in a run: (fetch, names, hour) -> (count, tracks).
_envelope_tracks: dict[tuple[int, tuple[str, ...], int], tuple[int, Any]] = {}


def envelope_gate(challenger: dict) -> list[str]:
    """Every reason not to promote a boosted-envelope model; empty means promote. The gates and
    why each number is what it is: `envelope_train.ENVELOPE_GATES`."""
    from .envelope_train import ENVELOPE_GATES, SLICE_DAYS, WINDOW_DAYS

    reasons = []
    vs = challenger.get("vs_empirical_slice", {})
    if not vs.get("high", float("nan")) < ENVELOPE_GATES["beats_empirical"]:
        reasons.append(
            f"pinball against the history envelope over {SLICE_DAYS} days {vs.get('relative')} "
            f"[{vs.get('low')}, {vs.get('high')}]: not better beyond noise"
        )
    ch = challenger.get("vs_champion")
    if ch:
        slack = max(ENVELOPE_GATES["vs_champion"], 2 * ch.get("se", 0.0))
        if not ch.get("relative", float("nan")) <= slack:
            reasons.append(f"pinball {ch.get('relative')} against the champion (slack {slack:.4f})")
    mine, theirs = challenger.get("worst_window"), challenger.get("empirical_worst_window")
    if mine is None or theirs is None or not mine >= theirs - ENVELOPE_GATES["slice_points"]:
        reasons.append(
            f"worst {WINDOW_DAYS}-day P90 cover over {SLICE_DAYS} days {mine} against the history"
            f" envelope's {theirs}"
        )
    # **The absolute floor, which every gate above lacks.** The three before this
    # are comparisons, so a challenger that is badly calibrated in company clears
    # all of them: if the history envelope's worst window is poor too, a model
    # covering 78% while quoting 90% passes. See `ENVELOPE_GATES`.
    floor = ENVELOPE_GATES["worst_window_floor"]
    if mine is None or math.isnan(mine) or mine < floor:
        reasons.append(
            f"worst {WINDOW_DAYS}-day P90 cover {mine} under the {floor:.0%} floor, "
            f"whatever the history envelope does"
        )
    # And pooled, at every level: a band wrong in a useful direction buys pinball.
    band = ENVELOPE_GATES["cover_band"]
    for name, nominal in (("p10", 0.10), ("p50", 0.50), ("p90", 0.90)):
        got = challenger.get(name)
        if got is None or math.isnan(got) or abs(got - nominal) > band:
            reasons.append(f"{name} covers {got} against a nominal {nominal:.0%} +-{band:.0%}")
    return reasons


def _envelope_contest(horizon: int, fetch: Callable[[str, str], list], names: list[str]):
    """One contest for one horizon's boosted envelope. Returns (spec to promote or None, report)."""
    from ..structures import rollover as ro
    from ..structures.vol import envelope as ev
    from . import envelope_train as et

    key = (id(fetch), tuple(names), int(time.time() // 3600))
    if key not in _envelope_tracks:
        _envelope_tracks.clear()
        series = {}
        for symbol in names:
            if ro.is_fx(symbol):
                got = fetch(symbol, ev.MODEL_INTERVAL)
                if len(got) > 2_000:
                    series[(symbol, ev.MODEL_INTERVAL)] = got
        _envelope_tracks[key] = (len(series), et.tracks(series))
    count, found = _envelope_tracks[key]
    when, x, y = et.rows(found, horizon)
    if len(y) == 0:
        return None, {"series": count, "promoted": False, "reasons": ["no usable FX 15m history"]}
    cut = when.max() - HOLDOUT_DAYS * 86_400
    early = when.max() - et.SLICE_DAYS * 86_400
    if not (when < early).any() or not (when >= cut).any():
        return None, {"series": count, "promoted": False, "reasons": ["too little history"]}
    spec = et.train(when[when < cut], x[when < cut], y[when < cut], horizon)
    fitted = spec.pop("_sklearn")
    exact = et.exactness(spec, fitted, x[when >= cut][:2_000])
    current = frozen.load(ev.MODELS[horizon], recipe=ev.MODEL_RECIPE, names=ev.MODEL_NAMES)
    specs = [spec, None] + ([current] if current else [])
    got = et.scored(found, horizon, specs, cut)
    challenger = et.summary(got[0])
    challenger["vs_empirical"] = et.compare(got[0], got[1])
    empirical = et.summary(got[1])
    champion = {}
    if current:
        champion = et.summary(got[2])
        challenger["vs_champion"] = et.compare(got[0], got[2])
    # The slice gate, over a longer out-of-sample block, by a model trained before it.
    judge = et.train(when[when < early], x[when < early], y[when < early], horizon)
    judge.pop("_sklearn")
    slice_model, slice_empirical = et.scored(found, horizon, [judge, None], early)
    challenger["vs_empirical_slice"] = et.compare(slice_model, slice_empirical)
    challenger["worst_window"] = round(et.worst_window(slice_model, early), 4)
    challenger["empirical_worst_window"] = round(et.worst_window(slice_empirical, early), 4)
    reasons = envelope_gate(challenger)
    if exact > GATES["exact"]:
        reasons.append(f"evaluator differs from the training library by {exact:.2e}")
    spec["test"] = challenger
    spec["holdout_from"] = datetime.fromtimestamp(cut, UTC).isoformat(timespec="seconds")
    report = {
        "series": count,
        "challenger": challenger,
        "champion": champion,
        "empirical": empirical,
        "promoted": not reasons,
        "reasons": reasons,
        "evaluator_max_diff": exact,
    }
    return (spec if not reasons else None), report


def run_envelope5(fetch: Callable[[str, str], list], names: list[str]):
    """The 5-bar boosted envelope's contest."""
    return _envelope_contest(5, fetch, names)


def run_envelope20(fetch: Callable[[str, str], list], names: list[str]):
    """The 20-bar boosted envelope's contest."""
    return _envelope_contest(20, fetch, names)


def run_envelope50(fetch: Callable[[str, str], list], names: list[str]):
    """The 50-bar boosted envelope's contest."""
    return _envelope_contest(50, fetch, names)


#: In run order. The envelope contests come before the touch contests, because the touch models
#: read the envelope's bands: they retrain on the bands in service after this run's promotions.
#: Deriv's own-law tables (`structures/vol/envelope.py`, research/docs/deriv-variants.md): the
#: timeframes the bridge serves that the tables cover, and the hold-out that judges each cell.
DERIV_LAW_INTERVALS: tuple[str, ...] = ("5m", "15m", "30m", "1h", "4h")
DERIV_LAW_HOLDOUT_DAYS = 90


def run_deriv_law(fetch: Callable[[str, str], list], names: list[str]) -> tuple[dict | None, dict]:
    """Fit the mechanics-only Deriv indices' own-law tables on everything before a 90-day
    hold-out, and keep the (family, interval, horizon) cells that beat the empirical envelope
    there with calibrated P10 / P90 (`deriv_law_train.select`). Promotes if any cell passes."""
    from . import deriv_law_train as dl

    series = {}
    for symbol in names:
        if not dl.family_of(symbol):
            continue
        for interval in DERIV_LAW_INTERVALS:
            got = fetch(symbol, interval)
            if len(got) > 3 * dl.MIN_BARS:
                series[(symbol, interval)] = got
    if not series:
        return None, {
            "series": 0,
            "promoted": False,
            "reasons": ["no mechanics-only Deriv history"],
        }
    cut = max(b[-1].time for b in series.values()) - DERIV_LAW_HOLDOUT_DAYS * 86_400
    before = {k: [b for b in v if b.time < cut] for k, v in series.items()}
    spec, cells = dl.select(dl.fit(before), series, cut)
    passing = [c for c in cells if c["pass"]]
    reasons = [] if passing else ["no cell beat the empirical envelope with calibrated P10 / P90"]
    spec["test"] = {"cells": cells, "holdout_from": datetime.fromtimestamp(cut, UTC).isoformat()}
    report = {
        "series": len(series),
        "challenger": {"cells_passing": len(passing), "cells": len(cells)},
        "champion": {},
        "promoted": not reasons,
        "reasons": reasons,
    }
    return (spec if not reasons else None), report


#: The expansion alert's gates (`structures/learning/expansion.py`, research/docs/expansion.md).
#: Its walks are not held to 0.5: from a deep compression the smoothed range takes longer to climb
#: back on any process, so some skill there is mechanical and correct. What must hold is that
#: markets beat the walks by a clear margin.
EXPANSION_GATES: dict[str, Any] = {
    "min_real_auc": 0.68,
    "over_control": 0.10,
    "vs_champion": 0.01,
    "calibration": (0.7, 1.4),
}


def expansion_gate(challenger: dict, champion: dict) -> list[str]:
    """Every reason not to promote an expansion model; empty means promote."""
    g = EXPANSION_GATES
    reasons = []
    real = challenger.get("real", float("nan"))
    if not real >= g["min_real_auc"]:
        reasons.append(f"real-market AUC {real} below {g['min_real_auc']}")
    control = challenger.get("control")
    if control is not None and not real - control >= g["over_control"]:
        reasons.append(
            f"real AUC {real} beats the walks' {control} by less than {g['over_control']}"
        )
    theirs = champion.get("real")
    if theirs is not None and not math.isnan(theirs) and not real >= theirs - g["vs_champion"]:
        reasons.append(f"real AUC {real} against the champion's {theirs}")
    lo, hi = g["calibration"]
    cal = challenger.get("calibration", float("nan"))
    if not lo <= cal <= hi:
        reasons.append(f"top-decile calibration {cal} outside {lo}-{hi}")
    return reasons


def run_expansion(fetch: Callable[[str, str], list], names: list[str]) -> tuple[dict | None, dict]:
    """One contest for the compression-to-expansion alert. Returns (spec or None, report)."""
    from ..structures.learning import expansion as ex
    from . import expansion_train as et

    series = {}
    for symbol in names:
        for interval in ("15m", "1h", "4h"):
            got = fetch(symbol, interval)
            if len(got) > ex.WARM + ex.AHEAD + 50:
                series[(symbol, interval)] = got
    rows = et.dataset(series)
    when, kinds, x, y = rows.arrays()
    if len(y) == 0:
        return None, {"series": len(series), "promoted": False, "reasons": ["no usable history"]}
    cut = when.max() - HOLDOUT_DAYS * 86_400
    train, held = when < cut, when >= cut
    spec = et.train(x[train], y[train])
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
    _, ck, cx, cy = et.dataset(et.walks()).arrays()  # never trained on
    xs, ys, ks = (
        np.vstack([x[held], cx]),
        np.concatenate([y[held], cy]),
        np.concatenate([kinds[held], ck]),
    )
    challenger = et.score(trees.predict, xs, ys, ks)
    current = frozen.load(ex.MODEL, recipe=ex.RECIPE, names=ex.NAMES)
    champion = et.score(frozen.Trees(current).predict, xs, ys, ks) if current else {}
    reasons = expansion_gate(challenger, champion)
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


REGISTRY: dict[str, Callable[..., tuple[dict | None, dict]]] = {
    "shocks": run_shocks,
    "expansion": run_expansion,
    "envelope_fx15m_5": run_envelope5,
    "envelope_fx15m_20": run_envelope20,
    "envelope_fx15m_50": run_envelope50,
    "touch90_fx15m": run_touch90,
    "touch10_fx15m": run_touch10,
    "deriv_law": run_deriv_law,
}


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
        f"pinball {c['vs_empirical'].get('relative')} against the history envelope"
        f" · worst 14-day P90 {c.get('worst_window')} (history {c.get('empirical_worst_window')})"
        if "vs_empirical" in c
        else f"champion AUC real {k.get('real', 'n/a')} · deriv {k.get('deriv', 'n/a')}"
        if "skill" not in c
        else f"skill over geometry {c.get('skill')} (champion {k.get('skill', 'n/a')})"
        f" · calibration {c.get('calibration')}",
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
