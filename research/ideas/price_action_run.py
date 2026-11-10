"""Run the price-action panel: feeds x intervals x patterns x entries x arms.

    ./.secrets/lab.sh run research/ideas/price_action_run.py \
        PA_OUT=pa-out PA_WORKERS=22 PA_DRAWS=4 PA_INTERVALS=1d,4h,1h,15m
    ./.secrets/lab.sh run research/ideas/price_action_run.py \
        PA_MODE=sweep PA_OUT=pa-out PA_INTERVALS=1d PA_WORKERS=14
    ./.secrets/lab.sh run research/ideas/price_action_run.py \
        PA_MODE=confluence PA_OUT=pa-out PA_INTERVALS=1d PA_WORKERS=14
    ./.secrets/lab.sh run research/ideas/price_action_run.py \
        PA_MODE=origin PA_OUT=pa-out PA_INTERVALS=1d PA_WORKERS=6

**Commas, not spaces, in `PA_INTERVALS`.** `lab.sh run` passes its env
arguments through an unquoted `$*`, so a value with a space in it never reaches
the script and the run dies before it writes a log
(`lab-run-breaks-on-spaces-in-env-args`: a missing log means this, not a
crashed script). Every list this module reads accepts either separator.

The four modes write into one directory and `price_action_report.py` reads it
whole, so a mode can be re-run on its own without invalidating the others. Run
the panel first and the rest after it: the panel is the only one that is not
1d-only, and on a shared box 22 workers plus 14 is oversubscription rather than
parallelism.

One job per `(feed, interval)`, because the expensive part is replaying the
series and that is per series. Output is one JSON object per line, so a partial
run is still readable - a sweep that has to finish before it says anything is a
sweep nobody runs twice.

The rules are frozen in `research/docs/price-action-rules.md` and the detectors
in `price_action.py`; this file only drives them. Read with
`price_action_report.py`.

## Pre-registered, so the report cannot be a selection

* **The deciding statistic is mean R** at targets of 1, 2 and 3 times the
  realised risk, where a driftless walk pays exactly zero at every target -
  because no source states a target and this is the only exit construction
  that cannot contribute a result. A hit rate is description.
* **Every cell carries six comparisons**: `real`, the three `level_shield`
  surrogates through the same detector, the `calendar-shuffle` that keeps the
  daily cycle, and `matched` - the same side, stop distance and target distance
  entered at a random bar, 20 draws per setup, which is `patterns.md`'s placebo
  and the duty-cycle control in one.
* **The census travels with every cell whether or not it scores.**
  `smc-conjunctions.md`'s correction is that printing only cells above a setup
  floor left the arms the study existed for producing no rows at all, while the
  document claimed to have tested them.
* **A finding needs** the real mean R outside the hardest arm's draws, clear of
  the matched placebo by more than two standard errors, the sign consistent
  across intervals, survival of Benjamini-Hochberg over every cell, and - since
  it is a trade - a cost in R inside the desk's 0.16-of-risk ceiling on a feed
  with recorded quotes.
* **Nothing is tuned.** Every parameter the sources leave unspecified is swept
  and the whole grid is reported with its mean rather than the best cell with
  its z (`sweep-thresholds-on-the-mean-not-z`).
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import research.ideas.price_action as P
from research.ideas.level_shield import fit_garch

#: Draws per surrogate arm. Four, as in `level-shield.md` and
#: `level-bounce.md`: enough that "outside the hardest arm's draws" is a
#: statement about a range rather than about one number.
DRAWS = int(os.environ.get("PA_DRAWS") or 4)

#: Draws of the matched random entry per real setup. Twenty, because one draw
#: was `patterns.md`'s first version and was too noisy to carry the comparison
#: everything rests on.
MATCHED_DRAWS = int(os.environ.get("PA_MATCHED") or 20)

OUT = Path(os.environ.get("PA_OUT") or "pa-out")
WORKERS = int(os.environ.get("PA_WORKERS") or 2)
MODE = os.environ.get("PA_MODE") or "panel"
INTERVALS = tuple((os.environ.get("PA_INTERVALS") or "1d 4h 1h 15m").replace(",", " ").split())
FEEDS = tuple((os.environ.get("PA_FEEDS") or " ".join(P.FEEDS)).replace(",", " ").split())


#: The cells the confluence mode runs: one per pattern, at the entry and stop
#: the sources state, plus the inside bar's two side rules because an inside
#: bar is sideless in the sources and the trend is itself a confluence factor.
CONFLUENCE_CELLS = (
    ("inside", "stop_mother", "mother_far", "straddle", "source"),
    ("inside", "stop_mother", "mother_far", "with_trend", "source"),
    ("inside", "stop_mother", "mother_50", "with_trend", "source"),
    ("pin", "market", "tail", "own", "source"),
    ("pin", "stop_nose", "tail", "own", "source"),
    ("fakey", "stop_back", "break_extreme", "own", "source"),
    ("combo", "stop_mother", "mother_far", "own", "source"),
)


def cells(mode: str) -> list[dict]:
    """Every (pattern, entry, stop, side) rule a mode measures.

    `panel` is the sources' rules at their own stated parameters. `sweep` moves
    only the parameters no source states. `confluence` adds the factor count
    and the level factor, which needs a book replay and is therefore its own
    mode rather than a column on the panel.
    """
    out: list[dict] = []
    base = {
        "tail_share": P.TAIL_SOURCE,
        "expiry": 3,
        "pip_pad": 0.02,
        "shape": "source",
        "break_ref": "inside",
        "close_back": "mother",
        "fake_bars": 1,
        "reach": 3,
        "fill_at": "trigger",
    }
    if mode == "confluence":
        # **Only the cells the sources prescribe.** The confluence question is
        # about the factor count on the method's own rules, and running it over
        # all 92 panel cells would double the most expensive mode in the study
        # - it replays the level book twice per arm-draw, once for the real
        # book and once for the placebo - to answer the same question 92 times.
        for pattern, entry, stop, side_rule, shape in CONFLUENCE_CELLS:
            for fill_at in ("trigger", "close"):
                out.append(
                    {
                        **base,
                        "pattern": pattern,
                        "entry": entry,
                        "stop": stop,
                        "side_rule": side_rule,
                        "shape": shape,
                        "fill_at": fill_at,
                    }
                )
        return out
    if mode == "panel":
        for pattern in P.PATTERNS:
            for entry in P.ENTRIES[pattern]:
                for stop in P.STOPS[pattern]:
                    for side_rule in P.SIDES[pattern]:
                        shapes = P.SHAPES if pattern in ("pin", "combo") else ("source",)
                        for shape in shapes:
                            for fill_at in ("trigger", "close"):
                                out.append(
                                    {
                                        **base,
                                        "pattern": pattern,
                                        "entry": entry,
                                        "stop": stop,
                                        "side_rule": side_rule,
                                        "shape": shape,
                                        "fill_at": fill_at,
                                    }
                                )
        return out
    # The sweep. One parameter moves at a time off the panel's own base cell,
    # so a grid of 400 cells does not become the multiplicity surface.
    for tail in P.TAIL_SHARES:
        out.append(
            {
                **base,
                "pattern": "pin",
                "entry": "market",
                "stop": "tail",
                "side_rule": "own",
                "tail_share": tail,
            }
        )
        out.append(
            {
                **base,
                "pattern": "pin",
                "entry": "stop_nose",
                "stop": "tail",
                "side_rule": "own",
                "tail_share": tail,
            }
        )
    for tail in P.GRADED_TAILS:
        out.append(
            {
                **base,
                "pattern": "pin",
                "entry": "market",
                "stop": "tail",
                "side_rule": "own",
                "shape": "graded",
                "graded_tail": tail,
            }
        )
    for stub in P.GRADED_STUBS:
        out.append(
            {
                **base,
                "pattern": "pin",
                "entry": "market",
                "stop": "tail",
                "side_rule": "own",
                "shape": "graded",
                "graded_stub": stub,
            }
        )
    for body in P.GRADED_BODIES:
        out.append(
            {
                **base,
                "pattern": "pin",
                "entry": "market",
                "stop": "tail",
                "side_rule": "own",
                "shape": "graded",
                "graded_body": body,
            }
        )
    for pad in P.PIP_PADS:
        out.append(
            {
                **base,
                "pattern": "pin",
                "entry": "stop_nose",
                "stop": "tail",
                "side_rule": "own",
                "pip_pad": pad,
            }
        )
    for expiry in P.EXPIRIES:
        out.append(
            {
                **base,
                "pattern": "inside",
                "entry": "stop_mother",
                "stop": "mother_far",
                "side_rule": "straddle",
                "expiry": expiry,
            }
        )
    for ref in ("inside", "mother"):
        for back in ("inside", "mother"):
            for bars in (1, 2):
                out.append(
                    {
                        **base,
                        "pattern": "fakey",
                        "entry": "stop_back",
                        "stop": "break_extreme",
                        "side_rule": "own",
                        "break_ref": ref,
                        "close_back": back,
                        "fake_bars": bars,
                    }
                )
    for reach in P.REACHES:
        out.append(
            {
                **base,
                "pattern": "inside",
                "entry": "stop_mother",
                "stop": "mother_far",
                "side_rule": "with_trend",
                "reach": reach,
            }
        )
    # A sweep that repeats a cell under two names would report one measurement
    # twice and inflate the multiplicity it then corrects for.
    seen: dict[str, dict] = {}
    for cell in out:
        seen.setdefault(_tag(cell), cell)
    return list(seen.values())


def _tag(cell: dict) -> str:
    bits = [cell["pattern"], cell["entry"], cell["stop"], cell["side_rule"]]
    if cell["shape"] == "source" and cell["pattern"] in ("pin", "combo"):
        bits.append(f"tail{cell['tail_share']:.3f}")
    if cell["shape"] != "source":
        bits.append(cell["shape"])
    for knob in ("graded_tail", "graded_stub", "graded_body"):
        if knob in cell:
            bits.append(f"{knob.split('_')[1]}{cell[knob]}")
    if cell["expiry"] != 3:
        bits.append(f"exp{cell['expiry']}")
    if cell["pip_pad"] != 0.02:
        bits.append(f"pad{cell['pip_pad']:.2f}")
    if cell["pattern"] == "fakey":
        bits.append(f"{cell['break_ref']}-{cell['close_back']}-{cell['fake_bars']}")
    if cell["reach"] != 3:
        bits.append(f"reach{cell['reach']}")
    bits.append(f"at-{cell['fill_at']}")
    return "/".join(bits)


def _money(r: np.ndarray, day: np.ndarray, *, draws: int = 200, seed: int = 0) -> dict:
    """Mean R with a **day-block** bootstrap standard error.

    Nearby trades share outcome bars and an ordinary standard error is far too
    narrow, which is why the block is a whole calendar day. The per-trade sd
    travels beside the mean because two arms with different variances rest on
    different amounts of evidence, and `needed` is the sample each arm's own
    mean and sd imply for |t| = 2 - an arm that wins on the mean while needing
    four times the sample has not won.

    The resample runs on **per-day sums and counts** rather than on the trades,
    which is the same estimator at `O(draws x days)` instead of
    `O(draws x trades)`. The matched placebo carries twenty draws per setup, so
    the slow form made the placebo arm - the one that decides - the most
    expensive thing in the run.
    """
    n = len(r)
    if n == 0:
        return {"n": 0}
    mean = float(r.mean())
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    keys, inverse = np.unique(day, return_inverse=True)
    sums = np.bincount(inverse, weights=r, minlength=len(keys))
    counts = np.bincount(inverse, minlength=len(keys)).astype(float)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(keys), size=(draws, len(keys)))
    totals = sums[pick].sum(axis=1)
    sizes = counts[pick].sum(axis=1)
    spread = totals / np.maximum(sizes, 1.0)
    se = float(spread.std()) if draws > 5 else 0.0
    return {
        "n": n,
        "mean": mean,
        "se": se,
        "sd": sd,
        "t": mean / se if se > 0 else 0.0,
        "needed": int((2.0 * sd / mean) ** 2) if mean else None,
        "win": float((r > 0).mean()),
        "blocks": int(len(keys)),
    }


def _by_stratum(got: P.Settled, mask: np.ndarray) -> list[dict]:
    """Mean R inside each compression quintile. Pooled is never the answer.

    `topology.md` found levels, ranges and shapes all restating volatility, so
    the comparison happens inside bins of trailing compression or it is a
    comparison of two volatility regimes.
    """
    out = []
    for s in range(int(got.stratum.max()) + 1 if len(got) else 0):
        pick = mask & (got.stratum == s)
        if pick.sum() < 20:
            out.append({"stratum": s, "n": int(pick.sum())})
            continue
        out.append({"stratum": s, "n": int(pick.sum()), "mean": float(got.r[pick].mean())})
    return out


def one(feed: str, interval: str) -> list[dict]:
    """Every row for one (feed, interval). A list, so the parent writes once."""
    con = sqlite3.connect(P.store_path(), uri=True)
    try:
        series = P.load(con, feed, interval)
        # A bar count is a claim about the world, so its error bar travels with
        # it: `spx500` and `us100` at 1d print half their history twice.
        dup = P.duplicate_share(con, feed, interval)
        bps = P.spread_bps(con, feed, series.venue) if series and feed in P.COSTED else 0.0
    finally:
        con.close()
    if series is None:
        return []
    span = int(P.SETTINGS[interval]["unit_span"])
    horizon = int(P.SETTINGS[interval]["horizon"])
    if MODE == "origin":
        unit = P.units(series, span)
        ctx = P.trend_and_legs(series, reach=3)
        got = P.origin_agreement(series, ctx, unit)
        return [
            {
                "feed": feed,
                "interval": interval,
                "venue": series.venue,
                "bars": len(series.close),
                "days": round(series.days, 1),
                "dup_share": dup,
                **got,
            }
        ]
    grid = cells(MODE)
    fitted = fit_garch(np.diff(np.log(np.maximum(series.close, 1e-12))))

    rows: list[dict] = []
    for arm, make in P.ARMS.items():
        draws = 1 if make is None else DRAWS
        for draw in range(draws):
            rng = random.Random(hash((feed, interval, arm, draw)) & 0xFFFF_FFFF)
            if make is None:
                s = series
            elif arm == "garch-bars":
                s = make(series, rng, fitted)
            else:
                s = make(series, rng)
            unit = P.units(s, span)
            strata = P.strata_of(s, unit, span)
            level = placebo_level = None
            if MODE == "confluence":
                level = P.level_touch(s, unit, placebo=False)
                placebo_level = P.level_touch(s, unit, placebo=True, seed=draw + 1)
            ctxs: dict[int, P.Context] = {}
            # The three pin encodings, once per series. `graded_pin` rebuilds a
            # `FuzzyCandlesticks` per bar, so computing it per cell would make
            # the arm that controls the wickiness confound the most expensive
            # thing in the run.
            pins: dict[tuple, tuple] = {}
            for cell in grid:
                reach = int(cell["reach"])
                if reach not in ctxs:
                    ctxs[reach] = P.trend_and_legs(s, reach)
                for level_arm, mask in (
                    ("none", None),
                    ("real", level),
                    ("placebo", placebo_level),
                ):
                    if MODE != "confluence" and level_arm != "none":
                        continue
                    if MODE == "confluence" and level_arm == "none":
                        continue
                    kw = {
                        k: v
                        for k, v in cell.items()
                        if k not in ("reach", "graded_tail", "graded_stub", "graded_body")
                    }
                    trades, cen = P.setups(
                        s,
                        unit,
                        strata,
                        ctxs[reach],
                        at_level=mask,
                        pins=_pins_for(s, cell, pins),
                        horizon=horizon,
                        **kw,
                    )
                    rows.append(
                        _row(
                            s,
                            feed,
                            interval,
                            arm,
                            draw,
                            cell,
                            level_arm,
                            trades,
                            cen,
                            unit,
                            strata,
                            ctxs[reach],
                            kw,
                            horizon,
                            bps,
                            dup,
                        )
                    )
    return rows


def _row(
    series,
    feed,
    interval,
    arm,
    draw,
    cell,
    level_arm,
    trades,
    cen,
    unit,
    strata,
    ctx,
    kw,
    horizon,
    bps,
    dup,
) -> dict:
    out: dict = {
        "feed": feed,
        "venue": series.venue,
        "interval": interval,
        "arm": arm,
        "draw": draw,
        "cell": _tag(cell),
        "pattern": cell["pattern"],
        "entry": cell["entry"],
        "stop": cell["stop"],
        "side_rule": cell["side_rule"],
        "level_arm": level_arm,
        "bars": len(series.close),
        "days": round(series.days, 1),
        "dup_share": dup,
        "spread_bps": round(bps, 4),
        "census": {
            "signals": cen.signals,
            "ambiguous": cen.ambiguous,
            "no_fill": cen.no_fill,
            "thin_risk": cen.thin_risk,
            "overlapped": cen.overlapped,
            "trades": cen.trades,
        },
        "r": {},
        "factors": {},
    }
    if not trades:
        return out
    plac = P.placebo_trades(
        series,
        unit,
        strata,
        ctx,
        signals=cen.signals,
        horizon=horizon,
        draws=MATCHED_DRAWS,
        seed=draw + 1,
        **kw,
    )
    base = P.settle(series, trades, unit, target=P.TARGETS[0], horizon=horizon)
    out["risk_vol"] = round(float(np.median(base.risk_vol)), 4)
    out["cost_r"] = None if bps <= 0 else round(P.cost_r(bps, series, base.risk_vol, unit), 4)
    out["placebo_trades"] = len(plac)
    out["long_share"] = round(float((base.side > 0).mean()), 4)
    for target in P.TARGETS:
        got = P.settle(series, trades, unit, target=target, horizon=horizon)
        mat = P.settle(series, plac, unit, target=target, horizon=horizon)
        live, live_m = got.decided, mat.decided
        real = _money(got.r[live], got.day[live], seed=draw)
        placebo = _money(mat.r[live_m], mat.day[live_m], seed=draw)
        out["r"][str(target)] = {
            **real,
            "decided": float(live.mean()),
            "tie": float(got.tie[live].mean()) if live.any() else 0.0,
            "strata": _by_stratum(got, live),
            "placebo": placebo,
            "placebo_decided": float(live_m.mean()) if len(live_m) else 0.0,
            "excess": _excess(real, placebo),
        }
        if target == 2.0:
            for count in P.FACTOR_COUNTS:
                pick = live & (_popcount(got.factors) >= count)
                pick_m = live_m & (_popcount(mat.factors) >= count)
                a = _money(got.r[pick], got.day[pick], seed=draw)
                b = _money(mat.r[pick_m], mat.day[pick_m], seed=draw)
                out["factors"][str(count)] = {**a, "placebo": b, "excess": _excess(a, b)}
    return out


def _excess(real: dict, placebo: dict) -> dict | None:
    """Mean R minus the same geometry entered at random **on the same series**.

    This is the statistic, not the mean. `level-shield.md` measured a bar-level
    barrier race departing from `1/(1+N)` by -0.25 to +0.12R, monotone in the
    stop-minus-target distance and growing with the interval, **and the
    surrogates do it harder** - so a raw mean R is not comparable between a
    market and its own GARCH twin, and comparing them would make a finding out
    of a replay bias. Subtracting each arm's own matched random entry removes
    it, because the placebo carries that arm's bar geometry and nothing of its
    ordering.

    The two arms are resampled independently and the standard errors added in
    quadrature: the placebo's entry bars are drawn uniformly, so its day blocks
    are not the real trades' day blocks and a paired bootstrap would be
    pretending they were.
    """
    if not real.get("n") or not placebo.get("n"):
        return None
    gap = real["mean"] - placebo["mean"]
    se = (real["se"] ** 2 + placebo["se"] ** 2) ** 0.5
    return {"value": gap, "se": se, "z": gap / se if se > 0 else 0.0}


def _pins_for(series, cell: dict, cache: dict) -> tuple | None:
    """The pin masks for this cell, computed once per distinct encoding.

    **The key carries every knob that changes the mask**, which is the defect
    this function had and a run caught: the first version keyed on the shape
    alone, so the four values of the swept tail share all read the
    pre-computed `TAIL_SOURCE` mask and the sweep printed **four identical
    rows at n = 2,256**. Four identical rows is what a parameter that never
    reached the detector looks like, and it is only visible because the grid
    was printed whole rather than summarised.
    """
    if cell["pattern"] not in ("pin", "combo"):
        return None
    key = (
        cell["shape"],
        cell["tail_share"] if cell["shape"] == "source" else None,
        cell.get("graded_tail"),
        cell.get("graded_stub"),
        cell.get("graded_body"),
    )
    if key not in cache:
        if cell["shape"] == "source":
            cache[key] = P.pin(series, float(cell["tail_share"]))
        elif cell["shape"] == "desk":
            cache[key] = P.desk_pin(series)
        else:
            cache[key] = P.graded_pin(
                series,
                tail=cell.get("graded_tail"),
                stub=cell.get("graded_stub"),
                body=cell.get("graded_body"),
            )
    return cache[key]


def _popcount(x: np.ndarray) -> np.ndarray:
    out = np.zeros(len(x), dtype=int)
    for bit in (P.F_TREND, P.F_EMA, P.F_LEVEL, P.F_RETRACE):
        out += (x & bit) > 0
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{MODE}.jsonl"
    jobs = [(feed, interval) for interval in INTERVALS for feed in FEEDS]
    print(f"{len(jobs)} jobs, {len(cells(MODE))} cells each, mode {MODE} -> {out}", flush=True)
    started = time.time()
    with out.open("w") as fh, ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for (feed, interval), rows in zip(jobs, pool.map(_call, jobs), strict=True):
            for row in rows:
                fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(
                f"{feed} {interval}: {len(rows)} rows, {time.time() - started:.0f}s",
                flush=True,
            )
    print(f"done in {time.time() - started:.0f}s", flush=True)
    return 0


def _call(job: tuple[str, str]) -> list[dict]:
    try:
        return one(*job)
    except Exception as exc:  # a dead job must not take the panel with it
        print(f"{job}: {type(exc).__name__}: {exc}", flush=True)
        return []


if __name__ == "__main__":
    sys.exit(main())
