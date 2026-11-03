"""Run the stop-coverage panel: every feed, every null arm, every horizon.

One process per (feed, interval, venue). Output is one JSON object per line so
a partial run is still readable - a sweep that has to finish before it says
anything is a sweep nobody runs twice.

Pre-registered in [`research/docs/stop-coverage.md`](../docs/stop-coverage.md)
before this ran. In short:

* the cells are feed x interval x unit x horizon x side x stop arm, the null
  arms are `garch-bars`, `walk-geometry` and `bar-shuffle` with **16 draws
  each**, and the headline statistic is the realised coverage against the
  0.100 target;
* the primary horizon is 20 bars, swept over {1, 5, 20, 48, 96}, and no
  verdict may depend on the choice;
* the online estimator earns its state only by beating `t-sqrt-h`, not
  `t-fixed`: `student_stop` carries no horizon, so beating it at `H` = 20 is a
  missing square root rather than a finding;
* every plant carries its own zero control, and `scale` **must read nothing**
  at every strength because the measurement is scale-equivariant.

Nothing here is priced except the 15m rows on the six costed feeds, and
`us100` and `spx500` are not the venue the live desk trades.
"""

import argparse
import json
import random
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import research.ideas.level_shield as L
import research.ideas.stop_coverage as S


def parse() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True, help="output directory")
    ap.add_argument("--workers", type=int, default=8, help="worker processes")
    ap.add_argument("--draws", type=int, default=S.DRAWS, help="draws per null arm")
    ap.add_argument("--store", default=S.STORE, help="sqlite URI for the price store")
    ap.add_argument(
        "--feeds",
        default="",
        help="space- or comma-separated feeds, else the pre-registered panel",
    )
    ap.add_argument(
        "--intervals", default="1d,15m", help="space- or comma-separated intervals"
    )
    ap.add_argument(
        "--horizons",
        default="",
        help="space- or comma-separated horizons in bars, else the swept set",
    )
    ap.add_argument("--no-plants", action="store_true", help="skip the power sweeps")
    ap.add_argument("--no-priced", action="store_true", help="skip the mean-R rows")
    return ap.parse_args()


def _names(raw: str, default: tuple[str, ...]) -> tuple[str, ...]:
    got = raw.replace(",", " ").split()
    return tuple(got) if got else default


def jobs_for(feeds: tuple[str, ...], intervals: tuple[str, ...]) -> list[tuple[str, str, str]]:
    """`(feed, interval, venue)` per cell.

    The 1d panel takes the fullest venue, ties alphabetically - a data-volume
    rule fixed before any result. The 15m panel takes the venue the **quotes**
    were measured on, because a spread read off another venue is another
    venue's spread and the same instrument runs 0.17 to 3.30 bps across them.
    """
    out: list[tuple[str, str, str]] = []
    for interval in intervals:
        if interval == "15m":
            out.extend(
                (feed, interval, venue)
                for feed, venue in S.COSTED.items()
                if not feeds or feed in feeds
            )
        else:
            out.extend((feed, interval, "") for feed in (feeds or S.FEEDS_1D))
    return out


#: One process per (feed, interval, **arm**) rather than per series.
#:
#: The 15 feed-intervals alone leave a 64-core box 49 cores idle, and the
#: expensive part is per arm: `real` carries both unit estimators, the whole
#: horizon sweep, the gain sweep, the plants and the priced rows, while each
#: null arm carries its own 16 draws. Splitting on the arm duplicates nothing,
#: because every job builds a disjoint set of rows.
ARM_JOBS = ("real", *(a for a in L.ARMS if a != "real"))


def arms_for(series: L.Series, draws: int, want: str) -> list[tuple[str, int, L.Series]]:
    """`(arm, draw, series)` for one arm: the real series, or its null draws.

    The GARCH fit is done once per series and shared across its draws: it is a
    coarse grid by design - the arm exists to supply clustering of about the
    right strength, not to be the best model of this series - so refitting per
    draw would cost the run and change nothing.
    """
    if want == "real":
        return [("real", 0, series)]
    make = L.ARMS[want]
    fitted = None
    if want == "garch-bars":
        fitted = L.fit_garch(np.diff(np.log(np.maximum(series.close, 1e-12))))
    plan: list[tuple[str, int, L.Series]] = []
    for draw in range(draws):
        rng = random.Random(S.seed_for(series.name, want, draw))
        built = make(series, rng, fitted) if want == "garch-bars" else make(series, rng)
        plan.append((want, draw, built))
    return plan


def rows_for(
    data: L.Series,
    *,
    head: dict,
    horizons: tuple[int, ...],
    spread: float,
    priced: bool,
    units: tuple[str, ...] = ("close",),
    gains: bool = False,
) -> list[dict]:
    """Every coverage row for one series: unit x horizon x side x arm.

    `units` and `gains` are narrower on the deeper null draws, and the reason
    is what each thing is for rather than a budget. **The second unit
    estimator is a check that the real reading does not depend on which sigma
    it was measured in**; a surrogate draw's reading does not need two units,
    so both run on the real arm and on each arm's first draw and `close` runs
    on the rest. **The gain sweep is a property of the step rule**, not of any
    market - `GAIN` is an absolute step, so the observations needed to reach a
    quantile grow with that quantile - so it runs once, on the real arm.
    Everything the verdict is scored against, including all five horizons,
    runs on every draw of every arm.
    """
    out: list[dict] = []
    for unit_name in units:
        estimator = S.UNITS[unit_name]
        sigma = estimator(data)
        spread_vol = (spread / 1e4) / np.maximum(sigma, 1e-24) if spread > 0.0 else None
        for horizon in horizons:
            for step_name, step in (("nonoverlap", None), ("dense", 1)):
                # The cap applies to the non-overlapping stream only, and to
                # every arm in it alike: the arms have to be scored on the same
                # anchors or the comparison is between two samples. The dense
                # stream is uncapped and carries the full-sample precision for
                # the fixed arms.
                exc = S.excursions(
                    data,
                    sigma,
                    horizon,
                    step=step,
                    cap=S.ONLINE_CAP if step is None else None,
                )
                if not len(exc.anchors):
                    continue
                if step_name == "dense":
                    # The online arms are never run on the overlapping stream:
                    # at step 1 the window at t+1 shares horizon-1 of its bars
                    # with the window at t, so an update before the next stop
                    # is a leak wearing causality's clothes.
                    readings = [
                        r
                        for side in (1, -1)
                        for r in S.fixed_arms(
                            exc, horizon, side=side, spread_vol=spread_vol
                        )
                    ]
                else:
                    readings = S.all_arms(exc, horizon, spread_vol=spread_vol)
                for reading in readings:
                    out.append(
                        {
                            **head,
                            "kind": "cover",
                            "unit": unit_name,
                            "horizon": horizon,
                            "step": step_name,
                            "arm_stop": reading.arm,
                            "side": reading.side,
                            "n": reading.n,
                            "hits": reading.hits,
                            "rate": round(reading.rate, 5),
                            "excess": round(reading.excess, 5),
                            "enough": reading.enough,
                            "calibrated": reading.calibrated,
                            "stop_median": round(reading.stop_median, 4),
                            "stop_first": round(reading.stop_first, 4),
                            "stop_last": round(reading.stop_last, 4),
                            "rate_late": round(reading.rate_late, 5),
                            "binds": round(reading.binds, 4),
                            "sd_block": round(reading.sd_block, 5),
                            "afford": reading.afford,
                            "clamped": exc.clamped(reading.side),
                        }
                    )
                if step_name != "nonoverlap":
                    continue
                for arm in ("quantile", "quantile-seated", "t-sqrt-h"):
                    ratio = S.side_ratio(readings, arm)
                    if ratio is not None:
                        out.append(
                            {
                                **head,
                                "kind": "ratio",
                                "unit": unit_name,
                                "horizon": horizon,
                                "arm_stop": arm,
                                "ratio": round(ratio, 5),
                            }
                        )
                if horizon == S.HORIZON and unit_name == "close":
                    if gains:
                        out.extend(
                            _gain_rows(exc, horizon, head=head, spread_vol=spread_vol)
                        )
                    if priced and spread_vol is not None:
                        out.extend(
                            _priced_rows(
                                data,
                                sigma,
                                exc,
                                horizon,
                                head=head,
                                spread_vol=spread_vol,
                                readings=readings,
                            )
                        )
    return out


def _gain_rows(
    exc: S.Excursions, horizon: int, *, head: dict, spread_vol: np.ndarray | None
) -> list[dict]:
    """The gain sweep, on the primary horizon only.

    `GAIN` is an **absolute** step in volatility units, so the observations
    needed to reach a quantile grow with that quantile - which is a property of
    the step rule and not of any market. Swept and reported as a grid on the
    mean, never as the best cell with its z.
    """
    out: list[dict] = []
    for gain in S.GAINS:
        for side in (1, -1):
            for name, seated in (("quantile", False), ("quantile-seated", True)):
                reading = S.online_arm(
                    exc,
                    horizon,
                    side=side,
                    name=name,
                    seated=seated,
                    gain=gain,
                    spread_vol=spread_vol,
                )
                out.append(
                    {
                        **head,
                        "kind": "gain",
                        "unit": "close",
                        "horizon": horizon,
                        "arm_stop": name,
                        "gain": gain,
                        "side": side,
                        "n": reading.n,
                        "rate": round(reading.rate, 5),
                        "excess": round(reading.excess, 5),
                        "rate_late": round(reading.rate_late, 5),
                        "stop_median": round(reading.stop_median, 4),
                        "stop_last": round(reading.stop_last, 4),
                    }
                )
    return out


def _priced_rows(
    data: L.Series,
    sigma: np.ndarray,
    exc: S.Excursions,
    horizon: int,
    *,
    head: dict,
    spread_vol: np.ndarray,
    readings: list[S.Reading],
) -> list[dict]:
    """Mean R per arm, **secondary**, and the same P&L in a common unit.

    Mean R across arms is a ranking of 1/width - `widestop.md` measured mean R
    at `m` times the stop to be the 1x mean over `m` in every row - so
    `per_sigma` is reported beside it and is the comparable number.

    Each arm is priced at its own **median** stop rather than at its path of
    stops, so the width is one number per arm and a mean R can be read against
    it. For the three fixed arms that is exact; for the online ones it is the
    arm's own realised width and is labelled as the median, because a
    path-varying stop makes `mean_r` a mixture over widths and
    `widestop.md`'s 1/m is then inside the statistic rather than beside it.
    """
    out: list[dict] = []
    for reading in readings:
        stops = np.full(len(exc.anchors), reading.stop_median)
        got = S.race(
            data,
            sigma,
            exc,
            stops,
            arm=reading.arm,
            side=reading.side,
            horizon=horizon,
            spread_vol=spread_vol,
            seed=S.seed_for(data.name, reading.arm, reading.side) % 2**31,
        )
        if got is None:
            continue
        out.append(
            {
                **head,
                "kind": "priced",
                "unit": "close",
                "horizon": horizon,
                "arm_stop": got.arm,
                "side": got.side,
                "n": got.n,
                "stopped": round(got.stopped, 5),
                "targeted": round(got.targeted, 5),
                "expired": round(got.expired, 5),
                "mean_r": round(got.mean_r, 5),
                "sd_r": round(got.sd_r, 5),
                "per_sigma": round(got.per_sigma, 6),
                "sd_per_sigma": round(got.sd_per_sigma, 6),
                "cost_share": round(got.cost_share, 5),
                "afford": reading.afford,
            }
        )
    return out


def plant_rows(series: L.Series, *, head: dict, horizon: int) -> list[dict]:
    """The power sweeps, with each plant's own zero control.

    A plant whose zero cell reads an effect is rejected and its question is
    left *untested* rather than null - `level-bounce.md`'s pure-order plant
    failed exactly that way, reading -0.180 at z -4.76 with nothing planted.
    """
    out: list[dict] = []
    for name, (make, strengths) in S.PLANTS.items():
        for strength in strengths:
            planted = make(series, strength)
            sigma = S.sigma_close(planted)
            exc = S.excursions(planted, sigma, horizon)
            if not len(exc.anchors):
                continue
            readings = S.all_arms(exc, horizon, spread_vol=None)
            ratio = S.side_ratio(readings, "quantile-seated")
            for reading in readings:
                out.append(
                    {
                        **head,
                        "kind": "plant",
                        "plant": name,
                        "strength": strength,
                        "unit": "close",
                        "horizon": horizon,
                        "arm_stop": reading.arm,
                        "side": reading.side,
                        "n": reading.n,
                        "rate": round(reading.rate, 5),
                        "excess": round(reading.excess, 5),
                        "stop_median": round(reading.stop_median, 4),
                        "ratio": None if ratio is None else round(ratio, 5),
                    }
                )
    return out


def one(job: tuple[str, str, str, str, str, int, bool, bool, tuple[int, ...]]) -> list[dict]:
    feed, interval, venue, want, store, draws, plants, priced, horizons = job
    con = sqlite3.connect(store, uri=True)
    try:
        series = S.load(con, feed, interval, venue or None)
        if series is None:
            return []
        spread = S.spread_bps(con, feed, series.venue) if feed in S.COSTED else 0.0
    finally:
        con.close()
    if feed in S.COSTED and S.COSTED[feed] != series.venue:
        spread = 0.0
    out: list[dict] = []
    for arm, draw, data in arms_for(series, draws, want):
        head = {
            "feed": feed,
            "venue": series.venue,
            "live_venue": series.venue in S.LIVE_VENUES,
            "interval": interval,
            "bars": len(series.close),
            "days": round(series.days, 1),
            "arm": arm,
            "draw": draw,
            "spread_bps": round(spread, 4),
        }
        # The 16 draws exist to bound the statistic the verdict is scored
        # against, which is at the primary horizon; the horizon sweep's job is
        # to show the *real* reading does not depend on H. So every arm's
        # first draw runs the whole sweep and both units, and the deeper draws
        # run the primary horizon on the primary unit.
        out.extend(
            rows_for(
                data,
                head=head,
                horizons=horizons if draw == 0 else (S.HORIZON,),
                spread=spread,
                priced=priced and arm == "real",
                units=("close", "range") if draw == 0 else ("close",),
                gains=arm == "real",
            )
        )
    if plants and want == "real":
        head = {
            "feed": feed,
            "venue": series.venue,
            "live_venue": series.venue in S.LIVE_VENUES,
            "interval": interval,
            "bars": len(series.close),
            "days": round(series.days, 1),
            "arm": "plant",
            "draw": 0,
            "spread_bps": round(spread, 4),
        }
        out.extend(plant_rows(series, head=head, horizon=S.HORIZON))
    return out


def main() -> None:
    args = parse()
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "stop_coverage.jsonl"
    feeds = _names(args.feeds, ())
    intervals = _names(args.intervals, ("1d", "15m"))
    horizons = tuple(int(x) for x in _names(args.horizons, ())) or S.HORIZONS
    jobs = [
        (feed, interval, venue, want, args.store, args.draws, not args.no_plants,
         not args.no_priced, horizons)
        for feed, interval, venue in jobs_for(feeds, intervals)
        for want in ARM_JOBS
    ]
    print(
        f"{len(jobs)} jobs ({len(jobs) // len(ARM_JOBS)} feed-intervals x {len(ARM_JOBS)} "
        f"arms) over {sorted(set(intervals))}, {args.draws} draws per null arm, horizons "
        f"{list(horizons)}, {args.workers} workers -> {target}",
        file=sys.stderr,
    )
    started = time.time()
    done = 0
    with target.open("w") as fh, ProcessPoolExecutor(max_workers=args.workers) as pool:
        for rows in pool.map(one, jobs):
            done += 1
            for row in rows:
                fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(f"{done}/{len(jobs)} {time.time() - started:.0f}s", file=sys.stderr)
    print(f"wrote {target} in {time.time() - started:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
