"""Where the price-action test goes blind: plant the effect and sweep its strength.

    ./.secrets/lab.sh run research/ideas/price_action_power.py \
        PA_OUT=pa-out PA_WORKERS=14 PA_INTERVALS=1d
    PA_WALK=1 uv run python research/ideas/price_action_power.py   # the leak's size

`show-power-before-reporting-a-null` is the rule and `level-bounce.md` is the
instance that earned it: that study's part 2 reported a null the estimator
**could not have seen**, and the only reason anybody knows that is the planted
effect it failed to find. A null without this file is a statement about the
harness.

## What is planted, and why it is planted in R

A **conditional drift**: after every bar where the pattern fires, the next
`horizon` bars are shifted in the pattern's direction, ramped linearly so the
total displacement at the end of the window is `strength` times that trade's
own risk. Every bar keeps its own shape exactly - open, high, low and close all
move by the same amount, as in `level_shield.plant` - so the detector never
sees a different kind of bar and the only thing added is the thing being
measured.

Planting it in **R** rather than in volatility units is what makes the sweep
readable: the deciding statistic is mean R, so a plant of 0.20 should appear as
an excess of roughly 0.20 and the strength at which the excess stops clearing
its own noise is the blind spot in the same units as the result.

The plant is **not** a reflecting barrier. `level_shield.plant` reflects price
off a price, which is the right plant for a level claim and the wrong one here:
these patterns are bar shapes, not prices, and a barrier would test whether the
harness can find a level.
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
import research.ideas.price_action_run as R
from research.ideas.level_shield import Series

#: Planted strengths, as a share of the trade's own risk delivered over the
#: forward window. Zero first, because an arm that reads non-zero at zero is a
#: bug and not a blind spot.
#: Commas as well as spaces, because `lab.sh run`'s env arguments are
#: unquoted and a value with a space in it never reaches the script
#: (`lab-run-breaks-on-spaces-in-env-args`: a missing log means this, not a
#: crashed script).
STRENGTHS = tuple(
    float(x)
    for x in (os.environ.get("PA_STRENGTHS") or "0 0.05 0.10 0.20 0.40 0.80")
    .replace(",", " ")
    .split()
)

#: The cells the sweep runs. One per pattern, at the entry and stop the sources
#: state, because power is a property of the detector and the sample size and
#: sweeping it over 22 cells would buy nothing but time.
CELLS = (
    {"pattern": "inside", "entry": "stop_mother", "stop": "mother_far", "side_rule": "straddle"},
    {"pattern": "pin", "entry": "market", "stop": "tail", "side_rule": "own"},
    {"pattern": "fakey", "entry": "stop_back", "stop": "break_extreme", "side_rule": "own"},
    {"pattern": "combo", "entry": "stop_mother", "stop": "mother_far", "side_rule": "own"},
)

BASE = {
    "tail_share": P.TAIL_SOURCE,
    "expiry": 3,
    "pip_pad": 0.02,
    "shape": "source",
    "break_ref": "inside",
    "close_back": "mother",
    "fake_bars": 1,
}


def plant(series: Series, trades: list[P.Trade], strength: float, horizon: int) -> Series:
    """A ramped directional drift after each setup, carrying each bar's shape.

    The shift is cumulative, so overlapping windows add - which is what a real
    drift would do and is the reason the recovered effect is read off the
    measurement rather than assumed equal to `strength`.
    """
    n = len(series.close)
    shift = np.zeros(n)
    for t in trades:
        start = t.fill + 1
        end = min(start + horizon, n)
        if end <= start:
            continue
        steps = np.arange(1, end - start + 1, dtype=float) / horizon
        shift[start:end] += t.side * strength * t.risk * steps
        if end < n:
            shift[end:] += t.side * strength * t.risk * (end - start) / horizon
    return Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=series.open + shift,
        high=series.high + shift,
        low=series.low + shift,
        close=series.close + shift,
    )


def one(feed: str, interval: str) -> list[dict]:
    con = sqlite3.connect(P.store_path(), uri=True)
    try:
        series = P.load(con, feed, interval)
    finally:
        con.close()
    if series is None:
        return []
    span = int(P.SETTINGS[interval]["unit_span"])
    horizon = int(P.SETTINGS[interval]["horizon"])
    unit = P.units(series, span)
    strata = P.strata_of(series, unit, span)
    ctx = P.trend_and_legs(series, reach=3)
    rows: list[dict] = []
    for cell in CELLS:
        kw = {**BASE, **cell}
        seed_trades, _ = P.setups(series, unit, strata, ctx, horizon=horizon, **kw)
        if not seed_trades:
            continue
        for strength in STRENGTHS:
            planted = plant(series, seed_trades, strength, horizon)
            u = P.units(planted, span)
            st_ = P.strata_of(planted, u, span)
            c = P.trend_and_legs(planted, reach=3)
            trades, cen = P.setups(planted, u, st_, c, horizon=horizon, **kw)
            if not trades:
                rows.append(
                    {
                        "feed": feed,
                        "interval": interval,
                        "cell": cell["pattern"],
                        "strength": strength,
                        "n": 0,
                    }
                )
                continue
            got = P.settle(planted, trades, u, target=2.0, horizon=horizon)
            plac = P.placebo_trades(
                planted,
                u,
                st_,
                c,
                signals=cen.signals,
                horizon=horizon,
                draws=R.MATCHED_DRAWS,
                seed=7,
                **kw,
            )
            mat = P.settle(planted, plac, u, target=2.0, horizon=horizon)
            live, live_m = got.decided, mat.decided
            real = R._money(got.r[live], got.day[live], seed=3)
            placebo = R._money(mat.r[live_m], mat.day[live_m], seed=3)
            rows.append(
                {
                    "feed": feed,
                    "interval": interval,
                    "cell": cell["pattern"],
                    "strength": strength,
                    "n": real["n"],
                    "trades": cen.trades,
                    "mean": real.get("mean"),
                    "se": real.get("se"),
                    "placebo": placebo.get("mean"),
                    "excess": R._excess(real, placebo),
                }
            )
    return rows


def walk_bars(n: int, seed: int) -> Series:
    """A driftless walk whose bars are built from the path, not pasted on.

    Sub-bar resolution, because `pattern-fingerprint.md` records that pattern
    rates depend on wick structure: a close series with wicks bolted on decides
    the answer before the measurement.
    """
    rng = random.Random(seed)
    close = 100.0
    rows = []
    for _ in range(n):
        open_ = close
        path = [open_]
        for _ in range(24):
            path.append(path[-1] + rng.gauss(0.0, 0.05))
        close = path[-1]
        rows.append((open_, max(path), min(path), close))
    arr = np.asarray(rows, dtype=float)
    return Series(
        feed="walk",
        venue="WALK",
        interval="1d",
        ts=np.arange(n, dtype=float) * 86_400.0,
        open=arr[:, 0],
        high=arr[:, 1],
        low=arr[:, 2],
        close=arr[:, 3],
    )


def walk_check(*, walks: int = 6, bars: int = 4000, draws: int = 10) -> None:
    """The size of the entry-mechanic leak, on a series where the answer is zero.

        PA_WALK=1 uv run python research/ideas/price_action_power.py

    A driftless walk is a martingale, so a time-bounded stopping rule on it
    cannot have positive expectancy. This prints the inside-bar breakout's mean
    R at 2R against two placebos - one entered at a random bar's **close**,
    which is what this harness first used, and one entered through **the same
    mechanics** at random bars - for both settlements. The first gap is the
    number the first version of this study would have published; the second is
    what is left once the mechanic appears in both arms.

    It is the table in `price-action.md`'s first section, and it exists as a
    function so that table is reproducible from a named script with named
    parameters rather than from a transcript.
    """
    print(f"walks={walks} bars={bars} placebo_draws={draws} target=2R horizon=20")
    for fill_at in ("trigger", "close"):
        real_r, old_r, new_r = [], [], []
        for seed in range(walks):
            series = walk_bars(bars, 500 + seed)
            unit = P.units(series, 20)
            strata = P.strata_of(series, unit, 20)
            ctx = P.trend_and_legs(series, reach=3)
            kw = dict(
                pattern="inside",
                entry="stop_mother",
                stop="mother_far",
                side_rule="straddle",
                fill_at=fill_at,
            )
            trades, cen = P.setups(series, unit, strata, ctx, horizon=20, **kw)
            got = P.settle(series, trades, unit, target=2.0, horizon=20)
            real_r.append(got.r[got.decided])
            old = _close_entry_placebo(series, trades, unit, draws=draws, seed=seed)
            old_r.append(old.r[old.decided])
            made = P.placebo_trades(
                series,
                unit,
                strata,
                ctx,
                signals=cen.signals,
                horizon=20,
                draws=draws,
                seed=seed,
                **kw,
            )
            new = P.settle(series, made, unit, target=2.0, horizon=20)
            new_r.append(new.r[new.decided])
        real, old, new = (np.concatenate(x) for x in (real_r, old_r, new_r))

        def line(name: str, arr: np.ndarray) -> str:
            se = float(arr.std(ddof=1)) / float(np.sqrt(len(arr)))
            return f"  {name:44s} {arr.mean():+.4f} +- {se:.4f}  n={len(arr)}"

        def gap(a: np.ndarray, b: np.ndarray) -> str:
            se = (a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)) ** 0.5
            return f"  {'  -> the gap':44s} {a.mean() - b.mean():+.4f} +- {se:.4f}"

        print(f"fill_at={fill_at}")
        print(line("the rule", real))
        print(line("placebo entered at a random bar's close", old))
        print(gap(real, old))
        print(line("placebo through the same mechanics", new))
        print(gap(real, new))


def _close_entry_placebo(series, trades, unit, *, draws: int, seed: int) -> P.Settled:
    """The placebo this harness used **before** the leak was found.

    Kept so the size of the mistake is reproducible rather than remembered. It
    enters at a random bar's close with the real trade's side and risk, which
    is `patterns.md`'s "identical stop and target distances at an arbitrary
    bar" - correct as far as it goes, and wrong here because the real arm's
    entry is a stop order and this one's is not.
    """
    rng = random.Random(seed)
    n = len(series.close)
    made = []
    for t in trades:
        for _ in range(draws):
            j = rng.randrange(20, max(21, n - 22))
            entry = float(series.close[j])
            made.append(
                P.Trade(
                    signal=j,
                    fill=j,
                    side=t.side,
                    entry=entry,
                    stop=entry - t.side * t.risk,
                    risk=t.risk,
                    factors=0,
                    stratum=0,
                    day=int(series.ts[j] // 86_400),
                )
            )
    return P.settle(series, made, unit, target=2.0, horizon=20)


def _call(job):
    try:
        return one(*job)
    except Exception as exc:
        print(f"{job}: {type(exc).__name__}: {exc}", flush=True)
        return []


def main() -> int:
    out_dir = Path(os.environ.get("PA_OUT") or "pa-out")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "power.jsonl"
    jobs = [(f, i) for i in R.INTERVALS for f in R.FEEDS]
    print(f"{len(jobs)} jobs, {len(CELLS)} cells, {len(STRENGTHS)} strengths -> {out}", flush=True)
    started = time.time()
    with out.open("w") as fh, ProcessPoolExecutor(max_workers=R.WORKERS) as pool:
        for job, rows in zip(jobs, pool.map(_call, jobs), strict=True):
            for row in rows:
                fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(f"{job}: {len(rows)} rows, {time.time() - started:.0f}s", flush=True)
    print(f"done in {time.time() - started:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    random.seed(0)
    if os.environ.get("PA_WALK"):
        walk_check()
        sys.exit(0)
    sys.exit(main())
