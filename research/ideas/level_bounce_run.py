"""Run the level-bounce panel: every feed, every interval, every kind, every arm.

One job per `(feed, interval, kind)`, because the expensive part is replaying
the book bar by bar and that is per series. Output is one JSON object per line
so a partial run is still readable - a sweep that has to finish before it says
anything is a sweep nobody runs twice.

**Pre-registered before the run**, so the report cannot be a selection:

* the cells are **feed x interval x kind x grade**; the arms are `placebo`
  (the real series with every level displaced 1.5-3.0 units and kept clear of
  any real one) and `garch-bars`, `walk-geometry` and `bar-shuffle` through the
  same detector, with `BOUNCE_DRAWS` draws each;
* **the deciding statistic is mean R**, at a stop one volatility unit through
  the level and targets at 1, 2 and 3 times the realised risk, where a
  driftless walk pays exactly zero at every target. A hit rate is descriptive
  only: **a poor win rate is not a failure**, and a score that raises
  expectancy while lowering the hit rate is still an edge. The bounce *rate* was
  never going to be the finding, because a return rate is the quantity that is
  geometry - `fade-to-value`'s 82% was matched by a distance-matched placebo on
  every class and a walk reads 0.825;
* **part 2's statistic is `grade_r`** - the mean R of touches whose level's
  *previous* departures scored above their cell's median grade, minus those
  below, within compression quintile crossed with level-age bin, paired on the
  same blocks. The grade gap in hit rate and the grade's AUC are reported
  beside it as description;
* **every arm reports its per-trade sd and the sample its own mean and sd imply
  for |t| = 2.** A score that selects sharper bounces selects larger moves, so
  it buys a higher variance; two arms' means are not comparable without the
  evidence each one rests on, and an arm that wins on the mean while needing
  four times the sample has not won;
* the direction is pre-stated: the claim predicts a **positive** R difference
  for `sharp_share`. A negative one is not a weaker version of the claim, it is
  the opposite of it;
* **a finding needs** the real value outside the hardest null arm's draws, the
  sign consistent between 1d and at least one of 1h/15m, survival of
  Benjamini-Hochberg over every cell, a deflated Sharpe over the full trial
  count that is still above 0.95, and - for the Kalman book to be judged as
  earning its complexity - `levels` beating `pivots` on mean R in excess of its
  own nulls. `tv-indicators.md`'s 0.58-0.59 first-touch hold against 0.565 for
  walk levels is the descriptive number part 1 has to land near, and a
  reproduction check rather than a result;
* `hold_share` and `hold_dev` are carried as reproduction arms.
  `record-auc.md` puts the raw record between 0.4977 and 0.5104 across twelve
  configurations, so a `hold_share` AUC far from 0.50 here means this harness
  is wrong before it means anything about levels.

Nothing is costed. A hold rate and a bounce shape are geometry, so the primary
result is **gross** and runs on the full history rather than on the six feeds
with enough recorded quotes to measure a spread (eurusd, gbpusd, gold, btc,
us100, spx500 - and the last two are not the venue the live desk trades).
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

import research.ideas.level_bounce as B
import research.ideas.level_bounce_agg as A
import research.ideas.level_bounce_duration as D
from research.ideas.level_shield import fit_garch

#: Draws per surrogate arm. Four, as in `level-shield.md`: enough that "outside
#: the hardest arm's draws" is a statement about a range and not about one
#: number, and the arms are rebuilt from scratch each draw.
DRAWS = int(os.environ.get("BOUNCE_DRAWS") or 4)

#: Where the run writes. A directory, not a file, so a sweep and its power
#: run can live together and be handed over as one path.
OUT = Path(os.environ.get("BOUNCE_OUT") or "bounce-out")

#: Workers. **Defaults to 2, not to the core count**, because this file gets
#: run on a shared 8-core box by accident and a pool sized to the machine
#: starves whatever else is on it. Set it explicitly on the big box.
WORKERS = int(os.environ.get("BOUNCE_WORKERS") or 2)

INTERVALS = tuple((os.environ.get("BOUNCE_INTERVALS") or "1d 1h 15m").replace(",", " ").split())


def _names(var: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = (os.environ.get(var) or "").replace(",", " ").split()
    return tuple(raw) if raw else default


def _stats(
    rows, kind: str, arm: str, draw: int, feed: str, interval: str, venue: str, horizon: int = 20
) -> dict:
    """Every estimator for one (series, kind, arm, draw), as one JSON row."""
    mask = np.ones(len(rows), dtype=bool)
    out: dict = {
        "feed": feed,
        "venue": venue,
        "interval": interval,
        "kind": kind,
        "arm": arm,
        "draw": draw,
        "episodes": len(rows),
        "levels": len(set(rows.tag.tolist())),
        "shares": A.shares(rows, mask),
        "strata": A.by_stratum(rows, mask),
        "tie_share": float(rows.tie.mean()) if len(rows) else 0.0,
        # Carried because both are selections on the scored population: a
        # touch bar closing a full unit through the level leaves no trade to
        # price, and dropping those tilts what survives in favour of the
        # bounce. Identical on every arm, so the comparison holds; the
        # absolute numbers are conditioned on it.
        "skipped": rows.skipped,
        "undecided": rows.undecided,
    }
    hold = A.hold_for(rows, mask, seed=draw)
    out["hold"] = None if hold is None else {"n": hold.n, "value": hold.value, "sd": hold.sd}
    out["excursion"] = float(rows.excursion.mean()) if len(rows) else 0.0
    for side, label in ((1, "support"), (-1, "resistance")):
        got = A.hold_for(rows, mask & (rows.away == side), seed=draw)
        out[f"hold_{label}"] = None if got is None else {"n": got.n, "value": got.value, "sd": got.sd}

    out["r"] = {}
    for target in B.TARGETS:
        got = A.r_for(rows, mask, target, seed=draw)
        out["r"][str(target)] = None if got is None else _money(got)
    out["r_mtm"] = (
        _money(A._money(rows.r_mtm, rows.block, draws=A.DRAWS, seed=draw))
        if len(rows) >= A.LEAST
        else None
    )

    # The duration arm: how long a departure lasts, which the committed run
    # never measured. Pooled first - the per-level grade below has no power,
    # measured, so the exponent is the primary reading and the grade is not.
    out["survival"] = D.as_json(D.survival_for(rows, mask, horizon, seed=draw))
    out["duration_censored_all"] = (
        float((rows.duration == B.DURATION_CENSORED).mean()) if len(rows) else 0.0
    )
    out["correlations"] = D.correlations(rows, mask)
    for side, label in ((1, "support"), (-1, "resistance")):
        out[f"survival_{label}"] = D.as_json(
            D.survival_for(rows, mask & (rows.away == side), horizon, seed=draw)
        )

    out["grades"] = {}
    for grade in B.GRADES:
        gap = A.grade_gap_for(rows, mask, grade, seed=draw)
        auc = A.grade_auc_for(rows, mask, grade, seed=draw)
        entry: dict = {
            "gap": None if gap is None else {"n": gap.n, "value": gap.value, "sd": gap.sd, "lo": gap.lo, "hi": gap.hi},
            "auc": None if auc is None else {"n": auc.n, "value": auc.value, "sd": auc.sd},
            "r": {},
        }
        entry["survival"] = D.split_as_json(
            D.grade_survival_for(rows, mask, grade, horizon, seed=draw)
        )
        for target in B.TARGETS:
            split = A.grade_r_for(rows, mask, grade, target, seed=draw)
            entry["r"][str(target)] = (
                None
                if split is None
                else {
                    "high": _money(split[0]),
                    "low": _money(split[1]),
                    "diff": _money(split[2]),
                }
            )
        out["grades"][grade] = entry
    return out


def _money(got: A.Money | None) -> dict | None:
    """A `Money` as JSON, with the implied sample carried beside the mean.

    `needed` travels with every mean because the correction that prompted it
    is that two arms with different variances rest on different amounts of
    evidence, and a report that prints only means invites exactly that
    comparison.
    """
    if got is None:
        return None

    def finite(x: float) -> float | None:
        # `None` rather than a JSON `NaN` or `Infinity`, which are not JSON and
        # are silently accepted by Python's own parser - so a file that only
        # ever round-trips through `json` here would break the first time
        # anything else read it.
        return None if x != x or x in (float("inf"), float("-inf")) else float(x)

    return {
        "n": got.n,
        "mean": got.mean,
        "se": got.se,
        "sd": got.sd,
        "t": got.t,
        "needed": finite(got.needed),
        "profit_factor": finite(got.profit_factor),
        "win_rate": got.win_rate,
        "sharpe": got.sharpe,
    }


def one(job: tuple[str, str, str]) -> list[dict]:
    """One `(feed, interval, kind)`: the real arm, the placebo, the surrogates."""
    feed, interval, kind = job
    con = sqlite3.connect(B.BOUNCE_STORE, uri=True)
    try:
        series = B.load(con, feed, interval)
    finally:
        con.close()
    if series is None:
        return []
    settings = B.SETTINGS[interval]
    span = int(settings["unit_span"])
    horizon = int(settings["horizon"])
    out: list[dict] = []

    unit = B.units(series, span)
    real = B.measure(series, kind, interval=interval, settings=settings)
    out.append(_stats(real.rows, kind, "real", 0, feed, interval, series.venue, horizon))

    books = B.book_path(series, kind, unit_span=span, interval=interval)
    for draw in range(DRAWS):
        rng = np.random.default_rng(10_000 + draw)
        rows = B.episodes(
            series,
            B.placebo_books(books, unit, rng),
            unit,
            B.strata_of(unit, span),
            interval=interval,
            horizon=int(settings["horizon"]),
        )
        out.append(_stats(rows, kind, "placebo", draw, feed, interval, series.venue, horizon))

    rets = np.diff(np.log(np.maximum(series.close, 1e-12)))
    fitted = fit_garch(rets)
    for index, (arm, make) in enumerate(B.ARMS.items()):
        if make is None:
            continue
        for draw in range(DRAWS):
            # Seeded off the arm's **position**, not `hash(arm)`: string hashing
            # is salted per process, so a hash-seeded run is not reproducible
            # and two workers would disagree about which draw they made.
            rng = random.Random(20_000 + 1_000 * index + draw)
            made = make(series, rng, fitted) if arm == "garch-bars" else make(series, rng)
            got = B.measure(made, kind, interval=interval, settings=settings)
            out.append(_stats(got.rows, kind, arm, draw, feed, interval, series.venue, horizon))
    return out


def sweep(job: tuple[str, str, str]) -> list[dict]:
    """The `RUN_EFF` grid on the real arm, reported whole on the mean.

    `sweep-thresholds-on-the-mean-not-z` is recorded because a z grid faked a
    ridge at the chosen threshold where the mean grid was monotone. Only the
    real arm, because the grid is about whether the definition is a knob and
    not about significance.
    """
    feed, interval, kind = job
    con = sqlite3.connect(B.BOUNCE_STORE, uri=True)
    try:
        series = B.load(con, feed, interval)
    finally:
        con.close()
    if series is None:
        return []
    settings = B.SETTINGS[interval]
    span = int(settings["unit_span"])
    horizon = int(settings["horizon"])
    unit = B.units(series, span)
    books = B.book_path(series, kind, unit_span=span, interval=interval)
    strata = B.strata_of(unit, span)
    out = []
    for eff in B.RUN_EFFS:
        rows = B.episodes(
            series,
            books,
            unit,
            strata,
            interval=interval,
            horizon=int(settings["horizon"]),
            run_eff=eff,
        )
        row = _stats(rows, kind, "real", 0, feed, interval, series.venue, horizon)
        row["run_eff"] = eff
        out.append(row)
    return out


def main() -> None:
    feeds = _names("BOUNCE_FEEDS", B.FEEDS)
    kinds = _names("BOUNCE_KINDS", B.KINDS)
    jobs = [(f, i, k) for i in INTERVALS for f in feeds for k in kinds]
    OUT.mkdir(parents=True, exist_ok=True)
    panel, grid = OUT / "panel.jsonl", OUT / "effgrid.jsonl"
    started = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=WORKERS) as pool, panel.open("w") as fh:
        for rows in pool.map(one, jobs):
            for row in rows:
                fh.write(json.dumps(row) + "\n")
            fh.flush()
            done += 1
            print(
                f"[{done}/{len(jobs)}] {time.time() - started:7.1f}s {len(rows):3d} rows",
                file=sys.stderr,
                flush=True,
            )
    with ProcessPoolExecutor(max_workers=WORKERS) as pool, grid.open("w") as fh:
        for rows in pool.map(sweep, [(f, "1d", "levels") for f in feeds]):
            for row in rows:
                fh.write(json.dumps(row) + "\n")
            fh.flush()
    print(f"wrote {panel} and {grid} in {time.time() - started:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
