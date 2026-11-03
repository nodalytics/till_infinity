"""Run the whole fear-and-greed study: one invocation, one output directory.

    uv run python -m research.ideas.fear_greed_run --out <dir> --jobs 16

One process by default so it is safe on a shared box; `--jobs` fans the
per-(series, arm) work out and is the only thing to raise on a larger one.
Output is one JSON object per line per section, so a partial run is still
readable - a sweep that has to finish before it says anything is a sweep
nobody runs twice.

## The order is the pre-registration

1. **`control.jsonl`** - the triangle screen with its misalignment sweep, and
   the 2008 carry crash. Written first and read first: if the fear reading does
   not light up on the episode Brunnermeier, Nagel and Pedersen (2008)
   describe, nothing after it means anything.
2. **`asym.jsonl`** - up longer and slower against down faster and deeper, per
   instrument, per era, per arm, at both swing scales.
3. **`levels.jsonl`** - the fear/greed label on a level's formation, per book
   and per instrument.
4. **`trade.jsonl`** - the short-the-cross rule in R, with the duty-cycle twin.
5. **`power.jsonl`** - every planted effect and its strength sweep.

## What is fixed before the run

* **1d is primary.** 4,980 bars common to all eight feeds on OANDA, 2007-05-16
  to 2026-08-13, 19.25 years. 15m is carried as a **separate rule** - 4,760
  bars, about 50 days - and never pooled with 1d, because the swing length, the
  volatility unit and the hold all scale with the bar.
* **Real legs carry every range-based question**, synthetic crosses carry the
  close-exact ones. A cross's bar extremes are bounds inflated about 1.7x on
  the JPY pairs, and `levels.chains` finds 4 displacement legs there in 19
  years against 83 on audusd.
* **Four null arms with `DRAWS` draws each**, every one through the same
  detector over the same bar geometry, plus two deterministic mirrors
  (`sign-flip`, `drift-free`) that are diagnostics and not nulls.
* **Nothing is priced.** The primary result is gross and says so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import random
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import research.ideas.fear_greed as F
import research.ideas.fear_greed_asym as A
import research.ideas.fear_greed_control as C
import research.ideas.fear_greed_levels as L
import research.ideas.fear_greed_power as P
import research.ideas.fear_greed_trade as T

#: Draws per surrogate arm. **Sixteen, not the four `level-shield.md` uses, and
#: the change is a measured correction rather than caution.**
#:
#: The exceedance test asks a real value to beat the *extreme* of all the draws,
#: and the max of four draws is a badly biased estimate of an arm's tail: on
#: audjpy at `reach` 10 the `bar-shuffle` speed gap has mean -0.171 and **sd
#: 0.106** over sixteen draws, spanning -0.467 to -0.024, where the panel's four
#: draws landed in a range of 0.06. Too few draws makes the null look tighter
#: than it is, so it **manufactures exceedances** - the test is anti-conservative
#: exactly where a positive claim is made. At four draws this study read 8 of 84
#: cells exceeding; at sixteen it reads 1 of 30, and both of its substantive
#: positive cells disappeared.
#:
#: A null conclusion is unaffected by the bias (a wider arm only widens the
#: margin), so the sections that concluded nothing-exceeds were conservative at
#: four. The cost of sixteen is runtime, and the whole panel ran in 91 seconds
#: at four on 64 cores, so there is nothing to trade off.
DRAWS = 16

#: Day-block bootstrap resamples. 400 is enough for a 95% interval's
#: quantiles; the interval is reported, never a standard error alone.
BOOTSTRAP = 400

#: Books whose crash class is too thin to measure, as counted on real data:
#: `Levels` publishes about 300 levels over 4,980 days and `BjorgumLevels`
#: about 150, which leaves **2 to 6 crash-labelled levels with a touch** per
#: instrument. They are still run on the real arm so the write-up can report
#: the sample, and the surrogate arms are skipped for them because an arm for
#: an unmeasurable cell buys nothing but runtime.
THIN_BOOKS = frozenset({"levels", "bjorgum"})


def seed(*parts: object) -> int:
    """A **reproducible** seed from the cell's own identity.

    A builtin `hash` of a tuple containing a string is salted by
    `PYTHONHASHSEED`, so seeding a surrogate from one draws different
    surrogates in every process. The first version of this file did exactly
    that, and the consequence was measured rather than guessed: the panel's arm
    means differ from a local run's on the same code and the same data -
    audjpy's `bar-shuffle` speed gap read -0.172 locally and **-0.266** on the
    panel - while every real value matched to the digit. A surrogate range that
    moves between runs cannot be the thing a verdict is scored against.

    `blake2b` over the repr is stable across processes and machines.
    """
    text = "|".join(repr(x) for x in parts)
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big")


def _arms(series: F.Series, draws: int) -> list[tuple[str, int, F.Series]]:
    """`(arm, draw, series)` for every arm, with one GARCH fit shared.

    The fit is done once per series rather than once per draw: it is a grid
    over 25 (alpha, beta) pairs and the arm exists to supply **clustering of
    about the right strength** rather than to be the best model, so refitting
    per draw would cost 25 likelihood passes to change nothing.
    """
    plan: list[tuple[str, int, F.Series]] = [("real", 0, series)]
    rets = np.diff(np.log(np.maximum(series.close, 1e-12)))
    fitted = F.fit_garch(rets)
    for arm, make in F.ARMS.items():
        if make is None:
            continue
        for draw in range(draws if arm in F.DRAWN else 1):
            rng = random.Random(seed(series.feed, series.interval, arm, draw))
            built = make(series, rng, fitted) if arm == "garch-bars" else make(series, rng)
            plan.append((arm, draw, built))
    return plan


def _load(interval: str) -> dict[str, F.Series]:
    con = sqlite3.connect(F.STORE, uri=True)
    try:
        return F.load(con, interval)
    finally:
        con.close()


def job_asym(args: tuple[str, str, int]) -> list[dict]:
    """Every arm's asymmetry table for one (feed, interval), at both reaches.

    Plus, on the real arm only, the swing shape **conditioned on the risk-off
    index** - which is where the coordinator's correction bites. The framing's
    claim is not "JPY crosses fall" but "JPY crosses fall *fast when fear is
    rising*", and `direction-is-closed-not-just-null` is a result about
    direction as a standalone gate, not about direction inside a volatility
    state. So `A.conditioned` reports the gap within terciles of
    `volatile_off`, within terciles of `directional_off`, **and** direction
    inside volatility - the interaction neither pooled reading can show.
    """
    feed, interval, draws = args
    held = _load(interval)
    series = held[feed]
    span = F.SETTINGS[interval]["unit_span"]
    out: list[dict] = []
    for arm, draw, built in _arms(series, draws):
        for reach in A.SWING_REACHES:
            for on_closes in (True, False) if F.range_trusted(series) else (True,):
                rng = random.Random(seed(feed, arm, draw, reach, on_closes))
                row = A.one_series(
                    built,
                    unit_span=span,
                    on_closes=on_closes,
                    draws=BOOTSTRAP if arm == "real" else 0,
                    rng=rng,
                    reach=reach,
                )
                row.update({"arm": arm, "draw": draw, "interval": interval})
                out.append(row)
    moods = {f: F.mood_path(held[f]) for f in F.LEGS}
    basket = F.basket_risk_off(moods)
    for reach in A.SWING_REACHES:
        got = A.conditioned(
            series, basket, unit_span=span, on_closes=True, reach=reach
        )
        out.append({**got, "section": "conditioned", "arm": "real", "interval": interval})
    return out


def job_levels(args: tuple[str, str, int]) -> list[dict]:
    """Every arm's label table for one (feed, interval), over the four books."""
    feed, interval, draws = args
    held = _load(interval)
    series = held[feed]
    if not F.range_trusted(series):
        return []
    settings = F.SETTINGS[interval]
    moods = {f: F.mood_path(held[f]) for f in F.LEGS}
    basket = F.basket_risk_off(moods)
    out: list[dict] = []
    for arm, draw, built in _arms(series, draws):
        for book in L.BOOKS:
            if arm != "real" and book in THIN_BOOKS:
                continue
            row = L.one_series(
                built,
                basket,
                book=book,
                unit_span=settings["unit_span"],
                horizon=settings["horizon"],
            )
            row.update({"arm": arm, "draw": draw, "interval": interval})
            out.append(row)
    return out


def job_trade(args: tuple[str, str, int]) -> list[dict]:
    """Every arm's trade table for one (feed, interval), with the random twin."""
    feed, interval, draws = args
    held = _load(interval)
    series = held[feed]
    settings = F.SETTINGS[interval]
    span, horizon = settings["unit_span"], settings["horizon"]
    moods = {f: F.mood_path(held[f]) for f in F.LEGS}
    basket = F.basket_risk_off(moods)
    gates = {
        "all": np.concatenate(
            [np.zeros(T.LOOKBACK, bool), np.ones(len(series) - T.LOOKBACK, bool)]
        ),
        "volatile_off": T.gate(basket.volatile_off, T.GATE_Q),
        "directional_off": T.gate(basket.directional_off, T.GATE_Q),
        "risk_off": T.gate(basket.risk_off, T.GATE_Q),
    }
    # The interaction the framing claims: direction inside a volatility state.
    gates["both"] = gates["volatile_off"] & gates["directional_off"]
    out: list[dict] = []
    for arm, draw, built in _arms(series, draws):
        unit = F.unit_for(built, span)
        for name, fires in gates.items():
            for target, stop in T.RACES:
                for side in (-1, 1):
                    rng = random.Random(
                        seed(feed, arm, draw, name, target, stop, side)
                    )
                    got = T.races(
                        built,
                        unit,
                        fires,
                        side=side,
                        target=target,
                        stop=stop,
                        horizon=horizon,
                    )
                    row = T.score(
                        got,
                        built.ts,
                        BOOTSTRAP if arm == "real" else 0,
                        rng,
                        horizon,
                    )
                    row.update(
                        {
                            "feed": feed,
                            "kind": series.kind,
                            "synthetic": series.synthetic,
                            "arm": arm,
                            "draw": draw,
                            "interval": interval,
                            "gate": name,
                            "target": target,
                            "stop": stop,
                            "side": side,
                        }
                    )
                    out.append(row)
                    if arm != "real" or row["n"] < 8:
                        continue
                    # The duty-cycle twin, aimed at the same **bars held**
                    # rather than the same trade count: every pause rule on
                    # this desk beat its baseline and none beat its own random
                    # twin. Positions block each other, so the realised duty
                    # will not match the target exactly - which is why the
                    # twin reports its own `duty` and the comparison is made
                    # on the pair of them rather than on the target.
                    twin = T.random_twin(
                        built,
                        unit,
                        row["duty"] / max(1.0, row["median_hold"]),
                        side=side,
                        target=target,
                        stop=stop,
                        horizon=horizon,
                        rng=rng,
                    )
                    labels = {
                        k: row[k]
                        for k in ("feed", "kind", "synthetic", "interval", "gate", "target", "stop", "side")
                    }
                    out.append(
                        {
                            **T.score(twin, built.ts, 0, rng, horizon),
                            **labels,
                            "arm": "random-twin",
                            "draw": 0,
                            "twin_of_duty": row["duty"],
                        }
                    )
    return out


def job_power(args: tuple[str, str, int]) -> list[dict]:
    """The planted sweeps for one feed. Reported as its own section."""
    feed, interval, draws = args
    held = _load(interval)
    series = held[feed]
    settings = F.SETTINGS[interval]
    span, horizon = settings["unit_span"], settings["horizon"]
    moods = {f: F.mood_path(held[f]) for f in F.LEGS}
    basket = F.basket_risk_off(moods)
    rng = random.Random(seed(feed, "power"))
    out: list[dict] = []
    for reach in A.SWING_REACHES:
        got = P.sweep_asymmetry(
            series, unit_span=span, reach=reach, draws=draws, rng=rng
        )
        for kind, rows in got.items():
            for row in rows:
                out.append({**row, "feed": feed, "section": f"asym-{kind}", "reach": reach})
    for row in P.sweep_trade(
        series,
        basket,
        unit_span=span,
        horizon=horizon,
        quantile=T.GATE_Q,
        target=2.0,
        stop=1.0,
        draws=max(2, draws // 2),
        rng=rng,
    ):
        out.append({**row, "feed": feed, "section": "trade"})
    if F.range_trusted(series):
        for book in ("pivots", "pips"):
            for row in P.sweep_levels(
                series,
                basket,
                unit_span=span,
                horizon=horizon,
                book=book,
                draws=max(1, draws // 2),
                rng=rng,
            ):
                out.append({**row, "feed": feed, "section": "levels"})
    return out


def write(path: pathlib.Path, rows) -> int:
    with path.open("w") as handle:
        count = 0
        for row in rows:
            handle.write(json.dumps(row, default=float) + "\n")
            count += 1
    return count


def fan(jobs, work, workers: int):
    """`work` over `jobs`, one process each, flattening the per-job lists.

    Serial at `workers` 1, which is the default: this study's own box has 8
    shared cores and `finding-edges` is explicit that research does not get to
    starve something else.
    """
    if workers <= 1:
        for job in jobs:
            yield from work(job)
        return
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for got in pool.map(work, jobs):
            yield from got


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--jobs", type=int, default=int(os.environ.get("FEARGREED_JOBS", "1")))
    parser.add_argument("--draws", type=int, default=DRAWS)
    parser.add_argument(
        "--intervals",
        default="1d",
        help="comma separated; 1d is primary and 15m is a separate rule, never pooled",
    )
    parser.add_argument(
        "--sections",
        default="control,asym,levels,trade,power",
        help="comma separated, run in the pre-registered order",
    )
    args = parser.parse_args(argv)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    intervals = [x.strip() for x in args.intervals.split(",") if x.strip()]
    sections = [x.strip() for x in args.sections.split(",") if x.strip()]
    started = time.time()

    if "control" in sections:
        rows: list[dict] = []
        for interval in intervals:
            held = _load(interval)
            rows.append(
                {
                    "interval": interval,
                    "section": "coverage",
                    "venue": F.VENUE,
                    "bars": len(held["audusd"]),
                    "years": held["audusd"].years,
                    "feeds": sorted(held),
                }
            )
            for shift in C.MISALIGN:
                for got in C.plant_misalign(held, shift):
                    rows.append({**got, "section": "triangle", "shift": shift, "interval": interval})
            moods = {f: F.mood_path(held[f]) for f in F.LEGS}
            basket = F.basket_risk_off(moods)
            rows.append(
                {
                    **C.crash_control(held, basket),
                    "section": "crash",
                    "interval": interval,
                }
            )
            for name in ("risk_off", "volatile_off", "directional_off"):
                rows.append(
                    {
                        "section": "boundary",
                        "interval": interval,
                        "reading": name,
                        **{
                            f"q{int(q * 100)}": T.boundary(getattr(basket, name), q)
                            for q in T.GATE_QUANTILES
                        },
                    }
                )
            rng = random.Random(20081026)
            for depth in C.CRASH_DEPTHS:
                for draw in range(args.draws):
                    rows.append(
                        {
                            **C.plant_crash(held, depth, rng=rng),
                            "section": "crash-power",
                            "interval": interval,
                            "draw": draw,
                        }
                    )
        print(f"control  {write(out / 'control.jsonl', rows)} rows  {time.time() - started:.0f}s")

    plans = {
        "asym": (job_asym, lambda held: sorted(held)),
        "levels": (job_levels, lambda held: list(F.LEGS)),
        "trade": (job_trade, lambda held: sorted(held)),
        "power": (job_power, lambda held: ["audjpy", "nzdjpy", "audusd", "eurgbp"]),
    }
    for name, (work, pick) in plans.items():
        if name not in sections:
            continue
        mark = time.time()
        jobs: list[tuple[str, str, int]] = []
        for interval in intervals:
            held = _load(interval)
            jobs += [(feed, interval, args.draws) for feed in pick(held)]
        count = write(out / f"{name}.jsonl", fan(jobs, work, args.jobs))
        print(f"{name:8s} {count} rows over {len(jobs)} jobs  {time.time() - mark:.0f}s")
    print(f"done in {time.time() - started:.0f}s -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
