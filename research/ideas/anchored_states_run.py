"""Run the anchored-states study: one invocation, every section.

    uv run python -m research.ideas.anchored_states_run --out <dir> --workers 48

**One invocation, because three studies competed on an 8-core box earlier in
the same session at load 25-31, one never completed its panel at all, and a
"406 seconds per leg" timing turned out to be a measurement of contention
rather than of the job - a twentyfold-wrong projection. The same panels ran in
91 and 96 seconds on a 64-core box.** So the panel, the power sweep and the
sanity check are sections of one command with the output directory and the
worker count as flags, and nothing here is meant to be run piecemeal on a
shared machine.

`--sanity` runs first and prints a fingerprint of each harness file.
`failed-sync-still-launches-the-run` is why: `lab.sh run` prints "launched"
whether or not the sync carried your new code, so the run states what it is
running rather than leaving it to be grepped for afterwards.

Sections, in the order the prereg puts them:

* `power` - the planted magnitude effect and the strength at which the test
  stops seeing it. **Before the panel**, because a null without it is not
  reportable, and because a plant whose zero control fails is a broken arm
  that would otherwise be discovered after the expensive part.
* `panel` - every feed, every interval, every anchor, every arm.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sqlite3
import sys
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import research.ideas.anchored_states as A
import research.ideas.anchored_states_agg as G
import research.ideas.level_shield as L

#: Which section writes which file. A partial run is still readable, which is
#: the point of one object per line.
FILES = {"panel": "panel.jsonl", "power": "power.jsonl"}

#: Planted strengths for the power sweep: the multiplicative lift on the
#: forward move for the picked state level. 0 is the zero control and is
#: **asserted**, not assumed.
#:
#: It runs to 3.2 - a forward move more than four times the other levels' -
#: because a sweep that stops before the test sees anything has not located
#: the blind point, it has only confirmed the null. Measured on eurusd 15m at
#: two draws an arm: a plant delivering **2.22x** the other levels' mean
#: absolute move raised the recovered effect from 0.257 to 0.483 and still sat
#: inside the arms, so the interesting part of the curve is above 0.80 at the
#: short intervals.
STRENGTHS = (0.0, 0.05, 0.10, 0.20, 0.40, 0.80, 1.60, 3.20)

#: The level each clock anchor is planted on, fixed here. `session` plants on
#: the London session and `through` on the first third of the period; both are
#: functions of the clock alone, so the plant cannot move the label.
PLANT_LEVEL = {"session": A.SESSIONS.index("london"), "through": 0}

#: The price-derived anchor the second plant uses, carried to measure how much
#: a plant attenuates when it changes the bars the label is recomputed from -
#: `fear-greed.md`'s sixth defect, where the act of planting destroyed the
#: association being planted (zero cell +0.1412, hard walls the wrong sign).
FEEDBACK_ANCHOR = "mood_vol"

#: Two shapes of the same planted effect, because the outcome's denominator is
#: a **trailing** volatility unit and that decides what this study can see.
#:
#: `all` plants every anchor at the picked level. The unit is an EWMA whose
#: span is the horizon, so 86% of its weight sits on the previous `H` bars; at
#: 1d the stride is exactly `H`, so a picked anchor following a picked anchor
#: reads a unit that has already absorbed the lift and the ratio cancels. At
#: 15m and 1h the jitter leaves an unplanted gap of 24 bars on average, so the
#: absorption is partial. That is a property of the pre-registered outcome, not
#: a harness bug, and the sweep measures it rather than working around it.
#:
#: `isolated` thins the plant so no two consecutive anchors are picked, so the
#: unit at the decision bar is unplanted and the lift is fully delivered. It
#: is the power of this test against a **transient** magnitude effect, which is
#: the only kind a trailing unit can see.
PLANTS = ("all", "isolated")


def _store(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path, uri=True)


def _halves(rows: A.Rows) -> np.ndarray:
    """0 for the earlier half of the anchors, 1 for the later.

    Split on the anchor's position rather than the calendar, so the two halves
    hold the same number of rows whatever the gaps in the feed - the prereg's
    "two non-overlapping halves of the history".
    """
    if len(rows) == 0:
        return np.zeros(0, dtype=np.int64)
    cut = len(rows) // 2
    out = np.zeros(len(rows), dtype=np.int64)
    out[cut:] = 1
    return out


def _spread(rows: A.Rows, anchor: str, outcome: str, *, block: int, draws: int, seed: int):
    value = rows.size if outcome == "size" else rows.signed
    return G.spread_for(
        rows.levels[anchor],
        rows.stratum,
        value,
        bins=A.ANCHORS[anchor],
        block=block,
        draws=draws,
        seed=seed,
    )


def _as_dict(got: G.Spread | None) -> dict | None:
    if got is None:
        return None
    return {
        "n": got.n,
        "mass": got.mass,
        "kept": round(got.kept, 4),
        "used": got.used,
        "spread": round(got.spread, 6),
        "sd": round(got.sd, 6),
        "effect": round(got.effect, 6),
        "effect_sd": round(got.effect_sd, 6),
        "resid_sd": round(got.resid_sd, 5),
        "kw": round(got.kw, 4),
        "level_n": list(got.per_level_n),
        "level_mean": [None if np.isnan(x) else round(x, 5) for x in got.per_level_mean],
        "level_sd": [None if np.isnan(x) else round(x, 5) for x in got.per_level_sd],
        "pooled_mean": round(got.pooled_mean, 5),
        "row_sd": round(got.row_sd, 5),
        "n_eff": round(got.n_eff, 1),
    }


def _arm_rows(
    feed: str, interval: str, series: L.Series, anchors, draws: int, fitted
) -> list[tuple[str, A.Rows]]:
    """Every surrogate draw's rows, one arm-draw at a time.

    The series is built, measured and **dropped** inside the loop rather than
    collected first: eighty 5,000-bar surrogates is about 16 MB a worker, and
    forty-eight workers holding them at once is memory spent for nothing.
    """
    arms = dict(A.SERIES_ARMS)
    if interval == "1d":
        arms.update(A.DIAGNOSTIC_ARMS)
    out: list[tuple[str, A.Rows]] = []
    for arm, make in arms.items():
        for draw in range(draws):
            rng = random.Random(A.seed_of(feed, interval, arm, draw) & 0xFFFFFFFF)
            built = make(series, rng, fitted) if arm == "garch-bars" else make(series, rng)
            out.append((arm, A.measure(built, interval, anchors)))
    return out


@dataclass(frozen=True, slots=True)
class guarded:
    """Turn a raised exception into one `error` record instead of a dead panel.

    `pool.map` propagates an exception out of a worker and takes the whole run
    with it. One feed's bad data is not a reason to lose forty-one other jobs,
    and this study has already hit the case: `FearGreed` raises on gold's dead
    1d bars, which killed a three-feed smoke run outright. A partial run is
    still readable; a sweep that has to finish before it says anything is a
    sweep nobody runs twice. The report prints every `error` record **before**
    any result, so a missing cell cannot be mistaken for a null.

    **A class and not a closure, because a closure cannot be pickled.** This
    was a nested `def`, which `ProcessPoolExecutor` refuses with
    `AttributeError: Can't get local object 'guarded.<locals>.run'` - raised
    from the queue feeder thread, so the pool hangs rather than exits. The
    serial path at `--workers 1` builds a generator and never pickles
    anything, so the whole study ran clean at one worker and died at every
    count above it. `runner` is a module-level function, which pickles by
    reference.
    """

    runner: Callable[[tuple], list[dict]]

    def __call__(self, job: tuple) -> list[dict]:
        try:
            return self.runner(job)
        except Exception as err:  # noqa: BLE001 - one bad job, not a dead panel
            return [
                {
                    "kind": "error",
                    "job": [str(part) for part in job[:4]],
                    "error": repr(err),
                    "where": traceback.format_exc(limit=4).splitlines()[-3:],
                }
            ]


def panel_job(job: tuple[str, str, str, int]) -> list[dict]:
    """One (feed, interval): the real arm, every surrogate draw, every anchor.

    One process per (feed, interval) because the expensive part is replaying
    `Pivots` and `FearGreed` bar by bar, and that is per series.
    """
    feed, interval, store, draws = job
    con = _store(store)
    try:
        series = L.load(con, feed, interval)
    finally:
        con.close()
    if series is None:
        return [{"kind": "missing", "feed": feed, "interval": interval}]

    anchors = A.anchors_for(series, interval)
    block = A.blocks_for(interval)
    real = A.measure(series, interval, anchors)
    half = _halves(real)
    head = {
        "feed": feed,
        "venue": series.venue,
        "interval": interval,
        "bars": len(series.close),
        "days": round(series.days, 1),
        "placebo": feed in A.PLACEBO,
    }
    out: list[dict] = [
        {
            **head,
            "kind": "series",
            "anchors": len(anchors),
            "stride": round(float(np.mean(np.diff(anchors))) if len(anchors) > 1 else 0.0, 2),
            "block_rows": block,
            "refused": real.refused,
            "dead": real.dead,
            "levels_seen": {
                name: int(len(set(real.levels[name][real.levels[name] >= 0])))
                for name in A.ANCHORS
            },
        }
    ]

    fitted = L.fit_garch(np.diff(np.log(np.maximum(series.close, 1e-12))))
    arm_rows = _arm_rows(feed, interval, series, anchors, draws, fitted)

    #: The marginal scale of the outcome on each arm, against the real series'.
    #: An arm that does not match here is not matched on the thing it is not
    #: removing, and an unstandardised statistic would read the difference as
    #: structure - which is why `effect` and not `spread` decides.
    marginal: dict[str, list[float]] = {}
    for arm, rows in [("real", real), *arm_rows]:
        marginal.setdefault(arm, []).extend(
            [float(np.nanmean(rows.size)), float(np.nanstd(rows.size))]
        )
    out[0]["arm_size"] = {
        arm: [round(sum(v[0::2]) / (len(v) / 2), 4), round(sum(v[1::2]) / (len(v) / 2), 4)]
        for arm, v in marginal.items()
    }

    for anchor in A.ANCHORS:
        bins = A.ANCHORS[anchor]
        for outcome in ("size", "signed"):
            cell: dict = {
                **head,
                "kind": "cell",
                "anchor": anchor,
                "outcome": outcome,
                "bins": bins,
                "v_comp": round(
                    float(G.cramers_v(real.levels[anchor], real.stratum, bins=bins)), 4
                ),
            }
            seed = A.seed_of("boot", feed, interval, anchor, outcome) & 0x7FFFFFFF
            for part, mask in (("all", None), ("a", half == 0), ("b", half == 1)):
                sliced = real if mask is None else _slice(real, mask)
                cell[part] = _as_dict(
                    _spread(sliced, anchor, outcome, block=block, draws=400, seed=seed)
                )
                arms: dict[str, list[float]] = {}
                #: The rank statistic's arms as well as the effect's. `size`
                #: carries this market's tails - kurtosis 47-74 on traded
                #: feeds - so a mean of twelve rows is not robust to them, and
                #: a robustness companion reported against nothing is not a
                #: null at all.
                kws: dict[str, list[float]] = {}
                for arm, rows in arm_rows:
                    got = _spread(
                        rows if mask is None else _slice(rows, mask),
                        anchor,
                        outcome,
                        block=block,
                        draws=0,
                        seed=seed,
                    )
                    if got is not None:
                        arms.setdefault(arm, []).append(round(got.effect, 6))
                        kws.setdefault(arm, []).append(round(got.kw, 4))
                duty = G.duty_draws(
                    sliced.levels[anchor],
                    sliced.stratum,
                    sliced.size if outcome == "size" else sliced.signed,
                    bins=bins,
                    block=block,
                    draws=draws,
                    seed=seed,
                )
                if duty:
                    arms["duty-twin"] = [round(x, 6) for x in duty]
                if outcome == "signed":
                    flips = G.sign_flip_draws(
                        sliced.levels[anchor],
                        sliced.stratum,
                        sliced.signed,
                        bins=bins,
                        block=block,
                        draws=draws,
                        seed=seed,
                    )
                    if flips:
                        arms["sign-flip"] = [round(x, 6) for x in flips]
                cell[f"arms_{part}"] = arms
                cell[f"kw_arms_{part}"] = kws
            auc = G.auc_crossfit(
                real.levels[anchor],
                real.stratum,
                real.size if outcome == "size" else real.signed,
                bins=bins,
                half=half,
            )
            cell["auc_strata"] = None if auc.strata is None else round(auc.strata, 4)
            cell["auc_pooled"] = None if auc.pooled is None else round(auc.pooled, 4)
            cell["auc_n"] = auc.n
            out.append(cell)
    return out


def _slice(rows: A.Rows, mask: np.ndarray) -> A.Rows:
    return A.Rows(
        anchor=rows.anchor[mask],
        day=rows.day[mask],
        stratum=rows.stratum[mask],
        size=rows.size[mask],
        signed=rows.signed[mask],
        levels={name: value[mask] for name, value in rows.levels.items()},
        refused=rows.refused,
        dead=rows.dead,
    )


def power_job(job: tuple[str, str, str, str, str, int]) -> list[dict]:
    """The planted magnitude sweep for one (feed, interval, anchor, plant).

    The base is a log-space walk with this market's bar geometry, so it has no
    path structure of its own and anything recovered is the plant. The arms
    are rebuilt from the **planted** series at each strength, so the bar the
    plant has to clear is the bar the panel uses.

    `delivered` is reported beside every recovered figure: the picked level's
    mean absolute log move against the unpicked levels', with no volatility
    unit in it. It separates "the plant arrived" from "the statistic saw it",
    which is the difference the trailing denominator makes and the thing a
    blind spot would otherwise be mistaken for.
    """
    feed, interval, anchor, plant, store, draws = job
    con = _store(store)
    try:
        series = L.load(con, feed, interval)
    finally:
        con.close()
    if series is None:
        return []
    anchors = A.anchors_for(series, interval)
    block = A.blocks_for(interval)
    bins = A.ANCHORS[anchor]
    base = A.walk_geometry(
        series, random.Random(A.seed_of("power-base", feed, interval) & 0xFFFFFFFF)
    )
    seeded = A.measure(base, interval, anchors)
    if anchor in A.CLOCK_ANCHORS:
        picked = seeded.levels[anchor] == PLANT_LEVEL[anchor]
    else:
        picked = seeded.levels[anchor] == bins - 1
    if plant == "isolated":
        # Greedy, not "drop anything with a picked predecessor": the condition
        # is that no two *planted* anchors are adjacent, so a run of three
        # keeps the first and the third. Dropping every anchor with a picked
        # predecessor keeps only the first of each run, which at 1d - where
        # the monthly phase advances by about one anchor's stride - left 2% of
        # anchors planted and a contrast too thin to calibrate anything.
        kept = np.zeros(len(picked), dtype=bool)
        for row in range(len(picked)):
            kept[row] = bool(picked[row]) and not (row and kept[row - 1])
        picked = kept
    out: list[dict] = []
    for strength in STRENGTHS:
        planted = A.plant_magnitude(base, interval, anchors, picked, strength)
        rows = A.measure(planted, interval, anchors)
        horizon = A.SETTINGS[interval]["horizon"]
        moves = np.abs(
            np.log(
                np.maximum(planted.close[anchors + horizon], 1e-12)
                / np.maximum(planted.close[anchors], 1e-12)
            )
        )
        delivered = (
            float(moves[picked].mean() / moves[~picked].mean())
            if picked.any() and (~picked).any() and moves[~picked].mean() > 0
            else float("nan")
        )
        seed = A.seed_of("power", feed, interval, anchor, plant, strength) & 0x7FFFFFFF
        real = _spread(rows, anchor, "size", block=block, draws=400, seed=seed)
        arms: dict[str, list[float]] = {}
        fitted = L.fit_garch(np.diff(np.log(np.maximum(planted.close, 1e-12))))
        for arm, make in A.SERIES_ARMS.items():
            for draw in range(draws):
                rng = random.Random(
                    A.seed_of("power", feed, interval, plant, arm, strength, draw) & 0xFFFFFFFF
                )
                built = make(planted, rng, fitted) if arm == "garch-bars" else make(planted, rng)
                got = _spread(
                    A.measure(built, interval, anchors), anchor, "size", block=block, draws=0, seed=seed
                )
                if got is not None:
                    arms.setdefault(arm, []).append(got.spread)
        duty = G.duty_draws(
            rows.levels[anchor], rows.stratum, rows.size, bins=bins, block=block, draws=draws, seed=seed
        )
        if duty:
            arms["duty-twin"] = duty
        verdict = G.judge(real.effect if real else 0.0, real.effect_sd if real else 0.0, arms)
        out.append(
            {
                "kind": "power",
                "feed": feed,
                "interval": interval,
                "anchor": anchor,
                "plant": plant,
                "clock_plant": anchor in A.CLOCK_ANCHORS,
                "strength": strength,
                "picked_share": round(float(picked.mean()), 4),
                "delivered": None if math.isnan(delivered) else round(delivered, 4),
                "real": _as_dict(real),
                "arms": {k: [round(x, 6) for x in v] for k, v in arms.items()},
                "z": None if verdict is None else round(verdict.z, 3),
                "excess": None if verdict is None else round(verdict.excess, 6),
                "beats_hardest": None if verdict is None else verdict.beats_hardest,
                "hardest_arm": None if verdict is None else verdict.hardest_arm,
                "level_mean": None if real is None else [
                    None if np.isnan(x) else round(x, 5) for x in real.per_level_mean
                ],
            }
        )
    return out


def sanity(store: str, feeds: tuple[str, ...], intervals: tuple[str, ...]) -> None:
    """Assert what the run assumes, and fingerprint what is about to run."""
    here = Path(__file__).parent
    for name in (
        "anchored_states.py",
        "anchored_states_agg.py",
        "anchored_states_run.py",
        "anchored_states_report.py",
    ):
        path = here / name
        digest = hashlib.blake2b(path.read_bytes(), digest_size=8).hexdigest()
        print(f"  {name:28s} {digest}  {path.stat().st_size:7d} bytes", file=sys.stderr)
    try:
        con = _store(store)
        found = 0
        try:
            for interval in intervals:
                for feed in feeds:
                    if L.venue_for(con, feed, interval) is None:
                        print(f"  MISSING {feed} {interval}", file=sys.stderr)
                    else:
                        found += 1
        finally:
            con.close()
    except sqlite3.Error as err:
        raise SystemExit(
            f"the price store at {store} is not readable ({err}). Pass --store with the "
            f"sqlite URI of a copy, e.g. --store 'file:/somewhere/prices.db?mode=ro'."
        ) from err
    if not found:
        raise SystemExit(
            f"no feed resolved a venue in {store}, so every job would return nothing. "
            f"Check --store, --feeds and --intervals before spending the panel."
        )
    assert A.seed_of("x", 1) == A.seed_of("x", 1), "seeds must reproduce in one process"
    for interval, settings in A.SETTINGS.items():
        frames = A.frames_for(
            L.Series(
                feed="feed",
                venue="VENUE",
                interval=interval,
                ts=np.zeros(1),
                open=np.ones(1),
                high=np.ones(1),
                low=np.ones(1),
                close=np.ones(1),
            ),
            interval,
        )
        assert len(frames.context) == 1, interval
        print(
            f"  {interval}: H={settings['horizon']} unit={settings['unit_span']} "
            f"pivots={settings['pivot_period']} through={settings['through_period']} "
            f"jitter={settings['jitter']} block_rows={A.blocks_for(interval)} "
            f"context={frames.context[0]}",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="output directory; one jsonl per section")
    ap.add_argument("--workers", type=int, default=1, help="processes; 1 on a shared box")
    ap.add_argument("--store", default=A.STORE, help="sqlite URI for the price store")
    ap.add_argument("--draws", type=int, default=16, help="draws per null arm (prereg minimum 16)")
    #: Eight and not four: `judge` takes the hardest arm by its **mean**, and
    #: at two draws an arm that mean is the luckier of two numbers. Measured on
    #: eurusd 15m, it put the bar above a plant delivering 2.22x the other
    #: levels' move, which is a statement about the draw count rather than
    #: about the test.
    ap.add_argument("--power-draws", type=int, default=8, help="draws per arm in the power sweep")
    ap.add_argument("--feeds", default="", help="space or comma separated; default all 14")
    ap.add_argument("--intervals", default="", help="default 15m 1h 1d")
    ap.add_argument(
        "--sections",
        default="power,panel",
        help="which sections to run, in order; power first so a broken plant is cheap",
    )
    ap.add_argument("--power-feeds", default="eurusd gold", help="feeds for the power sweep")
    args = ap.parse_args(argv)

    feeds = tuple((args.feeds or " ".join(A.FEEDS)).replace(",", " ").split())
    intervals = tuple((args.intervals or "15m 1h 1d").replace(",", " ").split())
    unknown = [i for i in intervals if i not in A.SETTINGS]
    if unknown:
        raise SystemExit(f"{unknown} have no horizon in SETTINGS; known: {', '.join(A.SETTINGS)}")
    sections = tuple(args.sections.replace(",", " ").split())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("sanity:", file=sys.stderr)
    sanity(args.store, feeds, intervals)
    (out / "meta.json").write_text(
        json.dumps(
            {
                "feeds": list(feeds),
                "intervals": list(intervals),
                "draws": args.draws,
                "power_draws": args.power_draws,
                "placebo": list(A.PLACEBO),
                "anchors": A.ANCHORS,
                "strengths": list(STRENGTHS),
                "plants": list(PLANTS),
                "warmup": A.WARMUP,
                "strata": A.STRATA,
                "deciding_arms": list(A.DECIDING_ARMS),
            },
            indent=2,
        )
        + "\n"
    )

    for section in sections:
        if section not in FILES:
            raise SystemExit(f"{section} is not a section; known: {', '.join(FILES)}")
        if section == "power":
            power_feeds = tuple(args.power_feeds.replace(",", " ").split())
            jobs = [
                (feed, interval, anchor, plant, args.store, args.power_draws)
                for interval in intervals
                for feed in power_feeds
                for anchor in (
                    *(a for a in A.CLOCK_ANCHORS if a != "session" or interval != "1d"),
                    FEEDBACK_ANCHOR,
                )
                for plant in (PLANTS if anchor in A.CLOCK_ANCHORS else ("all",))
            ]
            runner = guarded(power_job)
        else:
            jobs = [(feed, interval, args.store, args.draws) for interval in intervals for feed in feeds]
            runner = guarded(panel_job)
        print(
            f"{section}: {len(jobs)} jobs, {args.draws} draws an arm, "
            f"{args.workers} workers -> {out / FILES[section]}",
            file=sys.stderr,
        )
        started = time.time()
        done = 0
        with open(out / FILES[section], "w") as fh:
            if args.workers <= 1:
                streams = (runner(job) for job in jobs)
                for rows in streams:
                    done += 1
                    for row in rows:
                        fh.write(json.dumps(row) + "\n")
                    fh.flush()
                    print(f"  {done}/{len(jobs)} {time.time() - started:.0f}s", file=sys.stderr)
            else:
                with ProcessPoolExecutor(max_workers=args.workers) as pool:
                    for rows in pool.map(runner, jobs):
                        done += 1
                        for row in rows:
                            fh.write(json.dumps(row) + "\n")
                        fh.flush()
                        print(f"  {done}/{len(jobs)} {time.time() - started:.0f}s", file=sys.stderr)
        print(f"{section}: wrote {out / FILES[section]} in {time.time() - started:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
