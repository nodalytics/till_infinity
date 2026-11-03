"""Run the level-shield panel: every feed, every interval, every null arm.

One process per (feed, interval), because the expensive part is replaying the
level book bar by bar and that is per series. Output is one JSON object per
line so a partial run is still readable - a sweep that has to finish before it
says anything is a sweep nobody runs twice.

Pre-registered before the run, so the report cannot be a selection:

* the cells are feed x interval x distance x side, and the null arms are
  `garch-bars`, `walk-geometry` and `bar-shuffle` with four draws each;
* the headline statistic is the **mirror gap** - blocked side against clear
  side within the same anchor, skew-corrected - because `docs/magnet.md` §5
  showed that the whole of its own -4.6 point level deficit was the day mix,
  and its day-fixed control took the effect to -0.009 [-0.062, +0.038]. The
  dose slope and the presence gap are reported beside it and are weaker;
* a finding needs the real slope outside the range of the hardest null arm's
  draws, the sign consistent across intervals, and survival of
  Benjamini-Hochberg over every cell;
* the direction is pre-stated: a barrier means a **negative** slope (more
  levels in the path, lower reach rate) on both sides. A slope of one sign up
  and the other sign down is not a barrier, it is a drift or a book-geometry
  effect, and the null arms are what tell those apart.
"""

import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import research.ideas.level_shield as L
import research.ideas.level_shield_agg as A

DRAWS = int(os.environ.get("SHIELD_DRAWS", "4"))
OUT = os.environ.get("SHIELD_OUT") or "shield.jsonl"
WORKERS = int(os.environ.get("SHIELD_WORKERS") or 7)


def _names(var: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """A space- or comma-separated env list, or the default."""
    raw = (os.environ.get(var) or "").replace(",", " ").split()
    return tuple(raw) if raw else default


def one(job: tuple[str, str]) -> list[dict]:
    feed, interval = job
    con = sqlite3.connect(L.STORE, uri=True)
    try:
        series = L.load(con, feed, interval)
    finally:
        con.close()
    if series is None:
        return []
    settings = L.SETTINGS[interval]
    out: list[dict] = []
    rets = np.diff(np.log(np.maximum(series.close, 1e-12)))
    fitted = L.fit_garch(rets)

    plan: list[tuple[str, int, L.Series]] = [("real", 0, series)]
    import random as _random

    for arm, make in L.ARMS.items():
        if make is None:
            continue
        for draw in range(DRAWS):
            rng = _random.Random(hash((feed, interval, arm, draw)) & 0xFFFFFFFF)
            built = (
                make(series, rng, fitted) if arm == "garch-bars" else make(series, rng)
            )
            plan.append((arm, draw, built))

    for arm, draw, data in plan:
        walked = L.measure(data, settings)
        rows = walked.rows
        head = {
            "feed": feed,
            "venue": series.venue,
            "interval": interval,
            "bars": len(series.close),
            "days": round(series.days, 1),
            "arm": arm,
            "draw": draw,
        }
        for di, dist in enumerate(L.DISTANCES):
            for side in (1, -1):
                mask = (rows.dist == di) & (rows.side == side)
                dose = A.dose_for(rows, mask)
                pres = A.within_strata(rows, mask)
                pooled = A.gap_for(rows, mask, strata=False)
                out.append(
                    {
                        **head,
                        "kind": "cell",
                        "distance": dist,
                        "side": side,
                        "dose_n": list(dose.n) if dose else None,
                        "dose_rate": [None if np.isnan(x) else round(x, 5) for x in dose.rate]
                        if dose
                        else None,
                        "dose_slope": round(dose.slope, 6) if dose else None,
                        "dose_sd": round(dose.sd, 6) if dose else None,
                        "dose_monotone": dose.monotone if dose else None,
                        "gap_strata": round(pres.gap, 6) if pres else None,
                        "gap_strata_sd": round(pres.sd, 6) if pres else None,
                        "gap_pooled": round(pooled.gap, 6) if pooled else None,
                        "n_clear": pres.n_clear if pres else None,
                        "n_shield": pres.n_shield if pres else None,
                    }
                )
            got = A.mirror_for(walked, di)
            out.append(
                {
                    **head,
                    "kind": "mirror",
                    "distance": dist,
                    "n": got.n if got else None,
                    "n_concordant": got.n_concordant if got else None,
                    "p_blocked": round(got.p_blocked, 5) if got else None,
                    "p_clear": round(got.p_clear, 5) if got else None,
                    "raw": round(got.raw, 6) if got else None,
                    "skew": round(got.skew, 6) if got else None,
                    "gap": round(got.gap, 6) if got else None,
                    "sd": round(got.sd, 6) if got else None,
                }
            )
        if arm == "real" or draw == 0:
            for ti in range(len(L.DISTANCES)):
                for si in range(len(L.DISTANCES)):
                    if ti == si:
                        continue
                    for side in (1, -1):
                        got = L.race(walked, target=ti, stop=si, side=side)
                        if got is None:
                            continue
                        out.append(
                            {
                                **head,
                                "kind": "race",
                                "target": got.target,
                                "stop": got.stop,
                                "side": side,
                                "n": got.n,
                                "won": round(got.won, 5),
                                "expected": round(got.expected, 5),
                                "edge_r": round(got.edge_r, 5),
                                "sd": round(got.sd, 5),
                                "ties": round(got.ties, 5),
                            }
                        )
    return out


def main() -> None:
    feeds = _names("SHIELD_FEEDS", L.FEEDS)
    intervals = _names("SHIELD_INTERVALS", tuple(L.SETTINGS))
    unknown = [i for i in intervals if i not in L.SETTINGS]
    if unknown:
        raise SystemExit(
            f"SHIELD_INTERVALS names {unknown}, which have no horizon in SETTINGS. "
            f"Known: {', '.join(L.SETTINGS)}."
        )
    jobs = [(f, i) for i in intervals for f in feeds]
    print(
        f"{len(jobs)} jobs: {len(feeds)} feeds x {len(intervals)} intervals, "
        f"{DRAWS} draws per null arm, {L.ERAS} era(s) x {L.STRATA} compression "
        f"quintiles, {WORKERS} workers -> {OUT}",
        file=sys.stderr,
    )
    started = time.time()
    done = 0
    with open(OUT, "w") as fh, ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for rows in pool.map(one, jobs):
            done += 1
            for row in rows:
                fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(f"{done}/{len(jobs)} {time.time() - started:.0f}s", file=sys.stderr)
    print(f"wrote {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
