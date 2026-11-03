"""Does anchoring a stop at a level's floor beat a fixed volatility stop?

One invocation, three parts, one output directory. `stop_anchor_book.py` holds
the causal cluster book, the arms and the race; this file is the panel, the
signal-conditioned run, the power sweep and the tables.

    uv run python research/ideas/stop_anchor.py --all --draws 4 --out .data/out/stop_anchor

**Single process throughout.** No pool anywhere, so it runs beside other work
on one core. Measured at `--draws 4`: the geometry panel is about **45 minutes**
(14 feed-intervals times 13 series - one real plus four draws of each of three
surrogates - with the per-bar clustering dominating), `--catalogue` about **8
minutes** over 54 engine runs, and `--power` about **25 minutes** over 24
planted series, each of which maintains its own causal book bar by bar.
**About 80 minutes in all.**

Nothing here is parallel, so a larger box does not make it faster - it makes a
higher `--draws` affordable, which is what the criterion wants: a cell passes
by exceeding its **hardest** surrogate draw, and that bar rises with the draw
count, so 12 draws is the weakest form of this test.

## The three parts, and which one answers the question

**`--geometry`** is the one that decides. Entry-agnostic: every bar past
warm-up, both sides, no signal - 8 feeds of 19.2-19.9 year daily history and 6
feeds of 15-minute bars. **Gross**, because nothing is priced; only six feeds
have a measurable spread and none is invented for the rest. A stop rule is not
a function of the entry signal, so dropping the signal costs nothing the
question needs and buys four orders of magnitude of sample over the 75 trades
the recorded rule gives.

**`--catalogue`** is the signal-conditioned run, on `smc_bos_c_L50|M15|N20|time`
over the recorded catalogue, **net of the modelled spread**. It settles the one
thing the geometry panel cannot - `cost_px / risk` per arm, which the stop sets
and no exit rule can repair - and it settles nothing about edge: 75 trades at a
per-trade sd of 2.4R is a standard error of 0.20-0.95R
(`research/docs/smc-bos-reconcile.md`). The `vol` arm's reading is printed
before any arm is compared to it, and the reconciled `-0.533R` on `n` 75 is
reproduced first as the machinery check
(`reproduce-the-baseline-before-an-increment`).

**`--power`** plants the effect. A walk with this market's bar geometry whose
own cluster book reflects it at the **floor** - which is the claim, not at the
centre, which is what `level_shield_power.plant_book` plants - swept over
strength, so the null below arrives with the strength at which this test goes
blind.

## The prior, written down before the run

Poor. `research/docs/level-shield.md` measured the parent claim three weeks of
work ago and it is null: of 210 mirror cells asking whether a level in the path
suppresses the move, **1** beat its hardest null arm at z > +2 where chance
gives about 2, and real sat *below* the hardest null in **188**. "The level has
to break first" is the same mechanism read at a shorter range. The honest
expectation is a null and a clean null is the result this desk values.

## The prediction, fixed before the run

A barrier means the floor-anchored arm is **stopped less often than `matched`
at the same width**, on **both** sides, with the sign stable across intervals.
One sign long and the other short is a drift or a book-geometry effect, not a
barrier - `level-shield.md`'s dose arm died on exactly that. A finding needs the
real contrast outside the hardest surrogate arm's draws and survival of
Benjamini-Hochberg over every cell.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import random
import sqlite3
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import level_shield as L  # noqa: E402
import stop_anchor_book as B  # noqa: E402
from till_infinity.domain.models import Intent  # noqa: E402

#: Where the tables go, relative to the repository unless `STOP_OUT` says
#: otherwise. Relative, so nothing here names a machine.
OUT = os.environ.get("STOP_OUT", ".data/out/stop_anchor")

#: Feeds for the geometry panel, per interval. The 1d list is every feed whose
#: daily history spans more than seventeen years, which is where the power is;
#: the 15m list is the six with a measurable spread, so the two halves of this
#: study are on the same instruments. Fixed before any result was seen.
PANEL = {
    "1d": ("gold", "eurusd", "gbpusd", "usdjpy", "usdchf", "usdcad", "audusd", "nzdusd"),
    "15m": ("eurusd", "gbpusd", "gold", "btc", "us100", "spx500"),
}

#: Surrogate draws per arm. Four, matching `level_shield.py`, which is enough
#: for a hardest-arm comparison and not enough for a quantile.
DRAWS = 4

#: Block bootstrap draws, and the mean block in multiples of the horizon.
#: Blocks of bars and not of trades, because anchors at consecutive bars share
#: almost all of their forward window - `overlapping-windows-inflate-
#: permutation-nulls` is the recorded failure, where a level finding at p 0.015
#: was anchor overlap.
BOOT = 400
BLOCK = 2.0

#: The contrasts the verdict is read off, as `(arm, against, what it decides)`.
#: Fixed here rather than chosen from the output.
CONTRASTS = (
    ("beyond-floor+0.25", "beyond-matched+0.25", "the anchor against its own width"),
    ("beyond-floor+0.25", "beyond-centre+0.25", "the floor against the centre"),
    ("beyond-floor+0.25", "beyond-mirror+0.25", "the near side against the far side"),
    ("beyond-floor+0.25", "vol-2", "the level book against the incumbent"),
    ("near-floor+0.25", "near-matched+0.25", "the anchor against its own width, nearest level"),
    ("near-floor+0.25", "near-centre+0.25", "the floor against the centre, nearest level"),
)

#: Minimum anchors in a width stratum before it contributes to a standardised
#: contrast. Pooled first, then guarded: `pool-events-before-a-per-feed-guard`
#: records a min-events guard dropping 141 of 146 feeds and turning 0.9 sigma
#: into 4.8.
MIN_CELL = 50


def metrics(r: np.ndarray, se: float) -> dict[str, float]:
    """What an arm is judged on, and what it is only described by.

    **A win rate decides nothing here and a fall in it is not a cost.** A wider
    stop lowers the win rate and raises the payoff, and the two move together
    by arithmetic: a rule at 50% on 1:1 and one at 25% on 4:1 are the same
    expectancy. So `mean_r` with its day-block interval and `pf` are the
    verdict - and they are the same event, since `mean_r > 0` is `pf > 1` - and
    `win`, `mean_win` and `mean_loss` are carried to show the shape of the
    trade-off without being read as one.

    **What the trade-off does cost is sample, and that is the binding
    constraint here.** The trades needed for a given confidence scale with the
    variance, so an arm that widens the payoff distribution needs *more*
    evidence than the incumbent, not the same amount. `n_needed` is the sample
    at which **this arm's own** mean would be two of **its own** standard
    errors from zero, so two arms with different sd are never compared as
    though their means were equally well measured.

    `n_eff` is `(sd / se)**2` against the block-bootstrap se: the independent
    observations the overlap between forward windows actually leaves, which on
    a 20-bar horizon is a small fraction of the anchor count.

    `profit_factor` is `node.metrics`' - None where there are no losses rather
    than an infinity that would top any ranking.
    """
    from till_infinity.node.metrics import profit_factor

    # Masked in numpy and converted once. Element-wise `np.isfinite` in a
    # comprehension over 90 arms times 4,000 anchors is most of a second a
    # series, which is most of this panel's runtime.
    found = np.asarray(r, dtype=float)
    found = found[np.isfinite(found)]
    n = int(found.size)
    if not n:
        return {}
    mean = float(found.mean())
    sd = float(found.std(ddof=1)) if n > 1 else 0.0
    wins = found[found > 0.0]
    losses = found[found < 0.0]
    pf = profit_factor(found.tolist())
    return {
        "n": n,
        "mean_r": mean,
        "sd": sd,
        "se_r": se,
        "sharpe": mean / sd if sd > 0.0 else 0.0,
        "pf": float(pf) if pf is not None else float("nan"),
        "win": wins.size / n,
        "mean_win": float(wins.mean()) if wins.size else 0.0,
        "mean_loss": float(losses.mean()) if losses.size else 0.0,
        "n_eff": (sd / se) ** 2 if se > 0.0 and sd > 0.0 else float("nan"),
        "n_needed": (2.0 * sd / abs(mean)) ** 2 if mean else float("inf"),
    }


def dsr(r: np.ndarray, trials: list[float]) -> float:
    """`node.metrics.deflated_sharpe` over the arms that were actually tried.

    The trial set is every arm on this cell, both sides, which is 90-odd - so
    the deflation is against the expected maximum of 90 nothings and not
    against zero. Reported rather than a raw Sharpe because this study is a
    grid: `multiplicity, for any search over cells` is the skill's rule, and on
    this desk 18 of 43 nominally profitable instruments survived no deflation
    at all while five survived as losers.

    NaN where the series is too non-normal for the PSR approximation, which
    `probabilistic_sharpe` raises on rather than casting a complex number -
    tight-stop arms here reach a skew that does exactly that.
    """
    from till_infinity.node.metrics import deflated_sharpe

    values = [float(v) for v in r if np.isfinite(v)]
    if len(values) < 3 or len(trials) < 2:
        return float("nan")
    try:
        return float(deflated_sharpe(values, trials))
    except (ValueError, ZeroDivisionError):
        return float("nan")


class Tee:
    """Write to stdout and to a file at once, so one run leaves a report."""

    def __init__(self, handle: Any) -> None:
        self._handle = handle

    def write(self, text: str) -> int:
        self._handle.write(text)
        return sys.__stdout__.write(text)

    def flush(self) -> None:
        self._handle.flush()
        sys.__stdout__.flush()


# ──────────────────────────── the geometry panel ────────────────────────────


def one_series(series: L.Series, interval: str, arms: list[B.Arm], seed: int) -> dict[str, Any]:
    """Every arm raced on one series, both sides, as flat per-anchor arrays.

    One book replay for all arms, which is what makes the arms comparable: the
    clustering, the volatility unit, the anchor set and the forward window are
    one object, so a difference between two arms is a difference between two
    stop distances and cannot be anything else.
    """
    cfg = L.SETTINGS[interval]
    horizon, span = int(cfg["horizon"]), int(cfg["unit_span"])
    books = B.book_path(series.high, series.low, series.close, unit_span=span, beyond=B.MIN_VOL)
    unit = books["near"].unit
    out: dict[str, Any] = {"horizon": horizon, "sides": {}}
    for side in (1, -1):
        stops: dict[str, np.ndarray] = {}
        for arm in arms:
            if arm.kind == "matched":
                continue
            stops[arm.name] = B.distances(books, series.close, unit, arm, side)
        ok = B.usable(stops, unit, horizon)
        # The permuted-distance placebo is built *after* the anchor set is
        # fixed, from the floor arm it is matched to, so it cannot change which
        # anchors every other arm is scored on. Permuted in volatility units,
        # never in price: over nineteen years a price distance drawn from 2024
        # and applied to 2006 would differ from `floor` in the level of
        # volatility as well as in the pairing.
        rng = random.Random(seed * 7_919 + side)
        for arm in arms:
            if arm.kind != "matched":
                continue
            source = stops[f"{arm.pick}-floor+{arm.buffer:g}"]
            with np.errstate(invalid="ignore"):
                vol = source / unit
            stops[arm.name] = B.permute(vol, ok, rng) * unit
        rows: dict[str, dict[str, np.ndarray]] = {}
        for name, distance in stops.items():
            stop_px = series.close - side * distance
            hit, r = B.race(series.high, series.low, series.close, stop_px, side, horizon)
            rows[name] = {
                "hit": hit[ok],
                "r": r[ok],
                "stratum": B.strata(stop_px, series.close, unit, side)[ok],
                "vol": (distance / unit)[ok],
            }
        out["sides"][side] = {
            "n": int(ok.sum()),
            "kept": float(ok.mean()),
            "rows": rows,
            "members": float(np.nanmedian(books["near"].below_members[ok])) if ok.any() else 0.0,
            "span_vol": _span_vol(books["near"], unit, ok, side),
            "formed_agrees": _formed_agrees(books["beyond"], ok, side),
        }
    return out


def _span_vol(book: B.Book, unit: np.ndarray, ok: np.ndarray, side: int) -> float:
    """The nearest group's span in volatility units: floor minus centre.

    **This is the whole size of the effect being argued about.** The anchor can
    only move a stop by the distance between a group's extreme and its weighted
    mean, so if that is a few hundredths of a volatility unit against a stop of
    two, no choice of anchor can matter and the rest of the study is a
    formality.
    """
    low = book.below_low if side > 0 else book.above_high
    centre = book.below_centre if side > 0 else book.above_centre
    with np.errstate(invalid="ignore"):
        gap = np.abs(centre - low) / unit
    found = gap[ok]
    return float(np.nanmedian(found)) if found.size else float("nan")


def _formed_agrees(book: B.Book, ok: np.ndarray, side: int) -> float:
    """How often the level's formed side names the trade's own extreme.

    `Anchor.SIDED` reads `levels.Level.side` - the pivot side that *formed* the
    level - and the stop claim is written in the **trade's** side. Where they
    disagree, `Anchor.SIDED` hands a long the group's *ceiling* and the stop
    lands inside the cluster, which is the defect the anchor exists to prevent.
    """
    formed = book.below_side if side > 0 else book.above_side
    want = -1 if side > 0 else 1
    found = formed[ok]
    return float((found == want).mean()) if found.size else float("nan")


def blocks(n: int, horizon: int, draws: int, seed: int) -> np.ndarray:
    """Stationary block-bootstrap indices, `(draws, n)`.

    One index matrix per cell, **shared by every arm**, so a contrast is
    resampled as a paired difference. Resampling the arms independently would
    widen every interval by the variance the pairing removes, which is most of
    it here: the arms share the anchor, the bar path and the forward window.
    """
    rng = np.random.default_rng(seed)
    mean = max(2.0, BLOCK * horizon)
    out = np.empty((draws, n), dtype=np.int64)
    for d in range(draws):
        picked = np.empty(n, dtype=np.int64)
        at = 0
        while at < n:
            start = int(rng.integers(n))
            length = min(n - at, 1 + int(rng.geometric(1.0 / mean)))
            picked[at : at + length] = (start + np.arange(length)) % n
            at += length
        out[d] = picked
    return out


def standardised(
    a: dict[str, np.ndarray], b: dict[str, np.ndarray], key: str
) -> tuple[float, float]:
    """`(a - b, overlap)` on `key`, direct-standardised on the stop's own width.

    Each arm's mean is taken within quarter-unit bins of its own distance and
    the differences are recombined at `a`'s bin weights. Width is the confound
    the whole study is about - `a-return-rate-is-geometry`, where a
    distance-matched placebo reproduced an 82% return rate on every class - and
    standardising on it is the direct control. The gap between this number and
    the pooled difference is how much of the pooled difference is geometry.

    `overlap` is the share of `a`'s anchors that fell in a bin **both** arms
    populate. Reported because a fixed-distance arm occupies one bin: against
    `vol-2` the overlap is a few per cent, and a standardised contrast on a few
    per cent of the weight is a statement about those anchors and not about the
    arm. Without the share printed beside it, that number reads as a matched
    comparison and is not one.
    """
    top = 0.0
    weight = 0.0
    for stratum in range(len(B.EDGES) + 1):
        mask_a = a["stratum"] == stratum
        mask_b = b["stratum"] == stratum
        if mask_a.sum() < MIN_CELL or mask_b.sum() < MIN_CELL:
            continue
        top += mask_a.sum() * (a[key][mask_a].mean() - b[key][mask_b].mean())
        weight += mask_a.sum()
    total = len(a["stratum"])
    return (top / weight if weight else float("nan"), weight / total if total else 0.0)


def summarise(cell: dict[str, Any], seed: int) -> dict[str, Any]:
    """Per-arm means and the pre-registered contrasts, with paired intervals."""
    out: dict[str, Any] = {"arms": {}, "contrasts": {}}
    for side, found in cell["sides"].items():
        rows = found["rows"]
        if not found["n"]:
            continue
        idx = blocks(found["n"], cell["horizon"], BOOT, seed * 31 + (side > 0))
        # Bootstrapped only where the number is read: a gather of `BOOT` by `n`
        # per arm over 44 arms is most of this study's runtime, and the arms
        # outside `CONTRASTS` are in the table for their width and stop-out
        # rate, which are exact counts and need no interval.
        wanted = {a for a, _b, _w in CONTRASTS} | {b for _a, b, _w in CONTRASTS}
        for name, row in rows.items():
            blocked = name in wanted
            se = (
                float(row["r"][idx].mean(axis=1).std(ddof=1))
                if blocked
                else float(row["r"].std(ddof=1)) / math.sqrt(max(1, found["n"]))
            )
            got = metrics(row["r"], se) | {
                "p_stop": float(row["hit"].mean()),
                "med_vol": float(np.median(row["vol"])),
                "blocked": blocked,
            }
            if not blocked:
                # `n_eff` is only meaningful against a block-bootstrap se.
                # Computed off `sd / sqrt(n)` it returns `n` by algebra, which
                # would read as "the overlap costs nothing" on every arm that
                # was not resampled.
                got["n_eff"] = float("nan")
            out["arms"][(side, name)] = got
        # The trial set is every arm on this side of this cell, which is what
        # was searched. Computed after the arms so no arm is deflated against a
        # partial grid.
        trials = [v["sharpe"] for (s, _n), v in out["arms"].items() if s == side]
        for name in wanted & set(rows):
            out["arms"][(side, name)]["dsr"] = dsr(rows[name]["r"], trials)
        for arm, against, _why in CONTRASTS:
            if arm not in rows or against not in rows:
                continue
            a, b = rows[arm], rows[against]
            draws_r = (a["r"][idx] - b["r"][idx]).mean(axis=1)
            draws_p = (a["hit"][idx].astype(float) - b["hit"][idx].astype(float)).mean(axis=1)
            d_r_std, overlap = standardised(a, b, "r")
            d_p_std, _ = standardised(a, b, "hit")
            out["contrasts"][(side, arm, against)] = {
                "d_r": float((a["r"] - b["r"]).mean()),
                "se_r": float(draws_r.std(ddof=1)),
                "d_p": float(a["hit"].mean() - b["hit"].mean()),
                "se_p": float(draws_p.std(ddof=1)),
                "d_r_std": d_r_std,
                "d_p_std": d_p_std,
                "overlap": overlap,
                "d_vol": float((a["vol"] - b["vol"]).mean()),
            }
        out[("mechanics", side)] = {
            "kept": found["kept"],
            "members": found["members"],
            "span_vol": found["span_vol"],
            "formed_agrees": found["formed_agrees"],
        }
    return out


def geometry(intervals: tuple[str, ...], draws: int, out_dir: Path) -> None:
    """The entry-agnostic panel: real against three surrogates, per instrument."""
    arms = B.arms()
    con = sqlite3.connect(L.STORE, uri=True)
    report: dict[str, Any] = {}
    cells: list[tuple[str, int, str, float, float, bool, bool]] = []
    try:
        for interval in intervals:
            for feed in PANEL[interval]:
                series = L.load(con, feed, interval)
                if series is None:
                    print(f"  {feed}.{interval}: no series with 500 bars - skipped")
                    continue
                key = f"{feed}.{interval}"
                print(f"\n=== {key} ({series.venue}, {len(series.close)} bars, "
                      f"{series.days / 365.25:.2f}y) ===")
                real = summarise(one_series(series, interval, arms, seed=1), seed=1)
                report[key] = {"real": _flat(real), "venue": series.venue, "bars": len(series.close)}
                _print_arms(real)
                nulls: dict[str, list[dict[str, Any]]] = defaultdict(list)
                fitted = None
                for name, make in (
                    ("garch-bars", L.garch_bars),
                    ("walk-geometry", L.walk_geometry),
                    ("bar-shuffle", L.bar_shuffle),
                ):
                    for d in range(draws):
                        rng = random.Random(hash((key, name, d)) & 0xFFFFFFFF)
                        if name == "garch-bars":
                            if fitted is None:
                                rets = np.diff(np.log(np.maximum(series.close, 1e-12)))
                                fitted = L.fit_garch(rets)
                            made = make(series, rng, fitted)
                        else:
                            made = make(series, rng)
                        got = summarise(one_series(made, interval, arms, seed=2 + d), seed=2 + d)
                        nulls[name].append(_flat(got))
                report[key]["nulls"] = dict(nulls)
                cells.extend(_print_contrasts(real, dict(nulls), key))
    finally:
        con.close()
    _bh(cells)
    (out_dir / "geometry.json").write_text(json.dumps(report, indent=1, default=str))


def _bh(cells: list[tuple[str, int, str, float, float, bool, bool]]) -> None:
    """Benjamini-Hochberg over every cell, on both statistics.

    **The count is the whole point.** This grid is 14 feed-intervals times two
    sides times the pre-registered contrasts, and picking the best cell of a
    hundred gives a winner every time: on this desk 18 of 43 nominally
    profitable instruments survived no deflation while five survived as losers.
    One-sided in the direction fixed before the run, so a cell that beats its
    null the *wrong* way cannot be counted as evidence.
    """
    from till_infinity.node.metrics import phi
    from till_infinity.node.multiple import benjamini_hochberg

    if not cells:
        return
    print("\n=== Benjamini-Hochberg over every cell, one-sided in the fixed direction ===")
    print("  **Read the counts, not the q values.** Each z's sd comes from 12 surrogate")
    print("  draws, so every p here is far too small and BH inherits that; what the table")
    print("  settles is whether the number of cells pointing the right way exceeds chance,")
    print("  and the `exceeds its own hardest draw` count above it is the real criterion.")
    for label, at, beats in (
        ("dR|width above its null", 3, 5),
        ("dP(stop)|width below its null", 4, 6),
    ):
        rows = [c for c in cells if np.isfinite(c[at])]
        if not rows:
            continue
        won = sum(1 for c in rows if c[beats])
        print(
            f"  {label}: **{won} of {len(rows)} cells exceed their own hardest "
            f"surrogate draw**, where 12 draws give about {len(rows) / 13:.1f} by chance"
        )
        p = [1.0 - phi(c[at]) for c in rows]
        q = benjamini_hochberg(p)
        kept = [(c, qi) for c, qi in zip(rows, q, strict=True) if qi <= 0.10]
        nominal = sum(1 for c in rows if c[at] > 1.645)
        print(
            f"  {label}: {len(rows)} cells, {nominal} nominal at z > +1.645 "
            f"(chance gives {0.05 * len(rows):.1f}), {len(kept)} at BH q 0.10"
        )
        for cell, qi in sorted(kept, key=lambda row: row[1])[:12]:
            feed, side, name = cell[0], cell[1], cell[2]
            print(
                f"    {feed:<14} side {side:+d}  {name:<46} q {qi:.4f}  "
                f"beats its hardest draw: {cell[beats]}"
            )


def _flat(found: dict[str, Any]) -> dict[str, Any]:
    """Tuple keys as strings, so the result is JSON and a reader can grep it."""
    return {
        "arms": {f"{s:+d}|{n}": v for (s, n), v in found["arms"].items()},
        "contrasts": {f"{s:+d}|{a}|{b}": v for (s, a, b), v in found["contrasts"].items()},
        "mechanics": {f"{k[1]:+d}": v for k, v in found.items() if isinstance(k, tuple)},
    }


def _print_arms(found: dict[str, Any]) -> None:
    print(
        f"  {'arm':<20} {'side':>4} {'n':>6} {'width(v)':>9} {'P(stop)':>8} "
        f"{'R/anchor':>9} {'se':>7} {'sd':>6} {'PF':>6} {'DSR':>6} "
        f"{'win':>5} {'mWin':>7} {'mLoss':>7} {'nEff':>7} {'nNeed':>8}"
    )
    print("    verdict columns are R/anchor, se, PF and DSR; win/mWin/mLoss describe only")
    for (side, name), row in found["arms"].items():
        if not row:
            continue
        print(
            f"  {name:<20} {side:>+4} {row['n']:>6} {row['med_vol']:>9.3f} "
            f"{row['p_stop']:>8.3f} {row['mean_r']:>+9.4f} {row['se_r']:>7.4f} "
            f"{row['sd']:>6.3f} {row['pf']:>6.3f} {row.get('dsr', float('nan')):>6.3f} "
            f"{row['win']:>5.3f} {row['mean_win']:>+7.3f} {row['mean_loss']:>+7.3f} "
            f"{row['n_eff']:>7.0f} {row['n_needed']:>8.0f}"
        )
    for key, row in found.items():
        if not isinstance(key, tuple):
            continue
        print(
            f"  mechanics side {key[1]:+d}: anchors kept {row['kept']:.3f}, "
            f"group touches {row['members']:.1f}, floor-to-centre {row['span_vol']:.4f} vol, "
            f"formed side agrees {row['formed_agrees']:.3f}"
        )


def _print_contrasts(
    real: dict[str, Any], nulls: dict[str, list[dict[str, Any]]], key: str
) -> list[tuple[str, int, str, float, float, bool, bool]]:
    print("\n  contrasts, real against the hardest surrogate arm (paired day-block se)")
    print("  a finding needs dR|width above its hardest null AND dP|width below its own,")
    print("  on BOTH sides, with the sign stable across intervals. Fixed before the run.")
    print("  `hard` is the criterion: it is the single hardest of the surrogate draws, and")
    print("  `z` is indicative only - its sd comes from 12 draws, so it is far too")
    print("  confident to carry a verdict and is printed to rank cells, not to pass them.")
    print(
        f"  {'contrast':<44} {'side':>4} {'dR':>8} {'se':>6} {'dR|width':>9} "
        f"{'hard':>9} {'z':>6} {'dP|width':>9} {'hard':>9} {'z':>6} {'ovl':>5}"
    )
    out: list[tuple[str, int, str, float, float, bool, bool]] = []
    for (side, arm, against), row in real["contrasts"].items():
        tag = f"{side:+d}|{arm}|{against}"
        hard_r, z_r = _against(nulls, tag, "d_r_std", row["d_r_std"], sign=+1)
        # A barrier means the floor arm is stopped **less** often, so the
        # hardest null on dP(stop) is the most *negative* draw, not the largest.
        # Taking the max on both would score the stop-out claim against the
        # arm that agrees with it least, which is how a null gets passed.
        hard_p, z_p = _against(nulls, tag, "d_p_std", row["d_p_std"], sign=-1)
        print(
            f"  {arm[:20]:<20}-{against[:22]:<22} {side:>+4} {row['d_r']:>+8.4f} "
            f"{row['se_r']:>6.4f} {row['d_r_std']:>+9.4f} {hard_r:>+9.4f} {z_r:>+6.2f} "
            f"{row['d_p_std']:>+9.4f} {hard_p:>+9.4f} {z_p:>+6.2f} {row['overlap']:>5.2f}"
        )
        out.append(
            (
                key,
                side,
                f"{arm}-{against}",
                z_r,
                z_p,
                row["d_r_std"] > hard_r,
                row["d_p_std"] < hard_p,
            )
        )
    return out


def _against(
    nulls: dict[str, list[dict[str, Any]]], tag: str, key: str, observed: float, *, sign: int
) -> tuple[float, float]:
    """`(hardest null draw, z of real against the null draws)` for one contrast.

    `sign` is the direction the claim predicts, so the hardest arm is the draw
    that comes closest to producing the claimed effect by itself. Pooled over
    all three surrogate families, which is `hardest` in
    `node/surrogates.hardest`'s sense: the arm the real result beats by least.
    """
    draws = [
        d["contrasts"][tag][key]
        for arm_draws in nulls.values()
        for d in arm_draws
        if tag in d["contrasts"] and np.isfinite(d["contrasts"][tag][key])
    ]
    if not draws:
        return float("nan"), float("nan")
    hardest = max(draws) if sign > 0 else min(draws)
    sd = float(np.std(draws, ddof=1)) if len(draws) > 1 else 0.0
    z = sign * (observed - float(np.mean(draws))) / sd if sd > 0 else float("nan")
    return hardest, z


# ────────────────────────── the signal-conditioned run ──────────────────────


def anchored(arm: B.Arm, *, knobs: dict[str, Any] | None = None, queue=None) -> type:
    """A `Structure` leaf whose stop distance is `arm`'s, and nothing else.

    Built on the production rule rather than reimplemented, so the entries, the
    one-position slot, the 19:00-23:59 cut, the 96-bar clock, the sizing, the
    fills and the modelled spread are the reconciled rule's and only the stop
    differs - which is what `smc-bos-reconcile.md` had to correct four times to
    establish. `decide` delegates and replaces `Intent.stop`; `Intent.risk` is a
    property over `entry` and `stop`, so the sizer follows the new stop without
    a second place computing it.
    """
    import smc_bos_c_catalogue as S
    from till_infinity.strategies.entries import EdgeEntry
    from till_infinity.strategies.exits import ManagedExit
    from till_infinity.strategies.structure import Structure, StructureProfile

    profile = type(f"{arm.name}Profile", (StructureProfile,), dict(knobs or S.STACK[-1][1]))

    class Anchored(Structure):
        """The BOS rule with one of `stop_anchor_book`'s stops."""

        _arm: ClassVar[B.Arm] = arm
        _queue: ClassVar[Any] = queue

        def on_start(self) -> None:
            super().on_start()
            # 48, the `unit_span` `level_shield.SETTINGS` uses at 15m, so the
            # volatility unit here and in the geometry panel are one estimator.
            self.walker = B.Walker(unit_span=48)
            self.around: tuple[Any, ...] = (None, None, None, None)
            # Named `widths` and not `taken`: `Desk.on_data` keeps an int
            # counter called `taken` and shadowing it raises on the first
            # signal, which is a crash rather than a wrong number only
            # because `+=` on a list and on an int differ.
            self.widths: list[float] = []

        def on_bar(self, bar: Any) -> None:
            # Before `super()`, which is what fires the signal: the bar has
            # closed, so reading it is causal, and reading it *after* would
            # hand the decision a book that is one bar stale.
            self.walker.update(float(bar.high), float(bar.low))
            self.around = self.walker.around(float(bar.close), beyond=B.MIN_VOL)
            super().on_bar(bar)

        def decide(self, payload: dict[str, Any]) -> Any:
            found = super().decide(payload)
            if not isinstance(found, Intent):
                return found
            distance = self._distance(found)
            if distance is None or distance <= 0.0:
                # Dropped rather than fallen back on the volatility stop: a
                # mixture of two stop rules reported under one name is the
                # defect `one column, one unit` names, and the refusal rate is
                # the honest record of how often the book had nothing to say.
                from till_infinity.domain.models import Refusal

                return Refusal(gate="no-anchor", detail=self._arm.name, feed=found.feed)
            self.widths.append(distance / max(self.walker.unit, 1e-12))
            sign = found.side.sign
            return replace(
                found,
                stop=found.entry - sign * distance,
                features=found.features | {"anchor_vol": distance / max(self.walker.unit, 1e-12)},
            )

        def _distance(self, intent: Intent) -> float | None:
            side = intent.side.sign
            arm_ = self._arm
            unit = self.walker.unit
            if unit <= 0.0:
                return None
            if arm_.kind == "vol":
                return arm_.width * unit
            below, above, far_below, far_above = self.around
            near = below if side > 0 else above
            far = far_below if side > 0 else far_above
            found = near if arm_.pick == "near" else far
            if arm_.kind == "mirror":
                found = (above if side > 0 else below) if arm_.pick == "near" else (
                    far_above if side > 0 else far_below
                )
            if found is None:
                return None
            if arm_.kind == "matched":
                if not self._queue:
                    return None
                return self._queue.pop(0) * unit if self._queue else None
            if arm_.kind == "centre":
                anchor = found.centre
            elif arm_.kind == "mirror":
                anchor = found.high if side > 0 else found.low
            else:
                anchor = found.low if side > 0 else found.high
            # Absolute for `mirror` only, matching `stop_anchor_book.distances`
            # exactly. The mirror's anchor is on the **far** side of the entry,
            # so it contributes a *distance* placed on the trade's own side;
            # signing it gave every mirror trade a negative stop distance, and
            # the arm refused all 73 of them as `no-anchor` and reported `n 0`
            # rather than failing. A zero-trade arm reads as "the book had
            # nothing to say" and is indistinguishable from a sign error, which
            # is why this comment carries the trade count.
            gap = abs(intent.entry - anchor) if arm_.kind == "mirror" else (
                intent.entry - anchor
            ) * side
            return gap + arm_.buffer * unit

    return type(f"{arm.name}Edge", (Anchored, ManagedExit, EdgeEntry), {"profile": profile.__new__(profile)})


#: Arms the catalogue run carries. A subset, because 75 trades cannot separate
#: them and the value of this part is the cost and the mechanics, not the mean.
CATALOGUE_ARMS = (
    B.Arm("vol-2", "vol", width=2.0),
    B.Arm("near-floor+0.25", "floor", buffer=0.25, pick="near"),
    B.Arm("near-centre+0.25", "centre", buffer=0.25, pick="near"),
    B.Arm("beyond-floor+0.25", "floor", buffer=0.25, pick="beyond"),
    B.Arm("beyond-centre+0.25", "centre", buffer=0.25, pick="beyond"),
    B.Arm("beyond-mirror+0.25", "mirror", buffer=0.25, pick="beyond"),
    B.Arm("beyond-matched+0.25", "matched", buffer=0.25, pick="beyond"),
)


def catalogue(where: str, out_dir: Path) -> None:
    """The BOS rule over the recorded catalogue, stop arm by stop arm."""
    import smc_bos_c_catalogue as S

    loaded = S.load(where)
    if not loaded:
        print("nothing to run: the catalogue holds no instrument with both bars and quotes")
        return

    print("\n=== the machinery check: the rule's own ATR/N20 stop, unchanged ===")
    print("  reproduces research/docs/smc-bos-reconcile.md: -0.533R on n 75, per instrument")
    pooled: list[Any] = []
    for instrument, data in loaded:
        closed, _, _ = S.run_one(instrument, data, S.Arm("Baseline", dict(S.STACK[-1][1])))
        print(S.line(str(instrument.id.symbol), S.describe(closed, overshoot=False)))
        pooled.extend(closed)
    print(S.line("POOLED", S.describe(pooled, overshoot=False)))

    rows: dict[str, dict[str, Any]] = {}
    for arm in CATALOGUE_ARMS:
        print(f"\n=== {arm.name} ===")
        rows[arm.name] = {}
        pooled = []
        for instrument, data in loaded:
            closed, _, gates = _run_arm(S, instrument, data, arm)
            found = S.describe(closed, overshoot=False)
            # `Desk.consider` counts a refusal from `decide` as
            # `f"{self.label}:{gate}"`, so the key carries the strategy's own
            # label and a lookup on a fixed string silently reads zero - which
            # would report "the book always had an anchor" on an arm that in
            # fact never found one.
            found["no_anchor"] = sum(v for k, v in gates.items() if k.endswith(":no-anchor"))
            rows[arm.name][str(instrument.id.symbol)] = _trade_row(found)
            print(S.line(str(instrument.id.symbol), found) + f"  no-anchor {found['no_anchor']:>3}")
            pooled.extend(closed)
        whole = S.describe(pooled, overshoot=False)
        rows[arm.name]["POOLED"] = _trade_row(whole)
        print(S.line("POOLED", whole))

    keys = ["POOLED", *sorted(k for k in rows[CATALOGUE_ARMS[0].name] if k != "POOLED")]
    for label, field, fmt in (
        ("what the stop costs: cost_px / risk, set by the stop and by nothing else", "cost_r", "10.4f"),
        ("median stop distance in price", "risk_px", "10.5f"),
        ("per-trade sd in R - the sample each arm's own mean needs scales with this", "sd", "10.3f"),
        ("the sample this arm's own mean would need for two sigma", "n_needed", "10.0f"),
        ("profit factor, which is the verdict and is the same event as mean R > 0", "pf", "10.3f"),
        ("win rate - DESCRIPTIVE. A fall here is not a cost; see the payoff below", "win", "10.3f"),
        ("mean win in R", "mean_win", "10.3f"),
        ("mean loss in R", "mean_loss", "10.3f"),
    ):
        print(f"\n=== {label} ===")
        print(f"  {'arm':<20} " + "  ".join(f"{k[:9]:>10}" for k in keys))
        for name, found in rows.items():
            print(
                f"  {name:<20} "
                + "  ".join(format(found[k].get(field, float("nan")), fmt) for k in keys)
            )
    (out_dir / "catalogue.json").write_text(json.dumps(rows, indent=1, default=str))


def _trade_row(found: dict[str, Any]) -> dict[str, Any]:
    """`smc_bos_c_catalogue.describe` plus the metrics the verdict is read off.

    The day-block interval is `describe`'s own, over whole UTC days, because
    trades cluster in days and an ordinary standard error over 75 overlapping
    trades is far too narrow.
    """
    extra = metrics(np.asarray(found.get("r") or [], dtype=float), found.get("se", 0.0))
    return {k: v for k, v in (found | extra).items() if k not in ("r", "days")}


def _run_arm(S: Any, instrument: Any, data: list[Any], arm: B.Arm) -> tuple[Any, Any, Any]:
    """One instrument, one stop arm, through `smc_bos_c_catalogue`'s engine.

    The `matched` arm needs the distances the floor arm produced on this
    instrument, so it is a second pass over the same engine: the signal order
    is deterministic, which is what makes a pre-shuffled queue a permutation of
    the same trades rather than a different rule.
    """
    queue = None
    if arm.kind == "matched":
        floor = replace(arm, kind="floor", name=f"{arm.pick}-floor+{arm.buffer:g}")
        strategy = _engine(S, instrument, data, anchored(floor))
        queue = list(strategy.widths)
        random.Random(4_919).shuffle(queue)
    strategy = _engine(S, instrument, data, anchored(arm, queue=queue))
    return list(strategy.closed), dict(strategy.structure), dict(strategy.passed_over)


def _engine(S: Any, instrument: Any, data: list[Any], built: type) -> Any:
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, RiskEngineConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.enums import AccountType, OmsType
    from nautilus_trader.model.objects import Money

    from till_infinity.strategies.entries import EdgeEntryConfig

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="BACKTEST-001",
            logging=LoggingConfig(bypass_logging=True),
            risk_engine=RiskEngineConfig(bypass=False),
        )
    )
    engine.add_venue(
        venue=instrument.id.venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(S.EQUITY, USD)],
    )
    engine.add_instrument(instrument)
    engine.add_data(data)
    strategy = built(
        EdgeEntryConfig(
            instrument_id=instrument.id,
            bar_type=BarType.from_str(f"{instrument.id}-15-MINUTE-LAST-EXTERNAL"),
            order_id_tag="0001",
        )
    )
    engine.add_strategy(strategy)
    engine.run()
    engine.dispose()
    return strategy


# ───────────────────────────────── the power ─────────────────────────────────

#: Planted barrier strengths. 0 must read nothing, which is the control that
#: catches an estimator manufacturing a result out of estimation error.
STRENGTHS = (0.0, 0.10, 0.25, 0.50, 0.75, 1.00)


def plant_floors(
    series: L.Series, strength: float, rng: random.Random, *, span: int, clip: bool = False
) -> L.Series:
    """A walk whose own cluster book reflects it **at the floor**.

    `level_shield_power.plant_book` reflects at the level's Kalman centre,
    which plants the wrong effect for this question: the claim is that the
    *extreme* holds, so a barrier planted at the centre would be visible to the
    `centre` arm and not to `floor`, and the sweep would report the opposite
    blind point. Here the wall is every live cluster's floor and ceiling
    (`Walker.edges`), so the effect the test later looks for is the one that
    was planted - and planting at the *nearest* group alone would have missed
    the `beyond` arms, which anchor on the first cluster past `MIN_VOL`.

    `strength` 0 is a plain walk with this market's bar geometry and 1 is a
    book of hard walls at every cluster edge.

    **`clip` is the variant that matters, and the two apart are a result.**
    Without it the wall reflects the **close** path and each bar's high and low
    are still a resampled real range either side of that close - so a bar whose
    close never crosses a level still *prints* through it by up to a full bar
    range. Measured on eurusd 15m, a book of hard walls at `strength` 1.00
    recovers a stop-out difference of only -0.003, the same size as
    `strength` 0.00's +0.002: **a level that perfectly reflects the close path
    does not protect a stop at all**, because a stop is hit by the extreme and
    the nearest cluster is 0.43 volatility units away against a median bar
    range near one unit. `clip` plants the stronger claim - price may not
    *print* through the level - by clamping each bar's extremes at the nearest
    wall either side, which is the only form of the barrier a stop could use.
    """
    n = len(series.close)
    steps = np.diff(series.close)
    span_px = series.high - series.low
    safe = np.maximum(span_px, 1e-12)
    frac_o = np.where(span_px > 0, (series.open - series.low) / safe, 0.5)
    frac_c = np.where(span_px > 0, (series.close - series.low) / safe, 0.5)
    walker = B.Walker(unit_span=span)
    out = [np.empty(n) for _ in range(4)]
    price = float(series.close[0])
    for i in range(n):
        walls = walker.edges() if strength > 0.0 else []
        if i:
            want = price + float(steps[rng.randrange(len(steps))])
            for wall in sorted(walls, key=lambda w: abs(w - price)):
                if (price - wall) * (want - wall) < 0 and rng.random() < strength:
                    want = 2.0 * wall - want
                    break
            price = want
        k = rng.randrange(n)
        width = float(span_px[k])
        bottom = price - frac_c[k] * width
        top = bottom + width
        if clip and walls:
            under = [w for w in walls if w < price]
            over = [w for w in walls if w > price]
            if under and rng.random() < strength:
                bottom = max(bottom, max(under))
            if over and rng.random() < strength:
                top = min(top, min(over))
            # A clamp can invert the bar when both walls sit inside the
            # resampled range. Ordered rather than dropped, because a bar that
            # is not emitted would thin the series and the arms would be scored
            # on a shorter one at high strength than at low.
            bottom, top = min(bottom, price), max(top, price)
        out[3][i], out[2][i], out[1][i] = price, bottom, top
        out[0][i] = bottom + frac_o[k] * (top - bottom)
        walker.update(out[1][i], out[2][i])
    return L.Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=out[0],
        high=out[1],
        low=out[2],
        close=out[3],
    )


def power(feed: str, interval: str, draws: int, out_dir: Path) -> None:
    """The recovered floor-minus-matched contrast against planted strength.

    Two plants, and the pair is the result. `close` reflects the close path and
    leaves each bar's own range either side of it; `print` additionally clamps
    the extremes at the nearest wall, which is the only form of the barrier a
    stop placed just beyond a level could use - because a stop is hit by the
    extreme, not by the close.
    """
    arms = [a for a in B.arms() if a.buffer in (0.0, 0.25)]
    con = sqlite3.connect(L.STORE, uri=True)
    try:
        series = L.load(con, feed, interval)
    finally:
        con.close()
    if series is None:
        print(f"no series for {feed}.{interval}")
        return
    span = int(L.SETTINGS[interval]["unit_span"])
    print(f"\n=== power: a planted floor barrier on {feed}.{interval}, {len(series.close)} bars ===")
    print("  strength 0 must read nothing. The claim is a NEGATIVE dP(stop) on both sides.")
    print("  `close` reflects the close path; `print` also forbids the bar printing through.")
    print(
        f"  {'plant':>6} {'strength':>9} {'side':>4} {'dR':>9} {'dR|width':>9} "
        f"{'dP(stop)':>9} {'dP|width':>9}"
    )
    found: dict[str, Any] = {}
    for clip in (False, True):
        tag = "print" if clip else "close"
        for strength in STRENGTHS:
            per: dict[int, list[tuple[float, float, float, float]]] = defaultdict(list)
            for d in range(draws):
                made = plant_floors(
                    series, strength, random.Random(90_001 + d), span=span, clip=clip
                )
                got = summarise(one_series(made, interval, arms, seed=5 + d), seed=5 + d)
                for (side, arm, against), row in got["contrasts"].items():
                    if (arm, against) != ("beyond-floor+0.25", "beyond-matched+0.25"):
                        continue
                    per[side].append((row["d_r"], row["d_r_std"], row["d_p"], row["d_p_std"]))
            for side, values in sorted(per.items()):
                m = np.nanmean(np.asarray(values), axis=0)
                found[f"{tag}|{strength}|{side:+d}"] = m.tolist()
                print(
                    f"  {tag:>6} {strength:>9.2f} {side:>+4} {m[0]:>+9.4f} {m[1]:>+9.4f} "
                    f"{m[2]:>+9.4f} {m[3]:>+9.4f}"
                )
    (out_dir / "power.json").write_text(json.dumps(found, indent=1))


# ──────────────────────────────── the sanity ────────────────────────────────


def sanity() -> None:
    """The checks that make the rest of the numbers readable, each with its own
    failure. Run before any long job - `a-failed-sync-still-launches-the-run`.
    """
    from till_infinity.indicators.grouping import Anchor, cluster
    from till_infinity.indicators.trend import pivots

    groups = cluster([99.80, 99.95, 100.00, 100.02], 0.35, weights=[1, 3, 4, 2])
    assert len(groups) == 1, f"the worked example is one cluster, not {len(groups)}"
    centre = groups[0].price(Anchor.CENTRE)
    floor = groups[0].price(Anchor.FLOOR)
    assert abs(centre - 99.969) < 5e-4, centre
    assert abs(floor - 99.800) < 1e-9, floor
    print(f"  grouping worked example: centre {centre:.4f} against floor {floor:.4f} - ok")

    con = sqlite3.connect(L.STORE, uri=True)
    try:
        series = L.load(con, "eurusd", "1d")
    finally:
        con.close()
    assert series is not None
    walker = B.Walker(unit_span=20)
    mine: list[tuple[int, float, int]] = []
    for i in range(len(series.close)):
        for bar, price, side in walker.update(float(series.high[i]), float(series.low[i])):
            mine.append((bar - 1, round(price, 10), side))
    window = list(zip(series.high.tolist(), series.low.tolist(), series.ts.tolist(), strict=True))
    at = {t: i for i, t in enumerate(series.ts.tolist())}
    theirs = [(at[p.confirmed], round(p.price, 10), p.side) for p in pivots(window, B.BOOK_REACH)]
    assert sorted(mine) == sorted(theirs), (
        f"the walker found {len(mine)} pivots and trend.pivots {len(theirs)}: a book built "
        f"on a different turn is a different study, and the stop would be anchored on a "
        f"price nothing else here calls a level"
    )
    print(f"  Walker pivots == trend.pivots on {len(theirs)} confirmations over 19 years - ok")

    book = B.book_path(series.high, series.low, series.close, unit_span=20)
    assert np.allclose(book["near"].unit, L.units(series, 20)), (
        "the walker's volatility unit and level_shield.units have diverged: the two halves "
        "of this study would be measuring distances in different units"
    )
    print("  the walker's unit == level_shield.units - ok")

    unit = book["near"].unit
    near = (series.close - book["near"].below_low) / unit
    far = (series.close - book["beyond"].below_low) / unit
    print(
        f"  nearest floor below the close: {np.nanmedian(near):.3f} vol units; "
        f"first clearing {B.MIN_VOL:g}: {np.nanmedian(far):.3f}; "
        f"the incumbent is {B.MIN_VOL:g}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=OUT, help="directory for the written report")
    parser.add_argument("--geometry", action="store_true", help="the entry-agnostic panel")
    parser.add_argument("--catalogue", action="store_true", help="the BOS rule, net of spread")
    parser.add_argument("--power", action="store_true", help="the planted-floor sweep")
    parser.add_argument("--sanity", action="store_true", help="the correctness checks alone")
    parser.add_argument("--all", action="store_true", help="every part")
    parser.add_argument("--draws", type=int, default=DRAWS)
    parser.add_argument("--intervals", default="1d,15m")
    parser.add_argument("--catalogue-path", default="")
    args = parser.parse_args()

    os.environ.setdefault("LOG_LEVEL", "ERROR")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== sanity ===")
    sanity()
    if args.sanity and not args.all:
        return
    if args.geometry or args.all:
        geometry(tuple(args.intervals.split(",")), args.draws, out_dir)
    if args.catalogue or args.all:
        where = args.catalogue_path
        if not where:
            from till_infinity.node.backtest import catalogue as book_at

            where = str(book_at())
        print(f"\ncatalogue: {where}")
        catalogue(where, out_dir)
    if args.power or args.all:
        power("eurusd", "15m", min(3, args.draws), out_dir)


def report() -> None:
    """`main`, with everything it printed also written to `--out/report.txt`."""
    where = Path(
        next(
            (v for f, v in zip(sys.argv, sys.argv[1:], strict=False) if f == "--out"),
            OUT,
        )
    )
    where.mkdir(parents=True, exist_ok=True)
    with (where / "report.txt").open("w") as handle, contextlib.redirect_stdout(Tee(handle)):
        main()
    print(f"\nwritten to {where / 'report.txt'}")


if __name__ == "__main__":
    report()
